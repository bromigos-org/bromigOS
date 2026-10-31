"""Erase a drive for good (docs/fieldkit.md, "Erase a drive"), with a report you keep.

The drive's own erase comes first, because only the drive can reach every cell it has (spare
blocks, remapped sectors): NVMe's sanitize or format with secure erase, ATA's security erase.
Then a discard of every block (blkdiscard --secure where the drive offers it). Last, one
overwrite pass: nwipe when it's there, else dd from /dev/zero.

  erase plan DEV                                  what this drive can do, best first
  erase run DEV --confirm NAME --method METHOD    NAME must be the drive's own name (sdb); never
                                                  the drive Field Kit started from, never a
                                                  mounted one. Writes a report and returns its path

Methods: nvme-sanitize-crypto, nvme-sanitize-block, nvme-format-crypto, nvme-format,
ata-secure-erase-enhanced, ata-secure-erase, blkdiscard-secure, blkdiscard, nwipe, zero.
The report goes on the stick's FIELDKIT partition (fieldkit/reports/) when there is one, else
/run/bromigos-fieldkit/reports/.
"""

import json
import os
import random
import re
import time

from . import system
from .imaging import Args, boot_disk, mounted, name_of, parent_disk, size_of, stream

RUN = os.environ.get("BROMIGOS_FIELDKIT_RUN", "/run/bromigos-fieldkit")
STICK_LABEL = os.environ.get("BROMIGOS_FIELDKIT_STICK_DEV", "/dev/disk/by-label/FIELDKIT")
ATA_PASS = "bromigos"           # the temporary password ATA's erase needs; the erase clears it

METHODS = {
    "nvme-sanitize-crypto": "the drive throws away its encryption key: every block becomes unreadable at once (NVMe sanitize)",
    "nvme-sanitize-block": "the drive erases every block it has, spare ones too (NVMe sanitize)",
    "nvme-format-crypto": "the drive throws away its encryption key while formatting (NVMe format)",
    "nvme-format": "the drive erases its user data while formatting (NVMe format)",
    "ata-secure-erase-enhanced": "the drive erases every block, spare and remapped ones too (ATA enhanced security erase)",
    "ata-secure-erase": "the drive erases every block it lets the system see (ATA security erase)",
    "blkdiscard-secure": "every block discarded, securely, by the drive",
    "blkdiscard": "every block discarded (fast; the data is usually unrecoverable on SSDs)",
    "nwipe": "one pass of zeros over every block, then read back (nwipe)",
    "zero": "one pass of zeros over every block (dd)",
}


def drive_info(dev):
    r = system.run(["lsblk", "-dndo", "MODEL,SERIAL,TRAN,ROTA", "-J", dev], check=False)
    try:
        d = json.loads(r.stdout)["blockdevices"][0]
    except (ValueError, KeyError, IndexError):
        d = {}
    return {"device": dev, "name": name_of(dev), "model": (d.get("model") or "").strip(),
            "serial": (d.get("serial") or "").strip(), "transport": d.get("tran") or "",
            "rotational": bool(d.get("rota")), "bytes": size_of(dev), "size": system.human(size_of(dev))}


def nvme_caps(dev):
    """(sanitize: {"crypto", "block", "overwrite"}, format crypto erase) from nvme id-ctrl."""
    r = system.run(["nvme", "id-ctrl", "-o", "json", dev], check=False)
    try:
        d = json.loads(r.stdout)
    except ValueError:
        return set(), False, False
    sanicap = int(d.get("sanicap", 0))
    fna = int(d.get("fna", 0))
    san = {n for bit, n in ((0, "crypto"), (1, "block"), (2, "overwrite")) if sanicap & (1 << bit)}
    return san, bool(fna & 0b100), True


def ata_caps(dev):
    """(supported, frozen, enhanced) from hdparm -I's Security section."""
    r = system.run(["hdparm", "-I", dev], check=False)
    sec = r.stdout.split("Security:", 1)[1] if "Security:" in r.stdout else ""
    sec = sec.split("\n\n", 1)[0]
    supported = bool(re.search(r"^\s*supported\s*$", sec, re.M))
    frozen = bool(re.search(r"^\s*frozen\s*$", sec, re.M)) and not re.search(r"not\s+frozen", sec)
    enhanced = bool(re.search(r"^\s*supported: enhanced erase", sec, re.M))
    return supported, frozen, enhanced


def discard_caps(dev):
    r = system.run(["lsblk", "-dnbo", "DISC-MAX", dev], check=False)
    try:
        return int(r.stdout.strip() or 0) > 0
    except ValueError:
        return False


