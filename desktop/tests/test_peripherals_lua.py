"""bromigos/peripherals.lua (the default Hyprland config's loader) with a generated
hypr.lua, run by hl-record.lua's stand-in `hl`: the devices get the tag and the keymap
options after the user's, the keys bind on those devices only, and a key the module marks
exclusive keeps its default bind but off the module's devices.

    PYTHONPATH=lib python -m unittest discover -s tests
"""
import os
import shutil
import subprocess
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
DESKTOP = os.path.dirname(HERE)

GENERATED = '''return {
    {
        id = "razer-keyboard",
        tag = "bromigos-razer-keyboard",
        devices = { "razer-razer-blackwidow-v4-pro", "razer-razer-blackwidow-v4-pro-1" },
        kb_options = { "fkeys:basic_13-24" },
        exclusive = { "XF86AudioMicMute" },
        binds = {
            { keys = "code:191", cmd = "/usr/bin/bromigos-holo vector", hint = "M1" },
            { keys = "code:192", cmd = "/usr/bin/bromigos-holo ptt off", release = true, hint = "M2" },
        },
    },
}
'''

USER = '''bromigos = { config = { input = { kb_options = "caps:escape" } } }
dofile(os.getenv("BROMIGOS_SHARE_DIR") .. "/default/hypr/hyprland.lua")
'''


@unittest.skipUnless(shutil.which("lua"), "needs lua")
class LoaderTest(unittest.TestCase):
    def record(self, generated):
        with tempfile.TemporaryDirectory() as tmp:
            share = os.path.join(tmp, "share", "default")
            os.makedirs(share)
            os.symlink(os.path.join(DESKTOP, "hypr"), os.path.join(share, "hypr"))
            state = os.path.join(tmp, "state")
            if generated is not None:
                os.makedirs(os.path.join(state, "bromigos", "peripherals"))
                with open(os.path.join(state, "bromigos", "peripherals", "hypr.lua"), "w") as f:
                    f.write(generated)
            conf = os.path.join(tmp, "hyprland.lua")
            with open(conf, "w") as f:
                f.write(USER)
            env = {"HOME": tmp, "PATH": os.environ.get("PATH", "/usr/bin"), "XDG_STATE_HOME": state,
                   "BROMIGOS_SHARE_DIR": os.path.join(tmp, "share")}
            r = subprocess.run(["lua", os.path.join(HERE, "hl-record.lua"), conf], env=env,
                               capture_output=True, text=True, timeout=30)
            self.assertEqual(r.returncode, 0, r.stderr)
            return [line.split("\t") for line in r.stdout.splitlines() if line]

    def test_devices_keys_and_exclusions(self):
        rows = self.record(GENERATED)
        devices = [r for r in rows if r[0] == "device"]
        self.assertEqual([d[1] for d in devices], ["razer-razer-blackwidow-v4-pro", "razer-razer-blackwidow-v4-pro-1"])
        self.assertTrue(all(d[2] == "bromigos-razer-keyboard" for d in devices))
        self.assertTrue(all(d[3] == "caps:escape,fkeys:basic_13-24" for d in devices), devices)
        binds = [r for r in rows if r[0] == "bind"]
        m1 = [b for b in binds if b[1] == "code:191"]
        self.assertEqual(len(m1), 1)
        self.assertEqual(m1[0][3], "bromigos-razer-keyboard")
        self.assertIn("bromigos-holo vector", m1[0][4])
        m2 = [b for b in binds if b[1] == "code:192"]
        self.assertEqual(m2[0][2], "release")
        mic = [b for b in binds if b[1] == "XF86AudioMicMute"]
        self.assertEqual(len(mic), 1)
        self.assertEqual(mic[0][3], "!bromigos-razer-keyboard")
        # everything else is bound as before (the volume keys: no device list)
        vol = [b for b in binds if b[1] == "XF86AudioRaiseVolume"]
        self.assertEqual(vol[0][3], "")

    def test_no_module_on_changes_nothing(self):
        without = self.record(None)
        self.assertFalse([r for r in without if r[0] == "device"])
        self.assertFalse([r for r in without if r[1] in ("code:191", "code:192")])
        mic = [b for b in without if b[1] == "XF86AudioMicMute"]
        self.assertEqual(mic[0][3], "")
        broken = self.record("this isn't lua {")
        self.assertEqual(broken, without)


if __name__ == "__main__":
    unittest.main()
