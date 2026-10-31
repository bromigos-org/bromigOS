# Setting up bromigOS Server

bromigOS Server is bromigOS for a computer that doesn't need a screen: a spare PC in a
cupboard, a box in a rack, a machine that holds your files or runs your game server. You
install it from the USB stick in a few minutes. After that you rarely need to touch it:

- it updates itself at night, in a window you choose;
- it takes a snapshot first, and undoes the update by itself if the server doesn't come
  back healthy;
- it tells your phone when something needs you: a failing disk, an update it undid, a
  backup that didn't run.

You look after it from BRODEC on your phone, from your bromigOS desktop's lab console, or
at its own console, where VECTOR explains anything in plain words.

This page goes through the installer's server steps. [The installer](installer.md) covers
the steps every install shares.

## What will this server do?

Tick the cards for its jobs: one, or several together. A Lab node can also be a Game
server and Storage. **Just a server** is the base on its own, so ticking it clears the
others. The roles suggest what the server runs, and you can change any of it on the
**Run** step.

| Role | What it's for |
|---|---|
| **Lab node** | Computing and graphics cards for your lab. It joins your lab's cluster, and your lab's workstation sets it up from your desktop: you don't type anything on it. |
| **Storage** | Files and backups for the house and the lab: shared folders for Windows, Mac and Linux, hourly versions of every file, and backups. |
| **Home services** | Apps for the household: photos, media, passwords, documents, home automation. Each app gets a name like `photos.yourserver.local`, backs itself up, and updates at night. |
| **Game server** | Game servers for your friends, started and stopped from your phone. With a lab, it joins your lab's Pelican panel. Without one, the games run on the server itself. |
| **Media** | Your own movies, shows, music and Den TV for every screen, for media you own or have rights to. |
| **Just a server** | The safe base and nothing more, for a box you'll fill yourself. |

Every role gets the same safe base:

- signing in with keys only, and brute-force blocking;
- a firewall that lets in only what the role needs;
- a snapshot before each update, a health check after it, and a rollback when it fails;
- watching every disk's health, and checking the data each month;
- a clean shutdown when a UPS is plugged in by USB;
- your lab's monitoring, on your network only;
- an announcement on your network, so Find my lab sees the server;
- Wake-on-LAN on its network cable;
- nightly backups, once you choose where they go.

When roles share the machine, the step says what that means, and says when this computer
has less than the combination wants. For example: "Game server + Lab node: the games get
their own processor and memory budget, so the cluster's jobs never make them lag."

You can add a role later.

## Where should this server keep its keys and passwords?

Right after the roles. Your VPN login, a game's admin password, a provider's key: each one
goes straight into the store you pick here, never into a file or the answer file. What
doesn't need a person (a database's password, a node's token) is made for you and stored
the same way.

- **Connect my lab's Vault (OpenBao/HashiCorp)**, the choice when the server joins a lab.
  It uses your lab's connection or join bundle when there is one. Otherwise you type the
  Vault's address and how the server signs in: your Bromigos account, a role ID and secret
  ID from your lab's admin, or a one-time wrapped token. A root token is never asked for.
  The step shows the policy the server uses and its own path in the Vault, and tests the
  connection.
- **Create a new Vault (OpenBao)**, for a new lab. OpenBao is compatible with HashiCorp
  Vault. At the first start, the welcome tour shows its unseal and recovery keys once,
  with a QR code: keep them somewhere safe and offline.
- **Keep them on this server, encrypted (TPM-bound, with a recovery bundle)**. Sealed with
  the security chip and the server's own key, with a recovery bundle to download or print
  as a QR code.
- **My lab uses sops + age**, for power users.

A vault hologram shows each key going in. The summary says how many keys are stored and
where, never their values. Done and the welcome tour say where your keys live and how to
get them back.

## Its network

Choose the network port the server uses. Ports with a cable come first, and the one that's
plugged in is usually the right one. If the computer has Wi-Fi only, the step says so: a
server works best on a cable, and you can join Wi-Fi in the welcome tour after the install.

Then choose how it gets its address:

