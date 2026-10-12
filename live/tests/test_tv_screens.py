"""The den TV on every screen at once (live/live/tv.py), picked shows (lib/bromigos_tv.py),
size-appropriate streams (bromigos_homelab's video adapters) and the channel guide's
config writer (lib/bromigos_tvconfig.py). Stand-in Jellyfin and Plex servers
(tests/fake_media.py) and yt-dlp (tests/fake_ytdlp.py); stand-in players: no GPU, no
desktop, no network.

    cd live && python -m unittest tests.test_tv_screens

- every screen plays its own channel at once; none is sent back to channel 1; max_playing;
- the sound on one screen at a time (turning it on, or up, on one turns it off on the
  others); commands on the screen named (--screen, scope, small) or under the pointer;
- a covered screen pauses only when it's muted; a see-through window doesn't cover;
- the hint: a click on its speaker toggles the sound and is never a click on the screen;
  "Your desktop is muted"; YouTube's refusal;
- streams sized to each screen from Jellyfin and Plex (a transcode the screen's height,
  direct only for a small file), full screen at full quality; YouTube's format the
  screen's height; mpv decoding every codec on the GPU;
- YouTube resolved in the background while the screen is covered and uncovered every
  second, with yt-dlp taking seconds per video: the channel starts, and what's next is
  resolved ahead;
- picked shows: shuffled together, or taking turns in season and episode order, each show
  going on where it left off across days; titles matched once and remembered (a renamed
  show still plays); the same on Plex;
- the config writer: comments and other tables kept, a reorder, a removal and its undo,
  screens changed, through a symlink, atomically, and a change that wouldn't parse refused;
- screens = "any", [tv] screens, the aliases.
"""
import atexit
import json
import os
import shutil
import sys
import tempfile
import time
import unittest
import urllib.request
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
# never the user's own cache, state or config: set before bromigos_tv is first imported
# (its paths are read then), whichever test module comes first
if "bromigos_tv" not in sys.modules:
    _SANDBOX = tempfile.mkdtemp(prefix="bromigos-tvscr-env-")
    atexit.register(shutil.rmtree, _SANDBOX, True)
    for _k, _sub in (("XDG_CACHE_HOME", "cache"), ("XDG_STATE_HOME", "state"), ("XDG_CONFIG_HOME", "config")):
        os.environ[_k] = os.path.join(_SANDBOX, _sub)
    os.environ.setdefault("BROMIGOS_HOMELAB_CONFIG", os.path.join(_SANDBOX, "none.toml"))
for p in (os.path.join(REPO, "lib"), os.path.join(REPO, "homelab", "lib"), os.path.dirname(HERE), HERE):
    if p not in sys.path:
        sys.path.insert(0, p)

import bromigos_tv as TV  # noqa: E402
import bromigos_tvconfig as C  # noqa: E402
import fake_media as FM  # noqa: E402

try:
    from live import tv as livetv
    from live import hypr
except ImportError as e:                       # no PyOpenGL: the live layer's own tests skip too
    livetv = hypr = None
    WHY = str(e)


def read(path):
    with open(path) as f:
        return f.read()


def sandbox(t):
    """A test's own cache and state (the module paths point into it)."""
    root = tempfile.mkdtemp(prefix="bromigos-tvscr-")
    t.addCleanup(shutil.rmtree, root, True)
    for name, val in (("CACHE", os.path.join(root, "cache")), ("STATE_DIR", os.path.join(root, "state")),
                      ("STATE", os.path.join(root, "state", "tv.json")),
                      ("ROTATION", os.path.join(root, "state", "tv-rotation.json")),
                      ("PICKS", os.path.join(root, "state", "tv-picks.json"))):
        p = mock.patch.object(TV, name, val)
        p.start()
        t.addCleanup(p.stop)
    p = mock.patch.object(TV, "panel_channel", lambda: None)
    p.start()
    t.addCleanup(p.stop)
    return root


def homelab(t, *servers):
    """bromigos_homelab pointed at the fake servers."""
    from bromigos_homelab import config, registry
    root = tempfile.mkdtemp(prefix="bromigos-tvlab-")
    t.addCleanup(shutil.rmtree, root, True)
    toml = FM.homelab_toml(os.path.join(root, "homelab.toml"), *servers)
    old = config.USER
    config.USER = toml
    config._cache["sig"] = None
    registry._inst["sig"] = None

    def back():
        config.USER = old
        config._cache["sig"] = None
        registry._inst["sig"] = None
    t.addCleanup(back)


def make_tv(t, cfg):
    """A TV whose threads are done before the test's sandbox goes."""
    tv = livetv.TV(cfg, log=lambda *a: None)
    t.addCleanup(lambda: (tv.worker.join(15), tv.resolver.join(15)))
    t.addCleanup(tv.close)
    return tv


def files_channel(name, screens, n=3, dur=600):
    """A files channel with its items in the cache already (no ffprobe)."""
    ch = {"name": name, "files": [f"/media/{name}"], "screens": screens}
    c = TV._entry(ch, set())
    TV._write_json(TV.cache_path(c), {"items": [{"id": f"{c['key']}-{i}", "title": f"{name} {i}", "duration": dur,
                                                 "url": f"/media/{name}/{i}.mp4"} for i in range(n)],
                                      "fetched": time.time() + 3600, "error": None, "definition": TV.content_signature(c)})
    return ch


