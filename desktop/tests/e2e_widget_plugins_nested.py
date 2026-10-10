#!/usr/bin/env python3
"""End to end: bromigOS's built-in plugin panels (widgets/plugins/*.py) and the homelab's
(homelab/widgets/*_panels.py) in a nested Hyprland nobody sees.

It reuses e2e_widgets_nested.py's sandbox: kwin_wayland --virtual hosting a nested
Hyprland, a HOME and D-Bus of its own, and this checkout's panels with demo readings. The
homelab's widgets come from this checkout too, with the made-up lab
(BROMIGOS_WIDGETS_DEMO_LAB=1), so the ones that appear only with a homelab are listed. It
checks:

  - the widget gallery lists every built-in plugin panel as bromigOS's, with its words,
    its category and its size classes, and the homelab's as the homelab's;
  - each one can be added to the desktop: it comes up in a free spot, at its default
    size class, and draws without an error;
  - edit mode's tray shows them (with --shots, a picture of it);
  - nothing logged a traceback;
  - TWITCH's settings form (widget_form_driver.py) in its sign-in states: not set up,
    signed out, the device code shown, signed in, with a stand-in sign-in that reaches no
    service (with --shots, a picture of each).

Not part of `unittest discover` (it needs kwin_wayland, Hyprland and a GPU):

    python3 desktop/tests/e2e_widget_plugins_nested.py [--keep] [--shots DIR]
"""
import glob
import json
import os
import shutil
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from e2e_keys_nested import DESKTOP, REPO, Run, wait_for  # noqa: E402
from e2e_widgets_nested import WIDGETS, WidgetsNest, editing  # noqa: E402

BUILT_IN = sorted(os.path.basename(p)[:-3] for p in glob.glob(os.path.join(REPO, "widgets", "plugins", "*.py"))
                  if not os.path.basename(p).startswith("_"))
HOMELAB = sorted(os.path.basename(p)[:-len("_panels.py")]
                 for p in glob.glob(os.path.join(REPO, "homelab", "widgets", "*_panels.py"))
                 if os.path.basename(p) != "homelab_panels.py")


class PluginsNest(WidgetsNest):
    def __init__(self, keep=False, shots=None):
        super().__init__(keep, shots)
        # the homelab's widgets from this checkout, with the made-up lab
        with open(os.path.join(self.stubs, "bromigos-widgets"), "w") as f:
            f.write(f'#!/bin/sh\nexport BROMIGOS_WIDGETS_DEMO=1 BROMIGOS_WIDGETS_DEMO_LAB=1 '
                    f'BROMIGOS_HOMELAB={os.path.join(REPO, "homelab")}\n'
                    f'exec python3 {WIDGETS} "$@" 2>>"$HOME/widgets.err"\n')

    def gallery(self):
        res = self.widgets("gallery")
        try:
            return {w["name"]: w for w in json.loads(res.stdout or "{}").get("widgets", [])}
        except ValueError:
            return {}

    def plugin_health(self, name):
        return (self.health().get("plugins") or {}).get(name) or {}


def scenarios(n, r):
    r.check("the panels start at login, from this checkout",
            wait_for(lambda: len(n.layer_rects("bromigos-widgets")) >= 4, 30), n.layers())
    g = n.gallery()
    for name in BUILT_IN:
        e = g.get(name) or {}
        r.check(f"the gallery lists {name} as bromigOS's, with its words and size classes",
                e.get("source") == "bromigos" and e.get("description") and e.get("reads")
                and len(e.get("sizes") or e.get("size_classes") or []) >= 2 and not e.get("error"),
                {k: e.get(k) for k in ("source", "description", "reads", "error")})
    homelab = [nm for nm in g if g[nm].get("source") == "homelab"]
    r.check("the gallery lists the homelab's widgets with a homelab configured",
            all(any(h == nm or nm.startswith(h) for nm in homelab) for h in HOMELAB), (HOMELAB, homelab))
    for name in BUILT_IN + [nm for nm in homelab if nm != "lab"]:
        n.widgets("add", name)
        ok = wait_for(lambda: (n.panels().get(name) or {}).get("visible"), 8, 0.25)
        time.sleep(2.5)                                         # a draw or two, and the health file
        h = n.plugin_health(name)
        r.check(f"{name}: added to the desktop and drawing without an error",
                ok and h.get("status") == "ok" and not h.get("disabled"), (n.panels().get(name), h))
        n.shot(f"added-{name}")
        n.widgets("toggle", name)                               # off again: room for the next
        wait_for(lambda: not (n.panels().get(name) or {}).get("visible"), 5, 0.25)
    n.widgets("edit", "on")
    r.check("edit mode starts with them in the tray", editing(n), n.layers())
    time.sleep(2.0)
    n.shot("edit-tray")
    n.kb.key(64, True)                                          # F6 (evdev 64): to the tray's search
    n.kb.key(64, False)
    for i, words in enumerate(("media", "homelab", "github")):
        if i:
            for _ in range(12):
                n.kb.tap("BACKSPACE")
        n.kb.type(words)
        time.sleep(2.5)                                         # the cards draw every 2 s
        n.shot(f"edit-tray-{words}")
    n.widgets("edit", "cancel")
    editing(n, False)
    errs = open(os.path.join(n.home, "widgets.err")).read() if os.path.exists(os.path.join(n.home, "widgets.err")) else ""
    r.check("the panels logged no traceback", "Traceback" not in errs, errs[-2000:])
    log = os.path.join(n.home, ".local", "state", "bromigos", "widgets-plugins.log")
    bad = [ln for ln in (open(log).read().splitlines() if os.path.exists(log) else [])
           if any(w in ln for w in ("failed", "Traceback", "switched off", "Error"))]
    r.check("no plugin logged an error", not bad, "\n".join(bad)[-2000:])


def form(n, r, outdir):
    """Settings' form for TWITCH, in its sign-in states (widget_form_driver.py)."""
    env = dict(n.env, PYTHONPATH=os.pathsep.join([os.path.join(DESKTOP, "lib"), os.path.join(REPO, "lib"), HERE]),
               BROMIGOS_WIDGETS_DEMO="1")
    p = subprocess.run([sys.executable, os.path.join(HERE, "widget_form_driver.py"), os.path.join(DESKTOP, "settings"),
                        "twitch", outdir], env=env, capture_output=True, text=True, timeout=120)
    lines = [ln for ln in p.stdout.splitlines() if ln.startswith(("PASS", "FAIL"))]
    for ln in lines:
        r.check("form: " + ln.split(" ", 1)[1].split(" | ")[0], ln.startswith("PASS"), ln.split(" | ", 1)[-1])
    r.check("the form's driver finished", p.returncode == 0 and lines, (p.stdout[-600:], p.stderr[-1200:]))


def main():
    keep = "--keep" in sys.argv
    shots_dir = sys.argv[sys.argv.index("--shots") + 1] if "--shots" in sys.argv else None
    for tool in ("kwin_wayland", "dbus-run-session", "Hyprland", "lua"):
        if not shutil.which(tool):
            print(f"SKIP: needs {tool}")
            return 0
    n = PluginsNest(keep, shots_dir)
    r = Run()
    try:
        n.start()
        scenarios(n, r)
        form(n, r, shots_dir or os.path.join(n.tmp, "form"))
    finally:
        n.stop()
        if keep:
            print(f"kept: {n.tmp}")
    failed = [x for x in r.results if not x[1]]
    print(f"\n{len(r.results) - len(failed)}/{len(r.results)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
