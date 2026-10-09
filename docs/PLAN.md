# The bromigOS plan

This page is the plan for bromigOS. It says where each phase stands, what was built, what's
left, and the decisions behind it all. It's for contributors.

How each part works is in the docs page this plan links to. The repository's layout is in
[CONTRIBUTING.md](../CONTRIBUTING.md#repository-layout).

<!-- site:plan-status -->
## Where it stands

As of 2026-10-09:

- bromigOS is in early access. Phases 1, 2 and 3 are complete.
- A short script turns a fresh Arch install into the full desktop
  ([install.md](install.md)).
- The ISO boots a live desktop and installs it, encrypted, with snapshots in the boot menu
  ([iso.md](iso.md)).
- Phase 4, hardware and polish, has finished all its batches so far: the shell, themes
  beyond the desktop, safety, extensions, hardware, peripherals, accessibility, Settings,
  the shortcut picker and the boot menus.
- Phase 5, the lab console, has its first part built. Its second and third parts are
  planned.
- No decisions are open.

<!-- site:plan-highlights -->
## What bromigOS is about

The operator named four highlights on 2026-10-08. Every decision serves these first.

1. **The holograms.** VECTOR, the desktop's AI assistant, the decks and the live layer's
   holographic views.
2. **The homelab integrations.** The desktop is the homelab's console. Cluster health,
   GitOps, metrics, local models, secrets and agents show live on the desktop and to
   VECTOR. It's a first-class feature, in the `bromigos-homelab` package, not a private
   extra.
3. **The custom themes.** Themes are data, and one command recolours the whole desktop.
   The worlds are living scenes driven by real readings, with their own art, lore and
   emblems.
4. **The widgets.** Panels (widgets) on the desktop show real data and do things.

## Principles

- **A layer on Arch first, a distro second.** Ship an installer and pacman packages that
  sit on a plain Arch install. Build an ISO once that layer is solid.
- **The packages' files and the user's files stay apart.** Everything bromigOS installs
  belongs to a package, and updates replace it. A user's changes live in separate files
  that load the defaults, and updates never touch them.
- **The homelab integrations are a product feature. The operator's homelab is private.**
  The integrations ship generic in `bromigos-homelab`. Each is configured per user and off
  until configured. One person's hosts, endpoints, keys, personal plugins, likeness art and
  private voices stay in their own dotfiles and private overlay.
- **Every element shows real data or does something.** Nothing on screen is a decorative
  status label.
- **Use established tools.** archiso, pacman and makepkg, Hyprland, GTK's layer shell,
  Pydantic AI and standard speech models, not hand-rolled plumbing.

<!-- site:plan-phases -->
## Phases

### Phase 1: carve out the shareable desktop

**Done on 2026-10-08.**

The goal was to move the reusable parts of the operator's desktop out of his dotfiles and
into this repository, generalised. His desktop then runs on bromigOS plus his personal
plugins, so there's one source of truth.

What was built:

- **The packages.** `bromigos-core` holds the `bromigos` command, the themes and the
  shared Python libraries. `bromigos-live` is the live layer, with the worlds' engine.
  `bromigos-widgets` is the panels. `bromigos-desktop` holds the default configs for
  Hyprland, the bar, the launcher, notifications, idle and the lock screens, and the tools
  they call ([desktop.md](desktop.md)).
- **Thin user configs.** A user's files in `~/.config` include the read-only defaults and
  add their own changes. The lock screens work the same way. A VM test locked the screen,
  killed the locker and unlocked again.
- **Plugin folders** for the live layer, the panels, the homelab and VECTOR, in
  `~/.config/bromigos/plugins/` ([plugins.md](plugins.md)).
- **VECTOR in his own repository,** `bromigos-org/vector`, packaged as `bromigos-vector`
  into the same package repository. He has a brain with any OpenAI-compatible endpoint, a
  voice server with his own designed voice, an avatar and hologram renderer, tools with
  the terminal's limits, skills, and a local memory. Plugins can add tools, memory stores
  and skills. The guard watches his code, plugins and settings.
- **The private overlay and secrets tools,** `bromigos private` and `bromigos secrets`,
  and the emblem generator, `bromigos emblem build`, in `bromigos-core`. The brand's
  shareable sources are in `brand/`.
- **The homelab integrations as one package** (decided and built on 2026-10-08). Anyone
  with a homelab configures `bromigos-homelab` in `~/.config/bromigos/homelab.toml`. It's
  built on capabilities, not vendors, and adapters provide them. `bromigos setup homelab`
  finds the services and writes the file. Panels without code can be declared in the file.
  The LAB panel, the Ops, Netmap and Mind decks, the rack hologram, and VECTOR's read tools
  and memory moved into it. The operator's desktop runs on it with only his config
  ([homelab.md](homelab.md)).
- **`bromigos update`** (2026-10-08), the start of phase 2. It updates the packages, runs
  migrations, renders the theme again and restarts whatever runs old code. A pacman hook
  points a bare `pacman -Syu` at it ([update.md](update.md)).
- **Where AI runs** (2026-10-08). One setting, `targets.toml`, says where AI work runs:
  the homelab, this machine or the cloud, in order. `bromigos target` switches it
  ([targets.md](targets.md)). VECTOR never reaches the cloud on his own.

What's left:

- VECTOR's homelab *act* tools stay in his core. These are Argo CD sync, Vault writes and
  knowledge-base writes. The plugin seam allows only read and desktop levels, so moving
  them needs a deliberate, trusted plugin level.
- The Swarm deck's agents and the worlds' creatures read herdr from the live layer
  itself. herdr is a local tool, not part of the homelab.

### Phase 2: install on a fresh Arch machine

**Done on 2026-10-08.**

The goal was a bootstrap script, packages from bromigOS's own repository built in CI,
updates through pacman, and a first-run setup.

What was built:

- **`install.sh`,** about eighty lines. It adds the repository and its pinned key and
  installs `bromigos-core`. Then `bromigos install` installs the packages, services,
  configs and theme, and `bromigos setup` asks the first-run questions
  ([install.md](install.md)).
- **The `bromigos` meta-package** pulls in the whole desktop. `bromigos-desktop` declares
  the session's plumbing: the portal, a polkit agent, PipeWire and NetworkManager.
- **No AUR helper needed.** The AUR-only dependencies, `ttf-geist-mono` and `herdr`, are
  built into bromigOS's repository, pinned by checksum.
- **Plug-and-play monitors.** Nothing names a connector. Scale comes from pixel density,
  and workspaces split across monitors and follow hotplug ([desktop.md](desktop.md)).
- **Tests.** A KVM virtual machine installs from scratch, with one monitor, two, and
  hotplug (`test/vm/`). CI runs `install.sh --dry-run` on every installer change.
- **Closed on 2026-10-09.** The start page ships in `bromigos-desktop`. Screens that
  aren't 16:9 get the scene cropped to cover them, never stretched, and a world can set
  its focus point. nolgia signs in unattended with `--nolgia-token-file`. The launcher's
  menus and screenshots take the theme's colours.

What's left, none of it blocking:

- Run the VM test in CI. It needs a runner with KVM and about 8 GiB of memory
  ([install.md](install.md)).
- A trusted plugin level for VECTOR's homelab act tools (see phase 1).
- A read-only Proxmox token, for a live adapter test.
- A world focus point for Tidewell's surface on 32:9 screens, if wanted.

### Phase 3: the ISO

**Done on 2026-10-09.**

The goal was a live and install medium: a live session in the full desktop, a guided
install, and the splash and login screen in the theme.

What was built ([iso.md](iso.md)):

- **The profile,** in `iso/`. It's archiso's releng profile with bromigOS laid over it.
  BIOS and UEFI both boot straight into the full desktop as the user `live`.
- **The splash and login screen** in the Bromigos theme, from `bromigos-settings`.
- **The installer,** `bromigos-iso-install`. It drives archinstall with a few questions,
  then runs `bromigos install` and `bromigos setup` in the new system. By default the disk
  gets btrfs on LUKS2 encryption, with snapper and GRUB listing the snapshots
  ([iso-encryption.md](iso-encryption.md)).
- **No network needed.** The medium carries every package an install needs.
- **Tests in QEMU.** UEFI with encryption and BIOS without both installed, booted, signed
  in, updated and rolled back an update. CI checks the profile on every change.

What's left:

- Build the image and run the QEMU test in CI. Both need a privileged runner with KVM.

### Phase 4: hardware and polish

Phase 4 started from a list of features that Omarchy had and bromigOS lacked, approved on
2026-10-08. Each was adapted to bromigOS's packages and themes. Each batch below says what
was built and what's left.

#### The shell

**Done on 2026-10-09.**

- The desktop menu on **Super+Space**. Typing searches everything in it
  ([menu.md](menu.md)).
- The theme switcher on **Super+Ctrl+Shift+Space**. Its previews are the desktop drawn in
  each theme. Themes install from a Git URL, and **Super+Ctrl+Space** changes the
  wallpaper ([theming.md](theming.md)).
- Web apps: a site in its own window, with a shortcut ([webapps.md](webapps.md)).
- Setup menus for keybindings, input and config files.
- An on-screen display for volume and brightness, in the theme's colours.

#### Themes beyond the desktop

**Done on 2026-10-09.**

- `bromigos theme set` also themes btop, tmux, Neovim, and the browser frame in Chromium,
  Firefox and LibreWolf. Running apps pick up the change ([theming.md](theming.md)).
- Six colour themes: Rime, Sunder, Cinder, Lowtown, Highwind and Deepvein.
- Two panels, off by default: WEATHER and CONNECTIONS ([widgets.md](widgets.md)).
- Floating windows go back where they were, per workspace and app. It's opt-in
  ([desktop.md](desktop.md)).
- The app bundle, `bromigos-apps`: LazyVim, tmux, lazygit, mise, Chromium, Spotify, Signal
  and 1Password, configured and themed ([apps.md](apps.md)).

What's left:

- lazygit and mise can't include another file, so their configs are one-time copies.
- Chromium takes the frame colour only while it's running.

#### Safety and docs

**Done on 2026-10-09.**

- A snapshot before and after every `bromigos update`, on a btrfs root, and
  `bromigos update --rollback` to undo one. The boot menu lists the snapshots on GRUB
  ([update.md](update.md)).
- Four update channels: `stable`, `rc`, `edge` and `dev`.
- Full-disk encryption by default in the ISO's installer
  ([iso-encryption.md](iso-encryption.md)).
- The user manual in `manual/`, built and published by CI next to the packages. Its
  reference pages are generated from the code, and CI checks them.
- An update and its rollback, tested on the ISO's installed systems ([iso.md](iso.md)).

What's left:

- The plan named limine for the boot menu's snapshots. GRUB was built instead. limine
  needs `limine-snapper-sync` in bromigOS's repository.

#### Extensions

**Done on 2026-10-09.**

- One install command for everything bromigOS can be extended with: `bromigos ext`
  ([extensions.md](extensions.md)). An extension can be a theme, a deck, a shader layer,
  a panel, a VECTOR tool, memory store or skill, a homelab adapter, a command or a hook.
- Extensions come from Git, pinned to a commit, and a ledger records every file.
  Anything but a theme asks for approval at a terminal. VECTOR's terminal can't install,
  update or approve one.
- A starter for every kind, from `bromigos ext new`.
- A catalog, `bromigos-org/extensions`, with Mire and Tidewell and five tested examples.

What's left:

- The catalog is private, so only members of the organisation can read it.
- A catalog entry from a repository with many extensions clones the whole repository.

#### Hardware

**Done on 2026-10-09.**

- `bromigos hw` detects the GPUs, laptop parts and touchpads by reading files, then sets
  up what they need ([hardware.md](hardware.md)).
- The driver for each GPU comes from its makers' own lists. NVIDIA's Turing and newer get
  the open kernel modules. Older NVIDIA cards run nouveau. AMD and Intel get Mesa's
  pieces.
- Hybrid laptops get their render GPU set. Laptops get brightness and power profiles, and
  touchpads get tap to click and a three-finger workspace swipe.
- It runs in `bromigos install`, `bromigos setup` and the ISO's installer.
- Tested with unit tests on fixture machines, a real NVIDIA desktop read-only, and a QEMU
  machine posing as a laptop.

What's left:

- These need the real hardware to prove: NVIDIA's install on metal, the AUR driver
  branches, hybrid rendering, Intel and AMD on metal, and real batteries, keys and
  touchpads.

#### Peripheral modules

**Done on 2026-10-09.**

- The operator's Razer keyboard support became an optional module system,
  `bromigos peripheral` ([peripherals.md](peripherals.md)).
- The first module, `razer-keyboard`, binds the macro keys on that keyboard only. Its dial
  picks VECTOR's voice and its roller sets the volume. Its lighting follows VECTOR and the
  theme.
- Tested on a BlackWidow V4 Pro, and with fakes for the rest.

What's left:

- Other Razer keyboards' keys and dials aren't proven.
- Lighting works through openrazer only.

#### Accessibility

**Done on 2026-10-09.**

- Two settings: how much the desktop moves (`full`, `reduced` or `still`) and its
  contrast (`normal` or `high`) ([accessibility.md](accessibility.md)).
- Reduced motion reaches the live layer, the decks, Hyprland's animations and GTK.
  `still` holds the background as one frame, redrawn only when what it shows changes.
- High contrast raises every colour pair to WCAG targets, keeping the hues. Every shipped
  theme meets them, and the tests check it.
- VECTOR's holograms follow both settings.

What's left:

- The worlds' painted art, the login screen, the boot splash and the lock screen keep
  their colours.

#### Settings, and idle and lock

**Done on 2026-10-09.**

The operator asked for settings for the screensaver, lock and sleep timers, and for a
screensaver that doesn't lock.

- The idle policy is data, in `idle.toml`, with presets and a stay-awake switch
  ([idle.md](idle.md)).
- `bromigos settings` opens the Settings window, also on **Super+,**
  ([settings.md](settings.md)). Packages, extensions and users can add pages to it.

#### The Settings overhaul

**Done on 2026-10-09.**

The operator said the Settings window "could use love all over the place". An audit of
every page set the list ([settings-audit.md](settings-audit.md)).

- Groups, a search across every setting, one layout for every page, and Undo on every
  change.
- New pages, each backed by a small command of its own: Displays, Sound, Network,
  Bluetooth, Power, Keyboard and input, Date and time, Notifications, Default apps,
  Startup, Widgets, Live layer and holograms, Peripherals, Extensions, VECTOR, Creation
  targets, Account, About, and Updates and recovery ([settings.md](settings.md)).
- Tested with unit tests, offscreen renders, and an end-to-end run in a nested Hyprland
  with a sandboxed PipeWire (37 of 37 checks passed).

#### The shortcut picker

**Done on 2026-10-09, approved by the operator.**

- Change a shortcut without editing Lua: pick the action, then press the new keys
  ([desktop.md](desktop.md)). It's `bromigos keys`, or Settings › Shortcuts.
- It checks for clashes and offers to swap, replace or pick another. Every change can be
  undone.
- Tested by unit tests and an end-to-end run in a nested Hyprland with a virtual keyboard
  (49 of 49 checks passed).

#### The boot menus

**Done on 2026-10-09, approved by the operator.**

- GRUB's menu looks like the Wick's console, with the theme's colours, picture and
  emblem. The snapshots read like the rollback list ([boot.md](boot.md)).
- `bromigos boot theme` turns it on and off. A root helper copies the theme into `/boot`
  and puts things back on any failure.
- The ISO's boot menus match, on UEFI and BIOS.
- Only GRUB is themed. systemd-boot and limine are left alone.

### Phase 5: the lab console

The operator approved this plan on 2026-10-09: the desktop becomes the homelab's console,
through one command, `bromigos lab`, in three parts.

#### Part 1: the console

**Done on 2026-10-09** ([lab.md](lab.md)).

- `bromigos lab status`, and a live dashboard with no arguments. It shows a card for each
  part of the lab, built from whatever the adapters report.
- `bromigos lab models` shows what's installed and loaded where, and loads and unloads
  models. It also recommends models from the catalog ([lab-models.md](lab-models.md)).
- `bromigos lab run` and `bromigos lab jobs`: a queue for GPU work on the lab, such as
  images, holograms, voice lines and video. Heavy jobs run one at a time. It never uses a
  paid provider without `--cloud`. Upscales of images and clips, on SeedVR2 7B, came on
  2026-10-09. The same day, cutouts moved to Lucida and 3D to Pixal3D.
- `bromigos lab doctor` checks DNS, certificates, GPUs, disks, backups, GitOps and more.
  Every finding comes with a fix.
- The Lab deck, on **Super+Shift+H**, and Settings › Lab.
- Extensions can add status cards, doctor checks and job kinds ([homelab.md](homelab.md)).
- Tested with unit tests on recorded answers, offscreen renders, and an end-to-end run on
  a real homelab: read-only first, then a voice line and an image through the queue.

#### Part 2: changing the lab

> **Planned.** Not built yet.

Every change will be a commit or a pull request to the user's homelab repository, applied
by Argo CD, Flux or Ansible. Nothing will touch a server by hand. Each command will ask
first, and VECTOR's terminal will refuse all of them.

- `lab deploy <app>` will write the change, commit and push it, then follow the rollout.
  `--pr` will open a pull request instead.
- `lab logs <app>` will read the logs. It's read-only, so it may land early.
- `lab restart <app>` will restart an app through the repository, or through the API where
  the user allows it. It will never restart the voice service while VECTOR is speaking.
- `lab backups` will list, run and restore backups. A restore will always ask first and
  show what it overwrites.
- `lab power` will wake a sleeping machine and set GPU power limits.
- `lab models add|remove|replace` will change the lab's models. `replace` is also how the
  model catalog's auto-upgrade will apply. It will deploy the new model beside the old,
  test it, then switch or revert, and notify with Undo ([lab-models.md](lab-models.md)).

The hooks it needs are in place: job kinds can be non-GPU, and doctor checks and cards can
come from any module.

#### Part 3: setting up a new lab

> **Planned.** Not built yet. The design is [lab-provision.md](lab-provision.md).

`lab provision` will set up a new user's lab. The user picks a preset or their own set of
services. It will reach the machines over SSH, take an inventory, write a plan as the
user's own lab repository, apply it with Ansible, verify it, and write `homelab.toml` and
`targets.toml`. Only the reverse proxy will be exposed, and nothing will be public without
opting in. Installing an operating system on bare metal is out of scope.

The service catalog and presets are already data, in `homelab/share/lab/profiles.toml`.

## VECTOR without a homelab

VECTOR works on any machine. What runs his brain, voice and hearing depends on the GPU.

| Machine | Brain | Voice | Speech to text |
|---|---|---|---|
| No GPU | Any OpenAI-compatible endpoint, or the user's API key | Kokoro, on the CPU | Whisper small, on the CPU |
| A GPU with 8 GB or more | A local model through Ollama or llama.cpp | Kokoro or Qwen3-TTS 0.6B | Whisper turbo |
| A GPU with 12 GB or more, or a homelab | LiteLLM or a local vLLM | His Qwen3-TTS 1.7B voices | Whisper large-v3-turbo |

His memory works without a homelab too. The core remembers in a local SQLite store with a
local embedding model. Gnosis, a homelab memory service, is a plugin in
`bromigos-homelab`.

His tools are plugins with explicit permission levels: read-only, desktop actions and
shell. The shell has the same hard limits everywhere: no privilege escalation, no
secrets, no real money. Its refusals are enforced in code and covered by tests. His guard
records every change to his own code, plugins or settings in an audit log
(`bromigos vector guard log`). Only the operator switches him off, with the emergency
switch ([settings.md](settings.md#the-emergency-switch)).

## Where the desktop's pieces went

Phase 1 started from the operator's desktop, all in his dotfiles, on 2026-10-05. Each
piece went into a package or stayed personal.

| Piece | Now |
|---|---|
| The theme for Hyprland, the bar, the launcher, notifications and the lock screens | `bromigos-core` (themes, templates) and `bromigos-desktop` (configs) |
| The login screen, GTK, icons, cursor and fonts | `bromigos-settings` |
| SYSTEM, NETWORK, STORAGE, WORKBENCH, FIELD NOTES and SHORTCUTS panels | `bromigos-widgets`, with the new WEATHER and CONNECTIONS |
| The LAB panel, the Ops, Netmap and Mind decks, the lab feeds | `bromigos-homelab`, configured by `homelab.toml` |
| The background, scanner, screensaver, radial menu, sounds and the decks | `bromigos-live` |
| The 3D gallery, the hologram renderer and the event feed | `bromigos-vector` |
| VECTOR's brain, voices, memory, tools, terminal and skills | `bromigos-vector`, with his homelab tools in `bromigos-homelab` |
| A personal deck, a game-server panel, the voice cast, likeness art | Personal: the operator's plugins, in his dotfiles |
| The keyboard's macro keys, dial and lighting | A peripheral module in `bromigos-desktop` |

## What we borrowed from Omarchy

The plan studied Omarchy on 2026-10-07 and adapted these ideas:

- **Three places for files.** Read-only defaults, the user's own settings, and generated
  state ([README.md](README.md#where-files-live)).
- **`bromigos update` owns updating.** It runs the package transaction, then migrations,
  then hooks and restarts. Migrations are scripts in `migrations/`, named by timestamp and
  run once per user.
- **A command router.** `bromigos <group> <name>` runs a built-in or any
  `bromigos-<group>-<name>` executable, the way git finds its plugins. A header block
  describes each one, and `bromigos commands --check` lints them.
- **Themes as data.** A theme's colours render into every app's config.
- **Hardware quirks as small modules.** As built, these are the peripheral modules, as
  data rather than scripts.
- **Separate docs for users and contributors:** `manual/` and `docs/`. A third tree of
  contributor task guides isn't written yet.
- **Tests:** command tests, plus graphical tests through offscreen renders and a nested
  Hyprland.

Two ideas aren't built: seeding new users from `/etc/skel`, since the migrations seed each
user's configs instead, and `bromigos refresh <app>` to reset an app's config to the
defaults.

What bromigOS does differently: its own code is packaged, not pulled with `git pull`. The
core is Rust rather than shell scripts. VECTOR, the live layer and the holograms have no
counterpart there.

## Decisions

Each decision has its date, what was decided, and why.

**Audience (2026-10-05).** The Bromigos community first. Going public comes later, if it
makes sense.

**No regressions on the operator's desktop (2026-10-05).** Splitting the desktop out must
not take away anything his machine has. What's specific to it moves into the homelab
package's configuration or into personal plugins, and keeps working exactly as before.
Each step was checked against his live desktop before the dotfiles' copy was removed.
This held through phases 1 and 2.

**Repositories (2026-10-07).** One main repository plus a few satellites, as Omarchy does,
not many repositories, as EndeavourOS does. `bromigOS` holds everything that versions
together. VECTOR has his own repository, because he has his own release pace and tests,
and he's useful outside bromigOS. Possible later satellites are `bromigos-iso` and
`bromigos-pkgs`.

**Languages (2026-10-07).** A Rust core, with Python around it.

- Rust for the `bromigos` command and core library, and small always-on helpers. Later,
  perhaps, the live layer's render engine. It's the only piece that renders all the time,
  and in Python it costs about 7–8% of a CPU core and 270 MB.
- Python for VECTOR, the panels and, for now, the live layer. The machine-learning and
  automation tools are Python.
- Between them, TOML for config and JSON over Unix sockets. Python asks the `bromigos`
  binary for core logic instead of keeping its own copy, so every rule lives in one place.
  Three shell copies of the session-discovery logic caused three bugs on 2026-10-07.
- Shell only for tiny hooks and the bootstrap.

**Packaging (2026-10-07).** bromigOS's own code is packaged too, not updated with
`git pull`. Packages give versions, clean uninstalls, and pacman owning every file.
Migrations and lists of third-party packages are borrowed from Omarchy.

**Package hosting (2026-10-07).** A private, signed pacman repository, built by CI on
self-hosted runners. Going public would mean the same pipeline publishing to a public host,
such as Cloudflare R2, not a new pipeline.

**Licence (2026-10-07).** The code is `MIT OR Apache-2.0`, as with Omarchy and most Rust
tools. The brand assets, such as the emblem, art, voices and sounds, are all rights
reserved. [ASSETS.md](ASSETS.md) tracks each one.

**VECTOR's brain without a homelab (2026-10-07).** Local first, cloud optional. The first
run detects the GPU and runs a local model through Ollama when it fits. Otherwise it asks
for any OpenAI-compatible endpoint or API key.

**Default voice (2026-10-07).** VECTOR speaks with his own designed caretaker voices, made
from text with Qwen3-TTS VoiceDesign. No real person's or game's voice is used. Kokoro is
the light fallback. The operator's own voice cast stays a personal setting.

**Web search (2026-10-07).** Configurable, with SearXNG by default. The first run offers a
public instance or the user's own.

**Core memory store (2026-10-07).** SQLite with a small local embedding model, behind the
same remember, forget and recall interface. Gnosis is the operator's plugin.

**Art pipeline (2026-10-08).** A world's art is data. `themes/<world>/art.toml` lists every
asset and its recipe. `bromigos art plan` prices it from nolgia's live catalog,
`bromigos art run` makes it with the user's own nolgia login, and every job is logged.
Runs skip what's made and unchanged. It uses the best-quality models, with no cheap
default and no default spending cap. Spending is always logged and shown
([art.md](art.md)).

**Visibility (2026-10-09).** Private, as early access, until the asset audit in
[ASSETS.md](ASSETS.md) is done. After that, public repositories and the same pipeline
publishing to a public host.

**Brand separation (2026-10-09).** bromigOS sits under the Bromigos brand and is separate
from BRODEC. VECTOR's default voice is his own designed voice, and no other product's
voice cast ships.

No decisions are open.

## What's next

- Part 2 of the lab console: changing the lab through the homelab repository.
- Part 3 of the lab console: setting up a new lab.
- The follow-ups above, none blocking:
  - the fresh-machine VM test and the ISO build in CI, once a runner with KVM is free;
  - a trusted plugin level for VECTOR's homelab act tools;
  - `limine-snapper-sync` in the repository, for machines that boot with limine;
  - proof on real hardware for NVIDIA, hybrid laptops, Intel and AMD.
