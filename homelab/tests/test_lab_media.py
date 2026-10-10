"""`bromigos lab media` (mediareq.py, adapters/labrequests.py): the profile picker, anime
detection, the language settings, seasons and episodes, and every command against a fake
media stack (mediafake.py: made-up titles, the real apps' answer shapes). Nothing reaches a
network.

    PYTHONPATH=lib python -m unittest tests.test_lab_media
"""
import contextlib
import io
import json
import os
import sys
import tempfile
import unittest
from unittest import mock

os.environ.setdefault("BROMIGOS_HOMELAB_CONFIG", "/nonexistent")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import mediafake as F                                          # noqa: E402
from bromigos_homelab import config, registry                  # noqa: E402
from bromigos_homelab import mediareq as M                     # noqa: E402

EN = ["en", "ja"]


def by_name(profiles, name):
    return next(p for p in profiles if p["name"] == name)


# ------------------------------------------------------------------ pure parts
class Picker(unittest.TestCase):
    def test_movie_takes_the_best_trash_profile(self):
        c = M.pick_profile("movie", F.RADARR_PROFILES, ["en"], True)
        self.assertEqual(c["name"], "Remux + WEB 2160p")      # not the built-in Ultra-HD, though it allows as much
        self.assertIn("Remux-2160p", c["why"])
        self.assertEqual(c["warnings"], [])

    def test_movie_falls_back_to_1080p_without_a_2160p_profile(self):
        ps = [p for p in F.RADARR_PROFILES if p["name"] not in ("Remux + WEB 2160p", "Ultra-HD")]
        self.assertEqual(M.pick_profile("movie", ps, ["en"], True)["name"], "HD Bluray + WEB")

    def test_a_quality_ceiling(self):
        c = M.pick_profile("movie", F.RADARR_PROFILES, ["en"], True, quality="1080p")
        self.assertEqual(c["name"], "HD Bluray + WEB")

    def test_tv_takes_web_2160p(self):
        self.assertEqual(M.pick_profile("tv", F.SONARR_PROFILES, ["en"], True)["name"], "WEB-2160p")

    def test_anime_english_required_takes_the_english_audio_variant(self):
        c = M.pick_profile("tv", F.SONARR_PROFILES, EN, True, anime=True)
        self.assertEqual(c["name"], "Remux-1080p - Anime (English audio)")
        self.assertIn("English audio required", c["why"])
        self.assertIn("dual audio", c["why"])

    def test_anime_english_preferred(self):
        c = M.pick_profile("tv", F.SONARR_PROFILES, EN, False, anime=True)
        self.assertEqual(c["name"], "Remux-1080p - Anime (English preferred)")

    def test_anime_japanese_takes_the_original_audio_profile(self):
        c = M.pick_profile("movie", F.RADARR_PROFILES, ["ja"], True, anime=True)
        self.assertEqual(c["name"], "Remux-1080p - Anime")
        self.assertIn("original audio", c["why"])

    def test_anime_without_an_anime_profile_says_so(self):
        ps = [p for p in F.SONARR_PROFILES if "Anime" not in p["name"]]
        c = M.pick_profile("tv", ps, EN, True, anime=True)
        self.assertEqual(c["name"], "WEB-2160p")
        self.assertTrue(any("no anime profile" in w for w in c["warnings"]))

    def test_no_profile_matches_the_language(self):
        c = M.pick_profile("tv", F.SONARR_PROFILES, ["ja"], True)
        self.assertTrue(any("no profile here matches" in w for w in c["warnings"]))

    def test_music_takes_lossless(self):
        c = M.pick_profile("music", F.LIDARR_PROFILES)
        self.assertEqual(c["name"], "Lossless")              # lossless and nothing lossy, over "Any"
        self.assertIn("lossless", c["why"])
        c = M.pick_profile("music", [by_name(F.LIDARR_PROFILES, "Standard")])
        self.assertTrue(c["warnings"])

    def test_profile_audio_reads_the_scores(self):
        req = M.profile_audio(by_name(F.SONARR_PROFILES, "Remux-1080p - Anime (English audio)"))
        self.assertEqual(req, {"requires": "en", "english_first": True, "original": False, "dual": True})
        pref = M.profile_audio(by_name(F.SONARR_PROFILES, "Remux-1080p - Anime (English preferred)"))
        self.assertIsNone(pref["requires"])
        self.assertTrue(pref["english_first"])
        self.assertTrue(M.profile_audio(by_name(F.SONARR_PROFILES, "Remux-1080p - Anime"))["original"])
        self.assertEqual(M.profile_audio(by_name(F.SONARR_PROFILES, "WEB-2160p"))["requires"], "en")
        self.assertIsNone(M.profile_audio(by_name(F.SONARR_PROFILES, "Any"))["requires"])

    def test_no_profiles(self):
        self.assertIsNone(M.pick_profile("tv", []))


