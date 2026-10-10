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
`/usr/share/bromigos/homelab/lab/profiles.toml`. The picker's logic is written and tested
against it (`bromigos_homelab/services.py`), but nothing provisions from it yet.

## The service catalog

Every service the picker can offer is an entry in the catalog, a `[service.<id>]` table in
`profiles.toml`. Today the catalog lists:

- **Core:** Caddy, Netdata, restic and Homepage.
- **AI:** Ollama, vLLM, LiteLLM, ComfyUI with model sets, the voice service, Whisper,
  Open WebUI and SearXNG.
- **Games:** Pelican's panel and Wings.
- **Media:** Jellyfin, Plex, the arr apps, and Pinchflat for YouTube.
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
| `image` | its container image, pinned to a version or a digest. `lab update` bumps it. |
| `chart` | its Helm chart on a Kubernetes target: `{ repo, name, version }` |
| `storage` | what it keeps on the NAS: `media`, `downloads` or `backups` ([Storage](#storage-use-the-nas-you-already-have)) |
| `mounts` | where each of its folders comes from (below) |
| `env` | environment variables for its container |
| `account` | an online account it signs in to during setup, such as `plex` |
| `source` | the `homelab.toml` source the Verify step writes, so the lab console reads it |
| `configure` | steps that set it up after it starts ([Configure steps](#configure-steps)) |

Some fields need a few more words:

- **`kind`.** `compose` is a container on a Linux box. `helm` runs on a Kubernetes target,
  and as a container elsewhere. `host` installs on the machine itself. `cluster` is
  Kubernetes.
- **`gpu`** in `needs` is `none`, `nvidia`, `amd` or `any`. With `gpu = "none"`,
  `vram_gib` means a GPU helps but isn't required.
- **Roles.** Ollama and vLLM both provide `llm-server`, so they conflict. Another service
  can depend on the role and accept either. A role doesn't have to be exclusive. Jellyfin
  and Plex both provide `media-library`, and they can run side by side. The arr apps and
  Pinchflat depend on `media-library`, so either server, or both, is enough for them.
- **`mounts`.** Each key is a folder inside the container. Its value says where the folder
  comes from: a storage purpose (`media`), a folder in one (`media:youtube`), or the box's
  own disk. `state` is the box's disk, for databases and settings. `scratch` is the box's
  disk for throwaway files, such as transcoding. Databases never go on a NAS share:
  SQLite, Plex and Jellyfin all want a local disk with file locking.
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
| Media | Jellyfin, the arr apps and Pinchflat. Plex is listed too, unticked. |
| Home | Home Assistant |
| Advanced | Prometheus, Grafana and Loki; Vault; Kubernetes with Argo CD |

Core is always offered and ticked. Its backups are on by default. You may untick them, and
the picker will warn you what that costs.

A preset's `services` are ticked when you pick it. Its `offered` services are listed with it
but left unticked. In Media, Jellyfin is the default media server: it's open source and
needs no account. Plex is offered beside it. Its hover hint says it needs a free Plex
account, and that you sign in once during setup.

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
3. **Choose storage.** Pick the NAS shares the lab keeps its media, downloads and backups
   on. See [Storage](#storage-use-the-nas-you-already-have).
4. **Plan.** It generates your own lab repository: an Ansible inventory and roles, and a
   Compose file per service, or Helm values on Kubernetes. The base role sets up Docker,
   the NVIDIA container toolkit or ROCm, and the firewall. Generated secrets go into
   sops and age encrypted files in the repository, or into Vault when there is one. It
   shows the plan, with services, ports, disk use and model download sizes, and waits for
   your yes.
5. **Apply.** It runs `ansible-playbook` from the desktop. The run is idempotent. It shows
   model downloads with progress, and sets up certificates with Caddy and backups with
   restic. It mounts the shares, then starts each service and runs its configure steps.
   A service with an `account`, such as Plex, asks you to sign in first.
6. **Verify.** It runs health checks. Then it writes `homelab.toml` and `targets.toml` so
   the desktop connects, and runs `bromigos lab doctor`. Each service's `source` becomes a
   `[[source]]` in `homelab.toml`.
7. **Keep it running.** Running provisioning again converges, and never wipes anything.
   `lab provision add` and `remove` change one service. `lab update` will bump image
   versions in the repository and apply them. Everything can be rebuilt from the
   repository.

## Configure steps

Installing a service isn't enough to make it useful. Jellyfin needs its libraries, and
Pinchflat needs to know where to put videos. So a service can list steps, as
`[[service.<id>.configure]]` tables. The provisioner applies them in order, after the
service starts. Running provisioning again applies them again, and each step leaves alone
what's already right.

| `do` | What it does |
|---|---|
| `folder` | makes a folder, such as `{media}/youtube` |
| `first-run` | finishes the app's first-run wizard, with an admin user and a generated password |
| `secret` | gets a key or token from the app and keeps it, encrypted, under `name` |
| `sign-in` | signs in to an online account with `bromigos_account`, such as Plex's code at plex.tv/link. With `before_start`, it runs before the service starts. |
| `library` | adds a library to a media server: `name`, `type` (`movies`, `shows` or `music`) and `path` |
| `setting` | sets one of the app's own settings, such as a Pinchflat media profile, from `values` |
| `timer` | runs a command on a schedule (`every`): a systemd timer on a Linux box, a CronJob on Kubernetes |

A step with `on = "<role>"` runs on every ticked service with that role, instead of on its
own service. Pinchflat's YouTube library uses `on = "media-library"`. So it's made in
Jellyfin, in Plex, or in both, whichever you ticked.

Values can hold placeholders:

| Placeholder | Becomes |
|---|---|
| `{tz}` | the box's time zone |
| `{media}`, `{downloads}`, `{backups}` | where that purpose's share is mounted on the box |
| `{url:<service>}` | a service's address on the box, such as `{url:jellyfin}` |
| `{secret:<name>}` | a secret a step kept, or one generated for the lab |

An environment variable that names a service you didn't tick is left out. Pinchflat's own
`{{ … }}` templates aren't placeholders, and are passed on as they are.

### Pinchflat, as an example

Pinchflat downloads YouTube channels and playlists, so they play in Jellyfin or Plex and on
the den TV. (The den is the default theme's wallpaper, a room with live screens.) Its
entry sets it up like this:

1. It runs `ghcr.io/kieraneglin/pinchflat`, pinned by digest. Its settings and database
   stay on the box. Its downloads folder is `{media}/youtube` on the NAS.
2. It sets `ENABLE_PROMETHEUS=true`, so the lab console can show its download queue.
3. It makes the `youtube` folder, and a **YouTube** library pointing at it in each media
   server you ticked.
4. It adds two Pinchflat media profiles. Pinchflat has no API for this, so the provisioner
   fills in its form, as you would:
   - **Channel:** a season per year, with episodes by upload date:
     `Season 2026/s2026e1006… - title [id].mp4`.
   - **Playlist:** everything in Season 1, numbered by place in the playlist:
     `Season 1/s01e003 - title [id].mp4`.

   Both put the YouTube ID in the file name, which is how the sync finds each video.
5. It keeps Pinchflat's route token, which lists its sources for the console and the sync.
6. It installs a timer that runs `bromigos lab youtube sync` every hour. The sync turns
   each downloaded playlist into an ordered playlist in Jellyfin and Plex. It's a single
   Python file, so it runs on the lab with nothing else installed. It reads its addresses
   and keys from the environment.

## Storage: use the NAS you already have

Most people who want a lab already have a NAS full of films and shows. So the lab keeps its
big files there, not on the box's own disk. The Storage step comes after the inventory and
before the plan.

### What the step does

1. **It finds your NAS.** It looks on the network for NFS and SMB servers. You can also
   type an address, such as `nas.lab.example`. It lists each NAS's shares.
2. **You pick a share for each purpose:**

   | Purpose | What it holds | Folders it makes |
   |---|---|---|
   | Media | films, shows, music and YouTube downloads | `movies`, `tv`, `music`, `youtube` |
   | Downloads | downloads before the arr apps sort them | `downloads` |
   | Backups | restic's encrypted backups | `restic` |

   One share can hold more than one purpose. Downloads on the same share as media is best,
   because moving a finished download is then instant. The picker only asks for the
   purposes your ticked services need, from their `storage` field.
3. **It explains what each share needs:**
   - NFS is the better choice for media on Linux. SMB works too.
   - Every service must be able to read and write every file. The simplest way is to have
     the NAS treat everyone who connects as one user. On NFS that's called *squash*, or
     *all squash*. The alternative is to give the services the user and group IDs that
     own the files.
4. **It checks each share.** It writes a test file, reads it back and deletes it. If that
   fails, it says which setting to change on your brand of NAS, such as "Shared Folder ›
   Edit › NFS Permissions: set Squash to Map all users to admin" on a Synology.

### How a share is attached

| Target | How |
|---|---|
| A Linux box | Ansible writes systemd automount units, for NFS or CIFS. An SMB password goes in a sops-encrypted file in your lab repository. |
| Kubernetes | an NFS StorageClass from nfs-subdir-external-provisioner, or fixed PersistentVolumes |
| Proxmox | the share is added as Proxmox storage (`pvesm add nfs`), or mounted inside the VM |

Then each service gets its folders: Jellyfin and Plex get `media`, the arr apps get
`media` and `downloads`, Pinchflat gets `media:youtube`, and restic gets `backups:restic`.

### Your NAS's brand

Any NFS or SMB share works. For some brands, setup can also make the share for you,
through the NAS's own API. For the rest, it shows the steps and uses a share you made. The
`[storage.brand.*]` tables in `profiles.toml` hold each brand's steps and setting names.

| Brand | Setup | What to set |
|---|---|---|
| TrueNAS 25.04 or later | creates shares, through its API (with an API key you make) | Mapall User and Mapall Group on the NFS share |
| Synology (DSM 7) | use an existing share: Synology publishes no API for this | NFS Permissions › Squash: Map all users to admin |
| UniFi Drive (UNAS) | use an existing share: UniFi documents no API for UniFi Drive | turn on NFS in Settings › Services, and use Collaborative Mode (All Squash) |
| QNAP | use an existing share | NFS host access: Read/Write, Squash all users |
| Unraid 7 | use an existing share: its API can't make shares yet | NFS Export Yes, and a Private rule for the box |
| a Linux NFS server | use an existing share | `rw,all_squash,anonuid=…,anongid=…` in `/etc/exports` |
| anything else | use an existing share | map all users to one user |

On UniFi Drive, don't choose Isolated Mode for the drive. It can't be undone, and the drive
then works over NFS only. Its NFS path is `/var/nfs/shared/<Shared Drive name>`.

### Seeing it in the console

The lab console's Storage card lists each share the lab uses, with the NAS it's on and its
free space ([lab.md](lab.md#status)). UniFi Drive has no documented API for its health, so
bromigOS has no adapter for it. Its shares still show, from the box's mounts.

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

- The service catalog, presets, storage purposes, NAS brands and sizing rules, as data in
  `profiles.toml`.
- The picker's logic, `bromigos_homelab/services.py`: it checks the catalog and resolves a
  selection's dependencies, with the reasons in words. The catalog's tests use it.
- The Plex sign-in, in `bromigos_account` (`bromigos account login plex`), and the claim
  token a new Plex server needs.
- `bromigos lab youtube sync`, the playlist sync the Pinchflat timer will run.
- `bromigos lab provision`, which says it's planned for Phase 3.
- The lab console that provisioning will end in ([lab.md](lab.md)).
- The model catalog that will choose each service's models ([lab-models.md](lab-models.md)).