class Player:
    """mpvgl.Player, pretended: what it was asked."""
    def __init__(self, *a, **k):
        self.loads, self.paused_, self.sounds, self.stopped = [], True, [], 0
        self.ended, self.started, self.has_frame, self.ready = None, False, False, False

    def load(self, url, **k):
        self.loads.append(dict(k, url=url))
        self.started = True

    def pause(self, on):
        self.paused_ = bool(on)

    def paused(self):
        return self.paused_

    def sound(self, on, vol):
        self.sounds.append((on, vol))

    def seek(self, pos):
        self.seeks = getattr(self, "seeks", 0) + 1

    def seeking(self):
        return False

    def stop(self):
        self.stopped += 1

    def position(self):
        return 0.0

    def frame(self, w, h):
        return None

    def close(self):
        pass


@unittest.skipIf(livetv is None, "no PyOpenGL")
class ScreensTest(unittest.TestCase):
    def setUp(self):
        sandbox(self)
        self.cfg = {"tv": {"channel": [files_channel("Shows", ["big"]), files_channel("Clips", ["wave"]),
                                       files_channel("Movies", ["emblem"]),
                                       files_channel("Everywhere", "any")]}}
        self.tv = make_tv(self, self.cfg)
        self.tv.stop.set()
        for d in self.tv.decks.values():
            d.player = Player()
        self.tv.px = {"big": (1188, 678, 200, 175), "wave": (1475, 762, 124, 110), "emblem": (1090, 920, 158, 143)}
        self.tv.rects = dict(self.tv.px)

    def tick(self, **k):
        self.tv.drawn_at = livetv._mono()
        self.tv.tick(**k)

    def test_empty_schedule_stops_the_previous_items_audio_and_stream(self):
        self.tv.tune_to('big',2)
        deck=self.tv.decks['big'];deck.loaded=('shows','old-item')
        deck.stream={'url':'old-stream'}
        with mock.patch.object(self.tv,'slot',return_value=None):
            self.assertEqual(self.tv._picture('big',self.tv.channel('big')[1],200,175,1.0),(None,1.0))
        self.assertEqual(deck.player.stopped,1)
        self.assertIsNone(deck.loaded);self.assertIsNone(deck.stream)

    def test_every_screen_plays_its_own_channel_at_once(self):
        tv = self.tv
        tv.tune_to("big", 2)
        tv.tune_to("wave", 2)
        tv.tune_to("emblem", 2)
        self.assertEqual({s: tv.channel(s)[1]["name"] for s in TV.SCREENS},
                         {"big": "Shows", "wave": "Clips", "emblem": "Movies"})      # nobody sent back to 1
        self.tick()
        self.assertTrue(all(tv.decks[s].allowed for s in TV.SCREENS))
        self.assertEqual(len(tv.media_screens()), 3)
        self.assertEqual(TV.state()["screens"]["big"]["channel"], "shows")           # remembered

    def test_any_screen_and_the_numbers(self):
        for s in TV.SCREENS:
            self.assertEqual([c["name"] for c in self.tv.lineup(s)][-1], "Everywhere")
        self.assertEqual(len(self.tv.lineup("wave")), 3)

    def test_a_screen_starts_on_its_start_channel(self):
        self.cfg["tv"]["start"] = {"big": "Everywhere", "wave": "Clips", "emblem": "Nope"}
        tv = make_tv(self, self.cfg)
        tv.stop.set()
        self.assertEqual({s: tv.channel(s)[1]["name"] for s in TV.SCREENS},
                         {"big": "Everywhere", "wave": "Clips", "emblem": "BURN-IN"})   # a name it lacks: channel 1
        tv.tune_to("wave", 1)                                  # tuned by hand: remembered over the start
        tv2 = make_tv(self, self.cfg)
        tv2.stop.set()
        self.assertEqual(tv2.channel("wave")[0], 1)
        self.assertEqual(tv2.channel("big")[1]["name"], "Everywhere")

    def test_the_same_channel_on_two_screens_decodes_once(self):
        tv = self.tv
        tv.tune_to("big", 3)                                   # Everywhere
        tv.tune_to("wave", 3)                                  # Everywhere too
        tv.tune_to("emblem", 2)
        self.tick()
        self.assertEqual(tv.follows, {"wave": "big"})
        self.assertFalse(tv.decks["wave"].allowed)
        self.assertTrue(tv.decks["big"].allowed)
        tv.set_sound("wave", on=True)                          # the sound's screen decodes for both
        self.tick()
        self.assertEqual(tv.follows, {"big": "wave"})
        self.assertEqual(json.loads(tv.command("state --json"))["screens"]["big"]["follows"], "wave")

    def test_bumpers(self):
        tv = self.tv
        tv.tune_to("big", 2)
        ch = tv.channel("big")[1]
        slot = TV.Slot(item={"id": "x", "title": "Episode 4", "series": "Example", "kind": "episode", "season": 1,
                             "episode": 4}, offset=2.0, start=time.time() - 2, end=time.time() + 600)
        with mock.patch.object(tv, "slot", lambda c: slot):
            self.assertIsNone(tv._bumper("big"))               # not asked for
            ch["bumpers"] = True
            b = tv._bumper("big")
            self.assertEqual(b[:3], ("bumper", "Shows", "Example S1E4 · Episode 4"))
            slot["offset"] = 30.0
            self.assertIsNone(tv._bumper("big"))               # only the first seconds

    def test_max_playing(self):
        tv = self.tv
        self.cfg["tv"]["max_playing"] = 2
        for s in TV.SCREENS:
            tv.tune_to(s, 2)
        tv.set_sound("emblem", on=True)
        self.tick()
        self.assertEqual({s for s in TV.SCREENS if tv.decks[s].capped}, {"wave"})   # the sound's screen plays first
        self.assertTrue(tv.decks["emblem"].allowed and tv.decks["big"].allowed)

    def test_sound_on_one_screen_at_a_time(self):
        tv = self.tv
        for s in TV.SCREENS:
            tv.tune_to(s, 2)
        tv.set_sound("big", on=True)
        tv.set_sound("wave", on=True)
        self.assertEqual([s for s in TV.SCREENS if tv.screens[s]["sound"]], ["wave"])
        self.assertEqual(tv.sound_screen(), "wave")
        v = tv.screens["emblem"]["volume"]
        tv.set_sound("emblem", volume=v + 5)                  # turning one up from silent turns it on there
        self.assertEqual([s for s in TV.SCREENS if tv.screens[s]["sound"]], ["emblem"])
        self.tick()
        with mock.patch("live.sound.muted", lambda: False):
            tv._apply_sound()
        heard = {s: tv.decks[s].player.sounds[-1][0] for s in TV.SCREENS}
        self.assertEqual(heard, {"big": False, "wave": False, "emblem": True})
        self.assertEqual(sum(1 for s in TV.state()["screens"].values() if s["sound"]), 1)

    def test_an_old_state_with_two_sounds(self):
        TV.save_state({"screens": {"big": {"channel": "shows", "sound": True}, "wave": {"channel": "clips",
                                                                                         "sound": True}}})
        tv = make_tv(self, self.cfg)
        tv.stop.set()
        self.assertEqual([s for s in TV.SCREENS if tv.screens[s]["sound"]], ["big"])

    def test_commands_take_a_screen(self):
        tv = self.tv
        self.assertEqual(tv.parse("set 2 --screen scope"), ("set", "wave", ["2"]))
        self.assertEqual(tv.parse("sound on --screen=small"), ("sound", "emblem", ["on"]))
        self.assertEqual(tv.parse("volume 40 big"), ("volume", "big", ["40"]))
        self.assertIn("no screen called", tv.command("next --screen kitchen"))
        tv.command("set 2 --screen wave")
        self.assertEqual(tv.channel("wave")[0], 2)
        tv.hover = "emblem"                                      # the pointer's screen, when none is named
        tv.command("next")
        self.assertEqual(tv.channel("emblem")[0], 2)
        tv.hover = None
        tv.command("sound on --screen big")
        tv.command("sound on --screen wave")
        self.assertEqual(json.loads(tv.command("state --json"))["sound_from"], "wave")

    def test_covered_pauses_only_a_muted_screen(self):
        tv = self.tv
        for s in TV.SCREENS:
            tv.tune_to(s, 2)
        tv.set_sound("big", on=True)
        self.tick(covered={"big", "wave"})
        self.assertTrue(tv.decks["big"].allowed)              # sound on: plays behind the window
        self.assertFalse(tv.decks["big"].player.paused())
        self.assertFalse(tv.decks["wave"].allowed)             # muted and covered: paused
        self.assertTrue(tv.decks["wave"].player.paused())
        self.assertTrue(tv.decks["emblem"].allowed)

    def test_the_hints_speaker_is_never_a_click_on_the_screen(self):
        tv = self.tv
        tv.tune_to("big", 2)
        tv.layout_info = (2560, 1440, (0, 0), 1)
        tv.pointer_motion(1188 + 100, 678 + 80)
        self.assertEqual(tv.hover, "big")
        with mock.patch("live.glkit.texture_from_cairo", lambda surf: 1), \
                mock.patch.object(livetv.GL, "glDeleteTextures", lambda *a: None):
            tv.hint_texture(1)
        btn = {a: (x, y, w, h) for x, y, w, h, a in tv.buttons}
        hx, hy = tv.hint_rect[:2]
        x, y, w, h = btn["speaker"]
        with mock.patch.object(tv, "open_full", side_effect=AssertionError("a click on the hint opened the screen")):
            out = tv.click(hx + x + w / 2, hy + y + h / 2)
        self.assertIn("sound on", out)
        self.assertTrue(tv.screens["big"]["sound"])
        self.assertIn(tuple(int(round(v)) for v in tv.hint_rect), tv.input_rects())    # the hint takes the pointer
        self.assertIn("guide", btn)
        x, y, w, h = btn["skip"]
        with mock.patch.object(tv, "skip_item", return_value="Next item") as skip:
            self.assertEqual(tv.click(hx + x + w / 2, hy + y + h / 2), "Next item")
        skip.assert_called_once_with("big")

    def test_the_hint_says_the_desktop_is_muted(self):
        tv = self.tv
        tv.tune_to("big", 2)
        tv.set_sound("big", on=True)
        tv.desktop_muted = True
        self.assertEqual(tv._hint_note("big"), "Your desktop is muted")
        tv.desktop_muted = False
        with mock.patch("live.sound.muted", lambda: True):
            self.assertIn("muted", tv._hint_note("big"))
        self.assertIn("Sound comes from the big monitor", tv._hint_note("wave"))

    def test_a_new_channel_never_shows_the_last_ones_frame(self):
        tv = self.tv
        tv.tune_to("big", 2)
        d = tv.decks["big"]
        slot = tv.slot(tv.channel("big")[1])
        tv._ensure_loaded(d, tv.channel("big")[1], slot)
        self.assertEqual(len(d.player.loads), 1)
        tv.tune_to("big", 3)                                   # "Everywhere"
        ch = tv.channel("big")[1]
        tv._ensure_loaded(d, ch, tv.slot(ch))
        self.assertEqual(len(d.player.loads), 2)
        self.assertIn("Everywhere", d.player.loads[-1]["url"])
        self.assertIsNotNone(d.tune)                           # the channel change's static and number


