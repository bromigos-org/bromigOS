"""YouTube downloads: the Pinchflat adapter (adapters/labmedia.py), its console card
(adapters/labcards.py) and the playlist sync (youtube.py), against fake Pinchflat, Jellyfin and
Plex servers on 127.0.0.1. Nothing reaches a network.

    PYTHONPATH=lib python -m unittest tests.test_lab_youtube
"""
import email.utils
import json
import os
import threading
import unittest
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest import mock

os.environ.setdefault("BROMIGOS_HOMELAB_CONFIG", "/nonexistent")

from bromigos_homelab import youtube as Y                        # noqa: E402
from bromigos_homelab.adapters import labcards, labcommon as L, labmedia  # noqa: E402

TOKEN = "route-token-1"
PL_UUID = "11111111-2222-3333-4444-555555555555"
CH_UUID = "66666666-7777-8888-9999-000000000000"
# a playlist whose order isn't its upload order, and a channel
PLAYLIST = [("vid0000000a", "Opening", "Mon, 02 Mar 2026 10:00:00 +0000"),
            ("vid0000000b", "Second track", "Mon, 05 Jan 2026 10:00:00 +0000"),
            ("vid0000000c", "Third track", "Mon, 06 Apr 2026 10:00:00 +0000")]
CHANNEL = [("vid0000000d", "A channel upload", "Tue, 06 Oct 2026 10:00:00 +0000")]


def feed(name, link, items):
    body = "".join(f"<item><guid>{i}</guid><title>{t}</title><link>https://www.youtube.com/watch?v={i}</link>"
                   f"<pubDate>{d}</pubDate></item>" for i, t, d in sorted(items, key=lambda x: email.utils.parsedate_to_datetime(x[2]), reverse=True))
    return (f'<?xml version="1.0"?><rss version="2.0"><channel><title>{name}</title><link>{link}</link>'
            f"{body}</channel></rss>").encode()


def opml(base):
    return (f'<?xml version="1.0"?><opml version="2.0"><body>'
            f'<outline type="rss" text="Lofi Mix" xmlUrl="{base}/sources/{PL_UUID}/feed.xml" />'
            f'<outline type="rss" text="Some Channel" xmlUrl="{base}/sources/{CH_UUID}/feed.xml" />'
            f"</body></opml>").encode()


METRICS = b"""# TYPE pinchflat_prom_ex_oban_queue_length_count gauge
pinchflat_prom_ex_oban_queue_length_count{name="Oban",queue="media_fetching",state="available"} 3
pinchflat_prom_ex_oban_queue_length_count{name="Oban",queue="media_fetching",state="executing"} 1
pinchflat_prom_ex_oban_queue_length_count{name="Oban",queue="media_fetching",state="completed"} 40
pinchflat_prom_ex_oban_queue_length_count{name="Oban",queue="media_fetching",state="discarded"} 2
pinchflat_prom_ex_oban_queue_length_count{name="Oban",queue="fast_indexing",state="available"} 5
"""

# the YouTube library as the media servers see it: Pinchflat's playlist profile numbers the
# files by playlist position; the channel profile seasons them by year. One playlist video was
# also downloaded by the channel source: the playlist's own copy must win.
FILES = [("/media/youtube/Lofi Mix/Season 1/s01e001 - Opening [vid0000000a].mp4", 1, 1),
         ("/media/youtube/Lofi Mix/Season 1/s01e002 - Second track [vid0000000b].mp4", 1, 2),
         ("/media/youtube/Lofi Mix/Season 1/s01e003 - Third track [vid0000000c].mp4", 1, 3),
         ("/media/youtube/Some Channel/Season 2026/s2026e0105 - Second track [vid0000000b].mp4", 2026, 105),
         ("/media/youtube/Some Channel/Season 2026/s2026e1006 - A channel upload [vid0000000d].mp4", 2026, 1006)]


class Fake:
    """One fake server's state and the log of what changed it."""

    def __init__(self):
        self.playlists = {}          # id -> {"name", "items": [[key, entry]]}
        self.writes = []
        self.n = 0
        self.headers_seen = []
        self.down = False

    def entry(self):
        self.n += 1
        return f"e{self.n}"


class Server(ThreadingHTTPServer):
    daemon_threads = True


