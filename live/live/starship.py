"""The swarm's starships: one hull model (models/starship.holo.npz, made by
tools/make-starship.py), drawn instanced — every ship in one call for the wireframe
and one for the faint shell. Per ship: position, scale, yaw/pitch/roll, alpha and
four light levels (hull, spire, engines, running lights) plus a status colour for the
lights and the spire beacon, all as uniform arrays indexed by gl_InstanceID."""
import ctypes
import os
import sys

import numpy as np
from OpenGL import GL

from . import glkit

HERE = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
MODEL = os.path.join(HERE, "models", "starship.holo.npz")
MAX = 32


def load_model():
    """The shared reader (holo.fmt) when it is there, else numpy directly (same format)."""
    from . import VECTOR
    if VECTOR and VECTOR not in sys.path:
        sys.path.insert(0, VECTOR)
    try:
        from holo.fmt import HoloModel
        m = HoloModel(MODEL)
        return m.pos, m.part, m.edge, m.tri, m.meta
    except Exception:
        import json
        with np.load(MODEL) as d:
            return d["pos"], d["part"], d["edge"], d["tri"], json.loads(bytes(d["meta"]).decode())


class ShipPainter:
    def __init__(self):
        pos, part, edge, tri, self.meta = load_model()
        pos = pos.astype(np.float32)
        pos[:, 1] -= self.meta.get("height", 0.3) * 0.35          # pivot near the hull's middle
        corners = np.array([[0, 0], [1, 0], [1, 1], [0, 0], [1, 1], [0, 1]], np.float32)
        p0, p1 = pos[edge[:, 0]], pos[edge[:, 1]]
        pe = part[edge[:, 0]].astype(np.float32)
        n = len(edge)
        v = np.zeros((n, 6, 9), np.float32)
        v[:, :, 0:3] = p0[:, None, :]
        v[:, :, 3:6] = p1[:, None, :]
        v[:, :, 6:8] = corners[None, :, :]
        v[:, :, 8] = pe[:, None]
        self.n_line = n * 6
        self.lines = self._vao(v.reshape(-1, 9), ((0, 3, 0), (1, 3, 12), (2, 3, 24)), 36)
        tv = np.zeros((len(tri) * 3, 4), np.float32)
        tv[:, 0:3] = pos[tri.reshape(-1)]
        tv[:, 3] = part[tri.reshape(-1)]
        self.n_fill = len(tv)
        self.fill = self._vao(tv, ((0, 3, 0), (1, 1, 12)), 16)
        self.p_line = glkit.program("ship.vert", "line.frag")
        self.p_fill = glkit.program("ship_fill.vert", "ship_fill.frag")

    @staticmethod
    def _vao(data, attrs, stride):
        vao = GL.glGenVertexArrays(1)
        vbo = GL.glGenBuffers(1)
        GL.glBindVertexArray(vao)
        GL.glBindBuffer(GL.GL_ARRAY_BUFFER, vbo)
        GL.glBufferData(GL.GL_ARRAY_BUFFER, data.nbytes, np.ascontiguousarray(data), GL.GL_STATIC_DRAW)
        for loc, size, off in attrs:
            GL.glEnableVertexAttribArray(loc)
            GL.glVertexAttribPointer(loc, size, GL.GL_FLOAT, GL.GL_FALSE, stride, ctypes.c_void_p(off))
        GL.glBindVertexArray(0)
        return vao

    def draw(self, painter, res, t, ships, fade=1.0, width=1.15):
        """ships: list of dicts with pos(3), scale, rot(3), alpha, lights(4), colour(3), beacon."""
        ships = ships[:MAX]
        if not ships:
            return
        sp = np.zeros((MAX, 4), np.float32)
        so = np.zeros((MAX, 4), np.float32)
        sl = np.zeros((MAX, 4), np.float32)
        sc = np.zeros((MAX, 4), np.float32)
        for i, s in enumerate(ships):
            sp[i] = (*s["pos"], s["scale"])
            so[i] = (*s["rot"], s["alpha"])
            sl[i] = s["lights"]
            sc[i] = (*s["colour"], s["beacon"])
        for prog, vao, count in ((self.p_fill, self.fill, self.n_fill), (self.p_line, self.lines, self.n_line)):
            painter._uniforms(prog, res, t, {"fade": fade})
            prog.fv("u_sp", sp, 4)
            prog.fv("u_so", so, 4)
            prog.fv("u_sl", sl, 4)
            prog.fv("u_sc", sc, 4)
            if prog is self.p_line:
                prog.f("u_width", width)
            GL.glBindVertexArray(vao)
            GL.glDrawArraysInstanced(GL.GL_TRIANGLES, 0, count, len(ships))
        GL.glBindVertexArray(0)
