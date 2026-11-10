"""`bromigos lab app-data`: where this server's apps keep their data, and the move that puts it
on the data disks (docs/server.md, "Where the apps keep their data").

    bromigos lab app-data [status] [--json]     where /srv/apps is, against where it's meant to be
    bromigos lab app-data move [--dry-run]      as root: from the system disk to the data disks
    bromigos lab app-data remove-old            as root: deletes the old copy a move kept

Every app `bromigos lab provision --local` sets up keeps its data in /srv/apps/<item>. A
bromigOS Server with data disks means that folder to be on them: the installer mounts their
apps subvolume at /srv/apps. Until November 2026 it made the subvolume and didn't mount it,
so a server installed before then has its apps' data on the system disk. `status` says which
(the Server's status line and the server.app-data alert read it), and `move` puts it right:

    the apps stopped; a copy with rsync; every file compared with its copy by checksum; one line
    added to /etc/fstab; the old folder renamed, never deleted; the data disks' apps subvolume
    mounted in its place; the apps started.

A check that fails, or a file that differs, stops the move before anything is switched, with
the apps running again where they were. A move cut off part-way carries on when run again.
Its record is /var/lib/bromigos/lab/app-data.json. This lives in bromigos-lab because every
bromigOS Server has it, whichever medium installed it; `bromigos server app-data` is the same.
"""
import argparse
import contextlib
import datetime
import fcntl
import json
import os
import re
import shutil
import subprocess
import sys
import tomllib

SERVER_TOML = "/etc/bromigos/server.toml"      # the installer's choices: [storage] disks, layout, mount


def at(path):
    """A path on this machine (tests: under BROMIGOS_ROOT)."""
    return os.path.join(os.environ.get("BROMIGOS_ROOT", "/"), path.lstrip("/"))


def run(cmd, timeout=None):
    """(exit code, stdout, stderr); a missing command is exit 127."""
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, stdin=subprocess.DEVNULL)
        return r.returncode, r.stdout, r.stderr
    except FileNotFoundError:
        return 127, "", f"{cmd[0]}: not installed"
    except subprocess.TimeoutExpired:
        return 124, "", f"{cmd[0]}: timed out"


def now():
    return datetime.datetime.now(datetime.timezone.utc).astimezone().isoformat(timespec="seconds")


def read_json(path):
    try:
        with open(at(path)) as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def write_json(path, doc):
    os.makedirs(os.path.dirname(at(path)), mode=0o755, exist_ok=True)
    tmp = at(path) + ".tmp"
    with open(tmp, "w") as f:
        json.dump(doc, f, indent=1, sort_keys=True)
        f.write("\n")
        f.flush()
        os.fsync(f.fileno())
    os.chmod(tmp, 0o644)
    os.replace(tmp, at(path))


def last_line(text, fallback):
    return (text.strip().splitlines() or [fallback])[-1][:300]


def unit_state(unit):
    rc, out, _ = run(["systemctl", "is-active", unit])
    return out.strip() or ("unknown" if rc == 127 else "inactive")


def storage():
    """The installer's [storage] table, when this server has one that can be read."""
    try:
        with open(at(SERVER_TOML), "rb") as f:
            st = tomllib.load(f).get("storage")
    except (OSError, tomllib.TOMLDecodeError):
        st = None
    return st if isinstance(st, dict) else {}


APPS_DIR = "/srv/apps"          # every app's data, a folder each (bromigos lab provision --local)
POOL = "/srv/data"              # the data disks, when the server has them ([storage] mount)
STATE = "/var/lib/bromigos/lab/app-data.json"       # the move's own record
FSTAB = "/etc/fstab"
QUADLETS = "/etc/containers/systemd"
LEFTOVER = APPS_DIR + ".on-system-disk-"        # the old copy's name after a move, with its date
# Apps the engine installs as packages keep their data where the package does, on the system
# disk: the engine gives them no folder under /srv/apps, and no move here touches them. The
# status says so, so "on the data disks" is never read as "all of it"
PACKAGED = (("/var/lib/vaultwarden", "passwords (Vaultwarden)"),)
MOVING = ("copying", "verifying", "switching")


