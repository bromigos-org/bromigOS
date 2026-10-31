"""The voice guide (lib/bromigos_guide.py, lib/guide/): the catalogue and its clips, the
settings, and the player's choices, with stand-in players on PATH and a stand-in /proc. No
sound plays and no audio hardware is needed.

    PYTHONPATH=lib python -m unittest discover -s tests/voice-guide -v
"""
import ast
import json
import os
import shutil
import stat
import sys
import tempfile
import time
import unittest

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.realpath(__file__))))
sys.path.insert(0, os.path.join(REPO, "lib"))
import bromigos_guide as G  # noqa: E402

GUIDE = os.path.join(REPO, "lib", "guide")
INSTALLER = os.path.join(REPO, "iso/profile/airootfs/usr/local/lib/bromigos-iso/bromigos_installer")


class Catalogue(unittest.TestCase):
    def test_every_line_has_a_clip_that_says_its_words(self):
        self.assertEqual(G.problems(GUIDE), [])

    def test_clips_are_small_mono_opus(self):
        man = G.manifest(GUIDE)["clips"]
        total = 0
        for key, m in man.items():
            path = os.path.join(GUIDE, "clips", m["file"])
            with open(path, "rb") as f:
                head = f.read(64)
            self.assertTrue(head.startswith(b"OggS") and b"OpusHead" in head, key)
            self.assertEqual(head[head.find(b"OpusHead") + 9], 1, f"{key} isn't mono")
            total += os.path.getsize(path)
        self.assertLess(total, 4 * 1024 * 1024)

    def test_captions_equal_the_catalogue(self):
        cat = G.catalogue(GUIDE)
        man = G.manifest(GUIDE)["clips"]
        for key, lid, values, text in G.clips(GUIDE):
            self.assertEqual(G.line(lid, GUIDE, **values), text, key)
            self.assertEqual(man[key]["text"], text, key)
            if not values:
                self.assertEqual(G.line(lid, GUIDE), cat[lid]["text"])

    def test_a_name_without_a_clip_plays_the_nearest_one(self):
        self.assertEqual(G.line("installer.disk.alongside", GUIDE, who="Ubuntu 24.04"),
                         "Ubuntu 24.04 keeps its files. I'll make room beside it.")
        self.assertEqual(G.spoken("installer.disk.alongside", GUIDE, who="Windows 11")[0],
                         "installer.disk.alongside[who=Windows]")
        self.assertEqual(G.spoken("installer.disk.alongside", GUIDE, who="Ubuntu 24.04")[0],
                         "installer.disk.alongside[who=the other system]")
        self.assertEqual(G.spoken("installer.disk.alongside", GUIDE)[0],
                         "installer.disk.alongside[who=the other system]")

    def test_short_lines(self):
        self.assertEqual(G.pick("installer.welcome", short=True, folder=GUIDE), "installer.welcome.short")
        self.assertEqual(G.pick("installer.edition", short=True, folder=GUIDE), "installer.edition")
        self.assertEqual(G.line("installer.nothing-here", GUIDE), "")

    def test_every_step_has_its_line(self):
        """The installers and the tours read their captions from the catalogue: every step they
        show has a line (and no copy of the words is left in their code to drift)."""
        cat = G.catalogue(GUIDE)
        steps = {
            "installer": [s[0] for s in _list_in(os.path.join(INSTALLER, "common.py"), "STEPS")],
            "tour": [s[0] for s in _list_in(os.path.join(REPO, "desktop/bin/bromigos-welcome"), "STEPS")],
            "server-tour": [s[0] for s in _list_in(os.path.join(REPO, "bin/bromigos-welcome-console"), "STEPS")],
        }
        for prefix, ids in steps.items():
            self.assertTrue(ids, prefix)
            for sid in ids:
                self.assertIn(f"{prefix}.{sid}", cat, f"{prefix} step {sid!r} has no line in lines.toml")
        for lid in ("installer.failed", "installer.guide.sample", "installer.install.copying", "installer.install.nearly",
                    "tour.hello", "server-tour.hello"):
            self.assertIn(lid, cat)
        for mode in ("alongside", "erase", "reinstall"):
            self.assertIn(f"installer.disk.{mode}", cat)
        for path, name in ((os.path.join(INSTALLER, "gui.py"), "VECTOR_LINES"), (os.path.join(INSTALLER, "tui.py"), "VECTOR_LINES"),
                           (os.path.join(REPO, "desktop/bin/bromigos-welcome"), "GUIDE"),
                           (os.path.join(REPO, "bin/bromigos-welcome-console"), "GUIDE")):
            self.assertIsNone(_dict_in(path, name), f"{os.path.relpath(path, REPO)} keeps its own {name}")

    def test_short_lines_say_less(self):
        """The text installer's .short lines are its narrow rail's: never longer than the full one."""
        cat = G.catalogue(GUIDE)
        for lid, v in cat.items():
            if lid.endswith(".short"):
                self.assertIn(lid[:-6], cat, lid)
                self.assertLessEqual(len(v["text"]), len(cat[lid[:-6]]["text"]), lid)


