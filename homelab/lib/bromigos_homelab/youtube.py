"""YouTube playlists in your media server: `bromigos lab youtube sync`.

Pinchflat downloads YouTube channels and playlists into the media library. A downloaded
playlist lands as a folder of numbered videos: Pinchflat's playlist media profile names each
file `Season 1/s01eNNN - title [id].ext`, where NNN is its place in the YouTube playlist. This
sync turns each of those folders into a real, ordered playlist in Jellyfin, Plex, or both, so
a playlist plays in its order on any screen.

What it does, for every Pinchflat source that is a playlist:
  1. reads the source's videos from Pinchflat (its OPML list of sources, then each source's feed);
  2. finds those videos in the media server's YouTube library, by the YouTube id in the file
     name (`[dQw4w9WgXcQ]`), preferring the copy in the source's own folder;
  3. orders them by the episode number in the file name (the playlist position);
  4. creates a playlist named after the source, or brings the existing one up to date: it adds
     what's missing, removes what left the YouTube playlist, and moves what's out of place.

It is idempotent: a second run changes nothing. `--dry-run` says what it would do and
changes nothing. It never deletes a playlist, and it only touches playlists named after a
Pinchflat playlist source (with `prefix`, if one is set).

Configuration (the first that has a value wins):
  * the command line: --server, --library, --prefix, --source;
  * the environment, for the copy the provisioner runs on the lab as a timer:
      PINCHFLAT_URL, PINCHFLAT_ROUTE_TOKEN, PINCHFLAT_AUTH ("user:password", optional),
      JELLYFIN_URL, JELLYFIN_TOKEN, JELLYFIN_USER (optional), PLEX_URL, PLEX_TOKEN,
      YOUTUBE_LIBRARY ("YouTube"), YOUTUBE_PLAYLIST_PREFIX ("");
  * homelab.toml, on the desktop: the first source of type pinchflat, jellyfin and plex (each
    server's API key in token_ref, or auth_ref), and a [youtube] table:
      [youtube]
      library = "YouTube"       # the media server library Pinchflat downloads into
      prefix = ""               # put before each playlist's name, such as "YT: "
      jellyfin_user = ""        # whose playlists they are in Jellyfin (default: the first admin)

This file uses the standard library only and needs nothing else from bromigOS, so the
provisioner can run it on the lab as it is:  python3 youtube.py sync
"""
import argparse
import base64
import email.utils
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

LIBRARY = "YouTube"
YT_ID = re.compile(r"(?:[?&]v=|youtu\.be/|/shorts/|/live/)([A-Za-z0-9_-]{11})")
ID_IN_PATH = re.compile(r"\[([A-Za-z0-9_-]{11})\](?=[^/\\]*$)")
SXXEYY = re.compile(r"[sS](\d{1,4})[eE](\d{1,6})")
FEED_UUID = re.compile(r"/sources/([0-9a-fA-F-]{36})/feed")


# ------------------------------------------------------------------ Pinchflat's feeds
def source_kind(url):
    """"playlist" for a YouTube playlist's URL, else "channel"."""
    u = str(url or "")
    return "playlist" if "list=" in u or "/playlist" in u else "channel"


def video_id(url):
    m = YT_ID.search(str(url or ""))
    return m.group(1) if m else None


def parse_opml(text):
    """[{name, feed, uuid}] from Pinchflat's OPML list of sources."""
    root = ET.fromstring(text.encode() if isinstance(text, str) else text)
    out = []
    for o in root.iter("outline"):
        feed = o.get("xmlUrl")
        if not feed:
            continue
        m = FEED_UUID.search(feed)
        out.append({"name": o.get("text") or o.get("title") or "", "feed": feed, "uuid": m.group(1) if m else None})
    return out


def parse_feed(text):
    """A source's podcast feed: {name, link, kind, items: [{title, link, id, at}]}, newest
    first as Pinchflat writes it. `at` is the video's upload time (unix seconds)."""
    root = ET.fromstring(text.encode() if isinstance(text, str) else text)
    ch = root.find("channel")
    if ch is None:
        raise ValueError("not an RSS feed")
    items = []
    for it in ch.findall("item"):
        link = (it.findtext("link") or "").strip()
        at = None
        try:
            at = email.utils.parsedate_to_datetime(it.findtext("pubDate") or "").timestamp()
        except (TypeError, ValueError):
            pass
        row = {"title": (it.findtext("title") or "").strip(), "link": link, "id": video_id(link), "at": at}
        enclosure = it.find("enclosure")
        if enclosure is not None and enclosure.get("url"):
            row["download"] = enclosure.get("url")
        duration = it.findtext("{http://www.itunes.com/dtds/podcast-1.0.dtd}duration")
        if duration:
            try:
                seconds = 0
                for part in duration.split(":"): seconds = seconds * 60 + float(part)
                row["duration"] = seconds
            except ValueError: pass
        items.append(row)
    link = (ch.findtext("link") or "").strip()
    return {"name": (ch.findtext("title") or "").strip(), "link": link, "kind": source_kind(link), "items": items}


