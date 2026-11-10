"""`bromigos lab backups` (lib/bromigos_backups.py): the health line's words for every state, and
list, show, restore and the test restore against a real restic repository in a stand-in root,
backed up by the real `bromigos-server backup run`. A stand-in HOME, systemctl and snapper; no
root, no network, no desktop. Nothing on this machine is read or changed: the real snapper is
never run, and every file is under the test's temporary folder.

The tests that restore need restic on PATH (the packages' checkdepends and CI install it); the
health line's wording runs without it."""
import contextlib
import json
import os
import shutil
import signal
import sqlite3
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
LAB = REPO / "homelab/bin/bromigos-lab"
SERVER = REPO / "server/bromigos-server"
sys.path.insert(0, str(REPO / "lib"))

import bromigos_backups as B  # noqa: E402

RESTIC = shutil.which("restic")
NOW = 1793390400.0            # 2026-10-30 (a fixed clock)
# a name restic could misread three ways: as a pattern, as a $NAME to expand, with its last space trimmed
ODD = "srv/data/list [1]* $HOME.txt "
HOUR, DAY = 3600, 86400
S3 = "s3:https://s3.example/backups/box"

STUBS = {
    # sudo: never run from a stand-in root. It says so in the log, where every test looks
    "sudo": "#!/bin/sh\necho \"sudo $*\" >> \"$FAKE/log\"\nexit 1\n",
    "systemctl": "#!/bin/sh\ncase \"$1\" in is-active) if [ -f \"$FAKE/timers-off\" ]; then echo inactive; else echo active; fi ;; esac\nexit 0\n",
    # snapper: only run when BROMIGOS_BACKUPS_SNAPPER names it (a stand-in root never runs the real one)
    "snapper": r'''#!/bin/sh
echo "snapper $*" >> "$FAKE/log"
case " $* " in
  *" list-configs "*) cat "$FAKE/snapper-configs.json" ;;
  *" create "*) if [ -f "$FAKE/snapper-fails" ]; then echo "IO error: no space for a snapshot" >&2; exit 1; fi; echo 42 ;;
esac
''',
    # restic: the real one. With $FAKE/hang, a restore that writes restores that one path, then hangs
    # (not the look at where the backup's links point, which goes to a scratch folder)
    # $FAKE/mounts: folders that are other filesystems (a data disks' subvolume mounted at
    # srv/apps). Under --one-file-system restic leaves each out unless it is named as a target,
    # and so does this stand-in, by excluding it
    "restic": r'''#!/bin/sh
if [ "$1" = backup ] && [ -f "$FAKE/mounts" ]; then
  case " $* " in *" --one-file-system "*)
    while read -r m; do
      case " $* " in *" $m "*) ;; *) set -- "$@" --exclude "$m" ;; esac
    done < "$FAKE/mounts" ;;
  esac
fi
if [ "$1" = restore ]; then
  case " $* " in *" --dry-run "*|*/restore-test/links-*) ;; *)
    echo "restic restore" >> "$FAKE/log"
    if [ -f "$FAKE/hang" ]; then
      "$REAL_RESTIC" "$@" --include "$(cat "$FAKE/hang")" >/dev/null 2>&1
      echo $$ > "$FAKE/hanging"
      exec sleep 600
    fi ;;
  esac
fi
exec "$REAL_RESTIC" "$@"
''',
}


def rec(phase, age, **more):
    return dict({"phase": phase, "at": "2026-10-30T06:10:00-07:00", "ts": NOW - age}, **more)


class Words(unittest.TestCase):
    """health(): one verdict a person can act on, for each state the backups can be in."""

    def verdict(self, st, to=S3, present=None, restore=None):
        kind = "folder" if to.startswith("/") else "s3"
        return B.health(to, st, NOW, {"kind": kind, "path": to if kind == "folder" else "", "present": present}, restore)

    def test_the_health_line_for_each_state(self):
        good = rec("ok", 6 * HOUR)
        failed = rec("failed", HOUR, reason="the destination can't be reached: Fatal: unable to open config file")
        nine = rec("ok", 9 * DAY)
        cases = [
            ("off", {}, dict(to=""), "off",
             "Backups are off: nothing on this server is backed up. To turn them on, say where they go: "
             "[backup] to in /etc/bromigos/server.toml."),
            ("set up, none yet", {}, {}, "waiting", "No backup yet: the first one runs tonight."),
            ("a run with no destination left a note", {"run": {"phase": "off", "at": "x"}}, {}, "waiting",
             "No backup yet: the first one runs tonight."),
            ("healthy, no test restore yet", {"run": good, "first_ok_ts": NOW - 3 * DAY}, {}, "ok",
             "Backed up 6 hours ago. Last test restore: none yet."),
            ("healthy", {"run": good, "run_ok": good, "test": rec("ok", 12 * DAY), "test_ok": rec("ok", 12 * DAY)}, {}, "ok",
             "Backed up 6 hours ago. Last test restore: 12 days ago, passed."),
            ("an old state file, from before run_ok", {"run": good, "test": rec("ok", 12 * DAY)}, {}, "ok",
             "Backed up 6 hours ago. Last test restore: 12 days ago, passed."),
            ("the drive is not connected", {"run": dict(failed, ts=NOW - HOUR), "run_ok": nine}, dict(to="/mnt/backup", present=False),
             "attention", "No backup in 9 days: the drive at /mnt/backup is not connected. Last test restore: none yet."),
            ("late, and nothing says why", {"run": nine}, {}, "attention",
             "No backup in 9 days: the nightly backup has not run (the server may have been off, or its timer "
             "stopped). Last test restore: none yet."),
            ("the first one failed", {"run": failed}, {}, "attention",
             "No backup yet: the first one failed 1 hour ago: the destination can't be reached: unable to open "
             "config file. Last test restore: none yet."),
            ("the last one failed, the one before worked", {"run": failed, "run_ok": good}, {}, "attention",
             "The last backup failed: the destination can't be reached: unable to open config file. The one before it "
             "worked, 6 hours ago. Last test restore: none yet."),
            ("some files left out", {"run": rec("partial", 6 * HOUR, reason="some files couldn't be read: /srv/x")}, {}, "ok",
             "Backed up 6 hours ago. Some files could not be read and were left out. Last test restore: none yet."),
            ("the weekly check failed", {"run": good, "check": rec("failed", 2 * DAY, reason="Fatal: repository contains errors")},
             {}, "attention", "Backed up 6 hours ago. But the last check of the backup failed (2 days ago): repository "
             "contains errors. Last test restore: none yet."),
            ("the test restore failed", {"run": good, "test": rec("failed", DAY, reason="1 file did not come back from the "
                                                                    "backup of 2026-10-29 06:10 (1234abcd); the first: /etc/fstab: "
                                                                    "ciphertext verification failed"),
                                         "test_ok": rec("ok", 40 * DAY)}, {}, "attention",
             "Backed up 6 hours ago. The last test restore failed (1 day ago): 1 file did not come back from the backup of "
             "2026-10-29 06:10 (1234abcd); the first: /etc/fstab: ciphertext verification failed."),
            ("no test restore has passed for too long", {"run": good, "test_ok": rec("ok", 50 * DAY)}, {}, "attention",
             "Backed up 6 hours ago. No test restore has passed in 50 days."),
            ("none ever passed, and the backups are old", {"run": good, "first_ok_ts": NOW - 60 * DAY}, {}, "attention",
             "Backed up 6 hours ago. No test restore has passed in 60 days."),
            ("a restore in place stopped part-way", {"run": good, "test_ok": rec("ok", 2 * DAY)},
             dict(restore={"unfinished": {"snapshot": "1234abcd", "paths": ["/etc"], "snapshot_at": "x", "started": "y"}}),
             "attention", "Backed up 6 hours ago. Last test restore: 2 days ago, passed. A restore stopped part-way: some "
             "files are from the backup and some aren't."),
        ]
        for name, st, more, state, words in cases:
            with self.subTest(name):
                h = self.verdict(st, **more)
                self.assertEqual((h["state"], h["verdict"]), (state, words))
                self.assertEqual(h["state"] == "attention", any(p["severity"] != "info" for p in h["problems"]))

    def test_the_verdict_is_never_quieter_than_the_problems(self):
        mix = {"unfinished": {"snapshot": "1234abcd", "paths": [], "snapshot_at": "x", "started": "y"}}
        cases = [
            ("nothing has run, and a check failed", {"check": rec("failed", DAY, reason="Fatal: repository contains errors")}, {},
             "No backup yet: the first one runs tonight. The last check of the backup failed (1 day ago): repository contains errors."),
            ("nothing has run, and a test restore failed", {"test": rec("failed", HOUR, reason="the backup can't be reached")}, {},
             "No backup yet: the first one runs tonight. The last test restore failed (1 hour ago): the backup can't be reached."),
            ("backups off, and a restore in place unfinished", {}, dict(to="", restore=mix),
             "Backups are off: nothing on this server is backed up. To turn them on, say where they go: [backup] to in "
             "/etc/bromigos/server.toml. A restore stopped part-way: some files are from the backup and some aren't."),
            ("late, and the check failed too", {"run": rec("ok", 9 * DAY), "check": rec("failed", DAY, reason="x")}, {},
             "No backup in 9 days: the nightly backup has not run (the server may have been off, or its timer stopped). "
             "The last check of the backup failed (1 day ago): x. Last test restore: none yet."),
        ]
        for name, st, more, words in cases:
            with self.subTest(name):
                h = self.verdict(st, **more)
                self.assertEqual((h["state"], h["verdict"]), ("attention", words))
                self.assertTrue(h["problems"])
        h = self.verdict({}, to="", restore=mix)
        self.assertEqual(h["problems"][0]["detail"].split("Running it again finishes it: ")[1],
                         "bromigos lab backups restore 1234abcd --in-place --apply")

    def test_a_state_file_that_is_wrong_never_stops_the_status(self):
        odd = [None, [], "x", {"run": "ok"}, {"run": []}, {"run": {"phase": "ok"}}, {"run": {"phase": "ok", "ts": "soon"}},
               {"run": {"phase": "failed", "reason": ["a", "list"], "ts": NOW}}, {"run": {"phase": "partial", "reason": 7}},
               {"run_ok": "yes", "run": {"phase": "ok", "ts": NOW}}, {"run_ok": {}, "check": {"phase": "failed", "reason": None}},
               {"run": rec("ok", HOUR), "check": {"phase": "ok", "data": True}, "test": {"phase": "failed", "reason": {"a": 1}}},
               {"run": rec("ok", HOUR), "test_ok": {"ts": None}, "first_ok_ts": "then", "snapshots": {"count": "many"}},
               {"run": rec("ok", HOUR), "first_ok_ts": True, "snapshots": [1], "test": 5, "check_ok": 3},
               {"run": rec("failed", HOUR, files="some", bytes="lots", snapshot=7), "run_ok": rec("ok", DAY, files=None, bytes={})}]
        import contextlib
        import io
        for st in odd:
            with self.subTest(st=st):
                h = self.verdict(st)
                self.assertIn(h["state"], ("ok", "attention", "waiting"))
                self.assertTrue(h["verdict"])
                self.assertIsInstance(B.had_backup(st), bool)
                d = {"now": NOW, "configured": True, "to": S3, "destination": {"kind": "s3", "path": "", "present": None},
                     "timers": {}, "health": h, "last_backup": h["backup"], "last_success": h["success"], "last_check": h["check"],
                     "last_read_back": h["read_back"], "last_test": h["test"], "last_test_passed": h["test_passed"],
                     "snapshots": h["snapshots"], "restore": None, "running": None}
                with contextlib.redirect_stdout(io.StringIO()):
                    B.print_status(d)
        self.assertEqual(self.verdict({"run": {"phase": "ok"}})["verdict"],
                         "Backed up at a time that wasn't recorded. Last test restore: none yet.")
        self.assertEqual(B.when(None), "an unknown time")
        self.assertEqual((B.where("sftp://ada:pw@nas.example/b"), B.same_place("sftp://ada:pw@nas.example/b")),
                         ("sftp://nas.example/b", "sftp://ada@nas.example/b"))

    def test_a_path_as_a_line_of_a_restic_include_file(self):
        self.assertEqual(B.include_line("/srv/a [1]*?.txt"), "/srv/a \\[1]\\*\\?.txt")
        self.assertEqual(B.include_line("/srv/cost $HOME.txt"), "/srv/cost $$HOME.txt")
        self.assertEqual(B.include_line("/srv/ends in spaces \t"), "/srv/ends in spaces[ ][\t]")
        self.assertIsNone(B.include_line("/srv/two\nlines"))

    def test_what_is_unknown_is_said_not_guessed(self):
        h = self.verdict({"run": rec("ok", 6 * HOUR)})
        self.assertIsNone(h["snapshots"], "not counted until a backup counts them")
        self.assertIsNone(h["check"])
        self.assertIsNone(h["test"])
        d = {"now": NOW, "configured": True, "to": S3, "destination": {"kind": "s3", "present": None}, "timers": {},
             "health": {"verdict": h["verdict"], "problems": []}, "last_backup": h["backup"], "last_success": h["success"],
             "last_check": None, "last_read_back": None, "last_test": None, "last_test_passed": None, "snapshots": None,
             "restore": None, "running": None}
        import contextlib
        import io
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            B.print_status(d)
        for line in ("Last check    none yet", "Read-back     none yet", "Test restore  none yet", "Backups kept  not counted yet",
                     "check weekly (unknown)"):
            self.assertIn(line, out.getvalue())

    def test_the_thresholds(self):
        self.assertEqual(self.verdict({"run": rec("ok", 36 * HOUR - 60)})["state"], "ok")
        self.assertEqual(self.verdict({"run": rec("ok", 36 * HOUR + 60)})["problems"][0]["title"], "No backup for 36 hours")
        fresh = rec("ok", HOUR)
        self.assertEqual(self.verdict({"run": fresh, "test_ok": rec("ok", 45 * DAY - 60)})["problems"], [])
        self.assertEqual(self.verdict({"run": fresh, "test_ok": rec("ok", 45 * DAY + 60)})["problems"][0]["id"], "test-stale")
        # a failed test restore is said once, not also as "none passed"
        got = self.verdict({"run": fresh, "test": rec("failed", HOUR, reason="x"), "test_ok": rec("ok", 90 * DAY)})["problems"]
        self.assertEqual([p["id"] for p in got], ["test-failed"])

    def test_a_folder_destination_that_is_not_there(self):
        with tempfile.TemporaryDirectory() as d:
            to = os.path.join(d, "drive")
            self.assertEqual(B.destination(to, True, real=lambda p: p)["present"], False)
            self.assertIsNone(B.destination(to, False, real=lambda p: p)["present"], "a folder no backup has gone to yet")
            os.mkdir(to)
            self.assertEqual(B.destination(to, True, real=lambda p: p)["present"], False, "an empty mount point")
            self.assertIsNone(B.destination(to, False, real=lambda p: p)["present"], "a new, empty destination")
            Path(to, "config").write_text("restic's")
            self.assertEqual(B.destination(to, True, real=lambda p: p)["present"], True)
        self.assertEqual(B.destination(S3), {"kind": "s3", "path": "", "present": None})
        self.assertEqual(B.where("s3:https://user:secret@s3.example/b"), "s3:https://s3.example/b")


