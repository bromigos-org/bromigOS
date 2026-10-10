"""libmpv drawing into a GL texture: the den TV's picture (live/live/tv.py).

mpv decodes on its own threads, on the GPU where it can (hwdec=auto: NVDEC on NVIDIA,
VA-API elsewhere), and draws each new frame into our framebuffer through its render API
(mpv_render_context, OpenGL). We ask for a frame only when the live layer draws one, never
blocking for a frame's time, and the TV's own texture is small: the screen's size.

python-mpv (Arch: python-mpv) is the binding. Without it, or without libmpv, available()
says why and the TV shows posters only.

    p = Player(log=print)                 # with the GL context current
    p.load(url, start=312.5, headers={...}, ytdl_format=None)
    tex = p.frame(320, 240)               # each drawn frame: the texture, or None until one is ready
    p.pause(True); p.sound(True, 60); p.close()
"""
import ctypes
import threading

from OpenGL import GL

_mpv = None
_why = None


def available():
    """(True, "") or (False, why)."""
    global _mpv, _why
    if _mpv is not None:
        return True, ""
    if _why is not None:
        return False, _why
    try:
        import mpv
        _mpv = mpv
        return True, ""
    except (ImportError, OSError) as e:
        _why = f"python-mpv isn't installed ({type(e).__name__}): sudo pacman -S python-mpv"
        return False, _why


def _proc_address():
    """GL functions for mpv, from EGL (GTK's GL on Wayland, and the offscreen renders)."""
    egl = ctypes.CDLL("libEGL.so.1")
    egl.eglGetProcAddress.restype = ctypes.c_void_p
    egl.eglGetProcAddress.argtypes = [ctypes.c_char_p]

    def get(_ctx, name):
        return egl.eglGetProcAddress(name) or 0
    return get


