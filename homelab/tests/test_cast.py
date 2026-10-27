"""bromigos_cast: one list of targets, play, control and hand back, against stand-ins only.

No test reaches the network: the Cast, DLNA, AirPlay and Jellyfin libraries are fakes put in
sys.modules or mocks, the den is a fake live state, and every path is a temporary folder.
"""
import contextlib
import io
import json
import os
import stat
import sys
import tempfile
import types
import unittest
import uuid
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
for p in (os.path.join(ROOT, "lib"), os.path.join(ROOT, "homelab", "lib")):
    if p not in sys.path:
        sys.path.insert(0, p)

import bromigos_cast as C  # noqa: E402
from bromigos_homelab.adapters import labvideo  # noqa: E402

TOKEN = "test-token-not-real"
ITEM = dict(id="ep5", title="Ballad of Fallen Angels", series="Space Radio", season=1, episode=5,
            kind="episode", server="library", duration=1440)
STATE = {"screens": {
    "big": {"channel": 2, "name": "Night Block", "now": "Space Radio S1E5", "offset": 300.0, "volume": 40,
            "sound": True, "item": ITEM, "source": "library"},
    "wave": {"channel": 1, "name": "SCOPE", "volume": 60, "sound": False}}}


class FakeServer:
    """A media server adapter: what video_cast_url builds on."""
    name = "library"

    def video_cast_url(self, item, hls=True):
        return (f"http://media.example/Videos/{item['id']}/master.m3u8?api_key={TOKEN}" if hls
                else f"http://media.example/Videos/{item['id']}/stream?api_key={TOKEN}"), \
            ("application/x-mpegURL" if hls else "video/mp4")


class Recorder(C.Backend):
    """A stand-in protocol: records what it was asked."""
    def __init__(self, kind, rows, ok=True):
        self.kind, self.rows, self.ok, self.calls = kind, rows, ok, []

    def available(self):
        return (True, None) if self.ok else (False, f"{self.kind} library isn't installed")

    def discover(self, timeout):
        return [dict(r) for r in self.rows]

    def play(self, target, item, start):
        url, mime = C.media_url(item, self.hls)
        self.calls.append(("play", target["id"], item["id"], start, url, mime))

    def control(self, target, op, value):
        self.calls.append(("control", target["id"], op, value))

    def status(self, target):
        return C.playing("Space Radio S1E5", "playing", 812.4, 1440, 35)


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        env = mock.patch.dict(os.environ, XDG_CACHE_HOME=self.tmp.name + "/cache", XDG_STATE_HOME=self.tmp.name + "/state",
                              XDG_RUNTIME_DIR=self.tmp.name + "/run", XDG_CONFIG_HOME=self.tmp.name + "/config",
                              BROMIGOS_CAST_CALLER="test")
        env.start()
        self.addCleanup(env.stop)
        os.makedirs(self.tmp.name + "/run")
        self.cast = Recorder("cast", [dict(id="cast:11111111-2222-3333-4444-555555555555", kind="cast",
                                           name="Living Room TV", model="Google Chromecast", can=["play"],
                                           _host="192.0.2.10", _port=8009)])
        self.dlna = Recorder("dlna", [dict(id="dlna:uuid:tv", kind="dlna", name="Bedroom TV", model="Example TV",
                                           can=["play"], _location="http://192.0.2.11:1400/desc.xml")])
        self.dlna.hls = False
        backends = dict(C.BACKENDS, cast=self.cast, dlna=self.dlna, airplay=Recorder("airplay", [], ok=False),
                        jellyfin=Recorder("jellyfin", [], ok=False))
        p = mock.patch.object(C, "BACKENDS", backends)
        p.start()
        self.addCleanup(p.stop)
        p = mock.patch("bromigos_tvchannels.live_state", return_value=STATE)
        p.start()
        self.addCleanup(p.stop)
        p = mock.patch.object(C, "_video_source", return_value=FakeServer())
        p.start()
        self.addCleanup(p.stop)

    def audit_rows(self):
        with open(C._audit_path()) as f:
            return [json.loads(x) for x in f]


