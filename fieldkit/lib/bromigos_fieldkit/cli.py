"""`bromigos fieldkit` (and `fieldkit`) on the command line: the menu, or one job by name, in
plain text for a console or an SSH session (docs/fieldkit.md)."""

import argparse
import json
import os
import shutil
import subprocess
import sys
import time

from . import diagnose, system

IMAGE = "/usr/share/bromigos/fieldkit/bromigos-fieldkit.iso"
EDITION = "/usr/share/bromigos/fieldkit/edition.json"
BOOT_HELPER = "/usr/lib/bromigos/boot/bromigos-fieldkit-boot"


def need_root(argv):
    if os.geteuid() == 0:
        return
    sudo = shutil.which("sudo")
    if not sudo:
        sys.exit("fieldkit: this needs root (run it as root)")
    os.execv(sudo, [sudo, "--preserve-env=BROMIGOS_FIELDKIT_SETTINGS", sys.executable, "-I",
                    os.path.realpath(sys.argv[0]), *argv])


def target_for(root):
    if root:
        t = system.Target(root)
        top = os.environ.get("BROMIGOS_FIELDKIT_TOP")
        t.top = top if top and os.path.isdir(top) else None
        return t
    t = system.Target.load() or system.running_install()
    if not t:
        sys.exit("fieldkit: no install to look at. Mount it from the menu (fieldkit), or give --root DIR.")
    return t


def show(found):
    for f in found:
        print(("  ok   " if f.ok else "  ▸    ") + f.title)
        if f.detail and not f.ok:
            for line in f.detail.splitlines():
                print("       " + line)
        if f.fix and not f.ok:
            print(f"       fix: {f.fix_label}")
    if not any(not f.ok for f in found):
        print("  Nothing wrong found.")


def usb(dev):
    """The Field Kit medium onto a USB drive: this medium itself when it's running, else the
    image package's copy."""
    src = None
    if os.path.isdir("/run/archiso/bootmnt"):
        r = system.run(["findmnt", "-no", "SOURCE", "/run/archiso/bootmnt"], check=False)
        src = r.stdout.strip() or None
        if src and "/dev/loop" in src:
            src = None
    if not src and os.path.isfile(IMAGE):
        src = IMAGE
    if not src:
        sys.exit("fieldkit usb: no Field Kit image here (sudo pacman -S bromigos-fieldkit)")
    drives = [p for p in system.block_devices() if getattr(p, "type", "") == "disk" and (p.removable or p.tran == "usb")]
    if not dev:
        if not drives:
            sys.exit("fieldkit usb: plug in a USB drive first")
        print("USB drives:")
        for p in drives:
            print(f"  {p.path}  {p.size}  {p.model}")
        sys.exit("fieldkit usb DEVICE: name the one to write (everything on it is replaced)")
    if dev not in [p.path for p in drives]:
        sys.exit(f"fieldkit usb: {dev} isn't a USB drive Field Kit can see")
    ans = input(f"Everything on {dev} will be replaced by Field Kit. Type YES to go ahead: ")
    if ans.strip() != "YES":
        sys.exit("Nothing written.")
    size = os.path.getsize(src) if os.path.isfile(src) else None
    cmd = ["dd", f"if={src}", f"of={dev}", "bs=4M", "conv=fsync", "oflag=direct", "status=progress"]
    if size is None:
        # the running medium's device: only as many bytes as its ISO holds (isosize)
        r = system.run(["isosize", src], check=False)
        n = int(r.stdout.strip() or 0)
        if not n:
            sys.exit("fieldkit usb: couldn't tell this medium's size")
        cmd += ["iflag=fullblock,count_bytes", f"count={n}"]
    rc = subprocess.call(cmd)
    subprocess.call(["sync"])
    print("Done: the drive starts Field Kit." if rc == 0 else "The copy failed.")
    return rc


GREEN, SOFT, WARN, DIM, RESET, BOLD = "\033[32m", "\033[92m", "\033[33m", "\033[90m", "\033[0m", "\033[1m"


def panel(title, lines, colour=GREEN):
    """A DRIFTGLASS Glass panel in plain terminal text (the console's 16 colours, which
    bromigos-boot sets to DRIFTGLASS's; box drawing, which Geist Mono's console font has)."""
    width = max([len(title) + 4] + [len(x) + 4 for x in lines] + [60])
    out = [f"{colour}╭─ {BOLD}{title}{RESET}{colour} " + "─" * (width - len(title) - 4) + f"╮{RESET}"]
    out += [f"{colour}│{RESET} {x.ljust(width - 2)}{colour}│{RESET}" for x in lines]
    out.append(f"{colour}╰" + "─" * (width - 1) + f"╯{RESET}")
    return "\n".join(out)


