"""Cairo/Pango primitives in the Bromigos vocabulary: panel frames with targeting
brackets, 1px vector rules, wide-tracked uppercase labels, segment numerals,
fuel-cell bars and ring gauges. No scanlines or vignettes here: the desktop UI
stays crisp; atmosphere lives in the wallpaper and the lock screen."""
import math
import os
import sys

import gi

gi.require_version("Pango", "1.0")
gi.require_version("PangoCairo", "1.0")
from gi.repository import Pango, PangoCairo  # noqa: E402

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.realpath(__file__))), "lib"))
import bromigos_theme as T  # noqa: E402

# The Wick's names for the colours. The theme in force supplies them
# (bromigos_theme: phosphor is the theme's primary, amber its warn, …).
PAL = {
    "void": "#000500", "panel": "#001300", "guard": "#003b00",
    "phosphor": "#39ff14", "soft": "#9cff8a", "dim": "#159b09",
    "amber": "#d4af37", "danger": "#ff766f", "rust": "#4a0e0e",
    "static": "#7e927e",
}
FONT = "Geist Mono"
PANEL_ALPHA = 0.84


def rgb(name):
    """A colour by its Wick name, theme role or "#rrggbb", in the theme in force."""
    return T.rgb(name)


def src(cr, name, a=1.0):
    r, g, b = rgb(name)
    if a >= 0.3 and T.high_contrast():
        a = a + (1.0 - a) * 0.75               # high contrast: rules and plates near solid
    cr.set_source_rgba(r, g, b, a)


def level(v, warn, crit):
    """Colour for a reading: phosphor, amber at warn, danger at crit."""
    if v is None:
        return "static"
    if v >= crit:
        return "danger"
    if v >= warn:
        return "amber"
    return "phosphor"


# ----------------------------------------------------------------- text
_fd_cache = {}


def _fd(size, weight):
    k = (size, weight)
    if k not in _fd_cache:
        fd = Pango.FontDescription.from_string(f"{FONT} {size}px")
        fd.set_absolute_size(size * Pango.SCALE)
        fd.set_weight({"regular": Pango.Weight.NORMAL, "medium": Pango.Weight.MEDIUM,
                       "semibold": Pango.Weight.SEMIBOLD, "bold": Pango.Weight.BOLD}[weight])
        _fd_cache[k] = fd
    return _fd_cache[k]


def layout(cr, s, size=11, weight="medium", spacing=0.0, width=None, wrap=False):
    lay = PangoCairo.create_layout(cr)
    lay.set_font_description(_fd(size, weight))
    if spacing:
        attrs = Pango.AttrList()
        attrs.insert(Pango.attr_letter_spacing_new(int(size * spacing * Pango.SCALE)))
        lay.set_attributes(attrs)
    if width:
        lay.set_width(int(width * Pango.SCALE))
        if wrap:                                  # wrap onto more lines instead of "…"
            lay.set_wrap(Pango.WrapMode.WORD_CHAR)
        else:
            lay.set_ellipsize(Pango.EllipsizeMode.END)
    lay.set_text(s, -1)
    return lay


def text(cr, x, y, s, size=11, color="soft", weight="medium", spacing=0.0, align="left",
         glow=False, alpha=1.0, width=None, wrap=False):
    """Draw s with its top-left (or top-right/centre) at x,y. Returns (w, h)."""
    lay = layout(cr, s, size, weight, spacing, width, wrap)
    w, h = lay.get_pixel_size()
    if align == "right":
        x -= w
    elif align == "center":
        x -= w / 2
    cr.move_to(round(x), round(y))
    if glow and not T.high_contrast():          # high contrast: no halo behind the letters
        PangoCairo.layout_path(cr, lay)
        src(cr, color, 0.22 * alpha)
        cr.set_line_width(2.6)
        cr.stroke()
        cr.move_to(round(x), round(y))
    src(cr, color, alpha)
    PangoCairo.show_layout(cr, lay)
    return w, h


def label(cr, x, y, s, color="dim", size=11, align="left", alpha=1.0):
    size = max(size, 10)
    """Small uppercase monospace label, wide tracking (0.18em)."""
    return text(cr, x, y, s.upper(), size=size, color=color, weight="semibold",
                spacing=0.18, align=align, alpha=alpha)