def plan(dev):
    info = drive_info(dev)
    methods, notes = [], []
    if name_of(dev).startswith("nvme"):
        san, fmt_crypto, ok = nvme_caps(dev)
        if "crypto" in san:
            methods.append("nvme-sanitize-crypto")
        if "block" in san:
            methods.append("nvme-sanitize-block")
        if ok:
            if fmt_crypto:
                methods.append("nvme-format-crypto")
            methods.append("nvme-format")
    else:
        supported, frozen, enhanced = ata_caps(dev)
        if supported and frozen:
            notes.append("The drive's own erase is locked (frozen) until the machine sleeps once: "
                         "suspend and wake it (Shell › Restart isn't enough), then look again.")
        elif supported:
            if enhanced:
                methods.append("ata-secure-erase-enhanced")
            methods.append("ata-secure-erase")
    if discard_caps(dev):
        methods += ["blkdiscard-secure", "blkdiscard"]
    methods.append("nwipe" if system.have("nwipe") else "zero")
    if info["transport"] == "usb" and not name_of(dev).startswith("nvme"):
        notes.append("Through USB, a drive's own erase is often hidden by its adapter: connect it inside the machine for the best erase.")
    return {"ok": True, **info, "methods": [{"id": m, "what": METHODS[m]} for m in methods],
            "recommended": methods[0], "notes": notes}


def refuse(dev, confirm):
    if confirm != name_of(dev):
        raise system.Failed(f"To erase {name_of(dev)}, type its name ({name_of(dev)}) exactly. Nothing was erased.")
    boot = boot_disk()
    if boot and (dev == boot or parent_disk(dev) == boot):
        raise system.Failed(f"{name_of(dev)} is the drive Field Kit started from. Nothing was erased.")
    if mounted(dev):
        raise system.Failed(f"{name_of(dev)} is in use (mounted). Unmount it first. Nothing was erased.")
    stick = os.path.realpath(STICK_LABEL) if os.path.exists(STICK_LABEL) else None
    if stick and (parent_disk(stick) == dev or stick == dev):
        raise system.Failed(f"{name_of(dev)} holds Field Kit's settings (FIELDKIT). Nothing was erased.")


def command(dev, method, logfile):
    """The shell command for a method (its output gives the progress)."""
    if method == "nvme-sanitize-crypto":
        return f"nvme sanitize {dev} --sanact=4 && nvme_wait {dev}"
    if method == "nvme-sanitize-block":
        return f"nvme sanitize {dev} --sanact=2 && nvme_wait {dev}"
    if method == "nvme-format-crypto":
        return f"nvme format {dev} --ses=2 --force"
    if method == "nvme-format":
        return f"nvme format {dev} --ses=1 --force"
    if method in ("ata-secure-erase-enhanced", "ata-secure-erase"):
        flag = "--security-erase-enhanced" if method.endswith("enhanced") else "--security-erase"
        return (f"hdparm --user-master u --security-set-pass {ATA_PASS} {dev} && "
                f"hdparm --user-master u {flag} {ATA_PASS} {dev}")
    if method == "blkdiscard-secure":
        return f"blkdiscard --secure -f {dev}"
    if method == "blkdiscard":
        return f"blkdiscard -f {dev}"
    if method == "nwipe":
        reports = os.path.join(RUN, "reports")
        return (f"mkdir -p {reports} && nwipe --autonuke --nogui --nowait --method=zero --rounds=1 --verify=last "
                f"--logfile={logfile} --PDFreportpath={reports} {dev}")
    if method == "zero":
        return f"dd if=/dev/zero of={dev} bs=4M oflag=direct conv=fsync status=progress"
    raise system.Failed(f"There's no erase method called {method}.")


NVME_WAIT = r'''nvme_wait() {   # sanitize runs in the drive: follow its log until it's done
    while :; do
        p=$(nvme sanitize-log "$1" -o json 2>/dev/null | sed -n 's/.*"sprog" *: *\([0-9]*\).*/\1/p' | head -1)
        s=$(nvme sanitize-log "$1" -o json 2>/dev/null | sed -n 's/.*"sstat" *: *\([0-9]*\).*/\1/p' | head -1)
        [ -n "$p" ] && echo "$(( p * 100 / 65535 ))%"
        [ "$(( ${s:-1} & 7 ))" != 2 ] && break
        sleep 2
    done
}
'''


