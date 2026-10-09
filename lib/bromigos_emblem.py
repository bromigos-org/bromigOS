"""The burn-in: the operator's emblem, drawn to the canonical spec in
platform/agents/LORE.md ("The burn-in (the emblem)").

Geometry in a 1000-unit viewBox (D = 1000):
  outer line   at D        (r 495, 10 thick = 0.01 D)
  inner line   at 0.80 D   (r 400, 10 thick)
  text band    between them: the motto once, clockwise, filling 300 degrees
  tuning gap   the other 60 degrees: 11 ticks, the centre one twice as tall,
               at 12 o'clock at rest
  dark halo    phosphor glow off the inner line, fading TOWARD the flame
  flame        true black with a phosphor-dim hairline, 0.50 D tall, base a
               little below centre, a relay mast cut through it
Below 64 px the text band becomes a dial scale all round ("small" variant).

Parts are exported separately (ring / flame) so anything that animates the
ring (the live layer, the lock screen) can turn it while the flame holds still.
Canon motion: counter-clockwise, one turn per ~24 s.

A post's own mark (a world theme's emblem/, LORE.md "Worlds of the Drift") is the same
emblem with that post's motto, colours, tuning gap and the sigil's surroundings: pass
`spec` (from the theme's emblem/emblem.toml, see post_spec()). Without one, every
function draws the canonical burn-in exactly as before.
"""
import json
import math
import os
import re
import xml.sax.saxutils as sx

HERE = os.path.dirname(os.path.abspath(__file__))
# The canonical burn-in's data: identity.json (the motto, caption, sign-off) and flame.svg.
# Packaged in /usr/share/bromigos/emblem (bromigos-core); from a bromigOS checkout,
# theme/emblem next to this lib/.
DATA = next((d for d in (os.environ.get("BROMIGOS_EMBLEM_DATA", ""),
                         os.path.join(os.path.dirname(HERE), "theme", "emblem"),
                         os.path.join(os.environ.get("BROMIGOS_SHARE_DIR", "/usr/share/bromigos"), "emblem"))
             if d and os.path.isfile(os.path.join(d, "flame.svg"))), "/usr/share/bromigos/emblem")
BRAND = DATA
IDENTITY = os.path.join(DATA, "identity.json")

VOID = "#000500"
PHOSPHOR = "#39ff14"
PHOSPHOR_DIM = "#159b09"
BLACK = "#000000"

C = 500.0
R_OUT, R_IN, LINE = 495.0, 400.0, 10.0
R_BAND = (R_OUT + R_IN) / 2                         # 447.5
GAP_DEG = 60.0
FLAME_H, FLAME_TOP = 500.0, 272.0                   # spans 272..772: base a little below centre


WICK = {"ring": PHOSPHOR, "hairline": PHOSPHOR_DIM, "flame": BLACK, "void": VOID,
        "gap": "ticks", "sigil": "none"}


def style(spec=None):
    """The colours and shapes in force: the burn-in's, overridden by a post's spec."""
    st = dict(WICK)
    for k, v in (spec or {}).items():
        if k == "colors":
            st.update(v)
        else:
            st[k] = v
    return st


def identity():
    try:
        with open(IDENTITY) as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


# ------------------------------------------------------------------ flame
def _flame_src():
    with open(os.path.join(BRAND, "flame.svg")) as f:
        s = f.read()
    vb = [float(v) for v in re.search(r'viewBox="([^"]+)"', s).group(1).split()]
    gt = re.search(r'<g transform="([^"]+)"', s).group(1)
    paths = re.findall(r'<path d="([^"]+)"', s)
    return vb, gt, paths


def _flame_transform():
    vb, gt, _ = _flame_src()
    k = FLAME_H / vb[3]
    x = C - vb[2] * k / 2 - vb[0] * k
    y = FLAME_TOP - vb[1] * k
    return f"translate({x:.3f},{y:.3f}) scale({k:.6f}) {gt}", k