class AppDataError(Exception):
    pass


def fstab_rows():
    """[[device, mount point, type, options]] of /etc/fstab, comments left out."""
    try:
        with open(at(FSTAB)) as f:
            rows = [line.split() for line in f if line.strip() and not line.lstrip().startswith("#")]
    except OSError:
        return []
    return [r[:4] for r in rows if len(r) >= 4]


def is_mount(path):
    return run(["findmnt", "-n", "-o", "TARGET", "--mountpoint", at(path)])[0] == 0


def fs_uuid(path):
    """The ID of the filesystem a path is on. btrfs gives every subvolume, and every disk of a
    RAID1, the same one, so this tells the data disks from the system disk whatever the path."""
    rc, out, _ = run(["findmnt", "-n", "-o", "UUID", "--target", at(path)])
    return (out.strip().splitlines() or [""])[0] if rc == 0 else ""


def app_data_doc():
    """Where /srv/apps is, against where this server means it to be: its data disks' apps
    subvolume when it has data disks, else the system disk. `state`:
      ok            where it's meant to be (`where`: pool or system)
      not-on-pool   the server has data disks, and the apps' data is on the system disk
      pool-away     fstab puts /srv/apps on the data disks, and it isn't mounted
      moving        a move is under way (`running`), or one was cut off (`move`: how far it got)"""
    st = storage()
    rows = fstab_rows()
    pool = (st.get("mount") or POOL) if st.get("disks") else next((r[1] for r in rows if r[1] == POOL and r[2] == "btrfs"), "")
    j = read_json(STATE)
    left = j.get("leftover") or ""
    try:
        has_data = bool(os.listdir(at(APPS_DIR)))
    except OSError:
        has_data = False
    doc = {"path": APPS_DIR, "pool": pool, "pool_mounted": False, "where": "system", "state": "ok",
           "has_data": has_data, "move": j.get("state") or "", "running": False,
           "raid1": st.get("layout") == "raid1" and len(st.get("disks") or []) >= 2,
           "leftover": left if left and j.get("state") == "done" and os.path.isdir(at(left)) else "",
           "elsewhere": []}
    if not pool:
        return doc
    doc["elsewhere"] = [{"path": p, "what": what} for p, what in PACKAGED if os.path.isdir(at(p))]
    on_pool = is_mount(pool) and fs_uuid(pool)
    doc["pool_mounted"] = bool(on_pool)
    if on_pool and is_mount(APPS_DIR) and fs_uuid(APPS_DIR) == on_pool:
        doc["where"] = "pool"
    elif any(r[1] == APPS_DIR for r in rows):
        doc["state"] = "pool-away"
    else:
        doc["state"] = "not-on-pool"
    if j.get("state") in MOVING:
        doc["state"], doc["running"] = "moving", move_running()
    return doc


def move_running():
    """Whether a move holds its lock now (anyone may ask)."""
    try:
        with open(at(STATE) + ".lock") as lock:
            fcntl.flock(lock, fcntl.LOCK_SH | fcntl.LOCK_NB)
    except BlockingIOError:
        return True
    except OSError:
        pass
    return False


def status():
    """The doc with its plain words: what `bromigos server` prints on its App data line."""
    d = app_data_doc()
    d["words"] = app_data_words(d)
    return d


def app_data_words(d):
    """The status line, and the lines under it when there's something to do or to know."""
    words = _words(d)
    for e in d.get("elsewhere") or []:
        words.append(f"not on the data disks: {e['what']} keeps its data in {e['path']}, on the system disk")
    return words


