"""A stand-in machine for `bromigos alerts`' tests: a root folder with /proc, /sys and /var, and
stand-in commands on PATH (smartctl, btrfs, upsc, systemctl, journalctl, podman, bromigos,
bromigos-game-check, notify-send and Field Kit's engine), each answering from files in FAKE.
Nothing here reads or changes the real machine.

  python3 tests/alerts/fake.py DIR    write system.json, user.json and system-clear.json to DIR:
                                      every check's alert, from these stand-ins (BRODEC's tests
                                      use them)
"""
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve()
REPO = HERE.parents[2]
sys.path.insert(0, str(REPO / "lib"))

import bromigos_alerts as A  # noqa: E402

NOW = 1793390400000          # 2026-10-30 (a fixed clock)
GB = 1_000_000_000

STUBS = {
    "smartctl": r'''#!/bin/sh
echo "smartctl $*" >> "$FAKE/log"
if [ "$1" = "--scan" ]; then cat "$FAKE/smart/scan.json"; exit 0; fi
for last; do :; done
f="$FAKE/smart/$(basename "$last").json"
[ -f "$f" ] || exit 2
cat "$f"
exit "$(cat "$f.rc" 2>/dev/null || echo 0)"
''',
    "btrfs": r'''#!/bin/sh
echo "btrfs $*" >> "$FAKE/log"
case "$1 $2" in
  "scrub status") cat "$FAKE/scrub" ;;
  "device stats") cat "$FAKE/devstats" ;;
esac
''',
    "upsc": r'''#!/bin/sh
[ -d "$FAKE/ups" ] || { echo "Error: Connection failure: Connection refused" >&2; exit 1; }
if [ "$1" = "-l" ]; then cat "$FAKE/ups/list"; exit 0; fi
cat "$FAKE/ups/${1%@*}"
''',
    "systemctl": r'''#!/bin/sh
echo "systemctl $*" >> "$FAKE/log"
u=""; [ "$1" = "--user" ] && { u=".user"; shift; }
case "$1" in
  list-units)
    case "$*" in
      *--state=failed*) cat "$FAKE/failed$u" 2>/dev/null ;;
      *restic*) cat "$FAKE/backup-units" 2>/dev/null ;;
    esac ;;
  show) cat "$FAKE/show/$2" 2>/dev/null ;;
  status) echo "x $2 - $(sed -n 's/^Description=//p' "$FAKE/show/$2" 2>/dev/null)"; echo "     Active: failed (Result: exit-code)" ;;
esac
exit 0
''',
    "journalctl": r'''#!/bin/sh
cat "$FAKE/journal" 2>/dev/null
''',
    "podman": r'''#!/bin/sh
cat "$FAKE/podman.json" 2>/dev/null || echo '[]'
''',
    "bromigos": r'''#!/bin/sh
echo "bromigos $*" >> "$FAKE/log"
case "$*" in
  "update --check --json") cat "$FAKE/update-check.json" ;;
esac
''',
    "bromigos-game-check": r'''#!/bin/sh
cat "$FAKE/game.json"
''',
    "notify-send": r'''#!/bin/sh
for a; do printf '%s\n' "$a"; done >> "$FAKE/notified"
echo "--" >> "$FAKE/notified"
''',
}

TOOLS = ("sh", "cat", "sed", "basename", "sleep", "touch", "printf", "echo")

ENGINE = r'''#!/bin/sh
echo "fieldkit-engine $*" >> "$FAKE/log"
cat "$FAKE/fieldkit-$3.json" 2>/dev/null || echo '{"ok": false, "message": "no"}'
'''


def smart_nvme(passed=True, warning=0, used=3, media=0):
    return {"model_name": "Samsung SSD 980 PRO 2TB", "serial_number": "S6B0NX0T123456", "firmware_version": "5B2QGXA7",
            "smart_status": {"passed": passed},
            "nvme_smart_health_information_log": {"critical_warning": warning, "temperature": 41,
                                                  "percentage_used": used, "media_errors": media}}


