"""A fake media stack on 127.0.0.1 for `bromigos lab media` (mediareq.py): Seerr, Sonarr,
Radarr, Lidarr, Prowlarr, Bazarr, Jellyfin, Plex, qBittorrent, SABnzbd and slskd behind one
server, one path prefix each (http://127.0.0.1:PORT/sonarr/api/v3/…).

The answers have the shapes the real apps give (field names recorded from Seerr 3.4,
Sonarr 4, Radarr 6, Lidarr 3, Prowlarr 2, Bazarr 1.6, qBittorrent 5.2, SABnzbd 5.1 and
slskd 0.26); every title, id, name and number is made up. State is kept in memory, and
every write is logged in `writes` as (app, method, path, body).
"""
import copy
import json
import re
import threading
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

KEYS = {"seerr": "seerr-key", "sonarr": "sonarr-key", "radarr": "radarr-key", "lidarr": "lidarr-key",
        "prowlarr": "prowlarr-key", "bazarr": "bazarr-key", "jellyfin": "jf-key", "plex": "plex-token",
        "qbittorrent": "qbt_key", "sabnzbd": "sab-key", "slskd": "slskd-pass"}


# ------------------------------------------------------------------ quality profiles (TRaSH-like)
def q(qid, name, res, source, modifier=None):
    d = {"id": qid, "name": name, "source": source, "resolution": res}
    if modifier:
        d["modifier"] = modifier
    return d


SONARR_Q = [q(0, "Unknown", 0, "unknown"), q(1, "SDTV", 480, "television"), q(3, "WEBDL-1080p", 1080, "web"),
            q(15, "WEBRip-1080p", 1080, "webRip"), q(7, "Bluray-1080p", 1080, "bluray"),
            q(20, "Bluray-1080p Remux", 1080, "blurayRaw"), q(18, "WEBDL-2160p", 2160, "web"),
            q(17, "WEBRip-2160p", 2160, "webRip"), q(19, "Bluray-2160p", 2160, "bluray"),
            q(21, "Bluray-2160p Remux", 2160, "blurayRaw")]
RADARR_Q = [q(0, "Unknown", 0, "unknown"), q(3, "WEBDL-1080p", 1080, "webdl"), q(7, "Bluray-1080p", 1080, "bluray"),
            q(30, "Remux-1080p", 1080, "bluray", "remux"), q(18, "WEBDL-2160p", 2160, "webdl"),
            q(19, "Bluray-2160p", 2160, "bluray"), q(31, "Remux-2160p", 2160, "bluray", "remux")]


def profile(pid, name, qualities, allowed, scores=None, min_score=0, upgrade=True):
    items = [{"quality": x, "items": [], "allowed": x["name"] in allowed} for x in qualities]
    fi = [{"format": i + 1, "name": k, "score": v} for i, (k, v) in enumerate((scores or {}).items())]
    return {"id": pid, "name": name, "upgradeAllowed": upgrade, "cutoff": 1, "items": items, "minFormatScore": min_score,
            "cutoffFormatScore": 10000 if scores else 0, "minUpgradeFormatScore": 1, "formatItems": fi}


ANIME_TIERS = {"Anime BD Tier 01": 1400, "Anime BD Tier 02": 1300, "Remux Tier 01": 975, "Anime Web Tier 01": 600,
               "Anime Web Tier 02": 500, "Anime Web Tier 03": 400, "Anime Web Tier 04": 300, "Anime Web Tier 05": 200,
               "Anime Web Tier 06": 100, "HULU": 75, "MAX": 75, "CR": 6, "v4": 4, "v3": 3, "v2": 2, "v1": 1,
               "Anime Raws": -10000}


def anime_profiles(start, qualities, remux):
    allowed = {"Bluray-1080p", "WEBDL-1080p", remux}
    return [profile(start, "Remux-1080p - Anime", qualities, allowed, dict(ANIME_TIERS, **{"Dubs Only": -10000}), 100),
            profile(start + 1, "Remux-1080p - Anime (English preferred)", qualities, allowed,
                    dict(ANIME_TIERS, **{"Anime Dual Audio": 5000, "Dubs Only": 4000}), 100),
            profile(start + 2, "Remux-1080p - Anime (English audio)", qualities, allowed,
                    dict(ANIME_TIERS, **{"Anime Dual Audio": 5000, "Dubs Only": 4000}), 3000)]


NOT_EN = {"Language: Not English": -10000, "Repack/Proper": 5, "HDR": 500}