@unittest.skipIf(livetv is None, "no PyOpenGL")
class CoveringTest(unittest.TestCase):
    def answers(self, opacity):
        def req(cmd, as_json=True):
            if cmd == "monitors":
                return [{"name": "DP-1", "x": 0, "y": 0, "activeWorkspace": {"id": 1}, "specialWorkspace": {"id": -99}}]
            if cmd == "activewindow":
                return {"address": "0xb"}
            if cmd == "clients":
                return [{"address": "0xa", "workspace": {"id": 1}, "at": [1000, 600], "size": [400, 400]},
                        {"address": "0xb", "workspace": {"id": -99}, "at": [1400, 700], "size": [400, 300]}]
            if cmd.startswith("getprop address:0xa"):
                return {"opacity_inactive": opacity["a"]}
            if cmd.startswith("getprop address:0xb"):
                return {"opacity": opacity["b"]}
            if cmd.startswith("getoption"):
                return {"float": 1.0}
            return None
        return req

    def test_only_an_opaque_window_covers(self):
        rects = {"big": (1188, 678, 200, 175), "wave": (1475, 762, 124, 110), "emblem": (1090, 1100, 158, 143)}
        with mock.patch.object(hypr, "request", self.answers({"a": 1.0, "b": 0.8})):
            self.assertEqual(hypr.covered("DP-1", rects, 0.9), {"big"})            # the see-through one doesn't
        with mock.patch.object(hypr, "request", self.answers({"a": 0.85, "b": 1.0})):
            self.assertEqual(hypr.covered("DP-1", rects, 0.9), {"wave"})


