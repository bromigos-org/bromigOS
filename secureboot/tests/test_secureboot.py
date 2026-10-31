"""bromigos-secureboot (docs/secureboot.md) in a stand-in root: the firmware's variables, the
EFI system partition, efibootmgr, mokutil and grub-mkconfig are stand-ins; openssl, sbsign,
sbverify and grub-mkimage are the real ones (the tests that need them skip without them).
Nothing outside a temporary directory is read or written."""

import json
import os
import shutil
import stat
import struct
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
HELPER = os.path.join(HERE, "..", "bromigos-secureboot")
MODULES = os.path.join(HERE, "..", "grub-modules.txt")
GRUB_LIB = "/usr/lib/grub/x86_64-efi"
HAVE_SIGNING = all(shutil.which(t) for t in ("sbsign", "sbverify", "openssl", "grub-mkimage")) and \
    os.path.isfile(os.path.join(GRUB_LIB, "linux.mod"))

# efibootmgr's stand-in: the boot entries in a JSON file, printed the way efibootmgr -v does
FAKE_EFIBOOTMGR = r'''#!/usr/bin/env python3
import json, os, sys
db = os.environ["FAKE_EFI_DB"]
st = json.load(open(db))
a = sys.argv[1:]
log = open(db + ".log", "a"); log.write(" ".join(a) + "\n"); log.close()
def opt(name):
    return a[a.index(name) + 1] if name in a else None
if "--create" in a:
    n = "%04X" % (max([int(k, 16) for k in st["entries"]] or [0]) + 1)
    flags = {"--disk", "--part", "--label", "--loader", "--index", "--append-binary-args"}
    extra, i = [], 0
    while i < len(a):
        if a[i] in flags: i += 2; continue
        if a[i].startswith("-"): i += 1; continue
        extra.append(a[i]); i += 1
    if "--append-binary-args" in a:
        raw = open(opt("--append-binary-args"), "rb").read()
        assert raw.endswith(b"\0\0"), "shim needs the second stage's path to end in a NUL"
        extra.append(raw[:-2].decode("utf-16-le"))
    st["entries"][n] = {"label": opt("--label"), "loader": opt("--loader"), "args": " ".join(extra), "disk": opt("--disk"), "part": opt("--part")}
    idx = int(opt("--index") or 0)
    st["order"].insert(idx, n)
elif "--delete-bootnum" in a:
    n = opt("--bootnum").upper()
    st["entries"].pop(n, None)
    st["order"] = [x for x in st["order"] if x != n]
elif "--bootorder" in a:
    st["order"] = opt("--bootorder").split(",")
else:
    print("BootCurrent: 0001")
    print("BootOrder: " + ",".join(st["order"]))
    for n, e in sorted(st["entries"].items()):
        print("Boot%s* %s\tHD(1,GPT,0000,0x800,0x100000)/File(%s)%s" % (n, e["label"], e["loader"], ("  " + e["args"]) if e["args"] else ""))
json.dump(st, open(db, "w"))
'''

FAKE_MOKUTIL = r'''#!/usr/bin/env python3
import json, os, sys
db = os.environ["FAKE_MOK_DB"]
st = json.load(open(db)) if os.path.exists(db) else {"enrolled": [], "pending": []}
a = sys.argv[1:]
open(db + ".log", "a").write(" ".join(a) + "\n")
def fp(p): return open(p, "rb").read().hex()[:64]
if a[0].startswith("--generate-hash="):
    print("$6$fakesalt$" + a[0].split("=", 1)[1])
elif a[0] == "--test-key":
    k = fp(a[1])
    if k in st["enrolled"]: print(a[1] + " is already enrolled")
    elif k in st["pending"]: print(a[1] + " is already in the enrollment request")
    else: print(a[1] + " is not enrolled"); sys.exit(0)
elif a[0] == "--import":
    assert "--hash-file" in a and open(a[a.index("--hash-file") + 1]).read().startswith("$6$")
    st["pending"].append(fp(a[1]))
json.dump(st, open(db, "w"))
'''

