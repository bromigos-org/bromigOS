"""The den TV: channels on the den's screens, from your own Plex or Jellyfin library or
YouTube, playing as if live (lib/bromigos_tv.py has the channels and the schedule).

Each of the den's three screens (the big monitor, the scope, the small monitor) has a
channel list. Channel 1 is the screen's own picture, drawn as it always was. The media
channels come after it. One media channel plays at a time: tuning a second screen to one
sends the first back to its own picture.

    the picture   libmpv (live/live/mpvgl.py) decodes on the GPU into a texture the size of
                  the screen, muted unless you turn the sound on; bg.frag draws it in the
                  screen's glass with scanlines, curvature and glow.
    pausing       decoding runs only while the live layer draws and the screen is in view:
                  no frames drawn for a second (locked, a fullscreen window, a deck, the
                  screensaver), or a window over the screen, pauses mpv. Coming back, the
                  channel jumps to where it would be now. Still motion (or no GPU) shows the
                  item's poster instead; reduced motion a still frame, renewed every 30 s,
                  unless the sound is on.
    the pointer   the background window takes the pointer over the den's screens only (its
                  input region), and over the hint while it shows. Over a screen: the hint
                  (what's on, the channel buttons, the speaker, the volume, Full screen and
                  Watch in Plex/Jellyfin/YouTube). A click opens the channel in mpv, full
                  screen with sound, at the same moment; scroll changes channel, Shift+scroll
                  the volume.
    sound         off by default, remembered per screen with its volume. bromigOS's mute,
                  the lock screen and the screensaver silence it; VECTOR speaking (or a
                  codec call) ducks it to [tv] duck percent. PipeWire sees it as
                  "bromigOS den TV".

Nothing here touches the network on the drawing thread: a worker thread reads the channels'
lists (cached), YouTube's live streams, posters and YouTube downloads (`keep`).
"""
import io
import os
import shutil
import subprocess
import tempfile
import threading
import time

from OpenGL import GL

from . import LIB  # noqa: F401  (the shared libs on sys.path)
import bromigos_tv as TVL  # noqa: E402

SHADER_INDEX = {"wave": 1, "emblem": 2, "big": 3}
LOW_FORMAT = "bestvideo[height<=480]+bestaudio/best[height<=480]/best"
LOW_FORMAT_MUTED = "bestvideo[height<=480]/best[height<=480]/best"
FULL_FORMAT = "bestvideo[height<=1080]+bestaudio/best"
TUNE_STATIC = 0.35            # seconds of static when a channel changes (full motion)
TUNE_OSD = 1.6                # seconds the channel number shows
VOLUME_OSD = 1.3
REDUCED_EVERY = 30.0          # reduced motion: a new still frame this often
DRIFT = 3.0                   # seconds off the schedule before the picture is put back
HINT_W, HINT_H = 404, 112     # the hover hint, logical px


MONO = time.monotonic          # the TV's clock (the offscreen tests fix the scene's, not this)


def _mono():
    return MONO()



SYSTEM_CAS = ("/etc/ssl/certs/ca-certificates.crt", "/etc/ca-certificates/extracted/tls-ca-bundle.pem",
              "/etc/ssl/cert.pem")


def tls_bundle(extra, system=SYSTEM_CAS, out_dir=None):
    """A CA bundle of the system's roots and `extra` (a lab's own CA), written once to the
    runtime dir and rewritten when either changes; `extra` alone when no system bundle is found."""
    sysf = next((f for f in system if os.path.isfile(f)), None)
    if not sysf:
        return extra
    out_dir = out_dir or os.environ.get("XDG_RUNTIME_DIR") or tempfile.gettempdir()
    out = os.path.join(out_dir, "bromigos-tv-ca.pem")
    try:
        newest = max(os.path.getmtime(sysf), os.path.getmtime(extra))
        if os.path.isfile(out) and os.path.getmtime(out) >= newest:
            return out
        with open(sysf, "rb") as a, open(extra, "rb") as b:
            data = a.read().rstrip(b"\n") + b"\n" + b.read()
        tmp = out + ".tmp"
        with open(tmp, "wb") as f:
            f.write(data)
        os.replace(tmp, out)
        return out
    except OSError:
        return extra

