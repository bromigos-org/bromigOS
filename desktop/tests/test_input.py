"""`bromigos setup input` (desktop/bin/bromigos-setup-input): --json, --set, --unset, --reset
and --layouts, saved the safe way into a user's hyprland.lua (a stand-in Hyprland verifies;
no Hyprland runs, so it's saved for the next start), every file back when the verify fails."""
import os
import shutil
import tomllib
import unittest

from cmdtest import CmdTest, DESKTOP, FIXTURES

RULES = """! model
  pc105           Generic 105-key PC

! layout
  us              English (US)
  de              German
  fr              French

! variant
  dvorak          us: English (Dvorak)
  intl            us: English (US, intl., with dead keys)
  nodeadkeys      de: German (no dead keys)

! option
  grp                  Switching to another layout
  grp:alt_shift_toggle Alt+Shift
  grp:win_space_toggle Win+Space
  caps:escape          Make Caps Lock an additional Esc
  ctrl:nocaps          Caps Lock as Ctrl
"""


class InputTest(CmdTest):
    def setUp(self):
        super().setUp()
        self.lua = self.path(".config", "hypr", "hyprland.lua")
        os.makedirs(os.path.dirname(self.lua))
        shutil.copy(os.path.join(DESKTOP, "user", "hypr", "hyprland.lua"), self.lua)
        self.original = self.text(self.lua)
        stub = os.path.join(self.tmp, "stub")
        os.makedirs(stub)
        with open(os.path.join(stub, "Hyprland"), "w") as f:
            f.write('#!/bin/sh\n[ -n "$FAIL" ] && { echo "error: injected"; exit 1; }\necho "config ok"\n')
        os.chmod(os.path.join(stub, "Hyprland"), 0o755)
        rules = os.path.join(self.tmp, "evdev.lst")
        with open(rules, "w") as f:
            f.write(RULES)
        self.env.update(PATH=f"{stub}:{self.env['PATH']}", BROMIGOS_XKB_RULES=rules,
                        BROMIGOS_PROC=os.path.join(FIXTURES, "sysfs", "proc"))

    @staticmethod
    def text(path):
        with open(path) as f:
            return f.read()

    def toml(self):
        with open(self.path(".config", "bromigos", "input.toml"), "rb") as f:
            return tomllib.load(f)

    def test_json(self):
        d = self.cmd("setup-input")
        self.assertEqual(d["values"]["repeat_rate"], 50)
        self.assertIs(d["values"]["tap_to_click"], True)
        self.assertEqual(d["yours"], {})
        f = {x["key"]: x for x in d["fields"]}
        self.assertEqual(f["sensitivity"]["range"], [-1.0, 1.0])
        self.assertEqual(f["accel_profile"]["choices"], ["adaptive", "flat"])
        self.assertEqual(f["drag_lock"]["target"], "input.touchpad.drag_lock")
        self.assertEqual(d["touchpads"], ["SYNA8017:00 06CB:CE67 Touchpad"])

    def test_set_writes_the_block_and_the_file(self):
        d = self.cmd("setup-input", "--set", "kb_layout", "de", "--set", "repeat_rate", "35",
                     "--set", "drag_lock", "on", "--set", "accel_profile", "flat", "--set", "mouse_natural_scroll", "true")
        self.assertEqual(d["values"]["kb_layout"], "de")
        self.assertEqual(d["said"], "5 input settings saved")
        self.assertIn("next starts", d["applied"]["detail"])
        self.assertEqual(self.toml(), {"kb_layout": "de", "repeat_rate": 35, "accel_profile": "flat",
                                       "mouse_natural_scroll": True, "drag_lock": True})
        lua = self.text(self.lua)
        self.assertIn('bromigos.config.input.kb_layout = "de"', lua)
        self.assertIn("bromigos.config.input.natural_scroll = true", lua)          # the mouse's
        self.assertIn("bromigos.config.input.touchpad.drag_lock = true", lua)
        self.assertLess(lua.index("-- >>> bromigos setup input"), lua.index("dofile("))

    def test_one_change_says_what(self):
        d = self.cmd("setup-input", "--set", "repeat_delay", "300")
        self.assertEqual(d["said"], "Key repeat delay: 300")

    def test_refusals_change_nothing(self):
        for args in (["--set", "repeat_rate", "fast"], ["--set", "sensitivity", "3"], ["--set", "accel_profile", "wild"],
                     ["--set", "kb_layout", "us; rm"], ["--set", "nope", "1"], ["--unset", "nope"], ["--set", "kb_layout"]):
            self.cmd("setup-input", *args, ok=False)
        self.assertEqual(self.text(self.lua), self.original)
        self.assertFalse(os.path.exists(self.path(".config", "bromigos", "input.toml")))

    def test_a_failed_verify_puts_everything_back(self):
        self.cmd("setup-input", "--set", "kb_layout", "fr")
        before = self.text(self.lua)
        d = self.cmd("setup-input", "--set", "kb_layout", "de", ok=False, env={"FAIL": "1"})
        self.assertIn("not applied", d["error"])
        self.assertEqual(self.text(self.lua), before)
        self.assertEqual(self.toml(), {"kb_layout": "fr"})

    def test_unset_and_reset(self):
        self.cmd("setup-input", "--set", "kb_layout", "de", "--set", "left_handed", "true")
        d = self.cmd("setup-input", "--unset", "left_handed")
        self.assertEqual(d["yours"], {"kb_layout": "de"})
        d = self.cmd("setup-input", "--reset")
        self.assertEqual(d["yours"], {})
        self.assertFalse(os.path.exists(self.path(".config", "bromigos", "input.toml")))
        self.assertNotIn("bromigos setup input", self.text(self.lua))

    def test_show_keeps_working(self):
        self.cmd("setup-input", "--set", "kb_variant", "dvorak")
        import subprocess
        r = subprocess.run([os.path.join(DESKTOP, "bin", "bromigos-setup-input"), "--show"], env=self.env,
                           capture_output=True, text=True)
        self.assertEqual(r.stdout, "kb_variant = dvorak\n")

    def test_layouts(self):
        d = self.cmd("setup-input", "--layouts")
        lays = {x["code"]: x for x in d["layouts"]}
        self.assertEqual([v["code"] for v in lays["us"]["variants"]], ["dvorak", "intl"])
        self.assertEqual(lays["de"]["variants"][0]["name"], "German (no dead keys)")
        self.assertEqual([x["code"] for x in d["switch_keys"]], ["grp:alt_shift_toggle", "grp:win_space_toggle"])
        self.assertEqual([x["code"] for x in d["caps"]], ["caps:escape", "ctrl:nocaps"])


if __name__ == "__main__":
    unittest.main()
