"""Field Kit's black screen and boot checks on a stand-in install (no root, no real disks)."""
import os
import shutil
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


def bzimage(version):
    """A kernel image as far as its header goes: the version string where the header points."""
    head = bytearray(0x400)
    head[0x202:0x206] = b"HdrS"
    head[0x20E:0x210] = (0x100).to_bytes(2, "little")
    text = f"{version} (linux@archlinux) #1 SMP".encode() + b"\0"
    head[0x300:0x300 + len(text)] = text
    return bytes(head)


NEW, OLD, OLDEST = "7.2.15-arch1-1", "7.2.11-arch1-1", "6.10.5-arch1-1"
WITH_NVIDIA = "kernel/fs/btrfs.ko.zst:\nextramodules/nvidia.ko.zst:\n"
WITHOUT = "kernel/fs/btrfs.ko.zst:\n"


class Kernels(unittest.TestCase):
    """Which folders in /usr/lib/modules are the install's kernels: the ones a package owns. A
    removed kernel's folder can stay behind, whole, and must not be checked for a driver."""

    def target(self, kernels, boot=()):
        """kernels: {version: modules.dep}; each folder whole (pkgbase, vmlinuz, modules.dep), as a
        left-behind one is too. Plus an older leftover with one stray file and no pkgbase."""
        files = {"/var/lib/pacman/local/ALPM_DB_VERSION": "9\n",
                 f"/usr/lib/modules/{OLDEST}/modules.weakdep": ""}
        for ver, dep in kernels.items():
            files[f"/usr/lib/modules/{ver}/pkgbase"] = "linux\n"
            files[f"/usr/lib/modules/{ver}/vmlinuz"] = ""
            files[f"/usr/lib/modules/{ver}/modules.dep"] = dep
        t = system.Target(str(tree(files)))
        for name, version in boot:
            p = Path(t.path(f"/boot/{name}"))
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(bzimage(version))
        return t

    def look(self, t, owned=(), packages=None):
        """(kernels, the driver findings that aren't fine, the leftover notes), with pacman's
        answers stood in: the install's packages own the folders of the versions in `owned`."""
        def owns(target, rel):
            self.assertIs(target, t)
            return any(f"/{v}/" in rel for v in owned)
        with mock.patch.object(diagnose, "owned", side_effect=owns), \
                mock.patch.object(diagnose, "installed_packages",
                                  return_value=packages or {"nvidia-open": "595.58.03-2"}):
            return (diagnose.kernels(t), [f for f in diagnose.drivers(t) if not f.ok],
                    diagnose.leftover_kernels(t))

    def test_a_folder_left_behind_is_not_a_kernel(self):
        # the kernel went 7.2.11 -> 7.2.15; the driver is built for 7.2.15; 7.2.11's folder stayed
        t = self.target({NEW: WITH_NVIDIA, OLD: WITHOUT}, boot=[("vmlinuz-linux", NEW)])
        kernels, bad, notes = self.look(t, owned=[NEW])
        self.assertEqual(kernels, {NEW: "linux"})
        self.assertEqual(bad, [])
        # it is said, once, with the command that removes it, and nothing is removed
        self.assertEqual([n.title for n in notes], [f"A kernel folder was left behind: /usr/lib/modules/{OLD}"])
        self.assertTrue(notes[0].ok)
        self.assertIsNone(notes[0].fix)
        self.assertIn(f"rm -r {t.path('/usr/lib/modules/' + OLD)}", notes[0].detail)
        self.assertNotIn("sudo", notes[0].detail)          # Field Kit, on a mounted install, is root
        self.assertTrue(Path(t.path(f"/usr/lib/modules/{OLD}/vmlinuz")).exists())

    def test_an_installed_kernel_without_the_driver_is_raised(self):
        t = self.target({NEW: WITHOUT}, boot=[("vmlinuz-linux", NEW)])
        kernels, bad, notes = self.look(t, owned=[NEW])
        self.assertEqual([f.title for f in bad], [f"The NVIDIA driver isn't built for the kernel {NEW}"])
        self.assertIn("prebuilt driver is for a different kernel", bad[0].detail)
        self.assertEqual(notes, [])

    def test_an_installed_kernel_with_the_driver_is_quiet(self):
        t = self.target({NEW: WITH_NVIDIA}, boot=[("vmlinuz-linux", NEW)])
        kernels, bad, notes = self.look(t, owned=[NEW])
        self.assertEqual((kernels, bad, notes), ({NEW: "linux"}, [], []))

    def test_both_at_once_only_the_installed_kernel_is_raised(self):
        t = self.target({NEW: WITHOUT, OLD: WITHOUT}, boot=[("vmlinuz-linux", NEW)])
        kernels, bad, notes = self.look(t, owned=[NEW], packages={"nvidia-open-dkms": "595.58.03-2"})
        self.assertEqual([f.title for f in bad], [f"The NVIDIA driver isn't built for the kernel {NEW}"])
        self.assertEqual(bad[0].commands[0], "arch-chroot {root} dkms autoinstall -k " + NEW)
        self.assertEqual(len(notes), 1)
        self.assertIn(OLD, notes[0].title)

    def test_the_leftover_does_not_reach_the_other_checks(self):
        # the module list is checked against installed kernels only, and a rollback picks the
        # installed kernel for /boot, not the left-behind one of the same package
        t = self.target({NEW: WITHOUT, OLD: WITH_NVIDIA}, boot=[("vmlinuz-linux", NEW)])
        Path(t.path("/etc")).mkdir()
        Path(t.path("/etc/mkinitcpio.conf")).write_text("MODULES=(nvidia)\n")
        with mock.patch.object(diagnose, "owned", side_effect=lambda target, rel: f"/{NEW}/" in rel):
            self.assertEqual(len([f for f in diagnose.mkinitcpio(t) if not f.ok]), 1)
            self.assertEqual(repairs.match_kernel(t, {"linux": NEW}), "The kernel in /boot already matches.")

    def test_the_running_kernel_whose_folder_an_update_removed_is_not_looked_for(self):
        # after an update and before the restart: the running kernel (7.2.14) has no folder at all
        t = self.target({NEW: WITH_NVIDIA}, boot=[("vmlinuz-linux", NEW)])
        with mock.patch.object(system.Target, "is_live_root", new_callable=mock.PropertyMock, return_value=True), \
                mock.patch.object(diagnose.os, "uname", return_value=mock.Mock(release="7.2.14-arch1-1")):
            kernels, bad, notes = self.look(t, owned=[NEW])
        self.assertEqual((kernels, bad, notes), ({NEW: "linux"}, [], []))

    def test_the_running_kernels_own_folder_is_never_called_left_behind(self):
        t = self.target({NEW: WITH_NVIDIA, OLD: WITHOUT}, boot=[("vmlinuz-linux", NEW)])
        with mock.patch.object(system.Target, "is_live_root", new_callable=mock.PropertyMock, return_value=True), \
                mock.patch.object(diagnose.os, "uname", return_value=mock.Mock(release=OLD)):
            kernels, bad, notes = self.look(t, owned=[NEW])
        self.assertEqual((kernels, bad, notes), ({NEW: "linux"}, [], []))

    def test_on_the_running_system_the_command_is_for_a_person(self):
        t = self.target({NEW: WITH_NVIDIA, OLD: WITHOUT})
        with mock.patch.object(system.Target, "is_live_root", new_callable=mock.PropertyMock, return_value=True), \
                mock.patch.object(diagnose.os, "uname", return_value=mock.Mock(release="7.2.14-arch1-1")):
            notes = self.look(t, owned=[NEW])[2]
        self.assertIn("This removes it: sudo rm -r ", notes[0].detail)

    def test_a_kernel_in_boot_counts_though_no_package_owns_its_modules(self):
        # Secure Boot put the old kernel back (the update's couldn't be signed) and restored its
        # modules: it is what starts, so it is checked, and never called left behind
        t = self.target({NEW: WITH_NVIDIA, OLD: WITHOUT}, boot=[("vmlinuz-linux", OLD)])
        kernels, bad, notes = self.look(t, owned=[NEW])
        self.assertEqual(kernels, {NEW: "linux", OLD: "linux"})
        self.assertEqual([f.title for f in bad], [f"The NVIDIA driver isn't built for the kernel {OLD}"])
        self.assertEqual(notes, [])

    def test_when_pacman_cannot_say_every_folder_counts_as_before(self):
        t = self.target({NEW: WITH_NVIDIA, OLD: WITHOUT})
        with mock.patch.object(diagnose, "owned", return_value=None), \
                mock.patch.object(diagnose, "installed_packages", return_value={"nvidia-open": "595.58.03-2"}):
            self.assertEqual(diagnose.kernels(t), {NEW: "linux", OLD: "linux"})
            self.assertEqual(len([f for f in diagnose.drivers(t) if not f.ok]), 1)
            self.assertEqual(diagnose.leftover_kernels(t), [])

    def test_pacman_is_asked_about_the_installs_root_not_the_live_one(self):
        t = self.target({NEW: WITH_NVIDIA})
        rel = f"/usr/lib/modules/{NEW}/vmlinuz"
        answer = mock.Mock(returncode=0, stdout="linux\n", stderr="")
        with mock.patch.object(system, "run", return_value=answer) as run:
            self.assertIs(diagnose.owned(t, rel), True)
        argv = run.call_args.args[0]
        self.assertEqual(argv, ["pacman", "--root", t.root, "-Qqo", t.path(rel)])
        self.assertEqual(run.call_args.kwargs["env"]["LC_ALL"], "C")
        nobody = mock.Mock(returncode=1, stdout="", stderr=f"error: No package owns {t.path(rel)}\n")
        broken = mock.Mock(returncode=1, stdout="", stderr="error: failed to initialize alpm library\n")
        with mock.patch.object(system, "run", return_value=nobody):
            self.assertIs(diagnose.owned(t, rel), False)
        with mock.patch.object(system, "run", return_value=broken):
            self.assertIsNone(diagnose.owned(t, rel))
        with mock.patch.object(system, "run", side_effect=system.Failed("pacman isn't on this system")):
            self.assertIsNone(diagnose.owned(t, rel))
        # an install with no package database: nothing to ask
        bare = system.Target(str(tree({f"/usr/lib/modules/{NEW}/pkgbase": "linux\n"})))
        with mock.patch.object(system, "run", side_effect=AssertionError("pacman must not be asked")):
            self.assertIsNone(diagnose.owned(bare, f"/usr/lib/modules/{NEW}/pkgbase"))

    @unittest.skipUnless(shutil.which("pacman"), "pacman isn't on this system")
    def test_real_pacman_reads_the_stand_in_installs_database(self):
        """The real pacman, asked about a stand-in root with a package database of one package,
        linux, which owns the new kernel's files only. It never reads this system's database:
        this system's kernels aren't in the stand-in root."""
        new, old = "9.9.1-standin-1", "9.9.0-standin-1"       # versions no real system has
        t = self.target({new: WITH_NVIDIA, old: WITHOUT}, boot=[("vmlinuz-linux", new)])
        db = Path(t.path("/var/lib/pacman/local/linux-9.9.1.standin-1"))
        db.mkdir(parents=True)
        (db / "desc").write_text("%NAME%\nlinux\n\n%VERSION%\n9.9.1.standin-1\n\n%BASE%\nlinux\n\n"
                                 "%DESC%\nThe Linux kernel and modules\n\n%ARCH%\nx86_64\n\n")
        (db / "files").write_text("%FILES%\nusr/\nusr/lib/\nusr/lib/modules/\n"
                                  f"usr/lib/modules/{new}/\nusr/lib/modules/{new}/pkgbase\n"
                                  f"usr/lib/modules/{new}/vmlinuz\n\n")
        self.assertIs(diagnose.owned(t, f"/usr/lib/modules/{new}/vmlinuz"), True)
        self.assertIs(diagnose.owned(t, f"/usr/lib/modules/{old}/vmlinuz"), False)
        self.assertEqual(diagnose.kernel_folders(t), ({new: "linux"}, {old: "linux"}))
        with mock.patch.object(diagnose, "installed_packages", return_value={"nvidia-open": "595.58.03-2"}):
            self.assertEqual([f for f in diagnose.drivers(t) if not f.ok], [])


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