class Rig(unittest.TestCase):
    """A stand-in bromigOS Server: /etc, /home and /srv with files in them, a folder
    destination at /mnt/backup and, with backed_up, one real backup of it. The backup is made
    once for the class (restic's key takes half a second to open each time); every test gets
    the server back as it was then."""

    snapper = False
    backed_up = True

    @classmethod
    def setUpClass(cls):
        cls.base = tempfile.TemporaryDirectory()
        t = Path(cls.base.name).resolve()
        cls.root, cls.fake, cls.bin, cls.home, cls.pristine = t / "root", t / "fake", t / "bin", t / "home", t / "pristine"
        for d in (cls.fake, cls.bin, cls.home):
            d.mkdir()
        for name, text in STUBS.items():
            (cls.bin / name).write_text(text)
            (cls.bin / name).chmod(0o755)
        for rel, text in {"etc/fstab": "/dev/sda1 / btrfs\n", "etc/hostname": "box\n", "etc/app/app.conf": "port = 8080\n",
                          "home/ada/docs/note.txt": "remember the milk\n", "home/ada/docs/big.bin": "x" * 70_000,
                          "home/ada/photos/one.jpg": "jpeg one\n", "home/ada/photos/two.jpg": "jpeg two\n",
                          ODD: "a name restic could misread\n",
                          "etc/bromigos/server.toml": '[backup]\nto = "/mnt/backup"\npaths = ["/etc", "/home", "/srv"]\n'}.items():
            (cls.root / rel).parent.mkdir(parents=True, exist_ok=True)
            (cls.root / rel).write_text(text)
        os.symlink("note.txt", cls.root / "home/ada/docs/latest")
        os.symlink("../photos", cls.root / "home/ada/docs/pictures")
        cls.snap = None
        if cls.backed_up and RESTIC:
            r = subprocess.run([sys.executable, "-I", str(SERVER), "backup", "run"], env=cls.environment(), capture_output=True, text=True)
            assert r.returncode == 0, r.stderr
            cls.snap = json.loads((cls.root / "var/lib/bromigos/server/backup.json").read_text())["run"]["snapshot"]
        shutil.copytree(cls.root, cls.pristine, symlinks=True)

    @classmethod
    def tearDownClass(cls):
        cls.base.cleanup()

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()                         # for what a test makes outside the server
        self.procs = []
        shutil.rmtree(self.root)
        shutil.copytree(self.pristine, self.root, symlinks=True)
        shutil.rmtree(self.fake)
        self.fake.mkdir()
        (self.fake / "snapper-configs.json").write_text(json.dumps({"configs": [{"config": "root", "subvolume": "/"}]}))

    def tearDown(self):
        for p in self.procs:                                             # a command a failed test left running
            if p.poll() is None:
                p.kill()
                p.communicate()
        try:
            os.kill(int((self.fake / "hanging").read_text()), signal.SIGKILL)       # a stand-in restic left hanging
        except (OSError, ValueError):
            pass
        self.tmp.cleanup()
        # nothing reached for this machine: no sudo, and snapper only where a test named its stand-in
        self.assertNotIn("sudo ", self.log())
        if not self.snapper:
            self.assertNotIn("snapper ", self.log())

    @classmethod
    def environment(cls, snapper=False, **more):
        env = {k: v for k, v in os.environ.items() if k not in ("WAYLAND_DISPLAY", "DISPLAY", "PYTHONPATH", "RESTIC_REPOSITORY",
                                                                 "RESTIC_PASSWORD", "BROMIGOS_BACKUPS_FREE_BYTES")}
        env.update(PATH=f"{cls.bin}:/usr/bin:/bin", FAKE=str(cls.fake), REAL_RESTIC=RESTIC or "restic", HOME=str(cls.home),
                   XDG_CONFIG_HOME=str(cls.home / ".config"), XDG_STATE_HOME=str(cls.home / ".local/state"),
                   XDG_CACHE_HOME=str(cls.home / ".cache"), BROMIGOS_SERVER_ROOT=str(cls.root),
                   BROMIGOS_SERVER_SHARE=str(REPO / "server"), TZ="UTC")
        # the commands of the machine these tests run on are never the server's: snapper and systemctl
        # are run only as the stand-ins named here (a plain `snapper` on PATH is a stand-in too, and
        # every test checks it was never run)
        env["BROMIGOS_BACKUPS_SYSTEMCTL"] = str(cls.bin / "systemctl")
        if snapper:
            env["BROMIGOS_BACKUPS_SNAPPER"] = str(cls.bin / "snapper")
        env.update(more)
        return env

    def env(self, **more):
        return self.environment(self.snapper, **more)

    def spawn(self, *args):
        p = subprocess.Popen([sys.executable, str(LAB), "backups", *args], env=self.env(), stdout=subprocess.PIPE,
                             stderr=subprocess.PIPE, text=True, stdin=subprocess.DEVNULL, start_new_session=True)
        self.procs.append(p)
        deadline = time.time() + 60
        while not (self.fake / "hanging").exists():                      # until the stand-in restic hangs
            self.assertIsNone(p.poll(), "it ended before restic hung")
            self.assertLess(time.time(), deadline)
            time.sleep(0.05)
        return p

    def put(self, rel, text):
        p = self.root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)

    def lab(self, *args, **more):
        return subprocess.run([sys.executable, str(LAB), "backups", *args], env=self.env(**more), capture_output=True, text=True,
                              stdin=subprocess.DEVNULL)

    def doc(self, *args, rc=0, **more):
        r = self.lab(*args, "--json", **more)
        self.assertEqual(r.returncode, rc, r.stderr + r.stdout)
        return json.loads(r.stdout)

    def server(self, *args):
        return subprocess.run([sys.executable, "-I", str(SERVER), *args], env=self.env(), capture_output=True, text=True)

    def backup(self):
        r = self.server("backup", "run")
        self.assertEqual(r.returncode, 0, r.stderr)
        return self.state()["run"]["snapshot"]

    def state(self):
        return json.loads((self.root / "var/lib/bromigos/server/backup.json").read_text())

    def log(self):
        return (self.fake / "log").read_text() if (self.fake / "log").exists() else ""

    def tree(self, top=None, under=("etc", "home", "srv/data")):
        """{path: what's there}: every file's bytes, every link's target, every folder."""
        top, out = Path(top or self.root), {}
        for sub in under:
            for d, dirs, files in os.walk(top / sub):
                for n in dirs + files:
                    p = Path(d, n)
                    rel = "/" + str(p.relative_to(top))
                    out[rel] = ("link", os.readlink(p)) if p.is_symlink() else ("folder",) if p.is_dir() else ("file", p.read_bytes())
        return out

    def restored(self):
        return sorted(p.name for p in (self.root / "srv/restore").iterdir()) if (self.root / "srv/restore").is_dir() else []