# ------------------------------------------------------------------ HTTP
class Http:
    def __init__(self, base, headers=None, timeout=30):
        self.base = (base or "").rstrip("/")
        self.headers = dict(headers or {})
        self.timeout = timeout

    def call(self, method, path, params=None, body=None, raw=False):
        url = self.base + path
        if params:
            url += ("&" if "?" in url else "?") + urllib.parse.urlencode(
                {k: v for k, v in params.items() if v is not None}, safe=",:/")
        h = dict(self.headers)
        data = None
        if body is not None:
            data = json.dumps(body).encode()
            h["Content-Type"] = "application/json"
        req = urllib.request.Request(url, data=data, headers=h, method=method)
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as r:
                b = r.read()
        except urllib.error.HTTPError as e:
            raise SyncError(f"{method} {path}: HTTP {e.code}") from None
        except (OSError, ValueError) as e:
            raise SyncError(f"{self.base}: {e}") from None
        if raw:
            return b
        return json.loads(b) if b.strip() else None

    def get(self, path, **kw):
        return self.call("GET", path, **kw)


class SyncError(Exception):
    pass


class Pinchflat:
    def __init__(self, url, route_token, auth=None):
        if not url:
            raise SyncError("no Pinchflat: set PINCHFLAT_URL, or a source of type pinchflat in homelab.toml")
        if not route_token:
            raise SyncError("no route token for Pinchflat's list of sources: PINCHFLAT_ROUTE_TOKEN, or the "
                            "pinchflat source's route_token_ref (the route_token in the OPML link on its Sources page)")
        h = {"Authorization": "Basic " + base64.b64encode(auth.encode()).decode()} if auth else {}
        self.http, self.token = Http(url, h), route_token

    def sources(self):
        """[{name, kind, link, uuid, items}] for every source, its feed read."""
        out = []
        for s in parse_opml(self.http.get("/sources/opml.xml", params={"route_token": self.token}, raw=True)):
            path = f"/sources/{s['uuid']}/feed.xml" if s.get("uuid") else s["feed"]
            f = parse_feed(self.http.get(path, raw=True))
            out.append(dict(f, name=s["name"] or f["name"], uuid=s.get("uuid")))
        return out


