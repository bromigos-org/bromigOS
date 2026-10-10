"""Capabilities: what the desktop asks the homelab for, whatever runs it.

Every call returns a Result (a dict): {"ok", "items", "errors", "sources"}:
  ok       at least one provider answered
  items    the combined answer (a list of the capability's records; metrics: series)
  errors   {source: "unreachable: …"} for providers that didn't answer
  sources  the providers asked
With no provider the Result is {"ok": False, "items": [], "errors": {}, "sources": []}:
the consumer hides itself. A provider that's down is in errors: the consumer shows
"unreachable", never crashes.

Records (every field may be None when a source doesn't know it; "source" is always set):

  metrics      query(q)          -> [{"labels": {…}, "value": float, "t": float}]
               query_range(q, minutes, step) -> [{"labels": {…}, "points": [[t, v], …]}]
               (q is the source's query language: PromQL for Prometheus/VictoriaMetrics)
  hosts        {name, up, cpu_pct, mem_pct, disk_pct, load1, cores}
  workloads    {name, namespace, kind: pod|container|vm, state: running|pending|failed|
                stopped|unknown, restarts, node, image}
  deployments  {name, namespace, sync: synced|out_of_sync|unknown,
                health: healthy|progressing|degraded|missing|suspended|unknown, revision}
  models       {name, model, up, requests_per_min, tokens_per_s}
  agents       {key, name, status: working|needs_you|finished|error, cwd}
  secrets      {name, reachable, initialized, sealed, standby, version}   (status only: never a secret)
  ci           {repo, kind: pr|run, number, title, status: open|queued|in_progress|completed,
                conclusion: success|failure|cancelled|None, url, updated}
  alerts       {name, severity, state: firing|pending, summary, since, labels, link (its page on the source)}
  energy       {name, kind: solar, production_w, consumption_w, net_w (+ from the grid, - to it), today_wh,
                consumed_today_wh, lifetime_wh, battery_pct, battery_w, inverters, state}
"""
import concurrent.futures as cf

from . import registry
from .registry import Unreachable

SCHEMAS = {
    "hosts": ("name", "up", "cpu_pct", "mem_pct", "disk_pct", "load1", "cores"),
    "workloads": ("name", "namespace", "kind", "state", "restarts", "node", "image"),
    "deployments": ("name", "namespace", "sync", "health", "revision"),
    "models": ("name", "model", "up", "requests_per_min", "tokens_per_s"),
    "agents": ("key", "name", "status", "cwd"),
    "secrets": ("name", "reachable", "initialized", "sealed", "standby", "version"),
    "ci": ("repo", "kind", "number", "title", "status", "conclusion", "url", "updated"),
    "alerts": ("name", "severity", "state", "summary", "since", "labels", "link"),
    "voice": ("name", "endpoint", "up", "tts", "stt", "sample_rate", "tts_model", "stt_model"),
    "media": ("name", "endpoint", "up", "running", "pending", "vram_free", "vram_total", "gpu", "version", "models"),
    # the lab's own services (adapters/lab*.py); `state` is ok | warn | crit where the adapter judges it
    "gpus": ("name", "host", "model", "uuid", "vram_used", "vram_total", "util_pct", "temp_c", "power_w", "power_limit_w",
             "driver", "cuda", "holds"),
    "logs": ("name", "errors", "window_min", "state", "link"),
    "routes": ("name", "host", "entrypoints", "service", "up", "status", "tls", "rps", "error_pct"),
    "certs": ("name", "namespace", "dns_names", "not_after", "days_left", "ready", "issuer", "state"),
    "ddns": ("name", "type", "public_ip", "dns_ip", "match", "proxied", "updated", "state"),
    "network": ("name", "kind", "model", "up", "clients", "rx_bps", "tx_bps", "uptime_s", "version"),
    "storage": ("name", "kind", "used", "total", "used_pct", "objects", "healthy", "state", "nas", "free"),
    "apps": ("name", "kind", "up", "version", "detail", "endpoint", "vram_used", "link"),
    "games": ("name", "game", "status", "players", "players_max", "uptime_s", "cpu_pct", "mem_bytes"),
    "library": ("name", "kind", "up", "version", "queue", "queue_errors", "missing", "disk_free", "disk_total",
                "issues", "state"),
    "runners": ("name", "org", "online", "runners", "busy", "queued", "min", "max", "state"),
    "packages": ("name", "repo", "latest", "built", "age_h", "packages", "state"),
    "backups": ("name", "kind", "last_success", "age_h", "schedule", "ok", "max_age_hours", "offsite"),
    "ocr": ("name", "endpoint", "up", "model", "via"),
    "energy": ("name", "kind", "production_w", "consumption_w", "net_w", "today_wh", "consumed_today_wh",
               "lifetime_wh", "battery_pct", "battery_w", "inverters", "state"),
    # Pinchflat: one record for the downloader (kind "downloader": queue, errors, sources, recent),
    # then one per source (kind "channel" | "playlist")
    "youtube-downloader": ("name", "kind", "up", "videos", "newest", "newest_at", "queue", "errors", "state", "link"),
}


