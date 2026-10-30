"""Settings › Bluetooth (settings/pages/bluetooth.py): its words, and that its search entries
and pairing kinds come from the shared core. The page itself is drawn offscreen by
tools/settings/render.sh --page bluetooth --fixtures (with --bt-open for its dialogs), against
the stand-in bluez."""
import importlib.util
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
DESKTOP = os.path.dirname(HERE)
sys.path[:0] = [os.path.join(DESKTOP, "settings"), os.path.join(DESKTOP, "lib")]

try:
    import gi
    gi.require_version("Gtk", "4.0")
    gi.require_version("Adw", "1")
    from gi.repository import Adw, Gtk  # noqa: F401
    HAVE_GTK = True
except (ImportError, ValueError):
    HAVE_GTK = False

import bromigos_bluez as B  # noqa: E402


def page_module():
    spec = importlib.util.spec_from_file_location("bt_page", os.path.join(DESKTOP, "settings", "pages", "bluetooth.py"))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


@unittest.skipUnless(HAVE_GTK, "GTK 4 and libadwaita's Python bindings aren't installed")
class Page(unittest.TestCase):
    def setUp(self):
        self.m = page_module()

    def test_words(self):
        w = self.m._words
        d = {"paired": True, "connected": True}
        self.assertEqual(w(d, {"mode": "hifi", "codec": "LDAC"}), "Connected · Hi-fi · LDAC")
        self.assertEqual(w(d, {"mode": "headset", "codec": "mSBC"}), "Connected · Headset + mic · mSBC")
        self.assertEqual(w({"paired": True, "connected": False}), "Not connected")
        self.assertEqual(w({"paired": False, "connected": False}), "Found nearby")
        self.assertEqual(w(d, op="connecting"), "Connecting…")

    def test_search_finds_the_new_parts(self):
        keys = {e.key for e in self.m.PAGE.entries}
        for k in ("pair-wizard", "paired", "scan", "nearby", "reset", "repair", "tui", "console", "power",
                  "discoverable", "audio-default"):
            self.assertIn(k, keys)
        words = " ".join(self.m.PAGE.keywords)
        for w in ("controller", "devices", "xbox"):
            self.assertIn(w, words)

    def test_the_wizard_uses_the_cores_kinds(self):
        with open(os.path.join(DESKTOP, "settings", "pages", "bluetooth.py")) as f:
            src = f.read()
        self.assertIn("B.PAIR_KINDS", src)
        self.assertNotIn("Hold the small pair button", src, "the steps live in bromigos_bluez only")
        self.assertIn("Hold the small pair button", " ".join(B.PAIR_KINDS[0][2]))

    def test_the_clock_holds_still_under_reduced_motion(self):
        c = self.m.Clock()
        c.still = True
        a = Gtk.DrawingArea()
        c.watch(a, lambda: True)
        self.assertIsNone(c.timer, "no timer at all under reduced motion")


if __name__ == "__main__":
    unittest.main()
