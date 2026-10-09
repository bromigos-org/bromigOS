"""The Settings app's page registry and the bar's idle module, without a display:
pages are discovered from folders (a broken one skipped, a later one replacing an earlier
one by id), every packaged page imports, and the bar reads `bromigos idle status --json`
(a stub `bromigos` on PATH answers).

    python -m unittest discover -s desktop/tests
"""
import json
import os
import subprocess
import sys
import tempfile
import textwrap
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
DESKTOP = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(DESKTOP, "settings"))

try:                       # the window's toolkit: the registry's pages import it (not in a package builder)
    import gi  # noqa: F401
    gi.require_version("Gtk", "4.0")
    gi.require_version("Adw", "1")
    from gi.repository import Adw, Gtk  # noqa: F401
    HAVE_GTK = True
except (ImportError, ValueError):
    HAVE_GTK = False
if HAVE_GTK:
    from bromigos_settings import registry  # noqa: E402


def page_file(d, name, body):
    with open(os.path.join(d, name), "w") as f:
        f.write(textwrap.dedent(body))


@unittest.skipUnless(HAVE_GTK, "GTK 4 and libadwaita's Python bindings aren't installed")
class RegistryTest(unittest.TestCase):
    def test_packaged_pages_load_in_order(self):
        pages, problems = registry.discover([os.path.join(DESKTOP, "settings", "pages")])
        self.assertEqual(problems, [])
        ids = [p.id for p in pages]
        for pid in ("sound", "idle", "theme", "shortcuts", "accessibility", "targets", "updates", "lab"):
            self.assertIn(pid, ids)
        self.assertTrue(all(p.title and p.summary and callable(p.build) for p in pages))
        # pages sit in the sidebar's groups, in the groups' order
        order = [g for g, _, _ in registry.GROUPS]
        self.assertEqual([p.group_id for p in pages], sorted((p.group_id for p in pages), key=order.index))
        self.assertEqual(next(p for p in pages if p.id == "theme").group_id, "desktop")   # no group named: the default
        self.assertEqual(next(p for p in pages if p.id == "lab").group_id, "lab")

    def test_every_page_declares_its_settings_once(self):
        pages, _ = registry.discover([os.path.join(DESKTOP, "settings", "pages")])
        for p in pages:
            keys = [e.key for e in p.entries]
            self.assertEqual(len(keys), len(set(keys)), p.id)
            for e in p.entries:
                self.assertTrue(e.title and isinstance(e.keywords, list), (p.id, e.key))

    def test_sections_join_their_page_or_make_one(self):
        with tempfile.TemporaryDirectory() as a:
            page_file(a, "host.py", """
                from bromigos_settings import Page
                PAGE = Page(id="host", title="Host", group="system", build=lambda ctx: None)
            """)
            page_file(a, "extra.py", """
                from bromigos_settings import Entry, Section
                SECTIONS = [Section(page="host", id="more", title="More", build=lambda ctx, page: None,
                                    entries=[Entry("knob", "A knob", ["dial"])]),
                            Section(page="lab-models", id="planner", title="Lab models", page_title="Lab models",
                                    build=lambda ctx, page: None)]
            """)
            pages, problems = registry.discover([a])
            self.assertEqual(problems, [])
            host = next(p for p in pages if p.id == "host")
            self.assertEqual([s.id for s in host.sections], ["more"])
            orphan = next(p for p in pages if p.id == "lab-models")
            self.assertEqual(orphan.group_id, "lab")
            self.assertEqual([s.id for s in orphan.sections], ["planner"])

    def test_plugins_add_replace_and_fail_alone(self):
        with tempfile.TemporaryDirectory() as a, tempfile.TemporaryDirectory() as b:
            page_file(a, "sound.py", """
                from bromigos_settings import Page
                PAGE = Page(id="sound", title="Sound", order=35, build=lambda ctx: None)
            """)
            page_file(a, "two.py", """
                from bromigos_settings import Page
                PAGES = [Page(id="x", title="X", order=1, build=print), Page(id="y", title="Y", build=print)]
            """)
            page_file(b, "sound.py", """
                from bromigos_settings import Page
                PAGE = Page(id="sound", title="My sound", order=35, build=lambda ctx: None)
            """)
            page_file(b, "broken.py", "raise RuntimeError('nope')\n")
            page_file(b, "empty.py", "X = 1\n")
            page_file(b, "_private.py", "raise RuntimeError('never read')\n")
            pages, problems = registry.discover([a, b])
            self.assertEqual([p.id for p in pages], ["x", "sound", "y"])
            self.assertEqual(next(p for p in pages if p.id == "sound").title, "My sound")
            self.assertEqual(sorted(os.path.basename(f) for f, _ in problems), ["broken.py", "empty.py"])
            self.assertEqual(next(p for p in pages if p.id == "sound").group_id, "desktop")   # unknown: Desktop
            self.assertIn("nope", dict((os.path.basename(f), m) for f, m in problems)["broken.py"])

    def test_dirs_include_the_users_plugin_folder(self):
        env = {"XDG_CONFIG_HOME": "/c", "XDG_DATA_HOME": "/d", "BROMIGOS_SETTINGS_PAGES": "/t1:/t2"}
        old = {k: os.environ.get(k) for k in env}
        os.environ.update(env)
        try:
            d = registry.page_dirs()
        finally:
            for k, v in old.items():
                os.environ.pop(k, None) if v is None else os.environ.__setitem__(k, v)
        self.assertEqual(d[1:], ["/t1", "/t2", "/d/bromigos/ext/active/settings", "/c/bromigos/plugins/settings"])

    def test_list_needs_no_display(self):
        env = {k: v for k, v in os.environ.items() if k not in ("WAYLAND_DISPLAY", "DISPLAY")}
        env["XDG_CONFIG_HOME"] = tempfile.mkdtemp()
        out = subprocess.run([sys.executable, os.path.join(DESKTOP, "settings", "bromigos-settings"), "--list", "--json"],
                             capture_output=True, text=True, env=env, timeout=60)
        self.assertEqual(out.returncode, 0, out.stderr)
        doc = json.loads(out.stdout)
        self.assertEqual(doc["pages"][0]["group"], "system")
        self.assertTrue(all("entries" in p and "group" in p for p in doc["pages"]))

    def test_search_needs_no_display(self):
        env = {k: v for k, v in os.environ.items() if k not in ("WAYLAND_DISPLAY", "DISPLAY")}
        env["XDG_CONFIG_HOME"] = tempfile.mkdtemp()
        out = subprocess.run([sys.executable, os.path.join(DESKTOP, "settings", "bromigos-settings"), "--search",
                              "microphone", "--json"], capture_output=True, text=True, env=env, timeout=60)
        self.assertEqual(out.returncode, 0, out.stderr)
        doc = json.loads(out.stdout)
        self.assertEqual((doc["results"][0]["page"], doc["results"][0]["key"]), ("sound", "input"))


