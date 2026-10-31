"""The checks behind `bromigos alerts` (docs/alerts.md), one function each, in REGISTRY.

Each takes a Context (bromigos_alerts) and returns alerts; it raises Skip when it doesn't apply
here and Failed when it couldn't look. Where bromigOS already knows the answer, the check asks
it instead of working it out again:

  update.waiting   `bromigos update --check --json`
  update.restart   core's reboot rules (core/crates/bromigos-core/src/reboot.rs), read the same way
  update.held      bromigos-server's own state (its Arch news hold)
  fieldkit.finding Field Kit's engine (`fieldkit-engine engine check …`) and the findings a
                   Field Kit stick saved in this install
  game.steam       `bromigos game check --json`
"""

import json
import os
import re

from bromigos_alerts import Failed, Skip, alert, evidence, slug

FIELDKIT_ENGINE = "/usr/lib/bromigos/fieldkit/fieldkit-engine"
FIELDKIT_FINDINGS = "/var/lib/bromigos/fieldkit/findings.json"
SERVER_STATE = "/var/lib/bromigos/server/update.json"
BACKUP_STATUS = "/var/lib/bromigos/backup/status.json"
DAY = 86400_000


class Check:
    def __init__(self, name, passes, fn, boot_only=False):
        self.name, self.passes, self.fn, self.boot_only = name, set(passes), fn, boot_only


def size(n):
    n = float(n)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1000 or unit == "TB":
            return f"{n:.0f} {unit}" if unit in ("B", "KB") or n >= 100 else f"{n:.1f} {unit}"
        n /= 1000
    return f"{n:.0f} TB"


def lines(text, n=30):
    return [x for x in (text or "").splitlines() if x.strip()][-n:]


# ------------------------------------------------------------------ mounts

REAL_FS = {"ext2", "ext3", "ext4", "btrfs", "xfs", "f2fs", "vfat", "exfat", "ntfs3", "ntfs", "zfs", "bcachefs",
           "jfs", "reiserfs"}
NOT_THERE = ("/proc", "/sys", "/dev", "/run", "/snap", "/var/lib/docker", "/var/lib/containers", "/.snapshots")


def unescape(s):
    return re.sub(r"\\([0-7]{3})", lambda m: chr(int(m.group(1), 8)), s)


def mounts(env, fstypes=REAL_FS):
    """[(device, mountpoint, fstype)] of real, writable filesystems; one per device (btrfs
    subvolumes of one filesystem share its space: the shortest mount point stands for it)."""
    text = env.read("/proc/self/mounts") or ""
    best = {}
    for line in text.splitlines():
        parts = line.split()
        if len(parts) < 4:
            continue
        dev, mnt, fs, opts = unescape(parts[0]), unescape(parts[1]), parts[2], parts[3].split(",")
        if fs not in fstypes or "ro" in opts:
            continue
        if any(mnt == p or mnt.startswith(p + "/") for p in NOT_THERE) or "/.snapshots/" in mnt:
            continue
        if dev not in best or len(mnt) < len(best[dev][1]):
            best[dev] = (dev, mnt, fs)
    return sorted(best.values(), key=lambda m: m[1])


# ------------------------------------------------------------------ disk.smart

