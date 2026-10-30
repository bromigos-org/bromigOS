#!/usr/bin/env python3
"""bromigOS's app icons: the launcher's icons for bromigOS's own windows (Settings, the
theme switcher, the decks, the panels, VECTOR …), each a bold glyph inside a ring that
echoes the burn-in (the phosphor ring, its notch at twelve o'clock, the tick ring at large
sizes) on a dark disc, so it reads on a light launcher as well as a dark one.

Drawn in code like the bar's set (build-icons.py): each glyph is a few strokes in a
10 x 10 box (centre 5,5; everything inside a radius of 5 so it clears the ring), and each
size gets its own drawing rather than a scaled one, so the strokes stay bold and the ring
crisp from 16 px up:

  16x16, 24x24, 32x32   no tick ring, strokes a pixel and a bit, the ring's notch kept
  scalable (256)        the tick ring, the glyph's glow; used from 48 px up

  theme/tools/build-app-icons.py                 write theme/app-icons/<size>/apps/bromigos-*.svg
  theme/tools/build-app-icons.py --vector DIR    write VECTOR's two (vector, gallery) into DIR
                                                 (the vector repository's assets/icons/)
  theme/tools/build-app-icons.py --sheet OUT.png a contact sheet: every icon at 16 to 256 px
                                                 on a dark and a light ground (rsvg-convert, Pillow)
  theme/tools/build-app-icons.py --check         the files on disk are what this draws (CI)

Installed into the hicolor icon theme (every icon theme inherits it): bromigOS's by
bromigos-core, VECTOR's by bromigos-vector. Run again after editing a glyph.
"""
import argparse
import math
import os
import shutil
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
OUT = os.path.join(ROOT, "theme", "app-icons")
FLAME = os.path.join(ROOT, "theme", "emblem", "flame.svg")

PHOSPHOR = "#39ff14"
DISC_IN, DISC_OUT = "#0e2a0c", "#040904"     # the dark disc: a faint glow at its centre

# the sizes drawn: (directory, canvas px, ring width, glyph scale (px per unit), glyph stroke (units))
SIZES = [
    ("16x16", 16, 1.0, 1.0, 1.25),
    ("24x24", 24, 1.5, 1.5, 1.15),
    ("32x32", 32, 2.0, 2.0, 1.05),
    ("scalable", 256, 11.0, 13.0, 0.95),
]


def P(*pts):
    """A polyline "x,y x,y …" as path data."""
    return "M" + " L".join(f"{x:.3f} {y:.3f}" for x, y in pts)


def polar(cx, cy, r, deg):
    a = math.radians(deg - 90)                    # 0 degrees at twelve o'clock, clockwise
    return cx + r * math.cos(a), cy + r * math.sin(a)


def arc(cx, cy, r, a0, a1):
    """An arc from a0 to a1 degrees (clockwise, 0 at twelve o'clock) as path data."""
    x0, y0 = polar(cx, cy, r, a0)
    x1, y1 = polar(cx, cy, r, a1)
    large = 1 if (a1 - a0) % 360 > 180 else 0
    return f"M{x0:.3f} {y0:.3f} A{r} {r} 0 {large} 1 {x1:.3f} {y1:.3f}"


def star4(cx, cy, r, waist=0.32):
    """A four-pointed star (a sparkle) as a filled path."""
    w = r * waist
    pts = [(cx, cy - r), (cx + w, cy - w), (cx + r, cy), (cx + w, cy + w),
           (cx, cy + r), (cx - w, cy + w), (cx - r, cy), (cx - w, cy - w)]
    return P(*pts) + " Z"


def hexagon(cx, cy, r, flat=False):
    off = 30 if flat else 0
    return P(*[polar(cx, cy, r, off + 60 * i) for i in range(6)]) + " Z"


def stroke(d, **kw):
    extra = "".join(f' {k.replace("_", "-")}="{v}"' for k, v in kw.items())
    return f'<path d="{d}"{extra}/>'


