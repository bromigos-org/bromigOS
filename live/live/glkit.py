"""GL plumbing for the live layer: shader programs, render targets, and three
instanced vector primitives (AA lines, arcs/discs, glyphs) that every gadget is
built from.

Geometry is uploaded only when the data behind it changes (about 1-2 Hz); motion
(rotation, packets, assembly flourishes, typing) is driven by uniforms in the
shaders, so a frame costs a handful of draw calls and almost no Python.

Coordinates are screen pixels, origin top-left. A primitive can live in a 3D
"space" (1..3): its points are rotated by u_rot[space], given mild perspective
and dropped onto the screen at u_ctr[space].xy with scale u_ctr[space].z.
"""
import ctypes
import math
import os

import numpy as np
import OpenGL

OpenGL.ERROR_CHECKING = False
from OpenGL import GL  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
SHADERS = os.path.join(os.path.dirname(HERE), "shaders")

from . import LIB  # noqa: E402,F401  (puts the shared libs on sys.path)
from . import motion  # noqa: E402
import bromigos_theme as T  # noqa: E402

# The Wick's names for the colours; col() takes them from the theme in force
# (bromigos_theme: phosphor is the theme's primary, amber its warn, guard its selection).
PAL = {
    "void": (0x00, 0x05, 0x00), "panel": (0x00, 0x13, 0x00), "guard": (0x00, 0x3b, 0x00),
    "phosphor": (0x39, 0xff, 0x14), "soft": (0x9c, 0xff, 0x8a), "dim": (0x15, 0x9b, 0x09),
    "amber": (0xd4, 0xaf, 0x37), "danger": (0xff, 0x76, 0x6f), "static": (0x7e, 0x92, 0x7e),
    "white": (0xe8, 0xff, 0xe0),
}


def col(name, a=1.0):
    r, g, b = T.rgb(name)
    return (r, g, b, a)


def level(v, warn, crit):
    if v is None:
        return "static"
    return "danger" if v >= crit else "amber" if v >= warn else "phosphor"


def read_shader(name):
    with open(os.path.join(SHADERS, name)) as f:
        return theme_consts(f.read())


# The shaders' named UI colours, written as the Wick's: in another theme they are
# swapped for its colours when the shader is compiled (an overlay opened after a theme
# switch has them). The Wick's shader text is left exactly as written.
_CONSTS = {"VOID": "void", "PHOS": "primary", "SOFT": "soft", "DIM": "dim", "AMBER": "warn",
           "DANGER": "danger", "amber": "warn", "danger": "danger"}
# The den's own shades of the Wick's green (its screens' glass, the gadgets' panel, the
# meters, the loops' streaks, floor rows and steam): another theme gets each at its own
# lightness in the theme's colours (bromigos_theme.retint_rgb: greens to primary's hue,
# near-black greens onto its background -> panel -> selection), as the plate itself
# (scene.retint_plate). The Wick's shader text is left exactly as written.
_SHADES = {"GLASS", "GLASS_LIT", "PLATE_PANEL", "METER_INK", "METER_NEEDLE", "STREAK", "ROWC", "STEAMC"}


def _intercept(key, fallback):
    """A colour from the theme's [intercept] table (colors.toml), else the role."""
    try:
        return T.rgb("intercept." + key)
    except Exception:
        return T.rgb(fallback)


def _scaled(rgb, luma):
    """rgb scaled to a given luma (Rec. 601 weights): the same brightness, the theme's hue."""
    l = 0.3 * rgb[0] + 0.59 * rgb[1] + 0.11 * rgb[2]
    return tuple(c * luma / max(l, 1e-3) for c in rgb)


# Named colours computed from the theme, not one role: the intercept's static grade (the
# Wick's vec3(0.25, 1.25, 0.2), luma 0.835), its needle, the planet's night tint.
_COMPUTED = {
    "TEAR": lambda: _scaled(_intercept("static", "primary"), 0.835),
    "NEEDLE": lambda: _intercept("needle", "soft"),
    "NIGHT": lambda: tuple(c * 0.02 for c in T.rgb("primary")),
}


