"""`bromigos lab`'s dashboard driven by Textual's pilot on the recorded lab (labfake.py), and a
snapshot of its first screen.

    PYTHONPATH=lib:../lib python -m unittest discover -s tests
    LAB_SNAPSHOT_UPDATE=1 …          rewrite tests/snapshots/lab-tui.svg after a deliberate change
    LAB_SNAPSHOT_PNG=out.png …       also write the first screen as a PNG (rsvg-convert)

Skipped without Textual (python-textual). The snapshot is compared only on the Textual
version it was made with (tests/snapshots/lab-tui.version); other versions draw borders
and spacing a little differently, so they check the content instead.
"""
import asyncio
import os
import re
import shutil
import subprocess
import time
import unittest
from unittest import mock

import labfake

try:
    import textual
    from bromigos_homelab import tui
except ImportError:                                  # no python-textual: the dashboard isn't built
    textual = None

HERE = os.path.dirname(os.path.abspath(__file__))
SNAP = os.path.join(HERE, "snapshots", "lab-tui.svg")
T0 = 1791561600.0                                     # a fixed clock: 2026-10-09 15:00 UTC


class Fixture:
    """The dashboard's data from the recorded lab, read once; jobs from a fixed list."""

    def __init__(self):
        from bromigos_homelab import console, doctor, labmodels
        import socket
        from unittest import mock
        with labfake.Lab(), mock.patch.object(socket, "getaddrinfo", lambda *a, **k: [(2, 1, 6, "", ("192.0.2.1", 0))]), \
                mock.patch.object(doctor, "cert_days", lambda *a, **k: (200, "2027-04-27", True, None)):
            self._status = console.status()
            self._inv = labmodels.inventory()
            self._doctor = doctor.run(only={"argo", "disk", "gpu", "dns", "tls", "sources"})
        self._status["generatedAt"] = int(T0)
        self._status["seconds"] = 1.2
        for c in self._status["cards"]:
            if c["id"] == "jobs":
                c["summary"] = "1 running · 1 queued · service running"
        self._doctor["seconds"] = 2.4
        self.submitted, self.cancelled = [], []
        self._jobs = [
            {"id": "1009-150210-hologr-a1b2", "kind": "hologram", "preset": "hologram", "state": "running",
             "progress": 0.55, "progress_text": "3D", "created": T0 - 90, "prompt": "a brass telescope",
             "outputs": [], "why": ""},
            {"id": "1009-150305-image-c3d4", "kind": "image", "preset": "world-painting", "state": "waiting",
             "created": T0 - 30, "why": "waiting: one heavy job at a time (after 1009-150210-hologr-a1b2)",
             "outputs": []},
            {"id": "1009-144800-voice-e5f6", "kind": "voice", "preset": "voice-line", "state": "succeeded",
             "created": T0 - 800, "outputs": ["/home/u/Pictures/bromigos/lab/voice/1009-144800-voice-e5f6.wav"],
             "why": "", "text": "The relays are lit."},
            {"id": "1009-140000-cutout-0a0b", "kind": "cutout", "preset": None, "state": "failed", "created": T0 - 3600,
             "why": "image.cutout failed: the input isn't an image", "outputs": []}]

    def status(self):
        return self._status

    def inventory(self):
        return self._inv

    def jobs(self):
        return {"jobs": self._jobs, "service": "running"}

    def job_log(self, jid):
        return f"15:02:10 queued by you: hologram\n15:02:11 started (Hologram)\n15:02:40 made concept.png\n" \
            if jid.endswith("a1b2") else ""

    def doctor(self):
        return self._doctor

    def kinds(self):
        from bromigos_homelab import jobs
        return [dict(k.describe(), available=True) for k in jobs.kinds()] + \
            [dict(p.describe(), available=True, preset=True) for p in jobs.presets()]

    def submit(self, kind, preset, prompt, text):
        self.submitted.append((kind, preset, prompt, text))
        return {"id": "1009-150400-new"}

    def cancel(self, jid):
        self.cancelled.append(jid)
        return {"id": jid, "state": "cancelled"}

    def retry(self, jid):
        return {"id": jid + "-r"}

    def now(self):
        return T0


def _norm(svg):
    """Textual's SVG export without what changes run to run (its terminal id hash)."""
    return re.sub(r"terminal-\d+", "terminal", svg)


