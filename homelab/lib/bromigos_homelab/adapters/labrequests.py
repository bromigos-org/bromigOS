"""Media requests: Seerr (or Overseerr, Jellyseerr) and the download clients the *arr apps
hand their downloads to (qBittorrent, SABnzbd, slskd). Capability: requests. What each
holds now: Seerr's requests, each client's downloads. `bromigos lab media` (mediareq.py)
joins them with Sonarr, Radarr and Lidarr (type "arr" sources) into one status, and asks
through them.

    [[source]]
    name = "seerr"
    type = "seerr"                      # Seerr, Overseerr or Jellyseerr: the same API
    endpoint = "https://seerr.lab"
    auth_ref = "@file:~/.local/share/bromigos/seerr-key"     # Settings › General › API Key

    [[source]]
    name = "qbittorrent"
    type = "qbittorrent"
    endpoint = "https://qbittorrent.lab"
    auth_ref = "@file:~/.local/share/bromigos/qbittorrent-key"   # a WebUI API key (qBittorrent
                                        # 5.2+, sent as a Bearer token); or user_ref = the WebUI
                                        # user, and auth_ref its password

    [[source]]
    name = "sabnzbd"
    type = "sabnzbd"
    endpoint = "https://sabnzbd.lab"
    auth_ref = "@file:~/.local/share/bromigos/sabnzbd-key"   # Config › General › API Key

    [[source]]
    name = "slskd"
    type = "slskd"                      # Soulseek: music when Lidarr's indexers find nothing
    endpoint = "https://slskd.lab"
    auth_ref = "@file:~/.local/share/bromigos/slskd-password"    # the web UI's password
    user_ref = "slskd"                  # its user (slskd's default when left out); or
                                        # auth_scheme = "api-key" and auth_ref an API key
    import_path = "/media/downloads/slskd"   # where Lidarr sees slskd's downloads folder, so
                                        # it can import what slskd fetched

Read-only here: every call is a GET, except slskd's sign-in (a POST that changes nothing).
The requests themselves are mediareq.py's.
"""
import time
import urllib.parse

from ..registry import Unreachable, register
from . import labcommon as L

SEERR_STATUS = {1: "pending approval", 2: "approved", 3: "declined", 4: "failed", 5: "completed"}
MEDIA_STATUS = {1: "unknown", 2: "pending", 3: "processing", 4: "partly available", 5: "available",
                6: "blocklisted", 7: "deleted"}


def _secret(ref):
    from .. import config
    return config.resolve(ref or "")


@register
class Seerr(L.LabAdapter):
    """Seerr's requests: what was asked for, by whom, and where it is."""
    type = "seerr"
    hints = ("seerr", "overseerr", "jellyseerr")
    provides = ("requests",)
    default_ports = (5055,)

    def auth_headers(self):
        tok = _secret(self.opts.get("auth_ref"))
        return {"X-Api-Key": tok} if tok else {}

    def probe(self):
        d = self.request("/api/v1/status", timeout=3)
        return isinstance(d, dict) and "version" in d and "commitTag" in d

    def requests(self):
        d = self.fetch("/api/v1/request?take=50&skip=0&sort=added&filter=all", timeout=10) or {}
        out = []
        for r in d.get("results") or []:
            m = r.get("media") or {}
            out.append({"name": m.get("externalServiceSlug") or f"{m.get('mediaType')} {m.get('tmdbId')}",
                        "kind": m.get("mediaType"), "tmdb": m.get("tmdbId"), "tvdb": m.get("tvdbId"),
                        "state": SEERR_STATUS.get(r.get("status"), "unknown"),
                        "media": MEDIA_STATUS.get(m.get("status"), "unknown"),
                        "seasons": [s.get("seasonNumber") for s in r.get("seasons") or []],
                        "by": (r.get("requestedBy") or {}).get("displayName"), "added": r.get("createdAt"),
                        "id": r.get("id")})
        return out


@register
class QBittorrent(L.LabAdapter):
    """qBittorrent's torrents: progress, speed, ETA. A WebUI API key (Bearer), or a user and
    password (a session cookie, renewed when it lapses)."""
    type = "qbittorrent"
    hints = ("qbittorrent", "qbit")
    provides = ("requests",)
    default_ports = (8080,)

    def auth_headers(self):
        if self.opts.get("user_ref"):
            return {"Cookie": f"SID={self._sid()}"} if self._sid() else {}
        tok = _secret(self.opts.get("auth_ref"))
        return {"Authorization": f"Bearer {tok}"} if tok else {}

    def _sid(self, fresh=False):
        hit = getattr(self, "_session", None)
        if hit and not fresh and time.time() - hit[1] < 1800:
            return hit[0]
        user, pw = _secret(self.opts.get("user_ref")), _secret(self.opts.get("auth_ref"))
        if not (user and pw):
            return ""
        import urllib.request
        body = urllib.parse.urlencode({"username": user, "password": pw}).encode()
        req = urllib.request.Request(self.endpoint + "/api/v2/auth/login", data=body, method="POST",
                                     headers={"Referer": self.endpoint})
        try:
            with urllib.request.urlopen(req, timeout=8, context=self._ctx()) as r:
                cookie = r.headers.get("Set-Cookie") or ""
        except OSError as e:
            raise Unreachable(f"{self.name}: sign-in failed: {e}") from None
        sid = cookie.split("SID=", 1)[1].split(";", 1)[0] if "SID=" in cookie else ""
        self._session = (sid, time.time())
        return sid

    def probe(self):
        try:
            v = self.request("/api/v2/app/webapiVersion", timeout=3, raw=True)
        except Exception as e:
            return getattr(e, "code", None) in (401, 403)        # it's there, it wants a key
        return bool(v) and v[:1].isdigit()

    def torrents(self):
        return self.fetch("/api/v2/torrents/info", timeout=10) or []

    def requests(self):
        out = []
        for t in self.torrents():
            if t.get("progress", 0) >= 1 and t.get("state") not in ("error", "missingFiles"):
                continue
            out.append(download_of_torrent(t, self.name))
        return out