def _words(d):
    if d["state"] == "moving" and d["running"]:
        return ["moving to the data disks now" + (f" ({d['move']})" if d["move"] else "")]
    if d["state"] == "moving":
        return ["a move to the data disks didn't finish" + (f" ({d['move']})" if d["move"] else ""),
                "sudo bromigos lab app-data move carries on from there"]
    if d["state"] == "pool-away":
        return [f"on the data disks, which aren't mounted ({d['pool']}): the apps can't start until they are"]
    if d["state"] == "not-on-pool" and not d["has_data"]:
        return ["no app has data yet, and the next one's would go on the system disk, not the data disks",
                "sudo bromigos lab app-data move sets /srv/apps on the data disks (--dry-run shows what it would do)"]
    if d["state"] == "not-on-pool":
        return ["on the system disk, not the data disks: " + ("one copy, not two" if d["raid1"] else "not on the disks chosen for data"),
                "sudo bromigos lab app-data move puts it on the data disks (--dry-run shows what it would do)"
                if d["pool_mounted"] else
                f"the data disks aren't mounted now ({d['pool']}); once they are, sudo bromigos lab app-data move puts it on them"]
    words = [f"on the data disks ({d['path']}, their apps subvolume)" if d["where"] == "pool" else
             f"on the system disk ({d['path']}); this machine has no data disks"]
    if d["leftover"]:
        words.append(f"the old copy is kept at {d['leftover']}; sudo bromigos lab app-data remove-old deletes it")
    return words


def app_units():
    """The services that keep data under /srv/apps: every Quadlet that names it, and whatever
    else has a file open there now (a host service such as Syncthing), by its unit.
    (units, the host services among them, what isn't a service)."""
    units, hosts, strays = [], [], []
    qd = at(QUADLETS)
    for name in sorted(os.listdir(qd)) if os.path.isdir(qd) else []:
        if not name.endswith(".container"):
            continue
        try:
            with open(os.path.join(qd, name)) as f:
                text = f.read()
        except OSError:
            continue
        if re.search(rf"{APPS_DIR}(/|:|\s|$)", text, re.M):
            m = re.search(r"^ServiceName=(\S+)", text, re.M)
            units.append((m.group(1) if m else name.removesuffix(".container")) + ".service")
    for pid, what in busy():
        try:
            with open(at(f"/proc/{pid}/cgroup")) as f:
                parts = f.read().strip().split("/")
        except OSError:
            parts = []
        unit = next((part for part in reversed(parts) if part.endswith(".service")), "")
        if unit and "user.slice" not in parts:          # a system service; a person's own session isn't ours to stop
            hosts.append(unit)
        else:
            strays.append(f"process {pid} ({what})")
    hosts = [u for u in dict.fromkeys(hosts) if u not in units]
    return units + hosts, hosts, strays


def busy():
    """[(pid, a path)]: processes with a working folder, an open file or a mapped file under
    /srv/apps. A container's own view of its files isn't here: its mounts are asked of Podman."""
    out = []
    base = at("/proc")
    for pid in sorted(os.listdir(base)) if os.path.isdir(base) else []:
        if not pid.isdigit() or int(pid) == os.getpid():
            continue
        seen = []
        d = os.path.join(base, pid)
        try:
            links = [os.path.join(d, "cwd")] + [os.path.join(d, "fd", n) for n in os.listdir(os.path.join(d, "fd"))]
        except OSError:
            continue
        for link in links:
            try:
                seen.append(os.readlink(link))
            except OSError:
                pass
        try:
            with open(os.path.join(d, "maps")) as f:
                seen += [line.split(None, 5)[5].strip() for line in f if len(line.split(None, 5)) == 6]
        except OSError:
            pass
        hit = next((v for v in seen if v == APPS_DIR or v.startswith(APPS_DIR + "/")), None)
        if hit:
            out.append((pid, hit))
    return out


def containers_using():
    """Running containers that mount something under /srv/apps: [name]."""
    rc, out, _ = run(["podman", "ps", "--format", "json"], timeout=60)
    try:
        ids = [c["Id"] for c in json.loads(out or "[]")] if rc == 0 else []
    except (ValueError, KeyError, TypeError):
        ids = []
    if not ids:
        return []
    rc, out, _ = run(["podman", "inspect", *ids], timeout=60)
    try:
        rows = json.loads(out or "[]") if rc == 0 else []
    except ValueError:
        rows = []
    return [str(c.get("Name") or c.get("Id", "?")[:12]) for c in rows
            if any(str(m.get("Source", "")) == APPS_DIR or str(m.get("Source", "")).startswith(APPS_DIR + "/")
                   for m in c.get("Mounts") or [])]


