# Install

There are two ways to install bromigOS:

- **On an Arch Linux system you already have.** A short script adds bromigOS's packages
  and sets everything up. This is the way to install today.
- **From the bromigOS USB stick.** It boots straight into the desktop, and installs from
  there. The stick image isn't published yet.

## Before you start

You need:

- a computer with Arch Linux installed, and a user account that can use `sudo`;
- a network connection.

## Install on Arch Linux

1. Log in as your own user, not as root.
2. Download the installer:

   ```bash
   curl -fsSLO https://pub-725f58eecf5c43748779ba6473eb9720.r2.dev/bromigos/install.sh
   ```

3. Read it if you like. It's short: `less install.sh`.
4. Run it:

   ```bash
   bash install.sh
   ```

   To install from another copy of the repository, such as your own mirror, add
   `--repo <address>`. If that copy has its own security certificate, add
   `--ca <certificate file>` too.

5. Type your password when `sudo` asks, and answer the package manager's questions.
6. Answer the [first-run questions](first-run.md) when they appear.
7. Restart the computer, and sign in at the bromigOS login screen.

### What the installer does

1. It adds bromigOS's package repository and its signing key. The key's fingerprint is
   written into the script, so a wrong key stops it.
2. It installs bromigOS's packages. The list is in [What gets installed](packages.md). It
   also installs paru, a helper for the [AUR](apps.md#install-an-app-from-the-aur), unless
   you already have one.
3. It turns on networking, the login screen and sound, and Bluetooth if it's installed.
   If you already use another login screen or network manager, it keeps yours. To switch
   to bromigOS's login screen anyway, add `--force-dm`.
4. It sets up your [hardware](hardware.md): the graphics driver, and a laptop's power
   profiles.
5. If your system disk uses btrfs, it sets up [snapshots](glossary.md#snapshot), so you
   can undo an update.
6. It puts bromigOS's settings files in your home folder, applies the default theme, and
   themes the [boot menu](boot-menu.md).
7. It asks the [first-run questions](first-run.md).

Running it again is safe. It only changes what's missing. It writes everything it does to
`~/.local/state/bromigos/install.log`.

### Installer options

Add these after `bash install.sh`:

| Option | What it does |
|---|---|
| `--channel stable` | Follow tagged releases. This is the default. |
| `--channel rc` | Follow release candidates, the versions about to become stable. |
| `--channel edge` | Get every change as soon as it's built. |
| `--dry-run` | Say what it would do, and change nothing. |
| `--with bromigos-apps` | Also install the [app bundle](apps.md). Repeat `--with` for more packages. |
| `--no-setup` | Skip the first-run questions. Run `bromigos setup` later. |
| `--force-dm` | Use bromigOS's login screen even if another one is turned on. |
| `--no-aur` | Don't install an AUR helper, and leave the AUR out of updates. |

You can change the channel later. See [Channels](update-and-rollback.md#channels).

## Install from the USB stick

> **Not published yet.** The bromigOS install image works, but there's no download yet.
> Until there is, install on Arch Linux as above.

1. Write the image to a USB stick with your usual tool, such as `dd`.
2. Start the computer from the stick. Both UEFI and older BIOS machines work.
3. In the boot menu, choose **Start bromigOS (try it live)**. You're on the full desktop,
   and nothing is installed yet. Try the keys and look around.
4. To install, open a terminal with <kbd>Alt</kbd>+<kbd>Shift</kbd>+<kbd>Enter</kbd> and
   run:

   ```bash
   sudo bromigos-iso-install
   ```

   Or choose **Install bromigOS** in the boot menu, which opens the desktop with the
   installer already running.
5. Choose the disk to install on. **Everything on it is erased.**
6. Type your user name, your password, and a name for the computer.
7. Choose whether to encrypt the disk. It's on by default. Type a passphrase for the disk,
   or press <kbd>Enter</kbd> to use your password. You'll type it every time the computer
   starts.

   > **Remember the passphrase.** Nobody can recover it. Without it, the disk can't be
   > read.

8. Choose the keyboard layout, the time zone and the language.
9. Check the summary, and type `y` to go ahead. Pressing <kbd>Enter</kbd> on its own
   cancels.
10. Wait while it installs. It needs no network: everything is on the stick. The computer
    restarts into your new system when it's done.

The stick answers the first-run questions for you: the Wick theme, with VECTOR's brain,
voice and creation tools off. After your first login, run `bromigos setup` to change them.
See [First run](first-run.md).

The installed system updates from the package repository the stick was made for. The boot
menu's other entries are described in [The boot menu](boot-menu.md#the-install-stick).

## Next

- [First run](first-run.md): the questions bromigOS asks.
- [Getting around](desktop.md): what's on the screen, and the first keys to learn.
