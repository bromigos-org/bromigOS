#!/usr/bin/env python3
"""Placeholder art for the worlds (Mire, Tidewell): simple layered shapes and gradients
in each world's palette, so the live layer runs before the real art lands.

The art contract (docs/theming.md, "The art files"), which the real art follows too:

  themes/<world>/backgrounds/layers/NN-name.webp   2560x1440 RGBA, back to front
  themes/<world>/live/actors/<actor>.webp           RGBA, one frame
  themes/<world>/live/actors/<actor>/NN.webp        RGBA, a frame strip, in order
  themes/<world>/live/world.toml                    references them by these paths

Sprites are drawn facing right, feet (or the waterline contact) at the bottom centre,
with the lights' positions given in world.toml as fractions of the sprite (u across,
v down). Everything here is drawn from code: no source images.

  theme/tools/placeholder-worlds.py [mire|tidewell|all] [--force]

It never replaces a file that exists, and it skips a world whose real art has landed
(backgrounds/comp.webp is committed), unless --force. Both worlds have their real art.
"""
import math
import os
import random
import struct
import sys
import wave

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
W, H = 2560, 1440
SS = 2                      # supersampling for the shapes


def hexc(h, a=255):
    h = h.lstrip("#")
    return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16), a)


def canvas(w=W, h=H):
    im = Image.new("RGBA", (w * SS, h * SS), (0, 0, 0, 0))
    return im, ImageDraw.Draw(im)


def finish(im, w=W, h=H):
    return im.resize((w, h), Image.LANCZOS)


def S(v):
    return v * SS


def P(pts):
    return [(x * SS, y * SS) for x, y in pts]


def fbm(w, h, scale, octaves=4, seed=0):
    rng = np.random.default_rng(seed)
    out = np.zeros((h, w), np.float32)
    amp, tot = 1.0, 0.0
    for o in range(octaves):
        gw, gh = max(2, int(w / scale * 2 ** o)), max(2, int(h / scale * 2 ** o))
        g = rng.random((gh, gw)).astype(np.float32)
        up = np.asarray(Image.fromarray((g * 255).astype(np.uint8)).resize((w, h), Image.BICUBIC), np.float32) / 255
        out += up * amp
        tot += amp
        amp *= 0.5
    return out / tot


def vgrad(h, stops):
    """A vertical gradient: stops = [(y, (r, g, b))]."""
    ys = np.arange(h, dtype=np.float32)
    out = np.zeros((h, 3), np.float32)
    for c in range(3):
        out[:, c] = np.interp(ys, [s[0] for s in stops], [s[1][c] for s in stops])
    return out


FORCE = "--force" in sys.argv


def save(im, path, lossless=False):
    if os.path.exists(path) and not FORCE:
        print("  kept", os.path.relpath(path, ROOT))
        return
    os.makedirs(os.path.dirname(path), exist_ok=True)
    im.save(path, "WEBP", quality=88, method=6, lossless=lossless, exact=False)
    print(" ", os.path.relpath(path, ROOT), f"{os.path.getsize(path) // 1024} KB")


def solid(arr_rgb, alpha=None):
    a = np.full(arr_rgb.shape[:2], 255, np.uint8) if alpha is None else alpha
    return Image.fromarray(np.dstack([np.clip(arr_rgb, 0, 255).astype(np.uint8), a]), "RGBA")


# ------------------------------------------------------------------ shared shapes
def trunk(d, base, top, w0, w1, col, rng, bends=3):
    """A twisted trunk as a filled band along a wavy spine."""
    (x0, y0), (x1, y1) = base, top
    n = 40
    left, right = [], []
    ph = rng.random() * 6
    for i in range(n + 1):
        f = i / n
        x = x0 + (x1 - x0) * f + math.sin(f * bends * math.pi + ph) * 40 * (1 - f) * (0.5 + f)
        y = y0 + (y1 - y0) * f
        w = w0 + (w1 - w0) * f ** 0.7
        left.append((x - w / 2, y))
        right.append((x + w / 2, y))
    d.polygon(P(left + right[::-1]), fill=col)
    return [(l[0] / 2 + r[0] / 2, l[1]) for l, r in zip(left, right)]


def branch(d, start, ang, length, width, col, rng, depth, tips):
    x, y = start
    pts = [(x, y)]
    a = ang
    seg = 8
    for i in range(seg):
        a += (rng.random() - 0.5) * 0.5
        x += math.cos(a) * length / seg
        y += math.sin(a) * length / seg
        pts.append((x, y))
    for i in range(len(pts) - 1):
        w = width * (1 - i / seg * 0.7)
        d.line(P([pts[i], pts[i + 1]]), fill=col, width=max(1, int(S(w))))
        d.ellipse([S(pts[i][0] - w / 2), S(pts[i][1] - w / 2), S(pts[i][0] + w / 2), S(pts[i][1] + w / 2)], fill=col)
    tips.extend(pts[2:])
    if depth > 0:
        for _ in range(2):
            k = rng.randrange(3, seg)
            branch(d, pts[k], a + (rng.random() - 0.5) * 1.6, length * 0.55, width * 0.5, col, rng, depth - 1, tips)


def moss(d, pts, col, rng, n, lo, hi):
    for _ in range(n):
        x, y = pts[rng.randrange(len(pts))]
        L = lo + (hi - lo) * rng.random() ** 1.5
        ph = rng.random() * 6
        line = [(x + math.sin(ph + k * 0.35) * 4 * k / 10, y + k * L / 10) for k in range(11)]
        d.line(P(line), fill=col, width=S(1) + (S(1) if rng.random() < 0.4 else 0))


def reeds(d, x0, x1, ybase, hmin, hmax, col, rng, n, lean=0.0):
    for _ in range(n):
        x = x0 + (x1 - x0) * rng.random()
        h = hmin + (hmax - hmin) * rng.random()
        bend = (rng.random() - 0.5) * 0.6 + lean
        pts = [(x + bend * (k / 10) ** 2 * h * 0.5, ybase - k / 10 * h) for k in range(11)]
        w = 2 + 4 * rng.random()
        for i in range(10):
            d.line(P([pts[i], pts[i + 1]]), fill=col, width=max(1, int(S(w * (1 - i / 11)))))


