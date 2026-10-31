"""`bromigos alerts` on a stand-in machine (tests/alerts/fake.py): every check raising its alert,
each one resolving when its cause clears, first-seen times kept, a check that can't look keeping
what it found, your own checks, and the desktop notification's dedup and cooldown. No root, no
network, no real notification, nothing on this machine read or changed."""
import json
import os
import stat
import subprocess
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import fake  # noqa: E402
from fake import FakeMachine, NOW  # noqa: E402

import bromigos_alerts as A  # noqa: E402
import bromigos_alerts_checks as C  # noqa: E402

SCRIPT = fake.REPO / "bin/bromigos-alerts"
HOUR = 3600_000


def ids(doc):
    return {a["id"]: a["severity"] for a in doc["alerts"]}


def states(doc):
    return {c["check"]: c["state"] for c in doc["checks"]}


class Machine(unittest.TestCase):
    role = "desktop"

    def setUp(self):
        self.m = FakeMachine(role=self.role)

    def tearDown(self):
        self.m.close()


class EveryCheck(Machine):
    role = "server"

    def test_every_check_raises_its_alert_and_resolves_when_it_clears(self):
        self.m.broken()
        system = self.m.run("system", boot=True)
        user = self.m.run("user")
        got = dict(ids(system), **ids(user))
        want = {
            "disk.smart:nvme0": "critical", "disk.smart:sda": "needs_you",
            "disk.scrub:/": "critical",
            "disk.full:/": "needs_you", "disk.full:/mnt/Media": "critical",
            "update.waiting": "needs_you",           # nothing installed for 40 days
            "update.restart": "needs_you",
            "update.held": "needs_you",
            "backup.restic:restic-backup": "needs_you",
            "power.ups:rack": "critical",
            "systemd.failed:nginx.service": "needs_you",
            "systemd.failed:syncthing.service": "needs_you",
            "server.game:valheim": "needs_you", "server.game:container-minecraft": "needs_you",
            "game.steam:nvapi": "needs_you", "game.steam:default": "info", "game.steam:prune": "info",
        }
        for k, v in want.items():
            self.assertEqual(got.get(k), v, k)
        fk = [a for a in system["alerts"] if a["check"] == "fieldkit.finding"]
        self.assertEqual(len(fk), 2, fk)
        # every check in the registry found something on the broken machine
        self.assertEqual({c.name for c in C.REGISTRY}, {a["check"] for a in system["alerts"] + user["alerts"]})
        self.assertTrue(all(s == "ran" for s in states(system).values()), states(system))
        # what never matters isn't raised
        self.assertNotIn("systemd.failed:NetworkManager-wait-online.service", got)
        self.assertNotIn("systemd.failed:run-u42.service", got)
        # the document's shape (SPEC.md)
        self.assertEqual((system["schema"], system["scope"], system["role"], system["checked_at"]),
                         (1, "system", "server", NOW))
        for a in system["alerts"] + user["alerts"]:
            self.assertRegex(a["id"], r"^[A-Za-z0-9._:/@+-]{1,160}$")
            self.assertLessEqual(len(a["title"]), 120)
            self.assertLessEqual(len(a["detail"]), 600)
            self.assertIn(a["severity"], A.SEVERITIES)
            self.assertEqual(a["since"], NOW)
            self.assertLessEqual(len(a["evidence"]["lines"]), 40)
        # worst first
        ranks = [A.RANK[a["severity"]] for a in system["alerts"]]
        self.assertEqual(ranks, sorted(ranks, reverse=True))
        # the files: the system's readable by the machine agent, yours only by you
        sysdoc = self.m.root / "var/lib/bromigos/alerts/system.json"
        userdoc = self.m.home / ".local/state/bromigos/alerts/user.json"
        self.assertEqual(stat.S_IMODE(sysdoc.stat().st_mode), 0o644)
        self.assertEqual(stat.S_IMODE(userdoc.stat().st_mode), 0o600)
        self.assertEqual(json.loads(sysdoc.read_text()), system)
        # all clear: every alert resolves, every check still ran
        self.m.clear()
        self.m.now += 15 * 60_000
        system = self.m.run("system", boot=True)
        user = self.m.run("user")
        self.assertEqual(system["alerts"] + user["alerts"], [])
        self.assertTrue(all(s == "ran" for s in states(system).values()), states(system))

    def test_the_fixes_come_from_bromigos_own_logic(self):
        self.m.broken()
        doc = {a["id"]: a for a in self.m.run("system", boot=True)["alerts"]}
        scrub = doc["disk.scrub:/"]["fix"]
        self.assertEqual(scrub["from"], "fieldkit")
        self.assertIn("sudo btrfs scrub start -B -r /", scrub["commands"])
        sddm = [a for a in doc.values() if "sddm" in a["title"]][0]
        self.assertEqual(sddm["fix"]["from"], "fieldkit")
        self.assertTrue(any(c.startswith("mv /etc/sddm.conf.d/") for c in sddm["fix"]["commands"]))
        held = doc["update.held"]
        self.assertTrue(held["link"].startswith("https://archlinux.org/news/"))
        self.assertIn("sudo bromigos server update --now", held["fix"]["commands"])
        self.assertIn({"kind": "restart", "label": "Restart now"}, doc["update.restart"]["actions"])
        nginx = doc["systemd.failed:nginx.service"]
        self.assertTrue(any("Address already in use" in x for x in nginx["evidence"]["lines"]))
        user = {a["id"]: a for a in self.m.run("user")["alerts"]}
        self.assertEqual(user["game.steam:nvapi"]["fix"]["commands"], ["bromigos game check --fix"])
        self.assertIn("by itself", user["game.steam:default"]["detail"])