class Anime(unittest.TestCase):
    def test_signals(self):
        self.assertEqual(M.detect_anime({"keywords": [{"id": 210024, "name": "anime"}]}), (True, "TMDB's anime keyword"))
        self.assertTrue(M.detect_anime({"genres": ["Animation", "Anime"]})[0])
        self.assertTrue(M.detect_anime({"seriesType": "anime"})[0])
        self.assertTrue(M.detect_anime({"genres": [{"name": "Animation"}], "originalLanguage": "ja"})[0])
        self.assertTrue(M.detect_anime({"genres": ["Animation"], "originalLanguage": {"name": "Japanese"}})[0])
        self.assertTrue(M.detect_anime({"genres": ["Animation"], "originCountry": ["JP"]})[0])

    def test_western_animation_isnt_anime(self):
        self.assertFalse(M.detect_anime({"genres": [{"name": "Animation"}], "originalLanguage": "en"})[0])
        self.assertFalse(M.detect_anime({})[0])


class Languages(unittest.TestCase):
    def test_codes(self):
        for v, c in (("en", "en"), ("English", "en"), ("eng", "en"), ("en_US.UTF-8", "en"), ("jpn", "ja"),
                     ("Japanese", "ja"), ("any", "any"), ("", "")):
            self.assertEqual(M.lang_code(v), c, v)

    def test_defaults_come_from_the_desktop(self):
        with mock.patch.dict(os.environ, {"LANG": "ja_JP.UTF-8", "LC_ALL": "", "LC_MESSAGES": ""}):
            d = M.languages({})
        self.assertEqual((d["audio"], d["anime_audio"], d["subtitles"], d["required"]), (["ja"], ["ja"], ["ja"], True))
        self.assertEqual(d["from"], "the desktop's language")

    def test_settings(self):
        d = M.languages({"audio": ["en", "ja"], "anime_audio": ["ja"], "subtitles": "en", "audio_required": False})
        self.assertEqual((d["audio"], d["anime_audio"], d["subtitles"], d["required"]), (EN, ["ja"], ["en"], False))
        self.assertEqual(M.describe_audio(EN, True), "English required, Japanese welcome as a second track")

    def test_edit_media_table(self):
        text = '# mine\nname = "LAB"\n\n[media]\naudio = ["en"]   # spoken\nquality = "best"\n\n[tls]\nca_file = ""\n'
        new = M.edit_media_table(text, {"audio": ["en", "ja"], "subtitles": ["en"]})
        self.assertIn('audio = ["en", "ja"]   # spoken', new)
        self.assertIn('subtitles = ["en"]', new)
        self.assertLess(new.index("subtitles"), new.index("[tls]"))
        self.assertIn("# mine", new)
        gone = M.edit_media_table(new, {"subtitles": None})
        self.assertNotIn("subtitles", gone)
        added = M.edit_media_table('name = "LAB"\n', {"audio": ["ja"]})
        self.assertTrue(added.endswith('[media]\naudio = ["ja"]\n'))

    def test_write_through_a_symlink(self):
        tmp = tempfile.mkdtemp()
        real = os.path.join(tmp, "real.toml")
        with open(real, "w") as f:
            f.write('name = "LAB"\n')
        link = os.path.join(tmp, "homelab.toml")
        os.symlink(real, link)
        M.write_media_settings({"audio": ["en", "ja"]}, link)
        self.assertTrue(os.path.islink(link))
        with open(real) as f:
            self.assertIn('audio = ["en", "ja"]', f.read())


