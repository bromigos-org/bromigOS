"""The apps' databases made safe for a backup, and the lab's own nightly backup on a machine that
isn't a bromigOS Server (docs/server.md, "Backups"; docs/lab-provision.md, "Where the data goes").

    bromigos lab backups copy-databases [--json]   every hook's databases, copied whole
    bromigos lab backups job PATH… [--json]        the lab's own backup, start to finish
    bromigos lab backups holds [PATH…] [--json]    does the newest backup hold these?

This module is bromigos-lab's and needs nothing of bromigos-core's: the hooks are written by the
lab's engine (localprovision.py, DATABASES), and a machine with only bromigos-lab runs the job.
bromigOS Server's own backup and the Go Bag (bromigos-core's lib/bromigos_backups.py) call
copy_databases() here, so all three make the same copies.

A hook is /etc/bromigos/backup-databases.d/<app>.toml:

    what = "shows (Sonarr)"                         the app, as a person knows it
    sqlite = ["/srv/apps/sonarr/config/*.db"]       SQLite databases; a * matches inside one folder.
                                                    Each one that is there is copied with SQLite's
                                                    online backup (whole and consistent while the app
                                                    writes, its write-ahead log included), checked,
                                                    and kept in /var/lib/bromigos/backup-databases/<app>/
    own = ["/srv/apps/photos/library/backups/*"]    the app's own database backups: files the app
    own_days = 3                                    writes, which the backup holds as they are. The
                                                    newest must be this young, or the hook says so

The job (bromigos-lab-backup.service runs it, with RESTIC_REPOSITORY and RESTIC_PASSWORD_FILE):
the databases copied, restic over the paths that are there (--one-file-system, so each disk is
named by itself), a look into the new backup for the apps' folders, then the keep rules. How it
went is /var/lib/bromigos/lab/backup.json, in the shape of the Server's backup.json (`run`,
`run_ok`), which `bromigos alerts` reads: a failed or late backup is raised there.

BROMIGOS_SERVER_ROOT (or BROMIGOS_ROOT) puts every path under a stand-in root, for the tests.
"""
import argparse
import contextlib
import datetime
import glob
import json
import os
import pathlib
import shutil
import sqlite3
import subprocess
import sys
import time
import tomllib

ROOT = os.environ.get("BROMIGOS_SERVER_ROOT") or os.environ.get("BROMIGOS_ROOT") or "/"
HOOKS = "/etc/bromigos/backup-databases.d"
COPIES = "/var/lib/bromigos/backup-databases"
APPS = "/srv/apps"
FSTAB = "/etc/fstab"
STATE = "/var/lib/bromigos/lab/backup.json"
UNIT = "bromigos-lab-backup.service"
TAG = "bromigos-lab"
OWN_DAYS = 3                 # how old an app's own newest database backup may be, unless its hook says
MARGIN = 64 << 20            # free space left beside a copy
DAY = 86400


def at(path):
    return os.path.join(ROOT, path.lstrip("/"))


def sysp(path, root=None):
    """A path as the machine knows it: the stand-in root taken off."""
    root = (ROOT if root is None else root).rstrip("/")
    return (path[len(root):] or "/") if root and (path == root or path.startswith(root + "/")) else path


def iso(ts=None):
    t = datetime.datetime.fromtimestamp(time.time() if ts is None else ts, datetime.timezone.utc)
    return t.astimezone().isoformat(timespec="seconds")


def one_line(text, n=200):
    return " ".join(str(text).split())[:n]


# ------------------------------------------------------------------ the databases