# ----------------------------------------------------------------- frame
def frame(cr, w, h, title, right=None, right_color="static"):
    """Panel: translucent panel fill, 1px rule, targeting brackets, header rule."""
    src(cr, "panel", 1.0 if T.high_contrast() else PANEL_ALPHA)   # high contrast: opaque
    cr.rectangle(0, 0, w, h)
    cr.fill()
    cr.set_line_width(1)
    src(cr, "dim", 0.45)
    cr.rectangle(0.5, 0.5, w - 1, h - 1)
    cr.stroke()
    brackets(cr, 0, 0, w, h, 14, "phosphor", 2)
    label(cr, 16, 10, title, color="phosphor", size=12)
    if right:
        label(cr, w - 16, 12, right, color=right_color, size=11, align="right")
    src(cr, "dim", 0.45)
    cr.move_to(12, 33.5)
    cr.line_to(w - 12, 33.5)
    cr.stroke()
    return 44  # content top


def brackets(cr, x, y, w, h, n=10, color="phosphor", lw=1.5, alpha=1.0):
    src(cr, color, alpha)
    cr.set_line_width(lw)
    o = lw / 2
    for (px, py, dx, dy) in ((x + o, y + o, 1, 1), (x + w - o, y + o, -1, 1),
                             (x + o, y + h - o, 1, -1), (x + w - o, y + h - o, -1, -1)):
        cr.move_to(px, py + dy * n)
        cr.line_to(px, py)
        cr.line_to(px + dx * n, py)
    cr.stroke()


def rule(cr, x1, y, x2, color="dim", alpha=0.45):
    src(cr, color, alpha)
    cr.set_line_width(1)
    cr.move_to(x1, round(y) + 0.5)
    cr.line_to(x2, round(y) + 0.5)
    cr.stroke()


def dot(cr, x, y, r, color, glow=True):
    cr.new_path()
    if glow:
        src(cr, color, 0.25)
        cr.arc(x, y, r * 2.2, 0, 2 * math.pi)
        cr.fill()
    src(cr, color)
    cr.arc(x, y, r, 0, 2 * math.pi)
    cr.fill()


# ----------------------------------------------------------------- bars and gauges
def cells(cr, x, y, w, h, frac, n=24, warn=0.75, crit=0.9, gap=2):
    """Segmented 'fuel cell' bar. Lit cells take the colour of their own threshold."""
    frac = 0 if frac is None else max(0.0, min(1.0, frac))
    cw = (w - gap * (n - 1)) / n
    lit = frac * n
    for i in range(n):
        cx = x + i * (cw + gap)
        pos = (i + 1) / n
        col = "danger" if pos > crit else "amber" if pos > warn else "phosphor"
        if i < int(lit) or (i == int(lit) and lit - int(lit) > 0.5):
            src(cr, col, 1.0)
        else:
            src(cr, "guard", 0.9)
        cr.rectangle(round(cx), y, max(1, round(cw)), h)
        cr.fill()


def bar(cr, x, y, w, h, frac, color="phosphor"):
    src(cr, "guard", 0.9)
    cr.rectangle(x, y, w, h)
    cr.fill()
    if frac:
        src(cr, color)
        cr.rectangle(x, y, max(1, w * max(0, min(1, frac))), h)
        cr.fill()


def ring(cr, cx, cy, r, frac, width=6, color="phosphor", dashed=False):
    """Arc gauge from 12 o'clock clockwise with 24 vector ticks around it."""
    cr.new_path()
    cr.set_line_width(width)
    src(cr, "guard", 0.95)
    if dashed:
        cr.set_dash([3, 4])
    cr.arc(cx, cy, r, 0, 2 * math.pi)
    cr.stroke()
    cr.set_dash([])
    if frac:
        src(cr, color)
        cr.new_path()
        cr.arc(cx, cy, r, -math.pi / 2, -math.pi / 2 + 2 * math.pi * max(0, min(1, frac)))
        cr.stroke()
    cr.set_line_width(1)
    src(cr, "dim", 0.6)
    for i in range(24):
        a = i / 24 * 2 * math.pi
        r1, r2 = r + width / 2 + 2, r + width / 2 + (6 if i % 6 == 0 else 4)
        cr.move_to(cx + r1 * math.sin(a), cy - r1 * math.cos(a))
        cr.line_to(cx + r2 * math.sin(a), cy - r2 * math.cos(a))
    cr.stroke()


