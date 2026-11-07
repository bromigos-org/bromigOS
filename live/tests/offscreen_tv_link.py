#!/usr/bin/env python3
"""Offscreen render checks for linked channels (live/live/tvlink.py), headless (EGL, as
tools/offscreen.py: never a window), in a throwaway HOME and $XDG_RUNTIME_DIR:

  - a linked big monitor plays an HLS stream served here on 127.0.0.1 that answers only
    with the feed's Authorization header (a generated test pattern: never real media), with
    four people over it (two speaking, one a den screen) and the LIVE badge;
  - the same screen voice only: no stream, the people fill the screen;
  - `tv state` names the link and carries neither the address nor the token;
  - the TV's overlay at a TV's own size (1280x720), with and without a stream, for review.

    python3 live/tests/offscreen_tv_link.py [--out DIR]
    (DIR: PNGs of each render; exit 1 on a failure)
"""
import http.server
import json
import os
import shutil
import subprocess
import sys
import threading

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import offscreen_tv as O  # noqa: E402

LIVE = O.LIVE
REPO = O.REPO
TOKEN = "Bearer offscreen-test-token"


def people(pic):
    return [{"name": "kestrel", "picture": pic, "face": "", "speaking": True},
            {"name": "wren", "face": "", "speaking": True},
            {"name": "sable", "face": ""},
            {"name": "KESTREL · LIVING ROOM TV", "face": "", "endpoint": True}]


def serve(folder):
    """An HLS server on 127.0.0.1 that answers only with the token: (url base, hits, server)."""
    hits = {"ok": 0, "refused": 0}

    class H(http.server.SimpleHTTPRequestHandler):
        def __init__(self, *a, **k):
            super().__init__(*a, directory=folder, **k)

        def do_GET(self):
            if self.headers.get("Authorization") != TOKEN:
                hits["refused"] += 1
                self.send_error(401)
                return
            hits["ok"] += 1
            super().do_GET()

        def log_message(self, *a):
            pass
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return f"http://127.0.0.1:{srv.server_address[1]}", hits, srv


def child(out, opts):
    """One den frame with the big monitor linked; saves .npy and the state's .json."""
    import time
    sys.path.insert(0, LIVE)
    sys.path.insert(0, os.path.join(REPO, "lib"))
    import importlib.util
    spec = importlib.util.spec_from_file_location("offscreen", os.path.join(LIVE, "tools", "offscreen.py"))
    off = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(off)
    off.egl()
    real_sleep = time.sleep
    import numpy as np
    from OpenGL import GL
    import bromigos_theme as T
    T.PATH = opts["palette"]
    T._checked = float("-inf")
    T.version(0.0)
    import live.tv as livetv
    livetv.MONO = time.monotonic
    time.monotonic = lambda: 1000.0
    from live import config as C, cover, glkit, motion, scene
    from live.data import Data
    cfg = C.load()
    cfg["general"]["motion"] = opts.get("motion", "full")
    cfg["background"]["underlay"] = O.DEN
    motion.set_current(cfg["general"]["motion"])
    os.environ["OFF_TV"] = opts["clip"]
    os.environ["OFF_TV_SCREEN"] = "big"
    os.environ["OFF_TV_HINT"] = "0"
    os.environ["OFF_MOTION"] = cfg["general"]["motion"]
    off.tv_config(cfg)
    base, hits, srv = serve(opts["hls_dir"]) if opts.get("hls_dir") else (None, None, None)
    d = Data({}, lambda *a, **k: None)
    d.s.update(cpu=35.0, gpu=12.0, mem=40.0, rx=2.0e5, tx=4.0e4)
    r = cover.wrap(lambda cw, ch: scene.Background(cfg, d, cw, ch), O.W, O.H)
    r.now = lambda: 2.0
    r.loop_clock = lambda: 2.0
    tgt = glkit.Target(O.W, O.H)
    tv = off.tv_tune(r)
    from live.scene import DEN
    inner = getattr(r, "inner", r)
    tv.layout(inner.w, inner.h, {k: inner._px(DEN[k]) for k in ("big", "wave", "emblem")}, inner.view, 1)
    feed = dict(opts["feed"])
    if base:
        feed["video"] = {"hls": base + "/index.m3u8", "authorization": TOKEN}
    run = os.environ["XDG_RUNTIME_DIR"]
    os.makedirs(os.path.join(run, "bromigos-live"), mode=0o700, exist_ok=True)
    path = os.path.join(run, "bromigos-live", "link-big.json")
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        json.dump(feed, f)
    state = {"link": None if opts.get("nolink") else json.loads(tv.command(f"link --screen big --feed {path} --json"))}
    if base:
        state["picture"] = off.tv_warm(r, tv, lambda: r.render(tgt.fbo, 30), limit=20)
    for i in range(int(opts.get("frames", 30))):
        tv.tick(motion=cfg["general"]["motion"])
        r.render(tgt.fbo, 30)
        if i >= int(opts.get("frames", 30)) - 8:
            real_sleep(1 / 24)
    state["state"] = tv.command("state --json")
    if hits is not None:
        state["hits"] = dict(hits)
    GL.glBindFramebuffer(GL.GL_FRAMEBUFFER, tgt.fbo)
    frame = np.frombuffer(GL.glReadPixels(0, 0, O.W, O.H, GL.GL_RGB, GL.GL_UNSIGNED_BYTE), np.uint8)
    np.save(out, frame.reshape(O.H, O.W, 3)[::-1].copy())
    with open(out + ".json", "w") as f:
        json.dump(state, f, default=str)
    if srv:
        srv.shutdown()
    getattr(r, "close", lambda: None)()
    os._exit(0)


