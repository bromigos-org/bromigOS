"""bromigos_tracks: track lists from mpv and Jellyfin, labels, the defaults, the memory per
series, and finding subtitles, against stand-ins only (no network, temporary folders)."""
import json
import os
import stat
import sys
import tempfile
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
for p in (os.path.join(ROOT, "lib"), os.path.join(ROOT, "homelab", "lib")):
    if p not in sys.path:
        sys.path.insert(0, p)

import bromigos_tracks as T  # noqa: E402

# A dual-audio anime episode as Jellyfin lists it: Japanese first (the file's default),
# English 5.1, a commentary, full English subtitles, signs & songs, SDH, and a file beside it.
JELLYFIN = [
    {"Index": 0, "Type": "Video", "Codec": "hevc"},
    {"Index": 1, "Type": "Audio", "Language": "jpn", "Codec": "flac", "Channels": 2, "IsDefault": True},
    {"Index": 2, "Type": "Audio", "Language": "eng", "Codec": "eac3", "Channels": 6, "Title": "English 5.1"},
    {"Index": 3, "Type": "Audio", "Language": "eng", "Codec": "aac", "Channels": 2, "Title": "Director's Commentary"},
    {"Index": 4, "Type": "Subtitle", "Language": "eng", "Codec": "ass", "Title": "Full Subtitles",
     "IsTextSubtitleStream": True},
    {"Index": 5, "Type": "Subtitle", "Language": "eng", "Codec": "ass", "Title": "Signs & Songs", "IsForced": True,
     "IsTextSubtitleStream": True},
    {"Index": 6, "Type": "Subtitle", "Language": "eng", "Codec": "PGSSUB", "Title": "SDH",
     "IsHearingImpaired": True, "IsTextSubtitleStream": False},
    {"Index": 7, "Type": "Subtitle", "Language": "spa", "Codec": "srt", "IsExternal": True,
     "IsTextSubtitleStream": True, "Path": "/srv/media/anime/ep.es.srt"},
]
MPV = [
    {"id": 1, "type": "video", "codec": "hevc"},
    {"id": 1, "type": "audio", "lang": "jpn", "codec": "flac", "demux-channel-count": 2, "default": True,
     "ff-index": 1, "selected": True},
    {"id": 2, "type": "audio", "lang": "eng", "codec": "eac3", "demux-channel-count": 6, "ff-index": 2},
    {"id": 1, "type": "sub", "lang": "eng", "title": "Signs/Songs", "forced": True, "ff-index": 5},
    {"id": 2, "type": "sub", "lang": "en", "title": "English", "ff-index": 4},
    {"id": 3, "type": "sub", "lang": "eng", "title": "English [CC]", "ff-index": 6},
    {"id": 4, "type": "sub", "lang": "und", "external": True, "title": "ep.srt"},
]
ITEM = {"id": "ep5", "title": "Ballad of Fallen Angels", "series": "Space Radio", "season": 1, "episode": 5,
        "kind": "episode", "server": "library"}


class Parsing(unittest.TestCase):
    def test_jellyfin_streams_become_tracks_with_kinds_and_labels(self):
        audio, subs = T.from_jellyfin(JELLYFIN)
        self.assertEqual([t["id"] for t in audio], ["j1", "j2", "j3"])
        self.assertEqual([t["label"] for t in audio], ["Japanese · Stereo", "English · 5.1", "English · Commentary"])
        self.assertEqual([t["kind"] for t in audio], ["main", "main", "commentary"])
        self.assertEqual([t["kind"] for t in subs], ["full", "forced", "sdh", "full"])
        self.assertEqual([t["label"] for t in subs],
                         ["English · Full", "English · Signs & Songs", "English · SDH", "Spanish · Full"])
        self.assertTrue(subs[3]["external"])
        self.assertFalse(subs[2]["text"], "picture subtitles can't go as WebVTT")

    def test_mpv_track_list_becomes_tracks(self):
        audio, subs = T.from_mpv(MPV)
        self.assertEqual([t["id"] for t in audio], ["m1", "m2"])
        self.assertTrue(audio[0]["selected"])
        self.assertEqual(audio[1]["ff"], 2)
        self.assertEqual([t["kind"] for t in subs], ["forced", "full", "sdh", "full"])
        self.assertEqual(subs[0]["label"], "English · Signs & Songs")
        self.assertEqual(subs[3]["label"], "ep.srt · Full", "no language: its title")

    def test_language_codes_and_channels(self):
        for code, want in (("eng", "en"), ("en-US", "en"), ("jpn", "ja"), ("ger", "de"), ("und", None), ("", None),
                           ("japanese", "ja"), ("xx1", None)):
            self.assertEqual(T.lang2(code), want, code)
        for n, want in ((1, "Mono"), (2, "Stereo"), ("5.1(side)", "5.1"), (8, "7.1"), (3, "3 ch"), (None, None)):
            self.assertEqual(T.channels_label(n), want)

    def test_public_shape_has_no_paths_or_codecs(self):
        audio, subs = T.from_jellyfin(JELLYFIN)
        out = T.public(audio, subs, "j2", "j5", fetch=True, item=ITEM, screen="big")
        self.assertEqual(out["remembered"], "Space Radio")
        self.assertTrue(out["sub_on"] and out["can"] and out["fetch"])
        self.assertEqual([t["selected"] for t in out["audio"]], [False, True, False])
        text = json.dumps(out)
        for leak in ("/srv", "eac3", "PGSSUB", "flac"):
            self.assertNotIn(leak, text)
        self.assertEqual(T.summary(audio, subs, "j2", None), {"audio": "English · 5.1", "subs": None})


