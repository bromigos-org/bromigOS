"""Decks, the lab's name and its nodes come from what's installed and configured, never
from names written into the live layer (decks.py, constellation.py, config.py).

    cd live && python -m unittest discover -s tests
"""
import os
import re
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
LIVE = os.path.dirname(HERE)
REPO = os.path.dirname(LIVE)
sys.path.insert(0, LIVE)

from live import constellation, decks  # noqa: E402


class DecksTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.plugins = os.path.join(self.tmp.name, "plugins")
        self.homelab = os.path.join(self.tmp.name, "homelab")
        os.makedirs(self.plugins)
        os.makedirs(os.path.join(self.homelab, "live"))
        saved = decks.PLUGINS, decks.HOMELAB
        self.addCleanup(lambda: (setattr(decks, "PLUGINS", saved[0]), setattr(decks, "HOMELAB", saved[1])))
        decks.PLUGINS, decks.HOMELAB = [self.plugins], None

    def deck(self, folder, kind, body):
        with open(os.path.join(folder, f"{kind}_deck.py"), "w") as f:
            f.write(body)

    def test_a_plugin_deck_brings_its_own_words(self):
        self.deck(self.plugins, "trades", 'class D:\n    deck_label = "Trades"\n    deck_hint = "the floor"\n'
                                          '    def m(self):\n        deck_label = "not this"\nDECK = D\n')
        self.deck(self.plugins, "replay", 'class D:\n    title = "REPLAY // ONE TRADE"\n    hint = "for VECTOR"\nDECK = D\n')
        self.deck(self.plugins, "bare", "DECK = object\n")
        cat = {d["kind"]: d for d in decks.catalog()}
        self.assertEqual((cat["trades"]["label"], cat["trades"]["hint"], cat["trades"]["source"]),
                         ("Trades", "the floor", "plugin"))
        self.assertEqual((cat["replay"]["label"], cat["replay"]["hint"]), ("Replay", ""))   # a title, not `hint`
        self.assertEqual(cat["bare"]["label"], "Bare deck")
        self.assertEqual(decks.label("trades"), "Trades")
        self.assertEqual(decks.label("gone"), "Gone deck")
        # bromigOS's own first, in their order; without the homelab, none of its decks
        self.assertEqual([d["kind"] for d in decks.catalog()][:4], ["holodeck", "driftmap", "timeline", "swarm"])
        self.assertNotIn("mind", cat)

    def test_homelab_decks_when_it_is_installed(self):
        decks.HOMELAB = self.homelab
        self.deck(os.path.join(self.homelab, "live"), "mind", "DECK = object\n")
        self.deck(os.path.join(self.homelab, "live"), "rack", 'class D:\n    title = "RACK // THE LAB"\nDECK = D\n')
        cat = {d["kind"]: d for d in decks.catalog()}
        self.assertEqual((cat["mind"]["label"], cat["mind"]["source"]), ("Mind", "homelab"))
        self.assertEqual(cat["rack"]["label"], "Rack")

    def test_the_tab_cycle_is_configured_and_skips_what_isnt_there(self):
        self.deck(self.plugins, "trades", "DECK = object\n")
        default = decks.cycle({})
        self.assertEqual(default, ["holodeck", "timeline", "swarm"])          # no homelab here
        self.assertNotIn("trades", default)                                  # a plugin joins by config
        cfg = {"decks": {"cycle": ["holodeck", "trades", "timeline", "nope", "swarm"]}}
        self.assertEqual(decks.cycle(cfg), ["holodeck", "trades", "timeline", "swarm"])
        self.assertEqual(decks.next_deck("holodeck", cfg), "trades")
        self.assertEqual(decks.next_deck("swarm", cfg), "holodeck")          # round again
        self.assertEqual(decks.next_deck("driftmap", cfg), "holodeck")       # not in it: the first
        self.assertIsNone(decks.next_deck("holodeck", {"decks": {"cycle": ["holodeck"]}}))


