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
| move, resize and choose panels | <kbd>Super</kbd>+<kbd>Alt</kbd>+<kbd>W</kbd> (edit mode, below) |

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
| GPU | The graphics card: how busy it is, its memory, temperature and power, and which programs use it. | none | no |
| UPDATES | Updates waiting, and a button to install them. | none | no |
| VECTOR | What VECTOR is doing, his emergency switch, what he did lately, and his pull requests. | none | no |
| CI & PRS | Whether your projects' builds pass, and pull requests waiting for you. | none | no |
| GITHUB | Your GitHub notifications, reviews, repositories and stars. | none | no |
| GITLAB | Your GitLab merge requests, to-dos and pipelines. | none | no |
| CALENDAR | Today's events and the days ahead, from your calendars. | none | no |
| NOW PLAYING | The song or video playing, with its cover and the controls. | none | no |
| SPOTIFY | What your Spotify account plays on any device, and what's next. | none | no |
| TWITCH | Your Twitch channel, and the channels you follow that are live. | none | no |
| YOUTUBE | A channel's newest videos, and whether it's live. | none | no |
| DISCORD | Who's online in a Discord server. | none | no |
| LAB JOBS, SOLAR, GAME SERVERS, ALERTS | Your homelab's job queue, solar power, game servers and alerts. | none | offered when your homelab has them |

The panels marked "no" are off until you add them: open edit mode, find one in the tray,
and click **Add to desktop**. Each one says on the panel itself what it needs before it
can show anything, such as a calendar's address or a sign-in.

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

## Arrange the panels

Edit mode lets you move, resize and choose panels right on your desktop.

1. Press <kbd>Super</kbd>+<kbd>Alt</kbd>+<kbd>W</kbd>, or right-click any panel. You can
   also choose **Edit widgets** in the menu (<kbd>Super</kbd>+<kbd>Space</kbd>).
2. The panels come up above your windows, each with a frame. A tray with every panel
   opens on the right.
3. Drag a panel to move it. It snaps into line with the others. Hold <kbd>Ctrl</kbd> to
   place it freely.
4. Drag a corner to make it bigger or smaller.
5. Click a panel's × to hide it. To bring one back, flip its switch in the tray, or click
   **Add to desktop** to put it in a free spot.
6. Press <kbd>Esc</kbd> or click **Done** to save. **Cancel** puts everything back.

Bigger panels show more, not just the same thing larger. A large SYSTEM panel adds the
busiest programs and every temperature, and a wide WEATHER panel shows the hours ahead.
Each panel's card in the tray has buttons for its sizes, such as **Compact** and
**Large**.

<kbd>Ctrl</kbd>+<kbd>Z</kbd> undoes a change. **Reset…** in the tray puts every panel
back where bromigOS first had it.

You can do it all from the keyboard. <kbd>Tab</kbd> picks the next panel, the arrow keys
move it (with <kbd>Shift</kbd>, 10 pixels at a time), <kbd>Ctrl</kbd> and an arrow
resizes it, and <kbd>H</kbd> hides it. <kbd>F6</kbd> moves to the tray and back.

Why not just hold <kbd>Alt</kbd> and drag? On bromigOS, <kbd>Alt</kbd> and a drag moves
windows, so it can't move panels too.

## Choose panels

The tray in edit mode, the **Widgets** tab of [Customize](themes-and-worlds.md#customize)
and **Settings › Widgets** all show the widget gallery: every panel there is, on or off. Each one says what it shows, who made it and what it reads.
Type in the search box, or pick a category, to find one.

**Get more widgets**, in Settings › Widgets, lists widgets other people made, from the
bromigOS catalog. Each shows who made it, its licence and a link to its code. A widget is
a small program, so **Install…** opens a terminal that tells you what it can do and asks
before it installs. **Uninstall** removes it again.

To install a widget someone shared as a link, click **Install from URL…** in Settings ›
Widgets and paste the link. Settings shows what the widget reads and what it can do before
anything is installed, and installs it only when you click **Install**.

Settings › Widgets also shows a small picture of where the panels sit, and chooses which
monitor they use.

You can also choose and place panels from a terminal:

```bash
bromigos panels                   # which panels are on, and where
bromigos panels edit              # start edit mode on the desktop
bromigos panels show weather      # turn one on
bromigos panels add weather       # turn one on, in a free spot
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

## A panel's own settings

Many panels have settings of their own, such as which calendars to show or which Discord
server to watch. Click **Settings…** on the panel's card, in edit mode's tray or in
**Settings › Widgets**. The panel changes as soon as you save.

From a terminal:

```bash
bromigos panels settings calendars            # what it has, and the values now
bromigos panels set discord invite abc123     # change one
```

## Panels that need an account

GITHUB, GITLAB, SPOTIFY and TWITCH show your own account, so they need you to sign in
once. Open the panel's **Settings…** and click **Sign in**.

1. **Connect the service.** Each service needs an app of your own on its developer site.
   The form says where to make it and what to paste. You do this once per service, and
   every panel for that service shares it.
2. **Sign in.** For GitHub, GitLab and Twitch, a short code appears. Type it on the page
   that opens, and approve. For Spotify, approve on Spotify's page; the form finishes by
   itself.

The sign-in is kept in your login keyring, never in a file. **Sign out** forgets it.

If you use the `gh` command and you're signed in to it, GITHUB uses that, and there's
nothing to do. GITLAB can also take a personal access token: **Paste a token…**.

From a terminal:

```bash
bromigos account configure twitch client_id=YOUR_CLIENT_ID
bromigos account login twitch
bromigos account status twitch
bromigos account logout twitch
```

The developer docs' [widgets.md](https://github.com/bromigos-org/bromigOS/blob/main/docs/widgets.md#the-built-in-widgets)
say, for each panel, where to make the app.

## Panels of your own

- **For your homelab:** a gauge, a chart, a status light or a table needs no code. You
  describe it in a settings file. See
  [Your own panels](homelab.md#your-own-panels-without-code).
- **With code:** a panel can be a small Python file in
  `~/.config/bromigos/plugins/widgets/`, or an [extension](extensions.md).
  [Make your own widget](make-a-widget.md) walks you through it. The developer
  docs' [plugins.md](https://github.com/bromigos-org/bromigOS/blob/main/docs/plugins.md)
  shows how.

## Where the settings go

Your layout is `~/.config/bromigos/widgets/layout.json`, and the weather's place is in
`~/.config/bromigos/weather.toml`. A panel's own settings are in
`~/.config/bromigos/widgets/<name>.toml`, and the services' client IDs in
`~/.config/bromigos/accounts.toml`. Settings writes them all for you. If you edit them by hand,
run `bromigos widgets reload`.
