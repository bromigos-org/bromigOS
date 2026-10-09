"""Seamless video loops as GPU textures, for worlds (a layer's `video`, or any actor
sprite that names a video file).

One ffmpeg process per loop decodes it endlessly (`-stream_loop -1`) to raw NV12 on a
pipe (no colour conversion on the CPU); a reader thread keeps the newest frame; the
render thread uploads its two planes and converts them to premultiplied RGBA on the
GPU (shaders/world_yuv.frag) when the loop's clock says a new frame is due. Decoding is
hardware accelerated where ffmpeg can (`-hwaccel auto`: CUDA/NVDEC, VAAPI, Vulkan ...),
except VP9 with an alpha channel, which only the software decoder (libvpx) reads (that
one comes as RGBA). A seamless loop is decoded once: its first pass is kept on the GPU as
NV12 planes per frame and played from there, so no decoder runs and nothing is uploaded
after it (a loop not drawn for a minute gives its VRAM back). One-shot clips stream: an
ffmpeg process costs about 4-6% of a core while it runs, whatever the size.

Pausing is free: the reader takes a frame only after the previous one was used, so when
the layer stops rendering (locked, fullscreen, a deck on top) the pipe fills, ffmpeg
blocks and decodes nothing. A loop nobody draws for a while is never even started.

Alpha (world.toml `[loops."<path>"] alpha = ...`):
  "none"     opaque video (H.264 / HEVC / AV1 / VP9), hardware decoded
  "native"   VP9 or AV1 with alpha (default for .webm), software decoded
  "stacked"  the colour on top, its alpha (grey) below, in one frame twice as tall:
             any codec, hardware decoded; ffmpeg merges the halves
  "luma"     glow art on pure black (an additive creature): opaque video whose coverage is
             its brightness, so the black around it is truly empty (the default for a loop
             an actor with blend = "add" plays)
Also per loop: `fps` (default: the file's), `scale` (decode at this fraction of the
file's size, to keep big backdrops cheap).
"""
import json
import os
import subprocess
import threading
import time

import numpy as np
from OpenGL import GL

VIDEO_EXT = (".mp4", ".webm", ".mkv", ".mov", ".m4v")


def is_video(path):
    return path.lower().endswith(VIDEO_EXT)


def probe(path):
    """(width, height, fps) of the first video stream."""
    out = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
                          "stream=width,height,avg_frame_rate,r_frame_rate", "-of", "json", path],
                         capture_output=True, text=True, timeout=10).stdout
    s = (json.loads(out or "{}").get("streams") or [{}])[0]
    num, _, den = (s.get("avg_frame_rate") or s.get("r_frame_rate") or "30/1").partition("/")
    fps = float(num) / float(den or 1) if float(den or 1) else 30.0
    return int(s.get("width") or 0), int(s.get("height") or 0), fps or 30.0


