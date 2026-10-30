# The desktop's configs

bromigOS ships the configs for Hyprland, the bar, the launcher, notifications and the lock
screen as read-only defaults. Your `~/.config` holds small files that load those defaults
and then add your own settings. An update replaces the defaults, so every machine gets a
fix at once, and it never touches `~/.config`.

This page is for someone changing the defaults or building on them. For using the desktop,
read the manual's [Getting around](../manual/src/desktop.md) page.

## Dictation

`bromigos dictate` is the hold-to-dictate controller. The Menu key's press and release
binds are in `desktop/hypr/bromigos/dictation.lua`; the shortcut picker moves both.
The user guide is [Dictation](../manual/src/dictation.md).

`desktop/lib/bromigos_dictation.py` opens `pw-record` only for a recording. A worker
transcribes snapshots every 1.2 seconds through the existing voice socket's `stt` request,
or a configured `voice` provider's `/v1/stt` endpoint. Release closes the microphone,
transcribes the final tail, then inserts once. Cancel invalidates an in-flight response.
Recordings stop at two minutes. PCM snapshots are private temporary files removed after
each request; neither audio nor transcripts are logged or saved.

`bromigos_dictation_ui.py` draws a GTK4 layer at the top centre of the focused monitor.
Its keyboard mode is `NONE`, its input region is empty, and it reserves no screen space.
The audio meter and microphone drawing follow the theme and reduced-motion setting.
The controller's socket and locks belong to one Wayland display under
`$XDG_RUNTIME_DIR/bromigos-dictation/`. It exits after two minutes idle.

`bromigos_type.py` inserts literal Unicode through `zwp_virtual_keyboard_v1`, with a
one-level keymap and no modifiers. It does not touch the clipboard or send Enter.
Insertion checks the original focused window before each batch. Tests use synthetic
audio, a stub voice socket and a real entry in a nested Hyprland:
`desktop/tests/e2e_dictation_nested.py`. The unit tests cover final audio, cancellation,
silence, focus changes and temporary-file cleanup.

<!-- site:desktop-configs -->
## How your files load the defaults

The defaults come with the `bromigos-desktop` package and live in
`/usr/share/bromigos/default/`. Each of your files loads its default first, then adds
yours.

| App | Default | Your file | How yours loads it |
|---|---|---|---|
| Hyprland | `hypr/hyprland.lua` | `~/.config/hypr/hyprland.lua` | `dofile()`, after setting the `bromigos` table |
| The bar (waybar) | `waybar/config.jsonc`, `waybar/style.css` | `~/.config/waybar/config`, `style.css` | `"include"` and CSS `@import` |
| The launcher (rofi) | `rofi/config.rasi` | `~/.config/rofi/config.rasi` | `@import` |
| Notifications (dunst) | `dunst/dunstrc` | `~/.config/dunst/dunstrc` | a link to the default, plus drop-ins |
| Lock screen (gtklock) | `gtklock/style.css` and two templates | `~/.config/gtklock/` | CSS `@import`; the rest made from templates |
| Fallback lock (hyprlock) | `hypr/hyprlock.conf` | `~/.config/hypr/hyprlock.conf` | `source =` |
| Idle (hypridle) | rendered from `idle.toml` | `~/.config/hypr/hypridle.conf` | `source =` of the rendered policy |
| The shell (zsh) | `zsh/bromigos.zsh` | `~/.zshrc` | a `source` line you add |

A few of these need more words:

- **The bar** includes three files, and the earliest wins. First come the choices Settings
  makes (`~/.config/bromigos/waybar/settings.jsonc`), then bromigOS's defaults, then the
  theme's colours (`~/.local/state/bromigos/theme/current/waybar-markup.jsonc`). Your own
  keys in `config` win over all three. The CSS imports the theme's `waybar.css`, then the
  default style.
- **Notifications** read drop-ins from `~/.config/dunst/dunstrc.d/`.
  `90-bromigos-theme.conf` links to the theme's colours. `80-settings.conf` holds what
  Settings › Notifications chose. Put your own overrides in `99-mine.conf`.
- **The lock screen's** `config.ini` and `layout.ui` name files by absolute path, so
  yours are made from the `.in` templates. The CSS imports the theme's `gtklock.css`, then
  the default.
- **Idle** is data. `~/.config/bromigos/idle.toml` holds your policy and `bromigos idle`
  renders it for hypridle. See [idle.md](idle.md).
- **The shell.** bromigOS never edits a shell startup file. The installer tells you the
  line to add: `source /usr/share/bromigos/default/zsh/bromigos.zsh`. It adds the login
  banner and zoxide. mehshell's command status starts clear in each shell. Its hooks
  record only commands executed there, excluding startup and optional-file checks.
  Blank Enter and Ctrl+C while editing clear a previous failure. A running command
  that exits with status 130 shows a grey `interrupted` label; other failures show
  red `exit:N`. The instant prompt cache never saves a failed command's status.
  Updated hooks load in a new shell or with `eval "$(mehshell init zsh)"`. See the
  manual's [Shell and terminal](../manual/src/shell.md) page.
  Local persistent panes also refresh their desktop environment before commands.
  `bromigos session shell-env` supplies only `WAYLAND_DISPLAY`,
  `HYPRLAND_INSTANCE_SIGNATURE`, `DISPLAY` and `XAUTHORITY`. Empty values unset an
  obsolete Xwayland connection. The hook never evaluates helper output, changes
  systemd's environment or reads the clipboard. A valid inherited Wayland socket
  avoids a subprocess; SSH and explicit X displays are left alone.
- **The on-screen display** (swayosd) has no file of yours. Hyprland starts it with the
  theme's `swayosd.css`, and the media keys go through it. See
  [theming.md](theming.md) for the `osd` hook.