def serve(handle):
    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def _do(self):
            u = urllib.parse.urlsplit(self.path)
            q = {k: v[0] for k, v in urllib.parse.parse_qs(u.query).items()}
            n = int(self.headers.get("Content-Length") or 0)
            body = json.loads(self.rfile.read(n)) if n else None
            code, out, ctype = handle(self.command, u.path, q, body, self.headers, "http://127.0.0.1:%d" % self.server.server_port)
            data = out if isinstance(out, bytes) else json.dumps(out).encode() if out is not None else b""
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
        do_GET = do_POST = do_PUT = do_DELETE = _do
    s = Server(("127.0.0.1", 0), H)
    threading.Thread(target=s.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True).start()
    return s, f"http://127.0.0.1:{s.server_port}"


def pinchflat(state):
    def handle(method, path, q, body, headers, base):
        if state.down:
            return 503, b"down", "text/plain"
        if path == "/healthcheck":
            return 200, {"status": "ok"}, "application/json"
        if path == "/":
            return 200, b"<html><title>Pinchflat</title></html>", "text/html"
        if path == "/sources/opml.xml":
            return (200, opml(base), "application/xml") if q.get("route_token") == TOKEN else (401, b"Unauthorized", "text/plain")
        if path == f"/sources/{PL_UUID}/feed.xml":
            return 200, feed("Lofi Mix", "https://www.youtube.com/playlist?list=PLxyz", PLAYLIST), "application/xml"
        if path == f"/sources/{CH_UUID}/feed.xml":
            return 200, feed("Some Channel", "https://www.youtube.com/@somechannel", CHANNEL), "application/xml"
        if path == "/metrics":
            return 200, METRICS, "text/plain"
        return 404, b"not found", "text/plain"
    return handle


def jellyfin(st):
    keys = {f: f"jf{i}" for i, (f, _, _) in enumerate(FILES)}

    def items(pid):
        return [{"Id": k, "PlaylistItemId": e} for k, e in st.playlists[pid]["items"]]

    def handle(method, path, q, body, headers, base):
        st.headers_seen.append(headers.get("Authorization"))
        if 'Token="jf-key"' not in (headers.get("Authorization") or ""):
            return 401, b"", "text/plain"
        if method == "GET" and path == "/Users":
            return 200, [{"Id": "u2", "Name": "kid", "Policy": {}},
                         {"Id": "u1", "Name": "admin", "Policy": {"IsAdministrator": True}}], "application/json"
        if path == "/Library/VirtualFolders":
            return 200, [{"Name": "Movies", "ItemId": "lib0"}, {"Name": "YouTube", "ItemId": "lib1"}], "application/json"
        if path == "/Items" and q.get("IncludeItemTypes") == "Playlist":
            return 200, {"Items": [{"Id": p, "Name": v["name"]} for p, v in st.playlists.items()]}, "application/json"
        if path == "/Items" and q.get("ParentId") == "lib1":
            return 200, {"Items": [{"Id": keys[f], "Name": f.rsplit("/", 1)[1], "Path": f, "ParentIndexNumber": s,
                                    "IndexNumber": e} for f, s, e in FILES]}, "application/json"
        parts = path.strip("/").split("/")
        if parts[0] == "Playlists":
            if method == "POST" and len(parts) == 1:
                pid = f"pl{len(st.playlists) + 1}"
                st.playlists[pid] = {"name": body["Name"], "items": [[k, st.entry()] for k in body["Ids"]]}
                st.writes.append(("create", body["Name"], body["UserId"]))
                return 200, {"Id": pid}, "application/json"
            pid = parts[1]
            if method == "GET" and parts[2:] == ["Items"]:
                return 200, {"Items": items(pid)}, "application/json"
            if method == "POST" and parts[2:] == ["Items"]:
                st.playlists[pid]["items"] += [[k, st.entry()] for k in q["ids"].split(",")]
                st.writes.append(("add", q["ids"]))
                return 204, None, "application/json"
            if method == "DELETE" and parts[2:] == ["Items"]:
                gone = set(q["entryIds"].split(","))
                st.playlists[pid]["items"] = [x for x in st.playlists[pid]["items"] if x[1] not in gone]
                st.writes.append(("remove", q["entryIds"]))
                return 204, None, "application/json"
            if method == "POST" and len(parts) == 6 and parts[4] == "Move":
                lst = st.playlists[pid]["items"]
                it = next(x for x in lst if x[0] == parts[3])
                lst.remove(it)
                lst.insert(int(parts[5]), it)
                st.writes.append(("move", parts[3], int(parts[5])))
                return 204, None, "application/json"
        return 404, b"", "text/plain"
    return handle, keys


