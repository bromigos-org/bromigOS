"""Render the login banner with agetty using a disposable pseudo-terminal."""
import os
from pathlib import Path
import pty
import re
import shutil
import subprocess
import termios
import unittest


ISSUE = Path(__file__).resolve().parents[1] / '60-bromigos.issue'
COLOURS = re.compile(r'\\e\{(?:lightgreen|bold|reset)\}')
SGR = re.compile(rb'\x1b\[[0-9;]*m')


class IssueBanner(unittest.TestCase):
    def test_plain_text_fits_a_console_without_font_icons(self):
        text = ISSUE.read_text(encoding='ascii')
        plain = COLOURS.sub('', text)
        self.assertNotIn('\\', plain, 'Only approved colour escapes belong in the banner')
        self.assertTrue(all(char == '\n' or 32 <= ord(char) < 127 for char in plain))
        self.assertLessEqual(max(map(len, plain.splitlines())), 72)

    @unittest.skipUnless(shutil.which('agetty'), 'agetty is needed for the native render')
    def test_native_render_has_colours_and_resets_before_login(self):
        master, slave = pty.openpty()
        try:
            original = termios.tcgetattr(slave)
            result = subprocess.run(
                [shutil.which('agetty'), '--show-issue', '--issue-file', str(ISSUE)],
                stdin=slave, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                env={'PATH': '/usr/bin:/bin', 'LC_ALL': 'C', 'TERM': 'linux'},
                timeout=5, check=True,
            )
            self.assertEqual(termios.tcgetattr(slave), original)
        finally:
            os.close(master)
            os.close(slave)
        self.assertEqual(result.stderr, b'')
        self.assertIn(b'\x1b[', result.stdout)
        self.assertIn(b'\x1b[0m', result.stdout)
        self.assertEqual(SGR.findall(result.stdout)[-1], b'\x1b[0m')
        expected = COLOURS.sub('', ISSUE.read_text(encoding='ascii')).encode('ascii')
        self.assertEqual(SGR.sub(b'', result.stdout).replace(b'\r\n', b'\n'), expected)
        self.assertNotIn(b'\x1b', SGR.sub(b'', result.stdout))
        self.assertTrue(result.stdout.rstrip().endswith(b'Restart or shut down'))


if __name__ == '__main__':
    unittest.main()
