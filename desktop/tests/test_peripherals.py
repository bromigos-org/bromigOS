"""The peripheral modules' running parts (lib/bromigos_peripherals.py): the dial, the
lighting and what the daemon reads from `bromigos peripheral status --json`. No devices,
no desktop: commands are recorded, VECTOR's state and the theme are given.

    PYTHONPATH=lib python -m unittest discover -s tests
"""
import unittest

import bromigos_peripherals as P

STATE = {
    "state": "idle", "mood": "calm", "voice": "main", "voice_mode": "auto", "conversation": False,
    "voices": [{"role": "main", "name": "caretaker", "colour": "#39ff14"},
               {"role": "robot", "name": "sigil_unit", "colour": "#3fe0c5"},
               {"role": "notify", "name": None, "colour": "#d4af37"}],
    "voice_colour": "#39ff14",
}
THEME = {"primary": "#b8e05a", "warn": "#e0a040", "danger": "#ff5050"}


class Clock:
    def __init__(self):
        self.t = 100.0

    def __call__(self):
        return self.t


class DialTest(unittest.TestCase):
    def setUp(self):
        self.ran = []
        self.state = dict(STATE)
        self.clock = Clock()
        self.dial = P.Dial(self.ran.append, state=lambda: self.state, clock=self.clock, holo="holo")

    def voice_cmds(self):
        return [c for c in self.ran if c[0] == "holo"]

    def test_turns_step_through_auto_then_his_voices(self):
        self.assertEqual(self.dial.event(P.EV_REL, P.REL_HWHEEL, 1), "voice main")
        self.state["voice_mode"] = "main"
        self.clock.t += 1
        self.assertEqual(self.dial.event(P.EV_REL, P.REL_HWHEEL, 1), "voice robot")
        self.state["voice_mode"] = "notify"
        self.clock.t += 1
        self.assertEqual(self.dial.event(P.EV_REL, P.REL_HWHEEL, 1), "voice auto")   # wraps
        self.state["voice_mode"] = "auto"
        self.clock.t += 1
        self.assertEqual(self.dial.event(P.EV_REL, P.REL_HWHEEL, -1), "voice notify")  # left: back
        self.assertEqual(self.voice_cmds(), [["holo", "voice", m] for m in ("main", "robot", "auto", "notify")])

    def test_a_fast_turn_is_one_step_per_slice(self):
        self.dial.event(P.EV_REL, P.REL_HWHEEL, 1)
        self.clock.t += 0.05
        self.assertIsNone(self.dial.event(P.EV_REL, P.REL_HWHEEL, 1))
        self.clock.t += P.STEP_GAP
        self.assertIsNotNone(self.dial.event(P.EV_REL, P.REL_HWHEEL, 1))

    def test_the_notification_names_the_voice(self):
        self.state["voice_mode"] = "main"
        self.dial.event(P.EV_REL, P.REL_HWHEEL, 1)
        note = [c for c in self.ran if c[0] == "notify-send"][-1]
        self.assertEqual(note[-2:], ["VOICE", "Sigil Unit"])
        self.assertIn("string:x-dunst-stack-tag:vector-voice", note)
        self.state["voice_mode"] = "robot"
        self.clock.t += 1
        self.dial.event(P.EV_REL, P.REL_HWHEEL, 1)
        self.assertEqual([c for c in self.ran if c[0] == "notify-send"][-1][-1], "Notify")
        self.assertEqual(P.voice_order(self.state)[0], ("auto", P.AUTO_LABEL))

    def test_an_older_vector_without_voices_cycles(self):
        self.state.pop("voices")
        self.assertEqual(self.dial.event(P.EV_REL, P.REL_HWHEEL, -1), "voice cycle")
        self.assertEqual(self.voice_cmds(), [["holo", "voice", "cycle"]])

    def test_no_vector_says_so(self):
        self.state = None
        self.assertIn("not running", self.dial.event(P.EV_REL, P.REL_HWHEEL, 1))
        self.assertEqual(self.voice_cmds(), [])

    def test_the_roller_is_the_volume(self):
        self.assertEqual(self.dial.event(P.EV_KEY, P.KEY_VOLUMEUP, 1), "volume 2%+")
        self.assertEqual(self.dial.event(P.EV_KEY, P.KEY_VOLUMEDOWN, 2), "volume 2%-")   # held: repeats
        self.assertIsNone(self.dial.event(P.EV_KEY, P.KEY_VOLUMEUP, 0))                 # released
        self.assertEqual(self.dial.event(P.EV_REL, P.REL_WHEEL, -3), "volume 6%-")
        self.assertEqual(self.ran[0], ["wpctl", "set-volume", "-l", "1.0", "@DEFAULT_AUDIO_SINK@", "2%+"])
        quiet = P.Dial(self.ran.append, state=lambda: STATE, roller=False)
        self.assertIsNone(quiet.event(P.EV_KEY, P.KEY_VOLUMEUP, 1))


