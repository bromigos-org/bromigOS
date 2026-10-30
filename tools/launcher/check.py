#!/usr/bin/env python3
"""The app launcher's entries: every bromigOS window reachable from a launcher (Alt+P, rofi
drun, or any launcher that reads desktop entries), checked from this checkout.

  tools/launcher/check.py              every check below
  tools/launcher/check.py --static     only what needs no programs run (a package's check())
  tools/launcher/check.py --only DIR   only the entries in DIR/applications (live, desktop, …)
  tools/launcher/check.py --listing    print the launcher's listing (name, icon, comment) and exit

What it checks (docs/menu.md, "In the app launcher"):

  static   each entry passes desktop-file-validate with nothing to say; has Name,
           GenericName, a one-line Comment (the hover hint), Keywords, Categories, an Icon
           drawn at every size in theme/app-icons, TryExec, and X-Bromigos-Menu (the menu
           item it is) unless it's an app the menu has no row for; its package's PKGBUILD
           installs its folder; theme/app-icons is what build-app-icons.py draws
  exec     each Exec runs the right command: the program, run from this checkout exactly as
           the entry says, in a sandbox where a deck reaches a stand-in live-layer socket, a
           panel a stand-in widgets socket, and rofi, kitty and anything that could change the
           machine are stubs that only log. A GTK window (Settings, the theme switcher) is run
           with --help, since there's no display to open it on
  menu     bromigos-menu --json, with only these entries installed: none of them is listed
           again under LAUNCH, each X-Bromigos-Menu item appears once and carries the entry's
           icon, no group lists a label twice, and the menu's own entry isn't in it
  listing  what a launcher lists (Gio, as rofi drun reads them: TryExec honoured): every
           entry, with its icon found in the hicolor theme; the lab console only while its
           program is there

Nothing reaches a desktop: a throwaway HOME, runtime directory and data dirs, no display, no
D-Bus. tools/launcher/render.sh draws rofi's listing offscreen (a nested Hyprland nobody sees).
"""
import argparse
import configparser
import json
import os
import re
import shlex
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
ICONS = os.path.join(REPO, "theme", "app-icons")
SIZES = ("16x16", "24x24", "32x32", "scalable")
# the folders that hold entries, and the package that installs each
DIRS = {"core": "bromigos-core", "desktop": "bromigos-desktop", "live": "bromigos-live",
        "widgets": "bromigos-widgets", "homelab": "bromigos-homelab"}
REQUIRED = ("Name", "GenericName", "Comment", "Keywords", "Categories", "Icon", "TryExec", "Exec")
# apps the menu has no row for: they're listed under LAUNCH like any app
NO_MENU_ITEM = {"org.bromigos.PowerMenu", "org.bromigos.FieldNotes", "org.bromigos.DenTV"}
# installed paths -> this checkout (an entry naming a program by its absolute path)
INSTALLED = {
    "/usr/lib/bromigos/desktop/rofi/power-menu": "desktop/rofi/scripts/power-menu",
    "/usr/lib/bromigos/bin/bromigos-lab": "homelab/bin/bromigos-lab",
}
# the programs on PATH, as the packages install them
PROGRAMS = {
    "bromigos-tv-guide": "desktop/settings/bromigos-tv-guide",
    "bromigos-settings": "desktop/settings/bromigos-settings",
    "bromigos-theme-switcher": "desktop/bin/bromigos-theme-switcher",
    "bromigos-customize": "desktop/bin/bromigos-customize",
    "bromigos-keys": "desktop/bin/bromigos-keys",
    "bromigos-setup-keybindings": "desktop/bin/bromigos-setup-keybindings",
    "bromigos-menu": "desktop/bin/bromigos-menu",
    "bromigos-extensions": "desktop/bin/bromigos-extensions",
    "bromigos-live": "live/bin/bromigos-live",
    "bromigos-widgets": "widgets/bromigos-widgets",
}
# what running each entry's Exec must do: ("help", text in its --help) for a GTK window;
# ("live", command the live layer gets); ("widgets", datagram); ("ran", program, argv part)
EXPECT = {
    "org.bromigos.DenTV": ("help", "Den TV"),
    "org.bromigos.Settings": ("help", "bromigos settings"),
    "org.bromigos.ThemeSwitcher": ("help", "bromigos theme switcher"),
    "org.bromigos.Shortcuts": ("ran", "rofi", "-dmenu"),
    "org.bromigos.KeyList": ("ran", "rofi", "-dmenu"),
    "org.bromigos.Menu": ("ran", "rofi", "-show menu"),
    "org.bromigos.PowerMenu": ("ran", "rofi", "-dmenu"),
    "org.bromigos.Extensions": ("ran", "rofi", "-dmenu"),
    "org.bromigos.Update": ("ran", "kitty", "--hold --title bromigos update -e bromigos update"),
    "org.bromigos.Bluetooth": ("ran", "kitty", "--class bromigos-bluetooth --title Bluetooth -e bromigos bluetooth tui"),
    "org.bromigos.HoloDeck": ("live", "holodeck open"),
    "org.bromigos.DriftMap": ("live", "driftmap open"),
    "org.bromigos.Timeline": ("live", "timeline open"),
    "org.bromigos.Swarm": ("live", "deck swarm open"),
    "org.bromigos.Screensaver": ("live", "screensaver open"),
    "org.bromigos.Panels": ("widgets", "show all"),
    "org.bromigos.FieldNotes": ("widgets", "notes"),
    "org.bromigos.LabConsole": ("ran", "kitty", "--title bromigos lab -e bromigos lab"),
    "org.bromigos.LabDeck": ("live", "deck lab open"),
    "org.bromigos.OpsTheater": ("live", "deck ops open"),
    "org.bromigos.NetworkMap": ("live", "deck netmap open"),
    "org.bromigos.Mind": ("live", "deck mind open"),
}

