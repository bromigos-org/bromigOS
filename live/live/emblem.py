"""The burn-in, loaded from the theme's emblem kit (never redrawn here).

emblem-ring.svg   ring: lines, motto band, tuning gap -> rotated in the shader
emblem-flame.svg  halo + flame + mast                   -> holds still
emblem-small.svg  dial-scale ring for icon sizes (< 64 px text is unreadable)

The kit is the current theme's (~/.local/state/bromigos/theme/current/emblem/: a world's
post has its own mark, the Wick's is the burn-in), else the dotfiles' brand/.
"""
import os

import cairo
import gi

gi.require_version("Rsvg", "2.0")
from gi.repository import Rsvg  # noqa: E402

from . import glkit  # noqa: E402

# The kit when the theme in force has none: the operator's brand folder, else the Wick's
# kit as packaged (/usr/share/bromigos/themes/wick/emblem), else a checkout's themes/.
_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.realpath(__file__))))
BRAND = next((d for d in (os.path.expanduser("~/.config/bromigos/brand"),
                          os.path.join(os.environ.get("BROMIGOS_SHARE_DIR") or "/usr/share/bromigos",
                                       "themes", "wick", "emblem"),
                          "/usr/share/bromigos/themes/wick/emblem",   # packaged, whatever the share dir
                          os.path.join(_ROOT, "themes", "wick", "emblem"))
              if os.path.isfile(os.path.join(d, "emblem-ring.svg"))), os.path.expanduser("~/.config/bromigos/brand"))


CURRENT = os.path.join(os.environ.get("XDG_STATE_HOME") or os.path.expanduser("~/.local/state"),
                       "bromigos", "theme", "current", "emblem")


def kit():
    """The emblem kit in force: the current theme's, else the brand kit."""
    return CURRENT if os.path.exists(os.path.join(CURRENT, "emblem-ring.svg")) else BRAND


def _svg(path):
    """The SVG's text; the Wick's kit under a colour theme with no kit of its own comes in
    the theme's colours (bromigos_theme.retint: each of the Wick's colours for the theme's)."""
    with open(path, encoding="utf-8") as f:
        text = f.read()
    if not path.startswith(CURRENT + os.sep):
        text = glkit.T.retint(text)
    return text


def _surface(path, size):
    h = Rsvg.Handle.new_from_data(_svg(path).encode())
    surf = cairo.ImageSurface(cairo.FORMAT_ARGB32, size, size)
    cr = cairo.Context(surf)
    vp = Rsvg.Rectangle()
    vp.x, vp.y, vp.width, vp.height = 0, 0, size, size
    h.render_document(cr, vp)
    return surf


def _png(path, size):
    src = cairo.ImageSurface.create_from_png(path)
    surf = cairo.ImageSurface(cairo.FORMAT_ARGB32, size, size)
    cr = cairo.Context(surf)
    cr.scale(size / src.get_width(), size / src.get_height())
    cr.set_source_surface(src, 0, 0)
    cr.paint()
    return surf


class Emblem:
    """GL textures for one context: ring (rotating), flame (still), small (icon)."""

    def __init__(self, size=1024, small=128, kit_dir=None):
        k = kit_dir or kit()
        ring = os.path.join(k, "emblem-ring.svg")
        flame = os.path.join(k, "emblem-flame.svg")
        sm = os.path.join(k, "emblem-small.svg")
        self.split = os.path.exists(ring) and os.path.exists(flame)
        if self.split:
            self.ring = glkit.texture_from_cairo(_surface(ring, size), mip=True)
            self.flame = glkit.texture_from_cairo(_surface(flame, size), mip=True)
        else:
            whole = os.path.join(k, "emblem-1024.png")
            self.ring = glkit.texture_from_cairo(_png(whole, size), mip=True)
            self.flame = None
        if os.path.exists(sm):
            self.small = glkit.texture_from_cairo(_surface(sm, small), mip=True)
        else:
            self.small = self.ring
