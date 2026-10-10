# bromigOS docs

These pages explain how bromigOS is built and how to extend it. They're for
contributors, and for anyone writing a theme, a panel, a deck or a homelab adapter.

- To **use** bromigOS, read [the manual](../manual/src/index.md).
- To **build, test and send a change**, read [CONTRIBUTING.md](../CONTRIBUTING.md).
- To **write or edit these pages**, follow [WRITING.md](WRITING.md).
- The [manual coverage audit](manual-audit.md) lists checked commands, keys and fixed gaps.

## Where files live

bromigOS keeps files in three places. Knowing which is which explains most of how it
works.

| Place | What's there | Who changes it |
|---|---|---|
| `/usr/share/bromigos/`, `/usr/lib/bromigos/` | The packages' defaults, themes, templates, tools and libraries | pacman, on every update |
| `~/.config/bromigos/`, plus small files in `~/.config/hypr/`, `waybar/` and others | Your settings, themes, hooks and plugins | You, Settings and `bromigos setup`. Updates never touch it |
| `~/.local/state/bromigos/` | Generated files: the rendered theme, the update log, setup's answers | The `bromigos` command |

Your config files for Hyprland, the bar and the other apps are thin. Each one includes
the packaged default and adds only your changes. So an update can improve the defaults
without overwriting your settings. [desktop.md](desktop.md) explains how, and the
manual's [Files and folders](../manual/src/files.md) lists them for users.

## The desktop

| Page | What it covers |
|---|---|
| [desktop.md](desktop.md) | The default configs and how yours sit on top, monitors, windows, keys and the start page |
| [settings.md](settings.md) | The Settings window, its pages, and how to add a page |
| [settings-audit.md](settings-audit.md) | The audit that shaped the Settings window |
| [idle.md](idle.md) | The screensaver, lock and sleep timers, and `idle.toml` |
| [accessibility.md](accessibility.md) | Reduced motion and high contrast |
| [menu.md](menu.md) | The desktop menu, and how a command adds itself to it |
| [webapps.md](webapps.md) | Web apps: a site in its own window, with a shortcut |
| [apps.md](apps.md) | The optional app bundle: LazyVim, tmux and others, themed |
| [hardware.md](hardware.md) | GPU drivers, laptops and touchpads, and `bromigos hw` |
| [peripherals.md](peripherals.md) | Peripheral modules, such as a Razer keyboard's macro keys and dial |

## Themes and worlds

| Page | What it covers |
|---|---|
| [theming.md](theming.md) | How themes work: colours, templates, hooks, emblems, and making your own |
| [worlds.md](worlds.md) | The worlds, Mire and Tidewell: what each thing on screen shows |
| [art.md](art.md) | The art pipeline that makes a world's paintings and animations |

## Panels, decks and extensions

| Page | What it covers |
|---|---|
| [widgets.md](widgets.md) | The desktop panels (widgets) and their settings |
| [plugins.md](plugins.md) | Plugin folders for your own decks, shader layers and panels |
| [extensions.md](extensions.md) | Extensions: installing, writing and publishing them with `bromigos ext` |
| [live/README.md](../live/README.md) | The live layer: the animated background, the decks and the screensaver |
| [live/docs/ELEMENTS.md](../live/docs/ELEMENTS.md) | Every element of the animated background |

## Your homelab and AI

| Page | What it covers |
|---|---|
| [homelab.md](homelab.md) | Showing your homelab on the desktop: capabilities, adapters, `homelab.toml` |
| [lab.md](lab.md) | `bromigos lab`: status, models, GPU jobs and the health check |
| [lab-models.md](lab-models.md) | The model catalog: the best open models for each task and GPU size |
| [lab-provision.md](lab-provision.md) | Setting up Core services, Kubernetes, Argo CD and Vault |
| [targets.md](targets.md) | Where AI work runs: your homelab, this machine or the cloud |

VECTOR, the desktop's AI assistant, is documented in his own repository,
`bromigos-org/vector`.

## Installing, updating and booting

| Page | What it covers |
|---|---|
| [install.md](install.md) | `install.sh`, `bromigos install`, `bromigos setup`, the packages and the fresh-machine test |
| [update.md](update.md) | `bromigos update`, channels, snapshots and rollback, and publishing the manual |
| [aur.md](aur.md) | The AUR: bromigOS's paru, AUR packages in updates and their snapshots, turning it off, and drivers only the AUR has |
| [boot.md](boot.md) | The themed boot menu and its snapshot entries |
| [iso.md](iso.md) | The live and install ISO, and its installer |
| [iso-encryption.md](iso-encryption.md) | Full-disk encryption in the ISO's installer |
| [release.md](release.md) | Cutting a release: versions, release notes, tags and promoting a candidate to stable |
| [public.md](public.md) | Making the package repository public: the R2 mirror and `go-public.sh` |

## The project

| Page | What it covers |
|---|---|
| [PLAN.md](PLAN.md) | Where bromigOS stands, its phases and the decisions behind it |
| [ASSETS.md](ASSETS.md) | Every shipped asset, where it came from, and whether it may ship |
| [WRITING.md](WRITING.md) | How to write these docs |
| [CHANGELOG.md](../CHANGELOG.md) | What changed in each release |

## The code

Each folder has a README for anyone about to work in it:
[core](../core/README.md), [desktop](../desktop/README.md), [live](../live/README.md),
[widgets](../widgets/README.md), [homelab](../homelab/README.md),
[settings](../settings/README.md), [theme](../theme/README.md), [lib](../lib/README.md),
[packaging](../packaging/README.md) and [brand](../brand/README.md).
[CONTRIBUTING.md](../CONTRIBUTING.md#repository-layout) shows how they fit together.

## Generated sections

Some sections come from the code, so they can't drift: the manual's
[Commands](../manual/src/commands.md) and [Keys](../manual/src/keys.md) pages, and the
package tables in [install.md](install.md) and the manual's
[What gets installed](../manual/src/packages.md). Never edit them by hand.
[CONTRIBUTING.md](../CONTRIBUTING.md#docs) explains how to regenerate and check them.

## Pictures

The pictures of the desktop in the README and the manual are drawn offscreen, with demo
readings, by `tools/screenshots/render.py <outdir>`. Its scenes are in
`tools/screenshots/scenes/`, and `--list` names every picture. Before a picture is kept,
it's read back with tesseract and checked for words no picture may show.
[theming.md](theming.md#the-previews) explains the desktop it draws.

[Agents in your lab](lab-agents.md) records agent installation, settings and upstream sources.
