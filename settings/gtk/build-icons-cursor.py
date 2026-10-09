#!/usr/bin/env python3
"""Builds two user themes into linux/.local/share/icons/:

  Bromigos         icon theme: Breeze Dark with the folder/place icons recoloured
                   from Breeze blue to phosphor green. Everything else is inherited.
  Bromigos-cursor  Xcursor theme drawn here (arrow, pointer, text, crosshair,
                   busy, not-allowed, move, resizes); the rest inherit Adwaita.

No packages needed: SVGs are rasterised with rsvg-convert and the Xcursor files
are written directly (the format is a small table of ARGB images), since
xcursorgen is not installed.

Rebuild:  ./build-icons-cursor.py [--out DIR]   (bromigos-settings: --out /usr/share/icons)
Apply:    gsettings set org.gnome.desktop.interface icon-theme Bromigos
          gsettings set org.gnome.desktop.interface cursor-theme Bromigos-cursor
          hyprctl setcursor Bromigos-cursor 24
"""
import math
import os
import shutil
import struct
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.realpath(__file__))
ICONS = os.path.normpath(os.path.join(HERE, "..", "..", "..", ".local", "share", "icons"))
if "--out" in sys.argv[1:]:          # packaging: into /usr/share/icons (bromigos-settings)
    ICONS = os.path.abspath(sys.argv[sys.argv.index("--out") + 1])
BREEZE = "/usr/share/icons/breeze-dark"

VOID, PHOSPHOR, DIM, DANGER = "#000500", "#39ff14", "#159b09", "#ff766f"
BREEZE_ACCENT = "#3daee9"
FOLDER = "#1f8f12"      # between phosphor-dim and phosphor: reads as green, not neon


# ------------------------------------------------------------------ icons
def build_icons():
    out = os.path.join(ICONS, "Bromigos")
    if os.path.isdir(out):
        shutil.rmtree(out)
    dirs = []
    src_places = os.path.join(BREEZE, "places")
    for size in sorted(os.listdir(src_places)):
        sdir = os.path.join(src_places, size)
        files = {}
        for fn in sorted(os.listdir(sdir)):
            p = os.path.join(sdir, fn)
            real = os.path.realpath(p)
            if not fn.endswith(".svg") or os.path.dirname(real) != sdir:
                continue
            with open(real) as f:
                svg = f.read()
            if BREEZE_ACCENT in svg:
                files[fn] = (os.readlink(p) if os.path.islink(p) else None, svg)
        if not files:
            continue
        ddir = os.path.join(out, "places", size)
        os.makedirs(ddir)
        for fn, (link, svg) in files.items():
            dst = os.path.join(ddir, fn)
            if link and os.path.basename(link) in files:
                os.symlink(os.path.basename(link), dst)
            else:
                with open(dst, "w") as f:
                    f.write(svg.replace(BREEZE_ACCENT, FOLDER))
        dirs.append(size)
    # Directory metadata copied from Breeze Dark so sizes and scales resolve the same.
    meta = {}
    with open(os.path.join(BREEZE, "index.theme")) as f:
        cur = None
        for line in f:
            line = line.strip()
            if line.startswith("["):
                cur = line[1:-1]
                meta[cur] = []
            elif cur and "=" in line and not line.startswith("Name[") and not line.startswith("Comment["):
                meta[cur].append(line)
    names = [f"places/{d}" for d in dirs]
    with open(os.path.join(out, "index.theme"), "w") as f:
        f.write("[Icon Theme]\nName=Bromigos\nComment=Breeze Dark with phosphor folders\n"
                "Inherits=breeze-dark,breeze,hicolor\n"
                f"Directories={','.join(names)}\n\n")
        for n in names:
            f.write(f"[{n}]\n" + "\n".join(meta.get(n, [])) + "\n\n")
    return len(dirs)


# ------------------------------------------------------------------ cursors
# Each shape is drawn on a 32-unit canvas; the hotspot is in the same units.
# Readability on any background: a dark outline around a phosphor stroke, or a
# void fill with a phosphor edge.
ARROW = "M4 3 L4 25 L9.4 19.9 L13.2 28.4 L17 26.8 L13.3 18.5 L20.5 18.5 Z"


def svg(body):
    return f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32" width="32" height="32">{body}</svg>'


