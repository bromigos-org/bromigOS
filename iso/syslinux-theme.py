#!/usr/bin/env python3
"""The medium's BIOS boot menu (syslinux's vesamenu): its title card and font (docs/boot.md).

  iso/syslinux-theme.py --out DIR [--font-dir /usr/share/fonts/TTF]

Writes DIR/splash.png (1024x768: the Wick's den at night, "BROMIGOS // RELAY MEDIUM", the
burn-in where the splash puts it and the signal meter on its progress line, as the UEFI
menu's GRUB theme draws them) and DIR/bromigos.psf (Geist Mono as an 8x16 console font in
code page 437, which vesamenu reads). iso/build-in-container.sh runs it into the profile's
syslinux/; archiso_head.cfg places the channel list under the meter.
"""

import argparse
import importlib.machinery
import importlib.util
import os
import struct
import sys
import tempfile

from PIL import Image, ImageDraw, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
SW, SH = 1024, 768          # vesamenu's MENU RESOLUTION
CELL_W, CELL_H = 8, 16      # vesamenu's fonts are 8 pixels wide


def grub_theme():
    path = os.path.join(REPO, "settings", "grub", "build-grub-theme.py")
    loader = importlib.machinery.SourceFileLoader("build_grub_theme", path)
    spec = importlib.util.spec_from_loader("build_grub_theme", loader)
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    return mod


def splash(gen, font_dir, out):
    """The GRUB theme's medium background, at vesamenu's size, with the heading and the meter
    drawn in (vesamenu has no images of its own but the one)."""
    p = gen.Palette(gen.resolve_colors_toml(os.path.join(REPO, "themes", "wick", "colors.toml")), "Wick")
    kit = os.path.join(REPO, "themes", "wick", "emblem")
    im = gen.background(("night", gen.den(lock=False)), p)
    im = gen.shade(im, p.background)
    im = gen.scanlines(im)
    ring, flame = gen.emblem_layers(kit, p, True)
    im = gen.place_emblem(im, ring, flame)
    # 16:9 at 1440 rows -> 4:3 at 768: scaled to the height, the sides cropped (fitheight)
    w = round(gen.W * SH / gen.H)
    im = im.resize((w, SH), Image.LANCZOS)
    x = (w - SW) // 2
    im = im.crop((x, 0, x + SW, SH)).convert("RGBA")
    d = ImageDraw.Draw(im)
    # the heading, where the GRUB theme puts it: 34 px above the emblem's top, 34 px tall
    head = ImageFont.truetype(os.path.join(font_dir, "GeistMono-SemiBold.ttf"), 26)
    top = round(SH * 0.33) - 68
    tw = d.textlength(gen.HEADING_MEDIUM, font=head)
    d.text(((SW - tw) / 2, top + 4), gen.HEADING_MEDIUM, font=head, fill=(*p.primary, 255))
    # the signal meter on Plymouth's progress line, waiting: its bars dim (the track's colour
    # through the GRUB theme's mask, cut in the background's own colour there)
    y = round(SH * 0.72) - gen.METER_H // 2
    local = tuple(im.getpixel((SW // 2, y + gen.METER_H // 2))[:3])
    meter = Image.new("RGBA", (gen.METER_W, gen.METER_H), (*gen.mix(p.background, p.dim, 0.45), 255))
    with tempfile.TemporaryDirectory() as tmp:
        gen.meter(tmp, p, local)
        meter.alpha_composite(Image.open(os.path.join(tmp, "meter_mask.png")).convert("RGBA"))
    im.alpha_composite(meter, ((SW - gen.METER_W) // 2, y))
    im.convert("RGB").save(os.path.join(out, "splash.png"), optimize=True)


def psf(font_dir, out):
    """Geist Mono Regular as a PSF1 console font: 256 glyphs, 8x16, in code page 437's order
    (what syslinux reads its configuration's bytes as). Glyphs Geist Mono hasn't, blank."""
    font = ImageFont.truetype(os.path.join(font_dir, "GeistMono-Regular.ttf"), 13)
    ascent, _ = font.getmetrics()
    base = 12                       # the baseline's row in the cell
    glyphs = bytearray()
    for i in range(256):
        ch = bytes([i]).decode("cp437") if i >= 0x20 else ""
        cell = Image.new("1", (CELL_W, CELL_H), 0)
        if ch.strip():
            d = ImageDraw.Draw(cell)
            d.fontmode = "1"
            adv = font.getlength(ch)
            d.text((round((CELL_W - adv) / 2), base - ascent), ch, font=font, fill=1)
        for y in range(CELL_H):
            row = 0
            for x in range(CELL_W):
                if cell.getpixel((x, y)):
                    row |= 0x80 >> x
            glyphs.append(row)
    with open(os.path.join(out, "bromigos.psf"), "wb") as f:
        f.write(struct.pack("<BBBB", 0x36, 0x04, 0x00, CELL_H))
        f.write(bytes(glyphs))


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--out", required=True)
    ap.add_argument("--font-dir", default="/usr/share/fonts/TTF")
    args = ap.parse_args(argv)
    os.makedirs(args.out, exist_ok=True)
    gen = grub_theme()
    splash(gen, args.font_dir, args.out)
    psf(args.font_dir, args.out)
    print(f"{args.out}: splash.png, bromigos.psf")


if __name__ == "__main__":
    sys.exit(main())
