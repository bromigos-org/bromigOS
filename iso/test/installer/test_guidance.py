"""How would you like to be guided? (the installers' first step), VECTOR's voice in the installers
and the tours, and Ask VECTOR (docs/voice-guide.md). No audio hardware and no sound: the voice
guide's player is handed stand-ins, the tours' brain is a small stand-in server, and the
graphical installer draws offscreen in a headless weston of its own.

  python -m unittest discover -s iso/test/installer -p 'test_guidance.py'
"""
import asyncio
import http.server
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import unittest

HERE = os.path.dirname(os.path.realpath(__file__))
sys.path.insert(0, HERE)
import test_tui  # noqa: E402  (the recorded disks, the fake store and back end, the test's own settings)
from test_tui import HAVE, LIB  # noqa: E402

REPO = os.path.realpath(os.path.join(HERE, "../../.."))
CONSOLE_TOUR = os.path.join(REPO, "bin/bromigos-welcome-console")
ISO_INSTALL = os.path.join(HERE, "../../profile/airootfs/usr/local/bin/bromigos-iso-install")
import bromigos_guide as G  # noqa: E402
import bromigos_firstrun as F  # noqa: E402
from bromigos_installer import backend, common  # noqa: E402

if HAVE:
    from bromigos_installer import tui


class FakeProc:
    """What the guide's player would have run (Guide._start's commands), instead of running it."""
    played = []


def read(path):
    with open(path) as f:
        return f.read()


def clips():
    """The lines played, by id (the clip each command was given)."""
    return [os.path.basename(next(x for x in a if x.endswith(".opus"))).rsplit("-", 1)[0]
            for a in FakeProc.played if any(x.endswith(".opus") for x in a)]


