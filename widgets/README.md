# widgets/

This folder is the code for the desktop's panels (widgets), packaged as
`bromigos-widgets`. The panels are small dashboards that show this machine at a glance.
Each panel draws real readings only, and has a hover hint on every part.

What each panel shows and how to configure it is in [docs/widgets.md](../docs/widgets.md).
Writing a panel of your own is in [docs/plugins.md](../docs/plugins.md). This file is
about the code.

## How it runs

The panels are one GTK3 process, written in Python with GtkLayerShell, Cairo, Pango and
psutil. Hyprland starts it at login, from the `hyprland.start` autostart in the default
`hyprland.lua`.

Each panel is its own layer-shell window on the *bottom* layer of its monitor: the one
its `output` in layout.json names (found by make, model and serial with
`arrange.find_output()`), else the primary. That puts it above the animated background and
below every window. A 100 ms heartbeat drives the redraws. Redraws pause while windows
cover the desktop on a panel's monitor, but sampling carries on cheaply, so graphs still
have history when you come back.

On a hotplug (Hyprland's `monitoradded` and `monitorremoved` events, and GTK's), `App.fall_back()`
puts each panel back on its monitor, or on the primary while its monitor is gone. A panel
standing in on the primary remembers its own place (`fell` and `home`), and
`arrange.kept_place()` saves that place rather than the stand-in one.

The package installs:

- the code in `/usr/lib/bromigos/widgets/`;
- `/usr/bin/bromigos-widgets`;
- the default layout in `/usr/share/bromigos/widgets/layout.json`;
- the ready-made layouts in `/usr/share/bromigos/widgets/layouts/`.

A user's own layout goes in `~/.config/bromigos/widgets/layout.json`.

## Commands

```bash
bromigos-widgets toggle <name>|all    # show or hide one panel, or hide/restore the visible set
bromigos-widgets show <name>|all      # show one or all; never hides
bromigos-widgets add <name>           # show one in a free spot, and save it there
bromigos-widgets edit [on|done|cancel]    # edit mode; no word: on, or done when it's on
bromigos-widgets gallery [--previews <dir>]   # every panel there is, as JSON
bromigos-widgets notes                # focus the notes panel for typing; Esc hands focus back
bromigos-widgets reload               # read layout.json again
bromigos-widgets stats                # print draw counts and coverage to the app's stderr
bromigos-widgets render <name> out.png    # draw one panel offscreen, with no window
```

`render` also takes a plugin's path, such as `plugins/x.py`, `--ticks <n>`, and
`--size <w>x<h>` to draw it at another size, in that size class's layout.

Super+W hides the visible panels and restores exactly that set. The other keys are
Super+Alt+W for edit mode, Super+S, N, D, B and F for one each, Super+K for shortcuts, and Alt+N to type in the notes. The full list is the manual's
[Keys](../manual/src/keys.md) page, which is generated from `keybinds.py`.

## Files

| File | What it does |
|---|---|
| `bromigos-widgets` | The app: one window per panel, the heartbeat, the control socket, hotplug recovery |
| `editmode.py` | Edit mode: the canvas over the panels, the drags, the keyboard, and the tray with the widget gallery |
| `arrange.py` | Edit mode's geometry and file, with no GTK: snapping, free space, undo, reading and writing `layout.json` |
| `layouts.py` | Layouts, with no GTK: reading them, each theme's keep-clear areas, fitting a layout to a screen, Tidy up, and the layout remembered per theme |
| `layouts/` | The ready-made layouts (Minimal, Developer, Homelab, Streamer, Media, Gamer, Everything), installed to `/usr/share/bromigos/widgets/layouts/` |
| `widget_settings.py` | A widget's own settings: its declared fields, and their values in `~/.config/bromigos/widgets/<name>.toml` |
| `gallery.py` | The widget gallery's list: every panel, what it shows, who made it, what it reads, and its pictures |
| `panels.py` | The built-in panels |
| `plugins.py` | Loads plugin panels, from users and from `bromigos-homelab`, and finds them free space |
| `sources.py` | The readers: psutil, NVML, temperatures, Wi-Fi signal, ping, storage |
| `draw.py` | Cairo and Pango helpers in the house style: frames, brackets, gauges, bars |
| `keybinds.py` | Reads the key bindings for the shortcuts panel and for the shortcut search on Super+Shift+K |
| `keybinds-dump.lua` | Reads the bindings from Hyprland's Lua config when Hyprland isn't running |
| `demo.py` | Made-up, steady readings for pictures drawn offscreen |
| `layout.json` | The default positions and sizes, which panels are visible, and each panel's own keys |
| `applications/` | The app launcher's entries: Desktop Panels and Field Notes |

The control socket is `$XDG_RUNTIME_DIR/bromigos-widgets.sock`, a datagram socket.

`keybinds.py` reads the bindings live from Hyprland through `hyprctl`, using the list that
`hypr/bromigos/keys.lua` keeps. When Hyprland isn't running, it falls back to the Lua
config files through `keybinds-dump.lua`. Its `EXEC` and `DISPATCH` tables describe every
binding in words. `tools/docs/generate.py` uses it to build the manual's key table, so a
binding added to the defaults needs a row there.

`demo.py` swaps the readers in `sources.py` for steady, made-up values. Import it before
`panels` when you draw a picture. Then a picture never shows the machine it was drawn on,
and two pictures drawn a minute apart match. The theme switcher's previews use it.