def download_of_torrent(t, source=None):
    eta = t.get("eta")
    why = "No seeders connected" if t.get("state") == "stalledDL" and t.get("num_seeds") == 0 else None
    return {"name": t.get("name"), "kind": "torrent", "id": (t.get("hash") or "").lower(),
            "progress": round(100 * (t.get("progress") or 0), 1), "speed": t.get("dlspeed"),
            "eta_s": eta if eta is not None and 0 <= eta < 8640000 else None, "size": t.get("size"),
            "left": t.get("amount_left"), "state": t.get("state"), "category": t.get("category"),
            "seeds": t.get("num_seeds"), "client": source, "why": why}


@register
class Sabnzbd(L.LabAdapter):
    """SABnzbd's queue and recent history (failures and why)."""
    type = "sabnzbd"
    hints = ("sabnzbd", "sab")
    provides = ("requests",)
    default_ports = (8080,)

    def auth_headers(self):
        return {}

    def api(self, mode, **q):
        key = _secret(self.opts.get("auth_ref"))
        qs = urllib.parse.urlencode(dict(q, mode=mode, output="json", apikey=key))
        return self.fetch(f"/api?{qs}", timeout=25) or {}

    def probe(self):
        d = self.request("/api?mode=version&output=json", timeout=3)
        return isinstance(d, dict) and "version" in d

    def queue(self):
        return self.api("queue").get("queue") or {}

    def history(self, limit=30):
        return self.api("history", limit=limit).get("history") or {}

    def requests(self):
        q = self.queue()
        return [download_of_slot(s, self.name) for s in q.get("slots") or []]


def _hms(s):
    try:
        parts = [int(x) for x in str(s).split(":")]
    except ValueError:
        return None
    t = 0
    for p in parts:
        t = t * 60 + p
    return t


def download_of_slot(s, source=None):
    mb, left = float(s.get("mb") or 0), float(s.get("mbleft") or 0)
    return {"name": s.get("filename"), "kind": "usenet", "id": s.get("nzo_id"),
            "progress": float(s.get("percentage") or 0), "speed": None, "eta_s": _hms(s.get("timeleft")),
            "size": int(mb * 2 ** 20), "left": int(left * 2 ** 20), "state": (s.get("status") or "").lower(),
            "category": s.get("cat"), "client": source}


@register
class Slskd(L.LabAdapter):
    """slskd (Soulseek): its downloads, by user and folder."""
    type = "slskd"
    hints = ("slskd", "soulseek")
    provides = ("requests",)
    default_ports = (5030,)

    def auth_headers(self):
        sec = _secret(self.opts.get("auth_ref"))
        if not sec:
            return {}
        if self.opts.get("auth_scheme") == "api-key":
            return {"X-API-Key": sec}
        tok = self._token()
        return {"Authorization": f"Bearer {tok}"} if tok else {}

    def _token(self):
        hit = getattr(self, "_jwt", None)
        if hit and time.time() < hit[1]:
            return hit[0]
        import json
        import urllib.request
        user = _secret(self.opts.get("user_ref")) or self.opts.get("user") or "slskd"
        body = json.dumps({"username": user, "password": _secret(self.opts.get("auth_ref"))}).encode()
        req = urllib.request.Request(self.endpoint + "/api/v0/session", data=body, method="POST",
                                     headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=8, context=self._ctx()) as r:
                d = json.loads(r.read() or b"{}")
        except OSError as e:
            raise Unreachable(f"{self.name}: sign-in failed: {e}") from None
        tok = d.get("token") or ""
        self._jwt = (tok, time.time() + 1800)
        return tok

    def probe(self):
        try:
            self.request("/api/v0/application", timeout=3)
            return True
        except Exception as e:
            return getattr(e, "code", None) == 401

    def downloads(self):
        return self.fetch("/api/v0/transfers/downloads", timeout=10) or []

    def requests(self):
        return [d for d in folders_of_transfers(self.downloads(), self.name) if d["progress"] < 100]


def folders_of_transfers(users, source=None):
    """slskd's downloads, one record per remote folder: progress over its files."""
    out = []
    for u in users or []:
        for d in u.get("directories") or []:
            files = d.get("files") or []
            size = sum(f.get("size") or 0 for f in files)
            done = sum(f.get("bytesTransferred") or 0 for f in files)
            states = [str(f.get("state") or "") for f in files]
            failed = [s for s in states if any(w in s for w in ("Errored", "Rejected", "TimedOut", "Cancelled"))]
            ok = all("Succeeded" in s for s in states) and files
            speed = sum(f.get("averageSpeed") or 0 for f in files if "InProgress" in str(f.get("state")))
            out.append({"name": d.get("directory", "").replace("\\", "/").rstrip("/").rsplit("/", 1)[-1],
                        "kind": "soulseek", "id": f"{u.get('username')}:{d.get('directory')}",
                        "user": u.get("username"), "directory": d.get("directory"),
                        "progress": 100.0 if ok else round(100 * done / size, 1) if size else 0.0,
                        "speed": speed or None, "eta_s": int((size - done) / speed) if speed else None,
                        "size": size, "left": size - done, "files": len(files),
                        "state": "completed" if ok else "failed" if failed and len(failed) == len(states)
                        else "downloading" if any("InProgress" in s for s in states) else "queued",
                        "failed_files": len(failed), "client": source})
    return out
