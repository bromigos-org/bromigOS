# Your homelab on the desktop (bromigos-homelab)

`bromigos-homelab` connects the servers you run at home to the bromigOS desktop. It works
with whatever your homelab runs, because the desktop asks for kinds of readings, not for
particular products. This page is for someone connecting an unusual setup, writing an
adapter, or adding to the lab console. For using it, read the manual's
[Your homelab](../manual/src/homelab.md).

Once a homelab is connected, it shows up in many places:

- the LAB panel, and panels you declare in a config file;
- the homelab decks (Lab, Ops, Netmap and Mind), which are full-screen holographic views;
- the rack hologram in VECTOR's gallery (VECTOR is the desktop's AI assistant);
- the worlds' weather and creatures, which react to your homelab's health and load;
- VECTOR's answers, when you ask him about your homelab.

Nothing is on until you connect a source. When nothing provides a reading, whatever needs
it stays hidden. When a source is down, it reads *unreachable* and nothing crashes.

The lab console, `bromigos lab`, has its own page: [lab.md](lab.md). Setting up a new
homelab from scratch is planned: [lab-provision.md](lab-provision.md).

## Words on this page

| Word | Meaning |
|---|---|
| capability | a kind of reading the desktop asks for, such as `metrics`, `hosts` or `models` |
| adapter | the code that knows one kind of service, such as Prometheus, and provides capabilities from it |
| source | one of your services, listed in `homelab.toml` and read by one adapter |
| snapshot | the whole homelab in one document, for the views that draw all of it |
| the lab | your homelab, as the lab console and its decks call it |

The [glossary](../manual/src/glossary.md) defines the rest of bromigOS's terms.

## Connect a homelab

```bash
sudo pacman -S bromigos-homelab
bromigos setup homelab
bromigos homelab status
bromigos homelab check
bromigos restart
```

1. `bromigos-homelab` comes with the `bromigos` package, so it's usually installed already.
2. `bromigos setup homelab` asks for host names or URLs, probes them and writes the file.
3. `bromigos homelab status` lists each source and the capabilities it provides.
4. `bromigos homelab check` asks every capability now and lists anything unreachable.
5. `bromigos restart` makes the panels, the live layer and VECTOR read the new file.

### What setup looks for

On this machine, `bromigos setup homelab` looks for the Docker socket, the herdr command
and a signed-in `gh`. On each host you name, it tries every adapter's well-known ports,
over HTTP and HTTPS. A port only counts when the service's own API answers. An open
socket isn't enough.

It writes `~/.config/bromigos/homelab.toml`. Running it again only adds sources it hasn't
seen before. It never rewrites your edits.

| Option | What it does |
|---|---|
| `--hosts nas,gpu-box` | Probe these hosts' well-known ports. |
| `--url https://prometheus.example.org` | Identify one exact URL. Repeat it for more. |
| `--kube-context homelab` | Use this kubectl context for your cluster. |
| `--kubeconfig ~/.kube/viewer.yaml` | Use this kubeconfig, preferably a read-only one. |
| `--yes` | Write without asking, for scripts and the VM test. |
| `--print` | Show the sources it would add, and write nothing. |
| `--json` | Print the findings as JSON. |
| `--no-local` | Skip this machine's Docker, herdr and `gh`. |
| `--no-detect` | Don't detect services from the metrics and the cluster. |
| `--ingress` | Also probe the cluster's ingress hosts. This writes their names into the file. |

Setup never picks kubectl's *current* context by itself. On many machines that's someone's
production cluster. Name yours with `--kube-context` or `--kubeconfig`, or pick it from
the list when setup asks.

### Services found through metrics and the cluster

With a metrics source or a Kubernetes source, setup also detects what runs there. It reads
the metric names and the pods. Each adapter's `detect()` decides what it recognises, for
example:

- NVIDIA's DCGM exporter, vLLM, Traefik, cert-manager, Loki and Alloy;
- UniFi Poller, the arr exporters and Pelican's exporter;
- a dynamic-DNS CronJob, a NAS exporter or an NFS provisioner;
- GitHub's runner scale sets, and backup jobs.

These sources need no address, because they read through the metrics and the cluster.

`--ingress` goes further. It probes the cluster's ingress hosts with the adapters their
names suggest, so `sonarr.example.org` is tried as an arr app and `s3.example.org` as S3
storage. Because it writes those host names into the file, look with `--print` first.

## homelab.toml

`~/.config/bromigos/homelab.toml` is your file. bromigOS merges it over the packaged
`/usr/share/bromigos/default/homelab.toml`, which documents every key and has no sources.
More panels can go in `~/.config/bromigos/homelab/panels/*.toml`. Everything re-reads
these files when they change.

