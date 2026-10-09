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

## Set up your hardware again

Run this after you change graphics cards, or after an update. Updates don't install
drivers on their own.

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

On a new NVIDIA card the driver loads at the very start, so the start-up screen and the
login screen already use it.

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
- **Hibernation.** If you set up hibernation, NVIDIA's driver can't load at the very start.
  `bromigos hw setup` notices this, and loads it a little later instead.
- **The battery or the power profile doesn't show.** `bromigos hw` lists the battery it
  finds. The profile shows once the power profiles service runs: `bromigos hw setup` sets
  it up.

More in [Troubleshooting](troubleshooting.md).