def copy_databases(at=at, now=None):
    """Every hook's databases, made safe for the backup that follows. One row for each database
    tried, {"name", "what", "path", "ok", "reason"}, and one for an app's own backups ("own":
    true). A database that isn't there (an app not used yet) is skipped, and so is an app that
    hasn't had the time to make its first own backup."""
    now = time.time() if now is None else now
    try:
        names = sorted(n for n in os.listdir(at(HOOKS)) if n.endswith(".toml"))
    except OSError:
        names = []
    out = []
    for n in names:
        name, path = n[:-len(".toml")], os.path.join(at(HOOKS), n)
        try:
            with open(path, "rb") as f:
                hook = tomllib.load(f)
            written = os.stat(path).st_mtime
        except (OSError, tomllib.TOMLDecodeError) as e:
            out.append({"name": name, "what": name, "path": f"{HOOKS}/{n}", "ok": False,
                        "reason": f"{HOOKS}/{n} can't be read ({one_line(e)})"})
            continue
        what = str(hook.get("what") or name)
        used = set()
        for pattern in _strings(hook.get("sqlite")):
            for src in _matches(at(pattern)):
                shown = sysp(src, at("/"))
                copy = os.path.basename(src)
                if copy in used:                     # two folders, one file name: the folder's name in front
                    copy = os.path.basename(os.path.dirname(src)) + "-" + copy
                used.add(copy)
                row = {"name": name, "what": what, "path": shown, "ok": True, "reason": ""}
                try:
                    sqlite_copy(src, os.path.join(at(COPIES), name, copy))
                except (sqlite3.Error, OSError) as e:
                    row.update(ok=False, reason=f"{shown} couldn't be copied: {one_line(e)}")
                out.append(row)
        own = _strings(hook.get("own"))
        if own:
            days = hook.get("own_days")
            days = days if isinstance(days, (int, float)) and not isinstance(days, bool) and days > 0 else OWN_DAYS
            stamps = []
            for pattern in own:
                for p in _matches(at(pattern)):
                    with contextlib.suppress(OSError):
                        stamps.append(os.stat(p).st_mtime)
            row = {"name": name, "what": what, "path": own[0], "ok": True, "reason": "", "own": True}
            if stamps and now - max(stamps) <= days * DAY:
                out.append(row)
            elif stamps:
                out.append(dict(row, ok=False, reason=f"its own newest database backup ({own[0]}) is "
                                f"{int((now - max(stamps)) // DAY)} days old: its own backup may be turned off"))
            elif now - written > days * DAY:
                out.append(dict(row, ok=False, reason=f"it has made no database backup of its own ({own[0]}): its own "
                                "backup may be turned off"))
            # else: set up less than `days` ago and none made yet: nothing to say
    return out


def _strings(value):
    return [v for v in value if isinstance(v, str) and v.startswith("/")] if isinstance(value, list) else []


def _matches(pattern):
    """The files a hook's path names: the path itself, or with a * what it matches."""
    found = sorted(glob.glob(pattern)) if glob.has_magic(pattern) else [pattern]
    return [p for p in found if os.path.isfile(p) and not os.path.islink(p)]


def sqlite_copy(src, dst):
    """One SQLite database copied with its own online backup: a whole, consistent copy while
    the app goes on writing (its journal or write-ahead log included), never a file read
    half-way through a write. Root's alone (0600, in a 0700 folder). Refused, with nothing
    written, when the copy wouldn't fit."""
    os.makedirs(os.path.dirname(os.path.dirname(dst)), mode=0o700, exist_ok=True)
    os.makedirs(os.path.dirname(dst), mode=0o700, exist_ok=True)
    need = sum(os.path.getsize(p) for p in (src, src + "-wal") if os.path.exists(p))
    free = shutil.disk_usage(os.path.dirname(dst)).free
    if need + MARGIN > free:
        raise OSError(f"no room for the copy in {COPIES} (it needs {need >> 20} MiB, and {free >> 20} MiB are free)")
    tmp = dst + ".partial"
    with contextlib.suppress(FileNotFoundError):
        os.unlink(tmp)
    source = sqlite3.connect(pathlib.Path(src).as_uri() + "?mode=ro", uri=True, timeout=60)
    try:
        copy = sqlite3.connect(tmp)
        try:
            source.backup(copy)
            # the copy's own journal mode: one file, whatever the app's is
            copy.execute("PRAGMA journal_mode=DELETE")
            verdict = copy.execute("PRAGMA quick_check").fetchone()[0]
        finally:
            copy.close()
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(tmp)
        raise
    finally:
        source.close()
    if verdict != "ok":
        os.unlink(tmp)
        raise sqlite3.DatabaseError(f"the copy doesn't check out: {one_line(verdict)}")
    os.chmod(tmp, 0o600)
    os.replace(tmp, dst)


def failed_words(rows):
    """Each row that isn't ok, as a sentence for a person."""
    return [f"{r.get('what') or r.get('name')}: {r.get('reason') or 'it failed'}" for r in rows if not r.get("ok")]


# ------------------------------------------------------------------ what a backup must hold

def required(at=at):
    """What a backup made now must hold: the apps' folder, each app's own folder in it, and the
    databases' copies. Each one that is on this machine. (bromigos_backups.required_now() is
    the Server's, with its [backup] exclude; tests keep the two the same.)"""
    out = []
    if os.path.isdir(at(APPS)):
        out.append(APPS)
        try:
            names = sorted(os.listdir(at(APPS)))
        except OSError:
            names = []
        for n in names:
            p = os.path.join(at(APPS), n)
            if not n.startswith(".") and os.path.isdir(p) and not os.path.islink(p):
                out.append(f"{APPS}/{n}")
    if os.path.isdir(at(COPIES)):
        out.append(COPIES)
    return out