def theme_consts(src):
    import re
    # read the palette now, not up to a second late: a theme switch rebuilds the background
    # at once, and a shader compiled from the last theme's cache keeps its colours (the den's
    # rain came up Tidewell-blue after tidewell -> wick)
    T.version(0.0)
    if T.is_wick():
        return src

    def vec(name):
        return "vec3(%.4f, %.4f, %.4f)" % T.rgb(name)

    def sub(m):
        name = m.group(2)
        if name in _CONSTS:
            return m.group(1) + vec(_CONSTS[name])
        if name in _SHADES:
            wick = [float(x) for x in re.findall(r"[-\d.]+", m.group(0)[m.group(0).rindex("vec3(") + 5:])][:3]
            return m.group(1) + "vec3(%.4f, %.4f, %.4f)" % tuple(T.retint_rgb(tuple(wick)))
        if name in _COMPUTED:
            return m.group(1) + "vec3(%.4f, %.4f, %.4f)" % _COMPUTED[name]()
        return m.group(0)
    src = re.sub(r"\b((?:const\s+)?vec3\s+(\w+)\s*=\s*)vec3\([^)]*\)", sub, src)
    # ov.frag's plates under the gadgets: the panel colour
    return src.replace("mix(c, vec3(0.0, 0.03, 0.0), plate)", "mix(c, %s, plate)" % vec("panel"))


def _includes(src):
    import re
    return re.sub(r"#include (\w+)", lambda m: read_shader(m.group(1) + ".glsl"), src)


def _compile(src, kind):
    s = GL.glCreateShader(kind)
    GL.glShaderSource(s, src)
    GL.glCompileShader(s)
    if not GL.glGetShaderiv(s, GL.GL_COMPILE_STATUS):
        raise RuntimeError(GL.glGetShaderInfoLog(s).decode() + "\n" + src[:200])
    return s