class Targets(Base):
    def test_one_list_den_first_private_fields_never_shown(self):
        out = C.targets(timeout=1)
        ids = [t["id"] for t in out["targets"]]
        self.assertEqual(ids[:2], ["den:big", "den:wave"])
        self.assertIn("cast:11111111-2222-3333-4444-555555555555", ids)
        self.assertNotIn("192.0.2", json.dumps(out))
        self.assertEqual(out["protocols"]["airplay"], {"available": False, "why": "airplay library isn't installed"})
        big = out["targets"][0]
        self.assertEqual(big["playing"]["title"], "Space Radio S1E5")
        self.assertEqual(big["playing"]["volume"], 40)
        cache = C._cache_path()
        self.assertEqual(stat.S_IMODE(os.stat(cache).st_mode), 0o600)
        with open(cache) as f:
            self.assertIn("192.0.2.10", f.read())          # kept privately, for the next command

    def test_dry_run_writes_nothing(self):
        out = C.targets(timeout=1, dry_run=True)
        self.assertTrue(out["ok"])
        self.assertFalse(os.path.exists(C._cache_path()))

    def test_find_by_id_and_words(self):
        C.targets(timeout=1)
        self.assertEqual(C.find("living room chromecast")["id"], self.cast.rows[0]["id"])
        self.assertEqual(C.find("the bedroom TV")["kind"], "dlna")
        self.assertEqual(C.find("den:wave")["name"], "Den · scope")
        with self.assertRaises(C.CastError) as e:
            C.find("den")
        self.assertEqual(e.exception.code, 3)               # several: say which
        with self.assertRaises(C.CastError):
            C.find("kitchen")


class Play(Base):
    def test_title_plays_with_the_servers_stream_but_nothing_prints_the_token(self):
        with mock.patch("bromigos_tvplay.resolve", return_value=ITEM), \
                contextlib.redirect_stdout(io.StringIO()) as out:
            code = C.main(["play", "--target", "living room", "--title", "Space Radio S01E05", "--json"])
        self.assertEqual(code, 0)
        result = json.loads(out.getvalue())
        self.assertEqual(result["item"]["episode"], 5)
        self.assertNotIn(TOKEN, out.getvalue())
        call = self.cast.calls[-1]
        self.assertEqual(call[:4], ("play", self.cast.rows[0]["id"], "ep5", 0))
        self.assertIn(TOKEN, call[4])                       # only the target is given it
        self.assertEqual(call[5], "application/x-mpegURL")
        rows = self.audit_rows()
        self.assertEqual(rows[-1]["action"], "play")
        self.assertEqual(rows[-1]["caller"], "test")
        with open(C._audit_path()) as f:
            self.assertNotIn(TOKEN, f.read())

    def test_den_screen_hands_off_from_the_same_moment_and_dlna_gets_the_file(self):
        C.play("bedroom tv", screen="big")
        call = self.dlna.calls[-1]
        self.assertEqual((call[2], call[3]), ("ep5", 300.0))
        self.assertIn("/stream?", call[4])
        with self.assertRaises(C.CastError):
            C.play("bedroom tv", screen="wave")             # its own picture: nothing to cast

    def test_control_status_and_errors_as_json(self):
        result = C.control("living room", "volume", "35")
        self.assertEqual(self.cast.calls[-1], ("control", self.cast.rows[0]["id"], "volume", 35.0))
        self.assertEqual(result["playing"]["volume"], 35)
        with contextlib.redirect_stdout(io.StringIO()) as out:
            code = C.main(["control", "--target", "living room", "seek", "--json"])
        self.assertEqual(code, 2)
        self.assertEqual(json.loads(out.getvalue()), {"ok": False, "error": "seek needs a number", "code": 2})
        with contextlib.redirect_stdout(io.StringIO()) as out:
            code = C.main(["control", "--target", "x", "explode", "--json"])
        self.assertEqual(code, 2)
        self.assertFalse(json.loads(out.getvalue())["ok"])

    def test_handback_stops_the_target_and_plays_on_from_its_position(self):
        with mock.patch("bromigos_tvplay.resolve", return_value=ITEM):
            C.play("living room", title="Space Radio S01E05")
        with mock.patch("bromigos_tvplay.resolve", return_value=ITEM) as resolve, \
                mock.patch("bromigos_tvplay.play", return_value={"ok": True, "message": "Playing"}) as play:
            out = C.handback("living room", "scope")
        resolve.assert_called_with(id_="ep5", source="library")
        self.assertEqual(self.cast.calls[-1][2], "stop")
        screen, = play.call_args.args
        self.assertEqual(screen, "wave")
        self.assertEqual(play.call_args.kwargs["item"]["position"], 812.4)
        self.assertTrue(play.call_args.kwargs["resume"])
        self.assertEqual(out["position"], 812)
        self.assertEqual(self.audit_rows()[-1]["action"], "handback")


