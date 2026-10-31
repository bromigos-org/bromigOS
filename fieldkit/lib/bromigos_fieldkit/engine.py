"""Field Kit's engine: the jobs behind the screens, as JSON (docs/fieldkit.md, "How it's built").

The screens are bromigos-core's (`bromigos fieldkit`, ratatui, DRIFTGLASS); they run
`fieldkit engine VERB …` as root and read one JSON document from its standard output. Jobs that
take a while print progress lines first, each a JSON object with "progress" (0..100 or null)
and "line", then the result as the last line. Errors are {"ok": false, "message": "..."},
in plain words, exit 0; the exit status is 2 only for a verb or argument that doesn't exist.

  overview                        the Home screen: this computer, what's on its drives, the
                                  network, SSH, the stick, and suggestions from real findings
  status                          where Field Kit is: live medium or install, the network, the
                                  install it works on, remote help, the stick's settings
  installs                        partitions that may hold an install
  mount DEVICE                    unlock (the passphrase on standard input) and mount it
  unmount
  check black-screen|last-boot    findings: [{id, title, detail, fix, ok}]; on a mounted install the
                                  ones that aren't fine are also saved in it
                                  (/var/lib/bromigos/fieldkit/findings.json), so the install's own
                                  alerts raise them at its next boot (docs/alerts.md)
  fix black-screen|last-boot ID   apply that finding's fix (each backs up first)
  snapshots | rollback N
  grub-repair
  boot-options [--set WORDS]      the kernel's settings and the presets
  disks | scrub                   drive health; btrfs's read-only check
  backup-targets | backup DEVICE  every home folder to a USB drive (progress lines)
  edit-prepare PATH               back the file up; returns the path to open in the editor
  remote on|off|status
  graphics                        cards, drivers, connected monitors
  plan ACTION [ARGS]              what an action would run and touch, without running it:
                                  rollback N, grub-repair, boot-options WORDS, scrub, backup DEV,
                                  mount DEV, unmount (findings carry their own commands)
"""

import json
import os
import re
import subprocess
import sys

from . import diagnose, repairs, system

CHECKS = {"black-screen": diagnose.black_screen, "last-boot": diagnose.last_boot}


def out(doc):
    sys.stdout.write(json.dumps(doc) + "\n")
    sys.stdout.flush()


def progress(pct, line):
    out({"progress": pct, "line": line})


def target(required=True):
    t = system.Target.load() or system.running_install()
    if required and not t:
        raise system.Failed("Mount your bromigOS install first (Repair › Mount my install).")
    return t


def fill(text, target):
    """{root} and {top} in a command, for this install; on the running system, no chroot."""
    root = target.root if target else system.MOUNT
    top = (target.top if target and target.top else system.TOP)
    if root == "/":
        text = text.replace("arch-chroot {root} ", "").replace("{root}", "")
    return text.replace("{root}", root).replace("{top}", top)


def finding_doc(i, f, target=None):
    return {"id": str(i), "title": f.title, "detail": f.detail, "fix": f.fix_label if f.fix else "", "ok": f.ok,
            "commands": [fill(c, target) for c in getattr(f, "commands", [])], "touches": list(getattr(f, "touches", []))}


FINDINGS = "/var/lib/bromigos/fieldkit/findings.json"


class _Running:
    """The install as it is once it boots by itself: commands for "/", no chroot."""
    root = "/"
    top = None


def save_findings(target, check, found, now=None):
    """Keep CHECK's findings that aren't fine in the install itself, with their commands as
    they read on the running install, for its next boot (bromigos alerts' fieldkit.finding).
    Nothing on the running system (it has its own alerts) or when every finding is fine."""
    import time
    if target is None or target.is_live_root:
        return
    path = target.path(FINDINGS)
    try:
        with open(path) as f:
            doc = json.load(f)
    except (OSError, ValueError):
        doc = {}
    checks = doc.get("checks") if isinstance(doc.get("checks"), dict) else {}
    bad = [finding_doc(i, f, _Running) for i, f in enumerate(found) if not f.ok]
    for d in bad:
        d["lines"] = [str(x) for x in (getattr(found[int(d["id"])], "lines", None) or [])][-20:]
    if bad:
        checks[check] = {"saved_at": int((now or time.time()) * 1000), "findings": bad}
    else:
        checks.pop(check, None)
    try:
        if checks:
            os.makedirs(os.path.dirname(path), mode=0o755, exist_ok=True)
            tmp = path + ".tmp"
            with open(tmp, "w") as f:
                json.dump({"schema": 1, "checks": checks}, f, indent=1)
            os.chmod(tmp, 0o644)
            os.replace(tmp, path)
        elif os.path.exists(path):
            os.unlink(path)
    except OSError:
        pass   # a read-only install still gets its findings on screen


