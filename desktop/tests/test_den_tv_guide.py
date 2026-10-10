"""Standalone Den TV, the channel guide (desktop/settings/bromigos_tvguide.py), drawn in a
headless weston of its own (no window anywhere), against a stand-in Jellyfin
(live/tests/fake_media.py: generated posters, never real media) and a throwaway HOME:

- the guide: a grid per screen, every channel in order with channel 1 first, what's on
  now and next with posters, the channel each screen is on marked; no control without a
  hover hint (`--audit`);
- Add channel, and the show picker (the server's shows with their posters, picked ones
  marked);
- the PNGs land in $BROMIGOS_TEST_SHOTS when it's set (to look at them).

    python3 -m unittest desktop/tests/test_den_tv_guide.py
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
DESKTOP = os.path.dirname(HERE)
REPO = os.path.dirname(DESKTOP)
sys.path.insert(0, os.path.join(REPO, "live", "tests"))

CONFIG = """# the den TV, as the test has it
[[tv.channel]]
name = "Test Card"
source = "jellyfin"
library = "Shows"
order = "in order"

[[tv.channel]]
name = "Block"                 # two shows taking turns
source = "jellyfin"
shows = ["Test Card", "Night Shift"]
order = "in order"
bumpers = true

[[tv.channel]]
name = "Films"
source = "jellyfin"
library = "Movies"
screens = ["big", "emblem"]    # kept off the scope
"""


@unittest.skipUnless(shutil.which("weston"), "needs weston")
class GuideRender(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import fake_media as FM
        cls.tmp = tempfile.mkdtemp(prefix="bdtv-", dir="/tmp")             # short: a socket path
        os.chmod(cls.tmp, 0o700)
        cls.home = os.path.join(cls.tmp, "home")
        for d in (".config/bromigos-live", ".config/bromigos", ".cache", ".local/state/bromigos-live"):
            os.makedirs(os.path.join(cls.home, d), exist_ok=True)
        poster = os.path.join(cls.tmp, "poster.png")
        from PIL import Image, ImageDraw
        im = Image.new("RGB", (200, 300), (30, 60, 140))
        dr = ImageDraw.Draw(im)
        for y in range(0, 300, 24):
            dr.rectangle((0, y, 200, y + 10), fill=(220, 180, 40))
        im.save(poster)
        cls.jf = FM.FakeJellyfin(poster=poster)
        FM.homelab_toml(os.path.join(cls.home, ".config", "bromigos", "homelab.toml"), cls.jf)
        with open(os.path.join(cls.home, ".config", "bromigos-live", "config.toml"), "w") as f:
            f.write(CONFIG)
        with open(os.path.join(cls.home, ".local", "state", "bromigos-live", "tv.json"), "w") as f:
            json.dump({"screens": {"big": {"channel": "block", "sound": True}, "wave": {"channel": "films"}}}, f)
        cls.weston = subprocess.Popen(
            ["weston", "--backend=headless", "--renderer=pixman", "--width=1400", "--height=1000", "--socket=w",
             "--idle-time=0", "--no-config"],
            env={"HOME": cls.tmp, "XDG_RUNTIME_DIR": cls.tmp, "PATH": os.environ.get("PATH", "/usr/bin")},
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        for _ in range(100):
            if os.path.exists(os.path.join(cls.tmp, "w")):
                break
            time.sleep(0.05)
        cls.env = {"HOME": cls.home, "XDG_RUNTIME_DIR": cls.tmp, "WAYLAND_DISPLAY": "w", "GDK_BACKEND": "wayland",
                   "GSK_RENDERER": "cairo", "DBUS_SESSION_BUS_ADDRESS": "disabled:",
                   "XDG_CONFIG_HOME": os.path.join(cls.home, ".config"),
                   "XDG_CACHE_HOME": os.path.join(cls.home, ".cache"),
                   "XDG_STATE_HOME": os.path.join(cls.home, ".local", "state"),
                   "BROMIGOS_HOMELAB_CONFIG": os.path.join(cls.home, ".config", "bromigos", "homelab.toml"),
                   "BROMIGOS_SHARE_DIR": REPO,
                   "PATH": os.path.join(cls.tmp, "nobin") + ":" + os.environ.get("PATH", "/usr/bin"),
                   "PYTHONPATH": os.pathsep.join([os.path.join(REPO, "lib"), os.path.join(REPO, "homelab", "lib")])}
        nobin = os.path.join(cls.tmp, "nobin")
        os.makedirs(nobin)
        with open(os.path.join(nobin, "bromigos-live"), "w") as f:      # the live layer: not running
            f.write("#!/bin/sh\necho 'not running (bromigos-live start)'\nexit 1\n")
        os.chmod(os.path.join(nobin, "bromigos-live"), 0o755)
        cls.shots = os.environ.get("BROMIGOS_TEST_SHOTS")

    @classmethod
    def tearDownClass(cls):
        cls.weston.terminate()
        cls.weston.wait(5)
        cls.jf.close()
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def render(self, name, extra=(), env=None, size="1180x980"):
        out = os.path.join(self.tmp, name + ".png")
        r = subprocess.run([sys.executable, os.path.join(DESKTOP, "settings", "bromigos-tv-guide"), "--render", out,
                            "--page", "den-tv", "--size", size, *extra], env=dict(self.env, **(env or {})),
                           capture_output=True, text=True, timeout=120)
        self.assertEqual(r.returncode, 0, r.stderr[-3000:])
        if self.shots:
            os.makedirs(self.shots, exist_ok=True)
            shutil.copy(out, os.path.join(self.shots, f"den-tv-{name}.png"))
        from PIL import Image
        return Image.open(out).convert("RGB"), r

    def test_play_picker_and_its_hints(self):
        image, result = self.render("play", extra=("--audit",), env={"BROMIGOS_DEN_TV_OPEN":"play"})
        self.assertEqual(image.size, (1180,980))
        self.assertNotIn("without a hint", result.stderr)

    def test_the_guide(self):
        im, _r = self.render("guide")
        self.assertEqual(im.size, (1180, 980))
        px = im.load()
        posters = sum(1 for x in range(0, im.width, 4) for y in range(0, im.height, 4)
                      if px[x, y][0] > 180 and px[x, y][1] > 140 and px[x, y][2] < 90)
        self.assertGreater(posters, 200, "no poster drawn")             # the generated posters' yellow stripes
        self.assertTrue(os.listdir(os.path.join(self.home, ".cache", "bromigos", "tv", "posters")))

    def test_every_control_has_a_hint(self):
        r = subprocess.run([sys.executable, os.path.join(DESKTOP, "settings", "bromigos-tv-guide"), "--audit",
                            "--page", "den-tv", "--size", "1180x980"], env=self.env, capture_output=True, text=True,
                           timeout=120)
        doc = json.loads(r.stdout.strip().splitlines()[-1])
        self.assertEqual(doc["unhinted"], [], doc)
        self.assertEqual(doc["unbuilt_keys"], [], doc)

    def test_add_channel_and_the_show_picker(self):
        im, _r = self.render("add", env={"BROMIGOS_DEN_TV_OPEN": "add"})
        self.assertEqual(im.size, (1180, 980))
        im, _r = self.render("picker", env={"BROMIGOS_DEN_TV_OPEN": "picker"})
        px = im.load()
        posters = sum(1 for x in range(0, im.width, 4) for y in range(0, im.height, 4)
                      if px[x, y][0] > 180 and px[x, y][1] > 140 and px[x, y][2] < 90)
        self.assertGreater(posters, 100, "the picker drew no posters")
        self.assertTrue(self.jf.requests("IncludeItemTypes=Series"))     # the server's shows, listed


if __name__ == "__main__":
    unittest.main()
