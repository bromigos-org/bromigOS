"""The search across all settings (bromigos_settings/search.py): words by prefix, every
word must match, synonyms widen a word, a title beats a keyword beats the page's own
words, results say where they are. No toolkit needed.

    python -m unittest discover -s desktop/tests
"""
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "settings"))

from bromigos_settings.registry import Entry, Page, Section, discover  # noqa: E402
from bromigos_settings.search import Index, expand, norm  # noqa: E402

PAGES = [
    Page(id="network", title="Network", group="system", build=print, summary="Wi-Fi, wired, VPN",
         entries=[Entry("wifi", "Wi-Fi", ["wireless", "ssid"], "Wi-Fi"), Entry("vpn", "VPN", ["wireguard"], "VPN"),
                  Entry("wired", "Wired", ["ethernet"], "Wired")]),
    Page(id="notifications", title="Notifications", group="desktop", build=print, summary="do not disturb",
         entries=[Entry("dnd", "Do not disturb", ["quiet", "pause notifications"]),
                  Entry("timeout", "How long they stay", ["timeout", "duration"])]),
    Page(id="datetime", title="Date & time", group="system", build=print,
         entries=[Entry("clock24", "24-hour clock", ["time format", "am pm"]), Entry("tz", "Time zone", ["timezone"])]),
    Page(id="sound", title="Sound", group="system", build=print,
         entries=[Entry("output", "Output device", ["speakers", "headphones"], "Output"),
                  Entry("input", "Input device", ["microphone"], "Input")]),
]


class SearchTest(unittest.TestCase):
    def setUp(self):
        self.idx = Index(PAGES)

    def first(self, q):
        r = self.idx.search(q)
        return (r[0].page, r[0].key) if r else None

    def test_normalizes(self):
        self.assertEqual(norm("Wi-Fi"), "wifi")
        self.assertEqual(norm("  Date & Time "), "date time")
        self.assertEqual(norm("Café"), "cafe")
        self.assertIn("dnd", expand("do not disturb") | expand("dnd"))

    def test_by_name_and_prefix(self):
        self.assertEqual(self.first("wifi"), ("network", "wifi"))
        self.assertEqual(self.first("Wi-Fi"), ("network", "wifi"))
        self.assertEqual(self.first("vp"), ("network", "vpn"))
        self.assertEqual(self.first("time zone"), ("datetime", "tz"))

    def test_synonyms(self):
        self.assertEqual(self.first("wireless"), ("network", "wifi"))
        self.assertEqual(self.first("dnd"), ("notifications", "dnd"))
        self.assertEqual(self.first("mic"), ("sound", "input"))
        self.assertEqual(self.first("ethernet"), ("network", "wired"))
        self.assertEqual(self.first("24 hour"), ("datetime", "clock24"))
        self.assertEqual(self.first("am pm"), ("datetime", "clock24"))

    def test_every_word_must_match(self):
        self.assertEqual(self.idx.search("wifi microphone"), [])
        self.assertEqual(self.idx.search("zzzz"), [])
        self.assertEqual(self.idx.search(""), [])

    def test_the_page_itself_is_found(self):
        r = self.idx.search("network")
        self.assertEqual((r[0].kind, r[0].page), ("page", "network"))
        self.assertEqual(r[0].where, "System › Network")

    def test_where(self):
        r = self.idx.search("output device")[0]
        self.assertEqual(r.where, "System › Sound › Output")

    def test_sections_are_searched(self):
        p = Page(id="lab", title="Lab", group="lab", build=print)
        p.sections = [Section(page="lab", id="models", title="Lab models", build=print,
                              entries=[Entry("plan", "Model planner", ["vram", "gpu"])])]
        idx = Index([p])
        r = idx.search("vram")[0]
        self.assertEqual((r.page, r.key, r.where), ("lab", "plan", "Lab › Lab › Lab models"))
        self.assertEqual(idx.search("lab models")[0].key, "section:models")


class PackagedIndexTest(unittest.TestCase):
    """The pages bromigOS ships: each common search lands on the right setting."""

    @classmethod
    def setUpClass(cls):
        pages, _ = discover([os.path.join(os.path.dirname(HERE), "settings", "pages")])
        cls.ids = {p.id for p in pages}
        cls.idx = Index(pages)

    def lands(self, q, page, key=None):
        if page not in self.ids:
            self.skipTest(f"no {page} page here")
        r = self.idx.search(q)
        self.assertTrue(r, q)
        self.assertEqual((r[0].page, r[0].key if key else page if r[0].kind == "page" else r[0].page),
                         (page, key if key else page), f"{q!r} -> {[(x.page, x.key) for x in r[:4]]}")

    def test_sound(self):
        self.lands("volume", "sound", "output-volume")
        self.lands("microphone", "sound", "input")
        self.lands("speakers", "sound", "output")

    def test_dark_and_light(self):
        # the theme decides dark or light; "look" in "Look for devices" isn't a theme word,
        # and Displays' "a screen gone dark" is prose, not a keyword
        self.lands("dark", "theme", "themes")
        self.lands("dark mode", "theme", "themes")
        self.lands("light mode", "theme", "themes")
        self.lands("colour scheme", "theme", "themes")
        self.lands("look for devices", "bluetooth", "scan")
        self.lands("bluetooth", "bluetooth")


if __name__ == "__main__":
    unittest.main()
