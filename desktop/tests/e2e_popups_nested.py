#!/usr/bin/env python3
"""The bar's popups and a click elsewhere, in a real waybar in a private nested session
(kwin_wayland --virtual hosting Hyprland: nothing appears on the screen, nothing reaches the
desktop it's run from).

The Bluetooth panel, its quick menu and the sound popup (pinned) are opened from the bar the
way a click on their icon opens them. For each it checks:

  - a click on another bar module closes the popup, and that module's own click still
    happens (the popup never eats it);
  - a click on the desktop (an empty spot, away from the bar) closes it, and the next
    click on the bar works at once;
  - Esc closes it;
  - a second click on its icon closes it (a toggle);
  - while it's open, the rest of the bar keeps working;
  - the hover popup (unpinned) never holds the keyboard.

The devices are the stand-ins' (fake_bluez.py, fixtures/bin's pactl and `bromigos sound`):
nothing touches the machine's Bluetooth or sound.

  python desktop/tests/e2e_popups_nested.py [--keep] [--only bt|menu|sound|hover]
Needs the nested harness's tools (e2e_keys_nested.py), waybar, dbus-daemon and GTK 4 with
gtk4-layer-shell.
"""
import json
import os
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from e2e_keys_nested import Nest, Run, wait_for  # noqa: E402
from e2e_game_nested import private_bus  # noqa: E402
from fake_bluez import FakeBluez  # noqa: E402
from vptr import LEFT, RIGHT, VirtualPointer  # noqa: E402

DESKTOP = HERE.parent
BT = DESKTOP / "bin" / "bromigos-bluetooth"
MOD = 120                                       # each test module's width on the bar


def layers(n):
    """The namespaces of every layer surface Hyprland has mapped, on every output."""
    try:
        doc = json.loads(n.ctl("layers", "-j") or "{}")
    except ValueError:
        return []
    out = []
    for mon in doc.values():
        for lvl in mon.get("levels", {}).values():
            out += [s.get("namespace") for s in lvl]
    return out


def is_open(n, ns):
    return ns in layers(n)


