"""`bromigos notifications` against the stand-ins (fixtures/bin/dunstctl and notify-send: a
dunst with five notifications in its history)."""
import os
import unittest

from cmdtest import CmdTest

DROPIN = (".config", "dunst", "dunstrc.d", "80-settings.conf")


class NotificationsTest(CmdTest):
    def test_status(self):
        d = self.cmd("notifications")
        self.assertTrue(d["running"])
        self.assertFalse(d["dnd"])
        self.assertEqual(d["counts"], {"waiting": 0, "displayed": 1, "history": 5})
        self.assertEqual((d["position"], d["offset"]), ("top-right", [16, 16]))
        self.assertEqual(d["timeout"], {"low": 5, "normal": 8, "critical": 0})
        self.assertEqual([(a["name"], a["count"], a["rule"]) for a in d["apps"]][:2], [("Spotify", 2, "show"), ("Firefox", 1, "show")])
        self.assertIsNone(self.read(*DROPIN))

    def test_dnd(self):
        self.assertTrue(self.cmd("notifications", "dnd", "on")["dnd"])
        self.assertFalse(self.cmd("notifications", "dnd", "toggle")["dnd"])
        self.assertIn(["set-paused", "true"], self.calls("dunstctl"))
        self.cmd("notifications", "dnd", "maybe", ok=False)

    def test_settings_go_in_the_dropin_and_reload(self):
        self.cmd("notifications", "position", "bottom-left")
        self.cmd("notifications", "timeout", "normal", "12")
        self.cmd("notifications", "timeout", "critical", "0")          # the default: not written
        d = self.cmd("notifications", "offset", "20", "40")
        self.assertEqual((d["position"], d["offset"], d["timeout"]["normal"]), ("bottom-left", [20, 40], 12))
        text = self.read(*DROPIN)
        self.assertIn("[global]\n    origin = bottom-left\n    offset = (20, 40)", text)
        self.assertIn("[urgency_normal]\n    timeout = 12", text)
        self.assertNotIn("urgency_critical", text)
        self.assertEqual(self.state("dunstctl")["reloads"], 4)
        self.cmd("notifications", "position", "middle", ok=False)
        self.cmd("notifications", "timeout", "normal", "-3", ok=False)
        self.cmd("notifications", "timeout", "urgent", "3", ok=False)

    def test_app_rules(self):
        self.cmd("notifications", "app", "Spotify", "quiet")
        d = self.cmd("notifications", "app", "discord", "hide")
        rules = {a["name"]: a["rule"] for a in d["apps"]}
        self.assertEqual((rules["Spotify"], rules["discord"], rules["Firefox"]), ("quiet", "hide", "show"))
        text = self.read(*DROPIN)
        self.assertIn('[bromigos_app_spotify]\n    appname = "Spotify"\n    urgency = low', text)
        self.assertIn('[bromigos_app_discord]\n    appname = "discord"\n    skip_display = true', text)
        d = self.cmd("notifications", "app", "Spotify", "show")
        self.assertNotIn("Spotify", self.read(*DROPIN))
        self.cmd("notifications", "app", "Spotify", "loud", ok=False)
        # a rule for an app not in the history is still listed
        d = self.cmd("notifications", "app", "Steam", "quiet")
        self.assertIn(("Steam", "quiet"), [(a["name"], a["rule"]) for a in d["apps"]])

    def test_globs_in_a_name_match_only_themselves(self):
        self.cmd("notifications", "app", "weird*app", "hide")
        self.assertIn('appname = "weird?app"', self.read(*DROPIN))

    def test_reset_removes_the_dropin(self):
        self.cmd("notifications", "position", "top-left")
        d = self.cmd("notifications", "reset")
        self.assertIsNone(self.read(*DROPIN))
        self.assertEqual(d["position"], "top-right")

    def test_history_and_test(self):
        d = self.cmd("notifications", "test")
        self.assertEqual(d["counts"]["history"], 6)
        self.assertEqual(self.calls("notify-send")[0][:3], ["-a", "Settings", "-u"])
        self.assertEqual(self.cmd("notifications", "clear-history")["counts"]["history"], 0)

    def test_dunst_not_running(self):
        import json
        st = self.state("dunstctl")
        st["running"] = False
        with open(os.path.join(self.fx, "dunstctl.json"), "w") as f:
            json.dump(st, f)
        d = self.cmd("notifications")
        self.assertFalse(d["running"])
        d = self.cmd("notifications", "position", "bottom-right")
        self.assertIn("isn't running", d["note"])
        self.cmd("notifications", "dnd", "on", ok=False)


if __name__ == "__main__":
    unittest.main()
