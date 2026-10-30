"""`bromigos bluetooth session` (the TUI's bluez core, bromigos_btsession) against the stand-in
bluez on a private D-Bus, and a controller's evdev input and rumble (bromigos_gamepad) on a
made-up sysfs and event stream. Nothing reaches the machine's Bluetooth or input devices."""
import json
import os
import shutil
import struct
import subprocess
import sys
import tempfile
import threading
import time
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
DESKTOP = os.path.dirname(HERE)
sys.path[:0] = [HERE, os.path.join(DESKTOP, "lib")]

import bromigos_btsession as S  # noqa: E402
import bromigos_gamepad as G  # noqa: E402

HAVE_BUS = shutil.which("dbus-daemon") is not None
PAD = "00:00:5E:00:53:12"


def ev(t, code, value):
    return G.EVENT.pack(0, 0, t, code, value)


class Pure(unittest.TestCase):
    def test_mic_level(self):
        self.assertEqual(S.level(b""), 0.0)
        self.assertEqual(S.level(struct.pack("<4h", 0, 0, 0, 0)), 0.0)
        loud = S.level(struct.pack("<4h", 32767, -32767, 32767, -32767))
        quiet = S.level(struct.pack("<4h", 33, -33, 33, -33))
        self.assertGreater(loud, 0.95)
        self.assertLess(quiet, 0.05)

    def test_sound_of(self):
        got = S.sound_of([{"name": "bluez_output.00_00_5E_00_53_10.1"}, {"name": "alsa_output.x"}],
                         [{"name": "bluez_input.00_00_5E_00_53_10.0"}, {"name": "bluez_output.00_00_5E_00_53_10.1.monitor"}],
                         {"default_sink_name": "alsa_output.x"})
        self.assertEqual(got["devices"], {"00:00:5E:00:53:10": {"output": "bluez_output.00_00_5E_00_53_10.1",
                                                                 "input": "bluez_input.00_00_5E_00_53_10.0"}})
        self.assertEqual(got["defaults"]["output"], "alsa_output.x")


class Gamepad(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="gp-")
        dev = os.path.join(self.root, "sys/class/input/event7/device")
        os.makedirs(os.path.join(dev, "capabilities"))
        with open(os.path.join(dev, "uniq"), "w") as f:
            f.write(PAD.lower() + "\n")
        with open(os.path.join(dev, "capabilities", "key"), "w") as f:
            f.write("7fff000000000000 0 0 0 0\n")          # BTN_SOUTH and the rest of a pad
        mouse = os.path.join(self.root, "sys/class/input/event8/device")
        os.makedirs(os.path.join(mouse, "capabilities"))
        with open(os.path.join(mouse, "uniq"), "w") as f:
            f.write(PAD.lower())                           # same address, no gamepad buttons
        with open(os.path.join(mouse, "capabilities", "key"), "w") as f:
            f.write("1f0000 0 0 0 0\n")

    def tearDown(self):
        shutil.rmtree(self.root)

    def test_find_by_address(self):
        self.assertEqual(G.find(PAD, self.root), os.path.join(self.root, "dev/input/event7"))
        self.assertIsNone(G.find("00:00:5E:00:53:99", self.root))
        self.assertEqual(G._bits("1 0"), {64})

    def test_events_become_buttons_and_axes(self):
        data = (ev(G.EV_KEY, 0x130, 1) + ev(G.EV_KEY, 0x136, 1) + ev(G.EV_ABS, 0x00, 65535) +
                ev(G.EV_ABS, 0x02, 512) + ev(G.EV_ABS, 0x10, -1) + ev(G.EV_KEY, 0x132, 1))
        p = G.Pad.__new__(G.Pad)
        p.ranges = {0x00: (0, 65535), 0x02: (0, 1023)}
        p.held, p.effect = set(), None
        p.axes = {"lx": 0.0, "ly": 0.0, "rx": 0.0, "ry": 0.0, "lt": 0.0, "rt": 0.0, "dx": 0, "dy": 0}
        p.feed(G.parse(data))
        self.assertEqual(p.buttons, ["A", "LB", "LEFT", "X"])      # the basic driver's X too
        self.assertEqual(p.axes["lx"], 1.0)
        self.assertAlmostEqual(p.axes["lt"], 0.5, places=2)
        p.feed(G.parse(ev(G.EV_KEY, 0x130, 0) + ev(G.EV_ABS, 0x10, 0)))
        self.assertEqual(p.buttons, ["LB", "X"])

    def test_norm(self):
        self.assertEqual(G.norm(-32768, (-32768, 32767)), -1.0)
        self.assertEqual(G.norm(0, (-32768, 32767)), 0.0)
        self.assertEqual(G.norm(1023, (0, 1023), centred=False), 1.0)
        self.assertEqual(G.norm(5, (0, 0)), 0.0)

    def test_a_real_file_reads_and_rumble_says_no_without_a_driver(self):
        path = os.path.join(self.root, "events")
        with open(path, "wb") as f:
            f.write(ev(G.EV_KEY, 0x131, 1))
        p = G.Pad(path)                    # a plain file: no absinfo, no force feedback
        self.assertTrue(p.read())
        self.assertEqual(p.buttons, ["B"])
        self.assertFalse(p.rumble())
        p.close()


