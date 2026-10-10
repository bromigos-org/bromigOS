"""Stand-in Jellyfin and Plex servers for the den TV's tests: generated data, never real
media, on 127.0.0.1, every request written down.

    srv = FakeJellyfin(clip="test.mp4", poster="poster.png")   # or FakePlex(...)
    srv.url, srv.key, srv.seen                                   # its address, its key, [(path, headers)]
    srv.close()

Each has two shows ("Test Card": 3 episodes, "Night Shift": 2), two movies, a "Shows"
and a "Movies" library and a collection. Every episode and movie is `clip` (its length
is the clip's, CLIP seconds): a stream request answers with it, a transcode request
(Jellyfin's master.m3u8, Plex's start.m3u8) with a one-segment HLS playlist of it, so
mpv plays either. Images answer with `poster`.
"""
import json
import threading
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

CLIP = 120
TICKS = 10_000_000
SHOWS = {"s1": ("Test Card", ["ep0", "ep1", "ep2"]), "s2": ("Night Shift", ["ns0", "ns1"])}
MOVIES = {"m1": "Colour Bars", "m2": "Tone"}


class _Base:
    key = "test-key"

    def __init__(self, clip=None, poster=None, bitrate_kbps=800, height=360, codec="h264", bit_depth=8):
        self.clip = open(clip, "rb").read() if clip else b"\0" * 1024
        self.poster = open(poster, "rb").read() if poster else b""
        self.bitrate = bitrate_kbps
        self.height = height
        self.codec, self.bit_depth = codec, bit_depth
        self.seen = []
        self.stopped = []                     # DELETE /Videos/ActiveEncodings… (Jellyfin), stop?session=… (Plex)
        me = self

        class H(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, *a):
                pass

            def send(self, code, body, ctype="application/json", extra=None):
                if isinstance(body, (dict, list)):
                    body = json.dumps(body).encode()
                self.send_response(code)
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(len(body)))
                for k, v in (extra or {}).items():
                    self.send_header(k, v)
                self.end_headers()
                if self.command != "HEAD":
                    try:
                        self.wfile.write(body)
                    except OSError:
                        pass

            def video(self):
                data = me.clip
                rng = self.headers.get("Range")
                if rng and rng.startswith("bytes="):
                    a, _, b = rng[6:].partition("-")
                    a = int(a or 0)
                    b = int(b) if b else len(data) - 1
                    return self.send(206, data[a:b + 1], "video/mp4",
                                     {"Content-Range": f"bytes {a}-{b}/{len(data)}", "Accept-Ranges": "bytes"})
                return self.send(200, data, "video/mp4", {"Accept-Ranges": "bytes"})

            def hls(self):
                body = (f"#EXTM3U\n#EXT-X-VERSION:3\n#EXT-X-TARGETDURATION:{CLIP}\n#EXT-X-PLAYLIST-TYPE:VOD\n"
                        f"#EXTINF:{CLIP}.0,\n/clip.mp4\n#EXT-X-ENDLIST\n").encode()
                return self.send(200, body, "application/vnd.apple.mpegurl")

            def do_HEAD(self):
                self.do_GET()

            def do_DELETE(self):
                me.seen.append((self.path, dict(self.headers)))
                me.stopped.append(self.path)
                return self.send(204, b"")

            def do_GET(self):
                me.seen.append((self.path, dict(self.headers)))
                u = urllib.parse.urlparse(self.path)
                q = dict(urllib.parse.parse_qsl(u.query))
                if u.path == "/clip.mp4":
                    return self.video()
                return me.answer(self, u.path, q)
        self.srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self.url = f"http://127.0.0.1:{self.srv.server_port}"

    def close(self):
        self.srv.shutdown()
        self.srv.server_close()

    def requests(self, part):
        """The paths asked for that contain `part`."""
        return [p for p, _h in self.seen if part in p]

    def opens(self):
        """Every stream opened: a direct file, or a transcode's playlist."""
        return [p for p, _h in self.seen if "/stream?" in p or "master.m3u8" in p or "start.m3u8" in p
                or p.startswith("/library/parts/")]


