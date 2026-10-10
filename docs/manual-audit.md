# Manual coverage audit

This audit checks whether the commands and default shortcuts shipped by bromigOS appear
in the manual. It also checks the newer media workflows against their parsers and source.
The results below are from 10 October 2026, including the merged provisioner and
shell-prompt command.

## What was checked

| Source | Coverage |
|---|---|
| `bromigos commands --json`, with only this checkout's executables | 70 visible command routes |
| Built-in help and the generated Commands page | 128 command and subcommand help sections |
| `widgets/keybinds.py`, read from the packaged Hyprland config | 80 default key actions |
| `tools/docs/manual-reference.toml` | Every visible route and default key action has a task row |
| Generated Commands and Keys pages | Both match the code |
| Newly merged `bromigos lab provision --help` | Matches the lab setup guide and its supported services |
| Media and YouTube command examples in the new guide and calendar section | 22 examples parsed without executing requests |

Hidden implementation helpers, personal commands and personal key bindings are outside
this audit. Hardware-specific extra bindings are explained in
[Peripherals](../manual/src/peripherals.md). On a machine, `bromigos commands` and the
SHORTCUTS panel include that machine's additions.

## Gaps fixed

- `bromigos customize` and `bromigos media` had generated help but no task-group rows.
  They now link to Customize and Your media.
- The media workflow had no single starting page. [Your media](../manual/src/media.md)
  connects requests, tracking, safe deletion, YouTube, the den TV and release calendars.
- Calendar-feed export had no manual instructions. It now has a
  [calendar releases](../manual/src/panels.md#calendar-releases) section.
- The Claude follow key was in Keys, but VECTOR's page did not explain local session
  reading or its terminal controls. It now has
  [Read a Claude Code session](../manual/src/vector.md#read-a-claude-code-session).
- NAS playback trouble had no generic NFS lock note. It now has
  [Media files on a NAS](../manual/src/troubleshooting.md#media-files-on-a-nas).
- The release fallback kept only 25 subjects. It now keeps every user-facing subject,
  and release preparation includes the reviewed edge highlights.

No visible command route or default key action remains without a manual entry. The
first provisioning implementation is merged and documented in
[Setting up a lab](../manual/src/lab.md#setting-up-a-lab). AI, media and game installers
remain planned.
“Night Block” is an example channel to create, not a built-in schedule.

## Repeat the audit

Build the CLI, regenerate its reference, and check that it is current:

```bash
cd core
cargo build -p bromigos
cd ..
python3 tools/docs/generate.py
python3 tools/docs/generate.py --check
mdbook build manual
tools/docs/check-links.sh manual/book
```

Compare `bromigos commands --json` with Commands, and the packaged bindings interpreted
by `widgets/keybinds.py` with Keys. Review any **Other commands** or **Other keys** rows:
they have generated descriptions but still need a task-group entry. The generator uses
a temporary home and the checkout's command files, so personal commands cannot enter
this public reference.

A new nested media verb needs instructions in the task guide or its linked reference too.
Check examples against `bromigos_homelab.mediareq.parser()` and the YouTube parsers;
parsing arguments does not contact a lab or request a download.
