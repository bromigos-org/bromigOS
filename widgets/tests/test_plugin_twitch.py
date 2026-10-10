"""plugins/twitch.py: Helix answers parsed, the live list merged, chat lines counted (never
kept), the signed-out and unconfigured states, and every size class."""
import os
import sys
import time
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
import plugintest as PT  # noqa: E402
import _kit as K  # noqa: E402
import twitch  # noqa: E402
import bromigos_account as A  # noqa: E402

STREAM = {"id": "1", "user_id": "9", "user_login": "tidewatch", "user_name": "Tidewatch", "game_id": "5",
          "game_name": "Factorio", "type": "live", "title": "Megabase day 41", "viewer_count": 1873,
          "started_at": "2026-10-09T18:00:00Z", "language": "en",
          "thumbnail_url": "https://static-cdn.jtvnw.net/previews-ttv/live_user_tidewatch-{width}x{height}.jpg"}


def quiet_pollers():
    """Pollers that never start a thread (no network in tests)."""
    return mock.patch.object(K.KitPanel, "poller", lambda self, fn, every, idle=None, name="poll", start=True:
                             self.pollers.append(K.Poller(self, fn, every, idle, name, start=False)) or self.pollers[-1])


class Parse(unittest.TestCase):
    def test_stream(self):
        s = twitch.parse_stream(STREAM)
        self.assertEqual((s["login"], s["name"], s["game"], s["viewers"], s["live"]),
                         ("tidewatch", "Tidewatch", "Factorio", 1873, True))
        self.assertAlmostEqual(s["started"], 1791568800.0, delta=1)

    def test_thumbnail_size(self):
        self.assertTrue(twitch.thumb_url(STREAM["thumbnail_url"], 640, 360).endswith("-640x360.jpg"))

    def test_merge_followed_and_watched(self):
        a = twitch.parse_stream(STREAM)
        b = twitch.parse_stream(dict(STREAM, user_login="harbor", user_name="Harbor", viewer_count=12000))
        me = twitch.parse_stream(dict(STREAM, user_login="me", viewer_count=5))
        rows = twitch.merge_live([a, me], [a, b], me_login="me")
        self.assertEqual([r["login"] for r in rows], ["harbor", "tidewatch"])      # most viewers first, not me
        self.assertEqual([r["followed"] for r in rows], [False, True])


class Chat(unittest.TestCase):
    def test_counts_messages_only(self):
        c = twitch.ChatRate("Tidewatch")
        now = time.time()
        self.assertTrue(c.count_line("@badge-info=;color= :a!a@a.tmi.twitch.tv PRIVMSG #tidewatch :hello", now))
        self.assertFalse(c.count_line(":tmi.twitch.tv 001 justinfan123 :Welcome, GLHF!", now))
        self.assertFalse(c.count_line("PING :tmi.twitch.tv", now))
        c.count_line("x PRIVMSG #tidewatch :again", now - 30)
        c.count_line("x PRIVMSG #tidewatch :old", now - 400)
        self.assertEqual(c.per_minute(now), 2)
        self.assertFalse(any(isinstance(x, str) for x in c.stamps))                # no text kept
        c.started = now - 600
        series = c.series(10, now)
        self.assertEqual(series[-1], 2)
        self.assertEqual(sum(v or 0 for v in series), 3)


class States(unittest.TestCase):
    def setUp(self):
        A.KEYRING = A.MemoryKeyring()
        A._cache.clear()

    def test_unconfigured_says_how_to_set_up(self):
        with quiet_pollers():
            p = PT.make(twitch.TwitchPanel)
        tips = " ".join(PT.draw(p, 460, 300))
        self.assertIn("client ID", tips)
        self.assertIn("accounts.toml", tips)

    def test_signed_out_offers_sign_in(self):
        with mock.patch.object(A, "needs", lambda prov: []), quiet_pollers():
            p = PT.make(twitch.TwitchPanel)
            tips = " ".join(PT.draw(p, 460, 300))
        self.assertIn("Sign in to Twitch", tips)

    def test_every_size_class(self):
        PT.every_class(self, PT.make(twitch.TwitchPanel, demo=True))


if __name__ == "__main__":
    unittest.main()
