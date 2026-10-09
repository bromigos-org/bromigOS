#!/usr/bin/env python3
"""rofi's app launcher (Alt+P: `rofi -show drun`) listing bromigOS's entries, drawn offscreen.

  python3 tools/launcher/render.py OUTDIR [--filter TEXT]… [--keep]

A nested Hyprland nobody sees (kwin_wayland --virtual hosts it: the harness of
desktop/tests/e2e_keys_nested.py, with a HOME, runtime directory and D-Bus of its own), the
Wick theme rendered by this checkout's `bromigos` (core/target/debug; build it first), and
only this checkout's entries and icons installed (an XDG data dir of their own, as the
packages lay them out). rofi runs with this checkout's launcher config and theme; grim
saves the nested output:

  OUTDIR/drun.png             every entry (no filter)
  OUTDIR/drun-<filter>.png    what typing <filter> leaves (default: theme, settings, deck,
                              lab: Keywords at work)

Then the launcher's own commands, started from nothing: `bromigos-widgets show all` with no
panels running starts them (OUTDIR/panels.png). Nothing reaches the desktop it runs from: no
window, no screenshot of it. Needs kwin_wayland, Hyprland, rofi, grim and a GPU.
"""
import argparse
import os
import shutil
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(REPO, "desktop", "tests"))
import check  # noqa: E402
from e2e_keys_nested import Nest, wait_for  # noqa: E402


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("out")
    ap.add_argument("--filter", action="append")
    ap.add_argument("--keep", action="store_true")
    a = ap.parse_args()
    out = os.path.abspath(a.out)
    os.makedirs(out, exist_ok=True)
    bromigos = os.path.join(REPO, "core", "target", "debug", "bromigos")
    if not os.access(bromigos, os.X_OK):
        sys.exit(f"render: no {bromigos} (cargo build -p bromigos in core/)")
    nest = Nest(keep=a.keep)
    fails = 0
    try:
        # the theme first, before any compositor runs: `bromigos theme set` finds no session
        env = dict(nest.base, PATH=f"{nest.stubs}:/usr/bin", BROMIGOS_SHARE_DIR=REPO)
        r = subprocess.run([bromigos, "theme", "set", "wick", "--no-reload"], env=env, capture_output=True, text=True)
        if r.returncode != 0:
            sys.exit("render: bromigos theme set wick: " + r.stderr.strip()[-400:])
        data = check.stage(check.entries(), nest.tmp)
        conf = os.path.join(nest.tmp, "rofi.rasi")
        with open(os.path.join(REPO, "desktop", "rofi", "config.rasi")) as f:
            text = f.read().replace("/usr/share/bromigos/default/rofi/bromigos.rasi",
                                    os.path.join(REPO, "desktop", "rofi", "bromigos.rasi"))
        with open(conf, "w") as f:
            f.write(text)
        # hicolor's index (hicolor-icon-theme's on an install): without it no icon theme is found;
        # and what reads an SVG finds its loaders and the file types through XDG_DATA_DIRS
        # (glycin-loaders, mime), which here holds nothing but the entries
        if os.path.isfile("/usr/share/icons/hicolor/index.theme"):
            shutil.copy("/usr/share/icons/hicolor/index.theme", os.path.join(data, "icons", "hicolor", "index.theme"))
        for d in ("glycin-loaders", "mime"):
            if os.path.isdir(os.path.join("/usr/share", d)):
                os.symlink(os.path.join("/usr/share", d), os.path.join(data, d))
        # the programs the entries name, as installed (TryExec must find them); the nest's own
        # stubs (the live layer, the panels: its autostart) stay stubs
        for name, rel in check.PROGRAMS.items():
            dst = os.path.join(nest.stubs, name)
            if not os.path.lexists(dst):
                os.symlink(os.path.join(REPO, rel), dst)
        with open(nest.lua, "a") as f:            # a test run: no start-hyprland banner
            f.write("\nhl.config({ misc = { disable_watchdog_warning = true } })\n")
        nest.start()
        # the nested output at 1x (no EDID: Hyprland guesses 2x), the size kwin gives it
        nest.ctl("eval", 'hl.monitor({ output = "WAYLAND-1", mode = "1600x900", position = "0x0", scale = 1 })')
        time.sleep(0.8)
        env = dict(nest.env, XDG_DATA_DIRS=data, XDG_DATA_HOME=os.path.join(nest.tmp, "nodata"),
                   PYTHONPATH=os.pathsep.join([os.path.join(REPO, "desktop", "lib"), os.path.join(REPO, "lib")]))

        def shot(name):
            path = os.path.join(out, name)
            r = subprocess.run(["grim", path], env=env, capture_output=True, text=True, timeout=20)
            if r.returncode != 0:
                print(f"FAIL  grim {name}: {r.stderr.strip()}")
                return False
            print(f"ok    {path}")
            return True

        for flt in [None] + (a.filter or ["theme", "settings", "deck", "lab"]):
            cmd = ["rofi", "-show", "drun", "-config", conf, "-theme-str",
                   "window { width: 1180px; } listview { columns: 2; lines: 11; } element-icon { size: 1.6em; }"]
            if flt:
                cmd += ["-filter", flt]
            p = subprocess.Popen(cmd, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True,
                                 start_new_session=True)
            nest.procs.append(p)
            if not wait_for(lambda: nest.layer("rofi"), 10):
                print(f"FAIL  rofi didn't show ({flt}): {p.stderr.read()[-300:] if p.poll() is not None else ''}")
                fails += 1
                continue
            time.sleep(1.2)                          # icons load after the first frame
            fails += not shot(f"drun-{flt}.png" if flt else "drun.png")
            p.terminate()
            wait_for(lambda: not nest.layer("rofi"), 5)

        # the Desktop Panels entry with no panels running: they start, and show
        os.unlink(os.path.join(nest.stubs, "bromigos-widgets"))
        os.symlink(os.path.join(REPO, "widgets", "bromigos-widgets"), os.path.join(nest.stubs, "bromigos-widgets"))
        r = subprocess.run(["bromigos-widgets", "show", "all"], env=env, capture_output=True, text=True, timeout=30)
        up = wait_for(lambda: nest.layer("bromigos-widgets"), 15)
        print(("ok    " if r.returncode == 0 and up else "FAIL  ")
              + f"`bromigos-widgets show all` with no panels running started them ({r.stderr.strip()[-200:]})")
        fails += not (r.returncode == 0 and up)
        if up:
            time.sleep(2)
            fails += not shot("panels.png")
    finally:
        nest.stop()
        stray(nest.run)
    return fails


def stray(run):
    """Anything still running that was started in the nest (the panels the test started
    detach into a session of their own): stopped, by its runtime directory."""
    import signal
    for pid in filter(str.isdigit, os.listdir("/proc")):
        try:
            with open(f"/proc/{pid}/environ", "rb") as f:
                env = f.read().split(b"\0")
        except OSError:
            continue
        if f"XDG_RUNTIME_DIR={run}".encode() in env:
            try:
                os.kill(int(pid), signal.SIGTERM)
            except OSError:
                pass


if __name__ == "__main__":
    sys.exit(main())
