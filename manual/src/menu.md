# The menu

The menu is one place for everything: your apps, your settings, the themes, updates and
every bromigOS command. If you don't know where something is, start here.

## Open the menu and find something

1. Press <kbd>Super</kbd>+<kbd>Space</kbd>.
2. Type a few letters of what you want, such as `theme`, `update` or `firefox`. The menu
   searches every group at once.
3. Press <kbd>↑</kbd> or <kbd>↓</kbd> to choose, and <kbd>Enter</kbd> to run it.

![The menu with `theme` typed: matching groups, the theme switcher and each theme](images/menu.webp)

Press <kbd>Esc</kbd> to close the menu without running anything.

You can also browse. The first screen lists the groups. Choose one to see only its items,
and choose **‹ BACK** to return.

Items that need a terminal, such as an update or a setup question, open one. The terminal
stays open afterwards, so you can read what happened.

## What's in each group

| Group | What you'll find |
|---|---|
| LAUNCH | Your apps and web apps. |
| STYLE | The theme switcher, the next wallpaper, and each theme by name. |
| TOGGLE | Switches you turn on and off: mute, the animated background, the panels, reduced motion, a still background, high contrast, the lock when idle, stay awake, and each of the background's animations. **Screensaver** starts the screensaver now. |
| VECTOR | Show [VECTOR](vector.md), conversation mode, the hologram gallery, past conversations, and muting his voice. |
| HOLOGRAMS | The [holograms](holograms.md): the holo deck, the Drift map, the timeline, the Swarm, and the homelab's decks. |
| SETUP | [Settings](settings.md), and each [first-run question](first-run.md). Also your keys, your shortcuts, the keyboard and touchpad, and your config files. |
| INSTALL | Install a package, a [web app](webapps.md), a theme or an [extension](extensions.md). Ready-made web apps are listed here too. |
| REMOVE | Remove a package, one of your web apps or themes, or an extension. |
| UPDATE | [Update](update-and-rollback.md) bromigOS, see what an update would do, or restart what still runs old code. |
| COMMANDS | Every `bromigos` command on this machine. |
| ABOUT | The bromigOS packages installed, with their versions. |

The TOGGLE group shows each switch's state, such as **Reduced motion: off**. Choosing it
flips the switch, and the menu stays open so you can flip another.

## The menu updates itself

The menu is built from what's installed each time it opens. A new app, extension or
command of your own appears in it the next time you open it.

To print the whole menu in a terminal, run:

```bash
bromigos menu --dump
```

## The app launcher

The app launcher (<kbd>Alt</kbd>+<kbd>P</kbd>) is simpler: it lists apps only. bromigOS's
own windows are in it too, with their own icons:

- **bromigOS Settings**, **Theme Switcher** and **Extensions**;
- **Shortcuts**, to change a key, and **Key List**, to see them all;
- **Update bromigOS**, which runs the update in a terminal that stays open;
- the holograms: **Holo Deck**, **Drift Map**, **Timeline**, **Swarm**, **Lab Deck**,
  **Ops Theater**, **Network Map** and **Mind**. The homelab's decks fill in once you
  [connect your homelab](homelab.md);
- **Screensaver**, **Desktop Panels**, **Field Notes**, **Lab Console** and **Power Menu**;
- **bromigOS Menu**, which opens the menu above;
- with VECTOR installed, **VECTOR** and **Hologram Gallery**.

Type a word such as `theme`, `deck`, `keys`, `update` or `lab` to find them. Opening a
hologram or the panels from the launcher always shows them. It never closes one that's
already open.

## Add your own items

A command you write appears in the menu's COMMANDS group. See
[Your own commands](commands.md#your-own-commands).
