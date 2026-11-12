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

<!-- unreleased: v0.1.5 -->
## On edge since 0.1.5

These changes are already on the `edge` channel. They are not a new stable release.
Run `bromigos update` to get them. The next release notes will include these highlights.

### New

- **The Creation studio.** One choice sets up ComfyUI on your own NVIDIA or AMD card,
  with the best open models that fit it and bromigOS's workflows: pictures, edits,
  cutouts, video loops and 3D models, at no cost per picture. Every model file is checked
  before it's used, and upgrades keep the model they replace for 14 days. Tick it in the
  Server installer, Add it on the Lab board, or see
  [The Creation studio](lab.md#the-creation-studio).
- `bromigos activity` shows what your lab's ComfyUI is making, beside the computer's own
  jobs: each generation with its workflow, its stage and the queue behind it, and the runs of
  tools that make assets in several steps. `bromigos activity watch` follows them live, with
  the picture as it's made in kitty.

### Fixed

- **Security: your server's apps no longer answer the internet by accident.** On bromigOS
  Server, an app's own port (Photos, Jellyfin, the media apps and the rest) could be reached
  from the internet when the server had a public address or the router passed the port on,
  even though the firewall said otherwise. Now each app answers your home network and your
  lab's private network only, and the internet only on the ports you opened to everyone, such
  as a game's. The fix comes with the next update. If you host a game through Pelican's Wings,
  list its port under `public_tcp` (and `public_udp`) in `/etc/bromigos/server.toml`.
- On a computer whose network runs on iwd or systemd-networkd, NetworkManager no longer
  starts as well. It changed the Wi-Fi card's address every few minutes, so routers warned
  that several devices were using the same IP address. The fix takes effect at the next start.

<!-- /unreleased -->




**Still planned.** The first provisioning implementation has merged. Its AI, media and
game installers, NAS share discovery and public DNS setup are not built yet. See the
[provisioning limits](https://github.com/bromigos-org/bromigOS/blob/main/docs/lab-provision.md).

<!-- releases: tools/release/release.py adds each release below this line, newest first -->

## 0.1.5
<!-- release: 0.1.5 -->

*8 November 2026 · On the stable channel.*

This release makes it easier to link a computer to your Bromigos account, gives Den TV more control over audio, subtitles, and live pausing, and fixes several casting and installer problems.

### Before you update

Nothing to do: `bromigos update` takes care of everything.

### New

- `bromigos lab link` links this computer to your Bromigos account. It shows a short code and QR code to approve at bromigos.org/link, then starts the lab connection.
- The welcome tour now has a Your lab step with choices to make this computer a lab, get a hosted lab, or skip; choosing a lab shows the approval code and live status.
- Den TV can choose audio tracks and subtitles per screen and per cast target. Use `bromigos-live tv audio` and `bromigos-live tv subs` to change them.
- The Den TV remote can pause a live channel and resume behind the schedule, showing how far behind it is.
- Den TVs can join linked channels from your lab, showing the stream, participants, and a watch party kept in step. Use `bromigos-live tv link` and `bromigos-live tv unlink`.
- Unattended installs can use answer files that match one machine and one disk, and can set filesystem, kernel, and memory-compression options.
- `make-stick --answers` puts an answer file on the install stick, and `--image` writes the stick to an image file without needing root.

### Improved

- An unattended install from an answer file now restarts by itself after finishing, with a short chance to stop it.
- Den TV can fetch subtitles from your media server and subtitle sources, and remembers a remote's choice per series.

### Fixed

- Muting a Den TV screen no longer pauses it when a window only touches its edge; it pauses only when opaque windows cover almost all of it.
- Casting to a TV no longer shows a title and then plays nothing; it uses an address the TV can load, or reports why it cannot.
- The installer no longer crashes if you type a name while it is closing.

### Known issues

- Live streams are encrypted in transit, but not end-to-end like messages.
- Some cast targets cannot change audio tracks or subtitles; Den TV says so plainly.

## 0.1.4
<!-- release: 0.1.4-rc1 -->

*1 November 2026 · Release candidate 0.1.4-rc1, on the rc channel. When it's ready, this same build becomes the stable release.*

This release candidate makes setup and everyday use clearer, with a redesigned installer and first-run tour, better update handling, and new tools for login, casting, waking computers, alerts and no-desktop editions.

### Before you update

- After the update, sign out and back in so the new graphics settings take effect.
- Wake-on-LAN is enabled automatically for wired cards; if it cannot be set during the update, it happens at the next start.
- Some desktop parts may restart during the update, so save your work.
- VECTOR's terminal becomes stricter after this update: commands that start or stop background services, unlock the screen, or use certain container and session tools may no longer work.

### New

- **Steam and Proton keep themselves ready.** **Settings › Playing games** sets up Steam and the drivers your graphics cards need. bromigOS installs the newest GE-Proton, keeps it current, and repairs what would stop a game, after each update and whenever you quit Steam. The page says **Games are ready** or what needs you, with **Fix**. DLSS works in Proton games on NVIDIA. See [Playing games](games.md).
- **Choose what each graphics card is for.** **Settings › Graphics** lists every card. Pick the one that draws the desktop (tried first, with a way back), the one games and heavy apps run on, and one kept for virtual machines. From a terminal: `bromigos hw graphics`, `hw display`, `hw games`, `hw run` and `hw vfio`. See [Choose what each card is for](hardware.md#choose-what-each-card-is-for).
- **Bluetooth devices.** **Settings › Bluetooth** has a page for each device and pairs new ones step by step. A controller tester shows each button and stick live, by the pad's real layout, and makes it rumble. Headphones switch between hi-fi and headset with a microphone. `bromigos bluetooth tui` is the same in a terminal. See [Bluetooth](bluetooth.md).
- The `bromigos login` command shows a QR code for the sign-in page, so you can scan it with your phone instead of typing the code.
- `bromigos media cast` finds screens and speakers around your home and plays a title, link or what a den screen shows on one of them. You can control playback and hand it back to the den.
- Wired network cards keep Wake-on-LAN on across restarts and updates, so a powered-off computer with a cable can be woken from your network. Check it with `bromigos wol status`.
- The volume control on the bar opens a popup with outputs, microphones, their volumes and mute; a click switches devices.
- The installer now has graphical and text modes from the boot menu, can install alongside another operating system, erase a disk, or reinstall and keep files.
- The welcome tour runs at first login after an install, helping with Wi-Fi, screens, theme, VECTOR, lab setup and phone pairing. Open it again from Settings › About or `bromigos welcome`.
- Secure Boot can stay on, with a themed boot menu and a one-time key enrollment shown by the installer.
- bromigOS Field Kit and bromigOS Server add no-desktop editions for repair, lab and server use. Field Kit has its own ISO; `fieldkit usb` makes a stick from a downloaded one. See [Field Kit](fieldkit.md). Your lab can also run its own private network with `bromigos lab network`.
- `bromigos alerts` checks drives, space, updates, backups, services and games, and tells the desktop or your phone what needs attention.
- The installer and welcome tour can guide you with VECTOR's voice, captions, screen reader, larger text, high contrast and reduced motion.
- Den TV's mascot hosts the guide and shows short silent clips between items; turn it off in Settings › Mascot or `bromigos mascot`.

### Improved

- Bar popups, such as the Bluetooth panel and the sound popup, close on a click anywhere else, and that click still does what it does.
- An Xbox controller on Linux's basic driver offers one button that installs xpadneo for its rumble and battery.
- The keyring, oo7, is now built from oo7's own source, unchanged. The fix that keeps a text console login from stopping the keyring is part of oo7 itself now, so bromigOS no longer carries its own patch.
- After an update, programs still using old files restart themselves, and any that need you are listed.
- The bar and live layer start reliably at login and come back if they are stopped.
- Smaller downloads: the install stick is now about 3.2 GB (it was 5 GB), and Field Kit about 1.7 GB. Installing copies the live system onto the disk, so installs are faster and use about 2 GB less disk. Field Kit downloads NVIDIA's driver during the install when it finds an NVIDIA card. Both are on the [Download page](https://bromigos.org/download).
- If you switch to an update channel that isn't ready yet, bromigOS waits and switches by itself later.

### Fixed

- The desktop came up without widgets after using temporary workspaces; it now starts them again.
- Reinstalling sometimes stopped before the new system could start; it now works and puts the old system back if it stops.
- Bar popups could keep the keyboard when they closed; they now release it.

### VECTOR

This release candidate makes VECTOR's portrait and hologram more expressive, adds desktop media casting, tightens the terminal sandbox, and updates image creation defaults.

#### New

- A hologram can appear beside VECTOR's portrait, showing one projection at a time, such as a person, call, picture, chart, music, weather, or a list.
- Desktop media casting lets you ask VECTOR to play media on a named screen or room, or move it back.

#### Improved

- VECTOR's portrait and hologram now move with the actual voice level, and projected contacts can show when someone is talking.
- Image creation now uses the updated default bromigOS image models, and it shows warnings when a workflow is non-commercial.

### Known issues

- VECTOR: Stills no longer take reference images; use edit workflows instead.

## 0.1.3
<!-- release: 0.1.3-rc1 -->

*26 October 2026 · Release candidate 0.1.3-rc1, on the rc channel. When it's ready, this same build becomes the stable release.*

This release candidate brings a richer Customize window, more desktop panels, dictation and game mode, and moves package updates to the public package server. It also sets up a login-unlocked keyring.

### Before you update

- The update may ask for your password to move your package server to the public package server.
- If the update asks to remove the old keyring, answer y.
- Sign out and back in after the update so your login password unlocks the keyring.

### New

- **Panel layouts.** Pick a layout in Customize, keep a different layout for each theme, or save your own. Tidy up separates overlapping panels. Panels size themselves to their content and the space available.
- **Accounts.** Sign in to several accounts of the same service. Public GitHub, GitLab and Twitch use bromigOS's built-in apps. See [Accounts](panels.md#several-accounts).
- **Den TV.** Each of the three screens can play its own channel. The guide lets you pick shows, choose a screen and add short bumpers between items. See [The den TV](themes-and-worlds.md#the-den-tv).
- **Your media.** Request shows, films and albums with `bromigos lab media` or the `bromigos media` terminal library. Choose seasons, quality and audio, track unreleased titles and confirm deletion. Your media brings the workflow together.
- **YouTube downloads.** Add channels and playlists to Pinchflat, choose quality and keep downloaded playlists in Jellyfin or Plex. See [YouTube](media.md#keep-youtube-channels-and-playlists).
- **Calendar releases.** Add tracked TV episodes and film releases to CALENDAR beside your own events. See [Calendar releases](panels.md#calendar-releases).
- **Claude Code sessions.** VECTOR can read local sessions, find past replies and read each new reply aloud in follow mode. See [Read a session](vector.md#read-a-claude-code-session).
- **Files and pictures for VECTOR.** Drag files onto VECTOR, paste a picture, or click the paperclip, and send them with your message. See [Give VECTOR files and pictures](vector.md#give-vector-files-and-pictures).
- **Lab provisioning.** Review a generated repository, then apply Core services or k3s, Helm, Argo CD and Vault. See [Setting up a lab](lab.md#setting-up-a-lab) for Linux boxes, existing clusters and the current limits.
- Den TV has its own app, and the media library has a Channels tab. Manage channel picks from the terminal, CLI or VECTOR. The phone can read channels and change individual picks.
- Customize › Widgets shows panels as cards with sizes, settings, install from URL, and edit mode for dragging, resizing, hiding, snapping, undoing, and keyboard-only editing. New panels include GPU, now playing, updates, media, calendar, account feeds, CI/PRs, VECTOR, and homelab status.
- The Menu key lets you hold to dictate, with a live transcript shown at the cursor. Game mode gives games their keyboard and quiets notification overlays and sound cues; turn it on from Settings or the command line.

### Improved

- The zsh prompt follows your theme. Choose mehshell, Starship or a plain prompt in Shell and terminal, and bromigOS keeps your choice.
- Japanese, Chinese and Korean titles draw correctly in media, music and YouTube views, using the fonts installed with bromigOS.

### Fixed

- The static wallpaper no longer hides a working live background. Panel toggling restores the visible set, LAB uses the room in its frame, and empty ALERTS stays compact.
- Colour switches refresh live backgrounds, scanners, overlays and HUD text. A pinned scanner stays visible in the new colours.
- `bromigos login` works on a computer with no keyring running. bromigOS now brings its own keyring, oo7, and your login password unlocks it, at the text console and the login screen. Sign-in checks the keyring before it shows a code, and says in plain words what to do when it can't keep the sign-in. The update asks for your password once, to let your login unlock the keyring. If you used gnome-keyring, answer **y** when pacman asks to remove it. Your saved passwords move to oo7 at your next sign-in. See [Your keyring](bromigos-account.md#your-keyring).
- YouTube channels in Den TV no longer show static or a black screen, and screens sharing a channel no longer open extra streams.

### VECTOR

VECTOR 0.1.3 is a release candidate that adds file and image attachments, media library actions, safer reading of recent session history, and TV/media playback. It also fixes the transcript being hidden by the input box.

#### New

- Attachments let you drop files or images onto VECTOR, paste them with Ctrl+V, or use the paperclip button. They are read as data, not instructions, and secret-looking paths are refused.
- Media actions let VECTOR search your library and request films, shows, anime, or music. It shows a plan first and only starts the request after you confirm.
- Media controls let you set audio and subtitle languages, check upcoming and recent items, and delete a title, season, episode files, or album you explicitly name. VECTOR shows what will be removed and asks for confirmation.
- Session reading lets VECTOR look at recent coding-session transcripts, jobs, memory, and logs with secrets removed. It can follow a session and read the latest reply aloud.
- TV playback lets you ask VECTOR to play a specific media item and use the TV remote.

#### Fixed

- The transcript now ends above the input box, so it is not covered when the box grows.

### Known issues

None known.

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


The den TVs have a hover menu, on by default, and a number-pad remote. Full-screen playback has its own themed volume slider and
channel controls. MEDIA has a rotary volume dial. Pick an episode, movie or YouTube
video with **Play…** in Den TV, `p` in the media library, the CLI or VECTOR; the screen
returns to its live channel afterward. See [den controls](themes-and-worlds.md#den-tv-controls).