def smart(ctx):
    env = ctx.env
    rc, out, err = env.run(["smartctl", "--scan", "-j"], timeout=30)
    if rc == 127:
        raise Skip("smartmontools isn't installed")
    try:
        devices = json.loads(out).get("devices") or []
    except ValueError:
        raise Failed("smartctl --scan gave no answer: " + (err.strip() or "?")[:200])
    found = []
    for d in devices:
        dev = d.get("name")
        if not dev or dev.startswith(("/dev/loop", "/dev/zram", "/dev/sr")):
            continue
        argv = ["smartctl", "-j", "-H", "-A", "-i"] + (["-d", d["type"]] if d.get("type") else []) + [dev]
        rc, out, _ = env.run(argv, timeout=60)
        if rc & 0b11:           # the command line, or opening the device, failed
            continue
        try:
            r = json.loads(out)
        except ValueError:
            continue
        name = os.path.basename(dev)
        model = r.get("model_name") or r.get("model_family") or "a drive"
        serial = str(r.get("serial_number") or "")
        what = f"{model} ({name})"
        ev = [f"Drive: {model}, {dev}"]
        severity, why = None, []
        passed = (r.get("smart_status") or {}).get("passed")
        if passed is False or rc & 0b1000:
            severity = "critical"
            why.append("its own health check says FAILED")
            ev.append("SMART overall-health self-assessment test result: FAILED")
        elif passed is True:
            ev.append("SMART overall-health self-assessment test result: PASSED")
        nvme = r.get("nvme_smart_health_information_log") or {}
        if nvme:
            cw = int(nvme.get("critical_warning") or 0)
            used = int(nvme.get("percentage_used") or 0)
            media = int(nvme.get("media_errors") or 0)
            ev += [f"Critical Warning: 0x{cw:02x}", f"Percentage Used: {used}%", f"Media and Data Integrity Errors: {media}",
                   f"Temperature: {nvme.get('temperature', '?')} Celsius"]
            if cw:
                severity = "critical"
                why.append(f"it raised a critical warning (0x{cw:02x})")
            if media:
                severity = severity or "needs_you"
                why.append(f"{media} media error{'s' if media != 1 else ''}")
            if used >= 90:
                severity = severity or "needs_you"
                why.append(f"{used}% of its rated life is used")
        for row in (r.get("ata_smart_attributes") or {}).get("table") or []:
            key = row.get("name")
            raw = int(((row.get("raw") or {}).get("value")) or 0)
            if key in ("Reallocated_Sector_Ct", "Current_Pending_Sector", "Offline_Uncorrectable",
                       "Reported_Uncorrect"):
                ev.append(f"{key}: {raw}")
                if raw > 0:
                    severity = severity or "needs_you"
                    why.append({"Reallocated_Sector_Ct": f"{raw} reallocated sector{'s' if raw != 1 else ''}",
                                "Current_Pending_Sector": f"{raw} sector{'s' if raw != 1 else ''} it can't read",
                                "Offline_Uncorrectable": f"{raw} uncorrectable sector{'s' if raw != 1 else ''}",
                                "Reported_Uncorrect": f"{raw} uncorrectable error{'s' if raw != 1 else ''}"}[key])
            if row.get("when_failed") in ("now", "past"):
                severity = severity or "needs_you"
                why.append(f"{key} passed its failure threshold")
        if not severity:
            continue
        fix = {"commands": [f"sudo smartctl -a {dev}", f"sudo smartctl -t short {dev}"],
               "touches": ["nothing (it reads the drive's records and runs its own 2-minute self-test)"],
               "from": "bromigos", "root": True,
               "note": "Back up first: Field Kit's Back up my files copies every home folder to a USB drive."}
        if severity == "critical":
            title = f"A drive is failing: {what}"
            detail = (f"{what[0].upper() + what[1:]}: " + "; ".join(why) + ". Copy your files off it now, then replace it.")
        else:
            title = f"A drive is wearing out: {what}"
            detail = (f"{what[0].upper() + what[1:]}: " + "; ".join(why)
                      + ". It still works, but these numbers only grow: back up what's on it and plan to replace it.")
        found.append(alert("disk.smart", name, severity, title, detail, "SMART",
                           evidence=evidence(ev, model=model, device=dev, serial_tail=serial[-4:],
                                             firmware=r.get("firmware_version") or ""),
                           fix=fix))
    return found


# ------------------------------------------------------------------ disk.scrub

SCRUB_KEYS = ("read_errors", "csum_errors", "verify_errors", "super_errors", "uncorrectable_errors",
              "corrected_errors", "unverified_errors")


def scrub(ctx):
    env = ctx.env
    fs = mounts(env, {"btrfs"})
    if not fs:
        raise Skip("no btrfs filesystem here")
    if not env.find("btrfs"):
        raise Skip("btrfs-progs isn't installed")
    found = []
    for dev, mnt, _ in fs:
        rc, out, err = env.run(["btrfs", "scrub", "status", "-R", mnt], timeout=30)
        if rc != 0:
            raise Failed(f"btrfs scrub status {mnt}: " + (err.strip() or "failed")[:200])
        counts = {k: int(v) for k, v in re.findall(r"^\s*(\w+):\s*(\d+)\s*$", out, re.M) if k in SCRUB_KEYS}
        status = (re.search(r"^Status:\s*(.+)$", out, re.M) or [None, "never"])[1].strip()
        started = (re.search(r"^Scrub started:\s*(.+)$", out, re.M) or [None, ""])[1].strip()
        rc2, stats, _ = env.run(["btrfs", "device", "stats", mnt], timeout=30)
        dev_errs = [(m.group(1), m.group(2), int(m.group(3)))
                    for m in re.finditer(r"^\[([^\]]+)\]\.(\w+)\s+(\d+)$", stats if rc2 in (0, 64) else "", re.M)
                    if int(m.group(3)) > 0]
        bad = {k: v for k, v in counts.items() if v and k != "unverified_errors"}
        if not bad and not dev_errs:
            continue
        unc = counts.get("uncorrectable_errors", 0)
        ev = [f"Scrub started: {started}", f"Status: {status}"] + [f"{k}: {v}" for k, v in counts.items()]
        ev += [f"[{d}].{k}  {v}" for d, k, v in dev_errs]
        what = "the system drive" if mnt == "/" else mnt
        if unc:
            sev, title = "critical", f"btrfs found damaged data it can't repair on {what}"
            detail = (f"The last check of {mnt} found {unc} block{'s' if unc != 1 else ''} whose data no longer matches "
                      f"what was written, and there's no good copy to repair {'it' if unc == 1 else 'them'} from. Copy your files off first "
                      "(Field Kit's Back up my files), then ask before repairing.")
        elif bad:
            n = sum(bad.values())
            sev, title = "needs_you", f"btrfs found and fixed errors on {what}"
            detail = (f"The last check of {mnt} found {n} error{'s' if n != 1 else ''} "
                      f"({', '.join(k.replace('_', ' ') for k in bad)}). "
                      "It had a good copy this time, but errors usually mean a drive or its cable is going: "
                      "look at the drive's health and back up.")
        else:
            n = sum(v for *_, v in dev_errs)
            sev, title = "needs_you", f"btrfs counted errors on {what}"
            detail = (f"The drive under {mnt} had {n} read, write or checksum error{'s' if n != 1 else ''} "
                      f"({', '.join(sorted({k.replace('_', ' ') for _, k, _ in dev_errs}))}). "
                      "A full check (a scrub) shows whether any data is damaged.")
        fix = {"commands": [f"sudo btrfs scrub start -B -r {mnt}", f"sudo btrfs device stats {mnt}"],
               "touches": ["nothing (read-only)"], "from": "fieldkit", "root": True,
               "note": "Field Kit's own check: reads every block and checks its checksum, repairs nothing. "
                       "Once the cause is fixed, `sudo btrfs device stats -z` sets the counters back to zero."}
        found.append(alert("disk.scrub", mnt, sev, title, detail, "btrfs",
                           evidence=evidence(ev, mount=mnt, device=dev, status=status), fix=fix))
    return found


