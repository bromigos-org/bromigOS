"""`bromigos activity` on a stand-in machine (tests/activity/fake.py): the progress lines every
command in this repository prints, the record they become, a job's ends (done, failed at a
step, cancelled, interrupted by a kill or a restart), the bounds, what keeps secrets out, two
jobs at once, the JSON shapes, and a job in a (stand-in) unit of its own that outlives whoever
started it. No root, no real systemd unit, nothing on this machine read or changed."""
import io
import json
import os
import re
import signal
import stat
import subprocess
import sys
import time
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))

import fake  # noqa: E402
from fake import FakeMachine, FIXTURES, NOW, REPO  # noqa: E402

import bromigos_activity as A  # noqa: E402

DAY = 86400_000
RECORD_KEYS = {"schema", "id", "kind", "title", "subject", "state", "waiting_for", "question", "steps", "step", "pct",
               "stage", "notes", "started_at", "updated_at", "ended_at", "requested_by", "unit", "locks", "can",
               "cancel_safe", "cancel_note", "result", "error", "exit_code", "command", "log", "parent", "children",
               "boot_id"}
STEP_KEYS = {"id", "label", "state", "started_at", "ended_at", "detail", "progress"}

# what the installers print (iso/profile/airootfs/usr/local/bin/bromigos-iso-install, and
# bromigos_installer's disks.py, reinstall.py, server_apply.py, progress.py), and the engine's
# stand-in in the QEMU runs (iso/test/provision-stub): no ID on an error, other item states
INSTALLER_LINES = [
    "::stage 0 Putting your old bromigOS back",
    "::stage 4 Opening your bromigOS",
    "::stage 6 Keeping the old system as a snapshot (@old-root-20261109-2240)",
    "::stage 8 Bringing /var/log along",
    "::stage 90 Downloading the NVIDIA driver",
    "::error The disk chosen (/dev/sdb) is gone. Plug it back in and start the install again.",
    "::error Checking your choices stopped and the install didn't finish. Nothing was changed. The details are in "
    "/var/log/bromigos-install.log on the live system.",
    "::error Making room beside Windows failed: ntfsresize stopped. Nothing was changed.",
    "::error Setting up the server stopped: mkfs.btrfs failed. Nothing on the data disks was kept half done; start the "
    "install again.",
    "::error Reinstalling stopped: no space left. Your home folder wasn't touched.",
    "::stage 0 Setting up Jellyfin",
    "::item jellyfin running",
    "::item jellyfin waiting-for-network",
    "::item jellyfin done",
    "::stage 100 Everything in the plan is set up",
]


def transcript(name):
    return (FIXTURES / f"{name}.txt").read_text().splitlines()


class Machine(unittest.TestCase):
    systemd = False
    server = False

    def setUp(self):
        self.m = FakeMachine(systemd=self.systemd, server=self.server)
        self.addCleanup(self.m.close)

    def job(self, env=None, **kw):
        kw.setdefault("kind", "app.install")
        kw.setdefault("title", "Setting up this server")
        return A.Job(env or self.m.env(), **kw).open()

    def fed(self, lines, code=0, **kw):
        """A job fed these lines, then ended with this exit status: its record."""
        j = self.job(**kw)
        j.set_state("running")
        seen = []
        for line in lines:
            j.feed(line)
            seen.append(j.rec["state"])
        j.finish(code)
        self.states_seen = seen
        return self.m.on_disk()[j.id]


class TheLines(Machine):
    def test_every_line_the_engine_prints_is_understood(self):
        for name in ("provision-offline-then-network", "provision-failure", "provision-gave-up", "provision-plan-problems"):
            known = set()
            for line in transcript(name):
                ev = A.parse(line, known)
                self.assertIsNotNone(ev, line)
                self.assertEqual(ev["kind"], line[2:].split()[0])
                if ev["kind"] == "item":
                    known.add(ev["id"])
                    self.assertIn(ev["state"], A.ITEM_STATES, line)
                if ev["kind"] in ("note", "error"):                      # the engine always names what it's about
                    self.assertEqual(ev["id"], line.split()[1], line)
                    self.assertEqual(ev["words"], line.split(" ", 2)[2])

    def test_every_line_the_installers_print_is_understood(self):
        for line in INSTALLER_LINES:
            ev = A.parse(line)
            self.assertIsNotNone(ev, line)
            if ev["kind"] == "error":                                    # the installers' errors have no ID
                self.assertIsNone(ev["id"], line)
                self.assertEqual(ev["words"], line[len("::error "):])
            if ev["kind"] == "item":
                self.assertIn(ev["state"], A.ITEM_STATES, line)

    def test_each_form(self):
        self.assertEqual(A.parse("::stage 40 Installing Jellyfin"), {"kind": "stage", "pct": 40, "words": "Installing Jellyfin"})
        self.assertEqual(A.parse("::stage 100"), {"kind": "stage", "pct": 100, "words": ""})
        self.assertEqual(A.parse("::stage 250 Too far")["pct"], 100)
        self.assertEqual(A.parse("::stage 12.5% Half way")["pct"], 12)
        self.assertEqual(A.parse("::item jellyfin skipped-offline\n"),
                         {"kind": "item", "id": "jellyfin", "state": "skipped-offline", "words": ""})
        # the tour's own pattern lets words follow an item's state
        self.assertEqual(A.parse("::item jellyfin failed no room left")["words"], "no room left")
        self.assertEqual(A.parse("::step copy running Copying what changed"),
                         {"kind": "step", "id": "copy", "state": "running", "words": "Copying what changed"})
        self.assertEqual(A.parse("::note sonarr Sonarr (shows) didn't answer yet."),
                         {"kind": "note", "id": "sonarr", "words": "Sonarr (shows) didn't answer yet."})
        self.assertEqual(A.parse("::error network 2 items wait for the internet (a, b)."),
                         {"kind": "error", "id": "network", "words": "2 items wait for the internet (a, b)."})
        self.assertEqual(A.parse("::error pacman failed to reach the mirrors"),
                         {"kind": "error", "id": None, "words": "pacman failed to reach the mirrors"})
        self.assertEqual(A.parse("::error copy it stopped", known={"copy"}), {"kind": "error", "id": "copy", "words": "it stopped"})
        self.assertEqual(A.parse("::ask replace Replace the drive in bay 2?")["kind"], "ask")

    def test_a_line_it_does_not_understand_is_only_output(self):
        odd = ["", "::", ":: ", "::stage", "::stage soon", "::stage -4 Back", "::item", "::item lonely", "::note", "::error",
               "::bogus 1 2 3", "::Stage 10 Shouting", ":::stage 1 x", " ::stage 1 indented", "::error::a GitHub command",
               "::stage\t", "::item \x00 \x1b[31m", "::step " + "x" * 100_000, "plain words", "\ufffd\ufffd", None, 7, b"::stage 1 b",
               # the installers' other lines, which aren't progress: they stay output
               "::secureboot 123456", "::server firewall: ssh, mdns", "::page disk", "::result installed", "::stuck disk No disk"]
        for line in odd:
            self.assertIsNone(A.parse(line), repr(line)[:40])
        rec = self.fed([x for x in odd if isinstance(x, str)] + ["::stage 30 Still here"])
        self.assertEqual((rec["state"], rec["pct"], rec["steps"]), ("succeeded", 30, []))

    def test_every_kind_printed_in_this_repository_is_known(self):
        """Whatever a command here prints as `::word …`, the parser knows the word."""
        found = {}
        places = ["homelab/lib", "homelab/bin", "iso/profile/airootfs/usr/local", "iso/test/provision-stub", "bin", "lib",
                  "server", "fieldkit/lib", "desktop/bin", "desktop/lib"]
        for place in places:
            top = REPO / place
            for p in ([top] if top.is_file() else sorted(top.rglob("*")) if top.is_dir() else []):
                if not p.is_file() or p.suffix in (".pyc", ".png", ".opus", ".npz", ".webp") or p.stat().st_size > 2_000_000:
                    continue
                for word in re.findall(r"""["']::([a-z][a-z-]*)[ {%]""", p.read_text(errors="replace")):
                    found.setdefault(word, str(p.relative_to(REPO)))
        self.assertTrue({"stage", "item", "note", "error"} <= set(found), found)
        # the installers print these too. They aren't progress (a code for the last page, a line
        # of detail, the screens' test driver), so a job keeps them as output. A new word here
        # is a decision: progress the parser should learn, or one more for this list
        other = {"secureboot", "server", "page", "result", "stuck"}
        self.assertEqual({w: p for w, p in found.items() if w not in A.KINDS and w not in other}, {})

    def test_what_a_job_says_reads_back(self):
        out = io.StringIO()
        with redirect_stdout(out):
            j = A.Lines()
            j.stage(10, "Getting\nready")
            j.step("snapshot", "Taking a snapshot")
            j.step("copy", "Copying what changed")
            j.note("Nothing new since yesterday", "copy")
            j.error("The other side hung up")
            j.step("copy", state="done")
        got = [A.parse(l, {"snapshot", "copy"}) for l in out.getvalue().splitlines()]
        self.assertEqual([(e["kind"], e.get("id"), e.get("state")) for e in got],
                         [("stage", None, None), ("step", "snapshot", "running"), ("step", "snapshot", "done"),
                          ("step", "copy", "running"), ("note", "copy", None), ("error", None, None), ("step", "copy", "done")])
        self.assertEqual(got[0]["words"], "Getting ready")


