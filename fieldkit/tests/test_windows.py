"""Windows repair with stand-in tools: the firmware's boot entries, putting one first, adding
Windows Boot Manager back, a password cleared (with the accounts file kept first), and the
BitLocker key's shape checked before anything runs."""
import os
import shutil
import stat
import tempfile
import unittest

from bromigos_fieldkit import imaging, system, windows

ENTRIES = """BootCurrent: 0001
Timeout: 1 seconds
BootOrder: 0001,0000,0002
Boot0000* Windows Boot Manager	HD(1,GPT,aaaa,0x800,0x100000)/File(\\EFI\\Microsoft\\Boot\\bootmgfw.efi)
Boot0001* bromigOS	HD(1,GPT,aaaa,0x800,0x100000)/File(\\EFI\\bromigOS\\grubx64.efi)
Boot0002  UEFI: PXE IPv4	PciRoot(0x0)/Pci(0x2,0x0)/MAC(525400123456,1)
"""


def stub(bindir, name, body):
    path = os.path.join(bindir, name)
    with open(path, "w") as f:
        f.write("#!/bin/bash\necho \"%s $*\" >> \"$STUB_LOG\"\n" % name + body + "\n")
    os.chmod(path, os.stat(path).st_mode | stat.S_IEXEC)


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="fk-win-")
        self.bin = os.path.join(self.tmp, "bin")
        os.makedirs(self.bin)
        self.log = os.path.join(self.tmp, "log")
        open(self.log, "w").close()
        self.env = {k: os.environ.get(k) for k in ("PATH", "STUB_LOG", "STUB_TMP")}
        os.environ["PATH"] = self.bin + ":" + os.environ["PATH"]
        os.environ["STUB_LOG"] = self.log
        os.environ["STUB_TMP"] = self.tmp
        self.saved = windows.RUN
        windows.RUN = os.path.join(self.tmp, "run")
        os.makedirs(windows.RUN)
        with open(os.path.join(self.tmp, "entries"), "w") as f:
            f.write(ENTRIES)
        stub(self.bin, "efibootmgr", 'case "$*" in -v) cat "$STUB_TMP/entries" ;; *) : ;; esac')
        for t in ("sync", "umount", "findmnt"):
            stub(self.bin, t, ":")

    def tearDown(self):
        windows.RUN = self.saved
        for k, v in self.env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        shutil.rmtree(self.tmp)

    def logged(self):
        return imaging.slurp(self.log)


class Boot(Base):
    def test_entries(self):
        st = windows.boot_entries()
        self.assertEqual(st["order"], ["0001", "0000", "0002"])
        win = [e for e in st["entries"] if e["windows"]]
        self.assertEqual([e["num"] for e in win], ["0000"])
        self.assertEqual([e["num"] for e in st["entries"] if e["bromigos"]], ["0001"])
        self.assertFalse(st["entries"][2]["active"])

    def test_windows_first_keeps_the_old_list(self):
        r = windows.boot_fix(False, "windows")
        self.assertTrue(r["ok"], r)
        self.assertIn("efibootmgr --bootorder 0000,0001,0002", self.logged())
        self.assertIn("Windows Boot Manager", imaging.slurp(r["saved"]))

    def test_readd_windows_boot_manager(self):
        with open(os.path.join(self.tmp, "entries"), "w") as f:
            f.write("BootOrder: 0001\nBoot0001* bromigOS\tHD(1,GPT)/File(\\EFI\\bromigOS\\grubx64.efi)\n")
        esp = os.path.join(self.tmp, "esp")
        os.makedirs(os.path.join(esp, "EFI", "Microsoft", "Boot"))
        open(os.path.join(esp, "EFI", "Microsoft", "Boot", "bootmgfw.efi"), "w").close()
        stub(self.bin, "lsblk", f'''case "$*" in
  *-J*) echo '{{"blockdevices":[{{"name":"sda","path":"/dev/sda","type":"disk","size":1,"children":[{{"name":"sda1","path":"/dev/sda1","fstype":"vfat","type":"part","size":1,"mountpoints":["{esp}"]}}]}}]}}' ;;
  *PKNAME*) echo sda ;;
esac''')
        r = windows.boot_fix(True, None)
        self.assertTrue(r["ok"], r)
        self.assertIn("efibootmgr --create --disk /dev/sda --part 1 --label Windows Boot Manager --loader \\EFI\\Microsoft\\Boot\\bootmgfw.efi",
                      self.logged())

    def test_no_uefi(self):
        stub(self.bin, "efibootmgr", "echo 'EFI variables are not supported on this system.' >&2; exit 2")
        with self.assertRaisesRegex(system.Failed, "UEFI"):
            windows.boot_fix(True, "windows")


