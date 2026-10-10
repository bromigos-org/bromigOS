"""The lab console's cards for the lab adapters' capabilities (console.register_card): titles,
columns, a hover hint for the card and for each item, a one-line summary. Without the console
(console.py) nothing registers. bromigOS's own cards (cards.py) register first, so theirs win
an id they share. gpus and storage are cards.py's."""
GIB = 1024 ** 3


def _n(v, unit="", d=0):
    return "?" if v is None else f"{v:.{d}f}{unit}"


def _bits(bps):
    if bps is None:
        return "?"
    for u, s in ((1e9, "Gb/s"), (1e6, "Mb/s"), (1e3, "kb/s")):
        if bps >= u:
            return f"{bps / u:.1f} {s}"
    return f"{bps:.0f} b/s"


def _count(items, pred):
    return sum(1 for i in items if pred(i))


def _yt_state(r):
    if r.get("kind") == "downloader":
        return "crit" if r.get("up") is False else "warn" if (r.get("errors") or 0) > 0 else "ok"
    return r.get("state") if r.get("state") in ("ok", "warn", "crit", "unknown") else "ok"


def _yt_hint(r):
    if r.get("kind") == "downloader":
        if r.get("up") is False:
            return f"{r['name']}: DOWN ({r.get('detail') or 'no answer'}). Nothing downloads until it's back."
        bits = [f"{r['name']}: up", f"{r.get('sources', 0)} sources ({r.get('channels', 0)} channels, "
                f"{r.get('playlists', 0)} playlists)", f"{r.get('videos') or 0} videos downloaded"]
        bits.append(f"{r['queue']} waiting to download" if r.get("queue") is not None else
                    "the queue is unknown (turn on its metrics: ENABLE_PROMETHEUS)")
        if r.get("errors"):
            bits.append(f"{r['errors']} failed in the last 30 days (Pinchflat's History page says why)")
        if r.get("recent"):
            bits.append("newest: " + "; ".join(f"{i['title']} ({i['source']})" for i in r["recent"][:3]))
        if r.get("detail"):
            bits.append(r["detail"])
        return " · ".join(bits) + (f" · open {r['link']}" if r.get("link") else "")
    what = {"playlist": "a playlist: its videos keep the playlist's order, and `bromigos lab youtube sync` makes "
                        "it a playlist in Jellyfin or Plex",
            "channel": "a channel: one season per year, newest last"}.get(r.get("kind"), "a source")
    return (f"{r['name']}: {what}. {r.get('videos') if r.get('videos') is not None else '?'} videos" +
            (f" · newest: {r['newest']} ({(r.get('newest_at') or '?')[:10]})" if r.get("newest") else "") +
            (f" · {r['detail']}" if r.get("detail") else "") + (f" · on YouTube: {r['link']}" if r.get("link") else ""))


def _yt_summary(items):
    me = [i for i in items if i.get("kind") == "downloader"]
    src = [i for i in items if i.get("kind") != "downloader"]
    q = sum(i.get("queue") or 0 for i in me)
    err = sum(i.get("errors") or 0 for i in me)
    if me and not any(i.get("up") for i in me):
        return "Pinchflat is down"
    return (f"{len(src)} sources · {sum(i.get('videos') or 0 for i in src)} videos · {q} waiting" +
            (f" · {err} failed" if err else ""))