class TheRecord(Machine):
    def test_the_engines_run_becomes_steps(self):
        rec = self.fed(transcript("provision-offline-then-network"))
        self.assertEqual(set(rec), RECORD_KEYS)
        self.assertEqual([s["id"] for s in rec["steps"]], ["backups", "smb-shares", "media-library", "jellyfin", "seerr",
                                                           "prowlarr", "sonarr", "radarr", "qbittorrent", "gluetun"])
        for s in rec["steps"]:
            self.assertEqual(set(s), STEP_KEYS)
            self.assertEqual(s["state"], "done", s)
            self.assertLessEqual(s["started_at"], s["ended_at"])
        self.assertEqual((rec["state"], rec["pct"], rec["exit_code"], rec["error"]), ("succeeded", 100, 0, None))
        self.assertEqual(rec["result"], {"ok": True, "summary": "Done", "undo": None})
        self.assertEqual([n["id"] for n in rec["notes"]], ["media-library", "sonarr", "radarr", "secrets"])
        self.assertIn("No sources are set up", rec["steps"][2]["detail"])       # a note stays on its step
        self.assertIsNone(rec["steps"][0]["detail"])
        # with every item waiting for the internet and none running, the job waited, and said for what
        self.assertIn("waiting", self.states_seen)
        self.assertEqual(self.states_seen[-1], "running")

    def test_waiting_for_the_internet(self):
        j = self.job()
        j.set_state("running")
        for line in transcript("provision-gave-up")[:4]:
            j.feed(line)
        rec = self.m.on_disk()[j.id]
        self.assertEqual((rec["state"], rec["waiting_for"]), ("waiting", "network"))
        self.assertEqual((rec["steps"][0]["state"], rec["steps"][0]["detail"]), ("waiting", "Waiting for the internet"))
        j.feed("::item uptime downloading")
        rec = self.m.on_disk()[j.id]
        self.assertEqual((rec["state"], rec["waiting_for"], rec["steps"][0]["detail"]), ("running", None, "Downloading"))
        j.finish(0)

    def test_a_failure_names_the_step_and_the_reason(self):
        rec = self.fed(transcript("provision-failure"), code=1)
        self.assertEqual((rec["state"], rec["exit_code"]), ("failed", 1))
        self.assertEqual(rec["error"]["step"], "prowlarr")
        self.assertIn("couldn't download ghcr.io/linuxserver/prowlarr", rec["error"]["words"])
        self.assertEqual((rec["error"]["code"], rec["error"]["fix"]), ("exit", None))
        self.assertEqual({s["id"]: s["state"] for s in rec["steps"]}, {"media-library": "done", "prowlarr": "failed", "sonarr": "failed"})
        self.assertIn("needs Prowlarr", rec["steps"][2]["detail"])
        self.assertEqual(rec["result"], {"ok": False, "summary": "It stopped at prowlarr.", "undo": None})
        self.assertNotIn("Traceback", json.dumps(rec))

    def test_giving_up_on_the_internet_and_a_refused_plan(self):
        rec = self.fed(transcript("provision-gave-up"), code=75)
        self.assertEqual((rec["state"], rec["exit_code"], rec["error"]["step"]), ("failed", 75, None))
        self.assertIn("wait for the internet (uptime)", rec["error"]["words"])
        self.assertEqual(rec["steps"][0]["state"], "skipped")                    # it never ran, so it didn't fail
        rec = self.fed(transcript("provision-plan-problems"), code=1)
        self.assertIn("can't run on the same server", rec["error"]["words"])
        self.assertEqual(rec["steps"], [])

    def test_only_stages_still_give_a_title_and_a_share(self):
        j = self.job(kind="server.install", title="Installing bromigOS")
        j.set_state("running")
        for line in INSTALLER_LINES[:5]:
            j.feed(line)
        self.assertEqual(self.m.on_disk()[j.id]["pct"], None)     # progress alone is written at most four times a second
        j.save()
        rec = self.m.on_disk()[j.id]
        self.assertEqual((rec["title"], rec["pct"], rec["stage"], rec["steps"], rec["step"]),
                         ("Installing bromigOS", 90, "Downloading the NVIDIA driver", [], None))
        j.feed(INSTALLER_LINES[5])
        j.finish(1)
        rec = self.m.on_disk()[j.id]
        self.assertEqual(rec["error"], {"step": None, "code": "exit", "fix": None,
                                        "words": "The disk chosen (/dev/sdb) is gone. Plug it back in and start the install again."})

    def test_named_steps(self):
        j = self.job(kind="backup.run", title="Backing up")
        j.set_state("running")
        for line in ["::step snapshot running Taking a snapshot", "::step snapshot done",
                     "::step copy running Copying what changed", "::step copy running 120/400 MB",
                     "::step check todo Checking it reads back"]:
            j.feed(line)
        j.save()
        rec = self.m.on_disk()[j.id]
        self.assertEqual([(s["id"], s["label"], s["state"]) for s in rec["steps"]],
                         [("snapshot", "Taking a snapshot", "done"), ("copy", "Copying what changed", "running"),
                          ("check", "Checking it reads back", "todo")])
        self.assertEqual(rec["step"], 1)
        self.assertEqual(rec["steps"][1]["detail"], "120/400 MB")
        self.assertEqual(rec["steps"][1]["progress"], {"done": 120.0, "total": 400.0, "unit": "MB"})
        j.feed("::step copy bewildered")                                         # a state nobody defined: still going
        self.assertEqual(self.m.on_disk()[j.id]["steps"][1]["state"], "running")
        j.finish(0)
        rec = self.m.on_disk()[j.id]
        self.assertEqual([s["state"] for s in rec["steps"]], ["done", "done", "skipped"])

    def test_failing_in_the_middle_of_a_step(self):
        rec = self.fed(["::step snapshot running Taking a snapshot", "::step snapshot done",
                        "::step copy running Copying what changed", "rsync: connection unexpectedly closed"], code=12)
        self.assertEqual((rec["state"], rec["exit_code"]), ("failed", 12))
        self.assertEqual(rec["error"], {"step": "copy", "words": "rsync: connection unexpectedly closed", "code": "exit", "fix": None})
        self.assertEqual((rec["steps"][1]["state"], rec["steps"][1]["detail"]), ("failed", "It stopped here."))
        self.assertEqual(rec["result"]["summary"], "It stopped at Copying what changed.")
        rec = self.fed([], code=3)                                                # nothing said at all
        self.assertEqual(rec["error"]["words"], "It stopped with exit status 3.")

    def test_the_states_and_their_moves(self):
        self.assertEqual(set(A.MOVES), set(A.STATES) - set(A.FINAL))
        for state, to in A.MOVES.items():
            self.assertTrue(to <= set(A.STATES) and state not in to, state)
        self.assertEqual(A.MOVES["running"] - {"needs-you", "waiting"}, set(A.FINAL))
        j = self.job()
        self.assertEqual(self.m.on_disk()[j.id]["state"], "queued")
        with self.assertRaises(A.ActivityError):
            j.set_state("succeeded")                                             # not before it ran
        j.set_state("running")
        j.set_state("needs-you")
        j.set_state("running")
        j.finish(0, state="rolled-back", words="The new version didn't answer.")
        rec = self.m.on_disk()[j.id]
        self.assertEqual((rec["state"], rec["result"]["ok"], rec["error"]["words"]),
                         ("rolled-back", False, "The new version didn't answer."))
        self.assertIsNotNone(rec["ended_at"])
        with self.assertRaises(A.ActivityError):
            j.set_state("running")                                               # an end is an end
        self.assertEqual(j.finish(1)["state"], "rolled-back")

    def test_what_a_job_must_have(self):
        for kw in ({"kind": "install"}, {"kind": "App.Install"}, {"kind": "app." + "x" * 60}, {"kind": "app.install", "title": "  "},
                   {"kind": "app.install", "via": "carrier-pigeon"}):
            with self.assertRaises(A.ActivityError, msg=kw):
                self.job(**kw)
        with self.assertRaises(A.ActivityError):
            A.parse_subject("photos")
        self.assertEqual(A.parse_subject("app:photos:Photos"), {"type": "app", "id": "photos", "name": "Photos"})
        self.assertEqual(A.parse_subject("drive:bay-2"), {"type": "drive", "id": "bay-2", "name": "bay-2"})

    def test_the_id_names_the_time_the_kind_and_the_subject(self):
        env = self.m.env(BROMIGOS_ACTIVITY_NOW_MS=NOW)
        j = self.job(env, kind="app.update", title="Updating Photos", subject=A.parse_subject("app:photos:Photos"))
        self.assertRegex(j.id, r"^20261109-2240-app\.update-photos-[0-9a-f]{4}$")
        self.assertEqual(A.unit_name(j.id), f"bromigos-job-{j.id}.service")
        rec = self.m.on_disk()[j.id]
        self.assertEqual((rec["started_at"], rec["subject"]["name"], rec["requested_by"]), (NOW, "Photos", {"via": "cli", "device": None}))
        self.assertRegex(self.job(env, kind="pool.check", title="Checking the pool").id, r"^20261109-2240-pool\.check-[0-9a-f]{4}$")

    def test_a_python_command_is_a_job(self):
        env = self.m.env()
        with A.job("backup.run", "Backing up", env=env) as j:
            j.stage(10, "Getting ready")
            j.step("snapshot", "Taking a snapshot")
            j.step("copy", "Copying what changed")
            self.assertEqual(A.list_jobs(env)[0]["state"], "running")
        rec = A.list_jobs(env)[0]
        self.assertEqual((rec["state"], rec["unit"], [(s["id"], s["state"]) for s in rec["steps"]]),
                         ("succeeded", None, [("snapshot", "done"), ("copy", "done")]))
        with self.assertRaises(RuntimeError):
            with A.job("backup.run", "Backing up", env=env) as j:
                j.step("snapshot", "Taking a snapshot")
                raise RuntimeError("The disk is full.")
        rec = A.list_jobs(env)[0]
        self.assertEqual((rec["state"], rec["error"]["step"], rec["error"]["words"]), ("failed", "snapshot", "The disk is full."))
        # under `bromigos activity run` it only says its lines: the wrapper keeps the one record
        out = io.StringIO()
        with redirect_stdout(out), A.job("backup.run", "Backing up", env=self.m.env(BROMIGOS_ACTIVITY_JOB="x")) as j:
            j.step("snapshot", "Taking a snapshot")
        self.assertEqual(out.getvalue().splitlines(), ["::step snapshot running Taking a snapshot", "::step snapshot done"])
        self.assertEqual(len(A.list_jobs(env)), 2)


