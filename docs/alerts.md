# Alerts

bromigOS checks the computer for problems that need a person: a drive that is failing, a
disk that is almost full, a service that stopped, a backup that didn't run. It writes what it
finds to one file. The desktop shows it as a notification, `bromigos alerts` lists it, and
BRODEC's machine agent sends it to your phone, end-to-end encrypted, with buttons to act on
it.

bromigOS only finds and describes problems. It never fixes one by itself. On the phone, *Fix
it* asks VECTOR, the desktop's AI assistant, for a plan, and nothing runs until you approve it
(BRODEC's `docs/MACHINE_JOBS.md`).

The manual's [Alerts](../manual/src/alerts.md) page is the user's side.

## What it checks

| Check | What it looks for | How bad |
|---|---|---|
| `disk.smart` | A drive's own health records (SMART, and NVMe's health log) | Critical: the drive says it's failing, or raised a critical warning. Needs you: bad sectors, media errors, 90 % of an SSD's rated life used |
| `disk.scrub` | btrfs's last scrub (`btrfs scrub status`) and its error counters (`btrfs device stats`) | Critical: damaged data with no good copy. Needs you: errors it repaired, or counters above zero |
| `disk.full` | Each real filesystem's free space | Needs you at 90 %, critical at 97 % |
| `update.waiting` | Updates waiting (`bromigos update --check`) | Info. Needs you when nothing was installed for 30 days |
| `update.restart` | A new kernel or graphics driver that runs only after a restart | Needs you |
| `update.held` | bromigOS Server's automatic update held by Arch Linux news, or rolled back | Needs you (critical when a rollback also failed) |
| `backup.restic` | bromigOS Server's own backup (`bromigos server backup`), and restic backups run by systemd (`restic*` and `bromigos-backup*` services) | Needs you: the last one failed, none finished for 36 hours, or the Server's backup check failed |
| `power.ups` | A UPS through NUT (`upsc`) | Needs you: on battery, or its battery needs replacing. Critical: on battery and low |
| `systemd.failed` | Services that failed, leaving out ones that don't matter | Needs you. Critical for SSH, the firewall and the network on a Server |
| `server.game` | A game server that stopped (bromigOS Server) | Needs you |
| `fieldkit.finding` | After each boot: Field Kit's black screen check on this computer, and what a Field Kit stick found here | Needs you |
| `game.steam` | Steam and Proton (`bromigos game check`) | Needs you, or info when bromigOS fixes it by itself |

Two passes run them:

- **The system pass** runs as root, because reading drives and every service needs it.
  `bromigos-alerts.timer` runs it every 15 minutes. `bromigos-alerts-boot.timer` runs it two
  minutes after each boot, with Field Kit's checks.
- **Your pass** runs as you: updates waiting, the disk your home is on, your own services, and
  Steam. `bromigos-alerts-user.timer` runs it two minutes after you log in and every 30
  minutes. Then it shows the desktop notification.

Both are on for everyone. `sudo systemctl disable --now bromigos-alerts.timer
bromigos-alerts-boot.timer` turns the system pass off. `systemctl --user mask
bromigos-alerts-user.timer bromigos-alerts-notify.path` turns yours off.

## The desktop notification

`bromigos alerts notify` shows what needs you. It runs after your pass, and as soon as the
system pass writes something new (`bromigos-alerts-notify.path`).

- Only alerts that need you or are critical show. Info never does.
- Each alert shows once. It shows again after a while if it's still there: 6 hours for a
  critical one, 24 hours for one that needs you. It also shows again when it gets worse.
- An alert that clears and comes back within 30 minutes doesn't show again.
- A run shows at most three notifications. When more are due, the third says "And 3 more
  alerts on this computer".
- Nothing shows outside a desktop session or without `notify-send` (package `libnotify`).

## Field Kit's findings at the next boot

Field Kit is bromigOS's repair stick ([fieldkit.md](fieldkit.md)). When its black screen or
last boot check looks at an install, it saves the findings that aren't fine inside that
install, in `/var/lib/bromigos/fieldkit/findings.json`. The commands in them read as they
would on the running install, with no `arch-chroot`.

At the install's next boot, the boot pass runs Field Kit's black screen check on the running
system, and the same check again for each one the stick saved:

