"""Storage names change the text at every size, keeping the real mount as the action."""
import os
import sys
import tempfile
import unittest
from collections import deque
from unittest import mock

import cairo

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import draw as D
import panels as P
import widget_settings as WS


class StorageNames(unittest.TestCase):
    def setUp(self):
        self.home = tempfile.TemporaryDirectory()
        self.addCleanup(self.home.cleanup)
        env = mock.patch.dict(os.environ, {"HOME": self.home.name, "XDG_CONFIG_HOME": self.home.name})
        env.start()
        self.addCleanup(env.stop)
        gib = 1024 ** 3
        self.mount = {"mount": "/mnt/Work", "device": "nvme0n1p1", "fstype": "btrfs", "mounted": True,
                      "size": 1800 * gib, "used": 140 * gib, "free": 1660 * gib, "pct": 7.8}
        with mock.patch.object(P.S, "storage", return_value=[self.mount]), mock.patch.object(P.S, "DiskIO") as io:
            io.return_value.read_hist = deque([0, 0])
            io.return_value.write_hist = deque([0, 0])
            io.return_value.read = io.return_value.write = 0
            self.panel = P.StoragePanel()

    def render(self, size):
        w, h = size
        with D.record() as marks:
            self.panel.render(cairo.Context(cairo.ImageSurface(cairo.FORMAT_ARGB32, w, h)), w, h)
        return marks

    def test_saved_name_at_every_size_keeps_tooltip_and_click_path(self):
        WS.set_value("storage", P.StoragePanel.settings, "display_names", ["/mnt/Work = Projects"])
        for name, _lo, _hi, start in P.StoragePanel.size_classes():
            with self.subTest(size=name):
                shown = []
                show = D.PangoCairo.show_layout

                def capture(cr, layout):
                    shown.append((layout.get_text(), layout.is_ellipsized()))
                    return show(cr, layout)

                with mock.patch.object(D.PangoCairo, "show_layout", side_effect=capture):
                    marks = self.render(start)
                self.assertIn("PROJECTS", [m["what"] for m in marks])
                self.assertIn(("PROJECTS", False), shown)
                self.assertNotIn(("PROJECTS", True), shown)
                regions = [r for r in self.panel.regions if r[5]]
                self.assertTrue(regions)
                for region in regions:
                    self.assertIn("/mnt/Work", region[4])
                    with mock.patch.object(P.subprocess, "Popen") as launch:
                        region[5]()
                    launch.assert_called_once_with(["xdg-open", "/mnt/Work"], start_new_session=True)
        WS.unset("storage", "display_names")
        self.assertIn("/MNT/WORK", [m["what"] for m in self.render((470, 214))])
        self.assertEqual(self.mount["mount"], "/mnt/Work")

    def test_long_name_fits_and_invalid_settings_keep_path(self):
        label = "A very long display name for a drive with projects"
        WS.set_value("storage", P.StoragePanel.settings, "display_names", [f"/mnt/Work = {label}"])
        for name, lo, _hi, _start in P.StoragePanel.size_classes():
            with self.subTest(size=name):
                names = [m for m in self.render(lo) if m["what"] == label.upper()]
                self.assertTrue(names)
                for mark in names:
                    left, _top, right, _bottom = mark["box"]
                    self.assertGreaterEqual(left, 16)
                    self.assertLessEqual(right, lo[0] - 16)
        for invalid in ("wrong type", [None, 12, "/mnt/Work = ", "missing separator", "/mnt = Different",
                                      "/mnt/Work = Work\x00hidden"]):
            with self.subTest(invalid=invalid), mock.patch.object(self.panel, "setting", return_value=invalid):
                self.assertEqual(self.panel._display_name("/mnt/Work"), "/mnt/Work")

    def test_multiline_name_uses_one_line_above_usage(self):
        WS.set_value("storage", P.StoragePanel.settings, "display_names", ["/mnt/Work = Work\n\tArchive"])
        for _name, lo, _hi, _start in P.StoragePanel.size_classes():
            lines = []
            show = D.PangoCairo.show_layout

            def capture(cr, layout):
                if layout.get_text() == "WORK ARCHIVE":
                    lines.append(layout.get_line_count())
                return show(cr, layout)

            with mock.patch.object(D.PangoCairo, "show_layout", side_effect=capture):
                self.render(lo)
            self.assertTrue(lines)
            self.assertEqual(set(lines), {1})


if __name__ == "__main__":
    unittest.main()
