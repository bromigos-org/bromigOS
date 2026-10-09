#!/usr/bin/env python3
"""Builds the Bromigos GTK3/GTK4 theme into linux/.local/share/themes/Bromigos.

Nothing is drawn by hand: the theme starts from the toolkit's own dark theme
(GTK3 Adwaita-dark, GTK4 Default-dark, both extracted from the installed
libraries with `gresource`), so every widget keeps its tested layout and
contrast. Each colour is then mapped into the Bromigos palette:

  greys     -> a void-to-phosphor ramp (backgrounds stay near-black green,
               text stays light so it reads as well as Adwaita does)
  borders   -> green rules (border/outline properties get their own ramp)
  blues     -> phosphor accent (selection, focus, suggested buttons, links)
  greens    -> phosphor (success)
  oranges   -> amber (warnings); reds keep their hue (errors, destructive)

A short hand-written layer (overrides.css) adds the house touches on top.
libadwaita apps ignore GTK themes, so libadwaita.css only re-defines its named
colours; it is imported from ~/.config/gtk-4.0/gtk.css.

Rebuild after a GTK update:  ./build-gtk-theme.py [--out DIR]
(bromigos-settings builds the Wick's into /usr/share/themes/Bromigos at package time)
Apply:                       gsettings set org.gnome.desktop.interface gtk-theme Bromigos

That is the Wick's theme, kept in the dotfiles. For another bromigOS theme,
`./build-gtk-theme.py --current` builds Bromigos-<theme> into ~/.themes
from the theme in force (bromigos_theme): the same ramps with each Wick colour
swapped for the theme's, the accent at its primary's hue, warnings at its warn's.
The theme-set hook (~/.config/bromigos/hooks/theme-set.d/gtk) runs it and switches
gtk-theme, which makes running GTK apps restyle.
"""
import colorsys
import os
import re
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.realpath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, "..", "..", ".."))           # linux/
THEME = os.path.join(ROOT, ".local", "share", "themes", "Bromigos")

SOURCES = {
    "gtk-3.0": ("/usr/lib/libgtk-3.so.0", "/org/gtk/libgtk/theme/Adwaita", "gtk-contained-dark.css"),
    "gtk-4.0": ("/usr/lib/libgtk-4.so.1", "/org/gtk/libgtk/theme/Default", "Default-dark.css"),
}


def hexrgb(h):
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) / 255 for i in (0, 2, 4))


# Grey lightness -> palette colour. Anchors were picked against Adwaita-dark's
# own greys: #1e1e1e text view, #2d2d2d views, #353535 window, #919190 dim
# text, #eeeeec text, white.
RAMP = [(0.00, "#000500"), (0.08, "#000800"), (0.12, "#000a00"), (0.176, "#000e00"),
        (0.208, "#001300"), (0.25, "#062006"), (0.30, "#0b2c0b"), (0.36, "#1f3d1f"),
        (0.45, "#4e6b4e"), (0.57, "#7e927e"), (0.80, "#a9d2a2"), (0.93, "#c4f5bb"),
        (1.00, "#e6f5e6")]
BORDER_RAMP = [(0.00, "#021a02"), (0.10, "#0a3a0a"), (0.20, "#0f4f0f"), (0.30, "#1a5f1a"),
               (0.45, "#4e6b4e"), (0.57, "#7e927e"), (1.00, "#c4f5bb")]
ACCENT_HUE = 108 / 360      # phosphor #39ff14
AMBER_HUE = 46 / 360        # amber #d4af37


RETINT = str          # the Wick's theme: every colour as written


def use_current_theme():
    """Rebind the palette to the theme in force; returns the theme's directory name."""
    global THEME, RAMP, BORDER_RAMP, ACCENT_HUE, AMBER_HUE, RETINT
    for lib in (os.path.join(HERE, "..", "lib"), "/usr/lib/bromigos/lib"):   # dotfiles, package
        sys.path.insert(0, lib)
    import bromigos_theme as T
    name = T.name()
    # ~/.themes, not ~/.local/share/themes: that one is the dotfiles' (public) folder
    THEME = os.path.join(os.path.expanduser("~"), ".themes", f"Bromigos-{name}")
    RAMP = [(x, T.retint_hex(c)) for x, c in RAMP]
    BORDER_RAMP = [(x, T.retint_hex(c)) for x, c in BORDER_RAMP]
    ACCENT_HUE = colorsys.rgb_to_hls(*T.rgb("primary"))[0]
    AMBER_HUE = colorsys.rgb_to_hls(*T.rgb("warn"))[0]
    RETINT = T.retint
    return os.path.basename(THEME)


def ramp(points, x):
    for (x0, c0), (x1, c1) in zip(points, points[1:]):
        if x <= x1:
            t = 0 if x1 == x0 else (x - x0) / (x1 - x0)
            a, b = hexrgb(c0), hexrgb(c1)
            return tuple(a[i] + (b[i] - a[i]) * t for i in range(3))
    return hexrgb(points[-1][1])