- **From your router (DHCP).** The router picks the address, and it can change. Your
  server's name followed by `.local` works too.
- **A fixed address.** The server always has the same address, which is best for a server
  other computers reach. Type the address, the network size (24 for most home networks),
  your router's address and a name server (usually your router's address too). Each box
  shows a tick when what you typed is right, or a warning saying what to change.

The address other computers will use is shown big, with the line you'll type to sign in
from your own computer.

**Wake-on-LAN** lets BRODEC's Wake button or your desktop switch the server on over the
cable. It's on when the port can do it.

**Advanced** has a VLAN number and bonding (two ports joined as one), for networks set up
for them. Leave them alone otherwise.

## Who can sign in

The **admin** signs in at the server's own screen and over SSH from your computer, and
makes changes with `sudo`. The name is `admin` unless you choose another. The system
administrator account (root) can't sign in at all.

How you sign in from your computer:

- **Keys only (recommended).** You sign in with a key file from your computer, which
  nobody can guess. The installer finds keys in the stick's `fieldkit` folder, takes one
  you paste, or fetches the public keys GitHub shows for your GitHub name. GitHub's keys
  are shown with their fingerprints: compare them with your own computer's before you
  turn on **These are my keys**.
- **Keys or the password.** Your password works too. Anyone who can reach the server can
  try to guess it, so the step warns you.
- **No SSH.** You use the server only at its own screen and keyboard.

On a **Lab node**, the installer also makes a `lab` account. Your lab's workstation signs
in with it to set the server up. It works only with your lab workstation's key, and it can
run any command as the system administrator without a password. It exists only on a Lab
node.

**WireGuard** and **Tailscale** reach the server from outside your house. Both are
installed either way, and stay off unless you turn them on.

## Reach it from anywhere

How you get to the server when you're not at home:

- **Through BRODEC only**, the default and the safest: your phone reaches it, end to end
  encrypted, and nothing else on the internet can.
- **Join my lab's private network**: your lab's own network (Headscale), with a join code
  from your lab, BRODEC or the Field Kit stick.
- **WireGuard (advanced)**: a configuration you made yourself.
- **Tailscale's service**, with a Tailscale account.

The network picture shows the link to your devices. A public way in without a relay is a
port forwarded on your router to the server; keep keys-only sign-in if you do that. The
desktop installer asks the same question.

## Data disks

Pick other disks for your files and apps. They're joined into one place, `/srv/data`, with
snapshots. Each disk you pick is erased: the step says what's on it first.

- **One copy** uses all the space. If a disk fails, what's on it is lost.
- **Two copies (RAID1)** keeps every file on two disks, so one can fail without losing
  anything. It needs two or more disks.

On a Storage server, the step also has the shared folders: one for Windows and Mac, one
for Linux, both on your network only.

Skip the step to keep everything on the system's own disk.

## Lock the disk

Encryption keeps the data private if the server is stolen. The question is how it unlocks
when it restarts on its own after an update.

- **With a security chip (TPM 2.0)**, most PCs since 2016: the chip unlocks the disk at
  every start. At the very first start you type the passphrase once; from then on the
  server starts by itself. The passphrase stays the spare key, for the rare start the chip
  refuses (after a firmware update, say). Keep it somewhere safe.
- **Without a chip**, you choose: lock the disk and type its passphrase after every
  restart, or leave it unlocked. Locked is safest, but a restart after an update then waits
  for you, and your phone says so.

The admin's password is the passphrase unless you give the disk its own.

## How it updates

Choose how:

- **Update by itself** (recommended). Each night in the window: a snapshot, the update, a
  health check, and a rollback if it isn't healthy.
- **Download, then ask me.** It fetches the updates at night, then your phone says they're
  ready. One tap installs them, the same safe way.
- **I'll update it myself.** Nothing happens by itself.

The window is 3 to 5 AM in the server's time zone, unless you pick another. The server
restarts only when an update needs it, and only inside the window. When the news from Arch
(the system bromigOS is built on) asks for a step by hand, the server waits and tells you
first. On a Lab node, your lab restarts its machines one at a time, moving their work away
first.

