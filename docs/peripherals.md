# Peripheral modules

A peripheral module makes a device part of the desktop. bromigOS ships one, for Razer
keyboards that openrazer drives. It binds the macro keys on that keyboard only, turns the
command dial into a switch for VECTOR's voice, and makes the lighting follow VECTOR.
VECTOR is the desktop's AI assistant.

Modules are optional, and each is off until you turn it on. A module for a similar
keyboard is a folder with one TOML file. The manual's
[Keyboards and peripherals](../manual/src/peripherals.md) page is the user's guide.

## Turn a module on

```bash
bromigos peripheral                          # every module: is its device here, is it on
bromigos peripheral enable razer-keyboard    # turn it on
bromigos peripheral status                   # the modules that are on, as the desktop runs them
bromigos peripheral disable razer-keyboard   # turn it off
```

`bromigos setup peripherals` offers the modules whose device is connected. So does
SETUP › Peripherals in the menu, and the Peripherals page in Settings.

`bromigos peripheral enable <id>` does five things:

1. It checks the device is connected. `--force` turns the module on anyway.
2. It installs the packages the module needs with `sudo pacman -S --needed`, and adds you
   to its groups. A new group applies after you log out and back in.
3. It records `[<id>] enabled = true` in `~/.config/bromigos/peripherals.toml`.
4. It writes the Hyprland part to `~/.local/state/bromigos/peripherals/hypr.lua`, then
   reloads Hyprland safely. It turns auto-reload off, writes the file, checks your config
   with `Hyprland --verify-config`, reloads once, and checks `hyprctl configerrors`. If the
   config doesn't verify, the previous file comes back.
5. It starts the module's user services and `bromigos-peripherals.service`, the daemon
   that runs dials and lighting. If the daemon is already running, it restarts so it
   reads the new module.

Its options:

- `--dry-run` prints the steps and changes nothing.
- `--no-system` does only steps 3 and 4: no packages, groups or services.
- `--no-reload` leaves Hyprland to pick up the keys at its next reload.
- `--yes` answers pacman's questions with their defaults.

`disable` removes the keys with a verified reload. The daemon stops when no module is
left on. The packages stay installed.

## The Razer keyboard module

The `razer-keyboard` module is in `peripherals/razer-keyboard/peripheral.toml`. It needs
openrazer:

- **The kernel driver**, `openrazer-driver-dkms`, puts the keyboard in driver mode. Then
  the M-keys send F13 to F17, the side buttons send F18 to F20, and pressing the command
  dial sends F24.
- **The daemon**, `openrazer-daemon`, controls the lighting.

`enable` installs both, plus `python-openrazer` and `python-evdev`, and adds you to the
`openrazer` group.

| Key | What it does by default | Its name in `peripherals.toml` |
|---|---|---|
| M1 | Shows or hides VECTOR | `m1` |
| M2, held | Push to talk to VECTOR | `m2` |
| M3 | Opens VECTOR and turns hands-free conversation on or off | `m3` |
| M4 | Opens the holo deck | `m4` |
| M5 | Screenshots a region | `m5` |
| Side button 1 | Opens the desktop menu | `side1` |
| Side button 2 | Opens the timeline | `side2` |
| Side button 3 | Starts or stops recording a region | `side3` |
| Dial press | Mutes the desktop: the theme's sounds and VECTOR together | `dial` |
| Dial turn | Steps through VECTOR's voices, starting with auto | `dial = false` turns it off |
| Volume roller | Changes the volume, 2% a click | Goes with the dial |

A keyboard without some of these keys simply never sends them. Without VECTOR installed,
M1 to M3 are left out and the rest work.

### The lighting

By default, the lighting follows VECTOR:

- It takes the colour of the voice he's using, as his hologram shows it.
- It turns amber, the theme's `warn` colour, when he's concerned.
- It breathes in the theme's `danger` colour when he's alarmed.
- It brightens while he listens, thinks or speaks.
- It shows the theme's `primary` colour, dimmed, when he isn't running.

To make it show the theme's `primary` colour all the time instead, run:

```bash
bromigos peripheral follow razer-keyboard theme
```

`follow razer-keyboard vector` switches back. The theme page in Settings has the same
switch. The daemon picks up the change within 10 seconds.

The lighting covers every device openrazer drives, such as the keyboard and a Razer mouse
together. Set `rgb = "device"` for the keyboard only, or `rgb = "off"`.

## Change the keys and the lighting

Your settings live in `~/.config/bromigos/peripherals.toml`. Updates never touch it.
`enable` and `disable` change only the `enabled` line, and `follow` changes only
`rgb_follow`.