SONARR_PROFILES = [profile(1, "Any", SONARR_Q, {"SDTV", "WEBDL-1080p"}, upgrade=False),
                   profile(5, "Ultra-HD", SONARR_Q, {"WEBDL-2160p", "Bluray-2160p", "Bluray-2160p Remux"}, upgrade=False),
                   profile(7, "WEB-1080p", SONARR_Q, {"WEBDL-1080p", "WEBRip-1080p"}, NOT_EN),
                   profile(8, "WEB-2160p", SONARR_Q, {"WEBDL-2160p", "WEBRip-2160p", "WEBDL-1080p"}, NOT_EN)] + \
    anime_profiles(9, SONARR_Q, "Bluray-1080p Remux")
RADARR_PROFILES = [profile(4, "HD-1080p", RADARR_Q, {"Bluray-1080p", "WEBDL-1080p"}, upgrade=False),
                   profile(5, "Ultra-HD", RADARR_Q, {"Remux-2160p", "Bluray-2160p", "WEBDL-2160p"}, upgrade=False),
                   profile(7, "HD Bluray + WEB", RADARR_Q, {"Bluray-1080p", "WEBDL-1080p"}, NOT_EN),
                   profile(8, "Remux + WEB 2160p", RADARR_Q, {"Remux-2160p", "WEBDL-2160p", "Remux-1080p"}, NOT_EN)] + \
    anime_profiles(9, RADARR_Q, "Remux-1080p")
LIDARR_PROFILES = [
    {"id": 1, "name": "Any", "upgradeAllowed": False, "cutoff": 1, "formatItems": [],
     "items": [{"name": "Lossless", "allowed": True, "items": [{"quality": {"id": 6, "name": "FLAC"}, "allowed": True}]},
               {"name": "High Quality Lossy", "allowed": True,
                "items": [{"quality": {"id": 4, "name": "MP3-320"}, "allowed": True}]}]},
    {"id": 2, "name": "Lossless", "upgradeAllowed": False, "cutoff": 1, "formatItems": [],
     "items": [{"name": "Lossless", "allowed": True, "items": [{"quality": {"id": 6, "name": "FLAC"}, "allowed": True},
                                                             {"quality": {"id": 21, "name": "FLAC 24bit"},
                                                              "allowed": True}]}]},
    {"id": 3, "name": "Standard", "upgradeAllowed": False, "cutoff": 1, "formatItems": [],
     "items": [{"name": "High Quality Lossy", "allowed": True,
                "items": [{"quality": {"id": 4, "name": "MP3-320"}, "allowed": True}]}]}]


def qdefs(qualities):
    sizes = {"Bluray-1080p Remux": 69.1, "Remux-1080p": 69.1, "Bluray-2160p Remux": 187.4, "Remux-2160p": 187.4,
             "WEBDL-2160p": 25, "Bluray-2160p": 94.6, "Bluray-1080p": 50.4, "WEBDL-1080p": 15}
    return [{"quality": x, "title": x["name"], "minSize": sizes.get(x["name"], 2), "maxSize": None,
             "preferredSize": None, "id": i + 1} for i, x in enumerate(qualities)]


