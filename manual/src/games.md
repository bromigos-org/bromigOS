# Playing games

Install Steam, then press **Play**. bromigOS keeps everything a game needs to start ready
by itself, and tells you only when something needs you.

## Steam and Proton

Steam runs Windows games through Proton, a compatibility layer built on Wine. You don't
need to know how Proton works: bromigOS chooses a good one, keeps it current and repairs
what would stop a game from starting.

### Get started

1. Open **Settings › Playing games** and press **Set up Steam**. A terminal opens and asks
   for your password once. It installs Steam, GameMode, and the graphics drivers games
   need for the graphics cards in this computer.
2. Log out and back in.
3. Start Steam, sign in, install a game and press **Play**.

The first time Steam starts, bromigOS downloads the newest GE-Proton in the background
and makes it the Proton every game uses. GE-Proton is a community build of Proton with
extra fixes for games and video. It's checked against the checksum its makers publish
before it's installed.

### What bromigOS does for you

After every `bromigos update`, and each time you quit Steam, bromigOS:

- installs the newest GE-Proton, and makes it the default when the default is missing
  or an older GE-Proton;
- points a game set to a Proton that isn't installed any more back at one that is;
- puts the setting that lets Steam install its own runtimes back to Steam's own value;
- moves a broken Steam Linux Runtime aside, so Steam installs a fresh one the next time
  you press **Play**;
- moves old GE-Proton versions that no game uses aside, keeping the newest two.

It never changes Steam's files while Steam is open, because Steam would write its own
settings back when it quits. It never starts or stops Steam. Everything it changes can be
undone. Steam's settings file is copied first, and anything it moves aside is kept for
14 days.

Your choices stay. If you picked another Proton as the default, such as Valve's Proton
Experimental, bromigOS keeps it. A game you set to a Proton that's installed keeps it too.

### Is everything ready?

Open **Settings › Playing games**. The top of the page says **Games are ready**, or lists
what needs you, each with what to do. Hover over anything on the page to see what it is
and does. The page also shows which Proton your games use.

Things bromigOS fixes by itself are listed with when it will fix them. To fix them now,
close Steam and press **Fix**. If a leftover file from an older bromigOS set-up still
changes your login screen, **Fix** asks for your password to remove it. Updates remove
those files too.

When something needs you, such as a setting outside your home folder, you get one
notification that says so. You get it once, not every time you quit Steam.

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

If you changed the file that holds your session's graphics settings,
`~/.local/state/bromigos/hw/hyprland.lua`, bromigOS leaves it alone and doesn't turn
NVAPI on. Settings › Playing games says so. To hand the file back to bromigOS, run:

```bash
mv ~/.local/state/bromigos/hw/hyprland.lua ~/hyprland.lua.mine
bromigos hw setup --user-only
```

Then log out and back in. Your own version stays in `~/hyprland.lua.mine`.

## Game mode

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

## Doing it by hand

You don't need any of this: bromigOS does it for you. It's here for when you want to see
or change what it does.

### The commands

```bash
bromigos game setup               # install Steam, GameMode and your GPUs' 32-bit drivers
bromigos game check               # find what stops games from starting
bromigos game check --fix         # fix it now (close Steam first)
bromigos game maintain --dry-run  # what bromigOS would change by itself, changing nothing
bromigos game proton              # the Proton versions here
bromigos game proton install      # the latest GE-Proton
bromigos game proton install GE-Proton10-25   # one version
bromigos game proton remove GE-Proton10-25    # remove one (close Steam first)
```

`game setup --dry-run` shows what setup would install. Steam needs the multilib
repository, which holds 32-bit packages. If it's off, setup says how to turn it on and
stops.

`game proton install` downloads GE-Proton from its GitHub releases. It checks the
download against the SHA-512 checksum published with it, and throws away a download
that doesn't match. Pick a version for one game in Steam: the game's
**Properties › Compatibility**. `remove` won't remove a version games are still set to,
unless you pass `--force`.

To see what bromigOS did and when, run:

```bash
journalctl --user -u bromigos-game-maintain
```

Settings › Playing games › **Log** opens the same list.

### What the check says

| What it says | What it means | Who fixes it |
|---|---|---|
| A Steam Linux Runtime is broken | Files are missing from it, such as `_v2-entry-point` or `toolmanifest.vdf`. Every game that uses it quits within a second or two. Steam's **Verify** doesn't notice. | bromigOS moves it aside, into a `bromigos-backup` folder in that Steam library. Steam installs it again when you next press **Play**. |
| The default compatibility tool has the wrong priority | Steam's setting for all games should have priority 75. A higher number makes Steam run its own Linux runtimes through Proton, and installing them fails with "Invalid platform". | bromigOS sets it back to 75, after copying Steam's `config.vdf` to `~/.local/state/bromigos/game/backup/`. |
| The Proton every game uses isn't installed, isn't set or is older | The default for all games points at a Proton that's gone, or at an older GE-Proton. | bromigOS makes the newest GE-Proton the default. |
| A game is set to a Proton that isn't installed | You removed a Proton that a game still uses. | bromigOS sets the game back to the default. A game set to an old GE-Proton or TKG build gets the newest GE-Proton instead. |
| Old Proton versions no game uses | GE-Proton or TKG builds that nothing uses take up space. | bromigOS moves them aside, keeping the newest two GE-Proton versions. |
| A Proton needs a runtime Steam installs on Play | The runtime downloads the first time you play a game with that Proton. | Nobody: press **Play**. |
| Proton games don't get NVAPI | DLSS is missing on NVIDIA. | You: log out and back in. See [DLSS on NVIDIA](#dlss-on-nvidia). |
| A login screen file only repeats bromigOS's settings | A file in `/etc/sddm.conf.d` from an older set-up. Left there, it would override future changes to the login screen. | bromigOS moves it to `/var/lib/bromigos/sddm-backup/` when it updates. **Fix** in Settings does it now. |
| A login screen file changes bromigOS's login screen | A file in `/etc/sddm.conf.d` sets something differently, such as another theme. The check says what it changes. | You, if you didn't set it on purpose. It prints the `sudo mv` command that moves the file out. |
| A file in `/etc/sddm.conf.d` is still read | The login screen reads every file in that folder, whatever its name. So renaming a file to `.disabled` doesn't turn it off. A leftover setting can leave a black screen at login. | You. It prints the `sudo mv` command that moves the file out. |
| waybar is enabled as a user service | bromigOS starts its bar with the desktop. A second bar appears on top of it. | **Fix** disables your `waybar.service`. Log out and back in. |
| mkinitcpio's MODULES names a package | `/etc/mkinitcpio.conf` lists a package, such as `nvidia-open`, where a kernel module belongs. The module is `nvidia`. | You. It prints what to change, then `sudo mkinitcpio -P`. |

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

### Turn off the automatic upkeep

To stop bromigOS from keeping Steam and Proton ready by itself, run:

```bash
systemctl --user mask bromigos-game-maintain.service
```

Updates then leave Steam and Proton alone too. `systemctl --user unmask
bromigos-game-maintain.service` turns it back on.
