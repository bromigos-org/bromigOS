# Idle and lock

The idle policy decides what happens when you leave the desktop alone: when the
screensaver starts, when the screen locks, when the displays go off and when the machine
sleeps. It's data, in one small file of yours, so Settings and a command can both change
it. hypridle carries it out.

This page is for someone changing how the policy works. For using it, read the manual's
[Idle and lock](../manual/src/idle.md) page.

![The Settings window's Idle and lock page: the policy in words, presets, a stay-awake
switch and the timers](images/settings-idle.webp)

## The policy file

Your policy is `~/.config/bromigos/idle.toml`. It holds only the keys you changed, and
each one wins over bromigOS's default. `bromigos idle` and Settings › Idle & lock
(`bromigos settings idle`) write it. When they do, they keep your comments and any keys
bromigOS doesn't know.

```toml
# ~/.config/bromigos/idle.toml. Every key is optional.
[screensaver]   # the live layer's scene, full screen; any input ends it
enabled = true
minutes = 8

[lock]          # the lock screen (gtklock; hyprlock if it fails)
enabled = true
minutes = 10

[displays]      # the screens go dark (DPMS); any input wakes them
enabled = true
minutes = 15

[suspend]       # the machine sleeps (systemctl suspend)
enabled = false
minutes = 60

[sleep]
lock_before = true   # lock before any sleep: a suspend, the lid, the power menu

[activity]      # the worlds' keeper and creatures doze without input
enabled = true
seconds = 90
```

The values above are bromigOS's defaults:

- The screensaver starts at 8 minutes.
- The screen locks at 10 minutes.
- The displays go off at 15 minutes.
- The machine never suspends on its own.
- It locks before any sleep.
- The creatures in a world doze after 90 seconds without input.

Minutes are whole numbers from 1 to 1440. The creatures' seconds run from 10 to 3600. If
the file holds a value of the wrong type or out of range, `bromigos idle` says which, and
the default is used instead.

### Where the files live

| File | Who writes it | What it is |
|---|---|---|
| `/usr/share/bromigos/default/idle.toml` | `bromigos-core` | The defaults. A copy is also built into `bromigos`. |
| `/usr/share/bromigos/idle/hypridle.conf.tpl` | `bromigos-core` | The hypridle template. It's also built in. |
| `~/.config/bromigos/idle.toml` | you, Settings, `bromigos idle` | Your changes to the defaults. |
| `~/.config/hypr/hypridle.conf` | you | Loads the rendered policy, then any listeners of your own. |
| `~/.local/state/bromigos/idle/hypridle.conf` | `bromigos idle` | The policy rendered for hypridle. |
| `~/.local/state/bromigos/idle/undo.toml` | `bromigos idle` | Your file before the last change, for undo. |
| `$XDG_RUNTIME_DIR/bromigos-idle-awake.json` | `bromigos idle` | Stay awake's process and end time. It's gone at logout. |

The packaged files win over the built-in copies. When there was no file of yours before
the last change, the undo record is `undo.none` instead of `undo.toml`. The rendered file
is written again only when it changes.

## The `bromigos idle` command

```text
bromigos idle [status] [--json]            the policy in plain words, each timer, warnings
bromigos idle set KEY VALUE [KEY VALUE …]  change it
bromigos idle preset default|screensaver-only|presentation
bromigos idle stay-awake 1h|2h|30m|90|until-off|off|toggle [TIME]
bromigos idle off                          stop staying awake
bromigos idle undo                         undo the last change; again to redo
bromigos idle apply                        render, and restart this session's hypridle
bromigos idle hook                         point hypridle.conf at the rendered policy
bromigos idle render [--defaults]          print the hypridle config; write nothing
bromigos idle start [--detach]             render, then run hypridle
```

`set` takes these keys:

- `screensaver`, `lock`, `displays` or `suspend`, with `on`, `off` or a time. A time also
  turns the timer on. Write it as `8`, `90m` or `1h`.
- `activity`, with `on`, `off` or a number of seconds.
- `lock-before-sleep`, with `on` or `off`.
- Any `section.key` of the file, such as `lock.minutes 12`.

A value out of range is refused with exit status 1, and nothing is written.

`--no-restart` writes and renders the policy but doesn't restart hypridle. Every change
also refreshes the bar's idle module, with `pkill -RTMIN+10 waybar`.

Hyprland's autostart runs `bromigos idle start`. `--detach` starts hypridle in the current
session now, through the compositor, unless it's already running.

### Presets

| Preset | What it sets |
|---|---|
| `default` | Removes your timer keys, so bromigOS's defaults apply. `lock_before` stays as it is. |
| `screensaver-only` | The screensaver on, at its time. The lock, displays off and suspend all off. |
| `presentation` | Nothing idles. The screensaver, lock, displays off, suspend and the creatures' doze are all off. |

