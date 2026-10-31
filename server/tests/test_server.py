"""bromigos-server in a stand-in root, with stand-in systemctl, bromigos, ip, ping and nft:
the settings it applies, the firewall it builds, and the update, health and rollback flow.
No root, no network, nothing on this machine changes."""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
SCRIPT = HERE / "bromigos-server"

STUBS = {
    "systemctl": r'''#!/bin/sh
echo "systemctl $*" >> "$FAKE/log"
case "$1" in
  is-active) if grep -qx "$2" "$FAKE/down" 2>/dev/null; then echo inactive; exit 3; fi; echo active ;;
  is-enabled) echo enabled ;;
  is-system-running) echo running ;;
  list-units) cat "$FAKE/failed" 2>/dev/null ;;
esac
exit 0
''',
    "bromigos": r'''#!/bin/sh
echo "bromigos $*" >> "$FAKE/log"
case "$*" in
  *--rollback*) exit 0 ;;
  update*) cat "$FAKE/update.json" ;;
esac
''',
    "ip": r'''#!/bin/sh
case "$*" in
  *addr*) echo '[{"addr_info":[{"local":"192.0.2.20"}]}]' ;;
  *route*) echo '[{"gateway":"192.0.2.1"}]' ;;
esac
''',
    "ping": "#!/bin/sh\nexit 0\n",
    "nft": "#!/bin/sh\necho \"nft $*\" >> \"$FAKE/log\"\ncat > /dev/null\nexit 0\n",
    "podman": "#!/bin/sh\necho '[]'\n",
    "mkinitcpio": "#!/bin/sh\necho \"mkinitcpio $*\" >> \"$FAKE/log\"\n",
}


def report(packages, pre=10, post=11, kernel=False):
    return json.dumps({"schema": 1, "report": {
        "pacman": 0, "packages": [{"name": n, "from": "1", "to": "2"} for n in packages],
        "snapshot": {"pre": pre, "post": post} if packages else None,
        "reboot": {"kernel": {"running": "a", "installed": "b"}, "driver": None} if kernel else None}})