# ------------------------------------------------------------------ media servers
# Each client offers the same five calls over its own API:
#   videos()                -> [{key, path, season, episode, title}] in the YouTube library
#   playlists()             -> {name: playlist id}
#   entries(pid)            -> [{key, entry}] in playlist order (entry: the playlist's own id for it)
#   create(name, keys)      -> playlist id
#   add(pid, keys); remove(pid, entries); move(pid, entries, key, index)
# TODO: when the media servers' adapters (the `video` capability) carry their own clients, use
# theirs and keep only the sync here.
class Jellyfin:
    kind = "jellyfin"

    def __init__(self, url, token, library=LIBRARY, user=None):
        if not token:
            raise SyncError("Jellyfin needs an API key (Dashboard › API Keys): JELLYFIN_TOKEN, or token_ref")
        self.http = Http(url, {"Authorization": f'MediaBrowser Token="{token}"', "Accept": "application/json"})
        self.library, self.user = library, user
        self._uid = None

    def uid(self):
        if not self._uid:
            users = self.http.get("/Users") or []
            want = [u for u in users if self.user and u.get("Name", "").lower() == self.user.lower()]
            admins = [u for u in users if (u.get("Policy") or {}).get("IsAdministrator")]
            pick = (want or admins or users or [None])[0]
            if not pick:
                raise SyncError("Jellyfin has no users")
            self._uid = pick["Id"]
        return self._uid

    def _library_id(self):
        for f in self.http.get("/Library/VirtualFolders") or []:
            if f.get("Name", "").lower() == self.library.lower():
                return f["ItemId"]
        raise SyncError(f"Jellyfin has no library named {self.library!r}")

    def videos(self):
        d = self.http.get("/Items", params={"ParentId": self._library_id(), "Recursive": "true", "Fields": "Path",
                                            "IncludeItemTypes": "Episode,Movie,Video", "userId": self.uid()}) or {}
        return [{"key": i["Id"], "path": i.get("Path") or "", "season": i.get("ParentIndexNumber"),
                 "episode": i.get("IndexNumber"), "title": i.get("Name")} for i in d.get("Items") or []]

    def playlists(self):
        d = self.http.get("/Items", params={"IncludeItemTypes": "Playlist", "Recursive": "true", "userId": self.uid()}) or {}
        return {i["Name"]: i["Id"] for i in d.get("Items") or []}

    def entries(self, pid):
        d = self.http.get(f"/Playlists/{pid}/Items", params={"userId": self.uid()}) or {}
        return [{"key": i["Id"], "entry": i.get("PlaylistItemId") or i["Id"]} for i in d.get("Items") or []]

    def create(self, name, keys):
        d = self.http.call("POST", "/Playlists", body={"Name": name, "Ids": list(keys), "UserId": self.uid(),
                                                         "MediaType": "Video"}) or {}
        return d.get("Id")

    def add(self, pid, keys):
        self.http.call("POST", f"/Playlists/{pid}/Items", params={"ids": ",".join(keys), "userId": self.uid()})

    def remove(self, pid, entries):
        self.http.call("DELETE", f"/Playlists/{pid}/Items", params={"entryIds": ",".join(entries)})

    def move(self, pid, entries, key, index):
        self.http.call("POST", f"/Playlists/{pid}/Items/{key}/Move/{index}")


class Plex:
    kind = "plex"

    def __init__(self, url, token, library=LIBRARY):
        if not token:
            raise SyncError("Plex needs a token (the X-Plex-Token of a signed-in account): PLEX_TOKEN, or token_ref")
        self.http = Http(url, {"X-Plex-Token": token, "Accept": "application/json"})
        self.library = library
        self._mid = None

    def _mc(self, path, **kw):
        return (self.http.get(path, **kw) or {}).get("MediaContainer") or {}

    def _machine(self):
        if not self._mid:
            self._mid = self._mc("/identity").get("machineIdentifier")
        return self._mid

    def _uri(self, keys):
        return f"server://{self._machine()}/com.plexapp.plugins.library/library/metadata/{','.join(keys)}"

    def videos(self):
        sec = next((d for d in self._mc("/library/sections").get("Directory") or []
                    if d.get("title", "").lower() == self.library.lower()), None)
        if not sec:
            raise SyncError(f"Plex has no library named {self.library!r}")
        typ = {"show": 4, "movie": 1}.get(sec.get("type"), 4)        # episodes, or movies
        out = []
        for m in self._mc(f"/library/sections/{sec['key']}/all", params={"type": typ}).get("Metadata") or []:
            part = ((m.get("Media") or [{}])[0].get("Part") or [{}])[0]
            out.append({"key": str(m["ratingKey"]), "path": part.get("file") or "", "season": m.get("parentIndex"),
                        "episode": m.get("index"), "title": m.get("title")})
        return out

    def playlists(self):
        return {m["title"]: str(m["ratingKey"]) for m in self._mc("/playlists", params={"playlistType": "video"}).get(
            "Metadata") or [] if not m.get("smart")}

    def entries(self, pid):
        return [{"key": str(m["ratingKey"]), "entry": str(m.get("playlistItemID"))}
                for m in self._mc(f"/playlists/{pid}/items").get("Metadata") or []]

    def create(self, name, keys):
        d = (self.http.call("POST", "/playlists", params={"type": "video", "title": name, "smart": 0,
                                                          "uri": self._uri(keys)}) or {}).get("MediaContainer") or {}
        return str(((d.get("Metadata") or [{}])[0]).get("ratingKey"))

    def add(self, pid, keys):
        self.http.call("PUT", f"/playlists/{pid}/items", params={"uri": self._uri(keys)})

    def remove(self, pid, entries):
        for e in entries:
            self.http.call("DELETE", f"/playlists/{pid}/items/{e}")

    def move(self, pid, entries, key, index):
        by = {x["key"]: x["entry"] for x in entries}
        after = entries[index - 1]["key"] if index > 0 else None
        self.http.call("PUT", f"/playlists/{pid}/items/{by[key]}/move",
                       params={"after": by[after]} if after else None)


