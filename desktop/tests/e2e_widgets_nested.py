#!/usr/bin/env python3
"""End to end: the panels' edit mode in a nested Hyprland nobody sees.

The nested Hyprland is e2e_keys_nested.py's (kwin_wayland --virtual hosting it, a runtime
directory, HOME and D-Bus of its own, the template user config over this checkout's
defaults). Here the panels are real: this checkout's bromigos-widgets starts at login,
with demo readings (BROMIGOS_WIDGETS_DEMO), on the nested output. The sandbox's
layout.json is a symlink into a stand-in dotfiles folder, as on a machine whose config
lives in a dotfiles repository. A virtual keyboard (vkbd.py) and a virtual pointer
(vptr.py) drive it the way a person would. It checks:

  - Super+Alt+W starts edit mode: the canvas on the overlay layer, the panels lifted
    above windows (the top layer), and back below them after;
  - a drag moves a panel, snapped as arrange.py says, in the panels' own state and in
    Hyprland's layer geometry; a corner drag resizes within the panel's limits; the ×
    hides one;
  - the keyboard alone: Tab picks, arrows nudge (Shift: 10 px), H hides, Ctrl+Z undoes;
  - adding a hidden panel finds it a free spot;
  - Esc saves layout.json through the symlink (still a link), `bromigos panels` shows it;
    Cancel puts everything back and writes nothing; a right-click on a panel starts it;
  - the panels keep drawing while edit mode is on.

With --shots DIR it saves pictures of edit mode (grim, inside the nested session) in two
themes (set with `bromigos theme set --no-reload` in the sandbox) and with high contrast.

Not part of `unittest discover` (it needs kwin_wayland, Hyprland and a GPU):

    python3 desktop/tests/e2e_widgets_nested.py [--keep] [--shots DIR]
"""
import json
import os
import shutil
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from e2e_keys_nested import REPO, Nest, Run, wait_for  # noqa: E402

sys.path.insert(0, os.path.join(REPO, "widgets"))
import arrange as A  # noqa: E402
import vkbd  # noqa: E402
import vptr  # noqa: E402

WIDGETS = os.path.join(REPO, "widgets", "bromigos-widgets")


class WidgetsNest(Nest):
    SIZE = (2560, 1440)         # a 27" desktop's screen, at scale 1: the default layout fits

    def __init__(self, keep=False, shots=None):
        super().__init__(keep, shots)
        with open(self.lua) as f:
            conf = f.read()
        conf = conf.replace("bromigos = {\n", 'bromigos = {\n    monitors = { { output = "WAYLAND-1", mode = "2560x1440@60", '
                            'position = "0x0", scale = 1 } },\n', 1)
        with open(self.lua, "w") as f:
            f.write(conf)
        self.original = conf
        # the real panels, from this checkout, with demo readings
        with open(os.path.join(self.stubs, "bromigos-widgets"), "w") as f:
            f.write(f'#!/bin/sh\nexport BROMIGOS_WIDGETS_DEMO=1 BROMIGOS_HOMELAB=/nonexistent\n'
                    f'exec python3 {WIDGETS} "$@" 2>>"$HOME/widgets.err"\n')
        share = os.path.join(self.tmp, "share", "widgets")
        os.makedirs(share)
        os.symlink(os.path.join(REPO, "widgets", "layout.json"), os.path.join(share, "layout.json"))
        os.symlink(os.path.join(REPO, "desktop", "bin", "bromigos-panels"), os.path.join(self.stubs, "bromigos-panels"))
        for d in ("themes", "theme"):                  # `bromigos theme set` in the sandbox
            os.symlink(os.path.join(REPO, d), os.path.join(self.tmp, "share", d))
        # layout.json: a link into a dotfiles folder
        self.dots = os.path.join(self.home, "dotfiles", "bromigos", "widgets")
        os.makedirs(self.dots)
        shutil.copy(os.path.join(REPO, "widgets", "layout.json"), os.path.join(self.dots, "layout.json"))
        os.makedirs(os.path.join(self.home, ".config", "bromigos", "widgets"))
        self.link = os.path.join(self.home, ".config", "bromigos", "widgets", "layout.json")
        os.symlink("../../../dotfiles/bromigos/widgets/layout.json", self.link)
        self.base["PYTHONPATH"] = os.path.join(REPO, "desktop", "lib")
        self.base["BROMIGOS_LIB_BIN"] = os.path.join(REPO, "desktop", "bin")

    def start(self):
        super().start()
        m = json.loads(self.ctl("monitors", "-j"))[0]
        scale = float(m.get("scale") or 1)
        # the output in logical px: what the panels' margins and the pointer are in
        self.size = (round(m["width"] / scale), round(m["height"] / scale))
        self.ptr = vptr.VirtualPointer(os.path.join(self.run, "wayland-1"), *self.size)

    def health(self):
        try:
            with open(os.path.join(self.run, "bromigos-widgets-health.json")) as f:
                return json.load(f)
        except (OSError, ValueError):
            return {}

    def panels(self):
        return self.health().get("panels") or {}

    def widgets(self, *args):
        return subprocess.run(["bromigos-widgets", *args], env=self.env, capture_output=True, text=True, timeout=20)

    def layers(self):
        """{level: [(namespace, x, y, w, h)]} on the nested output."""
        try:
            doc = json.loads(self.ctl("layers", "-j") or "{}")
        except ValueError:
            return {}
        out = {}
        for mon in doc.values():
            for lv, ls in mon.get("levels", {}).items():
                out.setdefault(lv, []).extend((x.get("namespace"), x["x"], x["y"], x["w"], x["h"]) for x in ls)
        return out

    def layer_rects(self, namespace, level=None):
        return [tuple(x[1:]) for lv, ls in self.layers().items() if level is None or lv == level
                for x in ls if x[0] == namespace]

    def saved(self):
        with open(self.link) as f:
            return A.state_of(json.load(f))

    def bromigos(self, *args):
        built = os.path.join(REPO, "core", "target", "debug", "bromigos")
        return subprocess.run([built if os.access(built, os.X_OK) else "bromigos", *args], env=self.env,
                              capture_output=True, text=True, timeout=60)


