# Settings

Settings is one window for the desktop's settings: displays, sound, network, power, the
theme, shortcuts, VECTOR and more. Each page is a front end to a small `bromigos` command,
so the window never keeps its own copy of a rule. Any package, extension or user can add a
page.

This page is for someone adding a page or changing the window. For using it, read the
manual's [Settings](../manual/src/settings.md) page. The audit that shaped the current
layout is [settings-audit.md](settings-audit.md).

![The Settings window: a sidebar of pages grouped under System and Desktop, and the Idle
and lock page with its presets and timers](images/settings-idle.webp)

## Opening it

Press Super+, or choose SETUP › Settings… in the menu, or click the gear on the bar. From a
terminal:

```text
bromigos settings [PAGE[#SETTING]]        open it, on a page or one setting (sound#output)
bromigos settings --list [--json]         every page: its group, order, file and settings
bromigos settings --search WORDS [--json] search all settings and print the results
bromigos settings --render OUT.png [--page PAGE] [--size WxH] [--search WORDS] [--advanced]
bromigos settings --audit [--page PAGE]   build a page and print what it lacks
```

A second `bromigos settings` raises the window that's already open.

- `--render` draws a page to a PNG and exits. It needs a Wayland display, so the tests use
  a headless compositor.
- `--audit` reports a control without a hover hint, a setting the search lists that no
  row has, and a row wider than the window.

The window is GTK 4 and libadwaita. It ships in `bromigos-desktop`, installed in
`/usr/lib/bromigos/settings/`. Its colours come from the theme in force: libadwaita's
colour variables are set from `palette.json` through `bromigos_theme`. The house style
goes on top, with square corners, 1 px rules, Geist Mono and tracked capital headings.

## How the window works

### Groups

The sidebar groups its pages: System, Desktop, VECTOR & AI, Lab, Personal and About. The
list is `registry.GROUPS`. A page names its `group`. A page that doesn't name one goes
where `registry.DEFAULT_GROUP` says, or else under Desktop. That covers pages written
before groups existed and pages from other packages.

### Search

Search covers every setting on every page. Each page declares its settings in
`Page.entries`, with a name, synonyms and the section it sits in. Sections that other
modules add are indexed too. The index is `bromigos_settings/search.py`.

- Words match by prefix, and every word must match.
- A table of synonyms widens a word. "dnd" finds Do not disturb, "mic" the input device,
  and "wireless" Wi-Fi.
- A match in a title beats a keyword. A keyword beats a word in a page's summary or
  introduction, which are sentences, so "dark" finds the themes before a screen that
  goes dark.
- A result says where it is, such as System › Sound › Input.
- Choosing a result opens its page on that row, focused and lit for a moment.

### One layout for every page

Every page starts with a header. It holds the title, a short explanation, a link to the
manual's page and **Reset to defaults**. Below the header come groups of rows. Each row has
a label, a hint line and its control.

Some pages have nothing with a bromigOS default, such as a Wi-Fi network or a paired
device. There, the Reset button is greyed out and its hover says why.

### Hover hints

Every control, row and button says what it is and what it does when you hover over it.
The audit fails a page that misses one.

### Changes apply at once, with Undo

A change runs its command straight away. A toast says what changed and offers Undo, and
Ctrl+Z undoes the last change. Each page says where it differs:

- Displays waits for Apply, then asks "Keep these settings?" for 15 seconds.
- Anything that needs sudo opens a terminal that shows the command
  (`bromigos terminal --hold`).

### Advanced

Each row's `⋯` button opens a line under it. The line names the file and key the row
writes, and the command it runs, with a Copy button.

### Keys

| Keys | What they do |
|---|---|
| Type anything, or Ctrl+F | Search |
| Down | Move into the results |
| Enter | Open the first result |
| Esc | Clear the search |
| Ctrl+PgUp, Ctrl+PgDn | The previous or next page |
| Ctrl+1 to Ctrl+6 | The first page of each group |
| Ctrl+Z | Undo the last change |
| F1 | Open the page's part of the manual (below) |
| Ctrl+W | Close the window |

