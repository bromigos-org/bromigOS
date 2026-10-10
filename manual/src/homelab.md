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
| media | Seerr, Sonarr, Radarr, Lidarr, Prowlarr, Bazarr, Jellyfin, Plex, qBittorrent, SABnzbd, slskd, Pinchflat (YouTube downloads) |
| backups | backup jobs, NAS snapshots, Velero, Proxmox Backup Server |

Many of these need no address of their own. bromigOS finds them through your metrics or
your cluster, once it knows those.

If a service is missing, the parts of the desktop that need it are hidden. If a service
stops answering, it shows as "unreachable". To check everything, and get plain-words
advice on what to fix, run:

```bash
bromigos lab doctor
```

### YouTube downloads with Pinchflat

Pinchflat downloads YouTube channels and playlists into your media library. Add it to
`homelab.toml`. If its web page asks for a user and password, put them in a file as
`user:password` and name the file in `auth_ref`:

```toml
[[source]]
type = "pinchflat"
endpoint = "http://pinchflat.lan:8945"
auth_ref = "@file:~/.local/share/bromigos/pinchflat-login"
```

Without a password, it needs Pinchflat's route token instead. The token is in the OPML link
on Pinchflat's Sources page: copy the part after `route_token=` into a file, and name it in
`route_token_ref`.

To see its download queue too, start Pinchflat with `ENABLE_PROMETHEUS=true`.

For YouTube cookies (`bromigos lab youtube cookies`), say where Pinchflat reads them, with
`cookies_store` in the same source:

- `cookies_store = "file:/srv/pinchflat/config/extras/cookies.txt"` when its config folder
  is on this machine or a share you have mounted;
- `cookies_store = "vault:secret/lab/pinchflat#cookies"` when your lab copies Pinchflat's
  cookies from Vault.

`bromigos lab youtube sync` makes each downloaded playlist a playlist in Jellyfin or
Plex, in YouTube's order. It needs an API key for each media server: put it in a file and
name the file in that server's source as `token_ref`. See [The lab console](lab.md#youtube-downloads).

### Media requests

Start with [Your media](media.md) to find, download and watch a title.

To ask your lab for films, shows and music (`bromigos lab media`, see
[The lab console](lab.md#media-requests)), add a source for each app you have. Each needs
its address and its API key, which is on the app's Settings › General page. Put each key
in its own file, as above.

```toml
[[source]]
name = "seerr"
type = "seerr"
endpoint = "http://seerr.lan:5055"
auth_ref = "@file:~/.local/share/bromigos/seerr-key"

[[source]]
name = "sonarr"                  # the same for radarr, lidarr, prowlarr and bazarr
type = "arr"
endpoint = "http://sonarr.lan:8989"
auth_ref = "@file:~/.local/share/bromigos/sonarr-key"

[[source]]
name = "qbittorrent"             # and sabnzbd, slskd: for each download's progress
type = "qbittorrent"
endpoint = "http://qbittorrent.lan:8080"
auth_ref = "@file:~/.local/share/bromigos/qbittorrent-key"

[media]
audio = ["en", "ja"]             # your audio languages, best first
subtitles = ["en"]
```

Seerr is optional. Without it, requests go straight to Sonarr, Radarr and Lidarr. With it,
they show in Seerr's Requests too. qBittorrent needs a WebUI API key (version 5.2 or later),
or `user_ref` and its password. slskd takes its password, and `import_path`: the folder its
downloads land in, as Lidarr sees it.

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