class Running(Machine):
    """`bromigos activity run` where there is no systemd: the job runs in the foreground."""

    def run_job(self, body, *args, env=None):
        return self.m.cli("run", "--kind", "backup.run", "--title", "Backing up", *args, "--", self.m.script(body), env=env)

    def test_a_job_that_ends_well(self):
        code, out, err = self.run_job('echo "::stage 0 Getting ready"\necho "::step copy running Copying"\n'
                                      'echo "some detail" >&2\necho "::stage 100 All copied"\n', "--subject", "backup:nas:The NAS")
        self.assertEqual(code, 0, err)
        self.assertEqual(out.splitlines(), ["::stage 0 Getting ready", "::step copy running Copying", "some detail",
                                            "::stage 100 All copied"])        # what it printed, as it printed it
        [rec] = self.m.listed()
        self.assertEqual((rec["state"], rec["pct"], rec["exit_code"], rec["unit"]), ("succeeded", 100, 0, None))
        self.assertEqual(rec["result"]["summary"], "All copied")
        self.assertEqual(rec["steps"][0]["state"], "done")
        self.assertEqual(rec["subject"], {"type": "backup", "id": "nas", "name": "The NAS"})
        self.assertIn(f"done: All copied  ({rec['id']})", err)
        self.assertEqual(Path(rec["log"]).read_text().splitlines(), out.splitlines())
        self.assertEqual(stat.S_IMODE(os.stat(rec["log"]).st_mode), 0o640)       # the log is its owner's
        self.assertEqual(stat.S_IMODE(os.stat(self.m.jobs / f"{rec['id']}.json").st_mode), 0o644)
        self.assertEqual(sorted(p.suffix for p in self.m.jobs.iterdir()), [".json", ".log"])
        self.assertEqual(self.m.calls(), [])                                       # no unit, no password asked
        for d in (self.m.jobs, self.m.jobs.parent):                               # everyone may read, whatever the umask
            self.assertEqual(stat.S_IMODE(d.stat().st_mode), 0o755)

    def test_a_job_that_fails_in_a_step(self):
        code, out, err = self.run_job('echo "::step snapshot running Taking a snapshot"\necho "::step snapshot done"\n'
                                      'echo "::step copy running Copying"\necho "::error copy The NAS hung up."\nexit 7\n')
        self.assertEqual(code, 7)
        [rec] = self.m.listed()
        self.assertEqual((rec["state"], rec["exit_code"]), ("failed", 7))
        self.assertEqual(rec["error"], {"step": "copy", "words": "The NAS hung up.", "code": "exit", "fix": None})
        self.assertEqual([s["state"] for s in rec["steps"]], ["done", "failed"])
        self.assertIn("failed: stopped at Copying: The NAS hung up.", err)

    def test_a_command_that_is_not_there(self):
        code, out, err = self.m.cli("run", "--kind", "backup.run", "--title", "Backing up", "--", "no-such-command-here")
        self.assertEqual((code, out), (127, ""))
        self.assertIn("no such command: no-such-command-here", err)
        self.assertEqual(self.m.listed(), [])

    def test_a_command_killed_by_a_signal(self):
        code, out, err = self.run_job('echo "::step copy running Copying"\nkill -KILL $$\n')
        self.assertEqual(code, 137)
        [rec] = self.m.listed()
        self.assertEqual((rec["state"], rec["error"]["code"], rec["error"]["step"]), ("failed", "signal", "copy"))

    def test_odd_output_never_stops_a_job(self):
        code, out, err = self.run_job('printf "::stage\\n::item\\n::bogus 1\\n::stage x y\\n\\377\\376 bytes\\n"\n'
                                      'printf "%09000d\\n" 7\nprintf "no newline at the end"\n')
        self.assertEqual(code, 0, err)
        [rec] = self.m.listed()
        self.assertEqual((rec["state"], rec["steps"], rec["pct"]), ("succeeded", [], None))
        log = Path(rec["log"]).read_text().splitlines()
        self.assertEqual(log[-1], "no newline at the end")
        self.assertEqual(max(len(l) for l in log), A.LINE_MAX)                   # a long line is cut, not lost

    def start(self, body, name="job"):
        """A job in the background, once it runs: (the process, its record's id)."""
        p = self.m.popen("run", "--kind", "backup.run", "--title", "Backing up", "--", self.m.script(body, name))
        self.addCleanup(lambda: (p.poll() is None and p.kill(), p.wait(), p.stdout.close(), p.stderr.close()))
        ids = self.m.wait(lambda: [i for i, r in self.m.on_disk().items() if r["steps"]] if self.m.jobs.is_dir() else None)
        return p, ids[0]

    def test_cancel(self):
        marker = self.m.tmp / "child-ended"
        p, job_id = self.start(f'trap "echo stopped > {marker}; exit 0" TERM\necho "::step copy running Copying"\n'
                               'while :; do sleep 0.05; done\n')
        self.assertEqual(self.m.listed()[0]["state"], "running")
        p.send_signal(signal.SIGTERM)
        self.assertEqual(p.wait(timeout=20), 130)
        [rec] = self.m.listed()
        self.assertEqual((rec["state"], rec["error"]), ("cancelled", None))
        self.assertEqual(rec["result"], {"ok": False, "summary": "Stopped before it finished.", "undo": None})
        self.assertEqual((rec["steps"][0]["state"], rec["steps"][0]["detail"]), ("skipped", "It stopped here."))
        self.assertEqual(marker.read_text(), "stopped\n")                         # the command was told, and ended
        self.assertEqual(self.m.on_disk()[job_id]["state"], "cancelled")

    def test_a_closed_terminal_changes_nothing(self):
        gate = self.m.tmp / "go"
        p, job_id = self.start(f'echo "::step copy running Copying"\nwhile [ ! -e {gate} ]; do sleep 0.02; done\n'
                               'echo "::stage 100 All copied"\n')
        p.stdout.close()                                                          # whoever watched went away
        p.send_signal(signal.SIGHUP)
        gate.write_text("")
        self.assertEqual(p.wait(timeout=20), 0)
        self.assertEqual(self.m.on_disk()[job_id]["state"], "succeeded")

    def test_a_killed_job_reads_as_interrupted_and_the_next_start_closes_it(self):
        marker = self.m.tmp / "child-ended"
        p, job_id = self.start(f'trap "echo stopped > {marker}; exit 0" TERM\necho "::step copy running Copying"\n'
                               'while :; do sleep 0.05; done\n')
        p.kill()                                                                  # no last word
        p.wait()
        self.m.wait(marker.exists, words="the command ran on with nobody keeping its record")
        self.assertEqual(self.m.on_disk()[job_id]["state"], "running")            # the file still says so
        os.chmod(self.m.jobs, 0o555)                                              # a reader who may not write
        try:
            [rec] = self.m.listed()
            self.assertEqual(self.m.on_disk()[job_id]["state"], "running")
        finally:
            os.chmod(self.m.jobs, 0o755)
        self.assertEqual((rec["state"], rec["error"]["code"], rec["error"]["step"]), ("interrupted", "interrupted", "copy"))
        self.assertIn("its process was killed", rec["error"]["words"])
        self.assertEqual(rec["steps"][0]["state"], "skipped")
        code, _, err = self.m.cli("run", "--kind", "backup.run", "--title", "Backing up again", "--", "true")
        self.assertEqual(code, 0, err)
        on_disk = self.m.on_disk()[job_id]
        self.assertEqual((on_disk["state"], on_disk["error"]["code"]), ("interrupted", "interrupted"))
        self.assertIsNotNone(on_disk["ended_at"])
        self.assertFalse((self.m.jobs / f"{job_id}.lock").exists())
        self.assertEqual([r["state"] for r in self.m.listed()], ["succeeded", "interrupted"])

    def test_a_record_left_running_by_a_restart(self):
        env = self.m.env()
        j = self.job(env)
        j.set_state("running")
        j.feed("::item jellyfin installing")
        os.close(j._lock)                                # the power went: no last word, and no process holds the lock
        j._lock = None
        boot = self.m.root / "proc/sys/kernel/random"
        boot.mkdir(parents=True)
        (boot / "boot_id").write_text("0b5e2d1c-0000-4000-8000-00000000b007\n")   # a new boot
        rec = A.find(env, j.id)
        self.assertEqual(rec["state"], "interrupted")
        self.assertEqual(rec["error"]["words"], "This computer restarted or lost power while it ran.")
        self.assertEqual(self.m.on_disk()[j.id]["state"], "running")
        self.assertEqual(A.sweep(env)[0], [j.id])                                 # the next start closes it for good
        on_disk = self.m.on_disk()[j.id]
        self.assertEqual((on_disk["state"], on_disk["steps"][0]["state"], on_disk["ended_at"] is not None),
                         ("interrupted", "skipped", True))
        self.assertEqual(A.sweep(env)[0], [])                                     # once

    def test_two_jobs_at_once(self):
        gate = self.m.tmp / "go"
        body = ('echo "::step {0} running Doing {0}"\nwhile [ ! -e %s ]; do sleep 0.02; done\n'
                'echo "::step {0} done"\necho "::stage 100 {0} is done"\n' % gate)
        a = self.m.popen("run", "--kind", "backup.run", "--title", "Backing up", "--", self.m.script(body.format("copy"), "a"))
        b = self.m.popen("run", "--kind", "drive.test", "--title", "Testing a drive", "--", self.m.script(body.format("read"), "b"))
        for p in (a, b):
            self.addCleanup(lambda p=p: (p.poll() is None and p.kill(), p.wait(), p.stdout.close(), p.stderr.close()))
        both = self.m.wait(lambda: len([r for r in self.m.listed() if r["state"] == "running" and r["steps"]]) == 2 and self.m.listed())
        self.assertEqual({r["kind"]: r["steps"][0]["id"] for r in both}, {"backup.run": "copy", "drive.test": "read"})
        self.assertEqual(len({r["id"] for r in both}), 2)
        gate.write_text("")
        self.assertEqual((a.wait(timeout=20), b.wait(timeout=20)), (0, 0))
        done = {r["kind"]: r for r in self.m.listed()}
        self.assertEqual({k: (r["state"], r["result"]["summary"]) for k, r in done.items()},
                         {"backup.run": ("succeeded", "copy is done"), "drive.test": ("succeeded", "read is done")})
        self.assertIn("::step copy done", a.stdout.read())
        self.assertIn("::step read done", b.stdout.read())

    def test_the_writes_are_whole_under_a_kill(self):
        """A reader never sees half a record, whenever the writer dies."""
        writer = ("import sys; sys.path.insert(0, sys.argv[1]); import bromigos_activity as A\n"
                  "j = A.Job(A.Env(), 'backup.run', 'Backing up').open(); j.set_state('running'); print(j.id, flush=True)\n"
                  "n = 0\n"
                  "while True:\n"
                  "    n += 1; j.feed(f'::step s{n % 90} running ' + 'x' * 200); j.save()\n")
        for _ in range(3):
            p = subprocess.Popen([sys.executable, "-c", writer, str(REPO / "lib")], env=self.m.environ, stdout=subprocess.PIPE, text=True)
            job_id = p.stdout.readline().strip()
            path, reads = self.m.jobs / f"{job_id}.json", 0
            end = time.monotonic() + 0.4
            while time.monotonic() < end:
                self.assertEqual(json.loads(path.read_text())["id"], job_id)
                reads += 1
            p.kill()
            p.wait()
            p.stdout.close()
            self.assertGreater(reads, 5)
            self.assertEqual(json.loads(path.read_text())["state"], "running")
            self.assertEqual(A.find(self.m.env(), job_id)["state"], "interrupted")

    def test_help_and_wrong_commands(self):
        code, out, err = self.m.cli("--help")
        self.assertEqual(code, 0)
        self.assertIn("bromigos activity run --kind KIND --title WORDS", out)
        for args in (["frobnicate"], ["list", "--nope"], ["show", "a", "b"], ["run", "--kind", "backup.run", "--", "true"],
                     ["run", "--kind", "backup.run", "--title", "No command"]):
            self.assertEqual(self.m.cli(*args)[0], 2, args)
        code, out, err = self.m.cli("run", "--kind", "backup", "--title", "Backing up", "--", "true")
        self.assertEqual(code, 1)
        self.assertIn("a job's kind is two or more short words joined by dots", err)
        self.assertEqual(self.m.cli("show", "nothing-like-it")[0], 1)
        self.assertIn("no jobs yet", self.m.cli("show")[2])