@unittest.skipIf(livetv is None, "no PyOpenGL")
class SizedStreamTest(unittest.TestCase):
    """What each screen asks the server for."""

    def setUp(self):
        sandbox(self)

    def tv(self, server, channel):
        homelab(self, server)
        cfg = {"tv": {"channel": [channel]}}
        tv = make_tv(self, cfg)
        tv.stop.set()
        tv.px = {"big": (1188, 678, 200, 175), "wave": (1475, 762, 124, 110), "emblem": (1090, 920, 158, 143)}
        ch = TV.channels(cfg)[0]
        TV.fetch_items(ch, max_age=0)
        return tv, ch

    def check(self, srv, height_key, *expect):
        tv, ch = self.tv(srv, {"name": "Shows", "source": srv.type, "library": "Shows", "screens": "any"})
        slot = TV.now_next(ch)
        self.assertIsNotNone(slot, TV.cached_items(ch))
        got = {}
        for s in TV.SCREENS:
            st = tv.stream(ch, slot, screen=s)
            urllib.request.urlopen(urllib.request.Request(st["url"], headers=st["headers"]), timeout=5).read(64)
            got[s] = st["quality"]
        full = tv.stream(ch, slot, full=True)
        return got, full, srv

    def test_jellyfin_a_big_file_is_transcoded_to_each_screens_height(self):
        srv = FM.FakeJellyfin(bitrate_kbps=60000, height=2160)              # a 4K remux
        self.addCleanup(srv.close)
        got, full, srv = self.check(srv, "MaxHeight")
        self.assertEqual(got, {"big": "360p", "wave": "240p", "emblem": "240p"})
        asked = srv.requests("master.m3u8")
        self.assertTrue(any("MaxHeight=360" in p for p in asked) and any("MaxHeight=240" in p for p in asked), asked)
        self.assertTrue(all("test-key" not in p for p, _h in srv.seen))        # the key in a header, never the URL
        self.assertEqual(full["quality"], "direct")                             # full screen: the file itself

    def test_jellyfin_a_small_file_plays_as_it_is(self):
        srv = FM.FakeJellyfin(bitrate_kbps=900, height=360)
        self.addCleanup(srv.close)
        got, _full, srv = self.check(srv, "MaxHeight")
        self.assertEqual(got["big"], "direct")
        self.assertEqual(got["wave"], "direct")                                 # 900 kbit/s: under 3 x 240p's

    def test_plex_too(self):
        srv = FM.FakePlex(bitrate_kbps=40000, height=1080)
        self.addCleanup(srv.close)
        got, full, srv = self.check(srv, "videoResolution")
        self.assertEqual(got, {"big": "360p", "wave": "240p", "emblem": "240p"})
        asked = srv.requests("start.m3u8")
        self.assertTrue(any("videoResolution=640x360" in p for p in asked), asked)
        self.assertTrue(any("videoResolution=426x240" in p for p in asked), asked)
        self.assertEqual(full["quality"], "direct")

    def test_youtube_asks_for_the_screens_height(self):
        self.assertIn("height<=240", livetv.yt_format(165, False))
        self.assertIn("height<=360", livetv.yt_format(262, True))
        import bromigos_youtube as Y
        self.assertTrue(Y.stream_format(360).startswith("bv*[height<=360][vcodec^=avc1]+ba"))

    def test_mpv_decodes_every_codec_on_the_gpu(self):
        from live import mpvgl
        seen = {}

        class MPV:
            def __init__(self, **k):
                seen.update(k)

            def event_callback(self, _name):
                return lambda f: f
        fake = mock.MagicMock()
        fake.MPV = MPV
        with mock.patch.object(mpvgl, "_mpv", fake), mock.patch.object(mpvgl, "_proc_address", lambda: None):
            mpvgl.Player(log=lambda *a: None, ytdl=False)
        self.assertEqual((seen["hwdec"], seen["hwdec_codecs"]), ("auto", "all"))
        self.assertEqual(seen["scale"], "bilinear")
        self.assertFalse(seen["ytdl"])


