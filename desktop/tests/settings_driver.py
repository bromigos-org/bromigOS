"""Drive one Settings page as a user would, inside e2e_settings_nested.py's nested Hyprland:
its own widgets are set (a dropdown picked, a slider dragged, a switch flipped, a button
clicked), then what the page's command should have changed is checked where it lives (the
sandboxed PipeWire, the nested Hyprland, the files). Prints PASS/FAIL lines.

    python3 settings_driver.py DESKTOP/settings SCENARIO      (sound, displays, input, keys, vector)
"""
import faulthandler
import json
import os
import subprocess
import sys
import time

faulthandler.dump_traceback_later(int(os.environ.get("BROMIGOS_DRIVER_STACK", "120")), repeat=True)   # a hang says where

sys.path.insert(0, sys.argv[1])
import gi  # noqa: E402

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import GLib, Gtk  # noqa: E402

from bromigos_settings import app as A  # noqa: E402

SCENARIO = sys.argv[2]


class Results(list):
    """Each step's outcome, printed as it comes (a stuck step still leaves the ones before)."""
    def append(self, item):
        name, ok, detail = item
        print(("PASS" if ok else "FAIL"), name, "|", str(detail)[:300], flush=True)
        super().append(item)
PAGE = {"sound": "sound", "displays": "displays", "input": "input", "keys": "sound", "vector": "vector"}[SCENARIO]
results = Results()


def sh(*argv, timeout=20):
    try:
        return subprocess.run(argv, capture_output=True, text=True, timeout=timeout).stdout
    except (OSError, subprocess.SubprocessError):
        return ""


def jsh(*argv):
    try:
        return json.loads(sh(*argv) or "null")
    except ValueError:
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


def find_row(page_widget, key):
    return next((x for x in walk(page_widget) if getattr(x, "_bromigos_key", None) == key), None)


def button(page_widget, label):
    return next((x for x in walk(page_widget) if isinstance(x, Gtk.Button) and x.get_label() == label), None)


class Driver(A.App):
    def __init__(self):
        super().__init__(render={"out": "-", "page": PAGE, "key": None, "search": None, "size": (1120, 780),
                                 "advanced": False, "audit": False})

    def _snap_when_ready(self, waited):
        win = self.win
        if win.ctx.pending and waited < 15000:
            GLib.timeout_add(200, self._snap_when_ready, waited + 200)
            return False
        self.toasts = []
        orig = win.toast

        def spy(text, undo=None, timeout=5):
            self.toasts.append((text, undo))
            orig(text, undo, timeout)
        win.toast = spy
        self.steps = SCENARIOS[SCENARIO](self)
        print("READY", flush=True)
        GLib.timeout_add(300, self.next)
        return False

    def next(self):
        if self.win.ctx.pending:
            self.waits = getattr(self, "waits", 0) + 1
            if self.waits % 50 == 0:
                print(f"WAIT {self.win.ctx.pending} command(s) still running", file=sys.stderr, flush=True)
            return True
        if not self.steps:
            self.quit()
            return False
        name, act, check, settle = self.steps.pop(0)
        try:
            act()
        except Exception as e:
            results.append((name, False, f"{type(e).__name__}: {e}"))
            return True

        def verify(tries=0):
            if self.win.ctx.pending:
                return True
            ok, detail = check()
            if not ok and tries < 20:
                GLib.timeout_add(250, verify, tries + 1)
                return False
            results.append((name, ok, detail))
            GLib.timeout_add(150, self.next)
            return False
        GLib.timeout_add(int(settle * 1000), verify)
        return False

    def last_undo(self):
        u = next((u for _, u in reversed(self.toasts) if u), None)
        if u is None:
            raise RuntimeError("no toast with Undo")
        u()


