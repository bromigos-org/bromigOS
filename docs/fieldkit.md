# Field Kit

Field Kit: Repair. Recon. Deploy. Fix any computer, run your lab, install a server. No internet needed. It's a small medium for a USB stick, and an entry
in every bromigOS boot menu. It boots to a themed text console and opens on a Home screen
with seven sections:

- **Repair**: unlock and fix a bromigOS install that won't start properly. A black screen,
  a broken boot menu, a bad update, a failing disk. Disk imaging, secure erase and Windows
  repair too.
- **Lab**: the lab console, provisioning a lab machine, the model catalog, the network.
- **VECTOR**: bromigOS's assistant, in the terminal. He reads what Field Kit sees and
  proposes fixes you approve.
- **Tools**: the toolbelt: system monitors, disk and network tools, editors, file recovery.
- **Server**: install bromigOS Server, or look after the one this is ([server.md](server.md)).
- **Install**: install bromigOS Server (no desktop, for servers and lab machines) from the
  stick, with no network; or the full desktop, which downloads it.
- **Shell**: a command line, remote help, power.

Everything that doesn't talk to another machine works with no network at all. The medium
carries its own offline package store, so even installing needs none.

This page is for contributors. The manual's [Field Kit](../manual/src/fieldkit.md) page is
for people using it, and [server.md](server.md) covers bromigOS Server.

## Where it starts from

| From | How | What's there |
|---|---|---|
| Its own medium | `bromigos-fieldkit-<version>-x86_64.iso` on a USB stick, or through Ventoy | Everything, with the offline store |
| The full ISO's boot menu | "Field Kit (repair, lab and tools)" | The full medium's own system, started without the desktop |
| An installed system's boot menu | "bromigOS Field Kit" (package `bromigos-fieldkit`) | Everything but the offline store, started from `/boot` |

### The medium's boot menu

