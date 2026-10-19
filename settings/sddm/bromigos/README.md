# The login screen

This folder is bromigOS's theme for SDDM, the login screen you see at boot. It matches the
lock screen: the dimmed den, the turning emblem, "TRANSMISSION INTERCEPTED", a big clock
and a terminal-style sign-in, in phosphor green on black, set in Geist Mono. On top of the
lock screen's look, it adds the account, a session chooser and the power buttons.

The den is the default theme's wallpaper, a radio room with live screens. The emblem is
the burn-in, a flame inside a ring of text.

## How it's installed

It runs on SDDM's Wayland greeter, with Weston as the greeter's compositor and a Qt 6
greeter (`QtVersion=6`). The `bromigos-settings` package installs it:

| Installed | From |
|---|---|
| `/usr/share/sddm/themes/bromigos/` | This folder, plus the art below |
| `/usr/share/sddm/themes/bromigos/assets/` | The Wick's lock-screen ring and flame, and the empty den |
| `/usr/share/sddm/themes/bromigos/fonts/` | Links to Geist Mono and its licence |
| `/usr/lib/sddm/sddm.conf.d/zz-bromigos.conf` | `../conf/zz-bromigos.conf` |
| `/usr/lib/bromigos/sddm/bromigos-greeter` | `../bromigos-greeter`, Weston's launcher |

The art comes from elsewhere in the repository:

- `themes/wick/emblem/lock/ring.png` and `flame.png` become `assets/ring.png` and
  `assets/flame.png`;
- `desktop/wallpaper/bromigos-lock-empty-2560x1440.jpg` becomes `assets/background.jpg`.

`zz-bromigos.conf` sets `Current=bromigos`, the cursor, and the Wayland greeter. It's named
`zz-` so it comes after the `sddm` package's own `default.conf`. A machine's own
`/etc/sddm.conf.d/` and `/etc/sddm.conf` still win.

The packaged compositor launcher reads `bromigos hw display --json` before it starts
Weston. When exactly one usable host GPU has a screen connected, it passes that card
through Weston's `--drm-device` option. It allows up to two seconds for devices that
are still starting. Each query has a one-second timeout.