class FakeCastModule:
    """Enough of pychromecast for the Cast backend."""
    def __init__(self):
        self.played, self.youtube = [], []
        test = self
        info = types.SimpleNamespace(uuid=uuid.UUID(int=7), friendly_name="Living Room TV", model_name="Chromecast",
                                     manufacturer="Google Inc.", cast_type="cast", host="192.0.2.10", port=8009)

        class MC:
            status = types.SimpleNamespace(player_state="PLAYING", title="Space Radio", adjusted_current_time=12.0,
                                           duration=1440.0)

            def play_media(self, url, mime, **kw):
                test.played.append((url, mime, kw))

            def block_until_active(self, timeout=None):
                pass

            def update_status(self):
                pass

        class Cast:
            is_idle = False
            app_display_name = "Default Media Receiver"
            status = types.SimpleNamespace(volume_level=.5, volume_muted=False)

            def __init__(self):
                self.media_controller = MC()

            def wait(self, timeout=None):
                pass

            def disconnect(self, timeout=None):
                pass

            def register_handler(self, h):
                pass

        class YT:
            def play_video(self, vid):
                test.youtube.append(vid)

        browser = types.SimpleNamespace(stop_discovery=lambda: None)
        self.mod = types.SimpleNamespace(
            discovery=types.SimpleNamespace(discover_chromecasts=lambda timeout: ([info], browser)),
            get_chromecast_from_host=lambda host, **kw: Cast())
        self.yt = types.SimpleNamespace(YouTubeController=YT)


class CastBackend(unittest.TestCase):
    def test_discover_play_and_youtube_with_a_fake_pychromecast(self):
        fake = FakeCastModule()
        with mock.patch.dict(sys.modules, {"pychromecast": fake.mod, "pychromecast.controllers": types.ModuleType("c"),
                                           "pychromecast.controllers.youtube": fake.yt}), \
                mock.patch.object(C, "_video_source", return_value=FakeServer()):
            b = C.Cast()
            self.assertEqual(b.available(), (True, None))
            rows = b.discover(1)
            self.assertEqual(rows[0]["id"], f"cast:{uuid.UUID(int=7)}")
            self.assertEqual(rows[0]["playing"]["title"], "Space Radio")
            self.assertEqual(rows[0]["playing"]["volume"], 50)
            b.play(rows[0], ITEM, 30)
            url, mime, kw = fake.played[-1]
            self.assertEqual(mime, "application/x-mpegURL")
            self.assertEqual(kw["current_time"], 30.0)
            self.assertEqual(kw["title"], "Space Radio S1E5 · Ballad of Fallen Angels")
            b.play(rows[0], dict(id="https://www.youtube.com/watch?v=abcdefghijk", url="https://www.youtube.com/watch?v=abcdefghijk",
                                 server="youtube", kind="video", title="Clip"), 0)
            self.assertEqual(fake.youtube, ["abcdefghijk"])

    def test_missing_libraries_say_what_to_install(self):
        with mock.patch.dict(sys.modules, {"pychromecast": None, "pyatv": None, "async_upnp_client.profiles.dlna": None}):
            self.assertIn("python-pychromecast", C.Cast().available()[1])
            self.assertIn("python-pyatv", C.AirPlay().available()[1])
            self.assertIn("python-async-upnp-client", C.Dlna().available()[1])


class JellyfinBackend(unittest.TestCase):
    def test_sessions_exclude_the_den_and_play_only_its_own_items(self):
        a = mock.Mock()
        a.name = "library"
        a.remote_sessions.return_value = [
            dict(Id="s1", DeviceId="tv-1", DeviceName="Lounge TV", Client="Jellyfin Android TV", SupportsRemoteControl=True,
                 PlayableMediaTypes=["Video"], NowPlayingItem=dict(Name="Pilot", SeriesName="Space Radio", RunTimeTicks=14400000000),
                 PlayState=dict(PositionTicks=600000000, IsPaused=True, VolumeLevel=30)),
            dict(Id="s2", DeviceId=C.DEN_DEVICE, DeviceName="den", SupportsRemoteControl=True),
            dict(Id="s3", DeviceId="radio", DeviceName="Speaker", SupportsRemoteControl=True, PlayableMediaTypes=["Audio"])]
        with mock.patch.object(C, "_jellyfins", return_value=[a]):
            b = C.Jellyfin()
            rows = b.discover(1)
            self.assertEqual([r["id"] for r in rows], ["jellyfin:tv-1"])
            self.assertEqual(rows[0]["playing"], C.playing("Space Radio · Pilot", "paused", 60, 1440, 30))
            b.play(rows[0], ITEM, 90)
            a.remote_play.assert_called_with("s1", "ep5", 90)
            with self.assertRaises(C.CastError):
                b.play(rows[0], dict(ITEM, server="other"), 0)
            b.control(rows[0], "pause", None)
            a.remote_playstate.assert_called_with("s1", "Pause")
            b.control(rows[0], "seek", 120.0)
            a.remote_playstate.assert_called_with("s1", "Seek", 120.0)
            b.control(rows[0], "volume", 20.0)
            a.remote_command.assert_called_with("s1", "SetVolume", {"Volume": "20"})


