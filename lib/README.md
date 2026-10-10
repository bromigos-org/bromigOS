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

### bromigos_account

Widgets that read an online account sign in through this module: the device flow (Twitch,
GitHub, GitLab), or the authorization code with PKCE on a loopback port (Spotify). Tokens
go to the login keyring through libsecret, never to a file. Client IDs are the user's
own, in `~/.config/bromigos/accounts.toml`. For GitHub it uses the `gh` login when there
is one. `bromigos account` is its command line, and
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
