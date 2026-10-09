"""The media library: the *arr apps (Sonarr, Radarr, Lidarr, Readarr, Prowlarr, Bazarr) and
the media servers (Jellyfin, Plex). Capability: library. Read-only.

    [[source]]
    type = "arr"                        # every *arr app an exporter reports (scraparr or exportarr
                                        # metrics in the metrics source), with no endpoint
    [[source]]
    name = "sonarr"
    type = "arr"
    endpoint = "http://sonarr.lab:8989" # or one app through its API (health, queue, disk, missing):
    auth_ref = "@file:~/.local/share/bromigos/sonarr-key"   # its API key (sent as X-Api-Key)

    [[source]]
    type = "jellyfin"                   # or "plex": up and version
    endpoint = "http://jellyfin.lab:8096"
"""
from ..registry import Unreachable, register
from . import labcommon as L

KINDS = {"sonarr": "tv", "radarr": "movies", "lidarr": "music", "readarr": "books", "prowlarr": "indexers",
         "bazarr": "subtitles", "whisparr": "adult", "jellyfin": "media server", "plex": "media server"}
MISSING = {"sonarr": "missing_episodes", "radarr": "missing_movies", "lidarr": "missing_releases",
           "readarr": "missing_books", "bazarr": "wanted_episodes"}


def _app(lb, metric=""):
    return (lb.get("alias") or lb.get("scraparr_services") or metric.split("_", 1)[0]).lower()


def library_from_metrics(get):
    """library records from scraparr's or exportarr's metrics. get(q) -> rows."""
    apps = {}

    def put(app, **kw):
        a = apps.setdefault(app, {"name": app, "kind": KINDS.get(app, "app"), "up": None, "version": None,
                                  "queue": None, "queue_errors": None, "missing": None, "disk_free": None,
                                  "disk_total": None, "issues": None})
        for k, v in kw.items():
            if v is not None:
                a[k] = v
    for r in get("scraparr_services_up"):
        put((r["labels"].get("scraparr_services") or _app(r["labels"])).lower(), up=(r["value"] or 0) > 0)
    for app in KINDS:
        if app in ("jellyfin", "plex"):
            continue
        for r in get(f"{app}_queue_count") or get(f"{app}_queue_total"):
            put(_app(r["labels"], app) if r["labels"].get("alias") else app, queue=int(r["value"]))
        for r in get(f"{app}_queue_error"):
            put(_app(r["labels"], app), queue_errors=int(r["value"]))
        free = get(f"{app}_free_disk_size") or get(f"{app}_rootfolder_freespace_bytes")
        if free:
            put(app, disk_free=min(r["value"] for r in free))
        miss = MISSING.get(app)
        for r in (get(f"{app}_{miss}_total") if miss else []) or \
                (get(f"{app}_{'episode' if app == 'sonarr' else 'movie'}_missing_total") if app in ("sonarr", "radarr") else []):
            put(app, missing=int(r["value"]))
        for r in get(f"{app}_system_health_issues"):
            put(app, issues=int(r["value"]))
        for r in get(f"{app}_system_status"):
            put(app, up=(r["value"] or 0) > 0)
        if app == "prowlarr":
            for r in get("prowlarr_indexer_enabled_total"):
                put(app, indexers=int(r["value"]))
        if app in apps and apps[app]["up"] is None:
            apps[app]["up"] = True               # the exporter scraped it
    for a in apps.values():
        a["state"] = "crit" if a["up"] is False else "warn" if (a.get("queue_errors") or 0) or (a.get("issues") or 0) else "ok"
    return sorted(apps.values(), key=lambda a: a["name"])


def library_findings(recs, free_warn_gib=50, source=None):
    out = []
    for r in recs:
        rid, title = f"library.{r['name']}", f"{r['name']} ({r['kind']})"
        if r.get("up") is False:
            out.append(L.finding(rid, title, "fail", "down", f"{r['name']} doesn't answer: look at its pod and logs.", source))
            continue
        for msg in r.get("health_messages") or []:
            out.append(L.finding(f"{rid}.health.{abs(hash(msg)) % 10000}", title, "warn", msg,
                                 f"{r['name']}'s own health check says so: its System › Status page has the details.",
                                 source))
        if (r.get("queue_errors") or 0) > 0:
            out.append(L.finding(f"{rid}.queue", title + ": queue", "warn", f"{r['queue_errors']} item(s) with errors",
                                 "Downloads are stuck: open its Activity › Queue to see why (often the download "
                                 "client or a missing path).", source))
        free = r.get("disk_free")
        if free is not None and 0 <= free < free_warn_gib * 2 ** 30:
            out.append(L.finding(f"{rid}.disk", title + ": disk", "warn", f"{free / 2**30:.0f} GiB free",
                                 "Its library disk is nearly full: imports will fail. Free space or grow it.", source))
    if recs and not out:
        q = sum(r.get("queue") or 0 for r in recs)
        out.append(L.finding("library.all", "Media library", "ok", f"{len(recs)} apps up · {q} in the download queue",
                             source=source))
    return out