def sample(dev, size, n=16):
    """Reads n blocks of 4 KiB across the drive: (blocks read, blocks all zeros)."""
    read = zero = 0
    if size < 4096:
        return 0, 0
    spots = [0, max(size - 4096, 0)] + [random.randrange(0, size // 4096) * 4096 for _ in range(n - 2)]
    try:
        with open(dev, "rb") as f:
            for off in spots:
                f.seek(off)
                b = f.read(4096)
                if b:
                    read += 1
                    zero += not any(b)
    except OSError:
        pass
    return read, zero


def report_dir():
    """The stick's FIELDKIT partition, writable for the moment, else /run's."""
    if os.path.exists(STICK_LABEL):
        dev = os.path.realpath(STICK_LABEL)
        r = system.run(["findmnt", "-rno", "TARGET", "--source", dev], check=False)
        mp = r.stdout.split()[0] if r.stdout.split() else None
        if mp:
            system.run(["mount", "-o", "remount,rw", mp], check=False)
            d = os.path.join(mp, "fieldkit", "reports")
            return d, lambda: system.run(["mount", "-o", "remount,ro", mp], check=False)
        mp = os.path.join(RUN, "stick-rw")
        os.makedirs(mp, exist_ok=True)
        if system.run(["mount", dev, mp], check=False).returncode == 0:
            return os.path.join(mp, "fieldkit", "reports"), lambda: system.run(["umount", mp], check=False)
    return os.path.join(RUN, "reports"), lambda: None


def write_report(info, method, started, ended, rc, tail, sampled):
    d, done = report_dir()
    try:
        os.makedirs(d, exist_ok=True)
        path = os.path.join(d, f"erase-{info['name']}-{time.strftime('%Y%m%d-%H%M%S', time.localtime(started))}.txt")
        read, zero = sampled
        lines = [
            "bromigOS Field Kit: drive erase report",
            "",
            f"Drive:     {info['device']} ({info['model'] or 'unknown model'})",
            f"Serial:    {info['serial'] or 'not reported'}",
            f"Size:      {info['size']} ({info['bytes']} bytes)",
            f"Method:    {method}: {METHODS.get(method, '')}",
            f"Started:   {time.strftime('%Y-%m-%d %H:%M:%S %Z', time.localtime(started))}",
            f"Finished:  {time.strftime('%Y-%m-%d %H:%M:%S %Z', time.localtime(ended))}",
            f"Result:    {'erased' if rc == 0 else f'FAILED (exit {rc})'}",
            f"Check:     {read} blocks of 4 KiB read back across the drive, {zero} all zeros"
            + (" (a key or firmware erase leaves random-looking data: that's expected)" if method in
               ("nvme-sanitize-crypto", "nvme-format-crypto", "blkdiscard", "blkdiscard-secure") else ""),
            "",
            "The erase's last words:",
        ] + [f"  {t}" for t in tail]
        with open(path, "w") as f:
            f.write("\n".join(lines) + "\n")
            f.flush()
            os.fsync(f.fileno())
    finally:
        done()
    return path


def run_erase(dev, confirm, method, progress):
    refuse(dev, confirm)
    p = plan(dev)
    if method not in [m["id"] for m in p["methods"]]:
        raise system.Failed(f"{name_of(dev)} can't be erased with {method} here. It offers: "
                            + ", ".join(m["id"] for m in p["methods"]) + ".")
    info = {k: p[k] for k in ("device", "name", "model", "serial", "bytes", "size")}
    os.makedirs(RUN, exist_ok=True)
    logfile = os.path.join(RUN, f"nwipe-{info['name']}.log")
    started = time.time()
    progress(0, f"Erasing {info['name']} ({info['model'] or info['size']}): {METHODS[method]}")
    rc, tail = stream(NVME_WAIT + command(dev, method, logfile), progress)
    ended = time.time()
    progress(100 if rc == 0 else None, "Reading the drive back…")
    sampled = sample(dev, info["bytes"])
    path = write_report(info, method, started, ended, rc, tail, sampled)
    if rc != 0:
        return {"ok": False, "report": path,
                "message": f"The erase didn't finish ({tail[-1] if tail else f'exit {rc}'}). The report is in {path}."}
    read, zero = sampled
    if method in ("zero", "nwipe") and read and zero != read:
        return {"ok": False, "report": path, "message": f"The erase ran, but {read - zero} of {read} blocks read back "
                                                        f"weren't zeros. The drive may be failing. The report is in {path}."}
    return {"ok": True, "report": path, "message": f"{info['name']} is erased. The report is in {path}."}


def engine(args, progress):
    ap = Args(prog="erase")
    sub = ap.add_subparsers(dest="verb", required=True)
    p = sub.add_parser("plan")
    p.add_argument("device")
    p = sub.add_parser("run")
    p.add_argument("device")
    p.add_argument("--confirm", required=True)
    p.add_argument("--method", required=True)
    a = ap.parse_args(args)
    if a.verb == "plan":
        return plan(a.device)
    return run_erase(a.device, a.confirm, a.method, progress)
