# Accessibility

bromigOS has two accessibility settings. **Motion** sets how much the desktop moves:
full, reduced or still. **Contrast** sets how strongly its colours contrast: normal or
high. Both reach every part of the desktop that moves or draws in the theme's colours.

This page is for someone changing how the settings work or adding something that must
follow them. For using them, read the manual's
[Accessibility](../manual/src/accessibility.md) page.

![The Settings window's Accessibility page: Full, Reduced and Still motion, a high
contrast switch, and the theme measured against high contrast's
targets](images/settings-accessibility.webp)

## The settings file

Both settings live in `~/.config/bromigos/accessibility.toml`. An update never touches it.

```toml
motion = "reduced"     # "full" (the default), "reduced" or "still"
contrast = "high"      # "normal" (the default) or "high"
```

## Changing them

```text
bromigos accessibility                      the settings, and how the theme's colours measure
bromigos accessibility motion reduced       full, reduced or still
bromigos accessibility contrast high        normal or high
bromigos accessibility check [THEME]        a theme's colours against the targets
bromigos a11y …                             the same command, shorter
bromigos setup accessibility                the first run's two pages
```

`bromigos setup accessibility` also takes `--motion` and `--contrast` for an unattended
run. You can also use Settings › Accessibility, or the menu (Super+Space). The menu's
TOGGLE group has Reduced motion, Still background and High contrast, and SETUP has
Accessibility.

A change takes effect at once:

1. `bromigos accessibility` writes the file.
2. It renders the current theme again, because both settings are part of what
   `bromigos theme set` renders.
3. It tells the running parts of the desktop.

For contrast, it tells everything `theme set` tells. The bar restarts, and the terminal,
Hyprland, notifications, the live layer and the theme-set hooks are told. For motion, it
tells Hyprland, the live layer and GTK's `enable-animations`.

Outside a live session, nothing is told, and it says the change "takes effect at the next
login". `--no-reload` writes the setting and renders the theme but tells nothing. The live
layer also notices the file by itself within three seconds.

## Motion

### What each level changes

The live layer is the program that draws the animated background and the decks. A deck
is a full-screen holographic view you open with a key.

| What | Full | Reduced | Still |
|---|---|---|---|
| The live background | As designed | The same scene at 0.4 of real speed | One still frame |
| Parallax | Yes | No | No |
| Flicker, blinking, twinkling | Yes | Steady | Steady |
| Flashes | Yes | None | None |
| Rotation | Yes | None | None |
| Craft crossing the sky | Yes | None | None |
| One-off creatures on events | Yes | Yes, slower | None |
| The scanner | A sweeping beam | The schematic fades in | One frame |
| The unlock intercept | Tears, then the emblem draws itself | A crossfade | The finished card |
| A critical notification | Interference and a pulsing red edge | A steady red edge | As reduced |
| The screensaver | Turns and drifts | Slower, nothing turns | One moment, held |
| Decks left alone | Drift round | Hold still | Hold still |
| Hyprland's windows | Pop in, workspaces slide | Fade | No animation |
| GTK apps' animations | On | Off | Off |
| Letters typing in | A brief flash per letter | No flash | No flash |

Some of these need more detail:

- **Parallax** is the background's layers following the pointer.
- **Flicker and blinking** covers the den's screen grain, the emblem's flicker, stars,
  lamps, fireflies, an agent's "needs you" blink and a waking agent's eyes. Under reduced
  motion, lights hold their level. "Needs you" burns brighter in its signal colour instead
  of blinking.
- **Flashes** are lightning, the den's static bursts, rain bursts on a notification, and
  the wipe when you switch workspaces. Under reduced motion a storm still darkens the
  scene.
- **Rotation** covers the den's emblem and relay map and the screensaver's models.
- **The scanner** normally sweeps a beam every minute and on `scan`. Under reduced motion
  there's no beam and no periodic pass. `scan` fades the schematic in for a few seconds.
