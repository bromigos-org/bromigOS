"""Themed QR codes, in a world's colours with its emblem (docs/qr.md): the one QR component the
installer (its GUI and TUI), Settings and Field Kit draw with.

    import bromigos_qr as Q
    img, style = Q.render(text, style="camera")          # a PIL image, and the style it ended up as
    img, style = Q.render(text, style="art", world="wick")
    Q.save(text, "code.png", style="brodec")
    for line in Q.terminal(text): print(line)            # coloured half blocks, any terminal
    Q.kitty(png_bytes)                                   # the image itself, on kitty's terminal

Three styles, safest first:

  camera   for any phone camera (store links, share links): the world's dark ink on its light
           paper, rounded modules, finder patterns drawn as the emblem's rings (the 7x7 structure
           kept), the world's emblem in the centre. Error correction H; the emblem covers 6%.
  brodec   for BRODEC's own scanner (pairing codes): inverted, the world's glowing light on its
           dark, the same rings and emblem.
  art      brodec's colours with the world's picture blended in as a halftone: each module's
           centre keeps full contrast, the rest of it carries the picture, toned towards the
           module's colour. Finders, timing and alignment patterns stay solid.

Every style is checked by decoding it (`check`: zbar and ZXing, at full size and at phone-camera
size with blur and a slight tilt); `render` falls back to the next safer style when a decoder
here can't read it. `python3 bromigos_qr.py gallery DIR` draws every style in every world and
writes what each decoder read (DIR/report.json). Needs Pillow and python-qrcode.
"""

import io
import json
import math
import os
import shutil
import subprocess
import sys
import tempfile
import tomllib

import qrcode
from qrcode import constants, util
from PIL import Image, ImageDraw, ImageFilter, ImageOps

STYLES = ("camera", "brodec", "art")
SAFER = {"art": "brodec", "brodec": "camera", "camera": None}
THEMES = [os.environ.get("BROMIGOS_THEMES") or "",
          "/usr/share/bromigos/themes",
          os.path.join(os.path.dirname(os.path.dirname(os.path.realpath(__file__))), "themes")]
MODULE = 16              # pixels per module in a rendered image
QUIET = 4                # modules of quiet zone, as the standard asks
LOGO = 0.22              # the emblem's plate: 22% of the code's width (under 5% of its area)
MIN_CONTRAST = 7.0       # dark against light, WCAG's ratio: what `check` requires of every style


# ------------------------------------------------------------------ a world's colours and art

def _theme_dir(world):
    for base in THEMES:
        if base and os.path.isfile(os.path.join(base, world, "colors.toml")):
            return os.path.join(base, world)
    return None


def _resolve(doc):
    """colors.toml's values with its references followed: a value is "#rrggbb", a top-level
    name, a [colors] name, or "table.key"."""
    flat = {}
    for k, v in doc.items():
        if isinstance(v, dict):
            for k2, v2 in v.items():
                flat[f"{k}.{k2}"] = v2
                if k == "colors":
                    flat[k2] = v2
        else:
            flat[k] = v

    def get(name, depth=0):
        v = flat.get(name)
        if not isinstance(v, str) or depth > 12:
            return None
        return v if v.startswith("#") else get(v, depth + 1)
    return {k: get(k) for k in flat if get(k)}


def palette(world=None):
    """The world's colours as (r, g, b): the theme in force when `world` is None (bromigos_theme),
    else themes/<world>/colors.toml; the Wick's when neither is there."""
    if world is None:
        try:
            sys.path.insert(0, "/usr/lib/bromigos/lib")
            import bromigos_theme as T
            return {k: _rgb(T.hex(k)) for k in ("background", "panel", "selection", "primary", "soft",
                                                  "dim", "text", "muted", "white")}
        except Exception:
            world = "wick"
    d = _theme_dir(world) or _theme_dir("wick")
    with open(os.path.join(d, "colors.toml"), "rb") as f:
        doc = _resolve(tomllib.load(f))
    pal = {k: _rgb(v) for k, v in doc.items()}
    pal.setdefault("white", (255, 255, 255))
    return pal


def _rgb(h):
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def _mix(a, b, t):
    return tuple(round(x + (y - x) * t) for x, y in zip(a, b))


