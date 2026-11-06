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

    def test_linking_on_the_website_streams_the_bridges_events(self):
        argv = self.F.lab_link_argv(gui=True)
        self.assertEqual(argv[:4], ["pkexec", "brodec-lab", "connect", "--json"])
        self.assertIn("bromigos-setup", argv)
        self.assertEqual(self.F.lab_link_argv(gui=False, intent="hosted")[0], "sudo")
        p = self.script("connect", "echo '{\"event\":\"code\",\"user_code\":\"KX7-42Q\",\"qr\":\"x\"}'\n"
                                   "echo '{\"event\":\"approved\",\"intent\":\"hosted\"}'\n"
                                   "echo '{\"event\":\"hosted\",\"order_id\":null}'\n")
        evs = []
        self.F.Pairing([p], evs.append)
        self.assertTrue(self.wait(lambda: len(evs) == 3))
        self.assertEqual([e["event"] for e in evs], ["code", "approved", "hosted"])
        import time
        time.sleep(0.2)
        self.assertEqual(len(evs), 3, "hosted ends it: no failure after a clean exit")
        self.assertIn("bromigos.org", self.F.pairing_words(evs[2]))
        self.assertIn("turned down", self.F.pairing_words({"event": "failed", "code": "denied"}))

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


class LabStep(unittest.TestCase):
    """Your lab: the link through BRODEC's lab bridge (brodec-lab connect --json), stopped when the
    tour cancels it, its events in words, the bridge's service after linking, the card's name."""

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

    def wait(self, cond, n=100):
        import time
        for _ in range(n):
            if cond():
                return True
            time.sleep(0.05)
        return False

    def test_watched_runs_the_same_command_through_pkexec(self):
        argv = self.F.lab_link_watched("hosted", timeout=120)
        self.assertEqual(argv[:3], ["pkexec", "sh", "-c"])
        self.assertEqual(argv[5:], self.F.lab_link_argv(gui=True, intent="hosted", timeout=120)[1:])
        self.assertEqual(self.F.watched(["sudo", "x"]), ["sudo", "x"])

    def test_cancel_closes_stdin_and_stops_the_bridge(self):
        """Run as root, the bridge can't be signalled by the tour: closing its stdin stops it."""
        pidf = os.path.join(self.tmp, "pid")
        bridge = self.script("bridge", f"echo $$ > {pidf}\n"
                                       "echo '{\"event\":\"code\",\"user_code\":\"KX7-42Q\",\"expires_in\":600}'\n"
                                       "trap '' TERM\nwhile :; do sleep 0.1; done\n")
        evs = []
        # SIGTERM is ignored by the stand-in, as a root process ignores ours: only the pipe stops it
        argv = ["sh", "-c", self.F.STDIN_WATCH.replace('kill -TERM "$p"', 'kill -KILL "$p"'), "t", bridge]
        pr = self.F.Pairing(argv, evs.append, hold_stdin=True)
        self.assertTrue(self.wait(lambda: evs and os.path.exists(pidf)))
        self.assertEqual(evs[0]["user_code"], "KX7-42Q")
        pid = int(open(pidf).read())
        pr.cancel()
        self.assertTrue(self.wait(lambda: evs[-1]["event"] == "cancelled"))

        def gone():
            try:
                os.kill(pid, 0)
                with open(f"/proc/{pid}/stat") as f:
                    return f.read().split()[2] == "Z"
            except OSError:
                return True
        self.assertTrue(self.wait(gone), "the bridge still runs after cancel")

    def test_a_finished_link_ends_cleanly(self):
        bridge = self.script("bridge", "echo '{\"event\":\"code\",\"user_code\":\"A\"}'\n"
                                       "echo '{\"event\":\"approved\",\"intent\":\"self-hosted\"}'\n"
                                       "echo '{\"event\":\"paired\",\"owner\":\"a@example.org\",\"name\":\"desk\"}'\n")
        evs = []
        self.F.Pairing(["sh", "-c", self.F.STDIN_WATCH, "t", bridge], evs.append, hold_stdin=True)
        self.assertTrue(self.wait(lambda: len(evs) == 3))
        import time
        time.sleep(0.3)
        self.assertEqual([e["event"] for e in evs], ["code", "approved", "paired"])

    def test_every_event_has_words(self):
        w = self.F.link_words
        self.assertIn("new one", w({"event": "expired", "user_code": "A"}))
        self.assertIn("Linking this computer", w({"event": "approved"}, "self-hosted"))
        self.assertIn("Waiting for the website", w({"event": "approved"}, "hosted"))
        for code, words in (("denied", "turned down"), ("timeout", "in time"), ("already_paired", "already a lab"),
                            ("rate_limited", "Wait a minute"), ("not_installed", "Install it")):
            self.assertIn(words, w({"event": "failed", "code": code, "message": "x"}), code)
        self.assertIn("password window was closed",
                      w({"event": "failed", "code": "agent_failed",
                         "message": "Error executing command as another user: Request dismissed"}))
        self.assertIn("boom", w({"event": "failed", "code": "unreadable", "message": "Traceback\nboom"}))
        self.assertIn("Try again", w({"event": "cancelled"}))
        self.assertEqual(w({"event": "paired"}), "")

    def test_the_bridge_service_after_linking(self):
        log = os.path.join(self.tmp, "log")
        bindir = os.path.join(self.tmp, "bin")
        os.makedirs(bindir)
        for name, body in (("systemctl", f'echo "systemctl $*" >> {log}\n[ "$1" = is-active ] && exit ${{ACTIVE:-1}}\n'),
                           ("pkexec", f'echo "pkexec $*" >> {log}\n')):
            p = os.path.join(bindir, name)
            with open(p, "w") as f:
                f.write("#!/bin/sh\n" + body)
            os.chmod(p, 0o755)
        old = os.environ["PATH"]
        os.environ["PATH"] = bindir + ":" + old
        try:
            os.environ["ACTIVE"] = "0"
            self.assertEqual(self.F.lab_bridge_service(lambda l: None)[0], "running")
            os.environ["ACTIVE"] = "3"
            self.assertEqual(self.F.lab_bridge_service(lambda l: None)[0], "started")
        finally:
            os.environ["PATH"] = old
            os.environ.pop("ACTIVE", None)
        self.assertIn("pkexec systemctl enable --now brodec-lab", open(log).read())

    def test_the_cards_name(self):
        hw = lambda *gs: {"detection": {"gpus": list(gs)}}  # noqa: E731
        self.assertEqual(self.F.gpu_name(hw({"vendor": "NVIDIA", "name": "AD104 [GeForce RTX 4070]"})), "RTX 4070")
        self.assertEqual(self.F.gpu_name(hw({"vendor": "Intel", "name": "UHD 770"},
                                            {"vendor": "AMD", "name": "Navi 31 [Radeon RX 7900 XTX]"})),
                         "Radeon RX 7900 XTX")
        self.assertEqual(self.F.gpu_name(hw()), "")

    def test_vector_has_a_line_for_each_view(self):
        import tomllib
        with open(os.path.join(HERE, "../../lib/guide/lines.toml"), "rb") as f:
            lines = tomllib.load(f)
        for key in ("tour.lab", "tour.lab-link", "tour.lab-find"):
            self.assertTrue(lines.get(key, {}).get("text"), key)

    def test_the_renders_draw_every_lab_view(self):
        mod = load()
        self.assertEqual(mod.SAMPLE_LINK["event"], "code")
        self.assertIn("lab-hosted", mod.LAB_STATES)
        self.assertIn("lab-find", mod.LAB_STATES)