A preset only sets the switches. The timers' minutes stay as they were.

Under `screensaver-only`, any input ends the screensaver and nothing locks. Super+L still
locks, and sleep still locks first.

`bromigos idle status` names the preset the policy matches, in `preset`. It says `null`
for a mix of your own.

### Stay awake

Stay awake is a timer, not a setting. `bromigos idle stay-awake 1h` takes a logind idle
inhibitor, and hypridle honours it. Nothing idles until it ends. Then the policy runs as
before.

Under the hood it runs
`systemd-inhibit --what=idle --who=bromigOS … sleep 3600` in its own process group.

- `until-off`, or `on`, holds it until `bromigos idle off`.
- A new stay-awake replaces the old one.
- `toggle [TIME]` stops it when it's on, or starts it for TIME. The default is one hour.
  The bar's idle module runs this on a click.

`status` also lists other programs holding an idle inhibitor, such as a video player or a
download.

### Warnings about the order

The timers all count from the last input. bromigOS warns about odd combinations but never
refuses them. `status` lists them in `warnings`, and Settings shows them under the
summary.

| Level | When |
|---|---|
| warn | The screensaver starts at or after the lock, so the lock covers it and it never shows. |
| warn | The displays go off at or before the screensaver, so it would run on dark screens. |
| note | The displays go off before the lock, so a key wakes them unlocked until the lock. |
| warn | The machine suspends at or before the screensaver. |
| note | The machine suspends at or before displays off, so that timer never fires. |
| warn | The machine suspends with nothing locking first. |
| warn | Sleep doesn't lock first. |
| note | Nothing locks on idle. |
| note | The creatures doze only after the screensaver starts. |
| warn | The screensaver is on, but its animation is switched off. Run `bromigos anim on screensaver`. |
| warn | Your `hypridle.conf` doesn't load the rendered policy. |
| warn | hypridle isn't running. |

## How the policy reaches hypridle

### Rendering

`bromigos idle` renders `hypridle.conf.tpl` with the policy. The template uses minijinja,
like the theme's templates, in strict mode. An unknown name is an error, never an empty
string. The template sees:

- each timer as `screensaver`, `lock`, `displays` and `suspend`, with `enabled`, `minutes`
  and `seconds`;
- `activity`, with `enabled` and `seconds`;
- `lock_before_sleep`, `summary`, and `dispatch`, the Hyprland dispatcher tool for the
  displays.

The rendered config always sets `lock_cmd = bromigos lock-run`. So Super+L and a closed
lid lock the screen, whatever the policy.

### Restarting hypridle

hypridle reads its config only when it starts, so a change restarts it. That goes through
`bromigos restart`'s code in `update.rs`, as the piece `idle` of the package `hypridle`.

1. The running hypridle stops.
2. Hyprland starts it again, with
   `bromigos-dispatch 'hl.dsp.exec_cmd("hypridle")'`.

Starting it through Hyprland puts it in the graphical session, so logind's lock signal
reaches it. Only the hypridle of the session `bromigos` finds, by its `WAYLAND_DISPLAY`,
is restarted.

`bromigos restart` and an update's restarts also restart hypridle when needed. That's when
the policy renders differently from the file it's running, after a newer template, or when
a file it reads changed after it started. To do it by hand, run `bromigos restart idle`.

At login, the default `hyprland.lua` runs `bromigos idle start`, which renders the policy
and then starts hypridle.

## The migration from the old setup

Before the policy was data, a user's `~/.config/hypr/hypridle.conf` loaded the packaged
`/usr/share/bromigos/default/hypr/hypridle.conf`. That file still ships. It's the defaults,
rendered, and a test keeps it equal to the template's output.

`bromigos update` runs `migrations/20261009210000-idle-policy.sh`, which runs
`bromigos idle hook`. It handles four cases.

- **The file loads the packaged policy.** That line becomes
  `source = ~/.local/state/bromigos/idle/hypridle.conf`. It uses an absolute path when
  `XDG_STATE_HOME` isn't `~/.local/state`. The comment bromigOS seeded above it is updated,
  and every other line, such as your own listeners, stays. The old file is kept in
  `~/.local/state/bromigos/idle/hypridle.conf.before-policy`. A link into your dotfiles is
  written through to its target.
- **The file already loads the rendered policy.** It's kept.
- **The file loads neither.** That's your own idle setup, and it's left alone. `status`
  warns that Settings doesn't reach it, and says which line to add.
- **There's no file.** It's created.

Then the update's restarts start hypridle again, because its config changed after it
started.

