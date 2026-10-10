"""`bromigos bluetooth` against the stand-in bluetoothctl and rfkill (fixtures/bin: one adapter,
three paired devices, two more nearby: one pairs as "just works", one asks for a passkey)."""
import json
import os
import unittest

from cmdtest import CmdTest


class BluetoothTest(CmdTest):
    def set_state(self, fn):
        st = self.state("bluetoothctl")
        fn(st)
        with open(os.path.join(self.fx, "bluetoothctl.json"), "w") as f:
            json.dump(st, f)

    def test_status(self):
        d = self.cmd("bluetooth")
        self.assertEqual(d["adapter"]["alias"], "workstation")
        self.assertTrue(d["powered"])
        self.assertFalse(d["discoverable"] or d["blocked"])
        head = d["devices"][0]
        self.assertEqual((head["name"], head["kind"], head["connected"], head["battery"]), ("WH-1000XM5", "headset", True, 70))
        self.assertEqual([x["name"] for x in d["paired"]], ["WH-1000XM5", "MX Master 3S", "Xbox Wireless Controller"])
        self.assertIsNone(next(x for x in d["devices"] if x["kind"] == "game controller")["battery"])
        self.assertEqual(d["nearby"], [])

    def test_power_and_discoverable(self):
        d = self.cmd("bluetooth", "power", "off")
        self.assertFalse(d["powered"])
        self.assertFalse(any(x["connected"] for x in d["devices"]))
        self.cmd("bluetooth", "discoverable", "on", ok=False)        # off: refused
        self.assertTrue(self.cmd("bluetooth", "power", "on")["powered"])
        self.assertTrue(self.cmd("bluetooth", "discoverable", "on")["discoverable"])

    def test_a_soft_block_is_lifted_a_hard_one_isnt(self):
        self.set_state(lambda st: (st["rfkill"].update(soft=True), st["adapter"].update(powered=False)))
        self.assertTrue(self.cmd("bluetooth")["blocked"])
        d = self.cmd("bluetooth", "power", "on")
        self.assertTrue(d["powered"])
        self.assertIn(["unblock", "bluetooth"], self.calls("rfkill"))
        self.set_state(lambda st: (st["rfkill"].update(hard=True), st["adapter"].update(powered=False)))
        self.assertIn("hardware switch", self.cmd("bluetooth", "power", "on", ok=False)["error"])

    def test_scan_and_pair(self):
        d = self.cmd("bluetooth", "scan", "2")
        self.assertEqual([x["name"] for x in d["nearby"]], ["JBL Flip 6", "Pixel 9"])
        self.assertIn(["--timeout", "2", "scan", "on"], self.calls("bluetoothctl"))
        d = self.cmd("bluetooth", "pair", "00:00:5E:00:53:20")
        jbl = next(x for x in d["devices"] if x["name"] == "JBL Flip 6")
        self.assertTrue(jbl["paired"] and jbl["trusted"] and jbl["connected"])
        d = self.cmd("bluetooth", "pair", "00:00:5e:00:53:21", ok=False)
        self.assertTrue(d["needs_agent"])
        self.assertIn("passkey", d["error"])
        self.cmd("bluetooth", "scan", "600", ok=False)

    def test_connect_trust_remove(self):
        d = self.cmd("bluetooth", "connect", "00:00:5E:00:53:11")
        self.assertTrue(next(x for x in d["devices"] if x["name"] == "MX Master 3S")["connected"])
        d = self.cmd("bluetooth", "disconnect", "00:00:5E:00:53:11")
        self.assertFalse(next(x for x in d["devices"] if x["name"] == "MX Master 3S")["connected"])
        d = self.cmd("bluetooth", "trust", "00:00:5E:00:53:12", "on")
        self.assertTrue(next(x for x in d["devices"] if x["mac"] == "00:00:5E:00:53:12")["trusted"])
        d = self.cmd("bluetooth", "remove", "00:00:5E:00:53:12")
        self.assertNotIn("00:00:5E:00:53:12", [x["mac"] for x in d["devices"]])
        self.cmd("bluetooth", "connect", "not-a-mac", ok=False)
        self.cmd("bluetooth", "connect", "00:00:5E:00:53:FE", ok=False)

    def test_no_adapter(self):
        self.set_state(lambda st: st.update(adapter=None))
        d = self.cmd("bluetooth")
        self.assertIsNone(d["adapter"])
        self.assertIn("no Bluetooth adapter", self.cmd("bluetooth", "power", "on", ok=False)["error"])

    def test_no_bluetoothd(self):
        self.set_state(lambda st: st.update(running=False))
        self.assertIn("bluetoothd", self.cmd("bluetooth", ok=False)["error"])


if __name__ == "__main__":
    unittest.main()