class Defaults(unittest.TestCase):
    def test_english_audio_and_signs_by_default_on_a_dual_audio_file(self):
        audio, subs = T.from_jellyfin(JELLYFIN)
        a, s = T.choose(audio, subs)
        self.assertEqual(a["id"], "j2", "English, not the file's Japanese default")
        self.assertEqual(s["id"], "j5", "English audio: signs & songs")

    def test_english_audio_without_forced_subtitles_has_none(self):
        audio, subs = T.from_jellyfin([s for s in JELLYFIN if s["Index"] != 5])
        self.assertIsNone(T.choose(audio, subs)[1])

    def test_audio_that_isnt_english_turns_english_full_subtitles_on(self):
        audio, subs = T.from_jellyfin([s for s in JELLYFIN if s["Index"] not in (2, 3)])
        a, s = T.choose(audio, subs)
        self.assertEqual(a["lang"], "ja")
        self.assertEqual(s["id"], "j4", "full before forced")
        audio, subs = T.from_jellyfin([s for s in JELLYFIN if s["Index"] in (1, 5)])
        self.assertEqual(T.choose(audio, subs)[1]["id"], "j5", "forced when that's all there is")

    def test_no_english_subtitles_means_none(self):
        audio, subs = T.from_jellyfin([s for s in JELLYFIN if s["Index"] in (0, 1, 7)])
        self.assertEqual(T.choose(audio, subs), (audio[0], None))

    def test_commentary_is_never_the_default_and_the_most_channels_wins(self):
        audio, _ = T.from_jellyfin([
            {"Index": 1, "Type": "Audio", "Language": "eng", "Channels": 2, "Title": "Commentary"},
            {"Index": 2, "Type": "Audio", "Language": "eng", "Channels": 2},
            {"Index": 3, "Type": "Audio", "Language": "eng", "Channels": 8}])
        self.assertEqual(T.default_audio(audio)["id"], "j3")

    def test_nothing_to_choose(self):
        self.assertEqual(T.choose([], []), (None, None))