fails = []


def ok(cond, what):
    print(("ok    " if cond else "FAIL  ") + what)
    if not cond:
        fails.append(what)
    return cond


def entries(only=None):
    """[(id, folder, path, parsed)] for every entry in this checkout."""
    out = []
    for d in DIRS:
        if only and d not in only:
            continue
        folder = os.path.join(REPO, d, "applications")
        for f in sorted(os.listdir(folder)) if os.path.isdir(folder) else []:
            if f.endswith(".desktop"):
                cp = configparser.ConfigParser(interpolation=None, strict=False)
                cp.optionxform = str
                cp.read(os.path.join(folder, f))
                out.append((f[:-8], d, os.path.join(folder, f), cp))
    return out


# ------------------------------------------------------------------ static
def static(es):
    print("== static")
    validate = shutil.which("desktop-file-validate")
    ok(bool(validate), "desktop-file-validate is installed (desktop-file-utils)")
    for eid, d, path, cp in es:
        e = cp["Desktop Entry"]
        if validate:
            r = subprocess.run([validate, path], capture_output=True, text=True)
            ok(r.returncode == 0 and not (r.stdout + r.stderr).strip(),
               f"{eid}: desktop-file-validate {(r.stdout + r.stderr).strip()}".rstrip())
        for k in REQUIRED:
            ok(bool(e.get(k, "").strip()), f"{eid}: {k}")
        ok(len(e.get("Comment", "")) <= 140 and "\n" not in e.get("Comment", ""), f"{eid}: a one-line Comment")
        ok(e.get("Keywords", "").endswith(";") and e.get("Keywords", "").count(";") >= 4, f"{eid}: Keywords")
        ok(e.get("Name") != e.get("GenericName") or eid == "org.bromigos.Screensaver", f"{eid}: GenericName says what kind of app")
        if eid not in NO_MENU_ITEM:
            ok(bool(e.get("X-Bromigos-Menu", "").strip()), f"{eid}: X-Bromigos-Menu (the menu item it is)")
        ok(eid in EXPECT, f"{eid}: has an Exec expectation in this checker")
        icon = e.get("Icon", "")
        ok(all(os.path.isfile(os.path.join(ICONS, s, "apps", icon + ".svg")) for s in SIZES),
           f"{eid}: icon {icon} drawn at {', '.join(SIZES)}")
        if e.get("StartupWMClass"):
            ok(e.get("StartupNotify") == "true" or eid == "org.bromigos.ThemeSwitcher", f"{eid}: a window with a class")
    for d, pkg in DIRS.items():
        if not any(x[1] == d for x in es):
            continue
        text = open(os.path.join(REPO, "packaging", pkg, "PKGBUILD")).read()
        ok(f"{d}/applications" in text and "usr/share/applications" in text, f"{pkg} installs {d}/applications")
    if any(x[1] == "core" for x in es):
        text = open(os.path.join(REPO, "packaging", "bromigos-core", "PKGBUILD")).read()
        ok("theme/app-icons" in text and "icons/hicolor" in text, "bromigos-core installs theme/app-icons into hicolor")
        r = subprocess.run([sys.executable, os.path.join(REPO, "theme", "tools", "build-app-icons.py"), "--check"],
                           capture_output=True, text=True)
        ok(r.returncode == 0, "theme/app-icons is what build-app-icons.py draws " + r.stdout.strip())