class ConstellationTest(unittest.TestCase):
    def test_nodes_come_from_the_snapshot(self):
        pos, links, ai = constellation.layout(["n1", "n2", "n3"], {})
        self.assertEqual(list(pos), ["n1", "n2", "n3"])
        self.assertEqual(pos["n1"], (0.0, 0.08, 0.0))
        self.assertEqual(links, [("n1", "n2"), ("n1", "n3"), ("n1", "uplink")])
        self.assertIsNone(ai)
        for p in pos.values():
            self.assertLessEqual(sum(c * c for c in p), 1.0001)
        self.assertEqual(constellation.layout([], {}), ({}, [], None))

    def test_a_pinned_drawing(self):
        conf = {"hub": "b", "ai": ["a", "c"], "positions": {"a": [0.1, 0.2, 0.3], "b": [0, 0, 0], "c": [1, 0, 0],
                                                             "bad": ["x"]}}
        pos, links, ai = constellation.layout(["a", "b", "c", "d"], conf)
        self.assertEqual(list(pos), ["a", "b", "c"])                        # its order; unpinned nodes left out
        self.assertEqual(ai, ("a", "c"))
        self.assertEqual(links, [("b", "a"), ("b", "c"), ("a", "c"), ("b", "uplink")])
        # the overlay's form: a list of {node, at} tables (sops encrypts values, not keys),
        # the same drawing in the list's order; a malformed entry is passed over
        listed = dict(conf, positions=[{"node": "a", "at": [0.1, 0.2, 0.3]}, {"node": "b", "at": [0, 0, 0]},
                                       {"node": "c", "at": [1, 0, 0]}, {"node": "bad", "at": ["x"]},
                                       {"at": [1, 1, 1]}, ["a", 1, 2, 3]])
        self.assertEqual(constellation.layout(["a", "b", "c", "d"], listed), (pos, links, ai))
        # an ai pair naming a node that isn't drawn: no models' link
        self.assertIsNone(constellation.layout(["a"], {"ai": ["a", "zz"]})[2])


class NoPrivateNamesTest(unittest.TestCase):
    """What ships names no one's own deck, trading system, lab or machines."""

    # k8s_<app>: the names of one lab's NAS shares; a panel finds its share in the snapshot.
    # VECTOR's public tool names (k8s_restart, k8s_scale, k8s_delete_pod, k8s_run_job) aren't shares.
    PRIVATE = re.compile(r"blackflame|k8s_(?!(?:restart|scale|delete_pod|run_job)\b)[a-z]", re.I)
    TREES = ("live/live", "live/bin", "live/config.toml", "live/shaders", "live/tools", "desktop/bin", "desktop/lib",
             "desktop/startpage", "desktop/hypr", "widgets", "homelab/lib", "homelab/live", "homelab/share",
             "homelab/widgets", "themes/mire/live", "themes/tidewell/live")

    @staticmethod
    def lore_ids():
        """The public lore's ids (live/lore/catalog.json): a constructed world's id may look like a
        private name, and the lore is public."""
        import json
        with open(os.path.join(LIVE, "lore", "catalog.json")) as f:
            cat = json.load(f)
        ids = set()

        def walk(o):
            if isinstance(o, dict):
                for k, v in o.items():
                    if k == "id" and isinstance(v, str):
                        ids.add(v)
                    walk(v)
            elif isinstance(o, list):
                for v in o:
                    walk(v)
        walk(cat)
        return sorted(ids, key=len, reverse=True)

    def test_none_in_what_ships(self):
        # the private names come from the private overlay and salted hashes, never this file
        sys.path.insert(0, os.path.join(REPO, "tools", "privacy"))
        import private_words
        words = private_words.Finder()
        allowed = self.lore_ids()
        hits = []
        for t in self.TREES:
            path = os.path.join(REPO, t)
            files = [path] if os.path.isfile(path) else [
                os.path.join(dp, f) for dp, _, fs in os.walk(path) for f in fs
                if not dp.endswith("__pycache__") and not f.endswith((".png", ".jpg", ".npz", ".wav", ".pyc", ".mp4", ".webm"))]
            for f in files:
                try:
                    with open(f, encoding="utf-8") as fh:
                        text = fh.read()
                except (OSError, UnicodeDecodeError):
                    continue
                for n, line in enumerate(text.splitlines(), 1):
                    clean = line
                    for a in allowed:
                        clean = clean.replace(a, "")
                    why = words.search(clean) or ("a private name" if self.PRIVATE.search(clean) else None)
                    if why:
                        hits.append(f"{os.path.relpath(f, REPO)}:{n}: {why}")
        self.assertEqual(hits, [], "\n".join(hits))


if __name__ == "__main__":
    unittest.main()