# ------------------------------------------------------------------ disk.full

def full(ctx):
    env, conf = ctx.env, ctx.settings["disk"]
    warn, crit = float(conf.get("full_percent", 90)), float(conf.get("critical_percent", 97))
    ignore = set(conf.get("ignore") or [])
    fs = [m for m in mounts(env) if m[1] not in ignore]
    if ctx.scope == "user":
        # yours: the filesystem your home is on
        home = os.path.realpath(env.home)
        mine = [m for m in fs if home == m[1] or home.startswith(m[1].rstrip("/") + "/")]
        fs = sorted(mine, key=lambda m: len(m[1]))[-1:]
    prev = ctx.previous("disk.full")
    found = []
    for dev, mnt, fstype in fs:
        try:
            total, free, avail = env.statvfs(mnt)
        except OSError:
            continue
        used = total - free
        if total <= 0 or used + avail <= 0:
            continue
        pct = 100.0 * used / (used + avail)
        aid = f"disk.full:{mnt}"
        # a little hysteresis: one that was full stays raised until it's 2 points under
        limit = warn - 2 if aid in prev else warn
        if pct < limit:
            continue
        sev = "critical" if pct >= crit else "needs_you"
        what = {"/": "The system drive", "/home": "Your home drive", "/boot": "The boot partition"}.get(mnt, mnt)
        title = f"{what} is {pct:.0f}% full" + (f" ({mnt})" if what != mnt and mnt not in ("/",) else "")
        if mnt == "/boot":
            why = "When it's full, a kernel update can't be written and the next start may fail."
            commands = ["ls -la /boot", "pacman -Qo /boot/*"]
        else:
            why = ("When it fills, programs can't save, the desktop misbehaves and updates fail."
                   if pct < crit else "It's nearly out of room: programs and updates are about to fail.")
            commands = ["bromigos storage cleanup --preview", f"du -xh --max-depth=1 {mnt} 2>/dev/null | sort -h | tail -15"]
        detail = (f"{size(avail)} free of {size(total)} on {mnt}. {why} "
                  "bromigos storage cleanup --preview shows what can go, nothing is removed until you choose.")
        found.append(alert("disk.full", mnt, sev, title, detail, "Disk space",
                           evidence=evidence([f"{mnt} ({fstype} on {dev}): {pct:.1f}% used, {size(avail)} available "
                                              f"of {size(total)}"], mount=mnt, fstype=fstype, percent=f"{pct:.1f}",
                                             available=size(avail), total=size(total)),
                           fix={"commands": commands, "touches": ["nothing (it only looks)"], "from": "bromigos",
                                "root": False, "note": "Shows what takes the room; removing anything is your choice."}))
    return found


# ------------------------------------------------------------------ update.waiting

def last_upgrade_ms(env):
    """When pacman last finished a full system upgrade (pacman.log), in ms, or None."""
    import datetime
    text = env.read("/var/log/pacman.log") or ""
    when = None
    upgrading = False
    for line in text.splitlines():
        if "starting full system upgrade" in line:
            upgrading = True
        elif upgrading and "transaction completed" in line:
            m = re.match(r"\[([^\]]+)\]", line)
            if m:
                try:
                    when = int(datetime.datetime.fromisoformat(m.group(1).replace("Z", "+00:00")).timestamp() * 1000)
                except ValueError:
                    pass
            upgrading = False
    return when