def tree_bytes(path):
    rc, out, err = run(["du", "-sxB1", at(path)], timeout=3600)
    try:
        return int(out.split()[0])
    except (IndexError, ValueError):
        raise AppDataError(f"couldn't measure {path}: {last_line(err, 'du failed')}") from None


def gib(n):
    return f"{n / 1024 ** 3:.1f} GiB"


def must(argv, what, timeout=None):
    rc, out, err = run(argv, timeout=timeout)
    if rc != 0:
        raise AppDataError(f"{what}: {last_line(err or out, 'it failed')}")
    return out


def app_data_plan(d):
    """What a move would do, checked: the source, the pool and its fstab line, the apps
    subvolume (made if it isn't there), the space, the services to stop and the old copy's name."""
    src, pool = APPS_DIR, d["pool"]
    row = next((r for r in fstab_rows() if r[1] == pool), None)
    if not row or row[2] != "btrfs":
        raise AppDataError(f"the data disks ({pool}) aren't a btrfs line in {FSTAB}, so there's nothing to mount the apps' folder from")
    dst = os.path.join(pool, "apps")
    j = read_json(STATE)
    resuming = j.get("state") in (*MOVING, "failed") and j.get("destination") == dst
    if os.path.isdir(at(dst)) and os.listdir(at(dst)) and not resuming:
        names = ", ".join(sorted(os.listdir(at(dst)))[:5])
        raise AppDataError(f"{dst} already has files in it ({names}), and they aren't from a move of this server's apps. "
                           "Nothing was changed: move them away first, so nothing of yours is overwritten")
    if is_mount(src):
        raise AppDataError(f"{src} is a mount of its own, not a folder on the system disk: this moves only the folder the "
                           "apps were given. Nothing was changed")
    there = os.path.isdir(at(src))          # not there: no app has data yet, and there's nothing to copy or keep
    need, free = tree_bytes(src) if there else 0, shutil.disk_usage(at(pool)).free
    if there and not shutil.which("rsync"):
        raise AppDataError("rsync isn't installed, and the copy is made with it. Install the rsync package, then run this again")
    units, hosts, strays = app_units()
    left = LEFTOVER + datetime.date.today().isoformat() if there else ""
    if left and os.path.lexists(at(left)):
        left += "-" + datetime.datetime.now().strftime("%H%M%S")
    opts = ",".join(o for o in row[3].split(",") if not o.startswith(("subvol=", "subvolid=")))
    return {"source": src, "pool": pool, "destination": dst, "bytes": need, "free": free,
            # room for the copy, and some over: btrfs needs space of its own, and the apps start again after
            "fits": free >= int(need * 1.05) + 1024 ** 3,
            "units": units, "host_units": hosts, "strays": strays, "leftover": left,
            "fstab": f"{row[0]}  {src}  btrfs  subvol=/apps,{opts}  0 0", "resuming": resuming}


def print_move_plan(p, dry):
    will = "would" if dry else "will"
    if not p["leftover"]:
        print(f"bromigos lab app-data: no app has data yet. The data disks' apps subvolume ({p['destination']}) {will} be mounted "
              f"at {p['source']}, so the apps keep their data on the data disks from the start:")
        print(f"       {p['fstab']}")
        return
    print(f"bromigos lab app-data: the apps' data ({gib(p['bytes'])} in {p['source']}, on the system disk) {will} move to the data "
          f"disks ({p['destination']}, {gib(p['free'])} free)")
    print(f"  1. stop the apps: {', '.join(p['units']) or 'none is set up'}")
    print(f"  2. copy {p['source']} to {p['destination']}" + (" (carrying on from the copy already there; what's no longer in "
                                                                 f"{p['source']} leaves the copy too)" if p["resuming"] else ""))
    print("  3. compare every file with its copy, by checksum; any difference stops here, with nothing changed")
    print(f"  4. keep the old copy as {p['leftover']}, and mount the data disks' apps subvolume at {p['source']}:")
    print(f"       {p['fstab']}")
    print("  5. start the apps again")
    if not p["fits"]:
        print(f"  It doesn't fit: the copy needs {gib(int(p['bytes'] * 1.05) + 1024 ** 3)} free on the data disks.")
    for s in p["strays"]:
        print(f"  In the way: {s} is using {p['source']} and isn't a service this can stop. Close it first.")


