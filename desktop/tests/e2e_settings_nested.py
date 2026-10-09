#!/usr/bin/env python3
"""End to end: Settings' Displays, Sound, Keyboard & input and VECTOR pages in a nested
Hyprland nobody sees, with a PipeWire nobody hears.

The nested Hyprland is e2e_keys_nested.py's (kwin_wayland --virtual hosting it, a runtime
directory, HOME and D-Bus of its own, the template user config over this checkout's
defaults); the sound server is sandbox_audio.py's (no device monitors, no D-Bus: two null
sinks, a remapped microphone, an app playing silence) in the same runtime directory. The
live layer and VECTOR are stand-ins, so `bromigos mute` and the cues touch only files in
the sandbox. Nothing reaches the desktop it runs from: no window, no reload, no sound
device, no session socket.

Each page is driven as a user would (settings_driver.py: its own dropdowns, sliders,
switches and buttons) and checked where the change lands:

  - Displays: a headless output made in the nested Hyprland; its scale changed and
    applied: the "Keep these settings?" countdown left to run out reverts it by itself;
    applied again and kept, it stays; the block in hyprland.lua; Reset;
  - Sound: the output device picked (the playing app follows), the toast's Undo, a
    volume dragged, Ctrl+Z, mute, an app's own volume, the theme's cues;
  - Keyboard & input: key repeat dragged and checked in Hyprland's live options, Caps Lock
    as Escape, Reset to defaults;
  - VECTOR: the emergency switch flipped off (bromigos-holo off, at once), flipped on (only
    a dialog: Enter and Cancel leave him off, "Turn him on" runs bromigos-holo on), against
    the fixtures' stand-in bromigos-holo; and the emergency switch's key (SUPER+CTRL+ESCAPE)
    in the nested Hyprland's live binds, running the switch's toggle.

Not part of `unittest discover` (it needs kwin_wayland, Hyprland, PipeWire, WirePlumber):

    python3 desktop/tests/e2e_settings_nested.py [--keep] [--only sound,displays,input,vector]
"""
import os
import shutil
import signal
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from e2e_keys_nested import DESKTOP, REPO, Nest, Run  # noqa: E402
from sandbox_audio import AudioSandbox  # noqa: E402

# the commands the pages run, from this checkout
COMMANDS = ["bromigos-sound", "bromigos-scene", "bromigos-display", "bromigos-setup-input", "bromigos-keys",
            "bromigos-setup-config"]
# the live layer and VECTOR: stand-ins that keep their mute in a file (bromigos mute calls them)
STANDINS = {
    "live-standin": '#!/bin/sh\n# bromigos-live, pretended: mute only\nf="$HOME/.live-muted"\n'
                    'case "$1 $2" in "mute on") touch "$f"; echo muted;; "mute off") rm -f "$f"; echo unmuted;;\n'
                    '"mute status") [ -e "$f" ] && echo muted || echo unmuted;; *) exit 0;; esac\n',
    "holo-standin": '#!/bin/sh\n# bromigos-holo, pretended: mute only\nf="$HOME/.vector-muted"\n'
                    'case "$1 $2" in "mute on") touch "$f"; echo muted;; "mute off") rm -f "$f"; echo unmuted;;\n'
                    '"mute status") [ -e "$f" ] && echo muted || echo unmuted;; *) exit 0;; esac\n',
}


def driver(n, audio, scenario, r, timeout=180, extra=None):
    env = dict(n.env, **(extra or {}))
    env = dict(env, PYTHONPATH=os.pathsep.join([os.path.join(DESKTOP, "lib"), os.path.join(REPO, "lib"), HERE]),
               PIPEWIRE_RUNTIME_DIR=audio.run_dir if audio else n.run,
               PULSE_RUNTIME_PATH=os.path.join(n.run, "pulse"),
               BROMIGOS_LIVE_BIN=os.path.join(n.stubs, "live-standin"),
               BROMIGOS_HOLO_BIN=os.path.join(n.stubs, "holo-standin"),
               BROMIGOS_SETTINGS_DEBUG=os.environ.get("BROMIGOS_SETTINGS_DEBUG", ""))
    p = subprocess.Popen([sys.executable, os.path.join(HERE, "settings_driver.py"), os.path.join(DESKTOP, "settings"),
                          scenario], env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                         start_new_session=True)
    n.procs.append(p)
    # the driver's KEYS lines are typed into the nested Hyprland, the rest collected
    import threading
    import time
    lines = []
    timer = threading.Timer(timeout, lambda: os.killpg(p.pid, signal.SIGKILL))
    timer.start()
    try:
        for ln in p.stdout:
            ln = ln.rstrip("\n")
            if ln.startswith("KEYS "):
                verb, _, arg = ln[5:].partition(" ")
                time.sleep(0.25)
                {"type": n.kb.type, "tap": n.kb.tap, "combo": n.kb.combo}[verb](arg)
                continue
            lines.append(ln)
        p.wait()
    finally:
        timer.cancel()
    out, err = "\n".join(lines), p.stderr.read()
    steps = [ln for ln in out.splitlines() if ln.startswith(("PASS", "FAIL"))]
    for ln in steps:
        name, _, detail = ln.split(" ", 1)[1].partition(" | ")
        r.check(name, ln.startswith("PASS"), detail)
    r.check(f"{scenario}: the driver ended by itself (every step ran)", bool(steps) and p.returncode in (0, 1),
            (p.returncode, out[-600:], err[-1500:]))
    if os.environ.get("BROMIGOS_SETTINGS_DEBUG"):
        print("\n".join(ln for ln in err.splitlines() if ln.startswith("settings:"))[-3000:])
    return env


