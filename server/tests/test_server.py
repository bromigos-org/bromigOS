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
case "$1" in --root=*) shift ;; esac
case "$1" in
  is-active) if grep -qx "$2" "$FAKE/down" 2>/dev/null; then echo inactive; exit 3; fi; echo active ;;
  show) if grep -qx "$4" "$FAKE/units" 2>/dev/null; then echo loaded; else echo not-found; fi ;;
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
    # installed: the names in $FAKE/installed; -S fails for a name in $FAKE/unavailable
    "pacman": r'''#!/bin/sh
echo "pacman $*" >> "$FAKE/log"
case "$1" in
  -Q) grep -qx "$2" "$FAKE/installed" 2>/dev/null ;;
  -S) shift; for p in "$@"; do case "$p" in -*) continue ;; esac
        if grep -qx "$p" "$FAKE/unavailable" 2>/dev/null; then echo "error: target not found: $p" >&2; exit 1; fi
        echo "$p" >> "$FAKE/installed"; done ;;
  -R) shift; for p in "$@"; do case "$p" in -*) continue ;; esac
        grep -vx "$p" "$FAKE/installed" > "$FAKE/installed.new"; mv "$FAKE/installed.new" "$FAKE/installed"; done ;;
esac
''',
    # restic: $FAKE/restic-<verb>.rc and .out stand in for each verb's exit code and output
    "restic": r'''#!/bin/sh
echo "restic $* repo=$RESTIC_REPOSITORY key=$RESTIC_PASSWORD_FILE id=$AWS_ACCESS_KEY_ID" >> "$FAKE/log"
v=$1; [ "$v" = cat ] && v=cat-config
[ -f "$FAKE/restic-$v.out" ] && cat "$FAKE/restic-$v.out"
[ -f "$FAKE/restic-$v.err" ] && cat "$FAKE/restic-$v.err" >&2
exit "$(cat "$FAKE/restic-$v.rc" 2>/dev/null || echo 0)"
''',
    "nut-scanner": "#!/bin/sh\ncat \"$FAKE/nut-scanner\" 2>/dev/null\nexit 0\n",
}


def report(packages, pre=10, post=11, kernel=False):
    return json.dumps({"schema": 1, "report": {
        "pacman": 0, "packages": [{"name": n, "from": "1", "to": "2"} for n in packages],
        "snapshot": {"pre": pre, "post": post} if packages else None,
        "reboot": {"kernel": {"running": "a", "installed": "b"}, "driver": None} if kernel else None}})


class Rig(unittest.TestCase):
    """bromigos-server in a stand-in root, with the stand-ins above on its PATH."""

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
                   BROMIGOS_SERVER_HEALTH_POLL="0",
                   # never the network: no feed unless a test gives one
                   BROMIGOS_SERVER_NEWS_FEED=self.news)
        return subprocess.run([sys.executable, "-I", str(SCRIPT), *args], env=env, capture_output=True, text=True)

    news = "file:///nonexistent/arch-news.xml"

    # ---- the Arch news hold

    def with_news(self, last_success):
        self.news = (HERE / "tests/fixtures/arch-news.xml").as_uri()
        st = self.root / "var/lib/bromigos/server/update.json"
        st.parent.mkdir(parents=True, exist_ok=True)
        st.write_text(json.dumps({"phase": "ok", "last_success_ts": last_success}))
        (self.fake / "update.json").write_text(report(["bash"]))

    def test_news_since_the_last_update_holds_the_automatic_one(self):
        self.with_news(1793000000)                      # 2026-10-25: the openssh item came after
        r = self.run_server("update")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("holding the update", r.stdout)
        self.assertNotIn("bromigos update", self.log())
        st = self.state()
        self.assertEqual(st["phase"], "ok")
        self.assertEqual([i["title"] for i in st["hold"]["items"]],
                         ["Manual intervention required for the openssh 10.3 upgrade"])
        self.assertIn("archlinux.org/news/manual-intervention", st["hold"]["items"][0]["link"])
        status = self.run_server("status")
        self.assertIn("Update held", status.stdout)
        self.assertIn('"hold"', self.run_server("status", "--json").stdout)

    def test_update_now_is_a_person_deciding_it_clears_the_hold(self):
        self.with_news(1793000000)
        self.run_server("update")
        r = self.run_server("update", "--now")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("bromigos update --yes --no-aur --json", self.log())
        st = self.state()
        self.assertNotIn("hold", st)
        self.assertEqual(st["phase"], "ok")
        self.assertGreater(st["news_seen_ts"], 1793390400 - 10 ** 9)
        # the next automatic update: that news was read
        (self.fake / "log").write_text("")
        self.run_server("update")
        self.assertIn("bromigos update --yes", self.log())

    def test_older_news_and_an_unreadable_feed_hold_nothing(self):
        self.with_news(1795000000)                      # after every item
        self.run_server("update")
        self.assertIn("bromigos update --yes", self.log())
        self.assertNotIn("hold", self.state())
        self.with_news(1793000000)
        self.news = "file:///nonexistent/feed.xml"
        (self.fake / "log").write_text("")
        self.run_server("update")
        self.assertIn("bromigos update --yes", self.log())

    def test_the_hold_can_be_turned_off(self):
        self.with_news(1793000000)
        self.config("[health]\nminutes = 0\n[updates]\nnews_hold = false\n")
        self.run_server("update")
        self.assertIn("bromigos update --yes", self.log())


    def state(self):
        return json.loads((self.root / "var/lib/bromigos/server/update.json").read_text())

    def log(self):
        p = self.fake / "log"
        return p.read_text() if p.exists() else ""


class Server(Rig):
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
