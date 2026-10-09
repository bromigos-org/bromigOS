# The bromigOS ISO

The ISO is a live and install medium. Boot it, and the full bromigOS desktop is there
before anything is installed. Run `bromigos-iso-install` from it to put bromigOS on a
disk, encrypted by default, with snapshots in the boot menu. Every package an install
needs is on the medium, so installing needs no network.

This page explains how the ISO is built, what's on it, what the installer does and how to
test it. For users, the manual's [Install](../manual/src/install.md) page covers it.
During early access the ISO isn't published; you build it yourself, below.

![The ISO's boot menu: the title BROMIGOS // RELAY MEDIUM over the den at night, the
burn-in emblem, a countdown, and the entries Start bromigOS, Install bromigOS, safe
graphics, memory test and boot from disk](images/iso-menu.webp)

## How it's made

The ISO is archiso's `releng` profile, which the official Arch Linux medium is built
from, with bromigOS laid over it. `iso/profile/` is an overlay that `iso/build.sh` copies
over releng. So the boot loaders, the rescue tools and the drivers are Arch's own, and
they follow archiso's releases.

```text
iso/
  build.sh                  builds the ISO in a privileged archlinux container (Docker)
  build-in-container.sh     the build itself: the offline repository, the profile, mkarchiso
  test.sh                   boots the medium and the installed system in QEMU, headless
  test/live-checks.sh       what the live desktop, and the installed system, must have
  test/screen-wait.py       waits for a boot menu on the VM's screen and saves it
  syslinux-theme.py         the BIOS menu's picture and font
  profile/
    profiledef.sh           the medium's name, boot modes, squashfs options, kernel parameters
    grub/                   the UEFI boot menu: grub.cfg and loopback.cfg
    syslinux/               the BIOS boot menu: archiso_head.cfg, archiso_sys-linux.cfg, archiso_tail.cfg
    packages.x86_64         releng's package list, plus bromigOS and what its desktop expects
    airootfs/               files laid over the live system (below)
```

The important files in `airootfs/`:

| File | What it does |
|---|---|
| `etc/pacman.conf` | Puts the offline repository first and Arch's mirrors after it |
| `etc/sddm.conf.d/live.conf` | Signs the live user in automatically |
| `etc/mkinitcpio.conf.d/archiso.conf` | releng's initramfs hooks, plus `plymouth` |
| `root/customize_airootfs.sh` | Runs in the image at build time: creates the live user, seeds its configs, sets the splash theme |
| `usr/local/bin/bromigos-iso-install` | The installer |
| `usr/local/bin/bromigos-iso-autostart` | Starts the live session, and opens the installer when booted from "Install bromigOS" |
| `usr/local/lib/bromigos-iso/answers.py` | Writes archinstall's config and credentials from the installer's answers |
| `usr/local/lib/bromigos-iso/hardware.py` | Adds this machine's driver packages and services to that config |
| `usr/local/share/bromigos-iso/archinstall.json` | The archinstall config the installer starts from |
| `usr/local/share/bromigos-iso/live-answers.toml` | The live user's first-run answers |

## What's on it

### The boot menus

GRUB on UEFI and syslinux on BIOS both show bromigOS's boot theme, with the same entries:
Start bromigOS (try it live), Install bromigOS, safe graphics, a memory test, boot from
disk, and archiso's own screen reader, firmware and power entries. [boot.md](boot.md#the-isos-menu)
describes each one.

### The live desktop

The user `live` has no password and can use sudo without one, as on any live medium.
SDDM signs it in at boot, into Hyprland with bromigOS's defaults. Its configs are seeded
at build time, the way `bromigos install` seeds them on a new machine ([install.md](install.md)).

- The theme is the Wick, bromigOS's default.
- VECTOR, the desktop's AI assistant, is installed with no brain configured. He says so
  when asked. Once there's a network or a local Ollama, `bromigos setup vector` gives him
  one.
