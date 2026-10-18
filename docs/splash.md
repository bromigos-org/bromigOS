# Graphical shutdown and restart

`bromigos splash` selects the packaged Plymouth theme and saves the kernel flag
needed for graphical shutdown and restart. Plymouth is the program that draws the
screen while the system stops. User instructions are in the manual's
[boot menu page](../manual/src/boot-menu.md).

The command supports GRUB systems with `/etc/default/grub` and
`/boot/grub/grub.cfg`. It refuses a different boot loader reported by the firmware.
GRUB drop-in files under `/etc/default/grub.d/` and dynamic kernel argument
assignments are outside this helper's supported configuration.

## Commands

| Command | What it does |
|---|---|
| `bromigos splash status` | Read the selected theme, installed runtime, saved flag and running kernel flag |
| `bromigos splash status --json` | Return those readings as JSON |
| `sudo bromigos splash on` | Save the bromigOS theme and a GRUB splash flag |
| `sudo bromigos splash off` | Remove the helper's changes and restore the previous theme setting |

`on` requires Plymouth's executable programs, its script plugin and the packaged
bromigOS theme. Explicit flags that disable Plymouth must be reviewed first. The
helper leaves them in place and refuses to enable a contradictory configuration.
`status` reports disabled flags in both the saved and running configurations.

The running kernel command line cannot be changed by this command. Reboot once
after enabling the feature before expecting the new shutdown or restart visuals.
The shutdown at the start of that first reboot can still use the existing screen.
This helper does not add an initramfs hook or rebuild an initramfs. Early boot
animation remains a separate setup described in [boot.md](boot.md).

## Files and ownership

The executable is `bin/bromigos-splash`; its implementation is
`lib/bromigos_splash.py`. Both ship in `bromigos-core`.

The helper appends a marked block to `/etc/default/grub`. The block adds `splash`
only when that argument is absent. Existing kernel arguments stay in place.
Plymouth's selected theme is saved in `/etc/plymouth/plymouthd.conf`, inside its
`Daemon` section. The theme assignment has its own marked block.

State and backups live in `/var/lib/bromigos/splash/`, accessible only to root.
Each changed operation saves the original configurations, the generated GRUB menu
and the previous state, where those files existed. Its directory also contains a
manifest and `commands.log` for the GRUB commands. The command prints this directory
when it changes a setting or fails during generation.

`off` restores the previous theme assignment and removes only its GRUB block.
Unrelated edits made after `on` are retained. A user-supplied `splash` argument or
an already selected bromigOS theme remains in place. If an owned block was edited,
the helper stops for review instead of replacing it.

## Saving and rollback

Only root can change settings. Reads never source the shell configuration or run
GRUB, Plymouth, a service manager or a display command. Writes reject symlink paths,
files writable by other users and duplicate Plymouth theme assignments. A lock
prevents two splash changes from running together.

The helper writes each changed configuration atomically. It asks `grub-mkconfig`
to generate a temporary file beside the current `grub.cfg`, then checks that file
with `grub-script-check`. Only a nonempty menu that passes the check can replace
the existing menu. State is saved last.

Generation errors, validation errors, interrupted commands and state-write errors
restore the preceding files. Rollback also checks for concurrent edits. If another
process changed a file, that file is retained and the command reports the backup
directory for review. The helper never restarts the computer or a running service.

## Tests

Run the fixture tests with:

```bash
python3 -m unittest discover -s tests/splash -v
```

They use a temporary filesystem and an injected GRUB runner. An accidental real
subprocess is a test failure. Coverage includes round trips, preserving later edits,
unsupported boot loaders and drop-ins, unsafe paths, runtime prerequisites, disabled
flags, validation and write failures, and interruption rollback. No test changes a
real boot configuration or starts Plymouth.
