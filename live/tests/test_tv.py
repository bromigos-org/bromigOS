"""The den TV's channels and schedule (lib/bromigos_tv.py), and YouTube through yt-dlp
(lib/bromigos_youtube.py) against a stand-in (tests/fake_ytdlp.py: recorded listings in
tests/fixtures, no network). No GPU, no desktop.

    cd live && python -m unittest discover -s tests

- the schedule: the same answer for the same time, on any run; a position from the wall
  clock; wrapping round the list; the next item across a pass; a changed length or a new
  item; a stable shuffle; a playlist in its order; a shuffle that holds all day;
- the channels: each screen's list (its own picture first), defaults per kind, the media
  panel's channel, a bad entry skipped, remembered state;
- YouTube: a channel's uploads and a playlist parsed, cached and not run again, a failure
  keeping the last good list, live now, keeping videos (the layout, the .nfo, the size cap,
  an age-gated video), never on battery.
"""
import atexit
import json
import os
import shutil
import sys
import tempfile
import time
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(REPO, "lib"))

SANDBOX = tempfile.mkdtemp(prefix="bromigos-tvtest-")
atexit.register(shutil.rmtree, SANDBOX, True)      # its kept videos run to hundreds of MB: never left in /tmp
assert "bromigos_tv" not in sys.modules or sys.modules["bromigos_tv"].CACHE.startswith(tempfile.gettempdir()), \
    "bromigos_tv was imported with the user's own paths"
for k, sub in (("XDG_CACHE_HOME", "cache"), ("XDG_STATE_HOME", "state"), ("XDG_CONFIG_HOME", "config")):
    os.environ[k] = os.path.join(SANDBOX, sub)
os.environ["BROMIGOS_YTDLP"] = os.path.join(HERE, "fake_ytdlp.py")
os.environ["FAKE_YTDLP_LOG"] = os.path.join(SANDBOX, "ytdlp.log")
os.environ["BROMIGOS_HOMELAB_CONFIG"] = os.path.join(SANDBOX, "none.toml")

import bromigos_tv as TV  # noqa: E402
import bromigos_youtube as Y  # noqa: E402


def items(*durations, prefix="ep"):
    return [{"id": f"{prefix}{i}", "title": f"Episode {i}", "duration": d} for i, d in enumerate(durations)]


def calls():
    try:
        with open(os.environ["FAKE_YTDLP_LOG"]) as f:
            return [json.loads(x) for x in f]
    except OSError:
        return []


