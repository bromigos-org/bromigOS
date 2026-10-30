"""The boot menu's pieces (docs/boot.md): the theme generator, grub-btrfs's titles, and the
root helper against a stand-in root (BROMIGOS_BOOT_ROOT) with a stand-in grub-mkconfig.

  python -m unittest discover -s settings/grub/tests      (from the repository root)
"""

import importlib.machinery
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
GRUB = os.path.dirname(HERE)
REPO = os.path.dirname(os.path.dirname(GRUB))


def load(name, path):
    loader = importlib.machinery.SourceFileLoader(name, path)
    spec = importlib.util.spec_from_loader(name, loader)
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    return mod


gen = load("build_grub_theme", os.path.join(GRUB, "build-grub-theme.py"))
titles = load("grub_btrfs_titles", os.path.join(GRUB, "grub-btrfs-titles"))

# what grub-btrfs 4.14 writes (41_snapshots-btrfs: the header row, then a submenu per snapshot)
BTRFS_CFG = """menuentry '|        Date        |         Snapshot         | Type |   Description   |' { echo }
submenu '| 2026-10-09 00:31:02|@.snapshots/152/snapshot |post|bromigos update  |' {
    submenu '| 2026-10-09 00:31:02 | @.snapshots/152/snapshot | post | bromigos update |' { echo }
    menuentry '  vmlinuz-linux & initramfs-linux.img & amd-ucode.img' --class snapshots --class gnu-linux --class gnu --class os "$menuentry_id_option" 'gnulinux-snapshots-abc' {
        if [ x$feature_all_video_module = xy ]; then
        insmod all_video
        fi
    }
    menuentry '  vmlinuz-linux & initramfs-linux-fallback.img & amd-ucode.img' --class snapshots --class gnu-linux --class gnu --class os "$menuentry_id_option" 'gnulinux-snapshots-abc' {
        echo
    }
}
submenu '| 2026-10-09 00:28:15|@.snapshots/151/snapshot |pre |bromigos update  |' {
    submenu '| 2026-10-09 00:28:15 | @.snapshots/151/snapshot | pre | bromigos update |' { echo }
    menuentry '  vmlinuz-linux & initramfs-linux.img' --class snapshots --class gnu-linux --class gnu --class os "$menuentry_id_option" 'gnulinux-snapshots-abc' {
        echo
    }
}
submenu '| 2026-10-09 00:00:01|@.snapshots/150/snapshot |single|timeline       |' {
    submenu '| 2026-10-09 00:00:01 | @.snapshots/150/snapshot | single | timeline |' { echo }
    menuentry '  vmlinuz-linux-lts & initramfs-linux-lts.img' --class snapshots --class gnu-linux --class gnu --class os "$menuentry_id_option" 'gnulinux-snapshots-abc' {
        echo
    }
}
submenu '| 2026-10-08 23:11:40|@.snapshots/140/snapshot |pre |pacman -Syu  |' {
    submenu '| 2026-10-08 23:11:40 | @.snapshots/140/snapshot | pre | pacman -Syu |' { echo }
}
"""


