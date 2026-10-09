"""`bromigos panels`: the desktop panels' layout (bromigOS's widgets/layout.json until the
first change, then the user's copy, every other key kept) and weather.toml; nothing runs,
so nothing is told."""
import json
import os
import unittest

from cmdtest import REPO, CmdTest


class PanelsTest(CmdTest):
    def setUp(self):
        super().setUp()
        os.makedirs(os.path.join(self.env["BROMIGOS_SHARE_DIR"], "widgets"))
        os.symlink(os.path.join(REPO, "widgets", "layout.json"),
                   os.path.join(self.env["BROMIGOS_SHARE_DIR"], "widgets", "layout.json"))

    def panel(self, d, name):
        return next(p for p in d["panels"] if p["name"] == name)

    def test_status_from_bromigos_layout(self):
        d = self.cmd("panels")
        self.assertFalse(d["yours"])
        self.assertTrue(self.panel(d, "system")["visible"])
        self.assertFalse(self.panel(d, "weather")["visible"])
        self.assertEqual(self.panel(d, "system")["key"], "SUPER + S")
        self.assertEqual(self.panel(d, "connections")["title"], "Connections")
        self.assertFalse(d["running"])
        self.assertFalse(d["weather"]["exists"])

    def test_show_hide_keeps_the_rest(self):
        d = self.cmd("panels", "show", "connections")
        self.assertTrue(self.panel(d, "connections")["visible"])
        self.assertTrue(d["yours"])
        self.assertIn("next start", d["note"])
        with open(self.path(".config", "bromigos", "widgets", "layout.json")) as f:
            mine = json.load(f)
        net = next(p for p in mine["panels"] if p["name"] == "network")
        self.assertEqual(net["ping"][1]["host"], "1.1.1.1")                 # keys Settings doesn't know: kept
        self.assertIn("_comment", mine)
        d = self.cmd("panels", "hide", "system")
        self.assertFalse(self.panel(d, "system")["visible"])
        self.cmd("panels", "show", "nope", ok=False)

    def test_move_size_monitor(self):
        d = self.cmd("panels", "move", "notes", "40", "60")
        self.assertEqual((self.panel(d, "notes")["x"], self.panel(d, "notes")["y"]), (40, 60))
        d = self.cmd("panels", "size", "notes", "500", "300")
        self.assertEqual((self.panel(d, "notes")["width"], self.panel(d, "notes")["height"]), (500, 300))
        self.cmd("panels", "size", "notes", "5", "300", ok=False)
        self.cmd("panels", "move", "notes", "left", "0", ok=False)
        d = self.cmd("panels", "monitor", "DP-1")
        self.assertEqual(d["monitor"], "DP-1")
        self.cmd("panels", "monitor", "DP-1; rm", ok=False)

    def test_weather(self):
        d = self.cmd("panels", "weather", "place", "San", "Diego")
        self.assertEqual(d["weather"]["place"], "San Diego")
        d = self.cmd("panels", "weather", "units", "imperial")
        self.assertEqual((d["weather"]["place"], d["weather"]["units"]), ("San Diego", "imperial"))
        d = self.cmd("panels", "weather", "coords", "32.72", "-117.16")
        self.assertEqual((d["weather"]["lat"], d["weather"]["lon"], d["weather"]["place"]), (32.72, -117.16, None))
        self.cmd("panels", "weather", "coords", "100", "0", ok=False)
        self.cmd("panels", "weather", "units", "kelvin", ok=False)
        d = self.cmd("panels", "weather", "name", "Home")
        self.assertEqual(d["weather"]["name"], "Home")
        text = self.read(".config", "bromigos", "weather.toml")
        self.assertIn("units = \"imperial\"", text)
        d = self.cmd("panels", "weather", "clear")
        self.assertFalse(d["weather"]["exists"])

    def test_reset(self):
        self.cmd("panels", "hide", "system")
        self.cmd("panels", "weather", "place", "Oslo")
        d = self.cmd("panels", "reset")
        self.assertFalse(d["yours"])
        self.assertTrue(self.panel(d, "system")["visible"])
        self.assertFalse(d["weather"]["exists"])

    def test_a_broken_layout_is_said(self):
        os.makedirs(self.path(".config", "bromigos", "widgets"))
        with open(self.path(".config", "bromigos", "widgets", "layout.json"), "w") as f:
            f.write("{ nope")
        self.assertIn("layout.json", self.cmd("panels", ok=False)["error"])


if __name__ == "__main__":
    unittest.main()