- His voice isn't installed, because it's a large download. `bromigos-holo setup voice`
  installs it.

### The splash and login screen

The boot splash is Plymouth with the Bromigos theme, from `bromigos-settings`
(`/usr/share/plymouth/themes/bromigos`). It shows the lock screen's ring turning around
the flame, and a line that fills as the system boots. The passphrase prompt uses the same
look. The live boot and the installed system both use it. The login screen is
`bromigos-settings`' SDDM theme.

### The offline repository

`/var/lib/bromigos/repo/` holds every package an install needs:

- Arch's `core` and `extra`: everything on the medium and everything an install adds,
  with all their dependencies, in pacman's `$repo/os/$arch` layout, with signatures.
- `bromigos`: every bromigOS package from the channel the medium was built from, including
  `bromigos-homelab` and `herdr`.

The live system's `pacman.conf` lists this repository before Arch's mirrors. The
installer's archinstall config points at it, so an install reads only the medium.
Packages are verified as always (`SigLevel = Required`). bromigOS's key is trusted at
boot by archiso's `pacman-init.service`, which fills every keyring on the system,
including `bromigos-keyring`'s.

### Arch's live tools

archinstall, arch-install-scripts, and the rescue tools and drivers releng ships are all
there (`packages.x86_64`).

## Installing from it

From a terminal on the live desktop (Alt+Shift+Enter), run:

```bash
sudo bromigos-iso-install
```

It asks:

- **the disk**, from a list. The whole disk is wiped.
- **your user name and password**, and the **hostname** (default `bromigos`).
- **"Encrypt the disk?"** The default is yes ([iso-encryption.md](iso-encryption.md)).
  If yes, it asks whether the disk gets its own passphrase or uses your password. The
  passphrase is typed at every boot, and it can't be recovered.
- **keyboard layout, timezone and locale.**
- a last **"Go ahead and wipe it?"**

Then it installs with nothing more to type:

1. **The hardware.** It runs `bromigos hw detect --json` on the live system, whose `/sys`
   is the real machine's ([hardware.md](hardware.md)). `hardware.py` adds that plan's
   packages and services to archinstall's config, so they come from the medium too. For
   example: NVIDIA's open modules for a Turing-or-newer GPU, Intel's or AMD's video
   decoding, a hybrid laptop's `nvidia-prime`, and a laptop's `brightnessctl` and
   `power-profiles-daemon`. The live session itself runs on Mesa, or nouveau on NVIDIA.
2. **archinstall** builds the Arch system, silently, from the config. The layout is
   below. `--menu` opens archinstall's menu instead, filled in with all of it, so you can
   change anything before it installs.
3. **snapper's configuration for `/home`.** The installer creates it, because archinstall
   4.5 can't on this layout. It reads a config file's subvolume names as plain strings,
   so it never finds `@` on `/`.
4. **pacman for updates.** `/etc/pacman.conf` gets Arch's geo mirror plus the stock list,
   and a `[bromigos]` section at the repository the medium was built from, on its
   channel. If the repository has its own CA, the certificate goes into the system's
   trust store. The medium's offline copy isn't carried over.