class DlnaBackend(unittest.TestCase):
    def test_play_sets_the_uri_then_plays_and_seeks(self):
        calls = []

        class Dmr:
            has_seek_rel_time = has_volume_level = has_volume_mute = True
            volume_level, is_volume_muted = .2, False
            transport_state, media_title, media_position, media_duration = "PLAYING", "Pilot", 5, 100
            device = types.SimpleNamespace(udn="uuid:tv", friendly_name="Bedroom TV", manufacturer="Example",
                                           model_name="TV")

            async def async_update(self):
                calls.append("update")

            async def construct_play_media_metadata(self, url, title, **kw):
                return f"<DIDL-Lite>{title}</DIDL-Lite>"

            async def async_set_transport_uri(self, url, title, meta):
                calls.append(("uri", url, title, meta))

            async def async_wait_for_can_play(self):
                pass

            async def async_play(self):
                calls.append("play")

            async def async_seek_rel_time(self, t):
                calls.append(("seek", t.total_seconds()))

            async def async_set_volume_level(self, v):
                calls.append(("volume", round(v, 2)))

        async def device(self, location):
            return Dmr()

        with mock.patch.object(C.Dlna, "_device", device), mock.patch.object(C, "_video_source", return_value=FakeServer()):
            b = C.Dlna()
            target = dict(id="dlna:uuid:tv", kind="dlna", name="Bedroom TV", _location="http://192.0.2.11/desc.xml")
            b.play(target, ITEM, 60)
            uri = next(c for c in calls if c[0] == "uri")
            self.assertIn("/stream?", uri[1])
            self.assertIn("<DIDL-Lite>", uri[3])
            self.assertIn(("seek", 60.0), calls)
            b.control(target, "volume-up", None)
            self.assertIn(("volume", .25), calls)
            self.assertEqual(b.status(target)["state"], "playing")
            with self.assertRaises(C.CastError):
                b.play(target, dict(ITEM, server="youtube"), 0)


class CastUrls(unittest.TestCase):
    def test_jellyfin_and_plex_put_the_token_in_the_address_for_the_target_only(self):
        with mock.patch("bromigos_homelab.config.resolve", return_value=TOKEN):
            j = labvideo.JellyfinVideo.__new__(labvideo.JellyfinVideo)
            j.name, j.endpoint, j.opts = "library", "https://media.lab.example", {"auth_ref": "@file:x",
                                                                                 "cast_url": "http://192.0.2.5:8096"}
            url, mime = j.video_cast_url(dict(ITEM, bitrate=4000), hls=True)
            self.assertTrue(url.startswith("http://192.0.2.5:8096/Videos/ep5/master.m3u8?"))
            self.assertIn("api_key=" + TOKEN, url)
            self.assertIn("DeviceId=bromigos-cast", url)
            self.assertEqual(mime, "application/x-mpegURL")
            url, mime = j.video_cast_url(ITEM, hls=False)
            self.assertIn("/Videos/ep5/stream?static=true", url)
            self.assertEqual(mime, "video/mp4")
            p = labvideo.PlexVideo.__new__(labvideo.PlexVideo)
            p.name, p.endpoint, p.opts = "plex", "https://plex.lab.example", {"auth_ref": "@file:x"}
            url, mime = p.video_cast_url(dict(id="42", part="/library/parts/9/file.mkv"), hls=False)
            self.assertEqual(url, f"https://plex.lab.example/library/parts/9/file.mkv?X-Plex-Token={TOKEN}")


if __name__ == "__main__":
    unittest.main()
