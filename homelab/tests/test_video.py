"""The media servers' video libraries (adapters/labvideo.py: the `video` capability) against
fake Jellyfin and Plex servers on this machine, answering from recorded shapes
(tests/fixtures/video-servers.json, made up: no real library). No network.

    PYTHONPATH=lib python -m unittest discover -s tests

- the libraries, collections and playlists each server offers (music left out), and its
  playlists by themselves;
- a library's items (episodes, not series) with their lengths, a collection's (a show's
  episodes), a playlist's in its order; continue watching and recently added;
- a stream: direct, or a transcode over a bitrate, with the key in a header (never the URL);
- the web page, the poster; a server with no key says so, without asking it anything.
"""
import json
import os
import tempfile
import threading
import unittest
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from bromigos_homelab import caps, config, registry
from bromigos_homelab.adapters import labmedia

HERE = os.path.dirname(os.path.abspath(__file__))
with open(os.path.join(HERE, "fixtures", "video-servers.json")) as _f:
    FX = json.load(_f)


class Fake(BaseHTTPRequestHandler):
    answers, token_header, token, seen = {}, "", "", []

    def log_message(self, *a):
        pass

    def do_GET(self):
        u = urllib.parse.urlsplit(self.path)
        q = urllib.parse.parse_qs(u.query)
        type(self).seen.append((self.path, dict(self.headers)))
        if self.token_header and self.headers.get(self.token_header) != self.token:
            self.send_response(401)
            self.end_headers()
            return
        body = None
        for key, ans in self.answers.items():
            kp, _, kq = key.partition("?")
            if kp != u.path:
                continue
            if "?" in key and kq:
                name, _, val = kq.partition("=")
                if (q.get(name) or [None])[0] != val:
                    continue
            elif "?" not in key and u.query and any(k.startswith(u.path + "?") for k in self.answers):
                continue
            body = ans
            break
        if body is None:
            self.send_response(404)
            self.end_headers()
            return
        b = json.dumps(body).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)


def serve(answers, header, token):
    h = type("H", (Fake,), {"answers": answers, "token_header": header, "token": token, "seen": []})
    srv = ThreadingHTTPServer(("127.0.0.1", 0), h)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, h


class VideoServersTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.jf, cls.jh = serve(FX["jellyfin"], "Authorization", 'MediaBrowser Token="jf-key"')
        cls.px, cls.ph = serve(FX["plex"], "X-Plex-Token", "plex-token")
        cls.tmp = tempfile.mkdtemp(prefix="bromigos-video-")
        with open(os.path.join(cls.tmp, "jf-key"), "w") as f:
            f.write("jf-key\n")
        cls.toml = os.path.join(cls.tmp, "homelab.toml")
        with open(cls.toml, "w") as f:
            f.write(f'''
[[source]]
type = "jellyfin"
endpoint = "http://127.0.0.1:{cls.jf.server_port}"
auth_ref = "@file:{cls.tmp}/jf-key"
web_url = "https://watch.example.org"

[[source]]
type = "plex"
endpoint = "http://127.0.0.1:{cls.px.server_port}"
auth_ref = "@env:TEST_PLEX_TOKEN"
direct_max_mbps = 20
''')
        os.environ["TEST_PLEX_TOKEN"] = "plex-token"
        cls._user = config.USER
        config.USER = cls.toml
        config._cache["sig"] = None
        registry._inst["sig"] = None

    @classmethod
    def tearDownClass(cls):
        cls.jf.shutdown()
        cls.px.shutdown()
        config.USER = cls._user
        config._cache["sig"] = None
        registry._inst["sig"] = None

    def test_what_each_server_offers(self):
        r = caps.video()
        self.assertTrue(r["ok"], r["errors"])
        got = {(x["source"], x["kind"], x["title"]) for x in r["items"]}
        self.assertEqual(got, {("jellyfin", "library", "Shows"), ("jellyfin", "library", "Films"),
                               ("jellyfin", "library", "YouTube"), ("jellyfin", "collection", "Space shows"),
                               ("jellyfin", "playlist", "Lo-fi mixes"),
                               ("plex", "library", "Movies"), ("plex", "library", "TV Shows"),
                               ("plex", "collection", "Cartoons"), ("plex", "playlist", "Lo-fi mixes")})
        self.assertEqual([p["title"] for p in caps.video_source("plex").playlists()], ["Lo-fi mixes"])
        self.assertEqual([p["id"] for p in caps.video_source("jellyfin").playlists()], ["pl1"])   # not the audio one

    def test_jellyfin_items(self):
        a = caps.video_source("jellyfin")
        eps = a.video_items("library", "lib-shows")
        self.assertEqual(len(eps), 4)                                    # episodes; the series itself left out
        e = next(i for i in eps if i["id"] == "jep1")
        self.assertEqual((e["series"], e["season"], e["episode"], e["duration"], e["kind"], e["bitrate"]),
                         ("First Show", 1, 2, 1440.0, "episode", 4000))
        self.assertEqual(e["poster"], "/Items/jep1/Images/Primary")
        self.assertEqual(next(i for i in eps if i["id"] == "jep0")["poster"], "/Items/ser1/Images/Primary")
        self.assertEqual([i["title"] for i in a.video_items("playlist", "pl1")], ["Mix two", "Mix one"])
        self.assertEqual(a.video_items("library", "lib-yt")[0]["series"], "Example Studio")
        (r,) = a.video_resume()
        self.assertEqual((r["id"], r["position"]), ("jep1", 610.0))
        self.assertEqual([i["title"] for i in a.video_latest()], ["Episode 314", "A Film"])
        # the first administrator's views, with the key in a header and never in a URL
        paths = [p for p, _ in self.jh.seen]
        self.assertTrue(any(p.startswith("/Users/u-admin/Views") for p in paths))
        self.assertFalse(any("jf-key" in p for p in paths))

    def test_jellyfin_streams(self):
        a = caps.video_source("jellyfin")
        eps = {i["id"]: i for i in a.video_items("library", "lib-shows")}
        s = a.video_stream(eps["jep1"])
        self.assertEqual((s["direct"], s["quality"]), (True, "direct"))
        self.assertTrue(s["url"].endswith("/Videos/jep1/stream?static=true&MediaSourceId=jep1"))
        self.assertEqual(s["headers"], {"Authorization": 'MediaBrowser Token="jf-key"'})
        t = a.video_stream(eps["jep3"])                                  # 45 Mbit/s: over the 20 limit
        self.assertEqual((t["direct"], t["quality"]), (False, "480p"))
        q = urllib.parse.parse_qs(urllib.parse.urlsplit(t["url"]).query)
        self.assertEqual((q["MaxHeight"], q["VideoCodec"]), (["480"], ["h264"]))
        self.assertEqual(a.video_stream(eps["jep1"], "720p")["quality"], "720p")
        self.assertEqual(a.video_stream(eps["jep3"], "direct")["quality"], "direct")
        self.assertNotIn("jf-key", t["url"])
        self.assertEqual(a.video_web(eps["jep1"]), "https://watch.example.org/web/#/details?id=jep1")
        url, h = a.video_poster(eps["jep1"])
        self.assertIn("/Items/jep1/Images/Primary?", url)

    def test_plex_items(self):
        a = caps.video_source("plex")
        eps = a.video_items("library", "6")
        self.assertEqual([(i["series"], i["season"], i["episode"]) for i in eps],
                         [("Second Show", 1, 1), ("First Show", 1, 2), ("First Show", 1, 1)])
        self.assertEqual((eps[1]["duration"], eps[1]["poster"]), (1440.0, "/library/metadata/900/thumb/1"))
        self.assertEqual([i["title"] for i in a.video_items("library", "5")], ["A Film"])
        self.assertEqual([i["series"] for i in a.video_items("collection", "700")], ["Old Toons"])   # a show's episodes
        self.assertEqual([i["title"] for i in a.video_items("playlist", "800")], ["Mix two", "Mix one"])
        (r,) = a.video_resume()
        self.assertEqual(r["position"], 108.243)
        (n,) = a.video_latest()
        self.assertEqual((n["kind"], n["series"], n["season"]), ("season", "First Show", 2))

    def test_plex_streams(self):
        a = caps.video_source("plex")
        eps = {i["id"]: i for i in a.video_items("library", "6")}
        s = a.video_stream(eps["9"])
        self.assertEqual(s["url"], f"http://127.0.0.1:{self.px.server_port}/library/parts/9/1700000000/file.mkv")
        self.assertEqual(s["headers"], {"X-Plex-Token": "plex-token"})
        t = a.video_stream(eps["10"])                                    # 30 Mbit/s
        q = urllib.parse.parse_qs(urllib.parse.urlsplit(t["url"]).query)
        self.assertEqual((t["quality"], q["path"], q["videoResolution"], q["X-Plex-Platform"]),
                         ("480p", ["/library/metadata/10"], ["853x480"], ["Chrome"]))
        self.assertNotIn("plex-token", t["url"])
        self.assertEqual(a.video_web(eps["9"]), f"http://127.0.0.1:{self.px.server_port}/web/index.html#!/server/"
                                                "machine0123/details?key=%2Flibrary%2Fmetadata%2F9")
        url, h = a.video_poster(eps["9"])
        self.assertTrue(url.split("?")[0].endswith("/photo/:/transcode") and h == {"X-Plex-Token": "plex-token"})

    def test_no_key(self):
        a = labmedia.Jellyfin({"name": "jf", "type": "jellyfin", "endpoint": "http://127.0.0.1:9"})
        with self.assertRaises(registry.Unreachable) as e:
            a.video()
        self.assertIn("no API key", str(e.exception))
        p = labmedia.Plex({"name": "px", "type": "plex", "endpoint": "http://127.0.0.1:9"})
        with self.assertRaises(registry.Unreachable) as e:
            p.video()
        self.assertIn("no token", str(e.exception))

    def test_a_tv_channel_from_a_server(self):
        """lib/bromigos_tv.py: a channel names a library, a collection or a playlist by title."""
        import sys
        sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(HERE)), "lib"))
        import importlib
        from unittest import mock
        with mock.patch.dict(os.environ, {"XDG_CACHE_HOME": os.path.join(self.tmp, "cache"),
                                          "XDG_CONFIG_HOME": os.path.join(self.tmp, "config")}):
            import bromigos_tv as TV
            TV = importlib.reload(TV)
        self._tv_channels(TV)

    def _tv_channels(self, TV):
        chans = TV.channels({"tv": {"channel": [
            {"name": "Saturday", "source": "plex", "library": "tv shows"},
            {"name": "YouTube", "source": "jellyfin", "library": "YouTube"},
            {"name": "Mixes", "source": "plex", "playlist": "Lo-fi mixes"},
            {"name": "Nope", "source": "plex", "collection": "Nothing"}]}}, panel=False)
        by = {c["name"]: TV.fetch_items(c, max_age=0) for c in chans}
        self.assertEqual([(i["series"], i["episode"]) for i in by["Saturday"]["items"]],
                         [("First Show", 1), ("First Show", 2), ("Second Show", 1)])     # by series, season, episode
        self.assertEqual(by["YouTube"]["items"][0]["series"], "Example Studio")
        self.assertEqual([i["title"] for i in by["Mixes"]["items"]], ["Mix two", "Mix one"])   # the playlist's order
        self.assertIn("no collection called 'Nothing'", by["Nope"]["error"])
        mixes = next(c for c in chans if c["name"] == "Mixes")
        self.assertEqual(TV.now_next(mixes, TV.EPOCH + 2700 + 60).item["title"], "Mix one")
        cat = TV.catalog(max_age=0)
        self.assertEqual(sorted(cat["servers"]), ["jellyfin", "plex"])
        self.assertIn("Lo-fi mixes", [b["title"] for b in cat["boxes"] if b["kind"] == "playlist"])


if __name__ == "__main__":
    unittest.main()
