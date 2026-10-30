# desktop/

This folder is the `bromigos-desktop` package. It holds bromigOS's default configs for
Hyprland, the bar (waybar), the launcher (rofi), notifications (dunst), the lock screens
and the shell. It also holds the tools those configs call, the desktop menu, the shortcut
picker and the Settings window.

How the defaults and a user's own files fit together is in
[docs/desktop.md](../docs/desktop.md). The keys are listed in the manual's
[Keys](../manual/src/keys.md) page, which is generated from `hypr/`.

## What's here

| Folder or file | Installed to | What it is |
|---|---|---|
| `hypr/`, `waybar/`, `rofi/`, `dunst/`, `gtklock/`, `zsh/` | `/usr/share/bromigos/default/` | The read-only defaults |
| `user/` | `/usr/share/bromigos/default/user/` | The thin files a user's `~/.config` starts from |
| `settings/` | `/usr/lib/bromigos/settings/` | The Settings window and its pages |
| `bin/` | `/usr/lib/bromigos/desktop/bin/`, `/usr/lib/bromigos/bin/` | The commands |
| `lib/` | `/usr/lib/bromigos/lib/` | Shared Python and Lua code |
| `hooks/theme-set.d/` | `/usr/share/bromigos/hooks/theme-set.d/` | The hooks `bromigos theme set` runs |
| `waybar/scripts/`, `rofi/scripts/` | `/usr/lib/bromigos/desktop/{waybar,rofi}/` | The bar's readings, the power menu, the quick note |
| `startpage/` | `/usr/share/bromigos/startpage/` | The browser start page |
| `systemd/` | `/usr/lib/systemd/user/` | User services and timers |
| `applications/` | `/usr/share/applications/` | Desktop entries for the app launcher |
| `wallpaper/` | `/usr/share/bromigos/wallpaper/` | The Wick's empty den and its lock-screen twin |
| `tests/` | not installed | Unit tests and end-to-end drivers |

`packaging/bromigos-desktop/PKGBUILD` lists every installed path.

### The defaults

- `hypr/hyprland.lua` is the main Hyprland config. `hypr/bromigos/` holds its parts:
  `binds.lua` for keybinds, `live.lua` for the live layer's, `vector.lua` for VECTOR's,
  `peripherals.lua` for peripheral modules, and `keys.lua` for the bind helpers.
- `hypr/hypridle.conf` is the default idle policy, already rendered. The live policy is
  rendered from `idle.toml` by `bromigos idle` ([docs/idle.md](../docs/idle.md)).
- `hypr/hyprlock.conf` is the fallback lock screen. gtklock is the main one.