def _mast_shapes():
    """Relay mast in emblem units: base to 60% of the flame, 3 bars narrowing upward."""
    base = FLAME_TOP + FLAME_H
    top = base - 0.60 * FLAME_H
    shapes = [(C - 9, top, 18, base - top + 6)]
    for frac, w in ((0.20, 118), (0.36, 86), (0.50, 56)):
        y = base - frac * FLAME_H
        shapes.append((C - w / 2, y - 7, w, 14))
    return shapes


def flame_svg(hairline=3.0, st=None):
    """The flame with the mast cut through it (needs the <defs> from flame_defs())."""
    st = st or WICK
    t, k = _flame_transform()
    sw = hairline / (k * 0.1)                       # potrace paths carry scale(0.1,-0.1)
    _, _, paths = _flame_src()
    d = " ".join(paths)
    mast = "".join(f'<rect x="{x:.1f}" y="{y:.1f}" width="{w:.1f}" height="{h:.1f}"/>'
                   for x, y, w, h in _mast_shapes())
    return (f'<g mask="url(#bi-mast)"><path transform="{t}" d="{d}" fill="{st['flame']}" '
            f'stroke="{st['hairline']}" stroke-width="{sw:.1f}"/></g>'
            f'<g clip-path="url(#bi-flameclip)" fill="none" stroke="{st['hairline']}" '
            f'stroke-width="{min(hairline * 2, 6):.1f}">{mast}</g>')


def flame_defs():
    t, _ = _flame_transform()
    _, _, paths = _flame_src()
    d = " ".join(paths)
    mast = "".join(f'<rect x="{x:.1f}" y="{y:.1f}" width="{w:.1f}" height="{h:.1f}" fill="black"/>'
                   for x, y, w, h in _mast_shapes())
    return (f'<mask id="bi-mast" maskUnits="userSpaceOnUse" x="0" y="0" width="1000" height="1000">'
            f'<rect x="0" y="0" width="1000" height="1000" fill="white"/>{mast}</mask>'
            f'<clipPath id="bi-flameclip"><path transform="{t}" d="{d}"/></clipPath>')


# ------------------------------------------------------------------ ring
def _tick(a_deg, r1, r2, w):
    a = math.radians(a_deg)
    return (f'<line x1="{C + r1 * math.sin(a):.2f}" y1="{C - r1 * math.cos(a):.2f}" '
            f'x2="{C + r2 * math.sin(a):.2f}" y2="{C - r2 * math.cos(a):.2f}" stroke-width="{w}"/>')


def _gap_ticks(st=None):
    st = st or WICK
    if st["gap"] == "reeds":
        return _gap_reeds(st)
    if st["gap"] == "song":
        return _gap_song(st)
    out = []
    for i in range(11):
        a = -GAP_DEG / 2 + GAP_DEG * (i + 0.5) / 11
        if i == 5:
            out.append(_tick(a, R_BAND - 36, R_BAND + 36, 7))       # centre: twice as tall
        else:
            out.append(_tick(a, R_BAND - 18, R_BAND + 18, 6))
    return f'<g stroke="{st['ring']}" stroke-linecap="butt">' + "".join(out) + "</g>"


def _gap_angles():
    return [-GAP_DEG / 2 + GAP_DEG * (i + 0.5) / 11 for i in range(11)]


def _gap_reeds(st):
    """Mire: eleven reeds leaning a little in the draught; the centre one a cattail."""
    out = []
    lean = (2.5, -1.5, 1.0, -2.0, 1.5, 0.0, -1.0, 2.0, -2.5, 1.0, -1.5)
    tall = (0.70, 0.95, 0.80, 1.00, 0.85, 0.0, 0.90, 1.00, 0.75, 0.95, 0.65)
    for i, a in enumerate(_gap_angles()):
        if i == 5:
            out.append(f'<g transform="rotate({a:.3f} {C} {C})">'
                       f'<line x1="{C}" y1="{C - R_BAND + 40:.1f}" x2="{C}" y2="{C - R_BAND - 40:.1f}" stroke-width="6"/>'
                       f'<rect x="{C - 8}" y="{C - R_BAND - 34:.1f}" width="16" height="34" rx="8" '
                       f'fill="{st['ring']}" stroke="none"/></g>')
        else:
            h = 22 * tall[i]
            x2 = C + lean[i] * 1.3
            out.append(f'<g transform="rotate({a:.3f} {C} {C})"><path d="M{C} {C - R_BAND + 20:.1f} '
                       f'Q{C} {C - R_BAND:.1f} {x2:.1f} {C - R_BAND - h:.1f}" fill="none" stroke-width="5"/></g>')
    return f'<g stroke="{st['ring']}" stroke-linecap="round">' + "".join(out) + "</g>"


