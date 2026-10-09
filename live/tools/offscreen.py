#!/usr/bin/env python3
"""Render the live layer headless (EGL pbuffer) to PNG frames or a video, with
real readings, without touching the desktop. For screenshots and tuning.

  offscreen.py bg OUT.png [t]             one background frame at time t
  offscreen.py bg OUT.mp4 SECONDS [fps]   a background clip (ffmpeg)
  offscreen.py <overlay> OUT ...          same for holodeck|intercept|screensaver|radial|transmission
  offscreen.py world OUT ...              a theme's world (OFF_WORLD = the theme directory, default
                                          the current theme), with real readings unless scripted
  offscreen.py bench SECONDS [world|bg]   render in real time at 30 fps and report the cost
                                          (OFF_BENCH_W="event flyby; set cpu 0.1": world verbs first)

OFF_SCRIPT drives it with timed steps ("at verb args; ..."): burst, select, cmd (a VECTOR
verb), event, key, part, notes, scan, pin, radial, and for the zoomable maps
wheel X Y DY, dclick X Y, drag X0 Y0 X1 Y1 [shift|right], hover X Y (2560x1440 coords).
OFF_MOTION=full|reduced|still renders under that motion setting (docs/accessibility.md)
instead of the user's; `w still` (worlds) draws a new still frame.
For worlds: w <verb> <args> runs a world verb (live/world.py World.command), e.g.
  "0 w set agents a:working,b:working; 4 w set agents a:needs_you,b:working; 6 w event critical;
   8 w event fill win; 9 w set user dozing; 10 w set cpu 0.95; 12 w set hour 19.2"
"""
import ctypes
import os
import subprocess
import sys
import time

os.environ["PYOPENGL_PLATFORM"] = "egl"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.realpath(__file__))))

from OpenGL import EGL, GL  # noqa: E402
import numpy as np  # noqa: E402

W, H = int(os.environ.get("OFF_W", 2560)), int(os.environ.get("OFF_H", 1440))


def egl():
    """A surfaceless GL 3.3 core context on the NVIDIA EGL device (falls back to
    the default display, i.e. Mesa software, when there is no device platform)."""
    attrs = [EGL.EGL_CONTEXT_MAJOR_VERSION, 3, EGL.EGL_CONTEXT_MINOR_VERSION, 3,
             EGL.EGL_CONTEXT_OPENGL_PROFILE_MASK, EGL.EGL_CONTEXT_OPENGL_CORE_PROFILE_BIT, EGL.EGL_NONE]
    dpy = None
    try:
        from OpenGL.EGL.EXT.device_base import eglQueryDevicesEXT
        from OpenGL.EGL.EXT.platform_base import eglGetPlatformDisplayEXT
        from OpenGL.EGL.EXT.platform_device import EGL_PLATFORM_DEVICE_EXT
        devs = (EGL.EGLDeviceEXT * 8)()
        n = EGL.EGLint()
        eglQueryDevicesEXT(8, devs, ctypes.byref(n))
        for i in range(n.value):
            d = eglGetPlatformDisplayEXT(EGL_PLATFORM_DEVICE_EXT, devs[i], None)
            if EGL.eglInitialize(d, None, None) and b"NVIDIA" in (EGL.eglQueryString(d, EGL.EGL_VENDOR) or b""):
                dpy = d
                break
    except Exception:
        dpy = None
    if dpy is None:
        dpy = EGL.eglGetDisplay(EGL.EGL_DEFAULT_DISPLAY)
        EGL.eglInitialize(dpy, None, None)
    EGL.eglBindAPI(EGL.EGL_OPENGL_API)
    cfg = EGL.EGLConfig()
    n = EGL.EGLint()
    EGL.eglChooseConfig(dpy, [EGL.EGL_SURFACE_TYPE, EGL.EGL_PBUFFER_BIT, EGL.EGL_RENDERABLE_TYPE, EGL.EGL_OPENGL_BIT,
                              EGL.EGL_NONE], ctypes.byref(cfg), 1, ctypes.byref(n))
    ctx = EGL.eglCreateContext(dpy, cfg, EGL.EGL_NO_CONTEXT, attrs)
    EGL.eglMakeCurrent(dpy, EGL.EGL_NO_SURFACE, EGL.EGL_NO_SURFACE, ctx)
    print("offscreen GL:", GL.glGetString(GL.GL_RENDERER).decode(), file=sys.stderr)


