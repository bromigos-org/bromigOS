# Activity

Some things a computer does take minutes or hours: setting up the apps you chose, a backup, a
drive test. bromigOS calls each of these a job, and keeps a record of it. The record says what
the job is doing now, which steps are done, and how it ended.

A job doesn't need you to watch it. It carries on when you close the terminal that started
it, and when your SSH connection drops.

## See what your server is doing

```bash
bromigos activity
```

It lists the jobs still going, then the newest ones that ended:

```text
STATE    WHEN       JOB                                  WHAT
running  2 min ago  20261109-2240-app.install-this-c375  Setting up this server: 33 %, step 2 of 3, smb-shares (Installing)
failed   3 h ago    20261109-1931-backup.run-usb-e82e    Backing up to the USB drive: stopped at Copying what changed: The backup drive stopped answering.
```

| State | What it means |
|---|---|
| running | It's working. |
| waiting | It waits for something, such as the internet, and carries on by itself. |
| done | It finished. |
| failed | It stopped. The line says at which step, and why. |
| cancelled | Someone stopped it. |
| interrupted | The computer restarted or lost power while it ran. |

## Look at one job

```bash
bromigos activity show
```

That shows the newest job: each step, any notes it left, the command it ran, and the last
lines it printed. To see another job, give its name from the list, or any part of the name
that only one job has:

```bash
bromigos activity show backup
```

The last lines it printed can hold details about your system, so only an administrator may
read them. `sudo bromigos activity show` shows them.

## What makes a job

On [bromigOS Server](server.md), the welcome tour's **Run** step is a job: it sets up what you
chose at install. You can close the tour while it works. `bromigos activity` shows how far it
got.

bromigOS keeps a job's record for 30 days, and the 200 newest at most.

You can run a command of your own as a job, and give your scripts named steps.
[docs/activity.md](https://github.com/bromigos-org/bromigOS/blob/main/docs/activity.md) has
the details, the record's fields and the JSON output for scripts.