# ------------------------------------------------------------------ the plan
def _order(v, fallback):
    m = None
    for m in SXXEYY.finditer(v["path"] or ""):
        pass
    if m:
        return (0, int(m.group(1)), int(m.group(2)))
    if v.get("episode") is not None:
        return (0, int(v.get("season") or 0), int(v["episode"]))
    return (1, fallback, 0)


def desired(source, videos):
    """The media server's keys for a source's videos, in playlist order."""
    by_id = {}
    for v in videos:
        m = ID_IN_PATH.search(v["path"] or "")
        if m:
            by_id.setdefault(m.group(1), []).append(v)
    folder = "/" + source["name"].lower() + "/"
    picked, seen = [], set()
    n = len(source["items"])
    for pos, it in enumerate(source["items"]):
        cands = by_id.get(it.get("id")) or []
        if not cands:
            continue
        v = next((c for c in cands if folder in (c["path"] or "").replace("\\", "/").lower()), cands[0])
        if v["key"] in seen:
            continue
        seen.add(v["key"])
        picked.append((_order(v, n - pos), v["key"]))      # the feed is newest first: oldest first without numbers
    return [k for _, k in sorted(picked)]


def steps(current, want):
    """(remove: [entry], add: [key], moves: [(key, index)]) to turn current [{key, entry}] into want
    [key]. Moves are applied in order, each to the index it names."""
    wanted = set(want)
    seen, remove, keep = set(), [], []
    for e in current:
        if e["key"] not in wanted or e["key"] in seen:
            remove.append(e["entry"])
        else:
            keep.append(e["key"])
            seen.add(e["key"])
    add = [k for k in want if k not in seen]
    sim, moves = keep + add, []
    for i, k in enumerate(want):
        if sim[i] != k:
            sim.remove(k)
            sim.insert(i, k)
            moves.append((k, i))
    return remove, add, moves


def sync_server(server, sources, prefix="", dry_run=False):
    """[{server, playlist, action, items, added, removed, moved, detail}] for one media server."""
    out = []
    videos = server.videos()
    existing = server.playlists()
    for src in sources:
        name = prefix + src["name"]
        rec = {"server": server.kind, "playlist": name, "action": "ok", "items": 0, "added": 0, "removed": 0,
               "moved": 0, "detail": ""}
        want = desired(src, videos)
        rec["items"] = len(want)
        if not want:
            rec.update(action="skip", detail=f"none of its {len(src['items'])} videos is in the library yet")
            out.append(rec)
            continue
        pid = existing.get(name)
        if not pid:
            rec.update(action="create", added=len(want))
            if not dry_run:
                pid = server.create(name, want)
                cur = server.entries(pid)
                if [e["key"] for e in cur] != want:          # a server that didn't keep the order
                    _apply(server, pid, cur, want)
            out.append(rec)
            continue
        cur = server.entries(pid)
        remove, add, moves = steps(cur, want)
        rec.update(added=len(add), removed=len(remove), moved=len(moves))
        if remove or add or moves:
            rec["action"] = "update"
            if not dry_run:
                _apply(server, pid, cur, want)
        out.append(rec)
    return out


def _apply(server, pid, cur, want):
    remove, add, _ = steps(cur, want)
    if remove:
        server.remove(pid, remove)
    if add:
        server.add(pid, add)
    if remove or add:
        cur = server.entries(pid)
    _, _, moves = steps(cur, want)
    for key, index in moves:
        sim = [e for e in cur if e["key"] != key]
        sim.insert(index, next(e for e in cur if e["key"] == key))
        server.move(pid, sim, key, index)
        cur = sim


# ------------------------------------------------------------------ configuration
def _homelab():
    """(sources by type, [youtube] settings) from homelab.toml, or ({}, {}) without bromigOS."""
    try:
        from bromigos_homelab import config
    except ImportError:
        return {}, {}
    by = {}
    for s in config.sources():
        by.setdefault(s.get("type"), s)
    return by, config.table("youtube")


