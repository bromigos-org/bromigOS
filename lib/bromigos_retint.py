"""The den's painted plate in a colour theme's colours: a gradient map in OKLab.

The den (and its lock-screen twin) is painted in the Wick's phosphor green. A colour theme
recolours everything else from palette.json; this does the plate. Each pixel keeps its
OKLab lightness exactly (so every detail and all the contrast stay) and takes its hue and
chroma from a ramp built from the theme's colours, at that lightness:

    shadows -> background,  mids -> dim (the dimmed primary),  highlights -> primary,  top -> soft

The pixel's own chroma is kept relative to the Wick's ramp at the same lightness (a more
saturated light stays more saturated), and a pixel whose hue is far from the plate's green
(a genuine accent) keeps its colour. Colours outside sRGB lose chroma, never lightness.
Under the Wick nothing changes: the plate comes back as it is, bit for bit.

    import bromigos_retint as R
    out = R.retint(rgb_uint8, R.palette())          # (h, w, 3) uint8 in, the same out
    R.retint_file(src, dst, palette, darken=…)      # an image file (bromigos-wallpaper)

Used by the live layer (scene.py: the underlay, once per theme) and bromigos-wallpaper
(the wallpaper and the lock screen for a colour theme). Needs numpy (Pillow for files).
"""
import hashlib
import json

WICK = {"background": "#000500", "dim": "#159b09", "primary": "#39ff14", "soft": "#9cff8a"}
ROLES = ("background", "dim", "primary", "soft")
STOPS = (0.0, 0.35, 0.70, 0.92)            # the plate's OKLab lightness where each role sits
GREEN_HUE = 142.0                          # the plate's hue (OKLab degrees), measured
ACCENT = (35.0, 60.0)                      # hue distance (degrees) where a pixel starts to keep its colour
MAX_GAIN = 3.0                             # chroma may grow at most this much relative to the Wick's


def _hex(h):
    h = h.lstrip("#")
    return [int(h[i:i + 2], 16) / 255.0 for i in (0, 2, 4)]


def palette():
    """The theme in force: {"theme": name, role: "#rrggbb", …} (bromigos_theme)."""
    import bromigos_theme as T
    T.version(0.0)
    c = T.colors()
    return dict({r: c.get(r, WICK[r]) for r in ROLES}, theme=T.name())


def is_wick(pal):
    return (pal or {}).get("theme", "wick") == "wick" or all(
        (pal.get(r) or "").lower() == WICK[r] for r in ROLES)


def signature(pal):
    """A short key for a palette's ramp (caches)."""
    return hashlib.sha1(json.dumps([pal.get(r, WICK[r]).lower() for r in ROLES]).encode()).hexdigest()[:12]


# ---------------------------------------------------------------- OKLab (Björn Ottosson's)
def _np():
    import numpy as np
    return np


def to_linear(c):
    np = _np()
    return np.where(c <= 0.04045, c / 12.92, ((c + 0.055) / 1.055) ** 2.4)


def to_srgb(c):
    np = _np()
    c = np.clip(c, 0.0, 1.0)
    return np.where(c <= 0.0031308, c * 12.92, 1.055 * np.power(c, 1 / 2.4) - 0.055)


_M1 = [[0.4122214708, 0.5363325363, 0.0514459929], [0.2119034982, 0.6806995451, 0.1073969566],
       [0.0883024619, 0.2817188376, 0.6299787005]]
_M2 = [[0.2104542553, 0.7936177850, -0.0040720468], [1.9779984951, -2.4285922050, 0.4505937099],
       [0.0259040371, 0.7827717662, -0.8086757660]]
_M2I = [[1.0, 0.3963377774, 0.2158037573], [1.0, -0.1055613458, -0.0638541728],
        [1.0, -0.0894841775, -1.2914855480]]
_M1I = [[4.0767416621, -3.3077115913, 0.2309699292], [-1.2684380046, 2.6097574011, -0.3413193965],
        [-0.0041960863, -0.7034186147, 1.7076147010]]


def lin_to_oklab(lin):
    np = _np()
    lms = np.cbrt(lin @ np.asarray(_M1, np.float32).T)
    return lms @ np.asarray(_M2, np.float32).T


def oklab_to_lin(lab):
    np = _np()
    lms = (lab @ np.asarray(_M2I, np.float32).T) ** 3
    return lms @ np.asarray(_M1I, np.float32).T


def _ramp(pal):
    """The ramp's (a, b) at each stop: a role's hue and chroma (its lightness is the plate's)."""
    np = _np()
    cols = np.asarray([_hex(pal.get(r, WICK[r])) for r in ROLES], np.float32)
    return lin_to_oklab(to_linear(cols))[:, 1:]


