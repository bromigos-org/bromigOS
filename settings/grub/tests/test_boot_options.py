"""The installed system's "More ways to start" (11_bromigos-options) and the Field Kit entry
(42_bromigos-fieldkit, bromigos-fieldkit-boot), in a stand-in root, with a stand-in 10_linux
and grub-mkconfig, checked by the real grub-script-check where it's installed."""
import json
import sys
import os
import shutil
import stat
import subprocess
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
OPTIONS = HERE / "11_bromigos-options"
FIELDKIT = HERE / "42_bromigos-fieldkit"
HELPER = HERE / "bromigos-fieldkit-boot"

LINUX = """#!/bin/sh
cat <<EOF
menuentry 'bromigOS Linux' --class bromigos --class gnu-linux \\$menuentry_id_option 'gnulinux-simple-1234' {
\tload_video
\tinsmod btrfs
\tsearch --no-floppy --fs-uuid --set=root 1234
\techo 'Loading Linux linux ...'
\tlinux /vmlinuz-linux root=UUID=1234 rw rootflags=subvol=@ cryptdevice=PARTUUID=9:root $GRUB_CMDLINE_LINUX_DEFAULT
\tinitrd /intel-ucode.img /initramfs-linux.img
}
menuentry 'bromigOS Linux (fallback)' --class bromigos \\$menuentry_id_option 'gnulinux-fallback-1234' {
\tlinux /vmlinuz-linux $GRUB_CMDLINE_LINUX_DEFAULT
}
EOF
"""


def script(path, text):
    path.write_text(text)
    path.chmod(path.stat().st_mode | stat.S_IEXEC)


class Options(unittest.TestCase):
    def setUp(self):
        self.d = Path(tempfile.mkdtemp(prefix="bromigos-grub-options-"))
        self.addCleanup(shutil.rmtree, self.d, True)
        script(self.d / "10_linux", LINUX)
        self.sysfs = self.d / "sys"
        for addr, vendor, cls in (("0000:01:00.0", "0x10de", "0x030000"), ("0000:00:02.0", "0x8086", "0x030000"),
                                  ("0000:00:1f.0", "0x8086", "0x060100")):
            dev = self.sysfs / "bus/pci/devices" / addr
            dev.mkdir(parents=True)
            (dev / "vendor").write_text(vendor + "\n")
            (dev / "class").write_text(cls + "\n")
        self.lib = self.d / "lib"
        self.lib.mkdir()

    def run_options(self, default="loglevel=3 quiet splash"):
        env = dict(os.environ, GRUB_CMDLINE_LINUX_DEFAULT=default, BROMIGOS_GRUB_10_LINUX=str(self.d / "10_linux"),
                   BROMIGOS_SYSFS=str(self.sysfs), BROMIGOS_BOOT_LIB=str(self.lib))
        r = subprocess.run(["sh", str(OPTIONS)], env=env, capture_output=True, text=True, check=True)
        return r.stdout

    def test_presets_reuse_the_newest_entry_with_their_parameters(self):
        out = self.run_options()
        self.assertIn("submenu 'More ways to start ›'", out)
        self.assertIn("Start without the desktop (text mode)", out)
        text = out.split("bromigos-text")[1].split("menuentry")[0]
        self.assertIn("cryptdevice=PARTUUID=9:root loglevel=3 systemd.unit=multi-user.target", text)
        self.assertNotIn("quiet", text)
        self.assertIn("initrd /intel-ucode.img /initramfs-linux.img", text)
        safe = out.split("bromigos-safe")[1].split("menuentry")[0]
        self.assertIn("nomodeset", safe)
        # one per maker of a graphics card here: NVIDIA and Intel, not AMD
        self.assertIn("Start without the NVIDIA driver", out)
        self.assertIn("Start without the Intel driver", out)
        self.assertNotIn("Start without the AMD driver", out)
        self.assertIn("module_blacklist=nvidia,nvidia_drm,nvidia_modeset,nvidia_uvm,nouveau", out)
        self.assertIn("plymouth.enable=0", out)
        self.assertIn('configfile "${prefix}/grub-btrfs.cfg"', out)
        self.assertIn("themes/bromigos/colors.cfg", out)
        self.assertNotIn("fallback", out)
        self.assertIn("Help: what do these do?", out)

    @unittest.skipUnless(shutil.which("grub-script-check"), "grub-script-check (grub)")
    def test_grub_reads_it(self):
        cfg = self.d / "out.cfg"
        cfg.write_text(self.run_options())
        subprocess.run(["grub-script-check", str(cfg)], check=True)

    def test_without_10_linux_only_the_colours(self):
        (self.d / "10_linux").unlink()
        out = self.run_options()
        self.assertIn("colors.cfg", out)
        self.assertNotIn("submenu", out)