def waiting(ctx):
    env = ctx.env
    rc, out, err = env.run(["bromigos", "update", "--check", "--json"], timeout=240)
    if rc == 127:
        raise Skip("bromigos isn't installed")
    try:
        c = json.loads(out.strip().splitlines()[-1]).get("check") or {}
    except (ValueError, IndexError, AttributeError):
        raise Failed("bromigos update --check gave no answer: " + (err.strip().splitlines() or ["?"])[-1][:200])
    pkgs = c.get("packages")
    if pkgs is None:
        raise Failed("can't tell what's waiting (checkupdates, from pacman-contrib, isn't installed or failed)")
    aur = ((c.get("aur") or {}).get("packages")) or []
    n = len(pkgs) + len(aur)
    if not n:
        return []
    last = last_upgrade_ms(env)
    days = (env.now_ms() - last) // DAY if last else None
    sev = "needs_you" if days is not None and days >= 30 else "info"
    names = [p.get("name", "?") for p in (pkgs + aur)]
    title = f"{n} update{'s' if n != 1 else ''} waiting"
    detail = (f"{', '.join(names[:5])}{' and more' if n > 5 else ''}. "
              + (f"Nothing was updated for {days} days. " if days is not None and days >= 30 else "")
              + "bromigos update installs them, with a snapshot first so you can roll back.")
    kernel = any(x in ("linux", "linux-lts", "linux-zen", "linux-hardened") or x.startswith("nvidia") for x in names)
    return [alert("update.waiting", "", sev, title, detail, "Updates",
                  actions=[{"kind": "update", "label": "Update now"}, {"kind": "snooze"}, {"kind": "open"}],
                  evidence=evidence([f"{p.get('name')} {p.get('from')} -> {p.get('to')}" for p in pkgs + aur],
                                    packages=n, aur=len(aur), days_since_update=days if days is not None else "?",
                                    kernel_or_driver="yes" if kernel else "no"),
                  fix={"commands": ["bromigos update"], "touches": ["the installed packages (a snapshot pair around it)"],
                       "from": "bromigos", "root": False, "note": "Asks for your password for the packages step."})]


# ------------------------------------------------------------------ update.restart (core's reboot.rs, read the same way)

LIB_DIRS = ("/usr/lib", "/usr/lib64", "/usr/lib/x86_64-linux-gnu")
NVIDIA_LIBS = ("libEGL_nvidia.so.", "libGLX_nvidia.so.", "libnvidia-glcore.so.")
VERSION = re.compile(r"^\d+(\.\d+)+$")


def _ver_key(v):
    return [int(p) for p in v.split(".")]


def restart_pending(env):
    """(kernel, driver): what runs older than what's installed, as core's reboot.rs decides."""
    kernel = driver = None
    running = (env.read("/proc/sys/kernel/osrelease") or "").strip()
    installed = [r for r in env.listdir("/usr/lib/modules")
                 if env.exists(f"/usr/lib/modules/{r}/vmlinuz") or env.exists(f"/usr/lib/modules/{r}/kernel")]
    if running and installed and running not in installed:
        kernel = {"running": running, "installed": installed}
    module = (env.read("/sys/module/nvidia/version") or "").strip()
    if module:
        libs = {n[len(p):] for d in LIB_DIRS for n in env.listdir(d) for p in NVIDIA_LIBS
                if n.startswith(p) and VERSION.match(n[len(p):])}
        if libs and module not in libs:
            driver = {"running": module, "installed": max(libs, key=_ver_key)}
    return kernel, driver


def restart(ctx):
    kernel, driver = restart_pending(ctx.env)
    if not kernel and not driver:
        return []
    if kernel and driver:
        title, what = "Restart to finish the update: a new kernel and graphics driver", "The kernel and the graphics driver were updated"
    elif kernel:
        title, what = "Restart to finish the update: a new kernel", "The kernel was updated"
    else:
        title, what = "Restart to finish the update: a new graphics driver", "The graphics driver was updated"
    detail = (f"{what}: restart the computer to use {'them' if kernel and driver else 'it'}. Until then, a module that "
              "isn't loaded yet can't load" + (" and new programs can't use the graphics card" if driver else "") + ".")
    ev, facts = [], {}
    if kernel:
        ev.append(f"running kernel {kernel['running']}; installed: {', '.join(kernel['installed'])}")
        facts.update(kernel_running=kernel["running"], kernel_installed=", ".join(kernel["installed"]))
    if driver:
        ev.append(f"NVIDIA module {driver['running']} loaded; libraries {driver['installed']} installed")
        facts.update(driver_running=driver["running"], driver_installed=driver["installed"])
    return [alert("update.restart", "", "needs_you", title, detail, "Updates",
                  actions=[{"kind": "restart", "label": "Restart now"}, {"kind": "snooze"}, {"kind": "open"}],
                  evidence=evidence(ev, **facts))]


# ------------------------------------------------------------------ update.held (bromigos-server's Arch news hold)

