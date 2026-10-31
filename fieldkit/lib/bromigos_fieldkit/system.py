"""The machine Field Kit runs on, and the bromigOS install it works on (docs/fieldkit.md).

Everything here runs commands through `run()`, so tests swap in a fake. Paths into the
install go through `Target.path()`: Field Kit's live system works on an install mounted at
/mnt/bromigos; the same code on an installed system works on "/".
"""

import json
import os
import shutil
import socket
import subprocess
import time
from dataclasses import dataclass, field

MOUNT = os.environ.get("BROMIGOS_FIELDKIT_MOUNT", "/mnt/bromigos")
TOP = os.environ.get("BROMIGOS_FIELDKIT_TOP", "/run/bromigos-fieldkit/top")
STATE = os.environ.get("BROMIGOS_FIELDKIT_STATE", "/run/bromigos-fieldkit/state.json")
MAPPER = "bromigos-root"


class Failed(Exception):
    """A step that didn't work, in plain words."""


def run(cmd, *, input=None, check=True, timeout=None, env=None):
    """A command's result (stdout, stderr as text). Failed with its last line when check and
    it fails."""
    try:
        r = subprocess.run(cmd, input=input, capture_output=True, text=True, timeout=timeout, env=env)
    except FileNotFoundError:
        raise Failed(f"{cmd[0]} isn't on this system") from None
    except subprocess.TimeoutExpired:
        raise Failed(f"{cmd[0]} took too long") from None
    if check and r.returncode != 0:
        tail = (r.stderr or r.stdout).strip().splitlines()[-1:] or [f"exit {r.returncode}"]
        raise Failed(f"{' '.join(cmd[:2])}: {tail[0]}")
    return r


def read(path, errors="replace"):
    """A text file's contents (closed again at once)."""
    with open(path, errors=errors) as f:
        return f.read()


def have(cmd):
    return shutil.which(cmd) is not None


def live_medium():
    """Started from a Field Kit medium (or the full ISO's Field Kit entry), not an install."""
    return os.path.isdir("/run/archiso") or "bromigos.fieldkit" in cmdline()


def cmdline():
    try:
        with open("/proc/cmdline") as f:
            return f.read()
    except OSError:
        return ""


def reduced_motion():
    """DRIFTGLASS's rule 3: no Spark, Pulse or Sweep. The kernel's `bromigos.motion=reduced`, the
    environment's BROMIGOS_REDUCED_MOTION, or an installed system's own setting."""
    if "bromigos.motion=reduced" in cmdline() or os.environ.get("BROMIGOS_REDUCED_MOTION"):
        return True
    for d in (os.environ.get("XDG_STATE_HOME") or os.path.expanduser("~/.local/state"),):
        try:
            with open(os.path.join(d, "bromigos", "accessibility.json")) as f:
                return json.load(f).get("motion") == "reduced"
        except (OSError, ValueError):
            pass
    return False


# ------------------------------------------------------------------ the network

def link():
    """'internet', 'lan' (a link and an address, nothing further) or 'none'. Plain checks,
    each a second or two at most: never a reason for the menu to wait."""
    try:
        with open(os.environ.get("BROMIGOS_FIELDKIT_ROUTES", "/proc/net/route")) as f:
            rows = [r.split() for r in f.read().splitlines()[1:] if len(r.split()) > 2]
    except OSError:
        rows = []
    rows = [r for r in rows if r[0] != "lo"]
    if not rows:
        return "none"
    if not any(r[1] == "00000000" for r in rows):
        return "lan"
    try:
        socket.setdefaulttimeout(2)
        addr = socket.getaddrinfo("pkgs.bromigos.org", 443, proto=socket.IPPROTO_TCP)[0][4]
        with socket.create_connection(addr[:2], timeout=2):
            return "internet"
    except OSError:
        return "lan"
    finally:
        socket.setdefaulttimeout(None)


LINK_WORDS = {
    "internet": "online",
    "lan": "local network only",
    "none": "no network",
}


# ------------------------------------------------------------------ disks

@dataclass
class Part:
    path: str
    fstype: str
    size: str
    label: str = ""
    uuid: str = ""
    mountpoints: list = field(default_factory=list)
    parent: str = ""
    removable: bool = False
    tran: str = ""
    model: str = ""

    def describe(self):
        bits = [self.path, self.size]
        if self.label:
            bits.append(self.label)
        if self.model:
            bits.append(self.model)
        return " · ".join(bits)


