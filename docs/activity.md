# Activity

A long job on bromigOS, such as setting up apps or running a backup, keeps a record: what it
is, its named steps, how far it got and how it ended. `bromigos activity` reads the records.
Each job runs in a systemd unit of its own, so it carries on when the terminal or the
connection that started it goes away.

There is one record format, and the command line is the way in. Other faces of a server, such
as a web page, are meant to read the same commands' `--json`.

The manual's [Activity](../manual/src/activity.md) page is the user's side.

## See what is running

```bash
bromigos activity              # the jobs still going, then the newest that ended
bromigos activity show         # the newest job: steps, notes, command, the log's end
bromigos activity show backup  # a job by its id, or a part of it only one job has
```

```text
STATE   WHEN      JOB                                  WHAT
failed  just now  20261110-0605-backup.run-usb-e82e    Backing up to the USB drive: stopped at Copying what changed: The backup drive stopped answering.
done    3 h ago   20261110-0312-app.install-this-c375  Setting up this server: Done
```

```text
Backing up to the USB drive
  failed just now, after 41 s  ·  backup.run  ·  20261110-0605-backup.run-usb-e82e
  stopped at Copying what changed: The backup drive stopped answering.

Steps
  ✓ Taking a snapshot       done
  ✗ Copying what changed    failed   The backup drive stopped answering.
  · Checking it reads back  todo

Command  /usr/local/bin/backup-to-usb
Unit     bromigos-job-20261110-0605-backup.run-usb-e82e.service
Log      /var/lib/bromigos/activity/jobs/20261110-0605-backup.run-usb-e82e.log

The log's last 2 lines
  rsync: connection unexpectedly closed (0 bytes received so far)
  ::error copy The backup drive stopped answering.
```

Reading needs no privilege, except for the log's lines, which are root's. `list` takes
`--all` and `--limit N`. `show` takes `--log N` for more or fewer of the log's lines, and 0
for all of them.

