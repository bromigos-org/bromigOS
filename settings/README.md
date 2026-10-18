# settings/

This folder is the `bromigos-settings` package. It holds what must exist before anyone
signs in: the login screen, the boot splash, the boot menu, and the GTK theme, icons and
cursor the desktop names. It also holds the builders the `gtk` theme-set hook uses.

These system-wide pieces keep the Wick's look, the default theme. When a user runs
`bromigos theme set`, it changes their own GTK theme. The boot menu can follow their theme
too ([docs/boot.md](../docs/boot.md)).

This folder isn't the Settings window. That's `desktop/settings/`
([docs/settings.md](../docs/settings.md)).

## What's here

| Folder or file | Installed to | What it is |
|---|---|---|
| `sddm/bromigos/` | `/usr/share/sddm/themes/bromigos/` | The login screen ([its README](sddm/bromigos/README.md)) |
| `sddm/conf/zz-bromigos.conf` | `/usr/lib/sddm/sddm.conf.d/` | SDDM's settings: this theme, the cursor, the Wayland greeter |
| `plymouth/bromigos/` | `/usr/share/plymouth/themes/bromigos/` | The boot, shutdown and restart splash |
| `console/` | `/usr/lib/issue.d/60-bromigos.issue` | The text-console login banner ([its README](console/README.md)) |
| `grub/` | `/usr/share/bromigos/boot/grub/`, `/usr/lib/bromigos/boot/` | The boot menu's theme and its tools |
| `gtk/` | `/usr/share/themes/Bromigos`, `/usr/share/icons/Bromigos*`, `/usr/lib/bromigos/gtk/` | The GTK theme, icons and cursor, and their builders |

`packaging/bromigos-settings/PKGBUILD` lists every installed path.

### The boot, shutdown and restart splash

The splash is the emblem's ring and flame. Plymouth's script module reports whether the
system is booting, shutting down or restarting. Boot keeps its progress line, messages
and disk passphrase prompt. Shutdown and restart show their action below the emblem,
with a moving activity marker instead of a percentage.

The ring and flame come from the Wick's lock-screen art. The ISO's installer turns
Plymouth on. Existing systems need the theme selected and `splash` on the kernel command
line; [docs/boot.md](../docs/boot.md#the-boot-shutdown-and-restart-splash) covers activation.
`plymouth/tests/` runs the real script interpreter with in-memory displays, without a
daemon, console or service. The package runs those tests in `check()`.

### The boot menu

`grub/` holds the boot menu's theme and tools. See [docs/boot.md](../docs/boot.md).

- `build-grub-theme.py` generates a GRUB theme. It runs for each shipped theme when the
  package builds, and for a user's own theme on their machine.
- `bromigos-boot-theme` is the root helper. It copies a theme into `/boot`, keeps a block
  in `/etc/default/grub`, and makes `grub.cfg` again, checking each step.
- `grub-btrfs-titles` gives the snapshots in the boot menu readable titles.
- `preview.py` has GRUB itself draw a theme in a headless VM.
- `tests/` holds the tests.

### GTK, icons and cursor

- `build-gtk-theme.py` builds the Wick's GTK 3 and 4 theme when the package builds. For any
  other theme, it builds `Bromigos-<theme>` into `~/.themes`.
- `build-icons-cursor.py` makes the icons and cursor by recolouring Breeze Dark.
- `libadwaita.css` and `overrides.css` are the libadwaita and override styles.

### Fonts

The fonts come in as dependencies: Geist Mono (`ttf-geist-mono`, built into bromigOS's
repository), Meslo Nerd, Noto and Terminus. Terminus supplies the bitmap fonts for
Linux text consoles; choose their size with [`bromigos console`](../docs/console.md).

## Tests

```bash
python -m unittest discover -s settings/grub/tests
```

This covers the boot menu's generator, the snapshots' titles, and the root helper in a
stand-in root. The package's `check()` runs it. The login screen has its own preview and
test steps in [its README](sddm/bromigos/README.md#changing-it).
