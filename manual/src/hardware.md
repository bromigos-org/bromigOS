# Hardware

bromigOS looks at your computer when it installs, and sets up what the hardware needs:
the graphics driver, and on a laptop the battery, screen brightness, power profiles and
the touchpad. This page shows how to check what it found, and how to run that set-up
again.

## See what bromigOS found

```bash
bromigos hw
```

This lists your graphics cards and their drivers, whether this is a laptop, and what
`bromigos hw setup` would change.

To check whether the connected screens give bromigOS a clear automatic GPU choice, run:

```bash
bromigos hw display
```

This only checks the hardware. It does not change settings or report which card an
already running desktop is using.

## Set up your hardware again

Run this if a new graphics card needs its driver set up, or if the hardware check shows
missing setup. Updates don't install drivers on their own.

```bash
bromigos hw setup              # asks for your password for the system's part
bromigos hw setup --dry-run    # only say what it would do
```

It changes only what's different. It never removes anything, and it never replaces an
NVIDIA driver you already have.

It's also a [first-run question](first-run.md) (`bromigos setup hardware`), and an item in
the menu: **SETUP › Hardware**.

## Graphics cards

| Your graphics card | What bromigOS installs |
|---|---|
| NVIDIA GeForce 16 series, RTX 20 series and newer, and their workstation cards | NVIDIA's driver, with its open kernel modules, and hardware video decoding. |
| Older NVIDIA cards, up to the GeForce 10 series | The open-source driver, nouveau. NVIDIA's own driver for the GeForce 600 to 10 series is only in the AUR now. `bromigos hw setup` offers to build it for you with paru, and asks first. |
| AMD Radeon | Mesa, with Vulkan and video decoding. |
| Intel graphics | Mesa, with Vulkan and the right video decoder for its age. |
| A virtual machine | Mesa. |

Very old AMD and Intel chips get Mesa without Vulkan.

bromigOS knows a card by its ID, from NVIDIA's and Mesa's own lists, rather than guessing
from its name.

On a new NVIDIA card the driver loads at the very start, so it is ready for the start-up
screen and the login screen.

### More than one graphics card

If only one working graphics card has a screen connected, bromigOS prefers that card
for the login screen and desktop. You do not need to run setup just to choose it. A card
with no screen connected does not take priority because the computer booted on it.

If screens are connected to several cards, or none report a connected screen, bromigOS
keeps the existing GPU policy. Your explicit choices still take precedence, including
a laptop's saved preference. Cards bound or reserved for a virtual machine through
VFIO, the kernel's device-assignment interface, are excluded from the automatic choice.

The check happens when the login screen and desktop start. Moving a monitor cable does
not move a running desktop's renderer. Save your work and log out to start a new session;
restart the computer if the login screen also needs to choose again.

This chooses among cards whose drivers already work. It does not install a missing
driver or set up GPU passthrough to a virtual machine.

The default bar follows the available screens. If you pinned your bar or monitor
settings to a connector name, check those settings after moving the cable. A connector
on another card can have a different name.

### NVIDIA's own driver for an older card

For a GeForce 600 to 10 series card, NVIDIA's own driver is only in the
[AUR](apps.md#install-an-app-from-the-aur).

1. Run `bromigos hw setup`. It asks whether to build the driver with paru. Answer `y`.
2. paru shows you the recipe to review, then builds the driver.
3. Restart the computer.
4. Run `bromigos hw setup` again. With the driver loaded, it finishes setting it up.

Until then, the card runs on nouveau. The installer never builds this driver by itself.
If you install the driver yourself instead, run `bromigos hw setup` afterwards too.

## Laptops

On a laptop, bromigOS also sets up:

- **The battery** on the bar. It shows the charge, with `+` while charging and `=` when
  plugged in but not charging. It turns amber below 25% and red below 10%. Hover over it
  for the time left, the power it's using and the battery's health.
- **Power profiles**: power saver, balanced and performance. The bar shows the profile in
  use. Click it for the next one. The menu has them under **TOGGLE** too. If you already
  run another power manager, such as TLP or tuned, bromigOS leaves it alone.
- **The brightness keys**, which show the level on screen.
- **Two graphics cards.** On a laptop with a built-in graphics chip and an NVIDIA or AMD
  card, the desktop runs on the built-in one to save the battery. The other card sleeps
  until something needs it. To run a game or a heavy program on the other card, start it
  with `prime-run` (NVIDIA) or `DRI_PRIME=1` (AMD) in front:

  ```bash
  prime-run steam
  DRI_PRIME=1 blender
  ```

## The touchpad

| To | Do this |
|---|---|
| click | Tap with one finger. |
| right-click | Tap with two fingers. |
| middle-click | Tap with three fingers. |
| scroll | Slide two fingers. The page follows your fingers. |
| move between workspaces | Swipe sideways with three fingers. |

The touchpad turns off while you type. To change any of this, open
**Settings › Keyboard & input**, or run `bromigos setup input`.

To turn the three-finger swipe off, set `gestures = false` in the `bromigos` table of
your `~/.config/hypr/hyprland.lua`.

## If something's wrong

- **A black screen after installing an NVIDIA driver.** Restart once: the new driver loads
  when the computer starts. `bromigos hw` says whether the driver is loaded.
- **A black screen after moving a monitor to another card.** From a text console, run
  `bromigos hw display` to check the automatic GPU choice. An explicit GPU
  setting can override the automatic choice. Check your Hyprland hardware settings and
  any custom SDDM compositor command before changing drivers.
- **Hibernation.** If you set up hibernation, NVIDIA's driver can't load at the very start.
  `bromigos hw setup` notices this, and loads it a little later instead.
- **The battery or the power profile doesn't show.** `bromigos hw` lists the battery it
  finds. The profile shows once the power profiles service runs: `bromigos hw setup` sets
  it up.

More in [Troubleshooting](troubleshooting.md).
