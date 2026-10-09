# The desktop menu

Super+Space opens one menu for the whole desktop. It launches apps, installs things, sets
the desktop up, changes the style, updates, and switches things on and off. It's built
from what's installed each time it opens, so nobody keeps its list by hand, and a new
command appears in it on its own.

This page is for someone adding an item or changing the menu. For using it, read the
manual's [The menu](../manual/src/menu.md) page.

The menu is `bromigos-menu`, from `bromigos-desktop`. It's rofi in script mode, in the
launcher's theme.

## Finding things

The top level lists the groups, followed by every item of every group, written as
`GROUP › item`. So typing finds anything at once. For example, `the` matches
`STYLE › Theme…`, `Theme: Mire` and `SETUP › Theme`.

- Choosing a group narrows the list to that group. `‹ BACK` goes back up.
- Enter runs the item.
- After a toggle, such as an animation or the mute, the menu shows its group again with
  the new state.

## Where the items come from

| Group | Read from |
|---|---|
| LAUNCH | The desktop entries, through `Gio.AppInfo`, with their icons |
| STYLE | `bromigos theme list --json`: the theme switcher, the next wallpaper, each theme |
| TOGGLE | Animations, the mute, the live layer, the panels, the screensaver, power profiles, accessibility, idle |
| VECTOR | `bromigos-holo`'s verbs, when VECTOR is installed |
| HOLOGRAMS | The live layer's decks, when the live layer is installed |
| SETUP | Settings…, the `bromigos setup` sections, the desktop's setup tools, Shortcuts… |
| INSTALL, REMOVE | Packages, web apps, themes and extensions |
| UPDATE | `bromigos update`, `bromigos update --check`, `bromigos restart` |
| COMMANDS | `bromigos commands --json`: every command the router knows |
| ABOUT | The installed bromigOS packages and their versions |

Some groups read several sources:

- **LAUNCH** leaves out bromigOS's own entries. Each of those joins the menu item it
  stands for instead. See [No duplicates](#no-duplicates).
- **TOGGLE** reads each switch and its state from `bromigos anim --json`. It adds the
  mute, the live layer, the panels (widgets) and the screensaver. It lists the power
  profiles that power-profiles-daemon offers (`powerprofilesctl list`), which matters on a
  laptop ([hardware.md](hardware.md)). From `bromigos accessibility --json` it adds Reduced
  motion, Still background and High contrast ([accessibility.md](accessibility.md)). From
  `bromigos idle status --json` it adds Lock on idle and Stay awake, each with its state
  ([idle.md](idle.md)).
- **HOLOGRAMS** lists the decks. A deck is a full-screen holographic view, such as the
  timeline. When a plugin's deck isn't installed, its row says so.
- **SETUP** has Settings… (`bromigos settings`, [settings.md](settings.md)), and the
  `bromigos setup` sections: monitors, hardware, accessibility, theme, VECTOR, voice,
  homelab, create and targets. It also has the desktop's setup tools (keybindings, input
  and config files) and Shortcuts…, which opens `bromigos keys`
  ([desktop.md](desktop.md#shortcuts-you-set-by-pressing-the-keys)).
- **INSTALL and REMOVE** cover packages through pacman, web apps (`bromigos webapp` and
  its catalog), and themes (`bromigos theme install <git url>` and your own). Extension…
  runs `bromigos install extension` or `bromigos remove extension`
  ([extensions.md](extensions.md)).
- **COMMANDS** lists built-ins and every `bromigos-<group>-<name>` executable. A command
  whose header has `# bromigos:hidden=true` stays out.

### How items run

Items that need a terminal open one and keep it open afterwards. That includes an update,
a setup screen and a pacman transaction. The terminal is `$TERMINAL`, or kitty. Everything
else runs detached.

Prompts are typed into the same window: a package's name, a web app's name and then its
URL, or a theme's URL.

## Placing a command in a group

A `bromigos-<group>-<name>` executable can ask for a place in the menu. It adds two header
lines next to its `# bromigos:summary=` line:

```text
# bromigos:menu=INSTALL:Extension…
# bromigos:prompt=GIT URL
```

- `menu=` names the group's label, then the row's label.
- `prompt=` is optional. It asks for one argument first.

The command then shows under that group, as INSTALL › Extension… here. It runs in a
terminal, with the typed argument added at the end. It still appears under COMMANDS too.

The groups are LAUNCH, STYLE, TOGGLE, VECTOR, HOLOGRAMS, SETUP, INSTALL, REMOVE, UPDATE,
COMMANDS and ABOUT.

## In the app launcher

Every bromigOS window is also an app. Alt+P opens rofi's app launcher, which lists them,
and so does any launcher that reads desktop entries. Each entry has a Comment, which says
what it does and serves as a launcher's hover hint. It also has Keywords to find it by.
For example, `theme` finds the theme switcher, `deck` finds every deck, and `settings`
finds everything that sets something.

Each package ships the entries for what it owns:

| Entry | What it opens | Package | Menu item |
|---|---|---|---|
| bromigOS Settings | `bromigos settings` | bromigos-desktop | SETUP › Settings… |
| Theme Switcher | `bromigos-theme-switcher` | bromigos-desktop | STYLE › Theme… |
| Shortcuts | `bromigos keys` | bromigos-desktop | SETUP › Shortcuts… |
| Key List | `bromigos setup keybindings` | bromigos-desktop | SETUP › Keybindings |
| Extensions | `bromigos extensions` | bromigos-desktop | INSTALL › Extension catalog… |
| bromigOS Menu | this menu | bromigos-desktop | none, it's the menu |
| Power Menu | lock, suspend, log out, reboot, shut down | bromigos-desktop | LAUNCH |
| Update bromigOS | `bromigos update` in a terminal | bromigos-core | UPDATE › Update bromigOS |
| Holo Deck, Drift Map, Timeline, Swarm | `bromigos-live open <deck>` | bromigos-live | HOLOGRAMS |
| Screensaver | `bromigos-live open screensaver` | bromigos-live | TOGGLE › Screensaver |
| Desktop Panels | `bromigos-widgets show all` | bromigos-widgets | TOGGLE › Desktop panels |
| Field Notes | `bromigos-widgets notes` | bromigos-widgets | LAUNCH |
| Lab Console | `bromigos lab` in a terminal | bromigos-homelab | LAUNCH › Lab console |
| Lab Deck, Ops Theater, Network Map, Mind | `bromigos-live open <deck>` | bromigos-homelab | HOLOGRAMS |
| VECTOR, Hologram Gallery | `bromigos-holo vector-show`, `gallery-show` | bromigos-vector | VECTOR |

Settings' window class is `org.bromigos.Settings`. Field Notes opens the notes panel ready
to type in.

### Launchers open, they never toggle

- `bromigos-live open` shows a deck that's already up, rather than closing it. It starts
  the live layer first when it isn't running.
- `bromigos-widgets show` and `notes` start the panels when they aren't running.
- An entry that needs a terminal runs `bromigos terminal [--hold] -- COMMAND`. The
  terminal is `$TERMINAL`, or kitty, as in the menu. `--hold` keeps it open so you can
  read the outcome.
- Each entry has `TryExec`, so it's listed only while its program is installed. The Lab
  Console appears only with `bromigos lab`.

### No duplicates

An entry names the menu item it stands for with `X-Bromigos-Menu=<id>`. The ids come from
`bromigos menu --json`. The menu keeps that item in its group, with its own label, and
gives it the entry's icon. The entry isn't also listed under LAUNCH.

- An id the menu doesn't have yet puts the entry in that group under that id.
  `X-Bromigos-Menu-Label` names the row.
- `X-Bromigos-Menu=-` keeps an entry out. The menu's own entry uses it.

An extension's entry, or your own, can do the same.

### Icons

Each icon is a glyph inside the emblem's ring, with the ring's notch at twelve o'clock and
the tick ring from 48 px up. It's phosphor green on a dark disc, so it reads on a light
launcher too.

`theme/tools/build-app-icons.py` draws them in code. It draws 16, 24 and 32 px separately
so the strokes stay bold, and a scalable version above that. They install into the hicolor
icon theme as `bromigos-<name>`, which every icon theme inherits. VECTOR's two icons come
with him.

### Tests

`tools/launcher/check.py` runs in CI's `launcher.yml`. Each package's `check()` runs its
static part. It checks:

- `desktop-file-validate` on every entry, with nothing to report;
- the keys every entry needs, and its icon at every size;
- each Exec, run from the checkout against stand-ins. A deck must reach the live layer's
  socket as `<deck> open`, and the panels' as `show all`. A terminal entry must start
  kitty with exactly its command. Settings and the switcher must answer `--help`.
- `bromigos menu --json` with only these entries installed. Nothing appears under LAUNCH
  twice, each item appears once with its icon, no label repeats in a group, and no action
  is reachable from two items.
- the launcher's listing, and that the Lab Console disappears when its program does.

`tools/launcher/render.py OUTDIR` draws rofi's Alt+P listing offscreen, including a few
filtered by words, in a nested Hyprland nobody sees. It also starts the panels from
nothing there.

## From a terminal

```text
bromigos menu            open it
bromigos menu --dump     print the tree as text, as the menu would show it
bromigos menu --json     the same as JSON: id, label, hint and action for each item
bromigos menu --run ID   run one item by its id, such as style/theme/mire
```

The fresh-machine test checks `--dump` (`test/vm/checks.sh`).

## Related keys

| Keys | What they do |
|---|---|
| Alt+P | Open the plain app launcher (`rofi -show drun`), which lists every bromigOS window. |
| Super+Ctrl+Shift+Space | Open the theme switcher. See [theming.md](theming.md). |
| Super+Ctrl+Space | Show the next wallpaper. |
| Super+K | Show the SHORTCUTS panel, the same list as SETUP › Keybindings. |

Any menu item can have a key of its own. SETUP › Shortcuts… lists the menu's items next to
bromigOS's binds, and the key you press runs the item. A program runs directly, and a
terminal item runs through `bromigos menu --run ID`. See
[desktop.md](desktop.md#shortcuts-you-set-by-pressing-the-keys).