@unittest.skipUnless(RESTIC, "restic isn't installed")
class Status(Rig):
    backed_up = False

    def test_not_a_server_and_off(self):
        shutil.rmtree(self.root / "etc/bromigos")
        d = self.doc(rc=3)
        self.assertEqual((d["ok"], d["server"], d["error"]["code"]), (False, False, "not-a-server"))
        self.assertIn("isn't a bromigOS Server", self.lab().stderr)
        self.assertEqual(self.doc("list", rc=3)["error"]["code"], "not-a-server")
        self.put("etc/bromigos/server.toml", "[health]\nminutes = 10\n")
        d = self.doc()
        self.assertEqual((d["configured"], d["health"]["state"], d["health"]["problems"]), (False, "off", []))
        self.assertTrue(self.lab().stdout.startswith("Backups are off: nothing on this server is backed up."))
        for verb in ("list", "show", "restore", "test"):
            self.assertEqual(self.doc(verb, rc=3)["error"]["code"], "off")

    def test_the_status_after_a_backup_a_check_and_a_test_restore(self):
        d = self.doc()
        self.assertEqual((d["health"]["state"], d["health"]["verdict"]), ("waiting", "No backup yet: the first one runs tonight."))
        snap = self.backup()
        d = self.doc()
        self.assertEqual(sorted(d), sorted(
            ["schema", "ok", "server", "configured", "to", "destination", "timers", "health", "last_backup", "last_success",
             "last_check", "last_check_passed", "last_read_back", "last_test", "last_test_passed", "snapshots", "drives",
             "restore", "running", "checked_at", "now"]))
        self.assertEqual(d["drives"], [], "no Go Bag is set up (test_lab_backup_drive.py has the rest)")
        self.assertEqual((d["schema"], d["ok"], d["server"], d["configured"], d["to"]), (1, True, True, True, "/mnt/backup"))
        self.assertEqual(d["destination"], {"kind": "folder", "path": "/mnt/backup", "present": True})
        self.assertEqual(d["timers"], {"backup": "active", "check": "active", "test": "active"})
        self.assertEqual(sorted(d["health"]), ["problems", "state", "verdict"])
        self.assertEqual((d["health"]["state"], d["health"]["verdict"]), ("ok", "Backed up just now. Last test restore: none yet."))
        self.assertEqual((d["last_backup"]["phase"], d["last_backup"]["snapshot"], d["last_success"]["snapshot"]), ("ok", snap, snap))
        self.assertEqual(d["last_backup"]["files"], 10)                 # 8 files, the settings and the key
        self.assertEqual((d["snapshots"]["count"], d["last_check"], d["last_test"], d["restore"], d["running"]), (1, None, None, None, None))
        self.assertEqual(self.server("backup", "check", "--data").returncode, 0)
        self.assertEqual(self.lab("test").returncode, 0)
        d = self.doc()
        self.assertEqual((d["last_check"]["phase"], d["last_read_back"]["phase"], d["last_test"]["phase"]), ("ok", "ok", "ok"))
        self.assertEqual(d["health"]["verdict"], "Backed up just now. Last test restore: just now, passed.")
        out = self.lab().stdout
        self.assertEqual(out.splitlines()[0], d["health"]["verdict"])
        for line in ("Destination   /mnt/backup", f"Last backup   worked, just now (", f"snapshot {snap}, 10 files",
                     "Last check    passed, just now", "Read-back     5 % of the data read back just now, passed",
                     "Test restore  passed just now (", "): 10 files restored and read back, a sample", "Backups kept  1 backup, from ",
                     "Schedule      backup nightly (active), check weekly (active), test restore monthly (active)"):
            self.assertIn(line, out)
        # `bromigos server` says the same verdict
        self.assertIn("Backups      Backed up just now. Last test restore: just now, passed. To /mnt/backup.", self.server("status").stdout)

    def test_a_drive_that_is_not_connected(self):
        self.backup()
        os.rename(self.root / "mnt/backup", self.root / "mnt/unplugged")
        self.assertEqual(self.doc()["health"]["state"], "ok", "nothing is late yet")
        self.assertEqual(self.server("backup", "run").returncode, 1)
        d = self.doc(rc=1)
        self.assertEqual(d["destination"]["present"], False)
        self.assertEqual(d["health"]["verdict"], "The last backup failed: the drive at /mnt/backup is not connected. The one "
                         "before it worked, just now. Last test restore: none yet.")
        st = self.state()
        st["run_ok"]["ts"] -= 9 * DAY
        (self.root / "var/lib/bromigos/server/backup.json").write_text(json.dumps(st))
        r = self.lab()
        self.assertEqual(r.returncode, 1)
        self.assertEqual(r.stdout.splitlines()[0], "No backup in 9 days: the drive at /mnt/backup is not connected. Last test restore: none yet.")
        self.assertIn("Destination   /mnt/backup (not connected)", r.stdout)
        for verb in (["list"], ["show"], ["restore"]):
            e = self.doc(*verb, rc=1)["error"]
            self.assertEqual((e["code"], e["message"]), ("unreachable", "The backup can't be reached: the drive at /mnt/backup is not connected."))
        self.assertEqual(self.restored(), [])
        # a test restore that can't run is a failed one: nobody knows the backup restores
        self.assertEqual(self.doc("test", rc=1)["error"]["message"], "The backup can't be reached: the drive at /mnt/backup is not connected.")
        self.assertIn("The last test restore failed (just now): the backup can't be reached: the drive at /mnt/backup is not connected.",
                      self.doc(rc=1)["health"]["verdict"])
        os.rename(self.root / "mnt/unplugged", self.root / "mnt/backup")
        self.assertEqual(self.lab("test").returncode, 0)

    def test_the_key_is_never_made_here(self):
        self.backup()
        key = self.root / "etc/bromigos/server/backup.key"
        key.unlink()
        for verb in ("list", "show", "restore"):
            self.assertEqual(self.doc(verb, rc=1)["error"]["code"], "no-key")
        self.assertFalse(key.exists())
        key.write_text("not the key\n")
        self.assertEqual(self.doc("list", rc=1)["error"]["code"], "wrong-key")


