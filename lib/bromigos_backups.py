"""bromigOS Server's backups, for the person who needs their files back (docs/server.md, "Backups").

  bromigos lab backups [status] [--json]     the health line, and a short status
  bromigos lab backups list [--json]         every backup: when, how big, what's in it
  bromigos lab backups show [ID] [PATH]      what's inside one, a folder at a time
  bromigos lab backups restore [ID] [PATH…]  files back, into a new folder (nothing is replaced)
      --to DIR                               that folder (it must be new or empty)
      --in-place                             show what putting them back where they were would
                                             replace; with --apply, do it (a snapshot first)
  bromigos lab backups test [--all]          a test restore: a sample (or everything) restored to
                                             a scratch folder, read back, then removed
  bromigos lab backups run | check [--data]  = bromigos server backup run | check

The nightly backup itself is bromigos-server's (`backup run`, `backup check`): restic, to
[backup] to in /etc/bromigos/server.toml. This module reads what it leaves, and restores from it.

One verdict. health() says whether the backups are healthy, in words and as problems. The
status here, the Backups line of `bromigos server`, and the backup.restic check of `bromigos
alerts` all call it, so they can't disagree.

Files (BROMIGOS_SERVER_ROOT puts them under a stand-in root, for the tests):
  /etc/bromigos/server.toml               [backup] to, env_file
  /etc/bromigos/server/backup.key         the backup's key (root only); never made here
  /var/lib/bromigos/server/backup.json    the last backup, check and test restore; the count
  /var/lib/bromigos/server/restore.json   the restore running now, or the last one
  /var/lib/bromigos/server/restore-test.json   the same for the test restore
  /var/lib/bromigos/server/restore-test/  the test restore's scratch folder (emptied after)
  /srv/restore/                           where restores go unless --to says otherwise

Exit codes: 0 done (status: healthy, off, or waiting for the first backup); 1 it failed, or the
backups need you; 2 the command line; 3 refused (it would replace files, it needs a yes, this
isn't a Server); 4 not enough free space; 130 stopped part-way.
"""

import argparse
import datetime
import fcntl
import hashlib
import json
import os
import random
import re
import shutil
import signal
import stat
import subprocess
import sys
import tempfile
import time
import tomllib

SCHEMA = 1
ROOT = os.environ.get("BROMIGOS_SERVER_ROOT", "/")
CONFIG = "/etc/bromigos/server.toml"
ENV_FILE = "/etc/bromigos/server/backup.env"
KEY = "/etc/bromigos/server/backup.key"
STATE = "/var/lib/bromigos/server/backup.json"
JOURNAL = "/var/lib/bromigos/server/restore.json"
TEST_JOURNAL = "/var/lib/bromigos/server/restore-test.json"
SCRATCH = "/var/lib/bromigos/server/restore-test"
RESTORE_HOME = "/srv/restore"
SERVER = "/usr/lib/bromigos/server/bromigos-server"
MARKER = ".bromigos-restore-incomplete"
TAG = "bromigos-server"                      # the nightly backup's tag (bromigos-server backup run)
TIMERS = {"backup": "bromigos-server-backup.timer", "check": "bromigos-server-backup-check.timer",
          "test": "bromigos-server-backup-test.timer"}

HOUR, DAY = 3600, 86400
STALE = 36 * HOUR            # the nightly backup, a day and a half late
TEST_STALE = 45 * DAY        # the monthly test restore, half a month late
SAMPLE_FILES = 100           # a test restore's sample
SAMPLE_BYTES = 1 << 30
SAMPLE_FILE_BYTES = 256 << 20
MARGIN = 64 << 20            # free space left over after a restore
SHOWN = 30                   # how many files the in-place list prints before it counts the rest


class Problem(Exception):
    """Something a person can act on: said in plain words, with a code for --json."""

    def __init__(self, code, message, exit=1, **more):
        super().__init__(message)
        self.code, self.message, self.exit, self.more = code, message, exit, more


class Stopped(Exception):
    """Ctrl+C, a closed terminal, or systemd stopping the job."""


def at(path):
    return os.path.join(ROOT, path.lstrip("/"))


def sysp(path):
    """A path as the server knows it: the stand-in root taken off."""
    if ROOT != "/" and (path == ROOT.rstrip("/") or path.startswith(ROOT.rstrip("/") + "/")):
        return path[len(ROOT.rstrip("/")):] or "/"
    return path


# ------------------------------------------------------------------ words

def size(n):
    try:
        n = float(n)
    except (TypeError, ValueError):
        return "an unknown size"
    for unit in ("bytes", "KB", "MB", "GB", "TB"):
        if n < 1000 or unit == "TB":
            return f"{n:.0f} {unit}" if unit in ("bytes", "KB") or n >= 100 else f"{n:.1f} {unit}"
        n /= 1000


def count(n, one, many=None):
    return (f"{n:,}" if isinstance(n, (int, float)) else str(n)) + f" {one if n == 1 else many or one + 's'}"


