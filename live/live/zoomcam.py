"""Zoom, pan and level of detail for the 3D maps (Mind, Swarm, Network, the Drift map).

The camera works in screen space. A deck projects its model with
glkit.project(p, rot, ctr), ctr = (cx, cy, scale, persp), and the screen position is
linear in the centre and the scale. So the camera is two numbers on top of the
deck's own centre c0 and radius R: a zoom z and a pan offset o, giving
ctr = (c0 + o, R * z, persp). Zooming about a screen point A keeps the model point
under A still when

    o' = (A - c0) - (A - c0 - o) * z' / z

and that is applied every frame while the zoom eases, so the point under the cursor
never slides. Easing is frame-rate independent (1 - exp(-dt * RATE)) and works in
log zoom, so a touchpad's small smooth-scroll deltas give fine steps and a mouse
notch gives one STEP.

    cam = ZoomCam(panel_rect, (cx, cy), R, zmin=0.7, zmax=8)
    cam.wheel(x, y, dy)          # GTK scroll: dy > 0 zooms out; fractions from touchpads
    cam.pan_by(dx, dy)           # drag
    cam.fly_to(fn, z)            # VECTOR's verbs: fn() -> model xyz to centre, followed
    cam.fit(pts, rot, persp)     # frame a set of points (a traced path)
    cam.reset()                  # double-click empty space, or 0
    cam.step(dt, rot, persp)     # once per frame, before using cam.ctr(persp)

Labels: a map hands every label it could draw to Labels, highest priority first;
Labels keeps those that land inside the panel without overlapping one already kept,
up to a cap. Zoomed out, only the important ones fit; zooming in spreads the points
apart, so more labels fit and appear. lod(z, z0, z1) fades a class of detail in
between two zoom levels.
"""
import math

import numpy as np

from . import glkit
from .glkit import col

STEP = 0.18          # log zoom per mouse-wheel notch (about 1.2x)
RATE = 11.0          # easing toward the target, per second
FRAME_BUILD = 1 / 12  # while the camera moves, rebuild geometry at most this often


def lod(z, z0, z1):
    """0 below zoom z0, 1 above z1, smooth in between (in log zoom)."""
    if z1 <= z0:
        return 1.0 if z >= z0 else 0.0
    x = (math.log(max(z, 1e-6)) - math.log(z0)) / (math.log(z1) - math.log(z0))
    x = max(0.0, min(1.0, x))
    return x * x * (3 - 2 * x)