def fill(d, **kw):
    extra = "".join(f' {k.replace("_", "-")}="{v}"' for k, v in kw.items())
    return f'<path d="{d}" fill="currentColor" stroke="none"{extra}/>'


def circle(cx, cy, r, filled=False):
    f = ' fill="currentColor" stroke="none"' if filled else ""
    return f'<circle cx="{cx}" cy="{cy}" r="{r}"{f}/>'


def rect(x, y, w, h, filled=False):
    f = ' fill="currentColor" stroke="none"' if filled else ""
    return f'<rect x="{x}" y="{y}" width="{w}" height="{h}"{f}/>'


def flame_path():
    """The burn-in's flame (theme/emblem/flame.svg) as one path, with its own transform."""
    import re
    with open(FLAME) as f:
        text = f.read()
    d = re.search(r'<path d="([^"]+)"', text, re.S).group(1)
    return " ".join(d.split())


# ------------------------------------------------------------------ the glyphs
# Each: a list of SVG elements in the 10 x 10 box, drawn with the glyph's stroke and
# currentColor fills. Keep everything within 5 units of (5, 5).

def g_settings():
    teeth = [P(polar(5, 5, 3.0, a), polar(5, 5, 4.45, a)) for a in range(0, 360, 45)]
    return [circle(5, 5, 2.55), circle(5, 5, 0.85, True)] + [stroke(t) for t in teeth]


def g_tv():
    return [rect(1.1, 2.4, 7.8, 5.5), stroke(P((3, .8),(5, 2.4),(7, .8))),
            fill(P((4, 3.6),(6.5, 5.1),(4, 6.5)) + " Z"), stroke(P((3, 8.7),(7, 8.7)))]


def g_theme():
    # a drop of paint, half filled: the colours
    drop = "M5 0.7 C5 0.7 1.6 4.5 1.6 6.3 A3.4 3.4 0 0 0 8.4 6.3 C8.4 4.5 5 0.7 5 0.7 Z"
    return ['<clipPath id="half"><rect x="5" y="0" width="6" height="10"/></clipPath>',
            fill(drop, clip_path="url(#half)"), stroke(drop)]


def g_vector():
    # the construct's iris (the bar's VECTOR icon): an aperture and its core
    blades = [P(polar(5, 5, 4.1, a), polar(5, 5, 1.6, a + 60)) for a in range(0, 360, 120)]
    return [stroke(hexagon(5, 5, 4.1)), rect(4.05, 4.05, 1.9, 1.9, True)] + [stroke(b) for b in blades]


def g_gallery():
    # a model on its projector: a cube floating over a lit base
    cx, cy, r = 5, 4.0, 3.15
    top, ur, lr, bot, ll, ul = [polar(cx, cy, r, 60 * i) for i in range(6)]
    return [stroke(hexagon(cx, cy, r)),
            stroke(P(ul, (cx, cy), ur)), stroke(P((cx, cy), bot)),
            fill(P((2.4, 9.4), (7.6, 9.4), (6.9, 8.4), (3.1, 8.4)) + " Z")]


def g_holodeck():
    # the holo deck's arc rings round the machine
    return [stroke(arc(5, 5, 4.2, 40, 320)), stroke(arc(5, 5, 2.35, 220, 500)),
            circle(5, 5, 0.95, True)]


def g_timeline():
    return [stroke(P((0.9, 7.6), (9.1, 7.6))),
            stroke(P((0.9, 5.9), (2.7, 4.3), (4.3, 5.3), (6.1, 2.6), (7.7, 4.0), (9.1, 3.1))),
            stroke(P((6.1, 1.1), (6.1, 9.0)), stroke_width=0.7),
            fill(P((5.0, 9.6), (7.2, 9.6), (6.1, 8.3)) + " Z")]


def g_driftmap():
    # the lore's star chart: a bright star and its route to two others
    return [fill(star4(3.9, 5.6, 3.1)),
            stroke(P((5.2, 4.3), (8.3, 2.6)), stroke_width=0.55),
            stroke(P((5.3, 6.9), (7.6, 8.1)), stroke_width=0.55),
            circle(8.3, 2.6, 0.95, True), circle(7.6, 8.1, 0.8, True)]


