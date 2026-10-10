"""Cover fit for screens that aren't 16:9 (16:10, 21:9, 32:9, a 3:2 laptop).

The den and the worlds are painted and laid out for 16:9 (2560x1440 plate pixels): drawn
straight onto another shape they'd stretch. `wrap()` renders the scene unchanged at the
smallest 16:9 size that covers the screen, into its own target, and copies the visible
window of it onto the screen: nothing stretches, the overflow is cropped. The window is
centred, or on the scene's `focus` (plate pixels; a world's `[view] focus = [x, y]`), kept
inside the picture. On a 16:9 screen (within 1%) the scene is used as it is: no copy.
"""
from OpenGL import GL

from . import glkit

ASPECT = 16.0 / 9.0
PLATE_W, PLATE_H = 2560.0, 1440.0


def size(w, h):
    """The 16:9 render size that covers a w x h screen."""
    if w / h >= ASPECT:
        return w, max(h, int(round(w / ASPECT)))
    return max(w, int(round(h * ASPECT))), h


def wrap(make, w, h):
    """make(w, h) -> the scene. Returns it, or a Cover of it on a non-16:9 screen."""
    if abs((w / h) / ASPECT - 1.0) < 0.01:
        return make(w, h)
    cw, ch = size(w, h)
    return Cover(make(cw, ch), w, h, cw, ch)


class Cover:
    def __init__(self, inner, w, h, cw, ch):
        self.inner, self.w, self.h, self.cw, self.ch = inner, w, h, cw, ch
        self.target = None
        fx, fy = getattr(inner, "focus", None) or (PLATE_W / 2, PLATE_H / 2)
        # the window's lower-left corner in the target (GL: y up), kept inside it
        x0 = fx / PLATE_W * cw - w / 2
        y0 = ch - fy / PLATE_H * ch - h / 2
        self.x0 = int(round(min(max(x0, 0), cw - w)))
        self.y0 = int(round(min(max(y0, 0), ch - h)))
        inner.view = (self.x0, ch - self.y0 - h)       # the window's top-left in the scene: the den TV's pointer

    def __getattr__(self, name):          # events, commands, state: the scene's own
        return getattr(self.inner, name)

    def __setattr__(self, name, value):
        if name in ("inner", "w", "h", "cw", "ch", "target", "x0", "y0"):
            object.__setattr__(self, name, value)
        else:
            setattr(self.inner, name, value)   # e.g. r.app = …

    def render(self, fbo, fps):
        if self.target is None:
            self.target = glkit.Target(self.cw, self.ch)
        self.inner.render(self.target.fbo, fps)
        GL.glBindFramebuffer(GL.GL_READ_FRAMEBUFFER, self.target.fbo)
        GL.glBindFramebuffer(GL.GL_DRAW_FRAMEBUFFER, fbo)
        GL.glBlitFramebuffer(self.x0, self.y0, self.x0 + self.w, self.y0 + self.h,
                             0, 0, self.w, self.h, GL.GL_COLOR_BUFFER_BIT, GL.GL_NEAREST)
        GL.glBindFramebuffer(GL.GL_FRAMEBUFFER, fbo)
        GL.glViewport(0, 0, self.w, self.h)

    def close(self):
        if self.target is not None:
            try:
                self.target.free()
            except Exception:
                pass
            self.target = None
        close = getattr(self.inner, "close", None)
        if close:
            close()
