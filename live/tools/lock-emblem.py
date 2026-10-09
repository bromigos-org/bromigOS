#!/usr/bin/env python3
"""Render the burn-in's turning ring as a seamless loop of PNG frames for the lock screen.

  lock-emblem.py [OUT_DIR] [--fps N] [--turn SECONDS] [--size S] [--emblem E]
  lock-emblem.py --layers OUT_DIR      ring.png + flame.png, still, for gtklock (it turns the ring in CSS)
  ... --kit DIR                         draw that emblem kit (a theme's emblem/) instead of the current one

hyprlock can't play an animation, but an image widget with reload_time = 0 reloads on
SIGUSR2; bromigos-lock-anim flips it through these frames while the screen is locked.
The emblem is the live layer's own (the intercept's settled state: ring, flame and mast
lit, the ring turning; slower here than the desktop's 24 s), drawn with its bloom on a transparent
canvas; the glow becomes alpha so it lies over the lock wallpaper as it does on the desktop.

Defaults: OUT_DIR ~/.cache/bromigos/lock-emblem, one turn in 36 s at 24 fps (864 lossless
WebP frames, ~80 MB: about 1.5 px of travel per frame at the ring, which reads as smooth;
12 fps at 24 s judders), a 560 px canvas with a 400 px emblem (the size of the static logo
it replaces at hyprlock size = 560). Each frame gets its own mtime.
"""
import argparse
import importlib.util
import math
import os
import sys
import time

import numpy as np

HERE = os.path.dirname(os.path.realpath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
os.environ["PYOPENGL_PLATFORM"] = "egl"

TAU = 2 * math.pi


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("out", nargs="?", default=os.path.expanduser("~/.cache/bromigos/lock-emblem"))
    ap.add_argument("--fps", type=int, default=24)
    ap.add_argument("--turn", type=float, default=36.0, help="seconds per revolution (the desktop's is 24)")
    ap.add_argument("--size", type=int, default=560)
    ap.add_argument("--emblem", type=int, default=400)
    ap.add_argument("--layers", action="store_true", help="two still layers (ring, flame+mast) instead of a loop")
    ap.add_argument("--kit", help="an emblem kit directory (default: the current theme's, else brand/)")
    a = ap.parse_args()

    spec = importlib.util.spec_from_file_location("offscreen", os.path.join(HERE, "offscreen.py"))
    off = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(off)
    off.egl()

    from OpenGL import GL
    from PIL import Image

    from live import config, glkit
    if a.kit:
        from live import emblem as kit_mod
        kit_mod.kit = lambda: os.path.abspath(a.kit)
    from live.data import Data
    from live.overlays import Base

    S, E = a.size, a.emblem
    m = (S - E) / 2

    part = {"ring": 1.0, "flame": 1.0}

    class LockEmblem(Base):
        name = "lock-emblem"
        rebuild_every = 1e9

        def frame(self, t, d):
            return {"backdrop": 0.0, "gadget_fade": 0.0, "glow": 0.6,
                    "emblems": [{"rect": (m, m, E, E), "angle": -t * TAU / a.turn, "ring_t": part["ring"],
                                 "flame_t": part["flame"], "mast_t": part["flame"], "alpha": 1.0, "gain": 1.0}]}

    cfg = config.load()
    data = Data(cfg, lambda *x, **k: None)          # not started: the emblem needs no readings
    r = LockEmblem(cfg, data, S, S)
    tgt = glkit.Target(S, S)
    clock = {"t": 0.0}
    r.now = lambda: clock["t"]

    def grab():
        GL.glBindFramebuffer(GL.GL_FRAMEBUFFER, tgt.fbo)
        GL.glViewport(0, 0, S, S)
        GL.glClearColor(0, 0, 0, 0)
        GL.glClear(GL.GL_COLOR_BUFFER_BIT)
        r.render(tgt.fbo, a.fps)
        GL.glBindFramebuffer(GL.GL_FRAMEBUFFER, tgt.fbo)
        px = GL.glReadPixels(0, 0, S, S, GL.GL_RGBA, GL.GL_UNSIGNED_BYTE)
        img = np.frombuffer(px, dtype=np.uint8).reshape(S, S, 4)[::-1].astype(np.float32)
        alpha = img[..., :3].max(axis=2)          # light on black -> colour + alpha
        rgb = np.where(alpha[..., None] > 0, img[..., :3] * 255.0 / np.maximum(alpha[..., None], 1), 0)
        return Image.fromarray(np.dstack([rgb, alpha]).clip(0, 255).astype(np.uint8), "RGBA")

    os.makedirs(a.out, exist_ok=True)
    if a.layers:                                  # gtklock: the ring turns in CSS, the flame holds still
        for name, ring, flame in (("ring", 1.0, 0.0), ("flame", 0.0, 1.0)):
            part.update(ring=ring, flame=flame)
            clock["t"] = 0.0
            grab().save(os.path.join(a.out, f"{name}.png"), optimize=True)
        print(f"ring.png + flame.png, {S}px -> {a.out}", flush=True)
        os._exit(0)
    for f in os.listdir(a.out):
        if f.startswith("f") and f.endswith((".png", ".webp")):
            os.unlink(os.path.join(a.out, f))
    n = int(round(a.turn * a.fps))
    base = time.time() - n - 10
    for i in range(n):
        clock["t"] = i / a.fps
        GL.glBindFramebuffer(GL.GL_FRAMEBUFFER, tgt.fbo)
        GL.glViewport(0, 0, S, S)
        GL.glClearColor(0, 0, 0, 0)
        GL.glClear(GL.GL_COLOR_BUFFER_BIT)
        r.render(tgt.fbo, a.fps)
        GL.glBindFramebuffer(GL.GL_FRAMEBUFFER, tgt.fbo)
        px = GL.glReadPixels(0, 0, S, S, GL.GL_RGBA, GL.GL_UNSIGNED_BYTE)
        img = np.frombuffer(px, dtype=np.uint8).reshape(S, S, 4)[::-1].astype(np.float32)
        # light on black -> colour + alpha: alpha is the brightest channel, colour un-premultiplied
        alpha = img[..., :3].max(axis=2)
        rgb = np.where(alpha[..., None] > 0, img[..., :3] * 255.0 / np.maximum(alpha[..., None], 1), 0)
        out = np.dstack([rgb, alpha]).clip(0, 255).astype(np.uint8)
        path = os.path.join(a.out, f"f{i:04d}.webp")
        Image.fromarray(out, "RGBA").save(path, "WEBP", lossless=True, method=4)   # half a PNG's size, faster to decode
        os.utime(path, (base + i, base + i))
    with open(os.path.join(a.out, "loop.txt"), "w") as fh:
        fh.write(f"fps={a.fps}\nframes={n}\nturn={a.turn}\next=webp\nsize={S}\nemblem={E}\n")
    print(f"{n} frames at {a.fps} fps, {S}px -> {a.out}", flush=True)
    os._exit(0)                                       # the data threads were never started; skip GL teardown


if __name__ == "__main__":
    main()
