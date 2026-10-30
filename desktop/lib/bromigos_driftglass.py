"""DRIFTGLASS building blocks for the desktop's GLOW panels, in Cairo (package
bromigos-desktop, /usr/lib/bromigos/lib; docs/DRIFTGLASS.md): a device's hologram on its
Emitter, the Sweep, the battery cells and the signal bars. The Bluetooth panel draws with
them. Pure drawing: the colours come in as a palette (the theme's roles, hex), the time as
a number, and nothing here moves by itself.

  glyph(cr, kind, x, y, size, pal, t=0, live=False, fx=None, still=False)
      kind: controller, headset, earbuds, keyboard, mouse, phone, speaker, device.
      live: connected (it turns slowly and glows); otherwise dim and still at a fixed angle.
      fx: ("pulse", age) breathes while connecting, ("spark", age) glows once on success,
      ("fade", age) dims on a disconnect.
      still: reduced motion (nothing turns, breathes or sparks).
  radar(cr, x, y, size, pal, t, blips, still=False)
      the Sweep. blips: [(mac, rssi, age)]: where each device sits comes from its address,
      how far out from its signal; a new one rings as it appears.
  cells(cr, x, y, w, h, pct, pal, n=10)   battery cells: amber when low, red when critical
  bars(cr, x, y, h, rssi, pal)            signal strength, four bars
"""
import math
import zlib

LOW, CRITICAL = 15, 5

# Each kind as outlines (closed polylines, extruded into a slab that turns) and details
# (drawn on the front face only), in a -1..1 box, y down.


def _ellipse(cx, cy, rx, ry, n=20, a0=0.0, a1=2 * math.pi):
    return [(cx + rx * math.cos(a0 + (a1 - a0) * i / n), cy + ry * math.sin(a0 + (a1 - a0) * i / n))
            for i in range(n + 1)]


def _rect(x0, y0, x1, y1, r=0.0):
    if r <= 0:
        return [(x0, y0), (x1, y0), (x1, y1), (x0, y1), (x0, y0)]
    pts = []
    for cx, cy, a in ((x1 - r, y0 + r, -math.pi / 2), (x1 - r, y1 - r, 0), (x0 + r, y1 - r, math.pi / 2),
                      (x0 + r, y0 + r, math.pi)):
        pts += _ellipse(cx, cy, r, r, 4, a, a + math.pi / 2)
    return pts + [pts[0]]


MODELS = {
    "controller": {
        "hull": [[(-0.55, -0.42), (0.55, -0.42), (0.82, -0.3), (0.95, 0.2), (0.92, 0.45), (0.76, 0.6),
                  (0.58, 0.55), (0.36, 0.24), (-0.36, 0.24), (-0.58, 0.55), (-0.76, 0.6), (-0.92, 0.45),
                  (-0.95, 0.2), (-0.82, -0.3), (-0.55, -0.42)]],
        "detail": [_ellipse(-0.5, -0.12, 0.14, 0.14), _ellipse(0.22, 0.08, 0.12, 0.12),
                   [(-0.27, 0.08), (-0.11, 0.08)], [(-0.19, 0.0), (-0.19, 0.16)],
                   _ellipse(0.0, -0.22, 0.06, 0.06, 10)],
        "dots": [(0.52, -0.02), (0.64, -0.14), (0.4, -0.14), (0.52, -0.26)],
    },
    "headset": {
        "hull": [_rect(-0.82, 0.0, -0.46, 0.62, 0.12), _rect(0.46, 0.0, 0.82, 0.62, 0.12)],
        "detail": [_ellipse(0.0, 0.12, 0.66, 0.82, 24, math.pi * 1.02, math.pi * 1.98),
                   [(-0.64, 0.1), (-0.64, 0.52)], [(0.64, 0.1), (0.64, 0.52)]],
    },
    "earbuds": {
        "hull": [_ellipse(-0.42, -0.18, 0.26, 0.26), _ellipse(0.42, -0.18, 0.26, 0.26)],
        "detail": [[(-0.52, 0.06), (-0.5, 0.66), (-0.38, 0.66), (-0.36, 0.07)],
                   [(0.52, 0.06), (0.5, 0.66), (0.38, 0.66), (0.36, 0.07)],
                   _ellipse(-0.42, -0.18, 0.1, 0.1, 10), _ellipse(0.42, -0.18, 0.1, 0.1, 10)],
    },
    "keyboard": {
        "hull": [_rect(-0.92, -0.42, 0.92, 0.42, 0.06)],
        "detail": ([[(-0.74 + 0.185 * i, -0.24), (-0.66 + 0.185 * i, -0.24)] for i in range(9)] +
                   [[(-0.68 + 0.185 * i, -0.04), (-0.6 + 0.185 * i, -0.04)] for i in range(8)] +
                   [[(-0.4, 0.2), (0.4, 0.2)]]),
    },
    "mouse": {
        "hull": [_ellipse(0.0, 0.0, 0.42, 0.74, 28)],
        "detail": [[(0.0, -0.74), (0.0, -0.22)], [(-0.42, -0.22), (0.42, -0.22)], _rect(-0.05, -0.56, 0.05, -0.36, 0.04)],
    },
    "phone": {
        "hull": [_rect(-0.44, -0.82, 0.44, 0.82, 0.12)],
        "detail": [_rect(-0.34, -0.62, 0.34, 0.56), [(-0.1, -0.72), (0.1, -0.72)], _ellipse(0.0, 0.69, 0.05, 0.05, 8)],
    },
    "speaker": {
        "hull": [_rect(-0.48, -0.78, 0.48, 0.78, 0.1)],
        "detail": [_ellipse(0.0, 0.3, 0.3, 0.3), _ellipse(0.0, 0.3, 0.12, 0.12, 12), _ellipse(0.0, -0.4, 0.13, 0.13, 12)],
    },
    "device": {     # the Bluetooth rune
        "hull": [[(-0.36, -0.36), (0.36, 0.36), (0.0, 0.72), (0.0, -0.72), (0.36, -0.36), (-0.36, 0.36)]],
        "detail": [],
    },
}
DEPTH = 0.16