- **The intercept** plays when you unlock or sign in. At full motion it holds the screen,
  tears it, draws the ring, lights the flame, turns it, types the text, shows one black
  frame and cuts back to the desktop. Under reduced motion it crossfades from the frozen
  screen. The emblem fades in whole and doesn't turn, there's no black frame, and the card
  fades into the dark, which then lifts off the desktop in half a second. Under still
  motion, the finished card fades in over the frozen screen, holds, fades into the dark,
  and the dark lifts. At every setting, nothing of it is drawn over your windows while
  they show through.
- **A critical notification** at full motion shows brackets, a 150 ms interference band
  and a pulsing red edge. Under reduced motion it shows brackets and a steady red edge,
  faded in and out.
- **Decks** you drive still move as designed when you drag, zoom or fly to something.

### Worlds under reduced and still motion

A world is a theme whose wallpaper is a living scene, such as Mire or Tidewell. Worlds
keep their look and their life under reduced motion. Everything that shows a reading
still shows it, more slowly.

Under still motion, a world's picture is drawn again only when something it shows
changes, or once a minute. These changes count:

- an agent's state;
- your activity;
- VECTOR's state;
- the homelab's health;
- the weather's level, in quarters;
- the quarter hour;
- the moon's phase.

Each new frame is a cut. First the scene's clock moves on six seconds, simulated in its
usual steps but not drawn. So a creature that rose or went under is shown where it ended
up. A video loop holds the frame it was on. The live layer draws nothing in between, and
no frame timer runs, so a still background costs almost nothing.

### How it's built

- `live/live/motion.py` holds the modes and each renderer's clock. A clock takes real
  seconds and gives the scene's seconds.
- These read it: the den (`scene.py`), the worlds (`world.py`, `actors.py`,
  `fireflies.py`), the overlays (`overlays.py`) and the decks (`deckkit.py`,
  `drift_map.py`).
- The shaders take `u_calm`: `bg.frag`, `rain.glsl`, `space.glsl` and `world_layer.frag`.
- `live/app.py` runs the still frames. Every two seconds it asks the scene whether its
  picture changed.
- `config.py` merges the file's `motion` into the live config as `general.motion`. The
  older `general.reduced_motion = true` still means at least `reduced`.
- The theme's `hyprland.lua` carries `motion` and `contrast` for the default Hyprland
  config.
- `palette.json` carries `motion` for apps that animate, read with
  `bromigos_theme.motion()`.

### VECTOR

VECTOR is the desktop's AI assistant. His holograms and his avatar read the same setting.
It lives in the `vector` repository, in `holo/motion.py`, from `bromigos-vector` r32.

- Under reduced motion they turn at 0.4 of the pace, with no flicker, blinking, scan bands
  or glitch, and his movements are damped.
- Under still motion each window holds one frame. It's drawn again only when what it shows
  changes, and no frame timer runs.

A change of setting reaches them within a second.

### Not covered

The boot splash and the login screen don't follow motion. They're system files that a
user's setting can't reach.

## Contrast

High contrast is a transform of the theme's colours, not a theme of its own. So every
theme gets a high-contrast version, including a user's own themes and extensions' themes.

`bromigos theme set` resolves the theme's `colors.toml`, transforms the colours, and
renders every template and `palette.json` from the result. Everything that takes the
theme's colours follows:

- the bar, the launcher and menus, notifications and the on-screen display;
- the terminal, Neovim, tmux and btop;
- the lock screen;
- GTK and Qt apps;
- the panels (widgets), VECTOR and the live layer's decks.

### The targets

The targets are those of WCAG 2.1.

| Colours | On | Minimum |
|---|---|---|
| `text`, `soft`, `primary`, `warn`, `danger` | `background`, `panel`, `void` | 7:1 |
| `dim`, `muted`, `faint` | `background`, `panel`, `void` | 4.5:1 |
| `text`, `soft`, `primary` | `selection` | 4.5:1 |
| `selection` | `background`, `panel` | 3:1 |
| `danger_text` | `danger_surface` | 7:1 |
| `widgets.value`, `widgets.header` | `panel` | 7:1 |
| `holo.label` | `background` | 7:1 |
| `widgets.frame` | `panel` | 3:1 |
| `widgets.graph` | `widgets.track` | 3:1 |
| The terminal's foreground | its background | 7:1 |
| The terminal's colours 1 to 15 | its background | 4.5:1 |

