"""A render stage for one GLArea: the emissive layer (gadgets) with a small
bloom chain, composited by a final full-screen shader into the area's FBO."""
from OpenGL import GL

from . import glkit


class Stage:
    def __init__(self, w, h, final_frag, atlas=None):
        self.w, self.h = w, h
        self.atlas = atlas or glkit.Atlas()
        self.painter = glkit.Painter(self.atlas)
        self.fs = glkit.Fullscreen()
        self.blur = glkit.program("fs.vert", "blur.frag")
        self.final = glkit.program("fs.vert", final_frag)
        self.emblem = glkit.program("quad.vert", "emblem.frag")
        self._targets(w, h)

    def _targets(self, w, h):
        self.emit = glkit.Target(w, h)
        self.half = glkit.Target(max(w // 2, 1), max(h // 2, 1))
        self.q1 = glkit.Target(max(w // 4, 1), max(h // 4, 1))
        self.q2 = glkit.Target(max(w // 4, 1), max(h // 4, 1))

    def resize(self, w, h):
        if (w, h) == (self.w, self.h):
            return
        for t in (self.emit, self.half, self.q1, self.q2):
            t.free()
        self.w, self.h = w, h
        self._targets(w, h)

    def begin_emit(self):
        self.emit.bind()
        GL.glClearColor(0, 0, 0, 0)
        GL.glClear(GL.GL_COLOR_BUFFER_BIT)
        GL.glEnable(GL.GL_BLEND)
        GL.glBlendFuncSeparate(GL.GL_ONE, GL.GL_ONE, GL.GL_ONE, GL.GL_ONE)

    def bloom(self, gain=1.0):
        GL.glDisable(GL.GL_BLEND)
        p = self.blur
        p.use()
        p.i("u_src", 0)
        GL.glActiveTexture(GL.GL_TEXTURE0)
        steps = ((self.emit, self.half, (0.0, 0.0), gain),
                 (self.half, self.q1, (0.0, 0.0), 1.0),
                 (self.q1, self.q2, (1.0 / self.q1.w, 0.0), 1.0),
                 (self.q2, self.q1, (0.0, 1.0 / self.q1.h), 1.0),
                 (self.q1, self.q2, (2.0 / self.q1.w, 0.0), 1.0),
                 (self.q2, self.q1, (0.0, 2.0 / self.q1.h), 1.0))
        for src, dst, d, g in steps:
            dst.bind()
            GL.glBindTexture(GL.GL_TEXTURE_2D, src.tex)
            p.f("u_dir", *d)
            p.f("u_gain", g)
            self.fs.draw()
        return self.q1.tex

    def draw_emblem(self, em, rect, angle, ring_t=1.0, flame_t=1.0, mast_t=1.0, alpha=1.0, gain=1.0,
                    emissive=False, small=False):
        p = self.emblem
        p.use()
        p.f("u_res", float(self.w), float(self.h))
        p.f("u_rect", *rect)
        GL.glActiveTexture(GL.GL_TEXTURE0)
        GL.glBindTexture(GL.GL_TEXTURE_2D, em.small if small else em.ring)
        GL.glActiveTexture(GL.GL_TEXTURE1)
        GL.glBindTexture(GL.GL_TEXTURE_2D, em.flame or em.ring)
        p.i("u_ring", 0)
        p.i("u_flame", 1)
        p.f("u_has_flame", 1.0 if (em.flame and not small) else 0.0)
        p.f("u_angle", angle)
        p.f("u_ring_t", ring_t)
        p.f("u_flame_t", flame_t)
        p.f("u_mast_t", mast_t)
        p.f("u_alpha", alpha)
        p.f("u_ring_gain", gain)
        p.f("u_mode", 1.0 if emissive else 0.0)
        GL.glBindVertexArray(self.fs.vao)
        GL.glDrawArrays(GL.GL_TRIANGLES, 0, 6)
        GL.glActiveTexture(GL.GL_TEXTURE0)
