#!/usr/bin/env python3
"""The bromigOS boot menu: a GRUB theme made from a bromigOS theme (docs/boot.md).

"Tuning into the relay": the boot menu is the Wick's console. The burn-in sits exactly where
the Plymouth splash puts it (the screen's centre, a third of its height across), so the menu,
the splash, the passphrase and the login read as one screen changing. Under the emblem, on
the splash's progress line, the timeout is a signal-strength meter that lights up while it
counts ("TUNING IN · 5"); under that, the channel list.

  build-grub-theme.py --theme-dir themes/mire --out DIR    a shipped theme (package build)
  build-grub-theme.py --current --out DIR                  the theme in force (a user's own,
                                                           or high contrast)
  build-grub-theme.py --theme-dir themes/wick --medium --out DIR   the ISO's title card
  build-grub-theme.py --fonts-out DIR                      Geist Mono as GRUB fonts, only

Colours come from the theme (`--palette palette.json`, the rendered `--current` theme, or a
theme directory's colors.toml); the background from its lock-screen image (a world's
painting stacked, softened and darkened the way bromigos-wallpaper makes the lock screen's,
else the Wick's den with the chair empty), with a faint scanline texture and the emblem
baked in; the burn-in from its emblem kit (`emblem/lock/{ring,flame}.png`, Plymouth's own
layers; a theme without a kit gets the Wick's, recoloured). Fonts: Geist Mono as GRUB's
pf2, made with grub-mkfont from `--font-dir`, or copied from `--fonts` (made once at
package build). Layout is in percentages of the screen, the background scales to its
height (`fitheight`), so it holds at any resolution (GRUB_GFXMODE=auto), 800x600 up.

Writes DIR/theme.txt, background.png, the pixmaps, icons/, the fonts and manifest.json
(every file's sha256: what the root helper checks before it copies a theme to /boot).
"""

import argparse
import hashlib
import json
import math
import os
import shutil
import subprocess
import sys
import tomllib

from PIL import Image, ImageChops, ImageDraw, ImageEnhance, ImageFilter, ImageFont

# Bumped when the layout or the files change: a theme rendered by an older generator is
# rendered again (the manifest carries it).
VERSION = 3

# The canvas: 16:9 at 1440 rows. GRUB scales it to the screen's height and crops or pads
# the sides (desktop-image-scale-method fitheight), so everything placed by height lands
# where it should on any landscape screen.
W, H = 2560, 1440

# Plymouth's splash (settings/plymouth/bromigos/bromigos.script): the emblem a third of the
# short side across, centred; its progress line `size/2 + size*0.14` below the centre.
EMBLEM = 0.34
LINE = 0.5 + EMBLEM / 2 + EMBLEM * 0.14        # 0.7176: theme.txt rounds it to 72%

HEADING_INSTALLED = "RELAY CONSOLE // SELECT CHANNEL"
HEADING_MEDIUM = "BROMIGOS // RELAY MEDIUM"
FOOTER = "↑↓ choose · ENTER boot · E edit · C console"
TIMEOUT = "TUNING IN · %d"
METER_W = 300          # the timeout meter, in screen pixels
METER_H = 28           # GRUB's least height for a progress bar
METER_MARGIN = 30      # the plate round it
METER_PLATE_H = 56

# Geist Mono, as GRUB fonts: (file, weight, size). Every theme carries the same set under the
# same names, so the loadfont lines grub-mkconfig wrote stay right when the theme changes.
FONTS = [
    ("geist-mono-regular-14.pf2", "Regular", 14),
    ("geist-mono-regular-16.pf2", "Regular", 16),
    ("geist-mono-bold-16.pf2", "Bold", 16),
    ("geist-mono-semibold-20.pf2", "SemiBold", 20),
    ("geist-mono-semibold-26.pf2", "SemiBold", 26),
]
# ASCII, Latin-1, general punctuation (· … — • ›), arrows (↑↓), ⏎, box drawing, block elements
FONT_RANGES = "0x20-0x7E,0xA0-0xFF,0x2010-0x2027,0x2039-0x203A,0x2190-0x2193,0x23CE-0x23CE,0x2500-0x257F,0x2580-0x259F"

SHARE = os.environ.get("BROMIGOS_SHARE_DIR") or "/usr/share/bromigos"
STATE = os.path.join(os.environ.get("XDG_STATE_HOME") or os.path.expanduser("~/.local/state"), "bromigos")
HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.normpath(os.path.join(HERE, "..", ".."))


# ------------------------------------------------------------------ colours

def hexrgb(h):
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def hexstr(rgb, alpha=None):
    s = "#%02x%02x%02x" % tuple(max(0, min(255, round(c))) for c in rgb)
    return s if alpha is None else s + "%02x" % max(0, min(255, round(alpha)))


def mix(a, b, t):
    """a towards b by t (0..1)."""
    return tuple(round(x + (y - x) * t) for x, y in zip(a, b))


