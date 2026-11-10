# Setting up your lab

`bromigos lab provision` generates a Git repository for your lab and applies its Ansible
roles from the desktop. Run with no arguments, it guides a new user through setting up a
spare box, one checked step at a time. The first slice installs Core services, or adds k3s, Helm,
Argo CD and Vault. It creates Proxmox or KVM VMs and multi-node clusters. Every plan
includes Prometheus, Grafana, Loki and Alertmanager. It provisions agents against existing model endpoints, as
explained in [Agents in your lab](lab-agents.md). The [manual](../manual/src/lab.md#setting-up-a-lab) explains how to run it.

This implements part of the provisioning design approved on 2026-10-09. The remaining
work is listed below. The service catalog still contains services reserved for that work.
The provisioner refuses selections that have no installer.

## Targets and presets

An SSH target is one Linux box running Debian, Ubuntu, Fedora or Arch Linux. It needs
Python 3, a trusted SSH host key, key login and passwordless sudo. The installer supports
x86-64 and ARM64. An existing cluster needs an explicit kubeconfig and context. It must
have a default storage class for Vault's persistent disk. The desktop never runs sudo.

| Preset | What this slice installs |
|---|---|
| Core | Caddy, Netdata, restic, Homepage and monitoring |
| Advanced | Core, k3s, Helm, Argo CD, Vault and Kubernetes monitoring |

On an existing cluster, Core uses a generated Helm chart. The provisioner installs no
new Kubernetes server there. All its web services use ClusterIP services, which are
reachable inside the cluster. Use a port forward to open them from your desktop.

VM providers, storage selection, cluster growth and the required monitoring installer
are described in [VMs, cluster nodes and monitoring](lab-infrastructure.md).

## Reach and inventory

The first probe reads the distribution, CPU count, RAM and free root disk space over SSH.
It tests sudo access without changing the machine. A failed connection explains how to
use `ssh-copy-id`. It never disables host key checking. `--known-hosts` selects a trusted
host key file when the default SSH file is unsuitable.

For an existing cluster, the probe reads nodes and their available CPU and RAM. It cannot
infer free persistent storage from those numbers. The plan says that disk capacity needs
checking before approval.

### The hardware check

The same probe also reads the box's hardware. It only reads. It never formats, mounts or
changes a disk, and it loads no driver. The code is `homelab/lib/bromigos_homelab/hardware.py`.
Its `collect` function runs on the box. `provision.py` sends its source over SSH with the
rest of the probe, so the box needs nothing installed beyond Python 3. Every tool is
optional, and a missing tool falls back to files.

| What | Read from | Without the tool |
|---|---|---|
| GPUs and their drivers | `/sys/bus/pci/devices`, names from `lspci -mm -nn -D` | names from the box's `pci.ids` |
| NVIDIA memory and driver | `nvidia-smi` | the GPU shows "no driver loaded" or the driver it has |
| AMD memory | `/sys/class/drm/card*/device/mem_info_vram_total` | |
| Disks | `lsblk -J -b`, with `MOUNTPOINTS` or the older `MOUNTPOINT` column | `/sys/block`, which can't show whether a disk is empty |
| Mounted folders and NAS shares | `/proc/mounts`, with free space from `statvfs` | |
| Network cards | `/sys/class/net/*`: speed, link state, and Wi-Fi or wired | |
| CPU | `/proc/cpuinfo`: model and the `vmx` or `svm` flag; `/dev/kvm` | `lscpu` for ARM model names |
| Laptop or not | the DMI chassis type and a battery | |
| Devices of interest | `/sys/bus/usb/devices`; Coral PCIe cards from the PCI list | `lsusb` |

A disk counts as empty only when lsblk shows no partitions, no filesystem and no mount
point. Empty disks are suggestions only. Disks that are RAID, LVM or ZFS members, swap or
encrypted say so. Removable disks are listed but never suggested for backups. Disks
under 1 GB, such as a VM's seed image, are left out. Basic
display chips, such as a server's management controller or a VM's virtual screen, don't
count as GPUs. A GPU counts for sizing only when its driver works: `nvidia-smi` answers
for NVIDIA, and `amdgpu`, `i915` or `xe` is bound for AMD and Intel.

USB sticks are matched by their USB IDs and names. A Zigbee or Z-Wave stick, a Coral Edge
TPU or a camera gets a "could be used for" hint. The hints never add a service.

The plan prints the results under **Hardware**, in plain words:

```text
Hardware:
  Box: Debian, x86-64, 16 CPU threads, 64 GB memory, 429 GB free on the system disk
  CPU: AMD Ryzen 9 5950X 16-Core Processor, virtualisation available (AMD-V)
  GPU: 2 × NVIDIA GeForce RTX 3090, 24 GB each, driver loaded
  System disk: 1 TB NVMe (Samsung SSD 980 1TB)
  Spare disk: 4 TB HDD (WDC WD40EFRX-68N32N0), empty, not mounted
  Wired network: enp5s0, 2.5 Gb/s, connected
  USB: Coral Edge TPU. Could be used for fast object detection in Frigate
```

Notes follow the hardware. A selected service that needs a GPU warns when the box has
none, or when its GPU has no working driver. No service in this slice needs a GPU yet. Backups on the system disk get a warning,
and mounted disks, NAS shares and empty disks are suggested instead. A box with only
Wi-Fi connected, or a wired link slower than 1 Gb/s, gets a note too. None of these
notes changes the plan.

On an existing cluster the check reads GPUs from node labels and allocatable resources:
`nvidia.com/gpu`, `amd.com/gpu` and `gpu.intel.com/i915`, with NVIDIA's product and
memory labels. A node with a Node Feature Discovery GPU label but no allocatable GPU
is reported as found but not yet usable, because it has no device plugin.

## The guided setup

`bromigos lab provision` with no arguments, or with `--guided`, runs the guided setup in
`guidedprovision.py`. It is for a first lab on one spare box. Each step checks first. It
acts only after the user answers yes, and it never runs sudo on the desktop.

| Step | What it checks | What it offers |
|---|---|---|
| Desktop tools | Ansible, sops, age, Git and SSH | the exact `sudo pacman -S --needed …` line for the user to run |
| Age key | sops's key file, `SOPS_AGE_KEY_FILE` or `~/.config/sops/age/keys.txt` | to create it with `age-keygen` |
| The box | a saved answer | after Find my lab's yes, the machines it found that answer SSH; else the address, user name and SSH port |
| SSH | `ssh` with `StrictHostKeyChecking=yes` and `BatchMode=yes` | the host key fingerprint to confirm, then `ssh-copy-id` in the terminal. When signed in to a Bromigos account, its SSH keys first |
| Python and sudo | `python3` and `sudo -n true` on the box | the install command, and the `visudo` line to add |
| Hardware | the read-only probe above | nothing; it shows the results |
| Preset | Core and Advanced against the box's size | a recommendation, and the Git URL for Advanced |
| Backups | mounted disks and NAS shares on the box | a folder on one of them, created on the box only after a yes |
| Plan | `plan.json` in the lab repository | to generate it, commit it, then apply after `yes` |

The host key step runs `ssh-keyscan`, shows the fingerprints, and tells the user how to
read them on the box itself. Only an exact `yes` adds the key to `~/.ssh/known_hosts`. A
changed host key stops the setup. The plan's target names that file and the SSH key
explicitly, so SSH and Ansible check the same host key the user confirmed. When a step needs the user to act on the box, the
setup prints the command and waits for Enter. Typing `q` stops it.

Answers are kept in `$XDG_STATE_HOME/bromigos/lab-provision.json`, or
`~/.local/state/bromigos/lab-provision.json`. The file holds the box's address, the
choices and the lab repository's path. It never holds a private key or password. Running
the setup again skips every step that is already done. It checks the tools and SSH again,
which is quick. It reuses saved answers, and it doesn't rewrite an unchanged plan. Apply
then runs again after `yes`, which converges the lab. `--start-over` forgets the saved answers.

The box step can look for the box. It shows the same question as `bromigos setup homelab
--find` ([Find my lab](homelab.md#find-my-lab)), listing the sources it reads. After a
yes, it runs that search, then tries port 22 on the machines found, and only on those. The
ones that answer are a numbered list, with "Type an address" as the last choice. A no, or
nothing found, asks for the address as before. `findlab.ssh_boxes` does the port check.

## Your account's SSH keys

When the desktop is signed in to a Bromigos account
([bromigos-account.md](bromigos-account.md)), provisioning offers the account's SSH public
keys for the box's `~/.ssh/authorized_keys`, for the user it provisions through. The code
is `accountkeys.py`. Signed out, or without `lib/bromigos_login.py`, which the standalone
lab package doesn't include, nothing is offered.

1. `bromigos_login.account_ssh_keys()` reads the keys with the sign-in's token. Each key is
   checked: a known type, no options and no line breaks. Its fingerprint is worked out on
   the desktop.
2. Provisioning reads the box's `authorized_keys` and lists only the keys that aren't
   there, with their fingerprints.
3. After an exact `yes`, a short POSIX shell script appends those keys, reading them on
   stdin. It never removes or rewrites a line. It makes `~/.ssh` (mode 0700) and
   `authorized_keys` (mode 0600) only when they're missing.

In the guided setup, this happens in the SSH step. When the box already takes the
desktop's key, it runs over the same key login. When it doesn't yet, the setup offers the
keys before `ssh-copy-id`, over one password login (`BatchMode=no`, still with
`StrictHostKeyChecking=yes`). If the desktop's own key is among them, SSH then works and
`ssh-copy-id` isn't needed. The fingerprints added go into the saved answers as
`account_keys`. The ones the user declines go into `account_keys_declined`, and aren't
offered for that box again. A failure to read the account is said, and the setup carries
on.

`bromigos lab provision --ssh …` offers the same after its inventory, when stdin is a
terminal. `--no-account-keys` turns it off.

## The box announces itself

Every provisioned box announces itself on the local network, so Find my lab always finds
it. The plan's `announce` role installs Avahi, the mDNS service, and adds
`/etc/avahi/services/bromigos-lab.service`. That file announces a `_bromigos-lab._tcp`
service named "bromigOS lab on" and the box's host name.

- The announced port is the box's SSH port, the one bromigOS provisions it through.
- Its one TXT record is `txtvers=1`. No service list, version or name of yours goes on the
  network.
- A cluster plan's first control node announces itself too. Find my lab finds the other
  nodes through the Kubernetes source.
- A box behind a firewall must let mDNS through, which is UDP port 5353.

`announce.py` generates the role. `homelab/tests/test_findlab.py` checks the role and that
Find my lab recognises the announcement.

## Selection and sizing

`services.py` resolves service dependencies, roles and conflicts. The provisioner uses
it for the terminal checklist, `add`, `remove` and the console's Provision tree. Helm
needs a cluster. Argo CD and Vault need Helm. Presets include the default Core services.
Custom selections can untick Core services; removing restic warns about losing backups.
Monitoring is required and cannot be removed from a plan.

The plan adds each service's RAM and disk needs. It keeps the catalog's RAM and disk
headroom free. CPU needs are compared with the largest service requirement. A known
capacity shortage stops apply. Unknown cluster storage is a review note, rather than an
invented capacity number. No models are downloaded by this slice.

## The generated repository

| File or folder | What it holds |
|---|---|
| `plan.json` | The user's target, selection, inventory and choices |
| `ansible/inventory/hosts.json` | The Ansible target |
| `ansible/roles/` | Core containers, k3s and Helm installation tasks, and the box's mDNS announcement |
| `ansible/requirements.json` | The pinned Ansible collection installed at apply |
| `ansible/playbooks/provision.json` | The playbook run from the desktop |
| `compose/` | Core's container definitions and Caddy and Homepage settings |
| `helm/<service>/values.yaml` | Values for the selected Kubernetes services |
| `gitops/root.yaml` | Argo CD's app-of-apps, when selected |
| `gitops/argocd-apps/` | Its child applications |
| `secrets.enc.json` | Encrypted credentials, including bootstrap credentials before Vault starts |
| `infrastructure.json` | VM providers, node sizes and storage choices for cluster plans |
| `monitoring/` | Dashboards and single-box monitoring settings |

JSON files are also valid YAML input for Ansible and Kubernetes. The generator is a pure
function before its files are written. Golden tests compare its full output.

The repository belongs to the user. It is not bromigOS's source repository. Generated
target addresses and local paths stay there. The generator refuses to rewrite a dirty
Git repository. Users review, commit and publish its files themselves. Argo CD needs the
published Git URL before apply; an empty or credential-bearing URL is refused.

## Apply and verify

Apply takes a fresh inventory, prints services, ports and sizes, then waits for the exact
answer `yes`. It runs `ansible-playbook` from the desktop. Container images, k3s, Helm
and chart versions are pinned. Helm's archive checksum is checked. Ansible output is
suppressed to keep credentials out of logs.

Core binds only Caddy's ports on a Linux box. They bind to loopback by default.
`--listen-address` can select a private IPv4 address; a public address is refused. Homepage and Netdata are behind it. With
`--domain`, Caddy issues a local HTTPS certificate. The user must point that name at the
box and trust Caddy's local certificate authority. Without a name, the first setup uses
HTTP. This slice does not configure public DNS or expose a cluster service publicly.

Restic requires an existing backup destination. On a box, `--backup-path` is its absolute
path. On a cluster, it names an existing persistent volume claim in `lab-core`. The first
backup must succeed before verify passes. Further backups run daily. Core backs up its settings, Caddy data and Netdata data. This slice does not
create NAS shares. Cluster plans can mount an explicitly selected existing NFS export.

Verify checks running containers and Core's HTTP responses, cluster node readiness,
Vault's seal state, the first backup and Argo CD's synced and healthy applications.
It adds a `provisioned` source to `homelab.toml`, preserves existing sources and target
choices, and creates `targets.toml` if needed. When no model server is selected, it leaves
the default AI target order alone. The provisioned adapter reads the explicit target
through SSH or the chosen kubeconfig. It checks the live lab, not a saved health result.
Finally apply runs `bromigos lab doctor`.

## Vault and credentials

Vault uses five Shamir shares, with three needed to unseal it. Initialisation and secret
writes use its HTTP API through a temporary local port forward. Shares stay in memory.
They are shown once through `/dev/tty`, outside stdout, stderr and Ansible output. Apply
waits for the user to confirm that they saved them in a password manager. Losing the
shares can permanently lose access to Vault.

The user chooses a Vault operator password during the first apply. Its account can read
and write the provisioner's service credentials. The initial root token is never printed
or saved. It is revoked after setup. Later runs ask for the operator password. Vault's
normal recovery procedure can restore access using the stored shares.

Automatic unseal is off by default. A separate explicit `yes` stores three shares in a
Kubernetes Secret and installs an unseal job. Cluster administrators can read that Secret.
This trades independent recovery protection for unattended restarts. The other two shares
remain with the user. The Secret and its values never enter the generated Git repository.

The Argo CD, Grafana, cluster join and generated restic credentials go into Vault when selected.
Bootstrap credentials also stay age-encrypted so repeat apply can start before Vault.
Without Vault, generated credentials enter sops through stdin and only age-encrypted
ciphertext is written to the repository. Runtime services still need credentials: restic
reads a root-owned file on a box or a Kubernetes Secret on a cluster. These runtime
credentials are not copied into the public product. An existing backup password is
preserved on repeat runs.

## Keep running

Applying the reviewed repository again converges the selected services. It does not
uninstall services, prune applications or delete disks. `add` and `remove` change the
selection and regenerate the plan; they do not apply it. Dependencies may add a removed
service back, and the plan explains that choice. Removing a service leaves its running
resources and data in place.

## Tests

The infrastructure golden tests, fake Proxmox API and nested VM test are described in
[Infrastructure tests](lab-infrastructure.md#extensions-and-tests).

`homelab/tests/test_provision.py` checks complete Core and Advanced plans, resolver
failures, capacity checks and the secret boundaries. The existing catalog and console
tests cover the rest of the resolver and the terminal dashboard.

`homelab/tests/test_provision_hardware.py` runs the hardware check against fake `/sys`
trees and recorded tool outputs in `homelab/tests/fixtures/hardware/`. It covers a box
with two GPUs and every tool, a box with no tools at all, a laptop on Wi-Fi with the
nouveau driver, and a server with no GPU, RAID members and an old `lsblk`. It checks the
plan text, the notes and the cluster labels. It also runs the whole probe locally to prove
it prints facts, and checks that the collector parses as Python 3.6.

`homelab/tests/test_provision_guided.py` drives the guided setup with scripted answers, a
fake terminal and a fake box. It checks a first run, a second run that asks nothing, a
refused or changed host key, missing tools, Python and sudo, bad answers and a folder that
already holds other files. It also checks the box step's pick list from Find my lab: a no
reads nothing, a found machine can be picked, and "Type an address" still works.

`homelab/tests/test_provision_accountkeys.py` checks the account's SSH keys on the box. The
box's `authorized_keys` is a real file in a temporary home, changed by the real script. It
checks that only missing keys are offered and added, existing lines and modes stay, a no is
remembered, one password login can replace `ssh-copy-id`, and a signed-out or unreadable
account changes nothing.

`test/vm/lab-provision-e2e.py` creates a fresh Debian guest through `lab-vm.py` and
`vm-keeper.py`. It uses a sandbox home, its own SSH key and an isolated Git server. It
runs Core and Advanced, repeats apply, checks backup success, k3s readiness, Argo sync,
Vault initialisation and unseal, and the doctor. It also tests the same isolated cluster
through an explicit kubeconfig and context, with local Ansible and no desktop sudo. It checks that no Vault share appears
in files or captured output. Its cleanup stops the VM and removes its disk.

## Work reserved for later slices

The approved design also covers these features. They are not built here:

- Proxmox container creation and additional VM providers.
- GPU driver installation and model download sizing. The hardware check reports GPUs and
  their drivers, but installs nothing.
- New model servers, and games, media, home and network services. The hardware check's
  USB hints name possible uses, but don't add a service.
- Finding a NAS on the network, creating shares, SMB mounting, and creating RAID or ZFS
  pools. The hardware check only sees NAS shares already mounted on the box.
- Formatting and mounting a spare disk. The hardware check only suggests one.
- The catalog's app-specific configure steps, account sign-in and library setup.
- Public certificates, DNS and opt-in tunnels.
- Updating and rolling back an app with `bromigos lab apps update` and `rollback`, and a
  person's own Compose file or Quadlet through `bromigos lab apps add --file`. Listing,
  adding, removing (keeping or deleting the data), restarting and logs are built
  ([lab.md](lab.md#apps-on-a-server)).
- A seven-day snapshot of an app's data before `bromigos lab apps remove --delete-data`.
- Scheduled Vault Raft snapshots and backups of the cluster control plane.
- Updating pinned images and chart versions through `bromigos lab update`. For the local
  target's apps that means a CI job that tests and moves the catalogue's digests, and the
  server updating each app behind a snapshot of its data, with a check and a rollback
  ([Updates](#updates)). Until then no container app updates by itself.
- Provisioning from Settings, with the plan beside its service tree.

These features continue to use the catalog's existing `needs`, `depends`, `conflicts`,
`provides`, `storage`, `mounts`, `account`, `source` and `configure` fields. The shipped
installer does not silently treat them as implemented.

### Configure steps

The remaining design records app setup as `[[service.<id>.configure]]` tables. A step's
`do` chooses `folder`, `first-run`, `secret`, `sign-in`, `library`, `setting` or `timer`.
Steps run in order after a service starts. A step with `on = "<role>"` applies to each
selected provider of that role. Repeating a step must leave existing data in place.

Values can refer to `{tz}`, `{media}`, `{downloads}`, `{backups}`, `{url:<service>}` and
`{secret:<name>}`. An app's own double-brace templates are passed through unchanged.
These configure steps remain design data; this slice does not run them.

## The local target

`bromigos lab provision --local` sets up the machine it runs on. A bromigOS Server runs it on
its first boot from the installer's answer file, and the welcome tour shows its progress. It
reads the provisioning catalogue instead of the Core and Advanced presets; `--preset` maps
those onto catalogue items (`provcatalog.TIERS`), and the SSH and cluster targets above work
as before.

### The catalogue

`homelab/share/provision-catalogue.toml`, installed by bromigos-lab as
`/usr/share/bromigos/lab/provision-catalogue.toml`. The file's header documents every key.
Each `[[item]]` has an id, a group (`lab-core`, `ai`, `network`, `storage`, `games`, `home`,
`media`, `brodec`), a name, a one-line description, a hover hint, an Adwaita symbolic icon and
a console glyph (a key of `bromigos_textual.ICONS`), what it needs and conflicts with, the
roles that tick it, its hardware needs, its download size, ports, whether it needs the
internet, and how it installs:

- `install = { pacman = [...] }`, with `nvidia = [...]` or `amd = [...]` in its place on that
  GPU, and `enable` for the units to start;
- `install = { quadlet = "TEMPLATE" }`: Podman Quadlet units from `share/quadlet/TEMPLATE/`,
  with every image in `images` pinned by digest;
- `install = { step = "STEP" }`: a step in `localprovision.STEPS` (k3s, OpenBao, monitoring,
  backups, Caddy, the media library, Wings, …).

`[item.setup]` is a small form for the UIs: fields (`text`, `number`, `bool`, `choice`,
`secret`, `path`), choices with notes and links, `show_if`, actions with a URL, and the name of
a live check (`bromigos lab provision --check ITEM`).

#### Format 2: what an app manager needs to know

The file says `format = 2`. Format 2 adds keys to each item and changes none, so anything
that read format 1 reads this file the same way. The installer's own reader is one such.
The new keys describe an item well enough to show it as a tile, open its page, find its
data and ask whether it answers. `bromigos lab apps` reads them for each app's tile, its
health check and its data's size ([lab.md](lab.md#apps-on-a-server)). The update path,
which reads the rest, is under [work reserved for later slices](#work-reserved-for-later-slices).

| Key | What it holds |
|---|---|
| `job`, `app` | The name's two halves, apart: the job ("Photos") and the program ("Immich"). `name` stays as it was. |
| `holo` | The id of our own icon for the job, from `provcatalog.HOLO`. Items that do the same kind of job share one. |
| `web = { name, port, path }` | The item's page. See [App names](#app-names). |
| `[[item.data]]` | One for each folder or file the item keeps under `/srv/apps/<item>`. |
| `health` | How to ask the app whether it answers. |

**Data.** Each `[[item.data]]` has a `path` inside the item's own folder, a `kind` and a
sentence, `what`, that says what is in it. An item that runs containers lists exactly the
folders its template mounts from `{{data}}`. `validate()` compares the two, so a template
can't gain a folder the catalogue doesn't know. `localprovision.data_paths(item)` gives
the whole paths, such as `/srv/apps/photos/library`.

| `kind` | Means |
|---|---|
| `library` | Your own files: photos, documents, a game's world. |
| `database` | The app's records of what you did in it: accounts, history, what you follow. |
| `config` | Its settings and working files. |
| `cache` | Safe to lose. The app downloads or makes it again. |

Two container items list no data, because they keep none of their own: the VPN for
downloads (Gluetun) and Unpackerr. Items that aren't containers list none yet.

**Health.** A check is one of two shapes.

- `health = { http = "/api/server/ping", port = 2283 }` is a GET to that path on
  `127.0.0.1`, with nothing signed in and no redirect followed. `expect` is the status
  the first answer must have, as a number or a list. It is 200 when left out. `port` is one
  of the item's `ports`.
- `health = { cmd = ["podman", "exec", "minecraft", "mc-health"] }` runs a command inside
  one of the item's own containers. Exit code 0 means it answers.

`within_s` is how long a start may take before "no answer" counts. It is set only where
the app's own project gives a figure.

Every check is the app's own, never one we made up: the path or command its image's
`HEALTHCHECK` runs, or the one its documentation or source names as open to anyone. The
comment above each `health` line says which. Nothing was run to choose them, so a check is
as good as its project's word until a job starts each image and asks.

Two container items have no check, and say why in the file. Recyclarr runs on a timer and
listens on no port. Unpackerr listens on none unless its metrics are turned on, and here
they aren't. Items that aren't containers have none yet.

**Keys the reader knows and no item fills yet.** `homepage`, `licence`, `remove_note`,
`version` (the recipe's own revision, 1 when left out), `app_version`, `changed`, `track`,
`status` with `status_note`, `download_mb`, `[item.update]` and `[item.tile]`. `validate()`
checks their shape. The commands that read them will fill them.

`validate()` also names any key it doesn't know, so a misspelt key is a problem and not a
key nobody reads.

#### Reading the catalogue

`bromigos_homelab.provcatalog` reads it for the installer, the tour and the CLI:

| Call | Returns |
|---|---|
| `load(path=None)` | every item, defaults filled in |
| `groups()` | `[{id, name, icon, glyph}]` |
| `resolve(ids)` | `(ids with their needs, needs first; the ids added)`; an `a\|b` need is met by either |
| `budget(ids, hw, models=())` | `{cpu, ram_gb, disk_gb, gpu_vram_gb, fits, notes}`; notes are plain sentences |
| `recommend(roles, hw, lab="none")` | the ids the roles tick for this hardware and lab answer (several roles: the union) |
| `suggest_models(hw)` | models from the lab model catalogue sized to the GPU: `[{id, capability, name, serve_with, vram_gb, …, default}]` |
| `conflicts(ids)`, `fits_item(item, hw)`, `validate()` | sentences; `[]` when the catalogue is consistent |
| `web_names()` | `{item: name}` for the web apps that have a name on the local network |

`hw` is `{cpu, ram_gb, disk_gb, gpu (False or "nvidia"/"amd"/"intel"), gpu_vram_gb, gpu_name}`;
`localprovision.detect()` reads this machine's.

The salvage scan (`bromigos hw salvage`, [salvage.md](salvage.md)) asks the same calls about
a computer nothing is installed on yet: every item and every role, one at a time. So the
installer's meter and the scan give one answer to "does this fit".

Roles: `lab-node`, `storage`, `home-services`, `game-server`, `media`, `base` (also accepted:
`just-a-server`, bromigOS Server's name for it). Items with `default = false` are listed under
their role but never ticked for you; `lab = [...]` limits an item to some lab answers (Wings
when there's a lab, the Minecraft template without one).

### Plan and apply

`--plan [--json]` lists, per item, how it installs, its services, ports, needs, downloads and
whether it needs the internet, then the budget and any problem (two items that conflict, a
model whose server isn't chosen). `--apply` installs in dependency order and prints:

```text
::stage PCT words
::item ID waiting|downloading|installing|done|failed|skipped-offline
::note ID words
::error ID words
```

Run through `bromigos activity run`, these lines become a job's record, with each item a
step ([activity.md](activity.md#make-a-script-a-job)).

Items that need a download are `skipped-offline` while there's no network and installed when
it comes (NetworkManager's connectivity check, else a connection to pkgs.bromigos.org). Items
that don't need one go ahead. `--no-wait` exits 75 instead of waiting. A failed item is
reported with `::error` in words and its dependents fail with the reason; the rest carry on.
`/var/lib/bromigos/lab/provision-local.json` records each finished item with a fingerprint of
what it installed, so a re-run leaves finished items alone and redoes only changed ones. It
also keeps the recipe's revision (`recipe`) and the app's version (`app_version`) as
installed. The apply adds what it set up to `/etc/bromigos/lab/apps.toml`, the list of what
this server is meant to run ([lab.md](lab.md#what-the-server-is-meant-to-run)).

Media items get wired together after they install: qBittorrent and SABnzbd as download
clients in Sonarr, Radarr and Lidarr, with their categories, and the root folders. No source
is ever added.

### App names

Each web app Caddy serves gets one name on the local network, `<app>-<server>.local` (for
example `photos-myserver.local`, `media-myserver.local`), with HTTPS from Caddy's own authority
(`tls internal`).

The name and the port are the catalogue's: each item's `web = { name, port }`. The port is
the one Caddy sends the name to, and the one the start page links to. For most items it is
the first of `ports`. Monitoring's is Grafana's, 3005, and the same key sets the port
Grafana listens on. The S3 bucket server's is RustFS's console, 9001: its first port, 9000,
is the S3 API, which answers a browser with an error. An item whose `web` has a port and no name has a page on that port
and no name of its own: Sonarr is at `http://<server>.local:8989`. `path` is where the
page is, when it isn't `/`.

The names are one label on purpose. Every mDNS resolver answers a one-label
`.local` name: Linux's nss-mdns and systemd-resolved, Apple's mDNSResponder, Android's resolver
(November 2021 on) and Windows' DNS client. A subdomain such as `photos.<server>.local` is
answered by some of them and not others.

avahi announces only the host's own name, so `bromigos-lab-mdns-names.service`
(`bromigos lab mdns-names publish`, `bromigos_homelab/mdnsnames.py`) publishes each app's name.
It reads `/etc/bromigos/lab/mdns-names`, which the Caddy step writes, and points each name at
the address the default route leaves from. When that address changes, the names follow it
within 15 seconds. `bromigos lab mdns-names list` shows them.

Tested between two VMs on one network (avahi publishing, a client with nss-mdns as bromigOS sets
it up, and a client with systemd-resolved's mDNS): both shapes resolve on Linux, the one-label
shape being the one every other platform documents.

### The answer file

The installer writes `[server]` in `/var/log/bromigos/install-answers.toml`:
`roles = [...]`, `lab = "new" | "join" | "none"`, `lab_join = {bundle = PATH}` or
`{pair = true}`, `provision = [ids]`, `models = [ids]`, and `[server.settings.ITEM]` with
setup fields. Secret fields are references (`{secret = "local:NAME"}`, `vault:…`, `sops:…`,
`bitwarden:…`), never values; a plain value is refused. `--from-answers FILE` reads it.

### Quadlet templates

`share/quadlet/<template>/` holds the units; `_common/bromigos-lab.network` is the network
every app shares. Placeholders: `{{data}}` (`/srv/apps/<item>`: on a bromigOS Server with
data disks `/srv/apps` is on them, [server.md](server.md#where-the-apps-keep-their-data)), `{{media}}`,
`{{downloads}}`, `{{tz}}`, `{{host}}`, `{{puid}}`/`{{pgid}}` (the `bromigos-media` account),
`{{image:NAME}}` (`NAME-nvidia` on an NVIDIA server when listed), `{{secret:NAME}}` (the Podman
secret's name) and `{{setting:FIELD}}`. A line that starts `#if:ITEM `, `#ifnot:ITEM `,
`#ifset:FIELD ` or `#ifgpu:VENDOR ` is kept only when that holds. Secrets are mounted as files
(`type=mount`) wherever the app reads files.

### Where the data goes

Every item keeps its data in `/srv/apps/<item>`. On a bromigOS Server with data disks,
`/srv/apps` is a mount of the data disks' `apps` subvolume, so the data is on them
([server.md](server.md#where-the-apps-keep-their-data)). Anywhere else it is a folder on
the system disk. The plan's disk number is the free space under `/srv/apps` when that
folder is there, so it measures the disk the data goes to.

When `/etc/fstab` mounts `/srv/apps` and it isn't mounted, an item that keeps data there
fails with the reason and nothing is set up: the data disks are away, and the folder
behind the mount is the system disk's.

The media library (`/srv/media`) and the backup place (`/srv/backups`) are on the data
disks the same way, each in a subvolume of its own, and refuse the same way while the data
disks are away. A media library on a NAS share takes that folder over: the engine turns
the data disks' `fstab` line for `/srv/media` into a comment and unmounts their subvolume
before it mounts the share.

Passwords (Vaultwarden) is a package whose own settings file keeps the vault in
`/var/lib/vaultwarden`. Its step gives it `/srv/apps/passwords` and writes the two files
that tell the service (`appdata.py`'s `VAULT_ENV` and `VAULT_DROPIN`). When a vault is in
the package's folder already, the step leaves it there and writes neither file. Its
address and web vault come from a file too, `/etc/bromigos/lab/vaultwarden.env`
(`VAULT_SETTINGS`), because the package's file turns the web vault off and a file wins over
any `Environment=` line.

Some apps need a file before they start, written by a `prepare` step (`PREPARE`):
LiteLLM's `config.yaml` (a file the container mounts, never a folder), the start page's
links, Recyclarr's profiles, qBittorrent's first settings, and Autoscan's `config.yml`.
Autoscan exits without one. Its file has the triggers Sonarr and Radarr call, and the
media servers it tells where the engine knows them: Jellyfin with the API key in the secret
store (`jellyfin/api-key`), Plex with the token in its own `Preferences.xml` once it's
signed in. Autoscan reads its keys from that file alone, so the file is its account's,
`0600`. With neither, Autoscan starts and tells no one, and the plan's note says the one
step. The engine writes the file again only while it's as the engine wrote it (a digest on
its second line), so your changes stay.

**Backups.** On a bromigOS Server the Server's own nightly backup covers the apps
([server.md](server.md#backups)). Anywhere else, the Backups item (`step_backups`) writes
`bromigos-lab-backup.service`, which runs `restic backup --one-file-system` over `/etc`,
`/srv`, `/srv/apps`, `/var/lib/bromigos` and `/var/lib/vaultwarden`. `--one-file-system`
keeps it off other disks: `/srv/data` isn't read a second time, and `/srv/backups`, where
its own repository is by default, isn't backed up into itself. So `/srv/apps`, a disk of
its own on a server with data disks, is named by itself. Before restic, `bromigos lab
backups copy-databases` copies the apps' databases whole; after it, `bromigos lab backups
holds` fails the unit when the backup lacks `/srv/apps` or a copy failed. The engine writes
a hook for each app with a database file (`DATABASES`: passwords and documents) to
`/etc/bromigos/backup-databases.d/<item>.toml`.

`bromigos lab app-data` says where `/srv/apps` is. On a server installed before the
installer mounted it there, `bromigos lab app-data move` puts it on the data disks, and
the media library, the backups folder and a vault in the package's folder with it
(`bromigos_homelab/appdata.py`; [server.md](server.md#a-server-set-up-before-the-installer-did-this)).

### Updates

It depends on how an item installs.

- **Packages** update with the system. An item with `install = { pacman = [...] }`, or a
  step that installs a package (Vaultwarden, Syncthing, AdGuard Home, Caddy, Prometheus
  and Grafana, OpenBao, Samba), is an ordinary package. A bromigOS Server's nightly update
  brings its new versions.
- **Containers don't update by themselves.** That is most of the catalogue: every item
  with `install = { quadlet = … }`. Each image is pinned by digest in the catalogue, no
  template sets `AutoUpdate=registry`, and no CI job moves the digests. A container app
  stays at the version the catalogue pinned when it was installed.
- **k3s, Wings and the Helm charts** are pinned to one version in the engine
  (`localprovision.py`), and don't move by themselves either.

A container app changes only this way today: a bromigOS release ships a catalogue with a
newer digest for it, and someone runs the apply on the server again. The apply redoes the
items whose pinned image changed, and restarts them:

```bash
sudo bromigos lab provision --local --from-answers /var/log/bromigos/install-answers.toml --apply
```

That is a new image started on the old data, with no snapshot before it and no check
after it. Back the server up first.

Planned, and not built: a weekly CI job that tests each newer image and moves its digest,
and the server updating each container app after the system's own update, with a snapshot
of the app's data before, a check that it answers after, and a rollback when it doesn't.
It is in the list of [work reserved for later slices](#work-reserved-for-later-slices).

### What it doesn't do

- A self-hosted BRODEC Matrix homeserver isn't an item: BRODEC doesn't publish a supported way
  to run one yet.
- On a k3s lab, the lab's own Helm catalogue (`profiles.toml`) runs apps across the cluster;
  the local target runs them on this server with Podman.
- Wings joins a Pelican panel with the panel's own auto-deploy command.
