# Plugin folders

A plugin is a file you drop into a folder to add something to bromigOS: a deck, a shader
layer, a desktop panel (widget) or a Settings page. bromigOS's packaged code finds it
there, so you never edit files under `/usr/lib/bromigos`, and an update never overwrites
your plugin.

Plugins suit things that are yours alone, such as a deck for a system only you run. To
share one, make it an extension instead ([extensions.md](extensions.md)). The manual's
[Panels](../manual/src/panels.md) page covers the panels for users.

A *deck* is a full-screen holographic view, drawn by the *live layer*: the program behind
the animated background. The [glossary](../manual/src/glossary.md) has the other terms.

<!-- site:plugin-folders -->
## The folders

| Folder | What goes there |
|---|---|
| `~/.config/bromigos/plugins/live/` | Python modules that join the live layer's `live` package, such as module decks |
| `~/.config/bromigos/plugins/live/decks/` | Deck plugins: `<name>.py` files defining `DECK`, reloaded when they change |
| `~/.config/bromigos/plugins/live/layers/` | Shader layers: `<name>.frag` plus `<name>.json` |
| `~/.config/bromigos/plugins/widgets/` | Panels: `<name>.py` files defining a `panels.Panel` subclass |
| `~/.config/bromigos/plugins/settings/` | Settings pages: `<name>.py` files defining `PAGE` ([settings.md](settings.md)) |
| `~/.config/bromigos/plugins/homelab/` | Homelab adapters ([homelab.md](homelab.md)) |

VECTOR has a plugin folder of his own, `~/.config/bromigos/plugins/vector/`. His
repository's `docs/plugins.md` describes it.

## Which folder wins

The live layer, the panels and the homelab adapters search their folders in this order:

1. bromigOS's own files.
2. `bromigos-homelab`'s packaged folders, when it's installed.
3. Your plugin folder.
4. Installed extensions, in `~/.local/share/bromigos/ext/active/`.
5. The older homes, still read for now: `~/.config/bromigos-live/layers/`,
   `~/.config/bromigos-live/plugins/` for deck plugins, and
   `~/.config/bromigos/widgets/plugins/`.

When two folders have a file with the same name, the first one wins. So a plugin can add
a module but never replace one of bromigOS's.

Settings pages are the exception. There, a later page with the same id replaces an
earlier one, so you can replace a packaged page. [settings.md](settings.md) has the order.

To use different folders, set `$BROMIGOS_LIVE_PLUGINS` or `$BROMIGOS_WIDGET_PLUGINS` to a
colon-separated list. It replaces your plugin folder in the order above. The extensions'
folder is still read after it.

## Add a deck

There are two kinds of deck plugin.

**A deck plugin** is one file in `plugins/live/decks/`. It defines `DECK`, a class built
on the live layer's `live/deckkit.py`. It's reloaded whenever the file changes. If it
raises an error, the deck closes and the live layer carries on. Open it with:

```bash
bromigos-live plugin <name>
```

**A module deck** is a file named `<kind>_deck.py` in `plugins/live/`. It also defines
`DECK`. It sits on the same footing as bromigOS's own decks. Open it with either of:

```bash
bromigos-live deck <kind> [verb args]    # opens it, and passes a verb if you give one
bromigos-live <kind>                     # toggles it, like a key does
```

Module decks join the live layer's `live` package. When `live/__init__.py` is imported,
it adds each plugin folder to the package's search path. So
`~/.config/bromigos/plugins/live/foo.py` is imported as `live.foo`, and relative imports
such as `from . import deckkit, sources` work as if it were part of bromigOS. Put any
helper modules a deck needs, such as a data client, beside it.

If you name a deck that isn't installed, the live layer says so. For example: `no
'netmap' deck: it is a plugin, not installed`.

### Name your deck

Give the `DECK` class two attributes, or set them at module level:

```python
deck_label = "Trades"              # what the menu, the shortcuts panel and the Tab hint call it
deck_hint = "the trading floor"    # a few words shown after it in the menu
```

Without them, the label is the deck's `title` up to ` //`, or else "<Kind> deck". The
live layer reads these from the file without running it (`live/decks.py`).

### The Tab cycle

Tab closes a deck and opens the next one in a cycle. `bromigos-live decks` lists every
deck and the cycle (`--json` for scripts). The cycle is `[decks] cycle` in the live
layer's config. By default it's:

```toml
cycle = ["holodeck", "lab", "timeline", "mind", "ops", "swarm", "netmap"]
```

A deck that isn't installed is passed over. To add your own, put its kind in the list in
your `~/.config/bromigos-live/config.toml`.

## Add a shader layer

A shader layer draws over the finished background, behind every window. It's a pair of
files in `plugins/live/layers/`:

- `<name>.frag`, a GLSL 330 core fragment shader;
- `<name>.json`, which turns it on and sets its opacity, blend mode and GPU budget.

A layer draws only when its JSON says `"enabled": true`. The live layer measures each
layer's GPU time every frame. A layer that goes over its budget, or fails to compile, is
switched off until its files change. A broken layer never stops the background.

The shader gets real readings as uniforms: CPU, GPU, memory and video memory load, network
traffic, and the health of your homelab. The full contract is at the top of
`live/live/plugins.py`.

To try a layer headless, run this in a bromigOS checkout's `live/` folder. It compiles the
shader on the GPU and reports its GPU time.

