"""`bromigos display` against the stand-ins (fixtures/bin/hyprctl: a Hyprland with a 27"
1440p DP-1 and a 24" 1080p HDMI-A-1; fixtures/bin/Hyprland: --verify-config). The block it
writes is `bromigos setup monitors`'s (core/crates/bromigos-core/src/setup.rs), the change
goes through the safe save, and a trial not kept reverts by itself."""
import json
import os
import shutil
import time
import unittest

from cmdtest import DESKTOP, CmdTest

USER_LUA = os.path.join(DESKTOP, "user", "hypr", "hyprland.lua")
SETUP_BLOCK = """-- >>> bromigos setup monitors (2026-10-01 09:00): this machine's outputs, left to right. Run it again to
-- change them, or edit here; an output not listed still lights up on its own.
bromigos.monitors = {
    { output = "DP-1", mode = "2560x1440@143.97", position = "0x0", scale = 1 },  -- LG Electronics LG ULTRAGEAR, 27" (597x336 mm)
    { output = "HDMI-A-1", mode = "1920x1080@60", position = "2560x0", scale = 1 },
}
-- <<< bromigos setup monitors
"""


class DisplayTest(CmdTest):
    def setUp(self):
        super().setUp()
        self.env["HYPRLAND_INSTANCE_SIGNATURE"] = "standin"
        os.makedirs(self.path(".config", "hypr"))
        shutil.copy(USER_LUA, self.path(".config", "hypr", "hyprland.lua"))
        self.original = self.read(".config", "hypr", "hyprland.lua")

    def tearDown(self):
        # a watchdog still waiting has nothing to revert once its trial is gone
        try:
            os.unlink(self.path(".local", "state", "bromigos", "display", "pending.json"))
        except FileNotFoundError:
            pass
        super().tearDown()

    def lua(self):
        return self.read(".config", "hypr", "hyprland.lua")

    def mon(self, doc, name):
        return next(o for o in doc["outputs"] if o["name"] == name)

    def wait_for(self, fn, timeout=8.0):
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            if fn():
                return True
            time.sleep(0.2)
        return fn()

    # ------------------------------------------------------------------ reading
    def test_status(self):
        d = self.cmd("display")
        self.assertTrue(d["running"])
        dp = self.mon(d, "DP-1")
        self.assertEqual((dp["mode"], dp["scale"], dp["x"], dp["enabled"]), ("2560x1440@143.97", 1.0, 0, True))
        self.assertEqual(dp["suggested_scale"], 1.0)                   # 27" 1440p: about 109 ppi
        self.assertEqual(dp["physical"]["inches"], 27.0)
        self.assertIn("1920x1080@60", [m["mode"] for m in dp["modes"]])
        self.assertEqual(dp["logical"], {"width": 2560, "height": 1440})
        self.assertTrue(dp["primary"])                                  # no monitors.toml: the focused one
        self.assertEqual(d["primary_from"], "focused")
        self.assertFalse(d["block"])
        self.assertFalse(d["trial"]["pending"])

    def test_reads_setup_monitors_block_and_primary(self):
        lua = self.original.replace('dofile("/usr/share', SETUP_BLOCK + '\ndofile("/usr/share', 1)
        with open(self.path(".config", "hypr", "hyprland.lua"), "w") as f:
            f.write(lua)
        os.makedirs(self.path(".config", "bromigos"))
        with open(self.path(".config", "bromigos", "monitors.toml"), "w") as f:
            f.write('primary = "HDMI-A-1"\n')
        d = self.cmd("display")
        self.assertTrue(d["block"])
        self.assertEqual([p["output"] for p in d["pinned"]], ["DP-1", "HDMI-A-1"])
        self.assertEqual(d["pinned"][1], {"output": "HDMI-A-1", "mode": "1920x1080@60", "position": "2560x0", "scale": 1})
        self.assertEqual(d["primary"], "HDMI-A-1")
        self.assertTrue(self.mon(d, "HDMI-A-1")["primary"])

    def test_without_hyprland(self):
        env = dict(self.env, BROMIGOS_FIXTURE_NO_HYPRLAND="1")
        del env["HYPRLAND_INSTANCE_SIGNATURE"]
        self.env = env
        d = self.cmd("display")
        self.assertFalse(d["running"])
        self.assertIn("Hyprland isn't running", d["error"])
        self.assertIn("isn't running", self.cmd("display", "apply", "--output", "DP-1", "--scale", "1.5",
                                                ok=False)["error"])

    # ------------------------------------------------------------------ writing
    def test_apply_writes_the_block_and_keep_ends_the_trial(self):
        d = self.cmd("display", "apply", "--output", "DP-1", "--mode", "1920x1080@60", "--scale", "1.25",
                     "--output", "HDMI-A-1", "--position", "1536x0", "--primary", "HDMI-A-1", "--confirm", "30")
        self.assertIn("keep them within 30 s", d["said"])
        self.assertTrue(d["trial"]["pending"])
        dp = self.mon(d, "DP-1")
        self.assertEqual((dp["mode"], dp["scale"]), ("1920x1080@60", 1.25))
        self.assertEqual(self.mon(d, "HDMI-A-1")["x"], 1536)
        lua = self.lua()
        # setup.rs's format: the begin line (with its stamp), the table, the end line, before the defaults
        b, e = lua.index("-- >>> bromigos setup monitors ("), lua.index("-- <<< bromigos setup monitors\n")
        self.assertLess(e, lua.index('dofile("/usr/share/bromigos/default/hypr/hyprland.lua")'))
        block = lua[b:e]
        self.assertIn('{ output = "DP-1", mode = "1920x1080@60", position = "0x0", scale = 1.25 },', block)
        self.assertIn('{ output = "HDMI-A-1", mode = "1920x1080@60", position = "1536x0", scale = 1 },', block)
        self.assertIn('-- LG Electronics LG ULTRAGEAR, 27" (597x336 mm)', block)
        self.assertEqual(lua.replace(lua[b:e + len("-- <<< bromigos setup monitors\n") + 1], ""), self.original)
        self.assertIn('primary = "HDMI-A-1"', self.read(".config", "bromigos", "monitors.toml"))
        # the safe save: auto-reload held around one reload, then as it was
        calls = [c[:2] for c in self.calls("hyprctl")]
        self.assertIn(["reload"], [c[:1] for c in calls])
        self.assertFalse(self.state("hyprctl")["options"]["misc:disable_autoreload"])
        d = self.cmd("display", "keep")
        self.assertFalse(d["trial"]["pending"])
        self.assertEqual(self.mon(d, "DP-1")["mode"], "1920x1080@60")

    def test_revert_puts_the_old_settings_back(self):
        lua = self.original.replace('dofile("/usr/share', SETUP_BLOCK + '\ndofile("/usr/share', 1)
        with open(self.path(".config", "hypr", "hyprland.lua"), "w") as f:
            f.write(lua)
        self.cmd("display", "apply", "--output", "HDMI-A-1", "--transform", "1", "--confirm", "60")
        self.assertIn("transform = 1", self.lua())
        self.assertEqual(self.mon(self.cmd("display"), "HDMI-A-1")["transform"], 1)
        # an apply during the trial keeps its starting point
        self.cmd("display", "apply", "--output", "DP-1", "--scale", "1.5", "--confirm", "60")
        d = self.cmd("display", "revert")
        self.assertEqual(d["said"], "Display settings reverted")
        self.assertEqual(self.lua(), lua)
        self.assertEqual(self.mon(d, "HDMI-A-1")["transform"], 0)
        self.assertEqual(self.mon(d, "DP-1")["scale"], 1.0)
        self.assertEqual(self.cmd("display", "revert")["said"], "Nothing to revert: no change is waiting")

    def test_the_watchdog_reverts_a_trial_not_kept(self):
        self.cmd("display", "apply", "--output", "DP-1", "--mode", "1280x720", "--confirm", "1")
        self.assertIn("1280x720", self.lua())
        self.assertTrue(self.wait_for(lambda: self.lua() == self.original), self.lua())
        d = self.cmd("display")
        self.assertFalse(d["trial"]["pending"])
        self.assertEqual(self.mon(d, "DP-1")["mode"], "2560x1440@143.97")     # the preferred mode again
        log = self.read(".local", "state", "bromigos", "display", "watchdog.log")
        self.assertIn("reverted: not kept in time", log)

    def test_kept_in_time_the_watchdog_leaves_it(self):
        self.cmd("display", "apply", "--output", "DP-1", "--scale", "1.25", "--confirm", "2")
        self.cmd("display", "keep")
        time.sleep(3)
        self.assertIn("scale = 1.25", self.lua())

    def test_reset_removes_the_block(self):
        self.cmd("display", "apply", "--output", "DP-1", "--scale", "1.5", "--confirm", "0")
        self.assertIn("-- >>> bromigos setup monitors", self.lua())
        d = self.cmd("display", "reset", "--confirm", "0")
        self.assertEqual(self.lua(), self.original)
        self.assertEqual(self.mon(d, "DP-1")["scale"], 1.0)
        self.assertIn("nothing pinned", self.cmd("display", "reset")["said"])

    def test_turning_an_output_off_and_on(self):
        d = self.cmd("display", "apply", "--output", "HDMI-A-1", "--off", "--confirm", "0")
        self.assertIn('{ output = "HDMI-A-1", disabled = true },', self.lua())
        self.assertFalse(self.mon(d, "HDMI-A-1")["enabled"])
        d = self.cmd("display", "apply", "--output", "HDMI-A-1", "--on", "--confirm", "0")
        self.assertTrue(self.mon(d, "HDMI-A-1")["enabled"])

    def test_refusals(self):
        def err(*args):
            return self.cmd("display", "apply", *args, ok=False)["error"]
        self.assertIn("no output 'DP-9'", err("--output", "DP-9", "--scale", "1"))
        self.assertIn("doesn't offer 3840x2160", err("--output", "DP-1", "--mode", "3840x2160@60"))
        self.assertIn("isn't WxH", err("--output", "DP-1", "--mode", "big"))
        self.assertIn("out of range", err("--output", "DP-1", "--scale", "5"))
        self.assertIn("transform is 0 to 7", err("--output", "DP-1", "--transform", "9"))
        self.assertIn("isn't XxY", err("--output", "DP-1", "--position", "left"))
        self.assertIn("one stays on", err("--output", "DP-1", "--off", "--output", "HDMI-A-1", "--off"))
        self.assertIn("must be on", err("--output", "HDMI-A-1", "--off", "--primary", "HDMI-A-1"))
        self.assertIn("nothing to change", err())
        self.assertIn("name the output first", err("--scale", "2"))
        self.assertEqual(self.lua(), self.original)

    def test_a_scale_hyprland_changes_is_put_back(self):
        d = self.cmd("display", "apply", "--output", "DP-1", "--scale", "1.3", ok=False,
                     env={"BROMIGOS_FIXTURE_ROUND_SCALE": "1"})
        self.assertIn("a scale has to divide the resolution evenly", d["error"])
        self.assertEqual(self.lua(), self.original)
        self.assertFalse(self.cmd("display")["trial"]["pending"])

    def test_a_config_hyprland_refuses_leaves_every_file(self):
        d = self.cmd("display", "apply", "--output", "DP-1", "--scale", "1.5", ok=False,
                     env={"BROMIGOS_FIXTURE_VERIFY_FAIL": "1"})
        self.assertIn("Hyprland didn't accept the new config", d["error"])
        self.assertEqual(self.lua(), self.original)
        self.assertIsNone(self.read(".config", "bromigos", "monitors.toml"))
        self.assertFalse(self.cmd("display")["trial"]["pending"])
        self.assertEqual(self.mon(self.cmd("display"), "DP-1")["scale"], 1.0)

    def test_a_symlinked_hyprland_lua_stays_a_symlink(self):
        real = os.path.join(self.tmp, "dotfiles-hyprland.lua")
        shutil.move(self.path(".config", "hypr", "hyprland.lua"), real)
        os.symlink(real, self.path(".config", "hypr", "hyprland.lua"))
        self.cmd("display", "apply", "--output", "DP-1", "--scale", "1.25", "--confirm", "0")
        self.assertTrue(os.path.islink(self.path(".config", "hypr", "hyprland.lua")))
        with open(real) as f:
            self.assertIn("scale = 1.25", f.read())

    def test_json_only_on_stdout(self):
        r = self.run_cmd("display", "apply", "--output", "DP-1", "--scale", "1.25", "--confirm", "0")
        json.loads(r.stdout)


if __name__ == "__main__":
    unittest.main()