@unittest.skipUnless(RESTIC, "restic isn't installed")
class ListAndShow(Rig):
    def test_list_and_show(self):
        first = self.snap
        self.put("etc/hostname", "renamed\n")
        second = self.backup()
        d = self.doc("list")
        self.assertEqual((d["schema"], d["ok"], d["to"], [s["short_id"] for s in d["snapshots"]]), (1, True, "/mnt/backup", [first, second]))
        s = d["snapshots"][1]
        self.assertEqual(sorted(s), ["added_bytes", "at", "bytes", "files", "host", "id", "nightly", "paths", "short_id", "tags", "time", "ts"])
        self.assertEqual((s["paths"], s["files"], s["nightly"], s["tags"]), (["/etc", "/home", "/srv"], 10, True, ["bromigos-server"]))
        self.assertGreater(s["bytes"], 70_000)
        out = self.lab("list").stdout
        self.assertIn("2 backups at /mnt/backup, newest first:", out)
        self.assertLess(out.index(second), out.index(first))
        self.assertRegex(out, rf"{second}  \d{{4}}-\d\d-\d\d \d\d:\d\d +70 KB +10 files  /etc, /home, /srv")
        # show: the top, then a folder at a time; no id is the newest
        d = self.doc("show")
        self.assertEqual((d["snapshot"]["short_id"], d["path"], [(e["path"], e["type"]) for e in d["entries"]]),
                         (second, None, [("/etc", "dir"), ("/home", "dir"), ("/srv", "dir")]))
        d = self.doc("show", first, "/home/ada/docs")
        self.assertEqual({e["name"]: (e["type"], e["size"]) for e in d["entries"]},
                         {"big.bin": ("file", 70_000), "latest": ("symlink", None), "note.txt": ("file", 18), "pictures": ("symlink", None)})
        self.assertEqual(sorted(d["entries"][0]), ["mtime", "mtime_ts", "name", "path", "permissions", "size", "type"])
        self.assertEqual([e["path"] for e in self.doc("show", "/etc/fstab")["entries"]], ["/etc/fstab"])
        out = self.lab("show", second, "/home/ada").stdout
        self.assertIn(f"Backup {second} · ", out)
        self.assertRegex(out, r"folder +\d{4}-\d\d-\d\d \d\d:\d\d  docs/")
        self.assertEqual(self.doc("show", second, "/nope", rc=2)["error"]["code"], "not-in-backup")
        self.assertEqual(self.doc("show", "feedface", rc=2)["error"]["code"], "no-such-backup")
        self.assertEqual(self.doc("show", second, "etc", rc=2)["error"]["code"], "usage")


@unittest.skipUnless(RESTIC, "restic isn't installed")
class RestoreToANewFolder(Rig):
    def test_a_whole_backup_into_a_new_named_folder(self):
        snap = self.snap
        before = self.tree()
        self.put("etc/fstab", "changed since the backup\n")
        (self.root / "home/ada/docs/note.txt").unlink()
        now = self.tree()
        r = self.lab("restore")
        self.assertEqual(r.returncode, 0, r.stderr)
        (name,) = self.restored()
        self.assertRegex(name, rf"^backup-\d{{4}}-\d\d-\d\d-\d{{4}}-{snap}$")
        dest = self.root / "srv/restore" / name
        self.assertEqual(self.tree(dest), before, "every file, link and folder as it was when backed up")
        self.assertEqual(self.tree(), now, "nothing on the server was replaced")
        self.assertEqual(dest.stat().st_mode & 0o777, 0o700)
        self.assertFalse((dest / B.MARKER).exists())
        steps = ["[1/5] Finding the backup", "[2/5] Working out what to restore", "[3/5] Checking free space",
                 "[4/5] Restoring the files, then reading each one back", "[5/5] Finishing"]
        self.assertEqual([line for line in r.stdout.splitlines() if line.startswith("[")], steps)
        for line in (f"Restored 12 files (70 KB) from the backup of ", f"  into {dest}", "Nothing on the server was replaced.",
                     "Skipped: nothing."):
            self.assertIn(line, r.stdout)
        # again: another new folder, never the same one
        d = self.doc("restore", snap)
        self.assertEqual(self.restored(), [name, name + "-2"])
        self.assertEqual(sorted(d), ["bytes", "files", "mode", "ok", "paths", "replaced", "schema", "skipped", "snapshot", "state",
                                     "target", "verified"])
        self.assertEqual((d["ok"], d["state"], d["mode"], d["files"], d["replaced"], d["skipped"], d["verified"], d["target"]),
                         (True, "done", "new-folder", 12, 0, [], True, str(dest) + "-2"))
        rec = self.doc()["restore"]
        self.assertEqual((rec["kind"], rec["mode"], rec["state"], rec["interrupted"], rec["running"], rec["snapshot"]),
                         ("restore", "new-folder", "done", False, False, snap))
        self.assertEqual([s["state"] for s in rec["steps"]], ["done"] * 5)

    def test_chosen_paths_and_json_steps(self):
        snap = self.snap
        dest = Path(self.tmp.name) / "out"
        r = self.lab("restore", "/home/ada/docs/note.txt", "/" + ODD, "/home/ada/photos", "--to", str(dest), "--json")
        self.assertEqual(r.returncode, 0, r.stderr)
        d = json.loads(r.stdout)                                       # one document on stdout
        self.assertEqual((d["snapshot"]["short_id"], d["files"], d["target"]), (snap, 4, str(dest)))
        got = {str(p.relative_to(dest)) for p in dest.rglob("*") if not p.is_dir()}
        self.assertEqual(got, {"home/ada/docs/note.txt", ODD, "home/ada/photos/one.jpg", "home/ada/photos/two.jpg"})
        events = [json.loads(line) for line in r.stderr.splitlines()]  # the named steps, as JSON lines on stderr
        self.assertEqual([(e["id"], e["n"], e["of"]) for e in events if e["event"] == "step"],
                         [("find", 1, 5), ("size", 2, 5), ("space", 3, 5), ("restore", 4, 5), ("finish", 5, 5)])
        self.assertEqual(self.doc("restore", snap, "/etc/nope", rc=2)["error"]["code"], "not-in-backup")
        self.assertEqual(self.doc("restore", "/etc/fstab", "--to", str(dest / "x"), "--apply", rc=2)["error"]["code"], "usage")

    def test_it_refuses_to_write_where_there_are_files(self):
        full = Path(self.tmp.name) / "full"
        full.mkdir()
        (full / "mine.txt").write_text("keep me\n")
        for target in (full, full / "mine.txt", self.root / "etc"):
            with self.subTest(target=target.name):
                before = self.tree()
                e = self.doc("restore", "--to", str(target), rc=3)["error"]
                self.assertEqual(e["code"], "would-overwrite")
                self.assertEqual((full / "mine.txt").read_text(), "keep me\n")
                self.assertEqual(sorted(p.name for p in full.iterdir()), ["mine.txt"])
                self.assertEqual(self.tree(), before)
        self.assertIn("Restore never writes into a folder with files in it", self.lab("restore", "--to", str(full)).stderr)
        self.assertFalse(Path(str(full) + ".partial").exists())
        # nor into a .partial folder that isn't this restore's own, stopped part-way
        other = Path(self.tmp.name) / "taken.partial"
        other.mkdir()
        (other / "theirs.txt").write_text("someone else's\n")
        self.assertEqual(self.doc("restore", "--to", str(Path(self.tmp.name) / "taken"), rc=3)["error"]["code"], "would-overwrite")
        self.assertEqual(sorted(p.name for p in other.iterdir()), ["theirs.txt"])
        # a folder that's there and empty is fine
        empty = Path(self.tmp.name) / "empty"
        empty.mkdir()
        self.assertEqual(self.doc("restore", "/etc/fstab", "--to", str(empty))["target"], str(empty))
        self.assertEqual((empty / "etc/fstab").read_text(), "/dev/sda1 / btrfs\n")
        self.assertEqual(sorted(p.name for p in empty.iterdir()), ["etc"], "its work folder was inside it, and is gone")
        self.assertFalse(Path(str(empty) + ".partial").exists())

    def test_too_little_free_space(self):
        before = self.tree()
        e = self.doc("restore", rc=4, BROMIGOS_BACKUPS_FREE_BYTES=str(60_000))["error"]
        self.assertEqual((e["code"], e["need"] > 70_000, e["free"]), ("no-space", True, 60_000))
        self.assertIn("Not enough room: the restore needs 70 KB and", e["message"])
        self.assertIn("Nothing was restored.", e["message"])
        self.assertEqual(self.restored(), [], "not even a folder was made")
        self.assertEqual(self.tree(), before)
        self.assertEqual(self.doc()["restore"]["state"], "failed")
        # the margin counts: room for the files alone isn't enough
        self.assertEqual(self.doc("restore", rc=4, BROMIGOS_BACKUPS_FREE_BYTES=str(71_000))["error"]["code"], "no-space")
        # a smaller pick fits
        self.assertEqual(self.doc("restore", "/etc", BROMIGOS_BACKUPS_FREE_BYTES=str(B.MARGIN + 10_000))["state"], "done")

    def stop_part_way(self, *args, sig=signal.SIGINT):
        """Start a restore whose restic restores one file and then hangs; stop it."""
        (self.fake / "hang").write_text("/etc/fstab")
        p = self.spawn("restore", *args)
        p.send_signal(sig)
        out, err = p.communicate(timeout=60)
        (self.fake / "hang").unlink()
        return p.returncode, out, err

    def test_an_interrupted_restore_is_never_taken_for_a_whole_one(self):
        snap = self.snap
        before = self.tree()
        rc, out, err = self.stop_part_way()
        self.assertEqual(rc, 130)
        (name,) = self.restored()
        self.assertTrue(name.endswith(f"{snap}.partial"), name)
        work = self.root / "srv/restore" / name
        self.assertTrue((work / B.MARKER).is_file(), "the folder says it's incomplete")
        self.assertEqual((work / "etc/fstab").read_text(), "/dev/sda1 / btrfs\n")
        self.assertFalse((work / "home").exists(), "half a tree")
        self.assertIn(f"Stopped. What was restored so far is in {work}: it is incomplete", err)
        with self.assertRaises(ProcessLookupError, msg="restic was stopped too"):
            os.kill(int((self.fake / "hanging").read_text()), 0)
        d = self.doc()
        self.assertEqual((d["restore"]["state"], d["restore"]["interrupted"], d["restore"]["work"]), ("interrupted", True, str(work)))
        # another pick isn't poured into it: the folder would look whole and not be
        e = self.doc("restore", "/srv", rc=3)["error"]
        self.assertEqual(e["code"], "other-restore")
        self.assertFalse((work / "srv").exists())
        self.assertIn("Last restore  stopped part-way", self.lab().stdout)
        self.assertEqual(self.tree(), before)
        # the same command again carries on, and only then does the folder get its name
        (self.fake / "hanging").unlink()
        r = self.lab("restore")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("carrying on in", r.stdout)
        self.assertEqual(self.restored(), [name.removesuffix(".partial")])
        self.assertEqual(self.tree(self.root / "srv/restore" / name.removesuffix(".partial")), before)

    def test_a_restore_that_was_killed(self):
        rc, _, _ = self.stop_part_way("--json", sig=signal.SIGKILL)
        self.assertEqual(rc, -signal.SIGKILL)
        d = self.doc()
        self.assertEqual((d["restore"]["state"], d["restore"]["interrupted"], d["restore"]["running"]), ("running", True, False),
                         "it says running, and its process is gone")
        (name,) = self.restored()
        self.assertTrue(name.endswith(".partial"))
        self.assertTrue((self.root / "srv/restore" / name / B.MARKER).is_file())


