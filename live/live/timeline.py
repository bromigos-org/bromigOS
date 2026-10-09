"""SUPER+T — the timeline: the local history as a 3D time ribbon you scrub.

Lanes (front to back): CPU, GPU, MEM, NET (this machine, from the minute
recorder), LAB CPU, WAN and LAB ALERTS (the lab, backfilled from the lab snapshot's
own 24 h series and extended by the recorder). Each lane is drawn from bucket
maxima so spikes survive the zoom; the tallest spikes are tagged with when.
Events (critical notifications, codec calls, paper fills, lab alerts,
lock/unlock) stand as beacons behind the lanes.

Move the mouse (or ←/→) to scrub; 1/2/3 = 6 h / 24 h / 72 h; Tab cycles decks.
"""
import math
import time

import numpy as np

from . import gadgets, glkit
from .glkit import col
from .history import FIELDS, IX, History
from .homelab import lab_name
from .overlays import Base

TAU = 2 * math.pi
RANGES = {"1": 6 * 3600, "2": 24 * 3600, "3": 72 * 3600}
X0, X1 = -1.45, 1.45
LANES = [  # key, label, colour, transform, floor of the auto-scale, unit formatter
    ("cpu", "CPU", "phosphor", lambda v: v, 10.0, lambda v: f"{v:.0f}%"),
    ("gpu", "GPU", "soft", lambda v: v, 10.0, lambda v: f"{v:.0f}%"),
    ("mem", "MEM", "dim", lambda v: v, 10.0, lambda v: f"{v:.0f}%"),
    ("net", "NET", "amber", lambda v: math.log10(1 + v), 4.0, lambda v: gadgets.fmt_rate(v)),
    ("lab_cpu", "LAB CPU", "phosphor", lambda v: v, 10.0, lambda v: f"{v:.0f}%"),
    ("wan", "WAN", "amber", lambda v: math.log10(1 + v), 5.0, lambda v: gadgets.fmt_bytes(v / 8, "B/S")),
    ("lab_alerts", "LAB ALERTS", "danger", lambda v: v, 5.0, lambda v: f"{v:.0f}"),
]
H = 0.30
EV_COL = {"critical": "danger", "codec": "white", "fill": "amber", "lab": "danger", "lock": "dim",
          "unlock": "dim", "start": "soft", "notify": "dim"}


def _hm(ts):
    return time.strftime("%H:%M", time.localtime(float(ts)))


