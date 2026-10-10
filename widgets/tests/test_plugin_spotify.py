"""plugins/spotify.py: the Web API's answers, the errors a click can meet, the signed-out
and unconfigured states, and every size class. No network; nobody signs in."""
import os
import sys
import time
import unittest
import urllib.error
from unittest import mock

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "plugins"))
import plugintest as PT  # noqa: E402

import spotify as SP  # noqa: E402

PLAYER = {"device": {"name": "Kitchen", "type": "Speaker", "volume_percent": 40}, "is_playing": True,
          "progress_ms": 61000, "shuffle_state": False, "repeat_state": "context", "context": {"type": "album"},
          "item": {"id": "t1", "name": "Track", "type": "track", "duration_ms": 200000,
                   "artists": [{"name": "A"}, {"name": "B"}],
                   "album": {"name": "LP", "images": [{"url": "https://i/640", "width": 640},
                                                     {"url": "https://i/300", "width": 300},
                                                     {"url": "https://i/64", "width": 64}]},
                   "external_urls": {"spotify": "https://open.spotify.com/track/t1"}}}


class Parse(unittest.TestCase):
    def test_player(self):
        p = SP.parse_player(PLAYER)
        self.assertTrue(p["active"] and p["playing"])
        self.assertEqual((p["device"], p["volume"], p["position"]), ("Kitchen", 40, 61.0))
        t = p["track"]
        self.assertEqual((t["title"], t["artist"], t["album"], t["length"]), ("Track", "A, B", "LP", 200.0))
        self.assertEqual(t["art"], "https://i/300")

    def test_nothing_playing(self):
        self.assertEqual(SP.parse_player({}), {"active": False})

    def test_episode(self):
        t = SP.track({"name": "Ep", "type": "episode", "duration_ms": 1000, "show": {"name": "Pod"}, "images": []})
        self.assertEqual((t["artist"], t["album"], t["kind"]), ("Pod", "Pod", "episode"))

    def test_queue_and_recent(self):
        q = SP.parse_queue({"queue": [PLAYER["item"], None]})
        self.assertEqual([t["title"] for t in q], ["Track"])
        r = SP.parse_recent({"items": [{"track": PLAYER["item"], "played_at": "2026-10-09T20:00:00.123Z"}]})
        self.assertAlmostEqual(r[0]["played_at"], 1791576000.123, places=2)

    def test_click_errors(self):
        def err(code):
            return urllib.error.HTTPError("https://x", code, "x", {}, None)
        self.assertIn("Premium", SP.control_error(err(403)))
        self.assertIn("no active Spotify device", SP.control_error(err(404)))
        self.assertIn("sign in again", SP.control_error(err(401)))


class States(unittest.TestCase):
    def setUp(self):
        import bromigos_account as A
        self.A = A
        A.KEYRING = A.MemoryKeyring()
        A._cache.clear()
        try:
            os.unlink(A.accounts_path())                     # each test starts unconfigured
        except OSError:
            pass

    def panel(self):
        with mock.patch.object(SP.K.KitPanel, "poller", lambda self, *a, **k: mock.Mock(error=None, runs=0, busy=False)):
            return PT.make(SP.SpotifyPanel)

    def test_unconfigured_says_how(self):
        p = self.panel()
        tips = PT.draw(p, 460, 200)
        self.assertTrue(any("client ID" in t and "developer.spotify.com" in t for t in tips))

    def test_signed_out_offers_sign_in(self):
        self.A.configure("spotify", client_id="cid")
        p = self.panel()
        tips = PT.draw(p, 460, 200)
        self.assertTrue(any(t.startswith("Sign in to Spotify") for t in tips))

    def test_signed_in_nothing_playing(self):
        self.A.configure("spotify", client_id="cid")
        self.A.set_token("spotify", "tok", who="me")
        p = self.panel()
        p.player = {"active": False}
        tips = PT.draw(p, 460, 200)
        self.assertTrue(any("nothing is playing" in t for t in tips))

    def test_the_apps_mpris_player_takes_the_clicks(self):
        p = self.panel()
        p.player = SP.parse_player(PLAYER)
        src = mock.Mock()
        p.mpris_src, p.mpris = src, {"instance": "spotify", "position": 70.0}
        p.p_now = mock.Mock()
        p.act("next")
        src.control.assert_called_once_with("spotify", "next")
        self.assertEqual(p.position(), 70.0)

    def test_position_runs_on_between_reads(self):
        p = self.panel()
        p.player = dict(SP.parse_player(PLAYER), at=time.time() - 5)
        self.assertAlmostEqual(p.position(), 66.0, delta=0.5)

    def test_every_size_class(self):
        PT.every_class(self, PT.make(SP.SpotifyPanel, demo=True))


if __name__ == "__main__":
    unittest.main()