# ---------------------------------------------------------------------------- Sound
def sound(d):
    page = d.win.built["sound"]._sound

    def info():
        return jsh("pactl", "--format=json", "info") or {}

    def sink(name):
        return next((s for s in jsh("pactl", "--format=json", "list", "sinks") or [] if s["name"] == name), {})

    def vol(o):
        return int(next(iter(o["volume"].values()))["value_percent"].rstrip("%")) if o else None

    def app():
        return next(iter(jsh("pactl", "--format=json", "list", "sink-inputs") or []), {})

    def pick_output(name):
        c = page.output_combo
        c.set_selected(c._values.index(name))

    def overrides():
        try:
            with open(os.path.expanduser("~/.config/bromigos/live/overrides.toml")) as f:
                return f.read()
        except FileNotFoundError:
            return ""
    return [
        ("Sound: the output device picked: headphones is the default",
         lambda: pick_output("headphones"), lambda: (info().get("default_sink_name") == "headphones", info()), 0.3),
        ("Sound: the playing app followed it",
         lambda: None, lambda: (app().get("sink") == sink("headphones").get("index"), app().get("sink")), 0.2),
        ("Sound: the toast's Undo puts the speakers back",
         d.last_undo, lambda: (info().get("default_sink_name") == "speakers", info().get("default_sink_name")), 0.3),
        ("Sound: the volume slider dragged to 35%: the device at 35%",
         lambda: page.output_volume.scale.set_value(35), lambda: (vol(sink("speakers")) == 35, vol(sink("speakers"))),
         0.8),
        ("Sound: Ctrl+Z (the last change's undo): back to 100%",
         d.win.undo, lambda: (vol(sink("speakers")) == 100, vol(sink("speakers"))), 0.3),
        ("Sound: the mute button: the device muted",
         lambda: page.output_volume.mute_button.set_active(True), lambda: (sink("speakers").get("mute") is True,
                                                                           sink("speakers").get("mute")), 0.3),
        ("Sound: the app's own slider to 50%: its stream at 50%",
         lambda: next(iter(page.app_widgets.values()))[0].scale.set_value(50),
         lambda: (vol(app()) == 50, vol(app())), 0.8),
        ("Sound: the theme's cues switched off: written for the live layer",
         lambda: page.cues_row.set_active(False),
         lambda: ("enabled = false" in overrides().split("[sounds]", 1)[-1], overrides()[-200:]), 0.3),
        ("Sound: the page shows what PipeWire says (read again)",
         page.refresh, lambda: (page.output_volume.mute_button.get_active() and
                                round(page.output_volume.scale.get_value()) == 100, "mute and 100% shown"), 0.5),
    ]


# ---------------------------------------------------------------------------- the keyboard
def keys(d):
    """The harness types what a step prints (KEYS type|tap|combo …) into the nested
    Hyprland; the step checks where the window went and what has focus."""
    win = d.win

    def say(*lines):
        def act():
            for ln in lines:
                print("KEYS " + ln, flush=True)
        return act

    def focus_desc():
        w = win.get_focus()
        chain = []
        while w is not None and len(chain) < 6:
            chain.append(type(w).__name__ + (f"[{w._bromigos_key}]" if getattr(w, "_bromigos_key", None) else ""))
            w = w.get_parent()
        return "<".join(chain) + f" | search={win.search.get_text()!r} results=" + str(
            [r.title for r in win.index.search(win.search.get_text())[:3]])

    def focus_key():
        w = win.get_focus()
        while w is not None:
            k = getattr(w, "_bromigos_key", None)
            if k:
                return k
            w = w.get_parent()
        return None

    def first_of(group):
        return next(p for p in win.order if win.pages[p].group_id == group)
    sound = d.win.built["sound"]._sound
    return [
        ("Keys: typing anywhere searches; Enter opens the first result on its row (microphone -> Sound › Input device)",
         say("type microphone", "tap RETURN"),
         lambda: (win.current == "sound" and focus_key() == "input", (win.current, focus_desc())), 2.5),
        ("Keys: Esc clears the search",
         say("combo CTRL + F", "tap ESCAPE"), lambda: (win.search.get_text() == "", focus_desc()), 1.0),
        ("Keys: Ctrl+F, words, Enter: a setting on another page (lock after -> Idle & lock › Lock)",
         say("combo CTRL + F", "type lock the screen", "tap RETURN"),
         lambda: (win.current == "idle" and focus_key() == "lock", (win.current, focus_desc())), 2.5),
        ("Keys: Ctrl+1 opens the System group's first page",
         say("tap ESCAPE", "combo CTRL + 1"), lambda: (win.current == first_of("system"), win.current), 1.5),
        ("Keys: Ctrl+PgDn the next page",
         say("combo CTRL + PAGEDOWN"),
         lambda: (win.current == win.order[(win.order.index(first_of("system")) + 1) % len(win.order)], win.current),
         1.5),
        ("Keys: Ctrl+2 opens the Desktop group's first page",
         say("combo CTRL + 2"), lambda: (win.current == first_of("desktop"), win.current), 1.5),
    ]


