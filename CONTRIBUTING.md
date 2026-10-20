# Contributing to bromigOS

This page is for anyone changing bromigOS's code or docs. It covers how the repository is
laid out, how to build and test it, how to try your build on a real machine, and how to
send a change.

bromigOS is in early access.

## Before you start

- **Writing docs?** Follow [docs/WRITING.md](docs/WRITING.md). It applies to every
  Markdown file here.
- **How a part works** is in [docs/](docs/README.md), one page per part, plus a README in
  each folder.
- **Why things are the way they are** is in [docs/PLAN.md](docs/PLAN.md), the plan and
  its decision log.
- **Working with an AI coding assistant?** [AGENTS.md](AGENTS.md) has the rules it
  follows. They're the same rules as here.
- **Everyone here** follows the [code of conduct](CODE_OF_CONDUCT.md).

## Repository layout

Each top-level folder becomes one package, or part of one. Every file bromigOS installs
belongs to a package, so pacman installs, updates and removes all of it.

| Folder | What's in it | Package |
|---|---|---|
| [`core/`](core/README.md) | The `bromigos` command and its Rust libraries: installing, updating, themes, the art pipeline | `bromigos-core` |
| [`desktop/`](desktop/README.md) | Default configs for Hyprland, the bar, the launcher, notifications and the lock screen, plus the menu, Settings and other tools | `bromigos-desktop` |
| [`live/`](live/README.md) | The live layer: the animated background, the worlds and the decks | `bromigos-live` |
| [`widgets/`](widgets/README.md) | The desktop panels (widgets) | `bromigos-widgets` |
| [`homelab/`](homelab/README.md) | The homelab integrations and `bromigos lab` | `bromigos-lab`, `bromigos-homelab` |
| [`settings/`](settings/README.md) | The login screen, boot splash, boot menu, and the GTK, icon and cursor themes | `bromigos-settings` |
| [`theme/`](theme/README.md) | The templates every theme renders into each app's config, the bar's icons and the canonical emblem | `bromigos-core` |
| `themes/` | The eleven themes: colours, art, emblems and the worlds' scenes | `bromigos-core` |
| [`lib/`](lib/README.md) | Python libraries shared by the other parts | `bromigos-core` |
| `bin/` | Small commands that `bromigos` runs, such as `bromigos terminal` | `bromigos-core` |
| `migrations/` | Scripts that `bromigos update` runs once per user to bring an install forward | `bromigos-core` |
| `apps/` | Configs for the optional app bundle ([docs/apps.md](docs/apps.md)) | `bromigos-apps` |
| `peripherals/` | Peripheral modules, such as a Razer keyboard's macro keys ([docs/peripherals.md](docs/peripherals.md)) | `bromigos-desktop` |
| [`packaging/`](packaging/README.md) | The PKGBUILDs and the publishing pipeline | |
| `iso/` | The live and install ISO ([docs/iso.md](docs/iso.md)) | |
| `install.sh` | The installer's first step, run on a fresh Arch install | |
| `manual/` | The user manual (mdBook) | `bromigos-manual` |
| `docs/` | How bromigOS is built, for contributors ([docs/README.md](docs/README.md)) | |
| `tools/` | Docs generation and link checks, the GPU table generator and offscreen renderers | |
| `test/vm/` | The fresh-machine test in a virtual machine | |
| [`brand/`](brand/README.md) | Bromigos logos and the house palette, as source files | |
| `.github/workflows/` | CI ([below](#what-ci-checks)) | |

VECTOR, the desktop's AI assistant, has his own repository, `bromigos-org/vector`. It
builds the `bromigos-vector` package into the same package repository.

## What you need

Work on an Arch Linux machine. Install the build tools:

```bash
sudo pacman -S --needed base-devel git rust python lua mdbook lychee
```

Each package lists anything else it needs in its PKGBUILD's `depends` and
`makedepends`. `makepkg -s` installs them for you.

## Build

The `bromigos` command is Rust. To build it:

```bash
cd core
cargo build -p bromigos
```

The command lands in `core/target/debug/bromigos`. Run
`core/target/debug/bromigos --help` to try it. Most of the Python parts run from an
installed package, so to try them, build the packages.

To build one package from your checkout:

```bash
cd packaging/bromigos-live
makepkg -f
```

Each PKGBUILD builds from the checkout it sits in, not from a download. `makepkg`
rewrites the `pkgver=` line, so don't commit that change. Undo it with
`git checkout -- PKGBUILD`.

## Try your build on your machine

The `dev` channel installs your own build on your own machine, through pacman like any
other update. `packaging/dev-repo.sh` builds every package into a local repository:

```bash
packaging/dev-repo.sh       # builds into ~/.local/share/bromigos/repo
bromigos channel dev        # points pacman at that repository
bromigos update             # installs your build
```

To build only some packages, name them: `packaging/dev-repo.sh ~/.local/share/bromigos/repo
bromigos-live`. The local repository isn't signed. It's your own machine's build.

To go back, run `bromigos channel stable`, then `bromigos update --downgrade`. Your build
may be newer than the latest release, so pacman needs permission to go back a version.

## Test

Each package runs its tests when it builds, in its PKGBUILD's `check()`. You can run them
on their own:

| Part | From | Command |
|---|---|---|
| The Rust core | `core/` | `cargo test` |
| The live layer | `live/` | `python -m unittest discover -s tests` |
| Settings, the menu, keys and other desktop tools | `desktop/` | `PYTHONPATH=lib python -m unittest discover -s tests` |
| The homelab integrations and `bromigos lab` | `homelab/` | `PYTHONPATH=lib python -m unittest discover -s tests` |
| The boot menu theme | the root | `python -m unittest discover -s settings/grub/tests` |
| The app launcher's entries | the root | `python tools/launcher/check.py --static` |

The unit tests use stand-ins and recorded answers, so they need no GPU, no homelab and no
running desktop.

Bigger tests run by hand:

- **End to end in a nested Hyprland.** `desktop/tests/e2e_settings_nested.py`,
  `e2e_keys_nested.py` and `e2e_widgets_nested.py` drive Settings, the shortcut picker and
  the panels' edit mode in a Hyprland session that runs inside a virtual display. Nothing
  appears on your screen. A kwin window rule keeps that session full screen, and a run
  stops at once if its screen isn't the size the test asked for.
- **A fresh machine.** `test/vm/arch-vm.sh` installs bromigOS on a new virtual machine
  and checks it. It needs KVM and at least 14 GB of available memory before starting.
  [docs/install.md](docs/install.md) explains it.
- **The ISO.** `iso/build.sh` builds the ISO, and `iso/test.sh` boots and installs it in
  QEMU. [docs/iso.md](docs/iso.md) explains both.

The lab provisioner has isolated Debian tests too. `test/vm/lab-provision-e2e.py`
checks Core, Advanced, repeat apply and an explicit kubeconfig.
`test/vm/lab-infrastructure-e2e.py` needs nested KVM. It checks single-box monitoring,
creates two libvirt guests, joins a third and verifies cluster monitoring. Both paths
check targets, a Grafana dashboard and a real alert firing and resolving. The keeper
stops guests if the parent dies. It caps test VM RAM at 8 GiB by default and CPUs
at four. The nested lab test reserves at most 10 GiB and four CPUs in total.
These tests never need a real Proxmox API or NAS.
See [infrastructure tests](docs/lab-infrastructure.md#extensions-and-tests).

### Screenshots

Take screenshots offscreen, never from a real desktop. These tools draw bromigOS without
a window:

| What | Tool |
|---|---|
| The README's and the manual's pictures, and the animated loop | `tools/screenshots/render.py` |
| The live layer: the background, a world, a deck, the screensaver | `live/tools/offscreen.py` |
| The Settings window, one picture per page and theme | `tools/settings/render.sh` |
| The theme switcher, at several screen sizes | `tools/theme-switcher/render.sh` |
| Zettlr in a theme | `tools/zettlr/render.sh` |
| The app launcher | `tools/launcher/render.py` |
| The boot menu, drawn by GRUB in a headless VM | `settings/grub/preview.py` |

Each tool's header explains its options. `tools/screenshots/render.py` uses demo readings
only, and reads every picture back with OCR to check that no private name shows. Images
for the docs go in `docs/images/`, and each needs a row in [docs/ASSETS.md](docs/ASSETS.md).

## Docs

Write docs the way [docs/WRITING.md](docs/WRITING.md) describes. Three parts of the docs
are generated from the code:

- the manual's [Commands](manual/src/commands.md) page, from each command's `--help` or
  header;
- the manual's [Keys](manual/src/keys.md) page, from the default Hyprland config;
- the package tables in [docs/install.md](docs/install.md) and the manual's
  [What gets installed](manual/src/packages.md) page, from the PKGBUILDs.

After you change a command's help, a default key or a PKGBUILD, build `bromigos` and run
the generator:

```bash
(cd core && cargo build -p bromigos)
tools/docs/generate.py
```

Then check the docs:

```bash
tools/docs/generate.py --check     # every generated section is current
tools/docs/check-links.sh          # every relative link and anchor resolves
mdbook build manual                # the manual builds
```

`mdbook serve manual` previews the manual in a browser while you write.

A new default key also needs a row in `widgets/keybinds.py`, which describes each key for
the shortcuts panel. The manual groups keys and commands by task, in plain words, from
`tools/docs/manual-reference.toml`. Give a new key or command a row there too. Without
one, the manual still lists it, under "Other keys" or "Other commands".

## Send a change

New pull requests use the [pull request template](.github/pull_request_template.md).
Describe the problem, what changes for the user, and the checks you ran. Include rollout
or rollback steps when needed, and remove that section when it does not apply.

- **Keep commits small,** one area at a time. Commit files by path, not with
  `git add -A`.
- **Start the subject with the area,** then say what changed in plain words. For example:
  `live: the timeline deck scrolls with the mouse wheel`, or
  `docs: install: the ISO's terminal key is Alt+Shift+Enter`.
- **Rebase on `main` before you push.** Other changes land there often.
- **Keep CI green.** If a check fails, fix it before anything else.

### What CI checks

| Workflow | When | What it checks |
|---|---|---|
| `packages` | pushes to `main` that change a package, and version tags | Builds every package, runs their tests, signs and publishes them |
| `docs` | changes to docs, commands, keys or PKGBUILDs | The generated sections are current, the manual builds, links resolve |
| `manual` | changes to the manual | Builds the manual and publishes it with the packages |
| `install-smoke` | changes to `install.sh`, the signing key or `test/vm/` | `install.sh --dry-run` in a fresh Arch container, and a wrong key is refused |
| `iso-check` | changes to the ISO, the boot splash or the boot menu | The ISO profile's scripts and files, and its package list |
| `launcher` | changes to commands, launcher entries or their icons | Every entry is valid and runs the right command |
| `lab-catalog` | Mondays | Refreshes the lab model catalog's metadata and proposes new models for review |
| `release-tools` | changes to the release tools or workflows | The release tool's tests, shellcheck, and the release workflows parsed |
| `release-prepare` | by hand | Picks the version, drafts the notes and opens the release pull request |
| `release` | merging a release pull request | Tags bromigOS and VECTOR, publishes, and creates the GitHub Releases |
| `release-promote` | by hand | Makes a release candidate the stable release, without rebuilding |

Pushes to `main` publish to the `edge` channel. Version tags publish `stable` and `rc`.
[packaging/README.md](packaging/README.md) explains publishing, and
[docs/release.md](docs/release.md) explains releases.

## Rules

- **Nothing private.** No hostnames, LAN addresses, tokens, Vault paths, personal plugins,
  likeness art or private voices. Those belong in a user's own dotfiles.
- **Every shipped asset needs a "yes" row** in [docs/ASSETS.md](docs/ASSETS.md). That
  includes images in the docs.
- **The name.** bromigOS is *based on Arch Linux*. Never put "Arch" in the product's
  name.
- **One product.** bromigOS is a Bromigos product, separate from BRODEC.
- **Docs follow the code.** If you change what something does, change its docs in the
  same commit.
