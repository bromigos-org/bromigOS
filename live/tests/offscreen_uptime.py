#!/usr/bin/env python3
"""Offscreen check: the shaders' random numbers after days of uptime.

The live layer's shaders pick glyphs, stars, dust and grain with sine hashes (hash1/hash2
in shaders/rain.glsl, w_hash* in world_common.glsl), and several of those are fed with the
time. A graphics card's sin() stops telling large numbers apart, so on a wallpaper that had
been up for about three days every hash came out the same: the rain was all one glyph (a
T), the dust lined up in a grid, the grain stood still. This renders the hashes the scene
uses at 30 seconds, 4 days, 30 days and 120 days of uptime, headless (EGL, the same
context as tools/offscreen.py: never a window, never the running desktop), and checks that
they stay as varied as they are at the start.

    python3 live/tests/offscreen_uptime.py          # exit 1 on a failure

Without the graphics card, under Mesa's software renderer:
    EGL_PLATFORM=surfaceless LIBGL_ALWAYS_SOFTWARE=1 python3 live/tests/offscreen_uptime.py

The rule that keeps new hashes safe, without a GPU: tests/test_uptime.py.
"""
import importlib.util
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
LIVE = os.path.dirname(HERE)
for k in ("WAYLAND_DISPLAY", "HYPRLAND_INSTANCE_SIGNATURE", "DISPLAY"):
    os.environ.pop(k, None)
os.environ["PYOPENGL_PLATFORM"] = "egl"
os.environ.setdefault("BROMIGOS_SHARE_DIR", os.path.dirname(LIVE))
sys.path.insert(0, LIVE)

import numpy as np  # noqa: E402
from OpenGL import GL  # noqa: E402

W, H = 256, 96                      # one pixel per cell: 24,576 cells
DAY = 86400.0
UPTIMES = (("30 seconds", 30.0), ("4 days", 4 * DAY), ("30 days", 30 * DAY), ("120 days", 120 * DAY))

VS = """#version 330 core
void main() {
    const vec2 c[3] = vec2[3](vec2(-1, -1), vec2(3, -1), vec2(-1, 3));
    gl_Position = vec4(c[gl_VertexID], 0.0, 1.0);
}
"""

# One output per kind of use in the scene, each written the way the scene writes it:
#   r  the rain's glyph in this cell (rain.glsl rain_glyph), as glyph / 255
#   g  the den's film grain (bg.frag): a cell plus a count of time steps
#   b  the dust in the sky (space.glsl): a cell of a field that drifts with the time
#   a  a world's rain streaks (world.frag): a cell of a field that falls with the time
FS = """#version 330 core
out vec4 o;
uniform float u_time;
uniform vec4 u_rain_rect;
uniform vec4 u_rain;
uniform vec4 u_burst[6];
#include rain
#include world_common
void main() {
    vec2 ci = floor(gl_FragCoord.xy);
    float glyph = float(rain_glyph(ci)) / 255.0;
    float grain = hash2(ci + hwrap(floor(u_time * 20.0)));
    float dust = hash2(floor((gl_FragCoord.xy * 26.0 + vec2(u_time * 9.0, -u_time * 3.0)) / 26.0) * 1.31 + 5.0);
    float streak = w_hash2(floor(ci + vec2(0.0, -u_time * 7.5)));
    o = vec4(glyph, grain, dust, streak);
}
"""


def egl():
    spec = importlib.util.spec_from_file_location("offscreen", os.path.join(LIVE, "tools", "offscreen.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    mod.egl()


def render(prog, tgt, t):
    tgt.bind()
    prog.use()
    prog.f("u_time", t)
    GL.glDrawArrays(GL.GL_TRIANGLES, 0, 3)
    px = GL.glReadPixels(0, 0, W, H, GL.GL_RGBA, GL.GL_UNSIGNED_BYTE)
    return np.frombuffer(px, dtype=np.uint8).reshape(H, W, 4)


def check_glyphs(img):
    """Nearly all 24 glyphs in use, none of them taking over."""
    g = img[..., 0].ravel()
    counts = np.bincount(g, minlength=24)[:24]
    used = int((counts > 0).sum())
    top = counts.max() / g.size
    ok = used >= 22 and top < 0.10 and int(g.max()) < 24
    return ok, f"glyphs {used}/24 in use, the commonest on {top:.0%} of cells"


def check_hash(img, ch, name):
    """A hash: spread over the whole range, around one half, cells unlike their neighbours."""
    v = img[..., ch].astype(np.float32) / 255.0
    levels = len(np.unique(img[..., ch]))
    mean = float(v.mean())
    same = float((img[:, 1:, ch] == img[:, :-1, ch]).mean())       # a cell equal to the one beside it
    ok = levels >= 200 and 0.45 < mean < 0.55 and same < 0.05
    return ok, f"{name} {levels} levels, mean {mean:.2f}, {same:.0%} equal to the next cell"


def main():
    egl()
    from live import glkit
    prog = glkit.Program(VS, FS)
    vao = GL.glGenVertexArrays(1)
    GL.glBindVertexArray(vao)
    tgt = glkit.Target(W, H, filt=GL.GL_NEAREST)
    failed = False
    for label, t in UPTIMES:
        img = render(prog, tgt, t)
        results = [check_glyphs(img), check_hash(img, 1, "grain"), check_hash(img, 2, "dust"),
                   check_hash(img, 3, "streaks")]
        for ok, text in results:
            failed |= not ok
            print(f"{'ok  ' if ok else 'FAIL'} {label:>10}: {text}")
        # the glyphs still change as they fall: one mutation period later, most cells differ
        later = render(prog, tgt, t + 2.0)
        changed = float((later[..., 0] != img[..., 0]).mean())
        ok = changed > 0.5
        failed |= not ok
        print(f"{'ok  ' if ok else 'FAIL'} {label:>10}: {changed:.0%} of cells show another glyph 2 s later")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
