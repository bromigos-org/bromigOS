"""The lab adapters (adapters/lab*.py) and their doctor checks against recorded answers
(tests/fixtures/lab-adapters.json: sanitised shapes of the real services).

    PYTHONPATH=lib python -m unittest discover -s tests
"""
import gzip
import io
import json
import os
import socket
import tarfile
import tempfile
import threading
import unittest
from unittest import mock

from bromigos_homelab import caps
from bromigos_homelab.adapters import kube, labai, labbackup, labci, labcommon as L, labedge, labgames, labgpu, \
    labmedia, labobserve, labstorage
from bromigos_homelab.registry import Unreachable

HERE = os.path.dirname(os.path.abspath(__file__))
with open(os.path.join(HERE, "fixtures", "lab-adapters.json")) as _f:
    FX = json.load(_f)
NOW = 1791532800.0                       # 2026-10-09T08:00:00Z, the fixtures' "now"


def statuses(findings):
    return {f["id"]: f["status"] for f in findings}


class CommonTest(unittest.TestCase):
    def test_cron_minutes(self):
        self.assertEqual(L.cron_minutes("*/5 * * * *"), 5)
        self.assertEqual(L.cron_minutes("17 * * * *"), 60)
        self.assertEqual(L.cron_minutes("30 3 * * *"), 1440)
        self.assertEqual(L.cron_minutes("17 */6 * * *"), 360)
        self.assertEqual(L.cron_minutes("0 4 * * 0"), 10080)
        self.assertEqual(L.cron_minutes("@hourly"), 60)

    def test_parse_prom(self):
        s = L.parse_prom('# HELP x\nvllm:num_requests_running{model_name="a/b",engine="0"} 2\nup 1\nbad line\n'
                         'x{l="q\\"uote"} 3.5\n')
        self.assertEqual([x["name"] for x in s], ["vllm:num_requests_running", "up", "x"])
        self.assertEqual(s[0]["labels"], {"model_name": "a/b", "engine": "0"})
        self.assertEqual(s[2]["labels"]["l"], 'q"uote')

    def test_ts_and_iso(self):
        self.assertEqual(L.ts("2026-10-09T08:00:00Z"), NOW)
        self.assertEqual(L.iso(NOW), "2026-10-09T08:00:00Z")
        self.assertIsNone(L.ts(""))

    def test_service_spec(self):
        self.assertEqual(L.parse_service("monitoring/loki:3100"), ("monitoring", "loki", "3100"))
        self.assertIsNone(L.parse_service("loki"))

    def test_no_metrics_is_unreachable(self):
        with mock.patch.object(caps, "metrics", return_value={"ok": False, "items": [], "errors": {}, "sources": []}):
            with self.assertRaises(Unreachable):
                L.mq("up")
            self.assertEqual(L.mq_soft("up"), [])

    def test_a_kubeconfig_that_may_not_proxy(self):
        k = mock.Mock()
        k.kubectl.side_effect = RuntimeError('Error from server (Forbidden): services "loki:3100" is forbidden: User '
                                             '"system:serviceaccount:viewer:viewer" cannot get resource "services/proxy"')
        a = labobserve.Loki({"name": "loki", "type": "loki", "service": "monitoring/loki:3100"})
        with mock.patch.object(L, "kube", return_value=k), \
                mock.patch("bromigos_homelab.registry.providers", return_value=[a]):
            r = caps.collect("logs")
        self.assertFalse(r["ok"])
        self.assertIn("services/proxy", r["errors"]["loki"])
        self.assertIn("endpoint", r["errors"]["loki"])

    def test_a_failing_adapter_is_unreachable_not_a_crash(self):
        a = labgpu.DCGM({"name": "dcgm", "type": "dcgm"})
        with mock.patch("bromigos_homelab.registry.providers", return_value=[a]), \
                mock.patch.object(L, "mq", side_effect=Unreachable("prometheus: connection refused")):
            r = caps.collect("gpus")
        self.assertFalse(r["ok"])
        self.assertIn("unreachable", r["errors"]["dcgm"])


class GPUTest(unittest.TestCase):
    def rows(self):
        return {k: v for k, v in FX["dcgm"].items() if k.startswith("DCGM")}

    def test_records(self):
        gpus = labgpu.gpus_from(self.rows(), labgpu.gpu_pods_from_limits(FX["dcgm"]["limits"]))
        by = {g["host"]: g for g in gpus}
        g = by["gpu-node"]
        self.assertEqual(g["name"], "RTX 5090")
        self.assertEqual(g["vram_used"], 31000 * 2 ** 20)
        self.assertEqual(g["vram_total"], 31500 * 2 ** 20)
        self.assertEqual(g["holds"], ["imagegen/imagegen", "voice/voice"])     # DCGM's pod + the node's GPU pods
        s = by["spark-1"]
        self.assertIsNone(s["vram_total"])                                     # unified memory
        self.assertEqual(s["holds"], ["llm/llm-head"])
        self.assertEqual(list(caps._norm("gpus", g, "dcgm"))[:4], ["name", "host", "model", "uuid"])

    def test_pods_from_kube(self):
        self.assertEqual(labgpu.gpu_pods_from_kube(FX["pods"]["gpu_pods"]), {"gpu-node": ["voice/voice"]})

    def test_doctor(self):
        gpus = labgpu.gpus_from(self.rows())
        st = statuses(labgpu.gpu_findings(gpus))
        self.assertEqual(st["gpus.gpu-node.0.temp"], "fail")                 # 91 °C
        self.assertEqual(st["gpus.gpu-node.0.vram"], "warn")                 # 98% used
        self.assertNotIn("gpus.all", st)
        cool = [dict(g, temp_c=40, vram_used=1) for g in gpus]
        self.assertEqual(statuses(labgpu.gpu_findings(cool)), {"gpus.all": "ok"})

    def test_from_exporter_endpoint(self):
        text = "\n".join(f'{m}{{UUID="GPU-aaaa",gpu="0",Hostname="gpu-node",modelName="NVIDIA GeForce RTX 5090",'
                         f'namespace="voice",pod="voice-7d9f8c6b5d-x2x9q"}} {v}'
                         for m, v in (("DCGM_FI_DEV_GPU_UTIL", 5), ("DCGM_FI_DEV_FB_USED", 1024), ("DCGM_FI_DEV_FB_FREE", 1024),
                                      ("DCGM_FI_DEV_GPU_TEMP", 40)))
        a = labgpu.DCGM({"name": "dcgm", "type": "dcgm", "endpoint": "http://gpu-node:9400"})
        with mock.patch.object(a, "request", return_value=text.encode()), mock.patch.object(L, "mq_soft", return_value=[]), \
                mock.patch.object(L, "kube", return_value=None):
            (g,) = a.gpus()
        self.assertEqual(g["holds"], ["voice/voice"])
        self.assertEqual(g["vram_total"], 2 * 2 ** 30)
        self.assertEqual(g["state"], "ok")


