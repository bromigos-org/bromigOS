"""`bromigos power` against a laptop that isn't there: a fake /sys and /proc
(fixtures/sysfs: a battery, the charger, a mouse's battery, a lid), the stand-in
powerprofilesctl, logind's files in a temp /etc, and a pkexec that refuses."""
import os
import unittest

from cmdtest import CmdTest, FIXTURES


class PowerTest(CmdTest):
    def setUp(self):
        super().setUp()
        self.etc = os.path.join(self.tmp, "etc")
        self.usrlib = os.path.join(self.tmp, "usrlib")
        os.makedirs(os.path.join(self.etc, "systemd"))
        os.makedirs(os.path.join(self.usrlib, "systemd"))
        self.env.update(BROMIGOS_SYSFS=os.path.join(FIXTURES, "sysfs", "sys"),
                        BROMIGOS_PROC=os.path.join(FIXTURES, "sysfs", "proc"),
                        BROMIGOS_ETC=self.etc, BROMIGOS_USRLIB=self.usrlib)

    def dropin(self):
        with open(os.path.join(self.etc, "systemd", "logind.conf.d", "50-bromigos-lid.conf")) as f:
            return f.read()

    def logind(self, text, where="etc", name=None):
        d = os.path.join(self.etc if where == "etc" else self.usrlib, "systemd")
        if name:
            d = os.path.join(d, "logind.conf.d")
            os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, name or "logind.conf"), "w") as f:
            f.write(text)

    def test_status(self):
        d = self.cmd("power")
        p = d["profiles"]
        self.assertTrue(p["available"])
        self.assertEqual((p["active"], [x["name"] for x in p["list"]]), ("balanced", ["performance", "balanced", "power-saver"]))
        b = d["batteries"][0]
        self.assertEqual((b["capacity"], b["status"], b["health"], b["time_left_min"], b["cycles"]),
                         (72, "Discharging", 95, 259, 211))
        self.assertEqual([x["model"] for x in d["devices"]], ["MX Master 3S"])
        self.assertEqual(d["ac"], {"present": True, "online": False, "name": "AC"})
        self.assertTrue(d["laptop"])
        lid = d["lid"]
        self.assertEqual((lid["present"], lid["state"], lid["on_battery"], lid["on_power"], lid["docked"]),
                         (True, "open", "suspend", "suspend", "ignore"))
        self.assertTrue(d["hibernation"]["possible"])

    def test_logind_files_in_order(self):
        self.logind("[Login]\n#HandleLidSwitch=suspend\nHandleLidSwitch=lock\n")
        self.logind("[Login]\nHandleLidSwitchExternalPower=ignore\n", "usrlib", "10-vendor.conf")
        self.logind("[Login]\nHandleLidSwitchExternalPower=poweroff\n", "etc", "10-vendor.conf")   # /etc's of a name wins
        lid = self.cmd("power")["lid"]
        self.assertEqual((lid["on_battery"], lid["on_power"]), ("lock", "poweroff"))

    def test_a_desktop(self):
        empty = os.path.join(self.tmp, "nosys")
        os.makedirs(empty)
        d = self.cmd("power", env={"BROMIGOS_SYSFS": empty, "BROMIGOS_PROC": empty})
        self.assertEqual((d["batteries"], d["lid"]["present"], d["laptop"]), ([], False, False))

    def test_profile(self):
        self.assertEqual(self.cmd("power", "profile", "power-saver")["profiles"]["active"], "power-saver")
        self.assertIn("one of", self.cmd("power", "profile", "turbo", ok=False)["error"])

    def test_no_daemon(self):
        import json
        st = self.state("powerprofilesctl")
        st["running"] = False
        with open(os.path.join(self.fx, "powerprofilesctl.json"), "w") as f:
            json.dump(st, f)
        p = self.cmd("power")["profiles"]
        self.assertFalse(p["available"])
        self.assertIn("isn't running", p["why"])
        self.cmd("power", "profile", "balanced", ok=False)

    def test_lid_written_where_it_may(self):
        d = self.cmd("power", "lid", "lock", "--on-power", "ignore")
        text = self.dropin()
        self.assertIn("[Login]\nHandleLidSwitch=lock\nHandleLidSwitchExternalPower=ignore\n", text)
        self.assertEqual((d["lid"]["on_battery"], d["lid"]["on_power"], d["lid"]["docked"]), ("lock", "ignore", "ignore"))
        # a later change keeps what it isn't given
        self.cmd("power", "lid", "suspend", "--docked", "suspend")
        text = self.dropin()
        self.assertIn("HandleLidSwitchExternalPower=ignore", text)
        self.assertIn("HandleLidSwitchDocked=suspend", text)
        self.assertEqual(self.calls("pkexec"), [])

    def test_lid_print_writes_nothing(self):
        d = self.cmd("power", "lid", "poweroff", "--print")
        self.assertIn("HandleLidSwitch=poweroff", d["text"])
        self.assertFalse(os.path.exists(os.path.join(self.etc, "systemd", "logind.conf.d")))

    def test_lid_elsewhere_asks_through_pkexec(self):
        os.chmod(os.path.join(self.etc, "systemd"), 0o555)
        try:
            d = self.cmd("power", "lid", "lock", ok=False)
        finally:
            os.chmod(os.path.join(self.etc, "systemd"), 0o755)
        self.assertIn("password prompt", d["error"])
        call = self.calls("pkexec")[0]
        self.assertTrue(call[0].endswith("bromigos-power"))
        self.assertEqual(call[1:], ["lid", "lock", "--json"])

    def test_lid_refusals(self):
        self.cmd("power", "lid", "explode", ok=False)
        self.cmd("power", "lid", "lock", "--on-power", "dance", ok=False)
        self.cmd("power", "lid", ok=False)


if __name__ == "__main__":
    unittest.main()
