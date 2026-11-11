"""`bromigos alerts channels` (docs/alerts.md, "Channels") against an HTTP stand-in on this
machine's loopback: Discord's payload, the webhook's signature, dedupe, reminders, resolved,
quiet hours, the rate limit, retries and backoff, the detail levels, job results, the
catalogue, and no address, key or LAN address in any message, output or file but the secret
files themselves. Nothing is sent to Discord or anywhere else."""
import hashlib
import hmac
import http.server
import json
import os
import signal
import stat
import subprocess
import sys
import threading
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import fake  # noqa: E402
from fake import FakeMachine, NOW  # noqa: E402

import bromigos_alerts as A  # noqa: E402
import bromigos_notify as N  # noqa: E402

SCRIPT = fake.REPO / "bin/bromigos-alerts"
MIN, HOUR = 60_000, 3600_000
TOKEN = "TOKENsecretXYZ123"                       # the secret part of a stand-in address
DISCORD = f"https://discord.com/api/webhooks/123456789012345678/{TOKEN}"
KEY = "k3y-for-signing-0123456789abcdef"


def setUpModule():
    for k in ("http_proxy", "https_proxy", "HTTP_PROXY", "HTTPS_PROXY", "all_proxy", "ALL_PROXY"):
        os.environ.pop(k, None)
    os.environ["TZ"] = "UTC"                       # quiet hours are local time: the tests' is UTC
    time.tzset()


def alert(aid, check, severity, title, detail="", subject="", fix=(), since=NOW - HOUR):
    a = A.normalise({"id": aid, "check": check, "severity": severity, "title": title, "detail": detail,
                     "source": "x", "subject": subject,
                     "evidence": {"lines": ["EVIDENCE-LINE: the file's contents"], "facts": {"serial": "S6B0NX0T"}},
                     "fix": {"commands": list(fix), "touches": ["nothing"]} if fix else None})
    a["since"] = since
    return a


DRIVE = alert("disk.smart:samsung-ssd-980-pro-2tb-0f1c3b46", "disk.smart", "critical",
              "A drive is failing: Samsung SSD 980 PRO 2TB (nvme0)",
              "Its own health check says FAILED. Copy your files off it now, then replace it.", "nvme0",
              ["bromigos storage health nvme0", "sudo smartctl -a /dev/nvme0"])
BACKUP = alert("backup.restic:server", "backup.restic", "needs_you", "The last backup failed",
               "restic couldn't reach 192.168.1.20:8000 or fd12:3456:789a::1 with password=hunter2hunter2.", "server",
               ["sudo bromigos lab backups status"])
GOBAG = alert("backup.restic:server-drive", "backup.restic", "needs_you",
              "Your Go Bag drive hasn't been updated in 31 days", "Plug it in.", "server-drive")
UPDATES = alert("update.waiting", "update.waiting", "info", "12 updates are waiting")


class Stand(http.server.BaseHTTPRequestHandler):
    def do_POST(self):
        body = self.rfile.read(int(self.headers.get("Content-Length") or 0))
        self.server.got.append({"path": self.path, "headers": dict(self.headers), "raw": body, "body": json.loads(body)})
        status, extra = self.server.answers.pop(0) if self.server.answers else (204, {})
        self.send_response(status)
        for k, v in extra.items():
            self.send_header(k, v)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def log_message(self, *a):
        pass


