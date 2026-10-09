#!/usr/bin/env python3
"""Cut a sheet of painted craft (or creatures) into a world's sprites.

  craft-sprites.py SHEET CUT OUTDIR [~X0,Y0,X1,Y1 ...] NAME=X0,Y0,X1,Y1@WIDTH[!X0,Y0,X1,Y1 ...] ...

SHEET is the painting on a flat grey background (`bromigos art`, kind image) and CUT
its background-removed copy (kind cutout). The model's matte sometimes drops thin or
dark parts (moss hanging off a hull, a gun barrel, a second engine pod), so the matte
used is the union of CUT's alpha and a local key of the flat grey, with the grey taken
back out of the edge colours. Each NAME's craft is found inside the box X0,Y0,X1,Y1
(sheet pixels), trimmed to its alpha, scaled to WIDTH px (about the largest size the
world draws it, so the GPU never shrinks it far: the atlas has no mipmaps) and written
as OUTDIR/craft-NAME.webp with its size and box printed. Each `!X0,Y0,X1,Y1` after it
is a box left out (a neighbour's rotor reaching into this one's box).

A `~X0,Y0,X1,Y1` box holds see-through parts painted over the grey (a rotor's motion
blur, a lamp's beam): there the light, colourless pixels get the alpha of a silver blur
over the grey (how far from the grey toward silver they are), so the sky shows through;
the solid parts inside (hubs, pylons: darker or coloured) stay solid.
"""
import os
import sys

import numpy as np
from PIL import Image, ImageFilter


SILVER = np.array([214.0, 216.0, 222.0])


def matte(sheet, cut, clear=()):
    s = np.array(Image.open(sheet).convert("RGB")).astype(np.float32)
    c = np.array(Image.open(cut).convert("RGBA")).astype(np.float32)
    bg = np.median(np.concatenate([s[:16].reshape(-1, 3), s[-16:].reshape(-1, 3)]), axis=0)
    d = np.sqrt(((s - bg) ** 2).sum(-1))
    key = np.clip((d - 7.0) / 16.0, 0, 1)
    hard = Image.fromarray(((d > 9) * 255).astype(np.uint8))
    closed = hard.filter(ImageFilter.MaxFilter(7)).filter(ImageFilter.MinFilter(7))   # pinholes in grey metal
    closed = np.array(closed).astype(np.float32) / 255
    key = np.maximum(key, closed * np.clip((d - 3.0) / 6.0, 0, 1))
    a = np.maximum(c[..., 3] / 255.0, key)
    if clear:
        luma = s @ np.array([0.3, 0.59, 0.11])
        sat = s.max(-1) - s.min(-1)
        blur = (luma > bg @ np.array([0.3, 0.59, 0.11]) - 4) & (sat < 26)
        t = np.clip(np.sqrt(((s - bg) ** 2).sum(-1)) / np.sqrt(((SILVER - bg) ** 2).sum()), 0, 1)
        t = np.array(Image.fromarray((t * 255).astype(np.uint8)).filter(ImageFilter.GaussianBlur(5))) / 255.0
        for x0, y0, x1, y1 in clear:            # (a blade blur is streaky; smoothed, it reads as a spinning disc)
            sl = (slice(y0, y1), slice(x0, x1))
            a[sl] = np.where(blur[sl], t[sl], a[sl])
            s[sl] = np.where(blur[sl][..., None], s[sl] * 0.35 + SILVER * 0.65, s[sl])
    a[a < 0.04] = 0
    a3 = a[..., None]
    fg = np.clip(np.where(a3 > 0.02, (s - (1 - a3) * bg) / np.maximum(a3, 0.02), 0), 0, 255)
    if clear:
        for x0, y0, x1, y1 in clear:
            sl = (slice(y0, y1), slice(x0, x1))
            fg[sl] = np.where(blur[sl][..., None], s[sl], fg[sl])
    return Image.fromarray(np.dstack([fg, a * 255]).astype(np.uint8), "RGBA")


def main(argv):
    if len(argv) < 4:
        sys.exit(__doc__.strip())
    sheet, cut, outdir = argv[:3]
    clear = [tuple(int(v) for v in x[1:].split(",")) for x in argv[3:] if x.startswith("~")]
    argv = [x for x in argv if not x.startswith("~")]
    im = matte(sheet, cut, clear)
    a = np.array(im)[..., 3]
    os.makedirs(outdir, exist_ok=True)
    for spec in argv[3:]:
        name, _, rest = spec.partition("=")
        box, _, width = rest.partition("@")
        width, *cuts = width.split("!")
        x0, y0, x1, y1 = (int(v) for v in box.split(","))
        keep = np.zeros(a.shape, bool)
        keep[y0:y1, x0:x1] = True
        for cbox in cuts:
            cx0, cy0, cx1, cy1 = (int(v) for v in cbox.split(","))
            keep[cy0:cy1, cx0:cx1] = False
        mine = im.copy()
        mine.putalpha(Image.fromarray(np.where(keep, a, 0).astype(np.uint8)))
        m = (np.array(mine)[..., 3] > 12)[y0:y1, x0:x1]
        ys, xs = np.where(m.any(1))[0], np.where(m.any(0))[0]
        b = (x0 + xs[0] - 4, y0 + ys[0] - 4, x0 + xs[-1] + 5, y0 + ys[-1] + 5)
        c = mine.crop(b)
        w = int(width or c.width)
        c = c.resize((w, max(1, round(c.height * w / c.width))), Image.LANCZOS)
        out = os.path.join(outdir, f"craft-{name}.webp")
        c.save(out, quality=92, alpha_quality=100, method=6)
        print(f"{out}: {c.width}x{c.height} from {b}")


if __name__ == "__main__":
    main(sys.argv[1:])
