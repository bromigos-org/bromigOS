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
