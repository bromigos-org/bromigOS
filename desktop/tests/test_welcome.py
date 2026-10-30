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