def held(ctx):
    if ctx.role != "server":
        raise Skip("only bromigOS Server updates by itself")
    raw = ctx.env.read(SERVER_STATE)
    st = {}
    if raw:
        try:
            st = json.loads(raw)
        except ValueError:
            raise Failed(f"{SERVER_STATE} can't be read")
    found = []
    hold = st.get("hold")
    if hold:
        items = hold.get("items") or [hold]
        first = items[0]
        n = len(items)
        title = "An update is waiting for you: Arch Linux news asks for manual steps"
        detail = (f"The automatic update stopped before it started, because Arch Linux posted "
                  f"{'news' if n == 1 else f'{n} news items'} since the last update: \"{first.get('title', '?')}\". "
                  "Read it; once anything it asks is done, update (BRODEC's Update, or "
                  "`sudo bromigos server update --now`).")
        found.append(alert("update.held", "", "needs_you", title, detail, "Arch news",
                           actions=[{"kind": "link", "label": "Read the news", "url": first.get("link", "")},
                                    {"kind": "fix", "label": "Ask VECTOR"}, {"kind": "update", "label": "Update now"},
                                    {"kind": "snooze"}],
                           evidence=evidence([f"{i.get('published', '')}  {i.get('title', '')}  {i.get('link', '')}"
                                              for i in items], held_at=hold.get("since", ""), items=n),
                           fix={"commands": ["sudo bromigos server update --now"],
                                "touches": ["the installed packages (a snapshot pair around it, then the health check)"],
                                "from": "bromigos", "root": True,
                                "note": "Only after doing what the news item asks."},
                           link=first.get("link")))
    if st.get("phase") in ("rolled-back", "attention", "failed"):
        words = {"rolled-back": "The last automatic update was rolled back",
                 "attention": "An update and its rollback both failed the health check",
                 "failed": "The last automatic update didn't finish"}[st["phase"]]
        found.append(alert("update.held", "server-update", "critical" if st["phase"] == "attention" else "needs_you",
                           words, f"{words}: {st.get('reason') or 'see the server log'}. "
                           "`bromigos server status` says where it stands.", "Updates",
                           evidence=evidence([f"phase: {st.get('phase')}", f"reason: {st.get('reason', '')}",
                                              f"started: {st.get('started', '')}", f"finished: {st.get('finished', '')}"],
                                             pre=st.get("pre", ""), post=st.get("post", "")),
                           fix={"commands": ["bromigos server status", "journalctl -u bromigos-server-update.service -b -n 50",
                                             "journalctl -u bromigos-server-health.service -b -n 50"],
                                "touches": ["nothing (it only looks)"], "from": "bromigos", "root": False, "note": ""}))
    return found


# ------------------------------------------------------------------ backup.restic

def _show(env, unit, props, user=False):
    rc, out, _ = env.run(["systemctl", *(["--user"] if user else []), "show", unit, "--no-pager", "--timestamp=unix",
                          *[f"--property={p}" for p in props]], timeout=15)
    return dict(line.split("=", 1) for line in out.splitlines() if "=" in line) if rc == 0 else {}


def _stamp_ms(stamp):
    """`systemctl show --timestamp=unix`'s "@1793390000" (or nothing), in ms."""
    m = re.match(r"@(\d+)", (stamp or "").strip())
    return int(m.group(1)) * 1000 if m else 0


def journal_tail(env, unit, n=30, user=False):
    rc, out, _ = env.run(["journalctl", "--user-unit" if user else "-u", unit, "-n", str(n), "--no-pager",
                          "-o", "short-iso", "-b", "-q"], timeout=20)
    if rc != 0 or not out.strip():
        rc, out, _ = env.run(["journalctl", "--user-unit" if user else "-u", unit, "-n", str(n), "--no-pager",
                              "-o", "short-iso", "-q"], timeout=20)
    return lines(out, n)


def backup(ctx):
    env = ctx.env
    now = env.now_ms()
    found = []
    # bromigOS Server's own backups write a status file (docs/server.md): read it when it's there
    raw = env.read(BACKUP_STATUS)
    if raw:
        try:
            st = json.loads(raw)
        except ValueError:
            st = {}
        last_ok = int(st.get("last_success") or 0)
        if st.get("last_error"):
            found.append(alert("backup.restic", "bromigos", "needs_you", "The last backup failed",
                               f"{st['last_error'][:300]}. Your files weren't copied this time.", "restic",
                               evidence=evidence([str(st.get("last_error"))], last_success=last_ok)))
        elif last_ok and now - last_ok > 36 * 3600_000:
            found.append(alert("backup.restic", "bromigos", "needs_you", "No backup for over a day and a half",
                               f"The last good backup was {(now - last_ok) // 3600_000} hours ago.", "restic",
                               evidence=evidence([], last_success=last_ok)))
    rc, out, _ = env.run(["systemctl", "list-units", "--all", "--plain", "--no-legend", "--no-pager", "--type=service",
                          "restic*", "bromigos-backup*"], timeout=15)
    if rc == 127 and not raw:
        raise Skip("no systemd here")
    units = sorted({line.split()[0] for line in out.splitlines() if line.strip() and line.split()[0].endswith(".service")})
    if not units and not raw:
        raise Skip("no restic backups are set up here")
    for unit in units:
        p = _show(env, unit, ["ActiveState", "Result", "ExecMainStatus", "ExecMainExitTimestamp", "Description",
                              "TriggeredBy"])
        name = unit.removesuffix(".service")
        timer = p.get("TriggeredBy", "").split()
        if p.get("ActiveState") == "failed" or p.get("Result") not in (None, "", "success"):
            fix = {"commands": [f"journalctl -u {unit} -n 50 --no-pager", f"sudo systemctl start {unit}"],
                   "touches": [f"runs {unit} again (a backup)"], "from": "bromigos", "root": True,
                   "note": "Read why it failed first: a full disk, a lost network share or a wrong password are common."}
            found.append(alert("backup.restic", name, "needs_you", f"The last backup failed: {name}",
                               f"{p.get('Description') or unit} ended with {p.get('Result') or 'an error'} "
                               f"(exit status {p.get('ExecMainStatus') or '?'}). Your files weren't copied this time.",
                               "restic", evidence=evidence(journal_tail(env, unit), unit=unit,
                                                           result=p.get("Result", ""), status=p.get("ExecMainStatus", "")),
                               fix=fix))
            continue
        if timer:
            # scheduled: one that hasn't succeeded for 36 h is late. systemd keeps the last exit
            # only since this boot; a persistent timer keeps when it last fired
            tp = _show(env, timer[0], ["LastTriggerUSec", "ActiveState"])
            if tp.get("ActiveState") != "active":
                continue
            last_ms = _stamp_ms(p.get("ExecMainExitTimestamp")) or _stamp_ms(tp.get("LastTriggerUSec"))
            if last_ms and now - last_ms > 36 * 3600_000:
                hours = (now - last_ms) // 3600_000
                found.append(alert("backup.restic", name, "needs_you", f"No backup for {hours} hours: {name}",
                                   f"{timer[0]} is set up, but {unit} hasn't finished a backup for {hours} hours: "
                                   "the computer may have been off or asleep when it was due, or it's stuck.",
                                   "restic", evidence=evidence(journal_tail(env, unit), unit=unit, timer=timer[0]),
                                   fix={"commands": [f"systemctl list-timers {timer[0]}", f"sudo systemctl start {unit}"],
                                        "touches": [f"runs {unit} now (a backup)"], "from": "bromigos", "root": True,
                                        "note": ""}))
    return found