@unittest.skipUnless(RESTIC, "restic isn't installed")
class RestoreInPlace(Rig):
    snapper = True

    def damage(self):
        """What a bad day does: files changed, files gone, a link pointing elsewhere, and new
        files the backup never had."""
        self.put("etc/fstab", "wrong\n")
        self.put("home/ada/docs/big.bin", "y" * 70_000)                 # the same size, other bytes
        (self.root / "home/ada/docs/note.txt").unlink()
        shutil.rmtree(self.root / "home/ada/photos")
        os.unlink(self.root / "home/ada/docs/latest")
        os.symlink("big.bin", self.root / "home/ada/docs/latest")
        self.put("etc/new-since.conf", "not in the backup\n")
        self.put("srv/data/new/too.txt", "nor this\n")

    def test_the_dry_run_is_the_default_and_lists_exactly_what_changes(self):
        snap = self.snap
        good = self.tree()
        self.damage()
        before = self.tree()
        r = self.lab("restore", "--in-place")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.tree(), before, "a look changes nothing")
        self.assertNotIn("create", self.log())
        for line in ("replace 3 files that changed since the backup:", "/etc/fstab   (now 6 bytes, changed ",
                     "/home/ada/docs/latest   (a link that points somewhere else now)",
                     "bring back 4 files and folders that are gone:", "/home/ada/photos/one.jpg",
                     "leave alone everything that isn't in the backup: nothing is ever deleted",
                     'First, a snapshot of / is taken (snapper\'s "root"), so this can be undone.',
                     f"Nothing was changed: this was only a look. To do it: bromigos lab backups restore {snap} --in-place --apply"):
            self.assertIn(line, r.stdout)
        plan = self.doc("restore", "--in-place")
        self.assertEqual((plan["state"], plan["applied"], plan["mode"]), ("planned", False, "in-place"))
        self.assertEqual([p["path"] for p in plan["replace"]], ["/etc/fstab", "/home/ada/docs/big.bin", "/home/ada/docs/latest"])
        self.assertEqual([p["path"] for p in plan["add"]],
                         ["/home/ada/docs/note.txt", "/home/ada/photos", "/home/ada/photos/one.jpg", "/home/ada/photos/two.jpg"])
        self.assertEqual(sorted(plan["replace"][0]), ["now_modified", "now_size", "path", "size"])
        self.assertEqual(plan["safety"], [{"subvolume": "/", "config": "root", "files": 7, "bytes": plan["bytes"]}])
        self.assertEqual(self.tree(), before)
        # it needs a yes, and the list has to be the one that was shown
        self.assertEqual(self.doc("restore", "--in-place", "--apply", rc=3)["error"]["code"], "needs-yes")
        self.assertEqual(self.lab("restore", "--in-place", "--apply").returncode, 3, "no terminal to ask: no")
        self.put("etc/hostname", "changed after the look\n")
        e = self.doc("restore", "--in-place", "--apply", "--yes", "--plan", plan["digest"], rc=3)["error"]
        self.assertEqual(e["code"], "plan-changed")
        self.assertNotIn("create", self.log())
        self.put("etc/hostname", "box\n")
        self.assertEqual(self.tree(), before)
        fstab = self.root / "etc/fstab"                                 # a listed file touched again since the look
        was = fstab.stat()
        os.utime(fstab, ns=(was.st_atime_ns, was.st_mtime_ns + 5_000_000_000))
        self.assertEqual(self.doc("restore", "--in-place", "--apply", "--yes", "--plan", plan["digest"], rc=3)["error"]["code"],
                         "plan-changed")
        os.utime(fstab, ns=(was.st_atime_ns, was.st_mtime_ns))
        # apply: what changed on the server is the list, no more and no less
        d = self.doc("restore", "--in-place", "--apply", "--yes", "--plan", plan["digest"])
        after = self.tree()
        changed = {p for p in after if after[p] != before.get(p)}
        self.assertEqual(changed, {p["path"] for p in plan["replace"] + plan["add"]})
        self.assertEqual({p for p in before if p not in after}, set(), "nothing was deleted")
        self.assertEqual({p: after[p] for p in good}, good, "everything in the backup is back")
        self.assertEqual(after["/etc/new-since.conf"], ("file", b"not in the backup\n"))
        self.assertEqual(after["/srv/data/new/too.txt"], ("file", b"nor this\n"))
        self.assertEqual((d["ok"], d["state"], d["applied"], d["replaced"], d["added"], d["skipped"], d["verified"]),
                         (True, "done", True, 3, 4, [], True))
        self.assertEqual(d["snapshots_taken"], [{"subvolume": "/", "config": "root", "number": 42}])
        log = self.log().splitlines()
        took = [i for i, line in enumerate(log) if " create " in line + " "]
        self.assertEqual(len(took), 1)
        self.assertIn(f"before restoring from backup {snap}", log[took[0]])
        self.assertLess(took[0], log.index("restic restore"), "the snapshot comes before the first file is written")
        # done: a second look finds nothing to do
        again = self.doc("restore", "--in-place", "--apply", "--yes")
        self.assertEqual((again["applied"], again["replace"], again["add"]), (False, [], []))
        self.assertIn("there is nothing to do: every file already matches the backup", self.lab("restore", "--in-place").stdout)

    def test_chosen_paths_in_place(self):
        self.damage()
        before = self.tree()
        r = self.lab("restore", "/etc/fstab", "/home/ada/photos", "--in-place", "--apply", "--yes")
        self.assertEqual(r.returncode, 0, r.stderr)
        after = self.tree()
        self.assertEqual({p for p in after if after[p] != before.get(p)},
                         {"/etc/fstab", "/home/ada/photos", "/home/ada/photos/one.jpg", "/home/ada/photos/two.jpg"})
        self.assertEqual([line for line in r.stdout.splitlines() if line.startswith("[")],
                         ["[1/6] Finding the backup", "[2/6] Working out what would change", "[3/6] Checking free space",
                          "[4/6] Taking a snapshot of the files as they are now",
                          "[5/6] Putting the files back, then reading each one back", "[6/6] Finishing"])
        for line in ("1 file replaced, 3 brought back,", "Files that aren't in the backup were left alone.",
                     "Before it, snapshot 42 of / was taken.", "Skipped: nothing."):
            self.assertIn(line, r.stdout)
        self.assertEqual(self.doc("restore", "--in-place", "--to", "/x", rc=2)["error"]["code"], "usage")

    def test_a_folder_that_became_a_link_is_never_written_through(self):
        outside = Path(self.tmp.name) / "outside"
        outside.mkdir()
        (outside / "one.jpg").write_text("not the server's\n")
        shutil.rmtree(self.root / "home/ada/photos")
        os.symlink(outside, self.root / "home/ada/photos")
        plan = self.doc("restore", "/home/ada/photos", "--in-place")
        self.assertEqual((plan["replace"][0]["path"], plan["replace"][0]["link"]), ("/home/ada/photos", "not a link in the backup"))
        self.assertIn("/home/ada/photos   (a link now; a file or a folder in the backup)",
                      self.lab("restore", "/home/ada/photos", "--in-place").stdout)
        self.assertEqual(self.lab("restore", "/home/ada/photos", "--in-place", "--apply", "--yes").returncode, 0)
        self.assertFalse((self.root / "home/ada/photos").is_symlink(), "a real folder again")
        self.assertEqual((self.root / "home/ada/photos/one.jpg").read_text(), "jpeg one\n")
        self.assertEqual({p.name: p.read_text() for p in outside.iterdir()}, {"one.jpg": "not the server's\n"})

    def test_no_snapshot_mechanism_is_said_plainly_and_needs_its_own_yes(self):
        self.damage()
        before = self.tree()
        self.snapper = False                                             # no snapper on this server
        plan = self.doc("restore", "/etc", "--in-place")
        self.assertEqual(plan["safety"], [{"subvolume": "/", "config": None, "files": 1, "bytes": plan["bytes"]}])
        self.assertIn("No snapshot can be taken of /: snapshots aren't set up for it. What this replaces there can't be brought "
                      "back afterwards.", self.lab("restore", "/etc", "--in-place").stdout)
        e = self.doc("restore", "/etc", "--in-place", "--apply", "--yes", rc=3)["error"]
        self.assertEqual(e["code"], "no-safety-snapshot")
        self.assertIn("Nothing was changed. To go ahead anyway, add --without-snapshot.", e["message"])
        self.assertEqual(self.tree(), before)
        r = self.lab("restore", "/etc", "--in-place", "--apply", "--yes", "--without-snapshot")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("No snapshot was taken first: the files that were replaced can't be brought back.", r.stdout)
        self.assertEqual((self.root / "etc/fstab").read_text(), "/dev/sda1 / btrfs\n")
        self.assertNotIn("snapper", self.log(), "the machine's own snapper is never run from a stand-in root")
        # nor its systemctl, nor a destination on a network: without stand-ins named, the timers are unknown
        d = self.doc(BROMIGOS_BACKUPS_SYSTEMCTL="")
        self.assertEqual(d["timers"], {"backup": "unknown", "check": "unknown", "test": "unknown"})
        self.put("etc/bromigos/server.toml", '[backup]\nto = "sftp://backup@nas.example/srv"\n')
        self.assertEqual(self.doc("list", rc=3)["error"]["code"], "stand-in")

    def test_a_snapshot_that_cannot_be_taken_stops_it(self):
        self.damage()
        before = self.tree()
        (self.fake / "snapper-fails").write_text("")
        e = self.doc("restore", "--in-place", "--apply", "--yes", rc=3)["error"]
        self.assertEqual(e["code"], "no-safety-snapshot")
        self.assertIn("couldn't be taken (IO error: no space for a snapshot), so nothing was changed", e["message"])
        self.assertEqual(self.tree(), before)
        self.assertNotIn("restic restore", self.log())
        self.assertEqual(self.doc()["restore"]["state"], "refused")
        self.assertEqual(self.doc()["health"]["state"], "ok", "a refused restore changed nothing")

    def test_too_little_free_space_in_place(self):
        self.damage()
        before = self.tree()
        e = self.doc("restore", "--in-place", "--apply", "--yes", rc=4, BROMIGOS_BACKUPS_FREE_BYTES="10")["error"]
        self.assertEqual(e["code"], "no-space")
        self.assertIn("Nothing was changed.", e["message"])
        self.assertEqual(self.tree(), before)
        self.assertNotIn(" create ", self.log())

    def test_an_interrupted_restore_in_place_is_on_the_health_line_until_it_is_finished(self):
        snap = self.snap
        good = self.tree()
        self.damage()
        rc, out, err = RestoreToANewFolder.stop_part_way(self, "--in-place", "--apply", "--yes", sig=signal.SIGTERM)
        self.assertEqual(rc, 130)
        again = f"bromigos lab backups restore {snap} --in-place --apply"
        self.assertIn(f"Stopped part-way: some files are from the backup and some are still as they were. Running it again "
                      f"finishes it: {again}. A snapshot of / was taken first (number 42).", err)
        self.assertEqual((self.root / "etc/fstab").read_text(), "/dev/sda1 / btrfs\n")
        self.assertFalse((self.root / "home/ada/photos").exists(), "half done")
        d = self.doc(rc=1)
        self.assertEqual(d["health"]["state"], "attention")
        self.assertTrue(d["health"]["verdict"].endswith("A restore stopped part-way: some files are from the backup and some aren't."))
        (p,) = d["health"]["problems"]
        self.assertEqual((p["id"], p["severity"], p["title"]), ("restore-interrupted", "needs_you", "A restore stopped part-way"))
        self.assertIn(again, p["detail"])
        self.assertIn("A restore stopped part-way.", self.lab().stdout)
        # another job in between doesn't make it forgotten
        (self.fake / "hanging").unlink()
        self.assertEqual(self.lab("restore", "/etc/hostname", "--to", str(Path(self.tmp.name) / "o")).returncode, 0)
        self.assertEqual(self.lab("test").returncode, 0)
        self.assertEqual([p["id"] for p in self.doc(rc=1)["health"]["problems"]], ["restore-interrupted"])
        # the same restore run to the end clears it
        journal = self.root / "var/lib/bromigos/server/restore.json"
        stopped = journal.read_text()
        self.assertEqual(self.lab("restore", snap, "--in-place", "--apply", "--yes").returncode, 0)
        d = self.doc()
        self.assertEqual((d["health"]["state"], d["health"]["problems"], d["restore"]["state"]), ("ok", [], "done"))
        after = self.tree()
        self.assertEqual({p: after[p] for p in good}, good)
        # one that stopped while reading the files back left nothing to redo: a look settles it
        journal.write_text(stopped)
        self.assertEqual([p["id"] for p in self.doc(rc=1)["health"]["problems"]], ["restore-interrupted"])
        self.assertIn("there is nothing to do", self.lab("restore", snap, "--in-place").stdout)
        self.assertEqual(self.doc()["health"]["problems"], [])


