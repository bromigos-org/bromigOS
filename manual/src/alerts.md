# Alerts

bromigOS keeps an eye on your computer and tells you when something needs you: a drive that
is failing, a disk that is almost full, a restart an update is waiting for, a backup that
didn't run. It tells you with a notification on the desktop. With BRODEC on your phone, it
also tells you there, wherever you are.

bromigOS never fixes anything by itself. It says what's wrong, in plain words, and what to do.

## What it watches

- **Your drives.** A drive that reports it is failing or wearing out, and errors the file
  system found.
- **Disk space.** A disk that is 90 % full, and again at 97 %.
- **Updates.** Updates waiting, and a restart that a new kernel or graphics driver needs.
- **Backups.** A backup that failed, or didn't run for a day and a half.
- **The UPS.** A UPS (battery backup) that is running on its battery, or running low.
- **Services.** A part of the system that stopped working, such as a web server or file sync.
- **Games.** Problems that stop Steam games from starting ([Playing games](games.md)).
- **After a repair.** What [Field Kit](fieldkit.md) found when it looked at this computer.

On [bromigOS Server](server.md) it also watches game servers, and an automatic update that
Arch Linux news held back.

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

## Turn them off

- Your own checks and the notifications:
  `systemctl --user mask bromigos-alerts-user.timer bromigos-alerts-notify.path`
- The system checks:
  `sudo systemctl disable --now bromigos-alerts.timer bromigos-alerts-boot.timer`

To leave out one check, a disk or a service, edit `/etc/bromigos/alerts.toml` with sudo. The
[alerts docs](https://github.com/bromigos-org/bromigOS/blob/main/docs/alerts.md) list the
settings, and explain how to add a check of your own.
