"""The layouts (widgets/layouts.py): every ready-made layout and every theme's own, fitted to
five screens (1920x1080, 2560x1440, a 3440x1440 ultrawide, 3840x2160 and a 1366x768 laptop)
on each scene (the Wick's den, which the colour themes share, Tidewell and Mire). None
overlaps another, all are inside the area, none covers a scene's focal points, and none
covers more than a third of the screen but Everything (which says so). Widgets that can't
show anything are left out with the reason; small screens take smaller sizes; Tidy up
untangles the stacking bug's layout; a saved layout comes back where it was."""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REPO = os.path.dirname(HERE)
sys.path.insert(0, HERE)
os.environ.setdefault("XDG_CONFIG_HOME", tempfile.mkdtemp())       # no user's layouts
import arrange as A  # noqa: E402
import layouts as L  # noqa: E402

SCREENS = [(1920, 1080), (2560, 1440), (3440, 1440), (3840, 2160), (1366, 768)]
SCENES = ("wick", "tidewell", "mire", "cinder")
FIXTURE = os.path.join(HERE, "tests", "fixtures", "layout-stacked.json")

# every widget there is, with its real size classes: the gallery's entries, read once in a
# child (demo readings, the homelab's widgets with a made-up lab, so all of them are here)
_CATALOG = None


def catalog():
    global _CATALOG
    if _CATALOG is None:
        home = tempfile.mkdtemp(prefix="layouts-")
        env = dict(os.environ, HOME=home, XDG_CONFIG_HOME=os.path.join(home, ".config"),
                   XDG_STATE_HOME=os.path.join(home, ".state"), XDG_DATA_HOME=os.path.join(home, ".data"),
                   XDG_CACHE_HOME=os.path.join(home, ".cache"), BROMIGOS_WIDGETS_DEMO="1",
                   BROMIGOS_WIDGETS_DEMO_LAB="1", BROMIGOS_HOMELAB=os.path.join(REPO, "homelab"),
                   DBUS_SESSION_BUS_ADDRESS="disabled:")
        code = "import json, gallery, layouts as L; print(json.dumps(L.catalog_of(gallery.entries(), lambda p: True)))"
        r = subprocess.run([sys.executable, "-c", code], cwd=HERE, env=env, capture_output=True, text=True, timeout=120)
        shutil.rmtree(home, ignore_errors=True)
        if r.returncode != 0:
            raise RuntimeError(r.stderr[-2000:])
        doc = json.loads(r.stdout.strip().splitlines()[-1])
        for c in doc.values():
            c["classes"] = [(n, tuple(lo), tuple(hi), tuple(st)) for n, lo, hi, st in c["classes"]]
        _CATALOG = doc
    return {k: dict(v) for k, v in _CATALOG.items()}


def check_fit(t, r, scr, info, cat):
    """No overlaps (a gap between each), inside the area, off the hard keep-clear areas,
    each at a size its classes allow."""
    rects = {n: (p["x"], p["y"], p["width"], p["height"]) for n, p in r["placed"].items()}
    names = list(rects)
    for i, a in enumerate(names):
        x, y, w, h = rects[a]
        assert 0 <= x and 0 <= y and x + w <= scr.W and y + h <= scr.H, f"{a} outside the area: {rects[a]}"
        for b in names[i + 1:]:
            assert not A.overlaps(rects[a], rects[b], L.GAP - 1), f"{a} and {b} overlap: {rects[a]} {rects[b]}"
        for c in L.scene_rects(info["clear"], scr, info["focus"]):
            if not c[5]:
                assert not A.overlaps(rects[a], c[:4]), f"{a} covers {c[4]}: {rects[a]} {c[:4]}"
        if r["placed"][a]["size"]:
            cls = next(c for c in cat[a]["classes"] if c[0] == r["placed"][a]["size"])
            assert cls[1][0] <= w <= cls[2][0] and cls[1][1] <= h <= cls[2][1], f"{a} {w}x{h} outside {cls}"