def render(env, opts, name):
    out = os.path.join(env["HOME"], name + ".npy")
    p = subprocess.run([sys.executable, os.path.abspath(__file__), "--child", out, json.dumps(opts)],
                       env=env, capture_output=True, text=True, timeout=180)
    if p.returncode != 0 or not os.path.exists(out):
        raise RuntimeError(f"render {name} failed:\n{p.stdout[-1500:]}\n{p.stderr[-3000:]}")
    import numpy as np
    with open(out + ".json") as f:
        return np.load(out), json.load(f)


def tv_size(feed, out_png, motion="full"):
    """The overlay alone at a TV's own size, over a test card when there's a stream."""
    sys.path.insert(0, LIVE)
    sys.path.insert(0, os.path.join(REPO, "lib"))
    import cairo
    from live import glkit, tvlink
    w, h = 1280, 720
    surf = cairo.ImageSurface(cairo.FORMAT_ARGB32, w, h)
    cr = cairo.Context(surf)
    f = tvlink.parse_feed(json.dumps(feed))
    if f["video"]:                                              # a test card where the stream would be
        bars = [(0.75, 0.75, 0.75), (0.75, 0.75, 0), (0, 0.75, 0.75), (0, 0.75, 0), (0.75, 0, 0.75), (0.75, 0, 0),
                (0, 0, 0.75)]
        for i, c in enumerate(bars):
            cr.set_source_rgb(*c)
            cr.rectangle(i * w / 7, 0, w / 7 + 1, h)
            cr.fill()
    else:
        cr.set_source_rgb(0.02, 0.04, 0.03)
        cr.paint()
    tvlink.draw(cr, w, h, f, glkit.col, t=0.4, motion=motion)
    surf.write_to_png(out_png)
    return out_png


