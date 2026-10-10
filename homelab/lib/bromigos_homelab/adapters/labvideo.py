"""The media servers' video libraries (Jellyfin, Plex): the `video` capability.

The den TV's channels (lib/bromigos_tv.py) and the media panel read a server's libraries,
collections and playlists, their items, what you were watching and what's new, and a
stream for each item. Read-only: nothing here marks anything watched or changes a library.

    [[source]]
    type = "jellyfin"
    endpoint = "@private:endpoints.jellyfin"
    auth_ref = "@file:~/.local/share/bromigos/jellyfin-key"     # an API key (Dashboard › API Keys)
    user = "alice"                       # optional: whose "continue watching"; default the first admin

    [[source]]
    type = "plex"
    endpoint = "@private:endpoints.plex"
    auth_ref = "@vault:kv/plex#token"    # an X-Plex-Token

The `video` capability's records are the server's collections of videos, one per
library, collection and playlist:

    {name, kind: library | collection | playlist, id, title, count, media: movies | shows | mixed,
     server (the source's name)}

Each adapter also answers, for the TV and the panel (not capabilities: one server each):

    playlists()                     its video playlists (the `video` records of kind playlist)
    video_items(kind, id, limit)    the items in one of those, in its own order
    video_resume(limit)             continue watching: items part-way through
    video_latest(limit)             recently added
    video_stream(item, quality, height)  {"url", "headers", "direct", "quality"}: what mpv plays
    video_shows()                   every series, to pick from: {id, title, year, poster, count, server}
    video_show_items(id)            a series' episodes
    video_movies()                  every movie, to pick from (items)
    video_item(id)                  one item, or None
    video_web(item)                 the item's page in the server's web app
    video_poster(item)              (url, headers) of its poster, or (None, {})

An item is {id, title, series, season, episode, kind: movie | episode | video, duration
(seconds), year, poster, bitrate (kbit/s), position (seconds watched, for resume), added
(unix seconds), server}.

quality is "direct" (the file as it is), "auto" (direct, unless its bitrate is over the
source's `direct_max_mbps`, 20 by default: then a 480p transcode), or a height such as
"480p" or "720p" (the server transcodes to H.264 at that height, over HLS).

With `height` (the pixels it's drawn at: a den screen is a couple of hundred), "auto"
sizes the stream to it: the smallest height in HEIGHTS at least that tall, transcoded at
that height's bitrate, unless the file itself is already small (no more than three times
that bitrate, and no taller than twice the height): then it plays as it is. A 4K remux
drawn 260 pixels tall comes as a 360p stream, not 60 GB.
"""
import time
import urllib.parse
import uuid

from ..registry import Unreachable
from . import labcommon as L

TICKS = 10_000_000                         # Jellyfin's RunTimeTicks: 100 ns
HEIGHTS = {"240p": (240, 450), "360p": (360, 900), "480p": (480, 1500), "576p": (576, 2000), "720p": (720, 3000),
           "1080p": (1080, 8000)}          # height, video kbit/s
DEVICE = "bromigos-den-tv"


def fit_height(height):
    """The smallest HEIGHTS key at least `height` pixels tall (1080p at most)."""
    for k, (h, _kbps) in sorted(HEIGHTS.items(), key=lambda kv: kv[1][0]):
        if h >= height:
            return k
    return "1080p"


def _quality(q, bitrate_kbps, max_mbps, height=None, source_height=None):
    """"direct" or a HEIGHTS key, for the asked quality, the item's bitrate and height, and
    the height it's drawn at (None: not sized)."""
    q = (q or "auto").lower()
    if q == "direct" or q not in HEIGHTS and q != "auto":
        return "direct"
    if q == "auto" and height:
        fit = fit_height(int(height))
        h, kbps = HEIGHTS[fit]
        small = bitrate_kbps and bitrate_kbps <= kbps * 3 and (not source_height or source_height <= h * 2)
        return "direct" if small else fit
    if q == "auto":
        return "direct" if not bitrate_kbps or bitrate_kbps <= max_mbps * 1000 else "480p"
    return q


def _year_ts(v):
    t = L.ts(v)
    return t if t is None else float(t)