# ------------------------------------------------------------------ power.ups

def ups(ctx):
    env = ctx.env
    rc, out, err = env.run(["upsc", "-l"], timeout=15)
    if rc == 127:
        raise Skip("NUT isn't installed (no UPS set up)")
    names = [x.strip() for x in out.splitlines() if x.strip()]
    if rc != 0 and not names:
        if "Connection refused" in err or "not running" in err.lower():
            raise Skip("no UPS is set up (NUT's server isn't running)")
        raise Failed("upsc: " + (err.strip() or "no answer")[:200])
    found = []
    for name in names:
        rc, out, _ = env.run(["upsc", f"{name}@localhost"], timeout=15)
        if rc != 0:
            continue
        v = dict((k.strip(), x.strip()) for k, x in (line.split(":", 1) for line in out.splitlines() if ":" in line))
        status = v.get("ups.status", "").split()
        charge, runtime = v.get("battery.charge", "?"), v.get("battery.runtime")
        left = f", about {int(float(runtime)) // 60} min left" if runtime and runtime.replace(".", "").isdigit() else ""
        if "LB" in status:
            sev, title = "critical", f"The UPS battery is low: {name}"
            detail = (f"The power is out and the battery is at {charge}%{left}. This computer shuts down soon "
                      "to keep its disks safe; save your work now.")
        elif "OB" in status:
            sev, title = "needs_you", f"Running on the UPS battery: {name}"
            detail = f"The power went out. The battery is at {charge}%{left}."
        elif "RB" in status:
            sev, title = "needs_you", f"The UPS battery needs replacing: {name}"
            detail = "The UPS says its battery should be replaced: it may not hold when the power goes."
        else:
            continue
        found.append(alert("power.ups", name, sev, title, detail, "UPS",
                           actions=[{"kind": "snooze"}, {"kind": "open"}, {"kind": "fix", "label": "Fix it"}],
                           evidence=evidence([f"{k}: {x}" for k, x in v.items() if k.startswith(("ups.", "battery.", "input."))],
                                             status=" ".join(status), charge=charge, runtime=runtime or "?")))
    return found


# ------------------------------------------------------------------ systemd.failed

NEVER_MATTERS = re.compile(r"(-wait-online\.service|^run-|^session-|\.scope$|^user@|^user-runtime-dir@|^systemd-coredump@|"
                           r"^systemd-fsck@|^dbus-|^app-.*\.service$|^plymouth-)")
CRITICAL_ON_SERVER = {"sshd.service", "bromigos-server-firewall.service", "NetworkManager.service"}