class Bounds(Machine):
    def finished(self, env, n, kind="backup.run"):
        ids = []
        for _ in range(n):
            j = self.job(env, kind=kind, title="Backing up")
            j.set_state("running")
            log = A.Log(env.file(j.id, ".log"))
            log.write("a line")
            log.close()
            j.finish(0)
            ids.append(j.id)
        return ids

    def test_the_newest_200_and_30_days(self):
        with mock.patch.object(A, "KEEP_JOBS", 5):
            old = self.finished(self.m.env(BROMIGOS_ACTIVITY_NOW_MS=NOW - 3 * DAY), 4)
            new = self.finished(self.m.env(BROMIGOS_ACTIVITY_NOW_MS=NOW), 4)
            running = self.job(self.m.env(BROMIGOS_ACTIVITY_NOW_MS=NOW - 90 * DAY))
            running.set_state("running")
            closed, gone = A.sweep(self.m.env(BROMIGOS_ACTIVITY_NOW_MS=NOW))
            self.assertEqual((closed, len(gone)), ([], 3))
            self.assertTrue(set(gone) < set(old))
            left = {p.name for p in self.m.jobs.iterdir()}
            self.assertEqual(len([n for n in left if n.endswith(".json")]), 6)    # five ended, and the one still going
            for job_id in gone:
                self.assertFalse({f"{job_id}.json", f"{job_id}.log"} & left)
        # a month on, the ended ones are gone whatever their number; a job still going never is
        closed, gone = A.sweep(self.m.env(BROMIGOS_ACTIVITY_NOW_MS=NOW + 31 * DAY))
        self.assertEqual(len(gone), 5)
        self.assertEqual([p.name for p in self.m.jobs.glob("*.json")], [f"{running.id}.json"])
        self.assertEqual((A.KEEP_JOBS, A.KEEP_DAYS), (200, 30))
        running.finish(0)

    def test_files_nobody_owns_go(self):
        env = self.m.env()
        [kept] = self.finished(env, 1)
        stale = [self.m.jobs / n for n in ("20200101-0000-backup.run-dead.log", "20200101-0000-backup.run-dead.lock",
                                           "20200101-0000-backup.run-dead.spec", f"{kept}.json.tmp.4242")]
        fresh = self.m.jobs / "20200101-0000-backup.run-beef.log"
        for p in stale + [fresh]:
            p.write_text("x")
        for p in stale:
            os.utime(p, (time.time() - 2 * 86400,) * 2)
        A.sweep(env)
        self.assertEqual([p.exists() for p in stale], [False] * 4)
        self.assertTrue(fresh.exists())                                           # it may be a job about to start
        self.assertTrue((self.m.jobs / f"{kept}.json").exists())

    def test_a_record_stays_small(self):
        j = self.job()
        j.set_state("running")
        for n in range(A.MAX_STEPS + 40):
            j.feed(f"::step s{n} running {'label ' * 60}")
            j.feed(f"::step s{n} done {'what happened here, at length. ' * 40}")
            j.feed(f"::note s{n} {'a note worth reading. ' * 60}")
        j.feed("::error " + "why " * 1000)
        j.finish(1)
        rec = self.m.on_disk()[j.id]
        self.assertEqual(len(rec["steps"]), A.MAX_STEPS)
        self.assertEqual(len(rec["notes"]), A.MAX_NOTES)
        self.assertLessEqual(max(len(s["label"]) for s in rec["steps"]), A.MAX_LABEL)
        self.assertLessEqual(len(rec["error"]["words"]), A.MAX_WORDS)
        self.assertLessEqual((self.m.jobs / f"{j.id}.json").stat().st_size, A.RECORD_MAX + 4096)
        self.assertLessEqual(len(json.dumps(rec)), A.RECORD_MAX)
        long = self.job(title="t" * 500, command=["cmd"] + ["a" * 1000] * 200)
        rec = self.m.on_disk()[long.id]
        self.assertEqual((len(rec["title"]), len(rec["command"]), max(map(len, rec["command"]))), (A.MAX_TITLE, A.MAX_ARGS + 1, A.MAX_ARG))

    def test_a_log_stays_small_and_is_followed_across_its_turn_over(self):
        env = self.m.env()
        j = self.job(env)
        with mock.patch.object(A, "LOG_MAX", 4000):
            log, tail, got = A.Log(env.file(j.id, ".log")), A.Tail(env.file(j.id, ".log")), []
            for n in range(600):
                log.write(f"line {n:04d}")
                if n % 7 == 0:
                    got += tail.lines()
            log.close()
            got += tail.lines()
            tail.close()
        self.assertEqual(got, [f"line {n:04d}" for n in range(600)])              # every line once, in order
        sizes = [p.stat().st_size for p in self.m.jobs.glob("*.log*")]
        self.assertEqual(len(sizes), 2)
        self.assertLessEqual(sum(sizes), 4000)
        self.assertEqual(A.log_tail(env, j.rec, 3), ["line 0597", "line 0598", "line 0599"])
        self.assertGreater(len(A.log_tail(env, j.rec, 0)), 200)
        j.close()


