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

The panel opens under the icon. Press <kbd>Esc</kbd> or click anywhere else to close it.
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

Linux's own driver gives you the buttons and sticks. Rumble, the battery and the button
layout games expect come from a driver called xpadneo. When a controller runs without it,
the panel shows **BASIC DRIVER · SET UP** under it. Choose it, or run:

```bash
bromigos peripheral enable xbox-controller
```

That installs xpadneo and your kernel's headers, so the driver builds for your kernel. It
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

- **Pairing step by step.** Press <kbd>p</kbd>. Choose what you're pairing, and it says how
  to put that kind of device in pairing mode, with the steps for an Xbox controller. It
  scans, with devices appearing on a radar as they're found. Pick yours, answer any code
  it asks for, and it ends on **READY**.
- **Your devices**, with their battery, signal strength, and a headset's sound profile and
  codec. <kbd>/</kbd> searches them.
- **A device's page** (<kbd>Enter</kbd>):
  - a controller shows its buttons, sticks and triggers live as you press them, and
    <kbd>u</kbd> makes it rumble;
  - headphones switch between HI-FI and HEADSET + MIC with <kbd>m</kbd>; <kbd>o</kbd> and
    <kbd>i</kbd> make them the sound output and the microphone; <kbd>v</kbd> shows the
    microphone's level as you speak;
  - every device can be renamed (<kbd>r</kbd>), set to reconnect by itself or not
    (<kbd>t</kbd>), forgotten (<kbd>f</kbd>), or forgotten and paired again
    (<kbd>R</kbd>).
- **Troubleshooting** (<kbd>x</kbd>) shows whether the Bluetooth service runs and the radio
  is blocked, resets the adapter (<kbd>a</kbd>), and lists what went wrong lately in plain
  words.

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
