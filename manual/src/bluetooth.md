# Bluetooth

The Bluetooth icon on the bar shows whether Bluetooth is on and what's connected. A click
opens a panel where you connect, disconnect and pair devices: controllers, headphones,
keyboards, mice and phones.

## The icon

The icon sits between the network and the volume on the bar. Hover over it to see every
connected device and its battery.

- **Dim**: Bluetooth is off.
- **Lit**: Bluetooth is on. A small number beside it counts the devices connected.
- **A bar of five cells under it**: the battery of the main device connected. A controller
  counts first, then headphones. The icon turns amber, and stays amber, at 15% or less.
- **A slow blink**: Bluetooth is looking for devices, or pairing one. It stops when that
  ends.
- **A short glow** when a device connects or disconnects. A quiet notification says which.

The icon hides on a computer with no Bluetooth.

| Do this | To |
|---|---|
| Click | Open the Bluetooth panel |
| Right-click | Open the quick menu |
| Middle-click | Turn Bluetooth on or off |

With reduced motion on (`bromigos accessibility motion reduced`), the icon never blinks or
glows, and nothing in the panel moves.

## The panel

The panel opens under the icon. To close it, press <kbd>Esc</kbd>, click the icon again, or
click anywhere else. A click on something else still does what it does: a click on another
icon on the bar both closes the panel and opens that icon's menu.
<kbd>Tab</kbd> and the arrow keys move between its buttons.

- **The switch** at the top turns Bluetooth on or off.
- **Paired** lists the devices this computer knows. Each shows whether it's connected and
  its battery, and has **CONNECT** or **DISCONNECT**.
- **⋯** beside a device has **AUTO-RECONNECT**, which lets it connect by itself when you
  switch it on, and **FORGET…**, which unpairs it. Forget asks you to click twice.
- **SCAN** looks for devices in pairing mode for 30 seconds. They appear under
  **Nearby** as they're found, strongest signal first, each with **PAIR**.
