#!/usr/bin/env python3
"""Offscreen render checks for the den TV (live/live/tv.py), headless (EGL, as
tools/offscreen.py: never a window), in a throwaway HOME:

  - the den is pixel for pixel what it was before the den TV existed (the code at --base,
    origin/main by default) when no media channel is on: with no [tv] at all, and with
    media channels configured but every screen on its own channel 1;
  - a generated test clip (ffmpeg's test pattern, made here: never real media) plays on
    the big monitor through libmpv, in the Wick and in a colour theme (Cinder): there's a
    picture in the screen, the relay map steps off it, and the rest of the den is untouched;
  - the hover hint draws, and still motion shows the item's poster instead of video.

Every render runs in its own process with every clock fixed and the same readings.

    python3 live/tests/offscreen_tv.py [--out DIR] [--base REF] [--bromigos PATH]
    (DIR: PNGs of each render; exit 1 on a failure)
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
LIVE = os.path.dirname(HERE)
REPO = os.path.dirname(LIVE)
W, H = 1920, 1080
DEN = os.path.join(REPO, "desktop/wallpaper/bromigos-den-empty-2560x1440.jpg")
BIG = (1188, 678, 200, 175)                 # scene.DEN["big"], plate px


def sandbox():
    root = tempfile.mkdtemp(prefix="bromigos-tv-")
    env = {k: v for k, v in os.environ.items() if k not in (
        "WAYLAND_DISPLAY", "HYPRLAND_INSTANCE_SIGNATURE", "DISPLAY", "DBUS_SESSION_BUS_ADDRESS", "BROMIGOS_WORLD",
        "BROMIGOS_LIVE_CONFIG", "BROMIGOS_LIVE_PLUGINS", "BROMIGOS_HOMELAB", "BROMIGOS_VECTOR")}
    for k, sub in (("HOME", ""), ("XDG_CONFIG_HOME", ".config"), ("XDG_STATE_HOME", ".local/state"),
                   ("XDG_DATA_HOME", ".local/share"), ("XDG_CACHE_HOME", ".cache"), ("XDG_RUNTIME_DIR", "run")):
        env[k] = os.path.join(root, sub)
        os.makedirs(env[k], exist_ok=True)
    env["BROMIGOS_SHARE_DIR"] = REPO
    env["BROMIGOS_HOMELAB_CONFIG"] = os.path.join(root, "no-homelab.toml")
    env["PYOPENGL_PLATFORM"] = "egl"
    return root, env


# ------------------------------------------------------------------ one render (a child process)
def child(tree, out, opts):
    """Draw one den frame with the code in tree; save it as .npy (and the TV's state as .json)."""
    global W, H
    import time
    if opts.get("size"):
        W, H = opts["size"]
    sys.path.insert(0, os.path.join(tree, "live"))
    sys.path.insert(0, os.path.join(tree, "lib"))
    import importlib.util
    spec = importlib.util.spec_from_file_location("offscreen", os.path.join(tree, "live", "tools", "offscreen.py"))
    off = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(off)
    off.egl()
    real_sleep = time.sleep
    if opts.get("palette"):
        import bromigos_theme as T
        T.PATH = opts["palette"]
        T._checked = float("-inf")
        T.version(0.0)
    import numpy as np
    from OpenGL import GL
    if os.path.exists(os.path.join(tree, "live", "live", "tv.py")):
        import live.tv as livetv                         # the TV keeps the real clock: mpv plays in real time
        livetv.MONO = time.monotonic
    time.monotonic = lambda: 1000.0                      # the scene's clocks fixed: the same frame every run
    from live import config as C, cover, glkit, motion, scene
    from live.data import Data
    cfg = C.load()
    cfg["general"]["motion"] = opts.get("motion", "full")
    cfg["background"]["underlay"] = DEN
    motion.set_current(cfg["general"]["motion"])
    if "tv" in opts:
        cfg["tv"] = opts["tv"]
    if "tint" in opts:
        cfg.setdefault("tv", {})["tint"] = opts["tint"]
    if opts.get("clip"):
        os.environ["OFF_TV"] = opts["clip"]
        os.environ["OFF_TV_SCREEN"] = opts.get("screens") or "big"
        os.environ["OFF_TV_HINT"] = opts["hint"] if isinstance(opts.get("hint"), str) else (
            "1" if opts.get("hint") else "0")
        if opts.get("sound"):
            os.environ["OFF_TV_SOUND"] = opts["sound"]
        os.environ["OFF_MOTION"] = cfg["general"]["motion"]
        off.tv_config(cfg)
    d = Data({}, lambda *a, **k: None)
    d.s.update(cpu=35.0, gpu=12.0, mem=40.0, rx=2.0e5, tx=4.0e4)
    r = cover.wrap(lambda cw, ch: scene.Background(cfg, d, cw, ch), W, H)
    r.now = lambda: 2.0
    r.loop_clock = lambda: 2.0
    tgt = glkit.Target(W, H)
    state = {}
    frames = int(opts.get("frames", 1))
    if opts.get("clip"):
        tv = off.tv_tune(r)
        if opts.get("poster"):
            from PIL import Image
            im = Image.open(opts["poster"]).convert("RGBA")
            slot = tv.slot(tv.channel("big")[1])
            tv.poster[str(slot.item["id"])] = (im.tobytes(), im.width, im.height)
        state["picture"] = off.tv_warm(r, tv, lambda: r.render(tgt.fbo, 30), limit=15)
        covered = set(opts.get("covered") or ())
        if opts.get("swap"):
            # the frame swap: a screen showing clip A is tuned (covered, so paused) to clip B's
            # channel; read its middle pixel every frame until B's colour shows
            swap = opts["swap"]
            import bromigos_tv as TVL
            chB = dict(next(c for c in TVL.channels(tv.cfg, panel=False) if c["key"] != tv.screens["big"]["channel"]))
            tv.lineup = lambda s, _tv=tv, a=tv.lineup("big"): a + [chB] if s == "big" else [TVL.own_channel(s)]
            mid = [int((BIG[0] + BIG[2] / 2) * W / 2560.0), H - int((BIG[1] + BIG[3] / 2) * H / 1440.0)]

            def middle():
                GL.glBindFramebuffer(GL.GL_FRAMEBUFFER, tgt.fbo)
                return [int(v) for v in np.frombuffer(GL.glReadPixels(mid[0], mid[1], 1, 1, GL.GL_RGB,
                                                                       GL.GL_UNSIGNED_BYTE), np.uint8)]
            tv.tick(covered={"big"} if swap.get("covered") else set(), motion=cfg["general"]["motion"])
            r.render(tgt.fbo, 30)
            state["before"] = middle()
            tv.tune_to("big", number=3)
            seen = []
            t_end = time.time() + 12
            while time.time() < t_end:
                tv.tick(covered={"big"} if swap.get("covered") else set(), motion=cfg["general"]["motion"])
                r.render(tgt.fbo, 30)
                seen.append(middle())
                d = tv.decks["big"]
                if d.player is not None and d.player.has_frame and len(seen) > 40:
                    break
                real_sleep(0.03)
            state["seen"] = seen
            state["paused"] = tv.decks["big"].player.paused() if tv.decks["big"].player else None
            try:
                state["hwdec"] = tv.decks["big"].player.m.hwdec_current
            except Exception:                           # noqa: BLE001
                state["hwdec"] = None
        for i in range(frames):                         # the meters settle; the last frames play the clip
            tv.tick(covered=covered, motion=cfg["general"]["motion"])
            r.render(tgt.fbo, 30)
            if i >= frames - 8:
                real_sleep(1 / 24)
        state["describe"] = tv.describe()
        if opts.get("measure"):
            if opts.get("tv_off"):
                for s_ in tv.screens:
                    tv.screens[s_]["channel"] = "own"
                for d in tv.decks.values():
                    tv._close_player(d)
            state["measure"] = measure(r, tv, tgt, cfg, float(opts["measure"]), real_sleep)
    else:
        for _ in range(frames):
            r.render(tgt.fbo, 30)
    GL.glBindFramebuffer(GL.GL_FRAMEBUFFER, tgt.fbo)
    frame = np.frombuffer(GL.glReadPixels(0, 0, W, H, GL.GL_RGB, GL.GL_UNSIGNED_BYTE), np.uint8)
    np.save(out, frame.reshape(H, W, 3)[::-1].copy())
    with open(out + ".json", "w") as f:
        json.dump(state, f, default=str)
    getattr(r, "close", lambda: None)()
    os._exit(0)                                         # mpv's threads: no lingering at exit


def measure(r, tv, tgt, cfg, secs, real_sleep):
    """Draw at 30 frames a second for secs with every screen playing: this process's CPU
    (mpv's decoders and the scene, all threads) and the GPU's use (nvidia-smi, when there)."""
    import resource
    import shutil as sh
    from OpenGL import GL
    import time as _t
    gpu = None
    if sh.which("nvidia-smi"):
        gpu = subprocess.Popen(["nvidia-smi", "pmon", "-s", "u", "-c", str(int(secs)), "-d", "1"],
                               stdout=subprocess.PIPE, text=True)
    ru0 = resource.getrusage(resource.RUSAGE_SELF)
    w0 = _t.perf_counter()
    n = 0
    while _t.perf_counter() - w0 < secs:
        f0 = _t.perf_counter()
        tv.tick(motion=cfg["general"]["motion"])
        r.render(tgt.fbo, 30)
        GL.glFinish()
        n += 1
        real_sleep(max(0.0, 1 / 30 - (_t.perf_counter() - f0)))
    wall = _t.perf_counter() - w0
    ru1 = resource.getrusage(resource.RUSAGE_SELF)
    cpu = (ru1.ru_utime + ru1.ru_stime - ru0.ru_utime - ru0.ru_stime) / wall * 100
    sm = dec = []
    if gpu:
        out = gpu.communicate(timeout=secs + 15)[0]
        rows = [ln.split() for ln in out.splitlines() if ln.strip() and not ln.startswith("#")]
        mine = [x for x in rows if len(x) > 6 and x[1] == str(os.getpid())]
        sm = [float(x[3]) for x in mine if x[3] != "-"]
        dec = [float(x[6]) for x in mine if x[6] != "-"]
    avg = lambda v: round(sum(v) / len(v), 1) if v else None  # noqa: E731
    hw = {}
    for s, d in tv.decks.items():
        try:
            hw[s] = d.player.m.hwdec_current if d.player else None
        except Exception:                               # noqa: BLE001
            hw[s] = None
    return {"cpu": round(cpu, 1), "fps": round(n / wall, 1), "gpu_sm": avg(sm), "gpu_dec": avg(dec), "samples": len(sm),
            "hwdec": hw}


def render(env, tree, opts, name):
    out = os.path.join(env["HOME"], name + ".npy")
    p = subprocess.run([sys.executable, os.path.abspath(__file__), "--child", tree, out, json.dumps(opts)],
                       env=env, capture_output=True, text=True, timeout=180)
    if p.returncode != 0 or not os.path.exists(out):
        raise RuntimeError(f"render {name} failed:\n{p.stdout[-1500:]}\n{p.stderr[-3000:]}")
    import numpy as np
    with open(out + ".json") as f:
        return np.load(out), json.load(f)


def palette_json(env, theme, bromigos):
    state = os.path.join(env["HOME"], "state-" + theme)
    empty = os.path.join(env["HOME"], "empty-path")
    os.makedirs(empty, exist_ok=True)
    e = {"HOME": env["HOME"], "XDG_STATE_HOME": state, "XDG_CONFIG_HOME": env["XDG_CONFIG_HOME"],
         "XDG_RUNTIME_DIR": env["XDG_RUNTIME_DIR"], "BROMIGOS_SHARE_DIR": REPO, "PATH": empty}
    subprocess.run([bromigos, "theme", "set", theme, "--no-reload"], env=e, check=True, capture_output=True)
    return os.path.join(state, "bromigos", "theme", "current", "palette.json")


def main():
    if "--child" in sys.argv:
        i = sys.argv.index("--child")
        return child(sys.argv[i + 1], sys.argv[i + 2], json.loads(sys.argv[i + 3]))
    import numpy as np
    out = sys.argv[sys.argv.index("--out") + 1] if "--out" in sys.argv else None
    base = sys.argv[sys.argv.index("--base") + 1] if "--base" in sys.argv else "origin/main"
    bromigos = sys.argv[sys.argv.index("--bromigos") + 1] if "--bromigos" in sys.argv else next(
        (p for p in (os.path.join(REPO, "core/target/debug/bromigos"), shutil.which("bromigos") or "")
         if p and os.path.exists(p)), "bromigos")
    results = []

    def check(name, ok, detail=""):
        results.append(ok)
        print(f"{'PASS' if ok else 'FAIL'}  {name}" + (f"  ({detail})" if detail else ""), flush=True)

    root, env = sandbox()
    try:
        if out:
            os.makedirs(out, exist_ok=True)
        # the code as it was: git archive of the base's live/ and lib/
        old = os.path.join(root, "base")
        os.makedirs(old)
        arch = subprocess.run(["git", "-C", REPO, "archive", base, "live", "lib"], capture_output=True)
        if arch.returncode != 0:
            raise RuntimeError(f"git archive {base}: {arch.stderr.decode()[:200]}")
        subprocess.run(["tar", "-x", "-C", old], input=arch.stdout, check=True)
        wick = palette_json(env, "wick", bromigos)
        before, _ = render(env, old, {"palette": wick}, "before")
        now, _ = render(env, REPO, {"palette": wick}, "now")
        diff = int((before != now).any(axis=2).sum())
        check(f"the Wick den: pixel for pixel as at {base}, with no [tv]", diff == 0, f"{diff} pixels differ")
        tv = {"channel": [{"name": "Shows", "files": [os.path.join(root, "none.mp4")], "screens": ["big", "wave"]},
                          {"name": "Clips", "youtube": "https://www.youtube.com/playlist?list=PLexample"}]}
        on1, _ = render(env, REPO, {"palette": wick, "tv": tv}, "channels-on-1")
        diff = int((before != on1).any(axis=2).sum())
        check("…and with media channels set up, every screen on its own channel 1", diff == 0, f"{diff} pixels differ")
        if out:
            from PIL import Image
            Image.fromarray(now).save(os.path.join(out, "den-wick.png"))

        # the clip on the big monitor
        clip = os.path.join(root, "test-pattern.mp4")
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc2=size=640x360:rate=24",
                        "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000", "-t", "120", "-c:v", "libx264",
                        "-preset", "veryfast", "-pix_fmt", "yuv420p", "-c:a", "aac", clip], check=True)
        sx, sy = W / 2560.0, H / 1440.0
        x0, y0 = int(BIG[0] * sx), int(BIG[1] * sy)
        x1, y1 = int((BIG[0] + BIG[2]) * sx), int((BIG[1] + BIG[3]) * sy)
        for theme in ("wick", "cinder"):
            pal = wick if theme == "wick" else palette_json(env, theme, bromigos)
            plain, _ = render(env, REPO, {"palette": pal, "frames": 160}, f"plain-{theme}")
            frame, st = render(env, REPO, {"palette": pal, "clip": clip, "frames": 160}, f"tv-{theme}")
            screen_now = frame[y0 + 8:y1 - 8, x0 + 8:x1 - 8].astype(np.int16)
            screen_was = plain[y0 + 8:y1 - 8, x0 + 8:x1 - 8].astype(np.int16)
            spread = float(screen_now.reshape(-1, 3).std(axis=0).mean())
            check(f"{theme}: mpv drew the clip on the big monitor", bool(st.get("picture")) and spread > 25,
                  f"picture={st.get('picture')}, colour spread {spread:.1f}")
            check(f"{theme}: the relay map stepped off it", float(np.abs(screen_now - screen_was).mean()) > 10)
            mask = np.ones((H, W), bool)
            mask[max(0, y0 - 60):y1 + 60, max(0, x0 - 60):x1 + 60] = False      # the screen, its glow
            # the scene's own clocks are fixed but this render ran the clip in real time: the
            # rest of the den must still be the same picture
            outside = int(((frame != plain).any(axis=2) & mask).sum())
            check(f"{theme}: the rest of the den untouched", outside == 0, f"{outside} pixels differ outside the screen")
            if out:
                from PIL import Image
                Image.fromarray(frame).save(os.path.join(out, f"tv-{theme}.png"))
                Image.fromarray(frame[y0 - 120:y1 + 220, x0 - 260:x1 + 380]).save(os.path.join(out, f"tv-{theme}-crop.png"))
        hint, st = render(env, REPO, {"palette": wick, "clip": clip, "hint": True, "frames": 160}, "tv-hint")
        hy0 = y1 + int(10 * 1)
        region = hint[hy0:hy0 + 100, x0 - 100:x0 + 300].astype(np.int16)
        under = plain[hy0:hy0 + 100, x0 - 100:x0 + 300]
        check("the hover hint draws under the screen", float(np.abs(region - under).mean()) > 8)
        if out:
            from PIL import Image
            Image.fromarray(hint[y0 - 120:y1 + 220, x0 - 260:x1 + 380]).save(os.path.join(out, "tv-hint-crop.png"))
        # still motion: the poster, no video decoded
        from PIL import Image
        poster = os.path.join(root, "poster.png")
        im = Image.new("RGB", (200, 300), (200, 40, 40))
        for yy in range(0, 300, 30):
            for xx in range(200):
                im.putpixel((xx, yy), (240, 240, 240))
        im.save(poster)
        still, st = render(env, REPO, {"palette": wick, "clip": clip, "motion": "still", "poster": poster,
                                       "frames": 20}, "tv-still")
        playing = (st.get("describe") or {}).get("playing")
        red = still[y0 + 10:y1 - 10, x0 + 10:x1 - 10].reshape(-1, 3).astype(int)
        check("still motion: the poster, and mpv never started", playing is None and
              (red[:, 0] > red[:, 1] + 30).mean() > 0.1, f"playing={playing}")
        if out:
            Image.fromarray(still[y0 - 60:y1 + 60, x0 - 60:x1 + 60]).save(os.path.join(out, "tv-still-crop.png"))

        # every screen at once: three clips, three players
        clips = []
        for name, src in (("bars", "smptebars=size=640x360:rate=24"), ("mandel", "mandelbrot=size=640x360:rate=24"),
                          ("life", "testsrc=size=640x360:rate=24")):
            c = os.path.join(root, f"{name}.mp4")
            subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", src, "-t", "120", "-c:v", "libx264",
                            "-preset", "veryfast", "-pix_fmt", "yuv420p", c], check=True)
            clips.append(c)
        three = ",".join([clip] + clips[:2])
        frame, st = render(env, REPO, {"palette": wick, "clip": three, "screens": "big,wave,emblem", "frames": 160,
                                       "sound": "wave"}, "tv-three")
        desc = st.get("describe") or {}
        playing = {k: (v.get("playing") or {}) for k, v in (desc.get("screens") or {}).items()}
        check("three screens play at once, each its own channel and player",
              all(playing.get(k, {}).get("has_frame") for k in ("big", "wave", "emblem"))
              and len({playing[k].get("item") for k in playing}) == 3, {k: v.get("item") for k, v in playing.items()})
        check("…the sound from one screen only (the scope)", desc.get("sound_from") == "wave"
              and [k for k, v in desc["screens"].items() if v["sound"]] == ["wave"])
        secs = float(os.environ.get("OFF_MEASURE", "0") or 0)
        if secs:
            # what it costs, at 2560x1440 (the den's own size): the den alone, one screen, three
            for label, o in (("the den alone", {}),
                             ("one screen playing", {"clip": clip, "screens": "big"}),
                             ("three screens playing", {"clip": three, "screens": "big,wave,emblem"})):
                o = dict(o, palette=wick, frames=30, size=[2560, 1440], measure=secs)
                if not o.get("clip"):
                    o.update(clip=clip, screens="big", tv_off=True)
                _f, m = render(env, REPO, o, "measure")
                print(f"MEASURE  {label} at 2560x1440: {json.dumps(m.get('measure'))}", flush=True)
        if out:
            from PIL import Image
            Image.fromarray(frame).save(os.path.join(out, "tv-three.png"))
            Image.fromarray(frame[int(560 * sy):int(1100 * sy), int(1000 * sx):int(1700 * sx)]).save(
                os.path.join(out, "tv-three-crop.png"))

        # the frame swap: tuned while covered (so paused), the screen never keeps the last picture
        red = os.path.join(root, "red.mp4")
        blue = os.path.join(root, "blue.mp4")
        for c, col in ((red, "red"), (blue, "blue")):
            subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", f"color=c={col}:size=320x180:rate=24",
                            "-t", "120", "-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p", c], check=True)
        for covered in (True, False):
            _f, st = render(env, REPO, {"palette": wick, "clip": f"{red},{blue}", "screens": "big,wave", "frames": 2,
                                        "tint": 0, "swap": {"covered": covered}}, f"tv-swap-{covered}")
            seen = st.get("seen") or []
            reds = [p for p in seen if p[0] > p[2] + 40]
            blues = [p for p in seen if p[2] > p[0] + 40]
            what = "covered (paused)" if covered else "playing"
            check(f"the frame swap, {what}: the old channel's red was on before",
                  (st.get("before") or [0, 0, 0])[0] > (st.get("before") or [0, 0, 0])[2] + 40, st.get("before"))
            check(f"…and after the tune never again: static or the poster, then the new item's blue",
                  not reds and len(blues) > 0, f"{len(reds)} red frames, {len(blues)} blue of {len(seen)}")
            check(f"…decoded on the GPU ({what})", (st.get("hwdec") or "no") != "no" or not shutil.which("nvidia-smi"),
                  st.get("hwdec"))
    finally:
        shutil.rmtree(root, ignore_errors=True)
    print(f"\n{sum(results)}/{len(results)} checks pass")
    return 0 if all(results) else 1


if __name__ == "__main__":
    sys.exit(main())
