# Themes

A theme sets the look of the whole desktop at once. It colours every app, and it brings
the bar's icons, the emblem, the wallpaper and the lock screen's background. A *world*
goes further: its wallpaper is a living scene that moves with your machine. A theme is a
folder of data files, and `bromigos theme set <name>` renders them into each app's
config.

This page is for people making or changing themes. To use them, read the manual's
[Themes and worlds](../manual/src/themes-and-worlds.md) page. What each world shows, and
the designs for future ones, are in [worlds.md](worlds.md). The
[glossary](../manual/src/glossary.md) defines bromigOS's terms.

![The Customize window on its Themes tab: a grid of all eleven themes' previews, each the
whole desktop with a terminal and the panels in that theme, with Mire chosen](images/theme-switcher.webp)

## The themes bromigOS ships

There are three kinds of theme:

- **The den.** The Wick is the default theme. Its wallpaper is *the den*, a painted radio
  room whose screens, rain of glyphs and floor are drawn live.
- **Worlds.** A world has its own painted scene, with creatures and a keeper that react to
  real readings. The *live layer* draws it. That's the program that draws the animated
  background and the decks.
- **Colour themes.** A colour theme changes the colours only. The den stays behind it,
  recoloured in the theme's colours. Two of them, Wick · Tidewell and Wick · Mire, give
  the den the two worlds' colours.

| Theme | Kind | Look |
|---|---|---|
| `wick` | the den | Phosphor green on black. The default. |
| `mire` | world | A night bayou: black mirror water, moss and fireflies. |
| `tidewell` | world | The sea at night, split at the waterline. |
| `rime` | colour | Ice blue on a blizzard night. |
| `sunder` | colour | Sun-gold on scorched hull plate. |
| `cinder` | colour | Ember orange on soot. |
| `lowtown` | colour | Neon on wet asphalt. |
| `highwind` | colour | Kite-lantern gold on a dusk sky. |
| `deepvein` | colour | Amethyst on cavern black. |
| `wick-tidewell` | colour | The den in Tidewell's colours: cyan on deep water. |
| `wick-mire` | colour | The den in Mire's colours: firefly green and moss on black water. |

`bromigos theme list` shows every theme installed, with its source: `system` (shipped
with bromigOS), `ext` (an installed extension) or `user` (your own folder).

In the Bromigos stories, each theme is a post somewhere in the Drift, and the Wick is the
relay station where bromigOS runs. The colour themes are the posts whose scenes aren't
painted yet.

## Switch, install and remove themes

```bash
bromigos theme                                    # list the themes; * marks the current one
bromigos theme set mire                           # switch: every app recolours within a second
bromigos theme set                                # render the current theme again
bromigos theme install https://github.com/someone/deep-sea   # install one from Git
bromigos theme install https://github.com/someone/deep-sea@v1.2
bromigos ext update deep-sea                      # update it (shows the changes first)
bromigos theme remove deep-sea
```