@register
class Arr(L.LabAdapter):
    type = "arr"
    hints = ("sonarr", "radarr", "lidarr", "readarr", "prowlarr")  # setup --ingress: host names that suggest it
    provides = ("library",)
    default_ports = (8989, 7878, 8686, 9696, 6767)

    def auth_headers(self):
        from .. import config
        tok = config.resolve(self.opts.get("auth_ref") or "")
        return {self.opts.get("auth_header") or "X-Api-Key": tok} if tok else {}

    def probe(self):
        d = self.request("/ping", timeout=3)
        return isinstance(d, dict) and str(d.get("status", "")).upper() == "OK"

    @classmethod
    def detect(cls, d):
        if d.has_metric("scraparr_services_up") or any(d.has_metric(f"{a}_queue_total") for a in ("sonarr", "radarr")):
            return [{"type": "arr"}]
        return []

    def _api(self):
        for v in ("v3", "v1"):
            try:
                s = self.fetch(f"/api/{v}/system/status", timeout=6)
                return v, s
            except Exception as e:
                if getattr(e, "code", None) not in (404,):
                    raise
        raise Unreachable(f"{self.name}: no /api/v3 or /api/v1")

    def _one(self):
        v, s = self._api()
        app = (s.get("appName") or self.name).lower()
        rec = {"name": self.name, "kind": KINDS.get(app, "app"), "up": True, "version": s.get("version"),
               "queue": None, "queue_errors": None, "missing": None, "disk_free": None, "disk_total": None}
        health = self.fetch(f"/api/{v}/health", timeout=6) or []
        rec["issues"] = len(health)
        rec["health_messages"] = [h.get("message") for h in health if h.get("message")]
        try:
            q = self.fetch(f"/api/{v}/queue/status", timeout=6) or {}
            rec["queue"], rec["queue_errors"] = q.get("totalCount"), 1 if q.get("errors") else 0
        except Exception:
            pass
        try:
            disks = self.fetch(f"/api/{v}/diskspace", timeout=6) or []
            if disks:
                d = min(disks, key=lambda x: x.get("freeSpace") or 0)
                rec["disk_free"], rec["disk_total"] = d.get("freeSpace"), d.get("totalSpace")
        except Exception:
            pass
        if app in MISSING and app != "bazarr":
            try:
                rec["missing"] = (self.fetch(f"/api/{v}/wanted/missing?pageSize=1", timeout=6) or {}).get("totalRecords")
            except Exception:
                pass
        errs = any(h.get("type") == "error" for h in health)
        rec["state"] = "crit" if errs else "warn" if health or rec["queue_errors"] else "ok"
        return [rec]

    def library(self):
        if self.endpoint:
            return self._one()
        recs = library_from_metrics(L.mq_soft)
        if not recs:
            L.mq("vector(1)")
            raise Unreachable(f"{self.name}: no *arr exporter metrics (scraparr, exportarr) and no endpoint")
        return recs

    def doctor(self):
        return library_findings(self.library(), float(self.opt("free_warn_gib", 50)), self.name)


@register
class Jellyfin(L.LabAdapter):
    type = "jellyfin"
    provides = ("library",)
    default_ports = (8096,)

    def probe(self):
        d = self.request("/System/Info/Public", timeout=3)
        return isinstance(d, dict) and "Jellyfin" in str(d.get("ProductName", ""))

    def library(self):
        h = self.fetch("/health", raw=True, timeout=5).decode("utf-8", "replace").strip()
        i = self.fetch("/System/Info/Public", timeout=5) or {}
        return [{"name": self.name, "kind": "media server", "up": h.lower() == "healthy", "version": i.get("Version"),
                 "issues": 0 if h.lower() == "healthy" else 1, "detail": h}]


@register
class Plex(L.LabAdapter):
    type = "plex"
    provides = ("library",)
    default_ports = (32400,)

    def probe(self):
        d = self.request("/identity", timeout=3, headers={"Accept": "application/json"})
        return isinstance(d, dict) and "machineIdentifier" in (d.get("MediaContainer") or {})

    def library(self):
        d = (self.fetch("/identity", timeout=5, headers={"Accept": "application/json"}) or {}).get("MediaContainer") or {}
        return [{"name": self.name, "kind": "media server", "up": bool(d), "version": d.get("version"),
                 "claimed": d.get("claimed")}]