- When the check runs, its own result counts. A finding that was repaired is gone, and its
  entry leaves the file.
- When it can't run (the last boot check needs a saved journal), the stick's findings are
  raised instead.

The passes between boots keep what the boot pass found.

## The Arch news hold

Arch Linux sometimes posts news that asks for manual steps before an update. bromigOS
Server's automatic update reads Arch's news feed first. If an item was posted since the last
update, it doesn't update. It records the item's title and link in
`/var/lib/bromigos/server/update.json`, and `update.held` raises it with the link.

Read the item and do what it asks. Then update by hand: `sudo bromigos server update --now`,
or BRODEC's Update button, which runs the same command. That update clears the hold, and the
news posted until then counts as read. A feed that can't be read holds nothing.
[server.md](server.md#the-arch-news-hold) has the setting.

## Commands

```bash
bromigos alerts                          # the alerts now, worst first
bromigos alerts --json                   # the same, as one document
sudo bromigos alerts check --system      # run the system checks now
bromigos alerts check                    # run your checks now
sudo bromigos alerts check --system --only disk.smart --json
bromigos alerts checks                   # each check: when it ran, and why one couldn't
bromigos alerts notify                   # the desktop notification, once each
```

`bromigos alerts` exits with 1 when something needs you, so a script can use it.

## For power users

### The files

| File | Written by | Mode |
|---|---|---|
| `/var/lib/bromigos/alerts/system.json` | the system pass, as root | 0644 |
| `/var/lib/bromigos/alerts/state.json` | the system pass: when each alert was first seen | 0644 |
| `~/.local/state/bromigos/alerts/user.json` | your pass | 0600 |
| `~/.local/state/bromigos/alerts/state.json` | your pass: when each alert was first seen | 0600 |
| `~/.local/state/bromigos/alerts/notified.json` | `notify`: what the desktop showed, and when | 0600 |
| `/etc/bromigos/alerts.toml` | you, with sudo: the settings | |
| `/etc/bromigos/alerts.d/`, `~/.config/bromigos/alerts.d/` | you: your own checks | |

Each file is replaced atomically, so a reader never sees half of one. One pass of each kind
runs at a time.

### The document

Both passes write the same shape:

```json
{"schema": 1, "scope": "system", "role": "desktop", "checked_at": 1793390400000,
 "checks": [{"check": "disk.smart", "state": "ran", "error": null, "ran_at": 1793390400000}],
 "alerts": [ALERT, ...]}
```

- `role` is `desktop`, `server` or `fieldkit`.
- `checks[].state` is one of these:
  - `ran`: it looked, and every alert it found is in the list;
  - `skipped`: it doesn't apply here (no UPS, not a Server, the tool isn't installed). It
    counts as ran with nothing found;
  - `failed`: it couldn't look. `error` says why, and the check's earlier alerts stay as they
    were.
- An alert from a check that ran, and that isn't in the newest document, has cleared.
- Times are milliseconds since 1970.

### An alert

```json
{"id": "disk.smart:nvme0", "check": "disk.smart", "severity": "critical",
 "title": "A drive is failing: Samsung SSD 980 PRO 2TB (nvme0)",
 "detail": "… its own health check says FAILED … Copy your files off it now, then replace it.",
 "source": "SMART", "subject": "nvme0", "since": 1793390400000,
 "actions": [{"kind": "fix", "label": "Fix it"}, {"kind": "snooze"}, {"kind": "open"}],
 "evidence": {"lines": ["SMART overall-health self-assessment test result: FAILED", "…"],
              "facts": {"model": "Samsung SSD 980 PRO 2TB", "serial_tail": "3456"}},
 "fix": {"commands": ["sudo smartctl -a /dev/nvme0", "sudo smartctl -t short /dev/nvme0"],
         "touches": ["nothing (it reads the drive's records and runs its own 2-minute self-test)"],
         "from": "bromigos", "root": true, "note": "Back up first: …"},
 "link": null}
```

