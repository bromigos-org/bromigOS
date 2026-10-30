# The boot menu

bromigOS gives GRUB's boot menu a theme that matches the rest of the boot. The emblem sits
exactly where the boot splash will draw it, so the menu, the splash, the passphrase prompt
and the login screen read as one screen changing. On an installed system the menu takes
the current theme's colours, its lock-screen picture and its emblem.

This page explains how the theme is made, how it reaches `/boot`, and how to preview it.
For users, the manual's [The boot menu](../manual/src/boot-menu.md) page covers turning it on
and off.

![An installed system's boot menu: a dark scene behind the burn-in emblem, a row of
signal bars counting down, and the boot entries listed underneath](images/boot-menu.webp)

## What's on the screen

The *burn-in* is the bromigOS emblem: a flame inside a ring of text. The splash is
Plymouth, which draws the burn-in at the centre of the screen. The boot menu puts it in
the same place, at the same size, so nothing moves when GRUB hands over to the splash.

From top to bottom:

```text
                     RELAY CONSOLE // SELECT CHANNEL      <- the heading

                            ( the burn-in )               <- where Plymouth draws it

                       ▂▂▃▃▄▄▅▅▆▆▇▇█                      <- the countdown, on Plymouth's progress line
                             TUNING IN · 5
            ▌ bromigOS Linux                              <- the selected entry: a bar in the theme's colour
              Advanced options for bromigOS Linux
              Roll back to a snapshot
              UEFI Firmware Settings

              ↑↓ choose · ENTER boot · E edit · C console
```

The countdown is a signal meter. Its bars light up from left to right as the seconds run
out, and it disappears when you press a key. The heading and the countdown's label are
in-universe text: the Wick is the relay station in the Bromigos stories, and the menu
plays its radio console.

### The theme's files

| Piece | File | What it is |
|---|---|---|
| Background | `background.png`, 2560x1440 | The theme's lock-screen picture, darker at the bottom, with faint scanlines and the emblem baked in at the centre |
| Heading | a label in `theme.txt` | `RELAY CONSOLE // SELECT CHANNEL` in the theme's `primary` colour, Geist Mono SemiBold 20 |
| Countdown | a progress bar and label | The signal meter, 72% of the way down, with `TUNING IN · N` under it |
| Entry list | `boot_menu` | 580 px wide and centred, in Geist Mono 16 and the theme's `text` colour |
| Selection bar | `select_w`, `select_c`, `select_e` | A bar in `primary`, with the selected entry's text in the background colour, bold |
| Icons | `icons/<class>.png` | 22 px line drawings, chosen by each entry's `--class` |
| Footer | a label | `↑↓ choose · ENTER boot · E edit · C console`, in the `muted` colour |
| Console and editor | `terminal_*.png` | A dark panel behind GRUB's console (C) and editor (E) |
| Fonts | `geist-mono-*.pf2` | Geist Mono made by `grub-mkfont`, in five sizes |

More about some of these pieces:

- **The background** is made the way `bromigos-wallpaper` makes the lock screen. A
  world's painting is stacked, softened and darkened. The Wick uses its den with the
  chair empty. A colour theme uses the den in its own colours. The emblem is
  `lock/ring.png` over `lock/flame.png`, Plymouth's own layers, 34% of the screen's
  height across.
- **The icons** cover the system entries (classes `bromigos`, `arch`, `os` and `live`,
  which get the emblem), the snapshot classes, install, safe graphics, speech, the memory
  test, disk, firmware, shell and power.
- **The fonts** are Regular 14 and 16, Bold 16, and SemiBold 20 and 26. Every theme
  carries the same five, so `grub.cfg`'s `loadfont` lines stay right when the theme
  changes.

### Any screen size

- On UEFI, `GRUB_GFXMODE=auto` uses the screen's own mode.
- On BIOS, VBE's `auto` gives 640x480 wherever GRUB gets no EDID from the screen. That
  includes QEMU's SeaBIOS and many old cards. So on BIOS the theme asks for 1024x768,
  then 800x600, then `auto`.
- The background is scaled to the screen's height and cropped or padded at the sides
  (`desktop-image-scale-method: fitheight`). Padding uses the theme's background colour,
  which the picture's edges fade into.
