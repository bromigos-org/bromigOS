# What gets installed

bromigOS is a set of packages. You install one, `bromigos`, and it brings in the rest.
This page lists them all, so you can see what each part is and add the optional ones.

To add an optional package, run `bromigos install --with` and its name. For example, to add
the [app bundle](apps.md):

```bash
bromigos install --with bromigos-apps
```

<!-- generated:packages (tools/docs/generate.py; don't edit by hand) -->

| Package | What it is | Installed |
|---|---|---|
| `bromigos` | bromigOS: holograms, homelab integrations, living themes and widgets on Arch and Hyprland | the one to install: everything below marked *with bromigOS* |
| `bromigos-keyring` | bromigOS package-signing key for pacman | *with bromigOS* |
| `bromigos-core` | bromigos: one command for the bromigOS desktop | *with bromigOS* |
| `bromigos-desktop` | bromigOS desktop: default configs for Hyprland, waybar, rofi, dunst, gtklock and hypridle, and their tools | *with bromigOS* |
| `bromigos-settings` | bromigOS system settings: the login screen, the boot splash and menu, the GTK, icon and cursor themes, the fonts | *with bromigOS* |
| `bromigos-live` | bromigOS live layer: the animated, data-reactive background, its worlds and decks | *with bromigOS* |
| `bromigos-widgets` | bromigOS desktop widgets: system, network, storage, workbench, notes and shortcuts panels | *with bromigOS* |
| `bromigos-vector` | VECTOR, the desktop's caretaker, and the hologram renderer he lives in (from the `vector` repository) | *with bromigOS* |
| `bromigos-manual` | bromigOS manual: how to use the desktop, as HTML, for reading offline | *with bromigOS* |
| `bromigos-homelab` | bromigOS homelab integrations: capabilities, adapters, the LAB panel, homelab decks and VECTOR tools | *with bromigOS* (through `bromigos-desktop`) |
| `ttf-geist-mono` | Geist Mono, a monospaced typeface by Vercel | *with bromigOS* (through `bromigos-settings`) |
| `bromigos-lab-catalog` | bromigOS lab model catalog: the best open models per AI capability and GPU size, with licences | *with bromigOS* (through `bromigos-homelab`) |
| `bromigos-apps` | bromigOS app bundle: LazyVim, tmux, lazygit, mise, Chromium, Spotify and Signal, configured and themed | optional: `bromigos install --with bromigos-apps` |
| `herdr` | Terminal workspace manager for AI coding agents | optional: `bromigos install --with herdr` |
| `paru` | Feature packed AUR helper | by `bromigos install` (its `aur` step), unless `--no-aur` or `bromigos setup aur` leaves it out |
| `1password` | Password manager and secure wallet | optional, for `bromigos-apps` |
| `mehshell` | Fast parallel zsh prompt engine for bromigOS | on its own |

`herdr`, `ttf-geist-mono`, `1password` and `paru` aren't in Arch's own repositories, so bromigOS packages them into its own, each pinned by checksum. Only `1password` needs the AUR, and only on a public install (below).

- `herdr` and `paru` are built from their upstream source.
- `ttf-geist-mono` packages the fonts from Geist's release.
- `1password` repackages 1Password's own Linux download. It isn't built from source. Its licence is proprietary, so the public mirror leaves it out: there, `bromigos install --with 1password` gets it from the AUR with paru.

<!-- /generated:packages -->

## Where your own files go

Updates replace the packages' files, not yours. The full list of folders is on
[Files and folders](files.md).