def luminance(c):
    def ch(v):
        v /= 255
        return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4
    r, g, b = (ch(x) for x in c)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast(a, b):
    la, lb = sorted((luminance(a), luminance(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


def inks(world=None, inverted=False):
    """(dark, light) for a style: the world's deepest ink and its lightest paper, pushed apart
    until they reach MIN_CONTRAST. Inverted (brodec, art): the light is its glowing primary and
    the dark its background."""
    p = palette(world)
    if inverted:
        dark, light = p.get("background", (0, 0, 0)), _mix(p.get("primary", (57, 255, 20)), p.get("white", (255,) * 3), 0.25)
    else:
        dark = _mix(p.get("selection", p.get("panel", (0, 40, 0))), (0, 0, 0), 0.35)
        light = _mix(p.get("text", (200, 240, 200)), (255, 255, 255), 0.55)
    for _ in range(20):
        if contrast(dark, light) >= MIN_CONTRAST:
            break
        dark, light = _mix(dark, (0, 0, 0), 0.25), _mix(light, (255, 255, 255), 0.25)
    return dark, light


def emblem(world=None, on_dark=False):
    """The world's emblem (RGBA), or the Wick's tinted with the world's primary."""
    for w in ([world] if world else []) + ["wick"]:
        d = _theme_dir(w) if w else None
        if not d:
            continue
        for name in (("emblem-void-1024.png", "emblem-1024.png") if on_dark else ("emblem-1024.png",)):
            p = os.path.join(d, "emblem", name)
            if os.path.isfile(p):
                im = Image.open(p).convert("RGBA")
                if w != world and world:
                    im = _tint(im, palette(world).get("primary", (57, 255, 20)))
                return im
    return None


def art(world=None):
    """The world's picture for the art style: a background painting when the theme has one,
    else its emblem art."""
    d = _theme_dir(world or "wick")
    if d:
        bg = os.path.join(d, "backgrounds")
        for base, _, files in os.walk(bg) if os.path.isdir(bg) else []:
            for f in sorted(files):
                if f.endswith((".png", ".jpg", ".jpeg", ".webp")) and "comp" in f or f.startswith("00-"):
                    try:
                        return Image.open(os.path.join(base, f)).convert("RGB")
                    except OSError:
                        continue
    e = emblem(world, on_dark=True)
    return e.convert("RGB") if e else None


def _tint(im, colour):
    grey = ImageOps.grayscale(im)
    out = ImageOps.colorize(grey, (0, 0, 0), colour).convert("RGBA")
    out.putalpha(im.getchannel("A"))
    return out


# ------------------------------------------------------------------ the code

def matrix(text):
    """The modules (True dark) at error correction H, and its version."""
    q = qrcode.QRCode(error_correction=constants.ERROR_CORRECT_H, border=0)
    q.add_data(text)
    q.make(fit=True)
    return [list(r) for r in q.modules], q.version


def function_patterns(n, version):
    """The modules a style must draw solid: the finders and their separators, the timing
    lines, the alignment patterns, and the format and version information."""
    fixed = set()
    for (r0, c0) in ((0, 0), (0, n - 8), (n - 8, 0)):
        for r in range(r0, r0 + 8):
            for c in range(c0, c0 + 8):
                if 0 <= r < n and 0 <= c < n:
                    fixed.add((r, c))
    for i in range(n):
        fixed.add((6, i))
        fixed.add((i, 6))
    pos = util.pattern_position(version)
    for r in pos:
        for c in pos:
            if (r, c) in fixed and ((r < 9 and c < 9) or (r < 9 and c > n - 10) or (r > n - 10 and c < 9)):
                continue
            for dr in range(-2, 3):
                for dc in range(-2, 3):
                    fixed.add((r + dr, c + dc))
    for i in range(9):
        fixed.update({(8, i), (i, 8), (8, n - 1 - i), (n - 1 - i, 8)})
    if version >= 7:
        for i in range(6):
            for j in range(n - 11, n - 8):
                fixed.update({(i, j), (j, i)})
    return fixed


def _finder(draw, x, y, m, dark, light):
    """A finder as the emblem's rings: a 7x7 rounded ring one module thick, a light ring, a 3x3
    disc. The 1:1:3:1:1 widths every decoder looks for stay."""
    draw.rounded_rectangle([x, y, x + 7 * m - 1, y + 7 * m - 1], radius=int(2.2 * m), fill=dark)
    draw.rounded_rectangle([x + m, y + m, x + 6 * m - 1, y + 6 * m - 1], radius=int(1.5 * m), fill=light)
    draw.ellipse([x + 2 * m, y + 2 * m, x + 5 * m - 1, y + 5 * m - 1], fill=dark)


def _draw(mods, version, style, world, size=None):
    n = len(mods)
    m = MODULE
    inverted = style in ("brodec", "art")
    dark, light = inks(world, inverted)
    # inverted: a "dark" module (a 1 in the matrix) is drawn in the light ink
    on, off = (light, dark) if inverted else (dark, light)
    w = (n + 2 * QUIET) * m
    img = Image.new("RGB", (w, w), off)
    fixed = function_patterns(n, version)
    finder_origins = {(0, 0), (0, n - 7), (n - 7, 0)}
    in_finder = {(r0 + r, c0 + c) for (r0, c0) in finder_origins for r in range(7) for c in range(7)}
    if style == "art":
        img = _halftone(img, mods, fixed | in_finder, world, on, off, m)
    draw = ImageDraw.Draw(img)
    layer = Image.new("L", (w, w), 0)            # where modules are, for the glow
    ld = ImageDraw.Draw(layer)
    for r in range(n):
        for c in range(n):
            if (r, c) in in_finder or not mods[r][c]:
                continue
            x, y = (c + QUIET) * m, (r + QUIET) * m
            if style == "art" and (r, c) not in fixed:
                continue                          # drawn by the halftone
            if style == "camera" or (r, c) in fixed:
                draw.rounded_rectangle([x, y, x + m - 1, y + m - 1], radius=int(m * 0.3), fill=on)
            else:
                draw.ellipse([x + 1, y + 1, x + m - 2, y + m - 2], fill=on)
            ld.rectangle([x, y, x + m - 1, y + m - 1], fill=255)
    for (r0, c0) in finder_origins:
        _finder(draw, (c0 + QUIET) * m, (r0 + QUIET) * m, m, on, off)
    if inverted:
        # the glow: the light ink, blurred, under the code (it never reaches a module's centre)
        glow = layer.filter(ImageFilter.GaussianBlur(m * 0.45)).point(lambda v: int(v * 0.35))
        img = Image.composite(Image.new("RGB", (w, w), on), img, glow) if style == "brodec" else img
        draw = ImageDraw.Draw(img)
        for r in range(n):                        # sharp modules again over the glow
            for c in range(n):
                if mods[r][c] and (r, c) not in in_finder and style == "brodec":
                    x, y = (c + QUIET) * m, (r + QUIET) * m
                    if (r, c) in fixed:
                        draw.rounded_rectangle([x, y, x + m - 1, y + m - 1], radius=int(m * 0.3), fill=on)
                    else:
                        draw.ellipse([x + 1, y + 1, x + m - 2, y + m - 2], fill=on)
                elif not mods[r][c] and (r, c) not in in_finder and style == "brodec":
                    x, y = (c + QUIET) * m, (r + QUIET) * m
                    cx = m // 2
                    draw.rectangle([x + cx - m // 4, y + cx - m // 4, x + cx + m // 4, y + cx + m // 4], fill=off)
        for (r0, c0) in finder_origins:
            _finder(draw, (c0 + QUIET) * m, (r0 + QUIET) * m, m, on, off)
    # the emblem on its plate in the centre
    e = emblem(world, on_dark=inverted)
    if e is not None:
        plate = int(n * m * LOGO)
        plate -= plate % 2
        x = y = (w - plate) // 2
        draw.rounded_rectangle([x, y, x + plate, y + plate], radius=plate // 5, fill=off, outline=on, width=max(2, m // 6))
        inner = int(plate * 0.8)
        logo = e.resize((inner, inner), Image.LANCZOS)
        img.paste(logo, (x + (plate - inner) // 2, y + (plate - inner) // 2), logo)
    if size:
        img = img.resize((size, size), Image.LANCZOS)
    return img


def _halftone(img, mods, fixed, world, on, off, m):
    """The world's picture in each data module's outer ring, toned towards that module's colour;
    the centre (half the module's width) is the module's own colour, at full contrast."""
    n = len(mods)
    pic = art(world)
    if pic is None:
        return img
    w = img.width
    span = n * m
    pic = ImageOps.fit(pic, (span, span), Image.LANCZOS)
    grey = ImageOps.autocontrast(ImageOps.grayscale(pic))
    px = grey.load()
    out = img.copy()
    o = out.load()
    q = QUIET * m
    core0, core1 = m // 4, m - m // 4
    for r in range(n):
        for c in range(n):
            if (r, c) in fixed:
                continue
            want = on if mods[r][c] else off
            for y in range(m):
                for x in range(m):
                    if core0 <= x < core1 and core0 <= y < core1:
                        colour = want
                    else:
                        v = px[c * m + x, r * m + y] / 255
                        pic_colour = _mix(off, on, v)
                        colour = _mix(pic_colour, want, 0.55)
                    o[q + c * m + x, q + r * m + y] = colour
    return out


def render(text, style="camera", world=None, size=None, verify=True):
    """The code as a PIL image, and the style it was drawn in: `style` when a decoder here reads
    it (check), else the next safer one. With no decoder here, the style asked for (every style in
    every world is decoded in CI)."""
    mods, version = matrix(text)
    s = style if style in STYLES else "camera"
    while s:
        img = _draw(mods, version, s, world, size)
        if not verify or not decoders():
            return img, s
        if check(img, text, s)["ok"]:
            return img, s
        s = SAFER[s]
    img = qrcode.make(text, error_correction=constants.ERROR_CORRECT_H).convert("RGB")
    return img, "plain"


def save(text, path, **kw):
    img, s = render(text, **kw)
    img.save(path)
    return s


# ------------------------------------------------------------------ is it readable?

def decoders():
    return [d for d in ("zbarimg", "ZXingReader") if shutil.which(d)]


def _decode(path, tool, inverted):
    if tool == "zbarimg":
        r = subprocess.run(["zbarimg", "-q", "--raw", path], capture_output=True, text=True, timeout=30)
        return r.stdout.strip().splitlines()[0] if r.stdout.strip() else ""
    args = ["ZXingReader", "-bytes", "-formats", "QRCode"]
    if not inverted:
        args.insert(1, "-noinvert")
    r = subprocess.run(args + [path], capture_output=True, timeout=30)
    return r.stdout.decode("utf-8", "replace").strip()


def _camera(img, w=300):
    """The code as a phone's camera sees it: `w` px across (300 at arm's length, 200 from further
    off), a mild blur, a slight tilt, on a mid-grey table."""
    small = img.resize((w, w), Image.LANCZOS).filter(ImageFilter.GaussianBlur(0.8))
    canvas = Image.new("RGB", (w + 80, w + 80), (128, 128, 128))
    canvas.paste(small, (40, 40))
    d = 18
    coeffs = _perspective([(0, 0), (w + 80, 0), (w + 80, w + 80), (0, w + 80)],
                          [(d, 0), (w + 80 - d // 2, d // 2), (w + 80, w + 80), (0, w + 80 - d)])
    return canvas.transform(canvas.size, Image.PERSPECTIVE, coeffs, Image.BICUBIC, fillcolor=(128, 128, 128))


def _perspective(src, dst):
    import numpy  # noqa: F401  (only for the solve; Pillow ships no solver)
    a, b = [], []
    for (x, y), (u, v) in zip(dst, src):
        a.append([x, y, 1, 0, 0, 0, -u * x, -u * y])
        a.append([0, 0, 0, x, y, 1, -v * x, -v * y])
        b += [u, v]
    import numpy as np
    return np.linalg.solve(np.array(a, float), np.array(b, float)).tolist()


def check(img, text, style):
    """Whether this image decodes: each decoder here, at full size and as a camera sees it;
    camera style with ZXing's inverted search off (as any phone), brodec and art with it on (as
    BRODEC's scanner). And the ink's contrast. {"ok", "contrast", "reads": {tool: {view: ok}}}"""
    inverted = style in ("brodec", "art")
    out = {"style": style, "reads": {}}
    with tempfile.TemporaryDirectory() as d:
        views = {"full": img}
        try:
            views["camera"] = _camera(img, 300)
            views["far"] = _camera(img, 200)
        except Exception:
            pass
        for name, im in views.items():
            path = os.path.join(d, f"{name}.png")
            im.save(path)
            for tool in decoders():
                if tool == "zbarimg" and inverted:
                    continue          # zbar has no inverted search: BRODEC's scanner is ZXing
                out["reads"].setdefault(tool, {})[name] = _decode(path, tool, inverted) == text
    out["ok"] = bool(out["reads"]) and all(all(v.values()) for v in out["reads"].values())
    return out


# ------------------------------------------------------------------ in a terminal

def terminal(text, world=None, truecolor=None):
    """The code as lines of half blocks with both colours set in every cell (a cell all dark or
    all light is a space on that colour), in the world's camera-safe inks, for any terminal."""
    mods, _ = matrix(text)
    n = len(mods)
    full = [[False] * (n + 2 * QUIET) for _ in range(QUIET)] + \
           [[False] * QUIET + r + [False] * QUIET for r in mods] + \
           [[False] * (n + 2 * QUIET) for _ in range(QUIET)]
    dark, light = inks(world)
    if truecolor is None:
        truecolor = os.environ.get("COLORTERM") in ("truecolor", "24bit")
    if truecolor:
        fg = lambda c: f"\x1b[38;2;{c[0]};{c[1]};{c[2]}m"      # noqa: E731
        bg = lambda c: f"\x1b[48;2;{c[0]};{c[1]};{c[2]}m"      # noqa: E731
    else:
        fg = lambda c: "\x1b[30m" if c == dark else "\x1b[37m"   # noqa: E731
        bg = lambda c: "\x1b[40m" if c == dark else "\x1b[47m"   # noqa: E731
    lines = []
    for y in range(0, len(full), 2):
        top, bot = full[y], full[y + 1] if y + 1 < len(full) else [False] * len(full[0])
        s = ""
        for t, b in zip(top, bot):
            if t and b:
                s += bg(dark) + " "
            elif not t and not b:
                s += bg(light) + " "
            elif t:
                s += fg(dark) + bg(light) + "▀"
            else:
                s += fg(dark) + bg(light) + "▄"
        lines.append(s + "\x1b[0m")
    return lines


def kitty(png):
    """The kitty graphics protocol's escape for a PNG (kitty, and terminals that speak it)."""
    import base64
    data = base64.standard_b64encode(png).decode()
    parts = [data[i:i + 4096] for i in range(0, len(data), 4096)]
    out = ""
    for i, p in enumerate(parts):
        more = 1 if i < len(parts) - 1 else 0
        out += (f"\x1b_Ga=T,f=100,m={more};{p}\x1b\\" if i == 0 else f"\x1b_Gm={more};{p}\x1b\\")
    return out


def images_supported():
    return bool(os.environ.get("KITTY_WINDOW_ID")) or os.environ.get("TERM") == "xterm-kitty"


# ------------------------------------------------------------------ the gallery

def worlds():
    seen = []
    for base in THEMES:
        if base and os.path.isdir(base):
            for w in sorted(os.listdir(base)):
                if os.path.isfile(os.path.join(base, w, "colors.toml")) and w not in seen:
                    seen.append(w)
    return seen


def gallery(out, text):
    """Every style in every world, decoded; out/report.json says what each decoder read."""
    os.makedirs(out, exist_ok=True)
    report = {"text": text, "decoders": decoders(), "codes": []}
    for w in worlds():
        mods, version = matrix(text)
        for s in STYLES:
            img = _draw(mods, version, s, w)
            path = os.path.join(out, f"qr-{w}-{s}.png")
            img.save(path)
            c = check(img, text, s)
            dark, light = inks(w, s != "camera")
            c.update({"world": w, "file": os.path.basename(path), "contrast": round(contrast(dark, light), 2)})
            c["ok"] = c["ok"] and c["contrast"] >= MIN_CONTRAST
            report["codes"].append(c)
            print(f"{w:14} {s:7} contrast {c['contrast']:5.1f}  " +
                  "  ".join(f"{t}: {'/'.join(k for k, v in r.items() if v) or 'none'}" for t, r in c["reads"].items()) +
                  ("" if c["ok"] else "   FAILS"))
    with open(os.path.join(out, "report.json"), "w") as f:
        json.dump(report, f, indent=1)
    return report


def main(argv):
    import argparse
    ap = argparse.ArgumentParser(prog="bromigos qr", description="Themed QR codes (docs/qr.md)")
    sub = ap.add_subparsers(dest="cmd")
    p = sub.add_parser("show", help="a code in this terminal (the image itself on kitty)")
    p.add_argument("text")
    p.add_argument("--style", choices=STYLES, default="camera")
    p.add_argument("--world")
    p = sub.add_parser("png", help="a code as a PNG")
    p.add_argument("text")
    p.add_argument("out")
    p.add_argument("--style", choices=STYLES, default="camera")
    p.add_argument("--world")
    p.add_argument("--size", type=int)
    p = sub.add_parser("gallery", help="every style in every world, decoded")
    p.add_argument("out")
    p.add_argument("--text", default="https://accounts.bromigos.org/device?user_code=KPGGZFVT#machine=k1.3f2a9c0d&n=fieldkit")
    a = ap.parse_args(argv)
    if a.cmd == "png":
        s = save(a.text, a.out, style=a.style, world=a.world, size=a.size)
        print(f"{a.out}: {s}")
        return 0
    if a.cmd == "show":
        if images_supported():
            img, _ = render(a.text, style=a.style, world=a.world, size=480)
            buf = io.BytesIO()
            img.save(buf, "PNG")
            sys.stdout.write(kitty(buf.getvalue()) + "\n")
        else:
            print("\n".join(terminal(a.text, a.world)))
        return 0
    if a.cmd == "gallery":
        r = gallery(a.out, a.text)
        return 0 if all(c["ok"] for c in r["codes"]) else 1
    ap.print_help()
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
