# Activity

A long job on bromigOS, such as setting up apps or running a backup, keeps a record: what it
is, its named steps, how far it got and how it ended. `bromigos activity` reads the records.
Each job runs in a systemd unit of its own, so it carries on when the terminal or the
connection that started it goes away.

A job can also stop and ask a person a question, wait its turn behind another job, and say
whether stopping it now is safe. `bromigos activity answer`, `cancel` and `retry` are how a
person, or another program, replies.

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

## Answer, stop or start a job again

```bash
sudo bromigos activity answer ID CHOICE   # answer the question a job asks
sudo bromigos activity cancel ID          # stop a job, when it says that is safe
sudo bromigos activity retry ID           # start again a job that ended badly
```

Each needs root, like starting a job. Each first checks the record, which needs no
privilege. So a command the job would refuse never asks for your password.

- **`answer`** is for a job whose state is "needs you". `bromigos activity show ID` prints
  the question, each choice, and the exact command to type. The job then carries on.
- **`cancel`** stops a job only while the job says stopping is safe. Otherwise it refuses
  and prints the job's own reason. A job that only waits for another job hasn't started, so
  it can always be stopped. [Say when stopping is safe](#say-when-stopping-is-safe) has the
  rule.
- **`retry`** starts the same command again, as a new job. It works for a job that ended
  failed, put back, cancelled or interrupted, and that was started with `--retry-safe`.

A refusal ends with exit status 3. [The JSON](#the-json) has the `--json` form of each.

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
| `::ask ID words [CHOICE] label` | Asks a person a question. See [Ask a question](#ask-a-question). |
| `::cancel safe` or `::cancel unsafe words` | Says whether stopping the job now is safe. See [Say when stopping is safe](#say-when-stopping-is-safe). |

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

Four more options say how the job behaves beside other jobs:

| Option | What it does |
|---|---|
| `--lock NAME` | The job needs NAME to itself. See [Jobs that touch the same thing](#jobs-that-touch-the-same-thing). |
| `--parent ID` | The job is a part of job ID. See [A job with parts](#a-job-with-parts). |
| `--cancel-safe` | Stopping the job is safe from the start, until it prints `::cancel unsafe`. |
| `--retry-safe` | Starting the job again after it ended badly is safe. This allows `retry`. |

`run` ends with the script's own exit status. It ends with 127 when the command isn't there.

How `::item` states become step states:

| `::item` state | Step state | Detail |
|---|---|---|
| `waiting`, `queued` | `todo` | |
| `downloading`, `installing`, `running` | `running` | The state's own word |
| `skipped-offline`, `waiting-for-network` | `waiting` | "Waiting for the internet" |
| `done`, `failed`, `skipped` | The same | |
| Any other word | `running` | That word |

### Ask a question

Some jobs can't go on until a person has done something. Replacing a drive is the example:
the job gets the storage ready, then someone has to pull the old drive and push in the new
one. The job prints a `::ask` line and reads the answer:

```bash
#!/bin/sh
# replace-drive: a stand-in for replacing the drive in bay 2
echo "::cancel safe"
echo "::step ready running Getting the pool ready to lose the drive"
# … mark the drive as leaving …
echo "::step ready done"

echo "::step swap running Swapping the drive"
echo "::ask swapped Take the old drive out of bay 2 and put the new one in. [swapped] I've swapped the drive"
read -r answer < "$BROMIGOS_ACTIVITY_ANSWERS"

echo "::cancel unsafe The new drive is being filled. Stopping now would leave your files with one copy."
echo "::step swap done"
echo "::step rebuild running Copying your files onto the new drive"
# … rebuild …
echo "::step rebuild done"
echo "::stage 100 The new drive is in"
```

```bash
sudo bromigos activity run --kind drive.replace --title "Replacing the drive in bay 2" \
    --subject drive:bay-2:"Bay 2" --lock pool --detach -- /usr/local/bin/replace-drive
```

While it waits, the job's state is `needs-you`, and `bromigos activity show` prints:

```text
It asks
  Take the old drive out of bay 2 and put the new one in.
    swapped  I've swapped the drive
  Answer with: sudo bromigos activity answer 20261110-1904-drive.replace-bay-2-7c1e swapped

Stopping it now is safe: sudo bromigos activity cancel 20261110-1904-drive.replace-bay-2-7c1e
```

`sudo bromigos activity answer 20261110-1904-drive.replace-bay-2-7c1e swapped` sends the
answer. The script's `read` returns with `swapped`, and the job carries on.

The rules:

- **The line is `::ask ID words`, then the choices.** ID names the question. Each choice is
  `[CHOICE] label`. The script reads back the CHOICE that was picked, never the label.
- **`[CHOICE!]` marks a choice that destroys something**, such as wiping a drive. The
  record has it as `danger: true`, and `show` adds "this can't be undone".
- **With no choices, the question is a yes or no.** The script reads `yes` or `no`.
- **A question has at most 8 choices.** A choice's id is lower-case letters, digits, dots
  and dashes.
- **The answer comes through a named pipe**, at the path in `BROMIGOS_ACTIVITY_ANSWERS`.
  It is one line. The job's standard input stays empty, so a tool that prompts by surprise
  fails at once and doesn't hang.
- **A job waits for as long as it takes.** Nothing times out. Say with `::cancel safe` that
  the person may stop the job instead of answering, when that is true.
- **A second `::ask` before an answer replaces the first question.** An answer to the old
  one is dropped.
- **Run by hand, a script has no pipe.** `read -r answer < "${BROMIGOS_ACTIVITY_ANSWERS:-/dev/tty}"`
  asks in the terminal instead.

The record keeps what was answered as a note on the question's ID: "Answered: I've swapped
the drive".

### Say when stopping is safe

`bromigos activity cancel` stops a job only when the job has said that stopping is safe. A
job that says nothing can't be cancelled this way, because nobody knows what a half-done job
leaves behind.

- `::cancel safe` says: stopping now loses nothing.
- `::cancel unsafe words` says: don't stop now, and `words` say why. The person who tries
  reads those words.
- `run --cancel-safe` says "safe" from the start, for a command you can't change, such as a
  read-only scan. A later `::cancel unsafe` still wins.

Print the line each time the answer changes. The replace-a-drive script above is safe to
stop until the new drive is in, and unsafe while it rebuilds.

A cancelled job's command gets `SIGTERM`, then 15 seconds, then `SIGKILL`, the same as when
its unit is stopped. The record ends `cancelled`.

`sudo systemctl stop bromigos-job-<id>.service` still stops any job, safe or not. `cancel`
prints that command when it refuses. Use it when you know better than the job.

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

Questions and the cancel rule work the same way:

```python
with activity.job("drive.replace", "Replacing the drive in bay 2") as j:
    j.can_cancel(True)
    j.step("swap", "Swapping the drive")
    choice = j.ask("swapped", "Take the old drive out of bay 2 and put the new one in.",
                   [("swapped", "I've swapped the drive")])
    j.can_cancel(False, "The new drive is being filled.")
    j.step("rebuild", "Copying your files onto the new drive")
```

`ask()` returns the picked choice's id. A choice is `(id, label)`, or `(id, label, True)`
for one that destroys something.

Under `bromigos activity run`, `job()` prints the progress lines and the wrapper keeps the
record. Run on its own, the command keeps the record itself. Then it has no unit, and the
job ends when the process does. `job(…, locks=["pool"])` names its locks for that case.
Under `run`, give them with `--lock`. An exception ends the job as failed, with the
exception's words. `activity.parse(line)` reads one progress line. The module is in
`/usr/lib/bromigos/lib/`.

## Jobs that touch the same thing

Two jobs that change the same thing must not run at once: two app updates, or a backup and a
restore of the same backup store. A job names what it needs to itself with `--lock`:

```bash
sudo bromigos activity run --kind app.update --title "Updating Photos" --lock apps -- …
```

- While another job holds the lock, the new job waits. Its state is `waiting`, its
  `waiting_for` is `another job`, and its `stage` names the job it waits for. Its command
  hasn't started.
- Jobs that wait go in the order they started.
- A job can name several locks. It takes all of them or none, so two jobs can't block each
  other.
- A job that only waits can always be cancelled.
- The lock is free the moment its job ends, however it ends. A power cut frees it too.

A lock's name is a short lower-case word, such as `apps`, `pool` or `backup-repo`. A job
names at most 8. The lock files are in `/var/lib/bromigos/activity/locks/`.

## A job with parts

A big job can run each of its items as a job of its own. "Update every app" is one parent
job with a child job for each app, so each app has its own steps, log and end.

A job started from inside another job becomes its child. Nothing has to be passed: `run`
finds the parent in `BROMIGOS_ACTIVITY_JOB`, which every job's command has. `--parent ID`
names a parent by hand.

```bash
#!/bin/sh
# update-every-app, started with: run --kind app.update-all --lock apps …
for app in photos films; do
    bromigos activity run --kind app.update --title "Updating $app" \
        --subject "app:$app" --lock apps -- update-one-app "$app"
done
```

- The child's record has `parent`. The parent's record lists its `children`.
- A child doesn't wait for a lock its parent holds. Above, each child names `apps` and
  starts at once.
- `cancel` on the parent stops its children too. If one child says stopping isn't safe,
  nothing is stopped.
- Each child ends by itself. A parent decides from its children's exit statuses how it
  ends.
- A parent must still be going when a child starts.

## Lab jobs

The lab's creation jobs show beside the computer's own: each ComfyUI generation (an image, an
edit, a cut-out, a video, a 3D model) and each run of a multi-step tool that writes a **job
feed**, such as an asset pipeline. They are activity records too, with the same states and
steps, so `bromigos activity`, the [Lab board](board.md) and the start page show them with
no second format. `lib/bromigos_labjobs.py` reads them.

```bash
bromigos activity                 # the computer's jobs and the lab's
bromigos activity watch           # live: progress, the stage, the queue, the picture (in kitty)
bromigos activity list --lab      # the lab's only; --server for the computer's only
bromigos activity cancel comfy-studio-a92f9df3-…   # a queued generation leaves the queue,
                                                   # a running one is interrupted
```

A lab job's id says where it is from: `comfy-<instance>-<prompt id>` for a ComfyUI prompt,
`feed-<run>` for a feed run. Stopping a lab job needs no root: it is the ComfyUI's, not the
system's. A feed run can't be stopped from outside; the program that writes it stops it.

### Which ComfyUIs

Each ComfyUI a reader follows, first match by address wins:

1. `[[comfyui]]` tables in `/etc/bromigos/labjobs.toml`, and for a person also in
   `~/.config/bromigos/labjobs.toml`:

   ```toml
   [[comfyui]]
   name = "studio"                      # short: letters and digits
   url = "http://127.0.0.1:8188"        # or a reference: "@env:…", "@private:…", "@file:…"

   [feed]
   dirs = ["/srv/pipeline/feed"]        # more feed folders to read
   media = ["/srv/pipeline/out"]        # where a system feed's pictures may be read from
   ```

2. For a person, their creation settings: `create.toml`'s `[comfyui.<name>]` endpoints,
   `BROMIGOS_COMFYUI_URL` (as `homelab`) and `art.toml`'s `comfyui_url`
   ([art.md](art.md#creation-providers)). `@vault:` references aren't followed: reading
   jobs never asks Vault.
3. With none of these, this machine's own ComfyUI at `http://127.0.0.1:8188`, when something
   answers there.

### What a ComfyUI prompt becomes

Each prompt in the queue and in the recent history (`GET /queue`, `GET /history`) becomes a
record:

- **Its kind and title** come from the workflow. A graph made from one of bromigos art's
  workflows is recognised by the model files it loads and its nodes:
  `Image: Qwen-Image-2512 · a brass telescope`, `3D: Pixal3D · ship-a.png`. Kinds are
  `lab.image`, `lab.edit`, `lab.cutout`, `lab.upscale`, `lab.video`, `lab.model3d`.
- **Its steps** are the graph's stages, in order: load the models, read the inputs, read the
  prompt, sample, decode, save. Only the stages the graph has.
- **Its progress** comes from the websocket: the node that runs, and the sampler's steps
  (`Sample · 21 of 50 steps`). Without it, `pct` is an estimate from how long the same
  workflow took on this ComfyUI before (`lab.estimated` is true). An estimate stops at 95 %.
- **Its queue place**: `lab.position` and `lab.ahead` ("In the queue: 2 ahead").
- **Its end**: done, failed (with ComfyUI's error and the node it failed in), or cancelled
  when it was interrupted. `result.outputs` lists what it wrote.

The record's `lab` object has the rest: `instance`, `prompt_id`, `workflow`, `prompt`,
`client` (who queued it), `queued_at`, `ran_at`, `elapsed_ms`, `estimate_ms`, `preview` and
`interrupt` (true while stopping it means interrupting it).

### Live progress and previews

ComfyUI sends a prompt's progress and its preview frames only to the client that queued it.
To see everyone's prompts live, install the relay node, a ComfyUI custom node with no nodes
that copies those messages to watchers (clients named `bromigos-watch-…`):

```bash
ln -s /usr/share/bromigos/art/comfyui-relay /path/to/ComfyUI/custom_nodes/bromigos-relay
```

Previews also need ComfyUI to make them. bromigos art asks for them with each prompt
(`"extra_data": {"preview_method": "auto"}`). For other tools, start ComfyUI with
`--preview-method auto`.

Without the relay, a watcher still sees the queue, each prompt's stages when it ends, the
outputs, and an estimated progress.

### The follower

`bromigos activity follow` keeps the lab's jobs in a state folder, live: it reads each
ComfyUI every 2 seconds, listens on its websocket, fetches the newest outputs once, and makes
thumbnails (with Pillow). Pages that can't reach the network themselves read its files:

| | A person's | The machine's (`--system`) |
|---|---|---|
| Records | `$XDG_RUNTIME_DIR/bromigos-labjobs/jobs.json` | `/run/bromigos-labjobs/jobs.json` |
| Pictures, clips, models | `~/.cache/bromigos/labjobs/` | `/var/cache/bromigos-labjobs/` |

Media files are named by their content (`pv-`, `th-`, `of-`, `fm-` and 16 hex digits), and
only PNG, JPEG, WebP, GIF, MP4, WebM and GLB are kept, checked by their first bytes. The
folder keeps 512 MB at most; the oldest go first. A reader uses a `jobs.json` only while it
is less than 15 seconds old; otherwise `bromigos activity` reads each ComfyUI itself.
`bromigos activity watch` runs a follower of its own while it watches, when none is running.

### Job feeds

A tool that isn't run by `bromigos activity run` can still show its steps everywhere jobs
show: it appends to a job feed. A feed is a file of JSON lines, one file per run, in a feed
folder:

| Who writes | Folder |
|---|---|
| A person | `~/.local/state/bromigos/activity/feed/<run>.jsonl` |
| root | `/var/lib/bromigos/activity/feed/<run>.jsonl` |
| Either, elsewhere | `BROMIGOS_ACTIVITY_FEED` (folders, `:` between; the first is written) |

The run's name is short lower-case words, digits, dots and dashes (`ships-20261112`). Its
job's id is `feed-<run>`. Each line is one object, written whole, under 4096 bytes:

```json
{"v": 1, "at": 1794513000000, "start": {"title": "Universe assets: ships", "kind": "lab.pipeline", "pid": 4242, "boot_id": "…"}}
{"at": 1794513000100, "line": "::step cutout running Cut out ship-a"}
{"at": 1794513004000, "media": {"path": "/srv/out/ship-a/cut.png", "step": "cutout", "role": "preview"}}
{"at": 1794513004100, "line": "::step cutout done"}
{"at": 1794513090000, "media": {"path": "/srv/out/ship-a/ship-a.glb", "role": "output"}}
{"at": 1794513090100, "end": {"state": "succeeded", "words": "1 ship made"}}
```

- `at` is milliseconds since 1970, UTC.
- `start` begins the run: its `title`, `kind` (starts with `lab.`; default `lab.pipeline`),
  `subject` (`TYPE:ID[:NAME]`), and `pid` with `boot_id`: the process doing the work. When
  that process is gone, the run reads as interrupted.
- `line` is any progress line `bromigos activity run` reads
  ([Make a script a job](#make-a-script-a-job)): `::step`, `::stage`, `::item`, `::note`,
  `::error`. The lines go through the same record a job run would keep, so a feed reads the
  same.
- `media` is a picture, a clip or a 3D model: a step's thumbnail (`role: preview`), or a
  result (`role: output`). A relative path is relative to the feed's folder.
- `end` ends the run: `succeeded`, `failed` or `cancelled`, with words.
- A run that says nothing for an hour reads as interrupted. A run that ended more than 7
  days ago isn't listed. Each folder lists its 30 newest runs.

From Python, `bromigos_labjobs.Feed` writes it, with the same methods as a job's progress
lines ([From Python](#from-python)):

```python
import sys; sys.path.append("/usr/lib/bromigos/lib")
from bromigos_labjobs import Feed

with Feed("ships-20261112", "Universe assets: ships") as feed:
    feed.step("cutout", "Cut out ship-a")
    feed.media("out/ship-a/cut.png")          # a thumbnail of this step
    feed.step("shape", "Shape ship-a")
    feed.output("out/ship-a/ship-a.glb")      # a result
```

Leaving the `with` ends the run: succeeded, or failed with the exception's words. A line that
can't be written is dropped, so a feed never stops the tool that writes it.

From any language, `bromigos activity emit` writes one line:

```bash
bromigos activity emit ships start --title "Universe assets: ships" --pid $$
bromigos activity emit ships ::step cutout running Cut out ship-a
bromigos activity emit ships media out/ship-a/cut.png --step cutout
bromigos activity emit ships media out/ship-a/ship-a.glb --output
bromigos activity emit ships end succeeded 1 ship made
```

The machine's follower reads a system feed's pictures only from the feed's own folder and
`[feed] media` folders.

## When a job fails

A job that ends `failed` raises an alert, the same way a failing drive does
([alerts.md](alerts.md)). It shows in `bromigos alerts`, as a desktop notification, and on
the owner's phone.

- The check is `activity.job`. The job's own process runs it as the job ends, so the alert
  doesn't wait for the 15-minute timer.
- There is one alert for each kind and subject, such as `activity.job:backup.run:backup/usb`.
  A job that fails again doesn't add a second.
- The alert clears when that work next succeeds. A run that was cancelled or interrupted in
  between changes nothing.
- A job that ends `rolled-back` raises an alert for information only. It failed, but it put
  things back, so nothing needs you.
- A parent with a failed child stays quiet. The child's alert says what went wrong.
- The alert holds only what the record holds. It never quotes the log, which is root's.
- Then the job starts the alerts' channels (Discord, a webhook) without waiting for them, so
  the alert goes out at once ([Channels](alerts.md#channels-discord-and-webhooks)). A
  channel can also take every job's result, failed, done or asking, with `job-results`.

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
  seconds, then kills it. The record ends `cancelled`. This works whatever the job says
  about stopping. `bromigos activity cancel` is the careful way.
- **Only the job's process writes its record.** `answer` and `cancel` leave a small request
  file beside the record. The job's process takes it within half a second, acts, and
  removes it. [The files](#the-files) lists them.
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
| `waiting_for` | string or null | Set while `waiting` or `needs-you`: `network`, `another job` or `you`. |
| `question` | `{id, text, choices, asked_at}` or null | Set while `needs-you`. Each choice is `{id, label, danger}`. |
| `steps` | list | See [Steps](#steps). |
| `step` | int or null | The index of the step that started last. |
| `pct` | int or null | The share done, from `::stage`. Null means the job never said. |
| `stage` | string or null | What is happening now, from `::stage`. While it waits for another job: which one. |
| `notes` | list of `{id, words, at}` | The `::note` lines, 20 at most. |
| `started_at`, `updated_at`, `ended_at` | int | Milliseconds since the epoch, UTC. `ended_at` is null until the end. |
| `requested_by` | `{via, device}` | Who asked. `via` is `cli`, `board`, `phone`, `timer` or `vector`. |
| `unit` | string or null | The systemd unit. Null for a job run in the foreground. |
| `locks` | list of strings | The locks the job named. It holds them while it runs, and waits for them while `waiting_for` is `another job`. |
| `can` | list of strings | What a face may offer now: `answer`, `cancel`, `retry`. See below. |
| `cancel_safe` | bool | Whether stopping the job now is safe. |
| `cancel_note` | string or null | Why not, in the job's words, when it gave any. |
| `result` | `{ok, summary, undo}` or null | One sentence on how it ended. `undo` is null. |
| `error` | `{step, words, code, fix}` or null | Why it failed. See below. |
| `exit_code` | int or null | The command's exit status. 128 plus the signal when a signal ended it. |
| `command` | list of strings | The command as typed, with secrets hidden. |
| `log` | string | The log's path. |
| `parent` | string or null | The id of the job this one is a part of. |
| `children` | list of strings | The ids of its parts, 100 at most. |
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

`can` is kept by the job's process on every write, so a face only has to read it:

| In `can` | When |
|---|---|
| `answer` | The state is `needs-you`. |
| `cancel` | The job is still going and `cancel_safe` is true. |
| `retry` | The job ended `failed`, `rolled-back`, `cancelled` or `interrupted`, and was started with `--retry-safe`. |

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
   │       │  ↘ waiting → running          (the internet came back)
   │       │  ↘ needs-you → running        (a person answered)
   │       ├→ failed
   │       ├→ rolled-back                  (it failed and put things back by itself)
   │       ├→ cancelled
   │       └→ interrupted                  (its process is gone with no last word)
   └→ waiting → running                    (another job let go of a lock)
```

- A job is `waiting` while at least one step waits and none runs. The lab's provisioning
  does this while its downloads wait for the internet.
- A job is also `waiting` before it starts, while another job holds a lock it named.
  `waiting_for` tells the two apart.
- A job is `needs-you` from its `::ask` line until the answer. Its steps keep their own
  states: the step that asked stays `running`.
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
| `jobs/<id>.answers` | 0600, root, a named pipe | Where the job's command reads each answer. Removed at the job's end. |
| `jobs/<id>.answer` | 0600, root | An answer on its way to the job. Only one at a time. Removed as the job takes it. |
| `jobs/<id>.cancel` | 0600, root | A request to stop. Removed when the job refuses it, or at the job's end. |
| `jobs/<id>.children` | 0644 | One child's id on each line. Each child adds itself as it starts. |
| `jobs/<id>.retry` | 0600, root | What `retry` starts again: the command and its directory. Only for a job started with `--retry-safe`. |
| `locks/<name>.lock` | 0644 | Held while a job has the lock. Holds that job's id. |

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

- **A command with a secret in it is never kept to start again.** `retry` needs the exact
  command. When hiding secrets changed any word of it, no `<id>.retry` file is written,
  `--retry-safe` says so, and `can` never offers `retry`.

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

```bash
sudo bromigos activity answer ID CHOICE --json   # {"schema": 1, "ok": …, "refused": …, "words": …, "job": record}
sudo bromigos activity cancel ID --json          # the same shape
sudo bromigos activity retry ID --json           # run's shape; when it refuses, the shape above
```

`ok` is true when it was done. Otherwise `refused` says why, and `words` say it for a
person:

| `refused` | Meaning |
|---|---|
| `not-asking` | `answer`: the job has no open question. |
| `no-such-choice` | `answer`: the question has no such choice. `words` list the choices. |
| `unsafe` | `cancel`: the job, or one of its parts, says stopping now isn't safe. `words` are its reason. |
| `ended` | `answer`, `cancel`: the job has already ended. |
| `not-retryable` | `retry`: the job is still going, ended well, or wasn't started with `--retry-safe`. |

Exit status:

| Status | Meaning |
|---|---|
| 0 | Done. |
| 1 | A problem said in words, such as "no such job", or a job that didn't take the request. |
| 2 | A wrong command. |
| 3 | Refused. The job's state doesn't allow it. Nothing was changed. |

`run` and `retry` end with the command's own status.

## Where this differs from the first design

The first design of these records gave each kind of job a fixed list of locks and a fixed
answer to "can it be retried". What shipped has no table of kinds: a kind is any dotted
words. So the command that starts a job names both, with `--lock` and `--retry-safe`.

The design also had no way for a job to say that cancelling is safe. `::cancel` and
`--cancel-safe` are that way.

## Planned

> **Planned.** Undo isn't built: `result.undo`, and `undo` in `can`. Neither is
> `error.fix`, a command that repairs what made a job fail. Both fields are in the record
> and hold nothing yet.

## Tests

```bash
PYTHONPATH=lib python -m unittest discover -s tests/activity
```

The tests use a stand-in root (`BROMIGOS_ROOT`) and stand-in `systemd-run`, `systemctl`,
`sudo` and `pkexec` commands on `PATH` (`tests/activity/fake.py`). No real unit starts and no
password is asked. `BROMIGOS_ACTIVITY_NOW_MS` fixes the clock.

`tests/activity/test_control.py` covers questions and control. Its main case is the
replace-a-drive stand-in above: it asks, waits, is answered and carries on. Others cover two
jobs on one lock, a cancel refused while unsafe, `retry`, a parent with a child, and the
alert.

`tests/activity/test_labjobs.py` covers lab jobs: a real ComfyUI's `/queue` and `/history`
(`tests/activity/fixtures/comfyui/`, names scrubbed) as records, the websocket's frames, the
follower's files, stopping a prompt, feeds and their writer, the command line, and the relay
node. A stand-in answers every request; no ComfyUI is called.

`tests/activity/fixtures/` holds real output of the lab's provisioning, which the parser is
checked against. One test also reads the repository for every `::word` line a command prints,
so a new kind of line can't appear without the parser knowing it.

The `activity tests` workflow runs them on pull requests. The `bromigos-core` package runs
them when it builds.

Real systemd is tested in the ISO workflow. `iso/fieldkit/activity-checks.sh` runs on a
bromigOS Server installed in a virtual machine: real transient units, `sudo`, a session that
ends, the Server tour's apply, a job that asks and is answered, and a restart. [fieldkit.md](fieldkit.md#testing-it) describes that
test.