def app_data_journal(**kw):
    j = read_json(STATE)
    j.update(kw, updated=now())
    write_json(STATE, j)
    return j


def write_fstab(text):
    path = at(FSTAB)
    keep = path + ".before-app-data-move"
    if not os.path.exists(keep):
        shutil.copy2(path, keep)
    tmp = path + ".bromigos-new"
    with open(tmp, "w") as f:
        f.write(text)
        f.flush()
        os.fsync(f.fileno())
    shutil.copymode(path, tmp)
    os.replace(tmp, path)


def app_data_switch(j):
    """The old folder aside, the data disks' apps subvolume in its place. Every step looks
    first, so a move interrupted here carries on from wherever it stopped. fstab goes first:
    from that line on, a restart mounts the verified copy, never an empty folder."""
    src, left, line = j["source"], j["leftover"], j["fstab"]
    with open(at(FSTAB)) as f:
        text = f.read()
    if not any(r[1] == src for r in fstab_rows()):
        write_fstab(text.rstrip("\n") + "\n# the apps' data, on the data disks: their apps subvolume "
                    "(bromigos lab app-data move; docs/server.md)\n" + line + "\n")
    if left and not os.path.lexists(at(left)):
        if is_mount(src):               # a restart came in between: the old folder is under the mount
            must(["umount", at(src)], f"couldn't unmount {src}")
        os.rename(at(src), at(left))
    if not os.path.isdir(at(src)):
        os.mkdir(at(src), 0o755)
    # A container's unit waits for its folders' mounts by itself (Quadlet adds RequiresMountsFor
    # for each Volume= host path). A host service with its data here is told the same, so at a
    # start it comes after the data disks, and stays down while they're away
    for u in j.get("host_units") or []:
        drop = at(f"/etc/systemd/system/{u}.d/50-bromigos-app-data.conf")
        os.makedirs(os.path.dirname(drop), mode=0o755, exist_ok=True)
        with open(drop, "w") as f:
            f.write("# bromigos lab app-data move: this service keeps data under /srv/apps, which is on the data disks\n"
                    f"[Unit]\nRequiresMountsFor={src}\n")
    if not is_mount(src):
        # the mount point takes no files of its own: with the data disks away an app fails to
        # start, and never begins again, empty, on the system disk
        run(["chattr", "+i", at(src)])
        run(["systemctl", "daemon-reload"])
        must(["mount", at(src)], f"couldn't mount the data disks' apps subvolume at {src}")
    if not (is_mount(src) and fs_uuid(src) and fs_uuid(src) == fs_uuid(j["pool"])):
        raise AppDataError(f"{src} is mounted, but not from the data disks")


def app_data_unswitch(j):
    """A switch that failed, undone: the old folder back where the apps look, fstab as it was."""
    src, left = j["source"], j["leftover"]
    if is_mount(src):
        must(["umount", at(src)], f"couldn't unmount {src}")
    if os.path.isdir(at(src)) and (not left or os.path.isdir(at(left))):
        run(["chattr", "-i", at(src)])
        os.rmdir(at(src))                   # the mount point this made: empty, or it stays
    if left and os.path.isdir(at(left)):
        os.rename(at(left), at(src))
    with open(at(FSTAB)) as f:
        lines = f.read().splitlines(keepends=True)
    kept = [l for l in lines if not (l.split()[1:2] == [src] and not l.lstrip().startswith("#"))
            and "bromigos lab app-data move" not in l]
    if kept != lines:
        write_fstab("".join(kept))
    for u in j.get("host_units") or []:
        with contextlib.suppress(OSError):
            os.unlink(at(f"/etc/systemd/system/{u}.d/50-bromigos-app-data.conf"))
    run(["systemctl", "daemon-reload"])


