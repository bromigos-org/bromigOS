#!/usr/bin/env python3
"""Offscreen render checks for reduced motion (live/motion.py, docs/accessibility.md).

Renders the den, a world (Mire), the unlock/login intercept, the critical-notification
transmission and the screensaver headless (EGL, the same context as tools/offscreen.py:
never a window, never the running desktop) under each motion setting, and checks what a
viewer would see, frame by frame at 30 fps:

  - full motion animates; reduced animates less; still holds one frame (identical pixels);
  - reduced and still have no flashes: no tile of the screen (a 4x4 grid) changes relative
    luminance by 0.10 or more (WCAG 2.3.1's "general flash" step) from one frame to the next,
    lightning and the intercept's cut included (full motion shows they would);
  - reduced and still have no parallax: moving the pointer moves nothing;
  - the intercept under reduced and still has no static or tearing (its tear uniform stays 0,
    and frames change only as a crossfade does).

Everything runs in a throwaway HOME and runtime dir; the data is a fixed reading (the
pollers aren't started), so runs repeat.

    python3 live/tests/offscreen_motion.py [--out DIR]   # DIR: sample PNGs; exit 1 on a failure
"""
import os
import shutil
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
LIVE = os.path.dirname(HERE)
REPO = os.path.dirname(LIVE)

# ---- a sandbox, before anything reads the environment
SANDBOX = tempfile.mkdtemp(prefix="bromigos-motion-")
for k in ("WAYLAND_DISPLAY", "HYPRLAND_INSTANCE_SIGNATURE", "DISPLAY", "DBUS_SESSION_BUS_ADDRESS",
          "BROMIGOS_WORLD", "BROMIGOS_LIVE_CONFIG", "BROMIGOS_LIVE_PLUGINS", "BROMIGOS_HOMELAB",
          "BROMIGOS_VECTOR"):
    os.environ.pop(k, None)
for k, sub in (("HOME", ""), ("XDG_CONFIG_HOME", ".config"), ("XDG_STATE_HOME", ".local/state"),
               ("XDG_DATA_HOME", ".local/share"), ("XDG_CACHE_HOME", ".cache"), ("XDG_RUNTIME_DIR", "run")):
    os.environ[k] = os.path.join(SANDBOX, sub)
    os.makedirs(os.environ[k], exist_ok=True)
os.environ["BROMIGOS_SHARE_DIR"] = REPO
os.environ["BROMIGOS_WORLD_SYNC"] = "1"          # video loops: every frame, as rendered
os.environ["PYOPENGL_PLATFORM"] = "egl"
sys.path.insert(0, LIVE)

import importlib.util  # noqa: E402
import random  # noqa: E402

import numpy as np  # noqa: E402
from OpenGL import GL  # noqa: E402

W, H = 960, 540
FPS = 30
STEP = 0.10                     # WCAG 2.3.1: a change of 10% of relative luminance
TILES = 4                       # a 4x4 grid: each tile 1/16 of the screen

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


def linear(img):
    c = img[..., :3].astype(np.float32) / 255.0
    return np.where(c <= 0.04045, c / 12.92, ((c + 0.055) / 1.055) ** 2.4)