class Channels(unittest.TestCase):
    def setUp(self):
        self.m = FakeMachine(role="server")
        self.m.rootfile("/etc/hostname", "myserver\n")
        self.srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Stand)
        self.srv.got, self.srv.answers = [], []
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self.base = f"http://127.0.0.1:{self.srv.server_address[1]}"
        self.slept = []
        self.outputs = []                          # every printed output, for the no-secret check

    def tearDown(self):
        self.srv.shutdown()
        self.srv.server_close()
        self.m.close()

    # -- helpers
    def env(self, **extra):
        return self.m.env(**extra)

    def doc(self, *alerts):
        A.write_json(str(self.m.root / "var/lib/bromigos/alerts/system.json"),
                     {"schema": 1, "scope": "system", "role": "server", "checked_at": self.m.now, "checks": [],
                      "alerts": list(alerts)})

    def channel(self, kind="discord", name=None, **opts):
        """A channel added as the command adds one, its address then pointed at the stand-in."""
        name = name or kind
        url = DISCORD if kind == "discord" else f"https://hooks.example.org/in/{TOKEN}"
        N.add(self.env(), kind, name, url, KEY if kind == "webhook" else None, **opts)
        N.write_secret(self.env(), name, "url", f"{self.base}/{name}/{TOKEN}")
        return name

    def deliver(self):
        return N.deliver(self.env(), sleep=self.slept.append)

    def bodies(self, path=None):
        return [g["body"] for g in self.srv.got if path is None or g["path"].startswith(f"/{path}/")]

    def cli(self, *args, stdin=None):
        e = dict(self.env().environ)
        e.pop("WAYLAND_DISPLAY", None)
        e.pop("DISPLAY", None)
        r = subprocess.run([sys.executable, str(SCRIPT), *args], env=e, capture_output=True, text=True, input=stdin)
        self.outputs.append(r.stdout + r.stderr)
        return r

    def assertNothingSecret(self):
        """No address, token, key, LAN address, evidence or password anywhere but the secret files."""
        texts = [g["raw"].decode() for g in self.srv.got] + self.outputs
        for p in (self.m.root / "var/lib/bromigos/alerts/channels").glob("*.json"):
            texts.append(p.read_text())
        texts.append((self.m.root / "etc/bromigos/alerts.toml").read_text())
        for t in texts:
            for bad in (TOKEN, KEY, "hooks.example.org", "192.168.1.20", "fd12:3456", "hunter2", "EVIDENCE-LINE",
                        "S6B0NX0T"):
                self.assertNotIn(bad, t)

    # -- Discord
    def test_discord_is_minimal_by_default(self):
        self.channel("discord")
        self.doc(DRIVE, BACKUP, UPDATES)
        rows = self.deliver()
        self.assertEqual(rows[0]["messages"], 1, rows)
        [b] = self.bodies()
        self.assertEqual(b["username"], "bromigOS")
        self.assertEqual(b["allowed_mentions"], {"parse": []})      # no alert text can ping anyone
        [e] = b["embeds"]
        self.assertEqual(e["title"], "2 alerts need you on your lab (1 critical)")
        self.assertEqual(e["color"], N.COLOUR["critical"])
        self.assertIn("BRODEC", e["description"])
        text = json.dumps(b)
        for leak in ("myserver", "nvme0", "Samsung", "smartctl", "backup failed"):
            self.assertNotIn(leak, text)                             # minimal: nothing about the machine
        self.assertNothingSecret()

    def test_minimal_carries_the_boards_address_when_set(self):
        self.m.rootfile("/etc/bromigos/alerts.toml", '[notify]\nboard = "https://myserver.local"\n')
        self.channel("discord")
        self.doc(BACKUP)
        self.deliver()
        [e] = self.bodies()[0]["embeds"]
        self.assertEqual(e["title"], "1 alert needs you on your lab")
        self.assertEqual(e["url"], "https://myserver.local")
        self.assertIn("Open the Lab board: https://myserver.local", e["description"])

    def test_discord_full_is_an_embed_per_alert(self):
        self.channel("discord", detail="full")
        self.doc(DRIVE, BACKUP)
        self.deliver()
        [b] = self.bodies()
        drive, backup = b["embeds"]
        self.assertEqual(drive["title"], DRIVE["title"])
        self.assertEqual(drive["color"], 0xE5484D)
        self.assertEqual(backup["color"], 0xF5A524)
        self.assertIn("```sh\nbromigos storage health nvme0\nsudo smartctl -a /dev/nvme0\n```", drive["description"])
        fields = {f["name"]: f["value"] for f in drive["fields"]}
        self.assertEqual(fields["Machine"], "myserver")
        self.assertEqual(fields["Device"], "nvme0")
        self.assertEqual(fields["Since"], f"<t:{(NOW - HOUR) // 1000}:R>")
        self.assertEqual(fields["Severity"], "Critical")
        # the sentence leaves out the LAN addresses and the password, and evidence never goes
        self.assertIn("[address]", backup["description"])
        self.assertNothingSecret()

    def test_many_alerts_take_several_messages(self):
        self.channel("discord", detail="full")
        self.doc(*[alert(f"systemd.failed:s{i}.service", "systemd.failed", "needs_you", f"s{i} stopped") for i in range(6)])
        self.deliver()
        self.assertEqual([len(b["embeds"]) for b in self.bodies()], [4, 2])

    # -- the webhook
    def test_the_webhook_is_signed_with_its_key(self):
        self.channel("webhook", name="ha")
        self.doc(DRIVE, BACKUP)
        self.deliver()
        [g] = self.srv.got
        sig = "sha256=" + hmac.new(KEY.encode(), g["raw"], hashlib.sha256).hexdigest()
        self.assertEqual(g["headers"]["X-Bromigos-Signature-256"], sig)
        self.assertEqual(g["headers"]["X-Bromigos-Schema"], "1")
        self.assertEqual(g["headers"]["X-Bromigos-Event"], "alerts")
        b = g["body"]
        self.assertEqual((b["schema"], b["type"], b["detail"], b["machine"], b["test"]),
                         (1, "bromigos.alerts", "full", "myserver", False))
        self.assertEqual(b["delivery"], g["headers"]["X-Bromigos-Delivery"])
        drive = b["events"][0]
        self.assertEqual((drive["event"], drive["severity"], drive["source"]), ("alert.opened", "critical", "drives"))
        self.assertEqual(drive["alert"]["id"], DRIVE["id"])
        self.assertEqual(drive["alert"]["fix"]["commands"], DRIVE["fix"]["commands"])
        self.assertNotIn("evidence", drive["alert"])
        # a body changed on the way doesn't match
        self.assertNotEqual(sig, N.sign(KEY, g["raw"] + b" "))
        self.assertNothingSecret()

    def test_a_minimal_webhook_names_no_alert(self):
        self.channel("webhook", name="ha", detail="minimal")
        self.doc(DRIVE)
        self.deliver()
        b = self.bodies()[0]
        self.assertIsNone(b["machine"])
        self.assertEqual(b["events"], [{"event": "alert.opened", "severity": "critical", "source": "drives",
                                        "ref": N.ref(DRIVE["id"]), "since": NOW - HOUR}])
        self.assertEqual(b["summary"], ["1 alert needs you on your lab (1 critical)"])

    # -- the rules
    def test_each_alert_once_then_critical_again_after_6_hours(self):
        self.channel("webhook", name="ha")
        self.doc(DRIVE, BACKUP)
        self.deliver()
        self.deliver()
        self.assertEqual(len(self.srv.got), 1)                       # dedupe by id
        self.m.now += 6 * HOUR - MIN
        self.deliver()
        self.assertEqual(len(self.srv.got), 1)
        self.m.now += MIN
        self.deliver()
        [ev] = self.bodies()[-1]["events"]
        self.assertEqual((ev["event"], ev["alert"]["id"]), ("alert.reminder", DRIVE["id"]))   # not needs-you's
        # one that gets worse goes again at once
        self.doc(DRIVE, dict(BACKUP, severity="critical"))
        self.deliver()
        [ev] = self.bodies()[-1]["events"]
        self.assertEqual((ev["event"], ev["alert"]["id"]), ("alert.worse", BACKUP["id"]))

    def test_resolved_only_when_asked(self):
        self.channel("webhook", name="ha", resolved=True)
        self.channel("discord", detail="full")
        self.doc(BACKUP)
        self.deliver()
        self.doc()
        self.deliver()
        [ev] = self.bodies("ha")[-1]["events"]
        self.assertEqual(ev["event"], "alert.resolved")
        self.assertEqual(len(self.bodies("discord")), 1)             # Discord didn't ask
        # it comes back: after a cleared message, it is news again
        self.doc(BACKUP)
        self.deliver()
        self.assertEqual(self.bodies("ha")[-1]["events"][0]["event"], "alert.opened")
        self.assertEqual(len(self.bodies("discord")), 1)             # within 30 min: no new message
        self.doc()
        self.deliver()
        self.m.now += 31 * MIN
        self.deliver()
        self.doc(BACKUP)
        self.deliver()
        self.assertEqual(len(self.bodies("discord")), 2)             # gone for longer: it opens again
        self.assertEqual(self.bodies("discord")[-1]["embeds"][0]["title"], BACKUP["title"])

    def test_severities_and_sources(self):
        self.channel("webhook", name="drives", sources=["drives"])
        self.channel("webhook", name="bag", sources=["go-bag"], severities=["needs_you"])
        self.channel("webhook", name="all", severities=["critical", "needs_you", "info"])
        self.doc(DRIVE, BACKUP, GOBAG, UPDATES)
        self.deliver()
        got = {n: [e["alert"]["id"] for e in self.bodies(n)[0]["events"]] for n in ("drives", "bag", "all")}
        self.assertEqual(got["drives"], [DRIVE["id"]])
        self.assertEqual(got["bag"], [GOBAG["id"]])
        self.assertEqual(set(got["all"]), {DRIVE["id"], BACKUP["id"], GOBAG["id"], UPDATES["id"]})

    def test_quiet_hours(self):
        self.channel("webhook", name="quiet", quiet="22:00-07:00")
        self.channel("webhook", name="loud", quiet="22:00-07:00", critical_in_quiet=True)
        self.m.now = NOW - NOW % (24 * HOUR) + 23 * HOUR           # 23:00
        self.doc(DRIVE, BACKUP)
        rows = {r["channel"]: r for r in self.deliver()}
        self.assertEqual(self.bodies("quiet"), [])
        self.assertEqual((rows["quiet"]["held"], rows["quiet"]["why_held"]), (2, "quiet hours (22:00-07:00)"))
        self.assertEqual([e["alert"]["id"] for e in self.bodies("loud")[0]["events"]], [DRIVE["id"]])
        self.m.now += 2 * HOUR                                      # 01:00: still quiet
        self.deliver()
        self.assertEqual((len(self.bodies("quiet")), len(self.bodies("loud"))), (0, 1))
        self.m.now += 6 * HOUR + 30 * MIN                           # 07:30: what waited goes
        self.deliver()
        self.assertEqual(len(self.bodies("quiet")[0]["events"]), 2)
        # the critical one went at 23:00, so 6 hours on it is a reminder; the other opens now
        self.assertEqual(sorted((e["event"], e["alert"]["id"]) for e in self.bodies("loud")[1]["events"]),
                         [("alert.opened", BACKUP["id"]), ("alert.reminder", DRIVE["id"])])

    def test_the_rate_limit_holds_the_rest_until_the_hour_frees(self):
        self.channel("discord", detail="full", per_hour=1)
        self.doc(*[alert(f"systemd.failed:s{i}.service", "systemd.failed", "needs_you", f"s{i} stopped") for i in range(6)])
        [r] = self.deliver()
        self.assertEqual((r["messages"], r["events"], r["held"]), (1, 4, 2))
        self.assertIn("1 messages an hour", r["why_held"])
        self.m.now += 30 * MIN
        self.deliver()
        self.assertEqual(len(self.srv.got), 1)
        self.m.now += 31 * MIN
        self.deliver()
        self.assertEqual([len(b["embeds"]) for b in self.bodies()], [4, 2])

    def test_retries_then_backs_off_then_recovers(self):
        self.channel("webhook", name="ha")
        self.doc(BACKUP)
        self.srv.answers = [(500, {}), (502, {}), (503, {})]
        [r] = self.deliver()
        self.assertEqual(len(self.srv.got), 3)
        self.assertEqual(self.slept, [1, 2])
        self.assertEqual(r["error"], "the channel answered 503")
        st = N.load_state(self.env(), "ha")
        self.assertEqual((st["failures"], st["retry_at"]), (1, self.m.now + MIN))
        self.deliver()                                               # backing off: no try
        self.assertEqual(len(self.srv.got), 3)
        self.srv.answers = [(500, {})] * 3
        self.m.now += MIN
        self.deliver()
        self.assertEqual(N.load_state(self.env(), "ha")["retry_at"], self.m.now + 2 * MIN)   # 1, 2, 4 … 60 min
        self.m.now += 2 * MIN
        [r] = self.deliver()
        self.assertEqual((r["messages"], r["error"]), (1, None))
        self.assertEqual(self.bodies()[-1]["events"][0]["alert"]["id"], BACKUP["id"])
        self.assertEqual(N.load_state(self.env(), "ha")["failures"], 0)
        self.deliver()
        self.assertEqual(len(self.srv.got), 7)                      # and only once

    def test_429_waits_as_told_and_404_isnt_tried_again(self):
        self.channel("webhook", name="ha")
        self.doc(BACKUP)
        self.srv.answers = [(429, {"Retry-After": "3"})]
        [r] = self.deliver()
        self.assertEqual((self.slept, r["messages"]), ([3], 1))
        self.doc(BACKUP, DRIVE)
        self.srv.answers = [(404, {})]
        [r] = self.deliver()
        self.assertEqual(len(self.srv.got), 3)
        self.assertEqual(r["error"], "the channel answered 404 (the address is gone)")

    def test_an_unreachable_channel_doesnt_stop_the_others(self):
        self.channel("webhook", name="gone")
        self.channel("webhook", name="ha")
        N.write_secret(self.env(), "gone", "url", "http://127.0.0.1:9/nothing")
        self.doc(BACKUP)
        rows = {r["channel"]: r for r in self.deliver()}
        self.assertIn("couldn't reach it", rows["gone"]["error"])
        self.assertEqual(rows["ha"]["messages"], 1)

    # -- jobs and the catalogue
    def job(self, now, ok=True, ask=False, **env):
        import bromigos_activity as J
        e = J.Env({"BROMIGOS_ROOT": str(self.m.root), "BROMIGOS_ACTIVITY_NOW_MS": str(now), "PATH": "", **env})
        j = J.Job(e, "backup.run", "Backing up", None, ["true"]).open()
        j.begin()
        j.feed("::step copy running Copying")
        if ask:
            j.feed("::ask swap Swap the drive now? [yes] Yes [no] No")
            j.save()
            return j                                                 # still running: its lock is held
        if not ok:
            j.feed("::error copy The repository is locked.")
        j.finish(0 if ok else 1)
        j.close()
        return j

    def test_job_results_are_opt_in(self):
        self.channel("webhook", name="ha")
        self.channel("webhook", name="jobs", sources=["job-results"])
        self.doc()
        self.deliver()
        self.m.now += MIN
        self.job(self.m.now, ok=True)
        self.job(self.m.now, ok=False)
        asking = self.job(self.m.now, ask=True)
        self.deliver()
        self.assertEqual(self.bodies("ha"), [])
        evs = sorted((e["event"], e["job"]["state"]) for e in self.bodies("jobs")[0]["events"])
        self.assertEqual(evs, [("job.failed", "failed"), ("job.needs-you", "needs-you"), ("job.succeeded", "succeeded")])
        q = next(e for e in self.bodies("jobs")[0]["events"] if e["event"] == "job.needs-you")
        self.assertEqual(q["sentence"], "It asks: Swap the drive now?")
        self.assertEqual(q["job"]["question"]["choices"], ["yes", "no"])
        self.deliver()
        self.assertEqual(len(self.bodies("jobs")), 1)
        asking.close()

    def test_a_job_that_asks_or_ends_starts_the_delivery(self):
        import bromigos_activity as J
        kicked = self.m.root.parent / "kicked"
        stub = self.m.root.parent / "kick"
        stub.write_text(f"#!/bin/sh\necho kicked >> '{kicked}'\n")
        stub.chmod(0o755)
        env = J.Env({"BROMIGOS_ROOT": str(self.m.root), "PATH": "", "BROMIGOS_NOTIFY_KICK": str(stub)})

        def kicks(n):
            for _ in range(50):
                if kicked.exists() and len(kicked.read_text().split()) >= n:
                    break
                time.sleep(0.1)
            time.sleep(0.2)
            return len(kicked.read_text().split()) if kicked.exists() else 0

        with J.job("backup.run", "Backing up", env=env):
            pass
        self.assertEqual(kicks(1), 0)                                # no channel: nothing started
        self.channel("webhook", name="ha")
        with J.job("backup.run", "Backing up", env=env):
            pass
        self.assertEqual(kicks(1), 1)                                # ended: after its alert was written
        self.job(self.m.now, ask=True, BROMIGOS_NOTIFY_KICK=str(stub)).close()
        self.assertEqual(kicks(2), 1)                                # a question: only for job-results
        self.channel("webhook", name="jobs", sources=["job-results"])
        self.job(self.m.now, ask=True, BROMIGOS_NOTIFY_KICK=str(stub)).close()
        self.assertEqual(kicks(2), 2)

    def test_the_catalogue_says_when_new_models_wait_for_review(self):
        cat = self.m.rootfile("/usr/share/bromigos-lab/models.toml",
                              '[[pending]]\nid = "hf:a/one"\ntitle = "a/one"\nstate = "pending review"\n')
        self.channel("webhook", name="ha", sources=["catalogue"])
        self.doc(DRIVE)
        self.deliver()
        self.assertEqual(self.srv.got, [])                           # the first look: known already; no alerts asked
        cat.write_text(cat.read_text() + '[[pending]]\nid = "hf:b/two"\ntitle = "b/two: newer"\nstate = "pending review"\n'
                                         '[[pending]]\nid = "hf:c/old"\ntitle = "c/old"\nstate = "dismissed"\n')
        self.deliver()
        [ev] = self.bodies()[0]["events"]
        self.assertEqual((ev["event"], ev["title"], ev["sentence"], ev["fix"]),
                         ("catalogue.review", "1 new model to review in the lab's model catalogue", "b/two: newer",
                          ["bromigos lab models refresh"]))
        self.deliver()
        self.assertEqual(len(self.srv.got), 1)

    # -- the commands
    def test_add_reads_the_address_from_stdin_never_argv(self):
        e = dict(self.env().environ)
        e.pop("WAYLAND_DISPLAY", None)
        e.pop("DISPLAY", None)
        p = subprocess.Popen([sys.executable, str(SCRIPT), "channels", "add", "discord", "--severity", "critical"],
                             env=e, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                             start_new_session=True)
        try:
            time.sleep(0.5)                                          # waiting on its stdin now
            seen = []
            for d in Path("/proc").iterdir():
                if d.name.isdigit():
                    try:
                        seen.append((d / "cmdline").read_bytes().decode(errors="replace"))
                    except OSError:
                        pass
            self.assertTrue(any("channels\0add\0discord" in c for c in seen))   # it is the process we look at
            self.assertFalse(any(TOKEN in c for c in seen))
            ps = subprocess.run(["ps", "-eo", "args"], capture_output=True, text=True) if os.path.exists("/usr/bin/ps") else None
            if ps is not None:
                self.assertNotIn(TOKEN, ps.stdout)
            out, err = p.communicate(DISCORD + "\n", timeout=30)
        finally:
            if p.poll() is None:
                os.killpg(p.pid, signal.SIGKILL)
        self.outputs.append(out + err)
        self.assertEqual(p.returncode, 0, err)
        self.assertIn("Added discord: minimal detail", out)
        secret = self.m.root / "etc/bromigos/alerts-channels/discord.url"
        self.assertEqual(secret.read_text().strip(), DISCORD)
        self.assertEqual(stat.S_IMODE(secret.stat().st_mode), 0o600)
        self.assertEqual(stat.S_IMODE(secret.parent.stat().st_mode), 0o700)
        self.assertNothingSecret()

    def test_an_address_typed_as_an_argument_is_refused(self):
        r = self.cli("channels", "add", "discord", DISCORD, stdin="")
        self.assertEqual(r.returncode, 2)
        self.assertNotIn(TOKEN, r.stderr + r.stdout)
        r = self.cli("channels", "add", "discord", stdin="https://example.org/not-discord\n")
        self.assertEqual(r.returncode, 2)
        self.assertIn("isn't a Discord webhook address", r.stderr)

    def test_list_test_send_remove_and_the_settings_file(self):
        self.m.rootfile("/etc/bromigos/alerts.toml", "# mine\n[disk]\nfull_percent = 85\n")
        self.m.rootfile("/etc/brodec-machine/machine.toml", "")
        r = self.cli("channels", "add", "webhook", "ha", "--sources", "drives,job-results", "--quiet", "22:00-07:00",
                     "--resolved", stdin=f"https://hooks.example.org/in/{TOKEN}\n\n")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("A signing key was made", r.stdout)
        self.assertNotIn("sha256", r.stdout)
        made = (self.m.root / "etc/bromigos/alerts-channels/ha.key").read_text().strip()
        self.assertEqual(len(made), 64)
        self.assertNotIn(made, r.stdout)
        text = (self.m.root / "etc/bromigos/alerts.toml").read_text()
        self.assertTrue(text.startswith("# mine\n[disk]\nfull_percent = 85\n"))      # the rest kept
        self.assertEqual(A.settings(self.env())["disk"]["full_percent"], 85)
        N.write_secret(self.env(), "ha", "url", f"{self.base}/ha/{TOKEN}")
        self.cli("channels", "add", "discord", stdin=DISCORD + "\n")
        N.write_secret(self.env(), "discord", "url", f"{self.base}/discord/{TOKEN}")

        r = self.cli("channels", "--json")
        doc = json.loads(r.stdout)
        rows = {x["name"]: x for x in doc["channels"]}
        self.assertEqual(set(rows), {"ha", "discord", "brodec"})
        self.assertEqual((rows["ha"]["address"], rows["ha"]["key"], rows["ha"]["quiet"]), ("set", "set", "22:00-07:00"))
        self.assertEqual(rows["ha"]["sources"], ["drives", "job-results"])
        self.assertEqual(rows["discord"]["detail"], "minimal")
        self.assertEqual((rows["brodec"]["read_only"], rows["brodec"]["on"], rows["brodec"]["label"]),
                         (True, True, "BRODEC (paired phone)"))
        self.assertIn("channels", json.loads(self.cli("--json").stdout))   # the board's data
        r = self.cli("channels")
        self.assertIn("address set; signing key set; quiet 22:00-07:00", r.stdout)
        self.assertIn("BRODEC (paired phone)", r.stdout)

        r = self.cli("channels", "test", "discord")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue(self.bodies("discord")[0]["embeds"][0]["title"].startswith("TEST · "))
        r = self.cli("channels", "test", "ha", "--json")
        self.assertTrue(json.loads(r.stdout)["ok"])
        self.assertTrue(self.bodies("ha")[0]["test"])
        self.assertEqual(self.cli("channels", "test", "nope").returncode, 3)
        self.assertEqual(self.cli("channels", "remove", "brodec").returncode, 3)

        self.doc(DRIVE)
        r = self.cli("channels", "send", "--json")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual({x["channel"]: x["messages"] for x in json.loads(r.stdout)}, {"ha": 1, "discord": 1})
        self.srv.answers = [(500, {})] * 3
        self.doc(DRIVE, BACKUP)
        r = self.cli("channels", "send")
        self.assertEqual(r.returncode, 1)
        self.assertIn("problem: the channel answered 500", r.stdout)
        r = self.cli("channels")
        self.assertIn("last problem", r.stdout)

        self.assertEqual(self.cli("channels", "remove", "ha").returncode, 0)
        self.assertFalse((self.m.root / "etc/bromigos/alerts-channels/ha.key").exists())
        text = (self.m.root / "etc/bromigos/alerts.toml").read_text()
        self.assertNotIn("[channels.ha]", text)
        self.assertIn("[channels.discord]", text)
        self.assertIn("full_percent = 85", text)
        self.assertNothingSecret()

    def test_not_root_cant_touch_the_addresses(self):
        if os.geteuid() == 0:
            self.skipTest("running as root")
        e = dict(self.env().environ)
        e.pop("BROMIGOS_ALERTS_ROOT")
        for args in (["add", "discord"], ["test", "discord"], ["send"], ["remove", "discord"]):
            r = subprocess.run([sys.executable, str(SCRIPT), "channels", *args], env=e, capture_output=True,
                               text=True, input="")
            self.assertEqual(r.returncode, 3, args)
            self.assertIn("sudo bromigos alerts channels", r.stderr)

    def test_a_wrong_setting_is_said_not_used(self):
        self.m.rootfile("/etc/bromigos/alerts.toml", '[channels.x]\ntype = "discord"\nsources = ["drivez"]\nquiet = "late"\n')
        N.write_secret(self.env(), "x", "url", f"{self.base}/x/{TOKEN}")
        self.doc(DRIVE)
        [r] = self.deliver()
        self.assertIn("drivez unknown", r["error"])
        self.assertEqual(self.srv.got, [])


if __name__ == "__main__":
    unittest.main()