5. **bromigOS in the new system.** In the new system's chroot, as your user, it runs
   `bromigos install --yes --no-services --no-setup`. That seeds the thin configs, sets
   the desktop settings and the theme, and writes the hardware's system files, such as
   NVIDIA's early KMS. Then `bromigos setup --monitors auto --theme wick --vector none
   --voice off --create none` gives the first-run answers a fresh install can give. You
   can change all of them later with `bromigos setup`.
6. **The splash and the snapshots.** It adds the `plymouth` hook after `udev` and before
   `encrypt`, which asks for the passphrase through Plymouth. It adds `splash quiet` to
   GRUB's kernel line and runs `grub-mkconfig`. Then it runs
   `bromigos rollback setup --yes` as your user, the same command as on any machine
   ([update.md](update.md#how-setup-creates-snappers-configuration)). That creates
   snapper's `root` configuration, lets `wheel` list it, and adds the overlay hook that
   lets a snapshot boot from GRUB's menu.
7. **SSH,** with `--ssh-key FILE`: the key is authorised for your user and sshd is
   enabled, for a headless install.
8. **Loose ends.** The sync databases are dated 1970, so the first `pacman -Sy` fetches
   them afresh. The medium's copies are newer than the servers', so pacman would keep them
   and check the server's signature against the wrong file ("signature is invalid").
   Then it runs `sync`, so everything is on disk before a reboot.
9. **Reboot,** unless you gave `--no-reboot`. Type the disk's passphrase at the splash,
   then sign in at the Bromigos login screen.

### The disk layout

| Part | What archinstall makes |
|---|---|
| Partition table | GPT on UEFI, MBR on BIOS. archinstall 4.5 chooses by the firmware it runs on. On BIOS, GRUB's core image goes in the gap after the MBR. |
| `/boot` | 1 GiB, FAT32, unencrypted. It's the EFI system partition on UEFI. |
| The rest | btrfs, on LUKS2 unless `--no-encrypt` |
| btrfs subvolumes | `@` for `/`, `@home`, `@log`, `@pkg` and `@.snapshots` |
| Boot loader | GRUB, which boots BIOS and UEFI alike and lists the snapshots |
| Kernel | `linux` |

archinstall also installs NetworkManager, PipeWire, zram swap, the bromigOS packages,
snapper, snap-pac, grub-btrfs, inotify-tools and Plymouth. It enables SDDM, Bluetooth,
NetworkManager, snapper's timers and `grub-btrfsd`. There's no desktop profile, because
bromigOS is the desktop.

### Installer options

| Option | What it does |
|---|---|
| `--no-encrypt` | A plain btrfs root, with no LUKS |
| `--menu` | Opens archinstall's menu, filled in, before it installs |
| `--repo URL` | The repository the installed system updates from. The default is the medium's. |
| `--channel NAME` | `stable`, `rc` or `edge`. The default is the medium's. |
| `--ca FILE` | That repository's CA certificate, if it has its own |
| `--with PKG` | An optional package, such as `herdr`. Repeat it for more. |
| `--ssh-key FILE` | Authorises this public key for the new user and enables sshd |
| `--no-reboot` | Stays on the live system when it's done |
| `--dry-run` | Says what it would do |

### Unattended installs

```bash
sudo bromigos-iso-install --config <config.json> --creds <creds.json>
```

These are archinstall's own config and credentials files. `answers.py` writes them, and
the test harness uses it:

```bash
python3 /usr/local/lib/bromigos-iso/answers.py --disk /dev/sda --user <name> \
    --password <password> --out <dir>