@unittest.skipUnless(HAVE_BUS, "needs dbus-daemon")
class Live(unittest.TestCase):
    def setUp(self):
        from fake_bluez import FakeBluez
        self.fb = FakeBluez(instant=True).__enter__()
        self.tmp = tempfile.mkdtemp(prefix="bts-")
        env = dict(os.environ, BROMIGOS_BLUEZ_BUS=self.fb.address, PYTHONPATH=os.path.join(DESKTOP, "lib"),
                   PATH=f"{HERE}/fixtures/bin:{DESKTOP}/bin:/usr/bin", BROMIGOS_FIXTURE_STATE=self.tmp,
                   BROMIGOS_PERIPHERAL_ROOT=os.path.join(self.tmp, "root"), HOME=self.tmp,
                   XDG_CONFIG_HOME=os.path.join(self.tmp, ".config"))
        self.p = subprocess.Popen([sys.executable, os.path.join(DESKTOP, "bin", "bromigos-bluetooth"), "session"],
                                  env=env, stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
        self.out = []
        threading.Thread(target=self._read, daemon=True).start()

    def _read(self):
        for line in self.p.stdout:
            self.out.append(json.loads(line))

    def tearDown(self):
        try:
            self.p.stdin.close()
            self.p.wait(5)
        except Exception:
            self.p.kill()
        self.p.stdout.close()
        self.fb.__exit__()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def send(self, doc):
        self.p.stdin.write(json.dumps(doc) + "\n")
        self.p.stdin.flush()

    def wait(self, fn, secs=8):
        end = time.monotonic() + secs
        while time.monotonic() < end:
            got = fn()
            if got:
                return got
            time.sleep(0.05)
        self.fail(f"waited for nothing: {self.out[-3:]}")

    def reply(self, rid):
        return self.wait(lambda: next((m for m in self.out if m["t"] == "reply" and m["id"] == rid), None))

    def state(self):
        got = [m for m in self.out if m["t"] == "state"]
        return got[-1]["state"] if got else {}

    def test_state_then_scan_pair_with_a_code(self):
        self.wait(lambda: any(m["t"] == "state" for m in self.out))
        kinds = next(m for m in self.out if m["t"] == "kinds")
        self.assertEqual(self.out[0], kinds, "the kinds come first")
        # the TUI's tests draw the session's own kinds
        with open(os.path.join(DESKTOP, "..", "core", "crates", "bromigos-bt", "tests", "fixtures", "kinds.json")) as f:
            self.assertEqual(json.load(f), kinds)
        self.assertIn("Xbox", kinds["kinds"][0]["steps"][0])
        self.assertEqual(self.state()["adapter"]["alias"], "workstation")
        self.send({"id": 1, "do": "scan", "on": True})
        self.assertTrue(self.reply(1)["ok"])
        self.wait(lambda: any(d["name"] == "Pixel 9" for d in self.state()["devices"]))
        self.send({"id": 2, "do": "pair", "mac": "00:00:5E:00:53:21"})
        q = self.wait(lambda: next((m for m in self.out if m["t"] == "prompt"), None))
        self.assertEqual((q["what"], q["name"], q["value"]), ("confirm", "Pixel 9", "123456"))
        self.send({"answer": q["pid"], "value": True})
        self.assertTrue(self.reply(2)["ok"])
        steps = [m["step"] for m in self.out if m["t"] == "step" and m["id"] == 2]
        self.assertEqual(steps, ["pairing", "trusting", "connecting"])

    def test_a_refused_code_and_plain_errors(self):
        self.wait(lambda: any(m["t"] == "state" for m in self.out))
        self.send({"id": 1, "do": "scan", "on": True})
        self.reply(1)
        self.wait(lambda: any(d["name"] == "Pixel 9" for d in self.state()["devices"]))
        self.send({"id": 2, "do": "pair", "mac": "00:00:5E:00:53:21"})
        q = self.wait(lambda: next((m for m in self.out if m["t"] == "prompt"), None))
        self.send({"answer": q["pid"], "value": False})
        r = self.reply(2)
        self.assertFalse(r["ok"])
        self.assertIn("said no", r["error"])
        self.send({"id": 3, "do": "connect", "mac": "00:00:5E:00:53:FF"})
        self.assertIn("gone", self.reply(3)["error"])
        self.send({"id": 4, "do": "fly"})
        self.assertIn("unknown request", self.reply(4)["error"])
        self.send({"id": 5, "do": "input", "mac": PAD})
        self.assertIn("isn't there", self.reply(5)["error"])
        self.send({"id": 6, "do": "rename", "mac": PAD, "name": "  "})
        self.assertIn("empty", self.reply(6)["error"])

    def test_sound_and_reset(self):
        self.wait(lambda: self.state().get("audio"))
        st = self.state()
        self.assertEqual(st["audio"]["00:00:5E:00:53:10"]["codec"], "LDAC")
        self.assertEqual(st["sound"]["devices"]["00:00:5E:00:53:10"]["output"], "bluez_output.00_00_5E_00_53_10.1")
        self.send({"id": 1, "do": "profile", "mac": "00:00:5E:00:53:10", "mode": "headset"})
        self.assertTrue(self.reply(1)["ok"])
        self.wait(lambda: self.state()["audio"]["00:00:5E:00:53:10"]["mode"] == "headset")
        self.send({"id": 2, "do": "reset"})
        r = self.reply(2)
        self.assertTrue(r["ok"], r)
        self.assertTrue(self.state()["adapter"]["powered"])


if __name__ == "__main__":
    unittest.main()
