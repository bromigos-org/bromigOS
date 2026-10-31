"""End to end: `bromigos lab network` with a real Headscale and real Tailscale clients, in containers.

    PYTHONPATH=lib:../lib python -m unittest e2e_labnet       (from homelab/, with tests/ on the path)
    BROMIGOS_E2E_DIR=/somewhere/roomy …                       where the lab repo and keys go

Needs Docker (or BROMIGOS_E2E_ENGINE=podman) and the images docker.io/headscale/headscale:0.29.7 and
docker.io/tailscale/tailscale:stable; skipped without them. Not in the package's check (it pulls
images and makes containers). What it proves:

  - setup --on dev applies the same settings, policy and container limits the Quadlet uses
  - join makes one-time codes; connect (reach.join_now) joins real clients with them, with the key in
    a file, never on a command line; a used code is refused in plain words
  - the policy is default deny: lab machines reach each other and servers, a server reaches nothing
  - status shows every device online with its tags; remove takes one off; rotate expires unused codes
  - the Quadlet, applied over SSH to a lab machine (tests/labnet-node: systemd, Podman, sudo), keeps
    its devices across a restart; the Helm chart, applied to a real k3s (docker.io/rancher/k3s), serves
    on the node's own address. Each joins a client. BROMIGOS_E2E_NODES=0 skips these two.
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
BIN = os.path.join(os.path.dirname(HERE), "bin", "bromigos-lab")
ENGINE = os.environ.get("BROMIGOS_E2E_ENGINE", "docker")
TS_IMAGE = "docker.io/tailscale/tailscale:stable"
HS_IMAGE = "docker.io/headscale/headscale:0.29.7"
TAG = f"e2e{os.getpid()}"


def have_images():
    if not shutil.which(ENGINE):
        return False
    for image in (TS_IMAGE, HS_IMAGE):
        if subprocess.run([ENGINE, "image", "inspect", image], capture_output=True).returncode:
            if subprocess.run([ENGINE, "pull", "-q", image], capture_output=True).returncode:
                return False
    return True


@unittest.skipUnless(os.environ.get("BROMIGOS_E2E", "1") != "0" and have_images(), "needs Docker and the images")
class LabNetwork(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        base = os.environ.get("BROMIGOS_E2E_DIR") or None
        cls.dir = tempfile.mkdtemp(prefix="labnet-", dir=base)
        cls.keys = os.path.join(cls.dir, "keys")
        os.makedirs(cls.keys)
        cls.env = dict(os.environ, XDG_CONFIG_HOME=os.path.join(cls.dir, "cfg"),
                       XDG_DATA_HOME=os.path.join(cls.dir, "data"),
                       BROMIGOS_HOMELAB_CONFIG=os.path.join(cls.dir, "cfg", "bromigos", "homelab.toml"),
                       BROMIGOS_REACH_KEYDIR=cls.keys, NO_COLOR="1")
        cls.hs, cls.net = f"hs-{TAG}", f"net-{TAG}"
        cls.clients = {}
        r = cls.lab("setup", "--on", "dev", "--engine", ENGINE, "--container", cls.hs, "--docker-network", cls.net,
                    "--owner", "alice", "--repo", os.path.join(cls.dir, "repo"), "--yes", "--brief")
        assert r.returncode == 0, r.stdout + r.stderr

    @classmethod
    def tearDownClass(cls):
        names = [cls.hs] + list(cls.clients.values())
        subprocess.run([ENGINE, "rm", "-f"] + names, capture_output=True)
        subprocess.run([ENGINE, "volume", "rm", "-f", f"{cls.hs}-data"], capture_output=True)
        subprocess.run([ENGINE, "network", "rm", cls.net], capture_output=True)
        shutil.rmtree(cls.dir, ignore_errors=True)

    @classmethod
    def lab(cls, *args, env=None):
        return subprocess.run([sys.executable, BIN, "network", *args], capture_output=True, text=True,
                              env=dict(cls.env, **(env or {})), timeout=240)

    @classmethod
    def client(cls, name):
        """A Linux machine with Tailscale's daemon, its key folder at the same path as here."""
        c = f"ts-{name}-{TAG}"
        cls.clients[name] = c
        subprocess.run([ENGINE, "run", "-d", "--name", c, "--hostname", name, "--network", cls.net,
                        "--cap-add", "NET_ADMIN", "--cap-add", "NET_RAW", "--device", "/dev/net/tun",
                        "-v", f"{cls.keys}:{cls.keys}:ro", TS_IMAGE, "tailscaled", "--state=mem:"],
                       check=True, capture_output=True)
        for _ in range(30):
            if subprocess.run([ENGINE, "exec", c, "tailscale", "status"], capture_output=True).returncode in (0, 1):
                break
            time.sleep(0.5)
        return c

    def join(self, name, tag):
        r = self.lab("join", "--tag", tag, "--json")
        self.assertEqual(r.returncode, 0, r.stderr)
        doc = json.loads(r.stdout)
        self.assertTrue(doc["bundle"].startswith("bromigos-net:1:"))
        self.assertEqual(doc["tags"], [f"tag:{tag}"])
        c = self.clients.get(name) or self.client(name)
        r = self.lab("connect", doc["bundle"], "--hostname", name, "--json",
                     env={"BROMIGOS_TAILSCALE": f"{ENGINE} exec {c} tailscale"})
        out = json.loads(r.stdout)
        self.assertTrue(out["ok"], out)
        self.assertTrue(out["ip"].startswith("100."), out)
        self.assertEqual(os.listdir(self.keys), [], "the key file is gone after joining")
        return out["ip"], doc

    def ping(self, src, ip):
        for _ in range(8):                         # the policy reaches each client a moment after it joins
            if subprocess.run([ENGINE, "exec", self.clients[src], "ping", "-c", "1", "-W", "2", ip],
                              capture_output=True).returncode == 0:
                return True
            time.sleep(1)
        return False

    def test_network(self):
        a, _ = self.join("lab-a", "lab")
        b, _ = self.join("lab-b", "lab")
        s, used = self.join("server-c", "server")

        # status: three devices, online, tagged
        doc = json.loads(self.lab("status", "--json").stdout)
        self.assertTrue(doc["configured"])
        names = {d["name"]: d for d in doc["devices"]}
        self.assertEqual(set(names), {"lab-a", "lab-b", "server-c"})
        self.assertTrue(all(d["online"] for d in doc["devices"]), doc)
        self.assertEqual(names["lab-a"]["tags"], ["tag:lab"])
        self.assertEqual(names["server-c"]["kind"], "server")
        self.assertEqual(doc["codes"], [], "one-time codes are used up")

        # the two lab machines reach each other; the lab reaches the server; the server reaches nothing
        self.assertTrue(self.ping("lab-a", b), "lab-a → lab-b")
        self.assertTrue(self.ping("lab-b", a), "lab-b → lab-a")
        self.assertTrue(self.ping("lab-a", s), "lab-a → server-c")
        self.assertFalse(self.ping("server-c", a), "server-c → lab-a is denied by default")

        # a used one-time code is refused, in plain words
        c = self.client("late-d")
        r = self.lab("connect", used["bundle"], "--json", env={"BROMIGOS_TAILSCALE": f"{ENGINE} exec {c} tailscale"})
        out = json.loads(r.stdout)
        self.assertFalse(out["ok"])
        self.assertIn("join code", out["words"])

        # remove: the server is off the network
        r = self.lab("remove", "server-c", "--yes", "--json")
        self.assertEqual(r.returncode, 0, r.stderr)
        doc = json.loads(self.lab("status", "--json").stdout)
        self.assertNotIn("server-c", {d["name"] for d in doc["devices"]})

        # rotate: an unused code expires
        self.lab("join", "--json")
        self.assertEqual(len(json.loads(self.lab("status", "--json").stdout)["codes"]), 1)
        r = json.loads(self.lab("rotate", "--yes", "--json").stdout)
        self.assertEqual(len(r["expired_codes"]), 1)
        self.assertEqual(json.loads(self.lab("status", "--json").stdout)["codes"], [])