def block_devices():
    """Every partition and disk lsblk sees, flattened."""
    r = run(["lsblk", "-J", "-b", "-o", "NAME,PATH,FSTYPE,LABEL,UUID,SIZE,TYPE,MOUNTPOINTS,RM,TRAN,MODEL,PKNAME"], check=False)
    try:
        doc = json.loads(r.stdout or "{}")
    except ValueError:
        return []
    out = []

    def walk(devs, disk=None):
        for d in devs or []:
            top = disk or d
            out.append(Part(path=d.get("path") or "", fstype=d.get("fstype") or "", size=human(d.get("size") or 0),
                            label=d.get("label") or "", uuid=d.get("uuid") or "",
                            mountpoints=[m for m in (d.get("mountpoints") or []) if m],
                            parent=top.get("path") or "", removable=bool(top.get("rm")),
                            tran=top.get("tran") or "", model=(top.get("model") or "").strip()))
            out[-1].type = d.get("type")
            walk(d.get("children"), top)

    walk(doc.get("blockdevices"))
    return out


def human(n):
    n = int(n)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1000 or unit == "TB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1000
    return str(n)


def install_candidates():
    """Partitions that may hold a bromigOS install: LUKS (encrypted, the default) and btrfs."""
    return [p for p in block_devices() if p.fstype in ("crypto_LUKS", "btrfs") and getattr(p, "type", "") != "crypt"]


def usb_targets():
    """Partitions on removable or USB drives that a backup can go to."""
    return [p for p in block_devices()
            if (p.removable or p.tran == "usb") and p.fstype in ("ext4", "btrfs", "exfat", "vfat", "ntfs", "xfs")]


# ------------------------------------------------------------------ the install

class Target:
    """The install Field Kit works on: its root (mounted), how it got there, and how to undo it."""

    def __init__(self, root="/", device=None, mapper=None, top=None, mounted_by_us=False):
        self.root = root
        self.device = device            # the partition (LUKS or btrfs)
        self.mapper = mapper            # /dev/mapper/… when we unlocked it
        self.top = top                  # btrfs's top level (subvolid=5), for snapshots
        self.mounted_by_us = mounted_by_us

    def path(self, p):
        return os.path.join(self.root, p.lstrip("/"))

    @property
    def is_live_root(self):
        return self.root == "/"

    def chroot(self, cmd, **kw):
        """A command inside the install (arch-chroot sets /proc, /sys, /dev and /boot up)."""
        if self.is_live_root:
            return run(cmd, **kw)
        return run(["arch-chroot", self.root, *cmd], **kw)

    def chroot_argv(self, cmd):
        return list(cmd) if self.is_live_root else ["arch-chroot", self.root, *cmd]

    def hostname(self):
        try:
            with open(self.path("/etc/hostname")) as f:
                return f.read().strip() or "bromigos"
        except OSError:
            return "bromigos"

    def users(self):
        """The install's people: home folders under /home with a matching passwd line."""
        names = []
        try:
            with open(self.path("/etc/passwd")) as f:
                for line in f:
                    parts = line.split(":")
                    if len(parts) > 5 and parts[5].startswith("/home/") and int(parts[2]) >= 1000:
                        names.append((parts[0], parts[5]))
        except (OSError, ValueError):
            pass
        return names

    def save(self):
        os.makedirs(os.path.dirname(STATE), exist_ok=True)
        with open(STATE, "w") as f:
            json.dump({"root": self.root, "device": self.device, "mapper": self.mapper, "top": self.top,
                       "mounted_by_us": self.mounted_by_us}, f)

    @classmethod
    def load(cls):
        try:
            with open(STATE) as f:
                d = json.load(f)
            t = cls(**d)
            if t.root != "/" and not os.path.ismount(t.root):
                return None
            return t
        except (OSError, ValueError, TypeError):
            return None


def running_install():
    """On an installed bromigOS (not a medium): the running system itself."""
    if live_medium():
        return None
    return Target("/")


def unlock(dev, passphrase):
    """Opens a LUKS partition as /dev/mapper/bromigos-root (or finds it open already)."""
    mapped = f"/dev/mapper/{MAPPER}"
    if os.path.exists(mapped):
        return mapped
    r = run(["cryptsetup", "open", "--type", "luks", "--key-file=-", dev, MAPPER], input=passphrase, check=False)
    if r.returncode == 2:
        raise Failed("That passphrase didn't unlock it. Check the keyboard layout and try again.")
    if r.returncode != 0:
        raise Failed(f"The disk didn't unlock: {(r.stderr or '').strip()}")
    return mapped


def subvolumes(top):
    r = run(["btrfs", "subvolume", "list", "-o", top], check=False)
    names = []
    for line in r.stdout.splitlines():
        if " path " in line:
            names.append(line.split(" path ", 1)[1].strip())
    return names


