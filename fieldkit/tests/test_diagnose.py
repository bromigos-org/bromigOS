"""Field Kit's black screen and boot checks on a stand-in install (no root, no real disks)."""
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from bromigos_fieldkit import diagnose, repairs, system


def tree(files):
    root = Path(tempfile.mkdtemp(prefix="fieldkit-test-"))
    for rel, text in files.items():
        p = root / rel.lstrip("/")
        p.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(text, tuple):            # a symlink
            os.symlink(text[0], p)
        else:
            p.write_text(text)
    return root


PASSWD = "root:x:0:0::/root:/bin/zsh\nann:x:1000:1000::/home/ann:/bin/zsh\n"


class BlackScreen(unittest.TestCase):
    def target(self, files):
        files.setdefault("/etc/passwd", PASSWD)
        root = tree(files)
        return system.Target(str(root))

    def test_renamed_sddm_dropin_is_still_read_and_moved_out_with_a_backup(self):
        t = self.target({"/etc/sddm.conf.d/10-gpu.conf.disabled": "[Wayland]\nCompositorCommand=weston --drm-device=card1\n"})
        found = [f for f in diagnose.sddm_dropins(t) if not f.ok]
        self.assertEqual(len(found), 1)
        self.assertIn("reads every file", found[0].detail)
        msg = found[0].fix(t)
        self.assertFalse(Path(t.path("/etc/sddm.conf.d/10-gpu.conf.disabled")).exists())
        backups = list(Path(t.path(system.BACKUPS)).rglob("10-gpu.conf.disabled"))
        self.assertEqual(len(backups), 1)
        self.assertIn("Moved", msg)

    def test_plain_conf_without_risky_settings_passes(self):
        t = self.target({"/etc/sddm.conf.d/kde.conf": "[Theme]\nCursorTheme=breeze\n"})
        self.assertTrue(all(f.ok for f in diagnose.sddm_dropins(t)))

    def test_package_name_in_modules_is_found_and_corrected(self):
        t = self.target({
            "/etc/mkinitcpio.conf": "MODULES=(nvidia-open nvidia_drm)\nHOOKS=(base udev)\n",
            "/usr/lib/modules/7.2.11-arch1-1/pkgbase": "linux\n",
            "/usr/lib/modules/7.2.11-arch1-1/modules.dep": "kernel/drivers/video/nvidia.ko.zst:\nkernel/drivers/video/nvidia-drm.ko.zst:\n",
        })
        found = [f for f in diagnose.mkinitcpio(t) if not f.ok]
        self.assertEqual(len(found), 1)
        self.assertIn("nvidia-open is a package", found[0].detail)
        with mock.patch.object(diagnose, "rebuild_initramfs", return_value="built."):
            found[0].fix(t)
        self.assertIn("MODULES=(nvidia nvidia_drm)", Path(t.path("/etc/mkinitcpio.conf")).read_text())

    def test_pin_to_card_without_monitor(self):
        t = self.target({"/home/ann/.local/state/bromigos/hw/hyprland.lua":
                         'return { env = { { "AQ_DRM_DEVICES", "/dev/dri/by-path/pci-0000:01:00.0-card", when = {} } } }\n'})
        with mock.patch.object(diagnose, "connected_cards", return_value={"0000:01:00.0": [], "0000:00:02.0": ["eDP-1"]}):
            found = [f for f in diagnose.gpu_pins(t) if not f.ok]
        self.assertEqual(len(found), 1)
        self.assertIn("0000:00:02.0", found[0].detail)
        found[0].fix(t)
        self.assertIn("Field Kit took this out", Path(t.path("/home/ann/.local/state/bromigos/hw/hyprland.lua")).read_text())

    def test_nvidia_module_missing_for_kernel(self):
        t = self.target({"/usr/lib/modules/7.2.11-arch1-1/pkgbase": "linux\n",
                         "/usr/lib/modules/7.2.11-arch1-1/modules.dep": "kernel/fs/btrfs.ko.zst:\n"})
        with mock.patch.object(diagnose, "installed_packages", return_value={"nvidia-open-dkms": "590-1"}):
            found = [f for f in diagnose.drivers(t) if not f.ok]
        self.assertEqual(len(found), 1)
        self.assertIn("DKMS", found[0].detail)

    def test_no_display_manager(self):
        t = self.target({"/etc/systemd/system/default.target": ("/usr/lib/systemd/system/multi-user.target",),
                         "/usr/bin/sddm": ""})
        found = [f for f in diagnose.display_manager(t) if not f.ok]
        self.assertEqual(len(found), 2)


    def test_server_without_a_desktop_is_fine(self):
        t = self.target({"/etc/systemd/system/default.target": ("/usr/lib/systemd/system/multi-user.target",)})
        self.assertTrue(all(f.ok for f in diagnose.display_manager(t)))


class BootOptions(unittest.TestCase):
    def test_read_and_write_keep_a_backup_and_put_it_back_on_failure(self):
        root = tree({"/etc/default/grub": 'GRUB_TIMEOUT=5\nGRUB_CMDLINE_LINUX_DEFAULT="loglevel=3 quiet splash"\n'})
        t = system.Target(str(root))
        self.assertEqual(repairs.boot_options(t), ["loglevel=3", "quiet", "splash"])
        with mock.patch.object(repairs, "make_grub_cfg", side_effect=system.Failed("no")):
            with self.assertRaises(system.Failed):
                repairs.set_boot_options(t, ["quiet", "nomodeset"])
        self.assertIn('"loglevel=3 quiet splash"', Path(t.path("/etc/default/grub")).read_text())
        with mock.patch.object(repairs, "make_grub_cfg", return_value="made."):
            repairs.set_boot_options(t, ["quiet", "nomodeset"])
        self.assertIn('GRUB_CMDLINE_LINUX_DEFAULT="quiet nomodeset"', Path(t.path("/etc/default/grub")).read_text())


class Snapshots(unittest.TestCase):
    def test_lists_snapper_snapshots_newest_first(self):
        info = "<snapshot><type>{t}</type><num>{n}</num><date>2026-10-30 10:0{n}:00</date><description>{d}</description></snapshot>"
        top = tree({f"/@.snapshots/{n}/info.xml": info.format(t=k, n=n, d=d) for n, k, d in
                    ((1, "pre", "bromigos update"), (2, "post", "bromigos update"))})
        for n in (1, 2):
            (top / f"@.snapshots/{n}/snapshot").mkdir()
        t = system.Target("/mnt/none", top=str(top))
        snaps = repairs.snapshots(t)
        self.assertEqual([s.number for s in snaps], [2, 1])
        self.assertIn("bromigos update", snaps[0].title())


if __name__ == "__main__":
    unittest.main()