**Super+Ctrl+Shift+Space** opens the theme switcher. It's described
[below](#the-theme-switcher).

`bromigos theme install` is the same as `bromigos ext install`. It keeps the theme as a
Git checkout, pinned to the commit you installed, so `bromigos ext update` can update it.
[extensions.md](extensions.md) has the details. A few rules apply to themes:

- A theme is data, so it installs without a question. A theme that also ships a hook
  runs code, so it asks first.
- A repository with a `bromigos-ext.toml` names itself. A plain theme repository is named
  after the repository. The name is lowercased, without `.git` or a `bromigos-theme-`
  prefix. `--name` sets a different one.
- You can't install a theme with the same name as a shipped one. To change a shipped
  theme, overlay it instead ([below](#change-one-colour-of-a-theme)).
- If you have a theme of your own with the same name, the install stops. `--force` moves
  yours aside to `~/.local/state/bromigos/ext/adopted/` and installs the new one.
- A symlink that points outside the repository stops the install. So does anything that
  isn't a file or a folder. The result must load as a theme, or nothing is kept.

`bromigos theme remove` removes an extension's theme or one of yours. It never removes a
shipped theme or the theme in force.

The menu has the same actions: INSTALL › Theme from a git URL… and REMOVE › Theme.

## Make a colour theme

1. Start from an existing theme. This makes a folder `./my-theme` with a manifest
   (`bromigos-ext.toml`), `colors.toml` and `theme.toml`:

   ```bash
   bromigos theme new my-theme --from wick
   ```

   Leave out `--from` to start from the starter, a teal theme.
2. Edit `colors.toml` and `theme.toml`. The formats are [below](#the-theme-folder).
3. Install your copy and switch to it:

   ```bash
   bromigos ext install --copy ./my-theme
   bromigos theme set my-theme
   ```

   `--copy` installs the folder as it is, uncommitted changes included. After the next
   edit, run `bromigos ext update my-theme`.
4. Check its contrast against bromigOS's high-contrast targets:

   ```bash
   bromigos accessibility check my-theme
   ```

5. To share it, push the folder to a Git repository. Others install it with
   `bromigos theme install <url>`.

`bromigos theme new` also draws the theme's preview for the switcher in the background, so
it's ready when you install it.

### Change one colour of a theme

You don't need a whole theme to change a colour. Make a folder with the theme's name in
`~/.config/bromigos/themes/`, and put only what you want to change in it:

```toml
# ~/.config/bromigos/themes/wick/colors.toml
primary = "#5cff3a"
```

Then run `bromigos theme set wick`. Your file is merged over the shipped one.

## Where themes live

| Path | What it holds |
|---|---|
| `/usr/share/bromigos/themes/<name>/` | The shipped themes (`themes/` in this repository; package `bromigos-core`) |
| `/usr/share/bromigos/theme/templates/*.tpl` | The shipped templates (`theme/templates/`) |
| `~/.local/share/bromigos/ext/active/themes/<name>` | Installed extensions' themes, as links into their checkouts |
| `~/.config/bromigos/themes/<name>/` | Your own themes, and your overlays of the others |
| `~/.config/bromigos/theme/templates/*.tpl` | Your own templates |
| `~/.local/state/bromigos/theme/current/` | The rendered theme that every app reads |

`$BROMIGOS_SHARE_DIR` replaces `/usr/share/bromigos`. Point it at a checkout of this
repository to use the repository's themes and templates.

### How folders with the same name combine

A theme's name can have up to three folders: the shipped one, an extension's and yours.
They combine in that order, and the later one wins. (A shipped theme and an extension
theme never share a name, because `bromigos ext` refuses that.)

- `colors.toml` and `theme.toml` merge table by table. So an overlay can change one
  colour and keep the rest.
- Any other file of yours replaces the file with the same path.
- A template of yours replaces the shipped template with the same file name.

A theme that exists only in your folder is a theme of its own.

## The theme folder

```text
themes/<name>/
  theme.toml        the name, description, dark or light, and where it sits in the lore
  colors.toml       the colour roles
  backgrounds/      a world's painted layers (layers/NN-name.webp)
  live/             a world's scene: world.toml, actors, loops, clips, sounds
  holo/             the world's hologram models
  icons/            bar icons of the theme's own (*.svg)
  emblem/           the theme's own emblem kit
  art.toml          how a world's art is made (art.md)
  art.log.jsonl     every job that made it
  art/              working sources for the art; not in Git or the package
  widgets/          layout.toml: the scene's keep-clear areas and the panels' layout made for it
  sounds/           reserved
  lock/             reserved
```

Only `colors.toml` is required.

Nothing reads the reserved folders yet. They hold a README that says what they're for.

`widgets/layout.toml` tells the desktop's panels where the scene's focal points are, so
layouts keep off them, and holds the panels' layout made for this scene.
[widgets.md](widgets.md#layouts) has the format. A theme without one draws the Wick's den
and uses the Wick's file.
`bromigos theme set` copies a theme's files into `current/`, except READMEs, `art.toml`,
`art.log.jsonl` and `art/`.

A world's `holo/` holds its hologram models, in VECTOR's format. VECTOR's hologram gallery
(**Super+O**) shows each world's models on a shelf of its own, in that world's colours.
VECTOR is the desktop's AI assistant.

### `theme.toml`

```toml
name = "Wick"                 # the display name; the folder name is the theme's id
description = "Phosphor green on void: the burn-in look of the Wick's console."
mode = "dark"                 # "dark" or "light"
canon = "Where the theme sits in the lore."
```

Every key is optional. `name` defaults to the folder name, and `mode` to `dark`.

A theme can also choose the static of the *intercept*. That's the animation the live
layer plays over the screen at login and unlock.

```toml
[intercept]
static = "ripple"             # "scanlines" (the default), "ripple" or "swell"
```

Mire uses `ripple` and Tidewell uses `swell`. The intercept's colours are in
`colors.toml`'s `[intercept]` table.

### `colors.toml`

A theme names its colours by role, not by hue. Templates ask for `primary`, never for
"green", so a theme whose primary is amber still reads right.

A value is `"#rrggbb"`, or the name of another colour in the file. That can be a role, a
`[colors]` name, or `table.key`. Names can point at names, but not in a loop.

These are the roles. The values are the Wick's.

| Role | Used for | The Wick |
|---|---|---|
| `background` | The desktop, terminal and lock-screen background | `#000500` |
| `void` | The deepest black: tooltips, input wells, shadows | `background` |
| `panel` | The bar, the launcher, notifications, panel plates | `#001300` |
| `selection` | The selected row, inactive borders | `#003b00` |
| `primary` | Live values, active borders, the cursor | `#39ff14` |
| `soft` | Body text on panels | `#9cff8a` |
| `dim` | Rules, frames, quiet labels | `#159b09` |
| `text` | Terminal and long-form text | `#c4f5bb` |
| `muted` | Inactive labels | `#7e927e` |
| `faint` | Disabled text | `#4e6b4e` |
| `warn` | Warnings, urgency, recording | `#d4af37` |
| `danger` | Errors, critical values, alarms | `#ff766f` |
| `warn_surface` | Behind an urgent selected row | `#4a3a0a` |
| `danger_surface` | Behind a critical notification | `#1a0503` |
| `danger_text` | Text on `danger_surface` | `#ffd9d6` |

The tables:

| Table | What it holds | Read by |
|---|---|---|
| `[colors]` | Extra named hues: `cyan`, `gold`, `white`, `rust` | kitty, btop, Neovim, waybar |
| `[terminal]` | `foreground`, `background`, `color0` to `color15` | kitty, Neovim's terminal |
| `[qt]` | Extra surfaces for the Qt colour scheme | `kde.colors` |
| `[intercept]` | `static` (default `primary`), `needle` (default `soft`) | the live layer's intercept |
| `[holo]` | `line`, `glow`, `label`, `highlight` | reserved |
| `[widgets]` | `frame`, `header`, `value`, `graph`, `track` | reserved |

Each `[colors]` name becomes a top-level name in templates, like a role. So a name can't
be both a role and a `[colors]` name. Nothing reads `[holo]` or `[widgets]` yet, but both
go into `palette.json`, and `bromigos accessibility check` measures the `[widgets]`
pairs.

The templates use every role, the four `[colors]` names, and the `[terminal]` and `[qt]`
tables. Rendering stops at the first name a theme doesn't define. So a new theme needs all
of them. `bromigos theme new` starts you with a complete set.

## Templates

A template turns the theme's colours into one app's config. `theme/templates/<output>.tpl`
renders to `current/<output>`. Templates use [minijinja](https://docs.rs/minijinja), which
has Jinja2's syntax. Rendering is strict: a name the theme doesn't define is an error,
and nothing is written.

| Template | Output | Read by |
|---|---|---|
| `waybar.css.tpl` | A `@define-color` per role, and the bar's icons | waybar's `style.css`, by `@import` |
| `gtklock.css.tpl` | The same, for the lock screen | gtklock's `style.css`, by `@import` |
| `rofi.rasi.tpl` | rofi's variables and the launcher's layers | the launcher's theme, by `@import` |
| `kitty.conf.tpl` | The terminal palette | `kitty.conf`, by `include` |
| `dunst.conf.tpl` | Notification colours | a drop-in in `~/.config/dunst/dunstrc.d/` |
| `hyprland.lua.tpl` | Border and shadow colours, and a table of every colour | `hyprland.lua`, by `dofile` |
| `kde.colors.tpl` | The Qt colour scheme, named `Bromigos` | `~/.local/share/color-schemes/Bromigos.colors` |
| `waybar-markup.jsonc.tpl` | Colours in waybar's Pango markup | waybar's `config`, by `"include"` |
| `startpage.css.tpl` | The start page's colours | the start page's `index.html` |
| `btop.theme.tpl` | A btop theme | `~/.config/btop/themes/bromigos.theme` |
| `tmux.conf.tpl` | tmux's status, pane and message colours | `tmux.conf`, by `source-file` |
| `nvim.lua.tpl` | A Neovim colour scheme | `bromigos-apps`' `colors/bromigos.lua` |
| `chromium.theme.tpl` | The browser frame colour, as `r,g,b` | the `apps` hook |
| `userChrome.css.tpl` | Firefox and LibreWolf's window colours | a profile's `chrome/userChrome.css` |
| `swayosd.css.tpl` | The on-screen display's colours | swayosd's style |
| `zettlr.css.tpl` | Zettlr's colours and fonts | the `zettlr` hook, into Zettlr's `custom.css` ([Zettlr](#zettlr)) |

A theme can ship a finished file under a template's output name, such as `kitty.conf`.
Then the theme's file is used as it is, and that template is skipped.

### What a template sees

| Name | Value |
|---|---|
| each role and `[colors]` name | `"#rrggbb"`, as in `{{ primary }}` |
| `palette` | `[name, value]` pairs of the roles, then `[colors]`, in file order |
| each other table | a map, as in `{{ terminal.color4 }}` or `{{ terminal["color" ~ i] }}` |
| `meta` | `theme.toml`, as in `{{ meta.name }}` and `{{ meta.mode }}` |
| `theme` | the theme's id, such as `wick` |
| `a11y` | the user's accessibility settings: `a11y.motion` and `a11y.contrast` |

Loop over `palette` with `{% for name, value in palette %}`.

`a11y.motion` is `full`, `reduced` or `still`. `a11y.contrast` is `normal` or `high`. Under
high contrast, the colours a template sees are already the high-contrast ones. Use
`a11y` for what isn't a colour, such as an opaque layer or a wider border:
`{% if a11y.contrast == "high" %}`. [accessibility.md](accessibility.md) has the details.

A template that uses `a11y` starts with a default for it:
`{%- set a11y = a11y if a11y is defined else {"motion": "full", "contrast": "normal"} -%}`.
An update from bromigOS 0.1.0 or 0.1.1 renders the new templates with that release's
`bromigos`, which has no `a11y`. Later releases hand the theme to the newly installed
`bromigos` instead.

Three filters help with formats:

| Filter | Turns | Into |
|---|---|---|
| `strip` | `#39ff14` | `39ff14` |
| `rgb` | `#39ff14` | `57,255,20` |
| `kebab` | `warn_surface` | `warn-surface` (for rofi, whose names can't hold `_`) |

To add an alpha, write it after the hex value: `{{ selection }}cc`, or
`rgba({{ selection | strip }}ee)`.

### Connect an app to the theme

An app's config reads its colours from `current/` and keeps everything else of its own.

```css
/* waybar and gtklock style.css: the path is relative to the style file */
@import url("../../.local/state/bromigos/theme/current/waybar.css");
```

```text
/* rofi */  @import "~/.local/state/bromigos/theme/current/rofi.rasi"
# kitty     include ~/.local/state/bromigos/theme/current/kitty.conf
```

```lua
-- Hyprland
local state = os.getenv("XDG_STATE_HOME") or (os.getenv("HOME") .. "/.local/state")
local ok, theme = pcall(dofile, state .. "/bromigos/theme/current/hyprland.lua")
```

dunst has no include. Instead, `~/.config/dunst/dunstrc.d/90-bromigos-theme.conf` is a
link to `current/dunst.conf`. A drop-in overrides `dunstrc` key by key.

## `palette.json`: colours for apps that draw their own

Some apps draw their own colours: the panels, VECTOR, the live layer's decks and
overlays, and the bar's scripts. They read `current/palette.json`. `theme set` writes it
with every name resolved to a colour.

```json
{"schema": 1, "theme": "mire", "name": "Mire", "mode": "dark",
 "colors": {"background": "#05090a", "primary": "#b8e05a", "…": "…"},
 "tables": {"holo": {"line": "#b8e05a", "…": "…"}, "terminal": {"…": "…"}},
 "motion": "full", "contrast": {"mode": "normal", "ok": false, "lowest": {"…": "…"}}}
```

- `colors` holds the roles and the `[colors]` names.
- `tables` holds every other table.
- `motion` and `contrast` are the user's accessibility settings, as rendered. `ok` and
  `lowest` say how the colours measure against the high-contrast targets.

Python apps read it through `bromigos_theme` (`lib/bromigos_theme.py`, installed in
`/usr/lib/bromigos/lib/`). If the file is missing, it falls back to the Wick. It also
maps the Wick's old colour names (phosphor, amber, guard, static) onto the roles. Apps
check the file about once a second. `set` swaps in a new file, so its inode changes, and
they redraw in the new colours. No signal or restart is needed.

## Icons

`theme/icons/*.svg` is the bar's icon set: CPU, memory, disk, network and the rest, each
in four states, plus `emblem.svg`. The icons are drawn in the Wick's colours. `set` writes
each one into `current/icons/`, swapping every Wick colour for the theme's colour in the
same role. The rendered `waybar.css` points each bar module at its icon.

- A theme's own `icons/<name>.svg` is used as it is.
- Your own `~/.config/bromigos/theme/icons/<name>.svg` replaces the shipped icon with that
  name.
- The bar's emblem is the theme's own `emblem/emblem-small.svg`, sized to 48 pixels, when
  the theme has an emblem kit. Otherwise it's the Wick's, recoloured.

## The emblem

The emblem is a flame inside a ring of text. bromigOS calls it *the burn-in*. It appears
on the bar, the lock screen, the launcher's header, notifications, the shell banner, the
start page, the live layer's intercept and screensaver, and the boot menu.

A theme can carry its own version of the emblem, in `emblem/`. The flame, its mast and the
ring's shape never change. A theme can change:

- the colours,
- the motto in the ring,
- what fills the gap at the top of the ring,
- what stands around the flame.

The motto is only ever a motto. It's never a callsign, a name or a frequency.

`emblem/emblem.toml` describes it. Colours can name a role from `colors.toml`.

```toml
motto = "NOTHING HERE IS FORGOTTEN · ONLY SLEEPING ·"
gap = "reeds"      # the gap at the top: "ticks" (the default), "reeds" or "song"
sigil = "flood"    # around the flame: "none" (the default), "flood" or "swell"

[colors]
ring = "primary"   # the lines, the motto, the gap and the halo
hairline = "dim"   # the flame's edge and its mast
water = "dim"      # the flood lines or waves
eyes = "cyan"      # flood: the two eye-lamps
choir = "primary"  # swell: the line of light under the flame
flame = "#000000"  # the flame gives no light, in every theme
```

`flood` draws still water, a broken reflection and two eye-lamps. `swell` draws two waves
and a line of light passing under the flame.

### Build the emblem kit

The kit is built from `emblem.toml`, never drawn by hand. It's committed, and it ships in
the package. From a checkout, run:

```bash
bin/bromigos-emblem build --theme themes/mire
```

On an installed system, the same command is `bromigos emblem build --theme <dir>`.

It draws from the canonical burn-in (`theme/emblem/identity.json` and `flame.svg`) with
the theme's changes. Every kit has the same file names, so anything that shows the emblem
only swaps the folder.

| File | What it is |
|---|---|
| `emblem.svg` | The whole emblem, with the text as outlines |
| `emblem-ring.svg` | The ring alone, which turns |
| `emblem-flame.svg` | The halo and flame, which hold still |
| `emblem-small.svg` | A simpler version for under 64 pixels |
| `emblem-{256,512,1024,2048}.png` | The emblem as pictures |
| `emblem-void-{1024,2048}.png`, `emblem-glow-1024.png` | On black, and with a glow |
| `emblem-small-{32,48,64,128}.png` | The small version as pictures |
| `emblem.braille` | The shell banner's emblem |
| `lock/ring.png`, `lock/flame.png` | The lock screen's two layers |

The Wick has a kit too, built from an empty `emblem.toml`. It's the canonical burn-in, so
switching back to the Wick puts it back exactly.

### Where the emblem goes

`set` copies the kit into `current/emblem/`. The `emblem` hook keeps
`~/.local/state/bromigos/emblem` pointing at it, or at the Wick's kit when a theme has
none. Everything that shows the emblem reads that link or `current/emblem/`.

The boot menu follows the theme too ([boot.md](boot.md)). A theme without a kit gets the
Wick's, recoloured.

Three places keep the Wick's burn-in in every theme:

- the Drift map deck, where it marks the Wick itself;
- the login screen (SDDM);
- the boot splash (Plymouth).

The last two live in system folders that a user's `theme set` can't write.

In the stories, each post signs with its own version of the burn-in. Mire's ring speaks of
the Sleepers, and Tidewell's gap holds a stretch of the Choir's song. The Bromigos world
bible (`agents/LORE.md` in the platform repository) has each post's mark.

## Hooks

Some changes need more than a template. For those, `set` runs the *theme-set hooks* after
it reloads the apps. Hooks come from three folders:

- the shipped ones, in `/usr/share/bromigos/hooks/theme-set.d/` (package
  `bromigos-desktop`);
- installed extensions', linked as `<extension>--<file>` in
  `~/.local/share/bromigos/ext/active/hooks/theme-set.d/`;
- yours, in `~/.config/bromigos/hooks/theme-set.d/`.

They run as one list, in name order. A hook of yours with the same file name replaces a
shipped or an extension's hook. To switch one off, put an empty file with its name in
your folder. Only executable files run.

Each hook gets the theme's name as its argument. It also gets `BROMIGOS_THEME`,
`BROMIGOS_THEME_DIR` (the rendered theme) and the session's Wayland variables. `set`
waits for each hook, so keep them quick. If a hook fails, `set` reports it and exits with
status 1, but the theme stays set.

| Hook | What it does |
|---|---|
| `apps` | Makes running apps take the new colours: tmux, btop, Neovim, Chromium's frame and Firefox |
| `boot` | Updates the boot menu's theme, if bromigOS's GRUB theme is on ([boot.md](boot.md)) |
| `emblem` | Points `~/.local/state/bromigos/emblem` at the theme's emblem kit |
| `gtk` | Builds a GTK theme from the colours and switches GTK apps to it |
| `osd` | Restarts the on-screen display with its new style |
| `wallpaper` | Sets the wallpaper and the lock screen's background for the theme |
| `zettlr` | Puts the theme's colours into Zettlr's custom CSS and sets its dark mode ([Zettlr](#zettlr)) |

A few details:

- **`apps`** skips any app that isn't there. tmux re-reads its colours in a running
  server. Neovim needs nothing: `bromigos-apps`' colour scheme watches its file. A running
  Chromium or Chrome takes the new frame colour. Firefox and LibreWolf profiles with a
  `chrome/` folder get `userChrome.css` linked into it.
- **`boot`** runs in the background. If `sudo` needs a password, the next
  `bromigos update` applies it, and a notification says so.
- **`gtk`** builds `Bromigos-<theme>` into `~/.themes` in about half a second. It points
  `~/.config/gtk-4.0/gtk.css` at the theme for libadwaita apps, which pick it up when they
  next start. The Wick's GTK theme is `Bromigos`, from `bromigos-settings`. The hook
  leaves your GTK theme alone if it isn't a bromigOS one.
- **`wallpaper`** makes a world's painting the wallpaper under the live layer, and a
  darker copy the lock screen's background. The Wick gets its den back.

## What `bromigos theme set` does

1. It loads the theme and renders every template in memory. If the user has high
   contrast on, the colours are made high-contrast first. Any error stops here, before
   anything is written.
2. It copies the theme's folders into a staging folder beside `current/`. Then it writes
   the merged `colors.toml` and `theme.toml`, the rendered files, `palette.json`, the
   icons and a `name` file.
3. It swaps the staging folder into `current/` in one step (`renameat2` with
   `RENAME_EXCHANGE`). Apps see the old theme or the new one, never a mix.
4. It tells the running apps:
   - waybar restarts, since an in-place reload can crash it;
   - each kitty gets `SIGUSR1`;
   - Hyprland runs `hyprctl reload`;
   - dunst runs `dunstctl reload`;
   - the live layer gets `theme` on its socket and swaps to the theme's world or the den.

   The panels, VECTOR and the decks follow `palette.json` on their own. gtklock, rofi and
   Qt apps read their file when they next start.
5. It runs the hooks.

`--no-reload` stops after step 3: no app is told and no hook runs. Only one `set` runs at
a time, using a lock on `~/.local/state/bromigos/theme/.lock`. It exits with status 1 for
an unknown theme or a failed reload. The JSON output's schema is in
[core/README.md](../core/README.md).

## The theme switcher

The theme switcher is the Themes tab of the Customize window. Customize has a tab for each
part of the desktop's look: **Themes**, and **Widgets**, the
[widget gallery](widgets.md#the-widget-gallery). Ctrl+Tab, or Ctrl+1 and Ctrl+2, moves
between them.

**Super+Ctrl+Shift+Space** opens Customize on Themes. You can also run `bromigos theme
switcher` or `bromigos customize`, or choose STYLE › Customize: themes… in the menu.
`bromigos customize --tab widgets` opens it on Widgets. The Themes tab shows every theme as
a preview of your desktop wearing it. Choosing one runs `bromigos theme set`.

Above the cards are the Themes tab's tools:

- **Wallpaper, sounds, lights…** opens Settings › Theme at what goes with any theme: the
  live background, the wallpaper, the theme's sounds and the keyboard's lights.
- **Make your own…** copies the selected theme into a new one of yours, in
  `~/Themes/<name>`, with `bromigos theme new <name> --from <selected>`, and installs it.
  Change its `colors.toml`, then run `bromigos ext update <name>`.
- **Remove** removes the selected theme, when it's one you installed or made. bromigOS's
  own themes and the theme in force can't be removed.
- **Install from URL…** installs a theme from a git repository or a folder, after showing
  what it is. It works as in the [widget gallery](widgets.md#the-widget-gallery).

The switcher opens over the monitor you're on, with the desktop dimmed behind it. It fits
as many cards as suit that monitor, each at least 300 pixels wide and 16:9 like the
previews. When there are more themes than fit, it scrolls.

Each card shows the theme's name, a short tagline and a badge:

- **WORLD** for a world, **DEN** for the Wick, **COLOUR** for a colour theme;
- **CATALOG** for a theme from an extension catalog that isn't installed yet;
- **IN USE** on the theme in force.

Hover over a card to see what it is and what choosing it does.

| Key | What it does |
|---|---|
| Arrows, Page Up, Page Down, Home, End | Move the selection. It starts on the theme in force. |
| Enter, or a click | Apply the selected theme. A catalog theme is installed first. |
| Letters | Filter by name, description, kind (`world`, `den`, `colour`) or `catalog`. |
| Ctrl+Tab | Change tab. |
| Esc, a click outside, or the shortcut again | Close the switcher. Esc closes an open form first. |

`bromigos theme switcher --list` prints the cards and their pictures.

### The previews

A preview is a real picture of the desktop wearing the theme, drawn where nobody sees it.
It shows the theme's world or the den, the bar, a terminal, and the SYSTEM and NETWORK
panels, all with demo readings.

Where `kwin_wayland`, Hyprland and grim are installed, the preview is the real desktop.
bromigOS runs a Hyprland with its own config inside a headless kwin
(`kwin_wayland --virtual`, which has no screen). In it run the real waybar, panels and
kitty, and the live layer's own frame is the background. grim captures it. The picture is
1280×720, of a 1920×1080 desktop.

The picture has to show the whole desktop, so the renderer checks its size twice:

- A kwin window rule keeps the nested Hyprland full screen. The rule is written to
  `kwinrulesrc` in the throwaway home. Without it, kwin 6.8 sends Hyprland's
  window a late "choose your own size". Hyprland reads that as 1280×720, and the preview
  showed only the desktop's top-left corner.
- Before the picture, the renderer waits for Hyprland's output to be the size asked for.
  After it, the renderer checks grim's picture is that size too. If either is wrong, the
  picture is thrown away, the nested desktop is tried once more, and then the preview is
  put together from its pieces instead (see below). A cut-off picture is never cached.

The nested Hyprland never takes a login session. It's started with
`LIBSEAT_BACKEND=none`, so it can't open a seat and draws only into kwin. Without that,
Hyprland took the login session it was started from. When that session wasn't the one on
screen (a terminal started from a text console, say), Hyprland drew nothing: no bar, no
panels, and grim waited 30 seconds for a frame that never came. Every preview was then
put together from its pieces.

The hand-run nested tests (`desktop/tests/e2e_keys_nested.py` and the tests built on it)
use the same kwin rule, the same size check and the same `LIBSEAT_BACKEND=none`. They stop
at once if the nested screen isn't the size they asked for.

Each preview's `.json` file records the size asked for (`size`) and the size grim
captured (`captured`).

kwin comes with KDE Plasma, not with bromigOS. Without it, the same pieces are drawn one at
a time and put together: kitty and the bar in a headless weston, the panels from their own
drawing code, and Hyprland's border from the theme. `BROMIGOS_PREVIEWS_NESTED=0` forces
this way. Each preview's `.json` file says which way it was drawn.

Every piece runs in a throwaway home folder, with its own runtime folder and none of the
session's variables. `bromigos theme set <name> --no-reload` renders the theme there.
Anything that would reach past the session, such as the wallpaper or notifications, is a
stub. Nothing opens a window on a real screen, reads the screen or signals the desktop.

No reading in a preview is this machine's. The panels and the bar's own scripts show demo
values. waybar's built-in modules (CPU, memory, temperature, network, the clock) show
theirs as fixed text, with warning thresholds they can't reach. A made-up music player on
the preview's own D-Bus fills the middle of the bar.

A colour theme's preview shows the den behind it, recoloured, as the desktop does.

**The cache.** Previews are kept in `~/.cache/bromigos/theme-previews/<name>-<stamp>.jpg`,
with a `.json` file beside each. The stamp is a hash of everything the picture shows:

- the theme's files, including an extension's and your overlay;
- the templates and the bar's style;
- the live layer's drawing code and the colour libraries it reads;
- the preview renderer's version.

So when a theme or the live layer changes, the preview is drawn again. A new renderer
version draws every preview again. Version 4 replaced the previews that kwin 6.8 had cut
to the top-left corner. Version 5 replaced any that were put together from pieces because
the nested Hyprland drew nothing. Until the new one
is ready, the switcher shows the old one with a small spinner in its corner. A theme takes 10 to 20 seconds
to draw, a world the longest. Only one is drawn at a time, at low priority.

**When previews are drawn.** Always in the background, when a theme may have changed:

- after `bromigos update`;
- after a package update without it, through a pacman hook that starts each signed-in
  user's `bromigos-theme-previews` service;
- after `bromigos ext install` or `bromigos ext update` of a theme;
- after `bromigos theme new`, for the new folder;
- when the switcher finds one missing or out of date. The card shows DRAWING, in the
  theme's colours, until the picture lands.

**When there's no GPU.** The previews need the GPU. After an NVIDIA driver update, until
the computer restarts, the driver's two halves differ and nothing can use it. Then the
renderer draws nothing: it writes one line to `render.log` and exits, and each theme
shows as held back. If the GPU fails in the middle of a run, which shows in the nested
desktop's log as an EGL or backend error, the run gives up after that one failure. That
theme gets a `.failed` file, the rest wait, and the next run tries again. It never caches
a lesser picture in place of the real one
([update.md](update.md#when-the-kernel-or-the-graphics-driver-changes)).

To draw them yourself:

```bash
bromigos theme previews                     # draw the missing or out-of-date ones
bromigos theme previews mire --force        # draw one again
bromigos theme previews --list              # each theme's stamp, and whether it's current
bromigos theme previews --dir ./my-theme --out preview.jpg     # a theme that isn't installed
bromigos theme previews mire --size 2560x1440 --out mire.png   # one desktop at any size
```

`--size` draws one theme's desktop at that size and writes it whole to `--out`, as PNG,
WebP or JPEG. It leaves the cache alone. The website's pictures are made this way, from a
checkout, with `BROMIGOS_SRC=<checkout>` and `BROMIGOS=<its bromigos>`.

With `--out`, a picture can also show other panels, and put them and the terminal where
you like:

```bash
bromigos theme previews wick --size 2560x1440 --panels system,network,weather,lab --out wick.png
bromigos theme previews mire --size 2560x1440 --scene my-scene.json --out mire.png
```

`--panels` takes panel names: system, network, storage, workbench, notes, shortcuts,
weather, connections, and lab (from bromigos-homelab). Each goes where the default layout
puts it; LAB goes beside SYSTEM. `--scene` takes a JSON file:

```json
{
  "panels": [ {"name": "system", "x": 28, "y": 16}, {"name": "lab", "x": 514, "y": 16} ],
  "terminal": {"at": [1520, 836, 1012, 576], "script": "banner.sh", "font_size": 11.5},
  "notes": "what FIELD NOTES shows"
}
```

- `panels` are entries like those in `layout.json`, with x and y measured from below the bar.
- `terminal` is `false` for no terminal. Otherwise `at` is the window's place (x, y, width,
  height, border included); without it, the terminal goes where it hides the least of the
  scene. `script` runs in the terminal instead of the demo session: it sits beside the
  scene file, must be executable, and touches `$PV_READY` once it has printed everything.
  `font_size` is in points.

Every panel shows demo readings (`widgets/demo.py`). LAB shows a made-up lab
(`widgets/demo_lab.py`), and the live layer's decks see the same lab. The README's and the
manual's pictures are drawn this way, by `tools/screenshots/render.py`, with the scenes
in `tools/screenshots/scenes/`.

### Catalog themes in the switcher

After the installed themes, the switcher shows the themes that extension catalogs offer.
It reads `bromigos ext search --kind theme --json`. That's a list, or
`{"results": […]}`, of objects with these keys:

| Key | What it is |
|---|---|
| `name` | The theme's id |
| `display_name` or `title` | The name on the card |
| `description` | The card's tagline comes from its first clause |
| `tags` | Words the filter matches |
| `preview` | The catalog's picture: a URL (fetched once into the cache) or a path |
| `install` | The command, as a list or a string. The default is `bromigos ext install <name>`. |

Themes already installed aren't repeated, nor are entries the catalog marks installed or
bundled. To make a catalog picture the same way as the others, run
`bromigos theme previews --dir <theme> --out previews/<name>.jpg`.

## The wallpaper

Under the Wick, **Super+Ctrl+Space** (`bromigos wallpaper next`) steps through the den's
installed variants. bromigOS ships one: the den with its chair empty. Variants of your own
go in `~/.config/wallpaper`.

```bash
bromigos wallpaper next
bromigos wallpaper previous
bromigos wallpaper list            # the variants, with the chosen one marked
```

Settings › Theme has the same controls. A world's painting is its wallpaper, so there's
nothing to step through. The key says so.

The choice is kept as links in `~/.local/state/bromigos/wallpaper/`:

| File | What it is |
|---|---|
| `den.jpg` | The painting the live layer draws, and recolours itself |
| `wall.jpg` | What swaybg shows under the live layer |
| `lock.jpg` | The lock screen's background |

Under a world, all three come from the world's painting. Under a colour theme, `wall.jpg`
and `lock.jpg` are the den recoloured, as described next.

## Colour themes and the den

![The den in three themes, side by side: the Wick's phosphor green, Cinder's ember orange
and Rime's ice blue](images/den-colour-themes.webp)

The den is painted in the Wick's green. Under a colour theme, bromigOS recolours the
painting too, with a gradient map in the OKLab colour space (`lib/bromigos_retint.py`):

- Each pixel keeps its lightness exactly, so every detail and all the contrast stay.
- Its hue and saturation come from a ramp of the theme's colours, picked by lightness.
  Shadows take `background`, the middle tones `dim`, highlights `primary`, and the
  brightest `soft`.
- A pixel's saturation stays relative to the Wick's at that lightness. A more saturated
  light stays more saturated.
- A pixel whose colour is far from the painting's green is a real accent, and keeps its
  colour.
- A colour outside sRGB loses saturation, never lightness.

The live layer maps its painting once when it loads it, in a fraction of a second. The
den's own shaded parts, such as the screens' glass and the meters, go through
`bromigos_theme.retint_rgb`. The burn-in on the den's monitor is the Wick's kit,
recoloured, unless the theme has a kit of its own.

`bromigos-wallpaper` does the same for the wallpaper and the lock screen. It renders them
once per variant and palette into `~/.local/state/bromigos/wallpaper/colour/`. `den.jpg`
stays the Wick's painting, because the live layer recolours it itself.

Under the Wick nothing changes: the painting comes back bit for bit
(`live/tests/offscreen_retint.py` checks this). A world keeps its own painting.

### The den in a world's colours

![Four desktops in a two-by-two grid: on the left, the den in Tidewell's cyan and in Mire's
firefly green; on the right, the Tidewell and Mire worlds they take their colours
from](images/den-world-colours.webp)

`wick-tidewell` (Wick · Tidewell) and `wick-mire` (Wick · Mire) are colour themes with the
two worlds' palettes. Choose one to keep the den, its screens and its layout, in the
world's colours. The worlds themselves, `tidewell` and `mire`, bring their own scenes.

Each one's `colors.toml` is a copy of its world's. `live/tests/test_retint.py` checks that
the two stay equal, so a change to a world's colours goes into both files.

## High contrast

`bromigos accessibility contrast high` renders any theme in high contrast. The hues stay
the same. The surfaces get deeper, and text, rules and the selection get lighter, to meet
WCAG's ratios. The bar, the launcher, notifications and the terminal become opaque.

A theme needs nothing to support this. To measure one, normal and high, run
`bromigos accessibility check <name>`. [accessibility.md](accessibility.md) explains how
it works and lists the targets.

## Make a world

A world is a theme with `live/world.toml`. The live layer (package `bromigos-live`) draws
its scene as the desktop background, instead of the den. `theme set` copies the theme's
`backgrounds/` and `live/` into `current/` with everything else, then tells the live
layer, which swaps scenes at once. The live layer also notices the change on its own
within a few seconds. Your overlay replaces single files, so you can repaint one actor.

To make a world's art, see [art.md](art.md). For what each shipped world shows, see
[worlds.md](worlds.md).

### The rules every world keeps

These are the desktop's own rules:

- Every moving thing shows a real reading or a real event. Nothing moves for decoration.
- "Needs you" always looks the same: something turns to face the user and signals.
- The keeper and the ambient creatures follow the user. They work while the user works,
  doze when the user is idle, and sleep when the session locks.
- Day and night follow the real local clock, and the moon its real phase.
- If a reading isn't available, what it drives isn't drawn. A world never shows a fake
  value.

### The art files

| Path | What it is |
|---|---|
| `backgrounds/layers/NN-name.webp` | A painted layer, 2560×1440 with alpha, drawn back to front by `NN` |
| `live/actors/<actor>.webp` | An actor's sprite, one frame, with alpha |
| `live/actors/<actor>/NN.webp` | An actor's frames, in order |
| `live/loops/*.mp4` | Seamless video loops (also `.webm`, `.mkv` and `.mov`) |
| `live/clips/*` | Clips that play once, and `manifest.toml` with their places |
| `live/sounds/*.wav` | The world's sounds |
| `live/world.toml` | The world itself. It names every file above by its path. |

Mire's layers are `00-sky`, `10-far`, `20-mid`, `30-water`, `40-near` and `50-fore`.
Tidewell's are `00-sky`, `10-surface`, `20-water-far`, `30-kelp-mid` and
`40-water-near`.

Some conventions:

- Sprites face right. Their feet, or where they meet the water, are at the bottom
  centre. Any size works, because `world.toml` says how tall to draw them.
- A `front` frame faces the viewer. "Needs you" turns to it.
- The water layer's colour is the water's colour. Its alpha is where the water is (a
  mirror world) or how thick it is (a split world).
- Paint the art at night. The clock's grade and `day_lift` light it for the hour.

`theme/tools/placeholder-worlds.py` draws placeholder art. It never replaces a file that
exists.

### `live/world.toml`

Paths are relative to the theme folder. Positions and sizes are in pixels of the
2560×1440 painting, from the top left, and scaled to the monitor.

```toml
format = 1
name = "Mire"

[camera]
parallax = "cursor"   # the layers sway with the pointer while the user works; or "off"
sway = [22, 9]        # how far, in pixels, at parallax 1.0

[clock]               # the light by the hour, as RGB multipliers
dawn = [5.5, 7.5]     # the hours of dawn and dusk
dusk = [18.0, 20.5]
night = [0.62, 0.72, 0.86]
day = [0.95, 1.0, 0.95]
dawn_tint = [1.05, 0.82, 0.86]
dusk_tint = [1.1, 0.74, 0.56]
# twilight = [r, g, b]   the twilight glow's colour
# day_lift = [r, g, b]   light added by day

[water]
mode = "mirror"       # or "split"
line = 905            # the waterline's y

[[layers]]            # one per art file, drawn by depth
file = "backgrounds/layers/00-sky.webp"
depth = 0
parallax = 0.04       # 0 is still, 1 moves the most
sky = true            # carries the moon, the twilight glow and the lightning

[[effects]]           # reusable effects, one of each type per world
type = "rain"
signal = "cpu"
from = 0.35
full = 0.85

[[actors]]            # creatures and craft
id = "sleepers"
kind = "agents"
sprite = "live/actors/sleeper"

[loops."live/loops/hollis-working.mp4"]
alpha = "stacked"     # how this video carries transparency

[sounds]
ambient = []          # [{ file, every = [min, max] seconds, gain }]

[rollcall]            # at login, the world's lights wake one by one
sequence = "lights"
sound = ""            # reserved for a short cue

[view]
focus = [1280, 600]   # optional: the point to keep in view on screens that aren't 16:9
```

**Water.** A `mirror` world reflects everything behind the water layer, with ripples and
wakes. It takes `reflect`, `ripple` and `tint`. A `split` world has a moving surface line
with the deep below it. It takes `layer` (the water layer's id), `tide = "moon"` with
`tide_range`, `fog`, `fog_distance` and `fog_actors`.

**Layers.** Each layer has `file`, `depth` and `parallax`, and optionally an `id`.
`sky = true` marks the sky. `water = true` marks the water plane. `fog = true`, or a number
from 0 to 1, fogs the layer under a split world's surface. In a mirror world, everything
shallower than the water layer reflects. Actors in the water (`wade`) draw their own
reflection and are cut at their waterline. A layer can sway from its rooted bottom with
`sway = { signal, min, max, top, bottom }`, like Tidewell's kelp.

**Sounds.** Ambient sounds play often while the user works, a third as often when idle,
and not at all when the session is locked.

**Requires.** Any effect or actor can say `requires = "<signal>"`, such as `"lab"`. While
that source isn't available, it isn't drawn at all.

**Screens that aren't 16:9.** Worlds and the den are painted for 16:9. On a 16:10, 21:9,
32:9 or 3:2 screen, the live layer draws the scene at the smallest 16:9 size that covers
the screen, and shows the part that fits (`live/live/cover.py`). The scene is cropped,
never stretched. The crop is centred, or centred on `[view] focus`, kept inside the
picture. On a 16:9 screen, within 1%, the scene is drawn directly.

### Video loops

A layer with `video = "live/loops/<name>.mp4"` is a living backdrop. Its `file`, if given,
is shown until the first frame. Any actor sprite, or a state's `sprite`, that names a
video plays it instead of a still.

The live layer decodes each loop with ffmpeg, using the GPU's video decoder where it can
(NVDEC, VA-API or Vulkan). A loop only advances while it's drawn. When the background
pauses, for example while locked, under a fullscreen window or behind a deck, the decoder
waits and costs nothing. A loop that isn't drawn for 20 seconds is stopped until it's
needed.

Each video's `[loops."<path>"]` table sets `alpha`, and optionally `fps` (default: the
file's) and `scale` (decode at this fraction of the file's size).

| `alpha` | The file | Decoded |
|---|---|---|
| `none` (the default) | Opaque H.264, HEVC, AV1 or VP9 | by the GPU |
| `stacked` | The colour on top and its alpha as grey below, in one frame twice as tall | by the GPU |
| `native` (default for `.webm`) | VP9 or AV1 with an alpha channel | by the CPU, so keep these small |
| `luma` (default for `blend = "add"`) | Opaque glow art on black: the brightness is the coverage | by the GPU |

Make loops seamless: the last frame should flow into the first. Keep them modest:

- Draw creature and keeper loops at the size they're shown.
- Make a backdrop 1280×720 to 1920×1080, at 24 frames a second or less. A 1920×1080 loop
  at 30 frames a second costs about 9% of one CPU core to decode on the reference
  machine. 1280×720 at 24 costs about a third of that.
- Prefer `stacked` H.264 or HEVC over VP9 with alpha.

### Effects

Each effect is a `[[effects]]` table with a `type`. Most are bound to a `signal`.

| `type` | What it draws |
|---|---|
| `moon` | The real moon, its phase and place from the local clock, reflected in the water |
| `stars` | A faint starfield in the sky, hidden by every layer in front |
| `mist` | Low mist over the water |
| `rain` | Rain streaks and rings on the water, from drizzle to downpour |
| `lightning` | A bolt in the sky and a flash over everything |
| `fireflies` | Glowing particles drifting on a slow flow, each blinking on its own rhythm |
| `line` | A fishing line from the keeper's rod to a float |
| `beacon` | A blinking light, such as a mast's, while its signal is true |
| `beam` | A turning lighthouse beam |
| `swell` | A split world's surface swell, and the light patterns under it |
| `spray` | Splashes when an actor breaches or a catch leaves the water |
| `rays` | Light shafts down from a split world's surface |

Their parameters:

- **`moon`**: `window` (where it rides), `radius`.
- **`stars`**: `brightness`, `density`, `cell`, `horizon`, `fade`. They're brightest in
  deep night, gone by day and hidden by a storm.
- **`mist`**: `signal`, `band` (y0, y1), `base`, `gain`, `full`, `color`.
- **`rain`**: `signal`, `from` (where it starts) and `full` (a downpour). Or `mix`, a list
  of terms `{signal, from, full, floor, max}`. Each term is 0 at or below `from`, then
  rises from `floor` to `max` at `full`. The terms combine like layers of cloud:
  1 − Π(1 − term). `onset` and `tail`, in seconds, ease the rain in and out so it never
  flickers. Mire's rain mixes three terms: agents working, the homelab's models and the
  CPU.
- **`lightning`**: `signal`, `above` (the threshold), `every` (seconds between strikes),
  `zone`, `ground`.
- **`fireflies`**: `signal` sets their number and brightness, smoothed. `zone` is
  (x0, highest flight, x1, nearest water). Also `base`, `gain`, `max`, `curve`, `smooth`,
  `speed`, `reflect`, `near_depth`, `far_depth`, `color` and `color2`. `rain_hides` (0 to 1)
  is the share that goes to ground in a downpour. They scatter from a Sleeper rising or
  sinking.
- **`line`**: `float`, `sag`, `depth`, `color`. It goes taut on a catch. With
  `slack = false` it draws only while taut.
- **`beacon`**: `signal`, `at`, `color`, `period`, `radius`, `depth`.
- **`beam`**: `signal` and `colors` (one per level) set its colour. `rate_signal`, `rate`
  and `rate_gain` set how fast it turns. Also `at`, `reach`.
- **`swell`**: `signal`, `min`, `max` (in pixels), `wavelength`, `caustics`.
- **`rays`**: `gain`, `base`, `slant`, `reach`, `color`. The shafts move with the swell and
  flicker with lightning. With `follow_moon` they gather under the real moon at night.

### Actors

An actor is an `[[actors]]` table: a creature, a keeper or a craft. Its `kind` says where
its instances come from.

| `kind` | Its instances | Its states |
|---|---|---|
| `keeper` | The world's keeper, one, mirroring the user | `working`, `dozing`, `asleep` |
| `agents` | One per AI coding agent | `working`, `needs_you`, `finished`, `gone` |
| `signal` | One, whose state is a signal's value | one table per value |
| `crowd` | A flock or a school at fixed spots, following the user | `working`, `dozing`, `asleep` |
| `traffic` | Craft crossing on lanes | none |
| `event` | Spawned by events, such as a notification | none |
| `flyby` | Craft crossing the sky now and then | none |

More about each kind:

- **`keeper`**: its `lamp` dims with it. Its `events` table shows a pose for an event, as
  `events = { fill_win = { sprite, rect, after, seconds } }`. Mire's keeper holds up his
  catch this way.
- **`agents`**: one instance per agent that herdr runs, oldest first. (herdr is the
  terminal workspace manager for AI coding agents that bromigOS can install.) `max` caps
  them. `take = [from, to]` splits agents between definitions. In Mire, the first four
  agents are pieces of a half-sunk Sleeper and the rest wade. `slots` gives fixed places,
  each with its own `sprite`, `emissive` and `lights`. An error shows as `needs_you` in
  `error_color`.
- **`signal`**: the state is the signal's value, such as `"0"`, `"1"` and `"2"` for lab
  health, or VECTOR's states. A state with `hidden = true` hides the actor.
- **`crowd`**: `spots` places it. `around` and `spread` make it circle, and a small
  spread keeps a school together. `croak` with `hop_every` makes frogs hop between spots, and
  `sound` plays at each croak.
- **`traffic`**: craft cross on `lanes` in a `band`. Whether a crossing carries a craft is
  decided off-screen, from `base + gain × signal`, so nothing pops into view.
- **`event`**: each `[[actors.on]]` variant takes `event`, `motion`, `sprite`, `count`,
  `stagger`, `seconds`, `depth`, `tint`, `light`, `from`, `to`, `fade_in`, `fade_out`,
  `scale` (a number or a `[lo, hi]` range), `bright`, `distinct` (each creature its own
  `to`) and `under` (start beneath the target, ± pixels).
- **`flyby`**: one craft at a time, picked by `weight` from its `[[actors.craft]]`
  tables. The time to the next pass is `every` seconds on a quiet network, and passes
  faster with the signal (`gain`). `first` is the wait for the first one, and `max` the
  most at once. Each craft has `id`, `sprite`, `distance`, `height`, `speed` and `y` (each
  a near and a far value), plus `bob`, `bank`, `climb`, `haze`, `bright` and `lights`. A
  light can `blink`, as `"strobe"` or a period in seconds. Flybys are off with
  `bromigos anim off ships`, and under reduced motion.

**Common keys.** Every actor has `id`, `kind`, `sprite`, `height` and `depth`. As needed:

- `at`, `zones`, and `wade` (the share under its waterline), `reflect`, `fog`;
- `frames`: named lists of frame indices, such as `walk`, `front`, or one per state;
- `lights`: `at` and `front_at` (fractions of the sprite), `radius`, `color`, and `spill`
  (a wide faint glow on the water);
- `emissive`: a mask sprite with the same frames, white where light is painted, such as
  eyes. It's drawn as light in the actor's light colour, whatever the hour;
- `anchors`: named points per frame, such as the keeper's `rod`;
- `states`: one table per state, with `motion`, `light`, `lamp`, `hidden`, `turn`,
  `signal`, `color`, `tint`, `pulse`, `flicker`, `breathe` (`[amount, Hz]`) and `at`.

**Depth.** A zone (`zones`, or an event's `from`) can carry a fifth number, and a crowd's
spot a third. That's the instance's depth for its whole life. So one actor can have
creatures in front of a layer and others behind it, and nothing pops through. A deeper
instance looks farther away, by `far_scale` (default 0.72) and `far_bright` (default 0.6).
`hidden_x` lists spans (`[[x0, x1], …]`) where a far creature never stops, and which a
wanderer crosses quickly.

**Variety.** A crowd's `sizes` (`[lo, hi]` times its height) and `tints`
(`[r, g, b, amount]`) give each instance its own size and colour. `sprites`, a list of
loops or stills, gives each its own art. `light_colors` sets the colour of its lights.
Lists are dealt in turn, one per spot, so five members are five different ones.

**Art cut from the painting.** `rect = [x, y, w, h]` places a still or a loop exactly
where it sits on the painting. It works on the actor, a state or an event's pose. `patch`
does the same for a slot, or names a clip whose place is in `live/clips/manifest.toml`.
`emissive_rect` places a light mask inside a bigger patch. Some more keys:

- `faces = "left"` flips art drawn facing left.
- `front_sprite` is a separate still for the turn to the viewer.
- `poses = { sit, croak, hop }` gives a crowd a still per pose.
- `tow = { sprite, at, pivot, height, angle, sway, rate }` hangs a second sprite behind
  the actor, like Tidewell's trawlers towing their nets.
- `blend = "add"` marks glow art on black. Its loop's brightness is its coverage
  (`alpha = "luma"`), so fog and the water's tint stay on the creature.

**"Needs you."** `turn = true` stops the actor and turns it to its `front` frame, or
squashes it round when there's none. `signal = true` flashes its lights twice in
`signal_color`, then blinks them at 0.55 Hz. A state's `sink` below zero lifts it a
little.

**An agent's life in the water.** This applies to any `agents` actor with `wade`:

1. When an agent starts, or works again after finishing, bubbles rise for `rise_hold`
   seconds (default 1.2) and a swell spreads.
2. The actor breaks the surface over `rise_seconds` (default 2.6). Its lights stay dark
   until they clear the water (`eye_v` says how far down the sprite the eyes are). Then
   they flicker on and settle into the state's light.
3. When the agent finishes, it sinks to the state's `sink`. Past 1 is under. Rings
   spread, its lights dim as they go under, and the last bubbles rise.

Rising and sinking scatter nearby fireflies.

**Clips that play once.** A state's `clip` plays once when the state begins. A clip is a
video in `live/clips/`, or any video marked `once = true` in `[loops]`. Then it chains
into the state's `sprite`, or holds its last frame with `hold = true`. A clip can be a
patch of the scene rather than a cut-out. Give its place as `patch = [x, y, w, h]`, and put
a feathered mask beside it, named `<name>-mask.png`. A slot can have per-state sprites,
and a `rise_clip` and `submerge_clip`. In Mire, the Sleeper's head and hand are patches
with all four clips. The shoulder and crown are cut-outs that slide.

**Motions.** A state's `motion` is one of:

| Motion | What it does |
|---|---|
| `still`, `hold` | Stays put (`hold` with a slight bob) |
| `bob`, `rock`, `hover` | Bobs, rocks like a rocking chair, or hovers (`pace` below 1 slows it) |
| `wander` | Walks in its zone, using the walk frames |
| `roam` | Drifts round its spot by pulses, like a jellyfish (`range`, `rate`, `speed`, `bob`, `top`) |
| `settle` | Sinks by `sink` |
| `circle`, `drift`, `pace` | Circles, drifts, or paces along `path` |
| `croak` | Puffs its throat and hops between spots |
| `breach` | Rises to the surface and leaps every `every` seconds |
| `dive` | Dives, leaving a trail |

Events also have `rise`, `approach` (comes at the viewer, growing to `grow`), `reel` (up
the fishing line), `drift_up`, `dart` and `glide`. A glide is a calm pass with soft ends:
a shallow `arc`, a slow `bob`, banking by `bank` and turning at `spin` radians a second.

### Signals and events

| Signal | What it is |
|---|---|
| `cpu`, `gpu`, `mem` | This machine's load, 0 to 1. The CPU is smoothed over about 3 seconds. |
| `net`, `net_rx`, `net_tx` | Network throughput both ways, down and up, on a log scale from 0 to 1 |
| `health` | Lab health: 0 all well, 1 degraded, 2 something down |
| `lab_green`, `storm` | Every node and service is up; health is 2 |
| `lab` | A homelab snapshot is available |
| `fills` | A personal plugin's fills feed is answering |
| `ingress` | The homelab's incoming requests per second |
| `user` | `working`, `dozing` or `asleep` |
| `activity` | The same as a number: 1, 0.4 or 0 |
| `vector` | VECTOR's state: `off`, `idle`, `thinking`, `speaking`, `listening` or `error` |
| `agents` | herdr's agents |
| `agents_working` | Agents at work now, including busy Claude Code sessions outside herdr |
| `models` | The homelab's local models generating, from 0 to 1 |
| `hour`, `daylight` | The local hour, and how much daylight there is |
| `moon_phase`, `tide` | The moon's age from 0 to 1, and the tide from −1 to 1 |

`models` comes from LiteLLM through Prometheus every 10 seconds: requests per minute
divided by 30, or output tokens per second divided by 40, whichever is higher. Without
Prometheus, it's the lab snapshot's requests per minute.

The events are `notify` and `critical` (notifications), `fill`, `fill_win`, `fill_loss`
and `fill_open` (a personal plugin's fills), `lab_alert`, and `login` (the roll call).
`flyby` or `flyby:<craft id>` sends a craft over now, for testing.

### Try it on the running desktop

```bash
bromigos-live world state                  # what the world sees now
bromigos-live world event critical         # send an event
bromigos-live world event fill win
bromigos-live world set cpu 0.95           # hold a signal at a value
bromigos-live world set agents a:working,b:needs_you
bromigos-live world clear                  # let go of held signals
bromigos-live world rollcall               # play the login roll call
```

## What isn't themed yet

- **hyprlock**, the fallback lock screen, keeps the Wick's colours. Its background and
  emblem follow the theme, through the `wallpaper` and `emblem` hooks.
- **The login screen (SDDM) and the boot splash (Plymouth)** keep the Wick's look. Their
  files are in system folders that a user's `theme set` can't write.
- **libadwaita apps** take a new theme when they next start.
- **Zettlr** takes a new theme when it next starts. It reads its custom CSS only then.
- **A deck that's open** when the theme changes recolours its shapes at once. Effects
  built into its shader change when it next opens.

## Tests

- **The switcher's layout.** `python -m unittest discover -s desktop/tests` runs
  `test_theme_switcher.py` with no display. It checks the grid at 1366×768, 1920×1080,
  2560×1440 and 3440×1440. It also checks the preview stamps, the still den in a colour
  theme's colours, the bar's modules, the border and shadow, where the terminal sits, and
  what each card says. `NestedSizeTest` checks that a picture of the wrong size is
  refused, that the kwin rule keeps the nested desktop full screen, and that waiting for
  the nested screen's size fails when it never reaches it.
- **The whole desktop in each preview.** `python3 desktop/tests/e2e_previews_nested.py`
  draws the Wick in the nested desktop, in a throwaway home, at 1920×1080 and 1600×900,
  and its cached preview. It fails if a picture isn't the size asked for, or if the
  nested desktop fell back to the pieces. It needs kwin_wayland, Hyprland, grim and a GPU,
  so it runs by hand. Build `bromigos` first.
- **The previews and the switcher, drawn.** `tools/theme-switcher/render.sh <outdir>`
  draws every preview with this checkout, in a throwaway home. Build `bromigos` first.
  Then it draws the switcher offscreen at each size, in a headless weston of its own.
  Nothing can reach the desktop you're on. Options:
  `[--size WxH]… [--theme NAME] [--filter TEXT] [--catalog FILE] [--previews DIR]
  [--backdrop IMAGE]`. `--backdrop` is the desktop behind the switcher, instead of the
  theme in force's preview: a full-size `bromigos theme previews … --size WxH --out` picture.
- **Checking the renders.** `tools/theme-switcher/check.py` then checks that every
  shipped theme has a preview, drawn from every piece and not blank, and different from
  the others where the theme shows. A preview drawn in the nested desktop must have been
  captured at the size it asked for. The switcher fails a render if any part of it has no
  hover hint. `--previews DIR` reuses an earlier run's previews.
- **The den's recolouring.** `live/tests/test_retint.py` and
  `live/tests/offscreen_retint.py`.
- **Zettlr.** `core/crates/bromigos/tests/theme_cli.rs` renders every theme in a
  throwaway home and compares Zettlr's CSS with `desktop/tests/golden/zettlr/<name>.css`.
  A theme without a golden file still has to carry its own colours and mode.
  `desktop/tests/test_zettlr.py` checks the merge next to a user's own CSS. To draw Zettlr
  in a theme, run `tools/zettlr/render.sh <outdir> [--theme NAME]…`. It needs zettlr,
  weston and node. It renders in a throwaway home and a headless weston, so nothing
  reaches your desktop.

## The shell prompt

`bromigos shell prompt mehshell` chooses mehshell in the packaged zsh setup.
The choice lives in `~/.config/bromigos/shell.toml`. See the manual's
[shell page](../manual/src/shell.md) for setup and the other choices.

After a theme switch, `theme/hooks/theme-set.d/30-mehshell` runs
`live/tools/make-mehshell.py`. It reads the rendered `palette.json` and replaces
only the marked colour block in `~/.config/mehshell/config`. Other prompt options
stay in place. It clears the instant prompt cache so old colours cannot return.
mehshell reads the config again at each prompt.

The prompt's `brand = auto` uses a plain bromigOS wordmark when its packaged shell
defaults are present. Those defaults also export `MEHSHELL_BROMIGOS=1`. Explicit
`bromigos`, `os` and `none` choices override detection. No custom font glyph is needed.
The desktop's `bromigos shell` command forwards `doctor`, `preview` and `configure`
to mehshell's own validated commands. Preview output is printed, never evaluated.
User instructions are in [Shell and terminal](../manual/src/shell.md).

The generator uses the same colour roles for Wick, its eight colour variants,
Tidewell and Mire. Its reference files are in `live/tests/golden/mehshell/`.

## Zettlr

[Zettlr](https://www.zettlr.com) is a Markdown editor for notes. When it's installed,
every theme colours it: the editor, the file tree, the sidebar, the tabs, the toolbar,
the status bar, headings, links, code blocks, selections, scroll bars, pop-ups and the
other windows. It uses Geist Mono, the desktop's font, for text and code.

`bromigos theme set` renders `zettlr.css` from `theme/templates/zettlr.css.tpl`. The
theme-set hook `zettlr` (`desktop/lib/bromigos_zettlr.py`) then changes two files in
Zettlr's settings folder, `~/.config/Zettlr`:

- **`custom.css`.** This is Zettlr's own place for a user's CSS. The theme's colours go
  between two markers, `/* >>> bromigOS theme` and `/* <<< bromigOS theme */`.
  Everything outside the markers is yours and stays as it is. The first time, the block
  goes at the top, after any `@charset` and `@import` lines, so your own rules come after
  it. Its rules use `!important` to win over each of Zettlr's display themes, so a rule of
  yours needs `!important` too. If only one marker is there, the hook changes nothing and
  reports it.
- **`config.json`.** Only the `darkMode` key changes, to match the theme's `mode`. The
  hook leaves this file alone while Zettlr runs, because Zettlr would write its own
  settings back over it. It never creates the file either, so Zettlr's first-start setup
  still happens.

Zettlr reads `custom.css` when it starts, and it has no way to reload it from outside.
So a theme switch reaches Zettlr the next time you open it.

Zettlr's own setting **Automatically switch to dark mode** follows the system when Zettlr
is first installed. Then Zettlr follows the desktop's colour scheme, which bromigOS sets
to dark, and its `darkMode` follows that. The colours are the theme's either way. The
hook leaves that setting and every other one alone, including Zettlr's display theme and
font size.

If Zettlr is installed but hasn't run yet, the hook creates `~/.config/Zettlr/custom.css`,
so its first start is already in the theme's colours. A Flatpak Zettlr's folder,
`~/.var/app/com.zettlr.Zettlr/config/Zettlr`, gets the same treatment when it exists.

To stop bromigOS colouring Zettlr, switch the hook off with an empty file named
`~/.config/bromigos/hooks/theme-set.d/zettlr` ([Hooks](#hooks)). Then delete the block
from `custom.css`.

Settings › Default apps has a **Markdown notes** row, which offers Zettlr when it's
installed. bromigOS doesn't install Zettlr.
