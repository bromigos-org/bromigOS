"""The theme's colours at runtime, for the apps that draw their own: the widgets,
VECTOR, the live layer's decks and the waybar scripts.

`bromigos theme set NAME` (bromigOS's core) writes the theme with every colour
resolved to ~/.local/state/bromigos/theme/current/palette.json; this reads it, and
reads it again when it changes (a theme switch swaps the whole directory, so the
file's inode and mtime change). With no file (no bromigos-core, or no theme ever
set) the colours are the Wick's, exactly as these apps hard-coded them before.

    import bromigos_theme as T
    T.hex("primary")            # '#39ff14' (a role, a [colors] name, "widgets.frame")
    T.hex("phosphor")           # the Wick's old names work too: phosphor -> primary
    T.rgb("dim")                # (r, g, b) floats 0..1
    T.retint(css)               # every Wick colour in a string -> the theme's
    v = T.version()             # cheap (stats the file at most once a second); it goes
    if v != seen: seen = v; …   # up when the theme changes: re-read colours, redraw
    T.high_contrast()           # the user's high contrast is on (docs/accessibility.md):
                                # the colours already are; draw panels opaque, no glow
    T.motion()                  # "full", "reduced" or "still": animate accordingly

The old names: void, panel, guard (selection), phosphor (primary), soft, dim, amber
(warn), danger, rust, static (muted), cyan, gold, white, text, faint.
"""
import colorsys
import json
import os
import re
import time

_STATE = os.environ.get("XDG_STATE_HOME") or os.path.join(os.path.expanduser("~"), ".local", "state")
PATH = os.path.join(_STATE, "bromigos", "theme", "current", "palette.json")

# The Wick (bromigOS themes/wick/colors.toml), resolved: the fallback, and the
# colours retint() looks for in hard-coded strings.
WICK = {
    "background": "#000500", "void": "#000500", "panel": "#001300", "selection": "#003b00",
    "primary": "#39ff14", "soft": "#9cff8a", "dim": "#159b09", "text": "#c4f5bb",
    "muted": "#7e927e", "faint": "#4e6b4e",
    "warn": "#d4af37", "danger": "#ff766f", "warn_surface": "#4a3a0a",
    "danger_surface": "#1a0503", "danger_text": "#ffd9d6",
    "cyan": "#3fe0c5", "gold": "#f0d36a", "white": "#e8ffe0", "rust": "#4a0e0e",
}
WICK_TABLES = {
    "holo": {"line": "#39ff14", "glow": "#39ff14", "label": "#c4f5bb", "highlight": "#e8ffe0"},
    "widgets": {"frame": "#159b09", "header": "#39ff14", "value": "#9cff8a",
                "graph": "#39ff14", "track": "#003b00"},
    "terminal": {"color4": "#5aa9e6", "color5": "#c97bdb", "color7": "#b4c8b4",
                 "color9": "#ff9d97", "color12": "#8ccaf5", "color13": "#e3a8ef",
                 "color14": "#8af5e2", "color15": "#e6f5e6"},
}
LEGACY = {"guard": "selection", "phosphor": "primary", "amber": "warn", "static": "muted"}

_doc = {"theme": "wick", "name": "Wick", "mode": "dark", "colors": dict(WICK), "tables": WICK_TABLES}
_sig = None          # (inode, mtime_ns) of the file last read; None = never read
_checked = 0.0
_version = 0
_retint_map = {}


def _hexrgb(h):
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) / 255 for i in (0, 2, 4))


def _fmt(rgb):
    return "#" + "".join(f"{max(0, min(255, round(v * 255))):02x}" for v in rgb)


def _stat():
    try:
        st = os.stat(PATH)
        return (st.st_ino, st.st_mtime_ns)
    except OSError:
        return ("none",)


def _load():
    global _doc, _sig, _retint_map
    sig = _stat()
    doc = None
    if sig != ("none",):
        try:
            with open(PATH) as f:
                doc = json.load(f)
            if not isinstance(doc.get("colors"), dict):
                doc = None
        except (OSError, ValueError):
            doc = None
    if doc is None:
        doc = {"theme": "wick", "name": "Wick", "mode": "dark", "colors": {}, "tables": {}}
    colors = dict(WICK)
    colors.update(doc.get("colors") or {})
    tables = {t: dict(m) for t, m in WICK_TABLES.items()}
    for t, m in (doc.get("tables") or {}).items():
        tables.setdefault(t, {}).update(m)
    doc["colors"], doc["tables"] = colors, tables
    global _version
    _doc, _sig = doc, sig
    _retint_map = _build_retint()
    _version += 1


def _ensure():
    if _sig is None:
        _load()


