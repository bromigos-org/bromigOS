"""Installing by copying the live system (bromigos_installer/copyroot.py, archinstall_copy.py;
docs/iso.md, "How installing works"): the build's prep in a stand-in chroot (the medium's own
files sorted out, the store pruned, the package files the image lacks kept), and the copy onto
a stand-in new system (archinstall's files and the new system's mounts left alone, the medium's
own taken away, root's account and the kernels as a fresh system's). Nothing here runs as root:
the tools that must (pacman-key, systemd-machine-id-setup) are stood in."""
import importlib
import json
import os
import shutil
import subprocess
import sys
import tarfile
import tempfile
import unittest
from pathlib import Path

LIB = Path(__file__).resolve().parents[2] / "profile/airootfs/usr/local/lib/bromigos-iso"
sys.path.insert(0, str(LIB))
from bromigos_installer import copyroot, progress  # noqa: E402


def pkg_db(root, name, version, files, arch="x86_64"):
    d = Path(root) / "var/lib/pacman/local" / f"{name}-{version}"
    d.mkdir(parents=True, exist_ok=True)
    (d / "desc").write_text(f"%NAME%\n{name}\n\n%VERSION%\n{version}\n\n%ARCH%\n{arch}\n\n")
    (d / "files").write_text("%FILES%\n" + "\n".join(files) + "\n\n")


def put(root, rel, text="x"):
    p = Path(root) / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text)
    return p


class NoExtract(unittest.TestCase):
    def test_the_last_pattern_that_matches_decides(self):
        pats = ["usr/share/doc/*", "!usr/share/doc/bromigos*", "usr/share/hypr/wall*.png"]
        self.assertTrue(copyroot.noextracted("usr/share/doc/bash/README", pats))
        self.assertFalse(copyroot.noextracted("usr/share/doc/bromigos/manual.html", pats))
        self.assertTrue(copyroot.noextracted("usr/share/hypr/wall0.png", pats))
        self.assertFalse(copyroot.noextracted("usr/include/stdio.h", pats))

    def test_read_from_pacman_conf(self):
        with tempfile.TemporaryDirectory() as t:
            c = put(t, "pacman.conf", "[options]\nNoExtract   = usr/share/doc/* !usr/share/doc/bromigos*\n"
                    "#NoExtract = usr/include/*\nNoExtract = usr/share/gtk-doc/*\n[core]\n")
            self.assertEqual(copyroot.noextract(c), ["usr/share/doc/*", "!usr/share/doc/bromigos*", "usr/share/gtk-doc/*"])

    def test_the_live_pacman_conf_leaves_out_only_what_installed_systems_may_lack(self):
        pats = copyroot.noextract(LIB.parents[3] / "etc/pacman.conf")
        self.assertTrue(pats, "the live pacman.conf has NoExtract lines (the build reads them)")
        for kept in ("usr/include/stdio.h", "usr/lib/libc.a", "usr/share/locale/de/LC_MESSAGES/bash.mo",
                     "usr/share/man/de/man1/ls.1.gz", "usr/share/gir-1.0/Gtk-4.0.gir", "usr/share/doc/bromigos/x"):
            self.assertFalse(copyroot.noextracted(kept, pats), kept)
        self.assertTrue(copyroot.noextracted("usr/share/doc/bash/README", pats))


