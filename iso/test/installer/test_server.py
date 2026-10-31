"""bromigOS Server's steps in the installers (server.py, server_tui.py, server_gui.py,
server_apply.py; docs/server.md): the presets come from the data file, what's typed is
checked, GitHub's keys come from a stub server (never the network), keys only is the
default, RAID1 needs two disks, each role's answers and plan, the update window and mode in
server.toml, the answer files' [server] table, answers.py's configuration, server_apply's
files, and every new step driven and drawn in the text installer at 120×35 and 80×24.

  python -m unittest discover -s iso/test/installer -p 'test_server.py'
"""
import asyncio
import http.server
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import unittest

HERE = os.path.dirname(os.path.realpath(__file__))
sys.path.insert(0, HERE)
import test_tui  # noqa: E402,F401  (the fake store, back end and environment)
SERVER_PROBE = os.path.join(HERE, "fixtures/probe-server.json")
sys.path.insert(0, os.path.join(HERE, "../../../homelab/lib"))      # bromigos_homelab.reach (the lab network's)
ENV = {"BROMIGOS_HOMELAB_LIB": os.path.join(HERE, "../../../homelab/lib"),
       "BROMIGOS_PROVISION_CATALOGUE": os.path.join(HERE, "fixtures", "provision-catalogue.toml"),   # the stand-in's rules
       "BROMIGOS_INSTALLER_TPM": "0", "BROMIGOS_INSTALLER_UPS": "0", "BROMIGOS_INSTALLER_NVIDIA": "0"}
_SAVED = {}


def setUpModule():
    """This module's environment, for its own tests only (the other modules' run after, as before)."""
    for k, v in ENV.items():
        _SAVED[k] = os.environ.get(k)
        os.environ[k] = v
    from bromigos_installer import provision
    provision.load(reload=True)


def tearDownModule():
    for k, v in _SAVED.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v
    from bromigos_installer import provision
    provision._ENGINE = None
    provision.load(reload=True)
from bromigos_installer import backend, common, server  # noqa: E402

LIB = test_tui.LIB
SHARE = test_tui.SHARE
EXAMPLES = os.path.join(SHARE, "server", "examples")
KEY = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIExampleKeyForTheInstallerTestsOnly tester@lab"
KEY2 = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIOctocatsExampleKeyFromGitHubForTheTests octocat"


class ServerProbe:
    """The recorded server's disks (fixtures/probe-server.json) for the tests that need them."""

    def setUp(self):
        self._probe = os.environ.get("BROMIGOS_INSTALLER_PROBE")
        os.environ["BROMIGOS_INSTALLER_PROBE"] = SERVER_PROBE
        super().setUp() if hasattr(super(), "setUp") else None

    def tearDown(self):
        os.environ["BROMIGOS_INSTALLER_PROBE"] = self._probe


def answers(role="plain", **server_keys):
    """A server's answers as the installers hold them, Continue pressed on every step."""
    a = common.defaults()
    a.update(edition="server", disk="/dev/nvme0n1", mode="erase", user="admin", password="tester-pass",
             password2="tester-pass", hostname="srv-1", ssh_keys=[KEY], locale="en_US", timezone="UTC", keyboard="us")
    server.pick_role(a, role)
    s = server.srv(a)
    s.update(interface="enp3s0", unlock="passphrase")
    s.update(server_keys)
    return a


class Presets(unittest.TestCase):
    def test_roles_from_the_data_file(self):
        p = server.presets(reload=True)
        self.assertTrue(p["_source"].endswith("server/presets.toml"))
        self.assertEqual([r["id"] for r in server.roles()], ["lab", "storage", "home", "games", "media", "plain"])
        services = {x["id"] for x in p["services"]}
        apps = {x["id"] for x in p["apps"]}
        for r in server.roles():
            for k in ("title", "summary", "hint", "glyph"):
                self.assertTrue(r.get(k), (r["id"], k))
            self.assertLessEqual(set(r.get("services_on", [])), services, r["id"])
            self.assertLessEqual(set(r.get("apps_on", [])), apps, r["id"])
            for fw in r.get("firewall", []) + (r.get("with_lab") or {}).get("firewall", []):
                self.assertIn(fw, p["firewall"], r["id"])
        for x in p["services"] + p["apps"]:
            for fw in x.get("firewall", []):
                self.assertIn(fw, p["firewall"], x["id"])
        self.assertTrue(8 <= len(p["apps"]) <= 12)
        self.assertEqual(p["base"]["kernel"], "linux-lts")
        self.assertEqual(p["base"]["fallback_kernel"], "linux")
        self.assertEqual(p["updates"]["window"], "03:00-05:00")
        self.assertEqual(p["updates"]["modes"], ["auto", "download", "off"])
        self.assertEqual(p["updates"]["channel"], "live")
        self.assertIn("cockpit-packagekit", next(x for x in p["services"] if x["id"] == "cockpit")["never"])
        self.assertFalse(next(x for x in p["services"] if x["id"] == "cockpit").get("on"))
        self.assertIn("docker", p["roles"][3]["with_lab"]["packages"])
        self.assertNotIn("docker", p["base"]["packages"])
        self.assertEqual(p["roles"][0].get("lab_account"), True)
        self.assertFalse(any(r.get("lab_account") for r in p["roles"][1:]))

    def test_presets_are_data(self):
        """A role added to the file shows up, with its services: nothing in the code names the roles."""
        import tomllib
        with open(server.preset_path(), "rb") as f:
            text = f.read().decode()
        d = tempfile.mkdtemp()
        path = os.path.join(d, "presets.toml")
        with open(path, "w") as f:
            f.write(text + '\n[[roles]]\nid = "mediabox"\ntitle = "Media box"\nsummary = "Films."\nhint = "Big disks."\n'
                           'glyph = "drive"\npackages = ["mpv"]\nfirewall = ["web"]\nservices_on = ["front-door"]\n')
        tomllib.loads(open(path).read())
        os.environ["BROMIGOS_SERVER_PRESETS"] = path
        try:
            server.presets(reload=True)
            self.assertIn("mediabox", [r["id"] for r in server.roles()])
            a = answers("mediabox")
            p = server.plan(a)
            self.assertIn("mpv", p["packages"], server.roles_of(server.srv(a)))
            self.assertIn("web", p["firewall"])
        finally:
            del os.environ["BROMIGOS_SERVER_PRESETS"]
            server.presets(reload=True)

    def test_every_package_is_named_like_arch(self):
        import re
        p = server.presets()
        names = list(p["base"]["packages"]) + [x for r in p["roles"] for x in r.get("packages", []) + r.get("gpu_packages", [])
                                               + (r.get("with_lab") or {}).get("packages", [])]
        names += [x for s in p["services"] for x in s.get("packages", [])]
        for n in names:
            self.assertRegex(n, r"^[a-z0-9][a-z0-9@._+-]*$")
            self.assertFalse(n.endswith("-git") or n.endswith("-bin"), f"{n}: an AUR-style name")