class Program:
    def __init__(self, vs, fs):
        vs, fs = _includes(vs), _includes(fs)
        self.id = GL.glCreateProgram()
        a, b = _compile(vs, GL.GL_VERTEX_SHADER), _compile(fs, GL.GL_FRAGMENT_SHADER)
        GL.glAttachShader(self.id, a)
        GL.glAttachShader(self.id, b)
        GL.glLinkProgram(self.id)
        if not GL.glGetProgramiv(self.id, GL.GL_LINK_STATUS):
            raise RuntimeError(GL.glGetProgramInfoLog(self.id).decode())
        GL.glDeleteShader(a)
        GL.glDeleteShader(b)
        self._loc = {}
        self.cache = None          # a dict: f() skips a value the program already holds (opt-in)

    def use(self):
        GL.glUseProgram(self.id)

    def loc(self, name):
        if name not in self._loc:
            self._loc[name] = GL.glGetUniformLocation(self.id, name)
        return self._loc[name]

    def f(self, name, *v):
        if self.cache is not None:
            if self.cache.get(name) == v:
                return
            self.cache[name] = v
        n = len(v)
        (GL.glUniform1f, GL.glUniform2f, GL.glUniform3f, GL.glUniform4f)[n - 1](self.loc(name), *v)

    def i(self, name, v):
        GL.glUniform1i(self.loc(name), v)

    def fv(self, name, arr, comps):
        arr = np.ascontiguousarray(arr, dtype=np.float32)
        fn = {1: GL.glUniform1fv, 2: GL.glUniform2fv, 3: GL.glUniform3fv, 4: GL.glUniform4fv}[comps]
        fn(self.loc(name), arr.size // comps, arr)

    def mat3v(self, name, mats):
        arr = np.ascontiguousarray(mats, dtype=np.float32)
        GL.glUniformMatrix3fv(self.loc(name), arr.size // 9, GL.GL_TRUE, arr)


def program(vs_name, fs_name):
    return Program(read_shader(vs_name), read_shader(fs_name))


class Target:
    """A colour render target (texture + framebuffer)."""

    def __init__(self, w, h, fmt=GL.GL_RGBA8, filt=GL.GL_LINEAR):
        self.w, self.h = w, h
        self.tex = GL.glGenTextures(1)
        GL.glBindTexture(GL.GL_TEXTURE_2D, self.tex)
        GL.glTexImage2D(GL.GL_TEXTURE_2D, 0, fmt, w, h, 0, GL.GL_RGBA, GL.GL_UNSIGNED_BYTE, None)
        for p, v in ((GL.GL_TEXTURE_MIN_FILTER, filt), (GL.GL_TEXTURE_MAG_FILTER, filt),
                     (GL.GL_TEXTURE_WRAP_S, GL.GL_CLAMP_TO_EDGE), (GL.GL_TEXTURE_WRAP_T, GL.GL_CLAMP_TO_EDGE)):
            GL.glTexParameteri(GL.GL_TEXTURE_2D, p, v)
        self.fbo = GL.glGenFramebuffers(1)
        GL.glBindFramebuffer(GL.GL_FRAMEBUFFER, self.fbo)
        GL.glFramebufferTexture2D(GL.GL_FRAMEBUFFER, GL.GL_COLOR_ATTACHMENT0, GL.GL_TEXTURE_2D, self.tex, 0)

    def bind(self):
        GL.glBindFramebuffer(GL.GL_FRAMEBUFFER, self.fbo)
        GL.glViewport(0, 0, self.w, self.h)

    def free(self):
        GL.glDeleteFramebuffers(1, [self.fbo])
        GL.glDeleteTextures([self.tex])


def texture_rgba(data, w, h, fmt=GL.GL_BGRA, filt=GL.GL_LINEAR, mip=False):
    t = GL.glGenTextures(1)
    GL.glBindTexture(GL.GL_TEXTURE_2D, t)
    GL.glPixelStorei(GL.GL_UNPACK_ALIGNMENT, 1)
    GL.glTexImage2D(GL.GL_TEXTURE_2D, 0, GL.GL_RGBA8, w, h, 0, fmt, GL.GL_UNSIGNED_BYTE, data)
    GL.glTexParameteri(GL.GL_TEXTURE_2D, GL.GL_TEXTURE_MIN_FILTER,
                       GL.GL_LINEAR_MIPMAP_LINEAR if mip else filt)
    GL.glTexParameteri(GL.GL_TEXTURE_2D, GL.GL_TEXTURE_MAG_FILTER, filt)
    GL.glTexParameteri(GL.GL_TEXTURE_2D, GL.GL_TEXTURE_WRAP_S, GL.GL_CLAMP_TO_EDGE)
    GL.glTexParameteri(GL.GL_TEXTURE_2D, GL.GL_TEXTURE_WRAP_T, GL.GL_CLAMP_TO_EDGE)
    if mip:
        GL.glGenerateMipmap(GL.GL_TEXTURE_2D)
    return t


def texture_from_cairo(surf, mip=False):
    surf.flush()
    w, h, stride = surf.get_width(), surf.get_height(), surf.get_stride()
    buf = np.frombuffer(surf.get_data(), dtype=np.uint8).reshape(h, stride)[:, :w * 4]
    return texture_rgba(np.ascontiguousarray(buf), w, h, GL.GL_BGRA, mip=mip)


def update_texture_from_cairo(tex, surf):
    surf.flush()
    w, h, stride = surf.get_width(), surf.get_height(), surf.get_stride()
    buf = np.frombuffer(surf.get_data(), dtype=np.uint8).reshape(h, stride)[:, :w * 4]
    GL.glBindTexture(GL.GL_TEXTURE_2D, tex)
    GL.glPixelStorei(GL.GL_UNPACK_ALIGNMENT, 1)
    GL.glTexSubImage2D(GL.GL_TEXTURE_2D, 0, 0, 0, w, h, GL.GL_BGRA, GL.GL_UNSIGNED_BYTE,
                       np.ascontiguousarray(buf))


class Fullscreen:
    """One big triangle; the vertex shader derives it from gl_VertexID."""

    def __init__(self):
        self.vao = GL.glGenVertexArrays(1)

    def draw(self):
        GL.glBindVertexArray(self.vao)
        GL.glDrawArrays(GL.GL_TRIANGLES, 0, 3)


class Instanced:
    """A dynamic instance buffer of N vec4 attributes per instance, drawn as quads."""

    def __init__(self, vs, fs, nvec4):
        self.prog = program(vs, fs)
        self.n = nvec4
        self.vao = GL.glGenVertexArrays(1)
        self.vbo = GL.glGenBuffers(1)
        self.count = 0
        self.cap = 0
        GL.glBindVertexArray(self.vao)
        GL.glBindBuffer(GL.GL_ARRAY_BUFFER, self.vbo)
        stride = nvec4 * 16
        for i in range(nvec4):
            GL.glEnableVertexAttribArray(i)
            GL.glVertexAttribPointer(i, 4, GL.GL_FLOAT, GL.GL_FALSE, stride, ctypes.c_void_p(i * 16))
            GL.glVertexAttribDivisor(i, 1)
        GL.glBindVertexArray(0)

    def upload(self, arr):
        arr = np.ascontiguousarray(arr, dtype=np.float32).reshape(-1, self.n * 4)
        self.count = arr.shape[0]
        GL.glBindBuffer(GL.GL_ARRAY_BUFFER, self.vbo)
        if arr.nbytes > self.cap:
            self.cap = max(arr.nbytes, 4096) * 2
            GL.glBufferData(GL.GL_ARRAY_BUFFER, self.cap, None, GL.GL_DYNAMIC_DRAW)
        if arr.nbytes:
            GL.glBufferSubData(GL.GL_ARRAY_BUFFER, 0, arr.nbytes, arr)

    def draw(self):
        if not self.count:
            return
        GL.glBindVertexArray(self.vao)
        GL.glDrawArraysInstanced(GL.GL_TRIANGLES, 0, 6, self.count)


# ----------------------------------------------------------------- font atlas
GLYPHS = [chr(c) for c in range(32, 127)] + list("·°▲▼►◄◆│─█▮µ→←↑↓±×∝")


class Font:
    """Monospace glyph atlas rendered once with Pango (Geist Mono)."""

    def __init__(self, size, weight, x0, y0, cr_surface, family="Geist Mono"):
        import cairo
        import gi
        gi.require_version("Pango", "1.0")
        gi.require_version("PangoCairo", "1.0")
        from gi.repository import Pango, PangoCairo
        cr = cairo.Context(cr_surface)
        lay = PangoCairo.create_layout(cr)
        fd = Pango.FontDescription.from_string(f"{family}")
        fd.set_absolute_size(size * Pango.SCALE)
        fd.set_weight({"regular": Pango.Weight.NORMAL, "medium": Pango.Weight.MEDIUM,
                       "semibold": Pango.Weight.SEMIBOLD, "bold": Pango.Weight.BOLD}[weight])
        lay.set_font_description(fd)
        lay.set_text("M", -1)
        _, log = lay.get_pixel_extents()
        self.adv = log.width
        self.h = log.height
        fo = Pango.FontMetrics
        metrics = lay.get_context().get_metrics(fd, None)
        self.ascent = metrics.get_ascent() / Pango.SCALE
        self.cell_w = self.adv + 2
        self.cell_h = self.h + 2
        self.uv = {}
        W, H = cr_surface.get_width(), cr_surface.get_height()
        cols = 16
        cr.set_source_rgba(1, 1, 1, 1)
        for i, ch in enumerate(GLYPHS):
            gx = x0 + (i % cols) * self.cell_w
            gy = y0 + (i // cols) * self.cell_h
            lay.set_text(ch, -1)
            _, lg = lay.get_pixel_extents()
            cr.move_to(gx + 1 + (self.adv - lg.width) / 2.0, gy + 1)
            PangoCairo.show_layout(cr, lay)
            self.uv[ch] = (gx / W, gy / H, (gx + self.cell_w) / W, (gy + self.cell_h) / H)
        self.rows = (len(GLYPHS) + cols - 1) // cols
        self.block_w = cols * self.cell_w
        self.block_h = self.rows * self.cell_h
        del fo

    def width(self, s, track=0.0):
        return len(s) * (self.adv + track) - (track if s else 0)


class Atlas:
    SIZES = {"xs": (12, "medium"), "s": (14, "medium"), "m": (17, "semibold"),
             "l": (24, "semibold"), "xl": (40, "semibold"), "xxl": (64, "bold"),
             "cap": (22, "bold")}

    def __init__(self):
        import cairo
        W, H = 2048, 1024
        surf = cairo.ImageSurface(cairo.FORMAT_ARGB32, W, H)
        self.fonts = {}
        x, y, rowh = 0, 0, 0
        for key, (sz, wt) in self.SIZES.items():
            probe = Font(sz, wt, 0, 0, cairo.ImageSurface(cairo.FORMAT_ARGB32, 1, 1))
            if x + probe.block_w > W:
                x, y, rowh = 0, y + rowh, 0
            self.fonts[key] = Font(sz, wt, x, y, surf)
            x += probe.block_w + 4
            rowh = max(rowh, probe.block_h + 4)
        self.tex = texture_from_cairo(surf)


class Batch:
    """Collects instances for lines, arcs and glyphs; uploaded together."""

    def __init__(self, atlas):
        self.atlas = atlas
        self.lines, self.arcs, self.glyphs = [], [], []

    # line: p0 xyz space | p1 xyz width | rgba | part reveal dash glow | space1
    def line(self, p0, p1, c, width=1.0, space=0, part=-1, reveal=0.0, dash=0.0, glow=1.0, space1=None):
        z0 = p0[2] if len(p0) > 2 else 0.0
        z1 = p1[2] if len(p1) > 2 else 0.0
        self.lines.append((p0[0], p0[1], z0, space, p1[0], p1[1], z1, width,
                           c[0], c[1], c[2], c[3], part, reveal, dash, glow,
                           space if space1 is None else space1, 0, 0, 0))

    def polyline(self, pts, c, closed=False, **kw):
        for a, b in zip(pts, pts[1:] + (pts[:1] if closed else [])):
            self.line(a, b, c, **kw)

    def rect(self, x, y, w, h, c, **kw):
        self.polyline([(x, y), (x + w, y), (x + w, y + h), (x, y + h)], c, closed=True, **kw)

    def brackets(self, x, y, w, h, c, l=14, **kw):
        for (cx, cy, dx, dy) in ((x, y, 1, 1), (x + w, y, -1, 1), (x, y + h, 1, -1), (x + w, y + h, -1, -1)):
            self.line((cx, cy), (cx + dx * l, cy), c, **kw)
            self.line((cx, cy), (cx, cy + dy * l), c, **kw)

    # arc: center xyz space | end xyz speed | r0 r1 a0 a1 | segs gap spin phase | rgba | reveal kind part soft
    def arc(self, c, r0, r1, a0, a1, color, segs=0, gap=0.0, spin=0.0, phase=0.0, space=0,
            reveal=0.0, kind=0, part=-1, end=None, speed=0.0, soft=0.0):
        cz = c[2] if len(c) > 2 else 0.0
        e = end or c
        ez = e[2] if len(e) > 2 else 0.0
        self.arcs.append((c[0], c[1], cz, space, e[0], e[1], ez, speed, r0, r1, a0, a1,
                          segs, gap, spin, phase, color[0], color[1], color[2], color[3],
                          reveal, kind, part, soft))

    def plate(self, x, y, w, h, a=0.82):
        """Dark backing for readability (kind 1 = writes coverage into alpha)."""
        self.arcs.append((x + w / 2, y + h / 2, 0, 0, w / 2, h / 2, 0, 0, 0, 0, 0, 0,
                          0, 0, 0, 0, 0, 0, 0, a, 0, 3, -1, 0))

    def disc_plate(self, c, r, a=0.8, space=0):
        self.arc(c, 0, r, 0, 2 * math.pi, (0, 0, 0, a), kind=1, space=space)

    # glyph: anchor xyz space | offx offy w h | uv | rgba | reveal flash 0 0
    def text(self, s, x, y, c, font="s", track=1.0, align="l", space=0, z=0.0,
             reveal=0.0, type_rate=0.0, flash=1.0, dx=0.0, dy=0.0):
        f = self.atlas.fonts[font]
        w = f.width(s, track)
        ox = {"l": 0.0, "c": -w / 2.0, "r": -w}[align] + dx
        if motion.CURRENT != "full":
            flash = 0.0                          # reduced motion: letters appear without a flash
        for i, ch in enumerate(s):
            if ch == " ":
                continue
            uv = f.uv.get(ch) or f.uv["?"]
            rv = reveal + (i * type_rate if type_rate else 0.0) if reveal else 0.0
            self.glyphs.append((x, y, z, space, ox + i * (f.adv + track) - 1, dy - f.ascent - 1,
                                f.cell_w, f.cell_h, uv[0], uv[1], uv[2], uv[3],
                                c[0], c[1], c[2], c[3], rv, flash, 0, 0))
        return w

    def arrays(self):
        return (np.array(self.lines, dtype=np.float32).reshape(-1, 20),
                np.array(self.arcs, dtype=np.float32).reshape(-1, 24),
                np.array(self.glyphs, dtype=np.float32).reshape(-1, 20))


class Painter:
    """Owns the three primitive programs and draws a Batch with shared uniforms."""

    def __init__(self, atlas):
        self.atlas = atlas
        self.lines = Instanced("line.vert", "line.frag", 5)
        self.arcs = Instanced("arc.vert", "arc.frag", 6)
        self.glyphs = Instanced("glyph.vert", "glyph.frag", 5)
        self.rot = np.tile(np.eye(3, dtype=np.float32), (4, 1, 1))
        self.ctr = np.zeros((4, 4), dtype=np.float32)   # x y scale persp
        self.ctr[0] = (0, 0, 1, 0)
        self.parts = np.zeros((32, 4), dtype=np.float32)
        self.parts[:, 0] = 1.0
        self.clip = np.zeros((4, 4), dtype=np.float32)   # per space: x0 y0 x1 y1 px (zero = no clip)

    def upload(self, batch):
        l, a, g = batch.arrays()
        self.lines.upload(l)
        self.arcs.upload(a)
        self.glyphs.upload(g)

    def _uniforms(self, p, res, t, extra):
        p.use()
        p.f("u_res", *res)
        p.f("u_time", t)
        p.mat3v("u_rot", self.rot)
        p.fv("u_ctr", self.ctr, 4)
        p.fv("u_part", self.parts, 4)
        p.fv("u_clip", self.clip, 4)
        p.f("u_fade", extra.get("fade", 1.0))

    def draw(self, res, t, extra=None, which=("arcs", "lines", "glyphs")):
        extra = extra or {}
        for name in which:
            inst = getattr(self, name)
            if not inst.count:
                continue
            self._uniforms(inst.prog, res, t, extra)
            if name == "glyphs":
                GL.glActiveTexture(GL.GL_TEXTURE0)
                GL.glBindTexture(GL.GL_TEXTURE_2D, self.atlas.tex)
                inst.prog.i("u_atlas", 0)
            inst.draw()


def rot_matrix(yaw, pitch, roll=0.0):
    cy, sy = math.cos(yaw), math.sin(yaw)
    cp, sp = math.cos(pitch), math.sin(pitch)
    cr, sr = math.cos(roll), math.sin(roll)
    ry = np.array([[cy, 0, sy], [0, 1, 0], [-sy, 0, cy]], dtype=np.float32)
    rx = np.array([[1, 0, 0], [0, cp, -sp], [0, sp, cp]], dtype=np.float32)
    rz = np.array([[cr, -sr, 0], [sr, cr, 0], [0, 0, 1]], dtype=np.float32)
    flip = np.diag([1, -1, 1]).astype(np.float32)        # model y-up -> screen y-down
    return flip @ rx @ ry @ rz


def project(points, rot, ctr):
    """CPU twin of common.glsl project(): for picking and label layout."""
    v = np.asarray(points, dtype=np.float32) @ rot.T
    persp = ctr[3]
    k = persp / (persp + v[:, 2]) if persp > 0 else np.ones(len(v), dtype=np.float32)
    return np.stack([ctr[0] + v[:, 0] * ctr[2] * k, ctr[1] + v[:, 1] * ctr[2] * k, v[:, 2]], axis=1)
