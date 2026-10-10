"""plugins/youtube.py: the Atom feed, the /live page's answer (live, upcoming, offline,
unknown), a handle's channel ID, yt-dlp's entries, and every size class."""
import os
import sys
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
import plugintest as PT  # noqa: E402
import _kit as K  # noqa: E402
import youtube  # noqa: E402

FEED = b"""<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns:yt="http://www.youtube.com/xml/schemas/2015" xmlns:media="http://search.yahoo.com/mrss/"
      xmlns="http://www.w3.org/2005/Atom">
 <link rel="self" href="http://www.youtube.com/feeds/videos.xml?channel_id=UCabcdefghijklmnopqrstuv"/>
 <id>yt:channel:abcdefghijklmnopqrstuv</id>
 <yt:channelId>abcdefghijklmnopqrstuv</yt:channelId>
 <title>Keeper's Workshop</title>
 <link rel="alternate" href="https://www.youtube.com/channel/UCabcdefghijklmnopqrstuv"/>
 <entry>
  <id>yt:video:OLDOLDOLD01</id><yt:videoId>OLDOLDOLD01</yt:videoId>
  <title>An older one</title>
  <link rel="alternate" href="https://www.youtube.com/watch?v=OLDOLDOLD01"/>
  <published>2026-09-01T10:00:00+00:00</published>
  <media:group><media:thumbnail url="https://i1.ytimg.com/vi/OLDOLDOLD01/hqdefault.jpg" width="480" height="360"/>
   <media:community><media:starRating count="12" average="5.00" min="1" max="5"/>
   <media:statistics views="4567"/></media:community></media:group>
 </entry>
 <entry>
  <id>yt:video:NEWNEWNEW01</id><yt:videoId>NEWNEWNEW01</yt:videoId>
  <title>The beam at 3 a.m.</title>
  <link rel="alternate" href="https://www.youtube.com/shorts/NEWNEWNEW01"/>
  <published>2026-10-08T10:00:00+00:00</published>
  <media:group><media:community><media:statistics views="88"/></media:community></media:group>
 </entry>
</feed>"""


def quiet_pollers():
    return mock.patch.object(K.KitPanel, "poller", lambda self, fn, every, idle=None, name="poll", start=True:
                             self.pollers.append(K.Poller(self, fn, every, idle, name, start=False)) or self.pollers[-1])


class Feed(unittest.TestCase):
    def test_parse(self):
        d = youtube.parse_feed(FEED)
        self.assertEqual(d["channel"]["id"], "UCabcdefghijklmnopqrstuv")
        self.assertEqual(d["channel"]["title"], "Keeper's Workshop")
        new, old = d["videos"]
        self.assertEqual((new["id"], new["short"], new["views"]), ("NEWNEWNEW01", True, 88))
        self.assertEqual((old["views"], old["likes"], old["short"]), (4567, 12, False))
        self.assertTrue(new["thumb"].endswith("/NEWNEWNEW01/hqdefault.jpg"))     # made from the ID

    def test_shorts_setting(self):
        with quiet_pollers():
            p = PT.make(youtube.YoutubePanel, cfg={"shorts": False})
        self.assertEqual([v["id"] for v in p.videos(youtube.parse_feed(FEED))], ["OLDOLDOLD01"])


class Live(unittest.TestCase):
    def test_offline_when_the_page_is_the_channel(self):
        html = '<link rel="canonical" href="https://www.youtube.com/channel/UCabcdefghijklmnopqrstuv">'
        self.assertEqual(youtube.live_state(html)["state"], "offline")

    def test_live(self):
        html = ('<link rel="canonical" href="https://www.youtube.com/watch?v=LIVELIVE001">'
                '<meta name="title" content="Lamp room &amp; Q&amp;A"> ... "isLiveNow":true ...')
        st = youtube.live_state(html)
        self.assertEqual((st["state"], st["video"], st["title"]), ("live", "LIVELIVE001", "Lamp room & Q&A"))

    def test_upcoming_and_unknown(self):
        base = '<link rel="canonical" href="https://www.youtube.com/watch?v=SOON0000001">'
        self.assertEqual(youtube.live_state(base + '"isUpcoming":true')["state"], "upcoming")
        self.assertEqual(youtube.live_state(base)["state"], "unknown")             # a video, but not said live
        self.assertEqual(youtube.live_state("<html>consent</html>")["state"], "unknown")

    def test_handle_page(self):
        html = '<link rel="canonical" href="https://www.youtube.com/channel/UCabcdefghijklmnopqrstuv">'
        self.assertEqual(youtube.channel_id_of(html), "UCabcdefghijklmnopqrstuv")
        self.assertEqual(youtube.channel_id_of('x "externalId":"UCzzzzzzzzzzzzzzzzzzzzzz" y'), "UCzzzzzzzzzzzzzzzzzzzzzz")

    def test_ytdlp_shapes(self):
        v = youtube.from_ytdlp({"id": "abc", "title": "T", "upload_date": "20261001", "duration": 45,
                                "thumbnails": [{"url": "s"}, {"url": "big"}], "view_count": 9})
        self.assertEqual((v["short"], v["thumb"], v["views"]), (True, "big", 9))
        self.assertTrue(v["url"].endswith("watch?v=abc"))
        self.assertEqual(youtube.live_from(True)["state"], "live")
        self.assertEqual(youtube.live_from({"live": False})["state"], "offline")
        self.assertEqual(youtube.live_from(None)["state"], "unknown")


class States(unittest.TestCase):
    def test_no_channel(self):
        with quiet_pollers():
            p = PT.make(youtube.YoutubePanel)
        tips = " ".join(PT.draw(p, 460, 300))
        self.assertIn("needs a channel", tips)

    def test_channel_id_kept_as_is(self):
        with quiet_pollers():
            p = PT.make(youtube.YoutubePanel, cfg={"channel": "https://www.youtube.com/channel/UCabcdefghijklmnopqrstuv"})
        self.assertEqual(p.channel_id(), "UCabcdefghijklmnopqrstuv")

    def test_every_size_class(self):
        PT.every_class(self, PT.make(youtube.YoutubePanel, demo=True))


if __name__ == "__main__":
    unittest.main()