def _gap_song(st):
    """Tidewell: a stretch of the Choir's song as Maren logs it, the centre bar the loudest."""
    out = []
    amp = (0.30, 0.55, 0.40, 0.75, 0.50, 1.0, 0.65, 0.45, 0.80, 0.35, 0.25)
    for i, a in enumerate(_gap_angles()):
        h = 36 * amp[i]
        out.append(_tick(a, R_BAND - h, R_BAND + h, 7 if i == 5 else 6))
    return f'<g stroke="{st['ring']}" stroke-linecap="round">' + "".join(out) + "</g>"


def _text_band(text, font, st=None):
    st = st or WICK
    chars = list(text.strip())
    n = max(1, len(chars))
    span = 360.0 - GAP_DEG
    out = []
    for i, ch in enumerate(chars):
        if ch == " ":
            continue
        a = GAP_DEG / 2 + span * (i + 0.5) / n
        out.append(f'<text x="{C}" y="{C - R_BAND + 17.5:.1f}" transform="rotate({a:.3f} {C} {C})" '
                   f'text-anchor="middle">{sx.escape(ch)}</text>')
    return (f'<g fill="{st['ring']}" font-family="{font}" font-weight="700" font-size="50">'
            + "".join(out) + "</g>")


def ring_svg(angle=0.0, ident=None, st=None):
    """Both lines + text band + tuning gap. angle in degrees (negative = counter-clockwise)."""
    st = st or WICK
    ident = ident or identity()
    ring = st["ring"]
    lines = (f'<circle cx="{C}" cy="{C}" r="{R_OUT}" fill="none" stroke="{ring}" stroke-width="{LINE}"/>'
             f'<circle cx="{C}" cy="{C}" r="{R_IN}" fill="none" stroke="{ring}" stroke-width="{LINE}"/>')
    motto = st.get("motto") or ident.get("ring_text", "")
    band = _text_band(motto, ident.get("ring_font", "Geist Mono"), st) + _gap_ticks(st)
    return f'<g transform="rotate({angle:.3f} {C} {C})">{lines}{band}</g>'


def dial_svg(angle=0.0, st=None):
    """Small-size ring (< 64 px): no text, the dial scale all round, heavier strokes."""
    st = st or WICK
    ring = st["ring"]
    out = [f'<circle cx="{C}" cy="{C}" r="{R_OUT - 15}" fill="none" stroke="{ring}" stroke-width="40"/>',
           f'<circle cx="{C}" cy="{C}" r="{R_IN - 10}" fill="none" stroke="{ring}" stroke-width="34"/>']
    ticks = []
    for i in range(24):
        if i == 0:
            ticks.append(_tick(0, R_IN - 50, R_OUT, 34))       # centre tick, twice as tall
        else:
            ticks.append(_tick(i * 15, R_IN + 16, R_OUT - 38, 20))
    return (f'<g transform="rotate({angle:.3f} {C} {C})">' + "".join(out)
            + f'<g stroke="{ring}">' + "".join(ticks) + "</g></g>")


def halo_svg(strength=0.34, reach=0.52, st=None):
    """The dark halo: glow off the inner line that drains toward the flame.
    reach = radius fraction where the glow has fully drained (smaller = closer to the flame)."""
    st = st or WICK
    ring = st["ring"]
    return (f'<radialGradient id="bi-halo" cx="{C}" cy="{C}" r="{R_IN}" gradientUnits="userSpaceOnUse">'
            f'<stop offset="0" stop-color="{ring}" stop-opacity="0"/>'
            f'<stop offset="{reach}" stop-color="{ring}" stop-opacity="0"/>'
            f'<stop offset="0.85" stop-color="{ring}" stop-opacity="{strength * 0.35:.3f}"/>'
            f'<stop offset="1" stop-color="{ring}" stop-opacity="{strength:.3f}"/></radialGradient>',
            f'<circle cx="{C}" cy="{C}" r="{R_IN}" fill="url(#bi-halo)"/>')


