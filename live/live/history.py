"""A cheap local history for the timeline scrubber: one row a minute for 72 h
(a 4320-row ring of float32, ~300 KB), plus an events log. Persisted to
~/.local/state/bromigos-live/ (atomic writes every 5 min and on exit).

Rows hold minute averages where it matters (CPU, network) and the latest
reading otherwise. Lab fields come from the lab snapshot (bromigos-homelab); the timeline
also backfills the lab's own 24 h series from that endpoint, so the lab lanes
show a day of real history from the first open."""
import json
import os
import threading
import time

import numpy as np

STATE = os.path.join(os.environ.get("XDG_STATE_HOME", os.path.expanduser("~/.local/state")), "bromigos-live")
HIST = os.path.join(STATE, "history.npz")
EVENTS = os.path.join(STATE, "events.jsonl")
CAP = 72 * 60
FIELDS = ["cpu", "gpu", "mem", "vram", "cpu_temp", "gpu_temp", "gpu_power", "rx", "tx",
          "lab_cpu", "lab_alerts", "lab_ready", "lab_nodes", "lab_pods", "svc_up", "svc_total", "wan_down"]
IX = {f: i for i, f in enumerate(FIELDS)}


class History:
    def __init__(self):
        self.lock = threading.Lock()
        self.t = np.zeros(CAP, dtype=np.float64)
        self.v = np.full((CAP, len(FIELDS)), np.nan, dtype=np.float32)
        self.n = 0                 # rows written (ring index = n % CAP)
        self.events = []
        self.saved_at = time.time()
        self._load()

    # ------------------------------------------------------------------ io
    def _load(self):
        try:
            z = np.load(HIST)
            fields = list(z["fields"])
            t, v = z["t"], z["v"]
            keep = t > time.time() - CAP * 60
            t, v = t[keep], v[keep]
            order = np.argsort(t)
            t, v = t[order][-CAP:], v[order][-CAP:]
            for j, f in enumerate(fields):
                if f in IX:
                    self.v[:len(t), IX[f]] = v[:, j]
            self.t[:len(t)] = t
            self.n = len(t)
        except (OSError, KeyError, ValueError):
            pass
        try:
            cut = time.time() - CAP * 60
            with open(EVENTS) as f:
                for line in f:
                    try:
                        e = json.loads(line)
                    except ValueError:
                        continue
                    if e.get("t", 0) > cut:
                        self.events.append(e)
            self.events = self.events[-3000:]
        except OSError:
            pass

    def save(self):
        with self.lock:
            t, v = self.series()
        os.makedirs(STATE, exist_ok=True)
        tmp = HIST + ".tmp.npz"
        np.savez_compressed(tmp, t=t, v=v, fields=np.array(FIELDS))
        os.replace(tmp, HIST)
        # rewrite the events log trimmed to the window
        cut = time.time() - CAP * 60
        with self.lock:
            self.events = [e for e in self.events if e["t"] > cut][-3000:]
            lines = [json.dumps(e) + "\n" for e in self.events]
        with open(EVENTS + ".tmp", "w") as f:
            f.writelines(lines)
        os.replace(EVENTS + ".tmp", EVENTS)
        self.saved_at = time.time()

    # ------------------------------------------------------------------ write
    def add_row(self, ts, values):
        with self.lock:
            i = self.n % CAP
            self.t[i] = ts
            row = np.full(len(FIELDS), np.nan, dtype=np.float32)
            for k, val in values.items():
                if k in IX and val is not None:
                    row[IX[k]] = float(val)
            self.v[i] = row
            self.n += 1
        if time.time() - self.saved_at > 300:
            try:
                self.save()
            except OSError:
                pass

    def event(self, kind, text=""):
        e = {"t": time.time(), "k": kind, "x": (text or "")[:90]}
        with self.lock:
            self.events.append(e)
        try:
            os.makedirs(STATE, exist_ok=True)
            with open(EVENTS, "a") as f:
                f.write(json.dumps(e) + "\n")
        except OSError:
            pass

    # ------------------------------------------------------------------ read
    def series(self):
        """(t, v) in time order."""
        n = min(self.n, CAP)
        if self.n <= CAP:
            return self.t[:n].copy(), self.v[:n].copy()
        i = self.n % CAP
        return np.concatenate([self.t[i:], self.t[:i]]), np.concatenate([self.v[i:], self.v[:i]])


class Recorder(threading.Thread):
    """Samples the shared Data snapshot once a minute (CPU and network averaged
    over the minute from Data's 1 s samples)."""

    def __init__(self, data, hist):
        super().__init__(daemon=True, name="history")
        self.data = data
        self.hist = hist

    def run(self):
        while not self.data.stop.is_set():
            now = time.time()
            self.data.stop.wait(60 - now % 60 + 0.5)
            d = self.data.snapshot()
            acc = self.data.take_minute()
            cl = d.get("cluster") or {}
            c = cl.get("cluster") or {}
            svc = cl.get("services") or {}
            net = cl.get("network") or {}
            ok = d.get("cluster_ok")
            row = {
                "cpu": acc.get("cpu", d.get("cpu")), "gpu": d.get("gpu"), "mem": d.get("mem"), "vram": d.get("vram"),
                "cpu_temp": d.get("cpu_temp"), "gpu_temp": d.get("gpu_temp"), "gpu_power": d.get("gpu_power"),
                "rx": acc.get("rx", d.get("rx")), "tx": acc.get("tx", d.get("tx")),
            }
            if ok:
                row.update({"lab_cpu": c.get("cpuNow"), "lab_alerts": c.get("alertsFiring"),
                            "lab_ready": c.get("nodesReady"), "lab_nodes": c.get("nodesTotal"),
                            "lab_pods": c.get("podsRunning"),
                            "svc_up": sum(1 for v in svc.values() if (v or {}).get("status") == "up") if svc else None,
                            "svc_total": len(svc) if svc else None, "wan_down": net.get("wanDownBps")})
            self.hist.add_row(time.time() // 60 * 60, row)
