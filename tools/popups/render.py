#!/usr/bin/env python3
"""Offscreen pictures of the bar's Bluetooth: its icon in each state, the panel and the
quick menu, in each theme asked for. Nothing appears on a screen and nothing touches the
machine's Bluetooth or desktop:

  - a sandbox HOME, whose theme is set with `bromigos theme set NAME --no-reload` (from
    this checkout's themes and templates: no hooks run, nothing running is told);
  - the stand-in bluez (desktop/tests/fake_bluez.py) on a private D-Bus, and the stand-in
    pactl (desktop/tests/fixtures/bin), so the devices are the fixtures' made-up ones;
  - a headless weston of its own for GTK to draw in.

  tools/bluetooth/render.py OUT_DIR [--themes wick,mire,tidewell,wick+hc] [--bromigos PATH]

A theme named NAME+hc is drawn with high contrast and reduced motion
(`bromigos accessibility contrast high --no-reload` and `motion reduced --no-reload`, in the
sandbox).

Writes OUT_DIR/<theme>-icons.png, -panel.png, -scan.png, -pair.png, -menu.png. Needs weston,
dbus-daemon, GTK 3 and 4, and gtk4-layer-shell's typelib (only its loader, nothing shown).
"""
import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DESKTOP = os.path.join(REPO, "desktop")
sys.path[:0] = [os.path.join(DESKTOP, "tests"), os.path.join(DESKTOP, "lib"), os.path.join(REPO, "lib")]

# the icon's states, as the module prints them (bromigos_bluez.bar), beside its neighbours
ICON_STATES = [
    ("off", {"text": " ", "class": ["off"]}),
    ("on", {"text": " ", "class": ["on"]}),
    ("one connected", {"text": "<span size='x-small' rise='4500'>1</span>", "class": ["connected", "c4"]}),
    ("two, controller low", {"text": "<span size='x-small' rise='4500'>2</span>", "class": ["connected", "c1", "low"]}),
    ("scanning", {"text": " ", "class": ["on", "busy"]}),
    ("bluetoothd down", {"text": " ", "class": ["off", "problem"]}),
]


def sandbox(tmp, theme, bromigos):
    """A HOME with `theme` set, from this checkout; its environment."""
    theme, _, a11y = theme.partition("+")
    home = os.path.join(tmp, "home-" + theme + ("-" + a11y if a11y else ""))
    share = os.path.join(tmp, "share")
    os.makedirs(home, exist_ok=True)
    if not os.path.isdir(share):
        os.makedirs(share)
        for n in os.listdir("/usr/share/bromigos") if os.path.isdir("/usr/share/bromigos") else []:
            if n not in ("theme", "themes", "hooks"):
                os.symlink(os.path.join("/usr/share/bromigos", n), os.path.join(share, n))
        os.symlink(os.path.join(REPO, "theme"), os.path.join(share, "theme"))
        os.symlink(os.path.join(REPO, "themes"), os.path.join(share, "themes"))
    run = os.path.join(tmp, "run")
    os.makedirs(run, exist_ok=True)
    os.chmod(run, 0o700)
    fx = os.path.join(tmp, "fixtures")
    os.makedirs(fx, exist_ok=True)
    env = {"HOME": home, "XDG_CONFIG_HOME": os.path.join(home, ".config"),
           "XDG_STATE_HOME": os.path.join(home, ".local", "state"), "XDG_DATA_HOME": os.path.join(home, ".local", "share"),
           "XDG_CACHE_HOME": os.path.join(home, ".cache"), "XDG_RUNTIME_DIR": run, "LANG": "C.UTF-8",
           "PATH": f"{DESKTOP}/tests/fixtures/bin:{DESKTOP}/bin:/usr/bin", "BROMIGOS_SHARE_DIR": share,
           "BROMIGOS_FIXTURE_STATE": fx, "PYTHONPATH": os.path.join(DESKTOP, "lib"),
           "DBUS_SESSION_BUS_ADDRESS": "disabled:", "GSK_RENDERER": "cairo", "GDK_DEBUG": "", "NO_AT_BRIDGE": "1",
           # no real hardware: the xpadneo check and the rfkill read look at an empty root
           "BROMIGOS_PERIPHERAL_ROOT": os.path.join(tmp, "root")}
    steps = [["theme", "set", theme, "--no-reload"]]
    if a11y == "hc":
        steps += [["accessibility", "motion", "reduced", "--no-reload"],
                  ["accessibility", "contrast", "high", "--no-reload"]]
    for argv in steps:
        r = subprocess.run([bromigos, *argv], env=env, capture_output=True, text=True, timeout=120)
        if r.returncode != 0:
            raise RuntimeError(f"{' '.join(argv)}: {r.stderr.strip()[-300:]}")
    return env