def app_data_move(d, dry):
    j = read_json(STATE)
    if d["pool"] and not d["pool_mounted"]:
        raise AppDataError(f"the data disks aren't mounted ({d['pool']}). `bromigos lab app-data` and `journalctl -b -u "
                           f"{d['pool'].strip('/').replace('/', '-')}.mount` say why; nothing was changed")
    # A move cut off while switching. Past the point where the old folder stopped being the one
    # the apps use (it was renamed, or the data disks are mounted over it), only the switch is
    # left. Before it, the apps may have run on the old folder since: the copy is made again
    # (only what changed) and compared again, below
    left = j.get("leftover") or ""
    if j.get("state") == "switching" and (not left or os.path.lexists(at(left)) or is_mount(j["source"])):
        if dry:
            print(f"bromigos lab app-data: a move stopped while switching {j['source']} over; it would carry on: "
                  + (f"the old copy kept as {left}, " if left else "") + f"the data disks' apps subvolume mounted at {j['source']}, "
                  "the apps started")
            return 0
        units = j.get("units") or []
        for u in units:
            run(["systemctl", "stop", u])
        try:
            app_data_switch(j)
        except (AppDataError, OSError) as e:
            for u in units:
                run(["systemctl", "start", u])
            app_data_journal(error=str(e))
            raise AppDataError(f"{e}. The apps were started again as they were; run this again to carry on") from None
    else:
        if d["state"] == "ok":
            print("bromigos lab app-data: " + app_data_words(d)[0] + ". Nothing to move.")
            return 0
        if d["state"] == "pool-away":
            raise AppDataError(f"{FSTAB} mounts the data disks' apps subvolume at {APPS_DIR}, and it isn't mounted. There's "
                               "nothing to move: the apps' data is on the data disks. `journalctl -b -u srv-apps.mount` says "
                               "why it didn't mount")
        p = app_data_plan(d)
        print_move_plan(p, dry)
        if dry:
            print("  Nothing was changed. Without --dry-run, this does it.")
            return 0 if p["fits"] and not p["strays"] else 1
        if not p["fits"]:
            raise AppDataError("not enough room on the data disks; nothing was changed")
        if p["strays"]:
            raise AppDataError("something is using the apps' data that isn't a service; nothing was changed")
        src, dst = p["source"], p["destination"]
        was = [u for u in p["units"] if unit_state(u) in ("active", "activating", "reloading")]
        j = app_data_journal(state="copying", started=now(), source=src, pool=p["pool"], destination=dst, bytes=p["bytes"],
                             leftover=p["leftover"], fstab=p["fstab"], units=was, host_units=p["host_units"], error="")
        units = was
        try:
            for u in p["units"]:
                run(["systemctl", "stop", u])
            still = [u for u in p["units"] if unit_state(u) in ("active", "activating", "reloading", "deactivating")]
            still += [f"process {pid} ({what})" for pid, what in busy()] + [f"the container {n}" for n in containers_using()]
            if still:
                raise AppDataError(f"still using {src} after the apps were stopped: {', '.join(still)}. Stop it, then run this again")
            if run(["btrfs", "subvolume", "show", at(dst)])[0] != 0:
                if os.path.isdir(at(dst)):
                    os.rmdir(at(dst))               # an empty plain folder: a subvolume takes its place
                must(["btrfs", "subvolume", "create", at(dst)], f"couldn't make the apps subvolume {dst}")
            if p["leftover"]:
                # as `bromigos storage` copies: owners by number, hard links, ACLs, extended attributes, sparse files
                copy = ["rsync", "-aHAXS", "--numeric-ids"]
                print(f"bromigos lab app-data: copying {gib(p['bytes'])} …", flush=True)
                # carrying on from an earlier copy: what has left /srv/apps since leaves the copy too
                must([*copy, *(["--delete"] if p["resuming"] else []), "--", at(src) + "/", at(dst) + "/"],
                     "the copy didn't finish", timeout=None)
                app_data_journal(state="verifying")
                print("bromigos lab app-data: comparing every file with its copy …", flush=True)
                diff = must([*copy, "--checksum", "--dry-run", "--delete", "--itemize-changes", "--out-format=%i %n", "--",
                             at(src) + "/", at(dst) + "/"], "the comparison didn't finish", timeout=None)
                if diff.strip():
                    raise AppDataError(f"{len(diff.strip().splitlines())} files differ from their copies, the first: "
                                       f"{diff.strip().splitlines()[0]}. Something wrote to {src} during the copy")
                run(["sync"])
        except (AppDataError, OSError) as e:
            # nothing switched: the apps go on as they were, on the system disk; the copy so far
            # stays on the data disks, and the next run carries on from it
            for u in units:
                run(["systemctl", "start", u])
            app_data_journal(state="failed", error=str(e))
            raise AppDataError(f"{e}. The apps are running again, on the system disk as before; nothing of theirs was changed") from None
        j = app_data_journal(state="switching")
        try:
            app_data_switch(j)
        except (AppDataError, OSError) as e:
            try:
                app_data_unswitch(j)
            except (AppDataError, OSError) as e2:
                app_data_journal(error=f"{e}; putting it back: {e2}")
                raise AppDataError(f"{e}, and putting it back didn't work either ({e2}). The apps are stopped; their data is "
                                   f"safe, in {j['leftover']} or {src} and in {dst}. Run this again to carry on") from None
            for u in units:
                run(["systemctl", "start", u])
            app_data_journal(state="failed", error=str(e))
            raise AppDataError(f"{e}. It was put back: the apps are running again, on the system disk as before") from None
    for u in units:
        run(["systemctl", "start", u])
    j = app_data_journal(state="done", finished=now(), error="")
    print(f"bromigos lab app-data: the apps' data is on the data disks now ({j['source']} is {j['destination']})"
          + (f", and the apps are running again. The old copy is kept at {j['leftover']}: once you've seen the apps have "
             "everything, sudo bromigos lab app-data remove-old deletes it." if j["leftover"] else "."))
    return 0


