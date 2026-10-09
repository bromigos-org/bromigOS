# Disk encryption in the ISO installer

The ISO's installer encrypts the disk by default. The root file system is btrfs on LUKS2,
and the disk's passphrase is typed at every boot. This protects your files if the machine
is lost or stolen.

This page explains how the encryption is set up and why it's laid out this way. The
installer itself is described in [iso.md](iso.md#installing-from-it). For users, the
manual's [Install](../manual/src/install.md) page covers it.

## What you're asked

`sudo bromigos-iso-install` asks, after the disk, your user and the hostname:

1. **"Encrypt the disk? (typed at every boot; it can't be recovered) [Y/n]"** The default
   is yes.
2. **"A passphrase of its own for the disk, or Enter to use the password"** If you type
   one, it asks for it again. If you press Enter, your user's password becomes the
   passphrase.

`--no-encrypt` skips the question and installs without encryption.

An unattended install (`--config` and `--creds`) follows its config. With
`disk_encryption` in the config and `encryption_password` in the credentials, the root is
encrypted. Without them, it's plain btrfs. So an unattended install is always explicit
about it.

## How it's set up

The installer doesn't encrypt anything itself. archinstall does, through its own LUKS2
support, from the config `answers.py` writes.

| Part | Encrypted? | Why |
|---|---|---|
| `/boot` (1 GiB, FAT32) | No | GRUB and the firmware read the kernel and initramfs from it. On UEFI it's the EFI system partition. |
| The rest of the disk | Yes, LUKS2 | It holds the btrfs root: `/`, `/home`, the logs, the package cache and the snapshots |

`answers.py` (`iso/profile/airootfs/usr/local/lib/bromigos-iso/answers.py`) writes two
files:

- **The config** gets `disk_config` with the two partitions, and inside it
  `disk_encryption`:
  `{"encryption_type": "luks", "partitions": ["<the root partition's obj_id>"], "lvm_volumes": []}`.
  The `obj_id` is the one `answers.py` generated for the root partition.
- **The credentials** get `encryption_password`. The passphrase goes there only. It never
  goes in the config, on a command line or in a log. The credentials file is created
  with mode 0600.

archinstall then sets up the rest:

- the `encrypt` hook in mkinitcpio's `HOOKS`;
- the kernel parameter that tells the initramfs which partition to unlock;
- GRUB, with no `GRUB_ENABLE_CRYPTODISK`, because `/boot` isn't encrypted.

After archinstall, the installer adds the `plymouth` hook right after `udev` (or
`systemd`) and before `encrypt`. So the passphrase prompt appears inside the Bromigos boot
splash.

The packages for snapshots (`snapper`, `snap-pac`, `grub-btrfs`, `inotify-tools`) and
`cryptsetup` are in the medium's `archinstall.json`, and the medium carries them. An
install needs no network.

## Why not encrypt /boot, or use systemd-boot

- **GRUB can unlock an encrypted `/boot`,** but only LUKS1, slowly, and you'd type the
  passphrase twice.
- **systemd-boot can't read btrfs,** so it couldn't boot a snapshot.
- **A plain `/boot` keeps the boot menu simple.** GRUB lists the snapshots from it, and
  rolling back works the same as on an unencrypted machine ([update.md](update.md)).

The root, your home and the snapshots are all encrypted. The kernel on `/boot` comes from
Arch's signed `linux` package.

## How it's tested

`iso/test.sh install` installs encrypted by default, with the password as the passphrase.
`--no-encrypt` tests the plain case. `iso/test.sh boot-disk` types the passphrase at the
splash through QEMU's QMP, then checks the installed system: LUKS under the btrfs root
(or none for `--no-encrypt`), the subvolumes, snapper's configurations, the plymouth hook,
and the snapshots in GRUB's menu after the first update. [iso.md](iso.md#test-runs) has
the results.