def vector(d):
    """VECTOR's emergency switch, through the fixture's stand-in bromigos-holo (its markers in
    this sandbox's HOME and runtime folder, every call logged): off at once; a flip to on
    only opens the dialog and the switch stays off; Enter and Cancel leave him off; the
    dialog's "Turn him on" runs `bromigos-holo on`."""
    page = d.win.built["vector"]._vector
    row = page.switch_row
    marks = [os.path.expanduser("~/.local/state/bromigos/vector-switch/off"),
             os.path.join(os.environ["XDG_RUNTIME_DIR"], "bromigos-vector-switch", "off")]
    logf = os.path.join(os.environ["BROMIGOS_FIXTURE_STATE"], "bromigos-holo.log")
    dialogs = []
    orig = page.ctx.confirm

    def spy(*a, **k):
        dlg = orig(*a, **k)
        dialogs.append(dlg)
        return dlg
    page.ctx.confirm = spy

    def calls():
        try:
            with open(logf) as f:
                return [json.loads(x) for x in f if x.strip()]
        except (OSError, ValueError):
            return []

    def armed():                      # every call that would switch him on
        return [c for c in calls() if c[:1] == ["on"] or c[:2] in (["shell", "on"], ["switch", "on"])]

    def off():
        return all(os.path.exists(m) for m in marks)

    def click(label):
        b = next(x for x in walk(dialogs[-1]) if isinstance(x, Gtk.Button) and x.get_label() == label)
        b.emit("clicked")

    def state():
        return {"active": row.get_active(), "markers": [os.path.exists(m) for m in marks], "dialogs": len(dialogs),
                "subtitle": row.get_subtitle()[:60], "calls": calls()[-3:]}
    return [
        ("VECTOR: the switch starts on (no marker)", lambda: None,
         lambda: (row.get_active() and not any(os.path.exists(m) for m in marks), state()), 0.3),
        ("VECTOR: flipping the switch off runs bromigos-holo off at once: both markers there",
         lambda: row.set_active(False), lambda: (off() and ["off", "--from=settings"] in calls(), state()), 0.5),
        ("VECTOR: the page reads it back from the markers: off, and says so", page.refresh,
         lambda: (not row.get_active() and row.get_subtitle().startswith("Off"), state()), 0.5),
        ("VECTOR: a flip to on only asks: the switch stays off, one dialog, nothing ran",
         lambda: row.set_active(True),
         lambda: (not row.get_active() and len(dialogs) == 1 and not armed() and off(), state()), 0.8),
        ("VECTOR: Enter in the dialog says no (Cancel is the default): the dialog closed, he stays off",
         lambda: print("KEYS tap RETURN", flush=True),
         lambda: (not dialogs[0].get_mapped() and not armed() and off() and not row.get_active(),
                  dict(state(), dialog_shown=dialogs[0].get_mapped())), 1.5),
        ("VECTOR: the dialog's Cancel leaves him off",
         lambda: (row.set_active(True), click("Cancel")),
         lambda: (len(dialogs) == 2 and not armed() and off() and not row.get_active(), state()), 1.0),
        ("VECTOR: the dialog's Turn him on runs bromigos-holo on: the markers are gone",
         lambda: (row.set_active(True), click("Turn him on")),
         lambda: (armed() == [["on", "--from=settings"]] and not any(os.path.exists(m) for m in marks), state()), 1.0),
        ("VECTOR: the page reads on again", page.refresh,
         lambda: (row.get_active() and row.get_subtitle().startswith("On"), state()), 0.5),
    ]


def displays(d):
    from settings_driver_displays import steps
    return steps(d)


def input_(d):
    from settings_driver_input import steps
    return steps(d)


SCENARIOS = {"sound": sound, "displays": displays, "input": input_, "keys": keys, "vector": vector}

Driver().run([sys.argv[0]])
bad = sum(1 for _, ok, _ in results if not ok)
sys.exit(1 if bad or not results else 0)
