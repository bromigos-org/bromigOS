"""`bromigos lab network` (labnet.py): the reviewed plan for every way it can run, the policy, the
console's records from Headscale's recorded answers, and each verb's Headscale commands.

    PYTHONPATH=lib:../lib python -m unittest test_labnet

The real thing, with Headscale and Tailscale clients in containers: e2e_labnet.py.
"""
import argparse
import base64
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from unittest import mock

from bromigos_homelab import labnet as L
from bromigos_homelab import reach as R

HERE = os.path.dirname(os.path.abspath(__file__))
FIX = os.path.join(HERE, "fixtures", "labnet")
NOW = 1793414000                                  # just after the recordings were made


def fixture(name):
    with open(os.path.join(FIX, name)) as f:
        return json.load(f)


def args(**kw):
    base = dict(on=None, node=None, port=None, identity=None, known_hosts=None, kubeconfig=None, context=None,
                endpoint=None, domain=None, email=None, lan_address=None, public_port=None, derp=None, owner="alice",
                oidc_issuer=None, oidc_client_id=None, oidc_secret_file=None, oidc_allowed_domains=None, name=None,
                dns_domain=None, engine=None, container=None, docker_network=None, server_url=None, image=None)
    base.update(kw)
    return argparse.Namespace(**base)


def hujson(text):
    """The policy without its // comments: plain JSON."""
    return json.loads(re.sub(r"^\s*//.*$", "", text, flags=re.M))


class Options(unittest.TestCase):
    def test_refusals_in_plain_words(self):
        cases = [
            (args(), "Say where Headscale runs"),
            (args(on="quadlet", endpoint="relay", domain="net.example.org"), "--node user@host"),
            (args(on="k3s", kubeconfig="/k", context="c", endpoint="relay", domain="net.example.org"), "relay itself"),
            (args(on="k3s", kubeconfig="/k", endpoint="lan", lan_address="192.168.1.2"), "--context"),
            (args(on="quadlet", node="a@b", endpoint="router", domain="not a domain"), "domain name"),
            (args(on="quadlet", node="a@b", endpoint="lan", lan_address="8.8.8.8"), "your own network"),
            (args(on="quadlet", node="a@b", endpoint="lan", lan_address="192.168.1.2", derp="embedded"), "https"),
            (args(on="quadlet", node="a@b", endpoint="relay", domain="net.example.org", dns_domain="net.example.org"),
             "must differ"),
            (args(on="quadlet", node="a@b", endpoint="relay", domain="net.example.org", oidc_issuer="http://id.example.org"),
             "https://"),
            (args(on="quadlet", node="a@b", endpoint="relay", domain="net.example.org",
                  oidc_issuer="https://id.example.org", oidc_client_id="hs", oidc_secret_file="/s", owner="alice"),
             "email"),
        ]
        for a, words in cases:
            with self.assertRaises(L.NetError, msg=words) as e:
                L.options(a)
            self.assertIn(words, str(e.exception))

    def test_defaults(self):
        o = L.options(args(on="quadlet", node="alice@labbox", endpoint="relay", domain="Net.Example.org."))
        self.assertEqual(o["server_url"], "https://net.example.org")
        self.assertEqual(o["derp"], "embedded", "a relay runs its own DERP")
        o = L.options(args(on="quadlet", node="alice@labbox", endpoint="router", domain="net.example.org"))
        self.assertEqual(o["derp"], "tailscale")
        o = L.options(args(on="dev", owner="Alice B"))
        self.assertEqual((o["endpoint"], o["server_url"], o["owner"]), ("lan", "http://bromigos-headscale-dev:8080", "aliceb"))


