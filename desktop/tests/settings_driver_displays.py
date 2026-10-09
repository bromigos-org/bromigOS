"""settings_driver.py's Displays scenario, in the nested Hyprland: the harness made a
second output (BROMIGOS_TEST_OUTPUT); the page picks it, stages a scale, and Apply
changes it in the live compositor; the "Keep these display settings?" countdown left alone
reverts it by itself; applied again and kept (the dialog's own Keep button), it stays and
the block in hyprland.lua says so; Reset to defaults, kept, removes the block."""
import json
import os
import subprocess

from gi.repository import Gtk

OUT = os.environ.get("BROMIGOS_TEST_OUTPUT", "HEADLESS-2")
LUA = os.path.join(os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config"), "hypr", "hyprland.lua")


def monitor():
    try:
        out = subprocess.run(["hyprctl", "monitors", "all", "-j"], capture_output=True, text=True, timeout=10).stdout
        return next((m for m in json.loads(out or "[]") if m["name"] == OUT), {})
    except (OSError, ValueError, subprocess.SubprocessError):
        return {}


def block():
    try:
        with open(LUA) as f:
            lua = f.read()
    except FileNotFoundError:
        return ""
    b = lua.find("-- >>> bromigos setup monitors")
    e = lua.find("-- <<< bromigos setup monitors")
    return lua[b:e] if b >= 0 and e > b else ""


def trial():
    try:
        out = subprocess.run(["bromigos", "display", "--json"], capture_output=True, text=True, timeout=20).stdout
        return json.loads(out).get("trial")
    except (OSError, ValueError, subprocess.SubprocessError):
        return None


def walk(w):
    stack = [w]
    while stack:
        x = stack.pop()
        yield x
        c = x.get_first_child()
        while c is not None:
            stack.append(c)
            c = c.get_next_sibling()


def steps(d):
    page = d.win.built["displays"]._displays
    original = monitor().get("scale", 1.0)

    def stage_scale():
        page.out_combo.set_selected(page.out_combo._values.index(OUT))
        page.scale_combo.set_selected(page.scale_combo._values.index(1.5))

    def keep_button():
        b = next((x for x in walk(page.dialog) if isinstance(x, Gtk.Button) and x.get_label() == "Keep"), None) \
            if page.dialog is not None else None
        if b is None:
            raise RuntimeError("no Keep button: the dialog isn't up")
        b.emit("clicked")

    def scale_is(v):
        return lambda: (abs(monitor().get("scale", 0) - v) < 0.01, monitor().get("scale"))
    return [
        ("Displays: the test output is listed", lambda: page.refresh(),
         lambda: (OUT in page.out_combo._values, page.out_combo._values), 1.0),
        ("Displays: a scale staged: nothing applied yet",
         stage_scale, lambda: (abs(monitor().get("scale", 0) - original) < 0.01 and bool(page.staged),
                               (monitor().get("scale"), page.staged)), 0.5),
        ("Displays: Apply: the live output at 1.5x, and the question is up",
         page.apply, lambda: (abs(monitor().get("scale", 0) - 1.5) < 0.01 and page.dialog is not None,
                              (monitor().get("scale"), page.dialog is not None)), 1.0),
        ("Displays: the block in hyprland.lua pins it at 1.5",
         lambda: None, lambda: (OUT in block() and "scale = 1.5" in block(), block()[-300:]), 0.2),
        ("Displays: nobody answers: after 15 s it reverts by itself (1x again, the block as it was)",
         lambda: None, lambda: (abs(monitor().get("scale", 0) - original) < 0.01 and "scale = 1.5" not in block()
                                and OUT in block() and page.dialog is None,
                                (monitor().get("scale"), block()[-200:], page.dialog)), 17.0),
        ("Displays: applied again, and the dialog's own Keep pressed",
         lambda: (stage_scale(), page.apply()), lambda: (page.dialog is not None, "dialog up"), 1.5),
        ("Displays: kept: still 1.5x after the countdown would have run out",
         keep_button, lambda: (abs(monitor().get("scale", 0) - 1.5) < 0.01 and "scale = 1.5" in block(),
                               (monitor().get("scale"), block()[-200:])), 17.0),
        ("Displays: Reset to defaults: the question is up again",
         lambda: (page.reset(), None), lambda: (page.dialog is not None, "dialog up"), 1.5),
        ("Displays: reset kept: the block gone, no trial waiting",
         keep_button, lambda: (block() == "" and not (trial() or {}).get("pending"), (block()[-200:], trial())), 2.0),
    ]
