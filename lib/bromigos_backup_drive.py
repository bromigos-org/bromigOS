"""The Go Bag: bromigOS Server's backup on a USB drive you unplug and keep somewhere else
(docs/server.md, "The Go Bag").

  bromigos lab backups go-bag [status] [--json]   which drive, plugged in or not, its last good copy
  bromigos lab backups go-bag drives [--json]     the drives that could be one, and why not the others
  bromigos lab backups go-bag setup [DRIVE]       make DRIVE the Go Bag, then copy to it
      --erase                                     format it first (ext4): everything on it is deleted
      --internal                                  use a drive that isn't removable
      --yes                                       don't ask (scripts)
      --no-copy                                   set it up only
  bromigos lab backups go-bag run                 copy to it now (it must be plugged in)
  bromigos lab backups go-bag forget [--yes]      stop using the drive; what's on it is left alone
  bromigos lab backups list | show | restore | test --from go-bag
                                                  the restore commands, reading the drive

The name is in one place: NAME and VERB below. Everything a rename would otherwise break says
"backup drive": this module, the unit (bromigos-server-backup-drive@.service), the udev rule,
backup.json's `drives`, `--json`'s `drives`, [backup] drive_remind_days, the mount point, the
folder on the drive and the activity kind.

One more destination of the same backup. The drive holds a restic repository of its own, in
bromigos-backup/<hostname>, opened by the server's backup key and filled by `restic backup`
with the nightly backup's paths, excludes, tag and keep rules. So every restore command reads
it, it works where there is no nightly destination, and it never inherits the other's damage.

A drive is remembered by its filesystem's UUID, in backup.json's `drives`, and found again
each time from lsblk. No /dev/sdX name is ever stored.

Plugged in: the udev rule (65-bromigos-server-backup-drive.rules) starts the unit, which runs
`bromigos-server backup plugged --uuid UUID`: plugged() here. For the Go Bag it starts the copy
as an activity job (`bromigos activity run`, lib/bromigos_activity.py), whose body is
`bromigos-server backup drive-copy`: copy() here, with four named steps that end in "Safe to
unplug".

What touches a drive (lsblk, mount, umount, sync, wipefs, mkfs.ext4, udevadm) is the real
command on a real server. In a stand-in root (BROMIGOS_SERVER_ROOT, the tests) it is only the
stand-in named by BROMIGOS_BACKUPS_<TOOL> (BROMIGOS_BACKUPS_MKFS_EXT4), never the command of
the machine the tests run on.

Exit codes, as bromigos lab backups: 0 done; 1 it failed, or the Go Bag needs you; 2 the
command line; 3 refused (it needs a yes, the drive isn't one it may use, this isn't a Server);
130 stopped part-way.
"""

import argparse
import contextlib
import fcntl
import json
import os
import re
import shutil
import subprocess
import sys
import time

import bromigos_backups as B

NAME = "Go Bag"                                  # the feature's name, for people: change it here
VERB = "go-bag"                                  # … and its word on the command line
FLAG = f" --from {VERB}"                         # what a hint adds to a restore command that reads the drive
LABEL = (re.sub(r"[^A-Za-z0-9]", "", NAME).upper() or "BACKUP")[:16]     # a formatted drive's label

KIND = "backup.drive"                            # the activity record's kind
JOB_LOCK = "backup-drive"                        # … and its lock (`bromigos activity run --lock`)
MOUNTS = "/run/bromigos/backup-drive"            # /run/bromigos/backup-drive/<UUID>
FOLDER = "bromigos-backup"                       # on the drive: bromigos-backup/<hostname> is the repository
LOCK = "/var/lib/bromigos/server/backup-drive.lock"
ACTIVITY = "/usr/lib/bromigos/bin/bromigos-activity"
REMIND_DAYS = 30                                 # [backup] drive_remind_days
READ_BACK = "2G"                                 # how much of the drive's data a copy's check reads back
DAY = 86400
# filesystems the server writes without a helper. NTFS isn't one: the kernel's driver refuses a
# drive Windows didn't close cleanly
WRITABLE = ("ext4", "ext3", "ext2", "btrfs", "xfs", "f2fs", "exfat", "vfat")
OWNERLESS = ("exfat", "vfat")                    # no owners on the disk: mounted as root's, closed to others
# what an operating system leaves on a drive: never "files of yours"
LEFT_BY_SYSTEMS = ("lost+found", "System Volume Information", "$RECYCLE.BIN", ".Trashes", ".Spotlight-V100",
                   ".fseventsd", ".TemporaryItems", FOLDER)
STEPS = [("drive", f"Finding the {NAME} drive"), ("copy", "Copying what changed"),
         ("check", "Checking what was written"), ("unplug", "Making it safe to unplug")]


# ------------------------------------------------------------------ the commands that touch a drive

def tool(name):
    """A command that touches drives: the real one on a real server, and in a stand-in root
    only the stand-in BROMIGOS_BACKUPS_<NAME> names. None when there is none."""
    if B.ROOT == "/":
        return name
    return os.environ.get("BROMIGOS_BACKUPS_" + re.sub(r"[^A-Z0-9]", "_", name.upper())) or None


def call(name, *args, timeout=600):
    """(exit code, stdout, stderr). A missing command is 127."""
    exe = tool(name)
    if not exe:
        raise B.Problem("stand-in", f"In a stand-in root {name} is never run.", exit=3)
    try:
        r = subprocess.run([exe, *args], capture_output=True, text=True, timeout=timeout, stdin=subprocess.DEVNULL)
    except FileNotFoundError:
        return 127, "", f"{name}: not installed"
    except subprocess.TimeoutExpired:
        return 124, "", f"{name}: timed out"
    return r.returncode, r.stdout, r.stderr


def last_words(*texts):
    for t in texts:
        lines = [x.strip() for x in (t or "").splitlines() if x.strip()]
        if lines:
            return lines[-1][:300]
    return ""


def flag(v):
    """lsblk's true/false, which older ones print as "1"/"0"."""
    return v is True or v == 1 or str(v).strip().lower() in ("1", "true")


