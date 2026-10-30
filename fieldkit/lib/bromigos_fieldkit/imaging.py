"""Disk images and clones, in Clonezilla's format (docs/fieldkit.md, "Disk images and clones").

An image Field Kit saves restores in Clonezilla and Rescuezilla, and theirs restore here. The
layout follows Clonezilla's own scripts: drbl/clonezilla's `ocs-sr` and `ocs-functions`
(https://gitlab.com/stevenshiau/clonezilla: output_partclone_image, save_part_table_mbr_dm_info,
dump_hidden_data_after_mbr), and Rescuezilla's reader of them
(https://github.com/rescuezilla/rescuezilla, parser/clonezilla_image.py). One folder per image:

  disk                          the disk's kernel name ("sda"), when the whole disk was saved
  parts                         the partitions saved ("sda1 sda2"), one line
  sda-pt.sf                     the partition table, `sfdisk --dump`
  sda-pt.parted                 `parted -s /dev/sda unit s print`, for people
  sda-mbr                       the first sector (MBR disks), and
  sda-hidden-data-after-mbr     the gap before the first partition (boot loaders hide there)
  sda-gpt-1st, sda-gpt-2nd      the GPT's headers and tables (34 sectors, 33 at the end)
  sda-gpt.gdisk                 `sgdisk -b` (GPT disks)
  sda1.ext4-ptcl-img.zst.aa     a partition by partclone, zstd, split in 4 GB pieces (.aa, .ab…);
                                unknown or encrypted file systems: partclone.dd ("dd")
  blkdev.list, blkid.list, dev-fs.list, Info-*.txt, clonezilla-img   what Clonezilla writes too

Images go to a USB drive, another disk, or a network share on the local network (SMB or NFS).
Every image is checked after it's written (partclone.chkimg reads each partition's image back).

  image list [--dir DIR]                          images found (default: mounted drives and shares)
  image targets                                   where an image can go
  image mount-share URL [--user U]                smb://host/share or nfs://host/path; the password on stdin
  image create --source DEV --dest DIR [--name N] [--no-verify]
  image verify DIR
  image restore --image DIR --target DEV --confirm NAME
  image clone --source DEV --target DEV --confirm NAME
"""

import argparse
import glob
import json
import os
import re
import subprocess
import time

from . import system

SPLIT = "4096MB"                   # Clonezilla's default piece size (ocs-sr -i 4096)
PARTCLONE_FS = {                   # blkid's TYPE -> partclone's tool and Clonezilla's name for it
    "ext2": "ext2", "ext3": "ext3", "ext4": "ext4", "btrfs": "btrfs", "vfat": "vfat", "ntfs": "ntfs",
    "exfat": "exfat", "xfs": "xfs", "f2fs": "f2fs", "hfsplus": "hfsp", "fat": "fat",
}
RUN = os.environ.get("BROMIGOS_FIELDKIT_RUN", "/run/bromigos-fieldkit")
IMG = re.compile(r"^(?P<part>[\w-]+)\.(?P<fs>[\w+-]+)-ptcl-img\.(?P<comp>zst|gz|bz2|xz|lz4|uncomp)\.(?P<piece>[a-z]{2,})$")


class Args(argparse.ArgumentParser):
    """argparse that says what's wrong instead of exiting (engine.py turns it into words)."""

    def error(self, message):
        raise ValueError(message)


def slurp(path):
    with open(path, errors="replace") as f:
        return f.read()


def name_of(dev):
    return os.path.basename(dev.rstrip("/"))


def size_of(dev):
    r = system.run(["blockdev", "--getsize64", dev], check=False)
    try:
        return int(r.stdout.strip())
    except ValueError:
        return os.path.getsize(dev) if os.path.isfile(dev) else 0


def fstype(dev):
    return system.run(["blkid", "-o", "value", "-s", "TYPE", dev], check=False).stdout.strip()