def tiles(img):
    """Relative luminance per tile (TILES x TILES)."""
    y = linear(img) @ np.array([0.2126, 0.7152, 0.0722], np.float32)
    h, w = y.shape
    return y[:h - h % TILES, :w - w % TILES].reshape(TILES, h // TILES, TILES, w // TILES).mean(axis=(1, 3))


class Run:
    """Frames of one renderer: per-frame change and the biggest tile step."""

    def __init__(self, r, under=None):
        from live import glkit
        self.r, self.under = r, under
        self.tgt = glkit.Target(W, H)
        self.prev = None
        self.prev_t = None
        self.diffs, self.steps, self.frames = [], [], []

    def frame(self, t, keep=False):
        self.r.render(self.tgt.fbo, FPS)
        GL.glBindFramebuffer(GL.GL_FRAMEBUFFER, self.tgt.fbo)
        px = GL.glReadPixels(0, 0, W, H, GL.GL_RGBA, GL.GL_UNSIGNED_BYTE)
        img = np.frombuffer(px, dtype=np.uint8).reshape(H, W, 4)[::-1].copy()
        if self.under is not None:                 # an overlay, over the desktop it covers
            a = img[..., 3:4].astype(np.float32) / 255.0
            img[..., :3] = np.clip(img[..., :3].astype(np.float32) + self.under[..., :3] * (1.0 - a), 0, 255)
            img[..., 3] = 255
        tl = tiles(img)
        if self.prev is not None:
            self.diffs.append(float(np.abs(img[..., :3].astype(np.int16) - self.prev[..., :3]).mean()))
            self.steps.append(float(np.abs(tl - self.prev_t).max()))
        self.prev, self.prev_t = img, tl
        if keep:
            self.frames.append(img)
        return img


def run_frames(r, t0, t1, clock, under=None, keep=(), each=None):
    run = Run(r, under)
    n = int(round((t1 - t0) * FPS))
    for i in range(n + 1):
        t = t0 + i / FPS
        clock[0] = t
        if each:
            each(t)
        run.frame(t, keep=i in keep)
    return run


def hook(r, clock):
    r.now = lambda: clock[0]
    if hasattr(r, "loop_clock"):
        r.loop_clock = lambda: clock[0]


def config(mode):
    from live import config as C, motion
    cfg = C.load()
    cfg["general"]["motion"] = mode
    cfg["general"]["reduced_motion"] = mode != "full"
    cfg["background"]["underlay"] = os.path.join(REPO, "desktop/wallpaper/bromigos-den-empty-2560x1440.jpg")
    motion.set_current(mode)
    return cfg


class FakeFeed:
    """The world's herdr/VECTOR/models feed, standing still (nothing polled)."""

    def __init__(self, data):
        self.agents, self.working, self.models, self.vector = [], 0, None, "idle"

    def start(self):
        pass

    def halt(self):
        pass


def data():
    from live.data import Data
    d = Data({}, lambda *a, **k: None)             # not started: a fixed reading
    d.s.update(cpu=35.0, gpu=12.0, mem=40.0, rx=2.0e5, tx=4.0e4)
    return d


def world(mode, verbs=(), cursor=(0.0, 0.0)):
    from live import activity, cover, world as Wd, worldfeed
    worldfeed.Feed = FakeFeed
    random.seed(7)
    np.random.seed(7)
    act = activity.get()
    act.forced, act.cur = "working", cursor
    cfg = config(mode)
    path = os.path.join(REPO, "themes/mire/live/world.toml")
    r = cover.wrap(lambda cw, ch: Wd.World(cfg, data(), cw, ch, path), W, H)
    r.offscreen = True
    for v in verbs:
        verb, _, rest = v.partition(" ")
        r.command(verb, rest)
    return r


def save(out, name, img):
    if not out:
        return
    import cairo
    rgba = np.ascontiguousarray(img[..., [2, 1, 0, 3]])
    rgba[..., 3] = 255
    cairo.ImageSurface.create_for_data(memoryview(rgba), cairo.FORMAT_ARGB32, W, H).write_to_png(
        os.path.join(out, name + ".png"))


def check_den(out):
    from live import cover
    from live.scene import Background
    res = {}
    for mode in ("full", "reduced", "still"):
        clock = [0.0]
        cfg = config(mode)
        r = cover.wrap(lambda cw, ch: Background(cfg, data(), cw, ch), W, H)
        hook(r, clock)
        # a notification and a workspace switch half-way: rain bursts and the wipe
        fired = []

        def each(t):
            if t >= 1.5 and not fired:
                fired.append(1)
                r.burst(2)
                r.wipe()
        run = run_frames(r, 0.0, 4.0, clock, keep=(60,), each=each)
        res[mode] = run
        save(out, f"den-{mode}", run.frames[0])
    f, rd, st = (np.mean(res[m].diffs) for m in ("full", "reduced", "still"))
    report("den: full motion animates", f > 0.05, f"mean change {f:.3f}/frame")
    report("den: reduced animates less", 0 < rd < f, f"mean change {rd:.3f}/frame (full {f:.3f})")
    report("den: still holds one frame", max(res["still"].diffs) == 0.0,
           f"largest change {max(res['still'].diffs):.4f}/frame over {len(res['still'].diffs)} frames")
    for m in ("reduced", "still"):
        s = max(res[m].steps)
        report(f"den: {m}: no flash (a notification's burst, a workspace wipe)", s < STEP,
               f"largest tile step {s:.4f} (< {STEP})")


def check_world(out):
    res = {}
    for mode in ("full", "reduced", "still"):
        clock = [0.0]
        r = world(mode, verbs=("set hour 22.5", "set agents a:working,b:needs_you"))
        hook(r, clock)
        run = run_frames(r, 0.0, 3.0, clock, keep=(45,))
        res[mode] = run
        held = max(run.diffs)
        save(out, f"mire-{mode}", run.frames[0])
        if mode == "still":
            # a new still frame when what it shows changes: an agent finishes
            r.command("set", "agents a:finished,b:needs_you")
            changed = r.still_due()
            r.still_tick()
            clock[0] += 1.0 / FPS
            before = run.prev.copy()
            img = run.frame(clock[0])
            moved = float(np.abs(img[..., :3].astype(np.int16) - before[..., :3]).mean())
            still_held = held
            report("mire: still: a change is drawn as a new frame", changed and moved > 0,
                   f"still_due {changed}, the new frame differs by {moved:.3f}")
            # and holds again
            again = run_frames(r, clock[0] + 1 / FPS, clock[0] + 1.0, clock)
            report("mire: still: the new frame holds", max(again.diffs) == 0.0,
                   f"largest change {max(again.diffs):.4f}")
        r.close()
    f, rd = np.mean(res["full"].diffs), np.mean(res["reduced"].diffs)
    report("mire: full motion animates", f > 0.05, f"mean change {f:.3f}/frame")
    report("mire: reduced animates less", 0 < rd < f, f"mean change {rd:.3f}/frame (full {f:.3f})")
    report("mire: still holds one frame", still_held == 0.0, f"largest change {still_held:.4f}/frame")

    # lightning: a storm by day, so a flash is a real luminance step
    steps = {}
    for mode in ("full", "reduced"):
        clock = [0.0]
        r = world(mode, verbs=("set hour 13", "set cpu 0.97", "set health 2"))
        hook(r, clock)
        run = run_frames(r, 0.0, 8.0, clock)
        steps[mode] = max(run.steps)
        r.close()
    report("mire: full motion's lightning is a flash (the check sees it)", steps["full"] >= STEP,
           f"largest tile step {steps['full']:.3f}")
    report("mire: reduced: no lightning flash", steps["reduced"] < STEP,
           f"largest tile step {steps['reduced']:.4f} (< {STEP})")

    # parallax: the same scene with the pointer at the centre and at a corner
    for mode in ("full", "reduced"):
        last = []
        for cur in ((0.0, 0.0), (0.95, 0.6)):
            clock = [0.0]
            r = world(mode, verbs=("set hour 22.5",), cursor=cur)
            hook(r, clock)
            run = run_frames(r, 0.0, 2.0, clock)
            last.append(run.prev)
            r.close()
        d = float(np.abs(last[0][..., :3].astype(np.int16) - last[1][..., :3]).mean())
        if mode == "full":
            report("mire: full motion has parallax (the check sees it)", d > 0.5, f"pointer moved: frames differ by {d:.3f}")
        else:
            report("mire: reduced: no parallax", d == 0.0, f"pointer moved: frames differ by {d:.4f}")


def desktop():
    """A bright, busy captured screen for the intercept to start from."""
    y, x = np.mgrid[0:H, 0:W]
    img = np.zeros((H, W, 4), np.uint8)
    img[..., 0] = (120 + 100 * np.sin(x / 37.0)).astype(np.uint8)
    img[..., 1] = (160 + 80 * np.cos(y / 23.0)).astype(np.uint8)
    img[..., 2] = 200
    img[(y // 24) % 3 == 0] = (240, 240, 240, 255)       # lines of "text"
    img[..., 3] = 255
    return img


def check_overlays(out):
    from live import overlays
    under = desktop()
    for mode in ("full", "reduced", "still"):
        clock = [0.0]
        cfg = config(mode)
        r = overlays.Intercept(cfg, data(), W, H, frozen_rgb=np.ascontiguousarray(under[..., :3]))
        hook(r, clock)
        tears = []
        orig = r.frame

        def frame(t, d, orig=orig):
            u = orig(t, d)
            tears.append(u.get("tear", 0.0))
            return u
        r.frame = frame
        run = run_frames(r, 0.0, r.t_end + 0.2, clock, under=under, keep=(20, 100))
        for i, img in enumerate(run.frames):
            save(out, f"intercept-{mode}-{i}", img)
        tear_win = [d for k, d in enumerate(run.diffs) if r.t_tear <= (k + 1) / FPS < r.t_ring]
        s = max(run.steps)
        if mode == "full":
            report("intercept: full motion tears and cuts (the check sees it)", max(tears) > 0 and s >= STEP,
                   f"tear up to {max(tears):.2f}, largest tile step {s:.3f}, "
                   f"change while tearing {np.mean(tear_win):.2f}/frame")
            full_tear = np.mean(tear_win)
        else:
            report(f"intercept: {mode}: no static or tearing", max(tears) == 0.0,
                   f"tear stays {max(tears):.1f}; change while it would tear {np.mean(tear_win):.2f}/frame "
                   f"(full {full_tear:.2f})")
            report(f"intercept: {mode}: no flash (no black frame, no cut)", s < STEP,
                   f"largest tile step {s:.4f} (< {STEP})")

    for mode in ("full", "reduced"):
        clock = [0.0]
        r = overlays.Transmission(config(mode), data(), W, H, rect=(W - 440, 60, 400, 96), summary="TEST")
        hook(r, clock)
        run = run_frames(r, 0.0, 1.5, clock, under=under)
        if mode == "reduced":
            s = max(run.steps)
            report("transmission: reduced: no interference band or pulsing edge", s < STEP,
                   f"largest tile step {s:.4f}")

    clock = [0.0]
    overlays.time.strftime = lambda fmt, *a: "12:00"       # its clock text: no minute ticking over mid-run
    r = overlays.Screensaver(config("still"), data(), W, H)
    hook(r, clock)
    run = run_frames(r, 0.0, 3.0, clock)
    held = run.diffs[int(1.0 * FPS):]                     # after its fade in
    report("screensaver: still holds one frame", max(held) == 0.0, f"largest change {max(held):.4f}/frame")


def main():
    out = None
    if "--out" in sys.argv:
        out = sys.argv[sys.argv.index("--out") + 1]
        os.makedirs(out, exist_ok=True)
    egl()
    try:
        check_den(out)
        check_world(out)
        check_overlays(out)
    finally:
        shutil.rmtree(SANDBOX, ignore_errors=True)
    print("\n".join(lines))
    print(f"\n{len(lines) - len(failures)}/{len(lines)} checks pass" + (f"; failed: {', '.join(failures)}" if failures else ""))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
