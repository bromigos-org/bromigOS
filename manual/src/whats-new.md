# What's new

This page lists what each release of bromigOS brings, newest first. Each release says
what's new, what works better, what's fixed, and anything to know before you update.

To read the newest release's notes on your computer, run:

```bash
bromigos whats-new
```

The notes come with bromigOS, so this works offline. `bromigos whats-new --all` shows
every release. After an update that brings a new release, `bromigos update` tells you so
on its last line.

A release candidate, with a version such as `0.1.2-rc1`, comes to the `rc` channel first.
When it's ready, the same build becomes the stable release, and its notes stay as they
are. To change the channel you follow, see [Channels](update-and-rollback.md#channels).

Developers can read every change in the repository's `CHANGELOG.md`.

<!-- unreleased: v0.1.2 -->
## On edge since 0.1.2

These changes are already on the `edge` channel. They are not a new stable release.
Run `bromigos update` to get them. The next release notes will include these highlights.

### New

- **Panel layouts.** Pick a layout in [Customize](themes-and-worlds.md#customize), keep a
  different layout for each theme, or save your own. [Tidy up](panels.md#tidy-up) separates
  overlapping panels. Panels size themselves to their content and the space available.
- **Accounts.** Sign in to several accounts of the same service. Public GitHub, GitLab
  and Twitch use bromigOS's built-in apps. See [Accounts](panels.md#several-accounts).
- **Den TV.** Each of the three screens can play its own channel. The guide lets you pick
  shows, choose a screen and add short bumpers between items. See
  [The den TV](themes-and-worlds.md#the-den-tv).
- **Your media.** Request shows, films and albums with `bromigos lab media` or the
  `bromigos media` terminal library. Choose seasons, quality and audio, track unreleased
  titles and confirm deletion. [Your media](media.md) brings the workflow together.
- **YouTube downloads.** Add channels and playlists to Pinchflat, choose quality and keep
  downloaded playlists in Jellyfin or Plex. See [YouTube](media.md#keep-youtube-channels-and-playlists).
- **Calendar releases.** Add tracked TV episodes and film releases to CALENDAR beside
  your own events. See [Calendar releases](panels.md#calendar-releases).
- **Claude Code sessions.** VECTOR can read local sessions, find past replies and read
  each new reply aloud in follow mode. See [Read a session](vector.md#read-a-claude-code-session).

- **Lab provisioning.** Review a generated repository, then apply Core services or k3s,
  Helm, Argo CD and Vault. See [Setting up a lab](lab.md#setting-up-a-lab) for Linux boxes,
  existing clusters and the current limits.

- Den TV has its own app, and the media library has a Channels tab. Manage channel picks
  from the terminal, CLI or VECTOR. The phone can read channels and change individual picks.

### Improved

- The zsh prompt follows your theme. Choose mehshell, Starship or a plain prompt in
  [Shell and terminal](shell.md), and bromigOS keeps your choice.
- Japanese, Chinese and Korean titles draw correctly in media, music and YouTube views,
  using the fonts installed with bromigOS.

### Fixed

- The static wallpaper no longer hides a working live background. Panel toggling restores
  the visible set, LAB uses the room in its frame, and empty ALERTS stays compact.
- Colour switches refresh live backgrounds, scanners, overlays and HUD text. A pinned
  scanner stays visible in the new colours.
<!-- /unreleased -->

**Still planned.** The first provisioning implementation has merged. Its AI, media and
game installers, NAS share discovery and public DNS setup are not built yet. See the
[provisioning limits](https://github.com/bromigos-org/bromigOS/blob/main/docs/lab-provision.md).

<!-- releases: tools/release/release.py adds each release below this line, newest first -->

## 0.1.2
<!-- release: 0.1.2-rc2 -->

*9 October 2026 · Release candidate 0.1.2-rc2, on the rc channel. When it's ready, this same build becomes the stable release.*

This release candidate brings a new Settings window, idle and lock controls, shortcut rebinding, accessibility options, hardware and peripheral setup, a themed boot menu, homelab tools, AUR package updates, and an emergency switch for VECTOR.

### Before you update

- The update may ask for your password in the terminal to set up the boot theme, paru (the AUR helper), and the boot menu names.
- Your idle and lock policy is moved to a bromigOS-managed setup; your own listeners are kept, and the idle service is restarted.
- A new background lab model check is installed. It only runs when a homelab is configured, and you can turn it off with `systemctl --user disable --now bromigos-lab-models.timer`.
- If your machine uses the GRUB boot menu, entries are renamed to “bromigOS Linux”; `bromigos boot theme off` removes the themed boot menu and the name.
- If the update changes the graphics driver or kernel, it will hold the live desktop and VECTOR back and ask you to restart.
- VECTOR no longer switches off automatically when the guard sees changes; use `bromigos vector off` or `bromigos vector on` to control him.

### New

- The new Settings window opens with SUPER+, or SETUP > Settings…. It gathers most desktop settings, from idle and shortcuts to displays, network, Bluetooth, power, keyboard, notifications, default apps, startup, widgets, live layer, peripherals, extensions, VECTOR, account, about, and updates.
- Idle and lock settings are now controlled by `bromigos idle` and the Idle & lock page; the bar shows an idle eye, and you can stay awake for an hour or until stopped.
- Shortcuts can be rebound by pressing the new keys: open SETUP > Shortcuts… or `bromigos keys`, choose a command, then press the shortcut.
- Reduced motion and high contrast are available from `bromigos accessibility`, SETUP > Accessibility, and the menu; they change animations, borders, panels, and the live desktop.
- Hardware and peripheral setup: `bromigos hw` installs the right graphics and power packages; laptops get battery and power-profile controls in the bar, tap to click, and a three-finger workspace swipe. Supported keyboards can have their dial, side buttons, and lighting managed from SETUP > Peripherals.
- The boot menu can wear the bromigOS theme, and installed systems appear as “bromigOS Linux” instead of the generic name.
- A homelab console is available with `bromigos lab`, the Lab deck at SUPER+SHIFT+H, and Settings > Lab; it can check GPUs, models, jobs, and doctor findings.
- AUR support is built in: `bromigos update` can update AUR packages inside the same rollback snapshot, and `bromigos aur` turns it on or off.
- The release notes are available offline with `bromigos whats-new`, and the first update after a new release tells you to read them.

### Improved

- The theme switcher shows each theme as a real desktop preview, sized to your monitor, and Settings > Theme lets you wear a theme from its preview.
- Every bromigOS window now appears in the app launcher, and the menu lists each one once with its icon.
- Settings and About open the manual installed on your machine, so help works offline.
- When you choose Super as the window key, conflicting desktop shortcuts move to Alt instead of doing two things at once.
- On machines using software rendering, the live desktop holds a still frame and says so once, instead of using a lot of CPU.
- `bromigos lab` moves with the arrow keys and Vim's keys: j and k through cards and rows, h and l between panes, [ and ] between tabs.

### Fixed

- The live desktop no longer leaves extra copies running, and its background loads correctly at more screen sizes.
- Menu titles appear above the search box again. Alt+Esc suspends without asking for a password.
- Booting from a snapshot and running `bromigos update --rollback` no longer says there are no snapshots.
- Updating from an older release no longer stops while redrawing the theme.
- The Drift map finds its lore on every machine.

### VECTOR

This release gives you a manual emergency switch, adds VECTOR and the hologram gallery to the app launcher, and makes the holograms follow motion settings and show worlds' colours. It also fixes startup, voice cycling, and stopping VECTOR.

#### New

- The emergency switch lets you turn VECTOR off and on from `bromigos vector off` or `bromigos vector on`, `SUPER+CTRL+ESCAPE`, the bar, or Settings. The guard now only records changes and no longer switches VECTOR off by itself.
- VECTOR can propose changes himself. He works in his own copies of the bromigOS repositories, opens pull requests and merges them when the checks pass. Changes to the code behind his limits (real money, your keys, his emergency switch) wait for you.
- Plugins can now give VECTOR tools, decks, data feeds and real-money rules of your own.
- VECTOR and the hologram gallery appear in the app launcher with their icons.
- The hologram gallery (`Super+O`) shows worlds' holograms shelf by shelf, each in its world's colours.
- The holograms follow the motion setting in bromigOS accessibility settings: full, reduced, or still. Reduced slows movement and removes flicker, blinking, scan bands, and glitches; still holds one frame until the picture changes.

#### Improved

- VECTOR's homelab creation uses the lab's current models for cutouts and 3D, and can upscale an image or a short clip.

#### Fixed

- VECTOR starts without an error, and changing voices now takes effect immediately, so the keyboard dial steps through every voice.
- `bromigos-holo stop` and `bromigos-holo restart` now stop VECTOR promptly.

### Known issues

- The online manual may not match your installed channel; the manual opened from Settings matches your packages.