class Prep(unittest.TestCase):
    """The build's prep in a stand-in chroot."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = r = Path(self.tmp.name) / "root"
        store = r / copyroot.STORE / "core/os/x86_64"
        store.mkdir(parents=True)
        put(r, "etc/pacman.conf", "[options]\nNoExtract = usr/share/doc/*\n")
        # bash: installed whole; its doc left out (NoExtract, installed systems too)
        pkg_db(r, "bash", "5.3-1", ["usr/", "usr/bin/", "usr/bin/bash", "usr/share/doc/bash/README"])
        put(r, "usr/bin/bash")
        # intel-ucode: its file is on /boot, which mkarchiso empties: kept in the store
        pkg_db(r, "intel-ucode", "2026-1", ["boot/", "boot/intel-ucode.img"], arch="any")
        put(r, "boot/intel-ucode.img")
        # bromigos-core: the build left its worlds' media out (Field Kit's NoExtract): kept in the store
        pkg_db(r, "bromigos-core", "1-1", ["usr/share/bromigos/themes/wick/live/loop.mp4", "usr/bin/bromigos"])
        put(r, "usr/bin/bromigos")
        # filesystem: owns /etc/passwd and os-release (the build changes both)
        pkg_db(r, "filesystem", "2026-1", ["etc/", "etc/passwd", "usr/lib/os-release", "usr/local/", "usr/local/bin/",
                                           "var/", "var/lib/"], arch="any")
        put(r, "etc/passwd", "root:x:0:0:root:/root:/usr/bin/zsh\n")
        put(r, "usr/lib/os-release", "NAME=bromigOS\nIMAGE_ID=bromigos\n")
        # pacman-mirrorlist: the installer reads its file, so it stays in the store
        pkg_db(r, "pacman-mirrorlist", "2026-1", ["etc/pacman.d/mirrorlist"], arch="any")
        put(r, "etc/pacman.d/mirrorlist")
        for name, ver, arch in (("bash", "5.3-1", "x86_64"), ("intel-ucode", "2026-1", "any"), ("bromigos-core", "1-1", "x86_64"),
                                ("pacman-mirrorlist", "2026-1", "any"), ("nvidia-utils", "580-1", "x86_64")):
            put(store, f"{name}-{ver}-{arch}.pkg.tar.zst")
            put(store, f"{name}-{ver}-{arch}.pkg.tar.zst.sig")
        # filesystem's package, a real one: its os-release is put back as it was
        src = Path(self.tmp.name) / "fs"
        put(src, "usr/lib/os-release", "NAME=bromigOS\n")
        put(src, "etc/passwd", "root:x:0:0::/root:/usr/bin/bash\n")
        subprocess.run(["bsdtar", "--zstd", "-cf", str(store / "filesystem-2026-1-any.pkg.tar.zst"), "-C", str(src),
                        "usr/lib/os-release", "etc/passwd"], check=True)
        # the overlay as the build listed it
        put(r, "usr/local/bin/bromigos-iso-install")
        put(r, "etc/sddm.conf.d/live.conf")
        put(r, "etc/hostname")
        overlay = ["etc\td", "etc/hostname\tf", "etc/passwd\tf", "etc/sddm.conf.d\td", "etc/sddm.conf.d/live.conf\tf",
                   "usr\td", "usr/local\td", "usr/local/bin\td", "usr/local/bin/bromigos-iso-install\tf",
                   "var\td", "var/lib\td", "var/lib/bromigos\td", "root\td", "root/.zlogin\tf"]
        put(r, copyroot.COPY_DIR + "/overlay.txt", "\n".join(overlay) + "\n")

    def tearDown(self):
        self.tmp.cleanup()

    def test_prep_finish(self):
        copyroot.prep_finish(str(self.root))
        m = json.loads((self.root / copyroot.COPY_DIR / "manifest.json").read_text())
        self.assertEqual(sorted(m["remove"]), ["etc/hostname", "usr/local/bin/bromigos-iso-install"])
        self.assertEqual(sorted(m["trees"]), ["etc/sddm.conf.d", "var/lib/bromigos"])
        # the accounts are kept from the baseline (the system users' IDs), not a package's copy
        self.assertEqual(m["pristine"], ["usr/lib/os-release"])
        self.assertEqual((self.root / copyroot.COPY_DIR / "pristine/usr/lib/os-release").read_text(), "NAME=bromigOS\n")
        self.assertEqual(m["repair"], ["bromigos-core", "intel-ucode"])
        store = self.root / copyroot.STORE / "core/os/x86_64"
        left = sorted(f.name for f in store.iterdir() if not f.name.endswith(".sig"))
        self.assertEqual(left, ["bromigos-core-1-1-x86_64.pkg.tar.zst", "intel-ucode-2026-1-any.pkg.tar.zst",
                                "nvidia-utils-580-1-x86_64.pkg.tar.zst", "pacman-mirrorlist-2026-1-any.pkg.tar.zst"])
        self.assertFalse((store / "bash-5.3-1-x86_64.pkg.tar.zst.sig").exists(), "a pruned package's signature goes too")
        self.assertIn("bash", m["pruned"])
        self.assertEqual(m["dirs"], [["boot", 0o755 & os.stat(self.root / "boot").st_mode, os.getuid(), os.getgid()]])

    def test_offline_has_the_store_and_the_live_image(self):
        copyroot.prep_finish(str(self.root))
        copyroot._live.clear()
        store = str(self.root / copyroot.STORE)
        self.assertTrue(copyroot.offline_has("nvidia-utils", store, str(self.root)))     # a file in the store
        self.assertTrue(copyroot.offline_has("bash", store, str(self.root)))             # copied with the image
        self.assertFalse(copyroot.offline_has("linux-zen", store, str(self.root)))
        # a medium that doesn't install by copying: only the store counts
        os.remove(self.root / copyroot.COPY_DIR / "manifest.json")
        copyroot._live.clear()
        self.assertFalse(copyroot.offline_has("bash", store, str(self.root)))


class Firmware(unittest.TestCase):
    """Field Kit's store has linux-firmware's parts but NVIDIA's, not the whole set: archinstall's
    own linux-firmware (its base packages) and answers.py's become the parts the medium carries."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name) / "airootfs"
        self.store = self.root / copyroot.STORE / "core/os/x86_64"
        for name in ("linux-firmware-intel", "linux-firmware-realtek", "linux-firmware-whence"):      # in the image
            pkg_db(self.root, name, "20261019-1", [], arch="any")
        put(self.root, copyroot.COPY_DIR + "/manifest.json", "{}")
        for name in ("linux-firmware-cirrus", "linux-firmware-ti"):                                 # store only
            put(self.store, f"{name}-20261019-1-any.pkg.tar.zst")
            put(self.store, f"{name}-20261019-1-any.pkg.tar.zst.sig")
        copyroot._live.clear()
        self.args = (str(self.root / copyroot.STORE), str(self.root))

    def tearDown(self):
        copyroot._live.clear()
        self.tmp.cleanup()

    def test_offline_names(self):
        self.assertEqual(copyroot.offline_names("linux-firmware-", *self.args),
                         ["linux-firmware-cirrus", "linux-firmware-intel", "linux-firmware-realtek", "linux-firmware-ti",
                          "linux-firmware-whence"])

    def test_the_parts_in_place_of_the_whole_set(self):
        got = copyroot.firmware(["base", "sudo", "linux-firmware", "mkinitcpio"], *self.args)
        self.assertEqual(got, ["base", "sudo", "mkinitcpio", "linux-firmware-cirrus", "linux-firmware-intel",
                               "linux-firmware-realtek", "linux-firmware-ti"])
        self.assertNotIn("linux-firmware-nvidia", got)

    def test_the_whole_set_when_the_medium_has_it(self):
        put(self.store, "linux-firmware-20261019-1-any.pkg.tar.zst")          # the desktop medium's store
        self.assertEqual(copyroot.firmware(["base", "linux-firmware"], *self.args), ["base", "linux-firmware"])
        self.assertEqual(copyroot.firmware(["base", "grub"], *self.args), ["base", "grub"])

    def test_archinstalls_base_packages_through_the_plugin(self):
        os.environ["BROMIGOS_ISO_REPO_DIR"], os.environ["BROMIGOS_ISO_LIVE_ROOT"] = self.args
        os.environ["BROMIGOS_COPY_STRAPPED"] = str(Path(self.tmp.name) / "strapped.txt")
        try:
            plug = importlib.import_module("archinstall_copy").Plugin()
            plug.copied = True                    # the copy itself is Install's test
            got = plug.on_pacstrap(["base", "sudo", "linux-firmware", "mkinitcpio"])
            self.assertIn("linux-firmware-cirrus", got)
            self.assertNotIn("linux-firmware", got)
            self.assertIn("linux-firmware-ti", (Path(self.tmp.name) / "strapped.txt").read_text().split())
            self.assertIsNone(plug.on_pacstrap(["grub"]))                  # nothing to change: archinstall's own list
        finally:
            for k in ("BROMIGOS_ISO_REPO_DIR", "BROMIGOS_ISO_LIVE_ROOT", "BROMIGOS_COPY_STRAPPED"):
                os.environ.pop(k, None)


