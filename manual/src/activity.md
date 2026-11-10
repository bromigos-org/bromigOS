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
| needs you | It stopped to ask you something, and waits for your answer. See [below](#when-a-job-needs-you). |
| waiting | It waits for something, such as the internet or another job, and carries on by itself. |
| done | It finished. |
| failed | It stopped. The line says at which step, and why. |
| put back | It failed, then undid what it had changed. Nothing is left half done. |
| cancelled | Someone stopped it. |
| interrupted | The computer restarted or lost power while it ran. |

Two jobs that would change the same thing never run at once. The second one waits, and the
list says which job it waits for.

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

## When a job needs you

Some jobs can't finish without you. Replacing a drive is one: the server gets ready, then
someone has to take the old drive out and put the new one in. The job stops there and asks.

`bromigos activity` shows it as "needs you". `bromigos activity show` prints the question,
the answers you can give, and the command to type:

```text
It asks
  Take the old drive out of bay 2 and put the new one in.
    swapped  I've swapped the drive
  Answer with: sudo bromigos activity answer 20261110-1904-drive.replace-bay-2-7c1e swapped
```

Type that command once you've done what it asks. The job carries on from where it stopped.
It waits for as long as you need. Nothing runs out.

## Stop a job

```bash
sudo bromigos activity cancel backup
```

Give the job's name from the list, or a part of it. bromigOS stops a job only when the job
says stopping is safe. A job in the middle of something that mustn't be cut short refuses,
and tells you why:

```text
bromigos activity: not stopped. The new drive is being filled. Stopping now would leave your files with one copy.
```

`bromigos activity show` says the same before you try.

## When a job fails

A job that fails tells you. It shows up with your other [alerts](alerts.md): in
`bromigos alerts`, as a notification on the desktop, and on your phone if you use BRODEC.
The alert goes away when that job next works.

Some jobs can be started again as they were:

```bash
sudo bromigos activity retry backup
```

`bromigos activity show` prints that command for a job that offers it.

## What makes a job

On [bromigOS Server](server.md), the welcome tour's **Run** step is a job: it sets up what you
chose at install. You can close the tour while it works. `bromigos activity` shows how far it
got.

bromigOS keeps a job's record for 30 days, and the 200 newest at most.

You can run a command of your own as a job, and give your scripts named steps.
[docs/activity.md](https://github.com/bromigos-org/bromigOS/blob/main/docs/activity.md) has
the details, the record's fields and the JSON output for scripts.
