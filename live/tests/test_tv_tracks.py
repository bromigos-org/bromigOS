"""Audio tracks, subtitles and the remote's pause on the den's screens (live/live/tvtracks.py,
live/live/tvhold.py), with stand-in players and a stand-in Jellyfin: no GPU, no desktop, no
network.

    cd live && python -m unittest tests.test_tv_tracks
"""
import json
import os
import sys
import time
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(__file__))
import test_tv_screens as S  # noqa: E402  (the sandboxed environment comes first)

import bromigos_tracks as T  # noqa: E402

MPV_TRACKS = [
    {"id": 1, "type": "video"},
    {"id": 1, "type": "audio", "lang": "jpn", "demux-channel-count": 2, "default": True, "ff-index": 1},
    {"id": 2, "type": "audio", "lang": "eng", "demux-channel-count": 6, "ff-index": 2},
    {"id": 1, "type": "sub", "lang": "eng", "title": "Full", "ff-index": 3},
    {"id": 2, "type": "sub", "lang": "eng", "title": "Signs & Songs", "forced": True, "ff-index": 4},
]
JELLYFIN = [
    {"Index": 0, "Type": "Video"},
    {"Index": 1, "Type": "Audio", "Language": "jpn", "Channels": 2, "IsDefault": True},
    {"Index": 2, "Type": "Audio", "Language": "eng", "Channels": 6},
    {"Index": 3, "Type": "Subtitle", "Language": "eng", "Title": "Full", "IsTextSubtitleStream": True},
    {"Index": 4, "Type": "Subtitle", "Language": "eng", "Title": "Signs & Songs", "IsForced": True,
     "IsTextSubtitleStream": True},
    {"Index": 5, "Type": "Subtitle", "Language": "spa", "IsExternal": True, "IsTextSubtitleStream": True},
]


class TrackPlayer(S.Player):
    """The stand-in player with mpv's track list and the track calls."""
    def __init__(self, tracks=MPV_TRACKS):
        super().__init__()
        self.tracks, self.gen, self.audio, self.sub, self.added = list(tracks), 1, [], [], []

    def track_list(self):
        return self.tracks

    def choose_audio(self, aid):
        self.audio.append(aid)

    def choose_sub(self, sid):
        self.sub.append(sid)

    def add_sub(self, url, title, lang, done=None):
        self.added.append((url, title, lang))
        if done:
            done(9)


class FakeJellyfin:
    name = "library"
    type = "jellyfin"

    def __init__(self, streams=JELLYFIN):
        self.streams = streams

    def video_streams(self, item):
        return self.streams

    def video_subtitle_url(self, item, index, fmt="vtt"):
        return f"https://media.example/Videos/{item['id']}/{item['id']}/Subtitles/{index}/0/Stream.vtt", {}


@unittest.skipUnless(S.livetv is not None, getattr(S, "WHY", "needs PyOpenGL"))
class Base(unittest.TestCase):
    def setUp(self):
        S.sandbox(self)
        state = os.path.join(os.environ["XDG_STATE_HOME"], f"tracks-{id(self)}")
        p = mock.patch.dict(os.environ, XDG_STATE_HOME=state)
        p.start()
        self.addCleanup(p.stop)
        self.tv = S.make_tv(self, {"tv": {"channel": [S.files_channel("Shows", "any", dur=1200)]}})
        self.tv.stop.set()
        self.tv.track_memory = T.Memory()
        for d in self.tv.decks.values():
            d.player = TrackPlayer()
        self.tv.px = {"big": (1188, 678, 200, 175), "wave": (1475, 762, 124, 110), "emblem": (1090, 920, 158, 143)}
        self.tv.rects = dict(self.tv.px)
        self.tv.tune_to("big", 2)

    def load(self, screen="big", stream=None):
        """What _ensure_loaded leaves behind: the item loaded and started."""
        tv = self.tv
        n, ch = tv.channel(screen)
        slot = tv.slot(ch)
        d = tv.decks[screen]
        d.loaded = (ch["key"], str(slot.item["id"]))
        d.stream = stream or {"quality": "direct"}
        d.player.started = True
        return slot

    def tick(self, **k):
        self.tv.drawn_at = S.livetv._mono()
        self.tv.tick(**k)