class Seasons(unittest.TestCase):
    def test_parse(self):
        self.assertEqual(M.parse_seasons("all"), "all")
        self.assertEqual(M.parse_seasons("1,3"), [1, 3])
        self.assertEqual(M.parse_seasons("2-4"), [2, 3, 4])
        self.assertEqual(M.parse_seasons("s1, 5-6"), [1, 5, 6])
        self.assertEqual(M.parse_episodes("S02E05,s3e1"), [(2, 5), (3, 1)])
        with self.assertRaises(M.MediaError):
            M.parse_seasons("first")

    def test_describe_monitoring(self):
        s = {"monitored": True, "monitorNewItems": "all", "seasons": [{"seasonNumber": n, "monitored": n in (0, 1, 2, 3)}
                                                                      for n in range(5)]}
        self.assertEqual(M.describe_monitoring(s), "Monitoring seasons 1–3 and specials; new episodes and seasons are "
                                                   "picked up automatically")

    def test_sizes(self):
        rate = M.mb_per_minute(by_name(F.SONARR_PROFILES, "Remux-1080p - Anime (English audio)"), F.qdefs(F.SONARR_Q))
        self.assertAlmostEqual(rate, 138.2)
        self.assertEqual(M.human(94 * 10 ** 9), "94 GB")
        self.assertEqual(M.hm(3 * 3600 + 120), "3 h 02 min")


# ------------------------------------------------------------------ against the fake stack
class Stack(unittest.TestCase):
    apps = None
    media = '[media]\naudio = ["en", "ja"]\nanime_audio = ["en", "ja"]\nsubtitles = ["en"]\n'

    def setUp(self):
        self.srv = F.Server()
        self.st = self.srv.state
        self.tmp = tempfile.mkdtemp(prefix="media-")
        self.toml = F.homelab_toml(os.path.join(self.tmp, "homelab.toml"), self.srv.url, self.apps, self.media)
        self.patches = [mock.patch.object(config, "USER", self.toml),
                        mock.patch.object(M, "STATE_FILE", os.path.join(self.tmp, "state.json")),
                        mock.patch.object(M, "_wait", lambda fn, timeout=60, every=2.0: fn())]
        for p in self.patches:
            p.start()
        config._cache["sig"] = None
        registry._inst["sig"] = None

    def tearDown(self):
        for p in reversed(self.patches):
            p.stop()
        self.srv.close()
        config._cache["sig"] = None
        registry._inst["sig"] = None

    def cli(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err), \
                mock.patch.object(sys.stdin, "isatty", lambda: False):
            code = M.main(list(argv))
        return code, out.getvalue(), err.getvalue()

    def js(self, *argv):
        code, out, err = self.cli(*argv, "--json")
        return code, json.loads(out) if out.strip() else None

    def writes(self, app, method=None, path=None):
        return [w for w in self.st.writes if w[0] == app and (method is None or w[1] == method)
                and (path is None or w[2].endswith(path))]