def g_swarm():
    # agent starships in formation
    def ship(cx, cy, s):
        pts = [(0, -1.9), (1.35, 1.35), (0, 0.55), (-1.35, 1.35)]
        rot = math.radians(45)
        out = [(cx + s * (x * math.cos(rot) - y * math.sin(rot)), cy + s * (x * math.sin(rot) + y * math.cos(rot)))
               for x, y in pts]
        return fill(P(*out) + " Z")
    return [ship(6.3, 3.5, 1.3), ship(2.7, 4.6, 1.0), ship(5.5, 7.4, 1.0)]


def g_labdeck():
    # the lab's rack: three units, a light each
    out = [rect(2.0, 1.1, 6.0, 7.8)]
    out += [stroke(P((2.0, y), (8.0, y))) for y in (3.7, 6.3)]
    out += [rect(5.9, y, 1.0, 1.0, True) for y in (1.9, 4.5, 7.1)]
    out += [stroke(P((3.1, y + 0.5), (4.7, y + 0.5)), stroke_width=0.6) for y in (1.9, 4.5, 7.1)]
    return out


def g_labconsole():
    # a terminal on the lab: a prompt in a window
    return [rect(0.9, 2.0, 8.2, 6.2), stroke(P((0.9, 3.3), (9.1, 3.3)), stroke_width=0.6),
            stroke(P((2.5, 4.5), (4.0, 5.65), (2.5, 6.8))), stroke(P((4.9, 6.9), (7.2, 6.9)))]


def g_panels():
    return [rect(1.4, 1.7, 3.2, 6.6), rect(5.6, 1.7, 3.0, 2.8), rect(5.6, 5.5, 3.0, 2.8)]


def g_shortcuts():
    # a keycap, pressed: its face and the sides it sinks between
    return [rect(1.5, 1.5, 7.0, 7.0), rect(3.0, 2.6, 4.0, 3.8),
            stroke(P((1.5, 8.5), (3.0, 6.4))), stroke(P((8.5, 8.5), (7.0, 6.4)))]


def g_keylist():
    out = []
    for y in (1.6, 4.2, 6.8):
        out.append(rect(1.2, y, 1.8, 1.8, True))
        out.append(stroke(P((4.2, y + 0.9), (8.9, y + 0.9))))
    return out


def g_screensaver():
    # the moon and a star: the screen keeps watch
    R, r = 3.7, 3.1
    c1, c2 = (4.4, 5.6), (6.3, 4.0)
    d = math.dist(c1, c2)
    a = (R * R - r * r + d * d) / (2 * d)
    h = math.sqrt(max(R * R - a * a, 0))
    ux, uy = (c2[0] - c1[0]) / d, (c2[1] - c1[1]) / d
    mx, my = c1[0] + a * ux, c1[1] + a * uy
    p1 = (mx + h * uy, my - h * ux)
    p2 = (mx - h * uy, my + h * ux)
    crescent = (f"M{p1[0]:.3f} {p1[1]:.3f} A{R} {R} 0 1 0 {p2[0]:.3f} {p2[1]:.3f} "
                f"A{r} {r} 0 1 1 {p1[0]:.3f} {p1[1]:.3f} Z")
    return [fill(crescent), fill(star4(7.6, 2.6, 1.5, 0.3))]


def g_update():
    return [stroke(P((5, 0.9), (5, 6.2))), stroke(P((2.6, 3.9), (5, 6.3), (7.4, 3.9))),
            stroke(P((1.6, 6.4), (1.6, 8.5), (8.4, 8.5), (8.4, 6.4)))]


def g_extensions():
    # a puzzle piece: something that fits in
    d = ("M2.0 3.2 H3.6 A1.25 1.25 0 1 1 6.1 3.2 H7.7 V4.8 A1.25 1.25 0 1 1 7.7 7.3 V8.9 H2.0 Z")
    return [stroke(d)]