class Checks(ServerProbe, unittest.TestCase):
    def test_static_address(self):
        self.assertIsNone(server.check_address("192.0.2.40"))
        self.assertIsNone(server.check_address("2001:db8::40"))
        for bad in ("", "192.0.2", "300.1.1.1", "server", "127.0.0.1", "224.0.0.1", "0.0.0.0", "169.254.1.1"):
            self.assertIsNotNone(server.check_address(bad), bad)

    def test_prefix(self):
        self.assertIsNone(server.check_prefix("24", "192.0.2.40"))
        self.assertIsNone(server.check_prefix("/16", "192.0.2.40"))
        self.assertEqual(server.prefix_from("255.255.255.0"), "24")
        self.assertEqual(server.prefix_from("/20"), "20")
        self.assertIsNotNone(server.check_prefix("33", "192.0.2.40"))
        self.assertIsNotNone(server.check_prefix("abc", "192.0.2.40"))
        self.assertIn("network's own address", server.check_prefix("24", "192.0.2.0"))
        self.assertIsNone(server.check_prefix("64", "2001:db8::40"))

    def test_gateway(self):
        self.assertIsNone(server.check_gateway("192.0.2.1", "192.0.2.40", "24"))
        self.assertIn("isn't on 192.0.2.0/24", server.check_gateway("198.51.100.1", "192.0.2.40", "24"))
        self.assertIn("own", server.check_gateway("192.0.2.40", "192.0.2.40", "24"))
        self.assertIsNotNone(server.check_gateway("", "192.0.2.40", "24"))
        self.assertIsNotNone(server.check_gateway("router", "192.0.2.40", "24"))

    def test_dns(self):
        self.assertIsNone(server.check_dns("192.0.2.1 9.9.9.9"))
        self.assertIsNone(server.check_dns("192.0.2.1,2001:db8::1"))
        self.assertEqual(server.split_dns("192.0.2.1, 9.9.9.9;1.1.1.1"), ["192.0.2.1", "9.9.9.9", "1.1.1.1"])
        self.assertIsNotNone(server.check_dns(""))
        self.assertIn("dns.example", server.check_dns("192.0.2.1 dns.example"))

    def test_hostname_and_vlan(self):
        a = answers()
        a["hostname"] = "bad name"
        self.assertIn("no spaces", server.check(("network"), a))
        a["hostname"] = "srv-1"
        self.assertIsNone(server.check("network", a))
        self.assertIsNone(server.check_vlan(""))
        self.assertIsNone(server.check_vlan("20"))
        self.assertIsNotNone(server.check_vlan("4095"))

    def test_static_network_needs_every_field(self):
        a = answers(method="static", address="192.0.2.40", prefix="24", gateway="198.51.100.1", dns="192.0.2.1")
        self.assertIn("isn't on", server.check("network", a))
        server.srv(a)["gateway"] = "192.0.2.1"
        self.assertIsNone(server.check("network", a))
        server.srv(a)["dns"] = ""
        self.assertIn("name server", server.check("network", a))

    def test_admin_may_be_admin(self):
        self.assertIsNone(server.check_admin("admin"))
        self.assertIsNotNone(common.check_username("admin"))       # the desktop's About you still refuses it
        self.assertIsNotNone(server.check_admin("root"))

    def test_keys_only_is_the_default_and_needs_a_key(self):
        a = answers()
        self.assertEqual(server.srv(a)["ssh_mode"], "keys")
        a["ssh_keys"] = []
        self.assertIn("Keys only needs a key", server.check("access", a))
        server.srv(a)["ssh_mode"] = "password"
        self.assertIsNone(server.check("access", a))
        server.srv(a)["ssh_mode"] = "off"
        self.assertIsNone(server.check("access", a))
        doc = common.backend_answers(answers(), {"options": {}})
        self.assertTrue(doc["ssh"])
        self.assertFalse(doc["ssh_password"])
        self.assertFalse(doc["server"]["access"]["password_login"])

    def test_github_keys_must_be_confirmed(self):
        a = answers(github="octocat", github_keys=[KEY2], github_ok=False)
        self.assertIn("Get keys", server.check("access", a))
        server.srv(a)["github_ok"] = True
        self.assertIsNone(server.check("access", a))
        self.assertEqual(server.all_keys(a), [KEY, KEY2])

    def test_raid1_needs_two_disks(self):
        probe = backend.probe()
        a = answers("storage", data_disks=["/dev/sda"], data_layout="raid1")
        self.assertIn("two or more", server.check("storage", a, probe))
        server.srv(a)["data_disks"] = ["/dev/sda", "/dev/sdb"]
        self.assertIsNone(server.check("storage", a, probe))
        server.srv(a)["data_disks"] = ["/dev/sda", "/dev/nvme0n1"]           # the system disk isn't a data disk
        self.assertIn("two or more", server.check("storage", a, probe))
        self.assertEqual([d["path"] for d in server.data_disks(probe, a)], ["/dev/sda", "/dev/sdb", "/dev/sdc"])
        self.assertEqual(server.erases(probe["disks"][3]), "Linux files (ext4, media)")

    def test_unlock_without_a_chip(self):
        a = answers(unlock=None)
        self.assertEqual(server.unlock_choices(False), ["passphrase", "none"])
        self.assertIn("Choose how", server.check("unlock", a))
        server.srv(a)["unlock"] = "tpm"                      # no chip here: not a choice
        self.assertIsNotNone(server.check("unlock", a))
        server.srv(a)["unlock"] = "none"
        self.assertIsNone(server.check("unlock", a))
        self.assertFalse(a["encrypt"])
        os.environ["BROMIGOS_INSTALLER_TPM"] = "1"
        try:
            server.srv(a)["unlock"] = "tpm"
            self.assertIsNone(server.check("unlock", a))
            self.assertTrue(a["encrypt"])
        finally:
            os.environ["BROMIGOS_INSTALLER_TPM"] = "0"

    def test_update_window_and_mode(self):
        self.assertIsNone(server.check_window("03:00-05:00"))
        self.assertIsNotNone(server.check_window("3-5"))
        self.assertIsNotNone(server.check_window("03:00-03:00"))
        self.assertEqual(server.window_calendar("03:00-05:00"), ("*-*-* 03:00:00", "90min"))
        self.assertEqual(server.window_calendar("22:00-00:00"), ("*-*-* 22:00:00", "90min"))
        self.assertEqual(server.window_words("03:00-05:00"), "3 AM to 5 AM")
        for mode in ("auto", "download", "off"):
            a = answers(update_mode=mode, update_window="01:00-03:00")
            text = server.server_toml(server.plan(a))
            import tomllib
            t = tomllib.loads(text)
            self.assertEqual(t["updates"]["mode"], mode)
            self.assertEqual(t["updates"]["window"], "01:00-03:00")
            self.assertEqual(t["updates"]["auto"], mode == "auto")
            self.assertEqual(t["updates"]["channel"], "live")
            doc = common.backend_answers(a, {"options": {}})
            self.assertEqual(doc["auto_updates"], mode != "off")