class LogsTest(unittest.TestCase):
    def loki(self, **opts):
        a = labobserve.Loki(dict({"name": "loki", "type": "loki", "endpoint": "http://loki:3100"}, **opts))
        answers = {"query": FX["loki"]["errors"], "query_range": FX["loki"]["range"],
                   "buildinfo": FX["loki"]["buildinfo"]}

        def fetch(path, timeout=8, raw=False, headers=None):
            if path == "/ready":
                return b"ready\n"
            key = "query_range" if "query_range" in path else "query" if "/query?" in path else "buildinfo"
            self.paths.append(path)
            return answers[key]
        self.paths = []
        a.fetch = fetch
        return a

    def test_error_counts(self):
        recs = self.loki(warn_errors=25).logs()
        self.assertEqual([(r["name"], r["errors"], r["state"]) for r in recs],
                         [("gateway", 600, "crit"), ("media", 39, "warn"), ("monitoring", 4, "ok")])
        self.assertIn("count_over_time", self.paths[0])

    def test_logs_query(self):
        lines = self.loki().logs_query("media", since_min=30, limit=2)
        self.assertEqual(len(lines), 2)
        self.assertEqual(lines[0]["line"], "Traceback (most recent call last):")     # newest first
        self.assertIn("%7Bnamespace%3D%22media%22%7D", self.paths[-1])

    def test_doctor(self):
        a = self.loki()
        with mock.patch.object(L, "kube", return_value=None):
            st = statuses(a.doctor())
        self.assertEqual(st["apps.loki"], "ok")
        self.assertEqual(st["logs.gateway"], "warn")
        self.assertNotIn("logs.media", st)                                   # under doctor_errors (100)

    def test_quiet_lab(self):
        st = statuses(labobserve.noisy_findings([{"name": "x", "errors": 3}], 100, 15))
        self.assertEqual(st, {"logs.all": "ok"})


class TraefikTest(unittest.TestCase):
    def test_routes(self):
        routes = labedge.routes_from_api(FX["traefik"]["routers"], FX["traefik"]["services"],
                                         rps={"media-tv-0123456789abcdef0123@kubernetescrd": 2.0})
        by = {r["name"]: r for r in routes}
        self.assertEqual(sorted(by), ["broken-broken", "chat-chat", "media-tv", "media-tv#2", "monitoring-grafana-grafana-example-net"])
        self.assertTrue(by["media-tv"]["up"])
        self.assertEqual(by["media-tv"]["host"], "tv.example.net")
        self.assertFalse(by["chat-chat"]["up"])                              # its only server is DOWN
        self.assertTrue(by["chat-chat"]["tls"])
        self.assertEqual(by["monitoring-grafana-grafana-example-net"]["host"], "grafana.example.net")   # an Ingress's rule
        self.assertTrue(by["monitoring-grafana-grafana-example-net"]["up"])  # servers, no health check
        self.assertEqual(by["broken-broken"]["state"], "crit")

    def test_doctor(self):
        st = statuses(labedge.route_findings(labedge.routes_from_api(FX["traefik"]["routers"], FX["traefik"]["services"])))
        self.assertEqual(st, {"routes.broken-broken": "fail", "routes.chat-chat": "fail"})


class CertTest(unittest.TestCase):
    def test_objects(self):
        certs = labedge.certs_from_objects(FX["certificates"]["items"], now=NOW)
        by = {c["name"]: c for c in certs}
        self.assertEqual(by["wildcard"]["days_left"], 9)
        self.assertEqual(by["wildcard"]["state"], "warn")
        self.assertEqual(by["game-node"]["state"], "crit")                   # not ready
        self.assertEqual(by["lab-ca"]["state"], "ok")
        with mock.patch("time.time", return_value=NOW):
            st = statuses(labedge.cert_findings(labedge.certs_from_objects(FX["certificates"]["items"], now=NOW)))
        self.assertEqual(st, {"certs.ingress/wildcard": "warn", "certs.games/game-node": "fail"})

    def test_metrics_and_served(self):
        a = labedge.CertManager({"name": "cm", "type": "cert-manager"})
        exp = [{"labels": {"name": "wildcard", "namespace": "ingress", "issuer_name": "le"}, "value": NOW + 40 * 86400}]
        ready = [{"labels": {"name": "wildcard", "namespace": "ingress", "condition": "True"}, "value": 1}]
        with mock.patch.object(L, "mq_soft", side_effect=lambda q: exp if "expiration" in q else ready if "ready" in q else []):
            (c,) = a.certs()
        self.assertTrue(c["ready"])
        self.assertIn(c["days_left"], (39, 40))
        served = [{"labels": {"cn": "example.net", "sans": "*.example.net,example.net"}, "value": NOW + 5 * 86400}]
        with mock.patch.object(L, "mq_soft", side_effect=lambda q: served if "traefik" in q else []), \
                mock.patch.object(L, "kube", return_value=None):
            (c,) = a.certs()
        self.assertEqual((c["name"], c["state"]), ("example.net", "crit"))


