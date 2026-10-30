"""The bar's sound popup: its words and holograms (bromigos_soundpopup, without GTK), the
`bromigos sound` changes it relies on (status --light, a device switch moving what plays),
and the hover module's source and config (waybar/hover). The hover itself runs in a real
waybar in e2e_hover_nested.py."""
import json
import os
import re
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
DESKTOP = os.path.dirname(HERE)
sys.path[:0] = [HERE, os.path.join(DESKTOP, "lib")]

import bromigos_soundpopup as S  # noqa: E402
from cmdtest import CmdTest  # noqa: E402


def dev(desc, kind, default=False, **kw):
    d = {"name": kw.pop("name", "alsa_output.x"), "description": desc, "kind": kind, "default": default,
         "volume": 50, "muted": False, "state": "idle", "ports": [], "active_port": None}
    d.update(kw)
    return d


class Words(unittest.TestCase):
    def test_friendly_names(self):
        self.assertEqual(S.friendly(dev("Built-in Audio Analog Stereo", "speakers")), "Built-in Audio")
        self.assertEqual(S.friendly(dev("Yeti Stereo Microphone", "usb")), "Yeti Microphone")
        self.assertEqual(S.friendly(dev("GB205 High Definition Audio (DisplayPort)", "display")), "GB205 (DisplayPort)")
        self.assertEqual(S.friendly(dev("Analog Stereo", "speakers")), "Analog Stereo")    # nothing left: keep it
        self.assertEqual(S.friendly({"name": "n"}), "n")

    def test_glyphs(self):
        self.assertEqual(S.glyph(dev("x", "display")), "monitor")
        self.assertEqual(S.glyph(dev("x", "speakers")), "speaker")
        self.assertEqual(S.glyph(dev("x", "headphones")), "headset")
        self.assertEqual(S.glyph(dev("WH-1000XM5", "bluetooth")), "headset")
        self.assertEqual(S.glyph(dev("Galaxy Buds2 Pro", "bluetooth")), "earbuds")
        self.assertEqual(S.glyph(dev("JBL Flip 6", "bluetooth")), "speaker")
        self.assertEqual(S.glyph(dev("x", "usb"), out=False), "mic")
        self.assertEqual(S.glyph(dev("x", "microphone"), out=False), "mic")

    def test_the_line_under_the_name(self):
        d = dev("x", "speakers", ports=[{"name": "lo", "description": "Line Out"}], active_port="lo")
        self.assertEqual(S.detail(d), "SPEAKERS · LINE OUT")
        bt = dev("WH", "bluetooth", name="bluez_output.00_00_5E_00_53_10.1", muted=True)
        self.assertEqual(S.bt_mac(bt), "00:00:5E:00:53:10")
        self.assertEqual(S.detail(bt, {"mode": "headset", "codec": "mSBC"}), "BLUETOOTH · HEADSET + MIC · mSBC · MUTED")
        self.assertIsNone(S.bt_mac(d))

    def test_rows_put_the_one_in_use_first_and_explain_themselves(self):
        doc = {"output": {"devices": [dev("b", "speakers"), dev("a", "display"), dev("z", "headphones", True)]}}
        self.assertEqual([d["description"] for d in S.rows(doc, "output")], ["z", "a", "b"])
        self.assertEqual(S.rows({}, "input"), [])
        self.assertIn("in use", S.hint(dev("z", "x", True, state="running"), "output"))
        self.assertIn("playing now", S.hint(dev("z", "x", True, state="running"), "output"))
        self.assertIn("moves to it", S.hint(dev("b", "x"), "output"))
        self.assertIn("microphone", S.hint(dev("m", "x"), "input"))


class Cli(CmdTest):
    def test_light_status_leaves_the_slow_parts_out(self):
        d = self.cmd("sound", "status", "--light")
        self.assertIn("output", d)
        self.assertNotIn("mute", d)
        self.assertNotIn(["mute", "status", "--json"], self.calls("bromigos"))

    def test_a_new_output_takes_what_plays(self):
        st = self.state("pactl")
        st["sink_inputs"].append(dict(st["sink_inputs"][0], index=900, sink=58))   # pinned elsewhere
        with open(os.path.join(self.fx, "pactl.json"), "w") as f:
            json.dump(st, f)
        d = self.cmd("sound", "output", "bluez_output.00_00_5E_00_53_10.1")
        self.assertEqual(d["output"]["default"], "bluez_output.00_00_5E_00_53_10.1")
        self.assertTrue(all(a["output"] == "bluez_output.00_00_5E_00_53_10.1" for a in d["apps"]))


class Hover(unittest.TestCase):
    def test_the_bar_wires_the_volume_to_the_popup(self):
        with open(os.path.join(DESKTOP, "waybar", "config.jsonc")) as f:
            text = f.read()
        cfg = json.loads(re.sub(r",(\s*[}\]])", r"\1", re.sub(r"^\s*//.*$", "", text, flags=re.M)))
        right = cfg["modules-right"]
        self.assertEqual(right[right.index("pulseaudio") + 1], "cffi/sound-hover")
        h = cfg["cffi/sound-hover"]
        self.assertEqual((h["target"], h["app"], h["open-delay"]), ("pulseaudio", S.APP_ID, 350))
        self.assertEqual(cfg["pulseaudio"]["on-click"], "bromigos sound popup pin")
        self.assertIn("mute", cfg["pulseaudio"]["on-click-middle"])

    def test_the_module_speaks_the_apps_actions(self):
        with open(os.path.join(DESKTOP, "waybar", "hover", "bromigos-hover.c")) as f:
            src = f.read()
        self.assertIn('"org.gtk.Actions", "Activate"', src)
        for verb in ('"hover"', '"leave"'):
            self.assertIn(verb, src)
        self.assertIn("wbcffi_version = 2", src)


if __name__ == "__main__":
    unittest.main()
