#!/usr/bin/env python3
"""The installers' and welcome tours' art (desktop/art/, packaged by bromigos-desktop into
/usr/share/bromigos/art),
made from bromigOS's own renders, never stock art:

  vector-{idle,speaking,thinking}.png   VECTOR's hologram, cut out of the vector repository's
                                        offscreen render on a black plate (alpha from light)
  kind-desktop.png, kind-server.png     the "What kind of computer" cards: the workstation
                                        hologram over the Wick's den, the rack hologram
  feature-*.jpg                         the installing slideshow: manual pictures and world previews
  server-rack.png                       bromigOS Server's hologram: the rack turning on its
                                        emitter, 24 frames side by side (the graphical installer);
                                        lib/bromigos_rack.py has the same frames as braille, with
                                        their brightness (the text installer and the server's tour)

    tools/installer-art/make.py VECTOR_REPO VECTOR_RENDERS_DIR
    tools/installer-art/make.py rack RACK_FRAMES_DIR

RACK_FRAMES_DIR holds rack-00.png … rack-23.png: the vector gallery's rack, `tools/offscreen.py
gallery rack-NN.png rack 0 - 3` with OFF_DEMO=1 OFF_BG=black.jpg and the stage's yaw set to
-pi + 2pi * NN / 24 (no idle spin), one frame each: render-rack.py frames makes them.

VECTOR_RENDERS_DIR holds vector-STATE.png from `OFF_BG=black.jpg OFF_DEMO=1 OFF_CHAT=0
OFF_W=1280 OFF_H=800 tools/offscreen.py vector vector-STATE.png STATE` (demo readings).
"""
import os
import sys

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageEnhance

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.realpath(__file__))))
OUT = os.path.join(ROOT, "desktop/art")


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


RACK_FRAMES, RACK_H = 24, 300          # the sprite's frames and their height in pixels
BRAILLE = (10, 10)                       # the text frames: columns and rows (2x4 dots a cell)
RACK_STAGE = (400, 120, 880, 680)       # where the model stands in a 1280x800 gallery frame


def rack_turntable(frames_dir):
    """The rack turntable: one sprite (frames side by side, alpha from light) and its braille."""
    import json
    # the stage only (the gallery's title, readings, menus and brackets stay out)
    ims = [light_alpha(Image.open(os.path.join(frames_dir, f"rack-{i:02d}.png")).crop(RACK_STAGE), floor=18)
           for i in range(RACK_FRAMES)]
    box = None
    for im in ims:                      # one crop for every frame, so the rack doesn't jump as it turns
        b = im.getchannel("A").point(lambda v: 255 if v > 24 else 0).getbbox()
        box = b if box is None else (min(box[0], b[0]), min(box[1], b[1]), max(box[2], b[2]), max(box[3], b[3]))
    pad = 6
    box = (box[0] - pad, box[1] - pad, box[2] + pad, box[3] + pad)
    k = RACK_H / (box[3] - box[1])
    fw = round((box[2] - box[0]) * k)
    sheet = Image.new("RGBA", (fw * RACK_FRAMES, RACK_H))
    text = {"w": BRAILLE[0], "h": BRAILLE[1], "frames": []}
    for i, im in enumerate(ims):
        f = im.crop(box).resize((fw, RACK_H), Image.LANCZOS)
        sheet.alpha_composite(f, (i * fw, 0))
        # braille: 2x4 dots a cell; the lines of the wireframe light the dots (the light less its own
        # blur, so the glow doesn't fill the cell), the brightest third of them in each frame;
        # a cell's level (0-3) is how bright it is
        cw, ch = BRAILLE[0] * 2, BRAILLE[1] * 4
        a = f.getchannel("A")
        edge = np.asarray(a).astype(np.float32) - np.asarray(a.filter(ImageFilter.GaussianBlur(6))).astype(np.float32)
        lines = Image.fromarray(np.clip(edge * 3 + np.asarray(a) * 0.25, 0, 255).astype(np.uint8))
        lum = np.asarray(lines.resize((cw, ch), Image.BOX)).astype(np.float32) / 255.0
        cut = np.percentile(lum[lum > 0.05], 62) if (lum > 0.05).any() else 1.0
        top = lum.max() or 1.0
        bits = ((0, 0, 0x01), (0, 1, 0x02), (0, 2, 0x04), (1, 0, 0x08), (1, 1, 0x10), (1, 2, 0x20), (0, 3, 0x40), (1, 3, 0x80))
        rows, lit = [], []
        for cy in range(BRAILLE[1]):
            row, lv = "", ""
            for cx in range(BRAILLE[0]):
                code, peak = 0, 0.0
                for dx, dy, bit in bits:
                    v = lum[cy * 4 + dy, cx * 2 + dx]
                    if v > cut:
                        code |= bit
                    peak = max(peak, v)
                row += chr(0x2800 + code) if code else " "
                lv += str(min(3, int(peak / top * 4))) if code else "0"
            rows.append(row)
            lit.append(lv)
        text["frames"].append({"rows": rows, "lit": lit})
    sheet.save(os.path.join(OUT, "server-rack.png"), optimize=True)
    # the braille goes with the Textual library (bromigos-core), so a server without the
    # desktop's art has it too
    with open(os.path.join(ROOT, "lib/bromigos_rack.py"), "w") as fh:
        fh.write('"""bromigOS Server\'s rack hologram as braille: the vector gallery\'s rack turning, one frame\n'
                 'every 15 degrees, a level (0-3) a cell for its brightness. Made by tools/installer-art/make.py\n'
                 'rack from the same renders as desktop/art/server-rack.png; don\'t edit by hand."""\n')
        fh.write(f"W, H = {text['w']}, {text['h']}\n")
        fh.write("FRAMES = [\n")
        for fr in text["frames"]:
            fh.write("    (" + json.dumps(fr["rows"], ensure_ascii=False) + ",\n     " + json.dumps(fr["lit"]) + "),\n")
        fh.write("]\n")
    print("rack:", sheet.size, "frame", fw, "x", RACK_H)


def main():
    if len(sys.argv) == 3 and sys.argv[1] == "rack":
        os.makedirs(OUT, exist_ok=True)
        return rack_turntable(sys.argv[2])
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
