"""The theme switcher (bin/bromigos-theme-switcher) and its previews (lib/bromigos_previews.py)
without a display: the grid at every monitor size, the stamps that key the cache, the bar's
modules as waybar would fill them, the window's border and shadow read from the theme, where
the terminal goes, and what each card says. The pictures themselves are drawn offscreen by
tools/theme-switcher/render.sh (a GPU or Mesa, kitty and weston), checked by its check.py.

    PYTHONPATH=lib python -m unittest discover -s tests
"""
import importlib.machinery
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
DESKTOP = os.path.dirname(HERE)
REPO = os.path.dirname(DESKTOP)
sys.path.insert(0, os.path.join(DESKTOP, "lib"))
sys.path.insert(0, os.path.join(REPO, "lib"))

import bromigos_previews as PV  # noqa: E402

try:
    import PIL  # noqa: F401  (the previews are drawn with it; a package build may lack it)
    HAVE_PIL = True
except ImportError:
    HAVE_PIL = False


def load_switcher():
    path = os.path.join(DESKTOP, "bin", "bromigos-theme-switcher")
    loader = importlib.machinery.SourceFileLoader("bromigos_theme_switcher", path)
    spec = importlib.util.spec_from_loader(loader.name, loader)
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    return mod


SW = load_switcher()
SIZES = [(1366, 768), (1920, 1080), (2560, 1440), (3440, 1440)]


class GridTest(unittest.TestCase):
    def test_every_size_fits_its_monitor(self):
        for mw, mh in SIZES:
            for n in (3, 9, 11, 30):
                g = SW.Grid(mw, mh, n)
                with self.subTest(size=f"{mw}x{mh}", n=n):
                    self.assertGreaterEqual(g.margin, 16)
                    self.assertLessEqual(g.w + 2 * g.margin, mw)
                    self.assertLessEqual(g.h + 2 * g.margin, mh)
                    # the cards and their gaps inside the panel, no horizontal scroll
                    self.assertLessEqual(g.cols * g.card_w + (g.cols - 1) * g.GAP, g.inner)
                    self.assertGreaterEqual(g.card_w, 300)
                    self.assertLessEqual(g.card_w, 640)
                    self.assertAlmostEqual(g.card_h / g.card_w, 9 / 16, delta=0.01)
                    self.assertGreater(g.view_h, g.card_h + g.CAPTION)    # a whole row always shows

    def test_columns_grow_with_the_width(self):
        cols = [SW.Grid(mw, mh, 9).cols for mw, mh in SIZES]
        self.assertEqual(cols, sorted(cols))
        self.assertGreaterEqual(SW.Grid(3440, 1440, 9).cols, 5)
        self.assertLessEqual(SW.Grid(1366, 768, 9).cols, 3)

    def test_nine_themes_show_without_scrolling_where_there_is_room(self):
        for mw, mh in SIZES[1:]:
            g = SW.Grid(mw, mh, 9)
            with self.subTest(size=f"{mw}x{mh}"):
                self.assertLessEqual(g.height(g.cols, 9), g.view_h)

    def test_too_many_scroll_instead_of_shrinking_past_the_floor(self):
        g = SW.Grid(1366, 768, 40)
        self.assertGreater(g.height(g.cols, 40), g.view_h)
        self.assertGreaterEqual(g.card_w, 300)


class StampTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.a = os.path.join(self.tmp, "a", "teal")
        shutil.copytree(os.path.join(REPO, "themes", "rime"), self.a)

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def test_the_same_files_anywhere_give_the_same_stamp(self):
        b = os.path.join(self.tmp, "b", "teal")
        shutil.copytree(self.a, b)
        self.assertEqual(PV.stamp("teal", [self.a]), PV.stamp("teal", [b]))
        self.assertRegex(PV.stamp("teal", [self.a]), r"^[0-9a-f]{12}$")

    def test_a_changed_colour_changes_it(self):
        before = PV.stamp("teal", [self.a])
        with open(os.path.join(self.a, "colors.toml"), "a") as f:
            f.write("\n# a change\n")
        self.assertNotEqual(before, PV.stamp("teal", [self.a]))

    def test_readmes_dot_files_and_art_sources_dont_count(self):
        before = PV.stamp("teal", [self.a])
        for rel in ("README.md", ".git/HEAD", "art/source.png", "holo/README.md"):
            p = os.path.join(self.a, rel)
            os.makedirs(os.path.dirname(p), exist_ok=True)
            with open(p, "w") as f:
                f.write("x")
        self.assertEqual(before, PV.stamp("teal", [self.a]))

    def test_a_new_live_layer_changes_it(self):
        # the den drawn differently (its recolour) must redraw every preview
        before = PV.stamp("teal", [self.a])
        saved = list(PV._LIVE_HASH)
        try:
            PV._LIVE_HASH[:] = ["another live layer"]
            self.assertNotEqual(before, PV.stamp("teal", [self.a]))
        finally:
            PV._LIVE_HASH[:] = saved
        self.assertEqual(before, PV.stamp("teal", [self.a]))
        # and it reads the live layer's code and the colour libraries
        self.assertRegex(PV.live_code_hash(), r"^[0-9a-f]{64}$")

    @unittest.skipUnless(HAVE_PIL, "needs Pillow")
    def test_the_still_den_is_in_the_themes_colours(self):
        try:
            import numpy  # noqa: F401
        except ImportError:
            self.skipTest("needs numpy")

        class Box:
            current = self.tmp

        def still(theme, primary):
            with open(os.path.join(self.tmp, "palette.json"), "w") as f:
                json.dump({"theme": theme, "colors": {"background": "#090606", "dim": "#8a3f1e",
                                                      "primary": primary, "soft": "#ffc8a0"}}, f)
            import numpy as np
            return np.asarray(PV.den_still(Box()).resize((320, 180))).reshape(-1, 3).astype(float)
        wick = still("wick", "#39ff14")
        cinder = still("cinder", "#ff7a2a")
        self.assertGreater(wick[:, 1].mean(), wick[:, 0].mean())             # the Wick: green, as painted
        self.assertGreater(cinder[:, 0].mean(), cinder[:, 1].mean())         # Cinder: ember, not green

    def test_the_old_switchers_cards_are_removed(self):
        cache = os.path.join(self.tmp, "cache")
        os.makedirs(cache)
        keep = ["mire-0123456789ab.jpg", "mire-0123456789ab.json", "catalog-teal-0123456789.img", "render.log"]
        old = ["sunder-11720ff0d975.png", "no-preview.png", "catalog-teal-glass-0123456789.png"]
        for n in keep + old:
            open(os.path.join(cache, n), "w").close()
        saved = PV.CACHE
        PV.CACHE = cache
        try:
            self.assertEqual(sorted(PV.clean_legacy()), sorted(old))
            self.assertEqual(sorted(os.listdir(cache)), sorted(keep))
        finally:
            PV.CACHE = saved

    def test_cached_finds_only_this_themes_pictures(self):
        cache = os.path.join(self.tmp, "cache")
        os.makedirs(cache)
        for n in ("mire-0123456789ab.jpg", "mire-extra-0123456789ab.jpg", "mire-xyz.jpg", "mire-0123456789ab.json"):
            open(os.path.join(cache, n), "w").close()
        old = PV.CACHE
        PV.CACHE = cache
        try:
            self.assertEqual([os.path.basename(p) for p in PV.cached("mire")], ["mire-0123456789ab.jpg"])
            self.assertEqual(PV.current("mire", "ffffffffffff"), (os.path.join(cache, "mire-0123456789ab.jpg"), False))
            self.assertEqual(PV.current("mire", "0123456789ab")[1], True)
            self.assertEqual(PV.current("tidewell", "0123456789ab"), (None, False))
            # the Wick's and its colour variants' (wick-mire, wick-tidewell) never mix
            for n in ("wick-0123456789ab.jpg", "wick-mire-0123456789ab.jpg", "wick-tidewell-fedcba987654.jpg"):
                open(os.path.join(cache, n), "w").close()
            self.assertEqual([os.path.basename(p) for p in PV.cached("wick")], ["wick-0123456789ab.jpg"])
            self.assertEqual([os.path.basename(p) for p in PV.cached("wick-mire")], ["wick-mire-0123456789ab.jpg"])
        finally:
            PV.CACHE = old


