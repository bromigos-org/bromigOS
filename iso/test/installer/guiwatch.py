#!/usr/bin/env python3
"""The graphical installer as it is, with what its window shows written to a file: for the test
that drives it with a real pointer and real keys (iso/test.sh gui-type; docs/iso.md, "Testing it").

  python3 guiwatch.py STATE.json [the installer's own arguments…]

The installer's own main() runs, nothing of it changed. Five times a second STATE.json gets
the step on screen, the About-you fields' text, the problems line, which widget has the keyboard's
focus, where Continue, Back and each field are in the window (their middles, for the pointer:
the window is full screen, so these are the screen's), and how much of a core the installer
used since the last look (a callback that never stops shows as a whole core).
"""
import json
import os
import sys
import time

sys.path.insert(0, os.environ.get("BROMIGOS_INSTALLER_LIB", "/usr/local/lib/bromigos-iso"))
from bromigos_installer import gui  # noqa: E402
from gi.repository import Gio, GLib  # noqa: E402

STATE = sys.argv[1]
last = [time.monotonic(), time.process_time()]


def middle(widget, win):
    """The middle of a widget in the window, or None when it isn't on screen."""
    if widget is None or not widget.get_mapped():
        return None
    ok, rect = widget.compute_bounds(win)
    if not ok:
        return None
    return [round(rect.get_x() + rect.get_width() / 2), round(rect.get_y() + rect.get_height() / 2)]


def look():
    app = Gio.Application.get_default()
    win = app.get_active_window() if app else None
    if win is None or not hasattr(win, "step"):
        return True
    now, cpu = time.monotonic(), time.process_time()
    focus = win.get_focus()
    state = {
        "step": win.step,
        "fields": {k: row.get_text() for k, row in getattr(win, "f", {}).items()},
        "problems": win.err.get_label(),
        "focus": type(focus).__name__ if focus is not None else None,
        "cpu": round((cpu - last[1]) / max(now - last[0], 0.001), 2),
        "at": {k: middle(w, win) for k, w in {"next": win.next, "back": win.back, **getattr(win, "f", {})}.items()},
        "fullscreen": win.is_fullscreen(),
        "size": [win.get_width(), win.get_height()],
    }
    last[:] = [now, cpu]
    with open(STATE + ".new", "w") as f:
        json.dump(state, f)
    os.replace(STATE + ".new", STATE)
    return True


GLib.timeout_add(200, look)
sys.exit(gui.main(sys.argv[2:]))