class FieldKitEntry(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="bromigos-fieldkit-boot-"))
        self.addCleanup(shutil.rmtree, self.root, True)
        (self.root / "boot/grub").mkdir(parents=True)
        (self.root / "boot/vmlinuz-linux").write_bytes(b"k" * 1000)
        (self.root / "boot/initramfs-linux.img").write_bytes(b"i" * 4000)
        self.bin = self.root / "bin"
        self.bin.mkdir()
        # stand-ins: grub-probe (the UUID), grub-mkconfig (writes what 42_ prints), grub-script-check
        script(self.bin / "grub-probe", "#!/bin/sh\necho 1A2B-3C4D\n")
        script(self.bin / "mkconfig", f"#!/bin/sh\nBROMIGOS_BOOT_LIB={self.root}/lib BROMIGOS_BOOT_ROOT={self.root} sh {FIELDKIT} > \"$2\"\n")
        script(self.bin / "check", "#!/bin/sh\nexit 0\n")
        (self.root / "boot/grub/grub.cfg").write_text("# old\n")
        self.lib = self.root / "lib"
        self.lib.mkdir()
        for f in ("bromigos-fieldkit-boot", "bromigos-boot-theme", "build-grub-theme.py"):
            shutil.copy(HERE / f, self.lib / f)

    def helper(self, *args):
        env = dict(os.environ, BROMIGOS_BOOT_ROOT=str(self.root), BROMIGOS_SYS_EFI=str(self.root / "no-efi"), PATH=f"{self.bin}:{os.environ['PATH']}",
                   BROMIGOS_GRUB_MKCONFIG=str(self.bin / "mkconfig"), BROMIGOS_GRUB_SCRIPT_CHECK=str(self.bin / "check"))
        return subprocess.run([sys.executable, "-I", str(self.lib / "bromigos-fieldkit-boot"), *args], env=env,
                              capture_output=True, text=True)

    def image(self, size):
        top = self.root / "usr/share/bromigos/fieldkit/boot"
        for rel, n in (("fieldkit/boot/x86_64/vmlinuz-linux", 1000), ("fieldkit/boot/x86_64/initramfs-linux.img", 2000),
                       ("fieldkit/x86_64/airootfs.sfs", size), ("fieldkit/boot-x1.id", 10),
                       ("EFI/bromigos-fieldkit/fieldkit.efi", 3000)):
            (top / rel).parent.mkdir(parents=True, exist_ok=True)
            (top / rel).write_bytes(b"\0" * n)
        (top / "fieldkit/cmdline").write_text("archisobasedir=fieldkit archisosearchfilename=/fieldkit/boot-x1.id module_blacklist=nouveau bromigos.fieldkit=disk\n")
        (self.root / "usr/share/bromigos/fieldkit/version").write_text("0.1.3\n")
        return top

    def test_no_image_no_entry(self):
        r = self.helper("sync")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertFalse((self.root / "boot/fieldkit").exists())

    def test_copied_and_in_the_menu_then_gone_with_the_package(self):
        self.image(1 << 20)
        r = self.helper("sync")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue((self.root / "boot/fieldkit/x86_64/airootfs.sfs").is_file())
        cfg = (self.root / "boot/grub/grub.cfg").read_text()
        self.assertIn("--id 'bromigos-fieldkit'", cfg)
        self.assertIn("linux /fieldkit/boot/x86_64/vmlinuz-linux archisobasedir=fieldkit archisosearchfilename=/fieldkit/boot-x1.id", cfg)
        self.assertIn("bromigOS Field Kit 0.1.3 (repair, lab and tools)", cfg)
        self.assertIn("initrd /fieldkit/boot/x86_64/initramfs-linux.img", cfg)
        st = json.loads(self.helper("status", "--json").stdout)
        self.assertEqual(st["status"], "ready")
        shutil.rmtree(self.root / "usr/share/bromigos/fieldkit/boot")
        (self.root / "usr/share/bromigos/fieldkit/boot").mkdir()
        self.helper("sync")
        self.assertFalse((self.root / "boot/fieldkit").exists())
        self.assertNotIn("bromigos-fieldkit", (self.root / "boot/grub/grub.cfg").read_text())

    def test_no_room_says_so_and_changes_nothing(self):
        st = os.statvfs(self.root)
        # a stand-in: a huge initramfs makes the room needed more than what's free
        big = self.root / "boot/initramfs-linux-fallback.img"
        with open(big, "wb") as f:
            f.truncate(st.f_bavail * st.f_frsize + (1 << 30))
        self.image(1 << 20)
        r = self.helper("sync")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("not enough room on /boot", r.stdout)
        self.assertFalse((self.root / "boot/fieldkit/x86_64/airootfs.sfs").exists())
        self.assertEqual(json.loads(self.helper("status", "--json").stdout)["status"], "no-room")

    def test_not_grub(self):
        (self.root / "boot/grub/grub.cfg").unlink()
        self.image(1000)
        r = self.helper("sync")
        self.assertIn("isn't GRUB's", r.stdout)

    def test_firmware_entry_added_last_and_removed(self):
        """UEFI with /boot as the ESP: the UKI is copied and the entry made, at the end of the order."""
        (self.root / "sys-efi").mkdir()
        (self.root / "boot/EFI").mkdir()
        log = self.root / "efibootmgr.log"
        script(self.bin / "efibootmgr", f'''#!/bin/sh
echo "$@" >> {log}
state={self.root}/efi.state
[ -f "$state" ] || printf 'BootOrder: 0001,0002\nBoot0001* bromigOS\nBoot0002* UEFI Shell\n' > "$state"
case "$1" in
  --create) printf 'Boot0005* bromigOS Field Kit\tHD(...)\n' >> "$state"; sed -i 's/^BootOrder: /BootOrder: 0005,/' "$state" ;;
  --bootorder) sed -i "s/^BootOrder: .*/BootOrder: $2/" "$state" ;;
  --bootnum) sed -i "/^Boot$2/d" "$state" ;;
esac
cat "$state"
''')
        script(self.bin / "findmnt", "#!/bin/sh\necho /dev/vda1\n")
        self.image(1 << 20)
        env_efi = {"BROMIGOS_SYS_EFI": str(self.root / "sys-efi"), "BROMIGOS_EFIBOOTMGR": str(self.bin / "efibootmgr")}
        r = self.helper_env(env_efi, "sync")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue((self.root / "boot/EFI/bromigos-fieldkit/fieldkit.efi").is_file())
        calls = log.read_text()
        if "/sys/class/block/vda1" and os.path.exists("/sys/class/block/vda1"):
            self.assertIn("--create", calls)
            self.assertIn("--bootorder 0001,0002,0005", calls)
        r = self.helper_env(env_efi, "remove")
        self.assertFalse((self.root / "boot/EFI/bromigos-fieldkit").exists())

    def helper_env(self, extra, *args):
        env = dict(os.environ, BROMIGOS_BOOT_ROOT=str(self.root), PATH=f"{self.bin}:{os.environ['PATH']}",
                   BROMIGOS_GRUB_MKCONFIG=str(self.bin / "mkconfig"), BROMIGOS_GRUB_SCRIPT_CHECK=str(self.bin / "check"), **extra)
        return subprocess.run([sys.executable, "-I", str(self.lib / "bromigos-fieldkit-boot"), *args], env=env,
                              capture_output=True, text=True)


if __name__ == "__main__":
    unittest.main()