def editing(n, want=True):
    return wait_for(lambda: bool(n.health().get("editing")) == want and
                    bool(n.layer_rects("bromigos-widgets-edit")) == want, 8)


def rect(n, name):
    s = n.panels().get(name) or {}
    return (s.get("x"), s.get("y"), s.get("width"), s.get("height"))


def settle(n, fn, timeout=5):
    """Waits for the health file to say fn(panels) (it's written every 2 s and on each
    change of mode)."""
    return wait_for(lambda: fn(n.panels()), timeout, 0.25)


def scenarios(n, r):
    kb, ptr = n.kb, n.ptr
    r.check("the panels start at login, from this checkout",
            wait_for(lambda: len(n.layer_rects("bromigos-widgets")) >= 4, 30), n.layers())
    r.check("they sit on the bottom layer, below windows", wait_for(lambda: n.layer_rects("bromigos-widgets", "1"), 5))
    settle(n, lambda p: "system" in p, 8)
    start = n.panels()

    # -- entering: the key
    kb.combo("SUPER + ALT + W")
    r.check("Super+Alt+W: edit mode, the canvas on the overlay layer", editing(n), n.layers())
    r.check("edit mode: the panels lifted above windows (the top layer)",
            wait_for(lambda: n.layer_rects("bromigos-widgets", "2") and not n.layer_rects("bromigos-widgets", "1"), 5),
            n.layers())
    time.sleep(1.0)
    n.shot("edit-wick")

    # -- a drag moves a panel, snapped
    x, y, w, h = rect(n, "system")
    others = [tuple((s["x"], s["y"], s["width"], s["height"])) for k, s in n.panels().items()
              if k != "system" and s["visible"]]
    grab = (x + 150, y + 200)
    ptr.drag(grab, (grab[0] + 303, grab[1] + 97))
    want = A.snap_move((x + 303, y + 97, w, h), others, n.size)[:2]
    r.check("a drag moves SYSTEM where snapping puts it",
            settle(n, lambda p: (p["system"]["x"], p["system"]["y"]) == want), (rect(n, "system"), want))
    r.check("Hyprland draws it there", wait_for(lambda: (want[0], want[1], w, h) in n.layer_rects("bromigos-widgets"), 4),
            (want, n.layer_rects("bromigos-widgets")))

    # -- a corner drag resizes, within the panel's size classes
    import panels as PN
    smallest = PN.StoragePanel.limits()[0]
    x, y, w, h = rect(n, "storage")
    ptr.drag((x + w, y + h), (x + w - 400, y + h - 300))       # far smaller than its smallest class
    r.check(f"a corner drag stops at the panel's smallest size (STORAGE compact: {smallest[0]}x{smallest[1]})",
            settle(n, lambda p: (p["storage"]["width"], p["storage"]["height"]) == smallest), rect(n, "storage"))
    x, y, w, h = rect(n, "storage")
    ptr.drag((x + w, y + h), (x + w + 101, y + h + 37))
    r.check("…grows on the 8 px grid inside its class", settle(
        n, lambda p: (p["storage"]["x"] + p["storage"]["width"]) % 8 == 0 and p["storage"]["width"] > smallest[0]
        and PN.StoragePanel.size_class(p["storage"]["width"], p["storage"]["height"]) == "compact"), rect(n, "storage"))
    x, y, w, h = rect(n, "storage")
    std_min_h = dict((c[0], c[1]) for c in PN.StoragePanel.size_classes())["standard"][1]
    ptr.drag((x + w, y + h), (x + 500, y + std_min_h - 4))      # just short of the standard class
    r.check("…and between two classes it snaps to the nearer one (standard)", settle(
        n, lambda p: PN.StoragePanel.size_class(p["storage"]["width"], p["storage"]["height"]) == "standard"
        and p["storage"]["height"] >= std_min_h), rect(n, "storage"))

    # -- the × hides one
    x, y, w, h = rect(n, "notes")
    ptr.click(at=(x + w - 16, y + 16))
    r.check("× hides FIELD NOTES", settle(n, lambda p: not p["notes"]["visible"]), n.panels().get("notes"))

    # -- the keyboard alone
    ptr.move(n.size[0] - 8, n.size[1] - 8)                      # off every panel
    before = n.panels()
    sel_before = rect(n, "system")
    ptr.click(at=(sel_before[0] + 60, sel_before[1] + 120))     # pick SYSTEM
    for _ in range(3):
        kb.tap("RIGHT")
    kb.combo("SHIFT + DOWN")
    r.check("arrows nudge the picked panel: 3 right, Shift+Down 10 down",
            settle(n, lambda p: (p["system"]["x"], p["system"]["y"]) == (sel_before[0] + 3, sel_before[1] + 10)),
            (rect(n, "system"), sel_before))
    kb.combo("CTRL + Z")
    r.check("Ctrl+Z undoes the nudges as one step",
            settle(n, lambda p: (p["system"]["x"], p["system"]["y"]) == sel_before[:2]), rect(n, "system"))
    kb.tap("TAB")
    kb.tap("H")
    r.check("Tab picks the next panel, H hides it",
            settle(n, lambda p: sum(1 for s in p.values() if s["visible"]) ==
                    sum(1 for s in before.values() if s["visible"]) - 1), n.panels())
    kb.combo("CTRL + Z")
    r.check("Ctrl+Z brings it back", settle(n, lambda p: sum(1 for s in p.values() if s["visible"]) ==
                                            sum(1 for s in before.values() if s["visible"])), n.panels())

    # -- adding a hidden one finds a free spot
    n.widgets("add", "weather")
    ok = settle(n, lambda p: p["weather"]["visible"])
    p = n.panels()
    wr = (p["weather"]["x"], p["weather"]["y"], p["weather"]["width"], p["weather"]["height"])
    clear = all(not A.overlaps(wr, (s["x"], s["y"], s["width"], s["height"])) for k, s in p.items()
                if k != "weather" and s["visible"])
    r.check("adding WEATHER puts it in a free spot, clear of every shown panel", ok and clear, (wr, p))
    n.shot("edit-added")
    r.check("the panels keep drawing in edit mode", draws_go_up(n), "")

    # -- Esc saves, through the symlink
    final = n.panels()
    kb.tap("ESCAPE")
    r.check("Esc leaves edit mode", editing(n, False), n.layers())
    r.check("…the panels back below windows",
            wait_for(lambda: n.layer_rects("bromigos-widgets", "1") and not n.layer_rects("bromigos-widgets", "2"), 5))
    r.check("layout.json is still a symlink into the dotfiles", os.path.islink(n.link))
    saved = n.saved()
    r.check("…and holds the layout as it was left",
            all(saved[k] == {**final[k]} for k in final if k in saved), (saved, final))
    st = subprocess.run(["bromigos-panels", "--json"], env=n.env, capture_output=True, text=True, timeout=30)
    doc = json.loads(st.stdout or "{}")
    sysp = next((x for x in doc.get("panels", []) if x["name"] == "system"), {})
    r.check("`bromigos panels` shows it", (sysp.get("x"), sysp.get("y")) == (final["system"]["x"], final["system"]["y"])
            and doc.get("yours"), (sysp, st.stderr[-300:]))

    # -- Cancel puts everything back and writes nothing
    with open(n.link) as f:
        text = f.read()
    n.widgets("edit", "on")
    editing(n)
    x, y, w, h = rect(n, "network")
    ptr.drag((x + 100, y + 100), (x + 400, y + 50))
    settle(n, lambda p: p["network"]["x"] != x)
    n.widgets("edit", "cancel")
    r.check("Cancel: edit mode off", editing(n, False))
    r.check("Cancel: NETWORK back where it was", settle(n, lambda p: (p["network"]["x"], p["network"]["y"]) == (x, y)),
            rect(n, "network"))
    with open(n.link) as f:
        r.check("Cancel: layout.json untouched", f.read() == text)

    # -- a right-click on a panel starts it
    x, y, w, h = rect(n, "network")
    ptr.move(x + 100, y + 100)
    time.sleep(0.5)
    ptr.click(vptr.RIGHT, at=(x + 120, y + 120))
    r.check("a right-click on a panel starts edit mode", editing(n),
            ((x, y, w, h), n.ctl("cursorpos"), n.layers(), n.health().get("editing")))
    kb.tap("ESCAPE")
    editing(n, False)
    errs = open(os.path.join(n.home, "widgets.err")).read() if os.path.exists(os.path.join(n.home, "widgets.err")) else ""
    r.check("the panels logged no traceback", "Traceback" not in errs, errs[-1500:])