def blocks():
    """The server's disks as lsblk sees them now: [{"path", "name", "size", "model", "tran",
    "removable", "ro", "fstype", "label", "uuid", "mountpoints", "nodes": [each partition and
    whatever is inside one, flattened]}]. Sizes in bytes."""
    rc, out, err = call("lsblk", "--json", "--bytes", "--output",
                        "NAME,PATH,TYPE,SIZE,RO,RM,HOTPLUG,TRAN,FSTYPE,LABEL,UUID,MOUNTPOINTS,MODEL,VENDOR", timeout=60)
    try:
        tops = json.loads(out).get("blockdevices") if rc == 0 else None
    except (ValueError, AttributeError):
        tops = None
    if not isinstance(tops, list):
        raise B.Problem("failed", f"The server's drives couldn't be listed: {last_words(err) or 'lsblk failed'}.")

    def node(n, parent):
        return {"path": n.get("path") or "", "name": n.get("name") or "", "type": n.get("type") or "",
                "size": n.get("size") if isinstance(n.get("size"), int) else 0, "fstype": n.get("fstype") or "",
                "label": n.get("label") or "", "uuid": n.get("uuid") or "", "ro": flag(n.get("ro")), "parent": parent,
                "mountpoints": [m for m in (n.get("mountpoints") or []) if m]}

    def under(n, parent, into):
        for c in n.get("children") or []:
            if isinstance(c, dict):
                into.append(node(c, parent))
                under(c, c.get("path") or "", into)

    disks = []
    for t in tops:
        if not isinstance(t, dict) or t.get("type") != "disk":
            continue                                  # loop devices, optical drives, RAM disks
        d = node(t, "")
        d.update(model=" ".join(f"{t.get('vendor') or ''} {t.get('model') or ''}".split()), tran=(t.get("tran") or "").lower(),
                 removable=flag(t.get("rm")) or flag(t.get("hotplug")) or (t.get("tran") or "").lower() == "usb", nodes=[])
        under(t, d["path"], d["nodes"])
        disks.append(d)
    return disks


def find(uuid, disks=None):
    """(the disk, the node) whose filesystem has this UUID, or (None, None): not plugged in."""
    for d in blocks() if disks is None else disks:
        for n in [d, *d["nodes"]]:
            if n["uuid"] and n["uuid"] == uuid:
                return d, n
    return None, None


def describe(d, n=None):
    """A drive for people: "Portable SSD (1.0 TB)"."""
    words = f"{d.get('model') or 'a drive with no name'} ({B.size(d.get('size'))})"
    label = (n or d).get("label")
    return words + (f', labelled "{label}"' if label else "")


def in_use(d):
    """Why this drive must never be touched: it holds part of the running system. "" when it
    doesn't. Our own mount point (a copy that was killed) doesn't count."""
    ours = B.at(MOUNTS).rstrip("/") + "/"
    for n in [d, *d["nodes"]]:
        for m in n["mountpoints"]:
            if m == "[SWAP]":
                return f"{n['path']} is this server's swap space"
            if not m.startswith(ours):
                return f"{n['path']} is mounted at {B.sysp(m)}"
        if n["type"] in ("crypt", "lvm", "raid0", "raid1", "raid5", "raid6", "raid10", "mpath"):
            return f"{n['path']} is open as {n['type']} ({n['parent']})"
    return ""


def hostname():
    """The server's name, for the folder on the drive."""
    try:
        with open(B.at("/etc/hostname")) as f:
            name = f.read().strip()
    except OSError:
        name = ""
    if not name:
        import socket
        name = socket.gethostname()
    return re.sub(r"[^A-Za-z0-9._-]", "-", name).strip(".-") or "server"


class Mount:
    """The drive's filesystem, mounted for one job at /run/bromigos/backup-drive/<UUID>. A
    drive someone mounted themselves is used where it is, and left there."""

    def __init__(self, disk, node):
        self.disk, self.node, self.uuid = disk, node, node["uuid"]
        self.point = B.at(f"{MOUNTS}/{self.uuid}")
        self.where, self.ours = None, False

    @classmethod
    def of(cls, uuid):
        d, n = find(uuid)
        if not n:
            raise B.Problem("unplugged", f"The {NAME} drive isn't plugged in. Plug it in, then try again.")
        return cls(d, n)

    def mount(self):
        there = [m for m in self.node["mountpoints"] if m != "[SWAP]"]
        if there:
            self.where, self.ours = there[0], there[0] == self.point        # ours: a copy that was killed left it
            return self
        if self.node["fstype"] not in WRITABLE:
            raise B.Problem("failed", f"The drive's filesystem ({self.node['fstype'] or 'none'}) isn't one this "
                            f"server writes. Set it up again: bromigos lab backups {VERB} setup --erase")
        os.makedirs(self.point, mode=0o700, exist_ok=True)
        options = "rw,nosuid,nodev,noexec" + (",uid=0,gid=0,umask=077" if self.node["fstype"] in OWNERLESS else "")
        rc, out, err = call("mount", "-o", options, f"UUID={self.uuid}", self.point)
        if rc != 0:
            with contextlib.suppress(OSError):
                os.rmdir(self.point)
            raise B.Problem("failed", f"The {NAME} drive couldn't be mounted: {last_words(err, out) or 'mount failed'}.")
        self.where, self.ours = self.point, True
        return self

    def folder(self):
        """The repository's folder on the drive, as it is on this machine."""
        return os.path.join(self.where, FOLDER, hostname())

    def to(self):
        """… and as [backup] to would name it."""
        return B.sysp(self.folder())

    def unmount(self):
        """(True, "") unmounted, and looked: safe to unplug. (None, where) left mounted, since
        someone else mounted it. (False, why) it couldn't be unmounted."""
        if not self.where:
            return True, ""
        if not self.ours:
            with contextlib.suppress(B.Problem):
                call("sync", "-f", self.where)
            return None, B.sysp(self.where)
        why = ""
        for wait in (0, 2, 5):
            time.sleep(wait if B.ROOT == "/" else 0)
            rc, out, err = call("umount", self.point)
            why = last_words(err, out) or "umount failed"
            if rc == 0:
                break
        _, n = find(self.uuid)
        if n and self.point in n["mountpoints"]:
            return False, why
        with contextlib.suppress(OSError):
            os.rmdir(self.point)
        self.where = None
        return True, ""


@contextlib.contextmanager
def lock(wait=False):
    """One job on the backup drive at a time: a copy, a setup, a restore from it."""
    path = B.at(LOCK)
    os.makedirs(os.path.dirname(path), mode=0o755, exist_ok=True)
    with open(path, "a") as held:
        with contextlib.suppress(OSError):
            os.chmod(path, 0o644)                    # the status looks at it without being root
        try:
            fcntl.flock(held, fcntl.LOCK_EX | (0 if wait else fcntl.LOCK_NB))
        except OSError:
            raise B.Problem("busy", f"The {NAME} drive is in use by another job (a copy, or a restore from it). Try "
                            "again when that has finished: `bromigos activity` shows it.")
        yield


def running():
    """Is a job using the backup drive now? (No root needed.)"""
    try:
        with open(B.at(LOCK)) as f:
            try:
                fcntl.flock(f, fcntl.LOCK_SH | fcntl.LOCK_NB)
            except OSError:
                return True
    except OSError:
        pass
    return False


# ------------------------------------------------------------------ what is remembered

def remembered(st=None):
    """{uuid: record}: backup.json's drives."""
    st = B.read_json(B.STATE) if st is None else st
    drives = st.get("drives") if isinstance(st, dict) else None
    return {u: d for u, d in drives.items() if isinstance(d, dict) and u} if isinstance(drives, dict) else {}