def smart_ata(realloc=0, pending=0):
    return {"model_name": "WDC WD40EFRX-68N32N0", "serial_number": "WD-WCC7K1234567", "firmware_version": "82.00A82",
            "smart_status": {"passed": True},
            "ata_smart_attributes": {"table": [
                {"name": "Reallocated_Sector_Ct", "raw": {"value": realloc}, "when_failed": ""},
                {"name": "Current_Pending_Sector", "raw": {"value": pending}, "when_failed": ""},
                {"name": "Offline_Uncorrectable", "raw": {"value": 0}, "when_failed": ""}]}}


def scrub_text(corrected=0, uncorrectable=0, csum=0):
    return (f"UUID:             0d6e4b0a-0000-4000-8000-000000000001\nScrub started:    Sun Oct 25 03:00:01 2026\n"
            f"Status:           finished\nDuration:         0:14:07\n\tdata_extents_scrubbed: 912345\n"
            f"\tread_errors: 0\n\tcsum_errors: {csum}\n\tverify_errors: 0\n\tsuper_errors: 0\n\tmalloc_errors: 0\n"
            f"\tuncorrectable_errors: {uncorrectable}\n\tunverified_errors: 0\n\tcorrected_errors: {corrected}\n"
            f"\tlast_physical: 0\n")


def devstats(corrupt=0):
    return ("[/dev/nvme0n1p2].write_io_errs    0\n[/dev/nvme0n1p2].read_io_errs     0\n"
            "[/dev/nvme0n1p2].flush_io_errs    0\n"
            f"[/dev/nvme0n1p2].corruption_errs  {corrupt}\n[/dev/nvme0n1p2].generation_errs  0\n")