class Since(Machine):
    def test_first_seen_is_kept_and_a_new_firing_starts_again(self):
        self.m.disk_space(93)
        first = self.m.run()
        self.assertEqual(ids(first)["disk.full:/"], "needs_you")
        self.m.now += HOUR
        self.m.disk_space(98)
        second = self.m.run()
        a = [x for x in second["alerts"] if x["id"] == "disk.full:/"][0]
        self.assertEqual((a["severity"], a["since"]), ("critical", NOW))
        self.m.disk_space(50)
        self.m.now += HOUR
        self.assertNotIn("disk.full:/", ids(self.m.run()))
        self.m.disk_space(93)
        self.m.now += HOUR
        again = [x for x in self.m.run()["alerts"] if x["id"] == "disk.full:/"][0]
        self.assertEqual(again["since"], NOW + 3 * HOUR)

    def test_disk_full_has_hysteresis_and_settings(self):
        self.m.disk_space(91)
        self.assertIn("disk.full:/", ids(self.m.run()))
        self.m.disk_space(89)                       # under 90, not under 88: still raised
        self.assertIn("disk.full:/", ids(self.m.run()))
        self.m.disk_space(87)
        self.assertNotIn("disk.full:/", ids(self.m.run()))
        self.m.rootfile("/etc/bromigos/alerts.toml", '[disk]\nfull_percent = 80\nignore = ["/mnt/Media"]\n')
        self.m.disk_space(85, media_pct=99)
        got = ids(self.m.run())
        self.assertEqual(got.get("disk.full:/"), "needs_you")
        self.assertNotIn("disk.full:/mnt/Media", got)


class Failing(Machine):
    def test_a_check_that_cant_look_keeps_what_it_found(self):
        self.m.broken()
        first = self.m.run()
        self.assertIn("disk.smart:nvme0", ids(first))
        (self.m.bin / "smartctl").write_text("#!/bin/sh\necho 'not json'\n")
        second = self.m.run()
        row = [c for c in second["checks"] if c["check"] == "disk.smart"][0]
        self.assertEqual(row["state"], "failed")
        self.assertIn("no answer", row["error"])
        self.assertEqual(ids(second)["disk.smart:nvme0"], "critical")
        self.assertEqual(ids(second)["disk.smart:sda"], "needs_you")

    def test_a_missing_tool_or_a_check_turned_off_is_skipped(self):
        (self.m.bin / "smartctl").unlink()
        (self.m.bin / "upsc").unlink()
        self.m.rootfile("/etc/bromigos/alerts.toml", '[checks]\noff = ["disk.scrub"]\n')
        st = states(self.m.run())
        self.assertEqual((st["disk.smart"], st["power.ups"], st["disk.scrub"]), ("skipped", "skipped", "skipped"))
        # on a desktop: no automatic updates to hold, no game servers
        self.assertEqual((st["update.held"], st["server.game"]), ("skipped", "skipped"))

    def test_a_broken_check_never_stops_the_others(self):
        def boom(ctx):
            raise RuntimeError("bug")
        reg = list(C.REGISTRY)
        C.REGISTRY.insert(0, C.Check("disk.boom", ["system"], boom))
        try:
            doc = self.m.run()
        finally:
            C.REGISTRY[:] = reg
        self.assertEqual(states(doc)["disk.boom"], "failed")
        self.assertEqual(states(doc)["disk.full"], "ran")