class OpeningPlayer(Player):
    """A stand-in player that opens what it's given on the (fake) server, as mpv would."""
    def load(self, url, **k):
        super().load(url, **k)
        if url.startswith("http"):
            try:
                req = urllib.request.Request(url, headers=k.get("headers") or {})
                urllib.request.urlopen(req, timeout=5).read(64)
            except OSError:
                pass


@unittest.skipIf(livetv is None, "no PyOpenGL")
class StreamOpensTest(unittest.TestCase):
    """The den never floods a server: at most one stream per playing screen, none for a
    screen that shares another's, none for prefetch, and each one ended when its screen
    moves on. Frames drawn through tv.gl() with GL stood in for, players that open their
    stream on a fake Jellyfin or Plex that counts every open."""

    def setUp(self):
        sandbox(self)
        for target, val in (("live.glkit.texture_from_cairo", lambda surf: 1), ("live.glkit.texture_rgba", lambda *a: 1),
                            ("live.mpvgl.available", lambda: (True, "")), ("live.mpvgl.Player", OpeningPlayer)):
            p = mock.patch(target, val)
            p.start()
            self.addCleanup(p.stop)
        p = mock.patch.object(livetv.GL, "glDeleteTextures", lambda *a: None)
        p.start()
        self.addCleanup(p.stop)

    def make(self, srv, extra=()):
        homelab(self, srv)
        cfg = {"tv": {"channel": [{"name": "Shows", "source": srv.type, "library": "Shows"},
                                  {"name": "Films", "source": srv.type, "library": "Movies"}] + list(extra)}}
        for ch in TV.channels(cfg):
            TV.fetch_items(ch, max_age=0)
        tv = make_tv(self, cfg)
        tv.stop.set()
        tv.px = {"big": (1188, 678, 200, 175), "wave": (1475, 762, 124, 110), "emblem": (1090, 920, 158, 143)}
        tv.rects = dict(tv.px)
        return tv

    def frames(self, tv, n, covered=lambda i: set()):
        for i in range(n):
            tv.drawn_at = livetv._mono()
            tv.tick(covered=covered(i))
            tv.gl()

    def test_a_transcode_opens_once_however_the_screen_is_covered(self):
        srv = FM.FakeJellyfin(bitrate_kbps=60000, height=2160, codec="hevc", bit_depth=10)   # a 4K remux
        self.addCleanup(srv.close)
        tv = self.make(srv)
        tv.tune_to("big", 2)
        self.frames(tv, 40, covered=lambda i: {"big"} if i % 2 else set())
        opens = srv.opens()
        self.assertEqual(len(opens), 1, opens)
        self.assertNotIn("StartTimeTicks=", opens[0])                    # Jellyfin 10.11 fails every segment with it
        self.assertGreater(tv.decks["big"].player.loads[0]["start"], 0)  # mpv seeks there instead
        self.assertIn("DeviceId=bromigos-den-tv-big", opens[0])
        self.assertEqual(srv.stopped, [])

    def test_two_screens_on_one_channel_open_one_stream(self):
        srv = FM.FakeJellyfin(bitrate_kbps=60000, height=2160, codec="hevc", bit_depth=10)
        self.addCleanup(srv.close)
        tv = self.make(srv)
        tv.tune_to("big", 2)
        tv.tune_to("wave", 2)
        self.frames(tv, 40, covered=lambda i: {"big"} if i % 3 == 0 else set())
        self.assertEqual(len(srv.opens()), 1, srv.opens())
        self.assertIn(tv.follows, ({"wave": "big"}, {"big": "wave"}))     # whichever started, it stays

    def test_changing_channel_ends_the_last_stream(self):
        srv = FM.FakeJellyfin(bitrate_kbps=60000, height=2160, codec="hevc", bit_depth=10)
        self.addCleanup(srv.close)
        tv = self.make(srv)
        for n in (2, 3, 2, 3, 1, 2):
            tv.tune_to("big", n)
            self.frames(tv, 6)
        time.sleep(0.5)                                                  # the stops go on a thread
        self.assertEqual(len(srv.opens()), 5, srv.opens())               # one per media tune, channel 1 none
        self.assertEqual(len(srv.stopped), 4, srv.stopped)               # each one ended when it was left
        self.assertTrue(all("PlaySessionId=" in x for x in srv.stopped))

    def test_a_drifting_player_is_put_back_once_not_every_frame(self):
        srv = FM.FakeJellyfin()                                          # a direct stream: kept to the clock
        self.addCleanup(srv.close)
        tv = self.make(srv)
        tv.tune_to("big", 2)
        self.frames(tv, 3)
        d = tv.decks["big"]
        d.player.has_frame = True
        d.loaded_at -= 20                                                # long since opened, and 0 s in: drifted
        t_end = time.time() + 2.5
        while time.time() < t_end:                                       # 30 frames a second
            self.frames(tv, 1)
            time.sleep(1 / 30)
        self.assertEqual(getattr(d.player, "seeks", 0), 1)               # one seek, not one a frame
        self.assertEqual(len(srv.opens()), 1)

    def test_a_small_h264_file_plays_as_it_is(self):
        srv = FM.FakeJellyfin(bitrate_kbps=4000, height=1080, codec="h264")
        self.addCleanup(srv.close)
        tv = self.make(srv)
        tv.tune_to("big", 2)
        tv.tune_to("emblem", 3)
        self.frames(tv, 20)
        opens = srv.opens()
        self.assertEqual(len(opens), 2, opens)
        self.assertTrue(all("/stream?static=true" in p for p in opens), opens)      # no transcode at all
        self.assertTrue(all(ld.get("start") for d in tv.decks.values() if d.player for ld in d.player.loads))

    def test_prefetch_never_opens_a_server_stream(self):
        srv = FM.FakeJellyfin()
        self.addCleanup(srv.close)
        tv = self.make(srv)
        tv.tune_to("big", 2)
        ch = tv.channel("big")[1]
        before = len(srv.opens())
        tv._prefetch("big", ch, tv.slot(ch))
        self.assertEqual(len(srv.opens()), before)

    def test_plex_too(self):
        srv = FM.FakePlex(bitrate_kbps=60000, height=2160, codec="hevc", bit_depth=10)
        self.addCleanup(srv.close)
        tv = self.make(srv)
        tv.tune_to("big", 2)
        tv.tune_to("wave", 2)
        self.frames(tv, 30, covered=lambda i: {"big"} if i % 2 else set())
        opens = srv.opens()
        self.assertEqual(len(opens), 1, opens)
        self.assertNotIn("offset=0&", opens[0])                          # the transcode starts where it's on
        ld = tv.decks["big"].player.loads[0]
        self.assertIsNone(ld.get("start"))                               # …so mpv doesn't seek again
        tv.tune_to("big", 3)
        tv.tune_to("wave", 3)
        self.frames(tv, 6)
        time.sleep(0.5)
        self.assertEqual(len(srv.stopped), 1, srv.stopped)


