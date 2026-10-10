#!/usr/bin/env python3
"""Switch Wick -> Cinder -> Wick on existing den and radial surfaces, headless EGL.
Runs the daemon's frame handler in a sandbox; no desktop socket, theme or window.
The switched frames must equal freshly constructed scenes in the new palette.
"""
import ast
import os
import random
import shutil
import time
from types import SimpleNamespace as NS

import offscreen_retint as R
from OpenGL import GL
import numpy as np


def main():
    R.egl()
    from live import config, glkit, motion, overlays, scene
    from live.data import Data
    path = os.path.join(R.LIVE, 'live', 'app.py')
    tree = ast.parse(open(path).read())
    node = next(n for c in tree.body if isinstance(c, ast.ClassDef) and c.name == 'GLWindow'
                for n in c.body if isinstance(n, ast.FunctionDef) and n.name == '_render')
    ns = dict(glkit=glkit, GL=GL, time=time, log=print)
    exec(compile(ast.Module(body=[node], type_ignores=[]), path, 'exec'), ns)
    draw = ns['_render']
    bromigos = '/usr/bin/bromigos'
    paths = {t: R.palette_json(t, bromigos) for t in ('wick', 'cinder')}
    cfg = config.load()
    cfg['background']['underlay'] = R.DEN
    cfg['general']['motion'] = 'full'
    motion.set_current('full')
    data = Data({}, lambda *a, **k: None)
    data.s.update(cpu=35., gpu=12., mem=40., rx=2e5, tx=4e4)
    time.monotonic = lambda: 1000.
    area = NS(get_scale_factor=lambda: 1, get_allocated_width=lambda: R.W,
              get_allocated_height=lambda: R.H)
    target = glkit.Target(R.W, R.H)
    out = '/tmp/bromigos-palette-switch'
    os.makedirs(out, exist_ok=True)
    from PIL import Image
    try:
        for name, cls in [('den', scene.Background), ('radial', overlays.Radial)]:
            def make(w, h):
                random.seed(1)
                np.random.seed(1)
                r = cls(cfg, data, w, h)
                r.now = lambda: 2.
                r.loop_clock = lambda: 2.
                return r
            app = NS(bg=None)
            win = NS(renderer=None, rsize=None, failed=False, frames=5, fps=30,
                     app=app, make_renderer=make)
            win._close_renderer = lambda: getattr(win.renderer, 'close', lambda: None)()
            previous = None
            for theme in ('wick', 'cinder', 'wick'):
                R.use_theme(paths[theme])
                target.bind()
                draw(win, area, None)
                GL.glBindFramebuffer(GL.GL_FRAMEBUFFER, target.fbo)
                frame = np.frombuffer(GL.glReadPixels(0, 0, R.W, R.H, GL.GL_RGB, GL.GL_UNSIGNED_BYTE), np.uint8).copy()
                fresh = make(R.W, R.H)
                fresh.render(target.fbo, 30)
                GL.glBindFramebuffer(GL.GL_FRAMEBUFFER, target.fbo)
                reference = np.frombuffer(GL.glReadPixels(0, 0, R.W, R.H, GL.GL_RGB, GL.GL_UNSIGNED_BYTE), np.uint8)
                assert np.array_equal(frame, reference), f'{name}: stale pixels after switch to {theme} ({np.count_nonzero(frame != reference)} channels differ)'
                if previous is not None:
                    assert np.count_nonzero(frame != previous) > 10000, f'{name}: hue did not change'
                previous = frame.copy()
                Image.fromarray(frame.reshape(R.H, R.W, 3)[::-1]).save(f'{out}/{name}-{theme}.png')
                getattr(fresh, 'close', lambda: None)()
                print(f'PASS {name}: switch to {theme} matches a fresh scene')
            win._close_renderer()
    finally:
        target.free()
        shutil.rmtree(R.SANDBOX, ignore_errors=True)


if __name__ == '__main__':
    main()