STATUS = {
    "schema": 1, "summary": "Screensaver at 8 min, then nothing locks; the displays stay on; never suspends.",
    "preset": "screensaver-only", "screensaver_only": True, "policy": {},
    "stay_awake": {"on": False}, "hypridle": {"running": True, "pids": [1]}, "inhibitors": [], "warnings": [],
}


class BarTest(unittest.TestCase):
    def bar(self, doc):
        with tempfile.TemporaryDirectory() as d:
            stub = os.path.join(d, "bromigos")
            with open(stub, "w") as f:
                f.write("#!/bin/sh\ncat <<'EOF'\n" + json.dumps(doc) + "\nEOF\n")
            os.chmod(stub, 0o755)
            env = dict(os.environ, PATH=d + ":/usr/bin")
            out = subprocess.run([sys.executable, os.path.join(DESKTOP, "waybar", "scripts", "idle.py")],
                                 capture_output=True, text=True, env=env, timeout=20)
            return json.loads(out.stdout)

    def test_screensaver_only_shows_the_eye(self):
        b = self.bar(STATUS)
        self.assertEqual(b["text"], "NO LOCK")
        self.assertEqual(b["class"], ["saver"])
        self.assertIn("nothing locks", b["tooltip"])
        self.assertIn("right-click: Settings", b["tooltip"])

    def test_stay_awake_shows_the_cup_and_time_left(self):
        doc = dict(STATUS, stay_awake={"on": True, "remaining_s": 3000, "until": 2000000000})
        b = self.bar(doc)
        self.assertEqual(b["text"], "AWAKE 50m")
        self.assertEqual(b["class"], ["awake"])
        b = self.bar(dict(STATUS, stay_awake={"on": True, "remaining_s": None}))
        self.assertEqual(b["text"], "AWAKE")
        self.assertIn("until you stop it", b["tooltip"])

    def test_the_usual_policy_is_a_dim_eye_and_a_stopped_daemon_says_so(self):
        doc = dict(STATUS, preset="default", screensaver_only=False, hypridle={"running": False, "pids": []})
        b = self.bar(doc)
        self.assertEqual(b["text"], " ")
        self.assertEqual(b["class"], ["normal", "stopped"])
        self.assertIn("hypridle isn't running", b["tooltip"])