F1, a page's manual link and About's open the manual installed on the machine
(`bromigos-manual`), so it matches the machine's version and works offline. Without it,
they open the one published next to the packages, then the source on GitHub
([update.md](update.md#the-manual)).

Tab and the arrow keys move through every control. The groups use Ctrl and digits because
Alt and digits switch workspaces in bromigOS.

### Theme changes

When the theme changes, an open window restyles at once. It watches `palette.json` and
also checks every two seconds. A page that draws its own colours gets a call through
`ctx.on_restyle`.

### Sizes

The window opens at 85% of the monitor, at most 1280×860. That fits a 1366×768 screen
under the bar. Below 720 px wide, the sidebar and the page show one at a time, with a back
button between them. On a big screen the content is clamped at 1000 px wide.

## The pages bromigOS ships

| Group | id | Page | Command behind it |
|---|---|---|---|
| System | `displays` | [Displays](#displays) | `bromigos display` |
| | `sound` | [Sound](#sound) | `bromigos sound`, `mute`, `scene` |
| | `network` | [Network](#network) | `bromigos net` |
| | `bluetooth` | [Bluetooth](#bluetooth) | `bromigos bluetooth` |
| | `power` | [Power](#power) | `bromigos power` |
| | `input` | [Keyboard & input](#keyboard-and-input) | `bromigos setup input` |
| | `peripherals` | [Peripherals](#peripherals) | `bromigos peripheral` |
| | `datetime` | [Date & time](#date-and-time) | `bromigos clock` |
| | `updates` | [Updates & recovery](#updates-and-recovery) | `bromigos update`, `channel`, `rollback`, `boot` |
| Desktop | `idle` | [Idle & lock](#idle-and-lock) | `bromigos idle` |
| | `theme` | [Theme](#theme) | `bromigos theme` |
| | `live` | [Live layer & holograms](#live-layer-and-holograms) | `bromigos anim`, `scene`, `keys` |
| | `den-tv` | [Den TV](#den-tv) | `bromigos-live tv`, `lib/bromigos_tvconfig.py` |
| | `widgets` | [Widgets](#widgets) | `bromigos panels` |
| | `notifications` | [Notifications](#notifications) | `bromigos notifications` |
| | `shortcuts` | [Shortcuts](#shortcuts) | `bromigos keys` |
| | `accessibility` | [Accessibility](#accessibility) | `bromigos accessibility` |
| | `default-apps` | [Default apps](#default-apps) | `bromigos defaults`, `webapp` |
| | `startup` | [Startup](#startup) | `bromigos startup` |
| | `extensions` | [Extensions](#extensions) | `bromigos ext` |
| VECTOR & AI | `vector` | [VECTOR](#vector) | `bromigos-holo`, `bromigos memory`, `keys`, `target` |
| | `targets` | [Creation targets](#creation-targets) | `bromigos target` |
| Lab | `lab` | [Lab](#lab) | `bromigos lab` |
| Personal | `account` | [Account](#account) | `bromigos profile`, `avatar` |
| About | `about` | [About](#about) | `bromigos about` |

### Displays

The page shows each monitor Hyprland runs:

- its resolution and refresh rate, from the modes it offers;
- its scale, with the one its pixel density suggests marked;
- its orientation, whether it's on, and which one is primary.

The primary monitor is where the live layer, the panels (widgets) and VECTOR appear. The
arrangement view draws the displays as they sit. Drag one to move it, and it snaps to the
others' edges. The arrow keys nudge it.

Changes wait for Apply, then go together. They're written as the same `bromigos.monitors`
block that `bromigos setup monitors` keeps in your `hyprland.lua`, and either replaces the
other's. Hyprland reloads the safe way, and the live monitors are checked afterwards.

Then "Keep these display settings?" counts down 15 seconds. A screen that went dark can't
answer, so if nobody keeps the change, `bromigos display`'s own watchdog puts the old
block back. The watchdog runs on its own, so this works even if Settings has closed.

Reset removes the block. Every display then runs at its preferred mode, at the scale its
density gives, placed automatically.

From a terminal:

```bash
bromigos display apply --output DP-1 --mode 2560x1440@144 --scale 1.25
bromigos display keep          # or: bromigos display revert
```

A scale that Hyprland would round is refused, and every file is put back.

### Sound

`bromigos sound` talks to PipeWire's pulse server through `pactl`. The page has:

- the output and input device, which playing apps follow;
- the port, such as line out or headphones on one card;
- each device's volume, from 0 to 150%, and its mute;
- each app that's playing, with its own volume, mute and output.

It also has the desktop's sounds. The one mute is `bromigos mute`, Super+Shift+M, which
silences the theme's sound cues and VECTOR's voice together. The cues have an on/off switch
(`bromigos anim sounds`) and a volume (`bromigos scene set sounds.volume`), plus Test.

While it's shown, the page reads PipeWire again every few seconds, so the volume keys and
other mixers show up. Reset turns the cues on at their default volume. Devices and their
volumes have no bromigOS default.

### Network

`bromigos net` talks to NetworkManager through `nmcli -t`.

- The Wi-Fi switch turns the radio on and off.
- The network in use shows its signal, address, gateway and DNS. It has Disconnect, which
  Undo reverses, and Forget….
- Networks in reach are listed once each, strongest first, with a lock on secured ones.
- A saved or open network joins at once.
- A new secured network asks for its password in a dialog.
- "Join another network…" handles hidden networks.
- Enterprise (802.1X) and WEP networks open `nm-connection-editor` from More settings.
- Each saved network has an autoconnect switch. Wired ports show their address.
- Each VPN and WireGuard connection gets a switch.
- The CONNECTIONS panel switch runs `bromigos net panel on|off`, which shows or hides that
  panel.

The password never appears on a command line. The page passes it to
`bromigos net connect SSID --password-stdin` on stdin. The command hands it to
NetworkManager in a file only you can read, and deletes the file afterwards. A wrong
password leaves nothing saved.

### Bluetooth

`bromigos bluetooth` talks to bluez through `bluetoothctl`, one command at a time, and to
`rfkill`.

- The power switch lifts an rfkill soft block first. A hardware switch can't be
  overridden, and the page says so.
- "Visible to devices nearby" makes the machine discoverable. bluez turns that off again
  after three minutes.
- Paired devices show their kind, connection and battery. Each has Connect or Disconnect,
  which Undo reverses, and Forget…, which asks first.
- Scan looks for devices in pairing mode for 8 seconds. Pair pairs, trusts and connects.

A device that asks for a PIN or passkey needs an agent. The page says so and opens
`bluetoothctl` in a terminal. There you type `pair <MAC>` and answer the code.

### Power

`bromigos power` has the power profile and batteries, the lid and sleep.

- The power profile is a three-way switch: Power saver, Balanced and Performance. It
  offers what power-profiles-daemon offers. Without the daemon, the page says why and
  offers `bromigos hw setup` in a terminal.
- Each battery shows its charge, what it's doing, the time left at the current draw, and
  its health. Health compares the full charge with the design capacity, and counts cycles.
  The charger and devices' own batteries, such as a mouse's, are listed too.
- On a laptop, "The lid" chooses what closing it does on battery, plugged in and docked.
  That's logind's setting for the whole machine. It's written to
  `/etc/systemd/logind.conf.d/50-bromigos-lid.conf` through pkexec, so it asks for your
  password.
- Sleep links to the suspend timer on Idle & lock. It says whether hibernation is set up,
  and has Suspend now, which asks first.

Reset sets Balanced and puts the lid back to logind's defaults.

### Keyboard and input

The page drives `bromigos setup input`, with its `--json`, `--unset`, `--reset` and
`--layouts` options.

- **Keyboard.** The layout, which you can search, and its variant. Optionally a second
  layout and the keys that switch between them.
- **Key repeat.** The rate and the delay, with a box to try them in.
- **Caps Lock.** It can stay Caps Lock, or become Escape or Ctrl, swap with Escape, or do
  nothing. This edits only its own part of `kb_options`.
- **Num Lock** at start.
- **Mouse.** Speed, acceleration, natural scrolling, left-handed, scroll speed, and which
  window gets the keys.
- **Touchpad.** Tap to click, natural scrolling, off while typing, how a click is read,
  middle click, drag lock and scroll speed. With no touchpad connected, the page says so.

Everything goes into `~/.config/bromigos/input.toml` and a marked block of your
`hyprland.lua`, followed by one verified reload. Sliders save once they stop moving. Reset
removes the block.

### Peripherals

This page lists `bromigos peripheral`'s optional modules. Each has an On switch, its
device, what its lighting follows, its dial, and its keys with what each runs. The
lighting follows VECTOR or the theme (`bromigos peripheral follow`). The page also has
Refresh and a link to `peripherals.toml`.

The first time a module needs packages or a group, turning it on runs in a terminal,
where sudo asks for your password. After that it's one click, with Undo. See
[peripherals.md](peripherals.md).

### Date and time

`bromigos clock` sets network time and the time zone through systemd's timedated. The zone
list is searchable, and the change may ask for your password. The page's clock ticks in
the chosen zone.

The bar's clock can be 24-hour, show seconds, and show the date. A preview shows what the
bar will read. The choice is kept in `~/.config/bromigos/waybar/settings.jsonc`, which your
bar config includes first. waybar lets the earliest include win. A new user's config
already includes it. For an older config, `bromigos clock hook` adds the one line.

Reset sets bromigOS's clock: 24-hour, with seconds and no date.

### Updates and recovery

- **The channel.** Switching opens a terminal running `bromigos update --channel NAME`,
  because it needs sudo.
- **Update now** opens a terminal running `bromigos update`. It needs sudo or a security
  key, and pacman's prompts need a terminal to answer in.
- **The last update.**
- **What's waiting**, from `bromigos update --check`: packages with their old and new
  versions, migrations, and restarts with a Restart button. Check again reads it anew.
- **Snapshots.** How updates are snapshotted, with Set up… or Allow… when needed, and the
  updates that can be undone, with Roll back… (`bromigos update --rollback`).
- **The boot menu's theme**, from `bromigos boot theme status`. Switching it opens a
  terminal, because it needs root. See [boot.md](boot.md). On a `bromigos` too old to have
  `bromigos boot`, the row says so.

### Idle and lock

The page has each timer as a switch and a slider, lock before sleep, and the doze of the
worlds' creatures. It also has the presets, stay awake (1 h, 2 h, until off), "Try the
screensaver now", the policy in plain words with its warnings, and the files. Reset applies
the default preset. The policy and the command are described in [idle.md](idle.md).

### Theme

The page shows every theme as a picture of the desktop wearing it. These are the theme
switcher's cards and previews, from `lib/bromigos_themecards.py`.

- A click wears a theme (`bromigos theme set`). A spinner shows while it renders, then a
  toast offers Undo.
- The catalog's themes follow the installed ones.
- The theme in force shows its tagline, its palette, and what moves in its world and what
  drives it, read from `world.toml`. For the den, it shows the parts you can switch.
- Rows below cover the live background (`bromigos live on|off`), the wallpaper, the
  theme's sounds and Accessibility.
- The wallpaper row steps to the previous or next den, or picks a variant
  (`bromigos-wallpaper`).
- The sounds row mutes the theme's cues (`bromigos live mute`). `bromigos mute` silences
  VECTOR's voice too.
- Where a peripheral module with lighting is on, a row makes the keyboard's lighting
  follow the theme (`bromigos peripheral follow`).
- "Get more" searches the catalog, takes a Git URL, or makes your own from the theme in
  force (`bromigos theme new`).

The page follows the theme. A switch made anywhere else marks the new one and redraws the
rest. Themes are described in [theming.md](theming.md).

### Live layer and holograms

- The live background on or off until the next login, which is also Super+Shift+B.
- Every animation switch, grouped into background and events (`bromigos anim`).
- The theme's world: drawn or not, and its sounds, with a link to the creatures' doze on
  Idle & lock.
- The screensaver's content, a gas giant or a relay station, and "Try the screensaver
  now".
- The codec's calls: critical notifications and the homelab's alerts, at most N an hour.
- The frame rates.
- The decks on their keys. Turning one off unbinds its key, and turning it on puts the key
  back (`bromigos keys`).

`bromigos scene` handles the live layer's settings that aren't on/off animations. It
writes them into `~/.config/bromigos/live/overrides.toml` and keeps everything else in
that file. Reset puts every animation and setting back, but leaves keys to the Shortcuts
page.

### Den TV

Settings holds only the den TV's playback controls: `tv.enabled`, `tv.max_playing` and
`tv.cover_opacity`, plus `tv.hover_hint` for the floating controls. They use `bromigos scene` and the live overrides file. Cover opacity
is the window-opacity threshold that pauses a covered silent screen; it does not fade
the video. **Open Den TV…** launches `bromigos-tv-guide`.

The channel guide is a standalone GTK4/libadwaita application, `org.bromigos.DenTV`, in
`desktop/settings/bromigos_tvguide.py`. It reuses the house-style toolkit for rows,
commands, toasts, theme watching and sandbox renders, with no Settings sidebar. Its
launcher entry is **Den TV**. Super+Alt+G, `bromigos-live tv guide`, the TV hover hint's
**GUIDE** button and the MEDIA panel all open it.

The guide, media TUI, CLI and VECTOR share `lib/bromigos_tvchannels.py`. Its `Store`
serializes edits and uses `bromigos_tvconfig.py` to keep comments and other tables,
check the result, and write atomically through symlinks. A change asks the running live
layer to reload; its config watcher is the fallback. Neither rebuilds the background.
The guide reads posters and now/next from the den's cache. New channels fetch contents
in a worker thread. [The manual](../manual/src/themes-and-worlds.md#the-channel-guide)
explains its controls; [Your media](../manual/src/media.md#make-channels-for-the-den-tv)
covers the shared CLI and terminal tab.

### Widgets

`bromigos panels` manages the desktop panels (widgets). The page has:

- a small drawing of where each panel sits, and **Edit on the desktop**, which starts
  [edit mode](widgets.md#edit-mode);
- the monitor, where empty means the primary;
- the [widget gallery](widgets.md#the-widget-gallery): every panel with a picture, what
  it shows, who made it and what it reads, a switch, **Add to desktop**, and search and
  categories;
- **Get more widgets**, the community catalog's widgets, which install in a terminal;
- the weather panel's place, units and label.

A change writes your `~/.config/bromigos/widgets/layout.json` or `weather.toml`, and the
running panels reload at once. The first change copies bromigOS's layout into yours,
keeping every key. Reset removes both files, or writes bromigOS's layout through
`layout.json` when it's a link. See [widgets.md](widgets.md).

### Notifications

`bromigos notifications` drives dunst.

- Do not disturb holds notifications back until you turn it off, and shows how many are
  waiting.
- A small screen picks the corner they appear in, and the gap from the edge.
- Sliders set how long low, normal and critical notifications stay. Zero means until
  dismissed.
- Every app seen lately gets Show, Quiet or Hide. Quiet sets low urgency, and Hide sends
  them straight to the history.
- Send a test, and Clear history, which asks first.

The page keeps its choices in `~/.config/dunst/dunstrc.d/80-settings.conf`, which loads
before your own `99-mine.conf`. dunst reloads it at once. Reset removes the file.

### Shortcuts

The page lists every key by section, as the SHORTCUTS panel does
(`bromigos keys list --all --json`). Each key has Change…, which opens the "press the new
shortcut" window.

- Your own shortcuts have Change…, Put back for a moved default, and Remove.
- The defaults you turned off can be put back.
- Bind something new opens the picker.
- Reset… puts bromigOS's keys back.
- Every change shows a toast with Undo (`bromigos keys undo`).
- A change that would leave the menu or the terminal without a key asks "Do it anyway".

The picker and how it saves are described in
[desktop.md](desktop.md#shortcuts-you-set-by-pressing-the-keys).

### Accessibility

The page has the motion setting (Full, Reduced or Still) and a high contrast switch. It
also measures the theme against high contrast's targets, as designed and with high
contrast on, and lists the pairs of colours that fall short. Reset sets Full motion and
normal contrast. See [accessibility.md](accessibility.md).

### Default apps

`bromigos defaults` sets which app opens links, folders, plain text, Markdown notes,
pictures, videos, music, PDFs and mailto: links. There's one dropdown per kind, and each sets every file type
of its kind at once with xdg-mime.

The terminal and file manager that bromigOS's keys start are `bromigos.apps`, written in a
marked block of your `hyprland.lua` and saved the safe way. The terminal is also set as
`$TERMINAL` and listed first in `xdg-terminals.list`.

Your web apps (`bromigos webapp`) can be removed, added from the ready list, or added as any
site. Reset puts the terminal and file manager back to kitty and pcmanfm. Which app opens a
file has no bromigOS default, so Reset leaves it.

### Startup

`bromigos startup` shows what starts at login.

- bromigOS's own programs, such as the bar, the panels, the idle policy and the live
  layer, are read from the defaults and can't be changed here.
- Yours are `bromigos.autostart`, kept in a marked block and run after bromigOS's own. Add
  one as an app or a command line.
- bromigOS doesn't run XDG autostart entries. They're listed so you can add one as yours.
- Remembered windows (`bromigos windows`): the app classes whose floating windows go back
  where they were, the "every floating window" switch, what's remembered now with Forget,
  and a restart of `bromigos-windows` so it reads `windows.toml` again.

### Extensions

The page lists what's installed from Git, each with an on/off switch and Remove. It shows
the updates waiting (`bromigos ext update --all --check`) and the catalogs, which you can
search.

The rows are the same as the extensions window's (`bromigos extensions`, also in the app
launcher). Both come from `lib/bromigos_extlist.py`. A theme installs at once, with Undo.
Anything that runs code, and any update, opens a terminal running the command shown. That
terminal shows the extension's permissions or changes, and you answer yes there. See
[extensions.md](extensions.md).

### VECTOR

VECTOR is the desktop's AI assistant. The page reads his state without starting him.

- **His brain.** The model and endpoint from his `vector.toml [llm]`, what answers now, and
  why the other places don't (`bromigos target`). Change… opens `bromigos setup vector` in a
  terminal.
- **His voice.** His own mute (`bromigos-holo mute`, which never starts him), automatic or
  a pinned voice, and conversation mode. The hints say that pinning a voice or starting a
  conversation starts him.
- **His keys**, from `bromigos keys`, each with Change… and Undo.
- **What he remembers** (`bromigos memory`). Conversation and note counts, Export…, and
  Clear… for each. A clear is archived in `~/.local/state/bromigos/vector-archive/`, so
  Undo brings it back. A running VECTOR keeps his database open throughout.
- **His notes in Gnosis.** When `homelab.toml` has a `gnosis` source with both tokens,
  his notes live there, and the row says so. Clear… lists them with the read token,
  archives them, then deletes each with the write token. It clears any notes left in the
  local store too. If the gate doesn't answer, nothing changes. Undo files them again as
  they were written, without fact extraction. Another plugin's store is left to that
  plugin, and the row says so.

#### The emergency switch

One switch turns VECTOR on or off. It reads the switch's own markers,
`~/.local/state/bromigos/vector-switch/off` and
`$XDG_RUNTIME_DIR/bromigos-vector-switch/off`, so it shows the truth even while he's
stopped or hung.

Flipping it off runs `bromigos-holo off` at once. His running commands, his answer and his
speech stop. Flipping it on only opens a confirmation, whose default answer is Cancel. The
switch stays off unless you choose yes, which runs `bromigos-holo on`. There is no other
way in:

- no application or window action, since GTK exports those on D-Bus;
- no command-line flag;
- no `bromigos settings vector#…` link that clicks anything;
- no URL handler and no file the page watches;
- nothing a render, Reset or a search result activates, since a result only focuses its
  row.

While he's on, VECTOR can launch apps and open files and URLs, but he can't click. While
he's off, his tools refuse even that. So a flip and a confirm are the gate.
`desktop/tests/test_vector_guard.py` fails if any other code calls it. The nested
end-to-end run, `e2e_settings_nested.py --only vector`, drives the switch through off,
Enter and Cancel in the dialog, and yes.

The same switch is on the bar, as a power mark that turns into a red VECTOR OFF, and on
**Super+Ctrl+Escape**. The key asks before it switches him back on.

### Creation targets

Each service shows what it uses now and why the other places don't answer, in the row
itself. The services are images, image edits, cutouts, video loops, 3D models, and
VECTOR's voice, hearing and brain.

- A dropdown puts the homelab, this machine or the cloud first for that service
  (`bromigos target … --only`).
- The cloud asks first, because it spends credits.
- Undo restores the service's previous order.
- The page also has Probe now, the common order, the setup questions, a link to
  `targets.toml`, Reset (`bromigos target reset`), and a link to the Lab page for the
  homelab's models.

See [targets.md](targets.md).

### Lab

This page needs `bromigos-homelab`. It shows:

- the homelab's status, as every card of `bromigos lab status --json`;
- GPUs and models, with a button to unload what ComfyUI holds;
- the model catalog's planner, when it's installed;
- recent jobs, with buttons to open the result or cancel;
- the doctor's findings with their fixes;
- where AI runs.

The dashboard and the Lab deck are a click away. See [lab.md](lab.md). **Find my lab…**
sits beside each **Connect…** button. It runs `bromigos lab connect --find` in a terminal,
which asks before it reads anything ([homelab.md](homelab.md#find-my-lab)).

### Account

- Your name, full name, pronouns, aliases and forms of address (`bromigos profile`), with
  Undo, and what VECTOR calls you.
- Your picture (`bromigos avatar`). It's a 256 px square in `~/.face`, which the login
  screen shows through `~/.face.icon`.
- Who can see your profile. `profile.toml` is a plain file. When it sits in a Git
  repository you track, such as your dotfiles, the page says so and names the repository
  and its remote. Dotfiles are often public, so the page points private values at the
  private overlay (`bromigos private`). The overlay's `operator:` section seeds the profile.
  Edit… opens it when it exists.

There's nothing to reset on this page.

### About

- The version, channel, last full update and kernel.
- The hardware, from `bromigos hw`: CPU, memory, GPUs and driver, the machine and the disk.
- bromigOS's packages and what it's built on, with versions.
- Licences. The code's is MIT OR Apache-2.0. The brand, art, fonts, icons and models made
  in a homelab have their own terms ([ASSETS.md](ASSETS.md)). Each package's licence
  comes from pacman.
- Links to the manual and the source.
- Copy system info copies the output of `bromigos about text`.

## The commands behind the pages

A page asks a command for its data and runs the command to change anything. It keeps no
copy of the command's logic.

The newer commands are small Python programs in `bromigos-desktop`. Each lives in
`desktop/bin/bromigos-<name>` and installs to `/usr/lib/bromigos/bin`, where the router
finds it as `bromigos <name>`. They share one shape, from `lib/bromigos_cli.py`:

- `bromigos <name> [status] --json` prints the whole state.
- A verb, such as `bromigos sound volume output 40 --json`, prints the state after it,
  with `ok` and `said`.
- A refusal prints `{"ok": false, "error": …}` and exits with status 1.

Each wraps the established tool for its job and finds that tool on `PATH`. That's how the
tests give it stand-ins.

| Command | Wraps | Writes |
|---|---|---|
| `bromigos display` | `hyprctl`, `Hyprland --verify-config` | the monitors block of `hyprland.lua`, `monitors.toml` |
| `bromigos sound` | `pactl` | PipeWire's state |
| `bromigos scene` | nothing | `~/.config/bromigos/live/overrides.toml` |
| `bromigos net` | `nmcli` | NetworkManager's connections |
| `bromigos bluetooth` | `bluetoothctl`, `rfkill` | bluez's devices |
| `bromigos power` | `powerprofilesctl`, sysfs, `pkexec` | the profile, the lid's logind drop-in |
| `bromigos setup input` | `Hyprland --verify-config`, `hyprctl` | `input.toml`, the input block of `hyprland.lua` |
| `bromigos clock` | `timedatectl` | timedated, `~/.config/bromigos/waybar/settings.jsonc` |
| `bromigos notifications` | `dunstctl`, `notify-send` | `~/.config/dunst/dunstrc.d/80-settings.conf` |
| `bromigos defaults` | `xdg-mime` | `mimeapps.list`, a block of `hyprland.lua`, `xdg-terminals.list` |
| `bromigos startup` | `bromigos windows` | a block of `hyprland.lua`, `windows.toml` |
| `bromigos panels` | `bromigos-widgets reload` | `~/.config/bromigos/widgets/layout.json`, `weather.toml` |
| `bromigos memory` | `sqlite3` | VECTOR's chat log and memory, archived first |
| `bromigos about` | `pacman`, `bromigos hw`, `bromigos channel` | nothing |
| `bromigos avatar` | Pillow | `~/.face`, `~/.face.icon` |

A trial of `bromigos display` keeps its state in `~/.local/state/bromigos/display/`. Each
command's flags are listed by `bromigos <name> --help` and in the manual's
[Commands](../manual/src/commands.md) page.

## Adding a page

A page is a Python module in one of the page folders. It defines `PAGE`, or `PAGES` for a
list. A module can also, or instead, define `SECTION` or `SECTIONS`. A section is a group
of rows added to another package's page. That lets the package that owns a feature add its
part of a page without editing the page's file.

### Where pages are read from

| Folder | For |
|---|---|
| `/usr/lib/bromigos/settings/pages/` | bromigOS's pages, and any package's (a package adds `pages/<id>.py`) |
| `$BROMIGOS_SETTINGS_PAGES` | folders separated by colons, for development and tests |
| `~/.local/share/bromigos/ext/active/settings/` | installed extensions' pages |
| `~/.config/bromigos/plugins/settings/` | the user's own pages |

The folders are read in that order.

- A page whose `id` was seen already replaces the earlier one. So a user can replace a
  packaged page.
- Files whose names start with `_` are skipped.
- A module that fails to import, or defines no page or section, is skipped. `--list` names
  it, and so does a line under the sidebar, with the reasons in its hover. It never stops
  the window.
- If a page's `build` raises an error, the page shows the error instead of its content.
  The same goes for a section.

### An example page

```python
# ~/.config/bromigos/plugins/settings/nightlight.py
from bromigos_settings import Entry, Page


def build(ctx):
    page = ctx.page()                     # the header: title, intro, Reset to defaults
    page.set_reset(lambda: ctx.change(["bromigos", "nightlight", "off", "--json"], "Night light off"),
                   what="The night light off.")
    g = ctx.group(page, "Night light", "Warmer colours after sunset.")
    ctx.switch_row(g, "Night light", "From sunset to sunrise", key="on",
                   hint="Turns the night light on or off (bromigos nightlight on|off)",
                   on_toggle=lambda on: ctx.change(["bromigos", "nightlight", "on" if on else "off", "--json"],
                                                   f"Night light {'on' if on else 'off'}",
                                                   undo=["bromigos", "nightlight", "off" if on else "on", "--json"]),
                   advanced={"file": "~/.config/bromigos/nightlight.toml", "key": "enabled",
                             "runs": "bromigos nightlight on|off"})
    return page


PAGE = Page(id="nightlight", title="Night light", group="desktop", order=70, icon="weather-clear-night-symbolic",
            summary="warmer at night", intro="Warmer colours after sunset, easier on the eyes.",
            entries=[Entry("on", "Night light", ["blue light", "warm", "redshift"])], build=build)
```

### The `Page` fields

`Page` is defined in `bromigos_settings/registry.py`.

| Field | What it is |
|---|---|
| `id` | A short, unique, lower-case name. `bromigos settings <id>` opens it. |
| `title` | The name in the sidebar and the header. |
| `build(ctx)` | Returns the page's widget from `ctx.page()`. It's called the first time the page is shown. |
| `group` | `system`, `desktop`, `vector`, `lab`, `personal` or `about`. |
| `order` | The page's place in its group. Leave gaps. |
| `icon` | A symbolic icon name, or several. The first one the icon theme has is used. |
| `summary` | The second line of the sidebar row. |
| `intro` | The explanation under the page's title. It defaults to the summary. |
| `entries` | `Entry(key, title, keywords, section)` for each setting, for the search. |
| `keywords` | More words the search matches for the page itself. |
| `docs` | The manual page that explains it, such as `settings.md#sound`. F1 opens it. |
| `refresh(widget)` | Optional. It's called each time the page is shown again. |

An entry's `key` matches the row built with the same `key=`. That's the row a search
result opens.

bromigOS's own pages use these orders:

- System: displays 10, sound 20, network 30, Bluetooth 40, power 50, input 60,
  peripherals 70, date and time 80, updates 90.
- Desktop: idle 10, theme 20, live 22, widgets 24, notifications 26, shortcuts 30,
  accessibility 40, default apps 50, startup 55, extensions 60.
- VECTOR & AI: VECTOR 10, targets 50.
- Lab: lab 10.

### Sections

`Section(page, id, title, build(ctx, page_box), order, entries, page_title, group)` adds a
group of rows to the page named `page`, after the page's own rows. If no such page is
installed, a page is made for it, titled `page_title`.

### The `ctx` helpers

`ctx` is defined in `bromigos_settings/context.py`. It has the house-style pieces and the
plumbing.

| Helper | What it gives you |
|---|---|
| `ctx.page(intro)` | The page and its header. It has `add`, `clear`, `set_reset` and `set_intro`. |
| `ctx.group(page, TITLE, description, hint, key)` | A group of rows, its title in capitals. |
| `ctx.row(group, title, subtitle, hint, buttons, icon, activate, key, advanced, control)` | A plain row. More than two buttons wrap. |
| `ctx.switch_row`, `ctx.combo_row`, `ctx.scale_row`, `ctx.entry_row` | Rows whose control applies a change. |
| `ctx.dropdown`, `ctx.toggle_group`, `ctx.button` | Controls for the end of a row. |
| `advanced={"file", "key", "runs", "note"}` | Any row's Advanced line. |
| `ctx.change(argv, said, undo, done, failed)` | Runs a `--json` change and toasts `said`, with Undo. |
| `ctx.note`, `ctx.failed`, `ctx.loading` | A note or warning row, a failed read, or a spinner. |
| `ctx.confirm`, `ctx.choose_file` | A question with Cancel as the default, or a file chooser. |
| `ctx.hint(widget, text)` | The hover hint. Give every control one. |
| `ctx.run`, `ctx.json` | Run a command without blocking the window. |
| `ctx.json_now(argv)` | A quick `--json` read, waited for. |
| `ctx.has_command("keys")` | Whether `bromigos keys` exists. |
| `ctx.launch`, `ctx.terminal`, `ctx.open_file`, `ctx.open_url` | Start something detached, in a terminal, in the editor or in the browser. |
| `ctx.toast`, `ctx.open_page`, `ctx.colors`, `ctx.on_restyle` | A toast, another page, the theme's colours, and a call when they change. |

The rows that apply a change each have `set_quiet(value)`. It shows a value without acting
on it. `ctx.change`'s `undo` is an argv or a callable, and Ctrl+Z runs it too.

### The rules a page keeps

- Real data only. Ask the `bromigos` commands' `--json` instead of copying their logic.
- A hover hint on every control.
- A change applies at once, with Undo when it can be undone.
- Reset to defaults where bromigOS has defaults.
- Each row's Advanced line says what it writes.
- Slow reads run in the background (`ctx.json`), so the window never stalls.
- Nothing that needs sudo runs without a terminal. Open one that shows the command.

## Tests

### Unit tests

```bash
cd desktop
PYTHONPATH=lib python -m unittest discover -s tests
```

These cover:

- the registry: groups, order, replacing, sections, and broken files skipped;
- the search index (`test_settings_search.py`): prefixes, synonyms, every word, and where
  a result sits;
- that every packaged page imports, and `--list` and `--search` without a display;
- the Theme page's reading of `world.toml`;
- each command against stand-ins: `test_display`, `test_sound`, `test_net`,
  `test_bluetooth`, `test_power`, `test_input`, `test_clock`, `test_notifications`,
  `test_defaults`, `test_startup`, `test_panels`, `test_memory`, `test_about`,
  `test_avatar` and `test_extlist`;
- VECTOR's guard (`test_vector_guard.py`);
- the standalone Den TV app (`test_den_tv_guide.py`): drawn in a headless weston of its own against a
  stand-in Jellyfin, with Add channel and the show picker, and no control without a hint.
  The nested den TV test drives it as a user would (`den_tv_guide_driver.py`, from
  `e2e_tv_nested.py`).

The stand-ins live in `desktop/tests/fixtures/bin/`. They include `hyprctl`, `pactl`,
`nmcli`, `bluetoothctl`, `powerprofilesctl`, `timedatectl`, `dunstctl`, `xdg-mime`,
`pacman` and `bromigos-holo`. There's also a `bromigos` that answers for built-ins, one
file each in `fixtures/builtins/`. The stand-ins keep their state in a temporary folder
(`fixture.py`) and log what they were asked. `cmdtest.py` runs a command in a throwaway
home with the stand-ins first on `PATH`.

### Offscreen renders

```text
tools/settings/render.sh OUTDIR [--page P]… [--fixtures] [--audit] [--size WxH]
                         [--search WORDS] [--advanced] [THEME…]
```

This draws the window offscreen, one PNG per theme and page. It runs a headless weston
with its own runtime folder, a throwaway home and no D-Bus, so nothing reaches the desktop
you're on. `bromigos session` is stubbed out, so nothing a page launches can find your
session.

- `--fixtures` puts the stand-ins first, as a made-up laptop with its own sysfs, apps and
  pacman log. Built-ins without a stand-in fall through to this checkout's `bromigos`.
- `--audit` writes each page's audit to `OUTDIR/audit.jsonl`.
- `--interact` drives Idle & lock as a user would (`tools/settings/interact.py`).
- `--previews DIR` gives the Theme page the previews from an earlier
  `tools/theme-switcher/render.sh`.

### End to end in a nested Hyprland

`desktop/tests/e2e_settings_nested.py` drives the pages as a user would. It runs in a
nested Hyprland nobody sees, hosted by kwin's virtual backend, with a virtual keyboard. It
uses a PipeWire nobody hears (`sandbox_audio.py`), with null sinks, no device monitors, no
D-Bus and an app playing silence. It covers:

- Sound: picking the output and the app following it, Undo, dragging a volume, Ctrl+Z,
  mute, an app's own volume and the cues;
- the keyboard: typing searches, Enter opens a result on its row, Esc, Ctrl+F, Ctrl+1…6
  and Ctrl+PgDn;
- Displays: a second output's scale applied and left to revert by itself after 15
  seconds, applied and kept, and reset;
- Keyboard & input: repeat rate and delay live in Hyprland, Undo, Caps Lock as Escape and
  Reset.

The last run passed 37 of 37 checks.

### In the fresh-machine VM

`test/vm/settings-e2e.sh` runs in the fresh-machine VM, after `test/vm/arch-vm.sh install`.
It tests the commands against the real NetworkManager, bluetoothd, power-profiles-daemon
and pacman:

- A simulated Wi-Fi network (mac80211_hwsim, hostapd as a WPA2 access point, and dnsmasq)
  is found, refused with a wrong password, joined with the password on stdin,
  disconnected and forgotten.
- The radio goes off and on.
- bluetoothd without a controller is reported plainly.
- The power profiles switch, and the kernel's test battery is read.
- About, what's waiting and the snapshots are read.
- The pages are drawn in the VM's own session, signed in at its login screen.

The last run passed 22 of 22 checks. A virtual Bluetooth controller needs bluez's btvirt,
which Arch doesn't package, so pairing is tested against the stand-in only.

The Den TV app also has **Play…** for each screen. Search shows, seasons and episodes,
movies, downloaded YouTube videos or a YouTube video URL. Choose **Resume** to use the
saved position. On-demand playback returns to the live channel when it ends or the
channel changes. Its Floating controls switch hides the hover menu, which is on by
default. The MEDIA widget and number-pad remote remain available.