# ------------------------------------------------------------------ a post's sigil
# What stands round the flame at a post. The flame and its mast never change: every post
# carries the burn-in (LORE.md, "Worlds of the Drift"); the post adds where it stands.
WATERLINE = 748.0                                   # the flood line / the swell, across the flame's base


def _flood(st, small):
    """Mire: the flame scorched in just above the flood line. Still water in three ripple lines,
    the flame's reflection broken into dashes, and a Sleeper's two eye-lamps low in the water."""
    w = st.get("water", st["hairline"])
    k = 2.6 if small else 1.0
    y = WATERLINE
    lines = ((y, 300, 700, 6), (y + 22, 340, 660, 5), (y + 44, 380, 620, 4)) if not small else \
        ((y, 290, 710, 16), (y + 40, 360, 640, 13))
    out = [f'<g stroke="{w}" stroke-linecap="round" fill="none">']
    out += [f'<line x1="{x1}" y1="{yy:.1f}" x2="{x2}" y2="{yy:.1f}" stroke-width="{sw}"/>' for yy, x1, x2, sw in lines]
    out.append("</g>")
    if not small:
        # the reflection: the flame upside down, read in broken dashes, the mast a gap in each
        refl = []
        for i, (half, off) in enumerate(((78, 6), (66, 10), (54, 12), (40, 10), (28, 8), (16, 6))):
            yy = y + 60 + i * 14
            cx = C + off
            refl.append(f'<line x1="{cx - half:.1f}" y1="{yy:.1f}" x2="{cx - 12:.1f}" y2="{yy:.1f}"/>'
                        f'<line x1="{cx + 12:.1f}" y1="{yy:.1f}" x2="{cx + half:.1f}" y2="{yy:.1f}"/>')
        out.append(f'<g stroke="{w}" stroke-width="5" stroke-linecap="round" opacity="0.75">{"".join(refl)}</g>')
    eye = st.get("eyes", st["ring"])
    ex, ey, r = (322, y + 78, 9) if not small else (368, y + 66, 22)
    gap = 40 if not small else 62
    out.append(f'<g fill="{eye}"><circle cx="{ex}" cy="{ey:.1f}" r="{r * 2.4:.1f}" opacity="0.18"/>'
               f'<circle cx="{ex + gap}" cy="{ey:.1f}" r="{r * 2.4:.1f}" opacity="0.18"/>'
               f'<circle cx="{ex}" cy="{ey:.1f}" r="{r}"/><circle cx="{ex + gap}" cy="{ey:.1f}" r="{r}"/></g>')
    return "".join(out)


def _wave(y, x1, x2, amp, waves, phase=0.0):
    n = 64
    pts = []
    for i in range(n + 1):
        t = i / n
        x = x1 + (x2 - x1) * t
        yy = y + amp * math.sin(2 * math.pi * waves * t + phase)
        pts.append(f"{x:.1f},{yy:.1f}")
    return "M" + " L".join(pts)


