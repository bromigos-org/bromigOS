"""Panels never cut off their content, and the ones that fit their content say how tall it is
(docs/widgets.md, "Fitting to content").

Every built-in and plugin panel is drawn with a big fixture (LAB: six nodes, 36 services in
five groups and three storage pools; ALERTS: 20 alerts; CI: 20 repositories; every other
list grown to 20) at each size class's smallest and start sizes, in a process of its own
(fitcheck.py: demo readings never reach another test): nothing is drawn past the panel's
edges and no row is cut in half.
"""
import json
import os
import subprocess
import sys
import textwrap
import unittest

import plugintest  # noqa: F401  (a throwaway config home, the import path)

HERE = os.path.dirname(os.path.abspath(__file__))
WIDGETS = os.path.dirname(HERE)
REPO = os.path.dirname(WIDGETS)


def run(code_or_args, script=False):
    """fitcheck.py (args) or a snippet run beside it, in its own process; its JSON."""
    argv = [sys.executable, "-c", code_or_args] if script else [sys.executable, os.path.join(HERE, "fitcheck.py"),
                                                                 *code_or_args]
    env = dict(os.environ, BROMIGOS_HOMELAB=os.path.join(REPO, "homelab"))
    for k in ("WAYLAND_DISPLAY", "DISPLAY", "HYPRLAND_INSTANCE_SIGNATURE"):
        env.pop(k, None)
    r = subprocess.run(argv, cwd=HERE, env=env, capture_output=True, text=True, timeout=600)
    if r.returncode:
        raise AssertionError(r.stderr[-3000:])
    return json.loads(r.stdout.strip().splitlines()[-1])


class NeverCutOff(unittest.TestCase):
    def test_every_panel_with_a_big_fixture(self):
        got = run([])
        for name in ("system", "network", "storage", "shortcuts", "workbench", "weather", "connections", "lab",
                     "alerts", "ci", "labjobs", "games", "vector", "media", "github", "gitlab", "calendars"):
            self.assertIn(name, got)
        bad = [f"{n} {r['class']} {r['size'][0]}x{r['size'][1]}: {p}" for n, rows in got.items() for r in rows
               for p in r["problems"]]
        self.assertEqual(bad, [], "\n".join(bad))

    def test_the_check_sees_a_panel_that_runs_off_its_edge(self):
        got = run(textwrap.dedent('''
            import json, fitcheck as F, panels as P, draw as D
            class Spill(P.Panel):
                def draw(self, cr, w, h):
                    top = D.frame(cr, w, h, "SPILL")
                    for i in range(40):
                        D.text(cr, 16, top + i * 20, f"row {i}", 11)
            class Clipped(P.Panel):
                def draw(self, cr, w, h):
                    top = D.frame(cr, w, h, "CLIPPED")
                    cr.save(); cr.rectangle(0, top, w, 100); cr.clip()
                    for i in range(10):
                        D.text(cr, 16, top + i * 15, f"row {i}", 11)
                    cr.restore()
            print(json.dumps({"spill": F.problems(Spill(), 300, 200), "clipped": F.problems(Clipped(), 300, 300)}))
        '''), script=True)
        self.assertTrue(any("past the panel's edge" in p for p in got["spill"]), got)
        self.assertTrue(any("cut by a clip" in p for p in got["clipped"]), got)


class NaturalHeight(unittest.TestCase):
    def test_lab_is_as_tall_as_its_lab_and_folds_when_it_isnt(self):
        got = run(textwrap.dedent('''
            import json, fitcheck as F, panels as P
            lab = F.panels(["lab"])["lab"]
            nat = lab.natural_height(470, "standard")
            out = {"natural": nat, "fit": P.fit_height(lab, 470, "standard"), "naturals": P.naturals(lab)}
            for h in (nat, 640, 600):
                F.problems(lab, 470, h)
                out[str(h)] = lab.folded
            names = []
            import draw as D, cairo
            with D.record() as m:
                lab.render(cairo.Context(cairo.ImageSurface(cairo.FORMAT_ARGB32, 470, 640)), 470, 640)
            out["texts"] = [x["what"] for x in m if isinstance(x["what"], str)]
            out["tips"] = [r[4] for r in lab.regions]
            print(json.dumps(out))
        '''), script=True)
        nat = got["natural"]
        self.assertTrue(700 <= nat <= 1200, nat)                 # six nodes, 36 services: taller than 640
        self.assertEqual(got["fit"], nat)
        self.assertEqual(got["naturals"]["standard"], nat)
        self.assertEqual(got[str(nat)], {})                      # at its natural height: everything in full
        self.assertEqual(got["640"], {"services": "fold"})       # shorter: SERVICES folds first
        texts = got["texts"]
        self.assertIn("34/36 UP", texts)                          # the summary, and only the two that aren't up
        self.assertIn("PAPERLESS", texts)
        self.assertIn("SONAR", texts)
        self.assertNotIn("GRAFANA", texts)
        for n in ("CONTROLLER-1", "GPU-WORKER-1", "STORAGE-NODE", "EDGE-GATEWAY", "COMPUTE-WEST", "COMPUTE-EAST"):
            self.assertIn(n, texts)                               # whole names, never "CONTR…"
        self.assertTrue(any(t.startswith("Node gpu-worker-1: CPU") for t in got["tips"]))

    def test_alerts_frame_follows_its_rows(self):
        got = run(textwrap.dedent('''
            import json, fitcheck as F, panels as P
            F.grow_demo = lambda m: None                           # its five demo alerts
            a = F.panels(["alerts"])["alerts"]
            five = P.fit_height(a, 460, "standard")
            a.res = dict(a.res, items=a.res["items"][:4])
            four = P.fit_height(a, 460, "standard")
            a.res = dict(a.res, items=a.res["items"] * 6)
            many = P.fit_height(a, 460, "standard")
            print(json.dumps({"five": five, "four": four, "many": many, "regions": len(a.regions)}))
        '''), script=True)
        self.assertLess(got["four"], 220)                         # four rows: no mostly empty 300 px box
        self.assertLess(got["four"], got["five"])
        self.assertEqual(got["many"], 420)                        # more than fits: the class's tallest
        self.assertEqual(got["regions"], 0)                       # measuring leaves its hover regions alone

    def test_a_panel_without_a_preference_keeps_its_start(self):
        import panels as P

        class Chart(P.Panel):
            sizes = {"standard": ((300, 150), (600, 400), (400, 220))}

            def draw(self, cr, w, h):
                pass
        self.assertIsNone(Chart().natural_height(400))
        self.assertEqual(P.fit_height(Chart(), 400, "standard"), 220)
        self.assertEqual(P.naturals(Chart()), {})


if __name__ == "__main__":
    unittest.main()
