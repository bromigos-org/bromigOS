#!/usr/bin/env python3
"""Offscreen render checks: the live background's underlay at screen sizes whose rows
aren't 4-aligned, and at the usual odd ones (live/pixbuf.py).

GdkPixbuf pads each row to 4 bytes except the last, so the underlay failed to load on a
1280x800 screen (its 16:9 cover is 1422 wide: 4266 bytes a row) and on 1366x768. Each
size below gets the den two ways: the packaged den (an approved variant: the clean plate,
scaled) and an image that isn't one (a PNG with alpha: loaded and scaled straight). For
each it checks:

  - the underlay loaded (the scene has its texture, no fault);
  - the texture GL holds is the picture, row for row: read back and compared with the
    same picture scaled independently (PIL), a sheared or shifted row would show;
  - the rendered screen is the picture's cover crop (the scene's effects on top): its
    luminance, block by block, correlates with the reference's.

Headless (EGL, the same context as tools/offscreen.py: never a window, never the running
desktop), in a throwaway HOME and runtime dir; the data is a fixed reading.

    python3 live/tests/offscreen_sizes.py [--out DIR]   # DIR: the frames as PNGs; exit 1 on a failure
"""
import os
import shutil
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
LIVE = os.path.dirname(HERE)
REPO = os.path.dirname(LIVE)

# ---- a sandbox, before anything reads the environment
SANDBOX = tempfile.mkdtemp(prefix="bromigos-sizes-")
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
sys.path.insert(0, HERE)

import importlib.util  # noqa: E402

import numpy as np  # noqa: E402
from OpenGL import GL  # noqa: E402
from PIL import Image  # noqa: E402

# 16:10 (cover 1422 wide), the common laptop (1366: unaligned, within 1% of 16:9 so not
# covered), 16:9, 16:10 again (cover 2133), and two ultrawides (cover taller than the screen)
SIZES = [(1280, 800), (1366, 768), (1600, 900), (1920, 1200), (2560, 1080), (3440, 1440)]
DEN = os.path.join(REPO, "desktop/wallpaper/bromigos-den-empty-2560x1440.jpg")

failures = []
lines = []


def report(name, ok, detail):
    lines.append(f"{'PASS' if ok else 'FAIL'}  {name}: {detail}")
    if not ok:
        failures.append(name)