@unittest.skipIf(livetv is None, "no PyOpenGL")
class YouTubeResolveTest(unittest.TestCase):
    """yt-dlp slow (seconds a video), the screen covered and uncovered every second: the
    channel still starts, and the next videos are resolved ahead."""

    def setUp(self):
        sandbox(self)
        for k, v in (("BROMIGOS_YTDLP", os.path.join(HERE, "fake_ytdlp.py")), ("FAKE_YTDLP_SLEEP", "3"),
                     ("FAKE_YTDLP_LOG", os.path.join(TV.CACHE, "ytdlp.log"))):
            p = mock.patch.dict(os.environ, {k: v})
            p.start()
            self.addCleanup(p.stop)
        os.makedirs(TV.CACHE, exist_ok=True)

    def channel(self, ids, dur=90):
        ch = TV._entry({"name": "Clips", "youtube": "https://www.youtube.com/playlist?list=PLexample",
                        "screens": ["big"]}, set())
        TV._write_json(TV.cache_path(ch), {"items": [
            {"id": i, "title": f"Clip {i}", "duration": dur, "url": f"https://www.youtube.com/watch?v={i}"}
            for i in ids], "fetched": time.time() + 3600, "error": None, "definition": TV.content_signature(ch)})
        cfg = {"tv": {"channel": [{"name": "Clips", "youtube": "https://www.youtube.com/playlist?list=PLexample",
                                   "screens": ["big"], "order": "in order"}]}}
        tv = make_tv(self, cfg)
        tv.px = {"big": (1188, 678, 200, 175)}
        d = tv.decks["big"]
        d.player = Player()
        tv.tune_to("big", 2)
        return tv, d

    def test_slow_resolves_with_the_screen_covered_and_uncovered(self):
        tv, d = self.channel(["aaa", "bbb", "ccc", "ddd"])
        t_end = time.time() + 25
        covered = False
        while time.time() < t_end and not d.player.loads:
            covered = not covered
            tv.drawn_at = livetv._mono()
            tv.tick(covered={"big"} if covered else set())
            ch = tv.channel("big")[1]
            slot = tv.slot(ch)
            tv._ensure_loaded(d, ch, slot)
            tv._check_failure(d, ch, slot)
            time.sleep(1.0)
        self.assertTrue(d.player.loads, "never started")
        ld = d.player.loads[-1]
        self.assertIn("googlevideo.com", ld["url"])
        self.assertIn("itag=251", ld["audio"])                         # its sound, ready when it's turned on
        self.assertIsNone(ld.get("ytdl_format"))                       # mpv never runs yt-dlp for the den
        tv._prefetch("big", tv.channel("big")[1], tv.slot(tv.channel("big")[1]))
        t_end = time.time() + 15
        while time.time() < t_end and len(tv.resolved) < 3:
            time.sleep(0.2)
        self.assertGreaterEqual(len(tv.resolved), 3, list(tv.resolved))   # what's on and the next two
        self.assertTrue(all(h == 360 for _u, h in tv.resolved))           # 175 px x 1.5 = 262: the 360p format

    def test_a_refusal_shows_in_the_hint(self):
        tv, d = self.channel(["agegate1", "agegate2"])
        os.environ["FAKE_YTDLP_SLEEP"] = "0"
        t_end = time.time() + 10
        while time.time() < t_end and "clips" not in tv.notes:
            ch = tv.channel("big")[1]
            tv._ensure_loaded(d, ch, tv.slot(ch))
            time.sleep(0.2)
        self.assertIn("YouTube refused: Sign in to confirm your age", tv._hint_note("big"))