K3S_IMAGE = "docker.io/rancher/k3s:v1.37.1-k3s1"
NODE_IMAGE = f"bromigos-labnet-node:{TAG}"


def nodes_wanted():
    return os.environ.get("BROMIGOS_E2E_NODES", "1") != "0" and ENGINE == "docker" and have_images()


class Lab(unittest.TestCase):
    """One real lab target on its own network, with one client to join."""
    net = None

    @classmethod
    def base(cls, name):
        cls.dir = tempfile.mkdtemp(prefix=f"labnet-{name}-", dir=os.environ.get("BROMIGOS_E2E_DIR") or None)
        cls.keys = os.path.join(cls.dir, "keys")
        os.makedirs(cls.keys)
        cls.net = f"{name}-{TAG}"
        cls.names = []
        subprocess.run([ENGINE, "network", "create", cls.net], check=True, capture_output=True)
        cls.env = dict(os.environ, XDG_CONFIG_HOME=os.path.join(cls.dir, "cfg"), XDG_DATA_HOME=os.path.join(cls.dir, "data"),
                       BROMIGOS_HOMELAB_CONFIG=os.path.join(cls.dir, "cfg", "bromigos", "homelab.toml"),
                       BROMIGOS_REACH_KEYDIR=cls.keys, NO_COLOR="1")

    @classmethod
    def tearDownClass(cls):
        subprocess.run([ENGINE, "rm", "-f"] + cls.names, capture_output=True)
        subprocess.run([ENGINE, "network", "rm", cls.net], capture_output=True)
        shutil.rmtree(cls.dir, ignore_errors=True)

    @classmethod
    def ip(cls, name):
        return subprocess.run([ENGINE, "inspect", name, "--format", "{{(index .NetworkSettings.Networks \"%s\").IPAddress}}"
                               % cls.net], capture_output=True, text=True, check=True).stdout.strip()

    @classmethod
    def lab(cls, *args, env=None):
        return subprocess.run([sys.executable, BIN, "network", *args], capture_output=True, text=True,
                              env=dict(cls.env, **(env or {})), timeout=600)

    def join_one(self, tag):
        c = f"ts-{self.net}"
        self.names.append(c)
        subprocess.run([ENGINE, "run", "-d", "--name", c, "--network", self.net, "--cap-add", "NET_ADMIN",
                        "--device", "/dev/net/tun", "-v", f"{self.keys}:{self.keys}:ro", TS_IMAGE, "tailscaled",
                        "--state=mem:"], check=True, capture_output=True)
        time.sleep(2)
        doc = json.loads(self.lab("join", "--tag", tag, "--json").stdout)
        out = json.loads(self.lab("connect", doc["bundle"], "--hostname", "client", "--json",
                                  env={"BROMIGOS_TAILSCALE": f"{ENGINE} exec {c} tailscale"}).stdout)
        self.assertTrue(out["ok"], out)
        st = json.loads(self.lab("status", "--json").stdout)
        self.assertEqual([(d["name"], d["kind"], d["online"]) for d in st["devices"]],
                         [("client", "lab" if tag == "lab" else "server", True)])


