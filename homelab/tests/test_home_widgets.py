"""The homelab's widgets (widgets/*_panels.py): LAB JOBS, SOLAR, GAME SERVERS and ALERTS.

Their data (the queue split, progress, the GPU it waits for; several gateways added up,
the day's samples on disk; servers ordered and counted; alerts sorted by state and
severity), when each offers itself to the gallery, their size classes (none overlap), and,
where cairo is installed, every size class drawn with a hint on every part and an empty
state that says how to set the source up.

    PYTHONPATH=lib python -m unittest discover -s tests

Without cairo and PyGObject (the package's check() has neither), the drawing modules are
stand-ins and the drawing tests are skipped.
"""
import importlib.util
import os
import sys
import tempfile
import time
import types
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
HOMELAB = os.path.dirname(HERE)
WIDGETS = os.path.join(os.path.dirname(HOMELAB), "widgets")
FILES = {"labjobs": "labjobs_panels.py", "solar": "solar_panels.py", "games": "games_panels.py",
         "alerts": "alerts_panels.py"}


def _real():
    """True when the real drawing modules load (cairo, PyGObject's Pango)."""
    try:
        import cairo  # noqa: F401
        import gi
        gi.require_version("Pango", "1.0")
        gi.require_version("PangoCairo", "1.0")
        from gi.repository import PangoCairo  # noqa: F401
    except (ImportError, ValueError):
        return False
    return os.path.isdir(WIDGETS)


REAL = _real()


def _stubs():
    """draw, sources, panels and _kit stand-ins: enough to load the files and call their data code."""
    import datetime as dt
    D = types.ModuleType("draw")
    S = types.ModuleType("sources")
    S.human = lambda v, digits=1: f"{v}"
    S.duration = lambda s: f"{int(s)}s"
    P = types.ModuleType("panels")
    P.__file__ = os.path.join(tempfile.mkdtemp(), "panels.py")

    class Panel:
        sizes, default_size, min_size, max_size = {}, "standard", (240, 120), (1600, 1400)

        @classmethod
        def size_classes(cls):
            return [(n, tuple(v[0]), tuple(v[1]), tuple(v[2]) if len(v) > 2 else tuple(v[0]))
                    for n, v in cls.sizes.items()]
    P.Panel = Panel
    P.copy_text = P.open_url = lambda *a: None
    K = types.ModuleType("_kit")
    K.KitPanel = Panel
    K.STATE = tempfile.mkdtemp()
    K.demo = lambda: False

    def iso_time(s):
        if s in (None, ""):
            return None
        if isinstance(s, (int, float)):
            return float(s)
        return dt.datetime.fromisoformat(str(s).replace("Z", "+00:00")).timestamp()
    K.iso_time = iso_time
    K.ago = lambda t: "?"
    return {"draw": D, "sources": S, "panels": P, "_kit": K}


