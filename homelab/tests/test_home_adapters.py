"""The energy and games adapters behind the SOLAR and GAME SERVERS widgets, and the alerts'
links behind ALERTS: Enphase's gateway (both firmware shapes, its token, the old API),
Minecraft's Server List Ping against a fake server on a local port, and each alert's page.

    PYTHONPATH=lib python -m unittest discover -s tests
"""
import json
import os
import socket
import struct
import threading
import unittest
import urllib.error
from unittest import mock

import bromigos_homelab as H
from bromigos_homelab import caps, registry
from bromigos_homelab.adapters import labenergy as E
from bromigos_homelab.adapters import labgames as G
from bromigos_homelab.adapters import prometheus as P

FIX = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures")


def fixture(name):
    with open(os.path.join(FIX, name)) as f:
        return json.load(f)


class Capability(unittest.TestCase):
    def test_energy_is_a_capability_with_its_record(self):
        self.assertIn("energy", registry.CAPABILITIES)
        self.assertIn("production_w", caps.SCHEMAS["energy"])
        self.assertIn("link", caps.SCHEMAS["alerts"])
        self.assertIn("enphase", registry.ADAPTERS)
        self.assertIn("minecraft", registry.ADAPTERS)

    def test_nothing_configured_is_empty(self):
        with mock.patch.object(registry, "providers", lambda cap: []):
            self.assertEqual(H.energy(), {"ok": False, "items": [], "errors": {}, "sources": []})


class Enphase(unittest.TestCase):
    def test_metered_gateway(self):
        r = E.energy_from_production(fixture("enphase-production-metered.json"), "roof")
        self.assertEqual((r["name"], r["kind"], r["state"]), ("roof", "solar", "ok"))
        self.assertAlmostEqual(r["production_w"], 4180.4)        # the meter, not the inverters' estimate
        self.assertAlmostEqual(r["consumption_w"], 1240.2)
        self.assertAlmostEqual(r["net_w"], -2940.2)              # exporting
        self.assertAlmostEqual(r["today_wh"], 23400.7)
        self.assertAlmostEqual(r["consumed_today_wh"], 11800.1)
        self.assertEqual((r["battery_pct"], r["battery_w"], r["inverters"]), (72.0, -650.0, 18))
        self.assertTrue(r["metered"])

    def test_inverters_only(self):
        r = E.energy_from_production(fixture("enphase-production-inverters.json"))
        self.assertEqual(r["production_w"], 2310.0)
        self.assertIsNone(r["consumption_w"])
        self.assertIsNone(r["net_w"])
        self.assertIsNone(r["battery_pct"])                       # a battery entry that reports nothing
        self.assertFalse(r["metered"])

    def test_net_only_derives_consumption(self):
        d = fixture("enphase-production-metered.json")
        d["consumption"] = [c for c in d["consumption"] if c["measurementType"] == "net-consumption"]
        r = E.energy_from_production(d)
        self.assertAlmostEqual(r["consumption_w"], 4180.4 - 2940.2)

    def test_old_api(self):
        r = E.energy_from_v1(fixture("enphase-api-v1-production.json"))
        self.assertEqual((r["production_w"], r["today_wh"]), (2310.0, 15123.0))
        self.assertIsNone(E.energy_from_v1({"nothing": 1}))

    def _adapter(self, answers, **opts):
        a = E.Enphase(dict({"type": "enphase", "name": "roof", "endpoint": "https://envoy.example"}, **opts))

        def get_json(path, timeout=8, **kw):
            v = answers[path.split("?")[0]]
            if isinstance(v, Exception):
                raise v
            return v
        a.get_json = get_json
        return a

    def test_adapter_reads_production_json(self):
        a = self._adapter({"/production.json": fixture("enphase-production-metered.json")}, history_metric="solar_w")
        r, = a.energy()
        self.assertEqual(r["history_metric"], "solar_w")
        self.assertEqual(a.doctor()[0]["status"], "ok")

    def test_adapter_falls_back_to_the_old_api(self):
        e404 = urllib.error.HTTPError("https://envoy.example/production.json", 404, "Not Found", {}, None)
        a = self._adapter({"/production.json": e404, "/api/v1/production": fixture("enphase-api-v1-production.json")})
        self.assertEqual(a.energy()[0]["production_w"], 2310.0)

    def test_adapter_says_a_token_is_needed(self):
        e401 = urllib.error.HTTPError("https://envoy.example/production.json", 401, "Unauthorized", {}, None)
        a = self._adapter({"/production.json": e401})
        with self.assertRaises(registry.Unreachable) as c:
            a.energy()
        self.assertIn("token", str(c.exception))
        self.assertEqual(a.doctor()[0]["status"], "fail")