class VideoLoop:
    def __init__(self, path, alpha=None, fps=None, scale=1.0, sync=False, once=False, mask=None, cache=True):
        self.path = path
        self.alpha = alpha or ("native" if path.lower().endswith(".webm") else "none")
        w, h, f = probe(path)
        if self.alpha == "stacked":
            h //= 2
        sc = max(0.05, min(1.0, float(scale)))
        self.w, self.h = max(2, int(w * sc) // 2 * 2), max(2, int(h * sc) // 2 * 2)
        self.src_h = h
        self.nv12 = self.alpha != "native"           # stacked and opaque loops come as NV12
        self.target = None
        self.planes = None
        self.fps = float(fps or f)
        self.aspect = self.w / self.h
        self.tex = None
        self.proc = None
        self.frame = None            # the newest decoded frame (bytes), not yet uploaded
        self.taken = threading.Event()
        self.taken.set()
        self.lock = threading.Lock()
        self.clock = 0.0             # the loop's own time: advances only while it is drawn
        self.shown = -1
        self.stop = threading.Event()
        self.last_use = 0.0
        self.sync = sync             # offscreen renders: wait for each frame instead of dropping it
        self.once = once             # a one-shot clip: plays once, then holds its last frame
        self.ended = False
        base = os.path.splitext(path)[0]
        self.mask_path = mask or next((base + "-mask" + e for e in (".png", ".webp") if os.path.isfile(base + "-mask" + e)), None)
        self.mask_tex = None
        # A seamless loop is decoded once and kept on the GPU (NV12 planes per frame): after its
        # first pass no decoder runs and nothing is uploaded. One-shot clips stream.
        self.cache_on = cache and not once and self.nv12
        self.frames = []
        self.cached = False
        self.ended = False
        self.clock, self.shown = 0.0, -1

    # ---- decoding
    def _cmd(self):
        cmd = ["ffmpeg", "-v", "error", "-nostdin"]
        if self.alpha == "native":
            if self.path.lower().endswith(".webm"):
                cmd += ["-c:v", "libvpx-vp9"]          # ffmpeg's own VP9 decoder drops the alpha
        else:
            cmd += ["-hwaccel", "auto"]
        cmd += ([] if (self.once or self.cache_on) else ["-stream_loop", "-1"]) + ["-i", self.path]
        fh = self.h * 2 if self.alpha == "stacked" else self.h     # stacked: both halves
        if self.nv12:
            cmd += ["-vf", f"scale={self.w}:{fh}"] if (self.w, fh) != self._src_size() else []
            cmd += ["-r", f"{self.fps:.3f}", "-f", "rawvideo", "-pix_fmt", "nv12", "-"]
        else:
            cmd += ["-vf", f"scale={self.w}:{self.h},format=rgba"]
            cmd += ["-r", f"{self.fps:.3f}", "-f", "rawvideo", "-pix_fmt", "rgba", "-"]
        return cmd

    def _src_size(self):
        return (self.w, self.src_h * (2 if self.alpha == "stacked" else 1))

    def _frame_bytes(self):
        if self.nv12:
            fh = self.h * 2 if self.alpha == "stacked" else self.h
            return self.w * fh * 3 // 2
        return self.w * self.h * 4

    def _start(self):
        self.proc = subprocess.Popen(self._cmd(), stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                     bufsize=0, start_new_session=True)
        self.ready = threading.Event()
        threading.Thread(target=self._read, args=(self.proc.stdout, self.stop, self.taken, self.ready),
                         daemon=True, name="videoloop").start()

    def _read(self, f, stop, taken, ready):
        n = self._frame_bytes()
        while not stop.is_set():
            taken.wait()                              # paused until the last frame is used
            if stop.is_set():
                break
            buf = bytearray(n)
            view = memoryview(buf)
            got = 0
            try:
                while got < n:
                    k = f.readinto(view[got:])
                    if not k:
                        self.ended = True               # a one-shot clip's end: hold the last frame
                        ready.set()
                        return
                    got += k
            except (OSError, ValueError):
                return
            with self.lock:
                if stop.is_set():
                    return
                self.frame = buf
                taken.clear()
                ready.set()

    # ---- the render thread
    def advance(self, dt):
        """Advance the loop's clock by dt (the frame's time) and upload a new frame when one is
        due. Returns the texture (None until the first frame arrives)."""
        self.last_use = time.monotonic()
        if self.proc is None and not self.cached:
            self._start()
        self.clock += max(0.0, min(dt, 0.25))
        due = int(self.clock * self.fps)
        if self.cached:                                    # playing from the GPU
            k = due % len(self.frames)
            if k != self.shown:
                self._convert(self.frames[k])
                self.shown = k
            return self.tex
        if due != self.shown:
            if self.sync and not self.ended:
                self.ready.wait(5.0)
            with self.lock:
                self.ready.clear()
                buf, self.frame = self.frame, None
            if buf is not None:
                self._upload(buf)
                self.shown = due
                self.taken.set()
            elif self.cache_on and self.ended and self.frames:
                self.cached = True                         # the whole loop is on the GPU: stop decoding
                self.close(keep_texture=True)
                self.clock = 0.0
                self.shown = -1
        return self.tex

    def finished(self):
        """A one-shot clip has shown its last frame."""
        return self.once and self.ended and self.frame is None

    def restart(self):
        """Play a one-shot clip again from its first frame."""
        self.close(keep_texture=True)
        self.clock, self.shown, self.ended = 0.0, -1, False

    def _mask(self):
        """The clip's feathered edge mask (<name>-mask.png), as a texture (NV12 path) and an array."""
        if self.mask_tex is None and self.mask_path:
            from PIL import Image
            m = Image.open(self.mask_path).convert("L").resize((self.w, self.h), Image.BILINEAR)
            self.mask_arr = np.asarray(m, np.uint8)
            self.mask_tex = GL.glGenTextures(1)
            GL.glBindTexture(GL.GL_TEXTURE_2D, self.mask_tex)
            GL.glPixelStorei(GL.GL_UNPACK_ALIGNMENT, 1)
            GL.glTexImage2D(GL.GL_TEXTURE_2D, 0, GL.GL_R8, self.w, self.h, 0, GL.GL_RED, GL.GL_UNSIGNED_BYTE,
                            np.ascontiguousarray(self.mask_arr))
            for p, v in ((GL.GL_TEXTURE_MIN_FILTER, GL.GL_LINEAR), (GL.GL_TEXTURE_MAG_FILTER, GL.GL_LINEAR)):
                GL.glTexParameteri(GL.GL_TEXTURE_2D, p, v)
        return self.mask_tex

    def _upload(self, buf):
        if self.nv12:
            return self._upload_nv12(buf)
        if self.tex is None:
            self.tex = GL.glGenTextures(1)
            GL.glBindTexture(GL.GL_TEXTURE_2D, self.tex)
            GL.glPixelStorei(GL.GL_UNPACK_ALIGNMENT, 1)
            GL.glTexImage2D(GL.GL_TEXTURE_2D, 0, GL.GL_RGBA8, self.w, self.h, 0, GL.GL_RGBA, GL.GL_UNSIGNED_BYTE, None)
            for p, v in ((GL.GL_TEXTURE_MIN_FILTER, GL.GL_LINEAR), (GL.GL_TEXTURE_MAG_FILTER, GL.GL_LINEAR),
                         (GL.GL_TEXTURE_WRAP_S, GL.GL_CLAMP_TO_EDGE), (GL.GL_TEXTURE_WRAP_T, GL.GL_CLAMP_TO_EDGE)):
                GL.glTexParameteri(GL.GL_TEXTURE_2D, p, v)
        a = np.frombuffer(buf, np.uint8).reshape(self.h, self.w, 4)
        if self.alpha != "none" or self.mask_path:   # premultiply, like every other world texture
            a = a.copy()
            if self._mask() is not None:
                a[..., 3] = (a[..., 3].astype(np.uint16) * self.mask_arr // 255).astype(np.uint8)
            a[..., :3] = (a[..., :3].astype(np.uint16) * a[..., 3:4] // 255).astype(np.uint8)
        GL.glBindTexture(GL.GL_TEXTURE_2D, self.tex)
        GL.glPixelStorei(GL.GL_UNPACK_ALIGNMENT, 1)
        GL.glTexSubImage2D(GL.GL_TEXTURE_2D, 0, 0, 0, self.w, self.h, GL.GL_RGBA, GL.GL_UNSIGNED_BYTE, a)

    def _new_planes(self):
        fh = self.h * 2 if self.alpha == "stacked" else self.h
        planes = GL.glGenTextures(2)
        for t, (fmt, w, h) in zip(planes, ((GL.GL_R8, self.w, fh), (GL.GL_RG8, self.w // 2, fh // 2))):
            GL.glBindTexture(GL.GL_TEXTURE_2D, t)
            GL.glTexImage2D(GL.GL_TEXTURE_2D, 0, fmt, w, h, 0, GL.GL_RED if fmt == GL.GL_R8 else GL.GL_RG,
                            GL.GL_UNSIGNED_BYTE, None)
            for p, v in ((GL.GL_TEXTURE_MIN_FILTER, GL.GL_LINEAR), (GL.GL_TEXTURE_MAG_FILTER, GL.GL_LINEAR),
                         (GL.GL_TEXTURE_WRAP_S, GL.GL_CLAMP_TO_EDGE), (GL.GL_TEXTURE_WRAP_T, GL.GL_CLAMP_TO_EDGE)):
                GL.glTexParameteri(GL.GL_TEXTURE_2D, p, v)
        return list(planes)

    def _upload_nv12(self, buf):
        """The frame's Y and UV planes into textures (their own, kept, while a loop's first pass is
        being cached), then converted into the RGBA target."""
        from . import glkit
        fh = self.h * 2 if self.alpha == "stacked" else self.h
        if self.target is None:
            self.target = glkit.Target(self.w, self.h)
            self.tex = self.target.tex
            self.planes = self._new_planes()
            # one converter per GL context: a world switch or a healed surface brings a new
            # context, and a program id from the old one is invalid there (GL_INVALID_VALUE)
            import sys
            Gdk = sys.modules.get("gi.repository.Gdk")  # the live layer's; headless (tools/offscreen.py) has
            ctx = Gdk.GLContext.get_current() if Gdk else None   # one EGL context and no Gdk
            if getattr(VideoLoop, "_prog", None) is None or getattr(VideoLoop, "_ctx", None) is not ctx:
                VideoLoop._ctx = ctx
                VideoLoop._prog = glkit.program("fs.vert", "world_yuv.frag")
                VideoLoop._fs = glkit.Fullscreen()
        planes = self._new_planes() if self.cache_on else self.planes
        a = np.frombuffer(buf, np.uint8)
        ysz = self.w * fh
        GL.glPixelStorei(GL.GL_UNPACK_ALIGNMENT, 1)
        GL.glBindTexture(GL.GL_TEXTURE_2D, planes[0])
        GL.glTexSubImage2D(GL.GL_TEXTURE_2D, 0, 0, 0, self.w, fh, GL.GL_RED, GL.GL_UNSIGNED_BYTE, a[:ysz])
        GL.glBindTexture(GL.GL_TEXTURE_2D, planes[1])
        GL.glTexSubImage2D(GL.GL_TEXTURE_2D, 0, 0, 0, self.w // 2, fh // 2, GL.GL_RG, GL.GL_UNSIGNED_BYTE, a[ysz:])
        if self.cache_on:
            self.frames.append(planes)
        self._convert(planes)

    def _convert(self, planes):
        """NV12 planes to the premultiplied RGBA target. Called at the start of a frame, before any
        pass binds its own target, so nothing needs restoring but the blend state."""
        blend = GL.glIsEnabled(GL.GL_BLEND)
        GL.glDisable(GL.GL_BLEND)
        # the mask first: making it binds a texture on the active unit, and done after the planes
        # it took unit 1 from the UV plane (the first frame of a masked clip came out blue-green)
        mt = self._mask()
        self.target.bind()
        p = VideoLoop._prog
        p.use()
        GL.glActiveTexture(GL.GL_TEXTURE0)
        GL.glBindTexture(GL.GL_TEXTURE_2D, planes[0])
        GL.glActiveTexture(GL.GL_TEXTURE1)
        GL.glBindTexture(GL.GL_TEXTURE_2D, planes[1])
        GL.glActiveTexture(GL.GL_TEXTURE2)
        GL.glBindTexture(GL.GL_TEXTURE_2D, mt or planes[0])
        p.i("u_y", 0)
        p.i("u_uv", 1)
        p.i("u_mask", 2)
        p.f("u_has_mask", 1.0 if mt else 0.0)
        p.f("u_stacked", 1.0 if self.alpha == "stacked" else 0.0)
        p.f("u_luma", 1.0 if self.alpha == "luma" else 0.0)
        p.f("u_bt709", 1.0 if self.h > 576 else 0.0)
        VideoLoop._fs.draw()
        GL.glActiveTexture(GL.GL_TEXTURE0)
        if blend:
            GL.glEnable(GL.GL_BLEND)

    def _free_frames(self):
        for planes in self.frames:
            try:
                GL.glDeleteTextures(planes)
            except Exception:
                pass
        self.frames = []
        self.cached = False

    def idle_check(self, now, after=20.0):
        if self.cached and now - self.last_use > 60.0:     # a loop not drawn for a minute gives its VRAM back
            self._free_frames()
        """Stop the decoder of a loop that hasn't been drawn for a while (it restarts on use)."""
        if self.proc is not None and now - self.last_use > after:
            self.close(keep_texture=True)

    def close(self, keep_texture=False):
        self.stop.set()
        self.taken.set()
        if self.proc is not None:
            try:
                self.proc.kill()
                self.proc.wait(timeout=2)
            except Exception:
                pass
        self.proc = None
        self.stop = threading.Event()
        self.taken = threading.Event()
        self.taken.set()
        if not keep_texture:
            self._free_frames()
        if not keep_texture and self.tex is not None:
            try:
                if self.target is not None:
                    self.target.free()
                    GL.glDeleteTextures(list(self.planes))
                else:
                    GL.glDeleteTextures([self.tex])
            except Exception:
                pass
            self.tex = self.target = self.planes = None