def load(name):
    path = os.path.join(HOMELAB, "widgets", FILES[name])
    mod_name = f"home_widget_{name}_under_test"
    if REAL:
        for p in (WIDGETS, os.path.join(WIDGETS, "plugins"), os.path.join(WIDGETS, "tests")):
            if p not in sys.path:
                sys.path.insert(0, p)
        spec = importlib.util.spec_from_file_location(mod_name, path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod
    saved = {m: sys.modules.get(m) for m in ("draw", "sources", "panels", "_kit")}
    sys.modules.update(_stubs())
    try:
        spec = importlib.util.spec_from_file_location(mod_name, path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
    finally:
        for m, v in saved.items():
            if v is None:
                sys.modules.pop(m, None)
            else:
                sys.modules[m] = v
    return mod


L, SOLAR, GAMES, ALERTS = (load(n) for n in ("labjobs", "solar", "games", "alerts"))
PANELS = {"labjobs": L.LabJobsPanel, "solar": SOLAR.SolarPanel, "games": GAMES.GamesPanel, "alerts": ALERTS.AlertsPanel}
MODS = {"labjobs": L, "solar": SOLAR, "games": GAMES, "alerts": ALERTS}


class Gallery(unittest.TestCase):
    def test_words_and_sizes(self):
        for name, cls in PANELS.items():
            self.assertTrue(cls.description and cls.reads, name)
            self.assertEqual(cls.category, "homelab", name)
            names = [c[0] for c in cls.size_classes()]
            self.assertEqual(names, ["compact", "standard", "wide", "tall", "large"], name)
            self.assertIn(cls.default_size, names, name)

    def test_size_classes_never_overlap(self):
        for name, cls in PANELS.items():
            cs = cls.size_classes()
            for i, (a, alo, ahi, astart) in enumerate(cs):
                self.assertTrue(alo[0] <= astart[0] <= ahi[0] and alo[1] <= astart[1] <= ahi[1], f"{name} {a} start")
                for b, blo, bhi, _ in cs[i + 1:]:
                    both = alo[0] <= bhi[0] and blo[0] <= ahi[0] and alo[1] <= bhi[1] and blo[1] <= ahi[1]
                    self.assertFalse(both, f"{name}: {a} and {b} overlap")

    def test_offered_only_with_a_source(self):
        fake = types.SimpleNamespace(configured=lambda: False, available=lambda cap: False)
        with mock.patch.dict(sys.modules, {"bromigos_homelab": fake}), \
                mock.patch.dict(os.environ, {"BROMIGOS_WIDGETS_DEMO_LAB": ""}):
            for name, mod in MODS.items():
                self.assertEqual(mod.names(), {}, name)
                ok, why = PANELS[name].available()
                self.assertFalse(ok, name)
                self.assertTrue(why, name)
        on = types.SimpleNamespace(configured=lambda: True, available=lambda cap: True)
        with mock.patch.dict(sys.modules, {"bromigos_homelab": on}):
            for name, mod in MODS.items():
                self.assertEqual(list(mod.names()), [name])
                self.assertEqual(PANELS[name].available(), (True, ""))
        with mock.patch.dict(sys.modules, {"bromigos_homelab": fake}), \
                mock.patch.dict(os.environ, {"BROMIGOS_WIDGETS_DEMO_LAB": "1"}):
            self.assertEqual(list(L.names()), ["labjobs"])           # pictures of the made-up lab

    def test_each_gates_on_its_own_capability(self):
        asked = []
        fake = types.SimpleNamespace(configured=lambda: asked.append("configured") or False,
                                     available=lambda cap: asked.append(cap) or False)
        with mock.patch.dict(sys.modules, {"bromigos_homelab": fake}), \
                mock.patch.dict(os.environ, {"BROMIGOS_WIDGETS_DEMO_LAB": ""}):
            for mod in MODS.values():
                mod.names()
        self.assertEqual(asked, ["configured", "energy", "games", "alerts"])


class LabJobs(unittest.TestCase):
    def test_split_orders_running_then_waiting_then_queued(self):
        now = 10_000.0
        jobs = [{"id": "q", "state": "queued", "created": 1}, {"id": "r", "state": "running", "created": 5},
                {"id": "w", "state": "waiting", "created": 2}, {"id": "old", "state": "succeeded", "finished": 10},
                {"id": "new", "state": "failed", "finished": now - 60}, {"id": "mid", "state": "succeeded",
                                                                         "finished": now - 3600}]
        active, recent = L.split(jobs, now=now, recent_h=24 * 365)
        self.assertEqual([j["id"] for j in active], ["r", "w", "q"])
        self.assertEqual([j["id"] for j in recent], ["new", "mid", "old"])
        _, recent = L.split(jobs, now=now, recent_h=2)
        self.assertEqual([j["id"] for j in recent], ["new", "mid"])

    def test_progress_only_for_running_jobs_that_report_it(self):
        self.assertEqual(L.progress({"state": "running", "progress": 0.62}), 0.62)
        self.assertIsNone(L.progress({"state": "running", "progress": 0.0}))
        self.assertEqual(L.progress({"state": "running", "progress": 0.0, "progress_text": "loading"}), 0.0)
        self.assertIsNone(L.progress({"state": "waiting", "progress": 0.5}))

    def test_gpu_of_the_service(self):
        g = L.gpu_of({"gpu": {"source": "media", "free": 1024, "total": 4096}})
        self.assertEqual((g["used"], g["free"], g["source"]), (3072, 1024, "media"))
        self.assertIsNone(L.gpu_of({}))

    def test_reads_the_queue_files(self):
        state = tempfile.mkdtemp()
        sys.path.insert(0, os.path.join(HOMELAB, "lib"))
        from bromigos_homelab import jobqueue  # noqa: F401
        os.makedirs(os.path.join(state, "jobs"))
        with open(os.path.join(state, "jobs", "1009-000001-image-abcd.json"), "w") as f:
            f.write('{"id": "1009-000001-image-abcd", "kind": "image", "state": "queued", "created": 1}')
        with mock.patch.dict(os.environ, {"BROMIGOS_LAB_STATE": state}):
            q = L.read_queue()
        self.assertEqual([x["id"] for x in q["jobs"]], ["1009-000001-image-abcd"])
        self.assertEqual(q["state"], "stopped")


class Solar(unittest.TestCase):
    def test_power_words(self):
        self.assertEqual(SOLAR.power(4180.4), "4.2 kW")
        self.assertEqual(SOLAR.power(640), "640 W")
        self.assertEqual(SOLAR.power(None), "--")
        self.assertEqual(SOLAR.energy(23400), "23.4 kWh")

    def test_several_gateways_add_up(self):
        r = SOLAR.combine([{"name": "east", "production_w": 1000.0, "consumption_w": 700.0, "net_w": -300.0,
                            "battery_pct": 80.0},
                           {"name": "west", "production_w": 500.0, "consumption_w": None, "net_w": None,
                            "battery_pct": 60.0}])
        self.assertEqual((r["production_w"], r["consumption_w"], r["net_w"], r["battery_pct"]), (1500.0, 700.0, -300.0,
                                                                                               70.0))
        self.assertIsNone(SOLAR.combine([]))

    def test_self_powered(self):
        self.assertEqual(SOLAR.self_powered({"production_w": 500, "consumption_w": 1000}), 0.5)
        self.assertEqual(SOLAR.self_powered({"production_w": 3000, "consumption_w": 1000}), 1.0)
        self.assertIsNone(SOLAR.self_powered({"production_w": 3000, "consumption_w": None}))

    def test_the_days_samples_on_disk(self):
        d = tempfile.mkdtemp()
        now = time.time()
        path = os.path.join(d, "solar-today.json")
        old = os.path.join(d, "solar-2000-01-01.json")
        with open(old, "w") as f:
            f.write("[]")
        SOLAR.record({"production_w": 100.0, "consumption_w": 50.0}, now=now - 30, path=path)
        pts = SOLAR.record({"production_w": 200.0, "consumption_w": None}, now=now, path=path)
        self.assertEqual([p[1] for p in pts], [100.0, 200.0])
        self.assertEqual(SOLAR.load_day(path), pts)
        self.assertFalse(os.path.exists(old))                    # a week is kept
        self.assertEqual(SOLAR.load_day(os.path.join(d, "missing.json")), [])


class Games(unittest.TestCase):
    ITEMS = [{"name": "b", "status": "stopped"}, {"name": "a", "status": "running", "players": 1, "players_max": 10},
             {"name": "c", "status": "running", "players": 4, "players_max": 20}, {"name": "d", "status": "pending"}]

    def test_order_and_totals(self):
        self.assertEqual([g["name"] for g in GAMES.order(self.ITEMS)], ["c", "a", "d", "b"])
        self.assertEqual(GAMES.totals(self.ITEMS), {"servers": 4, "up": 2, "players": 5, "slots": 30})


class Alerts(unittest.TestCase):
    ITEMS = [{"name": "info-old", "severity": "info", "state": "firing", "since": "2026-10-01T00:00:00Z"},
             {"name": "pending-crit", "severity": "critical", "state": "pending", "since": "2026-10-09T00:00:00Z"},
             {"name": "warn", "severity": "warning", "state": "firing", "since": "2026-10-08T00:00:00Z"},
             {"name": "page", "labels": {"severity": "page"}, "state": "firing", "since": "2026-10-09T00:00:00Z"}]

    def test_firing_first_then_worst(self):
        self.assertEqual([a["name"] for a in ALERTS.sort_alerts(self.ITEMS)], ["page", "warn", "info-old", "pending-crit"])
        c = ALERTS.counts(self.ITEMS)
        self.assertEqual((c["firing"], c["pending"], c["critical"], c["warning"], c["info"]), (3, 1, 1, 1, 1))
        self.assertEqual(ALERTS.worst(self.ITEMS), "critical")
        self.assertIsNone(ALERTS.worst([self.ITEMS[1]]))

    def test_labels_shown_first_the_useful_ones(self):
        bits = ALERTS.label_bits({"labels": {"alertname": "x", "severity": "warning", "zone": "a", "namespace": "media",
                                             "pod": "p-1"}})
        self.assertEqual(bits, ["namespace=media", "pod=p-1", "zone=a"])


@unittest.skipUnless(REAL, "needs cairo and PyGObject (the desktop has them)")
class Drawing(unittest.TestCase):
    def setUp(self):
        import plugintest  # noqa: F401  (a throwaway config home)
        self.PT = plugintest

    def test_every_size_class_with_demo_readings(self):
        with mock.patch.dict(os.environ, {"BROMIGOS_WIDGETS_DEMO": "1"}):
            for name, cls in PANELS.items():
                p = cls({})
                self.PT.every_class(self, p)

    def _bare(self, cls):
        """A panel with no data yet and no poller thread."""
        with mock.patch.object(sys.modules["_kit"].KitPanel, "poller",
                               lambda self, fn, every, idle=None, name="poll", start=True:
                               sys.modules["_kit"].Poller(self, fn, every, idle, name, start=False)):
            return cls({})

    def test_empty_states_say_how_to_set_up(self):
        nothing = {"ok": False, "items": [], "errors": {}, "sources": []}
        for name, cls in (("alerts", ALERTS.AlertsPanel), ("games", GAMES.GamesPanel)):
            p = self._bare(cls)
            p.poll.data = nothing
            tips = " ".join(self.PT.draw(p, 460, 300))
            self.assertIn("homelab.toml", tips, name)
        p = self._bare(SOLAR.SolarPanel)
        p.poll.data = nothing
        self.assertIn("enphase", " ".join(self.PT.draw(p, 460, 280)))

    def test_unreachable_says_why(self):
        p = self._bare(ALERTS.AlertsPanel)
        p.poll.data = {"ok": False, "items": [], "errors": {"metrics": "unreachable: refused"}, "sources": ["metrics"]}
        self.assertIn("refused", " ".join(self.PT.draw(p, 460, 300)))

    def test_all_clear(self):
        p = self._bare(ALERTS.AlertsPanel)
        p.poll.data = {"ok": True, "items": [], "errors": {}, "sources": ["metrics"]}
        self.assertTrue(any("No alert" in t for t in self.PT.draw(p, 460, 300)))

    def test_empty_queue(self):
        p = self._bare(L.LabJobsPanel)
        p.poll.data = {"jobs": [], "service": {}, "state": "stopped"}
        self.assertTrue(any("bromigos lab run" in t for t in self.PT.draw(p, 460, 300)))

    def test_cancel_takes_two_clicks(self):
        with mock.patch.dict(os.environ, {"BROMIGOS_WIDGETS_DEMO": "1"}):
            p = L.LabJobsPanel({})
        ran = []
        with mock.patch.object(sys.modules["_kit"], "spawn", ran.append):
            j = {"id": "1009-x", "state": "queued"}
            p._cancel(j)
            self.assertEqual(ran, [])
            p._cancel(j)
        self.assertEqual(ran, [["bromigos", "lab", "jobs", "cancel", "1009-x"]])


if __name__ == "__main__":
    unittest.main()
