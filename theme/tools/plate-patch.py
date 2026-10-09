#!/usr/bin/env python3
"""Write a masked edit of a world's flattened layers back into the layers themselves.

A world's backgrounds/layers/*.webp are split from one painting. To change something
in the painting (paint the fish out of Tidewell's water, say), flatten the layers,
edit the flat image inside a mask (a nolgia masked edit; the mask is the edit's own:
transparent = may change), then run this to put the edited pixels back where they're
seen, inside the mask only:

  plate-patch.py THEME_DIR FLAT.png EDITED.png MASK.png LAYER [LAYER …]

LAYERs are names under backgrounds/layers/ (no extension), back to front, e.g.
20-water-far 30-kelp-mid. In the mask each pixel goes to the front-most listed layer
that covers it (alpha > 0.5); the layer behind keeps its own pixels there, so a layer
that sways or parallaxes never uncovers a copy of the one in front. Partly covering
edges are solved so the composite comes out as the edit. Pixels outside the mask
(feathered by 3 px) aren't touched; nor are layers in front of the listed ones, which
must be transparent inside the mask (checked).
"""
import os
import sys

import numpy as np
from PIL import Image, ImageFilter


def load(p, mode):
    return np.asarray(Image.open(p).convert(mode)).astype(np.float32) / 255.0


def main():
    if len(sys.argv) < 6:
        sys.exit(__doc__)
    theme, flat_p, edit_p, mask_p, names = sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4], sys.argv[5:]
    ldir = os.path.join(theme, "backgrounds", "layers")
    flat = load(flat_p, "RGB")
    h, w = flat.shape[:2]
    edit = np.asarray(Image.open(edit_p).convert("RGB").resize((w, h), Image.LANCZOS)).astype(np.float32) / 255.0
    m = Image.open(mask_p).convert("RGBA").getchannel("A").resize((w, h))
    m = Image.eval(m, lambda a: 255 - a).filter(ImageFilter.GaussianBlur(3))   # 1 = edited
    f = (np.asarray(m).astype(np.float32) / 255.0)[..., None]
    target = edit * f + flat * (1.0 - f)
    inside = f[..., 0] > 0.002

    every = sorted(n[:-5] for n in os.listdir(ldir) if n.endswith(".webp"))
    front = [n for n in every if n > names[-1]]
    for n in front:
        a = load(os.path.join(ldir, n + ".webp"), "RGBA")[..., 3]
        if (a[inside] > 0.02).any():
            sys.exit(f"{n} is in front of {names[-1]} and covers part of the mask; list it too")

    layers = {n: load(os.path.join(ldir, n + ".webp"), "RGBA") for n in names}
    # front to back: a pixel belongs to the front-most layer covering it
    claimed = np.zeros((h, w), bool)
    owner = {}
    for n in reversed(names):
        a = layers[n][..., 3]
        mine = inside & ~claimed & ((a > 0.5) | (n == names[0]))
        owner[n] = mine
        claimed |= a > 0.5
    # back to front: what's behind each layer, so a partly covering edge comes out right
    behind = None
    for n in names:
        L = layers[n]
        a = L[..., 3:4]
        rgb = L[..., :3]
        mine = owner[n][..., None]
        if behind is None:
            new = np.where(mine, target, rgb)
        else:
            solved = np.clip((target - (1.0 - a) * behind) / np.maximum(a, 1e-3), 0.0, 1.0)
            edge = (inside & (L[..., 3] > 0.02) & (L[..., 3] <= 0.5))[..., None]
            new = np.where(mine, target, np.where(edge, solved, rgb))
        changed = int((np.abs(new - rgb).max(-1) > 1 / 255).sum())
        L = np.concatenate([new, a], -1)
        layers[n] = L
        behind = new * a + (behind if behind is not None else 0.0) * (1.0 - a)
        out = os.path.join(ldir, n + ".webp")
        Image.fromarray((L * 255.0 + 0.5).astype(np.uint8), "RGBA").save(out, lossless=False, quality=92, method=6)
        print(f"{n}: {changed} px changed")


if __name__ == "__main__":
    main()