def status():
    from . import medium
    t = target(required=False)
    doc = {"ok": True, "live": system.live_medium(), "network": system.link(),
           "reduced_motion": system.reduced_motion(), "remote": medium.remote_state(),
           "remote_words": medium.remote_words(), "stick": medium.stick_summary(), "target": None}
    if t:
        doc["target"] = {"root": t.root, "hostname": t.hostname(), "mounted_by_fieldkit": t.mounted_by_us,
                         "users": [u for u, _ in t.users()]}
    try:
        doc["version"] = system.read("/usr/share/bromigos/fieldkit/version").strip()
    except OSError:
        doc["version"] = ""
    if os.path.exists("/run/archiso/bootmnt") and os.path.isfile("/version"):
        doc["version"] = system.read("/version").strip()
    return doc


def backup_stream(dev):
    t = target()
    drives = {p.path: p for p in system.usb_targets()}
    if dev not in drives:
        raise system.Failed("That drive isn't a USB drive Field Kit can write to.")
    p = drives[dev]
    mp = p.mountpoints[0] if p.mountpoints else None
    if not mp:
        mp = "/run/bromigos-fieldkit/usb"
        os.makedirs(mp, exist_ok=True)
        system.run(["mount", dev, mp])
    argv, folder = repairs.backup_argv(t, mp)
    proc = subprocess.Popen(argv, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1)
    for raw in proc.stdout:
        for line in raw.replace("\r", "\n").splitlines():
            m = re.search(r"\s(\d+)%", line)
            progress(int(m.group(1)) if m else None, line.strip())
    rc = proc.wait()
    system.run(["sync"], check=False)
    if rc != 0:
        return {"ok": False, "message": "The copy stopped with an error (the drive may be full)."}
    return {"ok": True, "message": f"Done: everything is in {folder} on the drive."}