class Player:
    def __init__(self, log=print, client_name="bromigOS den TV", tls_ca=None, ytdl_format=None):
        ok, why = available()
        if not ok:
            raise RuntimeError(why)
        mpv = _mpv
        self.log = log
        opts = dict(vo="libmpv", hwdec="auto", aid="no", mute=True, keep_open="yes", idle=True, ytdl=True,
                    input_default_bindings=False, input_vo_keyboard=False, osc=False, terminal=False,
                    audio_client_name=client_name, cache="yes", demuxer_max_bytes="32MiB",
                    demuxer_readahead_secs=20, hr_seek="yes", volume_max=100, sub="no",
                    ytdl_format=ytdl_format or "bestvideo[height<=480]+bestaudio/best[height<=480]/best")
        if tls_ca:
            opts.update(tls_ca_file=tls_ca, tls_verify=True)
        self.m = mpv.MPV(log_handler=self._log, loglevel="warn", **opts)
        self._get = mpv.MpvGlGetProcAddressFn(_proc_address())
        self.ctx = mpv.MpvRenderContext(self.m, "opengl", opengl_init_params={"get_proc_address": self._get})
        self._fresh = threading.Event()
        self.ctx.update_cb = self._fresh.set
        self.fbo = self.tex = None
        self.size = (0, 0)
        self.has_frame = False
        self.ended = None                     # (reason, error) of the last end-file, from mpv's thread
        self.started = False

        @self.m.event_callback("end-file")
        def _end(ev):
            try:
                d = ev.data                                     # MpvEventEndFile: reason 0 eof, 4 error
                self.ended = ({0: "eof", 1: "restarted", 2: "stop", 3: "quit", 4: "error"}.get(d.reason, "other"),
                              d.error)
            except Exception:                                   # noqa: BLE001
                self.ended = ("error", None)

        @self.m.event_callback("file-loaded")
        def _loaded(_ev):
            self.started = True
            self.ended = None

    def _log(self, level, prefix, text):
        if level in ("error", "fatal", "warn"):
            self.log(f"tv: mpv {prefix}: {text.strip()[:200]}")

    # ---- control (any thread: mpv's properties are thread safe)
    def load(self, url, start=None, headers=None, ytdl_format=None, title=""):
        self.has_frame = self.started = False
        self.ended = None
        self.m["http-header-fields"] = [f"{k}: {v}" for k, v in (headers or {}).items()]
        if ytdl_format:
            self.m["ytdl-format"] = ytdl_format
        opts = {"force-media-title": title} if title else {}
        if start:
            opts["start"] = f"{max(0.0, float(start)):.2f}"
        self.m.loadfile(url, "replace", **opts)

    def seek(self, pos):
        try:
            self.m.command_async("seek", f"{max(0.0, float(pos)):.2f}", "absolute+exact")
        except Exception:                                       # noqa: BLE001  not loaded yet
            pass

    def position(self):
        try:
            return self.m.time_pos
        except Exception:                                       # noqa: BLE001
            return None

    def pause(self, on):
        if bool(self.m.pause) != bool(on):
            self.m.pause = bool(on)

    def paused(self):
        return bool(self.m.pause)

    def sound(self, on, volume):
        """Sound on (the audio track decoded, unmuted) or off (no audio decoded at all)."""
        want_aid = "auto" if on else "no"
        if str(self.m["aid"]) != want_aid:
            self.m["aid"] = want_aid
        self.m.volume = max(0, min(100, int(volume)))
        self.m.mute = not on

    def stop(self):
        self.has_frame = False
        try:
            self.m.command_async("stop")
        except Exception:                                       # noqa: BLE001
            pass

    # ---- drawing (the render thread, with our GL context current)
    def _target(self, w, h):
        if (w, h) == self.size and self.tex:
            return
        self._free_target()
        self.tex = GL.glGenTextures(1)
        GL.glBindTexture(GL.GL_TEXTURE_2D, self.tex)
        GL.glTexImage2D(GL.GL_TEXTURE_2D, 0, GL.GL_RGBA8, w, h, 0, GL.GL_RGBA, GL.GL_UNSIGNED_BYTE, None)
        GL.glTexParameteri(GL.GL_TEXTURE_2D, GL.GL_TEXTURE_MAX_LEVEL, 4)
        for p, v in ((GL.GL_TEXTURE_MIN_FILTER, GL.GL_LINEAR_MIPMAP_LINEAR), (GL.GL_TEXTURE_MAG_FILTER, GL.GL_LINEAR),
                     (GL.GL_TEXTURE_WRAP_S, GL.GL_CLAMP_TO_EDGE), (GL.GL_TEXTURE_WRAP_T, GL.GL_CLAMP_TO_EDGE)):
            GL.glTexParameteri(GL.GL_TEXTURE_2D, p, v)
        self.fbo = GL.glGenFramebuffers(1)
        GL.glBindFramebuffer(GL.GL_FRAMEBUFFER, self.fbo)
        GL.glFramebufferTexture2D(GL.GL_FRAMEBUFFER, GL.GL_COLOR_ATTACHMENT0, GL.GL_TEXTURE_2D, self.tex, 0)
        GL.glClearColor(0, 0, 0, 1)
        GL.glClear(GL.GL_COLOR_BUFFER_BIT)
        GL.glGenerateMipmap(GL.GL_TEXTURE_2D)
        self.size = (w, h)
        self.has_frame = False

    def frame(self, w, h):
        """Draw mpv's newest frame, if there is one, into our w x h texture; the texture
        once a frame has been drawn, else None. Never waits."""
        prev = GL.glGetIntegerv(GL.GL_DRAW_FRAMEBUFFER_BINDING)
        vp = GL.glGetIntegerv(GL.GL_VIEWPORT)
        self._target(int(w), int(h))
        if self._fresh.is_set():
            self._fresh.clear()
            if self.ctx.update():
                self.ctx.render(opengl_fbo={"w": self.size[0], "h": self.size[1], "fbo": int(self.fbo)},
                                flip_y=False, block_for_target_time=False)
                for _ in range(16):                    # an error mpv's own GL left behind isn't ours
                    if GL.glGetError() == GL.GL_NO_ERROR:
                        break
                self.has_frame = True
                GL.glBindTexture(GL.GL_TEXTURE_2D, self.tex)       # the glow reads a blurred level
                GL.glGenerateMipmap(GL.GL_TEXTURE_2D)
        # mpv leaves its own GL state behind: give the scene back what it had
        GL.glBindFramebuffer(GL.GL_FRAMEBUFFER, int(prev))
        GL.glViewport(*[int(x) for x in vp])
        GL.glDisable(GL.GL_BLEND)
        GL.glDisable(GL.GL_SCISSOR_TEST)
        GL.glActiveTexture(GL.GL_TEXTURE0)
        GL.glPixelStorei(GL.GL_UNPACK_ALIGNMENT, 4)
        return self.tex if self.has_frame else None

    def _free_target(self):
        if self.fbo:
            GL.glDeleteFramebuffers(1, [self.fbo])
        if self.tex:
            GL.glDeleteTextures([self.tex])
        self.fbo = self.tex = None
        self.size = (0, 0)

    def close(self):
        """With the GL context current: free the render context first, then mpv."""
        try:
            self.ctx.free()
        except Exception:                                       # noqa: BLE001
            pass
        try:
            self._free_target()
        except Exception:                                       # noqa: BLE001
            pass
        try:
            self.m.terminate()
        except Exception:                                       # noqa: BLE001
            pass