TIDE = """from panels import Panel
import draw as D


class TideWatch(Panel):
    name, title = "tide_watch", "TIDE WATCH"
    description = "The next high and low tides for a harbour you choose"
    category, reads = "fun", "a tide table you point it at"
    settings = [
        {"key": "harbour", "label": "Harbour", "kind": "text", "default": "Harbor Point"},
        {"key": "every", "label": "Check every (minutes)", "kind": "number", "default": 30, "min": 5, "max": 720},
        {"key": "units", "label": "Heights in", "kind": "choice", "default": "metres",
         "choices": [["metres", "Metres"], ["feet", "Feet"]]},
        {"key": "glow", "label": "Glow at high tide", "kind": "bool", "default": True},
        {"key": "account", "label": "GitHub", "kind": "secret-signin", "provider": "github"},
    ]

    def draw(self, cr, w, h):
        D.frame(cr, w, h, self.title, self.setting("harbour").upper())
        self.region(0, 0, w, 34, "A demo widget with settings")


PANEL = TideWatch
"""


def settings_phase(n, r):
    """Settings › Widgets (settings_driver_widgets.py): a widget's form, and Install from URL
    from a git repository made here, its extension in a folder inside it."""
    n.widgets("edit", "done")                                    # Settings is a window: no overlay above it
    editing(n, False)
    plug = os.path.join(n.home, ".config", "bromigos", "plugins", "widgets")
    os.makedirs(plug, exist_ok=True)
    with open(os.path.join(plug, "tide_watch.py"), "w") as f:
        f.write(TIDE)
    repo = os.path.join(n.tmp, "src", "gauges")
    os.makedirs(os.path.join(repo, "examples"))
    made = n.bromigos("ext", "new", "widget", "hello-gauge", "--dir", os.path.join(repo, "examples", "hello-gauge"))
    if not r.check("a widget extension to install (bromigos ext new widget)", made.returncode == 0, made.stderr[-300:]):
        return
    git = ["git", "-C", repo, "-c", "user.name=test", "-c", "user.email=test@example.org"]
    for argv in (["init", "-q"], ["add", "-A"], ["commit", "-qm", "the widget"]):
        subprocess.run(git + argv, capture_output=True, env=n.env)
    env = dict(n.env, PYTHONPATH=os.pathsep.join([os.path.join(REPO, "desktop", "lib"), os.path.join(REPO, "lib"),
                                                   os.path.join(REPO, "desktop", "settings")]),
               SHOTS=n.shots or "")
    p = subprocess.Popen([sys.executable, os.path.join(HERE, "settings_driver_widgets.py"),
                          os.path.join(REPO, "desktop", "settings"), repo, "examples/hello-gauge"],
                         env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, start_new_session=True)
    n.procs.append(p)
    try:
        out, err = p.communicate(timeout=300)
    except subprocess.TimeoutExpired:
        os.killpg(p.pid, 9)
        out, err = p.communicate()
    steps = [ln for ln in out.splitlines() if ln.startswith(("PASS", "FAIL"))]
    for ln in steps:
        r.check("Settings: " + ln.split(" ", 1)[1].split(" | ")[0], ln.startswith("PASS"), ln)
    r.check("Settings: every step ran", len(steps) == 6, (out[-600:], err[-1200:]))


