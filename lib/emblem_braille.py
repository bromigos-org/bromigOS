#!/usr/bin/env python3
"""Renders the canon emblem (brand/emblem-small.svg) as braille cells with
24-bit colour for the terminal banner (`bromigos` in zsh). Writes
emblem.braille next to this script: one line per text row, ANSI escapes
included, so the shell only has to print it.

Rebuild after the emblem changes:  ./build-emblem-braille.py [cols]
A post's emblem (a world theme's emblem/; bromigos-emblem build --theme runs this):
  ./build-emblem-braille.py [cols] --svg DIR/emblem-small.svg --out DIR/emblem.braille \
      --palette '#b8e05a,#5d7a4b,#58e0e8'
"""
import os
import subprocess
import sys
import tempfile

from PIL import Image

HERE = os.path.dirname(os.path.realpath(__file__))
SVG = ""      # --svg: an emblem kit's emblem-small.svg (bromigos emblem build passes it)
OUT = ""      # --out: where emblem.braille goes
# Cells snap to the palette so the output stays small: phosphor, soft, dim.
PALETTE = [(57, 255, 20), (156, 255, 138), (21, 155, 9)]
# Braille dot bit for (x, y) inside a 2x4 cell.
BITS = {(0, 0): 0x01, (0, 1): 0x02, (0, 2): 0x04, (1, 0): 0x08,
        (1, 1): 0x10, (1, 2): 0x20, (0, 3): 0x40, (1, 3): 0x80}


def _hex(h):
    h = h.strip().lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def main():
    global SVG, OUT, PALETTE
    args = sys.argv[1:]
    for flag in ("--svg", "--out", "--palette"):
        if flag in args:
            i = args.index(flag)
            val = args[i + 1]
            del args[i:i + 2]
            if flag == "--svg":
                SVG = val
            elif flag == "--out":
                OUT = val
            else:
                PALETTE = [_hex(v) for v in val.split(",")]
    cols = int(args[0]) if args else 22
    w = cols * 2
    rows = (w + 3) // 4
    k = 4   # supersample: each dot is the brightest of a k x k block, so thin lines survive
    with open(SVG) as f:
        # Drop the soft halo: in braille it would fill the ring solid.
        src = f.read().replace('fill="url(#bi-halo)"', 'fill="none"')
    with tempfile.TemporaryDirectory() as tmp:
        svg, png = os.path.join(tmp, "e.svg"), os.path.join(tmp, "e.png")
        with open(svg, "w") as f:
            f.write(src)
        subprocess.run(["rsvg-convert", "-w", str(w * k), "-h", str(w * k), "-o", png, svg], check=True)
        big = Image.open(png).convert("RGBA").load()

    def dot(x, y):
        best = (0, (0, 0, 0))
        for yy in range(y * k, y * k + k):
            for xx in range(x * k, x * k + k):
                pr, pg, pb, pa = big[xx, yy]
                lum = (0.2126 * pr + 0.7152 * pg + 0.0722 * pb) * pa / 255
                if lum > best[0]:
                    best = (lum, (pr, pg, pb))
        return best
    lines = []
    for r in range(rows):
        out, last = [], None
        for c in range(cols):
            bits, acc, n = 0, [0, 0, 0], 0
            for (dx, dy), bit in BITS.items():
                x, y = c * 2 + dx, r * 4 + dy
                if y >= w:
                    continue
                lum, (pr, pg, pb) = dot(x, y)
                # A dot is lit where the emblem draws a line (ring, ticks, flame, mast).
                if lum > 60:
                    bits |= bit
                    acc[0] += pr; acc[1] += pg; acc[2] += pb
                    n += 1
            if not bits:
                out.append(" ")
                continue
            mean = tuple(v / n for v in acc)
            col = min(PALETTE, key=lambda p: sum((p[i] - mean[i]) ** 2 for i in range(3)))
            if col != last:
                out.append(f"\x1b[38;2;{col[0]};{col[1]};{col[2]}m")
                last = col
            out.append(chr(0x2800 + bits))
        lines.append("".join(out).rstrip() + "\x1b[0m")
    with open(OUT, "w") as f:
        f.write("\n".join(lines) + "\n")
    print(f"{OUT}: {cols}x{rows}")


if __name__ == "__main__":
    main()