def g_notes():
    page = P((2.2, 0.9), (6.1, 0.9), (7.8, 2.6), (7.8, 9.1), (2.2, 9.1)) + " Z"
    return [stroke(page), stroke(P((6.1, 0.9), (6.1, 2.6), (7.8, 2.6)), stroke_width=0.6)] + \
        [stroke(P((3.6, y), (6.4, y))) for y in (4.3, 5.9, 7.5)]


def g_bluetooth():
    # the Bluetooth rune
    return [stroke(P((3.1, 3.4), (6.9, 6.8), (5, 8.7), (5, 1.3), (6.9, 3.2), (3.1, 6.6)))]


def g_power():
    return [stroke(arc(5, 5.3, 3.75, 38, 322)), stroke(P((5, 0.8), (5, 4.6)))]


def g_menu():
    # the burn-in's flame: the menu is bromigOS's own
    d = flame_path()
    # flame.svg's path lives in (0..20480 tenths, y flipped); its drawn extent is
    # x 525..1524, y 185..1864. Fit 8.6 units tall, centred.
    s = 8.6 / 1679
    tx, ty = 5 - s * (525 + 999 / 2), 5 - s * (185 + 1679 / 2)
    return [f'<g transform="translate({tx:.4f} {ty:.4f}) scale({s:.6f}) translate(0 2048) scale(0.1 -0.1)">'
            f'<path d="{d}" fill="currentColor" stroke="none"/></g>']


def g_ops():
    # pushes and pipelines: a branch merging back
    return [stroke(P((3.0, 2.9), (3.0, 7.1))),
            stroke("M7.0 4.1 C7.0 6.0 3.0 5.6 3.0 7.1"),
            circle(3.0, 2.0, 1.15), circle(3.0, 8.0, 1.15, True), circle(7.0, 3.2, 1.15)]


def g_netmap():
    hosts = [(4.2, 0.9), (1.2, 6.9), (7.2, 6.9)]
    out = [stroke(P((5, 5), (h[0] + 0.8, h[1] + 0.8)), stroke_width=0.6) for h in hosts]
    out += [rect(3.9, 3.9, 2.2, 2.2, True)]
    out += [rect(h[0], h[1], 1.6, 1.6) for h in hosts]
    return out


def g_mind():
    # VECTOR's memory: two lobes and their folds
    left = "M5 1.5 C3.4 0.9 1.7 1.9 1.9 3.6 C0.8 4.3 0.9 6.3 2.1 6.8 C2.1 8.3 3.7 9.2 5 8.4"
    right = "M5 1.5 C6.6 0.9 8.3 1.9 8.1 3.6 C9.2 4.3 9.1 6.3 7.9 6.8 C7.9 8.3 6.3 9.2 5 8.4"
    return [stroke(left), stroke(right), stroke(P((5, 1.5), (5, 8.4))),
            stroke("M3.0 3.9 C3.9 3.9 4.2 4.6 4.2 5.2", stroke_width=0.65),
            stroke("M7.0 5.6 C6.1 5.6 5.8 6.3 5.8 6.9", stroke_width=0.65)]


