"""`bromigos lab doctor`'s checks against recorded answers (labfake.py), with DNS, TLS, Vault
and `bromigos target` stood in for.

    PYTHONPATH=lib:../lib python -m unittest discover -s tests
"""
import json
import socket
import subprocess
import unittest
from unittest import mock

import labfake
from bromigos_homelab import doctor
from bromigos_homelab.registry import Adapter, register


def by_id(doc):
    return {f["id"]: f for f in doc["findings"]}


class DoctorTest(unittest.TestCase):
    def run_doctor(self, only=None, lab=None):
        with mock.patch.object(socket, "getaddrinfo", lambda *a, **k: [(2, 1, 6, "", ("192.0.2.1", 0))]), \
                mock.patch.object(doctor, "cert_days", lambda h, p, ca=None, timeout=5: (200, "2027-04-27", True, None)):
            return doctor.run(only=only)

    def test_shape(self):
        with labfake.Lab():
            doc = self.run_doctor()
        self.assertTrue(doc["findings"])
        for f in doc["findings"]:
            self.assertEqual(set(f) - {"source"}, {"id", "check", "title", "status", "detail", "fix"})
            self.assertIn(f["status"], doctor.STATUSES)
            if f["status"] in ("warn", "fail"):
                self.assertTrue(f["fix"], f"{f['id']} has no fix")
            if f["status"] == "ok":
                self.assertEqual(f["fix"], "")
        self.assertEqual(sum(doc["summary"].values()), len(doc["findings"]))
        order = [{"fail": 0, "warn": 1, "ok": 2, "skip": 3}[f["status"]] for f in doc["findings"]]
        self.assertEqual(order, sorted(order))

    def test_argo_drift_and_unreachable_source(self):
        with labfake.Lab() as lab:
            apps = lab.http["prometheus"]["/api/v1/query?query=argocd_app_info"]["data"]["result"]
            apps[0]["metric"]["sync_status"] = "OutOfSync"           # someone changed it by hand
            apps[1]["metric"]["health_status"] = "Degraded"
            doc = self.run_doctor()
        f = by_id(doc)
        oos = [x for x in doc["findings"] if x["check"] == "argo" and x["status"] == "warn"]
        self.assertTrue(oos)
        self.assertIn("Never patch Argo", oos[0]["fix"])
        bad = [x for x in doc["findings"] if x["check"] == "argo" and x["status"] == "fail"]
        self.assertIn("degraded", bad[0]["detail"])
        self.assertEqual(f["sources.ollama.models"]["status"], "fail")
        self.assertIn("homelab.toml", f["sources.ollama.models"]["fix"])

    def test_disk(self):
        with labfake.Lab():
            doc = self.run_doctor({"disk"})
        disks = [x for x in doc["findings"] if x["check"] == "disk"]
        self.assertTrue(disks)
        for x in disks:
            pct = float(x["detail"].split("%")[0])
            self.assertEqual(x["status"], "fail" if pct >= 95 else "warn" if pct >= 85 else "ok")

    def test_gpu(self):
        with labfake.Lab():
            doc = self.run_doctor({"gpu"})
        f = by_id(doc)
        self.assertEqual(f["gpu.comfyui"]["status"], "ok")
        self.assertIn("RTX 5090", f["gpu.comfyui"]["detail"])
        self.assertEqual(len([x for x in doc["findings"] if "the driver sees it" in x["detail"]]), 4)

    def test_dns_failure_says_what_to_do(self):
        def gai(host, *a, **k):
            if host.startswith("tts."):
                raise socket.gaierror(-2, "Name or service not known")
            return [(2, 1, 6, "", ("192.0.2.1", 0))]
        with labfake.Lab(), mock.patch.object(socket, "getaddrinfo", gai):
            doc = doctor.run(only={"dns"})
        f = by_id(doc)["dns.tts.lab.example"]
        self.assertEqual(f["status"], "fail")
        self.assertIn("voice", f["fix"])
        self.assertEqual(by_id(doc)["dns.prometheus.lab.example"]["status"], "ok")

    def test_tls_expiry(self):
        days = {"prometheus.lab.example": 3, "vault.lab.example": 15, "litellm.lab.example": -2,
                "tts.lab.example": 300}
        with labfake.Lab(), mock.patch.object(doctor, "cert_days",
                                              lambda h, p, ca=None, timeout=5: (days[h], "2026-10-24", True, None)):
            doc = doctor.run(only={"tls"})
        f = by_id(doc)
        self.assertEqual(f["tls.prometheus.lab.example"]["status"], "fail")
        self.assertEqual(f["tls.vault.lab.example"]["status"], "warn")
        self.assertEqual(f["tls.litellm.lab.example"]["status"], "fail")
        self.assertIn("expired", f["tls.litellm.lab.example"]["fix"])
        self.assertEqual(f["tls.tts.lab.example"]["status"], "ok")
        self.assertNotIn("tls.comfyui.lab.example", f, "plain http has no certificate")

    def test_tokens_read_metadata_never_a_value(self):
        calls = []

        def vault(args, timeout=8):
            calls.append(args)
            if args[:2] == ["token", "lookup"]:
                return {"data": {"id": "hvs.SECRET-TOKEN-VALUE", "ttl": 3 * 86400, "expire_time": "x"}}
            if args[:3] == ["kv", "metadata", "get"]:
                return {"data": {"custom_metadata": {"expires": "2026-10-11"}}}
            return None
        with labfake.Lab('[console]\ntokens = [{ name = "runner PAT", vault = "kv/lab/ci#token" }]\n'), \
                mock.patch.object(doctor, "_vault", vault), \
                mock.patch("shutil.which", lambda n, *a, **k: "/usr/bin/vault" if n == "vault" else None):
            doc = doctor.run(only={"tokens"})
        f = by_id(doc)
        self.assertEqual(f["tokens.vault-login"]["status"], "warn")
        self.assertIn(f["tokens.runner PAT"]["status"], ("fail", "warn"))
        self.assertNotIn("SECRET-TOKEN-VALUE", json.dumps(doc))
        self.assertFalse([c for c in calls if c[:2] == ["kv", "get"]], "a value is never read")
        self.assertEqual(calls[1], ["kv", "metadata", "get", "-format=json", "kv/lab/ci"])

    def test_targets(self):
        out = {"services": [
            {"service": "image.generate", "entries": [{"target": "homelab", "ok": True, "engine": "comfyui:homelab"}],
             "uses": {"target": "homelab", "engine": "comfyui:homelab (qwen-image-2.1)"}},
            {"service": "voice.tts", "entries": [{"target": "homelab", "ok": False, "engine": "lab",
                                                  "detail": "doesn't answer"},
                                                 {"target": "local", "ok": True, "engine": "kokoro"}],
             "uses": {"target": "local", "engine": "kokoro"}},
            {"service": "video.loop", "entries": [], "uses": None},
            # the preferred workflow answers; a fallback the lab doesn't have is no finding
            {"service": "model3d.generate", "entries": [
                {"target": "homelab", "ok": True, "engine": "comfyui:homelab (pixal3d)"},
                {"target": "homelab", "ok": False, "engine": "comfyui:homelab (hunyuan3d-2.1)",
                 "detail": "missing checkpoints/hunyuan_3d_v2.1.safetensors"}],
             "uses": {"target": "homelab", "engine": "comfyui:homelab (pixal3d)"}},
            # the preferred one is missing and a later one runs: a finding, as before
            {"service": "image.cutout", "entries": [
                {"target": "homelab", "ok": False, "engine": "comfyui:homelab (lucida)", "detail": "missing"},
                {"target": "homelab", "ok": True, "engine": "comfyui:homelab (birefnet)"}],
             "uses": {"target": "homelab", "engine": "comfyui:homelab (birefnet)"}}]}

        def run(argv, **kw):
            return subprocess.CompletedProcess(argv, 0, json.dumps(out), "")
        with labfake.Lab(), mock.patch.object(doctor.subprocess, "run", run), \
                mock.patch.object(doctor.os.path, "exists", lambda p: True):
            doc = doctor.run(only={"targets"})
        f = by_id(doc)
        self.assertEqual(f["targets.image.generate"]["status"], "ok")
        self.assertEqual(f["targets.voice.tts"]["status"], "warn")
        self.assertIn("kokoro", f["targets.voice.tts"]["detail"])
        self.assertEqual(f["targets.video.loop"]["status"], "warn")
        self.assertEqual(f["targets.model3d.generate"]["status"], "ok")
        self.assertEqual(f["targets.image.cutout"]["status"], "warn")
        self.assertIn("lucida", f["targets.image.cutout"]["detail"])

    def test_adapter_checks_and_one_that_fails(self):
        @register
        class Ups(Adapter):
            type = "ups-test"
            provides = ()
            local = True

            def doctor(self):
                return [doctor.finding("ups.battery", "UPS battery", "warn", "62% and falling",
                                       "It's on battery: check the mains.", source=self.name)]

        @register
        class Broken(Adapter):
            type = "broken-test"
            provides = ()
            local = True

            def doctor(self):
                raise OSError("connection reset")
        try:
            with labfake.Lab('[[source]]\nname = "ups"\ntype = "ups-test"\n[[source]]\nname = "bad"\ntype = "broken-test"\n'):
                doc = self.run_doctor()
        finally:
            from bromigos_homelab import registry
            registry.ADAPTERS.pop("ups-test", None)
            registry.ADAPTERS.pop("broken-test", None)
        f = by_id(doc)
        self.assertEqual(f["ups.battery"]["status"], "warn")
        self.assertEqual(f["ups.battery"]["source"], "ups")
        self.assertEqual(f["bad.doctor"]["status"], "fail")
        self.assertTrue(f["bad.doctor"]["fix"])

    def test_a_check_that_raises_is_one_failed_finding(self):
        @doctor.check("zz-raises", "A broken check", needs=())
        def broken():
            raise ValueError("boom")
            yield
        try:
            with labfake.Lab():
                doc = doctor.run(only={"zz-raises"})
        finally:
            doctor.CHECKS.pop("zz-raises")
        (f,) = doc["findings"]
        self.assertEqual(f["status"], "fail")
        self.assertIn("boom", f["detail"])

    def test_needs_skips(self):
        with labfake.Lab():
            doc = self.run_doctor()
        self.assertNotIn("backups", doc["checks"], "no backups source: the check doesn't run")


if __name__ == "__main__":
    unittest.main()
