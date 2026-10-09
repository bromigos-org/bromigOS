# theme/: what every theme is rendered with

This folder holds the shared half of theming: the templates every theme fills in, the
bar's icons, the app launcher's icons, the canonical emblem and the hologram models all
worlds share. Each theme's own files, such as its colours and art, are in
[`../themes/<name>/`](../themes/). Everything here ships in the `bromigos-core` package.

How themes work, and what each template feeds, is in
[docs/theming.md](../docs/theming.md).

## What's here

| Folder | Installed to | What it holds |
|---|---|---|
| `templates/` | `/usr/share/bromigos/theme/templates/` | One template per app config. `bromigos theme set` renders them |
| `icons/` | `/usr/share/bromigos/theme/icons/` | The bar's icons, drawn in the Wick's colours |
| `app-icons/` | `/usr/share/icons/hicolor/<size>/apps/` | The app launcher's icons for bromigOS's own windows |
| `emblem/` | `/usr/share/bromigos/emblem/` | The canonical burn-in emblem |
| `holo/` | `/usr/share/bromigos/theme/holo/` | The hologram models every world shares ([holo/README.md](holo/README.md)) |
| `tools/` | Not installed, except `glow-loop.py` | Tools that draw the icons and prepare world art |

### Templates

Each `templates/*.tpl` file is a [minijinja](https://github.com/mitsuhiko/minijinja)
template for one app's config, such as the bar, the terminal or the lock screen.
`bromigos theme set` renders every template with the theme's colours into
`~/.local/state/bromigos/theme/current/`, then tells the running apps to reload.

A user can replace any template by putting a file of the same name in
`~/.config/bromigos/theme/templates/`.

### Icons

`icons/` holds the bar's icons. Each comes in four states: plain, `-dim`, `-amber` and
`-danger`. They're drawn in the Wick's colours, and recoloured for every other theme. A
theme can bring its own icons instead ([docs/theming.md](../docs/theming.md)).

`tools/build-icons.py` draws most of them in code, in all four states. Run it again after
you edit a shape. The battery and power-profile icons are hand-drawn SVGs.

### App icons

`app-icons/` holds an icon for each bromigOS window in the app launcher, named
`bromigos-<name>`. Each is a glyph inside the burn-in's ring, at 16, 24 and 32 pixels and
as a scalable SVG. They go into the hicolor icon theme, which every icon theme inherits.
[docs/menu.md](../docs/menu.md) explains the launcher's entries.

`tools/build-app-icons.py` draws every size of every icon:

```bash
python3 theme/tools/build-app-icons.py              # draw them all
python3 theme/tools/build-app-icons.py --check      # are the committed icons current?
python3 theme/tools/build-app-icons.py --sheet out.png   # a contact sheet to review
```

VECTOR's two icons live in the vector repository. `--vector DIR` draws them there.

### The emblem

`emblem/` holds the canonical burn-in: `identity.json` and `flame.svg`. The burn-in is
the Bromigos emblem, a flame inside a ring of text. Every theme's emblem kit is drawn
from these two files by `bromigos emblem build`. Never draw an emblem by hand.

### Tools

| Tool | What it does |
|---|---|
| `build-icons.py` | Draws the bar's icons, in all four states |
| `build-app-icons.py` | Draws `app-icons/` |
| `placeholder-worlds.py` | Draws stand-in art and sounds for a world before its real art exists |
| `glow-loop.py` | Prepares a glowing creature's video loop. Installed, because `bromigos art make video.loop --alpha` runs it |
| `plate-patch.py` | Writes a masked edit of a world's composite back into its layers |
| `craft-sprites.py` | Cuts, re-mattes and sizes the craft that fly over the worlds |

The world-art tools are part of the art pipeline. [docs/art.md](../docs/art.md)
explains it.

## Try a change

To render this checkout's themes and templates on your own desktop:

```bash
BROMIGOS_SHARE_DIR=$PWD bromigos theme set
```

Run it from the repository's root. Your running apps reload with the result.

To render without touching your desktop, use a throwaway home and `--no-reload`:

```bash
HOME=$(mktemp -d) BROMIGOS_SHARE_DIR=$PWD bromigos theme set mire --no-reload
```

The result is in that home's `.local/state/bromigos/theme/current/`. `--no-reload` also
skips the theme-set hooks. If your session sets `XDG_CONFIG_HOME` or `XDG_STATE_HOME`,
unset them for this command, or they'll point back at your real files.
