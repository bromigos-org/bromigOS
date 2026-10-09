# Panels (widgets)

The panels, which most people call widgets, are small dashboards on the desktop. They sit
above the animated background and below your windows, on the primary monitor. Each shows
real readings only, and every part you can hover over explains what it is and what a
click does.

This page covers what each panel shows and how to configure it. The manual's
[Panels](../manual/src/panels.md) page is the user's guide. The code is described in
[widgets/README.md](../widgets/README.md), and the package is `bromigos-widgets`.

<img src="images/panels-cinder.webp" width="600" alt="The panels in the Cinder colour
theme: CPU and memory, network traffic, disk usage, recent projects, the weather and a
list of shortcuts, in ember orange">

<!-- site:panels -->
## The panels

| Panel | Shows | On by default |
|---|---|---|
| `system` | CPU and threads, a load waterfall, memory, video memory, the GPU, uptime | Yes |
| `network` | The interface, a traffic scope, and a latency radar to the hosts you list | Yes |
| `storage` | The mounted filesystems and how full they are | Yes |
| `workbench` | Your recent Git repositories and most-visited folders | Yes |
| `notes` | Field notes, a notepad that saves as you type | Yes |
| `shortcuts` | Every key binding, read from Hyprland | Yes |
| `weather` | The forecast for a place you choose ([below](#weather)) | No |
| `connections` | Network connections, Wi-Fi and VPNs ([below](#connections)) | No |
| `lab` | Your homelab at a glance, and any panels you declare ([homelab.md](homelab.md)) | With `bromigos-homelab` and a configured homelab |

## Show or hide a panel

Each panel has a key. Super+W shows or hides them all. Super+S, Super+N, Super+D,
Super+B and Super+F toggle the system, network, storage, workbench and notes panels. The
manual's [Keys](../manual/src/keys.md) page has the full list.

From a terminal:

```bash
bromigos-widgets toggle <name>     # show or hide one panel, or all
bromigos-widgets show <name>       # show one panel, or all; never hides
```

`show` and `notes` start the panels first if they aren't running. The app launcher's
Desktop Panels entry runs `show all`.

To look at a panel without the desktop, draw it offscreen:

```bash
bromigos-widgets render <name> out.png
```

## Place the panels

The layout lives in `~/.config/bromigos/widgets/layout.json`. Start from a copy of the
packaged default:

```bash
mkdir -p ~/.config/bromigos/widgets
cp /usr/share/bromigos/widgets/layout.json ~/.config/bromigos/widgets/
```

Your file replaces the default whole. Each panel's entry has `x`, `y`, `width`, `height`
and `visible`, plus that panel's own keys. After you edit it, run `bromigos-widgets
reload`.

Panel plugins and the homelab's panels find free space on their own unless your layout
places them. [plugins.md](plugins.md) explains how to write a panel of your own.

## High contrast

With high contrast on ([accessibility.md](accessibility.md)), the panels take the theme's
high-contrast colours from `palette.json`, like everything else. They also draw their
plates opaque, their lines near solid, and their text without a glow. A plugin panel can
ask whether high contrast is on with `bromigos_theme.high_contrast()`.

## Weather

The weather panel shows:

- **now:** the temperature, the conditions in words, how it feels, humidity, wind, and
  rain in the last hour;
- **the next 24 hours:** temperature as a line and the chance of rain as bars;
- **the next three days:** conditions, low and high, and the chance of rain. Hover for
  sunrise and sunset.

The forecast comes from [Open-Meteo](https://open-meteo.com). It's free, needs no key,
and is licensed CC BY 4.0, which the header's hover credits. The panel fetches it every
10 minutes.

Nothing is fetched until you set a location. Put it in `~/.config/bromigos/weather.toml`,
or in the weather panel's entry in `layout.json`:

```toml
# ~/.config/bromigos/weather.toml
place = "San Diego"        # looked up once through Open-Meteo's geocoder
# lat = 32.72              # or give the coordinates instead
# lon = -117.16
name = "Home"              # the header's label; defaults to the place's name
units = "imperial"         # °F and mph; the default, "metric", is °C and km/h
```

Then turn the panel on by setting `"visible": true` on the `weather` entry in your
`layout.json`.

## Connections

The connections panel reads NetworkManager through `nmcli`. It shows:

- what's connected, with its name, kind and device;
- the Wi-Fi networks in reach, with signal strength and a lock for secured ones;
- your VPNs, including WireGuard;
- a switch for the Wi-Fi radio, in the header.

Click a Wi-Fi network to join it. A saved or open network connects straight away. A new
secured network opens `nmtui connect` in a terminal so you can type the password. Click a
VPN to bring it up or down.

The panel checks every 15 seconds. It says so when NetworkManager isn't running. To turn
it on, set `"visible": true` on the `connections` entry in your `layout.json`.
