"""`bromigos lab app-data`: where this server's apps keep their data, and the move that puts it
on the data disks (docs/server.md, "Where the apps keep their data").

    bromigos lab app-data [status] [--json]     where /srv/apps is, against where it's meant to be
    bromigos lab app-data move [--dry-run]      as root: from the system disk to the data disks
    bromigos lab app-data remove-old            as root: deletes the old copies a move kept

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

The media library (/srv/media) and the backups other machines keep here (/srv/backups) are on
the data disks the same way, each in a subvolume of its own (FOLDERS). The same move takes each
in turn, with a record per folder (app-data-media.json, app-data-backups.json).

The passwords vault (Vaultwarden, a package) is a folder under /srv/apps like every app's:
/srv/apps/passwords. A server set up before it was has the vault in /var/lib/vaultwarden, on
the system disk. On a server with data disks the move takes it last, by the same steps, and
then tells the service where its vault is (VAULT_DROPIN, VAULT_ENV).
"""
import argparse
import contextlib
import datetime
import fcntl
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import time
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
# What a server with data disks keeps on them: (the folder, the data disks' subvolume mounted
# there, what it holds). The installer makes each subvolume and its fstab line; the move does
# the same on a server set up before the installer did
FOLDERS = ((APPS_DIR, "apps", "the apps' data"),
           ("/srv/media", "media", "the media library"),
           ("/srv/backups", "backups", "the folder for other machines' backups"))
STATE = "/var/lib/bromigos/lab/app-data.json"       # the move's own record (state_file: one per folder)
FSTAB = "/etc/fstab"
QUADLETS = "/etc/containers/systemd"
LEFTOVER = ".on-system-disk-"                   # the old copy's name after a move: the folder's, this, its date
# The media library on a NAS share (bromigos lab provision --local, "On a NAS"): these units
# mount the share at /srv/media, so that folder isn't meant to be on the data disks
MEDIA_NAS = ("/etc/systemd/system/srv-media.mount", "/etc/systemd/system/bromigos-media-mount.service")
# The passwords vault. Vaultwarden is a package: its own file (/etc/vaultwarden.env) puts the
# vault in /var/lib/vaultwarden, on the system disk, and its unit may write nowhere else. The
# engine gives it a folder like every app's, and these two files tell the service: a later
# EnvironmentFile wins over the package's, where Environment= would lose to it
VAULT_OLD, VAULT = "/var/lib/vaultwarden", APPS_DIR + "/passwords"
VAULT_UNIT = "vaultwarden.service"
VAULT_ENV = "/etc/bromigos/lab/passwords.env"
VAULT_DROPIN = "/etc/systemd/system/vaultwarden.service.d/60-bromigos-data.conf"
VAULT_ENV_TEXT = ("# bromigOS: the passwords vault is with the other apps' data (docs/server.md, \"Where the apps keep\n"
                  f"# their data\"). Read after /etc/vaultwarden.env, so this line is the one that counts\nDATA_FOLDER={VAULT}\n")
VAULT_DROPIN_TEXT = ("# bromigOS: the passwords vault is with the other apps' data. On a server with data disks that\n"
                     "# is on them: the service starts once they're mounted, and not at all while they're away\n"
                     f"[Unit]\nRequiresMountsFor={VAULT}\n\n[Service]\nReadWritePaths={VAULT}\nEnvironmentFile={VAULT_ENV}\n")
MOVING = ("copying", "verifying", "switching")
RUNNING = ("active", "activating", "reloading")
SETTLE = 5                      # seconds Vaultwarden is given on its new folder before it's believed


def state_file(src=APPS_DIR):
    """A move's record: app-data.json for /srv/apps, app-data-NAME.json for another folder."""
    return STATE if src == APPS_DIR else STATE.removesuffix(".json") + f"-{os.path.basename(src)}.json"


def has_files(path):
    try:
        return bool(os.listdir(at(path)))
    except OSError:
        return False


def is_vault(folder):
    """Whether a folder (as it is on disk) holds a Vaultwarden vault: its database, its keys,
    or what people attached. The folder is the service's own, so a person asking for the
    status can't list it: there and not readable counts as the vault's."""
    try:
        names = os.listdir(folder)
    except PermissionError:
        return True
    except OSError:
        return False
    return any(n.startswith(("db.sqlite3", "rsa_key")) or n in ("attachments", "sends", "config.json") for n in names)


