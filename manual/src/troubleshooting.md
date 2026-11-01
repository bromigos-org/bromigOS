# Troubleshooting

Find your problem below. Each one says what to try, in order.

If none of these help, open **Settings › About** and choose **Copy system info**. It copies
your version, hardware and packages, ready to paste into a bug report.

## Something looks wrong after an update

Some parts of the desktop may still run the old version. To restart them:

```bash
bromigos restart
```

To see what it would restart first, run `bromigos update --check`.

## An update broke something

Undo it:

```bash
bromigos update --rollback
```

If the computer won't start, choose an earlier snapshot in the boot menu. It starts the
system as it was, until you restart. To keep it, run `bromigos update --rollback` there,
then restart. See [The boot menu](boot-menu.md#start-an-older-version-after-a-bad-update).

## The bar, the panels or the background is gone

The bar and the animated background come back by themselves: if one stops, it starts again
within a few seconds. If one stays gone, open **Settings › Startup** and press **Fix**. Or
run `bromigos status`: it says what isn't running and the command that starts it again.

| What's gone | Run |
|---|---|
| the bar | `bromigos restart waybar` (it starts the bar if it isn't running) |
| the panels | `bromigos restart widgets` |
| the animated background | `bromigos restart live` |

If the panels are just hidden, press <kbd>Super</kbd>+<kbd>W</kbd>. If the bar is hidden,
press <kbd>Alt</kbd>+<kbd>B</kbd>. If the background is turned off, press
<kbd>Super</kbd>+<kbd>Shift</kbd>+<kbd>B</kbd>.

`bromigos live status` says what the background is doing.

## The background stopped moving after a theme change

1. Run `bromigos restart live`.
2. If it keeps happening, look in `~/.local/state/bromigos-live/live.log` for the error.

## Colours are wrong after a theme change

1. Run `bromigos theme set` with the theme's name again.
2. Some apps, such as the launcher and Qt apps, only pick up the new colours when they
   next start. Close and open them.

## Hyprland says "emergency mode"

This means your Hyprland settings file has a mistake in it.

1. Run `hyprctl configerrors`. It names the line.
2. Fix that line in your `~/.config/hypr/hyprland.lua`.
3. Run `hyprctl reload`.

bromigOS's own defaults are in `/usr/share/bromigos/default/hypr/`, if you want to compare.
Updates don't cause this: while an update replaces those files, Hyprland waits, and only
reloads once the new settings check out.

## VECTOR doesn't answer, or is silent

1. If the bar shows a red VECTOR OFF, see [VECTOR is off](#vector-is-off).
2. Run `bromigos vector status` to see whether he's running. `bromigos vector restart`
   restarts him.
3. Run `bromigos mute status`, in case the desktop's sound is muted.
4. Run `bromigos target`. It shows where his brain and voice run, and whether each one
   answers. His voice uses the first that answers: your homelab's voice service, your
   graphics card, or the processor.

## VECTOR is off

If the bar shows a red VECTOR OFF, his emergency switch is off. Only you switch it off, so
you or someone at your keyboard did. To switch him back on, press
<kbd>Super</kbd>+<kbd>Ctrl</kbd>+<kbd>Esc</kbd> and choose **YES**, or run
`bromigos vector on`. See [The emergency switch](vector.md#the-emergency-switch).

## The background is a still picture

A notification said "The graphics card isn't available". The animated background found
no working graphics card, so it shows a still picture rather than drawing on the
processor, which would make the computer hot and slow.

1. If you updated recently, restart the computer. An update to NVIDIA's graphics driver
   only takes effect after a restart, and `bromigos update` says so in its last line.
2. If it happens after a restart too, run `bromigos hw`. It says which graphics driver
   runs.
3. `bromigos live status` shows a `NO GPU` line while this lasts.

In a virtual machine, the background shows a still picture too, without the notification,
because most virtual machines have no graphics card of their own. To make it move anyway,
run `bromigos scene set general.allow_software on`. It can take several processor cores.

## A black or slow screen after a new graphics card or driver

1. Restart the computer once.
2. Run `bromigos hw`. It says which driver runs and what's missing.
3. Run `bromigos hw setup` to fix what it can.

See [Hardware](hardware.md).

## A black screen after choosing another desktop card

Restart the computer: a card you haven't kept yet goes back by itself. Or press
Ctrl+Alt+F3, log in, and run:

```bash
sudo bromigos hw display reset
sudo systemctl restart display-manager
```

See [Move the desktop to another card](hardware.md#move-the-desktop-to-another-card).

## A game won't start

Open **Settings › Playing games**. It says what stops games, and **Fix** fixes what
bromigOS can: close Steam first. From a terminal, `bromigos game check` says the same,
and `bromigos game check --fix` fixes it. See [Playing games](games.md#what-the-check-says).

A game with DLSS that crashes on a computer with two graphics cards may be on the wrong
card. See [DLSS on NVIDIA](games.md#dlss-on-nvidia).

## A Bluetooth device won't pair or connect

Choose **FORGET…** under **⋯** in the Bluetooth panel, put the device in pairing mode, and
pair it again. **Settings › Bluetooth › Troubleshooting** resets the adapter and lists what
went wrong lately. See [When it doesn't work](bluetooth.md#when-it-doesnt-work).

## The lock screen crashed

It restarts by itself, and the screen stays locked. Your password still opens it.

## The screen locks too soon, or not at all

See [Idle and lock](idle.md). To stop it locking while you watch something, click the eye
on the bar.

## A key doesn't work

1. Press <kbd>Super</kbd>+<kbd>Shift</kbd>+<kbd>K</kbd> and search for what the key should
   do. It shows the key it's on now.
2. In a terminal, `bromigos keys check "SUPER + M"` says what a key does now, and where
   that comes from.
3. To put every key back as bromigOS set them, run `bromigos keys reset`. It also removes
   your own shortcuts, and asks first.

## Signing in says there's no keyring, or it's locked

bromigOS keeps sign-ins in your keyring, and your login password unlocks it.

1. Run `bromigos keyring status`. It says what's wrong and what to run.
2. Run `bromigos keyring setup`, then sign out and in again.
3. If oo7 isn't installed, run `sudo pacman -S bromigos/oo7` first.

[Your keyring](bromigos-account.md#your-keyring) explains the rest.

## Where to look

| What | Where |
|---|---|
| your settings | `~/.config/bromigos/` |
| logs and generated files | `~/.local/state/bromigos/` and `~/.local/state/bromigos-live/` |
| the install log | `~/.local/state/bromigos/install.log` |
| bromigOS's defaults | `/usr/share/bromigos/` |

Every `bromigos` command has `--help`. Many also have `--json`, for scripts. See
[Files and folders](files.md) for more.

## Media files on a NAS

If Jellyfin cannot play a file, check its media mount, permissions and transcoding logs.
If several media apps freeze together while the NAS still answers, check the filesystem
connection from the app's host. A stuck NFS lock connection can leave imports and playback
waiting even though the server is reachable.

Ask the lab administrator to check the client mount and lock service. Reconnect through
the lab's maintenance procedure, then check the affected apps. Restarting one media app
may not fix a host's stuck connection. Avoid deleting library files to try to clear it.

For request, language and download checks, see [Your media](media.md#if-something-goes-wrong).