def spark(cr, x, y, w, h, values, color="phosphor", lo=None, hi=None, fill=True):
    """A sparkline of values (oldest first) in the box; lo/hi fix the scale (else the data's)."""
    vals = [v for v in values if v is not None]
    if len(vals) < 2:
        return
    lo = min(vals) if lo is None else lo
    hi = max(vals) if hi is None else hi
    span = (hi - lo) or 1.0
    n = len(values)
    pts = [(x + w * i / (n - 1), y + h - h * (max(lo, min(hi, v)) - lo) / span)
           for i, v in enumerate(values) if v is not None]
    cr.new_path()
    cr.move_to(*pts[0])
    for p in pts[1:]:
        cr.line_to(*p)
    if fill:
        src(cr, color, 0.12)
        cr.line_to(pts[-1][0], y + h)
        cr.line_to(pts[0][0], y + h)
        cr.close_path()
        cr.fill()
        cr.move_to(*pts[0])
        for p in pts[1:]:
            cr.line_to(*p)
    src(cr, color)
    cr.set_line_width(1.5)
    cr.stroke()
    cr.set_line_width(1)


# ----------------------------------------------------------------- segment numerals
_SEG = {  # a b c d e f g
    "0": "abcdef", "1": "bc", "2": "abged", "3": "abgcd", "4": "fgbc", "5": "afgcd",
    "6": "afgedc", "7": "abc", "8": "abcdefg", "9": "abcdfg", "-": "g", " ": "",
}


def seg7(cr, x, y, h, s, color="phosphor", ghost=True, glow=True):
    """Seven-segment numerals (digits, '-', '.', '%'). Unlit segments show as ghosts.
    Returns the drawn width."""
    w = h * 0.52
    t = max(2.0, h * 0.11)
    sk = h * 0.08                       # italic skew
    gap = h * 0.16
    cx = x

    def seg(px, py, horiz, length):
        cr.save()
        cr.translate(px, py)
        if horiz:
            pts = [(0, 0), (t / 2, -t / 2), (length - t / 2, -t / 2), (length, 0),
                   (length - t / 2, t / 2), (t / 2, t / 2)]
        else:
            pts = [(0, 0), (-t / 2, t / 2), (-t / 2, length - t / 2), (0, length),
                   (t / 2, length - t / 2), (t / 2, t / 2)]
        cr.move_to(*pts[0])
        for p in pts[1:]:
            cr.line_to(*p)
        cr.close_path()
        cr.restore()

    def skew(px, py):
        return px + sk * (1 - (py - y) / h), py

    for ch in s:
        if ch == ".":
            src(cr, color)
            px, py = skew(cx + t * 0.2, y + h - t / 2)
            cr.rectangle(px - t / 2, py - t / 2, t, t)
            cr.fill()
            cx += t * 1.6
            continue
        if ch == "%":
            # vector percent: two small rings and a slash, at 60% height
            src(cr, color)
            cr.set_line_width(max(1.5, t * 0.6))
            ph = h * 0.6
            ox, oy = cx + 2, y + h - ph
            cr.arc(ox + ph * 0.18, oy + ph * 0.18, ph * 0.13, 0, 2 * math.pi)
            cr.stroke()
            cr.arc(ox + ph * 0.62, oy + ph * 0.82, ph * 0.13, 0, 2 * math.pi)
            cr.stroke()
            cr.move_to(ox + ph * 0.72, oy)
            cr.line_to(ox + ph * 0.08, oy + ph)
            cr.stroke()
            cx += ph * 0.9 + gap
            continue
        on = _SEG.get(ch, "")
        half = h / 2
        L = w - t
        geo = {
            "a": (cx + t / 2, y, True, L), "g": (cx + t / 2, y + half, True, L),
            "d": (cx + t / 2, y + h, True, L),
            "f": (cx, y + t / 2, False, half - t), "b": (cx + w, y + t / 2, False, half - t),
            "e": (cx, y + half + t / 2, False, half - t), "c": (cx + w, y + half + t / 2, False, half - t),
        }
        for k, (px, py, horiz, length) in geo.items():
            lit = k in on
            if not lit and not ghost:
                continue
            sx, sy = skew(px, py)
            cr.save()
            # apply skew for vertical segments by shearing about their top
            if not horiz:
                m = cr.get_matrix()
                cr.translate(sx, sy)
                import cairo as _c
                cr.transform(_c.Matrix(1, 0, -sk / h, 1, 0, 0))
                cr.translate(-sx, -sy)
                del m
            seg(sx, sy, horiz, length)
            cr.restore()
            if lit:
                if glow:
                    src(cr, color, 0.25)
                    cr.set_line_width(3)
                    cr.stroke_preserve()
                src(cr, color)
            else:
                src(cr, "guard", 0.35)
            cr.fill()
        cx += w + gap
    return cx - x - gap