### A source

```toml
[[source]]
name = "prometheus"                 # unique; defaults to the type
type = "prometheus"                 # the adapter
endpoint = "http://prometheus.example.org:9090"
auth_ref = "@file:~/.local/share/bromigos/prom-token"   # optional; a reference, never the secret
tls_ca = "~/certs/homelab-ca.crt"   # optional; [tls] ca_file sets one for every source
provides = ["metrics", "alerts"]    # optional; narrows what this source answers for
enabled = true                      # optional
```

Any other key is the adapter's own option, such as `kubeconfig`, `context`, `orgs` or
`namespace`. The adapter tables below list them.

### References

Any string in the file can be a *reference* instead of a value. With references, a
`homelab.toml` can sit in a public dotfiles repository with nothing private in it.

| Reference | Resolves to |
|---|---|
| `@private:endpoints.prometheus` | a dotted key in the private overlay, the sops and age encrypted file `bromigos private` manages |
| `@env:NAME` | an environment variable |
| `@file:~/path` | a file's content, stripped, such as a token file with mode 0600 |
| `@vault:kv/path#field` | a field in Vault, read with the `vault` command and its login, cached for 10 minutes |

A reference that doesn't resolve is empty, and its source stays off.

Secrets only ever go in `auth_ref`, and in `write_auth_ref` for Gnosis. They're always
references, never the secret itself.

### The other settings

| Setting | What it sets |
|---|---|
| `name` | the lab's name, shown on the relay map, the timeline's backfill note and the radial menu. Put it at the top, before any table. Default `LAB`. |
| `[tls] ca_file` | a CA bundle for every source. A source's `tls_ca` wins. |
| `[models] rpm_full`, `tps_full` | the model load that reads as full rain in the worlds. Defaults 30 requests a minute and 40 output tokens a second. |
| `[services] domain`, `include`, `exclude` | the drift map's relays, and the links in your notes |
| `[relays] hosts` | more hosts for the relay map to ping |
| `[netmap]` | the Netmap deck's devices: `gateway`, `switch`, `ap`, `roles`, `aliases`, `show_prefixes`, `show_hosts` |
| `[constellation]` | how the holo deck lays out the lab's nodes (below) |
| `[console]` | the lab console's settings ([The lab console](#the-lab-console-cards-doctor-checks-and-job-kinds)) |
| `[lab] voice_reserve_mib` | VRAM the job queue keeps free for the voice service. Default 1024. |

A reference keeps the lab's name out of a public file too:
`name = "@private:homelab.name"`.

### Laying out the constellation

The holo deck draws your lab's nodes as a constellation. The nodes themselves always come
from the snapshot. `[constellation]` only changes the layout, and every key is optional:

- `hub` is the node in the middle, linked to the others. By default it's the first node.
- `ai` is a pair of nodes whose link carries the models' requests per minute. Without it,
  there's no such link.
- `positions` pins nodes to points on the unit sphere, in drawing order. It's a list of
  `{node = "…", at = [x, y, z]}` tables. Without it, the other nodes ring the hub.

Node names are host names. In a public file, give them as references to the private
overlay:

```toml
[constellation]
hub = "@private:homelab.constellation.hub"
ai = "@private:homelab.constellation.ai"
positions = "@private:homelab.constellation.positions"
```

In the overlay, write `positions` as the same list:
`[{"node": "gpu-box", "at": [0.78, 0.12, -0.36]}, …]`. Don't use a table keyed by node
name. sops encrypts values but leaves a table's keys in clear text, so keyed positions
would publish every host name. In a file that isn't public, either form works:
`positions = { gpu-box = [0.78, 0.12, -0.36] }`.

<!-- site:capabilities -->
## Capabilities

A *capability* is a kind of reading, such as `hosts` or `alerts`. The panels, decks and
VECTOR ask for capabilities. Adapters provide them.

Every call returns a **Result**, a dict with four keys:

- `ok`: at least one provider answered.
- `items`: the records from every provider, combined.
- `errors`: `{source: "unreachable: …"}` for each provider that didn't answer.
- `sources`: the providers that were asked.

With no provider, everything is empty and whatever asked hides itself. Every record has a
`source` field. Any other field may be `None` when a source doesn't know it.