class ScheduleTest(unittest.TestCase):
    def test_same_time_same_answer(self):
        its = items(1200, 1500, 600, 2400)
        t = TV.EPOCH + 123456.7
        a = TV.schedule_at(its, t, "seed", "shuffle")
        b = TV.schedule_at(list(reversed(its)), t, "seed", "shuffle")     # whatever order the server lists
        self.assertEqual((a.item["id"], round(a.offset, 6)), (b.item["id"], round(b.offset, 6)))

    def test_position_follows_the_clock(self):
        its = items(100, 200, 300)
        s = TV.schedule_at(its, TV.EPOCH + 150, order="in order")
        self.assertEqual((s.item["id"], s.offset, s.start, s.end), ("ep1", 50, TV.EPOCH + 100, TV.EPOCH + 300))
        later = TV.schedule_at(its, TV.EPOCH + 160, order="in order")
        self.assertEqual((later.item["id"], later.offset), ("ep1", 60))         # as if it had been on all along

    def test_wraps_round(self):
        its = items(100, 200, 300)
        s = TV.schedule_at(its, TV.EPOCH + 600 * 7 + 30, order="in order")
        self.assertEqual((s.item["id"], s.offset, s.pass_), ("ep0", 30, 7))
        last = TV.schedule_at(its, TV.EPOCH + 600 * 7 - 1, order="in order")
        self.assertEqual((last.item["id"], last.next["id"]), ("ep2", "ep0"))  # the next item is the next pass's first
        exact = TV.schedule_at(its, TV.EPOCH + 100, order="in order")
        self.assertEqual((exact.item["id"], exact.offset), ("ep1", 0))         # a boundary starts the next item

    def test_before_the_epoch(self):
        s = TV.schedule_at(items(100, 200), TV.EPOCH - 50, order="in order")
        self.assertEqual((s.item["id"], s.offset), ("ep1", 150))

    def test_a_shuffle_is_stable_and_takes_new_items_in(self):
        its = items(*([600] * 30))
        t = TV.EPOCH + 1000
        day = TV.day_of(TV.EPOCH)
        first = [i["id"] for i in TV.order_of(its, "s", day, "shuffle")]
        self.assertNotEqual(first, [i["id"] for i in its])
        more = its + items(600, prefix="new")
        second = [i["id"] for i in TV.order_of(more, "s", day, "shuffle")]
        self.assertEqual([x for x in second if x != "new0"], first)            # the rest keep their order
        self.assertNotEqual(first, [i["id"] for i in TV.order_of(its, "other seed", day, "shuffle")])
        self.assertIsNotNone(TV.schedule_at(more, t, "s"))

    def test_a_shuffle_holds_all_day(self):
        its = items(*([60] * 10))                            # 10 minutes round: many passes a day
        old = os.environ.get("TZ")
        os.environ["TZ"] = "UTC"
        time.tzset()
        try:
            noon = TV.EPOCH + 86400 * 40 + 43200 + 17         # a pass boundary is at a whole 600 s from EPOCH
            today = [TV.schedule_at(its, noon + 600 * k, "seed").item["id"] for k in range(-60, 60)]
            self.assertEqual(len(set(today)), 1)               # the same slot each pass: one order all day
            days = {TV.schedule_at(its, noon + 86400 * k, "seed").item["id"] for k in range(12)}
            self.assertGreater(len(days), 1)                   # another day, another order
        finally:
            if old is None:
                os.environ.pop("TZ", None)
            else:
                os.environ["TZ"] = old
            time.tzset()

    def test_a_length_changes(self):
        its = items(100, 200, 300)
        t = TV.EPOCH + 10_000.5
        before = TV.schedule_at(its, t, order="in order")
        its[1]["duration"] = 260                             # the server corrected a length
        after = TV.schedule_at(its, t, order="in order")
        for s in (before, after):
            self.assertTrue(0 <= s.offset < s.item["duration"])
            self.assertAlmostEqual(s.start + s.offset, t, places=3)
            self.assertAlmostEqual(s.end - s.start, s.item["duration"], places=3)
        self.assertEqual(((t - TV.EPOCH) % 600, (t - TV.EPOCH) % 660), (400.5, 100.5))
        self.assertEqual((before.item["id"], round(before.offset, 1)), ("ep2", 100.5))
        self.assertEqual((after.item["id"], round(after.offset, 1)), ("ep1", 0.5))

    def test_items_without_a_length_or_bad_are_left_out(self):
        its = items(100, None, 0, 200)
        s = TV.schedule_at(its, TV.EPOCH + 150, order="in order")
        self.assertEqual((s.item["id"], s.offset, s.count), ("ep3", 50, 2))
        s = TV.schedule_at(its, TV.EPOCH + 50, order="in order", bad={"ep0"})
        self.assertEqual(s.item["id"], "ep3")
        self.assertIsNone(TV.schedule_at(items(None, 0), TV.EPOCH))
        self.assertIsNone(TV.schedule_at([], TV.EPOCH))

    def test_upcoming(self):
        up = TV.upcoming(items(100, 200, 300), TV.EPOCH + 10, 4, order="in order")
        self.assertEqual([s.item["id"] for s in up], ["ep1", "ep2", "ep0", "ep1"])

    def test_labels(self):
        self.assertEqual(TV.label({"title": "Pilot", "series": "Show", "season": 1, "episode": 2, "kind": "episode"}),
                         "Show S1E2 · Pilot")
        self.assertEqual(TV.label({"title": "Film", "year": 1999, "kind": "movie"}), "Film (1999)")
        self.assertEqual(TV.fmt_time(3725), "1:02:05")
        self.assertEqual(TV.fmt_time(65), "1:05")