@unittest.skipUnless(nodes_wanted(), "needs Docker, the images and BROMIGOS_E2E_NODES")
class QuadletOverSSH(Lab):
    @classmethod
    def setUpClass(cls):
        cls.base("quadlet")
        here = os.path.join(HERE, "labnet-node")
        subprocess.run([ENGINE, "build", "-q", "-t", NODE_IMAGE, here], check=True, capture_output=True)
        cls.node = f"node-{TAG}"
        cls.names.append(cls.node)
        subprocess.run([ENGINE, "run", "-d", "--name", cls.node, "--network", cls.net, "--privileged", "--cgroupns=host",
                        "-v", "/sys/fs/cgroup:/sys/fs/cgroup:rw", "-p", "127.0.0.1::22", NODE_IMAGE],
                       check=True, capture_output=True)
        key = os.path.join(cls.dir, "id")
        subprocess.run(["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-f", key], check=True)
        time.sleep(6)
        subprocess.run([ENGINE, "cp", key + ".pub", f"{cls.node}:/home/lab/.ssh/authorized_keys"], check=True)
        subprocess.run([ENGINE, "exec", cls.node, "sh", "-c", "chown lab:lab /home/lab/.ssh/authorized_keys; "
                        "chmod 600 /home/lab/.ssh/authorized_keys"], check=True)
        port = subprocess.run([ENGINE, "port", cls.node, "22/tcp"], capture_output=True, text=True,
                              check=True).stdout.split(":")[-1].strip()
        known = os.path.join(cls.dir, "known_hosts")
        with open(known, "w") as f:
            f.write(subprocess.run(["ssh-keyscan", "-p", port, "127.0.0.1"], capture_output=True, text=True).stdout)
        r = cls.lab("setup", "--on", "quadlet", "--node", "lab@127.0.0.1", "--port", port, "--identity", key,
                    "--known-hosts", known, "--endpoint", "lan", "--lan-address", cls.ip(cls.node), "--owner", "alice",
                    "--repo", os.path.join(cls.dir, "repo"), "--yes", "--brief")
        assert r.returncode == 0, r.stdout + r.stderr

    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        subprocess.run([ENGINE, "rmi", "-f", NODE_IMAGE], capture_output=True)

    def test_a_quadlet_on_a_lab_machine(self):
        active = subprocess.run([ENGINE, "exec", self.node, "systemctl", "is-active", "headscale.service"],
                                capture_output=True, text=True).stdout.strip()
        self.assertEqual(active, "active")
        self.join_one("server")
        subprocess.run([ENGINE, "exec", self.node, "systemctl", "restart", "headscale.service"], check=True)
        time.sleep(8)
        st = json.loads(self.lab("status", "--json").stdout)
        self.assertEqual([d["name"] for d in st["devices"]], ["client"], "its devices survive a restart")


