"""Proxmox and Netdata adapters against recorded API answers (tests/fixtures/*.json).

    PYTHONPATH=lib python -m unittest discover -s tests
"""
import json
import os
import unittest
import urllib.parse
from unittest import mock

from bromigos_homelab import caps
from bromigos_homelab.adapters.infra import Netdata, Proxmox

HERE = os.path.dirname(os.path.abspath(__file__))


def fixture(name):
    with open(os.path.join(HERE, "fixtures", name)) as f:
        return json.load(f)


class ProxmoxTest(unittest.TestCase):
    def setUp(self):
        self.fx = fixture("proxmox.json")
        self.a = Proxmox({"name": "proxmox", "type": "proxmox", "endpoint": "https://pve:8006"})
        self.a.get_json = lambda path, timeout=8, **kw: self.fx[path]

    def test_hosts(self):
        (h,) = self.a.hosts()
        self.assertEqual(h["name"], "pve")
        self.assertTrue(h["up"])
        self.assertEqual(h["cores"], 32)
        self.assertAlmostEqual(h["cpu_pct"], 6.2)
        self.assertAlmostEqual(h["mem_pct"], 87.5)
        self.assertAlmostEqual(h["disk_pct"], 20.7)

    def test_workloads(self):
        w = {x["name"]: x for x in self.a.workloads()}
        self.assertEqual(w["vm-alpha"]["kind"], "vm")
        self.assertEqual(w["vm-alpha"]["state"], "running")
        self.assertEqual(w["vm-alpha"]["node"], "pve")
        self.assertEqual(w["pihole"]["kind"], "container")
        self.assertEqual(w["pihole"]["state"], "stopped")
        self.assertEqual(w["pihole"]["namespace"], "net")

    def test_probe(self):
        self.assertTrue(self.a.probe())

    def test_token_header(self):
        a = Proxmox({"name": "p", "type": "proxmox", "endpoint": "https://pve:8006", "auth_ref": "@env:T"})
        with mock.patch.dict(os.environ, {"T": "reader@pve!bromigos=0000-1111"}):
            self.assertEqual(a.auth_headers(), {"Authorization": "PVEAPIToken=reader@pve!bromigos=0000-1111"})

    def test_schema(self):
        rec = caps._norm("hosts", self.a.hosts()[0], "proxmox")
        self.assertEqual(list(rec)[:7], list(caps.SCHEMAS["hosts"]))


class NetdataTest(unittest.TestCase):
    def setUp(self):
        self.fx = fixture("netdata.json")
        self.a = Netdata({"name": "netdata", "type": "netdata", "endpoint": "http://nas:19999"})

        def get_json(path, timeout=8, **kw):
            if path.startswith("/api/v1/data?"):
                chart = urllib.parse.parse_qs(path.split("?", 1)[1])["chart"][0]
                return self.fx[chart]
            return self.fx[path]
        self.a.get_json = get_json

    def test_hosts(self):
        (h,) = self.a.hosts()
        self.assertEqual(h["name"], "nas")
        self.assertAlmostEqual(h["cpu_pct"], 17.0)
        self.assertAlmostEqual(h["mem_pct"], 38.4)   # 12288 of 32000 MiB
        self.assertAlmostEqual(h["disk_pct"], 35.0)
        self.assertEqual(h["load1"], 0.82)
        self.assertEqual(h["cores"], 8)

    def test_metrics_dimension(self):
        (r,) = self.a.metrics_query("system.ram.used")
        self.assertEqual(r["labels"], {"chart": "system.ram", "dimension": "used"})
        self.assertEqual(r["value"], 12288.0)

    def test_metrics_chart(self):
        rs = self.a.metrics_query("system.load")
        self.assertEqual([r["labels"]["dimension"] for r in rs], ["load1", "load5", "load15"])

    def test_probe(self):
        self.assertTrue(self.a.probe())


if __name__ == "__main__":
    unittest.main()