class ZoomCam:
    def __init__(self, rect, centre, R, zmin=0.7, zmax=8.0):
        self.rect = rect                       # x, y, w, h: the panel (pan limits and the clip)
        self.c0 = np.array(centre[:2], np.float64)
        self.R = float(R)
        self.zmin, self.zmax = zmin, zmax
        self.z = self.zt = 1.0
        self.o = np.zeros(2)
        self.ot = np.zeros(2)
        self.anchor = None                     # screen point (relative to c0) held still while zooming
        self.follow = None                     # fn -> model xyz kept at the panel centre (fly-to)
        self.built = (1.0, 0.0, 0.0)
        self.built_t = -1.0

    # ------------------------------------------------------------------ state
    @property
    def zoomed(self):
        return max(self.z, self.zt) > 1.04

    def moving(self):
        return abs(math.log(self.zt / self.z)) > 1e-3 or float(np.abs(self.ot - self.o).max()) > 0.3

    def ctr(self, persp):
        return (float(self.c0[0] + self.o[0]), float(self.c0[1] + self.o[1]), self.R * self.z, persp)

    def clip(self):
        x, y, w, h = self.rect
        return (x, y, x + w, y + h)

    def inside(self, x, y):
        x0, y0, w, h = self.rect
        return x0 <= x <= x0 + w and y0 <= y <= y0 + h

    def _mid(self):
        x, y, w, h = self.rect
        return np.array([x + w / 2, y + h / 2]) - self.c0

    def _clamp_z(self, z):
        return max(self.zmin, min(self.zmax, z))

    def _clamp_o(self, o, z):
        """Keep the model in reach: its centre no further from the panel centre than its radius."""
        m = self._mid()
        lim = self.R * z * 1.1
        return np.clip(o, m - lim, m + lim)

    # ------------------------------------------------------------------ input
    def wheel(self, x, y, dy):
        """Zoom toward the screen point (x, y); dy is GTK's scroll delta (> 0 = out)."""
        zt = self._clamp_z(self.zt * math.exp(-dy * STEP))
        if zt == self.zt:
            return False
        a = np.array([x, y], np.float64) - self.c0
        want = a - (a - self.o) * (zt / self.z)
        self.ot = self._clamp_o(want, zt)
        self.anchor = a if np.allclose(self.ot, want) else None     # at the pan limit: plain easing
        self.zt = zt
        self.follow = None
        return True

    def key_zoom(self, sign):
        x, y, w, h = self.rect
        return self.wheel(x + w / 2, y + h / 2, -1.5 * sign)

    def pan_by(self, dx, dy):
        self.o = self._clamp_o(self.o + (dx, dy), self.z)
        self.ot = self.o.copy()
        self.zt = self.z
        self.anchor = self.follow = None

    def reset(self):
        self.zt, self.ot = 1.0, np.zeros(2)
        self.anchor = self.follow = None

    def fly_to(self, fn, z):
        """Ease to centre fn() (model xyz, re-read every frame so a moving target stays put) at zoom z."""
        self.zt = self._clamp_z(z)
        self.anchor = None
        self.follow = fn

    def fit(self, pts, rot, persp, margin=0.62, zmax=None):
        """Frame model points: zoom so they fill `margin` of the panel, centred."""
        pts = np.asarray(pts, np.float32).reshape(-1, 3)
        if not len(pts):
            return
        pr = glkit.project(pts, rot, (0.0, 0.0, self.R, persp))
        lo, hi = pr[:, :2].min(0), pr[:, :2].max(0)
        span = np.maximum(hi - lo, 1.0)
        x, y, w, h = self.rect
        z = min(w * margin / span[0], h * margin / span[1], zmax or self.zmax)
        c = pts.mean(0)
        self.fly_to(lambda: c, max(1.0, z))

    # ------------------------------------------------------------------ per frame
    def _aim(self, m, z, rot, persp):
        s = glkit.project(np.asarray(m, np.float32).reshape(1, 3), rot, (0.0, 0.0, self.R, persp))[0]
        return self._clamp_o(self._mid() - z * s[:2].astype(np.float64), z)

    def step(self, dt, rot, persp):
        a = 1.0 - math.exp(-max(dt, 0.0) * RATE)
        if self.follow is not None:
            m = self.follow()
            if m is not None:
                self.ot = self._aim(m, self.zt, rot, persp)
        z0 = self.z
        z1 = self.zt if abs(math.log(self.zt / z0)) < 1e-3 else z0 * (self.zt / z0) ** a
        if self.anchor is not None:
            self.o = self.anchor - (self.anchor - self.o) * (z1 / z0)
            if z1 == self.zt:
                self.o, self.anchor = self.ot.copy(), None
        else:
            self.o = self.o + (self.ot - self.o) * a
            if float(np.abs(self.ot - self.o).max()) < 0.3:
                self.o = self.ot.copy()
        self.z = z1

    def build_due(self, t):
        """Geometry (labels, expansion) depends on the view: rebuild while it changes, throttled."""
        z, ox, oy = self.built
        if abs(math.log(self.z / z)) < 0.004 and abs(self.o[0] - ox) + abs(self.o[1] - oy) < 1.5:
            return False
        return not self.moving() or t - self.built_t >= FRAME_BUILD

    def mark_built(self, t):
        self.built = (self.z, float(self.o[0]), float(self.o[1]))
        self.built_t = t

    # ------------------------------------------------------------------ HUD
    def readout_box(self, s):
        x, y, w, h = self.rect
        bx, by = x + 24 * s, y + h - 30 * s
        return (bx - 10 * s, by - 30 * s, bx + 380 * s, by + 14 * s)

    def labels(self, atlas, painter, s, cap=70):
        """A Labels for this view (space 2), keeping clear of the readout."""
        lab = Labels(atlas, painter.rot[2], painter.ctr[2], self.rect, cap=cap)
        lab.reserve(self.readout_box(s))
        return lab

    def readout(self, b, s, T=0.0):
        """Zoom readout in the panel's bottom-left corner: the factor on a log scale from min to max."""
        x, y, w, h = self.rect
        bx, by = x + 24 * s, y + h - 30 * s
        bw = 150 * s
        x0, y0, x1, y1 = self.readout_box(s)
        b.plate(x0, y0, x1 - x0, y1 - y0, 0.8)
        lz0, lz1 = math.log(self.zmin), math.log(self.zmax)
        f = (math.log(self.z) - lz0) / (lz1 - lz0)
        b.line((bx, by), (bx + bw, by), col("guard"), reveal=T)
        for zz in (self.zmin, 1.0, 2.0, 4.0, 8.0, 16.0):
            if self.zmin <= zz <= self.zmax:
                k = (math.log(zz) - lz0) / (lz1 - lz0)
                b.line((bx + bw * k, by - (6 if zz == 1.0 else 3) * s), (bx + bw * k, by + 3 * s), col("dim"),
                       reveal=T)
        b.line((bx, by), (bx + bw * f, by), col("soft", 0.9), width=2.0, reveal=T)
        b.arc((bx + bw * f, by), 0, 3.2 * s, 0, 2 * math.pi, col("white"), kind=2, reveal=T)
        b.text(f"ZOOM {self.z:.1f}×", bx + bw + 14 * s, by + 5 * s, col("soft" if self.zoomed else "dim"), font="xs",
               track=1.5, reveal=T)
        hint = "DRAG PANS · SHIFT+DRAG TURNS · 0 RESETS" if self.zoomed else "SCROLL TO ZOOM"
        b.text(hint, bx, by - 14 * s, col("dim", 0.85), font="xs", track=1.2, reveal=T)


