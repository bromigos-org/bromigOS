"""Reduced motion (live/motion.py, docs/accessibility.md): the logic, without a GPU.

    cd live && python -m unittest discover -s tests

The offscreen render checks (frames, flashes, parallax, the intercept) need EGL:
tests/offscreen_motion.py.
"""
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from live import actors as A  # noqa: E402
from live import config, motion  # noqa: E402


class ModeTest(unittest.TestCase):
    def test_modes_and_the_old_switch(self):
        self.assertEqual(motion.mode({}), "full")
        self.assertEqual(motion.mode({"general": {"motion": "still"}}), "still")
        self.assertEqual(motion.mode({"general": {"motion": "wobbly"}}), "full")
        self.assertEqual(motion.mode({"general": {"reduced_motion": True}}), "reduced")
        # the old switch never makes a calmer choice less calm
        self.assertEqual(motion.mode({"general": {"motion": "still", "reduced_motion": True}}), "still")
        self.assertTrue(motion.calm("reduced") and motion.calm({"general": {"motion": "still"}}))
        self.assertFalse(motion.calm("full"))

    def test_the_accessibility_file_sets_general_motion(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "accessibility.toml")
            old = config.A11Y
            config.A11Y = path
            try:
                cfg = config._motion({"general": {"motion": "full", "reduced_motion": False}})
                self.assertEqual(cfg["general"]["motion"], "full")      # no file: as it was
                with open(path, "w") as f:
                    f.write('motion = "still"\ncontrast = "high"\n')
                cfg = config._motion({"general": {"motion": "full", "reduced_motion": False}})
                self.assertEqual(cfg["general"]["motion"], "still")
                self.assertTrue(cfg["general"]["reduced_motion"])     # older readers follow too
                with open(path, "w") as f:
                    f.write('motion = "sideways"\n')
                cfg = config._motion({"general": {"motion": "reduced", "reduced_motion": False}})
                self.assertEqual(cfg["general"]["motion"], "reduced")  # a bad value: config.toml's
                with open(path, "w") as f:
                    f.write("not toml [")
                cfg = config._motion({"general": {"motion": "full", "reduced_motion": False}})
                self.assertEqual(cfg["general"]["motion"], "full")
            finally:
                config.A11Y = old


class ClockTest(unittest.TestCase):
    def test_full_is_the_renderers_own_time(self):
        c = motion.Clock("full")
        for t in (0.0, 1.5, 7.25, 100.0):
            self.assertEqual(c(t), t)
            self.assertEqual(c.peek(t + 1), t + 1)

    def test_reduced_runs_slower(self):
        c = motion.Clock("reduced")
        c(10.0)
        t0 = c.t
        self.assertAlmostEqual(c(12.0) - t0, 2.0 * motion.RATE["reduced"])
        self.assertAlmostEqual(c.peek(13.0) - c.t, motion.RATE["reduced"])
        self.assertLess(motion.RATE["reduced"], 0.5)

    def test_still_stands_until_stepped(self):
        c = motion.Clock("still")
        a = c(1.0)
        self.assertEqual(c(50.0), a)
        self.assertEqual(c.peek(90.0), a)
        self.assertEqual(c.step(motion.STILL_STEP), a + motion.STILL_STEP)
        self.assertEqual(c(120.0), a + motion.STILL_STEP)

    def test_still_steps_cover_the_jump(self):
        steps = motion.still_steps(6.0, 0.1)
        self.assertEqual(len(steps), 60)
        self.assertAlmostEqual(sum(dt for _, dt in steps), 6.0)
        self.assertAlmostEqual(steps[-1][0], 0.0)     # the last lands on the new time


def _inst(kind, states):
    d = A.Def({"id": "x", "kind": kind, "sprite": "s", "states": states},
              {"s": A.Sprite([(0.0, 0.0, 1.0, 1.0, 1.0)])}, None)
    inst = A.Inst(d, "k", 0.0)
    inst.state, inst.state_t = list(states)[0], 0.0
    return d, inst


