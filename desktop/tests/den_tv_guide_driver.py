"""Drive Settings › Den TV (the channel guide) inside e2e_tv_nested.py's nested Hyprland, as
a user would: Add channel filled in and Add clicked, a card dropped before another, its
screens changed, a screen's tune button, Remove and its Undo. After each, the live layer running in the
nest is asked what it has (`bromigos-live tv list|state`): the channels follow without a
restart. Prints PASS/FAIL lines.

    python3 den_tv_guide_driver.py DESKTOP/settings MEDIA_FOLDER
"""
import faulthandler
import json
import os
import subprocess
import sys

faulthandler.dump_traceback_later(240, repeat=True)

sys.path.insert(0, sys.argv[1])
import gi  # noqa: E402

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import GLib, Gtk  # noqa: E402

from bromigos_settings import app as A  # noqa: E402

MEDIA = sys.argv[2]
results = []


def say(name, ok, detail=""):
    results.append(ok)
    print(("PASS" if ok else "FAIL"), name, "|", str(detail)[:400], flush=True)


def live(*args):
    try:
        return subprocess.run(["bromigos-live", "tv", *args], capture_output=True, text=True, timeout=15).stdout
    except (OSError, subprocess.SubprocessError):
        return ""


def walk(w):
    stack = [w]
    while stack:
        x = stack.pop()
        yield x
        c = x.get_first_child()
        while c is not None:
            stack.append(c)
            c = c.get_next_sibling()


def lineup(screen):
    """[names] on a screen, from the live layer's `tv list`."""
    out = []
    for ln in live("list").splitlines():
        parts = ln.split()
        if parts and parts[0] == screen:
            rest = ln[len(screen):].lstrip().lstrip("*").split(None, 1)[1]
            out.append(rest.split("  (")[0].split("  [")[0].strip())
    return out


class Driver(A.App):
    def __init__(self):
        super().__init__(render={"out": "-", "page": "den-tv", "key": None, "search": None, "size": (1180, 900),
                                 "advanced": False, "audit": False})

    def _snap_when_ready(self, waited):
        win = self.win
        if win.ctx.pending and waited < 20000:
            GLib.timeout_add(200, self._snap_when_ready, waited + 200)
            return False
        self.toasts = []
        orig = win.toast

        def spy(text, undo=None, timeout=5):
            self.toasts.append((text, undo))
            orig(text, undo, timeout)
        win.toast = spy
        self.g = win.built["den-tv"]._guide
        self.steps = steps(self)
        GLib.timeout_add(300, self.next)
        return False

    def next(self):
        if self.win.ctx.pending:
            return True
        if not self.steps:
            self.quit()
            return False
        name, act, check = self.steps.pop(0)
        try:
            act()
        except Exception as e:
            say(name, False, f"{type(e).__name__}: {e}")
            GLib.timeout_add(100, self.next)
            return False

        def verify(tries=0):
            if self.win.ctx.pending:
                return True
            ok, detail = check()
            if not ok and tries < 40:
                GLib.timeout_add(250, verify, tries + 1)
                return False
            say(name, ok, detail)
            GLib.timeout_add(200, self.next)
            return False
        GLib.timeout_add(600, verify)
        return False

    def index(self, name):
        return next(i for i, ch, t in self.g.entries if (t or {}).get("name") == name)


def steps(d):
    g = d.g

    def add():
        dlg = g.add_dialog()
        f = dlg._fields
        f["kind"].set_selected(f["kinds"].index("folder"))
        f["folder"]._path = MEDIA
        f["name"].set_text("Driven")
        f["order"].set_selected(2)                            # in order
        f["screens"]["emblem"].set_active(False)              # the big monitor and the scope
        f["screens"]["wave"].set_active(True)
        dlg._ok.emit("clicked")

    def drop_before_first():
        i = d.index("Driven")
        first = next(i_ for i_, ch, t in g.entries if ch and "big" in ch["screens"])
        g._dropped(str(i), first)

    def to_small():
        g.set_screens(d.index("Driven"), ["big", "emblem"])

    def tune():
        n = lineup("emblem").index("Driven") + 1
        card = g.cards["driven"]
        btn = [b for b in walk(card) if isinstance(b, Gtk.Button) and b.get_label() == "SMALL"][0]
        d.tuned_n = n
        btn.emit("clicked")                                   # the card's SMALL button

    def remove():
        i = d.index("Driven")
        g.remove(i, g.entries[i][1])

    def undo():
        u = next(u for _t, u in reversed(d.toasts) if u)
        u()

    return [
        ("the guide lists the live layer's channels", lambda: None,
         lambda: (all(ch for _i, ch, _t in g.entries) and len(g.entries) >= 3 and g.live is not None,
                  [t.get("name") for _i, _c, t in g.entries])),
        ("Add channel: a folder, in order, on the big monitor and the scope; the live layer has it", add,
         lambda: ("Driven" in lineup("big") and "Driven" in lineup("wave") and "Driven" not in lineup("emblem"),
                  (lineup("big"), lineup("wave")))),
        ("…written to config.toml with its comments kept", lambda: None,
         lambda: ("# the den TV, as the test has it" in open(os.path.expanduser(
             "~/.config/bromigos-live/config.toml")).read(), "comment")),
        ("dragged before the first: channel 2 on the big monitor", drop_before_first,
         lambda: (lineup("big")[1:2] == ["Driven"], lineup("big"))),
        ("its screens: the big and small monitors, not the scope", to_small,
         lambda: ("Driven" in lineup("emblem") and "Driven" not in lineup("wave") and "Driven" in lineup("big"),
                  (lineup("big"), lineup("wave"), lineup("emblem")))),
        ("the card's SMALL button: the small monitor on it", tune,
         lambda: (json.loads(live("state", "--json") or "{}").get("screens", {}).get("emblem", {}).get("name")
                  == "Driven", live("state", "--json")[:300])),
        ("Remove: gone from every screen", remove,
         lambda: ("Driven" not in lineup("big") + lineup("emblem"), lineup("big"))),
        ("…and Undo puts it back", undo, lambda: ("Driven" in lineup("emblem"), lineup("emblem"))),
    ]


if __name__ == "__main__":
    Driver().run([sys.argv[0]])
    sys.exit(0 if results and all(results) else 1)
