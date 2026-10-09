# Windows and workspaces

bromigOS arranges windows for you. Each new window gets a share of the screen, and no
window hides another unless you let it float. You move between windows and workspaces
with the keyboard, or with the mouse if you prefer.

The window keys use **Alt**. If you'd rather use **Super**, see
[Use Super for the window keys](shortcuts.md#use-super-for-the-window-keys).

## How windows are arranged

The first window takes the large space on the left. Each new window goes to the top of
the stack on the right. Close a window and the rest grow to fill the space.

| To | Press |
|---|---|
| move to the next or previous window | <kbd>Alt</kbd>+<kbd>J</kbd> or <kbd>Alt</kbd>+<kbd>K</kbd> |
| move to the window on the left or right | <kbd>Alt</kbd>+<kbd>H</kbd> or <kbd>Alt</kbd>+<kbd>L</kbd> |
| make this window the large one | <kbd>Alt</kbd>+<kbd>Enter</kbd> |
| move this window left, right, up or down | <kbd>Alt</kbd>+<kbd>Shift</kbd> and <kbd>H</kbd>, <kbd>L</kbd>, <kbd>K</kbd> or <kbd>J</kbd> |
| move the edge between the large window and the stack | <kbd>Alt</kbd>+<kbd>←</kbd> or <kbd>Alt</kbd>+<kbd>→</kbd> |
| close this window | <kbd>Alt</kbd>+<kbd>C</kbd> |

Pointing at a window with the mouse also moves you to it. To change that, open
**Settings › Keyboard & input** and choose another **Window focus**.

## Use the mouse

- To move a window, hold <kbd>Alt</kbd> and drag it with the left mouse button.
- To resize a window, hold <kbd>Alt</kbd> and drag it with the right mouse button.

## Make a window bigger

| To | Press |
|---|---|
| fill the screen, but keep the bar | <kbd>Alt</kbd>+<kbd>F</kbd> |
| go fullscreen, over the bar | <kbd>Alt</kbd>+<kbd>Shift</kbd>+<kbd>F</kbd> |

Press the same keys again to put the window back.

## Let a window float

A floating window sits above the others, at any size, like on most desktops. Dialog boxes
float on their own.

To float the window you're in, press <kbd>Alt</kbd>+<kbd>Shift</kbd>+<kbd>V</kbd>. Press
it again to put the window back in the tiles.

### Put floating windows back where you left them

bromigOS can remember where you put a floating window, for each workspace, and put it
there the next time it opens.

1. Open **Settings › Startup**.
2. Under **Windows put back**, turn on **Every floating window**. Or type one app's class
   in **Remember an app (its class)**, such as `org.pulseaudio.pavucontrol` for the volume
   mixer.
3. Choose **Restart** on the **bromigos-windows** row, or log in again. The change works
   from then on.

To find an app's class, run `hyprctl clients` in a terminal while the app is open.

Or from a terminal:

```bash
bromigos startup windows remember org.pulseaudio.pavucontrol   # remember this app's windows
bromigos startup windows restart                               # use the change now
bromigos windows list                                          # what's remembered
bromigos windows clear                                         # forget them all
```

## Workspaces

A workspace is a separate screenful of windows. There are ten. Use them to keep tasks
apart: a browser on one, your project on another.

| To | Press |
|---|---|
| go to workspace 1 to 10 | <kbd>Alt</kbd> and a number key. <kbd>0</kbd> is workspace 10. |
| send this window to another workspace | <kbd>Alt</kbd>+<kbd>Shift</kbd> and a number key |

Sending a window doesn't move you with it. The bar shows the workspaces that have
windows. Click one to go there.

On a laptop, swipe sideways with three fingers on the touchpad to move between
workspaces.

### With more than one monitor

The ten workspaces are shared out across your monitors, from left to right. With two
monitors, workspaces 1 to 5 are on the left one and 6 to 10 on the right one. Pressing a
workspace's key takes you to the monitor it's on.

To choose which workspaces go on which monitor, see the `workspaces` setting in your
`~/.config/hypr/hyprland.lua`. The file's comments show the format.

## The scratchpad

The scratchpad is a hidden workspace that opens over the one you're on. It's handy for a
terminal or notes you want now and then.

| To | Press |
|---|---|
| put this window on the scratchpad | <kbd>Alt</kbd>+<kbd>Shift</kbd>+<kbd>S</kbd> |
| show or hide the scratchpad | <kbd>Alt</kbd>+<kbd>S</kbd> |

## Switch windows from a list

Press <kbd>Alt</kbd>+<kbd>Tab</kbd> for a list of every open window. Type to filter it,
and press <kbd>Enter</kbd> to go to the one you pick.
