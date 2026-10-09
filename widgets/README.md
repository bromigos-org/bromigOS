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

Each panel is its own layer-shell window on the *bottom* layer of the primary monitor.
That puts it above the animated background and below every window. A 100 ms heartbeat
drives the redraws. Redraws pause while windows cover the desktop on that monitor, but
sampling carries on cheaply, so graphs still have history when you come back.

The package installs:

- the code in `/usr/lib/bromigos/widgets/`;
- `/usr/bin/bromigos-widgets`;
- the default layout in `/usr/share/bromigos/widgets/layout.json`.

A user's own layout goes in `~/.config/bromigos/widgets/layout.json`.

## Commands

```bash
bromigos-widgets toggle <name>|all    # show or hide one panel, or all of them
bromigos-widgets show <name>|all      # show one or all; never hides
bromigos-widgets notes                # focus the notes panel for typing; Esc hands focus back
bromigos-widgets reload               # read layout.json again
bromigos-widgets stats                # print draw counts and coverage to the app's stderr
bromigos-widgets render <name> out.png    # draw one panel offscreen, with no window
```

`render` also takes a plugin's path, such as `plugins/x.py`, and `--ticks <n>`.

The keys are Super+W for all panels, Super+S, N, D, B and F for one each, Super+K for
shortcuts, and Alt+N to type in the notes. The full list is the manual's
[Keys](../manual/src/keys.md) page, which is generated from `keybinds.py`.

## Files

| File | What it does |
|---|---|
| `bromigos-widgets` | The app: one window per panel, the heartbeat, the control socket, hotplug recovery |
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

## Plugin health

`plugins.py` keeps each plugin panel isolated. An error is logged to
`~/.local/state/bromigos/widgets-plugins.log` and shown in that panel. After 5 errors in a
minute, or 5 slow draws in a row, the plugin is switched off until its file changes. A
health file, `$XDG_RUNTIME_DIR/bromigos-widgets-health.json`, is written every 2 seconds
with each plugin's status, errors and draw times.

## Tests

`check()` in `packaging/bromigos-widgets/PKGBUILD` compiles every file and checks the
launcher entries with `tools/launcher/check.py`. CI's `launcher.yml` runs the full
launcher check.