```bash
python -m live.plugins test-layer <name or path.frag> out.png
```

## Add a panel

A panel plugin is one file in `plugins/widgets/`. It defines a `panels.Panel` subclass,
either as `PANEL = MyPanel` or as the first subclass in the file. It may also define
`LAYOUT`, with `width`, `height`, `x`, `y` and `visible`.

- **Placement.** Your `layout.json`'s `plugins` map places a panel by name. Without a
  position, the panel goes into free space, clear of the other panels and of VECTOR's
  console.
- **Reloading.** The panels rescan the plugin folders every 2 seconds. A new or changed
  file loads, and a removed one closes.
- **Isolation.** An error in a plugin shows in its own panel and never reaches the
  others. After 5 errors in a minute, or 5 slow draws in a row, the plugin is switched off
  until its file changes. Errors go to `~/.local/state/bromigos/widgets-plugins.log`.

To look at a panel without the desktop, render it offscreen:

```bash
bromigos-widgets render <name or path/to/plugin.py> out.png
```

### What the gallery shows

The [widget gallery](widgets.md#the-widget-gallery) and edit mode read a few class
attributes from your `Panel` subclass. All are optional.

| Attribute | What it is | Default |
|---|---|---|
| `title` | The name on its frame and its card | The panel's name |
| `description` | One line: what it shows | Empty |
| `category` | `system`, `network`, `homelab`, `media`, `notes` or `fun` | `system` |
| `reads` | What it reads, in a few words, such as `"your CPU"` | Empty |
| `min_size`, `max_size` | The smallest and largest (width, height) edit mode lets it take, in pixels | (240, 120) and (1600, 1400) |
| `available()` | A class method: `True`, or `(False, "why")` when it can't show anything here, such as `(False, "no media source configured")`. The gallery then doesn't offer it, and greys it out with the reason while it's on the desktop. Keep it cheap: no network. | `True` |
| `settings` | Its own settings, as a list of fields: Settings draws the form, and `self.setting(key)` reads the values ([A widget's settings](widgets.md#a-widgets-settings)) | None |
| `sizes`, `default_size` | Its [size classes](widgets.md#size-classes), each with a layout of its own, and the one it starts in | One class, `standard`, from `min_size` to `max_size` |

```python
class LoadPanel(Panel):
    name, title = "load_panel", "LOAD"
    description = "The load average over 1, 5 and 15 minutes"
    category, reads = "system", "the load average"
    min_size, max_size = (360, 120), (720, 240)
```

`draw(cr, w, h)` gets the size the user chose, so lay the panel out from `w` and `h`.
With `sizes`, `self.size_class(w, h)` says which layout to draw. The
gallery says who made a panel from where it came from: bromigOS, an extension's
`authors`, or you.

[widgets.md](widgets.md) lists the panels bromigOS ships, and
[widgets/README.md](../widgets/README.md) describes the code.

## Configuration files

| File | Packaged default | Yours |
|---|---|---|
| The live layer's config | `/usr/share/bromigos/live/config.toml` | `~/.config/bromigos-live/config.toml`, or `$BROMIGOS_LIVE_CONFIG` |
| Animation switches | none | `~/.config/bromigos/live/overrides.toml`, written by `bromigos anim` |
| The panels' layout | `/usr/share/bromigos/widgets/layout.json` | `~/.config/bromigos/widgets/layout.json` |

The two files work differently:

- **The live layer's config** is merged key by key. Your file holds only what you
  change. The animation switches are merged over both.
- **The panels' layout** is replaced whole. To change it, copy the default and edit the
  copy.

## Shared Python libraries

`bromigos-core` installs shared Python libraries in `/usr/lib/bromigos/lib/`. They
include `bromigos_theme`, which reads the colours of the theme in force. The live layer
and the panels put that folder on the import path, so a plugin can import them too.
[lib/README.md](../lib/README.md) lists them.

## Example: a personal desk

Your dotfiles can carry pieces that are yours alone, versioned with the rest:

- a deck for a system of your own, with its data client beside it, as live-layer modules
  (`mything_deck.py` and `mything.py`);
- a game server's panel as a panel plugin (`game_servers.py`).

bromigOS ships none of them, and an update never touches them. A homelab no longer needs
plugins like these. The Netmap, Ops and Mind decks, the LAB panel and Gnosis memory now
come with `bromigos-homelab`, set up in `homelab.toml` ([homelab.md](homelab.md)).

To share a plugin, make it an extension. `bromigos ext new <kind> <name>` gives you a
working starter ([extensions.md](extensions.md)).

## bromigos-homelab's folders

`bromigos-homelab` plugs into the same places from its own packaged folders. They're
searched after bromigOS's and before yours:

| Folder | What's there |
|---|---|
| `/usr/lib/bromigos/homelab/live` | The Ops, Netmap and Mind decks |
| `/usr/lib/bromigos/homelab/widgets` | The LAB panel, and the panels you declare in `homelab.toml` |
| `/usr/lib/bromigos/homelab/vector` | VECTOR's homelab tools and the Gnosis memory store |

Declared panels come from a *panel generator*. That's a panel plugin file named
`<x>_panels.py` that offers several panels at once. It defines two functions:

- `names()` returns `{name: version}` for the panels it offers now;
- `panel(name)` returns `(Panel class, LAYOUT)` for one of them.

The panels come and go as its configuration changes.