def settings(args):
    by, yt = _homelab()

    def ref(src, *keys):
        if not src:
            return ""
        try:
            from bromigos_homelab import config
        except ImportError:
            return ""
        for k in keys:
            v = config.resolve(src.get(k) or "")
            if v:
                return v
        return ""
    env = os.environ.get
    pf, jf, px = by.get("pinchflat"), by.get("jellyfin"), by.get("plex")
    return {
        "pinchflat": {"url": env("PINCHFLAT_URL") or (pf or {}).get("endpoint"),
                      "token": env("PINCHFLAT_ROUTE_TOKEN") or ref(pf, "route_token_ref"),
                      "auth": env("PINCHFLAT_AUTH") or ref(pf, "auth_ref")},
        "jellyfin": {"url": env("JELLYFIN_URL") or (jf or {}).get("endpoint"),
                     "token": env("JELLYFIN_TOKEN") or ref(jf, "token_ref", "auth_ref"),
                     "user": env("JELLYFIN_USER") or yt.get("jellyfin_user")},
        "plex": {"url": env("PLEX_URL") or (px or {}).get("endpoint"),
                 "token": env("PLEX_TOKEN") or ref(px, "token_ref", "auth_ref")},
        "library": args.library or env("YOUTUBE_LIBRARY") or yt.get("library") or LIBRARY,
        "prefix": args.prefix if args.prefix is not None else env("YOUTUBE_PLAYLIST_PREFIX", yt.get("prefix") or ""),
    }


def servers(cfg, only=()):
    out = []
    for kind in ("jellyfin", "plex"):
        c = cfg[kind]
        if only and kind not in only:
            continue
        if not c["url"]:
            if only:
                raise SyncError(f"no {kind}: set {kind.upper()}_URL, or a source of type {kind} in homelab.toml")
            continue
        out.append(Jellyfin(c["url"], c["token"], cfg["library"], c.get("user")) if kind == "jellyfin"
                   else Plex(c["url"], c["token"], cfg["library"]))
    if not out:
        raise SyncError("no media server: set JELLYFIN_URL or PLEX_URL, or a jellyfin or plex source in homelab.toml")
    return out


def run(args):
    cfg = settings(args)
    pf = Pinchflat(cfg["pinchflat"]["url"], cfg["pinchflat"]["token"], cfg["pinchflat"]["auth"])
    srcs = [s for s in pf.sources() if s["kind"] == "playlist"]
    if args.source:
        want = {n.lower() for n in args.source}
        srcs = [s for s in srcs if s["name"].lower() in want]
    report, errors = [], {}
    for srv in servers(cfg, tuple(args.server or ())):
        try:
            report += sync_server(srv, srcs, cfg["prefix"], args.dry_run)
        except SyncError as e:
            errors[srv.kind] = str(e)
    return {"dry_run": bool(args.dry_run), "playlists": len(srcs), "report": report, "errors": errors}


def main(argv=None):
    p = argparse.ArgumentParser(prog="bromigos lab youtube",
                                description="Turn Pinchflat's downloaded YouTube playlists into ordered playlists "
                                            "in Jellyfin and Plex.")
    sub = p.add_subparsers(dest="verb")
    s = sub.add_parser("sync", help="create or update the playlists (idempotent)")
    s.add_argument("--dry-run", action="store_true", help="say what would change; change nothing")
    s.add_argument("--json", action="store_true")
    s.add_argument("--server", action="append", choices=("jellyfin", "plex"), help="only this server (repeat)")
    s.add_argument("--library", help=f"the media server's YouTube library (default {LIBRARY!r})")
    s.add_argument("--prefix", help="put before each playlist's name")
    s.add_argument("--source", action="append", help="only this Pinchflat source (repeat)")
    a = p.parse_args(argv)
    if a.verb != "sync":
        p.print_help(sys.stderr)
        return 2
    try:
        doc = run(a)
    except SyncError as e:
        print(f"youtube sync: {e}", file=sys.stderr)
        return 3
    if a.json:
        print(json.dumps(doc, indent=1))
    else:
        verb = {"create": "would create" if a.dry_run else "created",
                "update": "would update" if a.dry_run else "updated", "ok": "up to date", "skip": "skipped"}
        if not doc["report"] and not doc["errors"]:
            print("No playlist sources in Pinchflat yet.")
        for r in doc["report"]:
            bits = [f"{r['items']} videos"] + [f"{r[k]} {k}" for k in ("added", "removed", "moved")
                                                if r[k] and r["action"] != "create"]
            print(f"{r['server']:<9} {r['playlist'][:48]:<48} {verb[r['action']]:<13} {' · '.join(bits)}"
                  + (f"  ({r['detail']})" if r["detail"] else ""))
        for k, e in doc["errors"].items():
            print(f"{k:<9} failed: {e}", file=sys.stderr)
    return 1 if doc["errors"] else 0


if __name__ == "__main__":
    sys.exit(main())