# name -> (glyph, what it is for). bromigOS's set; VECTOR's two go to the vector repository.
ICONS = {
    "bromigos-den-tv": (g_tv, "Den TV"),
    "bromigos-settings": (g_settings, "Settings"),
    "bromigos-theme": (g_theme, "the theme switcher"),
    "bromigos-shortcuts": (g_shortcuts, "Shortcuts (press the keys)"),
    "bromigos-keylist": (g_keylist, "the key list"),
    "bromigos-menu": (g_menu, "the desktop menu"),
    "bromigos-power": (g_power, "the power menu"),
    "bromigos-extensions": (g_extensions, "the extension catalog"),
    "bromigos-update": (g_update, "Update bromigOS"),
    "bromigos-bluetooth": (g_bluetooth, "Bluetooth in the terminal"),
    "bromigos-holodeck": (g_holodeck, "the holo deck"),
    "bromigos-timeline": (g_timeline, "the timeline deck"),
    "bromigos-driftmap": (g_driftmap, "the Drift map"),
    "bromigos-swarm": (g_swarm, "the swarm deck"),
    "bromigos-screensaver": (g_screensaver, "the screensaver"),
    "bromigos-panels": (g_panels, "the desktop panels"),
    "bromigos-notes": (g_notes, "FIELD NOTES"),
    "bromigos-labdeck": (g_labdeck, "the Lab deck"),
    "bromigos-labconsole": (g_labconsole, "the lab console"),
    "bromigos-ops": (g_ops, "the Ops theater"),
    "bromigos-netmap": (g_netmap, "the network map"),
    "bromigos-mind": (g_mind, "VECTOR's memory (the Mind deck)"),
}
VECTOR_ICONS = {
    "bromigos-vector": (g_vector, "VECTOR"),
    "bromigos-gallery": (g_gallery, "the hologram gallery"),
}


# ------------------------------------------------------------------ the icon
def svg(glyph, size):
    """One icon at one size: the disc, the ring, the notch (the ticks and glow when large),
    the glyph."""
    _, px, ring_w, scale, sw = size
    c = px / 2
    r_ring = c - ring_w / 2 - (0.5 if px > 32 else 0)
    big = px > 32
    out = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{px}" height="{px}" viewBox="0 0 {px} {px}">',
           "<defs>",
           f'<radialGradient id="disc" cx="50%" cy="45%" r="55%"><stop offset="0" stop-color="{DISC_IN}"/>'
           f'<stop offset="1" stop-color="{DISC_OUT}"/></radialGradient>']
    if big:
        out.append('<filter id="glow" x="-20%" y="-20%" width="140%" height="140%">'
                   '<feGaussianBlur stdDeviation="0.32"/></filter>')
    out.append("</defs>")
    out.append(f'<circle cx="{c}" cy="{c}" r="{c - (0.5 if big else 0)}" fill="url(#disc)"/>')
    out.append(f'<g fill="none" stroke="{PHOSPHOR}" color="{PHOSPHOR}" stroke-linecap="square" '
               f'stroke-linejoin="miter">')
    out.append(f'<circle cx="{c}" cy="{c}" r="{r_ring}" stroke-width="{ring_w}"/>')
    # the notch at twelve o'clock: the burn-in's mark
    notch_len = ring_w * (2.2 if big else 1.6)
    nw = ring_w * (0.8 if big else 1.0)
    top = c - r_ring
    out.append(f'<rect x="{c - nw / 2}" y="{top}" width="{nw}" height="{notch_len + ring_w / 2}" '
               f'fill="{PHOSPHOR}" stroke="none"/>')
    if big:
        r0, r1 = r_ring - ring_w * 1.9, r_ring - ring_w * 1.15
        ticks = [P(polar(c, c, r0, a), polar(c, c, r1, a)) for a in range(15, 360, 15) if a % 90]
        out.append(f'<path d="{" ".join(ticks)}" stroke-width="{ring_w * 0.36}" opacity="0.5" '
                   f'stroke-linecap="butt"/>')
    out.append("</g>")
    off = c - 5 * scale
    body = "".join(glyph())
    g_attr = (f'transform="translate({off:.3f} {off:.3f}) scale({scale})" fill="none" stroke="{PHOSPHOR}" '
              f'color="{PHOSPHOR}" stroke-width="{sw}" stroke-linecap="square" stroke-linejoin="miter"')
    if big:
        out.append(f'<g {g_attr} opacity="0.55" filter="url(#glow)">{body}</g>'.replace('id="half"', 'id="half-glow"')
                   .replace("url(#half)", "url(#half-glow)"))
    out.append(f"<g {g_attr}>{body}</g>")
    out.append("</svg>")
    return "\n".join(out) + "\n"


