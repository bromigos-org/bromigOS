"""The lab's name and its constellation's drawing come from homelab.toml (and the private
overlay through references), never from the code (bromigos_homelab.lab_name, config.table).

    PYTHONPATH=lib python -m unittest discover -s tests
"""
import json
import os
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(HERE)), "lib"))   # bromigos_private

import bromigos_homelab as H  # noqa: E402
from bromigos_homelab import config  # noqa: E402


class LabNameTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.user = os.path.join(self.tmp.name, "homelab.toml")
        self.private = os.path.join(self.tmp.name, "private.json")
        saved = (config.USER, os.environ.get("BROMIGOS_PRIVATE_CONFIG"))

        def restore():
            config.USER = saved[0]
            if saved[1] is None:
                os.environ.pop("BROMIGOS_PRIVATE_CONFIG", None)
            else:
                os.environ["BROMIGOS_PRIVATE_CONFIG"] = saved[1]
            config._cache.update(sig=None)
        self.addCleanup(restore)
        config.USER = self.user
        os.environ["BROMIGOS_PRIVATE_CONFIG"] = self.private
        import bromigos_private
        bromigos_private.PATH = self.private
        self.addCleanup(lambda: setattr(bromigos_private, "PATH", saved[1] or bromigos_private.PATH))

    def write(self, text, private=None):
        with open(self.user, "w") as f:
            f.write(text)
        with open(self.private, "w") as f:
            json.dump(private or {}, f)
        config._cache.update(sig=None)

    def test_the_default_is_lab(self):
        self.write("")
        self.assertEqual(H.lab_name(), "LAB")
        self.write('name = "  "\n')
        self.assertEqual(H.lab_name(), "LAB")

    def test_named_or_by_reference(self):
        self.write('name = "Orbit Lab"\n[tls]\nca_file = ""\n')
        self.assertEqual(H.lab_name(), "Orbit Lab")
        self.write('name = "@private:homelab.name"\n', {"homelab": {"name": "Hidden"}})
        self.assertEqual(H.lab_name(), "Hidden")
        self.write('name = "@private:homelab.name"\n')                  # not in the overlay
        self.assertEqual(H.lab_name(), "LAB")

    def test_constellation_from_the_overlay(self):
        # the overlay's form: positions as a list of {node, at} (sops leaves a table's keys clear)
        nodes = {"hub": "h1", "ai": ["n1", "n2"],
                 "positions": [{"node": "h1", "at": [0, 0, 0]}, {"node": "n1", "at": [1, 0, 0]}]}
        self.write('[constellation]\nhub = "@private:homelab.constellation.hub"\n'
                   'ai = "@private:homelab.constellation.ai"\n'
                   'positions = "@private:homelab.constellation.positions"\n',
                   {"homelab": {"constellation": nodes}})
        self.assertEqual(config.table("constellation"), nodes)


if __name__ == "__main__":
    unittest.main()