class Labels:
    """Greedy label placement: highest priority first, kept only if the box lands inside the
    panel and overlaps no label already kept, up to `cap`. Boxes are found on a coarse grid."""

    CELL = 64

    def __init__(self, atlas, rot, ctr, rect, cap=70, pad=2.0):
        self.atlas, self.rot, self.ctr, self.rect = atlas, rot, ctr, rect
        self.cap, self.pad = cap, pad
        self.items = []
        self.reserved = []

    def add(self, prio, xyz, text, font="xs", track=1.0, dx=10.0, dy=-6.0, **kw):
        """kw: colour, reveal, and force=True for a label that is always drawn (it still
        claims its space, so the others make way)."""
        self.items.append((prio, xyz, text, font, track, dx, dy, kw))

    def reserve(self, box):
        """A screen box (x0, y0, x1, y1) that no label may cover, e.g. a hover readout."""
        self.reserved.append(box)

    def _cells(self, box):
        c = self.CELL
        for gx in range(int(box[0] // c), int(box[2] // c) + 1):
            for gy in range(int(box[1] // c), int(box[3] // c) + 1):
                yield gx, gy

    def _put(self, grid, box):
        for k in self._cells(box):
            grid.setdefault(k, []).append(box)

    def _hits(self, grid, box):
        for k in self._cells(box):
            for o in grid.get(k, ()):
                if box[0] < o[2] and o[0] < box[2] and box[1] < o[3] and o[1] < box[3]:
                    return True
        return False

    def place(self, b, space=2):
        """Draw the labels that fit; returns how many were drawn."""
        if not self.items:
            return 0
        self.items.sort(key=lambda it: (not it[7].get("force"), -it[0]))
        pts = np.array([it[1] for it in self.items], np.float32).reshape(-1, 3)
        pr = glkit.project(pts, self.rot, self.ctr)
        x0, y0, w, h = self.rect
        grid = {}
        for box in self.reserved:
            self._put(grid, box)
        n = 0
        for (prio, xyz, text, font, track, dx, dy, kw), (sx, sy, _) in zip(self.items, pr):
            f = self.atlas.fonts[font]
            tw = f.width(text, track)
            base = sy + dy                                    # the text's baseline
            # capitals: about 0.78 of the ascent above the baseline, nothing below
            box = (sx + dx - self.pad, base - 0.78 * f.ascent - self.pad, sx + dx + tw + self.pad, base + self.pad)
            force = kw.get("force")
            if not force and (box[0] < x0 or box[2] > x0 + w or box[1] < y0 or box[3] > y0 + h):
                continue
            if not force and self._hits(grid, box):
                continue
            self._put(grid, box)
            b.text(text, xyz[0], xyz[1], kw.get("colour") or col("soft"), font=font, track=track, space=space,
                   z=xyz[2], dx=dx, dy=dy, reveal=kw.get("reveal", 0.0))
            n += 0 if force else 1
            if n >= self.cap:
                break
        return n
