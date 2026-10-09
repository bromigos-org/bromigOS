# The app bundle

`bromigos-apps` is an optional set of desktop apps with bromigOS's own configs. Where the
theme reaches an app, the app changes colour with the rest of the desktop.

This page is for someone changing the bundle's configs. For using the apps, read the
manual's [Apps](../manual/src/apps.md) page.

To install it:

```bash
bromigos install --with bromigos-apps
```

`sudo pacman -S bromigos-apps` works too. The `bromigos` meta-package lists it as an
option.

## What's in it

| App | Package | bromigOS's config | How it takes the theme |
|---|---|---|---|
| Neovim | `neovim` | LazyVim, with the `bromigos` colour scheme | Re-applies the theme on a switch, without a restart |
| tmux | `tmux` | Sensible defaults, status bar on top | A running server re-reads the theme |
| btop | `btop` | `color_theme = "bromigos"` | A theme file linked into btop's themes folder |
| lazygit | `lazygit` | ASCII interface, no update checks | Uses the terminal's colours |
| mise | `mise` | An empty `[tools]` to fill in | No colours |
| Chromium | `chromium` | Wayland flags | The window frame's colour, while it runs |
| Spotify | `spotify-launcher` | Its own | Its own |
| Signal | `signal-desktop` | Its own | Its own |
| 1Password | `1password` | Its own | Its own |

1Password is optional. bromigOS builds it into its own repository.

The theme reaches these apps through `bromigos theme set`:

- Neovim gets `nvim.lua`.
- tmux gets `tmux.conf`. The `apps` theme-set hook makes a running server read it.
- btop gets `btop.theme`, linked into `~/.config/btop/themes/` by the `apps` hook.
- Chromium gets its frame colour through `--set-theme-color`.

See [theming.md](theming.md) for the templates and hooks.

## The defaults and your files

The configs are read-only defaults in `/usr/share/bromigos/default/apps/`, replaced by each
update. Your side lives in `~/.config`.

`bromigos apps setup` puts your side in place once, and only where you have nothing yet. A
file that exists is yours, and it's never replaced. A migration runs `bromigos apps setup`
when the package is installed. If you install the package later, run it yourself.
`bromigos apps setup --check` says what it would do without doing it.

| Your file | Kind | What it starts as |
|---|---|---|
| `~/.config/nvim/init.lua` | thin | Loads the defaults. Add your options below the `dofile` line. |
| `~/.config/tmux/tmux.conf` | thin | Sources the defaults, then yours. |
| `~/.config/lazygit/config.yml` | copy | A copy of the defaults, yours from then on. |
| `~/.config/mise/config.toml` | copy | The same. |
| `~/.config/chromium-flags.conf` | copy | The same. |

A thin file loads the defaults, so you get their updates. lazygit, mise and Chromium can't
include another file, so you get a one-time copy instead.

## Neovim

The defaults are LazyVim's starter config (see [lazyvim.org](https://www.lazyvim.org)).
The first time Neovim starts, lazy.nvim installs itself into `~/.local/share/nvim/lazy`,
then installs LazyVim's plugins.

bromigOS adds `colors/bromigos.lua`. `:colorscheme bromigos` applies the current theme's
`nvim.lua` and checks it every two seconds. So `bromigos theme set` recolours Neovim within
two seconds. `<leader>ut` re-applies the theme by hand.

Icons are ASCII, through `mini.icons`. The desktop's font, Geist Mono, isn't a Nerd Font,
so icon glyphs wouldn't line up.

Your own LazyVim config sits beside the defaults, the LazyVim way:

- plugin specs in `~/.config/nvim/lua/plugins/*.lua`, which lazy.nvim loads beside
  bromigOS's;
- options and keymaps in `init.lua`, after the `dofile` line.

To take over the whole config, replace `init.lua` with your own. Nothing else of yours is
touched.

## 1Password

bromigOS builds 1Password into its repository from 1Password's official Linux tarball,
pinned by checksum. The tarball's upstream signature was checked when the version was
pinned.

The package doesn't make the PolicyKit policy for unlocking with your system password,
because that policy would be filled with the build machine's users. To unlock 1Password
that way, run this once:

```bash
sudo /opt/1Password/install_biometrics_policy.sh
```