def sprite(w, h):
    return canvas(w, h)


def frames_out(dirpath, frames, w, h):
    if os.path.isdir(dirpath) and any(f.endswith(".webp") for f in os.listdir(dirpath)) and not FORCE:
        print("  kept", os.path.relpath(dirpath, ROOT))
        return
    os.makedirs(dirpath, exist_ok=True)
    for i, im in enumerate(frames):
        save(finish(im, w, h), os.path.join(dirpath, f"{i:02d}.webp"), lossless=True)


# ------------------------------------------------------------------ Mire
MIRE_LINE = 910                 # the far water line; the shack stands nearer, its stilts reach the water lower


def mire():
    out = os.path.join(ROOT, "themes", "mire")
    L = os.path.join(out, "backgrounds", "layers")
    A = os.path.join(out, "live", "actors")
    rng = random.Random(7)
    print("mire")
    # 00 sky: night over the bayou
    g = vgrad(H, [(0, (3, 8, 8)), (520, (8, 20, 18)), (MIRE_LINE, (22, 42, 36)), (H, (8, 14, 12))])
    sky = np.repeat(g[:, None, :], W, axis=1)
    cl = fbm(W, H, 700, 5, 1)
    band = np.clip(1.0 - np.abs(np.arange(H) - 360) / 300.0, 0, 1)[:, None]
    sky += (np.clip(cl - 0.45, 0, 1) * 60 * band)[..., None] * np.array([0.5, 0.65, 0.7])
    save(solid(sky), os.path.join(L, "00-sky.webp"))
    # 10 far: a misty cypress tree line across the left and centre
    im, d = canvas()
    for k in range(26):
        x = 40 + k * 62 + rng.random() * 30
        top = 300 + 260 * rng.random()
        trunk(d, (x, MIRE_LINE + 4), (x + (rng.random() - 0.5) * 20, top), 22, 6, hexc("#0f1d1c"), rng, bends=1)
        tips = []
        for j in range(4):
            branch(d, (x, top + 40 + j * 50), -math.pi / 2 + (rng.random() - 0.5) * 2.2, 90, 8, hexc("#0f1d1c"), rng, 1, tips)
        moss(d, tips, hexc("#18302a", 200), rng, 40, 20, 120)
    d.polygon(P([(0, MIRE_LINE - 40), (1700, MIRE_LINE - 30), (1700, MIRE_LINE + 6), (0, MIRE_LINE + 6)]), fill=hexc("#0f1d1c"))
    im = finish(im)
    a = np.asarray(im).astype(np.float32)
    haze = np.clip((np.arange(H) - 450) / 420.0, 0, 1)[:, None]
    a[..., :3] = a[..., :3] * (1 - haze[..., None] * 0.5) + (np.array([34, 58, 50]) * haze[..., None] * 0.5) * (a[..., 3:4] / 255)
    save(Image.fromarray(a.astype(np.uint8), "RGBA"), os.path.join(L, "10-far.webp"))
    # 20 mid: the crashed gunship, small and sunk deep on the left, its nacelle glowing
    im, d = canvas()
    gx, gy = 600, 925
    ang = math.radians(-8)

    def rot(pts):
        return [(gx + x * math.cos(ang) - y * math.sin(ang), gy + x * math.sin(ang) + y * math.cos(ang)) for x, y in pts]
    hullc = hexc("#1a1e18")
    d.polygon(P(rot([(-260, 12), (-220, -60), (-80, -96), (140, -90), (300, -40), (420, 12)])), fill=hullc)
    d.polygon(P(rot([(-60, -90), (-10, -150), (40, -160), (60, -92)])), fill=hexc("#151914"))           # a broken fin
    d.polygon(P(rot([(250, -50), (330, -40), (400, 10), (300, 12)])), fill=hexc("#0a0d0c"))              # the canopy
    for k in range(5):
        d.line(P(rot([(270 + 20 * k, -40 + 6 * k), (300 + 14 * k, 8)])), fill=hexc("#3a4840"), width=S(1))
    for x in range(-240, 400, 32):
        d.line(P(rot([(x, -88 + abs(x - 80) * 0.08), (x + 6, 10)])), fill=hexc("#11140f"), width=S(2))
    moss(d, rot([(x, -92 + abs(x - 40) * 0.06) for x in range(-220, 380, 8)]), hexc("#2f4a32", 220), rng, 120, 16, 70)
    nx, ny = 290, 885                                                                                      # the nacelle, apart
    d.ellipse([S(nx - 90), S(ny - 46), S(nx + 90), S(ny + 40)], fill=hexc("#181c16"))
    d.ellipse([S(nx - 40), S(ny - 20), S(nx - 10), S(ny + 10)], fill=hexc("#3fae5a"))                     # its glow (art)
    save(finish(im), os.path.join(L, "20-mid.webp"))
    # 30 water: the mirror's own colour; alpha = where the water is
    g = vgrad(H, [(MIRE_LINE, (8, 20, 18)), (H, (2, 7, 6))])
    wat = np.repeat(g[:, None, :], W, axis=1)
    alpha = np.zeros((H, W), np.uint8)
    alpha[MIRE_LINE:, :] = 255
    alpha[MIRE_LINE - 1, :] = 128
    save(solid(wat, alpha), os.path.join(L, "30-water.webp"))
    # 40 near: the stilt shack (it stands in front of the far water, its reflection painted),
    # the boat, the turret and plates in the foreground water, lily pads
    im, d = canvas()
    wood, dark, tin = hexc("#2a2016"), hexc("#160f0a"), hexc("#3a2e24")
    for xs in list(range(1270, 1760, 70)) + list(range(1800, 2300, 90)):
        d.rectangle([S(xs), S(890), S(xs + 14), S(1085)], fill=wood)                                     # stilts
        d.rectangle([S(xs), S(1090), S(xs + 14), S(1240)], fill=hexc("#1a140e", 110))                     # their reflection
    d.rectangle([S(1260), S(870), S(2300), S(900)], fill=hexc("#33281c"))                                   # the porch deck
    d.rectangle([S(1600), S(470), S(2300), S(872)], fill=hexc("#21180f"))                                   # the walls
    for yy in range(480, 872, 16):
        d.line(P([(1600, yy), (2300, yy)]), fill=dark, width=S(2))
    for wx in (1700, 2240):
        d.rectangle([S(wx), S(580), S(wx + 70), S(680)], fill=hexc("#5a3a16"))                             # windows, warm
    d.rectangle([S(1900), S(560), S(1990), S(872)], fill=dark)                                               # the door
    d.polygon(P([(1280, 580), (1600, 520), (2300, 300), (2300, 330), (1600, 556), (1280, 600)]), fill=tin)   # the roof
    d.polygon(P([(1520, 520), (2300, 300), (2300, 470), (1600, 470)]), fill=hexc("#2c231b"))
    for xx in range(1300, 2300, 12):
        y_top = 580 - (xx - 1280) * (280 / 1020)
        d.line(P([(xx, y_top + 2), (xx, y_top + 16)]), fill=hexc("#241c15"), width=S(2))
    for xs in (1330, 1530):
        d.rectangle([S(xs), S(570), S(xs + 12), S(872)], fill=wood)                                       # porch posts
    d.line(P([(1586, 590), (1586, 612)]), fill=dark, width=S(2))                                            # the lantern's hook
    d.rectangle([S(1576), S(612), S(1596), S(648)], outline=hexc("#5a4628"), width=S(2))
    mx = 1690                                                                                                # the radio mast
    for side in (-1, 1):
        d.line(P([(mx + side * 10, 420), (mx + side * 2, 60)]), fill=hexc("#3a3a36"), width=S(3))
    for yy in range(60, 420, 30):
        d.line(P([(mx - 10, yy), (mx + 10, yy + 30)]), fill=hexc("#2e2e2a"), width=S(2))
    d.line(P([(mx - 80, 90), (mx + 80, 60)]), fill=hexc("#3a3a36"), width=S(3))                             # the aerial
    d.ellipse([S(mx + 20), S(180), S(mx + 90), S(250)], outline=hexc("#3a3a36"), width=S(3))                # the dish
    d.polygon(P([(1410, 1020), (1440, 1140), (1980, 1140), (2010, 1020)]), fill=hexc("#2c2318"))            # the boat
    d.line(P([(1414, 1024), (2006, 1024)]), fill=hexc("#4a3c2a"), width=S(3))
    d.line(P([(1290, 900), (1420, 1030)]), fill=hexc("#4a4030"), width=S(1))                                # its rope
    for x0, y0, w0, h0 in ((300, 990, 280, 110), (700, 1090, 200, 70), (120, 1180, 260, 80)):              # turret and plates
        d.polygon(P([(x0, y0 + h0), (x0 + 20, y0 + 20), (x0 + w0 * 0.6, y0), (x0 + w0, y0 + 30), (x0 + w0 - 10, y0 + h0)]), fill=hexc("#1e1c16"))
    d.line(P([(500, 1010), (610, 980)]), fill=hexc("#1e1c16"), width=S(10))                                  # the turret's barrel
    pads = []
    for cx, cy, n in ((1000, 1300, 12), (1300, 1250, 8), (2000, 1330, 9), (560, 1340, 7)):
        for _ in range(n):
            x = cx + (rng.random() - 0.5) * 360
            y = cy + (rng.random() - 0.5) * 120
            persp = 0.6 + (y - MIRE_LINE) / (H - MIRE_LINE)
            rx, ry = 34 * persp * (0.7 + 0.6 * rng.random()), 11 * persp * (0.7 + 0.5 * rng.random())
            d.ellipse([S(x - rx), S(y - ry), S(x + rx), S(y + ry)], fill=hexc("#16281a"), outline=hexc("#23402a"), width=S(2))
            pads.append((round(x), round(y)))
    save(finish(im), os.path.join(L, "40-near.webp"))
    # 50 fore: the great mossy cypress on the right edge, reeds at the bottom left
    im, d = canvas()
    trunk(d, (2440, H + 20), (2380, -60), 360, 160, hexc("#0b120d"), rng)
    tips = []
    for k in range(4):
        branch(d, (2300, 80 + k * 120), math.pi + 0.3 + (rng.random() - 0.5) * 0.4, 420, 30, hexc("#0b120d"), rng, 2, tips)
    moss(d, tips, hexc("#2c4430", 230), rng, 420, 60, 380)
    reeds(d, -20, 300, H + 10, 140, 360, hexc("#050908"), rng, 50, lean=0.15)
    save(finish(im), os.path.join(L, "50-fore.webp"))
    print("  pads:", sorted(pads)[::6])

    # ---- actors
    sleeper(A)
    sleeper_heads(A)
    hollis(A)
    heron(A)
    fish_boot(A)
    lurker(A)
    drone(os.path.join(A, "drone"), "#2a3330", "#c8ffd0")
    frog(A)


