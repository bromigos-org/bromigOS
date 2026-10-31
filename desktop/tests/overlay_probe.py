#!/usr/bin/env python3
"""A plain window in one solid colour, for e2e_overlay_nested.py: whatever the compositor
shows over it is easy to tell from the window itself. SIGUSR1 paints it cyan, SIGUSR2
magenta. The window class is argv[1] (default bk-probe), so a test can stand it in for an
app a window rule matches.

    overlay_probe.py [CLASS] [--fullscreen]
"""
import signal
import sys

import gi

gi.require_version("Gtk", "3.0")
from gi.repository import GLib, Gtk  # noqa: E402

COLOURS = {"magenta": (1.0, 0.0, 1.0), "cyan": (0.0, 1.0, 1.0)}


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    GLib.set_prgname(args[0] if args else "bk-probe")
    state = {"rgb": COLOURS["magenta"]}
    win = Gtk.Window(title="overlay probe")
    area = Gtk.DrawingArea()

    def draw(_w, cr):
        cr.set_source_rgb(*state["rgb"])
        cr.paint()
        return True
    area.connect("draw", draw)
    win.add(area)
    win.set_default_size(900, 600)
    win.connect("destroy", Gtk.main_quit)

    def paint(name):
        state["rgb"] = COLOURS[name]
        area.queue_draw()
        return GLib.SOURCE_CONTINUE
    GLib.unix_signal_add(GLib.PRIORITY_DEFAULT, signal.SIGUSR1, paint, "cyan")
    GLib.unix_signal_add(GLib.PRIORITY_DEFAULT, signal.SIGUSR2, paint, "magenta")
    GLib.unix_signal_add(GLib.PRIORITY_DEFAULT, signal.SIGTERM, lambda: (Gtk.main_quit(), False)[1])
    win.show_all()
    if "--fullscreen" in sys.argv:
        win.fullscreen()
    Gtk.main()


if __name__ == "__main__":
    main()
