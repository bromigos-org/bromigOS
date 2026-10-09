"""The extensions' one list (lib/bromigos_extlist.py): the launcher's window (bromigos
extensions) and Settings › Extensions show the same rows with the same actions."""
import json
import os
import subprocess
import sys
import unittest

from cmdtest import DESKTOP, CmdTest

sys.path.insert(0, os.path.join(DESKTOP, "lib"))
import bromigos_extlist as X  # noqa: E402

LIST = {"list": {"extensions": [{"name": "rime-plus", "kinds": ["theme"], "enabled": True, "status": "ok",
                                 "version": "1.2", "source": "https://example.org/rime-plus"},
                                {"name": "pager", "kinds": ["live-deck"], "enabled": False, "status": "disabled"}]}}
SEARCH = {"results": [{"name": "rime-plus", "display_name": "Rime+", "description": "more ice", "kinds": ["theme"],
                       "installed": True},
                      {"name": "tide-deck", "display_name": "Tide deck", "description": "the tides", "kinds": ["live-deck"]},
                      {"name": "mire", "kinds": ["theme"], "bundled": True}],
          "errors": ["https://bad.example: timed out"]}


class MergeTest(unittest.TestCase):
    def test_installed_first_with_the_catalogs_words(self):
        items, errors = X.merge(LIST, SEARCH)
        self.assertEqual([i["name"] for i in items], ["rime-plus", "pager", "tide-deck", "mire"])
        self.assertEqual(items[0]["title"], "Rime+")
        self.assertEqual(items[0]["what"], "more ice")
        self.assertTrue(items[0]["theme"] and items[0]["installed"])
        self.assertIn(("Turn on", ["enable", "pager"]), items[1]["actions"])
        self.assertEqual(items[2]["install"], ["bromigos", "ext", "install", "tide-deck"])
        self.assertEqual(items[3]["actions"], [])                 # ships with bromigOS
        self.assertEqual(errors, ["https://bad.example: timed out"])
        self.assertEqual(X.kinds_text(["live-deck", "hook"]), "a deck, a hook")

    def test_nothing_answers(self):
        self.assertEqual(X.merge(None, None), ([], []))


class WindowTest(CmdTest):
    def test_the_window_lists_the_same_rows(self):
        r = subprocess.run([os.path.join(DESKTOP, "bin", "bromigos-extensions"), "--list", "--json"], env=self.env,
                           capture_output=True, text=True, timeout=60)
        self.assertEqual(r.returncode, 0, r.stderr)
        doc = json.loads(r.stdout)
        lst = json.loads(subprocess.run(["bromigos", "ext", "list", "--json"], env=self.env, capture_output=True,
                                        text=True, timeout=60).stdout)
        found = json.loads(subprocess.run(["bromigos", "ext", "search", "--json"], env=self.env, capture_output=True,
                                          text=True, timeout=60).stdout)
        items, _ = X.merge(lst, found)
        self.assertEqual([i["name"] for i in doc["extensions"]], [i["name"] for i in items])
        self.assertTrue(doc["extensions"])


if __name__ == "__main__":
    unittest.main()