def sleeper(A):
    """A moss-covered exo-frame, wading: four walk frames facing right, then one facing you."""
    w, h = 300, 420
    frames = []
    for i in range(5):
        im, d = sprite(w, h)
        rng = random.Random(30 + i)
        body, dark, mosscol = hexc("#1f2421"), hexc("#121614"), hexc("#3d5238", 235)
        front = i == 4
        sw = math.sin(i / 4 * 2 * math.pi)
        if not front:
            d.polygon(P([(95, 140), (205, 130), (220, 250), (200, 330), (100, 330), (85, 250)]), fill=body)      # torso
            d.polygon(P([(150, 60), (215, 58), (240, 90), (232, 128), (160, 132), (138, 100)]), fill=body)       # head, forward
            d.polygon(P([(196, 78), (236, 80), (234, 92), (198, 92)]), fill=dark)                                # the visor
            d.ellipse([S(68), S(128), S(140), S(190)], fill=dark)                                                   # shoulder
            d.polygon(P([(90, 170), (70 + 12 * sw, 300), (92 + 12 * sw, 305), (118, 180)]), fill=dark)          # arm
            d.polygon(P([(110, 320), (98 - 18 * sw, 420), (128 - 18 * sw, 420), (140, 320)]), fill=dark)       # legs
            d.polygon(P([(160, 320), (160 + 18 * sw, 420), (190 + 18 * sw, 420), (190, 320)]), fill=body)
            hang = [(150 + k * 6, 128 + rng.random() * 8) for k in range(12)] + [(80 + k * 6, 140) for k in range(10)]
        else:
            d.polygon(P([(85, 140), (215, 140), (228, 260), (205, 330), (95, 330), (72, 260)]), fill=body)
            d.polygon(P([(110, 60), (190, 60), (205, 100), (192, 132), (108, 132), (95, 100)]), fill=body)
            d.polygon(P([(118, 84), (182, 84), (180, 98), (120, 98)]), fill=dark)
            d.ellipse([S(40), S(126), S(110), S(186)], fill=dark)
            d.ellipse([S(190), S(126), S(260), S(186)], fill=dark)
            d.polygon(P([(52, 170), (44, 300), (68, 304), (86, 180)]), fill=dark)
            d.polygon(P([(248, 170), (256, 300), (232, 304), (214, 180)]), fill=dark)
            d.polygon(P([(105, 320), (100, 420), (140, 420), (145, 320)]), fill=dark)
            d.polygon(P([(155, 320), (160, 420), (200, 420), (195, 320)]), fill=dark)
            hang = [(105 + k * 8, 130) for k in range(12)] + [(50 + k * 6, 150) for k in range(10)] + [(196 + k * 6, 150) for k in range(10)]
        moss(d, hang, mosscol, rng, 70, 14, 110)
        frames.append(im)
    frames_out(os.path.join(A, "sleeper"), frames, w, h)


