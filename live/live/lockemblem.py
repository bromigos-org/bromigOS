"""The turning burn-in on the lock screen. DISABLED, DO NOT RE-ENABLE (config [events] lock_emblem).

2026-10-07: this crashed hyprlock 0.9.6 and locked the operator out. hyprlock's SIGUSR2
handler allocates memory; a signal that lands while hyprlock is inside malloc corrupts the
heap and it aborts (coredump: operator new inside the handler, interrupting
pthread_mutex_lock). Any rate of SIGUSR2 is unsafe, so signal-driven animation of hyprlock
is retired. The notes below describe the old mechanism.

hyprlock can't animate an image, so the frames are pre-rendered (tools/lock-emblem.py,
one slow turn) and flipped from here while the session is locked: each tick writes the
next frame's path to `current` and sends hyprlock SIGUSR2. hyprlock.conf's emblem image
has reload_time = 0 (reload only on SIGUSR2) and reload_cmd = cat of that file, so it
loads the new frame and keeps showing the last one until it's ready (no flicker).

hyprlock draws everything itself; nothing here can draw over or weaken the lock.
SIGUSR1 UNLOCKS hyprlock: only ever send SIGUSR2.
"""
import os
import signal
import subprocess
import time

from gi.repository import GLib

DIR = os.path.expanduser("~/.cache/bromigos/lock-emblem")
CURRENT = os.path.join(DIR, "current")
TOOL = os.path.join(os.path.dirname(os.path.dirname(os.path.realpath(__file__))), "tools", "lock-emblem.py")
PY = os.path.expanduser("~/.local/share/bromigos/venv-brain/bin/python")


def _log(*a):
    print(time.strftime("%H:%M:%S"), "lock-emblem:", *a, flush=True)


class LockEmblem:
    def __init__(self):
        self.frames, self.fps = [], 24
        self.pid = None
        self.timer = None
        self.rendering = None
        self.load()

    def load(self):
        try:
            with open(os.path.join(DIR, "loop.txt")) as f:
                meta = dict(line.strip().split("=", 1) for line in f if "=" in line)
            self.fps = max(1, int(meta.get("fps", 12)))
            n = int(meta.get("frames", 0))
            ext = meta.get("ext", "png")
            frames = [os.path.join(DIR, f"f{i:04d}.{ext}") for i in range(n)]
            self.frames = frames if frames and all(os.path.exists(p) for p in (frames[0], frames[-1])) else []
        except (OSError, ValueError):
            self.frames = []
        if self.frames:
            if not os.path.exists(CURRENT):
                self._point(self.frames[0])
        else:
            self.render()
        return bool(self.frames)

    def render(self):
        """Frames missing (first run, cache cleared): render them in the background, once."""
        if self.rendering and self.rendering.poll() is None:
            return
        py = PY if os.path.exists(PY) else "python3"
        try:
            self.rendering = subprocess.Popen(["nice", "-n", "19", py, TOOL, DIR], stdin=subprocess.DEVNULL,
                                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            _log("rendering the loop")
        except OSError as e:
            _log("can't render:", e)

    def _point(self, path):
        tmp = CURRENT + ".tmp"
        with open(tmp, "w") as f:
            f.write(path + "\n")
        os.replace(tmp, CURRENT)

    def start(self, pid):
        if self.timer or not pid:
            return
        if not self.frames and not self.load():
            return
        self.pid = pid
        self.timer = GLib.timeout_add(max(20, int(1000 / self.fps)), self._tick)

    def stop(self):
        if self.timer:
            GLib.source_remove(self.timer)
        self.timer, self.pid = None, None

    def _tick(self):
        if not self.pid or not os.path.exists(f"/proc/{self.pid}"):
            self.timer = None
            return False
        i = int(time.monotonic() * self.fps) % len(self.frames)   # wall-clock phase: no drift, no stutter
        try:
            self._point(self.frames[i])
            os.kill(self.pid, signal.SIGUSR2)                      # reload images. NEVER SIGUSR1 (that unlocks)
        except ProcessLookupError:
            self.timer = None
            return False
        except OSError as e:
            _log("tick failed:", e)
        return True