def mount_install(dev, passphrase=None, root=MOUNT):
    """The install mounted at root, the way its own fstab mounts it (subvolumes, /boot, /home),
    with btrfs's top level beside it for snapshots. dev: the LUKS or btrfs partition."""
    fs = run(["blkid", "-o", "value", "-s", "TYPE", dev], check=False).stdout.strip()
    mapper = None
    btr = dev
    if fs == "crypto_LUKS":
        if passphrase is None:
            raise Failed("This disk is encrypted: it needs its passphrase.")
        btr = mapper = unlock(dev, passphrase)
        fs = run(["blkid", "-o", "value", "-s", "TYPE", btr], check=False).stdout.strip()
    if fs != "btrfs":
        raise Failed(f"{dev} isn't a bromigOS install (it's {fs or 'nothing Field Kit knows'}).")
    os.makedirs(TOP, exist_ok=True)
    os.makedirs(root, exist_ok=True)
    if not os.path.ismount(TOP):
        run(["mount", "-o", "subvolid=5", btr, TOP])
    subs = subvolumes(TOP)
    root_sub = "@" if "@" in subs else None
    if not os.path.ismount(root):
        run(["mount", "-o", f"subvol={root_sub}" if root_sub else "subvolid=5", btr, root])
    if not os.path.isfile(os.path.join(root, "etc", "fstab")):
        raise Failed("Found a btrfs file system, but no system on it (no /etc/fstab).")
    # the rest as the install's own fstab says: /boot, /home, /var/log, the snapshots
    r = run(["mount", "-a", "--fstab", os.path.join(root, "etc", "fstab"), "--target-prefix", root], check=False)
    # Field Kit started from this install's /boot keeps that partition mounted read-only (archiso's
    # bootmnt), and a second mount shares it: writable, for the repairs that change /boot
    boot = os.path.join(root, "boot")
    if os.path.ismount(boot):
        opts = run(["findmnt", "-no", "OPTIONS", boot], check=False).stdout
        if opts.startswith("ro") or ",ro," in opts:
            run(["mount", "-o", "remount,rw", boot], check=False)
    t = Target(root, device=dev, mapper=mapper, top=TOP, mounted_by_us=True)
    t.save()
    if r.returncode != 0:
        t.warning = "Some of its other parts didn't mount: " + (r.stderr.strip().splitlines() or ["?"])[-1]
    return t


def unmount_install(t):
    if t is None or not t.mounted_by_us:
        return
    run(["umount", "-R", t.root], check=False)
    if t.top and os.path.ismount(t.top):
        run(["umount", t.top], check=False)
    if t.mapper:
        run(["cryptsetup", "close", MAPPER], check=False)
    try:
        os.unlink(STATE)
    except OSError:
        pass


# ------------------------------------------------------------------ backups before every write

BACKUPS = "/var/lib/bromigos/fieldkit-backups"


class Backup:
    """One repair's backups, inside the install: /var/lib/bromigos/fieldkit-backups/<when>/
    holds every file as it was, at its own path. `restore()` puts them back."""

    def __init__(self, target, what):
        self.target = target
        stamp = time.strftime("%Y%m%d-%H%M%S")
        self.dir = target.path(os.path.join(BACKUPS, f"{stamp}-{what}"))
        self.saved = []

    def keep(self, path):
        """A copy of an install path (absolute, as the install sees it) before it changes."""
        src = self.target.path(path)
        if not os.path.lexists(src):
            return None
        dst = os.path.join(self.dir, path.lstrip("/"))
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        if os.path.isdir(src) and not os.path.islink(src):
            shutil.copytree(src, dst, symlinks=True, dirs_exist_ok=True)
        else:
            shutil.copy2(src, dst, follow_symlinks=False)
        self.saved.append(path)
        return dst

    def move_out(self, path):
        """The file moved out of the way, into the backup: for folders where a program reads
        every file whatever its name (SDDM's sddm.conf.d), so a rename wouldn't disable it."""
        src = self.target.path(path)
        dst = os.path.join(self.dir, path.lstrip("/"))
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        shutil.move(src, dst)
        self.saved.append(path)
        return dst

    def write(self, path, text):
        """The file's new text, with its old self kept first; written aside and swapped in."""
        self.keep(path)
        dst = self.target.path(path)
        tmp = dst + ".fieldkit-new"
        mode = os.stat(dst).st_mode & 0o7777 if os.path.exists(dst) else 0o644
        with open(tmp, "w") as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        os.chmod(tmp, mode)
        os.replace(tmp, dst)

    def where(self):
        """The backup folder as the install sees it."""
        return "/" + os.path.relpath(self.dir, self.target.root) if not self.target.is_live_root else self.dir