def update_drive(uuid, **records):
    """Merge records into one drive's entry (None removes a key), under backup.json's lock."""
    def change(st):
        drives = st["drives"] if isinstance(st.get("drives"), dict) else {}
        d = dict(drives.get(uuid) or {})
        for k, v in records.items():
            if v is None:
                d.pop(k, None)
            else:
                d[k] = v
        drives[uuid] = d
        st["drives"] = drives
    B.change_state(change)


def forget_drive(uuid):
    def change(st):
        if isinstance(st.get("drives"), dict):
            st["drives"].pop(uuid, None)
            if not st["drives"]:
                del st["drives"]
    B.change_state(change)


def which(uuid=None):
    """(uuid, record) of the drive a command means: the one named, or the only one."""
    drives = remembered()
    if uuid:
        if uuid not in drives:
            raise B.Problem("not-set-up", f"That drive isn't this server's {NAME}.", exit=3)
        return uuid, drives[uuid]
    if not drives:
        raise B.Problem("not-set-up", f"No {NAME} drive is set up yet. Plug a USB drive in and run: bromigos lab "
                        f"backups {VERB} setup", exit=3)
    return next(iter(drives.items()))


def days(backup):
    """[backup] drive_remind_days: remind when the drive has had no good copy for this many
    days. 0 never reminds. Anything that isn't a number is the default."""
    v = backup.get("drive_remind_days", REMIND_DAYS) if isinstance(backup, dict) else REMIND_DAYS
    return v if isinstance(v, int) and not isinstance(v, bool) and v >= 0 else REMIND_DAYS


# ------------------------------------------------------------------ the verdict's part

# a copy's phases, as people read them; "stopped" is a copy someone stopped (not a failure)
PHASES = {"ok": "worked", "partial": "worked, but left some files out", "failed": "failed", "stopped": "stopped before it finished"}

def view(st, now, remind_days=REMIND_DAYS, real=None, busy=False):
    """Each remembered drive, for the status and for health(): its identity, whether it is
    plugged in (the kernel's /dev/disk/by-uuid link is there), the last copy and the last
    good one with their ages, and whether a reminder is due. Reads nothing but that link.
    real: how a path of the server is reached (a stand-in root)."""
    real = real or B.at
    rows = []
    for uuid, d in sorted(remembered(st).items(), key=lambda kv: str(kv[1].get("added_at") or "")):
        run = d.get("run") if isinstance(d.get("run"), dict) and d["run"].get("phase") in PHASES else None
        last = B._last(run, now) if run else None
        good = B._last(d.get("run_ok"), now, True)
        tst = d.get("test") if isinstance(d.get("test"), dict) and d["test"].get("phase") in ("ok", "failed") else None
        try:
            plugged = os.path.lexists(real(f"/dev/disk/by-uuid/{uuid}"))
        except OSError:
            plugged = None
        since = good["ts"] if good else d.get("added_ts")
        since = since if isinstance(since, (int, float)) and not isinstance(since, bool) else None
        late = now - since if since is not None and remind_days and now - since > remind_days * DAY else None
        rows.append({"name": NAME, "uuid": uuid, "label": str(d.get("label") or ""), "model": str(d.get("model") or ""),
                     "size": d.get("size") if isinstance(d.get("size"), int) else None, "fstype": str(d.get("fstype") or ""),
                     "added_at": d.get("added_at"), "plugged_in": plugged, "running": bool(busy and plugged),
                     "last_copy": last, "last_good_copy": good, "last_test": B._last(tst, now) if tst else None,
                     "remind_days": remind_days, "stale": late is not None, "stale_s": int(late) if late is not None else None})
    return rows


def judge(rows, now):
    """What health() says about the backup drive: (problems, a sentence for the verdict).

    A copy that failed is a problem here, so the verdict and --json say it. Its alert is the
    copy job's own (`bromigos alerts`' activity.job, which every failed job raises and its next
    success clears), so the problem says `raised_by` and the backup.restic check leaves it out:
    one failure, one alert."""
    problems, said = [], []
    look = [f"bromigos lab backups {VERB}", "bromigos activity"]
    go = f"bromigos lab backups {VERB} run"
    touches = [f"copies the backup to the {NAME} drive, then unmounts it"]
    for r in rows:
        last, good = r["last_copy"], r["last_good_copy"]
        failed = bool(last and last["phase"] == "failed")
        if failed:
            why = B.sentence(last.get("reason")) or "the copy did not finish"
            problems.append(dict(B._problem(
                "drive-failed", "server-drive-copy", "needs_you", f"The last copy to your {NAME} drive failed",
                f"{B.upper_first(why)}. " + (f"The last good copy was {B.ago(good['ts'], now)}." if good else "It has no good copy yet.")
                + " Plug the drive in again to try once more, or with it plugged in run the copy by hand.",
                look + [go], touches), raised_by="activity.job"))
            said.append(f"The last copy to your {NAME} drive failed ({B.ago(last['ts'], now)}): {why}.")
        if r["stale"]:
            title = f"Your {NAME} drive hasn't been updated in {r['stale_s'] // DAY} days"
            if r["plugged_in"]:
                do, short = ("It is plugged in, and a copy starts only when the drive is plugged in. Unplug it and plug "
                             "it back in, or run the copy by hand."), "Unplug it and plug it back in."
            else:
                do, short = "Plug it in. The copy starts by itself, and says when the drive is safe to unplug.", "Plug it in."
            problems.append(B._problem(
                "drive-stale", "server-drive", "needs_you", title,
                do + (f" The last good copy was on {good.get('at', '?')}." if good else " It has had no copy since it was set up."),
                look + [go], touches, f"The reminder comes after {r['remind_days']} days: [backup] drive_remind_days in {B.CONFIG}."))
            said.append(f"{title}. {short}")
        elif not failed:
            said.append(f"{NAME}: copied {B.ago(good['ts'], now)}." if good else f"{NAME}: no copy yet.")
    return problems, " ".join(said)


def drive_words(r):
    """A remembered drive, for people."""
    words = ", ".join(x for x in (r["model"], B.size(r["size"]) if r["size"] else "", f'labelled "{r["label"]}"' if r["label"] else "") if x)
    return words or "a drive with no name"


def print_rows(rows, now, row):
    """The drive's lines in `bromigos lab backups`."""
    for r in rows:
        plugged = "copying now" if r["running"] else "plugged in" if r["plugged_in"] else "not plugged in"
        row(NAME, f"{drive_words(r)}: {plugged}")
        last, good = r["last_copy"], r["last_good_copy"]
        if not last:
            row("Last copy", "none yet")
            continue
        words = PHASES[last["phase"]]
        more = [f"snapshot {last['snapshot']}"] if last.get("snapshot") else []
        if last.get("files") is not None and last["phase"] in ("ok", "partial"):
            more += [B.count(last["files"], "file"), B.size(last.get("bytes"))]
        row("Last copy", f"{words}, {B.ago(last['ts'], now)} ({B.when(last['ts'])}" + "".join(f", {m}" for m in more) + ")")
        if last.get("reason"):
            row("", last["reason"])
        if last["phase"] in ("failed", "stopped"):
            row("Last good one", f"{B.ago(good['ts'], now)} ({B.when(good['ts'])})" if good else "none yet")


