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

    def test_reset_keeps_a_dotfiles_symlink(self):
        dots = self.path("dotfiles", "widgets")
        os.makedirs(dots)
        real = os.path.join(dots, "layout.json")
        with open(real, "w") as f:
            json.dump({"monitor": "DP-9", "panels": [{"name": "system", "x": 1, "y": 1, "visible": False}]}, f)
        os.makedirs(self.path(".config", "bromigos", "widgets"))
        link = self.path(".config", "bromigos", "widgets", "layout.json")
        os.symlink(real, link)
        d = self.cmd("panels", "move", "system", "64", "32")
        self.assertTrue(os.path.islink(link))                               # a change writes through it
        with open(real) as f:
            self.assertEqual(json.load(f)["panels"][0]["x"], 64)
        d = self.cmd("panels", "reset")
        self.assertTrue(os.path.islink(link))                               # and so does reset
        self.assertTrue(self.panel(d, "system")["visible"])
        with open(real) as f:
            self.assertEqual(json.load(f)["monitor"], "")

    def test_add_puts_it_in_a_free_spot(self):
        d = self.cmd("panels", "add", "weather")
        w = self.panel(d, "weather")
        self.assertTrue(w["visible"])
        boxes = [(p["x"], p["y"], p["width"], p["height"]) for p in d["panels"]
                 if p["visible"] and p["name"] != "weather"]
        mine = (w["x"], w["y"], w["width"], w["height"])
        for b in boxes:                                                       # clear of every shown panel
            self.assertTrue(mine[0] + mine[2] <= b[0] or b[0] + b[2] <= mine[0] or
                            mine[1] + mine[3] <= b[1] or b[1] + b[3] <= mine[1], (mine, b))
        self.cmd("panels", "add", "nope", ok=False)

    def test_gallery_lists_every_panel_with_its_words(self):
        d = self.cmd("panels", "gallery")
        names = [w["name"] for w in d["widgets"]]
        for n in ("system", "network", "storage", "shortcuts", "workbench", "notes", "weather", "connections"):
            self.assertIn(n, names)
        for w in d["widgets"]:
            self.assertTrue(w["description"], w["name"])
            self.assertIn(w["category"], [c["id"] for c in d["categories"]])
            self.assertTrue(w["author"])
            self.assertLessEqual(w["min_size"][0], w["max_size"][0])
        system = next(w for w in d["widgets"] if w["name"] == "system")
        self.assertEqual((system["source"], system["author"], system["key"]), ("bromigos", "bromigOS", "SUPER + S"))
        self.assertFalse(next(w for w in d["widgets"] if w["name"] == "weather")["visible"])

    def test_a_plugin_panel_switches_on_and_off(self):
        plug = self.path(".config", "bromigos", "plugins", "widgets")
        os.makedirs(plug)
        with open(os.path.join(plug, "hello.py"), "w") as f:
            f.write("from panels import Panel\n\nclass Hello(Panel):\n    name, title = 'hello', 'HELLO'\n"
                    "    description = 'Says hello'\n    category, reads = 'fun', 'nothing'\n\n"
                    "    def draw(self, cr, w, h):\n        pass\n\nPANEL = Hello\n")
        g = self.cmd("panels", "gallery")
        hello = next(w for w in g["widgets"] if w["name"] == "hello")
        self.assertEqual((hello["source"], hello["author"], hello["category"]), ("yours", "you", "fun"))
        d = self.cmd("panels", "hide", "hello")
        self.assertFalse(self.panel(d, "hello")["visible"])

    def test_a_widgets_own_settings(self):
        plug = self.path(".config", "bromigos", "plugins", "widgets")
        os.makedirs(plug)
        with open(os.path.join(plug, "hello.py"), "w") as f:
            f.write("from panels import Panel\n\nclass Hello(Panel):\n    name, title = 'hello', 'HELLO'\n"
                    "    settings = [{'key': 'place', 'label': 'Place', 'kind': 'text', 'default': 'Oslo'},\n"
                    "                {'key': 'hosts', 'label': 'Hosts', 'kind': 'list', 'default': []},\n"
                    "                {'key': 'every', 'label': 'Every', 'kind': 'number', 'default': 60, 'min': 10},\n"
                    "                {'key': 'gh', 'label': 'GitHub', 'kind': 'secret-signin', 'provider': 'github'}]\n\n"
                    "    def draw(self, cr, w, h):\n        pass\n\nPANEL = Hello\n")
        d = self.cmd("panels", "settings", "hello")
        self.assertEqual(d["values"], {"place": "Oslo", "hosts": [], "every": 60})
        self.assertEqual([f["kind"] for f in d["form"]], ["text", "list", "number", "secret-signin"])
        d = self.cmd("panels", "set", "hello", "place", "Bergen")
        self.assertEqual(d["values"]["place"], "Bergen")
        d = self.cmd("panels", "set", "hello", "hosts", "a", "b")
        self.assertEqual(d["values"]["hosts"], ["a", "b"])
        self.assertIn('hosts = ["a", "b"]', self.read(".config", "bromigos", "widgets", "hello.toml"))
        self.assertIn("number", self.cmd("panels", "set", "hello", "every", "soon", ok=False)["error"])
        self.cmd("panels", "set", "hello", "every", "5", ok=False)
        self.cmd("panels", "set", "hello", "gh", "token", ok=False)            # a sign-in is never a value
        self.cmd("panels", "set", "hello", "nope", "x", ok=False)
        d = self.cmd("panels", "unset", "hello", "place")
        self.assertEqual(d["values"]["place"], "Oslo")
        g = next(w for w in self.cmd("panels", "gallery")["widgets"] if w["name"] == "hello")
        self.assertEqual(g["values"]["hosts"], ["a", "b"])
        self.assertIn("settings of its own", self.cmd("panels", "settings", "system", ok=False)["error"])

    def test_edit_asks_the_panels(self):
        stub = os.path.join(self.tmp, "stub")             # a stand-in bromigos-widgets: never the real one
        os.makedirs(stub)
        with open(os.path.join(stub, "bromigos-widgets"), "w") as f:
            f.write('#!/bin/sh\necho "$*" >> "$HOME/widgets.log"\n[ -z "$FAIL" ]\n')
        os.chmod(os.path.join(stub, "bromigos-widgets"), 0o755)
        env = {"PATH": f"{stub}:{self.env['PATH']}"}
        self.assertIn("Esc saves", self.cmd("panels", "edit", env=env)["said"])
        self.assertEqual(self.read("widgets.log").split("\n")[0], "edit on")
        doc = self.cmd("panels", "edit", ok=False, env=dict(env, FAIL="1"))
        self.assertIn("edit mode", doc["error"])

    def test_a_broken_layout_is_said(self):
        os.makedirs(self.path(".config", "bromigos", "widgets"))
        with open(self.path(".config", "bromigos", "widgets", "layout.json"), "w") as f:
            f.write("{ nope")
        self.assertIn("layout.json", self.cmd("panels", ok=False)["error"])


if __name__ == "__main__":
    unittest.main()
