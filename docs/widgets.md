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

A panel's key shows or hides it until you log out. To choose which panels start with
your session, use edit mode, Settings › Widgets or `bromigos panels show|hide <name>`.

To look at a panel without the desktop, draw it offscreen:

```bash
bromigos-widgets render <name> out.png
```

## Edit mode

Edit mode lets you arrange the panels on the desktop itself. To start it, do any of
these:

- press Super+Alt+W;
- right-click a panel (FIELD NOTES: its header);
- choose **Edit widgets** in the menu (Super+Space);
- click **Edit on the desktop** in Settings › Widgets;
- run `bromigos panels edit`.

The panels come up above your windows and keep updating. A frame and a name mark each
one, and the widget gallery opens beside them in a tray you can drag aside.

| To | Do this |
|---|---|
| Move a panel | Drag it. It snaps to an 8 px grid and to the other panels' edges, and a guide line shows what it lined up with. Hold Ctrl to place it freely. |
| Resize a panel | Drag a corner. Each panel has its own smallest and largest size. |
| Hide a panel | Click its ×, or pick it and press H. |
| Show a hidden panel | Flip its switch in the tray. It goes back where it was, or to a free spot if that's taken. **Add to desktop** always finds it a free spot. |
| Pick a panel | Click it, or press Tab and Shift+Tab. |
| Nudge the picked panel | The arrow keys move it 1 px, or 10 px with Shift. Ctrl and an arrow resizes it. |
| Move between the panels and the tray | F6 |
| Undo or redo | Ctrl+Z, Ctrl+Shift+Z, or the tray's buttons |
| Go back to bromigOS's layout | **Reset…** in the tray, then **Reset**. Ctrl+Z undoes it. |
| Save and leave | Esc, **Done**, or Super+Alt+W again |
| Leave without saving | **Cancel**. Everything goes back as it was. |

Saving writes `layout.json` (see [below](#place-the-panels)) with every panel's place,
size and whether it's on. A panel that a bigger monitor left off the screen comes onto it
when edit mode starts, so you can reach it.

Why not just Alt and a drag? Hyprland uses Alt+drag (or Super+drag) to move windows, and
catches the drag before a panel sees it. A panel also never learns that a key is held
while it doesn't have the keyboard. Edit mode takes the pointer and the keyboard for as
long as it's on, so a plain drag works.

The panels go on one monitor. The tray's **Monitor** list, shown when there's more than
one, moves them all to another. A panel can't sit on a different monitor from the rest.

## The widget gallery

The widget gallery lists every panel there is, including hidden ones. It's in edit
mode's tray and in Settings › Widgets. Its sections are:

- **On your desktop:** the panels that are on;
- **Built in:** bromigOS's panels that are off, and the homelab's;
- **Installed extensions:** panels from extensions you installed with `bromigos ext`;
- **Your own:** panels from your plugin folder.

Each card shows a picture of the panel, its name, what it shows, who made it and what it
reads. It has an on/off switch, **Add to desktop**, and **Settings…** for a panel with
settings of its own, such as the weather's place. Search finds a panel by any of those
words, and the category buttons narrow the list: System, Network, Homelab, Media, Notes
and Fun.

**Get more widgets** browses the community catalog, which `bromigos ext search --kind
widget` reads. Each entry shows its author, its licence, a link to its repository, and
whether it runs code. A widget always runs code. So **Install…** opens a terminal, where
`bromigos ext install` shows what the widget can do and asks you first.
[extensions.md](extensions.md) has the rules. **Uninstall** removes an installed one.

A panel tells the gallery about itself through a few class attributes. Writing your own
is in [plugins.md](plugins.md#what-the-gallery-shows).

From a terminal:

```bash
bromigos panels gallery           # every panel, with its words and where it sits
bromigos panels add weather       # turn one on, in a free spot
```

## Adding a widget

A new widget is one Python file. Where it goes says who it's for:

| For | Put the file in |
|---|---|
| bromigOS itself, built in | `widgets/plugins/<name>.py` in this repository. The package installs every file there. |
| Everyone, from the catalog | An extension (`bromigos ext new widget <name>`, [extensions.md](extensions.md)) |
| You alone | `~/.config/bromigos/plugins/widgets/<name>.py` |

The steps:

1. Write a `panels.Panel` subclass with `name` and `title`, and set `PANEL` to it.
   `tick()` reads the data every `interval` seconds, and `draw(cr, w, h)` paints it with
   the helpers in `widgets/draw.py`. Give each part a hover hint with `region()`.
2. Fill in what the gallery shows: `description`, `category`, `reads`, `min_size` and
   `max_size` ([plugins.md](plugins.md#what-the-gallery-shows)). Lay the panel out from
   the `w` and `h` that `draw()` gets, so any size in its range looks right.
3. Set `LAYOUT = {"width": …, "height": …, "visible": False}` if it shouldn't appear
   until someone switches it on. Without a position, it finds a free spot.
4. Read real data only. When there's nothing to read, say so in the panel. For pictures,
   give `demo.py` steady made-up readings for it.
5. Draw it offscreen with `bromigos-widgets render <name> out.png` and look at it at its
   smallest and largest sizes.

The panels pick the file up within 2 seconds. It appears in the widget gallery under its
category, with its own picture, and edit mode can place and size it. Nothing else needs
to change: no list to add it to, no key, no layout entry.

## Place the panels

The layout lives in `~/.config/bromigos/widgets/layout.json`. Edit mode, Settings and
`bromigos panels` write it for you. To edit it by hand, start from a copy of the
packaged default:

```bash
mkdir -p ~/.config/bromigos/widgets
cp /usr/share/bromigos/widgets/layout.json ~/.config/bromigos/widgets/
```

Your file replaces the default whole. Each panel's entry has `x`, `y`, `width`, `height`
and `visible`, plus that panel's own keys. Positions are in pixels from the top left of
the area under the bar. After you edit it, run `bromigos-widgets reload`.

Panel plugins and the homelab's panels find free space on their own unless your layout
places them. Once you move or switch one in edit mode, it gets an entry of its own.
[plugins.md](plugins.md) explains how to write a panel of your own.

Your `layout.json` can be a symbolic link, for example into a dotfiles repository. Every
writer replaces the file it points to in one step, and the link stays a link.
`bromigos panels reset` writes bromigOS's layout through the link instead of removing it.

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
