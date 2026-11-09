"""The text installer on a console (bromigos-iso-text-install@.service, bromigos-iso-text-console):
it has the console for its screen, and when it stops with an error a person sees why and what to do.

0.1.4 and 0.1.5: the unit sent standard error to the journal, and Textual draws its whole screen on
standard error, so "Install bromigOS with the text installer" (and the Server entry, a machine
with no graphics, a serial console) gave a black screen with a blinking cursor while the installer
ran unseen. A crash would have been cleared off the screen by the restart a second later.
iso/test.sh menu text is the same on a real medium's console.
"""
import contextlib
import io
import os
import pty
import select
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.realpath(__file__))
ROOT = os.path.join(HERE, "../../profile/airootfs")
UNIT = os.path.join(ROOT, "etc/systemd/system/bromigos-iso-text-install@.service")
CONSOLE = os.path.join(ROOT, "usr/local/bin/bromigos-iso-text-console")


def read(path):
    with open(path) as f:
        return f.read()


def unit_settings():
    out = {}
    for line in read(UNIT).splitlines():
        line = line.strip()
        if line and not line.startswith(("#", "[")) and "=" in line:
            k, v = line.split("=", 1)
            out[k] = v
    return out


class TheUnit(unittest.TestCase):
    def test_the_installer_has_the_console_for_all_three_streams(self):
        s = unit_settings()
        self.assertEqual(s.get("StandardInput"), "tty")
        self.assertEqual(s.get("StandardOutput"), "tty")
        # Textual's screen is written to standard error: anywhere but the console is a black screen
        self.assertIn(s.get("StandardError", "inherit"), ("tty", "inherit"))

    def test_it_runs_the_console_script(self):
        self.assertEqual(unit_settings().get("ExecStart"), "/usr/local/bin/bromigos-iso-text-console %I")


class Console:
    """bromigos-iso-text-console on a pseudo-terminal, with a stand-in installer (and stand-ins for
    logger, systemctl, setfont and stty: nothing of the machine running the test is touched)."""

    def __init__(self, installer, shell="exit 0"):
        self.tmp = tempfile.TemporaryDirectory(prefix="bromigos-text-console-")
        d = self.tmp.name
        for name, body in (("installer", installer), ("shell", f"echo IN-THE-SHELL\n{shell}"), ("logger", 'echo "$*" >> "$LOGGED"'),
                           ("systemctl", 'echo "systemctl $*" >> "$LOGGED"'), ("setfont", "exit 0"), ("stty", "exit 0")):
            path = os.path.join(d, name)
            with open(path, "w") as f:
                f.write("#!/bin/sh\n" + body + "\n")
            os.chmod(path, 0o755)
        self.logged = os.path.join(d, "logged")
        self.master, slave = pty.openpty()
        env = {"PATH": d + ":/usr/bin:/bin", "BROMIGOS_ISO_INSTALL": os.path.join(d, "installer"),
               "SHELL": os.path.join(d, "shell"), "LOGGED": self.logged, "TERM": "linux"}
        # a serial console's name: no console font is set (the stand-in setfont is there all the same)
        self.proc = subprocess.Popen(["bash", CONSOLE, "ttyS9"], stdin=slave, stdout=slave, stderr=slave, env=env,
                                     start_new_session=True)
        os.close(slave)
        self.seen = ""

    def until(self, words, seconds=10):
        """Reads the screen until `words` shows after what was already read; what came before it."""
        start = len(self.seen)
        end = time.time() + seconds
        while words not in self.seen[start:] and time.time() < end:
            r, _, _ = select.select([self.master], [], [], 0.2)
            if r:
                try:
                    self.seen += os.read(self.master, 4096).decode(errors="replace")
                except OSError:
                    break
        return words in self.seen[start:]

    def press(self, key):
        os.write(self.master, key.encode())

    def close(self):
        with contextlib.suppress(ProcessLookupError):       # it and what it started (a sleep after R)
            os.killpg(self.proc.pid, signal.SIGKILL)
        self.proc.wait()
        os.close(self.master)
        self.tmp.cleanup()