def _empty():
    return {"ok": False, "items": [], "errors": {}, "sources": []}


def _why(e):
    if isinstance(e, Unreachable):
        return "unreachable: " + str(e).split(": ", 1)[-1][:160]
    return f"{type(e).__name__}: {str(e)[:160]}"


def _norm(cap, rec, src):
    keys = SCHEMAS.get(cap)
    out = {k: rec.get(k) for k in keys} if keys else dict(rec)
    for k, v in rec.items():                # an adapter may add fields; schema fields come first
        out.setdefault(k, v)
    out["source"] = src
    return out


def collect(cap, method=None, *args, **kw):
    """Ask every provider of cap (in parallel), combine their records."""
    provs = registry.providers(cap)
    res = _empty()
    if not provs:
        return res
    res["sources"] = [a.name for a in provs]
    method = method or cap.replace("-", "_")         # youtube-downloader -> a.youtube_downloader()

    def one(a):
        return a, getattr(a, method)(*args, **kw)
    with cf.ThreadPoolExecutor(min(8, len(provs))) as ex:
        futs = [ex.submit(one, a) for a in provs]
        for f in futs:
            try:
                a, recs = f.result()
            except Exception as e:
                a = provs[futs.index(f)]
                res["errors"][a.name] = _why(e)
                continue
            res["ok"] = True
            res["items"] += [_norm(cap, r, a.name) for r in (recs or [])]
    return res


def first(cap, method, *args, **kw):
    """The first provider of cap that answers (metrics: one query language, one answer)."""
    res = _empty()
    for a in registry.providers(cap):
        res["sources"].append(a.name)
        try:
            res["items"] = getattr(a, method)(*args, **kw) or []
            res["ok"] = True
            return res
        except Exception as e:
            res["errors"][a.name] = _why(e)
    return res


def available(cap):
    return bool(registry.providers(cap))


# ---- the capabilities
def metrics(q, timeout=8):
    return first("metrics", "metrics_query", q, timeout=timeout)


def metrics_range(q, minutes=60, step=60, timeout=10):
    return first("metrics", "metrics_range", q, minutes, step, timeout=timeout)


def scalar(q, default=None, timeout=6):
    """The sum of a metrics query's values, or default (no provider, no data, unreachable)."""
    r = metrics(q, timeout)
    vals = [x["value"] for x in r["items"] if x.get("value") is not None]
    return sum(vals) if vals else default


def series(q, minutes=60, step=60):
    """[[t, v], …] of a range query's first series."""
    r = metrics_range(q, minutes, step)
    return [[int(t), round(float(v), 3)] for t, v in (r["items"][0]["points"] if r["items"] else [])]