# ------------------------------------------------------------------ reading the drive (--from)

def wanted(source, b):
    """Does a restore command read the backup drive? With --from go-bag, or by itself when no
    nightly destination is set and a drive is."""
    if source:
        if source not in (VERB, "drive"):
            raise B.Problem("usage", f"--from {source}: the only other place is the {NAME} drive, --from {VERB}.", exit=2)
        return True
    return not b["to"] and bool(remembered())


@contextlib.contextmanager
def source(b, quiet=False):
    """[backup]'s settings with the backup drive as the destination, for list, show, restore
    and test: the drive is mounted for as long as the command runs, then unmounted, and the
    last line says whether it is safe to unplug."""
    uuid, _ = which()
    with lock():
        m = Mount.of(uuid).mount()
        try:
            if not os.path.isfile(os.path.join(m.folder(), "config")):
                raise B.Problem("unreachable", f"The {NAME} drive has no backup of this server on it. Set it up "
                                f"again: bromigos lab backups {VERB} setup")
            yield dict(b, to=m.to(), source="drive", drive=uuid, flag=FLAG, name=f"the {NAME} drive")
        finally:
            B.hold_signals()
            safe, why = m.unmount()
            B.release_signals()
            if not quiet:
                print("\n" + unplug_words(safe, why, m), file=sys.stderr)


def unplug_words(safe, why, m=None):
    if safe:
        return f"The {NAME} drive is unmounted: safe to unplug."
    if safe is None:
        return f"The {NAME} drive is still mounted at {why}, where it was before: unmount it before you unplug it."
    point = f"{MOUNTS}/{m.uuid}" if m else f"{MOUNTS}/…"
    return (f"The {NAME} drive couldn't be unmounted ({why}). Don't unplug it yet: close what uses it, then "
            f"`sudo umount {point}`, or shut the server down first.")


# ------------------------------------------------------------------ the copy (the job's body)

def say(line):
    print(line, flush=True)


def copy(b, uuid=None):
    """The job's body (`bromigos-server backup drive-copy`): the server's backup, copied to the
    backup drive. b is [backup] with the server's defaults (paths, exclude, keep_*, env_file).
    It prints the house progress lines (docs/activity.md), keeps how it went in backup.json's
    drives, and always leaves the drive unmounted. Exit 0 only when the copy is good and the
    drive is safe to unplug (or was left mounted where its owner had it)."""
    for sid, label in STEPS:
        say(f"::step {sid} todo {label}")
    B.catch_signals()
    # Another copy is kept out by the job's own lock (job_command's --lock). This file lock is
    # for what isn't a job: a setup, or a restore that reads the drive. The copy waits for it
    # (stopping it meanwhile is safe), and is never skipped: a copy that didn't happen must
    # not end as one that did
    try:
        with lock():
            return copy_locked(b, uuid)
    except B.Problem as e:
        if e.code != "busy":
            raise
    waiting = f"Waiting for the command that is using the {NAME} drive (a setup, or a restore from it)"
    say(f"::stage 0 {waiting}")
    say(f"::note {waiting}")
    try:
        with lock(wait=True):
            return copy_locked(b, uuid)
    except B.Stopped:
        say(f"::error drive It was stopped while it waited for the {NAME} drive. Nothing was written.")
        return 130


def copy_locked(b, uuid):
    started, at_step, m, good, reason, code, stopped = time.time(), "drive", None, None, "", 1, False
    try:
        say(f"::stage 0 Looking for the {NAME} drive")
        say("::step drive running")
        uuid, _ = which(uuid)
        m = Mount.of(uuid).mount()
        if not os.path.isfile(os.path.join(m.folder(), "config")):
            raise B.Problem("failed", f"This drive has no backup of this server on it. Set it up again: bromigos "
                            f"lab backups {VERB} setup")
        env = B.restic_env(dict(b, to=m.to()))
        say(f"::step drive done {describe(m.disk, m.node)}")
        at_step = "copy"
        say("::stage 5 Copying what changed")
        say("::step copy running")
        run = backup(env, b)
        keep(env, b)
        say(f"::step copy done {B.count(run['files'] or 0, 'file')}, {B.size(run['bytes'])} ({B.size(run['added'])} added to the drive)")
        at_step = "check"
        say("::stage 88 Checking what was written")
        say("::step check running")
        verify(env)
        say("::step check done It reads back")
        at_step, good = "unplug", run
    except B.Stopped:
        reason, code, stopped = "It was stopped before it finished.", 130, True
    except B.Problem as e:
        reason, code = e.message, e.exit if e.exit not in (0, 3) else 1
    except OSError as e:
        reason = f"It stopped: {e}."
    B.hold_signals()                                 # unmounting and the record are never stopped half-way
    safe, why = (True, "") if not m else (None, "")
    if m:
        say(f"::cancel unsafe The {NAME} drive is being unmounted. Wait a moment: it is safe to unplug when this job ends.")
        if good:
            say("::stage 95 Unmounting the drive")
            say("::step unplug running")
        try:
            safe, why = m.unmount()
        except (B.Problem, OSError) as e:
            safe, why = False, getattr(e, "message", str(e))
    if good:
        rec = dict(good, seconds=round(time.time() - started, 1), unmounted=safe)
    else:
        # stopped (`bromigos activity cancel`, a unit stopped): not a failure, and no alert
        rec = {"phase": "stopped" if stopped else "failed", "at": B.iso(), "ts": time.time(), "reason": reason,
               "seconds": round(time.time() - started, 1), "unmounted": safe}
    if uuid and uuid in remembered():
        update_drive(uuid, run=rec, **({"run_ok": rec} if good else {}))
    if not good:
        say(f"::error {at_step} {reason} " + (unplug_words(safe, why, m) if m else "Nothing was written."))
        return code
    done = f"{B.count(good['files'] or 0, 'file')} ({B.size(good['bytes'])}) copied to the {NAME} drive."
    if safe:
        say("::step unplug done Unmounted")
        say(f"::stage 100 Safe to unplug. {done}")
        return 0
    if safe is None:
        say(f"::step unplug skipped Left mounted at {why}, where it was before")
        say(f"::stage 100 {done} It is still mounted at {why}, where it was before: unmount it before you unplug it.")
        return 0
    say(f"::error unplug The copy is good, but {B.lower_first(unplug_words(safe, why, m))}")
    return 1


