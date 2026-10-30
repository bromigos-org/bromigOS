# bromigOS Server

bromigOS Server is bromigOS installed without a desktop. It's for servers and the machines
in a homelab. It boots to a text console in bromigOS's colours, and you manage it over SSH
or from that console.

It has everything in bromigOS that doesn't need a screen: the `bromigos` command, the lab
console, the terminal apps (LazyVim, tmux, lazygit), herdr, and Field Kit's repairs. On top
of that it adds what a server needs:

- **SSH, with keys only**, when you choose it at install.
- **A firewall** that lets in SSH, ping and the lab's monitoring, and drops the rest.
- **Safe automatic updates.** Each one takes a snapshot first. If the server doesn't come
  back healthy, the update is rolled back by itself.
- **Containers**, with Podman and the `docker` command.
- **The lab's monitoring**: the node exporter the lab's Prometheus reads.
- **The lab's cluster**: the lab's workstation can add it to its k3s cluster.

You install it from the [Field Kit](fieldkit.md) medium. Everything it needs is on the
medium, so installing needs no network. The package is `bromigos-server`.

This page is for contributors. The manual's [bromigOS Server](../manual/src/server.md) page
is for people running one.

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
| The monitoring | A drop-in for `prometheus-node-exporter.service`, and `/opt/bromigos-monitoring/textfile/` |

The source is `server/` in the repository. Its tests are `server/tests/`, and the
package's `check()` runs them.

The package's install script runs `bromigos-server setup` on every install and upgrade.
`setup` applies the settings, enables the timers and services, and puts kmscon on the
first console. It's safe to run again. It never turns SSH on: that's the installer's
choice.

## The settings

```toml
# /etc/bromigos/server.toml
[ssh]
password = false        # true only when chosen at install: passwords work as well as keys

[firewall]
allow = []              # extra rule sets: "lab-cluster", "web"
tcp = []                # more TCP ports, open to the local network only

[updates]
auto = true             # the nightly update runs by itself
reboot = true           # it restarts by itself when a new kernel or driver needs it

[health]
minutes = 10            # how long the server has to come back healthy after an update
ignore_units = []       # failed units that don't count against it
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
- the node exporter, on port 9100, from the local network only.

Everything else coming in is dropped. Traffic going out, and traffic passing through to
containers and the cluster, is left alone.

"The local network" means private addresses: `10.0.0.0/8`, `172.16.0.0/12`,
`192.168.0.0/16`, `100.64.0.0/10`, and IPv6's `fc00::/7` and `fe80::/10`.

More can be let in three ways:

| How | What it opens |
|---|---|
| `bromigos server firewall allow lab-cluster` | k3s, from the local network: 6443 (the API), 10250 (the kubelet), 2379-2380 (etcd between servers) and 8472/udp (flannel) |
| `bromigos server firewall allow web` | 80 and 443, from anywhere |
| `tcp = [8080]` in `server.toml` | those TCP ports, from the local network |
| A file in `/etc/bromigos/server/nftables.d/*.nft` | your own `add rule inet bromigos-server input …` lines |

`bromigos server firewall apply` checks the rules with `nft -c` before it loads them. If
they don't load, the old ones stay. `bromigos server firewall` shows what's loaded, and
`--print` shows what it would load.

## Updates

Every night, between 04:00 and 05:00, `bromigos-server-update.timer` runs
`bromigos server update`. If the server was off then, it runs at the next start. It does
this:

1. It notes how the server is now: whether sshd runs, and the network's gateway.
2. It runs `bromigos update --yes --no-aur --json`. That's the same update as on the
   desktop. It updates from the server's own channel, `stable` unless you changed it.
   Arch has no separate security updates, so this is every update. snap-pac takes a
   snapshot before and after it, and the report names them.
3. If nothing changed, it stops there.
4. If the kernel or a graphics driver changed, it restarts the server, and the check runs
   after the restart. Otherwise the check runs straight away.

`reboot = false` in the settings stops the restart. The new kernel then runs after the
next restart you make, and the check waits for it.

### How health is judged

After an update, the server has `minutes` (10 by default) to be healthy. It's healthy when
all of these are true:

- **Startup finished.** systemd says it's running, or degraded only by a unit you told it
  to ignore.
- **Nothing failed.** No unit failed, except those in `ignore_units`.
- **The essentials run.** NetworkManager and the firewall run. sshd runs, if it ran before
  the update.
- **The network is back.** The server has an address, and the gateway it had before the
  update answers a ping.

The check looks every 15 seconds until it's healthy or the time runs out.

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

## Containers

The server has Podman, with the `docker` command (`podman-docker`) and compose
(`podman-compose`). `setup` enables `podman.socket`, so tools that talk to Docker's socket
work too. The lab's compose files run as they are.

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
```

`bromigos server status --json` gives the same as JSON: `hostname`, `addresses`, `ssh`,
`firewall`, `updates`, `rollbacks`, `containers`, `cluster` and `monitoring`. The Server's
home screen in the console reads it.

| Command | What it does |
|---|---|
| `bromigos server` | The status, above |
| `sudo bromigos server update --now` | An update now, with the same snapshot and check |
| `sudo bromigos server firewall allow\|deny NAME` | Opens or closes a rule set |
| `sudo bromigos server setup` | Applies `server.toml` again |

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
- set the default target to `multi-user.target`, with no display manager and no audio;
- not run `bromigos install` or `bromigos setup`, which set up the desktop. Run
  `bromigos-apps-setup` as the new user instead.

## Tests

```sh
python -m unittest discover -s server/tests
```

The tests run `bromigos-server` in a stand-in root, with stand-in `systemctl`, `bromigos`,
`ip`, `ping` and `nft`. They cover the firewall's rules from the settings, the SSH password
rule, an update with nothing to do, a healthy update, an unhealthy one rolled back once and
then flagged, ignored units, a kernel update's restart, a start that hung, and the status
document. Where user namespaces work, the firewall's rules are checked by the real `nft`.
Nothing on the machine running them changes.