class Checks(Machine):
    def test_failed_units_that_matter(self):
        self.m.write("failed", "sshd.service loaded failed failed OpenSSH Daemon\nmasked.service loaded failed failed m\n"
                               "nginx.service loaded failed failed web\n")
        self.m.write("show/sshd.service", "Transient=no\nUnitFileState=enabled\nDescription=OpenSSH Daemon\nResult=exit-code\n")
        self.m.write("show/masked.service", "Transient=no\nUnitFileState=masked\nDescription=m\n")
        self.m.write("show/nginx.service", "Transient=yes\nUnitFileState=\nDescription=web\n")
        self.assertEqual(ids(self.m.run()), {"systemd.failed:sshd.service": "needs_you"})
        self.m.rootfile("/etc/bromigos/alerts.toml", '[units]\nignore = ["sshd.service"]\n')
        self.assertEqual(ids(self.m.run()), {})

    def test_updates_waiting_and_a_restart(self):
        self.m.write("update-check.json", {"schema": 1, "check": {"packages": [{"name": "mesa", "from": "1", "to": "2"}],
                                                                   "aur": {"packages": [{"name": "paru", "from": "1", "to": "2"}]}}})
        a = self.m.run("user")["alerts"][0]
        self.assertEqual((a["id"], a["severity"], a["title"]), ("update.waiting", "info", "2 updates waiting"))
        self.assertEqual(a["actions"][0]["kind"], "update")
        self.m.write("update-check.json", {"schema": 1, "check": {"packages": None}})
        doc = self.m.run("user")
        self.assertEqual(states(doc)["update.waiting"], "failed")
        # a new kernel only
        self.m.rootfile("/usr/lib/modules/7.2.12-arch1-1/vmlinuz", "")
        import shutil
        shutil.rmtree(self.m.root / "usr/lib/modules/7.2.11-arch1-1")
        a = [x for x in self.m.run()["alerts"] if x["id"] == "update.restart"][0]
        self.assertEqual(a["title"], "Restart to finish the update: a new kernel")
        # a folder a removed kernel left behind (no image, no modules) doesn't count
        self.m.rootfile("/usr/lib/modules/7.2.11-arch1-1/modules.weakdep", "")
        self.assertIn("update.restart", ids(self.m.run()))
        self.m.rootfile("/usr/lib/modules/7.2.11-arch1-1/vmlinuz", "")
        self.assertNotIn("update.restart", ids(self.m.run()))

    def test_a_backup_that_is_late(self):
        self.m.write("show/restic-backup.service", "ActiveState=inactive\nResult=success\nExecMainStatus=0\n"
                     f"ExecMainExitTimestamp=@{NOW // 1000 - 48 * 3600}\nDescription=restic backup\n"
                     "TriggeredBy=restic-backup.timer\n")
        a = [x for x in self.m.run()["alerts"] if x["check"] == "backup.restic"][0]
        self.assertEqual(a["title"], "No backup for 48 hours: restic-backup")
        self.m.write("backup-units", "")
        self.assertEqual(states(self.m.run())["backup.restic"], "skipped")

    def test_bromigos_servers_own_backup(self):
        state = self.m.root / "var/lib/bromigos/server/backup.json"
        state.parent.mkdir(parents=True, exist_ok=True)
        state.write_text(json.dumps({"run": {"phase": "failed", "at": "2026-10-30T03:10:00-07:00",
                                             "ts": NOW / 1000 - 3600, "reason": "the destination can't be reached"},
                                     "check": {"phase": "failed", "at": "x", "reason": "pack 3f2a is damaged"}}))
        got = {a["id"]: a for a in self.m.run()["alerts"]}
        self.assertEqual(got["backup.restic:server"]["title"], "The last backup failed")
        self.assertIn("can't be reached", got["backup.restic:server"]["detail"])
        self.assertEqual(got["backup.restic:server-check"]["severity"], "needs_you")
        state.write_text(json.dumps({"run": {"phase": "ok", "at": "2026-10-28", "ts": NOW / 1000 - 50 * 3600}}))
        self.assertEqual(self.m.run()["alerts"][0]["title"], "No backup for 50 hours")
        state.write_text(json.dumps({"run": {"phase": "ok", "at": "today", "ts": NOW / 1000 - 3600}}))
        self.assertNotIn("backup.restic:server", ids(self.m.run()))

    def test_the_ups(self):
        self.m.write("ups/rack", "battery.charge: 80\nbattery.runtime: 1500\nups.status: OB DISCHRG\n")
        a = self.m.run()["alerts"][0]
        self.assertEqual((a["id"], a["severity"]), ("power.ups:rack", "needs_you"))
        self.assertIn("25 min left", a["detail"])

    def test_steam_without_steam_is_skipped(self):
        self.m.write("game.json", {"schema": 1, "ok": True, "steam_root": None, "findings": []})
        self.assertEqual(states(self.m.run("user"))["game.steam"], "skipped")