## The bar and the menu

The bar's idle module is `custom/idle`, drawn by `/usr/lib/bromigos/desktop/waybar/idle.py`.

| It shows | When |
|---|---|
| A dim eye | The timers run as set. |
| A lit eye with `NO LOCK` | Screensaver only. |
| A lit eye with `NO IDLE` | Presentation. |
| An amber cup with the time left | Staying awake. |
| Red | hypridle isn't running. |

Its tooltip gives the policy in words.

- A click stays awake for an hour. A second click stops it.
- A middle click stays awake until you stop it.
- A right click opens Settings › Idle & lock.

The menu's TOGGLE group has "Lock on idle" and "Stay awake", each with its state. See
[menu.md](menu.md).

## The screensaver

The screensaver is the live layer's own scene, drawn full screen over everything. Any
input ends it. Its content, a gas giant or a relay station, is set on the Live layer &
holograms page of Settings.

![The screensaver in phosphor green: a ringed wireframe planet, a relay station, this
machine's CPU and memory as rings, a clock, and the emblem in the
middle](images/screensaver.webp)

## JSON output

`status`, `set`, `preset`, `undo`, `apply`, `off` and `stay-awake` all print the same
document with `--json`. Its fields are `policy`, `defaults`, `set` (the keys your file
sets), `preset`, `screensaver_only`, `summary`, `warnings`, `stay_awake`, `inhibitors`,
`hook`, `hypridle` and the files. After a change it also has `applied`, with `rendered`
and `restarts`. The schema is in [core/README.md](../core/README.md).

## Tests

- **`cargo test` in `core/`** covers the defaults, merging, `set`'s words and ranges,
  edits that keep comments, presets, the warnings, the summaries, rendering, `hook`
  through a symlink, and undo. It also checks the shipped `desktop/hypr/hypridle.conf`
  against the template. The command runs end to end in a sandbox with no session, so
  nothing is restarted.
- **`tools/settings/render.sh --interact`** drives Settings' controls through the real
  command. See [settings.md](settings.md#tests).
- **`test/vm/idle-e2e.sh`** runs in a real session in the fresh-machine VM, after
  `test/vm/arch-vm.sh`. It checks:
  - Screensaver only, rendered, with hypridle restarted inside the graphical session;
  - the screensaver after a minute, nothing locked, and input ending it;
  - stay awake's inhibitor;
  - the migration of an old `hypridle.conf` with a listener of the user's;
  - the lock and unlock through the restarted hypridle;
  - the Settings window on the VM's screen.

## Runs

<!-- end-to-end runs, newest first -->

### 2026-10-09: pass, 30 of 30

The fresh-machine VM ran Arch's cloud image under KVM, with 6 GB of memory, 4 CPUs and
virtio-gpu on Mesa's software renderer, at 1280×800. It was installed from the edge
channel as it was before this work (`bromigos-core` r90) and signed in at the login screen.

Then the new packages went on: core r99, desktop r51, live r22 and widgets r15, built by
`packaging/dev-repo.sh`. `bromigos update --no-packages` ran the migration, which moved the
seeded `hypridle.conf` to the rendered policy. The update's restarts started hypridle again
inside the graphical session. After a reboot, login's `bromigos idle start` ran hypridle
in the session.

`test/vm/idle-e2e.sh` passed all 30 checks:

- Screensaver only was rendered and hypridle restarted in the session, and the bar showed
  NO LOCK.
- The screensaver came up after a minute. Nothing had locked at 2.5 minutes, with the
  lock's timer at 2 and switched off. A mouse movement ended it.
- Stay awake's inhibitor held, no screensaver started under it, and `off` released it.
- An old `hypridle.conf` with a listener of the user's was moved by `idle hook`.
  `bromigos restart` restarted the stale hypridle, and the user's listener fired.
- The default policy locked at 2 minutes, and the password unlocked it.
- The Settings window appeared on the VM's screen.

The run found and fixed three bugs:

- A mouse movement no longer ended the screensaver. Reduced motion's mode had taken the
  name of the overlays' pointer handler, `motion`.
- `bromigos restart` restarted a hypridle it had just started, because a process's start
  time is only known to the second.
- The checks' own detection timed out under load. They now ask Hyprland for the
  screensaver's layer instead of the live layer's `state`.

It also saw two problems outside this work:

- A raw `pacman -U` of `bromigos-desktop` while Hyprland's auto-reload is on can trip its
  emergency mode. `bromigos update` reloads Hyprland after a `bromigos-desktop` upgrade,
  which heals it.
- On a screen whose width times 3 isn't a multiple of 4, the live layer's renderer failed
  to load its underlay (`scene.py`, a pixbuf's rowstride).