# ------------------------------------------------------------------ made-up titles (TMDB/TVDB shapes)
SEERR_MOVIES = {
    7001: {"id": 7001, "title": "Comet Drift", "releaseDate": "2027-03-12", "runtime": 128, "status": "Post Production",
           "posterPath": "/cometdrift.jpg", "overview": "A tug crew chases a comet.", "originalLanguage": "en",
           "genres": [{"id": 878, "name": "Science Fiction"}], "keywords": [{"id": 1, "name": "space"}],
           "productionCountries": [{"iso_3166_1": "US"}], "externalIds": {"imdbId": "tt9000001"},
           "releases": {"results": [{"iso_3166_1": "US", "release_dates": [{"type": 3, "release_date": "2027-03-12T00:00:00Z"}]}]}},
    7002: {"id": 7002, "title": "Lanterns of Kiri", "releaseDate": "2003-07-19", "runtime": 115, "status": "Released",
           "posterPath": "/kiri.jpg", "overview": "Spirits and a lantern maker.", "originalLanguage": "ja",
           "genres": [{"id": 16, "name": "Animation"}], "keywords": [{"id": 210024, "name": "anime"}],
           "productionCountries": [{"iso_3166_1": "JP"}], "externalIds": {"imdbId": "tt9000002"},
           "releases": {"results": [{"iso_3166_1": "US", "release_dates": [{"type": 3, "release_date": "2003-07-19T00:00:00Z"},
                                                                          {"type": 5, "release_date": "2004-02-01T00:00:00Z"}]}]}},
    7003: {"id": 7003, "title": "Toy Orchard", "releaseDate": "2019-06-01", "runtime": 95, "status": "Released",
           "posterPath": None, "overview": "Toys run an orchard.", "originalLanguage": "en",
           "genres": [{"id": 16, "name": "Animation"}], "keywords": [], "productionCountries": [{"iso_3166_1": "US"}],
           "externalIds": {}, "releases": {"results": []}},
}
SEERR_TV = {
    8001: {"id": 8001, "name": "Starlight Harbor", "firstAirDate": "1999-04-03", "status": "Ended", "posterPath": "/sh.jpg",
           "overview": "Bounty hunters in a harbor city.", "originalLanguage": "ja", "originCountry": ["JP"],
           "genres": [{"id": 16, "name": "Animation"}], "keywords": [{"id": 210024, "name": "anime"}],
           "episodeRunTime": [24], "externalIds": {"tvdbId": 90001, "imdbId": "tt9000101"},
           "seasons": [{"seasonNumber": 0, "episodeCount": 3, "airDate": None},
                       {"seasonNumber": 1, "episodeCount": 26, "airDate": "1999-04-03"}]},
    8002: {"id": 8002, "name": "The Lantern Office", "firstAirDate": "2005-03-24", "status": "Ended",
           "originalLanguage": "en", "originCountry": ["US"], "genres": [{"id": 35, "name": "Comedy"}], "keywords": [],
           "episodeRunTime": [22], "externalIds": {"tvdbId": 90002},
           "seasons": [{"seasonNumber": n, "episodeCount": 20, "airDate": f"{2004 + n}-03-01"} for n in range(1, 10)]},
    8003: {"id": 8003, "name": "The Lantern Office", "firstAirDate": "2001-07-09", "status": "Ended",
           "originalLanguage": "en", "originCountry": ["GB"], "genres": [{"id": 35, "name": "Comedy"}], "keywords": [],
           "episodeRunTime": [30], "externalIds": {"tvdbId": 90003},
           "seasons": [{"seasonNumber": 1, "episodeCount": 6}, {"seasonNumber": 2, "episodeCount": 6}]},
    8004: {"id": 8004, "name": "Paper Moon Cafe", "firstAirDate": "2021-01-10", "status": "Returning Series",
           "originalLanguage": "en", "originCountry": ["US"], "genres": [{"id": 18, "name": "Drama"}], "keywords": [],
           "episodeRunTime": [45], "externalIds": {"tvdbId": 90004},
           "nextEpisodeToAir": {"airDate": "2027-01-05", "seasonNumber": 4, "episodeNumber": 1},
           "seasons": [{"seasonNumber": n, "episodeCount": 10} for n in range(1, 5)]},
}


def sonarr_lookup(tv):
    t = SEERR_TV[tv]
    return {"title": t["name"], "year": int(t["firstAirDate"][:4]), "tvdbId": t["externalIds"]["tvdbId"],
            "tmdbId": tv, "status": "ended" if t["status"] == "Ended" else "continuing", "runtime": t["episodeRunTime"][0],
            "genres": ["Animation", "Anime"] if t["originalLanguage"] == "ja" else [g["name"] for g in t["genres"]],
            "originalLanguage": {"id": 8 if t["originalLanguage"] == "ja" else 1,
                                 "name": "Japanese" if t["originalLanguage"] == "ja" else "English"},
            "seriesType": "standard", "seasons": [{"seasonNumber": s["seasonNumber"], "monitored": False}
                                                  for s in t["seasons"]],
            "firstAired": t["firstAirDate"] + "T00:00:00Z", "remotePoster": "https://img.example/p.jpg",
            "monitorNewItems": "all", "images": []}


def radarr_lookup(mv):
    m = SEERR_MOVIES[mv]
    return {"title": m["title"], "year": int(m["releaseDate"][:4]), "tmdbId": mv, "imdbId": m["externalIds"].get("imdbId"),
            "runtime": m["runtime"], "status": "announced" if m["status"] != "Released" else "released",
            "inCinemas": m["releaseDate"] + "T00:00:00Z", "genres": [g["name"] for g in m["genres"]],
            "originalLanguage": {"name": "Japanese" if m["originalLanguage"] == "ja" else "English"},
            "monitored": False, "qualityProfileId": 0, "images": []}


