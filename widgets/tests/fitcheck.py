"""Draws every panel with a big fixture and says where any of them draws past its edges or
cuts a row in half (test_fit_content.py runs it; it prints JSON). Run alone to see:

    python3 widgets/tests/fitcheck.py [NAME…]

Every built-in panel (panels.CORE, with demo.py's made-up readings) and every plugin panel
(widgets/plugins, the homelab's: LAB with demo_lab.BIG_LAB, six nodes and 36 services in five
groups) is drawn at each size class's smallest size and its start size. Each plugin's own
demo readings are made big first: each list of records in them (alerts, repositories,
events, jobs, …) grown to at least 20 (bigger()).

What counts as a problem:
  * anything inked outside the panel (a recording surface's ink extents);
  * a text's box (the part its clip lets show) past the panel's edges, or under its bottom
    edge (draw.record);
  * a text cut across by a clip as wide as the panel (a list clipped mid-row), unless the
    panel scrolls (it has scroll()).

It runs in a throwaway home (plugintest's), and imports demo.py, so it runs in a process of
its own: demo.py's made-up readings never reach another test.
"""
import copy
import json
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
WIDGETS = os.path.dirname(HERE)
REPO = os.path.dirname(WIDGETS)
os.environ.setdefault("BROMIGOS_HOMELAB", os.path.join(REPO, "homelab"))
os.environ["BROMIGOS_WIDGETS_DEMO_LAB"] = "1"
os.environ["BROMIGOS_WIDGETS_DEMO_LAB_SIZE"] = "big"
sys.path.insert(0, HERE)
import plugintest  # noqa: E402,F401  (a throwaway config home, the import path)

os.environ["BROMIGOS_WIDGETS_DEMO"] = "1"
import cairo  # noqa: E402

import demo  # noqa: E402,F401  made-up readings
import draw as D  # noqa: E402
import panels as P  # noqa: E402
import plugins as PL  # noqa: E402

BIG = 20
TAGS = ("name", "title", "id", "uid", "repo", "key", "slug", "number")


def bigger(v, n=BIG):
    """v with every list of records in it (a list of two or more dicts) grown to at least n,
    each copy told apart by its name or id; other values as they are."""
    if isinstance(v, dict):
        return {k: bigger(x, n) for k, x in v.items()}
    if isinstance(v, list) and len(v) >= 2 and all(isinstance(x, dict) for x in v):
        out = [bigger(x, n) for x in v]
        i = 0
        while len(out) < max(n, len(v)):
            c = copy.deepcopy(v[i % len(v)])
            k = len(out)
            for t in TAGS:
                if isinstance(c.get(t), str):
                    c[t] = f"{c[t]} {k}"
                elif isinstance(c.get(t), int) and not isinstance(c.get(t), bool):
                    c[t] = c[t] + 1000 + k
            out.append(c)
            i += 1
        return out
    return v


def grow_demo(module):
    """The module's demo readings made big: functions named demo*/_demo* return bigger()
    data, DEMO_* lists and dicts are replaced by bigger() copies."""
    for k, v in list(vars(module).items()):
        if k.startswith(("demo", "_demo")) and callable(v) and not k.startswith(("_demo_lab", "demo_picture",
                                                                                 "demo_art")):
            def wrap(*a, _f=v, **kw):
                return bigger(_f(*a, **kw))
            setattr(module, k, wrap)
        elif k.startswith("DEMO_") and isinstance(v, (list, dict)):
            setattr(module, k, bigger(v))


def panels(only=()):
    """{name: panel}: the built-in panels and every plugin panel, made with big readings."""
    out = {}
    for name, cls in P.CORE.items():
        if not only or name in only:
            out[name] = PL.make(cls, {"name": name}, lambda p: None)
    for name, (path, _m) in sorted(PL.files().items()):
        if name in out or (only and name not in only) or name in P.CORE:
            continue
        cls, layout = PL.load(os.path.realpath(path) if "#" not in path else path)
        grow_demo(sys.modules[cls.__module__])
        out[name] = PL.make(cls, dict(layout, name=name), lambda p: None)
    for p in out.values():
        p.tick()
    time.sleep(0.6)                                  # the threads' first readings (LAB's snapshot)
    for p in out.values():
        p.tick()
    return out


def problems(panel, w, h):
    """What's wrong with the panel drawn at w x h: [words]."""
    surf = cairo.RecordingSurface(cairo.CONTENT_COLOR_ALPHA, None)
    cr = cairo.Context(surf)
    with D.record() as marks:
        panel.render(cr, w, h)
    out = []
    x, y, iw, ih = surf.ink_extents()
    if x < -2 or y < -2 or x + iw > w + 2 or y + ih > h + 2:
        out.append(f"ink outside the panel: {x:.0f},{y:.0f} {iw:.0f}x{ih:.0f}")
    scrolls = hasattr(panel, "scroll")
    for m in marks:
        x0, y0, x1, y1 = m["box"]
        c0, c1, c2, c3 = m["clip"]
        what = str(m["what"])[:40]
        v0, v1, v2, v3 = max(x0, c0), max(y0, c1), min(x1, c2), min(y1, c3)    # what the clip lets show
        if v2 <= v0 or v3 <= v1:
            continue
        if v0 < -1 or v1 < -1 or v2 > w + 1 or v3 > h - 1:
            out.append(f"{what!r} at {x0:.0f},{y0:.0f}-{x1:.0f},{y1:.0f}: past the panel's edge")
            continue
        wide = (c2 - c0) >= 0.9 * w
        cut = (y0 < c3 < y1 - 1) or (y0 + 1 < c1 < y1)
        if wide and cut and not scrolls and isinstance(m["what"], str) and m["what"] not in (
                "bar", "cells", "spark", "ring", "seg7"):
            out.append(f"{what!r} at {x0:.0f},{y0:.0f}-{x1:.0f},{y1:.0f}: cut by a clip ending at {c3:.0f}")
    return out


def sizes(panel):
    """Each class's smallest size and its start size."""
    out = []
    for name, lo, _hi, start in panel.size_classes():
        for wh in (lo, start):
            if (name, tuple(wh)) not in out:
                out.append((name, tuple(int(v) for v in wh)))
    return out


def main(only=()):
    res = {}
    for name, p in panels(only).items():
        rows = []
        for cls, (w, h) in sizes(p):
            try:
                got = problems(p, w, h)
            except Exception as e:                    # noqa: BLE001  a crash is a problem too
                got = [f"draw failed: {type(e).__name__}: {e}"]
            rows.append({"class": cls, "size": [w, h], "problems": got})
        res[name] = rows
    print(json.dumps(res))


if __name__ == "__main__":
    main(sys.argv[1:])
