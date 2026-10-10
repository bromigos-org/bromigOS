"""Every built-in panel drawn at every size class it declares (its start, smallest and
largest), with demo.py's made-up readings: it draws without an error, each class gets its
own layout, and every hover region has a hint and sits inside the panel."""
import os
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
os.environ.setdefault("XDG_CONFIG_HOME", tempfile.mkdtemp())       # no user's weather.toml or layout
import demo  # noqa: E402,F401  (made-up readings: never this machine's)
import cairo  # noqa: E402

import keybinds  # noqa: E402
import panels as P  # noqa: E402

# SHORTCUTS reads the binds from Hyprland or the user's config; a clean home (a package
# build) has none, and then its size classes would draw alike. A fixed set instead.
_BINDS = [(sec, keys, desc, None) for sec, rows in (
    ("VECTOR", [(["SUPER", "E"], "Show / minimize"), (["SUPER", "V"], "Hold to talk"),
                (["SUPER", "ALT", "V"], "Chat box shown/hidden")]),
    ("PANELS + NOTES", [(["SUPER", "W"], "All desktop panels"), (["SUPER", "ALT", "W"], "Edit widgets"),
                        (["SUPER", "S"], "System panel"), (["ALT", "N"], "Type in field notes")]),
    ("HOLOGRAMS", [(["SUPER", "H"], "Holo deck (this machine)"), (["SUPER", "T"], "Timeline")]),
    ("LAUNCH", [(["SUPER", "SPACE"], "Desktop menu"), (["SUPER", "COMMA"], "Settings")]),
    ("WINDOWS", [(["ALT", "C"], "Close window"), (["ALT", "F"], "Maximize"), (["ALT", "TAB"], "Window switcher")]))
    for keys, desc in rows]
keybinds.shortcuts = lambda: list(_BINDS)
keybinds.config_mtime = lambda: 1


def draw(panel, w, h):
    surf = cairo.ImageSurface(cairo.FORMAT_ARGB32, w, h)
    cr = cairo.Context(surf)
    panel.render(cr, w, h)
    panel.tick()                       # what a size samples only while it's shown
    panel.render(cr, w, h)
    return surf


class Layouts(unittest.TestCase):
    def test_every_class_of_every_panel(self):
        for name, cls in P.CORE.items():
            panel = cls({"name": name})
            panel.tick()
            seen = {}
            for cname, lo, hi, start in cls.size_classes():
                for (w, h) in (start, lo, hi):
                    with self.subTest(panel=name, size=cname, at=(w, h)):
                        self.assertEqual(cls.size_class(w, h), cname)
                        surf = draw(panel, w, h)
                        regions = panel.regions
                        self.assertTrue(regions, "no hover regions")
                        for r in regions:
                            self.assertTrue((r[4] or "").strip(), f"a region without a hint at {r[:4]}")
                            self.assertTrue(-1 <= r[0] and -1 <= r[1] and r[0] + r[2] <= w + 1
                                            and r[1] + r[3] <= h + 1, f"a region outside the panel: {r[:4]} {r[4]}")
                        if (w, h) == start:
                            seen[cname] = bytes(surf.get_data())[:]
            if len(seen) > 1:          # each class is a layout of its own, not one picture scaled
                hints = set()
                for cname, lo, hi, start in cls.size_classes():
                    draw(panel, *start)
                    hints.add(frozenset(r[4].split(":")[0] for r in panel.regions))
                self.assertEqual(len(hints), len(seen), f"{name}: two size classes draw the same parts")


class LabLayouts(unittest.TestCase):
    """LAB (bromigos-homelab's), with demo_lab.py's made-up lab: its compact summary, the
    standard panel, and the large one with the constellation hologram."""

    def setUp(self):
        lab_py = os.path.join(os.path.dirname(HERE), "homelab", "widgets", "_lab.py")
        if not os.path.isfile(lab_py):
            self.skipTest("no homelab/ beside widgets/")
        demo._demo_lab()
        sys.path.insert(0, os.path.dirname(lab_py))
        try:
            import _lab
        except ImportError as e:
            self.skipTest(f"bromigos_homelab isn't importable: {e}")
        self.lab = _lab

    def test_every_class(self):
        panel = self.lab.LabPanel({})
        panel.lab.poll()
        parts = set()
        for cname, lo, hi, start in panel.size_classes():
            for (w, h) in (start, lo, hi):
                with self.subTest(size=cname, at=(w, h)):
                    draw(panel, w, h)
                    for r in panel.regions:
                        self.assertTrue((r[4] or "").strip())
                        self.assertTrue(-1 <= r[0] and -1 <= r[1] and r[0] + r[2] <= w + 1 and r[1] + r[3] <= h + 1,
                                        f"outside: {r[:4]} {r[4]}")
            parts.add(frozenset(r[4].split(":")[0] for r in panel.regions))
        self.assertEqual(len(parts), 3)
        self.assertTrue(any("constellation" in r[4] for r in panel.regions))       # the large one's hologram

    def test_the_hologram_holds_still_with_reduced_motion(self):
        panel = self.lab.LabPanel({})
        panel.lab.poll()
        panel.pulse_at = 0
        draw(panel, 980, 700)
        motion = self.lab.D.T.motion
        try:
            self.lab.D.T.motion = lambda: "full"
            self.assertTrue(panel.animating)                    # turning: redrawn at the heartbeat's 10 fps
            self.lab.D.T.motion = lambda: "reduced"
            self.assertFalse(panel.animating)                   # still: drawn only when the data changes
            draw(panel, 470, 640)
            self.lab.D.T.motion = lambda: "full"
            self.assertFalse(panel.animating)                   # not at the standard size
        finally:
            self.lab.D.T.motion = motion


if __name__ == "__main__":
    unittest.main()