### Where a new user's files come from

The thin files a new user starts from are in `/usr/share/bromigos/default/user/`. The
migration `20261008120200-desktop-user-configs`, run by `bromigos update`, copies them in
where you have none. It reports the files you already have and never changes them.

### The tools the defaults call

These come with the defaults, in the same package:

- `bromigos-shot` and `bromigos-rec` take screenshots and recordings.
- `bromigos-banner` prints the login banner.
- `bromigos-customize` opens the Customize window, which Super+Ctrl+Shift+Space opens on
  its Themes tab. Its tabs are Themes ([theming.md](theming.md#the-theme-switcher)) and
  Widgets ([widgets.md](widgets.md#the-widget-gallery)).
- The bar's readings live in `/usr/lib/bromigos/desktop/waybar/`.
- The power menu and the quick note live in `/usr/lib/bromigos/desktop/rofi/`.
- `bromigos-dispatch`, in `/usr/lib/bromigos/bin/`, runs one Hyprland dispatcher in either
  the Lua or the older form.

## Hyprland

### The `bromigos` table

Your `hyprland.lua` sets a global table called `bromigos`, then runs the defaults. Every
field is optional.

```lua
bromigos = {
    mod = "ALT",
    monitors = {
        { output = "DP-1", mode = "2560x1440@144", position = "0x0", scale = 1 },
    },
    workspaces = {
        { first = 1, last = 10, monitor = "DP-1" },
    },
    polkit = false,
    hw = false,
    gestures = false,
    apps = { terminal = "kitty", files = "pcmanfm" },
    config = { input = { kb_options = "caps:escape" } },
    unbind = { "XF86AudioMicMute" },
    autostart = { "some-daemon" },
}
dofile("/usr/share/bromigos/default/hypr/hyprland.lua")

-- Yours from here on.
local K = require("bromigos.keys")
K.exec("ALT + W", "firefox")
hl.window_rule({ match = { class = "Steam" }, workspace = "4" })
```

| Field | What it does | Default |
|---|---|---|
| `mod` | The main modifier for the window keys. See [below](#the-main-modifier). | `"ALT"` |
| `monitors` | Pins these outputs to a mode, position and scale | none: every output is automatic |
| `workspaces` | Opens these workspaces on this monitor | split left to right |
| `polkit` | `false` stops bromigOS starting its polkit agent | on |
| `hw` | `false` ignores this machine's GPU environment | on |
| `gestures` | `false` turns off the touchpad gestures | on |
| `apps` | The terminal and file manager the keys start | kitty, pcmanfm |
| `config` | A table merged over the default `hl.config()` | none |
| `unbind` | Default keys to drop, so you can bind them yourself | none |
| `autostart` | More commands to run at login, after bromigOS's | none |

`bromigos setup monitors` writes the `monitors` field for you, in a marked block.

### The main modifier

`mod` is the modifier of the window keys: focus, move, close, workspaces, the launcher,
the terminal and screenshots. bromigOS's own keys, such as the menu, the panels and the
lock, always use Super.

With `mod = "SUPER"`, some keys would do two things. For example, Super+L would lock the
screen and move focus right. So `bromigos/keys.lua` settles it while it binds the
defaults:

- The window keys pass `{ mod = true }` when they bind. The defaults' binds wait in a list
  until `K.finish()`, at the end of the defaults' `hyprland.lua`.
- `K.finish()` finds each of bromigOS's own keys that a window key also has. The window
  key keeps it. bromigOS's key moves to Alt, the modifier the window keys left, so the
  lock goes to Alt+L. If Alt is taken too, it moves to Super+Alt. With neither free, it's
  left out. Hyprland's log names each key that moved.
- `unbind` then turns off the keys you listed, by the keys the defaults end on.

`bromigos keys`, the SHORTCUTS panel and Hyprland all read the keys this leaves. The
tests (`desktop/tests/test_keys.py`, `ModSuperTest`) check with `bromigos keys`' own clash
check that no key does two things, for several values of `mod`.

### Adding your own binds and rules

Anything after the `dofile()` line is yours: rules, binds, devices, environment variables
and modules. A module at `~/.config/hypr/bromigos/mine.lua` loads with
`require("bromigos.mine")`.

Bind keys with the helpers in `bromigos.keys` (`K.exec` and `K.dsp`). The SHORTCUTS panel
reads them, so your binds appear there with their descriptions.

To replace a default bind, list its keys in `unbind` and bind them yourself. Or let
`bromigos keys` do it for you (see [Shortcuts](#shortcuts-you-set-by-pressing-the-keys)).

A keyboard with macro keys, a dial or lighting is better served by a peripheral module.
The defaults bind its keys on that keyboard only. See [peripherals.md](peripherals.md).

To check a config before you rely on it:

```bash
Hyprland --verify-config -c ~/.config/hypr/hyprland.lua
```

### Input and the touchpad

The default keyboard repeats 50 times a second after 240 ms. A touchpad gets these
defaults, and a machine without one is unaffected:

- Tap to click: one finger is a left click, two a right click, three a middle click.
- Natural scrolling.
- The touchpad is off while you type.
- A physical click counts fingers, like a tap.
- Three fingers swiped sideways switch workspaces.

To change them, use Settings › Keyboard & input, `bromigos setup input`, or
`bromigos.config.input`. To drop the swipe, set `bromigos.gestures = false`.

### The GPU's environment

`bromigos hw setup` writes this machine's GPU environment into
`~/.local/state/bromigos/hw/hyprland.lua`, and the defaults read it. On a hybrid laptop
that file sets `AQ_DRM_DEVICES`. Each variable is set only while the paths it names exist.
See [hardware.md](hardware.md).

### Motion and contrast

The defaults follow the user's accessibility settings, which the theme's rendered
`hyprland.lua` carries.

- Under reduced motion, windows and workspaces fade instead of popping in and sliding.
- Under still motion, Hyprland has no animations.
- Under high contrast, window borders are 3 px and solid.

Your own `hl.animation(…)` after the defaults, or `bromigos.config`, still wins. See
[accessibility.md](accessibility.md).

### The bar on a laptop

Two of the bar's modules appear only where they mean something.

- **The battery** shows the charge, with `+` while charging and `=` when plugged in. It
  turns amber at 25% and red at 10%. Its tooltip gives the time left.
- **The power profile** shows while `power-profiles-daemon` runs. A click moves to the
  next profile.

`bromigos hw setup` installs the daemon on laptops. See [hardware.md](hardware.md).

### The bar's Bluetooth

The bar's Bluetooth module is `waybar/scripts/bluetooth.py`. It runs as long as the bar,
and prints a line each time bluez's D-Bus signals say something changed: no polling. It
hides on a machine with no adapter. The manual's [Bluetooth](../manual/src/bluetooth.md)
page is the user's guide.

Its look follows [DRIFTGLASS](DRIFTGLASS.md). The icon is EMBER:

- the rune dim while Bluetooth is off and lit while it's on, with the number of devices
  connected beside it;
- the main device's battery as five cells under the rune (classes `c0` to `c5`), and amber
  at 15% or less (`low`);
- one Spark on a connect or disconnect (`spark`), and a slow blink while bluez scans or
  pairs (`scanning`).

Under reduced motion, the module leaves `spark` and `scanning` out and sets `busy`, which
doesn't move. The images are the theme's (`bt`, `btcell-N` in `theme/icons`), set by its
`waybar.css`.

One copy of the module, whichever takes a lock in `$XDG_RUNTIME_DIR` first, sends the
"connected" and "disconnected" notifications. It also makes a headset or speaker the sound
output when it connects, unless `audio_default = false` in
`~/.config/bromigos/bluetooth.toml`.

A click runs `bromigos bluetooth panel`, a right-click `bromigos bluetooth menu`, and a
middle-click `bromigos bluetooth power toggle`. The panel and the menu are
`lib/bromigos_btpanel.py`: GTK 4 on a gtk4-layer-shell surface, placed under the pointer.
Esc, a second click on the icon, or a click anywhere else closes it (see "Closing a bar
popup" below). Both are GLOW:

- Glass with faint Scanlines;
- each device a hologram on its Emitter (`lib/bromigos_driftglass.py`), turning slowly
  while connected;
- a Pulse while it connects, a Spark when that works, and the Sweep while scanning.

They move only while open, and not at all under reduced motion. High contrast makes the
glass opaque.

The panel pairs over bluez's D-Bus API with its own agent (`org.bluez.Agent1`). The agent
puts any PIN, passkey or "does it show 123456?" question in the panel. bluez code shared
by the module, the panel and `bromigos bluetooth` is in `lib/bromigos_bluez.py`. It also
explains bluez's errors in plain words.

Tests run against `tests/fake_bluez.py`, a stand-in bluez on a private D-Bus that pairs
the way real devices do. `tools/popups/render.py` draws the icon's states, the panel and
the menu offscreen, in any theme.

### Bluetooth in the terminal

`bromigos bluetooth tui` (`core/crates/bromigos-bt`, ratatui) is Bluetooth in the terminal.
It's DRIFTGLASS GLOW like the panel:

- box frames in the theme's colours, read from `palette.json`;
- device glyphs that brighten when connected, and segmented battery bars;
- a braille radar Sweep while scanning, with new devices blipping in;
- no motion under reduced motion.

`--window` runs it through `bromigos terminal --class bromigos-bluetooth`, which Hyprland
floats and centres (`hypr/hyprland.lua`). The app launcher's entry and the panel's
**MORE…** do that.

It has no bluez code of its own. It runs `bromigos bluetooth session`
(`lib/bromigos_btsession.py`), which speaks JSON lines on stdin and stdout over the same
`bromigos_bluez` the bar and the panel use:

- the state on every change, with PipeWire's cards and each device's sound devices;
- requests and their replies, the pairing steps, and the agent's questions and their
  answers;
- a controller's live input and rumble, from `lib/bromigos_gamepad.py`, which reads and
  drives evdev directly. Which axis is which stick or trigger depends on the driver:
  xpadneo and xpad put the right stick on `ABS_RX`/`ABS_RY` and the triggers on
  `ABS_Z`/`ABS_RZ`; hid-microsoft (an Xbox pad over Bluetooth without xpadneo) puts the
  right stick on `ABS_Z`/`ABS_RZ` and the triggers on `ABS_BRAKE`/`ABS_GAS`. So the layout
  is SDL_GameControllerDB's mapping for the device, by SDL's GUID and SDL's numbering of
  its buttons and axes, as Steam and most games read it (`lib/gamecontrollerdb.txt`, the
  Linux lines; `tools/gamecontrollerdb/update.sh` refreshes it). `SDL_GAMECONTROLLERCONFIG`
  comes first, as in SDL. A device the database doesn't know gets its layout from which
  axes its driver has. Each input message names the driver and where the layout came from;
- a microphone's level, from `parec`.

`core/crates/bromigos-bt/tests/screens.rs` draws every screen in ratatui's TestBackend in
the Wick, Mire and Tidewell. It compares the text with `tests/snapshots/` and checks the
colours against each world's palette. The state it draws is a real session document,
recorded against the stand-in bluez.

### Hover popups on the bar

waybar has no hover action. `waybar/hover/bromigos-hover.c` adds one: a waybar CFFI module
(a library waybar loads, package `bromigos-bar-hover`) that draws nothing. It finds another
module of its own bar by its widget name (`target`) and watches the pointer over it:

1. The pointer rests on the target for `open-delay` milliseconds (350). The module asks the
   popup app for its `hover` action, with the target's centre on the screen. It asks over
   D-Bus (`org.gtk.Actions.Activate` on the app's id), so a running app answers at once.
   If the app isn't running, the module runs `command hover X` instead.
2. The pointer leaves the target. The module asks for `leave`.

A quick pass over the target asks nothing. Each bar, on each monitor, runs its own copy.

The default bar gives the volume (`pulseaudio`) the sound popup this way:
`lib/bromigos_soundpopup.py`, `bromigos sound popup`. The popup is GLOW, built from the
same parts as the Bluetooth panel (`lib/bromigos_popup.py`). It works like this:

- **Opened by a hover**, it takes no keys. It closes 0.4 seconds after the pointer has
  left both the volume and the popup.
- **Pinned**, by a click on the volume (`bromigos sound popup pin`) or inside the popup, it
  takes the keys on demand and closes on <kbd>Esc</kbd>, a second click on the volume, or a
  click elsewhere.
- **It does everything through `bromigos sound`**: `output|input DEVICE` (which also moves
  what's playing), `volume`, `mute` and `status --light`.
- **It follows `pactl subscribe`** while it's open.
- **It keeps running** for ten minutes after it closes, so the next hover opens at once.

`tests/e2e_hover_nested.py` runs the module in a real waybar in a private nested session,
with a virtual pointer.

### Closing a bar popup

The Bluetooth panel, its quick menu and the pinned sound popup close the same way
(`Outside` in `lib/bromigos_popup.py`):

- **A click anywhere else**, on any screen, the bar included. While a popup is open, a
  nearly clear layer-shell surface covers each screen, under the popup and over the bar.
  When a click on it ends, the popup closes and the same button is clicked again where the
  pointer is (`lib/bromigos_vptr.py`, the compositor's virtual pointer). The click still
  reaches the bar module, window or desktop it was on.
- **A second click on its own icon.** That click closes the popup and isn't passed on, so
  the icon's command doesn't open the popup again.
- **<kbd>Esc</kbd>.** A popup takes the keys on demand: they reach it while it has the
  focus, and it never holds them. The only exception is while a PIN or passkey is typed
  into the Bluetooth panel. Then it takes them all, so the code can't go to another
  window.

The surface can't be fully transparent. A GTK 4 surface with nothing drawn on it is never
shown, so a click would go straight through it.

`tests/e2e_popups_nested.py` opens each popup from a real waybar in a private nested session.
It clicks another module, the desktop, the popup's own icon and <kbd>Esc</kbd>, and checks
that the popup closes and the other click still lands.

## Shortcuts you set by pressing the keys

`bromigos keys` rebinds a key without editing Lua. You pick what to bind, press the new
keys, and it's saved. You can open it four ways:

- SETUP › Shortcuts… in the menu (Super+Space).
- The Shortcuts page of Settings (Super+,). See [settings.md](settings.md).
- CHANGE A SHORTCUT in `bromigos setup keybindings`.
- `bromigos keys` in a terminal.

### What you can bind

The picker is a rofi list you can search. It has these rows:

| Row | What it is |
|---|---|
| YOURS | Your shortcuts. Change the key, remove it, or put a moved default back. |
| OFF | bromigOS defaults you turned off. Put one back, or give it another key. |
| DEFAULT | Every bromigOS default bind, so you can move it to another key. |
| LAUNCH, STYLE, TOGGLE and the other menu groups | Every item of the menu, read from the same sources the menu reads. |
| WEB APP | Your web apps (`bromigos webapp`). |
| COMMAND | A command of your own, run as a shell runs it. |

A menu item that runs a program is bound to that program. An item that opens a terminal is
bound to `bromigos-menu --run <id>`, so it runs exactly as it does from the menu.

### Pressing the keys

A small window says "Press the new shortcut" and shows the keys as you hold them, written
the way the SHORTCUTS panel writes them (`SUPER + SHIFT + W`).

- Let go and it saves after a moment. Enter saves at once.
- Backspace clears. Esc cancels. Thirty seconds without a key also cancels.
- Enter, Backspace and Esc on their own belong to the window. With a modifier they're
  ordinary keys, such as `ALT + RETURN`.

The window uses the theme's colours. Under high contrast its frame is a solid 2 px line.
Every part of it explains itself on hover.

### Why Hyprland's own keys don't fire

While the window listens, Hyprland switches to a submap called `bromigos-capture`, which
binds nothing but Esc. That's why `SUPER + Q` is captured instead of closing a window. The
submap is defined in `hypr/bromigos/binds.lua`, or at run time for an older config.

Nothing can leave you stuck in the submap:

- Esc always leaves it, and still reaches the window, which cancels.
- The window leaves it on every way out.
- A watchdog process leaves it if the window is killed or crashes.
- Hyprland's own timer leaves it after a minute.
- Hyprland refuses to enter a submap that doesn't exist.

### When a key is taken

The keys are checked against three things: what Hyprland has bound now
(`hyprctl binds -j`), bromigOS's defaults, and your config. If something holds the keys,
the picker says what, and offers:

- **Swap.** The holder gets the old key of what you're binding, if it had one.
- **Replace.** The holder loses the key. A bromigOS default is turned off and listed under
  OFF. `bromigos keys reset` brings it back.
- **Pick another key**, or **Cancel**.

Some binds can't be moved from here. These are binds you wrote yourself in
`hyprland.lua`, and binds only the running Hyprland has, such as a plugin's. Change those
where they're made, or pick another key.

The picker asks before it does anything risky. It asks if the change would leave the menu
or the terminal without a key. It also asks if the change would take a key you type with,
such as a letter or Space without a modifier.

### How your shortcuts are saved

Your shortcuts are kept in `~/.config/bromigos/keys.toml`. They're written into two marked
blocks of `~/.config/hypr/hyprland.lua`, using the same helpers as the defaults. Nothing
outside the blocks is touched.

```lua
-- >>> bromigos keys-unbind
for _, keys in ipairs({ "SUPER + SPACE" }) do table.insert(bromigos.unbind, keys) end
-- <<< bromigos keys-unbind
-- …
-- >>> bromigos keys
do
    local K = require("bromigos.keys")
    K.exec("SUPER + CTRL + M", "bromigos-menu")   -- Desktop menu … (from SUPER + SPACE)
end
-- <<< bromigos keys
```

The `keys-unbind` block sits just before the line that loads the defaults. The `keys`
block sits at the end of the file.

- **A moved default** is a copy of its binds on the new key, with its old key added to
  `bromigos.unbind`. A press-and-release pair stays a pair.
- **A peripheral module's keys** are defaults like the rest. They're bound before the
  default binds, so `bromigos.unbind` turns them off too. A shortcut on a key the module
  keeps for its own keyboard (`K.exclude`, such as `XF86AudioMicMute`) is written in the
  module's spelling, so it gets the same exclusion.
- **A web app's key** stays the web app's. It's kept in `~/.config/bromigos/webapps.toml`
  and its own block, as `bromigos webapp add --hotkey` writes it.

### How Hyprland takes the change

Every save goes through `bromigos_hypr.save`, in this order:

1. Hyprland's auto-reload is turned off.
2. The files are written whole.
3. `Hyprland --verify-config` checks them.
4. Hyprland reloads once.
5. The save checks that `hyprctl configerrors` reports nothing new.
6. The save checks the new binds in Hyprland's live table.
7. Auto-reload goes back to how it was.

If any step fails, every file goes back as it was, Hyprland reloads it, and a notification
says what happened. Without a running Hyprland, the files are verified and Hyprland reads
them at its next start. `bromigos webapp --hotkey` and `bromigos setup input` save the same
way.

### Commands

```text
bromigos keys                                     open the picker
bromigos keys bind --default "SUPER + SPACE"      press a new key for the menu
bromigos keys bind "SUPER + M" --default "SUPER + SPACE" --swap
bromigos keys bind "SUPER + ALT + G" --webapp gmail
bromigos keys bind "SUPER + ALT + T" --menu style/theme/mire
bromigos keys bind --exec "kitty -e btop" --what "System monitor"
bromigos keys list [--all] [--json]               yours and the defaults you turned off
bromigos keys check "SUPER + D"                   what a key does now, and where from
bromigos keys unbind "SUPER + D"                  free a key
bromigos keys reset ["SUPER + D"]                 every default back, or just that one
bromigos keys undo                                undo the last change; again to redo
```

- Without keys on the command line, the capture window asks for them.
- With keys on the command line, a clash or a lockout is printed rather than asked.
  `--swap`, `--replace` and `--yes` answer it.
- `--from KEYS` binds whatever is on KEYS now.
- `list --all` shows every key, where it comes from, and whether it can be moved.
- `reset` with no keys also removes your own shortcuts.
- `bind`, `unbind`, `reset` and `undo` take `--json`. The outcome is one document with
  `ok`, `notes` and `detail`. A refusal has `error`, plus `confirm` when `--yes` would do
  it, or `taken` when someone else holds the keys. The Settings page uses this form.

The SHORTCUTS panel (Super+K), its search (Super+Shift+K) and `bromigos setup keybindings`
list your shortcuts under YOURS, by the names you picked them by. A moved default keeps
its own name and section.

### Tests

- `desktop/tests/test_keys.py` covers the blocks, clashes, swaps, the lockout guard, the
  safe save and its rollback, `--json`, undo and redo, the capture's keys and submap. It
  also draws the window and the Settings page offscreen.
- `desktop/tests/e2e_keys_nested.py` runs end to end in a nested Hyprland nobody sees.
  kwin's virtual backend hosts it, and a virtual keyboard types. It checks that binds are
  held back during the capture, Esc, Backspace, a killed window, the picker, a clash
  answered in rofi, a failed verify, and a reset that leaves the file byte for byte as it
  was. It also drives the Settings page's Change…, Undo, Remove and Reset… buttons. The
  last run passed 49 of 49 checks. It needs kwin_wayland, Hyprland, rofi and a GPU, so it
  runs by hand. It stops at once if the nested screen isn't 1600×900. kwin 6.8 had shrunk
  it to 1280×720, so a window rule now keeps it full screen.

## Monitors

Nothing in bromigOS names a connector. Any monitor lights up, including one plugged in
later.

### Scale and placement

A catch-all rule runs every output at its preferred mode and places it automatically. An
output that `bromigos.monitors` doesn't pin gets a scale from its pixel density:

- The density comes from the EDID's physical width. About 110 pixels per inch is 1x.
- The scale is rounded to a step of 0.25, from 1 to 2.
- A 27-inch 1440p monitor runs at 1x, and a 15-inch 4K laptop screen at 2x.
- Without a physical size, a screen 2000 pixels tall or more runs at 1.5x.

### Workspaces

With several monitors and no `bromigos.workspaces`, workspaces 1 to 10 are split left to
right. Two monitors get 1–5 and 6–10. The split runs again when a monitor is added, removed
or moved. When you unplug one, its workspaces move to the monitor that's left.

### What goes on which monitor

The bar and the wallpaper go on every monitor. The live background goes on the *primary*
monitor, and so do the panels (widgets) until you drag one onto another monitor
([widgets.md](widgets.md#more-than-one-monitor)). bromigOS picks the primary in this
order:

1. The surface's own setting: `general.monitor` in the live layer's config, or `"monitor"`
   in the panels' layout.
2. The primary that `bromigos setup monitors` recorded in
   `~/.config/bromigos/monitors.toml`.
3. The focused monitor.
4. The first monitor.

The code is `lib/bromigos_monitors.py`. When the primary is unplugged, the background and
the panels move to another monitor, and they move back when it returns. A panel on another
monitor of its own moves to the primary while that monitor is unplugged. VECTOR's hologram
follows the same rule, and `BROMIGOS_HOLO_MONITOR` overrides it.

### Setting monitors up

`bromigos setup monitors` lists each output with its name, make and model, mode, physical
size and suggested scale. You choose the primary, the left-to-right order, and each
output's scale and refresh rate. It writes a marked `bromigos.monitors` block into your
`hyprland.lua`, just before the defaults load. Running it again replaces the block.

To run it without questions:

```bash
bromigos setup monitors --monitors auto --primary DP-1 --order DP-2,DP-1 \
  --scale DP-1=1.25 --refresh DP-2=144
```

Settings › Displays writes the same block. See [settings.md](settings.md#displays).

The fresh-machine VM test covers one output, two outputs, and plugging and unplugging a
third. See [install.md](install.md).

## Floating windows put back where they were

`bromigos-windows` remembers where floating windows sat, per workspace and app, and puts
them back. It's off until you list the apps in `~/.config/bromigos/windows.toml`:

```toml
remember = ["org.pulseaudio.pavucontrol", "nm-connection-editor"]   # app classes
all = false     # true: every floating window, whatever its class
```

The defaults start `bromigos-windows` at login. With no config it exits at once.
Otherwise it watches Hyprland's events:

- When a remembered floating window closes, its place and size are saved for that
  workspace and app class.
- When one opens on that workspace again, it's moved and sized to match.
- Tiled windows are left to the layout.

```text
bromigos windows list                  what's remembered
bromigos windows clear [CLASS…]        forget everything, or these classes
bromigos windows forget WORKSPACE CLASS
```

The state is kept in `~/.local/state/bromigos/windows.json`. Settings › Startup has the
same controls.

## The start page

`bromigos-desktop` ships a start page for your browser. It has a search box, a board of
links that shows which are up, your homelab's status, your latest field notes and a clock,
all in the theme's colours.

- The page ships in `/usr/share/bromigos/startpage`. Each user's copy lives in
  `~/.local/share/bromigos/startpage`.
- `bromigos-startpage.timer` refreshes the copy every minute. A migration enables it. It
  copies in the packaged files, the current theme's `theme.css` and emblem, and `data.js`,
  which holds the latest readings.
- The folder is self-contained. Use it as your browser's home page, load it unpacked as a
  new-tab extension (it has a `manifest.json`), or link to it.
- The homelab's status comes from `bromigos-homelab` when a homelab is configured.
  Otherwise it comes from a Lab API at the private overlay's `endpoints.lab`, with the
  read-only token in `~/.local/share/bromigos/lab-token`.

Your links, and optionally where the page folder lives, go in
`~/.config/bromigos/startpage.toml`:

```toml
dir = "~/.config/bromigos/startpage"        # optional; default ~/.local/share/bromigos/startpage
from_lab = ["argocd", "grafana", "vault"]   # services from the homelab's own groups, by id

[[link]]
name = "GRAFANA"
role = "the homelab's dashboards"
endpoint = "grafana"                        # a private overlay key, or url = "https://…"
```

## What stays yours

Your monitors, your apps and their window rules and binds stay yours. So do your
keyboard's quirks, your personal plugins' decks and binds ([plugins.md](plugins.md)), and
anything a default doesn't cover. An update never rewrites anything in `~/.config`. When a
default changes, you get the change because your file loads it.

Updating is described in [update.md](update.md).

## Settings

`bromigos settings` (Super+,) is one window for the desktop's settings. Each page drives a
`bromigos` command and keeps no copy of its rules. Any package, extension or user can add
a page. See [settings.md](settings.md).

## Legacy tray icons

Waybar's tray reads StatusNotifierItem, the modern tray protocol. Wine and older
X11 apps use XEmbed instead. `bromigos-desktop` depends on `plasma-workspace` for
`xembedsniproxy`, which starts at login alongside Waybar, before user autostart commands.
It owns the XEmbed tray selection and publishes each icon to Waybar, including its
mouse actions. Wine can then dock its icons instead of creating a floating tray.
A rule hides only the bridge's `xembedsniproxy` helper window and disables its blur.
This uses the helper class added in KDE 6.7; app windows and menus keep their own rules.
Restart an already running Wine app after the next login so it docks again.

`snixembed` is not used. It converts modern tray items into legacy XEmbed icons, which
is the opposite direction. See its [package description](https://archlinux.org/packages/extra/x86_64/snixembed/).

## Game mode

`desktop/bin/bromigos-game` provides `bromigos game on|off|toggle|status` and
`bromigos game auto on|off`. Settings › Playing games calls the same command.
The session helper serialises requests over a private Unix socket. Its mode is per
session, not a permanent settings change.

The `bromigos-game` Hyprland submap has one binding: Ctrl+Shift+F12. Every other key,
including the main modifier Alt, goes to the focused client. The escape resets the
submap directly before asking the helper to restore the desktop. Super+Ctrl+G enters
from the normal desktop. No compositor reload is needed to toggle it.

While active, the helper holds a separate logind idle inhibitor, pauses dunst, and
writes `$XDG_RUNTIME_DIR/bromigos-game-on.json`. The live layer stops background frames
and TV playback while the panels temporarily hide their windows. Panels keep their
previous visibility in memory and use it when saving their layout. Leaving restores
that visibility and dunst's previous paused state. Existing stay-awake timers and saved
wallpaper settings are untouched. Explicit locking remains available from a TTY.
The live layer also holds back notification overlays, sound cues and new spoken codec
alerts while game mode is on. Its saved mute setting stays intact.
The bar shows GAME MODE with the escape key in its tooltip.
An on-screen message confirms entry and exit, including when using the keyboard's game key.

The helper remembers display routing in the user's state folder so `bromigos game off`
can recover the desktop from a TTY or SSH. Its inhibitor child exits when its input pipe
closes, including after a helper crash. A new helper restores any saved notification
state before accepting requests, and sets the gaming LED to the mode. Leaving the
submap by another route also restores the desktop. Logging out ends the helper.

Automatic mode is off by default. Its setting lives in
`~/.config/bromigos/game.json`. When enabled, it follows the focused window's fullscreen
state and matches `steam_app_<number>`, `*.exe` and gamescope classes, or processes
started by Lutris. Battle.net, Steam and Lutris launchers are excluded. Native Lutris
games are recognised through process ancestry; detached games may need manual mode.
Leaving manually suppresses automatic re-entry until focus or fullscreen state changes. Manual mode remains on across focus changes.

For the Razer button and LED, see [peripherals](peripherals.md#game-mode-key).

### Steam and Proton

bromigOS keeps Steam and Proton ready by itself, so someone who doesn't know Proton never
has to. Four commands do the work. The manual's
[Playing games](../manual/src/games.md) page is the user's guide, and Settings ›
Playing games shows the result in plain words.

| Command | File | What it does |
|---|---|---|
| `bromigos game setup` | `desktop/bin/bromigos-game-setup` | Installs `steam`, `gamemode` and `lib32-gamemode`, with the `lib32-` and `vulkan-` packages `bromigos hw --json` wants for this machine's GPUs, in one `sudo pacman -S --needed`. Adds the user to `gamemode`, runs `bromigos hw setup --user-only` when the GPU environment changed, starts the upkeep's `.path` unit and, once Steam has run, `bromigos game maintain --refresh`. Without multilib it stops and says how to turn it on. |
| `bromigos game proton` | `desktop/bin/bromigos-game-proton` | Lists Steam's Proton apps and the tools in `compatibilitytools.d`. `install` takes GE-Proton's GitHub release, checks the tarball against the release's `.sha512sum`, unpacks it into a temporary folder beside the others, then renames it into place. `remove` refuses while Steam runs, and for a version games are set to unless `--force`. |
| `bromigos game check` | `desktop/bin/bromigos-game-check` | Read-only checks. `--fix` does now what the upkeep does when Steam next closes, and disables a user `waybar.service`. Exit status 0 means healthy, 1 means something needs fixing, and 2 means it couldn't check. Each `--json` finding has `auto: true` when the upkeep repairs it. |
| `bromigos game maintain` | `desktop/bin/bromigos-game-maintain` | The upkeep. Installs the latest GE-Proton, at most once an hour unless `--refresh`. With Steam closed, it applies `bromigos_gamefix`'s plan. `--wait` waits for Steam to exit first, `--dry-run` downloads and changes nothing, and `--notify` sends one notification for each new problem only the person can fix. |

#### What runs it, and when

- **After `bromigos update`.** The update's last step (`games_in_background` in
  `core/crates/bromigos-core/src/update.rs`) runs `systemctl --user start --no-block` on
  `bromigos-game-maintain.path` and `.service`. If systemd doesn't know them yet, it runs
  one `daemon-reload` and tries again. The report's `games` field says it started.
- **Each time Steam starts or exits.** `bromigos-game-maintain.path` watches
  `~/.steam/steam.pid`, which Steam writes as it starts, and
  `~/.local/share/Steam/config/config.vdf`, which it writes as it exits. Either one
  starts `bromigos-game-maintain.service`, which runs `bromigos game maintain --wait
  --notify` at `Nice=10` with idle I/O. The GE-Proton download happens at once. Steam's
  files change only after Steam has exited and stayed closed for 15 seconds, because
  Steam restarts itself after its own updates. The package enables the `.path` unit for
  every user with a `default.target.wants` link. `systemctl --user mask
  bromigos-game-maintain.service` turns it all off, the update's start included.
- **Logs.** The service's output is its journal: `journalctl --user -u
  bromigos-game-maintain`. Settings' **Log** button opens it.

#### What it repairs

`desktop/lib/bromigos_gamefix.py` has the logic. `plan(root)` reads Steam's files and
returns the changes. `apply()` makes them, and `readiness()` turns `game check --json`
into the page's plain words.

| Part | Rule |
|---|---|
| A game set to a missing tool | Its `CompatToolMapping` entry is removed, so it follows the default. That's what unticking "Force the use of a specific Steam Play compatibility tool" does. A game set to a GE-Proton or TKG build that's gone gets the newest GE-Proton instead, when the default isn't already that. Those builds carry game fixes Valve's Proton lacks, so the newest GE is the nearest match. Steam's own tools (`proton_9`, `proton_experimental`) count as present, because Steam downloads them itself. |
| The default (`"0"`) | It becomes the newest GE-Proton when it names a tool that isn't installed, is unset, or is an older GE-Proton. A choice of another tool that is installed stays, such as Proton Experimental, `proton_9` or a TKG build. With no GE-Proton here, a missing default becomes `proton_experimental`. A missing `"0"` or `CompatToolMapping` is added in Steam's own layout. |
| Priority | The default's priority goes back to 75. |
| Runtimes | A broken Steam Linux Runtime moves aside, as `--fix` always did. One that is downloading or updating is left alone. |
| Old builds | GE-Proton and TKG folders that no game or default uses move aside. The newest GE-Proton and the newest one before it stay. Pruning happens only when a GE-Proton is installed. It covers only folders directly in `compatibilitytools.d`, never a link, a package's tools in `/usr/share/steam`, or another kind of tool such as Luxtorpeda. |

Versions compare across GE's naming schemes: `Proton-6.21-GE-2` < `GE-Proton7-43` <
`GE-Proton11-11-x86_64` (`ge_version`).

Everything is reversible:

- `config.vdf` is copied to `~/.local/state/bromigos/game/backup/<time>/`. Then it is
  rewritten through a temporary file and a rename. An edit that doesn't parse back is
  never written.
- Runtimes and old builds are renamed into `<library>/bromigos-backup/<time>/`, on the
  same drive. Those folders are deleted after 14 days.
- The changes to `config.vdf` are checked again just before the write, and nothing is
  written if Steam has started.

A lock file in `~/.local/state/bromigos/game/` keeps the service, Settings' Fix and a
terminal from running at once. The upkeep never starts or stops Steam.

#### The login screen's leftovers

Earlier set-ups left files in `/etc/sddm.conf.d` that repeat the package's
`/usr/lib/sddm/sddm.conf.d/zz-bromigos.conf`: `10-wayland.conf`, and `20-bromigos.conf`
from the old `~/.config/bromigos/sddm/install.sh`. SDDM reads `/etc` last, so such a file
would quietly override the package's next change to the login screen.

`settings/sddm/bromigos-sddm-tidy`, installed to `/usr/lib/bromigos/sddm/`, reports each
file read-only. With `--apply` it moves the files that only repeat the package to
`/var/lib/bromigos/sddm-backup/<time>/`, and records each move in
`/var/lib/bromigos/sddm-tidy.json`. A file counts as a repeat when it sets something and
every setting matches the package's value, or when it holds only comments and the old
installer's header. A file with any setting of its own stays.

`bromigos-settings.install` runs `--apply --quiet` in `post_install` and `post_upgrade`.
Nobody types sudo. Settings › Playing games › Fix runs it through `pkexec` when a repeat
is still there.

`game check` reports a moved file as `ok`. It warns only when a file overrides one of
bromigOS's own settings, and says what it changes. A file that only adds settings, such
as autologin, is an `info` note.

#### Reading Steam's files

`desktop/lib/bromigos_steam.py` reads Steam's files for all four commands:

- **VDF.** Steam keeps its state in Valve's text KeyValues format. The parser records
  where each key and value sits in the text. A change rewrites that one value, removes
  one block with its lines, or adds one block in the file's own tab layout. The rest of
  the file stays byte for byte. A key that appears twice keeps its first value, as in
  Steam, and a change never adds a second copy. The `vdf` package from PyPI appends a
  duplicate key when you assign to one, so it isn't used.
- **Where Steam is.** The root is `~/.steam/root`, else `$XDG_DATA_HOME/Steam`. The
  libraries come from `steamapps/libraryfolders.vdf`, and each app from its
  `appmanifest_<id>.acf`.
- **Runtimes.** A runtime or tool is whole when its `toolmanifest.vdf` exists and the
  entry point its `commandline` names is there. The container runtimes, soldier (1391110),
  sniper (1628350) and Steam Linux Runtime 4.0 (4183110), also need `_v2-entry-point` and
  a non-empty `pressure-vessel/`. A runtime whose `StateFlags` show a download or update
  in progress is reported, not judged. A Proton whose runtime isn't installed is only a
  note, because Steam installs it when you press **Play**.
- **The default tool.** `CompatToolMapping` in `config/config.vdf` maps app IDs to tools.
  Its `"0"` entry is the default for every game, and its priority must be 75, Steam's own.
  Per-game entries use 250.
- **Steam running.** Steam is running when a process in `/proc` is `steam` or
  `steamwebhelper`, or a shell running `steam.sh`. Nothing that changes Steam's files runs
  then, because Steam writes `config.vdf` back when it exits.
- **GE-Proton.** `install_ge` downloads, checks the SHA-512 and unpacks. It needs four
  times the tarball's size free first. `game proton install` and the upkeep share it.

`BROMIGOS_FS_ROOT` moves `/` for `/proc`, `/etc`, `/usr` and `/var`, and
`BROMIGOS_PROTON_RELEASES` replaces GitHub's API with a folder of recorded releases.
`BROMIGOS_GAME_POLL` and `BROMIGOS_GAME_SETTLE` shorten the upkeep's wait for Steam.
`desktop/tests/test_steam.py` runs all four commands on a fake Steam in a throwaway home,
with the VDF files in `desktop/tests/fixtures/steam/`. `config-stale.vdf` copies a real
install's leftovers, and `config-stale-fixed.vdf` is the byte-exact result. The tests
cover the plan, applying it, the deferral while Steam runs, the GE download and its hourly
limit, pruning and notifications. `settings/sddm/tests/test_tidy.py` runs the SDDM tidy,
and the package scriptlet itself, against fixture `/etc` trees.
The isolated test is `desktop/tests/e2e_game_nested.py`; the tray test is
`desktop/tests/e2e_tray_nested.py`. The latter needs `gtk2` for its StatusIcon fixture.
It exercises the direct XEmbed button path also used by Wine. GTK 3 StatusIcon uses
the bridge's separate XTest input path; its menu did not open from a simulated Waybar
click in the nested test, although a direct SNI context-menu request worked.