# ------------------------------------------------------------------ the sandbox
STUB = """#!/bin/sh
printf '%s\\n' "$(basename "$0") $*" >> "$SANDBOX_LOG"
cat >/dev/null 2>&1 </dev/null
exit {code}
"""
BROMIGOS = """#!/bin/sh
# the bromigos CLI as far as these entries reach it; nothing here updates, installs or reloads
printf '%s\\n' "bromigos $*" >> "$SANDBOX_LOG"
case "$1" in
  session) exit 0 ;;
  commands) cat "$SANDBOX/commands.json" ;;
  terminal) shift; exec "$REPO/bin/bromigos-terminal" "$@" ;;
  ext) case "$2" in list) echo '{{"list": {{"extensions": []}}}}' ;; search) echo '{{"results": []}}' ;; esac ;;
  *) exit 1 ;;
esac
"""


class Sandbox:
    def __init__(self):
        self.dir = tempfile.mkdtemp(prefix="bl-", dir="/tmp")       # short: socket paths fit
        self.bin, self.run, self.home = (os.path.join(self.dir, x) for x in ("bin", "run", "home"))
        self.log = os.path.join(self.dir, "log")
        for x in (self.bin, self.run, self.home):
            os.makedirs(x)
        os.chmod(self.run, 0o700)
        open(self.log, "w").close()
        for name in ("rofi", "notify-send", "hyprctl", "systemctl", "loginctl", "sudo", "pacman", "gio",
                     "xdg-open", "Hyprland"):
            self.write(name, STUB.format(code=1 if name == "rofi" else 0))
        self.write("kitty", STUB.format(code=0))
        self.write("bromigos", BROMIGOS)
        for name, rel in PROGRAMS.items():
            os.symlink(os.path.join(REPO, rel), os.path.join(self.bin, name))
        with open(os.path.join(self.dir, "commands.json"), "w") as f:
            json.dump(commands_json(), f)

    def write(self, name, text):
        p = os.path.join(self.bin, name)
        with open(p, "w") as f:
            f.write(text)
        os.chmod(p, 0o755)

    def env(self, **extra):
        e = {"HOME": self.home, "XDG_RUNTIME_DIR": self.run, "XDG_CONFIG_HOME": os.path.join(self.home, ".config"),
             "XDG_STATE_HOME": os.path.join(self.home, ".local/state"), "XDG_CACHE_HOME": os.path.join(self.home, ".cache"),
             "XDG_DATA_HOME": os.path.join(self.home, ".local/share"), "PATH": f"{self.bin}:/usr/bin:/bin",
             "LANG": "C.UTF-8", "SANDBOX": self.dir, "SANDBOX_LOG": self.log, "REPO": REPO,
             "PYTHONPATH": os.pathsep.join([os.path.join(REPO, "desktop", "lib"), os.path.join(REPO, "lib")]),
             "BROMIGOS_HOMELAB": os.path.join(REPO, "homelab"), "BROMIGOS_SHARE_DIR": REPO,
             "DBUS_SESSION_BUS_ADDRESS": "disabled:", "GDK_BACKEND": "wayland", "TERMINAL": "kitty",
             "HYPRLAND_INSTANCE_SIGNATURE": "none"}
        e.update(extra)
        return e

    def logged(self):
        with open(self.log) as f:
            return f.read().splitlines()

    def close(self):
        shutil.rmtree(self.dir, ignore_errors=True)


def commands_json():
    """`bromigos commands --json` for this checkout's executables (what the menu reads): each
    one's route and its # bromigos: header."""
    out = []
    for d in ("bin", "desktop/bin", "desktop/settings", "homelab/bin", "live/bin", "widgets"):
        for f in sorted(os.listdir(os.path.join(REPO, d))):
            p = os.path.join(REPO, d, f)
            if not f.startswith("bromigos-") or not os.path.isfile(p):
                continue
            head = {}
            with open(p, errors="replace") as fh:
                for _ in range(30):
                    line = fh.readline()
                    if line.startswith("# bromigos:"):
                        k, _, v = line[11:].strip().partition("=")
                        head[k] = v
            route = "bromigos " + " ".join(f[len("bromigos-"):].split("-", 1))
            out.append({"command": route, "route": route, "path": p, "summary": head.get("summary"),
                        "hidden": head.get("hidden") == "true"})
    return {"builtins": [], "commands": out}


