#!/usr/bin/env python3
"""Offscreen render checks: the den follows a colour theme, plate and all (scene.py's
retint_plate, lib/bromigos_retint.py), and the Wick looks exactly as it did.

Each theme's palette.json is rendered by `bromigos theme set NAME --no-reload` into a
throwaway state dir (an empty PATH: nothing it could run reaches a desktop), and the den
is drawn headless (EGL, as tools/offscreen.py: never a window) at 1920x1080 with the
packaged den, the same fixed clock and data for every theme:

  - the Wick: identical pixels to the den drawn with the plate as it is (no recolour);
  - each colour theme (Cinder, Deepvein, Highwind, Lowtown, Rime, Sunder): the plate
    texture is the theme's (lightness kept, its hue in the bright parts), and the frame
    has no Wick-green room left: under 1% of the coloured pixels are the plate's green;
  - no banding: the frame keeps as many lightness levels as the Wick's (90% or more).

    python3 live/tests/offscreen_retint.py [--out DIR] [--bromigos PATH]
    (DIR: one PNG per theme; exit 1 on a failure)
"""
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
LIVE = os.path.dirname(HERE)
REPO = os.path.dirname(LIVE)

SANDBOX = tempfile.mkdtemp(prefix="bromigos-retint-")
for k in ("WAYLAND_DISPLAY", "HYPRLAND_INSTANCE_SIGNATURE", "DISPLAY", "DBUS_SESSION_BUS_ADDRESS",
          "BROMIGOS_WORLD", "BROMIGOS_LIVE_CONFIG", "BROMIGOS_LIVE_PLUGINS", "BROMIGOS_HOMELAB",
          "BROMIGOS_VECTOR"):
    os.environ.pop(k, None)
for k, sub in (("HOME", ""), ("XDG_CONFIG_HOME", ".config"), ("XDG_STATE_HOME", ".local/state"),
               ("XDG_DATA_HOME", ".local/share"), ("XDG_CACHE_HOME", ".cache"), ("XDG_RUNTIME_DIR", "run")):
    os.environ[k] = os.path.join(SANDBOX, sub)
    os.makedirs(os.environ[k], exist_ok=True)
os.environ["BROMIGOS_SHARE_DIR"] = REPO
os.environ["PYOPENGL_PLATFORM"] = "egl"
sys.path.insert(0, LIVE)
sys.path.insert(0, os.path.join(REPO, "lib"))

import importlib.util  # noqa: E402

import numpy as np  # noqa: E402
from OpenGL import GL  # noqa: E402

W, H = 1920, 1080
THEMES = ("wick", "cinder", "deepvein", "highwind", "lowtown", "rime", "sunder")
DEN = os.path.join(REPO, "desktop/wallpaper/bromigos-den-empty-2560x1440.jpg")
failures, lines = [], []


def report(name, ok, detail):
    lines.append(f"{'PASS' if ok else 'FAIL'}  {name}: {detail}")
    if not ok:
        failures.append(name)


