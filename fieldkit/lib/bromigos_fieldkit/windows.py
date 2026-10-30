"""Windows repair (docs/fieldkit.md, "Windows repair"): the jobs people bring a rescue stick for
when Windows shares the machine, or is the machine.

  windows find                                   Windows partitions, BitLocker volumes, the EFI
                                                 partition's Windows Boot Manager, the firmware's
                                                 boot entries
  windows users --part DEV                       the local accounts in that Windows
  windows reset-password --part DEV --user NAME  clears a local account's password (chntpw); the
                                                 SAM hive is copied first
  windows unlock-bitlocker --part DEV            the recovery key on standard input: the volume
                                                 opened read-only (dislocker), its files at the
                                                 returned path
  windows lock-bitlocker --part DEV              closes it again
  windows ntfsfix --part DEV                     clears the "not cleanly shut down" mark and fixes
                                                 common NTFS inconsistencies (ntfsfix)
  windows boot-entries                           the firmware's boot entries and their order
  windows boot-fix [--readd] [--first windows|bromigos]
                                                 adds Windows Boot Manager back when it's gone,
                                                 and puts one or the other first; the entries as
                                                 they were are saved first
"""

import os
import re
import shutil
import tempfile
import time

from . import system
from .imaging import Args, mounted, name_of, parent_disk, part_number

RUN = os.environ.get("BROMIGOS_FIELDKIT_RUN", "/run/bromigos-fieldkit")
BOOTMGR = r"\EFI\Microsoft\Boot\bootmgfw.efi"
RESET_WARNING = ("This clears the password of a local Windows account, so it signs in with none. A Microsoft "
                 "account (an e-mail address) isn't changed here: reset that at account.live.com. Files the "
                 "account encrypted with EFS become unreadable, and saved Windows passwords for it are lost. "
                 "If the drive uses BitLocker, Windows will still ask for its key.")


def blk(dev, key):
    return system.run(["blkid", "-o", "value", "-s", key, dev], check=False).stdout.strip()


def parts_of(fstypes):
    return [p for p in system.block_devices() if getattr(p, "type", "") == "part" and p.fstype in fstypes]


class Mounted:
    """A partition mounted for the moment, read-only unless asked (ntfs-3g for writing)."""

    def __init__(self, dev, write=False, fs=None):
        self.dev, self.write, self.fs = dev, write, fs
        self.dir = None

    def __enter__(self):
        self.dir = tempfile.mkdtemp(prefix=f"fieldkit-{name_of(self.dev)}-", dir=RUN if os.path.isdir(RUN) else None)
        if self.fs == "ntfs" and self.write:
            cmd = ["ntfs-3g", "-o", "rw", self.dev, self.dir]
        else:
            cmd = ["mount", "-o", "rw" if self.write else "ro", self.dev, self.dir]
        r = system.run(cmd, check=False, timeout=60)
        if r.returncode != 0:
            os.rmdir(self.dir)
            text = (r.stderr or r.stdout).strip()
            if re.search(r"hibernat|unsafe state|Windows is hibernated|fast restart", text, re.I):
                raise system.Failed("Windows didn't shut down fully (Fast Startup or hibernation), so its drive can't be "
                                    "changed safely. Start Windows, hold Shift while you choose Shut down, then try again.")
            raise system.Failed(f"{name_of(self.dev)} didn't mount: {text.splitlines()[-1] if text else 'no reason given'}")
        return self.dir

    def __exit__(self, *exc):
        system.run(["sync"], check=False)
        system.run(["umount", self.dir], check=False)
        try:
            os.rmdir(self.dir)
        except OSError:
            pass


def ci(base, *names):
    """A path under base matched without regard to case (NTFS and FAT names), or None."""
    cur = base
    for n in names:
        try:
            match = next((e for e in os.listdir(cur) if e.lower() == n.lower()), None)
        except OSError:
            return None
        if match is None:
            return None
        cur = os.path.join(cur, match)
    return cur


# ------------------------------------------------------------------ boot entries

def boot_entries():
    r = system.run(["efibootmgr", "-v"], check=False)
    if r.returncode != 0:
        return {"ok": False, "message": "This machine didn't start with UEFI, so it has no firmware boot entries "
                                        "(Windows on such a machine starts from the disk's own boot code).",
                "entries": [], "order": [], "raw": ""}
    order = []
    entries = []
    for line in r.stdout.splitlines():
        if line.startswith("BootOrder:"):
            order = [x.strip() for x in line.split(":", 1)[1].split(",") if x.strip()]
        m = re.match(r"^Boot([0-9A-Fa-f]{4})(\*?)\s+(.*?)(?:\t|\s{2,}|$)(.*)$", line)
        if m:
            num, active, label, path = m.groups()
            entries.append({"num": num.upper(), "active": bool(active), "label": label.strip(), "path": path.strip(),
                            "windows": "bootmgfw.efi" in path.lower() or label.strip().lower().startswith("windows boot manager"),
                            "bromigos": bool(re.search(r"bromigos|grub|arch", label + path, re.I))})
    return {"ok": True, "entries": entries, "order": [o.upper() for o in order], "raw": r.stdout}


