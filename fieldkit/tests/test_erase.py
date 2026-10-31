"""Erasing a drive, with stand-in tools and a file for a drive: what each drive offers, the
type-its-name guard, the drives it refuses, and the report it leaves."""
import os
import shutil
import stat
import tempfile
import unittest

from bromigos_fieldkit import erase, imaging, system


def stub(bindir, name, body):
    path = os.path.join(bindir, name)
    with open(path, "w") as f:
        f.write("#!/bin/bash\necho \"%s $*\" >> \"$STUB_LOG\"\n" % name + body + "\n")
    os.chmod(path, os.stat(path).st_mode | stat.S_IEXEC)


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="fk-erase-")
        self.bin = os.path.join(self.tmp, "bin")
        os.makedirs(self.bin)
        self.log = os.path.join(self.tmp, "log")
        open(self.log, "w").close()
        self.env = {k: os.environ.get(k) for k in ("PATH", "STUB_LOG")}
        os.environ["PATH"] = self.bin + ":" + os.environ["PATH"]
        os.environ["STUB_LOG"] = self.log
        self.saved = (erase.RUN, erase.STICK_LABEL)
        erase.RUN = os.path.join(self.tmp, "run")
        erase.STICK_LABEL = os.path.join(self.tmp, "no-stick")
        self.dev = os.path.join(self.tmp, "sdb")
        with open(self.dev, "wb") as f:
            f.write(os.urandom(256 * 1024))
        stub(self.bin, "lsblk", f'''case "$*" in
  *MODEL,SERIAL*) echo '{{"blockdevices":[{{"model":"Stand-in SSD","serial":"SN123","tran":"sata","rota":false}}]}}' ;;
  *DISC-MAX*) echo 0 ;;
  *) : ;;
esac''')
        stub(self.bin, "blockdev", "echo 262144")
        stub(self.bin, "findmnt", ":")
        stub(self.bin, "hdparm", 'echo "Security:"; echo "	not	supported"')

    def tearDown(self):
        erase.RUN, erase.STICK_LABEL = self.saved
        for k, v in self.env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        shutil.rmtree(self.tmp)


class Plan(Base):
    def test_nvme_offers_its_own_erase_first(self):
        stub(self.bin, "nvme", '''echo '{"sanicap": 3, "fna": 4}' ''')
        p = erase.plan("/dev/nvme0n1")
        self.assertEqual([m["id"] for m in p["methods"]][:4],
                         ["nvme-sanitize-crypto", "nvme-sanitize-block", "nvme-format-crypto", "nvme-format"])
        self.assertEqual(p["recommended"], "nvme-sanitize-crypto")

    def test_ata_frozen_says_how_to_unfreeze(self):
        stub(self.bin, "hdparm", 'printf "Security:\\n\\tMaster password revision code = 65534\\n\\tsupported\\n\\tnot\\tenabled\\n\\tnot\\tlocked\\n\\t\\tfrozen\\n"')
        p = erase.plan(self.dev)
        self.assertNotIn("ata-secure-erase", [m["id"] for m in p["methods"]])
        self.assertTrue(any("frozen" in n for n in p["notes"]))

    def test_ata_enhanced_erase(self):
        stub(self.bin, "hdparm", 'printf "Security:\\n\\tsupported\\n\\tnot\\tenabled\\n\\tnot\\tfrozen\\n\\tsupported: enhanced erase\\n"')
        p = erase.plan(self.dev)
        self.assertEqual([m["id"] for m in p["methods"]][:2], ["ata-secure-erase-enhanced", "ata-secure-erase"])

    def test_fallback_is_an_overwrite(self):
        p = erase.plan(self.dev)
        self.assertIn(p["recommended"], ("zero", "nwipe"))


class Run(Base):
    def test_the_name_must_be_typed(self):
        with self.assertRaisesRegex(system.Failed, "type its name"):
            erase.run_erase(self.dev, "sda", "zero", lambda *a: None)
        self.assertNotIn("dd ", imaging.slurp(self.log))

    def test_a_mounted_drive_is_refused(self):
        stub(self.bin, "lsblk", 'case "$*" in *MOUNTPOINTS*) echo /home ;; *) : ;; esac')
        with self.assertRaisesRegex(system.Failed, "in use"):
            erase.run_erase(self.dev, "sdb", "zero", lambda *a: None)

    def test_the_boot_drive_is_refused(self):
        stub(self.bin, "findmnt", f'echo {self.dev}')
        with self.assertRaisesRegex(system.Failed, "started from"):
            erase.run_erase(self.dev, "sdb", "zero", lambda *a: None)

    def test_an_unoffered_method_is_refused(self):
        with self.assertRaisesRegex(system.Failed, "can't be erased with"):
            erase.run_erase(self.dev, "sdb", "nvme-format", lambda *a: None)

    def test_zero_pass_and_its_report(self):
        # dd, stood in: fills the "drive" with zeros as the real one would
        stub(self.bin, "dd", '''of=; for a in "$@"; do case $a in of=*) of=${a#of=} ;; esac; done
python3 -c "import os,sys; n=os.path.getsize(sys.argv[1]); open(sys.argv[1],'r+b').write(bytes(n))" "$of"
echo "262144 bytes (262 kB) copied, 0.1 s, 2.6 MB/s" >&2''')
        os.environ["PATH"] = self.bin + ":/usr/bin"          # no nwipe: the dd pass
        lines = []
        r = erase.run_erase(self.dev, "sdb", "zero", lambda p, line: lines.append(line))
        self.assertTrue(r["ok"], r)
        self.assertTrue(r["report"].startswith(os.path.join(self.tmp, "run", "reports")))
        text = imaging.slurp(r["report"])
        for want in ("Stand-in SSD", "SN123", "Method:    zero", "Result:    erased", "all zeros"):
            self.assertIn(want, text)
        self.assertNotIn("FAILED", text)

    def test_a_failed_erase_still_leaves_a_report(self):
        stub(self.bin, "dd", 'echo "dd: error writing: No space left" >&2; exit 1')
        os.environ["PATH"] = self.bin + ":/usr/bin"
        r = erase.run_erase(self.dev, "sdb", "zero", lambda *a: None)
        self.assertFalse(r["ok"])
        self.assertIn("FAILED", imaging.slurp(r["report"]))


class Commands(unittest.TestCase):
    def test_each_method(self):
        self.assertIn("--sanact=4", erase.command("/dev/nvme0n1", "nvme-sanitize-crypto", "l"))
        self.assertIn("--ses=2", erase.command("/dev/nvme0n1", "nvme-format-crypto", "l"))
        self.assertIn("--security-erase-enhanced bromigos", erase.command("/dev/sda", "ata-secure-erase-enhanced", "l"))
        self.assertIn("--security-set-pass bromigos", erase.command("/dev/sda", "ata-secure-erase", "l"))
        self.assertIn("blkdiscard --secure -f /dev/sda", erase.command("/dev/sda", "blkdiscard-secure", "l"))
        self.assertIn("--method=zero --rounds=1 --verify=last", erase.command("/dev/sda", "nwipe", "l"))
        with self.assertRaises(system.Failed):
            erase.command("/dev/sda", "magic", "l")


if __name__ == "__main__":
    unittest.main()
