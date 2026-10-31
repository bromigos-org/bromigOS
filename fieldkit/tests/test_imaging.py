"""Disk images in Clonezilla's format, with stand-in disk tools (no real disk is touched): the
image's files, the pieces' names, the checks before a restore, and the table moved to another disk."""
import glob
import os
import shutil
import stat
import tempfile
import unittest

from bromigos_fieldkit import imaging, system


def stub(bindir, name, body):
    path = os.path.join(bindir, name)
    with open(path, "w") as f:
        f.write("#!/bin/bash\necho \"%s $*\" >> \"$STUB_LOG\"\n" % name + body + "\n")
    os.chmod(path, os.stat(path).st_mode | stat.S_IEXEC)


class Stubbed(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="fk-img-")
        self.bin = os.path.join(self.tmp, "bin")
        os.makedirs(self.bin)
        self.log = os.path.join(self.tmp, "log")
        open(self.log, "w").close()
        self.env = {k: os.environ.get(k) for k in ("PATH", "STUB_LOG", "STUB_TMP")}
        os.environ["PATH"] = self.bin + ":" + os.environ["PATH"]
        os.environ["STUB_LOG"] = self.log
        os.environ["STUB_TMP"] = self.tmp
        self.run_dir = os.path.join(self.tmp, "run")
        os.makedirs(self.run_dir)
        self.saved_run = imaging.RUN
        imaging.RUN = self.run_dir
        self.lines = []

    def tearDown(self):
        imaging.RUN = self.saved_run
        for k, v in self.env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        shutil.rmtree(self.tmp)

    def progress(self, pct, line):
        self.lines.append((pct, line))

    def logged(self):
        return imaging.slurp(self.log)


class Create(Stubbed):
    def setUp(self):
        super().setUp()
        d = self.tmp
        self.disk = os.path.join(d, "sda")
        with open(self.disk, "wb") as f:
            f.write(b"\xeb\x63" + b"\x00" * 508 + b"\x55\xaa" + b"\x11" * (2047 * 512) + b"\x00" * (4 << 20))
        for p in ("sda1", "sda2"):
            open(os.path.join(d, p), "wb").close()
        stub(self.bin, "lsblk", 'case "$*" in *"-ndo TYPE"*) echo disk ;; *KNAME*) echo "KNAME NAME" ;; *) : ;; esac')
        stub(self.bin, "sfdisk", f'cat <<EOF\nlabel: dos\ndevice: {self.disk}\nunit: sectors\n\n'
                                 f'{self.disk}1 : start=        2048, size=        4096, type=83\n'
                                 f'{self.disk}2 : start=        6144, size=        2048, type=7\nEOF')
        stub(self.bin, "blkid", 'case "$*" in *PTTYPE*) echo dos ;; *"TYPE"*sda1) echo ext4 ;; *"TYPE"*sda2) echo ;; *) echo "/dev/x: TYPE=\\"ext4\\"" ;; esac')
        stub(self.bin, "blockdev", "echo 8388608")
        stub(self.bin, "parted", "echo Model: stand-in")
        for tool in ("partclone.ext4", "partclone.dd"):
            stub(self.bin, tool, 'echo "Completed: 50.00%" >&2; printf "PARTCLONE-IMAGE %s" "$*"; echo "Completed: 100.00%" >&2')
        stub(self.bin, "partclone.chkimg", 'cat >/dev/null; echo "Completed: 100.00%" >&2')
        for t in ("dmidecode", "lspci", "findmnt", "sgdisk"):
            stub(self.bin, t, ":")

    def test_whole_disk_in_clonezillas_layout(self):
        dest = os.path.join(self.tmp, "images")
        os.makedirs(dest)
        r = imaging.create(self.disk, dest, "test-img", True, self.progress)
        self.assertTrue(r["ok"], r)
        d = os.path.join(dest, "test-img")
        self.assertEqual(imaging.slurp(os.path.join(d, "disk")).split(), ["sda"])
        self.assertEqual(imaging.slurp(os.path.join(d, "parts")).split(), ["sda1", "sda2"])
        for f in ("sda-pt.sf", "sda-pt.parted", "sda-mbr", "sda-hidden-data-after-mbr", "blkdev.list", "blkid.list",
                  "dev-fs.list", "Info-saved-by-cmd.txt", "Info-dmi.txt", "clonezilla-img",
                  "sda1.ext4-ptcl-img.zst.aa", "sda2.dd-ptcl-img.zst.aa"):
            self.assertTrue(os.path.isfile(os.path.join(d, f)), f)
        self.assertEqual(os.path.getsize(os.path.join(d, "sda-mbr")), 512)
        self.assertEqual(os.path.getsize(os.path.join(d, "sda-hidden-data-after-mbr")), 2047 * 512)
        self.assertIn("/dev/sda1 ext4", imaging.slurp(os.path.join(d, "dev-fs.list")))
        log = self.logged()
        self.assertRegex(log, r"partclone\.ext4 -z 10485760 -L \S+ -c -s \S+sda1 --output -")
        self.assertIn("partclone.dd", log)                    # no file system: sector by sector
        self.assertEqual(log.count("partclone.chkimg"), 2)     # checked after writing
        self.assertTrue(r["verified"])
        self.assertTrue(any(p == 50.0 for p, _ in self.lines))
        # it reads back as an image, as Clonezilla's and Rescuezilla's do
        found = imaging.list_images([dest])
        self.assertEqual([i["name"] for i in found], ["test-img"])
        self.assertEqual(found[0]["filesystems"], {"sda1": "ext4", "sda2": "dd"})
        self.assertEqual(found[0]["made_by"], "Field Kit")

    def test_a_mounted_source_is_refused(self):
        stub(self.bin, "lsblk", 'case "$*" in *MOUNTPOINTS*) echo /mnt/x ;; *"-ndo TYPE"*) echo disk ;; esac')
        with self.assertRaises(system.Failed):
            imaging.create(self.disk, self.tmp, "x", False, self.progress)