@unittest.skipUnless(RESTIC, "restic isn't installed")
class TestRestore(Rig):
    def scratch(self):
        d = self.root / "var/lib/bromigos/server/restore-test"
        return sorted(p.name for p in d.iterdir()) if d.is_dir() else []

    def test_a_sample_and_everything(self):
        snap = self.snap
        before = self.tree()
        r = self.lab("test")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual([line for line in r.stdout.splitlines() if line.startswith("[")],
                         ["[1/6] Finding the newest backup", "[2/6] Picking what to restore", "[3/6] Checking free space",
                          "[4/6] Restoring to a scratch folder, then reading each file back",
                          "[5/6] Comparing what came back with the backup's list", "[6/6] Removing the scratch folder"])
        self.assertIn("10 files picked at random out of 10", r.stdout)
        self.assertIn("The test restore passed: 10 files (70 KB) came back from the backup of ", r.stdout)
        self.assertEqual(self.scratch(), [], "cleaned up")
        self.assertEqual(self.tree(), before)
        os.link(self.root / "home/ada/photos/one.jpg", self.root / "home/ada/photos/one-again.jpg")    # one file, two names
        snap = self.backup()
        d = self.doc("test", "--all")
        self.assertEqual(sorted(d), ["ok", "schema", "snapshot", "state", "test"])
        self.assertEqual(sorted(d["test"]), ["at", "bytes", "files", "mode", "phase", "reason", "seconds", "snapshot", "ts"])
        self.assertEqual((d["ok"], d["state"], d["test"]["phase"], d["test"]["mode"], d["test"]["files"], d["test"]["snapshot"]),
                         (True, "passed", "ok", "all", 13, snap))
        self.assertEqual(self.scratch(), [])
        st = self.state()
        self.assertEqual((st["test"], st["test_ok"]), (d["test"], d["test"]))
        self.assertEqual(st["run"]["snapshot"], snap, "the backup's own record is kept")
        # quiet when it passes (the monthly timer), and through bromigos-server, as the timer runs it
        self.assertEqual(self.lab("test", "--quiet").stdout, "")
        r = self.server("backup", "test")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("The test restore passed", r.stdout)
        # a scratch folder of your own, and too little room in it
        mine = Path(self.tmp.name) / "scratch"
        (mine / "test-results-2019").mkdir(parents=True)                # yours, old, and named like a leftover
        (mine / "test-results-2019/keep.txt").write_text("mine\n")
        os.utime(mine / "test-results-2019", (1, 1))
        self.assertEqual(self.lab("test", "--scratch", str(mine)).returncode, 0)
        self.assertEqual(sorted(p.name for p in mine.iterdir()), ["bromigos-restore-test", "test-results-2019"])
        self.assertEqual((mine / "test-results-2019/keep.txt").read_text(), "mine\n")
        self.assertEqual(list((mine / "bromigos-restore-test").iterdir()), [], "its own folder, emptied")
        e = self.doc("test", "--all", rc=1, BROMIGOS_BACKUPS_FREE_BYTES="1000")
        self.assertEqual((e["state"], e["error"]["code"]), ("failed", "test-failed"))
        self.assertIn("not enough room for the test restore", e["error"]["message"])
        self.assertEqual(self.state()["test"]["phase"], "failed")
        self.assertEqual(self.state()["test_ok"]["phase"], "ok", "the last one that passed stays on record")

    def test_a_corrupted_backup_fails_the_test_and_the_health_line_says_so(self):
        self.assertEqual(self.lab("test").returncode, 0)
        passed = self.state()["test_ok"]
        # bit rot at the destination: a byte flipped in every 32 of every pack. This server's own cache
        # still has the lists of files, so only a test that reads the destination alone sees all of it
        for pack in sorted((self.root / "mnt/backup/data").rglob("*")):
            if pack.is_file():
                raw = bytearray(pack.read_bytes())
                for i in range(7, len(raw), 32):
                    raw[i] ^= 0xFF
                pack.chmod(0o600)
                pack.write_bytes(raw)
        r = self.lab("test", "--all")
        self.assertEqual(r.returncode, 1)
        self.assertIn("The test restore failed:", r.stderr)
        self.assertEqual(self.scratch(), [], "cleaned up after a failure too")
        st = self.state()
        self.assertEqual((st["test"]["phase"], st["test_ok"]), ("failed", passed))
        self.assertTrue(st["test"]["reason"])
        d = self.doc(rc=1)
        self.assertEqual((d["ok"], d["health"]["state"]), (False, "attention"))
        self.assertIn("The last test restore failed (just now):", d["health"]["verdict"])
        self.assertEqual([(p["id"], p["subject"], p["severity"]) for p in d["health"]["problems"]], [("test-failed", "server-test", "needs_you")])
        self.assertEqual((d["last_test"]["phase"], d["last_test_passed"]["ts"]), ("failed", passed["ts"]))
        out = self.lab().stdout
        self.assertRegex(out, r"Test restore  failed just now \(\d{4}-\d\d-\d\d \d\d:\d\d\): ")
        self.assertIn("the last one that passed: just now", out)
        self.assertIn("The last test restore failed", self.server("status").stdout, "`bromigos server` says the same")
        # and a restore from it is never passed off as whole
        r = self.lab("restore")
        self.assertEqual(r.returncode, 1)
        for name in self.restored():
            self.assertTrue(name.endswith((".partial", "-incomplete")), name)
        # nor in place: files that didn't come back leave a mix, and the health line keeps saying so
        (self.root / "home/ada/docs/note.txt").unlink()
        d = self.doc("restore", "/home/ada/docs/note.txt", "--in-place", "--apply", "--yes", "--without-snapshot", rc=1)
        self.assertEqual((d["ok"], d["state"], [s["path"] for s in d["skipped"]]), (False, "incomplete", ["/home/ada/docs/note.txt"]))
        self.assertIn("restore-interrupted", [p["id"] for p in self.doc(rc=1)["health"]["problems"]])

    def test_a_test_restore_stopped_part_way_counts_neither_way(self):
        (self.fake / "hang").write_text("/nothing")
        p = self.spawn("test")
        d = self.doc()
        self.assertEqual((d["running"]["kind"], d["running"]["step"]), ("test", "restore"))
        self.assertIn("Running now   a test restore: Restoring to a scratch folder", self.lab().stdout)
        p.send_signal(signal.SIGTERM)
        _, err = p.communicate(timeout=60)
        self.assertEqual(p.returncode, 130)
        self.assertIn("it doesn't count either way", err)
        self.assertNotIn("test", self.state())
        self.assertEqual(self.scratch(), [])
        self.assertEqual(self.doc()["health"]["state"], "ok")


