# Playing games

Game mode gives the focused game your keys, including Alt, Ctrl, letters and F-keys.
It quiets notifications, stops idle locking and sleep, pauses the live wallpaper and
hides panels (widgets). The bar shows **GAME MODE**.

Press **Super+Ctrl+G** to turn it on. Press **Ctrl+Shift+F12** to leave.
An on-screen message confirms entry and exit. The escape key appears when you enter. It is the only desktop shortcut that
works during game mode. Leaving restores your previous notification state, panels and
wallpaper behaviour.

You can also use Settings › Playing games or these commands:

```bash
bromigos game on
bromigos game off
bromigos game toggle
bromigos game status
```

If you need to recover from a TTY or SSH, run `bromigos game off` as your normal user.
The keyboard escape resets the shortcut mode even if the helper cannot answer.

## Steam and Proton

Steam runs Windows games through Proton, a compatibility layer built on Wine. Proton runs
inside a Steam Linux Runtime, a small container that Steam downloads. bromigOS has three
commands for this:

```bash
bromigos game setup             # install Steam, GameMode and your GPUs' 32-bit drivers
bromigos game proton install    # get the latest GE-Proton
bromigos game check             # find what stops games from starting
```

### Set up Steam

Run `bromigos game setup`. It installs Steam and GameMode, plus the 32-bit Vulkan and
graphics drivers for the GPUs `bromigos hw` finds. GameMode is a small service that gives
a running game more of the computer's attention. Getting the drivers in the same step
stops pacman from picking a 32-bit driver for the wrong card. It asks for your password
on the terminal. `--dry-run` shows what it would do first.

Steam needs the multilib repository, which holds 32-bit packages. If it's off, setup
says how to turn it on and stops.

Setup also adds you to the `gamemode` group. Log out and back in afterwards.

### Choose a Proton version

Steam comes with its own Proton. GE-Proton is a community build with more fixes for
games and video codecs. Some games run only with it.

```bash
bromigos game proton                         # the Proton versions here
bromigos game proton install                 # the latest GE-Proton
bromigos game proton install GE-Proton10-25  # one version
bromigos game proton remove GE-Proton10-25   # remove one (close Steam first)
```

`install` downloads GE-Proton from its GitHub releases and checks it against the
SHA-512 checksum published with it. A download that doesn't match is thrown away. Then
restart Steam, and pick the version for a game in its **Properties › Compatibility**.

`remove` won't remove a version that games are still set to. Choose another version for
them first, or pass `--force`.

### DLSS on NVIDIA

DLSS and Reflex need NVIDIA's NVAPI, which Proton leaves off unless asked. On NVIDIA's
own driver, bromigOS turns it on for your session with `PROTON_ENABLE_NVAPI=1`. You need
nothing per game.

To swap a game's DLSS for the newest version Proton has, add this to the game's
**Properties › General › Launch Options**:

```text
PROTON_DLSS_UPGRADE=1 %command%
```

Use it per game. Some games check their DLSS files and refuse to start when they change.

With two graphics cards, a game may start on the wrong one. Then DLSS isn't there and
the game may crash. `bromigos hw` lists each card with its ID, such as `10de:2f04`.
To keep a game on one card, add this to its Launch Options, with that card's ID:

```text
MESA_VK_DEVICE_SELECT=10de:2f04 %command%
```

### When games won't start

Run `bromigos game check`. It looks for each problem below and says how to fix it.
`bromigos game check --fix` fixes the ones in your own files. Close Steam first. Steam
writes its settings back when it quits, which would undo the fix. `--fix` never changes
files in `/etc`. For those, it prints the commands to run.

| What it says | What it means | What `--fix` does |
|---|---|---|
| A Steam Linux Runtime is broken | Files are missing from it, such as `_v2-entry-point` or `toolmanifest.vdf`. Every game that uses it quits within a second or two. Steam's **Verify** doesn't notice. | Moves the runtime aside, into a `bromigos-backup` folder in that Steam library. Steam installs it again when you next press **Play**. |
| The default compatibility tool has the wrong priority | Steam's setting for all games should have priority 75. A higher number makes Steam run its own Linux runtimes through Proton, and installing them fails with "Invalid platform". | Sets it back to 75. It saves a copy of Steam's `config.vdf` first, in `~/.local/state/bromigos/game/backup/`. |
| A Proton needs a runtime that isn't installed | The runtime downloads the first time you play a game with that Proton. | Nothing. Press **Play**. |
| A game is set to a Proton that isn't installed | You removed a Proton that a game still uses. | Nothing. Install it again, or choose another. |
| Proton games don't get NVAPI | DLSS is missing on NVIDIA. | Nothing. Log out and back in. |
| A file in `/etc/sddm.conf.d` is still read | The login screen reads every file in that folder, whatever its name. So renaming a file to `.disabled` doesn't turn it off. A leftover setting can leave a black screen at login. | Nothing. It prints the `sudo mv` command that moves the file out. |
| waybar is enabled as a user service | bromigOS starts its bar with the desktop. A second bar appears on top of it. | Disables your `waybar.service`. Log out and back in. |
| mkinitcpio's MODULES names a package | `/etc/mkinitcpio.conf` lists a package, such as `nvidia-open`, where a kernel module belongs. The module is `nvidia`. | Nothing. It prints what to change, then `sudo mkinitcpio -P`. |

### Reinstall a broken runtime by hand

If games quit at once and `bromigos game check` isn't at hand:

1. Quit Steam (**Steam › Exit**).
2. In the Steam library that holds the runtime, delete the runtime's folder in
   `steamapps/common`, for example `SteamLinuxRuntime_4`.
3. Delete `steamapps/appmanifest_<id>.acf`, `steamapps/downloading/<id>` and
   `steamapps/temp/<id>`. The ID of Steam Linux Runtime 4.0 is 4183110.
4. Start Steam and press **Play** on the game. Steam installs the runtime first.

Installing a runtime from a `steam://install/` link doesn't work. It fails with "Invalid
platform".

## Your keyboard's Game Mode key

After first installing this feature, log out and back in so the session loads its
shortcuts, bar indicator and keyboard helper. Updating alone does not start the helper.

With the Razer keyboard module enabled, OpenRazer's Game Mode key toggles bromigOS
game mode. On a BlackWidow V4 Pro this is **Fn+F10**. Its gaming LED follows game mode,
and turns off when you leave. Use Ctrl+Shift+F12 to leave even if the keyboard
has disabled Super. See [Keyboards and peripherals](peripherals.md).

## Automatic mode

Automatic mode is off by default. Turn it on in Settings › Playing games, or run:

```bash
bromigos game auto on
```

It enters when a fullscreen Steam, Windows, gamescope or Lutris game gets focus, and leaves
when that game loses focus or stops being fullscreen. Launchers are excluded. Detached native games may need manual mode. If you leave with the escape key, automatic mode waits
until focus or fullscreen changes before entering again.

To stop automatic mode, run `bromigos game auto off`. A game mode you turned on manually
stays on when you switch windows.

## Battle.net and StarCraft II

Battle.net uses the bar's tray. Right-click its icon for its menu. After installing a
tray-bridge update, log out and back in, then reopen Battle.net.

A Lutris shortcut can launch StarCraft II through an existing Battle.net installation.
Set its Wine prefix and executable to the ones used by Battle.net and its arguments to
`--exec="launch S2"`. This uses that installation without creating another Wine prefix.
