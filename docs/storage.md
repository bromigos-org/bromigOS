# Local storage

`bromigos storage` manages plans for local data drives, file migrations and cleanup.
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
external labels and paths are escaped.

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
