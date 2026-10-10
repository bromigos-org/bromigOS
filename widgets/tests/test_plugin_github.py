"""plugins/github.py: notifications, searches, repositories, events and the contribution
graph parsed from GitHub's answers; ETags; the signed-out state; every size class."""
import json
import os
import sys
import unittest
import urllib.error
from unittest import mock

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
import plugintest as PT  # noqa: E402
import github as G  # noqa: E402

FIX = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures")


def fixture(name):
    with open(os.path.join(FIX, name)) as f:
        return json.load(f)


class Parse(unittest.TestCase):
    def test_notifications(self):
        n = G.parse_notifications(fixture("github-notifications.json"))
        self.assertEqual(n[0]["url"], "https://github.com/octo/widgets/pull/827")
        self.assertEqual(n[0]["why"], "review asked")
        self.assertTrue(n[0]["unread"])
        self.assertEqual(n[1]["url"], "https://github.com/octo/relay/issues/91")
        self.assertEqual(n[2]["url"], "https://github.com/octo/relay/releases")
        self.assertAlmostEqual(n[0]["updated"], 1791607228.0)

    def test_search(self):
        s = G.parse_search(fixture("github-search.json"))
        self.assertEqual((s[0]["repo"], s[0]["number"], s[0]["pr"], s[0]["author"]), ("octo/widgets", 412, True, "mara"))
        self.assertFalse(s[1]["pr"])
        self.assertEqual(G.parse_search({}), [])

    def test_repos_skip_archived(self):
        r = G.parse_repos(fixture("github-repos.json"))
        self.assertEqual([x["name"] for x in r], ["widgets", "relay"])
        self.assertEqual((r[0]["stars"], r[1]["language"], r[1]["description"]), (1284, "", ""))

    def test_events_in_words_newest_first(self):
        e = G.parse_events(fixture("github-events.json"), me="octo")
        self.assertEqual([x["words"] for x in e], ["pushed 3 commits to main", "starred it", "merged PR #410",
                                                    "opened issue #91"])
        self.assertTrue(e[0]["me"])

    def test_contributions(self):
        c = G.parse_contrib(fixture("github-contrib.json"))
        self.assertEqual(c["total"], 9)
        self.assertEqual(c["weeks"][0], [("2026-10-04", 0), ("2026-10-05", 4)])
        self.assertEqual(G.parse_contrib({}), {"total": 0, "weeks": []})


class Etag(unittest.TestCase):
    def test_304_returns_the_last_copy(self):
        c = G.Client(lambda: "tok")
        calls = []

        class R:
            def __init__(self, body, etag):
                self.body, self.headers = body, {"ETag": etag, "X-RateLimit-Remaining": "4999"}

            def read(self):
                return self.body

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

        def fake(req, timeout=None):
            calls.append(dict(req.header_items()))
            if len(calls) == 1:
                return R(b'{"login": "octo"}', 'W/"abc"')
            raise urllib.error.HTTPError(req.full_url, 304, "Not Modified", {}, None)
        with mock.patch.object(G.urllib.request, "urlopen", fake):
            self.assertEqual(c.get("/user"), {"login": "octo"})
            self.assertEqual(c.get("/user"), {"login": "octo"})
        self.assertEqual(calls[1].get("If-none-match"), 'W/"abc"')
        self.assertEqual(calls[0].get("Authorization"), "Bearer tok")

    def test_no_token_is_not_signed_in(self):
        with self.assertRaises(PermissionError):
            G.Client(lambda: None).get("/user")


class Panel(unittest.TestCase):
    def test_signed_out_says_how_to_sign_in(self):
        import bromigos_account as A
        A.KEYRING = A.MemoryKeyring()
        A._gh.update(t=__import__("time").monotonic(), token=None)
        p = PT.make(G.GitHubPanel)
        tips = " ".join(PT.draw(p, 460, 320))
        self.assertIn("GitHub", tips)
        self.assertTrue("client ID" in tips or "Sign in" in tips, tips)

    def test_every_size_class_draws_with_hints(self):
        PT.every_class(self, PT.make(G.GitHubPanel, demo=True))


if __name__ == "__main__":
    unittest.main()
