"""`bromigos clock` against the stand-ins (fixtures/bin/timedatectl; pkill records the
signal it would send waybar): the time zone, network time, the bar's clock and the include."""
import json
import os
import shutil
import unittest

from cmdtest import CmdTest, DESKTOP

SETTINGS = (".config", "bromigos", "waybar", "settings.jsonc")


class ClockTest(CmdTest):
    def setUp(self):
        super().setUp()
        os.makedirs(self.path(".config", "waybar"))
        shutil.copy(os.path.join(DESKTOP, "user", "waybar", "config"), self.path(".config", "waybar", "config"))

    def bar_format(self):
        text = self.read(*SETTINGS)
        body = "\n".join(ln for ln in text.splitlines() if not ln.startswith("//"))
        return json.loads(body)["clock"]

    def test_status(self):
        d = self.cmd("clock")
        self.assertEqual((d["timezone"], d["ntp"], d["synced"]), ("America/Los_Angeles", True, True))
        b = d["bar"]
        self.assertEqual((b["format"], b["seconds"], b["date"], b["format_string"]), ("24", True, False, "{:%H:%M:%S}"))
        self.assertTrue(b["hooked"])                     # the template a new user gets includes it first
        self.assertFalse(b["exists"])

    def test_timezone_and_ntp(self):
        self.assertEqual(self.cmd("clock", "timezone", "Europe/Lisbon")["timezone"], "Europe/Lisbon")
        self.cmd("clock", "timezone", "Mars/Olympus", ok=False)
        self.assertFalse(self.cmd("clock", "ntp", "off")["ntp"])
        self.assertIn("UTC", self.cmd("clock", "zones")["zones"])

    def test_the_bars_clock(self):
        d = self.cmd("clock", "format", "12")
        self.assertEqual(d["bar"]["format_string"], "{:%I:%M:%S %p}")
        self.assertEqual(self.bar_format()["format"], "{:%I:%M:%S %p}")
        self.cmd("clock", "seconds", "off")
        d = self.cmd("clock", "date", "on")
        self.assertEqual(self.bar_format()["format"], "{:%a %d %b  %I:%M %p}")
        self.assertEqual((d["bar"]["format"], d["bar"]["seconds"], d["bar"]["date"]), ("12", False, True))
        self.assertIn(["-USR2", "-x", "-U", str(os.getuid()), "waybar"], self.calls("pkill"))
        d = self.cmd("clock", "reset")
        self.assertEqual(self.bar_format()["format"], "{:%H:%M:%S}")
        self.cmd("clock", "format", "36", ok=False)

    def test_hook_puts_the_include_first_and_nothing_else(self):
        cfg = self.path(".config", "waybar", "config")
        stock = ('{\n  // mine\n  "include": [\n    "/usr/share/bromigos/default/waybar/config.jsonc",\n'
                 '    "~/.local/state/bromigos/theme/current/waybar-markup.jsonc"\n  ]\n  , "output": ["DP-1"]\n}\n')
        with open(cfg, "w") as f:
            f.write(stock)
        self.assertEqual(self.cmd("clock")["bar"]["hook"], "missing")
        d = self.cmd("clock", "hook")
        self.assertTrue(d["bar"]["hooked"])
        self.assertEqual(self.read(".config", "waybar", "config"),
                         stock.replace('[\n    "/usr', '[\n    "~/.config/bromigos/waybar/settings.jsonc",\n    "/usr'))
        self.assertIsNotNone(self.read(*SETTINGS))
        # after the default: moved first
        with open(cfg, "w") as f:
            f.write(stock.replace('waybar-markup.jsonc"\n', 'waybar-markup.jsonc",\n    "~/.config/bromigos/waybar/settings.jsonc"\n'))
        self.assertEqual(self.cmd("clock")["bar"]["hook"], "after")
        self.assertTrue(self.cmd("clock", "hook")["bar"]["hooked"])
        text = self.read(".config", "waybar", "config")
        self.assertEqual(text.count("settings.jsonc"), 1)
        self.assertLess(text.index("settings.jsonc"), text.index("config.jsonc"))

    def test_hook_refuses_a_config_without_includes(self):
        with open(self.path(".config", "waybar", "config"), "w") as f:
            f.write('{ "modules-left": ["clock"] }\n')
        d = self.cmd("clock", "hook", ok=False)
        self.assertIn("settings.jsonc", d["error"])
        self.assertEqual(self.read(".config", "waybar", "config"), '{ "modules-left": ["clock"] }\n')

    def test_not_hooked_says_so(self):
        with open(self.path(".config", "waybar", "config"), "w") as f:
            f.write('{ "include": ["/usr/share/bromigos/default/waybar/config.jsonc"] }\n')
        d = self.cmd("clock", "date", "on")
        self.assertIn("bromigos clock hook", d["note"])
        d = self.cmd("clock", "hook")
        self.assertIn('"include": ["~/.config/bromigos/waybar/settings.jsonc", "/usr', self.read(".config", "waybar", "config"))


if __name__ == "__main__":
    unittest.main()