def backup(env, b):
    """restic backup of the server's paths to the drive, its percent done as the job's share.
    Returns the copy's record; raises Problem with why it failed."""
    # the nightly backup's own rules for what must be in it (bromigos_backups.py, REQUIRED): never
    # an empty /srv/apps while the data disks are away, the apps' databases copied whole first,
    # and the apps' data named by itself, whatever [backup] paths says
    gone = B.away()
    if gone:
        raise B.Problem("failed", f"The data disks aren't mounted, so {B.missing_words(gone)} can't be read. Nothing was copied.")
    dbs = B.copy_databases()
    paths = [B.at(p) for p in B.backup_set(b["paths"])]
    args = ["backup", "--json", "--tag", B.TAG, "--exclude-caches"]
    for x in b["exclude"]:
        args += ["--exclude", x]
    hold = {"summary": {}, "told": 0.0}

    def on_line(line):
        m = B._loads(line)
        if m.get("message_type") == "summary":
            hold["summary"] = m
        elif m.get("message_type") == "status" and m.get("total_bytes") and time.monotonic() - hold["told"] >= 2:
            hold["told"] = time.monotonic()
            done, total = int(m.get("bytes_done") or 0), int(m["total_bytes"])
            say(f"::stage {5 + int(80 * min(1.0, float(m.get('percent_done') or 0)))} Copying: {B.size(done)} of {B.size(total)}")
            say(f"::step copy running {done // 1_000_000}/{max(1, total // 1_000_000)} MB")

    rc, _, err = B.restic(env, [*args, *paths], on_line)
    summary = hold["summary"]
    skipped, last = B.restic_errors(err)
    # 3: some files couldn't be read, the rest was backed up
    if rc not in (0, 3) or not summary:
        raise B.Problem("failed", f"{B.upper_first(B.sentence(last or last_words(err) or 'restic backup failed'))}.")
    # looked for in the copy itself: one without the apps' data is not a good copy
    snap = str(summary.get("snapshot_id") or "")
    gone = B.missing(env, {"id": snap}, B.required_paths())
    if gone:
        raise B.Problem("failed", f"The copy left out {B.missing_words(gone)}.")
    why = [] if rc == 0 else ["some files couldn't be read: " + (last or f"{len(skipped)} of them")]
    why += [f"{d['what']}'s database wasn't copied whole ({d['reason']})" for d in dbs if not d["ok"]]
    return {"phase": "partial" if why else "ok", "at": B.iso(), "ts": time.time(),
            "snapshot": snap[:8], "files": summary.get("total_files_processed"),
            "bytes": summary.get("total_bytes_processed"), "added": summary.get("data_added"),
            "reason": "; ".join(why), "databases": dbs}


def keep(env, b):
    """The nightly backup's keep rules, on the drive."""
    B.restic(env, ["forget", "--tag", B.TAG, "--prune", "--keep-daily", str(b["keep_daily"]), "--keep-weekly",
                   str(b["keep_weekly"]), "--keep-monthly", str(b["keep_monthly"])])


def verify(env):
    """restic check, with up to READ_BACK of the data read back from the drive."""
    rc, out, err = B.restic(env, ["check", f"--read-data-subset={READ_BACK}", "--retry-lock", "2m"])
    if rc != 0:
        raise B.Problem("failed", "What was written doesn't read back: "
                        f"{B.sentence(B.restic_errors(err)[1] or last_words(err, out) or 'restic check failed')}. The drive may be failing.")


# ------------------------------------------------------------------ starting the job

def beside(*parts):
    """A file of bromigOS's beside this one's folder: /usr/lib/bromigos/… installed, the
    checkout's in a checkout. So a checkout's tests never run an installed command."""
    return os.path.join(os.path.dirname(os.path.dirname(os.path.realpath(__file__))), *parts)


def activity_command():
    for p in (beside("bin", "bromigos-activity"), ACTIVITY, shutil.which("bromigos-activity")):
        if p and os.access(p, os.X_OK):
            return p
    return None


def server_command():
    return beside("server", "bromigos-server") if os.path.exists(beside("server", "bromigos-server")) else B.server_command()


def job_command(uuid, via="cli", detach=False, as_json=False):
    """`bromigos activity run … -- bromigos-server backup drive-copy`: the copy as a job with a
    record, in a unit of its own."""
    act, server = activity_command(), server_command()
    if not act or not server:
        raise B.Problem("not-a-server", "bromigos-server and bromigos activity aren't both installed here, so the copy "
                        "can't be started.", exit=3)
    d = remembered().get(uuid) or {}
    name = re.sub(r"[\x00-\x1f:]", " ", d.get("label") or d.get("model") or NAME).strip() or NAME
    # --lock: two copies to the drive (a drive plugged in twice) take turns, and the second shows
    # as waiting for the first. --cancel-safe: stopping a copy loses nothing (restic leaves the
    # backup whole, and the drive is unmounted); the copy says otherwise while it unmounts.
    # --retry-safe: a copy is the same work every time, so `bromigos activity retry` may start it again
    return [act, "run", "--kind", KIND, "--title", f"Copying the backup to the {NAME} drive",
            "--subject", f"drive:{uuid.lower()}:{name}", "--via", via, "--lock", JOB_LOCK, "--cancel-safe", "--retry-safe",
            *(["--detach"] if detach else []), *(["--json"] if as_json else []),
            "--", sys.executable, "-I", server, "backup", "drive-copy", "--uuid", uuid]


def plugged(uuid):
    """The unit's hook: a filesystem with this UUID was plugged in. Not the backup drive:
    nothing to do. The backup drive: its copy starts, as a job of its own, and this returns."""
    if uuid not in remembered():
        return 0
    return subprocess.run(job_command(uuid, via="timer", detach=True), stdin=subprocess.DEVNULL).returncode


def follow(cmd, as_json):
    """Run the job and show it the house way: "[2/4] Copying what changed", "      40 % · …".
    Returns (exit status, the last words, the job's record when as_json)."""
    import bromigos_activity as A
    if as_json:
        r = subprocess.run(cmd, capture_output=True, text=True, stdin=subprocess.DEVNULL)
        try:
            rec = json.loads(r.stdout).get("job")
        except (ValueError, AttributeError):
            rec = None
        return r.returncode, "", rec
    order, labels, seen, last, told = [s for s, _ in STEPS], dict(STEPS), set(), "", 0.0
    # (activity's own last line, on stderr, says the same as ours: kept only for when it couldn't start the job)
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, stdin=subprocess.DEVNULL, text=True, errors="replace")
    try:
        for line in proc.stdout:
            ev = A.parse(line.rstrip("\n"), order)
            if not ev:
                continue
            words = ev.get("words") or ""
            if ev["kind"] == "step" and ev["state"] == "running" and ev["id"] not in seen:
                seen.add(ev["id"])
                print(f"[{order.index(ev['id']) + 1 if ev['id'] in order else '?'}/{len(order)}] {labels.get(ev['id'], ev['id'])}", flush=True)
            elif ev["kind"] == "step" and ev["state"] in ("done", "skipped") and words:
                print(f"      {words}", flush=True)
            elif ev["kind"] == "stage":
                last = words or last
                if ev["pct"] not in (0, 5, 88, 95, 100) and time.monotonic() - told >= 5:
                    told = time.monotonic()
                    print(f"      {ev['pct']} % · {words}", flush=True)
            elif ev["kind"] == "note":
                print(f"      {words}", flush=True)
            elif ev["kind"] == "error":
                last = words
        said = proc.stderr.read()
        rc = proc.wait()
        return rc, last or (last_words(said) if rc else ""), None
    except KeyboardInterrupt:
        proc.wait()
        return 130, "Stopped watching. If the copy still runs, `bromigos activity` shows it.", None