def sleeper_heads(A):
    """The foreground Sleepers: great golem heads half sunk at the bottom of the frame (the first
    herdr agents). Per head: 00 idle (three-quarter view), 01 turned to the viewer; and the
    same frames as an eye-light mask (white where the eyes glow) in <head>-eyes/."""
    w, h = 420, 360
    for n, (pad, tilt) in enumerate(((True, -6), (False, 4), (True, 0))):
        frames, masks = [], []
        for turned in (False, True):
            im, d = sprite(w, h)
            mk, dm = sprite(w, h)
            stone, moss_c = hexc("#1d221d"), hexc("#3a5236", 235)
            cx = 210 if turned else 230 + tilt
            d.polygon(P([(cx - 170, 360), (cx - 160, 190), (cx - 110, 110), (cx + 10, 80), (cx + 120, 104),
                         (cx + 168, 180), (cx + 176, 360)]), fill=stone)                                   # the dome
            d.polygon(P([(cx - 130, 220), (cx + 140, 220), (cx + 126, 262), (cx - 118, 262)]), fill=hexc("#0b0d0b"))  # brow slit
            eyes = [(cx - 60, 240), (cx + 60, 240)] if turned else [(cx + 30, 240), (cx + 120, 236)]
            for ex, ey in eyes:
                r = 20 if turned else 16
                d.ellipse([S(ex - r), S(ey - r * 0.6), S(ex + r), S(ey + r * 0.6)], fill=hexc("#0e1414"))
                dm.ellipse([S(ex - r * 0.8), S(ey - r * 0.45), S(ex + r * 0.8), S(ey + r * 0.45)], fill=(255, 255, 255, 255))
            rng = random.Random(70 + n)
            moss(d, [(cx - 150 + k * 10, 120 + abs(k - 15) * 4) for k in range(31)], moss_c, rng, 90, 16, 90)
            if pad:
                d.ellipse([S(cx - 70), S(70), S(cx + 70), S(104)], fill=hexc("#1e3a22"), outline=hexc("#2c5030"), width=S(2))
            frames.append(im)
            masks.append(mk.filter(ImageFilter.GaussianBlur(SS * 2)))
        frames_out(os.path.join(A, f"sleeper-head-{n + 1}"), frames, w, h)
        frames_out(os.path.join(A, f"sleeper-head-{n + 1}-eyes"), masks, w, h)


def hollis(A):
    """Hollis on his porch in a rocking chair, rod out over the water to the left:
    0-1 fishing, 2-3 dozing (head down, the rod dipping), 4 asleep."""
    w, h = 300, 260
    frames = []
    for i in range(5):
        im, d = sprite(w, h)
        chair, coat, hat = hexc("#2a2117"), hexc("#2c2f2a"), hexc("#3a3226")
        doze = i >= 2
        nod = {0: 0, 1: 2, 2: 14, 3: 18, 4: 26}[i]
        cx = 190
        d.arc([S(cx - 70), S(220), S(cx + 70), S(270)], 200, 340, fill=chair, width=S(5))       # rockers
        d.line(P([(cx + 40, 120), (cx + 58, 240)]), fill=chair, width=S(6))                      # back
        d.line(P([(cx - 40, 180), (cx + 50, 180)]), fill=chair, width=S(6))                      # seat
        d.line(P([(cx - 36, 180), (cx - 40, 245)]), fill=chair, width=S(5))
        d.polygon(P([(cx - 30, 115 + nod * 0.3), (cx + 38, 112), (cx + 46, 182), (cx - 36, 184)]), fill=coat)   # torso
        d.polygon(P([(cx - 36, 176), (cx - 80, 182), (cx - 84, 236), (cx - 70, 238), (cx - 64, 196), (cx - 20, 192)]), fill=coat)  # legs
        hx, hy = cx + 6 - nod * 0.5, 92 + nod
        d.ellipse([S(hx - 18), S(hy - 18), S(hx + 18), S(hy + 18)], fill=hexc("#4a3d30"))         # head
        d.ellipse([S(hx - 40), S(hy - 22), S(hx + 40), S(hy - 6)], fill=hat)                       # brim
        d.polygon(P([(hx - 20, hy - 18), (hx - 14, hy - 40), (hx + 16, hy - 40), (hx + 22, hy - 18)]), fill=hat)
        tip = {0: (8, 12), 1: (8, 18), 2: (16, 70), 3: (16, 78), 4: (22, 110)}[i]
        d.line(P([(cx - 30, 160), tip]), fill=hexc("#5a4a34"), width=S(3))                       # the rod
        d.line(P([(cx - 30, 160), (cx - 52, 150)]), fill=coat, width=S(10))                       # arm
        frames.append(im)
    frames_out(os.path.join(A, "hollis"), frames, w, h)
    print("  hollis rod tips (u, v):", [(round(x / w, 3), round(y / h, 3)) for x, y in ((8, 12), (8, 18), (16, 70), (16, 78), (22, 110))])


