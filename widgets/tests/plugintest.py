"""Helpers for the built-in plugin panels' tests: make a panel (with demo readings or
none) in a throwaway config home, draw it offscreen, and check every size class."""
import os
import sys
import tempfile

import cairo

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for p in (HERE, os.path.join(HERE, "plugins")):
    if p not in sys.path:
        sys.path.insert(0, p)

_HOME = tempfile.mkdtemp(prefix="bromigos-widget-test-")
for k, sub in (("XDG_CONFIG_HOME", ".config"), ("XDG_STATE_HOME", ".local/state"), ("XDG_CACHE_HOME", ".cache"),
               ("XDG_DATA_HOME", ".local/share")):
    os.environ.setdefault(k, os.path.join(_HOME, sub))


# Real readings unless a test asks for demo ones, even after another test imported demo.py
os.environ["BROMIGOS_WIDGETS_DEMO"] = "0"


def make(cls, demo=False, cfg=None):
    """A panel instance; demo=True draws its own made-up readings (as the picture tools do)."""
    if demo:
        os.environ["BROMIGOS_WIDGETS_DEMO"] = "1"
    try:
        return cls(cfg or {})
    finally:
        os.environ["BROMIGOS_WIDGETS_DEMO"] = "0"


def draw(panel, w, h):
    """Draw it once at w x h; returns the hover hints."""
    surf = cairo.ImageSurface(cairo.FORMAT_ARGB32, int(w), int(h))
    panel.render(cairo.Context(surf), int(w), int(h))
    return [r[4] for r in panel.regions]


def every_class(test, panel):
    """Draw at each size class's smallest and largest size: a hint on every region, every
    region inside the panel."""
    for name, lo, hi, _start in panel.size_classes():
        for w, h in (lo, hi):
            draw(panel, w, h)
            test.assertTrue(panel.regions, f"{name} {w}x{h}: no hover regions")
            for r in panel.regions:
                test.assertTrue((r[4] or "").strip(), f"{name} {w}x{h}: a region without a hint")
                test.assertTrue(r[0] >= -1 and r[1] >= -1 and r[0] + r[2] <= w + 1 and r[1] + r[3] <= h + 1,
                                f"{name} {w}x{h}: region out of bounds {r[:4]} ({r[4][:40]})")