- **OPEN SETTINGS** opens **Settings › Bluetooth**, which has a page for each device and
  pairing step by step ([Settings](settings.md#bluetooth)).

Pairing trusts the device, so it reconnects by itself next time, and then connects it. If
something goes wrong, the panel says what, in plain words.

## Pair a controller

An Xbox Wireless Controller pairs over Bluetooth. That covers the Xbox One S pad and
later, the Elite Series 2 and the Series X|S pads.

1. Click the Bluetooth icon and choose **SCAN**.
2. Switch the controller on with the Xbox button.
3. Hold the small pair button on its top edge until the Xbox logo flashes fast.
4. Choose **PAIR** beside **Xbox Wireless Controller**.

The controller reconnects by itself whenever you switch it on.

Linux's own driver gives you the buttons and sticks. Rumble and the battery come from a
driver called xpadneo. When a controller runs without it, the panel shows **BASIC DRIVER ·
ENABLE XBOX CONTROLLER SUPPORT** under it. Choose it, or run:

```bash
bromigos peripheral enable xbox-controller
```

That installs xpadneo and the headers of every kernel you have installed, so the driver
builds for each of them. It
asks for your password. Then switch the controller off and on again.
[Keyboards and peripherals](peripherals.md) has more about peripheral modules.

The Xbox Wireless Adapter, the USB stick some controllers came with, isn't Bluetooth. It
needs a different driver, xone, which bromigOS doesn't install. It's in the AUR (Arch's
shared build recipes): `paru -S xone-dkms`. Its build downloads the adapter's firmware
from Microsoft.

## Pair headphones or a speaker

1. Put the headphones in pairing mode. This is often a long press on the power button.
2. Click the Bluetooth icon, choose **SCAN**, then **PAIR** beside them.

When headphones or a speaker connect, they become the sound output. To keep the sound
where it is instead, turn off **Switch the sound over on connect** in
**Settings › Bluetooth**, or run `bromigos bluetooth audio-default off`.

Connected headphones show two buttons:

- **HI-FI** plays music at full quality, with the microphone off.
- **HEADSET + MIC** turns the microphone on for calls. The sound drops to phone-call
  quality while it's on.

The line under the name shows which one is on and the codec in use, such as LDAC, AAC or
SBC. A codec is how the sound is squeezed to travel over Bluetooth. Your headphones and
this computer pick the best one they share.

From a terminal: `bromigos bluetooth profile <address> hifi` or `headset`.

## Keyboards, mice and phones

- **Keyboards** often ask you to type a code on them. The panel shows the six digits.
  Type them on the keyboard, then press <kbd>Enter</kbd> on it.
- **Phones** show a code on both screens. If they match, choose **YES, PAIR** in the panel
  and accept on the phone. A phone connects for its sound only: music from the phone
  plays here.
- **Older devices** may ask for a PIN instead. It's often `0000` or `1234`. The device's
  manual says.

## In a terminal

`bromigos bluetooth tui` is Bluetooth in the terminal, with more than the panel has room
for. **MORE…** in the panel opens it in a window of its own, and so does **Bluetooth
Devices** in the app launcher (search for bluetooth, devices or controller).

- **Pairing step by step.** Press <kbd>a</kbd>, or <kbd>p</kbd> with no new device
  selected. With a device found by <kbd>s</kbd> (scan) selected, <kbd>p</kbd> pairs it
  straight away. Choose what you're pairing, and it says how
  to put that kind of device in pairing mode, with the steps for an Xbox controller. It
  scans, with devices appearing on a radar as they're found. Pick yours, answer any code
  it asks for, and it ends on **READY**.
- **Your devices**, with their battery, signal strength, and a headset's sound profile and
  codec. <kbd>/</kbd> searches them.
- **A device's page** (<kbd>Enter</kbd>):
  - a controller shows its buttons, sticks and triggers live as you press them, and
    <kbd>u</kbd> makes it rumble. It also names the controller's driver. Each stick and
    trigger is shown where it really is, whichever driver runs the controller;
  - headphones switch between HI-FI and HEADSET + MIC with <kbd>m</kbd>; <kbd>o</kbd> and
    <kbd>i</kbd> make them the sound output and the microphone; <kbd>v</kbd> shows the
    microphone's level as you speak;
  - every device can be renamed (<kbd>r</kbd>), set to reconnect by itself or not
    (<kbd>t</kbd>), forgotten (<kbd>f</kbd>), or forgotten and paired again
    (<kbd>R</kbd>).
- **Troubleshooting** (<kbd>x</kbd>) shows whether the Bluetooth service runs and the radio
  is blocked, resets the adapter (<kbd>a</kbd>), and lists what went wrong lately in plain
  words. <kbd>e</kbd> clears that list.
- <kbd>c</kbd> connects or disconnects the selected device, and <kbd>o</kbd> turns
  Bluetooth on or off.

<kbd>j</kbd>, <kbd>k</kbd> and the arrow keys move, <kbd>Esc</kbd> goes back,
<kbd>?</kbd> lists every key, and <kbd>q</kbd> quits. The mouse works too: click a device
to select it, click again to open it, and scroll to move. To open it with a key of your
own, for example <kbd>Super</kbd>+<kbd>Shift</kbd>+<kbd>B</kbd>, add a line after the
`dofile()` line of `~/.config/hypr/hyprland.lua`:

```lua
require("bromigos.keys").exec("SUPER + SHIFT + B", "bromigos bluetooth tui --window")
```

## The quick menu

Right-click the icon for the quick menu. It turns Bluetooth on or off, makes this computer
visible to devices nearby, and connects or disconnects each paired device with one click.
Use the arrow keys and <kbd>Enter</kbd>, or the mouse.

## When it doesn't work

- **The icon says bluetoothd isn't running.** Start the Bluetooth service:
  `sudo systemctl enable --now bluetooth`.
- **Bluetooth won't turn on.** A hardware switch or key may have turned the radio off.
  Turn it on there.
- **A device doesn't appear.** Put it in pairing mode again, then **SCAN**.
- **Pairing fails.** Choose **FORGET…** under **⋯** if it was paired before, then pair it
  again.

(`bromigos bluetooth`)

## For power users

Everything the icon, the panel, Settings › Bluetooth and the terminal app do, as commands,
files and rules.

### Every action, as a command

`MAC` is a device's address, such as `AA:BB:CC:DD:EE:FF`. `bromigos bluetooth` lists them.

| To | The command |
|---|---|
| See the adapter and every known device, with battery | `bromigos bluetooth` (or `status`) |
| Turn Bluetooth on, off or over | `bromigos bluetooth power on`, `off`, `toggle` (a soft rfkill block is lifted first) |
| Be visible to devices nearby | `bromigos bluetooth discoverable on`, `off` |
| Look for devices | `bromigos bluetooth scan [SECONDS]` (8 by default) |
| Pair and trust a device | `bromigos bluetooth pair MAC` (one that asks for a PIN or passkey pairs from the panel: `bromigos bluetooth panel pair MAC`) |
| Connect, disconnect | `bromigos bluetooth connect MAC`, `disconnect MAC` |
| Auto-reconnect | `bromigos bluetooth trust MAC on`, `off` |
| Forget | `bromigos bluetooth remove MAC` |
| **HI-FI** or **HEADSET + MIC** | `bromigos bluetooth profile MAC hifi`, `headset` |
| **Switch the sound over on connect** | `bromigos bluetooth audio-default on`, `off` |
| **ENABLE XBOX CONTROLLER SUPPORT** | `bromigos peripheral enable xbox-controller` |
| The panel, the quick menu | `bromigos bluetooth panel [scan]`, `bromigos bluetooth menu` |
| The terminal app, in its own window | `bromigos bluetooth tui --window` |

### Script it

- Every `bromigos bluetooth` command takes `--json`. `status --json` is the whole state as
  one document. A change answers with the state after it, with `ok` and `said`. A refusal
  or a failure is `{"ok": false, "error": "…"}` with exit status 1.
- `bromigos bluetooth session` is bluez as JSON lines on standard input and output: the
  state on every change, requests and their replies, the pairing steps and any code a
  device asks for, a controller's live input and rumble, and a microphone's level. The
  terminal app is built on it, and so can your own tools be.

### Files and rules

- **`~/.config/bromigos/bluetooth.toml`** holds `audio_default = true` or `false`.
- **Pairing** goes through bluez's D-Bus API with bromigOS's own agent
  (`org.bluez.Agent1`), which puts any PIN, passkey or "does it show 123456?" question in
  the panel, Settings or the terminal app. Pairing trusts the device, then connects it.
- **The bar icon** follows bluez's D-Bus signals, so it never polls.
- **A controller's layout** in the tester is SDL_GameControllerDB's mapping for that pad,
  by its SDL GUID, as Steam and most games read it. That's why the right stick and the
  triggers show where they really are whether xpadneo, xpad or hid-microsoft drives the
  pad. A mapping in `SDL_GAMECONTROLLERCONFIG` comes first, as in SDL, so you can fix a
  pad's layout there. A pad the database doesn't know is laid out from its driver's axes.
- **Xbox controllers.** xpadneo and xpad put the right stick on `ABS_RX`/`ABS_RY` and the
  triggers on `ABS_Z`/`ABS_RZ`. hid-microsoft, Linux's own driver for an Xbox pad over
  Bluetooth, puts the right stick on `ABS_Z`/`ABS_RZ` and the triggers on
  `ABS_BRAKE`/`ABS_GAS`. [Keyboards and peripherals](peripherals.md) has the module.

The developers' version is
[Bluetooth in the terminal](https://github.com/bromigos-org/bromigOS/blob/main/docs/desktop.md#bluetooth-in-the-terminal).
