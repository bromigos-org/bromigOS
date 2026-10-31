#!/usr/bin/env python3
"""The installers' and welcome tours' art (iso/profile/airootfs/usr/local/share/bromigos-iso/art/),
made from bromigOS's own renders, never stock art:

  vector-{idle,speaking,thinking}.png   VECTOR's hologram, cut out of the vector repository's
                                        offscreen render on a black plate (alpha from light)
  kind-desktop.png, kind-server.png     the "What kind of computer" cards: the workstation
                                        hologram over the Wick's den, the rack hologram
  feature-*.jpg                         the installing slideshow: manual pictures and world previews

    tools/installer-art/make.py VECTOR_REPO VECTOR_RENDERS_DIR

VECTOR_RENDERS_DIR holds vector-STATE.png from `OFF_BG=black.jpg OFF_DEMO=1 OFF_CHAT=0
OFF_W=1280 OFF_H=800 tools/offscreen.py vector vector-STATE.png STATE` (demo readings).
"""
import os
import sys

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageEnhance

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.realpath(__file__))))
OUT = os.path.join(ROOT, "iso/profile/airootfs/usr/local/share/bromigos-iso/art")


def light_alpha(im, floor=14):
    """A render on black as RGBA: alpha from the light, the colour un-premultiplied."""
    a = np.asarray(im.convert("RGB")).astype(np.float32)
    m = a.max(axis=2)
    alpha = np.clip((m - floor) * 255.0 / (255 - floor), 0, 255)
    rgb = np.where(m[..., None] > 0, a * 255.0 / np.maximum(m[..., None], 1), 0)
    return Image.fromarray(np.dstack([rgb, alpha]).clip(0, 255).astype(np.uint8), "RGBA")


def vector(renders):
    for st in ("idle", "speaking", "thinking"):
        im = Image.open(os.path.join(renders, f"vector-{st}.png")).convert("RGB")
        d = ImageDraw.Draw(im)          # the scene's own title and frame corners go
        for box in ((764, 24, 895, 56), (902, 40, 1026, 60), (764, 61, 952, 79), (740, 0, 775, 30),
                    (1240, 0, 1280, 30), (740, 770, 775, 800), (1240, 770, 1280, 800)):
            d.rectangle(box, fill=(0, 0, 0))
        cut = light_alpha(im.crop((745, 0, 1280, 800)))
        cut.resize((268, 400), Image.LANCZOS).save(os.path.join(OUT, f"vector-{st}.png"), optimize=True)


def card(holo, crop, bg, name, darken=0.35):
    w, h = 640, 400
    base = Image.open(bg).convert("RGB")
    s = max(w / base.width, h / base.height)
    base = base.resize((round(base.width * s), round(base.height * s)), Image.LANCZOS)
    base = base.crop(((base.width - w) // 2, (base.height - h) // 2, (base.width - w) // 2 + w, (base.height - h) // 2 + h))
    base = ImageEnhance.Brightness(base.filter(ImageFilter.GaussianBlur(2))).enhance(darken).convert("RGBA")
    fg = light_alpha(Image.open(holo).crop(crop), floor=22)
    k = min(w * 0.9 / fg.width, h * 0.95 / fg.height)
    fg = fg.resize((round(fg.width * k), round(fg.height * k)), Image.LANCZOS)
    base.alpha_composite(fg, ((w - fg.width) // 2, h - fg.height))
    base.convert("RGB").save(os.path.join(OUT, name), quality=88)


FEATURES = [
    ("manual/src/images/desktop.webp", "feature-desktop.jpg"),
    ("manual/src/images/holodeck.webp", "feature-holodeck.jpg"),
    ("manual/src/images/lab-console.webp", "feature-lab.jpg"),
    ("manual/src/images/den-tv.webp", "feature-den.jpg"),
    ("manual/src/images/settings.webp", "feature-settings.jpg"),
]


def features():
    for src, name in FEATURES:
        im = Image.open(os.path.join(ROOT, src)).convert("RGB")
        k = 640 / im.width
        im.resize((640, round(im.height * k)), Image.LANCZOS).save(os.path.join(OUT, name), quality=86)


def main():
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    vrepo, renders = sys.argv[1:3]
    os.makedirs(OUT, exist_ok=True)
    vector(renders)
    den = os.path.join(ROOT, "desktop/wallpaper/bromigos-den-empty-2560x1440.jpg")
    ws = os.path.join(vrepo, "assets/holo/previews/holo-workstation.jpg")
    rack = os.path.join(ROOT, "homelab/holo/previews/holo-rack-isolated.jpg")
    card(ws, (600, 180, 1180, 945), den, "kind-desktop.jpg")
    card(rack, (690, 150, 1190, 945), den, "kind-server.jpg", darken=0.22)
    features()
    print("art in", OUT)


if __name__ == "__main__":
    main()
