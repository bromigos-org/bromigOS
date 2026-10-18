# Local storage

`bromigos storage` manages plans for a local data drive and file migrations. Its default
status command reads devices and journals without changing the machine. User
instructions are in the manual’s [Storage](../manual/src/storage.md) page.

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
Cleanup previews retained data; it never silently deletes original files or snapshots.

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
