# Common tasks

Step-by-step answers to everyday jobs. Each one links to the page with more detail.

Most settings live in **Settings**, which opens with <kbd>Super</kbd>+<kbd>,</kbd> (Super
and the comma key). In Settings, start typing to search for any setting.

## Apps and windows

### Open an app

1. Press <kbd>Alt</kbd>+<kbd>P</kbd>.
2. Type part of the app's name.
3. Press <kbd>Enter</kbd>.

### Open a terminal

Press <kbd>Alt</kbd>+<kbd>Shift</kbd>+<kbd>Enter</kbd>.

### Close a window

Press <kbd>Alt</kbd>+<kbd>C</kbd>.

### Install an app

1. Press <kbd>Super</kbd>+<kbd>Space</kbd> and type `package`.
2. Choose **INSTALL › Package…**.
3. Type the package's name and press <kbd>Enter</kbd>. A terminal opens and installs it.

Or in a terminal: `sudo pacman -S` and the package's name.

### Keep a website as an app

1. Press <kbd>Super</kbd>+<kbd>Space</kbd> and type `web app`.
2. Choose **INSTALL › Web app…**.
3. Type a name and the site's address.

The site opens in its own window and appears in the app launcher. See
[Web apps](webapps.md).

### Move a window to another workspace

Press <kbd>Alt</kbd>+<kbd>Shift</kbd> and the workspace's number. See
[Windows and workspaces](windows.md).

## Look and feel

### Change the theme

1. Press <kbd>Super</kbd>+<kbd>Ctrl</kbd>+<kbd>Shift</kbd>+<kbd>Space</kbd>. The theme
   switcher opens, with a picture of your desktop in each theme.
2. Choose a theme with the arrow keys, or type part of its name.
3. Press <kbd>Enter</kbd>. Every app changes colour within a second.

See [Themes and worlds](themes-and-worlds.md).

### Turn off the animated background

Press <kbd>Super</kbd>+<kbd>Shift</kbd>+<kbd>B</kbd>. Press it again to turn it back on.

To keep the background but make it calmer, see the next task.

### Reduce motion

1. Open **Settings › Accessibility**.
2. Under motion, choose **Reduced** for a calmer desktop, or **Still** for a background
   that doesn't move.

See [Accessibility](accessibility.md).

### Show or hide the panels

Press <kbd>Super</kbd>+<kbd>W</kbd> to show or hide all of them. To choose which panels
show, open **Settings › Widgets**. See [Panels](panels.md).

## Network, sound and devices

### Connect to Wi-Fi

1. Open **Settings › Network**.
2. Choose your network from the list.
3. If it has a lock, type its password. bromigOS remembers it.

### Change the volume, or switch speakers

- Use your keyboard's volume keys, or scroll over the volume on the bar.
- To switch speakers or headphones, rest the pointer on the volume on the bar and choose
  one in the [sound popup](desktop.md#the-sound-popup). **Settings › Sound** has the same
  choice.

### Mute the desktop's own sounds

Press <kbd>Super</kbd>+<kbd>Shift</kbd>+<kbd>M</kbd>. This mutes the theme's sound cues and
VECTOR's voice. Your apps keep their sound.

### Pair a Bluetooth device

1. Put the device in pairing mode.
2. Click the Bluetooth icon on the bar and choose **SCAN**.
3. Choose **PAIR** beside the device when it appears.

[Bluetooth](bluetooth.md) has the steps for an Xbox controller and for headphones.

### Set up your monitors

1. Open **Settings › Displays**.
2. Drag the monitors in the picture to match your desk, and set each one's resolution and
   scale.
3. Choose **Apply**. bromigOS asks whether to keep the new settings. If you don't answer
   within 15 seconds, it puts the old ones back.

### Change the keyboard layout

Open **Settings › Keyboard & input** and choose your layout. You can add a second layout
and a key to switch between them.

## Screen and power

### Take a screenshot

- Press <kbd>Alt</kbd>+<kbd>Y</kbd> and drag out an area.
- Press <kbd>Alt</kbd>+<kbd>Shift</kbd>+<kbd>Y</kbd> for the whole of the monitor you're
  on.

The picture goes to `~/Pictures/screenshots` and is copied to the clipboard, ready to
paste.

### Record the screen

Press <kbd>Alt</kbd>+<kbd>Shift</kbd>+<kbd>R</kbd> and drag out an area. Press it again to
stop. The video goes to `~/Videos/recordings`.

### Lock the screen

Press <kbd>Super</kbd>+<kbd>L</kbd>.

### Stop the screen locking while you watch something

Click the eye on the bar. Nothing locks or sleeps for an hour. Click it again to stop.
See [Idle and lock](idle.md#stay-awake).

### Turn off the lock when you're away

1. Open **Settings › Idle & lock**.
2. Choose **Screensaver only**. The screensaver still starts, but the screen doesn't lock.

### Shut down or restart

Press <kbd>Alt</kbd>+<kbd>Shift</kbd>+<kbd>E</kbd> and choose from the power menu.

### Stop notifications for a while

Open **Settings › Notifications** and turn on **Do not disturb**.

## VECTOR

### Ask VECTOR something

1. Press <kbd>Super</kbd>+<kbd>E</kbd>.
2. Type your question and press <kbd>Enter</kbd>.
3. Press <kbd>Esc</kbd> to go back to your work.

To talk instead of typing, hold <kbd>Super</kbd>+<kbd>V</kbd> while you speak. See
[VECTOR](vector.md).

### Write a quick note

Press <kbd>Alt</kbd>+<kbd>Shift</kbd>+<kbd>N</kbd>, type one line and press
<kbd>Enter</kbd>. It's added to your field notes. See [Panels](panels.md#field-notes).

## Keys

### Find a key

Press <kbd>Super</kbd>+<kbd>Shift</kbd>+<kbd>K</kbd> and type what you want to do. Press
<kbd>Enter</kbd> to run it. See [Keys](keys.md).

### Change a key

1. Open **Settings › Shortcuts**.
2. Under **Every key**, open the key's section, and choose **Change…** next to it.
3. Press the new keys, then let go.

See [Your own shortcuts](shortcuts.md).

## Updates

### Update bromigOS

1. Open a terminal with <kbd>Alt</kbd>+<kbd>Shift</kbd>+<kbd>Enter</kbd>.
2. Run `bromigos update`.
3. Type your password when it asks.

### Undo an update

Run `bromigos update --rollback`. It shows what the last update changed, asks, and puts
it back. See [Updating and rolling back](update-and-rollback.md).

## Your homelab

### Connect your homelab

Run `bromigos setup homelab`. It looks for your homelab's services and connects the ones
it finds. See [Your homelab](homelab.md).