class FakeJellyfin(_Base):
    type = "jellyfin"

    def _ep(self, sid, n, eid):
        return {"Name": f"Episode {n + 1}", "Id": eid, "Type": "Episode", "SeriesName": SHOWS[sid][0],
                "SeriesId": sid, "ParentIndexNumber": 1, "IndexNumber": n + 1, "RunTimeTicks": CLIP * TICKS,
                "ImageTags": {"Primary": "p"},
                "MediaSources": [{"Id": eid, "Bitrate": self.bitrate * 1000,
                                  "MediaStreams": [{"Type": "Video", "Height": self.height, "Codec": self.codec,
                                                    "BitDepth": self.bit_depth}]}]}

    def _movie(self, mid):
        return {"Name": MOVIES[mid], "Id": mid, "Type": "Movie", "ProductionYear": 2001, "RunTimeTicks": CLIP * TICKS,
                "ImageTags": {"Primary": "p"},
                "MediaSources": [{"Id": mid, "Bitrate": self.bitrate * 1000,
                                  "MediaStreams": [{"Type": "Video", "Height": self.height, "Codec": self.codec,
                                                    "BitDepth": self.bit_depth}]}]}

    def answer(self, h, path, q):
        if h.headers.get("Authorization") != f'MediaBrowser Token="{self.key}"' and not path.endswith("/Primary"):
            return h.send(401, {})
        if path.startswith("/Videos/") and path.endswith("/stream"):
            return h.video()
        if path.startswith("/Videos/") and path.endswith("/master.m3u8"):
            if "StartTimeTicks" in q:                  # as Jellyfin 10.11: such a playlist's segments all fail
                return h.send(400, b"Error processing request.", "text/plain")
            return h.hls()
        if path.endswith("/Images/Primary"):
            return h.send(200, self.poster, "image/png")
        eps = [self._ep(sid, n, e) for sid, (_t, es) in SHOWS.items() for n, e in enumerate(es)]
        if path == "/Users":
            return h.send(200, [{"Name": "admin", "Id": "u1", "Policy": {"IsAdministrator": True}}])
        if path == "/System/Info/Public":
            return h.send(200, {"ProductName": "Jellyfin Server", "Version": "10.11.0"})
        if path == "/Users/u1/Views":
            return h.send(200, {"Items": [{"Name": "Shows", "Id": "lib1", "CollectionType": "tvshows"},
                                          {"Name": "Movies", "Id": "lib2", "CollectionType": "movies"}]})
        if path.startswith("/Shows/") and path.endswith("/Episodes"):
            sid = path.split("/")[2]
            if sid not in SHOWS:
                return h.send(404, {})
            return h.send(200, {"Items": [e for e in eps if e["SeriesId"] == sid]})
        if path.startswith("/Users/u1/Items/"):
            iid = path.rsplit("/", 1)[-1]
            hit = next((e for e in eps if e["Id"] == iid), None) or (self._movie(iid) if iid in MOVIES else None)
            return h.send(200, hit) if hit else h.send(404, {})
        if path == "/Users/u1/Items":
            t = q.get("IncludeItemTypes", "")
            if t == "Series":
                return h.send(200, {"Items": [{"Name": name, "Id": sid, "Type": "Series", "ProductionYear": 2020,
                                               "RecursiveItemCount": len(es), "ImageTags": {"Primary": "p"}}
                                              for sid, (name, es) in SHOWS.items()]})
            if t == "Movie":
                return h.send(200, {"Items": [self._movie(m) for m in MOVIES]})
            if t == "BoxSet":
                return h.send(200, {"Items": [{"Name": "Marathon", "Id": "c1", "ChildCount": 2}]})
            if t == "Playlist":
                return h.send(200, {"Items": []})
            if q.get("ParentId") == "lib1":
                return h.send(200, {"Items": eps})
            if q.get("ParentId") == "lib2":
                return h.send(200, {"Items": [self._movie(m) for m in MOVIES]})
            if q.get("ParentId") == "c1":
                return h.send(200, {"Items": [self._movie(m) for m in MOVIES]})
            return h.send(200, {"Items": []})
        return h.send(404, {})