@unittest.skipIf(textual is None, "python-textual isn't installed")
class DashboardTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._no_color = os.environ.pop("NO_COLOR", None)
        cls._tz = os.environ.get("TZ")
        os.environ["TZ"] = "UTC"                      # the clock on screen, the same everywhere
        time.tzset()
        cls.fx = Fixture()
        # The snapshot must not read the developer's installed desktop palette.
        cls._theme = mock.patch.object(tui, "bromigos_theme", lambda: tui.Theme(
            name="bromigos", primary="#39ff14", secondary="#9cff8a", accent="#3fe0c5", warning="#d4af37",
            error="#ff766f", success="#39ff14", foreground="#c4f5bb", background="#000500",
            surface="#001300", panel="#003b00", dark=True))
        cls._theme.start()

    @classmethod
    def tearDownClass(cls):
        cls._theme.stop()
        if cls._no_color is not None:
            os.environ["NO_COLOR"] = cls._no_color
        if cls._tz is None:
            os.environ.pop("TZ", None)
        else:
            os.environ["TZ"] = cls._tz
        time.tzset()

    def run_app(self, steps):
        app = tui.LabApp(source=self.fx, clock=lambda: T0, interval=3600)

        async def go():
            async with app.run_test(size=(150, 46)) as pilot:
                await pilot.pause(0.3)
                await pilot.wait_for_scheduled_animations()
                await steps(app, pilot)
        asyncio.run(go())
        return app

    def test_status_cards_and_detail(self):
        seen = {}

        async def steps(app, pilot):
            cards = list(app.query(tui.CardButton))
            seen["ids"] = [c.card["id"] for c in cards]
            seen["tooltips"] = [c.tooltip for c in cards]
            seen["top"] = str(app.query_one("#top").render())
            gpu = next(c for c in cards if c.card["id"] == "gpus")
            await pilot.click(f"#card-{gpu.card['id']}")
            await pilot.pause(0.1)
            seen["current"] = app.current
            t = app.query_one("#detail", tui.HintTable)
            seen["rows"] = t.row_count
            seen["hints"] = list(t.hints)
            await pilot.wait_for_scheduled_animations()
            svg = app.export_screenshot()
            seen["svg"] = svg
        self.run_app(steps)
        self.assertIn("gpus", seen["ids"])
        self.assertIn("services", seen["ids"])
        self.assertTrue(all(seen["tooltips"]), "every card has a hover hint")
        self.assertIn("LAB", seen["top"])
        self.assertEqual(seen["current"], "gpus")
        self.assertEqual(seen["rows"], 4)
        self.assertTrue(all(h for h in seen["hints"]), "every row has a hover hint")
        self.assertIn("5090", seen["svg"])
        self._snapshot(seen["svg"])

    def test_tabs_models_jobs_doctor(self):
        seen = {}

        async def steps(app, pilot):
            await pilot.press("2")
            await pilot.pause(0.3)
            seen["models"] = app.query_one("#modeltable").row_count
            seen["gpus"] = app.query_one("#gpus").row_count
            await pilot.press("3")
            await pilot.pause(0.2)
            seen["jobs"] = app.query_one("#jobtable").row_count
            seen["log"] = "\n".join(str(x) for x in app.query_one("#joblog").lines)
            await pilot.press("c")
            await pilot.pause(0.1)
            await pilot.press("4")
            await pilot.pause(0.3)
            seen["findings"] = app.query_one("#findings").row_count
            seen["docsum"] = str(app.query_one("#docsum").render())
        self.run_app(steps)
        self.assertGreater(seen["models"], 1)
        self.assertEqual(seen["gpus"], 4)
        self.assertEqual(seen["jobs"], 4)
        self.assertIn("made concept.png", seen["log"])
        self.assertEqual(self.fx.cancelled, ["1009-150210-hologr-a1b2"])
        self.assertGreater(seen["findings"], 3)
        self.assertIn("to look at", seen["docsum"])

    def test_vim_and_arrow_keys(self):
        """j/k and the arrows move between cards (showing each) and table rows; l/h and
        right/left cross between the STATUS panes; ] [ and L H step through the tabs."""
        seen = {}

        async def steps(app, pilot):
            ids = [c.card["id"] for c in app.query(tui.CardButton)]
            app._focus_main("status")
            await pilot.pause(0.1)
            first = app.current
            await pilot.press("g")
            await pilot.pause(0.1)
            seen["top"] = app.current
            await pilot.press("j")
            await pilot.pause(0.1)
            seen["after_j"] = app.current
            await pilot.press("down")
            await pilot.pause(0.1)
            seen["after_down"] = app.current
            await pilot.press("k")
            await pilot.pause(0.1)
            seen["after_k"] = app.current
            await pilot.press("l")
            await pilot.pause(0.1)
            seen["detail_focused"] = app.query_one("#detail").has_focus
            await pilot.press("h")
            await pilot.pause(0.1)
            seen["card_focused"] = isinstance(app.focused, tui.CardButton)
            seen["ids"], seen["first"] = ids, first
            await pilot.press("]")
            await pilot.pause(0.3)
            seen["tab1"] = app.query_one("#tabs").active
            seen["models_focused"] = app.query_one("#modeltable").has_focus
            t = app.query_one("#modeltable")
            await pilot.press("j", "j")
            await pilot.pause(0.1)
            seen["row_jj"] = t.cursor_row
            await pilot.press("up")
            await pilot.pause(0.1)
            seen["row_up"] = t.cursor_row
            await pilot.press("G")
            await pilot.pause(0.1)
            seen["row_G"], seen["rows"] = t.cursor_row, t.row_count
            await pilot.press("L")
            await pilot.pause(0.2)
            seen["tab2"] = app.query_one("#tabs").active
            await pilot.press("[", "[", "[")
            await pilot.pause(0.2)
            seen["tab_wrap"] = app.query_one("#tabs").active
        self.run_app(steps)
        ids = seen["ids"]
        self.assertEqual(seen["top"], ids[0])
        self.assertEqual(seen["after_j"], ids[1])
        self.assertEqual(seen["after_down"], ids[2])
        self.assertEqual(seen["after_k"], ids[1])
        self.assertTrue(seen["detail_focused"])
        self.assertTrue(seen["card_focused"])
        self.assertEqual(seen["tab1"], "models")
        self.assertTrue(seen["models_focused"])
        self.assertEqual(seen["row_jj"], 2)
        self.assertEqual(seen["row_up"], 1)
        self.assertEqual(seen["row_G"], seen["rows"] - 1)
        self.assertEqual(seen["tab2"], "jobs")
        self.assertEqual(seen["tab_wrap"], "provision")

    def test_new_job_form(self):
        async def steps(app, pilot):
            await pilot.press("n")
            await pilot.pause(0.2)
            screen = app.screen
            screen.query_one("#kind").value = "p:voice-line"
            screen.query_one("#prompt").value = "Lights are on."
            await pilot.click("#go")
            await pilot.pause(0.2)
        self.run_app(steps)
        self.assertEqual(self.fx.submitted[-1], (None, "voice-line", None, "Lights are on."))

    def _snapshot(self, svg):
        ver_file = SNAP[:-4] + ".version"
        if os.environ.get("LAB_SNAPSHOT_PNG") and shutil.which("rsvg-convert"):
            tmp = os.environ["LAB_SNAPSHOT_PNG"] + ".svg"
            with open(tmp, "w") as f:
                f.write(svg)
            subprocess.run(["rsvg-convert", "-o", os.environ["LAB_SNAPSHOT_PNG"], tmp], check=True)
            os.unlink(tmp)
        if os.environ.get("LAB_SNAPSHOT_UPDATE") or not os.path.exists(SNAP):
            os.makedirs(os.path.dirname(SNAP), exist_ok=True)
            with open(SNAP, "w") as f:
                f.write(svg)
            with open(ver_file, "w") as f:
                f.write(textual.__version__ + "\n")
            return
        with open(ver_file) as f:
            made_with = f.read().strip()
        with open(SNAP) as f:
            want = f.read()
        if made_with != textual.__version__:
            for word in ("GPUS", "SERVICES", "5090", "GITOPS"):
                self.assertIn(word, svg)
            return
        if _norm(svg) != _norm(want):
            with open(SNAP[:-4] + ".new.svg", "w") as f:
                f.write(svg)
            self.fail(f"the dashboard drew differently from {SNAP} (see .new.svg; LAB_SNAPSHOT_UPDATE=1 to accept)")


if __name__ == "__main__":
    unittest.main()