class BarTest(unittest.TestCase):
    def setUp(self):
        self.cur = tempfile.mkdtemp()
        with open(os.path.join(self.cur, "waybar-markup.jsonc"), "w") as f:
            f.write('// the theme\'s markup colours\n{"network": {"format-ethernet": '
                    '"<span color=\'#4e6b4e\'>⇣</span>{bandwidthDownBytes:>8} {bandwidthUpBytes:>8}"},}\n')

    def tearDown(self):
        shutil.rmtree(self.cur)

    def test_every_module_of_the_default_bar_is_drawn_as_waybar_names_it(self):
        cfg, mods = PV.bar_modules(self.cur, os.path.join(DESKTOP, "waybar"))
        names = {m[2] for m in mods}
        for want in ("custom-launcher", "workspaces", "window", "cpu", "memory", "custom-gpu", "temperature",
                     "custom-storage", "network", "pulseaudio", "clock", "custom-vector", "custom-idle",
                     "custom-settings", "tray", "mpris"):
            self.assertIn(want, names)
        laptop = {"battery", "power-profiles-daemon"}
        listed = {m.split("#")[0].split("/")[-1] for side in ("modules-left", "modules-center", "modules-right")
                  for m in cfg[side]}
        self.assertEqual(len(mods), len(listed - laptop))
        for side, kind, name, text, _cls in mods:
            if text is not None:
                self.assertNotIn("{", text, name)      # every format filled
        net = next(m for m in mods if m[2] == "network")
        self.assertIn("2.3MB/s", net[3])               # the theme's format, merged in
        self.assertEqual(next(m for m in mods if m[2] == "clock")[3], "21:24:07")

    def test_the_nested_bar_shows_no_reading_of_this_machine(self):
        # waybar's own modules read the machine: each gets its demo text as a fixed format and
        # thresholds it can't reach, so neither a value nor a warning colour is this machine's
        box = type("B", (), {"current": self.cur})()
        doc = PV._demo_builtins(box)
        self.assertEqual(set(doc), {"cpu", "memory", "temperature", "clock", "network"})
        for mod, d in doc.items():
            self.assertNotIn("{", d["format"], mod)
        self.assertEqual(doc["clock"]["format"], "21:24:07")
        self.assertIn("2.3MB/s", doc["network"]["format-wifi"])
        self.assertIn("2.3MB/s", doc["network"]["format-ethernet"])
        # past any reading, and within the byte waybar keeps a state's threshold in
        for mod in ("cpu", "memory"):
            for st in ("warning", "critical"):
                self.assertTrue(100 < doc[mod]["states"][st] <= 255, (mod, st))
        self.assertTrue(200 < doc["temperature"]["critical-threshold"] <= 255)

    def test_jsonc_comments_and_trailing_commas(self):
        p = os.path.join(self.cur, "x.jsonc")
        with open(p, "w") as f:
            f.write('{\n "url": "https://bromigos.org", // a comment\n /* block */ "list": [1, 2,],\n}\n')
        self.assertEqual(PV._jsonc(p), {"url": "https://bromigos.org", "list": [1, 2]})