GRUB on UEFI and syslinux on BIOS, both with the boot theme's medium variant titled
`BROMIGOS // FIELD KIT` ([boot.md](boot.md#the-isos-menu)):

| Entry | What it does |
|---|---|
| Start Field Kit | The default |
| Install bromigOS Server | The text installer, Server preselected (`bromigos.install bromigos.edition=server`); with `/fieldkit/install-server.toml` on the stick (an [answer file](iso.md#answer-files) with `edition = "server"`) it says "unattended", becomes the default and counts down |
| Start Field Kit · then unplug the stick | archiso's `copytoram=y`: the whole system is read into memory first |
| Start Field Kit · remote help over SSH | `bromigos.remote=on`: see [Remote help](#remote-help) |
| Start with basic graphics (if the screen stays black) | `nomodeset` |
| Test this computer's memory | Memtest86+ |
| More options › | The system on this computer's disk, the screen reader (S), the UEFI shell, the firmware settings, power |
| Help: what do these do? | A page with a paragraph per entry (H). On BIOS, a help line under the list for the highlighted entry. |

`iso/grub-menus.py` writes these menus, and the full medium's, from one description.

The kernel line always has `module_blacklist=nouveau`. NVIDIA cards stay on the firmware's
display, so the console never waits for NVIDIA's large firmware, which Field Kit doesn't
carry. It also has `vt.default_red`, `vt.default_grn` and `vt.default_blu`: DRIFTGLASS's 16
colours on the console from the kernel's first message.

### The full ISO's entry

The full medium's entry boots its own squashfs with `bromigos.fieldkit` and
`systemd.unit=multi-user.target`. So there's no second system on the medium: it costs
only the engine and a few tools in its package list. The first console's getty runs
`fieldkit-getty`, which signs root in when `bromigos.fieldkit` is on the kernel's command
line and gives the usual login prompt otherwise. Root's `.zlogin` starts the menu.

### In the installed system's boot menu

GRUB can't read an encrypted root, so Field Kit has to live on `/boot`. The package
`bromigos-fieldkit` carries Field Kit for `/boot` in `/usr/share/bromigos/fieldkit/boot/`:

| File | What it is |
|---|---|
| `fieldkit/boot/x86_64/vmlinuz-linux`, `initramfs-linux.img` | The medium's kernel and initramfs, which GRUB starts |
| `fieldkit/x86_64/airootfs.sfs` | The medium's system, made again without the offline store |
| `fieldkit/boot-<id>.id`, `fieldkit/cmdline` | A file unique to the build, and the kernel's command line that finds it |
| `EFI/bromigos-fieldkit/fieldkit.efi` | A Unified Kernel Image: the same kernel, initramfs and command line in one EFI program |

The initramfs finds the system by that file (archiso's `archisosearchfilename`), not by a
disk's UUID. It reads the system into memory (`copytoram`, about 1 GiB), so `/boot` isn't
held mounted read-only while Field Kit repairs it. So the command line is the same on every machine, and the UKI is made, and can
be signed, when the medium is built.

bromigos-boot's pacman hook (`bromigos-boot-menu.hook`) runs
`/usr/lib/bromigos/boot/bromigos-fieldkit-boot sync`:

1. It checks the room on `/boot`. The copy needs its own size, plus the biggest kernel or
   initramfs already there (a kernel update writes one more), plus 32 MiB. If that isn't
   free, it copies nothing and says, in one line, how much it needs. It never fails the
   transaction.
2. It copies the files beside the old ones, checks them against the package's, and swaps
   them in: `fieldkit/` to `/boot/fieldkit/`, and the UKI to `/boot/EFI/bromigos-fieldkit/`
   where `/boot` is the EFI system partition.
3. **The firmware's boot menu.** On UEFI, it adds a boot entry, "bromigOS Field Kit", for
   the UKI (`efibootmgr --create`), then puts the boot order back as it was, with Field Kit
   last. bromigOS stays first. Field Kit then shows in the PC's own boot menu (F8, F11,
   F12…) beside "bromigOS", so it starts even when GRUB is broken.
4. **GRUB's menu.** It makes `grub.cfg` again, the same safe way the boot theme does (aside,
   checked by `grub-script-check`, then swapped in). `42_bromigos-fieldkit` writes the entry,
   and the "More ways to start" submenu has it too:

```text
menuentry 'bromigOS Field Kit 0.1.3 (repair, lab and tools)' --class fieldkit --id 'bromigos-fieldkit' {
    search --no-floppy --file --set=root /fieldkit/boot/x86_64/vmlinuz-linux
    linux /fieldkit/boot/x86_64/vmlinuz-linux archisobasedir=fieldkit archisosearchfilename=/fieldkit/boot-<id>.id module_blacklist=nouveau vt.default_red=… copytoram=y bromigos.fieldkit=disk
    initrd /fieldkit/boot/x86_64/initramfs-linux.img
}
```

The title carries the version. Neither entry can go stale: Field Kit is a package, so every
`bromigos update` brings the current one, and the hook copies it to `/boot` and makes both
entries current. Removing the package removes the copy, the UKI, the firmware's entry and
the GRUB entry.

`bromigos fieldkit status` says where it stands. `sudo bromigos-fieldkit-boot remove` takes
it off `/boot`; the next `sync` puts it back.

**Secure Boot.** The UKI is one EFI program, so the release pipeline signs it with the same
key as the rest of the chain before it packages it (`sbsign`, on the medium's build
machine). An unsigned UKI starts only with Secure Boot off.

#### How much room

The ISO installer makes `/boot` 1 GiB. A kernel with its initramfs and fallback image uses
about 200 MiB of it, or 400 MiB with NVIDIA's early KMS modules. Field Kit for `/boot` is
about 1.1 GiB (the system 974 MiB, the kernel and initramfs 57 MiB, the UKI 57 MiB), so it doesn't fit a 1 GiB `/boot`, and the hook says so. New
installs need `/boot` at **2 GiB**: the installer is asked to make it that size. Machines
installed with 1 GiB keep working and start Field Kit from a stick.

## What's on it

[fieldkit-packages.md](fieldkit-packages.md) lists every package with its size and the
reason it's there. A package goes on the medium only when one of these needs it:

1. a Field Kit menu item;
2. booting and hardware support on unknown machines: the kernel, firmware, network,
   storage and graphics drivers, and accessibility (speech and braille);
3. bromigOS Server, the installed edition;
4. a documented server or lab job.

The list's one source is `iso/fieldkit/packages.toml` (with `server-packages.toml`).
`iso/fieldkit/manifest.py` makes the medium's `packages.x86_64`, bromigOS Server's package
list in `edition.json`, and the manifest page from it, with the sizes the build records.

### The offline store

The medium carries `/var/lib/bromigos/repo/`, as the full ISO does
([iso.md](iso.md#the-offline-repository)): every package on the medium and every package
bromigOS Server installs, with all their dependencies, signed, read with
`SigLevel = Required`. It also has what archinstall installs by itself (`linux-firmware`,
the microcode, zram) and the NVIDIA driver for a lab machine with an NVIDIA card.

## The console

Field Kit's console is kmscon, not the kernel's text console. kmscon draws the terminal on
the graphics card with real fonts: Geist Mono through FreeType, at a size picked for the
screen, with full Unicode, box drawing and 24-bit colour. Its 16 colours are DRIFTGLASS's.
Fedora has proposed kmscon as its default console, and Arch packages a current release (10).

Where kmscon can't start (no graphics device: `nomodeset` on BIOS, a serial console),
`kmsconvt@`'s own `OnFailure=` starts getty, which is still bromigOS: the same 16 colours
set with `setvtrgb`, and Geist Mono as a console font. [console.md](console.md) explains
both.

The menu's screens use the full palette where the terminal has true colour (kmscon, SSH
from a modern terminal, herdr) and the 16 colours on the kernel's console.

## The menu

The menu is `bromigos fieldkit`, a screen in bromigos-core built with ratatui and the shared
DRIFTGLASS widgets in `core/crates/bromigos-tui`, the same ones `bromigos bluetooth tui` uses.
Every screen has the same frame: a top bar with the title, the version, a breadcrumb
(Home › Repair) and status chips, and a bottom bar with "? keys and help" and a hint for the
highlighted item. State is on the left, actions on the right.

**Home** is a dashboard, not a list:

- chips: the network (wired, Wi-Fi or none), SSH on or off, REMOTE HELP ON in the warning
  colour while it's on, the stick's settings, the clock;
- the orb, VECTOR's hologram, beside "FIELD KIT": the screen's one FLARE;
- "This computer": the board, the processor and how busy it is, the memory and how much is in
  use (small meters), the graphics cards, the temperatures with their last few readings as a
  tiny line, and each disk as one bar of its partitions (bromigOS, Windows, EFI…, the free
  space dim);
- "Found on this computer": each install and system on the drives with its logo (bromigOS,
  encrypted and locked or open; Windows, with BitLocker on or off), USB sticks and Field Kit
  sticks, and the drive's own health verdict when it gives one (healthy, or FAILING);
- "Suggested", only when something real was found (a last boot that didn't finish, a hot
  processor), with the action that helps;
- seven tiles: Repair, Lab, VECTOR, Tools, Server, Install, Shell. With room they grow: an
  icon line, the name, and the line about it. The highlighted one glows.

The facts come from `fieldkit-engine engine overview`, read at start and every 15 seconds in
the background. Nothing is mounted or unlocked to find them. The drives' verdicts are a quick
`smartctl -H` each, asked once every ten minutes.

**Keys.** R, L, V, T, S, I and X open Repair, Lab, VECTOR, Tools, Server, Install and Shell
from anywhere, except while typing in a text field, where Alt+letter does the same
(Alt+letter works everywhere). On Home, 1 to 7 open the tiles and F runs the suggestion.
`?` or F1 opens the keys for the current screen. The letters aren't printed on the tiles:
the bottom bar shows an item's shortcut when it's highlighted or under the mouse pointer.

**Icons** are Nerd Font glyphs: kmscon falls back to Symbols Nerd Font Mono for them, and
Geist Mono draws the text. On the kernel's console, and in ASCII mode, each icon has a
plain character instead.

**DRIFTGLASS:** the orb on Home is the screen's one FLARE; sections and items are Glass panels
(GLOW); the status line and chips are EMBER, with a Reading glow for a state. A finished job
gives one Spark. Under reduced motion (`bromigos.motion=reduced` on the kernel's command
line, or the install's own setting) nothing moves: the orb holds still. On the kernel's
console and in ASCII, the orb is a ring of plain characters and the meters are plain blocks.

On the medium's first console, `fieldkit-engine console` runs the menu, then a shell when you
leave it, then the menu again. A menu that's missing or fails at once is never retried in a
loop: one panel says what happened and what to do, and after three quick failures the
console stays a shell (`fieldkit` tries again).

### How it's built

The screens are Rust. The jobs behind them are `fieldkit-engine` (package
`bromigos-fieldkit-tools`, Python), which answers in JSON:

```text
bromigos fieldkit  ──runs──▶  /usr/lib/bromigos/fieldkit/fieldkit-engine engine VERB …  ──▶  one JSON document
```

Long jobs print progress lines first. The engine's verbs are listed at the top of
`fieldkit/lib/bromigos_fieldkit/engine.py`. The same jobs work as text, for a console or SSH:

```bash
bromigos fieldkit why                 # what went wrong on the last boot
sudo bromigos fieldkit black-screen   # the black screen checks (--fix applies every fix)
bromigos fieldkit status              # Field Kit in this machine's boot menu
sudo bromigos fieldkit make-stick /dev/sdX
sudo bromigos fieldkit remote on|off|status
```

Programs people already know (btop, htop, nvtop, gdu, micro, Neovim, tmux, lazygit,
TestDisk) are in Tools for those who want them, themed through their own config files.
Nothing in Repair needs them.

### Shapes shared with the installer

The installer's screens (Python, Textual) draw the same orb, emblem and disk map as Field
Kit's, from the same source. The shapes live in Rust, in `bromigos-tui`, and one command
prints them as JSON:

```bash
bromigos fieldkit shapes --json --orb 22x11 --frames 24
```

It gives the palette in use (the theme's colours, the console's 16, and whether braille shows
here), the emblem's braille rows and the wordmarks, the orb's frames at that size (its rows,
and which cells glow; one frame every 0.12 seconds) with the plain ring's, and the disk map's
rules (each kind of partition, its colour and label, and how the cells are shared out).

`lib/bromigos_drift.py` (in bromigos-core, next to `bromigos_textual.py`) asks once, keeps
the answer, and gives rich Text:

```python
import bromigos_drift as D
D.orb_text(i)               # the orb's frame i: braille, or the plain ring on the console
D.emblem_text()             # the emblem, or the wordmark
D.disk_map_text(disk, 40)   # a disk from lsblk -J -b, as one bar of its partitions
```

Without `bromigos`, the orb is empty, the emblem is the plain wordmark, and the disk map
follows the same rules from a copy kept in the module.

### Every action as a command

Every screen action is also a command, for SSH and for the stick's startup scripts. `--json`
prints the engine's JSON; `--dry-run` prints the exact commands and what they touch, and runs
nothing; `--yes` skips the question a change asks (without a terminal and without `--yes`,
nothing changes). In the screens, `c` shows the same commands for the highlighted action,
copies them, or opens a shell with them ready to run step by step.

| Screen | Command |
|---|---|
| Home | `bromigos fieldkit overview [--json]` |
| Mount my bromigOS install | `bromigos fieldkit mount /dev/nvme0n1p2` (the passphrase on standard input) |
| Unmount my install | `bromigos fieldkit unmount` |
| What went wrong on the last boot? | `bromigos fieldkit repair last-boot` |
| Fix a black screen | `bromigos fieldkit repair black-screen [--fix [ID…]]` |
| Roll back to a snapshot | `bromigos fieldkit repair rollback N` |
| Repair the boot menu | `bromigos fieldkit repair boot-menu` |
| Change the boot options | `bromigos fieldkit repair boot-options [--set WORDS…]` |
| Check disks | `bromigos fieldkit disks`, then `bromigos fieldkit scrub` |
| Back up my files | `bromigos fieldkit backup /dev/sdb1` |
| Copy or image a disk | `bromigos fieldkit image list|targets|create|verify|restore|clone …` |
| Erase a disk securely | `bromigos fieldkit erase plan DEV`, then `erase run DEV --confirm NAME --method M` |
| Windows repair | `bromigos fieldkit windows find|users|reset-password|unlock-bitlocker|ntfsfix|boot-entries|boot-fix …` |
| Remote help | `bromigos fieldkit remote on|off|status` |
| Make a Field Kit USB stick | `bromigos fieldkit make-stick DEV [--wifi SSID:PASSWORD] [--remote]` |
| VECTOR | `bromigos fieldkit vector`; his queue: `fieldkit-engine engine vector pending|decide|run` |

`fieldkit` is the same as `bromigos fieldkit`. Underneath, each runs
`/usr/lib/bromigos/fieldkit/fieldkit-engine engine VERB`, whose verbs are listed at the top
of `fieldkit/lib/bromigos_fieldkit/engine.py`.

### The kernel parameters Field Kit reads

| Parameter | What it does |
|---|---|
| `bromigos.fieldkit` | The full medium: start in Field Kit's menu (with `systemd.unit=multi-user.target`) |
| `bromigos.fieldkit=disk` | Started from an install's `/boot`: the menu suggests opening that install |
| `bromigos.remote=on` | Remote help from the start |
| `bromigos.install bromigos.edition=server|desktop` | Start the installer with that edition (the installer's) |
| `bromigos.answers=/fieldkit/install-server.toml` | The answer file the menu found on the stick: the installer runs it unattended, after its own countdown with **Cancel** ([iso.md](iso.md#answer-files)) |
| `bromigos.motion=reduced` | No animation anywhere |
| `copytoram=y` | archiso: read the whole system into memory first |
| `module_blacklist=nouveau`, `vt.default_*` | Field Kit's defaults: the firmware's display for NVIDIA, DRIFTGLASS's colours |

### Repair

| Item | What it does |
|---|---|
| Mount my bromigOS install | Finds encrypted and btrfs partitions, asks for the passphrase, and mounts the install as its own `fstab` does, at `/mnt/bromigos`, with btrfs's top level beside it for snapshots |
| What went wrong on the last boot? | The install's own journal for its latest boot: failed units, graphics driver errors, crashes, whether it shut down cleanly |
| Fix a black screen / blinking cursor at startup | The checks below |
| Roll back to a snapshot | Lists snapper's snapshots and makes one the system, as `bromigos update --rollback` does, then makes the kernel in `/boot` match it |
| Repair the boot menu | Reinstalls GRUB from the install's own package (on the removable path when that's how it was installed) and makes the menu again |
| Change the boot options | `GRUB_CMDLINE_LINUX_DEFAULT`, with presets and a hint for each |
| Edit a file on my install | micro, with highlighting, in DRIFTGLASS; the file is backed up first |
| Check disks | Each drive's own health (SMART), then btrfs's scrub, read-only |
| Back up my files to a USB drive | Every home folder, with rsync |
| Copy or image a disk | Clonezilla's image format (below) |
| Erase a disk securely | The drive's own erase where it has one (below) |
| Windows repair | Below |
| Graphics: what's in this machine | Each card, its driver and its connected monitors |

**Every change keeps a backup first**, inside the install, in
`/var/lib/bromigos/fieldkit-backups/<when>-<what>/`, at each file's own path.

A check's findings each have a mark: ✓ fine (or fixed), ▲ a problem with a fix, ✕ a problem
without one (`ok`, `!` and `x` in ASCII). A fix that works flashes its ✓ and the panel's edge
for a second.

#### The black screen

A real case started this: the desktop came up as a black screen with a blinking cursor.
The repair checks each cause that has done it:

- **A leftover login screen setting.** SDDM reads every file in `/etc/sddm.conf.d`,
  whatever its name, so renaming one to `.disabled` doesn't switch it off. The fix moves the
  file out, into the backup.
- **A graphics card pinned with no monitor on it.** It reads the user's Hyprland GPU
  environment (`~/.local/state/bromigos/hw/hyprland.lua`), their Hyprland config and
  `environment.d`, and SDDM's settings, for `AQ_DRM_DEVICES` and similar. It compares the
  pinned card with the cards that have a connected monitor now (`/sys/class/drm`). A pin
  by number (`/dev/dri/card1`) is flagged too, since numbers can change between boots.
  The fix comments the pin out.
- **The startup files' module list.** `MODULES=()` in `/etc/mkinitcpio.conf` (and
  `mkinitcpio.conf.d`) naming a package (`nvidia-open`) instead of a module (`nvidia`), or
  a module this kernel hasn't got. The fix corrects the line and builds the startup files
  again (`mkinitcpio -P` in the install).
- **Startup files missing or older than the kernel.**
- **The NVIDIA driver not built for the installed kernel.** With DKMS, the fix builds it.
- **No login screen enabled**, or the machine set to start without the desktop.

It reads the install's journal for the failed boot (`journalctl -D` on the mounted install;
its latest boot is the failed one) in "What went wrong on the last boot?".

### Disk imaging, in Clonezilla's format

`fieldkit/lib/bromigos_fieldkit/imaging.py` saves a whole disk or one partition with
partclone, in the layout Clonezilla's `ocs-sr` writes: `disk`, `parts`, the partition table
(`<disk>-pt.sf`, the MBR and the data after it, or both GPT copies), the info files and
`clonezilla-img`, and each partition as `<part>.<fs>-ptcl-img.zst.aa…`. So Clonezilla and
Rescuezilla can restore Field Kit's images, and Field Kit restores theirs. Images go to a
USB drive, another disk, or a share on the local network (SMB or NFS). Each is checked
with `partclone.chkimg` after writing. Restoring and cloning ask for the target disk's name
to be typed.

### Secure erase

`erase.py` offers the drive's own erase first: NVMe sanitize or format with secure erase,
ATA secure erase (enhanced where supported), then discard, then an overwrite with nwipe.
The disk's name has to be typed. Field Kit refuses the drive it started from and a
mounted one. A report (the drive, its serial, the method, start and end, the result and a
read-back sample) is saved to the stick's FIELDKIT partition, or `/run` without one.

### Windows repair

`windows.py`:

- **Reset a local account's password** with chntpw. It says plainly what this doesn't
  change: a Microsoft account, BitLocker, and files encrypted with EFS (they become
  unreadable). The registry hive is backed up first.
- **Read a BitLocker drive** with its recovery key (dislocker, read-only).
- **ntfsfix** for an NTFS volume Windows left marked.
- **Boot entries**: put Windows Boot Manager back in the firmware's list, or put Windows
  or bromigOS first (efibootmgr; the old list is saved).

nwipe and dislocker aren't in Arch's repositories, so bromigOS builds them
(`packaging/nwipe`, `packaging/dislocker`) from their pinned upstream releases.

### Lab

The lab console (`bromigos lab`, package `bromigos-lab`) and its guided provisioning run as
they do on the desktop. They talk to other machines over the local network, never the
internet. With no link, the item says so and offers the network settings. The model
catalog is on the medium, so recommending models works offline.

The screen's left side shows the lab's parts and how each is (`bromigos lab status
--json`). On a wide screen (150 columns or more, in 24-bit colour) they're also a small map:
each part round the lab, with its name and a state dot, and a scan going round (still under
reduced motion). Narrower, and on the console, it's the list.

### Install

- **bromigOS Server (no desktop)** opens the medium's text installer
  (`bromigos-iso-install --text`), with its own edition and disk steps. The Field Kit stick
  puts `bromigos.edition=server` on every kernel line, so Server is preselected. It reads `/usr/share/bromigos/fieldkit/edition.json` (package
  `bromigos-fieldkit-tools`, made from `packages.toml`) for the packages and services.
  Everything comes from the offline store. [server.md](server.md#for-the-installer) lists
  what the installer honours.
- **bromigOS desktop** shows only when the machine is online, and says how much it
  downloads.
- **Make a Field Kit USB stick** (below).

The installer is the installer job's (`bromigos-iso-install`). The menu offers an edition
only when the installer's `--help` lists `--edition`.

## The toolbelt

Tools has cards for the programs most people want (a system monitor, disk usage,
temperatures, a hardware report, a network test, Wi-Fi, firmware versions, a stress test,
editors, file recovery), and `?` in Shell lists the whole toolbelt with a line each. All of it
is on the medium and works offline; [fieldkit-packages.md](fieldkit-packages.md) lists each
with its size:

- **Finding and reading:** fzf, ripgrep, fd, bat, eza, zoxide, tree, jq, yq, file, tealdeer
  (`tldr`, its pages fetched when the medium is built), man.
- **Network:** curl, wget, aria2, ssh, mosh, rsync, rclone, sshfs, socat, netcat, ip, ping,
  dig, traceroute, mtr, nmap, tcpdump, iperf3, ethtool, iw, iwd with impala, WireGuard,
  Tailscale, NFS, SMB.
- **Disks and files:** parted, gdisk, cryptsetup, LVM, mdadm, btrfs, ext4, XFS, FAT, exFAT,
  NTFS, F2FS, smartctl, nvme, hdparm, TestDisk and PhotoRec, ddrescue, partclone, nwipe,
  fsarchiver, squashfs, 7-Zip, zip, zstd, xz, pigz.
- **System and debugging:** btop, htop, nvtop, iotop, sysstat, lsof, strace, ltrace, gdb,
  sensors, dmidecode, lshw, inxi, hwinfo, efibootmgr, mokutil, sbctl, fwupd, memtester,
  stress-ng, powertop.
- **Editing:** Neovim with bromigOS's LazyVim (its plugins fetched when the medium is built),
  micro, nano, git, lazygit, tmux, herdr, Python.
- **Windows:** chntpw, wimlib, ntfs-3g, dislocker. **Security:** gnupg, age.

The shell is zsh with bromigOS's prompt (mehshell), fzf on Ctrl+R (history), Ctrl+T (files)
and Alt+C (folders) in DRIFTGLASS's colours, `z` (zoxide), and `ls` and `cat` as eza and bat.
iwd and Tailscale are installed but off: NetworkManager runs the network.

## VECTOR

VECTOR, bromigOS's assistant, has a section of his own: he reads what Field Kit sees (the
hardware, what's on the drives, the last boot's log, the repair checks) and proposes Field
Kit's own actions, each run only after you approve it on the screen. His brain is the lab's
model over the local network, or a configured service when online; with none he explains
the findings with Field Kit's own repair logic. "Pair with BRODEC" shows a QR code for
BRODEC's machine pairing. [fieldkit-vector.md](fieldkit-vector.md) has the details.

## Your settings on the stick

At every start, `bromigos-fieldkit-stick.service` looks for a `fieldkit/` folder on:

1. a partition labelled `FIELDKIT` (what `make-stick` adds after the medium);
2. a Ventoy partition, beside the ISO files;
3. the medium itself.

```text
fieldkit/
  config.toml        your SSH keys, Wi-Fi networks, the lab connection
  homelab.toml       the lab connection (bromigos lab's own file)
  autorun/*.sh       run at startup, as root, in name order
  reports/           what secure erase writes
```

```toml
[ssh]
authorized_keys = ["ssh-ed25519 AAAA… you@laptop"]
start = false            # true: SSH on at every start

[[wifi]]
ssid = "Workshop"
password = "…"

[lab]
config = "homelab.toml"
```

Each startup script's output is in `/run/bromigos-fieldkit/autorun-<name>.log`, and the
summary in `autorun.log`. The menu's status line says what the stick brought and whether
a script failed. This follows SystemRescue's `sysrescue.d` and autorun.

### Make your own stick

```bash
bromigos fieldkit make-stick                # lists the USB drives
bromigos fieldkit make-stick /dev/sdX --wifi "Workshop:password" [--remote]
bromigos fieldkit make-stick /dev/sdX --settings-only   # new settings, same stick
```

It gathers your settings as you: your public SSH keys (`~/.ssh/id_*.pub`, or `--ssh-key`),
the Wi-Fi networks you name, and your lab connection. Then, as root, it writes the medium
as it is (never rebuilt), adds a 256 MiB FAT partition labelled `FIELDKIT` in the space
after it, and puts your `fieldkit/` folder there. You type the drive's name to confirm.
The medium comes from the running Field Kit, `--iso FILE`, or a downloaded ISO.

## Remote help

Remote help lets someone you trust work on the machine over SSH. It's off until you turn
it on: from the boot menu ("with remote help"), the menu's Shell section, the stick's
`[ssh] start = true`, or `sudo bromigos fieldkit remote on`.

- With a key on the stick, SSH takes that key only.
- Without one, Field Kit makes a one-time password of three words and a number, sets it
  for root, and shows it.
- While it's on, the menu's status line says REMOTE HELP ON, in the warning colour, with
  the address to use. The other consoles say it above their login prompt.
- The menu runs inside a tmux session called `fieldkit`, so the helper can share it:
  `ssh root@ADDRESS` then `tmux attach -t fieldkit`. With herdr on their side,
  `herdr --remote root@ADDRESS` gives them a workspace on the machine.
- `remote off` stops SSH, removes the password and the note.

## The names the firmware shows

A PC's boot menu lists a USB stick by its EFI partition's label, as "UEFI: …". mkarchiso
labels it `ARCHISO_EFI`; the build names it `BROMIGOS_FK` on Field Kit and `BROMIGOS` on
the full medium (FAT labels are at most 11 characters). The ISO volume labels are
`BROMIGOS_FIELD_KIT` and `BROMIGOS` (`BROMIGOS_TEST` on a test build). Nothing looks the
medium up by label: the menus find it by its UUID, so the names are free to read well.

## Ventoy

Both ISOs boot from a Ventoy stick, in its normal mode and its GRUB2 mode, on UEFI and BIOS.
Two things make that work:

- Field Kit's initramfs has no `microcode` hook. Early microcode is a separate cpio at the
  front of the initramfs, which Ventoy's normal mode doesn't expect.
- The menus find the medium by its UUID (`archisosearchuuid`) on the medium itself, and
  through `loopback.cfg` (`img_dev` and `img_loop`) when another GRUB starts the ISO file,
  as Ventoy's GRUB2 mode does. Neither depends on the ISO's label.

`iso/fieldkit/ventoy-test.sh` boots each ISO through Ventoy in QEMU ([Testing it](#testing-it)).

## Building it

```bash
iso/build.sh --edition fieldkit --repo https://pkgs.bromigos.org --channel stable --version 0.1.3
```

It's the same build as the full ISO ([iso.md](iso.md#building-it)): releng, the profile
overlaid (`iso/fieldkit/`), the boot menus rendered, the offline store, mkarchiso. The
differences:

- The package list comes from `packages.toml` through `manifest.py`.
- The store adds bromigOS Server's packages and what archinstall installs by itself.
- releng's services that Field Kit leaves off are removed: iwd and systemd-networkd
  (NetworkManager instead), cloud-init, the virtual machine guest tools, smartcards, and SSH
  (until remote help).
- The full medium's offline `pacman.conf`, the clock's wait and the installer are shared.
- It also makes `bromigos-fieldkit-<version>-x86_64-boot.tar`, Field Kit for `/boot`:
  `iso/fieldkit/package.sh` turns that into the `bromigos-fieldkit` package, which the
  release pipeline signs and publishes with `ci/publish.sh`'s `PKGS_PREBUILT`.
- It writes `fieldkit-sizes.tsv`, `fieldkit-live.tsv` and `fieldkit-store.tsv`, which
  `manifest.py docs` turns into the manifest page.

`--local-repo DIR` makes a dev build from this checkout's packages (unsigned; the medium
trusts them). `check-medium.sh` refuses a dev build.

## Testing it

`iso/fieldkit/test.py` runs a VM with no network device (`-nic none`) unless `--net` is
given, signs in on the serial console, runs commands as root there and saves the screen. A
test build (`iso/build.sh --test-key`) has its console on the serial port. Any other medium
starts with `--direct`: QEMU starts the medium's own kernel and initramfs with the kernel line
of its menu's entry, plus the serial console, so a medium is tested exactly as built.

```bash
iso/fieldkit/test.py up --iso bromigos-fieldkit-0.1.3-x86_64.iso --firmware uefi --direct
iso/fieldkit/test.py wait-serial "login:"
iso/fieldkit/test.py login
iso/fieldkit/test.py run -- fieldkit overview --json
iso/fieldkit/test.py shot fieldkit-home
iso/fieldkit/test.py down
```

Its VMs and screenshots go in `~/.cache/bromigos-fieldkit-test/` (`BROMIGOS_FIELDKIT_TEST_DIR`,
`BROMIGOS_FIELDKIT_SHOTS`).

- **In CI**, the ISO workflow's menu test boots the medium to its menus (UEFI and BIOS), then
  runs `iso/fieldkit/ci-test.sh ISO DIR` (`iso/ci-test.sh --suite hook`). Field Kit starts with
  no network: its console, Home, the engine and the scripted CLI, the offline store. Then the
  installer's own backend installs bromigOS Server onto the VM's disk with no network, and the
  installed Server boots to its console and passes its checks: firewall, update timer,
  snapshots, the boot menu's "More ways to start".
- `iso/fieldkit/server-test.sh` installs Server encrypted and adds the `bromigos-fieldkit`
  package to it, for the tests below that need Field Kit in an installed boot menu.
- `iso/fieldkit/ventoy-test.sh` puts a medium on a Ventoy disk image and boots it in Ventoy's
  normal and GRUB2 modes, on UEFI and BIOS.
- The tests that need no VM: `fieldkit/tests` (the engine, with stand-in installs and tools),
  `settings/grub/tests` (the boot options and the Field Kit entry), `settings/console/tests`
  (the console's fonts, colours and notes), `server/tests`, and the Rust screens' tests at
  every size (`cargo test -p bromigos fieldkit`).

## Test runs

On a dev build of 0.1.3 (2026-10-30), in QEMU with KVM, headless, with no network unless
noted:

| What | Result |
|---|---|
| Field Kit, UEFI and BIOS | Boots to the console's Home. The plain console (VT) fallback works; with the menu's program missing, the console shows one panel and doesn't restart in a loop |
| bromigOS Server, installed offline from the stick | Installs (LUKS2, 70 packages) and boots to its console. Through the installer's own backend (`ci-test.sh`), it found two things the stick lacked, both fixed: the desktop's PipeWire in an edition's install, and the installer's own required packages (os-prober, vim and the rest) in the stick's store |
| Field Kit on an installed system's `/boot` | The copy (about 1.1 to 1.4 GB), its GRUB entry, and a UEFI entry added last in the boot order. Field Kit starts from the installed menu, mounts the install, and rolls back a snapshot (bromigos-boot r10 to r9) |
| GRUB deleted | The firmware's Field Kit entry (BootNext) starts; "Repair the boot menu" puts GRUB back |
| Ventoy 1.1.18 | Normal and GRUB2 modes, UEFI and BIOS: Field Kit and the full medium both boot |
| The full medium's Field Kit entry | Boots the same system without the desktop, into Field Kit |
| Field Kit's CI test (`iso/fieldkit/ci-test.sh`) on a medium built as CI builds it (no test key) | Passes: Field Kit starts offline; the pairing QR decodes (zbarimg) from kmscon and from the bare kernel console; bromigOS Server installs offline through the installer's backend; the installed Server boots to its console with its firewall, update timer and snapshots |
| A plain "Start Field Kit" boot | SSH off: only the remote-help entry, the stick's settings or a test build turn it on |
| The medium's checks (`check-medium.sh`) | Pass for Field Kit, the privacy guard and licence check included. A dev build (`--local-repo`) fails only its own dev-build check, as it should |