class Fitting(unittest.TestCase):
    def test_every_layout_on_every_scene_and_screen(self):
        cat = catalog()
        ts = L.templates()
        self.assertTrue({"minimal", "developer", "homelab", "streamer", "media", "gamer", "everything"} <= set(ts))
        for scene in SCENES:
            info = L.scene_info(scene, os.path.join(REPO, "themes", scene))
            self.assertIsNotNone(info["recommended"], scene)
            for tid, t in [("theme", info["recommended"])] + list(ts.items()):
                for sw, sh in SCREENS:
                    with self.subTest(scene=scene, layout=tid, screen=f"{sw}x{sh}"):
                        scr = L.Screen.size(sw, sh)
                        r = L.fit(t, scr, cat, info["clear"], info["focus"])
                        check_fit(t, r, scr, info, cat)
                        self.assertTrue(r["placed"], "nothing placed")
                        if t.get("pack"):
                            self.assertEqual(r["over_budget"], r["coverage"] > L.BUDGET)
                        else:
                            self.assertLessEqual(r["coverage"], L.BUDGET + 1e-6)
                        for x in r["left_out"]:
                            self.assertTrue(x["why"], x)

    def test_the_theme_layouts_keep_their_widgets_on_a_big_screen(self):
        cat = catalog()
        for scene in ("wick", "tidewell", "mire"):
            info = L.scene_info(scene, os.path.join(REPO, "themes", scene))
            r = L.fit(info["recommended"], L.Screen.size(2560, 1440), cat, info["clear"], info["focus"])
            with self.subTest(scene=scene):
                self.assertEqual(r["left_out"], [])
                self.assertIn("system", r["placed"])

    def test_small_screens_take_smaller_sizes_and_big_ones_bigger(self):
        cat = catalog()
        t = L.templates()["minimal"]
        info = L.scene_info("wick", os.path.join(REPO, "themes", "wick"))
        small = L.fit(t, L.Screen.size(1366, 768), cat, info["clear"])
        big = L.fit(t, L.Screen.size(3840, 2160), cat, info["clear"])
        self.assertEqual(small["placed"]["system"]["size"], "compact")
        self.assertEqual(big["placed"]["system"]["size"], "large")

    def test_widgets_that_cant_show_anything_are_left_out_with_why(self):
        cat = catalog()
        cat["github"] = dict(cat["github"], available=False, why="nobody is signed in to GitHub")
        t = L.templates()["developer"]
        r = L.fit(t, L.Screen.size(2560, 1440), cat)
        self.assertIn("gitlab", r["placed"])                # the next one there is
        self.assertNotIn("github", r["placed"])
        cat["gitlab"] = dict(cat["gitlab"], available=False, why="nobody is signed in to GitLab")
        r = L.fit(t, L.Screen.size(2560, 1440), cat)
        gone = next(x for x in r["left_out"] if x["name"] == "github")
        self.assertEqual(gone["title"], "GitHub or GitLab")
        self.assertIn("signed in", gone["why"])
        del cat["lab"]                                     # no homelab here
        r = L.fit(L.templates()["homelab"], L.Screen.size(2560, 1440), cat)
        self.assertIn("homelab", next(x for x in r["left_out"] if x["name"] == "lab")["why"])
        self.assertIn("alerts", r["placed"])

    def test_accounts_nobody_signed_in_to_are_unavailable(self):
        entries = [{"name": "github", "title": "GITHUB", "available": True, "sizes": [
            {"name": "standard", "min": [400, 200], "max": [700, 600], "start": [460, 320]}],
            "form": [{"key": "account", "kind": "secret-signin", "provider": "github"}]}]
        self.assertFalse(L.catalog_of(entries, lambda p: False)["github"]["available"])
        self.assertIn("GitHub", L.catalog_of(entries, lambda p: False)["github"]["why"])
        self.assertTrue(L.catalog_of(entries, lambda p: True)["github"]["available"])

    def test_the_budget_leaves_out_the_least_important(self):
        cat = catalog()
        t = L.parse({"title": "Lots", "budget": 0.1, "widget": [
            {"name": "system", "size": "standard", "side": "left", "priority": 1},
            {"name": "network", "size": "standard", "side": "left", "priority": 2},
            {"name": "workbench", "size": "standard", "side": "left", "lane": 2, "priority": 9}]}, "lots")
        r = L.fit(t, L.Screen.size(2560, 1440), cat)
        self.assertLessEqual(r["coverage"], 0.1 + 1e-6)
        self.assertIn("system", r["placed"])
        self.assertNotIn("workbench", r["placed"])
        self.assertIn("scene shows", next(x for x in r["left_out"] if x["name"] == "workbench")["why"])

    def test_ultrawide_keep_clear_follows_the_cover(self):
        info = L.scene_info("wick", os.path.join(REPO, "themes", "wick"))
        r16 = L.scene_rects(info["clear"], L.Screen(2560, 1440))
        r21 = L.scene_rects(info["clear"], L.Screen(3440, 1440))
        # the den is scaled to 3440 wide and cropped top and bottom: wider, shifted up
        self.assertAlmostEqual(r21[0][2] / r16[0][2], 3440 / 2560, places=2)
        self.assertLess(r21[0][1], r16[0][1] * 3440 / 2560)