class Search(Stack):
    def test_search_lists_titles_with_their_profile_and_state(self):
        code, out, _ = self.cli("search", "starlight")
        self.assertEqual(code, 0)
        self.assertIn("tv:tvdb:90001", out)
        self.assertIn("Starlight Harbor, 1999, anime TV, 1 season, ended, Sonarr profile Remux-1080p - Anime "
                      "(English audio), about", out)

    def test_unreleased_film_shows_its_dates(self):
        code, d = self.js("search", "comet")
        self.assertEqual(d[0]["release"], "in cinemas 2027-03-12, digital TBA")
        self.assertIn("in cinemas 2027-03-12, digital TBA", d[0]["summary"])

    def test_in_the_library_already(self):
        self.st.jellyfin_items = [{"Id": "jf1", "Name": "Paper Moon Cafe", "Type": "Series",
                                   "ProviderIds": {"Tvdb": "90004"}, "_seasons": 3, "_episodes": 30}]
        code, d = self.js("search", "paper moon")
        self.assertEqual(d[0]["library"]["jellyfin"]["resolution"], "4K")
        self.assertIn("already in Jellyfin: 4K, 3 seasons, 30 episodes, audio English", d[0]["summary"])

    def test_western_animation_isnt_sent_to_the_anime_profile(self):
        code, d = self.js("search", "toy orchard")
        self.assertFalse(d[0]["anime"])
        self.assertEqual(d[0]["profile"]["name"], "Remux + WEB 2160p")

    def test_youtube_links_go_to_pinchflat(self):
        code, d = self.js("search", "https://www.youtube.com/playlist?list=PL123")
        self.assertEqual(d[0]["kind"], "youtube")


class GetTV(Stack):
    def test_ambiguous_names_ask_which(self):
        code, d = self.js("get", "The Lantern Office", "--yes")
        self.assertEqual(code, 3)
        self.assertEqual(sorted(m["id"] for m in d["matches"]), ["tv:tvdb:90002", "tv:tvdb:90003"])
        self.assertEqual(self.st.writes, [])

    def test_without_yes_or_a_terminal_nothing_is_requested(self):
        code, d = self.js("get", "Starlight Harbor")
        self.assertEqual(code, 2)
        self.assertTrue(d["asked"])
        self.assertEqual(self.st.writes, [])

    def test_new_anime_through_seerr(self):
        code, d = self.js("get", "Starlight Harbor", "--specials", "--yes")
        self.assertEqual(code, 0)
        req = self.st.seerr_requests[0]
        self.assertEqual((req["mediaType"], req["seasons"], req["profileId"], req["rootFolder"]),
                         ("tv", "all", 11, "/media/tv"))
        s = next(iter(self.st.series.values()))
        self.assertEqual(s["seriesType"], "anime")
        self.assertTrue(next(z for z in s["seasons"] if z["seasonNumber"] == 0)["monitored"])
        self.assertIn(("sonarr", {"name": "SeasonSearch", "seriesId": s["id"], "seasonNumber": 0}), self.st.commands)
        self.assertEqual(d["result"]["route"], "seerr")
        self.assertIn("Monitoring season 1 and specials; new episodes and seasons are picked up automatically",
                      d["result"]["monitoring"])
        self.assertIn("subtitles: English (Bazarr)", d["result"]["subtitles"])
        self.assertEqual([p["name"] for p in self.st.bazarr_profiles], ["English"])

    def test_seasons_go_through_seerr_too(self):
        self.cli("get", "tv:tvdb:90002", "--seasons", "2-3", "--new", "no", "--yes")
        self.assertEqual(self.st.seerr_requests[0]["seasons"], [2, 3])
        s = next(iter(self.st.series.values()))
        self.assertEqual(s["monitorNewItems"], "none")

    def test_also_get_a_season_of_a_show_already_there(self):
        sid = self.st.add_series(8004, [1, 2, 3], profile=8)
        code, out, _ = self.cli("get", "Paper Moon Cafe", "--seasons", "4", "--yes")
        self.assertEqual(code, 0, out)
        self.assertEqual(self.st.seerr_requests, [])            # shows in Sonarr change in Sonarr
        s = self.st.series[sid]
        self.assertEqual([z["seasonNumber"] for z in s["seasons"] if z["monitored"]], [1, 2, 3, 4])
        self.assertEqual(s["qualityProfileId"], 8)               # no --quality: its profile stays
        self.assertTrue(all(e["monitored"] for e in self.st.episodes[sid] if e["seasonNumber"] == 4))
        self.assertIn(("sonarr", {"name": "SeasonSearch", "seriesId": sid, "seasonNumber": 4}), self.st.commands)
        self.assertIn("Monitoring seasons 1–4", out)
        self.assertIn("it doesn't add it again", out)

    def test_future_only(self):
        sid = self.st.add_series(8004, [], profile=8, new="none")
        self.cli("get", "tv:tvdb:90004", "--seasons", "future", "--yes")
        self.assertEqual(self.writes("sonarr", "POST", "/seasonpass")[0][3]["monitoringOptions"], {"monitor": "future"})
        self.assertEqual(self.st.series[sid]["monitorNewItems"], "all")
        self.assertFalse([c for c in self.st.commands if c[0] == "sonarr"])       # nothing to search now

    def test_stop_new_episodes(self):
        sid = self.st.add_series(8004, [1, 2], profile=8)
        self.cli("get", "tv:tvdb:90004", "--seasons", "none", "--new", "no", "--yes")
        self.assertEqual(self.st.series[sid]["monitorNewItems"], "none")
        self.assertEqual([z["seasonNumber"] for z in self.st.series[sid]["seasons"] if z["monitored"]], [1, 2])

    def test_episodes(self):
        sid = self.st.add_series(8004, [], profile=8)
        self.cli("get", "tv:tvdb:90004", "--episodes", "S02E05,S03E01", "--yes")
        want = {sid * 1000 + 205, sid * 1000 + 301}
        self.assertEqual({e["id"] for e in self.st.episodes[sid] if e["monitored"]}, want)
        self.assertIn(("sonarr", {"name": "EpisodeSearch", "episodeIds": sorted(want)}),
                      [(a, dict(b, episodeIds=sorted(b.get("episodeIds") or []))) for a, b in self.st.commands])

    def test_better_profile_on_request(self):
        sid = self.st.add_series(8001, [], profile=1)
        self.cli("get", "tv:tvdb:90001", "--quality", "best", "--specials", "--yes")
        s = self.st.series[sid]
        self.assertEqual((s["qualityProfileId"], s["seriesType"], s["monitorNewItems"]), (11, "anime", "all"))
        self.assertEqual([z["seasonNumber"] for z in s["seasons"] if z["monitored"]], [0, 1])
        self.assertIn(("sonarr", {"name": "SeriesSearch", "seriesId": sid}), self.st.commands)

    def test_audio_override(self):
        code, d = self.js("get", "Starlight Harbor", "--audio", "ja")
        self.assertEqual(d["plan"]["profile"]["name"], "Remux-1080p - Anime")