# ------------------------------------------------------------------ setup

def agreed(a, question, word="yes"):
    """A yes in words: typed on a terminal, or --yes from a script."""
    if a.yes:
        return True
    if a.json or not sys.stdin.isatty():
        return False
    try:
        return input(f"{question} Type {word}: ").strip().lower() == word
    except (EOFError, KeyboardInterrupt):
        print()
        return False


def matches(spec, n):
    if spec in (n["path"], n["name"], n["uuid"], n["label"]):
        return bool(spec)
    try:
        return B.ROOT == "/" and os.path.exists(spec) and os.path.realpath(spec) == os.path.realpath(n["path"])
    except OSError:
        return False


def choose(spec, disks):
    """(the disk, the partition named or None) for `setup [DRIVE]`: the drive named by its
    path, name, label or UUID, or the only removable drive that isn't part of the system."""
    if spec:
        for d in disks:
            for n in [d, *d["nodes"]]:
                if matches(spec, n):
                    return d, (None if n is d else n)
        raise B.Problem("no-such-drive", f"There is no drive {spec} here. `bromigos lab backups {VERB} drives` lists "
                        "what the server sees.", exit=2)
    removable = [d for d in disks if d["removable"]]
    usable = [d for d in removable if not in_use(d) and not d["ro"]]
    if not usable and removable:
        return removable[0], None                    # the one that is plugged in: setup says why it can't be used
    if not usable:
        raise B.Problem("no-drive", f"No USB drive that could be the {NAME} is plugged in. Plug one in and try again. "
                        f"`bromigos lab backups {VERB} drives` lists what the server sees.", exit=3)
    if len(usable) > 1:
        raise B.Problem("which-drive", "More than one USB drive is plugged in. Name the one to use:\n"
                        + "\n".join(f"  bromigos lab backups {VERB} setup {d['path']}     {describe(d)}" for d in usable), exit=2)
    return usable[0], None


def partition(disk, node):
    """The partition (or bare disk) the backup goes on."""
    if node is not None:
        if node["type"] != "part":
            raise B.Problem("no-such-drive", f"{node['path']} isn't a disk or a partition of one.", exit=2)
        return node
    parts = [n for n in disk["nodes"] if n["type"] == "part"]
    if not parts:
        return disk
    if len(parts) == 1:
        return parts[0]
    raise B.Problem("which-partition", f"{describe(disk)} has {len(parts)} partitions. Name the one to use:\n"
                    + "\n".join(f"  bromigos lab backups {VERB} setup {p['path']}     {B.size(p['size'])}, "
                                f"{p['fstype'] or 'no filesystem'}" + (f', "{p["label"]}"' if p["label"] else "") for p in parts), exit=2)


def holds(node):
    """What is on a partition, in a few words."""
    return (f"a {node['fstype']} filesystem" + (f' named "{node["label"]}"' if node["label"] else "")) if node["fstype"] \
        else "no filesystem this server knows"


README = """This drive is a backup drive of bromigOS Server: the {name} of the server "{host}".

The folder {folder}/{host} beside this file is an encrypted restic repository
(https://restic.net). Nobody can read it without the backup's key, which is kept on the
server and wherever you put your copy of it.

On the server, with this drive plugged in:

    bromigos lab backups list --from {verb}
    bromigos lab backups restore --from {verb}

On any computer with restic, and the key in a file (one line):

    restic -r <this drive>/{folder}/{host} --password-file backup.key snapshots
    restic -r <this drive>/{folder}/{host} --password-file backup.key restore latest --target ./restored

Wait for "Safe to unplug" before you unplug it.
"""