def _swell(st, small):
    """Tidewell: the flame riding above the swell, and under it the long back of one of the
    Choir, read as a line of light."""
    w = st.get("water", st["hairline"])
    y = WATERLINE
    sw1, sw2 = (9, 7) if not small else (24, 20)
    out = [f'<g fill="none" stroke="{w}" stroke-linecap="round">'
           f'<path d="{_wave(y, 280, 720, 12, 1.5, 0.6)}" stroke-width="{sw1}"/>'
           f'<path d="{_wave(y + (30 if not small else 52), 310, 690, 10, 1.5, 2.2)}" stroke-width="{sw2}"/></g>']
    choir = st.get("choir", st["ring"])
    n, span = (15, 22) if not small else (5, 13)
    dots = []
    for i in range(n):
        t = i / (n - 1)
        a = math.radians(-span + 2 * span * t)
        R = 600
        cx = C + R * math.sin(a)
        cy = (y + 82 if not small else y + 62) + R * (1 - math.cos(a))
        r = (2.5 + 6.5 * math.sin(math.pi * t)) * (1 if not small else 2.6)
        dots.append(f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="{r:.1f}"/>')
    out.append(f'<g fill="{choir}">' + "".join(dots) + "</g>")
    return "".join(out)


SIGILS = {"flood": _flood, "swell": _swell}


def sigil_svg(st, small=False):
    f = SIGILS.get(st.get("sigil", "none"))
    return f(st, small) if f else ""


# ------------------------------------------------------------------ documents
def svg(parts=("halo", "ring", "flame"), angle=0.0, background=None, glow=False, size=1000, small=False,
        spec=None):
    """A complete SVG document. parts: any of halo, ring, flame. small=True: dial ring, heavier lines.
    spec: a post's emblem (post_spec()); None draws the burn-in."""
    st = style(spec)
    defs = flame_defs()
    body = ""
    if "halo" in parts:
        hd, hb = halo_svg(0.85, 0.18, st) if small else halo_svg(0.34, st=st)
        defs += hd
        body += hb
    ring = (dial_svg(angle, st) if small else ring_svg(angle, st=st)) if "ring" in parts else ""
    if glow and ring:
        defs += ('<filter id="bi-glow" x="-10%" y="-10%" width="120%" height="120%">'
                 '<feGaussianBlur stdDeviation="10"/></filter>')
        body += f'<g filter="url(#bi-glow)" opacity="0.7">{ring}</g>'
    body += ring
    if "flame" in parts:
        flame = flame_svg(14.0 if small else 3.0, st)
        if st.get("sigil", "none") != "none":
            # the flame stands on the water: nothing of it below the line
            defs += (f'<clipPath id="bi-above"><rect x="0" y="0" width="1000" '
                     f'height="{WATERLINE + 4:.0f}"/></clipPath>')
            flame = f'<g clip-path="url(#bi-above)">{flame}</g>' + sigil_svg(st, small)
        body += flame
    bg = f'<rect x="-60" y="-60" width="1120" height="1120" fill="{background}"/>' if background else ""
    pad = 40 if glow else 0
    return (f'<svg xmlns="http://www.w3.org/2000/svg" width="{size}" height="{size}" '
            f'viewBox="{-pad} {-pad} {1000 + 2 * pad} {1000 + 2 * pad}"><defs>{defs}</defs>{bg}{body}</svg>')


def post_spec(theme_dir):
    """A world theme's emblem/emblem.toml, its colours resolved against the theme's colors.toml
    (a value may name a role: "primary", "dim", "cyan"). None when the theme has no emblem."""
    import tomllib
    path = os.path.join(theme_dir, "emblem", "emblem.toml")
    if not os.path.exists(path):
        return None
    with open(path, "rb") as f:
        spec = tomllib.load(f)
    roles = {}
    try:
        with open(os.path.join(theme_dir, "colors.toml"), "rb") as f:
            c = tomllib.load(f)
        roles.update({k: v for k, v in c.items() if isinstance(v, str)})
        roles.update({k: v for k, v in c.get("colors", {}).items() if isinstance(v, str)})
    except OSError:
        pass

    def resolve(v, depth=0):
        if isinstance(v, str) and not v.startswith("#") and v in roles and depth < 8:
            return resolve(roles[v], depth + 1)
        return v
    spec["colors"] = {k: resolve(v) for k, v in spec.get("colors", {}).items()}
    if "void" not in spec["colors"] and "background" in roles:
        spec["colors"]["void"] = resolve("background")
    return spec


def _rsvg(svg_text, size):
    import gi
    gi.require_version("Rsvg", "2.0")
    from gi.repository import Rsvg
    import cairo
    h = Rsvg.Handle.new_from_data(svg_text.encode())
    surf = cairo.ImageSurface(cairo.FORMAT_ARGB32, size, size)
    cr = cairo.Context(surf)
    vp = Rsvg.Rectangle()
    vp.x, vp.y, vp.width, vp.height = 0, 0, size, size
    h.render_document(cr, vp)
    return surf


def render_png(svg_text, path, size):
    surf = _rsvg(svg_text, size)
    surf.write_to_png(path)
    return surf


def surface(svg_text, size):
    return _rsvg(svg_text, size)