class PicksTest(unittest.TestCase):
    def setUp(self):
        sandbox(self)

    def make(self, srv, order, shows=("Test Card", "Night Shift"), **more):
        homelab(self, srv)
        ch = TV._entry(dict({"name": "Block", "source": srv.type, "shows": list(shows), "order": order}, **more), set())
        doc = TV.fetch_items(ch, max_age=0)
        self.assertIsNone(doc["error"], doc)
        return ch, doc

    def sequence(self, ch, t0, n):
        out, t = [], t0
        for _ in range(n):
            s = TV.now_next(ch, t)
            out.append((s.item["series"], s.item["episode"]))
            t = s.end + 0.001
        return out

    def test_taking_turns_in_order(self):
        srv = FM.FakeJellyfin()
        self.addCleanup(srv.close)
        ch, _doc = self.make(srv, "alternate")
        self.assertEqual(ch["order"], "in order")
        t0 = TV.day_start(time.time())
        seq = self.sequence(ch, t0 + 1, 6)
        self.assertEqual(seq, [("Test Card", 1), ("Night Shift", 1), ("Test Card", 2), ("Night Shift", 2),
                               ("Test Card", 3), ("Night Shift", 1)])                 # a shorter show goes round

    def test_each_show_goes_on_where_it_left_off(self):
        srv = FM.FakeJellyfin()
        self.addCleanup(srv.close)
        ch, _doc = self.make(srv, "in order")
        t0 = TV.day_start(time.time()) + 1
        TV.rotation_advance(ch, t0)                               # the worker's first anchor
        later = t0 + 3 * FM.CLIP + 5                              # the 4th item: Night Shift E2
        TV.rotation_advance(ch, later, every=0)                   # anchored there (a day's walk kept short)
        st = TV.rotation_state(ch["key"])
        self.assertEqual(st["turn"], "show:s2")
        nxt_day = later + 24 * 3600
        s = TV.now_next(ch, st["t"] + 1)
        self.assertEqual((s.item["series"], s.item["episode"]), ("Night Shift", 2))
        self.assertIsNotNone(TV.now_next(ch, nxt_day))            # the next day goes on from the anchor, no reset
        TV.rotation_advance(ch, nxt_day, every=0)
        self.assertGreater(TV.rotation_state(ch["key"])["t"], st["t"])

    def test_shuffled_together(self):
        srv = FM.FakeJellyfin()
        self.addCleanup(srv.close)
        ch, doc = self.make(srv, "shuffle")
        self.assertEqual(len(doc["items"]), 5)
        seen = {s for s, _e in self.sequence(ch, TV.EPOCH + 1000, 12)}
        self.assertEqual(seen, {"Test Card", "Night Shift"})
        a = [x for x in self.sequence(ch, TV.EPOCH + 1000, 5)]
        self.assertEqual(a, self.sequence(ch, TV.EPOCH + 1000, 5))   # the same, every time

    def test_skip_picked_rotation_survives_worker_anchor_refresh(self):
        srv = FM.FakeJellyfin()
        self.addCleanup(srv.close)
        ch, _doc = self.make(srv, "in order")
        t = TV.day_start(time.time()) + 20
        TV.rotation_advance(ch, t)
        before = TV.now_next(ch, t)
        moved = TV.channel_step(ch, t=t)
        self.assertEqual(moved.item["id"], before.next["id"])
        self.assertAlmostEqual(moved.offset, 0, places=3)
        TV.rotation_advance(ch, t + 30, every=0)
        self.assertEqual(TV.now_next(ch, t + 30).item["id"], moved.item["id"])
        self.assertAlmostEqual(TV.now_next(ch, t + 30).offset, 30, places=3)
        self.assertEqual(TV.now_next(ch, moved.end + .01).item["id"], moved.next["id"])

    def test_titles_matched_once_and_remembered(self):
        srv = FM.FakeJellyfin()
        self.addCleanup(srv.close)
        ch, _doc = self.make(srv, "shuffle")
        memory = json.loads(read(TV.PICKS))
        self.assertEqual(memory["jellyfin"]["show"]["test card"]["id"], "s1")
        listed = len(srv.requests("IncludeItemTypes=Series"))
        old = FM.SHOWS["s1"]
        FM.SHOWS["s1"] = ("Test Card (2026)", old[1])                # renamed on the server
        try:
            TV.fetch_items(ch, max_age=0)
            doc = TV.cached_items(ch)
            self.assertEqual(len(doc["items"]), 5)                  # still plays: matched by its id
            self.assertEqual(len(srv.requests("IncludeItemTypes=Series")), listed)   # not listed again
        finally:
            FM.SHOWS["s1"] = old

    def test_a_missing_show_says_so(self):
        srv = FM.FakeJellyfin()
        self.addCleanup(srv.close)
        homelab(self, srv)
        ch = TV._entry({"name": "Block", "source": "jellyfin", "shows": ["Test Card", "Nope"]}, set())
        doc = TV.fetch_items(ch, max_age=0)
        self.assertIn("Nope", doc["error"])
        self.assertEqual(len(doc["items"]), 3)

    def test_movies_and_collections(self):
        srv = FM.FakeJellyfin()
        self.addCleanup(srv.close)
        ch, doc = self.make(srv, "in order", shows=("Test Card",), items=["Colour Bars", "m2"], collections=["Marathon"])
        self.assertEqual([g[0] for g in doc["groups"]], ["show:s1", "items", "collection:c1"])
        seq = []
        t = TV.day_start(time.time()) + 1
        for _ in range(4):
            s = TV.now_next(ch, t)
            seq.append(s.item["title"])
            t = s.end + 0.001
        self.assertEqual(seq, ["Episode 1", "Colour Bars", "Colour Bars", "Episode 2"])

    def test_plex(self):
        srv = FM.FakePlex()
        self.addCleanup(srv.close)
        ch, doc = self.make(srv, "in order")
        self.assertEqual(self.sequence(ch, TV.day_start(time.time()) + 1, 3),
                         [("Test Card", 1), ("Night Shift", 1), ("Test Card", 2)])


