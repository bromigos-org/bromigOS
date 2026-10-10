"""`bromigos net` against the stand-in nmcli (fixtures/bin/nmcli: NetworkManager with a Wi-Fi card,
an ethernet port, two saved networks, a VPN and a WireGuard tunnel)."""
import json
import os
import subprocess
import unittest

from cmdtest import DESKTOP, CmdTest


class NetTest(CmdTest):
    def connect(self, ssid, password=None, *extra, ok=True):
        argv = [os.path.join(DESKTOP, "bin", "bromigos-net"), "connect", ssid, *extra, "--json"]
        if password is not None:
            argv.insert(-1, "--password-stdin")
        r = subprocess.run(argv, env=self.env, input=(password + "\n") if password is not None else None,
                           capture_output=True, text=True, timeout=60)
        doc = json.loads(r.stdout)
        self.assertEqual(doc.get("ok"), ok, doc)
        return doc

    def test_status(self):
        d = self.cmd("net")
        self.assertTrue(d["running"])
        self.assertEqual((d["state"], d["connectivity"]), ("connected", "full"))
        self.assertTrue(d["wifi"]["enabled"])
        nets = {n["ssid"]: n for n in d["wifi"]["networks"]}
        self.assertTrue(nets["Greywater Light"]["in_use"] and nets["Greywater Light"]["saved"])
        self.assertEqual(nets["Greywater Light"]["signal"], 82)             # the strongest of its two access points
        self.assertEqual(nets["Greywater Light"]["bssid"], "00:00:5E:00:53:40")   # '\:' unescaped
        self.assertIn("Station:Nine", nets)                                # a ':' in an SSID
        self.assertFalse(nets["Low Note Cafe"]["secured"])
        self.assertTrue(nets["Kite Works"]["enterprise"])
        self.assertNotIn("", nets)                                        # a hidden network isn't listed
        self.assertEqual(len(d["wifi"]["networks"]), 5)
        wlan = next(x for x in d["devices"] if x["name"] == "wlan0")
        self.assertEqual((wlan["ip4"], wlan["gateway"], wlan["dns"]),
                         (["192.0.2.41/24"], "192.0.2.1", ["192.0.2.1", "1.1.1.1"]))
        self.assertEqual(wlan["hwaddr"], "00:00:5E:00:53:30")
        self.assertEqual([x["name"] for x in d["wired"]], ["enp5s0"])
        self.assertEqual([(v["name"], v["type"]) for v in d["vpns"]], [("office", "vpn"), ("wg-station-nine", "wireguard")])
        self.assertNotIn("lo", [c["name"] for c in d["connections"]])
        self.assertIsNone(d["panel"])                                      # no `bromigos panels` here

    def test_wifi_radio(self):
        d = self.cmd("net", "wifi", "off")
        self.assertFalse(d["wifi"]["enabled"])
        self.assertEqual(d["wifi"]["networks"], [])
        self.assertEqual(self.calls("nmcli")[0], ["radio", "wifi", "off"])
        self.assertTrue(self.cmd("net", "wifi", "on")["wifi"]["enabled"])
        self.cmd("net", "wifi", "maybe", ok=False)

    def test_a_new_secured_network_the_password_never_on_argv(self):
        d = self.connect("Station:Nine", "aurora-dish")
        self.assertEqual(d["said"], "Connected to Station:Nine")
        net = next(n for n in d["wifi"]["networks"] if n["ssid"] == "Station:Nine")
        self.assertTrue(net["in_use"] and net["saved"])
        calls = self.calls("nmcli")
        self.assertFalse(any("aurora-dish" in " ".join(c) for c in calls), calls)
        add = next(c for c in calls if c[:2] == ["connection", "add"])
        self.assertEqual(add[add.index("wifi-sec.key-mgmt") + 1], "wpa-psk")        # WPA2/WPA3 transition
        up = next(c for c in calls if c[:2] == ["connection", "up"] and "passwd-file" in c)
        pf = up[up.index("passwd-file") + 1]
        self.assertFalse(os.path.exists(pf))                                     # removed after
        self.assertFalse(os.path.exists(os.path.dirname(pf)))
        self.assertEqual(next(c for c in self.state("nmcli")["connections"] if c.get("ssid") == "Station:Nine")["psk"],
                         "aurora-dish")

    def test_wpa3_only_uses_sae(self):
        self.connect("Debtor's Wake", "red-sky")
        add = next(c for c in self.calls("nmcli") if c[:2] == ["connection", "add"])
        self.assertEqual(add[add.index("wifi-sec.key-mgmt") + 1], "sae")

    def test_a_wrong_password_leaves_nothing_saved(self):
        d = self.connect("Station:Nine", "wrong", ok=False)
        self.assertIn("couldn't join Station:Nine", d["error"])
        self.assertFalse(any(c.get("ssid") == "Station:Nine" for c in self.state("nmcli")["connections"]))
        up = next(c for c in self.calls("nmcli") if "passwd-file" in c)
        self.assertFalse(os.path.exists(up[up.index("passwd-file") + 1]))             # removed after a failure too

    def test_saved_and_open_networks_need_no_password(self):
        d = self.connect("Low Note Cafe")
        self.assertTrue(next(n for n in d["wifi"]["networks"] if n["ssid"] == "Low Note Cafe")["in_use"])
        self.assertIn(["connection", "up", "uuid", "6f1c3e7a-1b2d-4c5e-9f00-0a1b2c3d4e02"], self.calls("nmcli"))
        self.connect("Station:Nine", ok=False)                                # secured, new, no password
        self.connect("Kite Works", "x", ok=False)                             # enterprise: refused here
        self.connect("Nowhere", "x", ok=False)
        d = self.connect("Hidden Pier", "pier-pass", "--hidden")
        self.assertIn("Hidden Pier", [c["name"] for c in d["saved_wifi"]])

    def test_disconnect_forget_up_down_autoconnect(self):
        d = self.cmd("net", "disconnect", "wlan0")
        self.assertEqual(next(x for x in d["devices"] if x["name"] == "wlan0")["state"], "disconnected")
        d = self.cmd("net", "forget", "Greywater Light")
        self.assertNotIn("Greywater Light", [c["name"] for c in d["connections"]])
        d = self.cmd("net", "up", "wg-station-nine")
        self.assertTrue(next(v for v in d["vpns"] if v["name"] == "wg-station-nine")["active"])
        d = self.cmd("net", "down", "6f1c3e7a-1b2d-4c5e-9f00-0a1b2c3d4e05")
        self.assertFalse(next(v for v in d["vpns"] if v["name"] == "wg-station-nine")["active"])
        d = self.cmd("net", "autoconnect", "Low Note Cafe", "on")
        self.assertTrue(next(c for c in d["connections"] if c["name"] == "Low Note Cafe")["autoconnect"])
        self.cmd("net", "forget", "nope", ok=False)
        self.cmd("net", "disconnect", "eth9", ok=False)

    def test_panel_without_bromigos_panels(self):
        d = self.cmd("net", "panel", "on", ok=False)
        self.assertIn("CONNECTIONS panel", d["error"])

    def test_panel_through_bromigos_panels(self):
        bindir = os.path.join(self.tmp, "bin")
        os.makedirs(bindir)
        log = os.path.join(self.tmp, "panels.log")
        with open(os.path.join(bindir, "bromigos-panels"), "w") as f:
            f.write(f'#!/bin/sh\necho "$*" >> {log}\n'
                    'echo \'{"schema": 1, "ok": true, "panels": [{"name": "connections", "visible": true}]}\'\n')
        os.chmod(os.path.join(bindir, "bromigos-panels"), 0o755)
        d = self.cmd("net", "panel", "on", env={"PATH": f"{bindir}:{self.env['PATH']}"})
        self.assertTrue(d["panel"])
        with open(log) as f:
            self.assertIn("show connections --json", f.read())

    def test_without_networkmanager(self):
        st = self.state("nmcli")
        st["running"] = False
        with open(os.path.join(self.fx, "nmcli.json"), "w") as f:
            json.dump(st, f)
        self.assertIn("NetworkManager isn't running", self.cmd("net", ok=False)["error"])


if __name__ == "__main__":
    unittest.main()
