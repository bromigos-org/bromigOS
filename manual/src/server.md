# bromigOS Server

bromigOS Server is bromigOS without a desktop, for servers and the machines in your lab.
It starts to a text console in bromigOS's colours. You look after it over SSH, from that
console, or from BRODEC on your phone.

It has everything in bromigOS that doesn't need a screen: the `bromigos` command, the lab
console, the terminal apps, and [Field Kit](fieldkit.md)'s repairs. It adds:

- **SSH with keys only**, if you turn it on during the install. Someone who keeps guessing
  is blocked for a while.
- **A firewall** that lets in SSH, your lab's monitoring and `.local` names, and nothing
  else.
- **Automatic updates that undo themselves.** Each one takes a snapshot first. If the
  server doesn't come back healthy, the update is rolled back by itself.
- **A watch on its disks.** A disk that's failing or too hot shows in `bromigos server`.
  Once a month the server checks every file against its checksum.
- **A clean shutdown on a UPS.** Plug one into USB and the server finds it by itself.
- **Backups every night**, once you say where to. One command says whether they're healthy
  and [gets your files back](#get-your-files-back).
- **Containers** with Podman. The `docker` command works too.
- **Your lab's monitoring** and its cluster. Find my lab sees the server as soon as it's on
  your network.

## Install it

Start the bromigOS USB stick and choose **Install bromigOS Server** in its boot menu, or
**bromigOS Server** at **What kind of computer is this?** ([The installer](installer.md)).
Or start [Field Kit](fieldkit.md) from its USB stick and choose **Install bromigOS Server**
in its boot menu, or **Install › bromigOS Server (no desktop)** in Field Kit. Both images
are on the [Download page](https://bromigos.org/download). Nothing is downloaded, unless
you pick something marked as needing the internet, or the computer has an NVIDIA graphics
card: NVIDIA's driver isn't on the sticks, so it downloads during the install, or with no
internet it installs by itself at the first update with it. The installer's server steps (its roles, where its keys live, network, who can sign
in, data disks, encryption, updates and what it runs) are in [Setting up bromigOS
Server](server-setup.md).

## Roles: what the server is for

During the install you pick one or more roles. You can add or remove one later.

| Role | What it's for |
|---|---|
| **Lab node** | Joins your lab and runs what it gives this computer. Your lab sets it up from your desktop. |
| **Storage** | Keeps files for the house and backups for the lab. Your computers see it as a network drive. |
| **Home services** | Runs apps for the household, each with its own name on your network. |
| **Media** | Your own movies, shows and music, and Den TV on every screen. Your desktops find it by themselves. |
| **Game server** | Hosts games for friends, started and stopped from your phone. |
| **Just a server** | The safe base and nothing else. |

Game server comes two ways. **On its own**, games run as containers, with no lab needed.
**With your lab's Pelican panel**, your lab runs the games here through Pelican's Wings;
that way needs the internet.

**Cockpit** is an extra, not a role: a web page for looking after the server from your
local network. It isn't installed unless you add it.

```bash
bromigos server roles                      # every role, and which are on
sudo bromigos server role add storage      # turn one on
sudo bromigos server role remove storage   # and off again
sudo bromigos server role add cockpit      # the Cockpit extra (needs the internet)
```

## Backups

Say where in `/etc/bromigos/server.toml`: your lab's S3, any S3 or SFTP server, or a USB
disk.

```toml
[backup]
to = "s3:https://s3.example/backups/myserver"
```

The backup runs every night after the update, and is checked every week. After the first
one, show its key and keep it somewhere safe, away from the server: without it no one can
read the backup.

Your apps' data is always in it, on whichever disk it is kept. The server looks for it in
each backup, app by app, and a backup without one counts as failed. Before each backup the
server also makes a clean copy of every app's database, so it opens when you restore it
even though the app was running. An app you add after a backup isn't a problem: the status
says it's "not in a backup yet", and when the next one runs.

```bash
sudo bromigos server backup key
```

### Is the backup working?

```bash
bromigos lab backups
```

The first line is the answer, in plain words, such as *"Backed up 6 hours ago. Last test
restore: 12 days ago, passed."* or *"No backup in 9 days: the drive at /mnt/backup is not
connected."* Under it are the last backup, the last check, and how many backups are kept.
[Alerts](alerts.md) tell you the same thing when it needs you.

Once a month the server does a **test restore**: it restores a sample of the backup's
files to a scratch folder, checks them, and removes them. So you know the backup gives
files back before the day you need it. `bromigos lab backups test` runs one now.

### Get your files back

1. **Find it.** `list` shows every backup. `show` looks inside one, a folder at a time.

   ```bash
   bromigos lab backups list
   bromigos lab backups show 1f3a9c2e /home/ada/documents
   ```

2. **Restore it.** Name the backup and the file or folder. With no backup named, it's the
   newest. With no path, you get everything.

   ```bash
   bromigos lab backups restore 1f3a9c2e /home/ada/documents
   ```

3. **Copy back what you need.** The files are in a new folder,
   `/srv/restore/backup-<date>-<id>/`, each at its old path inside it. The last lines say
   where, and how many files came back.

Nothing on the server is replaced, so this is safe to try. It checks there's room before it
starts and tells you each step. If you stop it, the folder keeps a name ending in
`.partial` until every file is back.

The commands ask for your password by themselves. You don't type `sudo`.

**To put files back where they were**, over what's there now, add `--in-place`. That only
shows what would be replaced. Add `--apply` to do it: it asks you to type `yes`, takes a
snapshot of the files as they are first, and never deletes anything.

```bash
bromigos lab backups restore 1f3a9c2e /etc/caddy --in-place           # look
bromigos lab backups restore 1f3a9c2e /etc/caddy --in-place --apply   # do it
```

If the server itself is gone, the backup still restores with restic on any computer, with
the key you kept. The [Server docs](https://github.com/bromigos-org/bromigOS/blob/main/docs/server.md#restore-without-bromigos)
have the commands, every flag, and `--json` for scripts.

### A Go Bag: a backup you carry away

A backup that sits beside the server is lost with it in a fire or a theft. A **Go Bag** is
a USB drive with a copy of the backup on it, which you keep somewhere else. It works with
the nightly backup, or by itself.

1. **Set it up, once.** Plug a USB drive in and run:

   ```bash
   bromigos lab backups go-bag setup
   ```

   It sets the drive up and makes the first copy. If the drive has files on it, or is new
   and has to be formatted, it stops and says what it would do and how to agree. It never
   deletes anything you didn't agree to. A disk the server itself uses is always refused.

2. **Take it away.** When the last line says *"Safe to unplug"*, unplug the drive and keep
   it in another place.

3. **Bring it back now and then.** Plug it in. The copy starts by itself: you don't run
   anything. `bromigos activity` shows how far it is. Wait for *"Safe to unplug"* again.

The copy is encrypted with the backup's key, so a lost drive gives nothing away. Keep the
key somewhere else too (`sudo bromigos server backup key`): without it, you can't read the
drive either.

If the drive hasn't been back for 30 days, the server reminds you: *"Your Go Bag drive
hasn't been updated in 31 days. Plug it in."* It's on the first line of `bromigos lab
backups` and in your [alerts](alerts.md).

To get files back from the drive, plug it in and add `--from go-bag` to the commands above:

```bash
bromigos lab backups list --from go-bag
bromigos lab backups restore --from go-bag /home/ada/documents
```

`bromigos lab backups go-bag` shows which drive it is, whether it's plugged in, and when
it last had a good copy. The [Server docs](https://github.com/bromigos-org/bromigOS/blob/main/docs/server.md#the-go-bag)
have every flag.

## Look after it

```bash
bromigos server status        # SSH, the firewall, the last update, roles, backups, disks
bromigos lab backups          # are the backups healthy, and getting files back
bromigos server update --now  # update now (it still checks and rolls back by itself)
sudo bromigos server firewall allow web   # open ports 80 and 443 to everyone on the internet
bromigos update --rollback    # undo the last update yourself
```

If it won't start, choose **bromigOS Field Kit** in the boot menu. The boot menu also has
a second kernel, under Advanced options: the server starts the long-term-support one, and
the newest one stays there in case it's needed.

## Your apps

See the apps your server runs, add one, or take one away:

```bash
bromigos lab apps                       # each app: running or not, its memory, its data, its page
bromigos lab apps list --all            # what else it can run
sudo bromigos lab apps add photos       # add Photos, and anything it needs
sudo bromigos lab apps remove photos    # take it away; your photos stay
```

**Removing an app keeps your data.** Your photos stay in `/srv/apps/photos`, with the app's
keys. Add the app again and it finds them. To delete the data as well, add
`--delete-data`. It asks you to type the app's name first, because the data is gone for
good.

`bromigos lab apps remove photos --plan` says what would stop, what stays and how big it
is, and changes nothing. An app that another app needs can't be removed until that one is.

Adding and removing keep going if you close the terminal. `bromigos activity` shows how
far they got. If an app says **Down** or **Degraded**:

```bash
bromigos lab apps logs photos           # what it said
sudo bromigos lab apps restart photos   # start it again
```

For scripts, every command takes `--json`. The
[lab docs](https://github.com/bromigos-org/bromigOS/blob/main/docs/lab.md#apps-on-a-server)
have where each number comes from, the exit codes and the JSON.

## The Lab board

The Lab board is the server's own web page. Open `https://<server>.local` in a browser on
your home network, where `<server>` is your server's name. The Home services, Media,
Storage and Game server roles set it up.

Before you sign in, the page shows your household's apps, each with a link that opens it.
To see everything else, sign in with a one-time code. Run this at the server, or over SSH:

```bash
sudo bromigos server board code
```

Type the code on the page. It works once, for ten minutes, and the browser stays signed in
for 30 days. The page answers only your home network and your lab's private network, never
the internet.

The first time, your browser warns that it doesn't know the page's certificate. The server
made its own, as it does for every app's address. The warning shows once per browser.

```bash
sudo bromigos server board sessions             # the browsers signed in
sudo bromigos server board sessions --end ID    # sign one out
```

The board's pages are still being built: until they land, the page lists the apps. The
[Lab board docs](https://github.com/bromigos-org/bromigOS/blob/main/docs/board.md) have
the API and everything it reads.

## Where your apps keep their data

If you gave the server data disks during the install, most of your apps keep their data
on them: photos, passwords, documents, home automation, the media apps, file sync. With
two copies (RAID1), one disk can fail without losing any of it. Without data disks, the
apps' data is on the system disk.

**Your passwords are in the nightly backup**, wherever they are kept, once you've told
the server where backups go ([Backups](#backups)).

`bromigos lab app-data` says where the apps' data is, and names anything that isn't on
the data disks.

A server set up before November 2026 keeps its passwords (Vaultwarden) on the system
disk, in `/var/lib/vaultwarden`. They are safe there and the app goes on working. On a
server with data disks, the command below moves them with the rest.

A server installed before November 2026 may say the apps' data is on the system disk, not
the data disks. That was a fault in the installer. Your phone gets an alert about it, and
one command puts it right:

```bash
sudo bromigos lab app-data move --dry-run   # shows what it would do
sudo bromigos lab app-data move
```

The move stops your apps, copies their data to the data disks, compares every file with
its copy, and starts the apps again. It does the same for your media library and for the
backups other computers keep on this server, when those are on the system disk too. Your
passwords go last: it stops Vaultwarden, copies the vault, checks the copy, and starts
Vaultwarden on it. If Vaultwarden doesn't come up on the copy, it puts the vault back
where it was. It keeps each old copy, under a name that says what it is, until you remove it:

```bash
sudo bromigos lab app-data remove-old
```

Pick a quiet time: the apps are off while the copy runs. If anything goes wrong, the move
stops and your apps start again where they were.

## For power users

- Settings: `/etc/bromigos/server.toml`, then `sudo bromigos server setup`.
- Your own services: Quadlet files in `/etc/containers/systemd/`. They start at boot and
  restart when they fail. One you mark `AutoUpdate=registry` updates after the system does.
- The apps bromigOS sets up as containers aren't marked. Each stays at the version it
  was installed with: they don't update by themselves yet. Apps that are packages, such
  as Vaultwarden and Syncthing, update with the system.
- The apps keep their data in `/srv/apps`, the media library is `/srv/media`, and other
  machines' backups are in `/srv/backups` ([above](#where-your-apps-keep-their-data)).
- WireGuard and Tailscale are installed and off. Turn on the one you use.
- AppArmor and a few hardening settings are on. Logs are kept for a month, 1 GiB at most.
- SSH lets in the account made at install and anyone you add to `bromigos-ssh`
  (`sudo gpasswd -a NAME bromigos-ssh`).

The contributor notes, with every setting and the role files' format, are in
[docs/server.md](https://github.com/bromigos-org/bromigOS/blob/main/docs/server.md).