class FakeMachine:
    """A stand-in computer. `broken()` makes every check find something; `clear()` nothing."""

    def __init__(self, role="desktop"):
        self.tmp = tempfile.TemporaryDirectory(prefix="bromigos-alerts-test-")
        t = Path(self.tmp.name)
        self.root, self.fake, self.bin, self.home = t / "root", t / "fake", t / "bin", t / "home/ann"
        for d in (self.root / "proc/self", self.root / "proc/sys/kernel", self.root / "etc/bromigos",
                  self.root / "var/log", self.fake / "smart", self.fake / "show", self.bin, self.home,
                  self.root / "usr/lib/bromigos/fieldkit", self.root / "var/lib/bromigos"):
            d.mkdir(parents=True, exist_ok=True)
        for name, text in STUBS.items():
            p = self.bin / name
            p.write_text(text)
            p.chmod(0o755)
        # only these from the real system: what the stand-ins themselves use. Nothing else on
        # PATH, so a check can never reach a real smartctl, systemctl or bromigos
        self.tools = t / "tools"
        self.tools.mkdir()
        for tool in TOOLS:
            real = shutil.which(tool)
            if real:
                os.symlink(real, self.tools / tool)
        eng = self.root / "usr/lib/bromigos/fieldkit/fieldkit-engine"
        eng.write_text(ENGINE)
        eng.chmod(0o755)
        if role == "server":
            (self.root / "usr/share/bromigos/server").mkdir(parents=True)
        self.now = NOW
        self.clear()

    def close(self):
        self.tmp.cleanup()

    def env(self, **extra):
        e = {"PATH": f"{self.bin}:{self.tools}", "FAKE": str(self.fake), "HOME": str(self.home),
             "XDG_STATE_HOME": str(self.home / ".local/state"), "XDG_CONFIG_HOME": str(self.home / ".config"),
             "BROMIGOS_ALERTS_ROOT": str(self.root), "BROMIGOS_ALERTS_NOW_MS": str(self.now),
             "BROMIGOS_ALERTS_STATVFS": str(self.fake / "statvfs.json"),
             "BROMIGOS_ALERTS_OWNER_UID": str(os.getuid())}
        e.update(extra)
        return A.Env(e)

    def write(self, rel, data):
        p = self.fake / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(data if isinstance(data, str) else json.dumps(data))

    def rootfile(self, rel, text):
        p = self.root / rel.lstrip("/")
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)
        return p

    def run(self, scope="system", boot=False, **extra):
        return A.run_pass(self.env(**extra), scope, boot=boot)

    # ---- every condition

    def mounts(self):
        self.rootfile("/proc/self/mounts",
                      "proc /proc proc rw 0 0\n/dev/nvme0n1p2 / btrfs rw,noatime,subvol=/@ 0 0\n"
                      "/dev/nvme0n1p2 /home btrfs rw,noatime,subvol=/@home 0 0\n"
                      "/dev/nvme0n1p2 /.snapshots btrfs rw,subvol=/@.snapshots 0 0\n"
                      "/dev/nvme0n1p1 /boot vfat rw 0 0\ntmpfs /tmp tmpfs rw 0 0\n"
                      "/dev/sda1 /mnt/Media ext4 rw 0 0\n/dev/sr0 /mnt/cd iso9660 ro 0 0\n")

    def disk_space(self, root_pct, media_pct=40):
        def fs(total, pct):
            free = int(total * (100 - pct) / 100)
            return {"total": total, "free": free, "avail": free}
        self.write("statvfs.json", {"/": fs(1000 * GB, root_pct), "/boot": fs(GB, 30), "/mnt/Media": fs(4000 * GB, media_pct)})

    def clear(self):
        self.mounts()
        self.disk_space(50)
        self.write("smart/scan.json", {"devices": [{"name": "/dev/nvme0", "type": "nvme"}, {"name": "/dev/sda", "type": "sat"}]})
        self.write("smart/nvme0.json", smart_nvme())
        (self.fake / "smart/nvme0.json.rc").unlink(missing_ok=True)
        self.write("smart/sda.json", smart_ata())
        self.write("scrub", scrub_text())
        self.write("devstats", devstats())
        self.rootfile("/proc/sys/kernel/osrelease", "7.2.11-arch1-1\n")
        self.rootfile("/usr/lib/modules/7.2.11-arch1-1/vmlinuz", "")
        shutil.rmtree(self.root / "usr/lib/modules/7.2.12-arch1-1", ignore_errors=True)
        shutil.rmtree(self.root / "sys", ignore_errors=True)
        self.write("ups/list", "rack\n")
        self.write("ups/rack", "battery.charge: 100\nbattery.runtime: 2400\nups.status: OL\nups.model: Back-UPS 1500\n")
        self.write("show/valheim.service", "ActiveState=active\nSubState=running\nDescription=Valheim dedicated server\n"
                                           "Result=success\n")
        self.write("failed", "")
        self.write("failed.user", "")
        self.write("backup-units", "restic-backup.service loaded inactive dead restic backup\n")
        self.write("show/restic-backup.service", "ActiveState=inactive\nResult=success\nExecMainStatus=0\n"
                   f"ExecMainExitTimestamp=@{NOW // 1000 - 3600}\nDescription=restic backup of /home\n"
                   "TriggeredBy=restic-backup.timer\n")
        self.write("show/restic-backup.timer", f"ActiveState=active\nLastTriggerUSec=@{NOW // 1000 - 3600}\n")
        self.write("journal", "")
        self.write("podman.json", [{"Names": ["minecraft"], "State": "running", "Status": "Up 3 days",
                                    "Labels": {"org.bromigos.game": "Minecraft"}, "Image": "docker.io/itzg/minecraft-server"}])
        self.write("update-check.json", {"schema": 1, "check": {"packages": [], "aur": {"packages": None}}})
        self.rootfile("/var/log/pacman.log", "[2026-10-29T09:00:00-0700] [PACMAN] starting full system upgrade\n"
                                             "[2026-10-29T09:01:00-0700] [ALPM] transaction completed\n")
        self.write("game.json", {"schema": 1, "ok": True, "healthy": True, "steam_root": str(self.home / ".local/share/Steam"),
                                 "findings": [{"check": "runtime", "level": "ok", "title": "Runtimes whole"}]})
        self.write("fieldkit-black-screen.json", {"ok": True, "findings": [
            {"id": "0", "title": "The login screen starts: sddm.service", "detail": "", "fix": "", "ok": True}]})
        self.write("fieldkit-last-boot.json", {"ok": True, "findings": [
            {"id": "0", "title": "Every part of the system started", "detail": "", "fix": "", "ok": True}]})
        p = self.root / "var/lib/bromigos/server/update.json"
        if p.exists():
            p.unlink()

    def broken(self):
        """Something for every check to find."""
        self.disk_space(93, media_pct=98)
        self.write("smart/nvme0.json", smart_nvme(passed=False, warning=0x04, used=91, media=17))
        self.write("smart/nvme0.json.rc", "8")
        self.write("smart/sda.json", smart_ata(realloc=12, pending=3))
        self.write("scrub", scrub_text(corrected=3, uncorrectable=1, csum=4))
        self.write("devstats", devstats(corrupt=4))
        self.rootfile("/usr/lib/modules/7.2.12-arch1-1/vmlinuz", "")
        shutil.rmtree(self.root / "usr/lib/modules/7.2.11-arch1-1", ignore_errors=True)
        self.rootfile("/sys/module/nvidia/version", "615.71.09\n")
        self.rootfile("/usr/lib/libEGL_nvidia.so.615.78.08", "")
        self.write("ups/list", "rack\n")
        self.write("ups/rack", "battery.charge: 18\nbattery.runtime: 240\nups.status: OB LB\nups.model: Back-UPS 1500\n"
                               "input.voltage: 0.0\n")
        self.write("failed", "nginx.service loaded failed failed A high performance web server\n"
                             "NetworkManager-wait-online.service loaded failed failed Network Manager Wait Online\n"
                             "run-u42.service loaded failed failed transient\n")
        self.write("show/nginx.service", "Transient=no\nUnitFileState=enabled\nDescription=A high performance web server\n"
                                         "Result=exit-code\n")
        self.write("failed.user", "syncthing.service loaded failed failed Syncthing - Open Source Continuous File Synchronization\n")
        self.write("show/syncthing.service", "Transient=no\nUnitFileState=enabled\n"
                                             "Description=Syncthing - Open Source Continuous File Synchronization\nResult=exit-code\n")
        self.write("journal", "2026-10-30T09:12:01-0700 box nginx[812]: nginx: [emerg] bind() to 0.0.0.0:80 failed (98: Address already in use)\n"
                              "2026-10-30T09:12:01-0700 box systemd[1]: nginx.service: Main process exited, code=exited, status=1/FAILURE\n")
        self.write("backup-units", "restic-backup.service loaded failed failed restic backup\n")
        self.write("show/restic-backup.service", "ActiveState=failed\nResult=exit-code\nExecMainStatus=1\n"
                   f"ExecMainExitTimestamp=@{NOW // 1000 - 7200}\nDescription=restic backup of /home\n"
                   "TriggeredBy=restic-backup.timer\n")
        self.write("podman.json", [{"Names": ["minecraft"], "State": "exited", "Status": "Exited (137) 5 minutes ago",
                                    "Labels": {"org.bromigos.game": "Minecraft"}, "Image": "docker.io/itzg/minecraft-server"}])
        self.rootfile("/etc/bromigos/alerts.toml", '[game]\nunits = ["valheim"]\n')
        self.write("show/valheim.service", "ActiveState=failed\nSubState=failed\nDescription=Valheim dedicated server\nResult=signal\n")
        self.write("update-check.json", {"schema": 1, "check": {
            "packages": [{"name": "linux", "from": "7.2.11.arch1-1", "to": "7.2.12.arch1-1"},
                         {"name": "mesa", "from": "1:26.2.3-1", "to": "1:26.2.4-1"},
                         {"name": "firefox", "from": "144.0-1", "to": "144.0.1-1"}],
            "aur": {"packages": []}}})
        self.rootfile("/var/log/pacman.log", "[2026-09-20T09:00:00-0700] [PACMAN] starting full system upgrade\n"
                                             "[2026-09-20T09:01:00-0700] [ALPM] transaction completed\n")
        self.write("game.json", {"schema": 1, "ok": True, "healthy": False, "steam_root": str(self.home / ".local/share/Steam"),
                                 "findings": [
                                     {"check": "default", "level": "problem", "title": "Steam's default Proton isn't installed",
                                      "detail": "GE-Proton10-25 is set as the default, but it isn't in compatibilitytools.d.",
                                      "fix": "bromigOS sets the newest GE-Proton again.", "fixable": "default", "auto": True},
                                     {"check": "nvapi", "level": "problem", "title": "Proton games don't get NVAPI (DLSS)",
                                      "detail": "PROTON_ENABLE_NVAPI isn't set in Steam's launch environment.",
                                      "fix": "Run bromigos game check --fix with Steam closed.", "fixable": "nvapi", "auto": False},
                                     {"check": "prune", "level": "warn", "title": "2 old GE-Proton builds no game uses",
                                      "detail": "GE-Proton9-20, GE-Proton9-27 take 1.4 GB.", "fix": "", "fixable": "prune", "auto": True}]})
        self.write("fieldkit-black-screen.json", {"ok": True, "findings": [
            {"id": "0", "title": "The login screen starts: sddm.service", "detail": "", "fix": "", "ok": True},
            {"id": "1", "title": "A login screen setting left in /etc/sddm.conf.d/10-gpu.conf.disabled",
             "detail": "It is named 10-gpu.conf.disabled, which looks switched off, but SDDM reads every file in that folder.",
             "fix": "Move it out (kept in a backup)", "ok": False,
             "commands": ["mkdir -p /var/lib/bromigos/fieldkit-backups/20261030-0912-black-screen/etc/sddm.conf.d",
                          "mv /etc/sddm.conf.d/10-gpu.conf.disabled /var/lib/bromigos/fieldkit-backups/20261030-0912-black-screen/etc/sddm.conf.d/"],
             "touches": ["/etc/sddm.conf.d/10-gpu.conf.disabled"]}]})
        # what a Field Kit stick saved in this install, from its last-boot check
        self.rootfile("/var/lib/bromigos/fieldkit/findings.json", json.dumps({"schema": 1, "checks": {"last-boot": {
            "saved_at": NOW - 3600_000, "findings": [
                {"id": "2", "title": "The graphics driver reported errors",
                 "detail": "The last ones:\n  NVRM: GPU 0000:01:00.0: RmInitAdapter failed! (0x26:0x56:1474)",
                 "fix": "", "ok": False, "commands": [], "touches": []}]}}}))
        self.write("fieldkit-last-boot.json", {"ok": False, "message": "no saved log"})
        self.server_hold()

    def server_hold(self):
        self.rootfile("/var/lib/bromigos/server/update.json", json.dumps({
            "phase": "ok", "last_success_ts": NOW / 1000 - 5 * 86400,
            "hold": {"since": "2026-10-30T03:00:05-07:00", "items": [
                {"title": "Manual intervention required for the openssh 10.3 upgrade",
                 "link": "https://archlinux.org/news/manual-intervention-required-for-the-openssh-103-upgrade/",
                 "published": "2026-10-28T12:00:00+00:00"}]}}))


def write_fixtures(out):
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    m = FakeMachine(role="server")
    try:
        m.broken()
        system = m.run("system", boot=True)
        user = m.run("user")
        # every check type, in one place: the user's and the system's
        (out / "system.json").write_text(json.dumps(system, indent=1) + "\n")
        (out / "user.json").write_text(json.dumps(user, indent=1) + "\n")
        m.clear()
        m.now += 15 * 60_000
        clear = m.run("system", boot=True)
        (out / "system-clear.json").write_text(json.dumps(clear, indent=1) + "\n")
        user_clear = m.run("user")
        (out / "user-clear.json").write_text(json.dumps(user_clear, indent=1) + "\n")
    finally:
        m.close()
    return out


if __name__ == "__main__":
    print(write_fixtures(sys.argv[1] if len(sys.argv) > 1 else "fixtures"))