class Scenes(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.old = {k: os.environ.get(k) for k in ("BROMIGOS_SHARE_DIR", "XDG_STATE_HOME", "XDG_CONFIG_HOME")}
        os.environ.update(BROMIGOS_SHARE_DIR=os.path.join(self.tmp, "share"),
                          XDG_STATE_HOME=os.path.join(self.tmp, "state"), XDG_CONFIG_HOME=os.path.join(self.tmp, "config"))

    def tearDown(self):
        for k, v in self.old.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_a_colour_theme_is_the_wicks_den(self):
        info = L.scene_info("cinder")
        self.assertEqual(info["scene"], "wick")
        self.assertEqual(info["recommended"]["title"], "Made for the Wick")
        self.assertTrue(any("screens" in c["name"] for c in info["clear"]))

    def test_a_colour_theme_with_a_file_of_its_own_is_its_own_scene(self):
        d = os.path.join(self.tmp, "share", "themes", "cinder", "widgets")
        os.makedirs(d)
        with open(os.path.join(d, "layout.toml"), "w") as f:
            f.write('scene_title = "Cinder"\n[[clear]]\nname = "the pour"\nrect = [0.4, 0.3, 0.2, 0.4]\n'
                    'title = "Made for Cinder"\n[[widget]]\nname = "system"\nside = "right"\n')
        info = L.scene_info("cinder")
        self.assertEqual((info["scene"], info["recommended"]["title"]), ("cinder", "Made for Cinder"))

    def test_a_world_without_a_file_keeps_the_middle_clear(self):
        d = os.path.join(self.tmp, "share", "themes", "harbour", "live")
        os.makedirs(d)
        with open(os.path.join(d, "world.toml"), "w") as f:
            f.write('format = 1\nname = "Harbour"\n[view]\nfocus = [1500, 700]\n')
        info = L.scene_info("harbour")
        self.assertEqual((info["scene"], info["kind"], info["recommended"]), ("harbour", "world", None))
        self.assertEqual(info["clear"], L.CENTRE)
        self.assertEqual(info["focus"], (1500.0, 700.0))

    def test_memory_per_scene_and_undo(self):
        st = {"system": {"x": 1, "y": 2, "width": 470, "height": 470, "visible": True, "ping": "kept out"}}
        L.remember("wick", st)
        self.assertEqual(L.recall("wick"), {"system": {"x": 1, "y": 2, "width": 470, "height": 470, "visible": True}})
        self.assertIsNone(L.recall("tidewell"))
        self.assertIsNone(L.recall("../etc"))
        L.save_undo(st, "the Homelab layout", "wick")
        self.assertEqual(L.peek_undo()["what"], "the Homelab layout")
        self.assertEqual(L.take_undo()["scene"], "wick")
        self.assertIsNone(L.take_undo())
        doc = {"version": 2, "panels": [{"name": "system", "x": 9, "y": 9, "width": 300, "height": 180},
                                        {"name": "network", "x": 9, "y": 300, "ping": [{"label": "WAN"}]}]}
        back = L.restore(doc, L.recall("wick"))
        self.assertEqual(A.state_of(back)["system"]["x"], 1)
        self.assertFalse(A.state_of(back)["network"]["visible"])     # not in the remembered one: off
        self.assertEqual(back["panels"][1]["ping"], [{"label": "WAN"}])  # its own settings kept


class Tidy(unittest.TestCase):
    def test_the_stacked_layout_untangled(self):
        """The regression: ten widgets switched on at once all landed on one remembered spot,
        then dragged partly apart. Tidy up leaves none overlapping, keeps them all, keeps
        off the den's screens and window, and keeps their order down each side."""
        with open(FIXTURE) as f:
            doc = json.load(f)
        st = A.state_of(doc)
        self.assertTrue(L.overlapping(st))                      # the fixture is the bug
        info = L.scene_info("wick", os.path.join(REPO, "themes", "wick"))
        scr = L.Screen(2560, 1440)
        r = L.tidy(st, scr, catalog(), info["clear"], info["focus"])
        # seventeen widgets don't all fit beside the den's screens: Tidy uses the scene too,
        # but never puts one on another
        check_fit(None, r, scr, dict(info, clear=[]), catalog())
        self.assertEqual(r["left_out"], [])
        self.assertEqual(set(r["placed"]), {n for n, s in st.items() if s.get("visible", True)})
        new = {n: dict(p, visible=True) for n, p in r["placed"].items()}
        self.assertEqual(L.overlapping(new), [])
        # the left column's order is kept: system above network above storage
        ys = [r["placed"][n]["y"] for n in ("system", "network", "storage")]
        self.assertEqual(ys, sorted(ys))

    def test_a_few_widgets_stay_off_the_scene(self):
        info = L.scene_info("wick", os.path.join(REPO, "themes", "wick"))
        st = {n: {"x": 1200 + 10 * i, "y": 500 + 10 * i, "width": w, "height": h, "visible": True}
              for i, (n, w, h) in enumerate((("system", 470, 470), ("network", 470, 262), ("storage", 470, 214),
                                              ("nowplaying", 460, 200)))}
        scr = L.Screen(2560, 1440)
        r = L.tidy(st, scr, catalog(), info["clear"], info["focus"])
        check_fit(None, r, scr, info, catalog())
        self.assertEqual(set(r["placed"]), set(st))

    def test_no_room_is_said_never_stacked(self):
        cat = catalog()
        st = {f"w{i}": {"x": 0, "y": 0, "width": 700, "height": 500, "visible": True} for i in range(9)}
        r = L.tidy(st, L.Screen(1366, 734), cat)
        self.assertTrue(r["left_out"])
        self.assertEqual(L.overlapping({n: dict(p, visible=True) for n, p in r["placed"].items()}), [])


class Saving(unittest.TestCase):
    def test_a_saved_layout_comes_back_where_it_was(self):
        cat = catalog()
        st = {"system": {"x": 24, "y": 24, "width": 470, "height": 470, "visible": True},
              "nowplaying": {"x": 2000, "y": 1100, "width": 460, "height": 200, "visible": True},
              "storage": {"x": 24, "y": 900, "width": 470, "height": 214, "visible": False}}
        scr = L.Screen(2560, 1440)
        text = L.from_state(st, scr, cat, "My desk")
        import tomllib
        t = L.parse(tomllib.loads(text), "my-desk", "yours")
        r = L.fit(t, scr, cat)
        self.assertEqual(set(r["placed"]), {"system", "nowplaying"})
        for n in ("system", "nowplaying"):
            self.assertEqual((r["placed"][n]["x"], r["placed"][n]["y"]), (st[n]["x"], st[n]["y"]))

    def test_mistakes_are_named(self):
        for doc, word in (({"widget": [{"side": "left"}]}, "no name"), ({"widget": [{"name": "x", "side": "up"}]}, "side"),
                          ({"widget": [{"name": "x", "side": "left", "from": "left"}]}, "column"),
                          ({"budget": 2, "widget": [{"name": "x", "side": "left"}]}, "budget"), ({}, "no widgets")):
            with self.subTest(word=word):
                with self.assertRaises(ValueError) as e:
                    L.parse(doc, "bad")
                self.assertIn(word, str(e.exception))


class Strict(unittest.TestCase):
    def test_place_never_stacks_when_strict(self):
        full = [(0, 0, 1000, 1000)]
        self.assertIsNone(A.place(400, 300, full, (1000, 1000), strict=True))
        self.assertEqual(A.place(400, 300, full, (1000, 1000)), (28, 16))      # a monitor gone: still shown
        self.assertIn("No room for GPU", A.no_room("GPU"))


class ContentHeights(unittest.TestCase):
    """A widget that fits its content gets the height its content needs, inside its class
    (the catalog's natural heights: the running panels' health file, or measured)."""

    def wick(self):
        return L.scene_info("wick", os.path.join(REPO, "themes", "wick"))

    def tpl(self, extra=""):
        import tomllib
        return L.parse(tomllib.loads('''
            [[widget]]
            name = "lab"
            size = "standard"
            side = "left"
            priority = 1
            ''' + extra + '''
            [[widget]]
            name = "alerts"
            size = "standard"
            side = "left"
            lane = 2
            priority = 2
        '''), "t")

    def test_lab_as_tall_as_its_lab_and_alerts_as_short_as_its_rows(self):
        cat = catalog()
        cat["lab"] = dict(cat["lab"], fit="content", natural={"standard": 913, "large": 913, "compact": 104})
        cat["alerts"] = dict(cat["alerts"], fit="content", natural={"standard": 152})
        scr = L.Screen.size(2560, 1440)
        info = self.wick()
        r = L.fit(self.tpl(), scr, cat, info["clear"], info["focus"], budget=1.0)
        self.assertEqual(r["placed"]["lab"]["height"], 920)          # 913, to the 8 px grid, inside 600..1200
        self.assertEqual(r["placed"]["alerts"]["height"], 152)       # four rows: not the 300 it starts at
        check_fit(self.tpl(), r, scr, info, cat)

    def test_more_than_the_class_allows_gets_its_tallest(self):
        cat = catalog()
        cat["lab"] = dict(cat["lab"], fit="content", natural={"standard": 5000})
        r = L.fit(self.tpl(), L.Screen.size(2560, 1440), cat, budget=1.0)
        self.assertEqual(r["placed"]["lab"]["height"], 1200)

    def test_fixed_keeps_the_start_height(self):
        cat = catalog()
        cat["lab"] = dict(cat["lab"], fit="content", natural={"standard": 913})
        r = L.fit(self.tpl('fit = "fixed"\n'), L.Screen.size(2560, 1440), cat, budget=1.0)
        self.assertEqual(r["placed"]["lab"]["height"], 640)
        with self.assertRaises(ValueError):
            self.tpl('fit = "tall"\n')

    def test_no_natural_height_keeps_the_start(self):
        cat = catalog()
        cat["lab"] = dict(cat["lab"], natural={})
        r = L.fit(self.tpl(), L.Screen.size(2560, 1440), cat, budget=1.0)
        self.assertEqual(r["placed"]["lab"]["height"], 640)

    def test_tidy_gives_each_its_content_height(self):
        cat = catalog()
        cat["alerts"] = dict(cat["alerts"], fit="content", natural={"standard": 152})
        state = {"alerts": {"x": 600, "y": 300, "width": 460, "height": 300, "visible": True},
                 "system": {"x": 24, "y": 24, "width": 470, "height": 320, "visible": True}}
        info = self.wick()
        r = L.tidy(state, L.Screen.size(2560, 1440), cat, info["clear"], info["focus"])
        self.assertEqual(r["placed"]["alerts"]["height"], 152)
        self.assertEqual(r["placed"]["system"]["height"], 320)       # no preference: its own size


if __name__ == "__main__":
    unittest.main()