def rgb(h):
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) / 255 for i in (0, 2, 4))


def _src(cr, pal, role, a=1.0):
    r, g, b = rgb(pal.get(role) or pal.get("primary") or "#39ff14")
    cr.set_source_rgba(r, g, b, max(0.0, min(1.0, a)))


def _mix(pal, a, b, f):
    ra, rb = rgb(pal.get(a, "#39ff14")), rgb(pal.get(b, "#e8ffe0"))
    return tuple(ra[i] + (rb[i] - ra[i]) * f for i in range(3))


def _project(p, z, ang, cx, cy, s):
    x, y = p
    xr = x * math.cos(ang) + z * math.sin(ang)
    zr = -x * math.sin(ang) + z * math.cos(ang)
    k = 3.2 / (3.2 - zr)
    return cx + xr * s * k, cy + y * s * k


def _poly(cr, pts):
    cr.move_to(*pts[0])
    for p in pts[1:]:
        cr.line_to(*p)


def angle(t, live, still):
    """The slab's turn: a slow sway while connected; fixed otherwise (and under reduced motion)."""
    if not live or still:
        return -0.42
    return -0.42 + 0.5 * math.sin(t * 0.55)


def glyph(cr, kind, x, y, size, pal, t=0.0, live=False, fx=None, still=False, hc=False, lit=()):
    """A device's hologram in a size×size box at x, y. lit: indices of the model's dots to
    light (a controller's face buttons)."""
    m = MODELS.get(kind, MODELS["device"])
    cx, cy, s = x + size / 2, y + size * 0.46, size * 0.4
    ang = angle(t, live, still)
    base = 1.0 if live else 0.55
    colour = "primary" if live else "dim"
    white = 0.0
    if fx and not still:
        what, age = fx
        if what == "pulse":
            base *= 0.55 + 0.45 * (0.5 + 0.5 * math.sin(age * 7.0))
            colour = "primary"
        elif what == "spark" and age < 0.6:
            white = 1.0 - age / 0.6
        elif what == "fade" and age < 0.6:
            base = 0.55 + 0.45 * (1.0 - age / 0.6)
    elif fx and fx[0] == "pulse":
        colour = "warn"
    if not live and fx is None:
        colour = "dim"
    r, g, b = _mix(pal, colour, "white", white) if white else rgb(pal.get(colour) or pal["primary"])

    def stroke(pts_list, a, w):
        cr.set_source_rgba(r, g, b, max(0.0, min(1.0, a)))
        cr.set_line_width(w)
        for pts in pts_list:
            _poly(cr, pts)
        cr.stroke()

    # the Emitter under it: a ring and a faint beam
    cr.save()
    cr.translate(cx, y + size * 0.9)
    cr.scale(size * 0.36, size * 0.07)
    cr.arc(0, 0, 1, 0, 2 * math.pi)
    cr.restore()
    cr.set_source_rgba(r, g, b, 0.35 * base)
    cr.set_line_width(1)
    cr.stroke()
    if live and not hc:
        import cairo
        beam = cairo.LinearGradient(0, y + size * 0.9, 0, y + size * 0.1)
        beam.add_color_stop_rgba(0, r, g, b, 0.16 * base)
        beam.add_color_stop_rgba(1, r, g, b, 0.0)
        cr.move_to(cx - size * 0.36, y + size * 0.9)
        cr.line_to(cx + size * 0.36, y + size * 0.9)
        cr.line_to(cx + size * 0.46, y + size * 0.1)
        cr.line_to(cx - size * 0.46, y + size * 0.1)
        cr.close_path()
        cr.set_source(beam)
        cr.fill()

    front = [[_project(p, DEPTH, ang, cx, cy, s) for p in h] for h in m["hull"]]
    back = [[_project(p, -DEPTH, ang, cx, cy, s) for p in h] for h in m["hull"]]
    ribs = []
    for h in m["hull"]:
        step = max(1, len(h) // 6)
        for p in h[::step]:
            ribs.append([_project(p, DEPTH, ang, cx, cy, s), _project(p, -DEPTH, ang, cx, cy, s)])
    detail = [[_project(p, DEPTH, ang, cx, cy, s) for p in d] for d in m["detail"]]
    if live and not hc:                     # the glow: the same lines, wide and faint
        stroke(front + detail, 0.16 * base, 3.2)
    stroke(back, 0.28 * base, 1)
    stroke(ribs, 0.22 * base, 1)
    stroke(front, 0.95 * base, 1.2 if hc else 1)
    stroke(detail, 0.8 * base, 1)
    for i, p in enumerate(m.get("dots", [])):
        px, py = _project(p, DEPTH, ang, cx, cy, s)
        on = i in lit
        if on:
            _src(cr, pal, "white", 1.0)
        else:
            cr.set_source_rgba(r, g, b, 0.8 * base)
        cr.arc(px, py, max(1.2, size * (0.035 if on else 0.022)), 0, 2 * math.pi)
        cr.fill()


def _where(mac, rssi):
    a = (zlib.crc32(mac.encode()) % 3600) / 3600 * 2 * math.pi
    r = 0.9 if rssi is None else max(0.22, min(0.92, (-int(rssi) - 35) / 60))
    return a, r


def radar(cr, x, y, size, pal, t, blips=(), still=False, hc=False):
    """The Sweep: a scope with rings, the beam (not under reduced motion) and a blip per
    device found."""
    cx, cy, R = x + size / 2, y + size / 2, size / 2 - 1.5
    _src(cr, pal, "panel", 0.6 if not hc else 1.0)
    cr.arc(cx, cy, R, 0, 2 * math.pi)
    cr.fill()
    cr.set_line_width(1)
    for f, a in ((1.0, 0.7), (0.66, 0.35), (0.33, 0.35)):
        _src(cr, pal, "dim", a)
        cr.arc(cx, cy, R * f, 0, 2 * math.pi)
        cr.stroke()
    _src(cr, pal, "dim", 0.3)
    cr.move_to(cx - R, cy)
    cr.line_to(cx + R, cy)
    cr.move_to(cx, cy - R)
    cr.line_to(cx, cy + R)
    cr.stroke()
    sweep = (t * 2.2) % (2 * math.pi)
    if not still:
        for i in range(14):                 # the trail: thin wedges, fading behind the beam
            a0 = sweep - (i + 1) * 0.07
            cr.move_to(cx, cy)
            cr.arc(cx, cy, R, a0, a0 + 0.07)
            cr.close_path()
            _src(cr, pal, "primary", 0.22 * (1 - i / 14))
            cr.fill()
        _src(cr, pal, "primary", 0.95)
        cr.move_to(cx, cy)
        cr.line_to(cx + R * math.cos(sweep), cy + R * math.sin(sweep))
        cr.stroke()
    for mac, rssi, age in blips:
        a, r = _where(mac, rssi)
        px, py = cx + R * r * math.cos(a), cy + R * r * math.sin(a)
        if still:
            glow = 1.0
        else:
            behind = (sweep - a) % (2 * math.pi)        # how long since the beam passed it
            glow = 0.45 + 0.55 * max(0.0, 1 - behind / 2.5)
        _src(cr, pal, "primary", glow)
        cr.arc(px, py, 2.2, 0, 2 * math.pi)
        cr.fill()
        if not still and age is not None and age < 0.9:      # a new one rings as it appears
            _src(cr, pal, "white", 0.8 * (1 - age / 0.9))
            cr.arc(px, py, 2.5 + age * 9, 0, 2 * math.pi)
            cr.stroke()


def level_role(pct):
    if pct is None:
        return "muted"
    return "danger" if pct <= CRITICAL else "warn" if pct <= LOW else "primary"


def cells(cr, x, y, w, h, pct, pal, n=10, gap=2):
    """Battery cells with a cap nub on the right; lit in the level's colour."""
    nub = 2
    cw = (w - nub - 1 - gap * (n - 1)) / n
    lit = 0 if pct is None else max(1 if pct > 0 else 0, min(n, round(pct * n / 100)))
    role = level_role(pct)
    for i in range(n):
        if i < lit:
            _src(cr, pal, role, 1.0)
        else:
            _src(cr, pal, "selection", 0.95)
        cr.rectangle(round(x + i * (cw + gap)), y, max(1, round(cw)), h)
        cr.fill()
    _src(cr, pal, role if lit else "dim", 0.8)
    cr.rectangle(x + w - nub, y + h * 0.25, nub, h * 0.5)
    cr.fill()


def bars(cr, x, y, h, rssi, pal, n=4):
    """Signal strength (RSSI, dBm) in four rising bars."""
    got = 0 if rssi is None else max(1, min(n, round((int(rssi) + 100) / 12)))
    bw = 3
    for i in range(n):
        bh = h * (i + 1) / n
        _src(cr, pal, "primary" if i < got else "selection", 1.0)
        cr.rectangle(x + i * (bw + 1), y + h - bh, bw, bh)
        cr.fill()