def cmd_setup(a, b):
    """Make a drive the backup drive. Refuses, in plain words, a drive that is part of the
    system, one that isn't removable, one with files it doesn't know and one it can't write,
    until the person says so in words (the table in docs/server.md)."""
    have = remembered()
    with lock():
        disks = blocks()
        disk, named = choose(a.drive, disks)
        busy = in_use(disk)
        if busy:
            raise B.Problem("in-use", f"{describe(disk)} can't be the {NAME}: {busy}. A drive this server is using "
                            "is never touched." + (f" If it is the drive you mean, unmount it first: sudo umount {busy.split(' at ')[-1]}"
                                                   if disk["removable"] and " mounted at " in busy else ""), exit=3)
        if disk["ro"]:
            raise B.Problem("read-only", f"{describe(disk)} is read-only (a write-protect switch?), so nothing can be copied to it.", exit=3)
        node = partition(disk, named)
        if node["ro"]:
            raise B.Problem("read-only", f"{node['path']} is read-only, so nothing can be copied to it.", exit=3)
        other = [u for u in have if u != node["uuid"]]
        if other:
            raise B.Problem("one-drive", f"This server already has a {NAME} drive ({drive_words(view({'drives': have}, time.time())[0])}). "
                            f"One drive for now: to change drives, first run: bromigos lab backups {VERB} forget", exit=3)
        if not disk["removable"] and not a.internal:
            # --yes alone never says this: a script names it (--internal), a person types it
            if a.yes or not agreed(a, f"{describe(disk)} isn't a removable drive: it looks like a disk inside this "
                                   f"server. A {NAME} is meant to be unplugged and kept somewhere else. Use it anyway?"):
                raise B.Problem("not-removable", f"{describe(disk)} isn't a removable drive: it looks like a disk inside "
                                f"this server, and a {NAME} is meant to be unplugged and kept somewhere else. Nothing was "
                                "changed. If it really is the drive you mean, add --internal.", exit=3)
        erased = adopted = False
        if node["mountpoints"]:                      # ours, from a copy that was killed (anyone else's was refused above)
            safe, why = Mount(disk, node).mount().unmount()
            if not safe:
                raise B.Problem("in-use", f"{node['path']} is still mounted from an earlier copy and couldn't be unmounted ({why}).", exit=3)
            node = dict(node, mountpoints=[])
        if a.erase:
            what = "; ".join(f"{n['path']}: {holds(n)}, {B.size(n['size'])}" for n in ([node] if node is not disk else [disk]))
            if not agreed(a, f"This erases {node['path']} on {describe(disk)} ({what}). Everything on it is deleted and "
                          "can't be brought back.", word="erase"):
                raise B.Problem("needs-yes", f"Erasing {node['path']} on {describe(disk)} ({what}) deletes everything on "
                                "it, so it needs a yes in words. Nothing was changed. On a terminal, type erase when "
                                "asked; in a script, add --yes.", exit=3)
            was = node["uuid"]
            node = erase(disk, node)
            erased = True
            if was in have:                          # the Go Bag itself, formatted: its old filesystem is gone
                forget_drive(was)
                have = {}
        elif node["fstype"] not in WRITABLE or not node["uuid"]:
            what = (f"holds {holds(node)}, which this server can't keep a backup on" if node["fstype"] else
                    "has no filesystem this server knows (a blank drive, or one made for another system)")
            raise B.Problem("needs-erase", f"{node['path']} on {describe(disk)} {what}. Nothing was changed. To format it "
                            f"for the {NAME}, which deletes everything on it: bromigos lab backups {VERB} setup "
                            f"{node['path']} --erase", exit=3)
        ensure_key()
        m = Mount(disk, node).mount()
        try:
            repo = m.folder()
            env = B.restic_env(dict(b, to=m.to()))
            if os.path.isfile(os.path.join(repo, "config")):
                rc, _, err = B.restic(env, ["cat", "config", "--retry-lock", "30s"])
                if rc == 12 or (rc != 0 and "wrong password" in err):
                    raise B.Problem("wrong-key", f"This drive already holds a {NAME} of a server named {hostname()}, made "
                                    f"with another key: this server's key ({B.KEY}) doesn't open it. Nothing was changed. "
                                    "Put the key you kept for it back in that file, or start over on this drive with "
                                    "--erase, which deletes everything on it.", exit=3)
                if rc != 0:
                    raise B.Problem("failed", f"The backup already on this drive can't be read: {B.restic_errors(err)[1] or last_words(err)}.")
                adopted = True
            else:
                try:
                    names = sorted(n for n in os.listdir(m.where) if n not in LEFT_BY_SYSTEMS and not n.startswith(".Trash-"))
                except OSError as e:
                    raise B.Problem("failed", f"The drive can't be read: {e}.")
                if names and not agreed(a, f"{describe(disk, node)} has other files on it ({listed(names)}). The {NAME} "
                                        f"adds one folder, {FOLDER}, and deletes nothing. Use this drive?"):
                    raise B.Problem("has-files", f"{describe(disk, node)} has files on it that aren't a {NAME}'s "
                                    f"({listed(names)}). Nothing was changed. To keep them and add the {NAME} beside them "
                                    f"(one folder, {FOLDER}; nothing is deleted), add --yes. To start with an empty drive, "
                                    "add --erase, which deletes everything on it.", exit=3)
                os.makedirs(repo, mode=0o700, exist_ok=True)
                rc, out, err = B.restic(env, ["init"])
                if rc != 0:
                    raise B.Problem("failed", f"The drive couldn't be set up: {B.restic_errors(err)[1] or last_words(err, out) or 'restic init failed'}.")
                with open(os.path.join(m.where, FOLDER, "README.txt"), "w") as f:
                    f.write(README.format(name=NAME, verb=VERB, host=hostname(), folder=FOLDER))
            now = time.time()
            was = have.get(node["uuid"]) or {}
            update_drive(node["uuid"], label=node["label"], model=disk["model"], size=disk["size"], fstype=node["fstype"],
                         removable=bool(disk["removable"]), folder=f"{FOLDER}/{hostname()}",
                         added_at=was.get("added_at") or B.iso(now), added_ts=was.get("added_ts") or now)
        finally:
            safe, why = m.unmount()
    uuid = node["uuid"]
    row = next(r for r in view(B.read_json(B.STATE), time.time(), b["drive_remind_days"]) if r["uuid"] == uuid)
    doc = {"schema": B.SCHEMA, "ok": True, "drive": row, "erased": erased, "adopted": adopted, "copy": None}
    if not a.json:
        print(f"{describe(disk, node)} is now this server's {NAME}"
              + (", formatted and empty." if erased else ": the backup already on it is kept." if adopted else "."))
        print(f"  It is remembered by its filesystem's id ({uuid}), whatever it is called next time.")
        print("  The backup on it is encrypted with this server's backup key. Keep a copy of the key somewhere "
              "else: sudo bromigos server backup key")
    if a.no_copy or safe is False:
        if not a.json:
            print("\n" + unplug_words(safe, why, m))
            print(f"The first copy is made when you next plug it in, or now: bromigos lab backups {VERB} run")
        else:
            print(json.dumps(doc, indent=1))
        return 0 if safe is not False else 1
    if not a.json:
        print("\nThe first copy:")
    rc, last, rec = follow(job_command(uuid, as_json=a.json), a.json)
    doc.update(ok=rc == 0, copy={"exit": rc, "job": rec},
               drive=next(r for r in view(B.read_json(B.STATE), time.time(), b["drive_remind_days"]) if r["uuid"] == uuid))
    if a.json:
        print(json.dumps(doc, indent=1))
    else:
        print(f"\n{last}", file=sys.stdout if rc == 0 else sys.stderr)
        if rc == 0:
            print(f"From now on, plug it in and the copy starts by itself. Remind after {b['drive_remind_days']} days "
                  f"without one ([backup] drive_remind_days).")
    return rc


def listed(names):
    return ", ".join(names[:5]) + (f" and {len(names) - 5} more" if len(names) > 5 else "")


