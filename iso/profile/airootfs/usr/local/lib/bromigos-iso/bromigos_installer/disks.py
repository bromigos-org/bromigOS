#!/usr/bin/env python3
"""The disks, for the installer (docs/iso.md, "Installing from it"): what is on each one,
whether bromigOS can go beside it, and making the room.

  disks.py probe [--json]                    every disk: size, model, what's on it, and the
                                             two choices (erase it, install alongside) with
                                             the reason when one can't be offered
  disks.py shrink --answers FILE             the installer's answers: shrink the partition
                                             they name (NTFS or ext4) to the size chosen,
                                             printing ::stage lines (bromigos-iso-install)

Runs as root (blkid, sfdisk, os-prober and ntfsresize read the disks). Nothing here
writes to a disk except `shrink`, and that only after its own checks: never a
BitLocker-encrypted, hibernated (Windows' Fast Startup), or unclean file system.
"""
import json
import os
import re
import subprocess
import sys
import tempfile


def _read(path):
    with open(path) as f:
        return f.read()

KiB, MiB, GiB = 1024, 1024 ** 2, 1024 ** 3
MIN_BROMIGOS = 20 * GiB     # the smallest bromigOS installs into: 1 GiB /boot and the root
GOOD_BROMIGOS = 60 * GiB    # room for apps, games' prefixes and snapshots: the slider's suggestion
BOOT_SIZE = 1 * GiB
ROOM = {"Windows": 10 * GiB}  # kept free for the other system beyond what it uses now (its updates)
OTHER_ROOM = 5 * GiB
ESP_FREE_NEEDED = 16 * MiB  # GRUB's EFI files on a shared EFI system partition
ALIGN = MiB

ESP_GUID = "c12a7328-f81f-11d2-ba4b-00a0c93ec93b"
MSR_GUID = "e3c9e316-0b5c-4db8-817d-f92df00215ae"
WINRE_GUID = "de94bba4-06d1-4d40-a16a-bfd50179d6ac"
BASIC_DATA_GUID = "ebd0a0a2-b9e5-4433-87c0-68b6b72699c7"
DOS_EXTENDED = {"5", "f", "85"}

FIX = {
    "bitlocker": (
        "Windows on this disk is locked with BitLocker (Device encryption), so bromigOS can't "
        "make it smaller safely.",
        "Start Windows. Open Settings › Privacy & security › Device encryption (or Control "
        "Panel › BitLocker Drive Encryption) and turn it off. Wait until it says it's off, "
        "then shut down and start this installer again. Or, in Windows, open Disk Management, "
        "right-click the C: drive, choose Shrink Volume and leave at least 20 GB free: "
        "bromigOS then installs in that free space without touching Windows."),
    "hibernated": (
        "Windows is paused (Fast Startup or hibernation), not shut down, so its drive can't "
        "be changed safely.",
        "Start Windows. Open Control Panel › Power Options › Choose what the power buttons "
        "do, click Change settings that are currently unavailable and untick Turn on fast "
        "startup. Then hold Shift while you click Shut down. Start this installer again."),
    "dirty": (
        "Windows wants to check this drive before anything changes it.",
        "Start Windows and let it finish starting (it checks the drive by itself, or run "
        "Check disk from the drive's Properties › Tools). Then hold Shift while you click "
        "Shut down, and start this installer again."),
    "unreadable": (
        "bromigOS couldn't read this drive's files to see how much room they use.",
        "Start the other system and let it check its drive, shut it down fully, then start "
        "this installer again. Or make free space from the other system (in Windows: Disk "
        "Management › Shrink Volume)."),
    "small": (
        "There isn't enough room beside what's already on this disk.",
        "bromigOS needs at least 20 GB. Delete some files or apps on the other system, or "
        "choose Erase the whole disk (after copying anything you want to keep), or install "
        "on another disk."),
    "uefi-mbr": (
        "The other system on this disk starts the older way (BIOS), but this computer started "
        "the installer the newer way (UEFI). The two can't share a boot menu.",
        "Restart, open the computer's boot menu (often F12, F11, F8 or Esc right after "
        "switching on) and choose the USB stick's entry that says Legacy or BIOS. Or choose "
        "Erase the whole disk."),
    "bios-gpt": (
        "This disk is laid out for the newer way of starting (UEFI), but this computer started "
        "the installer the older way (BIOS).",
        "Restart, open the computer's boot menu (often F12, F11, F8 or Esc right after "
        "switching on) and choose the USB stick's entry that says UEFI. Or choose Erase the "
        "whole disk."),
    "no-esp": (
        "This disk has no EFI system partition for the boot menu to live on.",
        "Choose Erase the whole disk, or install on a disk that already has Windows' or "
        "another system's EFI partition."),
    "esp-full": (
        "The disk's EFI system partition is full, so bromigOS's boot menu won't fit next to "
        "the other system's.",
        "In the other system, remove old boot entries you no longer use (or tools you "
        "installed that added one), then start this installer again. Or choose Erase the "
        "whole disk."),
    "mbr-full": (
        "This disk uses the older partition layout (MBR), which holds four partitions at most, "
        "and there's no slot left for bromigOS's two.",
        "Choose Erase the whole disk, or install on another disk."),
    "medium": (
        "This is the USB stick bromigOS started from.",
        "Choose another disk. To install onto a USB stick, start bromigOS from a different one."),
    "too-small": (
        "This disk is smaller than the 20 GB bromigOS needs.",
        "Choose a bigger disk."),
    "mounted": (
        "Something on this disk is in use by the live system right now.",
        "Close any file manager or app using it, or restart the installer."),
}