class GitHub(unittest.TestCase):
    """GitHub's keys, from a stub HTTP server on this machine (no real network)."""

    @classmethod
    def setUpClass(cls):
        class H(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                body = {"/octocat.keys": KEY2 + "\nssh-rsa AAAAB3NzaC1yc2EAAAADAQABAAABAQCexampleRSAkeyForTests\n",
                        "/nokeys.keys": "", "/junk.keys": "<html>not keys</html>\n"}.get(self.path)
                if body is None:
                    self.send_response(404)
                    self.end_headers()
                    return
                self.send_response(200)
                self.end_headers()
                self.wfile.write(body.encode())

            def log_message(self, *a):
                pass
        cls.httpd = http.server.HTTPServer(("127.0.0.1", 0), H)
        threading.Thread(target=cls.httpd.serve_forever, daemon=True).start()
        cls.base = f"http://127.0.0.1:{cls.httpd.server_port}"
        os.environ["BROMIGOS_GITHUB_KEYS_URL"] = cls.base

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        del os.environ["BROMIGOS_GITHUB_KEYS_URL"]

    def test_keys_and_fingerprints(self):
        keys, problem = server.fetch_github_keys("octocat")
        self.assertIsNone(problem)
        self.assertEqual(len(keys), 2)
        kind, fp, comment = server.fingerprint(keys[0])
        self.assertEqual((kind, comment), ("ED25519", "octocat"))
        self.assertTrue(fp.startswith("SHA256:"))
        if shutil.which("ssh-keygen"):
            with tempfile.NamedTemporaryFile("w", suffix=".pub", delete=False) as f:
                f.write(KEY2 + "\n")
            r = subprocess.run(["ssh-keygen", "-lf", f.name], capture_output=True, text=True)
            os.unlink(f.name)
            if r.returncode == 0:                    # the stand-in key isn't a real curve point: ssh-keygen may refuse it
                self.assertIn(fp, r.stdout)

    def test_problems_in_plain_words(self):
        self.assertIn("no GitHub user called ghost", server.fetch_github_keys("ghost")[1])
        self.assertIn("no SSH keys on GitHub", server.fetch_github_keys("nokeys")[1])
        self.assertIn("no SSH keys on GitHub", server.fetch_github_keys("junk")[1])
        self.assertIn("isn't a GitHub user name", server.fetch_github_keys("bad name!")[1])
        self.assertIn("can't be reached", server.fetch_github_keys("octocat", base="http://127.0.0.1:9")[1])

    def test_answer_file_fetches_them(self):
        a, problems = self.read('[install]\nedition = "server"\ndisk = "/dev/nvme0n1"\nmode = "erase"\nuser = "admin"\n'
                                'password = "pw-pw"\n\n[server]\nrole = "home"\ngithub = "octocat"\nunlock = "none"\n')
        self.assertEqual(problems, [])
        self.assertEqual(len(server.all_keys(a)), 2)

    def read(self, text):
        d = tempfile.mkdtemp()
        p = os.path.join(d, "install.toml")
        with open(p, "w") as f:
            f.write(text)
        return common.read_answer_file(p)


class Roles(unittest.TestCase):
    def doc(self, role, **kw):
        a = answers(role, **kw)
        return common.backend_answers(a, {"options": {}})

    def test_each_role(self):
        for role in ("lab", "storage", "home", "games", "plain"):
            with self.subTest(role=role):
                doc = self.doc(role)
                p = doc["server"]
                self.assertFalse(doc["desktop"])
                self.assertEqual(p["role"], role)
                self.assertEqual(p["kernels"], ["linux-lts", "linux"])
                for pkg in ("sshguard", "smartmontools", "restic", "avahi", "wireguard-tools", "tailscale", "apparmor"):
                    self.assertIn(pkg, p["packages"])
                self.assertIn("ssh", p["firewall"])
                self.assertFalse(p["access"]["tailscale"] or p["access"]["wireguard"])
                self.assertNotIn("tailscaled.service", p["services"])
                self.assertIn("tailscaled.service", p["off_services"])
                self.assertEqual(p["access"]["lab_account"], role == "lab")
                self.assertEqual("docker" in p["packages"], False)
                self.assertNotIn("cockpit", p["packages"])
                self.assertEqual(p["sysctl"]["kernel.kptr_restrict"], 2)
                self.assertEqual(p["journald"]["SystemMaxUse"], "1G")
                self.assertIn("apparmor", p["lsm"])

    def test_lab_node(self):
        p = self.doc("lab", lab_key="ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAILabWorkstationKeyForTheTests lab@ws",
                     lab_same_keys=False)["server"]
        self.assertIn("lab-cluster", p["firewall"])
        self.assertEqual(p["access"]["lab_keys"], ["ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAILabWorkstationKeyForTheTests lab@ws"])
        self.assertEqual(p["sysctl"]["fs.inotify.max_user_instances"], 512)
        self.assertIn("k3s", p["health"])
        self.assertTrue(p["updates"]["cluster_reboots"])
        self.assertNotIn("nvidia-open-dkms", p["packages"])           # no NVIDIA card here
        os.environ["BROMIGOS_INSTALLER_NVIDIA"] = "1"
        try:
            p = self.doc("lab")["server"]
            self.assertIn("nvidia-open-dkms", p["packages"])
            self.assertIn("linux-lts-headers", p["packages"])
        finally:
            os.environ["BROMIGOS_INSTALLER_NVIDIA"] = "0"

    def test_storage(self):
        p = self.doc("storage", data_disks=["/dev/sda", "/dev/sdb"], data_layout="raid1")["server"]
        self.assertEqual(p["storage"], {"disks": ["/dev/sda", "/dev/sdb"], "layout": "raid1", "mount": "/srv/data",
                                        "shares": ["smb", "nfs"], "timeline": True})
        self.assertIn("samba", p["packages"])
        self.assertIn("smb.service", p["services"])
        self.assertIn("btrfs-scrub@srv-data.timer", p["services"])
        self.assertTrue({"smb", "nfs"} <= set(p["firewall"]))
        one = self.doc("storage", data_disks=["/dev/sda"], data_layout="raid1")["server"]["storage"]
        self.assertEqual(one["layout"], "single")

    def test_home_services(self):
        p = self.doc("home")["server"]
        self.assertIn("caddy", p["packages"])
        self.assertIn("web", p["firewall"])
        self.assertTrue({"photos", "start-page", "ingress"} <= set(p["provision"]), p["provision"])

    def test_game_server_without_a_lab_runs_podman(self):
        p = self.doc("games")["server"]
        self.assertFalse(p["lab"])
        self.assertIn("minecraft", p["provision"])
        self.assertIn("podman-docker", p["packages"])
        self.assertNotIn("docker", p["packages"])
        self.assertIn("games", p["firewall"])

    def test_game_server_with_the_lab_joins_pelican_on_docker(self):
        a = answers("games")
        server.srv(a)["services"]["pelican-wings"] = True
        server.srv(a).update(pelican_url="https://panel.lab.example", registry_mirror="https://registry.lab.example")
        p = common.backend_answers(a, {"options": {}})["server"]
        self.assertTrue(p["lab"] and p["docker"])
        self.assertIn("docker", p["packages"])
        self.assertNotIn("podman-docker", p["packages"])
        self.assertIn("docker.service", p["services"])
        self.assertIn("wings", p["firewall"])
        self.assertNotIn("minecraft", p["apps"])
        self.assertEqual(p["games"]["pelican_url"], "https://panel.lab.example")
        self.assertIn("Pelican", json.dumps(server.presets()["roles"][3]))
        self.assertNotIn("terodactyl", json.dumps(server.presets()))

    def test_cockpit_is_opt_in_and_lan_only(self):
        a = answers("home")
        server.srv(a)["services"]["cockpit"] = True
        p = common.backend_answers(a, {"options": {}})["server"]
        self.assertIn("cockpit", p["packages"])
        self.assertNotIn("cockpit-packagekit", p["packages"])
        self.assertEqual(p["firewall_rules"]["cockpit"]["from"], "lan")

    def test_remote_access_only_when_chosen(self):
        p = self.doc("plain", tailscale=True, wireguard=True)["server"]
        self.assertIn("tailscaled.service", p["services"])
        self.assertTrue(p["access"]["wireguard"])

    def test_summary_and_ssh_line(self):
        a = answers("home", method="static", address="192.0.2.40", prefix="24", gateway="192.0.2.1", dns="192.0.2.1")
        rows, warn = common.summary(a, {"model": "Disk", "size_text": "1 TB", "partitions": [], "options": {}})
        keys = [k for k, _ in rows]
        for k in ("Role", "Server name", "Network", "Admin", "Sign-in", "Data disks", "Disk encryption", "Updates", "Services"):
            self.assertIn(k, keys)
        self.assertEqual(server.ssh_line(a), "ssh admin@192.0.2.40")
        self.assertEqual(server.qr_payload(a), "ssh://admin@192.0.2.40")
        self.assertIn("3 AM to 5 AM", dict(rows)["Updates"])


class AnswerFiles(unittest.TestCase):
    def test_every_example_reads_clean(self):
        from bromigos_installer import provision as PV
        os.environ["BROMIGOS_PROVISION_CATALOGUE"] = os.path.join(HERE, "../../../homelab/share/provision-catalogue.toml")
        PV.load(reload=True)                  # the examples name the lab engine's own items
        self.addCleanup(lambda: (os.environ.__setitem__("BROMIGOS_PROVISION_CATALOGUE",
                                                        os.path.join(HERE, "fixtures", "provision-catalogue.toml")),
                                 PV.load(reload=True)))
        os.environ["BROMIGOS_GITHUB_KEYS_URL"] = "http://127.0.0.1:9"
        os.environ["BROMIGOS_INSTALLER_TPM"] = "1"           # lab.toml asks for the security chip
        try:
            for name in sorted(os.listdir(EXAMPLES)):
                with self.subTest(example=name):
                    a, problems = common.read_answer_file(os.path.join(EXAMPLES, name))
                    s = server.srv(a)
                    want = {"lab-games-storage": ["lab", "games", "storage"]}.get(name[:-5], [name[:-5]])
                    self.assertEqual(server.roles_of(s), want)
                    if name == "home.toml":          # its GitHub name can't be fetched here: said plainly
                        self.assertTrue(any("can't be reached" in p for p in problems), problems)
                        continue
                    self.assertEqual(problems, [], name)
                    doc = common.backend_answers(a, {"options": {}})
                    self.assertEqual(doc["server"]["role"], s["role"])
        finally:
            del os.environ["BROMIGOS_GITHUB_KEYS_URL"]
            os.environ["BROMIGOS_INSTALLER_TPM"] = "0"

    def test_tpm_asked_for_without_one(self):
        _, problems = common.read_answer_file(os.path.join(EXAMPLES, "lab.toml"))
        self.assertTrue(any("Choose how the disk unlocks" in p for p in problems), problems)

    def test_storage_example(self):
        a, problems = common.read_answer_file(os.path.join(EXAMPLES, "storage.toml"))
        p = server.plan(a)
        self.assertEqual((p["storage"]["layout"], p["storage"]["disks"]), ("raid1", ["/dev/sda", "/dev/sdb"]))
        self.assertEqual(p["network"], {"interface": "enp3s0", "method": "static", "address": "192.0.2.10", "prefix": 24,
                                        "gateway": "192.0.2.1", "dns": ["192.0.2.1"], "wake_on_lan": True, "vlan": None, "bond": []})
        self.assertEqual(p["updates"]["mode"], "download")

    def test_problems_said_plainly(self):
        d = tempfile.mkdtemp()
        p = os.path.join(d, "install.toml")
        with open(p, "w") as f:
            f.write('[install]\nedition = "server"\ndisk = "/dev/nvme0n1"\nmode = "erase"\nuser = "admin"\npassword = "pw-pw"\n'
                    '[server]\nrole = "nas"\n')
        _, problems = common.read_answer_file(p)
        self.assertTrue(any("role \"nas\"" in x for x in problems), problems)
        with open(p, "w") as f:
            f.write('[install]\nedition = "server"\ndisk = "/dev/nvme0n1"\nmode = "erase"\nuser = "admin"\npassword = "pw-pw"\n'
                    '[server]\nrole = "storage"\ndata_disks = ["/dev/sda"]\ndata_layout = "raid1"\nmethod = "static"\n'
                    'address = "192.0.2.10"\nprefix = 24\ngateway = "198.51.100.1"\ndns = ["192.0.2.1"]\nunlock = "none"\n'
                    'colour = "green"\n')
        _, problems = common.read_answer_file(p)
        text = " ".join(problems)
        self.assertIn("RAID1 needs two", text)
        self.assertIn("isn't on 192.0.2.0/24", text)
        self.assertIn("server.colour", text)
        self.assertIn("keys only needs a key", text)

    def test_round_trip(self):
        a = answers("storage", data_disks=["/dev/sda", "/dev/sdb"], data_layout="raid1", method="static",
                    address="192.0.2.10", prefix="24", gateway="192.0.2.1", dns="192.0.2.1", update_window="01:00-03:00")
        text = common.answers_toml(dict(a, password="pw-pw"), secrets=True)
        self.assertIn("[server]", text)
        d = tempfile.mkdtemp()
        p = os.path.join(d, "install.toml")
        with open(p, "w") as f:
            f.write(text)
        b, problems = common.read_answer_file(p)
        self.assertEqual(problems, [])
        self.assertEqual(server.plan(b)["storage"], server.plan(a)["storage"])
        self.assertEqual(server.plan(b)["network"], server.plan(a)["network"])
        self.assertEqual(server.plan(b)["updates"], server.plan(a)["updates"])

    def test_yaml_dotted_keys(self):
        d = tempfile.mkdtemp()
        p = os.path.join(d, "install.yaml")
        with open(p, "w") as f:
            f.write("edition: server\ndisk: /dev/nvme0n1\nmode: erase\nuser: admin\npassword: pw-pw\nserver.role: lab\n"
                    "server.ssh_mode: password\nserver.unlock: none\n")
        a, problems = common.read_answer_file(p)
        self.assertEqual(problems, [])
        self.assertEqual(server.srv(a)["role"], "lab")
        self.assertTrue(a["ssh_password"])


class ArchinstallConfig(unittest.TestCase):
    """answers.py's configuration for each role: linux-lts first, linux the spare, the role's packages."""

    def run_answers(self, role, online, **kw):
        a = answers(role, **kw)
        doc = common.backend_answers(a, {"options": {}})
        doc["disk"] = "/dev/vda"
        d = tempfile.mkdtemp()
        path = os.path.join(d, "answers.json")
        with open(path, "w") as f:
            json.dump(doc, f)
        argv = [sys.executable, os.path.join(LIB, "answers.py"), "--answers", path, "--out", os.path.join(d, "out"),
                "--template", os.path.join(SHARE, "archinstall.json"), "--disk-bytes", str(64 * 1024 ** 3), "--firmware", "uefi"]
        env = dict(os.environ, PYTHONPATH=LIB, BROMIGOS_ISO_ONLINE="1" if online else "")
        if online:
            doc["online"] = True
            with open(path, "w") as f:
                json.dump(doc, f)
        r = subprocess.run(argv, capture_output=True, text=True, env=env)
        self.assertEqual(r.returncode, 0, r.stderr)
        with open(os.path.join(d, "out", "config.json")) as f:
            return json.load(f)

    def test_online_every_role(self):
        for role in ("lab", "storage", "home", "games", "plain"):
            with self.subTest(role=role):
                cfg = self.run_answers(role, True)
                self.assertEqual(cfg["kernels"], ["linux-lts", "linux"])
                self.assertIn("sshguard", cfg["packages"])
                self.assertNotIn("sshguard.service", cfg["services"])      # enabled later, once it's installed
                self.assertIn("grub-btrfsd", cfg["services"])

    def test_offline_takes_what_the_stick_has(self):
        cfg = self.run_answers("home", False)
        self.assertEqual(cfg["kernels"], ["linux"])              # the stand-in store has no linux-lts
        self.assertNotIn("caddy", cfg["packages"])               # nor caddy: it comes later

    def test_docker_replaces_podman_docker(self):
        a = answers("games")
        server.srv(a)["services"]["pelican-wings"] = True
        from bromigos_installer import server_apply
        cfg = server_apply.archinstall({"packages": ["podman-docker", "openssh"]}, server.plan(a), lambda x: True, False)
        self.assertIn("docker", cfg["packages"])
        self.assertNotIn("podman-docker", cfg["packages"])


class Apply(unittest.TestCase):
    """server_apply.py's files in a stand-in root (--dry-run: nothing is run)."""

    def apply(self, role, **kw):
        from bromigos_installer import server_apply
        a = answers(role, **kw)
        doc = common.backend_answers(a, {"options": {}})
        root = tempfile.mkdtemp()
        for p, text in (("etc/default/grub", 'GRUB_DEFAULT=0\nGRUB_CMDLINE_LINUX_DEFAULT="loglevel=3 quiet"\n'
                                             'GRUB_CMDLINE_LINUX="cryptdevice=PARTUUID=abcd:root root=/dev/mapper/root"\n'),
                        ("etc/fstab", "# fstab\n"), ("etc/nsswitch.conf", "hosts: mymachines resolve [!UNAVAIL=return] files myhostname dns\n"),
                        ("etc/mkinitcpio.conf", "HOOKS=(base udev autodetect microcode modconf kms keyboard keymap consolefont "
                                                "block encrypt filesystems fsck grub-btrfs-overlayfs)\n"),
                        ("etc/pacman.conf", "[options]\nHoldPkg = pacman glibc\n")):
            os.makedirs(os.path.join(root, os.path.dirname(p)), exist_ok=True)
            with open(os.path.join(root, p), "w") as f:
                f.write(text)
        ap = server_apply.Apply(doc, root, "admin", dry=True, online=False)
        ap.all()
        return root, ap

    def read(self, root, p):
        with open(os.path.join(root, p.lstrip("/"))) as f:
            return f.read()

    def test_static_network_and_keys_only(self):
        root, ap = self.apply("home", method="static", address="192.0.2.40", prefix="24", gateway="192.0.2.1",
                              dns="192.0.2.1 9.9.9.9")
        nm = self.read(root, "/etc/NetworkManager/system-connections/bromigos-server.nmconnection")
        self.assertIn("interface-name=enp3s0", nm)
        self.assertIn("address1=192.0.2.40/24,192.0.2.1", nm)
        self.assertIn("dns=192.0.2.1;9.9.9.9;", nm)
        self.assertIn("wake-on-lan=64", nm)
        self.assertEqual(oct(os.stat(os.path.join(root, "etc/NetworkManager/system-connections/bromigos-server.nmconnection")).st_mode)[-3:], "600")
        self.assertIn("PasswordAuthentication no", self.read(root, "/etc/ssh/sshd_config.d/01-bromigos-keys-only.conf"))
        lim = self.read(root, "/etc/ssh/sshd_config.d/20-bromigos-server-limits.conf")
        self.assertIn("MaxAuthTries 3", lim)
        self.assertIn("AllowGroups wheel bromigos-ssh", lim)
        self.assertIn(["passwd", "-l", "root"], ap.cmds)
        self.assertIn(["systemctl", "enable", "sshd.service"], ap.cmds)
        self.assertFalse(os.path.exists(os.path.join(root, "home/lab")))
        self.assertFalse(os.path.exists(os.path.join(root, "etc/sudoers.d/50-bromigos-lab")))

    def test_update_window_in_config(self):
        root, ap = self.apply("plain", update_window="01:00-03:00", update_mode="download")
        import tomllib
        t = tomllib.loads(self.read(root, "/etc/bromigos/server.toml"))
        self.assertEqual((t["updates"]["window"], t["updates"]["mode"], t["updates"]["auto"]), ("01:00-03:00", "download", False))
        self.assertEqual((t["roles"]["picked"], t["roles"]["enabled"]), (["plain"], ["just-a-server"]))   # bromigos-server's ids
        self.assertEqual(t["boot"]["kernel"], "linux-lts")
        drop = self.read(root, "/etc/systemd/system/bromigos-server-update.timer.d/10-window.conf")
        self.assertIn("OnCalendar=*-*-* 01:00:00", drop)
        self.assertIn("RandomizedDelaySec=90min", drop)

    def test_lab_node_account_and_firewall(self):
        root, ap = self.apply("lab")
        self.assertIn("lab ALL=(ALL) NOPASSWD: ALL", self.read(root, "/etc/sudoers.d/50-bromigos-lab"))
        self.assertEqual(self.read(root, "/home/lab/.ssh/authorized_keys").strip(), KEY)
        nft = self.read(root, "/etc/nftables.conf")
        self.assertIn('ip saddr @lan tcp dport { 6443, 10250, 2379, 2380 } accept comment "lab-cluster"', nft)
        self.assertIn('tcp dport 22 accept comment "ssh"', nft)
        self.assertNotIn("flush ruleset", nft)
        self.assertIn("fs.inotify.max_user_watches = 524288", self.read(root, "/etc/sysctl.d/90-bromigos-server.conf"))
        self.assertTrue(os.access(os.path.join(root, "etc/bromigos/server/health.d/50-k3s.sh"), os.X_OK))

    def test_storage_raid1_and_shares(self):
        root, ap = self.apply("storage", data_disks=["/dev/sda", "/dev/sdb"], data_layout="raid1")
        self.assertIn(["(live)", "mkfs.btrfs", "-f", "-L", "bromigos-data", "-d", "raid1", "-m", "raid1", "/dev/sda", "/dev/sdb"], ap.cmds)
        self.assertIn("/srv/data  btrfs", self.read(root, "/etc/fstab"))
        self.assertIn("[shares]", self.read(root, "/etc/samba/smb.conf"))
        self.assertIn("/srv/data/shares 10.0.0.0/8", self.read(root, "/etc/exports"))
        self.assertIn(["systemctl", "enable", "btrfs-scrub@srv-data.timer"], ap.cmds)
        self.assertIn(["snapper", "--no-dbus", "-c", "data", "create-config", "/srv/data"], ap.cmds)
        self.assertIn('accept comment "smb"', self.read(root, "/etc/nftables.conf"))

    def test_kernel_apparmor_and_find_my_lab(self):
        root, ap = self.apply("plain")
        g = self.read(root, "/etc/default/grub")
        self.assertIn('GRUB_TOP_LEVEL="/boot/vmlinuz-linux-lts"', g)
        self.assertIn('GRUB_DISABLE_SUBMENU="y"', g)
        self.assertIn("lsm=landlock,lockdown,yama,integrity,apparmor,bpf", g)
        self.assertIn("_bromigos-lab._tcp", self.read(root, "/etc/avahi/services/bromigos-server.service"))
        self.assertIn("mdns_minimal [NOTFOUND=return] resolve", self.read(root, "/etc/nsswitch.conf"))
        self.assertIn("SystemMaxUse=1G", self.read(root, "/etc/systemd/journald.conf.d/90-bromigos-server.conf"))
        self.assertIn(["grub-mkconfig", "-o", "/boot/grub/grub.cfg"], ap.cmds)

    def test_tpm_unlock(self):
        os.environ["BROMIGOS_INSTALLER_TPM"] = "1"
        try:
            root, ap = self.apply("plain", unlock="tpm")
        finally:
            os.environ["BROMIGOS_INSTALLER_TPM"] = "0"
        hooks = self.read(root, "/etc/mkinitcpio.conf")
        self.assertIn("HOOKS=(base systemd autodetect microcode modconf kms keyboard sd-vconsole block sd-encrypt filesystems fsck)", hooks)
        g = self.read(root, "/etc/default/grub")
        self.assertIn("rd.luks.name=abcd=root rd.luks.options=tpm2-device=auto", g)
        self.assertNotIn("cryptdevice", g)
        self.assertIn("NoExtract = etc/grub.d/41_snapshots-btrfs", self.read(root, "/etc/pacman.conf"))
        unit = self.read(root, "/etc/systemd/system/bromigos-server-tpm-enroll.service")
        self.assertIn("systemd-cryptenroll", unit)
        self.assertIn("--tpm2-device=auto", unit)
        self.assertIn(["systemctl", "disable", "grub-btrfsd.service"], ap.cmds)

    def test_games_with_the_lab(self):
        a = {"pelican_url": "https://panel.lab.example", "registry_mirror": "https://registry.lab.example"}
        from bromigos_installer import server_apply
        ans = answers("games", **a)
        server.srv(ans)["services"]["pelican-wings"] = True
        doc = common.backend_answers(ans, {"options": {}})
        root = tempfile.mkdtemp()
        server_apply.Apply(doc, root, "admin", dry=True, online=False).all()
        dj = json.loads(self.read(root, "/etc/docker/daemon.json"))
        self.assertEqual(dj["registry-mirrors"], ["https://registry.lab.example"])
        self.assertIn('pelican_url = "https://panel.lab.example"', self.read(root, "/etc/bromigos/server.toml"))
        self.assertIn('enabled = ["game-server/pelican-wings"]', self.read(root, "/etc/bromigos/server.toml"))

    def test_firewall_with_the_package(self):
        """bromigos-server installed: its own rule sets by name, the rest as rules in its nftables.d."""
        from bromigos_installer import server_apply
        a = answers("home")
        doc = common.backend_answers(a, {"options": {}})
        root = tempfile.mkdtemp()
        for f in ("usr/lib/bromigos/server/bromigos-server", "usr/share/bromigos/server/allow-web.nft"):
            os.makedirs(os.path.join(root, os.path.dirname(f)), exist_ok=True)
            open(os.path.join(root, f), "w").close()
        ap = server_apply.Apply(doc, root, "admin", dry=True, online=False)
        ap.all()
        import tomllib
        t = tomllib.loads(self.read(root, "/etc/bromigos/server.toml"))
        self.assertEqual(t["firewall"]["allow"], ["web"])
        extra = self.read(root, "/etc/bromigos/server/nftables.d/50-installer.nft")
        self.assertIn('add rule inet bromigos-server input ip saddr @lan udp dport 5353 accept comment "mdns"', extra)
        self.assertNotIn("web", extra)
        self.assertFalse(os.path.exists(os.path.join(root, "etc/nftables.conf")))
        self.assertIn(["bromigos-server", "setup"], ap.cmds)

    def test_pending_packages_offline(self):
        root, ap = self.apply("home")
        pend = self.read(root, "/etc/bromigos/server/pending-packages").split()
        self.assertIn("caddy", pend)
        self.assertIn("linux-lts", pend)
        self.assertIn("ConditionPathExists=/etc/bromigos/server/pending-packages",
                      self.read(root, "/etc/systemd/system/bromigos-server-pending.service"))


class MultiRole(unittest.TestCase):
    """Several roles at once: the presets merge, Just a server goes alone, a combination's notes."""

    def test_union(self):
        a = answers("plain")
        server.set_roles(a, ["lab", "games", "storage"])
        p = server.plan(a)
        self.assertEqual(p["roles"], ["lab", "games", "storage"])
        for pk in ("nfs-utils", "samba", "cpupower"):
            self.assertIn(pk, p["packages"])
        self.assertTrue({"lab-cluster", "games", "smb", "nfs"} <= set(p["firewall"]))
        self.assertTrue({"k3s", "arrays", "shares", "apps"} <= set(p["health"]))
        self.assertTrue(p["access"]["lab_account"])
        self.assertEqual(p["sysctl"]["fs.inotify.max_user_instances"], 512)
        rows = dict(server.summary(a, None)[0])
        self.assertEqual(rows["Roles"], "Lab node + Game server + Storage")

    def test_plain_goes_alone(self):
        a = answers("plain")
        server.toggle_role(a, "lab", True)
        self.assertEqual(server.roles_of(server.srv(a)), ["lab"])
        server.toggle_role(a, "media", True)
        self.assertEqual(server.roles_of(server.srv(a)), ["lab", "media"])
        server.toggle_role(a, "plain", True)
        self.assertEqual(server.roles_of(server.srv(a)), ["plain"])
        self.assertIn("or several", server.check("role", dict(a, server=dict(server.srv(a), roles=[], role=None))))

    def test_combination_notes(self):
        notes = server.combo_notes(["games", "lab"], {"cpu": 4, "ram_gb": 16})
        self.assertTrue(any("own processor and memory budget" in n for n in notes))
        self.assertTrue(any("It wants 32 GB of memory (this one has 16)" in n for n in notes), notes)
        self.assertFalse(any("It wants" in n for n in server.combo_notes(["games", "lab"], {"cpu": 16, "ram_gb": 64})))
        self.assertEqual(server.combo_notes(["home"], {"cpu": 1, "ram_gb": 1}), [])

    def test_answer_file_roles(self):
        d = tempfile.mkdtemp()
        p = os.path.join(d, "install.toml")
        with open(p, "w") as f:
            f.write('[install]\nedition = "server"\ndisk = "/dev/nvme0n1"\nmode = "erase"\nuser = "admin"\npassword = "pw-pw"\n'
                    f'ssh_keys = ["{KEY}"]\n[server]\nroles = ["storage", "media"]\nunlock = "none"\n')
        a, problems = common.read_answer_file(p)
        self.assertEqual(problems, [])
        self.assertEqual(server.roles_of(server.srv(a)), ["storage", "media"])
        with open(p, "w") as f:
            f.write('[install]\nedition = "server"\ndisk = "/dev/nvme0n1"\nmode = "erase"\nuser = "admin"\npassword = "pw-pw"\n'
                    f'ssh_keys = ["{KEY}"]\n[server]\nroles = ["plain", "lab"]\nunlock = "none"\n')
        _, problems = common.read_answer_file(p)
        self.assertTrue(any("goes alone" in x for x in problems), problems)


class Catalogue(unittest.TestCase):
    """What should this server run? The catalogue (its stand-in, the engine's schema), the roles'
    picks, what they need added, the budget, the models."""
    HW = {"cpu": 16, "ram_gb": 64, "disk_gb": 4000, "gpu": True, "gpu_name": "NVIDIA RTX 4090", "gpu_vram_gb": 24}

    def test_dependencies_are_added_and_said(self):
        from bromigos_installer import provision as PV
        ids, auto = PV.resolve(["argocd", "chat"])
        self.assertEqual(set(auto), {"kubernetes", "ai-gateway"})
        self.assertLess(ids.index("kubernetes"), ids.index("argocd"))
        self.assertEqual(len(PV.conflicts(["minecraft", "wings"])), 1)
        self.assertIn("can't run on the same server", PV.conflicts(["minecraft", "wings"])[0])

    def test_budget_states(self):
        from bromigos_installer import provision as PV
        b = PV.budget(["model-serving", "chat"], self.HW)
        self.assertTrue(b["fits"])
        self.assertEqual(b["gpu_vram_gb"], 8)
        small = PV.budget(["model-serving", "photos", "media", "monitoring"], {"cpu": 2, "ram_gb": 4, "disk_gb": 50, "gpu": False})
        self.assertFalse(small["fits"])
        text = " ".join(small["notes"])
        self.assertIn("graphics card", text)
        self.assertIn("GB of memory", text)
        self.assertEqual(PV.budget([], self.HW)["ram_gb"], 0)

    def test_roles_suggest_and_downloaders_stay_off(self):
        a = answers("media")
        picks = server.provision_picks(a, self.HW)
        self.assertTrue({"jellyfin", "seerr", "library", "den-tv"} <= set(picks), picks)
        for off in ("vpn", "sabnzbd", "torrent", "prowlarr"):
            self.assertNotIn(off, picks)
        self.assertIn("Media", server.suggested_by(a)["jellyfin"])
        a = answers("plain")
        server.set_roles(a, ["lab"])
        server.srv(a).update(lab="new", lab_set=True)
        self.assertIn("kubernetes", server.provision_picks(a, self.HW))

    def test_models_sized_to_the_card(self):
        from bromigos_installer import provision as PV
        ms = PV.suggest_models({"gpu": True, "gpu_vram_gb": 16})
        self.assertTrue(ms[0]["fits"])
        self.assertLessEqual(ms[0]["gpu_vram_gb"], 16)
        self.assertFalse(next(m for m in ms if m["id"] == "qwen3-32b-awq")["fits"])

    def test_guided_setups(self):
        from bromigos_installer import provision as PV
        f = {x["id"]: x for x in PV.setup("vpn")["field"]}
        self.assertEqual(f["provider"]["default"], "pia")
        self.assertEqual([c["id"] for c in f["provider"]["choices"]], ["pia", "protonvpn", "mullvad"])
        self.assertTrue(all(c.get("link") and c.get("note") for c in f["provider"]["choices"]))
        self.assertIs(f["kill_switch"]["default"], True)
        shown = [x["id"] for x in PV.fields("vpn", {"provider": "mullvad"})]
        self.assertIn("wireguard_key", shown)
        self.assertNotIn("username", shown)
        sab = {x["id"]: x.get("default") for x in PV.setup("sabnzbd")["field"]}
        self.assertEqual((sab["port"], sab["ssl"], sab["connections"]), (563, True, 20))
        self.assertIn("indexers you have access to", " ".join(PV.setup("prowlarr")["notes"]))
        cat = open(PV.catalogue_path()).read().lower()
        for word in ("nzbgeek", "1337x", "rarbg", "piratebay", "torrentleech"):     # no indexer or tracker names
            self.assertNotIn(word, cat)
        self.assertIn("own or have rights to", cat)
        os.environ["BROMIGOS_PROVISION_CMD"] = "no-such-engine-here"
        try:
            self.assertEqual(PV.check("vpn", {})[0], None)        # no engine: the first start checks it
        finally:
            del os.environ["BROMIGOS_PROVISION_CMD"]


class Secrets(unittest.TestCase):
    """Keys and passwords: into the store chosen, never into the answer file or the installed /etc."""
    SECRET = "Pa55-only-in-the-store-9k3"

    def doc(self, **store):
        a = answers("media")
        s = server.srv(a)
        s["provision"], s["provision_edited"] = ["jellyfin", "vpn", "sabnzbd", "minecraft"], True
        s["setup"] = {"vpn": {"provider": "pia", "username": "me"}}
        s["setup_secrets"] = {"vpn": {"password": self.SECRET}, "sabnzbd": {"password": self.SECRET + "b"}}
        s["store"] = dict({"kind": "vault", "auth": "approle", "address": "https://vault.lab.example:8200", "role_id": "r1",
                           "secret_id": self.SECRET + "c"}, **store)
        a["reach"] = {"mode": "tailscale", "tailscale_key": "tskey-auth-" + self.SECRET.replace("-", "")}
        return a

    def scan(self, text):
        """What a secrets scanner finds in a text: the typed values, and the usual shapes of keys."""
        import re
        hits = [v for v in (self.SECRET, self.SECRET + "b", self.SECRET + "c", "tskey-auth") if v in text]
        hits += re.findall(r"AGE-SECRET-KEY-\S+|BEGIN [A-Z ]*PRIVATE KEY|hvs\.[A-Za-z0-9]{20,}|bromigos-net:1:\S+", text)
        return hits

    def test_answer_file_has_no_secrets(self):
        a = self.doc()
        text = common.answers_toml(a)
        self.assertEqual(self.scan(text), [], text)
        self.assertIn('password = { secret = "vault:vpn/password" }', text)        # a reference, never the value
        self.assertIn('vpn = { provider = "pia", username = "me"', text)
        self.assertIn('reach = "tailscale"', text)
        doc = common.backend_answers(a, {"options": {}})
        self.assertEqual(self.scan(doc["answers_toml"]), [])

    def test_installed_etc_has_no_secrets(self):
        from bromigos_installer import server_apply
        a = self.doc()
        doc = common.backend_answers(a, {"options": {}})
        root = tempfile.mkdtemp()
        server_apply.Apply(doc, root, "admin", dry=True, online=False).all()
        for d, _, files in os.walk(os.path.join(root, "etc")):
            for f in files:
                with open(os.path.join(d, f), errors="replace") as fh:
                    self.assertEqual(self.scan(fh.read()), [], os.path.join(d, f))
        staged = os.path.join(root, "var/lib/bromigos/secrets/staged.json")
        self.assertEqual(oct(os.stat(staged).st_mode)[-3:], "600")
        self.assertIn("bromigos-server-secrets.service", os.listdir(os.path.join(root, "etc/systemd/system")))

    def test_summary_counts_without_values(self):
        a = self.doc()
        rows = dict(server.summary(a, None)[0])
        self.assertIn("keys stored in your lab's Vault", rows["Keys and passwords"])
        self.assertEqual(self.scan(json.dumps(rows)), [])

    def test_never_a_root_token(self):
        a = self.doc(auth="wrapped", token="root")
        self.assertIn("root token", server.check("secrets", a))
        a = self.doc(auth="approle", secret_id="")
        self.assertIn("secret ID", server.check("secrets", a))
        a = self.doc(kind="local")
        self.assertIsNone(server.check("secrets", a))
        a = self.doc(kind="openbao")
        self.assertIsNone(server.check("secrets", a))
        self.assertEqual(server.srv(a)["lab"], "new")
        self.assertIn("vault", server.srv(a)["provision"])
        self.assertEqual([b["id"] for b in server.secretstore().backends()], ["vault", "openbao", "local", "sops"])

    def test_plain_secret_in_settings_is_refused(self):
        d = tempfile.mkdtemp()
        p = os.path.join(d, "install.toml")
        with open(p, "w") as f:
            f.write('[install]\nedition = "server"\ndisk = "/dev/nvme0n1"\nmode = "erase"\nuser = "admin"\npassword = "pw-pw"\n'
                    f'ssh_keys = ["{KEY}"]\n[server]\nroles = ["media"]\nunlock = "none"\nprovision = ["vpn"]\n'
                    '[server.settings.vpn]\nprovider = "pia"\npassword = "in-plain-text"\n')
        a, problems = common.read_answer_file(p)
        self.assertTrue(any("is a secret: reference it" in x for x in problems), problems)
        with open(p, "w") as f:
            f.write('[install]\nedition = "server"\ndisk = "/dev/nvme0n1"\nmode = "erase"\nuser = "admin"\npassword = "pw-pw"\n'
                    f'ssh_keys = ["{KEY}"]\n[server]\nroles = ["media"]\nunlock = "none"\nprovision = ["vpn"]\n'
                    '[server.settings.vpn]\nprovider = "mullvad"\nwireguard_key = { secret = "local:vpn/wireguard_key" }\n')
        a, problems = common.read_answer_file(p)
        self.assertEqual(problems, [])
        self.assertEqual(server.srv(a)["setup"]["vpn"]["provider"], "mullvad")


class Reach(unittest.TestCase):
    """Reach it from anywhere (bromigos_homelab.reach, the lab network's)."""

    def setUp(self):
        if not server.reach_module():
            self.skipTest("bromigos_homelab.reach isn't here")

    def test_checks(self):
        m = server.reach_module()
        good = m.encode("https://headscale.lab.example", "0123456789abcdef0123456789abcd", "home-lab")
        self.assertIsNone(server.check_reach({"mode": "lab-network", "bundle": good}))
        self.assertIsNotNone(server.check_reach({"mode": "lab-network", "bundle": "bromigos-net:1:nonsense"}))
        self.assertIsNotNone(server.check_reach({"mode": "wireguard", "wireguard": "not a config"}))
        self.assertIsNone(server.check_reach({"mode": "brodec"}))
        self.assertIn("isn't one of", server.check_reach({"mode": "cloudflare"}))
        self.assertNotIn("cloudflare", json.dumps(server.reach_choices()).lower())

    def test_packages_and_steps(self):
        a = answers("plain")
        a["reach"] = {"mode": "lab-network"}
        self.assertIn("tailscale", server.plan(a)["packages"])
        desk = common.defaults()
        desk.update(edition="desktop", mode="erase")
        self.assertIn("reach", common.steps_for(desk))
        st = common.steps_for(answers("plain"))
        self.assertEqual(st[st.index("access") + 1], "reach")
        self.assertEqual(st[st.index("role") + 1], "secrets")


@unittest.skipUnless(test_tui.HAVE, "textual isn't installed")
class TextSteps(ServerProbe, unittest.TestCase):
    """Each new step in the text installer, driven by keys, drawn at 120×35 and 80×24."""
    SIZES = [(120, 35), (80, 24)]
    SHOTS = os.environ.get("BROMIGOS_INSTALLER_SHOTS")

    def each(self, fn, roles=("home",), size=(120, 35)):
        from bromigos_installer import tui

        async def go():
            app = tui.Installer()
            async with app.run_test(size=size) as pilot:
                await pilot.pause(0.4)
                for _ in range(50):
                    if app.probe is not None:
                        break
                    await pilot.pause(0.1)
                app.a.update(edition="server", disk="/dev/nvme0n1", mode="erase")
                return await fn(app, pilot)
        return asyncio.run(go())

    def test_every_step_draws_and_fits(self):
        for w, h in self.SIZES:
            for role in ("home", "lab", "storage", "games"):
                with self.subTest(size=f"{w}x{h}", role=role):
                    async def fn(app, pilot):
                        server.pick_role(app.a, role)
                        seen = []
                        for sid in [x for x in server.STEP_IDS] + ["summary"]:
                            await app.show(sid)
                            await pilot.pause(0.25)
                            page = app.query_one("#page")
                            self.assertEqual(page.max_scroll_x, 0, f"{sid} runs off the side")
                            for b in app.query("#nav Button"):
                                if b.display:
                                    self.assertLessEqual(b.region.right, w, f"{sid}: {b.id}")
                            for ctl in app.query("#steps Input, #steps Switch, #steps Checkbox, #steps Choice, #steps Select"):
                                if ctl.display and app.query_one("#steps").current == f"step-{sid}":
                                    self.assertTrue(getattr(ctl, "tooltip", None) or ctl.parent.tooltip,
                                                    f"{sid}: {ctl!r} has no hint")
                            if self.SHOTS:
                                os.makedirs(os.path.join(self.SHOTS, "server"), exist_ok=True)
                                app.save_screenshot(os.path.join(self.SHOTS, "server", f"tui-{w}x{h}-{role}-{sid}.svg"))
                            seen.append(sid)
                        return seen
                    self.assertEqual(self.each(fn, size=(w, h)), server.STEP_IDS + ["summary"])

    def test_network_static_by_keys(self):
        async def fn(app, pilot):
            server.pick_role(app.a, "home")
            await app.show("network")
            await pilot.pause(0.3)
            app.query_one("#srv-static").value = True
            await pilot.pause(0.4)
            app.query_one("#srv-address").value = "192.0.2.40"
            app.query_one("#srv-prefix").value = "24"
            app.query_one("#srv-gateway").value = "198.51.100.1"
            app.query_one("#srv-dns").value = "192.0.2.1"
            await pilot.pause(0.2)
            await pilot.press("ctrl+n")
            await pilot.pause(0.2)
            first = (app.step, str(app.query_one("#error").render()))
            label = str(app.query_one("#lab-srv-gateway").render())
            app.query_one("#srv-gateway").value = "192.0.2.1"
            await pilot.pause(0.2)
            await pilot.press("ctrl+n")
            await pilot.pause(0.3)
            return first, label, app.step, str(app.query_one("#addr-big").render()) if app.query("#addr-big") else ""
        first, label, step, _ = self.each(fn)
        self.assertEqual(first[0], "network")
        self.assertIn("isn't on 192.0.2.0/24", first[1])
        self.assertIn("isn't on", label)
        self.assertEqual(step, "access")

    def test_access_key_only_and_github(self):
        httpd = http.server.HTTPServer(("127.0.0.1", 0), type("H", (http.server.BaseHTTPRequestHandler,), {
            "do_GET": lambda self: (self.send_response(200), self.end_headers(), self.wfile.write((KEY2 + "\n").encode())),
            "log_message": lambda self, *a: None}))
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        os.environ["BROMIGOS_GITHUB_KEYS_URL"] = f"http://127.0.0.1:{httpd.server_port}"
        try:
            async def fn(app, pilot):
                server.pick_role(app.a, "home")
                app.a["found_keys"] = []
                await app.show("access")
                await pilot.pause(0.4)
                app.query_one("#srv-password").value = "tester-pass"
                app.query_one("#srv-password2").value = "tester-pass"
                await pilot.pause(0.2)
                await pilot.press("ctrl+n")
                await pilot.pause(0.2)
                no_key = str(app.query_one("#error").render())
                app.query_one("#srv-github").value = "octocat"
                await pilot.pause(0.2)
                await pilot.press("ctrl+n")
                await pilot.pause(0.2)
                unconfirmed = str(app.query_one("#error").render())
                app.query_one("#srv-ghget").press()
                for _ in range(40):
                    await pilot.pause(0.1)
                    if app.query("#srv-ghok"):
                        break
                shown = " ".join(str(w.render()) for w in app.query("#srv-gh Static"))
                app.query_one("#srv-ghok").value = True
                await pilot.pause(0.2)
                await pilot.press("ctrl+n")
                await pilot.pause(0.3)
                return no_key, unconfirmed, shown, app.step, server.all_keys(app.a)
            no_key, unconfirmed, shown, step, keys = self.each(fn)
        finally:
            httpd.shutdown()
            del os.environ["BROMIGOS_GITHUB_KEYS_URL"]
        self.assertIn("Keys only needs a key", no_key)
        self.assertIn("Get keys", unconfirmed)
        self.assertIn("SHA256:", shown)
        self.assertEqual(step, "reach")
        self.assertEqual(keys, [KEY2])

    def test_catalogue_adds_what_it_needs(self):
        async def fn(app, pilot):
            server.set_roles(app.a, ["home"])
            s = server.srv(app.a)
            s.update(lab="new", lab_set=True, provision=[], provision_edited=True)
            await app.show("services")
            await pilot.pause(0.6)
            app.query_one("#sprov-argocd").value = True
            await pilot.pause(0.8)
            k = app.query_one("#sprov-kubernetes")
            hero = str(app.query_one("#srv-budget").render())
            return k.value, str(k.label), server.srv(app.a)["provision"], hero
        on, words, picks, hero = self.each(fn)
        self.assertTrue(on)
        self.assertIn("added: needed by Argo CD", words)
        self.assertEqual(picks, ["argocd"])
        self.assertIn("2 CHOSEN", hero)

    def test_roles_tick_several(self):
        async def fn(app, pilot):
            server.set_roles(app.a, [])
            await app.show("role")
            await pilot.pause(0.4)
            for r in ("lab", "games", "storage"):
                app.query_one(f"#srole-{r}").action_pick()
                await pilot.pause(0.2)
            first = server.roles_of(server.srv(app.a))
            app.query_one("#srole-plain").action_pick()
            await pilot.pause(0.3)
            return first, server.roles_of(server.srv(app.a)), app.query_one("#srole-lab").value
        first, after, lab_on = self.each(fn)
        self.assertEqual(first, ["lab", "games", "storage"])
        self.assertEqual((after, lab_on), (["plain"], False))

    def test_raid1_by_keys(self):
        async def fn(app, pilot):
            server.pick_role(app.a, "storage")
            await app.show("storage")
            await pilot.pause(0.3)
            app.query_one("#srv-lay-raid1").value = True
            app.query_one("#sdisk-0").value = True
            await pilot.pause(0.2)
            await pilot.press("ctrl+n")
            await pilot.pause(0.2)
            one = str(app.query_one("#error").render())
            app.query_one("#sdisk-1").value = True
            await pilot.pause(0.2)
            await pilot.press("ctrl+n")
            await pilot.pause(0.3)
            return one, app.step, server.srv(app.a)["data_disks"], server.srv(app.a)["data_layout"]
        one, step, disks, layout = self.each(fn)
        self.assertIn("two or more", one)
        self.assertEqual((step, disks, layout), ("unlock", ["/dev/sda", "/dev/sdb"], "raid1"))

    def test_whole_install_by_keys(self):
        """bromigOS Server start to end by keys (tuidrive): what bromigos-iso-install is handed."""
        from tuidrive import drive
        from bromigos_installer import tui
        sent = []
        real = backend.Install.__init__

        def spy(inst, doc, *a, **k):
            sent.append(doc)
            real(inst, doc, *a, **k)
        backend.Install.__init__ = spy
        try:
            async def go():
                app = tui.Installer()
                async with app.run_test(size=(120, 42)) as pilot:
                    await drive(app, pilot, {"edition": "server", "mode": "erase", "disk_index": 0, "user": "admin",
                                             "password": "tester-pass", "hostname": "store-1", "ssh_key": KEY,
                                             "server": {"role": "storage", "method": "static", "address": "192.0.2.10",
                                                        "prefix": 24, "gateway": "192.0.2.1", "dns": ["192.0.2.1"],
                                                        "data_disks": ["/dev/sda", "/dev/sdb"], "data_layout": "raid1",
                                                        "unlock": "none", "update_mode": "download",
                                                        "update_window": "01:00-03:00"}})
                    await pilot.press("ctrl+n")
                    for _ in range(100):
                        if app.step == "done":
                            break
                        await pilot.pause(0.05)
                    return app.step
            step = asyncio.run(go())
        finally:
            backend.Install.__init__ = real
        self.assertEqual(step, "done")
        doc = sent[-1]
        p = doc["server"]
        self.assertEqual((doc["user"], doc["hostname"], doc["encrypt"], doc["ssh_keys"]), ("admin", "store-1", False, [KEY]))
        self.assertEqual((p["role"], p["network"]["address"], p["storage"]["layout"]), ("storage", "192.0.2.10", "raid1"))
        self.assertEqual((p["updates"]["mode"], p["updates"]["window"]), ("download", "01:00-03:00"))
        self.assertIn("[server]", doc["answers_toml"])
        self.assertNotIn("tester-pass", doc["answers_toml"])


@unittest.skipUnless(shutil.which("weston"), "no weston for the offscreen pictures")
class GraphicalSteps(unittest.TestCase):
    """Each new step in the graphical installer, drawn offscreen (render-gui.sh, headless weston)."""

    def test_render(self):
        out = os.environ.get("BROMIGOS_INSTALLER_SHOTS") and os.path.join(os.environ["BROMIGOS_INSTALLER_SHOTS"], "server-gui") \
            or tempfile.mkdtemp()
        env = dict(os.environ, BROMIGOS_INSTALLER_RENDER_ONLY="server-")
        r = subprocess.run([os.path.join(HERE, "render-gui.sh"), out, "--probe", os.path.join(HERE, "fixtures/probe-server.json")],
                           capture_output=True, text=True, env=env, timeout=400)
        self.assertEqual(r.returncode, 0, r.stderr[-1500:])
        made = sorted(f for f in os.listdir(out) if f.startswith("gui-server-"))
        from bromigos_installer import server_gui
        self.assertEqual(len(made), len(server_gui.RENDER_PLAN), made)


if __name__ == "__main__":
    unittest.main()
