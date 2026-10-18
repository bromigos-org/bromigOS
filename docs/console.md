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