```

It also takes `--no-encrypt`, `--passphrase`, `--hostname`, `--keymap`, `--timezone`,
`--locale`, `--firmware uefi|bios`, `--ssh` and `--root-gib N`.

Encryption follows the config. With `disk_encryption` in the config and
`encryption_password` in the credentials, the root is LUKS. Without them, it's plain
btrfs. So an unattended install is always explicit about it.

### Why archinstall

archinstall already handles disks, LUKS, btrfs, boot loaders, locales and users well,
and it's maintained alongside Arch. `bromigos install` already does everything bromigOS
needs. So the medium only joins the two, and asks a few questions in plain words.
archinstall's own menu offers encryption only inside its own disk flow, and a silent run
from a filled-in config keeps the install to what was answered.

## Building it

`mkarchiso` runs as root in a chroot, so the build runs in a privileged `archlinux`
container. Nothing is installed on the machine that runs it. You need Docker.

```bash
iso/build.sh --repo <repo> [--channel stable|rc|edge] [--ca <ca.pem>]
```

`<repo>` is the package repository's base URL, which must be reachable from the build
machine. The medium remembers it as the installed system's repository.

| Option | What it does |
|---|---|
| `--channel NAME` | Which channel's packages go on the medium, and which channel the installed system follows. The default is `stable`. |
| `--ca FILE` | The repository's CA certificate, if it has its own. It goes on the medium too. |
| `--hosts "IP NAME"` | The repository host's address, when DNS doesn't give it |
| `--out DIR` | Where the ISO goes. The default is `~/.cache/bromigos-iso`. |
| `--test-key FILE` | Makes a test build (below) |
| `--keep-work` | Keeps mkarchiso's work directory, to look inside the image |

The result is `<out>/bromigos-<version>-x86_64.iso` and its `.sha256`. Package downloads
are cached in `<out>/cache`, so a rebuild downloads only what changed.

What the build does, in the container:

1. Installs archiso, and trusts the repository: its CA, and its key, which must match
   `packaging/keys/bromigos.asc`.
2. Copies releng and lays `iso/profile/` over it. releng's systemd-boot entries are
   removed, because `uefi.grub` replaces them.
3. Renders the boot menus' pictures and fonts into the profile, with
   `settings/grub/build-grub-theme.py --medium` and `iso/syslinux-theme.py`.
4. Resolves every package it needs against an empty root, so every dependency is
   included, down to glibc. That's `packages.x86_64`, plus what an install adds:
   `archinstall.json`'s packages, what archinstall installs by itself, and every package
   `bromigos hw` can plan for any GPU. The last list sits after a `# bromigos hw:` comment
   in `packages.x86_64`, and a test keeps it in step with `hw.rs`.
5. Downloads and verifies them all, lays them out as the offline repository with
   `repo-add`, and points the build's `pacman.conf` at it.
6. Runs `mkarchiso`.

The squashfs is compressed with zstd, not releng's xz. The offline repository is most of
the image and is already zstd, so xz would gain little and cost minutes.

**A test build** (`--test-key FILE`) lets that SSH key sign in as the live user, turns
sshd on, adds a serial console, and labels the medium `BROMIGOS_TEST`. Build a medium for
people without it.

### What CI checks

`.github/workflows/iso-check.yml` checks the profile on every change to it:

- shellcheck on the scripts;
- the files `profiledef.sh` names;
- archinstall parsing the config, including GRUB, the snapshot packages and `grub-btrfsd`;
- `answers.py`'s layouts (BIOS encrypted and UEFI plain) parsing as archinstall's
  `DiskLayoutConfiguration`;
- `hardware.py` merging a hardware plan into a config;
- the package list resolving against Arch's repositories, and bromigOS's when the runner
  has `ISO_REPO_URL` and `ISO_REPO_CA`.

CI doesn't build or boot the image. mkarchiso needs a privileged container and around
20 GB of disk, and the boot test needs KVM and 6 GB of memory. That's more than the
shared runners have to spare, so those run by hand.

## Testing it

`iso/test.sh` boots a test build in QEMU, headless. It saves screenshots through QEMU's
monitor into `~/.cache/bromigos-isotest/shots/` and never opens a window. The VM has
6 GB of memory, 4 CPUs, virtio-vga with Mesa's software renderer, a USB tablet so it can
click, and a 40 GB disk.

