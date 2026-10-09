# Updates, channels and rollback

`bromigos update` is how a bromigOS machine updates. It upgrades the packages, then brings
everything that depends on them up to date. If an update breaks something,
`bromigos update --rollback` undoes it.

This page explains how updates, channels, snapshots and rollback work, for contributors.
To use them, read the manual's [Updating and rolling back](../manual/src/update-and-rollback.md)
page. Every option is in [Commands](../manual/src/commands.md).

![The Settings window's Updates and recovery page: the channel this machine follows, an
Update now button, the last update, and what an update would do now](images/settings-updates.webp)

## What an update does

`bromigos update` runs these steps in order:

1. It takes a snapshot of `/`, where the root is btrfs with snapper.
2. It upgrades the packages with `sudo pacman -Syu`.
3. It updates the packages you installed from the AUR, with `paru -Sua`. This step runs
   only when step 2 succeeded, the AUR is on, and `paru -Qua` lists an update
   ([aur.md](aur.md)).
4. It takes a second snapshot and records the pair, so the update can be undone. The AUR's
   changes are inside the same pair.
5. It runs the pending migrations. A migration is a script in `migrations/` that brings
   an existing install forward. Each runs once per user.
6. It renders the theme again. Where bromigOS's boot menu theme is on, it brings `/boot`
   up to date too ([boot.md](boot.md)).