class ScreensOptionTest(unittest.TestCase):
    def test_screens_values(self):
        self.assertEqual(TV.screens_of("any"), ["big", "wave", "emblem"])
        self.assertEqual(TV.screens_of(["scope", "small"]), ["wave", "emblem"])
        self.assertEqual(TV.screens_of(None), ["big", "wave", "emblem"])        # every screen by default
        with mock.patch.object(TV, "panel_channel", lambda: None):
            chans = TV.channels({"tv": {"screens": ["wave"], "channel": [{"name": "A", "files": "/x"},
                                                                         {"name": "B", "files": "/y",
                                                                          "screens": "all"}]}})
        self.assertEqual([c["screens"] for c in chans], [["wave"], ["big", "wave", "emblem"]])


class ConfigWriterTest(unittest.TestCase):
    TEXT = """# my live config
[general]
monitor = "DP-1"   # my screen

# The den TV: my channels
[[tv.channel]]
name = "Shows"           # the shows
source = "jellyfin"
library = "Shows"

# films, shuffled
[[tv.channel]]
name = "Movies"
library = "Movies"
screens = [
  "big",   # mine
  "emblem",
]

[radial]
items = [{ name = "A", cmd = "a" }]

[[tv.channel]]
name = "YouTube"
youtube = "https://www.youtube.com/playlist?list=PLx"
order = "in order"
"""

    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="bromigos-tvcfg-")
        self.addCleanup(shutil.rmtree, self.root, True)
        self.real = os.path.join(self.root, "dotfiles", "config.toml")
        os.makedirs(os.path.dirname(self.real))
        with open(self.real, "w") as f:
            f.write(self.TEXT)
        self.link = os.path.join(self.root, "config.toml")
        os.symlink(self.real, self.link)

    def names(self, doc):
        return [c["name"] for c in doc.channels()]

    def test_comments_and_other_tables_kept(self):
        doc = C.load(self.link)
        doc.move(0, 2)
        doc.set(0, "name", "Films")
        doc.save()
        self.assertTrue(os.path.islink(self.link))                       # still a link
        text = read(self.real)
        for kept in ("# my live config", 'monitor = "DP-1"   # my screen', "# The den TV: my channels",
                     "# films, shuffled", 'name = "Films"', "[radial]", 'items = [{ name = "A", cmd = "a" }]',
                     'name = "Shows"           # the shows'):
            self.assertIn(kept, text)
        self.assertEqual(self.names(C.load(self.link)), ["Films", "YouTube", "Shows"])
        self.assertLess(text.index("# The den TV"), text.index("# films, shuffled"))    # the section's intro stays
        self.assertLess(text.index("# films, shuffled"), text.index('name = "Films"'))   # a channel's own goes with it

    def test_remove_and_undo(self):
        doc = C.load(self.link)
        back = doc.remove(1)
        doc.save()
        self.assertNotIn("# films, shuffled", read(self.real))
        doc = C.load(self.link)
        doc.restore(*back)
        doc.save()
        self.assertEqual(self.names(C.load(self.link)), ["Shows", "Movies", "YouTube"])
        self.assertIn("# films, shuffled", read(self.real))

    def test_screens_and_new_channels(self):
        doc = C.load(self.link)
        doc.set(1, "screens", "any")
        doc.set(2, "order", None)
        i = doc.add({"name": "Block", "shows": ["Example Show", "Another Show"], "order": "in order",
                     "screens": ["wave"]})
        doc.save()
        chans = C.load(self.link).channels()
        self.assertEqual(chans[1]["screens"], "any")
        self.assertNotIn("order", chans[2])
        self.assertEqual((i, chans[3]["shows"]), (3, ["Example Show", "Another Show"]))

    def test_refused_when_it_would_break(self):
        doc = C.load(self.link)
        doc.text += "\n[general]\nmonitor = 1\n"
        with self.assertRaises(C.ConfigError):
            doc.save()
        doc = C.load(self.link)
        doc.text = doc.text.replace('monitor = "DP-1"', 'monitor = "HDMI-1"')
        with self.assertRaises(C.ConfigError):                           # more than the channels
            doc.save()
        self.assertEqual(read(self.real), self.TEXT)

    def test_a_missing_file(self):
        doc = C.load(os.path.join(self.root, "new", "config.toml"))
        doc.add({"name": "Shows", "library": "Shows"})
        doc.save()
        self.assertEqual(self.names(C.load(os.path.join(self.root, "new", "config.toml"))), ["Shows"])


if __name__ == "__main__":
    unittest.main()