def main():
    kind, out = sys.argv[1], sys.argv[2]
    egl()
    from live import config, glkit, motion
    from live.data import Data
    cfg = config.load()
    if os.environ.get("OFF_MOTION") in motion.MODES:       # render under another motion setting
        cfg["general"]["motion"] = os.environ["OFF_MOTION"]
        cfg["general"]["reduced_motion"] = os.environ["OFF_MOTION"] != "full"
    motion.set_current(motion.mode(cfg))
    data = Data(cfg, lambda *a, **k: None)
    data.start()
    time.sleep(float(os.environ.get("OFF_WARM", 3.5)))
    if kind == "codec":                         # a real call, voiced by the lab's TTS
        from live import overlays
        from live.codec import Call, Desk

        class _App:
            locked = fullscreen = False
            pass
        shim = _App()
        shim.cfg = cfg
        desk = Desk(shim)
        call = Call(os.environ.get("OFF_CH", "FLOOR"), os.environ.get("OFF_TEXT", "Floor here. Paper fill: buy open DBC, 352 dollars. Cause: rebalance."))
        desk._prepare(call)
        overlays.OFF_CALL["call"] = call
        if call.wav:
            import shutil
            shutil.copy(call.wav, out.rsplit(".", 1)[0] + ".wav")
    if kind == "bench":
        return bench(cfg, data)
    if kind == "bg":
        from live.scene import Background
        from live import cover
        r = cover.wrap(lambda cw, ch: Background(cfg, data, cw, ch), W, H)   # the daemon's fit
    elif kind == "world":
        r = make_world(cfg, data)
    else:
        from live import overlays
        r = overlays.offscreen(kind, cfg, data, W, H)
    if hasattr(getattr(r, "feed", None), "snapshot"):   # a deck with a feed: wait for its first full read
        t_end = time.time() + 40
        while time.time() < t_end:
            d, *_ = r.feed.snapshot()
            if all(k in d for k in ("roster", "road", "now", "overview", "trades", "positions")) and r.feed.bars:
                break
            time.sleep(0.5)
    if hasattr(r, "ready"):                     # decks: wait for their first real data
        t_end = time.time() + float(os.environ.get("OFF_READY", 90))
        while time.time() < t_end and not r.ready():
            time.sleep(0.5)
    tgt = glkit.Target(W, H)
    clock = {"t": 0.0}
    r.now = lambda: clock["t"]
    if hasattr(r, "loop_clock"):
        r.loop_clock = lambda: clock["t"] + float(os.environ.get("OFF_LOOP0", 0.0))

    # OFF_SCRIPT="3.0 burst 2; 4.5 select CPU" — scripted real-event stand-ins for demo clips
    script = []
    for item in filter(None, (x.strip() for x in os.environ.get("OFF_SCRIPT", "").split(";"))):
        at, cmd, *arg = item.split()
        script.append([float(at), cmd, arg, False])

    def frame(t):
        clock["t"] = t
        for ev in script:
            if not ev[3] and t >= ev[0]:
                ev[3] = True
                if ev[1] == "burst":
                    r.burst(int(ev[2][0]) if ev[2] else 0)
                elif ev[1] == "select":
                    r.selected = ev[2][0]
                    r.sel_t = t + 0.01
                    r.built_at = None
                elif ev[1] == "cmd":             # a VECTOR verb: cmd focus some text
                    print("verb:", r.command(ev[2][0], " ".join(ev[2][1:])), file=sys.stderr)
                elif ev[1] == "event":           # a feed event: event {"type": ...}
                    import json as _j
                    from live.vfeed import Feed
                    Feed.get().inject(dict(_j.loads(" ".join(ev[2])), source="offscreen-test"))
                elif ev[1] == "wheel":           # wheel X Y DY: scroll at a point (DY > 0 zooms out)
                    r.scroll(float(ev[2][0]) * W / 2560, float(ev[2][1]) * H / 1440, float(ev[2][2]))
                elif ev[1] == "dclick":          # dclick X Y
                    r.dclick(float(ev[2][0]) * W / 2560, float(ev[2][1]) * H / 1440)
                elif ev[1] == "drag":            # drag X0 Y0 X1 Y1 [shift|right]: one drag, in 8 moves
                    x0, y0, x1, y1 = (float(v) * (W / 2560 if i % 2 == 0 else H / 1440) for i, v in enumerate(ev[2][:4]))
                    r.mods = 1 if "shift" in ev[2][4:] else 0
                    r.click(x0, y0, 3 if "right" in ev[2][4:] else 1)
                    for k in range(1, 9):
                        r.motion(x0 + (x1 - x0) * k / 8, y0 + (y1 - y0) * k / 8, 0)
                    r.release(x1, y1)
                    r.mods = 0
                elif ev[1] == "hover":           # hover X Y
                    r.motion(float(ev[2][0]) * W / 2560, float(ev[2][1]) * H / 1440, 0)
                elif ev[1] == "key":
                    r.typed = ev[2][0] if len(ev[2][0]) == 1 else ""
                    r.key(ev[2][0])
                elif ev[1] == "part":
                    r.selected = ev[2][0]
                    r.sel_t = t + 0.01
                    r.built_at = None
                elif ev[1] == "notes":
                    r.notes.toggle()
                    if ev[2]:
                        r.notes.query = " ".join(ev[2])
                        r.notes._filter()
                    r.built_at = None
                elif ev[1] == "scan":
                    r.scan()
                elif ev[1] == "pin":
                    r.scan_pin_toggle()
                elif ev[1] == "radial":
                    r._select(int(ev[2][0]))
                elif ev[1] == "w":                 # a world verb: w set cpu 0.9 · w event notify
                    print("world:", r.command(ev[2][0], " ".join(ev[2][1:])), file=sys.stderr)
        if hasattr(r, "tick"):
            r.tick(t)
        r.render(tgt.fbo, 30)
        hv = getattr(r, "hv", None)
        if hv is not None and hv.live is not None and not getattr(r, "_hv_waited", False):
            r._hv_waited = True                    # the shared renderer polls on its own threads
            t_end = time.time() + 8
            while time.time() < t_end and hv.live.version() == 0:
                time.sleep(0.2)
            time.sleep(0.5)
        GL.glBindFramebuffer(GL.GL_FRAMEBUFFER, tgt.fbo)
        px = GL.glReadPixels(0, 0, W, H, GL.GL_RGBA, GL.GL_UNSIGNED_BYTE)
        return np.frombuffer(px, dtype=np.uint8).reshape(H, W, 4)[::-1]
    if out.endswith(".png"):
        import cairo
        times = [float(x) for x in sys.argv[3:]] or [2.0]
        last = -1.0
        for t in times:
            k = max(last, t - 0.5)
            while k < t - 0.05:                  # step up to t so timelines run naturally
                frame(k)
                k += 1 / 15
            img = frame(t)
            last = t
            rgba = np.ascontiguousarray(img[..., [2, 1, 0, 3]])
            if os.environ.get("OFF_OPAQUE", "1") == "1":
                rgba[..., 3] = 255
            surf = cairo.ImageSurface.create_for_data(memoryview(rgba), cairo.FORMAT_ARGB32, W, H)
            surf.write_to_png(out.replace("%", f"{t:05.2f}") if "%" in out else out)
    else:
        secs = float(sys.argv[3])
        fps = int(sys.argv[4]) if len(sys.argv) > 4 else 30
        t0 = float(os.environ.get("OFF_T0", 0.0))
        ff = subprocess.Popen(["ffmpeg", "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgba", "-s", f"{W}x{H}",
                               "-r", str(fps), "-i", "-", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "16",
                               "-preset", "medium", out], stdin=subprocess.PIPE)
        for i in range(int(secs * fps)):
            ff.stdin.write(frame(t0 + i / fps).tobytes())
            if i % fps == 0:
                time.sleep(0.0)
        ff.stdin.close()
        ff.wait()
    data.stop.set()