# ------------------------------------------------------------------ the server
class State:
    def __init__(self):
        self.writes = []
        self.series = {}          # Sonarr id -> series
        self.episodes = {}        # Sonarr series id -> [episode]
        self.movies = {}          # Radarr id -> movie
        self.artists, self.albums = {}, {}
        self.commands = []
        self.next = {"series": 100, "movie": 200, "artist": 300, "album": 400, "cmd": 1, "seerr": 50}
        self.seerr_requests = []
        self.seerr_servers = {"sonarr": [{"id": 0, "isDefault": True, "is4k": False, "activeDirectory": "/media/tv"}],
                              "radarr": [{"id": 0, "isDefault": True, "is4k": False, "activeDirectory": "/media/movies"}]}
        self.seerr_adds = True    # Seerr hands requests to Sonarr/Radarr at once
        self.queue = {"sonarr": [], "radarr": [], "lidarr": []}
        self.torrents, self.sab_slots, self.sab_history = [], [], []
        self.lidarr_finds = True
        self.slskd_responses, self.slskd_downloads = [], []
        self.bazarr_profiles, self.bazarr_settings = [], {"enabled_providers": ["embeddedsubtitles"]}
        self.bazarr_episodes = {}
        self.jellyfin_items = []
        self.calendar = {"sonarr": [], "radarr": []}
        self.prowlarr_results = []

    # ---- Sonarr helpers
    def add_series(self, tv, monitored_seasons=(), profile=7, new="all", files=0, series_type="standard"):
        sid = self.next["series"]
        self.next["series"] += 1
        look = sonarr_lookup(tv)
        seasons = []
        eps = []
        for s in SEERR_TV[tv]["seasons"]:
            n = s["seasonNumber"]
            seasons.append({"seasonNumber": n, "monitored": n in monitored_seasons,
                            "statistics": {"episodeFileCount": files if n == 1 else 0, "episodeCount": s["episodeCount"],
                                           "totalEpisodeCount": s["episodeCount"], "sizeOnDisk": 0}})
            for e in range(1, s["episodeCount"] + 1):
                eps.append({"id": sid * 1000 + n * 100 + e, "seriesId": sid, "seasonNumber": n, "episodeNumber": e,
                            "monitored": n in monitored_seasons, "hasFile": n == 1 and e <= files})
        self.series[sid] = dict(look, id=sid, seasons=seasons, monitored=bool(monitored_seasons), qualityProfileId=profile,
                                monitorNewItems=new, seriesType=series_type, path=f"/media/tv/{look['title']}",
                                statistics={"episodeFileCount": files, "totalEpisodeCount": len(eps), "sizeOnDisk": 0,
                                            "seasonCount": len(seasons)})
        self.episodes[sid] = eps
        return sid

    def sync_episodes(self, sid):
        """Sonarr: episodes follow their season's monitored flag when it changes."""
        s = self.series[sid]
        for season in s["seasons"]:
            for e in self.episodes.get(sid, []):
                if e["seasonNumber"] == season["seasonNumber"]:
                    e["monitored"] = season["monitored"]


