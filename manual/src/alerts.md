# Alerts

bromigOS keeps an eye on your computer and tells you when something needs you: a drive that
is failing, a disk that is almost full, a restart an update is waiting for, a backup that
didn't run. It tells you with a notification on the desktop. With BRODEC on your phone, it
also tells you there, wherever you are.

bromigOS never fixes anything by itself. It says what's wrong, in plain words, and what to do.

## What it watches

- **Your drives.** A drive that says it is failing, or whose error counts are rising, and
  errors the file system found. A few old errors that stopped growing don't alarm: they
  are a quiet line ([Storage](storage.md#check-your-drives-health)).
- **Disk space.** A disk that is 90 % full, and again at 97 %.
- **Updates.** Updates waiting, and a restart that a new kernel or graphics driver needs.
- **Backups.** A backup that failed, or didn't run for a day and a half. On
  [bromigOS Server](server.md#is-the-backup-working), also a
  [Go Bag](server.md#a-go-bag-a-backup-you-carry-away) drive that hasn't been plugged in
  for 30 days, a test restore that failed, or
  none passing for 45 days.
- **The UPS.** A UPS (battery backup) that is running on its battery, or running low.
- **Services.** A part of the system that stopped working, such as a web server or file sync.
- **Games.** Problems that stop Steam games from starting ([Playing games](games.md)).
- **After a repair.** What [Field Kit](fieldkit.md) found when it looked at this computer.

On [bromigOS Server](server.md) it also watches game servers, an automatic update that
Arch Linux news held back, and whether a server with data disks keeps its apps' data,
media library and passwords on them
([Where your apps keep their data](server.md#where-your-apps-keep-their-data)).

## See the alerts

```bash
bromigos alerts
```

It lists every alert, worst first, each with what to do. **CRITICAL** means act now, such as
copying your files off a failing drive. **NEEDS YOU** means soon. **info** is just so you
know.

The checks run by themselves: every 15 minutes, after each start, and when you log in. To
check again now, run `bromigos alerts check`, or `sudo bromigos alerts check --system` for the
drives and services.

## The notifications

A notification shows when something needs you, once. If the problem is still there, it
shows again later: after 6 hours when it's critical, after a day otherwise. It also shows
again when the problem gets worse. A few at a time at most: the rest are summed up as "And 3
more alerts on this computer".

## On your phone

[Pair your phone](phone.md) with BRODEC. Its alerts list every one of your computers. Each
alert has buttons: **Restart now** when an update waits for a restart, **Snooze**, and **Fix
it**. Fix it asks VECTOR, the desktop's AI assistant, for a plan, with the exact commands.
Nothing runs until you approve it with your fingerprint.

When the problem goes away, the alert clears by itself.

## On Discord, or anywhere else

bromigOS can post alerts to a Discord channel. In Discord, open the channel's **Edit Channel
› Integrations › Webhooks**, make a webhook and **Copy Webhook URL**. Then:

```bash
sudo bromigos alerts channels add discord
```

Paste the address when it asks. It doesn't show, and it's kept where only root can read it.
Then `sudo bromigos alerts channels test discord` posts a message marked TEST.

- **Short by default.** A Discord message says only "1 alert needs you on your lab", because
  other people can often read a Discord server. Add `--detail full` for the machine's name,
  the drive and the command that fixes it. Passwords, keys and home network addresses are
  never sent.
- **Read only.** You can't act on an alert from Discord. Use BRODEC on your phone, or the Lab
  board.
- **Choose what it gets.** `--severity critical` for critical alerts only, `--sources
  drives,backups` for some kinds, `--quiet 22:00-07:00` to keep the night quiet,
  `--resolved` to hear when a problem clears. `--sources alerts,job-results` adds each long
  job that finishes, fails or asks you something.

A webhook does the same for your own tools, such as Home Assistant:
`sudo bromigos alerts channels add webhook home`. Each one is signed, so your tool can tell it
came from your computer. `bromigos alerts channels` lists every channel, and `sudo bromigos
alerts channels remove discord` stops one. The
[alerts docs](https://github.com/bromigos-org/bromigOS/blob/main/docs/alerts.md#channels-discord-and-webhooks)
have every setting and the webhook's format.

## Turn them off

- Your own checks and the notifications:
  `systemctl --user mask bromigos-alerts-user.timer bromigos-alerts-notify.path`
- The system checks:
  `sudo systemctl disable --now bromigos-alerts.timer bromigos-alerts-boot.timer`

To leave out one check, a disk or a service, edit `/etc/bromigos/alerts.toml` with sudo. The
[alerts docs](https://github.com/bromigos-org/bromigOS/blob/main/docs/alerts.md) list the
settings, and explain how to add a check of your own.