def main():
    keep = "--keep" in sys.argv
    only = sys.argv[sys.argv.index("--only") + 1].split(",") if "--only" in sys.argv else \
        ["displays", "sound", "input", "vector"]
    for tool in ("kwin_wayland", "dbus-run-session", "Hyprland", "lua", "pipewire", "wireplumber", "pipewire-pulse",
                 "pactl", "pacat"):
        if not shutil.which(tool):
            print(f"SKIP: needs {tool}")
            return 0
    n = Nest(keep)
    for name in COMMANDS:
        src = os.path.join(DESKTOP, "bin", name)
        dst = os.path.join(n.stubs, name)
        if os.path.exists(src) and not os.path.lexists(dst):
            os.symlink(src, dst)
    for name, text in STANDINS.items():
        p = os.path.join(n.stubs, name)
        with open(p, "w") as f:
            f.write(text)
        os.chmod(p, 0o755)
    r = Run()
    audio = None
    try:
        n.start()
        if "sound" in only:
            audio = AudioSandbox(keep=keep, run_dir=n.run, home=n.home)
            audio.env.update({"PATH": f"{n.stubs}:/usr/bin"})
            audio.start()
            audio.sink("speakers", "Desk speakers")
            audio.sink("headphones", "USB headphones")
            audio.source("mic", "Desk microphone", "speakers")
            audio.pactl("set-default-sink", "speakers")
            audio.app("Music Player", sink="speakers")
            driver(n, audio, "sound", r)
            driver(n, audio, "keys", r)
        if "displays" in only:
            import json
            import time

            def names():
                try:
                    return {m["name"] for m in json.loads(n.ctl("monitors", "all", "-j") or "[]")}
                except ValueError:
                    return set()
            before = names()
            n.ctl("output", "create", "wayland")      # a second window in kwin: a real output (headless ones stay 0x0 here)
            new = None
            for _ in range(50):
                new = next(iter(names() - before), None)
                if new:
                    break
                time.sleep(0.1)
            if new:      # sized as a 1080p monitor
                n.ctl("eval", f'hl.monitor({{ output = "{new}", mode = "1920x1080@60", position = "auto", scale = 1 }})')

                def sized():
                    m = next((m for m in json.loads(n.ctl("monitors", "all", "-j") or "[]") if m["name"] == new), {})
                    return m.get("width", 0) > 0
                for _ in range(50):
                    if sized():
                        break
                    time.sleep(0.1)
            r.check("displays: a second output made in the nested Hyprland, 1920x1080", new is not None and sized(),
                    n.ctl("monitors", "all"))
            if new:      # as a user's monitors would be: pinned in hyprland.lua (no trial)
                env = dict(n.env, PYTHONPATH=os.path.join(DESKTOP, "lib"))
                pin = subprocess.run(["bromigos", "display", "apply", "--output", new, "--mode", "1920x1080@60",
                                      "--scale", "1", "--confirm", "0", "--json"], env=env, capture_output=True,
                                     text=True, timeout=60)
                r.check("displays: the outputs pinned at 1x first (bromigos display apply --confirm 0)",
                        '"ok": true' in pin.stdout, (pin.stdout[-300:], pin.stderr[-300:]))
            if new:
                driver(n, None, "displays", r, timeout=300, extra={"BROMIGOS_TEST_OUTPUT": new})
        if "input" in only:
            driver(n, None, "input", r)
        if "vector" in only:
            # the page's bromigos-holo: the fixtures' stand-in (markers in this sandbox, every call logged),
            # never the installed VECTOR
            holo = os.path.join(n.stubs, "bromigos-holo")
            if not os.path.lexists(holo):
                os.symlink(os.path.join(HERE, "fixtures", "bin", "bromigos-holo"), holo)
            state = os.path.join(n.tmp, "fixture-state")
            os.makedirs(state, exist_ok=True)
            driver(n, None, "vector", r, extra={"BROMIGOS_FIXTURE_STATE": state})
            import json
            binds = json.loads(n.ctl("binds", "-j") or "[]")
            want = [b for b in binds if "switch toggle --from=key" in (b.get("description") or "")]
            r.check("VECTOR: SUPER+CTRL+ESCAPE is bound in the live Hyprland to the switch's toggle",
                    len(want) == 1 and want[0].get("modmask") == 64 | 4 and want[0].get("key", "").lower() == "escape",
                    want or [b.get("description") for b in binds if "holo" in (b.get("description") or "")][:6])
            same = [b for b in binds if b.get("modmask") == 64 | 4 and (b.get("key") or "").lower() == "escape"]
            r.check("VECTOR: nothing else is bound to SUPER+CTRL+ESCAPE", len(same) == 1, same)
        r.check("no config errors at the end", n.ctl("configerrors").strip() == "", n.ctl("configerrors"))
    finally:
        if audio is not None:
            audio.stop()
        n.stop()
        if keep:
            print(f"kept: {n.tmp}")
    failed = [x for x in r.results if not x[1]]
    print(f"\n{len(r.results) - len(failed)}/{len(r.results)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