At startup, Hyprland asks `bromigos hw display` whether exactly one usable GPU has a
connected screen. It prefers that card unless an explicit GPU setting already applies.
This choice is made again at each login. It does not move a running renderer when a
cable is unplugged. See [GPU selection](../docs/hardware.md#choosing-the-gpu-with-a-connected-screen)
for the rules and overrides.

### The commands in `bin/`

Most go to `/usr/lib/bromigos/desktop/bin/` and are linked into `/usr/bin/`:

- `bromigos-menu`, the desktop menu ([docs/menu.md](../docs/menu.md));
- `bromigos-theme-switcher`, the Customize window, and `bromigos-customize`, which opens it
  on a tab; `bromigos-theme-previews`;
- `bromigos-wallpaper`, `bromigos-webapp` and `bromigos-windows`;
- `bromigos-keys`, the shortcut picker;
- `bromigos-setup-keybindings`, `bromigos-setup-input` and `bromigos-setup-config`;
- `bromigos-extensions`, the extensions window;
- `bromigos-shot`, `bromigos-rec` and `bromigos-banner`.

`bromigos dictate` records while the Menu key is held. Its top-centre panel shows audio
activity and transcript previews without taking focus. Release inserts the text through
a Wayland virtual keyboard and hides the panel. See [Dictation](../manual/src/dictation.md).
`lib/bromigos_dictation.py` handles recording and speech; `bromigos_dictation_ui.py`
draws the panel; `bromigos_type.py` inserts Unicode without using the clipboard.

The commands behind Settings' pages go to `/usr/lib/bromigos/bin/`, where `bromigos <name>`
finds them: `display`, `sound`, `net`, `bluetooth`, `power`, `clock`, `notifications`,
`defaults`, `startup`, `panels`, `scene`, `memory`, `about` and `avatar`. They're listed
in [docs/settings.md](../docs/settings.md#the-commands-behind-the-pages).
`bromigos-dispatch` goes there too.

`bromigos shell` chooses the prompt engine and forwards mehshell's `doctor`, `preview`
and `configure` tools. Previews are printed without evaluating shell text. The packaged
zsh defaults mark the session for bromigOS branding; prompt settings stay in mehshell's
own config. mehshell tracks commands run in the current shell, so startup checks and
cached prompts do not show a stale failure. Blank Enter and cancelling an input line
clear the status; interrupting a running command shows `interrupted`. See
[Shell and terminal](../manual/src/shell.md).

The zsh setup also refreshes missing or stale desktop settings before commands in
local Herdr, tmux and GNU Screen panes. It calls the core's read-only
`bromigos session shell-env` helper and imports only four allowed display variables,
without evaluating shell text. Working sockets take the fast path without launching
a helper. SSH, non-interactive shells and explicit working displays are preserved.
Already-running apps need to be restarted once to receive the recovered environment.

`bromigos-peripherals` is the daemon for peripheral modules. It isn't on `PATH`.
`bromigos commands` lists every command a machine has.

### Shared code in `lib/`

- `bromigos_hypr.py` holds the shared rofi code, the marked-block code and the safe save.
  `save()` turns auto-reload off, writes, verifies, reloads and checks. If anything fails,
  every file goes back.
- `bromigos_keys.py`, `bromigos_keycapture.py` and `bromigos_keys_eval.lua` are the
  shortcut picker. They hold the record, the clash checks, the blocks, the "press the new
  shortcut" window, and the reader that runs a user's `hyprland.lua` with a stand-in
  Hyprland ([docs/desktop.md](../docs/desktop.md#shortcuts-you-set-by-pressing-the-keys)).
- `bromigos_cli.py` is the shape every Settings command shares.
- `bromigos_extlist.py` holds the extension rows that Settings and the extensions window
  share.
- `bromigos_previews.py` and `bromigos_themecards.py` draw the theme switcher's previews
  and cards. `bromigos_widgetcards.py` is the Customize window's Widgets tab.
  Its layout cards create named arrangements, save changes and override presets;
  `bromigos customize --save-layout` opens the naming form directly.
- `bromigos_peripherals.py` holds the peripheral modules' logic
  ([docs/peripherals.md](../docs/peripherals.md)).
- `bromigos_bluez.py` is bluez over D-Bus, for the bar's Bluetooth module, its panel and
  `bromigos bluetooth`: the state from bluez's signals, the actions, the pairing agent,
  PipeWire's Bluetooth cards and bluez's errors in plain words.
  `bromigos_btpanel.py` is the panel and the quick menu (`bromigos bluetooth panel|menu`),
  and `bromigos_driftglass.py` draws their DRIFTGLASS parts: device holograms, the Sweep,
  battery cells ([docs/desktop.md](../docs/desktop.md#the-bars-bluetooth)).
- `bromigos_zettlr.py` is the `zettlr` hook's work. It puts the theme's colours into a
  marked block of Zettlr's `custom.css` and sets Zettlr's dark mode
  ([docs/theming.md](../docs/theming.md#zettlr)).

### Other parts

- `hooks/theme-set.d/` holds the `apps`, `boot`, `emblem`, `gtk`, `osd`, `wallpaper`,
  `widgets` and `zettlr` hooks ([docs/theming.md](../docs/theming.md)).
- `waybar/hover/` is `bromigos-hover`, a waybar CFFI module in C that gives a module a hover
  popup (package `bromigos-bar-hover`); `lib/bromigos_soundpopup.py` is the volume's sound
  popup, and `lib/bromigos_popup.py` the parts the DRIFTGLASS popups share
  ([docs/desktop.md](../docs/desktop.md#hover-popups-on-the-bar)).
- `waybar/scripts/bluetooth.py` is the bar's Bluetooth module: the rune, the devices
  connected and the main one's battery, following bluez's signals
  ([docs/desktop.md](../docs/desktop.md#the-bars-bluetooth)).
- `waybar/scripts/idle.py` draws the bar's idle module: the eye, and stay awake's cup.
- `waybar/scripts/vector-switch.py` draws VECTOR's emergency switch on the bar: a power
  mark while he's on, and a red VECTOR OFF while he's off. It reads the switch's own
  markers ([docs/settings.md](../docs/settings.md#the-emergency-switch)).
- `startpage/` and `systemd/bromigos-startpage.*` are the start page and the timer that
  keeps each user's copy ([docs/desktop.md](../docs/desktop.md#the-start-page)).
- The peripheral modules' manifests come from `../peripherals/` and install to
  `/usr/share/bromigos/peripherals/`.

## Changing a default

1. Edit the file here.
2. Check the Hyprland config. Point `BROMIGOS_SHARE_DIR` at a folder whose `default/`
   holds this one, or install the package, then run:

   ```bash
   Hyprland --verify-config -c desktop/user/hypr/hyprland.lua
   ```

3. If you changed a keybind, give it a description in `widgets/keybinds.py`. Then run
   `tools/docs/generate.py` so the manual's key list follows. See
   [CONTRIBUTING.md](../CONTRIBUTING.md).

## Tests

```bash
cd desktop
PYTHONPATH=lib python -m unittest discover -s tests
```

This covers the peripheral modules, the shortcut picker, and Settings and its commands
against stand-ins. The package's `check()` runs it, along with syntax checks of every
script and Lua file.

`tests/hl-record.lua` prints what a Hyprland config binds, without Hyprland.

Some tests run by hand, because they need kwin_wayland, Hyprland, rofi and a GPU:

- `tests/e2e_keys_nested.py` runs `bromigos keys` end to end in a nested Hyprland nobody
  sees. `vkbd.py`, a virtual keyboard, types into it. It also drives Settings' Shortcuts
  page with `settings_shortcuts_driver.py`. The other nested tests (Settings, widgets,
  tray, game, TV and more) reuse its nested Hyprland. A kwin window rule keeps it full
  screen at the size the test asks for, 1600×900 unless the test says otherwise. If the
  screen comes up at another size, the run stops with `WrongSize`. The rule and the check
  are the theme previews' own, from `lib/bromigos_previews.py`.
- `tests/e2e_settings_nested.py` drives Settings' pages the same way.
- `tests/e2e_previews_nested.py` draws a theme preview in the nested desktop at two sizes.
  It fails if the picture isn't the whole desktop at the size asked for.

The app launcher's entries are checked by `tools/launcher/check.py`
([docs/menu.md](../docs/menu.md#tests)). Settings' offscreen renders are
`tools/settings/render.sh` ([docs/settings.md](../docs/settings.md#tests)).

## Den TV

`settings/bromigos-tv-guide` opens the standalone GTK4/libadwaita channel guide, with its
launcher entry **Den TV**. It uses the Settings toolkit's colours and controls, and
`bromigos_tvchannels.Store` for shared channel edits. Settings keeps only playback
controls and an open button. [The manual](../manual/src/themes-and-worlds.md#the-channel-guide)
explains the app; `tests/e2e_tv_nested.py` drives it in a separate compositor.

## Den TV controls

The den screens have a hover menu for channels, sound, volume, full screen and the guide.
The hover menu is on by default and uses `tv.hover_hint`.
`bromigos-live tv hint on|off` changes it.
The MEDIA widget has a rotary dial and per-screen sound controls. Full-screen playback
loads only the den's own `live/tvosc.lua`, with a private palette and IPC connection;
it leaves global mpv settings alone. The number-pad remote selects a screen with
Super+KP 1/2/3 and releases it with Super+KP 0, Escape or a fifteen-second timeout.

`lib/bromigos_tvplay.py` shares media search and on-demand playback between the Den TV
app, media TUI, CLI and VECTOR. `lib/bromigos_tvremote.py` shares hint, selection and
remote commands. The media TUI uses `p` to play on a den screen and `P` for a profile.

## Playing games

`bromigos game` runs a session helper. It owns a logind idle inhibitor and keeps a
recovery record under `$XDG_RUNTIME_DIR`. The live layer and panels read its transient
marker; their saved settings stay intact. Settings › Playing games controls it.
On-screen messages confirm entry and exit, and the bar shows GAME MODE while active.
See [game mode](../docs/desktop.md#game-mode) and the manual's
[Playing games](../manual/src/games.md).

`xembedsniproxy` starts with the bar to put legacy XEmbed tray icons into Waybar.
It comes from `plasma-workspace`; `snixembed` bridges in the opposite direction.