class WhenItStops(unittest.TestCase):
    def console(self, installer, **k):
        c = Console(installer, **k)
        self.addCleanup(c.close)
        return c

    def test_an_error_stays_on_the_screen_with_what_to_do(self):
        c = self.console('echo "Traceback: the disk probe fell over" >&2\nexit 3')
        self.assertTrue(c.until("turn the computer off"), c.seen)
        self.assertIn("Traceback: the disk probe fell over", c.seen)          # its own words, still there
        self.assertIn("The installer stopped with an error (exit code 3)", c.seen)
        for way in ("start the installer again", "a shell", "restart the computer"):
            self.assertIn(way, c.seen)
        time.sleep(0.5)
        self.assertIsNone(c.proc.poll(), "it waits for a key: exiting lets the unit clear the screen and start over")
        self.assertIn("stopped on ttyS9 with exit code 3", read(c.logged))    # and the journal has a line

    def test_enter_starts_it_again(self):
        c = self.console("exit 1")
        self.assertTrue(c.until("turn the computer off"), c.seen)
        c.press("\n")
        self.assertEqual(c.proc.wait(10), 0)        # the unit (Restart=always) starts the installer afresh

    def test_s_is_a_shell_and_exit_comes_back(self):
        c = self.console("exit 1")
        self.assertTrue(c.until("turn the computer off"), c.seen)
        c.press("s")
        self.assertTrue(c.until("IN-THE-SHELL"), c.seen)
        self.assertTrue(c.until("turn the computer off"), c.seen)     # the choices again
        self.assertIsNone(c.proc.poll())

    def test_r_restarts_the_computer(self):
        c = self.console("exit 1")
        self.assertTrue(c.until("turn the computer off"), c.seen)
        c.press("r")
        for _ in range(50):
            if os.path.exists(c.logged) and "systemctl reboot" in read(c.logged):
                break
            time.sleep(0.1)
        self.assertIn("systemctl reboot", read(c.logged))      # the stand-in systemctl: asked, not done

    def test_a_clean_end_says_nothing(self):
        c = self.console("echo the installer was here\nexit 0")
        self.assertEqual(c.proc.wait(10), 0)
        c.until("never", 0.5)
        self.assertIn("the installer was here", c.seen)
        self.assertNotIn("stopped with an error", c.seen)


LIB = os.path.join(ROOT, "usr/local/lib/bromigos-iso")


class ACrashHasAnExitCode(unittest.TestCase):
    """Textual shows a crash and returns from run(): main() hands its code on, so the console
    script knows the installer didn't end by itself."""

    @classmethod
    def setUpClass(cls):
        # loaded here, not with this file: test_tui.py sets the fake back end's environment before it
        # loads the installer, and whichever loads it first decides what the others get
        os.environ.setdefault("BROMIGOS_INSTALLER_FAKE", "1")
        for d in (os.path.join(HERE, "../../../lib"), LIB):
            if d not in sys.path:
                sys.path.insert(0, d)
        try:
            from textual.app import App
            from bromigos_installer import tui
        except ImportError:
            raise unittest.SkipTest("python-textual isn't installed")
        cls.App, cls.tui = App, tui

    def run_main(self, on_mount):
        tui = self.tui

        class StandIn(self.App):
            def run(self, **k):
                return super().run(headless=True, **k)

        StandIn.on_mount = on_mount
        with mock.patch.object(tui, "Installer", StandIn), mock.patch.object(tui, "BT", None), \
                mock.patch.dict(os.environ, {"TERM": "xterm"}), mock.patch.object(tui, "_read", lambda p: ""), \
                contextlib.redirect_stderr(io.StringIO()), contextlib.redirect_stdout(io.StringIO()):
            return tui.main(["--fake", "--text"])

    def test_a_crash_is_not_zero(self):
        def boom(self):
            raise RuntimeError("a test crash")
        self.assertNotEqual(self.run_main(boom), 0)

    def test_leaving_is_zero(self):
        self.assertEqual(self.run_main(lambda self: self.exit()), 0)


if __name__ == "__main__":
    unittest.main()