def egl():
    spec = importlib.util.spec_from_file_location("offscreen", os.path.join(LIVE, "tools", "offscreen.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    mod.egl()


def config(underlay):
    from live import config as C, motion
    cfg = C.load()
    cfg["general"]["motion"] = "still"                 # one frame, no effects moving under the check
    cfg["general"]["reduced_motion"] = True
    cfg["background"]["underlay"] = underlay
    cfg["background"]["underlay_fallback"] = ""
    motion.set_current("still")
    return cfg


def data():
    from live.data import Data
    d = Data({}, lambda *a, **k: None)                 # not started: a fixed reading
    d.s.update(cpu=35.0, gpu=12.0, mem=40.0, rx=2.0e5, tx=4.0e4)
    return d


def texture(tex, w, h):
    """What GL holds in the texture, top row first, (h, w, 3)."""
    GL.glBindTexture(GL.GL_TEXTURE_2D, tex)
    GL.glPixelStorei(GL.GL_PACK_ALIGNMENT, 1)
    px = GL.glGetTexImage(GL.GL_TEXTURE_2D, 0, GL.GL_RGB, GL.GL_UNSIGNED_BYTE)
    return np.frombuffer(px, np.uint8).reshape(h, w, 3)


def blocks(img, n=(18, 32)):
    """Mean relative luminance in an n[0] x n[1] grid."""
    y = img[..., :3].astype(np.float32) @ np.array([0.2126, 0.7152, 0.0722], np.float32)
    h, w = y.shape
    by, bx = h // n[0], w // n[1]
    return y[:by * n[0], :bx * n[1]].reshape(n[0], by, n[1], bx).mean(axis=(1, 3))


def corr(a, b):
    a, b = a.ravel() - a.mean(), b.ravel() - b.mean()
    return float(a @ b / (np.linalg.norm(a) * np.linalg.norm(b) + 1e-9))


def save(out, name, img):
    if out:
        Image.fromarray(np.ascontiguousarray(img[..., :3])).save(os.path.join(out, name + ".png"))


def check(out, name, path, reference, w, h):
    """The den from `path` on a w x h screen; `reference(cw, ch)` is the underlay it should
    hold, scaled independently."""
    from live import cover, glkit
    from live.scene import Background
    cfg = config(path)
    tag = f"{name} {w}x{h}"
    try:
        r = cover.wrap(lambda cw, ch: Background(cfg, data(), cw, ch), w, h)
    except Exception as e:                                  # the bug: a reshape that doesn't fit
        report(f"{tag}: the underlay loads", False, f"{type(e).__name__}: {e}")
        return
    bg = getattr(r, "inner", r)
    cw, ch = bg.w, bg.h
    report(f"{tag}: the underlay loads", bg.under is not None,
           f"scene {cw}x{ch}" + (f" (cover of {w}x{h})" if (cw, ch) != (w, h) else "") +
           f", rows of {cw * 3} bytes ({'not ' if (cw * 3) % 4 else ''}4-aligned)")
    if bg.under is None:
        return
    ref = reference(cw, ch)
    got = texture(bg.under, cw, ch)
    diff = np.abs(got.astype(np.int16) - ref.astype(np.int16)).mean(axis=2)
    rows = diff.mean(axis=1)
    report(f"{tag}: the texture is the picture, row for row", float(rows.max()) < 6.0 and float(diff.mean()) < 3.0,
           f"mean difference {diff.mean():.2f} levels, worst row {rows.max():.2f} (row {int(rows.argmax())})")
    clock = [0.0]
    r.now = lambda: clock[0]
    if hasattr(r, "loop_clock"):
        r.loop_clock = lambda: clock[0]
    tgt = glkit.Target(w, h)
    r.render(tgt.fbo, 30)
    GL.glBindFramebuffer(GL.GL_FRAMEBUFFER, tgt.fbo)
    px = GL.glReadPixels(0, 0, w, h, GL.GL_RGBA, GL.GL_UNSIGNED_BYTE)
    frame = np.frombuffer(px, np.uint8).reshape(h, w, 4)[::-1, :, :3]
    x0 = getattr(r, "x0", 0)
    y0 = (ch - h - getattr(r, "y0", 0)) if (cw, ch) != (w, h) else 0     # the cover's window, top-down
    crop = ref[y0:y0 + h, x0:x0 + w]
    c = corr(blocks(frame), blocks(crop))
    report(f"{tag}: the screen shows it (the cover's crop)", c > 0.85 and frame.mean() > 8,
           f"block luminance correlation {c:.3f}, mean level {frame.mean():.1f}")
    save(out, f"{name}-{w}x{h}", frame)
    try:
        tgt.free()
        r.close()
    except Exception:
        pass


def main():
    out = None
    if "--out" in sys.argv:
        out = sys.argv[sys.argv.index("--out") + 1]
        os.makedirs(out, exist_ok=True)
    egl()
    from live import plate
    try:
        # the packaged den: an approved variant, so the clean plate (built once, cached in the sandbox)
        cfg = config(DEN)
        v1 = os.path.expanduser(cfg["background"].get("den_plate", "") or "")
        lp = cfg.get("loops", {})
        import hashlib
        with open(DEN, "rb") as f:
            variant = (cfg["background"].get("den_plates") or {}).get(hashlib.sha1(f.read()).hexdigest())
        report("the packaged den is an approved variant (the clean plate's path)", variant is not None, f"variant {variant}")
        img, _, _ = plate.clean_plate(DEN, v1, steam=variant in (lp.get("steam") or []),
                                      streaks=bool(lp.get("streaks", True)), rows=bool(lp.get("rows", True)))
        clean = Image.fromarray(img)

        # an image that isn't a den variant, with alpha: the straight load (transparency over black)
        other = os.path.join(SANDBOX, "not-a-den.png")
        im = Image.open(DEN).convert("RGBA").resize((1999, 1123), Image.BILINEAR)   # odd, to be scaled
        a = np.array(im)
        a[:, :, 3] = 255
        a[: a.shape[0] // 3, : a.shape[1] // 3, 3] = 128                          # a translucent corner
        Image.fromarray(a).save(other)
        flat = a[..., :3].astype(np.float32) * (a[..., 3:4] / 255.0)
        other_ref = Image.fromarray(np.clip(flat + 0.5, 0, 255).astype(np.uint8))

        for w, h in SIZES:
            check(out, "den", DEN, lambda cw, ch: np.array(clean.resize((cw, ch), Image.BILINEAR)), w, h)
            check(out, "other", other, lambda cw, ch: np.array(other_ref.resize((cw, ch), Image.BILINEAR)), w, h)
    finally:
        shutil.rmtree(SANDBOX, ignore_errors=True)
    print("\n".join(lines))
    print(f"\n{len(lines) - len(failures)}/{len(lines)} checks pass" + (f"; failed: {', '.join(failures)}" if failures else ""))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