def away(at=at):
    """Is the apps' folder one /etc/fstab mounts, and not mounted now (the data disks are away)?
    The folder there is the system disk's, empty: a backup of it would say the apps have no data."""
    try:
        with open(at(FSTAB)) as f:
            rows = {r[1] for r in (line.split() for line in f if not line.lstrip().startswith("#")) if len(r) > 1}
    except OSError:
        rows = set()
    return APPS in rows and not os.path.ismount(at(APPS))


def restic(args, timeout=12 * 3600):
    try:
        r = subprocess.run(["restic", *args], capture_output=True, text=True, timeout=timeout, stdin=subprocess.DEVNULL)
        return r.returncode, r.stdout, r.stderr
    except FileNotFoundError:
        return 127, "", "restic isn't installed"
    except subprocess.TimeoutExpired:
        return 124, "", "restic timed out"


def missing(snap, paths):
    """Which of these paths the backup doesn't hold (None: its list couldn't be read). A
    folder and what is right inside it are listed together."""
    if not paths:
        return []
    tops = [p for p in paths if os.path.dirname(p) not in paths]
    rc, out, _ = restic(["ls", "--json", "--retry-lock", "2m", snap, *[at(p) for p in tops]], timeout=1800)
    if rc != 0:
        return None
    have = set()
    for line in out.splitlines():
        with contextlib.suppress(ValueError, AttributeError):
            have.add(sysp(json.loads(line).get("path") or ""))
    return [p for p in paths if p not in have]


def what(path):
    """A required path, in words (bromigos_backups.what() says the same)."""
    if path == APPS:
        return "the apps' data"
    if path == COPIES:
        return "the apps' database copies"
    return f"the {os.path.basename(path)} app's data" if os.path.dirname(path) == APPS else "files"


def words(paths):
    """The paths a backup lacks, in words: a folder that is missing whole says it for what is in it."""
    tops = [p for p in paths if os.path.dirname(p) not in paths]
    return " and ".join(f"{p} ({what(p)})" for p in tops)


# ------------------------------------------------------------------ the record

def read_state():
    try:
        with open(at(STATE)) as f:
            doc = json.load(f)
    except (OSError, ValueError):
        return {}
    return doc if isinstance(doc, dict) else {}


def write_state(**records):
    st = read_state()
    st.update(records)
    os.makedirs(os.path.dirname(at(STATE)), mode=0o755, exist_ok=True)
    tmp = f"{at(STATE)}.tmp.{os.getpid()}"
    with open(tmp, "w") as f:
        json.dump(st, f, indent=1, sort_keys=True)
        f.write("\n")
    os.chmod(tmp, 0o644)                             # no key and no address in it: the alerts' pass reads it
    os.replace(tmp, at(STATE))
    return st


def last_line(err, fallback):
    """restic's reason: its last line, or the message of its --json exit_error."""
    line = (err.strip().splitlines() or [fallback])[-1]
    with contextlib.suppress(ValueError, AttributeError):
        line = (str(json.loads(line).get("message") or "").strip().splitlines() or [fallback])[0]
    return one_line(line, 300) or fallback


# ------------------------------------------------------------------ the job

