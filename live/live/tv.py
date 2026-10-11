"""The den TV: channels on the den's screens, from your own Plex or Jellyfin library or
YouTube, playing as if live (lib/bromigos_tv.py has the channels and the schedule).

Each of the den's three screens (the big monitor, the scope, the small monitor) has a
channel list. Channel 1 is the screen's own picture, drawn as it always was. The media
channels come after it: every channel, unless a channel's `screens` keeps it to some.
Every screen plays its own channel at the same time, each with a player of its own (at most
[tv] max_playing at once: past that, the rest show posters). Two screens on the same
channel show the same moment from one player. A screen nobody has tuned starts on
[tv] start's channel for it.

    the picture   libmpv (live/live/mpvgl.py) decodes on the GPU into a texture the size of
                  the screen; the server is asked for a stream that size (a few hundred
                  pixels: a transcode, unless the file is already small), YouTube for a
                  format that size. bg.frag draws it in the screen's glass with scanlines,
                  curvature and glow. A new channel or item shows static, the channel's
                  number and the item's poster until its own first frame: never the last
                  item's picture.
    pausing       each screen on its own: it decodes only while the live layer draws and the
                  screen is in view. No frames drawn for a second (locked, a fullscreen
                  window, a deck, the screensaver), or an opaque window over a muted screen
                  (one with the sound on keeps playing behind windows; a see-through window,
                  under [tv] cover_opacity, never counts) pauses it. Coming back, the channel
                  jumps to where it would be now. Still motion (or no GPU) shows the item's
                  poster instead; reduced motion a still frame, renewed every 30 s, unless
                  the sound is on.
    bumpers       a channel with `bumpers = true` opens each item with a few seconds' card:
                  the channel's name, what's on and the time, like a TV network's block.
    the pointer   the background window takes the pointer over the den's screens only (its
                  input region), and over the hint while it shows. Over a screen: the hint
                  (what's on, the channel buttons, the speaker, the volume, Full screen, Watch
                  in Plex/Jellyfin/YouTube and the channel guide). A click opens the channel
                  in mpv, full screen with sound, at the same moment; scroll changes channel,
                  a sideways scroll the volume.
    sound         off by default, and on one screen at a time: turning it on for one turns
                  it off on the others. The speaker on that screen shows where it comes from.
                  Each screen remembers its volume. bromigOS's mute, the lock screen and the
                  screensaver silence it; VECTOR speaking (or a codec call) ducks it to
                  [tv] duck percent. PipeWire sees it as "bromigOS den TV". When the desktop
                  itself is muted, the hint says so.

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

from .tvcontrol import Controls

from . import LIB  # noqa: F401  (the shared libs on sys.path)
import bromigos_tv as TVL  # noqa: E402

SHADER_INDEX = {"wave": 1, "emblem": 2, "big": 3}
PRIORITY = ("big", "wave", "emblem")       # who plays first when [tv] max_playing is fewer than the screens
ALIASES = {"scope": "wave", "small": "emblem", "monitor": "big"}
YT_HEIGHTS = (240, 360, 480, 720, 1080)
FULL_FORMAT = "bestvideo[height<=1080]+bestaudio/best"
TUNE_STATIC = 0.35            # seconds of static when a channel changes (full motion)
TUNE_OSD = 1.6                # seconds the channel number shows
VOLUME_OSD = 1.5
REDUCED_EVERY = 30.0          # reduced motion: a new still frame this often
DRIFT = 3.0                   # seconds off the schedule before the picture is put back
DRIFT_EVERY = 10.0            # how often that's checked (a seek restarts a server's transcode)
DRIFT_TRANSCODE = 120.0       # a server's transcode is put back only this far off
IDLE_CLOSE = 30.0             # a screen's player is closed after this long with nothing on
HINT_W, HINT_H = 404, 112     # the hover hint, logical px
BUMPER = 5.0                  # seconds of a channel's bumper card at the start of each item
MAX_PLAYING = 3               # every screen (measured: live/README.md, "The den TV", what it costs)
COVER_OPACITY = 0.9           # a window under this opacity doesn't count as covering a screen


def yt_format(height, sound):
    """yt-dlp's format for a den screen drawn `height` pixels tall: the smallest of
    YT_HEIGHTS at least that tall (a 4K video comes as 240p or 360p), with or without audio."""
    h = next((x for x in YT_HEIGHTS if x >= height), YT_HEIGHTS[-1])
    if sound:
        return f"bestvideo[height<={h}]+bestaudio/best[height<={h}]/best"
    return f"bestvideo[height<={h}]/best[height<={h}]/best"


LOW_FORMAT_MUTED = yt_format(360, False)


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


MONO = time.monotonic          # the TV's clock (the offscreen tests fix the scene's, not this)


def _mono():
    return MONO()


class Deck:
    """One den screen's playback: its player, what's loaded, its textures and on-screen display."""

    def __init__(self, name):
        self.name = name
        self.player = None
        self.loaded = None                 # (channel key, item id) in its mpv
        self.stream = None                 # the stream it plays (a server's: its transcode, ended when it moves on)
        self.loaded_at = 0.0
        self.idle_at = None                # when it last had nothing on (its player closes after IDLE_CLOSE)
        self.allowed = False               # drawing, in view (or with sound), within max_playing: decode
        self.capped = False                # past [tv] max_playing: the poster
        self.poster_tex = None             # (item id, texture, w, h)
        self.osd_tex = None
        self.osd_sig = None
        self.reduced_at = 0.0
        self.drift_at = 0.0
        self.tune = None                   # (monotonic start, number, name): the channel's number, static
        self.feedback = None
        self.vol_osd = None                # monotonic start


class TV(Controls):
    def __init__(self, cfg, log=print):
        self.cfg = cfg
        self.log = log
        st = TVL.state()
        conf = self.conf()
        self.screens = {s: TVL.screen_state(st, s, int(conf.get("volume", TVL.DEFAULT_VOLUME))) for s in TVL.SCREENS}
        on = [s for s in PRIORITY if self.screens[s]["sound"]]
        for s in on[1:]:                   # sound on one screen at a time (an older tv.json had more)
            self.screens[s]["sound"] = False
        self.decks = {s: Deck(s) for s in TVL.SCREENS}
        self.follows = {}                  # screen -> the screen whose player it shows (the same channel)
        self._owners = {}                  # channel key -> the screen decoding it for the others (kept while it can)
        self.live = {}                     # YouTube live streams now: channel key -> video
        self.fails = {}                    # channel key -> [(when, item id)] that wouldn't play
        self.retry_at = {}                 # channel key -> when to try its server again
        self._lineups = {}
        self.player_why = ""               # why there's no picture (no python-mpv, a failure)
        self.drawn_at = 0.0
        self.covered = set()
        self.quiet = False                 # locked or the screensaver: no sound
        self.ducked = False
        self.desktop_muted = False         # the desktop's own output is muted (the hint says so)
        self._mute_check_at = 0.0
        self.motion = "full"
        self.software = False
        self.poster = {}                   # item id -> (rgba bytes, w, h) from the worker
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
        self.full_proc = None
        self.full_session = None
        self.init_controls()
        self.resolved = {}                 # (YouTube URL, height) -> Y.stream()'s answer, or {"error", "at"}
        self.notes = {}                    # channel key -> (monotonic, what went wrong): the hint says it
        self._rq = []                      # YouTube streams to resolve: (url, height)
        self._rlock = threading.Lock()
        self._rwake = threading.Event()
        self.on_change = None              # the app: input region, redraw
        self.keeper = None
        self.stop = threading.Event()
        self.wake = threading.Event()
        self.worker = threading.Thread(target=self._work, daemon=True, name="den-tv")
        self.worker.start()
        self.resolver = threading.Thread(target=self._resolve_loop, daemon=True, name="den-tv-youtube")
        self.resolver.start()
        self._apply_start()

    def _apply_start(self):
        """A screen nobody has tuned starts on [tv] start's channel for it."""
        for s in TVL.SCREENS:
            st = self.screens[s]
            if st.get("tuned") or st.get("channel") not in (None, "own"):
                continue
            k = TVL.start_key(self.cfg, s)
            if k and any(ch["key"] == k for ch in self.lineup(s)):
                st["channel"] = k

    # ------------------------------------------------------------------ config
    def conf(self):
        return self.cfg.get("tv") or {}

    def enabled(self):
        return self.conf().get("enabled", True) is not False

    def max_playing(self):
        try:
            return max(0, min(3, int(self.conf().get("max_playing", MAX_PLAYING))))
        except (TypeError, ValueError):
            return MAX_PLAYING

    def reconfigured(self):
        """The [tv] table changed (the channel guide, an edit): read the channels again now."""
        self._lineups.clear()
        self.last_slot.clear()
        self._apply_start()
        self.wake.set()
        self._changed()

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
                return n + 1, self.override_channel(screen, ch)
        return 1, self.override_channel(screen, lu[0])

    def showing(self, screen):
        """True when the screen shows a media channel (not its own picture)."""
        return self.channel(screen)[1]["kind"] != "own"

    def media_screens(self):
        """[(screen, channel)] for every screen showing a media channel."""
        out = []
        for s in PRIORITY:
            n, ch = self.channel(s)
            if ch["kind"] != "own":
                out.append((s, ch))
        return out

    def media_screen(self):
        """(screen, channel) of the first screen showing a media channel (the sound's, first), or (None, None)."""
        ms = self.media_screens()
        snd = self.sound_screen()
        for s, ch in ms:
            if s == snd:
                return s, ch
        return ms[0] if ms else (None, None)

    def sound_screen(self):
        """The screen whose sound is on (one at a time), when it shows a media channel."""
        for s in PRIORITY:
            if self.screens[s]["sound"] and self.showing(s):
                return s
        return None

    def interactive(self):
        """The screens that have more than one channel (the pointer's region)."""
        return [s for s in TVL.SCREENS if len(self.lineup(s)) > 1]

    def save(self):
        TVL.save_state({"screens": {s: dict(v) for s, v in self.screens.items()}})

    @property
    def player(self):
        """The player of the screen with the sound, else the first playing (the tests', describe's)."""
        s, _ = self.media_screen()
        d = self.decks.get(s) if s else None
        if d is not None and d.player is not None:
            return d.player
        return next((d.player for d in self.decks.values() if d.player is not None), None)

    # ------------------------------------------------------------------ the schedule
    def slot(self, ch):
        if ch is None or ch["kind"] == "own":
            return None
        if ch.get("override"):
            return self.override_slot(ch)
        now = _mono()
        hit = self.last_slot.get(ch["key"])
        if hit and now - hit[0] < 0.5:
            return hit[1]
        s = TVL.now_next(ch)
        self.last_slot[ch["key"]] = (now, s)
        return s

    # ------------------------------------------------------------------ changing channel
    def tune_to(self, screen, number=None, step=0):
        self.overrides.pop(screen, None)
        lu = self.lineup(screen)
        cur, _ = self.channel(screen)
        n = number if number is not None else cur + step
        n = (n - 1) % len(lu) + 1
        ch = lu[n - 1]
        self.screens[screen]["channel"] = ch["key"]
        self.screens[screen]["tuned"] = True
        self.save()
        d = self.decks[screen]
        d.tune = (_mono(), n, ch["name"])
        self.last_slot.pop(ch["key"], None)
        if self.full_session and self.full_session.screen == screen:
            self.full_session.retune()
        self.wake.set()
        self._changed()
        self.log(f"tv: {TVL.SCREEN_NAMES.get(screen, screen)} on channel {n}, {ch['name']}")
        return f"{screen}: channel {n} of {len(lu)}, {ch['name']}"

    def rekey(self, old, new):
        """A channel renamed (its key is its name's): the screens tuned to it stay on it."""
        moved = [s for s, v in self.screens.items() if v.get("channel") == old]
        for s in moved:
            self.screens[s]["channel"] = new
        if moved:
            self.save()
        self.reconfigured()
        return f"renamed on {', '.join(moved) or 'no screen'}"

    def _changed(self):
        self.hint_sig = None
        if self.on_change:
            try:
                self.on_change()
            except Exception:                                   # noqa: BLE001
                pass

    # ------------------------------------------------------------------ sound
    def set_sound(self, screen, on=None, volume=None, from_full=False):
        s = self.screens[screen]
        if volume is not None:
            v = max(0, min(100, int(round(volume))))
            if v > s["volume"] and not s["sound"] and on is None:
                on = True                                       # turning it up turns it on
            s["volume"] = v
            self.decks[screen].vol_osd = _mono()
        if on is not None:
            self.decks[screen].feedback = (_mono(), "SOUND ON" if on else "MUTED")
            s["sound"] = bool(on)
            if on:                                              # one screen at a time
                for other in TVL.SCREENS:
                    if other != screen:
                        self.screens[other]["sound"] = False
        self.save()
        if s["sound"]:
            self._mute_check_at = 0.0
            self._check_desktop_mute()
        if self.full_session and not from_full:
            full = self.screens[self.full_session.screen]
            self.full_session.sound(full["volume"], full["sound"])
        self._apply_sound()
        self._changed()
        out = f"{screen}: sound {'on' if s['sound'] else 'off'}, volume {s['volume']}%"
        if s["sound"] and self.desktop_muted:
            out += " (your desktop is muted)"
        return out

    def _effective_sound(self, screen=None):
        """(on, volume) for a screen's player (default: the screen with the sound)."""
        screen = screen or self.sound_screen()
        if not screen or screen != self.sound_screen():
            return False, 0
        s = self.screens[screen]
        from .sound import muted
        fullscreen = self.full_session and self.full_session.screen == screen and self.full_session.proc.poll() is None
        on = s["sound"] and not self.quiet and not muted() and self.decks[screen].allowed and not fullscreen
        vol = s["volume"] * (float(self.conf().get("duck", 30)) / 100.0 if self.ducked else 1.0)
        return on, vol

    def _apply_sound(self):
        for s, d in self.decks.items():
            if d.player is None:
                continue
            on, vol = self._effective_sound(s)
            try:
                d.player.sound(on, vol)
            except Exception as e:                              # noqa: BLE001
                self.log(f"tv: sound: {e}")

    def _check_desktop_mute(self):
        """The desktop's output muted (wpctl, else pactl), off the drawing thread, every few
        seconds while a screen has its sound on: the hint says so."""
        now = _mono()
        if now - self._mute_check_at < 3.0 or not self.sound_screen():
            return
        self._mute_check_at = now

        def run():
            muted = False
            try:
                if shutil.which("wpctl"):
                    out = subprocess.run(["wpctl", "get-volume", "@DEFAULT_AUDIO_SINK@"], capture_output=True,
                                         text=True, timeout=2).stdout
                    muted = "MUTED" in out
                elif shutil.which("pactl"):
                    out = subprocess.run(["pactl", "get-sink-mute", "@DEFAULT_SINK@"], capture_output=True, text=True,
                                         timeout=2).stdout
                    muted = "yes" in out.lower()
            except (OSError, subprocess.SubprocessError):
                return
            if muted != self.desktop_muted:
                self.desktop_muted = muted
                self._changed()
        threading.Thread(target=run, daemon=True, name="den-tv-mute").start()

    # ------------------------------------------------------------------ the app's tick (0.5 s)
    def tick(self, covered=None, quiet=False, ducked=False, motion="full", software=False):
        """Each screen: play or pause. Frames drawn in the last second, not covered by an
        opaque window (unless its sound is on), within max_playing, not still."""
        self.controls_tick()
        self.covered = set(covered or ())
        self.quiet, self.ducked = quiet, ducked
        self.motion, self.software = motion, software
        drawing = _mono() - self.drawn_at < 1.2
        snd = self.sound_screen()
        media = [s for s, _ in self.media_screens()]
        order = ([snd] if snd else []) + [s for s in media if s != snd]
        cap = self.max_playing()
        self.follows = self._sharing(media, snd)
        decoding = [s for s in order if s not in self.follows]
        for s in TVL.SCREENS:
            d = self.decks[s]
            if s not in media or s in self.follows:
                d.allowed = False
                d.capped = False
                if s in self.follows and d.player is not None and d.loaded:
                    self._unload(d)                              # the screen it follows decodes for both
                continue
            d.capped = decoding.index(s) >= cap
            sound_on = s == snd
            want = (drawing and not software and not d.capped and (s not in self.covered or sound_on)
                    and (motion == "full" or (motion == "reduced" and sound_on)))
            was = d.allowed
            d.allowed = want
            if d.player is None:
                continue
            if want and not was and d.loaded and d.player.has_frame:
                slot = self.slot(self.channel(s)[1])
                pos = d.player.position()
                if slot and slot.offset is not None and (pos is None or abs(pos - slot.offset) > DRIFT):
                    d.player.seek(slot.offset)                   # back on: where the channel is now
            try:
                if not (motion == "reduced" and not sound_on):
                    d.player.pause(not want)
            except Exception:                                   # noqa: BLE001
                pass
        self._apply_sound()
        if snd:
            self._check_desktop_mute()
        if self.full_proc is not None and self.full_proc.poll() is not None:
            self.full_proc = None
            self.full_session = None
            self.log("tv: full screen closed; back to the den")

    def _sharing(self, media, snd):
        """{follower: owner} for screens on the same channel: one player decodes for all of
        them (the same moment, as on real TV). The owner: the screen with the sound, else
        the first not covered, else the first."""
        by = {}
        for s in media:
            by.setdefault(self.channel(s)[1]["key"], []).append(s)
        out, owners = {}, {}
        for key, group in by.items():
            if len(group) < 2:
                continue
            owner = self._owners.get(key)
            if snd in group:
                owner = snd                                      # the sound's screen decodes
            elif owner not in group:
                owner = next((s for s in group if s not in self.covered), group[0])
            owners[key] = owner                                  # kept: no new stream when a window comes and goes
            for s in group:
                if s != owner:
                    out[s] = owner
        self._owners = owners
        return out

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
        """Per frame, with the scene's GL context current: the uniforms bg.frag needs, per
        screen: "tv" (on, has a picture, aspect, tint), "tvtex", "tune" (static, has an OSD),
        "osd"."""
        self.drawn_at = _mono()
        tint = float(self.conf().get("tint", 0.4))
        out = {"tv": {}, "tvtex": {}, "tune": {}, "osd": {}}
        frames = {}                                    # an owner's frame this draw: (texture, its px aspect)
        follows = dict(self.follows)
        order = [s for s in TVL.SCREENS if s not in follows] + [s for s in TVL.SCREENS if s in follows]
        for s in order:
            d = self.decks[s]
            n, ch = self.channel(s)
            if ch["kind"] != "own":
                x, y, w, h = self.px.get(s, (0, 0, 320, 240))
                own = follows.get(s)
                if own and self.screens[own]["channel"] != self.screens[s]["channel"]:
                    own = None                                   # tuned away since the tick
                if own:
                    # the screen it follows decodes for both: its frame, else the poster (never a
                    # player of its own, not even for a moment: each start is a server's stream)
                    if frames.get(own):
                        tex, src_aspect = frames[own]
                        aspect = src_aspect / max(w / max(h, 1), 1e-3)
                    else:
                        slot = self.slot(ch)
                        p = self._poster_texture(d, slot.item if slot else None)
                        tex, aspect = (p[0], (p[1] / max(p[2], 1)) / max(w / max(h, 1), 1e-3)) if p else (None, 1.0)
                    d.idle_at = d.idle_at or _mono()                 # its own player isn't needed
                    if d.player is not None and _mono() - d.idle_at > IDLE_CLOSE:
                        self._close_player(d)
                else:
                    d.idle_at = None
                    tex, aspect = self._picture(s, ch, max(64, int(w * 1.5)), max(48, int(h * 1.5)), w / max(h, 1))
                    if tex and aspect == 1.0 and self.decks[s].player is not None and self.decks[s].player.has_frame:
                        frames[s] = (tex, w / max(h, 1))
                out["tv"][s] = (1.0, 1.0 if tex else 0.0, aspect, tint)
                out["tvtex"][s] = tex or 0
            else:
                out["tv"][s] = (0.0, 0.0, 1.0, 0.0)
                out["tvtex"][s] = 0
                if d.idle_at is None:
                    d.idle_at = _mono()
                if d.player is not None and _mono() - d.idle_at > IDLE_CLOSE:
                    self._close_player(d)                       # nothing on for a while: give it back
            static, osd = self._osd(s)
            out["tune"][s] = (static, 1.0 if osd else 0.0, 0.0, 0.0)
            out["osd"][s] = osd or 0
        return out

    def _picture(self, screen, ch, w, h, screen_aspect):
        """(texture, its aspect over the screen's) for a media screen: mpv's frame, or the
        poster (still motion, no mpv, past max_playing, loading), or (None, 1) for static."""
        d = self.decks[screen]
        slot = self.slot(ch)
        item = slot.item if slot else None
        if item is None:
            if d.loaded:
                self._unload(d)  # changed/empty picks must not keep the removed item's audio
            return None, 1.0
        poster_only = self.motion == "still" or self.software or d.capped or not self._player_ok(d)
        if not poster_only and item is not None:
            self._ensure_loaded(d, ch, slot)
            if self.motion == "reduced" and not self.screens[screen]["sound"]:
                now = _mono()
                direct = (d.stream or {}).get("quality") in (None, "direct")    # a transcode keeps its frame
                if now - d.reduced_at > REDUCED_EVERY and d.loaded and (direct or not d.player.has_frame):
                    d.reduced_at = now
                    d.player.pause(True)
                    if slot.offset is not None:
                        d.player.seek(slot.offset)
            self._check_failure(d, ch, slot)
            if d.player is not None:
                tex = d.player.frame(w, h)
                if tex:
                    return tex, 1.0
        p = self._poster_texture(d, item)
        if p:
            return p[0], (p[1] / max(p[2], 1)) / max(screen_aspect, 1e-3)
        return None, 1.0

    def _player_ok(self, d):
        if d.player is not None:
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
            d.player = mpvgl.Player(log=self.log, tls_ca=self._tls_ca(), ytdl_format=LOW_FORMAT_MUTED, ytdl=False)
            d.loaded = None
            self._apply_sound()
            return True
        except Exception as e:                                  # noqa: BLE001
            self.player_why = f"{type(e).__name__}: {e}"
            self.log(f"tv: no picture ({self.player_why}); posters only")
            return False

    def _lab_ca(self):
        """The homelab's own CA file (homelab.toml [tls] ca_file), or None."""
        H = TVL._homelab()
        if H is None:
            return None
        try:
            ca = H.config.expand(H.config.setting("tls", "ca_file", ""))
            return ca if ca and os.path.isfile(ca) else None
        except Exception:                                       # noqa: BLE001
            return None

    def _tls_ca(self):
        """The CA file for mpv: the system's trusted roots plus the lab's own CA, in one bundle.
        mpv's tls-ca-file replaces the trust store, so the lab's CA alone would fail every
        other site (YouTube's streams) with "Peer certificate failed verification"."""
        ca = self._lab_ca()
        return tls_bundle(ca) if ca else None

    def screen_height(self, screen):
        """The pixels a screen's picture is drawn at (its texture's height): what to ask for."""
        rect = self.px.get(screen)
        if not rect:
            from .scene import DEN
            rect = DEN.get(screen, (0, 0, 200, 175))
        return max(48, int(rect[3] * 1.5))

    def stream(self, ch, slot, full=False, screen=None):
        """{"url", "headers", "ytdl_format", "title", "start", "web", "kind"} for what's on, or
        None. Not full: sized to the screen (a transcode, or a small YouTube format)."""
        if slot is None:
            return None
        it = slot.item
        title = TVL.label(it)
        height = None if full else self.screen_height(screen or "big")
        sound = self._effective_sound(screen)[0] if screen else False
        if ch["kind"] == "live":
            if full:
                return {"url": it.get("url"), "headers": {}, "ytdl_format": FULL_FORMAT, "title": title, "start": None,
                        "web": it.get("url"), "server": "YouTube"}
            return self._resolved_stream(it.get("url"), height, title, None)
        if ch["kind"] == "files":
            return {"url": it.get("url"), "headers": {}, "ytdl_format": None, "title": title, "start": slot.offset,
                    "web": None, "server": "Files"}
        if ch["kind"] == "youtube" or it.get("server") == "youtube":
            import bromigos_youtube as Y
            path = Y.kept(ch.get("keep"), it.get("id")) if ch.get("keep") else None
            if path or full:
                return {"url": path or it.get("url"), "headers": {}, "ytdl_format": None if path else FULL_FORMAT,
                        "title": title, "start": slot.offset, "web": it.get("url"), "server": "YouTube",
                        "kept": bool(path)}
            return self._resolved_stream(it.get("url"), height, title, slot.offset)
        if it.get("download_source"):
            from bromigos_tvplay import downloaded_stream
            return dict(downloaded_stream(it), start=slot.offset, ytdl_format=None)
        a = TVL.server_of(ch)
        if a is None:
            return None
        start = (slot.offset + (0.0 if ch.get("override") else 1.0)) if slot.offset is not None else None     # the second it takes to open
        try:
            if full:
                s = a.video_stream(it, self.conf().get("fullscreen_quality", "direct"), start=start,
                                   device="bromigos-den-tv-full")
            else:
                s = a.video_stream(it, self.conf().get("quality", "auto"), height=height, start=start,
                                   device=f"bromigos-den-tv-{screen or 'big'}")
        except TypeError:                                       # an older bromigos-homelab: not sized
            s = a.video_stream(it, self.conf().get("quality", "auto"))
        return {"url": s["url"], "headers": s["headers"], "ytdl_format": None, "title": title, "start": slot.offset,
                "web": None, "server": {"jellyfin": "Jellyfin", "plex": "Plex"}.get(a.type, a.type), "adapter": a,
                "quality": s.get("quality"), "session": s.get("session"), "from_start": s.get("from_start")}

    # ------------------------------------------------------------------ YouTube's streams, resolved ahead
    @staticmethod
    def yt_height(height):
        return next((x for x in YT_HEIGHTS if x >= (height or 360)), YT_HEIGHTS[-1])

    def _resolved_stream(self, url, height, title, start):
        """The stream for a YouTube video from the resolver, or {"pending": True} while it
        works on it, or {"error": why}. mpv itself never runs yt-dlp for the den."""
        if not url:
            return None
        h = self.yt_height(height)
        r = self.resolved.get((url, h))
        if (r is None or ("video" in r and r["expires"] - time.time() < 600)
                or ("error" in r and time.time() - r["at"] > 120)):
            self.resolve_later(url, h, first=True)
            return {"pending": True}
        if "error" in r:
            return {"error": r["error"]}
        return {"url": r["video"], "audio": r.get("audio"), "headers": r.get("headers") or {}, "ytdl_format": None,
                "title": title, "start": start, "web": url, "server": "YouTube", "quality": f"{r.get('height')}p"}

    def resolve_later(self, url, height, first=False):
        """Queue a YouTube video's stream for the resolver (once): what's on first, then what's next."""
        key = (url, self.yt_height(height))
        r = self.resolved.get(key)
        if r is not None and ("error" in r and time.time() - r["at"] < 120
                              or "video" in r and r["expires"] - time.time() > 900):
            return
        with self._rlock:
            if key in self._rq:
                if first and self._rq[0] != key:
                    self._rq.remove(key)
                    self._rq.insert(0, key)
                return
            self._rq.insert(0, key) if first else self._rq.append(key)
        self._rwake.set()

    def _resolve_loop(self):
        """The resolver thread: yt-dlp for each queued video, one at a time. Covering,
        uncovering or a short clip ending never cancels one: its answer is kept (about six
        hours) for whenever the video comes on."""
        while not self.stop.is_set():
            with self._rlock:
                key = self._rq.pop(0) if self._rq else None
            if key is None:
                self._rwake.wait(10.0)
                self._rwake.clear()
                continue
            url, h = key
            try:
                import bromigos_youtube as Y
                t0 = time.time()
                self.resolved[key] = Y.stream(url, height=h, audio=True)
                self.log(f"tv: YouTube stream for {url.rsplit('=', 1)[-1]} ({h}p) in {time.time() - t0:.1f} s")
            except Exception as e:                              # noqa: BLE001  (StreamError, and anything else)
                self.resolved[key] = {"error": str(e)[:200] or type(e).__name__, "at": time.time()}
                self.log(f"tv: YouTube refused {url}: {self.resolved[key]['error']}")
            if len(self.resolved) > 64:
                now = time.time()
                for k in [k for k, v in self.resolved.items() if v.get("expires", v.get("at", 0) + 7200) < now]:
                    self.resolved.pop(k, None)
            self._changed()

    def _ensure_loaded(self, d, ch, slot):
        want = (ch["key"], str(slot.item.get("id")))
        if d.loaded == want or _mono() < self.retry_at.get(ch["key"], 0):
            return
        if d.loaded and d.loaded[0] == ch["key"] and d.tune is None:
            d.tune = (_mono(), self.channel(d.name)[0], ch["name"])     # the next item: a moment of static
        try:
            s = self.stream(ch, slot, screen=d.name)
        except Exception as e:                                  # noqa: BLE001
            s = None
            self.log(f"tv: no stream for {TVL.label(slot.item)}: {e}")
        if s and s.get("pending"):                              # YouTube: the resolver's on it; the poster meanwhile
            if d.loaded and d.loaded != want:
                self._unload(d)                                 # never the last item's picture
            return
        if s and s.get("error"):
            self.notes[ch["key"]] = (_mono(), f"YouTube refused: {s['error']}")
            self._skip(d, ch, slot, str(slot.item.get("id")), "YouTube refused it")
            return
        self._end_stream(d)                                     # the last item's transcode ends now
        d.loaded = want
        d.loaded_at = _mono()
        if not s or not s.get("url"):
            d.player.stop()                                     # never the last item's picture
            return
        d.stream = s
        start = None if s.get("from_start") or slot.offset is None else slot.offset + (0.0 if ch.get("override") else 1.0)   # a second to open
        d.player.load(s["url"], start=start, headers=s["headers"], ytdl_format=s.get("ytdl_format"),
                      title=s["title"], audio=s.get("audio"))
        d.player.pause(not d.allowed and not self.motion == "reduced")
        self._apply_sound()
        self.log(f"tv: {d.name}: playing {s['title']}" + (f" from {TVL.fmt_time(slot.offset)}" if slot.offset else "")
                 + (f" ({s['quality']})" if s.get("quality") else ""))
        self.wake.set()                                         # its poster, now
        self._keep(ch, slot)

    def _check_failure(self, d, ch, slot):
        """An item that won't play is skipped (left out of the schedule for a day), never a
        stalled screen: an error from mpv, or nothing after 25 s of trying while allowed."""
        p = d.player
        if not d.loaded or p is None:
            return
        if ch.get("override") and p.ended and p.ended[0] in ("eof", "error"):
            self.overrides.pop(d.name, None)
            self._unload(d)
            self.feedback(d.name, "BACK TO CHANNEL")
            return
        failed = p.ended is not None and p.ended[0] == "error"
        grace = 25 if (d.stream or {}).get("quality") in (None, "direct") else 60     # a transcode takes longer
        slow = (not p.started and d.allowed and _mono() - d.loaded_at > grace)
        if failed or slow:
            self._skip(d, ch, slot, d.loaded[1], "error" if failed else "no answer")
            return
        # drift: mpv's clock against the wall clock, every DRIFT_EVERY seconds once it plays.
        # Never while it's still opening or seeking: a seek in a server's transcode starts its
        # encoder again, and asking again before it answers only piles them up.
        now = _mono()
        if (p.started and p.has_frame and d.allowed and slot.offset is not None and now - d.loaded_at > 8
                and now - d.drift_at > DRIFT_EVERY and not p.seeking()):
            d.drift_at = now
            pos = p.position()
            # a transcode that starts late (or encodes at about real time) is let run: chasing
            # the clock would start its encoder again and again
            allow = DRIFT if (d.stream or {}).get("quality") in (None, "direct") else DRIFT_TRANSCODE
            if pos is not None and abs(pos - slot.offset) > allow and slot.offset < (slot.item.get("duration") or 0) - 2:
                d.drift_at = now + DRIFT_EVERY                   # and give that seek time to land
                p.seek(slot.offset)

    def _end_stream(self, d):
        """Tell the server a screen's transcode is over (off the drawing thread)."""
        st, d.stream = d.stream, None
        a = (st or {}).get("adapter")
        if a is not None and st.get("session") and hasattr(a, "video_stop"):
            threading.Thread(target=a.video_stop, args=(st,), daemon=True, name="den-tv-stop").start()

    def _unload(self, d):
        """A screen's player stops, and its server stream with it."""
        if d.player is not None:
            d.player.stop()
        d.loaded = None
        self._end_stream(d)

    def _skip(self, d, ch, slot, iid, why):
        """An item that won't play: left out for a day. Three in two minutes are the server's
        (or the network's) fault, not the items': they're put back and the channel tries
        again in a minute, on its poster, rather than skip the whole list."""
        now = _mono()
        recent = [(t, i) for t, i in self.fails.get(ch["key"], []) if now - t < 120] + [(now, iid)]
        self.fails[ch["key"]] = recent
        if len(recent) >= 3:
            TVL.unmark_bad([i for _, i in recent])
            self.fails[ch["key"]] = []
            self.retry_at[ch["key"]] = now + 60
            self.log(f"tv: {ch['name']} isn't answering; trying again in a minute")
            if ch["key"] not in self.notes or now - self.notes[ch["key"]][0] > 5:
                self.notes[ch["key"]] = (now, f"{ch['name']} isn't answering; trying again in a minute")
        else:
            self.log(f"tv: {TVL.label(slot.item)} didn't play ({why}); skipping it")
            TVL.mark_bad(iid)
        self.last_slot.pop(ch["key"], None)
        if d.player is not None:
            d.player.ended = None
        self._unload(d)

    def _poster_texture(self, d, item):
        if not item:
            return None
        iid = str(item.get("id"))
        if d.poster_tex and d.poster_tex[0] == iid:
            return d.poster_tex[1:]
        img = self.poster.get(iid)
        if img is None:
            return None
        data, w, h = img
        from . import glkit
        if d.poster_tex:
            GL.glDeleteTextures([d.poster_tex[1]])
        tex = glkit.texture_rgba(data, w, h, GL.GL_RGBA)
        d.poster_tex = (iid, tex, w, h)
        return tex, w, h

    def _close_player(self, d):
        self._end_stream(d)
        if d.player is not None:
            d.player.close()
            d.player = None
            d.loaded = None
            self.log(f"tv: {d.name}: nothing on; its mpv closed")

    # ------------------------------------------------------------------ the on-screen display
    def _osd(self, screen):
        """(static 0..1, texture) for a screen's OSD: the channel number while tuning, the
        volume while it changes, a small speaker on the screen the sound comes from."""
        if not self.enabled():
            return 0.0, None
        from . import glkit
        d = self.decks[screen]
        now = _mono()
        static, lines = 0.0, None
        if d.tune and now - d.tune[0] < TUNE_OSD:
            if self.motion == "full":
                static = max(0.0, 1.0 - (now - d.tune[0]) / TUNE_STATIC)
            lines = ("tune", d.tune[1], d.tune[2])
        elif d.tune:
            d.tune = None
        vol = None
        if d.vol_osd and now - d.vol_osd < VOLUME_OSD:
            vol = self.screens[screen]["volume"]
        elif d.vol_osd:
            d.vol_osd = None
        feedback = d.feedback[1] if d.feedback and now - d.feedback[0] < 1.5 else None
        if d.feedback and not feedback:
            d.feedback = None
        ages = [now - v for v in (d.tune[0] if d.tune else None, d.vol_osd, d.feedback[0] if d.feedback else None) if v is not None]
        alpha = round(min(1., max(0., (1.5 - min(ages)) / .35)), 2) if ages and self.motion == "full" else 1.
        tag = self.overrides.get(screen, {}).get("reason")
        speaker = screen == self.sound_screen() and self._effective_sound(screen)[0]
        if lines is None:
            lines = self._bumper(screen)
        if not (lines or vol is not None or speaker or static or feedback or tag) or screen not in self.px:
            return 0.0, None
        sig = (lines, vol, speaker, feedback, tag, alpha, self.px[screen][2:], glkit.T.version(0.0))
        if sig != d.osd_sig:
            d.osd_sig = sig
            self._draw_osd(d, lines, vol, speaker, feedback, tag, alpha)
        return static, d.osd_tex

    def _bumper(self, screen):
        """("bumper", channel name, what's on, the time) for the first BUMPER seconds of each
        item on a channel with `bumpers = true`, else None. From the wall clock, so every
        screen on the channel shows it together."""
        n, ch = self.channel(screen)
        if ch["kind"] == "own" or not ch.get("bumpers"):
            return None
        slot = self.slot(ch)
        if not slot or slot.offset is None or slot.offset > BUMPER:
            return None
        return ("bumper", ch["name"], TVL.label(slot.item), time.strftime("%H:%M", time.localtime(slot.start or 0)))

    def _draw_osd(self, d, lines, vol, speaker, feedback=None, tag=None, alpha=1.0):
        import cairo
        from . import glkit
        w, h = (max(32, int(v)) for v in self.px[d.name][2:])
        surf = cairo.ImageSurface(cairo.FORMAT_ARGB32, w, h)
        cr = cairo.Context(surf)
        r, g, b, _ = glkit.col("phosphor")
        u = h / 100.0
        cr.select_font_face("Geist Mono", cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_BOLD)
        if lines and lines[0] == "bumper":
            # a network's bumper: the channel's name large, what's on, the time, over a dark card
            _, chname, what, clock = lines
            cr.set_source_rgba(*glkit.col("panel", 0.82))
            cr.rectangle(0, 0, w, h)
            cr.fill()
            cr.set_source_rgba(r, g, b, 0.9)
            cr.set_line_width(max(1.0, u))
            cr.rectangle(4 * u, 4 * u, w - 8 * u, h - 8 * u)
            cr.stroke()

            def centre(t, size, y, alpha=0.95, maxw=None, least=0.0):
                cr.set_font_size(size)
                while maxw and size > least and cr.text_extents(t).x_advance > maxw:
                    size *= 0.92                                   # smaller to fit, down to `least`
                    cr.set_font_size(size)
                while maxw and t and cr.text_extents(t).x_advance > maxw:
                    t = t[:-2] + "…"
                e = cr.text_extents(t)
                cr.set_source_rgba(r, g, b, alpha)
                cr.move_to((w - e.x_advance) / 2, y)
                cr.show_text(t)
            series, _, title = what.partition(" · ")
            centre(chname.upper()[:28], 16 * u, 30 * u, maxw=w - 14 * u, least=8 * u)
            centre("UP NEXT", 7 * u, 46 * u, 0.7)
            centre(series, 9 * u, 60 * u, 0.95, maxw=w - 14 * u, least=6 * u)
            if title:
                centre(title, 8 * u, 72 * u, 0.85, maxw=w - 14 * u, least=6 * u)
            centre(clock, 7 * u, 88 * u, 0.7)
            lines = None
        if lines:
            _, n, name = lines
            cr.set_font_size(22 * u)
            cr.set_source_rgba(r, g, b, 0.95 * alpha)
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
                cr.set_source_rgba(r, g, b, (0.95 if on else 0.22) * alpha)
                cr.rectangle(x0 + i * bw + 1, y0, bw - 2, 7 * u)
                cr.fill()
            cr.set_font_size(9 * u)
            cr.set_source_rgba(r, g, b, 0.9 * alpha)
            cr.move_to(x0, y0 - 3 * u)
            cr.show_text(f"VOL {vol}")
        muted_feedback = feedback == "MUTED"
        if (speaker and vol is None) or muted_feedback:
            s = 7 * u
            x, y = w - 16 * u, h - 13 * u
            cr.set_source_rgba(r, g, b, 0.7 * (alpha if muted_feedback else 1.0))
            cr.move_to(x, y + s * 0.35)
            cr.line_to(x + s * 0.35, y + s * 0.35)
            cr.line_to(x + s * 0.8, y)
            cr.line_to(x + s * 0.8, y + s * 1.2)
            cr.line_to(x + s * 0.35, y + s * 0.85)
            cr.line_to(x, y + s * 0.85)
            cr.close_path()
            cr.fill()
            cr.set_line_width(max(1.0, 0.9 * u))
            if muted_feedback:
                cr.move_to(x + s, y + s * .2); cr.line_to(x + s * 1.6, y + s)
                cr.move_to(x + s * 1.6, y + s * .2); cr.line_to(x + s, y + s)
                cr.stroke()
            else:
                for k in (1, 2):
                    cr.arc(x + s * 0.8, y + s * 0.6, s * 0.35 * k, -0.9, 0.9)
                    cr.stroke()
        if feedback or tag:
            cr.set_font_size(8 * u)
            for text, yy, opacity in ((feedback, 12 * u, alpha), (tag, h - 7 * u, 1.0)):
                if text:
                    cr.set_source_rgba(*glkit.col("panel", .8 * opacity))
                    ext = cr.text_extents(text)
                    cr.rectangle(4 * u, yy - 9 * u, ext.x_advance + 6 * u, 12 * u); cr.fill()
                    cr.set_source_rgba(r, g, b, .95 * opacity); cr.move_to(7 * u, yy); cr.show_text(text)
        surf.flush()
        if d.osd_tex is not None:
            GL.glDeleteTextures([d.osd_tex])
        d.osd_tex = glkit.texture_from_cairo(surf)

    # ------------------------------------------------------------------ the hover hint
    def hint_visible(self):
        return self.enabled() and self.conf().get("hover_hint", True) is not False and self.hover is not None and self.hover in self.rects

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
        """("hint", screen) | ("screen", screen) | (None, None) for a logical point. The hint
        comes first: a click on it is never a click on the screen under it."""
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
        self.controls_tick()
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
        if kind == "hint":                     # a button, or nothing: never the screen under it
            self.hint_until = 0.0
            act = self._button_at(x, y)
            return self._do(act, x) if act else None
        if kind == "screen" and button == 1:
            n, ch = self.channel(s)
            if ch["kind"] != "own":
                return self.open_full(s)
            return self.tune_to(s, step=1)
        return None

    def release(self):
        self.dragging = False

    def _do(self, act, x=None):
        s = self.hover
        if s is None:
            return None
        if act == "prev":
            return self.tune_to(s, step=-1)
        if act == "next":
            return self.tune_to(s, step=1)
        if act == "full":
            return self.open_full(s)
        if act == "web":
            return self.open_web(s)
        if act == "guide":
            return self.open_guide(s)
        if act == "skip":
            return self.skip_item(s)
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

    def _hint_note(self, s):
        """The hint's warning line, or "": what went wrong on the channel (in the last five
        minutes), or the sound is on but can't be heard."""
        st = self.screens[s]
        n, ch = self.channel(s)
        note = self.notes.get(ch["key"])
        if note and _mono() - note[0] < 300:
            return note[1]
        if not st["sound"]:
            snd = self.sound_screen()
            return f"Sound comes from {TVL.SCREEN_NAMES.get(snd, snd)}" if snd else ""
        from .sound import muted
        if self.desktop_muted:
            return "Your desktop is muted"
        if muted():
            return "bromigOS's sound is muted (bromigos-live mute)"
        if self.quiet:
            return "Quiet while locked or on the screensaver"
        return ""

    def hint_texture(self, sf):
        """(texture, logical rect) of the hint, drawn again when what it says changes."""
        if not self.hint_visible():
            return None
        s = self.hover
        n, ch = self.channel(s)
        lu = self.lineup(s)
        slot = self.slot(ch)
        st = self.screens[s]
        note = self._hint_note(s)
        sig = (s, n, len(lu), ch["key"], (slot.item or {}).get("id") if slot else None, st["sound"], st["volume"],
               int(slot.offset // 60) if slot and slot.offset else None, sf, note)
        if sig != self.hint_sig or self.hint_tex is None:
            self.hint_sig = sig
            self._draw_hint(s, n, lu, ch, slot, st, sf, note)
        return self.hint_tex, self.hint_rect

    def _draw_hint(self, s, n, lu, ch, slot, st, sf, note=""):
        import cairo
        from . import glkit
        W, H = int(HINT_W * sf), int(HINT_H * sf)
        surf = cairo.ImageSurface(cairo.FORMAT_ARGB32, W, H)
        cr = cairo.Context(surf)
        cr.scale(sf, sf)
        ph, dim, soft = glkit.col("phosphor"), glkit.col("dim"), glkit.col("soft")
        warn = glkit.col("warn")
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
            button(256, 80, 64, 24, "SKIP", "skip")
            if note:
                text(10, 88, note, 10, warn if st["sound"] else dim, st["sound"], maxw=240)
            else:
                text(10, 88, "Click screen: full screen with sound", 10, dim, False, maxw=240)
            text(10, 103, "Wheel: channel · bar: volume", 10, dim, False, maxw=240)
        else:
            text(76, 61, "Scroll or ◀ ▶ to change channel", 10, dim, False)
        button(324, 80, 70, 24, "GUIDE", "guide")
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

    # ------------------------------------------------------------------ full screen, the web page, the guide
    def _pick(self, screen):
        """The screen a command acts on: the one named, else the one under the pointer, else
        the one with the sound, else the first showing a media channel, else the big monitor."""
        if screen and screen in self.screens:
            return screen
        if self.hover in self.screens:
            return self.hover
        s = self.sound_screen() or self.media_screen()[0]
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
        if self.full_session and self.full_session.proc.poll() is None:
            if self.full_session.screen == screen:
                self.full_session.retune()
                return f"full screen: {s['title']}"
            self.full_session.close()
        from .tvfull import Session
        try:
            self.full_session = Session(self, screen, s)
            self.full_proc = self.full_session.proc
        except OSError as e:
            return f"mpv didn't start: {e}"
        self._apply_sound()
        self.log(f"tv: full screen: {s['title']}")
        return f"full screen: {s['title']}"

    def open_web(self, screen=None):
        screen = self._pick(screen)
        n, ch = self.channel(screen)
        slot = self.slot(ch)
        if ch["kind"] == "own" or not slot:
            return "no media channel on"
        url = None
        if ch["kind"] in ("youtube", "live") or slot.item.get("server") == "youtube":
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

    def open_guide(self, screen=None):
        """The independent Den TV application, also usable while playback is off."""
        try:
            subprocess.Popen(["bromigos-tv-guide"], stdout=subprocess.DEVNULL,
                             stderr=subprocess.DEVNULL, start_new_session=True)
            return "Opened Den TV"
        except OSError as e:
            return f"Den TV: {e}"

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
        """Lists (each channel's, cached), YouTube live checks, posters, keep = "all", and
        where each in-order picked channel is."""
        live_at = {}
        while not self.stop.is_set():
            try:
                chans = TVL.channels(self.cfg) if self.enabled() else []
                on = self.media_screens()
                keys = {ch["key"] for _, ch in on}
                for ch in sorted(chans, key=lambda c: 0 if c["key"] in keys else 1):
                    if self.stop.is_set():
                        return
                    TVL.fetch_items(ch, max_age=float(self.conf().get("refresh_minutes", 15)) * 60)
                    TVL.rotation_advance(ch)
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
                for s, ch in on:
                    slot = self.slot(ch)
                    if slot:
                        self._prefetch(s, ch, slot)
                        self._fetch_poster(ch, slot.item)
                        if slot.next:
                            self._fetch_poster(ch, slot.next)
                if chans:
                    TVL.catalog(max_age=900)
            except Exception as e:                              # noqa: BLE001  never take the layer down
                self.log(f"tv: worker: {type(e).__name__}: {e}")
            self.wake.wait(20.0)
            self.wake.clear()

    def _prefetch(self, screen, ch, slot):
        """YouTube: resolve what's on and the next two ahead, so each starts at once."""
        if ch["kind"] not in ("youtube", "live") and slot.item.get("server") != "youtube":
            return
        h = self.screen_height(screen)
        self.resolve_later(slot.item.get("url"), h, first=True)
        if ch["kind"] != "youtube" and not ch.get("picks"):
            return
        nxt = slot
        for _ in range(2):
            if not nxt or not nxt.end:
                break
            nxt = TVL.now_next(ch, nxt.end + 0.001)
            if nxt and (ch["kind"] == "youtube" or nxt.item.get("server") == "youtube"):
                import bromigos_youtube as Y
                if not (ch.get("keep") and Y.kept(ch.get("keep"), nxt.item.get("id"))):
                    self.resolve_later(nxt.item.get("url"), h)

    def _fetch_poster(self, ch, item):
        iid = str(item.get("id"))
        if not item or iid in self.poster:
            return
        url, headers = None, {}
        if ch["kind"] in ("youtube", "live") or item.get("server") == "youtube":
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
            ctx = ssl.create_default_context()                # the system's CAs, and the lab's added
            ca = self._lab_ca()
            if ca:
                ctx.load_verify_locations(cafile=ca)
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=10, context=ctx) as r:
                b = r.read(4 << 20)
            im = Image.open(io.BytesIO(b)).convert("RGBA")
            im.thumbnail((360, 360))
            self.poster[iid] = (im.tobytes(), im.width, im.height)
            if len(self.poster) > 48:
                showing = {d.poster_tex[0] for d in self.decks.values() if d.poster_tex}
                for k in [k for k in list(self.poster)[:16] if k not in showing]:
                    self.poster.pop(k, None)
            self._changed()
        except Exception as e:                                  # noqa: BLE001
            self.log(f"tv: no poster for {TVL.label(item)}: {type(e).__name__}")
            self.poster[iid] = None

    # ------------------------------------------------------------------ commands (bromigos-live tv …)
    @staticmethod
    def parse(arg):
        """(verb, screen or None, the other words): `--screen X`, `--screen=X` or a bare
        screen name (big, wave, emblem; scope and small too)."""
        parts = arg.split()
        verb = parts[0] if parts else "state"
        rest, screen, i = [], None, 1
        while i < len(parts):
            w = parts[i]
            if w == "--screen" and i + 1 < len(parts):
                screen = parts[i + 1]
                i += 2
                continue
            if w.startswith("--screen="):
                screen = w.split("=", 1)[1]
            elif w in TVL.SCREENS or w in ALIASES:
                screen = w
            else:
                rest.append(w)
            i += 1
        if screen is not None:
            screen = ALIASES.get(screen, screen)
            if screen not in TVL.SCREENS:
                screen = "?" + screen
        return verb, screen, rest

    def command(self, arg):
        if arg.startswith("play-json "):
            return self.play_json(arg[len("play-json "):])
        verb, screen, rest = self.parse(arg)
        if screen and screen.startswith("?"):
            return f"no screen called {screen[1:]}: big, wave (the scope) or emblem (the small monitor)"
        if verb == "select":
            return self.select_screen(screen or (rest or ["none"])[0])
        if verb == "remote":
            return self.remote((rest or [""])[0], screen)
        if verb in ("skip", "previous"):
            return self.skip_item(self._pick(screen), verb == "previous")
        if verb in ("next", "prev"):
            return self.tune_to(self._pick(screen), step=1 if verb == "next" else -1)
        if verb == "set":
            if not rest or not rest[0].isdigit():
                return "bromigos-live tv set N [--screen big|wave|emblem]"
            return self.tune_to(self._pick(screen), number=int(rest[0]))
        if verb == "open":
            return self.open_full(screen)
        if verb == "web":
            return self.open_web(screen)
        if verb == "guide":
            return self.open_guide(screen)
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
            return "bromigos-live tv volume up|down|N [--screen big|wave|emblem]"
        if verb == "reload":
            return self.reconfigured() or "channels read again"
        if verb == "rename":
            if len(rest) != 2:
                return "bromigos-live tv rename OLD-KEY NEW-KEY"
            return self.rekey(*rest)
        if verb == "list":
            out = []
            snd = self.sound_screen()
            for s in TVL.SCREENS:
                cur, _ = self.channel(s)
                for n, ch in enumerate(self.lineup(s), 1):
                    out.append(f"{s:<7} {'*' if n == cur else ' '} {n:>2}  {ch['name']}"
                               + ("" if ch["kind"] == "own" else f"  ({ch['kind']})")
                               + ("  [sound]" if n == cur and s == snd else ""))
            return "\n".join(out)
        if verb == "state":
            import json
            return json.dumps(self.describe(), indent=None if "--json" in rest else 1)
        return ("bromigos-live tv next|prev|set N|open|web|guide|sound on|off|toggle|volume up|down|N|list|state "
                "[--screen big|wave|emblem]")

    def _playing(self, s):
        d = self.decks[s]
        if d.player is None or not d.loaded:
            return None
        pos = d.player.position()
        try:
            hw = d.player.m.hwdec_current
        except Exception:                                       # noqa: BLE001
            hw = None
        on, vol = self._effective_sound(s)
        return {"item": d.loaded[1], "position": None if pos is None else round(pos, 2), "hwdec": hw,
                "paused": d.player.paused(), "sound": on, "volume": round(vol), "has_frame": d.player.has_frame}

    def describe(self):
        snd = self.sound_screen()
        out = {"screens": {}, "playing": None, "picture": "mpv" if any(d.player for d in self.decks.values())
               else (self.player_why or "off"), "covered": sorted(self.covered), "sound_from": snd,
               "desktop_muted": self.desktop_muted, "max_playing": self.max_playing(),
               "selected": self.selected, "digits": self.digits, "hover_hint": self.conf().get("hover_hint", True)}
        out['lineups'] = {screen: [dict(number=n, name=ch['name'], key=ch['key'], kind=ch['kind'])
                                      for n, ch in enumerate(self.lineup(screen), 1)] for screen in TVL.SCREENS}
        for s in TVL.SCREENS:
            n, ch = self.channel(s)
            st = self.screens[s]
            d = self.decks[s]
            r = {"channel": n, "of": len(self.lineup(s)), "name": ch["name"], "kind": ch["kind"], "key": ch["key"],
                 "sound": st["sound"], "volume": st["volume"], "rect": [round(v) for v in self.rects.get(s, ())],
                 "allowed": d.allowed, "capped": d.capped, "covered": s in self.covered,
                 "follows": self.follows.get(s), "tuned": bool(st.get("tuned")),
                 "on_demand": s in self.overrides}
            slot = self.slot(ch)
            if slot:
                keep = ("id", "title", "series", "season", "episode", "kind", "duration", "year", "server", "poster",
                        "thumbnail", "url", "group", "download_source")
                r["now"] = TVL.label(slot.item)
                r["offset"] = None if slot.offset is None else round(slot.offset, 2)
                r["next"] = TVL.label(slot.next) if slot.next else None
                r["item"] = {k: slot.item.get(k) for k in keep if slot.item.get(k) is not None}
                r["next_item"] = {k: slot.next.get(k) for k in keep if slot.next.get(k) is not None} if slot.next else None
                r["start"], r["end"] = slot.start, slot.end
                r["source"] = ch.get("source") or None
            r["playing"] = self._playing(s)
            out["screens"][s] = r
        first = snd or next((s for s in PRIORITY if out["screens"][s]["playing"]), None)
        if first:
            out["playing"] = out["screens"][first]["playing"]
        out["allowed"] = any(self.decks[s].allowed for s in TVL.SCREENS)
        out["hint"] = self.hover
        if self.hover and self.hint_rect:
            hx, hy = self.hint_rect[:2]
            out["hint_rect"] = [round(v) for v in self.hint_rect]
            out["buttons"] = {a: [round(hx + bx + bw / 2), round(hy + by + bh / 2)] for bx, by, bw, bh, a in self.buttons}
            out["hint_note"] = self._hint_note(self.hover)
        out["input"] = self.input_rects()
        out["full_screen"] = self.full_proc is not None and self.full_proc.poll() is None
        return out

    def close(self):
        if self.full_session:
            self.full_session.close()
        if self.selected:
            self.select_screen("none")
        self.stop.set()
        self.wake.set()
        self._rwake.set()
        for d in self.decks.values():
            self._close_player(d)
            for t in (d.osd_tex,) + ((d.poster_tex[1],) if d.poster_tex else ()):
                if t:
                    try:
                        GL.glDeleteTextures([t])
                    except Exception:                           # noqa: BLE001
                        pass
            d.osd_tex = d.poster_tex = None
        if self.hint_tex:
            try:
                GL.glDeleteTextures([self.hint_tex])
            except Exception:                                   # noqa: BLE001
                pass
        self.hint_tex = None
