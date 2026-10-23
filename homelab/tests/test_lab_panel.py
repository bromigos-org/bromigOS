"""The LAB panel's storage rows (widgets/_lab.py): the object store's NAS share is the one the
snapshot binds its claims to, named as the lab names it, never a name in the code.

    PYTHONPATH=lib python -m unittest discover -s tests

The panel's drawing modules (draw, sources, panels: cairo and GTK) are stand-ins that
record the text drawn and the hover hints, so no display or cairo is needed.
"""
import importlib.util
import os
import sys
import types
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
HOMELAB = os.path.dirname(HERE)


class Recorder(types.ModuleType):
    """draw: label() records its text; every other primitive draws nothing."""

    def __init__(self):
        super().__init__("draw")
        self.texts = []

    def label(self, cr, x, y, text, *a, **k):
        self.texts.append(text)

    def level(self, *a, **k):
        return "phosphor"

    def __getattr__(self, name):
        return lambda *a, **k: None


def load_lab():
    D = Recorder()
    S = types.ModuleType("sources")
    S.human = lambda v, digits=1: f"{v / 1e9:.{digits}f} GB"
    P = types.ModuleType("panels")
    P.Panel = object
    P.copy_text = P.open_url = lambda *a: None
    saved = {m: sys.modules.get(m) for m in ("draw", "sources", "panels")}
    sys.modules.update(draw=D, sources=S, panels=P)
    try:
        path = os.path.join(HOMELAB, "widgets", "_lab.py")
        spec = importlib.util.spec_from_file_location("lab_panel_under_test", path)
        lab = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(lab)
    finally:
        for m, v in saved.items():
            if v is None:
                sys.modules.pop(m, None)
            else:
                sys.modules[m] = v
    return lab, D


class FakePanel:
    def __init__(self):
        self.hints = []

    def region(self, x, y, w, h, hint, act=None):
        self.hints.append(hint)

    def _svc_url(self, d, sid):
        return "https://example.invalid/"


def snapshot(shares):
    return {"services": {"rustfs": {"status": "up"}},
            "nas": {"pool": {"used": 2e12, "total": 8e12, "raidMembers": 4, "health": "healthy"}, "disks": [],
                    "shares": shares}}


class StorageRowsTest(unittest.TestCase):
    def setUp(self):
        self.lab, self.D = load_lab()
        FakePanel._nas_row = self.lab.LabPanel._nas_row      # the NAS pool's row, drawn as the panel draws it

    def draw(self, shares):
        self.D.texts.clear()
        p = FakePanel()
        self.lab.LabPanel._pools(p, None, snapshot(shares), 0, 600, 0)
        return [t for t in self.D.texts if " on " in t], p.hints

    def test_the_share_is_the_one_holding_the_object_stores_claims(self):
        shares = [{"name": "apps", "usage": 5e9, "volumes": [{"claim": "media/library"}]},
                  {"name": "objects", "usage": 120e9, "quota": -1,
                   "volumes": [{"claim": "rustfs/rustfs-data"}, {"claim": "rustfs/rustfs-logs"}]}]
        rows, hints = self.draw(shares)
        self.assertEqual(rows, ["120.0 GB on the NAS share objects"])
        self.assertTrue(any("used on the NAS share objects (no quota)" in h for h in hints), hints)

    def test_a_quota_is_the_shares_own(self):
        rows, hints = self.draw([{"name": "objects", "usage": 1e9, "quota": 500e9,
                                  "volumes": [{"claim": "rustfs/data"}]}])
        self.assertTrue(any("(quota 500.0 GB)" in h for h in hints), hints)

    def test_a_share_without_a_name_reads_the_nas(self):
        rows, hints = self.draw([{"usage": 3e9, "volumes": [{"claim": "rustfs/data"}]}])
        self.assertEqual(rows, ["3.0 GB on the NAS"])
        self.assertTrue(any("used on the NAS (no quota)" in h for h in hints), hints)

    def test_no_row_when_no_share_holds_the_object_store(self):
        # a share named like an object store, but nothing of rustfs's is bound on it
        rows, _ = self.draw([{"name": "rustfs", "usage": 9e9, "volumes": [{"claim": "media/library"}]}])
        self.assertEqual(rows, [])
        self.assertEqual(self.draw([])[0], [])
        self.assertIsNone(self.lab.store_share({}))


class NoCairo:
    """A cairo context that draws nothing."""

    def __getattr__(self, name):
        return lambda *a, **k: None


class EmptyReadingsTest(unittest.TestCase):
    """The lab can send a reading as null (a node or the cluster between scrapes): the panel draws
    0% instead of failing on it, five failures in a minute switching the whole panel off."""

    def setUp(self):
        self.lab, self.D = load_lab()

    def test_pct(self):
        self.assertEqual(self.lab._pct(None), 0.0)
        self.assertEqual(self.lab._pct("n/a"), 0.0)
        self.assertEqual(self.lab._pct(42.4), 42.4)

    def test_node_map_header_with_null_cluster_cpu(self):
        snap = {"cluster": {"cpuNow": None}, "nodes": []}
        panel = types.SimpleNamespace(pulse_at=0.0, _node_grid=lambda cr, nodes, w: (3, 120),
                                      _node_chips=lambda cr, nodes, x0, x1, y, draw: y)
        for mode in ("full", "fold"):
            self.D.texts.clear()
            self.lab.LabPanel._nodes(panel, NoCairo(), snap, 0, 440, 0, mode=mode)
            self.assertIn("CLUSTER CPU 0%", self.D.texts)

    def test_node_hint_with_null_readings(self):
        src = open(os.path.join(HOMELAB, "widgets", "_lab.py")).read()
        # every percentage the panel formats goes through _pct, so a null never reaches a format spec
        import re
        self.assertEqual(re.findall(r"\.get\('(?:cpuPct|memPct|cpuNow)', 0\):", src), [])

if __name__ == "__main__":
    unittest.main()