def mounts_work():
    """A mount of our own in a user and mount namespace: a real other filesystem for the test,
    seen by nothing outside it, gone when it ends. Not where user namespaces are off (CI's
    containers); the stand-in restic's $FAKE/mounts covers those."""
    if not shutil.which("unshare"):
        return False
    with tempfile.TemporaryDirectory() as d:
        return subprocess.run(["unshare", "-rm", "mount", "-t", "tmpfs", "standin", d], capture_output=True).returncode == 0


APP = "srv/apps/photos/library/beach.jpg"


def rows(db):
    with contextlib.closing(sqlite3.connect(db)) as c:
        return c.execute("SELECT count(*) FROM ciphers").fetchone()[0]


@unittest.skipUnless(RESTIC, "restic isn't installed")
class AppData(Rig):
    """What every backup must hold: the apps' data, on a server with data disks a mount of its
    own at /srv/apps. Named by itself in the backup, looked for in it after the run, by the
    weekly check and by the test restore."""
    backed_up = False

    def setUp(self):
        super().setUp()
        self.put(APP, "sand\n")
        (self.fake / "mounts").write_text(f"{self.root / 'srv/apps'}\n")

    def paths(self, *paths, exclude=None):
        self.put("etc/bromigos/server.toml", '[backup]\nto = "/mnt/backup"\npaths = [' + ", ".join(f'"{p}"' for p in paths) + "]\n"
                 + (f"exclude = {json.dumps(exclude)}\n" if exclude is not None else ""))

    def holds(self, rel, snap=None):
        env = dict(self.env(), RESTIC_REPOSITORY=str(self.root / "mnt/backup"), RESTIC_PASSWORD_FILE=str(self.root / "etc/bromigos/server/backup.key"))
        r = subprocess.run([RESTIC, "ls", "--json", snap or "latest", str(self.root / rel)], env=env, capture_output=True, text=True)
        return any(json.loads(line).get("path") == str(self.root / rel) for line in r.stdout.splitlines() if line.startswith("{"))

    def test_the_apps_data_is_backed_up_whatever_the_paths_say(self):
        self.paths("/etc", "/home")                                      # no /srv
        self.backup()
        self.assertTrue(self.holds(APP), "the apps' data is named by itself")
        self.assertTrue(self.holds("home/ada/docs/note.txt"))
        self.assertEqual(self.doc()["health"]["state"], "ok")

    @unittest.skipUnless(mounts_work(), "no mount of our own here (user namespaces are off)")
    def test_a_real_mount_at_srv_apps(self):
        # a filesystem of its own at srv/apps, as the data disks' apps subvolume is: the server's
        # backup, run in that namespace, must hold what is on it
        self.paths("/etc", "/home")
        shutil.rmtree(self.root / "srv/apps")
        (self.root / "srv/apps").mkdir()
        apps = self.root / "srv/apps"
        r = subprocess.run(["unshare", "-rm", "sh", "-ec", 'mount -t tmpfs standin "$1"; mkdir -p "$1/photos/library"; '
                            'echo sand > "$1/photos/library/beach.jpg"; shift; exec "$@"', "sh", str(apps),
                            sys.executable, "-I", str(SERVER), "backup", "run"], env=self.env(), capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(list(apps.iterdir()), [], "the mount was the namespace's own")
        self.assertTrue(self.holds(APP))

    def test_the_data_disks_away_nothing_is_backed_up(self):
        self.put("etc/fstab", "/dev/sda1 / btrfs\nUUID=2222 /srv/apps btrfs subvol=/apps,nofail 0 0\n")
        r = self.server("backup", "run")
        self.assertEqual(r.returncode, 1)
        self.assertIn("the data disks aren't mounted, so /srv/apps (the apps' data) can't be read. Nothing was backed up", r.stderr)
        self.assertFalse((self.root / "mnt/backup/config").exists(), "restic never ran")
        d = self.doc(rc=1)
        self.assertEqual((d["health"]["state"], d["last_backup"]["phase"]), ("attention", "failed"))
        self.assertIn("the data disks aren't mounted", d["health"]["verdict"])

    def test_a_backup_that_left_the_apps_out_fails_loudly(self):
        self.paths("/etc", "/home", "/srv", exclude=["apps"])          # an exclude of someone's
        r = self.server("backup", "run")
        self.assertEqual(r.returncode, 1, r.stdout)
        self.assertIn("the backup failed: the backup left out /srv/apps (the apps' data)", r.stderr)
        st = self.state()
        self.assertEqual((st["run"]["phase"], st["run"]["missing"]), ("failed", ["/srv/apps"]))
        self.assertNotIn("run_ok", st)
        d = self.doc(rc=1)
        (p,) = d["health"]["problems"]
        self.assertEqual((p["id"], p["severity"]), ("failed", "needs_you"))
        self.assertIn(f"The backup left out /srv/apps (the apps' data). The rest is in that backup ({st['run']['snapshot']}), "
                      "but it doesn't count. No backup has worked yet.", p["detail"])

    def test_the_check_and_the_test_restore_fail_when_the_newest_backup_lacks_the_apps(self):
        shutil.rmtree(self.root / "srv/apps")                            # not there when this backup ran
        snap = self.backup()
        self.assertEqual(self.server("backup", "check").returncode, 0)
        self.assertEqual(self.lab("test").returncode, 0)
        self.put(APP, "sand\n")                                          # there now: the backup must hold it
        r = self.server("backup", "check")
        self.assertEqual(r.returncode, 1)
        self.assertIn(f"the newest backup ({snap}) doesn't hold /srv/apps (the apps' data), which is on this server", r.stderr)
        e = self.doc("test", rc=1)
        self.assertIn(f"the newest backup ({snap}) doesn't hold /srv/apps (the apps' data)", e["error"]["message"])
        d = self.doc(rc=1)
        self.assertEqual(sorted(p["id"] for p in d["health"]["problems"]), ["check-failed", "test-failed"])
        # the next backup holds it, and both pass again
        self.backup()
        self.assertEqual(self.server("backup", "check").returncode, 0)
        self.assertEqual(self.lab("test").returncode, 0)
        self.assertEqual(self.doc()["health"]["state"], "ok")

    def test_a_folder_destination_inside_what_is_backed_up_is_not_backed_up_into_itself(self):
        self.put("etc/bromigos/server.toml", '[backup]\nto = "/srv/backups/restic"\npaths = ["/etc", "/srv"]\n')
        self.backup()
        self.backup()
        env = dict(self.env(), RESTIC_REPOSITORY=str(self.root / "srv/backups/restic"),
                   RESTIC_PASSWORD_FILE=str(self.root / "etc/bromigos/server/backup.key"))
        r = subprocess.run([RESTIC, "ls", "latest"], env=env, capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertNotIn("srv/backups/restic/", r.stdout)
        self.assertIn(str(self.root / APP), r.stdout)


@unittest.skipUnless(RESTIC, "restic isn't installed")
class Databases(Rig):
    """The apps' databases, copied whole while the app runs (copy_databases) and held by the backup."""
    backed_up = False

    def setUp(self):
        super().setUp()
        self.db = self.root / "srv/apps/passwords/db.sqlite3"
        self.db.parent.mkdir(parents=True)
        self.put("etc/bromigos/backup-databases.d/passwords.toml",
                 'what = "passwords (Vaultwarden)"\nsqlite = ["/srv/apps/passwords/db.sqlite3", "/var/lib/vaultwarden/db.sqlite3"]\n')
        # Vaultwarden's way: write-ahead log, open the whole time; what's in the log isn't in db.sqlite3 yet
        self.app = sqlite3.connect(self.db)
        self.app.execute("PRAGMA journal_mode=WAL")
        self.app.execute("PRAGMA wal_autocheckpoint=0")
        self.app.execute("CREATE TABLE ciphers (name TEXT)")
        self.app.executemany("INSERT INTO ciphers VALUES (?)", [(f"login {i}",) for i in range(500)])
        self.app.commit()

    def tearDown(self):
        self.app.close()
        super().tearDown()

    def test_a_database_in_use_is_copied_whole_and_backed_up(self):
        snap = self.backup()
        copy = self.root / "var/lib/bromigos/backup-databases/passwords/db.sqlite3"
        self.assertEqual(copy.stat().st_mode & 0o777, 0o600)
        self.assertEqual(rows(copy), 500)
        st = self.state()
        self.assertEqual(st["run"]["databases"], [{"name": "passwords", "what": "passwords (Vaultwarden)",
                                                   "path": "/srv/apps/passwords/db.sqlite3", "ok": True, "reason": ""}])
        # the copy comes back from the backup, and opens with every row
        out = Path(self.tmp.name) / "back"
        d = self.doc("restore", snap, "/var/lib/bromigos/backup-databases/passwords/db.sqlite3", "--to", str(out))
        self.assertTrue(d["ok"])
        back = out / "var/lib/bromigos/backup-databases/passwords/db.sqlite3"
        self.assertEqual(rows(back), 500)
        self.assertEqual(self.doc()["health"]["state"], "ok")

    def test_a_database_that_cannot_be_copied_is_said_loudly(self):
        self.put("etc/bromigos/backup-databases.d/documents.toml",
                 'what = "documents (Paperless-ngx)"\nsqlite = ["/srv/apps/documents/data/db.sqlite3"]\n')
        self.put("srv/apps/documents/data/db.sqlite3", "this is not a database at all, it was cut short\n" * 20)
        r = self.server("backup", "run")
        self.assertEqual(r.returncode, 1)
        self.assertIn("bromigos-server: backed up (", r.stdout, "the rest is backed up")
        self.assertIn("documents (Paperless-ngx): /srv/apps/documents/data/db.sqlite3 couldn't be copied:", r.stderr)
        d = self.doc(rc=1)
        self.assertEqual([p["id"] for p in d["health"]["problems"]], ["database-copy-failed"])
        self.assertEqual(d["health"]["verdict"], "Backed up just now. But the database of documents (Paperless-ngx) wasn't "
                         "copied whole, so it may not open from this backup. Last test restore: none yet.")
        self.assertTrue((self.root / "var/lib/bromigos/backup-databases/passwords/db.sqlite3").exists(), "the others are copied")
        self.assertFalse((self.root / "var/lib/bromigos/backup-databases/documents/db.sqlite3").exists())


@unittest.skipUnless(RESTIC, "restic isn't installed")
class TheLabsOwnBackup(unittest.TestCase):
    """The backup `bromigos lab provision --local` sets up on a machine that isn't a Server
    (bromigos-lab-backup.service): its own restic command, run from the unit it writes, with
    /srv/apps on a filesystem of its own."""

    def setUp(self):
        sys.path.insert(0, str(REPO / "homelab/tests"))
        from bromigos_homelab import localprovision as L, provcatalog as PC, secretstore as S
        from provfake import FakeMachine
        self.tmp = tempfile.TemporaryDirectory()
        t = Path(self.tmp.name)
        self.root, self.fake, self.bin = t / "root", t / "fake", t / "bin"
        for d in (self.root, self.fake, self.bin):
            d.mkdir()
        (self.bin / "restic").write_text(STUBS["restic"])
        (self.bin / "restic").chmod(0o755)
        m = FakeMachine(str(self.root))
        with mock.patch.object(PC, "SHARE", "/nonexistent"):
            PC._cache.clear()
            plan = L.build_plan(["backups"], hw={"cpu": 4, "ram_gb": 8, "disk_gb": 100, "gpu": False, "gpu_vram_gb": 0, "gpu_name": ""})
            host = L.Host(plan, root=str(self.root), run_=m, online=lambda: True, store=S.LocalStore(str(self.root), m, "box"),
                          emit=lambda line: None, hostname="box", tz="UTC")
            L.step_backups(host, PC.by_id()["backups"])
        PC._cache.clear()
        unit = (self.root / "etc/systemd/system/bromigos-lab-backup.service").read_text()
        self.unit = unit
        self.restic_args = next(line for line in unit.splitlines() if line.startswith("ExecStart=")).split()[1:]
        for rel, text in {"etc/hostname": "box\n", APP: "sand\n", "srv/www/index.html": "hello\n",
                          "srv/data/apps/photos/library/beach.jpg": "sand\n"}.items():
            (self.root / rel).parent.mkdir(parents=True, exist_ok=True)
            (self.root / rel).write_text(text)
        (t / "key").write_text("a test key\n")
        self.env = {k: v for k, v in os.environ.items() if k not in ("WAYLAND_DISPLAY", "DISPLAY", "PYTHONPATH")}
        self.env.update(PATH=f"{self.bin}:/usr/bin:/bin", FAKE=str(self.fake), REAL_RESTIC=RESTIC, HOME=str(t),
                        RESTIC_REPOSITORY=str(t / "repo"), RESTIC_PASSWORD_FILE=str(t / "key"), RESTIC_CACHE_DIR=str(t / "cache"),
                        BROMIGOS_SERVER_ROOT=str(self.root), TZ="UTC")
        subprocess.run([RESTIC, "init"], env=self.env, capture_output=True, check=True)

    def tearDown(self):
        self.tmp.cleanup()

    def command(self):
        """The unit's ExecStart, its paths under the stand-in root."""
        return ["restic"] + [str(self.root / a.lstrip("/")) if a.startswith("/") else a for a in self.restic_args]

    def holds(self, rel):
        r = subprocess.run([RESTIC, "ls", "--json", "latest", str(self.root / rel)], env=self.env, capture_output=True, text=True)
        return any(json.loads(line).get("path") == str(self.root / rel) for line in r.stdout.splitlines() if line.startswith("{"))

    def lab(self, *args):
        return subprocess.run([sys.executable, str(LAB), "backups", *args], env=self.env, capture_output=True, text=True,
                              stdin=subprocess.DEVNULL)

    def check_it_holds_the_apps(self):
        self.assertTrue(self.holds(APP), "the apps' data, on a filesystem of its own, is in the backup")
        self.assertTrue(self.holds("srv/www/index.html"))
        self.assertFalse(self.holds("srv/data/apps/photos/library/beach.jpg"), "the data disks aren't read twice")
        r = self.lab("holds")
        self.assertEqual(r.returncode, 0, r.stderr)

    def test_the_apps_on_a_filesystem_of_their_own(self):
        (self.fake / "mounts").write_text(f"{self.root / 'srv/apps'}\n{self.root / 'srv/data'}\n")
        r = subprocess.run(self.command(), env=self.env, capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.check_it_holds_the_apps()

    @unittest.skipUnless(mounts_work(), "no mount of our own here (user namespaces are off)")
    def test_a_real_mount_at_srv_apps(self):
        apps, data = self.root / "srv/apps", self.root / "srv/data"
        r = subprocess.run(["unshare", "-rm", "sh", "-ec", 'mount -t tmpfs apps "$1"; mount -t tmpfs data "$2"; '
                            'mkdir -p "$1/photos/library" "$2/apps"; echo sand > "$1/photos/library/beach.jpg"; '
                            'echo sand > "$2/apps/beach.jpg"; shift 2; exec "$@"', "sh", str(apps), str(data), *self.command()],
                           env=self.env, capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue(self.holds(APP))
        self.assertFalse(self.holds("srv/data/apps/beach.jpg"))

    def test_the_unit_fails_when_the_backup_lacks_the_apps(self):
        self.assertIn("ExecStartPost=/usr/lib/bromigos/bin/bromigos-lab backups holds\n", self.unit)
        self.assertIn("ExecStartPre=-/usr/lib/bromigos/bin/bromigos-lab backups copy-databases\n", self.unit)
        self.assertLess(self.unit.index("backups holds"), self.unit.index("restic forget"), "nothing is let go first")
        subprocess.run([RESTIC, "backup", str(self.root / "etc")], env=self.env, capture_output=True, check=True)
        r = self.lab("holds")
        self.assertEqual(r.returncode, 1)
        self.assertIn("The newest backup doesn't hold /srv/apps (the apps' data), which is on this computer.", r.stderr)

    def test_the_databases_are_copied_first_and_a_copy_that_failed_fails_the_unit(self):
        db = self.root / "srv/apps/documents/data/db.sqlite3"
        db.parent.mkdir(parents=True)
        c = sqlite3.connect(db)
        c.execute("CREATE TABLE documents (title TEXT)")
        c.execute("INSERT INTO documents VALUES ('tax 2025')")
        c.commit()
        c.close()
        hooks = self.root / "etc/bromigos/backup-databases.d"
        hooks.mkdir(parents=True)
        (hooks / "documents.toml").write_text('what = "documents (Paperless-ngx)"\nsqlite = ["/srv/apps/documents/data/db.sqlite3"]\n')
        r = self.lab("copy-databases")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stdout, "documents (Paperless-ngx): copied\n")
        self.assertEqual(subprocess.run(self.command(), env=self.env, capture_output=True).returncode, 0)
        self.assertTrue(self.holds("var/lib/bromigos/backup-databases/documents/db.sqlite3"))
        self.assertEqual(self.lab("holds").returncode, 0)
        db.write_text("not a database\n" * 50)
        self.assertEqual(self.lab("copy-databases").returncode, 1)
        self.assertEqual(subprocess.run(self.command(), env=self.env, capture_output=True).returncode, 0)
        r = self.lab("holds")
        self.assertEqual(r.returncode, 1)
        self.assertIn("Documents (Paperless-ngx): its database wasn't copied whole for the backup:", r.stderr)


class Command(Rig):
    backed_up = False

    def test_help_and_the_command_line(self):
        r = self.lab("--help")
        self.assertEqual(r.returncode, 0)
        for word in ("restore [ID] [PATH…]", "--in-place --apply", "test [--all]", "Every one takes --json"):
            self.assertIn(word, r.stdout)
        self.assertEqual(self.lab("frobnicate").returncode, 2)
        lab = subprocess.run([sys.executable, str(LAB), "--help"], env=self.env(), capture_output=True, text=True).stdout
        self.assertIn("lab backups restore [ID] [PATH…] --in-place [--apply]", lab)
        self.assertNotIn("deploy|restart|logs|backups", lab)


if __name__ == "__main__":
    unittest.main()
