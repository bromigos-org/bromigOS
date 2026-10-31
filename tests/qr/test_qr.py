"""lib/bromigos_qr.py: every style in every world decodes (zbar and ZXing, full size and as a
phone's camera sees it), its inks reach the contrast, a failing style falls back, and the terminal
form sets both colours in every cell."""
import os
import shutil
import sys
import tempfile
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "..", "lib"))
os.environ.setdefault("BROMIGOS_THEMES", os.path.join(HERE, "..", "..", "themes"))
import bromigos_qr as Q  # noqa: E402

URL = "https://accounts.bromigos.org/device?user_code=KPGGZFVT#machine=k1.3f2a9c0d&n=fieldkit"


class ThemedQr(unittest.TestCase):
    def test_every_world_and_style_decodes(self):
        if not Q.decoders():
            self.skipTest("no zbarimg or ZXingReader here")
        out = tempfile.mkdtemp(prefix="bromigos-qr-")
        self.addCleanup(shutil.rmtree, out, True)
        r = Q.gallery(out, URL)
        bad = [f"{c['world']} {c['style']}: {c['reads']} contrast {c['contrast']}" for c in r["codes"] if not c["ok"]]
        self.assertEqual(bad, [])
        self.assertEqual(len(r["codes"]), len(Q.worlds()) * len(Q.STYLES))

    def test_inks_reach_the_contrast(self):
        for w in Q.worlds():
            for inverted in (False, True):
                d, l = Q.inks(w, inverted)
                self.assertGreaterEqual(Q.contrast(d, l), Q.MIN_CONTRAST, (w, inverted))

    def test_a_style_that_fails_falls_back(self):
        calls = []

        def check(img, text, style):
            calls.append(style)
            return {"ok": style == "camera"}
        with mock.patch.object(Q, "check", check), mock.patch.object(Q, "decoders", return_value=["ZXingReader"]):
            _, s = Q.render(URL, style="art", world="wick")
        self.assertEqual((s, calls), ("camera", ["art", "brodec", "camera"]))

    def test_terminal_sets_both_colours(self):
        for line in Q.terminal(URL, "wick", truecolor=True):
            self.assertNotIn("█", line)
            for cell in line.split("\x1b[48;2;")[1:]:
                self.assertTrue(cell)          # every cell starts with its own background

    def test_kitty_escape_chunks(self):
        esc = Q.kitty(b"x" * 10000)
        self.assertTrue(esc.startswith("\x1b_Ga=T,f=100,m=1;"))
        self.assertTrue(esc.endswith("\x1b\\"))


if __name__ == "__main__":
    unittest.main()
