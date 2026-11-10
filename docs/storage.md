# Local storage

`bromigos storage` manages plans for local data drives, file migrations and cleanup, and
says how healthy each drive is ([Drive health](#drive-health)).
Its default status command reads devices and journals without changing the machine.
User instructions are in the manual’s [Storage](../manual/src/storage.md) page.

## Drive layout

A drive plan selects a stable `/dev/disk/by-id/` device, a mount path and data roles.
The filesystem is Btrfs. Development, games, downloads, VMs and models use isolated
subvolumes on the same filesystem. `development` is required first and mounts at
the named `/mnt` path; additional roles mount beneath it. VM storage is root-owned,
while the other role roots use the planning user’s UID and GID.
Capacity is shared; role quotas and reservations
are not implemented. The layout does not set up LUKS encryption or automatic snapshots.

Provisioning uses GPT with one Linux partition and normal Btrfs copy-on-write and
checksums. It binds the by-id device, serial, size and current mount configuration
to the saved plan. Apply asks for the exact serial in `/dev/tty`, rechecks the
identity and mounts, and records the erase before touching the disk. A plan with an
execution journal cannot erase a disk again. Failures require operator review.

Drive preparation, migration copying, verification and path switching require
administrative access. Copying uses rsync with ownership, hard links, ACLs, extended
attributes and sparse files preserved. Verification uses a checksum dry run that
also reports unexpected destination files; it does not delete them. Planning never escalates
privileges or starts a graphical approval flow.

## Files and records

`lib/bromigos_storage_common.py` owns checksummed plans, run journals, operation
locks and bounded subprocess calls. Plans live under
`$XDG_STATE_HOME/bromigos/storage/plans/` by default. `BROMIGOS_STORAGE_STATE`
overrides the storage state directory. Each plan has a neighbouring `.run.json`
journal tied to its digest. Files use mode `0600`. Root execution accepts the
absolute plan path so it can use the operator’s saved plan without guessing their
home directory.

`lib/bromigos_storage_inventory.py` reads block devices and mounts and previews
known cache locations. Btrfs subvolumes share capacity; free-space values for
several subvolumes must not be added together.

## Migration stages

A migration records source and destination directory and filesystem identities before
copying. New destinations must be absent or empty. Nested mounts and overlapping or
aliased source/destination paths are refused. A copy stage means data
has been staged at the destination. Verification is a separate stage. A switch changes
the path applications use only after writers have stopped and verification passes.
It requires a text terminal, refuses active Wayland/X11 sessions and checks process
working directories, open files and mapped files under the affected paths. It does
not stop any writer or session automatically.
The old source remains available after switching.

Interrupted copies resume through their saved plan. Recovery must inspect the recorded
stage rather than infer completion from destination size or a successful copy command.
Cleanup preview reads caches and snapshots. Clearing a cache or deleting retained
originals or selected snapshots requires a separate explicit cleanup plan and apply step.

A multi-move spec uses `[[move]]` records with absolute `source`, `destination` and
optional `keep_path` strings. If `keep_path` equals the source, switching renames
the original to a recovery directory before creating the bind mount. An existing
bind at another path must match the planned source. Without `keep_path`, no old
application path is redirected automatically.

The journal states distinguish `copying`, `staged`, `verifying`, `verified`,
`switching` and `switched`. Failed copy and verification states can be inspected
and retried through the matching resume/verify command. Once switching starts,
automatic copy and switch replay is refused, including after `switch-failed`.
The journal records retained source names, an fstab backup and switched paths for
manual recovery. No recovery step deletes the retained source automatically.

## Capacity and snapshot inventory

Human output groups mounts by filesystem UUID and lists physical drives separately.
A Btrfs filesystem has one capacity row even when many subvolumes and bind mounts use
it. RAM-backed swap devices are excluded from the physical-drive list. JSON keeps
`disks`, `mounts` and `free_space`, and adds `drives` and grouped `filesystems`.
`bromigos_storage_display.py` handles the terminal output. Control characters in
external labels and paths are escaped. Desktop terminals show usage with fractional
Unicode blocks. Linux text consoles, basic terminals, redirected output and encodings
without those glyphs use an ASCII bar. The bar needs no patched font or extra library.

Cleanup preview reads Snapper configurations and their snapshot lists. It also reads
ordinary local btrbk `volume`, `subvolume`, `snapshot_dir` and `snapshot_name` entries.
It never opens backup targets. Includes, wildcards and unsupported configurations are
reported rather than guessed. An unavailable provider is not an empty provider.
Inventory inspects only already mounted local filesystems and bounded directory
metadata. It avoids triggering automounts and does not scan snapshot file contents.
Snapshot counts do not estimate physically reclaimable space.

## Cleanup plans and execution

`bromigos_storage_cleanup.py` plans selected cache cleanup, retirement of originals
from this CLI's completed switches and explicitly selected local snapshot paths.
Plans and journals use the same records as other storage operations. Cleanup does
not import arbitrary external migration scripts or select snapshot history automatically.

The repeatable `cleanup plan --cache` option accepts `npm`, `conda` and
`package-archives`. npm and Conda cleanup plans and apply operations run as the cache
owner, without sudo. They cannot share a plan with package archives, retained originals
or snapshots. A package-archive plan can be created without root; applying it requires
root. Plans for originals or snapshots require root at both stages so their identities
can be inspected. Plans created with sudo normally live in root's state directory.
Use the printed absolute plan path with subsequent sudo commands.

Cache cleanup uses the cache manager's command with a fixed location. npm runs
`cache clean --force`, with its cache pinned to the owner's `~/.npm`; only downloaded
package content in `_cacache` is selected. Conda cleans only downloaded archives,
index data and logs in `~/.conda/pkgs`. Extracted packages and environments stay in
place. Its resolved package-cache list must contain only that pinned directory; extra
cache locations or a forced dry-run setting stop the operation. Package archives use
`paccache` on `/var/cache/pacman/pkg`, retaining three
versions of each package by default. `--keep-versions` accepts a count from 1 to 100.
It applies only to package-archive plans. The preview's allocated
cache size is not the amount these narrower actions will remove.
Close npm, Conda or package-manager clients before cleaning their caches. Apply
checks for running clients, changed paths and nested mounts. Native commands run
in a temporary directory with a minimal environment and explicit cache settings.

An original is eligible only when the completed migration journal identifies it,
the active bind resolves to the planned destination, and fstab still preserves that
binding. Copy-only sources are excluded. Apply checks for open files and working
folders under both the original and destination, including mounted aliases. Keep
writers stopped through cleanup. All originals undergo a fresh checksum and metadata
comparison before any deletion, then another comparison immediately before their
individual removal. Differences retain the data and report the first changed paths.
This includes legitimate changes made after switching; there is no force flag that
bypasses verification.

Snapshots must be discovered through Snapper or btrbk, read-only, unmounted, free of
nested subvolumes, and derived from their configured source. Plans bind the filesystem
UUID, subvolume UUID and ID, source identity and directory identity. Apply rechecks
them before deletion. Snapper selections are deleted through Snapper; btrbk selections
remove only the exact local Btrfs snapshot. Backup streams and other snapshots are
outside the selected plan.

Every apply attempt writes a private timestamped log beside the plan. The journal
records before/after available space, the active deletion and completed paths. Failed
preflight or verification can be retried when no deletion started. Once deletion
starts, failures require inspection and a new plan; partial deletion is not replayed.
An interrupted attempt also requires inspection. Btrfs deletion is synchronised
before measuring space. The final snapshot inventory highlights any new snapshots
created during cleanup without adding them to the approved deletion set.

## Drive health

`bromigos storage health` gives each drive a verdict in plain words. It judges a drive by
how its own health records change over time, not by one reading. An error count that
stopped growing long ago is a quiet line. A count that is rising is an alarm.

Every drive keeps health records about itself. On SATA drives they are called SMART. NVMe
drives keep a health log. bromigOS reads both.

```bash
bromigos storage health               # one line per drive
bromigos storage health nvme0         # one drive: verdict, what to do, readings over time
bromigos storage health nvme0 --all   # every kept reading, not only the newest 30
bromigos storage health --json        # the same, for a script or a screen
```

```text
Drive health, read 12 min ago

  WDC WD40EFRX-68N32N0 (sda)       getting worse  8 reallocated sectors appeared in the last day
  Samsung SSD 980 PRO 2TB (nvme0)  watch          41,870 media errors, unchanged since 3 Nov 2026
  Extreme 55AE (sdc)               cannot tell    it's connected through a USB adapter that doesn't pass the drive's health records on
```

The command reads no drive itself and needs no root. It shows what the system checks last
wrote. They read the drives every 15 minutes and after each boot, as the `disk.smart` check
of [`bromigos alerts`](alerts.md). To read the drives now:

```bash
sudo bromigos alerts check --system --only disk.smart
```

The manual's [Storage](../manual/src/storage.md#check-your-drives-health) page is the
user's side.

### The verdicts

| Verdict | It means | Alert | What to do |
|---|---|---|---|
| healthy | Nothing to report | None | Nothing |
| watch | Old errors that haven't grown for 30 days | Info, never a notification | Nothing while it holds |
| has errors, still checking | Errors that were there at the drive's first reading | Needs you | Check its backup, then wait |
| getting worse | An error count rose in the last 30 days | Needs you | Back up now, plan to replace it |
| replace soon | The drive says so itself, or a count keeps rising | Critical or needs you | Back up, then replace it |
| cannot tell | The drive gives no health records | None | Connect it directly |

The worst reason on a drive decides its verdict. In `--json` the verdicts are `healthy`,
`watch`, `checking`, `worse`, `replace` and `unknown`.

**watch.** One of these, and nothing worse:

- An error count is above zero and hasn't risen for 30 days. The line says since when.
- 90 % or more of an SSD's rated life is used.
- An attribute was past its threshold once, and isn't now.

**has errors, still checking.** The first reading of a drive already had an error count
above zero. Nothing says yet whether the errors are old. The alarm stays for 30 days. If no
count rises in that time, the verdict becomes watch. This is what an install with a
long-stable count sees after it gets this feature: one more month of the alarm, then quiet.

**getting worse.** A count rose in the last 30 days. The line says how fast: "reallocated
sectors rose from 12 to 20 in the last 3 days". If the count holds for 30 days after its
last rise, the verdict becomes watch.

**replace soon.** Any of these:

- The drive's own health check says FAILED. Critical.
- An NVMe drive's spare space is under the drive's own threshold. Critical.
- An NVMe drive raised a critical warning other than temperature. Critical.
- An attribute whose failure predicts a breakdown is past the drive's own threshold now.
  Critical.
- A wear attribute is past the drive's own threshold now. Needs you.
- The drive's newest finished self-test failed. Needs you.
- An SSD says 100 % or more of its rated life is used. Needs you.
- An error count rose on 3 separate days within 30 days. Needs you.

A critical alert reads "A drive is failing". The others read "Replace this drive soon".

**cannot tell.** The line says why: a USB adapter that doesn't pass the records on, a
virtual disk, a memory card, or a drive that didn't answer. bromigOS never guesses a
verdict for such a drive.

Two more rules:

- A drive that answered before and stops answering keeps its last verdict and its alert.
  A dying drive may stop answering, and that must not clear its alarm.
- An NVMe drive that says it is over its temperature limit raises "A drive is too hot".
  Heat doesn't change the verdict.

### When the alarm goes quiet

The alert follows the verdict. An alarm ends when its count has held for 30 days: "has
errors, still checking", "getting worse" or a "replace soon" that came from a rising count
becomes "watch". The alert drops from needs you to info. Its text starts with "The alarm
for this drive is off." for one day, so it is said once. After that it is the plain watch
line. An info alert shows no desktop notification and isn't sent to the phone
([alerts.md](alerts.md#an-alert)).

If the count rises again, the alarm comes back as "getting worse". Its text says from
what to what.

### What is read

`smartctl` reads the drives (package `smartmontools`). The check runs `smartctl --scan -j`,
then `smartctl -j -H -A -i -l selftest DEVICE` for each drive. A plain scan calls every
`sdX` drive `scsi`. That type isn't passed on, so smartctl finds the SATA drive behind it
by itself.

| SATA | From |
|---|---|
| Reallocated sectors | Attribute 5, raw value |
| Sectors it can't read (pending) | Attribute 197, raw value |
| Uncorrectable sectors | Attribute 198, raw value |
| Uncorrectable errors | Attribute 187, raw value |
| Cable (CRC) errors | Attribute 199, raw value. Kept and shown, not judged |
| Its own health check | `smart_status.passed`, and smartctl's exit bit 3 |
| Attributes past their threshold | Every attribute's `when_failed`: `now` or `past` |
| Power-on hours, temperature | `power_on_time.hours`, `temperature.current`. Kept and shown, not judged |
| Self-tests | The newest finished entry of `ata_smart_self_test_log` |

| NVMe | From `nvme_smart_health_information_log` |
|---|---|
| Media errors | `media_errors` |
| Spare space and its threshold | `available_spare`, `available_spare_threshold` |
| Rated life used | `percentage_used` |
| Critical warning | `critical_warning`, a set of bits |
| Unsafe shutdowns | `unsafe_shutdowns`. Kept and shown, not judged |
| Temperature, power-on hours | `temperature`, `power_on_hours`. Kept and shown, not judged |
| Self-tests | The newest finished entry of `nvme_self_test_log` |

A SAS drive's grown defect list (`scsi_grown_defect_list`) is judged like reallocated
sectors.

Without smartctl, or for an NVMe drive smartctl can't read, the check runs
`nvme smart-log /dev/nvme0 -o json` (package `nvme-cli`). The drive's model, serial number
and firmware then come from `/sys/class/nvme/`. With neither tool the check is skipped.

`lsblk` names the drives that give no records, and says how each is connected.

### The numbers, and why

| Number | Value | Why |
|---|---|---|
| Quiet period | 30 days | Long enough for a spreading defect to show |
| Kept rising | 3 separate days within 30 | A knock or a power cut raises a count once, not on three days |
| Worn | 90 % of rated life | A quiet line before the maker's own limit |
| Used up | 100 % of rated life | The maker's own limit for the drive's rated writes |
| Spare threshold | The drive's own | NVMe drives state it (`available_spare_threshold`) |
| Attribute thresholds | The drive's own | SMART compares each attribute itself (`when_failed`) |

These are fixed in `lib/bromigos_drives.py` (`QUIET_DAYS`, `SUSTAINED_DAYS`,
`WORN_PERCENT`, `SPENT_PERCENT`). `--json` gives them under `rules`.

Why a month: on bromigOS Server every drive runs a long self-test each Saturday
([server.md](server.md#disks)), so its whole surface is read four times in the period, and
btrfs scrubs once. A desktop runs no self-tests by itself. There the month covers ordinary
use, and `sudo smartctl -t long DEVICE` reads the whole surface when you want it read.

How the counts are compared:

- A rise is any reading higher than the one before. Rises on one calendar day (UTC) count
  as one.
- A rise found after the drive was away says the whole time away: "in the last 13 days".
- A count that falls is not a rise. Pending sectors fall when the drive reads them again.
  A count back at zero starts over.
- Spare space over the drive's threshold is not judged, however low.

The NVMe critical warning bits:

| Bit | Meaning | Verdict |
|---|---|---|
| `0x01` | Spare space under the threshold | replace soon, critical |
| `0x02` | Over or under its temperature limit | none. "A drive is too hot", needs you |
| `0x04` | Reliability degraded | replace soon, critical |
| `0x08` | Read-only | replace soon, critical |
| `0x10` | Power-loss protection failed | replace soon, critical |
| `0x20` | Persistent memory region read-only | replace soon, critical |

A self-test counts when it finished. A SATA status whose high four bits are 0 passed, and
3 to 8 failed. An NVMe result of 0 passed, and 5 to 7 failed. Aborted and running tests are
passed over, so the newest finished one decides.

### How a drive is told apart

A drive is its model and serial number. Device names such as `nvme0` and `nvme1` swap
between boots, so the history never uses them as the key.

- The key is the model in lower case plus eight hex digits, for example
  `samsung-ssd-980-pro-2tb-0f1c3b46`. The digits are a SHA-256 of the model and the serial
  number.
- The alert's `id` is `disk.smart:<key>`. It stays the same when the device name changes,
  so its first-seen time and a snooze on the phone stay too.
- A new drive in an old drive's slot is a new key with an empty history. The old drive's
  history stays, marked as not connected.
- A drive with no serial number is keyed by its device name. The detail view says so.
- A drive that stops answering often can't say its model or serial number either. It is
  taken for the drive that answered at that device name at the last check, unless `lsblk`
  gives a serial number that ends differently.

### The history file

`/var/lib/bromigos/drives/history.json`, written by the system pass as root, mode 0644. It
is replaced atomically.

| Field | What it holds |
|---|---|
| `schema`, `checked_at` | `1`, and when the drives were last read |
| `drives.<key>.model`, `serial_tail`, `firmware`, `device` | Who it is. Only the serial's last four characters are kept |
| `drives.<key>.first_seen`, `last_seen`, `present` | When it was first and last read, and whether the last check saw it |
| `drives.<key>.readings` | The newest reading |
| `drives.<key>.samples` | Readings over time |
| `drives.<key>.trend` | Per error count: its value, when it was first above zero, and each day it rose |
| `drives.<key>.events` | What happened: a firmware change, a verdict change, a count that fell |
| `drives.<key>.verdict` | The last verdict, its reasons and when it began |

The bounds:

- A reading is kept once a day, and whenever a judged value changes. Temperature and
  power-on hours alone don't add one.
- At most 400 readings per drive, which is over a year. The oldest go first.
- At most 64 drives. The ones gone longest are forgotten first. A connected drive never is.
- At most 64 rise days per count and 40 events per drive.

Times are milliseconds since 1970. A file that can't be read is started again. Deleting
it starts every drive's history again.

### Scripting

`--json` prints `schema`, `checked_at`, `history` (the file's path), `rules` and `drives`.
Each drive has:

| Field | What it is |
|---|---|
| `key`, `device`, `model`, `serial_tail`, `firmware`, `kind` | Who it is. `kind` is `nvme`, `ata` or `scsi` |
| `present`, `first_seen`, `last_seen`, `silent_since` | Whether it's connected, and since when it hasn't answered |
| `verdict`, `words`, `summary`, `advice` | The verdict's name, its plain words, why, and what to do |
| `alert` | The alert's severity: `info`, `needs_you`, `critical` or `null` |
| `since`, `quiet_on` | When the verdict began, and when an alarm goes quiet if nothing rises |
| `reasons` | Each reason: `level`, `text`, and for a count `counter`, `value`, `rise`, `days`, `since` |
| `readings`, `trend`, `events` | As in the history file |
| `samples` | Only with a drive named: every kept reading |

```bash
# the drives that aren't healthy
bromigos storage health --json | jq -r '.drives[] | select(.verdict != "healthy") | "\(.device) \(.words): \(.summary)"'

# one drive's media errors over time
bromigos storage health nvme0 --json | jq -r '.drives[0].samples[] | "\(.t / 1000 | todate) \(.media_errors)"'
```

`DRIVE` is a device name (`nvme0`, `/dev/nvme0`), a key, or part of a model. The command
exits with 0, or 1 when no drive or more than one matches.

The code is `lib/bromigos_drives.py`. Its tests are `tests/alerts/test_drive_health.py`.
They move a clock over drives shaped as `smartctl --json` and `nvme smart-log -o json`
print them (`tests/alerts/drives/`), on the stand-in machine the alerts' tests use.

