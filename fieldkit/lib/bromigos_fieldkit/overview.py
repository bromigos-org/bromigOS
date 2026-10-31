"""The Home screen's facts (docs/fieldkit.md, "The menu"): this computer (and how busy it is),
its disks and what's on them, the network and the stick, and suggestions from real findings
only. Read-only, quick, offline: nothing is mounted or unlocked to find them.

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


def cpu_times(text):
    """(busy, total) jiffies from /proc/stat's first line."""
    for line in text.splitlines():
        if line.startswith("cpu "):
            v = [int(x) for x in line.split()[1:]]
            idle = v[3] + (v[4] if len(v) > 4 else 0)
            return sum(v) - idle, sum(v)
    return 0, 0


def mem_pct(text):
    """Memory in use, in percent, from /proc/meminfo's text (what MemAvailable leaves)."""
    kb = {k: int(v) for k, v in re.findall(r"^(\w+):\s+(\d+)", text, re.M)}
    total, avail = kb.get("MemTotal", 0), kb.get("MemAvailable", kb.get("MemFree"))
    if not total or avail is None:
        return None
    return round(100 * (total - avail) / total, 1)


def load(gap=0.1):
    """How busy the processor is (from two looks at /proc/stat `gap` seconds apart, else the
    load average over the cores) and how much memory is in use, in percent."""
    cpu = None
    try:
        b0, t0 = cpu_times(system.read("/proc/stat"))
        time.sleep(gap)
        b1, t1 = cpu_times(system.read("/proc/stat"))
        if t1 > t0:
            cpu = round(100 * (b1 - b0) / (t1 - t0), 1)
    except OSError:
        pass
    if cpu is None:
        try:
            cpu = round(min(100.0, 100 * float(system.read("/proc/loadavg").split()[0]) / (os.cpu_count() or 1)), 1)
        except (OSError, ValueError, IndexError):
            pass
    try:
        mem = mem_pct(system.read("/proc/meminfo"))
    except OSError:
        mem = None
    return {"cpu_pct": cpu, "mem_pct": mem}


SMART_CACHE = os.environ.get("BROMIGOS_FIELDKIT_SMART_CACHE",
                             os.path.join(os.path.dirname(system.STATE), "smart.json"))
SMART_TTL = 600


def smart_verdict(text):
    """The drive's verdict from `smartctl -H -j`'s JSON: "ok", "failing", or "" (no report)."""
    try:
        doc = json.loads(text or "{}")
    except ValueError:
        return ""
    st = doc.get("smart_status") if isinstance(doc, dict) else None
    passed = st.get("passed") if isinstance(st, dict) else None
    if passed is True:
        return "ok"
    if passed is False:
        return "failing"
    return ""


def smart_health(paths, now=None):
    """Each disk's own health verdict (SMART): {path: "ok" | "failing"}, only where the disk
    reports one. A quick `smartctl -H -j` each, at most a few seconds, kept for ten minutes
    (the Home screen asks every 15 seconds). Without smartctl, nothing."""
    if not system.have("smartctl"):
        return {}
    now = time.time() if now is None else now
    try:
        with open(SMART_CACHE) as f:
            cache = json.load(f)
    except (OSError, ValueError):
        cache = {}
    changed = False
    for p in paths:
        hit = cache.get(p)
        if isinstance(hit, dict) and now - hit.get("at", 0) < SMART_TTL:
            continue
        try:
            r = system.run(["smartctl", "-H", "-j", p], check=False, timeout=3)
            verdict = smart_verdict(r.stdout)
        except system.Failed:
            verdict = ""
        cache[p] = {"at": now, "health": verdict}
        changed = True
    if changed:
        try:
            os.makedirs(os.path.dirname(SMART_CACHE), exist_ok=True)
            with open(SMART_CACHE, "w") as f:
                json.dump(cache, f)
        except OSError:
            pass
    return {p: cache[p]["health"] for p in paths if cache.get(p, {}).get("health")}