class SceneTest(unittest.TestCase):
    def test_the_default_is_the_switchers_picture(self):
        sc = PV.load_scene()
        self.assertEqual([p["name"] for p in sc["panels"]], list(PV.PANELS))
        self.assertEqual(sc["terminal"], {})
        self.assertEqual(PV.panel_rects(sc)[0][:2], (28, 16 + PV.BAR_H))

    def test_names_take_their_places_and_lab_sits_beside_system(self):
        sc = PV.load_scene({"panels": ["system", "weather", "lab"], "terminal": False})
        by = {p["name"]: p for p in sc["panels"]}
        self.assertEqual((by["weather"]["x"], by["weather"]["y"]), (514, 616))     # layout.json's place
        self.assertEqual((by["lab"]["x"], by["lab"]["y"], by["lab"]["height"]), (514, 16, 640))
        self.assertNotIn("visible", by["weather"])     # shown, though the default layout hides it
        self.assertIs(sc["terminal"], False)

    def test_a_file_places_its_panels_and_its_terminal_script_beside_it(self):
        tmp = tempfile.mkdtemp()
        try:
            with open(os.path.join(tmp, "s.json"), "w") as f:
                json.dump({"panels": [{"name": "storage", "x": 600, "y": 40}],
                           "terminal": {"at": [10, 20, 300, 200], "script": "t.sh"}, "notes": "hi"}, f)
            sc = PV.load_scene(os.path.join(tmp, "s.json"))
            self.assertEqual((sc["panels"][0]["x"], sc["panels"][0]["width"]), (600, 470))
            self.assertEqual(sc["terminal"]["script"], os.path.join(tmp, "t.sh"))
            self.assertEqual(sc["notes"], "hi")
        finally:
            shutil.rmtree(tmp)

    def test_a_panel_with_no_place_is_refused(self):
        with self.assertRaises(ValueError):
            PV.load_scene({"panels": ["no-such-panel"]})


class DemoPanelsTest(unittest.TestCase):
    """Every panel a picture can show draws on demo readings (widgets/demo.py), offscreen."""

    def test_every_panel_draws_with_demo_readings(self):
        try:
            import cairo  # noqa: F401
        except ImportError:
            self.skipTest("no pycairo")
        tmp = tempfile.mkdtemp()
        try:
            names = ["system", "network", "storage", "workbench", "weather", "connections", "lab"]
            env = dict(os.environ, PV_WIDGETS=os.path.join(REPO, "widgets"), HOME=tmp, XDG_CONFIG_HOME=tmp,
                       XDG_STATE_HOME=tmp, XDG_RUNTIME_DIR=tmp, BROMIGOS_WIDGETS_DEMO_LAB="1",
                       BROMIGOS_HOMELAB=os.path.join(REPO, "homelab"),
                       BROMIGOS_PRIVATE_CONFIG=os.path.join(tmp, "none.json"))
            r = subprocess.run([sys.executable, PV.__file__, "--child", "widgets", tmp] + names, env=env,
                               capture_output=True, text=True, timeout=120)
            self.assertEqual(r.returncode, 0, r.stderr[-800:])
            with open(os.path.join(tmp, "panels.json")) as f:
                sizes = json.load(f)
            self.assertEqual(sorted(sizes), sorted(names))
            self.assertEqual(sizes["lab"], [470, 640])
        finally:
            shutil.rmtree(tmp)

    def test_the_made_up_lab_names_no_real_service_or_share(self):
        sys.path.insert(0, os.path.join(REPO, "widgets"))
        from demo_lab import DEMO_LAB
        text = json.dumps(DEMO_LAB).lower()
        for word in ("k8s_", "rustfs", ".lan", ".local"):
            self.assertNotIn(word, text)
        # the lab's own names (private overlay) and internal tools' (salted hashes), never spelled here
        sys.path.insert(0, os.path.join(REPO, "tools", "privacy"))
        import private_words
        self.assertEqual(private_words.Finder().reasons(text), [])