class WithoutSeerr(Stack):
    apps = ("sonarr", "radarr")

    def test_new_show_straight_to_sonarr(self):
        code, out, err = self.cli("get", "tv:tvdb:90001", "--seasons", "latest", "--yes")
        self.assertEqual(code, 0, err)
        post = self.writes("sonarr", "POST", "/series")[0][3]
        self.assertEqual((post["qualityProfileId"], post["seriesType"], post["addOptions"]["monitor"]),
                         (11, "anime", "none"))
        self.assertEqual(self.writes("sonarr", "POST", "/seasonpass")[0][3]["monitoringOptions"]["monitor"],
                         "latestSeason")

    def test_unreleased_film_is_tracked_for_its_home_release(self):
        code, out, err = self.cli("get", "Comet Drift", "--yes")
        self.assertEqual(code, 0, err)
        m = next(iter(self.st.movies.values()))
        self.assertEqual((m["minimumAvailability"], m["qualityProfileId"], m["monitored"]), ("released", 8, True))
        self.assertIn("when it's out at home", out)
        self.assertIn("in cinemas 2027-03-12, digital TBA", out)

    def test_when_cinemas(self):
        self.cli("get", "Comet Drift", "--when", "cinemas", "--yes")
        self.assertEqual(next(iter(self.st.movies.values()))["minimumAvailability"], "inCinemas")


