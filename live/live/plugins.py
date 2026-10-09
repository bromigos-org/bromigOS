"""Live-layer plugins: background shader layers and decks, without touching core files.

Shader layers (<plugins>/layers/<name>.frag + <name>.json; docs/plugins.md)
  Opt-in: a layer draws only when its JSON says "enabled": true. Drawn over the finished
  background (behind every window), additively by default, at the background's own
  frame rate. Contract for the fragment shader (GLSL 330 core):
      in vec2 v_uv;            // 0..1, origin bottom-left
      out vec4 frag;           // premultiplied; with blend "add" only rgb counts
      uniform vec2  u_res;     // pixels
      uniform float u_time;    // seconds
      uniform float u_opacity; // the JSON's opacity
      uniform vec4  u_load;    // cpu, gpu, memory, vram (0..1, real readings)
      uniform vec4  u_net;     // rx, tx (log-scaled 0..1), rx_hist_peak, tx_hist_peak
      uniform float u_health;  // 0 all green, 1 hot or stale, 2 something down
      uniform vec4  u_rect;    // x, y, w, h in pixels (the JSON's rect or the screen)
  JSON: {"enabled": false, "opacity": 0.6, "blend": "add"|"alpha", "rect": [x,y,w,h],
         "budget_ms": 1.0, "title": "...", "hint": "what it shows"}.
  Budget: each layer's GPU time is measured with timer queries every frame; when its
  average over ~2 s exceeds budget_ms, or its shader fails to compile, it is switched off
  (logged, in the health file) until its files change. A broken layer never stops the
  background.

Deck plugins (<plugins>/decks/<name>.py)
  A module defining DECK = <a class built on deckkit>; opened with `bromigos-live plugin
  <name> [verb args]`. A deck that raises stops drawing and closes (GLWindow's guard);
  the host carries on. See the hologram-build skill for how decks are written.

<plugins> is each folder in live.PLUGINS (~/.config/bromigos/plugins/live), then the old
~/.config/bromigos-live/{layers,plugins}; the first folder with a name wins.

Health: $XDG_RUNTIME_DIR/bromigos-live-plugins.json (layers: status, gpu_ms, errors).
Offscreen: `python -m live.plugins test-layer <name|path.frag> OUT.png` compiles a layer
on the GPU headless, renders it over a dark plate with sample readings, and reports its
GPU time.
"""
import importlib.util
import json
import os
import sys
import time
import traceback

import numpy as np
from OpenGL import GL

