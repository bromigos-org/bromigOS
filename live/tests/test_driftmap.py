"""The Drift map's catalog: the public one ships with the package and is the default, and a
user's [driftmap] catalog still wins (config.py lore_catalog, live/lore/catalog.json).

    cd live && python -m unittest tests.test_driftmap
"""
import copy
import importlib.util
import json
import os
import re
import sys
import tomllib
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
LIVE = os.path.dirname(HERE)
sys.path.insert(0, LIVE)

from live import config  # noqa: E402

SHIPPED = os.path.join(LIVE, "lore", "catalog.json")


class CatalogPathTest(unittest.TestCase):
    def test_the_default_is_the_packaged_public_catalog(self):
        with open(os.path.join(LIVE, "config.toml"), "rb") as f:
            packaged = config._merge(copy.deepcopy(config.DEFAULTS), tomllib.load(f))
        self.assertEqual(packaged["driftmap"]["catalog"], "")
        self.assertEqual(config.lore_catalog(packaged), config.LORE)
        self.assertEqual(config.lore_catalog({}), config.LORE)
        self.assertTrue(os.path.isfile(config.LORE), config.LORE)
        self.assertTrue(config.LORE.endswith(os.path.join("live", "lore", "catalog.json")))

    def test_a_users_catalog_wins(self):
        with open(os.path.join(LIVE, "config.toml"), "rb") as f:
            packaged = config._merge(copy.deepcopy(config.DEFAULTS), tomllib.load(f))
        mine = config._merge(packaged, {"driftmap": {"catalog": "~/lore/catalog.json"}})
        self.assertEqual(config.lore_catalog(mine), os.path.expanduser("~/lore/catalog.json"))
        self.assertEqual(config.lore_catalog(config._merge(packaged, {"general": {"fps": 24}})), config.LORE)


class ShippedCatalogTest(unittest.TestCase):
    def setUp(self):
        with open(SHIPPED) as f:
            self.cat = json.load(f)

    def test_it_has_what_the_map_reads(self):
        entries = self.cat["entries"]
        self.assertGreater(len(entries), 50)
        ids = {e["id"] for e in entries}
        self.assertIn("the_wick", ids)
        for e in entries:
            self.assertTrue(e["id"] and e["name"] and e["kind"], e)
            for r in e["relationships"]:
                self.assertIsInstance(r["target"], str)
                self.assertIn("relation", r)
        self.assertTrue(self.cat["timeline"])
        for t in self.cat["timeline"]:
            self.assertEqual(set(t), {"order", "period", "event"})

    def test_only_the_public_lore(self):
        # bromigos.org's export checks it (tools/lore/sync-catalog.py runs its check again);
        # this catches a hand edit naming the internal tools, the lab or the other products
        with open(SHIPPED) as f:
            text = f.read()
        self.assertIsNone(re.search(r"brodec", text, re.I))
        # the internal tools' names (salted hashes) and the lab's name as a lab, from the
        # private overlay when there is one (tools/privacy/private_words.py): never spelled here
        sys.path.insert(0, os.path.join(os.path.dirname(LIVE), "tools", "privacy"))
        import private_words
        self.assertEqual(private_words.hashed_hits(text), [])
        lab = private_words.lab_name_pattern()
        if lab:
            self.assertIsNone(re.search(lab + r"[ _]lab", text, re.I), "the lab's name, as a lab")

    @unittest.skipUnless(importlib.util.find_spec("OpenGL"), "the Drift map imports PyOpenGL")
    def test_the_map_loads_it(self):
        from live import drift_map
        cat, nodes, edges = drift_map.load_catalog(SHIPPED)
        wick, near, rest = drift_map.split_wick(nodes, edges)
        self.assertEqual(wick["id"], "the_wick")
        self.assertTrue(near and rest)
        self.assertTrue(all(a in nodes and b in nodes for a, b in rest))


if __name__ == "__main__":
    unittest.main()