**Tell my phone** sends these notices to BRODEC, once your phone is paired in the welcome
tour.

## What should this server run?

First, its place in your lab:

- **Start a new lab on this server**: it becomes the lab's first machine.
- **Join my existing lab**: with the lab's connection file, a join bundle on the USB
  stick, or by pairing with BRODEC after the install.
- **Not part of a lab**: it runs on its own, and can join a lab later.

Then what it runs, in groups: Lab core, AI, Network, Storage, Media, Games, Home apps and
BRODEC. Each card says what it is, how big it is, what it needs (memory, a graphics card,
the internet), and which of your roles suggested it. Tick or untick anything. When a pick
needs another (Argo CD needs Kubernetes), that one is ticked too and says why. A meter
fills as you pick: the processor, memory, disk and graphics card the choices need, against
what this computer has. For model serving, you pick the model, sized to the graphics card.

Some picks have a short guided setup:

- **VPN for downloads (Gluetun)**: your VPN provider (Private Internet Access, or Proton
  VPN or Mullvad), each with a line about it and a link to get an account, then your
  account's details, a check that connects once, and the kill switch, on by default.
- **Usenet downloader (SABnzbd)**: your provider's server, port 563 with SSL, 20
  connections, your login, and a test.
- **Indexer manager (Prowlarr)**: you add the indexers you have access to in Prowlarr,
  after the install.
- **Library automation**: the audio language you prefer: English, dual audio first.

The downloaders and the VPN stay unticked even with the Media role: they're for media
you own or have rights to, and you choose them yourself.

Below that, what every server has: brute-force blocking, disk health, monitoring, Find my
lab, backups, a UPS shutdown and AppArmor are on; **Web admin (Cockpit)** is off, on your
network only when you turn it on, and without its own update page, so updates always take
a snapshot first.

Nothing here is installed during the install itself: at the first sign-in, the welcome
tour shows the plan (each service, its ports, its size, what it downloads, what needs the
internet), and nothing runs until you press **Apply**.

## Ready to install

Every choice in plain words, each with an **Edit** button, and how you'll sign in once it's
installed: `ssh admin@` and the server's address, big, and as a QR code an SSH app on your
phone can scan.

## After the install

At the first sign-in, the server's welcome tour checks its network and shows its address,
its roles, and how it updates. It then sets up VECTOR's brain, joins your lab, shows the
plan for what it runs and applies it when you say, pairs your phone, and shows what's on
the server for its roles. Its last page says where your keys live and how to recover
them.

If the server won't start, choose **bromigOS Field Kit** in its boot menu: it repairs it,
or rolls the last update back, without a network.

## For power users

Everything below is optional.

### The presets file

