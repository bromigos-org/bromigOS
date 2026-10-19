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

## Configure and check mehshell

Preview the current prompt at the width of a split terminal:

```sh
bromigos shell preview --width 40
bromigos shell preview --style rainbow --width 80
```

Preview changes no settings. To save a style or brand choice:

```sh
bromigos shell configure style lean
bromigos shell configure brand bromigos
```

Styles are `lean`, `classic` and `rainbow`. Brand choices are `auto`, `bromigos`,
`os` and `none`. Auto shows the bromigOS text badge on bromigOS and the OS icon
elsewhere. Text consoles use plain text. These commands configure mehshell without
switching your selected prompt engine. Comments and theme colours are preserved.

The prompt adapts to narrow windows. It shortens paths and removes optional details
before dropping your current folder or session identity. Git shows changed file
counts, ahead/behind counts, conflicts and active operations. `wt:` identifies a
linked worktree. `status?` means Git could not be read within the prompt's time or
output limit; `upstream?` means the comparison is unavailable. Counts use local
information and never trigger a fetch.

SSH sessions show the user and host; root shows `ROOT`. A failed command shows a red
`exit:N`, where `N` is its exit code. This reports a command run in the current shell.
Startup checks and the cached prompt do not carry an old failure into a new terminal.
Pressing Enter on an empty line or Ctrl+C while editing clears the status. Interrupting
a running command with Ctrl+C normally returns code 130 and shows a grey `interrupted`
label.

A small `GAME` label reflects the local game-mode record. Turn off session, command
status or game-mode labels with `bromigos shell configure session false`, `status false`
or `game false`, respectively. All indicators use local information.

Check configuration and terminal fallback, or measure slow local prompt segments:

```sh
bromigos shell doctor
bromigos shell doctor --timings
```

`--json` gives structured output. The doctor reports configuration issues without
printing their values. It does not test the installed font's glyph coverage or
inspect your running shell's hooks. It never queries your lab or prints credentials.
Style and segment changes appear at the next prompt; open a new shell after changing
hook options or updating mehshell. To load updated hooks in the current zsh shell, run:

```zsh
eval "$(mehshell init zsh)"
```

Reloading mehshell keeps one copy of its hooks.

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