def resolve_colors_toml(path):
    """A theme's colors.toml with every reference resolved (theme.rs's rule: a value is
    "#rrggbb" or the name of another colour: a role, a [colors] name or "table.key").
    Only for themes shipped with bromigOS, at package build; a user's theme comes as the
    palette.json `bromigos theme set` renders."""
    with open(path, "rb") as f:
        doc = tomllib.load(f)
    root = {k: v for k, v in doc.items() if not isinstance(v, dict)}
    tables = {k: v for k, v in doc.items() if isinstance(v, dict) and k != "colors"}
    root.update(doc.get("colors", {}))

    def look(ref):
        if "." in ref:
            t, k = ref.split(".", 1)
            return tables.get(t, {}).get(k)
        return root.get(ref)

    def resolve(key, v):
        for _ in range(32):
            if v is None:
                raise SystemExit(f"{path}: {key}: no such colour")
            if v.startswith("#"):
                if len(v) == 7 and all(c in "0123456789abcdefABCDEF" for c in v[1:]):
                    return v.lower()
                raise SystemExit(f"{path}: {key}: {v!r} is not #rrggbb")
            v = look(v)
        raise SystemExit(f"{path}: {key}: the names refer to each other in a loop")

    return {k: resolve(k, v) for k, v in root.items()}


class Palette:
    """The roles the boot menu uses, as RGB tuples."""

    ROLES = ("background", "panel", "selection", "primary", "soft", "dim", "text", "muted", "faint", "warn")

    def __init__(self, colors, name, mode="dark"):
        missing = [r for r in self.ROLES if r not in colors]
        if missing:
            raise SystemExit(f"the palette lacks {', '.join(missing)}")
        self.hex = {r: colors[r].lower() for r in self.ROLES}
        self.rgb = {r: hexrgb(colors[r]) for r in self.ROLES}
        self.name = name
        self.mode = mode

    def __getattr__(self, role):
        if role in Palette.ROLES:
            return self.rgb[role]
        raise AttributeError(role)


# ------------------------------------------------------------------ images

def lock_from_world(bg_dir):
    """A world's lock-screen image, as bromigos-wallpaper's world_images() makes it: its
    layers stacked (backgrounds/layers/*.webp in name order; comp.webp without them),
    softened (blur 6) and darkened (brightness 0.4)."""
    layers = sorted(f for f in os.listdir(os.path.join(bg_dir, "layers")) if f.endswith(".webp")) \
        if os.path.isdir(os.path.join(bg_dir, "layers")) else []
    if layers:
        im = Image.new("RGBA", (W, H), (0, 0, 0, 255))
        for f in layers:
            im.alpha_composite(Image.open(os.path.join(bg_dir, "layers", f)).convert("RGBA").resize((W, H), Image.LANCZOS))
        im = im.convert("RGB")
    else:
        im = Image.open(os.path.join(bg_dir, "comp.webp")).convert("RGB").resize((W, H), Image.LANCZOS)
    return ImageEnhance.Brightness(im.filter(ImageFilter.GaussianBlur(6))).enhance(0.4)


def cover(im, w=W, h=H):
    """Scaled to cover w x h, centred, cropped (a lock image of another shape)."""
    s = max(w / im.width, h / im.height)
    im = im.resize((max(w, round(im.width * s)), max(h, round(im.height * s))), Image.LANCZOS)
    x, y = (im.width - w) // 2, (im.height - h) // 2
    return im.crop((x, y, x + w, y + h))


def duotone(im, dark, light, top=90):
    """The image's light mapped from `dark` towards `light`: the Wick's den in another theme's
    colours (a theme with no painting of its own). The lock-screen den is dark (its light
    tops out near 35), so `light` is reached at `top`: as bright as the Wick's own."""
    g = im.convert("L")
    lut = []
    for ch in range(3):
        lut += [max(0, min(255, round(dark[ch] + (light[ch] - dark[ch]) * i / top))) for i in range(256)]
    return Image.merge("RGB", (g, g, g)).point(lut)


def scanlines(im, period=6, depth=0.16):
    """A faint CRT texture: every `period` rows a soft dark line. 6 rows at 1440 stay at
    least 2.5 px apart on an 800x600 screen, so scaling down doesn't beat them into bands."""
    row = [1.0 - depth * max(0.0, math.cos(2 * math.pi * (y % period) / period)) ** 2 for y in range(period)]
    mask = Image.new("L", (1, period))
    mask.putdata([round(255 * v) for v in row])
    mask = mask.resize((im.width, period), Image.NEAREST)
    tile = Image.new("L", (im.width, im.height))
    for y in range(0, im.height, period):
        tile.paste(mask, (0, y))
    return ImageChops.multiply(im, Image.merge("RGB", (tile, tile, tile)))


def shade(im, colour):
    """The bottom of the screen darker (the channel list reads over it), and the far left
    and right fading into the desktop colour (a screen wider than 16:9 is padded with it)."""
    w, h = im.size
    g = Image.new("L", (1, h))
    g.putdata([round(255 * (1.0 - 0.35 * max(0.0, (y / h - 0.62) / 0.38) ** 1.5)) for y in range(h)])
    g = g.resize((w, h))
    im = ImageChops.multiply(im, Image.merge("RGB", (g, g, g)))
    edge = Image.new("L", (w, 1))
    fade = round(w * 0.05)
    edge.putdata([round(255 * min(1.0, min(x, w - 1 - x) / fade) ** 0.8) for x in range(w)])
    edge = edge.resize((w, h))
    return Image.composite(im, Image.new("RGB", (w, h), colour), edge)


def recolour(im, rgb):
    """An emblem layer drawn in the Wick's green, in another colour: each pixel's light kept,
    its hue the new colour's (the flame's black stays black)."""
    im = im.convert("RGBA")
    r, g, b, a = im.split()
    light = ImageChops.lighter(ImageChops.lighter(r, g), b)
    chans = [light.point(lambda v, c=c: round(v * c / 255)) for c in rgb]
    return Image.merge("RGBA", (*chans, a))


