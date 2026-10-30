"""The welcome tour (bromigos welcome): it only opens when an install left it pending; Wi-Fi
networks read from nmcli as people see them; each step changes things only through
`bromigos setup` (a stand-in records what it's asked)."""
import importlib.machinery
import importlib.util
import os
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.realpath(__file__))
BIN = os.path.join(HERE, "../bin/bromigos-welcome")


def load():
    loader = importlib.machinery.SourceFileLoader("bromigos_welcome", BIN)
    spec = importlib.util.spec_from_loader("bromigos_welcome", loader)
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    return mod


class Welcome(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.env = dict(os.environ, XDG_STATE_HOME=os.path.join(self.tmp, "state"), PATH=os.path.join(self.tmp, "bin") + ":/usr/bin:/bin")
        os.makedirs(os.path.join(self.tmp, "bin"))

    def stub(self, name, script):
        p = os.path.join(self.tmp, "bin", name)
        open(p, "w").write("#!/bin/sh\n" + script)
        os.chmod(p, 0o755)

    def test_not_pending_opens_nothing(self):
        r = subprocess.run([sys.executable, BIN, "--if-pending"], env=self.env, capture_output=True, text=True, timeout=30)
        self.assertEqual(r.returncode, 0)
        self.assertEqual(r.stdout + r.stderr, "")

    def test_wifi_list(self):
        self.stub("nmcli", "printf '%s\\n' '*:Home Net:82:WPA2' ':Cafe\\:Guest:40:--' ':Home Net:30:WPA2' ':Hidden::'\n")
        os.environ["PATH"] = self.env["PATH"]
        nets = load().wifi_list()
        self.assertEqual([n["ssid"] for n in nets], ["Home Net", "Cafe:Guest", "Hidden"])
        self.assertTrue(nets[0]["connected"] and nets[0]["secure"])
        self.assertFalse(nets[1]["secure"])

    def test_setup_is_the_only_way(self):
        log = os.path.join(self.tmp, "setup.log")
        self.stub("bromigos", f'echo "$@" >> {log}\n')
        os.environ["PATH"] = self.env["PATH"]
        mod = load()
        self.assertEqual(mod.setup("theme", "--theme", "mire")[0], 0)
        self.assertEqual(open(log).read().strip(), "setup theme --theme mire")

    def test_every_step_has_words(self):
        mod = load()
        for sid, short, head, intro in mod.STEPS:
            self.assertTrue(short and head and intro, sid)


if __name__ == "__main__":
    unittest.main()


class Pairing(unittest.TestCase):
    """Pair your phone follows brodec-machine's `pair --json` events, and answers
    `brodec-machine enroll`'s question with the window's (BRODEC's docs/MACHINE_JOBS.md)."""

    def setUp(self):
        sys.path.insert(0, os.path.join(HERE, "../../lib"))
        import bromigos_firstrun
        self.F = bromigos_firstrun
        self.tmp = tempfile.mkdtemp()

    def script(self, name, body):
        p = os.path.join(self.tmp, name)
        with open(p, "w") as f:
            f.write("#!/bin/sh\n" + body)
        os.chmod(p, 0o755)
        return p

    def wait(self, cond):
        import time
        for _ in range(100):
            if cond():
                return True
            time.sleep(0.05)
        return False

    def test_events_in_order(self):
        p = self.script("pair", "echo '{\"event\":\"waiting\",\"reason\":\"starting\",\"message\":\"Starting\"}'\n"
                                "echo 'not json'\n"
                                "echo '{\"event\":\"code\",\"qr\":\"x\",\"user_code_display\":\"ABCD-EFGH\"}'\n"
                                "echo '{\"event\":\"paired\",\"owner\":\"@a:example.org\"}'\n")
        evs = []
        self.F.Pairing([p], evs.append)
        self.assertTrue(self.wait(lambda: len(evs) == 3))
        self.assertEqual([e["event"] for e in evs], ["waiting", "code", "paired"])

    def test_a_silent_end_is_a_failure_in_words(self):
        p = self.script("pair", "echo 'agent exploded' >&2\nexit 1\n")
        evs = []
        self.F.Pairing([p], evs.append)
        self.assertTrue(self.wait(lambda: evs))
        self.assertEqual(evs[0]["event"], "failed")
        self.assertIn("agent exploded", self.F.pairing_words(evs[0]))

    def test_no_capability_file_says_what_to_press(self):
        words = self.F.pairing_words({"event": "failed", "code": "no_capability_file"})
        self.assertIn("Allow pairing", words)

    def test_cancel_stops_the_watching(self):
        p = self.script("pair", "trap 'exit 130' TERM\necho '{\"event\":\"waiting\",\"reason\":\"starting\"}'\n"
                                "while :; do sleep 0.1; done\n")
        evs = []
        pr = self.F.Pairing([p], evs.append)
        self.assertTrue(self.wait(lambda: evs))
        pr.cancel()
        self.assertTrue(self.wait(lambda: evs[-1]["event"] == "cancelled"))

    def test_enroll_shows_the_phone_then_answers(self):
        fake = self.script("enroll", "printf 'Pixel 9 (key 4F:2A) asks to send jobs to desk.\\nAllow it? [y/N] '\n"
                                     "read a; [ \"$a\" = y ] && echo '1 phone(s) can now send jobs to desk.'\n")
        asked, result = [], []
        real = subprocess.Popen
        subprocess.Popen = lambda argv, *a, **k: real([fake], *a, **k)
        try:
            self.F.Enroll(lambda t: (asked.append(t), True)[1], lambda ok, w: result.append((ok, w)), user="alex")
            self.assertTrue(self.wait(lambda: result))
        finally:
            subprocess.Popen = real
        self.assertIn("Pixel 9 (key 4F:2A)", asked[0])
        self.assertTrue(result[0][0])
        self.assertIn("can now send jobs", result[0][1])