The roles, the service toggles, the apps and every package list are data, not code:
`presets.toml`. The installer reads `/usr/share/bromigos/server/presets.toml` (the
`bromigos-server` package's), else the stick's
`/usr/local/share/bromigos-iso/server/presets.toml`, or the file named by
`BROMIGOS_SERVER_PRESETS`.

| Part | What it holds |
|---|---|
| `[base]` | What every server gets: `packages`, `services` (enabled when the system has them), `off_services` (installed, off), `kernel` and `fallback_kernel`, `firewall` (rule sets always open), `health`, `lsm`, `ups_usb_vendors`, `[base.sysctl]`, `[base.journald]`, `[base.ssh]` |
| `[updates]` | `window` and the `windows` offered, `mode` and the `modes` offered, `channel`, `notify`, `arch_news_hold` |
| `[firewall.NAME]` | A rule set: `tcp`, `udp`, and `from = "lan"` (private addresses) or `"any"` |
| `[[roles]]` | A role card: `id`, `title`, `summary`, `hint`, `glyph`, `packages`, `services`, `firewall`, `health`, `services_on` and `apps_on` (toggles it turns on), `lab_account`, `[roles.sysctl]`, and `[roles.with_lab]` for a Game server joined to a lab |
| `[[services]]` | A toggle: `id`, `title`, `words`, `roles` (`"*"` for every role), `on`, `locked`, `packages`, `units`, `firewall`, `never` (packages it must never bring) |
| `[[apps]]` | An app card: `id`, `title`, `words`, `roles`, `image` or `package`, `name` (its web name), `firewall` |

Every package is from Arch's own repositories or bromigOS's. A role added to the file shows
up in the installer as a card, with no code changed. The apps' container templates, with
their image digests pinned and tested by bromigOS's CI, are the `bromigos-server`
package's.

### Answer files

An answer file installs a server with no questions, as for the desktop ([Answer
files](installer.md#answer-files)). The server's answers go in a `[server]` table:

| Key | Values | Default |
|---|---|---|
| `roles` | a list of `lab`, `storage`, `home`, `games`, `media`; or `["plain"]` alone (`role = "…"`, one, works too) | `["plain"]` |
| `lab`, `lab_join` | `new`, `join` or `none`; `{ pair = true }`, `{ bundle = "PATH" }` or `{ file = "PATH" }` | `join` for a Lab node, else `none` |
| `provision`, `models` | the catalogue's item ids to run (what they need is added); the model ids for model serving | the roles' suggestions |
| `settings` | each item's guided setup: `[server.settings.gluetun] provider = "pia"`; a secret only as a reference, `password = { secret = "local:gluetun/password" }` (or `vault:`, `sops:`, `bitwarden:`) | the defaults |
| `store` | `{ kind = "vault" \| "openbao" \| "local" \| "sops", address = "…", auth = "oidc" \| "approle" \| "wrapped", role_id = "…" }` | the lab's Vault when joining, else `local` |
| `interface` | a port's name, or `auto` (the first wired port with a cable) | `auto` |
| `method` | `dhcp` or `static` | `dhcp` |
| `address`, `prefix`, `gateway`, `dns` | a fixed address, its network size, the router, a list of name servers | |
| `wake_on_lan` | true/false | `true` |
| `vlan`, `bond` | a VLAN number; a list of ports to bond | none |
| `ssh_mode` | `keys`, `password` or `off` | `keys` |
| `github`, `github_keys` | a GitHub name whose keys are fetched during the countdown; or the keys themselves | |
| `lab_key` | the lab workstation's key for the `lab` account (Lab node); else `ssh_keys` | |
| `tailscale`, `wireguard` | true/false | `false` |
| `data_disks`, `data_layout` | a list of disks (erased); `single` or `raid1` | none; `single` |
| `unlock` | `tpm`, `passphrase` or `none` | `tpm` with a chip, else `passphrase` |
| `update_mode`, `update_window` | `auto`, `download` or `off`; `HH:MM-HH:MM` | `auto`; `03:00-05:00` |
| `notify_phone` | true/false | `true` |
| `services`, `services_off` | toggles to turn on, and off | the role's |
| `apps` | the apps to install | the role's |
| `pelican_url`, `registry_mirror` | a Game server's lab panel, and the lab's image cache | |

The admin's name, password and keys stay under `[install]` (`user`, `password`,
`ssh_keys`), as for the desktop, and so does `reach = "brodec" | "lab-network" |
"wireguard" | "tailscale"` (with `reach_bundle`, `reach_wireguard` or
`reach_tailscale_key`). Secrets are never written to an answer file: a secret setting is a
reference to where it's stored, and the installer refuses a plain value there. What you type
into a setup form goes straight into the store at the first start. A file with a problem is never half-used: the installer
says what's wrong and asks instead. Asking for `unlock = "tpm"` on a computer with no chip
is such a problem.

A Lab node, signing in with your key, the chip unlocking the disk:

```toml
[install]
edition = "server"
disk = "/dev/nvme0n1"
mode = "erase"
user = "admin"
hostname = "lab-node-1"
password = "used at the console and for sudo"
ssh_keys = ["ssh-ed25519 AAAA… you@laptop"]

[server]
role = "lab"
lab_key = "ssh-ed25519 AAAA… lab@workstation"
unlock = "tpm"
```

Storage, two disks as RAID1, a fixed address, updates that ask first:

```toml
[install]
edition = "server"
disk = "/dev/nvme0n1"
mode = "erase"
user = "admin"
hostname = "storage"
password = "used at the console, for sudo and for the shares"
ssh_keys = ["ssh-ed25519 AAAA… you@laptop"]

[server]
role = "storage"
method = "static"
address = "192.0.2.10"
prefix = 24
gateway = "192.0.2.1"
dns = ["192.0.2.1"]
data_disks = ["/dev/sda", "/dev/sdb"]
data_layout = "raid1"
unlock = "passphrase"
update_mode = "download"
```

Home services, keys from GitHub, five apps:

```toml
[install]
edition = "server"
disk = "/dev/sda"
mode = "erase"
user = "admin"
hostname = "home-server"
password = "used at the console and for sudo"

[server]
role = "home"
github = "your-github-name"
apps = ["photos", "media", "passwords", "homepage", "uptime-kuma"]
unlock = "none"
update_window = "01:00-03:00"
```

A Game server joined to your lab's Pelican panel (Docker's engine, from Arch's own
packages, and Wings):

```toml
[install]
edition = "server"
disk = "/dev/nvme0n1"
mode = "erase"
user = "admin"
hostname = "game-server"
password = "used at the console and for sudo"
ssh_keys = ["ssh-ed25519 AAAA… you@laptop"]

[server]
role = "games"
services = ["pelican-wings", "performance"]
pelican_url = "https://panel.lab.example"
unlock = "none"
```

Three roles on one machine, starting a new lab, its keys in a new Vault:

```toml
[install]
edition = "server"
disk = "/dev/nvme0n1"
mode = "erase"
user = "admin"
hostname = "lab-core"
password = "used at the console and for sudo"
ssh_keys = ["ssh-ed25519 AAAA… you@laptop"]

[server]
roles = ["lab", "games", "storage"]
lab = "new"
provision = ["k3s", "argocd", "monitoring", "vault", "ollama", "models", "pelican-panel", "wings", "s3", "backup-target"]
store = { kind = "openbao" }
data_disks = ["/dev/sda", "/dev/sdb"]
data_layout = "raid1"
unlock = "tpm"
```

Media, with the VPN's provider chosen (its login goes in when typed, never in the file):

```toml
[install]
edition = "server"
disk = "/dev/sda"
mode = "erase"
user = "admin"
hostname = "media-server"
password = "used at the console and for sudo"
ssh_keys = ["ssh-ed25519 AAAA… you@laptop"]

[server]
roles = ["media"]
provision = ["media-library", "jellyfin", "seerr", "sonarr", "radarr", "den-tv", "gluetun", "sabnzbd", "prowlarr"]
store = { kind = "local" }

[server.settings.gluetun]
provider = "pia"
kill_switch = true
password = { secret = "local:gluetun/password" }

[server.settings.media-library]
language = "English"
dual_audio = true
```

Just a server, updated by hand:

```toml
[install]
edition = "server"
disk = "/dev/vda"
mode = "erase"
user = "admin"
password = "used at the console and for sudo"
ssh_keys = ["ssh-ed25519 AAAA… you@laptop"]

[server]
role = "plain"
update_mode = "off"
```

The same files are on the stick in `/usr/local/share/bromigos-iso/server/examples/`.

### The provisioning catalogue

What the Run step offers is the lab provisioning engine's catalogue,
`/usr/share/bromigos/lab/provision-catalogue.toml` (bromigos-lab's), read through
`bromigos_homelab.provcatalog`: `groups`, `resolve` (a need written `a|b` takes either),
`conflicts`, `budget`, `recommend(roles, hw, lab)`, `suggest_models` and `fits_item`, with the
hardware from `localprovision.detect()`. Each `[[item]]` has an `id`, its `group`, `name`,
`line`, `hint`, `icon`, `glyph`, `needs`, `conflicts`, the `roles` that suggest it, whether
it's ticked by `default`, the `lab` answers it's offered with, what it `requires` (`cpu`,
`ram_gb`, `disk_gb`, `gpu`, `gpu_vram_gb`, `gpu_vendor`), `size_text`, `ports`, `internet`,
`install`, `images` (pinned by digest), the `secrets` it makes for itself and a `note`; an
`[item.setup]` table holds its guided form (`title`, `intro`, `check`, `action`, and fields of
kind `text`, `number`, `bool`, `choice`, `secret` or `path`, each shown only `show_if` its
condition holds).

At the first sign-in the welcome tour runs `bromigos lab provision --local --from-answers
/var/log/bromigos/install-answers.toml --plan --json`, shows it, and on **Apply** runs
`--apply --json`, following its `::stage`, `::item` and `::error` lines. Without the
screen, `bromigos welcome-console --provision plan` and `--provision apply` do the same.

### The update modes

The installer writes the choice to `/etc/bromigos/server.toml`:

```toml
[updates]
mode = "auto"           # auto, download or off
window = "03:00-05:00"  # the server's own time zone
channel = "live"        # Arch as it is today; a tested snapshot of it comes later
notify = true
arch_news_hold = true
```

The update timer starts at the window's beginning, each server at its own moment in it,
late enough that a restart still lands inside it
(`/etc/systemd/system/bromigos-server-update.timer.d/10-window.conf`). `auto` updates,
checks and rolls back by itself. `download` fetches and waits for a tap on your phone.
`off` leaves the timer off: `bromigos update` takes the snapshot and does the rest when
you run it.

### The health checks

After an update, the server has 10 minutes to be healthy, or it rolls back. Every server
checks that startup finished, that nothing failed, that the network and SSH are back, and
that no disk says it's failing. Each role adds its own, in
`/etc/bromigos/server/health.d/`, where a script that exits 0 means healthy:

| Check | Role | Healthy when |
|---|---|---|
| `50-disks.sh` | every role | no disk's SMART says it's failing |
| `50-k3s.sh` | Lab node | once the lab has joined it, the cluster's agent runs |
| `50-arrays.sh` | Storage | `/srv/data` has no disk errors |
| `50-shares.sh` | Storage | the shares' services run |
| `50-apps.sh` | Home services, Game server | no app has failed |
| `50-wings.sh` | Game server with a lab | Docker's engine runs, and Wings once it's set up |

Add your own script there and it counts too.

### What the installer sets up

| What | Where |
|---|---|
| The settings | `/etc/bromigos/server.toml` (`bromigos-server setup` applies them) |
| The network | `/etc/NetworkManager/system-connections/bromigos-*.nmconnection` |
| SSH | `/etc/ssh/sshd_config.d/`: keys only, `MaxAuthTries 3`, `LoginGraceTime 30`, `AllowGroups wheel bromigos-ssh` |
| The lab account (Lab node only) | `/home/lab/.ssh/authorized_keys`, `/etc/sudoers.d/50-bromigos-lab` |
| The firewall | `bromigos-server`'s rule sets, else its own table in `/etc/nftables.conf` |
| Hardening | `/etc/sysctl.d/90-bromigos-server.conf`, `/etc/systemd/journald.conf.d/90-bromigos-server.conf`, AppArmor on the kernel line |
| The kernel | `linux-lts` first in the boot menu, `linux` beside it (`GRUB_TOP_LEVEL`) |
| Data disks | btrfs at `/srv/data` in `/etc/fstab`, with `shares`, `apps` and `backups` in it; a monthly scrub |
| Shares (Storage) | `/etc/samba/smb.conf`, `/etc/exports`: the local network only |
| Find my lab | `/etc/avahi/services/bromigos-server.service` (`_bromigos-lab._tcp`) |
| Unlocking with the chip | systemd's initramfs (`sd-encrypt`), and `bromigos-server-tpm-enroll.service`, which enrols the chip at the first start (`systemd-cryptenroll --tpm2-device=auto`, bound to Secure Boot's state) and wipes its one-time key |
| What the stick didn't carry | installed from Arch's mirrors during the install when there's a network, else listed in `/etc/bromigos/server/pending-packages` and installed once there is |

Booting a snapshot from the boot menu needs the classic initramfs, so a server unlocked by
its chip has no snapshot entries there. Field Kit, in the same boot menu, rolls back
instead.