def vault_in(path):
    return is_vault(at(path))


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


def folder_doc(src, pool, rows, on_pool):
    """One folder against where this server means it to be (app_data_doc's states). `where` is
    pool, system, or elsewhere: something else is mounted there, or meant to be (the media
    library on a NAS share, a backup drive of the owner's with its own fstab line). That is
    where its owner put it, and it is left alone, mounted or not."""
    j = read_json(state_file(src))
    left = j.get("leftover") or ""
    d = {"path": src, "where": "system", "state": "ok", "has_data": has_files(src), "move": j.get("state") or "",
         "running": False, "leftover": left if left and j.get("state") == "done" and os.path.isdir(at(left)) else ""}
    if not pool:
        return d
    pool_device = next((r[0] for r in rows if r[1] == pool), "")
    if on_pool and is_mount(src) and fs_uuid(src) == on_pool:
        d["where"] = "pool"
    elif src != APPS_DIR and (is_mount(src) or any(r[1] == src and r[0] != pool_device for r in rows)
                              or (src == "/srv/media" and any(os.path.exists(at(u)) for u in MEDIA_NAS))):
        d["where"] = "elsewhere"
    elif any(r[1] == src for r in rows):
        d["state"] = "pool-away"
    else:
        d["state"] = "not-on-pool"
    if j.get("state") in MOVING:
        d["state"], d["running"] = "moving", move_running()
    return d


def app_data_doc():
    """Where /srv/apps is, against where this server means it to be: its data disks' apps
    subvolume when it has data disks, else the system disk. `state`:
      ok            where it's meant to be (`where`: pool or system)
      not-on-pool   the server has data disks, and the apps' data is on the system disk
      pool-away     fstab puts /srv/apps on the data disks, and it isn't mounted
      moving        a move is under way (`running`), or one was cut off (`move`: how far it got)
    `folders`: the same for the media library and the backups folder, on a server with data
    disks. `elsewhere`: the passwords vault, while it is still in the package's own folder.
    `vault`: that vault's move (`move`, `leftover`)."""
    st = storage()
    rows = fstab_rows()
    pool = (st.get("mount") or POOL) if st.get("disks") else next((r[1] for r in rows if r[1] == POOL and r[2] == "btrfs"), "")
    on_pool = (is_mount(pool) and fs_uuid(pool)) if pool else ""
    doc = folder_doc(APPS_DIR, pool, rows, on_pool)
    doc.update(pool=pool, pool_mounted=bool(on_pool), raid1=st.get("layout") == "raid1" and len(st.get("disks") or []) >= 2,
               elsewhere=[], folders=[], vault={})
    if not pool:
        return doc
    doc["folders"] = [folder_doc(src, pool, rows, on_pool) for src, _, _ in FOLDERS[1:]]
    j = read_json(state_file(VAULT_OLD))
    left = j.get("leftover") or ""
    doc["vault"] = {"move": j.get("state") or "",
                    "leftover": left if left and j.get("state") == "done" and os.path.isdir(at(left)) else ""}
    # the vault is where the service is pointed: the package's folder until VAULT_DROPIN says otherwise
    if vault_in(VAULT_OLD) and not os.path.exists(at(VAULT_DROPIN)):
        doc["elsewhere"] = [{"path": VAULT_OLD, "what": "passwords (Vaultwarden)"}]
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
    for f in d.get("folders") or []:
        words += folder_words(f, d)
    unfinished = (d.get("vault") or {}).get("move") in (*MOVING, "failed")
    for e in d.get("elsewhere") or []:
        words.append(f"not on the data disks: {e['what']} keeps its data in {e['path']}, on the system disk; "
                     + ("a move of it didn't finish, and sudo bromigos lab app-data move carries on" if unfinished else
                        "sudo bromigos lab app-data move puts it with the other apps' data"))
    if unfinished and not d.get("elsewhere"):
        words.append(f"passwords (Vaultwarden): a move of its vault to {VAULT} didn't finish; sudo bromigos lab app-data move carries on")
    left = (d.get("vault") or {}).get("leftover")
    if left:
        words.append(f"the passwords vault's old copy is kept at {left}; sudo bromigos lab app-data remove-old deletes it")
    return words


