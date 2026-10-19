"""Persistent shell recovery, using fake display sockets and a temporary HOME."""
import os
from pathlib import Path
import pty
import select
import shlex
import signal
import socket
import subprocess
import tempfile
import time
import unittest

ROOT = Path(__file__).resolve().parents[2]
ZSH = ROOT / 'desktop/zsh/bromigos.zsh'


class ShellSession(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.home = Path(self.tmp.name)
        self.bin = self.home / 'bin'
        self.bin.mkdir()
        self.runtime = self.home / 'runtime'
        self.runtime.mkdir()
        self.env = dict(HOME=str(self.home), ZDOTDIR=str(self.home),
                        XDG_CONFIG_HOME=str(self.home / 'config'),
                        XDG_STATE_HOME=str(self.home / 'state'),
                        XDG_CACHE_HOME=str(self.home / 'cache'),
                        XDG_RUNTIME_DIR=str(self.runtime), HERDR_ENV='1',
                        TERM='xterm-256color', BROMIGOS_BANNER='off',
                        PATH=str(self.bin) + ':/usr/bin:/bin')
        helper = self.bin / 'bromigos'
        helper.write_text('''#!/bin/sh
test "$*" = 'session shell-env' || exit 2
echo called >> "$HOME/calls"
cat "$HOME/answer"
''')
        helper.chmod(0o755)
        (self.home / 'answer').write_text(
            'WAYLAND_DISPLAY=wayland-new\nHYPRLAND_INSTANCE_SIGNATURE=new\nDISPLAY=:7\nXAUTHORITY=\n')

    def shell(self, body='', interactive=True):
        code = 'source "$1"; ' + body + '''
print -r -- "RESULT:${WAYLAND_DISPLAY-unset}|${DISPLAY-unset}|${XAUTHORITY-unset}"
print -r -- "HOOKS:${(j:,:)preexec_functions}"
'''
        result = subprocess.run(['zsh', '-f', '-i' if interactive else '-c',
                                 *(['-c'] if interactive else []), code, 'zsh', str(ZSH)],
                                env=self.env, capture_output=True, text=True, cwd=self.home,
                                timeout=5)
        self.assertEqual(result.returncode, 0, result.stderr)
        return result.stdout

    def test_startup_repairs_display_and_clears_old_auth(self):
        self.env['XAUTHORITY'] = '/gone/auth'
        self.assertIn('RESULT:wayland-new|:7|unset', self.shell())

    def test_existing_pane_recovers_before_next_command(self):
        (self.home / 'answer').write_text('')
        code = '''
print -r -- 'WAYLAND_DISPLAY=wayland-later\nDISPLAY=:8' > "$HOME/answer"
for hook in $preexec_functions; do "$hook"; done
'''
        self.assertIn('RESULT:wayland-later|:8|unset', self.shell(code))

    def test_valid_nested_socket_and_explicit_x_display_are_preserved(self):
        server = socket.socket(socket.AF_UNIX)
        self.addCleanup(server.close)
        server.bind(str(self.runtime / 'nested'))
        self.env['WAYLAND_DISPLAY'] = 'nested'
        self.assertIn('RESULT:nested|unset|unset', self.shell())
        self.assertFalse((self.home / 'calls').exists())
        self.env.pop('WAYLAND_DISPLAY')
        self.env['DISPLAY'] = ':42'
        self.assertIn('RESULT:unset|:42|unset', self.shell())
        self.assertFalse((self.home / 'calls').exists())

    def test_ssh_console_disabled_and_noninteractive_shells_do_not_discover(self):
        baseline = dict(self.env)
        for change in [{'SSH_CONNECTION': 'remote'}, {'SSH_CLIENT': 'remote'},
                       {'SSH_TTY': '/dev/pts/8'}, {'TERM': 'linux'}, {'TERM': 'dumb'},
                       {'BROMIGOS_SESSION_REFRESH': 'off'}, {'HERDR_ENV': ''}]:
            with self.subTest(change=change):
                self.env = dict(baseline, **change)
                self.shell()
                self.assertFalse((self.home / 'calls').exists())
        self.env = baseline
        self.shell(interactive=False)
        self.assertFalse((self.home / 'calls').exists())

    def test_values_are_not_evaluated_and_other_keys_are_ignored(self):
        (self.home / 'answer').write_text('WAYLAND_DISPLAY=$(touch forbidden)\nHOME=/wrong\n')
        self.assertIn('RESULT:$(touch forbidden)|unset|unset', self.shell())
        self.assertFalse((self.home / 'forbidden').exists())

    def test_reload_keeps_one_hook_and_missing_core_is_quiet(self):
        (self.bin / 'bromigos').write_text('#!/bin/sh\nexit 2\n')
        result = self.shell('source "$1"; ')
        self.assertIn('RESULT:unset|unset|unset', result)
        self.assertEqual(result.count('_bromigos_session_refresh'), 1)

    def test_real_preexec_hook_preserves_command_status_and_recovers_before_launch(self):
        pid, fd = pty.fork()
        if pid == 0:
            os.execve('/usr/bin/zsh', ['zsh', '-f', '-i'], self.env)

        pending = b''

        def until(marker):
            nonlocal pending
            deadline = time.monotonic() + 5
            while marker not in pending and time.monotonic() < deadline:
                if select.select([fd], [], [], .1)[0]:
                    pending += os.read(fd, 65536)
            self.assertIn(marker, pending)
            output, pending = pending.split(marker, 1)
            return output + marker

        try:
            os.write(fd, (f'source {shlex.quote(str(ZSH))}; PS1="READY> "; RPROMPT=""\n').encode())
            until(b'READY> ')
            # Wait for a unique command marker so terminal echo cannot be mistaken
            # for the first real prompt.
            os.write(fd, b'print READY$((10+7))\n')
            until(b'READY17')
            until(b'READY> ')
            os.write(fd, b'false\n')
            until(b'READY> ')
            os.write(fd, b'print -r -- STATUS:$?\n')
            result = until(b'READY> ')
            self.assertIn(b'STATUS:1', result)
            (self.home / 'answer').write_text('WAYLAND_DISPLAY=wayland-reconnected\nDISPLAY=:9\n')
            os.write(fd, b'/bin/sh -c \'printf "CHILD:%s\\n" "$WAYLAND_DISPLAY/$DISPLAY"\'\n')
            self.assertIn(b'CHILD:wayland-reconnected/:9', until(b'READY> '))
        finally:
            os.kill(pid, signal.SIGTERM)
            os.close(fd)
            os.waitpid(pid, 0)