- Plymouth sizes the emblem by the screen's short side. Scaling by height keeps GRUB's
  emblem in the same place on any landscape screen.
- Everything else is placed in percentages of the height, plus pixels, because that's
  what GRUB's theme format accepts.
- Pictures are made at the size they're shown, because GRUB never draws an image smaller
  than its file.

It's been checked from 800x600 to 2560x1440. At 800x600 on BIOS, three entries are in
view and the rest scroll.

### How the meter works

GRUB stretches a progress bar's pictures, so bars drawn into them would squash as the bar
grows. Instead, the progress bar is a plain filled bar: a dim track, with `primary`
filling it. A mask image lies over it. The mask is the background colour with bar-shaped
holes, so the bars light up as the fill passes under them. A plate of the background
colour sits under both, so nothing shows when the countdown stops.

GRUB paints a theme's components from last to first. So `theme.txt` lists them top-most
first. A progress bar must be at least 28 px tall.

### Why it's centred

The emblem sits at the centre because that's where Plymouth draws it. It doesn't move
when GRUB hands over to the splash, or at the passphrase prompt. The entry list goes
under it, where the splash's progress line and prompt go. That also leaves the list wide
enough for a snapshot's title at 800x600.

## Where the themes come from

**Shipped themes are rendered when the package is built.** `bromigos-settings` runs
`settings/grub/build-grub-theme.py --theme-dir themes/<name>` for every theme bromigOS
ships. The results go into `/usr/share/bromigos/boot/grub/themes/<name>/`, and the fonts
into `/usr/share/bromigos/boot/grub/fonts/`.

**Other themes are rendered on your machine.** That covers your own themes, an
extension's, your changes to a shipped theme, and high contrast. They're rendered as you,
into `~/.local/state/bromigos/boot/grub/`. The inputs are what `bromigos theme set`
rendered: `palette.json`, the emblem kit and the painting. A render only happens again
when one of those changed.

### Copying the theme into /boot

GRUB can only read `/boot`, because the root file system may be encrypted. So the theme
in use is copied to `/boot/grub/themes/bromigos/`. That needs root, so a root helper does
it: `/usr/lib/bromigos/boot/bromigos-boot-theme`.

- **A shipped theme** is copied by name.
- **A theme rendered as you** is checked first. It may hold pictures only, each a plain
  file you own (no links), an 8-bit PNG GRUB can read, of a sane size. The helper writes
  `theme.txt` itself from the render's colours, which must be `#rrggbb`. The fonts come
  from the package. GRUB never parses anything you wrote except pictures.
- **The swap is atomic.** The new theme is written beside the old one, then swapped in.
  Switching themes copies files only; `grub.cfg` stays as it is.
- **One helper runs at a time.** It takes a lock.
- **It records what it installed** in `/var/lib/bromigos/boot/state.json`. Anyone can
  read that file, so `bromigos boot theme` can tell without root whether `/boot` is up to
  date.

The helper runs at these times:

- **`bromigos update`** brings `/boot` up to date after it renders the theme again. sudo
  asks on the terminal, like the update's other root steps.
- **`bromigos theme set`, or the theme switcher,** runs the `boot` theme-set hook in the
  background: `bromigos boot theme apply --no-prompt`. If sudo would ask for a password,
  the hook waits for the next `bromigos update`, and a notification says so.
- **An upgrade of `bromigos-settings`** runs its pacman hook, `bromigos-boot-theme.hook`,
  which refreshes a shipped theme in `/boot`. A theme rendered as you waits for
  `bromigos update`. The hook also brings bromigOS's block in `/etc/default/grub` up to
  date when an older package wrote it, whichever theme is in `/boot`. If that fails, the
  migration `20261009235000-boot-menu-names` tries again at each `bromigos update`.
- **`bromigos boot theme apply`** does it now, asking sudo.

## Turning it on and off

```bash
bromigos boot theme            # status: GRUB, on or off, the theme in /boot, up to date or not
bromigos boot theme on         # turn it on, in the current theme's colours
bromigos boot theme off        # back to GRUB's own menu; it stays off until you run `on`
bromigos boot theme apply      # bring /boot up to the current theme now
```