class GetMovie(Stack):
    def test_anime_film_through_seerr(self):
        code, d = self.js("get", "Lanterns of Kiri", "--yes")
        self.assertEqual(code, 0)
        self.assertEqual(self.st.seerr_requests[0]["profileId"], 11)
        self.assertEqual(d["result"]["id"], 200)

    def test_film_already_in_radarr_gets_its_profile_and_a_search(self):
        self.st.movies[250] = dict(F.radarr_lookup(7002), id=250, qualityProfileId=4, monitored=False,
                                   minimumAvailability="announced", hasFile=False)
        code, d = self.js("get", "movie:tmdb:7002", "--quality", "best", "--yes")
        m = self.st.movies[250]
        self.assertEqual((m["qualityProfileId"], m["monitored"], m["minimumAvailability"]), (11, True, "released"))
        self.assertIn(("radarr", {"name": "MoviesSearch", "movieIds": [250]}), self.st.commands)
        self.assertEqual(self.st.seerr_requests, [])


class Music(Stack):
    def test_album_through_lidarr(self):
        code, d = self.js("get", "album:bbbbbbbb-0000-4000-8000-000000000002", "--yes")
        self.assertEqual(code, 0)
        post = self.writes("lidarr", "POST", "/album")[0][3]
        self.assertEqual((post["artist"]["qualityProfileId"], post["monitored"]), (2, True))
        self.assertEqual(d["result"]["route"], "lidarr")
        self.assertIn("Lidarr found it", d["result"]["say"])

    def test_soulseek_when_lidarr_finds_nothing(self):
        self.st.lidarr_finds = False
        flac = [{"filename": f"@@abc\\Music\\Quiet Engines\\Glass Valley\\{i:02d}.flac", "size": 30_000_000}
                for i in range(1, 11)]
        mp3 = [{"filename": f"@@xyz\\mp3\\Glass Valley\\{i:02d}.mp3", "size": 9_000_000} for i in range(1, 11)]
        half = [{"filename": f"@@hhh\\Glass Valley (partial)\\{i:02d}.flac", "size": 30_000_000} for i in range(1, 4)]
        self.st.slskd_responses = [{"username": "mp3fan", "hasFreeUploadSlot": True, "uploadSpeed": 9e6, "files": mp3},
                                   {"username": "half", "hasFreeUploadSlot": True, "uploadSpeed": 9e6, "files": half},
                                   {"username": "flacfan", "hasFreeUploadSlot": True, "uploadSpeed": 1e6, "files": flac}]
        code, d = self.js("get", "album:bbbbbbbb-0000-4000-8000-000000000002", "--yes")
        self.assertEqual(d["result"]["route"], "soulseek")
        self.assertEqual(d["result"]["soulseek"], {"user": "flacfan", "folder": "Glass Valley", "files": 10,
                                                    "lossless": True})
        self.assertIn("Lidarr's indexers found nothing, so Soulseek", d["result"]["say"])
        self.assertEqual(self.st.slskd_search["searchText"], "The Quiet Engines Glass Valley")
        # done: status hands the folder to Lidarr
        for dd in self.st.slskd_downloads:
            for f in dd["directories"][0]["files"]:
                f.update(state="Completed, Succeeded", bytesTransferred=f["size"])
        code, s = self.js("status")
        self.assertEqual(s["imported"][0]["import_path"], "/media/downloads/slskd/Glass Valley")
        self.assertIn(("lidarr", {"name": "DownloadedAlbumsScan", "path": "/media/downloads/slskd/Glass Valley"}),
                      self.st.commands)

    def test_pick_soulseek(self):
        self.assertIsNone(M.pick_soulseek([], 10))