class Accounts(Base):
    def setUp(self):
        super().setUp()
        self.win = os.path.join(self.tmp, "c")
        os.makedirs(os.path.join(self.win, "Windows", "System32", "config"))
        with open(os.path.join(self.win, "Windows", "System32", "config", "SAM"), "w") as f:
            f.write("hive")
        # "mounting" copies the stand-in Windows into the mount folder; the folder is the last argument
        for t in ("mount", "ntfs-3g"):
            stub(self.bin, t, f'cp -r "{self.win}/." "${{@: -1}}/"')
        stub(self.bin, "lsblk", ":")

    def test_users(self):
        stub(self.bin, "chntpw", '''cat <<'EOF'
| RID -|---------- Username ------------| Admin? |- Lock? --|
| 01f4 | Administrator                  | ADMIN  | dis/lock |
| 03e9 | alice                          | ADMIN  |          |
EOF''')
        r = windows.users("/dev/sda3")
        self.assertEqual([(u["name"], u["admin"], u["locked"]) for u in r["users"]],
                         [("Administrator", True, True), ("alice", True, False)])

    def test_reset_password_keeps_the_hive_first(self):
        stub(self.bin, "chntpw", 'cat > "$STUB_TMP/answers"; echo "Password cleared!"; echo "SAM - OK"')
        r = windows.reset_password("/dev/sda3", "alice")
        self.assertTrue(r["ok"], r)
        self.assertIn("Microsoft account", r["warning"])
        self.assertIn("chntpw -u alice", self.logged())
        self.assertEqual(imaging.slurp(os.path.join(self.tmp, "answers")), "1\nq\ny\n")
        kept = [f for f in os.listdir(os.path.join(windows.RUN, "reports")) if f.startswith("SAM.bromigos-fieldkit-")]
        self.assertEqual(len(kept), 1)

    def test_reset_password_says_when_it_didnt(self):
        stub(self.bin, "chntpw", 'echo "User alice not found"')
        with self.assertRaisesRegex(system.Failed, "didn't clear"):
            windows.reset_password("/dev/sda3", "alice")

    def test_fast_startup_is_explained(self):
        stub(self.bin, "ntfs-3g", 'echo "The disk contains an unclean file system (0, 0). Windows is hibernated, refused to mount." >&2; exit 14')
        with self.assertRaisesRegex(system.Failed, "Fast Startup"):
            windows.reset_password("/dev/sda3", "alice")


class BitLocker(Base):
    def test_the_key_must_look_like_one(self):
        with self.assertRaisesRegex(system.Failed, "48 digits"):
            windows.unlock_bitlocker("/dev/sda3", "1234")
        self.assertNotIn("dislocker", self.logged())

    def test_unlock_read_only(self):
        stub(self.bin, "dislocker-fuse", ":")
        stub(self.bin, "mount", ":")
        key = "-".join(["123456"] * 8)
        r = windows.unlock_bitlocker("/dev/sda3", key + "\n")
        self.assertTrue(r["ok"], r)
        self.assertIn("dislocker-fuse -r -V /dev/sda3 -p" + key, self.logged())
        self.assertIn("mount -o loop,ro", self.logged())


if __name__ == "__main__":
    unittest.main()
