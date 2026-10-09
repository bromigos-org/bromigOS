# Setting up a new lab: bromigos lab provision

> **Planned.** This is Phase 3 of the lab console. It's designed but not built. Today,
> `bromigos lab provision` only says it's planned. The design was approved on 2026-10-09
> and is recorded here so the work builds against it.

The lab console ([lab.md](lab.md)) reads a homelab someone already runs. Provisioning is
for someone who doesn't have one yet. It will turn a spare machine into a lab the desktop
connects to. That machine can be a GPU box or any Linux box, a Proxmox host, or an
existing Kubernetes cluster. The lab will be set up from a Git repository, so it can be
rebuilt the same way at any time.

The list of services it picks from is already data:
`homelab/share/lab/profiles.toml`, installed as
`/usr/share/bromigos/homelab/lab/profiles.toml`. Nothing reads it yet.

## The service catalog

Every service the picker can offer is an entry in the catalog, a `[service.<id>]` table in
`profiles.toml`. Today the catalog lists:

- **Core:** Caddy, Netdata, restic and Homepage.
- **AI:** Ollama, vLLM, LiteLLM, ComfyUI with model sets, the voice service, Whisper,
  Open WebUI and SearXNG.
- **Games:** Pelican's panel and Wings.
- **Media:** Jellyfin and the arr apps.
- **Home:** Home Assistant.
- **Advanced:** Prometheus, Grafana, Loki, Vault, and Kubernetes with Argo CD.
- **Network:** a Cloudflare tunnel.

Each entry has these fields:

| Field | What it holds |
|---|---|
| `title`, `summary` | its name and one line, for the picker's row and hover hint |
| `group` | where it's listed: core, ai, games, media, home, advanced or network |
| `kind` | how it runs: `compose`, `helm`, `host` or `cluster` |
| `needs` | the least it runs with: `cpu`, `ram_gib`, `disk_gib`, `vram_gib` and `gpu` |
| `ports` | the ports it listens on |
| `provides` | the roles it fills, such as `llm-server` |
| `depends` | the roles or services it needs |
| `conflicts` | services that can't share its role |
| `default` | `true` when it's ticked for everyone |
| `untick_warning` | what you lose by unticking a default service |
| `models` | where its models come from: `{ from = "catalog", capabilities = [...] }` |
| `exposes` | the subdomain of its web UI, behind the reverse proxy |
| `gpu_driver` | `true` when it needs the NVIDIA container toolkit, or ROCm |

Some fields need a few more words:

- **`kind`.** `compose` is a container on a Linux box. `helm` runs on a Kubernetes target,
  and as a container elsewhere. `host` installs on the machine itself. `cluster` is
  Kubernetes.
- **`gpu`** in `needs` is `none`, `nvidia`, `amd` or `any`. With `gpu = "none"`,
  `vram_gib` means a GPU helps but isn't required.
- **Roles.** Ollama and vLLM both provide `llm-server`, so they conflict. Another service
  can depend on the role and accept either.
- **Models.** `profiles.toml` lists no models of its own. A service's model set comes from
  the model catalog ([lab-models.md](lab-models.md)), sized for the machine's VRAM.

## Presets

A *preset* is a named selection from the catalog, a `[preset.<id>]` table. Picking a
preset ticks its services. You can then add or remove any service. Presets and the Custom
picker are the same screen.

| Preset | Services |
|---|---|
| Core | Caddy for automatic HTTPS, Netdata, restic backups to a NAS or a cloud bucket, Homepage |
| AI | Ollama or vLLM, LiteLLM in front, ComfyUI, the voice service, Whisper, Open WebUI, SearXNG |
| Game server | Pelican's panel and Wings, with Minecraft Paper as the default template |
| Media | Jellyfin and the arr apps |
| Home | Home Assistant |
| Advanced | Prometheus, Grafana and Loki; Vault; Kubernetes with Argo CD |

Core is always offered and ticked. Its backups are on by default. You may untick them, and
the picker will warn you what that costs.

In the AI preset, vLLM replaces Ollama on an NVIDIA GPU with 24 GB or more. The voice
service runs Qwen3-TTS on a GPU, or Kokoro on the CPU.

## The picker

The picker will:

- resolve dependencies by itself, and say so in words. For example: "Open WebUI needs an
  LLM server: Ollama is ticked too."
