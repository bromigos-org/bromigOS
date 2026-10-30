"""The text console's colours, font and notes (docs/console.md), with stand-in paths: no console
device, no service manager, nothing outside a temporary folder is touched."""
import gzip
import os
import shutil
import struct
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
REPO = HERE.parents[1]


class Setup(unittest.TestCase):
    def setUp(self):
        self.d = Path(tempfile.mkdtemp(prefix="bromigos-console-"))
        self.addCleanup(shutil.rmtree, self.d, True)
        (self.d / "fonts").mkdir()
        for n in (16, 24, 32):
            (self.d / f"fonts/bromigos-geist-{n}.psf.gz").write_bytes(b"x")
        (self.d / "share").mkdir()
        (self.d / "share/palette.vtrgb").write_text("0\n0\n0\n")
        self.sys = self.d / "sys/class/graphics/fb0"
        self.sys.mkdir(parents=True)

    def run_setup(self, width, vconsole=""):
        (self.sys / "virtual_size").write_text(f"{width},1080\n")
        (self.d / "vconsole.conf").write_text(vconsole)
        env = dict(os.environ, BROMIGOS_CONSOLE_SHARE=str(self.d / "share"), BROMIGOS_CONSOLE_FONTS=str(self.d / "fonts"),
                   BROMIGOS_VCONSOLE=str(self.d / "vconsole.conf"), BROMIGOS_SYSFS=str(self.d / "sys"))
        return subprocess.run(["sh", str(HERE / "bromigos-console-setup"), "--print"], env=env,
                              capture_output=True, text=True, check=True).stdout

    def test_palette_always_font_by_screen_width(self):
        out = self.run_setup(1366)
        self.assertIn("setvtrgb", out)
        if Path("/dev/tty1").exists():
            self.assertIn("bromigos-geist-16.psf.gz", out)
            self.assertIn("bromigos-geist-24.psf.gz", self.run_setup(1920))
            self.assertIn("bromigos-geist-32.psf.gz", self.run_setup(3840))

    def test_a_chosen_font_wins(self):
        out = self.run_setup(3840, 'KEYMAP=us\nFONT="ter-v32n"\n')
        self.assertIn("setvtrgb", out)
        self.assertNotIn("setfont", out)


class Hints(unittest.TestCase):
    def setUp(self):
        self.d = Path(tempfile.mkdtemp(prefix="bromigos-hint-"))
        self.addCleanup(shutil.rmtree, self.d, True)
        (self.d / "dri").mkdir()
        self.env = dict(os.environ, BROMIGOS_RUN=str(self.d / "run"), BROMIGOS_DRI=str(self.d / "dri"),
                        BROMIGOS_GRAPHICS_WAIT="1", PATH="/usr/bin:/bin")

    def hint(self, *args):
        return subprocess.run(["sh", str(HERE / "bromigos-console-hint"), *args], env=self.env, capture_output=True, text=True)

    def test_text_mode_note(self):
        self.assertEqual(self.hint("text-mode").returncode, 0)
        note = (self.d / "run/issue.d/40-bromigos-text.issue").read_text()
        self.assertIn("Text mode", note)
        self.assertIn("graphical.target", note)

    def test_no_graphics_device_skips_the_login_screen_with_a_note(self):
        env = dict(self.env, PATH=f"{self.d}:/usr/bin:/bin")
        (self.d / "systemd-run").write_text("#!/bin/sh\nexit 0\n")
        (self.d / "systemd-run").chmod(0o755)
        r = subprocess.run(["sh", str(HERE / "bromigos-console-hint"), "graphics-ready"], env=env, capture_output=True, text=True)
        self.assertEqual(r.returncode, 1)
        self.assertIn("graphics didn't come up", (self.d / "run/issue.d/40-bromigos-graphics.issue").read_text())

    def test_a_graphics_device_starts_the_login_screen(self):
        (self.d / "dri/card0").write_text("")
        self.assertEqual(self.hint("graphics-ready").returncode, 0)
        self.assertFalse((self.d / "run/issue.d").exists())


class Font(unittest.TestCase):
    @unittest.skipUnless(Path("/usr/share/fonts/TTF/GeistMono-Regular.ttf").exists(), "ttf-geist-mono")
    def test_fonts_palette_and_kmscon(self):
        out = Path(tempfile.mkdtemp(prefix="bromigos-font-"))
        self.addCleanup(shutil.rmtree, out, True)
        subprocess.run([sys.executable, str(HERE / "build-console-font.py"), "--out", str(out)], check=True, capture_output=True)
        for n, (w, h) in ((16, (8, 16)), (24, (12, 24)), (32, (16, 32))):
            data = gzip.open(out / f"bromigos-geist-{n}.psf.gz").read()
            magic, _, _, flags, count, size, height, width = struct.unpack("<IIIIIIII", data[:32])
            self.assertEqual((magic, flags, height, width), (0x864AB572, 1, h, w))
            self.assertIn(count, (256, 512))
            table = data[32 + count * size:]
            for ch in "─│╭╮▁█✓·→é":
                self.assertIn(ch.encode(), table, ch)
        rows = (out / "palette.vtrgb").read_text().split()
        self.assertEqual(len(rows), 3)
        self.assertEqual(rows[1].split(",")[2], "255")                 # the Wick's phosphor green is color2
        conf = (out / "kmscon.conf").read_text()
        self.assertIn("font-name=Geist Mono", conf)
        self.assertIn("palette-green=57,255,20", conf)
        self.assertIn("palette-background=0,5,0", conf)


if __name__ == "__main__":
    unittest.main()