class DecorationsTest(unittest.TestCase):
    def test_the_border_and_shadow_come_from_the_rendered_hyprland_lua(self):
        tmp = tempfile.mkdtemp()
        try:
            os.makedirs(os.path.join(tmp, "cur"))
            with open(os.path.join(tmp, "cur", "hyprland.lua"), "w") as f:
                f.write('return {\n    active_border   = { colors = { "rgb(b8e05a)", "rgb(4a6b3a)" }, angle = 45 },\n'
                        '    inactive_border = "rgba(1c2d27ee)",\n    shadow          = "rgba(b8e05a30)",\n}\n')

            class B:
                current = os.path.join(tmp, "cur")
            d = PV.decorations(B, {"colors": {"primary": "#b8e05a"}})
            self.assertEqual(d["border"], [(0xb8, 0xe0, 0x5a, 255), (0x4a, 0x6b, 0x3a, 255)])
            self.assertEqual(d["shadow"], (0xb8, 0xe0, 0x5a, 0x30))
            self.assertEqual(d["border_size"], 2)
            with open(os.path.join(tmp, "cur", "hyprland.lua"), "w") as f:
                f.write('return {\n    active_border   = "rgb(ffffff)",\n    border_size     = 3,\n}\n')
            d = PV.decorations(B, {"colors": {"primary": "#39ff14"}})
            self.assertEqual(d["border"], [(255, 255, 255, 255)])
            self.assertEqual(d["border_size"], 3)
        finally:
            shutil.rmtree(tmp)

    @unittest.skipUnless(HAVE_PIL, "needs python-pillow")
    def test_the_terminal_stays_clear_of_the_bar_and_the_panels(self):
        from PIL import Image
        bg = Image.new("RGB", (PV.DESK_W, PV.DESK_H), (10, 20, 10))
        # a bright scene on the right: the terminal should avoid it
        bg.paste((240, 240, 200), (1200, 0, PV.DESK_W, PV.DESK_H))
        panels = [(28, 50, 470, 452), (28, 518, 470, 262)]
        x, y, w, h = PV.place_terminal(bg, 34, panels, 2)
        self.assertGreaterEqual(y, 34)
        self.assertLessEqual(x + w, PV.DESK_W)
        self.assertLessEqual(y + h, PV.DESK_H)
        for px, py, pw, ph in panels:
            self.assertTrue(x >= px + pw or y >= py + ph)
        self.assertLess(x, 1200)
        # the den (no world): always the same spot, so the colour themes' previews line up
        self.assertEqual(PV.place_terminal(bg, 34, panels, 2, scene=False)[:2],
                         PV.place_terminal(Image.new("RGB", bg.size), 34, panels, 2, scene=False)[:2])


class CardTest(unittest.TestCase):
    def test_a_card_says_what_it_is_and_what_enter_does(self):
        e = SW.Entry("mire", "Mire", "A night bayou: black mirror water, moss and fireflies.", "world", ["system"])
        self.assertEqual(e.tagline(), "A night bayou")
        self.assertIn("bromigos theme set mire", e.hint())
        self.assertIn("world", e.hint())
        e.current = True
        self.assertIn("In use now", e.hint())
        c = SW.Entry("teal-glass", "Teal Glass", "Teal glass on deep slate.", "colour", install=["bromigos", "ext",
                                                                                                   "install", "x"])
        self.assertTrue(c.catalog)
        self.assertIn("install it from the catalog", c.hint())
        self.assertIn("catalog", c.haystack())

    def test_catalog_entries_skip_installed_and_bundled(self):
        tmp = tempfile.mkdtemp()
        try:
            p = os.path.join(tmp, "cat.json")
            with open(p, "w") as f:
                json.dump({"results": [{"name": "mire", "bundled": True}, {"name": "wick"},
                                       {"name": "teal-glass", "display_name": "Teal Glass", "tags": ["colours"],
                                        "install": "bromigos ext install teal-glass"},
                                       {"name": "done", "installed": True}]}, f)
            os.environ["BROMIGOS_THEME_CATALOG"] = p
            got = SW.catalog({"wick"})
            self.assertEqual([e.name for e in got], ["teal-glass"])
            self.assertEqual(got[0].install, ["bromigos", "ext", "install", "teal-glass"])
        finally:
            os.environ.pop("BROMIGOS_THEME_CATALOG", None)
            shutil.rmtree(tmp)

    def test_the_wick_is_its_den_worlds_are_worlds(self):
        self.assertEqual(SW.kind_of("wick"), "den")
        self.assertEqual(SW.kind_of("mire"), "world")
        self.assertEqual(SW.kind_of("cinder"), "colour")
        # the Wick in a world's colours is a colour theme (the den), never that world
        self.assertEqual(SW.kind_of("wick-tidewell"), "colour")
        self.assertEqual(SW.kind_of("wick-mire"), "colour")
        self.assertEqual(SW.Entry("wick", "Wick", "", "den").kind_label(), "DEN")

    def test_theme_colours_resolve_names(self):
        c = SW.theme_colors("wick")
        for role in ("background", "panel", "primary", "muted"):
            self.assertRegex(c[role], r"^#[0-9a-fA-F]{6}$")