class FakeLive:
    """The live layer's control socket: answers ping, records the rest."""

    def __init__(self, path):
        self.got = []
        self.s = socket.socket(socket.AF_UNIX)
        self.s.bind(path)
        self.s.listen(8)
        threading.Thread(target=self.loop, daemon=True).start()

    def loop(self):
        while True:
            try:
                c, _ = self.s.accept()
            except OSError:
                return
            with c:
                cmd = c.recv(65536).decode()
                if cmd != "ping":
                    self.got.append(cmd)
                c.sendall(b"pong" if cmd == "ping" else (cmd.replace("deck ", "")).encode())


class FakeWidgets:
    def __init__(self, path):
        self.got = []
        self.s = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
        self.s.bind(path)
        threading.Thread(target=self.loop, daemon=True).start()

    def loop(self):
        while True:
            try:
                b = self.s.recv(1024)
            except OSError:
                return
            if b.strip():
                self.got.append(b.decode())


def resolve(argv):
    a0 = argv[0]
    if a0 in INSTALLED:
        return [os.path.join(REPO, INSTALLED[a0])] + argv[1:]
    return argv


def execs(es):
    print("== exec")
    for eid, _, _, cp in es:
        e = cp["Desktop Entry"]
        want = EXPECT.get(eid)
        if not want:
            continue
        argv = resolve(shlex.split(e["Exec"]))
        if eid == "org.bromigos.LabConsole" and not os.path.exists(os.path.join(REPO, INSTALLED[e["TryExec"]])):
            print(f"skip  {eid}: no homelab/bin/bromigos-lab in this checkout")
            continue
        sb = Sandbox()
        live = FakeLive(os.path.join(sb.run, "bromigos-live.sock"))
        widgets = FakeWidgets(os.path.join(sb.run, "bromigos-widgets.sock"))
        if want[0] == "help":
            argv = argv + ["--help"]
        try:
            r = subprocess.run(argv, env=sb.env(), capture_output=True, text=True, timeout=60, cwd=sb.home)
            time.sleep(0.2)
            out, logged = r.stdout + r.stderr, sb.logged()
            if want[0] == "help":
                ok(r.returncode in (0, 1) and want[1] in out, f"{eid}: `{e['Exec']} --help` is {want[1]}'s")
            elif want[0] == "live":
                ok(live.got == [want[1]], f"{eid}: `{e['Exec']}` asks the live layer for {want[1]!r} (got {live.got})")
            elif want[0] == "widgets":
                ok(widgets.got == [want[1]], f"{eid}: `{e['Exec']}` asks the panels for {want[1]!r} (got {widgets.got})")
            else:
                prog, part = want[1], want[2]
                ran = [l for l in logged if l.split(" ", 1)[0] == prog]
                ok(any(part in l for l in ran), f"{eid}: `{e['Exec']}` runs {prog} … {part} "
                   f"(ran: {ran or logged or out.strip()[-200:]})")
            danger = [l for l in logged if l.split(" ", 1)[0] in ("systemctl", "loginctl", "sudo", "pacman")]
            ok(not danger, f"{eid}: nothing else ran ({danger})")
        finally:
            live.s.close()
            widgets.s.close()
            sb.close()


# ------------------------------------------------------------------ menu and listing
def stage(es, root, lab=True):
    """root/share: an XDG data dir with only these entries and icons, installed as the
    packages do. The absolute TryExec paths point into this checkout (lab=False: the lab's
    program absent). Also tools/launcher/render.py's."""
    data = os.path.join(root, "share")
    apps = os.path.join(data, "applications")
    os.makedirs(apps)
    for eid, _, path, _ in es:
        text = open(path).read()
        for inst, rel in INSTALLED.items():
            if "bromigos-lab" in inst and not lab:
                text = text.replace(inst, os.path.join(root, "absent", "bromigos-lab"))
            else:
                text = text.replace(inst, os.path.join(REPO, rel))
        with open(os.path.join(apps, eid + ".desktop"), "w") as f:
            f.write(text)
    shutil.copytree(ICONS, os.path.join(data, "icons", "hicolor"))
    return data