def main():
    keep = "--keep" in sys.argv
    only = sys.argv[sys.argv.index("--only") + 1] if "--only" in sys.argv else None
    n, r = Nest(keep), Run()
    pointer = None
    fb = FakeBluez()
    try:
        fb.__enter__()
        private_bus(n)
        n.start()
        clicks = Path(n.tmp, "clicks.log")
        py = sys.executable
        # the stand-ins for pactl and `bromigos sound` (not fixtures/bin's hyprctl: the real one
        # places the popups), then this checkout's commands
        bindir = Path(n.tmp, "bin")
        bindir.mkdir()
        for name in ("pactl", "bromigos"):
            (bindir / name).symlink_to(HERE / "fixtures" / "bin" / name)
        fx = Path(n.tmp, "fixtures")
        fx.mkdir()
        env = dict(n.env, BROMIGOS_BLUEZ_BUS=fb.address, BROMIGOS_FIXTURE_STATE=str(fx),
                   PATH=f"{bindir}:{DESKTOP / 'bin'}:{n.env['PATH']}", NO_AT_BRIDGE="1",
                   BROMIGOS_PERIPHERAL_ROOT=str(Path(n.tmp, "root")))
        cfg = {"layer": "bottom", "height": 34, "position": "top",
               "modules-left": ["custom/other"],
               "modules-right": ["custom/bt", "custom/sound"],
               "custom/other": {"format": "OTHER MODULE", "tooltip": False,
                                "on-click": f"sh -c 'echo other >> {clicks}'"},
               "custom/bt": {"format": "BLUETOOTH", "tooltip": False,
                             "on-click": f"{py} {BT} panel",
                             "on-click-right": f"{py} {BT} menu"},
               "custom/sound": {"format": "SOUND", "tooltip": False,
                                "on-click": f"{py} -c 'import sys; sys.path.insert(0, \"{DESKTOP / 'lib'}\"); "
                                            f"import bromigos_soundpopup as S; sys.exit(S.main([\"pin\"]))'"}}
        config = Path(n.tmp, "waybar.json")
        config.write_text(json.dumps(cfg))
        style = Path(n.tmp, "waybar.css")            # fixed widths: each module's place is known
        style.write_text("* { font-size: 12px; min-height: 0; padding: 0; margin: 0; }\n"
                         f"#custom-other, #custom-bt, #custom-sound {{ min-width: {MOD}px; }}\n")
        barlog = open(Path(n.tmp, "waybar.log"), "w")
        bar = subprocess.Popen(["/usr/bin/waybar", "-c", str(config), "-s", str(style)], env=env, stdout=barlog,
                               stderr=subprocess.STDOUT, start_new_session=True)
        n.procs.append(bar)
        r.check("waybar mapped", wait_for(lambda: n.layer("waybar")))
        mon = json.loads(n.ctl("monitors", "-j"))[0]
        W, H = round(mon["width"] / mon["scale"]), round(mon["height"] / mon["scale"])
        pointer = VirtualPointer(os.path.join(n.run, "wayland-1"), W, H)
        time.sleep(1.0)
        at = {"other": (MOD // 2, 17), "bt": (W - MOD - MOD // 2, 17), "sound": (W - MOD // 2, 17),
              "desktop": (MOD // 2, H - 40)}

        def clicked():
            return clicks.read_text().count("other") if clicks.exists() else 0

        def opened(ns, how):
            """Open the popup the way the bar does; True once it's mapped."""
            pointer.click(*how)
            return wait_for(lambda: is_open(n, ns), 15)

        cases = [("bt", "bromigos-bluetooth", (LEFT, at["bt"]), "the Bluetooth panel"),
                 ("menu", "bromigos-bluetooth", (RIGHT, at["bt"]), "the Bluetooth quick menu"),
                 ("sound", "bromigos-sound", (LEFT, at["sound"]), "the pinned sound popup")]
        for key, ns, how, name in cases:
            if only and key != only:
                continue
            # 1. a click on another bar module: closes it, and that module's click happens
            if not r.check(f"{name} opens", opened(ns, how), layers(n)):
                continue
            time.sleep(0.6)
            r.check(f"{name}: the clear surface that sees a click elsewhere is up, over the bar",
                    is_open(n, ns + "-outside"), layers(n))
            before = clicked()
            pointer.click(LEFT, at["other"])
            r.check(f"{name}: a click on another bar module closes it",
                    wait_for(lambda: not is_open(n, ns), 4), layers(n))
            r.check(f"{name}: that module's own click still happens",
                    wait_for(lambda: clicked() > before, 3), clicked())
            # 2. a click on the desktop closes it; the next click on the bar works
            r.check(f"{name} opens again", opened(ns, how), layers(n))
            time.sleep(0.6)
            pointer.click(LEFT, at["desktop"])
            r.check(f"{name}: a click on the desktop closes it",
                    wait_for(lambda: not is_open(n, ns), 4), layers(n))
            before = clicked()
            pointer.click(LEFT, at["other"])
            r.check(f"{name}: the next click on the bar works", wait_for(lambda: clicked() > before, 3))
            # 3. Esc
            r.check(f"{name} opens for Esc", opened(ns, how), layers(n))
            time.sleep(0.6)
            n.kb.tap("ESCAPE")
            r.check(f"{name}: Esc closes it", wait_for(lambda: not is_open(n, ns), 4), layers(n))
            # 4. its icon again
            r.check(f"{name} opens for the toggle", opened(ns, how), layers(n))
            time.sleep(0.6)
            pointer.click(*how)
            r.check(f"{name}: a second click on its icon closes it",
                    wait_for(lambda: not is_open(n, ns), 4), layers(n))
            time.sleep(0.4)
            r.check(f"{name}: and stays closed", not is_open(n, ns), layers(n))
            r.check(f"{name}: nothing of it is left over the screen", not is_open(n, ns + "-outside"), layers(n))

        # 5. the sound popup on hover (as bromigos-hover asks): nothing over the bar, the
        # bar's clicks go where they go
        if not only or only == "hover":
            sound = Path(n.tmp, "sound-hover.py")
            sound.write_text(f"import sys; sys.path.insert(0, {str(DESKTOP / 'lib')!r}); "
                             "import bromigos_soundpopup as S; sys.exit(S.main(sys.argv[1:]))")
            pointer.arrive(*at["sound"])
            subprocess.Popen([py, str(sound), "hover", str(at["sound"][0])], env=env, stdout=subprocess.DEVNULL,
                             stderr=subprocess.DEVNULL, start_new_session=True)
            r.check("the sound popup opens on hover", wait_for(lambda: is_open(n, "bromigos-sound"), 15), layers(n))
            time.sleep(0.4)
            r.check("the hover popup puts nothing over the screen", not is_open(n, "bromigos-sound-outside"), layers(n))
            before = clicked()
            pointer.click(LEFT, at["other"])
            r.check("with the hover popup open, a click on another module works",
                    wait_for(lambda: clicked() > before, 3), clicked())
    finally:
        if pointer:
            pointer.close()
        n.stop()
        fb.__exit__()
        if keep:
            print("kept:", n.tmp)
    return int(any(not ok for _, ok, _ in r.results))


if __name__ == "__main__":
    sys.exit(main())