FAKE_MKCONFIG = r'''#!/bin/sh
# grub-mkconfig's stand-in: a loadfont line for each font in the theme, as 00_header writes
out=$2
{ echo "### stand-in grub.cfg"; for f in "$FAKE_ROOT"/boot/grub/themes/bromigos/*.pf2; do [ -f "$f" ] && echo "loadfont $f"; done; } > "$out"
exit 0
'''


def write(path, data, mode=0o644):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb" if isinstance(data, bytes) else "w") as f:
        f.write(data)
    os.chmod(path, mode)


def rb(path):
    with open(path, "rb") as f:
        return f.read()


def jload(path):
    with open(path) as f:
        return json.load(f)


def jdump(doc, path):
    with open(path, "w") as f:
        json.dump(doc, f)


def kernel_bytes(version):
    """Enough of a bzImage for the version reader: the setup header's HdrS and the pointer
    to the version string (a real PE comes from grub-mkimage when signing is tested)."""
    b = bytearray(0x3000)
    b[0x202:0x206] = b"HdrS"
    struct.pack_into("<H", b, 0x20E, 0x1000)
    v = f"{version} (linux@archlinux) #1 SMP".encode()
    b[0x1200:0x1200 + len(v)] = v
    return bytes(b)


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="bromigos-sb-test-")
        self.root = os.path.join(self.tmp, "root")
        self.bin = os.path.join(self.tmp, "bin")
        self.efi = os.path.join(self.tmp, "sysefi")
        os.makedirs(os.path.join(self.efi, "efivars"))
        self.set_secure_boot(1)
        write(os.path.join(self.bin, "efibootmgr"), FAKE_EFIBOOTMGR, 0o755)
        write(os.path.join(self.bin, "mokutil"), FAKE_MOKUTIL, 0o755)
        write(os.path.join(self.bin, "grub-mkconfig"), FAKE_MKCONFIG, 0o755)
        write(os.path.join(self.bin, "grub-script-check"), "#!/bin/sh\nexit 0\n", 0o755)
        write(os.path.join(self.bin, "grub-probe"), "#!/bin/sh\necho 1234-ABCD\n", 0o755)
        write(os.path.join(self.bin, "grub-mkrelpath"), "#!/bin/sh\necho /grub\n", 0o755)
        self.efidb = os.path.join(self.tmp, "efi.json")
        jdump({"entries": {"0000": {"label": "Windows Boot Manager", "loader": r"\EFI\Microsoft\Boot\bootmgfw.efi", "args": ""},
                               "0001": {"label": "GRUB", "loader": r"\EFI\GRUB\grubx64.efi", "args": ""}},
                   "order": ["0001", "0000"]}, self.efidb)
        self.mokdb = os.path.join(self.tmp, "mok.json")
        # the installed system: /boot is the EFI system partition (the installer's layout)
        boot = os.path.join(self.root, "boot")
        write(os.path.join(boot, "grub", "grub.cfg"), "### the old menu\n")
        write(os.path.join(boot, "EFI", "GRUB", "grubx64.efi"), b"GRUB stand-in")
        for n in ("geist-mono-regular-16", "geist-mono-bold-16"):
            write(os.path.join(self.root, "usr/share/bromigos/boot/grub/fonts", n + ".pf2"), b"PFF2 " + n.encode())
            write(os.path.join(boot, "grub/themes/bromigos", n + ".pf2"), b"PFF2 " + n.encode())
        write(os.path.join(boot, "grub/themes/bromigos/theme.txt"), "title-text: \"\"\n")
        share = os.path.join(self.root, "usr/share/bromigos/secureboot")
        os.makedirs(share)
        shutil.copy(MODULES, share)
        if os.path.isdir(GRUB_LIB):
            os.makedirs(os.path.dirname(os.path.join(self.root, GRUB_LIB.lstrip("/"))), exist_ok=True)
            os.symlink(GRUB_LIB, os.path.join(self.root, GRUB_LIB.lstrip("/")))
        if os.path.isfile("/usr/share/grub/sbat.csv"):
            write(os.path.join(self.root, "usr/share/grub/sbat.csv"), rb("/usr/share/grub/sbat.csv"))

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def set_secure_boot(self, on):
        write(os.path.join(self.efi, "efivars", "SecureBoot-8be4df61-93ca-11d2-aa0d-00e098032b8c"), bytes([6, 0, 0, 0, on]))

    def env(self):
        e = dict(os.environ, BROMIGOS_SB_ROOT=self.root, BROMIGOS_SB_SYS_EFI=self.efi, BROMIGOS_SB_ESP="/boot",
                 BROMIGOS_SB_ESP_DISK="/dev/vda:1", FAKE_EFI_DB=self.efidb, FAKE_MOK_DB=self.mokdb, FAKE_ROOT=self.root)
        for t in ("efibootmgr", "mokutil", "grub-mkconfig", "grub-script-check", "grub-probe", "grub-mkrelpath", "mkinitcpio"):
            e["BROMIGOS_SB_" + t.upper().replace("-", "_")] = os.path.join(self.bin, t)
        return e

    def sb(self, *args, check=True):
        r = subprocess.run([sys.executable, HELPER, *args], capture_output=True, text=True, env=self.env())
        if check and r.returncode != 0:
            self.fail(f"bromigos-secureboot {' '.join(args)}: {r.returncode}\n{r.stdout}\n{r.stderr}")
        return r

    def at(self, path):
        return os.path.join(self.root, path.lstrip("/"))

    def efi_state(self):
        return jload(self.efidb)

    def verify(self, path):
        crt = self.at("/var/lib/bromigos/secureboot/machine.crt")
        return subprocess.run(["sbverify", "--cert", crt, path], capture_output=True).returncode == 0


