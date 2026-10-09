"""A GdkPixbuf's pixels at any width (live/pixbuf.py): rows at their own stride.

    cd live && python -m unittest discover -s tests

GdkPixbuf pads each row to 4 bytes but not the last one, so a width whose rows aren't
4-aligned (1366 x 3, or 1422 x 3: a 1280x800 screen's 16:9 cover) used to fail to load
the underlay or shear it. Images are written here as PNG files and read back through
GdkPixbuf's own loader, so the stride is GdkPixbuf's, not ours. Skipped without numpy
or GdkPixbuf's bindings. The whole background at odd screen sizes, rendered:
tests/offscreen_sizes.py.
"""
import os
import struct
import sys
import tempfile
import unittest
import zlib

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    import numpy as np
    import gi
    gi.require_version("GdkPixbuf", "2.0")
    from gi.repository import GdkPixbuf
    from live import pixbuf
    HAVE = True
except (ImportError, ValueError):
    HAVE = False

WIDTHS = list(range(1, 18)) + [1366, 1422, 2133]
HEIGHTS = (1, 2, 5)


def png(path, img):
    """An 8-bit RGB (h, w, 3) or RGBA (h, w, 4) PNG, written by hand."""
    h, w, n = img.shape
    raw = b"".join(b"\x00" + img[y].tobytes() for y in range(h))

    def chunk(kind, data):
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)
    with open(path, "wb") as f:
        f.write(b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 6 if n == 4 else 2, 0, 0, 0))
                + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))


@unittest.skipUnless(HAVE, "needs numpy and GdkPixbuf's bindings")
class PixbufTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.rng = np.random.default_rng(3)

    def tearDown(self):
        self.dir.cleanup()

    def path(self, name):
        return os.path.join(self.dir.name, name)

    def test_rgb_at_every_width_exactly(self):
        for w in WIDTHS:
            for h in HEIGHTS:
                img = self.rng.integers(0, 256, (h, w, 3), dtype=np.uint8)
                png(self.path("a.png"), img)
                pb = GdkPixbuf.Pixbuf.new_from_file(self.path("a.png"))
                self.assertGreaterEqual(pb.get_rowstride(), w * 3)
                got = pixbuf.rgb(pb)
                self.assertEqual(got.shape, (h, w, 3))
                self.assertTrue(got.flags["C_CONTIGUOUS"])
                np.testing.assert_array_equal(got, img, err_msg=f"{w}x{h}")
                got, _ = pixbuf.load(self.path("a.png"), w, h)          # the loader at its own size
                np.testing.assert_array_equal(got, img, err_msg=f"load {w}x{h}")

    def test_alpha_is_dropped_over_black(self):
        for w in (1, 3, 7, 1366, 1422):
            img = self.rng.integers(0, 256, (3, w, 4), dtype=np.uint8)
            img[0, :, 3] = 255                                          # an opaque row: as it is
            png(self.path("b.png"), img)
            pb = GdkPixbuf.Pixbuf.new_from_file(self.path("b.png"))
            self.assertEqual(pb.get_n_channels(), 4)
            np.testing.assert_array_equal(pixbuf.rgb(pb), img[..., :3], err_msg=f"rgba {w}")
            got, _ = pixbuf.load(self.path("b.png"), w, 3)
            self.assertEqual(got.shape, (3, w, 3))
            # GdkPixbuf's compositing rounds down by up to one level, opaque pixels too
            self.assertLessEqual(int(np.abs(got[0].astype(int) - img[0, :, :3]).max()), 1, f"opaque row {w}")
            want = img[..., :3].astype(np.int32) * img[..., 3:4] / 255.0
            self.assertLessEqual(float(np.abs(got.astype(np.int32) - want).max()), 2.0, f"over black {w}")   # its fixed-point maths

    def test_from_rgb_round_trips(self):
        for w in WIDTHS:
            img = self.rng.integers(0, 256, (4, w, 3), dtype=np.uint8)
            pb = pixbuf.from_rgb(img)
            self.assertEqual((pb.get_width(), pb.get_height(), pb.get_n_channels()), (w, 4, 3))
            np.testing.assert_array_equal(pixbuf.rgb(pb), img, err_msg=f"{w}")

    def test_scaling_to_odd_sizes_keeps_rows_and_columns_straight(self):
        # rows of one colour each, and a column ramp: a sheared result would bend them
        src = np.zeros((90, 160, 3), np.uint8)
        src[..., 0] = (np.arange(90) * 2)[:, None]
        src[..., 1] = (np.arange(160) * 1.5).astype(np.uint8)[None, :]
        for w, h in ((1422, 800), (1366, 768), (2133, 1200), (1600, 900), (7, 3)):
            out = pixbuf.scale(src, w, h)
            self.assertEqual(out.shape, (h, w, 3))
            spread_rows = int((out[..., 0].max(axis=1).astype(int) - out[..., 0].min(axis=1)).max())
            spread_cols = int((out[..., 1].max(axis=0).astype(int) - out[..., 1].min(axis=0)).max())
            self.assertLessEqual(spread_rows, 1, f"{w}x{h}: a row isn't one colour")
            self.assertLessEqual(spread_cols, 1, f"{w}x{h}: a column isn't one colour")

    def test_the_old_reshape_fails_where_rows_arent_aligned(self):
        # what the bug was: (h, rowstride) doesn't fit GdkPixbuf's buffer at these widths
        for w in (1366, 1422):
            pb = pixbuf.from_rgb(np.zeros((2, w, 3), np.uint8)).scale_simple(w, 3, GdkPixbuf.InterpType.BILINEAR)
            buf = np.frombuffer(pb.get_pixels(), dtype=np.uint8)
            with self.assertRaises(ValueError):
                buf.reshape(3, pb.get_rowstride())
            self.assertEqual(pixbuf.rgb(pb).shape, (3, w, 3))


if __name__ == "__main__":
    unittest.main()
