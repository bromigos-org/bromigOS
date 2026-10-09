"""`bromigos avatar`: the picture cropped square to ~/.face with the login screen's link, the
old one kept; and whether profile.toml sits in a git repository (dotfiles that may be public)
or the private overlay holds the private fields."""
import json
import os
import subprocess
import unittest

from cmdtest import CmdTest

try:
    from PIL import Image
except ImportError:
    Image = None


@unittest.skipIf(Image is None, "python-pillow isn't installed")
class AvatarTest(CmdTest):
    def picture(self, w, h, colour=(200, 40, 40)):
        p = os.path.join(self.tmp, f"pic-{w}x{h}.jpg")
        Image.new("RGB", (w, h), colour).save(p)
        return p

    def test_set_crops_square_and_links_the_icon(self):
        d = self.cmd("avatar", "set", self.picture(800, 400))
        self.assertEqual(d["size"], [256, 256])
        self.assertTrue(d["icon_links_face"])
        self.assertEqual(os.readlink(self.path(".face.icon")), ".face")
        d = self.cmd("avatar", "set", self.picture(300, 900, (10, 200, 10)))
        self.assertTrue(d["previous"])                      # the first kept
        with Image.open(self.path(".face.previous")) as im:
            self.assertEqual(im.getpixel((128, 128))[:3], (200, 40, 40))
        d = self.cmd("avatar", "clear")
        self.assertIsNone(d["face"])
        self.assertFalse(os.path.lexists(self.path(".face.icon")))

    def test_refusals(self):
        self.cmd("avatar", "set", os.path.join(self.tmp, "missing.png"), ok=False)
        bad = os.path.join(self.tmp, "notes.txt")
        with open(bad, "w") as f:
            f.write("not a picture")
        self.assertIn("isn't a picture", self.cmd("avatar", "set", bad, ok=False)["error"])

    def test_profile_in_a_dotfiles_repo_is_flagged(self):
        dot = self.path(".dotfiles")
        os.makedirs(os.path.join(dot, "bromigos"))
        subprocess.run(["git", "init", "-q", dot], check=True)
        with open(os.path.join(dot, "bromigos", "profile.toml"), "w") as f:
            f.write('[you]\nname = "Sam"\n')
        os.makedirs(self.path(".config"))
        os.symlink(os.path.join(dot, "bromigos"), self.path(".config", "bromigos"))
        s = self.cmd("avatar")["sharing"]
        self.assertTrue(s["linked"] and s["in_dotfiles"])
        self.assertEqual(s["repo"], dot)
        self.assertIn("shared", s["warning"])
        with open(os.path.join(dot, ".gitignore"), "w") as f:
            f.write("bromigos/profile.toml\n")
        s = self.cmd("avatar")["sharing"]
        self.assertTrue(s["ignored"])
        self.assertIsNone(s["warning"])

    def test_the_overlay(self):
        os.makedirs(self.path(".config", "bromigos", "private"))
        with open(self.path(".config", "bromigos", "private.sops.yaml"), "w") as f:
            f.write("sops: {}\n")
        with open(self.path(".config", "bromigos", "private", "config.json"), "w") as f:
            json.dump({"operator": {"name": "Sam"}}, f)
        o = self.cmd("avatar")["sharing"]["overlay"]
        self.assertEqual((o["encrypted"], o["decrypted"], o["operator"]), (True, True, True))


if __name__ == "__main__":
    unittest.main()