def disks_from(doc):
    """Each disk and its partitions from lsblk's JSON (sizes in bytes), for Home's disk maps:
    the partitions' filesystems and partition types say what each holds (bromigos-tui's
    diskmap names the kinds). Loop devices, RAM disks and optical drives are left out."""
    out = []
    for d in doc.get("blockdevices") or []:
        name = d.get("name") or ""
        if d.get("type") != "disk" or name.startswith(("zram", "loop", "sr", "ram")) or not int(d.get("size") or 0):
            continue
        parts = [{"name": c.get("name") or "", "path": c.get("path") or "", "size": int(c.get("size") or 0),
                  "fstype": c.get("fstype") or "", "label": c.get("label") or "",
                  "parttypename": c.get("parttypename") or ""}
                 for c in d.get("children") or [] if c.get("type") == "part"]
        out.append({"name": name, "path": d.get("path") or "", "size": int(d.get("size") or 0),
                    "model": (d.get("model") or "").strip(), "tran": d.get("tran") or "", "parts": parts})
    return out


def disks():
    r = system.run(["lsblk", "-J", "-b", "-o", "NAME,PATH,SIZE,TYPE,FSTYPE,LABEL,PARTTYPENAME,MODEL,TRAN"],
                   check=False, timeout=10)
    try:
        return disks_from(json.loads(r.stdout or "{}"))
    except ValueError:
        return []


def with_health(items, disk_docs, health):
    """The SMART verdict on each disk, and on what's found on it (a partition's disk's)."""
    owner = {}
    for d in disk_docs:
        if d["path"] in health:
            d["health"] = health[d["path"]]
        owner[d["path"]] = d["path"]
        for p in d["parts"]:
            owner[p["path"]] = d["path"]
    for i in items:
        disk = owner.get(i.get("device", ""))
        if disk in health:
            i["health"] = health[disk]
    return items


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


def lab():
    """The lab Field Kit knows: root's homelab.toml (from the stick's folder, or written here),
    its name and the services it names. None when there's none: no strip on Home."""
    from . import medium
    path = os.path.join(medium.ROOT_HOME, ".config", "bromigos", "homelab.toml")
    try:
        import tomllib
        with open(path, "rb") as f:
            doc = tomllib.load(f)
    except (OSError, ValueError):
        return None
    sources = [x for x in doc.get("source", []) if isinstance(x, dict) and x.get("enabled", True)]
    name = doc.get("name") if isinstance(doc.get("name"), str) and not doc["name"].startswith("@") else ""
    kinds = sorted({str(x.get("type", "")) for x in sources if x.get("type")})
    return {"name": name or "your lab", "sources": len(sources), "kinds": kinds[:6]}


def recent(limit=3):
    """Field Kit's last repairs on the opened install: its backups folder, newest first
    (<YYYYmmdd-HHMMSS>-<what>). Empty when no install is open or nothing was changed."""
    target = system.Target.load()
    if not target or target.is_live_root:
        return []
    d = target.path(system.BACKUPS)
    try:
        names = sorted((n for n in os.listdir(d) if re.match(r"\d{8}-\d{6}-", n)), reverse=True)
    except OSError:
        return []
    out = []
    for n in names[:limit]:
        stamp, what = n[:15], n[16:]
        when = f"{stamp[:4]}-{stamp[4:6]}-{stamp[6:8]} {stamp[9:11]}:{stamp[11:13]}"
        out.append({"when": when, "what": what.replace("-", " "), "backup": os.path.join(system.BACKUPS, n)})
    return out


def overview():
    from . import medium
    c = computer()
    items = found()
    try:
        disk_docs = disks()
    except system.Failed:
        disk_docs = []
    with_health(items, disk_docs, smart_health([d["path"] for d in disk_docs]))
    try:
        version = system.read("/version").strip() if os.path.exists("/run/archiso") else system.read("/usr/share/bromigos/fieldkit/version").strip()
    except OSError:
        version = ""
    st = medium.remote_state()
    ssh_on = system.run(["systemctl", "is-active", "--quiet", "sshd.service"], check=False).returncode == 0
    return {"ok": True, "version": version, "clock": time.strftime("%H:%M"), "network": network(),
            "ssh": {"on": ssh_on}, "remote": st, "stick": medium.stick_summary(), "live": system.live_medium(),
            "computer": c, "load": load(), "disks": disk_docs, "found": items, "suggestions": suggestions(items, c), "lab": lab(), "recent": recent()}


if __name__ == "__main__":
    print(json.dumps(overview(), indent=1))
