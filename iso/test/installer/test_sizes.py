"""The text installer and the Server tour at every size they must fit (docs/iso.md): wide
consoles, 80×24 (a VT, a serial line), a phone's 50–60 columns, down to the 40×15 minimum.
Every step at 150×45, 120×35, 80×24, 60×30 and 40×15: nothing runs off the side (no sideways
scrolling), the buttons and the hint line stay on screen, the focused control is in view; below
40×15 the "make the window bigger" sheet covers it. BROMIGOS_INSTALLER_SHOTS=DIR keeps the
pictures (DIR/sizes/WxH-STEP.svg).

  python -m unittest discover -s iso/test/installer -p 'test_sizes.py'
"""
import asyncio
import os
import sys
import unittest

HERE = os.path.dirname(os.path.realpath(__file__))
sys.path.insert(0, HERE)
import test_tui  # noqa: E402,F401  (the recorded disks, the fake store and back end)

SIZES = [(150, 45), (120, 35), (80, 24), (60, 30), (40, 15)]
SHOTS = os.environ.get("BROMIGOS_INSTALLER_SHOTS")

try:
    from bromigos_installer import tui
    import bromigos_textual  # noqa: F401
    HAVE = True
except ImportError:
    HAVE = False


def check_fits(test, app, w, h, where):
    page = app.query_one("#page")
    test.assertEqual(page.max_scroll_x, 0, f"{where}: runs off the side")
    for sel in ("#nav", "#hint"):
        r = app.query_one(sel).region
        test.assertTrue(r.right <= w and r.bottom <= h, f"{where}: {sel} off screen {r}")
    for b in app.query("#nav Button"):
        if b.display:
            test.assertTrue(b.region.right <= w and b.region.width > 0, f"{where}: {b.id} cut off {b.region}")
    f = app.focused
    if f is not None and f.display and f.region.height:
        test.assertTrue(f.region.bottom <= h and f.region.right <= w, f"{where}: the focused {f!r} out of view {f.region}")


class Sizes(unittest.TestCase):
    def setUp(self):
        if not HAVE:
            self.skipTest("textual or bromigos_textual isn't here")

    def test_every_step_fits(self):
        async def go(w, h):
            app = tui.Installer()
            seen = []
            async with app.run_test(size=(w, h)) as pilot:
                await pilot.pause(0.5)
                for _ in range(50):
                    if app.probe is not None:
                        break
                    await pilot.pause(0.1)
                app.a.update(disk="/dev/nvme0n1", mode="alongside", user="alex", full_name="Alex Rivera",
                             hostname="alex-pc", password="x", edition="server")
                for sid in [s for s in app.steps() if s not in ("install", "done")] + ["install"]:
                    await app.show(sid)
                    await pilot.pause(0.2)
                    if app.focused is not None:
                        app.focused.scroll_visible(animate=False)
                        await pilot.pause(0.1)
                    check_fits(self, app, w, h, f"{w}×{h} {sid}")
                    if SHOTS:
                        os.makedirs(os.path.join(SHOTS, "sizes"), exist_ok=True)
                        app.save_screenshot(os.path.join(SHOTS, "sizes", f"{w}x{h}-{sid}.svg"))
                    seen.append(sid)
                self.assertFalse(app.query_one("#too-small").display and app.screen.has_class("-too-small"))
            return seen
        for w, h in SIZES:
            with self.subTest(size=f"{w}x{h}"):
                self.assertIn("disk", asyncio.run(go(w, h)))

    def test_live_reflow_and_too_small(self):
        async def go():
            app = tui.Installer()
            async with app.run_test(size=(120, 35)) as pilot:
                await pilot.pause(0.5)
                await app.show("disk")
                await pilot.pause(0.3)
                wide_rail = app.query_one("#rail").display
                await pilot.resize_terminal(60, 30)
                await pilot.pause(0.5)
                narrow_rail = app.query_one("#rail").display
                top = str(app.query_one("#top").render())
                await pilot.resize_terminal(39, 14)
                await pilot.pause(0.3)
                small = app.screen.has_class("-too-small")
                await pilot.resize_terminal(80, 24)
                await pilot.pause(0.3)
                back = not app.screen.has_class("-too-small")
                return wide_rail, narrow_rail, top, small, back
        wide_rail, narrow_rail, top, small, back = asyncio.run(go())
        self.assertTrue(wide_rail)
        self.assertFalse(narrow_rail)
        self.assertIn("WHERE", top)
        self.assertTrue(small and back)


class ServerTourSizes(unittest.TestCase):
    """bromigOS Server's welcome tour at the same sizes (its --render --size checks each step fits)."""

    def test_every_step_fits(self):
        if not HAVE:
            self.skipTest("textual or bromigos_textual isn't here")
        import subprocess
        import tempfile
        tour = os.path.join(HERE, "../../../bin/bromigos-welcome-console")
        env = dict(os.environ, PYTHONPATH=os.path.join(HERE, "../../../lib"))
        for w, h in SIZES:
            out = os.path.join(SHOTS, "sizes", f"server-{w}x{h}") if SHOTS else tempfile.mkdtemp()
            with self.subTest(size=f"{w}x{h}"):
                r = subprocess.run([sys.executable, tour, "--render", out, "--size", f"{w}x{h}"], env=env,
                                   capture_output=True, text=True, timeout=180)
                self.assertEqual(r.returncode, 0, r.stdout[-600:] + r.stderr[-600:])
                self.assertEqual(len([f for f in os.listdir(out) if f.endswith(".svg")]), 5)


if __name__ == "__main__":
    unittest.main()