class DDNSTest(unittest.TestCase):
    def test_plain_log(self):
        p = labedge.parse_ddns_log(FX["ddns_logs"]["plain"])
        self.assertEqual(p["public_ip"], "203.0.113.7")
        self.assertEqual(p["changes"], 1)
        self.assertEqual({r["name"]: (r["status"], r["proxied"]) for r in p["records"]},
                         {"*.example.net": ("ok", True), "vpn.example.net": ("updated", False)})

    def test_emoji_log(self):
        p = labedge.parse_ddns_log(FX["ddns_logs"]["emoji"])
        self.assertEqual(p["public_ip"], "203.0.113.9")
        self.assertEqual({r["name"]: r["status"] for r in p["records"]}, {"home.example.net": "ok", "shop.example.net": "fail"})

    def test_records_and_doctor(self):
        p = labedge.parse_ddns_log(FX["ddns_logs"]["plain"])
        job = {"name": "ddns", "namespace": "ddns", "every_min": 5, "age_min": 3, "last_success": NOW}
        recs = labedge.ddns_records(p, True, NOW)
        self.assertTrue(all(r["match"] for r in recs))
        self.assertEqual(statuses(labedge.ddns_findings(recs, job)), {"ddns.all": "ok"})
        moved = labedge.ddns_records(p, True, NOW, now_ip="203.0.113.99")    # the address changed since
        st = statuses(labedge.ddns_findings(moved, job, "203.0.113.99", p["public_ip"]))
        self.assertEqual(st["ddns.ip"], "warn")
        self.assertEqual(st["ddns.vpn.example.net"], "fail")
        stale = dict(job, age_min=90)
        self.assertEqual(statuses(labedge.ddns_findings(recs, stale))["ddns.job"], "fail")
        self.assertEqual(statuses(labedge.ddns_findings([], {"missing": "no DDNS CronJob"})), {"ddns.job": "fail"})


class UniFiTest(unittest.TestCase):
    def rows(self, ap_up=1.0, wan_active=1.0):
        info = [{"labels": {"name": "Gateway", "type": "udm", "model": "UDM", "version": "1"}, "value": 1},
                {"labels": {"name": "AP Hall", "type": "uap", "model": "U7"}, "value": 1}]
        up = [{"labels": {"name": "Gateway"}, "value": 100.0}, {"labels": {"name": "AP Hall"}, "value": ap_up}]
        st = [{"labels": {"name": "AP Hall"}, "value": 12}]
        rx = [{"labels": {"name": "Gateway"}, "value": 1000.0}]
        tx = [{"labels": {"name": "Gateway"}, "value": 500.0}]
        wan = [{"labels": {"wan_interface": "Internet 1", "state": "ACTIVE" if wan_active else "DOWN"}, "value": wan_active},
               {"labels": {"wan_interface": "Internet 2", "state": "BACKUP"}, "value": 0.0}]
        return info, up, st, rx, tx, wan

    def test_records(self):
        recs = {r["name"]: r for r in labedge.unifi_records(*self.rows(), site_clients=20)}
        self.assertEqual(recs["Gateway"]["kind"], "gateway")
        self.assertEqual(recs["Gateway"]["rx_bps"], 8000.0)
        self.assertEqual(recs["AP Hall"]["clients"], 12)
        self.assertTrue(recs["Internet 2"]["up"])                            # a backup link is fine
        self.assertEqual(recs["site"]["clients"], 20)

    def test_doctor(self):
        self.assertEqual(statuses(labedge.network_findings(labedge.unifi_records(*self.rows()))), {"network.all": "ok"})
        st = statuses(labedge.network_findings(labedge.unifi_records(*self.rows(ap_up=0, wan_active=0)), False))
        self.assertEqual(st, {"network.controller": "fail", "network.wan.Internet 1": "fail", "network.AP Hall": "fail"})


class StorageTest(unittest.TestCase):
    def test_s3_health(self):
        self.assertEqual(labstorage.s3_health({"ready": True, "degradedReasons": [], "details": {}}), (True, ""))
        up, why = labstorage.s3_health({"ready": False, "degradedReasons": ["disk offline"],
                                        "details": {"storage": {"ready": False}}})
        self.assertFalse(up)
        self.assertEqual(why, "disk offline; storage not ready")

    def test_s3_buckets_from_metrics(self):
        a = labstorage.S3({"name": "s3", "type": "s3", "endpoint": "http://s3:9000"})
        rows = {"minio_bucket_usage_total_bytes": [{"labels": {"bucket": "backups"}, "value": 1e9}],
                "minio_bucket_usage_object_total": [{"labels": {"bucket": "backups"}, "value": 12}]}
        with mock.patch.object(L, "mq_soft", side_effect=lambda q: rows.get(q, [])):
            (b,) = a.storage()
        self.assertEqual((b["name"], b["kind"], b["used"], b["objects"]), ("backups", "bucket", 1e9, 12))

    def test_nas_records(self):
        recs = labstorage.nas_records([{"labels": {}, "value": 1000.0}], [{"labels": {}, "value": 900.0}],
                                      [{"labels": {"share": "media"}, "value": 50.0}, {"labels": {"share": "db"}, "value": 5.0}],
                                      [{"labels": {"share": "db"}, "value": 10.0}],
                                      [{"name": "web/data", "class": "nfs-client", "used": 1.0, "total": 4.0}])
        by = {r["name"]: r for r in recs}
        self.assertEqual(by["NAS"]["used_pct"], 90.0)
        self.assertIsNone(by["media"]["used_pct"])                           # no quota: no percentage
        self.assertEqual(by["db"]["used_pct"], 50.0)
        self.assertEqual(by["web/data"]["kind"], "volume")

    def test_nas_doctor(self):
        disks = [{"labels": {"slot": "1", "model": "HDD"}, "value": 1.0}, {"labels": {"slot": "2", "model": "HDD"}, "value": 0.0}]
        st = statuses(labstorage.nas_findings(True, disks, (False, "0/1 pods ready")))
        self.assertEqual(st, {"nas.disk.2": "fail", "nas.provisioner": "fail"})
        self.assertEqual(statuses(labstorage.nas_findings(True, disks[:1], (True, "1/1"))),
                         {"nas.provisioner": "ok", "nas.disks": "ok"})