def span(seconds):
    """6 hours, 12 days: how long, rounded down the way people say it."""
    s = max(0, int(seconds))
    if s < 90:
        return "a minute"
    if s < HOUR:
        return f"{s // 60} minutes"
    if s < DAY:
        return count(s // HOUR, "hour")
    return count(s // DAY, "day")


def ago(ts, now):
    if ts is None:
        return "at a time that wasn't recorded"
    return "just now" if now - ts < 60 else span(now - ts) + " ago"


def when(ts):
    if ts is None:
        return "an unknown time"
    return datetime.datetime.fromtimestamp(ts).astimezone().strftime("%Y-%m-%d %H:%M")


def iso(ts=None):
    t = datetime.datetime.fromtimestamp(time.time() if ts is None else ts, datetime.timezone.utc)
    return t.astimezone().isoformat(timespec="seconds")


def stamp(text):
    """restic's time ("2026-11-09T21:02:22.388872643-08:00") as Unix seconds; None when it isn't one."""
    try:
        return datetime.datetime.fromisoformat(re.sub(r"(\.\d{6})\d+", r"\1", text or "").replace("Z", "+00:00")).timestamp()
    except (TypeError, ValueError):
        return None


def where(to):
    """The destination without a user or password someone put in the address: for showing."""
    return re.sub(r"//[^/@]*@", "//", to) if to else ""


def same_place(to):
    """The destination without a password, the user kept: what backup.json remembers a backup
    went to, to tell the same place from another account's."""
    return re.sub(r"//([^/:@]*):[^/@]*@", r"//\1@", to) if to else ""


def lower_first(text):
    """"The destination…" inside a sentence; an acronym (S3, SFTP) keeps its capital."""
    return text if len(text) > 1 and text[1].isupper() else text[:1].lower() + text[1:]


def upper_first(text):
    text = str(text)
    return text[:1].upper() + text[1:]


def sentence(text):
    """A reason as the end of a sentence: one line, no full stop of its own."""
    text = re.sub(r"\b(Fatal|Error): ", "", " ".join(str(text or "").split()))       # restic's own prefixes
    return lower_first(text.rstrip(". "))[:300]


# ------------------------------------------------------------------ the one verdict

def repository(to):
    """restic's repository for [backup] to. A folder is a path on the server, so the tests'
    stand-in root holds it like every other file."""
    return at(to) if to.startswith("/") else "local:" + at(to[6:]) if to.startswith("local:") else to


def destination(to, had_backup=False, real=None):
    """What kind of place the backups go to, and for a folder whether it's there now:
    {"kind", "path", "present"}. present is True (restic's repository is in it), False (a
    backup used to be there, and the folder is missing or empty now: a drive that isn't
    plugged in), or None (can't tell from here: S3, SFTP, a folder no backup has gone to yet,
    one that can't be read)."""
    real = real or at
    if not to:
        return {"kind": "none", "path": "", "present": None}
    if not (to.startswith("/") or to.startswith("local:")):
        return {"kind": to.split(":", 1)[0], "path": "", "present": None}
    path = to.removeprefix("local:")
    p, present = real(path), None
    try:
        if os.path.isfile(os.path.join(p, "config")):
            present = True
        elif had_backup and (not os.path.isdir(p) or not os.listdir(p)):
            present = False
    except OSError:
        present = None
    return {"kind": "folder", "path": path, "present": present}


def had_backup(st):
    """Has a backup ever worked, as far as backup.json says?"""
    st = st if isinstance(st, dict) else {}
    run = st.get("run") if isinstance(st.get("run"), dict) else {}
    return bool(isinstance(st.get("run_ok"), dict) and st["run_ok"]) or run.get("phase") in ("ok", "partial")


def _last(rec, now, timed=False):
    """A record of backup.json with its age (None when it has no time), or None. timed: only
    a record that says when."""
    if not isinstance(rec, dict) or not rec:
        return None
    try:
        ts = float(rec["ts"])
    except (KeyError, TypeError, ValueError):
        return None if timed else dict(rec, ts=None, age_s=None)
    return dict(rec, ts=ts, age_s=max(0, int(now - ts)))


def _problem(pid, subject, severity, title, detail, commands, touches, note=""):
    return {"id": pid, "subject": subject, "severity": severity, "title": title, "detail": detail,
            "commands": commands, "touches": touches, "note": note}


READ_FIRST = "Read why it failed first: a destination that can't be reached and a full disk are common."


def health(to, st, now, dest=None, restore=None):
    """Are this server's backups healthy? Pure: `to` is [backup] to, `st` is backup.json,
    `now` is Unix seconds, `dest` is destination()'s answer and `restore` is job_record()'s
    (its "unfinished": a restore in place that stopped part-way).

    Returns {"state": "ok" | "attention" | "waiting" | "off", "verdict": one or two plain
    sentences, "problems": [...], and what it was judged from: "backup", "success", "check",
    "read_back", "test", "test_passed", "snapshots"}. Each problem has an id, a severity
    (bromigos alerts' words), a title, a detail and the commands that look into it."""
    st = st if isinstance(st, dict) else {}
    dest = dest or destination(to)
    run = st.get("run") if isinstance(st.get("run"), dict) else {}
    phase = run.get("phase") if run.get("phase") in ("ok", "partial", "failed") else None
    backup = _last(run, now) if phase else None
    success = _last(st.get("run_ok"), now, True) or (backup if phase in ("ok", "partial") and backup["ts"] else None)
    chk = st.get("check") if isinstance(st.get("check"), dict) else {}
    check = _last(chk, now) if chk.get("phase") in ("ok", "failed") else None
    check_ok = _last(st.get("check_ok"), now, True) or (check if check and check.get("phase") == "ok" and check["ts"] else None)
    read_back = _last(st.get("read_back_ok"), now, True) or (check if check and check.get("phase") == "ok" and check.get("data")
                                                              and check["ts"] else None)
    tst = st.get("test") if isinstance(st.get("test"), dict) else {}
    test = _last(tst, now) if tst.get("phase") in ("ok", "failed") else None
    test_ok = _last(st.get("test_ok"), now, True) or (test if test and test.get("phase") == "ok" and test["ts"] else None)
    inv = st.get("snapshots") if isinstance(st.get("snapshots"), dict) else None
    doc = {"state": "off", "verdict": "", "problems": [], "backup": backup, "success": success, "check": check,
           "check_passed": check_ok, "read_back": read_back, "test": test, "test_passed": test_ok,
           "snapshots": inv if inv and isinstance(inv.get("count"), int) else None}
    problems = doc["problems"]
    # a restore in place that didn't finish: the files there are a mix, whatever the backups do
    left = restore.get("unfinished") if isinstance(restore, dict) else None
    mix = None
    if isinstance(left, dict):
        paths = ", ".join(left.get("paths") or []) or "everything"
        again = "bromigos lab backups restore " + " ".join([str(left.get("snapshot", "")), *(left.get("paths") or [])]).strip() \
            + " --in-place --apply"
        mix = _problem(
            "restore-interrupted", "server-restore", "needs_you", "A restore stopped part-way",
            f"Putting {paths} back from the backup of {left.get('snapshot_at', '?')} stopped on "
            f"{left.get('started', '?')}, before it finished. Some files there are from the backup and some "
            f"aren't. Running it again finishes it: {again}",
            ["bromigos lab backups", again], [f"replaces files ({paths}) with the backup's"])
    mixed = " A restore stopped part-way: some files are from the backup and some aren't." if mix else ""
    if not to:
        doc["verdict"] = ("Backups are off: nothing on this server is backed up. To turn them on, say where "
                          "they go: [backup] to in /etc/bromigos/server.toml.") + mixed
        if mix:
            problems.append(mix)
            doc["state"] = "attention"
        return doc
    look = ["bromigos lab backups", "journalctl -u bromigos-server-backup.service -n 50 --no-pager"]
    gone = dest.get("present") is False
    stale = bool(success and success["age_s"] > STALE)
    why = f"the drive at {dest['path']} is not connected" if gone else sentence(run.get("reason")) if phase == "failed" else ""
    # the last backup
    if phase == "failed":
        before = (f"The last backup that worked was {ago(success['ts'], now)}." if success else "No backup has worked yet.")
        problems.append(_problem(
            "failed", "server", "needs_you", "The last backup failed",
            f"{upper_first(run.get('reason') or 'restic failed')[:300]}. Nothing was copied this time. {before}",
            look + ["sudo bromigos server backup run"], ["runs the backup again"], READ_FIRST))
    elif stale:
        problems.append(_problem(
            "stale", "server", "needs_you", f"No backup for {success['age_s'] // HOUR} hours",
            f"The last backup was on {success.get('at', '?')}. The nightly one hasn't run since: "
            + (f"{why}." if why else "the server may have been off, or the timer stopped."),
            look + ["sudo bromigos server backup run"], ["runs the backup again"], READ_FIRST))
    elif phase == "partial":
        problems.append(_problem(
            "partial", "server", "info", "The last backup left some files out",
            f"{upper_first(run.get('reason') or 'some files could not be read')[:300]}. The rest was backed up.",
            look, ["nothing (it only looks)"]))
    # the weekly check
    check_failed = bool(check and check.get("phase") == "failed")
    if check_failed:
        problems.append(_problem(
            "check-failed", "server-check", "needs_you", "The backup check failed",
            f"{upper_first(check.get('reason') or 'restic check failed')[:300]}. What's in the backup may not read "
            "back: look at it before you need it.",
            ["bromigos lab backups", "sudo bromigos server backup check"], ["nothing (it reads the backup back)"]))
    # the monthly test restore
    test_failed, test_late = bool(test and test.get("phase") == "failed"), None
    if test_failed:
        problems.append(_problem(
            "test-failed", "server-test", "needs_you", "The last test restore failed",
            f"{upper_first(test.get('reason') or 'the files did not come back')[:300].rstrip('.')}. A backup that can't be restored "
            "isn't a backup: look at it before you need it.",
            ["bromigos lab backups", "journalctl -u bromigos-server-backup-test.service -n 50 --no-pager",
             "sudo bromigos lab backups test"], ["nothing on the server (it restores to a scratch folder, then removes it)"]))
    else:
        since = test_ok["ts"] if test_ok else st.get("first_ok_ts")
        if isinstance(since, (int, float)) and not isinstance(since, bool) and now - since > TEST_STALE:
            test_late = now - since
            problems.append(_problem(
                "test-stale", "server-test", "needs_you", f"No test restore has passed for {int(test_late) // DAY} days",
                ("The last one that passed was on " + str(test_ok.get("at", "?")) + "." if test_ok else
                 "None has run since the first backup.") + " The monthly one hasn't run: the server may have "
                "been off, or its timer stopped. Until one passes, nobody knows the backup can be restored.",
                ["bromigos lab backups", "systemctl list-timers bromigos-server-backup-test.timer",
                 "sudo bromigos lab backups test"], ["nothing on the server (it restores to a scratch folder, then removes it)"]))
    if mix:
        problems.append(mix)
    # the verdict: a sentence or two a person can act on, and never quieter than the problems
    last = success or backup
    doc["state"] = "ok"
    if not last:
        doc["state"] = "waiting"
        line = "No backup yet: the first one runs tonight."
    elif phase == "failed" and not success:
        line = f"No backup yet: the first one failed {ago(backup['ts'], now)}: {why or 'restic failed'}."
    elif phase == "failed" and not stale:
        line = f"The last backup failed: {why or 'restic failed'}. The one before it worked, {ago(success['ts'], now)}."
    elif stale:
        line = f"No backup in {span(success['age_s'])}: " + (why or "the nightly backup has not run (the server may "
                                                             "have been off, or its timer stopped)") + "."
    else:
        line = f"Backed up {ago(last['ts'], now)}."
        if phase == "partial":
            line += " Some files could not be read and were left out."
    if check_failed:
        line += (" But the" if line.startswith("Backed up") else " The") + f" last check of the backup failed ({ago(check['ts'], now)}): " \
            + (sentence(check.get("reason")) or "restic check failed") + "."
    if test_failed:
        line += f" The last test restore failed ({ago(test['ts'], now)}): {sentence(test.get('reason')) or 'the files did not come back'}."
    elif test_late is not None:
        line += f" No test restore has passed in {span(test_late)}."
    elif test_ok:
        line += f" Last test restore: {ago(test_ok['ts'], now)}, passed."
    elif last:
        line += " Last test restore: none yet."
    doc["verdict"] = line + mixed
    if any(p["severity"] != "info" for p in problems):
        doc["state"] = "attention"
    return doc


# ------------------------------------------------------------------ files

def read_json(path, default=None):
    try:
        with open(at(path)) as f:
            doc = json.load(f)
    except (OSError, ValueError):
        return {} if default is None else default
    return doc if isinstance(doc, dict) else {}


def write_json(path, doc, mode=0o644):
    os.makedirs(os.path.dirname(at(path)), mode=0o755, exist_ok=True)
    tmp = f"{at(path)}.tmp.{os.getpid()}"
    with open(tmp, "w") as f:
        json.dump(doc, f, indent=1, sort_keys=True)
        f.write("\n")
    os.chmod(tmp, mode)
    os.replace(tmp, at(path))


def update_state(**records):
    """Merge records into backup.json under a lock: the nightly backup, its check and a test
    restore each keep their own keys, and none loses another's when they overlap. A value of
    None removes the key."""
    os.makedirs(os.path.dirname(at(STATE)), mode=0o755, exist_ok=True)
    with open(at(STATE) + ".lock", "a") as held:
        fcntl.flock(held, fcntl.LOCK_EX)
        st = read_json(STATE)
        for k, v in records.items():
            if v is None:
                st.pop(k, None)
            else:
                st[k] = v
        write_json(STATE, st)
    return st


def settings():
    """[backup] of /etc/bromigos/server.toml, as far as restoring needs it: to and env_file.
    Raises Problem when the file is there and can't be read."""
    try:
        with open(at(CONFIG), "rb") as f:
            c = tomllib.load(f)
    except FileNotFoundError:
        c = {}
    except (OSError, tomllib.TOMLDecodeError) as e:
        raise Problem("settings", f"{CONFIG} can't be read ({e}).")
    b = c.get("backup") if isinstance(c.get("backup"), dict) else {}
    return {"to": str(b.get("to") or ""), "env_file": str(b.get("env_file") or ENV_FILE)}


def is_server():
    return any(os.path.exists(at(p)) for p in (CONFIG, SERVER, STATE))


def stand_in(name):
    """A system command this module runs: the real one on a real server. In a stand-in root
    (the tests) only the stand-in named by BROMIGOS_BACKUPS_<NAME>, never the command of the
    machine the tests run on: its snapper would snapshot that machine, its systemctl would
    answer for that machine's timers. None when there is none."""
    return name if ROOT == "/" else os.environ.get(f"BROMIGOS_BACKUPS_{name.upper()}") or None


def unit_state(unit):
    if not stand_in("systemctl"):
        return "unknown"
    try:
        r = subprocess.run([stand_in("systemctl"), "is-active", unit], capture_output=True, text=True, timeout=15)
    except (OSError, subprocess.TimeoutExpired):
        return "unknown"
    return r.stdout.strip() or "inactive"


def alive(pid):
    try:
        os.kill(int(pid), 0)
    except ProcessLookupError:
        return False
    except (PermissionError, TypeError, ValueError):
        return True
    return True


def boot_id():
    try:
        with open("/proc/sys/kernel/random/boot_id") as f:
            return f.read().strip()
    except OSError:
        return ""


def job_record(path=JOURNAL, doc=None):
    """A job's file (restore.json, restore-test.json): the one running now, or the last one.
    `interrupted` is true when it was stopped part-way, or says running and its process is
    gone (a power cut, a kill). For a restore, `unfinished` is the restore in place that
    stopped part-way or ended with files missing, after it began to write (`writing`), and
    hasn't been run to the end since: the files there are a mix. doc: the file's contents,
    when the caller read it itself."""
    j = read_json(path) if doc is None else doc
    if not j or not isinstance(j, dict):
        return None
    running = j.get("state") == "running" and j.get("boot") == boot_id() and alive(j.get("pid"))
    j["interrupted"] = j.get("state") == "interrupted" or (j.get("state") == "running" and not running)
    j["running"] = running
    if (j["interrupted"] or j.get("state") == "incomplete") and j.get("mode") == "in-place" and j.get("writing"):
        j["unfinished"] = {k: j.get(k) for k in ("snapshot", "snapshot_at", "paths", "started", "snapshots_taken")}
    return j


def status_doc(now=None):
    """Everything `bromigos lab backups` says, as one document (--json)."""
    now = time.time() if now is None else now
    if not is_server():
        return {"schema": SCHEMA, "ok": False, "server": False,
                "error": {"code": "not-a-server", "message": "This computer isn't a bromigOS Server: these are the "
                          "Server's own backups. Your lab's other backup jobs are in `bromigos lab doctor`."}}
    b = settings()
    st = read_json(STATE)
    dest = destination(b["to"], had_backup(st))
    rec, test_run = job_record(), job_record(TEST_JOURNAL)
    running = next(({k: j.get(k) for k in ("kind", "mode", "step", "steps", "percent", "started", "snapshot")}
                    for j in (rec, test_run) if j and j["running"]), None)
    h = health(b["to"], st, now, dest, rec)
    return {"schema": SCHEMA, "ok": h["state"] != "attention", "server": True, "configured": bool(b["to"]),
            "to": where(b["to"]), "destination": dest,
            "timers": {k: unit_state(u) for k, u in TIMERS.items()} if b["to"] else {},
            "health": {"state": h["state"], "verdict": h["verdict"], "problems": h["problems"]},
            "last_backup": h["backup"], "last_success": h["success"], "last_check": h["check"],
            "last_check_passed": h["check_passed"], "last_read_back": h["read_back"],
            "last_test": h["test"], "last_test_passed": h["test_passed"],
            "snapshots": h["snapshots"], "restore": rec, "running": running, "checked_at": iso(now), "now": int(now)}


def print_status(d):
    now, h = d["now"], d["health"]
    print(h["verdict"])
    if not d["configured"]:
        return
    print()

    def row(label, text):
        print(f"  {label:<13} {text}")

    dest = d["destination"]
    row("Destination", d["to"] + (" (not connected)" if dest["present"] is False and dest["kind"] == "folder" else ""))
    lb, ok = d["last_backup"], d["last_success"]
    if not lb:
        row("Last backup", "none yet")
    else:
        words = {"ok": "worked", "partial": "worked, but left some files out", "failed": "failed"}[lb["phase"]]
        more = [f"snapshot {lb['snapshot']}"] if lb.get("snapshot") else []
        if lb.get("files") is not None:
            more.append(count(lb["files"], "file"))
        if lb.get("bytes") is not None:
            more.append(size(lb["bytes"]))
        row("Last backup", f"{words}, {ago(lb['ts'], now)} ({when(lb['ts'])}" + "".join(f", {m}" for m in more) + ")")
        if lb.get("reason"):
            row("", lb["reason"])
        if lb["phase"] == "failed":
            row("Last good one", f"{ago(ok['ts'], now)} ({when(ok['ts'])})" if ok else "none yet")
    lc = d["last_check"]
    row("Last check", "none yet (it runs on Sundays)" if not lc else
        f"{'passed' if lc['phase'] == 'ok' else 'failed'}, {ago(lc['ts'], now)} ({when(lc['ts'])})"
        + (f": {lc['reason']}" if lc.get("reason") else ""))
    rb = d["last_read_back"]
    row("Read-back", f"5 % of the data read back {ago(rb['ts'], now)}, passed" if rb else
        "none yet (in a month's first week, 5 % of the data is read back)")
    lt, tp = d["last_test"], d["last_test_passed"]
    if not lt:
        row("Test restore", "none yet (monthly; now: bromigos lab backups test)")
    elif lt["phase"] == "ok":
        row("Test restore", f"passed {ago(lt['ts'], now)} ({when(lt['ts'])}): {count(lt.get('files') or 0, 'file')} restored "
            "and read back" + (", everything" if lt.get("mode") == "all" else ", a sample"))
    else:
        row("Test restore", f"failed {ago(lt['ts'], now)} ({when(lt['ts'])}): {lt.get('reason') or '?'}")
        row("", f"the last one that passed: {ago(tp['ts'], now)}" if tp else "none has passed yet")
    sn = d["snapshots"]
    if sn is None:
        row("Backups kept", "not counted yet (the next backup counts them; now: bromigos lab backups list)")
    else:
        kept = count(sn["count"], "backup")
        if sn.get("oldest_ts") and sn.get("newest_ts") and sn["count"] > 1:
            kept += f", from {when(sn['oldest_ts'])[:10]} to {when(sn['newest_ts'])[:10]}"
        elif sn.get("newest_ts"):
            kept += f", from {when(sn['newest_ts'])[:10]}"
        row("Backups kept", kept + (f" (counted {ago(sn['ts'], now)})" if sn.get("ts") else ""))
    t = d["timers"]
    row("Schedule", f"backup nightly ({t.get('backup', 'unknown')}), check weekly ({t.get('check', 'unknown')}), "
        f"test restore monthly ({t.get('test', 'unknown')})")
    r = d["restore"]
    if d["running"] and d["running"]["kind"] == "test":
        row("Running now", "a test restore: " + next((s["title"] for s in d["running"]["steps"] if s["id"] == d["running"]["step"]), "starting"))
    if r:
        state = "running now" if r.get("running") else "stopped part-way" if r["interrupted"] else \
            {"done": "finished", "incomplete": "finished with files missing", "failed": "failed",
             "refused": "didn't start (nothing was changed)"}.get(r.get("state"), r.get("state"))
        row("Last restore", f"{state}, started {r.get('started', '?')}: backup {r.get('snapshot', '?')} "
            + ("put back in place" if r.get("mode") == "in-place" else f"into {r.get('work') if r['interrupted'] else r.get('target')}"))
    if dest["present"] is False:
        print(f"\n  Connect the drive that holds {dest['path']}. The nightly backup carries on by itself, or run one "
              "now: bromigos lab backups run")
    for p in h["problems"]:
        if p["severity"] != "info":
            print(f"\n  {p['title']}. {p['detail']}")
    print("\nGet files back: bromigos lab backups restore   ·   every backup: bromigos lab backups list")


# ------------------------------------------------------------------ restic

def restic_env(b):
    """restic's environment, as bromigos-server's backup has it: the destination, the key file,
    and the credentials file's KEY=VALUE lines. The key is never made here: a restore with a
    new key could read nothing."""
    if not os.path.isfile(at(KEY)):
        raise Problem("no-key", f"The backup's key ({KEY}) isn't on this server, and without it the backup can't be "
                      f"read. Put the key you kept back in that file, readable by root only, then try again.")
    if not os.access(at(KEY), os.R_OK):
        raise Problem("needs-root", f"The backup's key ({KEY}) can only be read by the administrator.", exit=3)
    if ROOT != "/" and not b["to"].startswith(("/", "local:")):
        # the tests' stand-in root holds a folder destination; anything else is a real place on a network
        raise Problem("stand-in", f"In a stand-in root only a folder destination is read, not {where(b['to'])}.", exit=3)
    env = dict(os.environ)
    env.update(RESTIC_REPOSITORY=repository(b["to"]), RESTIC_PASSWORD_FILE=at(KEY), RESTIC_CACHE_DIR=at("/var/cache/restic"),
               RESTIC_PROGRESS_FPS="1")
    try:
        with open(at(b["env_file"])) as f:
            for line in f:
                k, eq, v = line.strip().partition("=")
                if eq and re.match(r"^[A-Z][A-Z0-9_]*$", k):
                    env[k] = v.strip().strip('"').strip("'")
    except OSError:
        pass
    return env


def restic(env, args, on_line=None):
    """(exit code, stdout, stderr). on_line gets each line of stdout as it comes (a restore's
    progress). If this process is stopped while restic runs, restic is stopped too, and unlocks
    the backup."""
    with tempfile.TemporaryFile("w+", errors="replace") as err:
        try:
            proc = subprocess.Popen(["restic", *args], stdout=subprocess.PIPE, stderr=err, stdin=subprocess.DEVNULL,
                                    text=True, errors="replace", env=env)
        except FileNotFoundError:
            return 127, "", "restic: not installed"
        out = []
        try:
            for line in proc.stdout:
                if on_line:
                    on_line(line)
                else:
                    out.append(line)
            rc = proc.wait()
        except BaseException:
            proc.send_signal(signal.SIGINT)
            try:
                proc.wait(timeout=15)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait()
            raise
        err.seek(0)
        return rc, "".join(out), err.read()


def restic_errors(err):
    """restic's --json errors on stderr: ([{"path", "why"}], the last message)."""
    items, last = [], ""
    for line in err.splitlines():
        try:
            m = json.loads(line)
        except ValueError:
            if line.strip():
                last = line.strip()
            continue
        if not isinstance(m, dict):
            continue
        if m.get("message_type") == "error":
            why = (m.get("error") or {}).get("message") or "restic gave no reason"
            path = sysp(m.get("item") or "")
            if not any(i["path"] == path for i in items):      # restic says a file twice: why it failed, then what that broke
                items.append({"path": path, "why": why})
            last = why
        elif m.get("message_type") == "exit_error":
            last = m.get("message") or last
    return items, " ".join(last.split())[:300]


def unreachable(b, rc, err):
    """restic couldn't open the backup: why, as a Problem."""
    _, last = restic_errors(err)
    dest = destination(b["to"], True)
    if rc == 127:
        return Problem("no-restic", "restic isn't installed on this server, so the backup can't be read.")
    if dest["present"] is False:
        return Problem("unreachable", f"The backup can't be reached: the drive at {dest['path']} is not connected.")
    if rc == 10:
        return Problem("unreachable", f"There is no backup at {where(b['to'])} yet: the first one runs tonight.")
    if rc == 11:
        return Problem("locked", "The backup is in use by another job (the nightly backup, its check or another "
                       "restore). Try again when that has finished.")
    if rc == 12:
        return Problem("wrong-key", f"The key in {KEY} doesn't open this backup. Put the key you kept for it back "
                       "in that file.")
    return Problem("unreachable", f"The backup at {where(b['to'])} can't be read: {last or 'restic failed'}")


def snapshot_row(s):
    summary = s.get("summary") or {}
    ts = stamp(s.get("time"))
    return {"id": s.get("id", ""), "short_id": s.get("short_id") or s.get("id", "")[:8], "time": s.get("time"), "ts": ts,
            "at": iso(ts) if ts else None, "host": s.get("hostname", ""), "tags": s.get("tags") or [],
            "paths": [sysp(p) for p in s.get("paths") or []], "raw_paths": s.get("paths") or [],
            "files": summary.get("total_files_processed"), "bytes": summary.get("total_bytes_processed"),
            "added_bytes": summary.get("data_added_packed", summary.get("data_added")),
            "nightly": TAG in (s.get("tags") or [])}


def snapshots(b, env):
    """Every backup in the destination, oldest first."""
    rc, out, err = restic(env, ["snapshots", "--json", "--retry-lock", "2m"])
    if rc != 0:
        raise unreachable(b, rc, err)
    try:
        rows = [snapshot_row(s) for s in json.loads(out or "[]")]
    except ValueError:
        raise Problem("unreachable", "restic's list of backups couldn't be read.")
    return sorted(rows, key=lambda r: r["ts"] or 0)


def inventory(rows, now=None):
    """How many backups and what they span: backup.json's "snapshots"."""
    stamps = [r["ts"] for r in rows if r["ts"]]
    return {"count": len(rows), "oldest_ts": min(stamps) if stamps else None, "newest_ts": max(stamps) if stamps else None,
            "ts": time.time() if now is None else now}


def pick(rows, spec):
    """The backup a person named: "latest" (the newest nightly one), or the start of an id."""
    if not rows:
        raise Problem("no-such-backup", "There are no backups yet: the first one runs tonight.")
    if not spec or spec == "latest":
        ours = [r for r in rows if r["nightly"]] or rows
        return ours[-1]
    hits = [r for r in rows if r["id"].startswith(spec.lower())]
    if len(hits) == 1:
        return hits[0]
    raise Problem("no-such-backup", (f"More than one backup starts with {spec}: give more of the id." if hits else
                                     f"There is no backup {spec}.") + " `bromigos lab backups list` shows them.", exit=2)


def nodes(env, snap, paths, recursive=False):
    """restic ls: the nodes at (or under) these paths of the backup, as it tells them."""
    out_rows = []

    def on_line(line):
        try:
            m = json.loads(line)
        except ValueError:
            return
        if isinstance(m, dict) and m.get("message_type", m.get("struct_type")) == "node":
            out_rows.append(m)

    rc, _, err = restic(env, ["ls", "--json", "--retry-lock", "2m", *(["--recursive"] if recursive else []), snap["id"],
                              *[at(p) for p in paths]], on_line)
    if rc != 0:
        raise Problem("failed", f"The backup's list of files couldn't be read: {restic_errors(err)[1] or 'restic failed'}")
    return out_rows


def entry(n):
    return {"name": n.get("name", ""), "path": sysp(n.get("path", "")),
            "type": n.get("type") if n.get("type") in ("file", "dir", "symlink") else "other",
            "size": n.get("size") if n.get("type") == "file" else None, "mtime": n.get("mtime"),
            "mtime_ts": stamp(n.get("mtime")), "permissions": n.get("permissions", "")}


def clean_paths(paths):
    out = []
    for p in paths:
        if not p.startswith("/"):
            raise Problem("usage", f"{p}: give the full path as it was on the server, such as /etc/fstab.", exit=2)
        out.append(os.path.normpath(p))
    return list(dict.fromkeys(out))


def literal(path):
    """A path as a restic include pattern that means exactly that path."""
    return re.sub(r"([\\*?\[])", r"\\\1", path)


def include_line(path):
    """A path as one line of a restic include file, meaning exactly that path. restic expands
    $NAME in these files and trims each line's ends, so a $ is doubled and a trailing space is
    written as [ ]. None for a name with a line break in it, which no line can say."""
    if "\n" in path or "\r" in path:
        return None
    line = literal(path).replace("$", "$$")
    tail = re.search(r"\s+$", line)
    return line if not tail else line[:tail.start()] + "".join(f"[{c}]" for c in tail.group())


def own_folder(path):
    """A work folder of ours: made if it isn't there, and only ever a real folder that belongs
    to whoever runs this, open to no one else (never a link someone left in its place)."""
    os.makedirs(os.path.dirname(path) or "/", mode=0o755, exist_ok=True)
    try:
        os.mkdir(path, 0o700)
    except FileExistsError:
        pass
    d = os.lstat(path)
    if not stat.S_ISDIR(d.st_mode) or d.st_uid != os.geteuid():
        raise Problem("failed", f"{path} isn't a folder of this command's own, so it isn't used: move it away.")
    return path


def snapref(snap):
    """restic's "ID:subfolder": the backup with the stand-in root taken off its paths, so a
    restore writes /etc/fstab and not /stand-in/etc/fstab."""
    return snap["id"] if ROOT == "/" else f"{snap['id']}:{ROOT.rstrip('/')}"


def in_backup(env, snap, paths):
    """Each path must be in the backup: say which isn't, and where to look."""
    if not paths:
        return
    have = {sysp(n.get("path", "")) for n in nodes(env, snap, paths)}
    for p in paths:
        if p not in have:
            raise Problem("not-in-backup", f"{p} isn't in the backup of {when(snap['ts'])} ({snap['short_id']}). See what "
                          f"is: bromigos lab backups show {snap['short_id']} {os.path.dirname(p) or '/'}", exit=2)


def free_bytes(path):
    """Free space where path will be written: on the filesystem of its nearest folder that exists."""
    fixed = os.environ.get("BROMIGOS_BACKUPS_FREE_BYTES")       # the tests' stand-in disk
    if fixed:
        return int(fixed)
    p = path
    while not os.path.exists(p) and p != os.path.dirname(p):
        p = os.path.dirname(p)
    return shutil.disk_usage(p).free


# ------------------------------------------------------------------ a job's named steps

class Job:
    """A restore or a test restore: its named steps on the screen (or as JSON lines on stderr),
    and in restore.json, so another screen can follow it and a stopped one is never taken for
    a finished one."""

    def __init__(self, kind, steps, as_json, quiet=False, **record):
        self.steps, self.as_json, self.quiet, self.n, self.last = steps, as_json, quiet, 0, 0.0
        self.path = TEST_JOURNAL if kind == "test" else JOURNAL
        before = (job_record(self.path) or {}).get("unfinished")
        self.record = dict(record, id=f"{time.strftime('%Y%m%d-%H%M%S')}-{os.getpid()}", kind=kind, state="running",
                           started=iso(), started_ts=time.time(), pid=os.getpid(), boot=boot_id(), step="", percent=None,
                           steps=[{"id": s, "title": t, "state": "waiting"} for s, t in steps])
        if before:
            self.record["unfinished"] = before      # a restore in place that stopped part-way stays on record
        self.save()

    def save(self):
        try:
            write_json(self.path, self.record)
        except OSError:
            pass

    def _event(self, **doc):
        if self.as_json:
            print(json.dumps(doc), file=sys.stderr, flush=True)

    def step(self, sid):
        for s in self.record["steps"]:
            if s["state"] == "running":
                s["state"] = "done"
            if s["id"] == sid:
                s["state"] = "running"
        self.n = [s for s, _ in self.steps].index(sid) + 1
        title = dict(self.steps)[sid]
        self.record.update(step=sid, percent=None)
        self.save()
        self._event(event="step", id=sid, n=self.n, of=len(self.steps), title=title)
        if not self.as_json and not self.quiet:
            print(f"[{self.n}/{len(self.steps)}] {title}", flush=True)

    def note(self, text):
        self._event(event="note", id=self.record["step"], text=text)
        if not self.as_json and not self.quiet:
            print(f"      {text}", flush=True)

    def progress(self, percent, text):
        now = time.monotonic()
        if now - self.last < 5:
            return
        self.last = now
        self.record["percent"] = percent
        self.save()
        self._event(event="progress", id=self.record["step"], percent=percent, text=text)
        if not self.as_json and not self.quiet:
            print(f"      {percent} % · {text}", flush=True)

    def finish(self, state, **result):
        for s in self.record["steps"]:
            if s["state"] == "running":
                s["state"] = "done" if state in ("done", "incomplete") else state
        self.record.update(state=state, finished=iso(), finished_ts=time.time(), percent=None, result=result)
        if state == "done" and self.record.get("mode") == "in-place" and covers(self.record.get("paths"), self.record.get("unfinished")):
            del self.record["unfinished"]           # those paths are whole again
        self.save()


def covers(paths, left):
    """Do these paths (none: everything) take in every path of an unfinished restore?"""
    if not isinstance(left, dict):
        return False
    paths, theirs = paths or [], left.get("paths") or []
    return not paths or bool(theirs and all(any(p == q or p.startswith(q.rstrip("/") + "/") for q in paths) for p in theirs))


def settle(paths):
    """A look found every file of these paths matching a backup: an unfinished restore of
    them is finished after all (it stopped while reading files back, say)."""
    j = read_json(JOURNAL)
    left = (job_record(doc=dict(j)) or {}).get("unfinished")
    if covers(paths, left):
        j.pop("unfinished", None)
        if j.get("mode") == "in-place" and j.get("state") in ("running", "interrupted", "incomplete"):
            j.update(state="done", finished=iso(), finished_ts=time.time(), settled=True)
        try:
            write_json(JOURNAL, j)
        except OSError:
            pass


def on_progress(job, what="files"):
    """restic restore's --json status lines as the job's progress; returns (callback, holder)
    where holder["summary"] is restic's last word."""
    hold = {"summary": {}}

    def on_line(line):
        try:
            m = json.loads(line)
        except ValueError:
            return
        if not isinstance(m, dict):
            return
        if m.get("message_type") == "summary":
            hold["summary"] = m
        elif m.get("message_type") == "status" and m.get("total_files"):
            job.progress(int(100 * (m.get("percent_done") or 0)),
                         f"{m.get('files_restored', 0):,} of {m['total_files']:,} {what}")
    return on_line, hold


def catch_signals():
    def stop(signum, frame):
        for s in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
            signal.signal(s, signal.SIG_IGN)
        raise Stopped(signal.Signals(signum).name)
    for s in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
        signal.signal(s, stop)


def hold_signals():
    for s in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
        signal.signal(s, signal.SIG_IGN)


def release_signals():
    signal.signal(signal.SIGINT, signal.default_int_handler)
    for s in (signal.SIGTERM, signal.SIGHUP):
        signal.signal(s, signal.SIG_DFL)


def confirm(question):
    try:
        return input(f"{question} Type yes: ").strip().lower() == "yes"
    except (EOFError, KeyboardInterrupt):
        print()
        return False


# ------------------------------------------------------------------ list and show

def cmd_list(a, b):
    env = restic_env(b)
    rows = snapshots(b, env)
    doc = {"schema": SCHEMA, "ok": True, "to": where(b["to"]), "snapshots": [{k: v for k, v in r.items() if k != "raw_paths"} for r in rows]}
    if a.json:
        print(json.dumps(doc, indent=1))
        return 0
    if not rows:
        print(f"No backups yet at {where(b['to'])}: the first one runs tonight.")
        return 0
    print(f"{count(len(rows), 'backup')} at {where(b['to'])}, newest first:\n")
    for r in reversed(rows):
        files = count(r["files"], "file") if r["files"] is not None else "files not counted"
        print(f"  {r['short_id']}  {when(r['ts']) if r['ts'] else '?':<16}  {size(r['bytes']):>10}  {files:>14}  "
              + ", ".join(r["paths"]) + ("" if r["nightly"] else f"  (not the nightly backup: from {r['host'] or '?'})"))
    print("\nLook inside one: bromigos lab backups show ID   ·   get files back: bromigos lab backups restore ID [PATH…]")
    return 0


def cmd_show(a, b):
    env = restic_env(b)
    spec, where_in = (None, a.snapshot) if (a.snapshot or "").startswith("/") and not a.path else (a.snapshot, a.path)
    snap = pick(snapshots(b, env), spec)
    path = clean_paths([where_in])[0] if where_in else None
    if path is None:
        tops = snap["paths"]
        got = {sysp(n.get("path", "")): n for n in nodes(env, snap, tops)}
        entries = [entry(got[p]) for p in tops if p in got]
    else:
        got = nodes(env, snap, [path])
        if not any(sysp(n.get("path", "")) == path for n in got):
            raise Problem("not-in-backup", f"{path} isn't in the backup of {when(snap['ts'])} ({snap['short_id']}). "
                          f"`bromigos lab backups show {snap['short_id']}` lists what is.", exit=2)
        entries = [entry(n) for n in got if sysp(n.get("path", "")) != path] or [entry(n) for n in got]
    doc = {"schema": SCHEMA, "ok": True, "snapshot": {k: v for k, v in snap.items() if k != "raw_paths"}, "path": path,
           "entries": entries}
    if a.json:
        print(json.dumps(doc, indent=1))
        return 0
    print(f"Backup {snap['short_id']} · {when(snap['ts'])} · {path or 'everything in it'}\n")
    for e in entries:
        kind = {"dir": "folder", "symlink": "link"}.get(e["type"], e["type"])
        print(f"  {kind:<7} {size(e['size']) if e['size'] is not None else '':>10}  "
              f"{when(e['mtime_ts']) if e['mtime_ts'] else '':<16}  {e['path'] if path is None else e['name']}"
              + ("/" if e["type"] == "dir" else ""))
    if not entries:
        print("  (empty)")
    print(f"\nGo deeper: bromigos lab backups show {snap['short_id']} PATH   ·   get it back: "
          f"bromigos lab backups restore {snap['short_id']} PATH")
    return 0


# ------------------------------------------------------------------ restore

def restore_args(a):
    """`restore [ID] [PATH…]`: a first word that starts with / is a path, from the newest backup."""
    words = list(a.what)
    spec = None if not words or words[0].startswith("/") else words.pop(0)
    return spec, clean_paths(words)


INSIDE = "restore.partial"       # the work folder's name inside a --to folder that was there already


def new_folder(a, snap):
    """Where a restore goes: (the folder, its work folder while it isn't whole). --to must be
    new or empty; without it, a new folder under /srv/restore named after the backup. The work
    folder is always on the filesystem the files end up on: beside a new folder, inside one
    that was there already (an empty disk's mount point, say)."""
    if a.to:
        final = os.path.abspath(a.to)
        if os.path.lexists(final) and (not os.path.isdir(final) or os.path.islink(final)):
            raise Problem("would-overwrite", f"{final} is there already and isn't a folder. Restore never writes over "
                          "anything: pick a folder that doesn't exist yet.", exit=3)
        if os.path.isdir(final):
            inside, names = os.path.join(final, INSIDE), os.listdir(final)
            if names and not (names == [INSIDE] and unfinished_folder(inside)):
                raise Problem("would-overwrite", f"{final} has files in it. Restore never writes into a folder with "
                              "files in it, so nothing can be replaced by mistake: pick a new folder. To put files "
                              "back where they came from, see --in-place.", exit=3)
            return final, inside
        return final, final.rstrip("/") + ".partial"
    base = os.path.join(at(RESTORE_HOME), f"backup-{time.strftime('%Y-%m-%d-%H%M', time.localtime(snap['ts'] or 0))}-{snap['short_id']}")
    final, n = base, 1
    while os.path.lexists(final):
        n += 1
        final = f"{base}-{n}"
    return final, final + ".partial"


def unfinished_folder(work):
    """What a restore's own work folder says it is, when it stopped part-way: its marker
    ({"snapshot", "paths"}). Only a real folder of ours with a real marker file in it (never
    a link someone left there); else None."""
    try:
        d, m = os.lstat(work), os.lstat(os.path.join(work, MARKER))
        if not (stat.S_ISDIR(d.st_mode) and stat.S_ISREG(m.st_mode) and d.st_uid == m.st_uid == os.geteuid()):
            return None
        with open(os.path.join(work, MARKER)) as f:
            doc = json.load(f)
        return doc if isinstance(doc, dict) else None
    except (OSError, ValueError):
        return None


def count_files(top):
    """(files and links, their bytes) under a restored folder."""
    files = total = 0
    for d, dirs, names in os.walk(top):
        for n in names + [x for x in dirs if os.path.islink(os.path.join(d, x))]:
            if n == MARKER and d == top:
                continue
            try:
                s = os.lstat(os.path.join(d, n))
            except OSError:
                continue
            files += 1
            total += s.st_size if stat.S_ISREG(s.st_mode) else 0
    return files, total


def cmd_restore(a, b):
    env = restic_env(b)
    spec, paths = restore_args(a)
    if a.in_place:
        if a.to:
            raise Problem("usage", "--to and --in-place don't go together: a new folder, or back where the files were.", exit=2)
        return restore_in_place(a, b, env, spec, paths)
    if a.apply or a.plan or a.without_snapshot:
        raise Problem("usage", "--apply, --plan and --without-snapshot belong to --in-place. Without it, restore "
                      "makes a new folder and replaces nothing.", exit=2)
    steps = [("find", "Finding the backup"), ("size", "Working out what to restore"), ("space", "Checking free space"),
             ("restore", "Restoring the files" + ("" if a.no_verify else ", then reading each one back")),
             ("finish", "Finishing")]
    snap = pick(snapshots(b, env), spec)
    in_backup(env, snap, paths)
    final, work = new_folder(a, snap)
    resumed = os.path.lexists(work)
    if resumed:
        was = unfinished_folder(work)
        if not was:
            raise Problem("would-overwrite", f"{work} is there already, and isn't a restore stopped part-way. Restore "
                          "never writes over anything: move it away, or pick another folder with --to.", exit=3)
        if was.get("snapshot") != snap["short_id"] or was.get("paths") != paths:
            raise Problem("other-restore", f"{work} holds another restore that stopped part-way: backup {was.get('snapshot')}, "
                          f"{', '.join(was.get('paths') or []) or 'everything in it'}. Mixing two would leave a folder "
                          "that looks whole and isn't. Finish that one with its own command, delete the folder, or "
                          "pick another with --to.", exit=3)
    job = Job("restore", steps, a.json, mode="new-folder", snapshot=snap["short_id"], snapshot_at=snap["at"],
              paths=paths, target=final, work=work)
    includes = [x for p in paths for x in ("--include", literal(p))]
    try:
        catch_signals()
        job.step("find")
        job.note(f"the backup of {when(snap['ts'])} ({snap['short_id']}): " + (", ".join(paths) if paths else "everything in it"))
        job.step("size")
        rc, out, err = restic(env, ["restore", snapref(snap), "--target", work, "--dry-run", "--json", "--retry-lock", "2m", *includes])
        need = None
        for line in out.splitlines():
            try:
                m = json.loads(line)
            except ValueError:
                continue
            if isinstance(m, dict) and m.get("message_type") == "summary":
                need = int(m.get("total_bytes") or 0)
        if rc != 0 or need is None:
            raise Problem("failed", f"The backup couldn't be read: {restic_errors(err)[1] or 'restic failed'}")
        job.note(size(need))
        job.step("space")
        free = free_bytes(work)
        job.note(f"{size(need)} needed, {size(free)} free in {os.path.dirname(final)}")
        if need + MARGIN > free:
            raise Problem("no-space", f"Not enough room: the restore needs {size(need)} and {os.path.dirname(final)} has "
                          f"{size(free)} free. Nothing was restored. Free some space, restore fewer paths, or pick "
                          "a folder on a bigger disk with --to.", exit=4, need=need, free=free)
        job.step("restore")
        if not resumed:
            os.makedirs(os.path.dirname(work), exist_ok=True)
            os.mkdir(work, 0o700)                   # fails sooner than follow something put there since the look
        with os.fdopen(os.open(os.path.join(work, MARKER), os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o600), "w") as f:
            json.dump({"snapshot": snap["short_id"], "paths": paths, "started": iso(), "note": "This folder is a "
                       "restore that hasn't finished. It is incomplete until this file is gone and the folder has "
                       "lost its .partial name."}, f)
        if resumed:
            job.note(f"carrying on in {work}, where a restore stopped before")
        on_line, hold = on_progress(job)
        rc, _, err = restic(env, ["restore", snapref(snap), "--target", work, "--json", "--retry-lock", "2m",
                                  *([] if a.no_verify else ["--verify"]), *includes], on_line)
        skipped, last = restic_errors(err)
        if rc != 0 and not hold["summary"]:
            raise Problem("failed", f"The restore failed: {last or 'restic failed'}. What it got to is in {work}, and "
                          "is incomplete.")
        job.step("finish")
        hold_signals()                              # giving the folder its name is never stopped half-way
        files, total = count_files(work)
        state = "done" if rc == 0 and not skipped else "incomplete"
        inside = os.path.dirname(work) == final     # --to was there already: the work is in it
        if state == "incomplete":
            base, n = (os.path.join(final, "restore-incomplete") if inside else final + "-incomplete"), 1
            final = base
            while os.path.lexists(final):
                n += 1
                final = f"{base}-{n}"
            inside = False
        os.unlink(os.path.join(work, MARKER))
        if inside:
            for name in os.listdir(work):
                os.rename(os.path.join(work, name), os.path.join(final, name))
            os.rmdir(work)
        else:
            os.rename(work, final)
    except Stopped as e:
        if not os.path.isdir(work):
            return stopped(job, a, e, "Stopped before anything was restored. Nothing on the server changed.", "refused")
        return stopped(job, a, e, f"Stopped. What was restored so far is in {work}: it is incomplete, and keeps "
                       "that name. Nothing else on the server changed. Run the same command again to carry on, or delete that folder.")
    except Problem as e:
        job.finish("failed", error=e.message)
        raise
    except OSError as e:
        job.finish("failed", error=str(e))
        raise Problem("failed", f"The restore stopped: {e}. " + (f"What it got to is in {work}, and is incomplete."
                                                                 if os.path.isdir(work) else "Nothing was restored."))
    finally:
        release_signals()
    result = {"schema": SCHEMA, "ok": state == "done", "state": state, "mode": "new-folder",
              "snapshot": {k: v for k, v in snap.items() if k != "raw_paths"}, "paths": paths or snap["paths"],
              "target": final, "files": files, "bytes": total, "verified": not a.no_verify and state == "done",
              "replaced": 0, "skipped": skipped}
    job.finish(state, target=final, files=files, bytes=total, skipped=len(skipped))
    if a.json:
        print(json.dumps(result, indent=1))
    else:
        print(f"\nRestored {count(files, 'file')} ({size(total)}) from the backup of {when(snap['ts'])} ({snap['short_id']})")
        print(f"  into {final}")
        print(f"  Each file is at its old path inside that folder: /etc/fstab would be {final}/etc/fstab.")
        print("  Nothing on the server was replaced. Copy back what you need; the folder is root's, like the backup.")
        print_skipped(skipped, f"The folder is named -incomplete because of {'it' if len(skipped) == 1 else 'them'}.")
    return 0 if state == "done" else 1


def print_skipped(skipped, more=""):
    if not skipped:
        print("  Skipped: nothing.")
        return
    print(f"  Skipped: {count(len(skipped), 'file')} could not be restored. {more}".rstrip())
    for s in skipped[:10]:
        print(f"    {s['path'] or '?'}: {s['why']}")
    if len(skipped) > 10:
        print(f"    … and {len(skipped) - 10} more (--json lists them all)")


def stopped(job, a, e, words, state="interrupted"):
    job.finish(state, signal=str(e))
    if a.json:
        print(json.dumps({"schema": SCHEMA, "ok": False, "state": "interrupted",
                          "error": {"code": "interrupted", "message": words}}, indent=1))
    else:
        print(f"\n{words}", file=sys.stderr)
    return 130


# ---- in place

def snapper():
    """The snapper command: the real one only on a real server (stand_in())."""
    return stand_in("snapper")


def snapper_configs():
    """{subvolume: snapper's configuration}: where the server keeps snapshots (/ and the data
    disks, as the installer set them up). Empty where there's no snapper."""
    if not snapper():
        return {}
    for extra in ([], ["--no-dbus"]):
        try:
            r = subprocess.run([snapper(), *extra, "--jsonout", "list-configs", "--columns", "config,subvolume"],
                               capture_output=True, text=True, timeout=60)
        except (OSError, subprocess.TimeoutExpired):
            return {}
        if r.returncode == 0:
            try:
                return {c["subvolume"]: c["config"] for c in json.loads(r.stdout).get("configs") or []}
            except (ValueError, KeyError, TypeError, AttributeError):
                return {}
    return {}


def subvolume_of(path, cache):
    """The top of the filesystem (or btrfs subvolume) a server path is on: the folder snapper
    would have a configuration for."""
    p = at(path)
    while not os.path.lexists(p) or not os.path.isdir(p) or os.path.islink(p):
        p = os.path.dirname(p)
    if p in cache:
        return cache[p]
    start, dev = p, os.lstat(p).st_dev
    top = os.path.realpath(ROOT)
    while os.path.realpath(p) != top:
        up = os.path.dirname(p)
        if up == p or os.lstat(up).st_dev != dev:
            break
        p = up
    cache[start] = sysp(p)
    return cache[start]


def plan_in_place(env, snap, paths):
    """What putting these paths back where they were would do, from restic's own dry run:
    which files it replaces, which it brings back, and how many already match. Nothing is
    written to the server's files."""
    includes = [x for p in paths for x in ("--include", literal(p))]
    replace, add, links, same, summary = [], [], [], [0], {}

    def on_line(line):
        try:
            m = json.loads(line)
        except ValueError:
            return
        if not isinstance(m, dict):
            return
        if m.get("message_type") == "summary":
            summary.update(m)
        if m.get("message_type") != "verbose_status":
            return
        item, action = m.get("item") or "", m.get("action")
        if action == "unchanged":
            same[0] += 1
            return
        try:
            now = os.lstat(at(item))
        except OSError:
            add.append({"path": item, "size": int(m.get("size") or 0)})
            return
        if stat.S_ISLNK(now.st_mode):
            links.append(item)                  # restic remakes every link: only one that points elsewhere changes
        elif not stat.S_ISDIR(now.st_mode):
            replace.append({"path": item, "size": int(m.get("size") or 0), "now_size": now.st_size, "now_modified": iso(now.st_mtime)})

    rc, _, err = restic(env, ["restore", snapref(snap), "--target", ROOT, "--dry-run", "--json", "-vv", "--retry-lock", "2m",
                              *includes], on_line)
    if rc != 0 or not summary:
        raise Problem("failed", f"The backup couldn't be read: {restic_errors(err)[1] or 'restic failed'}")
    if links:
        # what's a link on the server now. In the backup it may be a link too (then where does it
        # point?) or a file or folder (then the link goes). restic's list says which; it doesn't
        # say where a link points, so the backup's links alone are restored to a scratch folder
        # and read there: never a folder's contents
        kinds = {}
        for i in range(0, len(links), 400):
            kinds.update({sysp(n.get("path", "")): n.get("type") for n in nodes(env, snap, links[i:i + 400])})
        scratch = tempfile.mkdtemp(prefix="links-", dir=own_folder(at(SCRATCH)))
        try:
            listing, tree = os.path.join(scratch, ".include"), os.path.join(scratch, "tree")
            with open(listing, "w") as f:
                f.write("".join(include_line(p) + "\n" for p in links if kinds.get(p) == "symlink" and include_line(p)))
            if os.path.getsize(listing):
                restic(env, ["restore", snapref(snap), "--target", tree, "--json", "--retry-lock", "2m", "--include-file", listing])
            for item in links:
                try:
                    there = os.readlink(os.path.join(tree, item.lstrip("/"))) if kinds.get(item) == "symlink" else None
                except OSError:
                    there = None
                if there is not None and there == os.readlink(at(item)):
                    same[0] += 1
                else:
                    replace.append({"path": item, "size": 0, "now_size": 0, "now_modified": iso(os.lstat(at(item)).st_mtime),
                                    "link": "points elsewhere" if kinds.get(item) == "symlink" else "not a link in the backup"})
        finally:
            shutil.rmtree(scratch, ignore_errors=True)
    replace.sort(key=lambda r: r["path"])
    add.sort(key=lambda r: r["path"])
    digest = hashlib.sha256(json.dumps([snap["id"], paths, [[r["path"], r["size"], r["now_size"], r["now_modified"]] for r in replace],
                                        [[r["path"], r["size"]] for r in add]]).encode()).hexdigest()[:16]
    cache, configs, by_sub = {}, snapper_configs(), {}
    for r in replace + add:
        by_sub.setdefault(subvolume_of(os.path.dirname(r["path"]) or "/", cache), []).append(r)
    # room for every file it writes: the snapshot taken first keeps what the old ones held
    safety = [{"subvolume": sub, "config": configs.get(sub), "files": len(rows), "bytes": sum(r["size"] for r in rows)}
              for sub, rows in sorted(by_sub.items())]
    return {"replace": replace, "add": add, "unchanged": same[0], "digest": digest, "safety": safety,
            "bytes": sum(s["bytes"] for s in safety)}


def print_plan(snap, paths, plan):
    rep, add = plan["replace"], plan["add"]
    print(f"\nPutting {', '.join(paths) if paths else 'everything'} back from the backup of {when(snap['ts'])} ({snap['short_id']}) would:\n")
    print(f"  replace {count(len(rep), 'file')} that changed since the backup" + (":" if rep else ""))
    for r in rep[:SHOWN]:
        print(f"    {r['path']}   " + ("(a link that points somewhere else now)" if r.get("link") == "points elsewhere" else
                                      "(a link now; a file or a folder in the backup)" if r.get("link") else
                                      f"(now {size(r['now_size'])}, changed {r['now_modified'][:16].replace('T', ' ')}; "
                                      f"the backup's is {size(r['size'])})"))
    if len(rep) > SHOWN:
        print(f"    … and {len(rep) - SHOWN:,} more (--json lists them all)")
    print(f"  bring back {count(len(add), 'file or folder', 'files and folders')} that {'is' if len(add) == 1 else 'are'} gone"
          + (":" if add else ""))
    for r in add[:SHOWN]:
        print(f"    {r['path']}")
    if len(add) > SHOWN:
        print(f"    … and {len(add) - SHOWN:,} more (--json lists them all)")
    print(f"  leave {count(plan['unchanged'], 'file')} alone that already match the backup")
    print("  leave alone everything that isn't in the backup: nothing is ever deleted\n")
    for s in plan["safety"]:
        if s["config"]:
            print(f"  First, a snapshot of {s['subvolume']} is taken (snapper's \"{s['config']}\"), so this can be undone.")
        else:
            print(f"  No snapshot can be taken of {s['subvolume']}: snapshots aren't set up for it. What this replaces "
                  "there can't be brought back afterwards.")


def restore_in_place(a, b, env, spec, paths):
    steps = [("find", "Finding the backup"), ("plan", "Working out what would change"), ("space", "Checking free space"),
             ("snapshot", "Taking a snapshot of the files as they are now"),
             ("restore", "Putting the files back" + ("" if a.no_verify else ", then reading each one back")), ("finish", "Finishing")]
    snap = pick(snapshots(b, env), spec)
    in_backup(env, snap, paths)
    plan = plan_in_place(env, snap, paths)
    doc = {"schema": SCHEMA, "ok": True, "state": "planned", "mode": "in-place", "applied": False,
           "snapshot": {k: v for k, v in snap.items() if k != "raw_paths"}, "paths": paths or snap["paths"], **plan}
    todo = len(plan["replace"]) + len(plan["add"])
    again = "bromigos lab backups restore " + " ".join([snap["short_id"], *paths]) + " --in-place --apply"
    if not todo:
        settle(paths)
    if not a.apply or not todo:
        if a.json:
            print(json.dumps(doc, indent=1))
        else:
            print_plan(snap, paths, plan)
            print("\nNothing was changed: this was only a look." + (f" To do it: {again}" if todo else
                                                                     " And there is nothing to do: every file already matches the backup."))
        return 0
    if a.plan and a.plan != plan["digest"]:
        raise Problem("plan-changed", "The files changed since you looked: the list isn't the one you agreed to. "
                      "Nothing was changed. Look again, then apply.", exit=3, digest=plan["digest"])
    bare = [s["subvolume"] for s in plan["safety"] if not s["config"]]
    if not a.json:
        print_plan(snap, paths, plan)
        sys.stdout.flush()
    if not a.yes:
        if a.json or not sys.stdin.isatty():
            raise Problem("needs-yes", "Putting files back in place replaces files on the server, so it needs a yes: "
                          "read the list, then add --yes.", exit=3, digest=plan["digest"])
        if not confirm(f"\nReplace {count(len(plan['replace']), 'file')} and bring back {len(plan['add']):,} on this server?"):
            print("Nothing was changed.")
            return 3
    if bare and not a.without_snapshot:
        if a.yes or a.json or not sys.stdin.isatty():
            raise Problem("no-safety-snapshot", f"No snapshot can be taken of {', '.join(bare)} first, so what this "
                          "replaces there couldn't be brought back. Nothing was changed. To go ahead anyway, add "
                          "--without-snapshot.", exit=3, digest=plan["digest"])
        if not confirm(f"No snapshot can be taken of {', '.join(bare)}. Replace the files there anyway?"):
            print("Nothing was changed.")
            return 3
    job = Job("restore", steps, a.json, mode="in-place", snapshot=snap["short_id"], snapshot_at=snap["at"],
              paths=paths, target="/", work="/", plan=plan["digest"])
    taken, writing = [], False
    includes = [x for p in paths for x in ("--include", literal(p))]
    try:
        catch_signals()
        job.step("find")
        job.note(f"the backup of {when(snap['ts'])} ({snap['short_id']})")
        job.step("plan")
        job.note(f"{count(len(plan['replace']), 'file')} to replace, {len(plan['add']):,} to bring back, {plan['unchanged']:,} already match")
        job.step("space")
        for s in plan["safety"]:
            free = free_bytes(at(s["subvolume"]))
            job.note(f"{s['subvolume']}: {size(s['bytes'])} needed, {size(free)} free")
            if s["bytes"] + MARGIN > free:
                raise Problem("no-space", f"Not enough room on {s['subvolume']}: the files to put back need {size(s['bytes'])}, "
                              f"and {size(free)} is free. Nothing was changed.", exit=4, need=s["bytes"], free=free)
        job.step("snapshot")
        for s in plan["safety"]:
            if not s["config"]:
                job.note(f"{s['subvolume']}: no snapshot (snapshots aren't set up for it); going ahead as you said")
                continue
            try:
                r = subprocess.run([snapper(), "-c", s["config"], "create", "--type", "single", "--cleanup-algorithm", "number",
                                    "--print-number", "--description",
                                    f"before restoring from backup {snap['short_id']} (bromigos lab backups)"],
                                   capture_output=True, text=True, timeout=600)
                number, said = r.stdout.strip().splitlines()[-1:] if r.returncode == 0 else [], r.stderr
            except (OSError, subprocess.TimeoutExpired) as e:
                number, said = [], str(e)
            number = number[0].strip() if number else ""
            if not number.isdigit():
                why = (said.strip().splitlines() or ["snapper gave no number"])[-1][:200]
                if not a.without_snapshot:
                    raise Problem("no-safety-snapshot", f"The snapshot of {s['subvolume']} couldn't be taken ({why}), so "
                                  "nothing was changed. To go ahead without one, add --without-snapshot.", exit=3)
                job.note(f"{s['subvolume']}: the snapshot couldn't be taken ({why}); going ahead as you said")
                continue
            taken.append({"subvolume": s["subvolume"], "config": s["config"], "number": int(number)})
            job.note(f"{s['subvolume']}: snapshot {number}")
        job.record["snapshots_taken"] = taken
        job.record["writing"] = writing = True
        job.step("restore")
        on_line, hold = on_progress(job)
        rc, _, err = restic(env, ["restore", snapref(snap), "--target", ROOT, "--json", "--retry-lock", "2m",
                                  *([] if a.no_verify else ["--verify"]), *includes], on_line)
        skipped, last = restic_errors(err)
        if rc != 0 and not hold["summary"]:
            raise Problem("failed", f"The restore failed part-way: {last or 'restic failed'}. Some files may be from the "
                          f"backup and some not. Running it again carries on: {again}")
        job.step("finish")
    except Stopped as e:
        if not writing:
            return stopped(job, a, e, "Stopped before any file was changed.", "refused")
        undo = " ".join(f"A snapshot of {t['subvolume']} was taken first (number {t['number']})." for t in taken)
        return stopped(job, a, e, "Stopped part-way: some files are from the backup and some are still as they were. "
                       f"Running it again finishes it: {again}. {undo}".rstrip())
    except Problem as e:
        job.finish("interrupted" if writing else "refused", error=e.message)
        raise
    except OSError as e:
        job.finish("interrupted" if writing else "refused", error=str(e))
        raise Problem("failed", f"The restore stopped: {e}. " + (f"Some files may be from the backup and some not. Running "
                                                                 f"it again carries on: {again}" if writing else "Nothing was changed."))
    finally:
        release_signals()
    state = "done" if rc == 0 and not skipped else "incomplete"
    gone = {s["path"] for s in skipped}
    doc.update(ok=state == "done", state=state, applied=True, snapshots_taken=taken, skipped=skipped,
               replaced=len([r for r in plan["replace"] if r["path"] not in gone]),
               added=len([r for r in plan["add"] if r["path"] not in gone]), verified=not a.no_verify and state == "done")
    job.finish(state, replaced=doc["replaced"], added=doc["added"], skipped=len(skipped), snapshots_taken=taken)
    if a.json:
        print(json.dumps(doc, indent=1))
    else:
        print(f"\nPut back from the backup of {when(snap['ts'])} ({snap['short_id']}), in place:")
        print(f"  {count(doc['replaced'], 'file')} replaced, {doc['added']:,} brought back, {plan['unchanged']:,} already matched.")
        print("  Files that aren't in the backup were left alone.")
        for t in taken:
            print(f"  Before it, snapshot {t['number']} of {t['subvolume']} was taken. It holds every file as it was "
                  f"(snapper -c {t['config']} undochange {t['number']}..0 puts them back).")
        if not taken:
            print("  No snapshot was taken first: the files that were replaced can't be brought back.")
        print_skipped(skipped)
    return 0 if state == "done" else 1


# ------------------------------------------------------------------ the test restore

def sample(env, snap, rng):
    """A random sample of the backup's files: up to SAMPLE_FILES of them, none over
    SAMPLE_FILE_BYTES, SAMPLE_BYTES in all. Reads the backup's whole list once, keeping only
    the sample."""
    kept, seen = [], [0]

    def on_line(line):
        try:
            m = json.loads(line)
        except ValueError:
            return
        if not isinstance(m, dict) or m.get("type") != "file" or m.get("struct_type", m.get("message_type")) != "node":
            return
        if int(m.get("size") or 0) > SAMPLE_FILE_BYTES or include_line(m.get("path", "")) is None:
            return
        seen[0] += 1
        row = {"path": m.get("path", ""), "size": int(m.get("size") or 0)}
        if len(kept) < SAMPLE_FILES:
            kept.append(row)
        else:
            i = rng.randrange(seen[0])
            if i < SAMPLE_FILES:
                kept[i] = row

    rc, _, err = restic(env, ["ls", "--json", "--recursive", "--retry-lock", "2m", snap["id"]], on_line)
    if rc != 0:
        raise Problem("failed", f"the backup's list of files couldn't be read: {restic_errors(err)[1] or 'restic failed'}")
    kept.sort(key=lambda r: r["size"])
    while len(kept) > 1 and sum(r["size"] for r in kept) > SAMPLE_BYTES:
        kept.pop()
    return kept, seen[0]


def clear_scratch(home):
    """What a test restore that was killed left behind: its scratch folders, once they are
    six hours old (one running now is younger)."""
    for name in os.listdir(home):
        p = os.path.join(home, name)
        try:
            old = time.time() - os.lstat(p).st_mtime > 6 * HOUR
        except OSError:
            continue
        if old and name.startswith(("test-", "links-")):
            shutil.rmtree(p, ignore_errors=True) if os.path.isdir(p) and not os.path.islink(p) else os.unlink(p)


def run_test(a, b, job, home):
    """The test restore's steps. Returns (the backup, files, bytes); raises Problem with why
    it failed. Its scratch folder, job.record["work"], holds the restored tree and the list
    of what to restore; home is a folder of this command's own."""
    job.step("find")
    clear_scratch(own_folder(home))
    scratch = job.record["work"] = tempfile.mkdtemp(prefix="test-", dir=home)
    tree = os.path.join(scratch, "tree")
    # an empty cache of its own: on the day the server is gone there is no cache, so the test
    # must get everything, the lists of files too, from the destination alone
    env = dict(restic_env(b), RESTIC_CACHE_DIR=os.path.join(scratch, "cache"))
    snap = pick(snapshots(b, env), None)
    job.record.update(snapshot=snap["short_id"], snapshot_at=snap["at"])
    job.note(f"the backup of {when(snap['ts'])} ({snap['short_id']})")
    job.step("pick")
    if a.all:
        rows, includes = None, []
        rc, out, err = restic(env, ["restore", snap["id"], "--target", tree, "--dry-run", "--json", "--retry-lock", "2m"])
        need = next((int(m.get("total_bytes") or 0) for m in map(_loads, out.splitlines()) if m.get("message_type") == "summary"), None)
        if rc != 0 or need is None:
            raise Problem("failed", f"the backup couldn't be read: {restic_errors(err)[1] or 'restic failed'}")
        job.note(f"everything in it: {size(need)}")
    else:
        rows, seen = sample(env, snap, random.Random(a.seed))
        if not rows:
            raise Problem("failed", "the newest backup has no files in it")
        need = sum(r["size"] for r in rows)
        listing = os.path.join(scratch, "include")
        with open(listing, "w") as f:
            f.write("".join(include_line(r["path"]) + "\n" for r in rows))
        includes = ["--include-file", listing]
        job.note(f"{count(len(rows), 'file')} picked at random out of {seen:,} ({size(need)})")
    job.step("space")
    free = free_bytes(scratch)
    job.note(f"{size(need)} needed, {size(free)} free in {home}")
    if need + MARGIN > free:
        raise Problem("no-space", f"not enough room for the test restore: it needs {size(need)} and {home} has "
                      f"{size(free)} free" + (" (a sample needs far less: leave --all out)" if a.all else ""))
    job.step("restore")
    on_line, hold = on_progress(job)
    rc, _, err = restic(env, ["restore", snap["id"], "--target", tree, "--verify", "--json", "--retry-lock", "2m", *includes], on_line)
    skipped, last = restic_errors(err)
    if skipped:
        raise Problem("failed", f"{count(len(skipped), 'file')} did not come back from the backup of {when(snap['ts'])} "
                      f"({snap['short_id']}); the first: {skipped[0]['path']}: {skipped[0]['why']}")
    if rc != 0:
        raise Problem("failed", f"the restore failed: {last or 'restic failed'}")
    job.step("compare")
    if rows is None:
        # everything: restic's own count of what it wrote against what the backup holds (a file
        # with two names is counted once by both)
        files, total = count_files(tree)
        wrote = hold["summary"].get("bytes_restored")
        if wrote != need:
            raise Problem("failed", f"what came back is {size(wrote)}, and the backup says {size(need)}")
    else:
        for r in rows:
            try:
                got = os.lstat(os.path.join(tree, r["path"].lstrip("/"))).st_size
            except OSError:
                raise Problem("failed", f"{sysp(r['path'])} did not come back")
            if got != r["size"]:
                raise Problem("failed", f"{sysp(r['path'])} came back as {size(got)}, and the backup says {size(r['size'])}")
        files, total = len(rows), need
    job.note(f"{count(files, 'file')} ({size(total)}) match the backup")
    job.step("clean")
    return snap, files, total


def cmd_test(a, b):
    """The test restore: the newest backup's files (a random sample, or all of them) restored
    to a scratch folder and read back against the backup, then removed. How it went is kept
    in backup.json, where the health line and the alert read it."""
    steps = [("find", "Finding the newest backup"), ("pick", "Picking what to restore"), ("space", "Checking free space"),
             ("restore", "Restoring to a scratch folder, then reading each file back"),
             ("compare", "Comparing what came back with the backup's list"), ("clean", "Removing the scratch folder")]
    mode = "all" if a.all else "sample"
    job = Job("test", steps, a.json, quiet=a.quiet, mode=mode)
    started = time.time()
    snap, files, total, reason = None, 0, 0, ""
    # --scratch DIR: a folder of this command's own inside it, so nothing of yours there is touched
    home = os.path.join(os.path.abspath(a.scratch), "bromigos-restore-test") if a.scratch else at(SCRATCH)
    try:
        catch_signals()
        snap, files, total = run_test(a, b, job, home)
    except Stopped as e:
        shutil.rmtree(job.record.get("work") or os.path.join(home, "none"), ignore_errors=True)
        return stopped(job, a, e, "Stopped. The test restore didn't finish, so it doesn't count either way. Its scratch "
                       "folder was removed; nothing on the server changed.")
    except Problem as e:
        reason = e.message
    except OSError as e:
        reason = f"the test restore couldn't run: {e}"
    finally:
        hold_signals()                               # the record of how it went is always written
        if job.record.get("work"):
            shutil.rmtree(job.record["work"], ignore_errors=True)
    rec = {"phase": "failed" if reason else "ok", "at": iso(), "ts": time.time(), "mode": mode, "files": files, "bytes": total,
           "snapshot": job.record.get("snapshot", ""), "seconds": round(time.time() - started, 1), "reason": reason}
    update_state(test=rec, **({} if reason else {"test_ok": rec}))
    job.finish("failed" if reason else "done", **rec)
    release_signals()
    doc = {"schema": SCHEMA, "ok": not reason, "state": "failed" if reason else "passed", "test": rec,
           "snapshot": {k: v for k, v in snap.items() if k != "raw_paths"} if snap else None}
    if reason:
        doc["error"] = {"code": "test-failed", "message": reason}
    if a.json:
        print(json.dumps(doc, indent=1))
    elif reason:
        print(f"\nThe test restore failed: {sentence(reason)}.\nUntil one passes, don't count on this backup to give "
              "your files back. `bromigos lab backups` has the rest, and `bromigos alerts` raises it.", file=sys.stderr)
    elif not a.quiet:
        print(f"\nThe test restore passed: {count(files, 'file')} ({size(total)}) came back from the backup of "
              f"{when(snap['ts'])} ({snap['short_id']}) and match it. "
              + ("That is every file in it." if a.all else "That is a random sample: --all restores everything."))
        print("  The scratch folder was removed. Nothing on the server changed.")
    return 1 if reason else 0


def _loads(line):
    try:
        m = json.loads(line)
    except ValueError:
        return {}
    return m if isinstance(m, dict) else {}


# ------------------------------------------------------------------ the command

USAGE = """bromigos lab backups: this server's backups, and getting files back (docs/server.md, "Backups")

  bromigos lab backups                       are the backups healthy? One plain line, then the details
  bromigos lab backups list                  every backup: when, how big, what's in it
  bromigos lab backups show [ID] [PATH]      look inside one, a folder at a time (no ID: the newest)
  bromigos lab backups restore [ID] [PATH…]  get files back, into a new folder under /srv/restore.
                                             Nothing on the server is replaced. No ID: the newest
      --to DIR                               … into this folder instead (it must be new or empty)
      --in-place                             show what putting them back where they were would
                                             replace. It changes nothing
      --in-place --apply [--yes]             … and do it: a snapshot of the files as they are first,
                                             then the backup's files over them; never a delete
          --plan DIGEST                      only if the list is still the one --in-place showed
          --without-snapshot                 go ahead where no snapshot can be taken
      --no-verify                            don't read each restored file back
  bromigos lab backups test [--all]          a test restore: a random sample (--all: everything)
                                             restored to a scratch folder, read back, removed
      --scratch DIR                          the scratch folder's place (default: bromigOS's state)
  bromigos lab backups run | check [--data]  a backup now | a check now (bromigos server backup …)

Every one takes --json. list, show, restore and test read the backup's key, so they ask for the
administrator's password when you aren't root.
"""


def parser():
    ap = argparse.ArgumentParser(prog="bromigos lab backups", add_help=False)
    ap.add_argument("-h", "--help", action="store_true")
    sub = ap.add_subparsers(dest="verb")
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--json", action="store_true")
    sub.add_parser("status", parents=[common], add_help=False)
    sub.add_parser("list", parents=[common], add_help=False)
    p = sub.add_parser("show", parents=[common], add_help=False)
    p.add_argument("snapshot", nargs="?")
    p.add_argument("path", nargs="?")
    p = sub.add_parser("restore", parents=[common], add_help=False)
    p.add_argument("what", nargs="*", metavar="ID|PATH")
    p.add_argument("--to")
    p.add_argument("--in-place", action="store_true")
    p.add_argument("--apply", action="store_true")
    p.add_argument("--yes", action="store_true")
    p.add_argument("--plan")
    p.add_argument("--without-snapshot", action="store_true")
    p.add_argument("--no-verify", action="store_true")
    p = sub.add_parser("test", parents=[common], add_help=False)
    p.add_argument("--all", action="store_true")
    p.add_argument("--scratch")
    p.add_argument("--quiet", action="store_true")
    p.add_argument("--seed", type=int, help=argparse.SUPPRESS)
    for verb in ("run", "check"):
        p = sub.add_parser(verb, parents=[common], add_help=False)
        p.add_argument("--data", action="store_true")
    return ap


def as_root(argv, reexec, as_json):
    """list, show, restore and test read the backup's key, which is root's: when you aren't
    root, run again through sudo, the way `bromigos server` does. Nothing to type but the
    password."""
    if ROOT != "/" or os.geteuid() == 0:
        return
    sudo = shutil.which("sudo")
    if not sudo or not reexec:
        raise Problem("needs-root", "This reads the backup's key, which only the administrator can: run it as root.", exit=3)
    quiet = [] if sys.stdin.isatty() else ["-n"]
    if quiet and subprocess.run([sudo, "-n", "true"], capture_output=True).returncode != 0:
        raise Problem("needs-root", "This reads the backup's key, which only the administrator can, and there is no "
                      "terminal here to ask for the password. Run it in a terminal, or as root.", exit=3)
    sys.stdout.flush()
    os.execv(sudo, [sudo, *quiet, sys.executable, *reexec, *argv])


def server_command():
    for p in (shutil.which("bromigos-server"), SERVER,
              os.path.join(os.path.dirname(os.path.dirname(os.path.realpath(__file__))), "server", "bromigos-server")):
        if p and os.path.exists(p):
            return p
    return None


def main(argv, reexec=None):
    """`bromigos lab backups …`. reexec is how to run this again as root: the script and the
    words before argv."""
    as_json = "--json" in argv
    try:
        ap = parser()
        if not argv or (argv[0].startswith("-") and argv[0] not in ("-h", "--help")):
            argv = ["status", *argv]                            # `backups --json`
        try:
            a = ap.parse_args(argv)
        except SystemExit as e:
            if e.code:
                print(f"\n{USAGE}", file=sys.stderr)
            return 2 if e.code else 0
        if a.help:
            print(USAGE.strip() if shutil.which("bromigos") else USAGE.strip().replace("bromigos lab", "bromigos-lab"))
            return 0
        verb = a.verb or "status"
        if verb == "status":
            d = status_doc()
            if as_json:
                print(json.dumps(d, indent=1))
            elif not d["server"]:
                print(d["error"]["message"], file=sys.stderr)
            else:
                print_status(d)
            return 3 if not d["server"] else 0 if d["ok"] else 1
        if not is_server():
            raise Problem("not-a-server", status_doc()["error"]["message"], exit=3)
        if verb in ("run", "check"):
            exe = server_command()
            if not exe:
                raise Problem("not-a-server", "bromigos-server isn't installed here.", exit=3)
            cmd = [sys.executable, "-I", exe, "backup", verb, *(["--data"] if a.data else [])]
            if not as_json:
                sys.stdout.flush()
                os.execv(sys.executable, cmd)
            r = subprocess.run(cmd, capture_output=True, text=True)
            print(json.dumps(dict(status_doc(), ok=r.returncode == 0, ran=verb, exit=r.returncode,
                                  said=(r.stderr.strip() or r.stdout.strip()).splitlines()[-1:]), indent=1))
            return r.returncode
        b = settings()
        if not b["to"]:
            raise Problem("off", "Backups are off, so there is nothing to restore from: no destination is set "
                          "([backup] to in /etc/bromigos/server.toml).", exit=3)
        as_root(argv, reexec, as_json)
        return {"list": cmd_list, "show": cmd_show, "restore": cmd_restore, "test": cmd_test}[verb](a, b)
    except Problem as e:
        if as_json:
            print(json.dumps({"schema": SCHEMA, "ok": False, "error": dict(e.more, code=e.code, message=e.message)}, indent=1))
        else:
            print(e.message, file=sys.stderr)
        return e.exit
    except BrokenPipeError:
        raise
    except OSError as e:                                        # a full disk, a folder that can't be written
        if as_json:
            print(json.dumps({"schema": SCHEMA, "ok": False, "error": {"code": "failed", "message": f"It stopped: {e}."}}, indent=1))
        else:
            print(f"It stopped: {e}.", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:], [os.path.realpath(__file__)]))