class Secrets(Machine):
    # made here, never written whole in this file: shapes of tokens that scanners know
    GITHUB = "gh" + "p_" + "A1b2C3d4E5" * 4
    JWT = "ey" + "J" + "hbGciOiJIUzI1NiJ9" + "." + "eyJzdWIiOiIxMjM0NTY3ODkwIn0" + "." + "SflKxwRJSMeKKF2QT4fwpM"
    AGE = "AGE-SECRET-" + "KEY-1" + "QQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQ"

    def test_what_is_hidden(self):
        for text, hidden in (
                ("restic -r sftp://backup:hunter2@nas.example.org/repo", "hunter2"),
                ("GET https://example.org/api?apikey=abc123&page=2", "abc123"),
                ("curl -H 'Authorization: Bearer abcdef0123456789'", "abcdef0123456789"),
                ("VPN_PASSWORD=correct-horse-battery-staple", "correct-horse"),
                ("password: s3cret, then more", "s3cret"),
                ('client_secret = "v3ry-s3cret"', "v3ry-s3cret"),
                (f"cloning with {self.GITHUB}", self.GITHUB),
                (f"token {self.JWT} sent", self.JWT),
                (self.AGE, self.AGE)):
            self.assertNotIn(hidden, A.redact(text), text)
            self.assertIn("***", A.redact(text))
        for plain in ("Your keys: On this server, encrypted and sealed to its security chip.",
                      "::note secrets 6 keys stored on this server, encrypted with its TPM chip and host key",
                      "max_tokens=512, 1200 tokens: fine", "https://example.org/photos?page=2",
                      "::item passwords installing", "sha256:9f86d081884c7d659a2feaa0c55ad015a3bf4f1b2b0b822cd15d6c15b0f00a08"):
            self.assertEqual(A.redact(plain), plain)
        for name in ("provision-offline-then-network", "provision-failure"):      # the engine's own words pass whole
            for line in transcript(name):
                self.assertEqual(A.redact(line), line)

    def test_hiding_stays_quick_on_any_line(self):
        """No line a job can print makes the patterns crawl (each is cut to LINE_MAX first)."""
        lines = ["a." * 2048, "a-" * 2048, "pas." * 1024, ("token.-" * 600)[:4096], "https://" + "a." * 2040, "?" + "a.b&" * 1000,
                 "password" * 512, "x" * 4096, '"' * 4096, "pass: " * 680, "eyJ" + "a." * 2040, "Bearer " * 580]
        began = time.monotonic()
        for line in lines * 3:
            A.redact(line[:A.LINE_MAX])
            A.parse("::step " + line)
        self.assertLess(time.monotonic() - began, 3.0)

    def test_a_commands_arguments(self):
        argv = ["restic", "--password", "hunter2", "--repo=sftp://u:pw123@nas.example.org/r", "--set", "gluetun.password=p4ss",
                "--api-key", "k3y", "--token=t0k", "-v", "--from-answers", "/var/log/bromigos/install-answers.toml"]
        self.assertEqual(A.redact_argv(argv),
                         ["restic", "--password", "***", "--repo=sftp://u:***@nas.example.org/r", "--set", "gluetun.password=***",
                          "--api-key", "***", "--token=***", "-v", "--from-answers", "/var/log/bromigos/install-answers.toml"])

    def test_nothing_secret_lands_in_a_record_or_a_log(self):
        secrets = ["hunter2", "s3cr3t-in-output", "t0ken-in-a-step", "pw-in-an-error", "MIIEvQIBADANBgkqhkiG9w0BAQEFAASC",
                   "in-the-environment", "p4ss-in-a-title"]
        body = ('echo "connecting with password=s3cr3t-in-output"\n'
                'echo "::step login running Signing in with token: t0ken-in-a-step"\n'
                'echo "-----BEGIN OPENSSH PRIVATE KEY-----"\necho "MIIEvQIBADANBgkqhkiG9w0BAQEFAASC"\n'
                'echo "-----END OPENSSH PRIVATE KEY-----"\necho "after the key"\n'
                'echo "::error login https://admin:pw-in-an-error@example.org refused us"\nexit 1\n')
        script = self.m.script(body)
        code, out, err = self.m.cli("run", "--kind", "backup.run", "--title", "Backing up with password=p4ss-in-a-title",
                                    "--", script, "--password", "hunter2", env={"RESTIC_PASSWORD": "in-the-environment"})
        self.assertEqual(code, 1)
        [rec] = self.m.listed()
        everything = "".join(p.read_text() for p in self.m.jobs.iterdir()) + out + err + json.dumps(rec)
        for s in secrets:
            self.assertNotIn(s, everything)
        self.assertEqual(rec["command"], [script, "--password", "***"])
        self.assertEqual(rec["error"]["words"], "https://admin:***@example.org refused us")
        self.assertEqual(rec["steps"][0]["label"], "Signing in with token: ***")
        self.assertEqual(rec["title"], "Backing up with password=***")
        self.assertIn("after the key", Path(rec["log"]).read_text())
        self.assertNotIn("environ", json.dumps(rec))