def remap(rgb, border=False):
    h, l, s = colorsys.rgb_to_hls(*rgb)
    if s < 0.15 or l < 0.03 or l > 0.97:
        return ramp(BORDER_RAMP if border else RAMP, l)
    deg = h * 360
    if 170 <= deg <= 270:           # blue: the accent
        # Green reads much brighter than blue at equal HSL lightness; scale it
        # down so white text on a selection keeps about 5:1 contrast.
        return colorsys.hls_to_rgb(ACCENT_HUE, l * 0.72, min(1.0, s))
    if 80 <= deg < 170:             # green: success
        return colorsys.hls_to_rgb(ACCENT_HUE, l * 0.85, s)
    if 20 <= deg < 80:              # orange/yellow: warning
        return colorsys.hls_to_rgb(AMBER_HUE, l, s * 0.85)
    return rgb                      # reds, purples: unchanged


def fmt(rgb, a=None):
    r, g, b = (max(0, min(255, round(v * 255))) for v in rgb)
    if a is None:
        return f"#{r:02x}{g:02x}{b:02x}"
    return f"rgba({r}, {g}, {b}, {a})"


COLOR = re.compile(r"#[0-9a-fA-F]{6}\b|#[0-9a-fA-F]{3}\b|rgba?\(\s*[\d.]+\s*,\s*[\d.]+\s*,\s*[\d.]+\s*(?:,\s*[\d.]+\s*)?\)|\b(?:white|black)\b")


def map_value(value, border):
    def sub(m):
        t = m.group(0)
        if t == "white":
            rgb, a = (1, 1, 1), None
        elif t == "black":
            rgb, a = (0, 0, 0), None
        elif t.startswith("#"):
            hx = t[1:]
            if len(hx) == 3:
                hx = "".join(c * 2 for c in hx)
            rgb, a = hexrgb(hx), None
        else:
            nums = [float(x) for x in re.findall(r"[\d.]+", t)]
            rgb, a = tuple(n / 255 for n in nums[:3]), (nums[3] if len(nums) > 3 else None)
        return fmt(remap(rgb, border), a)
    return COLOR.sub(sub, value)


DECL = re.compile(r"([\w-]+)(\s*:\s*)([^;{}]+);")
DEFINE = re.compile(r"(@define-color\s+)([\w-]+)(\s+)([^;]+);")


def transform(css):
    css = DEFINE.sub(lambda m: m.group(1) + m.group(2) + m.group(3)
                     + map_value(m.group(4), "border" in m.group(2)) + ";", css)
    return DECL.sub(lambda m: m.group(1) + m.group(2)
                    + map_value(m.group(3), m.group(1).startswith(("border", "outline"))) + ";", css)


def extract(lib, path):
    return subprocess.run(["gresource", "extract", lib, path], check=True,
                          capture_output=True).stdout


def build(ver):
    lib, base, name = SOURCES[ver]
    src = extract(lib, f"{base}/{name}").decode()
    out = os.path.join(THEME, ver)
    if os.path.isdir(out):
        shutil.rmtree(out)
    os.makedirs(os.path.join(out, "assets"))
    # Only the assets the stylesheet actually references.
    for asset in sorted(set(re.findall(r'url\("assets/([^"]+)"\)', src))):
        with open(os.path.join(out, "assets", asset), "wb") as f:
            f.write(extract(lib, f"{base}/assets/{asset}"))
    with open(os.path.join(HERE, "overrides.css")) as f:
        overrides = RETINT(f.read())
    css = ("/* Bromigos GTK theme: generated by ~/.config/bromigos/gtk/build-gtk-theme.py\n"
           f"   from {os.path.basename(lib)} {base}/{name}. Edit overrides.css, not this file. */\n\n"
           + transform(src) + "\n\n/* ---- overrides.css ---- */\n" + overrides)
    with open(os.path.join(out, "gtk.css"), "w") as f:
        f.write(css)
    with open(os.path.join(out, "gtk-dark.css"), "w") as f:
        f.write('@import url("gtk.css");\n')
    if ver == "gtk-4.0":
        with open(os.path.join(HERE, "libadwaita.css")) as f:
            adw = RETINT(f.read())
        with open(os.path.join(out, "libadwaita.css"), "w") as f:
            f.write(adw)


def main():
    global THEME
    if "--current" in sys.argv[1:]:
        use_current_theme()
    if "--out" in sys.argv[1:]:          # packaging: the Wick's theme into /usr/share/themes/Bromigos
        THEME = os.path.abspath(sys.argv[sys.argv.index("--out") + 1])
    os.makedirs(THEME, exist_ok=True)
    with open(os.path.join(THEME, "index.theme"), "w") as f:
        f.write("[Desktop Entry]\nType=X-GNOME-Metatheme\nName=" + os.path.basename(THEME) + "\n"
                "Comment=Phosphor on void, from the Bromigos palette\nEncoding=UTF-8\n\n"
                "[X-GNOME-Metatheme]\nGtkTheme=" + os.path.basename(THEME) + "\nIconTheme=Bromigos\nCursorTheme=Bromigos-cursor\n")
    for ver in SOURCES:
        build(ver)
    print(f"built {THEME}")


if __name__ == "__main__":
    main()
