#!/usr/bin/env python3
"""Bromigos HUD icon set: 16x16, 1px strokes on the pixel grid (coordinates on .5
so lines land on whole pixels), square caps, no fills except tiny indicator dots.

Concepts came from a nolgia recraft-v4.1 sheet (chip, cylinder, antenna, speaker,
clock ...); the geometry is redrawn here by hand so it stays crisp at bar size.

Writes <name>.svg (phosphor), <name>-amber.svg, <name>-danger.svg and <name>-dim.svg
next to this script. Run it again after editing a shape.
"""
import os

HERE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "icons")   # theme/icons
COLORS = {"": "#39ff14", "-amber": "#d4af37", "-danger": "#ff766f", "-dim": "#159b09"}

ICONS = {
    # CPU: chip with three pins per side and a core
    "cpu": """
      <rect x="3.5" y="3.5" width="9" height="9"/>
      <rect x="6.5" y="6.5" width="3" height="3"/>
      <path d="M5.5 1.5v1M7.5 1.5v1M10.5 1.5v1M5.5 13.5v1M7.5 13.5v1M10.5 13.5v1
               M1.5 5.5h1M1.5 7.5h1M1.5 10.5h1M13.5 5.5h1M13.5 7.5h1M13.5 10.5h1"/>""",
    # RAM: a module with three packages and edge contacts
    "ram": """
      <rect x="0.5" y="4.5" width="15" height="6"/>
      <path d="M3.5 6.5h2v2h-2zM7 6.5h2v2h-2zM10.5 6.5h2v2h-2z"/>
      <path d="M2.5 10.5v2M4.5 10.5v2M6.5 10.5v2M9.5 10.5v2M11.5 10.5v2M13.5 10.5v2"/>""",
    # GPU: card with a fan and its bracket
    "gpu": """
      <path d="M1.5 2.5v12"/>
      <rect x="1.5" y="3.5" width="13" height="8"/>
      <circle cx="10" cy="7.5" r="2.5"/>
      <path d="M4.5 5.5v4M6.5 5.5v4M4.5 11.5v2h6v-2"/>""",
    # temperature: thermometer with scale ticks
    "temp": """
      <path d="M5.5 9.5v-7a1.5 1.5 0 0 1 3 0v7"/>
      <circle cx="7" cy="12" r="2.5"/>
      <path d="M10.5 3.5h2M10.5 5.5h2M10.5 7.5h2"/>
      <path d="M7 6.5v3" stroke-width="1"/>""",
    # storage: a stacked cylinder (a volume)
    "disk": """
      <ellipse cx="8" cy="3.5" rx="6.5" ry="2"/>
      <path d="M1.5 3.5v9c0 1.1 2.9 2 6.5 2s6.5-.9 6.5-2v-9"/>
      <path d="M1.5 8c0 1.1 2.9 2 6.5 2s6.5-.9 6.5-2"/>""",
    # network: mast with two arcs
    "net": """
      <path d="M7.5 7.5v7M4.5 14.5h6M5.5 14.5l2-7 2 7"/>
      <path d="M4.7 5.2a4 4 0 0 1 5.6 0M2.6 3.1a7 7 0 0 1 9.8 0"/>
      <rect x="7" y="6" width="1" height="1" fill="currentColor" stroke="none"/>""",
    # volume: speaker with two waves
    "vol": """
      <path d="M1.5 5.5h3l4-3v11l-4-3h-3z"/>
      <path d="M10.5 5.5a3 3 0 0 1 0 5M12.5 3.5a6 6 0 0 1 0 9"/>""",
    # volume muted: speaker with a cross
    "vol-muted": """
      <path d="M1.5 5.5h3l4-3v11l-4-3h-3z"/>
      <path d="M10.5 5.5l5 5M15.5 5.5l-5 5"/>""",
    # VECTOR: the construct's iris: a twelve-sided bezel, a six-blade aperture, the core
    "vector": """
      <path d="M8 0.5l3.75 1 2.75 2.75 1 3.75-1 3.75-2.75 2.75-3.75 1-3.75-1-2.75-2.75-1-3.75 1-3.75 2.75-2.75z"/>
      <path d="M8 3.5l3.9 2.25v4.5l-3.9 2.25-3.9-2.25v-4.5z"/>
      <rect x="7" y="7" width="2" height="2" fill="currentColor" stroke="none"/>""",
    # media: a reel-to-reel cassette
    "tape": """
      <rect x="0.5" y="2.5" width="15" height="11"/>
      <circle cx="5" cy="7" r="1.5"/>
      <circle cx="11" cy="7" r="1.5"/>
      <path d="M6.5 7h3M3.5 13.5l1.5-2.5h6l1.5 2.5"/>""",
    # clock: dial with ticks at 12/3/6/9 and hands
    "clock": """
      <circle cx="7.5" cy="7.5" r="6"/>
      <path d="M7.5 1.5v1M14.5 7.5h-1M7.5 14.5v-1M1.5 7.5h1"/>
      <path d="M7.5 4.5v3h3"/>""",
    # idle: an open eye (the screensaver keeps watch; nothing locks)
    "eye": """
      <path d="M0.5 8c2-3.5 4.5-5 7.5-5s5.5 1.5 7.5 5c-2 3.5-4.5 5-7.5 5s-5.5-1.5-7.5-5z"/>
      <circle cx="8" cy="8" r="2.5"/>
      <rect x="7.5" y="7.5" width="1" height="1" fill="currentColor" stroke="none"/>""",
    # stay awake: a cup with steam
    "cup": """
      <path d="M2.5 6.5h9v4a3 3 0 0 1-3 3h-3a3 3 0 0 1-3-3z"/>
      <path d="M11.5 7.5h1a2 2 0 0 1 0 4h-1"/>
      <path d="M5.5 1.5v2M8.5 1.5v2M1.5 15.5h11"/>""",
    # settings: a gear (a ring, its hub and eight teeth)
    "gear": """
      <circle cx="8" cy="8" r="4.5"/>
      <circle cx="8" cy="8" r="1.5"/>
      <path d="M8 0.5v3M8 12.5v3M0.5 8h3M12.5 8h3M2.7 2.7l2.1 2.1M11.2 11.2l2.1 2.1M2.7 13.3l2.1-2.1M11.2 4.8l2.1-2.1"/>""",
    # Bluetooth: the rune (the bar's module)
    "bt": """
      <path d="M4.5 4.5l7 7-3.5 3.5v-14l3.5 3.5-7 7"/>""",
    # the kinds of Bluetooth device (the toasts and the panel's fallbacks): a game controller
    "bt-pad": """
      <path d="M4.5 4.5h7l2 1.5 1.5 6-1 1.5h-1.5l-2.5-3h-4l-2.5 3h-1.5l-1-1.5 1.5-6z"/>
      <path d="M4.5 7.5v2M3.5 8.5h2"/>
      <rect x="10" y="7" width="1" height="1" fill="currentColor" stroke="none"/>
      <rect x="12" y="8" width="1" height="1" fill="currentColor" stroke="none"/>""",
    # headphones: the band and two cups
    "bt-headset": """
      <path d="M2.5 9.5v-2a5.5 5.5 0 0 1 11 0v2"/>
      <rect x="1.5" y="9.5" width="3" height="5"/>
      <rect x="11.5" y="9.5" width="3" height="5"/>""",
    # earbuds: two buds with stems
    "bt-buds": """
      <circle cx="4.5" cy="5.5" r="2.5"/><circle cx="11.5" cy="5.5" r="2.5"/>
      <path d="M3.5 8.5v5h2v-5M10.5 8.5v5h2v-5"/>""",
    # a speaker: the box, a woofer and a tweeter
    "bt-speaker": """
      <rect x="3.5" y="0.5" width="9" height="15"/>
      <circle cx="8" cy="10" r="3"/>
      <circle cx="8" cy="4" r="1.5"/>""",
    # a keyboard
    "bt-kbd": """
      <rect x="0.5" y="3.5" width="15" height="9"/>
      <path d="M2.5 5.5h1M5.5 5.5h1M8.5 5.5h1M11.5 5.5h2M2.5 7.5h2M6.5 7.5h1M9.5 7.5h1M12.5 7.5h1M4.5 10.5h7"/>""",
    # a mouse
    "bt-mouse": """
      <rect x="3.5" y="1.5" width="9" height="13" rx="4.5"/>
      <path d="M8 1.5v5M3.5 6.5h9"/>""",
    # a phone
    "bt-phone": """
      <rect x="3.5" y="0.5" width="9" height="15" rx="1.5"/>
      <path d="M6.5 2.5h3M3.5 12.5h9"/>""",
    # any other device: the rune in a frame
    "bt-dev": """
      <rect x="0.5" y="0.5" width="15" height="15"/>
      <path d="M5.5 5.5l5 5-2.5 2.5v-10l2.5 2.5-5 5"/>""",
}

# The battery sliver under the bar's Bluetooth glyph: 16×3, five cells, N lit (btcell-N).
SLIVER = {f"btcell-{n}": "".join(
    f'<rect x="{1 + i * 3}" y="0" width="2" height="3" fill="currentColor" stroke="none"'
    + ("" if i < n else ' fill-opacity="0.28"') + "/>" for i in range(5)) for n in range(6)}


def svg(body, color, w=16, h=16):
    return (f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" viewBox="0 0 {w} {h}" '
            f'fill="none" stroke="{color}" stroke-width="1" stroke-linecap="square" '
            f'stroke-linejoin="miter" color="{color}">{body.strip()}</svg>\n')


if __name__ == "__main__":
    for name, body in ICONS.items():
        for suffix, color in COLORS.items():
            with open(os.path.join(HERE, f"{name}{suffix}.svg"), "w") as f:
                f.write(svg(body, color))
    for name, body in SLIVER.items():
        for suffix, color in COLORS.items():
            with open(os.path.join(HERE, f"{name}{suffix}.svg"), "w") as f:
                f.write(svg(body, color, 16, 3))
    print(f"{len(ICONS) + len(SLIVER)} icons x {len(COLORS)} colours -> {HERE}")