7:1 is level AAA for text (WCAG 1.4.6). 3:1 is the target for interface parts
(WCAG 1.4.11). The `selection` row covers the selected row and inactive borders. The
terminal's colour 0 is its black, used as a surface, so it stays as dark as the
background.

### How the transform works

1. The surfaces move toward the theme's own end: darker on a dark theme, lighter on a
   light one, at OKLCH lightness × 0.45. The surfaces are `background`, `void`, `panel`,
   the warning and danger surfaces, the terminal's background and Qt's surfaces.
2. Each other colour moves in OKLCH lightness only, just far enough to meet its minimum
   against what it's drawn on.
3. A colour's hue never changes. Its chroma drops only where sRGB can't hold it.
4. A colour that already contrasts enough is left exactly as it was.

The colour maths is the [`palette`](https://docs.rs/palette) crate's: OKLCH, relative
luminance and contrast ratios. `core/crates/bromigos-core/src/accessibility.rs` holds the
roles and the targets.

Every shipped theme meets every target under high contrast. `bromigos accessibility check`
shows the numbers, and the tests check them. Under normal contrast the themes keep their
own colours. `check` shows where they fall short of high contrast's targets. Most often
that's the selection, which is a quiet highlight by design.

### Beyond the colours

The templates also see `a11y.contrast` (see [theming.md](theming.md)). Under high
contrast:

- the bar is opaque, with solid rules and no glow behind text;
- the launcher's layers are opaque, and its matched letters are underlined;
- notifications get a 2 px frame;
- the terminal gets an opaque background;
- Hyprland draws 3 px solid borders;
- the panels draw opaque plates, with near-solid rules and no glow
  (`bromigos_theme.high_contrast()`).

`palette.json` and `bromigos theme set --json` report how the colours measure, in
`contrast`, with `mode`, `ok` and the `lowest` pair. The schema is in
[core/README.md](../core/README.md).

### Not covered

These keep the Wick's colours under high contrast:

- the worlds' painted art, which is a scene rather than text;
- the boot splash and the login screen;
- hyprlock, the fallback lock screen.

## Tests

- **`core/crates/bromigos-core/src/accessibility.rs` and `tests/theme.rs`** cover the
  settings file, the transform on dark and light themes, and every shipped theme against
  every target with its hues kept. They also check the rendered outputs, and that normal
  contrast is left alone.
- **`core/crates/bromigos/tests/accessibility_cli.rs`** covers the command, `a11y`,
  `check`, setup's section and answers. It also checks that nothing is told without a
  session.
- **`live/tests/test_motion.py`** covers the modes, the clocks, the lights, the fireflies,
  the settings file and `palette.json`. Run it with
  `cd live && python -m unittest discover -s tests`. The package's check runs it too.
- **`live/tests/offscreen_motion.py`** renders the den, Mire, the intercept, a critical
  notification and the screensaver headless. It uses EGL, in a throwaway home with fixed
  readings, and never opens a window. It checks what a viewer sees at 30 frames a second:
  - Full motion animates, reduced less, and still not at all, with identical pixels until
    what it shows changes.
  - Under reduced and still motion, no tile of a 4×4 grid changes by 0.10 or more in
    relative luminance from one frame to the next. That's WCAG 2.3.1's step for a general
    flash. Lightning and the intercept's cut are included, and full motion shows the check
    would catch them.
  - Moving the pointer moves nothing.
  - The intercept doesn't tear.

  It needs a GPU, so it runs by hand: `python3 live/tests/offscreen_motion.py [--out DIR]`.
  DIR gets sample frames.