class TV:
    def __init__(self, cfg, log=print):
        self.cfg = cfg
        self.log = log
        st = TVL.state()
        conf = self.conf()
        self.screens = {s: TVL.screen_state(st, s, int(conf.get("volume", TVL.DEFAULT_VOLUME))) for s in TVL.SCREENS}
        self.live = {}                     # YouTube live streams now: channel key -> video
        self.fails = {}                    # channel key -> [(when, item id)] that wouldn't play
        self.retry_at = {}                 # channel key -> when to try its server again
        self._lineups = {}
        self.player = None
        self.player_why = ""               # why there's no picture (no python-mpv, a failure)
        self.loaded = None                 # (channel key, item id) in mpv
        self.loaded_at = 0.0
        self.allowed = False               # drawing and in view: decode
        self.drawn_at = 0.0
        self.covered = set()
        self.quiet = False                 # locked or the screensaver: no sound
        self.ducked = False
        self.motion = "full"
        self.software = False
        self.tune = None                   # (screen, monotonic start, number, name)
        self.vol_osd = None                # (screen, monotonic start)
        self.poster = {}                   # item id -> (rgba bytes, w, h) from the worker
        self.poster_tex = None             # (item id, texture, w, h)
        self.osd_tex = None
        self.osd_sig = None
        self.hint_tex = None
        self.hint_sig = None
        self.hover = None                  # the screen the pointer is over (or its hint)
        self.hint_rect = None              # logical x, y, w, h
        self.hint_until = 0.0
        self.buttons = []                  # (x, y, w, h, action) in the hint, logical px
        self.dragging = False
        self.layout_info = (2560, 1440, (0, 0), 1)
        self.rects = {}                    # screen -> logical rect
        self.px = {}                       # screen -> render px rect
        self.last_slot = {}
        self.slot_at = 0.0
        self.reduced_at = 0.0
        self.full_proc = None
        self.on_change = None              # the app: input region, redraw
        self.keeper = None
        self.stop = threading.Event()
        self.wake = threading.Event()
        self.worker = threading.Thread(target=self._work, daemon=True, name="den-tv")
        self.worker.start()

    # ------------------------------------------------------------------ config
    def conf(self):
        return self.cfg.get("tv") or {}

    def enabled(self):
        return self.conf().get("enabled", True) is not False

    def lineup(self, screen):
        """The screen's channels (the config and the media panel's file, read every 2 s at most)."""
        now = _mono()
        hit = self._lineups.get(screen)
        if hit and now - hit[0] < 2.0 and hit[2] == len(self.live):
            return hit[1]
        lu = TVL.lineup(self.cfg, screen, self.live) if self.enabled() else [TVL.own_channel(screen)]
        self._lineups[screen] = (now, lu, len(self.live))
        return lu

    def channel(self, screen):
        """(number from 1, channel) on a screen now."""
        lu = self.lineup(screen)
        key = self.screens[screen]["channel"]
        for n, ch in enumerate(lu):
            if ch["key"] == key:
                return n + 1, ch
        return 1, lu[0]

    def media_screen(self):
        """(screen, channel) showing a media channel, or (None, None)."""
        for s in ("big", "wave", "emblem"):
            n, ch = self.channel(s)
            if ch["kind"] != "own":
                return s, ch
        return None, None

    def interactive(self):
        """The screens that have more than one channel (the pointer's region)."""
        return [s for s in TVL.SCREENS if len(self.lineup(s)) > 1]

    def save(self):
        TVL.save_state({"screens": {s: dict(v) for s, v in self.screens.items()}})

    # ------------------------------------------------------------------ the schedule
    def slot(self, ch):
        if ch is None or ch["kind"] == "own":
            return None
        now = _mono()
        hit = self.last_slot.get(ch["key"])
        if hit and now - hit[0] < 0.5:
            return hit[1]
        s = TVL.now_next(ch)
        self.last_slot[ch["key"]] = (now, s)
        return s

    # ------------------------------------------------------------------ changing channel
    def tune_to(self, screen, number=None, step=0):
        lu = self.lineup(screen)
        cur, _ = self.channel(screen)
        n = number if number is not None else cur + step
        n = (n - 1) % len(lu) + 1
        ch = lu[n - 1]
        self.screens[screen]["channel"] = ch["key"]
        if ch["kind"] != "own":                       # one media channel at a time
            for other in TVL.SCREENS:
                if other != screen and self.channel(other)[1]["kind"] != "own":
                    self.screens[other]["channel"] = "own"
        self.save()
        self.tune = (screen, _mono(), n, ch["name"])
        self.last_slot.pop(ch["key"], None)
        self.wake.set()
        self._changed()
        self.log(f"tv: {TVL.SCREEN_NAMES.get(screen, screen)} on channel {n}, {ch['name']}")
        return f"{screen}: channel {n} of {len(lu)}, {ch['name']}"

    def _changed(self):
        self.hint_sig = None
        if self.on_change:
            try:
                self.on_change()
            except Exception:                                   # noqa: BLE001
                pass

    # ------------------------------------------------------------------ sound
    def set_sound(self, screen, on=None, volume=None):
        s = self.screens[screen]
        if volume is not None:
            v = max(0, min(100, int(round(volume))))
            if v > s["volume"] and not s["sound"] and on is None:
                on = True                                       # turning it up turns it on
            s["volume"] = v
            self.vol_osd = (screen, _mono())
        if on is not None:
            s["sound"] = bool(on)
        self.save()
        self._apply_sound()
        self._changed()
        return f"{screen}: sound {'on' if s['sound'] else 'off'}, volume {s['volume']}%"

    def _effective_sound(self):
        screen, ch = self.media_screen()
        if not screen:
            return False, 0
        s = self.screens[screen]
        from .sound import muted
        on = s["sound"] and not self.quiet and not muted() and self.allowed
        vol = s["volume"] * (float(self.conf().get("duck", 30)) / 100.0 if self.ducked else 1.0)
        return on, vol

    def _apply_sound(self):
        if self.player is None:
            return
        on, vol = self._effective_sound()
        try:
            self.player.sound(on, vol)
        except Exception as e:                                  # noqa: BLE001
            self.log(f"tv: sound: {e}")

    # ------------------------------------------------------------------ the app's tick (0.5 s)
    def tick(self, covered=None, quiet=False, ducked=False, motion="full", software=False):
        """Play or pause: frames drawn in the last second, the screen not covered, not still."""
        self.covered = set(covered or ())
        self.quiet, self.ducked = quiet, ducked
        self.motion, self.software = motion, software
        screen, ch = self.media_screen()
        drawing = _mono() - self.drawn_at < 1.2
        sound_on = screen is not None and self.screens[screen]["sound"]
        want = (screen is not None and drawing and screen not in self.covered and not software
                and (motion == "full" or (motion == "reduced" and sound_on)))
        was = self.allowed
        self.allowed = want
        if self.player is not None:
            if want and not was and self.loaded:
                slot = self.slot(ch)
                if slot and slot.offset is not None:
                    self.player.seek(slot.offset)             # back on: where the channel is now
            try:
                if not (self.motion == "reduced" and not sound_on and screen is not None):
                    self.player.pause(not want)
            except Exception:                                   # noqa: BLE001
                pass
            self._apply_sound()
        if self.full_proc is not None and self.full_proc.poll() is not None:
            self.full_proc = None
            self.log("tv: full screen closed; back to the den")

    # ------------------------------------------------------------------ the frame (GL thread)
    def layout(self, w, h, px_rects, view=(0, 0), sf=1):
        """The scene's size, each den screen's rect in render px, the visible window's
        offset in it (a cover crop) and the monitor's scale: the logical rects for the pointer."""
        info = (w, h, tuple(view), sf)
        self.px = px_rects
        if info == self.layout_info and self.rects:
            return
        self.layout_info = info
        vx, vy = view
        self.rects = {s: ((x - vx) / sf, (y - vy) / sf, rw / sf, rh / sf) for s, (x, y, rw, rh) in px_rects.items()}
        self._changed()

    def gl(self):
        """Per frame, with the scene's GL context current: the uniforms bg.frag needs."""
        self.drawn_at = _mono()
        out = {"tv": (0.0, 0.0, 1.0, 0.0), "tvtex": 0, "tune": (0.0, 0.0, 0.0, 0.0), "osd": 0}
        screen, ch = self.media_screen()
        tint = float(self.conf().get("tint", 0.4))
        if screen:
            x, y, w, h = self.px.get(screen, (0, 0, 320, 240))
            tex, aspect = self._picture(screen, ch, max(64, int(w * 1.5)), max(48, int(h * 1.5)), w / max(h, 1))
            out["tv"] = (float(SHADER_INDEX[screen]), 1.0 if tex else 0.0, aspect, tint)
            out["tvtex"] = tex or 0
        elif self.player is not None and _mono() - self.loaded_at > 30:
            self._close_player()                               # nothing on for a while: give it back
        osd_screen, static, osd = self._osd(screen)
        if osd_screen:
            out["tune"] = (float(SHADER_INDEX[osd_screen]), static, 1.0 if osd else 0.0, 0.0)
            out["osd"] = osd or 0
        return out

    def _picture(self, screen, ch, w, h, screen_aspect):
        """(texture, its aspect over the screen's) for the media screen: mpv's frame, or the
        poster (still motion, no mpv, loading), or (None, 1) for static."""
        slot = self.slot(ch)
        item = slot.item if slot else None
        poster_only = self.motion == "still" or self.software or not self._player_ok()
        if not poster_only and item is not None:
            self._ensure_loaded(ch, slot)
            if self.motion == "reduced" and not self.screens[screen]["sound"]:
                now = _mono()
                if now - self.reduced_at > REDUCED_EVERY and self.loaded:
                    self.reduced_at = now
                    self.player.pause(True)
                    if slot.offset is not None:
                        self.player.seek(slot.offset)
            self._check_failure(ch, slot)
            tex = self.player.frame(w, h)
            if tex:
                return tex, 1.0
        p = self._poster_texture(item)
        if p:
            return p[0], (p[1] / max(p[2], 1)) / max(screen_aspect, 1e-3)
        return None, 1.0

    def _player_ok(self):
        if self.player is not None:
            return True
        if self.player_why:
            return False
        from . import mpvgl
        ok, why = mpvgl.available()
        if not ok:
            self.player_why = why
            self.log(f"tv: {why}; posters only")
            return False
        try:
            self.player = mpvgl.Player(log=self.log, tls_ca=self._tls_ca(), ytdl_format=LOW_FORMAT_MUTED)
            self._apply_sound()
            return True
        except Exception as e:                                  # noqa: BLE001
            self.player_why = f"{type(e).__name__}: {e}"
            self.log(f"tv: no picture ({self.player_why}); posters only")
            return False

    def _tls_ca(self):
        """The CA file for mpv: the system's trusted roots plus the lab's own CA, in one bundle.
        mpv's tls-ca-file replaces the trust store, so the lab's CA alone would fail every
        other site (YouTube's streams) with "Peer certificate failed verification"."""
        H = TVL._homelab()
        if H is None:
            return None
        try:
            ca = H.config.expand(H.config.setting("tls", "ca_file", ""))
        except Exception:                                       # noqa: BLE001
            return None
        if not ca or not os.path.isfile(ca):
            return None
        return tls_bundle(ca)

    def stream(self, ch, slot, full=False):
        """{"url", "headers", "ytdl_format", "title", "start", "web", "kind"} for what's on, or None."""
        if slot is None:
            return None
        it = slot.item
        title = TVL.label(it)
        if ch["kind"] == "live":
            return {"url": it.get("url"), "headers": {}, "ytdl_format": FULL_FORMAT if full else LOW_FORMAT_MUTED,
                    "title": title, "start": None, "web": it.get("url"), "server": "YouTube"}
        if ch["kind"] == "files":
            return {"url": it.get("url"), "headers": {}, "ytdl_format": None, "title": title, "start": slot.offset,
                    "web": None, "server": "Files"}
        if ch["kind"] == "youtube":
            import bromigos_youtube as Y
            path = Y.kept(ch.get("keep"), it.get("id")) if ch.get("keep") else None
            fmt = FULL_FORMAT if full else (LOW_FORMAT if self._effective_sound()[0] else LOW_FORMAT_MUTED)
            return {"url": path or it.get("url"), "headers": {}, "ytdl_format": None if path else fmt, "title": title,
                    "start": slot.offset, "web": it.get("url"), "server": "YouTube", "kept": bool(path)}
        a = TVL.server_of(ch)
        if a is None:
            return None
        q = self.conf().get("fullscreen_quality", "direct") if full else self.conf().get("quality", "auto")
        s = a.video_stream(it, q)
        return {"url": s["url"], "headers": s["headers"], "ytdl_format": None, "title": title, "start": slot.offset,
                "web": None, "server": {"jellyfin": "Jellyfin", "plex": "Plex"}.get(a.type, a.type), "adapter": a}

    def _ensure_loaded(self, ch, slot):
        want = (ch["key"], str(slot.item.get("id")))
        if self.loaded == want or _mono() < self.retry_at.get(ch["key"], 0):
            return
        try:
            s = self.stream(ch, slot)
        except Exception as e:                                  # noqa: BLE001
            s = None
            self.log(f"tv: no stream for {TVL.label(slot.item)}: {e}")
        self.loaded = want
        self.loaded_at = _mono()
        if not s or not s.get("url"):
            return
        start = (slot.offset + 1.0) if slot.offset is not None else None      # the second it takes to open
        self.player.load(s["url"], start=start, headers=s["headers"], ytdl_format=s.get("ytdl_format"),
                         title=s["title"])
        self.player.pause(not self.allowed and not self.motion == "reduced")
        self._apply_sound()
        self.log(f"tv: playing {s['title']}" + (f" from {TVL.fmt_time(slot.offset)}" if slot.offset else ""))
        self._keep(ch, slot)

    def _check_failure(self, ch, slot):
        """An item that won't play is skipped (left out of the schedule for a day), never a
        stalled screen: an error from mpv, or nothing after 25 s of trying while allowed."""
        p = self.player
        if not self.loaded or p is None:
            return
        failed = p.ended is not None and p.ended[0] == "error"
        slow = (not p.started and self.allowed and _mono() - self.loaded_at > 25)
        if failed or slow:
            iid = self.loaded[1]
            now = _mono()
            recent = [(t, i) for t, i in self.fails.get(ch["key"], []) if now - t < 120] + [(now, iid)]
            self.fails[ch["key"]] = recent
            if len(recent) >= 3:
                # three in two minutes: the server (or the network), not the items. Put them
                # back and try again in a minute, on static, rather than skip the whole list.
                TVL.unmark_bad([i for _, i in recent])
                self.fails[ch["key"]] = []
                self.retry_at[ch["key"]] = now + 60
                self.log(f"tv: {ch['name']} isn't answering; trying again in a minute")
            else:
                self.log(f"tv: {TVL.label(slot.item)} didn't play ({'error' if failed else 'no answer'}); skipping it")
                TVL.mark_bad(iid)
            self.last_slot.pop(ch["key"], None)
            self.loaded = None
            p.ended = None
            p.stop()
            return
        # drift: mpv's clock against the wall clock, now and then
        if p.started and self.allowed and slot.offset is not None and _mono() - self.loaded_at > 8:
            if int(_mono()) % 10 == 0:
                pos = p.position()
                if pos is not None and abs(pos - slot.offset) > DRIFT and slot.offset < (slot.item.get("duration") or 0) - 2:
                    p.seek(slot.offset)

    def _poster_texture(self, item):
        if not item:
            return None
        iid = str(item.get("id"))
        if self.poster_tex and self.poster_tex[0] == iid:
            return self.poster_tex[1:]
        img = self.poster.get(iid)
        if img is None:
            return None
        data, w, h = img
        from . import glkit
        if self.poster_tex:
            GL.glDeleteTextures([self.poster_tex[1]])
        tex = glkit.texture_rgba(data, w, h, GL.GL_RGBA)
        self.poster_tex = (iid, tex, w, h)
        return tex, w, h

    def _close_player(self):
        if self.player is not None:
            self.player.close()
            self.player = None
            self.loaded = None
            self.log("tv: nothing on; mpv closed")

    # ------------------------------------------------------------------ the on-screen display
    def _osd(self, media_screen):
        """(screen, static 0..1, texture) for the screen's OSD: the channel number while
        tuning, the volume while it changes, a small speaker while the sound is on."""
        now = _mono()
        screen, static, lines = None, 0.0, None
        if self.tune and now - self.tune[1] < TUNE_OSD:
            screen = self.tune[0]
            if self.motion == "full":
                static = max(0.0, 1.0 - (now - self.tune[1]) / TUNE_STATIC)
            lines = ("tune", self.tune[2], self.tune[3])
        elif self.tune:
            self.tune = None
        vol = None
        if self.vol_osd and now - self.vol_osd[1] < VOLUME_OSD:
            screen = screen or self.vol_osd[0]
            vol = self.screens[self.vol_osd[0]]["volume"]
        speaker = media_screen is not None and self._effective_sound()[0]
        if speaker and screen is None:
            screen = media_screen
        if screen is None:
            return None, 0.0, None
        if screen not in self.px:
            return None, 0.0, None
        sig = (screen, lines, vol, speaker and screen == media_screen, self.px[screen][2:])
        if sig != self.osd_sig:
            self.osd_sig = sig
            self._draw_osd(screen, lines, vol, speaker and screen == media_screen)
        return screen, static, self.osd_tex

    def _draw_osd(self, screen, lines, vol, speaker):
        import cairo
        from . import glkit
        w, h = (max(32, int(v)) for v in self.px[screen][2:])
        surf = cairo.ImageSurface(cairo.FORMAT_ARGB32, w, h)
        cr = cairo.Context(surf)
        r, g, b, _ = glkit.col("phosphor")
        u = h / 100.0
        cr.select_font_face("Geist Mono", cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_BOLD)
        if lines:
            _, n, name = lines
            cr.set_font_size(22 * u)
            cr.set_source_rgba(r, g, b, 0.95)
            t = f"CH {n}"
            ext = cr.text_extents(t)
            cr.move_to(w - ext.x_advance - 8 * u, 24 * u)
            cr.show_text(t)
            cr.set_font_size(10 * u)
            name = name.upper()[:18]
            ext = cr.text_extents(name)
            cr.move_to(w - ext.x_advance - 8 * u, 38 * u)
            cr.show_text(name)
        if vol is not None:
            bars, bw = 16, (w * 0.62) / 16
            x0, y0 = w * 0.19, h * 0.78
            for i in range(bars):
                on = i < round(vol / 100 * bars)
                cr.set_source_rgba(r, g, b, 0.95 if on else 0.22)
                cr.rectangle(x0 + i * bw + 1, y0, bw - 2, 7 * u)
                cr.fill()
            cr.set_font_size(9 * u)
            cr.set_source_rgba(r, g, b, 0.9)
            cr.move_to(x0, y0 - 3 * u)
            cr.show_text(f"VOL {vol}")
        if speaker and vol is None:
            s = 7 * u
            x, y = w - 16 * u, h - 13 * u
            cr.set_source_rgba(r, g, b, 0.7)
            cr.move_to(x, y + s * 0.35)
            cr.line_to(x + s * 0.35, y + s * 0.35)
            cr.line_to(x + s * 0.8, y)
            cr.line_to(x + s * 0.8, y + s * 1.2)
            cr.line_to(x + s * 0.35, y + s * 0.85)
            cr.line_to(x, y + s * 0.85)
            cr.close_path()
            cr.fill()
            cr.set_line_width(max(1.0, 0.9 * u))
            for k in (1, 2):
                cr.arc(x + s * 0.8, y + s * 0.6, s * 0.35 * k, -0.9, 0.9)
                cr.stroke()
        surf.flush()
        if self.osd_tex is None:
            self.osd_tex = glkit.texture_from_cairo(surf)
        else:
            GL.glDeleteTextures([self.osd_tex])
            self.osd_tex = glkit.texture_from_cairo(surf)

    # ------------------------------------------------------------------ the hover hint
    def hint_visible(self):
        return self.hover is not None and self.hover in self.rects

    def input_rects(self):
        """Logical rects the background window takes the pointer in."""
        out = [self.rects[s] for s in self.interactive() if s in self.rects]
        if self.hint_visible() and self.hint_rect:
            out.append(self.hint_rect)
        return [tuple(int(round(v)) for v in r) for r in out]

    def _place_hint(self, screen):
        x, y, w, h = self.rects[screen]
        mw, mh = (self.layout_info[0] / self.layout_info[3], self.layout_info[1] / self.layout_info[3])
        hx = min(max(8, x + w / 2 - HINT_W / 2), mw - HINT_W - 8)
        hy = y + h - 2 if y + h + HINT_H < mh - 8 else y - HINT_H + 2     # touching it: no gap to cross
        return (hx, hy, HINT_W, HINT_H)

    def _target(self, x, y):
        """("hint", None) | ("screen", screen) | (None, None) for a logical point."""
        def inside(r):
            return r and r[0] <= x <= r[0] + r[2] and r[1] <= y <= r[1] + r[3]
        if self.hint_visible() and inside(self.hint_rect):
            return "hint", self.hover
        for s in self.interactive():
            if inside(self.rects.get(s)):
                return "screen", s
        return None, None

    def pointer_motion(self, x, y):
        kind, s = self._target(x, y)
        if self.dragging and self.hint_visible():
            self._drag_volume(x)
            return
        if kind:
            self.hint_until = 0.0
            if s != self.hover:
                self.hover = s
                self.hint_rect = self._place_hint(s)
                self._changed()
        elif self.hover is not None:
            self.pointer_leave(now=True)

    def pointer_leave(self, now=False):
        """The pointer left the screens and the hint: the hint goes after a moment (time to
        come back), or at once."""
        if self.hover is None:
            return
        if not now:
            self.hint_until = self.hint_until or _mono() + 0.6
            return
        self.hover = None
        self.hint_until = 0.0
        self.dragging = False
        self._changed()

    def hint_expired(self):
        """The app's tick: hide a hint the pointer left."""
        if self.hover is not None and self.hint_until and _mono() > self.hint_until:
            self.pointer_leave(now=True)
            return True
        return False

    def _button_at(self, x, y):
        if not self.hint_rect:
            return None
        hx, hy = self.hint_rect[:2]
        for bx, by, bw, bh, action in self.buttons:
            if hx + bx <= x <= hx + bx + bw and hy + by <= y <= hy + by + bh:
                return action
        return None

    def click(self, x, y, button=1):
        kind, s = self._target(x, y)
        if kind == "screen" and button == 1:
            n, ch = self.channel(s)
            if ch["kind"] != "own":
                return self.open_full(s)
            return self.tune_to(s, step=1)
        if kind == "hint":
            act = self._button_at(x, y)
            if act:
                return self._do(act, x)
        return None

    def release(self):
        self.dragging = False

    def _do(self, act, x=None):
        s = self.hover
        if act == "prev":
            return self.tune_to(s, step=-1)
        if act == "next":
            return self.tune_to(s, step=1)
        if act == "full":
            return self.open_full(s)
        if act == "web":
            return self.open_web(s)
        if act == "speaker":
            return self.set_sound(s, on=not self.screens[s]["sound"])
        if act == "down":
            return self.set_sound(s, volume=self.screens[s]["volume"] - 5)
        if act == "up":
            return self.set_sound(s, volume=self.screens[s]["volume"] + 5)
        if act == "bar":
            self.dragging = True
            return self._drag_volume(x)
        return None

    def _drag_volume(self, x):
        bar = next((b for b in self.buttons if b[4] == "bar"), None)
        if not bar or self.hover is None or not self.hint_rect:
            return None
        frac = (x - self.hint_rect[0] - bar[0]) / max(bar[2], 1)
        return self.set_sound(self.hover, volume=max(0.0, min(1.0, frac)) * 100)

    def scroll(self, x, y, dy, shift=False, dx=0.0):
        """The wheel over a screen changes channel. The volume: the wheel over the hint's
        volume (the bar, − and +), a sideways scroll over the screen, or Shift and the wheel
        where the compositor tells the background about Shift (Hyprland doesn't: the
        background never has the keyboard)."""
        kind, s = self._target(x, y)
        if not kind:
            return None
        on_volume = kind == "hint" and self._button_at(x, y) in ("bar", "down", "up", "speaker")
        if dx and not dy:
            return self.set_sound(s, volume=self.screens[s]["volume"] + (5 if dx > 0 else -5))
        if shift or on_volume:
            return self.set_sound(s, volume=self.screens[s]["volume"] + (5 if dy < 0 else -5))
        return self.tune_to(s, step=1 if dy > 0 else -1)

    def hint_texture(self, sf):
        """(texture, logical rect) of the hint, drawn again when what it says changes."""
        if not self.hint_visible():
            return None
        s = self.hover
        n, ch = self.channel(s)
        lu = self.lineup(s)
        slot = self.slot(ch)
        st = self.screens[s]
        sig = (s, n, len(lu), ch["key"], (slot.item or {}).get("id") if slot else None, st["sound"], st["volume"],
               int(slot.offset // 60) if slot and slot.offset else None, sf)
        if sig != self.hint_sig or self.hint_tex is None:
            self.hint_sig = sig
            self._draw_hint(s, n, lu, ch, slot, st, sf)
        return self.hint_tex, self.hint_rect

    def _draw_hint(self, s, n, lu, ch, slot, st, sf):
        import cairo
        from . import glkit
        W, H = int(HINT_W * sf), int(HINT_H * sf)
        surf = cairo.ImageSurface(cairo.FORMAT_ARGB32, W, H)
        cr = cairo.Context(surf)
        cr.scale(sf, sf)
        ph, dim, soft = glkit.col("phosphor"), glkit.col("dim"), glkit.col("soft")
        bg = glkit.col("void")
        cr.set_source_rgba(bg[0], bg[1], bg[2], 0.88)
        cr.rectangle(0, 0, HINT_W, HINT_H)
        cr.fill()
        cr.set_source_rgba(ph[0], ph[1], ph[2], 0.75)
        cr.set_line_width(1)
        cr.rectangle(0.5, 0.5, HINT_W - 1, HINT_H - 1)
        cr.stroke()
        cr.select_font_face("Geist Mono", cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_BOLD)
        media = ch["kind"] != "own"

        def text(x, y, t, size, c=soft, bold=True, maxw=None):
            cr.select_font_face("Geist Mono", cairo.FONT_SLANT_NORMAL,
                                cairo.FONT_WEIGHT_BOLD if bold else cairo.FONT_WEIGHT_NORMAL)
            cr.set_font_size(size)
            if maxw:
                while t and cr.text_extents(t).x_advance > maxw:
                    t = t[:-2] + "…"
            cr.set_source_rgba(*c[:3], 0.95)
            cr.move_to(x, y)
            cr.show_text(t)
            return cr.text_extents(t).x_advance

        self.buttons = []

        def button(x, y, w, h, label, action, on=False):
            cr.set_source_rgba(ph[0], ph[1], ph[2], 0.28 if on else 0.12)
            cr.rectangle(x, y, w, h)
            cr.fill()
            cr.set_source_rgba(ph[0], ph[1], ph[2], 0.7)
            cr.rectangle(x + 0.5, y + 0.5, w - 1, h - 1)
            cr.stroke()
            cr.select_font_face("Geist Mono", cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_BOLD)
            cr.set_font_size(11)
            e = cr.text_extents(label)
            cr.set_source_rgba(*soft[:3], 1.0)
            cr.move_to(x + (w - e.x_advance) / 2, y + h / 2 + 4)
            cr.show_text(label)
            self.buttons.append((x, y, w, h, action))

        if media and slot:
            it = slot.item
            line = ("▶ LIVE · " if ch["kind"] == "live" else "▶ ") + TVL.label(it)
            text(10, 19, line, 13, soft, maxw=HINT_W - 90)
            if slot.offset is not None and it.get("duration"):
                text(10, 34, f"{ch['name']} · {TVL.fmt_time(slot.offset)} of {TVL.fmt_time(it['duration'])}",
                     10, dim, False, maxw=HINT_W - 90)
            else:
                text(10, 34, ch["name"], 10, dim, False)
        elif media:
            text(10, 19, f"▶ {ch['name']}", 13, soft)
            text(10, 34, "Tuning in…", 10, dim, False)
        else:
            text(10, 19, f"{ch['name']}", 13, soft)
            text(10, 34, ch.get("what", ""), 10, dim, False, maxw=HINT_W - 90)
        text(HINT_W - 70, 19, f"CH {n}/{len(lu)}", 12, ph)
        y = 44
        button(10, y, 26, 24, "◀", "prev")
        button(40, y, 26, 24, "▶", "next")
        if media:
            button(76, y, 34, 24, "", "speaker", on=st["sound"])
            self._speaker(cr, 84, y + 6, 12, st["sound"], soft)
            button(114, y, 22, 24, "−", "down")
            bx, bw = 140, 84
            cr.set_source_rgba(ph[0], ph[1], ph[2], 0.18)
            cr.rectangle(bx, y + 9, bw, 6)
            cr.fill()
            cr.set_source_rgba(ph[0], ph[1], ph[2], 0.9 if st["sound"] else 0.45)
            cr.rectangle(bx, y + 9, bw * st["volume"] / 100.0, 6)
            cr.fill()
            self.buttons.append((bx, y, bw, 24, "bar"))
            button(228, y, 22, 24, "+", "up")
            button(256, y, 64, 24, "FULL", "full")
            if ch["kind"] in ("youtube", "live", "server"):
                web = "YOUTUBE" if ch["kind"] != "server" else (self._server_name(ch) or "WEB").upper()
                button(324, y, 70, 24, web[:8], "web")
            text(10, 88, "Click the screen: full screen with sound", 10, dim, False)
            text(10, 103, "Wheel: channel · wheel on the volume bar: volume", 10, dim, False)
        else:
            text(76, 61, "Scroll or ◀ ▶ to change channel", 10, dim, False)
        surf.flush()
        if self.hint_tex is not None:
            GL.glDeleteTextures([self.hint_tex])
        self.hint_tex = glkit.texture_from_cairo(surf)

    @staticmethod
    def _speaker(cr, x, y, s, on, c):
        """A speaker: with waves when the sound is on, crossed out when it's off."""
        cr.set_source_rgba(c[0], c[1], c[2], 1.0)
        cr.move_to(x, y + s * 0.32)
        cr.line_to(x + s * 0.3, y + s * 0.32)
        cr.line_to(x + s * 0.62, y)
        cr.line_to(x + s * 0.62, y + s)
        cr.line_to(x + s * 0.3, y + s * 0.68)
        cr.line_to(x, y + s * 0.68)
        cr.close_path()
        cr.fill()
        cr.set_line_width(1.4)
        if on:
            for k in (1, 2):
                cr.arc(x + s * 0.62, y + s * 0.5, s * 0.28 * k, -0.9, 0.9)
                cr.stroke()
        else:
            cr.move_to(x + s * 0.8, y + s * 0.3)
            cr.line_to(x + s * 1.2, y + s * 0.7)
            cr.move_to(x + s * 1.2, y + s * 0.3)
            cr.line_to(x + s * 0.8, y + s * 0.7)
            cr.stroke()

    def _server_name(self, ch):
        if ch["kind"] != "server":
            return ""
        a = TVL.server_of(ch)
        return {"jellyfin": "Jellyfin", "plex": "Plex"}.get(getattr(a, "type", ""), "")

    # ------------------------------------------------------------------ full screen, the web page
    def _pick(self, screen):
        if screen and screen in self.screens:
            return screen
        s, _ = self.media_screen()
        return s or "big"

    def open_full(self, screen=None):
        """The channel in mpv, full screen with sound, at the same moment, as a normal window."""
        screen = self._pick(screen)
        n, ch = self.channel(screen)
        if ch["kind"] == "own":
            return f"{screen}: channel {n} is the screen's own picture; nothing to open"
        if not shutil.which("mpv"):
            return "mpv isn't installed (sudo pacman -S mpv)"
        slot = self.slot(ch)
        try:
            s = self.stream(ch, slot, full=True)
        except Exception as e:                                  # noqa: BLE001
            self.log(f"tv: no stream to open: {type(e).__name__}: {e}")
            s = None
        if not s:
            return f"nothing to open on {ch['name']} yet"
        st = self.screens[screen]
        conf = tempfile.NamedTemporaryFile("w", prefix="bromigos-tv-", suffix=".conf",
                                           dir=os.environ.get("XDG_RUNTIME_DIR") or None, delete=False)
        os.chmod(conf.name, 0o600)
        for k, v in (s.get("headers") or {}).items():         # secrets stay out of the command line
            val = f"{k}: {v}"
            conf.write(f"http-header-fields-append=%{len(val.encode())}%{val}\n")
        ca = self._tls_ca()
        if ca:
            conf.write(f"tls-ca-file={ca}\ntls-verify=yes\n")
        conf.close()
        cmd = ["mpv", "--fs", "--force-window=immediate", f"--include={conf.name}", f"--volume={st['volume']}",
               "--volume-max=100", f"--title={s['title']} · bromigOS den TV", "--audio-client-name=bromigOS den TV",
               f"--force-media-title={s['title']}"]
        if s.get("ytdl_format"):
            cmd.append(f"--ytdl-format={s['ytdl_format']}")
        start = s.get("start")
        if start is not None:
            cmd.append(f"--start={start + 0.6:.2f}")
        cmd.append(s["url"])
        try:
            self.full_proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                              start_new_session=True)
        except OSError as e:
            return f"mpv didn't start: {e}"
        threading.Timer(20.0, lambda: os.path.exists(conf.name) and os.remove(conf.name)).start()
        self.log(f"tv: full screen: {s['title']}" + (f" at {TVL.fmt_time(start)}" if start else ""))
        return f"full screen: {s['title']}" + (f" at {TVL.fmt_time(start)}" if start else "")

    def open_web(self, screen=None):
        screen = self._pick(screen)
        n, ch = self.channel(screen)
        slot = self.slot(ch)
        if ch["kind"] == "own" or not slot:
            return "no media channel on"
        url = None
        if ch["kind"] in ("youtube", "live"):
            url = slot.item.get("url")
        else:
            a = TVL.server_of(ch)
            url = a.video_web(slot.item) if a else None
        if not url:
            return "no page for it"
        try:
            subprocess.Popen(["xdg-open", url], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                             start_new_session=True)
        except OSError as e:
            return f"xdg-open: {e}"
        return f"opened {url.split('?')[0]}"

    # ------------------------------------------------------------------ YouTube keep
    def _keep(self, ch, slot):
        if ch["kind"] != "youtube" or not ch.get("keep"):
            return
        import bromigos_youtube as Y
        if self.keeper is None:
            self.keeper = Y.Keeper(self.log)
        it = slot.item
        self.keeper.want(it, ch["keep"], it.get("playlist"), it.get("index"), ch.get("keep_max_gb"))

    def _keep_all(self, ch):
        """keep_all: every video of the playlist or channel, not just what the TV plays."""
        import bromigos_youtube as Y
        if self.keeper is None:
            self.keeper = Y.Keeper(self.log)
        for it in (TVL.cached_items(ch) or {}).get("items") or []:
            self.keeper.want(it, ch["keep"], it.get("playlist"), it.get("index"), ch.get("keep_max_gb"))

    # ------------------------------------------------------------------ the worker
    def _work(self):
        """Lists (each channel's, cached), YouTube live checks, posters, keep = "all"."""
        live_at = {}
        while not self.stop.is_set():
            try:
                chans = TVL.channels(self.cfg) if self.enabled() else []
                screen, on = self.media_screen()
                for ch in sorted(chans, key=lambda c: 0 if on and c["key"] == on["key"] else 1):
                    if self.stop.is_set():
                        return
                    TVL.fetch_items(ch, max_age=float(self.conf().get("refresh_minutes", 15)) * 60)
                    if ch["kind"] == "youtube" and ch.get("live") and time.time() - live_at.get(ch["key"], 0) > 600:
                        live_at[ch["key"]] = time.time()
                        import bromigos_youtube as Y
                        v = Y.live_now(ch["youtube"])
                        if bool(v) != bool(self.live.get(ch["key"])):
                            self.log(f"tv: {ch['name']} is {'live now' if v else 'no longer live'}")
                            self.hint_sig = None
                        if v:
                            self.live[ch["key"]] = v
                        else:
                            self.live.pop(ch["key"], None)
                    if ch["kind"] == "youtube" and ch.get("keep") and ch.get("keep_all"):
                        self._keep_all(ch)
                if on is not None:
                    slot = self.slot(on)
                    if slot:
                        self._fetch_poster(on, slot.item)
                        if slot.next:
                            self._fetch_poster(on, slot.next)
                if chans:
                    TVL.catalog(max_age=900)
            except Exception as e:                              # noqa: BLE001  never take the layer down
                self.log(f"tv: worker: {type(e).__name__}: {e}")
            self.wake.wait(20.0)
            self.wake.clear()

    def _fetch_poster(self, ch, item):
        iid = str(item.get("id"))
        if not item or iid in self.poster:
            return
        url, headers = None, {}
        if ch["kind"] in ("youtube", "live"):
            url = item.get("thumbnail") or item.get("poster")
        else:
            a = TVL.server_of(ch)
            if a is not None:
                url, headers = a.video_poster(item)
        if not url:
            self.poster[iid] = None
            return
        try:
            import ssl
            import urllib.request
            from PIL import Image
            ca = self._tls_ca()
            ctx = ssl.create_default_context(cafile=ca) if ca else ssl.create_default_context()
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=10, context=ctx) as r:
                b = r.read(4 << 20)
            im = Image.open(io.BytesIO(b)).convert("RGBA")
            im.thumbnail((360, 360))
            self.poster[iid] = (im.tobytes(), im.width, im.height)
            if len(self.poster) > 24:
                for k in list(self.poster)[:8]:
                    self.poster.pop(k, None)
        except Exception as e:                                  # noqa: BLE001
            self.log(f"tv: no poster for {TVL.label(item)}: {type(e).__name__}")
            self.poster[iid] = None

    # ------------------------------------------------------------------ commands (bromigos-live tv …)
    def command(self, arg):
        parts = arg.split()
        verb = parts[0] if parts else "state"
        rest = parts[1:]
        screens = [x for x in rest if x in TVL.SCREENS]
        rest = [x for x in rest if x not in TVL.SCREENS]
        screen = screens[0] if screens else None
        if verb in ("next", "prev"):
            s = screen or self.media_screen()[0] or "big"
            return self.tune_to(s, step=1 if verb == "next" else -1)
        if verb == "set":
            if not rest or not rest[0].isdigit():
                return "bromigos-live tv set N [big|wave|emblem]"
            return self.tune_to(screen or "big", number=int(rest[0]))
        if verb == "open":
            return self.open_full(screen)
        if verb == "web":
            return self.open_web(screen)
        if verb == "sound":
            s = self._pick(screen)
            w = (rest or ["toggle"])[0]
            on = {"on": True, "off": False}.get(w, not self.screens[s]["sound"])
            return self.set_sound(s, on=on)
        if verb == "volume":
            s = self._pick(screen)
            w = (rest or [""])[0]
            cur = self.screens[s]["volume"]
            if w == "up":
                return self.set_sound(s, volume=cur + 5)
            if w == "down":
                return self.set_sound(s, volume=cur - 5)
            if w.isdigit():
                return self.set_sound(s, volume=int(w))
            return "bromigos-live tv volume up|down|N [big|wave|emblem]"
        if verb == "list":
            out = []
            for s in TVL.SCREENS:
                cur, _ = self.channel(s)
                for n, ch in enumerate(self.lineup(s), 1):
                    out.append(f"{s:<7} {'*' if n == cur else ' '} {n:>2}  {ch['name']}"
                               + ("" if ch["kind"] == "own" else f"  ({ch['kind']})"))
            return "\n".join(out)
        if verb == "state":
            import json
            return json.dumps(self.describe(), indent=None if "--json" in rest else 1)
        return "bromigos-live tv next|prev|set N|open|web|sound on|off|toggle|volume up|down|N|list|state [screen]"

    def describe(self):
        out = {"screens": {}, "playing": None, "picture": "mpv" if self.player else (self.player_why or "off"),
               "allowed": self.allowed, "covered": sorted(self.covered)}
        for s in TVL.SCREENS:
            n, ch = self.channel(s)
            st = self.screens[s]
            d = {"channel": n, "of": len(self.lineup(s)), "name": ch["name"], "kind": ch["kind"],
                 "sound": st["sound"], "volume": st["volume"], "rect": [round(v) for v in self.rects.get(s, ())]}
            slot = self.slot(ch)
            if slot:
                keep = ("id", "title", "series", "season", "episode", "kind", "duration", "year", "server", "poster",
                        "thumbnail", "url")
                d["now"] = TVL.label(slot.item)
                d["offset"] = None if slot.offset is None else round(slot.offset, 2)
                d["next"] = TVL.label(slot.next) if slot.next else None
                d["item"] = {k: slot.item.get(k) for k in keep if slot.item.get(k) is not None}
                d["next_item"] = {k: slot.next.get(k) for k in keep if slot.next.get(k) is not None} if slot.next else None
                d["start"], d["end"] = slot.start, slot.end
                d["source"] = ch.get("source") or None
            out["screens"][s] = d
        if self.player is not None and self.loaded:
            pos = self.player.position()
            try:
                hw = self.player.m.hwdec_current
            except Exception:                                   # noqa: BLE001
                hw = None
            out["playing"] = {"item": self.loaded[1], "position": None if pos is None else round(pos, 2), "hwdec": hw,
                              "paused": self.player.paused(), "sound": self._effective_sound()[0],
                              "volume": round(self._effective_sound()[1])}
        out["hint"] = self.hover
        if self.hover and self.hint_rect:
            hx, hy = self.hint_rect[:2]
            out["hint_rect"] = [round(v) for v in self.hint_rect]
            out["buttons"] = {a: [round(hx + bx + bw / 2), round(hy + by + bh / 2)] for bx, by, bw, bh, a in self.buttons}
        out["input"] = self.input_rects()
        out["full_screen"] = self.full_proc is not None and self.full_proc.poll() is None
        return out

    def close(self):
        self.stop.set()
        self.wake.set()
        self._close_player()
        for t in (self.osd_tex, self.hint_tex) + ((self.poster_tex[1],) if self.poster_tex else ()):
            if t:
                try:
                    GL.glDeleteTextures([t])
                except Exception:                               # noqa: BLE001
                    pass
        self.osd_tex = self.hint_tex = self.poster_tex = None