class FakeRedis(threading.Thread):
    """Answers PING and INFO like Dragonfly, then closes on QUIT."""

    def __init__(self):
        super().__init__(daemon=True)
        self.s = socket.socket()
        self.s.bind(("127.0.0.1", 0))
        self.s.listen(4)
        self.port = self.s.getsockname()[1]

    def run(self):
        while True:
            try:
                c, _ = self.s.accept()
            except OSError:
                return
            buf = b""
            while b"QUIT" not in buf:
                d = c.recv(4096)
                if not d:
                    break
                buf += d
            out = b""
            if b"PING" in buf:
                out += b"+PONG\r\n"
            if b"INFO" in buf:
                body = b"# Server\r\ndragonfly_version:v1.38.0\r\nredis_version:7.4.0\r\n"
                out += b"$%d\r\n%s\r\n" % (len(body), body)
            c.sendall(out + b"+OK\r\n")
            c.close()


class AppsTest(unittest.TestCase):
    def test_redis_protocol(self):
        srv = FakeRedis()
        srv.start()
        a = labstorage.Dragonfly({"name": "kv", "type": "dragonfly", "endpoint": f"redis://127.0.0.1:{srv.port}"})
        self.assertTrue(a.probe())
        with mock.patch.object(L, "kube", return_value=None), mock.patch.object(L, "have_metrics", return_value=False):
            (r,) = a.apps()
        self.assertTrue(r["up"])
        self.assertEqual(r["version"], "v1.38.0")
        srv.s.close()

    def test_pod_states(self):
        a = labai.Workload({"name": "web", "type": "workload", "namespace": "web", "kind": "chat"})
        with mock.patch.object(L, "kube", return_value=object()), mock.patch.object(L, "have_metrics", return_value=False), \
                mock.patch.object(L, "pods", return_value=FX["pods"]["app_ok"]):
            (r,) = a.apps()
        self.assertEqual((r["up"], r["kind"], r["detail"]), (True, "chat", "1/1 pods ready · 2 restarts"))   # the Job pod left out
        with mock.patch.object(L, "kube", return_value=object()), mock.patch.object(L, "have_metrics", return_value=False), \
                mock.patch.object(L, "pods", return_value=FX["pods"]["app_crash"]):
            (r,) = a.apps()
            self.assertEqual(statuses(a.doctor())["apps.web"], "fail")
        self.assertFalse(r["up"])
        self.assertIn("CrashLoopBackOff", r["detail"])
        with mock.patch.object(L, "kube", return_value=object()), mock.patch.object(L, "have_metrics", return_value=False), \
                mock.patch.object(L, "pods", return_value=[]):
            (r,) = a.apps()
            self.assertEqual(statuses(a.doctor())["apps.web"], "skip")
        self.assertEqual((r["up"], r["state"]), (None, "not deployed"))      # not down: nothing there

    def test_nothing_to_check_by(self):
        a = labai.Workload({"name": "x", "type": "workload", "namespace": "x"})
        with mock.patch.object(L, "kube", return_value=None):
            with self.assertRaises(Unreachable):
                a.apps()

    def test_http_apps(self):
        cases = [(labai.OpenWebUI, {"/health": {"status": True}, "/api/version": {"version": "0.11.4"}}, "0.11.4"),
                 (labai.SearXNG, {"/healthz": b"OK", "/config": {"version": "2026.10.4", "engines": []}}, "2026.10.4"),
                 (labstorage.Neo4j, {"/": {"neo4j_version": "2026.05.0", "bolt_direct": "bolt://x"}}, "2026.05.0")]
        for cls, answers, version in cases:
            a = cls({"name": cls.type, "type": cls.type, "endpoint": "http://app"})
            a.fetch = lambda path, timeout=8, raw=False, headers=None, ans=answers: ans[path]
            with mock.patch.object(L, "kube", return_value=None), mock.patch.object(L, "have_metrics", return_value=False):
                (r,) = a.apps()
            self.assertEqual((r["up"], r["version"]), (True, version), cls.type)

    def test_unreachable_endpoint_reads_down(self):
        a = labai.OpenWebUI({"name": "chat", "type": "open-webui", "endpoint": "http://chat"})
        a.fetch = mock.Mock(side_effect=Unreachable("chat: [Errno 111] Connection refused"))
        with mock.patch.object(L, "kube", return_value=None), mock.patch.object(L, "have_metrics", return_value=False):
            (r,) = a.apps()
        self.assertFalse(r["up"])
        self.assertIn("unreachable", r["detail"])


