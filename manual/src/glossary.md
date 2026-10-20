# Glossary

The words this manual uses for parts of bromigOS, in alphabetical order. Some come from
the bromigOS story. You never need the story to use the desktop.

## AUR

The Arch User Repository: build recipes that Arch Linux users share, for software that
isn't in Arch Linux's own repositories. Nobody vets them. paru, which bromigOS installs,
builds them on your machine. See
[Install an app from the AUR](apps.md#install-an-app-from-the-aur).

## Bar

The strip along the top of the screen. It shows your workspaces, the window title, what's
playing, readings such as processor and memory use, and the clock. See
[The bar](desktop.md#the-bar).

## Burn-in

The bromigOS emblem: a flame inside a ring of text. It appears on the lock screen, at
login, in the boot menu and on the screensaver.

## Channel

Which stream of updates your machine follows: `stable`, `rc`, `edge` or `dev`. See
[Channels](update-and-rollback.md#channels).

## Codec call

A short spoken message from the desktop about something important, such as a long job
finishing. It shows on screen in a small panel while it plays. You can turn the voice off
and keep the panel (<kbd>Super</kbd>+<kbd>Shift</kbd>+<kbd>C</kbd>). The name comes from
the radio calls of the story.

## Coding agent

An AI program that writes code for you in a terminal. bromigOS shows agents that run in
`herdr`, a terminal workspace manager. The [worlds](#world) and the
[Swarm](holograms.md#swarm) show when an agent is working or needs you.

## Colour theme

A [theme](#theme) that changes the colours of everything and shows the [den](#den) in
those colours. bromigOS has eight: Rime, Sunder, Cinder, Lowtown, Highwind, Deepvein, and
Wick · Tidewell and Wick · Mire, the den in the two worlds' colours.

## Creation tools

The AI tools that make images, edits, cutouts (a picture with its background removed),
3D models and short video loops. VECTOR uses them. See
[Creating with AI](where-ai-runs.md).

## Deck

A full-screen [hologram](#hologram) that opens over your windows: the holo deck, the
timeline, the Drift map and the Swarm, and with a homelab the lab deck, Mind, Ops theater
and the network map. One deck shows at a time. See [Holograms](holograms.md).

## Den

The background of the Wick theme: a radio room with a desk of old consoles and a window
onto space. Parts of it move with your machine's readings. Colour themes show the den in
their own colours.

## Den TV

The [den](#den)'s screens playing your own videos as TV channels: from Jellyfin, Plex,
YouTube or a folder, always part-way through something, as if they'd been on all along.
Each screen plays its own channel. A *TV channel* is one of these, not an update
[channel](#channel). The channel guide (Settings › Den TV) lists them all. See
[The den TV](themes-and-worlds.md#the-den-tv).

## The Drift

The part of space where the bromigOS story takes place. Each [world](#world) is a post
somewhere in the Drift, and the Drift map is a chart of it.

## Extension

An add-on that somebody shares as a git repository: a theme, a deck, a panel, a tool for
VECTOR, a homelab adapter or a command. See [Extensions](extensions.md).

## Field notes

Your notes, in the FIELD NOTES panel. They save as you type. See
[Field notes](panels.md#field-notes).

## Homelab

Computers you run yourself, at home or in a cupboard: servers, a machine with a graphics
card for AI, a NAS. bromigOS can show your homelab on the desktop and run AI work on it.
"The lab" means the same thing. See [Your homelab](homelab.md).

## Hologram

A glowing 3D view. VECTOR appears as one, [decks](#deck) are full-screen ones, and the
gallery holds 3D models you can turn and take apart. See [Holograms](holograms.md).

## Hyprland

The window manager bromigOS runs on. It places your windows and runs the keys.

## Keeper

The figure who lives in a [world's](#world) scene, such as Hollis on the porch in Mire.
The keeper works while you work and dozes when you leave.

## The lab

Your [homelab](#homelab). `bromigos lab` is its console. See
[The lab console](lab.md).

## Live layer

The program that draws the animated background, the screensaver, the [decks](#deck) and
the lock-screen animation. Its package is `bromigos-live`. Turn the background off and on
with <kbd>Super</kbd>+<kbd>Shift</kbd>+<kbd>B</kbd>.

## The line

Showing VECTOR. In the story VECTOR talks to you over a radio line, so the menu calls
showing him "the line".

## The menu

The bromigOS menu, which opens with <kbd>Super</kbd>+<kbd>Space</kbd>. It launches apps
and runs everything bromigOS does. See [The menu](menu.md).

## Migration

A small script that an update runs to adjust your settings after bromigOS changes. A
migration that has to change one of your files keeps a copy of the old one.

## nolgia

A paid cloud service for AI images, video and 3D models. bromigOS can only use it once you
sign in to it, and then only where you allow the cloud or choose nolgia for a creation
tool. See [Creating with AI](where-ai-runs.md).

## Panel

A readout on the desktop, under your windows: SYSTEM, NETWORK, STORAGE, WORKBENCH, FIELD
NOTES, SHORTCUTS, and others you can turn on. bromigOS's own files sometimes call them
widgets. See [Panels](panels.md).

## Peripheral module

Optional support for a device's extra features, such as a keyboard's macro keys, dial and
lighting. See [Keyboards and peripherals](peripherals.md).

## Post

In the story, a relay station somewhere in the Drift. Each [world](#world) shows the view
from one post.

## Primary monitor

The monitor where the background, the panels and VECTOR appear. Choose it in
**Settings › Displays**.

## Private overlay

Settings you keep encrypted alongside your dotfiles, such as addresses or keys.
`bromigos private edit` edits them and decrypts them again. It needs the `sops` and `age`
packages. bromigOS decrypts them when you sign in, and again whenever the encrypted file
changes, such as after you pull your dotfiles. Without your age key, nothing happens.

## Scanner

A drawing of your machine's hardware that the background can show, with live readings.
Hold <kbd>Super</kbd>+<kbd>Z</kbd> to see it, or press <kbd>Super</kbd>+<kbd>X</kbd> to
pin it.

## Scratchpad

A hidden workspace that opens over the one you're on. See
[Windows and workspaces](windows.md#the-scratchpad).

## Snapshot

A saved copy of the system's files. If your system disk uses btrfs, bromigOS takes one
before and after every update, so you can undo the update. See [Updating and rolling back](update-and-rollback.md).

## Super

The key with the Windows or logo symbol on it. bromigOS's own keys use it.

## Target

A place where AI work can run: `homelab`, `local` (this machine) or `cloud`. See
[Creating with AI](where-ai-runs.md).

## Theme

The whole look of the desktop: the colours of every app, the bar's icons, the wallpaper,
the lock screen and the boot menu. See [Themes and worlds](themes-and-worlds.md).

## VECTOR

The desktop's AI assistant. He talks, runs your tools and makes images and holograms. In
the story he is the caretaker of a distant spaceport, talking to you over a radio line.
See [VECTOR](vector.md).

## The Wick

The default theme: phosphor green on black, with the [den](#den) as its background. In the
story the Wick is a relay station at the edge of the Drift.

## Workspace

A separate screenful of windows. There are ten. See
[Windows and workspaces](windows.md).

## World

A theme with its own living scene instead of a still wallpaper. Everything that moves in
it shows something real: your coding agents, your network, your homelab. bromigOS has two
worlds, Mire and Tidewell. See [The worlds](themes-and-worlds.md#the-worlds).
