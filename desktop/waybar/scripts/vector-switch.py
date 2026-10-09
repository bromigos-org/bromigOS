#!/usr/bin/env python3
"""Waybar VECTOR emergency switch: a small power mark while VECTOR is on; a red
"VECTOR OFF" while the operator's switch is off. A click switches him off at once; while
he's off, a click asks first (a NO/YES menu) before switching him back on. Reads the
switch's markers itself, so it shows the truth while his daemon is stopped, hung or
crashed (vector: holo/vector/switch.py). Refreshed on SIGRTMIN+9 (the switch and his
daemon send it) and every 10 s. Empty (hidden) when VECTOR isn't installed."""
import json
import os
import shutil

HOME = os.path.expanduser("~")
STATE = os.path.join(HOME, ".local/state/bromigos")        # where VECTOR keeps it (his switch.py)
RUN = os.environ.get("XDG_RUNTIME_DIR") or f"/run/user/{os.getuid()}"
DIR = os.path.join(STATE, "vector-switch")
RUN_DIR = os.path.join(RUN, "bromigos-vector-switch")
MARKS = (os.path.join(RUN_DIR, "off"), os.path.join(DIR, "off"), os.path.join(STATE, "vector-shell-off"))
GLYPH = "\uf011"                                   # the power mark (Nerd Font; bromigos-settings ships it)
KEY = "SUPER+CTRL+ESCAPE"


def installed():
    return bool(shutil.which("bromigos-holo")) or os.path.exists("/usr/lib/bromigos/vector/bin/bromigos-holo")


def is_off():
    """The switch's own rule: any marker there, or a markers' folder swapped for a symlink."""
    return any(os.path.lexists(p) for p in MARKS) or any(os.path.islink(d) for d in (DIR, RUN_DIR))


def who():
    for p in MARKS[:2]:
        try:
            with open(p) as f:
                return (json.load(f) or {}).get("by")
        except (OSError, ValueError, AttributeError):
            continue
    return None


def main():
    if not installed():
        return {"text": "", "class": "absent"}
    if is_off():
        by = who()
        return {"text": f"{GLYPH} VECTOR OFF", "class": ["off"],
                "tooltip": ("VECTOR's emergency switch is OFF" + (f" (switched off by {by})" if by else "") + ".\n"
                            "His terminal runs nothing and his tools change nothing; he can still talk.\n"
                            f"click: switch him back on (asks YES first) · {KEY} does the same\n"
                            "Only you can switch him back on: Settings › VECTOR, or `bromigos vector on`")}
    return {"text": GLYPH, "class": ["on"],
            "tooltip": ("VECTOR's emergency switch: on.\n"
                        "click: switch VECTOR off now. It stops his commands, his current answer and his speech, "
                        "and keeps him off until you switch him back on.\n"
                        f"Also {KEY}, Settings › VECTOR, or `bromigos vector off`")}


if __name__ == "__main__":
    print(json.dumps(main()))