class FakeMinecraft(threading.Thread):
    """A server that answers one Server List Ping (handshake, status, ping) per connection."""

    def __init__(self, status):
        super().__init__(daemon=True)
        self.status = status
        self.sock = socket.socket()
        self.sock.bind(("127.0.0.1", 0))
        self.sock.listen(4)
        self.port = self.sock.getsockname()[1]
        self.handshakes = []

    def run(self):
        while True:
            try:
                c, _ = self.sock.accept()
            except OSError:
                return
            with c:
                try:
                    self.serve(c)
                except (OSError, ValueError):
                    pass

    @staticmethod
    def packet(c):
        n = G._read_varint(c)
        return G._recv_exact(c, n)

    def serve(self, c):
        hs = self.packet(c)
        self.handshakes.append(hs)
        self.packet(c)                                    # the status request
        body = json.dumps(self.status).encode()
        c.sendall(G._packet(0, G._varint(len(body)) + body))
        ping = self.packet(c)
        c.sendall(G._packet(1, ping[1:]))

    def close(self):
        self.sock.close()


class Minecraft(unittest.TestCase):
    STATUS = {"version": {"name": "1.21.4", "protocol": 769},
              "players": {"max": 20, "online": 3, "sample": [{"name": "lamplighter", "id": "0"},
                                                             {"name": "Tidewatch", "id": "1"},
                                                             {"name": "§7and 1 more", "id": "2"}]},
              "description": {"text": "Harbor ", "extra": [{"text": "§aPoint"}, {"text": " survival"}]}}

    def setUp(self):
        self.srv = FakeMinecraft(self.STATUS)
        self.srv.start()

    def tearDown(self):
        self.srv.close()

    def test_server_list_ping(self):
        st, ms = G.slp("127.0.0.1", self.srv.port, timeout=3)
        self.assertEqual(st["players"]["online"], 3)
        self.assertIsNotNone(ms)
        hs = self.srv.handshakes[0]
        self.assertEqual(hs[0], 0)                       # the handshake's packet id
        self.assertEqual(hs[-1], 1)                      # next state: status
        self.assertIn(struct.pack(">H", self.srv.port), hs)

    def test_adapter_record(self):
        a = G.Minecraft({"type": "minecraft", "name": "survival", "endpoint": f"minecraft://127.0.0.1:{self.srv.port}",
                         "servers": [{"name": "gone", "address": "127.0.0.1:1"}]})
        self.assertTrue(a.configured())
        up, down = a.games()
        self.assertEqual((up["name"], up["status"], up["players"], up["players_max"]), ("survival", "running", 3, 20))
        self.assertEqual(up["version"], "1.21.4")
        self.assertEqual(up["motd"], "Harbor Point survival")
        self.assertEqual(up["player_names"], ["lamplighter", "Tidewatch"])      # not the hidden-players line
        self.assertEqual(up["address"], f"minecraft://127.0.0.1:{self.srv.port}")
        self.assertEqual((down["name"], down["status"]), ("gone", "stopped"))
        self.assertIn("no answer", down["error"])

    def test_addresses(self):
        self.assertEqual(G.parse_address("minecraft://mc.example.org:25566"), ("mc.example.org", 25566))
        self.assertEqual(G.parse_address("mc.example.org"), ("mc.example.org", 25565))
        self.assertEqual(G.parse_address("[2001:db8::1]:25570"), ("2001:db8::1", 25570))

    def test_not_configured(self):
        a = G.Minecraft({"type": "minecraft"})
        self.assertFalse(a.configured())
        with self.assertRaises(registry.Unreachable):
            a.games()

    def test_varint_round_trip(self):
        class Sock:
            def __init__(self, b):
                self.b = b

            def recv(self, n):
                out, self.b = self.b[:n], self.b[n:]
                return out
        for n in (0, 1, 127, 128, 25565, 2 ** 31 - 1, -1):
            self.assertEqual(G._read_varint(Sock(G._varint(n))), n)