The first job bromigOS itself runs this way is the Server tour's **Run** step, which applies
the plan chosen at install (`bromigos lab provision --local … --apply`,
[lab-provision.md](lab-provision.md#the-local-target)). Its record's steps are the plan's
items.

## Make a script a job

Any command becomes a job when you start it through `bromigos activity run`:

```bash
sudo bromigos activity run --kind backup.run --title "Backing up to the USB drive" \
    --subject backup:usb:"USB drive" -- /usr/local/bin/backup-to-usb
```

The script runs unchanged. What it prints shows in your terminal and goes to the job's log.
To give the record steps, the script prints progress lines, each on a line of its own:

```bash
#!/bin/sh
echo "::stage 0 Getting ready"
echo "::step snapshot running Taking a snapshot"
btrfs subvolume snapshot -r /srv/data /srv/data/.backup || exit 1
echo "::step snapshot done"
echo "::stage 30 Copying"
echo "::step copy running Copying what changed"
rsync -a /srv/data/.backup/ /mnt/usb/ || { echo "::error copy The backup drive stopped answering."; exit 12; }
echo "::step copy done"
echo "::stage 100 Backed up"
```

| Line | What it does |
|---|---|
| `::stage PCT words` | Sets the share done, 0 to 100, and what is happening now. |
| `::step ID STATE words` | Names a step. STATE is `todo`, `running`, `waiting`, `done`, `failed` or `skipped`. |
| `::item ID STATE` | The same, in the states the lab's provisioning prints. See the table below. |
| `::note ID words` | Something the person should know. With a step's ID, it shows on that step. |
| `::error ID words` | Why it failed, in plain words. With a step's ID, the failure names that step. |

The rules:

- **The exit status decides.** 0 is `succeeded`. Anything else is `failed`. A script that
  prints nothing but exits 1 still gets a failed record, with its last line as the reason.
- **A step's first words are its label.** Words on later lines for the same step are its
  detail. Words that start with `N/M UNIT`, such as `120/400 MB`, also set its progress.
- **The ID is optional** on `::note` and `::error`. The first word counts as an ID when it is
  a step's, or when it is a lower-case word followed by a sentence.
- **Only `::stage` is enough.** A script with no steps still has a title and a share done.
- **A line the parser doesn't know is only output.** It goes to the log, and the job goes on.
- **Flush each line.** In Python, `print(…, flush=True)`. `run` sets `PYTHONUNBUFFERED=1`.

`--kind` is two or more lower-case words joined by dots, such as `app.install`, `backup.run`
or `drive.test`. `--title` is plain words for people. `--subject TYPE:ID[:NAME]` says what
the job is about, so a face can link it to an app or a drive. `--via` and `--device` say who
asked. `--detach` prints the job's id and returns at once. `--json` prints the final record
instead of the output.

`run` ends with the script's own exit status. It ends with 127 when the command isn't there.

How `::item` states become step states:

| `::item` state | Step state | Detail |
|---|---|---|
| `waiting`, `queued` | `todo` | |
| `downloading`, `installing`, `running` | `running` | The state's own word |
| `skipped-offline`, `waiting-for-network` | `waiting` | "Waiting for the internet" |
| `done`, `failed`, `skipped` | The same | |
| Any other word | `running` | That word |

### From Python

A Python command can use the library instead of printing the lines itself:

```python
import bromigos_activity as activity

with activity.job("backup.run", "Backing up") as j:
    j.stage(0, "Getting ready")
    j.step("snapshot", "Taking a snapshot")
    j.step("copy", "Copying what changed")     # the step before it is now done
    j.note("Nothing new since yesterday", "copy")
```

Under `bromigos activity run`, `job()` prints the progress lines and the wrapper keeps the
record. Run on its own, the command keeps the record itself. Then it has no unit, and the
job ends when the process does. An exception ends the job as failed, with the exception's
words. `activity.parse(line)` reads one progress line. The module is in
`/usr/lib/bromigos/lib/`.

## How a job runs

`bromigos activity run` starts a transient systemd unit named `bromigos-job-<id>.service`
with `systemd-run`. Inside the unit, a second `bromigos activity run` starts your command,
reads what it prints, and writes the record. That process is the record's only writer.

- **It needs root.** Jobs belong to the system. When you aren't root, `run` runs itself
  again through `sudo` in a terminal, or through `pkexec` without one, and you type your
  password once.
- **It outlives the caller.** The first `run` only watches. It prints the log's lines as
  they come and ends with the job's exit status. Closing the terminal ends the watcher, not
  the job. `Ctrl+C` does the same, and says how to look at the job later.
- **The unit's command line holds only the job's id.** The command to run goes through a
  root-only file, so its arguments don't show in `systemctl status`.
- **It starts clean.** The command runs as root, in the directory you were in, with
  systemd's environment and not your shell's. `HOME` is root's home. It has no terminal: its
  input is empty.
- **Stopping the unit cancels the job.** `sudo systemctl stop bromigos-job-<id>.service`
  sends the job's process `SIGTERM`. It passes the signal to your command, waits up to 15
  seconds, then kills it. The record ends `cancelled`.
- **The usual tools work.** `systemctl status bromigos-job-<id>.service` shows the processes,
  and `systemctl list-units 'bromigos-job-*'` lists the jobs running now.

### Without systemd

In a container, or anywhere `/run/systemd/system` is missing, `run` runs the job in the
foreground instead. The record, the log and the exit status are the same. The job ignores a
closed terminal and carries on, but it has no unit, so nothing restarts or tracks it.
`Ctrl+C` cancels it. `--detach` can't detach there, and says so.

`BROMIGOS_ACTIVITY_RUNNER=foreground` or `=systemd` chooses for you.

## The record

One JSON file per job, `/var/lib/bromigos/activity/jobs/<id>.json`. It is written whole each
time: a new file takes the old one's place, so a reader never sees half a record.

| Field | Type | Meaning |
|---|---|---|
| `schema` | 1 | The format's version. |
| `id` | string | `YYYYMMDD-HHMM-<kind>-<subject>-<4 hex>`, in UTC. Sorts by time. |
| `kind` | string | What sort of job, such as `app.install`. |
| `title` | string | Plain words for people. |
| `subject` | `{type, id, name}` or null | What the job is about. |
| `state` | string | See [States](#states). |
| `waiting_for` | string or null | `network` while the job waits for the internet. |
| `question` | null | Not used yet. See [Planned](#planned). |
| `steps` | list | See [Steps](#steps). |
| `step` | int or null | The index of the step that started last. |
| `pct` | int or null | The share done, from `::stage`. Null means the job never said. |
| `stage` | string or null | What is happening now, from `::stage`. |
| `notes` | list of `{id, words, at}` | The `::note` lines, 20 at most. |
| `started_at`, `updated_at`, `ended_at` | int | Milliseconds since the epoch, UTC. `ended_at` is null until the end. |
| `requested_by` | `{via, device}` | Who asked. `via` is `cli`, `board`, `phone`, `timer` or `vector`. |
| `unit` | string or null | The systemd unit. Null for a job run in the foreground. |
| `locks`, `can` | list | Empty. See [Planned](#planned). |
| `cancel_safe`, `cancel_note` | bool, null | False and null. See [Planned](#planned). |
| `result` | `{ok, summary, undo}` or null | One sentence on how it ended. `undo` is null. |
| `error` | `{step, words, code, fix}` or null | Why it failed. See below. |
| `exit_code` | int or null | The command's exit status. 128 plus the signal when a signal ended it. |
| `command` | list of strings | The command as typed, with secrets hidden. |
| `log` | string | The log's path. |
| `parent`, `children` | null, list | Not used yet. See [Planned](#planned). |
| `boot_id` | string | The boot the job started in. It tells a restart from a kill. |

`stage`, `notes`, `exit_code` and `boot_id` aren't in the first design. They were added
because the progress lines carry them and a reader needs them.

`error.step` is the failed step's id, or null. `error.words` is the first `::error` line,
or the command's last line when it printed none. `error.code` is one of:

| Code | Meaning |
|---|---|
| `exit` | The command ended with a status other than 0. |
| `signal` | A signal ended the command. |
| `not-started` | The command couldn't be started. |
| `interrupted` | The computer shut down, or the job's process went away without a last word. |

`error.fix` is null for now.

### Steps

Each step is `{id, label, state, started_at, ended_at, detail, progress}`.

- `state` is `todo`, `running`, `waiting`, `done`, `failed` or `skipped`.
- `detail` is a sentence, or null.
- `progress` is `{done, total, unit}`, or null.

When a job ends, its steps end too. On success, a running step becomes `done` and a step
that never ran becomes `skipped`. On failure, the running step becomes `failed`. On cancel or
interruption it becomes `skipped`, with "It stopped here."

### States

```text
queued → running → succeeded
           │  ↘ waiting → running          (the internet came back)
           │  ↘ needs-you → running        (planned)
           ├→ failed
           ├→ rolled-back                  (it failed and put things back by itself)
           ├→ cancelled
           └→ interrupted                  (its process is gone with no last word)
```

- A job is `waiting` while at least one step waits and none runs. The lab's provisioning
  does this while its downloads wait for the internet.
- `rolled-back` is for a job that undoes its own failure. Only the Python library can end a
  job that way today: `j.finish(1, state="rolled-back", words="…")`.
- `queued`, `waiting` and `needs-you` can also end `failed`, `cancelled` or `interrupted`.

For people, `list` and `show` print `succeeded` as "done", `rolled-back` as "put back" and
`needs-you` as "needs you". The JSON always has the names above.

### Interrupted jobs

A job's process holds a lock on `<id>.lock` for as long as it lives. A restart, a power cut
or a kill releases it. A reader that finds an unfinished record whose lock is free shows the
job as `interrupted`, at once and without writing anything. The reason says whether the
computer restarted, by comparing `boot_id`.

The file itself is closed by whoever may write it next: every new job, and `list` or `show`
run as root. So a record never stays `running` after its job is gone.

If the job's process is killed, your command gets `SIGTERM` too, so it doesn't run on with
nobody keeping its record.

A clean shutdown or restart interrupts a job as well. systemd stops the unit, the job's
process sees that the system is stopping (`systemctl is-system-running`), and the record ends
`interrupted` instead of `cancelled`.

## The files

| File | Mode | What it holds |
|---|---|---|
| `jobs/<id>.json` | 0644 | The record. |
| `jobs/<id>.log` | 0640, root | What the command printed, with secrets hidden. |
| `jobs/<id>.log.1` | 0640, root | The log's older half, once it turned over. |
| `jobs/<id>.lock` | 0644 | Held while the job lives. Removed at its end. |
| `jobs/<id>.spec` | 0600, root | What a unit is to run. Removed as it starts. |

They live in `/var/lib/bromigos/activity/`. On bromigOS Server that path is a link to
`/var/lib/bromigos/server/activity/`. That folder is on the state subvolume, which a
rollback of the system leaves alone, so rolling back an update keeps the records.

## The bounds

| What | Bound |
|---|---|
| Finished jobs kept | 30 days, and the newest 200. Both hold. |
| Jobs still going | Never dropped. |
| A record | 64 KiB. Steps' details go first, then the notes. |
| Steps in a record | 100. Later new steps stay in the log only. |
| A title or a label | 120 characters. |
| A detail | 300 characters. A reason or a note: 600. |
| A command | 64 words of 256 characters. |
| A log | 2 MiB, in two halves. The older half goes when the newer one fills. |
| A line of output | 4096 characters. |

Every new job drops what is past the bounds, and so do `list` and `show` run as root.

## What keeps secrets out

Records are readable by everyone on the computer, so nothing secret may reach one.

- **The environment is never stored.**
- **The command is stored with secrets hidden.** The value after an option such as
  `--password` or `--api-key` becomes `***`. So does the value in `NAME=value` when the name
  ends in a word such as `password`, `secret` or `token`.
- **Every word from a progress line is checked the same way** before it becomes a title, a
  label, a detail, a note or a reason. A password in a URL, a secret in a URL's query, a
  `Bearer` token, a private key block and tokens of well-known shapes become `***`.
- **The log gets the same treatment, and is root's.** Output can hold things no pattern
  knows.

This is a net, not a promise. A job must not print secrets, and must not take one as an
argument: every user can read a running command's arguments. Give it a file, or the
[secret store](lab-secrets.md).

Control characters are removed from everything a record stores, and from the log's lines
that `show` prints.

## The JSON

```bash
bromigos activity list --json     # {"schema": 1, "jobs": [record, …]}
bromigos activity show ID --json  # {"schema": 1, "job": record, "log_tail": [line, …]}
sudo bromigos activity run --kind K --title T --json -- COMMAND            # {"schema": 1, "job": record}
sudo bromigos activity run --kind K --title T --detach --json -- COMMAND   # {"schema": 1, "id": …, "unit": …}
```

`log_tail` is null when the caller may not read the log. `list --json` gives 20 jobs unless
you pass `--all` or `--limit N`. A record read this way already shows an interrupted job as
`interrupted`.

Exit status: 0, 1 for a problem said in words such as "no such job", 2 for a wrong command.
`run` ends with the command's own.

## Planned

> **Planned.** Questions and control aren't built yet: `bromigos activity answer`, `cancel`
> and `retry`, jobs that queue on a shared lock, a parent job with a child per app, and an
> alert when a job fails. The fields `question`, `locks`, `can`, `cancel_safe`,
> `cancel_note`, `parent`, `children` and `error.fix` are in the record for them, and hold
> nothing yet. A `::ask` line is kept in the log and changes nothing.

## Tests

```bash
PYTHONPATH=lib python -m unittest discover -s tests/activity
```

The tests use a stand-in root (`BROMIGOS_ROOT`) and stand-in `systemd-run`, `systemctl`,
`sudo` and `pkexec` commands on `PATH` (`tests/activity/fake.py`). No real unit starts and no
password is asked. `BROMIGOS_ACTIVITY_NOW_MS` fixes the clock.

`tests/activity/fixtures/` holds real output of the lab's provisioning, which the parser is
checked against. One test also reads the repository for every `::word` line a command prints,
so a new kind of line can't appear without the parser knowing it.

The `activity tests` workflow runs them on pull requests. The `bromigos-core` package runs
them when it builds.

Real systemd is tested in the ISO workflow. `iso/fieldkit/activity-checks.sh` runs on a
bromigOS Server installed in a virtual machine: real transient units, `sudo`, a session that
ends, the Server tour's apply and a restart. [fieldkit.md](fieldkit.md#testing-it) describes that
test.