The VM stops when the session that started it ends, as the fresh-machine test's does
([install.md](install.md#the-fresh-machine-test)). `BROMIGOS_VM_OWNER=none` keeps it
running until `down`. Its keeper logs to `~/.cache/bromigos-isotest/keeper.log`.

```bash
iso/test.sh boot --iso ~/.cache/bromigos-iso/bromigos-*.iso --firmware uefi
iso/test.sh install --repo <repo> --ca <ca.pem>
iso/test.sh boot-disk --firmware uefi
iso/test.sh menu --firmware uefi install
iso/test.sh grub <name> down,down,ret
iso/test.sh destroy
```

| Command | What it does |
|---|---|
| `boot` | Boots the medium (`--firmware uefi` or `bios`), waits for the live desktop over SSH, takes a screenshot and runs `test/live-checks.sh` |
| `install` | Installs onto the VM's disk, unattended, over SSH. Encrypted by default; `--no-encrypt` for plain btrfs. |
| `boot-disk` | Boots the installed system, types the passphrase and signs in, takes screenshots, and runs the installed-system checks. Then it runs the first update and rolls it back. |
| `menu ENTRY` | Saves the medium's boot menu, then boots one entry and checks it |
| `grub NAME [KEYS]` | Boots the installed disk to its GRUB menu, presses KEYS, and saves the screen as `shots/grub-NAME.png` |
| `up` | From that menu, boots the default entry, types the passphrase and waits for SSH |
| `shot NAME`, `ssh [cmd…]`, `down`, `destroy` | A screenshot, a command in the VM, power off, or delete the VM |

More about each:

- **`menu ENTRY`** waits for the boot menu with `test/screen-wait.py`, which watches the
  VM's screen until a selection bar shows. ENTRY is `live`, `install`, `safe`, `speech`,
  `memtest`, or `disk` (after an install, the installed system's GRUB). Each check's
  result goes in `menu-ENTRY-FIRMWARE.out`. `BROMIGOS_ISOTEST_VGA` picks the display
  device; the default is `virtio-vga`.
- **`boot`'s live checks** cover Hyprland, the bar, the panels (widgets), the live layer,
  SDDM, the theme, the splash theme, the offline repository, pacman resolving `bromigos`
  from it, bromigOS's key being trusted, and the installer.
- **`install`** has the medium's own `answers.py` write the files for `/dev/vda`. The
  test user is `tester`, with the password `tester`, sshd and the test key. The
  passphrase is the password. After installing, it records what the new system got while
  it's still mounted (`install-state.out`). Then it unmounts, closes the LUKS mapping and
  powers the VM off. Killing QEMU instead once lost the last minute's writes.
- **`boot-disk`** types the passphrase through QMP (skipped for a plain install), clicks
  the account at the login screen and types the password. Over SSH, it runs the live
  checks in their installed-system mode, plus `test/vm/checks.sh` from the fresh-machine
  test ([install.md](install.md#the-fresh-machine-test)).
- **The first update** goes to the other channel (`--update-channel NAME`), because a
  transaction is what makes snapshots, and the medium's own channel may have nothing
  newer. From a `stable` medium it runs `bromigos update --channel edge`. From an `edge`
  medium it runs `--channel stable` after `sudo pacman -Sy`. That tests a move to an older
  channel, which once failed with "signature is invalid". Then `live-checks.sh updated`
  checks the channel, the snapshot pair, the snapshots in `grub-btrfs.cfg`, the update
  recorded for `--rollback`, and a clean `bromigos update --check`.

The installed-system checks include: btrfs with the subvolumes, with LUKS under it (or
none for `--no-encrypt`); snapper's `root` and `home` with `wheel` allowed; snap-pac's
hooks; grub-btrfs and its daemon; `splash` in `grub.cfg`; the plymouth and overlay hooks;
`bromigos rollback status` saying GRUB lists the snapshots with nothing left to set up;
`/boot` unreadable to the user; and one `[bromigos]` section at a channel.

The harness gives the test user sudo without a password for the checks, in
`/etc/sudoers.d/99-isotest`. A normal installed system asks.

To fake a laptop or another machine, `BROMIGOS_ISOTEST_QEMU` adds QEMU arguments, such as
`-smbios file=…` from `test/vm/smbios-chassis.py` ([hardware.md](hardware.md)).

To run a second VM beside another, give it its own directory, SSH port and display with
`BROMIGOS_ISOTEST_DIR`, `BROMIGOS_ISOTEST_PORT` and `BROMIGOS_ISOTEST_VNC`.
`BROMIGOS_ISOTEST_MEM` sets its memory in MiB, 6144 by default.

## Test runs

Newest first. All runs were on a workstation with KVM.

### 2026-10-09, 11:15 to 12:05 Pacific: rolling back from a booted snapshot

The installed disk from the 2026-10-08 BIOS run (plain btrfs, GRUB, `/boot` on its own
FAT partition), under a fresh overlay disk, with 3 GB of memory. This tree's `bromigos`
was copied into the user's home, so the snapshots couldn't roll it back.

- **A normal update, then its snapshot.** `bromigos update --channel edge` changed 20
  packages inside snap-pac's pair 3..4. In the boot menu, **Roll back to a snapshot**
  booted snapshot 3. `/` was grub-btrfs-overlayfs's overlay, and the kernel line ended
  `rootflags=…,subvol=@.snapshots/3/snapshot`. snapper couldn't open `/` there ("IO
  Error (subvolume is not a btrfs subvolume)"), so `snapper rollback` failed too.
- **Made the root.** `bromigos rollback status` said the boot was snapshot 3.
  `bromigos update --rollback` listed the update it undoes and its commands, asked, then
  renamed `@` to `@.before-rollback-20261009-183530` and made a writable copy of
  snapshot 3 as `@`. After a normal boot, `/` was the new `@` (subvolume 271),
  `bromigos-core` was back at r73, the update's new packages were gone, and no unit had
  failed. The update was marked rolled back.
- **pacman's lock.** The next `bromigos update` failed with "unable to lock database".
  snap-pac takes its pre snapshot while pacman runs, so the snapshot holds
  `/var/lib/pacman/db.lck`. The rollback now removes it from the new root. After the
  kernel run below, snapshot 7 still held the lock, the new root didn't, and
  `pacman -Sy` ran.
- **In place, afterwards.** On the new root, `bromigos update --rollback --yes` undid the
  older pair 1..2 as before.
- **A kernel change.** `pacman -U` of linux 7.2.8 over 7.2.9 made pair 7..8. Snapshot 7
  booted with `/boot`'s 7.2.8, found no `vfat` module for it in the snapshot, failed
  `boot.mount` and stopped in emergency mode. From root's shell, `su - tester` and
  `bromigos update --rollback` loaded `vfat`, `nls_cp437` and `nls_ascii` from the
  replaced root, mounted `/boot`, copied 7.2.9's kernel there and rebuilt the initramfs.
  The next normal boot ran 7.2.9, with `/boot` mounted and no failed units.
- After a second rollback, the boot menu listed the first one's replaced root too. That
  root was made by a rollback, so it's a snapshot. Deleting it, as the rollback says,
  takes it off the list.

### 2026-10-09, 11:15 to 11:45 Pacific: the boot menu's names

A UEFI test build on the `edge` channel, 4.0 GiB, with bromigos-settings
0.1.0.r51.g68ab3b0. It was installed encrypted (LUKS2), and GRUB named the entries
"bromigOS Linux" from the first boot.

| | Live | Installed system | First update and rollback |
|---|---|---|---|
| UEFI, encrypted (LUKS2) | 16/16 | 76/76 | 7/7 |

[boot.md](boot.md#test-runs) has the naming checks, and the same change on a machine
installed before it.

### 2026-10-09, 03:55 to 06:30 Pacific: the boot menus

Test builds on the `edge` channel, 4.0 GiB, rebuilt as the runs found problems. Each
firmware ran `menu` for every entry, then `boot`, `install`, `boot-disk` (with the first
update and its rollback), then the boot theme checks on the installed system.

| | UEFI, encrypted (LUKS2) | BIOS, `--no-encrypt` |
|---|---|---|
| The medium's menu | GRUB with the theme, 1280x800 | vesamenu, 1024x768, Geist Mono |
| Boot entries | All pass (19 checks) | All pass (20 checks) |
| Live, installed, update and rollback | 16/16, 75/75, 7/7 | 16/16, 74/74, 7/7 |
| The boot theme | 18/18 | 18/18 |
| GRUB's mode as installed | 1280x800 (`auto`) | 1024x768 (VBE's `auto` was 640x480) |
| GRUB forced to | 1024x768, 1920x1080 | 1024x768, 800x600 |

The boot theme checks covered: on after the install; the block and its backup; `grub.cfg`
loading the theme; the theme and fonts in `/boot`; the update's pair described
"bromigos update"; `theme set mire` then `bromigos update`; the theme-set hook waiting
for the next update without a sudo password; then off and on again.

What it found and fixed:

- Memtest86+ on UEFI: mkarchiso 91 didn't copy memtest86+-efi 8's binary.
- Boot from disk on UEFI: archinstall installs GRUB on the removable path with no firmware
  entry, the firmware may not connect the disk, and a chainloaded GRUB loses its prefix.
  The medium's GRUB now connects the disks and reads the installed `grub.cfg`.
- VBE's `auto` gave 640x480 on BIOS.
- A VM killed right after `bromigos boot theme on` came back with an older `grub.cfg`.
  The helper now syncs.
- The selected entry's icon on the selection bar, and a snapshot's two kernel entries
  (one per microcode) looking the same.

On BIOS, "safe graphics" comes up on the text console, because there's no framebuffer
without KMS there. SSH still works.

### 2026-10-08, 22:57 to 23:08 Pacific: the v0.1.1 candidate

A 3.9 GiB test build on `edge`, the candidate for stable v0.1.1 (`bromigos-core`
r82.gdb950b8, `bromigos-vector` r28.gafc7592). The offline repository held 810 packages,
1.6 GiB.

| | Live | Install time | Installed system | First update and rollback |
|---|---|---|---|---|
| UEFI, encrypted (LUKS2) | 16/16 | 2 min 44 s | 72/72 | 7/7 |
| BIOS, `--no-encrypt` | 16/16 | 1 min 52 s | 71/71 | 7/7 |

- The installer set up rollback with `bromigos rollback setup --yes` in the chroot. It
  recognised the chroot and ran snapper with `--no-dbus`.
- On the installed systems, `bromigos rollback status` said GRUB lists the snapshots,
  even with `/boot` unreadable to the user.
- The first update moved to an older channel (`--channel stable` after `pacman -Sy` on
  `edge`). The old database was dropped, 7 packages went back inside snap-pac's pair, and
  there was no "signature is invalid". `bromigos update --rollback --yes` put `/` back.

The same candidate passed the fresh-machine test too ([install.md](install.md#test-runs)).

### 2026-10-08, 21:31 to 21:44 Pacific: stable v0.1.0

A 3.9 GiB test build on `stable`. The build took 3 minutes with the package cache warm.

| | Live | Install time | Installed system | First update and rollback |
|---|---|---|---|---|
| UEFI, encrypted (LUKS2) | 16/16 | 2 min 15 s | 57/57 | 6/6 |
| BIOS, `--no-encrypt` | 16/16 | 1 min 14 s | 56/56 | 6/6 |

The installed systems booted GRUB, then the Plymouth passphrase prompt (when encrypted),
then the login screen. The first update to `edge` changed 7 packages inside snap-pac's
pair, and `bromigos update --rollback --yes` put them back.

What it found and fixed in the installer and the harness:

- archinstall 4.5 doesn't create snapper's configurations from a config file, and its
  BIOS installs use MBR.
- Writes were lost when the VM was killed. The installer now runs `sync`, and the harness
  unmounts and powers off.
- The medium's sync databases broke the first `pacman -Sy`.
- The user couldn't list snapper's snapshots, so updates weren't recorded. Fixed with
  `ALLOW_GROUPS=wheel`.

What it found outside `iso/`, fixed in the next run:

- `bromigos rollback status` and `bromigos update` said "unknown boot loader", because
  archinstall mounts `/boot` with mode 0700.
- `bromigos update --channel` to an older channel failed with "signature is invalid". A
  switch now drops the old database.
- `bromigos rollback setup` couldn't run in a chroot.