class Clonezillas(Stubbed):
    def make_cz_image(self, name="2026-01-01-img"):
        d = os.path.join(self.tmp, "partimag", name)
        os.makedirs(d)
        open(os.path.join(d, "disk"), "w").write("sda\n")
        open(os.path.join(d, "parts"), "w").write("sda1\n")
        open(os.path.join(d, "sda-pt.sf"), "w").write(
            "label: gpt\ndevice: /dev/sda\nunit: sectors\nlast-lba: 20000\n\n/dev/sda1 : start= 2048, size= 16000, type=0FC63DAF\n")
        open(os.path.join(d, "sda1.ext4-ptcl-img.gz.aa"), "wb").write(b"x")
        open(os.path.join(d, "clonezilla-img"), "w").write("saved by Clonezilla\n")
        return d

    def test_lists_a_clonezilla_image(self):
        d = self.make_cz_image()
        found = imaging.list_images([os.path.dirname(d)])
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0]["filesystems"], {"sda1": "ext4"})
        self.assertEqual(found[0]["made_by"], "Clonezilla or Rescuezilla")

    def test_restore_guards(self):
        d = self.make_cz_image()
        target = os.path.join(self.tmp, "sdb")
        open(target, "wb").close()
        for t in ("lsblk", "findmnt"):
            stub(self.bin, t, ":")
        stub(self.bin, "blockdev", "echo 1048576")            # 1 MiB: smaller than the image needs
        with self.assertRaisesRegex(system.Failed, "type its name"):
            imaging.restore(d, target, "sdc", self.progress)
        with self.assertRaisesRegex(system.Failed, "smaller"):
            imaging.restore(d, target, "sdb", self.progress)
        self.assertNotIn("sfdisk", self.logged())

    def test_restore_writes_the_table_then_each_partition(self):
        d = self.make_cz_image()
        target = os.path.join(self.tmp, "sdb")
        open(target, "wb").close()
        for t in ("lsblk", "findmnt", "partprobe", "udevadm"):
            stub(self.bin, t, ":")
        stub(self.bin, "blockdev", "echo 107374182400")
        stub(self.bin, "sfdisk", 'cat > "$STUB_TMP/table.in"')
        stub(self.bin, "gzip", "cat >/dev/null")
        stub(self.bin, "partclone.ext4", 'echo "Completed: 100.00%" >&2')
        r = imaging.restore(d, target, "sdb", self.progress)
        self.assertTrue(r["ok"], r)
        table = imaging.slurp(os.path.join(self.tmp, "table.in"))
        self.assertNotIn("last-lba", table)
        self.assertNotIn("device:", table)
        self.assertIn(f"{target}1 :", table)
        self.assertRegex(self.logged(), r"partclone\.ext4 -z 10485760 -r -s - -o \S+sdb1")


class Names(unittest.TestCase):
    def test_partition_names(self):
        self.assertEqual(imaging.part_path("/dev/sda", 2), "/dev/sda2")
        self.assertEqual(imaging.part_path("/dev/nvme0n1", 1), "/dev/nvme0n1p1")
        self.assertEqual(imaging.part_path("/dev/mmcblk0", 3), "/dev/mmcblk0p3")

    def test_piece_names(self):
        for ok in ("sda1.ext4-ptcl-img.zst.aa", "nvme0n1p2.ntfs-ptcl-img.gz.ab", "sdb3.dd-ptcl-img.zst.aa"):
            self.assertTrue(imaging.IMG.match(ok), ok)
        self.assertFalse(imaging.IMG.match("sda-pt.sf"))

    def test_tools(self):
        self.assertEqual(imaging.tool_for("ext4"), ("partclone.ext4", "ext4"))
        self.assertEqual(imaging.tool_for("crypto_LUKS"), ("partclone.dd", "dd"))
        self.assertEqual(imaging.tool_for(""), ("partclone.dd", "dd"))

    def test_table_needs(self):
        self.assertEqual(imaging.table_end_bytes("label: dos\n/dev/sda1 : start= 2048, size= 2048, type=83\n"), 4096 * 512)
        self.assertEqual(imaging.table_end_bytes("label: gpt\n/dev/sda1 : start= 2048, size= 2048, type=x\n"), (4096 + 33) * 512)


class Engine(unittest.TestCase):
    def test_bad_requests_are_words(self):
        with self.assertRaises(ValueError):
            imaging.engine(["restore", "--image", "x"], lambda *a: None)
        with self.assertRaises(ValueError):
            imaging.engine(["nonsense"], lambda *a: None)


if __name__ == "__main__":
    unittest.main()