class LightsTest(unittest.TestCase):
    def levels(self, calm, cfg):
        acts = A.Actors([])
        acts.calm = calm
        d, inst = _inst("signal", {"on": cfg})
        return [acts._blink(inst, t / 30.0, cfg) for t in range(0, 300)]

    def test_needs_you_blinks_unless_calm(self):
        cfg = {"signal": True}
        full = self.levels(False, cfg)
        self.assertGreater(max(full) - min(full), 0.8)       # the double flash, then the blink
        calm = self.levels(True, cfg)
        self.assertEqual(len(set(calm)), 1)                  # steady
        self.assertGreater(calm[0], 1.0)                     # and brighter than plain "on"

    def test_pulse_and_flicker_hold_steady_when_calm(self):
        for cfg in ({"pulse": 0.4}, {"flicker": True}):
            self.assertGreater(len(set(self.levels(False, cfg))), 1)
            self.assertEqual(set(self.levels(True, cfg)), {1.0})

    def test_a_rising_agents_eyes_come_up_without_flicker(self):
        acts = A.Actors([])
        acts.calm = True
        d, inst = _inst("agents", {"working": {}})
        inst.rise_t = 0.0
        self.assertEqual(acts._blink(inst, 0.5, {}), 0.0)    # under: dark
        inst.extra["booted"] = 1.0
        ups = [acts._blink(inst, 1.0 + k / 30.0, {}) for k in range(60)]
        self.assertEqual(ups, sorted(ups))                   # only ever brighter
        self.assertEqual(ups[-1], 1.0)

    def test_still_spawns_no_one_off_creatures(self):
        d = A.Def({"id": "ev", "kind": "event", "sprite": "s", "on": [{"event": "notify", "count": 2}]},
                  {"s": A.Sprite([(0.0, 0.0, 1.0, 1.0, 1.0)])}, None)
        acts = A.Actors([d])
        acts.event("notify", 0.0)
        self.assertEqual(len(acts.insts), 2)
        acts = A.Actors([d])
        acts.still = True
        acts.event("notify", 0.0)
        self.assertEqual(len(acts.insts), 0)


class FirefliesTest(unittest.TestCase):
    def test_they_glow_steadily_when_calm(self):
        try:
            from live.fireflies import Fireflies
        except ImportError as e:                              # numpy missing
            self.skipTest(str(e))
        for calm, steady in ((False, False), (True, True)):
            f = Fireflies({"max": 40, "base": 40, "gain": 0}, 900)
            f.calm = calm
            for k in range(60):                              # let them all come out
                f.update(k * 0.1, 0.1, 1.0, 1.0)
            a = f.update(6.0, 0.0, 1.0, 1.0)
            b = f.update(7.3, 0.0, 1.0, 1.0)
            ia = sorted(r[7] for rows in a.values() for r in rows)
            ib = sorted(r[7] for rows in b.values() for r in rows)
            self.assertEqual(ia == ib, steady)


class PaletteTest(unittest.TestCase):
    """The apps that draw their own read the settings from palette.json (bromigos_theme)."""

    def test_high_contrast_and_motion_from_palette_json(self):
        import json
        import bromigos_theme as T
        with tempfile.TemporaryDirectory() as d:
            old = T.PATH
            T.PATH = os.path.join(d, "palette.json")
            try:
                T._load()
                self.assertFalse(T.high_contrast())          # no file: the Wick, as it was
                self.assertEqual(T.motion(), "full")
                self.assertEqual(T.retint("#001300"), "#001300")
                with open(T.PATH, "w") as f:
                    json.dump({"theme": "wick", "colors": {"panel": "#000200"}, "tables": {},
                               "motion": "still", "contrast": {"mode": "high", "ok": True}}, f)
                T._load()
                self.assertTrue(T.high_contrast())
                self.assertEqual(T.motion(), "still")
                # the Wick's hard-coded colours follow its high-contrast ones
                self.assertEqual(T.retint("#001300"), "#000200")
            finally:
                T.PATH = old
                T._load()


if __name__ == "__main__":
    unittest.main()