def plain_size(n):
    """A size in plain words: 512 GB, 1.8 TB, 20 GB (decimal units, as the box says)."""
    if n is None:
        return "?"
    for unit, scale in (("TB", 10 ** 12), ("GB", 10 ** 9), ("MB", 10 ** 6)):
        if n >= scale:
            v = n / scale
            return f"{v:.1f} {unit}" if v < 10 and unit != "MB" else f"{v:.0f} {unit}"
    return f"{n} bytes"


def run(argv, input=None, timeout=120):
    try:
        return subprocess.run(argv, input=input, capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired) as e:
        return subprocess.CompletedProcess(argv, 127, "", str(e))


def firmware():
    return "uefi" if os.path.isdir("/sys/firmware/efi") else "bios"


# ── what the tools say ──────────────────────────────────────────────────────────────────
LSBLK_COLS = "NAME,PATH,TYPE,SIZE,MODEL,VENDOR,TRAN,RM,RO,FSTYPE,LABEL,UUID,PARTTYPE,PARTLABEL,PTTYPE,MOUNTPOINTS,PKNAME"


def lsblk():
    r = run(["lsblk", "-J", "-b", "-o", LSBLK_COLS])
    return json.loads(r.stdout or '{"blockdevices": []}').get("blockdevices", [])


def sfdisk_json(dev):
    r = run(["sfdisk", "--json", dev])
    if r.returncode != 0 or not r.stdout.strip():
        return None
    return json.loads(r.stdout).get("partitiontable")


def os_prober():
    """{partition: name} from os-prober (Windows' boot manager on the ESP counts for the disk)."""
    r = run(["os-prober"], timeout=300)
    return parse_os_prober(r.stdout)


def parse_os_prober(text):
    found = {}
    for line in (text or "").splitlines():
        parts = line.split(":")
        if len(parts) < 4:
            continue
        dev = parts[0].split("@")[0]
        name = parts[1].strip() or parts[2].strip()
        if name == "Windows Boot Manager":
            name = "Windows"
        found.setdefault(dev, name)
    return found


def medium_disks():
    """The disks the live system started from (archiso's boot medium), never offered."""
    out = set()
    r = run(["findmnt", "-no", "SOURCE", "/run/archiso/bootmnt"])
    src = r.stdout.strip()
    try:
        cmd = _read("/proc/cmdline")
    except OSError:
        cmd = ""
    m = re.search(r"archisosearchuuid=(\S+)", cmd)
    if m:
        r = run(["blkid", "-U", m.group(1)])
        if r.stdout.strip():
            src = src or r.stdout.strip()
            out.add(r.stdout.strip())
    if src:
        out.add(src)
    disks = set()
    for s in out:
        r = run(["lsblk", "-no", "PKNAME", s])
        pk = r.stdout.strip().splitlines()
        disks.add("/dev/" + pk[0] if pk and pk[0] else s)
    return disks


