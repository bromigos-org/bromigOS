"""Update's theme wallpaper hook in a sandbox session; no real desktop commands."""
import os
from pathlib import Path
import shutil
import socket
import subprocess
import tempfile
import threading
import unittest

ROOT = Path(__file__).resolve().parents[2]

class Wallpaper(unittest.TestCase):
    def test_theme_apply_hands_the_background_to_live(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            runtime = home / 'run'; runtime.mkdir()
            bins = home / 'bin'; bins.mkdir()
            wp = home / '.config/wallpaper'; wp.mkdir(parents=True)
            for name in ('bromigos-den-empty-2560x1440.jpg', 'bromigos-lock-empty-2560x1440.jpg'):
                (wp / name).write_bytes(b'fixture')
            calls = home / 'calls'
            for name, body in [('hyprctl', 'exit 0'), ('swaybg', f'echo swaybg >> "{calls}"'),
                               ('hyprpaper', 'exit 0')]:
                p = bins / name; p.write_text('#!/bin/sh\n' + body + '\n'); p.chmod(0o755)
            (bins/'bromigos-wallpaper').symlink_to(ROOT/'desktop/bin/bromigos-wallpaper')
            env = dict(os.environ, HOME=tmp, XDG_CONFIG_HOME=str(home/'.config'),
                       XDG_STATE_HOME=str(home/'state'), XDG_RUNTIME_DIR=str(runtime),
                       WAYLAND_DISPLAY='wayland-test', PATH=f'{bins}:/usr/bin',
                       BROMIGOS_SHARE_DIR=str(home/'share'))
            env.pop('HYPRLAND_INSTANCE_SIGNATURE', None)
            srv = socket.socket(socket.AF_UNIX)
            srv.bind(str(runtime/'bromigos-live.sock')); srv.listen(); srv.settimeout(.1)
            stop = threading.Event()
            def live():
                while not stop.is_set():
                    try: c, _ = srv.accept()
                    except socket.timeout: continue
                    with c:
                        self.assertEqual(c.recv(128), b'background-active')
                        c.sendall(b'on')
            thread = threading.Thread(target=live); thread.start()
            # A static fallback left over from session startup, confined to this runtime.
            proc = subprocess.Popen(['/usr/bin/python3', '-c',
                'import ctypes,time; ctypes.CDLL(None).prctl(15,b"swaybg",0,0,0); time.sleep(60)'], env=env)
            try:
                import time
                time.sleep(.1)
                result = subprocess.run([str(ROOT/'desktop/hooks/theme-set.d/wallpaper')], env=env,
                                        capture_output=True, text=True, timeout=10)
                self.assertEqual(result.returncode, 0, result.stderr)
                proc.wait(timeout=3)
                self.assertFalse(calls.exists(), 'theme apply started swaybg above live')
                stop.set(); thread.join(); srv.close()
                # No live socket: the same update step must provide a still fallback.
                result = subprocess.run([str(ROOT/'desktop/hooks/theme-set.d/wallpaper')], env=env,
                                        capture_output=True, text=True, timeout=10)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(calls.read_text().strip(), 'swaybg')
            finally:
                if proc.poll() is None: proc.terminate(); proc.wait()
                stop.set(); thread.join(); srv.close()


class SavedChoice(unittest.TestCase):
    """The saved den variant is the user's: apply (login, every theme switch, every update)
    never replaces it, even with a user's own art in ~/.config/wallpaper and many applies at
    once (an update's theme step, the live layer's restart and its daemon all apply)."""

    def sandbox(self, tmp, own_art=True):
        home = Path(tmp)
        (home / 'run').mkdir()
        bins = home / 'bin'; bins.mkdir()
        share = home / 'share/wallpaper'; share.mkdir(parents=True)
        for name in ('bromigos-den-empty-2560x1440.jpg', 'bromigos-lock-empty-2560x1440.jpg'):
            (share / name).write_bytes(b'shipped')
        if own_art:     # a user's own art: den, masked (never picked by itself)
            wp = home / '.config/wallpaper'; wp.mkdir(parents=True)
            for name in ('bromigos-den-operator-2560x1440.jpg', 'bromigos-lock-operator-2560x1440.jpg',
                         'bromigos-den-masked-2560x1440.jpg'):
                (wp / name).write_bytes(b'own')
        for name in ('hyprctl', 'swaybg', 'hyprpaper', 'notify-send'):
            p = bins / name; p.write_text('#!/bin/sh\nexit 0\n'); p.chmod(0o755)
        env = dict(os.environ, HOME=tmp, XDG_CONFIG_HOME=str(home / '.config'),
                   XDG_STATE_HOME=str(home / 'state'), XDG_RUNTIME_DIR=str(home / 'run'),
                   WAYLAND_DISPLAY='wayland-test', PATH=f'{bins}:/usr/bin', BROMIGOS_SHARE_DIR=str(home / 'share'))
        env.pop('HYPRLAND_INSTANCE_SIGNATURE', None)
        state = home / 'state/bromigos/wallpaper'
        return env, state, share

    def wp(self, env, *args):
        return subprocess.run([str(ROOT / 'desktop/bin/bromigos-wallpaper'), *args], env=env,
                              capture_output=True, text=True, timeout=30)

    def test_nothing_saved_is_the_shipped_den_never_own_art(self):
        with tempfile.TemporaryDirectory() as tmp:
            env, state, share = self.sandbox(tmp)
            r = self.wp(env, 'apply')
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertEqual(os.readlink(state / 'den.jpg'), str(share / 'bromigos-den-empty-2560x1440.jpg'))
            self.assertEqual(self.wp(env, 'status').stdout.split()[1], 'empty')
            self.assertFalse((state / 'variant').exists(), 'apply wrote a choice nobody made')

    def test_concurrent_applies_keep_the_saved_choice(self):
        with tempfile.TemporaryDirectory() as tmp:
            env, state, share = self.sandbox(tmp)
            self.assertEqual(self.wp(env, 'empty').returncode, 0)
            self.assertEqual((state / 'variant').read_text().strip(), 'empty')
            for _ in range(3):
                procs = [subprocess.Popen([str(ROOT / 'desktop/bin/bromigos-wallpaper'), 'apply'], env=env,
                                          stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL) for _ in range(12)]
                for p in procs:
                    self.assertEqual(p.wait(timeout=60), 0)
                self.assertEqual((state / 'variant').read_text().strip(), 'empty')
                self.assertEqual(os.readlink(state / 'den.jpg'), str(share / 'bromigos-den-empty-2560x1440.jpg'))

    def test_a_chosen_variant_without_its_art_is_kept(self):
        with tempfile.TemporaryDirectory() as tmp:
            env, state, share = self.sandbox(tmp, own_art=False)
            state.mkdir(parents=True)
            (state / 'variant').write_text('den\n')
            r = self.wp(env, 'apply')
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertEqual(os.readlink(state / 'den.jpg'), str(share / 'bromigos-den-empty-2560x1440.jpg'))
            self.assertEqual((state / 'variant').read_text().strip(), 'den', 'the choice was replaced')

    def test_choosing_own_art_is_kept_by_apply(self):
        with tempfile.TemporaryDirectory() as tmp:
            env, state, _share = self.sandbox(tmp)
            self.assertEqual(self.wp(env, 'masked').returncode, 0)
            self.assertEqual(self.wp(env, 'apply').returncode, 0)
            self.assertEqual((state / 'variant').read_text().strip(), 'masked')
            self.assertTrue(os.readlink(state / 'den.jpg').endswith('bromigos-den-masked-2560x1440.jpg'))


if __name__ == '__main__':
    unittest.main()
