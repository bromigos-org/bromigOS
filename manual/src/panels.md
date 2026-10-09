# Panels

Panels are the readouts on your desktop. They sit under your windows, on the left side of
your [primary monitor](glossary.md#primary-monitor), and show live readings: how busy your
machine is, your network, your disks, your projects and your notes. Every reading is real.
Hover over any part of a panel to see what it is.

bromigOS's own files sometimes call panels *widgets*. **Settings › Widgets** is where you
choose them.

## Show and hide panels

| To | Press |
|---|---|
| show or hide all the panels | <kbd>Super</kbd>+<kbd>W</kbd> |
| show or hide one panel | its key, in the table below |

## The panels

| Panel | What it shows | Key | Shown at first |
|---|---|---|---|
| SYSTEM | Processor use for each core, memory, the graphics card, temperatures and how long the machine has been on. | <kbd>Super</kbd>+<kbd>S</kbd> | yes |
| NETWORK | Traffic in and out, Wi-Fi signal, and a radar of how quickly your router and the internet answer. | <kbd>Super</kbd>+<kbd>N</kbd> | yes |
| STORAGE | Your disks, and how full each one is. | <kbd>Super</kbd>+<kbd>D</kbd> | yes |
| WORKBENCH | The code projects and folders you use most. | <kbd>Super</kbd>+<kbd>B</kbd> | yes |
| FIELD NOTES | Your notes. | <kbd>Super</kbd>+<kbd>F</kbd> | yes |
| SHORTCUTS | Every key on the desktop, your own included. | <kbd>Super</kbd>+<kbd>K</kbd> | yes |
| WEATHER | The weather now, for the next 24 hours, and for three days. | none | no |
| CONNECTIONS | What's connected, Wi-Fi networks in reach, VPNs, and a switch for Wi-Fi. | none | no |
| LAB | Your homelab at a glance. | none | when you've [connected a homelab](homelab.md) |

## Use the panels

- **WORKBENCH.** Each project has buttons to open it in the editor, in a terminal, or in
  the file manager.
- **SHORTCUTS.** Click a row to run that key's action. Keys that move windows or
  workspaces only work from the keyboard.
- **CONNECTIONS.** Click a Wi-Fi network to join it.

### Field notes

FIELD NOTES is a notepad on your desktop. It saves as you type.

1. Press <kbd>Alt</kbd>+<kbd>N</kbd>. The panel is ready for typing.
2. Type your note.
3. Press <kbd>Esc</kbd> to go back to your windows.

To add one line without leaving what you're doing, press
<kbd>Alt</kbd>+<kbd>Shift</kbd>+<kbd>N</kbd>, type it, and press <kbd>Enter</kbd>. It's
added to your notes with the time.

Your notes are a plain text file, `~/.local/share/bromigos/notes.md`.

## Choose and place panels

Open **Settings › Widgets** and turn each panel on or off. The page shows a small picture
of where the panels sit, and chooses which monitor they use.

To move or resize a panel, use a terminal:

```bash
bromigos panels                   # which panels are on, and where
bromigos panels show weather      # turn one on
bromigos panels hide connections  # turn one off
bromigos panels move notes 514 16 # move one, in pixels from the top-left
bromigos panels size notes 470 400 # resize one: width and height in pixels
```

## Set up the weather

The WEATHER panel fetches nothing until you say where you are.

1. Open **Settings › Widgets**.
2. Under **Weather**, type your town in **Place**, and choose the **Units**.
3. Under **Panels**, turn the weather panel on.

Or from a terminal:

```bash
bromigos panels weather place "San Diego"
bromigos panels weather units imperial
bromigos panels show weather
```

The forecast comes from Open-Meteo, a free weather service.

## Panels of your own

- **For your homelab:** a gauge, a chart, a status light or a table needs no code. You
  describe it in a settings file. See
  [Your own panels](homelab.md#your-own-panels-without-code).
- **With code:** a panel can be a small Python file in
  `~/.config/bromigos/plugins/widgets/`, or an [extension](extensions.md). The developer
  docs' [plugins.md](https://github.com/bromigos-org/bromigOS/blob/main/docs/plugins.md)
  shows how.

## Where the settings go

Your layout is `~/.config/bromigos/widgets/layout.json`, and the weather's place is in
`~/.config/bromigos/weather.toml`. Settings writes both for you. If you edit them by hand,
run `bromigos widgets reload`.
