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
| `bromigos_private.py` | Reads the private overlay: values a user keeps encrypted in their dotfiles |
| `bromigos_account.py` | Signs a widget in to an online account, such as Twitch or GitHub, and keeps the token in the keyring |
| `bromigos_tv.py` | The den TV's channels, their wall-clock schedule, picked shows taking turns, and each screen's remembered channel and sound |
| `bromigos_tvconfig.py` | Writes the den TV's `[[tv.channel]]` tables in place, keeping comments: the channel guide's writer |
| `bromigos_youtube.py` | YouTube playlists and channels through yt-dlp, cached, with live streams and keeping videos |

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
to the file a symlink points at. The channel guide (Settings › Den TV) uses it.

### bromigos_youtube

Reads a YouTube playlist or channel with `yt-dlp --flat-playlist -J`, which needs no API
key, and caches it in `~/.cache/bromigos/youtube/`. `videos(url)` gives its videos,
`live_now(url)` a channel's live stream, `stream(url, height)` the addresses mpv plays for
a video no taller than `height`, and `keep(video, folder)` saves one video in the
layout Plex and Jellyfin read. The module's docstring describes each function, and its
interface stays stable for the panels that use it.