class AlertLinks(unittest.TestCase):
    def test_monitoring_helpers_are_hidden_but_real_info_alerts_remain(self):
        alerts = [
            {"labels": {"alertname": "Watchdog", "severity": "none"}, "state": "firing"},
            {"labels": {"alertname": "InfoInhibitor", "severity": "none"}, "state": "firing"},
            {"labels": {"alertname": "QuotaNearlyFull", "severity": "info"}, "state": "firing"},
            {"labels": {"alertname": "InfoInhibitorCustom", "severity": "info"}, "state": "pending"},
            {"labels": {"alertname": "WatchdogMissing", "severity": "critical"}, "state": "firing"},
            {"labels": {"alertname": "BackupNotice", "severity": "none"}, "state": "firing"},
        ]
        for cls in (P.Prometheus, P.VictoriaMetrics, P.Alertmanager):
            with self.subTest(source=cls.type):
                a = cls({"type": cls.type, "name": "metrics", "endpoint": "https://alerts.example"})
                if cls is P.Alertmanager:
                    payload = [dict(x, status={"state": "active" if x["state"] == "firing" else "pending"})
                               for x in alerts]
                else:
                    payload = {"data": {"alerts": alerts}}
                a.get_json = lambda *args, **kwargs: payload
                out = a.alerts()
                self.assertEqual([x["name"] for x in out],
                                 ["QuotaNearlyFull", "InfoInhibitorCustom", "WatchdogMissing", "BackupNotice"])
                self.assertEqual([x["severity"] for x in out], ["info", "info", "critical", "none"])
                self.assertEqual(out[1]["state"], "pending")

    def test_prometheus_links_to_its_alerts_page(self):
        a = P.Prometheus({"type": "prometheus", "name": "metrics", "endpoint": "https://prom.example"})
        a.get_json = lambda *x, **k: {"data": {"alerts": [
            {"labels": {"alertname": "DiskFull", "severity": "critical"}, "state": "firing", "activeAt": "2026-10-09T08:00:00Z",
             "annotations": {"summary": "disk"}},
            {"labels": {"alertname": "Watchdog"}, "state": "firing"}]}}
        r, = a.alerts()
        self.assertEqual(r["link"], "https://prom.example/alerts?search=DiskFull")

    def test_alertmanager_prefers_the_generator_url(self):
        a = P.Alertmanager({"type": "alertmanager", "name": "am", "endpoint": "https://am.example"})
        a.get_json = lambda *x, **k: [
            {"labels": {"alertname": "A"}, "status": {"state": "active"}, "generatorURL": "https://prom.example/graph?g0.expr=up"},
            {"labels": {"alertname": "B b"}, "status": {"state": "active"}}]
        one, two = a.alerts()
        self.assertEqual(one["link"], "https://prom.example/graph?g0.expr=up")
        self.assertTrue(two["link"].startswith("https://am.example/#/alerts?filter="))
        self.assertIn("B%20b", two["link"])


if __name__ == "__main__":
    unittest.main()