def failed_units(ctx):
    env, user = ctx.env, ctx.scope == "user"
    rc, out, err = env.run(["systemctl", *(["--user"] if user else []), "list-units", "--state=failed", "--plain",
                            "--no-legend", "--no-pager"], timeout=20)
    if rc == 127:
        raise Skip("no systemd here")
    if rc != 0:
        raise Failed("systemctl: " + (err.strip() or "no answer")[:200])
    ignore = set(ctx.settings["units"].get("ignore") or [])
    found = []
    for line in out.splitlines():
        if not line.strip():
            continue
        unit = line.split()[0].lstrip("●").strip()
        if unit in ignore or NEVER_MATTERS.search(unit):
            continue
        p = _show(env, unit, ["Transient", "UnitFileState", "Description", "Result", "ActiveEnterTimestamp",
                              "InactiveEnterTimestamp"], user)
        if p.get("Transient") == "yes":
            continue
        if p.get("UnitFileState") in ("masked", "masked-runtime", "transient", "bad"):
            continue
        desc = p.get("Description") or unit
        rc, st, _ = env.run(["systemctl", *(["--user"] if user else []), "status", unit, "--no-pager", "-n", "0",
                             "--lines=0"], timeout=15)
        status_lines = [x.rstrip() for x in st.splitlines() if x.strip()][:8]
        sev = "critical" if ctx.role == "server" and unit in CRITICAL_ON_SERVER else "needs_you"
        sudo = "" if user else "sudo "
        u = "--user " if user else ""
        detail = (f"{desc} ({unit}) stopped with {p.get('Result') or 'an error'}"
                  f"{' and the server may be unreachable' if sev == 'critical' else ''}. "
                  "Its last log lines say why; starting it again is often enough once the cause is fixed.")
        found.append(alert("systemd.failed", unit, sev, f"{'One of your services' if user else 'A service'} failed: {desc}", detail, "systemd",
                           actions=[{"kind": "fix", "label": "Fix it"},
                                    {"kind": "run", "label": "Start it again", "command": f"{sudo}systemctl {u}restart {unit}"},
                                    {"kind": "snooze"}, {"kind": "open"}],
                           evidence=evidence(status_lines + journal_tail(env, unit, 30, user), unit=unit,
                                             result=p.get("Result", ""), unit_file=p.get("UnitFileState", ""),
                                             scope="user" if user else "system"),
                           fix={"commands": [f"systemctl {u}status {unit} --no-pager",
                                             f"journalctl {'--user-unit' if user else '-u'} {unit} -b -n 50 --no-pager",
                                             f"{sudo}systemctl {u}restart {unit}"],
                                "touches": [f"restarts {unit}"], "from": "bromigos", "root": not user, "note": ""}))
    return found


# ------------------------------------------------------------------ server.game

def game_server(ctx):
    if ctx.role != "server":
        raise Skip("game servers are a bromigOS Server role")
    env = ctx.env
    found = []
    for unit in ctx.settings["game"].get("units") or []:
        unit = unit if "." in unit else unit + ".service"
        p = _show(env, unit, ["ActiveState", "SubState", "Description", "Result"])
        if not p:
            continue
        if p.get("ActiveState") in ("active", "reloading", "activating"):
            continue
        name = (p.get("Description") or unit)
        found.append(alert("server.game", unit.removesuffix(".service"), "needs_you", f"A game server is down: {name}",
                           f"{name} ({unit}) is {p.get('ActiveState', 'stopped')}"
                           f"{' (' + p['Result'] + ')' if p.get('Result') not in (None, '', 'success') else ''}: "
                           "nobody can join until it runs again.", "Game server",
                           actions=[{"kind": "run", "label": "Start it", "command": f"sudo systemctl restart {unit}"},
                                    {"kind": "fix", "label": "Fix it"}, {"kind": "snooze"}, {"kind": "open"}],
                           evidence=evidence(journal_tail(env, unit), unit=unit, state=p.get("ActiveState", "")),
                           fix={"commands": [f"journalctl -u {unit} -n 50 --no-pager", f"sudo systemctl restart {unit}"],
                                "touches": [f"restarts {unit}"], "from": "bromigos", "root": True, "note": ""}))
    # containers marked as game servers (org.bromigos.game)
    rc, out, _ = env.run(["podman", "ps", "-a", "--format", "json", "--filter", "label=org.bromigos.game"], timeout=20)
    if rc == 0:
        try:
            rows = json.loads(out or "[]")
        except ValueError:
            rows = []
        for c in rows:
            names = c.get("Names") or [c.get("Id", "?")[:12]]
            name = names[0] if isinstance(names, list) else str(names)
            if c.get("State") == "running":
                continue
            label = (c.get("Labels") or {}).get("org.bromigos.game") or name
            found.append(alert("server.game", f"container-{name}", "needs_you", f"A game server is down: {label}",
                               f"Its container {name} is {c.get('State', 'stopped')} ({c.get('Status', '')}): "
                               "nobody can join until it runs again.", "Game server",
                               actions=[{"kind": "run", "label": "Start it", "command": f"sudo podman start {name}"},
                                        {"kind": "fix", "label": "Fix it"}, {"kind": "snooze"}, {"kind": "open"}],
                               evidence=evidence([f"{name}: {c.get('State')} {c.get('Status', '')}"],
                                                 container=name, image=c.get("Image", "")),
                               fix={"commands": [f"sudo podman logs --tail 50 {name}", f"sudo podman start {name}"],
                                    "touches": [f"starts the container {name}"], "from": "bromigos", "root": True,
                                    "note": ""}))
    return found


# ------------------------------------------------------------------ fieldkit.finding

def _engine(env):
    p = env.environ.get("BROMIGOS_FIELDKIT_ENGINE") or env.path(FIELDKIT_ENGINE)
    return p if os.path.isfile(p) and os.access(p, os.X_OK) else None