def ensure_key():
    """The backup's key, made by bromigos-server when there is none yet (a server whose first
    backup is its Go Bag). Its words go nowhere: `backup key` prints the key."""
    if os.path.isfile(B.at(B.KEY)):
        return
    server = server_command()
    if server:
        subprocess.run([sys.executable, "-I", server, "backup", "key"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                       stdin=subprocess.DEVNULL)


def erase(disk, node):
    """Format the partition (or bare disk) ext4, and return it as lsblk sees it afterwards.
    The partition table is never touched."""
    dev = node["path"]
    for name, args in (("wipefs", ["--all", dev]), ("mkfs.ext4", ["-q", "-F", "-m", "0", "-L", LABEL, dev])):
        rc, out, err = call(name, *args, timeout=1800)
        if rc != 0:
            raise B.Problem("failed", f"{dev} couldn't be formatted: {last_words(err, out) or name + ' failed'}.")
    call("udevadm", "settle", "--timeout=30", timeout=40)
    for _ in range(10):
        for d in blocks():
            for n in [d, *d["nodes"]]:
                if n["path"] == dev and n["fstype"] == "ext4" and n["uuid"]:
                    return n
        time.sleep(1 if B.ROOT == "/" else 0)
    raise B.Problem("failed", f"{dev} was formatted, but the server doesn't see its new filesystem. Unplug the drive, "
                    f"plug it back in, and run: bromigos lab backups {VERB} setup")


# ------------------------------------------------------------------ status, drives, run, forget

def status_doc(now=None):
    now = time.time() if now is None else now
    b = B.settings()
    rows = view(B.read_json(B.STATE), now, b["drive_remind_days"], busy=running())
    problems, said = judge(rows, now)
    return {"schema": B.SCHEMA, "ok": not problems, "name": NAME, "set_up": bool(rows), "verdict": said, "drives": rows,
            "problems": problems, "remind_days": b["drive_remind_days"], "checked_at": B.iso(now), "now": int(now)}


def cmd_status(a, b):
    d = status_doc()
    if a.json:
        print(json.dumps(d, indent=1))
        return 0 if d["ok"] else 1
    if not d["set_up"]:
        print(f"No {NAME} drive is set up.\n\nA {NAME} is a USB drive that holds a copy of this server's backup. You plug "
              "it in, the copy starts by itself, and when it says \"Safe to unplug\" you take the drive somewhere "
              f"else: a fire or a theft that takes the server doesn't take it.\n\nPlug a drive in and run: bromigos lab backups {VERB} setup")
        return 0
    print(d["verdict"] + "\n")
    print_rows(d["drives"], d["now"], lambda label, text: print(f"  {label:<13} {text}"))
    days_ = d["remind_days"]
    print(f"  {'Reminder':<13} " + (f"after {days_} days without a good copy" if days_ else "off") + " ([backup] drive_remind_days)")
    for p in d["problems"]:
        print(f"\n  {p['title']}. {p['detail']}")
    print(f"\nCopy now: bromigos lab backups {VERB} run   ·   get files back: bromigos lab backups restore{FLAG}")
    return 0 if d["ok"] else 1


def cmd_drives(a, b):
    have = remembered()
    rows = []
    for d in blocks():
        busy = in_use(d)
        ours = next((n["uuid"] for n in [d, *d["nodes"]] if n["uuid"] in have), None)
        why = (f"it is this server's {NAME}" if ours else f"it is part of this server ({busy})" if busy else
               "it is read-only" if d["ro"] else "" if d["removable"] else "it isn't removable (a disk inside the server)")
        rows.append({"path": d["path"], "model": d["model"], "size": d["size"], "removable": d["removable"], "transport": d["tran"],
                     "usable": not why, "why": why, "remembered": bool(ours),
                     "partitions": [{k: n[k] for k in ("path", "size", "fstype", "label", "uuid")} for n in d["nodes"] if n["type"] == "part"]})
    if a.json:
        print(json.dumps({"schema": B.SCHEMA, "ok": True, "drives": rows}, indent=1))
        return 0
    if not rows:
        print("The server sees no drives.")
        return 0
    for r in rows:
        print(f"  {r['path']:<14} {r['model'] or 'no name'}, {B.size(r['size'])}: "
              + (f"can be the {NAME}" if r["usable"] else f"not offered: {r['why']}"))
        for p in r["partitions"]:
            print(f"      {p['path']:<12} {B.size(p['size'])}, {p['fstype'] or 'no filesystem'}" + (f', "{p["label"]}"' if p["label"] else ""))
    print(f"\nMake one the {NAME}: bromigos lab backups {VERB} setup DRIVE")
    return 0


def cmd_run(a, b):
    uuid, _ = which()
    if not find(uuid)[1]:
        raise B.Problem("unplugged", f"The {NAME} drive isn't plugged in. Plug it in: the copy starts by itself.")
    rc, last, rec = follow(job_command(uuid, as_json=a.json), a.json)
    if a.json:
        print(json.dumps({"schema": B.SCHEMA, "ok": rc == 0, "exit": rc, "job": rec,
                          "drive": next((r for r in status_doc()["drives"] if r["uuid"] == uuid), None)}, indent=1))
    elif last:
        print(f"\n{last}", file=sys.stdout if rc == 0 else sys.stderr)
    return rc


def cmd_forget(a, b):
    uuid, d = which()
    words = drive_words(view({"drives": {uuid: d}}, time.time())[0])
    if not agreed(a, f"Stop using {words} as this server's {NAME}? What is on the drive is left alone."):
        raise B.Problem("needs-yes", f"Forgetting the {NAME} drive needs a yes. Nothing was changed. In a script, add --yes.", exit=3)
    with lock():
        forget_drive(uuid)
    if a.json:
        print(json.dumps({"schema": B.SCHEMA, "ok": True, "forgotten": uuid}, indent=1))
    else:
        print(f"{B.upper_first(words)} is no longer this server's {NAME}: plugging it in starts nothing, and no reminder "
              f"comes. The backup on it is still there, in {FOLDER}/. To use it again: bromigos lab backups {VERB} setup")
    return 0


USAGE = f"""bromigos lab backups {VERB}: the {NAME}, a copy of this server's backup on a USB drive you unplug
and keep somewhere else (docs/server.md, "The {NAME}")

  bromigos lab backups {VERB}                 which drive it is, whether it is plugged in, its last good copy
  bromigos lab backups {VERB} drives          the drives it could be, and why not the others
  bromigos lab backups {VERB} setup [DRIVE]   make DRIVE the {NAME} (no DRIVE: the only USB drive plugged
                                              in), then make the first copy
      --erase                                 format it first (ext4). Everything on it is deleted
      --internal                              use a drive that isn't removable
      --yes                                   don't ask
      --no-copy                               set it up only
  bromigos lab backups {VERB} run             copy now (the drive must be plugged in)
  bromigos lab backups {VERB} forget [--yes]  stop using the drive. What is on it is left alone

Plug the {NAME} in and the copy starts by itself; `bromigos activity` shows it, and its last
line is "Safe to unplug". To read the drive: bromigos lab backups list | show | restore | test{FLAG}

Every one takes --json. setup, run and forget ask for the administrator's password when you
aren't root.
"""


def main(argv, typed, reexec):
    """`bromigos lab backups go-bag …`. typed is the whole command after `backups`, for running
    it again as root."""
    ap = argparse.ArgumentParser(prog=f"bromigos lab backups {VERB}", add_help=False)
    ap.add_argument("-h", "--help", action="store_true")
    sub = ap.add_subparsers(dest="verb")
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--json", action="store_true")
    for name in ("status", "drives", "run"):
        sub.add_parser(name, parents=[common], add_help=False)
    p = sub.add_parser("setup", parents=[common], add_help=False)
    p.add_argument("drive", nargs="?")
    p.add_argument("--erase", action="store_true")
    p.add_argument("--internal", action="store_true")
    p.add_argument("--yes", action="store_true")
    p.add_argument("--no-copy", action="store_true")
    p = sub.add_parser("forget", parents=[common], add_help=False)
    p.add_argument("--yes", action="store_true")
    if not argv or (argv[0].startswith("-") and argv[0] not in ("-h", "--help")):
        argv = ["status", *argv]
    try:
        a = ap.parse_args(argv)
    except SystemExit as e:
        if e.code:
            print(f"\n{USAGE}", file=sys.stderr)
        return 2 if e.code else 0
    if a.help:
        print(USAGE.strip() if shutil.which("bromigos") else USAGE.strip().replace("bromigos lab", "bromigos-lab"))
        return 0
    if not B.is_server():
        raise B.Problem("not-a-server", f"This computer isn't a bromigOS Server: the {NAME} is the Server's backup drive.", exit=3)
    b = B.settings()
    verb = a.verb or "status"
    if verb in ("status", "drives"):                 # these two only look
        return {"status": cmd_status, "drives": cmd_drives}[verb](a, b)
    B.as_root(typed, reexec, a.json)
    return {"setup": cmd_setup, "run": cmd_run, "forget": cmd_forget}[verb](a, b)