```toml
[razer-keyboard]
enabled = true
rgb = "all"            # what lights up: all, device or off
rgb_follow = "theme"   # what it follows: "vector" (the module's default) or "theme"
dial = true            # false leaves the dial alone, so it scrolls sideways
devices = []           # extra Hyprland device names, from hyprctl devices, if one is missed

[razer-keyboard.keys]
side1 = "bromigos-live timeline"                  # a command, run with sh -c
m5 = ""                                           # an empty string leaves the key unbound
m2 = { press = "my-ptt down", release = "my-ptt up" }
```

Commands run through `sh -c`, so `~` and `$HOME` work. A misspelled key is an error, and
`bromigos peripheral status` says which. It never falls back to a default silently.

After you edit the file, run:

```bash
bromigos peripheral refresh
```

Hyprland reloads only when the keys changed.

## How it works

### Finding the device

`/proc/bus/input/devices` lists the input devices. A module's `[match]` section picks its
own. The interfaces of one USB device are grouped first. A keyboard has several: the keys,
the media keys, and a mouse interface that the dial reports on.

A group matches when either of these is true:

- One of its HID devices is bound to a driver in `hid_drivers`, read from
  `/sys/bus/hid/devices/<id>/driver`. For Razer keyboards that's openrazer's `razerkbd`.
  A group bound to another vendor driver doesn't match. openrazer's `razermouse` is an
  example: a mouse whose side buttons also look like a keyboard.
- Only generic drivers are bound, because openrazer isn't installed yet, and the device's
  name contains one of `name_hints`, such as `BlackWidow` or `Huntsman`. `list` then says
  it found the device by its name.

A keyboard module also needs a keyboard interface in the group. The dial is the
interface that reports both a horizontal wheel and a pointer (`REL_HWHEEL` and `REL_X`).
That's the keyboard's own mouse interface. A consumer interface that only reports a
horizontal wheel isn't it.

Hyprland names an input device by its name in lower case, with spaces as `-`. Further
interfaces with the same name get `-1`, `-2` and so on. A module tags the name and `-1`
to `-9`.

Device names are remembered in `devices.json`, beside `hypr.lua`. Unplugging a keyboard
changes nothing. When a keyboard of a new kind appears, the daemon runs `refresh` and its
keys work within ten seconds.

### The Hyprland part

bromigOS's default `hyprland.lua` loads `bromigos/peripherals.lua` before its other key
bindings. For each module in the generated `hypr.lua`, it does three things.

**It tags the devices and sets their keymap.** Each of the module's devices gets the tag
`bromigos-<id>`. It also gets the module's keymap options, added after yours. Yours are
`bromigos.config.input.kb_options`, or else the config's. The Razer module adds
xkeyboard-config's `fkeys:basic_13-24` option. Without it, the default layout reads
F13–F24 as XF86Tools, XF86Launch5–9 and XF86AudioMicMute.

**It binds each key by keycode, on the module's devices only.** A keycode bind looks like
`code:N`, where N is the kernel's code plus 8. In Hyprland 0.56, a `code:N` bind also
fires for any key without a keysym on any keyboard. Limiting the bind to the module's
devices, with `device = { list = { tag } }`, stops another keyboard's odd keys from
setting it off.

**It keeps exclusive keys off the device.** A module can mark keys as `exclusive`. The
Razer module marks `XF86AudioMicMute`. Other bindings of those keys, made through
`bromigos/keys.lua`, then ignore the module's devices. So a side button that arrives as
mic-mute doesn't mute the microphone.

The bindings go through `bromigos/keys.lua` with the defaults. So the shortcuts panel
lists them, with the module's key names from `bromigos peripheral status --json`. To skip
one, add it to `bromigos.unbind`, for example `bromigos.unbind = { "code:196" }`, as for
any default.

To see what a config binds without running Hyprland:

```bash
lua desktop/tests/hl-record.lua ~/.config/hypr/hyprland.lua
```

It prints every device setting and binding, with keys, release, device list and command.

### The daemon

`bromigos-peripherals.service` runs dials and lighting. It's a user service in
`bromigos-desktop`. The program is `/usr/lib/bromigos/desktop/bin/bromigos-peripherals`,
and its logic is in `desktop/lib/bromigos_peripherals.py`. Every ten seconds it asks
`bromigos peripheral status --json` what's on. It exits when no module is on.

**Dials.** The daemon grabs the dial's input device with python-evdev, so turning it
doesn't also scroll windows sideways. A turn steps VECTOR's voice: auto first, then each
voice in his order. It reads the list from `voices` in VECTOR's state file,
`$XDG_RUNTIME_DIR/bromigos-vector.json`, and pins a voice with `bromigos-holo voice
<role>`. It takes at most one step every 0.12 seconds. A quiet notification names the
voice and replaces the last one. An older VECTOR without `voices` gets `bromigos-holo
voice cycle` instead.

The volume roller shares the grabbed device, so the daemon handles it too. Each click
changes the volume by 2% with `wpctl set-volume`, capped at 100%.

