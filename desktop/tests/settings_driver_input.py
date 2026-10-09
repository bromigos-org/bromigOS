"""settings_driver.py's Keyboard & input scenario, in the nested Hyprland: the repeat rate
dragged on the page is Hyprland's live option a moment later (one verified reload); Caps
Lock as Escape lands in its kb_options; the toast's Undo and Reset to defaults put
bromigOS's values back; the block in hyprland.lua comes and goes with them."""
import json
import os
import subprocess

LUA = os.path.join(os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config"), "hypr", "hyprland.lua")


def option(name):
    try:
        out = subprocess.run(["hyprctl", "getoption", name, "-j"], capture_output=True, text=True, timeout=10).stdout
        d = json.loads(out or "{}")
        return d.get("int", d.get("str", d.get("float")))
    except (OSError, ValueError, subprocess.SubprocessError):
        return None


def block():
    try:
        with open(LUA) as f:
            lua = f.read()
    except FileNotFoundError:
        return ""
    b, e = lua.find("-- >>> bromigos setup input"), lua.find("-- <<< bromigos setup input")
    return lua[b:e] if b >= 0 and e > b else ""


def steps(d):
    page = d.win.built["input"]._input

    def caps(value):
        page.caps.set_selected(page.caps._values.index(value))
    return [
        ("Keyboard: bromigOS's repeat rate is live (50 a second)", lambda: None,
         lambda: (option("input:repeat_rate") == 50, option("input:repeat_rate")), 0.2),
        ("Keyboard: the repeat-rate slider dragged to 30: Hyprland repeats 30 a second",
         lambda: page.rate.scale.set_value(30),
         lambda: (option("input:repeat_rate") == 30 and "repeat_rate = 30" in block(),
                  (option("input:repeat_rate"), block()[-200:])), 2.5),
        ("Keyboard: the toast's Undo: 50 again",
         d.last_undo, lambda: (option("input:repeat_rate") == 50, option("input:repeat_rate")), 2.0),
        ("Keyboard: Caps Lock as Escape: kb_options caps:escape, live",
         lambda: caps("caps:escape"),
         lambda: (option("input:kb_options") == "caps:escape", option("input:kb_options")), 2.0),
        ("Keyboard: the delay dragged to 400 ms: live",
         lambda: page.delay.scale.set_value(400),
         lambda: (option("input:repeat_delay") == 400, option("input:repeat_delay")), 2.5),
        ("Keyboard: Reset to defaults: bromigOS's values live, the block gone",
         page.reset,
         lambda: (option("input:repeat_rate") == 50 and option("input:repeat_delay") == 240 and
                  option("input:kb_options") in (None, "", "[[EMPTY]]") and "repeat_rate" not in block(),
                  (option("input:repeat_rate"), option("input:repeat_delay"), option("input:kb_options"),
                   block()[-200:])), 2.5),
    ]