def folder_words(f, d):
    """A line for the media library or the backups folder, only when there's something to do or
    to know: a folder nobody uses yet says nothing, and the move sets it up with the rest."""
    what = next(w for src, _, w in FOLDERS if src == f["path"])
    if f["state"] == "moving":
        return [f"{what} ({f['path']}): moving to the data disks now" if f["running"] else
                f"{what} ({f['path']}): a move to the data disks didn't finish; sudo bromigos lab app-data move carries on"]
    if f["state"] == "pool-away":
        return [f"{what} ({f['path']}): on the data disks, which aren't mounted ({d['pool']})"]
    if f["state"] == "not-on-pool" and f["has_data"]:
        return [f"{what} ({f['path']}): on the system disk, not the data disks; sudo bromigos lab app-data move puts it on them"]
    if f["leftover"]:
        return [f"{what}: the old copy is kept at {f['leftover']}; sudo bromigos lab app-data remove-old deletes it"]
    return []


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


def app_units(src=APPS_DIR):
    """The services that keep data under a folder (/srv/apps): every Quadlet that names it, and
    whatever else has a file open there now (a host service such as Syncthing), by its unit.
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
        if re.search(rf"{src}(/|:|\s|$)", text, re.M):
            m = re.search(r"^ServiceName=(\S+)", text, re.M)
            units.append((m.group(1) if m else name.removesuffix(".container")) + ".service")
    for pid, what in busy(src):
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


def busy(src=APPS_DIR):
    """[(pid, a path)]: processes with a working folder, an open file or a mapped file under
    the folder. A container's own view of its files isn't here: its mounts are asked of Podman."""
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
        hit = next((v for v in seen if v == src or v.startswith(src + "/")), None)
        if hit:
            out.append((pid, hit))
    return out


def containers_using(src=APPS_DIR):
    """Running containers that mount something under the folder: [name]."""
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
            if any(str(m.get("Source", "")) == src or str(m.get("Source", "")).startswith(src + "/")
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


def old_copy_name(src):
    left = src + LEFTOVER + datetime.date.today().isoformat()
    return left + ("-" + datetime.datetime.now().strftime("%H%M%S") if os.path.lexists(at(left)) else "")


def app_data_plan(d, src=APPS_DIR, sub="apps", what="the apps' data"):
    """What a move would do, checked: the source, the pool and its fstab line, the folder's
    subvolume (made if it isn't there), the space, the services to stop and the old copy's name."""
    pool = d["pool"]
    row = next((r for r in fstab_rows() if r[1] == pool), None)
    if not row or row[2] != "btrfs":
        raise AppDataError(f"the data disks ({pool}) aren't a btrfs line in {FSTAB}, so there's nothing to mount {src} from")
    dst = os.path.join(pool, sub)
    j = read_json(state_file(src))
    resuming = j.get("state") in (*MOVING, "failed") and j.get("destination") == dst
    there = has_files(src)                  # nothing in it: nothing to copy or keep, and the folder is the mount point
    theirs = sorted(os.listdir(at(dst))) if os.path.isdir(at(dst)) and not resuming else []
    if theirs and there:
        raise AppDataError(f"{dst} already has files in it ({', '.join(theirs[:5])}), and they aren't from a move of {what}. "
                           "Nothing was changed: move them away first, so nothing of yours is overwritten")
    if is_mount(src):
        raise AppDataError(f"{src} is a mount of its own, not a folder on the system disk: this moves only the folder "
                           f"{what} was given. Nothing was changed")
    need, free = tree_bytes(src) if there else 0, shutil.disk_usage(at(pool)).free
    if there and not shutil.which("rsync"):
        raise AppDataError("rsync isn't installed, and the copy is made with it. Install the rsync package, then run this again")
    units, hosts, strays = app_units(src)
    opts = ",".join(o for o in row[3].split(",") if not o.startswith(("subvol=", "subvolid=")))
    return {"source": src, "pool": pool, "destination": dst, "bytes": need, "free": free, "what": what, "sub": sub,
            # room for the copy, and some over: btrfs needs space of its own, and the apps start again after
            "fits": free >= int(need * 1.05) + 1024 ** 3,
            "units": units, "host_units": hosts, "strays": strays, "leftover": old_copy_name(src) if there else "",
            "theirs": theirs,               # files of the owner's in the subvolume already, with nothing to copy over them
            "fstab": f"{row[0]}  {src}  btrfs  subvol=/{sub},{opts}  0 0", "resuming": resuming}


def print_move_plan(p, dry):
    will = "would" if dry else "will"
    if not p["leftover"]:
        print((f"bromigos lab app-data: no app has data yet. The data disks' apps subvolume ({p['destination']}) {will} be mounted "
               f"at {p['source']}, so the apps keep their data on the data disks from the start:") if p["sub"] == "apps" else
              (f"bromigos lab app-data: nothing is in {p['source']} yet. The data disks' {p['sub']} subvolume ({p['destination']}) "
               f"{will} be mounted there, so {p['what']} is on the data disks from the start:"))
        print(f"       {p['fstab']}")
        if p["theirs"]:
            print(f"  {p['destination']} has files in it already ({', '.join(p['theirs'][:5])}). They stay as they are, and "
                  f"show at {p['source']} too.")
        return
    print(f"bromigos lab app-data: {p['what']} ({gib(p['bytes'])} in {p['source']}, on the system disk) {will} move to the data "
          f"disks ({p['destination']}, {gib(p['free'])} free)")
    print(f"  1. stop the apps: {', '.join(p['units']) or 'none is set up'}")
    print(f"  2. copy {p['source']} to {p['destination']}" + (" (carrying on from the copy already there; what's no longer in "
                                                                 f"{p['source']} leaves the copy too)" if p["resuming"] else ""))
    print("  3. compare every file with its copy, by checksum; any difference stops here, with nothing changed")
    print(f"  4. keep the old copy as {p['leftover']}, and mount the data disks' {p['sub']} subvolume at {p['source']}:")
    print(f"       {p['fstab']}")
    print("  5. start the apps again")
    if not p["fits"]:
        print(f"  It doesn't fit: the copy needs {gib(int(p['bytes'] * 1.05) + 1024 ** 3)} free on the data disks.")
    for s in p["strays"]:
        print(f"  In the way: {s} is using {p['source']} and isn't a service this can stop. Close it first.")


def app_data_journal(src=APPS_DIR, **kw):
    j = read_json(state_file(src))
    j.update(kw, updated=now())
    write_json(state_file(src), j)
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


def host_dropin(unit, src):
    return f"/etc/systemd/system/{unit}.d/50-bromigos-app-data" + ("" if src == APPS_DIR else "-" + os.path.basename(src)) + ".conf"


def fstab_mark(src):
    """What the comment over a folder's fstab line says made it."""
    return "bromigos lab app-data move" + ("" if src == APPS_DIR else f", {src}")


def app_data_switch(j):
    """The old folder aside, the data disks' apps subvolume in its place. Every step looks
    first, so a move interrupted here carries on from wherever it stopped. fstab goes first:
    from that line on, a restart mounts the verified copy, never an empty folder."""
    src, left, line = j["source"], j["leftover"], j["fstab"]
    with open(at(FSTAB)) as f:
        text = f.read()
    if not any(r[1] == src for r in fstab_rows()):
        write_fstab(text.rstrip("\n") + f"\n# {j.get('what') or FOLDERS[0][2]}, on the data disks: their "
                    f"{j.get('sub') or 'apps'} subvolume ({fstab_mark(src)}; docs/server.md)\n" + line + "\n")
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
        drop = at(host_dropin(u, src))
        os.makedirs(os.path.dirname(drop), mode=0o755, exist_ok=True)
        with open(drop, "w") as f:
            f.write(f"# bromigos lab app-data move: this service keeps data under {src}, which is on the data disks\n"
                    f"[Unit]\nRequiresMountsFor={src}\n")
    if not is_mount(src):
        # the mount point takes no files of its own: with the data disks away an app fails to
        # start, and never begins again, empty, on the system disk
        run(["chattr", "+i", at(src)])
        run(["systemctl", "daemon-reload"])
        must(["mount", at(src)], f"couldn't mount the data disks' {j.get('sub') or 'apps'} subvolume at {src}")
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
            and f"({fstab_mark(src)};" not in l]
    if kept != lines:
        write_fstab("".join(kept))
    for u in j.get("host_units") or []:
        with contextlib.suppress(OSError):
            os.unlink(at(host_dropin(u, src)))
    run(["systemctl", "daemon-reload"])


