"""Fireflies (a world's `fireflies` effect): live particles, this machine's network
throughput as their number and brightness.

Each firefly lives over a spot of water (its `ground` y: farther ones higher on the
screen, smaller, dimmer, with less parallax) at a height above it, and drifts on a slow
divergence-free (curl) flow, so the swarm wanders lazily without bunching up. Each blinks
on its own slow rhythm. Near ones get their reflection directly below them on the water;
far ones are drawn behind the water plane, so the mirror reflects them by itself.

  count       base + gain x throughput (smoothed over `smooth` s): a handful when the
              network is idle, hundreds during a big download; a few more in deep night,
              thinning toward dawn
  scatter     a Sleeper rising or submerging pushes the ones nearby away

All positions are plate pixels; `update()` returns glow instances for the world's glow
pass: [(depth, (x, y, rx, ry, r, g, b, intensity, fog))].
"""
import math

import bromigos_theme as palette

import numpy as np

TAU = 2 * math.pi


class Fireflies:
    calm = False               # reduced motion (live/motion.py): no blinking

    def __init__(self, e, line):
        self.e = e
        n = int(e.get("max", 420))
        rng = np.random.default_rng(int(e.get("seed", 7)))
        z = e.get("zone", (0, 600, 2560, 1360))           # x0, y0 (highest flight), x1, y1 (nearest water)
        self.x0, self.top, self.x1, self.y1 = (float(v) for v in z)
        self.line = float(line)
        self.n = n
        self.zdepth = rng.random(n) ** 0.8                 # 0 far .. 1 near
        self.ground = self.line + 8 + (self.y1 - self.line - 8) * self.zdepth ** 1.6
        self.x = rng.uniform(self.x0, self.x1, n)
        hmax = np.maximum(self.ground - self.top, 40.0)
        self.h = rng.random(n) ** 1.5 * hmax * 0.6 + 8.0      # height above its water
        self.hmax = hmax
        self.vx = np.zeros(n)
        self.vh = np.zeros(n)
        self.rank = rng.permutation(n).astype(np.float64)   # who lights first as the count grows
        self.alpha = np.zeros(n)
        self.period = rng.uniform(2.6, 7.5, n)
        self.phase = rng.random(n) * TAU
        self.size = 0.6 + 0.8 * rng.random(n)
        self.hue = rng.random(n)
        self.count = float(e.get("base", 6))
        self.disturb = []                                  # (x, y, t0)
        c0 = e.get("color", palette.rgb("primary"))
        c1 = e.get("color2", palette.rgb("warn"))
        self.c0, self.c1 = np.array(c0, float), np.array(c1, float)
        self.near_depth = float(e.get("near_depth", 44))
        self.far_depth = float(e.get("far_depth", 25))
        self.split = float(e.get("split", 0.45))           # zdepth over this: in front of the water

    def scatter(self, x, y, t):
        self.disturb.append((float(x), float(y), t))

    def update(self, t, dt, level, night, shelter=0.0):
        """`shelter` 0..1: the share that has gone to ground (rain), fading out smoothly."""
        e = self.e
        dt = max(0.0, min(dt, 0.1))
        target = float(e.get("base", 6)) + float(e.get("gain", 380)) * max(0.0, level) ** float(e.get("curve", 1.4))
        target *= 0.75 + 0.45 * night                       # more in deep night, fewer toward dawn
        target *= 1.0 - max(0.0, min(1.0, shelter))
        target = min(target, self.n)
        k = 1.0 - math.exp(-dt / float(e.get("smooth", 3.0))) if dt > 0 else 0.0
        self.count += (target - self.count) * k
        on = (self.rank < self.count).astype(np.float64)
        self.alpha += (on - self.alpha) * (1.0 - math.exp(-dt / 1.2) if dt > 0 else 0.0)
        # the curl of psi(x, h, t): a slow, swirling, divergence-free flow
        s = float(e.get("speed", 16.0))
        x, h = self.x, self.h
        a1, a2, a3 = 0.0021, 0.0034, 0.0013
        dpsi_dh = (-a2 * np.sin(x * a1 + t * 0.07) * np.sin(h * a2 - t * 0.05)
                   + 0.6 * a3 * np.cos((x - 1.7 * h) * a3 + t * 0.11) * -1.7)
        dpsi_dx = (a1 * np.cos(x * a1 + t * 0.07) * np.cos(h * a2 - t * 0.05)
                   + 0.6 * a3 * np.cos((x - 1.7 * h) * a3 + t * 0.11))
        fx = dpsi_dh / a2 * s
        fh = -dpsi_dx / a1 * s * 0.45
        # scatter from a rising or submerging Sleeper
        px_ = np.zeros(self.n)
        ph_ = np.zeros(self.n)
        self.disturb = [d for d in self.disturb if t - d[2] < 2.5]
        for (dx, dy, t0) in self.disturb:
            gy = self.ground - self.h
            rx, ry = x - dx, gy - dy
            r2 = rx * rx + ry * ry + 400.0
            f = 260.0 * math.exp(-(t - t0) / 0.9) * np.exp(-r2 / (2 * 220.0 ** 2))
            r = np.sqrt(r2)
            px_ += f * rx / r
            ph_ += -f * ry / r
        kv = 1.0 - math.exp(-dt / 0.8) if dt > 0 else 0.0
        self.vx += (fx + px_ - self.vx) * kv
        self.vh += (fh + ph_ - self.vh) * kv
        self.x += self.vx * dt * (0.5 + 0.5 * self.zdepth)
        self.h += self.vh * dt * (0.5 + 0.5 * self.zdepth)
        # keep them over their water: wrap across, bounce off the surface and the ceiling
        span = self.x1 - self.x0
        self.x = self.x0 + np.mod(self.x - self.x0, span)
        lo = self.h < 6.0
        self.h[lo] = 6.0
        self.vh[lo] = np.abs(self.vh[lo])
        hi = self.h > self.hmax
        self.h[hi] = self.hmax[hi]
        self.vh[hi] = -np.abs(self.vh[hi])
        # blinking: a soft flash on each one's own rhythm (reduced motion: a steady glow)
        if self.calm:
            blink = 0.6
        else:
            u = np.sin(t * TAU / self.period + self.phase)
            blink = 0.22 + 0.78 * np.clip(u, 0.0, 1.0) ** 2
        bright = float(e.get("brightness", 1.0)) * (0.6 + 0.8 * min(level * 1.4, 1.0))
        inten = self.alpha * blink * bright * (0.45 + 0.55 * self.zdepth)
        live = inten > 0.02
        cols = self.c0[None, :] * (1 - self.hue[:, None]) + self.c1[None, :] * self.hue[:, None]
        rad = (2.0 + 3.6 * self.zdepth) * self.size
        y = self.ground - self.h
        rows = np.zeros((self.n, 12))
        rows[:, 0], rows[:, 1], rows[:, 2], rows[:, 3] = self.x, y, rad, rad
        rows[:, 4:7] = cols
        rows[:, 7] = inten
        near = self.zdepth > self.split
        out = {}
        far_rows = rows[live & ~near]
        near_rows = rows[live & near]
        refl = float(e.get("reflect", 0.4))
        if refl > 0 and len(near_rows):                    # their reflections, directly below on the water
            r = near_rows.copy()
            sel = live & near
            r[:, 1] = self.ground[sel] + self.h[sel] * 0.9
            r[:, 2] *= 1.1
            r[:, 3] *= 2.2
            r[:, 7] *= refl
            near_rows = np.concatenate([near_rows, r])
        if len(far_rows):
            out[self.far_depth] = far_rows
        if len(near_rows):
            out[self.near_depth] = near_rows
        return out
