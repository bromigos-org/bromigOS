# lib/

This folder holds Python libraries that several parts of bromigOS share, so each rule
lives in one place. The live layer, the desktop panels (widgets), the desktop's tools,
VECTOR and plugins all import them.

`bromigos-core` installs them in `/usr/lib/bromigos/lib/`. Other packages add their own
modules to the same folder:

- `bromigos-desktop` adds the desktop's helpers from `desktop/lib/`, such as
  `bromigos_hypr.py` and the shortcut picker's `bromigos_keys.py`.
- `bromigos-homelab` adds the `bromigos_homelab` package.

## The modules

| Module | What it does |
|---|---|
| `bromigos_theme.py` | Reads the colours of the theme in force |
| `bromigos_monitors.py` | Picks the monitor that bromigOS's own surfaces go on |
| `bromigos_retint.py` | Recolours the den's painted wallpaper for a colour theme |
| `bromigos_emblem.py` | Draws the emblem, called the burn-in, to its canonical spec |
| `emblem_braille.py` | Draws the emblem as coloured braille for the terminal banner |
| `bromigos_drift.py` | Field Kit's orb, emblem and disk map as rich Text for the installer's TUI, from `bromigos fieldkit shapes`; [the shapes](../docs/fieldkit.md#shapes-shared-with-the-installer) |
| `bromigos_private.py` | Reads the private overlay: values a user keeps encrypted in their dotfiles |
| `bromigos_account.py` | Signs a widget in to an online account, such as Twitch or GitHub, and keeps the token in the keyring |
| `bromigos_login.py` | Signs in to your Bromigos account, with a code, an SSH key or a token, and reads the account's SSH keys; [account reference](../docs/bromigos-account.md) |
| `bromigos_keyring.py` | Checks the keyring that keeps sign-ins (oo7), puts its errors in plain words, and adds the PAM lines that let the login unlock it; [the keyring](../docs/bromigos-account.md#the-keyring) |
| `bromigos_tv.py` | The den TV's channels, their wall-clock schedule, picked shows taking turns, and each screen's remembered channel and sound |
| `bromigos_tvchannels.py` | Shared channel operations and JSON CLI for the guide, media and VECTOR |
| `bromigos_tvconfig.py` | Writes the den TV's `[[tv.channel]]` tables in place, keeping comments: the channel guide's writer |
| `bromigos_tvplay.py`, `bromigos_tvremote.py` | Search and play on a den screen, its remote's actions, and their JSON command line |
| `bromigos_cast.py` | Casting: Chromecasts, DLNA TVs, AirPlay, Jellyfin's apps and the den's screens as one list of targets (`bromigos media cast`) |
| `bromigos_youtube.py` | YouTube playlists and channels through yt-dlp, cached, with live streams and keeping videos |
| `bromigos_storage*.py` | Local drive inventory, saved provisioning plans, verified migration, grouped capacity, Snapper/btrbk inventory and logged cache and retirement plans; [storage reference](../docs/storage.md) |
| `bromigos_console.py` | Reads and safely saves text console font presets for the next boot; [console reference](../docs/console.md) |
| `bromigos_power_menu.py` | Keyboard power selection and confirmation with a preview mode; [power menu reference](../docs/power-menu.md) |
| `bromigos_splash.py` | Saved Plymouth and GRUB splash settings, with backups and rollback; [splash reference](../docs/splash.md) |
| `bromigos_guide.py` | VECTOR's voice guide: the scripted lines of the installers and tours (`guide/lines.toml`), their clips (`guide/clips/`) and the player; [voice guide](../docs/voice-guide.md) |

### bromigos_account

Widgets that read an online account sign in through this module: the device flow (Twitch,
GitHub, GitLab), the authorization code with PKCE on a loopback port (Spotify), or Plex's
PIN, a code you enter at plex.tv/link. `plex_claim_token()` gives a new Plex server the
claim token that adds it to your account. Tokens
go to the login keyring through libsecret, never to a file. Client IDs and server
addresses are in `~/.config/bromigos/accounts.toml`. A service can have several accounts,
such as gitlab.com and a company's own GitLab: the first is `default`, and each other one
has a name and its own table and keyring item. For GitHub's default account it uses the
`gh` login when there is one. `bromigos account` is its command line, and
[docs/plugins.md](../docs/plugins.md#a-widget-that-needs-an-account) shows a panel that
uses it.

Your Bromigos account is its provider `bromigos`, an OpenID Connect sign-in whose refresh
tokens rotate. `authed_json()` calls a service with an account's token and refreshes it
once after a 401. `bromigos_login.py` adds the SSH sign-in and the `bromigos login`,
`logout` and `whoami` commands. [docs/bromigos-account.md](../docs/bromigos-account.md)
explains both.

### bromigos_theme

`bromigos theme set` writes the theme, with every colour resolved, to
`~/.local/state/bromigos/theme/current/palette.json`. This module reads that file, and
reads it again when it changes. With no file, it returns the Wick's colours. It also maps
the Wick's old colour names onto the colour roles. [docs/theming.md](../docs/theming.md)
describes `palette.json`. `high_contrast()` tells a panel or deck whether high contrast
is on.

### bromigos_monitors

The live layer's background and the panels go on one monitor. This module chooses it, in
this order:

1. the monitor the surface's own setting names, if it's connected;
2. the primary monitor that `bromigos setup monitors` recorded in
   `~/.config/bromigos/monitors.toml`;
3. the focused monitor;
4. the first monitor Hyprland lists.

Nothing names a connector, so a setting from another machine falls through to this one's
monitors. When a monitor goes away, the surface picks again.
[docs/desktop.md](../docs/desktop.md) covers monitors.

### bromigos_retint

The den is the default theme's wallpaper, painted in phosphor green. A colour theme
recolours it with this module. Each pixel keeps its lightness exactly, so every detail
stays. Its hue comes from a ramp built from the theme's colours. The lock screen's copy
of the den is recoloured the same way.

### bromigos_emblem and emblem_braille

`bromigos_emblem.py` draws the burn-in from its canonical spec in `theme/emblem/`. It also
builds the emblem kits that `bromigos emblem build` writes into each theme.
`emblem_braille.py` turns an emblem into coloured braille characters for the shell
banner. Each kit's `emblem.braille` comes from it.

### bromigos_private

A user can keep private values, such as their own hosts, encrypted in their dotfiles with
sops and age. At login, `bromigos-private.service` runs `bromigos private decrypt`, which
decrypts them to `~/.config/bromigos/private/config.json`. `bromigos-private.path` runs it
again whenever the encrypted file changes. `bromigos-core` ships both user units, on for
every user. Without the encrypted file or the age key they do nothing. This module reads
the decrypted file and never prints it. Without the file, every lookup returns the
default the caller passes, so the desktop still runs.

## Run from a checkout

The panels find this folder on their own, as `../lib` beside `widgets/`. For the live
layer, set `BROMIGOS_PYLIB` to this folder's path, or put it on `PYTHONPATH`.

### bromigos_tv

The den TV's channels ([live/README.md](../live/README.md#the-den-tv)). The live layer
plays them and the MEDIA panel shows them, so both read the schedule from here.
`lineup(cfg, screen)` lists a screen's channels, its own picture first.
`schedule_at(items, t, seed, order)` says what's on at time `t` and how far in.
`now_next(channel)` does the same from the channel's cached list, with no network.
A channel of picked shows (`shows`, `items`, `collections`) is matched to the server's ids
once (`resolve_picks`). In order, `rotation_at(groups, t, anchor)` has the shows take
turns, and `rotation_advance(channel)` keeps where each one is in the live layer's state.

### bromigos_tvconfig

Edits the `[[tv.channel]]` tables of the live layer's `config.toml` as text, a table at a
time, so comments, blank lines and other tables stay exactly as they were. `load()` gives
a `Doc` with `channels()`, `add(table)`, `remove(i)` and `restore(i, text)` for Undo,
`move(i, j)`, `set(i, key, value)` and `save()`. A save is checked first: the new file
must parse, and nothing but the channels may read differently. It's written in one step
to the file a symlink points at. The standalone Den TV guide uses it through `bromigos_tvchannels.Store`.

### bromigos_youtube

Reads a YouTube playlist or channel with `yt-dlp --flat-playlist -J`, which needs no API
key, and caches it in `~/.cache/bromigos/youtube/`. `videos(url)` gives its videos,
`live_now(url)` a channel's live stream, `stream(url, height)` the addresses mpv plays for
a video no taller than `height`, and `keep(video, folder)` saves one video in the
layout Plex and Jellyfin read. The module's docstring describes each function, and its
interface stays stable for the panels that use it.

### bromigos_tvchannels

`Store` reads channel summaries and contents, creates, renames, reorders and deletes
channels, adds/removes/reorders picks, changes order and bumpers, restores the last
deleted table, and tunes a screen. Names and one-based config positions identify channels.
Screen numbers remain the live player's own numbering. `Store.edit()` serializes guide
edits with CLI and TUI edits and uses the comment-preserving writer. Read operations use
cache only unless `refresh=True` is requested. `main()` provides the JSON CLI and its
exit codes. [Your media](../manual/src/media.md#make-channels-for-the-den-tv) has examples.

## Den TV controls

The den screens have a hover menu for channels, sound, volume, full screen and the guide.
The hover menu is on by default and uses `tv.hover_hint`.
`bromigos-live tv hint on|off` changes it.
The MEDIA widget has a rotary dial and per-screen sound controls. Full-screen playback
loads only the den's own `live/tvosc.lua`, with a private palette and IPC connection;
it leaves global mpv settings alone. The number-pad remote selects a screen with
Super+KP 1/2/3 and releases it with Super+KP 0, Escape or a fifteen-second timeout.

### bromigos_cast

`bromigos_cast.py` puts every screen something can be cast to in one list: Google Cast
devices (python-pychromecast), DLNA renderers (python-async-upnp-client), AirPlay
receivers (pyatv), the apps Jellyfin can steer, and the den's own screens. `targets()`
finds them in parallel and keeps their addresses in a private cache
(`~/.cache/bromigos/cast-targets.json`, 0600); `find()` takes an id or words from a name
or room; `play()`, `control()`, `status()` and `handback()` act on one. `bromigos media
cast`, VECTOR's tools and BRODEC's den remote all call it. Each protocol is optional, and
`protocols` in `targets()` says why one isn't there. It was tested against
pychromecast 14.0.10, async-upnp-client 0.40.0 and pyatv 0.18.0.

A target fetches the stream from the media server itself, with the server's key in the
address (`video_cast_url()` in the media server's adapter). That address goes only to the
target. Every play, control and hand back is a line in
`~/.local/state/bromigos/cast-audit.jsonl`, without addresses or keys.
`BROMIGOS_CAST_CALLER` names who asked (VECTOR sets `vector`). AirPlay video plays while its
sender stays connected, so a small helper process holds the connection until the video
ends or is stopped. The tests (`homelab/tests/test_cast.py`) use stand-ins for every
library and device.

`lib/bromigos_tvplay.py` shares media search and on-demand playback between the Den TV
app, media TUI, CLI and VECTOR. `lib/bromigos_tvremote.py` shares hint, selection and
remote commands. The media TUI uses `p` to play on a den screen and `P` for a profile.