from . import PLUGINS  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
_LEGACY = os.path.join(os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config"), "bromigos-live")
LAYER_DIRS = [os.path.join(d, "layers") for d in PLUGINS] + [os.path.join(_LEGACY, "layers")]
DECK_DIRS = [os.path.join(d, "decks") for d in PLUGINS] + [os.path.join(_LEGACY, "plugins")]


def _found(dirs, ext):
    """{name: path} for every <dir>/<name><ext>; the first folder with a name wins."""
    out = {}
    for d in dirs:
        if os.path.isdir(d):
            for f in sorted(os.listdir(d)):
                if f.endswith(ext) and not f.startswith(("_", ".")):
                    out.setdefault(f[:-len(ext)], os.path.join(d, f))
    return out
RUN = os.environ.get("XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}")
HEALTH = os.path.join(RUN, "bromigos-live-plugins.json")
LOG = os.path.expanduser("~/.local/state/bromigos/live-plugins.log")
VS = """#version 330 core
out vec2 v_uv;
void main() {
    vec2 p = vec2((gl_VertexID << 1) & 2, gl_VertexID & 2);
    v_uv = p;
    gl_Position = vec4(p * 2.0 - 1.0, 0.0, 1.0);
}
"""


def log(name, msg):
    os.makedirs(os.path.dirname(LOG), exist_ok=True)
    with open(LOG, "a") as f:
        f.write(f"{time.strftime('%Y-%m-%dT%H:%M:%S')} {name}: {msg.rstrip()}\n")


def _sig(dirs, ext):
    out = []
    for d in dirs:
        if os.path.isdir(d):
            for f in sorted(os.listdir(d)):
                if f.endswith(ext) or f.endswith(".json"):
                    try:
                        out.append((d, f, os.path.getmtime(os.path.join(d, f))))
                    except OSError:
                        pass
    return tuple(out)


def _meta(name, frag=None):
    frag = frag or _found(LAYER_DIRS, ".frag").get(name, name + ".frag")
    try:
        with open(frag[:-5] + ".json") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


class Layer:
    def __init__(self, name, src, meta):
        from .glkit import Program
        self.name, self.meta = name, meta
        self.prog = Program(VS, src)
        self.vao = GL.glGenVertexArrays(1)
        self.q = GL.glGenQueries(2)
        self.qi = 0
        self.primed = [False, False]
        self.ms = []
        self.off = None

    def draw(self, w, h, t, u):
        m = self.meta
        if self.primed[self.qi]:                       # read last-but-one frame's GPU time
            buf = np.zeros(1, np.uint32)               # nanoseconds; 32 bits hold ~4 s, plenty for one draw
            GL.glGetQueryObjectuiv(self.q[self.qi], GL.GL_QUERY_RESULT, buf)
            self.ms = (self.ms + [float(buf[0]) / 1e6])[-60:]
        GL.glBeginQuery(GL.GL_TIME_ELAPSED, self.q[self.qi])
        GL.glEnable(GL.GL_BLEND)
        if m.get("blend", "add") == "alpha":
            GL.glBlendFunc(GL.GL_ONE, GL.GL_ONE_MINUS_SRC_ALPHA)
        else:
            GL.glBlendFunc(GL.GL_ONE, GL.GL_ONE)
        p = self.prog
        p.use()
        rect = m.get("rect") or [0, 0, w, h]
        p.f("u_res", float(w), float(h))
        p.f("u_time", float(t))
        p.f("u_opacity", float(m.get("opacity", 0.6)))
        p.f("u_load", *u["load"])
        p.f("u_net", *u["net"])
        p.f("u_health", float(u["health"]))
        p.f("u_rect", *[float(x) for x in rect])
        GL.glBindVertexArray(self.vao)
        GL.glDrawArrays(GL.GL_TRIANGLES, 0, 3)
        GL.glDisable(GL.GL_BLEND)
        GL.glEndQuery(GL.GL_TIME_ELAPSED)
        self.primed[self.qi] = True
        self.qi ^= 1
        budget = float(m.get("budget_ms", 1.0))
        if len(self.ms) >= 60 and sum(self.ms) / len(self.ms) > budget:
            self.off = f"over its GPU budget: {sum(self.ms) / len(self.ms):.2f} ms a frame (budget {budget} ms)"
            log(self.name, "switched off: " + self.off)

    def gpu_ms(self):
        return round(sum(self.ms) / len(self.ms), 3) if self.ms else None


class Layers:
    """Owned by the Background; draw() after its final composite, into the same target."""

    def __init__(self):
        self.sig = None
        self.layers = {}       # name -> Layer
        self.failed = {}       # name -> reason (compile errors, budget)
        self.checked = 0.0
        self.health_at = 0.0

    def _reload(self):
        sig = _sig(LAYER_DIRS, ".frag")
        if sig == self.sig:
            return
        self.sig = sig
        self.layers, self.failed = {}, {}
        for name, path in _found(LAYER_DIRS, ".frag").items():
            meta = _meta(name, path)
            if not meta.get("enabled", False):
                continue                                # opt-in
            try:
                with open(path) as fh:
                    self.layers[name] = Layer(name, fh.read(), meta)
                log(name, "loaded")
            except Exception as e:
                self.failed[name] = f"compile: {str(e).strip().splitlines()[0][:200]}"
                log(name, "failed:\n" + traceback.format_exc())

    @staticmethod
    def uniforms(d, gadgets):
        lv = lambda v: max(0.0, min(1.0, np.log10(1 + (v or 0.0)) / 7.5))  # noqa: E731
        g = lambda k: max(0.0, min(1.0, (d.get(k) or 0.0) / 100.0))          # noqa: E731
        rx, tx = d.get("rx_hist") or [0], d.get("tx_hist") or [0]
        return {"load": (g("cpu"), g("gpu"), g("mem"), g("vram")),
                "net": (lv(d.get("rx")), lv(d.get("tx")), lv(max(rx)), lv(max(tx))),
                "health": float(gadgets.health(d))}

    def draw(self, fbo, w, h, t, d):
        try:
            now = time.monotonic()
            if now - self.checked > 2.0:
                self.checked = now
                self._reload()
            if self.layers:
                from . import gadgets
                u = self.uniforms(d, gadgets)
                GL.glBindFramebuffer(GL.GL_FRAMEBUFFER, fbo)
                GL.glViewport(0, 0, w, h)
                for name, L in list(self.layers.items()):
                    if L.off:
                        self.failed[name] = L.off
                        del self.layers[name]
                        continue
                    try:
                        L.draw(w, h, t, u)
                    except Exception as e:
                        self.failed[name] = f"draw: {type(e).__name__}: {str(e)[:160]}"
                        log(name, "draw failed:\n" + traceback.format_exc())
                        del self.layers[name]
            if now - self.health_at > 2.0:
                self.health_at = now
                self._health()
        except Exception:
            log("layers", "failed:\n" + traceback.format_exc())

    def _health(self):
        d = {"t": time.time(), "pid": os.getpid(),
             "layers": {**{n: {"status": "on", "gpu_ms": L.gpu_ms(), "budget_ms": L.meta.get("budget_ms", 1.0)}
                           for n, L in self.layers.items()},
                        **{n: {"status": "off", "reason": r} for n, r in self.failed.items()}}}
        tmp = HEALTH + ".tmp"
        with open(tmp, "w") as f:
            json.dump(d, f)
        os.replace(tmp, HEALTH)


# ------------------------------------------------------------------ decks
def deck_names():
    return sorted(_found(DECK_DIRS, ".py"))


def deck_class(name):
    path = _found(DECK_DIRS, ".py").get(name, "")
    if not os.path.isfile(path):
        raise KeyError(f"no deck plugin {name!r}")
    mod_name = f"bromigos_live_plugin_{name}_{int(os.path.getmtime(path) * 1000)}"
    spec = importlib.util.spec_from_file_location(mod_name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[mod_name] = mod
    spec.loader.exec_module(mod)
    cls = getattr(mod, "DECK", None)
    if cls is None:
        raise TypeError(f"{name}.py defines no DECK")
    return cls


# ------------------------------------------------------------------ offscreen test
def test_layer(target, out, w=1280, h=720, frames=90):
    """Compile and render one layer headless; -> stats. Uses the live offscreen EGL context."""
    sys.path.insert(0, ROOT)
    from tools.offscreen import egl
    egl()
    path = target if target.endswith(".frag") else _found(LAYER_DIRS, ".frag")[target]
    name = os.path.basename(path)[:-5]
    meta = dict(_meta(name, path), enabled=True)
    with open(path) as f:
        L = Layer(name, f.read(), meta)
    from .glkit import Target
    tgt = Target(w, h)
    u = {"load": (0.45, 0.6, 0.5, 0.4), "net": (0.55, 0.3, 0.7, 0.5), "health": 0.0}
    t0 = time.perf_counter()
    for i in range(frames):
        tgt.bind()
        GL.glViewport(0, 0, w, h)
        GL.glClearColor(0.0, 0.02, 0.0, 1.0)
        GL.glClear(GL.GL_COLOR_BUFFER_BIT)
        L.draw(w, h, 4.0 + i / 30.0, u)
    GL.glFinish()
    wall = (time.perf_counter() - t0) * 1000 / frames
    tgt.bind()
    px = GL.glReadPixels(0, 0, w, h, GL.GL_RGBA, GL.GL_UNSIGNED_BYTE)
    img = np.frombuffer(px, np.uint8).reshape(h, w, 4)[::-1, :, :3]
    from PIL import Image
    Image.fromarray(img).save(out)
    lit = float((img.max(axis=2) > 40).mean())
    return {"out": out, "size": [w, h], "gpu_ms": L.gpu_ms(), "wall_ms_per_frame": round(wall, 3),
            "budget_ms": meta.get("budget_ms", 1.0), "lit_fraction": round(lit, 3),
            "within_budget": (L.gpu_ms() or 0) <= float(meta.get("budget_ms", 1.0))}


if __name__ == "__main__":
    if len(sys.argv) >= 4 and sys.argv[1] == "test-layer":
        print(json.dumps(test_layer(sys.argv[2], sys.argv[3])))
    else:
        sys.exit("usage: python -m live.plugins test-layer <name|path.frag> OUT.png")