def ntfs_facts(dev):
    """{windows, hibernated, dirty, min_bytes, used_bytes, unreadable, bios_boot}"""
    f = {"windows": False, "hibernated": False, "dirty": False, "min_bytes": None, "used_bytes": None,
         "unreadable": False, "bios_boot": False}
    # hiberfil.sys's first bytes: "hibr"/"HIBR" (hibernated or Fast Startup), "wake", "RSTR"
    try:
        p = subprocess.Popen(["ntfscat", dev, "hiberfil.sys"], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        head = p.stdout.read(4)
        p.kill()
        p.wait()
        f["hibernated"] = head.lower() in (b"hibr", b"wake", b"rstr")
    except OSError:
        pass
    f["windows"] = run(["ntfsls", "-p", "/Windows/System32", dev]).returncode == 0
    f["bios_boot"] = run(["ntfsls", "-p", "/Boot", dev]).returncode == 0 and \
        "bootmgr" in run(["ntfsls", dev]).stdout.lower()
    r = run(["ntfsresize", "--info", "--no-progress-bar", dev], timeout=600)
    f.update(parse_ntfsresize(r.stdout + r.stderr))
    return f


def parse_ntfsresize(text):
    f = {}
    t = text.lower()
    if "hibernat" in t or "unsafe state" in t or "fast restart" in t:
        f["hibernated"] = True
    if "scheduled for check" in t or "is inconsistent" in t or "dirty" in t:
        f["dirty"] = True
    m = re.search(r"you might resize at (\d+) bytes", t)
    if m:
        f["min_bytes"] = int(m.group(1))
    m = re.search(r"space in use\s*:\s*(\d+) mb", t)
    if m:
        f["used_bytes"] = int(m.group(1)) * 10 ** 6
    if "min_bytes" not in f and not f.get("hibernated") and not f.get("dirty"):
        f["unreadable"] = True
    return f


def ext4_facts(dev):
    f = {"min_bytes": None, "dirty": False, "unreadable": False}
    r = run(["dumpe2fs", "-h", dev])
    m_state = re.search(r"Filesystem state:\s*(\S+)", r.stdout)
    m_bs = re.search(r"Block size:\s*(\d+)", r.stdout)
    if not m_bs:
        f["unreadable"] = True
        return f
    if m_state and m_state.group(1) != "clean":
        f["dirty"] = True
    r = run(["resize2fs", "-P", dev], timeout=600)
    m = re.search(r"minimum size of the filesystem:\s*(\d+)", r.stdout)
    if m:
        f["min_bytes"] = int(m.group(1)) * int(m_bs.group(1))
    else:
        f["unreadable"] = True
    return f


def health(dev):
    """The disk's own verdict (SMART, or NVMe's health log, through smartctl): "ok", "failing"
    with its words, or "unknown" (a virtual disk, a USB bridge that hides it)."""
    r = run(["smartctl", "-H", "-j", dev], timeout=60)
    try:
        doc = json.loads(r.stdout)
    except ValueError:
        return {"state": "unknown"}
    passed = (doc.get("smart_status") or {}).get("passed")
    if passed is False:
        return {"state": "failing", "why": "The disk reports that it's failing (its own health check, SMART)."}
    crit = (doc.get("nvme_smart_health_information_log") or {}).get("critical_warning")
    if crit:
        return {"state": "failing", "why": "The disk reports a critical warning (its NVMe health log)."}
    return {"state": "ok" if passed else "unknown"}


def esp_free(dev):
    """Free bytes on a FAT EFI system partition (mounted read-only for a moment), and
    whether Windows' boot manager is on it."""
    d = tempfile.mkdtemp(prefix="bromigos-esp-")
    try:
        if run(["mount", "-o", "ro", dev, d]).returncode != 0:
            return None, False
        try:
            st = os.statvfs(d)
            ms = any(n.lower() == "microsoft" for n in os.listdir(os.path.join(d, "EFI"))) \
                if os.path.isdir(os.path.join(d, "EFI")) else False
            return st.f_bavail * st.f_frsize, ms
        finally:
            run(["umount", d])
    finally:
        try:
            os.rmdir(d)
        except OSError:
            pass


# ── the picture of one disk ─────────────────────────────────────────────────────────────
def free_regions(table, disk_bytes):
    """Unallocated stretches of at least 1 GiB, aligned to 1 MiB: [{start, size}] in bytes."""
    if table is None:
        return [{"start": ALIGN, "size": disk_bytes - 2 * ALIGN}] if disk_bytes > 2 * ALIGN else []
    ss = int(table.get("sectorsize", 512))
    first = max(int(table.get("firstlba", 2048)), ALIGN // ss)
    last = int(table.get("lastlba", disk_bytes // ss - 1))
    if table.get("label") == "dos":
        last = min(last, disk_bytes // ss - 1, 2 ** 32 - 1)
    used = []
    for p in table.get("partitions", []):
        start, size = int(p["start"]), int(p["size"])
        used.append((start, start + size))
    used.sort()
    out, cur = [], first
    for s, e in used + [(last + 1, last + 1)]:
        if s > cur:
            a = -(-cur * ss // ALIGN) * ALIGN            # round the start up to 1 MiB
            b = ((s * ss) // ALIGN) * ALIGN              # the end down
            if b - a >= GiB:
                out.append({"start": a, "size": b - a})
        cur = max(cur, e)
    return out


def describe_partition(p, os_names):
    """A partition in a few plain words: Windows (NTFS, 120 GB), EFI system partition…"""
    pt = (p.get("parttype") or "").lower()
    fs = p.get("fstype") or ""
    size = plain_size(p.get("size"))
    name = os_names.get(p["path"])
    if pt == ESP_GUID or pt in ("ef", "0xef"):
        return f"EFI system partition, {size}" + (" (Windows' boot manager)" if p.get("has_microsoft") else "")
    if pt == MSR_GUID:
        return f"Microsoft reserved, {size}"
    if pt == WINRE_GUID or (p.get("label") or "").lower() in ("recovery", "winre"):
        return f"Windows recovery, {size}"
    if fs == "BitLocker":
        return f"{name or 'Windows'} (locked with BitLocker), {size}"
    if name:
        return f"{name}, {size}"
    if fs == "ntfs" and p.get("windows"):
        return f"Windows, {size}"
    if fs in ("ntfs", "exfat", "vfat"):
        return f"Files ({fs.upper() if fs != 'vfat' else 'FAT'}), {size}"
    if fs in ("ext4", "btrfs", "xfs", "f2fs"):
        return f"Linux files ({fs}), {size}"
    if fs == "crypto_LUKS":
        return f"Encrypted Linux, {size}"
    if fs == "swap":
        return f"Swap, {size}"
    if fs:
        return f"{fs}, {size}"
    return f"Unformatted, {size}"


def disk_picture(dev, parts, table, os_names, fw, medium, deep=True):
    """One disk as the installer shows it, with its two choices."""
    size = int(dev.get("size") or 0)
    vendor = (dev.get("vendor") or "").strip()
    vendor = "" if re.fullmatch(r"0x[0-9a-f]+|ATA", vendor, re.I) else vendor
    model = " ".join(x for x in (vendor, (dev.get("model") or "").strip()) if x) or \
        ("Virtual disk" if (dev.get("name") or "").startswith("vd") else "Disk")
    tran = (dev.get("tran") or "").lower()
    kind = {"usb": "USB", "nvme": "NVMe", "sata": "SATA", "ata": "SATA", "virtio": "virtual"}.get(tran, "")
    if (dev.get("name") or "").startswith("vd"):
        kind = kind or "virtual"
    ptable = table.get("label") if table else None
    tparts = {p["node"]: p for p in (table or {}).get("partitions", [])}
    out_parts = []
    for p in parts:
        q = {"path": p["path"], "size": int(p.get("size") or 0), "fstype": p.get("fstype"),
             "label": p.get("label"), "parttype": (p.get("parttype") or "").lower(),
             "mounted": bool([m for m in (p.get("mountpoints") or []) if m])}
        tp = tparts.get(p["path"], {})
        q["start"] = int(tp.get("start", 0)) * int((table or {}).get("sectorsize", 512))
        q["bootable"] = bool(tp.get("bootable"))
        q["esp"] = q["parttype"] in (ESP_GUID, "ef", "0xef")
        if deep and q["fstype"] == "ntfs":
            q.update(ntfs_facts(p["path"]))
        elif deep and q["fstype"] == "ext4":
            q.update(ext4_facts(p["path"]))
        if deep and q["esp"] and q["fstype"] == "vfat":
            q["esp_free"], q["has_microsoft"] = esp_free(p["path"])
        q["bitlocker"] = q["fstype"] == "BitLocker"
        out_parts.append(q)
    oses = []
    for q in out_parts:
        n = os_names.get(q["path"])
        if n and n not in oses:
            oses.append(n)
        if q.get("windows") and not any(o.startswith("Windows") for o in oses):
            oses.append("Windows")
        if q["bitlocker"] and not any(o.startswith("Windows") for o in oses):
            oses.append("Windows")
    for q in out_parts:
        q["what"] = describe_partition(q, os_names)
    free = free_regions(table, size) if ptable else []
    hl = health(dev["path"]) if deep and not dev["path"] in medium else {"state": "unknown"}
    d = {"path": dev["path"], "size": size, "health": hl, "size_text": plain_size(size), "model": model, "kind": kind,
         "removable": bool(dev.get("rm")) or tran == "usb", "table": ptable, "partitions": out_parts,
         "free": free, "free_bytes": sum(f["size"] for f in free), "oses": oses, "medium": dev["path"] in medium}
    if d["medium"]:
        d["summary"] = "the USB stick bromigOS started from"
    elif not out_parts:
        d["summary"] = "Empty"
    elif oses:
        d["summary"] = ", ".join(oses) + f" · {len(out_parts)} partition{'s' if len(out_parts) != 1 else ''}"
    else:
        d["summary"] = f"{len(out_parts)} partition{'s' if len(out_parts) != 1 else ''}, no system found"
    d["bitlocker"] = any(p["bitlocker"] for p in out_parts)
    d["bromigos"] = find_bromigos(out_parts, fw) if deep and not d["medium"] else None
    if d["bromigos"] and "bromigOS" not in d["oses"]:
        d["oses"].insert(0, "bromigOS")
        d["summary"] = ", ".join(d["oses"]) + f" · {len(out_parts)} partition{'s' if len(out_parts) != 1 else ''}"
    d["options"] = {"erase": erase_option(d), "alongside": alongside_option(d, fw), "reinstall": reinstall_option(d)}
    return d


def _why(code, **extra):
    what, fix = FIX[code]
    return {"ok": False, "code": code, "why": what, "fix": fix, **extra}


def find_bromigos(parts, fw):
    """An installed bromigOS on these partitions: its /boot (GRUB's menu names bromigOS), its
    root (btrfs, or LUKS around it) and, unencrypted, its users. None when there's none."""
    boot = root = None
    for p in parts:
        if p["fstype"] in ("vfat", "ext4") and not p["mounted"]:
            d = tempfile.mkdtemp(prefix="bromigos-boot-")
            try:
                if run(["mount", "-o", "ro", p["path"], d]).returncode == 0:
                    try:
                        for cfg in ("grub/grub.cfg", "boot/grub/grub.cfg"):
                            path = os.path.join(d, cfg)
                            if os.path.exists(path) and "menuentry 'bromigOS" in open(path, errors="replace").read():
                                boot = p
                    finally:
                        run(["umount", d])
            finally:
                os.rmdir(d)
        if p["fstype"] in ("btrfs", "crypto_LUKS") and root is None:
            root = p
    if not (boot and root):
        return None
    found = {"boot": boot["path"], "root": root["path"], "encrypted": root["fstype"] == "crypto_LUKS",
             "esp": next((p["path"] for p in parts if p["esp"] and p["path"] != boot["path"]), None),
             "boot_is_esp": boot["esp"], "users": []}
    if not found["encrypted"]:
        found["users"] = bromigos_users(root["path"])
    return found


def bromigos_users(dev, mapper=None):
    """The people on an installed bromigOS's root: [{name, uid, gid, gecos, home, shell}]."""
    d = tempfile.mkdtemp(prefix="bromigos-root-")
    users = []
    try:
        if run(["mount", "-o", "ro,subvol=@", mapper or dev, d]).returncode != 0:
            return users
        try:
            for line in open(os.path.join(d, "etc/passwd")):
                f = line.rstrip("\n").split(":")
                if len(f) >= 7 and f[2].isdigit() and 1000 <= int(f[2]) < 60000 and not f[6].endswith(("nologin", "false")):
                    users.append({"name": f[0], "uid": int(f[2]), "gid": int(f[3]), "gecos": f[4], "home": f[5], "shell": f[6]})
        except OSError:
            pass
        finally:
            run(["umount", d])
    finally:
        os.rmdir(d)
    return users


def reinstall_option(d):
    b = d.get("bromigos")
    if not b:
        return {"ok": False, "code": "none", "why": "There's no bromigOS on this disk to reinstall.", "fix": ""}
    return {"ok": True, **b, "label": "Reinstall bromigOS and keep my files",
            "words": ("A fresh bromigOS system; your home folder and everything in it stay. The old system is kept as a "
                      "snapshot, so nothing is lost.") + (" You'll be asked the disk's passphrase to unlock it." if b["encrypted"] else "")}


def erase_option(d):
    if d["medium"]:
        return _why("medium")
    if d["size"] < MIN_BROMIGOS:
        return _why("too-small")
    if any(p["mounted"] for p in d["partitions"]):
        return _why("mounted")
    lost = ", ".join(d["oses"]) if d["oses"] else ("the files on it" if d["partitions"] else "nothing: it's empty")
    return {"ok": True, "loses": lost}


def alongside_option(d, fw):
    """Whether, and how, bromigOS can go beside what's on the disk: in free space, or by
    shrinking one partition. {ok, mode: free|shrink, name, ...} or {ok: False, code, why, fix}."""
    name = d["oses"][0] if d["oses"] else None
    base = {"name": name, "label": f"Install alongside {name}" if name else "Install alongside what's on it"}
    if not d["partitions"]:
        return {"ok": False, "code": "empty", "why": "The disk is empty: there's nothing to install beside.",
                "fix": "Choose Erase the whole disk: nothing is lost.", **base}
    if d["medium"]:
        return {**_why("medium"), **base}
    if any(p["mounted"] for p in d["partitions"]):
        return {**_why("mounted"), **base}
    esp = None
    if fw == "uefi":
        if d["table"] != "gpt":
            return {**_why("uefi-mbr"), **base}
        esps = [p for p in d["partitions"] if p["esp"]]
        esps.sort(key=lambda p: (not p.get("has_microsoft"), p["start"]))
        if not esps:
            return {**_why("no-esp"), **base}
        esp = esps[0]
        if esp.get("esp_free") is not None and esp["esp_free"] < ESP_FREE_NEEDED:
            return {**_why("esp-full"), **base}
    else:
        if d["table"] != "dos":
            return {**_why("bios-gpt"), **base}
        primaries = [p for p in d["partitions"] if _partnum(p["path"]) <= 4]
        if len(primaries) > 2:
            return {**_why("mbr-full"), **base}
    base["esp"] = esp["path"] if esp else None
    biggest = max(d["free"], key=lambda f: f["size"], default=None)
    if biggest and biggest["size"] >= MIN_BROMIGOS:
        return {"ok": True, "mode": "free", "size": biggest["size"], "size_text": plain_size(biggest["size"]),
                **base, "warn": _bitlocker_warning(d)}
    # shrink: the biggest partition with room to spare, skipping the ones it mustn't touch
    blocked = []
    cands = sorted((p for p in d["partitions"] if p["fstype"] in ("ntfs", "ext4", "BitLocker")),
                   key=lambda p: p["size"], reverse=True)
    for p in cands:
        if p["bitlocker"]:
            blocked.append("bitlocker")
            continue
        if p.get("hibernated"):
            blocked.append("hibernated")
            continue
        if p.get("dirty"):
            blocked.append("dirty")
            continue
        if p.get("min_bytes") is None:
            blocked.append("unreadable")
            continue
        room = ROOM.get("Windows" if (p.get("windows") or (name or "").startswith("Windows")) and p["fstype"] == "ntfs"
                        else "", OTHER_ROOM)
        keep_min = -(-(p["min_bytes"] + room) // GiB) * GiB          # whole GiB, rounded up
        after = [f for f in d["free"] if p["start"] + p["size"] <= f["start"] <= p["start"] + p["size"] + ALIGN]
        extra = after[0]["size"] if after else 0
        max_b = ((p["size"] - keep_min) // GiB) * GiB + (extra // GiB) * GiB
        if max_b >= MIN_BROMIGOS:
            default = min(max_b, max(MIN_BROMIGOS, min(GOOD_BROMIGOS, (p["size"] // 2 // GiB) * GiB)))
            who = name or ("Windows" if p["fstype"] == "ntfs" else "the other system")
            return {"ok": True, "mode": "shrink", **base, "partition": p["path"], "fs": p["fstype"],
                    "part_size": p["size"], "keep_min": keep_min, "free_after": extra,
                    "min": MIN_BROMIGOS, "max": max_b, "default": default, "who": who,
                    "warn": _bitlocker_warning(d)}
        blocked.append("small")
    for code in ("bitlocker", "hibernated", "dirty", "unreadable"):
        if code in blocked:
            return {**_why(code), **base}
    return {**_why("small"), **base}


def _bitlocker_warning(d):
    if any(p["bitlocker"] for p in d["partitions"]):
        return ("Windows here is locked with BitLocker. The first time Windows starts after this, "
                "it may ask for its BitLocker recovery key: have it ready (it's in your Microsoft "
                "account, at aka.ms/myrecoverykey).")
    return None


def _partnum(path):
    m = re.search(r"(\d+)$", path)
    return int(m.group(1)) if m else 0


def probe(deep=True):
    """Every disk the installer could use, as plain facts and choices."""
    fw = firmware()
    medium = medium_disks()
    os_names = os_prober() if deep else {}
    disks = []
    for dev in lsblk():
        if dev.get("type") != "disk" or (dev.get("name") or "").startswith(("loop", "sr", "zram", "ram")):
            continue
        if dev.get("ro") or int(dev.get("size") or 0) == 0:
            continue
        parts = [c for c in dev.get("children", []) if c.get("type") == "part"]
        table = sfdisk_json(dev["path"]) if parts or dev.get("pttype") else None
        disks.append(disk_picture(dev, parts, table, os_names, fw, medium, deep))
    disks.sort(key=lambda d: (d["medium"], d["removable"], d["path"]))
    return {"firmware": fw, "disks": disks, "other_os": any(d["oses"] for d in disks if not d["medium"])}


# ── making the room ─────────────────────────────────────────────────────────────────────
def stage(pct, text):
    print(f"::stage {pct} {text}", flush=True)


def shrink(part, fs, bromigos_bytes, say=print):
    """Shrink PART's file system and then the partition, leaving BROMIGOS_BYTES free after
    it (less any free space already there). Checks first; raises SystemExit with plain words."""
    disk_r = run(["lsblk", "-no", "PKNAME", part])
    disk = "/dev/" + disk_r.stdout.split()[0]
    table = sfdisk_json(disk)
    tp = next((p for p in table["partitions"] if p["node"] == part), None)
    if tp is None:
        raise SystemExit(f"{part} isn't on {disk}'s partition table")
    ss = int(table.get("sectorsize", 512))
    size = int(tp["size"]) * ss
    after = [f for f in free_regions(table, int(run(["blockdev", "--getsize64", disk]).stdout or 0))
             if (int(tp["start"]) + int(tp["size"])) * ss <= f["start"] <= (int(tp["start"]) + int(tp["size"])) * ss + ALIGN]
    extra = after[0]["size"] if after else 0
    take = max(0, bromigos_bytes + 2 * ALIGN - extra)         # a little over: GPT's backup table, alignment
    new_size = ((size - take) // ALIGN) * ALIGN
    if take == 0:
        say("there's room already: nothing to shrink")
        return
    if run(["findmnt", "-rno", "TARGET", "-S", part]).stdout.strip():
        raise SystemExit("the partition is mounted: close whatever is using it")
    if fs == "ntfs":
        f = ntfs_facts(part)
        if f["hibernated"] or f["dirty"] or f["min_bytes"] is None:
            raise SystemExit("Windows' drive isn't safe to change: " + ("it's paused (Fast Startup)" if f["hibernated"] else "it needs a check"))
        if new_size - ALIGN < f["min_bytes"]:
            raise SystemExit("Windows needs more room than that")
        fs_size = new_size - ALIGN                              # the file system a little inside the partition
        say(f"ntfsresize --size {fs_size} {part}")
        r = run(["ntfsresize", "--no-action", "--no-progress-bar", "--size", str(fs_size), part], timeout=3600)
        if r.returncode != 0:
            raise SystemExit("the test run of the resize failed: " + (r.stdout + r.stderr).strip().splitlines()[-1])
        r = run(["ntfsresize", "--no-progress-bar", "--size", str(fs_size), part], input="y\n", timeout=6 * 3600)
        say(r.stdout + r.stderr)
        if r.returncode != 0:
            raise SystemExit("resizing Windows' file system failed (it's unchanged)")
    elif fs == "ext4":
        r = run(["e2fsck", "-f", "-p", part], timeout=3600)
        if r.returncode not in (0, 1):
            raise SystemExit("the file system's check found problems: it's unchanged")
        fs_size = new_size - ALIGN
        r = run(["resize2fs", part, f"{fs_size // KiB}K"], timeout=6 * 3600)
        say(r.stdout + r.stderr)
        if r.returncode != 0:
            raise SystemExit("resizing the file system failed (it's unchanged)")
    else:
        raise SystemExit(f"bromigOS doesn't shrink {fs}")
    num = _partnum(part)
    say(f"sfdisk -N {num} {disk}: size {new_size // ss} sectors")
    r = run(["sfdisk", "--no-reread", "-N", str(num), disk], input=f",{new_size // ss}\n")
    say(r.stdout + r.stderr)
    if r.returncode != 0:
        raise SystemExit("the partition table couldn't be changed (the file system is smaller, the partition isn't)")
    run(["partx", "-u", disk])
    run(["udevadm", "settle"])
    if fs == "ntfs":
        # --force: the resize itself marks the volume for Windows' own check at its next
        # start (chkdsk runs once, by itself); the file system must still read as whole
        r = run(["ntfsresize", "--info", "--force", "--no-progress-bar", part], timeout=600)
        if "you might resize at" not in (r.stdout + r.stderr).lower():
            raise SystemExit("Windows' drive didn't check out after the resize: " + (r.stdout + r.stderr).strip()[-300:])
    else:
        r = run(["e2fsck", "-f", "-n", part], timeout=3600)
        if r.returncode != 0:
            raise SystemExit("the file system didn't check out after the resize")


def main():
    args = sys.argv[1:]
    if not args or args[0] in ("-h", "--help"):
        print(__doc__.strip())
        return 0
    if args[0] == "probe":
        doc = probe(deep="--quick" not in args)
        print(json.dumps(doc, indent=None if "--json" in args else 2))
        return 0
    if args[0] == "shrink":
        a = json.loads(_read(args[args.index("--answers") + 1]))
        s = a.get("shrink")
        if not s:
            return 0
        stage(4, f"Making room: shrinking {s.get('who') or 'the other system'} (this can take a while)")
        try:
            shrink(s["partition"], s["fs"], int(s["bromigos_bytes"]), say=lambda t: print(t, flush=True))
        except SystemExit as e:
            print(f"::error Making room beside {s.get('who') or 'the other system'} failed: {e}. "
                  "Nothing was installed, and its files are as they were.", flush=True)
            return 1
        stage(9, "The room is ready")
        return 0
    print(__doc__.strip(), file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
