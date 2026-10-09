"""Readings only the worlds need, polled only while a world is up:

  agents   herdr's agents (the Swarm deck's data: `herdr api snapshot`, ~8 ms), every
           2 s; every 8 s while the layer is paused. Each: key, status (working,
           needs_you, finished; error counts as needs_you with a danger signal), cwd.
  sessions Claude Code sessions outside herdr (herdr already lists the ones in its panes):
           `claude` processes without HERDR_ENV, working while they burn CPU (a /proc scan,
           every 4 s). Counted in `working` with herdr's working agents.
  models   the homelab's local models generating: LiteLLM's model requests per minute and
           output tokens per second from Prometheus (two ~20 ms queries every 10 s; 30 s while
           paused), as 0..1, from bromigos-homelab. Without it the lab snapshot's rpmNow stands in (World).
  vector   VECTOR's state from $XDG_RUNTIME_DIR/bromigos-vector.json (written by his
           daemon on every change): off (no file / stale daemon), idle, thinking,
           speaking, listening, error. A stat every 0.5 s; read only when it changed.
"""
import json
import os
import threading
import time

TICK = os.sysconf("SC_CLK_TCK") if hasattr(os, "sysconf") else 100

from . import sources

RUNTIME = os.environ.get("XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}")
VECTOR_FILE = os.path.join(RUNTIME, "bromigos-vector.json")


def agent_status(a):
    """herdr's agent_status as a world state (same reading as the Swarm deck's status_of)."""
    s = (a.get("agent_status") or "").lower()
    if s in ("working", "busy", "running"):
        return "working", False
    if s in ("blocked", "waiting", "needs_input", "permission", "attention"):
        return "needs_you", False
    if s in ("error", "failed", "crashed", "exited"):
        return "needs_you", True
    return "finished", False


class Feed:
    def __init__(self, data):
        self.data = data            # live.data.Data: its .paused slows the polls
        self.agents = []
        self.agents_ok = False
        self.vector = "off"
        self.stop = threading.Event()
        self._vsig = None
        self.first_seen = {}        # agent key -> when first seen: a stable order (the first few are the foreground)
        self.outside = 0            # Claude Code sessions outside herdr that are working
        self._cpu = {}              # pid -> (cpu ticks, when) for those sessions
        self._scan_t = 0.0
        self.models = None          # 0..1, None until Prometheus answered (World falls back to rpmNow)
        self.models_rpm = 0.0
        self.models_tps = 0.0

    def start(self):
        threading.Thread(target=self._herdr_loop, daemon=True, name="world-herdr").start()
        threading.Thread(target=self._vector_loop, daemon=True, name="world-vector").start()
        threading.Thread(target=self._models_loop, daemon=True, name="world-models").start()

    @property
    def working(self):
        """Agents at work right now: herdr's working agents plus busy Claude Code sessions outside it."""
        return sum(1 for a in self.agents if a["status"] == "working") + self.outside

    def halt(self):
        self.stop.set()

    def _herdr_loop(self):
        while not self.stop.is_set():
            try:
                raw = sources.herdr()
                out = []
                for a in raw:
                    st, err = agent_status(a)
                    key = a.get("terminal_id") or a.get("pane_id") or json.dumps(a.get("agent_session"))
                    out.append({"key": str(key), "status": st, "error": err, "cwd": a.get("cwd") or "",
                                "name": a.get("agent") or a.get("name") or ""})
                now = time.time()
                for a in out:
                    self.first_seen.setdefault(a["key"], now)
                live = {a["key"] for a in out}
                self.first_seen = {k: v for k, v in self.first_seen.items() if k in live}
                out.sort(key=lambda a: (self.first_seen[a["key"]], a["key"]))
                self.agents = out
                self.agents_ok = True
            except Exception:
                self.agents_ok = False
            if time.time() - self._scan_t >= 4.0:
                try:
                    self._scan_sessions()
                except Exception:
                    self.outside = 0
            self.stop.wait(8.0 if getattr(self.data, "paused", False) else 2.0)

    def _scan_sessions(self):
        """Claude Code sessions not in a herdr pane, working when they used over 3% of a core
        since the last scan (an idle session sits near 0)."""
        now = time.time()
        self._scan_t = now
        seen, busy = {}, 0
        for pid in os.listdir("/proc"):
            if not pid.isdigit():
                continue
            try:
                with open(f"/proc/{pid}/comm") as f:
                    if f.read().strip() != "claude":
                        continue
                with open(f"/proc/{pid}/environ", "rb") as f:
                    if b"HERDR_ENV=1\0" in f.read():
                        continue                    # herdr lists it already
                with open(f"/proc/{pid}/stat") as f:
                    st = f.read().rsplit(")", 1)[1].split()
                ticks = int(st[11]) + int(st[12])  # utime + stime
            except (OSError, ValueError, IndexError):
                continue
            seen[pid] = (ticks, now)
            prev = self._cpu.get(pid)
            if prev and now > prev[1] and (ticks - prev[0]) / TICK / (now - prev[1]) > 0.03:
                busy += 1
        self._cpu = seen
        self.outside = busy

    def _models_loop(self):
        """The homelab's local models generating, through bromigos-homelab (its [models]
        rates); None without it, and the World falls back to the snapshot's rpmNow."""
        from .homelab import H
        while not self.stop.is_set():
            try:
                lv = H.models_level() if H else None
                if lv is None:
                    self.models = None
                else:
                    self.models, self.models_rpm, self.models_tps = lv
            except Exception:
                self.models = None
            self.stop.wait(30.0 if getattr(self.data, "paused", False) or not H else 10.0)

    def _vector_loop(self):
        while not self.stop.is_set():
            try:
                st = os.stat(VECTOR_FILE)
                sig = (st.st_mtime_ns, st.st_size)
                if sig != self._vsig:
                    self._vsig = sig
                    with open(VECTOR_FILE) as f:
                        self.vector = str(json.load(f).get("state") or "idle")
            except (OSError, ValueError):
                self._vsig = None
                self.vector = "off"
            self.stop.wait(2.0 if getattr(self.data, "paused", False) else 0.5)