def console(max_rounds=None):
    """The first console on a Field Kit medium (root's login there runs this): the menu, inside
    a shared tmux session while remote help is on, then a shell when someone leaves it, then the
    menu again. A menu that's missing or fails at once is never retried in a loop: one panel
    says what happened and what to do, and after three quick failures the console stays a
    shell (`fieldkit` tries again)."""
    from . import medium
    os.environ["BROMIGOS_FIELDKIT_CONSOLE"] = "1"      # its shells don't start another console
    shell = os.environ.get("BROMIGOS_FIELDKIT_SHELL") or shutil.which("zsh") or "/bin/bash"
    menu = (os.environ.get("BROMIGOS_FIELDKIT_MENU") or "bromigos fieldkit").split()
    quick_failures = rounds = 0
    while max_rounds is None or rounds < max_rounds:
        rounds += 1
        if quick_failures < 3:
            started = time.monotonic()
            if not shutil.which(menu[0]):
                rc, why = 127, f"{menu[0]} isn't on this system"
            else:
                argv = menu
                if medium.remote_state().get("on") and shutil.which("tmux"):
                    argv = ["tmux", "new-session", "-A", "-s", "fieldkit", *menu]
                rc = subprocess.call(argv)
                why = f"{' '.join(menu)} stopped with an error ({rc})"
            quick = rc != 0 and time.monotonic() - started < 10
            quick_failures = quick_failures + 1 if quick else 0
            if quick:
                print(panel("Field Kit's menu didn't open", [
                    why + ".",
                    "You're in a shell instead. Everything Field Kit does works from here too:",
                    "  bromigos fieldkit why             what went wrong on the last boot",
                    "  bromigos fieldkit black-screen    the black screen checks",
                    "Type fieldkit to try the menu again." if quick_failures < 3 else
                    "It won't be opened again by itself: type fieldkit to try.",
                ], WARN))
            else:
                print(panel("Field Kit", ["The menu is closed. Type fieldkit to open it again;",
                                          "exit comes back to it."]))
        subprocess.call([shell, "-l"])
        if quick_failures >= 3:
            time.sleep(1)                               # a shell that exits at once can't spin
    return 0


SCRIPTABLE = ("repair", "mount", "unmount", "disks", "scrub", "backup", "overview", "image", "erase", "windows")
SCRIPT_HELP = """bromigos fieldkit — every Field Kit job as a command, for SSH and the stick's autorun scripts.
Add --json for the engine's JSON, --dry-run to see the exact commands and what they touch
without running them. --yes skips the question a change asks.

  overview                              this computer, what's on its drives, the network
  mount DEV  (passphrase on stdin)      unlock and mount an install at /mnt/bromigos
  unmount
  repair last-boot                      what went wrong on the last boot
  repair black-screen [--fix [ID…]]     the black screen checks; --fix applies every fix (or those IDs)
  repair rollback N                     start from snapshot N from now on
  repair boot-menu                      put GRUB back and make its menu again
  repair boot-options [--set WORDS]     the kernel's settings at every start
  disks                                 each drive's own health
  scrub                                 btrfs's read-only check of the mounted install
  backup DEV                            every home folder to a USB drive
  image|erase|windows …                 the engine's imaging, secure erase and Windows verbs
"""


def engine_call(args, stdin=None):
    """One engine verb, as its JSON document (and the progress lines it streamed, printed)."""
    import io
    from contextlib import redirect_stdout
    from .engine import main as engine
    buf = io.StringIO()
    old = sys.stdin
    if stdin is not None:
        sys.stdin = io.StringIO(stdin)
    try:
        with redirect_stdout(buf):
            engine(list(args))
    finally:
        sys.stdin = old
    lines = [line for line in buf.getvalue().splitlines() if line.strip()]
    docs = [json.loads(line) for line in lines]
    for d in docs[:-1]:
        if "line" in d:
            print(d["line"], file=sys.stderr)
    return docs[-1] if docs else {"ok": False, "message": "no answer"}


