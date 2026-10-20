#!/usr/bin/env python3
"""Check the rotating emblem's rim in a surfaceless EGL context.

    python3 live/tests/offscreen_emblem.py --out /tmp/emblem-frames

Uses a throwaway HOME, no windows and no data pollers. Set EGL_PLATFORM=surfaceless
and __EGL_VENDOR_LIBRARY_FILENAMES to Mesa's vendor JSON to test a Mesa GPU; the
offscreen tool otherwise prefers NVIDIA. --shader can compare an older shader.
"""
import argparse
import importlib.util
import json
import math
import os
from pathlib import Path
import sys
import tempfile


REPO = Path(__file__).resolve().parents[2]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--shader", type=Path)
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    shader = args.shader.read_text() if args.shader else None
    with tempfile.TemporaryDirectory(prefix="bromigos-emblem-") as sandbox:
        for key in ("DISPLAY", "WAYLAND_DISPLAY", "HYPRLAND_INSTANCE_SIGNATURE",
                    "DBUS_SESSION_BUS_ADDRESS", "BROMIGOS_WORLD", "BROMIGOS_LIVE_CONFIG",
                    "BROMIGOS_LIVE_PLUGINS", "BROMIGOS_HOMELAB", "BROMIGOS_VECTOR"):
            os.environ.pop(key, None)
        for key, sub in (("HOME", ""), ("XDG_CONFIG_HOME", "config"), ("XDG_STATE_HOME", "state"),
                         ("XDG_DATA_HOME", "data"), ("XDG_CACHE_HOME", "cache"), ("XDG_RUNTIME_DIR", "run")):
            os.environ[key] = str(Path(sandbox) / sub)
            Path(os.environ[key]).mkdir(exist_ok=True)
        os.environ["BROMIGOS_SHARE_DIR"] = str(REPO)
        os.environ["PYOPENGL_PLATFORM"] = "egl"
        sys.path.insert(0, str(REPO / "live"))
        spec = importlib.util.spec_from_file_location("offscreen", REPO / "live/tools/offscreen.py")
        offscreen = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(offscreen)
        offscreen.egl()
        check(out, shader)


def check(out, shader):
    import cairo
    import numpy as np
    from OpenGL import GL
    from live import config, glkit, overlays
    from live.data import Data
    from live.emblem import Emblem
    from live.stage import Stage

    def pixels(target):
        GL.glBindFramebuffer(GL.GL_FRAMEBUFFER, target.fbo)
        raw = GL.glReadPixels(0, 0, target.w, target.h, GL.GL_RGBA, GL.GL_UNSIGNED_BYTE)
        return np.frombuffer(raw, np.uint8).reshape(target.h, target.w, 4)[::-1].copy()

    def save(name, image):
        bgra = np.ascontiguousarray(image[..., [2, 1, 0, 3]])
        bgra[..., 3] = 255
        h, w = image.shape[:2]
        cairo.ImageSurface.create_for_data(bgra, cairo.FORMAT_ARGB32, w, h).write_to_png(str(out / name))

    stage = Stage(900, 900, "ov.frag")
    if shader:
        stage.emblem = glkit.Program(glkit.read_shader("quad.vert"), shader)
    emblem = Emblem(kit_dir=str(REPO / "themes/wick/emblem"))
    target = glkit.Target(900, 900)
    y, x = np.mgrid[:900, :900]
    radius = np.hypot(x + 0.5 - 450, y + 0.5 - 450)
    results = []
    for size in (210, 420, 560, 561.6, 748.8):
        # Only the circular outer rim: letters and dial ticks should rotate.
        rim = (radius > size / 2 - 1.5) & (radius < size / 2 + 0.5)
        baseline = None
        worst = 0
        for degrees in range(0, 360, 15):
            target.bind()
            GL.glDisable(GL.GL_BLEND)
            GL.glClearColor(0, 0, 0, 0)
            GL.glClear(GL.GL_COLOR_BUFFER_BIT)
            stage.draw_emblem(emblem, ((900 - size) / 2, (900 - size) / 2, size, size),
                              math.radians(degrees))
            image = pixels(target)
            if degrees in (0, 45, 90):
                save(f"rim-{size}-{degrees}.png", image)
            green = image[..., 1].astype(np.int16)
            if baseline is None:
                baseline = green
            else:
                worst = max(worst, int(np.abs(green - baseline)[rim].max()))
        # Ordinary texture resampling changes a few shades. Broken mip selection
        # creates bright/dark notches (up to 220/255 on the reproducing AMD GPU).
        results.append({"diameter": size, "largest_rim_change": worst, "passed": worst < 80})

    # An opaque texture isolates the circular clipping edge from SVG antialiasing.
    # The edge itself must have partial coverage, rather than an on/off staircase.
    solid = np.full((64, 64, 4), 255, np.uint8)
    texture = glkit.texture_rgba(solid, 64, 64, fmt=GL.GL_RGBA, mip=True)
    from types import SimpleNamespace
    target.bind()
    stage.draw_emblem(SimpleNamespace(ring=texture, flame=None), (170, 170, 560, 560), 0.5)
    image = pixels(target)
    inside_edge = (radius > 279.25) & (radius < 280)
    partial = float(((image[..., 3] > 0) & (image[..., 3] < 250))[inside_edge].mean())
    results.append({"circular_mask_partial_coverage": partial, "passed": partial > 0.7})
    GL.glDeleteTextures([texture])
    target.free()

    # Render both real consumers, with fixed readings and no desktop capture.
    data = Data({}, lambda *a, **k: None)
    data.s.update(cpu=35.0, gpu=12.0, mem=40.0)
    cfg = config.load()
    cfg["general"].update(motion="full", reduced_motion=False)

    class DemoIntercept(overlays.Intercept):
        def _syslines(self):
            return ["BROMIGOS · OFFSCREEN RENDER"]

    full = glkit.Target(2560, 1440)
    for name, kind in (("screensaver", overlays.Screensaver), ("unlock", DemoIntercept)):
        renderer = kind(cfg, data, 2560, 1440)
        if shader:
            renderer.stage.emblem = glkit.Program(glkit.read_shader("quad.vert"), shader)
        renderer.now = lambda: 3.0
        renderer.render(full.fbo, 30)
        save(name + ".png", pixels(full))
    full.free()
    report = {"renderer": GL.glGetString(GL.GL_RENDERER).decode(), "checks": results}
    (out / "results.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))
    if not all(result["passed"] for result in results):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