class Server(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        t = Path(self.tmp.name)
        self.root, self.fake, self.bin = t / "root", t / "fake", t / "bin"
        for d in (self.root / "etc/bromigos", self.fake, self.bin, self.root / "opt/bromigos-monitoring/textfile"):
            d.mkdir(parents=True)
        for name, text in STUBS.items():
            p = self.bin / name
            p.write_text(text)
            p.chmod(0o755)
        self.config("[health]\nminutes = 0\n")

    def tearDown(self):
        self.tmp.cleanup()

    def config(self, text):
        (self.root / "etc/bromigos/server.toml").write_text(text)

    def run_server(self, *args):
        env = dict(os.environ, PATH=f"{self.bin}:/usr/bin:/bin", FAKE=str(self.fake),
                   BROMIGOS_SERVER_ROOT=str(self.root), BROMIGOS_SERVER_SHARE=str(HERE),
                   BROMIGOS_SERVER_HEALTH_POLL="0")
        return subprocess.run([sys.executable, "-I", str(SCRIPT), *args], env=env, capture_output=True, text=True)

    def state(self):
        return json.loads((self.root / "var/lib/bromigos/server/update.json").read_text())

    def log(self):
        p = self.fake / "log"
        return p.read_text() if p.exists() else ""

    def test_firewall_rules_follow_the_settings(self):
        self.config('[firewall]\nallow = ["lab-cluster", "nope"]\ntcp = [8080, "x", 70000]\n')
        r = self.run_server("firewall", "apply", "--print")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("policy drop", r.stdout)
        self.assertIn("tcp dport 22 accept", r.stdout)
        self.assertIn("6443", r.stdout)
        self.assertIn("tcp dport { 8080 }", r.stdout)
        self.assertNotIn("70000", r.stdout)
        self.assertNotIn("80, 443", r.stdout)
        self.assertIn("no rule set 'nope'", r.stderr)

    def test_allow_and_deny_rewrite_only_the_list(self):
        self.config("# mine\n[ssh]\npassword = false\n\n[firewall]\ntcp = [8080]\n")
        self.assertEqual(self.run_server("firewall", "allow", "web").returncode, 0)
        text = (self.root / "etc/bromigos/server.toml").read_text()
        self.assertIn('allow = ["web"]', text)
        self.assertIn("# mine", text)
        self.assertIn("tcp = [8080]", text)
        self.run_server("firewall", "deny", "web")
        self.assertIn("allow = []", (self.root / "etc/bromigos/server.toml").read_text())

    def test_password_sign_in_only_when_chosen(self):
        pw = self.root / "etc/ssh/sshd_config.d/05-bromigos-server-password.conf"
        self.config("[ssh]\npassword = true\n")
        self.run_server("setup")
        self.assertIn("PasswordAuthentication yes", pw.read_text())
        self.config("[ssh]\npassword = false\n")
        self.run_server("setup")
        self.assertFalse(pw.exists())

    def test_nothing_to_update(self):
        (self.fake / "update.json").write_text(report([]))
        r = self.run_server("update")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.state()["phase"], "nothing")

    def test_healthy_update(self):
        (self.fake / "update.json").write_text(report(["bash"]))
        r = self.run_server("update")
        self.assertEqual(r.returncode, 0, r.stderr)
        st = self.state()
        self.assertEqual((st["phase"], st["pre"], st["post"]), ("ok", 10, 11))
        self.assertIn("bromigos update --yes --no-aur --json", self.log())
        self.assertNotIn("--rollback", self.log())
        prom = (self.root / "opt/bromigos-monitoring/textfile/bromigos-server.prom").read_text()
        self.assertIn("bromigos_server_update_healthy 1", prom)

    def test_unhealthy_update_rolls_back_once(self):
        (self.fake / "update.json").write_text(report(["bash"]))
        (self.fake / "failed").write_text("broken.service loaded failed failed Broken\n")
        self.run_server("update")
        st = self.state()
        self.assertEqual(st["phase"], "verify")
        self.assertTrue(st["rolled_back"])
        self.assertIn("bromigos update --rollback 10 --yes", self.log())
        self.assertIn("systemctl reboot", self.log())
        # after the restart, still unhealthy: no second rollback, it asks for attention
        self.run_server("mark-boot")
        r = self.run_server("health")
        self.assertEqual(r.returncode, 1)
        self.assertEqual(self.state()["phase"], "attention")
        self.assertEqual(self.log().count("--rollback"), 1)

    def test_ignored_units_dont_count(self):
        self.config('[health]\nminutes = 0\nignore_units = ["broken.service"]\n')
        (self.fake / "update.json").write_text(report(["bash"]))
        (self.fake / "failed").write_text("broken.service loaded failed failed Broken\n")
        self.run_server("update")
        self.assertEqual(self.state()["phase"], "ok")

    def test_kernel_update_restarts_then_checks(self):
        (self.fake / "update.json").write_text(report(["linux"], kernel=True))
        self.run_server("update")
        self.assertEqual(self.state()["phase"], "reboot")
        self.assertIn("systemctl reboot", self.log())
        self.run_server("mark-boot")
        self.assertEqual(self.state()["boots"], 1)
        self.run_server("health")
        self.assertEqual(self.state()["phase"], "ok")

    def test_a_start_that_hung_rolls_back_straight_away(self):
        (self.fake / "update.json").write_text(report(["linux"], kernel=True))
        self.run_server("update")
        self.run_server("mark-boot")
        self.run_server("mark-boot")          # the first start hung; someone pressed reset
        self.run_server("health")
        self.assertIn("--rollback 10", self.log())
        self.assertIn("never reached the check", self.state()["reason"])

    def test_sshd_down_after_update_is_unhealthy(self):
        (self.fake / "update.json").write_text(report(["openssh"]))
        r = self.run_server("update")
        # sshd ran before (the stub says active), then goes down
        self.assertEqual(r.returncode, 0)
        st = self.state()
        self.assertEqual(st["phase"], "ok")
        st["phase"], st["sshd"] = "verify", True
        (self.root / "var/lib/bromigos/server/update.json").write_text(json.dumps(st))
        (self.fake / "down").write_text("sshd.service\n")
        self.run_server("health")
        self.assertIn("not running: sshd.service", self.state()["reason"])

    def test_status_json(self):
        r = self.run_server("status", "--json")
        self.assertEqual(r.returncode, 0, r.stderr)
        d = json.loads(r.stdout)
        self.assertEqual(d["addresses"], ["192.0.2.20"])
        self.assertEqual(d["updates"]["phase"], "never")
        self.assertFalse(d["cluster"]["joined"])
        self.assertEqual(d["ssh"]["how"], "keys only")


class Files(unittest.TestCase):
    def test_sshd_dropin_is_key_only(self):
        text = (HERE / "10-bromigos-server.conf").read_text()
        for line in ("PasswordAuthentication no", "KbdInteractiveAuthentication no", "PermitRootLogin no"):
            self.assertIn(line, text)

    def test_ruleset_loads_where_nft_can_check_it(self):
        import shutil
        if not (shutil.which("nft") and shutil.which("unshare")):
            self.skipTest("nft and unshare are needed")
        probe = subprocess.run(["unshare", "-rn", "true"], capture_output=True)
        if probe.returncode != 0:
            self.skipTest("no user namespaces here")
        with tempfile.TemporaryDirectory() as d:
            cfg = Path(d) / "etc/bromigos"
            cfg.mkdir(parents=True)
            (cfg / "server.toml").write_text('[firewall]\nallow = ["lab-cluster", "web"]\ntcp = [8080]\n')
            env = dict(os.environ, BROMIGOS_SERVER_ROOT=d, BROMIGOS_SERVER_SHARE=str(HERE))
            rules = subprocess.run([sys.executable, "-I", str(SCRIPT), "firewall", "apply", "--print"],
                                   env=env, capture_output=True, text=True, check=True).stdout
            r = subprocess.run(["unshare", "-rn", "nft", "-c", "-f", "-"], input=rules, capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, r.stderr)


if __name__ == "__main__":
    unittest.main()