def scripted(argv):
    """`bromigos fieldkit repair …` and the other scriptable jobs."""
    as_json = "--json" in argv
    dry = "--dry-run" in argv
    yes = "--yes" in argv
    words = [a for a in argv if a not in ("--json", "--dry-run", "--yes")]
    if not words or words[0] in ("-h", "--help") or words[-1] in ("-h", "--help"):
        print(SCRIPT_HELP)
        return 0
    need_root(argv)

    def out(doc):
        if as_json:
            print(json.dumps(doc, indent=1))
        else:
            if doc.get("message"):
                print(doc["message"])
            for f in doc.get("findings", []):
                print(("  ok   " if f["ok"] else f"  [{f['id']}]  ") + f["title"])
                if not f["ok"] and f.get("detail"):
                    print("       " + f["detail"].replace("\n", "\n       "))
                for c in f.get("commands", []) if not f["ok"] else []:
                    print("       $ " + c)
            for c in doc.get("commands", []):
                print("  $ " + c)
            if doc.get("touches"):
                print("  touches: " + ", ".join(doc["touches"]))
        return 0 if doc.get("ok", True) else 1

    def confirm(what):
        if yes or not sys.stdin.isatty():
            return yes
        return input(f"{what} [y/N] ").strip().lower().startswith("y")

    def change(action, plan_args, run_args, question):
        plan = engine_call(["plan", action, *plan_args])
        if dry or not plan.get("ok"):
            return out(plan)
        if not as_json:
            out(plan)
        if not confirm(question):
            print("Nothing done (--yes to go ahead without asking).")
            return 1
        return out(engine_call(run_args))

    verb, rest = words[0], words[1:]
    if verb == "overview":
        return out(engine_call(["overview"]))
    if verb == "mount":
        if dry:
            return out(engine_call(["plan", "mount", rest[0]]))
        pw = sys.stdin.read().rstrip("\n") if not sys.stdin.isatty() else __import__("getpass").getpass("The disk's passphrase: ")
        return out(engine_call(["mount", rest[0]], stdin=pw))
    if verb == "unmount":
        return out(engine_call(["plan", "unmount"]) if dry else engine_call(["unmount"]))
    if verb == "disks":
        doc = engine_call(["disks"])
        if not as_json:
            for d in doc.get("disks", []):
                print(d["verdict"])
            return 0
        return out(doc)
    if verb == "scrub":
        return out(engine_call(["plan", "scrub"]) if dry else engine_call(["scrub"]))
    if verb == "backup":
        return change("backup", [rest[0]], ["backup", rest[0]], f"Back up every home folder to {rest[0]}?")
    if verb in ("image", "erase", "windows"):
        return out(engine_call([verb, *rest]))
    if verb == "repair" and rest:
        job, more = rest[0], rest[1:]
        if job in ("last-boot", "why"):
            return out(engine_call(["check", "last-boot"]))
        if job == "black-screen":
            doc = engine_call(["check", "black-screen"])
            if "--fix" not in more:
                return out(doc)
            ids = [m for m in more if m != "--fix"] or [f["id"] for f in doc.get("findings", []) if f.get("fix") and not f["ok"]]
            if dry or as_json is False:
                out(doc)
            if dry:
                return 0
            if not ids or not confirm(f"Apply {len(ids)} fix(es)? Each backs up what it changes."):
                print("Nothing done.")
                return 0 if not ids else 1
            rc = 0
            for i in ids:
                rc |= out(engine_call(["fix", "black-screen", i]))
            return rc
        if job == "rollback" and more:
            return change("rollback", [more[0]], ["rollback", more[0]], f"Start from snapshot {more[0]} from now on?")
        if job == "boot-menu":
            return change("grub-repair", [], ["grub-repair"], "Put GRUB back and make the boot menu again?")
        if job == "boot-options":
            if "--set" in more:
                new = more[more.index("--set") + 1:]
                return change("boot-options", new, ["boot-options", "--set", *new], "Save these boot options?")
            return out(engine_call(["boot-options"]))
    print(SCRIPT_HELP, file=sys.stderr)
    return 2


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv[:1] == ["engine"]:
        need_root(argv)
        from .engine import main as engine
        return engine(argv[1:])
    if argv[:1] and argv[0] in SCRIPTABLE:
        return scripted(argv)
    ap = argparse.ArgumentParser(prog="bromigos fieldkit", description="Field Kit. Repair. Recon. Deploy.: fix any computer, run your lab, install a server (docs/fieldkit.md)")
    sub = ap.add_subparsers(dest="verb")
    sub.add_parser("menu", help="the Field Kit menu (the default): bromigos fieldkit's screens")
    p = sub.add_parser("why", help="what went wrong on the last boot, in plain words")
    p.add_argument("--root", help="an install mounted there (default: the mounted one, or this system)")
    p = sub.add_parser("black-screen", help="check the causes of a black screen at startup")
    p.add_argument("--root")
    p.add_argument("--fix", action="store_true", help="apply every fix it offers (each backs up first)")
    sub.add_parser("status", help="whether Field Kit is in this machine's boot menu")
    p = sub.add_parser("usb", help="write Field Kit onto a USB drive")
    p.add_argument("device", nargs="?")
    p = sub.add_parser("make-stick", help="write Field Kit onto a USB drive with your SSH key, Wi-Fi and lab settings")
    p.add_argument("device", nargs="?")
    p.add_argument("--ssh-key", action="append", default=[], help="a public key file (repeat); default: ~/.ssh/id_*.pub")
    p.add_argument("--wifi", action="append", default=[], help="SSID or SSID:PASSWORD (repeat)")
    p.add_argument("--lab", help="the lab connection to carry (default: ~/.config/bromigos/homelab.toml)")
    p.add_argument("--remote", action="store_true", help="SSH on at every start (with the key)")
    p.add_argument("--yes", action="store_true", help="don't ask before replacing the drive")
    p.add_argument("--settings-only", action="store_true", help="only (re)write the settings partition of a Field Kit stick")
    p.add_argument("--iso", help="the Field Kit ISO to write (default: bromigos-fieldkit's)")
    p = sub.add_parser("remote", help="remote help: SSH on or off, and how to reach this machine")
    p.add_argument("state", nargs="?", choices=["on", "off", "status"], default="status")
    sub.add_parser("stick-boot", help=argparse.SUPPRESS)
    sub.add_parser("console", help=argparse.SUPPRESS)
    p = sub.add_parser("edition", help="what the Field Kit edition installs (for installers)")
    p.add_argument("--json", action="store_true")
    sub.add_parser("brodec-setup", help="as root, before pairing with BRODEC: BRODEC's capability file for this machine, when there's none")
    a = ap.parse_args(argv)
    verb = a.verb or "menu"
    if verb == "brodec-setup":
        # a setup screen's root step (pkexec) before `brodec-machine pair --json --start`
        from . import machine_link
        if os.geteuid() != 0:
            print("brodec-setup writes root's /etc/brodec-machine/machine.toml: run it as root.", file=sys.stderr)
            return 1
        wrote = machine_link.write_capability()
        print(("wrote " if wrote else "kept (the operator's) ") + machine_link.CONFIG)
        return 0
    if verb == "status":
        if os.path.exists(BOOT_HELPER):
            return subprocess.call([BOOT_HELPER, "status"])
        print("bromigos-boot isn't installed: no Field Kit in the boot menu")
        return 0
    if verb == "edition":
        try:
            doc = json.load(open(EDITION))
        except OSError:
            sys.exit(f"fieldkit: no {EDITION} (package bromigos-fieldkit)")
        if a.json:
            print(json.dumps(doc, indent=1))
        else:
            print(doc.get("summary", ""))
            print("packages: " + " ".join(doc.get("packages", [])))
            print("services: " + " ".join(doc.get("services", [])))
        return 0
    if verb == "make-stick":
        from .stick import make_stick
        return make_stick(a, need_root, argv)
    need_root(argv)
    if verb == "stick-boot":
        from . import medium
        medium.boot()
        return 0
    if verb == "remote":
        from . import medium
        if a.state == "on":
            medium.remote_on()
        elif a.state == "off":
            medium.remote_off()
            print("Remote help is off.")
            return 0
        print(medium.remote_words() or "Remote help is off. (bromigos fieldkit remote on)")
        return 0
    if verb == "console":
        return console()
    if verb == "menu":
        os.execvp("bromigos", ["bromigos", "fieldkit"])
    if verb == "usb":
        return usb(a.device)
    t = target_for(a.root)
    if verb == "why":
        show(diagnose.last_boot(t))
        return 0
    if verb == "black-screen":
        found = diagnose.black_screen(t)
        show(found)
        if a.fix:
            for f in found:
                if f.fix and not f.ok:
                    print(f"\n{f.fix_label}: {f.fix(t)}")
        return 0
    return 2