class VideoServer:
    """What both servers share."""

    def video_direct_max(self):
        try:
            return float(self.opts.get("direct_max_mbps") or 20)
        except (TypeError, ValueError):
            return 20.0

    def playlists(self):
        """The server's video playlists: the `video` records whose kind is playlist."""
        return [v for v in self.video() if v["kind"] == "playlist"]

    def web_base(self):
        """The server's address for a browser: `web_url` when the desktop reaches it by
        another name (a public host name), else the endpoint."""
        return (self.opts.get("web_url") or self.endpoint or "").rstrip("/")


# ------------------------------------------------------------------ Jellyfin
class JellyfinVideo(VideoServer):
    FIELDS = "RunTimeTicks,ProductionYear,DateCreated,MediaSources,ParentId,SeriesName,ChildCount,RecursiveItemCount"

    def auth_headers(self):
        from .. import config
        tok = config.resolve(self.opts.get("auth_ref") or "")
        return {"Authorization": f'MediaBrowser Token="{tok}"'} if tok else {}

    def _token(self):
        from .. import config
        return config.resolve(self.opts.get("auth_ref") or "")

    def _user(self):
        """The user whose views and progress we read: `user`, else the first administrator."""
        hit = getattr(self, "_uid", None)
        if hit and time.time() - hit[1] < 3600:
            return hit[0]
        if not self._token():
            raise Unreachable(f"{self.name}: no API key (auth_ref) in homelab.toml")
        users = self.fetch("/Users", timeout=6) or []
        want = (self.opts.get("user") or "").lower()
        pick = next((u for u in users if want and (u.get("Name") or "").lower() == want), None)
        if pick is None:
            pick = next((u for u in users if (u.get("Policy") or {}).get("IsAdministrator")
                         and not (u.get("Policy") or {}).get("IsDisabled")), None) or (users[0] if users else None)
        if not pick:
            raise Unreachable(f"{self.name}: no users")
        self._uid = (pick["Id"], time.time())
        return pick["Id"]

    def _item(self, it):
        kind = {"Movie": "movie", "Episode": "episode"}.get(it.get("Type"), "video")
        src = (it.get("MediaSources") or [{}])[0]
        ud = it.get("UserData") or {}
        ticks = it.get("RunTimeTicks") or src.get("RunTimeTicks")
        return {"id": it.get("Id"), "title": it.get("Name") or "", "series": it.get("SeriesName"),
                "season": it.get("ParentIndexNumber"), "episode": it.get("IndexNumber"), "kind": kind,
                "duration": round(ticks / TICKS, 3) if ticks else None, "year": it.get("ProductionYear"),
                "poster": f"/Items/{it.get('Id')}/Images/Primary" if (it.get("ImageTags") or {}).get("Primary")
                else (f"/Items/{it.get('SeriesId')}/Images/Primary" if it.get("SeriesId") else None),
                "bitrate": int(src["Bitrate"] / 1000) if src.get("Bitrate") else None,
                "height": next((m.get("Height") for m in src.get("MediaStreams") or [] if m.get("Type") == "Video"),
                               None),
                "position": round((ud.get("PlaybackPositionTicks") or 0) / TICKS, 3) or None,
                "added": _year_ts(it.get("DateCreated")), "server": self.name}

    def video(self):
        uid = self._user()
        out = []
        for v in (self.fetch(f"/Users/{uid}/Views", timeout=6) or {}).get("Items") or []:
            ct = v.get("CollectionType")
            if ct not in ("movies", "tvshows", "homevideos", "musicvideos", "mixed", None):
                continue
            out.append({"name": v.get("Name"), "kind": "library", "id": v.get("Id"), "title": v.get("Name"),
                        "count": v.get("ChildCount"), "media": {"movies": "movies", "tvshows": "shows"}.get(ct, "mixed"),
                        "server": self.name})
        for t, kind in (("BoxSet", "collection"), ("Playlist", "playlist")):
            q = urllib.parse.urlencode({"IncludeItemTypes": t, "Recursive": "true", "Fields": "ChildCount"})
            for v in (self.fetch(f"/Users/{uid}/Items?{q}", timeout=6) or {}).get("Items") or []:
                if kind == "playlist" and v.get("MediaType") not in (None, "Video", "Unknown"):
                    continue
                out.append({"name": v.get("Name"), "kind": kind, "id": v.get("Id"), "title": v.get("Name"),
                            "count": v.get("ChildCount"), "media": "mixed", "server": self.name})
        return out

    def video_items(self, kind, id_, limit=5000):
        uid = self._user()
        base = {"Fields": self.FIELDS, "Limit": str(int(limit)), "EnableImages": "true"}
        if kind == "playlist":
            q = urllib.parse.urlencode(dict(base, UserId=uid))
            data = self.fetch(f"/Playlists/{id_}/Items?{q}", timeout=15) or {}
        else:
            q = urllib.parse.urlencode(dict(base, ParentId=id_, Recursive="true", IncludeItemTypes="Movie,Episode,Video",
                                            SortBy="SeriesSortName,ParentIndexNumber,IndexNumber,SortName",
                                            SortOrder="Ascending"))
            data = self.fetch(f"/Users/{uid}/Items?{q}", timeout=15) or {}
        return [self._item(i) for i in data.get("Items") or [] if i.get("Type") in ("Movie", "Episode", "Video")]

    def video_shows(self):
        uid = self._user()
        q = urllib.parse.urlencode({"IncludeItemTypes": "Series", "Recursive": "true", "SortBy": "SortName",
                                    "Fields": "ProductionYear,RecursiveItemCount,ChildCount", "EnableImages": "true"})
        return [{"id": v.get("Id"), "title": v.get("Name") or "", "year": v.get("ProductionYear"),
                 "poster": f"/Items/{v.get('Id')}/Images/Primary" if (v.get("ImageTags") or {}).get("Primary") else None,
                 "count": v.get("RecursiveItemCount") or v.get("ChildCount"), "kind": "show", "server": self.name}
                for v in (self.fetch(f"/Users/{uid}/Items?{q}", timeout=15) or {}).get("Items") or []]

    def video_show_items(self, id_):
        uid = self._user()
        q = urllib.parse.urlencode({"UserId": uid, "Fields": self.FIELDS, "EnableImages": "true"})
        data = self.fetch(f"/Shows/{id_}/Episodes?{q}", timeout=15)
        if data is None:
            raise LookupError(f"{self.name}: no series {id_}")
        return [self._item(i) for i in data.get("Items") or [] if i.get("Type") == "Episode"]

    def video_movies(self):
        uid = self._user()
        q = urllib.parse.urlencode({"IncludeItemTypes": "Movie", "Recursive": "true", "SortBy": "SortName",
                                    "Fields": self.FIELDS, "EnableImages": "true"})
        return [self._item(i) for i in (self.fetch(f"/Users/{uid}/Items?{q}", timeout=20) or {}).get("Items") or []]

    def video_item(self, id_):
        uid = self._user()
        it = self.fetch(f"/Users/{uid}/Items/{id_}", timeout=8)
        return self._item(it) if it and it.get("Id") else None

    def video_resume(self, limit=12):
        uid = self._user()
        q = urllib.parse.urlencode({"Limit": str(limit), "MediaTypes": "Video", "Fields": self.FIELDS})
        return [self._item(i) for i in (self.fetch(f"/Users/{uid}/Items/Resume?{q}", timeout=8) or {}).get("Items") or []]

    def video_latest(self, limit=12):
        uid = self._user()
        q = urllib.parse.urlencode({"Limit": str(limit), "Fields": self.FIELDS, "GroupItems": "true"})
        return [self._item(i) for i in self.fetch(f"/Users/{uid}/Items/Latest?{q}", timeout=8) or []]

    def video_stream(self, item, quality="auto", height=None):
        q = _quality(quality, item.get("bitrate"), self.video_direct_max(), height, item.get("height"))
        iid = item["id"]
        if q == "direct":
            url = f"{self.endpoint}/Videos/{iid}/stream?static=true&MediaSourceId={iid}"
        else:
            h, kbps = HEIGHTS[q]
            url = f"{self.endpoint}/Videos/{iid}/master.m3u8?" + urllib.parse.urlencode({
                "MediaSourceId": iid, "DeviceId": DEVICE, "PlaySessionId": uuid.uuid4().hex,
                "VideoCodec": "h264", "AudioCodec": "aac", "MaxHeight": str(h),
                "VideoBitrate": str(kbps * 1000), "AudioBitrate": "128000", "SegmentContainer": "ts"})
        return {"url": url, "headers": self.auth_headers(), "direct": q == "direct", "quality": q}

    def video_web(self, item):
        return f"{self.web_base()}/web/#/details?id={item['id']}"

    def video_poster(self, item):
        p = item.get("poster")
        return (f"{self.endpoint}{p}?fillHeight=360&quality=85", self.auth_headers()) if p else (None, {})


