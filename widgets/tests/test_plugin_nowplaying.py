"""plugins/nowplaying.py: MPRIS metadata, playerctl's output, picking a player, cava's
raw lines, when the visualizer may run, and the empty states. No media player is touched."""
import os
import sys
import time
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "plugins"))
import plugintest as PT  # noqa: E402

import nowplaying as NP  # noqa: E402


class Metadata(unittest.TestCase):
    def test_record_from_mpris(self):
        r = NP.record("spotify.instance42", "playing",
                      {"xesam:title": "Song", "xesam:artist": ["A", "B"], "xesam:album": "LP",
                       "mpris:artUrl": "https://i.scdn.co/image/x", "mpris:length": 247_000_000}, 83_500_000)
        self.assertEqual((r["name"], r["status"], r["artist"]), ("spotify", "Playing", "A, B"))
        self.assertEqual((r["length"], r["position"]), (247.0, 83.5))
        self.assertTrue(r["caps"]["seek"])

    def test_missing_length_and_title_from_url(self):
        r = NP.record("mpv", "Paused", {"xesam:url": "file:///music/drift.flac", "mpris:length": ""})
        self.assertEqual(r["title"], "drift.flac")
        self.assertIsNone(r["length"])

    def test_cli_lines(self):
        out = "spotify\tPlaying\tSong\tArtist\tLP\tfile:///a.png\t200000000\t1000000\n" \
              "firefox.instance_1_2\tPaused\tVideo\t\t\t\t\t\nbroken line\n"
        rows = NP.parse_cli(out)
        self.assertEqual([r["name"] for r in rows], ["spotify", "firefox"])
        self.assertEqual(rows[0]["art"], "file:///a.png")
        self.assertIsNone(rows[1]["length"])

    def test_pick_prefers_setting_then_playing_then_last(self):
        a = NP.record("mpv", "Paused", {})
        b = NP.record("spotify", "Playing", {})
        c = NP.record("firefox.i1", "Playing", {})
        self.assertIs(NP.pick([a, b, c], prefer="mpv"), a)
        self.assertIs(NP.pick([a, b, c]), b)
        self.assertIs(NP.pick([a, b, c], last="firefox.i1"), c)       # two playing: stay on the shown one
        self.assertIsNone(NP.pick([]))

    def test_mmss(self):
        self.assertEqual((NP.mmss(83), NP.mmss(3725), NP.mmss(None)), ("1:23", "1:02:05", "--:--"))


class CavaOutput(unittest.TestCase):
    def test_raw_ascii_line(self):
        self.assertEqual(NP.parse_cava("0;50;100;120;\n"), [0.0, 0.5, 1.0, 1.0])

    def test_garbage(self):
        self.assertIsNone(NP.parse_cava("abc;"))
        self.assertIsNone(NP.parse_cava("\n"))


class Fake:
    kind = "fake"

    def __init__(self, rows):
        self.rows, self.calls = rows, []

    def read(self):
        return list(self.rows)

    def control(self, inst, verb, arg=None):
        self.calls.append((inst, verb, arg))


class Panel(unittest.TestCase):
    def make(self, rows):
        with mock.patch.object(NP, "source", lambda: Fake(rows)):
            return PT.make(NP.NowPlayingPanel)

    def test_no_playerctl(self):
        with mock.patch.object(NP, "source", lambda: None):
            p = PT.make(NP.NowPlayingPanel)
        tips = PT.draw(p, 460, 200)
        self.assertTrue(any("pacman -S playerctl" in t for t in tips))

    def test_nothing_playing(self):
        p = self.make([])
        tips = PT.draw(p, 460, 200)
        self.assertTrue(any("MPRIS" in t for t in tips))

    def test_controls_go_to_the_shown_player(self):
        p = self.make([NP.record("spotify", "Playing", {"xesam:title": "S", "mpris:length": 100_000_000}, 0)])
        PT.draw(p, 460, 200)
        play = next(r for r in p.regions if r[4].startswith("Pause"))
        play[5]()
        seek = next(r for r in p.regions if "Click to jump" in r[4])
        seek[5]()
        self.assertEqual(p.src.calls[0], ("spotify", "play-pause", None))
        self.assertEqual(p.src.calls[1][:2], ("spotify", "seek"))

    def test_visualizer_rules(self):
        p = self.make([NP.record("spotify", "Playing", {"xesam:title": "S"})])
        p.last_class, p.drawn_at = "standard", time.monotonic()
        with mock.patch.object(NP.K, "motion", lambda: "full"):
            self.assertTrue(p.want_visualizer())
            p.drawn_at = time.monotonic() - 10                   # hidden or covered: off
            self.assertFalse(p.want_visualizer())
            p.drawn_at = time.monotonic()
            p.last_class = "compact"                             # no room for it
            self.assertFalse(p.want_visualizer())
        p.last_class = "standard"
        with mock.patch.object(NP.K, "motion", lambda: "reduced"):
            self.assertFalse(p.want_visualizer())
        p.current["status"] = "Paused"
        with mock.patch.object(NP.K, "motion", lambda: "full"):
            self.assertFalse(p.want_visualizer())

    def test_every_size_class(self):
        p = PT.make(NP.NowPlayingPanel, demo=True)
        PT.every_class(self, p)


if __name__ == "__main__":
    unittest.main()
