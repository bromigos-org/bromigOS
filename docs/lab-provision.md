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
| SSH | `ssh` with `StrictHostKeyChecking=yes` and `BatchMode=yes` | the host key fingerprint to confirm, then `ssh-copy-id` in the terminal |
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
- Service removal with a separate data-retention decision.
- Scheduled Vault Raft snapshots and backups of the cluster control plane.
- Updating pinned images and chart versions through `bromigos lab update`.
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