def heron(A):
    w, h = 240, 200
    frames = []
    for i in range(3):
        im, d = sprite(w, h)
        c, dk = hexc("#8794a0"), hexc("#55606a")
        if i < 2:
            d.ellipse([S(70), S(90), S(160), S(130)], fill=c)                                           # body
            d.line(P([(150, 100), (175, 80), (168, 60), (186, 50)]), fill=c, width=S(9))              # neck
            d.polygon(P([(186, 44), (236, 52), (186, 56)]), fill=hexc("#b8a070"))                        # beak
            d.line(P([(80, 120), (10, 140)]), fill=dk, width=S(4))                                       # legs trailing
            if i == 0:
                d.polygon(P([(90, 100), (60, 10), (150, 30), (140, 100)]), fill=dk)                    # wings up
            else:
                d.polygon(P([(90, 112), (40, 190), (130, 175), (140, 112)]), fill=dk)                  # wings down
        else:
            d.polygon(P([(120, 90), (0, 70), (10, 96), (110, 110)]), fill=dk)                          # facing you
            d.polygon(P([(120, 90), (240, 70), (230, 96), (130, 110)]), fill=dk)
            d.ellipse([S(100), S(80), S(140), S(140)], fill=c)
            d.ellipse([S(108), S(50), S(132), S(84)], fill=c)
            d.polygon(P([(116, 76), (124, 76), (120, 100)]), fill=hexc("#b8a070"))
        frames.append(im)
    frames_out(os.path.join(A, "heron"), frames, w, h)


def fish_boot(A):
    im, d = sprite(110, 46)
    d.ellipse([S(14), S(8), S(88), S(38)], fill=hexc("#c8d4dc"))
    d.polygon(P([(14, 23), (0, 6), (0, 40)]), fill=hexc("#a8b4bc"))
    d.ellipse([S(72), S(16), S(78), S(22)], fill=hexc("#101418"))
    save(finish(im, 110, 46), os.path.join(A, "fish.webp"), lossless=True)
    im, d = sprite(80, 80)
    d.polygon(P([(20, 4), (48, 4), (50, 50), (78, 58), (78, 76), (14, 76), (16, 40)]), fill=hexc("#7a6850"))
    d.line(P([(20, 14), (48, 14)]), fill=hexc("#4a3c2c"), width=S(3))
    save(finish(im, 80, 80), os.path.join(A, "boot.webp"), lossless=True)


def lurker(A):
    """Lab trouble: 0 = two eyes at the surface, 1 = a long shape breaking it."""
    w, h = 420, 120
    frames = []
    for i in range(2):
        im, d = sprite(w, h)
        c = hexc("#0d1512")
        if i == 0:
            d.ellipse([S(100), S(70), S(200), S(130)], fill=c)
        else:
            d.polygon(P([(40, 120), (90, 70), (210, 50), (330, 80), (410, 120)]), fill=c)
            for k in range(8):
                x = 140 + k * 28
                d.polygon(P([(x, 62 + k * 2), (x + 10, 40 + k * 2), (x + 18, 64 + k * 2)]), fill=c)
        frames.append(im)
    frames_out(os.path.join(A, "lurker"), frames, w, h)


def drone(path, body, lamp):
    w, h = 80, 64
    frames = []
    for i in range(2):
        im, d = sprite(w, h)
        d.ellipse([S(18), S(20), S(62), S(44)], fill=hexc(body))
        for x in (10, 70):
            d.line(P([(x - 8, 18 - i * 2), (x + 8, 18 + i * 2)]), fill=hexc("#5a6662"), width=S(2))
            d.line(P([(x, 18), (40, 28)]), fill=hexc(body), width=S(3))
        d.ellipse([S(34), S(34), S(46), S(46)], fill=hexc(lamp, 120))
        frames.append(im)
    frames_out(path, frames, w, h)


def frog(A):
    w, h = 60, 40
    frames = []
    for i in range(2):
        im, d = sprite(w, h)
        d.ellipse([S(6), S(12), S(54), S(40)], fill=hexc("#22361f"))
        d.ellipse([S(10), S(6), S(24), S(20)], fill=hexc("#22361f"))
        d.ellipse([S(36), S(6), S(50), S(20)], fill=hexc("#22361f"))
        d.ellipse([S(14), S(9), S(19), S(14)], fill=hexc("#c0b060"))
        d.ellipse([S(40), S(9), S(45), S(14)], fill=hexc("#c0b060"))
        if i == 1:
            d.ellipse([S(20), S(24), S(40), S(40)], fill=hexc("#8a9a70"))     # the throat, puffed
        frames.append(im)
    frames_out(os.path.join(A, "frog"), frames, w, h)


# ------------------------------------------------------------------ Tidewell
TIDE_LINE = 250                 # high: a thin strip of sky and surface, the deep below
LIGHT_X = 2220                  # Greywater Light, small, in the upper right corner