`--dry-run` shows what any of these would run. `--json` prints the result as JSON.

These turn it on automatically, except where you turned it off with
`bromigos boot theme off`:

- `bromigos install`, in its `boot menu` step.
- `bromigos setup`, after the theme section.
- The migration `20261009230000-boot-theme`, on machines installed before the boot theme
  existed.

It only acts where GRUB boots the machine. The helper checks, as root, that GRUB's
`grub.cfg` is in `/boot`. When the firmware says which loader booted the machine (UEFI's
`LoaderInfo` variable), that loader must be GRUB. systemd-boot and limine keep their own
menus, and `status` says so.

### What "on" changes

"On" adds a block at the end of `/etc/default/grub`. The rest of the file stays yours.
Later lines win, so the block overrides your values only while it's there.

```sh
# >>> bromigOS boot menu (bromigos boot theme; `bromigos boot theme off` takes it out)
if [ -f /boot/grub/themes/bromigos/theme.txt ]; then
    GRUB_THEME=/boot/grub/themes/bromigos/theme.txt
    if [ -d /sys/firmware/efi ]; then
        GRUB_GFXMODE=auto
    else
        GRUB_GFXMODE=1024x768,800x600,auto
    fi
    GRUB_TERMINAL_OUTPUT=gfxterm
fi
if [ -x /usr/lib/bromigos/boot/grub-btrfs-titles ]; then
    GRUB_DISTRIBUTOR="bromigOS"
    GRUB_BTRFS_SCRIPT_CHECK=../lib/bromigos/boot/grub-btrfs-titles
    GRUB_BTRFS_SUBMENUNAME="Roll back to a snapshot' --class rollback --id 'bromigos-rollback"
fi
# <<< bromigOS boot menu
```

The `if` guards keep GRUB working if the theme or the package goes away. Without the
package, the entries take their old name again.

The entries themselves come from `grub-mkconfig`. On UEFI, GRUB 2.16 also lists each of
the firmware's boot options, as `… (EFI BootNext)`, before the snapshots. To leave them
out, set `GRUB_DISABLE_BOOTNEXT=true` in `/etc/default/grub`. bromigOS leaves that choice
to GRUB.

If you set `GRUB_TERMINAL=console`, GRUB stays in text mode, and `status` says so.

### The entries' names

`GRUB_DISTRIBUTOR` names the installed system's entries. GRUB's `10_linux` script titles
them after it, so they read like this:

```text
bromigOS Linux
Advanced options for bromigOS Linux
    bromigOS Linux, with Linux linux
```

Each installed kernel gets its own entry under "Advanced options".

The entries also get the class `bromigos`, which shows the emblem. The snapshots'
entries are named by `grub-btrfs-titles`, so they don't change.

The block doesn't rebrand the system underneath, which is Arch Linux:

- The file's own line, `GRUB_DISTRIBUTOR="Arch"`, stays where it is. The block's value
  wins only while the block is there.
- `/etc/os-release` still says Arch Linux.
- `bromigos boot theme off` takes the block out, so the entries say "Arch Linux" again.

A `GRUB_DEFAULT` that names an entry by its title, such as
`"Advanced options for Arch Linux>…"`, stops matching while the block is there. Name the
entry by its id instead. The id is the last quoted word on its `menuentry` line in
`grub.cfg`, and the name doesn't change it.

`grub-install` reads `GRUB_DISTRIBUTOR` too. Run without `--bootloader-id`, it names
GRUB's folder on the EFI partition, and the firmware's boot entry, `bromigOS`. If you
reinstall GRUB and want to keep the old name, give `--bootloader-id`.

### Changes never leave GRUB broken

1. The old file is kept as `/etc/default/grub.bromigos-bak`.
2. `grub-mkconfig` writes a new `grub.cfg` into a separate file.
3. `grub-script-check` checks it.
4. It's written to disk (fsync), then put in place. The old one is kept as
   `grub.cfg.bromigos-bak`.
5. `/boot` is synced before the helper returns.

If either `grub-mkconfig` or the check fails, `/etc/default/grub` goes back as it was,
and `grub.cfg` isn't touched.

## The snapshots in the boot menu

