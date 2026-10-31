"""STATIC's art folder (lib/bromigos_static_art.py): a manifest's frames are found by name,
face and height, the first folder wins, and anything missing or broken falls back to the
placeholder. The terminal shrinks a rendered frame to half-block pixels, and `bromigos mascot`
turns him on, quiet or off.

    python3 -m unittest tests/mascot/test_static_art.py
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
sys.path[:0] = [os.path.join(REPO, "lib"), HERE]
import artfixture  # noqa: E402
import bromigos_static_art as A  # noqa: E402
import bromigos_static_term as ST  # noqa: E402


class Folder(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="static-art-")
        self.env = {"BROMIGOS_STATIC_ART": artfixture.folder(os.path.join(self.tmp, "art")),
                    "HOME": self.tmp}

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def test_found_by_name_face_and_height(self):
        a = A.find("host", height=100, env=self.env)
        self.assertEqual((a.name, a.height, len(a.frames)), ("host", 256, 2))
        self.assertEqual(A.find("host", height=40, env=self.env).height, 64)
        self.assertEqual(A.find("host", height=900, env=self.env).height, 256)       # the tallest there is
        self.assertEqual(A.find("remote", face="snow", height=64, env=self.env).name, "remote:snow")
        self.assertEqual(A.find("watching", face="watching", head=True, env=self.env).name, "head:watching")
        self.assertIsNone(A.find("popcorn", env=self.env))                          # not rendered: the placeholder
        self.assertIsNone(A.find("remote", env=self.env))

    def test_missing_or_broken_falls_back(self):
        os.remove(os.path.join(self.env["BROMIGOS_STATIC_ART"], "host-256-01.png"))
        self.assertEqual(A.find("host", height=200, env=self.env), None)
        with open(os.path.join(self.env["BROMIGOS_STATIC_ART"], "manifest.json"), "w") as f:
            f.write("{not json")
        self.assertIsNone(A.find("snow", env=self.env))
        self.assertEqual(A.names(env=self.env), {})

    def test_the_first_folder_wins(self):
        user = os.path.join(self.tmp, ".local", "share", "bromigos", "static")
        artfixture.folder(user, names=("host",), heights=(128,), colour=(0, 255, 0, 255))
        a = A.find("host", height=100, env=self.env)
        self.assertTrue(a.folder.endswith("art"))                                    # $BROMIGOS_STATIC_ART first
        env = dict(self.env, BROMIGOS_STATIC_ART="")
        self.assertEqual(A.find("host", height=100, env=env).height, 128)

    def test_a_frame_as_half_blocks(self):
        a = A.find("snow", height=40, env=self.env)
        px = ST.png_pixels(ST.art_pngs(a)[0], 20, 24)
        self.assertEqual(len(px), 24)
        self.assertIn("#ff00ff", {c for row in px for c in row})


class Switch(unittest.TestCase):
    def test_on_quiet_off(self):
        tmp = tempfile.mkdtemp(prefix="static-mode-")
        env = dict(os.environ, HOME=tmp, XDG_CONFIG_HOME=os.path.join(tmp, ".config"), BROMIGOS_MASCOT="")
        cli = [sys.executable, os.path.join(REPO, "bin", "bromigos-mascot")]
        doc = json.loads(subprocess.run(cli + ["--json"], env=env, capture_output=True, text=True).stdout)
        self.assertEqual(doc["mode"], "on")
        doc = json.loads(subprocess.run(cli + ["off", "--json"], env=env, capture_output=True, text=True).stdout)
        self.assertEqual((doc["mode"], doc["before"]), ("off", "on"))
        doc = json.loads(subprocess.run(cli + ["--json"], env=env, capture_output=True, text=True).stdout)
        self.assertEqual(doc["mode"], "off")
        self.assertEqual(subprocess.run(cli + ["loud"], env=env, capture_output=True).returncode, 2)
        shutil.rmtree(tmp)


if __name__ == "__main__":
    unittest.main()
