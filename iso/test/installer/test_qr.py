"""The pairing QR in a terminal (lib/bromigos_textual.py: qr_matrix, qr_text): half blocks with
both colours set in every cell, dark modules on light, a 4-module quiet zone; drawn to pixels
as a terminal draws ▀ and decoded with zbarimg at full size and scaled down as a phone sees it.
Real terminals (kitty, Alacritty, the bare VT in QEMU) are checked the same way by
iso/test/qr-capture.sh."""
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.realpath(__file__))
sys.path.insert(0, os.path.join(HERE, "../../../lib"))
import bromigos_textual as BT  # noqa: E402

PAYLOADS = ["https://accounts.bromigos.org/device#machine=k1.example&n=desk", "KPGG-ZFVT"]
NAMES = {"black": (0, 0, 0), "white": (170, 170, 170), "bright_white": (255, 255, 255)}   # the console's VGA shades


def rgb(colour):
    if colour.startswith("#"):
        return tuple(int(colour[i:i + 2], 16) for i in (1, 3, 5))
    return NAMES[colour]


def cells(text):
    """Each cell's (character, foreground, background), row by row."""
    rows, row = [], []
    for seg in text.render(__import__("rich.console", fromlist=["Console"]).Console(width=500)):
        if seg.text == "\n":
            rows.append(row)
            row = []
            continue
        for ch in seg.text:
            row.append((ch, seg.style.color.name if seg.style and seg.style.color else None,
                        seg.style.bgcolor.name if seg.style and seg.style.bgcolor else None))
    if row:
        rows.append(row)
    return rows


class QR(unittest.TestCase):
    def setUp(self):
        if not BT.qr_matrix("x"):
            self.skipTest("neither qrencode nor python-qrcode is here")

    def check(self, payload, mode):
        os.environ["BROMIGOS_COLORS"] = mode
        try:
            m = BT.qr_matrix(payload)
            t = BT.qr_text(m)
        finally:
            os.environ.pop("BROMIGOS_COLORS", None)
        grid = cells(t)
        w, h = BT.qr_size(m)
        self.assertEqual((len(grid[0]), len(grid)), (w, h))
        for row in grid:
            for ch, fg, bg in row:            # both colours in every cell: no line gap can show
                self.assertEqual(ch, "▀")
                self.assertIsNotNone(fg)
                self.assertIsNotNone(bg)
        light = rgb(grid[0][0][1])
        self.assertGreater(sum(light), 450)   # dark on light, the standard's polarity (the console's white is grey)
        for c in range(w):                    # the quiet zone: two cells (four modules) of light
            for r in (0, 1, h - 2, h - 1):
                self.assertEqual((rgb(grid[r][c][1]), rgb(grid[r][c][2]) if r < h - 1 else light), (light, light))
        return grid

    def raster(self, grid, px=6):
        from PIL import Image
        im = Image.new("RGB", (len(grid[0]) * px, len(grid) * 2 * px))
        for r, row in enumerate(grid):
            for c, (_, fg, bg) in enumerate(row):
                for (y0, col) in ((0, fg), (px, bg)):
                    im.paste(rgb(col), (c * px, r * 2 * px + y0, (c + 1) * px, r * 2 * px + y0 + px))
        return im

    def test_every_cell_both_colours_and_quiet_zone(self):
        for p in PAYLOADS:
            for mode in ("truecolor", "16"):
                self.check(p, mode)

    def test_small_version(self):
        self.assertLessEqual(len(BT.qr_matrix("KPGG-ZFVT")), 25)                 # version 2 or less
        self.assertLessEqual(len(BT.qr_matrix(PAYLOADS[0])), 33)                  # version 4 at most

    def test_decodes_full_size_and_as_a_phone_sees_it(self):
        if not shutil.which("zbarimg"):
            self.skipTest("zbarimg isn't installed")
        try:
            import PIL  # noqa: F401
        except ImportError:
            self.skipTest("Pillow isn't installed")
        for p in PAYLOADS:
            for mode in ("truecolor", "16"):
                im = self.raster(self.check(p, mode))
                for scale in (1.0, 0.5, 0.33):
                    s = im.resize((max(1, int(im.width * scale)), max(1, int(im.height * scale))))
                    with tempfile.NamedTemporaryFile(suffix=".png") as f:
                        s.save(f.name)
                        r = subprocess.run(["zbarimg", "-q", "--raw", f.name], capture_output=True, text=True)
                    self.assertEqual(r.stdout.strip(), p, f"{mode} at {scale:.0%}")

    def test_big_code_when_it_cannot_fit(self):
        t = BT.big_code("KPGG-ZFVT")
        self.assertEqual(len(str(t).split("\n")), 5)


if __name__ == "__main__":
    unittest.main()
