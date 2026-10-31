# bromigOS Server

> **For the installer's Server screens:** the role cards read the role files described in
> [Roles](#roles) (their keys are in [the table](#the-role-files-keys)). On the Field Kit
> stick, the same data is in `edition.json`'s `roles`. What the installer writes and runs is
> in [For the installer](#for-the-installer).

bromigOS Server is bromigOS installed without a desktop. It's for servers and the machines
in a homelab. It boots to a text console in bromigOS's colours, and you manage it over SSH
or from that console.

It has everything in bromigOS that doesn't need a screen: the `bromigos` command, the lab
console, the terminal apps (LazyVim, tmux, lazygit), herdr, and Field Kit's repairs. On top
of that it adds what a server needs:

- **SSH, with keys only**, when you choose it at install. An address that keeps guessing
  is blocked for a while.
- **A firewall** that lets in SSH, ping, the lab's monitoring and `.local` names, and drops
  the rest.
- **Safe automatic updates.** Each one takes a snapshot first. If the server doesn't come
  back healthy, the update is rolled back by itself.
- **A watch on its disks**, a monthly check of its files, and a clean shutdown when a UPS's
  battery runs low.
- **Backups**, every night, once you say where to.
- **Containers**, with Podman and the `docker` command.
- **Roles**: Lab node, Storage, Home services, Game server, or Just a server. You pick them
  at install, or add them later.
- **The lab's monitoring**: the node exporter the lab's Prometheus reads.
- **The lab's cluster**: the lab's workstation can add it to its k3s cluster.

You install it from the [Field Kit](fieldkit.md) medium. Everything it needs is on the
medium, so installing needs no network. The package is `bromigos-server`.

This page is for contributors. The manual's [bromigOS Server](../manual/src/server.md) page
is for people running one.

## The base

Every bromigOS Server gets these, whatever its roles. Each part is on by itself unless
the table says otherwise.

| Part | What it does for you | Package |
|---|---|---|
| SSH limits and sshguard | Fewer guesses, and an address that keeps guessing is blocked ([SSH](#ssh)) | `openssh`, `sshguard` |
| The firewall | Nothing comes in unless a role or you open it ([The firewall](#the-firewall)) | `nftables` |
| Safe updates | Snapshot, update, check, roll back ([Updates](#updates)) | `snapper`, `snap-pac` |
| Logs that never fill the disk | [Logs](#logs) | `systemd` |
| A watch on the disks, and a monthly scrub | [Disks](#disks) | `smartmontools`, `btrfs-progs` |
| A clean shutdown on a UPS | Only when one is plugged in ([Power](#power)) | `nut` |
| Backups | Off until you say where ([Backups](#backups)) | `restic` |
| Find my lab and `.local` names | [Find my lab](#find-my-lab) | `avahi`, `nss-mdns` |
| Wake-on-LAN | BRODEC's Power on button can start the server ([Wake-on-LAN](#wake-on-lan)) | `ethtool` (`bromigos-core`'s) |
| AppArmor and the hardening settings | [Hardening](#hardening) | `apparmor` |
| The LTS kernel first | [The kernel](#the-kernel) | `linux-lts`, `linux` |
| WireGuard and Tailscale | Installed, off. Turn on the one you use | `wireguard-tools`, `tailscale` |
| BRODEC's machine agent | Optional until `brodec-machine` is published ([BRODEC on your phone](#brodec-on-your-phone)) | `brodec-machine` |
| Cockpit | Not installed. An extra you can add ([Roles](#roles)) | `cockpit` |

All of the base is on the Field Kit stick, so Server installs with no network.

## Roles

A role is what the server is for. Roles stack: one box can be Storage and Home services.
You pick them on the installer's cards, or add one later:

```bash
bromigos server roles                       # every role, and which are on
sudo bromigos server role add storage       # one on
sudo bromigos server role remove storage    # and off again
```

| Role | In plain words | What it adds |
|---|---|---|
| **Lab node** | Joins your lab and runs what it gives this computer. The lab sets it up from your desktop. | The `lab-cluster` rule set; NFS for the lab's NAS; the kernel settings container-dense nodes need; the lab workstation's account; k3s in the health check once the lab installs it |
| **Storage** | Keeps files for the house and backups for the lab. | Samba and NFS (on, with no shares yet), btrbk, disk spin-down; the `smb` and `nfs` rule sets |
| **Home services** | Runs apps for the household: photos, media, passwords. | Caddy on 80 and 443, local network only (`web-lan`) |
| **Game server** | Hosts games for friends, run from your phone. | The `games` rule set (Minecraft's 25565, from anywhere); the processor at full speed. Two ways, below |
| **Just a server** | The safe base and nothing else. | Nothing more |
| **Cockpit** (an extra) | A web page for looking after the server, on your local network. | Cockpit with its Podman, storage and files pages, on 9090 (`cockpit`). Never its update page, which would update outside the snapshot and the check |

**Game server comes two ways:**

- **On its own** (the default): games run as Podman containers, from bromigOS's game
  templates. No lab is needed.
- **With your lab's Pelican panel** (`game-server/pelican-wings`): the lab's Pelican panel
  runs the games here, through Wings, Pelican's game daemon. Wings needs Docker's engine,
  so this way installs `docker` in place of `podman-docker` (Podman itself stays). It needs
  `[lab] pelican_panel` set, and the internet. The lab sets Wings up from its panel; Wings
  counts in the health check once it's there.

**Lab node's account.** With `[lab] ssh_key` set to the lab workstation's public key, Lab
node makes a `lab` account for it: that key signs in, the account is in `bromigos-ssh`, and
sudo needs no password for it. That's what `bromigos lab provision` needs from an SSH
target. Removing the role takes the key and the sudo rule away (the account stays, locked).
Without a key, no account is made, and the lab signs in as you.

**What a role does when it's added:** it installs its packages (`pacman`), removes the
packages it replaces, writes its files when they aren't there, writes its kernel settings,
turns its services on, and opens its rule sets. Its health checks count from the next
update. **When it's removed,** its services stop, its rule sets close, its settings go, and
its files go if they're still as it wrote them. Its packages stay; the command says how to
remove them.

Roles marked offline install from the Field Kit stick with no network. Docker (for Wings)
and Cockpit need the network.

### For power users: the role files

One TOML file per role, in `/usr/share/bromigos/server/roles/` (`server/roles/` in the
repository), named after its `id`. `bromigos server roles --json` prints them all, with
`enabled` and `enabled_variant` for this server. On the Field Kit stick they're in
`/usr/share/bromigos/fieldkit/edition.json`'s `roles`, generated from the same files.

```toml
# /usr/share/bromigos/server/roles/game-server.toml
schema = 1
id = "game-server"
kind = "role"
order = 40
title = "Game server"
summary = "Host game servers for friends, started and stopped from your phone."
hint = "Players come in from the internet on the game's own port. Everything else stays closed."
offline = true
packages = []
services = []
firewall = ["games"]
health = []
health_optional = []
requires = []
conflicts = []

[files]
"/etc/tmpfiles.d/50-bromigos-game-server.conf" = "game-server/cpu-performance.conf"

[[variant]]
id = "podman"
default = true
title = "On its own"
hint = "Games run as containers with Podman, from bromigOS's game templates. No lab needed."
offline = true

[[variant]]
id = "pelican-wings"
title = "With your lab's Pelican panel"
hint = "Your lab's Pelican panel runs the games here through Wings ..."
offline = false
packages = ["docker"]
services = ["docker.service"]
firewall = ["wings"]
health = ["docker.service"]
health_optional = ["wings.service"]
requires = ["setting:lab.pelican_panel"]
conflicts = ["podman-docker"]
```

#### The role files' keys

| Key | Type | Default | What it means |
|---|---|---|---|
| `schema` | integer | `1` | The format's version. This page describes 1 |
| `id` | string | required | Lower case, letters, digits and `-`; the file is `ID.toml` |
| `kind` | `"role"` or `"extra"` | `"role"` | A role is an installer card. An extra isn't: it's added later (Cockpit) |
| `order` | integer | `100` | The cards' order, lowest first |
| `title` | string | required | The card's name |
| `summary` | string | required | One sentence, in plain words |
| `hint` | string | `""` | What it does and what it opens, in plain words: the card's longer text and its hover hint |
| `offline` | boolean | `true` | Whether every package it needs is on the Field Kit stick. `false`: it needs the network |
| `packages` | list of package names | `[]` | Installed with `pacman -S --needed` when they aren't |
| `services` | list of units | `[]` | Enabled (and started) when the role is added; disabled when it's removed, unless another role that's on lists them |
| `firewall` | list of rule set names | `[]` | `allow-NAME.nft` rule sets, open while the role is on |
| `health` | list of units | `[]` | Must be active for an update to count as healthy |
| `health_optional` | list of units | `[]` | The same, once the unit exists (something else installs it later) |
| `sysctl` | table of strings | `{}` | Kernel settings, written to `/etc/sysctl.d/60-bromigos-role-ID.conf` |
| `requires` | list | `[]` | `role:ID`: another role must be on. `setting:SECTION.KEY`: that `server.toml` key must be set |
| `conflicts` | list | `[]` | A package name: removed before the role's packages go in, and put back if they fail. `role:ID`: can't be on with that role |
| `files` | table | `{}` | `"/etc/PATH" = "SOURCE"`: a file from `roles/files/SOURCE`, written when nothing is at the path; removed with the role when unchanged |
| `lab_account` | boolean | `false` | Makes the `lab` account from `[lab] ssh_key` (Lab node) |
| `[[variant]]` | tables | none | Ways to have the role. Each has `id`, `title`, `hint`, `default` (exactly one is `true`), `offline` (when it differs from the role's), and any of `packages`, `services`, `firewall`, `health`, `health_optional`, `sysctl`, `requires`, `conflicts` and `files`, which add to the role's |

`[roles] enabled` in `server.toml` lists what's on. An entry is a role's `id` for its
default variant, or `ID/VARIANT` for another (`"game-server/pelican-wings"`).
`bromigos server role add` and `remove` write it; `setup` applies every role it lists, so
the installer can write it and run `setup`. A file that breaks a rule above is left out,
with the reason on standard error; the tests check every shipped file.

## What it is made of

`bromigos-server` is a meta-package. It depends on the non-desktop parts of bromigOS and
on the server's own tools, and installs a few files of its own.

| What | Where |
|---|---|
| The `bromigos server` command | `/usr/lib/bromigos/server/bromigos-server` (also `/usr/lib/bromigos/bin/bromigos-server`, so `bromigos server` finds it) |
| Its settings | `/etc/bromigos/server.toml`, which the installer writes. Every key is optional. |
| What it remembers | `/var/lib/bromigos/server/update.json` (the last update) and `history.jsonl` (every update, check and rollback) |
| SSH's rules | `/etc/ssh/sshd_config.d/10-bromigos-server.conf` |
| The firewall | `/usr/share/bromigos/server/nftables.nft` and `allow-*.nft`, loaded by `bromigos-server-firewall.service` |
| The updates | `bromigos-server-update.timer`, `bromigos-server-health.service`, `bromigos-server-mark-boot.service` |
| The roles | `/usr/share/bromigos/server/roles/*.toml`, and the files they write in `roles/files/` |
| SSH's guard | `/usr/share/bromigos/server/sshguard.conf`, and a drop-in for `sshguard.service` |
| The disks | `/usr/share/bromigos/server/smartd.conf`, a drop-in for `smartd.service`, `/usr/lib/bromigos/server/bromigos-server-disk-alert` |
| Backups | `bromigos-server-backup.timer` (nightly) and `bromigos-server-backup-check.timer` (weekly) |
| The UPS | `bromigos-server-ups.service` |
| Logs | `/usr/lib/systemd/journald.conf.d/60-bromigos-server.conf` |
| Hardening | `/usr/lib/sysctl.d/60-bromigos-server.conf` |
| Find my lab | `/etc/avahi/services/bromigos-lab.service` |
| The `bromigos-ssh` group | `/usr/lib/sysusers.d/bromigos-server.conf` |
| The containers' updates | A drop-in for `podman-auto-update.timer` |
| The monitoring | A drop-in for `prometheus-node-exporter.service`, and `/opt/bromigos-monitoring/textfile/` |

The source is `server/` in the repository. Its tests are `server/tests/`, and the
package's `check()` runs them.

The package's install script runs `bromigos-server setup` on every install and upgrade.
`setup` applies the settings, enables the timers and services, sets the boot menu, applies
the roles that are on, and puts kmscon on the first console. It's safe to run again. It
never turns SSH on: that's the installer's choice.

## The settings

```toml
# /etc/bromigos/server.toml
[ssh]
password = false        # true only when chosen at install: passwords work as well as keys

[firewall]
allow = []              # extra rule sets: "lab-cluster", "web", ... (roles add their own)
tcp = []                # more TCP ports, open to the local network only
udp = []                # more UDP ports, open to the local network only
public_tcp = []         # TCP ports open to everyone, such as a game's
public_udp = []         # UDP ports open to everyone

[updates]
auto = true             # the nightly update runs by itself
reboot = true           # it restarts by itself when a new kernel or driver needs it
news_hold = true        # Arch Linux news since the last update holds the nightly one

[health]
minutes = 10            # how long the server has to come back healthy after an update
ignore_units = []       # failed units that don't count against it

[roles]
enabled = []            # "storage", "game-server/pelican-wings", ... (role add writes it)

[backup]
to = ""                 # where: "s3:https://host/bucket/path", "sftp:user@host:/path", "/mnt/usb"
keep_daily = 7          # how many backups are kept
keep_weekly = 4
keep_monthly = 6
env_file = "/etc/bromigos/server/backup.env"   # root-only: the S3 or SFTP credentials
# paths and exclude: what's backed up and what's left out (below)

[boot]
kernel = "linux-lts"    # the boot menu's first entry; "linux", the newest, stays in it
apparmor = true         # AppArmor on, from the next start

[lab]
ssh_key = ""            # the lab workstation's public key (the Lab node role)
pelican_panel = ""      # your lab's Pelican panel (the Game server role, with Wings)
```

After changing the file, run `sudo bromigos server setup`. `bromigos server firewall allow
NAME` and `deny NAME` change the `allow` list for you, and reload the firewall.

## SSH

The installer asks whether to turn SSH on. If you say yes, it enables `sshd`. The package
never does.

`10-bromigos-server.conf` allows keys only, and doesn't let root sign in:

```text
PasswordAuthentication no
KbdInteractiveAuthentication no
PermitRootLogin no
```

A password works too only when the installer was told so. Then `server.toml` says
`password = true`, and `setup` writes `05-bromigos-server-password.conf`, which turns
passwords back on. sshd takes the first value it reads, and it reads the files by name, so
the `05-` file wins over the `10-` one. With `password = false`, `setup` removes it.

The same file limits how SSH can be tried:

```text
MaxAuthTries 3
LoginGraceTime 30
AllowGroups wheel bromigos-ssh
```

Only the account made at install (it's in `wheel`) and the members of `bromigos-ssh` can
sign in. To let someone else in, add them: `sudo gpasswd -a NAME bromigos-ssh`. The Lab
node role's `lab` account is in it.

### Guessing gets an address blocked

sshguard reads sshd's journal. An address that keeps failing is blocked for two minutes,
then for longer each time it comes back. It blocks through nftables, in tables of its own
(`ip sshguard`, `ip6 sshguard`) beside the server's.

For power users: `sshguard.service` reads `/usr/share/bromigos/server/sshguard.conf` in place
of `/etc/sshguard.conf`, which the package leaves as it is. A drop-in binds the file over it.
To change the settings, add your own drop-in that binds your file instead.
`sudo nft list set ip sshguard attackers` shows who's blocked.

## The firewall

The firewall is nftables, in a table of its own, `inet bromigos-server`. It doesn't use
`/etc/nftables.conf`, so that file stays yours. Podman and k3s add their own rules beside
it.

What it lets in:

- replies to connections this server made;
- anything on the loopback;
- ping, over IPv4 and IPv6;
- DHCP answers;
- SSH, on port 22 (sshd only listens when it's on);
- the node exporter, on port 9100, from the local network only;
- mDNS, on port 5353/udp, from the local network only, so Find my lab and `.local` names
  work.

Everything else coming in is dropped. Traffic going out, and traffic passing through to
containers and the cluster, is left alone.

"The local network" means private addresses: `10.0.0.0/8`, `172.16.0.0/12`,
`192.168.0.0/16`, `100.64.0.0/10`, and IPv6's `fc00::/7` and `fe80::/10`.

More can be let in. A role opens its own rule sets while it's on. You can open one
yourself too:

| Rule set | What it opens | Who uses it |
|---|---|---|
| `lab-cluster` | k3s, from the local network: 6443 (the API), 10250 (the kubelet), 2379-2380 (etcd between servers) and 8472/udp (flannel) | Lab node |
| `web` | 80 and 443, from anywhere | you |
| `web-lan` | 80 and 443, from the local network | Home services |
| `smb` | 445, from the local network | Storage |
| `nfs` | 2049, from the local network | Storage |
| `games` | 25565 (Minecraft), TCP and UDP, from anywhere | Game server |
| `wings` | 8080 and 2022, from the local network (the lab's panel) | Game server with Wings |
| `cockpit` | 9090, from the local network | the Cockpit extra |

The other ways:

| How | What it opens |
|---|---|
| `bromigos server firewall allow NAME` | a rule set above, on its own |
| `tcp = [8080]`, `udp = [...]` in `server.toml` | those ports, from the local network |
| `public_tcp = [27015]`, `public_udp = [...]` | those ports, from anywhere (a game's port) |
| A file in `/etc/bromigos/server/nftables.d/*.nft` | your own `add rule inet bromigos-server input …` lines |

A rule set is a file, `/usr/share/bromigos/server/allow-NAME.nft`. Its first line says what
it opens; `bromigos server firewall allow` lists them.

`bromigos server firewall apply` checks the rules with `nft -c` before it loads them. If
they don't load, the old ones stay. `bromigos server firewall` shows what's loaded, and
`--print` shows what it would load.

## Updates

Every night, between 04:00 and 05:00, `bromigos-server-update.timer` runs
`bromigos server update`. If the server was off then, it runs at the next start. It does
this:

1. It reads Arch Linux's news. News posted since the last update holds the update
   ("The Arch news hold", below).
2. It notes how the server is now: whether sshd runs, and the network's gateway.
3. It runs `bromigos update --yes --no-aur --json`. That's the same update as on the
   desktop. It updates from the server's own channel, `stable` unless you changed it.
   Arch has no separate security updates, so this is every update. snap-pac takes a
   snapshot before and after it, and the report names them.
4. If nothing changed, it stops there.
5. If the kernel or a graphics driver changed, it restarts the server, and the check runs
   after the restart. Otherwise the check runs straight away.

`reboot = false` in the settings stops the restart. The new kernel then runs after the
next restart you make, and the check waits for it.

### The Arch news hold

Some Arch Linux news asks for manual steps before an update, such as editing a config file.
An automatic update can't do those. So before each nightly update, the server reads Arch's
news feed. If an item was posted since the last successful update, it doesn't update:

- `bromigos server` shows "Update held", with the item's title and link;
- `update.json` has a `hold` with each item's title, link and date;
- the alert `update.held` tells your phone, with the link ([alerts.md](alerts.md)).

Read the item and do what it asks. Then update by hand with `sudo bromigos server update
--now`, or with BRODEC's Update button, which runs the same command. That clears the hold,
and the news posted until then counts as read. The next night's update runs as usual.

A feed that can't be read, with no network or the site down, holds nothing. `news_hold =
false` turns the hold off.

### How health is judged

After an update, the server has `minutes` (10 by default) to be healthy. It's healthy when
all of these are true:

- **Startup finished.** systemd says it's running, or degraded only by a unit you told it
  to ignore.
- **Nothing failed.** No unit failed, except those in `ignore_units`.
- **The essentials run.** NetworkManager and the firewall run. sshd runs, if it ran before
  the update.
- **The roles' services run.** Each role that's on lists the units it needs (its `health`).
  Some arrive later, such as k3s, which the lab installs: those count once they're there
  (its `health_optional`).
- **The disks counted no new errors.** No btrfs device's error counters went up since the
  update began. Errors from before don't count; `bromigos server` shows them.
- **The network is back.** The server has an address, and the gateway it had before the
  update answers a ping.

The check looks every 15 seconds until it's healthy or the time runs out.

The server's own background jobs never count against an update, even when one failed: the
backup and its check, the btrfs scrub, and the containers' update. `bromigos server` reports
them.

### When an update goes wrong

If the server isn't healthy in time, it rolls the update back:

1. It runs `bromigos update --rollback PRE --yes`. Every file `/` had before the update
   comes back ([update.md](update.md#rolling-an-update-back)).
2. If the update changed the kernel, it puts the old kernel back in `/boot`, which isn't in
   the snapshots. It copies `/usr/lib/modules/<release>/vmlinuz` to `/boot` and makes the
   initramfs again with `mkinitcpio`. Both work offline.
3. It restarts the server.

After that restart it checks again. If the server still isn't healthy, it doesn't roll
back a second time. It stops and says it needs attention, in `bromigos server` and in the
lab's metrics.

A start can hang before the check ever runs. So `bromigos-server-mark-boot.service` counts
each start after an update, early on. If a second start comes before the check finished,
the first one hung or was reset. Then the check rolls the update back at once.

If the server won't start at all, the boot menu still lists the snapshots, and Field Kit
can roll back from outside ([fieldkit.md](fieldkit.md)).

## Containers and services

The server has Podman, with the `docker` command (`podman-docker`) and compose
(`podman-compose`). `setup` enables `podman.socket`, so tools that talk to Docker's socket
work too. The lab's compose files run as they are.

**Services are Quadlets.** Every service bromigOS sets up as a container is a Quadlet: a
`.container` file (with `.volume` and `.network` files when it needs them) in
`/etc/containers/systemd/`. Podman turns each one into a systemd service. It then starts at
boot, restarts when it fails, logs to the journal, and counts in the health check like any
other service. Put your own there too:

```ini
# /etc/containers/systemd/whoami.container
[Container]
Image=docker.io/traefik/whoami:v1.10
PublishPort=8080:80
AutoUpdate=registry

[Install]
WantedBy=multi-user.target
```

Then `sudo systemctl daemon-reload` and `sudo systemctl start whoami`.

**Containers update after the system.** `podman-auto-update.timer` is on, moved by a drop-in
from midnight to 05:30, after the nightly update. It updates each container marked
`AutoUpdate=registry`, and rolls one back when its service fails to start.

For power users: Podman's own docs are `man podman-systemd.unit` and
`man podman-auto-update`. Compose files still work; they just aren't services systemd knows.

## Logs

The journal is kept across restarts, but it never takes more than 1 GiB, and nothing older
than a month is kept.

For power users: `/usr/lib/systemd/journald.conf.d/60-bromigos-server.conf` sets
`Storage=persistent`, `SystemMaxUse=1G` and `MaxRetentionSec=1month`. A file in
`/etc/systemd/journald.conf.d/` overrides it.

## Disks

A failing disk is the most common way a home server loses data, so the server watches
every disk. Each night at 02:00 each disk runs a short self-test, and on Saturdays at 01:00
a long one. A disk that reports a problem, or gets too hot, shows in `bromigos server`
with what it said.

Once a month the server also scrubs `/`: btrfs reads every file back and checks it against
its checksum. Corruption found while the second copy (or the backup) can still fix it is
corruption you can do something about. Any error the disks counted shows in
`bromigos server`, and new ones make an update count as unhealthy.

For power users:

- smartd reads `/usr/share/bromigos/server/smartd.conf` (a drop-in adds `-c`), so
  `/etc/smartd.conf` stays as the package left it. One line: `DEVICESCAN -a -o on -S on
  -n standby,q -s (S/../.././02|L/../../6/01) -W 4,55,65`. Temperatures: a note at 55 °C, a
  warning at 65 °C, and each change of 4 °C. Disks asleep aren't woken for a check.
- A warning runs `bromigos-server-disk-alert`, which adds a line to
  `/var/lib/bromigos/server/disk-alerts.jsonl`. No mail is sent.
- smartd runs with `-q nodev0` as `Type=simple`: on a machine with no disk it can read (a
  VM, a RAID card that hides its disks), it stops instead of failing.
- The scrub is btrfs-progs' own `btrfs-scrub@-.timer`, enabled only when `/` is btrfs.
- The error counters come from `/sys/fs/btrfs/*/devinfo/*/error_stats`, which any user can
  read. `sudo btrfs device stats /` shows them per device.

## Power

Plug a UPS into the server's USB, and the server shuts down cleanly before its battery
runs out. Nothing needs setting up: at each start the server looks for one.

For power users: `bromigos-server-ups.service` runs `bromigos server ups detect`, which asks
`nut-scanner -U`. With no UPS, nothing changes and NUT stays off. With one, it writes NUT's
files in `/etc/nut/`: `nut.conf` (`MODE=standalone`), `ups.conf` (the UPS as `ups`),
`upsd.conf` (this machine only), `upsd.users` and `upsmon.conf` (a monitor user with a
random password, and `systemctl poweroff` as the shutdown). Then it turns on `nut.target`,
`nut-driver-enumerator`, `nut-server` and `nut-monitor`. It only replaces files that are
NUT's own untouched ones or its own: a file you changed is kept, and it says so. If the UPS
is gone at a later start, NUT is turned off, so a missing UPS isn't a failing service.
`bromigos server ups` shows what it found. Telling other machines to shut down (NUT as a
network server) is for later.

## Backups

A snapshot isn't a backup: it's on the same disk. The server backs itself up every night
with restic, once you say where to: the lab's S3, any S3 or SFTP server, or a USB disk.
Until then it does nothing, and `bromigos server` says backups are off.

```toml
# /etc/bromigos/server.toml
[backup]
to = "s3:https://s3.example/backups/myserver"
```

For S3 or SFTP, put the credentials in `/etc/bromigos/server/backup.env`, readable by root
only (`sudo chmod 600`):

```sh
AWS_ACCESS_KEY_ID=...
AWS_SECRET_ACCESS_KEY=...
```

**The key.** The first backup makes the backup's key, `/etc/bromigos/server/backup.key`,
readable by root only. Without it, no one can read the backup, you included. Show it with
`sudo bromigos server backup key` and keep it somewhere away from the server.

| What | When |
|---|---|
| The backup | Every night at 06:00 (up to 30 minutes later), after the update and the containers' update. If the server was off, at the next start |
| What's kept | 7 daily, 4 weekly and 6 monthly backups |
| The check | Every Sunday at 08:00, `restic check`. In a month's first week it also reads back 5 % of the data |

What's backed up: `/etc`, `/var/lib/bromigos`, the Quadlets in `/etc/containers/systemd`,
the containers' volumes, `/srv`, `/home` and `/root`. Caches are left out (folders with a
`CACHEDIR.TAG`, `~/.cache`, `node_modules`), and the offline package store.

For power users:

| Command | What it does |
|---|---|
| `bromigos server backup` | How the last backup and check went (`--json` too) |
| `sudo bromigos server backup run` | A backup now. The first one sets the destination up (`restic init`) |
| `sudo bromigos server backup check [--data]` | A check now; `--data` reads 5 % back |
| `sudo bromigos server backup key` | Shows the key |

`paths` and `exclude` in `[backup]` replace the lists above. The state is in
`/var/lib/bromigos/server/backup.json`; `bromigos server status --json` shows the
destination without any password in it. To restore, use restic itself:
`sudo RESTIC_REPOSITORY=... RESTIC_PASSWORD_FILE=/etc/bromigos/server/backup.key restic restore latest --target /srv/restore`,
then copy back what you need.
A restore command of its own, the lab's Vault for the key, and alerts on the phone are for
later.

## Find my lab

The server announces itself on the local network over mDNS, so Find my lab on your desktop
lists it before the lab has set it up. It also answers to `NAME.local`, and finds other
machines' `.local` names.

For power users: `avahi-daemon` publishes `/etc/avahi/services/bromigos-lab.service`, the same
`_bromigos-lab._tcp` record `bromigos lab provision` writes ([lab-provision.md](lab-provision.md#the-box-announces-itself)):
SSH's port and `txtvers=1`, nothing else. `setup` adds `mdns_minimal [NOTFOUND=return]` to
`/etc/nsswitch.conf`'s `hosts:` line, before the resolver, once. The firewall lets 5353/udp
in from the local network only.

## Wake-on-LAN

The server's wired network cards keep Wake-on-LAN on, so BRODEC's Power on button (or any
machine on your network) can start it when it's off. That's `bromigos-core`'s, the same as
on the desktop: [wake-on-lan.md](wake-on-lan.md). `bromigos server` shows each card.

## Hardening

AppArmor is on: Podman then confines every container with its default profile. A few
kernel settings that cost nothing on a server are on too.

For power users:

- AppArmor needs the kernel's `lsm=` line. `setup` adds
  `lsm=landlock,lockdown,yama,integrity,apparmor,bpf` to `GRUB_CMDLINE_LINUX_DEFAULT`, in a
  block of its own at the end of `/etc/default/grub` (unless the line already has an `lsm=`),
  then makes `grub.cfg` again, safely, the way `bromigos boot theme` does: a copy of the old
  file is kept, and the new `grub.cfg` must pass `grub-script-check`. It takes effect from
  the next start. `apparmor.service` loads the profiles. `[boot] apparmor = false` takes it out.
- `/usr/lib/sysctl.d/60-bromigos-server.conf`, after systemd's `50-default.conf`:
  `kernel.kptr_restrict=2`, `kernel.dmesg_restrict=1`, `kernel.unprivileged_bpf_disabled=1`,
  no ICMP redirects in or out, `rp_filter=2` (loose, which k3s's flannel needs),
  `tcp_syncookies=1`, and `fs.protected_hardlinks`, `_symlinks`, `_fifos` and `_regular`.
  A file in `/etc/sysctl.d/` overrides it.
- Not on: USBGuard, auditd rules, ClamAV. They cost more in breakage than they buy on a home
  server.

## The kernel

Server starts the long-term-support kernel, `linux-lts`, by default. The newest, `linux`,
stays installed as the second choice, under the boot menu's Advanced options. If an update
of one series breaks something, the other still starts the server.

For power users: the same block in `/etc/default/grub` sets
`GRUB_TOP_LEVEL=/boot/vmlinuz-linux-lts` (when that file is there), so GRUB's first entry,
the default, is the LTS kernel. `[boot] kernel = "linux"` puts the newest first, for very
new hardware. An NVIDIA card on the LTS kernel needs `nvidia-open-dkms` and
`linux-lts-headers`, which the Field Kit stick carries. The automatic rollback already puts
back every kernel it finds in `/usr/lib/modules`.

## Remote access

WireGuard (`wireguard-tools`) and Tailscale (`tailscale`) are installed, and both are off.
WireGuard reaches the server from outside the house without opening ports to the world;
NetworkManager has it built in (`nmcli connection import type wireguard file wg0.conf`).
Tailscale is for people who already use it: it relies on Tailscale's own servers, so it's
your choice (`sudo systemctl enable --now tailscaled`, then `sudo tailscale up`).

## The lab's cluster

k3s isn't in Arch's repositories, so the server doesn't come with it. The lab installs it
when it adds the server to its cluster, as it does for any machine.

To add a Server to the lab's cluster:

1. Install it with SSH on, and with the lab workstation's key.
2. On it, open the firewall to the cluster:

   ```bash
   sudo bromigos server firewall allow lab-cluster
   ```

3. On the lab's workstation, in the lab's provisioning folder, add it as an existing host:

   ```bash
   bromigos lab provision add-node --repo <folder> --node-spec <file> --role worker
   ```

   The node file names the server's SSH address. The lab's provisioning shows its plan
   and waits for `yes`. It downloads k3s's installer and installs the version the lab
   pins, so this step needs the internet. Then it joins the node with the cluster's own
   join credential, and waits for it to be ready ([lab-infrastructure.md](lab-infrastructure.md)).

`bromigos server` shows whether the server is in a cluster, its role, and whether k3s
runs. It reads the files the lab's provisioning leaves, `/etc/rancher/k3s/bromigos-<owner>`.

## Monitoring

The lab's Prometheus reads each machine's node exporter on port 9100. The server runs
`prometheus-node-exporter` there, and the firewall lets only the local network reach it.

A drop-in adds `--collector.textfile.directory=/opt/bromigos-monitoring/textfile`. That's
the folder the lab's own provisioning uses for extra metrics. `bromigos server` writes
three of its own there, in `bromigos-server.prom`:

| Metric | Meaning |
|---|---|
| `bromigos_server_update_healthy` | 1: the last update came back healthy. 0.5: it's being checked. 0: rolled back, or needs attention. |
| `bromigos_server_update_timestamp_seconds` | When the last automatic update ran |
| `bromigos_server_rollbacks_total` | Updates rolled back because the server didn't come back healthy |

If the server joins the cluster, the lab's own node exporter runs on it as part of the
cluster, on the same port. Turn the server's off then:
`sudo systemctl disable --now prometheus-node-exporter`.

## The console

The first console runs kmscon. It draws with Geist Mono and DRIFTGLASS's colours, in full
colour, with the settings `bromigos-boot` ships. `setup` enables `kmsconvt@tty1.service`
and turns off `getty@tty1`. If kmscon can't start, for example with no graphics driver,
its unit starts the plain console's login instead. That one still has bromigOS's colours
and font ([console.md](console.md)).

## BRODEC on your phone

With the `brodec-machine` package (BRODEC's machine agent), the server pairs with BRODEC on
your phone: the welcome tour's "Pair your phone" step, Field Kit's Server › Pair with BRODEC, or
VECTOR › CTRL+P shows a
code to scan in LAB › MACHINES › ADD MACHINE. Field Kit then writes root's
`/etc/brodec-machine/machine.toml`, unless one is already there:

- no jobs;
- the console's Herdr workspace and the phone's own shells;
- machine controls: restart, shut down and update, each with your fingerprint. The update is
  `bromigos-server update --now`, with its snapshot, health check and rollback.

Then allow your phone at the server once ("Allow this phone", `brodec-machine enroll`).
[fieldkit-vector.md](fieldkit-vector.md#pair-with-brodec) has the details, and BRODEC's
`docs/MACHINE_JOBS.md` the rules.

### Alerts

The server checks itself for what needs you: failing drives, btrfs errors, a full disk, an
update held by the news or rolled back, a failed backup, the UPS on battery, a service that
stopped, a game server that's down. `bromigos alerts` lists them. BRODEC's machine agent sends
them to your phone, end-to-end encrypted, with buttons to act on them. [alerts.md](alerts.md)
has the checks and how to add your own.

## `bromigos server`

```text
$ bromigos server
bromigOS Server · lab-node-2 · 192.0.2.20
  SSH          on (keys only)
  Firewall     active, also open: lab-cluster
  Updates      the last update came back healthy (2026-10-30T04:12:09-07:00)
  Containers   3 running (podman)
  Lab cluster  agent of homelab, active
  Monitoring   node exporter active on port 9100 (local network only)
  Roles        Lab node, Storage
  Backups      the last backup worked (2026-10-30T06:14:51-07:00), to s3:https://s3.example/backups/lab-node-2
  Disks        no errors; SMART watch active, monthly scrub active
  Power        UPS: none on USB (NUT is off)
  Protection   sshguard active, AppArmor on
  Wake-on-LAN  enp3s0 on
```

`bromigos server status --json` gives the same as JSON: `hostname`, `addresses`, `ssh`,
`firewall`, `updates`, `rollbacks`, `containers`, `cluster`, `monitoring`, `roles`,
`backup`, `disks`, `ups`, `security`, `mdns`, `wake_on_lan` and `kernel`. The Server's home
screen in the console reads it.

| Command | What it does |
|---|---|
| `bromigos server` | The status, above |
| `sudo bromigos server update --now` | An update now, with the same snapshot and check |
| `sudo bromigos server firewall allow\|deny NAME` | Opens or closes a rule set |
| `bromigos server roles [--json]` | The roles, and which are on |
| `sudo bromigos server role add\|remove ROLE[/VARIANT]` | A role on or off (`extra add\|remove` is the same, for Cockpit) |
| `bromigos server backup [run\|check\|key]` | The backups ([Backups](#backups)) |
| `bromigos server ups [detect]` | The UPS ([Power](#power)) |
| `sudo bromigos server setup` | Applies `server.toml` again, the roles included |

## For the installer

The installer reads `/usr/share/bromigos/fieldkit/edition.json` ([fieldkit.md](fieldkit.md)).
For Server, it should:

- install the packages it lists, which include `bromigos-server`, from the medium's
  offline store;
- ask whether to turn SSH on. With yes, enable `sshd.service` and authorize the key the
  person gives. Write `[ssh] password = true` to `/etc/bromigos/server.toml` only if they
  explicitly chose to allow passwords;
- write `/etc/bromigos/server.toml` before installing `bromigos-server`, or run
  `bromigos server setup` again after writing it;
- for the roles chosen on its cards (`edition.json`'s `roles`, [Roles](#roles)): add each
  role's `packages`, and its variant's, to the packages it installs, and leave out its
  `conflicts` (the Wings variant: no `podman-docker`). Write `[roles] enabled` with each
  role's `id`, or `ID/VARIANT` for a variant that isn't the default. Write `[lab] ssh_key`
  when Lab node's card was given the lab workstation's key, and `[lab] pelican_panel` for
  the Wings variant. `setup` then applies them. A role whose `offline` is false needs the
  network: say so on its card;
- not offer `kind = "extra"` (Cockpit) as a card;
- install both kernels in `edition.json`'s `kernels` (`linux-lts` first); `setup` makes the
  LTS one the boot menu's first entry. Write `[boot] kernel = "linux"` when the person asks
  for the newest kernel. With an NVIDIA card, the LTS kernel needs `nvidia-open-dkms` and
  `linux-lts-headers` (in the store), not `nvidia-open`;
- make sure the account it creates is in `wheel`: SSH lets in only `wheel` and
  `bromigos-ssh`;
- set the default target to `multi-user.target`, with no display manager and no audio;
- not run `bromigos install` or `bromigos setup`, which set up the desktop. Run
  `bromigos-apps-setup` as the new user instead.

## Tests

```sh
python -m unittest discover -s server/tests
```

The tests run `bromigos-server` in a stand-in root, with stand-in `systemctl`, `bromigos`,
`ip`, `ping`, `nft`, `pacman`, `restic` and `nut-scanner`. `test_server.py` covers the
firewall's rules from the settings, the SSH password rule, an update with nothing to do, a
healthy update, an unhealthy one rolled back once and then flagged, ignored units, a
kernel update's restart, a start that hung, and the status document.
`test_base_roles.py` covers the base's files (sysctls, journald, SSH's limits, sshguard,
smartd, the containers' update time, the backup's timers, the mDNS record against the
lab's), every role file against the format, `offline` against the Field Kit stick's list,
the base's packages on the stick, adding and removing roles (stacking, variants, a failed
install put back, the lab account, files you changed kept), the roles' and the disks' part
in the health check, the boot menu's block, `.local` names, backups (off, the first one,
a failure, a check), the UPS (none, one, settings changed by hand), and smartd's warnings.
Where user namespaces work, every rule set is checked by the real `nft`, and where
shellcheck is installed, the shell files. Nothing on the machine running them changes.