def plex(st):
    keys = {f: str(100 + i) for i, (f, _, _) in enumerate(FILES)}

    def handle(method, path, q, body, headers, base):
        if headers.get("X-Plex-Token") != "px-token":
            return 401, b"", "text/plain"
        mc = lambda d: (200, {"MediaContainer": d}, "application/json")   # noqa: E731
        if path == "/identity":
            return mc({"machineIdentifier": "mid1"})
        if path == "/library/sections":
            return mc({"Directory": [{"key": "1", "title": "Films", "type": "movie"},
                                     {"key": "5", "title": "YouTube", "type": "show"}]})
        if path == "/library/sections/5/all" and q.get("type") == "4":
            return mc({"Metadata": [{"ratingKey": keys[f], "title": f.rsplit("/", 1)[1], "parentIndex": s, "index": e,
                                     "Media": [{"Part": [{"file": f}]}]} for f, s, e in FILES]})
        parts = path.strip("/").split("/")
        if path == "/playlists" and method == "GET":
            return mc({"Metadata": [{"ratingKey": p, "title": v["name"], "smart": False} for p, v in st.playlists.items()]})
        if path == "/playlists" and method == "POST":
            assert q["uri"].startswith("server://mid1/com.plexapp.plugins.library/library/metadata/"), q["uri"]
            pid = str(900 + len(st.playlists))
            st.playlists[pid] = {"name": q["title"], "items": [[k, st.entry()] for k in q["uri"].rsplit("/", 1)[1].split(",")]}
            st.writes.append(("create", q["title"]))
            return mc({"Metadata": [{"ratingKey": pid}]})
        if parts[0] == "playlists" and len(parts) >= 3:
            pid, lst = parts[1], st.playlists[parts[1]]["items"]
            if method == "GET" and len(parts) == 3:
                return mc({"Metadata": [{"ratingKey": k, "playlistItemID": e} for k, e in lst]})
            if method == "PUT" and len(parts) == 3:
                lst += [[k, st.entry()] for k in q["uri"].rsplit("/", 1)[1].split(",")]
                st.writes.append(("add", q["uri"].rsplit("/", 1)[1]))
                return mc({})
            if method == "DELETE" and len(parts) == 4:
                st.playlists[pid]["items"] = [x for x in lst if x[1] != parts[3]]
                st.writes.append(("remove", parts[3]))
                return mc({})
            if method == "PUT" and len(parts) == 5 and parts[4] == "move":
                it = next(x for x in lst if x[1] == parts[3])
                lst.remove(it)
                after = q.get("after")
                at = 0 if not after else next(i for i, x in enumerate(lst) if x[1] == after) + 1
                lst.insert(at, it)
                st.writes.append(("move", parts[3], after))
                return mc({})
        return 404, b"", "text/plain"
    return handle, keys


class Servers(unittest.TestCase):
    def setUp(self):
        self.pf, self.jf, self.px = Fake(), Fake(), Fake()
        self.s_pf, self.pf_url = serve(pinchflat(self.pf))
        h, self.jf_keys = jellyfin(self.jf)
        self.s_jf, self.jf_url = serve(h)
        h, self.px_keys = plex(self.px)
        self.s_px, self.px_url = serve(h)
        self.env = mock.patch.dict(os.environ, {
            "PINCHFLAT_URL": self.pf_url, "PINCHFLAT_ROUTE_TOKEN": TOKEN, "JELLYFIN_URL": self.jf_url,
            "JELLYFIN_TOKEN": "jf-key", "PLEX_URL": self.px_url, "PLEX_TOKEN": "px-token"})
        self.env.start()

    def tearDown(self):
        self.env.stop()
        for s in (self.s_pf, self.s_jf, self.s_px):
            s.shutdown()
            s.server_close()

    def sync(self, *argv):
        a = Y.argparse.Namespace(dry_run="--dry-run" in argv, server=[x for x in ("jellyfin", "plex") if x in argv],
                                 library=None, prefix=None, source=None)
        return Y.run(a)

    def order(self, fake, keys):
        back = {v: k for k, v in keys.items()}
        (pl,) = fake.playlists.values()
        return [back[k].rsplit("[", 1)[1][:11] for k, _ in pl["items"]]