class TestNoSigning(Base):
    def test_status_not_set_up(self):
        doc = json.loads(self.sb("status", "--json").stdout)
        self.assertFalse(doc["set_up"])
        self.assertEqual(doc["secure_boot"], "on")
        self.assertIn("sudo bromigos secureboot setup", doc["summary"])

    def test_bios(self):
        shutil.rmtree(self.efi)
        doc = json.loads(self.sb("status", "--json").stdout)
        self.assertEqual(doc["firmware"], "bios")
        r = self.sb("setup", check=False)
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("BIOS", r.stderr)

    def test_hooks_do_nothing_when_not_set_up(self):
        for verb in ("hook-pre", "hook-post", "hook-remove"):
            self.assertEqual(self.sb(verb).returncode, 0)
        self.sb("initcpio-post", self.at("/boot/vmlinuz-linux"))
        self.assertFalse(os.path.exists(self.at("/var/lib/bromigos/secureboot/state.json")))

    def test_code_must_be_digits(self):
        r = self.sb("setup", "--code", "abcd", check=False)
        self.assertEqual(r.returncode, 2)

    def test_hook_remove_refuses_while_needed(self):
        write(self.at("/var/lib/bromigos/secureboot/state.json"), json.dumps({"status": "ready"}))
        self.assertEqual(self.sb("hook-remove", check=False).returncode, 1)
        self.set_secure_boot(0)
        self.assertEqual(self.sb("hook-remove").returncode, 0)


