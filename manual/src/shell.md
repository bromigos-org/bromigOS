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