@unittest.skipUnless(nodes_wanted(), "needs Docker, the images and BROMIGOS_E2E_NODES")
class HelmOnK3s(Lab):
    @classmethod
    def setUpClass(cls):
        cls.base("k3s")
        if subprocess.run([ENGINE, "pull", "-q", K3S_IMAGE], capture_output=True).returncode or not shutil.which("helm"):
            raise unittest.SkipTest("needs the k3s image and helm")
        cls.node = f"k3s-{TAG}"
        cls.names.append(cls.node)
        subprocess.run([ENGINE, "run", "-d", "--name", cls.node, "--network", cls.net, "--privileged",
                        "-p", "127.0.0.1::6443", K3S_IMAGE, "server", "--disable", "traefik", "--tls-san", "127.0.0.1"],
                       check=True, capture_output=True)
        for _ in range(80):
            if b" Ready" in subprocess.run([ENGINE, "exec", cls.node, "kubectl", "get", "nodes"], capture_output=True).stdout:
                break
            time.sleep(3)
        port = subprocess.run([ENGINE, "port", cls.node, "6443/tcp"], capture_output=True, text=True,
                              check=True).stdout.split(":")[-1].strip()
        kube = subprocess.run([ENGINE, "exec", cls.node, "cat", "/etc/rancher/k3s/k3s.yaml"], capture_output=True,
                              text=True, check=True).stdout.replace("https://127.0.0.1:6443", f"https://127.0.0.1:{port}")
        cls.kubeconfig = os.path.join(cls.dir, "kubeconfig")
        with open(os.open(cls.kubeconfig, os.O_WRONLY | os.O_CREAT, 0o600), "w") as f:
            f.write(kube)
        r = cls.lab("setup", "--on", "k3s", "--kubeconfig", cls.kubeconfig, "--context", "default", "--endpoint", "lan",
                    "--lan-address", cls.ip(cls.node), "--owner", "alice", "--repo", os.path.join(cls.dir, "repo"),
                    "--yes", "--brief")
        assert r.returncode == 0, r.stdout + r.stderr

    def test_the_chart_on_k3s(self):
        out = subprocess.run(["kubectl", "--kubeconfig", self.kubeconfig, "-n", "lab-network", "get", "svc", "headscale",
                              "-o", "json"], capture_output=True, text=True, check=True).stdout
        svc = json.loads(out)
        self.assertEqual(svc["spec"]["type"], "LoadBalancer")
        self.join_one("lab")


if __name__ == "__main__":
    unittest.main()