class Settings(unittest.TestCase):
    """Each test its own voice-guide.json and accessibility.json."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.old = {k: os.environ.get(k) for k in ("BROMIGOS_GUIDE_STATE", "BROMIGOS_ACCESS_STATE")}
        os.environ["BROMIGOS_GUIDE_STATE"] = os.path.join(self.tmp, "voice-guide.json")
        os.environ["BROMIGOS_ACCESS_STATE"] = os.path.join(self.tmp, "accessibility.json")
        FakeProc.played = []
        self.real_start = G.Guide._start
        G.Guide._start = lambda guide, argvs: (FakeProc.played.extend(argvs), True)[1]

    def tearDown(self):
        G.Guide._start = self.real_start
        for k, v in self.old.items():
            os.environ.pop(k, None)
            if v is not None:
                os.environ[k] = v
        os.environ.pop("BROMIGOS_REDUCED_MOTION", None)
        os.environ["BROMIGOS_REDUCED_MOTION"] = "1"


class TextInstaller(Settings):
    def setUp(self):
        if not HAVE:
            self.skipTest("textual isn't installed")
        super().setUp()

    def run_app(self, body, size=(120, 42)):
        async def go():
            app = tui.Installer()
            async with app.run_test(size=size) as pilot:
                await pilot.pause(0.3)
                return await body(app, pilot)
        return asyncio.run(go())

    def test_guidance_is_the_first_step_and_its_caption_is_the_catalogues(self):
        async def body(app, pilot):
            line = str(app.query_one("#vector-line").render())
            return app.step, app.steps()[0], line, [w.id for w in app.query("#step-guide Switch")], \
                len(app.query("#step-guide #locale"))
        step, first, line, switches, locale = self.run_app(body)
        self.assertEqual((step, first), ("guide", "guide"))
        self.assertIn(G.line("installer.guide"), line)
        self.assertEqual(switches, ["g-voice", "g-screen_reader", "g-console_font", "g-high_contrast", "g-reduce_motion"])
        self.assertEqual(locale, 1)                          # the language is on the first step
        self.assertEqual(common.steps_for(common.defaults())[0], "guide")      # the graphical installer's too

    def test_ctrl_v_turns_the_voice_on_then_mutes_it(self):
        async def body(app, pilot):
            seen = [(app.voice.enabled, app.voice.muted)]
            for _ in range(3):
                await pilot.press("ctrl+v")                  # Ctrl+Alt+V, as the Linux console reads it
                await pilot.pause(0.1)
                seen.append((app.voice.enabled, app.voice.muted, str(app.query_one("#hint").render()),
                             app.query_one("#g-voice").value))
            return seen, dict(app.a["guidance"])
        seen, g = self.run_app(body)
        self.assertEqual(seen[0], (False, False))            # off until someone turns it on
        self.assertEqual(seen[1][:2], (True, False))
        self.assertTrue(seen[1][3])                          # the step's switch follows the key
        self.assertEqual(seen[2][:2], (True, True))
        self.assertIn("Ctrl+Alt+V voice muted", seen[2][2])
        self.assertEqual(seen[3][:2], (True, False))
        self.assertTrue(g["voice"] and not g["voice_muted"])
        self.assertTrue(G.settings()["enabled"])             # remembered in voice-guide.json

    def test_each_step_speaks_once_and_back_stops_him(self):
        async def body(app, pilot):
            app.voice._out = ("aplay", "ffmpeg")             # a sound card: the console's way (ALSA)
            await pilot.press("ctrl+v")
            await pilot.pause(0.1)
            await pilot.press("ctrl+n")                      # Welcome
            await pilot.pause(0.3)
            await app.show("welcome")                        # drawn again: not said again
            await pilot.pause(0.2)
            n = len(FakeProc.played)
            await pilot.press("escape")                      # back: he stops, the first step isn't read again
            await pilot.pause(0.3)
            return app.step, n, list(FakeProc.played)
        step, n, played = self.run_app(body)
        self.assertEqual(step, "guide")
        self.assertEqual(clips(), ["installer.guide", "installer.welcome.short"])      # each decoded, then aplay
        self.assertEqual(played[0][0], "ffmpeg")
        self.assertEqual(played[1][:2], ["aplay", "-q"])
        self.assertEqual(n, 4)
        self.assertEqual(len(played), 4)

    def test_quiet_while_a_screen_reader_talks(self):
        async def body(app, pilot):
            app.voice._out = ("pw-play", None)
            app.voice.screen_reader = lambda: "espeakup"
            await pilot.press("ctrl+v")
            await pilot.pause(0.1)
            await pilot.press("ctrl+n")
            await pilot.pause(0.3)
            return app.voice.status(), str(app.query_one("#hint").render())
        status, hint = self.run_app(body)
        self.assertEqual(status, "screen-reader")
        self.assertEqual(FakeProc.played, [])                # no second voice over the screen reader
        self.assertIn("voice quiet", hint)

    def test_the_choices_reach_the_install_and_the_new_user(self):
        async def body(app, pilot):
            for key in ("high_contrast", "reduce_motion"):
                app.query_one(f"#g-{key}").value = True
                await pilot.pause(0.1)
            app.query_one("#g-voice").value = True
            await pilot.pause(0.1)
            return dict(app.a["guidance"]), app.theme, app.animation_level
        g, theme, motion = self.run_app(body)
        self.assertTrue(g["high_contrast"] and g["reduce_motion"] and g["voice"])
        self.assertEqual((theme, motion), ("bromigos-hc", "none"))
        a = dict(common.defaults(), guidance=g, disk="/dev/sda", mode="erase", user="alex", password="p", hostname="h")
        doc = common.backend_answers(a, None)
        self.assertEqual(doc["guidance"]["voice_guide"], {"enabled": True, "muted": False})
        self.assertTrue(doc["guidance"]["accessibility"]["high_contrast"])
        self.assertIn("--motion reduced --contrast high", "\n".join(common.what_will_run(doc)))
        # bromigos-iso-install's own helpers write the new user's two files from those answers
        path = os.path.join(self.tmp, "answers.json")
        with open(path, "w") as f:
            json.dump(doc, f)
        funcs = "\n".join(line for line in read(ISO_INSTALL).splitlines() if line.startswith(("guidance()", "acc()")))
        out = {}
        for key in ("voice_guide", "accessibility"):
            r = subprocess.run(["bash", "-c", funcs + f'\nanswers={path}; guidance {key}'], capture_output=True, text=True)
            out[key] = json.loads(r.stdout)
        r = subprocess.run(["bash", "-c", funcs + f'\nanswers={path}; acc high_contrast; acc screen_reader'],
                           capture_output=True, text=True)
        self.assertEqual(r.stdout.split(), ["1", "0"])
        state = os.path.join(self.tmp, "home", ".local", "state", "bromigos")
        os.makedirs(state)
        with open(os.path.join(state, "voice-guide.json"), "w") as f:
            json.dump(out["voice_guide"], f)
        with open(os.path.join(state, "accessibility.json"), "w") as f:
            json.dump(out["accessibility"], f)
        # the welcome tour reads them at its start: the server's, in high contrast
        env = dict(os.environ, XDG_STATE_HOME=os.path.join(self.tmp, "home", ".local", "state"), PYTHONPATH=os.path.join(REPO, "lib"))
        for k in ("BROMIGOS_GUIDE_STATE", "BROMIGOS_ACCESS_STATE", "BROMIGOS_REDUCED_MOTION"):
            env.pop(k, None)
        shots = os.path.join(self.tmp, "shots")
        r = subprocess.run([sys.executable, CONSOLE_TOUR, "--live-shots", shots, "tour", "0.5", "--size", "100x36"], env=env,
                           capture_output=True, text=True, timeout=120)
        self.assertEqual(r.returncode, 0, r.stderr[-800:])
        svg = read(os.path.join(shots, "server-welcome-tour-0.5s.svg"))
        self.assertIn("#ffffff", svg.lower())                # high contrast's white on black
        with open(os.path.join(state, "voice-guide.json")) as f:
            self.assertTrue(json.load(f)["enabled"])

    def test_bigger_letters_only_on_a_real_console(self):
        real = backend.FAKE
        backend.FAKE = False
        try:
            os.environ["TERM"], term = "xterm-kitty", os.environ.get("TERM")
            ok, words = backend.console_font(True, tty="/dev/pts/3")
            self.assertFalse(ok)
            self.assertIn("terminal's own settings", words)
        finally:
            backend.FAKE = real
            if term is None:
                os.environ.pop("TERM", None)
            else:
                os.environ["TERM"] = term


class SpeechBoot(unittest.TestCase):
    """The boot menu's speech entry: the text installer, read aloud, the voice guide off."""

    def test_the_entry_starts_the_installer_with_the_screen_reader(self):
        prof = os.path.join(HERE, "../../profile")
        for p in ("grub/grub.cfg", "grub/loopback.cfg", "syslinux/archiso_tail.cfg"):
            text = read(os.path.join(prof, p))
            self.assertIn("accessibility=on bromigos.install=text bromigos.voice=off", text, p)
        console = read(os.path.join(HERE, "../../profile/airootfs/usr/local/bin/bromigos-iso-text-console"))
        self.assertIn("accessibility=on' <<<\"$cmd\" && exec /usr/local/bin/bromigos-iso-install --plain", console)

    def test_the_screen_reader_wins(self):
        words = "linux accessibility=on bromigos.install=text bromigos.voice=off".split()
        self.assertTrue(common.speech_boot(words))
        root = tempfile.mkdtemp()
        os.makedirs(os.path.join(root, "proc"))
        with open(os.path.join(root, "proc", "cmdline"), "w") as f:
            f.write(" ".join(words))
        g = G.Guide("console", state=os.path.join(root, "v.json"), root=root)
        self.assertEqual(g.status(), "off")
        g.toggle()                                            # turned on all the same: speakup still wins
        os.makedirs(os.path.join(root, "sys", "accessibility", "speakup"))
        with open(os.path.join(root, "sys", "accessibility", "speakup", "synth"), "w") as f:
            f.write("soft\n")
        self.assertEqual(g.status(), "screen-reader")

    def test_a_screen_reader_in_the_new_system(self):
        sys.path.insert(0, LIB)
        import answers
        path = os.path.join(tempfile.mkdtemp(), "a.json")
        doc = {"disk": "/dev/sda", "user": "u", "password": "p", "desktop": False,
               "guidance": {"accessibility": {"screen_reader": True, "console_font": True}}}
        with open(path, "w") as f:
            json.dump(doc, f)
        argv = answers.from_answers(path)
        self.assertEqual(argv[argv.index("--screen-reader") + 1], "console")
        self.assertIn("--console-font", argv)


