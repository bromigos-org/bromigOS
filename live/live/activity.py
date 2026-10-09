"""The user's activity, for the worlds' keeper and creatures: working, dozing, asleep.

  working  input in the last `idle_after` seconds (default 90)
  dozing   no input for longer than that
  asleep   the session is locked (App.on_lock sets it from the lock watch)

Input is measured cheaply, three ways, the first that is available winning:
  1. hypridle: the idle policy's listener (docs/idle.md) runs `bromigos-live ctl activity idle`
     after the idle timeout and `... activity active` on resume (the compositor's own
     idle-notify, so typing counts). Once it has spoken this session it is trusted alone.
  2. Hyprland: the pointer position (one IPC request every 0.5 s) and Hyprland's own
     events (focus, title, workspace changes; App.on_hypr calls touch()).
  3. Nothing: always working.

The pointer is also the worlds' camera: `cursor()` gives it in -1..1 across the
monitor, for the layers' parallax.
"""
import threading
import time

from . import hypr

_inst = None


def get():
    global _inst
    if _inst is None:
        _inst = Activity()
    return _inst


class Activity:
    def __init__(self):
        self.last_input = time.monotonic()
        self.locked = False
        self.idle_after = 90.0
        self.hypridle = None        # None = never heard from; True idle; False active
        self.cur = (0.0, 0.0)
        self.cur_raw = None
        self.monitor = None         # (x, y, w, h) of the layer's monitor, logical px
        self.forced = None          # offscreen and tests: "working" | "dozing" | "asleep"
        self.running = False
        self.stop = threading.Event()
        self.lock = threading.Lock()

    # ---- inputs
    def touch(self):
        self.last_input = time.monotonic()

    def set_locked(self, on):
        self.locked = bool(on)
        if not on:
            self.touch()

    def hypridle_says(self, what):
        """`activity idle|active` from the hypridle listener."""
        if what == "idle":
            self.hypridle = True
        else:
            self.hypridle = False
            self.touch()
        return self.state()

    # ---- the pointer poller (only while a world is up)
    def start(self, monitor_name):
        self.monitor_name = monitor_name
        if self.running:
            return
        self.running = True
        self.stop.clear()
        threading.Thread(target=self._loop, daemon=True, name="activity").start()

    def halt(self):
        self.running = False
        self.stop.set()

    def _loop(self):
        n = 0
        while not self.stop.is_set():
            if n % 20 == 0 or self.monitor is None:
                mons = hypr.request("monitors") or []
                m = next((m for m in mons if m.get("name") == self.monitor_name), None) or (mons[0] if mons else None)
                if m:
                    sc = float(m.get("scale") or 1.0)
                    self.monitor = (m.get("x", 0), m.get("y", 0), m.get("width", 2560) / sc, m.get("height", 1440) / sc)
            n += 1
            p = None if self.locked else hypr.request("cursorpos")
            if isinstance(p, dict) and "x" in p:
                raw = (p["x"], p["y"])
                if raw != self.cur_raw:
                    if self.cur_raw is not None:
                        self.touch()
                    self.cur_raw = raw
                    if self.monitor:
                        x, y, w, h = self.monitor
                        self.cur = (max(-1.0, min(1.0, (raw[0] - x) / max(w, 1) * 2 - 1)),
                                    max(-1.0, min(1.0, (raw[1] - y) / max(h, 1) * 2 - 1)))
            self.stop.wait(0.5)

    # ---- outputs
    def state(self):
        if self.forced:
            return self.forced
        if self.locked:
            return "asleep"
        if self.hypridle is not None:
            return "dozing" if self.hypridle else "working"
        return "dozing" if time.monotonic() - self.last_input > self.idle_after else "working"

    def level(self):
        """1 working, 0.4 dozing, 0 asleep."""
        return {"working": 1.0, "dozing": 0.4, "asleep": 0.0}[self.state()]

    def cursor(self):
        return self.cur if self.state() == "working" else (0.0, 0.0)