class TimelineDeck(Base):
    name = "timeline"
    rebuild_every = 1.0

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        s = self.h / 1440.0
        self.s = s
        self.hist = getattr(self.app, "history", None) or History()
        self.range = RANGES["2"]
        self.cursor = None            # absolute time; None = now
        self.L = {"panel": (60 * s, 150 * s, 1880 * s, 1060 * s), "center": (1000 * s, 690 * s, 500 * s),
                  "read": (1960 * s, 150 * s, 540 * s, 1060 * s)}
        self.yaw, self.pitch = 0.0, -0.42
        self.lanes = {}
        self.last_input = -10.0

    # ------------------------------------------------------------------ data
    def _gather(self, d):
        t, v = self.hist.series()
        now = time.time()
        lanes = {}

        def col_(f):
            j = IX[f]
            m = ~np.isnan(v[:, j])
            return t[m], v[m, j].astype(np.float64)
        for f in ("cpu", "gpu", "mem", "lab_cpu", "lab_alerts"):
            lanes[f] = col_(f)
        rt, rv = col_("rx")
        tt, tv = col_("tx")
        n = min(len(rt), len(tt))
        lanes["net"] = (rt[:n], rv[:n] + tv[:n])
        lanes["wan"] = col_("wan_down")
        # backfill the lab lanes from the lab's own series (real, 10-min steps)
        cl = d.get("cluster") or {}
        for key, path in (("lab_cpu", ("cluster", "cpuSeries")), ("wan", ("network", "wanDownSeries"))):
            ser = (cl.get(path[0]) or {}).get(path[1]) or []
            if ser:
                bt = np.array([p[0] for p in ser], dtype=np.float64)
                bv = np.array([p[1] for p in ser], dtype=np.float64)
                ht, hv = lanes[key]
                keep = bt < (ht[0] if len(ht) else now + 1)
                lanes[key] = (np.concatenate([bt[keep], ht]), np.concatenate([bv[keep], hv]))
        self.lanes = lanes
        self.since = float(t[0]) if len(t) else now

    def _x(self, ts, now):
        return X0 + (X1 - X0) * (1.0 - (now - ts) / self.range)

    @staticmethod
    def _z(i):
        return -0.66 + i * 0.2

    # ------------------------------------------------------------------ build
    def build(self, b, d, t):
        s = self.s
        T = 0.05
        self._gather(d)
        now = time.time()
        t0 = now - self.range
        cur = float(self.cursor or now)
        x, y, w, h = self.L["panel"]
        rng = {6 * 3600: "6 H", 24 * 3600: "24 H", 72 * 3600: "72 H"}[self.range]
        b.text("TIMELINE // WHAT SPIKED, AND WHEN", 60 * s, 110 * s, col("soft"), font="l", track=6, reveal=T,
               type_rate=0.02)
        b.text(f"RANGE {rng} · LOCAL RECORDING SINCE {time.strftime('%b %d %H:%M', time.localtime(float(self.since))).upper()}"
               f" · LAB LANES BACKFILLED FROM {lab_name()}", self.w - 60 * s, 108 * s, col("dim"), font="xs", track=1.5,
               align="r", reveal=T + 0.2)
        b.line((60 * s, 130 * s), (self.w - 60 * s, 130 * s), col("guard"), reveal=T)
        gadgets.frame(b, x, y, w, h, "THE RIBBON", T + 0.05, sub="MOUSE / ← → SCRUB · 1 2 3 RANGE · TAB NEXT DECK")
        zb = self._z(len(LANES))
        # time grid on the floor of the ribbon
        step = {6 * 3600: 3600, 24 * 3600: 3 * 3600, 72 * 3600: 12 * 3600}[self.range]
        first = math.ceil(t0 / step) * step
        for k, ts in enumerate(np.arange(first, now, step)):
            xx = self._x(ts, now)
            b.line((xx, 0.0, self._z(0) - 0.08), (xx, 0.0, zb), col("guard", 0.9), space=2, reveal=T + 0.2)
            b.text(_hm(ts), xx, 0.0, col("dim"), font="xs", track=1, space=2, z=self._z(0) - 0.1, dx=-18, dy=20,
                   reveal=T + 0.3)
        peaks = []
        for i, (key, label, c, tf, floor, fmt) in enumerate(LANES):
            z = self._z(i)
            ts_, vs_ = self.lanes.get(key, (np.zeros(0), np.zeros(0)))
            m = ts_ >= t0
            ts_, vs_ = ts_[m], vs_[m]
            b.line((X0, 0.0, z), (X1, 0.0, z), col("guard"), space=2, reveal=T + 0.15 + i * 0.04)
            b.text(label, X0, 0.0, col(c), font="s", track=2, space=2, z=z, dx=-12, dy=4, align="r",
                   reveal=T + 0.3 + i * 0.04)
            if not len(ts_):
                b.text("NO SAMPLES IN RANGE YET", X0 + 0.05, 0.0, col("dim", 0.8), font="xs", track=1.5, space=2,
                       z=z, dx=6, dy=-6, reveal=T + 0.4)
                continue
            nb = 360
            idx = np.clip(((ts_ - t0) / self.range * nb).astype(int), 0, nb - 1)
            mx = np.full(nb, np.nan)
            np.fmax.at(mx, idx, vs_)
            tv = np.array([tf(v) if not np.isnan(v) else np.nan for v in mx])
            top = max(np.nanmax(tv) * 1.1, floor)
            sc = lambda v: tf(v) / top  # noqa: E731
            pts = []
            for k in range(nb):
                if np.isnan(mx[k]):
                    pts.append(None)
                    continue
                xx = X0 + (X1 - X0) * (k + 0.5) / nb
                yy = sc(mx[k]) * H
                pts.append((xx, yy, z))
            have = [k for k in range(nb) if pts[k]]
            gap = max(3, int(nb * 1500 / self.range))      # bridge sample spacing up to ~25 min
            for a, c2 in zip(have, have[1:]):
                if c2 - a <= gap:
                    b.line(pts[a], pts[c2], col(c, 1.0), width=1.6, space=2,
                           reveal=T + 0.35 + i * 0.05 + a * 0.0012)
            for k in range(nb):
                if pts[k] and k % 2 == 0:
                    b.line((pts[k][0], 0.0, z), pts[k], col(c, 0.12), space=2, reveal=T + 0.4 + i * 0.05)
            # the tallest spike, tagged with when
            j = int(np.nanargmax(mx)) if not np.all(np.isnan(mx)) else None
            if j is not None and pts[j]:
                tj = t0 + (j + 0.5) / nb * self.range
                peaks.append((label, fmt(mx[j]), tj, c))
                b.arc(pts[j], 0, 3.0 * s, 0, TAU, col("white"), kind=2, space=2, reveal=T + 0.8)
                b.text(f"{fmt(mx[j])} {_hm(tj)}", *pts[j][:2], col(c), font="xs", track=0.8, space=2, z=z,
                       dx=8, dy=-8, reveal=T + 0.9)
            # now value at the right end
            b.text(fmt(vs_[-1]), X1, 0.0, col(c), font="xs", track=1, space=2, z=z, dx=10, dy=4, reveal=T + 0.6)
        # events: beacons standing behind the lanes
        evs = [e for e in self.hist.events if e["t"] >= t0]
        for e in evs:
            xx = self._x(e["t"], now)
            c = EV_COL.get(e["k"], "dim")
            hgt = 0.14 if e["k"] in ("notify", "lock", "unlock") else 0.40
            b.line((xx, 0.0, zb), (xx, hgt, zb), col(c, 0.75), space=2, reveal=T + 0.7)
            b.arc((xx, hgt, zb), 0, 2.2 * s, 0, TAU, col(c), kind=2, space=2, reveal=T + 0.8)
        # the cursor: a plane through every lane
        xc = self._x(cur, now)
        b.line((xc, 0.0, self._z(0) - 0.08), (xc, 0.0, zb), col("white", 0.9), space=2, width=1.5)
        b.line((xc, 0.0, self._z(0) - 0.08), (xc, 0.45, self._z(0) - 0.08), col("white", 0.6), space=2)
        late = (now - cur) < self.range * 0.15
        b.text(time.strftime("%a %H:%M", time.localtime(float(cur))).upper(), xc, 0.45, col("white"), font="s", track=1.5,
               space=2, z=self._z(0) - 0.08, dx=-12 if late else -30, dy=-10, align="r" if late else "l")
        self._readout(b, cur, evs, peaks, T)

    def _readout(self, b, cur, evs, peaks, T):
        s = self.s
        x, y, w, h = self.L["read"]
        gadgets.frame(b, x, y, w, h, "AT THE CURSOR", T + 0.1)
        b.text(time.strftime("%A %d %B · %H:%M", time.localtime(float(cur))).upper(), x + 18 * s, y + 70 * s,
               col("white"), font="s", track=1.5)
        yy = y + 104 * s
        for key, label, c, tf, floor, fmt in LANES:
            ts_, vs_ = self.lanes.get(key, (np.zeros(0), np.zeros(0)))
            val = None
            if len(ts_):
                k = int(np.argmin(np.abs(ts_ - cur)))
                if abs(ts_[k] - cur) <= max(self.range / 300, 660):
                    val = vs_[k]
            b.text(label, x + 18 * s, yy, col(c), font="xs", track=2)
            b.text(fmt(val) if val is not None else "--", x + w - 18 * s, yy, col("white" if val is not None else "dim"),
                   font="s", track=1, align="r")
            yy += 26 * s
        yy += 14 * s
        b.text("NEAR THE CURSOR", x + 18 * s, yy, col("dim"), font="xs", track=3)
        yy += 24 * s
        near = sorted([e for e in evs if abs(e["t"] - cur) <= self.range / 60], key=lambda e: abs(e["t"] - cur))[:8]
        if not near:
            b.text("NO EVENTS", x + 18 * s, yy, col("dim", 0.8), font="xs", track=1.5)
            yy += 22 * s
        for e in sorted(near, key=lambda e: e["t"]):
            txt = "".join(ch if 32 <= ord(ch) < 127 else "" for ch in e.get("x", ""))
            b.text(f"{_hm(e['t'])} {e['k'].upper():<8} {txt}"[:52].upper(), x + 18 * s, yy,
                   col(EV_COL.get(e["k"], "dim")), font="xs", track=0.5)
            yy += 21 * s
        yy += 18 * s
        b.text("TALLEST SPIKES IN RANGE", x + 18 * s, yy, col("dim"), font="xs", track=3)
        yy += 24 * s
        for label, v, tj, c in peaks:
            b.text(f"{label:<11} {v:>12}  AT {time.strftime('%a %H:%M', time.localtime(float(tj))).upper()}", x + 18 * s,
                   yy, col(c), font="xs", track=0.5)
            yy += 21 * s
        b.text(f"{len(evs)} EVENTS · 1 2 3: 6 H / 24 H / 72 H", x + 18 * s, y + h - 20 * s, col("dim"), font="xs",
               track=1.5)

    # ------------------------------------------------------------------ frame
    def frame(self, t, d):
        p = self.stage.painter
        cx, cy, R = self.L["center"]
        p.rot[2] = glkit.rot_matrix(self.yaw, self.pitch)
        p.ctr[2] = (cx, cy, R, 3.4)
        fade = min(t / 0.25, 1.0)
        if self.closing_at is not None:
            fade = max(0.0, 1.0 - (t - self.closing_at) / 0.25)
        u = {"backdrop": 0.86, "glow": 0.9, "fade": fade}
        if self.closing_at is not None and t - self.closing_at > 0.26:
            u["finished"] = True
        return u

    # ------------------------------------------------------------------ input
    def _time_at(self, sx):
        p = self.stage.painter
        a, bb = glkit.project([(X0, 0.0, self._z(0)), (X1, 0.0, self._z(0))], p.rot[2], p.ctr[2])[:, 0]
        # float(): glkit.project returns float32, and under NumPy 2 a float32 operand keeps the
        # whole expression float32 — epoch seconds then lose ~2 minutes of precision and
        # time.localtime() rejects the value (the deck crashed on open as the cursor moved).
        f = float(min(max((sx - a) / max(bb - a, 1.0), 0.0), 1.0))
        return time.time() - self.range * (1.0 - f)

    def motion(self, x, y, buttons):
        x0, y0, w, h = self.L["panel"]
        if x0 <= x <= x0 + w and y0 <= y <= y0 + h:
            self.cursor = self._time_at(x)
            self.built_at = None

    def click(self, x, y, button):
        x0, y0, w, h = self.L["panel"]
        x1, y1, w1, h1 = self.L["read"]
        if not (x0 <= x <= x0 + w and y0 <= y <= y0 + h) and not (x1 <= x <= x1 + w1 and y1 <= y <= y1 + h1):
            self.close()
        return True

    def key(self, name):
        if name in ("Escape", "q"):
            self.close()
        elif name in RANGES:
            self.range = RANGES[name]
            self.cursor = None
        elif name in ("Left", "h", "Right", "l"):
            cur = self.cursor or time.time()
            step = self.range / 240 * (-1 if name in ("Left", "h") else 1)
            self.cursor = min(max(cur + step, time.time() - self.range), time.time())
        elif name in ("End",):
            self.cursor = None
        elif name == "Tab" and self.app:
            from .decks import next_deck
            nxt = next_deck(self.name, self.cfg)
            if nxt:
                self.close()
                from gi.repository import GLib
                GLib.timeout_add(300, lambda: (self.app.overlay(nxt), False)[1])
        self.built_at = None
        return True