# ------------------------------------------------------------------ Plex
class PlexVideo(VideoServer):
    JSON = {"Accept": "application/json"}

    def auth_headers(self):
        from .. import config
        tok = config.resolve(self.opts.get("auth_ref") or "")
        return {"X-Plex-Token": tok} if tok else {}

    def _get(self, path, timeout=10):
        if not self.auth_headers():
            raise Unreachable(f"{self.name}: no token (auth_ref) in homelab.toml")
        return ((self.fetch(path, timeout=timeout, headers=self.JSON) or {}).get("MediaContainer") or {})

    def _machine(self):
        hit = getattr(self, "_mid", None)
        if hit:
            return hit
        self._mid = (self._get("/identity", timeout=5) or {}).get("machineIdentifier") or ""
        return self._mid

    def _item(self, m):
        t = m.get("type")
        media = (m.get("Media") or [{}])[0]
        part = (media.get("Part") or [{}])[0]
        dur = m.get("duration") or media.get("duration")
        title = m.get("title") or ""
        series = m.get("grandparentTitle") if t == "episode" else (m.get("parentTitle") if t == "season" else None)
        return {"id": str(m.get("ratingKey")), "title": title, "series": series,
                "season": m.get("parentIndex") if t == "episode" else (m.get("index") if t == "season" else None),
                "episode": m.get("index") if t == "episode" else None,
                "kind": {"movie": "movie", "episode": "episode", "season": "season", "show": "show"}.get(t, "video"),
                "duration": round(dur / 1000.0, 3) if dur else None, "year": m.get("year"),
                "poster": m.get("grandparentThumb") if t == "episode" and m.get("grandparentThumb") else (
                    m.get("thumb") or m.get("parentThumb")),
                "bitrate": media.get("bitrate"), "part": part.get("key"), "height": media.get("height"),
                "position": round((m.get("viewOffset") or 0) / 1000.0, 3) or None,
                "added": float(m["addedAt"]) if m.get("addedAt") else None, "server": self.name}

    def video(self):
        out = []
        for s in self._get("/library/sections").get("Directory") or []:
            if s.get("type") not in ("movie", "show"):
                continue
            out.append({"name": s.get("title"), "kind": "library", "id": str(s.get("key")), "title": s.get("title"),
                        "count": None, "media": "movies" if s.get("type") == "movie" else "shows", "server": self.name})
            for c in self._get(f"/library/sections/{s.get('key')}/collections").get("Metadata") or []:
                out.append({"name": c.get("title"), "kind": "collection", "id": str(c.get("ratingKey")),
                            "title": c.get("title"), "count": c.get("childCount"), "media": "mixed", "server": self.name})
        for p in self._get("/playlists?playlistType=video").get("Metadata") or []:
            out.append({"name": p.get("title"), "kind": "playlist", "id": str(p.get("ratingKey")), "title": p.get("title"),
                        "count": p.get("leafCount"), "media": "mixed", "server": self.name})
        return out

    def video_items(self, kind, id_, limit=5000):
        if kind == "library":
            secs = self._get("/library/sections").get("Directory") or []
            sec = next((s for s in secs if str(s.get("key")) == str(id_)), {})
            typ = 4 if sec.get("type") == "show" else 1            # episodes, or movies
            path = f"/library/sections/{id_}/all?type={typ}&sort=titleSort"
        elif kind == "collection":
            path = f"/library/collections/{id_}/children"
        else:
            path = f"/playlists/{id_}/items"
        sep = "&" if "?" in path else "?"
        data = self._get(f"{path}{sep}X-Plex-Container-Start=0&X-Plex-Container-Size={int(limit)}", timeout=20)
        items = [self._item(m) for m in data.get("Metadata") or []]
        if kind == "collection" and any(i["kind"] == "show" for i in items):      # a collection of shows: their episodes
            eps = []
            for i in items:
                if i["kind"] == "show":
                    eps += [self._item(m) for m in self._get(f"/library/metadata/{i['id']}/allLeaves").get("Metadata") or []]
                else:
                    eps.append(i)
            items = eps
        return [i for i in items if i["kind"] in ("movie", "episode", "video")]

    def _sections(self, typ):
        return [s for s in self._get("/library/sections").get("Directory") or [] if s.get("type") == typ]

    def video_shows(self):
        out = []
        for sec in self._sections("show"):
            for m in self._get(f"/library/sections/{sec.get('key')}/all?type=2", timeout=20).get("Metadata") or []:
                out.append({"id": str(m.get("ratingKey")), "title": m.get("title") or "", "year": m.get("year"),
                            "poster": m.get("thumb"), "count": m.get("leafCount"), "kind": "show", "server": self.name})
        return out

    def video_show_items(self, id_):
        data = self._get(f"/library/metadata/{id_}/allLeaves", timeout=20)
        if not data:
            raise LookupError(f"{self.name}: no show {id_}")
        return [self._item(m) for m in data.get("Metadata") or [] if m.get("type") == "episode"]

    def video_movies(self):
        out = []
        for sec in self._sections("movie"):
            out += [self._item(m) for m in self._get(f"/library/sections/{sec.get('key')}/all?type=1",
                                                     timeout=20).get("Metadata") or []]
        return out

    def video_item(self, id_):
        m = (self._get(f"/library/metadata/{id_}").get("Metadata") or [None])[0]
        return self._item(m) if m else None

    def video_resume(self, limit=12):
        return [self._item(m) for m in (self._get("/library/onDeck").get("Metadata") or [])[:limit]]

    def video_latest(self, limit=12):
        q = f"/library/recentlyAdded?X-Plex-Container-Start=0&X-Plex-Container-Size={int(limit)}"
        return [self._item(m) for m in self._get(q).get("Metadata") or []]

    def video_stream(self, item, quality="auto", height=None):
        q = _quality(quality, item.get("bitrate"), self.video_direct_max(), height, item.get("height"))
        if q == "direct" and item.get("part"):
            return {"url": f"{self.endpoint}{item['part']}", "headers": self.auth_headers(), "direct": True,
                    "quality": "direct"}
        if q == "direct":
            q = "1080p"
        h, kbps = HEIGHTS[q]
        # Plex picks a client profile by platform: "Chrome" is one every server knows (an
        # unknown product or client id gets 400 Bad Request)
        url = f"{self.endpoint}/video/:/transcode/universal/start.m3u8?" + urllib.parse.urlencode({
            "path": f"/library/metadata/{item['id']}", "mediaIndex": "0", "partIndex": "0", "protocol": "hls",
            "offset": "0", "copyts": "1", "fastSeek": "1", "videoResolution": f"{h * 16 // 9}x{h}",
            "maxVideoBitrate": str(kbps), "session": uuid.uuid4().hex, "X-Plex-Platform": "Chrome"})
        return {"url": url, "headers": self.auth_headers(), "direct": False, "quality": q}

    def video_web(self, item):
        key = urllib.parse.quote(f"/library/metadata/{item['id']}", safe="")
        mid = ""
        try:
            mid = self._machine()
        except Exception:
            pass
        return f"{self.web_base()}/web/index.html#!/server/{mid}/details?key={key}"

    def video_poster(self, item):
        p = item.get("poster")
        if not p:
            return None, {}
        q = urllib.parse.urlencode({"width": "240", "height": "360", "minSize": "1", "upscale": "1", "url": p})
        return f"{self.endpoint}/photo/:/transcode?{q}", self.auth_headers()
