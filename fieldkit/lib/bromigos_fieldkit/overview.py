"""The Home screen's facts (docs/fieldkit.md, "The menu"): this computer, what's on its drives,
the network and the stick, and suggestions from real findings only. Read-only, quick, offline:
nothing is mounted or unlocked to find them.

  fieldkit-engine engine overview
"""

import glob
import json
import os
import re
import time

from . import system

SYS = os.environ.get("BROMIGOS_SYSFS", "/sys")


def read(path, default=""):
    try:
        return system.read(path).strip()
    except OSError:
        return default


def computer():
    dmi = os.path.join(SYS, "class/dmi/id")
    vendor, board = read(f"{dmi}/board_vendor"), read(f"{dmi}/board_name")
    product = read(f"{dmi}/product_name")
    name = " ".join(x for x in (read(f"{dmi}/sys_vendor"), product) if x and x != "System Product Name")
    cpu = ""
    try:
        for line in system.read("/proc/cpuinfo").splitlines():
            if line.startswith("model name"):
                cpu = re.sub(r"\s+", " ", line.split(":", 1)[1].strip())
                break
    except OSError:
        pass
    cores = len(glob.glob(os.path.join(SYS, "devices/system/cpu/cpu[0-9]*")))
    ram = ""
    try:
        kb = int(re.search(r"MemTotal:\s+(\d+)", system.read("/proc/meminfo")).group(1))
        ram = f"{kb / 1024 / 1024:.0f} GB" if kb > 1024 * 1024 else f"{kb // 1024} MB"
    except (OSError, AttributeError):
        pass
    gpus = []
    r = system.run(["lspci", "-mm", "-d", "::0300"], check=False)
    r2 = system.run(["lspci", "-mm", "-d", "::0302"], check=False)
    for line in (r.stdout + r2.stdout).splitlines():
        parts = re.findall(r'"([^"]*)"', line)
        if len(parts) >= 3:
            gpus.append(f"{parts[1]} {parts[2]}".replace(" Corporation", "").replace("Advanced Micro Devices, Inc. ", ""))
    temps = []
    for hw in sorted(glob.glob(os.path.join(SYS, "class/hwmon/hwmon*"))):
        chip = read(f"{hw}/name")
        for t in sorted(glob.glob(f"{hw}/temp*_input"))[:2]:
            try:
                c = int(read(t, "0")) / 1000
            except ValueError:
                continue
            if 0 < c < 130:
                label = read(t.replace("_input", "_label")) or chip
                temps.append({"label": label, "celsius": round(c)})
    return {"name": name, "board": " ".join(x for x in (vendor, board) if x), "cpu": cpu, "cores": cores,
            "ram": ram, "gpus": gpus, "temps": temps[:6]}


def network():
    kind, name = "none", ""
    r = system.run(["nmcli", "-t", "-f", "TYPE,STATE,CONNECTION", "device"], check=False)
    for line in r.stdout.splitlines():
        parts = line.split(":")
        if len(parts) >= 3 and parts[1] == "connected" and parts[0] in ("ethernet", "wifi"):
            kind, name = ("wired" if parts[0] == "ethernet" else "wifi"), parts[2]
            break
    return {"kind": kind, "state": system.link(), "name": name}


def found():
    """Each OS or install on the drives, and the sticks, from what blkid and the firmware's
    boot entries say. Nothing is mounted."""
    out = []
    target = system.Target.load()
    for p in system.block_devices():
        t = getattr(p, "type", "")
        where = os.path.basename(p.path)
        if t == "disk" and (p.removable or p.tran == "usb"):
            out.append({"kind": "usb", "title": f"USB drive {where}", "device": p.path,
                        "state": " ".join(x for x in (p.size, p.model) if x), "detail": ""})
            continue
        if p.fstype == "crypto_LUKS":
            opened = target is not None and target.device == p.path
            out.append({"kind": "bromigos", "title": f"bromigOS on {where}", "device": p.path,
                        "state": "encrypted, open" if opened else "encrypted, locked",
                        "detail": target.hostname() if opened else "probably bromigOS (an encrypted btrfs install)"})
        elif p.fstype == "btrfs" and not p.mountpoints:
            out.append({"kind": "linux", "title": f"btrfs on {where}", "device": p.path, "state": p.size,
                        "detail": p.label or ""})
        elif p.fstype == "BitLocker":
            out.append({"kind": "windows", "title": f"Windows on {where}", "device": p.path,
                        "state": "BitLocker on", "detail": p.size})
        elif p.fstype == "ntfs" and p.size and not p.label.lower().startswith(("recovery", "system")):
            out.append({"kind": "windows", "title": f"Windows on {where}", "device": p.path,
                        "state": "NTFS", "detail": " ".join(x for x in (p.size, p.label) if x)})
        elif p.label in ("FIELDKIT", "Ventoy", "BROMIGOS_FIELD_KIT"):
            out.append({"kind": "fieldkit", "title": f"Field Kit stick ({p.label})", "device": p.path,
                        "state": "settings" if p.label == "FIELDKIT" else "", "detail": ""})
    return out


def suggestions(items, computer_doc):
    """Only from real findings."""
    out = []
    target = system.Target.load() or system.running_install()
    if target and not target.is_live_root:
        try:
            from . import diagnose
            for f in diagnose.last_boot(target):
                if not f.ok and ("failed to start" in f.title or "didn't shut down" in f.title
                                 or "graphics driver" in f.title):
                    out.append({"text": f"{target.hostname()}: {f.title.lower()} last time → Find out why",
                                "action": "why", "device": target.device or ""})
                    break
        except (system.Failed, OSError):
            pass
    elif not target or target.is_live_root:
        locked = [i for i in items if i["kind"] == "bromigos" and i["state"].endswith("locked")]
        if len(locked) == 1 and "bromigos.fieldkit=disk" in system.cmdline():
            out.append({"text": f"Started from {locked[0]['title']}'s boot menu → Open it to repair",
                        "action": "mount", "device": locked[0]["device"]})
    hot = [t for t in computer_doc.get("temps", []) if t["celsius"] >= 90]
    if hot:
        out.append({"text": f"{hot[0]['label']} is at {hot[0]['celsius']} °C → See what's running",
                    "action": "tools:btop", "device": ""})
    return out


def overview():
    from . import medium
    c = computer()
    items = found()
    try:
        version = system.read("/version").strip() if os.path.exists("/run/archiso") else system.read("/usr/share/bromigos/fieldkit/version").strip()
    except OSError:
        version = ""
    st = medium.remote_state()
    ssh_on = system.run(["systemctl", "is-active", "--quiet", "sshd.service"], check=False).returncode == 0
    return {"ok": True, "version": version, "clock": time.strftime("%H:%M"), "network": network(),
            "ssh": {"on": ssh_on}, "remote": st, "stick": medium.stick_summary(), "live": system.live_medium(),
            "computer": c, "found": items, "suggestions": suggestions(items, c)}


if __name__ == "__main__":
    print(json.dumps(overview(), indent=1))