7. It restarts whatever still runs older code than is installed (`bromigos restart`).
   When a new kernel or graphics driver waits for a restart of the computer, it leaves
   alone what needs the GPU, and says so last
   ([below](#when-the-kernel-or-the-graphics-driver-changes)).

If pacman fails, the update stops before the migrations. If an AUR package fails to
build, the update still runs every other step. Then it says which package failed and how
to try again, and exits with status 1.

`bromigos update --yes` doesn't ask. pacman takes its defaults (`--noconfirm`), the AUR
step builds without paru's review of each recipe, and a rollback goes ahead without a
question. `bromigos update --no-aur` leaves the AUR out this time. A bare `pacman -Syu` works too,
but a pacman hook (`bromigos-update.hook`) reminds you to run `bromigos update` after
bromigOS packages change.

How restarts and migrations work is in [core/README.md](../core/README.md).

To see what an update would do without doing it:

```bash
bromigos update --check
```

It lists the upgrades waiting, the migrations pending, the restarts needed, how this
machine takes snapshots, and the updates that can be rolled back.

## When the kernel or the graphics driver changes

A new kernel or a new NVIDIA driver only runs after the computer restarts. Until then,
starting a program that needs the GPU can do harm, so `bromigos update` doesn't.

NVIDIA's driver has two halves, and they must be the same version:

- the kernel module, which loads when the computer starts. `/sys/module/nvidia/version`
  says which version is loaded.
- the libraries each program loads when it starts, such as `libEGL_nvidia.so.<version>`
  from `nvidia-utils`.

An update replaces the libraries at once, but the module only at the next start. A
program that starts in between can't use the GPU. NVIDIA's EGL refuses, and Mesa's
software renderer, llvmpipe, draws on the CPU instead. Programs that were already running
keep the libraries they loaded, and are fine.

On 2026-10-09 an update took `nvidia-utils` from 615.71.09 to 615.78.08 with the 615.71.09
module still loaded. It restarted the live layer, the program that draws the animated
background. The new process drew on llvmpipe: about 15 threads at 1,180% CPU, the CPU at
93 °C. The theme switcher's previews failed at EGL, theme after theme.

### What the update checks

After the package step, `bromigos update` compares what runs with what's installed
(`core/crates/bromigos-core/src/reboot.rs`):

| What | Running | Installed |
|---|---|---|
| NVIDIA's driver | `/sys/module/nvidia/version` | The version in the libraries' file names (`libEGL_nvidia.so.*`, `libGLX_nvidia.so.*`, `libnvidia-glcore.so.*`), or else `nvidia-utils`' version from pacman |
| The kernel | `uname -r` | Each `/usr/lib/modules/<release>` with a `vmlinuz` or a `kernel/` folder in it |

A removed kernel's folder can stay behind with a few files nobody owns, such as
`modules.weakdep`, so a folder alone doesn't count. A machine with no NVIDIA module
loaded, or with no kernels in `/usr/lib/modules` (a container), has nothing to compare.

### What it does then

When either differs:

- **It holds back what needs the GPU.** The live layer and VECTOR aren't restarted, even
  when their code is newer. Their restart shows `held back: restart the computer to run
  it`. They keep running on the libraries they loaded.
- **It doesn't draw the theme switcher's previews.**
- **It restarts everything else as usual**: the panels, the bar, notifications, the
  volume display and the idle policy.
- **It ends with one line**, and sends the same text as one desktop notification:

  ```text
  The graphics driver was updated: restart the computer to use it. Until then, the animated background stays off.
  ```

  The first sentence names what changed: the graphics driver, the kernel, or both. The
  second says "keeps running as it is" when the live layer is running.

`bromigos update --check` and `bromigos restart --check` list the waiting restart as a
`driver` or `kernel` line with the need `reboot`. A bare `bromigos restart` holds back the
same pieces. `bromigos restart live` restarts the live layer anyway, because you asked.

In `--json`, the report's `reboot` field has the details
([core/README.md](../core/README.md#json-documents)).

### The live layer's own guard

If the live layer starts anyway, it checks which renderer it got. When GTK's GL context
reports llvmpipe, softpipe, swrast or "Software Rasterizer", the live layer:

- holds a still frame, as `bromigos accessibility motion still` does. It draws a new
  frame at most every 30 seconds, and only when what it shows changed;
- runs the decks at 10 frames a second at most;
- logs the renderer, and on a real machine sends one notification a session.

`bromigos live status` shows a `NO GPU` line. A virtual machine without 3D always has a
software renderer, so it gets the same still frame, but no notification.
`[general] allow_software = true` in the live layer's config, or
`bromigos scene set general.allow_software on`, allows full motion anyway.
[live/README.md](../live/README.md#no-gpu) has the details.

### The previews

`bromigos-theme-previews` makes the same check before it draws anything. It doesn't
matter what started it: `bromigos update`, the pacman hook, the switcher or you. While
the driver halves differ, it draws nothing, writes one line to its log and exits. If the
GPU fails in the middle of a run for another reason, the run gives up after that one
failure. The next run tries again ([theming.md](theming.md#the-previews)).

### Testing it

`BROMIGOS_GPU_ROOT` is a test hook. It moves where the driver's files are read:
`<root>/sys/module/nvidia/version` and `<root>/usr/lib/`. A test, or a VM without NVIDIA,
fakes a mismatch with two files:

```bash
mkdir -p /tmp/gpu/sys/module/nvidia /tmp/gpu/usr/lib
echo 615.71.09 > /tmp/gpu/sys/module/nvidia/version
touch /tmp/gpu/usr/lib/libEGL_nvidia.so.615.78.08
BROMIGOS_GPU_ROOT=/tmp/gpu bromigos update --no-packages
```

The tests:

- `reboot.rs` has unit tests with fixture machines: the 2026-10-09 mismatch, a matching
  driver, no NVIDIA, a package without libraries, a kernel update and both at once.
- `update.rs`'s `a_new_driver_holds_back_what_needs_the_gpu` checks the restart plan.
- `tests/cli.rs`'s `update_says_when_the_graphics_driver_waits_for_a_restart` runs the
  whole update with a faked mismatch and a stand-in `notify-send`.
- `live/tests/test_software.py` and `live/tests/software_session.py` cover the live
  layer, the second on a real llvmpipe.
- `desktop/tests/test_theme_switcher.py`'s `NoGpuTest` covers the previews.

<!-- site:channels -->
## Channels

A *channel* is which builds a machine follows. Each one is a path in the same package
repository.

| Channel | What you get | Path, under the repository's base URL |
|---|---|---|
| `stable` | Tagged releases (`vX.Y.Z`). The default for new installs. | `bromigos/stable/x86_64/` |
| `rc` | Release candidates (`vX.Y.Z-rcN`). | `bromigos/rc/x86_64/` |
| `edge` | Every push to `main`, as soon as CI publishes it. | `bromigos/x86_64/` |
| `dev` | Your own build, from a local repository. | `file://<dir>/bromigos/x86_64/` |

A machine's channel is simply where the `Server` line of the `[bromigos]` section in
`/etc/pacman.conf` points. bromigOS stores nothing else about it, except the remote base
URL. That URL is kept in `~/.local/state/bromigos/channel.toml`, so a machine that leaves
`dev` can find its way back.

### Switching channels

```bash
bromigos channel                        # show the channel, and what each one is
bromigos channel stable                 # switch (rewrites the Server line with sudo)
bromigos update --channel edge          # switch and update in one go
bromigos channel dev --dev-dir <dir>    # follow your own build
bromigos channel edge --repo <url>      # give the base URL, when it changed or isn't known
```

After `bromigos channel`, run `bromigos update` to install the new channel's packages.

Moving to an older channel, such as from `edge` to `stable`, leaves packages that are
newer than the channel's in place. `bromigos update --downgrade` brings them back to the
channel's versions with `pacman -Syuu`. `bromigos update --channel` does this by itself.

The `dev` channel sets `SigLevel = Optional`, because your own build is unsigned. The
other channels keep `SigLevel = Required DatabaseOptional`.

A switch also deletes the old channel's sync files from pacman's `sync/` directory: its
`bromigos.db`, the signature and the file list. The next `pacman -Sy` then fetches the new
channel's database afresh. Without this, a move to an older channel failed with
"signature is invalid". The old database was newer than the new channel's, so pacman kept
it and checked the new signature against it.

Migrations see the channel in `BROMIGOS_CHANNEL`: `stable`, `rc`, `edge`, `dev` or
`unknown`.

### Building your own channel

`packaging/dev-repo.sh` builds every package from your checkout into a local repository.
Then point the machine at it and update:

```bash
packaging/dev-repo.sh                   # builds into ~/.local/share/bromigos/repo
bromigos channel dev
bromigos update
```

### How channels are published

CI publishes each channel ([packaging/README.md](../packaging/README.md) has the
details):

- A push to `main` publishes to `edge`.
- A `vX.Y.Z` tag publishes the same build to `stable`.
- A `vX.Y.Z-rcN` tag publishes to `rc`.
- A manual run of the workflow can name a channel.

Each channel has its own database. Two repositories publish into it, this one and
`vector`, and each is tagged on its own. A stable release needs both tagged, because the
`bromigos` package depends on `bromigos-vector`.

## Snapshots

On a btrfs root with snapper, every update is bracketed by a *pre* and a *post* snapshot
of `/`.

- **`bromigos update` makes the pair itself.** It runs `snapper -c root create` with
  `-t pre`, then `-t post`, described "bromigos update". The boot menu's snapshot list
  shows that description ([boot.md](boot.md#the-snapshots-in-the-boot-menu)).
- **snap-pac stays out of the way.** snap-pac is Arch's package of pacman hooks that
  snapshot every other pacman run. `bromigos update` runs pacman with `SNAP_PAC_SKIP=y`,
  so there's one pair, not two. sudo passes that variable on for an admin, because the
  usual `ALL` rule includes SETENV.
- **paru's transactions skip snap-pac too.** paru runs pacman through sudo for each
  package it installs. `SNAP_PAC_SKIP=y` is in paru's environment, and sudo is told to keep
  it with `--sudoflags --preserve-env=SNAP_PAC_SKIP`. sudo allows that exactly where it
  allows `sudo SNAP_PAC_SKIP=y pacman`. So the AUR's changes land in the update's own pair,
  they're recorded, and `--rollback` undoes them. In the VM, post was pre + 1, with no
  snapshot between.
- **An empty pair is deleted.** If nothing changed, the update deletes both snapshots with
  `snapper delete`. Right after the post snapshot, snapperd compares the pair in the
  background and refuses a delete with "Config is in use.", so the update retries for up
  to 10 seconds.
- **A bare `pacman -Syu` gets snap-pac's pair.** That pair is described with pacman's
  command line. It appears in the boot menu, but it isn't recorded for `--rollback`.
- **No btrfs or no snapper configuration means no snapshot.** The update prints
  `snapshot: none (…)` and carries on. Nothing fails for want of a snapshot.

### Letting the user read the snapshots

The update runs as you, and it reads snapper's list to find the snapshots it made. So
snapper's `root` configuration must let you list them. bromigOS sets
`ALLOW_GROUPS=wheel`, and `SYNC_ACL=yes` so the group can enter `/.snapshots`.
Without that, snapper answers "No permissions." and the update says it wasn't recorded.

- `bromigos rollback setup` sets this on a configuration it creates.
- `bromigos rollback allow` sets it on one that already exists. It reads the
  configuration with `sudo snapper get-config` and keeps the groups and users already
  there. If you aren't in `wheel`, it adds you to `ALLOW_USERS`. It sets only what's
  missing.
- The migration `20261009190000-snapper-user-access` runs `allow` once on machines where
  the user couldn't list the snapshots. It asks for sudo on the terminal, like the
  update's other root steps.

### The update record

Each recorded update is one line in `~/.local/state/bromigos/updates.jsonl`. It holds the
pair's numbers, the channel and the packages that changed:

```json
{"at":"2026-10-08T19:29:52-07:00","channel":"edge","snapshot":{"pre":151,"post":152},"packages":["bromigos-desktop 0.1.0.r8-1 -> 0.1.0.r15-1"],"rolled_back":false}
```

`bromigos update --check` and `bromigos rollback status` both list the updates that can
be rolled back.

## Rolling an update back

```bash
bromigos update --rollback          # the newest recorded update
bromigos update --rollback 151      # the update whose pre snapshot is 151
bromigos update --rollback --yes    # don't ask first (for scripts; --json needs it)
```

First it shows the update: its date, channel and packages. Then it shows what the
rollback will touch, from `snapper status`: the files changed, created and deleted
between the two snapshots. It asks, then runs `sudo snapper -c root undochange PRE..POST`.

Every file `/` had before the update comes back, pacman's database included. This
happens in place, on the running system. It works on any btrfs layout, because it doesn't
swap the default subvolume and needs no reboot to apply.

Afterwards:

- **If the kernel was part of the update, reboot.** If `/boot` is a separate file system,
  its kernel image wasn't reverted. Run `sudo pacman -S linux` first, then reboot.
  pacman's cache has the version that's now installed.
- **Otherwise, restart what's running.** The running programs are newer than what's
  installed. Run `bromigos restart`, or reboot.

The rollback is recorded in `updates.jsonl` as `rolled_back`, so `--check` no longer
offers it. Migrations that ran with the update stay marked as done. Their state lives
under `~/.local/state`, which snapper's `home` configuration covers, not `root`.
Migrations are written to be safe to run again, and the next update runs any new ones.

## When the machine won't boot

`--rollback` undoes an update in place, so it needs a system that boots. For one that
doesn't, the boot menu lists the snapshots. Boot the one from before the update, then run
`bromigos update --rollback` there. It makes that snapshot the root, so the next normal
boot comes up on it ([below](#making-a-booted-snapshot-the-root)).

`bromigos rollback setup` installs what the machine's boot loader needs for this.
`bromigos install` runs it too. `bromigos rollback status` says where the machine stands,
and whether setup has anything left to do.

| Root file system | snapper | Boot loader | Update snapshots | Snapshots in the boot menu |
|---|---|---|---|---|
| btrfs | yes | GRUB | bromigOS's pair, or snap-pac's | Yes: grub-btrfs and `grub-btrfsd.service`, with the overlay hook |
| btrfs | yes | limine | bromigOS's pair, or snap-pac's | Not yet: limine-snapper-sync isn't in bromigOS's repository |
| btrfs | yes | systemd-boot | bromigOS's pair, or snap-pac's | No: use `--rollback` |
| btrfs | no | any | After `bromigos rollback setup` | As above |
| ext4, xfs or other | — | any | None | None |

The ISO's installer sets up btrfs, snapper, snap-pac and grub-btrfs ([iso.md](iso.md)).
A machine installed from it can roll back from its first update.

### Booting a read-only snapshot

A snapshot is read-only, so a system booted from one can't come up on it as it is. On
GRUB, `rollback setup` adds grub-btrfs's `grub-btrfs-overlayfs` hook to the initramfs.

- The hook goes last in `HOOKS`, in every file that sets them: `/etc/mkinitcpio.conf`
  and its drop-ins.
- Setup then rebuilds the initramfs with `mkinitcpio -P`.
- At boot, the hook lays a writable overlay in memory over the snapshot. The system boots
  like a live medium and forgets its changes at shutdown.

A systemd-based initramfs (the `systemd` hook) can't run this hook. Setup says so, and a
snapshot booted from GRUB's menu comes up read-only there.

### Making a booted snapshot the root

In a snapshot booted from the boot menu, `bromigos update --rollback` doesn't undo an
update. It makes the booted snapshot the root instead. It knows it's in one when the
kernel line names a snapshot as the root subvolume
(`rootflags=…,subvol=@.snapshots/3/snapshot`) and `/` is an overlay or a read-only btrfs.
`bromigos rollback status` says so too.

`snapper rollback` can't do this on bromigOS. From grub-btrfs's overlay, snapper can't
open `/` at all ("subvolume is not a btrfs subvolume"). And archinstall's layout names
the root subvolume, `@`, in `/etc/fstab` and on GRUB's kernel line, so a new default
subvolume would be ignored.

It shows the snapshot, the recorded updates it undoes and every command, then asks. Then
it:

1. Mounts the btrfs file system's top level at `/run/bromigos-rollback`.
2. Renames the root subvolume `@` to `@.before-rollback-<date>-<time>`. Nothing is
   deleted.
3. Makes a writable snapshot of the booted snapshot, named `@`.
4. Removes pacman's lock, `/var/lib/pacman/db.lck`, from the new `@`. snap-pac takes its
   snapshots while pacman runs, so they keep the lock, and pacman would refuse to start.
5. Unmounts the top level.

`/etc/fstab` and GRUB don't change. They mount `@` by name, and `@` is now the snapshot,
so the next normal boot comes up on it. In `updates.jsonl`, every recorded update made at
or after the snapshot is marked `rolled_back`, with `"root"` set to the snapshot's
number. If nothing was recorded after it, one line says which snapshot became the root.

If renaming or copying fails, `@` gets its name back, and nothing has changed.

It works where `/etc/fstab` mounts `/` by subvolume name (`subvol=/@`), as archinstall,
the Arch wiki and the ISO do. On any other layout it refuses and says why. On a layout
that boots btrfs's default subvolume (no `subvol=` for `/`), do it by hand from the
booted snapshot, then reboot:

```bash
sudo mount -o subvolid=5 <device> /mnt
sudo btrfs subvolume snapshot /mnt/<snapshot> /mnt/<new>
sudo btrfs subvolume set-default /mnt/<new>
sudo umount /mnt
```

`<device>` is the `root=` value on the kernel line (`cat /proc/cmdline`), `<snapshot>` the
`subvol=` value, and `<new>` any free name.

#### When the update changed the kernel

`/boot` is a file system of its own on the ISO's layout, so it isn't in the snapshots.
GRUB boots a snapshot with the kernel in `/boot`, the update's. The snapshot only has the
modules of its own kernel. Without the module for `/boot`'s file system, `/boot` can't be
mounted, and that boot stops in emergency mode, asking for root's password. The ISO's
installer gives root the same password as the user. There, run:

```bash
su - <user>
bromigos update --rollback
```

The rollback sees that the running kernel has no modules in the snapshot, and puts the
snapshot's kernel back before it unmounts the top level:

1. It loads the modules `/boot` needs (`vfat` and its code pages, from `/etc/fstab`) out
   of the replaced root, which has them for the running kernel (`modprobe -d`). Then it
   mounts `/boot`. It skips both when `/boot` is already mounted.
2. It copies the snapshot's kernel, `/usr/lib/modules/<release>/vmlinuz`, to
   `/boot/vmlinuz-<pkgbase>`.
3. It rebuilds the initramfs with `mkinitcpio -p <pkgbase>`.

If one of these fails, the snapshot is the root already, and the error lists the commands
left to run before the reboot.

#### Deleting the replaced root

The rollback keeps the root it replaced. Once the rolled-back system works, delete it:

```bash
sudo mount -o subvolid=5 <device> /mnt
sudo btrfs subvolume delete -R /mnt/@.before-rollback-<date>-<time>
sudo umount /mnt
```

The rollback prints these commands with the real names. `-R` also deletes the
subvolumes inside it, such as `var/lib/machines`. A replaced root that was itself made
by a rollback is a snapshot, so grub-btrfs lists it in the boot menu until it's deleted.

### How setup finds the boot loader

archinstall mounts `/boot` with mode 0700, so as a user nothing in it shows. Setup tries
these in order:

1. GRUB's `grub.cfg`, or limine's or systemd-boot's files, when `/boot` can be read.
2. UEFI's `LoaderInfo` variable, which names the loader that booted the machine. GRUB's
   `bli` module sets it too.
3. GRUB's `/etc/default/grub` and the `grub` package.

### How setup creates snapper's configuration

Without a `root` configuration, setup creates one with `snapper create-config /`.

Many layouts, including the Arch wiki's and archinstall's, keep `/.snapshots` as a
subvolume of its own, `@.snapshots`. That way, rolling `@` back leaves the snapshots
alone. snapper refuses to create a configuration there, because it wants to make
`.snapshots` itself. So setup unmounts the subvolume from `/.snapshots`, lets snapper
create its configuration and its own `.snapshots`, deletes that one, and mounts the
subvolume again.

Setup also works inside an install chroot. The ISO's installer uses the same command.

- Setup recognises a chroot because its root mount differs from PID 1's. Any user can
  read both mountinfo files.
- In a chroot, snapper runs with `--no-dbus`. arch-chroot binds the live system's `/run`
  in, so the system bus there belongs to the live system. Asking its snapperd would set
  up the live system instead.
- systemctl reads the unit files with `--root=/`, and services are enabled, not started.

## Hyprland during a package transaction

Hyprland reloads its config by itself when one of its files changes. pacman replaces the
desktop's default config files in `/usr/share/bromigos/default/hypr/` one at a time. A
running Hyprland could reload a half-written set, such as a new `bromigos/binds.lua` with
the old `bromigos/keys.lua`. That causes a Lua error, which leaves no key bindings and
puts Hyprland in its emergency mode. Any pacman transaction can do this, not only
`bromigos update`.

Two pacman hooks in `bromigos-core` prevent it, whatever runs pacman:

| Hook | When it runs | What it runs |
|---|---|---|
| `bromigos-hypr-hold.hook` | Before the first file changes (PreTransaction) | `bromigos session hold --pacman` |
| `bromigos-hypr-release.hook` | After every package's files are in place (PostTransaction) | `bromigos session release --pacman` |

- **The hold** turns `misc.disable_autoreload` on in every running Hyprland, for every
  user. It reaches each session through `/run/user/<uid>/hypr/<signature>`, running
  hyprctl as that user. It records the old setting in `/run/bromigos/hypr-hold/`.
- **The release** verifies each Hyprland's config with `Hyprland --verify-config`, as its
  user, with its own `-c`. If the config verifies, it reloads once. Then it puts
  auto-reload back as it was.

Both hooks trigger on paths matching `usr/share/bromigos/default/hypr/*`, for install,
upgrade and removal. So they only run for a transaction that changes those files.

That includes AUR packages, since paru installs them with pacman. In the VM, `paru -Bi` of
a package with a file in `usr/share/bromigos/default/hypr/` printed "Holding Hyprland's
config reloads…" before and "Reloading Hyprland's config once, verified…" after.

### Why pacman hooks

- pacman runs them for every front end: `bromigos update`, `pacman -U`, an AUR helper.
  They run as root, which can reach every user's session.
- A PostTransaction hook runs once, after every package in the transaction is in place.
  A package's own `post_upgrade` script runs right after that package. With two
  packages upgraded together, it could reload against a half-upgraded set.
- They match files, not a package name. If another package ever ships a file the config
  loads from there, the hooks cover it too.

### When something goes wrong

- **The config doesn't verify after the transaction.** It isn't reloaded, so Hyprland
  keeps running its old config. The hook prints why, and auto-reload goes back on.
- **The transaction fails after the hold.** pacman runs no PostTransaction hooks then,
  and it may have been killed. So before holding anything, the hold starts a watcher:
  `bromigos session release --after PID:START,PID:START`. It waits for pacman and the
  hold to exit, identifying each by PID and start time. Then it releases whatever is
  still held, the same way. A half-written set won't verify, so it isn't reloaded.
  Auto-reload goes back on, and the watcher logs to the journal
  (`journalctl -t bromigos-hypr-hold`).
- **Hold, release and the watcher never act at once.** They take turns on a lock in the
  records' directory.
- **A Hyprland started mid-transaction** wasn't held. The release gives it the verified
  reload too.
- **Your own `disable_autoreload = true`** is recorded and stays.

pacman reads its hooks from disk at each phase. So the transaction that first installs
these hooks runs only the release: there's no hold, but the verified reload still fixes a
session that reloaded mid-transaction. Every later transaction is held. `bromigos update`
also reloads Hyprland after a `bromigos-desktop` upgrade, which is harmless after the
hook's reload.

You can use the same pair by hand. As a user it covers your own sessions; as root it
covers everyone's:

```bash
bromigos session hold
# change the files
bromigos session release
```

The tests are `core/crates/bromigos/tests/hypr_hold.rs`. They use stand-in compositors and
a stand-in hyprctl in a sandbox, and cover the hold, the release, a config that doesn't
verify, the user's own setting, several compositors, stale locks and the watcher after a
"pacman" that dies. The fresh-machine VM runs `test/vm/hypr-hold-e2e.sh`
([install.md](install.md#the-fresh-machine-test)).

## The manual

The user manual (`manual/`) is an mdBook. It reaches users two ways:

- **On every machine.** The `bromigos-manual` package builds it and installs the HTML in
  `/usr/share/doc/bromigos/manual/`. It's about 7 MB, matches the machine's own packages,
  and works offline, search included.
- **On the web.** `.github/workflows/manual.yml` builds it on every change and publishes it
  next to the packages, at `<repo>/bromigos/manual/` (`manual/publish.sh`). This copy is
  built from `main`, whatever channel a machine follows.

Settings (F1, and each page's manual link) and Settings › About open the installed copy
first, then the web one, then the source on GitHub. `bromigos_cli.manual_url` in
`desktop/lib/` decides, and its test reads the web address from `manual/publish.sh`.

To preview the manual from a checkout, run `mdbook serve manual`.

The manual's generated pages (the commands, the keys and the packages) come from
`tools/docs/generate.py`. `.github/workflows/docs.yml` fails when they're out of date or a
link is broken. [CONTRIBUTING.md](../CONTRIBUTING.md) explains how to run both.

## Test runs

### 2026-10-09: the driver hold, on the mismatched machine and in the VM

The NVIDIA desktop that had the incident was still between the update and its restart:
`nvidia-utils` 615.78.08 installed, the 615.71.09 module loaded. Everything here ran
read-only there, or in a sandbox.

- **Detection on the real machine.** `bromigos restart --check` listed
  `driver reboot: NVIDIA's driver 615.78.08 is installed (nvidia-utils 615.78.08-1), but
  the kernel module running is 615.71.09`. A stray `/usr/lib/modules/6.10.5-arch1-1`
  folder, holding only `modules.weakdep`, wasn't taken for an installed kernel.
- **The update in the fresh-machine VM** (`test/vm/gpu-hold-e2e.sh`, 11 of 11 checks
  pass). The VM was installed from `stable`. The live layer and the panels were made stale
  by reinstalling their packages, and the mismatch was faked with `BROMIGOS_GPU_ROOT`.
  The update held the live layer back, so its PID stayed the same. It restarted the
  panels, printed the `driver` line, ended with the restart line and sent one
  notification. `--json` had `report.reboot`. With the driver back in step, the same
  update restarted the live layer, and said nothing about a restart.
- **The live layer on llvmpipe** (`live/tests/software_session.py`, in a sandbox on the
  real machine, 1920×1080). Held to a still frame, the daemon used 3.8% of one CPU over
  30 seconds and drew 3 frames in about a minute. It sent one notification, and its status
  said `NO GPU` and `motion still`. With `allow_software = true` it used 988% of one CPU,
  which is the incident's load.
- **The live layer in the VM** (llvmpipe, 4 CPUs, 1280×800). At full motion, the old
  code took 233% of one CPU and fell behind. Held still, the new code took 1%, with no
  notification. A screenshot showed the den drawn.
- **The previews on the real machine.** Before the change, `wick mire` took 2 minutes
  14 seconds. Each theme tried the nested desktop twice, failed (`CBackend::create()
  failed!`) and cached a lesser, composed picture as if it were current. After it, the
  same run held back every theme in 0.05 seconds. With the check bypassed, the run
  failed once, in 35 seconds, and gave up. The other themes were left for the next run,
  and nothing was cached.

### 2026-10-09: the reload hold in the VM, 21 of 21 checks pass

The fresh-machine VM was installed from `edge` (core r99, desktop r54) and signed in, with
Hyprland 0.56.2's auto-reload on. Then `bromigos-core` r101 with the hooks went in by
`pacman -U`. `test/vm/hypr-hold-e2e.sh --desktop` ran with a `bromigos-desktop` r55.

- **Two upgrades in a row.** Each variant called a new `keys.lua` function from the top
  of `binds.lua`, with 96 MiB between them in the archive. Auto-reload was off for the
  0.7 s of each transaction, with no reload while files changed and exactly one after.
  The binds never dropped below 95, the new bind was live, there were no config errors,
  auto-reload came back on, and no hold or watcher was left.
- **pacman killed mid-write.** No PostTransaction hooks ran. The watcher released within
  a second and didn't reload the half-written set, which failed to verify with `attempt
  to call a nil value`. It turned auto-reload back on and said so in the journal.
  Hyprland kept running the previous config with all its binds.
- **The original package back.** One verified reload, its binds, and `pacman -Qk` clean.
- **The control, with the hooks moved aside.** Five reloads happened 0.64 s into the
  transaction, and Hyprland fell into emergency mode with only its 3 emergency binds. In
  another run, Hyprland stopped answering and the VM needed a reboot.