class Titles(unittest.TestCase):
    def test_titles_read_like_the_rollback_list(self):
        out = titles.rewrite(BTRFS_CFG)
        self.assertIn("menuentry 'ROLL BACK · boot the system as it was, newest first' --class info { echo }", out)
        self.assertIn("submenu '10/09 00:31 · after bromigos update' --class snapshot-post --class snapshots {", out)
        self.assertIn("submenu '10/09 00:28 · before bromigos update' --class snapshot-pre --class snapshots {", out)
        self.assertIn("submenu '10/09 00:00 · timeline' --class snapshot --class snapshots {", out)
        self.assertIn("submenu '10/08 23:11 · before pacman -Syu' --class snapshot-pre --class snapshots {", out)
        self.assertIn("    submenu 'snapshot 151 · 10/09 00:28 · before bromigos update' --class info { echo }", out)
        self.assertIn("    menuentry 'Boot it: linux' --class snapshots", out)
        self.assertIn("    menuentry 'Boot it: linux (amd-ucode)' --class snapshots", out)
        self.assertIn("    menuentry 'Boot it: linux (fallback initramfs, amd-ucode)' --class snapshots", out)
        self.assertIn("    menuentry 'Boot it: linux-lts' --class snapshots", out)
        # the boot entries themselves are untouched
        self.assertIn("\"$menuentry_id_option\" 'gnulinux-snapshots-abc' {", out)
        self.assertIn("        insmod all_video", out)
        self.assertNotIn("|", out.replace("x$feature_all_video_module", ""))

    def test_another_title_format_is_left_alone(self):
        cfg = BTRFS_CFG.replace("|        Date        |", "|  Mystery  |")
        self.assertEqual(titles.rewrite(cfg), cfg)

    def test_a_description_with_a_bar_stays_as_written(self):
        cfg = BTRFS_CFG.replace("|pacman -Syu  |' {", "|pacman -S a|b  |' {")
        out = titles.rewrite(cfg)
        self.assertIn("|pacman -S a|b  |' {", out)

    def test_it_runs_grub_script_check_and_keeps_its_answer(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "grub-btrfs.new")
            with open(path, "w") as f:
                f.write(BTRFS_CFG)
            for check, code in (("/bin/true", 0), ("/bin/false", 1)):
                env = dict(os.environ, BROMIGOS_GRUB_SCRIPT_CHECK=check)
                r = subprocess.run([sys.executable, os.path.join(GRUB, "grub-btrfs-titles"), path], env=env)
                self.assertEqual(r.returncode, code)
            with open(path) as f:
                self.assertIn("before bromigos update", f.read())

    def test_real_grub_script_check_accepts_it(self):
        if not shutil.which("grub-script-check"):
            self.skipTest("no grub-script-check here")
        with tempfile.NamedTemporaryFile("w", suffix=".cfg") as f:
            f.write(titles.rewrite(BTRFS_CFG))
            f.flush()
            self.assertEqual(subprocess.run(["grub-script-check", f.name]).returncode, 0)


def write(path, text):
    with open(path, "w") as f:
        f.write(text)


def fake_fonts(d):
    os.makedirs(d, exist_ok=True)
    for name, _, _ in gen.FONTS:
        with open(os.path.join(d, name), "wb") as f:
            f.write(b"FILE\0\0\0\4PFF2" + name.encode())