def parent_disk(dev):
    r = system.run(["lsblk", "-no", "PKNAME", dev], check=False)
    p = r.stdout.strip().splitlines()[0].strip() if r.stdout.strip() else ""
    return f"/dev/{p}" if p else None


def part_path(disk, number):
    """The kernel's name for partition NUMBER of DISK: sda1, nvme0n1p1, mmcblk0p1."""
    return f"{disk}p{number}" if disk[-1:].isdigit() else f"{disk}{number}"


def part_number(part):
    m = re.search(r"(\d+)$", part)
    return int(m.group(1)) if m else None


def disk_partitions(disk):
    """The disk's partitions, in order, from its own table (sfdisk -d)."""
    r = system.run(["sfdisk", "-d", disk], check=False)
    return [line.split(":", 1)[0].strip() for line in r.stdout.splitlines() if ":" in line and "start=" in line]


def mounted(dev):
    r = system.run(["lsblk", "-nrpo", "MOUNTPOINTS", dev], check=False)
    return [m for m in r.stdout.split() if m]


def boot_disk():
    """The disk Field Kit started from (never a target)."""
    r = system.run(["findmnt", "-no", "SOURCE", "/run/archiso/bootmnt"], check=False)
    src = r.stdout.strip()
    if not src:
        return None
    return parent_disk(src) or src


def stream(script, progress, env=None):
    """A bash pipeline (pipefail), its output lines passed on as progress; partclone's
    "Completed: 42.13%" becomes the percentage. Returns (exit status, the last lines)."""
    proc = subprocess.Popen(["bash", "-o", "pipefail", "-c", script], stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, text=True, bufsize=1, env=env)
    tail = []
    with proc.stdout:
        for raw in proc.stdout:
            for line in raw.replace("\r", "\n").splitlines():
                line = line.strip()
                if not line:
                    continue
                m = re.search(r"Completed:\s*([\d.]+)%", line) or re.search(r"\b(\d{1,3})%", line)
                progress(float(m.group(1)) if m else None, line)
                tail = (tail + [line])[-5:]
    return proc.wait(), tail


def q(s):
    return "'" + str(s).replace("'", "'\\''") + "'"


# ------------------------------------------------------------------ finding images

def is_image(d):
    return os.path.isdir(d) and (os.path.isfile(os.path.join(d, "clonezilla-img")) or os.path.isfile(os.path.join(d, "parts"))) \
        and bool(glob.glob(os.path.join(d, "*-ptcl-img.*")) or glob.glob(os.path.join(d, "*-pt.sf")))


def describe_image(d):
    parts = slurp(os.path.join(d, "parts")).split() if os.path.isfile(os.path.join(d, "parts")) else []
    disk = slurp(os.path.join(d, "disk")).split() if os.path.isfile(os.path.join(d, "disk")) else []
    pieces = glob.glob(os.path.join(d, "*-ptcl-img.*"))
    size = sum(os.path.getsize(p) for p in pieces)
    files = {}
    for p in pieces:
        m = IMG.match(os.path.basename(p))
        if m:
            files.setdefault(m.group("part"), m.group("fs"))
    by = "Field Kit" if os.path.isfile(os.path.join(d, "Info-fieldkit.txt")) else "Clonezilla or Rescuezilla"
    return {"path": d, "name": os.path.basename(d), "disk": disk[0] if disk else "", "parts": parts,
            "filesystems": files, "bytes": size, "size": system.human(size), "made_by": by,
            "whole_disk": bool(disk)}


def list_images(dirs):
    found = []
    for base in dirs:
        for d in [base] + sorted(glob.glob(os.path.join(base, "*"))) + sorted(glob.glob(os.path.join(base, "*", "*"))):
            if is_image(d) and d not in [f["path"] for f in found]:
                found.append(describe_image(d))
    return found


def default_dirs():
    out = []
    for p in system.block_devices():
        out += [m for m in p.mountpoints if m.startswith(("/run/media", "/mnt", "/run/bromigos-fieldkit"))]
    out += glob.glob(os.path.join(RUN, "share-*"))
    out += [d for d in ("/home/partimag",) if os.path.isdir(d)]
    return sorted(set(out))