def tidewell():
    out = os.path.join(ROOT, "themes", "tidewell")
    L = os.path.join(out, "backgrounds", "layers")
    A = os.path.join(out, "live", "actors")
    rng = random.Random(11)
    print("tidewell")
    # 00 sky: the strip of night sky
    g = vgrad(H, [(0, (4, 10, 22)), (TIDE_LINE - 20, (18, 34, 52)), (TIDE_LINE, (24, 44, 62)), (H, (2, 6, 10))])
    sky = np.repeat(g[:, None, :], W, axis=1)
    cl = fbm(W, H, 500, 5, 3)
    band = np.clip(1.0 - np.abs(np.arange(H) - 120) / 120.0, 0, 1)[:, None]
    sky += (np.clip(cl - 0.5, 0, 1) * 70 * band)[..., None] * np.array([0.55, 0.65, 0.8])
    save(solid(sky), os.path.join(L, "00-sky.webp"))
    # 10 surface: the sea to the horizon, a far headland, the rock and Greywater Light
    im, d = canvas()
    d.polygon(P([(0, TIDE_LINE - 22), (W, TIDE_LINE - 22), (W, TIDE_LINE + 3), (0, TIDE_LINE + 3)]), fill=hexc("#0c1c2a"))
    hl = [(0, TIDE_LINE - 22)]
    for x in range(0, 640, 16):
        hl.append((x, TIDE_LINE - 22 - 34 * math.sin(x / 640 * math.pi) ** 0.6 - 6 * rng.random()))
    hl.append((640, TIDE_LINE - 22))
    d.polygon(P(hl), fill=hexc("#08121c"))
    tx, base = LIGHT_X, TIDE_LINE - 18
    d.polygon(P([(tx - 110, TIDE_LINE + 3), (tx - 90, base - 6), (tx - 40, base - 20), (tx + 60, base - 22),
                 (tx + 160, base - 4), (tx + 320, TIDE_LINE + 3)]), fill=hexc("#10171c"))           # the Sliver
    top = base - 132
    d.polygon(P([(tx - 18, base - 10), (tx - 11, top), (tx + 11, top), (tx + 18, base - 10)]), fill=hexc("#c9c6bc"))
    for y0 in (base - 40, base - 76):
        d.rectangle([S(tx - 16), S(y0), S(tx + 16), S(y0 + 10)], fill=hexc("#7a2a24"))
    d.rectangle([S(tx - 16), S(top - 2), S(tx + 16), S(top + 1)], fill=hexc("#22282c"))              # gallery
    d.rectangle([S(tx - 9), S(top - 18), S(tx + 9), S(top - 2)], fill=hexc("#11181c"))                # lamp room
    for x in range(tx - 9, tx + 10, 6):
        d.line(P([(x, top - 18), (x, top - 2)]), fill=hexc("#2a3236"), width=S(1))
    d.pieslice([S(tx - 11), S(top - 28), S(tx + 11), S(top - 10)], 180, 360, fill=hexc("#1c2226"))
    d.polygon(P([(tx - 70, base - 10), (tx - 66, base - 30), (tx - 36, base - 36), (tx - 30, base - 10)]), fill=hexc("#8f8b82"))
    d.rectangle([S(tx - 58), S(base - 26), S(tx - 50), S(base - 18)], fill=hexc("#1a1c1e"))
    # the trawler moored on the left, its net hanging into the water (the net is in 30-kelp-mid)
    bx = 460
    d.polygon(P([(bx - 110, TIDE_LINE - 28), (bx + 110, TIDE_LINE - 28), (bx + 96, TIDE_LINE + 3), (bx - 98, TIDE_LINE + 3)]), fill=hexc("#141a1e"))
    d.rectangle([S(bx - 20), S(TIDE_LINE - 70), S(bx + 60), S(TIDE_LINE - 28)], fill=hexc("#141a1e"))
    d.line(P([(bx - 60, TIDE_LINE - 28), (bx - 60, TIDE_LINE - 140)]), fill=hexc("#141a1e"), width=S(4))
    d.line(P([(bx + 20, TIDE_LINE - 70), (bx + 20, TIDE_LINE - 150)]), fill=hexc("#141a1e"), width=S(3))
    save(finish(im), os.path.join(L, "10-surface.webp"))
    print(f"  lamp room at ({tx}, {top - 10}), gallery y {top - 2}, house window ({tx - 54}, {base - 22})")
    # 20 water, far: the water's colour and thickness, the surface to the abyss
    g = vgrad(H, [(TIDE_LINE, (12, 50, 62)), (620, (5, 28, 40)), (1050, (2, 12, 20)), (H, (1, 3, 7))])
    wat = np.repeat(g[:, None, :], W, axis=1)
    ys = np.arange(H, dtype=np.float32)
    al = np.clip(0.85 + (ys - TIDE_LINE) / (H - TIDE_LINE) * 0.15, 0, 1)
    al[: TIDE_LINE - 30] = 0
    alpha = np.repeat((al * 255).astype(np.uint8)[:, None], W, axis=1)
    save(solid(wat, alpha), os.path.join(L, "20-water-far.webp"))
    # 30 kelp, mid: the Sliver's rock walls falling away on the right, kelp on their shelves,
    # the moored trawler's hull from below and its net hanging down on the left
    im, d = canvas()
    wall = hexc("#14262c")
    d.polygon(P([(2040, TIDE_LINE + 4), (W + 10, TIDE_LINE + 4), (W + 10, H + 10), (1900, H + 10), (2000, 1100), (1880, 760), (2010, 520)]), fill=wall)
    d.polygon(P([(1500, H + 10), (1560, 1000), (1700, 820), (1640, 600), (1760, 470), (1860, 720), (1840, 1100), (1900, H + 10)]), fill=hexc("#112026"))
    d.polygon(P([(1340, 900), (1560, 860), (1640, 940), (1400, 960)]), fill=hexc("#16282e"))           # a shelf
    for k in range(30):
        x = 1300 + rng.random() * 1200
        b = 900 + rng.random() * 540
        hgt = 260 + 560 * rng.random()
        ph = rng.random() * 6
        pts = [(x + math.sin(ph + j * 0.5) * 26 * j / 10, b - j / 10 * hgt) for j in range(11)]
        for j in range(10):
            d.line(P([pts[j], pts[j + 1]]), fill=hexc("#2a4a2e"), width=S(int(9 - j * 0.6)))
            if j % 2 == 0:
                lx, ly = pts[j]
                d.ellipse([S(lx), S(ly - 7), S(lx + 30), S(ly + 5)], fill=hexc("#33582f"))
    hx = 460
    d.chord([S(hx - 98), S(TIDE_LINE - 20), S(hx + 98), S(TIDE_LINE + 34)], 0, 180, fill=hexc("#0a1218"))
    top_l, top_r = (hx - 40, TIDE_LINE + 20), (hx + 60, TIDE_LINE + 20)
    bot = [(470, 600), (560, 760), (700, 900), (760, 940)]
    d.line(P([top_l, (430, 600), (560, 860), (700, 930)]), fill=hexc("#3a4a50", 220), width=S(2))
    d.line(P([top_r, (620, 520), (720, 760), (760, 930)]), fill=hexc("#3a4a50", 220), width=S(2))
    for k in range(1, 16):
        f = k / 16
        a0 = (top_l[0] + (700 - top_l[0]) * f, top_l[1] + (930 - top_l[1]) * f)
        a1 = (top_r[0] + (760 - top_r[0]) * f, top_r[1] + (930 - top_r[1]) * f)
        d.line(P([a0, a1]), fill=hexc("#2a3a40", 170), width=S(1))
    for k in range(1, 7):
        f = k / 7
        d.line(P([(top_l[0] + (top_r[0] - top_l[0]) * f, TIDE_LINE + 20), (700 + 60 * f, 930)]), fill=hexc("#2a3a40", 150), width=S(1))
    save(finish(im), os.path.join(L, "30-kelp-mid.webp"))
    # 40 water, near: foreground rocks and kelp in the corners
    im, d = canvas()
    d.polygon(P([(-10, H + 10), (-10, 1150), (160, 1120), (330, 1260), (420, H + 10)]), fill=hexc("#03080a"))
    d.polygon(P([(W + 10, H + 10), (W + 10, 1100), (2380, 1180), (2240, 1330), (2160, H + 10)]), fill=hexc("#03080a"))
    for x0 in (60, 200, 2300, 2450):
        ph = rng.random() * 6
        pts = [(x0 + math.sin(ph + j * 0.6) * 30 * j / 10, H + 20 - j / 10 * 760) for j in range(11)]
        for j in range(10):
            d.line(P([pts[j], pts[j + 1]]), fill=hexc("#04100e"), width=S(int(14 - j)))
    save(finish(im), os.path.join(L, "40-water-near.webp"))

    leviathan(A)
    hull(os.path.join(A, "trawler.webp"), 300, 150, "#0b1319", net=True)
    hull(os.path.join(A, "hauler.webp"), 380, 120, "#0a1116", net=False)
    jelly(A)
    im, d = sprite(44, 20)
    d.polygon(P([(2, 10), (14, 2), (38, 6), (44, 10), (38, 14), (14, 18)]), fill=hexc("#c8d2da"))
    d.polygon(P([(2, 10), (0, 2), (0, 18)]), fill=hexc("#a0aab2"))
    save(finish(im, 44, 20), os.path.join(A, "netfish.webp"), lossless=True)
    seabird(A)
    maren(A)
    drone(os.path.join(A, "drone"), "#2a3038", "#ffe6a8")


