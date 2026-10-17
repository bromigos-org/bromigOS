# Playing games

Game mode gives the focused game your keys, including Alt, Ctrl, letters and F-keys.
It quiets notifications, stops idle locking and sleep, pauses the live wallpaper and
hides panels (widgets). The bar shows **GAME MODE**.

Press **Super+Ctrl+G** to turn it on. Press **Ctrl+Shift+F12** to leave.
The escape key appears on screen when you enter. It is the only desktop shortcut that
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