class Status(Stack):
    def test_downloads_join_the_clients(self):
        sid = self.st.add_series(8001, [1], profile=11, files=2, series_type="anime")
        self.st.queue["sonarr"] = [{"seriesId": sid, "seasonNumber": 1, "series": {"title": "Starlight Harbor"},
                                    "episode": {"seasonNumber": 1, "episodeNumber": 3}, "size": 2 * 10 ** 9,
                                    "sizeleft": 10 ** 9, "downloadId": "ABCDEF", "status": "downloading",
                                    "trackedDownloadState": "downloading", "trackedDownloadStatus": "ok",
                                    "languages": [{"name": "English"}, {"name": "Japanese"}], "timeleft": "00:20:00",
                                    "protocol": "torrent", "downloadClient": "qBittorrent", "statusMessages": []},
                                   {"seriesId": sid, "seasonNumber": 1, "series": {"title": "Starlight Harbor"},
                                    "episode": {"seasonNumber": 1, "episodeNumber": 4}, "size": 2 * 10 ** 9,
                                    "sizeleft": 2 * 10 ** 9, "downloadId": "nzo-1", "status": "warning",
                                    "trackedDownloadState": "downloading", "trackedDownloadStatus": "warning",
                                    "languages": [{"name": "Japanese"}], "protocol": "usenet",
                                    "statusMessages": [{"title": "x", "messages": ["No files found are eligible"]}]}]
        self.st.torrents = [{"hash": "abcdef", "name": "SH 03", "progress": 0.75, "dlspeed": 5_000_000, "eta": 200,
                             "size": 2 * 10 ** 9, "amount_left": 5 * 10 ** 8, "state": "downloading"}]
        self.st.sab_slots = [{"nzo_id": "nzo-1", "filename": "SH 04", "percentage": "10", "timeleft": "0:30:00",
                              "mb": "2000", "mbleft": "1800", "status": "Downloading"}]
        self.st.bazarr_profiles = [{"profileId": 1, "name": "English", "items": [{"language": "en"}]}]
        self.st.bazarr_episodes[sid] = [{"subtitles": [{"code2": "en", "path": "/x.srt"}], "missing_subtitles": []},
                                        {"subtitles": [], "missing_subtitles": [{"code2": "en"}]}]
        code, out, err = self.cli("status", "starlight")
        self.assertEqual(code, 0, err)
        self.assertIn("Starlight Harbor: 2 items (1 downloading, 1 stuck)", out)
        self.assertIn("at 5.0 MB/s", out)
        self.assertIn("audio English+Japanese (from the release names)", out)
        self.assertIn("why: No files found are eligible", out)
        self.assertIn("Season 1: monitored, 2 of 26 aired on disk", out)
        self.assertIn("Audio on disk: Japanese (1 file), English+Japanese (1 file)", out)
        self.assertIn("1 file is below the profile's target", out)
        self.assertIn("English subs: found for 1 of 2, searching for 1", out)
        code, d = self.js("status", "starlight")
        item = next(i for i in d["items"] if i["what"] == "S01E03")
        self.assertEqual((item["progress"], item["eta_s"], item["speed"]), (75.0, 200, 5_000_000))
        self.st.torrents[0]["eta"] = 8640000                     # qBittorrent's "never", and Sonarr's own
        self.st.queue["sonarr"][0]["timeleft"] = "587.14:00:00"  # guess: a stall, never "587 d left"
        code, out, _ = self.cli("status")
        self.assertIn("(1 stalled: no seeds or no speed)", out)
        self.assertNotIn(" d ", out.split("Starlight Harbor:")[1].split("\n")[0])

    def test_missing_with_nothing_found_explains_the_indexers(self):
        self.st.add_series(8004, [1], profile=8)
        self.st.prowlarr_results = [{"indexer": "UsenetLike", "title": "x"}]
        code, out, _ = self.cli("status", "paper moon")
        self.assertIn("Prowlarr now: results from UsenetLike (1); nothing from NyaaLike; not asked (failing, paused "
                      "by Prowlarr): BrokenLike", out)

    def test_bazarr_without_providers(self):
        self.st.bazarr_settings = {"enabled_providers": []}
        code, out, _ = self.cli("status")
        self.assertIn("Bazarr has no subtitle providers turned on", out)


