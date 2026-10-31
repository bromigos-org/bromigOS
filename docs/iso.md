# The bromigOS ISO

The ISO is a live and install medium. Boot it, and the full bromigOS desktop is there
before anything is installed. Run `bromigos-iso-install` from it to put bromigOS on a
disk, encrypted by default, with snapshots in the boot menu. Every package an install
needs is on the medium, so installing needs no network.

This page explains how the ISO is built, what's on it, what the installer does and how to
test it. For users, the manual's [Install](../manual/src/install.md) page and the
[Download page](https://bromigos.org/download) cover it. Every release's ISO is built,
checked, tested, signed and published by CI, as one file at
`https://pkgs.bromigos.org/iso/<version>/` ([A release's ISO](#a-releases-iso)). It
starts with Secure Boot on, and so does the system it installs ([secureboot.md](secureboot.md)). The
same build makes Field Kit with `--edition fieldkit` ([fieldkit.md](fieldkit.md)).

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
  check-medium.sh           unpacks a built ISO and checks what it carries (a release's)
  test.sh                   boots the medium and the installed system in QEMU, headless
  ci-test.sh                CI's tests of a built medium, in a container with KVM
  publish.sh                signs an ISO and publishes it to the bucket; latest.json; what's kept
  release-notes.py          puts a release's ISO on its GitHub Release's text
  secureboot/               shim, and GRUB and the kernel signed (secureboot.md)
  test/live-checks.sh       what the live desktop, and the installed system, must have
  test/screen-wait.py       waits for a boot menu on the VM's screen and saves it
  test/medium-privacy.py    the privacy guard over an unpacked medium
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
Start bromigOS (try it live), Install bromigOS, Field Kit (the same system without the
desktop, for repairs: [fieldkit.md](fieldkit.md#the-full-isos-entry)), safe graphics, a
memory test, boot from disk, and archiso's own screen reader, firmware and power entries. [boot.md](boot.md#the-isos-menu)
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

`pacman-init` runs once the clock is set, after `time-sync.target`. archiso's
`systemd-time-wait-sync` holds that target until a time server answers, and with no
network it would hold it forever, so the keyring would stay empty and archinstall would
stop with "required key missing from keyring". The medium's drop-in
(`etc/systemd/system/systemd-time-wait-sync.service.d/bromigos-iso.conf`) lets it wait 30
seconds at most. The installer starts `pacman-init` before archinstall, so it waits for
the keyring if it isn't ready yet.

### Arch's live tools

archinstall, arch-install-scripts, and the rescue tools and drivers releng ships are all
there (`packages.x86_64`).

## Installing from it

There are three ways in, and they all lead to the same installer:

- **"Install bromigOS"** in the boot menu starts the live desktop with the graphical
  installer open, full screen.
- **"Install bromigOS (text mode)"** in the boot menu starts no desktop. The text installer
  opens on the screen, and on the serial console when the kernel's console is on one. It's
  also used by itself when "Install bromigOS" finds no graphics.
- **On the live desktop**, the welcome card's **Install bromigOS**, the desktop's INSTALL
  panel, or "Install bromigOS" in the app launcher. `sudo bromigos-iso-install` in a
  terminal opens the text installer.

The graphical installer (GTK 4 and libadwaita, in the Settings window's style) and the text
installer (Textual) show the same steps, with the same words and the same checks. Both
follow [DRIFTGLASS](DRIFTGLASS.md): GLOW panels and steps, the emblem as the one FLARE on
the first step, and no motion when motion is reduced. Every control has a hover hint, and
in the text installer the hint line at the bottom says what the focused control does.
Nothing on any disk changes until **Install** is pressed on the summary.

The **Before you start** step (`common.checks`; the plain prompts print the same lines)
asks the medium's `bromigos-iso-secureboot check` ([secureboot.md](secureboot.md)): exit 1
means Secure Boot is on, and its words become a warning (its first paragraph the title, the
second what it means, its link in what to do). Exit 0, a BIOS start, or a medium without
the reader: nothing is shown. The warning never stops the install.

### The steps

1. **Welcome.** The language for the new system, the time zone, and whether there's a
   network. The install doesn't need one: everything is on the USB stick. **Connect to
   Wi-Fi…** is there for the one case that downloads (below).
2. **Before you start**, shown only when there's something to say: running on battery,
   less than 4 GB of memory, a disk whose own health check says it's failing, a graphics
   card bromigOS can't drive well, and whether the machine started the UEFI or the BIOS
   way. Each says what to do. None of them stops the install, except that installing onto a
   failing disk needs **Install on it anyway** on the next step.
3. **What kind of computer is this?** **bromigOS (desktop)**, the default, or **bromigOS
   Server**: no desktop, for servers and lab machines ([Editions](#editions)).
4. **Keyboard.** The layout changes at once, so the box under it tries it.
5. **Where to install.** Every disk, with its size, model and what's on it: Windows, another
   system, files, or empty. The USB stick bromigOS started from is shown but can't be
   chosen. For the chosen disk:
   - **Install alongside Windows** (or the system found) keeps it and its files. If the
     disk has 20 GB or more free, bromigOS goes there. Otherwise the installer makes room
     by shrinking Windows' partition, and a slider sets the split. Windows keeps what it
     uses now plus 10 GB to grow; bromigOS gets at least 20 GB. When it can't be offered,
     the step says why and what to do ([Beside Windows](#beside-windows)).
   - **Erase the whole disk** deletes everything on it and says what will be lost.
6. **BitLocker**, only when Windows on the chosen disk is locked with BitLocker: how to
   save the recovery key, and **I've saved the BitLocker recovery key** before going on.
   Changing how the computer starts can make Windows ask for that key once.
7. **About you.** Your name, user name, password (twice, with a strength hint) and the
   computer's name. The user name and computer name are suggested from your name.
8. **Encryption.** On by default. Your password unlocks the disk, or it gets a passphrase of
   its own ([iso-encryption.md](iso-encryption.md)).
9. **Remote access and protection**, bromigOS Server only: SSH (off by default; keys only
   when on, with keys read from the stick's `fieldkit/` folder or pasted, and a password
   login only when chosen), the firewall (on), and automatic updates with a snapshot before
   each (on).
10. **Summary.** Every choice in plain words, and what the disk loses. The button says
    **Erase disk and install** when the disk is erased.
11. **Installing.** A progress bar and one plain status line (Making room, Encrypting the
    disk, Copying bromigOS onto the disk with a package count, Installing the boot menu,
    Setting up the desktop, Finishing). **Details** shows every line of the install.
12. **Done.** What happens next (take out the stick, the passphrase, the boot menu) and
    **Restart now**. If the install stopped, the screen says where and what to do, and
    **Save a problem report** puts the logs, a hardware summary and the answers (without
    passwords) on a USB drive, and says where it went.

With the speech boot entry (`accessibility=on`), the text installer asks the same questions
one at a time as plain lines (`bromigos-iso-install --plain`), which the screen reader reads
in order. The graphical installer gives every control an accessible name and description
for Orca, works with the keyboard alone (Tab, the arrows, Enter, Esc to go back), and
follows high contrast.

### What it does

The installers write their answers to a file only root can read and run
`bromigos-iso-install --answers FILE`. That script prints `::stage PERCENT words` lines for
the progress bar and one `::error words` line if it stops. Everything else it prints is the
**Details**. Then:

1. **Making room** (alongside, when it shrinks): `disks.py shrink` checks the partition again
   (not BitLocker, not hibernated, clean), shrinks the file system with `ntfsresize` (or
   `resize2fs` for ext4), then the partition with `sfdisk`, and checks the file system
   reads whole. Windows checks its drive once at its next start; that's normal.
2. **The hardware.** It runs `bromigos hw detect --json` on the live system, whose `/sys`
   is the real machine's ([hardware.md](hardware.md)). `hardware.py` adds that plan's
   packages and services to archinstall's config, so they come from the medium too. For
   example: NVIDIA's open modules for a Turing-or-newer GPU, Intel's or AMD's video
   decoding, a hybrid laptop's `nvidia-prime`, and a laptop's `brightnessctl` and
   `power-profiles-daemon`. The live session itself runs on Mesa, or nouveau on NVIDIA.
3. **archinstall** builds the Arch system, silently, from the config `answers.py` wrote.
   The layout is below. Its output goes through `progress.py`, which turns pacman's
   "(n/N) installing" lines and archinstall's own steps into the progress bar.
   `--menu` (with `--config`) opens archinstall's menu instead, filled in with all of it.
   Beside another system, `/boot` is set back to a plain Linux partition (archinstall's
   boot flag made it an ESP's type on GPT) and `GRUB_DISABLE_OS_PROBER=false` goes in
   `/etc/default/grub`, so every `grub-mkconfig` lists the other systems; the menu then
   waits 10 seconds.
4. **snapper's configuration for `/home`.** The installer creates it, because archinstall
   4.5 can't on this layout. It reads a config file's subvolume names as plain strings,
   so it never finds `@` on `/`.
5. **pacman for updates.** `/etc/pacman.conf` gets Arch's geo mirror plus the stock list,
   and a `[bromigos]` section at the repository the medium was built from, on its
   channel. If the repository has its own CA, the certificate goes into the system's
   trust store. The medium's offline copy isn't carried over.
6. **bromigOS in the new system** (the desktop). In the new system's chroot, as your user, it runs
   `bromigos install --yes --no-services --no-setup`. That seeds the thin configs, sets
   the desktop settings and the theme, and writes the hardware's system files, such as
   NVIDIA's early KMS. Then `bromigos setup --monitors auto --theme wick --vector none
   --voice off --create none` gives the first-run answers a fresh install can give. You
   can change all of them later with `bromigos setup`. The keyboard chosen goes to the
   desktop too (`bromigos setup input --set kb_layout …`), and your name to the account.
   bromigOS Server instead runs its edition's `user_commands` as you and starts to the
   text console (`multi-user.target`).
7. **The splash and the snapshots.** It adds the `plymouth` hook after `udev` and before
   `encrypt`, which asks for the passphrase through Plymouth. It adds `splash quiet` to
   GRUB's kernel line and runs `grub-mkconfig`. Then it runs
   `bromigos rollback setup --yes` as your user, the same command as on any machine
   ([update.md](update.md#how-setup-creates-snappers-configuration)). That creates
   snapper's `root` configuration, lets `wheel` list it, and adds the overlay hook that
   lets a snapshot boot from GRUB's menu.
8. **SSH and a server's protection.** With `--ssh-key FILE` the key is authorised for your
   user and sshd is enabled, for a headless install. The installers' SSH answer enables
   sshd too, adds the keys chosen, and, unless a password login was chosen, allows keys
   only. For bromigOS Server, when its `bromigos-server` package is installed, the
   installer writes `/etc/bromigos/server.toml` (`[ssh] password`, `[updates] auto`) and
   runs `bromigos-server setup`, which owns the firewall and the updates. Without that
   package, the installer writes an nftables firewall (replies, ping, and SSH when it's on)
   and enables the edition's update timer if the system has one. When the medium carries
   `bromigos-boot` and `bromigos-fieldkit`, they're installed, and
   `bromigos-fieldkit-boot sync --menu` puts Field Kit on `/boot` with its GRUB and firmware
   entries (Field Kit's own docs); `/boot` is 2 GiB so it fits.
9. **Loose ends.** The sync databases are dated 1970, so the first `pacman -Sy` fetches
   them afresh. The medium's copies are newer than the servers', so pacman would keep them
   and check the server's signature against the wrong file ("signature is invalid").
   The answers, without the password and passphrase, are kept in
   `/var/log/bromigos/install-answers.toml`, an [answer file](#answer-files) that repeats
   the install. Then it runs `sync`, so everything is on disk before a reboot.
10. **Reboot,** unless you gave `--no-reboot` (the installers always do, and restart from
    their last step). Type the disk's passphrase at the splash, then sign in.

### The disk layout

| Part | What archinstall makes |
|---|---|
| Partition table | GPT on UEFI, MBR on BIOS. archinstall 4.5 chooses by the firmware it runs on. On BIOS, GRUB's core image goes in the gap after the MBR. |
| `/boot` | 2 GiB, FAT32, unencrypted. It's the EFI system partition on UEFI. Beside another system: 2 GiB, ext4, in the free space, with the disk's own EFI system partition at `/boot/efi` |
| The rest | btrfs, on LUKS2 unless `--no-encrypt` |
| btrfs subvolumes | `@` for `/`, `@home`, `@log`, `@pkg` and `@.snapshots`; and the data an update's rollback must never touch: `@containers` (`/var/lib/containers`), `@k3s` (`/var/lib/rancher`), `@srv` (`/srv`) and `@bromigos-state` (`/var/lib/bromigos/server`, the update history) |
| Boot loader | GRUB, which boots BIOS and UEFI alike and lists the snapshots |
| Kernel | `linux` |

archinstall also installs NetworkManager, PipeWire, zram swap, the bromigOS packages,
snapper, snap-pac, grub-btrfs, inotify-tools and Plymouth. It enables SDDM, Bluetooth,
NetworkManager, snapper's timers and `grub-btrfsd`. There's no desktop profile, because
bromigOS is the desktop.

### Beside Windows

`disks.py probe` reads every disk (as root: `lsblk`, `sfdisk --json`, `blkid`, `os-prober`,
`smartctl`, and for NTFS `ntfscat`, `ntfsls` and `ntfsresize --info`) and decides, per
disk, whether **Install alongside** can be offered:

| On the disk | What it does |
|---|---|
| 20 GB or more unallocated | bromigOS goes in the largest free stretch; nothing is resized |
| An NTFS (or ext4) partition with room to spare | It's shrunk to what it uses plus 10 GB for Windows (5 GB for another system); the slider picks the split, bromigOS at least 20 GB |
| BitLocker on Windows' partition | Never resized. The step says how to turn BitLocker off, or to shrink C: in Windows' Disk Management, which leaves free space bromigOS can use. Free space beside a BitLocker drive is used, after the BitLocker step |
| Windows paused (Fast Startup or hibernation: `hiberfil.sys` says HIBR) | Not resized. The step says how to turn Fast Startup off and shut down fully |
| A file system that wants a check (dirty) | Not resized. Windows' own check first |
| UEFI machine, MBR disk (or BIOS machine, GPT disk) | Not offered: the two couldn't share a boot menu. The step says which boot-menu entry to start the stick from |
| BIOS machine, MBR disk with three or more partitions | Not offered: MBR holds four, and bromigOS needs two |
| No EFI system partition, or one with under 16 MB free | Not offered, with what to do |

On UEFI, GRUB goes in its own folder on the shared EFI system partition (`EFI/GRUB`) with a
firmware boot entry first in the boot order (`removable: false` in archinstall's
`bootloader_config`): Windows' own files, the fallback `EFI/BOOT/BOOTX64.EFI` among them,
are left alone. On BIOS, GRUB goes in the MBR, as for any second system there; os-prober's
entry chainloads Windows' boot sector.

### Reinstalling

`mode = "reinstall"` (**Reinstall bromigOS and keep my files**) is `reinstall.py`'s, around
archinstall's pre-mounted layout:

1. `prepare` unlocks the root, snapshots `@` read-only as `@old-root-DATE`, moves
   `@.snapshots` to `@old-snapshots-DATE`, makes a fresh `@` and `@.snapshots`, moves the
   old kernels aside on `/boot` (`.bromigos-old-kernels/`), and mounts it all at `/mnt`.
   From the snapshot on, `/run/bromigos-iso/reinstall.json` says what it did.
2. archinstall installs into `/mnt` with no boot loader of its own (`--skip-boot`, which
   lets its configuration say `No bootloader`).
3. `finish` brings back the old system's people (user IDs, groups, passwords) and
   `/home`'s snapper configuration; `boot` sets up the disk's unlocking and GRUB; `tidy`
   removes the old kernels' copy.

If anything stops it between 1 and the end of 3, `bromigos-iso-install` runs `undo`: `@`
is made again from `@old-root-DATE` (the restored `fstab` names it by `subvol=`, since its
ID changed), the old snapshots and kernels go back, and the error says the old system is
back. The installed system starts as it did before.

### Editions

**bromigOS (desktop)** installs `archinstall.json`'s packages and sets up the desktop.
**bromigOS Server** has no desktop. Its packages come from its edition file: the
`bromigos-server` package's `/usr/share/bromigos/fieldkit/edition.json` (from Field Kit's
`iso/fieldkit/packages.toml`), else `/usr/share/bromigos/editions/*.json`, else the
medium's stand-in, `/usr/local/share/bromigos-iso/editions/server.json`. The installer
reads `id` (or `name`), `title`, `summary`, `packages`, `services`, `default_target`,
`user_commands`, `skip_desktop_install` (or `desktop: false`), `meta` (a meta package that
replaces `packages` when it's on the medium) and `check_packages`. The boot, disk and
snapshot packages (`answers.py`'s `REQUIRED`) are always added.

A server's first sign-in, at its console or over SSH, opens its welcome tour
(`bromigos welcome-console`, bromigos-core's; Textual in DRIFTGLASS): the network and its
address, SSH (on or off, keys only, a key pasted in), joining the lab
(`bromigos setup homelab --find`), and what's on the server. The installer leaves
`~/.local/state/bromigos/welcome-pending`; `/etc/profile.d/bromigos-welcome.sh` opens the tour
while it's there. The desktop's own tour is `bromigos welcome`.

Each edition installs offline when its packages are in the medium's offline repository:
the full ISO carries both, the small Field Kit stick carries Server. Only the desktop chosen
on the Field Kit stick downloads: the step says how much, offers Wi-Fi, and with no network
explains it and suggests Server or the full stick. `answers.py --online` points archinstall
at Arch's mirrors and `bromigos-iso-install` puts the repositories first in the live
system's `pacman.conf`.

### Boot parameters

The installers read these from the kernel line, so a boot menu entry can go straight to one
(the menus' direct install entries are Field Kit's and the release's; `iso/test.sh param`
tests each):

| Parameters | What opens |
|---|---|
| `bromigos.install` (or `bromigos.edition=desktop` with it) | The graphical installer on the live desktop, the desktop preselected. On a medium with no login screen (the Field Kit stick), the text installer |
| `bromigos.install bromigos.edition=server` | The text installer on the console, bromigOS Server preselected. The edition step still shows, so it can be changed |
| `bromigos.install bromigos.text`, or `bromigos.install=text` | The text installer, whichever edition |
| `bromigos.answers=PATH` | The [answer file](#answer-files) to use: the install runs by itself after a 10-second countdown with **Cancel** |
| `accessibility=on` | The text installer asks its questions one at a time, for the screen reader |

When the text installer is asked for on a medium with a desktop, the login screen steps
aside for that boot (`systemctl mask --runtime display-manager.service`), so it has the
console. The desktop edition chosen on the small Field Kit stick downloads what isn't on it
([Editions](#editions)).

### Answer files

An answer file installs with no questions. The installer looks for one at
`bromigos.answers=PATH` on the kernel line (a file, or a path on the stick), else at
`bromigos/install.toml` or `fieldkit/install.toml` on a USB partition. It shows a
10-second countdown with **Cancel** first (`countdown = 0` skips it). Every install keeps its
own answers, without secrets, in `/var/log/bromigos/install-answers.toml`: add the password
and it's an answer file.

```toml
[install]
edition = "desktop"          # or "server"
locale = "en_US"
timezone = "America/Los_Angeles"
keyboard = "us"              # an id from bromigos_installer/common.py's KEYBOARDS
disk = "/dev/nvme0n1"
mode = "alongside"           # or "erase"
bromigos_bytes = 68719476736 # alongside, when it shrinks: bromigOS's share
full_name = "Alex Rivera"
user = "alex"
hostname = "alex-pc"
password = "…"               # never written back out
encrypt = true
separate_passphrase = false
passphrase = "…"             # with separate_passphrase
ssh = false                  # Server: ssh, ssh_password, ssh_keys = ["ssh-ed25519 …"],
firewall = true              # firewall, auto_updates
auto_updates = true
countdown = 10
```

The same keys work as flat YAML (`install.yaml`, `key: value` per line).
`common.read_answer_file` checks it and says, in plain words, what's wrong.

### Installer options

| Option | What it does |
|---|---|
| `--answers FILE` | The installers' answers (JSON): what the graphical and text installers run |
| `--text`, `--plain` | The text installer, or its plain questions (a screen reader's) |
| `--menu` | With `--config`: opens archinstall's menu, filled in, before it installs |
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
`--locale`, `--firmware uefi|bios`, `--ssh`, `--root-gib N`, `--alongside [--esp DEV]`,
`--edition FILE`, `--online`, and `--answers FILE` (the installers' JSON).

Encryption follows the config. With `disk_encryption` in the config and
`encryption_password` in the credentials, the root is LUKS. Without them, it's plain
btrfs. So an unattended install is always explicit about it.

### Why archinstall

archinstall already handles disks, LUKS, btrfs, boot loaders, locales and users well,
and it's maintained alongside Arch. `bromigos install` already does everything bromigOS
needs. So the medium only joins the two, and asks its questions in plain words. Its code
is `/usr/local/lib/bromigos-iso/bromigos_installer/`: `common.py` (the steps, words and
checks both installers share), `disks.py` (the disks and making room), `backend.py` (running
the install), `gui.py`, `tui.py`, `plain.py`, `welcome.py` (the live desktop's card) and
`progress.py`. The text installer's DRIFTGLASS look is bromigos-core's
`lib/bromigos_textual.py` (the theme's palette in truecolour, a 16-colour mapping on a bare
console, and the Emitter, Sweep and Reading widgets).
archinstall's own menu offers encryption only inside its own disk flow, and a silent run
from a filled-in config keeps the install to what was answered.

## Building it

`mkarchiso` runs as root in a chroot, so the build runs in a privileged `archlinux`
container. Nothing is installed on the machine that runs it. You need Docker.

```bash
iso/build.sh --repo <repo> [--channel stable|rc|edge] [--ca <ca.pem>]
```

`<repo>` is the package repository's base URL, which must be reachable from the build
machine. The medium remembers it as the installed system's repository, unless
`--medium-repo` names another.

| Option | What it does |
|---|---|
| `--medium-repo URL` | The repository the medium names for the installed system, when it isn't the one the build downloads from: a build that reads a private copy of the channels, say, for a medium that names the public repository. `--ca` then stays in the build and isn't put on the medium. |
| `--version V` | The medium's version, in its file name (`bromigos-V-x86_64.iso`). The default is the build's date. |
| `--channel NAME` | Which channel's packages go on the medium, and which channel the installed system follows. The default is `stable`. |
| `--ca FILE` | The repository's CA certificate, if it has its own. It goes on the medium too, unless `--medium-repo` names another repository. |
| `--hosts "IP NAME"` | The repository host's address, when DNS doesn't give it |
| `--out DIR` | Where the ISO goes. The default is `~/.cache/bromigos-iso`; on a workstation, give a directory on a disk with room (about 20 GB). |
| `--profile DIR` | Another profile, a directory of `iso/` with its own `profiledef.sh`, such as the Field Kit's. The default is `profile`, the desktop medium. |
| `--secureboot-key FILE`, `--secureboot-cert FILE` | Signs the medium for Secure Boot with this key ([secureboot.md](secureboot.md)). Without them, the medium starts only with Secure Boot off. |
| `--test-key FILE` | Makes a test build (below) |
| `--keep-work` | Keeps mkarchiso's work directory, to look inside the image |
| `--edition E` | `desktop` (the default) or `fieldkit`: Field Kit, to fix any computer, run your lab and install a server ([fieldkit.md](fieldkit.md#building-it)) |
| `--local-repo DIR` | A dev build: this checkout's own packages (`packaging/dev-repo.sh`'s, unsigned) in place of `[bromigos]`'s. For tests only; `check-medium.sh` refuses it |

The result is `<out>/bromigos-<version>-x86_64.iso` and its `.sha256`, owned by whoever
ran the build. Package downloads are cached in `<out>/cache`, so a rebuild downloads only
what changed.

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
6. With a Secure Boot key: fetches shim and checks it against its pins, and makes a copy
   of `mkarchiso` that signs the kernel and puts shim, the signed GRUB and the
   certificate on the medium ([secureboot.md](secureboot.md#the-medium)).
7. Runs `mkarchiso`.

The squashfs is compressed with zstd, not releng's xz. The offline repository is most of
the image and is already zstd, so xz would gain little and cost minutes.

**A test build** (`--test-key FILE`) lets that SSH key sign in as the live user, adds a
serial console, and labels the medium `BROMIGOS_TEST`. Build a medium for people without
it. sshd runs on every medium, as on Arch's own, but nobody can sign in over it: `live`
and `root` have empty passwords, which sshd refuses, and only a test build has a key.

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

`iso-check` doesn't build the image. `.github/workflows/iso.yml` does, for every release,
every week and by hand ([A release's ISO](#a-releases-iso)).

## A release's ISO

Every stable release gets its ISO from CI, with nobody at a workstation:
`.github/workflows/iso.yml`. It's an ordinary build with three differences: it carries
the `stable` channel, it names the public repository, and it has no test key.

### Where it finds packages

- **Installing** reads only the offline repository on the medium, so it works with no
  network.
- **Updating** the installed system reads the repository the medium names
  (`/etc/bromigos-iso/repo.url`). For a release that's the public repository,
  `https://pkgs.bromigos.org`, as `install.sh`'s `PUBLIC_REPO` ([public.md](public.md)).
  The build downloads from the same address, so it needs no CA and no private access.

The first v0.1.2 ISO, published on 2026-10-09 before the repository went public, named
the bucket's r2.dev address instead. It was replaced on 2026-10-10. Machines installed
from it move to `pkgs.bromigos.org` on an update, through a migration
([public.md](public.md#the-r2dev-address)).

### What CI does with it

The workflow starts when `packages.yml` has published a `vX.Y.Z` tag's stable channel
(`release-promote` pushes the tag; [release.md](release.md)), so the ISO takes the
release's packages. For each profile under `iso/` (a directory with a `profiledef.sh`:
the desktop medium, and the Field Kit once it's there), side by side:

1. **Build** from the tag, from the public repository, with `iso/build.sh`, signed for
   Secure Boot with bromigOS's key.
2. **Check what's on it** with `iso/check-medium.sh` (below).
3. **Test it** with `iso/ci-test.sh`, in an archlinux container with KVM. The desktop
   medium: UEFI with the network, an encrypted install, the installed system, its first
   update and rollback; then BIOS with no network and a plain install. Then the medium
   once more with Secure Boot on, an install from it that starts with Secure Boot on (its
   key enrolled in MokManager, a kernel update, a Unified Kernel Image), and one beside a
   stand-in Windows ([secureboot.md](secureboot.md#testing-it)). A profile with no installer boots to its menu on UEFI and
   BIOS, then runs its own `ci-test.sh` if it has one.
4. **Sign it** with the package signing key (a detached, armoured `.sig`), and check the
   signature against `packaging/keys/bromigos.asc` alone.
5. **Publish it**: the ISO as one file, its `.sha256`, `.sig` and `.json`, into the
   version's folder of the public bucket. Then it downloads it back from
   `https://pkgs.bromigos.org`, as anyone would, and checks the checksum.
6. **Point at it**: `iso/latest.json` names the newest version's ISOs, the versions past
   the newest three are removed, and the GitHub Release's `ISO:` line gets the links, sizes
   and checksums (`iso/release-notes.py`). The Download page reads `latest.json` and
   follows it within the hour.

The tests' screenshots and output are the run's artifact, `iso-tests-<profile>`. Nothing
is published unless every step before it passed.

It runs on GitHub's hosted runner: the repository is public, so it costs nothing, and the
runner has Docker, KVM and, once the job clears its unused toolchains, the ~30 GB the
build and a test VM need at once. `CI_RUNNER_ISO` can name another runner; it must be one
that only this workflow can use, because a public repository's pull requests must never
reach a homelab runner ([public.md](public.md)).

**By hand** (Actions, iso, Run workflow):

| Input | What it does |
|---|---|
| `channel` | `stable`, a release's ISO; or `edge`, the edge channel's |
| `tag` | The release, for `stable`. Empty: the newest |
| `ref` | Build from this ref's `iso/` instead of the tag's: a fix made after the release, as v0.1.2's was. The packages are still the channel's |
| `publish` | Off: build, check and test only, for any branch |
| `tests` | Off only to publish again a medium already tested |
| `import_release_parts` | Moves an ISO attached to a GitHub Release in parts (v0.1.2's) into the bucket, verified, and removes the parts |

```bash
gh workflow run iso -R bromigos-org/bromigOS -f channel=stable -f tag=v0.1.3 -f ref=main
gh workflow run iso -R bromigos-org/bromigOS -f channel=edge -f publish=false -f ref=<branch>
```

**Edge** is built every Monday from main, from the edge channel, and kept alone: each one
replaces the last. **Pull requests** that change the pipeline build, check and test it, and
publish nothing.

### Where the ISO lives

In the public bucket, `bromigos-pkgs`, beside the packages
([public.md](public.md)). R2 charges nothing for downloads, and takes the 5 GB ISO as one
object, which GitHub's Releases (2 GiB a file) couldn't.

```text
https://pkgs.bromigos.org/iso/
  latest.json                                  the newest stable version's index.json
  0.1.3/
    bromigos-0.1.3-x86_64.iso                  the desktop medium (live and installer)
    bromigos-0.1.3-x86_64.iso.sha256 .sig .json
    bromigos-fieldkit-0.1.3-x86_64.iso         the Field Kit, from the release it first ships in
    index.json                                 every ISO of the version
  edge/
    latest.json
    2026.11.02/bromigos-2026.11.02-x86_64.iso  the newest edge build only
```

Each ISO's `.json`, and the `isos` of `index.json` and `latest.json`, give its `edition`
(`bromigos`, `bromigos-fieldkit`), `file`, `version`, `tag`, `size`, `sha256`, `url`,
`sha256_url`, `sig_url`, `secure_boot`, `secure_boot_installed` (its installer sets the
installed system up for Secure Boot: the stick carries `SECURE_BOOT.txt`) and when it was
built and published.

**What's kept:** the newest three stable versions, and the newest edge build. Older
releases' ISOs are removed from the bucket when a fourth is published. At 5 GB each that's
about 20 GB, well under a dollar a month of R2 storage. To keep a version longer, copy it
elsewhere first, or give `iso/publish.sh pointers --keep N`.

### Checking what's on it

`iso/check-medium.sh` unpacks the ISO (the squashfs in an unprivileged container, as
you) and checks:

- the repository the medium names and its channel;
- no CA, no test key, no `authorized_keys`, no serial console, no `BROMIGOS_TEST` label;
- no package with a proprietary licence in the offline repository;
- the privacy guard (`iso/test/medium-privacy.py`), with the repository's own rules.
  Every text file and file name is checked for the lab's own names (the private
  overlay, `PRIVACY_PATTERNS`, the hashed internal words). bromigOS's files also get
  the whole guard: private addresses, internal host names, MAC addresses and token
  shapes. Arch's packages hit a few everyday words; the report shows those apart;
- the pictures bromigOS puts on it, listed for you to look at: no likeness
  ([ASSETS.md](ASSETS.md)).

```bash
iso/check-medium.sh <iso> --keep <dir>
```

The repository it must name is `install.sh`'s `PUBLIC_REPO` (`--repo` gives another).
A finding in bromigOS's files is fixed where it comes from, then the ISO is built
again. A finding in a package that's already published (a release's, which can't change)
and judged harmless goes in `iso/test/privacy-accepted.txt`, exactly as the guard prints
it, with why. Its path names the package's version, so it never covers a later build.

### Making one by hand

The same steps, on a workstation with Docker and KVM, if CI can't:

```bash
git worktree add ../bromigos-v0.1.3 v0.1.3
../bromigos-v0.1.3/iso/build.sh --repo https://pkgs.bromigos.org \
    --medium-repo https://pkgs.bromigos.org --channel stable --version 0.1.3 \
    --out <dir> [--secureboot-key <key> --secureboot-cert <cert>]
iso/check-medium.sh <dir>/bromigos-0.1.3-x86_64.iso --keep <dir>/check
iso/ci-test.sh <dir>/bromigos-0.1.3-x86_64.iso --out <dir>/tests [--secureboot-cert <cert> [--secureboot-package <pkg>]]
iso/publish.sh sign <dir>/bromigos-0.1.3-x86_64.iso
iso/publish.sh upload <dir>/bromigos-0.1.3-x86_64.iso --channel stable --tag v0.1.3
iso/publish.sh pointers --channel stable --out <dir>/index
iso/release-notes.py --tag v0.1.3 --index <dir>/index/0.1.3/index.json
```

`publish.sh` reads the bucket's and the signing key's secrets from the environment
(its header lists them); the Secure Boot key is in the deployment's secret store
([secureboot.md](secureboot.md#the-key)).

### Downloading it

The [Download page](https://bromigos.org/download) has the newest one, with the steps to
put it on a USB stick from Windows, macOS or Linux and to start a PC from it. Checking it:

```bash
curl -fLO https://pkgs.bromigos.org/iso/0.1.3/bromigos-0.1.3-x86_64.iso
curl -fLO https://pkgs.bromigos.org/iso/0.1.3/bromigos-0.1.3-x86_64.iso.sha256
curl -fLO https://pkgs.bromigos.org/iso/0.1.3/bromigos-0.1.3-x86_64.iso.sig
sha256sum -c bromigos-0.1.3-x86_64.iso.sha256
gpg --import bromigos.asc        # packaging/keys/bromigos.asc
gpg --verify bromigos-0.1.3-x86_64.iso.sig bromigos-0.1.3-x86_64.iso
```

The key's fingerprint is `393E 7D54 F7DE 58FE 75B9 7214 947C 9D61 93D3 DD8B`
([public.md](public.md#the-signing-key)).

## Testing it

`iso/test.sh` boots a medium in QEMU, headless. It saves screenshots through QEMU's
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
- **`boot`** works with any medium. A test build has the harness's key. Any other medium
  gets it from a cloud-init seed (`DIR/seed.iso`, a second CD labelled `CIDATA`), which
  releng's cloud-init reads as on Arch's own medium. So a release's medium is tested as
  it was built.
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
  recorded for `--rollback`, and a clean `bromigos update --check`. With `--update-repo
  URL`, the update reads that copy of the channels instead of the system's own repository
  (and trusts `--ca`): for a medium whose repository can't be reached from the test, such
  as a private one. The checks before it still see the system as installed.
- **`BROMIGOS_ISOTEST_OFFLINE=1`** starts the VM with no network (QEMU's `restrict=on`):
  only the harness's SSH reaches it. With it, `boot` and `install` test the medium the way
  it's meant to install, with no time server and no mirrors.

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
`BROMIGOS_ISOTEST_MEM` sets its memory in MiB, 6144 by default. `BROMIGOS_ISOTEST_OVMF_CODE`
gives another UEFI firmware: `ci-test.sh`'s Secure Boot test uses OVMF's Secure Boot build.

## Test runs

Newest first. Until 2026-10-30 all runs were on a workstation with KVM; since then CI runs
them on GitHub's hosted runner (`iso.yml`).

### 2026-10-30, 11:40 to 16:20 Pacific: the graphical and text installers

The installers of [#27](https://github.com/bromigos-org/bromigOS/pull/27) and their fixes
since, on the workstation's KVM: an ISO built from #27's branch (5.3 GB, 13:52), each run
with the installer copied in from the checkout. The VMs had 2 CPUs and 4 GB, so that two
fit the shared test-VM budget. The stand-in Windows is `iso/test/fake-windows.sh`: an
NTFS partition with 256 MB of files, an EFI system partition with a Microsoft boot stub,
and a recovery partition.

| Scenario | Install | Installed system | Beside Windows |
|---|---|---|---|
| UEFI, graphical, alongside Windows, encrypted (1280×800) | installed | 75 passed, 2 failed (VM) | 7/7 |
| UEFI, graphical, alongside Windows, encrypted (1920×1080) | installed | not run (the sign-in's clicks are for 1280×800) | 7/7 |
| BIOS, text, alongside Windows, plain | installed | GRUB lists Windows 11; desktop checks lost to a slow first session | files unchanged |
| UEFI, text, erase, encrypted | installed | 90 passed, 3 failed (VM) | |
| BIOS, graphical, erase, encrypted (1280×800) | installed | 91 passed, 2 failed (VM) | |
| BIOS, graphical, erase, plain | installed | 89 passed, 3 failed (VM) | |
| UEFI, text, reinstall keeping files, encrypted | installed | 79 passed, 1 skipped | |
| UEFI, a hibernated Windows | refused, in plain words | | |

- **Beside Windows, 7 checks:** Windows' files unchanged (SHA-256), its NTFS consistent
  after the resize, GRUB lists bromigOS and Windows Boot Manager, the EFI system
  partition's files unchanged, GRUB in its own folder with a firmware entry first, one
  EFI system partition.
- **(VM):** the wallpaper check (swaybg, which the live layer replaces on a VM) and the theme
  switcher's preview (no 3D; main now SKIPs it there).
- **Reinstall:** a file in the home folder kept unchanged, the user's ID 1000 kept, the old
  system kept as `@old-root-…`. The first runs found that archinstall 4.5 wants
  `--skip-boot` for "No bootloader" ([#34](https://github.com/bromigos-org/bromigOS/pull/34)). A
  reinstall stopped that way put the old system back, which then passed 77 of 77.
- **Boot parameters**, typed into each firmware's boot menu editor: BIOS
  `bromigos.edition=server` and `bromigos.text`, all passed; UEFI `bromigos.edition=server`,
  `bromigos.text`, `bromigos.edition=desktop`, 12 of 12 once the test typed on the linux line.
- **The menu's Install bromigOS (text mode)**, on BIOS and UEFI: the text installer on tty1
  and on the serial console, no login screen.
- **The welcome tour** on the reinstalled desktop, each step opened in the session:
  pictures of all of them, and it opens by itself when the installer left it pending. With
  the network up it starts at Your screens; VECTOR's "This computer" isn't offered with no
  graphics card; Pair your phone offers to install BRODEC's helper.
- **An answer file** (`bromigos/install.toml` on a second USB stick: bromigOS Server,
  encrypted, SSH with a key) and `bromigos.edition=server`, with no network: the countdown,
  then the install by itself, in about 3 minutes. The installed server's 12 checks passed.
  One of them only after a fix to the test: OpenSSH 10's `sshd -T` capitalises its keywords
  (`PasswordAuthentication no`), and the check compared them in lower case.

### 2026-10-30, 13:14 to 13:40 Pacific: the first ISO built and tested by CI

`iso.yml` on its pull request, on GitHub's hosted runner (4 CPUs, 16 GB, KVM): the stable
channel at v0.1.3 with main's `iso/`, signed for Secure Boot with a throwaway key. 5.0 GB
(5,333,149,696 bytes; 1,007 packages, a 2.4 GB offline repository). The build took
5 min 53 s with a cold cache, `check-medium.sh` 3 min 41 s, the tests 16 min.

| | Live | Install | Installed system | First update and rollback |
|---|---|---|---|---|
| UEFI, encrypted (LUKS2) | 16/16 | passed | all passed, 1 skipped | passed |
| BIOS, `--no-encrypt`, with no network for the live session and the install | 16/16 | passed | all passed, 1 skipped | passed |
| Secure Boot on, Microsoft's keys only: MokManager, the key enrolled from the medium | 16/16 | | | |

- The skipped check is the theme switcher's preview: the nested desktop it draws can't
  start on a VM display with no 3D (QEMU's virtio-vga), with Hyprland 0.57 and Mesa 26.2.
  It reproduced the same way on the workstation. On a VM it's now a SKIP with that reason.
- The guard's one finding in bromigOS's files, Docker's default bridge address in the
  widgets' demo data, is accepted for v0.1.3's package and fixed at the source.
- With Secure Boot on, the menu was GRUB's plain one: lockdown loaded no font. Media
  built since carry the fonts inside GRUB ([secureboot.md](secureboot.md#the-medium)). The
  firmware said Secure Boot was on, and the key was in the MOK list.

### 2026-10-10, 00:48 to 01:01 Pacific: v0.1.2's ISO, naming pkgs.bromigos.org

The ISO now on the v0.1.2 Release, which replaced the first one below. It was built from
the public repository, `https://pkgs.bromigos.org`, which it names. The packages are the
same v0.1.2 ones, without `1password`, which the public repository leaves out. 4.3 GB,
with `iso/` from main. The build took 6 min 21 s with a cold cache.

| | Live | Install time | Installed system | First update and rollback |
|---|---|---|---|---|
| UEFI, encrypted (LUKS2) | 16/16 | 3 min 17 s | 76/76 | 7/7 |
| BIOS, `--no-encrypt`, with no network for the live session and the install | 16/16 | 2 min 36 s | 75/75 | 7/7 |

- The installed systems named `https://pkgs.bromigos.org/$repo/stable/$arch`, and the
  first update read from it, with no `--update-repo`.
- `iso/check-medium.sh` passed every check but the guard, which found the same five lines
  in the same packages as the first ISO's run (below).
- **The migration, on a machine installed from the first ISO.** That system, as installed,
  named the r2.dev address on `stable`. `bromigos channel edge` kept the address, and
  `bromigos update` brought `bromigos-core` 0.1.2.r158.g2a3b405, which has the migration.
  The update ran `20261010080000-public-repo-address`, and the `Server` line became
  `https://pkgs.bromigos.org/$repo/$arch`. `/etc/pacman.conf.bromigos-r2dev` held the old
  file, one line different. The next `bromigos update` synced from `pkgs.bromigos.org`
  and had nothing to do ([public.md](public.md#the-r2dev-address)).

### 2026-10-09, 19:02 to 19:46 Pacific: v0.1.2's first ISO

The first release's medium, replaced on 2026-10-10 (above): the `stable` channel at
v0.1.2 (`bromigos-core` 0.1.2.r143.g07924b0, `bromigos-vector` 0.1.2.r58.g172967c),
naming the bucket's r2.dev address, with no test key. 4.3 GB (4,321,310,720 bytes), with 827
packages in the offline repository (2.0 GB). The build took 3 min 35 s with the cache
warm. Its `iso/` is main's: the tag's, plus the keyring fix below. The packages are the
tag's.

| | Live | Install time | Installed system | First update and rollback |
|---|---|---|---|---|
| UEFI, encrypted (LUKS2) | 16/16 | 2 min 21 s | 76/76 | 7/7 |
| BIOS, `--no-encrypt`, with no network for the live session and the install | 16/16 | 1 min 52 s | 75/75 | 7/7 |

- The harness gave the medium its key through cloud-init. The installed systems named the
  r2.dev address, on `stable`. Before go-live that address wasn't public yet, so the first
  update read the homelab's copy (`--update-repo`), moved to edge, and was rolled back.
- `iso/check-medium.sh`: the public address, `stable`, no CA, no keys, no serial console,
  and no proprietary package (`1password` isn't on it). The guard found nothing in the
  live system's own files. In bromigOS's packages it found an example MAC address in
  `bromigos bluetooth`'s help, and in the three manual pages made from it, and an address
  in a test of VECTOR's guard. Both are made up, and both have since changed on main. The
  lab's name appears only as the lore's public place. In Arch's packages it found 18
  everyday words in word lists and hardware databases. The pictures were the den with the
  chair empty, the worlds' art and the emblems: no likeness.

What it found and fixed:

- **An install with no network failed**: archinstall stopped with "keyring is not
  writable" and "required key missing from keyring". archiso's `pacman-init` waits for
  `time-sync.target`, which waits for a time server, so with no network the live
  system's keyring stayed empty. Every earlier run had a network, so it never showed. The
  medium now waits 30 seconds at most, and the installer waits for the keyring
  ([The offline repository](#the-offline-repository)). The ISO was built again with the
  fix and every test run again; the table is the second build's.
- The live check of bromigOS's key ran before `pacman-init`, when the VM's clock synced
  80 s after boot. The check now waits for it.
- The harness's cloud-init seed needed its own port on q35's AHCI controller.

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