def _requests_card(_res):
    """The Requests card: what's downloading for Sonarr, Radarr and Lidarr (progress and time
    left from qBittorrent and SABnzbd), Seerr's open requests and Soulseek fetches. The same
    data as `bromigos lab media status`, read-only (it hands nothing to Lidarr)."""
    from .. import mediareq as M
    lab = M.Lab()
    if not lab.configured():
        return None
    d = M.status(lab, finish=False)
    items = []
    for g in sorted(d["downloads"], key=lambda g: -(g.get("left") or 0)):
        stuck = any(k in g["states"] for k in ("stuck", "importFailed", "importBlocked", "failed", "failedPending"))
        kind = {"sonarr": "TV", "radarr": "film", "lidarr": "music"}[g["app"]]
        audio = "+".join(M.lang_name(a) for a in g["audio"])
        items.append({"name": g["title"], "kind": kind, "status": ", ".join(f"{n} {k}" for k, n in g["states"].items()),
                      "progress": f"{g['progress']:.0f}%" if g["progress"] is not None else "?",
                      "left": M.hm(g["eta_s"]) if g.get("eta_s") else "-", "audio": audio or "-",
                      "state": "warn" if stuck else "ok",
                      "hint": f"{g['title']} ({kind}): {g['items']} item(s), {M.human(g['size'])}"
                              + (f", {M.human(g['speed'])}/s" if g.get("speed") else "")
                              + (f", about {M.hm(g['eta_s'])} left" if g.get("eta_s") else "")
                              + (f" · audio {audio} (from the release names)" if audio else "")
                              + "".join(f" · why: {w[:160]}" for w in g["why"][:2])})
    for r in d.get("requests") or []:
        items.append({"name": r["name"], "kind": "film" if r["kind"] == "movie" else "TV", "status": f"Seerr: {r['media']}",
                      "progress": "-", "left": "-", "audio": "-", "state": "ok",
                      "hint": f"{r['name']}: requested in Seerr by {r.get('by') or '?'}, {r['media']}: Sonarr or Radarr "
                              "is looking for it (or waiting for its release)"})
    for f in d.get("soulseek") or []:
        items.append({"name": f["name"], "kind": "music", "status": f"Soulseek: {f['state']}",
                      "progress": f"{f['progress']:.0f}%", "left": M.hm(f["eta_s"]) if f.get("eta_s") else "-",
                      "audio": "-", "state": "warn" if f["state"] == "failed" else "ok",
                      "hint": f"{f['name']} from {f['user']} on Soulseek ({f['files']} files): Lidarr imports it when "
                              "it's done (bromigos lab media status hands it over)"})
    stuck = sum(1 for i in items if i["state"] == "warn" and i["kind"] != "subtitles")
    going = sum(1 for g in d["downloads"] if any(k in g["states"] for k in ("downloading", "queued", "importing",
                                                                           "importPending", "delay", "paused")))
    summary = (f"{going} downloading" if going else "nothing downloading") + (f" · {stuck} stuck" if stuck else "") + \
        (f" · {len(d['requests'])} requested" if d.get("requests") else "")
    if d.get("subtitle_warning"):
        items.append({"name": "Bazarr", "kind": "subtitles", "status": "no providers", "progress": "-", "left": "-",
                      "audio": "-", "state": "warn", "hint": d["subtitle_warning"]})
    return {"columns": ["name", "kind", "status", "progress", "left", "audio"], "items": items, "summary": summary,
            "errors": {f"media{i}": e for i, e in enumerate(d.get("errors") or [])}}


def _backup_state(r):
    age, limit = r.get("age_h"), r.get("max_age_hours") or 30
    if r.get("ok") is False or age is None:
        return "crit"
    return "crit" if age > 2 * limit else "warn" if age > limit else "ok"