class Upcoming(Stack):
    def test_upcoming_lists_episodes_and_home_releases(self):
        self.st.calendar["sonarr"] = [{"airDateUtc": "2026-11-02T02:00:00Z", "seasonNumber": 4, "episodeNumber": 1,
                                       "title": "Reopening", "hasFile": False, "series": {"title": "Paper Moon Cafe"}}]
        self.st.calendar["radarr"] = [{"title": "Comet Drift", "year": 2027, "inCinemas": "2027-03-12T00:00:00Z",
                                       "digitalRelease": "2027-05-01T00:00:00Z", "hasFile": False}]
        with mock.patch.object(M.dt, "date", wraps=M.dt.date) as d:
            d.today.return_value = M.dt.date(2026, 10, 10)
            code, rows = self.js("upcoming", "--days", "365")
        self.assertEqual([(r["title"], r["what"]) for r in rows],
                         [("Paper Moon Cafe", "S04E01"), ("Comet Drift", "in cinemas"), ("Comet Drift", "digital")])

    def test_calendar_feed_marks_only_downloaded_films(self):
        self.st.movies = {201: {"id": 201, "title": "Comet Drift", "tmdbId": 7001, "hasFile": False},
                          202: {"id": 202, "title": "Lanterns of Kiri", "tmdbId": 7002, "hasFile": True}}
        lab = M.Lab()
        ics = M.calendar_ics("movies", lab=lab).decode()
        self.assertIn("UID:Radarr_movie_201_digital\r\nDTSTART;VALUE=DATE:20261020\r\nDTEND;VALUE=DATE:20261021\r\n"
                      "SUMMARY:Comet Drift (Digital Release)\r\nSTATUS:TENTATIVE", ics)
        self.assertIn("SUMMARY:Lanterns of Kiri (Digital Release)\r\nSTATUS:CONFIRMED", ics)
        self.assertNotIn("radarr-key", json.dumps(M.calendar_sources(lab)))
        self.assertEqual([c["name"] for c in M.calendar_sources(lab)], ["TV", "Movies"])


class LanguageCommand(Stack):
    def test_set_show_and_subtitles(self):
        code, d = self.js("language", "set", "en", "ja")
        self.assertEqual(d["audio"], EN)
        code, d = self.js("language", "anime", "ja")
        self.assertEqual(d["anime_audio"], ["ja"])
        code, d = self.js("language", "anime", "same")
        self.assertEqual(d["anime_audio"], EN)
        code, d = self.js("language", "subtitles", "en")
        self.assertIn("Bazarr's default profile is now English", d["bazarr"])
        code, d = self.js("language", "required", "no")
        self.assertFalse(d["required"])
        with open(self.toml) as f:
            text = f.read()
        self.assertIn('audio = ["en", "ja"]', text)
        self.assertIn("audio_required = false", text)
        self.assertIn("[[source]]", text)                     # the rest of the file is kept


class Card(Stack):
    def test_requests_card(self):
        from bromigos_homelab.adapters import labcards
        sid = self.st.add_series(8001, [1], profile=11)
        self.st.queue["sonarr"] = [{"seriesId": sid, "series": {"title": "Starlight Harbor"}, "episode":
                                    {"seasonNumber": 1, "episodeNumber": 1}, "size": 100, "sizeleft": 50,
                                    "trackedDownloadState": "importFailed", "trackedDownloadStatus": "warning",
                                    "statusMessages": [{"messages": ["Not an upgrade"]}], "languages": []}]
        c = labcards._requests_card(None)
        self.assertEqual(c["items"][0]["name"], "Starlight Harbor")
        self.assertEqual(c["items"][0]["state"], "warn")
        self.assertIn("why: Not an upgrade", c["items"][0]["hint"])
        self.assertIn("1 stuck", c["summary"])


class Adapters(unittest.TestCase):
    def test_folders_of_transfers(self):
        from bromigos_homelab.adapters.labrequests import folders_of_transfers
        rec = folders_of_transfers([{"username": "u", "directories": [{"directory": "a\\b\\Album", "files": [
            {"size": 100, "bytesTransferred": 100, "state": "Completed, Succeeded"},
            {"size": 100, "bytesTransferred": 50, "state": "InProgress", "averageSpeed": 10}]}]}])[0]
        self.assertEqual((rec["name"], rec["progress"], rec["state"], rec["eta_s"]), ("Album", 75.0, "downloading", 5))


if __name__ == "__main__":
    unittest.main()