class ChannelsTest(unittest.TestCase):
    def setUp(self):
        shutil.rmtree(os.environ["XDG_CONFIG_HOME"], ignore_errors=True)

    CFG = {"tv": {"channel": [
        {"name": "Saturday", "source": "plex", "library": "TV Shows", "screens": ["big", "wave"]},
        {"name": "Mixes", "playlist": "Lo-fi mixes"},
        {"name": "Studio", "youtube": "https://www.youtube.com/@examplestudio", "live": True},
        {"name": "Clips", "youtube": "https://www.youtube.com/playlist?list=PLexample", "screens": "emblem"},
        {"name": "saturday", "library": "Again"},                  # the same name: skipped
        {"name": "Nothing to play"},                                 # skipped
        {"name": "Off", "library": "X", "enabled": False},
    ]}}

    def test_lineups(self):
        self.assertEqual([c["name"] for c in TV.lineup(self.CFG, "big")], ["RELAY MAP", "Saturday", "Mixes", "Studio"])
        self.assertEqual([c["name"] for c in TV.lineup(self.CFG, "wave")], ["SCOPE", "Saturday"])
        self.assertEqual([c["name"] for c in TV.lineup(self.CFG, "emblem")], ["BURN-IN", "Clips"])
        self.assertEqual([c["name"] for c in TV.lineup({}, "big")], ["RELAY MAP"])
        self.assertEqual([c["name"] for c in TV.lineup({"tv": dict(self.CFG["tv"], enabled=False)}, "big")],
                         ["RELAY MAP"])

    def test_defaults_per_kind(self):
        by = {c["name"]: c for c in TV.channels(self.CFG)}
        self.assertEqual(by["Saturday"]["order"], "shuffle")          # a library: shuffled
        self.assertEqual(by["Mixes"]["order"], "in order")            # a playlist: its own order
        self.assertEqual(by["Studio"]["order"], "shuffle")            # a channel's uploads
        self.assertEqual(by["Clips"]["order"], "in order")            # a YouTube playlist
        self.assertEqual(by["Mixes"]["screens"], ["big"])

    def test_live_now_is_a_channel_of_its_own(self):
        lu = TV.lineup(self.CFG, "big", live={"studio": {"id": "x", "title": "Live", "url": "u"}})
        self.assertEqual([c["name"] for c in lu][-2:], ["Studio", "Studio LIVE"])
        self.assertEqual(TV.now_next(lu[-1]).item["kind"], "live")

    def test_the_panels_channel(self):
        d = os.path.join(os.environ["XDG_CONFIG_HOME"], "bromigos", "widgets")
        os.makedirs(d)
        with open(os.path.join(d, "media.toml"), "w") as f:
            f.write('play = "playlist:Lo-fi mixes"\nsource = "jellyfin"\nscreen = "wave"\nchannel_name = "Panel mix"\n')
        ch = next(c for c in TV.channels(self.CFG) if c["name"] == "Panel mix")
        self.assertEqual((ch["playlist"], ch["source"], ch["screens"], ch["order"]),
                         ("Lo-fi mixes", "jellyfin", ["wave"], "in order"))
        self.assertNotIn("Panel mix", [c["name"] for c in TV.channels(self.CFG, panel=False)])
        with open(os.path.join(d, "media.toml"), "w") as f:
            f.write('source = "youtube"\nyoutube = "https://www.youtube.com/@examplestudio"\nkeep = "~/Videos/YouTube"\n')
        ch = TV.channels({})[0]
        self.assertEqual((ch["kind"], ch["keep"], ch["screens"]), ("youtube", "~/Videos/YouTube", ["big"]))

    def test_state_is_remembered(self):
        st = TV.state()
        self.assertEqual(TV.screen_state(st, "big"), {"channel": "own", "sound": False, "volume": TV.DEFAULT_VOLUME})
        st["screens"]["big"] = {"channel": "saturday", "sound": True, "volume": 140}
        TV.save_state(st)
        again = TV.screen_state(TV.state(), "big")
        self.assertEqual(again, {"channel": "saturday", "sound": True, "volume": 100})     # capped at 100

    def test_files_channel(self):
        d = os.path.join(SANDBOX, "videos")
        os.makedirs(d, exist_ok=True)
        for n in ("b.mkv", "a.mp4", "notes.txt"):
            open(os.path.join(d, n), "w").close()
        with mock.patch.object(TV, "_probe", side_effect=lambda p: 600.0 if p.endswith(".mp4") else 1200.0) as probe:
            got = TV.local_files(d)
            self.assertEqual([(i["title"], i["duration"]) for i in got], [("a", 600.0), ("b", 1200.0)])
            TV.local_files(d)
            self.assertEqual(probe.call_count, 2)                      # lengths cached by size and time

    def test_a_bad_item_is_left_out_for_a_day(self):
        TV.mark_bad("ep1")
        self.assertIn("ep1", TV.bad_items())
        with mock.patch.object(TV.time, "time", return_value=time.time() + TV.BAD_FOR + 5):
            self.assertNotIn("ep1", TV.bad_items())