def write_set(icons, root):
    """{path: text} for a set: root/<size>/apps/<name>.svg, the hicolor tree, so a package
    installs it as it is."""
    files = {}
    for name, (glyph, _) in icons.items():
        for size in SIZES:
            files[os.path.join(root, size[0], "apps", name + ".svg")] = svg(glyph, size)
    return files


def contact_sheet(out_png, icons):
    """Every icon at 16, 24, 32, 48, 64, 128 and 256 px, on a dark and a light ground."""
    from PIL import Image, ImageDraw, ImageFont
    sizes = [16, 24, 32, 48, 64, 128, 256]
    with tempfile.TemporaryDirectory() as tmp:
        for p, t in write_set(icons, tmp).items():
            os.makedirs(os.path.dirname(p), exist_ok=True)
            with open(p, "w") as f:
                f.write(t)

        def pick(name, px):            # the file a theme lookup would use at px
            d = {16: "16x16", 24: "24x24", 32: "32x32"}.get(px, "scalable")
            return os.path.join(tmp, d, "apps", name + ".svg")
        try:
            font = ImageFont.truetype("/usr/share/fonts/TTF/GeistMono-Regular.ttf", 13)
        except OSError:
            font = ImageFont.load_default()
        pad, label_w = 14, 210
        col_w = [max(px, 40) + pad for px in sizes]
        row_h = 256 + 2 * pad
        width = label_w + sum(col_w) * 2 + pad * 3
        height = row_h * len(icons) + 40
        sheet = Image.new("RGB", (width, height), "#101010")
        draw = ImageDraw.Draw(sheet)
        half = label_w + sum(col_w) + pad
        draw.rectangle([half, 0, width, height], fill="#e9ece6")
        x = label_w
        for i, px in enumerate(sizes):
            for base in (x, x + sum(col_w) + pad):
                draw.text((base, 10), f"{px}", fill="#888888", font=font)
            x += col_w[i]
        for row, name in enumerate(icons):
            y0 = 40 + row * row_h
            draw.text((pad, y0 + row_h // 2 - 16), name.replace("bromigos-", ""), fill="#39ff14", font=font)
            draw.text((pad, y0 + row_h // 2 + 2), icons[name][1][:26], fill="#7a8a78", font=font)
            x = label_w
            for i, px in enumerate(sizes):
                png = os.path.join(tmp, f"{name}-{px}.png")
                subprocess.run(["rsvg-convert", "-w", str(px), "-h", str(px), pick(name, px), "-o", png], check=True)
                im = Image.open(png).convert("RGBA")
                for base in (x, x + sum(col_w) + pad):
                    sheet.paste(im, (base, y0 + (row_h - px) // 2), im)
                x += col_w[i]
        sheet.save(out_png)
    return out_png


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--vector", metavar="DIR", help="write VECTOR's icons into DIR instead")
    ap.add_argument("--sheet", metavar="OUT.png", help="draw a contact sheet of every icon")
    ap.add_argument("--check", action="store_true", help="exit 1 when the files on disk differ")
    a = ap.parse_args()
    if a.sheet:
        contact_sheet(a.sheet, {**ICONS, **VECTOR_ICONS})
        print(a.sheet)
        return 0
    icons, root = (VECTOR_ICONS, a.vector) if a.vector else (ICONS, OUT)
    files = write_set(icons, root)
    if a.check:
        stale = [p for p, t in files.items() if not os.path.exists(p) or open(p).read() != t]
        known = set(files)
        extra = [os.path.join(d, f) for d, _, fs in os.walk(root) for f in fs
                 if f.endswith(".svg") and os.path.join(d, f) not in known]
        for p in stale + extra:
            print(f"stale: {os.path.relpath(p, ROOT)} (theme/tools/build-app-icons.py)")
        return 1 if stale or extra else 0
    if not a.vector and os.path.isdir(root):
        shutil.rmtree(root)
    for p, t in files.items():
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w") as f:
            f.write(t)
    print(f"{len(files)} icons in {os.path.relpath(root, ROOT) if root.startswith(ROOT) else root}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