| Capability | Record fields |
|---|---|
| `metrics` | `query(q)` gives `{labels, value, t}`. `query_range(q, minutes, step)` gives `{labels, points}`. The query is in the source's language, such as PromQL. |
| `hosts` | `name, up, cpu_pct, mem_pct, disk_pct, load1, cores` |
| `workloads` | `name, namespace, kind, state, restarts, node, image`. `kind` is pod, container or vm. |
| `deployments` | `name, namespace, sync, health, revision`, plus `message`: why an app is out of sync or degraded |
| `models` | `name, model, up, requests_per_min, tokens_per_s`. vLLM adds `running`, `waiting` and `kv_cache_pct`. |
| `agents` | `key, name, status, cwd`. `status` is working, needs_you, finished or error. |
| `secrets` | `name, reachable, initialized, sealed, standby, version`. Status only: nothing reads a secret. |
| `ci` | `repo, kind, number, title, status, conclusion, url, updated`. `kind` is pr or run. |
| `alerts` | `name, severity, state, summary, since, labels`. `state` is firing or pending. |
| `voice` | `name, endpoint, up, tts, stt, sample_rate, tts_model, stt_model`: a speech service VECTOR talks through |
| `media` | `name, endpoint, up, running, pending, vram_free, vram_total, gpu, version, models` |
| `gpus` | `name, host, model, uuid, vram_used, vram_total, util_pct, temp_c, power_w, power_limit_w, driver, holds` |
| `logs` | `name, errors, window_min, link`, and `logs_query(app, since_min, limit, contains)` for log lines |
| `routes` | `name, host, entrypoints, service, up, status, tls, rps, error_pct` |
| `certs` | `name, namespace, dns_names, not_after, days_left, ready, issuer` |
| `ddns` | `name, type, public_ip, dns_ip, match, proxied, updated` |
| `network` | `name, kind, model, up, clients, rx_bps, tx_bps, uptime_s, version` |
| `storage` | `name, kind, used, total, used_pct, objects, healthy` |
| `apps` | `name, kind, up, version, detail, endpoint, vram_used, link`. `up` is `None` when the app isn't deployed. |
| `games` | `name, game, status, players, players_max, uptime_s, cpu_pct, mem_bytes` |
| `library` | `name, kind, up, version, queue, queue_errors, missing, disk_free, disk_total, issues` |
| `runners` | `name, org, online, runners, busy, queued, min, max` |
| `packages` | `name, repo, latest, built, age_h, packages` |
| `backups` | `name, kind, last_success, age_h, schedule, ok, max_age_hours, offsite` |
| `ocr` | `name, endpoint, up, model, via`: where the `ocr` job kind sends pages |

Sizes such as `vram_used`, `used` and `total` are in bytes. On unified memory,
`vram_total` is `None`. `holds` lists what uses a GPU, as `"namespace/app"`.

Where an adapter judges a record's health, it adds `state`: `ok`, `warn` or `crit`. The
lab console's cards read it.

Two more capabilities serve the richer views:

- `snapshot` is the whole lab in one dict. A `lab` source provides it, or bromigOS builds
  it from the capabilities above. `bromigos homelab snapshot` prints it.
- `knowledge` is a Gnosis memory service.

### Read capabilities from Python

The live layer, the panels and VECTOR all use the same module:

```python
import bromigos_homelab as H

H.models()                                           # a Result
H.workloads(namespace="ai", name="vllm.*", state="running")
H.metrics('avg(DCGM_FI_DEV_GPU_UTIL)')
H.snapshot(); H.models_level(); H.status()
```

### Add a capability

A new capability takes three small changes in `homelab/lib/bromigos_homelab/`:

1. Add its name to `registry.CAPABILITIES`.
2. Add its record to `caps.SCHEMAS`.
3. Add an accessor in `caps.py`, like `H.gpus()` or `H.logs()`.

The lab console gives a new capability a card by itself.

<!-- site:adapters -->
## Adapters

An *adapter* knows one kind of service. To list every adapter, yours included:

```bash
bromigos homelab adapters
```

### General adapters