class Shapes(Machine):
    def test_list_show_and_run_as_json(self):
        script = self.m.script('echo "::step copy running Copying"\necho "::stage 100 All copied"\n')
        code, out, err = self.m.cli("run", "--kind", "backup.run", "--title", "Backing up", "--json", "--", script)
        self.assertEqual((code, err), (0, ""))
        doc = json.loads(out)                                                     # only the record: no output mixed in
        self.assertEqual(set(doc), {"schema", "job"})
        self.assertEqual((doc["schema"], set(doc["job"]), doc["job"]["state"]), (1, RECORD_KEYS, "succeeded"))
        job_id = doc["job"]["id"]
        code, out, err = self.m.cli("list", "--json")
        doc = json.loads(out)
        self.assertEqual((code, set(doc), doc["schema"], [set(j) for j in doc["jobs"]]), (0, {"schema", "jobs"}, 1, [RECORD_KEYS]))
        job = doc["jobs"][0]
        self.assertEqual({k: type(job[k]).__name__ for k in sorted(RECORD_KEYS)}, {
            "boot_id": "str", "can": "list", "cancel_note": "NoneType", "cancel_safe": "bool", "children": "list",
            "command": "list", "ended_at": "int", "error": "NoneType", "exit_code": "int", "id": "str", "kind": "str",
            "locks": "list", "log": "str", "notes": "list", "parent": "NoneType", "pct": "int", "question": "NoneType",
            "requested_by": "dict", "result": "dict", "schema": "int", "stage": "str", "started_at": "int", "state": "str",
            "step": "int", "steps": "list", "subject": "NoneType", "title": "str", "unit": "NoneType",
            "updated_at": "int", "waiting_for": "NoneType"})
        self.assertEqual(set(job["steps"][0]), STEP_KEYS)
        self.assertEqual(set(job["result"]), {"ok", "summary", "undo"})
        for args in (["show", "--json"], ["show", job_id, "--json"], ["show", job_id[-4:], "--json", "--log", "1"]):
            code, out, err = self.m.cli(*args)
            doc = json.loads(out)
            self.assertEqual((code, set(doc), doc["job"]["id"]), (0, {"schema", "job", "log_tail"}, job_id), args)
        self.assertEqual(doc["log_tail"], ["::stage 100 All copied"])
        self.assertEqual(json.loads(self.m.cli("--json")[1])["jobs"][0]["id"], job_id)   # `bromigos activity` is list

    def test_for_people(self):
        self.assertIn("No jobs yet", self.m.cli()[1])
        self.m.cli("run", "--kind", "app.install", "--title", "Setting up this server", "--", self.m.script(
            'echo "::item jellyfin waiting"\necho "::item jellyfin installing"\necho "::error jellyfin Jellyfin: no room left."\n'
            'echo "::item jellyfin failed"\necho "::note secrets 2 keys stored"\nexit 1\n'))
        code, out, _ = self.m.cli()
        head, row = out.splitlines()
        self.assertEqual(head.split(), ["STATE", "WHEN", "JOB", "WHAT"])
        self.assertRegex(row, r"^failed +just now +\d{8}-\d{4}-app\.install-[0-9a-f]{4} +Setting up this server: "
                              r"stopped at jellyfin: Jellyfin: no room left\.$")
        code, out, _ = self.m.cli("show")
        self.assertRegex(out, r"(?m)^  failed just now, after \d+ s  ·  app\.install  ·  ")
        for words in ("Setting up this server\n", "Steps\n  ✗ jellyfin  failed   Jellyfin: no room left.", "Notes\n  ▲ secrets: 2 keys stored",
                      "Unit     none: it ran in the foreground", "The log's last 5 lines\n  ::item jellyfin waiting"):
            self.assertIn(words, out)
        log = self.m.listed()[0]["log"]
        os.chmod(log, 0)                                                          # someone who may not read the log
        try:
            if os.geteuid() != 0:
                self.assertIn("The log is root's to read: sudo bromigos activity show", self.m.cli("show")[1])
                self.assertIsNone(json.loads(self.m.cli("show", "--json")[1])["log_tail"])
        finally:
            os.chmod(log, 0o640)

    def test_what_goes_before_a_command_that_must_be_root(self):
        class Person(A.Env):                              # someone who isn't root, on a real root
            stand_in = False

            def is_root(self):
                return False

        env = Person(dict(self.m.environ, PATH=str(self.m.bin)))               # only the stand-ins can be found
        self.assertEqual(A.elevation(env, tty=True), ["sudo"])
        self.assertEqual(A.elevation(env, tty=False), ["pkexec"])
        (self.m.bin / "sudo").unlink()
        self.assertEqual(A.elevation(env, tty=True), ["pkexec"])
        self.assertEqual(A.elevation(self.m.env(), tty=True), [])                 # a stand-in root needs nobody's password
        self.assertEqual(self.m.calls(), [])                                       # and nothing was run to find out