class Weston:
    def __init__(self, tmp):
        self.sock = "bt-render-" + str(os.getpid())
        run = os.path.join(tmp, "wrun")
        os.makedirs(run, exist_ok=True)
        os.chmod(run, 0o700)
        self.run = run
        self.p = subprocess.Popen(["weston", "--backend=headless", "--renderer=pixman", "--shell=kiosk", "--width=1600",
                                   "--height=1000", f"--socket={self.sock}", "--idle-time=0"],
                                  env=dict(os.environ, XDG_RUNTIME_DIR=run), stdout=subprocess.DEVNULL,
                                  stderr=subprocess.DEVNULL)
        for _ in range(100):
            if os.path.exists(os.path.join(run, self.sock)):
                return
            time.sleep(0.05)
        raise RuntimeError("weston didn't start")

    def env(self):
        return {"WAYLAND_DISPLAY": os.path.join(self.run, self.sock), "GDK_BACKEND": "wayland"}

    def close(self):
        self.p.terminate()
        self.p.wait(5)


ICON_CHILD = r"""
import json, os, sys
import gi
gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
from gi.repository import Gdk, GLib, Gtk
cur, style, out, states = sys.argv[1], sys.argv[2], sys.argv[3], json.loads(sys.argv[4])
css = os.path.join(os.path.dirname(out), "bt-bar.css")
with open(css, "w") as f:
    f.write(f'@import url("file://{cur}/waybar.css");\n@import url("file://{style}");\n'
            'label.cap { color: @soft; font-size: 11px; padding: 0 12px; }\n'
            '#waybar { background-color: @panel; border-bottom: 1px solid alpha(@dim, 0.55); }\n'
            '#page { background-color: @void; padding: 8px; }\n')
prov = Gtk.CssProvider()
prov.load_from_path(css)
Gtk.StyleContext.add_provider_for_screen(Gdk.Screen.get_default(), prov, Gtk.STYLE_PROVIDER_PRIORITY_USER)
win = Gtk.OffscreenWindow()
win.set_name("waybar")
win.get_style_context().add_class("top")
col = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
for cap, doc in states:
    row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
    inner = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
    inner.set_size_request(-1, 34)
    for name, text, classes in (("network", "LAN", []), ("custom-bluetooth", doc["text"], doc["class"]),
                                ("pulseaudio", "40%", [])):
        lab = Gtk.Label()
        lab.set_name(name)
        lab.set_markup(text)
        for c in classes:
            lab.get_style_context().add_class(c)
        inner.pack_start(lab, False, False, 0)
    inner.set_name("waybar")
    row.pack_start(inner, False, False, 0)
    c = Gtk.Label(label=cap)
    c.get_style_context().add_class("cap")
    row.pack_start(c, False, False, 0)
    col.pack_start(row, False, False, 0)
col.set_name("page")
win.add(col)
win.show_all()
n = {"n": 0}
def snap():
    n["n"] += 1
    if n["n"] < 4:
        return True
    win.get_surface().write_to_png(out)
    Gtk.main_quit()
    return False
GLib.timeout_add(150, snap)
Gtk.main()
"""


def icons(env, out):
    cur = os.path.join(env["XDG_STATE_HOME"], "bromigos", "theme", "current")
    r = subprocess.run([sys.executable, "-c", ICON_CHILD, cur, os.path.join(DESKTOP, "waybar", "style.css"), out,
                        json.dumps(ICON_STATES)], env=env, capture_output=True, text=True, timeout=60)
    if r.returncode != 0 or not os.path.exists(out):
        raise RuntimeError("the icon render failed: " + r.stderr[-400:])


PANEL_CHILD = r"""
import sys, json
import bromigos_btpanel as P
view, out, scan, prompt = sys.argv[1], sys.argv[2], sys.argv[3] == "1", json.loads(sys.argv[4])
print(P.render(out, view, scan=scan, prompt=tuple(prompt) if prompt else None))
"""


def panel(env, out, view="panel", scan=False, prompt=None):
    from fake_bluez import FakeBluez
    with FakeBluez(instant=True) as fb:
        e = dict(env, BROMIGOS_BLUEZ_BUS=fb.address)
        r = subprocess.run([sys.executable, "-c", PANEL_CHILD, view, out, "1" if scan else "0", json.dumps(prompt)],
                           env=e, capture_output=True, text=True, timeout=90)
    if r.returncode != 0 or not os.path.exists(out):
        raise RuntimeError(f"the {view} render failed: " + r.stderr[-600:])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("out")
    ap.add_argument("--themes", default="wick,mire,tidewell")
    ap.add_argument("--bromigos", default=shutil.which("bromigos") or "bromigos")
    ap.add_argument("--motion", choices=["full", "reduced"], default="full")
    o = ap.parse_args()
    os.makedirs(o.out, exist_ok=True)
    tmp = tempfile.mkdtemp(prefix="btr-", dir=os.environ.get("TMPDIR"))
    w = Weston(tmp)
    try:
        for theme in o.themes.split(","):
            env = sandbox(tmp, theme, o.bromigos)
            env.update(w.env())
            base = os.path.join(o.out, theme.replace("+", "-"))
            icons(env, base + "-icons.png")
            panel(env, base + "-panel.png")
            panel(env, base + "-scan.png", scan=True)
            panel(env, base + "-pair.png", scan=True, prompt=["confirm", "00:00:5E:00:53:21"])
            panel(env, base + "-menu.png", view="menu")
            print(f"{theme}: icons, panel, scan, pair, menu")
    finally:
        w.close()
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