class FieldKit(Machine):
    def saved(self):
        p = self.m.root / "var/lib/bromigos/fieldkit/findings.json"
        return json.loads(p.read_text()) if p.exists() else None

    def test_what_a_stick_saved_is_raised_at_the_next_boot_until_a_clean_check(self):
        self.m.broken()
        doc = self.m.run(boot=True)
        fk = {a["id"]: a for a in doc["alerts"] if a["check"] == "fieldkit.finding"}
        saved = fk["fieldkit.finding:last-boot:the-graphics-driver-reported-errors"]
        self.assertIn("from the stick", saved["detail"])
        self.assertEqual(saved["evidence"]["facts"]["saved_by_stick"], "yes")
        # its live re-check couldn't run: the saved finding stays in the file
        self.assertIn("last-boot", self.saved()["checks"])
        # passes between boots keep what the boot pass found
        self.m.now += HOUR
        between = self.m.run()
        self.assertEqual({a["id"] for a in between["alerts"] if a["check"] == "fieldkit.finding"}, set(fk))
        self.assertEqual([c["ran_at"] for c in between["checks"] if c["check"] == "fieldkit.finding"], [NOW])
        # the next boot: the live check works and is clean: the saved entry goes, and so does the alert
        self.m.write("fieldkit-last-boot.json", {"ok": True, "findings": [{"id": "0", "title": "fine", "ok": True}]})
        self.m.write("fieldkit-black-screen.json", {"ok": True, "findings": []})
        doc = self.m.run(boot=True)
        self.assertEqual([a for a in doc["alerts"] if a["check"] == "fieldkit.finding"], [])
        self.assertIsNone(self.saved())

    def test_no_engine_and_nothing_saved_is_skipped(self):
        (self.m.root / "usr/lib/bromigos/fieldkit/fieldkit-engine").unlink()
        self.assertEqual(states(self.m.run(boot=True))["fieldkit.finding"], "skipped")


class Custom(Machine):
    def check(self, name, body, mode=0o755):
        d = self.m.root / "etc/bromigos/alerts.d"
        d.mkdir(parents=True, exist_ok=True)
        d.chmod(0o755)
        p = d / name
        p.write_text(body)
        p.chmod(mode)
        return p

    def test_your_own_check_is_prefixed_and_kept_to_the_shape(self):
        self.check("nas-mount", "#!/bin/sh\ncat <<'EOF'\n" + json.dumps({"alerts": [
            {"id": "media", "severity": "needs_you", "title": "The NAS isn't mounted", "detail": "/mnt/nas is empty",
             "actions": [{"kind": "run", "command": "sudo mount /mnt/nas"}, {"kind": "nonsense"}]}]}) + "\nEOF\n")
        doc = self.m.run()
        a = [x for x in doc["alerts"] if x["check"] == "custom.nas-mount"][0]
        self.assertEqual((a["id"], a["source"]), ("custom.nas-mount:media", "nas-mount"))
        self.assertEqual(a["actions"], [{"kind": "run", "command": "sudo mount /mnt/nas"}])
        self.assertEqual(states(doc)["custom.nas-mount"], "ran")

    def test_one_anyone_could_change_is_never_run(self):
        p = self.check("open", "#!/bin/sh\ntouch \"$FAKE/ran\"\necho '{\"alerts\": []}'\n", mode=0o777)
        doc = self.m.run()
        row = [c for c in doc["checks"] if c["check"] == "custom.open"][0]
        self.assertEqual(row["state"], "failed")
        self.assertIn("writable by no one else", row["error"])
        self.assertFalse((self.m.fake / "ran").exists())
        p.chmod(0o755)
        self.assertEqual(states(self.m.run())["custom.open"], "ran")

    def test_a_slow_or_wrong_check_fails_alone(self):
        self.check("slow", "#!/bin/sh\nsleep 5\n")
        self.check("bad", "#!/bin/sh\necho '{\"alerts\": [{\"severity\": \"loud\", \"title\": \"x\"}]}'\n")
        doc = A.run_pass(self.m.env(BROMIGOS_ALERTS_CUSTOM_TIMEOUT="0.5"), "system")
        rows = {c["check"]: c for c in doc["checks"]}
        self.assertIn("no answer within", rows["custom.slow"]["error"])
        self.assertIn("severity must be", rows["custom.bad"]["error"])
        self.assertEqual(rows["disk.full"]["state"], "ran")