| Type | Provides | Endpoint and options |
|---|---|---|
| `prometheus` | metrics, hosts, alerts | `http://host:9090`. Hosts come from node-exporter. |
| `victoriametrics` | metrics, hosts, alerts | `http://host:8428` |
| `alertmanager` | alerts | `http://host:9093` |
| `kubernetes` | workloads (pods), hosts (nodes) | `kubeconfig = "…"`, preferably read-only, or `context = "…"` |
| `docker` | workloads (containers), hosts | `unix:///var/run/docker.sock` by default, or `http://host:2375` |
| `argocd` | deployments | its API (`endpoint` and `auth_ref`), else its metrics, else Application objects through a Kubernetes source |
| `flux` | deployments | Kustomizations and HelmReleases, through a Kubernetes source |
| `litellm` | models | `http://host:4000`. Load comes from its Prometheus metrics. `auth_ref` is only for `/v1/models`. |
| `ollama` | models | `http://host:11434`. Loaded models read as up. |
| `openai` | models | anything with `/v1/models`, such as vLLM, a llama.cpp server or LM Studio |
| `vault` | secrets | `https://host:8200`. It reads `sys/health` only. |
| `herdr` | agents | the herdr command on this machine |
| `github` | ci | your `gh` login. `orgs = [...]` for open pull requests, `repos = [...]` for the latest runs. |
| `lab` | snapshot, hosts | a Lab API serving the snapshot at `GET /api/status`, with a bearer `auth_ref` |
| `gnosis` | knowledge | a Gnosis gate. Options: `auth_ref`, `write_auth_ref`, `tenant`, `spaces`, `labels`, `orgs`, `roots`, `search_spaces`. |
| `bromigos-voice` | voice | a bromigOS voice server, such as `https://tts.example.org` |
| `comfyui` | media | `http://host:8188`. `bromigos art` uses the same server. |
| `proxmox` | hosts (nodes), workloads (VMs and containers) | `https://host:8006` with a read-only API token |
| `netdata` | metrics, hosts | `http://host:19999`. Its queries are charts, such as `system.cpu`, not PromQL. |

A few of these need more words:

- **bromigos-voice** streams Qwen3-TTS voices and runs Whisper. An endpoint that ends in
  the older `/v1/audio/speech` is trimmed to its base.
- **comfyui** reads the queue, VRAM and models from `/system_stats`, `/queue` and
  `/models`.
- **proxmox** needs `auth_ref` to resolve to `user@realm!tokenid=secret`, for a token
  with a read-only role such as PVEAuditor. It's sent as `PVEAPIToken=`. Its certificate
  is usually self-signed, so set `tls_ca`, or `tls_verify = false`.
- **netdata** takes `chart` or `chart.dimension` as a metrics query, such as
  `system.ram.used`.

### Adapters for the lab's own services

These adapters read the services a homelab runs for itself: GPUs, logs, routes,
certificates, storage, backups and more. Each one tries these ways in order and uses the
first that answers:

1. **The service's own endpoint**, over HTTP (`endpoint = "…"`). A service inside the
   cluster with no ingress works too (`service = "namespace/name:port"`). It's reached
   through the Kubernetes source's API proxy, when that kubeconfig may proxy to services.
2. **The lab's metrics**, through a Prometheus or VictoriaMetrics source, by the metric
   names the service's exporter uses.
3. **The Kubernetes source**: objects, pods and their logs.

Nothing here writes. Every call is a GET, a list or a log read. A source that can't be
read the way it's configured reads *unreachable* and says why. Nothing else is affected.

| Type | Reads | Provides |
|---|---|---|
| `dcgm` | NVIDIA's DCGM exporter (`DCGM_FI_*`), and the pods that ask a node for a GPU | gpus |
| `loki` | Loki's API: error lines per app, `/ready`, its build | logs, apps |
| `alloy` | its `/-/ready`, else its pods | apps |
| `dozzle` | its `/healthcheck` | apps, with a link to read logs in |
| `traefik` | its API's routers and services, else IngressRoutes; rates and 5xx from its metrics | routes |
| `cert-manager` | its metrics, else Certificates, else the certificates Traefik serves | certs |
| `ddns` | the dynamic-DNS CronJob and its last runs' logs | ddns |
| `unifi` | UniFi Poller's metrics (`unpoller_*`), or its own `/metrics` | network |
| `s3` | `/health` (RustFS) or `/minio/health/live` (MinIO); buckets from metrics or a read-only key | storage, apps |
| `nas` | a NAS exporter's metrics, kubelet's volume stats, the NFS provisioner's pods | storage |
| `redis`, `dragonfly` | `PING` and `INFO`, else its pods | apps |
| `neo4j` | its discovery document at `/` | apps |
| `open-webui`, `searxng` | their health and version endpoints | apps |
| `workload` | any app by its pods, and the GPU memory DCGM puts on its namespace | apps |
| `vllm` | vLLM's own `/metrics` and `/v1/models`, or its `vllm:*` series | models |
| `ocr` | an OpenAI-compatible OCR server, or a model on the lab's LLM gateway | ocr, apps |
| `pelican` | a Pelican exporter's metrics, else the panel's client API | games |
| `arr` | scraparr's or exportarr's metrics, or one app's API | library |
| `jellyfin`, `plex` | their health and identity endpoints | library |
| `arc` | GitHub's Actions Runner Controller: its listener and runner pods, or its `gha_*` metrics | runners |
| `pacman-repo` | a pacman repository's databases per channel, and the publishing workflow's runs | packages |
| `backups` | backup CronJobs, NAS share snapshots, Velero's last successful backup | backups |
| `pbs` | Proxmox Backup Server's API: each backup group's newest snapshot | backups |