def _finding_alert(check, f, saved_at=None):
    words = {"black-screen": "the black screen check", "last-boot": "the last boot check"}.get(check, check)
    title = f.get("title") or "?"
    detail = (f.get("detail") or "").strip()
    if saved_at:
        detail = (f"Field Kit found this when it looked at this install from the stick ({words}). " + detail).strip()
    else:
        detail = (f"Field Kit's {words} found this on this computer. " + detail).strip()
    commands = list(f.get("commands") or [])
    fix = {"commands": commands, "touches": list(f.get("touches") or []), "from": "fieldkit", "root": True,
           "note": f.get("fix") or ""} if commands else None
    return alert("fieldkit.finding", f"{check}:{slug(re.sub(r'[0-9]+', ' ', title))}", "needs_you", title, detail,
                 "Field Kit", evidence=evidence(f.get("lines") or [detail[:280]], check=check,
                                                saved_by_stick="yes" if saved_at else "no",
                                                fix=f.get("fix") or ""), fix=fix)


def fieldkit(ctx):
    """At boot: the findings a Field Kit stick saved in this install, and Field Kit's own checks
    on the running system. A saved check whose live re-check worked is replaced by it (and taken
    out of the file): a finding that was repaired is gone, one that wasn't stays raised."""
    env = ctx.env
    raw = env.read(FIELDKIT_FINDINGS)
    saved = {}
    if raw:
        try:
            saved = (json.loads(raw).get("checks") or {})
        except ValueError:
            saved = {}
    engine = _engine(env)
    if not engine and not saved:
        raise Skip("Field Kit's engine isn't installed (bromigos-fieldkit-tools)")
    found, cleared = [], []
    for check in ["black-screen"] + [c for c in saved if c != "black-screen"]:
        live = None
        if engine:
            rc, out, _ = env.run([engine, "engine", "check", check], timeout=120)
            try:
                doc = json.loads([x for x in out.splitlines() if x.lstrip().startswith("{")][-1])
                live = doc.get("findings") if doc.get("ok") else None
            except (ValueError, IndexError):
                live = None
        if live is not None:
            found += [_finding_alert(check, f) for f in live if not f.get("ok")]
            if check in saved:
                cleared.append(check)
        elif check in saved:
            entry = saved[check] or {}
            found += [_finding_alert(check, f, entry.get("saved_at")) for f in entry.get("findings") or []
                      if not f.get("ok")]
    if cleared:
        left = {k: v for k, v in saved.items() if k not in cleared}
        path = env.path(FIELDKIT_FINDINGS)
        try:
            if left:
                from bromigos_alerts import write_json
                write_json(path, {"schema": 1, "checks": left})
            else:
                os.unlink(path)
        except OSError:
            pass
    return found


# ------------------------------------------------------------------ game.steam

def steam(ctx):
    env = ctx.env
    exe = env.find("bromigos-game-check")
    if not exe:
        raise Skip("the games tools aren't installed (bromigos-desktop)")
    rc, out, err = env.run([exe, "--json"], timeout=120)
    try:
        doc = json.loads([x for x in out.splitlines() if x.lstrip().startswith("{")][-1])
    except (ValueError, IndexError):
        raise Failed("bromigos game check gave no answer: " + (err.strip().splitlines() or ["?"])[-1][:200])
    if not doc.get("steam_root"):
        raise Skip("Steam isn't set up for you")
    found, used = [], {}
    for f in doc.get("findings") or []:
        level = f.get("level")
        if level not in ("warn", "problem"):
            continue
        check = f.get("check") or "steam"
        used[check] = used.get(check, 0) + 1
        subject = check if used[check] == 1 else f"{check}-{used[check]}"
        auto = bool(f.get("auto"))
        sev = "needs_you" if level == "problem" and not auto else "info"
        detail = " ".join(x for x in (f.get("detail"), f.get("fix")) if x)
        if auto:
            detail += " bromigOS fixes this by itself the next time Steam closes."
        commands = ["bromigos game check --fix"] if f.get("fixable") else []
        found.append(alert("game.steam", subject, sev, f.get("title") or "Steam needs a look", detail.strip(), "Steam",
                           evidence=evidence([f.get("title", ""), f.get("detail", ""), f.get("fix", "")], check=check,
                                             level=level, auto="yes" if auto else "no", fixable=f.get("fixable") or ""),
                           fix={"commands": commands, "touches": ["Steam's config (a backup is kept)"],
                                "from": "game check", "root": f.get("fixable") == "sddm",
                                "note": "Steam must be closed."} if commands else None))
    return found


REGISTRY = [
    Check("disk.smart", ["system"], smart),
    Check("disk.scrub", ["system"], scrub),
    Check("disk.full", ["system", "user"], full),
    Check("update.waiting", ["user"], waiting),
    Check("update.restart", ["system"], restart),
    Check("update.held", ["system"], held),
    Check("backup.restic", ["system"], backup),
    Check("power.ups", ["system"], ups),
    Check("systemd.failed", ["system", "user"], failed_units),
    Check("server.game", ["system"], game_server),
    Check("fieldkit.finding", ["system"], fieldkit, boot_only=True),
    Check("game.steam", ["user"], steam),
]