class GamesTest(unittest.TestCase):
    def test_metrics(self):
        def rows(m, vals):
            return [{"labels": {"server_uuid": u, "server_name": n, "game": "minecraft"}, "value": v} for (u, n), v in vals]
        s = [("u1", "survival"), ("u2", "creative")]
        g = labgames.games_from_metrics(rows("info", [(s[0], 1), (s[1], 1)]), rows("state", [(s[0], 1), (s[1], 0)]),
                                        rows("p", [(s[0], 3)]), rows("pm", [(s[0], 20)]), [], [], [])
        self.assertEqual([(x["name"], x["status"], x["players"]) for x in g], [("creative", "stopped", None), ("survival", "running", 3)])
        st = statuses(labgames.game_findings(g, expect=("creative",)))
        self.assertEqual(st, {"games.creative": "warn"})
        self.assertEqual(statuses(labgames.game_findings(g)), {"games.all": "ok"})

    def test_api(self):
        g = labgames.games_from_api(FX["pelican_api"]["servers"], FX["pelican_api"]["resources"])
        by = {x["name"]: x for x in g}
        self.assertEqual((by["survival"]["status"], by["survival"]["uptime_s"], by["survival"]["game"]), ("running", 3600, "Paper"))
        self.assertEqual(by["creative"]["status"], "stopped")


class LibraryTest(unittest.TestCase):
    def test_scraparr_metrics(self):
        rows = {"scraparr_services_up": [{"labels": {"alias": "Radarr", "scraparr_services": "radarr"}, "value": 1},
                                         {"labels": {"alias": "sonarr", "scraparr_services": "sonarr"}, "value": 0}],
                "sonarr_queue_count": [{"labels": {"alias": "sonarr"}, "value": 2}],
                "sonarr_queue_error": [{"labels": {"alias": "sonarr"}, "value": 1}],
                "sonarr_free_disk_size": [{"labels": {"alias": "sonarr", "path": "/tv"}, "value": 10 * 2 ** 30}],
                "sonarr_missing_episodes_total": [{"labels": {"alias": "sonarr"}, "value": 21}],
                "radarr_queue_count": [{"labels": {"alias": "Radarr"}, "value": 1}],
                "radarr_missing_movies_total": [{"labels": {"alias": "Radarr"}, "value": 3}]}
        recs = {r["name"]: r for r in labmedia.library_from_metrics(lambda q: rows.get(q, []))}
        self.assertEqual(sorted(recs), ["radarr", "sonarr"])
        self.assertEqual((recs["radarr"]["up"], recs["radarr"]["queue"], recs["radarr"]["missing"]), (True, 1, 3))
        self.assertEqual(recs["sonarr"]["state"], "crit")
        st = statuses(labmedia.library_findings(list(recs.values())))
        self.assertEqual(st, {"library.sonarr": "fail"})
        recs["sonarr"]["up"] = True
        st = statuses(labmedia.library_findings(list(recs.values())))
        self.assertEqual(st, {"library.sonarr.queue": "warn", "library.sonarr.disk": "warn"})

    def test_exportarr_metrics(self):
        rows = {"sonarr_queue_total": [{"labels": {}, "value": 5}], "sonarr_system_status": [{"labels": {}, "value": 1}],
                "sonarr_episode_missing_total": [{"labels": {}, "value": 7}],
                "sonarr_rootfolder_freespace_bytes": [{"labels": {"path": "/tv"}, "value": 1e12}]}
        (r,) = labmedia.library_from_metrics(lambda q: rows.get(q, []))
        self.assertEqual((r["name"], r["queue"], r["missing"], r["disk_free"], r["up"]), ("sonarr", 5, 7, 1e12, True))

    def test_api(self):
        a = labmedia.Arr({"name": "sonarr", "type": "arr", "endpoint": "http://sonarr:8989", "auth_ref": "@env:K"})
        a.fetch = lambda path, timeout=8, raw=False, headers=None: FX["arr_api"][path]
        (r,) = a.library()
        self.assertEqual((r["kind"], r["version"], r["queue"], r["queue_errors"], r["missing"]), ("tv", "4.0.15", 4, 1, 21))
        self.assertEqual(r["disk_free"], 21474836480)
        self.assertEqual(r["state"], "warn")
        with mock.patch.dict(os.environ, {"K": "abc"}):
            self.assertEqual(a.auth_headers(), {"X-Api-Key": "abc"})
        ids = statuses(labmedia.library_findings([r]))
        self.assertEqual(sorted(ids.values()), ["warn", "warn", "warn"])     # health, queue, 20 GiB free


class VLLMTest(unittest.TestCase):
    def page(self, gen, req, waiting=0):
        return L.parse_prom(f'vllm:num_requests_running{{model_name="org/Model-7B"}} 2\n'
                            f'vllm:num_requests_waiting{{model_name="org/Model-7B"}} {waiting}\n'
                            f'vllm:kv_cache_usage_perc{{model_name="org/Model-7B"}} 0.5\n'
                            f'vllm:generation_tokens_total{{model_name="org/Model-7B"}} {gen}\n'
                            f'vllm:request_success_total{{model_name="org/Model-7B",finished_reason="stop"}} {req}\n')

    def test_rates_from_two_reads(self):
        recs, prev = labai.vllm_records(self.page(1000, 10), None, now=100)
        self.assertIsNone(recs[0]["tokens_per_s"])
        recs, prev = labai.vllm_records(self.page(1400, 12, waiting=9), prev, now=102)
        r = recs[0]
        self.assertEqual((r["name"], r["running"], r["waiting"], r["kv_cache_pct"]), ("Model-7B", 2, 9, 50.0))
        self.assertEqual(r["tokens_per_s"], 200.0)
        self.assertEqual(r["requests_per_min"], 60.0)
        self.assertEqual(r["state"], "warn")
        self.assertEqual(statuses(labai.vllm_findings(recs)), {"models.Model-7B.queue": "warn"})

    def test_from_metrics(self):
        a = labai.VLLM({"name": "vllm", "type": "vllm"})
        ans = {"run": [{"labels": {"model_name": "m"}, "value": 1}], "wait": [{"labels": {"model_name": "m"}, "value": 0}],
               "tps": [{"labels": {"model_name": "m"}, "value": 42.0}]}
        with mock.patch.object(L, "mq", return_value=ans["run"]), \
                mock.patch.object(L, "mq_soft", side_effect=lambda q: ans["wait"] if "waiting" in q else
                                  ans["tps"] if "generation" in q else []):
            (r,) = a.models()
        self.assertEqual((r["running"], r["waiting"], r["tokens_per_s"], r["state"]), (1, 0, 42.0, "ok"))