class LightingTest(unittest.TestCase):
    def colour(self, n):
        return THEME[n]

    def test_targets_follow_his_voice_and_mood(self):
        st = dict(STATE)
        self.assertEqual(P.lighting_target(None, self.colour), ("static", "#b8e05a", P.REST_BRIGHTNESS))
        self.assertEqual(P.lighting_target(st, self.colour), ("static", "#39ff14", P.REST_BRIGHTNESS))
        st["state"] = "speaking"
        self.assertEqual(P.lighting_target(st, self.colour)[2], P.ACTIVE_BRIGHTNESS)
        st["voice_colour"] = "#3fe0c5"
        self.assertEqual(P.lighting_target(st, self.colour)[1], "#3fe0c5")
        st["mood"] = "concerned"
        self.assertEqual(P.lighting_target(st, self.colour), ("static", "#e0a040", P.ACTIVE_BRIGHTNESS))
        st["mood"] = "alarmed"
        self.assertEqual(P.lighting_target(st, self.colour), ("breath", "#ff5050", P.ACTIVE_BRIGHTNESS))
        # an older VECTOR: the pinned voice's colour from his list
        old = {k: v for k, v in STATE.items() if k != "voice_colour"}
        old["voice_mode"] = "robot"
        self.assertEqual(P.lighting_target(old, self.colour)[1], "#3fe0c5")
        # following the theme: its primary, whatever his voice or mood
        loud = {"state": "speaking", "mood": "alarmed", "voice_colour": "#3fe0c5"}
        self.assertEqual(P.lighting_target(loud, self.colour, "theme"), ("static", "#b8e05a", P.REST_BRIGHTNESS))

    def test_writes_only_on_a_change_and_keeps_the_modules_devices(self):
        class Dev:
            def __init__(self, pid):
                self._pid, self.name = pid, f"dev {pid:04x}"

        applied, st = [], dict(STATE)
        clock = Clock()
        light = P.Lighting(lambda: [Dev(0x028D), Dev(0x0050)], self.colour, state=lambda: st,
                           apply=lambda devs, *t: applied.append(([d._pid for d in devs], t)), clock=clock,
                           pids={0x028D})
        self.assertIsNotNone(light.tick())
        self.assertIsNone(light.tick())                      # the same target: no write
        st["mood"] = "alarmed"
        light.tick()
        self.assertEqual(len(applied), 2)
        self.assertEqual(applied[0][0], [0x028D])            # scope "device": the keyboard only
        clock.t += 61                                        # found again a minute on: re-applied
        light.tick()
        self.assertEqual(len(applied), 3)

    def test_openrazer_keyboard_and_mouse(self):
        calls = []

        class FX:
            def __init__(self, tag):
                self.tag = tag

            def static(self, *c):
                calls.append((self.tag, "static", c))

            def breath_single(self, *c):
                calls.append((self.tag, "breath", c))

        class Kbd:
            name = "kbd"
            fx = FX("kbd")

            def has(self, cap):
                return cap in ("brightness", "lighting_static", "lighting_breath_single")

        class Mouse:
            name = "mouse"

            class fx:  # noqa: N801  (openrazer's attribute)
                class misc:  # noqa: N801
                    logo, scroll = FX("logo"), FX("scroll")

            def has(self, cap):
                return cap in ("lighting_logo_static", "lighting_scroll_static")

        k = Kbd()
        P.apply_openrazer([k, Mouse()], "breath", "#ff0000", 100)
        self.assertEqual(k.brightness, 100)
        self.assertEqual(calls[0], ("kbd", "breath", (255, 0, 0)))
        P.apply_openrazer([Mouse()], "static", "#ff8000", 50)
        self.assertIn(("logo", "static", (127, 64, 0)), calls)


class PlanTest(unittest.TestCase):
    DOC = {"ok": True, "hypr_current": True, "modules": [{
        "id": "razer-keyboard", "devices": ["razer-x", "razer-x-1"], "dials": ["/dev/input/event25"],
        "dial": {"turn": "vector-voice", "roller": "volume", "hint": ""},
        "rgb": {"backend": "openrazer", "follow": "vector", "hint": ""}, "rgb_scope": "all",
        "found": [{"usb": "1532:028d"}]}]}

    def test_dials_and_lighting(self):
        dials, light = P.plan(self.DOC)
        self.assertEqual(dials, [("razer-keyboard", "/dev/input/event25", True)])
        self.assertEqual(light, ("openrazer", None, "vector"))
        doc = {"modules": [dict(self.DOC["modules"][0], rgb_scope="device")]}
        self.assertEqual(P.plan(doc)[1], ("openrazer", {0x028D}, "vector"))
        theme = dict(self.DOC["modules"][0]["rgb"], follow="theme")
        doc = {"modules": [dict(self.DOC["modules"][0], rgb=theme)]}
        self.assertEqual(P.plan(doc)[1], ("openrazer", None, "theme"))
        doc = {"modules": [dict(self.DOC["modules"][0], rgb=None, dial=None)]}
        self.assertEqual(P.plan(doc), ([], None))
        self.assertEqual(P.hypr_names(self.DOC), ["razer-x", "razer-x-1"])


if __name__ == "__main__":
    unittest.main()