def customize_phase(n, r):
    """The Customize window (bromigos customize): opened on its Widgets tab, Ctrl+Tab to
    Themes, Esc closes it; with --shots, a picture of each tab."""
    n.widgets("edit", "done")
    editing(n, False)
    env = dict(n.env, BROMIGOS_PREVIEWS_HOLD="1", BROMIGOS_WIDGETS_DEMO="1",
               PYTHONPATH=os.pathsep.join([os.path.join(REPO, "desktop", "lib"), os.path.join(REPO, "lib")]))
    p = subprocess.Popen([sys.executable, os.path.join(REPO, "desktop", "bin", "bromigos-customize"), "--tab", "widgets"],
                         env=env, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True, start_new_session=True)
    n.procs.append(p)
    up = wait_for(lambda: n.layer_rects("bromigos-theme-switcher"), 20)
    r.check("Customize opens over the desktop (Super+Ctrl+Shift+Space's window)", up, n.layers())
    if not up:
        return
    time.sleep(5)                                        # the widget gallery draws its pictures
    n.shot("customize-widgets")
    n.kb.combo("CTRL + TAB")
    time.sleep(1.5)
    n.shot("customize-themes")
    n.kb.tap("ESCAPE")
    r.check("Esc closes it", wait_for(lambda: not n.layer_rects("bromigos-theme-switcher"), 8), n.layers())
    try:
        err = p.communicate(timeout=10)[1]
    except subprocess.TimeoutExpired:
        err = ""
    r.check("Customize logged no traceback", "Traceback" not in (err or ""), (err or "")[-1500:])