def menu(es):
    print("== menu")
    sb = Sandbox()
    try:
        data = stage(es, sb.dir)
        env = sb.env(XDG_DATA_DIRS=data)
        r = subprocess.run([os.path.join(REPO, "desktop", "bin", "bromigos-menu"), "--json"], env=env,
                           capture_output=True, text=True, timeout=120)
        if not ok(r.returncode == 0, "bromigos-menu --json " + r.stderr.strip()[-300:]):
            return
        tree = json.loads(r.stdout)
        ids = {}
        for g, items in tree.items():
            for it in items:
                ids.setdefault(it["id"], []).append(g)
        mine = {eid: cp["Desktop Entry"] for eid, _, _, cp in es}
        launch = [it["id"] for it in tree.get("launch", [])]
        for eid, e in mine.items():
            place = e.get("X-Bromigos-Menu", "").strip()
            if place == "-":
                ok(not any(eid in i for i in ids), f"{eid}: not in the menu (X-Bromigos-Menu=-)")
            elif place:
                ok(f"launch/{eid}.desktop" not in launch, f"{eid}: not listed again under LAUNCH")
                ok(len(ids.get(place, [])) == 1, f"{eid}: its item {place} appears once ({ids.get(place)})")
                item = next((it for g in tree.values() for it in g if it["id"] == place), {})
                ok(item.get("icon") == e["Icon"], f"{eid}: {place} carries its icon ({item.get('icon')})")
            else:
                ok(launch.count(f"launch/{eid}.desktop") == 1, f"{eid}: listed once under LAUNCH")
        for g, items in tree.items():
            if g in ("about",):
                continue
            labels = [it["label"].replace(" (current)", "").lower() for it in items]
            dup = sorted({l for l in labels if labels.count(l) > 1})
            ok(not dup, f"{g.upper()}: no label twice {dup or ''}".rstrip())
        many = sorted(i for i, gs in ids.items() if len(gs) > 1)
        ok(not many, f"no item id twice {many or ''}".rstrip())
        # the same thing reached from two groups (commands aside: that group lists every command)
        acts = {}
        for g, items in tree.items():
            if g in ("commands", "about"):
                continue
            for it in items:
                if it.get("action") and it["action"][0] in ("run", "hold", "term"):
                    acts.setdefault(json.dumps(it["action"]), []).append(it["id"])
        twice = {a: i for a, i in acts.items() if len(i) > 1}
        ok(not twice, f"no action reached from two items {list(twice.values()) or ''}".rstrip())
    finally:
        sb.close()


def listing(es, show=False):
    """What a launcher lists, read the way rofi's drun and the menu read entries (GIO)."""
    print("== listing")
    for lab in (True, False):
        sb = Sandbox()
        try:
            data = stage(es, sb.dir, lab=lab)
            code = r"""
import json, os, sys
import gi
from gi.repository import Gio
out = []
for a in Gio.AppInfo.get_all():
    if not a.should_show():
        continue
    icon = a.get_icon().to_string() if a.get_icon() else ""
    out.append({"id": a.get_id(), "name": a.get_name(), "generic": a.get_generic_name() or "",
                "icon": icon, "comment": a.get_description() or "", "keywords": a.get_keywords()})
print(json.dumps(sorted(out, key=lambda x: x["name"].lower())))
"""
            r = subprocess.run([sys.executable, "-c", code], env=sb.env(XDG_DATA_DIRS=data),
                               capture_output=True, text=True, timeout=60)
            if not ok(r.returncode == 0, "Gio reads the entries " + r.stderr.strip()[-300:]):
                return
            apps = json.loads(r.stdout)
            listed = {a["id"][:-8] for a in apps}
            want = {eid for eid, *_ in es} - (set() if lab else {"org.bromigos.LabConsole"})
            if lab:
                ok(listed == want, f"a launcher lists every entry ({len(listed)}/{len(want)}) {sorted(want ^ listed) or ''}".rstrip())
                for a in apps:
                    found = [s for s in SIZES if os.path.isfile(os.path.join(data, "icons", "hicolor", s, "apps", a["icon"] + ".svg"))]
                    ok(len(found) == len(SIZES), f"{a['name']}: icon {a['icon']} in hicolor at {', '.join(found)}")
                if show:
                    print()
                    print(f"{'NAME':<20} {'GENERIC NAME':<24} {'ICON':<22} COMMENT")
                    for a in apps:
                        print(f"{a['name']:<20} {a['generic']:<24} {a['icon']:<22} {a['comment']}")
                    print()
            else:
                ok("org.bromigos.LabConsole" not in listed, "without bromigos-lab the Lab Console isn't listed (TryExec)")
        finally:
            sb.close()


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--static", action="store_true")
    ap.add_argument("--only", action="append", choices=list(DIRS))
    ap.add_argument("--listing", action="store_true")
    a = ap.parse_args()
    es = entries(a.only)
    ok(bool(es), f"{len(es)} entries")
    if a.listing:
        listing(es, show=True)
        return 1 if fails else 0
    static(es)
    if not a.static:
        execs(es)
        menu(es)
        listing(es, show=True)
    print(f"\n{len(fails)} failed" if fails else "\nall passed")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
