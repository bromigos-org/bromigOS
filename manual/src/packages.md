# What gets installed

bromigOS is a set of packages. You install one, `bromigos`, and it brings in the rest.
This page lists them all, so you can see what each part is and add the optional ones.

To add an optional package, run `bromigos install --with` and its name. For example, to add
the [app bundle](apps.md):

```bash
bromigos install --with bromigos-apps
```

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
| `bromigos-apps-terminal` | bromigOS app bundle, terminal half: LazyVim, tmux, lazygit and mise, configured and themed (no desktop needed) | with `bromigos-apps`, `bromigos-server` |
| `bromigos-fieldkit-tools` | bromigOS Field Kit engine: repair an install (black screen, last boot, rollback, boot menu, disks, backups), the stick and remote help | with `bromigos-server` |
| `bromigos-secureboot` | bromigOS on Secure Boot: shim, a GRUB built and signed on the computer, kernels signed after every update | by the installer, on a computer that starts the newer way (UEFI); elsewhere by `sudo pacman -S bromigos-secureboot` (docs/secureboot.md) |
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
it current. It keeps its sign-in in your [keyring](bromigos-account.md#your-keyring), as bromigOS
does.

BRODEC's lab bridge is optional too: `sudo pacman -S brodec-lab` lets this machine report
to your BRODEC account as your lab. It only reads. Nothing starts until you run
`sudo systemctl enable --now brodec-lab`, then `sudo brodec-lab pair`, and scan the code it
shows in BRODEC.

## Where your own files go

Updates replace the packages' files, not yours. The full list of folders is on
[Files and folders](files.md).
