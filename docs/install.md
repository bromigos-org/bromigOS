# Installing bromigOS

bromigOS installs on a plain Arch Linux system as a set of signed pacman packages from its
own repository. A short script, `install.sh`, adds the repository. Then `bromigos install`
installs and sets up the desktop, and `bromigos setup` asks the first-run questions.

This page explains each step, its options and its files, for contributors. For users,
the manual's [Install](../manual/src/install.md) page is shorter. To install from the
ISO instead, see [iso.md](iso.md): its graphical and text installers (Erase, Install
alongside Windows, Reinstall keeping files; the desktop or bromigOS Server) end by running
the same `bromigos install` and `bromigos setup` described here, in the new system. Users'
guide: [The installer](../manual/src/installer.md).

## Standalone lab package

`bromigos-lab` runs on plain Arch without `bromigos-core`. Its AUR recipe builds from
an immutable source release and verifies a SHA-256 checksum. The release workflow
installs that exact archive in a clean Arch container before pushing to the AUR.
Users can follow [the standalone console instructions](../manual/src/lab.md#install-on-plain-arch).
The [package split and release gate](lab-package.md) explain ownership and testing.

## Before you start

You need:

- **Arch Linux,** freshly installed, with a user who can use `sudo` and a working network.
  archinstall's minimal profile is enough.
- **Another repository, if you use one.** By default `install.sh` installs from the
  public repository, `https://pkgs.bromigos.org`. A mirror of your own is written `<repo>` below. If its TLS
  certificate is signed by its own certificate authority, pass that certificate with
  `--ca`.

## Install

Signed in as your own user, not root, download the script, read it, then run it:

```bash
curl -fsSLO https://pkgs.bromigos.org/bromigos/install.sh
less install.sh
bash install.sh
```

From another repository, download the script from it and add `--repo <repo>`, and
`--ca <ca.pem>` if it has its own certificate authority. Then `curl` needs the certificate
too: add `--cacert <ca.pem>` to the first command.

When it's done, reboot and sign in at the Bromigos login screen.

Piping the script straight into bash works too:
`curl -fsSL https://pkgs.bromigos.org/bromigos/install.sh | bash`. It asks its questions
on the terminal, not the pipe. With no terminal at all, such as `ssh` without `-t`, it
stops unless you add `--yes`. Then it installs unattended, and `bromigos setup` asks the
first-run questions after you sign in.

| `install.sh` option | What it does |
|---|---|
| `--repo URL` | The package repository's base URL, or set `BROMIGOS_REPO_URL`. The default is the public repository, `https://pkgs.bromigos.org`. |
| `--ca FILE` or `--ca URL` | A CA certificate to trust for the repository's TLS |
| `--channel NAME` | `stable` (the default), `rc` or `edge`. See [update.md](update.md#channels). |
| `--aur-route` | Print the alternative AUR bootstrap steps and exit. |
| `--dry-run` | Says what it would do, and changes nothing |
| anything else | Passed on to `bromigos install`, such as `--with herdr`. `--yes` also stops pacman from asking. |

Everything is logged to `~/.local/state/bromigos/install.log`. Running it again is safe.

## What install.sh does

`install.sh` is about eighty lines long, so you can read it before you run it. In order,
it:

1. Refuses to run as root, and checks that pacman is there.
2. Reads its answers from the terminal (`/dev/tty`) when its input isn't one, as when it's
   piped into bash. The script is one function called on its last line, so bash has read
   all of it before anything runs, and pacman never reads the script as its answers. With
   no terminal at all, it goes on only with `--yes` or `--dry-run`.
3. Trusts the repository's CA certificate, if you gave `--ca`.
4. Downloads the repository's public key from `<repo>/bromigos/bromigos.asc`. It refuses
   the key unless its fingerprint is the one written into the script,
   `393E7D54F7DE58FE75B97214947C9D6193D3DD8B`. Then it adds the key with
   `pacman-key --add` and signs it locally with `--lsign-key`.
5. Adds a `[bromigos]` section to `/etc/pacman.conf`, with
   `SigLevel = Required DatabaseOptional`.
6. Runs `sudo pacman -Syu bromigos-keyring bromigos-core`. It always upgrades the whole
   system, never part of it.
7. Hands over to `bromigos install`, with the rest of its arguments.

<!-- site:install-steps -->
## What bromigos install does

`bromigos install` is the installer itself, written in Rust
(`core/crates/bromigos-core/src/install.rs`). It runs these steps in order:

| Step | What it does |
|---|---|
| preflight | Checks for a regular user with sudo, on Arch, with the `[bromigos]` repository |
| packages | Installs the `bromigos` package and any `--with` extras |
| aur | Installs paru, the AUR helper, unless the AUR is off or a helper is already installed |
| services | Enables networking, the login screen, Bluetooth and PipeWire |
| rollback | Sets up update snapshots, where `/` is btrfs |
| hardware | Installs and configures the graphics drivers and laptop power tools |
| configs | Runs the pending migrations, which create your config files |
| desktop settings | Sets the GTK theme, icons, cursor, font and dark mode |
| theme | Renders the theme |
| boot menu | Turns on bromigOS's GRUB theme, where GRUB boots the machine |

Then it runs `bromigos setup`, unless you gave `--no-setup`.

### The steps in detail

- **packages** runs `sudo pacman -S --needed bromigos`, plus each `--with` package. Some
  files from an older hand install aren't owned by any package: the SDDM theme, and the
  icon and cursor themes. Those are overwritten by name, and nothing else is.
- **aur** runs `bromigos aur ensure`, which installs paru with `sudo pacman -S --needed
  paru`. paru comes from bromigOS's own repository, never from the AUR
  ([aur.md](aur.md)).
  - It skips paru where paru or yay is already installed, or where a package provides
    `paru`, such as paru-bin or paru-git.
  - `--no-aur`, or `[aur] mode = "off"` in the answers file, turns the AUR off before
    anything is installed. Then paru never is.
  - If paru can't be installed, the step says so and the install carries on. That happens
    when the repository is unreachable, or on an install medium whose offline copy doesn't
    carry paru, as the ISO's doesn't yet. The migration `20261009235000-aur-helper`
    installs it on the next update.
- **services** enables, but doesn't start, these services. They come up at the next boot.
  - NetworkManager, unless another network manager is already enabled:
    systemd-networkd, iwd, connman, dhcpcd, netctl or wicd.
  - SDDM, unless another display manager is enabled. `--force-dm` switches to SDDM
    anyway.
  - Bluetooth, when bluez is installed.
  - PipeWire, its PulseAudio socket and WirePlumber, for your user.
- **rollback** sets up snapper, snap-pac and the boot menu's snapshots (grub-btrfs on
  GRUB), as `bromigos rollback setup` does ([update.md](update.md#snapshots)). Where `/`
  isn't btrfs, it says why it can't. `--no-services` skips it.
- **hardware** runs `bromigos hw setup` ([hardware.md](hardware.md)). That covers the GPU's
  drivers, NVIDIA's early KMS, a hybrid laptop's render GPU, a laptop's `brightnessctl`
  and `power-profiles-daemon`, and Hyprland's GPU settings. It never swaps an NVIDIA
  driver that's already installed. If it fails, the install reports it and carries on.
  `--no-hardware` skips it.
- **configs** runs the pending migrations. They create the small config files in
  `~/.config` that load bromigOS's defaults: Hyprland, the bar, rofi, dunst, hypridle,
  hyprlock and gtklock. They only create a file where you don't have one.
- **desktop settings** sets the GTK theme, icons, cursor, UI font and dark preference
  through gsettings. It only changes a setting that's still GNOME's default.
- **theme** renders the current theme again, or `--theme` (default `wick`) when no theme
  is set yet.
- **boot menu** turns on the GRUB theme ([boot.md](boot.md)), unless you turned it off
  with `bromigos boot theme off`.

### bromigos install options

| Option | What it does |
|---|---|
| `--with PACKAGE` | Installs an optional package too, such as `bromigos-apps` or `herdr`. Repeat it for more. |
| `--yes` | Answers pacman's questions with their defaults, for unattended installs |
| `--no-services` | Leaves services alone, and skips the rollback step |
| `--force-dm` | Enables SDDM even when another display manager is enabled |
| `--theme THEME` | The theme to use when none is set yet. The default is `wick`. |
| `--no-hardware` | Leaves drivers and power settings for `bromigos hw setup` later |
| `--no-aur` | Installs no AUR helper, and `bromigos update` leaves the AUR alone. `bromigos aur on` changes it later. |
| `--no-setup` | Doesn't run `bromigos setup` afterwards |
| `--answers FILE` | Gives `bromigos setup` its answers from a file, below |
| `--dry-run` | Says what it would do |
| `--json` | Prints the result as JSON ([core/README.md](../core/README.md)) |

### The packages

<!-- generated:packages (tools/docs/generate.py; don't edit by hand) -->

| Package | What it is | Installed |
|---|---|---|
| `bromigos` | bromigOS: holograms, homelab integrations, living themes and widgets on Arch and Hyprland | the one to install: everything below marked *with bromigOS* |
| `bromigos-keyring` | bromigOS package-signing key for pacman | *with bromigOS* |
| `bromigos-core` | bromigos: one command for the bromigOS desktop | *with bromigOS* |
| `bromigos-desktop` | bromigOS desktop: default configs for Hyprland, waybar, rofi, dunst, gtklock and hypridle, and their tools | *with bromigOS* |
| `bromigos-settings` | bromigOS system settings: the login screen, the boot splash, the GTK, icon and cursor themes, the fonts | *with bromigOS* |
| `bromigos-live` | bromigOS live layer: the animated, data-reactive background, its worlds and decks | *with bromigOS* |
| `bromigos-widgets` | bromigOS desktop widgets: system, network, storage, workbench, notes and shortcuts panels | *with bromigOS* |
| `bromigos-vector` | VECTOR, the desktop's caretaker, and the hologram renderer he lives in (from the `vector` repository) | *with bromigOS* |
| `bromigos-manual` | bromigOS manual: how to use the desktop, as HTML, for reading offline | *with bromigOS* |
| `bromigos-mirrorlist` | bromigOS package repository mirrors | *with bromigOS* (through `bromigos-keyring`) |
| `bromigos-homelab` | bromigOS homelab integrations: desktop panels, homelab decks and VECTOR tools | *with bromigOS* (through `bromigos-desktop`) |
| `bromigos-bar-hover` | bromigOS bar hover popups: a waybar module that opens a popup when the pointer rests on another | *with bromigOS* (through `bromigos-desktop`) |
| `mehshell` | Fast parallel zsh prompt engine for bromigOS | *with bromigOS* (through `bromigos-desktop`) |
| `oo7` | A Secret Service provider | *with bromigOS* (through `bromigos-desktop`) |
| `bromigos-boot` | bromigOS boot menu and text console: the GRUB theme, advanced boot options, the Field Kit entry, the console font and colours | *with bromigOS* (through `bromigos-settings`) |
| `ttf-geist-mono` | Geist Mono, a monospaced typeface by Vercel | *with bromigOS* (through `bromigos-settings`) |
| `bromigos-lab` | Standalone homelab console, adapters, model catalog and reviewed provisioning | *with bromigOS* (through `bromigos-homelab`) |
| `bromigos-lab-catalog` | bromigOS lab model catalog: the best open models per AI capability and GPU size, with licences | *with bromigOS* (through `bromigos-homelab`) |
| `bromigos-apps` | bromigOS app bundle: LazyVim, tmux, lazygit, mise (bromigos-apps-terminal), Chromium, Spotify and Signal, configured and themed | optional: `bromigos install --with bromigos-apps` |
| `herdr` | Terminal workspace manager for AI coding agents | optional: `bromigos install --with herdr` |
| `paru` | Feature packed AUR helper | by `bromigos install` (its `aur` step), unless `--no-aur` or `bromigos setup aur` leaves it out |
| `1password` | Password manager and secure wallet | optional, for `bromigos-apps` |
| `bromigos-secureboot` | bromigOS on Secure Boot: shim, a GRUB built and signed on the computer, kernels signed after every update | by the installer, on a computer that starts the newer way (UEFI); elsewhere by `sudo pacman -S bromigos-secureboot` (docs/secureboot.md) |
| `bromigos-apps-terminal` | bromigOS app bundle, terminal half: LazyVim, tmux, lazygit and mise, configured and themed (no desktop needed) | with `bromigos-apps`, `bromigos-server` |
| `bromigos-fieldkit-tools` | bromigOS Field Kit engine: repair an install (black screen, last boot, rollback, boot menu, disks, backups), the stick and remote help | with `bromigos-server` |
| `bromigos-server` | bromigOS Server: bromigOS without a desktop for servers and lab machines (SSH, firewall, safe automatic updates, containers, the lab) | on its own |
| `dislocker` | Read BitLocker-encrypted volumes (FUSE) | on its own |
| `nwipe` | Securely erase disks using a variety of recognised methods (a fork of dwipe) | on its own |
| `xpadneo-dkms` | Advanced Linux Driver for Xbox One Wireless Gamepad | by `bromigos peripheral enable xbox-controller`, for an Xbox controller |

`herdr`, `ttf-geist-mono`, `1password`, `paru` and `xpadneo-dkms` aren't in Arch's own repositories, so bromigOS packages them into its own, each pinned by checksum. Only `1password` needs the AUR, and only on a public install (below).

- `herdr`, `paru` and `xpadneo-dkms` are built from their upstream source.
- `ttf-geist-mono` packages the fonts from Geist's release.
- `1password` repackages 1Password's own Linux download. It isn't built from source. Its licence is proprietary, so the public mirror leaves it out: there, `bromigos install --with 1password` gets it from the AUR with paru.

`oo7`, the keyring, is in Arch's repositories too, but Arch's version can't unlock it at a text console login. bromigOS builds a newer one from upstream's source, until Arch's catches up.

<!-- /generated:packages -->

**BRODEC (optional):** `sudo pacman -S brodec-desktop`. BRODEC is a separate Bromigos
product, an end-to-end encrypted messenger. Its desktop app is in the bromigOS package
repository, but it isn't installed by default. Once you install it, system updates keep
it current. It keeps its sign-in in your [keyring](bromigos-account.md#the-keyring), as bromigOS
does.

BRODEC's lab bridge is optional too: `sudo pacman -S brodec-lab` lets this machine report
to your BRODEC account as your lab. It only reads. Nothing starts until you run
`sudo systemctl enable --now brodec-lab`, then `sudo brodec-lab pair`, and scan the code it
shows in BRODEC.

## bromigos setup

`bromigos setup` asks the first-run questions, one page per section. You can run it again
any time, whole or one section at a time:

```bash
bromigos setup            # every section
bromigos setup voice      # just one
```

| Section | What it asks | Where the answer goes |
|---|---|---|
| monitors | Your screens: the main one, their order from left to right, each one's scale and refresh rate | A block in `~/.config/hypr/hyprland.lua`, and the main screen in `~/.config/bromigos/monitors.toml` |
| aur | Whether to keep an AUR helper and update AUR packages with `bromigos update` | `~/.config/bromigos/aur.toml` ([aur.md](aur.md)). "Off" removes the paru the install added. |
| hardware | Whether to set up what `bromigos hw` found now | `bromigos hw setup` ([hardware.md](hardware.md)) |
| accessibility | How much the desktop moves, and its contrast | `~/.config/bromigos/accessibility.toml` ([accessibility.md](accessibility.md)) |
| theme | The theme, and for the Wick, which den wallpaper | `bromigos theme set` and `bromigos wallpaper` |
| vector | VECTOR's brain: a local Ollama, any OpenAI-compatible server, or none yet | `~/.config/bromigos/vector/vector.toml`, its `[llm]` table |
| voice | VECTOR's voice: `gpu`, `cpu` or `off` | Installs the voice, or turns it off |
| homelab | Your homelab's services | `~/.config/bromigos/homelab.toml` ([homelab.md](homelab.md)) |
| targets | Where AI work runs: your homelab, this machine, the cloud, in order | `~/.config/bromigos/targets.toml` ([targets.md](targets.md)) |
| create | Which tools make images, video loops and 3D models | `~/.config/bromigos/create.toml` ([art.md](art.md)) |
| peripherals | Which optional device modules to turn on | `~/.config/bromigos/peripherals.toml` ([peripherals.md](peripherals.md)) |

*VECTOR* is the desktop's AI assistant. Setup merges its answers into your existing files,
so your other keys and comments stay. More about some sections:

- **monitors.** Setup finds your screens, with their names, makes, models, modes and
  physical sizes. The default scale comes from each screen's pixel density. Running it
  again replaces the block. A screen that isn't in the block still lights up on its own
  ([desktop.md](desktop.md)).
- **accessibility** comes before the theme, because the theme renders with it. It has two
  pages: motion (`full`, `reduced` or `still`) and contrast (`normal` or `high`).
- **voice.** `gpu` is VECTOR's designed voice. `cpu` is Kokoro, a voice that runs on the
  CPU. `off` mutes him. Setup runs `bromigos-holo setup voice` or `voice-cpu` to install
  the voice.
- **homelab** never overwrites your `homelab.toml` unless you pass `--replace`. Its
  Find my lab answer (`find = true`) runs `bromigos setup homelab --find` after the
  questions. That asks before it reads anything, so it needs a terminal. The USB stick's
  answers leave the homelab out, so it stays Skip.
- **targets.** Setup looks for a `homelab.toml` with AI services, a GPU on this machine,
  and a nolgia sign-in. The default is your homelab first, then this machine, and never
  the cloud. You can allow the cloud for video loops alone.
- **create.** By default the creation tools follow where AI runs, so `bromigos target`
  moves them too. Or you can pin each capability (`image.generate`, `image.edit`,
  `image.cutout`, `video.loop`, `model3d.generate`) to its own list of providers.
  - A ComfyUI is offered only where it has a shipped workflow's models. Setup looks for
    one on this machine at `127.0.0.1:8188`, a `comfyui` source in `homelab.toml`, or
    `BROMIGOS_COMFYUI_URL`.
  - nolgia is a cloud service that costs credits. Signing in runs `nolgia auth login`. An
    unattended install can pass a personal access token in a file instead. It's stored
    with mode 0600 in `~/.local/share/bromigos/nolgia-token`, for `bromigos art`, and
    never printed.
- **peripherals** is only asked when such a device is connected. Today that's a Razer
  keyboard: its macro keys, its dial as VECTOR's voice dial, and lighting that follows
  him. Turning a module on does what `bromigos peripheral enable` does.

What you answered is kept in `~/.local/state/bromigos/setup.toml`.

### Unattended setup

For an unattended run, give the answers in a file with `--answers FILE`:

```toml
[monitors]
mode = "auto"            # or "skip"
primary = "DP-1"         # optional, like every key below it
order = ["DP-2", "DP-1"] # left to right
scale = { "DP-1" = 1.25 }
refresh = { "DP-2" = 144 }

[aur]
mode = "on"              # or "off": no AUR helper; bromigos install reads it first

[hardware]
mode = "auto"            # runs bromigos hw setup; "skip" leaves it

[accessibility]          # leave either out to keep it as it is
motion = "reduced"       # "full", "reduced" or "still"
contrast = "high"        # "normal" or "high"

[theme]
name = "wick"
den = "empty"            # optional: the Wick's den wallpaper

[vector]
backend = "openai"       # "ollama", "openai" or "none"
base_url = "https://models.example/v1"
api_key_file = "/home/me/.config/bromigos/vector/key"
model = "qwen3"

[voice]
tier = "off"             # "gpu", "cpu" or "off"

[homelab]
file = "/home/me/homelab.toml"   # or find = true: Find my lab, which asks in the terminal

[targets]
order = ["homelab", "local"]   # leave "cloud" out to never use it
cloud_for = ["video.loop"]     # optional: services that may use the cloud last

[create]
nolgia_token_file = "/home/me/nolgia-token"   # optional: sign in to nolgia unattended

[create.providers]       # a capability's providers, in order
"image.generate" = ["comfyui:local", "nolgia"]
"video.loop" = ["nolgia"]
"model3d.generate" = ["none"]

[peripherals]            # peripheral modules (peripherals.md)
enable = ["razer-keyboard"]
disable = []
force = false            # true: turn it on even when the device isn't connected
system = true            # false: only the choice and keys, no packages, groups or services
```

The file is strict. A misspelled section or key is an error, not silently ignored.

Or use flags. Each section has its own, and `bromigos setup --help` lists them all:

```bash
bromigos setup --monitors auto --primary DP-1 --aur on --hardware auto --motion reduced \
    --contrast high --theme mire --vector ollama --voice off \
    --create image.generate=comfyui:local,nolgia --peripheral razer-keyboard
```

`--create none` turns every capability off.

## The fresh-machine test

`test/vm/arch-vm.sh` installs bromigOS on a new virtual machine and checks the result. It
runs on any machine with KVM and about 8 GiB of memory to spare.

```bash
test/vm/arch-vm.sh up --repo <repo> --ca <ca.pem>   # a new VM from Arch's cloud image
test/vm/arch-vm.sh install                          # install.sh with test/vm/answers.toml
test/vm/arch-vm.sh check                            # runs test/vm/checks.sh in the VM
test/vm/arch-vm.sh reboot
test/vm/arch-vm.sh shot login                       # a screenshot of the login screen
test/vm/arch-vm.sh destroy
```

| Option or command | What it does |
|---|---|
| `up --hosts "<ip> <name>"` | Adds the repository's host to the VM's `/etc/hosts`, when DNS doesn't reach it |
| `up --heads 2` | Gives the VM two screens |
| `install --channel edge` | Installs from another channel |
| `shot NAME [N]` | Saves a screenshot of screen N to `~/.cache/bromigos-vmtest/shots/` |
| `down` | Powers the VM off, keeping its disk |

To test two screens with the same install, run `down`, then `up --heads 2`, then
`shot left 0` and `shot right 1`. To test plugging a screen in, run
`hyprctl output create headless TEST-1` inside the session, then
`hyprctl output remove TEST-1`.

The VM uses Arch's official cloud image, checked against its checksum, with a 40 GB
overlay disk, 6 GB of memory, 4 CPUs and virtio-gpu. It runs headless. Screenshots come
through QEMU's monitor, and it never opens a window on the host.

The VM stops when the session that started it ends. QEMU runs under
`test/vm/vm-keeper.py`, which watches the *owner*: the terminal's shell, or whatever ran
the commands. When the owner exits, the keeper stops QEMU. If the keeper itself is
killed, the kernel stops QEMU (`PR_SET_PDEATHSIG`). Before this, a VM whose session was
killed ran on for 45 minutes, holding 5 GB.

- `BROMIGOS_VM_OWNER=<pid>` ties the VM to another process.
- `BROMIGOS_VM_OWNER=none` keeps it running until `down`, as before.
- `<dir>/keeper.log` says who the owner is, and why the VM stopped.
- `test/vm/keeper-test.sh` checks the keeper with an empty QEMU.

`test/vm/` also has end-to-end tests that run inside the VM: `hypr-hold-e2e.sh`
([update.md](update.md#hyprland-during-a-package-transaction)), `idle-e2e.sh` and
`settings-e2e.sh`.

### What CI checks

`.github/workflows/install-smoke.yml` runs on every change to the installer:

- shellcheck on `install.sh`;
- `install.sh --dry-run` as a regular user, in a fresh Arch container, against a stand-in
  repository with the real key;
- the same, piped into bash, with a terminal and without one, and a real install piped
  with no terminal, which must stop before it changes anything;
- a check that a wrong key is refused.

> **Planned.** The full VM test isn't in CI yet. It needs a runner with KVM (`/dev/kvm`
> passed to the job's container, or a KVM device plugin) and about 8 GiB of memory for
> one run. That's more than the current shared runners have to spare. When a runner has
> the room, a `vm-test` job will run it on manual dispatch and on release tags, not on
> every push. The ISO's QEMU test ([iso.md](iso.md#testing-it)) needs the same.

## Test runs

Newest first.

### 2026-10-09, 11:15 to 11:30 Pacific: install.sh piped and downloaded

A fresh Arch container (`archlinux:base`) per run, against the real repository on
`stable`, with a stand-in `bromigos` that says whether its input is a terminal. A
pseudo-terminal answered pacman's question with `y`.

| Form | Result |
|---|---|
| Downloaded, then `bash install.sh`, on a terminal | pacman asked on the terminal; `bromigos-core` installed; the handover had a terminal |
| Piped, on a terminal | The same |
| Piped, on a terminal, the old script | pacman read the line `if ((dry)) && ! command -v brom…` as its answer and stopped; nothing installed |
| Piped, no terminal | Stopped at once: "no terminal to ask on", exit 2, nothing changed |
| Piped, no terminal, `--yes` | Unattended: pacman didn't ask, and `bromigos install --yes` ran without a terminal |
| Piped, no terminal, `--dry-run --ca` | Every step said what it would do. The key was fetched trusting the CA for that request only. |

### 2026-10-09: pass, 43 of 43, with the live layer's fixes

`install.sh --channel edge` on a fresh Arch cloud image (core r99, desktop r54, live r22,
vector r30), at 1280x800. `checks.sh` passed 43 of 43 after the install, and again in the
signed-in desktop.

- The shortcut picker's three checks ran for the first time: `bromigos keys` reads the
  config, the capture submap ships, and a bind followed by a reset leaves the file
  unchanged. In the desktop, the bind went live and came off again.
- Fixed in the test: the bind check expected the keys in the order typed, but
  `bromigos keys` writes them in its own order (SUPER ALT CTRL SHIFT). It also left the
  bind behind when it failed.
- The live layer from this tree (r24) fixed two bugs. At 1280x800, edge's daemon had
  failed to reshape the den's painting and drawn the den without it; the new one loaded
  it. And `bromigos-live restart` over an older daemon now stops both processes and
  starts exactly one, even when restarted five times in quick succession or right after
  a login.

### 2026-10-08, 22:37 to 22:46 Pacific: pass, the v0.1.1 candidate

`install.sh --channel edge` on a fresh Arch cloud image (`bromigos-core` r82.gdb950b8,
`bromigos-vector` r28.gafc7592). The image is btrfs with GRUB and a systemd initramfs, and
its cloud-init user isn't in `wheel`.

- Every step ran, including rollback. Setup installed snapper, snap-pac and grub-btrfs,
  created snapper's `root` configuration with the user allowed to list it, and enabled
  `grub-btrfsd`. It noted that a systemd initramfs can't take the overlay hook.
- `checks.sh` passed 40 of 40, including the rollback checks.
- `bromigos update --channel stable` downgraded 7 packages inside snap-pac's pair, and
  `bromigos update --rollback --yes` put them back. Switching the `Server` line by hand
  instead failed with "signature is invalid", which is why a switch now drops the old
  database.
- The snapper-user-access migration fixed a configuration where the user got "No
  permissions.", and left alone one where the user already had access.
- After the v0.1.1 tags, `install.sh` with its defaults (the `stable` channel) passed
  40 of 40 too. v0.1.0's rollback step had waited on pacman's question under `--yes`.

### 2026-10-08: pass

A fresh Arch cloud image (kernel 7.2.7), 6 GB, 4 CPUs, with bromigos r2, core r53,
desktop r6, settings r6, live r12, widgets r6, vector r10, herdr 0.9.3 and ttf-geist-mono
1.7.2.

- `install.sh --yes --answers test/vm/answers.toml` took 71 s and installed 355 packages.
  Networking stayed with the image's systemd-networkd. SDDM, Bluetooth and PipeWire were
  enabled, the migrations created the configs, and setup applied every section.
- `checks.sh` passed 22 of 22: packages, `pacman -Qk` and `-Dk`, fonts, SDDM's theme, the
  configs, `Hyprland --verify-config` before and after setup's monitors block, the theme,
  `bromigos update --check`, and a second `bromigos install` that changed nothing.
- After a reboot: the Bromigos login screen, then Hyprland with the bar, the panels
  (widgets), the live den, the wallpaper and the polkit agent.
- Two screens: both lit side by side, with workspaces 1 to 5 on the left and 6 to 10 on
  the right. The second screen wasn't in setup's block, so the catch-all rule placed it.
- Hotplug: a third screen got a wallpaper and a share of the workspaces. Unplugged, its
  wallpaper went and the workspaces folded back.

What it found and fixed:

- SDDM's own `default.conf` overrode the theme. bromigOS's drop-in is now
  `zz-bromigos.conf`, so it's read last.
- `DP-1` was hard-coded in the live layer, the panels, swaybg and VECTOR's hologram.
- Two build dependencies were missing: `glib2-devel` and Pillow.
- A newly added screen was sorted as the leftmost.
- swaybg kept running on an unplugged screen.

## The AUR bootstrap route

`bromigos-keyring` and `bromigos-mirrorlist` are also built from the AUR.
The manual's [AUR steps](../manual/src/install.md#start-from-the-aur) explain how
users add the repository. `install.sh --aur-route` prints those steps.

The recipes live in `packaging/aur/`. After the signed package workflow passes,
its AUR job pins them to an immutable `aur-bootstrap-<commit>` tag, records the
archive checksum, and copies the repo packages' versions. It builds and installs
both recipes in an Arch container. It adds the repository there, runs
`pacman -Sy`, and verifies a signed `bromigos-core` download. Only then does it
push the PKGBUILDs and `.SRCINFO` to the AUR.

The keyring's install hook populates `bromigos` in pacman's keyring and prints
the two configuration lines. It never edits `pacman.conf`. The mirrorlist is
backed up by pacman, so later updates keep a user's extra mirrors.

The channel reader accepts the mirrorlist's `Include`. Switching channels writes
an explicit `Server` in `pacman.conf`, leaving the packaged mirrorlist alone.