![The boot menu's snapshot list: "Roll back: boot the system as it was, newest first",
then entries for after and before a bromigos update](images/boot-snapshots.webp)

grub-btrfs lists the snapshots in a submenu of their own, "Roll back to a snapshot"
([update.md](update.md) explains the snapshots). Before grub-btrfs keeps a new list, it
runs a syntax check, `GRUB_BTRFS_SCRIPT_CHECK`. bromigOS's block points that at
`/usr/lib/bromigos/boot/grub-btrfs-titles`, which does two things:

1. It rewrites the titles, so they read like the rollback list.
2. It runs `grub-script-check` and returns its answer. grub-btrfs keeps the list only
   when GRUB can read it.

The titles look like this:

```text
ROLL BACK · boot the system as it was, newest first
10/09 00:31 · after bromigos update        --class snapshot-post
10/09 00:28 · before bromigos update       --class snapshot-pre
10/09 00:00 · timeline                      --class snapshot
10/08 23:11 · before pacman -Syu            (a bare pacman run: snap-pac's pair)
```

- The columns (date, snapshot, type and snapper's description) are read from
  grub-btrfs's header row. A title format of your own, or a description containing `|`,
  is left as grub-btrfs wrote it.
- Inside a snapshot's entry, the title is like
  `snapshot 151 · 2026-10-09 00:28 · before bromigos update`, followed by `Boot it: linux`
  and its fallback initramfs.
- `bromigos update` describes its own pair as "bromigos update". It makes the pair itself
  and tells snap-pac to skip that transaction.

## The boot, shutdown and restart splash

`settings/plymouth/bromigos/bromigos.script` draws the Wick's ring and flame on black.
It reads `Plymouth.GetMode()` once when the theme starts:

| Plymouth mode | What it draws below the emblem |
|---|---|
| `boot` | The existing boot progress line, messages and disk passphrase prompt |
| `shutdown` | `SHUTTING DOWN` and a moving activity marker |
| `reboot` | `RESTARTING` and a moving activity marker |

The shutdown marker moves back and forth along the line. It shows activity, not a
percentage or an estimate of how much work is left. Boot progress callbacks cannot
fill it. Messages sit below the action label, so a service message does not cover it.
Other Plymouth modes keep the existing appearance without claiming a power action.

These mode names come from Plymouth's
[script API implementation](https://gitlab.freedesktop.org/plymouth/plymouth/-/blob/26.134.222/src/plugins/splash/script/script-lib-plymouth.c).
Its packaged power-off and reboot units start the daemon with `--mode=shutdown` and
`--mode=reboot`. The theme does not launch or stop any service itself.

### Activate Plymouth on an existing installation

The ISO's installer configures Plymouth already. Installing the theme files on an
existing system does not select them or change the boot configuration.

For shutdown and restart on GRUB systems, `sudo bromigos splash on` selects the
theme and saves the kernel flag. `bromigos splash status` reads the saved and running
settings. `sudo bromigos splash off` undoes its changes. The [splash helper](splash.md)
documents its backups, validation and supported configurations; the
[manual](../manual/src/boot-menu.md#the-startup-and-shutdown-splash) has user instructions.
Reboot once before expecting the new closing visuals. This command does not add
Plymouth to the initramfs.

For a splash during early startup as well:

1. Install Plymouth if needed: `sudo pacman -S plymouth`.
2. For a boot splash, add `plymouth` just after `udev` or `systemd` in the effective
   mkinitcpio `HOOKS` list, before any disk-unlock hook. Preserve the other hooks.
   Check `/etc/mkinitcpio.conf` and its files in `/etc/mkinitcpio.conf.d/`.
3. Add `splash` to the kernel command line, preserving its other arguments. With GRUB,
   edit `GRUB_CMDLINE_LINUX_DEFAULT` in `/etc/default/grub`, then run
   `sudo grub-mkconfig -o /boot/grub/grub.cfg`. Other boot loaders have their own way
   to save kernel arguments. `quiet` reduces kernel text but does not select the splash.
4. Select the theme and rebuild the initramfs:
   `sudo plymouth-set-default-theme -R bromigos`.
5. Reboot when ready. The new kernel arguments apply to that session; subsequent
   shutdowns and restarts can show the graphical splash too.

Plymouth checks the active kernel arguments when selecting a graphical splash during
shutdown as well as boot. Choosing `bromigos` without `splash` can still leave text
output. `plymouth.enable=0`, masked Plymouth services or unavailable graphics can also
prevent the splash. These controls belong to the installation; package updates leave
them alone. Press Escape during a splash to see Plymouth's detailed output.

### Test without touching a desktop or console

```bash
python -m unittest discover -s settings/plymouth/tests
```

The tests load the installed Plymouth `script.so` parser and interpreter. Window,
image, sprite and callback functions are in-memory test doubles; only the maths
library is native. They check the shipped script's syntax and behaviour in boot,
shutdown and restart modes, including progress, activity bounds, messages and the
passphrase prompt at several screen sizes. They never start a daemon or open a display,
console or service. This proves script behaviour; final graphics-driver handover still
depends on the machine. `bromigos-settings` requires Plymouth for its package checks.

## The ISO's menu

The ISO has its own title card, `BROMIGOS // RELAY MEDIUM`, over the Wick's den at night.
It shows the same emblem and meter. [iso.md](iso.md) has a picture of it.

| Firmware | Boot loader | How the menu is made |
|---|---|---|
| UEFI | GRUB (archiso's `uefi.grub`) | `iso/profile/grub/grub.cfg`, with the boot theme's medium variant rendered into `grub/themes/bromigos/` by `iso/build-in-container.sh` |
| BIOS | syslinux (`bios.syslinux`) | vesamenu at 1024x768. `iso/syslinux-theme.py` makes `splash.png` (the same title card) and `bromigos.psf` (Geist Mono as an 8x16 console font). `iso/profile/syslinux/archiso_head.cfg` places the list. |

Both menus have the same entries, in plain words:

| Entry | What it boots |
|---|---|
| Start bromigOS (try it live) | The live desktop. This is the default. |
| Install bromigOS | The live desktop, with the graphical installer open full screen |
| Install bromigOS (text mode) | No desktop (`multi-user.target`): the text installer on the first console, and on the serial console when the kernel's console is there |
| Start with safe graphics (nomodeset) | The live desktop on the firmware's framebuffer |
| Memory test (Memtest86+) | Memtest86+ |
| Boot from disk | The installed system on another disk |
| Start with the screen reader (speech) | archiso's accessibility entry, with the hotkey `s` |
| UEFI shell, UEFI firmware settings, or Hardware information (HDT) | archiso's own entries |
| Shut down, Restart | archiso's own entries |

Some entries need more than archiso gives:

- **Install bromigOS** adds `bromigos.install` to the kernel line. The live user's
  Hyprland autostart, `bromigos-iso-autostart`, sees it and opens the graphical installer;
  any other live boot shows the welcome card instead ([iso.md](iso.md#installing-from-it)).
- **Install bromigOS (text mode)** adds `bromigos.install=text systemd.unit=multi-user.target`.
  `bromigos-iso-text-check.service` decides, with no console of its own, and starts
  `bromigos-iso-text-install@tty1.service` (and `@ttyS0`, when the kernel's console is
  there), which runs the text installer in place of the login prompt. On "Install bromigOS"
  with no graphics (`/dev/dri` empty), it takes tty1 the same way. The console unit is
  never started otherwise: its TTY settings hang the console up, which would end a desktop
  session running there.
- **Memory test on UEFI.** memtest86+-efi 8 names its binary `memtest86x64.efi`, which
  mkarchiso 91 doesn't copy. The build puts it in `grub/` and the menu finds it there.
- **Boot from disk on UEFI** reads the installed system's own `grub.cfg` from another
  disk. A GRUB chainloaded from another GRUB can't find its prefix, so the medium's GRUB
  reads the config directly. If there's no GRUB, it tries systemd-boot, limine, Windows
  or a removable-path loader, then `exit` (the firmware's next device). It runs
  `connectefi all` first, because firmware that booted the medium quickly may not have
  connected the other disks.
- **Boot from disk on BIOS** runs `chain.c32 hd0 0`. Press Tab to pick another disk.

`loopback.cfg` has the same entries, for booting the ISO as a file from another GRUB.
archiso 91 copies everything in the profile's `grub/` folder that isn't a `.cfg` to the
medium's `/boot/grub/`. That's how the theme gets onto the medium.

## Previewing a theme without booting

```bash
settings/grub/build-grub-theme.py --theme-dir themes/mire --out /tmp/t
settings/grub/preview.py --theme /tmp/t --out /tmp/shots
settings/grub/preview.py --theme /tmp/t --menu snapshots --mode 1920x1080 --keys down
```

- `build-grub-theme.py` also takes `--current` (the theme in use) or `--medium` (the
  ISO's title card) instead of `--theme-dir`.
- `preview.py` saves a picture at each of 800x600, 1024x768, 1280x800, 1920x1080 and
  2560x1440, unless you give `--mode`. `--menu` picks `installed`, `snapshots` or
  `medium`. `--firmware bios` previews a BIOS boot.

`preview.py` has GRUB itself draw the theme, with no window:

1. It builds a standalone GRUB with `grub-mkstandalone`, on a folder QEMU shows as a FAT
   disk. On BIOS it uses grub-mkrescue's image.
2. It boots that in QEMU with `-display none`, with OVMF's standard VGA set to each mode.
3. When GRUB reports on the serial port that it's up, it waits `--at` seconds and saves
   the screen through QEMU's monitor.

Its menus are samples of what `grub-mkconfig`, grub-btrfs (with these titles) and the
ISO write.

QEMU runs through `test/vm/vm-keeper.py`, like the other test VMs. The VM stops when
`preview.py` does, even if it's killed, and the keeper's limits apply: 8 GiB for all your
test VMs together (`BROMIGOS_VM_MAX_MEM_GIB`, at most 10), and at least 14 GiB free in
`free -g` before one starts.

## Tests

`settings/grub/tests` runs in the package's `check()`. It covers:

- the theme generator;
- the snapshot titles, checked with the real `grub-script-check`;
- the root helper, in a stand-in root with a stand-in `grub-mkconfig`;
- `preview.py`'s VM: a stand-in QEMU stops when the preview or its keeper is killed.
  These checks are skipped when `free -g` shows less than 14 GiB free.

## Test runs

### 2026-10-09, 11:15 to 11:45 Pacific: the entries' names

Two UEFI systems in `iso/test.sh`'s VM, both on the `edge` channel.

**A machine installed before the change.** It was installed from the earlier test
medium, plain btrfs, with the boot theme on and the entries named "Arch Linux".

1. `bromigos update` brought in bromigos-settings 0.1.0.r51.g68ab3b0.
2. The package's pacman hook rewrote the block, and GRUB showed "bromigOS Linux" after a
   reboot.
3. The migration found the block up to date and finished.
4. `bromigos boot theme off` brought back "Arch Linux", in GRUB's own menu.
5. `bromigos boot theme on` brought back "bromigOS Linux".
6. The block an older package wrote was put back by hand, and the migration rewrote it.

**A fresh install** from a test medium built with those packages, encrypted with LUKS2:

- GRUB's first menu showed "bromigOS Linux" and "Advanced options for bromigOS Linux".
- Off, then on again, each checked after a reboot, as above.
- The checks passed: live 16 of 16, installed 76 of 76, and the first update and its
  rollback 7 of 7.

On both systems, `/etc/os-release` still said Arch Linux, and the snapshot list had no
"Arch Linux" in it. On the first, `grub-install` without `--bootloader-id` named GRUB's
EFI folder `bromigOS`.

### 2026-10-09: the boot menus on UEFI and BIOS

[iso.md](iso.md#test-runs) has the whole run. For the boot menus, it covered:

- the medium's menus and every entry, on UEFI and BIOS;
- installed systems, UEFI encrypted and BIOS plain, with the theme on from the install;
- each at its own mode, and forced to 1024x768, 1920x1080 and 800x600;
- Mire, after a theme switch and an update;
- the snapshot submenu, titled like the rollback list;
- the theme-set hook waiting when sudo needs a password;
- turning the theme off and on again.

All 18 boot theme checks passed on each system, and the installed-system checks were
unchanged (75 of 75 and 74 of 74).
