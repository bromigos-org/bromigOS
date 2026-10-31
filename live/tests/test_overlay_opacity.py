"""The full-screen overlays never sit over a working window at partial opacity
(live/overlays.py; docs/DRIFTGLASS.md, "Calm by default"): the logic, without a GPU.

    cd live && python -m unittest discover -s tests

Each frame's uniforms are what ov.frag composites: `backdrop` is the void's opacity, `frozen`
the captured screen's, `fade` the whole overlay's; `gadget_fade` and the emblems' `alpha` are
what's drawn on it. A frame covers the windows when the void or the captured screen is
opaque. The checks, at every motion setting:

  - the intercept draws its card (words, emblem) only on a covering frame: no ghost, no card
    fading over the desktop;
  - where it doesn't cover, it draws nothing, only the void lifting (reduced and still,
    which can't cut), for no longer than CALM_CLEAR;
  - it finishes at its deadline, which the window's watchdog enforces even without frames;
    a skip moves the deadline up;
  - the screensaver is opaque once its fade-in is done, and has a deadline once closed.

The composited result is checked in a real compositor by desktop/tests/e2e_overlay_nested.py.
"""
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from live import overlays  # noqa: E402

STEP = 1 / 120


class _Data:
    static = {"sys": "Arch Linux", "kernel": "6.0", "arch": "x86_64", "cpu_model": "Test CPU",
              "gpu_name": "Test GPU"}

    def snapshot(self):
        return {"cpu": 10, "mounts": []}


def _cfg(motion):
    return {"general": {"motion": motion, "reduced_motion": motion != "full"}, "space": {}, "rain": {"enabled": True}}


def make(kind, motion):
    with mock.patch.object(overlays, "Stage"), mock.patch.object(overlays, "Emblem"), \
            mock.patch.object(overlays.Intercept, "_syslines", lambda self: []), \
            mock.patch.object(overlays, "tear_style", lambda: 0.0):
        return kind(_cfg(motion), _Data(), 1280, 800)


def drawn(u):
    """Anything drawn besides the void and the captured screen."""
    return u.get("gadget_fade", 1.0) > 0.0 or any(e.get("alpha", 1.0) > 0.0 for e in u.get("emblems", []))


def covers(u):
    if u.get("finished"):
        return False
    return max(u.get("backdrop", 0.0), u.get("frozen", 0.0)) * u.get("fade", 1.0) >= 1.0


def timeline(r, until):
    t, out = 0.0, []
    while t <= until:
        out.append((t, r.frame(t, {})))
        t += STEP
    return out


class InterceptTest(unittest.TestCase):
    def test_no_card_or_ghost_over_the_desktop(self):
        for motion in ("full", "reduced", "still"):
            with self.subTest(motion=motion):
                r = make(overlays.Intercept, motion)
                uncovered = []
                for t, u in timeline(r, r.t_end + 1.0):
                    if u.get("finished"):
                        self.assertGreaterEqual(t, r.t_end - STEP)
                        continue
                    if not covers(u):
                        self.assertFalse(drawn(u), f"{motion}: something drawn at {t:.2f}s over the desktop: {u}")
                        self.assertNotIn("emblems", u)
                        uncovered.append(t)
                if motion == "full":
                    self.assertEqual(uncovered, [], "full motion cuts: never a translucent frame")
                else:
                    self.assertTrue(uncovered, "reduced and still lift the void instead of cutting")
                    self.assertLessEqual(uncovered[-1] - uncovered[0], r.CALM_CLEAR + STEP)
                    self.assertGreaterEqual(uncovered[0], r.t_cut + r.CALM_OUT - STEP)

    def test_it_finishes_by_its_deadline(self):
        for motion in ("full", "reduced", "still"):
            with self.subTest(motion=motion):
                r = make(overlays.Intercept, motion)
                self.assertEqual(r.deadline(), r.t_end)
                self.assertTrue(r.frame(r.deadline(), {}).get("finished"))
                # the full sequence lasts seconds, not the old three-second ghost on top
                self.assertLess(r.t_end - r.t_cut, 1.6)

    def test_a_skip_moves_the_deadline_up(self):
        r = make(overlays.Intercept, "full")
        with mock.patch.object(r, "now", return_value=1.0):
            r.skip()
        self.assertAlmostEqual(r.deadline(), 1.0 + (r.t_end - r.t_cut))
        # skipped at 1 s: the cut's frame, then finished
        self.assertTrue(covers(r.frame(1.01, {})))
        self.assertTrue(r.frame(r.deadline() + 0.01, {}).get("finished"))


class ScreensaverTest(unittest.TestCase):
    def test_opaque_once_faded_in(self):
        for motion in ("full", "reduced", "still"):
            with self.subTest(motion=motion):
                r = make(overlays.Screensaver, motion)
                with mock.patch.object(overlays.gadgets, "local_sun_angle", return_value=0.0):
                    for t in (0.8, 1.0, 5.0, 60.0, 600.0):
                        u = r.frame(t, {})
                        self.assertTrue(covers(u), f"{motion} at {t}s: {u}")
                self.assertIsNone(r.deadline())

    def test_closing_has_a_deadline(self):
        r = make(overlays.Screensaver, "full")
        with mock.patch.object(r, "now", return_value=30.0):
            r.close()
        self.assertAlmostEqual(r.deadline(), 30.26)
        with mock.patch.object(overlays.gadgets, "local_sun_angle", return_value=0.0):
            self.assertTrue(r.frame(30.3, {}).get("finished"))


if __name__ == "__main__":
    unittest.main()