class Handler(BaseHTTPRequestHandler):
    server_version = "fake-media/1"

    def log_message(self, *a):
        pass

    @property
    def st(self):
        return self.server.state

    def _body(self):
        n = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(n) if n else b""
        if (self.headers.get("Content-Type") or "").startswith("application/x-www-form-urlencoded"):
            return urllib.parse.parse_qs(raw.decode())
        try:
            return json.loads(raw) if raw else None
        except ValueError:
            return raw.decode()

    def _send(self, code, obj, ctype="application/json", headers=None):
        b = obj if isinstance(obj, bytes) else json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(b)))
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(b)

    def _auth(self, app, qs):
        h = self.headers
        key = KEYS[app]
        if app in ("sonarr", "radarr", "lidarr", "prowlarr", "seerr"):
            return h.get("X-Api-Key") == key or (qs.get("apikey") == [key])
        if app == "bazarr":
            return h.get("X-Api-Key") == key or h.get("X-API-KEY") == key
        if app == "jellyfin":
            return key in (h.get("Authorization") or "")
        if app == "plex":
            return h.get("X-Plex-Token") == key
        if app == "qbittorrent":
            return h.get("Authorization") == f"Bearer {key}"
        if app == "sabnzbd":
            return qs.get("apikey") == [key] or qs.get("mode") == ["version"]
        if app == "slskd":
            return h.get("Authorization") == "Bearer jwt-1" or self.path.endswith("/api/v0/session")
        return False

    def do_GET(self):
        self._route("GET")

    def do_POST(self):
        self._route("POST")

    def do_PUT(self):
        self._route("PUT")

    def _route(self, method):
        u = urllib.parse.urlsplit(self.path)
        parts = u.path.split("/", 2)
        app, path = parts[1], "/" + (parts[2] if len(parts) > 2 else "")
        qs = urllib.parse.parse_qs(u.query)
        body = self._body() if method in ("POST", "PUT") else None
        if app not in KEYS:
            return self._send(404, {"message": "no such app"})
        if not self._auth(app, qs):
            return self._send(401, {"message": "Unauthorized"})
        if method != "GET":
            self.st.writes.append((app, method, path, body))
        try:
            res = getattr(self, "app_" + app)(method, path, qs, body)
        except KeyError as e:
            return self._send(404, {"message": f"not found: {e}"})
        if isinstance(res, tuple):
            return self._send(*res)
        return self._send(200, res)

    # ---------------------------------------------------------------- Seerr
    def app_seerr(self, method, path, qs, body):
        st = self.st
        if path == "/api/v1/search":
            words = (qs.get("query") or [""])[0].lower()
            res = [dict(mediaType="movie", id=k, title=v["title"], releaseDate=v["releaseDate"]) for k, v in
                   SEERR_MOVIES.items() if words in v["title"].lower()]
            res += [dict(mediaType="tv", id=k, name=v["name"], firstAirDate=v["firstAirDate"]) for k, v in
                    SEERR_TV.items() if words in v["name"].lower()]
            return {"page": 1, "totalPages": 1, "totalResults": len(res), "results": res}
        m = re.match(r"^/api/v1/(movie|tv)/(\d+)$", path)
        if m:
            d = copy.deepcopy((SEERR_MOVIES if m.group(1) == "movie" else SEERR_TV)[int(m.group(2))])
            return d
        m = re.match(r"^/api/v1/settings/(sonarr|radarr)$", path)
        if m:
            return st.seerr_servers[m.group(1)]
        if path == "/api/v1/request" and method == "POST":
            rid = st.next["seerr"]
            st.next["seerr"] += 1
            st.seerr_requests.append(dict(body, id=rid))
            if st.seerr_adds:
                if body["mediaType"] == "tv":
                    tv = body["mediaId"]
                    seasons = [s["seasonNumber"] for s in SEERR_TV[tv]["seasons"] if s["seasonNumber"]] \
                        if body["seasons"] == "all" else body["seasons"]
                    st.add_series(tv, seasons, body["profileId"], "all")
                else:
                    mid = st.next["movie"]
                    st.next["movie"] += 1
                    st.movies[mid] = dict(radarr_lookup(body["mediaId"]), id=mid, qualityProfileId=body["profileId"],
                                          monitored=True, minimumAvailability="released", hasFile=False)
            return 201, {"id": rid, "status": 2}
        if path.startswith("/api/v1/request"):
            return {"results": [{"id": r["id"], "status": 2, "createdAt": "2026-10-01T00:00:00Z",
                                 "requestedBy": {"displayName": "tester"},
                                 "media": {"mediaType": r["mediaType"], "tmdbId": r["mediaId"], "status": 3},
                                 "seasons": []} for r in st.seerr_requests]}
        raise KeyError(path)

    # ---------------------------------------------------------------- Sonarr
    def app_sonarr(self, method, path, qs, body):
        st = self.st
        p = path[len("/api/v3"):]
        if p == "/qualityprofile":
            return SONARR_PROFILES
        if p == "/qualitydefinition":
            return qdefs(SONARR_Q)
        if p == "/rootfolder":
            return [{"path": "/media/tv", "freeSpace": 22 * 10 ** 12}]
        if p == "/series/lookup":
            term = qs["term"][0]
            m = re.match(r"tvdb:(\d+)", term)
            out = []
            for tv, t in SEERR_TV.items():
                if (m and t["externalIds"]["tvdbId"] == int(m.group(1))) or (not m and term.lower() in t["name"].lower()):
                    have = next((s for s in st.series.values() if s["tvdbId"] == t["externalIds"]["tvdbId"]), None)
                    out.append(copy.deepcopy(have) if have else sonarr_lookup(tv))
            return out
        if p == "/series" and method == "GET":
            return list(st.series.values())
        if p == "/series" and method == "POST":
            tv = next(k for k, v in SEERR_TV.items() if v["externalIds"]["tvdbId"] == body["tvdbId"])
            sid = st.add_series(tv, [], body["qualityProfileId"], body.get("monitorNewItems", "all"),
                                series_type=body.get("seriesType"))
            st.series[sid]["monitored"] = body.get("monitored", True)
            return 201, st.series[sid]
        m = re.match(r"^/series/(\d+)$", p)
        if m:
            sid = int(m.group(1))
            if method == "PUT":
                old = st.series[sid]
                changed = {s["seasonNumber"] for s in body["seasons"]
                           if s["monitored"] != next(o["monitored"] for o in old["seasons"]
                                                     if o["seasonNumber"] == s["seasonNumber"])}
                st.series[sid] = body
                for e in st.episodes[sid]:
                    if e["seasonNumber"] in changed:
                        e["monitored"] = next(s["monitored"] for s in body["seasons"]
                                              if s["seasonNumber"] == e["seasonNumber"])
                return 202, body
            return st.series[sid]
        if p == "/seasonpass":
            opt = body["monitoringOptions"]["monitor"]
            for x in body["series"]:
                s = st.series[x["id"]]
                real = [z for z in s["seasons"] if z["seasonNumber"]]
                latest = max(z["seasonNumber"] for z in real)
                for z in s["seasons"]:
                    n = z["seasonNumber"]
                    z["monitored"] = {"all": n > 0, "latestSeason": n == latest, "future": False, "none": False}[opt]
                st.sync_episodes(x["id"])
                if opt == "future":
                    for e in st.episodes[x["id"]]:
                        e["monitored"] = False
            return 202, {}
        if p == "/episode":
            return st.episodes.get(int(qs["seriesId"][0]), [])
        if p == "/episode/monitor":
            for eps in st.episodes.values():
                for e in eps:
                    if e["id"] in body["episodeIds"]:
                        e["monitored"] = body["monitored"]
            return 202, {}
        if p == "/episodefile":
            sid = int(qs["seriesId"][0])
            return [{"id": e["id"], "seasonNumber": e["seasonNumber"], "qualityCutoffNotMet": e["episodeNumber"] == 1,
                     "mediaInfo": {"audioLanguages": "eng/jpn" if e["episodeNumber"] > 1 else "jpn", "subtitles": "eng"}}
                    for e in st.episodes.get(sid, []) if e["hasFile"]]
        if p == "/command":
            st.commands.append(("sonarr", body))
            return 201, {"id": len(st.commands), "status": "queued", "name": body["name"]}
        if p == "/queue":
            return {"page": 1, "totalRecords": len(st.queue["sonarr"]), "records": st.queue["sonarr"]}
        if p == "/history/series":
            return []
        if p == "/calendar":
            return st.calendar["sonarr"]
        raise KeyError(p)

    # ---------------------------------------------------------------- Radarr
    def app_radarr(self, method, path, qs, body):
        st = self.st
        p = path[len("/api/v3"):]
        if p.startswith("/feed/") or path.startswith("/feed/"):
            ics = ("BEGIN:VCALENDAR\r\nVERSION:2.0\r\nPRODID:-//fake//EN\r\n" + "".join(
                f"BEGIN:VEVENT\r\nUID:Radarr_movie_{mid}_digital\r\nDTSTART;VALUE=DATE:20261020\r\n"
                f"DTEND;VALUE=DATE:20261021\r\nSTATUS:CONFIRMED\r\nSUMMARY:{m['title']} (Digital Release)\r\n"
                "END:VEVENT\r\n" for mid, m in st.movies.items()) + "END:VCALENDAR\r\n").encode()
            return 200, ics, "text/calendar"
        if p == "/qualityprofile":
            return RADARR_PROFILES
        if p == "/qualitydefinition":
            return qdefs(RADARR_Q)
        if p == "/rootfolder":
            return [{"path": "/media/movies", "freeSpace": 22 * 10 ** 12}]
        if p == "/movie/lookup/tmdb":
            return radarr_lookup(int(qs["tmdbId"][0]))
        if p == "/movie/lookup":
            return [radarr_lookup(k) for k, v in SEERR_MOVIES.items() if qs["term"][0].lower() in v["title"].lower()]
        if p == "/movie" and method == "GET":
            if qs.get("tmdbId"):
                return [m for m in st.movies.values() if m["tmdbId"] == int(qs["tmdbId"][0])]
            return list(st.movies.values())
        if p == "/movie" and method == "POST":
            mid = st.next["movie"]
            st.next["movie"] += 1
            st.movies[mid] = dict(body, id=mid, hasFile=False)
            return 201, st.movies[mid]
        m = re.match(r"^/movie/(\d+)$", p)
        if m:
            mid = int(m.group(1))
            if method == "PUT":
                st.movies[mid] = body
                return 202, body
            return st.movies[mid]
        if p == "/moviefile":
            return []
        if p == "/command":
            st.commands.append(("radarr", body))
            return 201, {"id": len(st.commands), "status": "queued"}
        if p == "/queue":
            return {"page": 1, "totalRecords": len(st.queue["radarr"]), "records": st.queue["radarr"]}
        if p == "/history/movie":
            return []
        if p == "/calendar":
            return st.calendar["radarr"]
        raise KeyError(p)

    # ---------------------------------------------------------------- Lidarr
    def app_lidarr(self, method, path, qs, body):
        st = self.st
        p = path[len("/api/v1"):]
        artist = {"artistName": "The Quiet Engines", "foreignArtistId": "aaaaaaaa-0000-4000-8000-000000000001",
                  "artistType": "Group", "status": "continuing", "images": []}
        album = {"title": "Glass Valley", "foreignAlbumId": "bbbbbbbb-0000-4000-8000-000000000002",
                 "releaseDate": "2016-05-20T00:00:00Z", "albumType": "Album", "duration": 2700000,
                 "releases": [{"media": [{"trackCount": 10}]}], "artist": artist}
        if p == "/qualityprofile":
            return LIDARR_PROFILES
        if p == "/metadataprofile":
            return [{"id": 1, "name": "Standard"}]
        if p == "/rootfolder":
            return [{"path": "/media/music", "freeSpace": 22 * 10 ** 12}]
        if p == "/search":
            return [{"foreignId": artist["foreignArtistId"], "artist": artist},
                    {"foreignId": album["foreignAlbumId"], "album": album}]
        if p == "/album/lookup":
            return [album]
        if p == "/artist/lookup":
            return [artist]
        if p == "/album" and method == "POST":
            aid = st.next["album"]
            st.next["album"] += 1
            st.albums[aid] = dict(body, id=aid)
            return 201, st.albums[aid]
        if p == "/artist" and method == "POST":
            aid = st.next["artist"]
            st.next["artist"] += 1
            st.artists[aid] = dict(body, id=aid)
            return 201, st.artists[aid]
        if p == "/artist":
            return list(st.artists.values())
        if p == "/command" and method == "POST":
            st.commands.append(("lidarr", body))
            if body["name"] == "AlbumSearch" and st.lidarr_finds:
                st.queue["lidarr"].append({"albumId": body["albumIds"][0], "artistId": 300, "protocol": "torrent",
                                           "downloadClient": "qBittorrent", "size": 1, "sizeleft": 1,
                                           "artist": {"artistName": "The Quiet Engines"},
                                           "album": {"title": "Glass Valley"}, "status": "downloading"})
            return 201, {"id": len(st.commands), "status": "queued"}
        m = re.match(r"^/command/(\d+)$", p)
        if m:
            return {"id": int(m.group(1)), "status": "completed"}
        if p == "/queue":
            return {"page": 1, "totalRecords": len(st.queue["lidarr"]), "records": st.queue["lidarr"]}
        raise KeyError(p)

    # ---------------------------------------------------------------- Prowlarr
    def app_prowlarr(self, method, path, qs, body):
        p = path[len("/api/v1"):]
        if p == "/indexer":
            return [{"id": 1, "name": "NyaaLike", "enable": True}, {"id": 2, "name": "UsenetLike", "enable": True},
                    {"id": 3, "name": "BrokenLike", "enable": True}]
        if p == "/indexerstatus":
            return [{"indexerId": 3, "disabledTill": "2099-01-01T00:00:00Z"}]
        if p == "/search":
            return self.st.prowlarr_results
        raise KeyError(p)

    # ---------------------------------------------------------------- Bazarr
    def app_bazarr(self, method, path, qs, body):
        st = self.st
        if path == "/api/system/languages/profiles":
            return st.bazarr_profiles
        if path == "/api/system/languages":
            return [{"code2": "en", "name": "English", "enabled": False}]
        if path == "/api/system/settings" and method == "POST":
            st.bazarr_profiles = json.loads(body["languages-profiles"][0])
            return 204, b""
        if path == "/api/system/settings":
            return {"general": st.bazarr_settings}
        if path in ("/api/series", "/api/movies") and method == "POST":
            return 204, b""
        if path == "/api/series":
            return {"data": [{"profileId": 1 if st.bazarr_profiles else None}]}
        if path == "/api/episodes":
            sid = int(qs["seriesid[]"][0])
            return {"data": st.bazarr_episodes.get(sid, [])}
        if path == "/api/movies":
            return {"data": []}
        raise KeyError(path)

    # ---------------------------------------------------------------- Jellyfin and Plex
    def app_jellyfin(self, method, path, qs, body):
        st = self.st
        if path == "/Items":
            if qs.get("searchTerm"):
                t = qs["searchTerm"][0].lower()
                items = [i for i in st.jellyfin_items if t in i["Name"].lower()]
                return {"Items": items, "TotalRecordCount": len(items)}
            parent = qs["ParentId"][0]
            hit = next(i for i in st.jellyfin_items if i["Id"] == parent)
            if qs.get("IncludeItemTypes") == ["Season"]:
                return {"Items": [], "TotalRecordCount": hit["_seasons"]}
            return {"Items": [{"MediaSources": [{"MediaStreams": [{"Type": "Video", "Width": 3840},
                                                                  {"Type": "Audio", "Language": "eng"}]}]}],
                    "TotalRecordCount": hit["_episodes"]}
        raise KeyError(path)

    def app_plex(self, method, path, qs, body):
        if path == "/hubs/search":
            return {"MediaContainer": {"Hub": []}}
        raise KeyError(path)

    # ---------------------------------------------------------------- downloaders
    def app_qbittorrent(self, method, path, qs, body):
        if path == "/api/v2/torrents/info":
            return self.st.torrents
        raise KeyError(path)

    def app_sabnzbd(self, method, path, qs, body):
        mode = qs.get("mode", [""])[0]
        if mode == "queue":
            return {"queue": {"slots": self.st.sab_slots}}
        if mode == "history":
            return {"history": {"slots": self.st.sab_history}}
        if mode == "version":
            return {"version": "5.1.0"}
        raise KeyError(mode)

    def app_slskd(self, method, path, qs, body):
        st = self.st
        if path == "/api/v0/session":
            return {"token": "jwt-1", "tokenType": "Bearer"}
        if path == "/api/v0/searches" and method == "POST":
            st.slskd_search = body
            return {"id": body["id"], "state": "InProgress"}
        m = re.match(r"^/api/v0/searches/([\w-]+)(/responses)?$", path)
        if m:
            return st.slskd_responses if m.group(2) else {"id": m.group(1), "state": "Completed, TimedOut"}
        m = re.match(r"^/api/v0/transfers/downloads/(.+)$", path)
        if m and method == "POST":
            user = urllib.parse.unquote(m.group(1))
            d = body[0]["filename"].rsplit("\\", 1)[0]
            st.slskd_downloads.append({"username": user, "directories": [{"directory": d, "files": [
                dict(f, state="Queued, Remotely", bytesTransferred=0, averageSpeed=0) for f in body]}]})
            return 201, {}
        if path == "/api/v0/transfers/downloads":
            return st.slskd_downloads
        raise KeyError(path)


class Server:
    def __init__(self):
        self.state = State()
        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.httpd.state = self.state
        self.url = f"http://127.0.0.1:{self.httpd.server_address[1]}"
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()

    def close(self):
        self.httpd.shutdown()
        self.httpd.server_close()


def homelab_toml(path, url, apps=None, extra=""):
    """A homelab.toml with a source per app (keys from files under path's folder)."""
    import os
    apps = apps or ("seerr", "sonarr", "radarr", "lidarr", "prowlarr", "bazarr", "jellyfin", "plex", "qbittorrent",
                    "sabnzbd", "slskd")
    d = os.path.dirname(path)
    out = [extra]
    for a in apps:
        kf = os.path.join(d, f"{a}.key")
        with open(kf, "w") as f:
            f.write(KEYS[a])
        typ = "arr" if a in ("sonarr", "radarr", "lidarr", "prowlarr", "bazarr") else a
        out.append(f'[[source]]\nname = "{a}"\ntype = "{typ}"\nendpoint = "{url}/{a}"\nauth_ref = "@file:{kf}"\n'
                   + ('import_path = "/media/downloads/slskd"\n' if a == "slskd" else ""))
    with open(path, "w") as f:
        f.write("\n".join(out))
    return path