class StubBrain(http.server.BaseHTTPRequestHandler):
    """VECTOR's brain, stood in: /v1/models answers, /v1/chat/completions says one thing."""
    asked = []
    delay = 0

    def log_message(self, *a):
        pass

    def do_GET(self):
        self.send_response(200 if self.path == "/v1/models" else 404)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(b'{"data": [{"id": "vector"}]}')

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        StubBrain.asked.append(body)
        time.sleep(StubBrain.delay)
        out = json.dumps({"choices": [{"message": {"content": "<think>hmm</think>Your lab runs my brain."}}]}).encode()
        try:
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(out)
        except OSError:
            pass


class AskVector(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), StubBrain)
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()
        cls.url = f"http://127.0.0.1:{cls.srv.server_address[1]}/v1"

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()

    def setUp(self):
        self.old = os.environ.get("BROMIGOS_VECTOR_BRAIN")
        StubBrain.asked, StubBrain.delay = [], 0

    def tearDown(self):
        os.environ["BROMIGOS_VECTOR_BRAIN"] = self.old or "none"

    def test_his_answer_with_the_steps_context(self):
        os.environ["BROMIGOS_VECTOR_BRAIN"] = "none"
        self.assertIsNone(F.brain())
        ok, words = F.ask("What's this?", "Your lab.")
        self.assertFalse(ok)
        self.assertIn("Settings › VECTOR", words)
        os.environ["BROMIGOS_VECTOR_BRAIN"] = self.url
        b = F.brain()
        self.assertEqual(b["url"], self.url)
        ok, words = F.ask("What does my lab give me?", "Your lab. Optional.", b)
        self.assertEqual((ok, words), (True, "Your lab runs my brain."))
        msgs = StubBrain.asked[-1]["messages"]
        self.assertIn("Your lab. Optional.", msgs[0]["content"])
        self.assertEqual(msgs[1], {"role": "user", "content": "What does my lab give me?"})

    def test_a_slow_brain_times_out_plainly(self):
        StubBrain.delay = 3
        ok, words = F.ask("Hello?", "", {"url": self.url, "model": "m", "key": "none"}, timeout=1)
        self.assertFalse(ok)
        self.assertIn("didn't answer in 1 seconds", words)

    def tour(self, brain, step="lab"):
        if not HAVE:
            self.skipTest("textual isn't installed")
        out = tempfile.mkdtemp()
        env = dict(os.environ, PYTHONPATH=os.path.join(REPO, "lib"), BROMIGOS_VECTOR_BRAIN=brain,
                   XDG_STATE_HOME=tempfile.mkdtemp())
        r = subprocess.run([sys.executable, CONSOLE_TOUR, "--live-shots", out, step, "2", "--size", "110x40"], env=env,
                           capture_output=True, text=True, timeout=120)
        self.assertEqual(r.returncode, 0, r.stderr[-800:])
        return read(os.path.join(out, f"server-welcome-{step}-2s.svg"))

    def test_the_box_is_hidden_without_a_brain_and_shown_with_one(self):
        self.assertNotIn("ASK&#160;VECTOR", self.tour("none"))
        self.assertIn("ASK&#160;VECTOR", self.tour(self.url))


class GraphicalInstaller(unittest.TestCase):
    """The graphical installer draws its guidance step first (headless weston, a D-Bus of its own)."""

    def test_the_guidance_step_draws_first(self):
        if not (shutil.which("weston") and shutil.which("dbus-run-session")):
            self.skipTest("weston and dbus-run-session are needed")
        out = tempfile.mkdtemp()
        r = subprocess.run(["dbus-run-session", "--", "bash", os.path.join(HERE, "render-gui.sh"), out, "--size", "1024x600"],
                           capture_output=True, text=True, timeout=300)
        import re
        drawn = re.findall(r"rendered (gui-[\w-]+\.png)", r.stdout)     # other programs' logs may share the lines
        self.assertTrue(drawn, r.stderr[-800:])
        self.assertEqual(drawn[:2], ["gui-guide.png", "gui-guide-on.png"])
        self.assertGreater(os.path.getsize(os.path.join(out, "gui-guide.png")), 10000)


if __name__ == "__main__":
    unittest.main()
