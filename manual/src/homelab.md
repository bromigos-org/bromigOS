# Your homelab

A homelab is the computers you run yourself: servers, a NAS, a machine with a graphics
card for AI. If you have one, bromigOS can put it on your desktop and use it:

- the LAB [panel](panels.md) shows its health at a glance;
- the lab deck and other [holograms](holograms.md) show it in 3D;
- [VECTOR](vector.md) can tell you what it's doing, and use its AI models;
- AI work, such as pictures and VECTOR's voice, can run on its graphics cards instead of a
  paid service ([Creating with AI](where-ai-runs.md));
- the [worlds](themes-and-worlds.md#the-worlds) show its health: Tidewell's lighthouse,
  for example.

bromigOS works with the services you already run. It doesn't need a particular set-up.
You don't need a homelab to use bromigOS. Without one, these parts stay hidden.

## Connect your homelab

1. Run:

   ```bash
   bromigos setup homelab
   ```

2. Give it the names or addresses of your homelab's machines when it asks. It checks each
   one for the services it knows, and only counts a service whose own interface answers.
3. Check what it found:

   ```bash
   bromigos homelab status
   ```

4. Run `bromigos restart live widgets vector`, so the background, the panels and VECTOR
   pick it up.

Running `bromigos setup homelab` again only adds what's new. It never rewrites your own
changes.

Some useful options:

```bash
bromigos setup homelab --hosts nas,gpu-box          # check these machines
bromigos setup homelab --url https://prometheus.lan  # add one service by its address
bromigos setup homelab --print                       # show what it would add; change nothing
```

If you run Kubernetes, bromigOS never picks a cluster on its own. Name yours when it asks,
or with `--kube-context`.

## What it understands

| Kind of service | Examples |
|---|---|
| metrics and machines | Prometheus, VictoriaMetrics, Netdata |
| workloads | Kubernetes, Docker, Proxmox |
| deployments | Argo CD, Flux |
| AI models | LiteLLM, Ollama, vLLM, any OpenAI-compatible server |
| alerts | Alertmanager |
| secrets | Vault (its status only) |
| coding agents | herdr |
| code and pull requests | GitHub |
| voice and pictures | bromigOS's voice service, ComfyUI |
| graphics cards | NVIDIA's DCGM exporter |
| logs | Loki, Dozzle |
| the network's edge | Traefik, cert-manager, dynamic DNS, UniFi |
| storage | S3 object stores such as MinIO, a NAS and its shares |
| apps and databases | Open WebUI, SearXNG, Redis, Dragonfly, Neo4j |
| game servers | Pelican |
| media | Sonarr, Radarr, Lidarr, Prowlarr, Bazarr, Jellyfin, Plex |
| backups | backup jobs, NAS snapshots, Velero, Proxmox Backup Server |

Many of these need no address of their own. bromigOS finds them through your metrics or
your cluster, once it knows those.

If a service is missing, the parts of the desktop that need it are hidden. If a service
stops answering, it shows as "unreachable". To check everything, and get plain-words
advice on what to fix, run:

```bash
bromigos lab doctor
```

## Keep passwords out of the file

Your homelab's settings are in `~/.config/bromigos/homelab.toml`. Where a service needs a
password or a token, the file holds a *reference* to it, never the secret itself. So you
can keep the file in a public dotfiles repository.

| Write | To read the secret from |
|---|---|
| `@file:~/path` | a file, such as a token file only you can read |
| `@env:NAME` | an environment variable |
| `@private:some.key` | your [private overlay](glossary.md#private-overlay) |
| `@vault:path#field` | HashiCorp Vault, through its command-line tool |

## Your own panels without code

You can add a gauge, a chart, a number, a status light or a table to the desktop by
describing it in `homelab.toml`, or in a file in `~/.config/bromigos/homelab/panels/`. It
takes the theme's colours like every other panel. For example, a light that shows whether
a service answers:

```toml
[[panel]]
name = "jellyfin"
kind = "status"
url = "http://jellyfin.lan:8096/health"
```

Each panel reads one thing: a metrics query, an address to check, or one of the kinds of
service above. The developer docs'
[homelab.md](https://github.com/bromigos-org/bromigOS/blob/main/docs/homelab.md) lists
every option, with more examples.

## The lab console

`bromigos lab` shows your whole homelab at once, runs AI jobs on its graphics cards, and
checks it for problems. See [The lab console](lab.md).

## More

The developer docs'
[homelab.md](https://github.com/bromigos-org/bromigOS/blob/main/docs/homelab.md) has every
kind of service, the settings file in full, and how to write support for a new service.
