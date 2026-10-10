# Setting up your lab

`bromigos lab provision` generates a Git repository for your lab and applies its Ansible
roles from the desktop. The first slice installs Core services, or adds k3s, Helm,
Argo CD and Vault. The [manual](../manual/src/lab.md#setting-up-a-lab) explains how to run it.

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
| Core | Caddy, Netdata, restic and Homepage in containers |
| Advanced | Core, k3s, Helm, Argo CD and Vault |

On an existing cluster, Core uses a generated Helm chart. The provisioner installs no
new Kubernetes server there. All its web services use ClusterIP services, which are
reachable inside the cluster. Use a port forward to open them from your desktop.

Prometheus, Grafana and Loki remain in the catalog. They have no installer in this slice.

## Reach and inventory

The first probe reads the distribution, CPU count, RAM and free root disk space over SSH.
It tests sudo access without changing the machine. A failed connection explains how to
use `ssh-copy-id`. It never disables host key checking. `--known-hosts` selects a trusted
host key file when the default SSH file is unsuitable.

For an existing cluster, the probe reads nodes and their available CPU and RAM. It cannot
infer free persistent storage from those numbers. The plan says that disk capacity needs
checking before approval.

## Selection and sizing

`services.py` resolves service dependencies, roles and conflicts. The provisioner uses
it for the terminal checklist, `add`, `remove` and the console's Provision tree. Helm
needs a cluster. Argo CD and Vault need Helm. Presets include the default Core services.
Custom selections can untick them; removing restic warns about losing backups.

The plan adds each service's RAM and disk needs. It keeps the catalog's RAM and disk
headroom free. CPU needs are compared with the largest service requirement. A known
capacity shortage stops apply. Unknown cluster storage is a review note, rather than an
invented capacity number. No models are downloaded by this slice.

## The generated repository

| File or folder | What it holds |
|---|---|
| `plan.json` | The user's target, selection, inventory and choices |
| `ansible/inventory/hosts.json` | The Ansible target |
| `ansible/roles/` | Core containers, k3s and Helm installation tasks |
| `ansible/requirements.json` | The pinned Ansible collection installed at apply |
| `ansible/playbooks/provision.json` | The playbook run from the desktop |
| `compose/` | Core's container definitions and Caddy and Homepage settings |
| `helm/<service>/values.yaml` | Values for the selected Kubernetes services |
| `gitops/root.yaml` | Argo CD's app-of-apps, when selected |
| `gitops/argocd-apps/` | Its child applications |
| `secrets.enc.json` | sops and age ciphertext when Vault is absent |

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
find, create or mount NAS shares.

Verify checks running containers and Core's HTTP responses, cluster node readiness,
Vault's seal state, the first backup and Argo CD's synced and healthy applications.
It adds a `provisioned` source to `homelab.toml`, preserves existing sources and target
choices, and creates `targets.toml` if needed. No AI service is selected, so it leaves
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

The Argo CD admin password and generated restic password go into Vault when selected.
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

`homelab/tests/test_provision.py` checks complete Core and Advanced plans, resolver
failures, capacity checks and the secret boundaries. The existing catalog and console
tests cover the rest of the resolver and the terminal dashboard.

`test/vm/lab-provision-e2e.py` creates a fresh Debian guest through `lab-vm.py` and
`vm-keeper.py`. It uses a sandbox home, its own SSH key and an isolated Git server. It
runs Core and Advanced, repeats apply, checks backup success, k3s readiness, Argo sync,
Vault initialisation and unseal, and the doctor. It also tests the same isolated cluster
through an explicit kubeconfig and context, with local Ansible and no desktop sudo. It checks that no Vault share appears
in files or captured output. Its cleanup stops the VM and removes its disk.

## Work reserved for later slices

The approved design also covers these features. They are not built here:

- Proxmox VM and container creation.
- GPU inventory, driver installation and model download sizing.
- Prometheus, Grafana, Loki and the AI, games, media, home and network services.
- Finding a NAS, creating shares and testing and mounting NFS or SMB storage.
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