@unittest.skipUnless(HAVE_SIGNING, "needs openssl, sbsigntools and grub's x86_64-efi modules")
class TestSetUp(Base):
    def setUp(self):
        super().setUp()
        write(os.path.join(self.root, "usr/share/bromigos/secureboot/shimx64.efi"), b"shim stand-in")
        write(os.path.join(self.root, "usr/share/bromigos/secureboot/mmx64.efi"), b"MokManager stand-in")
        # a real PE for a kernel: a GRUB image, with a bzImage's setup header written into its
        # DOS stub's unused bytes would break it, so the version test uses kernel_bytes()
        pe = os.path.join(self.tmp, "pe.efi")
        subprocess.run(["grub-mkimage", "-O", "x86_64-efi", "-d", GRUB_LIB, "-o", pe, "-p", "/x", "normal"], check=True)
        self.pe = rb(pe)
        write(self.at("/boot/vmlinuz-linux"), self.pe)
        write(self.at("/boot/initramfs-linux.img"), b"initramfs")
        write(self.at("/boot/fieldkit/boot/x86_64/vmlinuz-linux"), self.pe)
        write(self.at("/boot/EFI/bromigos-fieldkit/fieldkit.efi"), self.pe)
        st = self.efi_state()
        st["entries"]["0002"] = {"label": "bromigOS Field Kit", "loader": r"\EFI\bromigos-fieldkit\fieldkit.efi", "args": ""}
        st["order"].append("0002")
        jdump(st, self.efidb)

    def test_setup(self):
        r = self.sb("setup", "--fresh-install", "--code", "4827")
        self.assertIn("type the code 4827", r.stdout)
        keys = self.at("/var/lib/bromigos/secureboot/keys")
        self.assertEqual(stat.S_IMODE(os.stat(keys).st_mode), 0o700)
        self.assertEqual(stat.S_IMODE(os.stat(os.path.join(keys, "machine.key")).st_mode), 0o600)
        self.assertNotIn("PRIVATE", r.stdout + r.stderr)
        d = self.at("/boot/EFI/bromigos-secureboot")
        self.assertEqual(rb(os.path.join(d, "shimx64.efi")), b"shim stand-in")
        self.assertTrue(os.path.isfile(os.path.join(d, "mmx64.efi")))
        self.assertTrue(os.path.isfile(os.path.join(d, "ENROLL_THIS_KEY_FOR_THIS_PC.cer")))
        grub = rb(os.path.join(d, "grubx64.efi"))
        self.assertIn(b"fonts/geist-mono-regular-16.pf2", grub)            # the memdisk
        self.assertIn(b"search --no-floppy --fs-uuid --set=root 1234-ABCD", grub)
        self.assertIn(b"for f in geist-mono-bold-16 geist-mono-regular-16; do loadfont $f; done", grub)
        self.assertIn(b"source $prefix/grub.cfg", grub)
        for p in ("/boot/EFI/bromigos-secureboot/grubx64.efi", "/boot/vmlinuz-linux",
                  "/boot/fieldkit/boot/x86_64/vmlinuz-linux", "/boot/EFI/bromigos-fieldkit/fieldkit.efi"):
            self.assertTrue(self.verify(self.at(p)), p)
        # no Windows on this disk, and the fallback path was empty: shim there too
        self.assertEqual(rb(self.at("/boot/EFI/BOOT/BOOTX64.EFI")), b"shim stand-in")
        efi = self.efi_state()
        mine = [n for n, e in efi["entries"].items() if e["label"] == "bromigOS"]
        self.assertEqual(len(mine), 1)
        self.assertEqual(efi["order"][0], mine[0])
        self.assertNotIn("0001", efi["entries"])                            # the installer's GRUB entry
        self.assertIn("0000", efi["order"])                                 # Windows' stays
        fk = [e for e in efi["entries"].values() if e["label"] == "bromigOS Field Kit"]
        self.assertEqual(len(fk), 1)
        self.assertEqual(fk[0]["loader"], r"\EFI\bromigos-secureboot\shimx64.efi")
        self.assertEqual(fk[0]["args"], r"\EFI\bromigos-fieldkit\fieldkit.efi")
        self.assertEqual(efi["order"][-1], [n for n, e in efi["entries"].items() if e["label"] == "bromigOS Field Kit"][0])
        # the key asked for, with the code; the theme's fonts out of /boot, grub.cfg without them
        self.assertEqual(len(jload(self.mokdb)["pending"]), 1)
        self.assertEqual(rb(os.path.join(keys, "enroll-code")).decode().strip(), "4827")
        self.assertEqual([n for n in os.listdir(self.at("/boot/grub/themes/bromigos")) if n.endswith(".pf2")], [])
        self.assertNotIn("loadfont", rb(self.at("/boot/grub/grub.cfg")).decode())
        doc = json.loads(self.sb("status", "--json").stdout)
        self.assertTrue(doc["set_up"])
        self.assertEqual(doc["mok"], "pending")
        self.assertEqual(doc["code"], "4827")
        self.assertIn("4827", doc["summary"])
        self.assertEqual(doc["problems"], [])
        self.assertTrue(doc["entry"]["first"])
        # setup again changes nothing and asks for nothing new
        self.sb("setup")
        self.assertEqual(len(jload(self.mokdb)["pending"]), 1)
        self.assertEqual(len([e for e in self.efi_state()["entries"].values() if e["label"] == "bromigOS"]), 1)

    def test_theme_helper_leaves_fonts_out(self):
        self.sb("setup", "--code", "1111")
        sys.path.insert(0, os.path.join(HERE, "..", "..", "settings", "grub"))
        import importlib.machinery
        import importlib.util
        path = os.path.join(HERE, "..", "..", "settings", "grub", "bromigos-boot-theme")
        os.environ["BROMIGOS_BOOT_ROOT"] = self.root
        try:
            loader = importlib.machinery.SourceFileLoader("bbt", path)
            spec = importlib.util.spec_from_loader("bbt", loader)
            mod = importlib.util.module_from_spec(spec)
            loader.exec_module(mod)
            self.assertTrue(mod.fonts_in_grub())
        finally:
            del os.environ["BROMIGOS_BOOT_ROOT"]

    def test_installers_removable_grub_replaced(self):
        # grub-install --removable: GRUB itself at the fallback path, no Windows on the disk
        grub = os.path.join(self.tmp, "removable.efi")
        subprocess.run(["grub-mkimage", "-O", "x86_64-efi", "-d", GRUB_LIB, "-o", grub, "-p", "/x", "normal"], check=True)
        write(self.at("/boot/EFI/BOOT/BOOTX64.EFI"), rb(grub))
        self.sb("setup", "--code", "1234")
        self.assertEqual(rb(self.at("/boot/EFI/BOOT/BOOTX64.EFI")), b"shim stand-in")
        self.assertTrue(self.verify(self.at("/boot/EFI/BOOT/grubx64.efi")))

    def test_windows_esp_untouched(self):
        win = self.at("/boot/EFI/Microsoft/Boot/bootmgfw.efi")
        write(win, b"Windows boot manager")
        write(self.at("/boot/EFI/BOOT/BOOTX64.EFI"), b"Windows fallback")
        self.sb("setup", "--code", "1234")
        self.assertEqual(rb(win), b"Windows boot manager")
        self.assertEqual(rb(self.at("/boot/EFI/BOOT/BOOTX64.EFI")), b"Windows fallback")
        self.assertFalse(os.path.exists(self.at("/boot/EFI/BOOT/grubx64.efi")))
        efi = self.efi_state()
        self.assertEqual(efi["entries"]["0000"]["label"], "Windows Boot Manager")
        self.assertIn("0000", efi["order"])

    def test_kernel_update_resigned(self):
        self.sb("setup", "--code", "1234")
        write(self.at("/boot/vmlinuz-linux"), self.pe)                     # mkinitcpio copied a new one
        self.assertFalse(self.verify(self.at("/boot/vmlinuz-linux")))
        self.sb("initcpio-post", self.at("/boot/vmlinuz-linux"), self.at("/boot/initramfs-linux.img"))
        self.assertTrue(self.verify(self.at("/boot/vmlinuz-linux")))
        write(self.at("/boot/vmlinuz-linux"), self.pe)
        self.sb("hook-post")
        self.assertTrue(self.verify(self.at("/boot/vmlinuz-linux")))
        self.assertEqual(jload(self.at("/var/lib/bromigos/secureboot/state.json"))["status"], "ready")

    def test_failed_signing_puts_the_old_kernel_back(self):
        self.sb("setup", "--code", "1234")
        old = rb(self.at("/boot/vmlinuz-linux"))
        self.sb("hook-pre")
        self.assertEqual(rb(self.at("/var/lib/bromigos/secureboot/last-good/linux/vmlinuz")), old)
        # the update: a new kernel that can't be signed (not a PE at all)
        write(self.at("/usr/lib/modules/6.2.0-arch1-1/pkgbase"), "linux\n")
        write(self.at("/usr/lib/modules/6.2.0-arch1-1/vmlinuz"), b"not a PE image")
        write(self.at("/boot/vmlinuz-linux"), b"not a PE image")
        write(self.at("/boot/initramfs-linux.img"), b"new initramfs")
        r = self.sb("hook-post")
        self.assertEqual(r.returncode, 0)                                     # never fails pacman
        self.assertIn("WARNING", r.stderr)
        self.assertIn("kernel from before this update is back", r.stderr)
        self.assertEqual(rb(self.at("/boot/vmlinuz-linux")), old)
        self.assertEqual(rb(self.at("/boot/initramfs-linux.img")), b"initramfs")
        st = jload(self.at("/var/lib/bromigos/secureboot/state.json"))
        self.assertEqual(st["status"], "failed")
        self.assertEqual(st["put_back"], ["linux"])
        doc = json.loads(self.sb("status", "--json").stdout)
        self.assertIn("resign", doc["summary"])
        # fixed (a signable kernel this time): resign puts the update's kernel in /boot again,
        # makes its initramfs and signs it
        write(self.at("/usr/lib/modules/6.2.0-arch1-1/vmlinuz"), self.pe)
        write(os.path.join(self.bin, "mkinitcpio"), "#!/bin/sh\necho made > \"$FAKE_ROOT/boot/initramfs-$2.img\"\n", 0o755)
        self.sb("resign")
        self.assertTrue(self.verify(self.at("/boot/vmlinuz-linux")))
        self.assertEqual(rb(self.at("/boot/initramfs-linux.img")).decode().strip(), "made")
        st = jload(self.at("/var/lib/bromigos/secureboot/state.json"))
        self.assertEqual((st["status"], st.get("put_back")), ("ready", []))
        self.assertFalse(os.path.exists(self.at("/var/lib/bromigos/secureboot/last-good")))

    def test_kernel_version(self):
        write(self.at("/usr/lib/modules/6.17.5-arch1-1/pkgbase"), "linux\n")
        write(self.at("/boot/vmlinuz-x"), kernel_bytes("6.17.5-arch1-1"))
        code = ("import importlib.machinery, importlib.util, sys; "
                "l = importlib.machinery.SourceFileLoader('h', sys.argv[1]); s = importlib.util.spec_from_loader('h', l); "
                "m = importlib.util.module_from_spec(s); l.exec_module(m); print(m.kernel_of(sys.argv[2]))")
        r = subprocess.run([sys.executable, "-c", code, HELPER, self.at("/boot/vmlinuz-x")], capture_output=True,
                           text=True, env=self.env())
        self.assertEqual(r.stdout.strip(), "6.17.5-arch1-1")

    def test_remove(self):
        self.sb("setup", "--code", "1234")
        self.sb("remove", "--dry-run")
        self.assertTrue(os.path.isdir(self.at("/boot/EFI/bromigos-secureboot")))
        self.sb("remove")
        self.assertFalse(os.path.isdir(self.at("/boot/EFI/bromigos-secureboot")))
        efi = self.efi_state()
        self.assertFalse([e for e in efi["entries"].values() if e["label"] == "bromigOS"])
        self.assertTrue(os.path.isfile(self.at("/boot/grub/themes/bromigos/geist-mono-regular-16.pf2")))
        self.assertTrue(os.path.isfile(self.at("/var/lib/bromigos/secureboot/keys/machine.key")))
        doc = json.loads(self.sb("status", "--json").stdout)
        self.assertFalse(doc["set_up"])
        self.sb("setup", "--code", "1234")                                   # the same key again
        self.assertEqual(len(jload(self.mokdb)["pending"]), 1)

    def test_dry_run_changes_nothing(self):
        before = self.efi_state()
        r = self.sb("setup", "--dry-run")
        self.assertIn("would", r.stdout)
        self.assertEqual(self.efi_state(), before)
        self.assertFalse(os.path.exists(self.at("/boot/EFI/bromigos-secureboot")))
        self.assertFalse(os.path.exists(self.at("/var/lib/bromigos/secureboot/keys")))
        self.assertTrue(os.path.isfile(self.at("/boot/grub/themes/bromigos/geist-mono-regular-16.pf2")))


if __name__ == "__main__":
    unittest.main()