def leviathan(A):
    """One of the Choir: a long glowing swimmer facing right; frame 1 faces you."""
    w, h = 720, 220
    frames = []
    for i in range(2):
        im, d = sprite(w, h)
        c, fin, belly = hexc("#2c6f7c"), hexc("#1c4e5a"), hexc("#5fa8b4")
        if i == 0:
            body = []
            for k in range(41):
                f = k / 40
                x = 20 + f * 660
                th = 70 * math.sin(f * math.pi) ** 0.7 * (0.6 + 0.6 * f)
                body.append((x, 110 - th + 10 * math.sin(f * 6)))
            under = [(x, 110 + (110 - y) * 0.8 + 6) for x, y in body]
            d.polygon(P(body + under[::-1]), fill=c)
            belly_line = [(x, 110 + (110 - y) * 0.55) for x, y in body[4:-4]]
            d.line(P(belly_line), fill=belly, width=S(6))
            for k in range(8, 36, 4):                                  # bioluminescent marks
                x, y = body[k]
                d.ellipse([S(x - 5), S(y + 18), S(x + 5), S(y + 28)], fill=hexc("#9ff0f8"))
            d.polygon(P([(20, 110), (-0, 60), (10, 110), (0, 170)]), fill=fin)
            d.polygon(P([(380, 150), (330, 214), (440, 160)]), fill=fin)
            d.polygon(P([(300, 52), (360, 8), (380, 50)]), fill=fin)
        else:
            d.ellipse([S(230), S(30), S(490), S(200)], fill=c)
            d.ellipse([S(290), S(110), S(430), S(190)], fill=belly)
            for x in (300, 345, 375, 420):
                d.ellipse([S(x - 5), S(70), S(x + 5), S(80)], fill=hexc("#9ff0f8"))
            d.polygon(P([(240, 120), (40, 170), (240, 160)]), fill=fin)
            d.polygon(P([(480, 120), (680, 170), (480, 160)]), fill=fin)
        frames.append(im)
    frames_out(os.path.join(A, "leviathan"), frames, w, h)


def hull(path, w, h, col, net):
    """A boat seen from below the surface: the hull's underside (the waterline is the
    sprite's row `h * 0.3`), a little of the superstructure above it, a trailing net."""
    im, d = sprite(w, h)
    wl = h * 0.3
    d.rectangle([S(w * 0.55), S(wl - 26), S(w * 0.75), S(wl)], fill=hexc(col))
    d.line(P([(w * 0.35, wl), (w * 0.35, 2)]), fill=hexc(col), width=S(3))
    d.chord([S(8), S(wl - 22), S(w - 8), S(wl + 44)], 0, 180, fill=hexc(col))
    d.line(P([(w * 0.5, wl + 40), (w * 0.5, wl + 50)]), fill=hexc(col), width=S(6))
    if net:
        d.line(P([(14, wl + 8), (2, h - 4)]), fill=hexc("#3a4a52", 200), width=S(2))
        d.line(P([(2, h - 4), (60, h - 10)]), fill=hexc("#3a4a52", 160), width=S(1))
    save(finish(im, w, h), path, lossless=True)