def _at(ab, L):
    """(a, b) of a ramp at lightness L (linear between the stops, held past the ends)."""
    np = _np()
    return np.stack([np.interp(L, STOPS, ab[:, 0]), np.interp(L, STOPS, ab[:, 1])], axis=-1)


def retint(rgb, pal):
    """(h, w, 3) uint8 sRGB in the Wick's green -> the same in the palette's colours.
    Each distinct colour is mapped once (a painted plate has some tens of thousands)."""
    np = _np()
    rgb = np.asarray(rgb)
    if is_wick(pal):
        return rgb
    shape = rgb.shape
    flat = rgb.reshape(-1, 3)
    key = (flat[:, 0].astype(np.uint32) << 16) | (flat[:, 1].astype(np.uint32) << 8) | flat[:, 2]
    uniq, inv = np.unique(key, return_inverse=True)
    cols = np.stack([(uniq >> 16) & 255, (uniq >> 8) & 255, uniq & 255], axis=1).astype(np.uint8)
    return map_colours(cols, pal)[inv.ravel()].reshape(shape)


def map_colours(cols, pal):
    """(n, 3) uint8 colours -> the same in the palette's colours (the gradient map itself)."""
    np = _np()
    px = cols.astype(np.float32) / 255.0
    lab = lin_to_oklab(to_linear(px))
    L, ab = lab[:, 0], lab[:, 1:]
    C = np.hypot(ab[:, 0], ab[:, 1])
    w_ab, t_ab = _at(_ramp(WICK), L), _at(_ramp(pal), L)
    wc, tc = np.hypot(w_ab[:, 0], w_ab[:, 1]), np.hypot(t_ab[:, 0], t_ab[:, 1])
    gain = np.minimum(tc / np.maximum(wc, 0.02), MAX_GAIN)
    tdir = t_ab / np.maximum(tc, 1e-6)[:, None]
    new_ab = tdir * (C * gain)[:, None]
    # a genuine accent (far from the plate's green, and coloured) keeps its own colour
    hue = np.degrees(np.arctan2(ab[:, 1], ab[:, 0])) % 360.0
    dist = np.abs((hue - GREEN_HUE + 180.0) % 360.0 - 180.0)
    keep = np.clip((dist - ACCENT[0]) / (ACCENT[1] - ACCENT[0]), 0, 1) * np.clip((C - 0.02) / 0.03, 0, 1)
    new_ab = new_ab * (1 - keep)[:, None] + ab * keep[:, None]
    # into sRGB; a colour outside it gives up chroma (bisection), never lightness
    out = oklab_to_lin(np.concatenate([L[:, None], new_ab], axis=1))
    bad = (out.min(axis=1) < -1e-4) | (out.max(axis=1) > 1 + 1e-4)
    if bad.any():
        lo = np.zeros(bad.sum(), np.float32)
        hi = np.ones(bad.sum(), np.float32)
        Lb, ab_b = L[bad, None], new_ab[bad]
        for _ in range(12):
            mid = (lo + hi) / 2
            o = oklab_to_lin(np.concatenate([Lb, ab_b * mid[:, None]], axis=1))
            ok = (o.min(axis=1) >= -1e-4) & (o.max(axis=1) <= 1 + 1e-4)
            lo, hi = np.where(ok, mid, lo), np.where(ok, hi, mid)
        out[bad] = oklab_to_lin(np.concatenate([Lb, ab_b * lo[:, None]], axis=1))
    srgb = to_srgb(out)
    return np.clip(np.rint(srgb * 255.0), 0, 255).astype(np.uint8)


def retint_file(src, dst, pal, quality=92):
    """An image file in the Wick's green -> dst in the palette's colours (JPEG/PNG by name)."""
    np = _np()
    from PIL import Image
    im = Image.open(src).convert("RGB")
    out = Image.fromarray(retint(np.asarray(im), pal))
    kw = {"quality": quality} if dst.lower().endswith((".jpg", ".jpeg")) else {}
    out.save(dst, **kw)
    return dst


def main(argv):
    """bromigos_retint.py SRC DST [THEME_PALETTE_JSON]: recolour one image (default: the
    theme in force)."""
    import sys
    if len(argv) < 2:
        print(main.__doc__, file=sys.stderr)
        return 2
    pal = palette()
    if len(argv) > 2:
        with open(argv[2]) as f:
            d = json.load(f)
        c = d.get("colors") or d
        pal = dict({r: c.get(r, WICK[r]) for r in ROLES}, theme=d.get("theme", "custom"))
    retint_file(argv[0], argv[1], pal)
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main(sys.argv[1:]))
