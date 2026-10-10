"""plugins/discord.py: invite codes, the invite and widget answers, the empty state, a
disabled widget, and every size class."""
import os
import sys
import unittest
import urllib.error
from unittest import mock

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
import plugintest as PT  # noqa: E402
import _kit as K  # noqa: E402
import discord  # noqa: E402

INVITE = {"type": 0, "code": "abc123", "guild": {"id": "42", "name": "Harbor Point", "icon": "f00", "description": "x"},
          "approximate_member_count": 122, "approximate_presence_count": 32}
WIDGET = {"id": "42", "name": "Harbor Point", "instant_invite": "https://discord.com/invite/xyz", "presence_count": 3,
          "channels": [{"id": "v2", "name": "Workshop", "position": 1}, {"id": "v1", "name": "Lounge", "position": 0}],
          "members": [{"id": "0", "username": "zed", "status": "idle", "avatar_url": "https://cdn/a.png"},
                      {"id": "1", "username": "amy", "status": "online", "avatar_url": "https://cdn/b.png",
                       "channel_id": "v1"},
                      {"id": "2", "username": "bo", "status": "dnd", "avatar_url": None}]}


def quiet_pollers():
    return mock.patch.object(K.KitPanel, "poller", lambda self, fn, every, idle=None, name="poll", start=True:
                             self.pollers.append(K.Poller(self, fn, every, idle, name, start=False)) or self.pollers[-1])


class Parse(unittest.TestCase):
    def test_invite_codes(self):
        for s in ("abc123", "discord.gg/abc123", "https://discord.gg/abc123/", "https://discord.com/invite/abc123"):
            self.assertEqual(discord.invite_code(s), "abc123")
        self.assertIsNone(discord.invite_code(""))
        self.assertIsNone(discord.invite_code("not a code!"))

    def test_invite(self):
        d = discord.parse_invite(INVITE)
        self.assertEqual((d["name"], d["online"], d["members"], d["id"]), ("Harbor Point", 32, 122, "42"))
        self.assertTrue(discord.icon_url("42", "f00").startswith("https://cdn.discordapp.com/icons/42/f00.png"))

    def test_widget(self):
        w = discord.parse_widget(WIDGET)
        self.assertEqual([m["name"] for m in w["list"]], ["amy", "zed", "bo"])   # in voice first, then idle, dnd
        self.assertEqual([c["name"] for c in w["voice"]], ["Lounge", "Workshop"])
        self.assertEqual(w["voice"][0]["who"], ["amy"])
        self.assertEqual(w["online"], 3)


class Fetch(unittest.TestCase):
    def test_disabled_widget_falls_back_to_the_invite(self):
        def fake(url, **kw):
            if "/invites/" in url:
                return INVITE
            e = urllib.error.HTTPError(url, 403, "Forbidden", {}, None)
            e.body = {"message": "Widget Disabled", "code": 50004}
            raise e
        with quiet_pollers():
            p = PT.make(discord.DiscordPanel, cfg={"invite": "abc123", "server": "42"})
        with mock.patch.object(discord.A, "http_json", fake), mock.patch.object(K, "fetch_bytes", lambda *a, **k: b""):
            d = p.fetch()
        self.assertEqual(d["online"], 32)
        self.assertIn("Enable Server Widget", d["widget_error"])
        self.assertEqual(list(p.history)[-1][1], 32)


class States(unittest.TestCase):
    def test_not_configured(self):
        with quiet_pollers():
            p = PT.make(discord.DiscordPanel)
        tips = " ".join(PT.draw(p, 420, 240))
        self.assertIn("invite code", tips)

    def test_every_size_class(self):
        PT.every_class(self, PT.make(discord.DiscordPanel, demo=True))


if __name__ == "__main__":
    unittest.main()