class FakePlex(_Base):
    type = "plex"

    def _ep(self, sid, n, eid):
        return {"ratingKey": eid, "type": "episode", "title": f"Episode {n + 1}", "grandparentTitle": SHOWS[sid][0],
                "grandparentRatingKey": sid, "parentIndex": 1, "index": n + 1, "duration": CLIP * 1000,
                "thumb": f"/library/metadata/{eid}/thumb",
                "Media": [{"bitrate": self.bitrate, "height": self.height, "videoCodec": self.codec,
                           "videoProfile": "main 10" if self.bit_depth > 8 else "high",
                           "Part": [{"key": f"/library/parts/{eid}/file.mp4"}]}]}

    def _movie(self, mid):
        return {"ratingKey": mid, "type": "movie", "title": MOVIES[mid], "year": 2001, "duration": CLIP * 1000,
                "thumb": f"/library/metadata/{mid}/thumb",
                "Media": [{"bitrate": self.bitrate, "height": self.height, "videoCodec": self.codec,
                           "videoProfile": "main 10" if self.bit_depth > 8 else "high",
                           "Part": [{"key": f"/library/parts/{mid}/file.mp4"}]}]}

    def answer(self, h, path, q):
        if h.headers.get("X-Plex-Token") != self.key and q.get("X-Plex-Token") != self.key:
            return h.send(401, {})
        mc = lambda d: h.send(200, {"MediaContainer": d})  # noqa: E731
        eps = [self._ep(sid, n, e) for sid, (_t, es) in SHOWS.items() for n, e in enumerate(es)]
        if path.startswith("/library/parts/"):
            return h.video()
        if path == "/video/:/transcode/universal/start.m3u8":
            return h.hls()
        if path == "/video/:/transcode/universal/stop":
            self.stopped.append(path + "?" + urllib.parse.urlencode(q))
            return mc({})
        if path.endswith("/thumb") or path == "/photo/:/transcode":
            return h.send(200, self.poster, "image/png")
        if path == "/identity":
            return mc({"machineIdentifier": "fake"})
        if path == "/library/sections":
            return mc({"Directory": [{"key": "1", "type": "show", "title": "Shows"},
                                     {"key": "2", "type": "movie", "title": "Movies"}]})
        if path == "/library/sections/1/all":
            if q.get("type") == "2":
                return mc({"Metadata": [{"ratingKey": sid, "type": "show", "title": name, "year": 2020,
                                         "leafCount": len(es), "thumb": f"/library/metadata/{sid}/thumb"}
                                        for sid, (name, es) in SHOWS.items()]})
            return mc({"Metadata": eps})
        if path == "/library/sections/2/all":
            return mc({"Metadata": [self._movie(m) for m in MOVIES]})
        if path.endswith("/collections"):
            return mc({"Metadata": [{"ratingKey": "c1", "title": "Marathon", "childCount": 2}]} if "/2/" in path
                      else {"Metadata": []})
        if path == "/library/collections/c1/children":
            return mc({"Metadata": [self._movie(m) for m in MOVIES]})
        if path == "/playlists":
            return mc({"Metadata": []})
        if path.startswith("/library/metadata/") and path.endswith("/allLeaves"):
            sid = path.split("/")[3]
            if sid not in SHOWS:
                return h.send(404, {})
            return mc({"Metadata": [e for e in eps if e["grandparentRatingKey"] == sid]})
        if path.startswith("/library/metadata/"):
            iid = path.split("/")[3]
            hit = next((e for e in eps if e["ratingKey"] == iid), None) or (self._movie(iid) if iid in MOVIES else None)
            return mc({"Metadata": [hit]}) if hit else h.send(404, {})
        return h.send(404, {})


def homelab_toml(path, *servers):
    """A homelab.toml with each fake server as a source (keys in files beside it)."""
    import os
    lines = []
    for n, s in enumerate(servers):
        key = os.path.join(os.path.dirname(path), f"{s.type}-key-{n}")
        with open(key, "w") as f:
            f.write(s.key + "\n")
        os.chmod(key, 0o600)
        lines.append(f'[[source]]\ntype = "{s.type}"\nendpoint = "{s.url}"\nauth_ref = "@file:{key}"\n')
    with open(path, "w") as f:
        f.write("\n".join(lines))
    return path