class VectorSwitchBarTest(unittest.TestCase):
    """The bar's VECTOR emergency switch reads the switch's markers itself (a throwaway HOME
    and runtime folder; a stand-in bromigos-holo on PATH says VECTOR is installed)."""

    def bar(self, setup=None, installed=True):
        with tempfile.TemporaryDirectory() as d:
            home, run, path = os.path.join(d, "home"), os.path.join(d, "run"), os.path.join(d, "bin")
            for x in (home, run, path):
                os.makedirs(x)
            if installed:
                stub = os.path.join(path, "bromigos-holo")
                with open(stub, "w") as f:
                    f.write("#!/bin/sh\nexit 0\n")
                os.chmod(stub, 0o755)
            if setup:
                setup(home, run)
            env = dict(os.environ, HOME=home, XDG_RUNTIME_DIR=run, PATH=path + ":/usr/bin")
            out = subprocess.run([sys.executable, os.path.join(DESKTOP, "waybar", "scripts", "vector-switch.py")],
                                 capture_output=True, text=True, env=env, timeout=20)
            return json.loads(out.stdout)

    @staticmethod
    def mark(where, by=None):
        def setup(home, run):
            p = {"state": os.path.join(home, ".local/state/bromigos/vector-switch/off"),
                 "run": os.path.join(run, "bromigos-vector-switch/off"),
                 "old": os.path.join(home, ".local/state/bromigos/vector-shell-off")}[where]
            os.makedirs(os.path.dirname(p), exist_ok=True)
            with open(p, "w") as f:
                f.write(json.dumps({"by": by}) if by else "")
        return setup

    def test_on_is_a_quiet_power_mark_with_a_hint(self):
        b = self.bar()
        self.assertEqual(b["class"], ["on"])
        self.assertNotIn("OFF", b["text"])
        self.assertIn("click: switch VECTOR off now", b["tooltip"])
        self.assertIn("SUPER+CTRL+ESCAPE", b["tooltip"])

    def test_any_marker_reads_vector_off_in_red(self):
        for where in ("state", "run", "old"):
            b = self.bar(self.mark(where))
            self.assertEqual(b["class"], ["off"], where)
            self.assertIn("VECTOR OFF", b["text"], where)
            self.assertIn("asks YES first", b["tooltip"], where)

    def test_it_says_who_switched_him_off(self):
        b = self.bar(self.mark("run", "the operator (key)"))
        self.assertIn("switched off by the operator (key)", b["tooltip"])

    def test_a_swapped_folder_reads_off(self):
        def swap(home, run):
            os.makedirs(os.path.join(home, ".local/state/bromigos"))
            os.symlink(run, os.path.join(home, ".local/state/bromigos/vector-switch"))
        self.assertEqual(self.bar(swap)["class"], ["off"])

    @unittest.skipIf(os.path.exists("/usr/lib/bromigos/vector/bin/bromigos-holo"), "VECTOR is installed here")
    def test_hidden_without_vector(self):
        self.assertEqual(self.bar(installed=False)["text"], "")


if __name__ == "__main__":
    unittest.main()


@unittest.skipUnless(HAVE_GTK, "GTK 4 and libadwaita's Python bindings aren't installed")
class ThemePageTest(unittest.TestCase):
    """Settings › Theme says what moves in a world and what drives it, from its world.toml."""

    def page(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location("theme_page", os.path.join(DESKTOP, "settings", "pages",
                                                                                "theme.py"))
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod

    def test_a_worlds_moving_parts_and_their_drivers(self):
        mod = self.page()
        repo = os.path.dirname(DESKTOP)
        moves = dict(mod.world_moves(os.path.join(repo, "themes", "mire", "live", "world.toml")))
        self.assertIn("this machine's CPU load", moves["Rain"])
        self.assertIn("network traffic", moves["Fireflies"])
        self.assertTrue(any("keeper" in v for v in moves.values()))
        self.assertTrue(any("coding agent" in v for v in moves.values()))
        self.assertTrue(all(isinstance(k, str) and k and v for k, v in moves.items()))
        tide = dict(mod.world_moves(os.path.join(repo, "themes", "tidewell", "live", "world.toml")))
        self.assertTrue(tide)
        self.assertEqual(mod.world_moves("/nonexistent/world.toml"), [])
