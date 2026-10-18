# Storage

`bromigos storage` helps prepare a local data drive and move files onto it. It separates
planning, copying, verification and switching paths. The original files stay available
until you decide how to retire them.

## See your drives

```bash
bromigos storage status
```

Status reads local devices, mounts, free capacity and saved operation stages. It does not format a drive or
move files. Use `--json` for structured output.

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

## Preview cleanup

```bash
bromigos storage cleanup --preview
```

Cleanup is a preview. It does not delete your originals or home snapshots. Saved
operation status covers this command’s own plans; it does not adopt copies started
by other scripts or earlier sessions. Review
retained data and recovery needs before making a separate cleanup decision.