class FakeCtx:
    def __init__(self, tmp):
        self.tmp, self.logs, self.progressed = tmp, [], []

    def out(self, stem=None, ext=None):
        return os.path.join(self.tmp, (stem or "out") + (ext or ".txt"))

    def log(self, t):
        self.logs.append(t)

    def progress(self, f, t=""):
        self.progressed.append(f)

    def cancelled(self):
        return False

    def run(self, argv, timeout=60):
        import subprocess
        prefix = argv[-1]
        for i in (1, 2):                                 # what pdftoppm writes: page-1.png, page-2.png
            with open(f"{prefix}-{i}.png", "wb") as f:
                f.write(b"\x89PNG fake")
        return subprocess.CompletedProcess(argv, 0, "", "")


class OCRTest(unittest.TestCase):
    def test_pages(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(labai.ocr_pages("/x/scan.JPG", None, tmp), [("/x/scan.JPG", "image/jpeg")])
            pages = labai.ocr_pages("/x/doc.pdf", FakeCtx(tmp).run, tmp)
            self.assertEqual([os.path.basename(p) for p, _ in pages], ["page-1.png", "page-2.png"])
            with self.assertRaises(ValueError):
                labai.ocr_pages("/x/notes.docx", None, tmp)

    def test_job(self):
        try:
            from bromigos_homelab import jobs
        except ImportError:
            self.skipTest("no job queue (jobs.py)")
        a = labai.OCR({"name": "ocr", "type": "ocr", "endpoint": "http://ocr:8000", "model": "ocr-model"})
        with tempfile.TemporaryDirectory() as tmp:
            pdf = os.path.join(tmp, "letter.pdf")
            with open(pdf, "wb") as f:
                f.write(b"%PDF-1.7")
            ctx = FakeCtx(tmp)
            with mock.patch("bromigos_homelab.registry.providers", return_value=[a]), \
                    mock.patch.object(a, "page_text", side_effect=["Dear lab,", "Regards."]):
                outs = labai.run_ocr({"inputs": [pdf]}, ctx)
            with open(outs[0]) as f:
                self.assertEqual(f.read(), "Dear lab,\n\f\nRegards.\n")
            self.assertEqual(ctx.progressed[-1], 1.0)
        self.assertIn("ocr", {k.id for k in jobs.kinds()})

    def test_key_without_the_model_warns(self):
        a = labai.OCR({"name": "ocr", "type": "ocr", "via": "llm", "model": "ocr-model"})
        body = json.dumps({"data": [{"id": "chat"}, {"id": "embed"}]}).encode()

        class R(io.BytesIO):
            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False
        with mock.patch.object(a, "_api", return_value=("http://gw/v1", {}, "ocr-model")), \
                mock.patch("urllib.request.urlopen", return_value=R(body)), \
                mock.patch.object(L, "kube", return_value=None), mock.patch.object(L, "have_metrics", return_value=False):
            (r,) = a.ocr()
            st = statuses(a.doctor())
        self.assertEqual(r["state"], "warn")
        self.assertEqual(st, {"ocr.ocr": "warn"})


class RunnersTest(unittest.TestCase):
    def test_listener_logs(self):
        self.assertEqual(labci.listener_stats(FX["arc_log"]), {"assigned": 3, "min": 0, "max": 1, "current": 1})
        old = labci.listener_stats(FX["arc_log_old"])
        self.assertEqual((old["assigned"], old["busy"], old["idle"]), (2, 1, 1))

    def test_records(self):
        stats = {"pool-amd64": labci.listener_stats(FX["arc_log"])}
        recs = {r["name"]: r for r in labci.runner_records(FX["pods"]["listeners"], FX["pods"]["runners"], stats)}
        a = recs["pool-amd64"]
        self.assertEqual((a["online"], a["runners"], a["queued"], a["max"], a["state"]), (True, 1, 2, 1, "warn"))
        self.assertEqual(recs["pool-arm64"]["state"], "crit")
        st = statuses(labci.runner_findings(list(recs.values())))
        self.assertEqual(st, {"runners.pool-amd64": "warn", "runners.pool-arm64": "fail"})

    def test_metrics(self):
        rows = {"gha_registered_runners": [{"labels": {"name": "p", "organization": "o"}, "value": 2}],
                "gha_assigned_jobs": [{"labels": {"name": "p"}, "value": 3}],
                "gha_running_jobs": [{"labels": {"name": "p"}, "value": 2}],
                "gha_max_runners": [{"labels": {"name": "p"}, "value": 2}]}
        (r,) = labci.runner_records_from_metrics(lambda m: rows.get(m, []))
        self.assertEqual((r["runners"], r["queued"], r["state"]), (2, 1, "warn"))


def make_db(pkgs):
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w") as tf:
        for name, ver, built in pkgs:
            desc = f"%FILENAME%\n{name}-{ver}-any.pkg.tar.zst\n\n%NAME%\n{name}\n\n%VERSION%\n{ver}\n\n%BUILDDATE%\n{built}\n\n"
            info = tarfile.TarInfo(f"{name}-{ver}/desc")
            info.size = len(desc.encode())
            tf.addfile(info, io.BytesIO(desc.encode()))
    return gzip.compress(buf.getvalue())


class PackagesTest(unittest.TestCase):
    def test_db(self):
        pkgs = labci.parse_db(make_db([("desk-core", "0.1.0.r9-1", int(NOW - 7200)), ("desk-ui", "0.1.0.r3-1", int(NOW - 3600))]))
        r = labci.channel_record("edge", "desk", pkgs, now=NOW)
        self.assertEqual((r["latest"], r["age_h"], r["packages"]), ("desk-ui 0.1.0.r3-1", 1.0, 2))

    def test_pacman_conf(self):
        with tempfile.NamedTemporaryFile("w", suffix=".conf", delete=False) as f:
            f.write("[core]\nInclude = /etc/pacman.d/mirrorlist\n\n[desk]\nSigLevel = Required\n"
                    "Server = https://pkgs.example.net/$repo/stable/$arch\n")
        try:
            s = labci.pacman_server("desk", f.name)
        finally:
            os.unlink(f.name)
        self.assertEqual(s, "https://pkgs.example.net/$repo/stable/$arch")
        self.assertEqual(labci.repo_base(s), "https://pkgs.example.net")

    def test_channels_and_unpublished(self):
        import urllib.error
        a = labci.PacmanRepo({"name": "pkgs", "type": "pacman-repo", "endpoint": "https://pkgs.example.net", "repo": "bromigos",
                              "arch": "x86_64"})
        db = make_db([("bromigos-core", "1-1", int(NOW))])

        def request(url, timeout=8, raw=False, **kw):
            if "/rc/" in url:
                raise urllib.error.HTTPError(url, 404, "Not Found", {}, None)
            return db
        a.request = request
        recs = {r["name"]: r for r in a.packages()}
        self.assertEqual(sorted(recs), ["edge", "rc", "stable"])
        self.assertEqual(recs["rc"]["state"], "unknown")
        self.assertEqual(recs["edge"]["packages"], 1)

    def test_doctor(self):
        recs = [{"name": "edge", "built": "2026-10-08T00:00:00Z", "age_h": 32.0, "state": "ok"},
                {"name": "rc", "state": "unknown", "detail": "not published"}]
        failed = [{"status": "completed", "conclusion": "failure", "displayTitle": "a change", "url": "https://ci/1"}]
        self.assertEqual(statuses(labci.package_findings(recs, failed, now=NOW)), {"packages.rc": "skip", "packages.publish": "fail"})
        later_ok = [{"status": "completed", "conclusion": "success", "updatedAt": "2026-10-09T07:00:00Z"}]
        self.assertEqual(statuses(labci.package_findings(recs, later_ok, now=NOW))["packages.stale"], "warn")
        st = statuses(labci.package_findings(recs[:1], None, now=NOW))
        self.assertEqual(st, {"packages.all": "ok"})


class BackupsTest(unittest.TestCase):
    def cronjob(self, name, ns, schedule, ok, sched, active=0):
        return {"metadata": {"name": name, "namespace": ns}, "spec": {"schedule": schedule},
                "status": {"lastSuccessfulTime": ok, "lastScheduleTime": sched, **({"active": [{}] * active} if active else {})}}

    def test_jobs(self):
        items = [self.cronjob("db-backup", "web", "15 4 * * *", "2026-10-09T04:15:22Z", "2026-10-09T04:15:00Z"),
                 self.cronjob("vault-snapshot", "vault", "30 2 * * *", "2026-10-07T02:30:09Z", "2026-10-09T02:30:00Z"),
                 self.cronjob("coins-snapshots", "data", "17 */6 * * *", None, None),        # a data job, not a backup
                 self.cronjob("db-restore-drill", "web", "30 6 * * 0", None, None),
                 self.cronjob("nightly-report", "web", "0 1 * * *", None, None)]
        recs = {r["name"]: r for r in labbackup.jobs_from_objects(items, exclude=r"restore|drill", now=NOW)}
        self.assertEqual(sorted(recs), ["vault/vault-snapshot", "web/db-backup"])
        self.assertTrue(recs["web/db-backup"]["ok"])
        self.assertEqual(recs["web/db-backup"]["max_age_hours"], 38.0)
        self.assertFalse(recs["vault/vault-snapshot"]["ok"])                    # scheduled since, no success

    def test_jobs_from_metrics(self):
        rows = {"kube_cronjob_info": [{"labels": {"namespace": "web", "cronjob": "db-backup", "schedule": "*/30 * * * *"}, "value": 1}],
                "kube_cronjob_status_last_successful_time": [{"labels": {"namespace": "web", "cronjob": "db-backup"}, "value": NOW - 600}],
                "kube_cronjob_status_last_schedule_time": [{"labels": {"namespace": "web", "cronjob": "db-backup"}, "value": NOW - 600}]}
        (r,) = labbackup.jobs_from_metrics(lambda m: rows.get(m, []), now=NOW)
        self.assertEqual((r["ok"], r["age_h"], r["max_age_hours"]), (True, 0.17, 2.8))

    def test_snapshots(self):
        recs = labbackup.snapshot_records(
            [{"labels": {"share": "db"}, "value": NOW - 3600}, {"labels": {"share": "scratch"}, "value": NOW - 9e6}],
            [{"labels": {"share": "db"}, "value": 1}, {"labels": {"share": "scratch"}, "value": 0}],
            [{"labels": {"share": "db"}, "value": 8}], now=NOW)
        self.assertEqual([(r["name"], r["schedule"], r["max_age_hours"]) for r in recs], [("db", "every 24 h", 38.0)])

    def test_coverage(self):
        self.assertEqual(statuses(labbackup.coverage_findings([], [], [], False)), {"backups.none": "fail"})
        recs = [{"name": "web/db-backup", "kind": "job", "namespace": "web"}]
        st = statuses(labbackup.coverage_findings(recs, [("web", "data"), ("media", "config"), ("tmp", "cache")],
                                                  ["scratch", "photos"], False, ignore=("tmp", "scratch")))
        self.assertEqual(st, {"backups.coverage.volumes": "warn", "backups.coverage.shares": "warn", "backups.offsite": "warn"})
        f = {x["id"]: x for x in labbackup.coverage_findings(recs, [("media", "config")], ["photos"], False)}
        self.assertIn("media/config", f["backups.coverage.volumes"]["detail"])
        self.assertEqual(statuses(labbackup.coverage_findings(recs + [{"name": "cloud", "kind": "job", "offsite": True}],
                                                              [("web", "data")], [], True)), {"backups.coverage": "ok"})


class ArgoTest(unittest.TestCase):
    def test_message(self):
        self.assertEqual(kube.app_message(FX["argo"]["app"]), "differs from git: Application/gpu-operator")
        m = kube.app_message(FX["argo"]["degraded"])
        self.assertIn("SyncError: one or more objects failed to apply", m)
        self.assertIn("last sync failed: Job batch-weekly failed", m)
        self.assertIn("Job/batch-weekly: Job has reached the specified backoff limit", m)

    def test_record_from_object(self):
        a = kube.ArgoCD({"name": "argocd", "type": "argocd"})
        r = a._from_object(FX["argo"]["degraded"])
        self.assertEqual((r["sync"], r["health"], r["revision"]), ("synced", "degraded", "v1.2.0"))

    def test_flips(self):
        self.assertEqual(kube.count_flips(FX["argo"]["events"], 60, now=NOW), {"apps-root": 3})

    def test_findings(self):
        a = kube.ArgoCD({"name": "argocd", "type": "argocd"})
        apps = [dict(a._from_object(FX["argo"]["app"]), sync="synced"),          # synced just now, but it flaps
                a._from_object(FX["argo"]["degraded"]),
                {"name": "web", "sync": "synced", "health": "healthy", "message": None}]
        f = {x["id"]: x for x in kube.argo_findings(apps, {"apps-root": 3})}
        self.assertEqual(sorted(f), ["argo.apps-root.why", "argo.batch.why"])
        self.assertEqual(f["argo.apps-root.why"]["status"], "warn")
        self.assertIn("Application/gpu-operator", f["argo.apps-root.why"]["detail"])
        self.assertIn("3 times in the last hour", f["argo.apps-root.why"]["detail"])
        self.assertIn("ignoreDifferences", f["argo.apps-root.why"]["fix"])
        self.assertEqual(f["argo.batch.why"]["status"], "fail")
        self.assertEqual(f["argo.batch.why"]["check"], "argo")

    def test_metrics_path_reads_why_from_objects(self):
        a = kube.ArgoCD({"name": "argocd", "type": "argocd"})
        info = [{"labels": {"name": "apps-root", "dest_namespace": "argocd", "sync_status": "OutOfSync",
                            "health_status": "Healthy"}},
                {"labels": {"name": "web", "dest_namespace": "web", "sync_status": "Synced", "health_status": "Healthy"}}]
        k = mock.Mock()
        k.kubectl.return_value = json.dumps({"items": [FX["argo"]["app"]]})
        with mock.patch("bromigos_homelab.caps.available", return_value=True), \
                mock.patch("bromigos_homelab.caps.metrics", return_value={"ok": True, "items": info}), \
                mock.patch.object(kube, "_kube_source", return_value=k):
            apps = {x["name"]: x for x in a.deployments()}
        self.assertEqual(apps["apps-root"]["message"], "differs from git: Application/gpu-operator")
        self.assertIsNone(apps["web"]["message"])


class DetectTest(unittest.TestCase):
    def test_detect_from_metrics_and_pods(self):
        class M:
            def metrics_query(self, q, timeout=8):
                have = ("DCGM_FI_DEV_GPU_UTIL", "unpoller_device_info", "scraparr_services_up", "pelican_server_info",
                        "vllm:num_requests_running", "traefik_router_requests_total")
                return [{"labels": {}, "value": 1.0}] if any(h in q for h in have) else []

        class K:
            def kubectl(self, args, timeout=25):
                if "pods" in args and LISTENER in args:
                    return json.dumps({"items": FX["pods"]["listeners"]})
                return json.dumps({"items": []})
        LISTENER = labci.LISTENER
        d = L.Discovery(M(), K())
        found = {t: cls.detect(d) for t, cls in (("dcgm", labgpu.DCGM), ("unifi", labedge.UniFi), ("arr", labmedia.Arr),
                                                  ("pelican", labgames.Pelican), ("vllm", labai.VLLM),
                                                  ("traefik", labedge.Traefik), ("arc", labci.ARC), ("ddns", labedge.DDNS),
                                                  ("backups", labbackup.Backups))}
        self.assertEqual([t for t, v in found.items() if v], ["dcgm", "unifi", "arr", "pelican", "vllm", "traefik", "arc",
                                                             "backups"])
        self.assertEqual(L.Discovery().rows("up"), [])


if __name__ == "__main__":
    unittest.main()

