"""The sky's traffic (space.glsl traffic()), decided on the CPU so ships never pop.

Ten lanes, each in a depth tier: far ships are small, slow and dim, near ones larger,
faster and brighter. Every crossing is a straight path at its own heading (horizontal,
a gentle diagonal of 10-35 degrees, or a steep 50-70 degrees, either way) through the
ship region, entering off one edge and leaving off another. A rare far crossing
approaches or recedes: its scale changes along the path.

Whether a crossing carries a ship is decided once, when it starts off-screen, from the
traffic level at that moment (this machine's network throughput), and the whole path is
fixed then; so a ship never appears or vanishes mid-screen. The level still sets how
many lanes are busy, with a lag of at most one crossing.

The debris density follows a slow average of the level (about 25 s); the shader fades
flecks in and out around that threshold.

Per frame `uniforms(level, rect)` returns u_ship (N x vec4: x, y px, heading rad,
scale), u_ship2 (N x vec4: brightness, occupied, hull kind, -), sorted far to near so the
shader can draw near over far, and the smoothed level. Positions use time.monotonic() in
double precision.
"""
import hashlib
import math
import time

import numpy as np

LANES = 10
TIERS = ("far", "far", "far", "mid", "mid", "mid", "mid", "mid", "near", "near")
TIER = {                       # scale, speed px/s (range), brightness
    "far": (0.5, (7.0, 13.0), 0.45),
    "mid": (0.8, (14.0, 26.0), 0.72),
    "near": (1.15, (24.0, 38.0), 1.0),
}
REACH = 150.0                  # px a ship (hull 44, trail behind) can extend from its centre at scale 1
EMA_SECONDS = 25.0


def _unit(*key):
    """A stable pseudo-random number in [0, 1) for a key (same on every run)."""
    h = hashlib.blake2b(repr(key).encode(), digest_size=8).digest()
    return int.from_bytes(h, "little") / 2.0 ** 64


def heading(lane, cyc):
    """Horizontal (40%), gentle diagonal 10-35 deg (40%) or steep 50-70 deg (20%), either way."""
    u = _unit("kind", lane, cyc)
    if u < 0.4:
        a = math.radians(-6 + 12 * _unit("a", lane, cyc))
    elif u < 0.8:
        a = math.radians(10 + 25 * _unit("a", lane, cyc)) * (1 if _unit("s", lane, cyc) < 0.5 else -1)
    else:
        a = math.radians(50 + 20 * _unit("a", lane, cyc)) * (1 if _unit("s", lane, cyc) < 0.5 else -1)
    if _unit("dir", lane, cyc) < 0.5:
        a += math.pi                                    # the other way along the same line
    return a


def path(rect, a, through, pad):
    """The straight path at heading a through a point, from pad px outside the rect to pad px outside it."""
    x0, y0, w, h = rect
    dx, dy = math.cos(a), math.sin(a)

    def reach(sign):                                    # distance to the rect's edge along +-(dx, dy)
        ts = []
        for d, p, lo, hi in ((dx * sign, through[0], x0, x0 + w), (dy * sign, through[1], y0, y0 + h)):
            if d > 1e-6:
                ts.append((hi - p) / d)
            elif d < -1e-6:
                ts.append((lo - p) / d)
        return min(ts) if ts else 0.0
    back, fwd = reach(-1) + pad, reach(1) + pad
    start = (through[0] - dx * back, through[1] - dy * back)
    return start, back + fwd


class Crossing:
    __slots__ = ("cyc", "t0", "dur", "start", "a", "length", "s0", "s1", "busy", "kind")


class Traffic:
    def __init__(self, clock=time.monotonic):
        self.clock = clock
        self.lanes = [None] * LANES
        self.cycles = [0] * LANES
        self.smooth = None
        self.t_last = None
        self.rect = None
        self.focus = None          # sub-regions the paths are aimed through (lane k uses focus[k % n])

    def _new(self, k, now, level, first=False):
        """Decide lane k's next crossing: path, depth, speed and whether it carries a ship."""
        cyc = self.cycles[k]
        self.cycles[k] += 1
        tier = TIERS[k]
        scale, (v0, v1), _ = TIER[tier]
        c = Crossing()
        c.cyc = cyc
        c.a = heading(k, cyc)
        x0, y0, w, h = self.focus[k % len(self.focus)] if self.focus else self.rect
        through = (x0 + w * (0.1 + 0.8 * _unit("px", k, cyc)), y0 + h * (0.1 + 0.8 * _unit("py", k, cyc)))
        speed = v0 + (v1 - v0) * _unit("v", k, cyc)
        c.s0 = c.s1 = scale
        if tier == "far" and _unit("zoom", k, cyc) < 0.12:     # rare: approaching or receding
            lo, hi = scale * 0.55, scale * 1.6
            c.s0, c.s1 = (lo, hi) if _unit("toward", k, cyc) < 0.5 else (hi, lo)
            speed *= 0.6
        c.start, c.length = path(self.rect, c.a, through, REACH * max(c.s0, c.s1))
        c.dur = c.length / speed
        c.t0 = now - (c.dur * _unit("t", k, cyc) if first else 0.0)   # at start-up lanes are mid-way
        c.busy = _unit("busy", k, cyc) < 0.12 + 0.88 * level
        c.kind = 1.0 if _unit("hull", k, cyc) < 0.5 else 0.0
        self.lanes[k] = c

    def uniforms(self, level, rect, focus=None):
        """level 0..1 (< 0 = traffic off); rect = the region paths cross (x, y, w, h) px; focus =
        sub-rects where ships are actually visible (the open sky, the den's window): each lane's
        paths are aimed through one of them, so every visible region keeps its share of traffic."""
        now = self.clock()
        dt = 0.0 if self.t_last is None else max(0.0, min(now - self.t_last, 5.0))
        self.t_last = now
        u1 = np.zeros((LANES, 4), np.float32)
        u2 = np.zeros((LANES, 4), np.float32)
        if level < 0:
            self.smooth = None
            return u1, u2, -1.0
        self.smooth = level if self.smooth is None else \
            self.smooth + (level - self.smooth) * (1 - math.exp(-dt / EMA_SECONDS))
        rect = tuple(float(v) for v in rect)
        focus = [tuple(float(v) for v in f) for f in focus] if focus else None
        first = self.rect != rect or self.focus != focus
        self.rect, self.focus = rect, focus
        rows = []
        for k in range(LANES):
            if first or self.lanes[k] is None:
                self._new(k, now, level, first=True)
            if now - self.lanes[k].t0 > 4 * self.lanes[k].dur:      # back from a long pause: start afresh
                self._new(k, now, level, first=True)
            while now - self.lanes[k].t0 >= self.lanes[k].dur:      # a crossing ended off-screen: the next one
                end = self.lanes[k].t0 + self.lanes[k].dur
                self._new(k, end, level)
            c = self.lanes[k]
            f = (now - c.t0) / c.dur
            s = c.length * f
            x = c.start[0] + math.cos(c.a) * s
            y = c.start[1] + math.sin(c.a) * s
            sc = c.s0 + (c.s1 - c.s0) * f
            bright = TIER[TIERS[k]][2] * (0.75 + 0.25 * min(sc / TIER[TIERS[k]][0], 1.4))
            rows.append((sc, (x, y, c.a, sc), (bright, 1.0 if c.busy else 0.0, c.kind, 0.0)))
        rows.sort(key=lambda r: r[0])                      # far first, near last: near draws over far
        for i, (_, a, b) in enumerate(rows):
            u1[i], u2[i] = a, b
        return u1, u2, float(self.smooth)