def ship(path, w, h, col, tall):
    im, d = sprite(w, h)
    hull = [(4, h - 50), (w - 4, h - 50), (w - 30, h - 4), (24, h - 4)]
    d.polygon(P(hull), fill=hexc(col))
    d.rectangle([S(w * 0.55), S(h - 86), S(w * 0.8), S(h - 50)], fill=hexc(col))
    d.line(P([(w * 0.35, h - 50), (w * 0.35, 6 if tall else h - 96)]), fill=hexc(col), width=S(4))
    if tall:
        d.line(P([(w * 0.35, 14), (w * 0.05, h - 50)]), fill=hexc(col), width=S(2))
    save(finish(im, w, h), path, lossless=True)


def jelly(A):
    w, h = 90, 140
    frames = []
    for i in range(2):
        im, d = sprite(w, h)
        sq = 1.0 if i == 0 else 0.82
        d.pieslice([S(45 - 38 * sq), S(10), S(45 + 38 * sq), S(10 + 70 / sq)], 180, 360, fill=hexc("#9ad8e8", 150))
        for k in range(6):
            x = 18 + k * 11
            d.line(P([(x, 44), (x + math.sin(k + i) * 6, 136)]), fill=hexc("#7ab8c8", 110), width=S(2))
        frames.append(im)
    frames_out(os.path.join(A, "jelly"), frames, w, h)


def seabird(A):
    w, h = 100, 50
    frames = []
    for i in range(2):
        im, d = sprite(w, h)
        c = hexc("#b8c0c8")
        up = 10 if i == 0 else 40
        d.line(P([(4, up), (40, 28), (50, 30), (60, 28), (96, up)]), fill=c, width=S(5))
        d.ellipse([S(42), S(24), S(58), S(36)], fill=c)
        frames.append(im)
    frames_out(os.path.join(A, "seabird"), frames, w, h)


def maren(A):
    """Maren, the keeper: 0-1 standing / moving, 2 sitting by the window, 3 asleep."""
    w, h = 50, 100
    frames = []
    for i in range(4):
        im, d = sprite(w, h)
        c, hair = hexc("#3a4048"), hexc("#6a5a48")
        if i < 2:
            d.polygon(P([(16, 34), (34, 34), (38, 72), (12, 72)]), fill=c)
            d.line(P([(18, 72), (16 - 4 * i, 100)]), fill=c, width=S(6))
            d.line(P([(32, 72), (34 + 4 * i, 100)]), fill=c, width=S(6))
            d.ellipse([S(15), S(12), S(35), S(34)], fill=hexc("#8a7a6a"))
            d.pieslice([S(14), S(10), S(36), S(30)], 180, 360, fill=hair)
        else:
            nod = 0 if i == 2 else 8
            d.polygon(P([(12, 50), (34, 50), (36, 82), (10, 82)]), fill=c)
            d.line(P([(14, 82), (34, 86)]), fill=c, width=S(8))
            d.line(P([(34, 86), (36, 100)]), fill=c, width=S(6))
            d.ellipse([S(13 + nod * 0.4), S(28 + nod), S(33 + nod * 0.4), S(50 + nod)], fill=hexc("#8a7a6a"))
            d.pieslice([S(12 + nod * 0.4), S(26 + nod), S(34 + nod * 0.4), S(46 + nod)], 180, 360, fill=hair)
        frames.append(im)
    frames_out(os.path.join(A, "maren"), frames, w, h)


# ------------------------------------------------------------------ sounds (Mire's frogs and crickets)
def wav(path, samples, rate=22050):
    if os.path.exists(path) and not FORCE:
        print("  kept", os.path.relpath(path, ROOT))
        return
    os.makedirs(os.path.dirname(path), exist_ok=True)
    s = np.clip(samples, -1, 1)
    with wave.open(path, "wb") as f:
        f.setnchannels(1)
        f.setsampwidth(2)
        f.setframerate(rate)
        f.writeframes(b"".join(struct.pack("<h", int(v * 32000)) for v in s))
    print(" ", os.path.relpath(path, ROOT), f"{os.path.getsize(path) // 1024} KB")


def sounds():
    rate = 22050
    t = np.arange(int(rate * 0.9)) / rate
    chirp = np.zeros_like(t)
    for k in range(3):                                   # three quick pulses of a cricket
        t0 = 0.08 + k * 0.11
        env = np.exp(-((t - t0) / 0.025) ** 2)
        chirp += env * np.sin(2 * np.pi * 4300 * t) * (0.7 + 0.3 * np.sin(2 * np.pi * 70 * t))
    wav(os.path.join(ROOT, "themes", "mire", "live", "sounds", "cricket.wav"), chirp * 0.35, rate)
    t = np.arange(int(rate * 0.7)) / rate
    f = 95 + 40 * np.exp(-t / 0.12)                      # a bullfrog's low croak
    ph = 2 * np.pi * np.cumsum(f) / rate
    croak = (np.sin(ph) + 0.5 * np.sin(2 * ph) + 0.25 * np.sin(3 * ph)) * np.exp(-((t - 0.22) / 0.16) ** 2)
    croak *= 0.6 + 0.4 * np.sin(2 * np.pi * 28 * t)
    wav(os.path.join(ROOT, "themes", "mire", "live", "sounds", "frog.wav"), croak * 0.4, rate)


def has_real_art(world):
    """A world whose real art has landed (its approved comp is committed) is left alone."""
    return os.path.isfile(os.path.join(ROOT, "themes", world, "backgrounds", "comp.webp"))


if __name__ == "__main__":
    which = sys.argv[1] if len(sys.argv) > 1 and not sys.argv[1].startswith("-") else "all"
    for w in ("mire", "tidewell"):
        if which in (w, "all") and has_real_art(w) and not FORCE:
            print(f"{w}: the real art is in (backgrounds/comp.webp); nothing to do (--force draws placeholders anyway)")
    if has_real_art("mire") and not FORCE:
        which = "none" if which == "mire" else ("tidewell" if which == "all" else which)
    if has_real_art("tidewell") and not FORCE:
        which = "none" if which == "tidewell" else ("mire" if which == "all" else which)
    if which in ("mire", "all"):
        mire()
    if which in ("tidewell", "all"):
        tidewell()
    if which in ("mire", "all"):
        sounds()
