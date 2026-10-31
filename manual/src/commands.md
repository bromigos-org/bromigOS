# Commands

Everything bromigOS does has a command, and they all start with `bromigos`. You rarely
need them: the [menu](menu.md) and [Settings](settings.md) run most of them for you. They
help when you'd rather type, when you write a script, or when something goes wrong.

- `bromigos --help` lists the main commands.
- `bromigos commands` lists every command on your machine, your own included.
- Add `--help` to any command to see what it takes, such as `bromigos idle --help`.
- Many commands take `--json`, which prints their answer in a fixed format for scripts.

This page lists the commands by task first, then each one in full.

<!-- generated:commands (tools/docs/generate.py; don't edit by hand) -->

## Commands by task

### Set up and change settings

| Command | What it does |
|---|---|
| [`bromigos settings`](#bromigos-settings) | Open [Settings](settings.md). `bromigos settings sound` opens one page; `--search wifi` finds a setting. |
| [`bromigos setup`](#bromigos-setup) | Ask the [first-run questions](first-run.md) again, all of them or one section: `bromigos setup voice`. |
| [`bromigos setup input`](#bromigos-setup-input) | Set the keyboard layout, key repeat, the mouse and the touchpad. |
| [`bromigos setup keybindings`](#bromigos-setup-keybindings) | List every key in a menu, and run the one you pick. |
| [`bromigos setup config`](#bromigos-setup-config) | Open one of your config files in your editor. When you close the Hyprland file, it's checked and reloaded safely. |
| [`bromigos keys`](#bromigos-keys) | Make [your own shortcuts](shortcuts.md): press new keys for anything. |
| [`bromigos display`](#bromigos-display) | Change your monitors' resolution, refresh rate, scale and layout. |
| [`bromigos dictate`](#bromigos-dictate) | [Dictate at your cursor](dictation.md): start, finish, cancel or check a recording. |
| [`bromigos sound`](#bromigos-sound) | Choose speakers and microphone, and set volumes. |
| [`bromigos net`](#bromigos-net) | Turn Wi-Fi on or off, join a network, or connect a VPN. |
| [`bromigos bluetooth`](#bromigos-bluetooth) | Turn [Bluetooth](bluetooth.md) on or off, pair or connect devices, and choose a headset's sound: hi-fi, or headset with the microphone. |
| [`bromigos bluetooth tui`](#bromigos-bluetooth-tui) | Bluetooth in the terminal: pair step by step, test a controller, switch a headset's sound. `--window` opens it in its own window. |
| [`bromigos power`](#bromigos-power) | Choose a power profile, see batteries, and set what closing the lid does. |
| [`bromigos power menu`](#bromigos-power-menu) | Open the keyboard [power menu](power-menu.md) in a terminal or text console. |
| [`bromigos clock`](#bromigos-clock) | Set the time zone and how the bar's clock looks. |
| [`bromigos notifications`](#bromigos-notifications) | Turn on do not disturb, and choose where notifications appear and how long they stay. |
| [`bromigos defaults`](#bromigos-defaults) | Choose the apps that open links, files, pictures and the rest. |
| [`bromigos startup`](#bromigos-startup) | Choose what starts when you log in. |
| [`bromigos idle`](#bromigos-idle) | Choose what happens when you leave the computer: the [screensaver, the lock and sleep](idle.md). |
| [`bromigos lock`](#bromigos-lock) | Lock the screen now. |
| [`bromigos windows`](#bromigos-windows) | See or forget where your floating windows go back to. |
| [`bromigos profile`](#bromigos-profile) | Set your name, and what VECTOR calls you. |
| [`bromigos avatar`](#bromigos-avatar) | Set your picture, saved as `~/.face`. Settings › Account shows it. |
| [`bromigos login`](#bromigos-login) | Sign in to [your Bromigos account](bromigos-account.md): with a code on the website, with `--ssh` and an SSH key on your account, or with `--with-token` and a personal access token. |
| [`bromigos whoami`](#bromigos-whoami) | Show which [Bromigos account](bromigos-account.md) this computer is signed in to, and how. |
| [`bromigos logout`](#bromigos-logout) | Sign out of your [Bromigos account](bromigos-account.md) on this computer. |
| [`bromigos keyring`](#bromigos-keyring) | Check [your keyring](bromigos-account.md#your-keyring), where sign-ins are kept, with `status`. `setup` makes your login unlock it. |
| [`bromigos private`](#bromigos-private) | Edit the private overlay: settings you keep encrypted in your dotfiles. Needs the `sops` and `age` packages. |
| [`bromigos hw`](#bromigos-hw) | See what [hardware](hardware.md) bromigOS found, or set up drivers with `bromigos hw setup`. `hw graphics`, `hw display`, `hw games`, `hw run` and `hw vfio` [choose what each graphics card is for](hardware.md#choose-what-each-card-is-for): the desktop, games, or virtual machines. |
| [`bromigos peripheral`](#bromigos-peripheral) | Turn on extra features for a [keyboard](peripherals.md), such as a Razer keyboard's macro keys, or an Xbox controller's driver: `bromigos peripheral enable xbox-controller`. |

### Change the look

| Command | What it does |
|---|---|
| [`bromigos theme`](#bromigos-theme) | List the [themes](themes-and-worlds.md), or switch: `bromigos theme set mire`. |
| [`bromigos console`](#bromigos-console) | Read or save a [text console font](shell.md#make-text-consoles-readable) for the next boot. |
| [`bromigos splash`](#bromigos-splash) | Check, enable or undo the [shutdown and restart splash](boot-menu.md#the-startup-and-shutdown-splash) on a GRUB system. |
| [`bromigos theme switcher`](#bromigos-theme-switcher) | Open the theme switcher, with a preview of each theme. |
| [`bromigos theme previews`](#bromigos-theme-previews) | Draw the theme switcher's previews again. |
| [`bromigos wallpaper`](#bromigos-wallpaper) | Switch between the den wallpapers you have. |
| [`bromigos accessibility`](#bromigos-accessibility) | Reduce motion or raise contrast. See [Accessibility](accessibility.md). |
| [`bromigos anim`](#bromigos-anim) | List the background's animations, and turn each one on or off. |
| [`bromigos scene`](#bromigos-scene) | Change the background's other settings: the world, the screensaver, the sound volume. |
| [`bromigos live`](#bromigos-live) | Turn the animated background on or off, or open a [hologram](holograms.md): `bromigos live timeline`. |
| [`bromigos customize`](#bromigos-customize) | Preview themes and choose a panel layout in [Customize](themes-and-worlds.md#customize). |
| [`bromigos panels`](#bromigos-panels) | Show, hide or move the desktop [panels](panels.md), start edit mode, list every widget, and set the weather's place. |
| [`bromigos widgets`](#bromigos-widgets) | Show or hide one panel or all of them. |
| [`bromigos account`](#bromigos-account) | Sign a panel in to an online account, such as Twitch, GitHub, GitLab or Spotify. A service can have several accounts, such as gitlab.com and your company's GitLab. See [Panels that need an account](panels.md#panels-that-need-an-account). `bromigos account token` says how to make a Bromigos personal access token. |
| [`bromigos mute`](#bromigos-mute) | Mute or unmute the theme's sounds and VECTOR's voice together. |
| [`bromigos boot`](#bromigos-boot) | Turn the themed [boot menu](boot-menu.md) on or off. |
| [`bromigos emblem`](#bromigos-emblem) | Draw a theme's emblem pictures. For people making themes. |

### VECTOR and AI

| Command | What it does |
|---|---|
| [`bromigos vector`](#bromigos-vector) | Talk to [VECTOR](vector.md) and control him: `bromigos vector ask "…"`, `bromigos vector status`, and his emergency switch, `bromigos vector off` and `on`. |
| [`bromigos memory`](#bromigos-memory) | See, export or clear what VECTOR remembers. |
| [`bromigos target`](#bromigos-target) | Choose [where AI work runs](where-ai-runs.md): your homelab, this machine or the cloud. |
| [`bromigos art`](#bromigos-art) | Make a world's artwork, on your homelab's ComfyUI or through nolgia, which costs money. `plan` prices it first. For people making worlds. |

### Your homelab

| Command | What it does |
|---|---|
| [`bromigos setup homelab`](#bromigos-setup-homelab) | Find [your homelab](homelab.md)'s services and connect them. |
| [`bromigos homelab`](#bromigos-homelab) | See what's connected from your homelab, and what doesn't answer. |
| [`bromigos media`](#bromigos-media) | Open [Your media](media.md) in the terminal: find and request media, see their channels and download progress, monitor, play or delete shows, films and albums. |
| [`bromigos lab`](#bromigos-lab) | Open [the lab console](lab.md): your homelab's status, its GPUs, and jobs to run on them. |

### Apps, extensions and the menu

| Command | What it does |
|---|---|
| [`bromigos menu`](#bromigos-menu) | Open the [menu](menu.md). `--dump` prints everything in it. |
| [`bromigos webapp`](#bromigos-webapp) | Keep a website as an app of its own: [web apps](webapps.md). |
| [`bromigos apps setup`](#bromigos-apps-setup) | Put the [app bundle](apps.md)'s settings in place. |
| [`bromigos ext`](#bromigos-ext) | Find, install, update and remove [extensions](extensions.md). |
| [`bromigos extensions`](#bromigos-extensions) | Open the extensions window: what you have, and what you can add. |
| [`bromigos install extension`](#bromigos-install-extension) | Install an extension. The same as `bromigos ext install`. |
| [`bromigos remove extension`](#bromigos-remove-extension) | Remove an extension. The same as `bromigos ext remove`. |
| [`bromigos commands`](#bromigos-commands) | List every `bromigos` command on this machine, your own included. |

### Install, update and recover

| Command | What it does |
|---|---|
| [`bromigos install`](#bromigos-install) | [Install](install.md) bromigOS on an Arch Linux system. `install.sh` runs this for you. |
| [`bromigos update`](#bromigos-update) | [Update](update-and-rollback.md) everything. `--check` says what it would do; `--rollback` undoes the last update. |
| [`bromigos whats-new`](#bromigos-whats-new) | Read [what's new](whats-new.md) in this release, offline. `--all` shows every release. |
| [`bromigos channel`](#bromigos-channel) | See or change the [update channel](update-and-rollback.md#channels) you follow. |
| [`bromigos storage`](#bromigos-storage) | Plan a [data drive](storage.md), copy and verify files, then review a path switch while keeping the originals. |
| [`bromigos rollback`](#bromigos-rollback) | See whether updates can be undone on this machine, and set that up. |
| [`bromigos aur`](#bromigos-aur) | See which [AUR](apps.md#install-an-app-from-the-aur) packages have updates waiting. `bromigos aur off` leaves the AUR out of updates and removes bromigOS's paru; `on` brings it back. |
| [`bromigos restart`](#bromigos-restart) | Restart the parts of the desktop that still run old code after an update. |
| [`bromigos status`](#bromigos-status) | Check that the background, VECTOR and the session are running. |
| [`bromigos about`](#bromigos-about) | Show the version, the update channel, this machine's hardware and bromigOS's packages. |

### Screenshots and recordings

| Command | What it does |
|---|---|
| [`bromigos shot`](#bromigos-shot) | Take a screenshot: `bromigos shot region` or `bromigos shot screen`. |
| [`bromigos rec`](#bromigos-rec) | Start or stop a screen recording. |

### Used by the desktop itself

The desktop runs these for you. You don't need them day to day.

| Command | What it does |
|---|---|
| [`bromigos session`](#bromigos-session) | Connects programs to the running desktop session. |
| [`bromigos lock-run`](#bromigos-lock-run) | Starts the lock screen, and keeps the screen locked if the lock screen crashes. |
| [`bromigos banner`](#bromigos-banner) | Prints the login banner in a terminal. |
| [`bromigos secrets`](#bromigos-secrets) | Refreshes the desktop's secret files from Vault, if you keep secrets there. |

### Shell prompt

| Command | What it does |
|---|---|
| [`bromigos shell`](#bromigos-shell) | Choose the zsh prompt: mehshell, Starship or a plain prompt. See [Shell and terminal](shell.md). |

### Playing games

| Command | What it does |
|---|---|
| [`bromigos game`](#bromigos-game) | Give the game your keys and quiet the desktop. See [Playing games](games.md). |
| [`bromigos game setup`](#bromigos-game-setup) | Install Steam with your graphics cards' 32-bit drivers. See [Steam and Proton](games.md#steam-and-proton). |
| [`bromigos game proton`](#bromigos-game-proton) | List, install or remove Proton versions, such as GE-Proton. |
| [`bromigos game check`](#bromigos-game-check) | Find what stops games from starting. `--fix` repairs it now. |
| [`bromigos game maintain`](#bromigos-game-maintain) | Keep Steam and Proton ready. It runs by itself after each update and each time Steam exits. |

### Other commands

| Command | What it does |
|---|---|
| [`bromigos tv guide`](#bromigos-tv-guide) |  |
| [`bromigos welcome`](#bromigos-welcome) | The welcome tour after an install: Wi-Fi, your screens, a world, VECTOR and his voice, your homelab, the keys; every step skippable |
| [`bromigos welcome console`](#bromigos-welcome-console) | The welcome tour in the terminal (bromigOS Server's first sign-in): the network, SSH, joining your lab, and what's here |
| [`bromigos wol`](#bromigos-wol) | Keep Wake-on-LAN on for wired network cards |

## Every command in full

Each command's own help, A to Z. Commands built into `bromigos` show their whole `--help`; the others show how to call them and an example or two, and their own `--help` says more.

### bromigos about

About this machine and bromigOS: the version and channel, the packages, the hardware, the licences, the last update.

```text
bromigos about [status] | text | last-update  [--json]
```

For example:

```text
bromigos about
bromigos about text
bromigos about --json
```

From the `bromigos-desktop` package.

### bromigos accessibility

```text
Reduced motion and high contrast: show them, set them (`bromigos accessibility motion reduced`, `contrast high`), measure a theme's colours (`check`)

Usage: bromigos accessibility [OPTIONS] [COMMAND]

Commands:
  status    The settings and how the current theme's colours measure (the default)
  motion    How much the desktop moves: full, reduced or still
  contrast  The colours' contrast: normal or high
  check     Measure a theme's colours, normal and high contrast, against high contrast's targets
  help      Print this message or the help of the given subcommand(s)

Options:
      --json  Print the JSON document (schema in core/README.md)
  -h, --help  Print help
```

#### bromigos accessibility status

```text
The settings and how the current theme's colours measure (the default)

Usage: bromigos accessibility status [OPTIONS]

Options:
      --json  Print the JSON document (schema in core/README.md)
  -h, --help  Print help
```

#### bromigos accessibility motion

```text
How much the desktop moves: full, reduced or still

Usage: bromigos accessibility motion [OPTIONS] <LEVEL>

Arguments:
  <LEVEL>
          Possible values:
          - full:    Everything moves as designed
          - reduced: Calmer and slower: no parallax, flicker, flashes or static; window animations fade
          - still:   The live background holds a still frame; no window animations

Options:
      --no-reload
          Write the setting and render the theme, but tell no running app

      --json
          Print the JSON document (schema in core/README.md)

  -h, --help
          Print help (see a summary with '-h')
```

#### bromigos accessibility contrast

```text
The colours' contrast: normal or high

Usage: bromigos accessibility contrast [OPTIONS] <LEVEL>

Arguments:
  <LEVEL>
          Possible values:
          - normal: The theme's own colours
          - high:   Every colour the theme renders raised to WCAG AAA (text 7:1), panels opaque

Options:
      --no-reload
          Write the setting and render the theme, but tell no running app

      --json
          Print the JSON document (schema in core/README.md)

  -h, --help
          Print help (see a summary with '-h')
```

#### bromigos accessibility check

```text
Measure a theme's colours, normal and high contrast, against high contrast's targets

Usage: bromigos accessibility check [OPTIONS] [THEME]

Arguments:
  [THEME]  The theme (default: the current one)

Options:
      --json  Print the JSON document (schema in core/README.md)
  -h, --help  Print help
```

### bromigos account

Sign in to the online accounts widgets use (Twitch, GitHub, GitLab, Spotify), several per service if you like; tokens stay in your keyring.

```text
bromigos account list [PROVIDER] | add PROVIDER NAME [base=URL] [client_id=ID] [label=TEXT] | remove PROVIDER NAME | status|login|logout|set-token|configure PROVIDER [--as NAME] [client_id=ID] [base=URL]
```

For example:

```text
bromigos account login twitch
bromigos account add gitlab work base=https://git.example.org
bromigos account configure gitlab --as work client_id=abc123
bromigos account login gitlab --as work
bromigos account list
```

From the `bromigos-core` package.

### bromigos anim

```text
Every wallpaper animation and whether it's on; turn them on, off or reset

Usage: bromigos anim [OPTIONS] [VERB] [NAMES]...

Arguments:
  [VERB]      Turn on, off, or back to the defaults (no verb: list them) [possible values: on, off, reset]
  [NAMES]...  Animation names, or "all" (reset with none: all)

Options:
      --json  Print the JSON document (after any change; schema in core/README.md)
  -h, --help  Print help
```

### bromigos apps setup

Seed the app bundle's user configs (neovim, tmux, lazygit, mise, Chromium) where you have none.

```text
bromigos apps setup [--check]
```

For example:

```text
bromigos apps setup
bromigos apps setup --check
```

From the `bromigos-apps` package.

### bromigos art

```text
A world's art: plan (price it), run (make it through nolgia), status, mark

Usage: bromigos art [OPTIONS] <COMMAND>

Commands:
  plan    What a run would make and the exact credits, from nolgia's live catalog
  run     Make what isn't produced (or ASSET…) through nolgia, and log each job
  status  What's produced, missing, stale or new, and which backends answer (nolgia's credentials, the homelab ComfyUI)
  make    Make one thing through create.toml's providers, outside any world (VECTOR's hologram builder and gen3d.py call this). CAPABILITY: image.generate, image.edit, image.cutout, image.upscale, video.loop, video.upscale, model3d.generate
  mark    Record an asset made outside `art run` as produced with its current recipe
  help    Print this message or the help of the given subcommand(s)

Options:
      --json       Print the JSON document (schema in core/README.md)
      --dir <DIR>  The world's theme directory (default: themes/WORLD/ in the checkout you're in, then ~/.config/bromigos/themes/WORLD/, then the system's)
  -h, --help       Print help
```

#### bromigos art plan

```text
What a run would make and the exact credits, from nolgia's live catalog

Usage: bromigos art plan [OPTIONS] <WORLD> [ASSETS]...

Arguments:
  <WORLD>      
  [ASSETS]...  Only these assets (and the inputs they need that aren't produced)

Options:
      --force      Make the named assets again even if they're done
      --json       Print the JSON document (schema in core/README.md)
      --dir <DIR>  The world's theme directory (default: themes/WORLD/ in the checkout you're in, then ~/.config/bromigos/themes/WORLD/, then the system's)
  -h, --help       Print help
```

#### bromigos art run

```text
Make what isn't produced (or ASSET…) through nolgia, and log each job

Usage: bromigos art run [OPTIONS] <WORLD> [ASSETS]...

Arguments:
  <WORLD>      
  [ASSETS]...  

Options:
      --force                  
      --json                   Print the JSON document (schema in core/README.md)
      --dir <DIR>              The world's theme directory (default: themes/WORLD/ in the checkout you're in, then ~/.config/bromigos/themes/WORLD/, then the system's)
      --max-credits <CREDITS>  Refuse to start when the plan costs more (exit 3), and stop before a job that would take the run past it. No cap by default
  -h, --help                   Print help
```

#### bromigos art status

```text
What's produced, missing, stale or new, and which backends answer (nolgia's credentials, the homelab ComfyUI)

Usage: bromigos art status [OPTIONS] <WORLD>

Arguments:
  <WORLD>  

Options:
      --json       Print the JSON document (schema in core/README.md)
      --dir <DIR>  The world's theme directory (default: themes/WORLD/ in the checkout you're in, then ~/.config/bromigos/themes/WORLD/, then the system's)
  -h, --help       Print help
```

#### bromigos art make

```text
Make one thing through create.toml's providers, outside any world (VECTOR's hologram builder and gen3d.py call this). CAPABILITY: image.generate, image.edit, image.cutout, image.upscale, video.loop, video.upscale, model3d.generate

Usage: bromigos art make [OPTIONS] --out <FILE> <CAPABILITY>

Arguments:
  <CAPABILITY>  

Options:
      --json                     Print the JSON document (schema in core/README.md)
      --prompt <PROMPT>          The prompt (image.generate, image.edit, video.loop; optional otherwise)
      --dir <DIR>                The world's theme directory (default: themes/WORLD/ in the checkout you're in, then ~/.config/bromigos/themes/WORLD/, then the system's)
      --input <FILE>             An input image (the image to edit, cut out, upscale or model; the start frame; references for image.generate), or the clip to upscale; repeat for more
      --mask <FILE>              An edit's mask (transparent = may change)
      --provider <ID>            Use only this provider (comfyui:<name> or nolgia)
      --model <MODEL>            The workflow (ComfyUI) or model id (nolgia); needs --provider
      --aspect <ASPECT>          W:H for a new image or video
      --duration <DURATION>      A video's length in seconds (default 5)
      --resolution <RESOLUTION>  A video's resolution tier (nolgia's quality; a ComfyUI workflow's sizes, e.g. 720p or 480p)
      --alpha <MODE>             video.loop: make the world's loop from the raw clip with theme/tools/glow-loop.py (crop to the creature, cut at the wrap, matte): luma (glow on black, drawn additive), stacked (colour over its matte) or mask (also OUT-mask.png, a soft oval edge); the raw clip is kept as OUT-raw.mp4
      --post <ARG>               An argument for glow-loop.py with --alpha (repeat), e.g. --post=--width=960
      --out <FILE>               Where to write the result (.png, .mp4, .glb)
      --max-credits <CREDITS>    Skip a provider whose job would cost more
      --extra <KEY=VALUE>        A provider option, KEY=VALUE (VALUE as JSON when it parses, else text), e.g. texture=true for a textured nolgia mesh, scale=2 for an upscale; repeat for more
  -h, --help                     Print help
```

#### bromigos art mark

```text
Record an asset made outside `art run` as produced with its current recipe

Usage: bromigos art mark [OPTIONS] <WORLD> <ASSET>

Arguments:
  <WORLD>  
  <ASSET>  

Options:
      --job <JOB>          The nolgia job that made it
      --json               Print the JSON document (schema in core/README.md)
      --credits <CREDITS>  The credits it cost
      --dir <DIR>          The world's theme directory (default: themes/WORLD/ in the checkout you're in, then ~/.config/bromigos/themes/WORLD/, then the system's)
      --at <AT>            When it was made (RFC 3339; default now)
      --seconds <SECONDS>  
      --by <BY>            What made it [default: "bromigos art mark"]
  -h, --help               Print help
```

### bromigos aur

```text
The AUR (build recipes Arch users share; docs/aur.md): `status` (the helper here, whether bromigos update uses it, the AUR updates waiting), `on`, `off`, `ensure`

Usage: bromigos aur [OPTIONS] [COMMAND]

Commands:
  status  The helper here (bromigOS's paru, or your own paru or yay), whether bromigos update uses it, and the AUR updates waiting (paru -Qua) (the default)
  on      Use the AUR: bromigos update updates AUR packages, and bromigOS's paru is installed when there's no paru or yay here (sudo pacman -S paru)
  off     Leave the AUR alone: bromigos update doesn't touch AUR packages, and the paru bromigOS installed is removed (sudo pacman -R paru); a helper you installed stays
  ensure  bromigOS's paru, unless the AUR is off here or a helper is installed: what bromigos install and the update's migration run. Exit 75 when paru isn't in the repositories pacman has synced yet
  help    Print this message or the help of the given subcommand(s)

Options:
      --json  Print the JSON document (schema in core/README.md)
  -h, --help  Print help

The AUR (Arch User Repository) holds build recipes that Arch users share; anyone can submit one, so nobody vets them. bromigOS never needs it: an install comes from Arch's repositories and bromigOS's own, where its build of paru is too. With the AUR on (the default), bromigos update updates your AUR packages after the repositories', inside the same snapshot pair, and paru shows each recipe's changes for you to review first (--yes skips the review). The setting: ~/.config/bromigos/aur.toml. docs/aur.md.
```

#### bromigos aur status

```text
The helper here (bromigOS's paru, or your own paru or yay), whether bromigos update uses it, and the AUR updates waiting (paru -Qua) (the default)

Usage: bromigos aur status [OPTIONS]

Options:
      --json  Print the JSON document (schema in core/README.md)
  -h, --help  Print help
```

#### bromigos aur on

```text
Use the AUR: bromigos update updates AUR packages, and bromigOS's paru is installed when there's no paru or yay here (sudo pacman -S paru)

Usage: bromigos aur on [OPTIONS]

Options:
      --yes      pacman doesn't ask
      --dry-run  Only say what it would do
      --json     Print the JSON document (schema in core/README.md)
  -h, --help     Print help
```

#### bromigos aur off

```text
Leave the AUR alone: bromigos update doesn't touch AUR packages, and the paru bromigOS installed is removed (sudo pacman -R paru); a helper you installed stays

Usage: bromigos aur off [OPTIONS]

Options:
      --yes      pacman doesn't ask
      --dry-run  Only say what it would do
      --json     Print the JSON document (schema in core/README.md)
  -h, --help     Print help
```

#### bromigos aur ensure

```text
bromigOS's paru, unless the AUR is off here or a helper is installed: what bromigos install and the update's migration run. Exit 75 when paru isn't in the repositories pacman has synced yet

Usage: bromigos aur ensure [OPTIONS]

Options:
      --yes      pacman doesn't ask
      --dry-run  Only say what it would do
      --json     Print the JSON document (schema in core/README.md)
  -h, --help     Print help
```

### bromigos avatar

Your picture (~/.face, which the login screen shows), and whether your profile may be shared (dotfiles, the private overlay).

```text
bromigos avatar [status] | set FILE | clear  [--json]
```

For example:

```text
bromigos avatar
bromigos avatar set ~/Pictures/me.png
bromigos avatar clear
```

From the `bromigos-desktop` package.

### bromigos banner

The login banner: the emblem beside live readings (kernel, uptime, load, memory, disk).

```text
bromigos banner
```

From the `bromigos-desktop` package.

### bromigos bluetooth

Bluetooth: the adapter (on, off, visible), paired devices, pairing new ones, through bluez.

```text
bromigos bluetooth [status] | power on|off|toggle | discoverable on|off | scan [SECONDS] | pair MAC | connect MAC | disconnect MAC | trust MAC on|off | remove MAC | profile MAC hifi|headset | audio-default on|off | panel [pair MAC|scan] | menu | tui [--window] | session  [--json]
```

For example:

```text
bromigos bluetooth
bromigos bluetooth power on
bromigos bluetooth scan
bromigos bluetooth pair 00:00:5E:00:53:10
bromigos bluetooth profile 00:00:5E:00:53:10 headset
bromigos bluetooth panel
```

From the `bromigos-desktop` package.

### bromigos bluetooth tui

Bluetooth in the terminal: pair step by step, connect, test a controller, switch a headset's sound.

```text
bromigos bluetooth tui [--window]
```

For example:

```text
bromigos bluetooth tui
bromigos bluetooth tui --window
```

From the `bromigos-core` package.

### bromigos boot

```text
The boot menu: bromigOS's GRUB theme in your theme's colours (`bromigos boot theme status|on|off|apply`; docs/boot.md)

Usage: bromigos boot [COMMAND]

Commands:
  theme  GRUB's theme: status (default), on (turn it on, in the current theme's colours), off (GRUB's own menu, and it stays off here), apply (/boot on the current theme)
  help   Print this message or the help of the given subcommand(s)

Options:
  -h, --help  Print help
```

#### bromigos boot theme

```text
GRUB's theme: status (default), on (turn it on, in the current theme's colours), off (GRUB's own menu, and it stays off here), apply (/boot on the current theme)

Usage: bromigos boot theme [OPTIONS] [ACTION]

Arguments:
  [ACTION]  status, on, off or apply

Options:
      --no-prompt  on, apply: never ask sudo for a password (then the next bromigos update does it)
      --auto       on: not where `off` turned it off (bromigos install, setup, the migration)
      --dry-run    Only say what it would run
      --json       Print the JSON document (schema in core/README.md)
  -h, --help       Print help
```

### bromigos channel

```text
The update channel this machine follows (stable, rc, edge, dev): show it, or switch

Usage: bromigos channel [OPTIONS] [NAME]

Arguments:
  [NAME]  Switch to this channel (rewrites the [bromigos] Server line with sudo)

Options:
      --repo <URL>     The repository's base URL, when it isn't known (after dev) or changes
      --dev-dir <DIR>  dev: the local repository's directory (default ~/.local/share/bromigos/repo)
      --json           Print the JSON document (schema in core/README.md)
  -h, --help           Print help
```

### bromigos clock

Date and time: the time zone, network time, and the bar's clock (24 or 12 hour, seconds, the date).

```text
bromigos clock [status] | timezone ZONE | ntp on|off | format 24|12 | seconds on|off | date on|off | hook | zones | reset  [--json]
```

For example:

```text
bromigos clock
bromigos clock timezone Europe/Lisbon
bromigos clock format 12
bromigos clock date on
```

From the `bromigos-desktop` package.

### bromigos commands

```text
Every command: the built-ins and the bromigos-<group>-<name> executables found

Usage: bromigos commands [OPTIONS]

Options:
      --json   
      --check  Report commands with no summary, and route collisions (exit 1 if any)
      --all    Include hidden commands
  -h, --help   Print help
```

### bromigos console

Read or save the text console font for the next boot.

```text
bromigos console status [--json] | font small|medium|large|default
```

For example:

```text
bromigos console status
sudo bromigos console font large
sudo bromigos console font default
```

From the `bromigos-core` package.

### bromigos customize

Customize: the themes and the widget gallery in one window, with tabs (SUPER+CTRL+SHIFT+SPACE).

```text
bromigos customize [--tab themes|widgets] [--save-layout]
```

For example:

```text
bromigos customize
bromigos customize --tab widgets
bromigos customize --save-layout
```

From the `bromigos-desktop` package.

### bromigos defaults

Default apps: the browser, file manager, editor, viewers and players (xdg-mime), the terminal and file manager bromigOS's keys start, your web apps.

```text
bromigos defaults [status] | set KIND APP | terminal APP|COMMAND | files APP|COMMAND | apps [KIND] | webapp-add NAME URL | webapp-catalog NAME | webapp-remove NAME | reset  [--json]
```

For example:

```text
bromigos defaults
bromigos defaults set browser firefox.desktop
bromigos defaults terminal foot.desktop
bromigos defaults apps editor
```

From the `bromigos-desktop` package.

### bromigos dictate

Hold to dictate into the focused app, with an audio meter and transcript preview.

```text
bromigos dictate on | off | cancel | status [--json]
```

For example:

```text
bromigos dictate status
bromigos dictate on
bromigos dictate off
bromigos dictate cancel
```

From the `bromigos-desktop` package.

### bromigos display

Displays: each output's resolution, refresh rate, scale, position, orientation and the primary, applied with a 15-second check that reverts by itself.

```text
bromigos display [status] | apply [--output NAME [--mode WxH@HZ] [--scale S] [--position XxY] [--transform 0-7] [--off|--on]]… [--primary NAME] [--confirm SECONDS] | keep | revert | reset [--confirm SECONDS]  [--json]
```

For example:

```text
bromigos display
bromigos display apply --output DP-1 --mode 2560x1440@144 --scale 1.25
bromigos display keep
bromigos display revert
```

From the `bromigos-desktop` package.

### bromigos emblem

Build a theme's emblem kit (SVGs, PNGs, banner braille, lock layers).

```text
bromigos emblem build --theme DIR
```

From the `bromigos-core` package.

### bromigos ext

```text
Extensions from git: themes, decks, widgets, VECTOR tools, homelab adapters, commands, hooks (install, list, info, update, remove, new, search)

Usage: bromigos ext [OPTIONS] [COMMAND]

Commands:
  install   Install from a git URL, a folder or a catalog name: SOURCE[@tag|@branch|@commit]
  list      The installed extensions (and themes of yours not from one)
  info      One extension: installed (its ledger entry, files checked), or what a source would install (fetched and checked; nothing installed)
  update    Update one extension (or --all): shows what changed and any new permissions first
  remove    Remove an extension: its links, its checkout (the ledger keeps a line)
  enable    Link a disabled extension's parts again (its files are checked first)
  disable   Unlink an extension's parts; its checkout stays
  new       A working starter of KIND in ./NAME: theme, live-deck, live-layer, widget, vector-tool, vector-memory, vector-skill, homelab-adapter, command, hook
  search    The catalogs' extensions (bromigOS's own, or catalogs = […] in ~/.config/bromigos/ext.toml)
  validate  Check an extension folder (default .): its manifest, parts and permissions
  migrate   Themes installed before extensions (copied into ~/.config/bromigos/themes): each one a catalog has, file for file, becomes an extension that updates
  help      Print this message or the help of the given subcommand(s)

Options:
      --json  Print the JSON document
  -h, --help  Print help

Sources: a git URL (https://, ssh://, git@host:path, file://) or a folder, with
@tag, @branch or @commit to pin it (or --ref); or a name from the catalogs
(bromigos ext search). A theme repository without a bromigos-ext.toml installs as a
theme. Installed: ~/.local/share/bromigos/ext/src/<name> (a git checkout), linked into
~/.local/share/bromigos/ext/active/; the ledger: ~/.local/state/bromigos/ext/ledger.json.

Themes install at once. Anything else (code, or something VECTOR uses) shows its
permissions and asks you at a terminal; an update shows what changed first.
```

#### bromigos ext install

```text
Install from a git URL, a folder or a catalog name: SOURCE[@tag|@branch|@commit]

Usage: bromigos ext install [OPTIONS] <SOURCE>

Arguments:
  <SOURCE>  

Options:
      --json         Print the JSON document
      --ref <REF>    A branch, tag or commit (instead of @ref)
      --path <DIR>   The extension's folder inside the repository
      --name <NAME>  A theme repository without a manifest: install it under this name
      --copy         A folder that's a git repository: install its files as they are (uncommitted changes too) instead of its last commit
      --adopt        A theme of yours with the same name (an old `theme install`): move it aside (kept in ~/.local/state/bromigos/ext/adopted) and install this one
  -h, --help         Print help
```

#### bromigos ext list

```text
The installed extensions (and themes of yours not from one)

Usage: bromigos ext list [OPTIONS]

Options:
      --json    Print the JSON document
      --verify  Also check every file against the ledger
  -h, --help    Print help
```

#### bromigos ext info

```text
One extension: installed (its ledger entry, files checked), or what a source would install (fetched and checked; nothing installed)

Usage: bromigos ext info [OPTIONS] <WHAT>

Arguments:
  <WHAT>  

Options:
      --json         Print the JSON document
      --ref <REF>    
      --path <DIR>   
      --name <NAME>  
  -h, --help         Print help
```

#### bromigos ext update

```text
Update one extension (or --all): shows what changed and any new permissions first

Usage: bromigos ext update [OPTIONS] [NAME]

Arguments:
  [NAME]  

Options:
      --all        Every installed extension
      --json       Print the JSON document
      --ref <REF>  Move to this branch, tag or commit
      --check      Only say what would change
  -h, --help       Print help
```

#### bromigos ext remove

```text
Remove an extension: its links, its checkout (the ledger keeps a line)

Usage: bromigos ext remove [OPTIONS] <NAME>

Arguments:
  <NAME>  

Options:
      --json  Print the JSON document
  -h, --help  Print help
```

#### bromigos ext enable

```text
Link a disabled extension's parts again (its files are checked first)

Usage: bromigos ext enable [OPTIONS] <NAME>

Arguments:
  <NAME>  

Options:
      --json  Print the JSON document
  -h, --help  Print help
```

#### bromigos ext disable

```text
Unlink an extension's parts; its checkout stays

Usage: bromigos ext disable [OPTIONS] <NAME>

Arguments:
  <NAME>  

Options:
      --json  Print the JSON document
  -h, --help  Print help
```

#### bromigos ext new

```text
A working starter of KIND in ./NAME: theme, live-deck, live-layer, widget, vector-tool, vector-memory, vector-skill, homelab-adapter, command, hook

Usage: bromigos ext new [OPTIONS] <KIND> <NAME>

Arguments:
  <KIND>  
  <NAME>  

Options:
      --dir <DIR>  Where (default ./NAME)
      --json       Print the JSON document
  -h, --help       Print help
```

#### bromigos ext search

```text
The catalogs' extensions (bromigOS's own, or catalogs = […] in ~/.config/bromigos/ext.toml)

Usage: bromigos ext search [OPTIONS] [TERM]

Arguments:
  [TERM]  

Options:
      --json         Print the JSON document
      --kind <KIND>  Only this kind (theme, live-deck, widget, …)
      --refresh      Fetch the catalogs now (they are kept six hours)
  -h, --help         Print help
```

#### bromigos ext validate

```text
Check an extension folder (default .): its manifest, parts and permissions

Usage: bromigos ext validate [OPTIONS] [DIR]

Arguments:
  [DIR]  

Options:
      --json  Print the JSON document
  -h, --help  Print help
```

#### bromigos ext migrate

```text
Themes installed before extensions (copied into ~/.config/bromigos/themes): each one a catalog has, file for file, becomes an extension that updates

Usage: bromigos ext migrate [OPTIONS]

Options:
      --dry-run  Only say which
      --json     Print the JSON document
  -h, --help     Print help
```

### bromigos extensions

Extensions in a window: what's installed and the catalog, with previews; pick one to install, update, turn off or remove.

```text
bromigos extensions [--list [--json]]
```

For example:

```text
bromigos extensions
bromigos extensions --list
```

From the `bromigos-desktop` package.

### bromigos game

Give games the keyboard, quiet the desktop, and restore it afterwards.

```text
bromigos game on|off|toggle|status | auto on|off [--json]
```

For example:

```text
bromigos game on
bromigos game off
bromigos game auto on
```

From the `bromigos-desktop` package.

### bromigos game check

Check Steam, Proton and the desktop for what stops games starting; --fix repairs it now.

```text
bromigos game check [--fix] [--json]
```

For example:

```text
bromigos game check
bromigos game check --fix
```

From the `bromigos-desktop` package.

### bromigos game maintain

Keep Steam and Proton ready by itself: the latest GE-Proton, games set to a removed Proton, broken runtimes.

```text
bromigos game maintain [--wait] [--refresh] [--no-download] [--dry-run] [--notify] [--json]
```

For example:

```text
bromigos game maintain --dry-run
bromigos game maintain
```

From the `bromigos-desktop` package.

### bromigos game proton

Proton versions for Steam: list them, install the latest GE-Proton (checksum verified), remove one.

```text
bromigos game proton [list] | install [VERSION] | remove VERSION [--force]  [--json]
```

For example:

```text
bromigos game proton
bromigos game proton install
bromigos game proton remove GE-Proton10-25
```

From the `bromigos-desktop` package.

### bromigos game setup

Install Steam with the 32-bit graphics drivers for this machine's GPUs, and GameMode.

```text
bromigos game setup [--dry-run] [--yes] [--json]
```

For example:

```text
bromigos game setup --dry-run
bromigos game setup
```

From the `bromigos-desktop` package.

### bromigos homelab

The homelab connection: status (what provides what, what's unreachable), adapters, check &lt;capability&gt;.

```text
bromigos homelab
```

From the `bromigos-homelab` package.

### bromigos hw

```text
This machine's hardware: its GPUs and their drivers, a laptop's battery, backlight, touchpad and power profiles; `hw setup` sets them up (docs/hardware.md)

Usage: bromigos hw [OPTIONS] [COMMAND]

Commands:
  detect    What this machine is and what `bromigos hw setup` would do (the default)
  display   Which card draws the login screen and the desktop (read-only), or change it: `use CARD|auto`, `keep`, `cancel`, `reset` (Settings › Graphics)
  setup     Set this machine's hardware up: drivers, early KMS, a hybrid laptop's GPUs, power profiles, Hyprland's GPU environment (sudo for the system's part)
  graphics  Every graphics card and what it's for: the desktop, games and heavy apps, virtual machines (what Settings › Graphics shows)
  games     The card games and heavy apps use (Automatic: the strongest), or change it
  run       Run a program on the games card: bromigos hw run -- PROGRAM [ARGS] (a Steam game's launch options: bromigos hw run -- %command%)
  vfio      Virtual machines: each card's checks for VFIO passthrough, or `reserve CARD` and `release CARD|all` (by PCI address; sudo, then a restart)
  help      Print this message or the help of the given subcommand(s)

Options:
      --json  Print the JSON document (schema in core/README.md)
  -h, --help  Print help

What it reads: the PCI display devices (NVIDIA's own supported-chips list and Mesa's tables say which driver), the DMI chassis type, batteries, the lid, backlights, touchpads, the kernels, mkinitcpio's MODULES. What setup does, only where it differs: the GPU's packages (never swapping an installed NVIDIA driver), NVIDIA's early KMS, a hybrid laptop's render GPU (udev names, AQ_DRM_DEVICES for Hyprland), runtime power management for its NVIDIA GPU, and on a laptop brightnessctl and power-profiles-daemon. A driver only the AUR has (NVIDIA's 580.xx and 470.xx branches) is offered through paru, after a question. What each card is for (the desktop, games and heavy apps, virtual machines): hw graphics, hw display, hw games, hw run, hw vfio, and Settings › Graphics. docs/hardware.md.
```

#### bromigos hw detect

```text
What this machine is and what `bromigos hw setup` would do (the default)

Usage: bromigos hw detect [OPTIONS]

Options:
      --json  Print the JSON document (schema in core/README.md)
  -h, --help  Print help
```

#### bromigos hw display

```text
Which card draws the login screen and the desktop (read-only), or change it: `use CARD|auto`, `keep`, `cancel`, `reset` (Settings › Graphics)

Usage: bromigos hw display [OPTIONS] [COMMAND]

Commands:
  use     Draw the desktop on CARD (a PCI address such as 0000:03:00.0, or card1), or `auto`. A new card is tried first: log out and in, then `keep` it; a restart goes back
  keep    Keep the card being tried (after a login on it worked)
  cancel  Stop trying a card: the desktop stays where it was
  reset   Back to Automatic, from a text console too (sudo); then restart the login screen
  help    Print this message or the help of the given subcommand(s)

Options:
      --hyprland         Print the GPU order for Hyprland (the chosen card's, else the automatic one), or nothing when there is no clear choice
      --hyprland-chosen  Print "trial DEVICES" or "chosen DEVICES" for a card chosen in Settings, else nothing (Hyprland's startup asks this first)
      --json             Print the JSON document (schema in core/README.md)
  -h, --help             Print help
```

#### bromigos hw setup

```text
Set this machine's hardware up: drivers, early KMS, a hybrid laptop's GPUs, power profiles, Hyprland's GPU environment (sudo for the system's part)

Usage: bromigos hw setup [OPTIONS]

Options:
      --dry-run    Only say what it would do
      --yes        Answer pacman's questions with their defaults (unattended)
      --user-only  Only your own part: Hyprland's GPU environment (no sudo, no packages)
      --aur        Build a driver only the AUR has (NVIDIA's 580.xx or 470.xx) with paru without asking first; paru still shows its recipe for review unless --yes (docs/aur.md)
      --json       Print the JSON document (schema in core/README.md)
  -h, --help       Print help
```

#### bromigos hw graphics

```text
Every graphics card and what it's for: the desktop, games and heavy apps, virtual machines (what Settings › Graphics shows)

Usage: bromigos hw graphics [OPTIONS]

Options:
      --json  Print the JSON document (schema in core/README.md)
  -h, --help  Print help
```

#### bromigos hw games

```text
The card games and heavy apps use (Automatic: the strongest), or change it

Usage: bromigos hw games [OPTIONS] [COMMAND]

Commands:
  use    Run games and heavy apps on CARD (a PCI address, or card1), or `auto` (the strongest)
  steam  Start Steam on the games card (your copy of Steam's launcher), or stop
  help   Print this message or the help of the given subcommand(s)

Options:
      --json  Print the JSON document (schema in core/README.md)
  -h, --help  Print help
```

#### bromigos hw run

```text
Run a program on the games card: bromigos hw run -- PROGRAM [ARGS] (a Steam game's launch options: bromigos hw run -- %command%)

Usage: bromigos hw run [OPTIONS] [COMMAND]...

Arguments:
  [COMMAND]...  The program and its arguments, after `--`

Options:
      --print  Print the environment it sets (NAME=VALUE lines), and run nothing without a program
      --json   Print the JSON document (schema in core/README.md)
  -h, --help   Print help
```

#### bromigos hw vfio

```text
Virtual machines: each card's checks for VFIO passthrough, or `reserve CARD` and `release CARD|all` (by PCI address; sudo, then a restart)

Usage: bromigos hw vfio [OPTIONS] [COMMAND]

Commands:
  reserve  Reserve CARD for virtual machines (vfio-pci, by PCI address, from the next start): writes three files, makes the initramfs again (sudo)
  release  Give CARD (or `all`) back to its own driver, from the next start (sudo)
  help     Print this message or the help of the given subcommand(s)

Options:
      --json  Print the JSON document (schema in core/README.md)
  -h, --help  Print help
```

### bromigos idle

```text
Idle and lock: when the screensaver starts, the screen locks, the displays go off and it suspends (status, set, preset, stay-awake, off, undo; docs/idle.md)

Usage: bromigos idle [OPTIONS] [COMMAND]

Commands:
  status      The policy in force, in plain words, with any warnings (the default)
  set         Change it: KEY VALUE pairs. screensaver|lock|displays|suspend on|off|MINUTES (a time also turns it on: 8, 90m, 1h), activity on|off|SECONDS, lock-before-sleep on|off, or any section.key of idle.toml
  preset      A preset: default (bromigOS's timers), screensaver-only (the screensaver at its time, nothing locks, dims or sleeps), presentation (nothing idles)
  stay-awake  Stay awake for a while: 1h, 2h, 30m, 90 (minutes) or until-off; `off` ends it; `toggle [TIME]` turns it off when on, else on (1 h)
  off         Stop staying awake (stay-awake off)
  undo        Put idle.toml back as it was before the last change (again: redo)
  apply       Render the policy and restart this session's hypridle
  hook        Point ~/.config/hypr/hypridle.conf at the rendered policy, keeping your own listeners (an update's migration runs it)
  render      Print the hypridle config the policy renders to
  start       Hyprland's autostart: render the policy, then run hypridle (--detach: start it in this session now, through the compositor, unless it runs already)
  help        Print this message or the help of the given subcommand(s)

Options:
      --json        Print the JSON document (schema in core/README.md)
      --no-restart  Write and render only: don't restart hypridle
  -h, --help        Print help
```

#### bromigos idle status

```text
The policy in force, in plain words, with any warnings (the default)

Usage: bromigos idle status [OPTIONS]

Options:
      --json        Print the JSON document (schema in core/README.md)
      --no-restart  Write and render only: don't restart hypridle
  -h, --help        Print help
```

#### bromigos idle set

```text
Change it: KEY VALUE pairs. screensaver|lock|displays|suspend on|off|MINUTES (a time also turns it on: 8, 90m, 1h), activity on|off|SECONDS, lock-before-sleep on|off, or any section.key of idle.toml

Usage: bromigos idle set [OPTIONS] <KEY VALUE> <KEY VALUE>...

Arguments:
  <KEY VALUE> <KEY VALUE>...  

Options:
      --json        Print the JSON document (schema in core/README.md)
      --no-restart  Write and render only: don't restart hypridle
  -h, --help        Print help
```

#### bromigos idle preset

```text
A preset: default (bromigOS's timers), screensaver-only (the screensaver at its time, nothing locks, dims or sleeps), presentation (nothing idles)

Usage: bromigos idle preset [OPTIONS] <NAME>

Arguments:
  <NAME>  

Options:
      --json        Print the JSON document (schema in core/README.md)
      --no-restart  Write and render only: don't restart hypridle
  -h, --help        Print help
```

#### bromigos idle stay-awake

```text
Stay awake for a while: 1h, 2h, 30m, 90 (minutes) or until-off; `off` ends it; `toggle [TIME]` turns it off when on, else on (1 h)

Usage: bromigos idle stay-awake [OPTIONS] <TIME|until-off|off|toggle> [TIME]

Arguments:
  <TIME|until-off|off|toggle>  
  [TIME]                       toggle: how long when it turns on (default 1h)

Options:
      --json        Print the JSON document (schema in core/README.md)
      --no-restart  Write and render only: don't restart hypridle
  -h, --help        Print help
```

#### bromigos idle off

```text
Stop staying awake (stay-awake off)

Usage: bromigos idle off [OPTIONS]

Options:
      --json        Print the JSON document (schema in core/README.md)
      --no-restart  Write and render only: don't restart hypridle
  -h, --help        Print help
```

#### bromigos idle undo

```text
Put idle.toml back as it was before the last change (again: redo)

Usage: bromigos idle undo [OPTIONS]

Options:
      --json        Print the JSON document (schema in core/README.md)
      --no-restart  Write and render only: don't restart hypridle
  -h, --help        Print help
```

#### bromigos idle apply

```text
Render the policy and restart this session's hypridle

Usage: bromigos idle apply [OPTIONS]

Options:
      --json        Print the JSON document (schema in core/README.md)
      --no-restart  Write and render only: don't restart hypridle
  -h, --help        Print help
```

#### bromigos idle hook

```text
Point ~/.config/hypr/hypridle.conf at the rendered policy, keeping your own listeners (an update's migration runs it)

Usage: bromigos idle hook [OPTIONS]

Options:
      --json        Print the JSON document (schema in core/README.md)
      --no-restart  Write and render only: don't restart hypridle
  -h, --help        Print help
```

#### bromigos idle render

```text
Print the hypridle config the policy renders to

Usage: bromigos idle render [OPTIONS]

Options:
      --defaults    The packaged defaults' config instead of yours
      --json        Print the JSON document (schema in core/README.md)
      --no-restart  Write and render only: don't restart hypridle
  -h, --help        Print help
```

#### bromigos idle start

```text
Hyprland's autostart: render the policy, then run hypridle (--detach: start it in this session now, through the compositor, unless it runs already)

Usage: bromigos idle start [OPTIONS]

Options:
      --detach      
      --json        Print the JSON document (schema in core/README.md)
      --no-restart  Write and render only: don't restart hypridle
  -h, --help        Print help
```

### bromigos install

```text
Install bromigOS on this machine (after install.sh): the packages, services, the hardware, your configs, the desktop settings and the theme, then the first-run setup

Usage: bromigos install [OPTIONS]

Options:
      --dry-run         Only say what it would do
      --with <PACKAGE>  Optional packages too (e.g. --with bromigos-homelab --with herdr)
      --yes             Answer pacman's questions with their defaults (unattended)
      --no-services     Leave services alone
      --force-dm        Enable SDDM even when another display manager is enabled
      --theme <THEME>   The theme when none is set yet [default: wick]
      --no-hardware     Leave the hardware alone (drivers, early KMS, power profiles: bromigos hw setup later)
      --no-aur          No AUR helper: paru isn't installed, and bromigos update leaves the AUR alone (bromigos aur on, any time; docs/aur.md)
      --no-setup        Don't run the first-run setup afterwards
      --answers <FILE>  Setup's answers from a file (TOML; docs/install.md) instead of asking
      --json            Print the JSON document (schema in core/README.md)
  -h, --help            Print help
```

### bromigos install extension

Install an extension from a git URL, a folder or a catalog name (bromigos ext install).

```text
bromigos install extension SOURCE[@tag|@branch]
```

For example:

```text
bromigos install extension https://github.com/you/thing@v1.0
bromigos install extension hello-deck
```

From the `bromigos-core` package.

### bromigos keyring

The keyring that keeps your sign-ins (oo7): whether it runs and your login unlocks it, and setting that up.

```text
bromigos keyring status [--json] | setup [--dry-run]
```

For example:

```text
bromigos keyring status
bromigos keyring setup
```

From the `bromigos-core` package.

### bromigos keys

Your shortcuts without editing Lua: press a key for a default, a menu item, an app, a web app or a command; list, unbind, reset.

```text
bromigos keys [bind [KEYS] [--default KEYS | --from KEYS | --menu ID | --webapp NAME | --exec CMD [--what TEXT]] [--swap | --replace] [--yes] | list [--all] [--json] | check KEYS [--json] | unbind KEYS [--yes] | reset [KEYS] [--yes] | undo]
```

For example:

```text
bromigos keys
bromigos keys bind --default "SUPER + SPACE"
bromigos keys bind "SUPER + M" --default "SUPER + SPACE" --swap
bromigos keys bind "SUPER + ALT + G" --webapp gmail
bromigos keys list
bromigos keys reset
```

From the `bromigos-desktop` package.

### bromigos lab

Your homelab's console: status, models, jobs, doctor and guided maintenance (no arguments: the live dashboard).

```text
bromigos lab [status [--json] | models [list|load|unload|recommend|plan|upgrades] … | run KIND [PRESET] [--prompt …] [--input FILE] [--text …] [--cloud] [--wait] | jobs [list|watch|logs|cancel|retry] [ID] | doctor [--json] | maintenance [check|status|plan shutdown|startup|run PLAN_ID|resume RUN_ID] … | power [status|plan TARGET on|off|run PLAN_ID|resume RUN_ID] … | media search|get|status|upcoming|language … | provision [--guided [--start-over] | plan|apply|cluster|add-node|remove-node|vm|storage|capacity|add SERVICE|remove SERVICE --repo PATH …] | connect … | target …]
```

For example:

```text
bromigos lab
bromigos lab status
bromigos lab run image --prompt "a lighthouse at dusk"
bromigos lab run hologram --prompt "a brass telescope"
bromigos lab run voice --text "Lights are on."
bromigos lab jobs watch
bromigos lab doctor
bromigos lab provision
bromigos lab media get "Cowboy Bebop" --seasons all --specials
```

From the `bromigos-homelab` package.

### bromigos live

```text
The whole animated background: on|off (runtime), or any bromigos-live command

Usage: bromigos live [ARGS]...

Arguments:
  [ARGS]...
```

```text
bromigos live start|stop|restart|status|open <deck>|tv <verb>|<deck> …
```

From the `bromigos-live` package.

### bromigos lock

```text
Lock the screen now (loginctl lock-session)

Usage: bromigos lock

Options:
  -h, --help  Print help
```

### bromigos lock-run

```text
The lock launcher hypridle runs: keeps the screen locked if the locker crashes

Usage: bromigos lock-run

Options:
  -h, --help  Print help
```

### bromigos login

Sign in to your Bromigos account: a code on the website, an SSH key, or a personal access token; the sign-in stays in your keyring.

```text
bromigos login [--ssh [--key PATH] | --with-token] [--no-browser]
```

For example:

```text
bromigos login
bromigos login --ssh
bromigos login --ssh --key ~/.ssh/id_ed25519
bromigos login --with-token < token.txt
```

From the `bromigos-core` package.

### bromigos logout

Sign out of your Bromigos account on this computer.

```text
bromigos logout [--json]
```

For example:

```text
bromigos logout
```

From the `bromigos-core` package.

### bromigos media

Your media library in a terminal: TV, films, music, YouTube, downloads, releases, search and den TV channels; request, monitor, change quality, play, cast or delete.

```text
bromigos media [tv|movies|music|youtube|downloads|upcoming|search|channels] | search|get|status|upcoming|recent|library|language|monitor|profile|refresh|delete|channel|cast …
```

For example:

```text
bromigos media
bromigos media movies
bromigos media get "Cowboy Bebop"
bromigos media status
bromigos media cast targets
```

From the `bromigos-homelab` package.

### bromigos memory

VECTOR's memory and conversation history: what's kept, export it, clear it (recoverably), undo the clear.

```text
bromigos memory [status] | export DIR | clear history|memory|all --yes | undo  [--json]
```

For example:

```text
bromigos memory
bromigos memory export ~/Documents
bromigos memory clear history --yes
bromigos memory undo
```

From the `bromigos-desktop` package.

### bromigos menu

The desktop menu (SUPER+SPACE): launch, install, setup, style, update, toggles, VECTOR, holograms.

```text
bromigos menu [--filter TEXT | --dump | --json]
```

For example:

```text
bromigos menu
bromigos menu --dump
```

From the `bromigos-desktop` package.

### bromigos mute

```text
The desktop's one mute: the theme's sounds and VECTOR's voice together (on, off, toggle, status; SUPER+SHIFT+M)

Usage: bromigos mute [OPTIONS] [VERB]

Arguments:
  [VERB]
          Possible values:
          - on:     Mute the theme's sounds and VECTOR's voice
          - off:    Unmute both
          - toggle: Anything unmuted: mute all; all muted: unmute all (the keys)
          - status: Say what is muted
          
          [default: toggle]

Options:
      --json
          Print the JSON document

  -h, --help
          Print help (see a summary with '-h')
```

### bromigos net

The network: Wi-Fi (on, off, scan, connect, forget), wired, VPNs, through NetworkManager.

```text
bromigos net [status] | wifi on|off | scan | connect SSID [--password-stdin] [--hidden] [--device DEV] | disconnect DEVICE | forget NAME|UUID | up NAME|UUID | down NAME|UUID | autoconnect NAME|UUID on|off | panel on|off  [--json]
```

For example:

```text
bromigos net
bromigos net wifi off
echo 'secret' | bromigos net connect HomeNet --password-stdin
bromigos net up work-vpn
```

From the `bromigos-desktop` package.

### bromigos notifications

Notifications (dunst): do not disturb, where they appear, how long they stay, each app's rule.

```text
bromigos notifications [status] | dnd on|off|toggle | position CORNER | offset X Y | timeout low|normal|critical SECONDS | app NAME show|quiet|hide | clear-history | test | reset  [--json]
```

For example:

```text
bromigos notifications dnd on
bromigos notifications position bottom-right
bromigos notifications timeout normal 12
bromigos notifications app Spotify quiet
```

From the `bromigos-desktop` package.

### bromigos panels

The desktop panels: which are on, where they sit, the monitor, the weather's place (your layout.json and weather.toml).

```text
bromigos panels [status] | edit | gallery [--previews DIR] | layouts | layout apply ID [--monitor NAME] [--all-themes] | layout save NAME [--description TEXT] [--monitor NAME] | layout save --replace ID [--description TEXT] [--monitor NAME] | layout undo | tidy [--monitor NAME] | show|hide|add NAME | settings NAME | set NAME KEY VALUE… | unset NAME KEY | inspect SOURCE [--path DIR] [--ref REF] | move NAME X Y | size NAME W H|CLASS | monitor NAME|"" | weather place PLACE | weather coords LAT LON | weather units metric|imperial | weather name TEXT | weather clear | reset  [--json]
```

For example:

```text
bromigos panels
bromigos panels edit
bromigos panels layouts
bromigos panels layout apply homelab
bromigos panels tidy
bromigos panels add weather
bromigos panels weather place "San Diego"
bromigos panels hide connections
```

From the `bromigos-desktop` package.

### bromigos peripheral

```text
Optional peripheral modules: a Razer keyboard's macro keys, its dial as VECTOR's voice dial, lighting that follows VECTOR (list, status, enable, disable, refresh)

Usage: bromigos peripheral [OPTIONS] [COMMAND]

Commands:
  list     Every module: whether its device is here, whether it's on, what it needs
  status   The modules that are on, as the desktop runs them: devices, keys, dial, lighting
  enable   Turn a module on: its packages, group and services, your choice recorded, the keys bound (a verified Hyprland reload) and the dial and lighting started
  disable  Turn a module off (its packages stay installed)
  follow   What a module's lighting follows: VECTOR (his voice and mood) or the theme (its primary, always); written to peripherals.toml, the daemon takes it within 10 s
  refresh  Write the keys again from peripherals.toml and the devices here (after an edit, or another keyboard plugged in); Hyprland reloads only when they changed
  help     Print this message or the help of the given subcommand(s)

Options:
      --json  Print the JSON document (schema in core/README.md)
  -h, --help  Print help

Modules: /usr/share/bromigos/peripherals/<id>/ (packaged), ~/.config/bromigos/peripherals/<id>/
(yours: a similar keyboard; docs/peripherals.md). Your choices and key changes:
~/.config/bromigos/peripherals.toml, e.g.

  [razer-keyboard]
  enabled = true
  rgb = "all"          # the lighting: all (every Razer device), device (the keyboard), off
  dial = true
  [razer-keyboard.keys]
  side1 = "bromigos-live timeline"   # "" leaves a key unbound

then `bromigos peripheral refresh`.
```

#### bromigos peripheral list

```text
Every module: whether its device is here, whether it's on, what it needs

Usage: bromigos peripheral list [OPTIONS]

Options:
      --json  Print the JSON document (schema in core/README.md)
  -h, --help  Print help
```

#### bromigos peripheral status

```text
The modules that are on, as the desktop runs them: devices, keys, dial, lighting

Usage: bromigos peripheral status [OPTIONS]

Options:
      --json  Print the JSON document (schema in core/README.md)
  -h, --help  Print help
```

#### bromigos peripheral enable

```text
Turn a module on: its packages, group and services, your choice recorded, the keys bound (a verified Hyprland reload) and the dial and lighting started

Usage: bromigos peripheral enable [OPTIONS] <ID>

Arguments:
  <ID>  

Options:
      --dry-run    Only say what it would do
      --json       Print the JSON document (schema in core/README.md)
      --yes        Answer pacman's questions with their defaults
      --force      Turn it on even when its device isn't connected now
      --no-reload  Don't reload Hyprland (it takes the keys at its next reload)
      --no-system  Don't install, join groups or start services (record the choice, write the keys)
  -h, --help       Print help
```

#### bromigos peripheral disable

```text
Turn a module off (its packages stay installed)

Usage: bromigos peripheral disable [OPTIONS] <ID>

Arguments:
  <ID>  

Options:
      --json       Print the JSON document (schema in core/README.md)
      --no-reload  Don't reload Hyprland
      --no-system  Leave the daemon alone
  -h, --help       Print help
```

#### bromigos peripheral follow

```text
What a module's lighting follows: VECTOR (his voice and mood) or the theme (its primary, always); written to peripherals.toml, the daemon takes it within 10 s

Usage: bromigos peripheral follow [OPTIONS] <ID> <FOLLOW>

Arguments:
  <ID>      
  <FOLLOW>  [possible values: vector, theme]

Options:
      --json  Print the JSON document (schema in core/README.md)
  -h, --help  Print help
```

#### bromigos peripheral refresh

```text
Write the keys again from peripherals.toml and the devices here (after an edit, or another keyboard plugged in); Hyprland reloads only when they changed

Usage: bromigos peripheral refresh [OPTIONS]

Options:
      --json       Print the JSON document (schema in core/README.md)
      --no-reload  Don't reload Hyprland
  -h, --help       Print help
```

### bromigos power

Power: the power profile, batteries, what closing the lid does, suspend.

```text
bromigos power [status] | profile NAME | lid ACTION [--on-power ACTION] [--docked ACTION] [--print] | suspend  [--json]
```

For example:

```text
bromigos power
bromigos power profile power-saver
bromigos power lid lock --on-power ignore
```

From the `bromigos-desktop` package.

### bromigos power menu

Choose and confirm a power action with the keyboard.

```text
bromigos power menu [--preview]
```

For example:

```text
bromigos power menu
bromigos power menu --preview
```

From the `bromigos-core` package.

### bromigos private

The private overlay: encrypted values in your dotfiles, decrypted at login.

```text
bromigos private decrypt|edit|status|seed-profile
```

From the `bromigos-core` package.

### bromigos profile

```text
Who you are and what VECTOR calls you (show, set, address, alias)

Usage: bromigos profile [OPTIONS] [COMMAND]

Commands:
  show     Show the profile (the default)
  set      Set name, full_name or pronouns ("" clears it)
  address  Forms of address, most preferred first: add, remove, or set the whole list
  alias    Other names you go by: add or remove
  help     Print this message or the help of the given subcommand(s)

Options:
      --json  Print the JSON document (after any change; schema in core/README.md)
  -h, --help  Print help
```

#### bromigos profile show

```text
Show the profile (the default)

Usage: bromigos profile show [OPTIONS]

Options:
      --json  Print the JSON document (after any change; schema in core/README.md)
  -h, --help  Print help
```

#### bromigos profile set

```text
Set name, full_name or pronouns ("" clears it)

Usage: bromigos profile set [OPTIONS] <FIELD> <VALUE>

Arguments:
  <FIELD>  [possible values: name, full_name, pronouns]
  <VALUE>  

Options:
      --json  Print the JSON document (after any change; schema in core/README.md)
  -h, --help  Print help
```

#### bromigos profile address

```text
Forms of address, most preferred first: add, remove, or set the whole list

Usage: bromigos profile address [OPTIONS] <VERB> [VALUE]...

Arguments:
  <VERB>      [possible values: add, remove, set]
  [VALUE]...  

Options:
      --json  Print the JSON document (after any change; schema in core/README.md)
  -h, --help  Print help
```

#### bromigos profile alias

```text
Other names you go by: add or remove

Usage: bromigos profile alias [OPTIONS] <VERB> <VALUE>...

Arguments:
  <VERB>      [possible values: add, remove]
  <VALUE>...  

Options:
      --json  Print the JSON document (after any change; schema in core/README.md)
  -h, --help  Print help
```

### bromigos rec

Start/stop a screen recording to ~/Videos/recordings.

```text
bromigos rec [region|screen]
```

From the `bromigos-desktop` package.

### bromigos remove extension

Remove an installed extension: its links and its checkout (bromigos ext remove).

```text
bromigos remove extension NAME
```

For example:

```text
bromigos remove extension hello-deck
bromigos ext list
```

From the `bromigos-core` package.

### bromigos restart

```text
Restart what runs stale (its package is newer than the process), or the pieces named

Usage: bromigos restart [OPTIONS] [PIECES]...

Arguments:
  [PIECES]...  live, widgets, waybar, dunst, vector, hyprland (its config), osd, idle (hypridle), or a user unit a package's restart.d drop-in declares; none: whatever is stale

Options:
      --check  Only say what would restart
      --json   Print the JSON document (schema in core/README.md)
  -h, --help   Print help
```

### bromigos rollback

```text
Rolling updates back: `status` (how this machine snapshots updates, what can be undone), `setup` (snapper's root configuration, snap-pac, grub-btrfs with its overlay hook or limine-snapper-sync, where / is btrfs), `allow` (wheel may list root's snapshots, so updates are recorded). Undoing one is `bromigos update --rollback`

Usage: bromigos rollback [OPTIONS] [ACTION]

Arguments:
  [ACTION]  status (default), setup or allow

Options:
      --dry-run  setup, allow: only say what it would run
      --yes      setup: pacman doesn't ask (unattended installs)
      --json     Print the JSON document (schema in core/README.md)
  -h, --help     Print help
```

### bromigos scene

The live layer's settings beyond the animation switches: the world, the screensaver's content, the sounds' volume, the codec's calls and den TV playback.

```text
bromigos scene [get [KEY…]] | set KEY VALUE | reset [KEY…] | keys  [--json]
```

For example:

```text
bromigos scene
bromigos scene set sounds.volume 0.2
bromigos scene set world.enabled off
```

From the `bromigos-desktop` package.

### bromigos secrets

Refresh the desktop's secret files from Vault (never prints values).

```text
bromigos secrets sync [--quiet]|status
```

From the `bromigos-core` package.

### bromigos session

```text
The live Hyprland session (prints KEY=value; import, exec or adopt it; hold and release its config reloads around a package transaction)

Usage: bromigos session [OPTIONS] [COMMAND]

Commands:
  shell-env  Print missing or stale local shell display settings; leave SSH and working displays alone
  import     Also push WAYLAND_DISPLAY and HYPRLAND_INSTANCE_SIGNATURE to systemd --user and D-Bus
  exec       Import, then exec CMD with the session's values
  adopt      At login: import, and stop VECTOR's daemon if it belongs to another session
  hold       Hold Hyprland's config reloads: auto-reload off in every running Hyprland (as root, every user's), what it was remembered. pacman runs it before a transaction that changes the desktop's default config (docs/update.md)
  release    Let go of a hold: each held Hyprland's config verified (Hyprland --verify-config), reloaded once when it verifies, auto-reload back as it was. pacman runs it after the transaction
  help       Print this message or the help of the given subcommand(s)

Options:
      --json  Print the JSON document (schema in core/README.md)
  -h, --help  Print help
```

#### bromigos session shell-env

```text
Print missing or stale local shell display settings; leave SSH and working displays alone

Usage: bromigos session shell-env [OPTIONS]

Options:
      --json  Print the JSON document (schema in core/README.md)
  -h, --help  Print help
```

#### bromigos session import

```text
Also push WAYLAND_DISPLAY and HYPRLAND_INSTANCE_SIGNATURE to systemd --user and D-Bus

Usage: bromigos session import [OPTIONS]

Options:
      --json  Print the JSON document (schema in core/README.md)
  -h, --help  Print help
```

#### bromigos session exec

```text
Import, then exec CMD with the session's values

Usage: bromigos session exec [OPTIONS] <CMD>...

Arguments:
  <CMD>...  

Options:
      --json  Print the JSON document (schema in core/README.md)
  -h, --help  Print help
```

#### bromigos session adopt

```text
At login: import, and stop VECTOR's daemon if it belongs to another session

Usage: bromigos session adopt [OPTIONS]

Options:
      --json  Print the JSON document (schema in core/README.md)
  -h, --help  Print help
```

#### bromigos session hold

```text
Hold Hyprland's config reloads: auto-reload off in every running Hyprland (as root, every user's), what it was remembered. pacman runs it before a transaction that changes the desktop's default config (docs/update.md)

Usage: bromigos session hold [OPTIONS]

Options:
      --json    Print the JSON document (schema in core/README.md)
      --pacman  As pacman's hook: quiet when no Hyprland runs, and a watcher releases what is still held if pacman exits without running the release hook
  -h, --help    Print help
```

#### bromigos session release

```text
Let go of a hold: each held Hyprland's config verified (Hyprland --verify-config), reloaded once when it verifies, auto-reload back as it was. pacman runs it after the transaction

Usage: bromigos session release [OPTIONS]

Options:
      --json    Print the JSON document (schema in core/README.md)
      --pacman  As pacman's hook: every running Hyprland gets the verified reload, held or not; quiet when none runs
  -h, --help    Print help
```

### bromigos settings

Settings: displays, sound, network, power, input, the desktop, VECTOR, updates, your account (SUPER+,).

```text
bromigos settings [PAGE[#SETTING]] | --list [--json] | --search WORDS [--json] | --render OUT.png [--page PAGE] [--size WxH] [--search WORDS] [--advanced] | --audit [--page PAGE]
```

For example:

```text
bromigos settings
bromigos settings sound
bromigos settings --search wifi
bromigos settings --list
```

From the `bromigos-desktop` package.

### bromigos setup

```text
The first-run questions (monitors, the AUR, hardware, accessibility, theme, VECTOR's brain and voice, homelab, where AI runs, the creation tools, peripheral modules); run again any time, or one section: `bromigos setup voice`. `bromigos setup homelab` detects your homelab's services (bromigos-homelab; --hosts, --url, --yes, --print)

Usage: bromigos setup [OPTIONS] [SECTION]

Arguments:
  [SECTION]  One section: monitors, aur, hardware, accessibility, theme, vector, voice, homelab, targets, create, peripherals (none: all)

Options:
      --answers <FILE>                 The answers from a file (TOML; docs/install.md) instead of asking
      --monitors <MONITORS>            Unattended answers: monitors auto|skip
      --aur <AUR>                      Unattended answers: the AUR (an AUR helper, AUR packages in bromigos update; bromigos aur) on|off
      --hardware <HARDWARE>            Unattended answers: the hardware (drivers, power profiles; bromigos hw setup) auto|skip
      --primary <PRIMARY>              Unattended answers: the primary output (the live background and the panels go on it)
      --order <ORDER>                  Unattended answers: outputs left to right, comma-separated (e.g. DP-2,DP-1)
      --scale <OUTPUT=SCALE>           Unattended answers: an output's scale, OUTPUT=SCALE (repeat for more)
      --refresh <OUTPUT=HZ>            Unattended answers: an output's refresh rate, OUTPUT=HZ (repeat for more)
      --targets <TARGETS>              Unattended answers: where AI runs, the targets in order, comma-separated (e.g. homelab,local; the cloud costs money: leave it out to never use it)
      --cloud-for <SERVICE>            Unattended answers: a service that may also use the cloud, last (e.g. video.loop; repeat for more)
      --create <CAPABILITY=PROVIDERS>  Unattended answers: a capability's providers in order, CAPABILITY=P1,P2 (e.g. image.generate=comfyui:local,nolgia; none: off), or `none` for every capability
      --nolgia-token-file <FILE>       Unattended answers: sign in to nolgia with the personal access token in FILE (stored 0600 for bromigos art, never printed)
      --motion <LEVEL>                 Unattended answers: how much the desktop moves: full, reduced or still (bromigos accessibility)
      --contrast <LEVEL>               Unattended answers: the colours' contrast: normal or high
      --theme <THEME>                  Unattended answers: the theme
      --den <DEN>                      Unattended answers: the Wick's den variant
      --vector <VECTOR>                Unattended answers: VECTOR's brain: ollama, openai or none
      --base-url <BASE_URL>            Unattended answers: the OpenAI-compatible server's base URL
      --api-key-file <API_KEY_FILE>    Unattended answers: a file holding its API key
      --model <MODEL>                  Unattended answers: the model
      --voice <VOICE>                  Unattended answers: VECTOR's voice: gpu, cpu or off
      --homelab <HOMELAB>              Unattended answers: a homelab.toml to use
      --peripheral <MODULE>            Unattended answers: turn a peripheral module on (e.g. razer-keyboard; repeat for more; bromigos peripheral list)
      --replace                        Replace an existing homelab.toml
      --json                           Print the JSON document (schema in core/README.md)
  -h, --help                           Print help
```

### bromigos setup config

Open one of your config files in the editor (Hyprland reloads safely after).

```text
bromigos setup config [NAME]
```

For example:

```text
bromigos setup config
bromigos setup config hyprland
```

From the `bromigos-desktop` package.

### bromigos setup homelab

Find the homelab's services and write ~/.config/bromigos/homelab.toml (re-runnable).

```text
bromigos setup homelab [--find [--ssh-config]] [--hosts H,H] [--url URL …] [--yes] [--print] [--json] …
```

For example:

```text
bromigos setup homelab
bromigos setup homelab --find
bromigos setup homelab --hosts nas,gpu-box
bromigos setup homelab --find --print
```

From the `bromigos-homelab` package.

### bromigos setup input

Keyboard layout, key repeat, the mouse and the touchpad, written to your hyprland.lua (a marked block).

```text
bromigos setup input [--set KEY VALUE …] [--unset KEY …] [--reset] [--show] [--layouts] [--json]
```

For example:

```text
bromigos setup input
bromigos setup input --set kb_layout us --set repeat_rate 50
bromigos setup input --json
```

From the `bromigos-desktop` package.

### bromigos setup keybindings

Every keybind, described, in a menu that runs the chosen one; EDIT opens yours (safe reload after).

```text
bromigos setup keybindings [--list|--edit]
```

For example:

```text
bromigos setup keybindings
bromigos setup keybindings --list
```

From the `bromigos-desktop` package.

### bromigos shell

Choose, configure, preview and diagnose the shell prompt.

```text
bromigos shell [status] | prompt mehshell|starship|none [--json] | doctor [--json] [--timings] | preview [--width N] [--style STYLE] | configure KEY VALUE
```

For example:

```text
bromigos shell prompt mehshell
bromigos shell doctor
bromigos shell preview --width 40
bromigos shell configure brand bromigos
```

From the `bromigos-desktop` package.

### bromigos shot

Screenshot to ~/Pictures/screenshots and the clipboard.

```text
bromigos shot [region|screen]
```

From the `bromigos-desktop` package.

### bromigos sound

Sound: the output and input device, their volumes, each app's volume, the theme's sounds and the desktop's mute.

```text
bromigos sound [status] | output|input DEVICE | volume output|input|DEVICE PERCENT | mute output|input on|off|toggle | app-volume ID PERCENT | app-mute ID on|off | app-output ID DEVICE | port output|input DEVICE PORT | all-mute on|off|toggle | sounds on|off | sounds-volume PERCENT | test [DEVICE] | popup [pin|hover X|leave|close]  [--json]
```

For example:

```text
bromigos sound
bromigos sound volume output 40
bromigos sound output alsa_output.usb-headset
bromigos sound app-volume 79 50
```

From the `bromigos-desktop` package.

### bromigos splash

Configure graphical shutdown and restart on GRUB systems.

```text
bromigos splash status [--json] | on | off
```

For example:

```text
bromigos splash status
sudo bromigos splash on
sudo bromigos splash off
```

From the `bromigos-core` package.

### bromigos startup

What starts at login: bromigOS's own, yours (a marked block in your hyprland.lua), and the floating windows put back where they were.

```text
bromigos startup [status] | add COMMAND… [--name NAME] | add --app APP | remove N|COMMAND | windows remember|forget-class CLASS | windows all on|off | windows clear [CLASS…] | windows restart | reset  [--json]
```

For example:

```text
bromigos startup
bromigos startup add --app org.keepassxc.KeePassXC.desktop
bromigos startup add syncthing --name Syncthing
bromigos startup windows remember pavucontrol
```

From the `bromigos-desktop` package.

### bromigos status

```text
The live layer, VECTOR, the session and the animations

Usage: bromigos status [OPTIONS]

Options:
      --json  Print the JSON document (schema in core/README.md)
  -h, --help  Print help
```

### bromigos storage

Inspect drives, migrate data and clean selected caches, originals or snapshots.

```text
bromigos storage status [--json] | plan --device DEVICE --mount PATH [--roles LIST] [--json] | apply PLAN | migrate plan|run|resume|verify|status … | switch PLAN --writers-stopped | cleanup [--preview] [--json] | cleanup plan [--cache NAME] [--keep-versions N] [--migration PLAN] [--snapshot PATH] [--json] | cleanup apply PLAN [--yes] | cleanup status PLAN [--json]
```

For example:

```text
bromigos storage status
bromigos storage cleanup --preview
bromigos storage migrate plan --source /path/to/data --destination /mnt/Work/data --keep-path /path/to/data
```

From the `bromigos-core` package.

### bromigos target

```text
Where AI work runs: homelab, local or cloud, per service (art, VECTOR's voice and brain); show it, probe it, switch it (`bromigos target local`)

Usage: bromigos target [OPTIONS] [WORDS]...

Arguments:
  [WORDS]...  show, check, probe [SERVICE…], homelab, local, cloud, order T…, reset, resolve SERVICE

Options:
      --only <SERVICE>  Only these services (repeat), for homelab|local|cloud, order and reset
      --exclusive       With homelab|local|cloud: that target alone, no fallback
      --json            Print the JSON document
  -h, --help            Print help

Words:
  (none), show          each service, what it would use now, and whether that answers
  check                 every target of every service, probed
  probe [SERVICE…]      the same for these services (a ComfyUI: its workflow's models, its VRAM)
  homelab|local|cloud   put that target first (the cloud is never added by another one)
  order T [T…]          the exact order, e.g. `order homelab local`
  reset                 services follow the global order again
  resolve SERVICE       what SERVICE tries, in order (JSON; for VECTOR; no probing)

Services: image.generate image.edit image.cutout image.upscale video.loop video.upscale
model3d.generate voice.tts voice.stt llm. Your file: ~/.config/bromigos/targets.toml (docs/targets.md).
```

### bromigos theme

```text
The look: list the themes, show the current one, set one (renders every app's colours)

Usage: bromigos theme [OPTIONS] [COMMAND]

Commands:
  list     Every theme, first-party and the user's (the default verb)
  current  The theme in force (the default, wick, when none was set)
  set      Render NAME (default: the current theme) into ~/.local/state/bromigos/theme/current and tell the running apps
  install  Install a theme from a git URL, a folder or the catalog: `bromigos ext install` (a git checkout that `bromigos ext update` updates)
  remove   Remove a theme: an extension's (`bromigos ext remove`) or one of yours (never a first-party one, never the one in force)
  new      A new theme to make your own, as an extension in ./NAME: from the starter, or a copy of an installed theme (--from)
  help     Print this message or the help of the given subcommand(s)

Options:
      --json  Print the JSON document (schema in core/README.md)
  -h, --help  Print help
```

#### bromigos theme list

```text
Every theme, first-party and the user's (the default verb)

Usage: bromigos theme list [OPTIONS]

Options:
      --json  Print the JSON document (schema in core/README.md)
  -h, --help  Print help
```

#### bromigos theme current

```text
The theme in force (the default, wick, when none was set)

Usage: bromigos theme current [OPTIONS]

Options:
      --json  Print the JSON document (schema in core/README.md)
  -h, --help  Print help
```

#### bromigos theme set

```text
Render NAME (default: the current theme) into ~/.local/state/bromigos/theme/current and tell the running apps

Usage: bromigos theme set [OPTIONS] [NAME]

Arguments:
  [NAME]  

Options:
      --json       Print the JSON document (schema in core/README.md)
      --no-reload  Don't signal waybar, kitty, Hyprland or dunst
  -h, --help       Print help
```

#### bromigos theme install

```text
Install a theme from a git URL, a folder or the catalog: `bromigos ext install` (a git checkout that `bromigos ext update` updates)

Usage: bromigos theme install [OPTIONS] <SOURCE>

Arguments:
  <SOURCE>  

Options:
      --json         Print the JSON document (schema in core/README.md)
      --name <NAME>  A theme repository without a manifest: the name to install it as
      --force        A theme of yours with the same name: move it aside and install this one
  -h, --help         Print help
```

#### bromigos theme remove

```text
Remove a theme: an extension's (`bromigos ext remove`) or one of yours (never a first-party one, never the one in force)

Usage: bromigos theme remove [OPTIONS] <NAME>

Arguments:
  <NAME>  

Options:
      --json  Print the JSON document (schema in core/README.md)
  -h, --help  Print help
```

#### bromigos theme new

```text
A new theme to make your own, as an extension in ./NAME: from the starter, or a copy of an installed theme (--from)

Usage: bromigos theme new [OPTIONS] <NAME>

Arguments:
  <NAME>  

Options:
      --from <FROM>  The theme to start from (bromigos theme list)
      --json         Print the JSON document (schema in core/README.md)
      --dir <DIR>    Where (default ./NAME)
  -h, --help         Print help
```

### bromigos theme previews

Draw the theme switcher's previews: each theme as a miniature screenshot of the desktop wearing it.

```text
bromigos theme previews [NAME…] [--force] [--list] [--json] [--quiet] | [NAME | --dir DIR [--name NAME]] [--size WxH] [--panels LIST | --scene FILE] --out FILE
```

For example:

```text
bromigos theme previews
bromigos theme previews mire --force
bromigos theme previews --list
bromigos theme previews wick --size 2560x1440 --panels system,network,weather,lab --out wick.png
```

From the `bromigos-desktop` package.

### bromigos theme switcher

Customize: themes from previews of the desktop wearing them, and the widget gallery (SUPER+CTRL+SHIFT+SPACE).

```text
bromigos theme switcher [--tab themes|widgets] [--save-layout] [--list [--json]] [--render [NAME…]] [--screenshot OUT.png --size WxH [--tab TAB] [--select NAME] [--filter TEXT]]
```

For example:

```text
bromigos theme switcher
bromigos theme switcher --list
bromigos theme previews
```

From the `bromigos-desktop` package.

### bromigos tv guide



```text
bromigos tv guide
```

From the `bromigos-desktop` package.

### bromigos update

```text
Update everything: packages (sudo pacman -Syu, then AUR packages with paru), then migrations, the theme, and restarts of whatever runs older code than is installed

Usage: bromigos update [OPTIONS]

Options:
      --check             Only say what it would do: upgrades waiting, migrations pending, restarts needed, how updates are snapshotted, the updates that can be rolled back
      --no-packages       Skip the package step (migrations, the theme and restarts only)
      --rollback [<PRE>]  Undo an update: every file / had before it comes back (snapper undochange on the pre/post pair around it), after a summary and a question. PRE picks an older one. In a snapshot started from the boot menu: that snapshot becomes the root
      --yes               Don't ask: pacman takes its defaults, the AUR step builds without paru's review of each recipe (docs/aur.md), and a rollback goes ahead without a question
      --no-aur            Leave AUR packages alone this time (`bromigos aur off`: every time)
      --downgrade         Allow downgrades (pacman -Syuu): after a move to an older channel
      --channel <NAME>    Follow this channel from now on (stable, rc, edge, dev), then update
      --json              Print the JSON document (schema in core/README.md)
  -h, --help              Print help
```

### bromigos vector

```text
VECTOR (any bromigos-holo command: off, on, vector, ask, status, mute, …)

Usage: bromigos vector [ARGS]...

Arguments:
  [ARGS]...
```

### bromigos wallpaper

```text
The den wallpaper (any bromigos-wallpaper command)

Usage: bromigos wallpaper [ARGS]...

Arguments:
  [ARGS]...
```

```text
bromigos wallpaper den|empty|masked|v1|next|previous|list [--json]|apply|outputs|status
```

From the `bromigos-desktop` package.

### bromigos webapp

Web apps: a site as its own frameless window, in the launcher, with a hotkey.

```text
bromigos webapp add NAME URL [--icon FILE|URL] [--hotkey "SUPER + SHIFT + X"] | add --from-catalog NAME | remove NAME | list | launch NAME | catalog
```

For example:

```text
bromigos webapp add gmail https://mail.google.com --hotkey "SUPER + SHIFT + G"
bromigos webapp list
```

From the `bromigos-desktop` package.

### bromigos welcome

The welcome tour after an install: Wi-Fi, your screens, a world, VECTOR and his voice, your homelab, the keys; every step skippable.

```text
bromigos welcome [--if-pending] [--step STEP] [--render DIR]
```

For example:

```text
bromigos welcome
bromigos welcome --step world
```

From the `bromigos-desktop` package.

### bromigos welcome console

The welcome tour in the terminal (bromigOS Server's first sign-in): the network, SSH, joining your lab, and what's here.

```text
bromigos welcome console [--if-pending] [--render DIR [--size WxH]]
```

For example:

```text
bromigos welcome-console
```

From the `bromigos-core` package.

### bromigos whats-new

```text
What's new in this release of bromigOS: the release notes installed with it (they read offline; the manual's "What's new" page)

Usage: bromigos whats-new [OPTIONS] [RELEASE]

Arguments:
  [RELEASE]  A release's notes (e.g. 0.1.2); the newest by default

Options:
      --all   Every release's notes, newest first
  -h, --help  Print help
```

### bromigos whoami

Show who's signed in to a Bromigos account here, and how.

```text
bromigos whoami [--json]
```

For example:

```text
bromigos whoami
```

From the `bromigos-core` package.

### bromigos widgets

The desktop panels: run them (login does), show or hide one or all, edit mode, type in the notes.

```text
bromigos widgets [toggle NAME|all | show NAME|all | add NAME | edit [on|done|cancel] | notes | reload | gallery [--previews DIR]]
```

From the `bromigos-widgets` package.

### bromigos windows

Remember floating windows' positions per workspace and app, and put them back.

```text
bromigos windows [run | list | clear [CLASS…] | forget WORKSPACE CLASS]
```

For example:

```text
bromigos windows list
bromigos windows clear pavucontrol
bromigos windows clear
```

From the `bromigos-desktop` package.

### bromigos wol

Keep Wake-on-LAN on for wired network cards.

```text
bromigos wol status [--json] | apply [--quiet] [CARD...]
```

For example:

```text
bromigos wol status
sudo bromigos wol apply
```

From the `bromigos-core` package.

<!-- /generated:commands -->

## Your own commands

Any program named `bromigos-<group>-<name>` on your `PATH` becomes a `bromigos` command:
`bromigos <group> <name>`. It shows up in `bromigos commands` and in the menu's COMMANDS
group.

1. Make a file in a folder on your `PATH`, such as
   `~/.local/bin/bromigos-toggle-nightlight`.
2. Describe it in a comment block at the top:

   ```sh
   #!/bin/sh
   # bromigos:summary=Toggle the night light
   # bromigos:args=[on|off]
   # bromigos:examples=bromigos toggle nightlight on
   ```

3. Make it executable with `chmod +x`, and run it as `bromigos toggle nightlight`.

To share a command, make it an [extension](extensions.md#make-your-own).