def copy_and_compare(src, dst, size, resuming):
    """The copy, then every file against its copy by checksum. Any difference raises: something
    wrote to the source while it was read, and nothing may be switched to a copy like that."""
    # as `bromigos storage` copies: owners by number, hard links, ACLs, extended attributes, sparse files
    copy = ["rsync", "-aHAXS", "--numeric-ids"]
    print(f"bromigos lab app-data: copying {gib(size)} …", flush=True)
    # carrying on from an earlier copy: what has left the source since leaves the copy too
    must([*copy, *(["--delete"] if resuming else []), "--", at(src) + "/", at(dst) + "/"],
         "the copy didn't finish", timeout=None)
    app_data_journal(src, state="verifying")
    print("bromigos lab app-data: comparing every file with its copy …", flush=True)
    diff = must([*copy, "--checksum", "--dry-run", "--delete", "--itemize-changes", "--out-format=%i %n", "--",
                 at(src) + "/", at(dst) + "/"], "the comparison didn't finish", timeout=None)
    if diff.strip():
        raise AppDataError(f"{len(diff.strip().splitlines())} files differ from their copies, the first: "
                           f"{diff.strip().splitlines()[0]}. Something wrote to {src} during the copy")
    run(["sync"])


def app_data_move(d, dry):
    """Each folder that isn't on the data disks, in turn: the apps' data first, then the media
    library and the backups folder, then the passwords vault into the apps' folder. Everything
    waits for the apps' data: if that can't move, nothing else is tried. After it, one that
    can't move is said and left as it was, and doesn't hold the others back: files in the way of
    the backups folder must never keep the passwords off the data disks."""
    if d["pool"] and not d["pool_mounted"]:
        raise AppDataError(f"the data disks aren't mounted ({d['pool']}). `bromigos lab app-data` and `journalctl -b -u "
                           f"{d['pool'].strip('/').replace('/', '-')}.mount` say why; nothing was changed")
    todo = [f for f in (d, *d["folders"]) if f["state"] != "ok"]
    vault = bool(d["pool"]) and vault_waiting()
    if not todo and not vault:
        print("bromigos lab app-data: " + _words(d)[0] + ". Nothing to move.")
        return 0
    rc = 0
    for f in todo:
        try:
            rc = move_folder(d, f, *next(x[1:] for x in FOLDERS if x[0] == f["path"]), dry) or rc
        except AppDataError as e:
            if f["path"] == APPS_DIR:
                raise
            print(f"bromigos lab app-data: {e}", file=sys.stderr)
            rc = 1
    if vault:
        rc = vault_move(dry) or rc
    return rc


