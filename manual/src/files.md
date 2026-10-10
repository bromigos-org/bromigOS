# Files and folders

bromigOS keeps three kinds of files apart: its own defaults, your settings, and files it
makes for you. Updates replace bromigOS's defaults. They don't overwrite your settings. Now
and then an update moves or adjusts one of your files so it keeps working, and keeps a
copy of the old one.

## The three homes

| Folder | What's in it | Who changes it |
|---|---|---|
| `/usr/share/bromigos/` and `/usr/lib/bromigos/` | bromigOS's defaults, themes, tools and libraries. | Updates. Don't edit these. |
| `~/.config/bromigos/`, plus short files in `~/.config/hypr/`, `~/.config/waybar/` and friends | Your settings. | You, Settings, and `bromigos setup`. |
| `~/.local/state/bromigos/` | Files bromigOS makes: the current theme's colours, logs, the record of updates. | bromigOS. |

Your files in `~/.config/hypr/`, `~/.config/waybar/` and the rest are short. Each one loads
bromigOS's defaults first, then adds yours. So an update can improve the defaults without
undoing your changes.

## Your settings

All in `~/.config/bromigos/`:

| File or folder | What it holds | Changed by |
|---|---|---|
| `accessibility.toml` | Motion and contrast. | [Accessibility](accessibility.md) |
| `shell.toml` | Your prompt choice. | [Shell and terminal](shell.md) |
| `aur.toml` | Whether bromigOS uses the AUR. | `bromigos aur` |
| `idle.toml` | When the screensaver, the lock and sleep happen. | [Idle and lock](idle.md) |
| `targets.toml` | Where AI work runs. | [Creating with AI](where-ai-runs.md) |
| `create.toml` | The tools that make pictures and 3D models. | `bromigos setup create` |
| `homelab.toml` | Your homelab's services. | [Your homelab](homelab.md) |
| `peripherals.toml` | Your keyboard's extra keys and lighting. | [Keyboards and peripherals](peripherals.md) |
| `keys.toml` | Your own shortcuts. | [Your own shortcuts](shortcuts.md) |
| `monitors.toml` | Your primary monitor. | **Settings › Displays** |
| `input.toml` | The keyboard layout, key repeat, the mouse and the touchpad. | **Settings › Keyboard & input** |
| `profile.toml` | Who you are, and what VECTOR calls you. | **Settings › Account** |
| `webapps.toml` | Your web apps. | [Web apps](webapps.md) |
| `weather.toml` | The weather panel's place. | [Panels](panels.md#set-up-the-weather) |
| `widgets/layout.json` | Where the panels sit. | [Panels](panels.md) |
| `windows.toml` | Which floating windows go back where you left them. | [Windows and workspaces](windows.md) |
| `startpage.toml` | The browser start page's links. | [Apps](apps.md#a-start-page-for-your-browser) |
| `vector/` | VECTOR's brain, voices and holograms. | [VECTOR](vector.md) |
| `themes/` | Themes of your own. | [Themes and worlds](themes-and-worlds.md) |
| `plugins/` | Panels, Settings pages and VECTOR tools of your own. | You |
| `live/overrides.toml` | The background's animation switches. | `bromigos anim` |

Your Hyprland settings, including your monitors and your own keys, are in
`~/.config/hypr/hyprland.lua`. `bromigos setup config` opens it, and your other config
files, in your editor.

## Files bromigOS makes for you

| File or folder | What it is |
|---|---|
| `~/.local/state/bromigos/install.log` | Everything the installer did. |
| `~/.local/state/bromigos/vector-shell.log` | Every command VECTOR ran in his terminal, every one he refused, and every flip of his emergency switch. |
| `~/.local/state/bromigos/vector-guard.log` | Every change to VECTOR's safety code and settings. `bromigos vector guard log` reads it. |
| `~/.local/state/bromigos/theme/` | The theme you chose, drawn for every app. |
| `~/.local/state/bromigos-live/live.log` | The animated background's log. |
| `~/.local/state/bromigos/ext/ledger.json` | The extensions you installed. |
| `~/.local/share/bromigos/notes.md` | Your field notes. |
| `~/.local/share/bromigos/startpage/` | The browser start page. |
| `~/.local/share/bromigos/ext/` | Your extensions' files. |
| `~/Pictures/screenshots/` | Your screenshots. |
| `~/Videos/recordings/` | Your screen recordings. |
| `~/Pictures/bromigos/lab/` | What your homelab made for you. |

## The package repository

| File | What it holds |
|---|---|
| `/etc/pacman.conf` | Which repositories pacman uses. You add bromigOS here. |
| `/etc/pacman.d/bromigos-mirrorlist` | The stable package server and any extra mirrors you add. |
| `/usr/share/pacman/keyrings/bromigos.gpg` | The public signing key installed by `bromigos-keyring`. |
| `/usr/share/pacman/keyrings/bromigos-trusted` | The signing key's fingerprint for pacman. |

The [AUR install route](install.md#start-from-the-aur) puts the keyring and
mirrorlist in place. The packages leave `pacman.conf` for you to edit.

## Keep your settings in dotfiles

Your settings are plain files, so you can keep them in a git repository with the rest of
your dotfiles. To keep private values out of a public repository:

- homelab passwords and tokens are written as references, not as the secrets themselves
  ([Keep passwords out of the file](homelab.md#keep-passwords-out-of-the-file));
- other private values go in the [private overlay](glossary.md#private-overlay), which is
  encrypted. `bromigos private edit` opens it. It needs the `sops` and `age` packages.
