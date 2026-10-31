"""VECTOR's line in the text installer's rail always shows whole: on every step, for the
desktop's steps and bromigOS Server's longer list, at 120x35 and 80x24, in full colour and in
the Linux console's 16. When the steps leave the rail too little room, the orb gets smaller,
then goes, then his line moves over the page, under the step's title bar (tui.Installer._fit_rail).

  python -m unittest test_rail
"""
import asyncio
import os
import sys
import textwrap
import unittest

HERE = os.path.dirname(os.path.realpath(__file__))
sys.path.insert(0, HERE)
import test_tui  # noqa: E402,F401  (the fake store, back end and environment)

try:
    from bromigos_installer import server, tui
    HAVE = test_tui.HAVE
except ImportError:
    HAVE = False

KEY = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIExampleKeyForTheInstallerTestsOnly alex@laptop"
SKIP = ("auto", "install")          # the countdown and the install itself: they run, they're not shown here


def line_shown(app):
    """(True, how) when his whole line is on the screen, else (False, why)."""
    line = getattr(app, "_vline", "")
    if not line:
        return True, "no line"
    rail, vl = app.query_one("#rail"), app.query_one("#vector-line")
    if rail.display and vl.display and "-away" not in vl.classes:
        rows = len(textwrap.wrap("VECTOR  " + line, max(8, rail.content_size.width)))
        r, c = vl.region, rail.content_region
        ok = r.height >= rows and r.bottom <= c.bottom and r.y >= c.y
        return ok, f"in the rail: {r} inside {c}, {rows} rows"
    w, page = app.query_one("#vector-top"), app.query_one("#page")
    if not (w.display and "-here" in w.classes):
        return False, "neither in the rail nor over the page"
    r = w.region
    rows = len(textwrap.wrap("VECTOR  " + line, max(8, w.content_size.width)))
    ok = r.height >= rows and r.bottom <= page.region.y and str(w.render()).strip().endswith(line.split()[-1])
    return ok, f"over the page: {r}, the page at {page.region}"


class VectorLine(unittest.TestCase):
    def setUp(self):
        if not HAVE:
            self.skipTest("textual isn't installed")

    def every_step(self, edition, size, sixteen):
        env = {"BROMIGOS_COLORS": "16", "TERM": "linux"} if sixteen else {}
        old = {k: os.environ.get(k) for k in ("BROMIGOS_COLORS", "TERM")}
        os.environ.update(env)
        problems, seen = [], []

        async def go():
            app = tui.Installer()
            async with app.run_test(size=size) as pilot:
                await pilot.pause(0.3)
                for _ in range(50):
                    if app.probe is not None:
                        break
                    await pilot.pause(0.1)
                a = app.a
                a.update(disk=(app.probe or {}).get("disks", [{}])[0].get("path"), mode="erase", user="alex",
                         password="correct-horse-battery", password2="correct-horse-battery", hostname="box",
                         host_edited=True)
                if edition == "server":
                    a.update(edition="server", user="admin", found_keys=[], ssh_keys=[KEY])
                    server.set_roles(a, ["lab", "games", "storage"])
                for sid in app.steps():
                    if sid in SKIP:
                        continue
                    if sid == "done":
                        app.done = True
                    await app.show(sid)
                    await pilot.pause(0.2)
                    ok, how = line_shown(app)
                    seen.append(sid)
                    if not ok:
                        problems.append(f"{sid}: {how}")
                return len(app.steps())
        try:
            n = asyncio.run(go())
        finally:
            for k, v in old.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v
        self.assertGreater(len(seen), 5)
        self.assertEqual(problems, [], f"{edition} ({n} steps) at {size[0]}x{size[1]}" + (" in 16 colours" if sixteen else ""))
        return n

    def test_desktop(self):
        for size in ((120, 35), (80, 24)):
            for sixteen in (False, True):
                with self.subTest(size=size, sixteen=sixteen):
                    self.every_step("desktop", size, sixteen)

    def test_server(self):
        for size in ((120, 35), (80, 24)):
            for sixteen in (False, True):
                with self.subTest(size=size, sixteen=sixteen):
                    self.assertGreaterEqual(self.every_step("server", size, sixteen), 16)


if __name__ == "__main__":
    unittest.main()