class Notify(Machine):
    def setUp(self):
        super().setUp()
        self.shown = []

    def notify(self, **env):
        return A.notify(self.m.env(**env), send=lambda t, b, u: self.shown.append((t, u)))

    def test_once_then_after_the_cooldown_or_when_it_gets_worse(self):
        self.m.disk_space(93)
        self.m.run()
        self.notify()
        self.assertEqual(self.shown, [("The system drive is 93% full", "normal")])
        self.m.now += HOUR
        self.m.run()
        self.notify()
        self.assertEqual(len(self.shown), 1, "the same alert again within the cooldown")
        self.m.disk_space(98)
        self.m.run()
        self.notify()
        self.assertEqual(self.shown[-1], ("The system drive is 98% full", "critical"))
        self.m.now += 6 * HOUR
        self.m.run()
        self.notify()
        self.assertEqual(len(self.shown), 3, "a critical one again after 6 h")

    def test_info_never_and_a_flap_doesnt_show_twice(self):
        self.m.write("update-check.json", {"schema": 1, "check": {"packages": [{"name": "mesa", "from": "1", "to": "2"}]}})
        self.m.run("user")
        self.notify()
        self.assertEqual(self.shown, [])
        self.m.disk_space(93)
        self.m.run()
        self.notify()
        self.m.disk_space(50)
        self.m.now += 10 * 60_000
        self.m.run()
        self.notify()
        self.m.disk_space(93)
        self.m.now += 10 * 60_000
        self.m.run()
        self.notify()
        self.assertEqual(len(self.shown), 1)

    def test_at_most_three_a_run(self):
        self.m.broken()
        self.m.run(boot=True)
        self.notify()
        self.assertEqual(len(self.shown), 3)
        self.assertTrue(self.shown[-1][0].startswith("And "), self.shown)
        self.assertEqual(self.shown[0][1], "critical")
        self.shown.clear()
        self.notify()
        self.assertEqual(self.shown, [])

    def test_the_real_command_only_in_a_desktop_session(self):
        self.m.disk_space(93)
        self.m.run()
        env = self.m.env()
        env.environ.pop("WAYLAND_DISPLAY", None)
        env.environ.pop("DISPLAY", None)
        self.assertEqual(A.notify(env), [])
        self.assertFalse((self.m.fake / "notified").exists())
        env = self.m.env(WAYLAND_DISPLAY="wayland-test")
        A.notify(env)
        text = (self.m.fake / "notified").read_text()
        self.assertIn("--urgency=normal", text)
        self.assertIn("The system drive is 93% full", text)


class Command(Machine):
    def cli(self, *args, **env):
        e = dict(self.m.env(**env).environ)
        return subprocess.run([sys.executable, str(SCRIPT), *args], env=e, capture_output=True, text=True)

    def test_the_command(self):
        self.m.disk_space(93)
        r = self.cli("check", "--json")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(json.loads(r.stdout)["scope"], "system")
        r = self.cli("check", "--user")
        self.assertIn("user checks:", r.stdout)
        r = self.cli()
        self.assertEqual(r.returncode, 1)
        self.assertIn("NEEDS YOU  The system drive is 93% full", r.stdout)
        doc = json.loads(self.cli("--json").stdout)
        self.assertEqual([a["id"] for a in doc["alerts"]], ["disk.full:/"])
        self.assertIn("disk.smart", self.cli("checks").stdout)
        r = self.cli("check", "--only", "disk.smart", "--json")
        self.assertEqual([c["check"] for c in json.loads(r.stdout)["checks"]][-1], "disk.smart")
        self.assertEqual(self.cli("frobnicate").returncode, 2)

    def test_the_system_pass_needs_root(self):
        if os.geteuid() == 0:
            self.skipTest("running as root")
        e = dict(self.m.env().environ)
        e.pop("BROMIGOS_ALERTS_ROOT")
        r = subprocess.run([sys.executable, str(SCRIPT), "check", "--system"], env=e, capture_output=True, text=True)
        self.assertEqual(r.returncode, 2)
        self.assertIn("sudo bromigos alerts check --system", r.stderr)


if __name__ == "__main__":
    unittest.main()