class Install(unittest.TestCase):
    """The copy onto a stand-in new system, as the plugin runs it at archinstall's first package step."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        t = Path(self.tmp.name)
        self.src, self.target = s, d = t / "image", t / "mnt"
        put(s, "usr/bin/foo", "foo")
        os.symlink("foo", s / "usr/bin/foo-link")
        put(s, "usr/local/bin/bromigos-iso-install")
        put(s, "usr/local/share/bromigos-iso/install-panel.py")
        put(s, copyroot.STORE + "/core/os/x86_64/core.db")
        put(s, "home/live/.zshrc")
        put(s, "root/.zshrc")
        put(s, "etc/sddm.conf.d/live.conf", "image's /etc is never copied")
        put(s, "version", "2026.11.01")
        put(s, "usr/lib/os-release", "NAME=bromigOS\nIMAGE_ID=bromigos\n")
        put(s, "usr/lib/modules/7.2.11-arch1-1/pkgbase", "linux\n")
        put(s, "usr/lib/modules/7.2.11-arch1-1/vmlinuz", "kernel")
        (s / "boot").mkdir()
        (s / "var/lib/bromigos").mkdir(parents=True, exist_ok=True)
        pkg_db(s, "foo", "1-1", ["usr/bin/foo"])
        # /etc as the packages left it (the baseline): overlay files in it too
        base = t / "base"
        put(base, "etc/passwd", "root:x:0:0:root:/root:/usr/bin/zsh\nbin:x:1:1::/:/usr/bin/nologin\n")
        put(base, "etc/shadow", "root::14871::::::\nbin:!*:20000::::::\n")
        put(base, "etc/hostname", "bromigos\n")
        put(base, "etc/vconsole.conf", "KEYMAP=us\n")
        put(base, "etc/sddm.conf.d/live.conf", "[Autologin]\nUser=live\n")
        (base / "etc/systemd/system/getty.target.wants").mkdir(parents=True)
        os.symlink("/usr/lib/systemd/system/getty@.service", base / "etc/systemd/system/getty.target.wants/getty@tty1.service")
        cd = s / copyroot.COPY_DIR
        cd.mkdir(parents=True)
        with tarfile.open(cd / "etc.tar", "w") as tf:
            tf.add(base / "etc", arcname="etc")
        put(cd, "pristine/usr/lib/os-release", "NAME=bromigOS\n")
        self.manifest = {"schema": 1, "remove": ["etc/hostname", "etc/vconsole.conf", "usr/local/bin/bromigos-iso-install"],
                         "trees": ["etc/sddm.conf.d", "usr/local/share/bromigos-iso", "var/lib/bromigos"],
                         "pristine": ["usr/lib/os-release"], "repair": [],
                         "dirs": [["boot/memtest86+", 0o755, os.getuid(), os.getgid()]], "live_packages": ["foo"],
                         "noextract": [], "pruned": ["foo"]}
        (cd / "manifest.json").write_text(json.dumps(self.manifest))
        # the new system as archinstall left it before its first package step: its mounts, its
        # keyboard, a reinstall's kept home
        put(d, "etc/vconsole.conf", "KEYMAP=de\n")
        put(d, "home/tester/keepme.txt", "kept")
        (d / "var/lib/bromigos/server").mkdir(parents=True)
        (d / "boot").mkdir()
        self.calls = []

    def tearDown(self):
        self.tmp.cleanup()

    def run_(self, argv, **kw):
        if argv[0] in ("systemd-machine-id-setup", "pacman-key", "gpgconf"):
            self.calls.append(argv[0])
            if argv[0] == "systemd-machine-id-setup":
                put(self.target, "etc/machine-id", "0123456789abcdef0123456789abcdef\n")
            return subprocess.CompletedProcess(argv, 0)
        return subprocess.run(argv, **kw)

    def test_the_copy(self):
        if not shutil.which("rsync"):
            self.skipTest("no rsync here")
        copyroot.install(str(self.target), str(self.src), run=self.run_)
        d = self.target
        self.assertEqual((d / "usr/bin/foo").read_text(), "foo")
        self.assertTrue(os.path.islink(d / "usr/bin/foo-link"))
        self.assertTrue((d / "var/lib/pacman/local/foo-1-1/desc").exists())
        # the medium's own: gone
        for gone in ("usr/local/bin/bromigos-iso-install", "usr/local/share/bromigos-iso", "etc/sddm.conf.d",
                     "etc/hostname", copyroot.STORE, "home/live", "root/.zshrc", "version"):
            self.assertFalse(os.path.lexists(d / gone), gone)
        # archinstall's own and the new system's mounts: as they were
        self.assertEqual((d / "etc/vconsole.conf").read_text(), "KEYMAP=de\n")
        self.assertEqual((d / "home/tester/keepme.txt").read_text(), "kept")
        self.assertTrue((d / "var/lib/bromigos/server").is_dir())
        # /etc: the baseline's
        self.assertTrue(os.path.islink(d / "etc/systemd/system/getty.target.wants/getty@tty1.service"))
        self.assertEqual((d / "usr/lib/os-release").read_text(), "NAME=bromigOS\n")
        # root as a fresh system's, the system users as they were
        self.assertIn("root:x:0:0:root:/root:/usr/bin/bash", (d / "etc/passwd").read_text())
        self.assertIn("bin:x:1:1::/:/usr/bin/nologin", (d / "etc/passwd").read_text())
        self.assertTrue((d / "etc/shadow").read_text().startswith("root:*:"))
        # the kernel on /boot, the packages' folders there, a machine ID and keyring of its own
        self.assertEqual((d / "boot/vmlinuz-linux").read_text(), "kernel")
        self.assertTrue((d / "boot/memtest86+").is_dir())
        self.assertEqual(self.calls, ["systemd-machine-id-setup", "pacman-key", "pacman-key", "gpgconf"])


class Prune(unittest.TestCase):
    """After archinstall: what it installed explicitly stays, the live system's own goes."""

    def test_explicit_kept_orphans_removed(self):
        with tempfile.TemporaryDirectory() as t:
            for n in ("base", "bash", "archinstall", "python-pyparted", "clonezilla"):
                pkg_db(t, n, "1-1", [])
            deps = {"base": {"bash"}, "archinstall": {"python-pyparted"}}
            state = {"explicit": set(), "installed": {"base", "bash", "archinstall", "python-pyparted", "clonezilla"}}
            ran = []

            def fake(target, *argv, check=True, capture=False):
                ran.append(argv[:2])
                if argv[:2] == ("pacman", "-D"):
                    if argv[2] == "--asexplicit":
                        state["explicit"] |= set(argv[3:])
                    return subprocess.CompletedProcess(argv, 0, "", "")
                if argv[:2] == ("pacman", "-Qttdq"):
                    needed = set()
                    for e in state["explicit"]:
                        needed |= {e} | deps.get(e, set())
                    return subprocess.CompletedProcess(argv, 0, "\n".join(sorted(state["installed"] - needed)), "")
                if argv[:2] == ("pacman", "-Rns"):
                    for n in argv[3:]:
                        state["installed"].discard(n)
                        shutil.rmtree(Path(t) / "var/lib/pacman/local" / f"{n}-1-1")
                    return subprocess.CompletedProcess(argv, 0, "", "")
                raise AssertionError(argv)
            real = copyroot.chroot
            copyroot.chroot = fake
            try:
                gone = copyroot.prune(t, ["base", "linux-firmware-whatever"])
            finally:
                copyroot.chroot = real
            self.assertEqual(sorted(gone), ["archinstall", "clonezilla", "python-pyparted"])
            self.assertEqual(state["installed"], {"base", "bash"})


class Progress(unittest.TestCase):
    def test_the_copy_then_the_store(self):
        import io
        out = io.StringIO()
        progress.main(io.StringIO("Installing packages: ['base']\nCopying the live system: 50%\nCopying the live system: 100%\n"
                                  "(1/3) installing nvidia-utils\n(3/3) installing linux-headers\n"), out)
        stages = [l.split(" ", 2)[1] for l in out.getvalue().splitlines() if l.startswith("::stage")]
        self.assertEqual(stages, ["15", "40", "65", "65", "65"])


class Plugin(unittest.TestCase):
    def test_archinstall_loads_it(self):
        try:
            importlib.import_module("archinstall.lib.plugins")
        except Exception:
            self.skipTest("no archinstall here")
        from archinstall.lib import plugins
        plugins.load_plugin(LIB / "archinstall_copy.py")
        self.assertIn("archinstall_copy.py", plugins.plugins)
        self.assertTrue(hasattr(plugins.plugins["archinstall_copy.py"], "on_pacstrap"))


if __name__ == "__main__":
    unittest.main()