def egl():
    spec = importlib.util.spec_from_file_location("offscreen", os.path.join(LIVE, "tools", "offscreen.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    mod.egl()


def palette_json(theme, bromigos):
    """The theme's palette.json, rendered by bromigos into its own throwaway state dir."""
    state = os.path.join(SANDBOX, "state-" + theme)
    empty = os.path.join(SANDBOX, "empty-path")
    os.makedirs(empty, exist_ok=True)
    env = {"HOME": os.environ["HOME"], "XDG_STATE_HOME": state, "XDG_CONFIG_HOME": os.environ["XDG_CONFIG_HOME"],
           "XDG_RUNTIME_DIR": os.environ["XDG_RUNTIME_DIR"], "BROMIGOS_SHARE_DIR": REPO, "PATH": empty}
    subprocess.run([bromigos, "theme", "set", theme, "--no-reload"], env=env, check=True, capture_output=True)
    return os.path.join(state, "bromigos", "theme", "current", "palette.json")


def use_theme(path):
    import bromigos_theme as T
    T.PATH = path
    T._checked = float("-inf")              # read it now, whatever the (fixed) clock says
    T.version(0.0)
    return T


def render(retint=True):
    import time
    time.monotonic = lambda: 1000.0          # every clock fixed: the same frame on every run
    from live import config as C, cover, glkit, motion, scene
    from live.data import Data
    cfg = C.load()
    cfg["general"]["motion"] = "full"
    cfg["background"]["underlay"] = DEN
    motion.set_current("full")
    d = Data({}, lambda *a, **k: None)
    d.s.update(cpu=35.0, gpu=12.0, mem=40.0, rx=2.0e5, tx=4.0e4)
    saved = scene.retint_plate
    if not retint:
        scene.retint_plate = lambda raw: raw
    try:
        r = cover.wrap(lambda cw, ch: scene.Background(cfg, d, cw, ch), W, H)
    finally:
        scene.retint_plate = saved
    bg = getattr(r, "inner", r)
    r.now = lambda: 2.0
    r.loop_clock = lambda: 2.0
    tgt = glkit.Target(W, H)
    r.render(tgt.fbo, 30)
    GL.glBindFramebuffer(GL.GL_FRAMEBUFFER, tgt.fbo)
    frame = np.frombuffer(GL.glReadPixels(0, 0, W, H, GL.GL_RGB, GL.GL_UNSIGNED_BYTE), np.uint8)
    frame = frame.reshape(H, W, 3)[::-1].copy()
    GL.glBindTexture(GL.GL_TEXTURE_2D, bg.under)
    GL.glPixelStorei(GL.GL_PACK_ALIGNMENT, 1)
    plate = np.frombuffer(GL.glGetTexImage(GL.GL_TEXTURE_2D, 0, GL.GL_RGB, GL.GL_UNSIGNED_BYTE), np.uint8)
    plate = plate.reshape(bg.h, bg.w, 3).copy()
    tgt.free()
    getattr(r, "close", lambda: None)()
    return frame, plate


def oklab(img):
    import bromigos_retint as R
    return R.lin_to_oklab(R.to_linear(img.reshape(-1, 3).astype(np.float32) / 255.0))


def main():
    out = sys.argv[sys.argv.index("--out") + 1] if "--out" in sys.argv else None
    bromigos = sys.argv[sys.argv.index("--bromigos") + 1] if "--bromigos" in sys.argv else next(
        (p for p in (os.path.join(REPO, "core/target/debug/bromigos"), os.path.join(REPO, "core/target/release/bromigos"),
                     shutil.which("bromigos") or "") if p and os.path.exists(p)), "bromigos")
    if out:
        os.makedirs(out, exist_ok=True)
    egl()
    import bromigos_retint as R
    try:
        paths = {t: palette_json(t, bromigos) for t in THEMES}
        use_theme(paths["wick"])
        wick, wick_plate = render()
        asis, asis_plate = render(retint=False)
        report("wick: the den as it was", np.array_equal(wick, asis) and np.array_equal(wick_plate, asis_plate),
               f"frames differ in {int((wick != asis).any(axis=2).sum())} pixels, plates in "
               f"{int((wick_plate != asis_plate).any(axis=2).sum())}")
        wl = oklab(wick)
        wick_levels = len(np.unique(np.rint(wl[:, 0] * 1000)))
        wpl = oklab(wick_plate)
        if out:
            from PIL import Image
            Image.fromarray(wick).save(os.path.join(out, "den-wick.png"))
        for t in THEMES[1:]:
            T = use_theme(paths[t])
            frame, plate = render()
            pl = oklab(plate)
            dl = float(np.percentile(np.abs(pl[:, 0] - wpl[:, 0]), 99))
            p = oklab(np.asarray([[int(T.hex("primary")[i:i + 2], 16) for i in (1, 3, 5)]], np.uint8))[0]
            bright = wpl[:, 0] > 0.55
            hue = np.degrees(np.arctan2(pl[bright, 2], pl[bright, 1]))
            dh = float(np.median(np.abs((hue - np.degrees(np.arctan2(p[2], p[1])) + 180) % 360 - 180)))
            report(f"{t}: the plate in its colours", dl < 0.02 and dh < 25,
                   f"lightness kept (p99 off by {dl:.4f}), bright parts {dh:.1f}° from its primary")
            fl = oklab(frame)
            c = np.hypot(fl[:, 1], fl[:, 2])
            h = np.degrees(np.arctan2(fl[:, 2], fl[:, 1])) % 360
            coloured = c > 0.03
            green = coloured & (np.abs((h - R.GREEN_HUE + 180) % 360 - 180) < 20)
            share = float(green.sum() / max(coloured.sum(), 1))
            report(f"{t}: no Wick-green room left", share < 0.01, f"{share:.2%} of coloured pixels are the plate's green")
            levels = len(np.unique(np.rint(fl[:, 0] * 1000)))
            report(f"{t}: no banding", levels >= 0.9 * wick_levels,
                   f"{levels} lightness levels (the Wick's {wick_levels})")
            if out:
                from PIL import Image
                Image.fromarray(frame).save(os.path.join(out, f"den-{t}.png"))
    finally:
        shutil.rmtree(SANDBOX, ignore_errors=True)
    print("\n".join(lines))
    print(f"\n{len(lines) - len(failures)}/{len(lines)} checks pass" + (f"; failed: {', '.join(failures)}" if failures else ""))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