def esp_with_windows():
    """(partition, disk, number) of an EFI partition holding Windows Boot Manager."""
    for p in parts_of(("vfat",)):
        if p.mountpoints:
            base = p.mountpoints[0]
            found = ci(base, "EFI", "Microsoft", "Boot", "bootmgfw.efi")
        else:
            try:
                with Mounted(p.path) as m:
                    found = ci(m, "EFI", "Microsoft", "Boot", "bootmgfw.efi")
            except system.Failed:
                found = None
        if found:
            return p.path, parent_disk(p.path), part_number(p.path)
    return None, None, None


def save_entries(raw):
    d = os.path.join(RUN, "reports")
    os.makedirs(d, exist_ok=True)
    path = os.path.join(d, f"efibootmgr-{time.strftime('%Y%m%d-%H%M%S')}.txt")
    with open(path, "w") as f:
        f.write(raw)
    return path


def boot_fix(readd, first):
    st = boot_entries()
    if not st["ok"]:
        raise system.Failed(st["message"])
    kept = save_entries(st["raw"])
    words = []
    win = [e for e in st["entries"] if e["windows"]]
    if readd and not win:
        part, disk, num = esp_with_windows()
        if not part:
            raise system.Failed("There's no Windows Boot Manager on any EFI partition here: Windows' own boot files "
                                "are missing (Windows' recovery media can rebuild them: bcdboot).")
        r = system.run(["efibootmgr", "--create", "--disk", disk, "--part", str(num), "--label", "Windows Boot Manager",
                        "--loader", BOOTMGR], check=False)
        if r.returncode != 0:
            raise system.Failed("The firmware didn't take the new entry: " + (r.stderr.strip() or "?"))
        words.append(f"Windows Boot Manager is back in the firmware's boot list (from {name_of(part)}).")
        st = boot_entries()
        win = [e for e in st["entries"] if e["windows"]]
    elif readd:
        words.append("Windows Boot Manager is already in the firmware's boot list.")
    if first:
        pick = win if first == "windows" else [e for e in st["entries"] if e["bromigos"]]
        if not pick:
            raise system.Failed(f"There's no {'Windows' if first == 'windows' else 'bromigOS'} entry to put first.")
        lead = pick[0]["num"]
        order = [lead] + [o for o in st["order"] if o != lead]
        r = system.run(["efibootmgr", "--bootorder", ",".join(order)], check=False)
        if r.returncode != 0:
            raise system.Failed("The firmware didn't take the new order: " + (r.stderr.strip() or "?"))
        words.append(f"{pick[0]['label']} starts first now.")
    return {"ok": True, "message": " ".join(words) or "Nothing to change.", "saved": kept}


# ------------------------------------------------------------------ the Windows partition

def find():
    windows, bitlocker = [], []
    for p in parts_of(("ntfs", "BitLocker")):
        if p.fstype == "BitLocker":
            bitlocker.append({"path": p.path, "size": p.size, "label": p.label})
            continue
        try:
            with Mounted(p.path) as m:
                sam = ci(m, "Windows", "System32", "config", "SAM")
                ver = bool(ci(m, "Windows", "explorer.exe"))
        except system.Failed as e:
            windows.append({"path": p.path, "size": p.size, "label": p.label, "windows": None, "note": str(e)})
            continue
        if sam or ver:
            windows.append({"path": p.path, "size": p.size, "label": p.label, "windows": True, "note": ""})
    esp, _, _ = esp_with_windows()
    st = boot_entries()
    return {"ok": True, "windows": windows, "bitlocker": bitlocker, "boot_manager": esp or "",
            "entries": st["entries"], "order": st["order"], "uefi": st["ok"]}


def sam_path(m):
    p = ci(m, "Windows", "System32", "config", "SAM")
    if not p:
        raise system.Failed("This partition has no Windows accounts file (Windows\\System32\\config\\SAM).")
    return p


def users(part):
    with Mounted(part, fs="ntfs") as m:
        r = system.run(["chntpw", "-l", sam_path(m)], check=False)
    out = []
    for line in r.stdout.splitlines():
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) >= 3 and re.fullmatch(r"[0-9a-fA-F]{3,8}", cells[0] or ""):
            out.append({"rid": cells[0], "name": cells[1], "admin": "ADMIN" in cells[2].upper(),
                        "locked": len(cells) > 3 and "lock" in cells[3].lower()})
    return {"ok": True, "users": out, "warning": RESET_WARNING}