class YouTubeTest(unittest.TestCase):
    def setUp(self):
        shutil.rmtree(Y.CACHE, ignore_errors=True)
        try:
            os.remove(os.environ["FAKE_YTDLP_LOG"])
        except OSError:
            pass

    def test_tab_urls(self):
        self.assertEqual(Y.channel_tab("https://www.youtube.com/@x"), "https://www.youtube.com/@x/videos")
        self.assertEqual(Y.channel_tab("https://www.youtube.com/@x/"), "https://www.youtube.com/@x/videos")
        self.assertEqual(Y.channel_tab("https://www.youtube.com/@x/streams"), "https://www.youtube.com/@x/streams")
        self.assertEqual(Y.channel_tab("https://www.youtube.com/channel/UC1", "streams"),
                         "https://www.youtube.com/channel/UC1/streams")
        pl = "https://www.youtube.com/playlist?list=PL1"
        self.assertEqual(Y.channel_tab(pl), pl)

    def test_a_channels_uploads(self):
        d = Y.videos("https://www.youtube.com/@examplestudio")
        self.assertIsNone(d["error"])
        self.assertEqual([v["title"] for v in d["videos"]],
                         ["Studio log 32", "Project teaser", "Behind the scenes", "Material library tour"])
        v = d["videos"][0]
        self.assertEqual((v["duration"], v["url"].startswith("https://www.youtube.com/watch?v=")), (855.0, True))
        self.assertTrue(v["thumbnail"].endswith("?big"))                  # the biggest at most 720 wide
        Y.videos("https://www.youtube.com/@examplestudio")
        self.assertEqual(len(calls()), 1)                                 # cached: yt-dlp ran once
        self.assertEqual(calls()[0][-1], "https://www.youtube.com/@examplestudio/videos")

    def test_a_channels_page_listing_tabs(self):
        doc = Y.parse(json.load(open(os.path.join(HERE, "fixtures", "ytdlp-channel.json"))))
        self.assertEqual(len(doc["videos"]), 4)

    def test_a_playlist(self):
        d = Y.videos("https://www.youtube.com/playlist?list=PLexample0000000000000000000000000")
        self.assertEqual([v["title"] for v in d["videos"]], ["Mix one", "Mix two", "Mix three"])

    def test_a_failure_keeps_the_last_list(self):
        url = "https://www.youtube.com/@gone"
        self.assertEqual(Y.videos(url)["videos"], [])
        self.assertIn("does not exist", Y.videos(url, max_age=0)["error"])
        good = "https://www.youtube.com/@examplestudio"
        Y.videos(good)
        with open(Y._path(Y.channel_tab(good))) as f:
            doc = json.load(f)
        doc["fetched"] = 0
        doc["url"] = good
        with open(Y._path(Y.channel_tab(good)), "w") as f:
            json.dump(doc, f)
        with mock.patch.object(Y, "_run", side_effect=RuntimeError("HTTP Error 429")):
            d = Y.videos(good)
        self.assertEqual((len(d["videos"]), d["error"]), (4, "HTTP Error 429"))

    def test_live_now(self):
        v = Y.live_now("https://www.youtube.com/@examplestudio")
        self.assertEqual((v["title"], v["live"]), ("Live: modelling session", "is_live"))
        self.assertIsNone(Y.live_now("https://www.youtube.com/playlist?list=PL1"))
        with mock.patch.object(Y, "videos", return_value={"videos": [{"id": "x", "live": "was_live"}], "error": None}):
            self.assertIs(Y.live_now("https://www.youtube.com/@quiet"), False)      # known not live
        self.assertIsNone(Y.live_now("https://www.youtube.com/@gone"))              # can't be told

    def test_channel_videos_for_the_youtube_panel(self):
        got = Y.channel_videos("https://www.youtube.com/@examplestudio", limit=2)
        self.assertEqual([(v["title"], v["live_status"]) for v in got], [("Studio log 32", None), ("Project teaser", None)])
        self.assertIn("timestamp", got[0])
        with self.assertRaises(RuntimeError):
            Y.channel_videos("https://www.youtube.com/@gone")

    def test_no_ytdlp(self):
        with mock.patch.dict(os.environ, {"BROMIGOS_YTDLP": ""}), mock.patch.object(Y.shutil, "which", return_value=None):
            d = Y.videos("https://www.youtube.com/@nobody")
        self.assertIn("isn't installed", d["error"])

    def test_tv_items_from_youtube(self):
        pl = "https://www.youtube.com/playlist?list=PLexample"
        ch = TV.channels({"tv": {"channel": [{"name": "Mixes", "youtube": pl}]}}, panel=False)[0]
        doc = TV.fetch_items(ch, max_age=0)
        self.assertEqual([(i["title"], i["index"], i["playlist"]) for i in doc["items"]],
                         [("Mix one", 1, "Lo-fi mixes"), ("Mix two", 2, "Lo-fi mixes"), ("Mix three", 3, "Lo-fi mixes")])
        s = TV.now_next(ch, TV.EPOCH + 3600 + 5)
        self.assertEqual((s.item["title"], round(s.offset)), ("Mix two", 5))