def _list_in(path, name):
    with open(path) as f:
        tree = ast.parse(f.read())
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and any(getattr(t, "id", None) == name for t in node.targets):
            try:
                return ast.literal_eval(node.value)
            except ValueError:
                return []
    return []


def _dict_in(path, name):
    try:
        with open(path) as f:
            tree = ast.parse(f.read())
    except (OSError, SyntaxError):
        return None
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and any(getattr(t, "id", None) == name for t in node.targets):
            try:
                return ast.literal_eval(node.value)
            except ValueError:
                return None
    return None


class Settings(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.state = os.path.join(self.tmp.name, "state", "bromigos", "voice-guide.json")
        self.root = os.path.join(self.tmp.name, "root")
        os.makedirs(os.path.join(self.root, "proc"))

    def tearDown(self):
        self.tmp.cleanup()

    def test_off_until_turned_on(self):
        g = G.Guide("gui", folder=GUIDE, state=self.state, root=self.root, env={})
        self.assertFalse(g.enabled)
        self.assertEqual(g.status(), "off")
        self.assertFalse(g.play("installer.welcome"))

    def test_the_hotkey_turns_it_on_when_off(self):
        g = G.Guide("gui", folder=GUIDE, state=self.state, root=self.root, env={})
        self.assertFalse(g.toggle())          # not quiet any more: on, unmuted
        g = G.Guide("console", folder=GUIDE, state=self.state, root=self.root, env={})
        self.assertTrue(g.enabled)
        self.assertFalse(g.muted)

    def test_the_boot_option_turns_it_on(self):
        with open(os.path.join(self.root, "proc", "cmdline"), "w") as f:
            f.write("quiet splash bromigos.voice=on\n")
        self.assertTrue(G.Guide("gui", folder=GUIDE, state=self.state, root=self.root, env={}).enabled)

    def test_mute_is_remembered(self):
        G.Guide("gui", folder=GUIDE, state=self.state, root=self.root, env={}).set_enabled(True)
        g = G.Guide("gui", folder=GUIDE, state=self.state, root=self.root, env={})
        self.assertFalse(g.muted)
        self.assertTrue(g.toggle())
        self.assertTrue(G.Guide("gui", folder=GUIDE, state=self.state, root=self.root, env={}).muted)
        with open(self.state) as f:
            self.assertEqual(json.load(f), {"enabled": True, "muted": True})
        g.toggle()
        self.assertFalse(G.Guide("console", folder=GUIDE, state=self.state, root=self.root, env={}).muted)

    def test_off_is_remembered(self):
        G.Guide("gui", folder=GUIDE, state=self.state, root=self.root, env={}).set_enabled(False)
        g = G.Guide("gui", folder=GUIDE, state=self.state, root=self.root, env={})
        self.assertFalse(g.enabled)
        self.assertEqual(g.status(), "off")

    def test_the_boot_option_turns_it_off(self):
        with open(os.path.join(self.root, "proc", "cmdline"), "w") as f:
            f.write("quiet splash bromigos.voice=off\n")
        self.assertFalse(G.Guide("gui", folder=GUIDE, state=self.state, root=self.root, env={}).enabled)

    def test_the_default_path(self):
        old = {k: os.environ.pop(k, None) for k in ("BROMIGOS_GUIDE_STATE", "XDG_STATE_HOME")}
        try:
            os.environ["XDG_STATE_HOME"] = "/x/state"
            self.assertEqual(G.state_path(), "/x/state/bromigos/voice-guide.json")
        finally:
            for k, v in old.items():
                os.environ.pop(k, None)
                if v is not None:
                    os.environ[k] = v


STANDIN = """#!/bin/sh
# a stand-in player: records how it was called, then plays for a while
printf '%s\\n' "${0##*/} $*" >> "{log}"
case "${0##*/}" in
  ffmpeg|opusdec) printf 'RIFF' ;;
  aplay) cat > "{log}.stdin" ;;
esac
exec sleep 30
"""


class Access(unittest.TestCase):
    """The installer's other choices (accessibility.json): what the welcome tours start with."""

    def test_all_off_until_chosen_and_kept(self):
        with tempfile.TemporaryDirectory() as t:
            path = os.path.join(t, "bromigos", "accessibility.json")
            self.assertEqual(G.access(path), G.ACCESS_DEFAULTS)
            G.save_access({"high_contrast": True, "large_text": 1, "nonsense": True}, path)
            got = G.access(path)
            self.assertTrue(got["high_contrast"] and got["large_text"])
            self.assertFalse(got["screen_reader"] or got["applied"])
            with open(path) as f:
                self.assertNotIn("nonsense", json.load(f))
            G.save_access({"applied": True}, path)
            self.assertTrue(G.access(path)["high_contrast"] and G.access(path)["applied"])

    def test_the_default_path(self):
        old = {k: os.environ.pop(k, None) for k in ("BROMIGOS_ACCESS_STATE", "XDG_STATE_HOME")}
        try:
            os.environ["XDG_STATE_HOME"] = "/x/state"
            self.assertEqual(G.access_path(), "/x/state/bromigos/accessibility.json")
            os.environ["BROMIGOS_ACCESS_STATE"] = "/y/a.json"
            self.assertEqual(G.access_path(), "/y/a.json")
        finally:
            for k, v in old.items():
                os.environ.pop(k, None)
                if v is not None:
                    os.environ[k] = v


class Player(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        t = self.tmp.name
        self.bin = os.path.join(t, "bin")
        self.run = os.path.join(t, "run")
        self.root = os.path.join(t, "root")
        self.log = os.path.join(t, "calls.log")
        for d in (self.bin, self.run, os.path.join(self.root, "proc", "asound")):
            os.makedirs(d)
        self.state = os.path.join(t, "voice-guide.json")
        self.env = {"PATH": self.bin, "XDG_RUNTIME_DIR": self.run}
        for real in ("sleep", "cat"):                 # the stand-ins' own tools; PATH has only them
            os.symlink(shutil.which(real), os.path.join(self.bin, real))
        self.guides = []

    def tearDown(self):
        for g in self.guides:
            g.stop()
        self.tmp.cleanup()

    def tool(self, *names):
        for n in names:
            p = os.path.join(self.bin, n)
            with open(p, "w") as f:
                f.write(STANDIN.replace("{log}", self.log))
            os.chmod(p, os.stat(p).st_mode | stat.S_IXUSR)

    def pipewire(self):
        open(os.path.join(self.run, "pipewire-0"), "w").close()

    def card(self):
        with open(os.path.join(self.root, "proc", "asound", "cards"), "w") as f:
            f.write(" 0 [PCH            ]: HDA-Intel - HDA Intel PCH\n                      HDA Intel PCH at 0xf7f10000\n")

    def guide(self, ui="gui", **kw):
        g = G.Guide(ui, folder=GUIDE, state=self.state, root=self.root, env=self.env, tty=kw.pop("tty", "/dev/tty1"), **kw)
        g.enabled = True                   # as after "How would you like to be guided?"
        self.guides.append(g)
        return g

    def calls(self, n=1, wait=5.0):
        t0 = time.monotonic()
        while time.monotonic() - t0 < wait:
            try:
                with open(self.log) as f:
                    got = f.read().splitlines()
                if len(got) >= n:
                    return got
            except OSError:
                pass
            time.sleep(0.02)
        return []

    def test_pipewire_when_a_session_runs(self):
        self.tool("pw-play", "aplay", "ffmpeg")
        self.pipewire()
        self.card()
        g = self.guide()
        self.assertEqual(G.output("gui", self.root, self.env)[0], "pw-play")
        self.assertTrue(g.play("installer.edition"))
        call = self.calls()[0]
        self.assertTrue(call.startswith("pw-play "), call)
        self.assertTrue(call.endswith(g.clip("installer.edition")), call)
        self.assertTrue(g.speaking())

    def test_alsa_with_a_decoder_without_pipewire(self):
        self.tool("pw-play", "aplay", "ffmpeg")
        self.card()
        self.assertEqual(G.output("console", self.root, self.env, tty="/dev/tty1"), ("aplay", "ffmpeg"))
        g = self.guide("console")
        self.assertTrue(g.play("installer.disk.alongside", who="Windows"))
        got = sorted(c.split()[0] for c in self.calls(2))
        self.assertEqual(got, ["aplay", "ffmpeg"])
        with open(self.log) as f:
            self.assertIn("installer.disk.alongside-who-windows-", f.read())

    def test_opusdec_when_theres_no_ffmpeg(self):
        self.tool("aplay", "opusdec")
        self.card()
        self.assertEqual(G.output("console", self.root, self.env, tty="/dev/tty1"), ("aplay", "opusdec"))

    def test_nothing_without_a_card_or_a_player(self):
        self.tool("aplay", "ffmpeg")
        self.assertIsNone(G.output("gui", self.root, self.env)[0])          # no card
        self.card()
        os.remove(os.path.join(self.bin, "ffmpeg"))
        self.assertIsNone(G.output("gui", self.root, self.env)[0])          # aplay can't read Opus
        self.tool("ffmpeg")
        os.remove(os.path.join(self.bin, "aplay"))
        self.assertIsNone(G.output("gui", self.root, self.env)[0])          # no player

    def test_no_sound_device_says_so_once_and_stays_silent(self):
        self.tool("aplay", "ffmpeg")              # tools, but no card
        said = []
        g = self.guide(notify=said.append)
        for _ in range(3):
            self.assertFalse(g.play("installer.edition"))
        self.assertEqual(len(said), 1)
        self.assertIn("No sound device", said[0])
        self.assertEqual(g.status(), "no-sound")
        self.assertEqual(g.notice, said[0])
        self.assertEqual(self.calls(wait=0.3), [])

    def test_a_serial_console_is_silent(self):
        self.tool("aplay", "ffmpeg")
        self.card()
        said = []
        g = self.guide("console", notify=said.append, tty="/dev/ttyS0")
        self.assertFalse(g.play("installer.edition"))
        self.assertEqual(len(said), 1)
        self.assertIn("serial console", said[0])

    def test_over_ssh_is_silent(self):
        self.tool("aplay", "ffmpeg")
        self.card()
        self.env["SSH_CONNECTION"] = "192.0.2.1 50000 192.0.2.2 22"
        said = []
        g = self.guide("console", notify=said.append, tty="/dev/pts/0")
        self.assertFalse(g.play("server-tour.network"))
        self.assertEqual(len(said), 1)
        self.assertIn("SSH", said[0])

    def _proc(self, pid, comm, argv=None):
        d = os.path.join(self.root, "proc", str(pid))
        os.makedirs(d)
        with open(os.path.join(d, "comm"), "w") as f:
            f.write(comm + "\n")
        with open(os.path.join(d, "cmdline"), "wb") as f:
            f.write(b"\0".join(a.encode() for a in (argv or [comm])) + b"\0")

    def test_quiet_while_orca_talks(self):
        self.tool("pw-play")
        self.pipewire()
        self._proc(4242, "python3", ["/usr/bin/python3", "/usr/bin/orca", "--replace"])
        g = self.guide()
        self.assertEqual(g.status(), "screen-reader")
        self.assertFalse(g.play("tour.phone"))
        self.assertEqual(self.calls(wait=0.3), [])
        self.assertIn("screen reader", g.describe())

    def test_quiet_while_the_console_talks(self):
        self.tool("aplay", "ffmpeg")
        self.card()
        self._proc(77, "espeakup")
        self.assertFalse(self.guide("console").play("server-tour.ssh"))
        self.assertEqual(G.screen_reader("gui", self.root), None)           # espeakup talks on the console only
        os.makedirs(os.path.join(self.root, "sys", "accessibility", "speakup"))
        with open(os.path.join(self.root, "sys", "accessibility", "speakup", "synth"), "w") as f:
            f.write("soft\n")
        self.assertEqual(G.screen_reader("console", os.path.join(self.root)), "speakup")
        self.assertEqual(self.calls(wait=0.3), [])

    def test_muted_is_silent_and_the_next_line_cuts_off_the_last(self):
        self.tool("pw-play")
        self.pipewire()
        g = self.guide()
        self.assertTrue(g.play("installer.welcome"))
        self.calls(1)
        first = list(g._procs)
        self.assertTrue(g.play("installer.edition"))
        self.assertTrue(all(p.poll() is not None for p in first))          # cut off
        self.calls(2)
        g.stop()
        self.assertFalse(g.speaking())
        self.assertTrue(g.play("installer.disk"))
        self.calls(3)
        g.toggle()                                                          # Ctrl+Alt+V
        self.assertFalse(g.speaking())
        self.assertFalse(g.play("installer.user"))
        time.sleep(0.2)
        self.assertEqual(len(self.calls(3)), 3)

    def test_a_sample_plays_while_off_but_never_over_a_screen_reader(self):
        """Play a sample: heard before the guide is turned on; still quiet while Orca talks."""
        self.tool("pw-play")
        self.pipewire()
        g = self.guide()
        g.enabled = False
        self.assertFalse(g.play("installer.guide"))
        self.assertTrue(g.play("installer.guide.sample", force=True))
        self.assertIn("installer.guide.sample-", self.calls(1)[0])
        g.stop()
        self._proc(4243, "orca")
        self.assertFalse(g.play("installer.guide.sample", force=True))

    def _voice_server(self, wav=None):
        """A stand-in for VECTOR's voice service: answers one tts request with a wav's path."""
        import socket
        import threading
        sock = os.path.join(self.run, "voice.sock")
        srv = socket.socket(socket.AF_UNIX)
        srv.bind(sock)
        srv.listen(2)
        self.env["BROMIGOS_VOICE_SOCK"] = sock
        got = []

        def serve():
            c, _ = srv.accept()
            buf = b""
            while not buf.endswith(b"\n"):
                buf += c.recv(4096)
            got.append(json.loads(buf))
            c.sendall((json.dumps({"wav": wav, "engine": "lab"} if wav else {"error": "no voice"}) + "\n").encode())
            c.close()
            srv.close()
        threading.Thread(target=serve, daemon=True).start()
        return got

    def test_any_words_through_his_running_voice(self):
        """An answer has no clip: his running voice service speaks it, and it plays like a clip."""
        self.tool("pw-play")
        self.pipewire()
        wav = os.path.join(self.run, "answer.wav")
        open(wav, "wb").close()
        asked = self._voice_server(wav)
        g = self.guide()
        self.assertTrue(g.live())
        self.assertTrue(g.say("Your lab runs my brain."))
        self.assertIn("answer.wav", self.calls(1)[0])
        self.assertEqual(asked[0], {"op": "tts", "text": "Your lab runs my brain.", "role": "main"})

    def test_no_voice_service_plays_the_clip_instead(self):
        self.tool("pw-play")
        self.pipewire()
        g = self.guide()
        self.assertFalse(g.live())
        self.assertTrue(g.say("I'm here now.", fallback="tour.hello"))
        self.assertIn("tour.hello-", self.calls(1)[0])
        self.assertFalse(g.say("Nothing to fall back on."))

    def test_a_failed_voice_service_falls_back_and_stop_wins(self):
        self.tool("pw-play")
        self.pipewire()
        self._voice_server(None)
        g = self.guide()
        self.assertTrue(g.say("Hello.", fallback="server-tour.hello"))
        self.assertIn("server-tour.hello-", self.calls(1)[0])
        g.muted = True
        self.assertFalse(g.say("Hello."))

    def test_a_line_without_a_clip_is_silent(self):
        self.tool("pw-play")
        self.pipewire()
        self.assertFalse(self.guide().play("installer.not-a-line"))


if __name__ == "__main__":
    unittest.main()
