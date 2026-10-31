#!/usr/bin/env python3
"""bromigOS's text console font and colours (docs/console.md): Geist Mono as Linux console
fonts, and a theme's terminal colours as the console's 16-colour palette.

  build-console-font.py --out DIR [--font-dir /usr/share/fonts/TTF] [--theme-dir themes/wick]

Writes, into DIR:
  bromigos-geist-16.psf.gz, -24, -32   Geist Mono as PSF2 fonts (8x16, 12x24, 16x32 cells),
                                       512 glyphs with a Unicode table: ASCII, Latin-1, the
                                       box drawing and block characters text interfaces draw
                                       panels with, and the arrows, dots and marks bromigOS's
                                       commands print
  palette.vtrgb                        the theme's [terminal] color0..color15 as setvtrgb reads
                                       them (three lines of 16 decimal values: red, green, blue)
  kmscon.conf                          kmscon's settings: Geist Mono (sized for the screen), the
                                       same 16 colours in true colour, and its foreground and
                                       background (docs/console.md, "The console")

The kernel's console takes at most 512 glyphs, so the font is a chosen set; a character
outside it shows as a box. The `bromigos-boot` package runs this at build time.
"""

import argparse
import gzip
import importlib.machinery
import importlib.util
import os
import struct
import sys

from PIL import Image, ImageDraw, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))

# cell width, cell height, the TrueType size that fills the cell, the baseline's row
SIZES = {16: (8, 16, 13, 12), 24: (12, 24, 20, 18), 32: (16, 32, 26, 24)}
MAX_GLYPHS = 512


# CP437's pictures in 0x00..0x1F (Python's cp437 codec gives control characters there);
# position 0 (␀) stays blank
CP437_LOW = "\u2400☺☻♥♦♣♠•◘○◙♂♀♪♫☼►◄↕‼¶§▬↨↑↓→←∟↔▲▼"


def charset():
    """The characters, in the font's order (the first 256 are code page 437's own layout for
    those that have a place there, so early boot's 8-bit output still reads)."""
    want = []
    seen = set()

    def add(cp):
        if cp not in seen:
            seen.add(cp)
            want.append(cp)

    # the first 256 in code page 437's own order, so a glyph's position is its CP437 byte: the
    # kernel draws an erased cell with position 32 directly (a space), and early boot's
    # 8-bit output reads right
    for b in range(256):
        add(ord(CP437_LOW[b]) if b < 0x20 else ord(bytes([b]).decode("cp437")))
    for cp in range(0x20, 0x7F):
        add(cp)
    for cp in range(0xA0, 0x100):               # Latin-1
        add(cp)
    for cp in range(0x2500, 0x2580):            # box drawing: Textual's and ratatui's borders
        add(cp)
    for cp in range(0x2580, 0x25A0):            # block elements: half blocks, shades, meters
        add(cp)
    for cp in (0x2010, 0x2011, 0x2012, 0x2013, 0x2014, 0x2015, 0x2018, 0x2019, 0x201C, 0x201D,
               0x2020, 0x2021, 0x2022, 0x2026, 0x2030, 0x2032, 0x2033, 0x2039, 0x203A, 0x203C,
               0x20AC, 0x2122, 0x2190, 0x2191, 0x2192, 0x2193, 0x2194, 0x2195, 0x21B5, 0x21BA,
               0x21BB, 0x21D0, 0x21D2, 0x2026, 0x2212, 0x2219, 0x221A, 0x221E, 0x2248, 0x2260,
               0x2264, 0x2265, 0x2303, 0x2318, 0x2325, 0x232B, 0x23CE, 0x23F5, 0x23F4, 0x23F6,
               0x23F7, 0x23F8, 0x23F9, 0x23FA, 0x25A0, 0x25A1, 0x25AA, 0x25AB, 0x25B2, 0x25B3,
               0x25B4, 0x25B6, 0x25B8, 0x25BA, 0x25BC, 0x25BD, 0x25BE, 0x25C0, 0x25C2, 0x25C4,
               0x25C6, 0x25C7, 0x25CB, 0x25CF, 0x25D0, 0x25D1, 0x25E2, 0x25E3, 0x25E4, 0x25E5,
               0x2605, 0x2606, 0x2610, 0x2611, 0x2612, 0x2630, 0x2713, 0x2714, 0x2715, 0x2716,
               0x2717, 0x2718, 0x2726, 0x2731, 0x2771, 0x27E8, 0x27E9, 0x2800, 0x2B24, 0x00B7,
               0x2027, 0x22C5, 0x2016, 0x2236, 0x2502, 0x2E3A, 0x2E3B, 0x2581, 0x2594, 0x258F,
               0x2595, 0x0152, 0x0153, 0x0160, 0x0161, 0x0178, 0x017D, 0x017E, 0x0192, 0x02C6,
               0x02DC, 0x0391, 0x0393, 0x0398, 0x03A3, 0x03A6, 0x03A9, 0x03B1, 0x03B4, 0x03B5,
               0x03C0, 0x03C3, 0x03C4, 0x03C6, 0x2070, 0x00B9, 0x2074, 0x2075, 0x2076, 0x2077,
               0x2078, 0x2079, 0x2080, 0x2081, 0x2082, 0x2083, 0x2084, 0x207F, 0x2105, 0x2116,
               0x2153, 0x2154, 0x215B, 0x2160, 0x2161, 0x2162, 0x2163, 0x2164, 0x2302, 0x2310,
               0x2320, 0x2321, 0xFFFD):
        add(cp)
    return want[:MAX_GLYPHS]