def picture(path):
    """A person's picture for the test: a soft gradient portrait card, made here."""
    from PIL import Image, ImageDraw
    im = Image.new("RGB", (256, 256), (30, 60, 90))
    dr = ImageDraw.Draw(im)
    for y in range(256):
        dr.line([(0, y), (255, y)], fill=(40 + y // 4, 70 + y // 5, 110 + y // 6))
    dr.ellipse((78, 48, 178, 148), fill=(210, 180, 150))
    dr.rectangle((60, 160, 196, 256), fill=(60, 90, 70))
    im.save(path)
    os.chmod(path, 0o600)


def main():
    if "--child" in sys.argv:
        i = sys.argv.index("--child")
        return child(sys.argv[i + 1], json.loads(sys.argv[i + 2]))
    import numpy as np
    from PIL import Image
    out = sys.argv[sys.argv.index("--out") + 1] if "--out" in sys.argv else None
    results = []

    def check(name, ok, detail=""):
        results.append(bool(ok))
        print(f"{'PASS' if ok else 'FAIL'}  {name}" + (f"  ({detail})" if detail else ""), flush=True)

    root, env = O.sandbox()
    try:
        if out:
            os.makedirs(out, exist_ok=True)
        bromigos = next((p for p in (os.path.join(REPO, "core/target/debug/bromigos"), shutil.which("bromigos") or "")
                         if p and os.path.exists(p)), "bromigos")
        wick = O.palette_json(env, "wick", bromigos)
        os.chmod(env["XDG_RUNTIME_DIR"], 0o700)
        pic = os.path.join(env["XDG_RUNTIME_DIR"], "kestrel.png")
        picture(pic)
        clip = os.path.join(root, "channel.mp4")
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc=size=320x180:rate=24",
                        "-t", "60", "-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p", clip], check=True)
        hls = os.path.join(root, "hls")
        os.makedirs(hls)
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "smptebars=size=640x360:rate=24",
                        "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000", "-t", "60", "-c:v", "libx264",
                        "-preset", "veryfast", "-g", "48", "-pix_fmt", "yuv420p", "-c:a", "aac", "-f", "hls",
                        "-hls_time", "2", "-hls_list_size", "0", "-hls_playlist_type", "vod",
                        os.path.join(hls, "index.m3u8")], check=True)
        sx, sy = O.W / 2560.0, O.H / 1440.0
        x0, y0 = int(O.BIG[0] * sx), int(O.BIG[1] * sy)
        x1, y1 = int((O.BIG[0] + O.BIG[2]) * sx), int((O.BIG[1] + O.BIG[3]) * sy)
        live_feed = {"version": 1, "screen": "big", "badge": "LIVE · MOVIE NIGHT", "title": "Movie night",
                     "people": people(pic), "voice": True, "mic": False}
        plain, _ = render(env, {"palette": wick, "clip": clip, "feed": live_feed, "nolink": True,
                                "frames": 30}, "plain")
        frame, st = render(env, {"palette": wick, "clip": clip, "hls_dir": hls, "feed": live_feed, "frames": 60},
                           "linked")
        check("the link was taken", st["link"].get("ok") and st["link"].get("linked"), st["link"])
        check("mpv played the stream with the feed's header (the server refuses without it)",
              st.get("picture") and st["hits"]["ok"] > 0 and st["hits"]["refused"] == 0, st.get("hits"))
        state = st["state"]
        big = json.loads(state)["screens"]["big"]
        check("tv state: linked, the badge, four people, two speaking",
              big.get("linked") and big.get("badge") == "LIVE · MOVIE NIGHT" and big.get("people") == 4
              and big.get("speaking") == 2, {k: big.get(k) for k in ("linked", "badge", "people", "speaking")})
        check("…and neither the address nor the token", "offscreen-test-token" not in state and "127.0.0.1" not in state)
        scr = frame[y0 + 6:y1 - 6, x0 + 6:x1 - 6].astype(np.int16)
        spread = float(scr.reshape(-1, 3).std(axis=0).mean())
        check("the stream shows on the big monitor", spread > 25, f"colour spread {spread:.1f}")
        voice_feed = dict(live_feed, badge="#160.04 RAID COMMS", title="Raid comms")
        vframe, vst = render(env, {"palette": wick, "clip": clip, "feed": voice_feed, "frames": 30}, "voice")
        vscr = vframe[y0 + 6:y1 - 6, x0 + 6:x1 - 6].reshape(-1, 3).astype(int)
        dark = float((vscr.max(axis=1) < 60).mean())
        lit = float((vscr[:, 1] > 140).mean())
        check("voice only: dark glass over the screen, the people lit on it", dark > 0.3 and lit > 0.01,
              f"{dark:.2f} dark, {lit:.3f} lit")
        vbig = json.loads(vst["state"])["screens"]["big"]
        check("…and no stream loaded", vbig.get("linked") and not vbig.get("video") and vbig.get("playing") is None,
              {k: vbig.get(k) for k in ("linked", "video", "playing")})
        mask = np.ones((O.H, O.W), bool)
        mask[max(0, y0 - 60):y1 + 60, max(0, x0 - 60):x1 + 60] = False
        diffmask = (vframe != plain).any(axis=2) & mask
        outside = int(diffmask.sum())
        if outside:
            ys, xs = np.nonzero(diffmask)
            print("outside diff bbox", xs.min(), ys.min(), xs.max(), ys.max(), "screen", x0, y0, x1, y1, flush=True)
        check("the rest of the den untouched", outside == 0, f"{outside} pixels differ outside the screen")
        if out:
            Image.fromarray(frame).save(os.path.join(out, "linked-den.png"))
            Image.fromarray(frame[y0 - 120:y1 + 160, x0 - 200:x1 + 260]).save(os.path.join(out, "linked-crop.png"))
            Image.fromarray(vframe[y0 - 120:y1 + 160, x0 - 200:x1 + 260]).save(os.path.join(out, "voice-crop.png"))
            sys.path.insert(0, LIVE)
            sys.path.insert(0, os.path.join(REPO, "lib"))
            import bromigos_theme as T
            T.PATH = wick
            T._checked = float("-inf")
            T.version(0.0)
            tv_size(dict(live_feed, video={"hls": "http://127.0.0.1/x.m3u8", "authorization": TOKEN}),
                    os.path.join(out, "tv-1280-live.png"))
            tv_size(dict(voice_feed, mic=True), os.path.join(out, "tv-1280-voice.png"))
            tv_size(dict(voice_feed, people=people(pic) * 2), os.path.join(out, "tv-1280-voice-8.png"),
                    motion="reduced")
    finally:
        shutil.rmtree(root, ignore_errors=True)
    print(f"\n{sum(results)}/{len(results)} checks pass")
    return 0 if all(results) else 1


if __name__ == "__main__":
    sys.exit(main())