def make_world(cfg, data):
    from live import world
    if os.environ.get("OFF_WORLD"):
        os.environ["BROMIGOS_WORLD"] = os.environ["OFF_WORLD"]
    os.environ["BROMIGOS_WORLD_SYNC"] = "1"          # video loops: every frame, as rendered
    p = world.world_file(cfg)
    if not p:
        sys.exit("no world: set OFF_WORLD to a theme directory with live/world.toml")
    from live import cover
    r = cover.wrap(lambda cw, ch: world.World(cfg, data, cw, ch, p), W, H)   # the daemon's fit
    r.offscreen = True
    return r


def bench(cfg, data):
    """bench SECONDS [world|bg]: render at 30 fps in real time, like the daemon, and report
    this process's CPU (all threads: the data pollers too) and the GPU time per frame."""
    import resource
    secs = float(sys.argv[2]) if len(sys.argv) > 2 else 30.0
    what = sys.argv[3] if len(sys.argv) > 3 else "world"
    from live import glkit
    if what == "world":
        r = make_world(cfg, data)
    else:
        from live.scene import Background
        from live import cover
        r = cover.wrap(lambda cw, ch: Background(cfg, data, cw, ch), W, H)
    tgt = glkit.Target(W, H)
    q = GL.glGenQueries(1)[0]
    gpu = []
    for item in filter(None, (x.strip() for x in os.environ.get("OFF_BENCH_W", "").split(";"))):
        verb, _, rest = item.partition(" ")      # OFF_BENCH_W="event flyby:petrel; set cpu 0.1": world verbs first
        print("world:", r.command(verb, rest), file=sys.stderr)
    for _ in range(30):                          # warm up
        r.render(tgt.fbo, 30)
    GL.glFinish()
    ru0, t0 = resource.getrusage(resource.RUSAGE_SELF), time.monotonic()
    n = 0
    nxt = t0
    frame_cpu = 0.0
    while time.monotonic() - t0 < secs:
        GL.glBeginQuery(GL.GL_TIME_ELAPSED, q)
        c0 = time.thread_time()
        r.render(tgt.fbo, 30)
        frame_cpu += time.thread_time() - c0
        GL.glEndQuery(GL.GL_TIME_ELAPSED)
        if n % 15 == 0:
            v = ctypes.c_uint64(0)
            GL.glGetQueryObjectui64v(q, GL.GL_QUERY_RESULT, ctypes.byref(v))
            gpu.append(v.value / 1e6)
        n += 1
        GL.glFlush()
        nxt += 1 / 30
        time.sleep(max(0.0, nxt - time.monotonic()))
    ru1, t1 = resource.getrusage(resource.RUSAGE_SELF), time.monotonic()
    cpu = (ru1.ru_utime - ru0.ru_utime + ru1.ru_stime - ru0.ru_stime) / (t1 - t0) * 100
    gpu.sort()
    print(f"{what} {W}x{H}: {n / (t1 - t0):.1f} fps, process CPU {cpu:.1f}% of one core "
          f"(frames alone {frame_cpu / (t1 - t0) * 100:.1f}%, {frame_cpu / max(n, 1) * 1000:.2f} ms each), "
          f"GPU {gpu[len(gpu) // 2]:.2f} ms median, {gpu[int(len(gpu) * 0.95)]:.2f} ms p95 per frame")
    data.stop.set()
    if hasattr(r, "close"):
        r.close()


if __name__ == "__main__":
    main()
