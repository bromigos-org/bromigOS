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
- **Backups**, every night, once you say where to, with a way to [get your files
  back](#get-your-files-back) and a test restore every month.
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
| Backups | Off until you say where. Restore and a monthly test restore ([Backups](#backups)) | `restic` |
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
| **Storage** | Keeps files for the house and backups for the lab. | Samba and NFS (on, with no shares yet), btrbk, disk spin-down; the `smb` and `nfs` rule sets; `web-lan` for the server's own page |
| **Home services** | Runs apps for the household: photos, media, passwords. | Caddy on 80 and 443, local network only (`web-lan`) |
| **Media** | Your own movies, shows, music and Den TV for every screen. | Jellyfin, requests and the library's upkeep, as containers the lab's engine sets up; `web-lan` and `media` (8096, and 7359/udp for the apps to find it), local network only; the `_bromigos-media._tcp` announcement, so desktops add it as a Den TV source by themselves |
| **Game server** | Hosts games for friends, run from your phone. | The `games` rule set (Minecraft's 25565, from anywhere); `web-lan` for the server's own page; the processor at full speed. Two ways, below |
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
turns its services on, and opens its rule sets. Then the lab's engine adds what it sets up
for that role on this server (its apps, their web names and checks): `bromigos lab provision
--local --roles ROLE --apply`, which only adds. Where the engine can't do that yet, the
command says so. Its health checks count from the next
update. **When it's removed,** its services stop, its rule sets close, its settings go, and
its files go if they're still as it wrote them. Its packages stay; the command says how to
remove them.

Roles marked offline install from the Field Kit stick with no network. Docker (for Wings)
and Cockpit need the network.

**The installer's picks.** The installer writes its own role ids too, under `[roles] picked`
(`lab`, `storage`, `home`, `games`, `media`, `plain`). Each one counts as the matching role
here (`lab-node`, `storage`, `home-services`, `game-server`, `media`, `just-a-server`), as
well as those in `[roles] enabled`. `role remove` takes a role out of both lists.

**Its secrets.** `sudo bromigos server secrets` is the lab's secret store, with the same
words: `status`, `set NAME`, `generate NAME`, `rotate NAME`, `recovery` (`bromigos lab
secrets`). The installer chooses where it keeps them.
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
hint = "Players come in from the internet on the game's own port. The server's own page answers your local network only; everything else stays closed."
offline = true
packages = []
services = []
firewall = ["games", "web-lan"]
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
| Backups | `bromigos-server-backup.timer` (nightly), `bromigos-server-backup-check.timer` (weekly) and `bromigos-server-backup-test.timer` (monthly) |
| The Go Bag | `/usr/lib/udev/rules.d/65-bromigos-server-backup-drive.rules`, which starts `bromigos-server-backup-drive@.service` when a USB drive is plugged in ([the Go Bag](#the-go-bag)) |
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
allow = []              # extra rule sets: "lab-cluster", "s3", ... (roles add their own)
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
picked = []             # the installer's own ids ("media", "home", ...): they count too

[backup]
to = ""                 # where: "s3:https://host/bucket/path", "sftp:user@host:/path", "/mnt/usb"
keep_daily = 7          # how many backups are kept
keep_weekly = 4
keep_monthly = 6
env_file = "/etc/bromigos/server/backup.env"   # root-only: the S3 or SFTP credentials
drive_remind_days = 30  # the Go Bag: remind after this long without a good copy; 0 is never
# paths and exclude: what's backed up and what's left out (below)

[boot]
kernel = "linux-lts"    # the boot menu's first entry; "linux", the newest, stays in it
apparmor = true         # AppArmor on, from the next start

[lab]
ssh_key = ""            # the lab workstation's public key (the Lab node role)
pelican_panel = ""      # your lab's Pelican panel (the Game server role, with Wings)
```

The installer also writes what it chose for `bromigos server status` to show: `[network]`
(the port, DHCP or a fixed address, VLAN, bond, Wake-on-LAN), `[storage]` (the data disks,
their layout and shares), `[unlock]` (`tpm`, `passphrase` or `none`), `[services]` (`on`,
`off`), `[apps]` (`enabled`, containers with their images pinned), `[lab]`, `[games]`
(`pelican_url`, `registry_mirror`), `[remote]` (Tailscale, WireGuard), `[kernel]` and
`[packages] pending`. Status also shows what it left for the first start, while those
units are there: `bromigos-server-pending.service` (the packages that waited for a network,
listed in `/etc/bromigos/server/pending-packages`), `bromigos-server-tpm-enroll.service`
(the security chip unlocking the disk) and `bromigos-server-secrets.service` (the install's
keys into the secret store). They're the installer's own units, and they run once.

The pending packages' unit skips itself while there's no network (its `ExecCondition` looks
up Arch's mirror), so it never shows as failed. `bromigos server update` starts it before
each update, so the first update with a network installs them, not only the next start.
When NVIDIA's driver is among them (an NVIDIA machine installed from Field Kit with no
network: the stick doesn't carry the driver), that update counts as a driver update: the
server restarts in its window and the health check follows, as for a new kernel. Until
then the card runs on the basic display driver.

`setup` never overwrites the installer's own files: its SSH drop-ins
(`/etc/ssh/sshd_config.d/01-…`, `05-…`, `20-…`: a `05-bromigos-server-password.conf` is
setup's own only when it says so), its kernel and journal settings (`90-…`, read after the
package's `60-…`), and `/etc/bromigos/server/nftables.d`.

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
`192.168.0.0/16`, and IPv6's `fc00::/7` and `fe80::/10`.

`100.64.0.0/10` joins them only while this server is on your lab's private network
([lab-network.md](lab-network.md)). That network hands out its addresses from this range,
and so do some internet providers to their customers. So the range counts as local while
the lab network's interface (`tailscale0`) is there or its service (`tailscaled`) runs, and
not otherwise. The firewall loads itself again when that service starts and stops
(`/usr/lib/systemd/system/tailscaled.service.d/bromigos-server.conf`).

More can be let in. A role opens its own rule sets while it's on. You can open one
yourself too:

| Rule set | What it opens | Who uses it |
|---|---|---|
| `lab-cluster` | k3s, from the local network: 6443 (the API), 10250 (the kubelet), 2379-2380 (etcd between servers) and 8472/udp (flannel) | Lab node |
| `web` | 80 and 443, from anywhere | you, on purpose ([below](#opening-a-server-to-the-internet)) |
| `web-lan` | 80 and 443, from the local network | Home services, Media, Storage, Game server: Caddy, and the server's own page ([board.md](board.md)) |
| `smb` | 445, from the local network | Storage |
| `nfs` | 2049, from the local network | Storage |
| `games` | 25565 (Minecraft), TCP and UDP, from anywhere | Game server |
| `wings` | 8080 and 2022, from the local network (the lab's panel) | Game server with Wings |
| `cockpit` | 9090, from the local network | the Cockpit extra |
| `media` | 8096 (Jellyfin) and 7359/udp (its apps finding it), from the local network | Media |
| `s3` | 9000 (S3: RustFS, the lab's object store), from the local network | you |

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

### What each role opens

No role opens anything to the internet except the Game server's game port.

| Role | Opens | To whom |
|---|---|---|
| Lab node | `lab-cluster`: the k3s ports | the local network |
| Storage | `smb` (445) and `nfs` (2049), and `web-lan`: 80 and 443 (the server's own page) | the local network |
| Home services | `web-lan`: 80 and 443 | the local network |
| Media | `web-lan`: 80 and 443, and `media`: 8096 and 7359/udp | the local network |
| Game server | `games`: 25565, TCP and UDP | everyone |
| | `web-lan`: 80 and 443 (the server's own page) | the local network |
| Game server with Wings | `wings`: 8080 and 2022 | the local network |
| Just a server | nothing more | |

The installer gives a server the same rule sets as the roles picked there, and nothing else.

### Opening a server to the internet

A server's pages answer your home network only. To let anyone on the internet reach ports
80 and 443, say so yourself:

```bash
sudo bromigos server firewall allow web    # 80 and 443, from anywhere
sudo bromigos server firewall deny web     # back to the local network only
```

`bromigos server status` then says, under Firewall, that ports 80 and 443 are open to
everyone, with the command that closes them. The server remembers that you asked
(`/var/lib/bromigos/server/firewall.json`, `owner_allowed`), and an update never undoes it.

Opening the firewall is half of it: your router must also send those ports to the server.
Think about what you put there first. The Lab board refuses every address that isn't
private whatever the firewall says ([board.md](board.md)), and the apps have their own
sign-in pages, which are then all that stands between them and the internet.

For one port that isn't a rule set, `public_tcp = [27015]` in `server.toml` does the same.

### Servers installed from 0.1.4-rc1 to 0.1.5

The installers of 0.1.4-rc1, 0.1.4 and 0.1.5 gave the Home services and Media roles the
rule set `web` where they meant `web-lan`. On those servers ports 80 and 443 accepted
connections from anywhere, not only from the home network. A home router that forwards
nothing still kept the internet out over IPv4.

The next update fixes it by itself. `bromigos server setup` (which every update of the
package runs) and `bromigos server firewall apply` (which runs at every start) move such a
server from `web` to `web-lan`, and for a month `bromigos server status` says so:

```
  Firewall     active, also open: web-lan, media
               ports 80 and 443 now answer the local network only: the installer had opened them to everyone by mistake. To open them to everyone on purpose: sudo bromigos server firewall allow web
```

How it tells the installer's `web` from yours: the installer keeps its own record of the
rule sets it gave a server (`[firewall] rule_sets` in `server.toml`, which
`bromigos-server` itself never writes). `web` in both `allow` and `rule_sets` is the
installer's, and moves. `web` that the record doesn't have was opened by hand, and stays.
After the move, `sudo bromigos server firewall allow web` is noted as yours and stays for
good.

If you relied on those ports being open to the internet on such a server, run
`sudo bromigos server firewall allow web` once after the update.

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

### Update modes, the window and the channel

The installer writes how updates go, under `[updates]`:

```toml
[updates]
mode = "auto"           # auto, download or off
window = "03:00-05:00"  # the server's own time zone
channel = "live"        # Arch as it is today; a tested snapshot of it comes later
notify = true
arch_news_hold = true   # the same as news_hold
cluster_reboots = false
```

| `mode` | What the nightly run does |
|---|---|
| `auto` | Updates, checks and rolls back by itself (above) |
| `download` | Downloads what the update would install (`pacman -Syuw`) and stops. `bromigos server` says how many wait, and the alert `update.held` tells your phone (unless `notify = false`). BRODEC's Update, or `sudo bromigos server update --now`, then installs them with the snapshot, the check and the rollback |
| `off` | Nothing: the timer is off. `sudo bromigos server update --now` runs the whole update when you want it |

A file from before the modes has `auto = true` or `false`: that's `auto` or `off`.

**The window.** The installer moves the timer into the window
(`/etc/systemd/system/bromigos-server-update.timer.d/10-window.conf`), each server at its
own moment in it. A restart the update needs happens only inside the window: an update
approved from your phone at noon installs at once, and the restart waits for the window's
next opening (status says "the restart it needs waits for the window"). `--now` at the
console restarts at once. No window: any time.

**Cluster reboots.** A Lab node with `cluster_reboots = true`, joined to the lab's cluster,
never restarts by itself: it leaves `/run/reboot-required` for the lab, which restarts its
machines one at a time and moves their work away first. The check runs after that restart.

**The channel.** `live` is Arch as it is today, protected by the snapshot, the check and the
rollback. A tested channel (a dated copy of Arch that CI has installed and booted) comes
later; until then any other value updates from `live`, and says so.

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
- **Every script in `/etc/bromigos/server/health.d/` exits 0.** The installer writes each
  role's (`50-disks.sh`, `50-k3s.sh`, `50-arrays.sh`, `50-shares.sh`, `50-apps.sh`,
  `50-wings.sh`), and any script you add counts too. Each has a minute; one that isn't
  executable runs with `sh`. Its last line of output is the reason a failure gives.

`[health] checks` lists the checks the installer chose: `startup`, `units`, `network` and
`sshd` are the built-in ones above; any other name is its `health.d` script. `bromigos
server status --json` shows both.

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

**Containers you mark update after the system.** `podman-auto-update.timer` is on, moved by
a drop-in from midnight to 05:30, after the nightly update. It updates each container marked
`AutoUpdate=registry`, as in the example above, and rolls one back when its service fails
to start.

**The catalogue's container apps don't update by themselves.** Most apps bromigOS sets
up, from the installer's **What should this server run?** step or
`bromigos lab provision --local`, run as containers: photos, documents, home automation,
the media apps. Each is pinned to one exact image and isn't marked `AutoUpdate=registry`.
The timer leaves them alone, and the nightly update changes the system's packages, not
them. Such an app stays at the version it was installed with.

A few items are packages, not containers: passwords (Vaultwarden), file sync (Syncthing),
ad blocking (AdGuard Home), Caddy, Ollama. Those update with the system each night, like
any package. [lab-provision.md](lab-provision.md#updates) says how a container app changes
today, and what is planned.

For power users: Podman's own docs are `man podman-systemd.unit` and
`man podman-auto-update`. Compose files still work; they just aren't services systemd knows.

### Add and remove apps

`bromigos lab apps` manages the catalogue's apps on a running server: the ones chosen at
install and any added later.

```bash
bromigos lab apps                       # each app: running or not, memory, data, its page
bromigos lab apps list --all            # and what can be added
sudo bromigos lab apps add photos       # add one, with what it needs
sudo bromigos lab apps remove photos    # remove it; its data stays in /srv/apps/photos
sudo bromigos lab apps restart photos
bromigos lab apps logs photos -f
```

- **Remove keeps the data.** The app's folder in `/srv/apps` and its keys stay, and adding
  the app again picks them up. Only `--delete-data` deletes the folder. It asks you to type
  the app's id first.
- **An app others need can't be removed.** Remove those first. Items set up by a step that
  changes more than one service, such as Caddy or ad blocking, can't be removed yet.
- **Adding and removing are jobs.** Each runs in a unit of its own, with named steps, so it
  finishes with the terminal closed. `bromigos activity` shows it. Two app jobs queue.
- On a Server, `bromigos lab deploy`, `restart` and `logs` are these commands.
  `bromigos lab update` says updating apps is planned.

What the server is meant to run is `/etc/bromigos/lab/apps.toml`, seeded once from the
install answers. Every command takes `--json`. [lab.md](lab.md#apps-on-a-server) has the
details: where each reading comes from, the steps, the tile JSON, the exit codes.

## Where the apps keep their data

Every app that runs as a container keeps its data in a folder of its own under
`/srv/apps`: the photo library and its database in `/srv/apps/photos`, the documents in
`/srv/apps/documents`. File sync (Syncthing) keeps its folder there too. Which disk that
is depends on the server.

- **With data disks**, `/srv/apps` is on them. The installer makes the data disks' `apps`
  subvolume and mounts it at `/srv/apps`, so it is the same folder as `/srv/data/apps`.
  With two copies (RAID1), the apps' data has two copies too. The data disks' monthly
  scrub checks it.
- **Without data disks**, `/srv/apps` is a folder on the system disk.

Two more folders follow the same rule. With data disks, each is a subvolume of theirs,
mounted where the lab's engine makes the folder. Without, each is a folder on the system
disk.

| Folder | What it holds | The data disks' subvolume |
|---|---|---|
| `/srv/apps` | Every app's data | `apps` |
| `/srv/media` | The media library: films, shows, music, books and the downloads | `media` |
| `/srv/backups` | The backups other machines keep on this server (the backup place, over SFTP) | `backups` |

A media library on a NAS share is the exception. The share is mounted at `/srv/media`, so
the data disks' line for that folder becomes a comment in `/etc/fstab` and the share takes
its place. The `media` subvolume stays on the data disks, at `/srv/data/media`.

**The passwords vault is there too.** Passwords (Vaultwarden) is a package, not a
container, and its package keeps the vault in `/var/lib/vaultwarden`, on the system disk.
bromigOS gives it a folder like every other app's, `/srv/apps/passwords`, so the vault is
on the data disks when the server has them. Two files tell the service:

- `/etc/bromigos/lab/passwords.env` sets `DATA_FOLDER=/srv/apps/passwords`.
- `/etc/systemd/system/vaultwarden.service.d/60-bromigos-data.conf` reads that file, lets
  the service write to the folder, and makes it wait for the folder's disk.

The package's own `/etc/vaultwarden.env` also sets `DATA_FOLDER`. systemd lets a file
named later win over one named earlier, and any file win over an `Environment=` line, so
the setting has to come from a file. The same goes for the vault's address and its web
vault, which that file turns off: `/etc/bromigos/lab/vaultwarden.env` turns it on and sets
the address (`ROCKET_ADDRESS`, `ROCKET_PORT`, `WEB_VAULT_ENABLED`, `WEB_VAULT_FOLDER`,
`DOMAIN`), read through `vaultwarden.service.d/50-bromigos.conf`. Your own settings still
go in `/etc/vaultwarden.env`; a setting the engine's file makes wins over yours.

AdGuard Home, Grafana and Prometheus, and OpenBao are packages too, and each keeps its
state where its package does, on the system disk.

`bromigos lab app-data` says where each of these is, and `bromigos server` has it on its
**App data** line.
`bromigos lab app-data status --json` gives the same as JSON. The command is the lab's
(`bromigos-lab`), because every bromigOS Server has that package, whichever stick installed
it. `bromigos server app-data` is the same command.

### A server set up before the installer did this

Until November 2026 the installer made the `apps` subvolume and never mounted it. A server
installed with data disks before then has its apps' data on the system disk: one copy,
where you may have chosen two. It says so on the App data line, and as the
`server.app-data` alert ([alerts.md](alerts.md)), which reaches your phone. One command
moves the data:

```bash
sudo bromigos lab app-data move --dry-run   # says what it would do, and changes nothing
sudo bromigos lab app-data move
```

What the move does:

1. It checks first, and stops with nothing changed when a check fails. The data disks must
   be mounted. The copy must fit, with 5 % and 1 GiB to spare. The data disks' `apps`
   folder must be empty. Nothing but services may be using `/srv/apps`.
2. It stops the apps: every Quadlet that names `/srv/apps`, and any service with a file
   open there.
3. It copies `/srv/apps` to the data disks with rsync, keeping owners, hard links, ACLs,
   extended attributes and sparse files.
4. It compares every file with its copy, by checksum. A difference stops the move and
   starts the apps again where they were.
5. It adds one line to `/etc/fstab`, renames the old folder to
   `/srv/apps.on-system-disk-DATE`, and mounts the data disks' `apps` subvolume at
   `/srv/apps`. If the mount fails, it puts all three back.
6. It starts the apps that were running.

Nothing is deleted. The status names the old copy until you remove it. Once you've seen
that the apps have everything, `sudo bromigos lab app-data remove-old` deletes it and
gives the system disk its space back.

You can run the move again at any point. A copy that was interrupted carries on from what
is already there. A move cut off during step 5, by a power cut for example, finishes when
you run the command again. Until then the status and the alert say it is waiting.

The move isn't automatic. It stops the household's apps for as long as the copy takes, so
a person chooses when.

**The media library and the backups folder move with it.** Until November 2026 the
installer mounted neither, and made no `media` subvolume. The same command takes each in
turn after the apps' data, by the same six steps: `/srv/media` to the data disks' `media`
subvolume, which it makes, and `/srv/backups` to their `backups` subvolume. For the media
library it stops the media apps, because their Quadlets name `/srv/media`. Each folder's
old copy is kept by name (`/srv/media.on-system-disk-DATE`), and `remove-old` deletes
them together. Everything waits for the apps' data: if that can't move, nothing else is
tried. After it, a folder that can't move is named and left as it was, the others still
move, and the command ends with an error. A folder nothing uses yet has nothing to copy: the move mounts its subvolume, so
what comes later is on the data disks from the start. Files of your own already in that
subvolume, such as a backup you pointed at `/srv/data/backups`, stay as they are and show
at `/srv/backups` too. They are in the way only when the folder on the system disk has
data to copy over them. Then that folder isn't moved until you move them. The status has a line for the media
library or the backups folder only when it holds data on the system disk. A media library
on a NAS share is left alone. So is a disk of your own mounted at either folder, or named
for it in `/etc/fstab`: the status counts it as `elsewhere`, mounted or not.

**The passwords vault moves last.** A server set up before November 2026 has the vault in
`/var/lib/vaultwarden`. Setting the server up again never moves it: Vaultwarden would
start on an empty folder and show no passwords. It stays where it is and goes on working,
and it is in the nightly backup there ([Backups](#backups)). On a server with data disks
the status names it, with the same command. Once the apps' data is on the data disks, the
move:

1. stops Vaultwarden;
2. copies `/var/lib/vaultwarden` to `/srv/apps/passwords` and compares every file;
3. writes the two files above, renames the old folder to
   `/var/lib/vaultwarden.on-system-disk-DATE`, and leaves an empty folder in its place,
   because the package's service starts in it;
4. starts Vaultwarden, waits five seconds, and checks that it is up and has made no vault
   in the old folder.

If the last check fails, everything is put back: the two files removed, the vault in
`/var/lib/vaultwarden` again, Vaultwarden running on it. An empty vault it made in the
meantime is set aside as `/var/lib/vaultwarden.started-empty-DATE`, never deleted. A move
cut off after the two files were written never copies over the new folder again, because
Vaultwarden may have run on it since. It only finishes the switch. On a server without
data disks nothing moves: the vault is on the same disk either way.

### When the data disks are away

The data disks' lines in `/etc/fstab` have `nofail`, so the server still starts without
them. The apps don't.

- Each app's service waits for `/srv/apps` at every start. Quadlet makes a container's
  service depend on the mounts of its `Volume=` folders. File sync (Syncthing) has a
  drop-in that says the same. So an app starts once the data disks are mounted, and not
  at all while they're away. systemd waits 30 seconds for the disks
  (`x-systemd.device-timeout=30s`).
- `/srv/apps` is then an empty folder on the system disk that takes no files
  (`chattr +i`), so no app can begin again from nothing there. `/srv/media` and
  `/srv/backups` are the same.
- `bromigos lab provision --local` refuses to set an app up. It refuses the media library
  and the backup place the same way.

The status and a critical alert say that the data disks aren't mounted.

For power users:

- The line is `UUID=…  /srv/apps  btrfs  subvol=/apps,…`, with the data disks' own options.
  `/srv/media` and `/srv/backups` each have one like it (`subvol=/media`,
  `subvol=/backups`). The move keeps `/etc/fstab` as it was in
  `/etc/fstab.before-app-data-move`.
- The move's record is `/var/lib/bromigos/lab/app-data.json`. Its `state` is `copying`,
  `verifying`, `switching`, `done` or `failed`. The media library and the backups folder
  have records of their own beside it: `app-data-media.json` and `app-data-backups.json`.
  The vault's is `app-data-vaultwarden.json`.
- `bromigos lab app-data status --json` has the apps' folder at the top (`path`, `state`,
  `where`, `has_data`, `move`, `leftover`) and the other two under `folders`, with the
  same fields. `where` is `pool`, `system`, or `elsewhere` for a media library on a NAS.
  `elsewhere` lists the vault while it is in `/var/lib/vaultwarden` on a server with data
  disks, and `vault` has its move (`move`, `leftover`).
- The copy is made with rsync. `bromigos-server` depends on it. A Server without that
  package needs the `rsync` package for the move, and the move says so before it starts.
- Hourly snapshots of `/srv/data` (snapper's `data` configuration) don't hold the apps'
  data. `apps` is a subvolume inside the data disks' top one, and a btrfs snapshot stops
  at a subvolume inside it. The second copy and the nightly backup protect the apps' data.
- The nightly backup reads `/srv` and names `/srv/apps` too, so on a server with data
  disks it reads the apps' data twice, as `/srv/apps` and as `/srv/data/apps`. restic
  stores it once. It doesn't count on reaching `/srv/apps` through `/srv`
  ([Backups](#backups)).
- A media library whose setup names another folder than `/srv/media` is wherever that
  folder is. Nothing here moves it.
- The move checks the room for each folder when it reaches it. The dry run reports each
  against the space free now, so a library that fits only before the apps' data is copied
  is found by the move itself, which stops there with that folder untouched.

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

`bromigos storage health` gives each disk a verdict from its history: healthy, watch,
getting worse, replace soon, or cannot tell. A few old errors that stopped growing are a
quiet line, not an alarm. A count that is rising, or a disk that says it is failing, is an
alert on your phone, with what changed and what to do.
[storage.md](storage.md#drive-health) explains each verdict and every number behind it.

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
- The verdicts come from the alerts' `disk.smart` check, which reads each disk every 15
  minutes and keeps the readings in `/var/lib/bromigos/drives/history.json`. The weekly long
  self-test is what makes 30 quiet days mean something: the whole surface is read four times
  in them. `bromigos storage health --json` gives the verdicts to a script.
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
Until then it does nothing, and `bromigos server` says backups are off. A second copy can
go on a USB drive you carry away: [the Go Bag](#the-go-bag).

This section starts with what you need on a bad day: getting files back. Turning backups
on, the checks and the full depth come after it.

### Get your files back

One command does it all, `bromigos lab backups`. It reads the backup's key, which only
the administrator can, so it asks for your password by itself. You never type `sudo`.

**1. See that there is a backup.**

```text
$ bromigos lab backups
Backed up 6 hours ago. Last test restore: 12 days ago, passed.

  Destination   s3:https://s3.example/backups/myserver
  Last backup   worked, 6 hours ago (2026-10-30 06:14, snapshot 1f3a9c2e, 48,210 files, 12.4 GB)
  Last check    passed, 5 days ago (2026-10-25 08:03)
  Read-back     5 % of the data read back 26 days ago, passed
  Test restore  passed 12 days ago (2026-10-18 10:07): 100 files restored and read back, a sample
  Backups kept  17 backups, from 2026-05-01 to 2026-10-30 (counted 6 hours ago)
  Schedule      backup nightly (active), check weekly (active), test restore monthly (active)

Get files back: bromigos lab backups restore   ·   every backup: bromigos lab backups list
```

The first line is the verdict. [The health line](#the-health-line) lists what it can say.

**2. Find what you lost.** `list` shows every backup, newest first. `show` looks inside
one, a folder at a time. With no backup named, it's the newest.

```bash
bromigos lab backups list
bromigos lab backups show 1f3a9c2e /home/ada/documents
```

**3. Get it back.** Name the backup and what you want. With no paths, you get everything.
With no backup named, it's the newest.

```bash
bromigos lab backups restore 1f3a9c2e /home/ada/documents
```

The files go into a new folder, `/srv/restore/backup-<date>-<id>/`. Each one sits at its
old path inside it, so `/home/ada/documents/tax.pdf` comes back as
`/srv/restore/backup-<date>-<id>/home/ada/documents/tax.pdf`. Then copy back what you need.

A restore like this is safe to try:

- **Nothing on the server is replaced.** It only ever writes into that new folder.
  `--to <folder>` picks another one, which must be new or empty. A folder with files in
  it is refused.
- **It checks for room first.** If the disk is too small, it says how much it needs and
  stops before writing anything.
- **It reads every file back** against the backup after writing it.
- **It tells you each step** as it goes, and ends by saying what was restored, where, how
  many files, and anything it had to skip and why.
- **You can stop it.** Press `Ctrl+C` and the folder keeps the name
  `backup-<date>-<id>.partial`, so nobody takes it for a whole one. Run the same command
  again and it carries on. The folder loses `.partial` only when every file is back. A
  different restore is never poured into it.
  If some files couldn't be read from the backup, the folder ends in `-incomplete` and the
  summary lists them.

The new folder belongs to root and only root can open it, like the backup itself.

### Put files back where they were

To put files back in place, over what's there now, add `--in-place`. That alone changes
nothing. It shows what would happen:

```text
$ bromigos lab backups restore 1f3a9c2e /etc/caddy --in-place

Putting /etc/caddy back from the backup of 2026-10-30 06:14 (1f3a9c2e) would:

  replace 1 file that changed since the backup:
    /etc/caddy/Caddyfile   (now 212 bytes, changed 2026-10-30 19:02; the backup's is 388 bytes)
  bring back 1 file or folder that is gone:
    /etc/caddy/sites/blog.conf
  leave 3 files alone that already match the backup
  leave alone everything that isn't in the backup: nothing is ever deleted

  First, a snapshot of / is taken (snapper's "root"), so this can be undone.

Nothing was changed: this was only a look. To do it: bromigos lab backups restore 1f3a9c2e /etc/caddy --in-place --apply
```

Add `--apply` to do it. It shows the list again and asks you to type `yes`. Then it:

1. checks there's room for every file it writes;
2. takes a snapshot of the files as they are now, where the server keeps snapshots: `/`,
   and the data disks the installer set up at `/srv/data`;
3. puts the backup's files over them, and reads each one back;
4. says what it replaced, what it brought back, and the snapshot's number.

It never deletes. A file that isn't in the backup stays where it is.

**Where no snapshot can be taken**, it says so plainly: *"No snapshot can be taken of
/home: snapshots aren't set up for it. What this replaces there can't be brought back
afterwards."* Then it asks a second time. If a snapshot should work and fails, the restore
stops before it changes anything.

**If it stops part-way** (a power cut, `Ctrl+C`), or some files can't be read from the
backup, some files are from the backup and some aren't. The server doesn't forget that. The
health line says "A restore stopped part-way", with the command that finishes it, and
[alerts](alerts.md) raise it, until a restore of those paths runs to the end. Running it
again is safe: files that already match are left alone.

### The test restore

A backup nobody has restored from is a hope, not a backup. So once a month the server
tries: it picks 100 of the newest backup's files at random, restores them to a scratch
folder, reads each one back against the backup, compares them with the backup's own list,
and removes the scratch folder. Nothing on the server changes. The sample leaves out
files over 256 MiB and stops at 1 GiB in all, so it fits beside the system. It reads
everything from the destination, with none of restic's cache on the server: on the day the
server is gone, there is no cache.

It's quiet when it passes. The health line says when one last passed. When one fails, or
none has passed for 45 days, the health line says so and [alerts](alerts.md) tell your
desktop and your phone.

```bash
bromigos lab backups test          # one now, with a sample
bromigos lab backups test --all    # restore every file: needs room for all of them
```

A sample can miss damage in files it didn't pick. `--all` reads everything, and so does
the weekly check's `--data` over time, 5 % a month.

### The health line

`bromigos lab backups` opens with one verdict. `bromigos server` shows the same sentence
on its Backups line, and [alerts](alerts.md) raise the same problems, because all three
ask one function (`health()` in `lib/bromigos_backups.py`). They can't disagree.

| The line | What it means |
|---|---|
| Backed up 6 hours ago. Last test restore: 12 days ago, passed. | All is well. |
| Backed up 6 hours ago. Last test restore: none yet. | New backups. The first test restore runs within a month. |
| No backup yet: the first one runs tonight. | A destination is set, and nothing has run. |
| Backups are off: nothing on this server is backed up. … | No destination is set. |
| No backup in 9 days: the drive at /mnt/backup is not connected. | A backup worked there before, and the folder is missing or empty now. |
| No backup in 9 days: the nightly backup has not run (…). | The server was off, or the timer is stopped. |
| The last backup failed: … The one before it worked, 1 day ago. | One bad night. The reason is restic's. |
| Backed up 6 hours ago. Some files could not be read and were left out. | The rest was backed up. |
| … But the last check of the backup failed (2 days ago): … | The weekly check found damage. |
| … The last test restore failed (1 day ago): … | Files didn't come back. Look before you need them. |
| … No test restore has passed in 50 days. | The monthly one hasn't run, or keeps failing to start. |
| … A restore stopped part-way: … | A restore in place was interrupted. Run it again. |
| The last backup failed: the backup left out /srv/apps (the apps' data). … | The backup ran without the apps' data. It doesn't count. |
| … But the database of documents (Paperless-ngx) wasn't copied whole, … | That app's database copy failed. The rest was backed up. |
| … But photos (Immich) has no recent database backup of its own, … | Immich's own nightly dump has stopped. The backup holds its database only through those. |
| … Go Bag: copied 3 days ago. | The [Go Bag](#the-go-bag) drive has a good copy. |
| … Go Bag: no copy yet. | A Go Bag is set up, and has never been copied to. |
| … Your Go Bag drive hasn't been updated in 31 days. Plug it in. | The reminder. `drive_remind_days` sets the wait. |
| … The last copy to your Go Bag drive failed (2 hours ago): … | The reason is restic's, or the drive's. |
| No nightly backup is set up: the Go Bag drive is this server's only backup. … | No destination is set, and a Go Bag is. |

What it doesn't know, it says: "none yet", "not counted yet". The count of backups and
their dates are taken after each night's backup, so the status needs no key and no network.
`bromigos lab backups list` reads them fresh.

A backup is late after 36 hours. Reasons come from restic as they are, without its
`Fatal:` prefix.

### Turn backups on

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
`sudo bromigos server backup key` and keep it somewhere away from the server. Keep the
destination's address and its credentials with it: those three things are all a restore
needs ([below](#restore-without-bromigos)).

| What | When |
|---|---|
| The backup | Every night at 06:00 (up to 30 minutes later), after the update and the containers' update. If the server was off, at the next start |
| What's kept | 7 daily, 4 weekly and 6 monthly backups |
| The check | Every Sunday at 08:00, `restic check`. In a month's first week it also reads back 5 % of the data |
| The test restore | The second Sunday of each month at 10:00, after that morning's check. If the server was off, at the next start |

What's backed up: `/etc`, `/var/lib/bromigos`, the Quadlets in `/etc/containers/systemd`,
the containers' volumes, `/var/lib/vaultwarden`, `/srv`, `/home` and `/root`. `/srv` holds
the media library and anything else you keep there. `/var/lib/vaultwarden` is where a
server set up before November 2026 keeps the vault
([Where the apps keep their data](#where-the-apps-keep-their-data)). A folder that isn't
there is skipped. Caches are left out (folders with a
`CACHEDIR.TAG`, `~/.cache`, `node_modules`), the offline package store, and `/srv/restore`,
where restores go. So is a folder destination inside one of those paths, which would
otherwise be backed up into itself. `paths` and `exclude` in `[backup]` replace those lists.

**The apps' data is always in it.** Every backup names `/srv/apps` by itself, whatever
`paths` says. On a server with data disks it's a disk of its own, mounted there, and a
backup that only named `/srv` and didn't cross into other disks would leave every app's
data out. After each backup the server looks in it for `/srv/apps` and for each app's own
folder inside (`/srv/apps/photos`, `/srv/apps/documents`). If one isn't there, the backup
counts as failed, the health line says which was left out, and [alerts](alerts.md) raise
it. The weekly check and the monthly test restore look too, and fail the same way. When
the data disks aren't mounted, `/srv/apps` is an empty folder, so the backup doesn't run
at all and says why: a backup of that would say the apps have no data.

An app's folder that your own `exclude` names is your choice, and isn't asked of the
backup. `/srv/apps` itself always is.

**An app you add later isn't a failed backup.** Each backup is judged against what was on
the server when it ran. An app set up since then isn't missing from that backup: it's in
the next one. Until then the status has a line for it, and the check and the test restore
pass and say the same:

```text
  Added since   /srv/apps/navidrome (the navidrome app's data): not in a backup yet: the next one runs at 2026-11-11 06:00
```

An app that was there when the backup ran, and isn't in it, still fails.

**The databases are made safe first.** An app writes to its database while the backup
reads it, so a file copied half-way through a write may not open. Before each backup, the
server copies each app's SQLite databases with SQLite's own online backup, which gives a
whole, consistent copy while the app goes on running, its write-ahead log included. An app
with several databases has each copied. Each copy goes on the same disk as the apps' data,
readable by root only, and every backup holds it:

- **With data disks**, in `/srv/apps/.bromigos-backup-databases/<app>/`, on the data disks.
  A large history (Home Assistant's, Jellyfin's) is copied onto the disks that hold it,
  never onto the system disk. The backup holds it through `/srv/apps`, once.
- **Without data disks**, in `/var/lib/bromigos/backup-databases/<app>/`, on the system
  disk, where the apps' data is too.

When the apps' data moves (`bromigos lab app-data move`), the next backup makes the copies
in the new place, and removes the old ones once the new ones are written. To get an app's
database back, restore its copy and put it in place of the app's own file with the app
stopped.

Every app in the catalogue that keeps a database has a hook that says how, written when
the app is installed. A server set up before a hook existed gets every hook the next time
the lab's engine runs there: when an app is added or removed (`bromigos lab apps add`), or
when the install's own apply is run again.

| App | What is made safe |
|---|---|
| Passwords (Vaultwarden), Documents (Paperless-ngx), Navidrome, Audiobookshelf, Uptime Kuma, Tautulli, Seerr, Home Assistant, Beets, Autoscan | Its SQLite database, copied |
| Sonarr, Radarr, Lidarr, Prowlarr | Both of its databases (`sonarr.db` and `logs.db`, and so on), copied. Each also keeps zipped backups of its own in `config/Backups`, which the backup holds |
| Jellyfin, Bazarr, Pinchflat, the Pelican panel, slskd | Every database in its data folder, copied |
| Photos (Immich) | Nothing is copied. Its database is PostgreSQL, whose files can't be copied while it runs. Immich dumps it itself every night into `/srv/apps/photos/library/backups`, and the backup holds those dumps |
| Plex | Nothing is copied. Plex's database only Plex reads safely. Plex backs it up itself every three days, beside the database, and the backup holds those files |

For Photos and Plex the server checks that the app's own newest backup is recent (3 days
for Immich, 10 for Plex). When it isn't, the health line and the alert say so: the app's
own backup may be turned off. A new app gets that long to make its first one.

**A copy never fills a disk.** Before each copy the server checks the free space where it
goes: the database's size and its write-ahead log's, 64 MiB more, and never taking that
disk below 1 GiB free or 5 % of its size, whichever is more. Without the room, that
database isn't copied and nothing is written. The backup is partial, and the health line
and the alert name the app: "not enough free space on /srv/apps for a copy of
/srv/apps/home-automation/config/home-assistant_v2.db: it needs 4.2 GB, and 3.1 GB is
free (1.0 GB is always left free)". The copy from the night before stays. A copy is written beside its place and moved
in when whole, so one that stops part-way (a power cut) never replaces it, and what it left
is removed at the next backup.

A copy that fails for another reason is on the health line the same way, and the rest of
the backup still runs. An app with no database yet (nothing was ever added to it) is
skipped.

**A hook that finds nothing is said.** Most hooks' paths come from each app's own
documentation. If one is wrong, the backup finds nothing to copy for that app. So
`bromigos lab backups` has a Databases row for each app: what was copied last time, or why
not. For an app whose services are running, a hook that found nothing is said too:

```text
  Databases     music tags (Beets): nothing found at /srv/apps/beets/config/musiclibrary.blb, and it is running: …
```

It is a note, not a failure: an app nobody has used yet may have made no database. It isn't
shown for an app set up within the hour.

**Which paths are proven.** CI installs the real apps on a throwaway machine
(`homelab/tests/apps-databases.sh`), and each hook must copy that app's database once it
answers. The pull request that added it lists which apps that proved. The others' paths
are from their documentation only.

A copy to the [Go Bag](#the-go-bag) follows all of this. It names `/srv/apps`, makes the
databases safe first, looks for each app's folder in what it wrote, and doesn't run while
the data disks are away. A database copy that fails there makes the Go Bag's copy "worked,
but left some files out", with the reason under it.

**A drive that isn't plugged in.** When a backup worked at the destination before and
nothing is there now, the nightly backup fails and says so. It never starts a new backup
in the old one's place, which for an unplugged USB disk would be the folder under it, on
the system disk. Plug the drive in and the next night carries on. If the old backup is
gone for good, `sudo bromigos server backup run --new` starts over.

### The Go Bag

A Go Bag is a USB drive that holds a copy of the server's backup, which you unplug and
keep somewhere else: at work, at a friend's, in a drawer in another building. A fire or a
theft that takes the server doesn't take it. It works with the nightly backup or without
one, and it is the least a server should have.

You plug it in. The copy starts by itself. When it says "Safe to unplug", you take the
drive away again.

**Set one up.** Plug the drive in and run:

```bash
bromigos lab backups go-bag setup
```

It picks the USB drive that is plugged in, sets it up, makes the first copy and ends with
"Safe to unplug". It asks for your password by itself. With more than one USB drive
plugged in, it lists them and you name one: `bromigos lab backups go-bag setup /dev/sdb`.

`setup` never guesses when a drive could hold something you want. It stops and says why:

| The drive | What `setup` does |
|---|---|
| Has files of yours on it | Stops. Say `yes` and it adds one folder, `bromigos-backup`, beside them. Nothing is deleted |
| Is new, or formatted for Windows only (NTFS) | Stops. `--erase` formats it, after you type `erase`. Everything on it is deleted |
| Is a disk inside the server, not a removable one | Stops. `--internal` uses it anyway |
| Holds part of the running system, or is mounted | Refuses. No flag changes that |
| Already holds this server's Go Bag | Uses it as it is |

**Keep the key.** The copy is encrypted with the same key as the nightly backup
([above](#turn-backups-on)). Without the key the drive is unreadable, for a thief and for
you. Show it with `sudo bromigos server backup key`, and keep a copy away from the server
and away from the drive.

**Plug it in.** From then on, plugging the drive in is all you do. The copy runs as a job
with four steps, which `bromigos activity` shows ([activity.md](activity.md)):

```text
$ bromigos activity show
Copying the backup to the Go Bag drive
  done just now, after 3 min  ·  backup.drive  ·  20261110-1802-backup.drive-6f1d2c3b-9a7e-4c11-4e1a
  Safe to unplug. 48,211 files (212 GB) copied to the Go Bag drive.

Steps
  ✓ Finding the Go Bag drive   done     Portable SSD (1.0 TB), labelled "GOBAG"
  ✓ Copying what changed       done     48,211 files, 212 GB (1.4 GB added to the drive)
  ✓ Checking what was written  done     It reads back
  ✓ Making it safe to unplug   done     Unmounted
```

Only what changed since the last copy is written, so later copies are short. The drive is
unmounted at the end, and after a copy that failed too. If it can't be unmounted, the job
fails and says "Don't unplug it yet". `bromigos lab backups go-bag run` starts a copy by
hand, for a drive that stays plugged in.

A copy that fails is an [alert](alerts.md), raised by the job itself as it ends, the way
every job's failure is ([activity.md](activity.md)). It clears with the next good copy.
`sudo bromigos activity retry <id>` starts the copy again, and `sudo bromigos activity
cancel <id>` stops one: stopping a copy is safe, except for the moment the drive is being
unmounted. A stopped copy isn't a failure. The drive keeps its last good copy.

**The reminder.** A Go Bag in a drawer goes stale. When it has had no good copy for 30
days, the [health line](#the-health-line) and [alerts](alerts.md) say so: "Your Go Bag
drive hasn't been updated in 31 days. Plug it in." Change the wait with
`drive_remind_days` in `[backup]`; 0 turns the reminder off.

**Get files back from it.** The restore commands [above](#get-your-files-back) read the Go
Bag when you add `--from go-bag`, with the drive plugged in:

```bash
bromigos lab backups list --from go-bag
bromigos lab backups restore --from go-bag /home/ada/documents
```

Each mounts the drive, does its work, unmounts it and says it is safe to unplug. On a
server with no nightly destination, the Go Bag is the backup, and the same commands read
it without `--from`. If the server is gone, the drive restores with restic on any
computer ([below](#restore-without-bromigos)): the repository is the folder
`bromigos-backup/<the server's name>` on it, and a `README.txt` on the drive says so.

#### For power users: the Go Bag

| Command | What it does |
|---|---|
| `bromigos lab backups go-bag [status]` | The Go Bag's line, the drive, whether it is plugged in, the last copy. Needs no root |
| `bromigos lab backups go-bag drives` | Every disk the server sees, and whether it can be the Go Bag. Needs no root |
| `bromigos lab backups go-bag setup [DRIVE]` | `DRIVE` is a path (`/dev/sdb`, `/dev/sdb1`, a `/dev/disk/by-id/…` link), a label or a filesystem UUID |
| `… setup --erase` | Formats the partition ext4, labelled `GOBAG`. On a disk with no partitions, the whole disk. It never changes a partition table |
| `… setup --internal` | Allows a drive that isn't removable |
| `… setup --yes` | Answers the questions `yes`. It doesn't stand for `--internal` |
| `… setup --no-copy` | Sets the drive up without the first copy |
| `bromigos lab backups go-bag run` | A copy now. The drive must be plugged in |
| `bromigos lab backups go-bag forget [--yes]` | Stops using the drive. What is on it stays |
| `… list \| show \| restore \| test --from go-bag` | The restore commands, reading the drive. A test restore from it is recorded as the drive's |

Each takes `--json`. The exit codes are the ones [below](#for-power-users): 3 for a
refusal, 2 when you have to name the drive or the partition, 1 when a copy failed or the
Go Bag needs you.

| Command | Its document |
|---|---|
| `go-bag status` | `name`, `set_up`, `verdict`, `drives`, `problems`, `remind_days` |
| `go-bag drives` | `drives`: each `path`, `model`, `size`, `removable`, `transport`, `usable`, `why`, `remembered`, `partitions` |
| `go-bag setup` | `drive`, `erased`, `adopted`, `copy`: `exit` and `job`, the activity record |
| `go-bag run` | `exit`, `job`, `drive` |

A drive in `drives`, here and in `bromigos lab backups --json` and `bromigos server status
--json`, has `name`, `uuid`, `label`, `model`, `size`, `fstype`, `added_at`, `plugged_in`,
`running`, `last_copy`, `last_good_copy`, `last_test`, `remind_days`, `stale` and `stale_s`.
`last_copy` and `last_good_copy` have `phase` (`ok`, `partial`, `failed`, `stopped`), `at`,
`ts`, `age_s`, `snapshot`, `files`, `bytes`, `added`, `seconds`, `reason` and `unmounted`.

The Go Bag's problems in `health.problems` are `drive-stale` and `drive-failed`. A problem
with `raised_by` is another check's alert: `drive-failed` has `raised_by: "activity.job"`, so
the `backup.restic` alert leaves it out and the failure is one alert, not two.

Error codes of its own, beside the ones below: `not-set-up`, `no-drive`, `which-drive`,
`which-partition`, `no-such-drive`, `in-use`, `read-only`, `not-removable`, `needs-erase`,
`has-files`, `one-drive`, `unplugged`, `busy`.

**How the drive is remembered.** By its filesystem's UUID, in `backup.json` under `drives`,
with its label, model and size for showing. No device name such as `/dev/sdb` is stored:
each time, the drive is found again by that UUID. Formatting a drive gives it a new UUID, so
a drive you format yourself has to be set up again.

**What is on the drive.** `bromigos-backup/<hostname>/` is a restic repository like the
nightly one ([below](#for-power-users)), opened by the same key, holding the same paths
with the same tag, excludes and keep rules. It is filled by `restic backup` from the
server itself, not copied from the nightly destination. So it works when that destination
is away or damaged, and it never inherits its damage. Filesystems used as they are: ext4,
btrfs, XFS, F2FS, exFAT and FAT.

**How plugging in starts it.** A udev rule,
`/usr/lib/udev/rules.d/65-bromigos-server-backup-drive.rules`, makes every USB filesystem
want `bromigos-server-backup-drive@<UUID>.service`. That unit runs `bromigos-server backup
plugged --uuid <UUID>`. For any drive but the Go Bag it does nothing. For the Go Bag it
starts the job, `bromigos-job-<id>.service`, and ends. The job's body is `bromigos-server
backup drive-copy`: mount at `/run/bromigos/backup-drive/<UUID>`, `restic backup`, `restic
forget --prune`, `restic check --read-data-subset=2G`, unmount.

The job is started with `bromigos activity run --lock backup-drive --cancel-safe
--retry-safe` ([activity.md](activity.md)). The lock makes two copies take turns: a drive
plugged in twice gives a second copy that waits, then copies what changed. The job prints
`::cancel unsafe` while it unmounts. A setup or a restore from the drive isn't a job, so it
holds `/var/lib/bromigos/server/backup-drive.lock` instead, and a copy that starts meanwhile
waits for it and says so. A copy is never skipped. To turn the rule off:
`sudo ln -s /dev/null /etc/udev/rules.d/65-bromigos-server-backup-drive.rules`.

A drive you mounted yourself is used where it is and left mounted. The job then ends with
"unmount it before you unplug it" and not with "Safe to unplug".

> **Planned.** Two drives that take turns, so one is always away from the server. The
> copy's progress and "Safe to unplug" on a phone. A copy on a timer for a drive that stays
> plugged in. Today `setup` takes one drive, and a drive set up with `--internal` isn't
> started by the udev rule: run its copy by hand.

### For power users

| Command | What it does |
|---|---|
| `bromigos lab backups [status]` | The health line and the status. Needs no root and no network |
| `bromigos lab backups list` | Every backup in the destination: id, date, size, files, paths |
| `bromigos lab backups show [ID] [PATH]` | One folder of a backup. No `PATH`: its top-level paths. A path alone is in the newest backup |
| `bromigos lab backups restore [ID] [PATH…]` | Into a new folder under `/srv/restore`. A first word that starts with `/` is a path, from the newest backup |
| `… restore … --to DIR` | Into `DIR`, which must not exist or be empty. While it runs, the work folder is `DIR.partial`, or `DIR/restore.partial` when `DIR` was there already, so it's always on the disk the files end up on |
| `… restore … --in-place` | The list of what would be replaced and brought back. Changes nothing |
| `… restore … --in-place --apply` | Does it, after a `yes` and a snapshot |
| `bromigos lab backups test [--all] [--scratch DIR]` | A test restore, recorded for the health line. `--scratch DIR` works in `DIR/bromigos-restore-test`, a folder of its own, and touches nothing else there |
| `bromigos lab backups run`, `check [--data]` | The same as `bromigos server backup run` and `check` |
| `sudo bromigos lab backups copy-databases` | Makes the apps' databases safe, as the nightly backup does first. For a backup job of your own. Exit 1 when one failed |
| `bromigos lab backups holds [PATH…]` | For a backup job of your own: does the newest backup in `$RESTIC_REPOSITORY` hold these folders (none: `/srv/apps`, each app's folder in it and the database copies)? Exit 1 when not |
| `bromigos lab backups job PATH…` | The lab's own nightly backup on a machine that isn't a bromigOS Server, which `bromigos-lab-backup.service` runs ([lab-provision.md](lab-provision.md#where-the-data-goes)). Not for a Server |
| `sudo bromigos server backup run [--new]` | A backup now. The first one sets the destination up (`restic init`) |
| `sudo bromigos server backup check [--data]` | A check now; `--data` reads 5 % back |
| `sudo bromigos server backup test` | What the monthly timer runs: `bromigos lab backups test` |
| `sudo bromigos server backup key` | Shows the key |

More flags for `restore`:

| Flag | What it does |
|---|---|
| `--yes` | With `--apply`: don't ask. Scripts need it, since there's no terminal to type `yes` in |
| `--plan DIGEST` | With `--apply`: go ahead only if the list is still the one `--in-place` showed. `DIGEST` is that plan's `digest` |
| `--without-snapshot` | With `--apply`: go ahead where no snapshot can be taken |
| `--no-verify` | Don't read each restored file back |

`ID` is the start of a backup's id, or `latest`: the newest of the nightly backups. Paths
are the full paths the files had on the server. A name with `*`, `?` or `[` in it is taken
as that exact name, never as a pattern.

**Exit codes.** 0: done, or for the status: healthy, off, or waiting for the first backup.
1: it failed, or the backups need you. 2: the command line. 3: refused: it would replace
files, it needs a `yes`, backups are off, or this isn't a Server. 4: not enough free
space. 130: stopped part-way.

**Scripting with `--json`.** Every command takes `--json` and prints one JSON document on
stdout. While a restore or a test restore runs, each step is a JSON line on stderr:
`{"event": "step", "id": "restore", "n": 4, "of": 5, "title": "…"}`, and `"progress"` lines
with a `percent`. Every document has `schema` (1) and `ok`. A failure has
`error.code` and `error.message`.

| Command | Its document |
|---|---|
| `status` | `server`, `configured`, `to`, `destination` (`kind`, `path`, `present`), `timers`, `health` (`state`: `ok`, `attention`, `waiting` or `off`; `verdict`; `problems`), `last_backup`, `last_success`, `last_check`, `last_check_passed`, `last_read_back`, `last_test`, `last_test_passed`, `snapshots` (`count`, `oldest_ts`, `newest_ts`), `drives` (the [Go Bag](#for-power-users-the-go-bag)), `not_in_backup_yet` (each `path`, `what`: set up since the last backup ran), `next_backup_ts` (when the next one runs, when something waits for it), `restore`, `running`, `checked_at`, `now` |
| `list` | `to`, `snapshots`: each `id`, `short_id`, `time`, `ts`, `host`, `tags`, `paths`, `files`, `bytes`, `added_bytes`, `nightly` |
| `show` | `snapshot`, `path`, `entries`: each `name`, `path`, `type` (`file`, `dir`, `symlink`, `other`), `size`, `mtime`, `permissions` |
| `restore` | `state` (`done`, `incomplete`), `mode` (`new-folder`), `snapshot`, `paths`, `target`, `files`, `bytes`, `verified`, `replaced` (0), `skipped`: each `path`, `why` |
| `restore --in-place` | `state` (`planned`), `mode` (`in-place`), `applied` (false), `snapshot`, `paths`, `replace`: each `path`, `size`, `now_size`, `now_modified`, and `link` when it's a link now; `add`: each `path`, `size`; `unchanged`; `digest`; `bytes`; `safety`: each `subvolume`, `config` (null: no snapshot there), `files`, `bytes` |
| `restore --in-place --apply` | The same, with `applied` (true), `state`, `replaced`, `added`, `skipped`, `verified`, `snapshots_taken`: each `subvolume`, `config`, `number` |
| `test` | `state` (`passed`, `failed`), `test`: `phase`, `at`, `ts`, `mode` (`sample`, `all`), `files`, `bytes`, `snapshot`, `seconds`, `reason`; `snapshot` |

Error codes: `not-a-server`, `off`, `settings`, `needs-root`, `no-key`, `wrong-key`,
`no-restic`, `unreachable`, `locked`, `no-such-backup`, `not-in-backup`, `would-overwrite`,
`needs-yes`, `other-restore`, `plan-changed`, `no-safety-snapshot`, `no-space`, `interrupted`,
`test-failed`, `failed`, `usage`. Times are ISO 8601 (`at`, `time`) and Unix seconds
(`ts`); sizes are bytes.

For example, to restore one folder in place from a script, only if the list is what a
person saw:

```bash
plan=$(bromigos lab backups restore latest /etc/caddy --in-place --json)
echo "$plan" | jq -r '.replace[].path, .add[].path'
bromigos lab backups restore latest /etc/caddy --in-place --apply --yes \
  --plan "$(echo "$plan" | jq -r .digest)" --json
```

**The files.**

| File | What it holds |
|---|---|
| `/etc/bromigos/server.toml` | `[backup]`: `to`, `paths`, `exclude`, `keep_daily`, `keep_weekly`, `keep_monthly`, `env_file`, `drive_remind_days` |
| `/etc/bromigos/server/backup.key` | The key: restic's repository password, one line. Root only |
| `/etc/bromigos/server/backup.env` | The destination's credentials, as `KEY=VALUE` lines. Root only |
| `/var/lib/bromigos/server/backup.json` | `run`, `check` and `test`: how the last of each went; a backup's `run` also has `databases` (each copy's `name`, `what`, `path`, `ok`, `reason`; `own` for an app's own backups), `saw` (the folders it had to hold: what was on the server when it ran) and, when it left one out, `missing`. `run_ok`, `check_ok`, `read_back_ok` and `test_ok`: the last one that worked, and for a backup where it went (`to`, without any password). `first_ok_ts`, and `snapshots`: the count and dates. `drives`: the Go Bag, by its filesystem's UUID, with its own `run`, `run_ok`, `test` and `test_ok` |
| `/var/lib/bromigos/server/backup-drive.lock` | Held by the one job that uses the Go Bag drive |
| `/run/bromigos/backup-drive/<UUID>/` | Where the Go Bag drive is mounted while a job uses it |
| `/var/lib/bromigos/server/restore.json` | The restore running now, or the last one: its steps, its state, and a restore in place that stopped part-way |
| `/var/lib/bromigos/server/restore-test.json` | The same for the test restore |
| `/var/lib/bromigos/server/restore-test/` | The test restore's scratch folder. Empty between runs |
| `/var/cache/restic/` | restic's cache |
| `/etc/bromigos/backup-databases.d/<app>.toml` | One per app that keeps a database. `what`: its name. `sqlite`: its SQLite files; a `*` matches inside one folder, and the ones that aren't there are skipped. `own` and `own_days`: the app's own database backups (files the backup holds), and how old the newest may be. The lab's engine writes one for each catalogue app, again at every apply; a file of your own with another name is read the same way |
| `/srv/apps/.bromigos-backup-databases/<app>/` or `/var/lib/bromigos/backup-databases/<app>/` | The databases' copies, made before each backup, one file per database: beside the apps' data when `/srv/apps` is a disk of its own (data disks), else on the system disk. Root only |
| `/srv/restore/` | Where restores go |

`bromigos server status --json` shows the destination without any password in it, and the
same `health` as `bromigos lab backups --json`.

**The units.** `bromigos-server-backup.timer`, `bromigos-server-backup-check.timer` and
`bromigos-server-backup-test.timer` run `bromigos-server backup run`, `check` and `test`.
`bromigos server setup` enables all three. They do nothing until `[backup] to` is set. A
failed one never makes an update unhealthy. Nor does
`bromigos-server-backup-drive@<UUID>.service`, the [Go Bag](#for-power-users-the-go-bag)'s
unit, which nothing enables: a drive plugged in starts it.

**How an in-place restore is made.** The list comes from restic's own dry run
(`restic restore --dry-run -vv`), so it's what restic will do. restic remakes every link,
so links are compared separately and only one that points elsewhere is listed. A link
standing where the backup has a folder is replaced by that folder; nothing is ever
written through a link. The
snapshot is `snapper -c <config> create`, for each snapper configuration whose subvolume
holds a file that changes. `snapper -c <config> undochange <number>..0` puts files back
as they were in it. The free-space check counts every file it writes at full size, since
that snapshot keeps the space of the ones it replaces. Files that already match keep their
contents, and get the backup's dates and permissions, as do the folders on the way to
them. `--delete` is never passed. A look that finds nothing left to do also settles a
restore that stopped part-way.

**The repository.** It's a plain restic repository, format version 2, with nothing of
bromigOS's own in it:

| In the destination | What it is |
|---|---|
| `config` | The repository's id and settings |
| `keys/` | The key file that `backup.key`'s password opens |
| `snapshots/` | One file per backup |
| `index/`, `data/00` … `data/ff` | The files' contents, split into encrypted packs |
| `locks/` | Who is using it now |

Every nightly backup has the tag `bromigos-server` and the server's host name. Paths are
stored as they were on the server, from `/`. Everything in it is encrypted with the key.

### Restore without bromigOS

If the server is gone, or bromigOS is, the backup still restores with restic alone, on any
computer. You need three things you kept away from the server: where the backup is
(`[backup] to`), the key, and for S3 or SFTP the credentials.

```bash
# on any computer with restic installed (https://restic.net)
export RESTIC_REPOSITORY='s3:https://s3.example/backups/myserver'   # [backup] to
export RESTIC_PASSWORD_FILE=./backup.key        # a file with the key in it, one line
export AWS_ACCESS_KEY_ID=...                    # S3 only: backup.env's lines
export AWS_SECRET_ACCESS_KEY=...

restic snapshots                                # every backup
restic ls latest /home/ada                      # look inside the newest
restic restore latest --target ./restored       # everything, into a new folder
restic restore latest --target ./restored --include /home/ada/documents   # or one folder
restic restore 1f3a9c2e --target ./restored --verify    # an older one, read back
```

For a USB disk, `RESTIC_REPOSITORY` is the folder on it, such as
`/run/media/you/backup/myserver`. On the server itself the same commands work as root with
`RESTIC_PASSWORD_FILE=/etc/bromigos/server/backup.key`. `bromigos lab backups` runs restic
the same way and adds nothing to the backup, so either can read what the other wrote.

The lab's Vault for the key is for later.

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
`linux-lts-headers`. The Field Kit stick doesn't carry them (about 505 MiB with the compiler,
LLVM and Mesa they pull in): the installer downloads them during the install, or with no
network they wait for the first update with one. The automatic rollback already puts
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
  `bromigos-server update --now`, with its snapshot, health check and rollback;
- power on (`[wake]`): the server isn't woken (it's always on), but it sends wake-ups for your
  other machines on its network when you press Power on in BRODEC (`enabled = false`,
  `send = true`).

Then allow your phone at the server once ("Allow this phone", `brodec-machine enroll`).
[fieldkit-vector.md](fieldkit-vector.md#pair-with-brodec) has the details, and BRODEC's
`docs/MACHINE_JOBS.md` the rules.

### Alerts

The server checks itself for what needs you: failing drives, btrfs errors, a full disk, an
update held by the news or rolled back, a failed backup, the UPS on battery, a service that
stopped, a game server that's down, apps' data on the wrong disk. `bromigos alerts` lists them. BRODEC's machine agent sends
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
  Backups      Backed up 6 hours ago. Last test restore: 12 days ago, passed. To s3:https://s3.example/backups/lab-node-2.
  Disks        no errors; SMART watch active, monthly scrub active
  App data     on the data disks (/srv/apps, their apps subvolume)
  Power        UPS: none on USB (NUT is off)
  Protection   sshguard active, AppArmor on
  Wake-on-LAN  enp3s0 on
```

`bromigos server status --json` gives the same as JSON: `hostname`, `addresses`, `ssh`,
`firewall`, `updates`, `rollbacks`, `containers`, `cluster`, `monitoring`, `roles`,
`backup`, `disks`, `ups`, `app_data`, `security`, `mdns`, `wake_on_lan` and `kernel`. The Server's home
screen in the console reads it.

| Command | What it does |
|---|---|
| `bromigos server` | The status, above |
| `sudo bromigos server update --now` | An update now, with the same snapshot and check |
| `sudo bromigos server firewall allow\|deny NAME` | Opens or closes a rule set |
| `bromigos server roles [--json]` | The roles, and which are on |
| `sudo bromigos server role add\|remove ROLE[/VARIANT]` | A role on or off (`extra add\|remove` is the same, for Cockpit) |
| `bromigos server backup [run\|check\|test\|key]` | The nightly backup and its checks. Getting files back is `bromigos lab backups` ([Backups](#backups)), and the drive you carry away is `bromigos lab backups go-bag` ([the Go Bag](#the-go-bag)) |
| `bromigos server ups [detect]` | The UPS ([Power](#power)) |
| `bromigos server app-data [status\|move\|remove-old]` | Where the apps keep their data: `bromigos lab app-data` ([above](#where-the-apps-keep-their-data)) |
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
  `linux-lts-headers`, not `nvidia-open`. They aren't in Field Kit's store: download them
  when there's a network, else list them in `/etc/bromigos/server/pending-packages` for the
  first update with one. The store has `linux-firmware`'s parts but NVIDIA's
  (`linux-firmware-nvidia`), so install those parts, and `linux-firmware` itself on an
  NVIDIA machine, the same way;
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
a failure, a check, what the health line needs kept, a backup that vanished never started
again elsewhere), the UPS (none, one, settings changed by hand), and smartd's warnings.
`test_app_data.py` covers the App data line and `bromigos server app-data`, with a stand-in
`bromigos-lab`.

The move itself is the lab's, tested in `homelab/tests/test_appdata.py`: the status in each
case, the dry run, the move with the real rsync (every file, mode and hard link; the old
copy kept; the `fstab` line; the apps stopped and started in order), a write during the
copy, a mount that fails and is put back, a move cut off before and after the switch took,
files already in the pool's folder, a host service and a stray shell, and the space check.
Its `findmnt`, `mount`, `umount`, `btrfs`, `chattr` and `systemctl` are stand-ins that keep
a list of what's mounted and what's running.
Where user namespaces work, every rule set is checked by the real `nft`, and where
shellcheck is installed, the shell files. Nothing on the machine running them changes.

Restoring is tested against a real restic, where it's installed:

```sh
cd homelab && PYTHONPATH=lib python -m unittest tests.test_lab_backups
```

`homelab/tests/test_lab_backups.py` makes a stand-in server with files in `/etc`, `/home`
and `/srv`, backs it up with the real `bromigos-server backup run` to a folder, and runs
`bromigos lab backups` against it. It covers the health line's words for every state, the
JSON documents, `list` and `show`, a restore to a new folder, the refusal to write where
files are, an in-place restore whose dry-run list is compared with what changed on disk,
no snapshot mechanism, a snapshot that fails, too little free space, a restore stopped by
a signal and one killed, a drive that isn't connected, and a damaged repository failing
the test restore. It also covers what every backup must hold: `/srv/apps` on a filesystem
of its own (a stand-in restic that leaves out `$FAKE/other-filesystems` under `--one-file-system`, as
restic does, and, where user namespaces allow, a real tmpfs mounted there in a namespace of
the test's own), a `paths` list without `/srv`, the data disks away, an exclude that drops
the apps (the run fails), one app's folder left out (the run, the check and the test
restore fail) against an exclude of your own (they don't), an app set up after the last
backup (nothing fails, and the status says "not in a backup yet"), a state file from before
runs kept their list (judged by each folder's birth time), a SQLite database in
write-ahead-log mode copied whole while it's open, an app with several, one that can't be
copied, one that wouldn't fit, an app's own backups that are recent, old or not made yet,
and the lab's own backup job, with and without bromigos-core's library. snapper is a stand-in: from a stand-in root the machine's own snapper
is never run, nor its `systemctl`, nor `sudo`. `tests/alerts/test_alerts.py` checks that
every backup alert is a problem of the same `health()` the status prints.

The Go Bag is tested the same way, with no real drive:

```sh
cd homelab && PYTHONPATH=lib python -m unittest tests.test_lab_backup_drive
```

`homelab/tests/test_lab_backup_drive.py` gives the stand-in server a "USB drive": a folder,
with stand-ins for `lsblk`, `mount`, `umount`, `sync`, `wipefs`, `mkfs.ext4` and `udevadm`
that the code is pointed at with `BROMIGOS_BACKUPS_<TOOL>`. From a stand-in root the
machine's own are never run. restic and `bromigos activity` are the real ones. It covers
the Go Bag's words in the health line and the reminder's thresholds, each refusal of
`setup` and that a refusal runs nothing, `--erase`, the drive remembered by its UUID and
found again under another device name, the copy as a job with its four steps, a copy that
fails, a drive that can't be unmounted, one someone else mounted, the status and its JSON,
and `list`, `show`, `restore` and `test` reading the drive.

The real tools are tried on a real install. CI's ISO workflow installs bromigOS Server in
a VM ([fieldkit.md](fieldkit.md#testing-it)), and `iso/fieldkit/restore-drill.sh` then runs
on it, as a user in `wheel`, with no network: a backup to a folder; `list` and `show`; a
restore to a new folder compared by checksum; an in-place restore with a real snapper
snapshot of `/` and of `/home`, and the plain refusal on `/srv`, which has none; the test
restore by hand and through `bromigos-server-backup-test.service`; the re-run through
`sudo`; and a pack file cut in half, which the test restore, the health line and the alert
must all report. On the Server installed with two data disks, `iso/test/server-data-checks.sh`
backs it up with the real `bromigos server backup run` and reads the newest backup back:
it must hold the app's folder under `/srv/apps`, a mount of the data disks, and the vault's
database copy, which must open. The engine also installs Navidrome there: the real app
makes its database, and the backup must hold the copy its hook made. Then a folder is made
under `/srv/apps` after the backup: the check and the test restore must pass, and the
status must say it isn't in a backup yet.

`iso/fieldkit/backup-drive-drill.sh` follows it on the same server, for the Go Bag. The
harness plugs a disk image into the running VM as a USB drive and pulls it out again
(`iso/fieldkit/test.py plug` and `unplug`), so the kernel, udev and systemd see a real
drive come and go. The system disk and a blank drive are refused; `setup --erase` formats
the drive and makes the first copy; pulled out, the status says so; plugged in again, the
copy starts by itself and ends "Safe to unplug" with nothing mounted; the restore commands
read it; and 40 days without a copy raise the reminder on the health line and as an alert.