class MpvTracks(Base):
    def test_english_audio_and_signs_are_chosen_from_mpvs_list(self):
        self.load()
        self.tick()
        p = self.tv.decks["big"].player
        self.assertEqual(p.audio[-1], 2, "English, not the file's Japanese default")
        self.assertEqual(p.sub[-1], 2, "English audio: signs & songs")
        self.assertEqual(self.tv.describe()["screens"]["big"]["tracks"],
                         {"audio": "English · 5.1", "subs": "English · Signs & Songs"})

    def test_the_commands_list_switch_and_remember(self):
        self.load()
        self.tick()
        out = json.loads(self.tv.command("tracks --screen big --json"))
        self.assertTrue(out["can"])
        self.assertEqual([t["id"] for t in out["audio"]], ["m1", "m2"])
        self.assertEqual([t["selected"] for t in out["subs"]], [False, True])
        out = json.loads(self.tv.command("audio m1 --screen big --json"))
        self.assertEqual(out["message"], "Audio: Japanese · Stereo")
        self.assertEqual(self.tv.decks["big"].player.audio[-1], 1)
        out = json.loads(self.tv.command("subs m1 --screen big --json"))
        self.assertTrue(out["sub_on"])
        self.assertEqual(self.tv.decks["big"].player.sub[-1], 1)
        out = json.loads(self.tv.command("subs off --screen big --json"))
        self.assertFalse(out["sub_on"])
        self.assertIsNone(self.tv.decks["big"].player.sub[-1])
        item = self.tv.slot(self.tv.channel("big")[1]).item
        mem = self.tv.track_memory.get(item)
        self.assertEqual((mem["audio"]["lang"], mem["subs"]), ("ja", "off"))
        self.assertFalse(json.loads(self.tv.command("audio m7 --screen big --json"))["ok"])

    def test_the_screens_own_picture_and_a_player_still_opening_say_so(self):
        self.tv.tune_to("wave", 1)
        out = json.loads(self.tv.command("tracks --screen wave --json"))
        self.assertFalse(out["can"])
        self.assertIn("Nothing", out["why"])
        out = json.loads(self.tv.command("tracks --screen big --json"))
        self.assertFalse(out["can"])
        self.assertIn("moment", out["why"])

    def test_sound_off_decodes_no_audio_and_keeps_the_choice(self):
        from live import mpvgl
        real = mpvgl.Player.__new__(mpvgl.Player)          # its track calls, without libmpv
        real.m = _Props(aid="no", sid="no", volume=0, mute=True)
        real.want_aid, real.sound_on = "auto", False
        real.choose_audio(2)
        self.assertEqual(real.m["aid"], "no", "the sound is off: nothing decoded")
        real.sound(True, 40)
        self.assertEqual(real.m["aid"], "2")
        real.sound(False, 40)
        self.assertEqual(real.m["aid"], "no")
        real.choose_sub(3)
        self.assertEqual(real.m["sid"], 3)
        real.choose_sub(None)
        self.assertEqual(real.m["sid"], "no")


class _Props(dict):
    """mpv's properties, as items and attributes."""
    def __getattr__(self, k):
        return self[k]

    def __setattr__(self, k, v):
        self[k] = v


class JellyfinTracks(Base):
    def setUp(self):
        super().setUp()
        self.jf = FakeJellyfin()
        p = mock.patch.object(self.tv, "_jellyfin_of", return_value=self.jf)
        p.start()
        self.addCleanup(p.stop)

    def wait_streams(self):
        for _ in range(100):
            if all(v is not None for v in self.tv.item_streams.values()) and self.tv.item_streams:
                return
            time.sleep(.02)
        self.fail("the track list wasn't read")

    def test_a_direct_stream_is_matched_by_index_and_a_file_beside_it_is_added(self):
        self.load()
        self.tick()
        self.wait_streams()
        self.tick()
        p = self.tv.decks["big"].player
        self.assertEqual(p.audio[-1], 2, "Jellyfin's index 2 is mpv's ff-index 2")
        self.assertEqual(p.sub[-1], 2)
        out = json.loads(self.tv.command("tracks --screen big --json"))
        self.assertEqual([t["id"] for t in out["subs"]], ["j3", "j4", "j5"])
        self.assertTrue(out["subs"][2]["external"])
        self.assertNotIn("media.example", json.dumps(out))
        json.loads(self.tv.command("subs j5 --screen big --json"))
        self.assertIn("/Subtitles/5/0/Stream.vtt", p.added[-1][0])
        self.assertEqual(p.added[-1][1], "Spanish · Full")
        json.loads(self.tv.command("subs j5 --screen big --json"))
        self.assertEqual(len(p.added), 1, "added once; then picked by its mpv id")
        self.assertEqual(p.sub[-1], 9)

    def test_a_transcode_gets_a_new_stream_with_the_chosen_audio(self):
        d = self.tv.decks["big"]
        self.load(stream={"quality": "480p", "audio_index": 1})
        self.tick()
        self.wait_streams()
        self.tick()
        self.assertIsNone(d.loaded, "a new stream with the English track")
        self.assertEqual(self.tv.track_stream_args("big", self.tv.slot(self.tv.channel("big")[1]).item),
                         {"audio_index": 2})
        self.load(stream={"quality": "480p", "audio_index": 2})
        self.tick()
        self.assertIsNotNone(d.loaded)
        self.assertEqual(d.player.audio[-1], "auto", "the transcode carries one track")
        self.assertIn("/Subtitles/4/", d.player.added[-1][0], "signs & songs as WebVTT")


