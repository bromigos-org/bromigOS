"""STATIC, the mascot (lib/bromigos_static.py and lib/bromigos_static_term.py): every pose and
loop frame draws as well-formed SVG in any theme's colours, the faces have their grids, the
rig's parts stand alone, he can be turned off, and the terminal looks (kitty pictures,
half-block pixels, text) are chosen and drawn as they should be.

    python3 -m unittest tests/mascot/test_static.py
"""
import os
import shutil
import sys
import unittest
import xml.etree.ElementTree as ET

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(REPO, "lib"))
import bromigos_static as S  # noqa: E402
import bromigos_static_term as ST  # noqa: E402

MIRE = {"void": "#05030a", "panel": "#120a1c", "primary": "#c58cff", "soft": "#e2c6ff", "dim": "#6b3fa0",
        "text": "#efe3ff", "muted": "#8f7fa3", "warn": "#ffb454", "white": "#ffffff"}


class Rig(unittest.TestCase):
    def test_every_pose_and_frame_is_svg(self):
        for pose in S.POSES:
            for f in range(S.frames(pose)):
                for level in ("ember", "glow", "flare"):
                    doc = S.svg(pose, frame=f, level=level, size=128)
                    root = ET.fromstring(doc)
                    self.assertEqual(root.get("height"), "128", pose)
            ET.fromstring(S.svg(pose, crop="head", size=32))

    def test_the_theme_decides_the_colours(self):
        doc = S.svg("host", pal=MIRE)
        self.assertIn(MIRE["primary"], doc)
        self.assertNotIn(S.WICK["primary"], doc)
        hc = S.svg("host", pal=MIRE, hc=True)
        self.assertNotIn('filter="url(#glow)"', hc)              # high contrast: no glow
        self.assertIn(MIRE["white"], hc)

    def test_the_faces(self):
        for name in list(S.APPROVED) + list(S.DEN):
            for f in range(4):
                g = S.face_grid(name, f)
                self.assertEqual((len(g), len(g[0])), (S.GH, S.GW), name)
                m = S.face_grid(name, f, mini=True)
                self.assertEqual((len(m), len(m[0])), (S.MH, S.MW), name)
                self.assertTrue(set("".join(g + m)) <= set("#+a."), name)
        self.assertNotEqual(S.face_grid("snow", 0), S.face_grid("snow", 1))        # snow moves
        self.assertEqual(S.face_grid("happy", 0), S.face_grid("happy", 3))         # a face holds

    def test_ik_reaches(self):
        """The hand lands where the pose asks (the remote, the earpiece, the set's side)."""
        import math
        for pose in ("remote", "listening", "whack", "host"):
            p = S.resolve(pose, 0)
            for side, (space, x, y, _b) in p["ik"].items():
                up, fore, _h, _k = p[side]
                hip, torso = p["hip"], p["torso"]
                s = S.JOINTS["torso"]["shoulder_" + side[-1]]
                e = S._add(s, S._rot((0, S.ARM[0]), up))
                w = S._add(e, S._rot((0, S.ARM[1]), up + fore))
                world = S._add(hip, S._rot(w, torso))
                if space == "world":
                    self.assertLess(math.dist(world, (x, y)), 3, pose)

    def test_parts_stand_alone(self):
        parts = S.parts()
        for name in ("head", "screen", "antenna", "torso", "upperarm", "forearm", "hand_open", "thigh", "shin",
                     "boot", "cable", "remote", "armchair_back", "armchair_front", "desk"):
            ET.fromstring(f'<svg xmlns="http://www.w3.org/2000/svg">{parts[name]["svg"]}</svg>')
        self.assertEqual(parts["head"]["joints"]["antenna"], list(S.JOINTS["head"]["antenna"]))

    def test_on_quiet_off(self):
        self.assertEqual(S.mode({"BROMIGOS_MASCOT": "off"}), "off")
        self.assertEqual(S.mode({"BROMIGOS_MASCOT": "Quiet"}), "quiet")
        import tempfile
        d = tempfile.mkdtemp()
        os.makedirs(os.path.join(d, "bromigos"))
        self.assertEqual(S.mode({"XDG_CONFIG_HOME": d}), "on")
        with open(os.path.join(d, "bromigos", "mascot.toml"), "w") as f:
            f.write('mode = "off"\n')
        self.assertEqual(S.mode({"XDG_CONFIG_HOME": d}), "off")
        shutil.rmtree(d)


class Terminal(unittest.TestCase):
    def test_which_look(self):
        self.assertEqual(ST.look({"KITTY_WINDOW_ID": "1", "TERM": "xterm-kitty"}), "kitty")
        self.assertEqual(ST.look({"KITTY_WINDOW_ID": "1", "TERM": "xterm-kitty", "TMUX": "x"}), "blocks")
        self.assertEqual(ST.look({"TERM": "xterm-256color", "COLORTERM": "truecolor"}), "blocks")
        self.assertEqual(ST.look({"TERM": "linux"}), "text")
        self.assertEqual(ST.look({"TERM": "xterm-kitty", "BROMIGOS_ICONS": "ascii"}), "text")
        self.assertEqual(ST.look({"BROMIGOS_STATIC_TERM": "text", "KITTY_WINDOW_ID": "1"}), "text")
        self.assertEqual(ST.glyph("whack"), "[×_×]")
        self.assertTrue(ST.glyph("whack", ascii=True).isascii())

    def test_the_pixel_head(self):
        g = ST.head("watching", pal=MIRE)
        self.assertEqual((len(g), len(g[0])), (14, 16))
        self.assertIn(MIRE["primary"], {c for row in g for c in row})
        t = ST.blocks(g)
        self.assertEqual(len(t.plain.splitlines()), 7)                # two pixel rows to a cell

    @unittest.skipUnless(shutil.which("rsvg-convert"), "needs rsvg-convert")
    def test_a_figure_in_half_blocks(self):
        px = ST.figure("antenna", 36, 20)
        self.assertEqual(len(px), 40)
        lit = sum(1 for row in px for c in row if c)
        self.assertGreater(lit, 200)
        self.assertEqual(len(ST.blocks(px).plain.splitlines()), 20)

    def test_kitty_cells(self):
        seq = ST.kitty_transmit(b"\x89PNG" + b"x" * 9000, 77, 16, 7)
        self.assertTrue(seq.startswith("\x1b_Ga=T,U=1,f=100,q=2,i=77,c=16,r=7,m=1;"))
        t = ST.kitty_cells(77, 16, 7)
        rows = t.plain.split("\n")
        self.assertEqual(len(rows), 7)
        self.assertEqual(rows[0].count(ST.PLACEHOLDER), 16)
        self.assertEqual(rows[2][1], chr(ST.DIACRITICS[2]))           # the row mark


if __name__ == "__main__":
    unittest.main()