Their options:

| Type | Options |
|---|---|
| `dcgm` | `endpoint` for the exporter's own `/metrics`; `warn_temp` (83 °C), `crit_temp` (90 °C) |
| `loki` | `endpoint` or `service`; `doctor_errors` (100 lines), `window_min` (15) |
| `cert-manager` | `warn_days` (21), `fail_days` (7) |
| `ddns` | `namespace`, `cronjob` (default: one named `*ddns*`), `ip_url`, `resolver` |
| `s3` | `access_key`, and `auth_ref` for its secret. Listing buckets needs python-boto3. |
| `nas` | `volume_classes`: the NFS-provisioned storage classes |
| `redis`, `dragonfly` | `endpoint = "redis://host:6379"`, `auth_ref` for AUTH |
| `workload` | `namespace` or `selector`; `kind`; `endpoint` and `health_path` |
| `vllm` | `queue_warn` (8) |
| `ocr` | `endpoint`, or `via = "llm"` with `model`, which uses the homelab `llm` in targets.toml and its key |
| `pelican` | `endpoint`, `auth_ref` (a client key); `expect_running` |
| `arr` | `endpoint`, `auth_ref` (the app's key, sent as `X-Api-Key`); `free_warn_gib` (50) |
| `pacman-repo` | `channels` (default edge, rc and stable), `endpoint`, `github_repo`, `workflow`; `stale_hours` (24) |
| `backups` | `match`, `exclude`, `local_classes`, `offsite`, `ignore` |
| `pbs` | `endpoint`, `auth_ref` (a token, sent as `PBSAPIToken=`) |

Numbers in brackets are the defaults.

A namespace with no pods reads *not deployed* on the `workload` adapter, not *down*.
Pelican's start, stop and restart aren't built yet.

#### What a kubeconfig needs

These adapters only read. Their kubeconfig needs `get` and `list` on pods, `pods/log`,
events, CronJobs, Jobs, Argo CD Applications, Traefik IngressRoutes and cert-manager
Certificates. Sources that use `service = …` also need `get` on `services/proxy`. When a
permission is missing, the adapter tries its next way, or reads unreachable with the
reason.

#### Their doctor checks

Each of these adapters has a `doctor()` method, so `bromigos lab doctor` checks it. The
finding ids start with the area: `gpus.*`, `logs.*`, `routes.*`, `certs.*`, `ddns.*`,
`network.*`, `nas.*`, `apps.*`, `s3.*`, `games.*`, `library.*`, `models.*`, `ocr.*`,
`runners.*`, `packages.*` and `backups.*`. For example:

- `dcgm` warns about temperature, nearly full VRAM and XID errors.
- `cert-manager` warns about certificates close to expiry, or not ready.
- `backups` warns when nothing backs up the lab, when volumes on a node's own disk have no
  backup job, when shares have snapshots off, and when no copy leaves the lab.

Argo CD adds `argo.<app>.why`. It lists each app that's out of sync or degraded, with the
reason. It also flags an app that went out of sync three or more times in the last hour.
That pattern means Argo CD fixes the app and something undoes the fix, such as a
controller adding a field the app's Git source doesn't have.

#### The `ocr` job kind

With an `ocr` source, `bromigos lab run ocr --input FILE` turns a PDF or an image into
text, page by page. Each PDF page is rendered with pdftoppm first. The result is a `.txt`
file with a form feed between pages.

### Writing an adapter

An adapter is a Python file in `~/.config/bromigos/plugins/homelab/`, or in
`$BROMIGOS_HOMELAB_PLUGINS`. It subclasses `Adapter` and registers itself:

```python
from bromigos_homelab import Adapter, register

@register
class Netdata(Adapter):
    type = "netdata"
    provides = ("metrics", "hosts")
    default_ports = (19999,)            # `bromigos setup homelab` probes these

    def probe(self):                    # is the endpoint one of these? (a real API answer)
        return "version" in self.get_json("/api/v1/info", timeout=3)

    def hosts(self):                    # one method per capability, returning records
        i = self.get_json("/api/v1/info")
        return [{"name": i["mirrored_hosts"][0], "up": True, "cores": i.get("cores_total")}]

    def metrics_query(self, q, timeout=8):   # metrics: metrics_query and metrics_range
        ...
```

- An adapter has `self.endpoint`, `self.opts` (the source's table), `self.get_json(path)`
  and `self.request(...)`.
- `get_json` and `request` use the source's `tls_ca`, and send its `auth_ref` as a bearer
  header. `auth_header` and `auth_scheme` change the header.
- When the service is down, raise `Unreachable`, or let the network error through. The
  Result reports it.
- An adapter that needs no endpoint, such as one for a command or a socket, sets
  `local = True` and defines `configured()`.
- A plugin can't replace a type bromigOS already has. The first registration wins.
- An adapter that fails to load is skipped, and `bromigos homelab status` names it.
- Adapters run inside VECTOR's tool calls, so this folder is guarded like his own code.
  He can't write to it, and his guard records every change in its audit log
  (`bromigos vector guard log`).

To share an adapter, package it as a `homelab-adapter` extension
([extensions.md](extensions.md)).

## Panels without code

A *panel* (widget) is one of the small dashboards on the desktop. You can declare one in
`homelab.toml`, or in `~/.config/bromigos/homelab/panels/*.toml`, with no code. It appears
on the desktop in the theme's colours, like every panel, and goes away when its source
does.

```toml
[[panel]]
name = "gpu"
title = "GPU"
kind = "gauge"                          # gauge, sparkline, stat, status or table
metric = "avg(DCGM_FI_DEV_GPU_UTIL)"
unit = "%"
max = 100
warn = 70                               # amber from here, red from crit
crit = 90

[[panel]]
name = "cluster-cpu"
kind = "sparkline"
metric = '100*(1-avg(rate(node_cpu_seconds_total{mode="idle"}[5m])))'
range_minutes = 60
unit = "%"

[[panel]]
name = "pods"
title = "Pods running"
kind = "stat"
capability = "workloads"
where = { state = "running" }

[[panel]]
name = "argo"
kind = "table"
capability = "deployments"
columns = ["name", "sync", "health"]
limit = 8

[[panel]]
name = "jellyfin"
kind = "status"
url = "http://jellyfin.example.org:8096/health"   # up when it answers with expect (200)

[[panel]]
name = "inference"
kind = "status"
capability = "workloads"
select = { namespace = "ai", name = "vllm.*" }

[[panel]]
name = "comfyui"
title = "ComfyUI"
kind = "status"
capability = "media"                    # up while the ComfyUI source answers
```

Each panel binds to one thing:

- `metric`: a query, through the `metrics` capability.
- `url`: a health check.
- `capability`: with `where` filters, and `select` for workloads.

Set `invert = true` when a low value is bad. Other options are `refresh` (seconds),
`width`, `height`, `x`, `y`, `visible`, `decimals`, `label`, `limit`, `columns` and
`link`.

To place a panel, add its name to the `"plugins"` map in `layout.json`, like any plugin
panel ([plugins.md](plugins.md)). To render one offscreen:

```bash
bromigos-widgets render gpu out.png
```

The LAB panel draws with the same primitives in `widgets/draw.py`: ring, bar, dot, seg7,
spark and label. It reads the snapshot, so it shows whatever your lab provides.

## What lights up

| On the desktop | Needs |
|---|---|
| the LAB panel | a snapshot: a `lab` source, or any of metrics, hosts, workloads, deployments, models or alerts |
| declared panels | whatever each binds to |
| the Ops deck (`bromigos-live ops`) | metrics from Argo CD and kube-state-metrics, and your Git repositories |
| the Netmap deck (`bromigos-live netmap`) | UniFi Poller's metrics, and `[netmap]` |
| the Mind deck (`bromigos-live mind`) | a `gnosis` source |
| the drift map's relays, and the worlds' beacon, lurker, coral and storm | the snapshot's services and alerts |
| the worlds' rain for model load | models with load: LiteLLM's or vLLM's metrics |
| VECTOR's homelab tools | the snapshot, metrics, a Kubernetes source, deployments, secrets, a `gnosis` source |
| VECTOR's memory in Gnosis | a `gnosis` source with both tokens |
| VECTOR's voice and hearing from the lab | a `voice` source, or `lab.url` in his `voice.json` |
| ComfyUI's state on a declared panel | a `comfyui` source |
| the lab console's other cards | the matching capability ([lab.md](lab.md)) |

The Ops, Netmap and Mind decks have no default key. Open them with the command shown, the
menu's HOLOGRAMS group, or the radial menu (Super+A).

## VECTOR's homelab tools

VECTOR's homelab tools are read-only: `lab_status`, `prometheus_query`, `k8s_get`,
`k8s_logs`, `k8s_events`, `argocd_apps`, `lab_vault_status`, `gnosis_search` and
`knowledge_search`. Each is offered only when `homelab.toml` has what it needs.

They're a packaged VECTOR plugin in `/usr/lib/bromigos/homelab/vector/`. Every call goes
through his audit log and his limits. To hide them all, set `homelab = "off"` under
`[tools]` in his `vector.toml`.

His tools that change a homelab, such as an Argo CD sync, a Vault write or `kb_write`,
are still in his own code. The plugin interface only allows reading and desktop actions.

## The lab console: cards, doctor checks and job kinds

`bromigos lab` is the lab console ([lab.md](lab.md)). It's built on three extension points
in `bromigos_homelab`: status cards, doctor checks and job kinds. bromigOS's own cards,
checks and kinds use them, and so can yours.

A file in `~/.config/bromigos/plugins/homelab/` that registers an adapter can also register
cards, checks and kinds. An adapter class can answer for them itself. The same goes for a
`homelab-adapter` extension. Nothing in the console names a vendor. It shows what the
registry reports.

### Status cards

`bromigos_homelab.console.status()` returns
`{"generatedAt", "state", "cards", "errors"}`. `bromigos lab status --json` prints it. A
card looks like this:

```json
{"id": "gpus", "title": "GPUs", "order": 20,
 "state": "ok | warn | crit | unreachable | empty",
 "summary": "2 GPUs · 1 busy · 9.2 / 24.0 GiB on the RTX 4090",
 "hint": "what the card shows and where it comes from (its hover hint)",
 "columns": ["name", "host", "vram", "util_pct", "temp_c", "power_w", "holds"],
 "items": [{"name": "RTX 4090", "state": "ok | warn | crit | unknown", "hint": "…", "…": "…"}],
 "errors": {"source": "unreachable: …"}, "sources": ["prometheus"]}
```

**Every capability with a provider gets a card.** When bromigOS has no card of its own for
a capability, the console makes a generic one:

- the capability's records are the items;
- the columns come from `caps.SCHEMAS`, or the record's keys;
- each item's state comes from the first of `state`, `health`, `status`, `sync` and `up`
  that says something.

`console.item_state` maps words to states. Failed, down and degraded are `crit`. Pending,
progressing and out of sync are `warn`. Running, healthy, synced and up are `ok`. So an
adapter for a new kind of service shows up on the console by itself.

**To shape a card**, register it:

```python
console.register_card(id, title=, order=, hint=, columns=, state=fn(rec),
                      summary=fn(items), item_hint=fn(rec), build=fn(result) -> card,
                      capability=, needs=, covers=)
```

The first registration of an id wins, so a plugin adds cards and never replaces one.
bromigOS's cards use these orders:

| Order | Card |
|---|---|
| 10 | Nodes |
| 20 | GPUs |
| 30 | Services |
| 40 | Models |
| 50 | GitOps apps |
| 55 | Workloads |
| 60 | Storage |
| 70 | Alerts |
| 80 | Jobs |
| 90 | Vault |
| 100 and up | generic cards, Agents (120), CI and pull requests (130) |

**A card that isn't a capability** comes from an adapter method, `cards(self)`, which
returns a list of cards. Each card needs a `title`, and the rest is filled in. If the
method raises, the console shows one *unreachable* card.

**Records the console reads** when an adapter provides them:

- `gpus`. Without it, the GPUs card reads NVIDIA's DCGM exporter through `metrics`, then
  the media server's device. A record may add `cuda` to the fields above.
- `storage`: `name`, `kind` (pool, share, bucket or disk), and `used` and `total` in bytes,
  or `used_pct`. The Storage card and the doctor's disk check read it beside each host's
  root disk.
- `backups`: `name`, `last_success` (Unix seconds or ISO 8601), `ok`, `max_age_hours`. The
  doctor's backup check reads it. Without it, that check is skipped.

**The `[console]` table** in `homelab.toml` sets:

| Key | What it does |
|---|---|
| `hide` | fnmatch patterns on an item's name or namespace. Matching items stay off every card and out of the doctor's Argo check. |
| `disk_warn_pct`, `disk_crit_pct` | when storage turns amber and red. Defaults 85 and 95. |
| `backup_max_age_hours` | how old a backup may be when its record doesn't say. Default 30. |
| `tokens` | tokens whose expiry the doctor checks: `[{ name = "…", vault = "kv/path" }]` |

### Doctor checks

`bromigos_homelab.doctor.run()` returns `{"generatedAt", "summary", "findings"}`, where
`summary` counts `ok`, `warn`, `fail` and `skip`. `bromigos lab doctor --json` prints it. A
finding looks like this:

```json
{"id": "tls.grafana.example.org", "check": "tls",
 "title": "TLS certificate of grafana.example.org",
 "status": "ok | warn | fail | skip", "detail": "expires 2026-10-21 (in 12 days)",
 "fix": "what to do, in plain words (empty when ok)", "source": "prometheus"}
```

There are two ways to add checks:

- **A check function.** Decorate it with
  `@doctor.check("ups", "UPS battery", order=60, needs=("power",))`. It yields or returns
  findings made with `doctor.finding(id, title, status, detail, fix, source)`. `needs`
  lists capabilities; when none of them has a provider, the check is skipped. The first
  registration of an id wins.
- **An adapter method**, `doctor(self)`, which returns findings. Every configured source
  that has one is asked, in parallel. If it raises, that's one `fail` finding: the source
  didn't answer.

Ids take the form `check.subject`. Each finding id is kept once, the first time it
appears. So an adapter's check and bromigOS's can meet on the same subject without
doubling it.

bromigOS's own checks are listed in [lab.md](lab.md#the-doctor). Checks only read. A fix
is advice, and nothing here changes the lab.

### Job kinds

A *job kind* is something `bromigos lab run` can make on the lab's GPUs, such as `image`
or `voice`. Register one like this:

```python
from bromigos_homelab import jobs

jobs.register_kind(jobs.Kind(
    id="ocr", title="OCR", summary="text from an image or a PDF",
    needs=("ocr",),          # capabilities that must have a provider
    vram_mib=0,              # peak VRAM the job adds on its GPU, measured (0: none)
    gpu="media",             # the GPU it lands on: "media" (ComfyUI's), "voice", "llm", or yours
    heavy=False,             # heavy jobs run one at a time, gated on free VRAM
    takes=("input",),        # what `lab run` passes: prompt, input, text, voice, model, aspect, mask, name
    ext=".txt",              # its result files
    run=run_ocr,             # run(job, ctx) -> [output paths]
    available=None))         # optional: () -> (ok, why), beyond needs
jobs.register_preset(jobs.Preset("receipt", "ocr", "Receipt", "a receipt's text", {"template": "…"}))
```

A kind whose `needs` have no provider says "not available" and why. When `run` fails for a
reason the user can act on, it raises `jobs.JobError("plain words")`. Kind ids use
lowercase letters, digits and hyphens. The first registration of an id wins.

`run(job, ctx)` gets the queue's record of the job (`id, kind, preset, prompt, text,
inputs, options, voice, model, …`) and a context:

| Context | What it gives |
|---|---|
| `ctx.out(stem, ext)` | a new path in `~/Pictures/bromigos/lab/<kind>/` |
| `ctx.log(text)` | a line in the job's log |
| `ctx.progress(fraction, text)` | progress from 0 to 1, shown in the dashboard and the deck |
| `ctx.note(**info)` | details shown with the job |
| `ctx.cancelled()` | true once the job is cancelled; stop soon |
| `ctx.run(argv, timeout)` | runs a command, killed if the job is cancelled |
| `ctx.source(type)` | a configured adapter of that type |
| `ctx.cloud` | whether the user passed `--cloud`. Never assume it. |

A heavy kind's `vram_mib` decides when it may start. The queue also records the most each
kind was seen to take, in `vram.json`, and uses the larger of the two.

#### Measured kinds: jobs.toml

`homelab/share/lab/jobs.toml`, installed as `/usr/share/bromigos/homelab/lab/jobs.toml`,
records what a kind measured. Whoever builds or re-measures a kind writes it there, not
in code. Each entry is a `[kind.<id>]` table:

| Key | What it records |
|---|---|
| `vram_mib` | the peak VRAM the job adds over what its GPU holds at rest |
| `seconds` | a typical job's time, from start to file |
| `workflow` | the `bromigos art` workflow it ran |
| `measured` | when, and on what |
| `note` | how it was measured, in plain words; the kind's hover hint |

`jobs.py` reads the file when it's imported. An entry sets that kind's `vram_mib` and its
hover note.

The `video` kind is there now. It's Wan 2.2 TI2V-5B making a 5-second loop, measured at
17,800 MiB (17.4 GiB) and about 2.5 minutes on a 32 GB card. It runs `bromigos art make video.loop` on
the lab, with no credits. The `creature-loop` preset adds a prompt that describes motion,
and `--alpha luma` for a world's loop ([art.md](art.md)).

## Security

- **Read-only by design.** Give the Kubernetes source a viewer kubeconfig. The desktop only
  gets, lists and reads logs. The Vault adapter reads health only.
- **No secrets in the file.** `auth_ref` holds references. Tokens live in files with mode
  0600, in the private overlay, or in Vault.
- **VECTOR's guard** covers this package, its data layer, `homelab.toml` and the adapter
  plugin folder. He can't write to them, and his guard's audit log records any change.
- **Nothing is sent anywhere** except the endpoints you configure.