class Pause(Base):
    def test_a_pause_holds_and_play_goes_on_from_there_behind_live(self):
        tv = self.tv
        tv.tune_to("wave", 2)                               # the same channel on another screen
        slot = self.load()
        d = tv.decks["big"]
        key = d.loaded[0]
        self.assertEqual(json.loads(tv.command("pause on --screen big --json"))["held"], True)
        self.assertTrue(d.loaded[0].endswith("~behind-big"), "the player keeps its picture (no reload)")
        self.assertNotEqual(d.loaded[0], key)
        self.assertNotEqual(tv.channel("wave")[1]["key"], tv.channel("big")[1]["key"], "the scope stays live")
        self.tick(covered=set())
        self.assertTrue(d.player.paused_, "held, though in view and drawing")
        self.tick(covered={"big"})
        self.tick(covered=set())
        self.assertTrue(d.player.paused_, "uncovering never undoes the remote's pause")
        first = tv.slot(tv.channel("big")[1])
        time.sleep(.3)
        held = tv.slot(tv.channel("big")[1])
        self.assertEqual(held.item["id"], slot.item["id"])
        self.assertAlmostEqual(first.offset, slot.offset, delta=1.5)
        self.assertAlmostEqual(held.offset, first.offset, delta=.05, msg="frozen while held")
        tv.holds["big"]["held_at"] -= 252                   # as if held four minutes and twelve seconds
        self.assertEqual(tv.hold_tag("big"), "PAUSED · −4:12")
        out = json.loads(tv.command("resume --screen big --json"))
        self.assertFalse(out["held"])
        self.assertAlmostEqual(out["behind"], 252, delta=1.5)
        self.tick(covered=set())
        self.assertFalse(d.player.paused_)
        self.assertTrue(tv.hold_tag("big").startswith("BEHIND LIVE · −4:1"))
        live = tv.slot(tv.channel("wave")[1])
        behind = tv.slot(tv.channel("big")[1])
        self.assertAlmostEqual((live.offset - behind.offset) % 1200, 252, delta=2)
        st = tv.describe()["screens"]["big"]
        self.assertEqual((st["held"], round(st["behind"] / 10)), (False, 25))

    def test_jump_to_live_and_a_channel_change_go_back_to_the_schedule(self):
        tv = self.tv
        self.load()
        tv.hold("big", "on")
        out = json.loads(tv.command("jump-live --screen big --json"))
        self.assertEqual(out["message"], "big: live")
        self.assertNotIn("big", tv.holds)
        self.assertIsNone(tv.decks["big"].loaded, "a new stream at where the channel is now")
        self.assertEqual(tv.jump_live("big"), "big: already live")
        tv.hold("big", "on")
        tv.tune_to("big", 1)
        self.assertNotIn("big", tv.holds)
        self.assertIn("nothing to pause", tv.hold("big", "toggle"))

    def test_something_picked_pauses_without_a_schedule(self):
        tv = self.tv
        item = dict(id="pick-1", title="Picked", duration=600, server="files", url="/media/x.mp4")
        tv.override("big", item)
        self.load()
        tv.hold("big", "toggle")
        self.assertEqual(tv.hold_tag("big"), "PAUSED")
        self.assertIsNone(tv.hold_describe("big")["behind"])
        self.assertEqual(tv.hold("big", "toggle"), "big: playing")
        self.assertIsNone(tv.hold_tag("big"))


class FullScreen(unittest.TestCase):
    """The full-screen player follows the den's choice over its IPC (no mpv started)."""
    def session(self, sel, tracks):
        from live import tvfull
        fs = tvfull.Session.__new__(tvfull.Session)
        fs.sent, fs.track_sel, fs.track_list, fs.subs_added = [], sel, tracks, set()
        fs.send = lambda *c: fs.sent.append(c)
        return fs

    @unittest.skipUnless(S.livetv is not None, getattr(S, "WHY", "needs PyOpenGL"))
    def test_tracks_by_index_a_file_once_and_off(self):
        tl = [dict(t, **{"ff-index": t.get("ff-index")}) for t in MPV_TRACKS]
        fs = self.session({"audio_index": 2, "sub_index": 4, "subs_off": False}, tl)
        fs._apply_tracks()
        self.assertEqual(fs.sent, [("set_property", "aid", 2), ("set_property", "sid", 2)])
        fs = self.session({"audio_index": 1, "sub_index": 5, "sub_url": "https://m/x.vtt", "sub_label": "Spanish · Full",
                           "subs_off": False}, tl)
        fs._apply_tracks()
        fs._apply_tracks()
        self.assertEqual(fs.sent, [("set_property", "aid", 1), ("sub-add", "https://m/x.vtt", "select", "Spanish · Full",
                                                                  ""), ("set_property", "aid", 1)])
        fs = self.session({"audio_index": 2, "subs_off": True}, tl)
        fs._apply_tracks()
        self.assertEqual(fs.sent[-1], ("set_property", "sid", "no"))


if __name__ == "__main__":
    unittest.main()
