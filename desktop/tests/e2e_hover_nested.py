#!/usr/bin/env python3
"""The bar's hover module (waybar/hover/bromigos-hover.c) in a real waybar, in a private
nested session (kwin_wayland --virtual hosting Hyprland: nothing appears on the screen).

A stand-in popup app (a GApplication with "hover" and "leave" actions, like
bromigos_soundpopup) records what it's asked. A virtual pointer:
  - passes over the target quickly: no hover (the open delay);
  - rests on it: one "hover", with the target's centre on the screen;
  - leaves: one "leave".
With the app not running, a rest on the target runs the module's "command" instead.

  python desktop/tests/e2e_hover_nested.py [--keep] [--so PATH]   (builds the module unless --so)
Needs the nested harness's tools (e2e_keys_nested.py), waybar, cc and gtk3's headers.
"""
import json
import os
import subprocess
import sys
import time
from pathlib import Path

from e2e_keys_nested import Nest, Run, wait_for
from e2e_game_nested import private_bus
from vptr import VirtualPointer

HERE = Path(__file__).resolve().parent
SRC = HERE.parent / "waybar" / "hover" / "bromigos-hover.c"

APP = r'''import sys, gi
from pathlib import Path
from gi.repository import Gio, GLib
log = Path(sys.argv[1])
def say(t):
    with log.open("a") as f: f.write(t + "\n")
app = Gio.Application(application_id="org.bromigos.HoverTest", flags=Gio.ApplicationFlags.FLAGS_NONE)
def startup(a):
    h = Gio.SimpleAction.new("hover", GLib.VariantType.new("i"))
    h.connect("activate", lambda a_, v: say(f"hover {v.get_int32()}"))
    l = Gio.SimpleAction.new("leave", None)
    l.connect("activate", lambda *_: say("leave"))
    a.add_action(h); a.add_action(l)
app.connect("startup", startup)
app.connect("activate", lambda a: (a.hold(), say("ready")))
app.run([sys.argv[0]])
'''


def build(out):
    flags = subprocess.run(["pkg-config", "--cflags", "--libs", "gtk+-3.0"], capture_output=True, text=True,
                           check=True).stdout.split()
    subprocess.run(["cc", "-Wall", "-Wextra", "-Wno-unused-parameter", "-Werror", "-shared", "-fPIC", "-o", out,
                    str(SRC), *flags], check=True)


def main():
    keep = "--keep" in sys.argv
    n, r = Nest(keep), Run()
    pointer = None
    try:
        private_bus(n)
        n.start()
        so = sys.argv[sys.argv.index("--so") + 1] if "--so" in sys.argv else str(Path(n.tmp, "bromigos-hover.so"))
        if "--so" not in sys.argv:
            build(so)
        log = Path(n.tmp, "app.log")
        marker = Path(n.tmp, "spawned.log")
        cfg = {"layer": "top", "height": 34, "modules-right": ["custom/target", "cffi/hover"],
               "custom/target": {"format": "TARGET MODULE", "tooltip": False},
               "cffi/hover": {"module_path": so, "target": "custom-target", "app": "org.bromigos.HoverTest",
                              "command": f"sh -c 'echo \"$0 $1\" >> {marker}'", "open-delay": 350}}
        config = Path(n.tmp, "waybar.json")
        config.write_text(json.dumps(cfg))
        barlog = open(Path(n.tmp, "waybar.log"), "w")
        benv = dict(n.env, **{k: v for k, v in os.environ.items() if k == "BROMIGOS_HOVER_DEBUG"})
        bar = subprocess.Popen(["/usr/bin/waybar", "-c", str(config), "-l", "debug"], env=benv, stdout=barlog,
                               stderr=subprocess.STDOUT, start_new_session=True)
        n.procs.append(bar)
        r.check("waybar mapped", wait_for(lambda: n.layer("waybar")))
        mon = json.loads(n.ctl("monitors", "-j"))[0]
        size = (round(mon["width"] / mon["scale"]), round(mon["height"] / mon["scale"]))
        pointer = VirtualPointer(os.path.join(n.run, "wayland-1"), *size)
        # the target is the right-most module but the empty hover one: about 100 px from the edge
        tx = size[0] - 70

        # 1. the app isn't running: a rest runs the command, with "hover X"
        time.sleep(1.0)                                   # the module finds its target
        pointer.arrive(size[0] // 2, size[1] // 2)
        pointer.arrive(tx, 17)
        time.sleep(0.8)
        r.check("not running: a rest runs the command with hover X",
                wait_for(lambda: marker.exists() and marker.read_text().startswith("hover ")),
                marker.read_text() if marker.exists() else "nothing")
        pointer.arrive(size[0] // 2, size[1] // 2)

        app = subprocess.Popen([sys.executable, "-c", APP, str(log)], env=n.env, stdout=subprocess.DEVNULL,
                               stderr=subprocess.DEVNULL, start_new_session=True)
        n.procs.append(app)
        r.check("the stand-in app is up", wait_for(lambda: log.exists() and "ready" in log.read_text()))

        # 2. passing over quickly: nothing
        pointer.move(tx, 17)
        time.sleep(0.12)
        pointer.move(size[0] // 2, size[1] // 2)
        time.sleep(0.6)
        r.check("a quick pass asks nothing", "hover" not in log.read_text(), log.read_text())

        # 3. a rest: hover with the target's centre; leaving: leave
        pointer.arrive(tx, 17)
        got = wait_for(lambda: next((ln for ln in log.read_text().splitlines() if ln.startswith("hover ")), None), 3)
        r.check("a rest asks for hover", got, log.read_text())
        if got:
            x = int(got.split()[1])
            r.check("hover gives the target's centre", size[0] - 160 < x < size[0], got)
        pointer.arrive(size[0] // 2, size[1] // 2)
        r.check("leaving asks for leave", wait_for(lambda: "leave" in log.read_text(), 3), log.read_text())
        lines = log.read_text().splitlines()
        r.check("one hover and one leave", lines.count("leave") == 1 and
                sum(ln.startswith("hover") for ln in lines) == 1, lines)
    finally:
        if pointer:
            pointer.close()
        n.stop()
        if keep:
            print("kept:", n.tmp)
    return int(any(not ok for _, ok, _ in r.results))


if __name__ == "__main__":
    sys.exit(main())