def main(argv=None):
    p = argparse.ArgumentParser(prog="bromigos lab app-data",
                                description="Where this server's apps keep their data, and the move onto its data disks")
    p.add_argument("verb", nargs="?", choices=["status", "move", "remove-old"], default="status")
    p.add_argument("--json", action="store_true", help="status: as JSON")
    p.add_argument("--dry-run", action="store_true", help="move: say what it would do, and change nothing")
    a = p.parse_args(argv)
    d = status()
    if a.verb == "status":
        if a.json:
            print(json.dumps(d, indent=1))
        else:
            print("App data: " + "\n          ".join(d["words"]))
        return 0
    if os.geteuid() != 0 and os.environ.get("BROMIGOS_ROOT", "/") == "/":
        print(f"bromigos lab app-data: {a.verb} needs root: sudo bromigos lab app-data {a.verb}"
              + (" --dry-run" if a.dry_run else ""), file=sys.stderr)
        return 1
    os.makedirs(os.path.dirname(at(STATE)), mode=0o755, exist_ok=True)
    with open(at(STATE) + ".lock", "w") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            print("bromigos lab app-data: a move of the apps' data is running already", file=sys.stderr)
            return 1
        try:
            if a.verb == "move":
                return app_data_move(d, a.dry_run)
            left = d["leftover"]
            if not left:
                print("bromigos lab app-data: there's no old copy of the apps' data to remove")
                return 0
            if d["state"] != "ok" or d["where"] != "pool":
                raise AppDataError(f"the apps' data isn't on the data disks right now, so the old copy ({left}) stays")
            if not left.startswith(LEFTOVER) or is_mount(left):
                raise AppDataError(f"{left} isn't an old copy a move left")
            size = tree_bytes(left)
            shutil.rmtree(at(left))
            app_data_journal(leftover="", removed=now())
            print(f"bromigos lab app-data: removed the old copy, {left} ({gib(size)} back on the system disk)")
            return 0
        except (AppDataError, OSError) as e:
            print(f"bromigos lab app-data: {e}", file=sys.stderr)
            return 1


if __name__ == "__main__":
    sys.exit(main())