def hosts():
    return collect("hosts")


def workloads(**selector):
    """selector: namespace, name (regex), kind, state."""
    import re
    r = collect("workloads")
    if selector:
        def keep(w):
            for k, v in selector.items():
                if v in (None, ""):
                    continue
                if k == "name" and not re.search(str(v), w.get("name") or ""):
                    return False
                if k != "name" and w.get(k) != v:
                    return False
            return True
        r["items"] = [w for w in r["items"] if keep(w)]
    return r


def deployments():
    return collect("deployments")


def models():
    return collect("models")


def agents():
    return collect("agents")


def secrets():
    return collect("secrets")


def ci(limit=20):
    return collect("ci", "ci", limit)


def voice():
    """Lab speech services (TTS/STT) VECTOR and others can speak and listen through."""
    return collect("voice")


def media():
    """Media generation servers (ComfyUI): queue, VRAM, models."""
    return collect("media")


def alerts():
    return collect("alerts")


# ---- the lab's own services (adapters/lab*.py): one accessor each, every one a Result
def _lab(cap, doc):
    def f():
        return collect(cap)
    f.__name__, f.__doc__ = cap, doc
    return f


gpus = _lab("gpus", "GPUs (DCGM): VRAM, use, temperature, power, and what holds each")
logs = _lab("logs", "Recent error counts per app (Loki)")
routes = _lab("routes", "Ingress routes and whether each answers (Traefik)")
certs = _lab("certs", "Certificates and their expiry (cert-manager)")
ddns = _lab("ddns", "Dynamic DNS records against the current public address")
network = _lab("network", "Network devices, clients and WAN throughput (UniFi through unpoller)")
storage = _lab("storage", "Object stores, NAS pools, shares and volumes: used and total")
apps = _lab("apps", "The lab's apps and whether they answer (web UIs, search, databases, log stacks)")
games = _lab("games", "Game servers: online, players (Pelican, Minecraft)")
library = _lab("library", "The media library's apps: queue, health, disk (Sonarr, Radarr, …, Jellyfin, Plex)")
runners = _lab("runners", "CI runner pools: online, busy, queued (GitHub Actions Runner Controller)")
packages = _lab("packages", "Package repository channels: the latest build and its age")
backups = _lab("backups", "Backup targets and their last success")
ocr = _lab("ocr", "OCR services (the `ocr` job kind runs on them)")
energy = _lab("energy", "Home energy: solar production, what the house uses, the grid and batteries (Enphase)")
youtube_downloader = _lab("youtube-downloader", "YouTube downloaders (Pinchflat): sources, newest videos, the "
                                                "download queue and failed jobs")
youtube_downloader.__name__ = "youtube_downloader"


def logs_query(selector=None, since_min=60, limit=200, contains=None, timeout=15):
    """Log lines from the first logs provider that answers: [{t, labels, line}], newest first.
    selector: an app name (its namespace or app label) or a LogQL stream selector."""
    return first("logs", "logs_query", selector, since_min=since_min, limit=limit, contains=contains, timeout=timeout)


def models_level(rpm_full=None, tps_full=None):
    """The local models generating, 0..1 (the worlds' `models` rain), or None with no models
    provider reporting load. Full rain at [models] rpm_full requests/min or tps_full tokens/s."""
    from . import config
    rpm_full = float(rpm_full or config.setting("models", "rpm_full", 30.0))
    tps_full = float(tps_full or config.setting("models", "tps_full", 40.0))
    r = models()
    if not r["ok"]:
        return None
    rpm = sum(m.get("requests_per_min") or 0.0 for m in r["items"])
    tps = sum(m.get("tokens_per_s") or 0.0 for m in r["items"])
    if not any(m.get("requests_per_min") is not None or m.get("tokens_per_s") is not None for m in r["items"]):
        return None
    return max(0.0, min(1.0, max(rpm / rpm_full, tps / tps_full))), rpm, tps