class KeepTest(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.mkdtemp(dir=SANDBOX, prefix="keep-")

    def video(self, vid, title="T"):
        return {"id": vid, "title": title, "url": f"https://www.youtube.com/watch?v={vid}", "channel": "Example Studio"}

    def test_a_channels_video(self):
        p = Y.keep(self.video("abc"), self.folder)
        self.assertEqual(os.path.relpath(p, self.folder), "Example Studio/Season 2026/2026-03-14 - Video abc.mkv")
        base = p[:-4]
        nfo = open(base + ".nfo").read()
        self.assertIn("<season>2026</season>", nfo)
        self.assertIn("<aired>2026-03-14</aired>", nfo)
        self.assertIn("&amp; &lt;its&gt;", nfo)
        self.assertTrue(os.path.exists(os.path.join(self.folder, "Example Studio", "tvshow.nfo")))
        self.assertTrue(os.path.exists(os.path.join(self.folder, "Example Studio", "poster.jpg")))
        self.assertFalse(os.path.exists(base + ".info.json"))
        self.assertEqual(Y.kept(self.folder, "abc"), p)
        self.assertEqual(Y.keep(self.video("abc"), self.folder), p)          # kept: not downloaded again
        cmd = calls()[-1]
        self.assertIn("bv*[height<=1080]+ba/b[height<=1080]/b", cmd)

    def test_a_playlists_video_is_numbered(self):
        p = Y.keep(self.video("pl7"), self.folder, playlist="Lo-fi mixes", index=7)
        self.assertEqual(os.path.relpath(p, self.folder), "Lo-fi mixes/Season 1/S01E007 - Video pl7.mkv")
        self.assertIn("<episode>7</episode>", open(p[:-4] + ".nfo").read())

    def test_low_priority(self):
        with mock.patch.object(Y.subprocess, "run", wraps=Y.subprocess.run) as run:
            Y.keep(self.video("nice1"), self.folder)
        argv = run.call_args[0][0]
        if shutil.which("nice"):
            self.assertEqual(argv[:3], ["nice", "-n", "19"])
        if shutil.which("ionice"):
            self.assertIn("ionice", argv)

    def test_an_age_gated_video(self):
        with self.assertRaises(Y.KeepError) as e:
            Y.keep(self.video("agegate"), self.folder)
        self.assertIn("confirm your age", str(e.exception))

    def test_the_cap_removes_the_oldest(self):
        with mock.patch.dict(os.environ, {"FAKE_YTDLP_SIZE": "400000000"}):
            for n, vid in enumerate(("old", "mid", "new")):
                Y.keep(self.video(vid), self.folder, playlist="P", index=n + 1)
                idx = Y._index(self.folder)
                idx[vid]["kept_at"] = 1000 + n
                Y._save_index(self.folder, idx)
        mine = os.path.join(self.folder, "P", "not-ours.mkv")
        open(mine, "w").close()
        gone = Y.prune(self.folder, 1.0)                 # 1.2 GB kept, 1 GB allowed
        self.assertTrue(all("Video old" in g for g in gone) and gone)
        self.assertIsNone(Y.kept(self.folder, "old"))
        self.assertIsNotNone(Y.kept(self.folder, "new"))
        self.assertTrue(os.path.exists(mine))            # never a file keep() didn't write

    def test_never_on_battery(self):
        k = Y.Keeper(log=lambda *a: None)
        with mock.patch.object(Y, "on_battery", return_value=True):
            k.want(self.video("bat"), self.folder)
            time.sleep(0.3)
            self.assertIsNone(Y.kept(self.folder, "bat"))
        k.wake.set()
        for _ in range(50):
            if Y.kept(self.folder, "bat"):
                break
            time.sleep(0.1)
        self.assertIsNotNone(Y.kept(self.folder, "bat"))
        self.assertFalse(k.want(self.video("bat"), self.folder))      # once


class FailureTest(unittest.TestCase):
    """live/tv.py: an item that won't play is skipped; a server that's down isn't the items' fault."""

    def setUp(self):
        sys.path.insert(0, os.path.dirname(HERE))
        try:
            from live import tv as livetv
        except ImportError as e:                     # no PyOpenGL: the live layer's own tests skip too
            self.skipTest(str(e))
        self.livetv = livetv
        shutil.rmtree(TV.CACHE, ignore_errors=True)
        self.tv = livetv.TV({"tv": {}}, log=lambda *a: None)
        self.tv.stop.set()

    class Player:
        def __init__(self):
            self.ended, self.started, self.stopped = ("error", -13), False, 0

        def stop(self):
            self.stopped += 1

    def fail(self, iid):
        p = self.Player()
        d = self.tv.decks["big"]
        d.player = p
        d.loaded = ("ch", iid)
        self.tv._check_failure(d, {"key": "ch", "name": "Ch"}, TV.Slot(item={"id": iid, "title": iid}, offset=1.0))
        return p

    def test_one_bad_item_is_skipped(self):
        p = self.fail("a")
        self.assertIn("a", TV.bad_items())
        self.assertIsNone(self.tv.decks["big"].loaded)
        self.assertEqual(p.stopped, 1)

    def test_a_server_thats_down_skips_nothing(self):
        for iid in ("a", "b", "c"):
            self.fail(iid)
        self.assertEqual(set(TV.bad_items()) & {"a", "b", "c"}, set())
        self.assertGreater(self.tv.retry_at["ch"], self.livetv._mono())


class TLSBundleTest(unittest.TestCase):
    """live/tv.py: mpv trusts the system's roots and the lab's CA together, never the lab's alone
    (its tls-ca-file replaces the trust store, so YouTube's streams failed verification)."""

    def setUp(self):
        sys.path.insert(0, os.path.dirname(HERE))
        try:
            from live import tv as livetv
        except ImportError as e:
            self.skipTest(str(e))
        self.livetv = livetv
        self.dir = tempfile.mkdtemp()
        self.sys_ca = os.path.join(self.dir, "system.pem")
        self.lab_ca = os.path.join(self.dir, "lab.crt")
        with open(self.sys_ca, "w") as f:
            f.write("SYSTEM ROOTS\n")
        with open(self.lab_ca, "w") as f:
            f.write("LAB CA\n")

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def test_bundle_has_both(self):
        out = self.livetv.tls_bundle(self.lab_ca, system=(self.sys_ca,), out_dir=self.dir)
        self.assertNotEqual(out, self.lab_ca)
        with open(out) as f:
            text = f.read()
        self.assertIn("SYSTEM ROOTS", text)
        self.assertIn("LAB CA", text)

    def test_no_system_bundle_falls_back_to_the_lab_ca(self):
        out = self.livetv.tls_bundle(self.lab_ca, system=(os.path.join(self.dir, "none.pem"),), out_dir=self.dir)
        self.assertEqual(out, self.lab_ca)

    def test_rewritten_when_the_lab_ca_changes(self):
        out = self.livetv.tls_bundle(self.lab_ca, system=(self.sys_ca,), out_dir=self.dir)
        later = time.time() + 5
        with open(self.lab_ca, "w") as f:
            f.write("NEW LAB CA\n")
        os.utime(self.lab_ca, (later, later))
        self.livetv.tls_bundle(self.lab_ca, system=(self.sys_ca,), out_dir=self.dir)
        with open(out) as f:
            self.assertIn("NEW LAB CA", f.read())


if __name__ == "__main__":
    unittest.main()