class Generator(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp()
        fake_fonts(os.path.join(cls.tmp, "fonts"))

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp)

    def build(self, theme, *extra):
        out = os.path.join(self.tmp, theme + "".join(extra).replace("-", ""))
        gen.main(["--theme-dir", os.path.join(REPO, "themes", theme), "--out", out, "--fonts", os.path.join(self.tmp, "fonts"), *extra])
        return out

    def test_every_shipped_theme_resolves(self):
        for name in sorted(os.listdir(os.path.join(REPO, "themes"))):
            path = os.path.join(REPO, "themes", name, "colors.toml")
            if os.path.exists(path):
                colors = gen.resolve_colors_toml(path)
                gen.Palette(colors, name)
                self.assertTrue(all(v.startswith("#") and len(v) == 7 for v in colors.values()), name)

    def test_the_wick_resolves_as_the_theme_engine_does(self):
        sys.path.insert(0, os.path.join(REPO, "lib"))
        try:
            import bromigos_theme
        finally:
            sys.path.pop(0)
        colors = gen.resolve_colors_toml(os.path.join(REPO, "themes", "wick", "colors.toml"))
        for k, v in bromigos_theme.WICK.items():
            self.assertEqual(colors[k], v, k)

    def test_a_theme_has_everything_theme_txt_names(self):
        out = self.build("wick")
        with open(os.path.join(out, "theme.txt")) as f:
            txt = f.read()
        import re
        for name in re.findall(r'"([a-z_]+(?:\*)?\.png)"', txt):
            if "*" in name:
                prefix = name.split("*")[0]
                self.assertTrue(any(n.startswith(prefix) for n in os.listdir(out)), name)
            else:
                self.assertTrue(os.path.exists(os.path.join(out, name)), name)
        for fname, weight, size in gen.FONTS:
            self.assertTrue(os.path.exists(os.path.join(out, fname)))
        for f in re.findall(r'font = "([^"]+)"', txt):
            self.assertIn(f, {gen.font(w, s) for _, w, s in gen.FONTS})
        with open(os.path.join(out, "manifest.json")) as f:
            m = json.load(f)
        self.assertEqual(m["theme"], "wick")
        self.assertEqual(m["colors"]["primary"], "#39ff14")
        self.assertRegex(m["plate"], r"^#[0-9a-f]{6}$")
        self.assertIn("icons/snapshot-pre.png", m["files"])
        self.assertIn('text = "TUNING IN · %d"', txt)
        self.assertIn('text = "RELAY CONSOLE // SELECT CHANNEL"', txt)
        self.assertIn('desktop-image-scale-method: "fitheight"', txt)

    def test_the_medium_has_its_title_card(self):
        out = self.build("wick", "--medium")
        with open(os.path.join(out, "theme.txt")) as f:
            self.assertIn('text = "BROMIGOS // RELAY MEDIUM"', f.read())

    def test_a_world_and_a_colour_theme(self):
        for theme in ("mire", "cinder"):
            out = self.build(theme)
            from PIL import Image
            im = Image.open(os.path.join(out, "background.png"))
            self.assertEqual(im.size, (gen.W, gen.H))
            self.assertEqual(im.mode, "RGB")


DEFAULT_GRUB = """# GRUB boot loader configuration

GRUB_DEFAULT=0
GRUB_TIMEOUT=5
GRUB_DISTRIBUTOR="Arch"
GRUB_CMDLINE_LINUX_DEFAULT="loglevel=3 quiet splash"
GRUB_CMDLINE_LINUX=""
GRUB_PRELOAD_MODULES="part_gpt part_msdos"
#GRUB_TERMINAL_OUTPUT=console
GRUB_GFXMODE=auto
GRUB_GFXPAYLOAD_LINUX=keep
"""

# a grub-mkconfig of our own: reads /etc/default/grub (paths moved into the stand-in root)
# and writes what grub.cfg would say about the theme, and the system's entry as GRUB 2.16's
# 10_linux names and classes it from GRUB_DISTRIBUTOR; FAIL in the root makes it fail
MKCONFIG = """#!/bin/sh
set -e
root="$BROMIGOS_BOOT_ROOT"
[ -e "$root/FAIL" ] && { echo "grub-mkconfig: it went wrong" >&2; exit 1; }
echo x >> "$root/mkconfig.calls"
sed "s#\\([ =]\\)/boot/#\\1$root/boot/#g; s#\\([ =]\\)/usr/lib/#\\1$root/usr/lib/#g" "$root/etc/default/grub" > "$root/grub.sh"
. "$root/grub.sh"
CLASS="--class gnu-linux --class gnu --class os"
if [ "x${GRUB_DISTRIBUTOR}" = "x" ] ; then
  OS=Linux
else
  OS="${GRUB_DISTRIBUTOR} Linux"
  CLASS="--class $(echo ${GRUB_DISTRIBUTOR} | tr 'A-Z' 'a-z' | cut -d' ' -f1|LC_ALL=C sed 's,[^[:alnum:]_],_,g') ${CLASS}"
fi
{
  echo "set gfxmode=$GRUB_GFXMODE"
  echo "terminal_output ${GRUB_TERMINAL_OUTPUT:-console}"
  [ -n "$GRUB_THEME" ] && echo "set theme=($root)${GRUB_THEME#$root}"
  echo "menuentry '$OS' $CLASS { true }"
  echo "submenu 'Advanced options for $OS' {"
  echo "    menuentry '$OS, with Linux linux' $CLASS { true }"
  echo "}"
} > "$2"
"""


