#!/usr/bin/env python3
"""Tests for the brodec-lab chart: helm lint, then helm template with several values, checked.

  python3 homelab/charts/brodec-lab/tests/test_chart.py

Needs helm (3.8 or later) and PyYAML. No cluster: `lookup` sees nothing, as on a first install.
"""
import pathlib
import subprocess
import sys
import unittest

import yaml

CHART = pathlib.Path(__file__).resolve().parent.parent


def helm(*args, ok=True):
    r = subprocess.run(["helm", *args], capture_output=True, text=True)
    if ok and r.returncode:
        raise AssertionError(f"helm {' '.join(args)} failed:\n{r.stderr}")
    return r


def render(*sets, name="lab", ns="brodec-lab"):
    args = ["template", name, str(CHART), "--namespace", ns]
    for s in sets:
        args += ["--set", s]
    docs = [d for d in yaml.safe_load_all(helm(*args).stdout) if d]
    return {(d["kind"], d["metadata"]["name"]): d for d in docs}


def env(dep):
    c = dep["spec"]["template"]["spec"]["containers"][0]
    return {e["name"]: e["value"] for e in c["env"]}


class Chart(unittest.TestCase):
    def test_lint(self):
        helm("lint", "--strict", str(CHART), "--set", "lab.name=my-lab")

    def test_defaults_are_locked_down(self):
        out = render("lab.name=basement-rack")
        self.assertEqual(sorted(k for k, _ in out), ["Deployment", "NetworkPolicy", "PersistentVolumeClaim", "Secret"])
        dep = out[("Deployment", "lab-brodec-lab")]
        spec = dep["spec"]
        self.assertEqual(spec["replicas"], 1)
        self.assertEqual(spec["strategy"]["type"], "Recreate")
        pod = spec["template"]["spec"]
        self.assertIs(pod["automountServiceAccountToken"], False)
        self.assertEqual(pod["securityContext"]["runAsUser"], 10001)
        self.assertEqual(pod["securityContext"]["runAsGroup"], 10001)
        self.assertIs(pod["securityContext"]["runAsNonRoot"], True)
        self.assertEqual(pod["securityContext"]["seccompProfile"]["type"], "RuntimeDefault")
        c = pod["containers"][0]
        self.assertIs(c["securityContext"]["readOnlyRootFilesystem"], True)
        self.assertIs(c["securityContext"]["allowPrivilegeEscalation"], False)
        self.assertEqual(c["securityContext"]["capabilities"]["drop"], ["ALL"])
        self.assertEqual(c["image"], "ghcr.io/bromigos-org/brodec-lab:0.1.0")
        self.assertEqual(c["livenessProbe"]["exec"]["command"], ["/usr/local/bin/brodec-lab", "health"])
        self.assertEqual(c["readinessProbe"]["exec"]["command"], ["/usr/local/bin/brodec-lab", "health", "--ready"])
        e = env(dep)
        self.assertEqual(e["BRODEC_LAB_NAME"], "basement-rack")
        self.assertEqual(e["BRODEC_DATA_DIR"], "/data/bridge")
        self.assertEqual(e["BRODEC_SWITCH_ON_FILE"], "/run/switch/on")
        self.assertEqual(e["BRODEC_HOMESERVER"], "https://matrix.bromigos.org")
        for k in e:
            self.assertFalse(k.endswith("_URL") and k.startswith("BRODEC_LAB_"), k)
            self.assertNotIn("BRAIN", k)
        # No RBAC, no service account, no Service: nothing talks to it and it talks to no API.
        self.assertFalse(any(k in ("Role", "ClusterRole", "RoleBinding", "ClusterRoleBinding", "ServiceAccount", "Service") for k, _ in out))
        pvc = out[("PersistentVolumeClaim", "lab-brodec-lab-data")]
        self.assertEqual(pvc["spec"]["accessModes"], ["ReadWriteOnce"])
        self.assertEqual(pvc["metadata"]["annotations"]["helm.sh/resource-policy"], "keep")
        sw = out[("Secret", "lab-brodec-lab-switch")]
        self.assertEqual(sw["data"], {"on": ""})
        self.assertEqual(sw["metadata"]["annotations"]["helm.sh/resource-policy"], "keep")

    def test_lab_name_defaults_to_release_and_is_checked(self):
        self.assertEqual(env(render(name="rack")[("Deployment", "rack-brodec-lab")])["BRODEC_LAB_NAME"], "rack")
        r = helm("template", "x", str(CHART), "--set", "lab.name=bad name;rm", ok=False)
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("lab.name", r.stderr)

    def test_sources_brain_and_secrets(self):
        out = render("lab.name=r", "sources.prometheusUrl=http://prometheus-operated.monitoring.svc:9090",
                     "sources.alertmanagerUrl=http://alertmanager.monitoring.svc:9093",
                     "sources.labApi.url=https://status.example.org", "sources.labApi.tokenSecret.name=lab-token",
                     "brain.url=http://ollama.ai.svc:11434/v1", "brain.model=llama3.1:8b",
                     "brain.keySecret.name=brain", "image.tag=0.1.0.r9.gabcdef0")
        dep = out[("Deployment", "lab-brodec-lab")]
        e = env(dep)
        self.assertEqual(e["BRODEC_LAB_PROMETHEUS_URL"], "http://prometheus-operated.monitoring.svc:9090")
        self.assertEqual(e["BRODEC_LAB_ALERTMANAGER_URL"], "http://alertmanager.monitoring.svc:9093")
        self.assertEqual(e["BRODEC_LAB_API_URL"], "https://status.example.org")
        self.assertEqual(e["BRODEC_LAB_API_TOKEN_FILE"], "/run/secrets/lab-api/token")
        self.assertEqual(e["BRODEC_BRAIN_URL"], "http://ollama.ai.svc:11434/v1")
        self.assertEqual(e["BRODEC_BRAIN_MODEL"], "llama3.1:8b")
        self.assertEqual(e["BRODEC_BRAIN_KEY_FILE"], "/run/secrets/brain/key")
        pod = dep["spec"]["template"]["spec"]
        self.assertEqual(pod["containers"][0]["image"], "ghcr.io/bromigos-org/brodec-lab:0.1.0.r9.gabcdef0")
        vols = {v["name"]: v for v in pod["volumes"]}
        self.assertEqual(vols["lab-api"]["secret"]["secretName"], "lab-token")
        self.assertEqual(vols["brain"]["secret"]["items"], [{"key": "key", "path": "key"}])
        # Secrets are files, never env values.
        for v in e.values():
            self.assertNotIn("secret", v.lower().replace("/run/secrets/", ""))
        np = out[("NetworkPolicy", "lab-brodec-lab")]["spec"]
        self.assertEqual(np["ingress"], [])
        ports = sorted(p["port"] for rule in np["egress"] for p in rule["ports"] if p["protocol"] == "TCP")
        self.assertEqual(ports, [53, 443, 9090, 9093, 11434])

    def test_guests_never_get_the_brain_by_default(self):
        brain = ["lab.name=r", "brain.url=http://agent.ai.svc:8642/v1", "brain.model=m", "brain.keySecret.name=brain"]
        # Default: no guest brain at all; guests get a polite no, never `brain`.
        e = env(render(*brain)[("Deployment", "lab-brodec-lab")])
        self.assertFalse([k for k in e if k.startswith("BRODEC_GUEST_BRAIN")], e)
        # A guest brain of its own, with its own key and port.
        out = render(*brain, "guestBrain.url=http://plain.ai.svc:11434/v1", "guestBrain.model=small",
                     "guestBrain.keySecret.name=guest-key")
        dep = out[("Deployment", "lab-brodec-lab")]
        e = env(dep)
        self.assertEqual(e["BRODEC_GUEST_BRAIN_URL"], "http://plain.ai.svc:11434/v1")
        self.assertEqual(e["BRODEC_GUEST_BRAIN_MODEL"], "small")
        self.assertEqual(e["BRODEC_GUEST_BRAIN_KEY_FILE"], "/run/secrets/guest-brain/key")
        vols = {v["name"]: v for v in dep["spec"]["template"]["spec"]["volumes"]}
        self.assertEqual(vols["guest-brain"]["secret"]["secretName"], "guest-key")
        np = out[("NetworkPolicy", "lab-brodec-lab")]["spec"]
        ports = sorted(p["port"] for rule in np["egress"] for p in rule["ports"] if p["protocol"] == "TCP")
        self.assertIn(11434, ports)
        # sameAsBrain: the owner's say-so that `brain` is a plain model API.
        e = env(render(*brain, "guestBrain.sameAsBrain=true")[("Deployment", "lab-brodec-lab")])
        self.assertEqual(e["BRODEC_GUEST_BRAIN_URL"], e["BRODEC_BRAIN_URL"])
        self.assertEqual(e["BRODEC_GUEST_BRAIN_KEY_FILE"], "/run/secrets/guest-brain/key")
        # Both, or a URL without a model, is refused.
        for bad in (["guestBrain.sameAsBrain=true", "guestBrain.url=http://x:1/v1"], ["guestBrain.url=http://x:1/v1"]):
            args = ["template", "x", str(CHART)]
            for s in brain[:1] + bad:
                args += ["--set", s]
            self.assertNotEqual(helm(*args, ok=False).returncode, 0, bad)

    def test_no_network_policy_and_existing_things(self):
        out = render("lab.name=r", "networkPolicy.enabled=false", "persistence.existingClaim=mine",
                     "switch.create=false", "switch.existingSecret=my-switch")
        self.assertEqual(sorted(k for k, _ in out), ["Deployment"])
        vols = {v["name"]: v for v in out[("Deployment", "lab-brodec-lab")]["spec"]["template"]["spec"]["volumes"]}
        self.assertEqual(vols["data"]["persistentVolumeClaim"]["claimName"], "mine")
        self.assertEqual(vols["switch"]["secret"]["secretName"], "my-switch")
        r = helm("template", "x", str(CHART), "--set", "lab.name=r", "--set", "switch.create=false", ok=False)
        self.assertNotEqual(r.returncode, 0)

    def test_lab_network_address(self):
        e = env(render("lab.name=r")[("Deployment", "lab-brodec-lab")])
        self.assertNotIn("BRODEC_LAB_NETWORK_URL", e, "not offered unless set")
        e = env(render("lab.name=r", "network.loginServer=https://net.example.org", "network.name=Home")[
            ("Deployment", "lab-brodec-lab")])
        self.assertEqual(e["BRODEC_LAB_NETWORK_URL"], "https://net.example.org")
        self.assertEqual(e["BRODEC_LAB_NETWORK_NAME"], "Home")

    MEDIA = ["lab.name=r", "mediaServer.enabled=true", "mediaServer.host=100.64.0.7"]

    @staticmethod
    def containers(dep):
        return {c["name"]: c for c in dep["spec"]["template"]["spec"]["containers"]}

    def test_media_server_is_off_by_default(self):
        out = render("lab.name=r")
        dep = out[("Deployment", "lab-brodec-lab")]
        self.assertEqual(list(self.containers(dep)), ["bridge"])
        self.assertFalse([k for k in env(dep) if k.startswith("BRODEC_STREAM_")])
        self.assertNotIn(("ConfigMap", "lab-brodec-lab-mediamtx"), out)
        self.assertNotIn(("Service", "lab-brodec-lab-media"), out)
        np = out[("NetworkPolicy", "lab-brodec-lab")]["spec"]
        self.assertEqual(np["ingress"], [])
        udp = [p["port"] for rule in np["egress"] for p in rule["ports"] if p["protocol"] == "UDP"]
        self.assertEqual(udp, [53])
        text = helm("template", "lab", str(CHART), "--set", "lab.name=r").stdout
        for port in ("1935", "8889", "8890", "8189", "8888", "9996", "9997", "9108"):
            self.assertNotIn(port, text, port)

    def test_media_server_on_keeps_its_api_and_hook_on_loopback(self):
        out = render(*self.MEDIA)
        dep = out[("Deployment", "lab-brodec-lab")]
        cs = self.containers(dep)
        self.assertEqual(list(cs), ["bridge", "mediamtx"], "no tailnet unless asked")
        m = cs["mediamtx"]
        self.assertTrue(m["image"].startswith("docker.io/bluenviron/mediamtx:1.21.3@sha256:"), m["image"])
        self.assertIs(m["securityContext"]["readOnlyRootFilesystem"], True)
        self.assertEqual(m["securityContext"]["capabilities"]["drop"], ["ALL"])
        self.assertIs(m["securityContext"]["allowPrivilegeEscalation"], False)
        self.assertNotIn("env", m, "no secret without a relay")
        e = env(dep)
        self.assertEqual(e["BRODEC_STREAM_API_URL"], "http://127.0.0.1:9997")
        self.assertEqual(e["BRODEC_STREAM_AUTH_LISTEN"], "127.0.0.1:9108")
        self.assertEqual(e["BRODEC_STREAM_HOST"], "100.64.0.7")
        self.assertEqual(e["BRODEC_STREAM_MAX_STREAMS"], "1")
        self.assertEqual(e["BRODEC_STREAM_MAX_VIEWERS"], "10")
        self.assertEqual(e["BRODEC_STREAM_TRANSCODE"], "none")
        for k in ("BRODEC_STREAM_RELAY", "BRODEC_STREAM_RECORD", "BRODEC_STREAM_GUESTS", "BRODEC_STREAM_LAN_HOST"):
            self.assertNotIn(k, e, k)
        conf = yaml.safe_load(out[("ConfigMap", "lab-brodec-lab-mediamtx")]["data"]["mediamtx.yml"])
        self.assertEqual(conf["authMethod"], "http")
        self.assertEqual(conf["authHTTPAddress"], "http://127.0.0.1:9108/mediamtx/auth")
        self.assertEqual(conf["apiAddress"], "127.0.0.1:9997")
        self.assertEqual(conf["rtspAddress"], "127.0.0.1:8554")
        self.assertIs(conf["moq"], False)
        self.assertIs(conf["metrics"], False)
        self.assertIs(conf["pprof"], False)
        self.assertIs(conf["playback"], False)
        self.assertIs(conf["webrtcIPsFromInterfaces"], False)
        self.assertEqual(conf["webrtcAdditionalHosts"], ["100.64.0.7"])
        self.assertEqual(conf["webrtcICEServers2"], [])
        self.assertIs(conf["pathDefaults"]["record"], False)
        self.assertEqual(conf["paths"], {})
        # Nothing exposes the API or the hook: no Service, no container port, no policy port.
        self.assertNotIn(("Service", "lab-brodec-lab-media"), out, "LAN off by default")
        ports = [p["containerPort"] for p in m["ports"]]
        self.assertEqual(sorted(set(ports)), [1935, 8189, 8888, 8889, 8890])
        np = out[("NetworkPolicy", "lab-brodec-lab")]["spec"]
        self.assertEqual(np["ingress"], [], "the tailnet dials out; nothing connects in")
        anno = dep["spec"]["template"]["metadata"]["annotations"]
        self.assertIn("checksum/mediamtx", anno)
        r = helm("template", "x", str(CHART), "--set", "lab.name=r", "--set", "mediaServer.enabled=true", ok=False)
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("mediaServer.host", r.stderr)

    def test_media_tailnet_forwards_only_media_ports(self):
        out = render(*self.MEDIA, "mediaServer.tailnet.enabled=true", "mediaServer.tailnet.loginServer=https://net.example.org",
                     "mediaServer.tailnet.authKeySecret.name=ts", "mediaServer.recording.existingClaim=nas")
        dep = out[("Deployment", "lab-brodec-lab")]
        ts = self.containers(dep)["tailnet"]
        te = {x["name"]: x for x in ts["env"]}
        self.assertEqual(te["TS_USERSPACE"]["value"], "true")
        self.assertEqual(te["TS_AUTHKEY"]["valueFrom"]["secretKeyRef"], {"name": "ts", "key": "auth_key"})
        self.assertEqual(te["TS_EXTRA_ARGS"]["value"], "--login-server=https://net.example.org")
        import json
        serve = json.loads(te["TS_SERVE_JSON"]["value"])
        self.assertEqual(sorted(serve["TCP"]), ["1935", "8189", "8888", "8889", "9996"])
        for port, rule in serve["TCP"].items():
            self.assertEqual(rule, {"TCPForward": f"127.0.0.1:{port}"})
        self.assertEqual(ts["securityContext"]["capabilities"]["drop"], ["ALL"])
        np = out[("NetworkPolicy", "lab-brodec-lab")]["spec"]
        udp = sorted(p["port"] for rule in np["egress"] for p in rule["ports"] if p["protocol"] == "UDP")
        self.assertEqual(udp, [53, 3478, 41641])
        for k in ("tailnet", "loginServer"):
            r = helm("template", "x", str(CHART), *sum((["--set", s] for s in self.MEDIA + ["mediaServer.tailnet.enabled=true"]), []), ok=False)
            self.assertNotEqual(r.returncode, 0, k)

    def test_media_recording_relay_and_lan(self):
        out = render(*self.MEDIA, "mediaServer.recording.existingClaim=nas-recordings", "mediaServer.recording.keepDays=7",
                     "mediaServer.relay.turnUrl=turns:turn.example.org", "mediaServer.relay.secret.name=turn",
                     "mediaServer.consoles.enabled=true", "mediaServer.consoleHost=media.example.org",
                     "mediaServer.consoles.allowFrom={100.64.0.0/10}", "mediaServer.guests=true", "mediaServer.transcode=opus")
        dep = out[("Deployment", "lab-brodec-lab")]
        e = env(dep)
        self.assertEqual(e["BRODEC_STREAM_RECORD"], "on")
        self.assertEqual(e["BRODEC_STREAM_RELAY"], "on")
        self.assertEqual(e["BRODEC_STREAM_GUESTS"], "on")
        self.assertEqual(e["BRODEC_STREAM_LAN_HOST"], "media.example.org")
        self.assertEqual(e["BRODEC_STREAM_TRANSCODE"], "opus")
        m = self.containers(dep)["mediamtx"]
        self.assertIn(":1.21.3-ffmpeg@sha256:", m["image"])
        self.assertEqual(m["env"], [{"name": "MTX_WEBRTCICESERVERS2_0_PASSWORD",
                                     "valueFrom": {"secretKeyRef": {"name": "turn", "key": "secret"}}}])
        self.assertIn({"name": "recordings", "mountPath": "/recordings"}, m["volumeMounts"])
        vols = {v["name"]: v for v in dep["spec"]["template"]["spec"]["volumes"]}
        self.assertEqual(vols["recordings"]["persistentVolumeClaim"]["claimName"], "nas-recordings")
        conf = yaml.safe_load(out[("ConfigMap", "lab-brodec-lab-mediamtx")]["data"]["mediamtx.yml"])
        self.assertIs(conf["playback"], True)
        self.assertEqual(conf["pathDefaults"]["recordDeleteAfter"], "168h")
        self.assertTrue(conf["pathDefaults"]["recordPath"].startswith("/recordings/"))
        self.assertEqual(conf["webrtcICEServers2"], [{"url": "turns:turn.example.org", "username": "AUTH_SECRET", "password": ""}])
        self.assertEqual(conf["webrtcAdditionalHosts"], ["100.64.0.7", "media.example.org"])
        svc = out[("Service", "lab-brodec-lab-media")]["spec"]
        self.assertEqual(svc["type"], "LoadBalancer")
        self.assertEqual(svc["loadBalancerSourceRanges"], ["100.64.0.0/10"])
        sp = {(p["port"], p["protocol"]) for p in svc["ports"]}
        self.assertEqual(sp, {(1935, "TCP"), (8890, "UDP"), (8889, "TCP"), (8189, "UDP"), (8189, "TCP"), (8888, "TCP"), (9996, "TCP")})
        np = out[("NetworkPolicy", "lab-brodec-lab")]["spec"]
        ing = {(p["port"], p["protocol"]) for p in np["ingress"][0]["ports"]}
        self.assertEqual(ing, sp)
        self.assertEqual(np["ingress"][0]["from"], [{"ipBlock": {"cidr": "100.64.0.0/10"}}])
        relay = sorted((p["port"], p["protocol"]) for rule in np["egress"] for p in rule["ports"] if p["port"] == 5349)
        self.assertEqual(relay, [(5349, "TCP"), (5349, "UDP")])
        # The API and the hook are never in any Service, policy or forward.
        for port in (9997, 9108):
            self.assertNotIn(port, {p["port"] for p in svc["ports"]})
            self.assertNotIn(port, {p["port"] for p in np["ingress"][0]["ports"]})

    def test_values_carry_no_private_defaults(self):
        text = (CHART / "values.yaml").read_text() + "".join(p.read_text() for p in (CHART / "templates").iterdir())
        for word in ("vault", "secret/", "10.", "192.168.", ".lan", ".local", "hermes", "@b"):
            self.assertNotIn(word, text.lower(), word)


if __name__ == "__main__":
    sys.exit(unittest.main())