def draws_go_up(n):
    """The panels redraw while edit mode is on (their stats, to the app's stderr)."""
    def count():
        n.widgets("stats")
        time.sleep(0.3)
        try:
            lines = [ln for ln in open(os.path.join(n.home, "widgets.err")) if "system:draws=" in ln]
        except OSError:
            return None
        part = lines[-1].split("system:draws=")[1] if lines else ""
        return int(part.split(",")[0]) if part else None
    a = count()
    time.sleep(2.5)
    b = count()
    return a is not None and b is not None and b > a


def shots(n, r):
    """Edit mode in two more looks: the Cinder colour theme and high contrast."""
    for theme in ("cinder", "tidewell"):
        res = n.bromigos("theme", "set", theme, "--no-reload")
        if res.returncode != 0:
            r.check(f"theme {theme} set in the sandbox", False, res.stderr[-300:])
            continue
        time.sleep(2.5)                                          # the panels pick it up within a second or two
        n.widgets("edit", "on")
        editing(n)
        time.sleep(1.5)
        x, y, w, h = rect(n, "system")
        n.ptr.drag((x + 200, y + 200), (x + 260, y + 210))       # mid-drag guides are drawn on release too
        n.ptr.move(x + w - 16 + 60, y + 16)
        time.sleep(0.6)
        n.shot(f"edit-{theme}")
        n.widgets("edit", "cancel")
        editing(n, False)
    # the size classes: SYSTEM large, WEATHER wide, NETWORK compact, then edit mode over them
    for name, cls in (("system", "large"), ("weather", "wide"), ("network", "compact"), ("storage", "tall")):
        subprocess.run(["bromigos-panels", "size", name, cls, "--json"], env=n.env, capture_output=True, timeout=60)
    subprocess.run(["bromigos-panels", "show", "weather", "--json"], env=n.env, capture_output=True, timeout=60)
    time.sleep(3)                                                # they reload
    n.widgets("edit", "on")
    editing(n)
    time.sleep(1.5)
    n.shot("edit-sizes-tidewell")
    n.widgets("edit", "done")
    editing(n, False)
    res = n.bromigos("accessibility", "contrast", "high", "--no-reload")
    if not r.check("high contrast set in the sandbox", res.returncode == 0, (res.stdout[-300:], res.stderr[-300:])):
        return
    if res.returncode == 0:
        time.sleep(2.5)
        n.widgets("edit", "on")
        editing(n)
        time.sleep(1.5)
        n.shot("edit-high-contrast")
        n.widgets("edit", "cancel")
        editing(n, False)


def main():
    keep = "--keep" in sys.argv
    shots_dir = sys.argv[sys.argv.index("--shots") + 1] if "--shots" in sys.argv else None
    for tool in ("kwin_wayland", "dbus-run-session", "Hyprland", "lua"):
        if not shutil.which(tool):
            print(f"SKIP: needs {tool}")
            return 0
    n = WidgetsNest(keep, shots_dir)
    r = Run()
    try:
        n.start()
        scenarios(n, r)
        settings_phase(n, r)
        customize_phase(n, r)
        if shots_dir:
            shots(n, r)
    finally:
        n.stop()
        if keep:
            print(f"kept: {n.tmp}")
    failed = [x for x in r.results if not x[1]]
    print(f"\n{len(r.results) - len(failed)}/{len(r.results)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