class Helper(unittest.TestCase):
    """bromigos-boot-theme in a stand-in root."""

    @classmethod
    def setUpClass(cls):
        cls.pkg = tempfile.mkdtemp()
        fake_fonts(os.path.join(cls.pkg, "fonts"))
        for theme in ("wick", "mire"):
            gen.main(["--theme-dir", os.path.join(REPO, "themes", theme), "--out", os.path.join(cls.pkg, "themes", theme),
                      "--no-fonts"])
        cls.user_render = os.path.join(cls.pkg, "render")
        gen.main(["--theme-dir", os.path.join(REPO, "themes", "rime"), "--out", cls.user_render, "--no-fonts"])

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.pkg)

    def setUp(self):
        self.root = tempfile.mkdtemp()
        r = self.root
        os.makedirs(f"{r}/boot/grub")
        os.makedirs(f"{r}/etc/default")
        with open(f"{r}/boot/grub/grub.cfg", "w") as f:
            f.write("menuentry 'Arch Linux' { true }\n")
        with open(f"{r}/etc/default/grub", "w") as f:
            f.write(DEFAULT_GRUB)
        shutil.copytree(os.path.join(self.pkg, "themes"), f"{r}/usr/share/bromigos/boot/grub/themes")
        shutil.copytree(os.path.join(self.pkg, "fonts"), f"{r}/usr/share/bromigos/boot/grub/fonts")
        os.makedirs(f"{r}/usr/lib/bromigos/boot")
        shutil.copy(os.path.join(GRUB, "grub-btrfs-titles"), f"{r}/usr/lib/bromigos/boot/grub-btrfs-titles")
        self.mk = os.path.join(r, "grub-mkconfig")
        with open(self.mk, "w") as f:
            f.write(MKCONFIG)
        os.chmod(self.mk, 0o755)

    def tearDown(self):
        shutil.rmtree(self.root)

    def run_helper(self, *args):
        env = dict(os.environ, BROMIGOS_BOOT_ROOT=self.root, BROMIGOS_GRUB_MKCONFIG=self.mk,
                   BROMIGOS_GRUB_SCRIPT_CHECK="/bin/true", SUDO_UID=str(os.getuid()))
        return subprocess.run([sys.executable, os.path.join(GRUB, "bromigos-boot-theme"), *args],
                              env=env, capture_output=True, text=True)

    def read(self, rel):
        with open(os.path.join(self.root, rel)) as f:
            return f.read()

    def state(self):
        return json.loads(self.read("var/lib/bromigos/boot/state.json"))

    def calls(self):
        p = os.path.join(self.root, "mkconfig.calls")
        if not os.path.exists(p):
            return 0
        with open(p) as f:
            return len(f.read().split())

    def test_on_puts_the_theme_in_boot_and_turns_it_on(self):
        r = self.run_helper("on", "--theme", "wick")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue(os.path.isfile(f"{self.root}/boot/grub/themes/bromigos/theme.txt"))
        self.assertTrue(os.path.isfile(f"{self.root}/boot/grub/themes/bromigos/background.png"))
        self.assertTrue(os.path.isfile(f"{self.root}/boot/grub/themes/bromigos/geist-mono-regular-16.pf2"))
        default = self.read("etc/default/grub")
        self.assertIn("GRUB_THEME=/boot/grub/themes/bromigos/theme.txt", default)
        self.assertIn("GRUB_TERMINAL_OUTPUT=gfxterm", default)
        self.assertIn("GRUB_GFXMODE=1024x768,800x600,auto", default)      # BIOS: VBE's auto is 640x480
        self.assertIn("GRUB_BTRFS_SCRIPT_CHECK=../lib/bromigos/boot/grub-btrfs-titles", default)
        self.assertTrue(default.startswith(DEFAULT_GRUB.rstrip("\n")))       # the user's lines kept
        self.assertEqual(self.read("etc/default/grub.bromigos-bak"), DEFAULT_GRUB)
        cfg = self.read("boot/grub/grub.cfg")
        self.assertIn("themes/bromigos/theme.txt", cfg)
        self.assertIn("terminal_output gfxterm", cfg)
        self.assertEqual(self.read("boot/grub/grub.cfg.bromigos-bak"), "menuentry 'Arch Linux' { true }\n")
        st = self.state()
        self.assertTrue(st["enabled"])
        self.assertEqual((st["theme"], st["source"]), ("wick", "package"))
        # again: nothing changes, grub.cfg isn't made again
        n = self.calls()
        self.assertEqual(self.run_helper("on", "--theme", "wick").returncode, 0)
        self.assertEqual(self.calls(), n)
        self.assertEqual(self.read("etc/default/grub").count("bromigOS boot menu"), 2)

    def test_the_entries_read_bromigos_while_it_is_on(self):
        self.assertEqual(self.run_helper("on", "--theme", "wick").returncode, 0)
        default = self.read("etc/default/grub")
        self.assertIn('GRUB_DISTRIBUTOR="bromigOS"', default.split("bromigOS boot menu", 1)[1])
        self.assertIn('GRUB_DISTRIBUTOR="Arch"', DEFAULT_GRUB)            # the file's own line, kept
        self.assertTrue(default.startswith(DEFAULT_GRUB.rstrip("\n")))
        cfg = self.read("boot/grub/grub.cfg")
        self.assertIn("menuentry 'bromigOS Linux' --class bromigos --class gnu-linux", cfg)
        self.assertIn("submenu 'Advanced options for bromigOS Linux'", cfg)
        self.assertIn("menuentry 'bromigOS Linux, with Linux linux'", cfg)
        self.assertNotIn("Arch", cfg)
        # off: the file as it was, so the entries are Arch's again
        self.assertEqual(self.run_helper("off").returncode, 0)
        self.assertEqual(self.read("etc/default/grub"), DEFAULT_GRUB)
        cfg = self.read("boot/grub/grub.cfg")
        self.assertIn("menuentry 'Arch Linux' --class arch --class gnu-linux", cfg)
        self.assertNotIn("bromigOS", cfg)
        # and on again
        self.assertEqual(self.run_helper("on", "--theme", "wick").returncode, 0)
        self.assertIn("menuentry 'bromigOS Linux'", self.read("boot/grub/grub.cfg"))

    def test_the_name_goes_with_the_package(self):
        self.run_helper("on", "--theme", "wick")
        # bromigos-boot removed: its files go, the block stays (pacman doesn't edit
        # /etc/default/grub), and the next grub-mkconfig names the entries as before
        os.unlink(f"{self.root}/usr/lib/bromigos/boot/grub-btrfs-titles")
        subprocess.run([self.mk, "-o", f"{self.root}/boot/grub/grub.cfg"], check=True,
                       env=dict(os.environ, BROMIGOS_BOOT_ROOT=self.root))
        self.assertIn("menuentry 'Arch Linux' --class arch", self.read("boot/grub/grub.cfg"))

    def old_block(self):
        """/etc/default/grub with the block a bromigos-settings before the name wrote."""
        path = f"{self.root}/etc/default/grub"
        with open(path) as f:
            text = f.read()
        with open(path, "w") as f:
            f.write(text.replace('    GRUB_DISTRIBUTOR="bromigOS"\n', ""))
        subprocess.run([self.mk, "-o", f"{self.root}/boot/grub/grub.cfg"], check=True,
                       env=dict(os.environ, BROMIGOS_BOOT_ROOT=self.root))
        self.assertIn("menuentry 'Arch Linux'", self.read("boot/grub/grub.cfg"))

    def test_refresh_brings_an_old_block_up_to_date(self):
        for source in (("--theme", "mire"), ("--from", "render")):
            with self.subTest(source=source[0]):
                if source[0] == "--from" and not os.path.isdir(f"{self.root}/render"):
                    shutil.copytree(self.user_render, f"{self.root}/render")
                    source = ("--from", f"{self.root}/render")
                self.assertEqual(self.run_helper("on", *source).returncode, 0)
                self.old_block()
                st = json.loads(self.run_helper("status", "--json").stdout)
                self.assertTrue(st["block"])
                self.assertTrue(st["block_outdated"])
                n = self.calls()
                r = self.run_helper("refresh")
                self.assertEqual(r.returncode, 0, r.stderr)
                self.assertIn("brought up to date", r.stdout)
                self.assertEqual(self.calls(), n + 1)
                self.assertIn('GRUB_DISTRIBUTOR="bromigOS"', self.read("etc/default/grub"))
                self.assertEqual(self.read("etc/default/grub").count("bromigOS boot menu"), 2)
                self.assertIn("menuentry 'bromigOS Linux'", self.read("boot/grub/grub.cfg"))
                self.assertFalse(json.loads(self.run_helper("status", "--json").stdout)["block_outdated"])
                # current: refresh does nothing
                self.assertEqual(self.run_helper("refresh").returncode, 0)
                self.assertEqual(self.calls(), n + 1)

    def test_refresh_leaves_a_turned_off_machine_alone(self):
        self.run_helper("on", "--theme", "wick")
        self.run_helper("off")
        n = self.calls()
        self.assertEqual(self.run_helper("refresh").returncode, 0)
        self.assertEqual(self.calls(), n)
        self.assertEqual(self.read("etc/default/grub"), DEFAULT_GRUB)
        self.assertFalse(json.loads(self.run_helper("status", "--json").stdout)["block_outdated"])

    def test_an_old_block_is_brought_up_to_date(self):
        self.run_helper("on", "--theme", "wick")
        path = f"{self.root}/etc/default/grub"
        with open(path) as f:
            text = f.read()
        with open(path, "w") as f:
            f.write(text.replace("    if [ -d /sys/firmware/efi ]; then", "    if true; then"))
        r = self.run_helper("apply", "--theme", "mire")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertNotIn("if true; then", self.read("etc/default/grub"))
        self.assertEqual(self.read("etc/default/grub").count("bromigOS boot menu"), 2)

    def test_switching_theme_copies_files_only(self):
        self.run_helper("on", "--theme", "wick")
        n = self.calls()
        r = self.run_helper("apply", "--theme", "mire")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.calls(), n)
        self.assertIn("Mire", self.read("boot/grub/themes/bromigos/theme.txt"))
        self.assertEqual(self.state()["theme"], "mire")
        self.assertFalse(os.path.exists(f"{self.root}/boot/grub/themes/.bromigos.old"))

    def test_apply_does_nothing_while_off(self):
        r = self.run_helper("apply", "--theme", "mire")
        self.assertEqual(r.returncode, 0)
        self.assertFalse(os.path.exists(f"{self.root}/boot/grub/themes/bromigos"))

    def test_a_failed_mkconfig_puts_everything_back(self):
        open(f"{self.root}/FAIL", "w").close()
        r = self.run_helper("on", "--theme", "wick")
        self.assertEqual(r.returncode, 3)
        self.assertIn("grub-mkconfig failed", r.stderr)
        self.assertEqual(self.read("etc/default/grub"), DEFAULT_GRUB)
        self.assertEqual(self.read("boot/grub/grub.cfg"), "menuentry 'Arch Linux' { true }\n")
        self.assertFalse(os.path.exists(f"{self.root}/boot/grub/grub.cfg.bromigos-new"))

    def test_off_and_the_opt_out(self):
        self.run_helper("on", "--theme", "wick")
        r = self.run_helper("off")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.read("etc/default/grub"), DEFAULT_GRUB)
        self.assertNotIn("theme", self.read("boot/grub/grub.cfg"))
        self.assertFalse(os.path.exists(f"{self.root}/boot/grub/themes/bromigos"))
        self.assertTrue(self.state()["opted_out"])
        # the migration and the installer ask with --auto: an opted-out machine stays off
        self.assertEqual(self.run_helper("on", "--theme", "wick", "--auto").returncode, 0)
        self.assertNotIn("bromigOS boot menu", self.read("etc/default/grub"))
        # asked by name, it's on again
        self.assertEqual(self.run_helper("on", "--theme", "wick").returncode, 0)
        self.assertIn("bromigOS boot menu", self.read("etc/default/grub"))
        self.assertFalse(self.state()["opted_out"])

    def test_not_grub(self):
        os.unlink(f"{self.root}/boot/grub/grub.cfg")
        r = self.run_helper("on", "--theme", "wick")
        self.assertEqual(r.returncode, 4)
        self.assertEqual(self.read("etc/default/grub"), DEFAULT_GRUB)

    def test_a_machine_systemd_boot_booted(self):
        efivars = f"{self.root}/sys/firmware/efi/efivars"
        os.makedirs(efivars)
        with open(f"{efivars}/LoaderInfo-4a67b082-0a4c-41cf-b6c7-440b29bb8c4f", "wb") as f:
            f.write(b"\x06\0\0\0" + "systemd-boot 258".encode("utf-16-le") + b"\0\0")
        r = self.run_helper("on", "--theme", "wick")
        self.assertEqual(r.returncode, 4)
        self.assertIn("systemd-boot", r.stderr)

    def test_a_users_render(self):
        self.run_helper("on", "--theme", "wick")
        render = os.path.join(self.root, "render")
        shutil.copytree(self.user_render, render)
        with open(f"{render}/theme.txt", "w") as f:
            f.write('title-text: "not this"\n')
        r = self.run_helper("apply", "--from", render)
        self.assertEqual(r.returncode, 0, r.stderr)
        txt = self.read("boot/grub/themes/bromigos/theme.txt")
        self.assertNotIn("not this", txt)                          # written by the helper
        self.assertIn('"#9fe3ff"', txt)                             # Rime's primary
        self.assertEqual(self.state()["source"], "user")
        self.assertTrue(os.path.isfile(f"{self.root}/boot/grub/themes/bromigos/geist-mono-bold-16.pf2"))

    def test_a_render_is_checked(self):
        self.run_helper("on", "--theme", "wick")
        cases = {
            "a link": lambda d: (os.unlink(f"{d}/select_c.png"), os.symlink("/etc/passwd", f"{d}/select_c.png")),
            "not a picture": lambda d: write(f"{d}/meter_mask.png", "#!/bin/sh\n"),
            "a stranger": lambda d: write(f"{d}/grub.cfg", "menuentry x { true }\n"),
            "bad colours": lambda d: write(f"{d}/manifest.json", json.dumps({"colors": {"primary": "red"}, "plate": "#000000"})),
        }
        for what, spoil in cases.items():
            render = os.path.join(self.root, "render-" + what.replace(" ", "-"))
            shutil.copytree(self.user_render, render)
            spoil(render)
            r = self.run_helper("apply", "--from", render)
            self.assertEqual(r.returncode, 3, what)
            self.assertIn("Wick", self.read("boot/grub/themes/bromigos/theme.txt"), what)

    def test_refresh_after_the_package_changed(self):
        self.run_helper("on", "--theme", "mire")
        self.assertEqual(self.run_helper("refresh").returncode, 0)
        before = self.read("boot/grub/themes/bromigos/theme.txt")
        # a new bromigos-settings: the theme's pictures changed
        m = f"{self.root}/usr/share/bromigos/boot/grub/themes/mire/manifest.json"
        with open(m) as f:
            doc = json.load(f)
        doc["files"]["background.png"] = "0" * 64
        with open(m, "w") as f:
            json.dump(doc, f)
        with open(f"{self.root}/usr/share/bromigos/boot/grub/themes/mire/theme.txt", "a") as f:
            f.write("# new\n")
        r = self.run_helper("refresh")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertNotEqual(self.read("boot/grub/themes/bromigos/theme.txt"), before)


if __name__ == "__main__":
    unittest.main()