**Lighting.** The daemon reads VECTOR's `state`, `mood` and `voice_colour`, and the
theme's `primary`, `warn` and `danger` colours through `bromigos_theme`. It writes
through openrazer's client only when the target colour changes. It looks for devices
again every minute.

Reading a Razer keyboard's input devices needs the `openrazer` group, because openrazer's
udev rules own them.

## Write a module for a similar keyboard

Put a folder in `~/.config/bromigos/peripherals/<id>/` with a `peripheral.toml` in it.
A packaged module with the same id is replaced by yours. `bromigos peripheral list` shows
it marked `(yours)`, or `BROKEN` with the reason.

```toml
format = 1
name = "My macro pad"
description = "Twelve macro keys sending F13-F24"
kind = "keyboard"

[match]
usb_vendor = "feed"                # its USB vendor id, from lsusb
hid_drivers = []                   # empty: the vendor alone decides
name_hints = []

[needs]
packages = []                      # installed by enable
groups = []
user_services = []

[keymap]
options = ["fkeys:basic_13-24"]    # XKB options for this device only, after the user's
exclusive = []                     # keys whose other bindings ignore this device

[[keys]]
id = "f13"                         # its name in peripherals.toml
code = 191                         # the keycode: evdev's KEY_F13 (183) plus 8
label = "F13"
press = "kitty"                    # a command; {holo} stands for VECTOR's launcher
release = ""                       # optional: a command on release
hint = "a terminal"                # what it does, in a few words
needs = ""                         # "vector": bound only when VECTOR is installed

# optional
[dial]
turn = "vector-voice"              # the only one so far
roller = "volume"                  # or leave it out
hint = "…"

[rgb]
backend = "openrazer"              # the only backend so far
follow = "vector"                  # or "theme"; the user's rgb_follow wins
hint = "…"
```

To find a key's code, run `evtest` or `libinput debug-events`, press the key, and add 8.

The manifest is checked when it's read. bromigOS checks the format, the vendor id, that
key ids are unique, that keycodes are between 9 and 767, and the dial, roller and
lighting kinds. An unknown field is an error.

## Files

| Path | What it is |
|---|---|
| `/usr/share/bromigos/peripherals/<id>/peripheral.toml` | Packaged modules, from `peripherals/` in this repository |
| `~/.config/bromigos/peripherals/<id>/peripheral.toml` | Your own modules |
| `~/.config/bromigos/peripherals.toml` | Your settings: which modules are on, and your keys |
| `~/.local/state/bromigos/peripherals/hypr.lua` | Generated: the Hyprland part, removed when no module is on |
| `~/.local/state/bromigos/peripherals/devices.json` | Generated: the device names each module has seen |
| `/usr/share/bromigos/default/hypr/bromigos/peripherals.lua` | The loader in the default Hyprland config |
| `bromigos-peripherals.service` | The user service that runs dials and lighting |

`BROMIGOS_PERIPHERAL_ROOT` points detection at another root, reading
`<root>/proc/bus/input/devices` and `<root>/sys/bus/hid/devices`. The tests use it for
fake devices. The JSON documents that `list`, `status`, `enable`, `disable` and `refresh`
print with `--json` are described in [core/README.md](../core/README.md).

## How it's tested

- **Detection, matching, the generated Lua and the user's file.** Rust unit tests run on
  a real `/proc/bus/input/devices` from a BlackWidow V4 Pro and a Naga Hex V2, with fake
  drivers. CLI tests run in a sandbox with a fake root, in
  `core/crates/bromigos/tests/peripheral.rs`.
- **The loader.** `desktop/tests/test_peripherals_lua.py` runs the default config with a
  generated file through a stand-in. `Hyprland --verify-config` 0.56.2 accepts the
  defaults with the module's devices and bindings.
- **The keymap option.** `xkbcli compile-keymap` with `fkeys:basic_13-24` maps FK13–FK24
  to F13–F24.
- **The dial and the lighting.** `desktop/tests/test_peripherals.py` runs them with fakes
  for openrazer's keyboard and mouse calls.
- **A real keyboard.** On a BlackWidow V4 Pro, `list` finds the keyboard by openrazer's
  driver, finds its dial on the right device, and leaves a Razer mouse out. Its bindings
  were recorded before and after moving onto the module, and they matched.

The dial and lighting tests cover turns, the gap between steps, wrapping round, the
roller, the notification, every lighting target, writing only on a change, and the device
scope.

Not proven yet:

- Razer keyboards other than the BlackWidow V4 Pro. openrazer's driver claims them, but
  their keys and dials are untested.
- Other vendors' lighting. openrazer is the only backend. An OpenRGB backend would go
  beside it.
- A keyboard whose dial isn't on its mouse interface.
