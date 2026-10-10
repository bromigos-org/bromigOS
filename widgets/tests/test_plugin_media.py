"""The MEDIA panel (plugins/media.py) as a remote for the den TV: a row for each of the
den's three screens, the screen chosen by a click on its row, and the buttons acting on
that screen (`bromigos-live tv … --screen`), with demo readings and a stand-in control
socket. Nothing reaches a live layer."""
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import plugintest  # noqa: E402  (a throwaway config home, the import path)

import cairo  # noqa: E402

import media  # noqa: E402



class MediaRemote(unittest.TestCase):
    def setUp(self):
        cls = media.MediaPanel
        self.mod = media
        p = mock.patch.object(self.mod, "_demo", lambda: True)
        p.start()
        self.addCleanup(p.stop)
        self.panel = plugintest.make(cls, demo=True)
        self.panel.tick()

    def test_a_row_for_each_screen_and_every_size(self):
        self.assertEqual([r["screen"] for r in self.panel.rows], ["big", "wave", "emblem"])
        plugintest.every_class(self, self.panel)
        hints = plugintest.draw(self.panel, 760, 250)
        self.assertTrue(any("The scope: Lo-fi" in h for h in hints), hints)
        self.assertTrue(any("channel guide" in h for h in hints), hints)
        out = os.environ.get("BROMIGOS_TEST_SHOTS")
        if out:
            os.makedirs(out, exist_ok=True)
            for name, (w, h) in (("compact", (380, 150)), ("wide", (760, 250)), ("large", (760, 560))):
                surf = cairo.ImageSurface(cairo.FORMAT_ARGB32, w, h)
                self.panel.render(cairo.Context(surf), w, h)
                surf.write_to_png(os.path.join(out, f"media-{name}.png"))

    def test_guide_button_opens_the_standalone_app(self):
        with mock.patch("subprocess.Popen") as start:
            self.panel._guide()
        self.assertEqual(start.call_args.args[0], ["bromigos-tv-guide"])
        self.assertTrue(start.call_args.kwargs["start_new_session"])

    def test_a_click_chooses_the_screen_the_buttons_act_on(self):
        p = self.panel
        p.sel = "big"
        plugintest.draw(p, 760, 250)
        row = next(r for r in p.regions if r[4].startswith("The scope"))
        row[5]()                                                # a click on the scope's row
        self.assertEqual(p.sel, "wave")
        asked = []
        with mock.patch.object(self.mod, "_ask", lambda cmd, timeout=1.5: asked.append(cmd)), \
                mock.patch.object(p, "tick", lambda: None):
            plugintest.draw(p, 760, 250)
            nxt = next(r for r in p.regions if r[4].startswith("The next channel"))
            nxt[5]()
            snd = next(r for r in p.regions if r[4].startswith("Sound from"))
            snd[5]()
        self.assertEqual(asked, ["tv next --screen wave", "tv sound toggle --screen wave"])


if __name__ == "__main__":
    unittest.main()