def line2(d, w=2.2):
    """A phosphor stroke with a void outline, for thin shapes."""
    return (f'<path d="{d}" fill="none" stroke="{VOID}" stroke-width="{w + 2.4}" stroke-linecap="round" stroke-linejoin="round"/>'
            f'<path d="{d}" fill="none" stroke="{PHOSPHOR}" stroke-width="{w}" stroke-linecap="round" stroke-linejoin="round"/>')


def arrow(fill, edge):
    return f'<path d="{ARROW}" fill="{fill}" stroke="{edge}" stroke-width="1.6" stroke-linejoin="round"/>'


def spinner(cx, cy, r, phase, w=2.6):
    a0 = phase * 2 * math.pi
    a1 = a0 + math.pi * 0.6
    x0, y0 = cx + r * math.cos(a0), cy + r * math.sin(a0)
    x1, y1 = cx + r * math.cos(a1), cy + r * math.sin(a1)
    return (f'<circle cx="{cx}" cy="{cy}" r="{r}" fill="none" stroke="{VOID}" stroke-width="{w + 2.4}"/>'
            f'<circle cx="{cx}" cy="{cy}" r="{r}" fill="none" stroke="#0f4f0f" stroke-width="{w}"/>'
            f'<path d="M{x0:.2f} {y0:.2f} A{r} {r} 0 0 1 {x1:.2f} {y1:.2f}" fill="none" '
            f'stroke="{PHOSPHOR}" stroke-width="{w}" stroke-linecap="round"/>')


def double_arrow(angle):
    d = "M5 16 L27 16 M5 16 L10 11 M5 16 L10 21 M27 16 L22 11 M27 16 L22 21"
    return f'<g transform="rotate({angle} 16 16)">{line2(d)}</g>'


FRAMES = 12
SHAPES = {
    # name: (frames, hotspot, names it serves)
    "default": ([svg(arrow(VOID, PHOSPHOR))], (4, 3),
                ["default", "left_ptr", "arrow", "top_left_arrow"]),
    "pointer": ([svg(arrow(PHOSPHOR, VOID))], (4, 3),
                ["pointer", "hand1", "hand2", "pointing_hand", "e29285e634086352946a0e7090d73106"]),
    "text": ([svg(line2("M16 6 L16 26 M12 6 L20 6 M12 26 L20 26", 2))], (16, 16),
             ["text", "xterm", "ibeam"]),
    "crosshair": ([svg(line2("M16 3 L16 12 M16 20 L16 29 M3 16 L12 16 M20 16 L29 16", 2)
                       + f'<circle cx="16" cy="16" r="1.4" fill="{PHOSPHOR}"/>')], (16, 16),
                  ["crosshair", "cross", "tcross", "cell"]),
    "wait": ([svg(spinner(16, 16, 9, i / FRAMES)) for i in range(FRAMES)], (16, 16),
             ["wait", "watch"]),
    "progress": ([svg(arrow(VOID, PHOSPHOR) + spinner(24, 24, 5, i / FRAMES, 2.2)) for i in range(FRAMES)], (4, 3),
                 ["progress", "left_ptr_watch", "half-busy", "00000000000000020006000e7e9ffc3f",
                  "08e8e1c95fe2fc01f976f1e063a24ccd", "3ecb610c1bf2410f44200f48c40d3599"]),
    "not-allowed": ([svg(f'<circle cx="16" cy="16" r="10" fill="none" stroke="{VOID}" stroke-width="5.4"/>'
                         f'<path d="M9 23 L23 9" stroke="{VOID}" stroke-width="5.4"/>'
                         f'<circle cx="16" cy="16" r="10" fill="none" stroke="{DANGER}" stroke-width="3"/>'
                         f'<path d="M9 23 L23 9" stroke="{DANGER}" stroke-width="3"/>')], (16, 16),
                    ["not-allowed", "crossed_circle", "no-drop", "forbidden", "circle",
                     "03b6e0fcb3499374a867c041f52298f0"]),
    "move": ([svg(line2("M16 4 L16 28 M4 16 L28 16 M16 4 L12 8 M16 4 L20 8 M16 28 L12 24 M16 28 L20 24 "
                        "M4 16 L8 12 M4 16 L8 20 M28 16 L24 12 M28 16 L24 20"))], (16, 16),
             ["move", "fleur", "all-scroll", "size_all", "grabbing", "closedhand", "dnd-move",
              "4498f0e0c1937ffe01fd06f973665830", "9081237383d90e509aa00f00170e968f"]),
    "ew-resize": ([svg(double_arrow(0))], (16, 16),
                  ["ew-resize", "col-resize", "sb_h_double_arrow", "h_double_arrow", "size_hor",
                   "e-resize", "w-resize", "right_side", "left_side", "split_h",
                   "028006030e0e7ebffc7f7070c0600140", "14fef782d02440884392942c11205230"]),
    "ns-resize": ([svg(double_arrow(90))], (16, 16),
                  ["ns-resize", "row-resize", "sb_v_double_arrow", "v_double_arrow", "size_ver",
                   "n-resize", "s-resize", "top_side", "bottom_side", "split_v",
                   "00008160000006810000408080010102", "2870a09082c103050810ffdffffe0204"]),
    "nwse-resize": ([svg(double_arrow(45))], (16, 16),
                    ["nwse-resize", "size_fdiag", "nw-resize", "se-resize", "top_left_corner",
                     "bottom_right_corner", "c7088f0f3e6c8088236ef8e1e3e70000"]),
    "nesw-resize": ([svg(double_arrow(-45))], (16, 16),
                    ["nesw-resize", "size_bdiag", "ne-resize", "sw-resize", "top_right_corner",
                     "bottom_left_corner", "fcf1c3c7cd4491d801f1e1c78f100000"]),
}
SIZES = (24, 32, 48)