def main(argv):
    if not argv:
        print(__doc__)
        return 2
    verb, args = argv[0], argv[1:]
    try:
        if verb == "status":
            doc = status()
        elif verb == "installs":
            doc = {"ok": True, "installs": [{"path": p.path, "fstype": p.fstype, "size": p.size, "label": p.label,
                                             "model": p.model, "encrypted": p.fstype == "crypto_LUKS"}
                                            for p in system.install_candidates()]}
        elif verb == "mount":
            passphrase = sys.stdin.read().rstrip("\n") if not sys.stdin.isatty() else None
            t = system.mount_install(args[0], passphrase or None)
            doc = {"ok": True, "message": f"{t.hostname()} is open at {t.root}. Unmount it before you restart.",
                   "warning": getattr(t, "warning", "")}
        elif verb == "unmount":
            system.unmount_install(target())
            doc = {"ok": True, "message": "Unmounted and locked. It's safe to restart."}
        elif verb == "check":
            t = target()
            found = CHECKS[args[0]](t)
            save_findings(t, args[0], found)
            doc = {"ok": True, "findings": [finding_doc(i, f, t) for i, f in enumerate(found)]}
        elif verb == "fix":
            t = target()
            found = CHECKS[args[0]](t)
            f = found[int(args[1])]
            if not f.fix:
                raise system.Failed("That finding has nothing to fix.")
            doc = {"ok": True, "message": f.fix(t)}
            # what's left for the install's next boot: the check again, after the fix
            try:
                save_findings(t, args[0], CHECKS[args[0]](t))
            except (system.Failed, OSError):
                pass
        elif verb == "snapshots":
            doc = {"ok": True, "snapshots": [{"number": s.number, "date": s.date, "kind": s.kind,
                                              "description": s.description, "title": s.title()}
                                             for s in repairs.snapshots(target())]}
        elif verb == "rollback":
            doc = {"ok": True, "message": repairs.rollback(target(), int(args[0]))}
        elif verb == "grub-repair":
            doc = {"ok": True, "message": repairs.repair_grub(target())}
        elif verb == "boot-options":
            t = target()
            if args[:1] == ["--set"]:
                doc = {"ok": True, "message": repairs.set_boot_options(t, " ".join(args[1:]).split())}
            else:
                doc = {"ok": True, "words": repairs.boot_options(t),
                       "presets": [{"word": w, "label": label, "hint": h} for w, label, h in repairs.PRESETS]}
        elif verb == "disks":
            rows = []
            for d in repairs.disks():
                verdict, _ = repairs.disk_report(d.path)
                rows.append({"path": d.path, "model": d.model, "size": d.size, "verdict": verdict,
                             "failing": "FAILING" in verdict})
            doc = {"ok": True, "disks": rows}
        elif verb == "scrub":
            verdict, details = repairs.scrub(target())
            doc = {"ok": True, "message": verdict, "details": details}
        elif verb == "backup-targets":
            doc = {"ok": True, "drives": [{"path": p.path, "describe": p.describe(), "fstype": p.fstype}
                                          for p in system.usb_targets()]}
        elif verb == "backup":
            doc = backup_stream(args[0])
        elif verb == "edit-prepare":
            t = target()
            path = args[0] if args[0].startswith("/") else "/" + args[0]
            b = system.Backup(t, "edit")
            kept = b.keep(path)
            doc = {"ok": True, "open": t.path(path), "backup": b.where() if kept else "",
                   "candidates": []}
        elif verb == "edit-candidates":
            t = target()
            common = ["/etc/default/grub", "/etc/mkinitcpio.conf", "/etc/fstab", "/etc/pacman.conf", "/etc/hostname"]
            if os.path.isdir(t.path("/etc/sddm.conf.d")):
                common += ["/etc/sddm.conf.d/" + n for n in sorted(os.listdir(t.path("/etc/sddm.conf.d")))]
            for _, home in t.users():
                common += [os.path.join(home, ".local/state/bromigos/hw/hyprland.lua"), os.path.join(home, ".config/hypr/hyprland.lua")]
            doc = {"ok": True, "files": [c for c in common if os.path.exists(t.path(c))]}
        elif verb == "remote":
            from . import medium
            st = args[0] if args else "status"
            if st == "on":
                medium.remote_on()
            elif st == "off":
                medium.remote_off()
            doc = {"ok": True, "remote": medium.remote_state(), "words": medium.remote_words()}
        elif verb == "plan":
            # what an action would run, without running it ("show commands", --dry-run)
            t = target(required=args[0] not in ("mount",))
            p = repairs.plan(t, args[0], *args[1:])
            doc = {"ok": True, "action": args[0], "commands": [fill(c, t) for c in p["commands"]],
                   "touches": [x for x in p["touches"] if x]}
        elif verb == "overview":
            from .overview import overview
            doc = overview()
        elif verb == "graphics":
            cards = diagnose.connected_cards()
            r = system.run(["lspci", "-nnk", "-d", "::0300"], check=False)
            r2 = system.run(["lspci", "-nnk", "-d", "::0302"], check=False)
            doc = {"ok": True, "cards": [{"pci": k, "connected": v} for k, v in sorted(cards.items())],
                   "lspci": (r.stdout + r2.stdout).strip()}
        else:
            # the engines other modules add (imaging, erase, windows): engine_<verb>(args) -> doc
            mod = {"image": "imaging", "erase": "erase", "windows": "windows", "vector": "vector_tools"}.get(verb)
            if not mod:
                print(f"fieldkit engine: no verb {verb}", file=sys.stderr)
                return 2
            m = __import__(f"bromigos_fieldkit.{mod}", fromlist=["engine"])
            doc = m.engine(args, progress)
    except (system.Failed, OSError, KeyError, IndexError, ValueError) as e:
        doc = {"ok": False, "message": str(e) if isinstance(e, (system.Failed, OSError)) else f"bad request: {e}"}
    out(doc)
    return 0