class Remembered(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.mem = T.Memory(os.path.join(self.tmp.name, "state", "den-tracks.json"))

    def test_a_choice_carries_to_the_next_episode_by_language_and_kind(self):
        audio, subs = T.from_jellyfin(JELLYFIN)
        self.mem.put(ITEM, audio=T.find(audio, "j1"), subs=T.find(subs, "j4"))
        self.assertEqual(stat.S_IMODE(os.stat(self.mem.path).st_mode), 0o600)
        nxt = dict(ITEM, id="ep6", episode=6, title="Toys in the Attic")
        # the next file numbers its streams differently
        renumbered = [dict(s, Index=s["Index"] + 10) for s in JELLYFIN]
        audio2, subs2 = T.from_jellyfin(renumbered)
        a, s = T.choose(audio2, subs2, self.mem.get(nxt))
        self.assertEqual((a["id"], s["id"]), ("j11", "j14"))

    def test_off_is_remembered_and_halves_are_kept(self):
        audio, subs = T.from_jellyfin(JELLYFIN)
        self.mem.put(ITEM, audio=T.find(audio, "j1"), subs=T.find(subs, "j4"))
        self.mem.put(ITEM, subs=None, keep_audio=True)
        row = self.mem.get(ITEM)
        self.assertEqual(row["audio"]["lang"], "ja")
        self.assertEqual(row["subs"], "off")
        a, s = T.choose(audio, subs, row)
        self.assertEqual((a["id"], s), ("j1", None))
        self.mem.put(ITEM, audio=T.find(audio, "j2"), keep_subs=True)
        self.assertEqual(self.mem.get(ITEM)["subs"], "off")

    def test_a_language_that_isnt_there_falls_back_to_the_defaults(self):
        self.mem.put(ITEM, audio={"lang": "de", "kind": "main"}, subs={"lang": "de", "kind": "full"})
        audio, subs = T.from_jellyfin(JELLYFIN)
        a, s = T.choose(audio, subs, self.mem.get(ITEM))
        self.assertEqual((a["id"], s["id"]), ("j2", "j5"))

    def test_films_are_remembered_on_their_own(self):
        film = {"id": "m1", "title": "Knockin' on Heaven's Door", "kind": "movie", "server": "library"}
        self.assertEqual(T.memory_key(film), "item:library:m1")
        self.assertEqual(T.memory_key(ITEM), "series:space radio")
        self.assertIsNone(self.mem.get(film))

    def test_the_memory_is_bounded(self):
        with mock.patch.object(T, "MEMORY_MAX", 3):
            for i in range(5):
                self.mem.put({"id": f"x{i}", "server": "s"}, subs=None)
        with open(self.mem.path) as f:
            self.assertEqual(len(json.load(f)), 3)


class FakeArr:
    def __init__(self, name, type_="arr"):
        self.name, self.type, self.endpoint = name, type_, f"http://{name}.example"


class FakeLab:
    def __init__(self, apps, series=(), movies=(), episodes=()):
        self.apps = {a: FakeArr(a) for a in apps}
        self.series, self.movies, self.episodes = list(series), list(movies), list(episodes)
        self.calls = []

    def app(self, name):
        return self.apps.get(name)

    def arr_get(self, app, path, **q):
        self.calls.append(("get", app, path, q))
        if path == "/series":
            return [s for s in self.series if str(s["tvdbId"]) == str(q.get("tvdbId"))]
        if path == "/episode":
            return [e for e in self.episodes if e["seriesId"] == q.get("seriesId")]
        if path == "/movie":
            return [m for m in self.movies if str(m["tmdbId"]) == str(q.get("tmdbId"))]
        return []

    def call(self, a, path, data=None, method=None, timeout=20):
        self.calls.append((method or "GET", a.name, path))
        return None


class FakeServer:
    name = "library"

    def __init__(self, ids=None, search=0, plugin=True):
        self.ids, self.search, self.plugin = ids or {}, search, plugin
        self.refreshed, self.searched = [], []

    def provider_ids(self, item):
        return self.ids

    def refresh_item(self, item):
        self.refreshed.append(item["id"])

    def has_subtitle_search(self):
        return self.plugin

    def subtitle_search(self, item, lang3):
        self.searched.append(lang3)
        return self.search


class Fetching(unittest.TestCase):
    def setUp(self):
        T._AVAILABLE.clear()

    def test_bazarr_is_asked_for_the_episode_by_sonarr_ids(self):
        lab = FakeLab(["bazarr", "sonarr"], series=[{"id": 7, "tvdbId": 76885}],
                      episodes=[{"id": 70, "seriesId": 7, "seasonNumber": 1, "episodeNumber": 4},
                                {"id": 71, "seriesId": 7, "seasonNumber": 1, "episodeNumber": 5}])
        srv = FakeServer({"kind": "episode", "series_tvdb": "76885", "season": 1, "episode": 5})
        out = T.fetch_subs(ITEM, "en", srv, lab)
        self.assertEqual(out["via"], "bazarr")
        patch = [c for c in lab.calls if c[0] == "PATCH"]
        self.assertEqual(len(patch), 1)
        self.assertIn("seriesid=7", patch[0][2])
        self.assertIn("episodeid=71", patch[0][2])
        self.assertIn("language=en", patch[0][2])
        self.assertEqual(srv.refreshed, ["ep5"], "the server looks beside the video again")
        self.assertEqual(srv.searched, [])

    def test_a_film_goes_by_radarr(self):
        lab = FakeLab(["bazarr", "radarr"], movies=[{"id": 3, "tmdbId": 11299}])
        srv = FakeServer({"kind": "movie", "tmdb": "11299"})
        T.fetch_subs({"id": "m1", "title": "Film", "server": "library"}, "ja", srv, lab)
        self.assertIn("/api/movies/subtitles?radarrid=3&language=ja", [c for c in lab.calls if c[0] == "PATCH"][0][2])

    def test_the_servers_own_search_when_bazarr_doesnt_know_it(self):
        lab = FakeLab(["bazarr", "sonarr"])
        srv = FakeServer({"kind": "episode", "series_tvdb": "1", "season": 1, "episode": 1}, search=4)
        out = T.fetch_subs(ITEM, "en", srv, lab)
        self.assertEqual(out["via"], "server")
        self.assertEqual(srv.searched, ["eng"])

    def test_nothing_found_and_nothing_to_look_with_say_so(self):
        with self.assertRaisesRegex(T.FetchError, "No English subtitles"):
            T.fetch_subs(ITEM, "en", FakeServer(search=0), FakeLab([]))
        with self.assertRaisesRegex(T.FetchError, "Bazarr"):
            T.fetch_subs(ITEM, "en", FakeServer(plugin=False), FakeLab([]))

    def test_available_with_bazarr_or_a_plugin(self):
        self.assertTrue(T.fetch_available(FakeServer(plugin=False), FakeLab(["bazarr", "sonarr"])))
        T._AVAILABLE.clear()
        self.assertTrue(T.fetch_available(FakeServer(plugin=True), FakeLab([])))
        T._AVAILABLE.clear()
        self.assertFalse(T.fetch_available(FakeServer(plugin=False), FakeLab(["bazarr"])))


if __name__ == "__main__":
    unittest.main()