# ------------------------------------------------------------------ where images go

def targets():
    boot = boot_disk()
    drives = []
    for p in system.block_devices():
        if getattr(p, "type", "") not in ("part", "disk") or p.fstype in ("", "crypto_LUKS", "swap", "iso9660"):
            continue
        if boot and (p.parent == boot or p.path == boot):
            continue
        kind = "USB drive" if (p.removable or p.tran == "usb") else "disk"
        drives.append({"path": p.path, "describe": p.describe(), "fstype": p.fstype, "kind": kind,
                       "mounted": p.mountpoints[0] if p.mountpoints else ""})
    shares = [{"path": d, "describe": slurp(os.path.join(d, ".fieldkit-share")).strip()
               if os.path.isfile(os.path.join(d, ".fieldkit-share")) else d, "kind": "network share", "mounted": d}
              for d in glob.glob(os.path.join(RUN, "share-*")) if os.path.ismount(d)]
    return drives + shares


def mount_share(url, user, password):
    """smb://host/share or nfs://host/path, mounted read-write under /run/bromigos-fieldkit."""
    if system.link() == "none":
        raise system.Failed("A network share is on your local network, and this machine has no network link. "
                            "Plug in a cable or join Wi-Fi first (Lab › Network settings).")
    n = len(glob.glob(os.path.join(RUN, "share-*"))) + 1
    mnt = os.path.join(RUN, f"share-{n}")
    os.makedirs(mnt, exist_ok=True)
    m = re.match(r"^(smb|cifs|nfs)://([^/]+)(/.*)$", url)
    if not m:
        raise system.Failed("Give the share as smb://host/share or nfs://host/path.")
    kind, host, path = m.groups()
    if kind == "nfs":
        r = system.run(["mount", "-t", "nfs", f"{host}:{path}", mnt], check=False, timeout=60)
    else:
        cred = os.path.join(RUN, f".share-{n}.cred")
        fd = os.open(cred, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as f:
            f.write(f"username={user or 'guest'}\npassword={password or ''}\n")
        try:
            r = system.run(["mount", "-t", "cifs", f"//{host}{path}", mnt, "-o", f"credentials={cred},uid=0,gid=0"],
                           check=False, timeout=60)
        finally:
            os.unlink(cred)
    if r.returncode != 0:
        os.rmdir(mnt)
        raise system.Failed(f"The share didn't mount: {(r.stderr or r.stdout).strip() or 'no answer'}")
    with open(os.path.join(mnt, ".fieldkit-share"), "w") as f:
        f.write(url)
    return {"ok": True, "message": f"{url} is ready at {mnt}.", "path": mnt}


# ------------------------------------------------------------------ saving

def save_table(disk, d, disk_name):
    """The disk's partition table and the sectors around it, as Clonezilla saves them."""
    pt = system.run(["blkid", "-o", "value", "-s", "PTTYPE", disk], check=False).stdout.strip() or "dos"
    dump = system.run(["sfdisk", "--dump", disk], check=False).stdout
    with open(os.path.join(d, f"{disk_name}-pt.sf"), "w") as f:
        f.write(dump)
    with open(os.path.join(d, f"{disk_name}-pt.parted"), "w") as f:
        f.write(system.run(["parted", "-s", disk, "unit", "s", "print"], check=False).stdout)
    starts = [int(m.group(1)) for m in re.finditer(r"start=\s*(\d+)", dump)]
    first = min(starts) if starts else 2048
    if pt == "gpt":
        system.run(["dd", f"if={disk}", f"of={os.path.join(d, disk_name + '-gpt-1st')}", "bs=512", "count=34"], check=False)
        sectors = size_of(disk) // 512
        system.run(["dd", f"if={disk}", f"of={os.path.join(d, disk_name + '-gpt-2nd')}", "bs=512",
                    f"skip={max(sectors - 33, 0)}", "count=33"], check=False)
        system.run(["sgdisk", "-b", os.path.join(d, f"{disk_name}-gpt.gdisk"), disk], check=False)
        with open(os.path.join(d, f"{disk_name}-gpt.sgdisk"), "w") as f:
            f.write(system.run(["sgdisk", "-p", disk], check=False).stdout)
    else:
        system.run(["dd", f"if={disk}", f"of={os.path.join(d, disk_name + '-mbr')}", "bs=512", "count=1"], check=False)
        gap = min(first, 2048) - 1
        if gap > 0:
            system.run(["dd", f"if={disk}", f"of={os.path.join(d, disk_name + '-hidden-data-after-mbr')}", "bs=512",
                        "skip=1", f"count={gap}"], check=False)
    return pt


def info_files(d, cmd, parts):
    with open(os.path.join(d, "blkdev.list"), "w") as f:
        f.write(system.run(["lsblk", "-o", "KNAME,NAME,SIZE,TYPE,FSTYPE,MOUNTPOINT,MODEL"], check=False).stdout)
    with open(os.path.join(d, "blkid.list"), "w") as f:
        f.write(system.run(["blkid"], check=False).stdout)
    with open(os.path.join(d, "dev-fs.list"), "w") as f:
        f.write("# <Device name>   <File system>   <Size>\n")
        f.write("# File system is got from blkid (bromigOS Field Kit). It might be different from that of parted.\n")
        for p, fs in parts:
            f.write(f"/dev/{p} {fs or 'unknown'} {system.human(size_of('/dev/' + p))}\n")
    with open(os.path.join(d, "Info-saved-by-cmd.txt"), "w") as f:
        f.write(" ".join(cmd) + "\n")
    with open(os.path.join(d, "Info-dmi.txt"), "w") as f:
        f.write(system.run(["dmidecode"], check=False).stdout)
    with open(os.path.join(d, "Info-lspci.txt"), "w") as f:
        f.write(system.run(["lspci"], check=False).stdout)
    with open(os.path.join(d, "Info-fieldkit.txt"), "w") as f:
        f.write(f"Saved by bromigOS Field Kit on {time.strftime('%Y-%m-%d %H:%M')}, in Clonezilla's image format.\n")
    with open(os.path.join(d, "clonezilla-img"), "w") as f:
        f.write(f"This image was saved by bromigOS Field Kit at {time.strftime('%Y-%m-%d %H:%M:%S')}, "
                "in Clonezilla's format (partclone, zstd).\n")


def tool_for(fs):
    """(partclone's program, Clonezilla's file system word) for blkid's TYPE."""
    name = PARTCLONE_FS.get(fs)
    if name:
        return f"partclone.{name}", name
    return "partclone.dd", "dd"


def save_part(dev, d, progress):
    pname = name_of(dev)
    fs = fstype(dev)
    tool, word = tool_for(fs)
    if fs == "swap":
        with open(os.path.join(d, f"swappt-{pname}.info"), "w") as f:
            f.write(system.run(["blkid", "-o", "export", dev], check=False).stdout)
        return pname, fs, True
    out = os.path.join(d, f"{pname}.{word}-ptcl-img.zst.")
    script = (f"{tool} -z 10485760 -L {q(os.path.join(RUN, 'partclone.log'))} -c -s {q(dev)} --output - "
              f"| zstd -T0 -c | split -a 2 -b {SPLIT} - {q(out)}")
    progress(0, f"Saving {pname} ({fs or 'unknown, sector by sector'}) with {tool}")
    rc, tail = stream(script, progress)
    if rc != 0:
        raise system.Failed(f"Saving {pname} failed: " + " / ".join(tail[-2:]))
    return pname, fs, True


def create(source, dest, name, verify, progress):
    if not os.path.isdir(dest):
        raise system.Failed(f"{dest} isn't a folder Field Kit can write to (mount the drive or share first).")
    t = system.run(["lsblk", "-ndo", "TYPE", source], check=False).stdout.strip()
    whole = t == "disk"
    if mounted(source):
        raise system.Failed(f"{name_of(source)} is in use (mounted). Unmount it first, so the image is consistent.")
    disk = source if whole else parent_disk(source)
    name = name or time.strftime("%Y-%m-%d-%H-") + ("img" if whole else "img-part")
    d = os.path.join(dest, name)
    if os.path.exists(d):
        raise system.Failed(f"{d} already exists: choose another name.")
    os.makedirs(d)
    parts = disk_partitions(source) if whole else [source]
    if whole:
        with open(os.path.join(d, "disk"), "w") as f:
            f.write(name_of(source) + "\n")
    with open(os.path.join(d, "parts"), "w") as f:
        f.write(" ".join(name_of(p) for p in parts) + "\n")
    if disk:
        save_table(disk, d, name_of(disk))
    saved = []
    for i, p in enumerate(parts):
        progress(100 * i / max(len(parts), 1), f"Partition {i + 1} of {len(parts)}: {name_of(p)}")
        saved.append(save_part(p, d, progress)[:2])
    info_files(d, ["fieldkit", "image", "create", "--source", source, "--dest", dest], saved)
    result = {"ok": True, "path": d, "message": f"Saved {name_of(source)} as {d}."}
    if verify:
        v = verify_image(d, progress)
        result["verified"] = v["ok"]
        result["message"] += " " + v["message"]
        result["ok"] = v["ok"]
    size = sum(os.path.getsize(p) for p in glob.glob(os.path.join(d, "*")) if os.path.isfile(p))
    result["size"] = system.human(size)
    return result


# ------------------------------------------------------------------ checking and restoring

def pieces(d, part):
    """A partition's image pieces, in order: (files, file system word, compression)."""
    found = sorted(p for p in glob.glob(os.path.join(d, f"{part}.*-ptcl-img.*")) if IMG.match(os.path.basename(p)))
    if not found:
        return [], None, None
    m = IMG.match(os.path.basename(found[0]))
    return found, m.group("fs"), m.group("comp")


DECOMP = {"zst": "zstd -dc", "gz": "gzip -dc", "bz2": "bzip2 -dc", "xz": "xz -dc", "lz4": "lz4 -dc", "uncomp": "cat"}


def verify_image(d, progress):
    if not is_image(d):
        raise system.Failed(f"{d} isn't a Clonezilla-style image.")
    parts = slurp(os.path.join(d, "parts")).split()
    bad = []
    for i, part in enumerate(parts):
        files, fs, comp = pieces(d, part)
        if not files:
            if glob.glob(os.path.join(d, f"swappt-{part}.info")):
                continue
            bad.append(f"{part}: no image")
            continue
        progress(100 * i / max(len(parts), 1), f"Checking {part}")
        script = f"cat {' '.join(q(f) for f in files)} | {DECOMP[comp]} | partclone.chkimg -s -"
        rc, tail = stream(script, progress)
        if rc != 0:
            bad.append(f"{part}: " + (tail[-1] if tail else "unreadable"))
    if bad:
        return {"ok": False, "message": "The image doesn't read back cleanly: " + "; ".join(bad) + "."}
    return {"ok": True, "message": f"Checked: every partition's image reads back cleanly ({len(parts)})."}


def table_end_bytes(sf_text):
    """How big a disk must be for this table: the end of its last partition, plus GPT's backup."""
    end = 0
    for m in re.finditer(r"start=\s*(\d+),\s*size=\s*(\d+)", sf_text):
        end = max(end, int(m.group(1)) + int(m.group(2)))
    gpt = "label: gpt" in sf_text
    return (end + (33 if gpt else 0)) * 512


def guard(target, confirm, what):
    if confirm != name_of(target):
        raise system.Failed(f"To {what} {name_of(target)}, type its name ({name_of(target)}) to confirm. Nothing was written.")
    boot = boot_disk()
    if boot and (target == boot or parent_disk(target) == boot):
        raise system.Failed(f"{name_of(target)} is the drive Field Kit started from. Nothing was written.")
    if mounted(target):
        raise system.Failed(f"{name_of(target)} is in use (mounted). Unmount it first. Nothing was written.")


def retarget_table(sf_text, old_disk, new_disk):
    """sfdisk's dump for another disk: its own device names, no fixed last LBA."""
    out = []
    for line in sf_text.splitlines():
        if line.startswith(("device:", "last-lba:")):
            continue
        if ":" in line and "start=" in line:
            dev, rest = line.split(":", 1)
            n = part_number(dev.strip())
            line = f"{part_path(new_disk, n)} :{rest}"
        out.append(line)
    return "\n".join(out) + "\n"


def restore(image, target, confirm, progress):
    if not is_image(image):
        raise system.Failed(f"{image} isn't a Clonezilla-style image.")
    guard(target, confirm, "restore onto")
    parts = slurp(os.path.join(image, "parts")).split()
    whole = os.path.isfile(os.path.join(image, "disk"))
    if whole:
        disk_name = slurp(os.path.join(image, "disk")).split()[0]
        sf = os.path.join(image, f"{disk_name}-pt.sf")
        text = slurp(sf) if os.path.isfile(sf) else ""
        need = table_end_bytes(text)
        have = size_of(target)
        if need and have < need:
            raise system.Failed(f"{name_of(target)} is smaller ({system.human(have)}) than the image needs "
                                f"({system.human(need)}). Nothing was written.")
        progress(0, f"Writing the partition table to {name_of(target)}")
        r = system.run(["sfdisk", "--force", "--no-reread", target], input=retarget_table(text, "/dev/" + disk_name, target), check=False)
        if r.returncode != 0:
            raise system.Failed("The partition table didn't write: " + (r.stderr.strip().splitlines() or ["?"])[-1])
        hidden = os.path.join(image, f"{disk_name}-hidden-data-after-mbr")
        if os.path.isfile(hidden):
            system.run(["dd", f"if={hidden}", f"of={target}", "bs=512", "seek=1", "conv=notrunc"], check=False)
        system.run(["partprobe", target], check=False)
        system.run(["udevadm", "settle"], check=False)
        dests = {p: part_path(target, part_number(p)) for p in parts}
    else:
        if len(parts) != 1:
            raise system.Failed("This image holds several partitions without their disk: restore it in Clonezilla.")
        files, fs, comp = pieces(image, parts[0])
        need = 0
        dests = {parts[0]: target}
    for i, part in enumerate(parts):
        dst = dests[part]
        files, fs, comp = pieces(image, part)
        if not files:
            continue
        tool = "partclone.dd" if fs == "dd" else f"partclone.{fs}"
        progress(100 * i / max(len(parts), 1), f"Restoring {part} to {name_of(dst)}")
        script = f"cat {' '.join(q(f) for f in files)} | {DECOMP[comp]} | {tool} -z 10485760 -r -s - -o {q(dst)}"
        rc, tail = stream(script, progress)
        if rc != 0:
            raise system.Failed(f"Restoring {part} failed: " + " / ".join(tail[-2:]))
    system.run(["sync"], check=False)
    return {"ok": True, "message": f"Restored {os.path.basename(image)} onto {name_of(target)}."}


def clone(source, target, confirm, progress):
    """Disk to disk (or partition to partition): the table, then each partition with partclone's
    device-to-device mode; checked after by comparing each partition's file system and ID."""
    guard(target, confirm, "clone onto")
    if mounted(source):
        raise system.Failed(f"{name_of(source)} is in use (mounted). Unmount it first.")
    t = system.run(["lsblk", "-ndo", "TYPE", source], check=False).stdout.strip()
    if t == "disk":
        text = system.run(["sfdisk", "--dump", source]).stdout
        need, have = table_end_bytes(text), size_of(target)
        if have < need:
            raise system.Failed(f"{name_of(target)} is smaller ({system.human(have)}) than {name_of(source)}'s "
                                f"partitions need ({system.human(need)}). Nothing was written.")
        r = system.run(["sfdisk", "--force", "--no-reread", target], input=retarget_table(text, source, target), check=False)
        if r.returncode != 0:
            raise system.Failed("The partition table didn't write: " + (r.stderr.strip().splitlines() or ["?"])[-1])
        system.run(["partprobe", target], check=False)
        system.run(["udevadm", "settle"], check=False)
        pairs = [(p, part_path(target, part_number(p))) for p in disk_partitions(source)]
    else:
        if size_of(target) < size_of(source):
            raise system.Failed(f"{name_of(target)} is smaller than {name_of(source)}. Nothing was written.")
        pairs = [(source, target)]
    for i, (s, dst) in enumerate(pairs):
        fs = fstype(s)
        if fs == "swap":
            system.run(["mkswap", "-U", system.run(["blkid", "-o", "value", "-s", "UUID", s], check=False).stdout.strip() or "random", dst], check=False)
            continue
        tool, _ = tool_for(fs)
        progress(100 * i / max(len(pairs), 1), f"Copying {name_of(s)} to {name_of(dst)} with {tool}")
        rc, tail = stream(f"{tool} -z 10485760 -b -s {q(s)} -o {q(dst)}", progress)
        if rc != 0:
            raise system.Failed(f"Copying {name_of(s)} failed: " + " / ".join(tail[-2:]))
    system.run(["sync"], check=False)
    wrong = []
    for s, dst in pairs:
        a = system.run(["blkid", "-o", "value", "-s", "TYPE", "-s", "UUID", s], check=False).stdout.split()
        b = system.run(["blkid", "-p", "-o", "value", "-s", "TYPE", "-s", "UUID", dst], check=False).stdout.split()
        if a and a != b:
            wrong.append(name_of(dst))
    if wrong:
        return {"ok": False, "message": f"Copied, but {', '.join(wrong)} don't match their source. Check before using them."}
    return {"ok": True, "message": f"Cloned {name_of(source)} onto {name_of(target)}, and checked: every partition "
                                   "has its source's file system and ID."}


# ------------------------------------------------------------------ the engine's verbs

def engine(args, progress):
    ap = Args(prog="image")
    sub = ap.add_subparsers(dest="verb", required=True)
    p = sub.add_parser("list")
    p.add_argument("--dir", action="append")
    sub.add_parser("targets")
    p = sub.add_parser("mount-share")
    p.add_argument("url")
    p.add_argument("--user")
    p = sub.add_parser("create")
    p.add_argument("--source", required=True)
    p.add_argument("--dest", required=True)
    p.add_argument("--name")
    p.add_argument("--no-verify", action="store_true")
    p = sub.add_parser("verify")
    p.add_argument("dir")
    for verb in ("restore", "clone"):
        p = sub.add_parser(verb)
        if verb == "restore":
            p.add_argument("--image", required=True)
        else:
            p.add_argument("--source", required=True)
        p.add_argument("--target", required=True)
        p.add_argument("--confirm", required=True)
    a = ap.parse_args(args)
    if a.verb == "list":
        return {"ok": True, "images": list_images(a.dir or default_dirs())}
    if a.verb == "targets":
        return {"ok": True, "targets": targets()}
    if a.verb == "mount-share":
        import sys
        password = "" if sys.stdin.isatty() else sys.stdin.read().rstrip("\n")
        return mount_share(a.url, a.user, password)
    if a.verb == "create":
        return create(a.source, a.dest, a.name, not a.no_verify, progress)
    if a.verb == "verify":
        return verify_image(a.dir, progress)
    if a.verb == "restore":
        return restore(a.image, a.target, a.confirm, progress)
    return clone(a.source, a.target, a.confirm, progress)


if __name__ == "__main__":       # a manual check: python -m bromigos_fieldkit.imaging list --dir DIR
    import sys
    print(json.dumps(engine(sys.argv[1:], lambda p, line: print(p, line, file=sys.stderr)), indent=1))
