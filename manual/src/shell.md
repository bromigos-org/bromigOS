# Shell and terminal

bromigOS opens kitty as its terminal and provides a zsh shell setup. The prompt shows
where you are and, in a project, its Git branch and language version.

## Choose a prompt

Open Settings → Default apps and change **Prompt**, or run:

```bash
bromigos shell prompt mehshell
```

The choices are `mehshell`, `starship` and `none`. Open a new zsh shell after
changing the choice. `none` gives you a plain prompt with your current folder.
Starship needs its package first:

```bash
sudo pacman -S starship
bromigos shell prompt starship
```

New installs use mehshell. Existing installs keep their startup files and prompt.
To use the bromigOS choice on an existing install, replace your prompt engine's
initialisation line in `~/.zshrc` with this line:

```zsh
source /usr/share/bromigos/default/zsh/bromigos.zsh
```

Source it once. Remove any separate mehshell or Starship initialisation first.
It also loads bromigOS's login banner and folder shortcuts.

The choice is saved in `~/.config/bromigos/shell.toml`. Your prompt's other options
stay in its own config. mehshell uses `~/.config/mehshell/config`.

On Linux text consoles, mehshell uses text labels, simple prompt marks and basic
colours. Its startup cache is separate from the desktop's, so desktop icons do not
appear during console login. Your desktop style and icon settings stay saved.
Basic terminals (`TERM=dumb`) receive a prompt without colour formatting.

## Match the theme

mehshell follows every bromigOS theme. A theme change updates its colours, and
its next prompt reads them automatically. Your segment and style options stay
in place. Restart zsh after changing instant prompt, transient prompt or vi mode
options in mehshell's config.

## Install mehshell

The signed bromigOS package repository at [pkgs.bromigos.org](https://pkgs.bromigos.org)
includes mehshell. Once that repository is configured, run:

```bash
sudo pacman -S mehshell
```

Other systems can use the installation instructions in
[mehshell's repository](https://github.com/bromigos-org/mehshell).

## Make text consoles readable

The text console you reach with Ctrl+Alt+F3 has its own font, separate from kitty.
Check its saved setting, then choose a size:

```bash
bromigos console status
sudo bromigos console font medium
```

Choose `small`, `medium` or `large` for Terminus glyphs 16, 24 or 32 pixels tall.
`sudo bromigos console font default` removes the saved font choice.
The setting takes effect after reboot. The command keeps your keyboard layout and
other console settings, and leaves the running console alone.

The `bromigos-settings` package includes Terminus. On a core-only installation,
install it first with `sudo pacman -S terminus-font`. Text consoles support fewer
symbols than a graphical terminal; changing the size does not add Nerd Font icons.

The early boot or disk-unlock screen may still use a font stored in the initramfs
until that image is rebuilt separately. This command does not rebuild it.
A `vconsole.font` kernel option also takes precedence over the saved setting.
If you have custom `FONT_MAP` or `FONT_UNIMAP` settings, review them before choosing
a Terminus size; the command refuses to combine them. `default` preserves them.
