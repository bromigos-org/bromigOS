"""The den's plate in a colour theme's colours (lib/bromigos_retint.py), on the real plate.

    cd live && python -m unittest discover -s tests

- the Wick: the plate comes back untouched, bit for bit;
- every shipped colour theme: OKLab lightness kept (so detail and contrast), the bright
  parts in the theme's hue, the shadows near its background, colours inside sRGB;
- no banding: no step between neighbouring pixels grows more than 2.5x, smooth parts stay
  smooth, and the lightness levels stay distinct (no posterizing; chroma may shrink to a
  paler theme's, so near-identical greens may merge);
- a genuine accent (a red light on the green plate) keeps its colour.

Skipped without numpy or GdkPixbuf's bindings (the plate is read through live/pixbuf.py).
The rendered den in each theme: tests/offscreen_retint.py.
"""
import os
import sys
import tomllib
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
LIVE = os.path.dirname(HERE)
REPO = os.path.dirname(LIVE)
sys.path.insert(0, LIVE)
sys.path.insert(0, os.path.join(REPO, "lib"))

try:
    import numpy as np
    import bromigos_retint as R
    from live import pixbuf
    pixbuf.load  # noqa: B018
    import gi
    gi.require_version("GdkPixbuf", "2.0")
    from gi.repository import GdkPixbuf  # noqa: F401
    HAVE = True
except (ImportError, ValueError):
    HAVE = False

DEN = os.path.join(REPO, "desktop/wallpaper/bromigos-den-empty-2560x1440.jpg")
COLOUR_THEMES = ("cinder", "deepvein", "highwind", "lowtown", "rime", "sunder")


def palette(theme):
    with open(os.path.join(REPO, "themes", theme, "colors.toml"), "rb") as f:
        c = tomllib.load(f)
    return dict({r: c[r] for r in R.ROLES}, theme=theme)


def lab(img):
    return R.lin_to_oklab(R.to_linear(img.reshape(-1, 3).astype(np.float32) / 255.0))


@unittest.skipUnless(HAVE, "needs numpy and GdkPixbuf's bindings")
class RetintTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.plate = pixbuf.load(DEN, 960, 540)[0]
        cls.lab = lab(cls.plate)

    def test_the_wick_is_untouched(self):
        out = R.retint(self.plate, palette("wick"))
        self.assertTrue(np.array_equal(out, self.plate))
        self.assertTrue(R.is_wick(dict(R.WICK, theme="anything")))      # the Wick's own colours too

    def test_colour_themes_keep_lightness_and_take_their_hue(self):
        bright = self.lab[:, 0] > 0.55
        dark = self.lab[:, 0] < 0.12
        for t in COLOUR_THEMES:
            with self.subTest(theme=t):
                pal = palette(t)
                out = R.retint(self.plate, pal)
                o = lab(out)
                dl = np.abs(o[:, 0] - self.lab[:, 0])
                self.assertLess(float(np.percentile(dl, 99)), 0.02, "lightness kept")
                # the bright parts point the way the theme's primary does (OKLab hue)
                p = R.lin_to_oklab(R.to_linear(np.asarray([R._hex(pal["primary"])], np.float32)))[0]
                ph = np.degrees(np.arctan2(p[2], p[1]))
                oh = np.degrees(np.arctan2(o[bright, 2], o[bright, 1]))
                d = np.abs((oh - ph + 180) % 360 - 180)
                self.assertLess(float(np.median(d)), 25.0, f"bright parts in {t}'s hue")
                # the shadows sit near the background (little chroma, the theme's own)
                self.assertLess(float(np.median(np.hypot(o[dark, 1], o[dark, 2]))), 0.04)

    def test_no_banding(self):
        def steps(x):
            return np.linalg.norm(np.diff(x.reshape(540, 960, 3), axis=1), axis=2).ravel()
        din = steps(self.lab)
        levels = lambda x: len(np.unique(np.rint(x[:, 0] * 1000)))        # noqa: E731  (lightness, 0.001 steps)
        n_in = levels(self.lab)
        for t in COLOUR_THEMES:
            with self.subTest(theme=t):
                out = R.retint(self.plate, palette(t))
                dout = steps(lab(out))
                sel = din > 0.004                       # neighbours that differ at all
                ratio = dout[sel] / din[sel]
                self.assertLess(float(np.percentile(ratio, 99.9)), 2.5, "no step amplified into an edge")
                n_out = levels(lab(out))
                self.assertGreater(n_out / n_in, 0.9, f"distinct lightness levels kept ({n_out} of {n_in})")
                # where the plate is smooth, the result is too
                flat = din < 0.004
                self.assertLess(float(np.percentile(dout[flat], 99.9)), 0.02)

    def test_a_genuine_accent_keeps_its_colour(self):
        img = self.plate.copy()
        img[10:20, 10:20] = (200, 40, 40)                # a red light
        out = R.retint(img, palette("rime"))
        self.assertLessEqual(int(np.abs(out[15, 15].astype(int) - (200, 40, 40)).max()), 2)

    def test_files(self):
        import tempfile
        try:
            from PIL import Image
        except ImportError:
            self.skipTest("needs Pillow")
        with tempfile.TemporaryDirectory() as d:
            src = os.path.join(d, "in.png")
            Image.fromarray(self.plate[:64, :64]).save(src)
            dst = R.retint_file(src, os.path.join(d, "out.png"), palette("cinder"))
            got = np.asarray(Image.open(dst).convert("RGB"))
            self.assertTrue(np.array_equal(got, R.retint(self.plate[:64, :64], palette("cinder"))))


if __name__ == "__main__":
    unittest.main()