def rasterize(svg_text, size, tmp):
    src, png = os.path.join(tmp, "c.svg"), os.path.join(tmp, "c.png")
    with open(src, "w") as f:
        f.write(svg_text)
    subprocess.run(["rsvg-convert", "-w", str(size), "-h", str(size), "-o", png, src], check=True)
    from PIL import Image
    im = Image.open(png).convert("RGBA")
    px = []
    data = im.tobytes()
    for i in range(0, len(data), 4):   # Xcursor wants premultiplied ARGB
        r, g, b, a = data[i:i + 4]
        px.append((a << 24) | ((r * a // 255) << 16) | ((g * a // 255) << 8) | (b * a // 255))
    return px


def write_xcursor(path, images):
    """images: [(nominal, w, h, xhot, yhot, delay_ms, pixels)]"""
    ntoc = len(images)
    header = struct.pack("<4sIII", b"Xcur", 16, 0x10000, ntoc)
    pos = 16 + ntoc * 12
    toc, chunks = b"", b""
    for nominal, w, h, xh, yh, delay, px in images:
        toc += struct.pack("<III", 0xFFFD0002, nominal, pos)
        chunk = struct.pack("<IIIIIIIII", 36, 0xFFFD0002, nominal, 1, w, h, xh, yh, delay)
        chunk += struct.pack(f"<{len(px)}I", *px)
        chunks += chunk
        pos += len(chunk)
    with open(path, "wb") as f:
        f.write(header + toc + chunks)


def build_cursors():
    out = os.path.join(ICONS, "Bromigos-cursor")
    if os.path.isdir(out):
        shutil.rmtree(out)
    cdir = os.path.join(out, "cursors")
    os.makedirs(cdir)
    with tempfile.TemporaryDirectory() as tmp:
        for name, (frames, (hx, hy), aliases) in SHAPES.items():
            images = []
            for size in SIZES:
                s = size / 32
                for fr in frames:
                    images.append((size, size, size, round(hx * s), round(hy * s),
                                   60 if len(frames) > 1 else 0, rasterize(fr, size, tmp)))
            write_xcursor(os.path.join(cdir, name), images)
            for a in aliases:
                if a != name:
                    os.symlink(name, os.path.join(cdir, a))
    with open(os.path.join(out, "index.theme"), "w") as f:
        f.write("[Icon Theme]\nName=Bromigos-cursor\nComment=Phosphor cursors; unlisted shapes come from Adwaita\n"
                "Inherits=Adwaita\n")
    with open(os.path.join(out, "cursor.theme"), "w") as f:
        f.write("[Icon Theme]\nName=Bromigos-cursor\nInherits=Adwaita\n")
    return len(SHAPES)


if __name__ == "__main__":
    print(f"icons: {build_icons()} place sizes; cursors: {build_cursors()} shapes -> {ICONS}")