class SyncTest(Servers):
    WANT = ["vid0000000a", "vid0000000b", "vid0000000c"]        # the playlist's order, not the upload order

    def test_creates_the_playlist_in_order_on_both(self):
        doc = self.sync()
        self.assertEqual(doc["errors"], {})
        self.assertEqual(doc["playlists"], 1)                    # the channel isn't a playlist
        self.assertEqual({(r["server"], r["playlist"], r["action"], r["items"]) for r in doc["report"]},
                         {("jellyfin", "Lofi Mix", "create", 3), ("plex", "Lofi Mix", "create", 3)})
        self.assertEqual(self.order(self.jf, self.jf_keys), self.WANT)
        self.assertEqual(self.order(self.px, self.px_keys), self.WANT)
        # the playlist's own copy of the video, not the channel's
        self.assertNotIn(self.jf_keys[FILES[3][0]], [k for k, _ in self.jf.playlists["pl1"]["items"]])
        self.assertEqual(self.jf.writes[0], ("create", "Lofi Mix", "u1"))     # the first admin's

    def test_idempotent(self):
        self.sync()
        jw, pw = len(self.jf.writes), len(self.px.writes)
        doc = self.sync()
        self.assertEqual({r["action"] for r in doc["report"]}, {"ok"})
        self.assertEqual((len(self.jf.writes), len(self.px.writes)), (jw, pw))

    def test_dry_run_changes_nothing(self):
        doc = self.sync("--dry-run")
        self.assertTrue(doc["dry_run"])
        self.assertEqual({r["action"] for r in doc["report"]}, {"create"})
        self.assertEqual((self.jf.writes, self.px.writes, self.jf.playlists), ([], [], {}))

    def test_repairs_a_changed_playlist(self):
        self.sync()
        for fake, keys in ((self.jf, self.jf_keys), (self.px, self.px_keys)):
            (pl,) = fake.playlists.values()
            stray = keys[FILES[4][0]]
            pl["items"] = [pl["items"][2], [stray, fake.entry()], pl["items"][0]]     # shuffled, one gone, one extra
        doc = self.sync("--dry-run")
        self.assertEqual({(r["action"], r["added"], r["removed"]) for r in doc["report"]}, {("update", 1, 1)})
        doc = self.sync()
        self.assertEqual({r["action"] for r in doc["report"]}, {"update"})
        self.assertEqual(self.order(self.jf, self.jf_keys), self.WANT)
        self.assertEqual(self.order(self.px, self.px_keys), self.WANT)
        self.assertEqual({r["action"] for r in self.sync()["report"]}, {"ok"})

    def test_one_server(self):
        doc = self.sync("plex")
        self.assertEqual({r["server"] for r in doc["report"]}, {"plex"})
        self.assertEqual(self.jf.writes, [])

    def test_a_server_that_fails_is_reported(self):
        os.environ["PLEX_TOKEN"] = "wrong"
        doc = self.sync()
        self.assertIn("HTTP 401", doc["errors"]["plex"])
        self.assertEqual({r["server"] for r in doc["report"]}, {"jellyfin"})
        with mock.patch("sys.stdout"), mock.patch("sys.stderr"):
            self.assertEqual(Y.main(["sync", "--json"]), 1)

    def test_prefix_and_main(self):
        os.environ["YOUTUBE_PLAYLIST_PREFIX"] = "YT: "
        with mock.patch("sys.stdout"):
            self.assertEqual(Y.main(["sync", "--server", "jellyfin"]), 0)
        self.assertEqual([p["name"] for p in self.jf.playlists.values()], ["YT: Lofi Mix"])

    def test_not_configured(self):
        os.environ.pop("PINCHFLAT_ROUTE_TOKEN")
        with mock.patch("sys.stderr"):
            self.assertEqual(Y.main(["sync"]), 3)
        os.environ["PINCHFLAT_ROUTE_TOKEN"] = "nope"
        with self.assertRaises(Y.SyncError):
            self.sync()


