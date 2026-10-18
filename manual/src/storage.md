# Storage

`bromigos storage` helps prepare a local data drive and move files onto it. It separates
planning, copying, verification and switching paths. The original files stay available
until you decide how to retire them.

## See your drives

```bash
bromigos storage status
```

Status groups the mounted folders under each filesystem, with its used space,
available space and usage bar. Each filesystem's capacity appears once. Btrfs
subvolumes and bind mounts share that capacity. RAM-backed swap is not listed as
a physical drive. Use `--json` for structured output.

## Plan a data drive

Find the stable device name in `/dev/disk/by-id/`. Check its model, serial number and
capacity against the physical drive. Replace `<device-id>` below with that name and
choose one named mount directory directly under `/mnt`:

```bash
bromigos storage plan --device /dev/disk/by-id/<device-id> --mount /mnt/Data \
  --roles development,games,downloads,vms,models
```

Read the resulting plan before applying it. Preparing a drive is destructive. Back up
anything you need from that device first. Existing disks are not a substitute for a
backup of important data.

When the device and plan are correct, apply it yourself in a terminal. Use the
absolute plan-file path printed by planning, since root uses a different home directory:

```bash
sudo bromigos storage apply /absolute/path/to/plan.json
```

Applying asks you to type the exact disk serial number in your terminal. It erases
the whole disk, creates one GPT partition, mounts the filesystem and writes its
mounts to `/etc/fstab`. If it fails, inspect the journal before trying anything else.
The same erase plan cannot be applied twice.

The data filesystem is Btrfs. Each selected role gets a separate subvolume, which is a
folder Btrfs manages independently. Roles share the drive’s free capacity. They do not
reserve space or impose quotas. VM storage can fill the same free space used by other
roles. This flow does not configure encryption or automatic snapshots.

The `development` role comes first and mounts at `/mnt/Data` itself. Other selected
roles mount under it as `/mnt/Data/games`, `/mnt/Data/downloads`, `/mnt/Data/vms`
and `/mnt/Data/models`. VMs are owned by root; the other role roots belong to the
user who created the plan. Choose roles explicitly when you need fewer of them.

## Copy files before switching

Plan a copy with explicit source and destination directories:

```bash
bromigos storage migrate plan --source /path/to/source --destination /mnt/Data/projects
```

Keep the displayed plan ID and absolute saved-plan path. Copying preserves owners,
permissions and extended attributes, so run it with administrative access. Then
verify it and read its status:

```bash
sudo bromigos storage migrate run /absolute/path/to/plan.json
sudo bromigos storage migrate verify /absolute/path/to/plan.json
bromigos storage migrate status <plan-id>
```

A copied directory has not necessarily been verified. Verified files have not
necessarily replaced the paths your applications use. Check the recorded stage before
continuing.

| Stage | Meaning |
|---|---|
| `planned` | The paths are recorded; copying has not started. |
| `copying` | Data is being staged. The source stays in place. |
| `staged` | The copy pass finished; checksum verification is still separate. |
| `verified` | The staged files and metadata matched at the last check. |
| `switching` | Path changes have started. Inspect the journal if interrupted. |
| `switched` | The switch finished and the original data is retained. |

If copying stops, inspect its status and resume the same plan:

```bash
sudo bromigos storage migrate resume /absolute/path/to/plan.json
```

For several moves, write a TOML file and use `--spec /path/to/moves.toml` instead
of `--source` and `--destination`:

```toml
[[move]]
source = "/path/to/source"
destination = "/mnt/Data/projects"
keep_path = "/path/to/source"
```

`keep_path` is optional. Set it when applications must keep using an existing path.
Switching requires at least one such path. For a copy without one, verify the copy
and update your application's storage setting yourself.
If it is the source path, switching retains the original as
`<source-name>.before-storage-<plan-id>` beside the old directory and places a bind
mount at the old path. A bind mount makes the destination
appear at that path. Without `keep_path`, the original path stays as it was; update
your applications to use the destination yourself.

Stop every application or service that writes to the source before the final
verification and switch. Log out of all graphical sessions and use a text console
for the switch. Keep writers stopped while switching. The original copy is
retained for recovery; the switch does not make a backup unnecessary. The command
does not stop applications, services or graphical sessions for you. It refuses the
switch while processes still use the affected paths. Once writers are stopped, switch
using the absolute saved-plan path:

```bash
sudo bromigos storage switch /absolute/path/to/plan.json --writers-stopped
```

The command asks you to type `SWITCH` and the plan ID in your terminal. It performs
a fresh final copy and checksum comparison before changing paths. Inspect the journal after any failed
or interrupted switch before trying to continue. A switch in progress or marked
`switch-failed` cannot be replayed automatically. Its journal lists retained source
paths and the saved fstab file for manual recovery. Do not delete the old directory
merely because the destination exists.

## Review cleanup and snapshots

```bash
bromigos storage cleanup --preview
```

The preview lists supported cache locations and local snapshots managed by Snapper
and btrbk. It shows when a provider cannot be inspected; run the preview with sudo
if it reports access restrictions. Cache entries are informational and are not
removed by this command. Snapshot counts and file sizes are not promises of space
reclaimed. Other snapshots can still hold the files after originals are deleted.

## Retire migrated originals

After a successful switch, create a cleanup plan for its retained originals:

```bash
sudo bromigos storage cleanup plan --migration /absolute/path/to/migration-plan.json
```

Planning records the exact directories without deleting them. It accepts completed
switches made by this CLI. External scripts and their records are not imported.
Copy-only sources are kept because they may still be in use.

Close applications and services using the affected data before applying the cleanup.
Keep them stopped until it finishes. The command checks open files, working folders,
mounts, fstab and checksums. If active files have changed since switching, it keeps
the original and lists differences for review. It never overwrites the active copy.

Use the absolute **cleanup plan** path printed by planning:

```bash
sudo bromigos storage cleanup apply /absolute/path/to/cleanup-plan.json
```

It asks you to type `CLEANUP` followed by the plan ID. For an already reviewed plan,
add `--yes` to skip that confirmation. Administrative authentication can still be
required. Original-copy deletion cannot be undone by this command.

## Remove selected snapshot history

Copy an exact snapshot path from the cleanup preview. You can repeat `--snapshot`
to select several paths in one plan:

```bash
sudo bromigos storage cleanup plan --snapshot /absolute/path/to/snapshot
```

Read the plan, then apply it using the same `cleanup apply` command above. Deleting
a snapshot removes that rollback point. Only the listed local snapshots are selected;
NAS backup streams and other snapshots are kept. Removing btrbk source snapshots
can make its next backup send a full copy. Root snapshots are included only
if you explicitly select their paths. Snapshot cleanup is never inferred from the
amount of free space.

The command waits for Btrfs to finish removing the selected snapshots, reports actual
available space before and after, and lists remaining snapshots. A snapshot created
while cleanup runs is reported for separate review. It is not automatically deleted.

## Read cleanup progress and errors

```bash
sudo bromigos storage cleanup status /absolute/path/to/cleanup-plan.json
```

Each attempt saves a private log beside the plan, including errors. Status shows the
log path, completed deletions and available-space measurements. Add `--json` for the
full record. If checks failed before deletion, address the reported problem and retry
the same plan. If deletion started and then failed or was interrupted, inspect the
log and completed paths before making a new plan. The command refuses to replay a
partial deletion automatically.
