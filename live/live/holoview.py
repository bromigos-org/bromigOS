"""A compact hologram for the holo deck, drawn by the shared bromigos-holo renderer
(holo.render.Holo + holo.stage.Stage + holo.bind readings over holo.live.Live),
reading the same .holo.npz files as the SUPER+O gallery. No loader or readings of
our own: the deck shows the current model turning on its table with live part
colours, a hover readout, and hands the model to the gallery (click or O) for the
full viewer (explode, isolate, callouts)."""
import math
import os
import subprocess
import sys
import time

import numpy as np
from OpenGL import GL

from . import VECTOR, VECTOR_CMD, glkit

# VECTOR's tree (bromigos-vector: /usr/lib/bromigos/vector), else the old dotfiles copy
HOLO = VECTOR or os.path.expanduser("~/.config/bromigos/holo")
if HOLO not in sys.path:
    sys.path.insert(0, HOLO)


def available():
    try:
        from holo import fmt
        return fmt.available()
    except Exception:
        return []


class CompactHolo:
    def __init__(self, names, scale=1.0):
        self.names = list(names)
        self.idx = 0
        self.scale = scale
        self.holo = None
        self.live = None
        self.stage = None
        self.target = None
        self.blit = None
        self.last_t = time.monotonic()
        self.t0 = None
        self.size = (1, 1)

    @property
    def name(self):
        return self.names[self.idx % len(self.names)]

    def cycle(self, step):
        self.idx = (self.idx + step) % len(self.names)
        if self.stage:
            self.stage.release()
            self.stage = None

    def _ensure(self, w, h):
        from holo.live import Live
        from holo.render import Holo
        from holo.stage import Stage
        if self.holo is None:
            self.holo = Holo(self.scale)
            self.live = Live()
        if self.stage is None:
            self.stage = Stage(self.name, self.live)
        if self.target is None or (self.target.w, self.target.h) != (w, h):
            if self.target:
                self.target.free()
            self.target = glkit.Target(w, h)
        if self.blit is None:
            self.blit = glkit.Program(glkit.read_shader("quad.vert"), glkit.read_shader("tex.frag"))
            self.vao = GL.glGenVertexArrays(1)
        self.size = (w, h)

    def title(self):
        if self.stage is None:
            return self.name.upper()
        return (self.stage.meta.get("title") or self.name).upper()

    def render(self, w, h, deck_t=None):
        """Draw the model into our own target (call outside any of our passes).
        deck_t: the deck's clock, so headless renders age the model like real time."""
        w, h = max(int(w), 16), max(int(h), 16)
        new = self.stage is None
        self._ensure(w, h)
        if self.t0 is None:
            self.t0 = time.monotonic() - (deck_t or 0.0)
        t = self.t0 + deck_t if deck_t is not None else time.monotonic()
        if new:
            self.stage.born = self.stage.scan_t0 = self.stage.last_scan = t
        dt = min(0.1, max(t - self.last_t, 0.0))
        self.last_t = t
        s = self.stage
        s.update(dt)
        H = self.holo
        H.begin(w, h, t)
        tgt = np.array([0, 0.48, 0], np.float32)
        dist = 3.6 / max(min(w / h, 1.0), 0.35) * 0.66        # a tall panel: pull back so it fits across
        eye = tgt + dist * np.array([0, math.sin(s.pitch), math.cos(s.pitch)], np.float32)
        H.camera(eye, tgt, 30.0, viewport=(0, 0, w, h))
        s.draw(H, t, size=0.95)
        H.end(self.target.fbo, bg=(0.0, 0.0, 0.0, 0.0), bloom=1.0)
        GL.glBindVertexArray(0)

    def composite(self, res, rect, fade=1.0):
        """Blend our target over the deck (premultiplied alpha) at rect (px, top-left)."""
        if self.target is None:
            return
        p = self.blit
        p.use()
        p.f("u_res", *res)
        p.f("u_rect", *rect)
        p.f("u_fade", fade)
        GL.glEnable(GL.GL_BLEND)
        GL.glBlendFunc(GL.GL_ONE, GL.GL_ONE_MINUS_SRC_ALPHA)
        GL.glActiveTexture(GL.GL_TEXTURE0)
        GL.glBindTexture(GL.GL_TEXTURE_2D, self.target.tex)
        p.i("u_tex", 0)
        GL.glBindVertexArray(self.vao)
        GL.glDrawArrays(GL.GL_TRIANGLES, 0, 6)
        GL.glDisable(GL.GL_BLEND)

    # ------------------------------------------------------------------ input (panel-local px)
    def pick(self, x, y):
        if self.stage is None or self.holo is None or self.stage.anchor_px is None:
            return None
        return self.stage.pick(self.holo, x, y)

    def hover(self, i):
        if self.stage:
            self.stage.hover = i

    def reading(self, i):
        """(label, level, lines, hint) for part i from the shared bindings."""
        s = self.stage
        p = s.parts[i]
        level, _v, lines, _ = s.readings[i]
        return p.get("label", p.get("id", "")).upper(), level, list(lines or []), p.get("hint", "")

    def drag(self, dyaw, dpitch):
        if self.stage:
            self.stage.dragging = True
            self.stage.yaw += dyaw
            self.stage.pitch = max(-0.2, min(1.1, self.stage.pitch + dpitch))

    def end_drag(self):
        if self.stage:
            self.stage.dragging = False

    def open_gallery(self):
        """The full viewer is SUPER+O; open it on this model."""
        exe = VECTOR_CMD or os.path.join(HOLO, "bin", "bromigos-holo")
        try:
            subprocess.Popen([exe, "gallery", self.name], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                             start_new_session=True)
        except OSError:
            pass

    def release(self):
        if self.stage:
            self.stage.release()
            self.stage = None
        if self.target:
            self.target.free()
            self.target = None