class Plans(unittest.TestCase):
    def plan(self, **kw):
        o = L.options(args(**kw))
        return o, L.plan(o, "/repo")

    def test_quadlet_on_a_relay(self):
        o, p = self.plan(on="quadlet", node="alice@relay", endpoint="relay", domain="net.example.org", email="a@example.org")
        self.assertEqual(sorted(p["files"]), ["network/acl.hujson", "network/config.yaml", "network/network.json",
                                              "network/quadlet/headscale-data.volume", "network/quadlet/headscale.container"])
        cfg = p["files"]["network/config.yaml"]
        for line in ('server_url: "https://net.example.org"', 'listen_addr: "0.0.0.0:443"',
                     'tls_letsencrypt_hostname: "net.example.org"', 'tls_letsencrypt_challenge_type: "TLS-ALPN-01"',
                     'acme_email: "a@example.org"', 'path: "/etc/headscale/acl.hujson"', "enabled: true",
                     'base_domain: "lab.home.arpa"', "override_local_dns: false"):
            self.assertIn(line, cfg)
        self.assertNotIn("oidc:", cfg)
        unit = p["files"]["network/quadlet/headscale.container"]
        for line in ("Image=docker.io/headscale/headscale:0.29.7", "Exec=serve", "PublishPort=443:443/tcp",
                     "PublishPort=3478:3478/udp", "ReadOnly=true", "Tmpfs=/var/run/headscale", "NoNewPrivileges=true",
                     "Volume=/etc/headscale:/etc/headscale:ro,Z", "WantedBy=multi-user.target default.target"):
            self.assertIn(line, unit.splitlines())
        words = [w for w, _ in p["steps"]]
        self.assertIn("Install the Podman Quadlet", words)
        self.assertIn("Make you its owner, the local user alice", words)
        self.assertEqual(p["ports"][0], "TCP 443 open on the relay (Headscale's certificate and the network itself)")
        state = json.loads(p["files"]["network/network.json"])
        self.assertEqual(state["target"], {"kind": "ssh", "ssh": "alice@relay", "port": 22})

    def test_lan_quadlet_binds_only_the_lan_address(self):
        o, p = self.plan(on="quadlet", node="alice@labbox", endpoint="lan", lan_address="192.168.1.20")
        self.assertEqual(p["server_url"], "http://192.168.1.20:8080")
        unit = p["files"]["network/quadlet/headscale.container"].splitlines()
        self.assertIn("PublishPort=192.168.1.20:8080:8080/tcp", unit)
        self.assertFalse([u for u in unit if u.startswith("PublishPort=443")])
        self.assertIn('listen_addr: "0.0.0.0:8080"', p["files"]["network/config.yaml"])
        self.assertIn('tls_letsencrypt_hostname: ""', p["files"]["network/config.yaml"])

    def test_k3s_router_with_your_identity_provider(self):
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp)
        secret = os.path.join(tmp, "secret")
        with open(secret, "w") as f:
            f.write("s3cr3t-never-in-the-repo\n")
        o, p = self.plan(on="k3s", kubeconfig=os.path.join(tmp, "kube"), context="lab", endpoint="router",
                         domain="net.example.org", public_port=8443, owner="alice@example.org",
                         oidc_issuer="https://id.example.org/application/o/headscale/", oidc_client_id="headscale",
                         oidc_secret_file=secret, oidc_allowed_domains=["example.org"])
        files = p["files"]
        self.assertIn("network/helm/headscale/Chart.yaml", files)
        self.assertFalse(any("s3cr3t" in t for t in files.values()), "the client secret never enters the repository")
        cfg = files["network/config.yaml"]
        self.assertIn('issuer: "https://id.example.org/application/o/headscale"', cfg)
        self.assertIn('client_secret_path: "/etc/headscale/oidc/client_secret"', cfg)
        self.assertIn('- "alice@example.org"', cfg)
        self.assertIn('- "example.org"', cfg)
        self.assertIn("servicePort: 8443", files["network/helm/headscale/values.yaml"])
        words = [w for w, _ in p["steps"]]
        self.assertTrue(any(w.startswith("Store the client secret as a Kubernetes Secret") for w in words))
        self.assertFalse(any("local user" in w for w in words), "no local users with an identity provider")
        self.assertIn("forward TCP 443 to the lab machine's port 8443", p["ports"][0])
        self.assertTrue(any("/oidc/callback" in n for n in p["notes"]))
        pol = hujson(files["network/acl.hujson"])
        self.assertEqual(pol["groups"]["group:owners"], ["alice@example.org"])

    @unittest.skipUnless(shutil.which("helm"), "needs helm")
    def test_chart_lints_and_renders(self):
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp)
        o, p = self.plan(on="k3s", node="alice@k3sbox", endpoint="router", domain="net.example.org", public_port=8443)
        L.write_files(tmp, p["files"])
        chart = os.path.join(tmp, "network/helm/headscale")
        r = subprocess.run(["helm", "lint", chart], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        out = subprocess.run(["helm", "template", "headscale", chart, "-n", L.NAMESPACE], capture_output=True,
                             text=True, check=True).stdout
        for words in ("kind: Deployment", "readOnlyRootFilesystem: true", "type: LoadBalancer", "port: 8443",
                      "claimName: headscale-data", 'server_url: "https://net.example.org"', '"tag:server"',
                      "checksum/config:", 'image: "docker.io/headscale/headscale:0.29.7"'):
            self.assertIn(words, out)

    def test_policy_is_default_deny(self):
        o, p = self.plan(on="quadlet", node="alice@labbox", endpoint="lan", lan_address="10.0.0.5")
        pol = hujson(p["files"]["network/acl.hujson"])
        self.assertEqual(pol["groups"]["group:owners"], ["alice@"])
        self.assertEqual(set(pol["tagOwners"]), {"tag:lab", "tag:server"})
        self.assertEqual(len(pol["acls"]), 2)
        sources = [s for rule in pol["acls"] for s in rule["src"]]
        self.assertNotIn("tag:server", sources, "servers reach nothing on their own")
        self.assertNotIn("*", sources)
        self.assertFalse(any("*" == d for rule in pol["acls"] for d in rule["dst"]))
        self.assertIn("Default deny", p["files"]["network/acl.hujson"])

    def test_review_shows_every_file_in_full(self):
        o, p = self.plan(on="quadlet", node="alice@labbox", endpoint="lan", lan_address="10.0.0.5")
        out = []
        L.review(p, o, "/repo", out=out.append, changed=list(p["files"]))
        text = "\n".join(out)
        self.assertIn("── network/quadlet/headscale.container", text)
        self.assertIn("PublishPort=10.0.0.5:8080:8080/tcp", text)
        self.assertIn("Access: default deny.", text)
        self.assertIn("1. Make Headscale's settings folder on alice@labbox", text)


class Records(unittest.TestCase):
    def test_devices_from_headscale(self):
        devs = L.devices(fixture("nodes.json"), now=NOW)
        self.assertEqual(len(devs), 1)
        d = devs[0]
        self.assertEqual((d["name"], d["kind"], d["user"], d["online"], d["tags"]),
                         ("box1", "server", "", True, ["tag:server"]))
        self.assertEqual(d["ips"], ["100.64.0.1", "fd7a:115c:a1e0::1"])
        self.assertEqual(d["expires"], "", "server keys don't expire")

    def test_an_offline_owner_device(self):
        node = dict(fixture("nodes.json")[0], online=False, tags=[], given_name="phone",
                    user={"id": 1, "name": "alice"}, last_seen={"seconds": NOW - 7200})
        d = L.devices([node], now=NOW)[0]
        self.assertEqual((d["kind"], d["user"], d["seen_ago"], L.ago(d["seen_ago"])), ("device", "alice", 7200, "2h ago"))

    def test_codes_leave_out_used_and_expired(self):
        cs = L.codes(fixture("preauthkeys.json"), now=NOW)
        self.assertEqual([c["id"] for c in cs], [1, 3])
        self.assertEqual(cs[1]["tags"], ["tag:lab"])
        self.assertEqual([c["id"] for c in L.codes(fixture("preauthkeys.json"), now=NOW + 3 * 86400)], [3])


class FakeControl:
    """Headscale's command, answered from the recordings; every call kept."""

    def __init__(self, state=None):
        self.state = state or {"server_url": "https://net.example.org", "name": "Home", "owner": "alice", "on": "quadlet",
                               "endpoint": "relay", "target": {"kind": "dev", "container": "x"}}
        self.calls = []

    def hs(self, *a, json_out=True):
        self.calls.append(list(a))
        if a[:2] == ("nodes", "list"):
            return fixture("nodes.json")
        if a[:2] == ("preauthkeys", "list"):
            return fixture("preauthkeys.json")
        if a[:2] == ("preauthkeys", "create"):
            return fixture("preauthkey-create.json")
        if a[:2] == ("auth", "register"):
            return {"given_name": "pixel"}
        return {}


class Verbs(unittest.TestCase):
    def test_join_makes_a_bundle(self):
        c = FakeControl()
        doc = L.join("server", "24h", control=c)
        self.assertEqual(c.calls[0], ["preauthkeys", "create", "--tags", "tag:server", "--expiration", "24h"])
        raw = json.loads(base64.urlsafe_b64decode(doc["bundle"][len(R.PREFIX):] + "=="))
        self.assertEqual(raw["server"], "https://net.example.org")
        self.assertEqual(raw["key"], "hskey-auth-FIXTUREfixtureFIXTUREfixture_0123456789")
        self.assertEqual(raw["tags"], ["tag:server"])
        self.assertEqual(doc["expires"], "2026-10-31T03:31:08Z")
        self.assertIn("--login-server https://net.example.org --auth-key hskey-auth-", doc["command"])
        with self.assertRaises(L.NetError):
            L.join("everything", control=c)
        with self.assertRaises(L.NetError):
            L.join("server", "forever", control=c)

    def test_remove_rotate_approve(self):
        c = FakeControl()
        self.assertIn("box1 is off", L.remove("box1", control=c)["words"])
        self.assertEqual(c.calls[-1], ["nodes", "delete", "--identifier", "1", "--force"])
        with self.assertRaises(L.NetError):
            L.remove("nobody", control=c)
        c = FakeControl()
        with mock.patch.object(L.time, "time", return_value=NOW):
            r = L.rotate(control=c)
        self.assertEqual(r["expired_codes"], [1, 3])
        self.assertEqual(c.calls[-2:], [["preauthkeys", "expire", "--id", "1"], ["preauthkeys", "expire", "--id", "3"]])
        r = L.rotate(device="box1", control=c)
        self.assertEqual(c.calls[-1], ["nodes", "expire", "--identifier", "1"])
        r = L.approve("AbCd-1234_x", control=c)
        self.assertEqual(c.calls[-1], ["auth", "register", "--auth-id", "AbCd-1234_x", "--user", "alice"])
        self.assertIn("pixel is on the lab network", r["words"])
        with self.assertRaises(L.NetError):
            L.approve("bad code; rm", control=c)

    def test_status(self):
        with mock.patch.object(L.time, "time", return_value=NOW):
            doc = L.status(FakeControl())
        self.assertEqual(doc["summary"], "1 device, 1 online, 2 unused join codes")
        self.assertEqual(doc["login_server"], "https://net.example.org")

    def test_commands_for_each_adapter(self):
        c = L.Control({"target": {"kind": "dev", "engine": "docker", "container": "hs"}})
        self.assertEqual(c.prefix(), ["docker", "exec", "-i", "hs", "headscale"])
        c = L.Control({"target": {"kind": "kubectl", "kubeconfig": "/k", "context": "lab"}})
        self.assertEqual(c.prefix()[-7:], ["-n", "lab-network", "exec", "-i", "deploy/headscale", "--", "headscale"])
        seen = []
        with mock.patch.object(L, "run", lambda argv, **k: seen.append(argv) or subprocess.CompletedProcess(argv, 0, "[]", "")):
            L.Control({"target": {"kind": "ssh", "ssh": "alice@labbox", "port": 2222}}).hs("nodes", "list")
        self.assertEqual(seen[0][-2], "alice@labbox")
        self.assertEqual(seen[0][-1], "sudo -n podman exec -i headscale headscale nodes list -o json",
                         "one remote command line")
        self.assertIn("2222", seen[0])


class Connection(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp)
        self.toml = os.path.join(self.tmp, "homelab.toml")
        self.env = mock.patch.dict(os.environ, {"BROMIGOS_HOMELAB_CONFIG": self.toml})
        self.env.start()
        self.addCleanup(self.env.stop)

    def test_homelab_toml_block(self):
        with open(self.toml, "w") as f:
            f.write('[[source]]\ntype = "prometheus"\nendpoint = "http://prom:9090"\n')
        L.save_connection("https://net.example.org", "Home", "/repo/network/network.json")
        L.save_connection("https://net2.example.org", "Home", "/repo/network/network.json", bundle="bromigos-net:1:abc")
        L.save_connection("https://net2.example.org", "Home", "/repo/network/network.json")
        with open(self.toml) as f:
            text = f.read()
        import tomllib
        doc = tomllib.loads(text)
        self.assertEqual(doc["source"][0]["type"], "prometheus", "other sources stay")
        self.assertEqual(doc["network"]["login_server"], "https://net2.example.org")
        self.assertEqual(doc["network"]["join_bundle"], "bromigos-net:1:abc", "a kept bundle stays")
        self.assertEqual(text.count("[network]"), 1)
        self.assertEqual(oct(os.stat(self.toml).st_mode & 0o777), "0o600")

    def test_status_without_a_network(self):
        out = io.StringIO()
        with redirect_stdout(out):
            self.assertEqual(L.main(["status", "--json"]), 0)
        self.assertEqual(json.loads(out.getvalue())["configured"], False)

    def test_setup_plan_only_json_writes_the_files(self):
        repo = os.path.join(self.tmp, "repo")
        out = io.StringIO()
        with redirect_stdout(out):
            rc = L.main(["setup", "--on", "quadlet", "--node", "alice@labbox", "--endpoint", "lan",
                         "--lan-address", "192.168.1.20", "--owner", "alice", "--repo", repo, "--plan-only", "--json"])
        self.assertEqual(rc, 0)
        doc = json.loads(out.getvalue())
        self.assertFalse(doc["applied"])
        self.assertEqual(doc["server_url"], "http://192.168.1.20:8080")
        self.assertTrue(os.path.isfile(os.path.join(repo, "network", "quadlet", "headscale.container")))
        self.assertFalse(os.path.exists(self.toml), "a plan connects nothing")
        # a second run with the same answers changes nothing
        out = io.StringIO()
        with redirect_stdout(out):
            L.main(["setup", "--repo", repo, "--plan-only", "--json"])
        self.assertEqual(json.loads(out.getvalue())["changed"], [], "the saved plan's answers are reused")

    def test_dirty_repository_is_refused(self):
        repo = os.path.join(self.tmp, "repo")
        os.makedirs(os.path.join(repo, "network"))
        subprocess.run(["git", "init", "-q", repo], check=True)
        with open(os.path.join(repo, "network", "config.yaml"), "w") as f:
            f.write("my edit\n")
        with self.assertRaises(L.NetError):
            L.write_files(repo, {"network/config.yaml": "new\n"})


class QR(unittest.TestCase):
    TEXT = R.encode("https://net.example.org", "hskey-auth-" + "a" * 40)

    def square(self, lines):
        visible = [re.sub(r"\x1b\[[0-9;]*m", "", x) for x in lines]     # the themed component colours each cell
        self.assertGreater(len(visible), 10)
        self.assertEqual(len({len(x) for x in visible}), 1, "a square of half blocks")

    def test_qr_lines(self):
        """The shared themed component (bromigos_qr) when it's installed, else plain half blocks."""
        try:
            import qrcode  # noqa: F401
        except ImportError:
            self.skipTest("needs python-qrcode")
        self.square(L.qr_lines(self.TEXT))

    def test_plain_half_blocks_without_the_themed_component(self):
        try:
            import qrcode  # noqa: F401
        except ImportError:
            self.skipTest("needs python-qrcode")
        with mock.patch.dict(sys.modules, {"bromigos_qr": None}):
            lines = L.qr_lines(self.TEXT)
        self.square(lines)
        self.assertFalse(any("\x1b" in x for x in lines))


if __name__ == "__main__":
    unittest.main()
