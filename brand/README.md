# brand/

This folder holds the Bromigos brand as bromigOS uses it: the logos and the house
palette. They're source files for other work, not part of any package.

The brand isn't open source. The code in this repository is `MIT OR Apache-2.0`, but the
brand assets are all rights reserved. [docs/ASSETS.md](../docs/ASSETS.md) records where
each one comes from and whether it may ship.

## What's here

| File | What |
|---|---|
| `bromigos-logo.png` | The canonical Bromigos logo. Every variant below is traced from it. |
| `logos/bromigos-glyph.*`, `logos/bromigos-glyph-amber.*` | The glyph alone, in phosphor green and in amber. Each is an SVG plus 2048 and 512 px PNGs. |
| `logos/bromigos-lockup-horizontal.*`, `logos/bromigos-lockup-stacked.*` | The glyph with "BROMIGOS" set in Geist Mono Bold and "THE NETWORK" under it. Each also comes in `-amber`. |
| `logos/bromigos-favicon.*` | The glyph at favicon scale: an SVG, an ICO, and PNGs from 16 to 2048 px. The 180 px PNG is the Apple touch icon. |
| `palette.json`, `palette.css`, `kitty-colors.conf` | The house palette, which is the Wick theme's. |

## The house palette

| Name | Colour |
|---|---|
| phosphor | `#39ff14` |
| phosphor-soft | `#9cff8a` |
| phosphor-dim | `#159b09` |
| amber | `#d4af37` |
| danger | `#ff766f` |
| void | `#000500` |

These files are the reference. Running code reads the theme in force instead, from
`palette.json` in `~/.local/state/bromigos/theme/current/`. `bromigos theme set` writes
that file ([docs/theming.md](../docs/theming.md)).

## The emblem

The emblem, called the burn-in, isn't in this folder. Its canonical data is in
[`theme/emblem/`](../theme/README.md): `identity.json` and `flame.svg`. Each theme ships
its own emblem kit in `themes/<name>/emblem/`. `bromigos emblem build --theme DIR` draws
the kit from the canonical data and the theme's `emblem/emblem.toml`.

## What never goes here

Anyone's likeness or personal brand never goes in this repository. That includes
portraits, personal wordmarks, channel overlays and den wallpapers with a person in them.
A lab's or a personal plugin's own marks stay out too. All of these belong in their
owner's dotfiles.