def render(font, ch, w, h, base, ascent):
    cell = Image.new("1", (w, h), 0)
    if not ch.strip() and ch != "⠀":
        return cell
    d = ImageDraw.Draw(cell)
    d.fontmode = "1"
    adv = font.getlength(ch)
    d.text((round((w - adv) / 2), base - ascent), ch, font=font, fill=1)
    return cell


def box_glyph(cp, w, h):
    """Box drawing and block characters drawn to the cell's edges, so lines join from cell to
    cell (a font's own glyphs stop short of them at small sizes). None: not one of these."""
    im = Image.new("1", (w, h), 0)
    d = ImageDraw.Draw(im)
    t = max(1, w // 8)                       # a light line's thickness
    T = max(2, t * 2)                        # a heavy one's
    cx, cy = w // 2, h // 2

    def hline(x0, x1, th, y=cy):
        d.rectangle((x0, y - th // 2, x1, y - th // 2 + th - 1), fill=1)

    def vline(y0, y1, th, x=cx):
        d.rectangle((x - th // 2, y0, x - th // 2 + th - 1, y1), fill=1)

    # light/heavy lines and corners: (left, right, up, down) weights, 0 none, 1 light, 2 heavy
    arms = {
        0x2500: (1, 1, 0, 0), 0x2501: (2, 2, 0, 0), 0x2502: (0, 0, 1, 1), 0x2503: (0, 0, 2, 2),
        0x250C: (0, 1, 0, 1), 0x250F: (0, 2, 0, 2), 0x2510: (1, 0, 0, 1), 0x2513: (2, 0, 0, 2),
        0x2514: (0, 1, 1, 0), 0x2517: (0, 2, 2, 0), 0x2518: (1, 0, 1, 0), 0x251B: (2, 0, 2, 0),
        0x251C: (0, 1, 1, 1), 0x2523: (0, 2, 2, 2), 0x2524: (1, 0, 1, 1), 0x252B: (2, 0, 2, 2),
        0x252C: (1, 1, 0, 1), 0x2533: (2, 2, 0, 2), 0x2534: (1, 1, 1, 0), 0x253B: (2, 2, 2, 0),
        0x253C: (1, 1, 1, 1), 0x254B: (2, 2, 2, 2),
        0x2574: (1, 0, 0, 0), 0x2575: (0, 0, 1, 0), 0x2576: (0, 1, 0, 0), 0x2577: (0, 0, 0, 1),
        0x2578: (2, 0, 0, 0), 0x2579: (0, 0, 2, 0), 0x257A: (0, 2, 0, 0), 0x257B: (0, 0, 0, 2),
        0x257C: (1, 2, 0, 0), 0x257D: (0, 0, 1, 2), 0x257E: (2, 1, 0, 0), 0x257F: (0, 0, 2, 1),
    }
    if cp in (0x2713, 0x2714):              # a tick (Geist Mono has none)
        th = t if cp == 0x2713 else T
        d.line((w // 8, h // 2, w * 3 // 8, h * 3 // 4, w - 1 - w // 8, h // 4), fill=1, width=th)
        return im
    if cp in (0x2715, 0x2716, 0x2717, 0x2718):   # a cross
        th = t if cp in (0x2715, 0x2717) else T
        d.line((w // 8, h // 4, w - 1 - w // 8, h * 3 // 4), fill=1, width=th)
        d.line((w // 8, h * 3 // 4, w - 1 - w // 8, h // 4), fill=1, width=th)
        return im
    if cp in arms:
        left, right, up, down = arms[cp]
        for weight, fn in ((left, lambda th: hline(0, cx, th)), (right, lambda th: hline(cx, w - 1, th)),
                           (up, lambda th: vline(0, cy, th)), (down, lambda th: vline(cy, h - 1, th))):
            if weight:
                fn(t if weight == 1 else T)
        return im
    # rounded corners (Textual's "round" border): drawn as arcs meeting the edges
    # rounded corners (Textual's "round" border): a quarter circle, then straight to the edges
    rounded = {0x256D: (1, 1, 180), 0x256E: (-1, 1, 270), 0x256F: (-1, -1, 0), 0x2570: (1, -1, 90)}
    if cp in rounded:
        sx, sy, a0 = rounded[cp]
        r = max(2, w // 3)
        ox, oy = cx + sx * r, cy + sy * r
        d.arc((ox - r, oy - r, ox + r, oy + r), a0, a0 + 90, fill=1, width=t)
        hline(min(ox, w - 1) if sx > 0 else 0, w - 1 if sx > 0 else max(ox, 0), t)
        vline(min(oy, h - 1) if sy > 0 else 0, h - 1 if sy > 0 else max(oy, 0), t)
        return im
    # double lines
    doubles = {0x2550: "h", 0x2551: "v", 0x2554: "dr", 0x2557: "dl", 0x255A: "ur", 0x255D: "ul"}
    if cp in doubles:
        g = max(2, t * 2)
        k = doubles[cp]
        if k == "h":
            hline(0, w - 1, t, cy - g // 2 - t // 2)
            hline(0, w - 1, t, cy + g // 2 + t // 2)
        elif k == "v":
            vline(0, h - 1, t, cx - g // 2 - t // 2)
            vline(0, h - 1, t, cx + g // 2 + t // 2)
        else:
            xo, yo = cx - g // 2 - t // 2, cy - g // 2 - t // 2
            xi, yi = cx + g // 2 + t // 2, cy + g // 2 + t // 2
            if k == "dr":
                hline(xo, w - 1, t, yo); vline(yo, h - 1, t, xo); hline(xi, w - 1, t, yi); vline(yi, h - 1, t, xi)
            elif k == "dl":
                hline(0, xi, t, yo); vline(yo, h - 1, t, xi); hline(0, xo, t, yi); vline(yi, h - 1, t, xo)
            elif k == "ur":
                hline(xo, w - 1, t, yi); vline(0, yi, t, xo); hline(xi, w - 1, t, yo); vline(0, yo, t, xi)
            elif k == "ul":
                hline(0, xi, t, yi); vline(0, yi, t, xi); hline(0, xo, t, yo); vline(0, yo, t, xo)
        return im
    # block elements: eighths from the bottom and the left, halves, quadrants, shades
    if 0x2581 <= cp <= 0x2588:
        n = cp - 0x2580
        d.rectangle((0, h - round(h * n / 8), w - 1, h - 1), fill=1)
        return im
    if 0x2589 <= cp <= 0x258F:
        n = 0x2590 - cp
        d.rectangle((0, 0, round(w * n / 8) - 1, h - 1), fill=1)
        return im
    simple = {
        0x2580: (0, 0, w, h // 2), 0x2590: (w // 2, 0, w, h), 0x2594: (0, 0, w, max(1, h // 8)),
        0x2595: (w - max(1, w // 8), 0, w, h), 0x2596: (0, h // 2, w // 2, h), 0x2597: (w // 2, h // 2, w, h),
        0x2598: (0, 0, w // 2, h // 2), 0x259D: (w // 2, 0, w, h // 2),
    }
    if cp in simple:
        x0, y0, x1, y1 = simple[cp]
        d.rectangle((x0, y0, x1 - 1, y1 - 1), fill=1)
        return im
    quads = {0x2599: "tl bl br", 0x259A: "tl br", 0x259B: "tl tr bl", 0x259C: "tl tr br", 0x259E: "tr bl", 0x259F: "tr bl br"}
    if cp in quads:
        box = {"tl": (0, 0), "tr": (w // 2, 0), "bl": (0, h // 2), "br": (w // 2, h // 2)}
        for q in quads[cp].split():
            x, y = box[q]
            d.rectangle((x, y, x + w // 2 - 1, y + h // 2 - 1), fill=1)
        return im
    if cp in (0x2591, 0x2592, 0x2593):
        step = {0x2591: 4, 0x2592: 2, 0x2593: 0}[cp]
        for y in range(h):
            for x in range(w):
                on = (x + y) % 2 == 0 if step == 2 else ((x % 2 == 0 and y % 2 == 0) if step == 4 else not (x % 2 == 1 and y % 2 == 1))
                if on:
                    im.putpixel((x, y), 1)
        return im
    return None


def build_font(font_dir, size):
    w, h, pt, base = SIZES[size]
    font = ImageFont.truetype(os.path.join(font_dir, "GeistMono-Regular.ttf"), pt)
    ascent, _ = font.getmetrics()
    notdef = render(font, "\U000F0000", w, h, base, ascent).tobytes()
    cps = charset()
    rowbytes = (w + 7) // 8
    glyphs, table = bytearray(), bytearray()
    for cp in cps:
        ch = chr(cp)
        cell = box_glyph(cp, w, h)
        if cell is None:
            cell = render(font, ch, w, h, base, ascent)
            if cell.tobytes() == notdef and ch.strip():
                if len(table) and cps.index(cp) >= 256:
                    continue                                  # Geist Mono hasn't it: left out
                cell = Image.new("1", (w, h), 0)              # in CP437's 256: kept, blank
        for y in range(h):
            for xb in range(rowbytes):
                byte = 0
                for bit in range(8):
                    x = xb * 8 + bit
                    if x < w and cell.getpixel((x, y)):
                        byte |= 0x80 >> bit
                glyphs.append(byte)
        table += ch.encode("utf-8") + b"\xff"
    n = len(glyphs) // (rowbytes * h)
    # pad to 256 or 512 glyphs: the kernel takes those counts best
    target = 256 if n <= 256 else 512
    glyphs += bytes(rowbytes * h * (target - n))
    table += b"\xff" * (target - n)
    header = struct.pack("<IIIIIIII", 0x864AB572, 0, 32, 0x01, target, rowbytes * h, h, w)
    return header + bytes(glyphs) + bytes(table), n


def grub_theme():
    path = os.path.join(REPO, "settings", "grub", "build-grub-theme.py")
    loader = importlib.machinery.SourceFileLoader("build_grub_theme", path)
    spec = importlib.util.spec_from_loader("build_grub_theme", loader)
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    return mod


KMSCON_NAMES = ["black", "red", "green", "yellow", "blue", "magenta", "cyan", "light-grey", "dark-grey",
                "light-red", "light-green", "light-yellow", "light-blue", "light-magenta", "light-cyan", "white"]


def kmscon_conf(vtrgb):
    rows = [list(map(int, line.split(","))) for line in vtrgb.strip().splitlines()]
    rgb = list(zip(*rows))
    lines = ["# kmscon for bromigOS (package bromigos-boot; docs/console.md): DRIFTGLASS on the Wick,",
             "# Geist Mono through pango, which falls back to Symbols Nerd Font for the screens' icons;\n# sized by kmscon for the screen (font-size 0).",
             "font-engine=pango", "font-name=Geist Mono", "font-size=0",
             "term=xterm-256color", "palette=custom"]
    lines += [f"palette-{n}={c[0]},{c[1]},{c[2]}" for n, c in zip(KMSCON_NAMES, rgb)]
    lines += [f"palette-foreground={','.join(map(str, rgb[7]))}", f"palette-background={','.join(map(str, rgb[0]))}"]
    return "\n".join(lines) + "\n"


def palette(theme_dir):
    """The theme's terminal colours (colors.toml's [terminal] color0..15), as setvtrgb's file."""
    import tomllib
    path = os.path.join(theme_dir, "colors.toml")
    roots = grub_theme().resolve_colors_toml(path)
    with open(path, "rb") as f:
        doc = tomllib.load(f)

    def resolve(v):
        for _ in range(32):
            if v.startswith("#"):
                return v
            if "." in v:
                t, k = v.split(".", 1)
                v = doc.get(t, {}).get(k, "")
            else:
                v = roots.get(v, "")
            if not v:
                break
        raise SystemExit(f"{path}: a [terminal] colour names nothing")

    rgb = []
    for i in range(16):
        v = doc.get("terminal", {}).get(f"color{i}")
        if not v:
            raise SystemExit(f"{path}: no [terminal] color{i}")
        v = resolve(v)
        rgb.append(tuple(int(v[k:k + 2], 16) for k in (1, 3, 5)))
    return "\n".join(",".join(str(c[i]) for c in rgb) for i in range(3)) + "\n"


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--out", required=True)
    ap.add_argument("--font-dir", default="/usr/share/fonts/TTF")
    ap.add_argument("--theme-dir", default=os.path.join(REPO, "themes", "wick"))
    args = ap.parse_args(argv)
    os.makedirs(args.out, exist_ok=True)
    for size in SIZES:
        data, n = build_font(args.font_dir, size)
        with gzip.GzipFile(os.path.join(args.out, f"bromigos-geist-{size}.psf.gz"), "wb", mtime=0) as f:
            f.write(data)
        print(f"bromigos-geist-{size}.psf.gz: {n} glyphs")
    vtrgb = palette(args.theme_dir)
    with open(os.path.join(args.out, "palette.vtrgb"), "w") as f:
        f.write(vtrgb)
    with open(os.path.join(args.out, "kmscon.conf"), "w") as f:
        f.write(kmscon_conf(vtrgb))
    print("palette.vtrgb, kmscon.conf")


if __name__ == "__main__":
    sys.exit(main())