def reset_password(part, user):
    if mounted(part):
        raise system.Failed(f"{name_of(part)} is in use (mounted). Unmount it first.")
    with Mounted(part, write=True, fs="ntfs") as m:
        sam = sam_path(m)
        backup = f"{sam}.bromigos-fieldkit-{time.strftime('%Y%m%d-%H%M%S')}"
        shutil.copy2(sam, backup)
        os.makedirs(os.path.join(RUN, "reports"), exist_ok=True)
        shutil.copy2(sam, os.path.join(RUN, "reports", os.path.basename(backup)))
        # chntpw's own menu, answered: 1 clears the password, q leaves the user, y writes the hive
        r = system.run(["chntpw", "-u", user, sam], input="1\nq\ny\n", check=False, timeout=60)
    text = r.stdout
    if "Password cleared" not in text and "cleared" not in text.lower():
        raise system.Failed(f"chntpw didn't clear the password for {user} (is the name right? see windows users). "
                            "Nothing was changed.")
    return {"ok": True, "message": f"{user} on {name_of(part)} has no password now. Sign in without one, then set a new one in Windows.",
            "warning": RESET_WARNING, "backup": "\\Windows\\System32\\config\\" + os.path.basename(backup)}


def unlock_bitlocker(part, key):
    key = (key or "").strip()
    if not re.fullmatch(r"(\d{6}-){7}\d{6}", key):
        raise system.Failed("A BitLocker recovery key is 48 digits in eight groups of six, separated by dashes.")
    fuse = os.path.join(RUN, f"bitlocker-{name_of(part)}")
    files = os.path.join(RUN, f"windows-{name_of(part)}")
    os.makedirs(fuse, exist_ok=True)
    os.makedirs(files, exist_ok=True)
    r = system.run(["dislocker-fuse", "-r", "-V", part, f"-p{key}", "--", fuse], check=False, timeout=120)
    if r.returncode != 0:
        raise system.Failed("That key didn't open it: " + ((r.stderr or r.stdout).strip().splitlines() or ["no reason given"])[-1])
    r = system.run(["mount", "-o", "loop,ro", os.path.join(fuse, "dislocker-file"), files], check=False)
    if r.returncode != 0:
        system.run(["umount", fuse], check=False)
        raise system.Failed("Unlocked, but the Windows file system inside didn't mount: " + (r.stderr.strip() or "?"))
    return {"ok": True, "path": files, "message": f"Opened read-only: the files are in {files}. Copy what you need, "
                                                  "then close it (windows lock-bitlocker)."}


def lock_bitlocker(part):
    for d in (os.path.join(RUN, f"windows-{name_of(part)}"), os.path.join(RUN, f"bitlocker-{name_of(part)}")):
        system.run(["umount", d], check=False)
    return {"ok": True, "message": f"{name_of(part)} is closed again."}


def ntfsfix(part):
    if mounted(part):
        raise system.Failed(f"{name_of(part)} is in use (mounted). Unmount it first.")
    r = system.run(["ntfsfix", "-d", part], check=False, timeout=600)
    if r.returncode != 0:
        return {"ok": False, "message": "ntfsfix couldn't repair it: " + ((r.stdout + r.stderr).strip().splitlines() or ["?"])[-1]
                + ". Run Windows' own check (chkdsk /f) from Windows or its recovery media."}
    return {"ok": True, "message": f"{name_of(part)} is marked clean and its common problems fixed. Windows checks it "
                                   "fully (chkdsk) at its next start.", "details": r.stdout}


def engine(args, progress):
    import sys
    ap = Args(prog="windows")
    sub = ap.add_subparsers(dest="verb", required=True)
    sub.add_parser("find")
    sub.add_parser("boot-entries")
    for verb in ("users", "reset-password", "unlock-bitlocker", "lock-bitlocker", "ntfsfix"):
        p = sub.add_parser(verb)
        p.add_argument("--part", required=True)
        if verb == "reset-password":
            p.add_argument("--user", required=True)
    p = sub.add_parser("boot-fix")
    p.add_argument("--readd", action="store_true")
    p.add_argument("--first", choices=["windows", "bromigos"])
    a = ap.parse_args(args)
    if a.verb == "find":
        return find()
    if a.verb == "boot-entries":
        st = boot_entries()
        st.pop("raw", None)
        return st
    if a.verb == "users":
        return users(a.part)
    if a.verb == "reset-password":
        return reset_password(a.part, a.user)
    if a.verb == "unlock-bitlocker":
        return unlock_bitlocker(a.part, "" if sys.stdin.isatty() else sys.stdin.read())
    if a.verb == "lock-bitlocker":
        return lock_bitlocker(a.part)
    if a.verb == "ntfsfix":
        return ntfsfix(a.part)
    return boot_fix(a.readd, a.first)