class NoGpuTest(unittest.TestCase):
    """After a graphics driver update the previews mustn't fail theme after theme (2026-10-09:
    each theme tried the nested desktop twice and failed at EGL, then cached a lesser picture)."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.saved = PV.CACHE, PV.render_one, os.environ.get("BROMIGOS_GPU_ROOT")
        PV.CACHE = os.path.join(self.tmp, "cache")

    def tearDown(self):
        PV.CACHE, PV.render_one, root = self.saved
        if root is None:
            os.environ.pop("BROMIGOS_GPU_ROOT", None)
        else:
            os.environ["BROMIGOS_GPU_ROOT"] = root
        shutil.rmtree(self.tmp, ignore_errors=True)

    def machine(self, module, libs):
        root = os.path.join(self.tmp, "root-" + module)
        os.makedirs(os.path.join(root, "sys/module/nvidia"))
        os.makedirs(os.path.join(root, "usr/lib"))
        with open(os.path.join(root, "sys/module/nvidia/version"), "w") as f:
            f.write(module + "\n")
        for v in libs:
            open(os.path.join(root, "usr/lib", f"libEGL_nvidia.so.{v}"), "w").close()
        open(os.path.join(root, "usr/lib", "libEGL_nvidia.so.0"), "w").close()
        return root

    def test_the_driver_mismatch(self):
        why = PV.driver_mismatch(self.machine("615.71.09", ["615.78.08"]))
        self.assertIn("615.78.08 installed, 615.71.09 running", why)
        self.assertIsNone(PV.driver_mismatch(self.machine("615.78.08", ["615.78.08"])))
        self.assertIsNone(PV.driver_mismatch(os.path.join(self.tmp, "no-nvidia")))

    def test_nothing_is_tried_until_the_restart(self):
        os.environ["BROMIGOS_GPU_ROOT"] = self.machine("615.71.09", ["615.78.08"])
        tried = []
        PV.render_one = lambda name, *a, **k: tried.append(name)
        r = PV.render(["wick", "mire"], force=True)
        self.assertEqual(tried, [])
        self.assertEqual([x["name"] for x in r], ["wick", "mire"])
        self.assertTrue(all("restarts" in x["held"] and not x.get("error") for x in r))
        with open(os.path.join(PV.CACHE, "render.log")) as f:
            self.assertIn("not drawing: the graphics driver was updated", f.read())

    def test_one_gpu_failure_ends_the_run(self):
        os.environ["BROMIGOS_GPU_ROOT"] = self.machine("615.78.08", ["615.78.08"])
        tried = []

        def fail(name, *a, **k):
            tried.append(name)
            raise PV.GpuLost("the GPU didn't start for the nested desktop (the nested Hyprland didn't start)")
        PV.render_one = fail
        r = PV.render(["wick", "mire", "tidewell"], force=True)
        self.assertEqual(tried, ["wick"], "one failure, then the run gives up")
        self.assertIn("GpuLost", r[0]["error"])
        self.assertTrue(all("not tried" in x["held"] for x in r[1:]))
        with open(os.path.join(PV.CACHE, "render.log")) as f:
            self.assertIn("giving up this run after one failure", f.read())

    def test_what_a_gpu_failure_looks_like(self):
        self.assertTrue(PV.gpu_trouble("--- hyprland\n  what():  CBackend::create() failed!\n"))
        self.assertTrue(PV.gpu_trouble("MESA-EGL: warning: egl: failed to create dri2 screen"))
        self.assertTrue(PV.gpu_trouble("kwin_core: eglInitialize failed: EGL_NOT_INITIALIZED"))
        self.assertFalse(PV.gpu_trouble("--- hyprland\nConfig error in file binds.lua line 3"))



class NestedSizeTest(unittest.TestCase):
    """The nested desktop's picture is the size asked for (2026-10-17: kwin 6.8 shrank the
    nested Hyprland to 1280x720, and every preview showed the desktop's top-left corner).
    The whole pipeline at real sizes is tests/e2e_previews_nested.py (kwin, Hyprland, a GPU)."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.saved = PV.DESK_W, PV.DESK_H, PV.TERM_W, PV.TERM_H

    def tearDown(self):
        PV.DESK_W, PV.DESK_H, PV.TERM_W, PV.TERM_H = self.saved
        shutil.rmtree(self.tmp, ignore_errors=True)

    def nested(self, monitors=None):
        n = PV.Nested.__new__(PV.Nested)
        n.env, n.captured = {}, None
        n.ctl = lambda *a: json.dumps(monitors or [])
        return n

    def grab_at(self, size):
        """Nested.grab with a stand-in grim that writes a picture of `size`."""
        from PIL import Image
        from unittest import mock
        out = os.path.join(self.tmp, "desktop.png")

        def grim(argv, **k):
            Image.new("RGB", size).save(argv[-1])
            return subprocess.CompletedProcess(argv, 0, "", "")
        n = self.nested()
        with mock.patch.object(PV.subprocess, "run", grim):
            return n, n.grab(out), out

    @unittest.skipUnless(HAVE_PIL, "needs python-pillow")
    def test_a_picture_of_the_size_asked_for_is_kept(self):
        for w, h in ((1920, 1080), (2560, 1440)):
            PV.set_size(w, h)
            n, got, out = self.grab_at((w, h))
            self.assertEqual(got, out)
            self.assertEqual(n.captured, [w, h])

    @unittest.skipUnless(HAVE_PIL, "needs python-pillow")
    def test_a_picture_of_another_size_is_refused(self):
        PV.set_size(1920, 1080)
        with self.assertRaises(PV.WrongSize) as e:
            self.grab_at((1280, 720))
        self.assertIn("1280x720, not 1920x1080", str(e.exception))
        self.assertFalse(os.path.exists(os.path.join(self.tmp, "desktop.png")), "nothing left to cache")

    def test_the_output_size_is_hyprlands(self):
        n = self.nested([{"name": "WAYLAND-1", "width": 1280, "height": 720}])
        self.assertEqual(n.output_size(), (1280, 720))
        self.assertIsNone(self.nested([]).output_size())

    def test_kwin_keeps_the_nested_desktop_full_screen(self):
        import configparser
        c = configparser.ConfigParser()
        c.optionxform = str
        c.read_string(PV.KWIN_RULES)
        self.assertEqual(c["General"]["count"], "1")
        rule = c[c["General"]["rules"]]
        self.assertEqual(rule["wmclass"], "aquamarine")          # Hyprland's Wayland backend
        self.assertEqual(rule["wmclassmatch"], "1")               # exactly
        self.assertEqual((rule["fullscreen"], rule["fullscreenrule"]), ("true", "2"))   # forced


if __name__ == "__main__":
    unittest.main()