def move_folder(d, f, sub, what, dry):
    src = f["path"]
    j = read_json(state_file(src))
    # A move cut off while switching. Past the point where the old folder stopped being the one
    # the apps use (it was renamed, or the data disks are mounted over it), only the switch is
    # left. Before it, the apps may have run on the old folder since: the copy is made again
    # (only what changed) and compared again, below
    left = j.get("leftover") or ""
    if j.get("state") == "switching" and (not left or os.path.lexists(at(left)) or is_mount(j["source"])):
        if dry:
            print(f"bromigos lab app-data: a move stopped while switching {j['source']} over; it would carry on: "
                  + (f"the old copy kept as {left}, " if left else "") + f"the data disks' {sub} subvolume mounted at {j['source']}, "
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
            app_data_journal(src, error=str(e))
            raise AppDataError(f"{e}. The apps were started again as they were; run this again to carry on") from None
    else:
        if f["state"] == "pool-away":
            raise AppDataError(f"{FSTAB} mounts the data disks' {sub} subvolume at {src}, and it isn't mounted. There's "
                               f"nothing to move: {what} is on the data disks. `journalctl -b -u "
                               f"{src.strip('/').replace('/', '-')}.mount` says why it didn't mount")
        p = app_data_plan(d, src, sub, what)
        print_move_plan(p, dry)
        if dry:
            print("  Nothing was changed. Without --dry-run, this does it.")
            return 0 if p["fits"] and not p["strays"] else 1
        if not p["fits"]:
            raise AppDataError("not enough room on the data disks; nothing was changed")
        if p["strays"]:
            raise AppDataError(f"something is using {src} that isn't a service; nothing was changed")
        dst = p["destination"]
        was = [u for u in p["units"] if unit_state(u) in ("active", "activating", "reloading")]
        j = app_data_journal(src, state="copying", started=now(), source=src, pool=p["pool"], destination=dst, bytes=p["bytes"],
                             leftover=p["leftover"], fstab=p["fstab"], units=was, host_units=p["host_units"], error="",
                             what=what, sub=sub)
        units = was
        try:
            for u in p["units"]:
                run(["systemctl", "stop", u])
            still = [u for u in p["units"] if unit_state(u) in ("active", "activating", "reloading", "deactivating")]
            still += [f"process {pid} ({path})" for pid, path in busy(src)] + [f"the container {n}" for n in containers_using(src)]
            if still:
                raise AppDataError(f"still using {src} after the apps were stopped: {', '.join(still)}. Stop it, then run this again")
            if run(["btrfs", "subvolume", "show", at(dst)])[0] != 0:
                if has_files(dst):
                    raise AppDataError(f"{dst} is a plain folder with files in it, not a subvolume, so it can't be mounted "
                                       f"at {src}. Move the files away first")
                if os.path.isdir(at(dst)):
                    os.rmdir(at(dst))               # an empty plain folder: a subvolume takes its place
                must(["btrfs", "subvolume", "create", at(dst)], f"couldn't make the {sub} subvolume {dst}")
            if p["leftover"]:
                copy_and_compare(src, dst, p["bytes"], p["resuming"])
        except (AppDataError, OSError) as e:
            # nothing switched: the apps go on as they were, on the system disk; the copy so far
            # stays on the data disks, and the next run carries on from it
            for u in units:
                run(["systemctl", "start", u])
            app_data_journal(src, state="failed", error=str(e))
            raise AppDataError(f"{e}. The apps are running again, on the system disk as before; nothing of theirs was changed") from None
        j = app_data_journal(src, state="switching")
        try:
            app_data_switch(j)
        except (AppDataError, OSError) as e:
            try:
                app_data_unswitch(j)
            except (AppDataError, OSError) as e2:
                app_data_journal(src, error=f"{e}; putting it back: {e2}")
                raise AppDataError(f"{e}, and putting it back didn't work either ({e2}). The apps are stopped; their data is "
                                   f"safe, in {j['leftover']} or {src} and in {dst}. Run this again to carry on") from None
            for u in units:
                run(["systemctl", "start", u])
            app_data_journal(src, state="failed", error=str(e))
            raise AppDataError(f"{e}. It was put back: the apps are running again, on the system disk as before") from None
    for u in units:
        run(["systemctl", "start", u])
    j = app_data_journal(src, state="done", finished=now(), error="")
    print(f"bromigos lab app-data: {what} is on the data disks now ({j['source']} is {j['destination']})"
          + (f", and the apps are running again. The old copy is kept at {j['leftover']}: once you've seen the apps have "
             "everything, sudo bromigos lab app-data remove-old deletes it." if j["leftover"] else "."))
    return 0


def vault_waiting():
    """Whether the passwords vault has a move to make, or one to finish."""
    return vault_in(VAULT_OLD) or read_json(state_file(VAULT_OLD)).get("state") == "switching"


def vault_switch(j):
    """The service told where its vault is, then the old folder set aside by name, and an empty
    one in its place: the package's unit starts in that folder and lists it as writable. Every
    step looks first, so a move cut off here carries on. VAULT_DROPIN is the switch itself: once
    it is there, every start uses the new folder, and nothing is ever copied over that folder
    again (vault_move)."""
    old, left = j["source"], j["leftover"]
    for path, text in ((VAULT_ENV, VAULT_ENV_TEXT), (VAULT_DROPIN, VAULT_DROPIN_TEXT)):
        os.makedirs(os.path.dirname(at(path)), mode=0o755, exist_ok=True)
        with open(at(path) + ".tmp", "w") as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        os.chmod(at(path) + ".tmp", 0o644)
        os.replace(at(path) + ".tmp", at(path))
    run(["systemctl", "daemon-reload"])
    if vault_in(old) and not os.path.lexists(at(left)):
        os.rename(at(old), at(left))
    if not os.path.isdir(at(old)):
        st = os.stat(at(left))
        os.mkdir(at(old), stat.S_IMODE(st.st_mode))
        os.chown(at(old), st.st_uid, st.st_gid)


def vault_unswitch(j):
    """A switch that failed, undone: the service stopped, its vault back in the folder it was
    in, the two files that pointed it elsewhere gone. Nothing is deleted: a vault the service
    made from nothing in the old folder's place is set aside by name."""
    old, left = j["source"], j["leftover"]
    run(["systemctl", "stop", VAULT_UNIT])
    for path in (VAULT_DROPIN, VAULT_ENV):
        with contextlib.suppress(OSError):
            os.unlink(at(path))
    if os.path.isdir(at(left)):
        if has_files(old):
            os.rename(at(old), at(old + ".started-empty-" + datetime.datetime.now().strftime("%Y-%m-%d-%H%M%S")))
        elif os.path.isdir(at(old)):
            os.rmdir(at(old))
        os.rename(at(left), at(old))
    run(["systemctl", "daemon-reload"])


def vault_move(dry):
    """The passwords vault from the package's folder (/var/lib/vaultwarden, the system disk) to
    the apps' folder (/srv/apps/passwords), on a server whose apps' data is on its data disks.
    The same steps as a folder's move: Vaultwarden stopped, the copy, every file compared, the
    old folder kept by name, Vaultwarden started. It isn't believed until it is up on the new
    folder and has made nothing in the old one; otherwise everything is put back."""
    old, new = VAULT_OLD, VAULT
    j = read_json(state_file(old))
    will = "would" if dry else "will"
    if os.path.exists(at(VAULT_DROPIN)) or (j.get("state") == "switching" and not vault_in(old)):
        # A move cut off while switching. Vaultwarden is pointed at the new folder already, and
        # may have run on it since (a restart starts it there). So nothing is copied over the
        # new folder again: only the rest of the switch is left
        left = j.get("leftover") or old_copy_name(old)
        if dry:
            print(f"bromigos lab app-data: a move of the passwords vault stopped while switching over; it would carry on: "
                  f"the old copy kept as {left}, Vaultwarden started on {new}")
            return 0
        was = bool(j.get("was_running", unit_state(VAULT_UNIT) in RUNNING))     # no record of it: as it is now
        run(["systemctl", "stop", VAULT_UNIT])
        j = app_data_journal(old, state="switching", source=old, destination=new, leftover=left, was_running=was)
    else:
        if app_data_doc()["where"] != "pool":
            print(f"bromigos lab app-data: the passwords vault ({old}) {will} move to {new} once the apps' data is on the data disks")
            return 0 if dry else 1
        resuming = j.get("state") in (*MOVING, "failed") and j.get("destination") == new
        if has_files(new) and not resuming:
            raise AppDataError(f"{new} already has files in it, and they aren't from a move of the passwords vault. Nothing was "
                               f"changed, and Vaultwarden goes on using {old}: move them away first, so no vault is overwritten")
        need, free = tree_bytes(old), shutil.disk_usage(at(APPS_DIR)).free
        fits = free >= int(need * 1.05) + 1024 ** 3
        left = old_copy_name(old)
        print(f"bromigos lab app-data: the passwords vault ({gib(need)} in {old}, on the system disk) {will} move to the data "
              f"disks, with the other apps' data ({new})")
        print(f"  1. stop Vaultwarden ({VAULT_UNIT})")
        print(f"  2. copy {old} to {new}" + (" (carrying on from the copy already there)" if resuming else ""))
        print("  3. compare every file with its copy, by checksum; any difference stops here, with nothing changed")
        print(f"  4. keep the old copy as {left}, and tell Vaultwarden where its vault is ({VAULT_DROPIN})")
        print("  5. start Vaultwarden, and check it is using the new folder; if it isn't, everything is put back")
        if not fits:
            print(f"  It doesn't fit: the copy needs {gib(int(need * 1.05) + 1024 ** 3)} free on the data disks.")
        if dry:
            print("  Nothing was changed. Without --dry-run, this does it.")
            return 0 if fits else 1
        if not fits:
            raise AppDataError("not enough room on the data disks for the passwords vault; nothing was changed")
        if not shutil.which("rsync"):
            raise AppDataError("rsync isn't installed, and the copy is made with it. Install the rsync package, then run this again")
        was = unit_state(VAULT_UNIT) in RUNNING
        app_data_journal(old, state="copying", started=now(), source=old, destination=new, bytes=need, leftover=left,
                         was_running=was, error="")
        try:
            run(["systemctl", "stop", VAULT_UNIT])
            still = [VAULT_UNIT] if unit_state(VAULT_UNIT) in (*RUNNING, "deactivating") else []
            still += [f"process {pid} ({path})" for pid, path in busy(old)]
            if still:
                raise AppDataError(f"still using {old} after Vaultwarden was stopped: {', '.join(still)}. Stop it, then run this again")
            os.makedirs(at(new), mode=0o700, exist_ok=True)
            copy_and_compare(old, new, need, resuming)
        except (AppDataError, OSError) as e:
            # nothing switched: Vaultwarden goes on as it was, and the next run carries on from the copy so far
            if was:
                run(["systemctl", "start", VAULT_UNIT])
            app_data_journal(old, state="failed", error=str(e))
            raise AppDataError(f"{e}. Vaultwarden is " + ("running again" if was else "as it was") + f", on {old} as before; "
                               "nothing of its was changed") from None
        j = app_data_journal(old, state="switching")
    try:
        vault_switch(j)
        if was:
            must(["systemctl", "start", VAULT_UNIT], "Vaultwarden didn't start on its new folder")
            time.sleep(SETTLE)
            if unit_state(VAULT_UNIT) not in RUNNING:
                raise AppDataError(f"Vaultwarden didn't stay up on its new folder (journalctl -u {VAULT_UNIT} says why)")
            if vault_in(old):
                raise AppDataError(f"Vaultwarden started on {old} again, not on {new}")
    except (AppDataError, OSError) as e:
        try:
            vault_unswitch(j)
        except (AppDataError, OSError) as e2:
            app_data_journal(old, error=f"{e}; putting it back: {e2}")
            raise AppDataError(f"{e}, and putting it back didn't work either ({e2}). Vaultwarden is stopped; the vault is whole "
                               f"in {j['leftover']} or {old}, and in {new}. Run this again to carry on") from None
        if was:
            run(["systemctl", "start", VAULT_UNIT])
        app_data_journal(old, state="failed", error=str(e))
        raise AppDataError(f"{e}. It was put back: Vaultwarden is " + ("running again" if was else "as it was")
                           + f", on {old} as before") from None
    j = app_data_journal(old, state="done", finished=now(), error="")
    print(f"bromigos lab app-data: the passwords vault is with the other apps' data now ({new})"
          + (", and Vaultwarden is running again" if was else "") + f". The old copy is kept at {j['leftover']}: once you've "
          "signed in and seen your passwords, sudo bromigos lab app-data remove-old deletes it.")
    return 0


def remove_old(d):
    """The old copies a move kept, deleted: each only while what it was a copy of is on the data disks."""
    on_pool = d["state"] == "ok" and d["where"] == "pool"
    olds = [(f["path"], next(w for src, _, w in FOLDERS if src == f["path"]), f["leftover"], f["state"] == "ok" and f["where"] == "pool")
            for f in (d, *d["folders"]) if f["leftover"]]
    if (d.get("vault") or {}).get("leftover"):
        olds.append((VAULT_OLD, "the passwords vault", d["vault"]["leftover"], on_pool and not d["elsewhere"]))
    if not olds:
        print("bromigos lab app-data: there's no old copy of the apps' data to remove")
        return 0
    for src, what, left, safe in olds:
        if not safe:
            raise AppDataError(f"{what} isn't on the data disks right now, so the old copy ({left}) stays")
        if not left.startswith(src + LEFTOVER) or is_mount(left):
            raise AppDataError(f"{left} isn't an old copy a move left")
        size = tree_bytes(left)
        shutil.rmtree(at(left))
        app_data_journal(src, leftover="", removed=now())
        print(f"bromigos lab app-data: removed the old copy, {left} ({gib(size)} back on the system disk)")
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
            return remove_old(d)
        except (AppDataError, OSError) as e:
            print(f"bromigos lab app-data: {e}", file=sys.stderr)
            return 1


if __name__ == "__main__":
    sys.exit(main())