- refuse two services in one exclusive role, and offer the other instead;
- warn when the selection won't fit the hardware. It compares the inventory's numbers with
  each service's `needs`, plus the headroom in `[sizing]`.

It will be the same picker everywhere:

- `bromigos lab provision --custom` will show an interactive checklist in a terminal. In
  the dashboard, it will be a tree grouped by `group`, with presets as one-key selections.
- `bromigos lab provision add <service>` and `remove <service>` will change one service at
  a time.
- Settings › Lab will show the same tree, with the plan beside it.

Extensions will be able to add catalog entries with the same fields, such as a community
TrueNAS or UPS service. A `homelab-adapter` extension's `lab/catalog/*.toml` will be read
after bromigOS's. The first entry of a name wins, so an extension adds services and never
replaces one.

## How it will provision

1. **Reach the machine.** The desktop connects over SSH with keys. `lab provision` will
   help set them up with `ssh-copy-id`, and it needs sudo on the target. Supported targets:
   - a Linux box running Debian, Ubuntu, Fedora or Arch Linux;
   - a Proxmox host, where it creates a VM or a container through the API, then
     provisions inside it;
   - an existing Kubernetes cluster, through Helm, or Argo CD when the cluster has it.
2. **Take an inventory.** A read-only probe, using Ansible facts and GPU detection, finds
   the CPU, RAM, GPUs and VRAM, disks and distribution. The inventory sizes the selection
   (below).
3. **Plan.** It generates your own lab repository: an Ansible inventory and roles, and a
   Compose file per service, or Helm values on Kubernetes. The base role sets up Docker,
   the NVIDIA container toolkit or ROCm, and the firewall. Generated secrets go into
   sops and age encrypted files in the repository, or into Vault when there is one. It
   shows the plan, with services, ports, disk use and model download sizes, and waits for
   your yes.
4. **Apply.** It runs `ansible-playbook` from the desktop. The run is idempotent. It shows
   model downloads with progress, and sets up certificates with Caddy and backups with
   restic.
5. **Verify.** It runs health checks. Then it writes `homelab.toml` and `targets.toml` so
   the desktop connects, and runs `bromigos lab doctor`.
6. **Keep it running.** Running provisioning again converges, and never wipes anything.
   `lab provision add` and `remove` change one service. `lab update` will bump image
   versions in the repository and apply them. Everything can be rebuilt from the
   repository.

### Sizing

The `[sizing]` table in `profiles.toml` holds the rules the inventory applies:

| Key | Value | Meaning |
|---|---|---|
| `vram_tiers` | cpu, 8, 12, 16, 24, 32, 48, 80 | the VRAM tiers model sets are picked for |
| `ram_headroom_gib` | 4 | RAM kept free for the OS, the page cache and builds |
| `disk_headroom_pct` | 15 | disk kept free |
| `vram_job_headroom_gib` | 2 | VRAM kept free beyond resident models, for jobs and the voice service |
| `vllm_min_vram_gib` | 24 | the least VRAM on an NVIDIA GPU for vLLM; Ollama otherwise |
| `voice_gpu_min_vram_gib` | 8 | the least free VRAM for Qwen3-TTS on the GPU; Kokoro on the CPU otherwise |
| `gpu_driver_distros` | debian, ubuntu, fedora, arch | where GPU drivers may be installed |

Model sets come from the model catalog's `pick()`, by VRAM tier. When a preset is too big
for the machine, the plan says so.

## Safety defaults

- Only the reverse proxy is exposed. Every other port stays on the machine.
- Nothing goes public unless you opt in, with the Cloudflare tunnel entry.
- No password is stored in plain text. Generated secrets are encrypted in the repository,
  or kept in Vault.
- GPU drivers install only on the supported distributions, and always as a dry run first.

## Out of scope

bromigOS won't install an operating system on bare metal. You bring a Linux install or a
Proxmox host. A ready-made server image for a lab is a possible later idea.

## What exists today

- The service catalog, presets and sizing rules, as data in `profiles.toml`.
- `bromigos lab provision`, which says it's planned for Phase 3.
- The lab console that provisioning will end in ([lab.md](lab.md)).
- The model catalog that will choose each service's models ([lab-models.md](lab-models.md)).