CARDS = [
    dict(id="apps", title="Apps", order=35, columns=("name", "kind", "up", "version", "detail"),
         hint="The lab's apps (web UIs, search, databases, the log stack, OCR, GPU apps): whether each answers, "
              "its version, and its pods. Grey: not deployed.",
         item_hint=lambda r: f"{r['name']} ({r.get('kind')}): " + ("up" if r.get("up") else "not deployed"
                                                                    if r.get("up") is None else "DOWN") +
         (f", {r['version']}" if r.get("version") else "") + (f" · {r['detail']}" if r.get("detail") else "") +
         (f" · open {r['link']}" if r.get("link") else ""),
         summary=lambda items: f"{_count(items, lambda i: i.get('up'))} of "
                               f"{_count(items, lambda i: i.get('up') is not None)} up" +
         (f" · {_count(items, lambda i: i.get('up') is None)} not deployed"
          if _count(items, lambda i: i.get("up") is None) else "")),
    dict(id="logs", title="Logs", order=105, columns=("name", "errors", "window_min"),
         hint="Error lines each app logged lately (Loki), noisiest first. Amber and red from the source's "
              "warn_errors and crit_errors. bromigos lab logs <app> reads them.",
         item_hint=lambda r: f"{r['name']}: {r['errors']} error lines in the last {r.get('window_min')} min"
                             " · bromigos lab logs " + r["name"] + (f" · or {r['link']}" if r.get("link") else ""),
         summary=lambda items: f"{sum(i['errors'] for i in items)} error lines" +
         (f" · noisiest {items[0]['name']} ({items[0]['errors']})" if items else "")),
    dict(id="routes", title="Routes", order=110, columns=("name", "host", "up", "entrypoints", "rps"),
         hint="Every ingress route (Traefik) and whether a backend answers behind it; requests a second when "
              "Traefik's metrics are there. Red: no healthy backend, or Traefik rejected the route.",
         item_hint=lambda r: f"{r['host'] or r['name']} → {r.get('service')}: " +
         ("answers" if r.get("up") else "NO BACKEND" if r.get("up") is False else "declared") +
         f" ({', '.join(r.get('entrypoints') or [])})" + (f" · {r['rps']:.2f} req/s" if r.get("rps") else ""),
         summary=lambda items: f"{len(items)} routes" + (
             f" · {_count(items, lambda i: i.get('up') is False)} without a backend"
             if _count(items, lambda i: i.get("up") is False) else " · all answer")),
    dict(id="certs", title="Certificates", order=115, columns=("name", "namespace", "not_after", "days_left", "issuer"),
         hint="TLS certificates (cert-manager) and when each expires. Amber under 21 days, red under 7 or not ready.",
         item_hint=lambda r: f"{r['name']} ({', '.join(r.get('dns_names') or []) or '-'}): expires "
                             f"{(r.get('not_after') or '?')[:10]}, in {r.get('days_left')} days · issuer {r.get('issuer')}",
         summary=lambda items: (lambda s: f"soonest: {s['name']} in {s['days_left']} days" if s else "-")(
             min((i for i in items if i.get("days_left") is not None), key=lambda i: i["days_left"], default=None))),
    dict(id="ddns", title="Dynamic DNS", order=120, columns=("name", "type", "match", "proxied", "updated"),
         hint="DNS records a dynamic-DNS updater keeps pointed at this network's public address, and whether "
              "they match it now. Red: a record points elsewhere or the updater fails.",
         item_hint=lambda r: f"{r['name']} ({r.get('type')}): " + ("matches the public address" if r.get("match")
                                                                  else "DOES NOT match" if r.get("match") is False
                                                                  else "unknown") +
         (" · proxied (DNS answers the proxy's address)" if r.get("proxied") else "") +
         f" · updated {r.get('updated') or '?'}",
         summary=lambda items: f"{_count(items, lambda i: i.get('match'))} of {len(items)} records match"),
    dict(id="network", title="Network", order=125, columns=("name", "kind", "model", "up", "clients", "rx_bps", "tx_bps"),
         hint="The network's devices and WAN links (UniFi, through UniFi Poller): up, clients, and the gateway's "
              "WAN throughput now.",
         item_hint=lambda r: f"{r['name']} ({r['kind']}{', ' + r['model'] if r.get('model') else ''}): " +
         ("up" if r.get("up") else "DOWN") + (f" · {r['clients']} clients" if r.get("clients") is not None else "") +
         (f" · down {_bits(r.get('rx_bps'))}, up {_bits(r.get('tx_bps'))}" if r.get("rx_bps") is not None else "") +
         (f" · {r['role']}" if r.get("role") else ""),
         summary=lambda items: (lambda site, gw: f"{_count(items, lambda i: i['kind'] not in ('wan', 'site') and i.get('up'))}"
                                f" devices up · {site.get('clients', '?')} clients · WAN down "
                                f"{_bits(gw.get('rx_bps'))}, up {_bits(gw.get('tx_bps'))}")(
             next((i for i in items if i["kind"] == "site"), {}),
             next((i for i in items if i["kind"] == "gateway"), {}))),
    dict(id="games", title="Game servers", order=130, columns=("name", "game", "status", "players", "players_max"),
         hint="Game servers (Pelican): running or not, and who's playing. Starting and stopping them comes later.",
         item_hint=lambda r: f"{r['name']} ({r.get('game')}): {r['status']} · {r.get('players') or 0} of "
                             f"{r.get('players_max') or '?'} players · up {_n((r.get('uptime_s') or 0) / 3600, ' h')}",
         summary=lambda items: f"{_count(items, lambda i: i.get('status') == 'running')} of {len(items)} running · "
                               f"{sum(i.get('players') or 0 for i in items)} playing"),
    dict(id="library", title="Media library", order=135, columns=("name", "kind", "up", "queue", "missing", "disk_free"),
         hint="The media apps (Sonarr, Radarr, Lidarr, Prowlarr, Bazarr) and servers (Jellyfin, Plex): up, the "
              "download queue, what's missing, the library disk's free space. Read-only.",
         item_hint=lambda r: f"{r['name']} ({r.get('kind')}): " + ("up" if r.get("up") else "DOWN") +
         (f" · {r['queue']} in the queue" if r.get("queue") is not None else "") +
         (f" ({r['queue_errors']} with errors)" if r.get("queue_errors") else "") +
         (f" · {r['missing']} missing" if r.get("missing") is not None else "") +
         (f" · {r['disk_free'] / GIB:.0f} GiB free" if r.get("disk_free") is not None else "") +
         (f" · {r['version']}" if r.get("version") else ""),
         summary=lambda items: f"{_count(items, lambda i: i.get('up'))} of {len(items)} up · "
                               f"{sum(i.get('queue') or 0 for i in items)} downloading"),
    dict(id="youtube-downloader", title="YouTube downloads", order=136,
         columns=("name", "kind", "videos", "newest", "queue", "errors"), state=_yt_state,
         hint="Pinchflat downloads YouTube channels and playlists into your media library, so they play in "
              "Jellyfin or Plex. The first row is Pinchflat itself: the download queue and failed jobs. Then one "
              "row per channel or playlist, with its newest video. Read-only.",
         item_hint=_yt_hint, summary=_yt_summary),
    dict(id="requests", title="Requests", order=137, capability=None, needs=("requests", "library"), covers=("requests",),
         hint="Films, shows and music you asked for (bromigos lab media get): what Sonarr, Radarr and Lidarr are "
              "downloading, with progress and time left from qBittorrent and SABnzbd, Seerr's open requests and "
              "Soulseek fetches. Amber: stuck or failed to import (hover for why). Read-only; M (or bromigos media) "
              "opens the media library to change things.",
         build=_requests_card),
    dict(id="runners", title="CI runners", order=140, columns=("name", "online", "runners", "busy", "queued", "max"),
         hint="Self-hosted GitHub Actions runner pools (Actions Runner Controller): online, runners up, jobs "
              "waiting. Amber: jobs queue on a full pool.",
         item_hint=lambda r: f"{r['name']} ({r.get('org')}): " + ("online" if r.get("online") else "LISTENER DOWN") +
         f" · {r.get('runners')} running of max {r.get('max') if r.get('max') is not None else '?'} · "
         f"{r.get('queued')} queued",
         summary=lambda items: f"{_count(items, lambda i: i.get('online'))} pools online · "
                               f"{sum(i.get('runners') or 0 for i in items)} running · "
                               f"{sum(i.get('queued') or 0 for i in items)} queued"),
    dict(id="packages", title="Packages", order=145, columns=("name", "latest", "built", "age_h", "packages"),
         hint="The package repository's channels (edge, rc, stable): the newest build in each and how old it is.",
         item_hint=lambda r: f"{r['name']}: " + (f"{r['latest']}, built {r['built']} ({_n(r.get('age_h'), ' h')} ago), "
                                                 f"{r['packages']} packages" if r.get("latest") else "not published"),
         summary=lambda items: " · ".join(f"{i['name']} {_n(i.get('age_h'), ' h')}" for i in items if i.get("built"))
         or "nothing published"),
    dict(id="backups", title="Backups", order=150, columns=("name", "kind", "last_success", "age_h", "max_age_hours"),
         state=_backup_state,
         hint="Each backup target (backup jobs, NAS snapshots, Velero, a backup server) and when it last succeeded. "
              "Amber past its expected interval, red at twice it or when its last run failed. The doctor says "
              "what nothing backs up.",
         item_hint=lambda r: f"{r['name']} ({r['kind']}): last good {r.get('last_success') or 'never'} "
                             f"({_n(r.get('age_h'), ' h')} ago; expected within {r.get('max_age_hours')} h)" +
         ("" if r.get("ok") is not False else " · its last run FAILED") +
         (" · leaves the lab" if r.get("offsite") else ""),
         summary=lambda items: f"{len(items)} targets · oldest " + (lambda o: f"{o['name']} {_n(o['age_h'], ' h')}" if o
                                                                    else "-")(
             max((i for i in items if i.get("age_h") is not None), key=lambda i: i["age_h"] / (i.get("max_age_hours") or 30),
                 default=None))),
    dict(id="ocr", title="OCR", order=155, columns=("name", "up", "model", "via", "detail"),
         hint="OCR models the `ocr` job kind sends pages to (bromigos lab run ocr --input FILE).",
         item_hint=lambda r: f"{r['name']}: " + ("up" if r.get("up") else "down") + f" · model {r.get('model')} "
                             f"via {r.get('via')}" + (f" · {r['detail']}" if r.get("detail") else "")),
]


def register():
    try:
        from .. import console
    except ImportError:
        return
    try:
        from .. import cards  # noqa: F401  (bromigOS's own register first)
    except ImportError:
        pass
    for c in CARDS:
        console.register_card(**c)


register()
