# Text console fonts

`bromigos console` reads and saves the font used by Linux text consoles.
The user-facing instructions are in the manual's
[Shell and terminal](../manual/src/shell.md#make-text-consoles-readable) page.

`bin/bromigos-console` loads `lib/bromigos_console.py`. The core package installs
both; `bromigos-settings` depends on `terminus-font`, which core lists as optional.
The command uses only Python's standard library.

## Commands and presets

`bromigos console status` reads `/etc/vconsole.conf` without root access. It reports
the saved font and installed presets, not a measurement of the running console.
`--json` provides the same information for scripts.

`sudo bromigos console font SIZE` changes only the `FONT` assignment:

| Size | Saved font | Glyph height |
|---|---|---|
| `small` | `ter-v16n` | 16 pixels |
| `medium` | `ter-v24n` | 24 pixels |
| `large` | `ter-v32n` | 32 pixels |
| `default` | Removes `FONT` | System default |

The selected `.psf.gz` file must exist in `/usr/share/kbd/consolefonts` before a
preset can be saved. `default` does not require Terminus. The filenames come from
Arch's [terminus-font package](https://archlinux.org/packages/extra/any/terminus-font/files/).
These are console fonts; they do not contain graphical terminals' Nerd Font icons.

## Saving safely

Font changes require explicit root execution. A root-owned regular lock file in
`/run/lock` serialises bromigOS writes. Config symlinks, duplicate assignments,
multiline values and unsupported syntax are refused. Blank lines, comments,
keyboard settings and other single-line assignments are preserved.

Nonempty `FONT_MAP` or `FONT_UNIMAP` overrides are refused when choosing a Terminus
preset, since they can conflict with its Unicode mapping. The error asks the user
to review those overrides. `default` removes only `FONT` and preserves the maps.

The writer builds a temporary file beside the config, preserves its owner and
permissions, flushes it, checks that the original text has not changed and replaces
it atomically. It then syncs the containing directory. A missing config is created
with mode `0644`; resetting a missing config to `default` leaves it missing.

No console device is opened, and no font loader or service is called. The setting
applies at the next boot. A font embedded in the initramfs can still appear during
early boot until that image is rebuilt separately; this command does not rebuild
it. Kernel command-line settings such as `vconsole.font` take precedence, as
documented in systemd's
[vconsole.conf reference](https://www.freedesktop.org/software/systemd/man/latest/vconsole.conf.html).

## Tests

Run the sandbox fixtures from the repository root:

```sh
PYTHONPATH=lib python -m unittest discover -s tests/console
```

They use temporary config, font and lock paths. Coverage includes permission checks,
preserved settings, map conflicts, invalid configs, symlink refusal, failed writes,
concurrent edits and resetting to the default. Packaging runs them in `check()`.

## The console's look

`bromigos-boot` makes every text console look like bromigOS, on the desktop, Field Kit and
bromigOS Server alike. Nothing is plain white on black, even with no graphics driver.

### kmscon, where an edition turns it on

kmscon is a terminal that draws the console on the graphics card itself: real fonts through
FreeType, full Unicode and box drawing, and 24-bit colour. Fedora has proposed it as its
default console, and Arch packages a current release. Field Kit and bromigOS Server turn it
on for the first console (`kmsconvt@tty1.service`). The desktop doesn't: its login screen
has that screen.

bromigos-boot ships its settings and a drop-in for every console kmscon runs:

| File | What it does |
|---|---|
| `/usr/share/bromigos/console/kmscon/kmscon.conf` | Geist Mono through pango (which falls back to Symbols Nerd Font for icons), sized by kmscon for the screen, the DRIFTGLASS palette in true colour (the Wick's terminal colours, `build-console-font.py` makes it), `term=xterm-256color` |
| `/usr/lib/systemd/system/kmsconvt@.service.d/bromigos.conf` | kmscon with that folder, and `bromigos-console-login` as its login program |
| `/usr/lib/bromigos/console/bromigos-console-login` | sets `COLORTERM=truecolor`, so programs use the full palette, then `login -p`. On a Field Kit medium's first console it signs root in, straight into the menu |

Where kmscon can't start (no graphics device: `nomodeset` on BIOS, a serial console),
`kmsconvt@`'s own `OnFailure=` starts getty on that console instead.

### The kernel's console

Wherever getty runs, `bromigos-console.service` (and a udev rule, when a graphics driver
takes the screen over and resets it) runs `bromigos-console-setup`:

- **The colours.** `setvtrgb` sets the console's 16 colours to DRIFTGLASS's, the same as
  the terminal's (`/usr/share/bromigos/console/palette.vtrgb`). It changes the kernel's
  defaults too, so a console made later starts in them.
- **The font,** unless you chose one (`FONT=` in `/etc/vconsole.conf`, or `vconsole.font=`
  on the kernel's command line). Geist Mono, as console fonts bromigos-boot makes at
  three sizes: 8x16, 12x24 and 16x32 (`/usr/share/kbd/consolefonts/bromigos-geist-*.psf.gz`).
  The size follows the screen's width: under 1800 pixels 16, under 3000 pixels 24, else 32.

A console font holds at most 512 glyphs. Geist Mono's go in, chosen for what text screens
draw: ASCII and Latin-1, box drawing and blocks (panels, borders, meters), and the dots,
arrows, ticks and crosses bromigOS's commands print. Box drawing and blocks are drawn to the
cell's edges, so lines join. A character outside the set shows as a box.

### When the desktop doesn't start

bromigos-boot keeps a machine from stopping at a black screen with a blinking cursor:

- **No graphics device** after 15 seconds: SDDM's start condition
  (`sddm.service.d/bromigos-graphics.conf`, `ExecCondition=bromigos-console-hint
  graphics-ready`) skips the login screen. The first console's login takes its place,
  with a note above it saying the graphics didn't come up, how to try again and how to find
  out why.
- **SDDM fails** (`OnFailure=bromigos-no-graphics.service`): the same note and the same
  login.
- **Text mode from the boot menu** (`systemd.unit=multi-user.target`):
  `bromigos-text-mode.service` puts a note above the login saying so, and how to start the
  desktop.

The notes go in `/run/issue.d`, which agetty reads, so they're gone at the next boot.