class InItsOwnUnit(Machine):
    """`bromigos activity run` where systemd runs: the job is a transient unit (here a stand-in
    systemd-run that runs the unit's command detached, as systemd would)."""
    systemd = True

    def test_the_job_is_a_unit_and_the_caller_follows_it(self):
        script = self.m.script('echo "::step copy running Copying"\npwd\necho "::stage 100 All copied"\n')
        code, out, err = self.m.cli("run", "--kind", "backup.run", "--title", "Backing up 100%", "--", script, "--password", "hunter2")
        self.assertEqual(code, 0, err)
        [rec] = self.m.listed()
        self.assertEqual(out.splitlines(), ["::step copy running Copying", str(self.m.tmp), "::stage 100 All copied"])
        self.assertEqual((rec["state"], rec["unit"]), ("succeeded", f"bromigos-job-{rec['id']}.service"))
        [call] = self.m.calls()
        self.assertEqual(call, f"systemd-run --unit=bromigos-job-{rec['id']}.service --collect --quiet --service-type=exec "
                               f"--property=KillMode=mixed --description=bromigOS job: Backing up 100 "
                               f"--setenv=HOME={self.m.home} --setenv=BROMIGOS_ROOT={self.m.root} -- {fake.SCRIPT} run --job {rec['id']}")
        self.assertNotIn("hunter2", call)                                         # the unit's command line is the id only
        self.assertEqual(rec["command"], [script, "--password", "***"])
        self.assertEqual(sorted(p.suffix for p in self.m.jobs.iterdir()), [".json", ".log"])   # the spec went as it started

    def test_it_finishes_with_whoever_started_it_gone(self):
        gate = self.m.tmp / "go"
        script = self.m.script(f'echo "::step copy running Copying"\nwhile [ ! -e {gate} ]; do sleep 0.02; done\n'
                               'echo "::stage 100 All copied"\n')
        p = self.m.popen("run", "--kind", "backup.run", "--title", "Backing up", "--", script)
        self.addCleanup(lambda: (p.stdout.close(), p.stderr.close()))
        self.assertEqual(p.stdout.readline(), "::step copy running Copying\n")    # the caller sees it start
        p.kill()                                                                  # the terminal closed
        p.wait()
        [rec] = self.m.listed()
        self.assertEqual(rec["state"], "running")
        gate.write_text("")
        done = self.m.wait(lambda: [r for r in self.m.listed() if r["state"] == "succeeded"])
        self.assertEqual((done[0]["id"], done[0]["pct"], done[0]["steps"][0]["state"]), (rec["id"], 100, "done"))

    def test_detach(self):
        code, out, err = self.m.cli("run", "--kind", "backup.run", "--title", "Backing up", "--detach", "--json", "--",
                                    self.m.script('echo "::stage 100 All copied"\n'))
        self.assertEqual(code, 0, err)
        doc = json.loads(out)
        self.assertEqual(doc, {"schema": 1, "id": doc["id"], "unit": f"bromigos-job-{doc['id']}.service"})
        self.m.wait(lambda: [r for r in self.m.listed() if r["id"] == doc["id"] and r["state"] == "succeeded"])

    def test_the_unit_gone_with_no_last_word(self):
        marker = self.m.tmp / "child-ended"
        script = self.m.script(f'trap "echo stopped > {marker}; exit 0" TERM\necho "::step copy running Copying"\n'
                               'while :; do sleep 0.05; done\n')
        code, out, err = self.m.cli("run", "--kind", "backup.run", "--title", "Backing up", "--detach", "--", script)
        job_id = out.strip()
        self.m.wait(lambda: self.m.on_disk().get(job_id, {}).get("steps"))
        os.killpg(self.m.unit_pid(job_id), signal.SIGKILL)                        # as a power cut would
        self.m.wait(marker.exists)
        rec = self.m.wait(lambda: [r for r in self.m.listed() if r["state"] == "interrupted"])[0]
        self.assertEqual((rec["id"], rec["error"]["step"], rec["unit"]), (job_id, "copy", A.unit_name(job_id)))

    def test_stopping_the_unit_cancels_the_job(self):
        script = self.m.script('trap "exit 0" TERM\necho "::step copy running Copying"\nwhile :; do sleep 0.05; done\n')
        code, out, err = self.m.cli("run", "--kind", "backup.run", "--title", "Backing up", "--detach", "--", script)
        job_id = out.strip()
        self.m.wait(lambda: self.m.on_disk().get(job_id, {}).get("steps"))
        os.kill(self.m.unit_pid(job_id), signal.SIGTERM)                          # what `systemctl stop` sends (KillMode=mixed)
        rec = self.m.wait(lambda: [r for r in self.m.listed() if r["state"] == "cancelled"])[0]
        self.assertEqual(rec["id"], job_id)
        self.assertIn("systemctl is-system-running", self.m.calls())              # it asked whether this was a shutdown

    def test_a_shutdown_interrupts_the_job(self):
        script = self.m.script('trap "exit 0" TERM\necho "::step copy running Copying"\nwhile :; do sleep 0.05; done\n')
        code, out, err = self.m.cli("run", "--kind", "backup.run", "--title", "Backing up", "--detach", "--", script)
        job_id = out.strip()
        self.m.wait(lambda: self.m.on_disk().get(job_id, {}).get("steps"))
        (self.m.fake / "system-state").write_text("stopping\n")                  # systemd is taking the system down
        os.kill(self.m.unit_pid(job_id), signal.SIGTERM)
        rec = self.m.wait(lambda: [r for r in self.m.on_disk().values() if r["state"] in A.FINAL])[0]
        self.assertEqual((rec["state"], rec["error"]["code"], rec["error"]["step"]), ("interrupted", "interrupted", "copy"))
        self.assertEqual(rec["error"]["words"], "This computer was shut down or restarted while it ran.")
        self.assertEqual(rec["steps"][0]["state"], "skipped")

    def test_a_unit_that_does_not_start(self):
        (self.m.fake / "refuse").write_text("")
        code, out, err = self.m.cli("run", "--kind", "backup.run", "--title", "Backing up", "--", "true")
        self.assertEqual((code, out), (1, ""))
        self.assertIn("the job's unit didn't start: Failed to start transient service unit", err)
        self.assertEqual(list(self.m.jobs.iterdir()), [])                         # nothing left behind

    def test_two_units_at_once(self):
        gate = self.m.tmp / "go"
        body = 'echo "::step {0} running Doing {0}"\nwhile [ ! -e %s ]; do sleep 0.02; done\necho "::step {0} done"\n' % gate
        ids = [self.m.cli("run", "--kind", kind, "--title", "A job", "--detach", "--", self.m.script(body.format(step), step))[1].strip()
               for kind, step in (("backup.run", "copy"), ("drive.test", "read"))]
        self.m.wait(lambda: len([r for r in self.m.listed() if r["state"] == "running" and r["steps"]]) == 2)
        gate.write_text("")
        done = self.m.wait(lambda: len([r for r in self.m.listed() if r["state"] == "succeeded"]) == 2 and self.m.listed())
        self.assertEqual(sorted((r["id"], r["steps"][0]["id"]) for r in done), sorted(zip(ids, ("copy", "read"))))
        self.assertEqual(len([c for c in self.m.calls() if c.startswith("systemd-run ")]), 2)


class OnAServer(Machine):
    """bromigOS Server keeps /var/lib/bromigos/server on a subvolume that a rollback leaves alone."""
    server = True

    def test_the_records_live_on_the_state_subvolume(self):
        code, out, err = self.m.cli("run", "--kind", "server.update", "--title", "Updating", "--", "true")
        self.assertEqual(code, 0, err)
        link = self.m.root / "var/lib/bromigos/activity"
        self.assertEqual((link.is_symlink(), os.readlink(link)), (True, "server/activity"))
        real = self.m.root / "var/lib/bromigos/server/activity/jobs"
        self.assertEqual(len(list(real.glob("*.json"))), 1)
        [rec] = self.m.listed()
        self.assertTrue(rec["log"].startswith(str(link)))                         # the documented path
        link.unlink()                                 # a rollback to before the first job: the link is gone
        self.assertEqual([r["id"] for r in self.m.listed()], [rec["id"]])         # the records still read
        self.m.cli("run", "--kind", "server.update", "--title", "Updating again", "--", "true")
        self.assertTrue(link.is_symlink())
        self.assertEqual(len(self.m.listed()), 2)


if __name__ == "__main__":
    unittest.main()
