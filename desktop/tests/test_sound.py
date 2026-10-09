"""`bromigos sound` and `bromigos scene` against the stand-ins (fixtures/bin/pactl: a
PipeWire pulse server with three outputs, two inputs and two apps playing)."""
import unittest

from cmdtest import CmdTest


class SoundTest(CmdTest):
    def test_status(self):
        d = self.cmd("sound")
        self.assertIn("PipeWire", d["server"])
        outs = {x["description"]: x for x in d["output"]["devices"]}
        self.assertEqual(outs["Built-in Audio Analog Stereo"]["kind"], "speakers")
        self.assertTrue(outs["Built-in Audio Analog Stereo"]["default"])
        self.assertEqual(outs["WH-1000XM5"]["kind"], "bluetooth")
        self.assertEqual(outs["GB205 High Definition Audio (DisplayPort)"]["kind"], "display")
        self.assertEqual(outs["Built-in Audio Analog Stereo"]["volume"], 62)
        self.assertEqual([x["description"] for x in d["input"]["devices"]],
                         ["Yeti Stereo Microphone", "Built-in Audio Analog Stereo"])   # no monitors
        self.assertEqual([a["app"] for a in d["apps"]], ["Firefox", "Spotify"])
        self.assertEqual(d["mute"]["muted"], False)
        self.assertEqual(d["sounds"], {"enabled": True, "volume": 30})

    def test_default_output_moves_the_apps(self):
        d = self.cmd("sound", "output", "WH-1000XM5")
        self.assertEqual(d["output"]["default"], "bluez_output.AC_80_0A_00_00_01.1")
        self.assertTrue(all(a["output"] == "bluez_output.AC_80_0A_00_00_01.1" for a in d["apps"]))
        self.assertIn("WH-1000XM5", d["said"])
        self.cmd("sound", "output", "nope", ok=False)

    def test_volumes_and_mutes(self):
        d = self.cmd("sound", "volume", "output", "40")
        self.assertEqual(next(x for x in d["output"]["devices"] if x["default"])["volume"], 40)
        self.assertIn(["set-sink-volume", "alsa_output.pci-0000_0c_00.4.analog-stereo", "40%"], self.calls("pactl"))
        d = self.cmd("sound", "volume", "input", "15")
        self.assertEqual(next(x for x in d["input"]["devices"] if x["default"])["volume"], 15)
        self.assertEqual(self.cmd("sound", "volume", "output", "151", ok=False)["error"], "151: 0 to 150")
        self.cmd("sound", "volume", "output", "loud", ok=False)
        d = self.cmd("sound", "mute", "output", "on")
        self.assertTrue(next(x for x in d["output"]["devices"] if x["default"])["muted"])
        d = self.cmd("sound", "mute", "output", "toggle")
        self.assertFalse(next(x for x in d["output"]["devices"] if x["default"])["muted"])

    def test_ports(self):
        self.cmd("sound", "port", "output", "alsa_output.pci-0000_0c_00.4.analog-stereo", "analog-output-headphones")
        self.assertEqual(self.state("pactl")["sinks"][0]["active_port"], "analog-output-headphones")
        self.cmd("sound", "port", "output", "alsa_output.pci-0000_0c_00.4.analog-stereo", "nope", ok=False)

    def test_apps(self):
        d = self.cmd("sound", "app-volume", "97", "35")
        self.assertEqual(next(a for a in d["apps"] if a["id"] == 97)["volume"], 35)
        d = self.cmd("sound", "app-mute", "91", "on")
        self.assertTrue(next(a for a in d["apps"] if a["id"] == 91)["muted"])
        d = self.cmd("sound", "app-output", "91", "WH-1000XM5")
        self.assertEqual(next(a for a in d["apps"] if a["id"] == 91)["output"], "bluez_output.AC_80_0A_00_00_01.1")
        self.cmd("sound", "app-volume", "12345", "35", ok=False)

    def test_the_desktops_sounds(self):
        d = self.cmd("sound", "all-mute", "on")
        self.assertTrue(d["mute"]["muted"])
        self.assertEqual(self.state("bromigos")["mute"], {"theme": True, "vector": True})
        d = self.cmd("sound", "sounds", "off")
        self.assertFalse(d["sounds"]["enabled"])
        d = self.cmd("sound", "sounds-volume", "20")
        self.assertEqual(d["sounds"]["volume"], 20)
        self.assertIn("volume = 0.2", self.read(".config", "bromigos", "live", "overrides.toml"))
        self.cmd("sound", "sounds-volume", "101", ok=False)

    def test_without_pactl(self):
        import os
        import sys
        bare = os.path.join(self.tmp, "bare")
        os.makedirs(bare)
        os.symlink(sys.executable, os.path.join(bare, "python3"))
        d = self.cmd("sound", ok=False, env={"PATH": bare})
        self.assertIn("pactl isn't installed", d["error"])


class SceneTest(CmdTest):
    def test_set_get_reset_keeps_the_rest(self):
        import os
        os.makedirs(self.path(".config", "bromigos", "live"))
        with open(self.path(".config", "bromigos", "live", "overrides.toml"), "w") as f:
            f.write("# mine\n[rain]\nenabled = false   # no rain\n")
        d = self.cmd("scene", "set", "world.enabled", "off")
        self.assertFalse(d["values"]["world.enabled"])
        self.cmd("scene", "set", "general.fps", "24")
        text = self.read(".config", "bromigos", "live", "overrides.toml")
        self.assertIn("enabled = false   # no rain", text)
        self.assertIn("[world]\nenabled = false", text)
        d = self.cmd("scene", "get", "general.fps", "world.enabled")
        self.assertEqual(d["values"], {"general.fps": 24, "world.enabled": False})
        self.assertTrue(all(s["yours"] for s in d["settings"]))
        d = self.cmd("scene", "reset", "world.enabled")
        self.assertTrue(d["values"]["world.enabled"])
        self.assertIn("# no rain", self.read(".config", "bromigos", "live", "overrides.toml"))

    def test_refusals(self):
        self.assertIn("0.0 to 1.0", self.cmd("scene", "set", "sounds.volume", "3", ok=False)["error"])
        self.cmd("scene", "set", "general.fps", "fast", ok=False)
        self.cmd("scene", "set", "rain.enabled", "on", ok=False)        # not one of its keys
        self.cmd("scene", "set", "general.monitor", 'DP-1"\n[x]', ok=False)


if __name__ == "__main__":
    unittest.main()