| Field | What it is |
|---|---|
| `id` | Stable for the problem: `<check>:<subject>`. At most 160 characters of `A-Z a-z 0-9 . _ : / @ + -` |
| `severity` | `info` (listed, never sent to a phone), `needs_you` or `critical` |
| `title` | One plain line, at most 120 characters |
| `detail` | What it means, then what to do. At most 600 characters |
| `source` | What saw it, as a person would say it: `SMART`, `btrfs`, `Disk space`, `Updates`, `Arch news`, `restic`, `UPS`, `systemd`, `Game server`, `Field Kit`, `Steam` |
| `subject` | What it's about: a drive, a mount point, a service, a UPS |
| `since` | When it was first seen. It stays the same while the alert lasts |
| `actions` | Suggested, in order. `kind` is `restart`, `update`, `fix` (ask VECTOR), `snooze`, `open`, `run` (with `command`) or `link` (with `url`). `label` is optional |
| `evidence` | For VECTOR: at most 40 `lines` of at most 300 characters, and `facts`. No secrets, on purpose. BRODEC redacts them again anyway |
| `fix` | A repair bromigOS already knows, when it knows one: `commands` as a person types them, what it `touches`, `from` (`fieldkit`, `game check`, `bromigos`), whether it needs `root`, and a `note` |
| `link` | A web page, such as the Arch news item |

### The settings

`/etc/bromigos/alerts.toml`. Every key is optional.

```toml
[disk]
full_percent = 90        # needs you from here
critical_percent = 97    # critical from here
ignore = []              # mount points never checked, such as "/mnt/scratch"

[units]
ignore = []              # failed services that never alert, such as "foo.service"

[checks]
off = []                 # checks turned off, such as "game.steam"

[game]
units = []               # the services that are game servers, such as "valheim.service"
```

A full disk stays raised until it is 2 points under `full_percent`, so a disk hovering at the
line doesn't alert again and again. `systemd.failed` leaves out transient and masked units,
`*-wait-online` services, sessions and scopes. A container with the label `org.bromigos.game`
counts as a game server too.

### Your own checks

Put an executable in `/etc/bromigos/alerts.d/`. The system pass runs it as root. One in
`~/.config/bromigos/alerts.d/` runs as you, in your pass.

- The file and its folder must belong to root (yours: to you), and no one else may write
  them. Otherwise it doesn't run, and `bromigos alerts checks` says why.
- It must print `{"alerts": [ALERT, ...]}` within 30 seconds and exit with 0.
- Its check is `custom.<file name>`, and each `id` gets that in front: `media` from
  `nas-mount` becomes `custom.nas-mount:media`. `source` is the file's name unless you give one.
- `severity` and `title` are needed. The rest follows the limits above. An action of an
  unknown kind is left out.
- When it fails, times out or prints something else, its earlier alerts stay as they were.

An example, `/etc/bromigos/alerts.d/nas-mount`:

```sh
#!/bin/sh
if mountpoint -q /mnt/nas; then
  echo '{"alerts": []}'
else
  echo '{"alerts": [{"id": "nas", "severity": "needs_you", "title": "The NAS share is not mounted",
    "detail": "/mnt/nas is empty, so the backups to it fail.",
    "actions": [{"kind": "run", "label": "Mount it", "command": "sudo mount /mnt/nas"}]}]}'
fi
```

### How BRODEC uses it

BRODEC's machine agent, `brodec-machine`, runs as you. It reads both documents when they
change and keeps its own record of each alert: active, snoozed or resolved. It redacts the
text and sends the changes to your phone, end-to-end encrypted. It wakes the phone only for
alerts that need you, with limits so nothing spams. Its side is in BRODEC's
`docs/MACHINE_JOBS.md`, "Alerts".

### The code and the tests

- `bin/bromigos-alerts`: the command.
- `lib/bromigos_alerts.py`: the passes, the document, custom checks and the notification.
- `lib/bromigos_alerts_checks.py`: the checks.
- `packaging/bromigos-core/bromigos-alerts*.{service,timer,path}`: the units.
- `tests/alerts/`: every check against stand-in commands in a stand-in root (`fake.py`).
  Nothing real is read, and no notification shows. `python3 tests/alerts/fake.py DIR` writes
  documents with an alert of every kind, for BRODEC's tests.

```bash
PYTHONPATH=lib python -m unittest discover -s tests/alerts
```