## The panels

| Panel | Reads | Every |
|---|---|---|
| SYSTEM | CPU per core, memory, the GPU through NVML, temperatures, uptime | 2 s |
| NETWORK | Throughput, Wi-Fi signal, and a latency radar to the hosts in `layout.json` | 1 s |
| STORAGE | Mounts and how full they are | 30 s |
| WORKBENCH | Recent Git repositories by local activity, and zoxide's most-used folders | 60 s |
| FIELD NOTES | `~/.local/share/bromigos/notes.md`, saved as you type | On edit |
| SHORTCUTS | Every binding, from `keybinds.py` | 5 s |
| WEATHER | Open-Meteo's forecast for a configured place | 10 min |
| CONNECTIONS | NetworkManager through `nmcli` | 15 s |
| LAB | The homelab's snapshot, from `bromigos-homelab` | 20 s |

WEATHER and CONNECTIONS are off by default. LAB comes with `bromigos-homelab`.
WORKBENCH's rows open Neovim, a terminal or the file manager. SYSTEM's GPU readings come
from NVIDIA's NVML library, so they need an NVIDIA GPU.

### The built-in plugin panels

More built-in panels are files in `plugins/`, one each, loaded like any plugin and off
until someone adds them. They share `plugins/_kit.py`: settings through
`widget_settings.py`, pollers that stop while a panel isn't drawn, empty states, buttons
and pictures. The ones that sign in to an account use `lib/bromigos_account.py`.

| Panel | File | Reads | Every (while shown) |
|---|---|---|---|
| GPU | `gpu.py` | NVML (NVIDIA), or `/sys/class/drm` (AMD, Intel); processes through NVML | 2 s; processes 4 s |
| UPDATES | `updates.py` | `bromigos update --check --json`, cached in `~/.cache/bromigos/widgets/` | 3 h, and when pacman's database changes |
| VECTOR | `vector.py` | His state file, his audit log, `gh search prs` | 2 s; PRs 5 min |
| CI & PRS | `ci.py` | One `gh api graphql` query | 3 min |
| GITHUB | `github.py` | GitHub's REST and GraphQL APIs, with ETags | 4 min; the graph hourly |
| GITLAB | `gitlab.py` | GitLab's API (`/api/v4`) | 4 min |
| CALENDAR | `calendars.py` | ICS addresses, files and folders (python-icalendar, dateutil) | 15 min; files on change |
| NOW PLAYING | `nowplaying.py` | MPRIS through Playerctl; cava for the visualizer | 1 s |
| SPOTIFY | `spotify.py` | Spotify's Web API, and MPRIS when the app is here | 5 s playing, 20 s paused |
| TWITCH | `twitch.py` | Helix; the anonymous chat when large | 1 min |
| YOUTUBE | `youtube.py` | The channel's feed and `/live` page | 15 min; live 10 min |
| DISCORD | `discord.py` | The invite and server widget APIs | 3 min |

The homelab's own (LAB JOBS, SOLAR, GAME SERVERS, ALERTS) are `*_panels.py` generators in
`homelab/widgets/`, each offered only when a source provides what it reads.

Name a plugin file unlike any Python module (`calendars.py`, not `calendar.py`). Its
folder is on the import path, and the tests put it first.

## Plugin health

`plugins.py` keeps each plugin panel isolated. An error is logged to
`~/.local/state/bromigos/widgets-plugins.log` and shown in that panel. After 5 errors in a
minute, or 5 slow draws in a row, the plugin is switched off until its file changes. A
health file, `$XDG_RUNTIME_DIR/bromigos-widgets-health.json`, is written every 2 seconds
with each plugin's status, errors and draw times.

## Edit mode

Edit mode (`editmode.py`) moves every panel to the *top* layer, above windows, and puts
a transparent surface, a canvas, on each monitor's *overlay* layer above them. A canvas
covers its monitor under the bar, so its coordinates are the layout's for the panels on
that monitor. The canvases take the pointer, and the one on the focused monitor holds the
tray and the keyboard. They draw the frames, handles and guides, and move a panel by
changing its layer-shell margins. A drag works in the desktop's layout (each canvas's
origin plus the pointer), so when the pointer crosses onto another monitor the panel's
window moves to that output (`App.move_panel()`). The panels keep their 100 ms heartbeat, and keep
drawing even when windows would cover them. Leaving puts them back on the bottom layer.

The tray is a GTK widget inside the main canvas. Its cards draw each panel live, small, every
2 seconds. Done calls `App.save_layout()`, which writes through `arrange.write()`. The
health file carries `editing` and every panel's place and size (`panels`), which the
end-to-end test reads.

## Tests

`check()` in `packaging/bromigos-widgets/PKGBUILD` compiles every file, runs the unit
tests in `tests/` (snapping, free space, undo, each panel's monitor and its migration,
`layout.json` written through a symlink, and every layout fitted to five screens on each
scene, none overlapping), and checks the launcher entries with `tools/launcher/check.py`.
`desktop/tests/e2e_widgets_nested.py` drives edit mode in a nested Hyprland, with a
virtual keyboard and pointer, on one output and then two. CI's `launcher.yml` runs the full
launcher check.

The MEDIA panel's **GUIDE** button opens the standalone **Den TV** app
(`bromigos-tv-guide`), including while the live background is off. Its settings form
opens that same app. [The media guide](../manual/src/media.md#make-channels-for-the-den-tv)
explains channels and their shared controls.
