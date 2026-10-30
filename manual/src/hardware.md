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

To see which graphics card the login screen and desktop will use at the next login, run:

```bash
bromigos hw display
```

This only checks the hardware. It does not change settings or report which card an
already running desktop is using. `bromigos hw graphics` lists every card and what it's
for.

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

**Settings › Graphics** lists every graphics card in your computer, whatever its make,
and what each one is for. [Choose what each card is for](#choose-what-each-card-is-for)
explains it. Until you choose, bromigOS decides by itself, as below.

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
driver.

The default bar follows the available screens. If you pinned your bar or monitor
settings to a connector name, check those settings after moving the cable. A connector
on another card can have a different name.

### Choose what each card is for

Open **Settings › Graphics**. Each card shows its driver and the screens connected to it,
and a **Use for** row with three buttons:

- **Desktop**: the card that draws the login screen and your desktop. Only a card with
  a screen connected can be chosen.
- **Games and heavy apps**: the card games and demanding programs run on, even when the
  desktop draws on another card. One card can do both.
- **Virtual machines**: a card kept for virtual machines only, so a VM can use it as its
  own graphics card. This is called GPU passthrough.

Hover over anything on the page to see what it does. Each use is **Automatic** until you
choose. Automatic for the desktop is the rule above. For games, it's the strongest card:
a card of its own over one built into the processor, then the newest.

If you add, swap or remove a card, bromigOS notices at the next start. A use whose card
is gone goes back to Automatic.

#### Move the desktop to another card

1. Connect a screen to the card.
2. In Settings › Graphics, choose **Desktop** on that card, then **Try it**.
3. Enter your password.
4. Log out and log back in. The login screen and the desktop now use that card.
5. Settings opens by itself. Choose **Keep**.

Until you choose Keep, the old card is still your choice. If the screen stays dark,
restart the computer and the old card comes back by itself. You never need the boot
menu for this.

You can also go back from a text console. Press Ctrl+Alt+F3, log in, and run:

```bash
sudo bromigos hw display reset
sudo systemctl restart display-manager
```

The first command sets the desktop's card back to Automatic. The second brings the login
screen back. It ends any open session, so restarting the computer works too.

From a terminal, `bromigos hw display use CARD` chooses a card and `bromigos hw display
keep` keeps it. A card is its PCI address, such as `0000:03:00.0`, or its name in
`/dev/dri`, such as `card1`.

#### Run games on another card

Choose **Games and heavy apps** on a card. It's yours alone, so it needs no password,
and it applies to programs you start from then on.

- **Steam.** Turn on **Start Steam on the games card**. Steam and every game it starts,
  Proton's included, then run on that card.
- **Any other program.** Start it with `bromigos hw run` in front:

  ```bash
  bromigos hw run -- blender
  ```

- **One Steam game.** Set its launch options to `bromigos hw run -- %command%`.

`bromigos hw run` sets the switches each maker's driver expects, and nothing when the
games card also draws the desktop. `bromigos hw run --print` shows what it sets.

#### Keep a card for virtual machines

A card for a virtual machine must pass a few checks first. Open the card's **Virtual
machines** row in Settings › Graphics to see them. Hover over one to see why it matters.
The checks are:

- the IOMMU is on. It's a firmware setting, and the row says how to turn it on;
- the card doesn't share its IOMMU group with other devices;
- no screen is connected to it, the desktop doesn't use it, and another card with a
  screen stays for the desktop;
- the computer doesn't start on it. Choose the other card in the firmware settings if it
  does.

When they all pass, choose **Virtual machines** on the card. A terminal opens and asks
for your password, then rebuilds the start-up files. Restart the computer. From then on,
your virtual machines can use the card, and the desktop and programs can't.

To give the card back, choose **Virtual machines** again, or run
`bromigos hw vfio release CARD`, then restart.

bromigOS keeps the card by its PCI address, so it works with two identical cards. The
card's own sound device goes with it. Some older AMD cards need an extra kernel module,
`vendor-reset`, to restart a VM. The checks say when yours does.

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
- **A black screen after choosing another desktop card.** Restart the computer: a card
  you haven't kept yet goes back by itself. Or press Ctrl+Alt+F3 and run
  `sudo bromigos hw display reset`, then `sudo systemctl restart display-manager`.
- **A black screen after moving a monitor to another card.** From a text console, run
  `bromigos hw display` to check which card the login screen uses. A card chosen in
  Settings › Graphics wins while it has a monitor. Check your Hyprland hardware settings
  and any custom SDDM compositor command before changing drivers.
- **Hibernation.** If you set up hibernation, NVIDIA's driver can't load at the very start.
  `bromigos hw setup` notices this, and loads it a little later instead.
- **The battery or the power profile doesn't show.** `bromigos hw` lists the battery it
  finds. The profile shows once the power profiles service runs: `bromigos hw setup` sets
  it up.

More in [Troubleshooting](troubleshooting.md).
