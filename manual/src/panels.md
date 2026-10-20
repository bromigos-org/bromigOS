# Panels

Panels are the readouts on your desktop. They sit under your windows, on the left side of
your [primary monitor](glossary.md#primary-monitor) until you move them, and show live
readings: how busy your
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
| MEDIA | What's on the [den TV](themes-and-worlds.md#the-den-tv), now and next, and your media server's continue watching and recently added. | none | no; offered when you have a media server or a den TV channel |

The panels marked "no" are off until you add them: open edit mode, find one in the tray,
and click **Add to desktop**. Each one says on the panel itself what it needs before it
can show anything, such as a calendar's address or a sign-in.

## Use the panels

- **WORKBENCH.** Each project has buttons to open it in the editor, in a terminal, or in
  the file manager.
- **SHORTCUTS.** Click a row to run that key's action. Keys that move windows or
  workspaces only work from the keyboard.
- **CONNECTIONS.** Click a Wi-Fi network to join it.

### Storage names

To give a drive a shorter name, open **Settings › Widgets**, find **STORAGE**, and
open its **Settings…**. In **Drive display names**, enter one mount path and name per
line, such as `/mnt/Work = Work`. Clear an entry to show its mount path again.

Names appear at every widget size. Hover still shows the full mount path, and clicking
opens that folder. This changes the widget's text only; it does not rename the drive.

From a terminal, set the whole list with:

```bash
bromigos panels set storage display_names '/ = System' '/mnt/Work = Work'
```

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

   ![Edit mode: the panels framed on the desktop, NETWORK picked, and the tray with every panel on the right](images/edit-mode.webp)

3. Drag a panel to move it. It snaps into line with the others. Hold <kbd>Ctrl</kbd> to
   place it freely. To put it on another monitor, drag it over that monitor's edge.
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

### More than one monitor

Each panel can go on any monitor. Drag it across, or pick it and choose a monitor in the
tray's **Monitor** list. A panel knows its monitor even when you plug it into another
port. When you unplug a monitor, its panels move to your primary monitor for the time
being. They go back to their places when you plug it in again.

You can do it all from the keyboard. <kbd>Tab</kbd> picks the next panel, the arrow keys
move it (with <kbd>Shift</kbd>, 10 pixels at a time), <kbd>Ctrl</kbd> and an arrow
resizes it, and <kbd>H</kbd> hides it. <kbd>F6</kbd> moves to the tray and back.

Why not just hold <kbd>Alt</kbd> and drag? On bromigOS, <kbd>Alt</kbd> and a drag moves
windows, so it can't move panels too.

## Layouts

A layout is a ready-made set of panels, already sized and placed for you. Pick one and
your desktop changes at once. Each panel keeps its own settings, such as the weather's
place.

| Layout | What it shows |
|---|---|
| Made for your theme | The panels this theme's scene suits, placed around it. It comes first. |
| Minimal | SYSTEM, WEATHER and NOW PLAYING. |
| Developer | SYSTEM, WORKBENCH, GITHUB or GITLAB, CI & PRS, SHORTCUTS and UPDATES. |
| Homelab | Your homelab's LAB hologram, large, with ALERTS, LAB JOBS, STORAGE, NETWORK and GAME SERVERS. |
| Streamer | TWITCH, YOUTUBE, DISCORD, NOW PLAYING and a small SYSTEM. |
| Media | NOW PLAYING, MEDIA, SPOTIFY and YOUTUBE. |
| Gamer | GPU, SYSTEM, GAME SERVERS, DISCORD and NOW PLAYING. |
| Everything | Every panel that can show something, packed tidily. |

To pick one:

1. Open **Customize** (<kbd>Super</kbd>+<kbd>Ctrl</kbd>+<kbd>Shift</kbd>+<kbd>Space</kbd>)
   and choose the **Widgets** tab. The **Layouts** row is at the top.
2. Each card is your screen in miniature, with your theme's scene behind it. It shows
   where each panel would go. The dashed boxes are the parts of the scene a layout keeps
   clear.
3. Click a card, or its **Use this layout** button.
4. Changed your mind? Click **Undo**.

In edit mode, the tray's **Layouts…** button lists them too. There, <kbd>Ctrl</kbd>+<kbd>Z</kbd>
undoes one, and **Done** keeps it. In a terminal, `bromigos panels layouts` lists them,
and `bromigos panels layout apply homelab` applies one.

Layouts fit any screen, from a 1366×768 laptop to a 4K or ultrawide monitor. On a small
screen, panels come in smaller sizes. A layout never covers more than about a third of the
screen, so you can still see your scene. When a panel doesn't fit, or can't show anything
on your machine, the layout leaves it out and says why. For example, GITHUB needs you to
be signed in, and LAB needs a [homelab](homelab.md). Everything is the exception: it may
cover more, and it tells you when it does.

### Each theme has its own layout

Your scene is the point of your desktop, so each theme keeps the panels off its best
parts. The Wick keeps its screens, TVs and window clear. Tidewell keeps the waterline,
the lighthouse and the creatures' water clear. Mire keeps the Sleeper and Hollis clear.

Your desktop remembers a layout for each theme. When you switch theme, your panels switch
to the layout you last had on that theme. The first time, you get the layout made for
it. The colour themes (Cinder, Deepvein, Highwind, Lowtown, Rime, Sunder, Wick · Tidewell
and Wick · Mire) paint the Wick's den in other colours, so they share the Wick's layout. Switching between them
leaves your panels alone.

To use one layout on every theme, run `bromigos panels layout apply minimal
--all-themes`.

### Save your own

Arrange the panels the way you like, then choose **Save as layout…** in the edit-mode
tray. Or open **Customize › Widgets** and click **New layout…** beside **Layouts**.
Enter a name and, optionally, a description, then save. The form captures the current
arrangement on the screen it names. Your new layout joins the cards marked **yours**.

To update a saved layout, choose **Save changes…** on its card. The form names the
layout that will be replaced with your current arrangement. **Override…** does the
same for a ready-made preset, saving your own version. Packaged preset files stay
available on disk. The theme's own card offers **Save as new…**.

Saving does not apply the selected card first. Use **Use this layout**, arrange the
widgets, and then save changes if you want to start from that card. A new name that
matches an existing layout is rejected; use its save or override action instead.
These actions are also available from **Settings › Widgets › Layouts**.

From the terminal:

```sh
bromigos panels layout save "My desk"
bromigos panels layout save --replace my-desk
bromigos panels layout apply my-desk
```

The first command creates a layout, the second updates it, and the third puts it on
your desktop. Add `--monitor <name>` to choose a screen when saving.

### Tidy up

Panels on top of each other? Click **Tidy up** in edit mode's tray, in Customize's
Layouts row, or in **Settings › Widgets**. You can also run `bromigos panels tidy`. Tidy
up moves your panels so none covers another. It keeps them in the same order, and keeps
them off the scene where it can. **Undo** puts them back.

When you switch on a panel and there's no room left for it, bromigOS tells you: "No room
for GPU: hide something or try a smaller size". It never puts one panel on top of
another.

### Panels that fit what they show

Some panels show lists that grow and shrink, such as LAB, ALERTS and CI & PRs. These
panels take the height their content needs. A layout gives LAB room for your whole lab,
and ALERTS with four alerts is a short panel, not a big empty box. As the list changes,
the panel's frame follows it, inside the room it was given. It changes only now and then,
so it doesn't jump around.

When a panel has less room than its content needs, it shows less instead of cutting
anything off. LAB, for example, shows "34/36 UP" and only the services that are down.
Make it taller to see everything again.

### Making a panel bigger

When you make a panel bigger, it stays where it is. Panels in its way move down or to the
side. If they can't, the panel moves to free space, never onto the scene's screens or
window. If there's no room anywhere, nothing changes and bromigOS tells you: "No room to
make LAB 900 tall here: move or hide something".

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

Settings › Widgets also shows a small picture of where the panels sit. Its **Monitor for
every panel** puts them all on one monitor.

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

## Media

MEDIA is a remote for the [den TV](themes-and-worlds.md#the-den-tv): all three screens at
once, what each is showing and where the sound comes from. Click a screen's line to choose
it, then use the buttons to change its channel, turn its sound on or off, watch it full
screen, or open the channel guide. It comes in three sizes:

- **compact:** a line for each screen, and the buttons;
- **wide:** each screen with its poster and what's next;
- **large:** what you were part-way through on your server, and what's new, with posters.

Click something you were watching to open it in Jellyfin or Plex, which remember where you
were.

Its **Settings…** make a TV channel without editing a file. Choose a source and a library,
collection or playlist from your server, or paste a YouTube address. You can also choose
the den screen, the order, and a folder to keep YouTube videos in. For every other
channel, the form links to the
[channel guide](themes-and-worlds.md#the-channel-guide).

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

## Calendar releases

CALENDAR can add tracked TV episodes and film releases to your calendar. Open its
**Settings…** and turn on **Your media server's releases**. Sonarr or Radarr must be
connected in [Your homelab](homelab.md#media-requests).

The setting is `media = true` in `~/.config/bromigos/widgets/calendars.toml`. It adds
releases without replacing your other calendars. For the whole workflow, see
[Your media](media.md#put-releases-on-your-calendar).

To export the releases as calendar files for another app:

```bash
bromigos lab media calendar tv > ~/Downloads/tv-releases.ics
bromigos lab media calendar movies > ~/Downloads/film-releases.ics
```

These are copies of the feed at that moment. Export again to update them. `--past` and
`--future` set how many days to include. The panel reads fresh releases by itself.

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

1. **Connect the service, if asked.** GitHub, gitlab.com and Twitch need nothing:
   bromigOS has its own apps for them. Spotify, and a GitLab or GitHub server of your
   own, need an app of your own. The form says where to make it and what to paste. You
   do this once per service, and every panel for that service shares it.
2. **Sign in.** For GitHub, GitLab and Twitch, a short code appears. Type it on the page
   that opens, and approve. For Spotify, approve on Spotify's page; the form finishes by
   itself.

The sign-in is kept in your login keyring, never in a file. **Sign out** forgets it.

If you use the `gh` command and you're signed in to it, GITHUB uses that, and there's
nothing to do. GITLAB can also take a personal access token: **Paste a token…**.

### Several accounts

You can sign in to more than one account of a service. For example, gitlab.com and your
company's own GitLab, GitHub and a GitHub Enterprise server, or two Twitch accounts. One
panel shows them all.

1. In the panel's **Settings…**, click **Add another account…**.
2. Give it a short name, such as `work`. For GitLab and GitHub, give its server's address
   too, or leave it empty for the public site.
3. A server of your own needs its own app, so the form asks for its client ID. Then click
   **Sign in**, as for the first account.

With two accounts signed in, the panel merges their rows, newest first. Each row shows
which account it came from, such as `gitlab.com` or `work`. Each account has a tick box
in the form: untick it to leave that account out of this panel. **Remove…** signs an
account out and forgets it, after asking. SPOTIFY shows one account at a time: the first
one ticked.

From a terminal:

```bash
bromigos account login twitch
bromigos account status twitch
bromigos account logout twitch
bromigos account configure spotify client_id=YOUR_CLIENT_ID      # services without a bromigOS app

bromigos account add gitlab work base=https://git.example.org    # another account, on its own server
bromigos account configure gitlab --as work client_id=YOUR_APP_ID
bromigos account login gitlab --as work
bromigos account list                                            # every account, and who's signed in
bromigos account remove gitlab work
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
