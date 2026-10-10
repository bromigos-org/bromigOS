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

    def _mine(self, doc):
        os.makedirs(self.path(".config", "bromigos", "widgets"), exist_ok=True)
        with open(self.path(".config", "bromigos", "widgets", "layout.json"), "w") as f:
            json.dump(doc, f)

    def test_monitor_puts_every_panel_on_one_forgetting_their_own(self):
        own = {"make": "Dell Inc.", "model": "DELL P2419H", "serial": "7NK8JR2", "name": "HDMI-A-1"}
        self._mine({"version": 2, "monitor": "", "panels": [{"name": "system", "x": 1, "y": 1, "output": own},
                                                             {"name": "notes", "x": 2, "y": 2}],
                    "plugins": {"lab": {"x": 3, "y": 3, "output": own}}})
        d = self.cmd("panels")
        self.assertEqual((self.panel(d, "system")["output"], self.panel(d, "system")["output_model"]),
                         ("HDMI-A-1", "Dell Inc. DELL P2419H"))
        self.assertEqual(self.panel(d, "notes")["output"], "")
        d = self.cmd("panels", "monitor", "DP-1")
        self.assertEqual((d["monitor"], self.panel(d, "system")["output"]), ("DP-1", ""))
        with open(self.path(".config", "bromigos", "widgets", "layout.json")) as f:
            mine = json.load(f)
        self.assertNotIn("output", mine["panels"][0])
        self.assertNotIn("output", mine["plugins"]["lab"])

    def test_an_old_layout_gets_each_panels_monitor_on_a_change(self):
        # one "monitor" for every panel (before version 2): each panel gets it, by make,
        # model and serial (the hyprctl stand-in's HDMI-A-1)
        self._mine({"monitor": "HDMI-A-1", "panels": [{"name": "system", "x": 1, "y": 1},
                                                      {"name": "notes", "x": 2, "y": 2}]})
        self.cmd("panels", "move", "notes", "40", "60", env={"HYPRLAND_INSTANCE_SIGNATURE": "test"})
        with open(self.path(".config", "bromigos", "widgets", "layout.json")) as f:
            mine = json.load(f)
        self.assertEqual(mine["version"], 2)
        self.assertEqual(mine["panels"][0]["output"]["serial"], "7NK8JR2")
        self.assertEqual(mine["panels"][1]["output"]["name"], "HDMI-A-1")

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
            if w.get("available", True) or w["visible"]:                     # one the gallery offers
                self.assertIn(w["category"], [c["id"] for c in d["categories"]])
            self.assertTrue(w["author"])
            self.assertLessEqual(w["min_size"][0], w["max_size"][0])
        system = next(w for w in d["widgets"] if w["name"] == "system")
        self.assertEqual((system["source"], system["author"], system["key"]), ("bromigos", "bromigOS", "SUPER + S"))
        self.assertFalse(next(w for w in d["widgets"] if w["name"] == "weather")["visible"])

    def test_gallery_categories_are_what_the_widgets_declare(self):
        # a widget of your own in a category bromigOS doesn't have: it gets a button too
        plug = self.path(".config", "bromigos", "plugins", "widgets")
        os.makedirs(plug)
        with open(os.path.join(plug, "tide_watch.py"), "w") as f:
            f.write("from panels import Panel\n\n\nclass Tide(Panel):\n    name, title = 'tide_watch', 'TIDE'\n"
                    "    description = 'The tides'\n    category = 'harbour-life'\n\n\nPANEL = Tide\n")
        d = self.cmd("panels", "gallery")
        cats = {c["id"]: c for c in d["categories"]}
        offered = {w["category"] for w in d["widgets"] if w.get("available", True) or w["visible"]}
        self.assertEqual(set(cats), offered)
        self.assertEqual((cats["harbour-life"]["label"], cats["harbour-life"]["count"]), ("Harbour", 1))
        self.assertIn("(1 widget)", cats["harbour-life"]["hint"])
        self.assertEqual(list(cats)[0], "system")                             # bromigOS's own order first
        self.assertEqual(list(cats)[-1], "harbour-life")
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
        self.assertEqual(d["values"], {"place": "Oslo", "hosts": [], "every": 60, "gh": []})   # gh: every account
        self.assertEqual([f["kind"] for f in d["form"]], ["text", "list", "number", "secret-signin"])
        d = self.cmd("panels", "set", "hello", "place", "Bergen")
        self.assertEqual(d["values"]["place"], "Bergen")
        d = self.cmd("panels", "set", "hello", "hosts", "a", "b")
        self.assertEqual(d["values"]["hosts"], ["a", "b"])
        self.assertIn('hosts = ["a", "b"]', self.read(".config", "bromigos", "widgets", "hello.toml"))
        self.assertIn("number", self.cmd("panels", "set", "hello", "every", "soon", ok=False)["error"])
        self.cmd("panels", "set", "hello", "every", "5", ok=False)
        self.cmd("panels", "set", "hello", "gh", "token", ok=False)            # a sign-in's value is account names
        self.assertEqual(self.cmd("panels", "set", "hello", "gh", "default")["values"]["gh"], ["default"])
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

    # ------------------------------------------------------------------ never stacked; layouts
    def _overlaps(self, d):
        """The shown panels that overlap, from the layout written (status's own check)."""
        return d["overlapping"]

    def test_switching_on_widget_after_widget_never_stacks(self):
        """The stacking bug: about ten widgets switched on in a row from Customize (each a
        `bromigos panels show NAME`) all landed on one spot. Each now gets its own place, and
        when there's no room left it says so instead."""
        said_no_room = False
        for name in ("gpu", "nowplaying", "updates", "vector", "youtube", "discord", "calendars", "ci", "weather",
                     "connections", "workbench", "notes", "shortcuts"):
            r = self.run_cmd("panels", "show", name)
            doc = json.loads(r.stdout)
            if doc.get("ok") is False:
                self.assertIn("No room for", doc["error"])
                said_no_room = True
                continue
            self.assertEqual(self._overlaps(doc), [], name)
            p = self.panel(doc, name)
            self.assertTrue(p["visible"] and p["x"] is not None, name)
        d = self.cmd("panels")
        self.assertEqual(self._overlaps(d), [])
        self.assertGreaterEqual(sum(1 for p in d["panels"] if p["visible"]), 10)
        # a widget made bigger stays clear of the others, or moves
        d = self.cmd("panels", "size", "network", "wide")
        self.assertEqual(self._overlaps(d), [])
        del said_no_room

    def test_add_with_no_room_says_so(self):
        big = [{"name": n, "x": x, "y": y, "width": 1240, "height": 700} for n, x, y in
               (("system", 0, 0), ("network", 1260, 0), ("storage", 0, 720), ("notes", 1260, 720))]
        self._mine({"version": 2, "monitor": "", "panels": big + [{"name": "weather", "visible": False}]})
        doc = self.cmd("panels", "add", "weather", ok=False)
        self.assertIn("No room for Weather: hide something or try a smaller size", doc["error"])
        self.assertFalse(self.panel(self.cmd("panels"), "weather")["visible"])      # nothing changed

    def test_layouts_are_listed_fitted_to_the_screen(self):
        d = self.cmd("panels", "layouts")
        ids = [x["id"] for x in d["layouts"]]
        self.assertEqual(ids[0], "theme")                                        # the theme's own first
        self.assertEqual(d["layouts"][0]["made_for"], "the Wick")
        for want in ("minimal", "developer", "homelab", "streamer", "media", "gamer", "everything"):
            self.assertIn(want, ids)
        self.assertEqual((d["scene"], d["screen"]["width"], d["first_run"]), ("wick", 2560, True))
        self.assertTrue(any("screens" in c["name"] for c in d["clear"]))
        dev = next(x for x in d["layouts"] if x["id"] == "developer")
        self.assertTrue(any("signed in" in n for n in dev["notes"]))           # nobody's signed in here

    def test_apply_undo_keeps_each_widgets_own_settings(self):
        d = self.cmd("panels", "layout", "apply", "minimal")
        on = {p["name"] for p in d["panels"] if p["visible"]}
        self.assertEqual(on, {"system", "weather", "nowplaying"})
        self.assertEqual(self._overlaps(d), [])
        self.assertTrue(d["undo"])
        with open(self.path(".config", "bromigos", "widgets", "layout.json")) as f:
            mine = json.load(f)
        net = next(p for p in mine["panels"] if p["name"] == "network")
        self.assertFalse(net["visible"])
        self.assertEqual(net["ping"][1]["host"], "1.1.1.1")                     # its own settings: kept
        d = self.cmd("panels", "layout", "undo")
        self.assertTrue(self.panel(d, "network")["visible"])
        self.assertFalse(self.panel(d, "nowplaying")["visible"] if any(p["name"] == "nowplaying" for p in d["panels"])
                         else False)
        d = self.cmd("panels", "layout", "undo")                                 # again: back to Minimal
        self.assertFalse(self.panel(d, "network")["visible"])
        self.cmd("panels", "layout", "apply", "nope", ok=False)

    def test_apply_writes_through_a_symlink(self):
        dots = os.path.join(self.home, "dotfiles")
        os.makedirs(dots)
        with open(os.path.join(REPO, "widgets", "layout.json")) as f:
            text = f.read()
        with open(os.path.join(dots, "layout.json"), "w") as f:
            f.write(text)
        os.makedirs(self.path(".config", "bromigos", "widgets"))
        link = self.path(".config", "bromigos", "widgets", "layout.json")
        os.symlink(os.path.join(dots, "layout.json"), link)
        self.cmd("panels", "layout", "apply", "theme")
        self.assertTrue(os.path.islink(link))
        with open(os.path.join(dots, "layout.json")) as f:
            self.assertTrue(next(p for p in json.load(f)["panels"] if p["name"] == "nowplaying")["visible"])

    def test_save_a_layout_of_your_own_and_apply_it(self):
        self.cmd("panels", "layout", "apply", "theme")
        before = {p["name"]: (p["x"], p["y"]) for p in self.cmd("panels")["panels"] if p["visible"]}
        d = self.cmd("panels", "layout", "save", "My desk")
        self.assertEqual(d["id"], "my-desk")
        self.assertTrue(os.path.exists(d["path"]))
        self.cmd("panels", "layout", "apply", "minimal")
        d = self.cmd("panels", "layout", "apply", "my-desk")
        self.assertEqual({p["name"]: (p["x"], p["y"]) for p in d["panels"] if p["visible"]}, before)
        self.assertIn("my-desk", [x["id"] for x in self.cmd("panels", "layouts")["layouts"]])

    def test_tidy_untangles_the_stacked_layout(self):
        with open(os.path.join(REPO, "widgets", "tests", "fixtures", "layout-stacked.json")) as f:
            doc = json.load(f)
        doc["panels"] = [p for p in doc["panels"] if p["name"] not in ("lab", "alerts", "labjobs", "game_servers")]
        self._mine(doc)
        self.assertTrue(self._overlaps(self.cmd("panels")))
        d = self.cmd("panels", "tidy")
        self.assertEqual(self._overlaps(d), [])
        self.assertIn("Tidied", d["said"])
        self.assertTrue(self._overlaps(self.cmd("panels", "layout", "undo")))  # undo puts it back

    def test_each_theme_has_its_own_layout_and_colour_themes_share_the_wicks(self):
        self.cmd("panels", "layout", "apply", "minimal")                         # the Wick: Minimal
        d = self.cmd("panels", "layout", "theme", "tidewell")                    # first time: made for it
        self.assertTrue(d["changed"])
        self.assertEqual(d["layout"], "theme-tidewell")
        tide = {p["name"] for p in d["panels"] if p["visible"]}
        self.assertNotEqual(tide, {"system", "weather", "nowplaying"})
        d = self.cmd("panels", "layout", "theme", "cinder")                      # the den again: Minimal back
        self.assertEqual({p["name"] for p in d["panels"] if p["visible"]}, {"system", "weather", "nowplaying"})
        d = self.cmd("panels", "layout", "theme", "wick")                        # the same den: nothing changes
        self.assertFalse(d["changed"])
        d = self.cmd("panels", "layout", "theme", "tidewell")                    # Tidewell's, as it was
        self.assertEqual({p["name"] for p in d["panels"] if p["visible"]}, tide)
        # one layout for every theme: the other themes' memories go, each gets it fitted
        self.cmd("panels", "layout", "apply", "minimal", "--all-themes")
        d = self.cmd("panels", "layout", "theme", "mire")
        self.assertEqual(d["layout"], "minimal")


if __name__ == "__main__":
    unittest.main()