An administrator's `CompositorCommand` override keeps control, as does an explicit
`--drm-device` argument to the launcher. If the hardware command is missing, too old,
fails, or cannot make a single choice, Weston uses its usual device choice. Seats other
than `seat0` also keep Weston's usual choice. The launcher does not install drivers or
change a running session. See
[GPU selection](../../../docs/hardware.md#choosing-the-gpu-with-a-connected-screen).

`bromigos install` enables SDDM unless another display manager is already enabled
([docs/install.md](../../../docs/install.md)). Nothing restarts SDDM, so the theme shows at
the next boot or logout.

To preview the installed theme in a window:

```bash
sddm-greeter-qt6 --test-mode --theme /usr/share/sddm/themes/bromigos
```

## Rules

- **No live data, no network.** The greeter runs as the `sddm` user before anyone signs
  in. It has no homelab, no plugins and no VECTOR. Nothing on screen pretends to be a
  reading. The only things that move are the emblem, the stars and the clock.
- **It's a public screen.** Anyone at the desk sees it. It shows no callsign, frequency or
  dossier. It never shows the account name: a remembered account appears as "ACCOUNT ON
  RECORD". The den is always the empty lock-screen variant, never one with a person in it.
- **Cheap motion.** One `RotationAnimator`, on the render thread, and a few dozen opacity
  animations. No shaders, no CRT effect, no scanlines.

## What's on screen

| Element | What it looks like | Code | Setting in `theme.conf` |
|---|---|---|---|
| Den | The lock-screen den, dimmed and cropped to fill | `Main.qml`, the first `Image` | `background` |
| Stars | About 80 faint dots twinkling in the sky, top left | `components/Starfield.qml` | `stars` (0 turns them off) |
| Emblem | The ring turning anticlockwise, the flame still | `Main.qml`, `emblem` | `ring`, `flame`, `ringSeconds` |
| Caption | "TRANSMISSION INTERCEPTED" | `Main.qml`, `caption` | `caption` |
| Clock and date | The time in large type, the date in spaced capitals | `Main.qml`, `clock` and `date` | none |
| Account | "ACCOUNT ON RECORD", or a `USER` line | `components/Field.qml` | none |
| Passphrase | A `>` prompt, dots and a blinking block cursor | `components/Field.qml` | none |
| Status line | The sign-in state | `Main.qml`, `statusLine` | none |
| Failure | The field shakes and clears | `Main.qml`, `failAnim` | none |
| Session | `SESSION HYPRLAND ▴`, which opens a list upwards | `components/SessionButton.qml`, `SessionMenu.qml` | `defaultSession` |
| Power | `SUSPEND`, `REBOOT`, `SHUT DOWN` | `components/PowerButton.qml` | none |
| Hint line | What the hovered or focused control does | `Main.qml`, `hintLine` | none |
| Sign-off | "STILL LIT." in dim green at the bottom | `Main.qml`, the last `Text` | `signoff` |

Some details:

- **The emblem's ring** makes one turn every 24 seconds by default (`ringSeconds`). The
  flame and its halo stay still.
- **The clock** is 138 px tall at 2560×1440, and a one-second `Timer` updates it.
- **The status line** shows `> VERIFYING` in amber, `> REJECTED · n` in red, and
  `CAPS LOCK IS ON` in amber. It also shows SDDM's own messages.
- **A failed sign-in** turns the outline red and swings it three times over 430 ms. The
  field clears, and red text stays for 2.5 seconds. The code is `failAnim` and `rejected()`
  in `Main.qml`.
- **Reboot and shut down** need a second press within 4 seconds. The button says
  "AGAIN TO …" in amber in between. The code is `power()` in `Main.qml`.
- **Each control** carries its own description in `about`, which the hint line shows.

Positions are in units of one pixel at 2560×1440. `root.s` scales them, so the layout holds
at 1080p.

## Keyboard

Focus starts on the passphrase when an account is remembered, or on the user line when
none is.

| Keys | What they do |
|---|---|
| Enter | Sign in. |
| Esc | Clear the passphrase. |
| Tab, Shift+Tab | Move through user, passphrase, session, suspend, reboot and shut down. |
| Space, on "ACCOUNT ON RECORD" | Switch to typing another account. A click does the same. |
| Up, Down, in the session list | Move through the sessions. |
| Enter, in the session list | Choose a session. |
| Esc, in the session list | Close the list. |

## Files

| File | What it is |
|---|---|
| `Main.qml` | The screen: palette, layout, state, and the calls to SDDM (`sddm.login`, `suspend`, `reboot`, `powerOff`) |
| `components/*.qml` | `Field`, `SessionButton`, `SessionMenu`, `PowerButton` and `Starfield` |
| `components/TestDriver.qml` | Steps through the screen's states for the test, below |
| `metadata.desktop` | SDDM's theme metadata, for Qt 6 |
| `theme.conf` | The theme's settings: asset paths, caption, sign-off, the ring's speed, stars |
| `../conf/zz-bromigos.conf` | The SDDM drop-in, described above |
| `../bromigos-greeter` | Reads the automatic GPU choice and starts Weston |
| `../tests/` | Launcher tests with stand-ins for the hardware command and Weston |
| `packaging/bromigos-settings/PKGBUILD` | Puts it together |

## Changing it

1. Edit the files here.
2. Lay out a test copy and run the greeter without root:

   ```bash
   t=$(mktemp -d); cp -r settings/sddm/bromigos/. "$t/"; mkdir -p "$t/assets"
   cp themes/wick/emblem/lock/{ring,flame}.png "$t/assets/"
   cp desktop/wallpaper/bromigos-lock-empty-2560x1440.jpg "$t/assets/background.jpg"
   mkdir -p /tmp/sddm-shots; echo 'testShots=/tmp/sddm-shots' >> "$t/theme.conf"
   echo '{"screens":[{"name":"TEST-1","x":0,"y":0,"width":2560,"height":1440,"logicalDpi":96,"logicalBaseDpi":96,"dpr":1}]}' > /tmp/screen.json
   QT_FORCE_STDERR_LOGGING=1 QT_QPA_PLATFORM="offscreen:configfile=/tmp/screen.json" \
     timeout 30 sddm-greeter-qt6 --test-mode --theme "$t"
   ```

   `components/TestDriver.qml` steps through idle, typing, a wrong password, caps lock,
   the session list and an armed shut-down. It saves each state as
   `/tmp/sddm-shots/<w>x<h>-<state>.png`. It only runs when `theme.conf` sets
   `testShots`, which no installed theme does. In test mode SDDM never signs anyone in,
   so the driver simulates the failure.

3. Repeat with 1920×1080 in the screen file.
4. Check that the greeter printed no QML warnings.
5. Commit. Each machine gets the change with its next `bromigos update`, and it shows at
   the next login screen.

The lock screens it matches are gtklock's (`desktop/gtklock/`) and hyprlock's
(`desktop/hypr/hyprlock.conf`). When the look changes, change all three together.