class StepsTest(unittest.TestCase):
    def test_steps(self):
        cur = [{"key": k, "entry": "e" + k} for k in ("c", "x", "a", "a")]
        remove, add, moves = Y.steps(cur, ["a", "b", "c"])
        self.assertEqual((remove, add), (["ex", "ea"], ["b"]))
        sim = ["c", "a", "b"]
        for k, i in moves:
            sim.remove(k)
            sim.insert(i, k)
        self.assertEqual(sim, ["a", "b", "c"])
        self.assertEqual(Y.steps([{"key": "a", "entry": "1"}], ["a"]), ([], [], []))

    def test_parsers(self):
        self.assertEqual(Y.source_kind("https://www.youtube.com/playlist?list=PL1"), "playlist")
        self.assertEqual(Y.source_kind("https://www.youtube.com/@x/videos"), "channel")
        self.assertEqual(Y.video_id("https://youtu.be/vid0000000a?t=3"), "vid0000000a")
        f = Y.parse_feed(feed("P", "https://www.youtube.com/playlist?list=PL1", PLAYLIST))
        self.assertEqual([i["id"] for i in f["items"]], ["vid0000000c", "vid0000000a", "vid0000000b"])  # newest first


class AdapterTest(Servers):
    def adapter(self, **kw):
        src = {"name": "pinchflat", "type": "pinchflat", "endpoint": self.pf_url, "route_token_ref": "@env:PF_TOK"}
        src.update(kw)
        return labmedia.Pinchflat(src)

    def test_records(self):
        with mock.patch.dict(os.environ, {"PF_TOK": TOKEN}):
            a = self.adapter()
            self.assertTrue(a.probe())
            me, *srcs = a.youtube_downloader()
        self.assertEqual((me["kind"], me["up"], me["queue"], me["errors"], me["state"]), ("downloader", True, 4, 2, "warn"))
        self.assertEqual((me["sources"], me["playlists"], me["channels"], me["videos"]), (2, 1, 1, 4))
        self.assertEqual(me["recent"][0]["title"], "A channel upload")
        by = {r["name"]: r for r in srcs}
        self.assertEqual((by["Lofi Mix"]["kind"], by["Lofi Mix"]["videos"], by["Lofi Mix"]["newest"]),
                         ("playlist", 3, "Third track"))
        self.assertEqual(by["Some Channel"]["kind"], "channel")
        self.assertEqual(by["Some Channel"]["newest_at"], "2026-10-06T10:00:00Z")
        with mock.patch.dict(os.environ, {"PF_TOK": TOKEN}):
            st = {f["id"]: f["status"] for f in a.doctor()}
        self.assertEqual(st, {"youtube.pinchflat.failed": "warn"})

    def test_without_a_route_token_or_metrics(self):
        a = self.adapter(route_token_ref="", metrics="none")
        me, *srcs = a.youtube_downloader()
        self.assertEqual((srcs, me["queue"], me["up"]), ([], None, True))
        self.assertIn("route_token_ref", me["detail"])
        self.assertIn("youtube.pinchflat.sources", {f["id"] for f in a.doctor()})

    def test_queue_from_the_lab_metrics(self):
        rows = [{"labels": {"queue": "media_fetching", "state": "retryable"}, "value": 2},
                {"labels": {"queue": "local_data", "state": "discarded"}, "value": 1}]
        a = self.adapter(metrics="source")
        with mock.patch.object(L, "mq_soft", return_value=rows):
            self.assertEqual(a.queue(), (2, 1))

    def test_down(self):
        self.pf.down = True
        (me,) = self.adapter().youtube_downloader()
        self.assertEqual((me["up"], me["state"]), (False, "crit"))
        self.assertIn("HTTP 503", me["detail"])
        self.assertEqual({f["status"] for f in self.adapter().doctor()}, {"fail"})

    def test_card(self):
        with mock.patch.dict(os.environ, {"PF_TOK": TOKEN}):
            recs = self.adapter().youtube_downloader()
        card = next(c for c in labcards.CARDS if c["id"] == "youtube-downloader")
        self.assertEqual(card["summary"](recs), "2 sources · 4 videos · 4 waiting · 2 failed")
        self.assertEqual([card["state"](r) for r in recs], ["warn", "ok", "ok"])
        hints = [card["item_hint"](r) for r in recs]
        self.assertIn("4 waiting to download", hints[0])
        self.assertIn("bromigos lab youtube sync", hints[1])
        self.assertTrue(all(hints) and card["hint"])
        self.pf.down = True
        (me,) = self.adapter().youtube_downloader()
        self.assertEqual(card["summary"]([me]), "Pinchflat is down")
        self.assertIn("DOWN", card["item_hint"](me))


if __name__ == "__main__":
    unittest.main()
