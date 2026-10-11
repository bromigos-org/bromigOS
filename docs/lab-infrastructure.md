# VMs, cluster nodes and monitoring

The provisioner can create Linux VMs on Proxmox or a configured libvirt host, then form a
k3s cluster. It can also use existing SSH machines. Every service plan includes
Prometheus, Grafana, Loki and Alertmanager. The user reviews resources and storage before
any VM is created. The [manual](../manual/src/lab.md#creating-a-cluster) covers the
commands.

## Providers and upstream research

`vmproviders.py` defines `Provider`: create, list, start, stop, delete, snapshot, console,
storage inventory and guest SSH public keys. A provider never receives an operator's
default endpoint. It receives the user's explicit configuration and an in-memory
credential. Mutations require the generated repository's ownership ID.

Proxmox uses its HTTPS API with certificate verification. It clones an existing cloud-init
template, waits for each task, sets CPU, RAM, disk size, bridge, VLAN and cloud-init
networking, then starts the guest. It does not import images, change storage configuration
or require a root token. An administrator prepares templates with Python, cloud-init and
the QEMU guest agent. The root disk defaults to `scsi0`; cloud-init uses `ide2`. GPU
passthrough uses an administrator-defined PCI mapping. Disks only grow.

The least-privilege and request details were checked against Proxmox's own [QEMU API
implementation](https://git.proxmox.com/?p=qemu-server.git;a=blob;f=src/PVE/API2/Qemu.pm;hb=HEAD)
and [guest-agent
API](https://git.proxmox.com/?p=qemu-server.git;a=blob;f=src/PVE/API2/Qemu/Agent.pm;hb=HEAD).
The [API guide](https://pve.proxmox.com/wiki/Proxmox_VE_API), [API
explorer](https://pve.proxmox.com/pve-docs/api-viewer/) and [cloud-init
guide](https://pve.proxmox.com/wiki/Cloud-Init_Support) describe the public interface.

Libvirt uses its Python bindings locally or through authenticated SSH. `vmhost.py` runs on
that host. It makes a full qcow2 copy in an existing file-backed pool, writes a cloud-init
seed and defines a domain with an ownership marker. It supports an existing libvirt
network or bridge, optional VLAN and PCI passthrough. It never starts a desktop privilege
prompt or runs desktop sudo. Local access must already work. Remote sudo is an explicit
provider setting. Required host tools are the Python libvirt bindings, `qemu-img` and
`cloud-localds`.

For local provisioning on bromigOS, the optional packages are `libvirt-python`,
`qemu-base` and `cloud-image-utils`. They provide the bindings, disk tools and
[cloud-init seed tool](https://archlinux.org/packages/extra/any/cloud-image-utils/files/).
On a remote host, install those host tools there instead.

Local libvirt defaults to `qemu:///session`. System access needs a preconfigured socket
with `auth_unix_rw = "none"` and no polkit access driver. An administrator must configure
and restart that daemon beforehand. The provisioner refuses interactive authentication and
never changes daemon access. Cloud-init seeds use read-only virtio disks so minimal cloud
kernels can see them.

Sources: libvirt's [domain XML](https://libvirt.org/formatdomain.html), [storage
pools](https://libvirt.org/formatstorage.html), [lifecycle and snapshot
commands](https://libvirt.org/manpages/virsh.html) and [QEMU guest-agent
API](https://libvirt.org/html/libvirt-libvirt-qemu.html). Authentication follows libvirt's
[access configuration](https://libvirt.org/auth.html). Guest-agent execution reads only
the guest's SSH public key. It does not change the guest. This key establishes SSH trust
before Ansible connects. SSH host-key checking stays on.

Both providers refuse a VM owned by another plan. Changed VM specifications are refused
instead of rebuilding an existing VM. Shutdown is graceful. A timeout stops the command;
there is no automatic force stop. Libvirt snapshots require a stopped VM. Proxmox snapshot
support depends on the selected storage backend. Console information is a command or link,
never an automatically opened desktop window.

## Cluster specification

The specification is JSON. Paths and addresses are supplied by the user. `distribution`
defaults to `debian`; set it to match the prepared image. All nodes in this slice use that
distribution. KVM guests currently use x86-64. This example uses documentation addresses;
replace them with unused addresses on the chosen network. Do not put any token or private
key in this file. `identity` names a local SSH key file. `ssh_public_key` contains its
public half. The age recipient encrypts credentials.

Credential fields are rejected regardless of letter case. Git addresses also reject
embedded credentials, query strings and fragments. Enter secrets in the hidden prompts.

```json
{
  "providers": {
    "kvm": {"type": "kvm", "uri": "qemu:///session"}
  },
  "identity": "/path/to/ssh-key",
  "age_recipient": "age1replace-with-your-public-key",
  "storage_class": "local-path",
  "volume_path": "/var/lib/rancher/k3s/storage",
  "nodes": [
    {
      "name": "control", "role": "server", "on": "kvm",
      "vm": {
        "name": "control", "cpu": 4, "ram_mib": 24576, "disk_gib": 140,
        "storage": "images", "image": "/path/to/debian-cloud.qcow2",
        "network": "lab", "mac": "00:00:5e:00:53:01",
        "address": "192.0.2.11/24", "gateway": "192.0.2.1",
        "dns": ["192.0.2.1"], "user": "tester",
        "ssh_public_key": "ssh-ed25519 replace-with-public-key"
      }
    }
  ]
}
```

Add workers with the same fields and unique names, addresses and MACs. Three servers need
unique names and addresses too. Optional node fields are `labels` (`key=value`) and
`taints` (`key=value:NoSchedule`). `services` can add supported catalog services. For
remote libvirt, the provider also takes `target` with `kind: ssh`, `ssh: user@host`,
`identity`, `known_hosts` and optional `port`. Set provider `sudo: true` only if the
remote libvirt host requires it. These credentials give root access on that host.

A Proxmox provider takes `type: proxmox`, `url`, `node`, `pool` and optional `ca_file`.
Its VM fields replace `image`, `network` and `mac` with numeric `id`, `template` and
`bridge`. Optional fields include `vlan`, `root_disk` and `gpu_mapping`. KVM passthrough
uses `gpu_pci`, an array of four hexadecimal strings for domain, bus, slot and function.
An extension defines any additional provider fields.

Existing machines use a node `target` instead of `vm`. Imported k3s servers also need
`existing_cluster: true` and their existing join credential at the hidden prompt. Optional
`nas` names `server`, `export` and a dedicated `/mnt/<name>` mount folder. There is no
storage-creation field.

## Proxmox token permissions

Use a dedicated user and a privilege-separated token. Assign the same bounded ACLs to
both: effective token permissions are their intersection. Prepare a dedicated resource
pool and templates as an administrator. Never grant `PVEAdmin`, `Sys.Modify` or
unrestricted datastore configuration rights to the provisioner.

| ACL scope | Required privileges |
|---|---|
| Each chosen template, `/vms/<template-id>` | `VM.Audit`, `VM.Clone` |
| Dedicated `/pool/<pool>` | `VM.Allocate`, `VM.Audit`, `VM.Config.CPU`, `VM.Config.Memory`, `VM.Config.Disk`, `VM.Config.Network`, `VM.Config.Cloudinit`, `VM.Config.Options`, `VM.PowerMgmt`, `VM.Snapshot`, `VM.GuestAgent.Unrestricted` |
| Each chosen `/storage/<pool>` | `Datastore.Audit`, `Datastore.AllocateSpace` |
| Chosen `/nodes/<node>` | `Sys.Audit` for node and task status |
| Chosen bridge or VNet ACL path from the API explorer | `SDN.Use` |
| Optional `/mapping/pci/<mapping>` | `Mapping.Use`; also `VM.Config.HWType` on the dedicated VM pool |

Guest-agent `exec` requires `VM.GuestAgent.Unrestricted` in the current API. Read-only
guest-agent audit rights cannot execute `cat`. This powerful permission is confined to VMs
in the dedicated pool. The token does not need console proxy rights: console info returns
a link, and the user signs in separately. Verify names against the installed API explorer
when using an older Proxmox release. Enter the token in the hidden planning prompt. It is
encrypted with age before apply and is never a command-line argument.

## Storage

Planning reads Proxmox storage pools, including ZFS, LVM-thin, Ceph and NFS. Libvirt
reports its configured pools; allocation currently supports file-backed `dir`, `fs` and
`netfs` pools. Free space is compared with new disk allocations. Existing owned disks are
not counted as new allocations on repeat apply.

With a provider SSH target, inventory also reads `/proc/mdstat` and `zpool status`. It
reports degraded arrays, mirrors, stripes and RAIDZ. A pool type alone does not prove
redundancy. The plan warns when redundancy is absent or unknown. It does not infer a
physical RAID layout from a VM's virtual disk. Console storage rows identify cached
planning inventory. Apply refreshes it before approval.

`storage_class` chooses Kubernetes volume placement. `volume_path` chooses k3s's
local-path directory. Existing NFS exports can be selected with `nas`; generated Ansible
mounts them and a pinned NFS provisioner offers `lab-nfs` for other workloads. Its reclaim
policy retains data. Prometheus TSDB and Grafana SQLite remain on local or block storage.
No NAS share, RAID array or ZFS pool is created. The storage command refuses creation, so
there is no hidden destructive path. SMB mounting and raw block libvirt allocation remain
future work.

NFS source: the Kubernetes SIG's [chart and retention
settings](https://github.com/kubernetes-sigs/nfs-subdir-external-provisioner/blob/master/charts/nfs-subdir-external-provisioner/README.md).

## Cluster growth and removal

The cluster specification names one or three servers and any workers. Three servers use
k3s embedded etcd. Servers share the same critical networking and encryption flags. The
first starts etcd; later servers join it. Ansible reads the credential from its temporary
process environment and writes root-owned runtime configuration. It stays encrypted in
the repository and is also stored in Vault when selected. No join key appears in a golden plan or log.

This uses Ansible's built-in
[environment lookup](https://docs.ansible.com/ansible/latest/collections/ansible/builtin/env_lookup.html).
The value stays out of command arguments and controller files. Task and debug logging
are disabled for the cluster playbook.

GPU workers receive a label and a scheduling taint. They require a prepared NVIDIA driver
and container runtime; the role checks both before installation. Pinned NVIDIA
device-plugin and DCGM exporter charts supply GPU resources and metrics. GPU driver
installation and physical passthrough have not been verified by the CPU-only VM test.

`add-node` can prompt from an existing provider's template or accept a node specification.
Worker prompts leave GPU passthrough out of a copied template. A GPU mapping or PCI
address is shown in the plan when selected.
It regenerates the reviewable repository, waits for `yes`, creates the VM and verifies
cluster readiness. Existing hosts can join through SSH. An explicit `existing_cluster`
specification leaves its server configuration alone; an existing join credential must be
supplied and encrypted. The provisioner never silently adopts another k3s install.

Removal drains a worker without force or automatic deletion of temporary pod data.
Disruption-budget or local-data failures stop removal. It disables the worker service
before stopping its VM and deleting the Kubernetes node. Deleting its VM disk needs a
second answer naming the VM. Control-plane removal is refused pending an etcd backup and
quorum procedure.

Sources: k3s [HA embedded etcd](https://docs.k3s.io/datastore/ha-embedded),
[tokens](https://docs.k3s.io/cli/token),
[configuration](https://docs.k3s.io/installation/configuration), Kubernetes
[drain](https://kubernetes.io/docs/reference/kubectl/generated/kubectl_drain/) and NVIDIA
[DCGM
exporter](https://docs.nvidia.com/datacenter/dcgm/latest/installation/install-dcgm-exporter.html).

## Monitoring and proposals

Kubernetes uses pinned kube-prometheus-stack, including node_exporter, kube-state-metrics,
Grafana and Alertmanager. Loki uses a persistent single-binary chart. Alloy collects
system journals. A single box uses the corresponding containers, with loopback listeners
and a host node_exporter. Changing Core to Advanced stops only the old monitoring
containers and retains their volumes. Historical data is retained there; it is not copied
into Kubernetes volumes. Monitoring settings mount as directories so Ansible's atomic file
replacement is visible. Changed settings recreate containers while retaining disks.

Netdata supplies native Prometheus metrics. Services without metrics use blackbox HTTP
probes. With an explicitly selected Caddy local HTTPS name, probes measure reach and
expiry without checking its private authority. The generated dashboards cover nodes,
Kubernetes, GPU readings and apps. Rules cover node loss, disk space, failed service
probes, pod crashloops, certificate expiry and stale backups when backups are selected.
Certificate alerts allow fourteen days for public certificates and one hour for Caddy's
short-lived local certificates. Caddy documents their twelve-hour lifetime in its
[internal issuer settings](https://caddyserver.com/docs/caddyfile/directives/tls#internal).
Grafana's stable admin credential goes into sops and Vault when selected. The provisioned
adapter supplies Prometheus queries and Alertmanager alerts through the explicit SSH or
kubeconfig target. The console and ALERTS widget need no second setup.

Capacity proposals require at least fifteen minutes of fresh, continuous samples above 85
percent CPU or 90 percent memory. Pending pods must have insufficient-resource scheduling
reasons. Missing samples, short spikes and storage/affinity problems do not trigger
proposals. The console's capacity card and VECTOR's read-only `lab_capacity` tool show the
same suggestion. Neither has a VM creation path.

Sources:
[kube-prometheus-stack](https://github.com/prometheus-community/helm-charts/tree/main/charts/kube-prometheus-stack),
[Prometheus alert
rules](https://prometheus.io/docs/prometheus/latest/configuration/alerting_rules/),
[Alertmanager](https://prometheus.io/docs/alerting/latest/configuration/), [Grafana
provisioning](https://grafana.com/docs/grafana/latest/administration/provisioning/) and
[Loki single-binary
installation](https://grafana.com/docs/loki/latest/setup/install/helm/install-monolithic/).

On a new, owned k3s installation, the first server checks its four bootstrap
resource definitions before workers join. If accepted names stay unready for 30
seconds, it requests another readiness check through a metadata annotation. Kubernetes
still decides readiness; the installer never forces status or deletes a definition.
The check fails after three minutes. Ansible starts k3s once after writing its
configuration; the installer does not start it separately. The check also handles
a bootstrap interrupted before its
readiness update. The upstream [readiness queue](https://github.com/kubernetes/apiextensions-apiserver/blob/master/pkg/apiserver/customresource_handler.go)
and [k3s bootstrap wait](https://github.com/k3s-io/k3s/blob/main/pkg/server/context.go)
explain this dependency. Existing kubeconfig targets receive no bootstrap changes.

SSH health checks keep their service tunnel open only for the check. Closing its
input stops and waits for the remote `kubectl` process. Repeated checks cannot leave
idle forwarding processes consuming a node's memory. Grafana's service port is set
explicitly to 3000 so its health tunnel uses the same port as the generated values.

## Extensions and tests

A homelab extension imports `vmproviders.Provider` and registers its class with
`vmproviders.register("provider-name", ProviderClass)`. Existing plugin loading imports it
before provider selection. Implement ownership checks, safe retries, task completion,
storage inventory and guest key trust. Incus, Harvester and cloud providers can use this
interface. Override `validate_spec` for provider-specific fields. Set `credential_prompt`
when the provider needs a hidden, encrypted credential. Common VM sizes, SSH networking
and public-key fields remain required. They are not included yet.

`test_infrastructure.py` checks full KVM and Proxmox HA plan goldens, TLS fake API
requests, lifecycle retries, ownership, approval, storage health and proposals.
`test/vm/lab-infrastructure-e2e.py` creates an isolated Debian hypervisor through the
existing keeper. It tests single-box monitoring, creates two nested libvirt VMs, forms
k3s, adds a third node and checks Ready. Both monitoring paths must show targets up, load
a dashboard, and fire and resolve a real test alert. Cleanup removes the guests and test
keys. Proxmox is tested only against the fake API. No real lab or NAS is needed.

`lab-vm.py` verifies Debian's SHA-512 image checksum before boot. Repeated cached-image
tests can set `BROMIGOS_PROVISION_IMAGE_SHA512` to a digest previously verified against
Debian's manifest. Every image copy is still checked. Obtain that digest independently;
do not calculate a trusted value from an unverified download.

Test VMs share a hard RAM limit: `BROMIGOS_VM_MAX_MEM_GIB`, 8 GiB by default,
and never above 10 GiB. The keeper also limits running QEMU guests to four CPUs.
It checks `free -g` before each launch and refuses when less than 14 GiB is available.
The single-box test uses 8 GiB and two CPUs. The nested test uses a 4 GiB, one-CPU
parent and up to three 2 GiB, one-CPU guests: 10 GiB and four CPUs altogether.
The nested test explicitly uses a 10 GiB cap and reserves all future child RAM and
CPUs in the parent’s QEMU name, so another keeper counts the whole reservation.
A temporary swap file lives inside the parent's thin disk. All writable test disks
and keys are removed afterward. Check `pgrep -a qemu` after a run.
Both VM fixtures use a short, private temporary directory for Ansible's SSH
sockets. OpenSSH's [socket setup](https://github.com/openssh/openssh-portable/blob/master/mux.c)
adds a temporary suffix when creating a socket, so long sandbox
home paths can exceed the system's path limit.

These tests use a separate, visible small-service catalogue and short monitoring
retention. They keep Prometheus, Grafana, Loki, Alertmanager, the starter dashboards
and real alert checks. The shipped catalogue keeps its normal sizing estimates.
The small test profile is unsuitable for a busy lab or long-term logs.

When Core services stay on an SSH box and monitoring moves into Kubernetes, Alloy
collects Netdata metrics on the control-plane host. It sends them to Prometheus's
private service using [remote write](https://grafana.com/docs/alloy/latest/reference/components/prometheus/prometheus.remote_write/).
A pod's loopback address cannot reach the box's loopback services. The verifier
checks the forwarded Netdata scrape as well as Prometheus's own targets. Keep
exporter ports inside the lab network, including Alloy's port 12345.

Helm 4 upgrades use client-side updates when handing resources to Argo CD. This
avoids two server-side field managers competing on repeated apply. Helm 3 keeps
its existing update method. The wrapper follows the upstream [upgrade options](https://helm.sh/docs/helm/helm_upgrade/).
It captures Helm output in memory and reports only fixed failure categories.
It never prints chart notes, generated credentials or raw error text. Ownership
checks still run before any upgrade; unrelated releases are refused.

Kubeconfig inventory reads the cluster's storage classes. A single default is written
by name into the plan and volume values, matching the SSH plan's explicit class.
Without one clear default, the user must choose `--storage-class`. Switching connection
methods must not try to alter an existing volume's immutable storage setting.

Adding a worker runs node configuration only on the new node. Existing machines receive
read-only inventory checks, and their k3s settings are left alone. Monitoring is refreshed
after the new node is Ready. This keeps growth from reapplying control-plane settings.