def version(every=1.0):
    """A number that goes up each time the theme's colours change (they are loaded by
    then). Stats palette.json at most once per `every` seconds; each caller keeps the
    number it last saw, so any number of readers in one process can follow it."""
    global _checked
    now = time.monotonic()
    if _sig is None:
        _load()
        _checked = now
    elif now - _checked >= every:
        _checked = now
        if _stat() != _sig:
            _load()
    return _version


def name():
    _ensure()
    return _doc.get("theme", "wick")


def is_wick():
    return name() == "wick"


def hex(n):  # noqa: A001  (the colour's hex, not the builtin)
    """A role, [colors] name, legacy Wick name, "table.key", or a literal #rrggbb."""
    _ensure()
    if n.startswith("#"):
        return retint(n)
    if "." in n:
        t, k = n.split(".", 1)
        v = _doc["tables"].get(t, {}).get(k)
        if v:
            return v
        raise KeyError(n)
    n = LEGACY.get(n, n)
    return _doc["colors"][n]


def rgb(n):
    return _hexrgb(hex(n))


def rgb255(n):
    return tuple(round(v * 255) for v in rgb(n))


def table(t):
    _ensure()
    return dict(_doc["tables"].get(t, {}))


def colors():
    _ensure()
    return dict(_doc["colors"])


# ----------------------------------------------------------------- accessibility
# `bromigos accessibility` (docs/accessibility.md): palette.json says how it was rendered.

def high_contrast():
    """True when the colours were rendered high-contrast: draw panels opaque, rules solid,
    no glow behind text."""
    _ensure()
    c = _doc.get("contrast")
    return isinstance(c, dict) and c.get("mode") == "high"


def motion():
    """The user's motion setting: "full", "reduced" (calm: no blinking, pulsing or sweeping)
    or "still" (hold still)."""
    _ensure()
    m = _doc.get("motion")
    return m if m in ("full", "reduced", "still") else "full"


# ----------------------------------------------------------------- retint
# Hard-coded strings (GTK CSS, Pango markup, shader constants) were written in the
# Wick's colours. retint() swaps each Wick role colour for the theme's; other greens
# (hand-mixed shades of phosphor) turn to the theme's primary hue at their own
# lightness, so the shades stay shades. Everything is identity under the Wick.

def _build_retint():
    if _doc.get("theme", "wick") == "wick" and not high_contrast():
        return {}
    m = {}
    for k, v in WICK.items():
        m.setdefault(v.lower(), _doc["colors"].get(k, v).lower())
    for t, kv in WICK_TABLES.items():
        for k, v in kv.items():
            m.setdefault(v.lower(), _doc["tables"].get(t, {}).get(k, v).lower())
    return m


def _shift(rgb_):
    """A non-role Wick shade -> the theme: greens follow primary's hue and saturation."""
    h, l, s = colorsys.rgb_to_hls(*rgb_)
    deg = h * 360
    if s < 0.08 or not (70 <= deg <= 170):
        return rgb_
    # near-black greens are surfaces: place them on the theme's background -> panel ->
    # selection ramp at the same point they sit on the Wick's
    ramp = [(colorsys.rgb_to_hls(*_hexrgb(WICK[k]))[1], k) for k in ("background", "panel", "selection")]
    if l <= ramp[-1][0]:
        for (l0, k0), (l1, k1) in zip(ramp, ramp[1:]):
            if l <= l1:
                t = max(0.0, (l - l0) / (l1 - l0))
                a, b = _hexrgb(_doc["colors"][k0]), _hexrgb(_doc["colors"][k1])
                return tuple(a[i] + (b[i] - a[i]) * t for i in range(3))
    ph, pl, ps = colorsys.rgb_to_hls(*_hexrgb(_doc["colors"]["primary"]))
    wh, wl, ws = colorsys.rgb_to_hls(*_hexrgb(WICK["primary"]))
    return colorsys.hls_to_rgb(ph, min(1.0, l * (pl / wl) if wl else l), min(1.0, s * (ps / ws) if ws else s))


_HEX = re.compile(r"#[0-9a-fA-F]{6}\b")


def retint_hex(h):
    _ensure()
    if not _retint_map:
        return h
    low = h.lower()
    if low in _retint_map:
        return _retint_map[low]
    return _fmt(_shift(_hexrgb(low)))


def retint(text):
    """Every #rrggbb in `text` mapped from the Wick to the current theme."""
    _ensure()
    if not _retint_map:
        return text
    return _HEX.sub(lambda m: retint_hex(m.group(0)), text)


def retint_rgb(rgb_):
    """A Wick colour as floats (0..1) -> the theme's, as floats. Alpha passes through."""
    _ensure()
    if not _retint_map:
        return tuple(rgb_)
    tail = tuple(rgb_[3:])
    return _hexrgb(retint_hex(_fmt(rgb_[:3]))) + tail