def job(paths, keep=(7, 4, 6), say=print):
    """The lab's own backup, start to finish; 0 when the backup is good. Always leaves a record."""
    def failed(reason, **more):
        write_state(run=dict({"phase": "failed", "at": iso(), "ts": time.time(), "reason": reason}, **more))
        print(f"bromigos-lab: the backup failed: {reason}", file=sys.stderr)
        return 1

    if not os.environ.get("RESTIC_REPOSITORY"):
        print("bromigos-lab: backups job reads the backup named by RESTIC_REPOSITORY (with RESTIC_PASSWORD_FILE): "
              f"it is {UNIT}'s own command.", file=sys.stderr)
        return 2
    if away():
        return failed(f"the data disks aren't mounted, so {APPS} (the apps' data) can't be read. Nothing was backed up")
    rc, _, err = restic(["cat", "config"], timeout=600)
    if rc == 10 or (rc != 0 and "does not exist" in err):
        rc, _, err = restic(["init"], timeout=600)
        if rc != 0:
            return failed(f"the destination couldn't be set up: {last_line(err, 'restic init failed')}")
    elif rc != 0:
        return failed(f"the destination can't be reached: {last_line(err, 'restic failed')}")
    dbs = copy_databases()
    saw = required()
    # --one-file-system keeps restic on the disk each path is on (the data disks aren't read
    # twice, and a repository under /srv/backups isn't backed up into itself), so every folder
    # on a disk of its own is a path here. One that isn't there is left out: restic fails a run
    # that names it
    targets = [at(p) for p in dict.fromkeys(paths) if os.path.exists(at(p))]
    rc, out, err = restic(["backup", "--json", "--tag", TAG, "--one-file-system", "--exclude-caches", *targets])
    summary = {}
    for line in out.splitlines():
        with contextlib.suppress(ValueError, AttributeError):
            m = json.loads(line)
            if m.get("message_type") == "summary":
                summary = m
    # 3: some files couldn't be read, the rest was backed up
    if rc not in (0, 3) or not summary:
        return failed(last_line(err, "restic backup failed"), databases=dbs)
    snap = str(summary.get("snapshot_id") or "")
    gone = missing(snap, saw)
    if gone or gone is None:
        return failed(f"the backup left out {words(gone)}" if gone else "what the backup holds couldn't be read back",
                      snapshot=snap[:8], missing=gone or [], databases=dbs, saw=saw)
    restic(["forget", "--keep-daily", str(keep[0]), "--keep-weekly", str(keep[1]), "--keep-monthly", str(keep[2]), "--prune"])
    run = {"phase": "ok" if rc == 0 else "partial", "at": iso(), "ts": time.time(), "snapshot": snap[:8],
           "files": summary.get("total_files_processed"), "bytes": summary.get("total_bytes_processed"),
           "added": summary.get("data_added"), "databases": dbs, "saw": saw,
           "reason": "" if rc == 0 else "some files couldn't be read: " + last_line(err, "")}
    st = read_state()
    write_state(run=run, run_ok=run, **({} if st.get("first_ok_ts") else {"first_ok_ts": run["ts"]}))
    say(f"bromigos-lab: backed up ({run['snapshot']})")
    bad = failed_words(dbs)
    for line in bad:
        print(f"bromigos-lab: {line}", file=sys.stderr)
    return 1 if bad else 0


# ------------------------------------------------------------------ the commands

def cmd_copy_databases(a):
    rows = copy_databases()
    bad = [r for r in rows if not r["ok"]]
    if a.json:
        print(json.dumps({"schema": 1, "ok": not bad, "databases": rows}, indent=1))
    else:
        for r in rows:
            if r["ok"]:
                print(f"{r['what']}: " + ("its own backup is recent" if r.get("own") else f"{r['path']} copied"))
            else:
                print(f"{r['what']}: {r['reason']}", file=sys.stderr)
    return 1 if bad else 0


def cmd_holds(a):
    if not os.environ.get("RESTIC_REPOSITORY"):
        print("holds reads the backup named by RESTIC_REPOSITORY (with RESTIC_PASSWORD_FILE): it's for a backup "
              "job's own unit.", file=sys.stderr)
        return 2
    bad = [p for p in a.paths if not p.startswith("/")]
    if bad:
        print(f"{bad[0]}: give the full path, such as {APPS}.", file=sys.stderr)
        return 2
    paths = [os.path.normpath(p) for p in a.paths] or required()
    gone = missing("latest", paths)
    if a.json:
        print(json.dumps({"schema": 1, "ok": gone == [], "paths": paths, "missing": gone}, indent=1))
    elif gone is None:
        print("What the newest backup holds couldn't be read.", file=sys.stderr)
    elif gone:
        print(f"The newest backup doesn't hold {words(gone)}, on this computer now.", file=sys.stderr)
    return 0 if gone == [] else 1


VERBS = ("copy-databases", "holds", "job")


def main(argv):
    ap = argparse.ArgumentParser(prog="bromigos lab backups", add_help=False)
    sub = ap.add_subparsers(dest="verb", required=True)
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--json", action="store_true")
    sub.add_parser("copy-databases", parents=[common], add_help=False)
    for verb in ("holds", "job"):
        p = sub.add_parser(verb, parents=[common], add_help=False)
        p.add_argument("paths", nargs="*")
    try:
        a = ap.parse_args(argv)
    except SystemExit as e:
        return 2 if e.code else 0
    if a.verb == "copy-databases":
        return cmd_copy_databases(a)
    if a.verb == "holds":
        return cmd_holds(a)
    if not a.paths:
        print("bromigos lab backups job PATH…: the folders to back up.", file=sys.stderr)
        return 2
    code = job(a.paths, say=(lambda line: None) if a.json else print)
    if a.json:
        st = read_state()
        print(json.dumps({"schema": 1, "ok": code == 0, "run": st.get("run"), "run_ok": st.get("run_ok")}, indent=1))
    return code
