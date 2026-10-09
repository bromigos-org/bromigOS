# Apps

bromigOS runs any Linux app. This page covers installing apps, choosing which apps open
your files, and the optional app bundle: a set of apps already set up in bromigOS's style.

## Install an app

1. Open the menu with <kbd>Super</kbd>+<kbd>Space</kbd> and type `package`.
2. Choose **INSTALL › Package…**.
3. Type the package's name and press <kbd>Enter</kbd>. A terminal opens, installs it, and
   stays open so you can see the result.

Or in a terminal, with Arch Linux's package manager:

```bash
sudo pacman -S firefox
```

To remove an app, choose **REMOVE › Package…** in the menu, or run `sudo pacman -Rs` and
the package's name.

## Install an app from the AUR

The AUR, the Arch User Repository, has recipes for software that isn't in Arch Linux's own
repositories. A helper called paru fetches a recipe, builds the app on your machine and
installs it. bromigOS installs paru for you, unless you said no at the first run.

```bash
paru -S cbonsai
```

Anyone can submit a recipe to the AUR, and nobody checks it first. A recipe runs commands
on your machine when it builds. So before paru builds anything, it shows you the recipe, or
what changed in it, and asks whether to go on. Read it, or only install apps whose
maintainers you trust.

`bromigos update` updates your AUR apps too, after everything else. See
[Packages from the AUR](update-and-rollback.md#packages-from-the-aur).

To leave the AUR out altogether, run `bromigos aur off`. `bromigos aur on` brings it back.
The developer docs'
[aur.md](https://github.com/bromigos-org/bromigOS/blob/main/docs/aur.md) has the details.

A new app appears in the app launcher and the menu straight away. Some launchers keep a
cache, and show it the next time they open.

## Choose which apps open your files

Open **Settings › Default apps**. Choose the app that opens links, folders, text files,
pictures, videos, music, PDFs and email. The same page chooses the terminal and file
manager that bromigOS's keys open.

## Keep a website as an app

See [Web apps](webapps.md).

## A start page for your browser

bromigOS keeps a browser start page up to date for you, in your theme's colours. It has a
search box, your links, your homelab's status, your latest field notes and a clock.

1. In your browser's settings, set the home page to
   `file:///home/YOU/.local/share/bromigos/startpage/index.html`, with your user name in
   place of `YOU`.
2. To change the links, edit `~/.config/bromigos/startpage.toml`.

In Chromium-based browsers, you can also load the same folder as a new-tab extension.

## The app bundle

`bromigos-apps` is an optional set of apps with bromigOS's settings. Where the theme can
reach them, they take its colours.

| App | What you get |
|---|---|
| Neovim | The LazyVim set-up, in the theme's colours. It follows a theme change within seconds. |
| tmux | Sensible settings, with its status bar at the top, in the theme's colours. |
| btop | The theme's colours, once you choose the `bromigos` colour theme in btop's options. |
| lazygit | A plain interface in the terminal's colours. |
| mise | A starting `config.toml` for your tools. |
| Chromium | Settings for Wayland. Its window frame takes the theme's colour when you switch themes while it's open. |
| Spotify, Signal | As they come. |
| 1Password | Optional. Install it with `sudo pacman -S 1password`. |

To install the bundle:

1. Run `bromigos install --with bromigos-apps`, or `sudo pacman -S bromigos-apps`.
2. Run `bromigos apps setup`. This puts the apps' settings files in place, only where you
   don't have your own.

### Your own settings for these apps

Your Neovim and tmux files are short. They load bromigOS's settings first, so you add yours
after them. For Neovim, add plugins in `~/.config/nvim/lua/plugins/`, the LazyVim way.

lazygit, mise and Chromium can't load another file, so you get a copy of bromigOS's
settings. From then on the copy is yours, and updates don't change it.