def emblem_layers(kit, palette, own):
    ring = Image.open(os.path.join(kit, "lock", "ring.png")).convert("RGBA")
    flame = Image.open(os.path.join(kit, "lock", "flame.png")).convert("RGBA")
    if not own:
        ring, flame = recolour(ring, palette.primary), recolour(flame, palette.primary)
    return ring, flame


def place_emblem(im, ring, flame):
    """Ring then flame, centred, EMBLEM of the height across (Plymouth's layers, its order)."""
    size = round(EMBLEM * H)
    out = im.convert("RGBA")
    for layer in (ring, flame):
        l = layer.resize((size, round(layer.height * size / layer.width)), Image.LANCZOS)
        out.alpha_composite(l, ((W - l.width) // 2, (H - l.height) // 2))
    return out.convert("RGB")


# ------------------------------------------------------------------ pixmaps

def plate_colour(im):
    """The background's mean colour where the timeout meter sits (under Plymouth's line)."""
    y = round(LINE * H)
    box = (round(W * 0.36), y - 30, round(W * 0.64), y + 30)
    return tuple(round(c) for c in im.crop(box).resize((1, 1), Image.BOX).getpixel((0, 0)))


def ss(n):
    return n * 4      # drawn at 4x, then scaled down: smooth edges without a vector library


def down(im, size):
    return im.resize(size, Image.LANCZOS)


def save(im, path):
    im.save(path, optimize=True)


def selection_bar(out, p):
    """The selected channel: a phosphor bar in the theme's accent (9-slice: a bright cap on
    the left, the bar, a soft end on the right). The text on it is the theme's background."""
    h = 32
    acc = p.primary
    # left cap: 6 px, the brightest
    cap = Image.new("RGBA", (6, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(cap)
    d.rectangle((0, 0, 2, h - 1), fill=(*mix(acc, (255, 255, 255), 0.35), 255))
    d.rectangle((3, 0, 5, h - 1), fill=(*acc, 235))
    save(cap, os.path.join(out, "select_w.png"))
    # the bar: the accent, a hair lighter at the top (a lit tube), scaled to the item's size
    bar = Image.new("RGBA", (4, h), (0, 0, 0, 0))
    for y in range(h):
        t = y / (h - 1)
        c = mix(mix(acc, (255, 255, 255), 0.12), acc, min(1.0, t * 3))
        bar.paste((*c, 235), (0, y, 4, y + 1))
    save(bar, os.path.join(out, "select_c.png"))
    # the right end fades out
    end = Image.new("RGBA", (16, h), (0, 0, 0, 0))
    for x in range(16):
        end.paste((*acc, round(235 * (1 - x / 16) ** 1.6)), (x, 0, x + 1, h))
    save(end, os.path.join(out, "select_e.png"))


def scrollbar(out, p):
    frame = Image.new("RGBA", (4, 8), (*p.faint, 70))
    save(frame, os.path.join(out, "scroll_frame_c.png"))
    thumb = Image.new("RGBA", (4, 8), (*p.dim, 230))
    save(thumb, os.path.join(out, "scroll_thumb_c.png"))


def terminal_box(out, p):
    """Behind the console (C) and the entry editor (E): a dark panel with a thin rule."""
    edge = (*p.dim, 160)
    fill = (*mix(p.background, p.panel, 0.5), 238)
    pieces = {
        "c": ((8, 8), None),
        "n": ((8, 2), "h"), "s": ((8, 2), "h"), "w": ((2, 8), "v"), "e": ((2, 8), "v"),
        "nw": ((2, 2), "x"), "ne": ((2, 2), "x"), "sw": ((2, 2), "x"), "se": ((2, 2), "x"),
    }
    for name, (size, kind) in pieces.items():
        im = Image.new("RGBA", size, fill if kind is None else edge)
        save(im, os.path.join(out, f"terminal_{name}.png"))


def meter(out, p, plate_rgb):
    """The timeout as a signal-strength meter. GRUB's progress bar stretches its pixmaps, so
    the bars are cut out of a mask laid over it: a plate under the bar, the bar (a dim track,
    the accent filling it as the seconds run), then the mask, the plate's colour with
    bar-shaped holes. The bars light up left to right. (GRUB draws a theme's components last
    to first, so theme.txt lists the mask before the bar; and an image is never drawn smaller
    than its file, so these are made at the size they're shown.) The plate's colour is the
    background's own there: with the timeout stopped, nothing shows."""
    # the plate: flat under the meter, fading out round it
    pw, ph = METER_W + 2 * METER_MARGIN, METER_PLATE_H
    core = Image.new("L", (pw, ph), 0)
    ImageDraw.Draw(core).rectangle((METER_MARGIN - 2, (ph - METER_H) // 2 - 2,
                                    pw - METER_MARGIN + 1, (ph + METER_H) // 2 + 1), fill=255)
    soft = core.filter(ImageFilter.GaussianBlur(10))
    alpha = ImageChops.lighter(soft.point(lambda v: min(255, v * 2)), core)
    plate = Image.new("RGBA", (pw, ph), (*plate_rgb, 255))
    plate.putalpha(alpha)
    save(plate, os.path.join(out, "meter_plate.png"))
    # the mask over the bar (GRUB makes a progress bar at least 28 px tall): bars rising to
    # the right on one baseline, the plate's colour round them
    n, base, low, high = 20, 21, 3, 17
    mask = Image.new("RGBA", (ss(METER_W), ss(METER_H)), (*plate_rgb, 255))
    d = ImageDraw.Draw(mask)
    step = ss(METER_W) / n
    for i in range(n):
        x0 = round(i * step + step * 0.18)
        x1 = round((i + 1) * step - step * 0.18)
        hgt = ss(low) + (ss(high) - ss(low)) * i / (n - 1)
        d.rectangle((x0, ss(base) - round(hgt), x1, ss(base) - 1), fill=(0, 0, 0, 0))
    save(down(mask, (METER_W, METER_H)), os.path.join(out, "meter_mask.png"))


# ------------------------------------------------------------------ icons

ICON = 22


def icon_canvas():
    im = Image.new("RGBA", (ss(ICON), ss(ICON)), (0, 0, 0, 0))
    return im, ImageDraw.Draw(im)


def glyphs(p):
    """The class icons: small line drawings in the theme's colours (what GRUB shows before an
    entry, by its --class). Drawn at 4x, scaled down."""
    ink = (*p.soft, 255)
    acc = (*p.primary, 255)
    w = ss(2)
    s = ss(ICON)

    def arc(d, box, a0, a1, fill=ink, width=w):
        d.arc(box, a0, a1, fill=fill, width=width)

    out = {}

    im, d = icon_canvas()                         # power
    arc(d, (ss(4), ss(4), s - ss(4), s - ss(4)), -50, 230)
    d.line((s // 2, ss(2), s // 2, s // 2), fill=ink, width=w)
    out["shutdown"] = im

    im, d = icon_canvas()                         # restart: a circle and its arrowhead
    arc(d, (ss(4), ss(4), s - ss(4), s - ss(4)), 20, 320)
    d.polygon([(s - ss(4), ss(5)), (s - ss(3), ss(11)), (s - ss(9), ss(9))], fill=ink)
    out["restart"] = im

    im, d = icon_canvas()                         # install: an arrow down into a tray
    d.line((s // 2, ss(3), s // 2, ss(14)), fill=acc, width=w)
    d.line((ss(7), ss(9), s // 2, ss(14), ss(15), ss(9)), fill=acc, width=w, joint="curve")
    d.line((ss(4), ss(13), ss(4), ss(18), s - ss(4), ss(18), s - ss(4), ss(13)), fill=ink, width=w, joint="curve")
    out["install"] = im

    im, d = icon_canvas()                         # safe graphics: a screen, a low-res grid
    d.rectangle((ss(3), ss(4), s - ss(3), ss(16)), outline=ink, width=w)
    for x in (ss(8), ss(11), ss(14)):
        d.line((x, ss(7), x, ss(13)), fill=(*p.dim, 255), width=ss(1))
    d.line((ss(8), ss(19), s - ss(8), ss(19)), fill=ink, width=w)
    out["safe"] = im

    im, d = icon_canvas()                         # speech: a speaker and its waves
    d.polygon([(ss(3), ss(8)), (ss(7), ss(8)), (ss(11), ss(4)), (ss(11), ss(18)), (ss(7), ss(14)), (ss(3), ss(14))], outline=ink, width=w)
    arc(d, (ss(9), ss(7), ss(16), ss(15)), -55, 55)
    arc(d, (ss(9), ss(4), ss(20), ss(18)), -55, 55)
    out["speech"] = im

    im, d = icon_canvas()                         # memory: a module with its contacts
    d.rectangle((ss(2), ss(6), s - ss(2), ss(15)), outline=ink, width=w)
    for x in range(ss(5), s - ss(4), ss(3)):
        d.line((x, ss(15), x, ss(18)), fill=ink, width=ss(1))
    d.rectangle((ss(5), ss(9), ss(9), ss(12)), fill=acc)
    d.rectangle((ss(12), ss(9), ss(16), ss(12)), fill=acc)
    out["memtest"] = im

    im, d = icon_canvas()                         # a disk: a drive and its light
    d.rounded_rectangle((ss(2), ss(6), s - ss(2), ss(16)), radius=ss(2), outline=ink, width=w)
    d.ellipse((s - ss(7), ss(10), s - ss(5), ss(12)), fill=acc)
    d.line((ss(5), ss(11), ss(11), ss(11)), fill=(*p.dim, 255), width=ss(1))
    out["disk"] = im

    im, d = icon_canvas()                         # firmware: a chip and its pins
    d.rectangle((ss(6), ss(6), s - ss(6), s - ss(6)), outline=ink, width=w)
    for t in (ss(9), ss(13)):
        for a, b in (((t, ss(2)), (t, ss(6))), ((t, s - ss(6)), (t, s - ss(2))),
                     ((ss(2), t), (ss(6), t)), ((s - ss(6), t), (s - ss(2), t))):
            d.line((*a, *b), fill=ink, width=ss(1))
    d.rectangle((ss(9), ss(9), ss(13), ss(13)), fill=acc)
    out["efi"] = im

    im, d = icon_canvas()                         # a shell: the prompt
    d.line((ss(4), ss(6), ss(10), ss(11), ss(4), ss(16)), fill=ink, width=w, joint="curve")
    d.line((ss(12), ss(16), ss(18), ss(16)), fill=acc, width=w)
    out["shell"] = im

    im, d = icon_canvas()                         # roll back: an arrow turning back round a clock
    arc(d, (ss(3), ss(3), s - ss(3), s - ss(3)), 200, 470)
    d.polygon([(ss(2), ss(6)), (ss(8), ss(7)), (ss(3), ss(12))], fill=ink)
    d.line((s // 2, ss(7), s // 2, s // 2, ss(14), ss(14)), fill=acc, width=w, joint="curve")
    out["rollback"] = im

    im, d = icon_canvas()                         # before an update: a hollow marker, an open bracket
    d.line((ss(8), ss(4), ss(4), ss(4), ss(4), ss(18), ss(8), ss(18)), fill=ink, width=w, joint="curve")
    d.ellipse((ss(10), ss(8), ss(16), ss(14)), outline=acc, width=w)
    out["snapshot-pre"] = im

    im, d = icon_canvas()                         # after it: the marker filled, the bracket closed
    d.line((ss(14), ss(4), ss(18), ss(4), ss(18), ss(18), ss(14), ss(18)), fill=ink, width=w, joint="curve")
    d.ellipse((ss(6), ss(8), ss(12), ss(14)), fill=acc)
    out["snapshot-post"] = im

    im, d = icon_canvas()                         # a single snapshot (the timeline's): a clock
    d.ellipse((ss(3), ss(3), s - ss(3), s - ss(3)), outline=ink, width=w)
    d.line((s // 2, ss(6), s // 2, s // 2, ss(15), s // 2), fill=acc, width=w, joint="curve")
    out["snapshot"] = im

    im, d = icon_canvas()                         # information
    d.ellipse((ss(3), ss(3), s - ss(3), s - ss(3)), outline=(*p.dim, 255), width=w)
    d.ellipse((s // 2 - ss(1), ss(6), s // 2 + ss(1), ss(8)), fill=ink)
    d.line((s // 2, ss(10), s // 2, ss(16)), fill=ink, width=w)
    out["info"] = im

    im, d = icon_canvas()                         # other systems (os-prober): a window
    d.rectangle((ss(3), ss(4), s - ss(3), s - ss(4)), outline=ink, width=w)
    d.line((ss(3), ss(8), s - ss(3), ss(8)), fill=ink, width=w)
    out["other"] = im

    im, d = icon_canvas()                         # the Field Kit: a case and its handle
    d.rounded_rectangle((ss(2), ss(8), s - ss(2), ss(19)), radius=ss(2), outline=ink, width=w)
    d.line((ss(8), ss(8), ss(8), ss(4), s - ss(8), ss(4), s - ss(8), ss(8)), fill=ink, width=w, joint="curve")
    d.line((ss(2), ss(12), s - ss(2), ss(12)), fill=(*p.dim, 255), width=ss(1))
    d.rectangle((s // 2 - ss(2), ss(11), s // 2 + ss(2), ss(14)), fill=acc)
    out["fieldkit"] = im

    im, d = icon_canvas()                         # boot options: three sliders
    for i, x in enumerate((ss(6), ss(11), ss(16))):
        d.line((ss(3), x, s - ss(3), x), fill=ink, width=ss(1))
        k = (ss(8), ss(15), ss(10))[i]
        d.rectangle((k - ss(2), x - ss(2), k + ss(2), x + ss(2)), fill=acc)
    out["options"] = im

    return {k: down(v, (ICON, ICON)) for k, v in out.items()}


# which classes get which icon (GRUB takes an entry's first class that has one)
ICON_CLASSES = {
    "emblem": ["bromigos", "arch", "gnu-linux", "os", "live"],
    "install": ["install"],
    "safe": ["safe", "nomodeset", "gpu"],
    "speech": ["speech", "accessibility"],
    "memtest": ["memtest", "memtest86"],
    "disk": ["disk", "chain", "existing"],
    "efi": ["efi", "firmware", "uefi"],
    "shell": ["shell", "text"],
    "fieldkit": ["fieldkit", "rescue"],
    "options": ["options"],
    "shutdown": ["shutdown", "poweroff", "halt"],
    "restart": ["restart", "reboot"],
    "rollback": ["rollback", "snapshots-menu"],
    "snapshot-pre": ["snapshot-pre"],
    "snapshot-post": ["snapshot-post"],
    "snapshot": ["snapshot", "snapshots", "snapshot-single"],
    "info": ["info", "verbose"],
    "other": ["windows", "osx", "macosx", "hurd", "recovery"],
}


def icons(out, p, kit, own):
    d = os.path.join(out, "icons")
    os.makedirs(d, exist_ok=True)
    g = glyphs(p)
    small = os.path.join(kit, "emblem-small-64.png")
    em = Image.open(small).convert("RGBA") if os.path.exists(small) else None
    if em is not None and not own:
        em = recolour(em, p.primary)
    if em is not None:
        g["emblem"] = down(em, (ICON, ICON))
    for icon, classes in ICON_CLASSES.items():
        if icon not in g:
            continue
        im = haloed(g[icon], p.background)
        for c in classes:
            save(im, os.path.join(d, f"{c}.png"))


def haloed(icon, colour):
    """An icon with a thin edge in the background colour round its strokes: GRUB draws the
    selected entry's icon on the phosphor bar, where the bar's own colour would hide it."""
    a = icon.getchannel("A").filter(ImageFilter.MaxFilter(3))
    out = Image.new("RGBA", icon.size, (*colour, 0))
    out.putalpha(a.point(lambda v: round(v * 0.85)))
    out.alpha_composite(icon)
    return out


# ------------------------------------------------------------------ fonts

def fonts(out, font_dir, prebuilt):
    for name, weight, size in FONTS:
        dst = os.path.join(out, name)
        if prebuilt:
            shutil.copyfile(os.path.join(prebuilt, name), dst)
            continue
        ttf = os.path.join(font_dir, f"GeistMono-{weight}.ttf")
        if not os.path.exists(ttf):
            raise SystemExit(f"no {ttf} (ttf-geist-mono; or --fonts DIR with the pf2 files)")
        r = subprocess.run(["grub-mkfont", "-s", str(size), "-n", "Geist Mono", "-r", FONT_RANGES, "-o", dst, ttf],
                           capture_output=True, text=True)
        if r.returncode != 0 or not os.path.exists(dst):
            raise SystemExit(f"grub-mkfont {name}: {r.stderr.strip()}")


def font(weight, size):
    return f"Geist Mono {weight} {size}"


# ------------------------------------------------------------------ theme.txt

def theme_txt(p, heading, medium, plate):
    """The layout, in percentages of the screen (GRUB takes whole percents plus pixels):
    vertical positions by its height (the background is scaled to it), the emblem's centre
    at 50%, Plymouth's progress line at 72%. GRUB paints a theme's components from the last
    to the first, so they're listed top-most first."""
    c = p.hex
    line = round(LINE * 100)                      # 72
    top = round((0.5 - EMBLEM / 2) * 100)         # the emblem's top edge, 33%
    head_font = font("SemiBold", 26 if medium else 20)
    head_h = 34 if medium else 28
    track = hexstr(mix(p.background, p.dim, 0.45))
    bar = f"left = 50%-{METER_W // 2}  top = {line}%-{METER_H // 2}  width = {METER_W}  height = {METER_H}"
    lines = [
        f"# bromigOS boot menu: {p.name}. Made by build-grub-theme.py (v{VERSION}) from the theme's",
        "# colours, its lock-screen image and emblem kit; `bromigos boot theme` makes it again,",
        "# don't edit it here. docs/boot.md. GRUB paints the components last to first.",
        'title-text: ""',
        'desktop-image: "background.png"',
        'desktop-image-scale-method: "fitheight"',
        'desktop-image-h-align: "center"',
        'desktop-image-v-align: "center"',
        f'desktop-color: "{c["background"]}"',
        f'message-font: "{font("Regular", 16)}"',
        f'message-color: "{c["soft"]}"',
        f'message-bg-color: "{c["background"]}"',
        f'terminal-font: "{font("Regular", 16)}"',
        'terminal-box: "terminal_*.png"',
        'terminal-left: "8%"',
        'terminal-top: "10%"',
        'terminal-width: "84%"',
        'terminal-height: "80%"',
        'terminal-border: "0"',
        "",
        "# what the keys do",
        "+ label {",
        "    left = 0  top = 100%-30  width = 100%  height = 20",
        f'    text = "{FOOTER}"  align = "center"',
        f'    font = "{font("Regular", 14)}"  color = "{c["muted"]}"',
        "}",
        "",
        "# the channel list, under the meter",
        "+ boot_menu {",
        f"    left = 50%-380  top = {line}%+40  width = 760  height = {100 - line - 5}%-40",
        f'    item_font = "{font("Regular", 16)}"  item_color = "{c["text"]}"',
        f'    selected_item_font = "{font("Bold", 16)}"  selected_item_color = "{c["background"]}"',
        "    icon_width = 22  icon_height = 22  item_icon_space = 12",
        "    item_height = 26  item_padding = 0  item_spacing = 2",
        '    selected_item_pixmap_style = "select_*.png"',
        '    scrollbar = true  scrollbar_width = 4  scrollbar_slice = "center"  scrollbar_left_pad = 8',
        '    scrollbar_frame = "scroll_frame_*.png"  scrollbar_thumb = "scroll_thumb_*.png"',
        "}",
        "",
        "# the timeout, counting: TUNING IN · 5",
        "+ label {",
        '    id = "__timeout__"',
        f"    left = 0  top = {line}%+14  width = 100%  height = 20",
        f'    text = "{TIMEOUT}"  align = "center"',
        f'    font = "{font("Regular", 14)}"  color = "{c["soft"]}"',
        "}",
        "",
        "# the signal meter on Plymouth's progress line: the mask (its bars are holes), the",
        "# bar it shows through (the accent fills the track as the seconds run), the plate",
        "+ image {",
        f"    {bar}",
        '    file = "meter_mask.png"',
        "}",
        "+ progress_bar {",
        '    id = "__timeout__"',
        f"    {bar}",
        f'    fg_color = "{c["primary"]}"  bg_color = "{track}"  border_color = "{hexstr(plate)}"',
        f'    font = "{font("Regular", 14)}"',
        "}",
        "+ image {",
        f"    left = 50%-{METER_W // 2 + METER_MARGIN}  top = {line}%-{METER_PLATE_H // 2}  width = {METER_W + 2 * METER_MARGIN}  height = {METER_PLATE_H}",
        '    file = "meter_plate.png"',
        "}",
        "",
        "# the heading, over the emblem",
        "+ label {",
        f'    left = 0  top = {top}%-{head_h + 34}  width = 100%  height = {head_h}',
        f'    text = "{heading}"  align = "center"',
        f'    font = "{head_font}"  color = "{c["primary"]}"',
        "}",
    ]
    return "\n".join(lines) + "\n"


# ------------------------------------------------------------------ colors.cfg

# GRUB's console and its editor (E, C) take colours by name, from VGA's sixteen
GRUB_COLOURS = {
    "black": (0, 0, 0), "blue": (0, 0, 170), "green": (0, 170, 0), "cyan": (0, 170, 170),
    "red": (170, 0, 0), "magenta": (170, 0, 170), "brown": (170, 85, 0), "light-gray": (170, 170, 170),
    "dark-gray": (85, 85, 85), "light-blue": (85, 85, 255), "light-green": (85, 255, 85),
    "light-cyan": (85, 255, 255), "light-red": (255, 85, 85), "light-magenta": (255, 85, 255),
    "yellow": (255, 255, 85), "white": (255, 255, 255),
}


def grub_colour(rgb):
    """The nearest of GRUB's sixteen colour names (never black: black is see-through)."""
    return min((n for n in GRUB_COLOURS if n != "black"),
               key=lambda n: sum((a - b) ** 2 for a, b in zip(GRUB_COLOURS[n], rgb)))


def colors_cfg(p):
    """colors.cfg: the theme's colours for what theme.txt can't reach: GRUB's editor (E) and
    console (C), and the menu when the theme can't load. grub.cfg sources it (11_bromigos-options,
    the media's grub.cfg). Black backgrounds are see-through, so the terminal box shows."""
    ink, sel = grub_colour(p.text), grub_colour(p.primary)
    return "\n".join([
        f"# bromigOS boot menu: {p.name}'s colours for GRUB's editor and console (build-grub-theme.py)",
        f"set color_normal={ink}/black",
        f"set color_highlight=black/{sel}",
        f"set menu_color_normal={ink}/black",
        f"set menu_color_highlight=black/{sel}",
    ]) + "\n"


# ------------------------------------------------------------------ inputs

def first(*paths):
    for p in paths:
        if p and os.path.exists(p):
            return p
    return None


def wick_kit():
    return first(os.path.join(REPO, "themes", "wick", "emblem"), os.path.join(SHARE, "themes", "wick", "emblem"))


def den(lock):
    name = f"bromigos-{'lock' if lock else 'den'}-empty-2560x1440.jpg"
    path = first(os.path.join(REPO, "desktop", "wallpaper", name), os.path.join(SHARE, "wallpaper", name))
    if not path:
        raise SystemExit(f"no {name} (bromigos-desktop's den)")
    return path


def has_kit(d):
    return bool(d) and os.path.exists(os.path.join(d, "lock", "ring.png")) and os.path.exists(os.path.join(d, "lock", "flame.png"))


def gather(args):
    """What the theme is made from: (name, palette, emblem kit, whether the kit is the theme's
    own, how the background is made, the files it all comes from)."""
    name = "wick"
    inputs = []
    if args.current:
        cur = os.path.join(STATE, "theme", "current")
        inputs.append(os.path.join(cur, "palette.json"))
        with open(inputs[-1]) as f:
            doc = json.load(f)
        name = doc.get("theme", "wick")
        p = Palette(doc["colors"], doc.get("name", name), doc.get("mode", "dark"))
        kit = os.path.join(cur, "emblem")
        bg_dir = os.path.join(cur, "backgrounds")
    elif args.palette:
        inputs.append(args.palette)
        with open(args.palette) as f:
            doc = json.load(f)
        name = doc.get("theme", "wick")
        p = Palette(doc["colors"], doc.get("name", name), doc.get("mode", "dark"))
        kit, bg_dir = None, None
    else:
        d = args.theme_dir
        name = os.path.basename(os.path.normpath(d))
        meta = {}
        if os.path.exists(os.path.join(d, "theme.toml")):
            with open(os.path.join(d, "theme.toml"), "rb") as f:
                meta = tomllib.load(f)
        inputs.append(os.path.join(d, "colors.toml"))
        p = Palette(resolve_colors_toml(inputs[-1]), meta.get("name", name), meta.get("mode", "dark"))
        kit = os.path.join(d, "emblem")
        bg_dir = os.path.join(d, "backgrounds")
    if args.emblem:
        kit = args.emblem
    # a theme's own kit is drawn in its colours; without one it gets the Wick's, recoloured
    own = has_kit(kit)
    if not own:
        kit, own = wick_kit(), name == "wick"
    inputs += [os.path.join(kit, "lock", "ring.png"), os.path.join(kit, "lock", "flame.png"),
               os.path.join(kit, "emblem-small-64.png")]
    is_world = bool(bg_dir) and (os.path.isdir(os.path.join(bg_dir, "layers")) or os.path.exists(os.path.join(bg_dir, "comp.webp")))
    if args.medium:
        bg = ("night", den(lock=False))
    elif args.background:
        bg = ("lock", args.background)
    elif is_world:
        bg = ("world", bg_dir)
    elif name == "wick":
        bg = ("lock", den(lock=True))
    else:
        # a theme without a painting: the Wick's den, in its colours
        bg = ("tinted", den(lock=True))
    if bg[0] == "world":
        layers = os.path.join(bg_dir, "layers")
        inputs += sorted(os.path.join(layers, f) for f in os.listdir(layers)) if os.path.isdir(layers) \
            else [os.path.join(bg_dir, "comp.webp")]
    else:
        inputs.append(bg[1])
    return name, p, kit, own, bg, inputs


def background(bg, p):
    kind, src = bg
    if kind == "night":
        # the ISO's title card: the Wick's den at night, softer than the lock screen's
        im = Image.open(src).convert("RGB")
        im = ImageEnhance.Brightness(im.filter(ImageFilter.GaussianBlur(1.5))).enhance(0.42)
        im = ImageEnhance.Color(im).enhance(0.85)
    elif kind == "world":
        im = lock_from_world(src)
    else:
        im = Image.open(src).convert("RGB")
        if kind == "tinted":
            im = duotone(im, p.background, p.dim)
    return cover(im)


def inputs_key(args, p, inputs, heading):
    """What a render is made from: the generator, the variant, the colours, every file's size
    and time. The same key, the same theme (--if-changed skips the work)."""
    h = hashlib.sha256()
    h.update(json.dumps([VERSION, bool(args.medium), heading, p.hex, bool(args.no_fonts)], sort_keys=True).encode())
    for path in inputs:
        try:
            st = os.stat(path)
            h.update(f"{path}:{st.st_size}:{st.st_mtime_ns}".encode())
        except OSError:
            h.update(f"{path}:-".encode())
    return h.hexdigest()


# ------------------------------------------------------------------ the whole theme

def digest(out):
    files = {}
    for root, _, names in os.walk(out):
        for n in sorted(names):
            path = os.path.join(root, n)
            rel = os.path.relpath(path, out)
            if rel == "manifest.json":
                continue
            with open(path, "rb") as f:
                files[rel] = hashlib.sha256(f.read()).hexdigest()
    return dict(sorted(files.items()))


def manifest_digest(m):
    """What identifies a boot theme's pictures and colours: the root helper records it for the
    theme it put in /boot, and `bromigos boot theme` compares it with the one wanted."""
    key = {"generator": m.get("generator"), "colors": m.get("colors"), "plate": m.get("plate"), "files": m.get("files")}
    return hashlib.sha256(json.dumps(key, sort_keys=True).encode()).hexdigest()


def build(args):
    name, p, kit, own, bg, inputs = gather(args)
    out = args.out
    medium = bool(args.medium)
    heading = args.heading or (HEADING_MEDIUM if medium else HEADING_INSTALLED)
    key = inputs_key(args, p, inputs, heading)
    if args.if_changed:
        try:
            with open(os.path.join(out, "manifest.json")) as f:
                old = json.load(f)
            if old.get("inputs") == key and old.get("digest"):
                return old
        except (OSError, ValueError):
            pass
    final, out = out, f"{out}.tmp-{os.getpid()}"
    if os.path.isdir(out):
        shutil.rmtree(out)
    os.makedirs(out)
    im = shade(background(bg, p), p.background)
    im = scanlines(im)
    ring, flame = emblem_layers(kit, p, own)
    im = place_emblem(im, ring, flame)
    im.save(os.path.join(out, "background.png"), optimize=True)
    selection_bar(out, p)
    scrollbar(out, p)
    terminal_box(out, p)
    plate = plate_colour(im)
    meter(out, p, plate)
    icons(out, p, kit, own)
    if not args.no_fonts:
        fonts(out, args.font_dir, args.fonts)
    with open(os.path.join(out, "theme.txt"), "w") as f:
        f.write(theme_txt(p, heading, medium, plate))
    with open(os.path.join(out, "colors.cfg"), "w") as f:
        f.write(colors_cfg(p))
    manifest = {
        "schema": 1,
        "generator": VERSION,
        "theme": name,
        "name": p.name,
        "variant": "medium" if medium else "installed",
        "colors": p.hex,
        "plate": hexstr(plate),
        "files": digest(out),
        "inputs": key,
    }
    manifest["digest"] = manifest_digest(manifest)
    with open(os.path.join(out, "manifest.json"), "w") as f:
        json.dump(manifest, f, indent=1)
        f.write("\n")
    # made beside it, then swapped in: a render running at the same time never sees half
    old = f"{final}.old-{os.getpid()}"
    if os.path.isdir(final):
        os.rename(final, old)
    os.rename(out, final)
    if os.path.isdir(old):
        shutil.rmtree(old)
    return manifest


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    src = ap.add_mutually_exclusive_group()
    src.add_argument("--theme-dir", help="a theme's directory (colors.toml, emblem/, backgrounds/)")
    src.add_argument("--current", action="store_true", help="the theme in force (~/.local/state/bromigos/theme/current)")
    src.add_argument("--palette", help="a palette.json (with --emblem and --background)")
    ap.add_argument("--out", help="the theme's directory (made afresh)")
    ap.add_argument("--fonts-out", help="only make the fonts (Geist Mono as pf2) into this directory")
    ap.add_argument("--emblem", help="an emblem kit (lock/ring.png, lock/flame.png)")
    ap.add_argument("--background", help="the lock-screen image (already softened and darkened)")
    ap.add_argument("--medium", action="store_true", help="the ISO's title card")
    ap.add_argument("--heading", help="the heading's text")
    fsrc = ap.add_mutually_exclusive_group()
    fsrc.add_argument("--fonts", help="a directory with the pf2 files (copied)")
    fsrc.add_argument("--font-dir", default="/usr/share/fonts/TTF", help="Geist Mono's TTFs, for grub-mkfont")
    ap.add_argument("--no-fonts", action="store_true", help="leave the fonts out (the root helper adds the package's)")
    ap.add_argument("--if-changed", action="store_true", help="keep DIR when it was made from the same inputs")
    ap.add_argument("--json", action="store_true", help="print the manifest")
    args = ap.parse_args(argv)
    if args.fonts_out:
        os.makedirs(args.fonts_out, exist_ok=True)
        fonts(args.fonts_out, args.font_dir, None)
        print(f"{args.fonts_out}: {len(FONTS)} fonts")
        return 0
    if not (args.theme_dir or args.current or args.palette) or not args.out:
        ap.error("--theme-dir, --current or --palette, and --out")
    if args.fonts is None and not args.no_fonts and not shutil.which("grub-mkfont"):
        default = os.path.join(SHARE, "boot", "grub", "fonts")
        if os.path.isdir(default):
            args.fonts = default
    m = build(args)
    if args.json:
        print(json.dumps(m, indent=1))
    else:
        print(f"{args.out}: {m['name']} ({m['variant']}), {len(m['files'])} files")


if __name__ == "__main__":
    sys.exit(main())
