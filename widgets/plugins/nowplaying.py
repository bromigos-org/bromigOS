"""NOW PLAYING: what any media player is playing, through MPRIS (the desktop's standard
for media players: Spotify, Firefox, mpv, VLC, …), with its cover art, the controls and,
when cava is installed, a visualizer.

MPRIS is read through playerctl's GObject bindings, or its command when the bindings are
missing. The visualizer runs cava only while something plays, the panel is on screen and
motion isn't reduced; otherwise nothing runs. Cover art from the web is fetched once and
kept in ~/.cache/bromigos/widgets/art.
"""
import hashlib
import math
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time

sys.path.append(os.path.dirname(os.path.realpath(__file__)))   # after the standard library
import _kit as K  # noqa: E402

import cairo  # noqa: E402

import draw as D  # noqa: E402

ART_DIR = os.path.join(K.CACHE, "art")
FIELDS = ("instance", "status", "title", "artist", "album", "art", "length", "position")
CLI_FORMAT = "\t".join("{{%s}}" % f for f in ("playerInstance", "status", "xesam:title", "xesam:artist",
                                              "xesam:album", "mpris:artUrl", "mpris:length", "position"))


# ------------------------------------------------------------------ MPRIS records
def record(instance, status, meta, position=None, caps=None):
    """A player as the panel draws it, from MPRIS metadata (a plain dict of xesam:/mpris:
    keys). Lengths and positions are in seconds."""
    def one(v):
        if isinstance(v, (list, tuple)):
            return ", ".join(str(x) for x in v if x)
        return str(v) if v not in (None, "") else ""
    length = meta.get("mpris:length")
    try:
        length = int(length) / 1e6 if length not in (None, "") else None
    except (TypeError, ValueError):
        length = None
    try:
        position = int(position) / 1e6 if position not in (None, "") else None
    except (TypeError, ValueError):
        position = None
    name = instance.split(".", 1)[0] if instance else "?"
    c = {"play": True, "pause": True, "next": True, "previous": True, "seek": True}
    c.update(caps or {})
    return {"instance": instance, "name": name, "status": (status or "Stopped").capitalize(),
            "title": one(meta.get("xesam:title")) or (os.path.basename(one(meta.get("xesam:url"))) or ""),
            "artist": one(meta.get("xesam:artist")), "album": one(meta.get("xesam:album")),
            "art": one(meta.get("mpris:artUrl")) or None, "length": length if length and length > 0 else None,
            "position": position, "caps": c, "seen": time.time()}


def parse_cli(out):
    """Players from `playerctl -a metadata --format …` (one tab-separated line each)."""
    rows = []
    for line in (out or "").splitlines():
        p = line.split("\t")
        if len(p) < len(FIELDS) or not p[0]:
            continue
        inst, status, title, artist, album, art, length, pos = p[:8]
        rows.append(record(inst, status, {"xesam:title": title, "xesam:artist": artist, "xesam:album": album,
                                          "mpris:artUrl": art, "mpris:length": length}, pos))
    return rows


def pick(players, prefer=None, last=None):
    """The player to show: the preferred one if it's there, else the one playing (the last
    shown first, so two playing players don't flicker), else the last shown, else the first."""
    if not players:
        return None
    if prefer:
        hit = next((p for p in players if p["name"].lower() == prefer.lower() or p["instance"] == prefer), None)
        if hit:
            return hit
    playing = [p for p in players if p["status"] == "Playing"]
    if playing:
        return next((p for p in playing if p["instance"] == last), playing[0])
    return next((p for p in players if p["instance"] == last), players[0])


# ------------------------------------------------------------------ sources
class GiSource:
    """playerctl's GObject bindings: properties from D-Bus, held by proxies per player."""
    kind = "playerctl (GObject)"

    def __init__(self):
        import gi
        gi.require_version("Playerctl", "2.0")
        from gi.repository import Playerctl
        self.P = Playerctl
        self.players = {}

    def read(self):
        names = self.P.list_players()
        seen, out = set(), []
        for n in names:
            inst = n.instance
            seen.add(inst)
            pl = self.players.get(inst)
            if pl is None:
                try:
                    pl = self.players[inst] = self.P.Player.new_from_name(n)
                except Exception:                      # noqa: BLE001  GLib.Error: it went away
                    continue
            try:
                meta = pl.props.metadata
                meta = meta.unpack() if meta is not None else {}
                status = pl.props.playback_status.value_nick
                try:
                    pos = pl.get_position()
                except Exception:                      # noqa: BLE001  no Position
                    pos = None
                caps = {"play": pl.props.can_play, "pause": pl.props.can_pause, "next": pl.props.can_go_next,
                        "previous": pl.props.can_go_previous, "seek": pl.props.can_seek}
            except Exception:                          # noqa: BLE001
                continue
            out.append(record(inst, status, meta, pos, caps))
        for gone in set(self.players) - seen:
            self.players.pop(gone, None)
        return out

    def control(self, instance, verb, arg=None):
        pl = self.players.get(instance)
        if pl is None:
            return
        if verb == "seek":
            pl.set_position(int(arg * 1e6))
        else:
            getattr(pl, {"play-pause": "play_pause", "next": "next", "previous": "previous"}[verb])()


class CliSource:
    """The playerctl command: one call reads every player."""
    kind = "playerctl"

    def read(self):
        return parse_cli(K.run(["playerctl", "-a", "metadata", "--format", CLI_FORMAT], timeout=3))

    def control(self, instance, verb, arg=None):
        args = ["position", f"{arg:.1f}"] if verb == "seek" else [verb]
        K.spawn(["playerctl", "-p", instance] + args)


class DemoSource:
    kind = "demo"

    def __init__(self):
        self.t0 = time.time() - 83

    def read(self):
        return [record("spotify", "Playing", {"xesam:title": "Harbour Lights at Low Tide", "xesam:artist": ["The Relay Keepers"],
                                              "xesam:album": "Signals from the Breakwater", "mpris:artUrl": "demo:art",
                                              "mpris:length": 247_000_000}, 83_000_000),
                record("firefox.instance_1_42", "Paused", {"xesam:title": "Lamplighter's Field Recording No. 4",
                                                          "xesam:artist": "Greywater Archive", "mpris:length": 1_412_000_000},
                       610_000_000),
                record("mpv", "Stopped", {"xesam:title": "drift-ambience.flac", "xesam:artist": ""})]

    def control(self, instance, verb, arg=None):
        pass


def source():
    """The bindings, else the command, else None."""
    if K.demo():
        return DemoSource()
    try:
        return GiSource()
    except (ImportError, ValueError):
        pass
    return CliSource() if shutil.which("playerctl") else None


# ------------------------------------------------------------------ the visualizer (cava)
CAVA_CONF = """[general]
bars = {bars}
framerate = 20
sleep_timer = 0
[output]
method = raw
raw_target = /dev/stdout
data_format = ascii
ascii_max_range = 100
bar_delimiter = 59
frame_delimiter = 10
"""


def parse_cava(line):
    """[0..1] per bar from one line of cava's raw ascii output ("12;40;7;\\n")."""
    out = []
    for x in line.strip().strip(";").split(";"):
        try:
            out.append(max(0.0, min(1.0, int(x) / 100)))
        except ValueError:
            return None
    return out or None


class Cava:
    """cava on a thread, while asked; .bars is the newest frame."""

    def __init__(self, bars=24):
        self.n = bars
        self.proc, self.bars, self.conf = None, [0.0] * bars, None

    @staticmethod
    def available():
        return shutil.which("cava") is not None

    def running(self):
        return self.proc is not None and self.proc.poll() is None

    def start(self):
        if self.running() or not self.available():
            return
        fd, self.conf = tempfile.mkstemp(prefix="bromigos-cava-", suffix=".conf")
        with os.fdopen(fd, "w") as f:
            f.write(CAVA_CONF.format(bars=self.n))
        try:
            self.proc = subprocess.Popen(["cava", "-p", self.conf], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                         stdin=subprocess.DEVNULL, text=True, bufsize=1)
        except OSError:
            self.proc = None
            return
        threading.Thread(target=self._read, args=(self.proc,), daemon=True, name="cava").start()

    def _read(self, proc):
        for line in proc.stdout:
            b = parse_cava(line)
            if b:
                self.bars = b

    def stop(self):
        p, self.proc = self.proc, None
        if p is not None:
            p.terminate()
            try:
                p.wait(timeout=1)
            except subprocess.TimeoutExpired:
                p.kill()
        if self.conf:
            try:
                os.unlink(self.conf)
            except OSError:
                pass
            self.conf = None
        self.bars = [0.0] * self.n


def demo_bars(n=24):
    return [0.25 + 0.6 * abs(math.sin(i * 0.9 + 0.4)) * (1 - i / (n * 1.3)) for i in range(n)]


# ------------------------------------------------------------------ cover art
def demo_art(size=256):
    """A made-up cover: a harbour light over water, drawn with cairo."""
    s = cairo.ImageSurface(cairo.FORMAT_ARGB32, size, size)
    cr = cairo.Context(s)
    g = cairo.LinearGradient(0, 0, 0, size)
    g.add_color_stop_rgb(0, 0.05, 0.08, 0.18)
    g.add_color_stop_rgb(0.62, 0.55, 0.28, 0.32)
    g.add_color_stop_rgb(0.63, 0.06, 0.12, 0.2)
    g.add_color_stop_rgb(1, 0.02, 0.04, 0.08)
    cr.set_source(g)
    cr.paint()
    cr.set_source_rgba(1.0, 0.85, 0.5, 0.95)
    cr.arc(size * 0.68, size * 0.42, size * 0.09, 0, 2 * math.pi)
    cr.fill()
    for i in range(9):
        y = size * (0.66 + i * 0.035)
        cr.set_source_rgba(1.0, 0.8, 0.5, 0.5 - i * 0.05)
        cr.rectangle(size * (0.6 - i * 0.01), y, size * (0.16 + i * 0.02), size * 0.008)
        cr.fill()
    cr.set_source_rgba(0.02, 0.03, 0.05, 1)
    cr.rectangle(size * 0.2, size * 0.36, size * 0.035, size * 0.27)
    cr.fill()
    return s


class Art:
    """Cover art: a file:// picture at once, an http(s) one fetched once on a thread into the
    cache, then read from there."""

    def __init__(self):
        self.pending = set()
        self.demo = None

    def path_for(self, url):
        return os.path.join(ART_DIR, hashlib.sha1(url.encode()).hexdigest()[:20] + ".img")

    def get(self, url, size, on_ready=None):
        if not url:
            return None
        if url == "demo:art":
            if self.demo is None:
                self.demo = demo_art()
            return self.demo
        if url.startswith("file://") or url.startswith("/"):
            return K.picture(url, size)
        if url.startswith(("http://", "https://")):
            p = self.path_for(url)
            if os.path.isfile(p):
                return K.picture(p, size)
            if url not in self.pending and not K.demo():
                self.pending.add(url)
                threading.Thread(target=self._fetch, args=(url, p, on_ready), daemon=True, name="art").start()
        return None

    def _fetch(self, url, path, on_ready):
        try:
            data = K.fetch_bytes(url, timeout=10)
            os.makedirs(ART_DIR, exist_ok=True)
            tmp = path + ".tmp"
            with open(tmp, "wb") as f:
                f.write(data)
            os.replace(tmp, path)
        except OSError:
            return
        finally:
            self.pending.discard(url)
        if on_ready:
            on_ready()


def mmss(s):
    if s is None:
        return "--:--"
    s = int(max(0, s))
    return f"{s // 3600}:{s // 60 % 60:02d}:{s % 60:02d}" if s >= 3600 else f"{s // 60}:{s % 60:02d}"


# ------------------------------------------------------------------ drawing shared with SPOTIFY
def draw_art(panel, cr, surf, x, y, size, tip):
    """The cover in a framed square, or an empty frame with a note when there's none."""
    D.src(cr, "void", 0.9)
    cr.rectangle(x, y, size, size)
    cr.fill()
    if surf is not None:
        K.draw_picture(cr, surf, x, y, size, size, cover=True)
    else:
        D.src(cr, "dim", 0.5)
        cr.set_line_width(1)
        r = size * 0.22
        cr.arc(x + size / 2, y + size / 2, r, 0, 2 * math.pi)
        cr.stroke()
        cr.arc(x + size / 2, y + size / 2, r * 0.18, 0, 2 * math.pi)
        cr.fill()
    D.src(cr, "dim", 0.6)
    cr.set_line_width(1)
    cr.rectangle(x + 0.5, y + 0.5, size - 1, size - 1)
    cr.stroke()
    D.brackets(cr, x - 3, y - 3, size + 6, size + 6, 8, "phosphor", 1.2, 0.8)
    panel.region(x, y, size, size, tip)


def draw_progress(panel, cr, x, y, w, pos, length, seek=None, color="phosphor", tip_what="the track"):
    """A thin bar with the times under it; a click seeks when seek(seconds) is given."""
    frac = (pos / length) if pos is not None and length else 0
    D.bar(cr, x, y, w, 4, frac, color)
    if pos is not None and length:
        D.src(cr, color)
        cr.rectangle(x + w * min(1, frac) - 1, y - 3, 2, 10)
        cr.fill()
    D.text(cr, x, y + 9, mmss(pos), 10, "soft", "regular")
    D.text(cr, x + w, y + 9, mmss(length), 10, "static", "regular", align="right")
    if seek and length:
        # one region per tenth, so a click lands near where it was
        for i in range(10):
            panel.region(x + w * i / 10, y - 6, w / 10, 16,
                         f"{mmss(pos)} of {mmss(length)}. Click to jump to {mmss(length * (i + 0.5) / 10)}",
                         lambda s=length * (i + 0.5) / 10: seek(s))
    else:
        panel.region(x, y - 6, w, 16, f"{mmss(pos)} of {mmss(length)} into {tip_what}"
                     + ("" if length else " (the player doesn't say how long it is)"))


def draw_transport(panel, cr, x, y, playing, act, size=26, can=None, what="the player"):
    """⏮ ⏯ ⏭ as vector buttons; returns the width. act(verb) carries a click out."""
    can = can or {}
    gap = 8
    cx = x
    for verb, ok in (("previous", can.get("previous", True)), ("play-pause", can.get("play", True) or can.get("pause", True)),
                     ("next", can.get("next", True))):
        s = size + (6 if verb == "play-pause" else 0)
        yy = y - (3 if verb == "play-pause" else 0)
        D.src(cr, "guard", 0.9)
        cr.rectangle(cx, yy, s, s)
        cr.fill()
        D.src(cr, "phosphor" if verb == "play-pause" else "dim", 0.9)
        cr.set_line_width(1)
        cr.rectangle(cx + 0.5, yy + 0.5, s - 1, s - 1)
        cr.stroke()
        col = "phosphor" if ok else "static"
        m, c = s * 0.3, (cx + s / 2, yy + s / 2)
        D.src(cr, col)
        if verb == "play-pause" and playing:
            cr.rectangle(c[0] - m * 0.7, c[1] - m, m * 0.5, 2 * m)
            cr.rectangle(c[0] + m * 0.2, c[1] - m, m * 0.5, 2 * m)
            cr.fill()
        elif verb == "play-pause":
            cr.move_to(c[0] - m * 0.6, c[1] - m)
            cr.line_to(c[0] + m, c[1])
            cr.line_to(c[0] - m * 0.6, c[1] + m)
            cr.close_path()
            cr.fill()
        else:
            d = -1 if verb == "previous" else 1
            for k in (0, 1):
                ox = c[0] + d * (k * m * 0.9 - m * 0.45)
                cr.move_to(ox - d * m * 0.45, c[1] - m * 0.8)
                cr.line_to(ox + d * m * 0.45, c[1])
                cr.line_to(ox - d * m * 0.45, c[1] + m * 0.8)
                cr.close_path()
            cr.fill()
            cr.rectangle(c[0] + d * m * 0.95 - 1, c[1] - m * 0.8, 2, m * 1.6)
            cr.fill()
        words = {"previous": "Previous track", "next": "Next track",
                 "play-pause": "Pause" if playing else "Play"}[verb]
        panel.region(cx, yy, s, s, f"{words} ({what})" + ("" if ok else ": this player doesn't allow it"),
                     (lambda v=verb: act(v)) if ok else None)
        cx += s + gap
    return cx - x - gap


def draw_bars(cr, x, y, w, h, bars, color="phosphor", alpha=0.85):
    """The visualizer's bars, mirrored lightly under a baseline: bars and reflection both
    inside the box (the bars take 4/5 of it)."""
    n = len(bars)
    if not n:
        return
    bw = w / n
    hb = max(1.0, (h - 2) / 1.25)
    for i, v in enumerate(bars):
        bh = max(1.0, v * hb)
        col = "amber" if v > 0.85 else color
        D.src(cr, col, alpha * (0.45 + 0.55 * v))
        cr.rectangle(x + i * bw + 1, y + hb - bh, bw - 2, bh)
        cr.fill()
        D.src(cr, col, 0.12)
        cr.rectangle(x + i * bw + 1, y + hb + 2, bw - 2, bh * 0.25)
        cr.fill()


# ------------------------------------------------------------------ the panel
class NowPlayingPanel(K.KitPanel):
    name, title = "nowplaying", "NOW PLAYING"
    description = "What your media players are playing, with the cover, the controls and a visualizer"
    category, reads = "media", "your media players (MPRIS), and cava for the visualizer"
    width, height = 460, 200
    interval = 1.0
    settings = [
        {"key": "player", "label": "Player to show", "kind": "text", "default": "",
         "hint": "A player's name, such as spotify or firefox. Empty: whichever is playing."},
        {"key": "visualizer", "label": "Visualizer", "kind": "bool", "default": True,
         "hint": "Bars that move with the sound, drawn by cava while something plays"},
    ]
    sizes = {
        "compact": ((240, 100), (420, 150), (300, 110)),
        "standard": ((380, 170), (640, 260), (460, 200)),
        "wide": ((660, 150), (1200, 280), (780, 190)),
        "tall": ((330, 380), (560, 900), (380, 520)),
        "large": ((660, 400), (1200, 900), (780, 520)),
    }
    default_size = "standard"

    def __init__(self, cfg=None, wake=None):
        super().__init__(cfg, wake)
        self.src = source()
        self.players, self.current, self.chosen = [], None, None
        self.art = Art()
        self.cava = Cava()
        self.read_at = 0.0
        self.error = None
        self.tick()

    # ---- data
    def tick(self):
        now = time.monotonic()
        seen = now - self.drawn_at < 30
        if self.src and (seen or not self.players) and now - self.read_at >= 0.9:
            self.read_at = now
            try:
                self.players = self.src.read()
                self.error = None
            except Exception as e:                     # noqa: BLE001  shown in the panel
                self.error = K._words(e)
        prefer = self.chosen or self.conf.get("player") or None
        self.current = pick(self.players, prefer, (self.current or {}).get("instance"))
        self._visualizer(now)

    def want_visualizer(self, now=None):
        now = now or time.monotonic()
        cur = self.current
        return bool(cur and cur["status"] == "Playing" and self.conf.get("visualizer", True)
                    and K.motion() == "full" and now - self.drawn_at < 5 and not K.demo()
                    and self.last_class not in (None, "compact"))

    def _visualizer(self, now):
        if self.want_visualizer(now):
            self.cava.start()
        elif self.cava.running():
            self.cava.stop()
        self.animating = self.cava.running()

    def __del__(self):
        try:
            self.cava.stop()
        except Exception:                              # noqa: BLE001
            pass

    def control(self, verb, arg=None):
        cur = self.current
        if not cur or not self.src:
            return
        try:
            self.src.control(cur["instance"], verb, arg)
        except Exception as e:                         # noqa: BLE001
            self.error = K._words(e)
        self.read_at = 0.0

    def choose(self, inst):
        self.chosen = inst
        self.current = pick(self.players, inst)

    def bars(self):
        if K.demo():
            return demo_bars(self.cava.n)
        if self.cava.running():
            return self.cava.bars
        return None

    def _redraw(self):
        if callable(self.wake):
            try:
                self.wake(self)
            except Exception:                          # noqa: BLE001
                pass

    # ---- drawing
    def draw(self, cr, w, h):
        cls = self.size_class(w, h)
        cur = self.current
        right = None
        if cur:
            right = cur["name"].upper() + ("" if cls == "compact" else f" · {cur['status'].upper()}")
        top = D.frame(cr, w, h, self.title if cls != "compact" else "PLAYING", right,
                      "phosphor" if cur and cur["status"] == "Playing" else "static")
        self.region(0, 0, w, 34, "Now playing, from your media players through MPRIS"
                    + (f" (read with {self.src.kind})" if self.src else "")
                    + (f". Showing {cur['name']}, {cur['status'].lower()}" if cur else "")
                    + (f"; {len(self.players)} players open" if len(self.players) > 1 else ""))
        if not self.src:
            self.empty(cr, w, h, top, "PLAYERCTL ISN'T INSTALLED",
                       "This panel reads media players through playerctl. Install it: sudo pacman -S playerctl",
                       tip="Now playing needs playerctl, which talks to media players over MPRIS. "
                           "Install it with sudo pacman -S playerctl.")
            return
        if not cur:
            self.empty(cr, w, h, top, "NOTHING IS PLAYING",
                       "Start music or a video in any player that speaks MPRIS: Spotify, Firefox, mpv, VLC and most others."
                       if cls != "compact" else "No media player is open.",
                       color="static",
                       tip="No media player is open, or none speaks MPRIS. Most do: Spotify, Firefox, Chromium, mpv, VLC.")
            return
        x0, x1 = 16, w - 16
        getattr(self, "_" + cls)(cr, cur, w, h, top, x0, x1)

    def _art(self, cur, size):
        return self.art.get(cur.get("art"), (size, size), on_ready=self._redraw)

    def _art_tip(self, cur):
        return (f"Cover of {cur['album'] or cur['title'] or 'this track'}" if cur.get("art")
                else f"{cur['name']} gives no cover for this track")

    def _words(self, cr, cur, x, y, width, big=15, lines=3, bottom=None):
        """Title, artist, album (those that fit above bottom); returns the y under them."""
        title = cur["title"] or "Untitled"
        tw, th = D.text(cr, x, y, title, big, "phosphor", "semibold", width=width, glow=cur["status"] == "Playing")
        self.region(x, y, width, th, f"Title: {title}")
        y += th + 3
        for val, col, size, what in ((cur["artist"], "soft", big - 3, "Artist"), (cur["album"], "static", big - 4, "Album"))[:lines - 1]:
            if val:
                if bottom is not None and y + size + 4 > bottom:
                    break
                _, hh = D.text(cr, x, y, val, size, col, "regular", width=width)
                self.region(x, y, width, hh, f"{what}: {val}")
                y += hh + 2
        return y

    def _transport(self, cr, cur, x, y, size=26):
        return draw_transport(self, cr, x, y, cur["status"] == "Playing", self.control, size, cur.get("caps"),
                              cur["name"])

    def _progress(self, cr, cur, x, y, w):
        draw_progress(self, cr, x, y, w, cur.get("position"), cur.get("length"),
                      (lambda s: self.control("seek", s)) if cur["caps"].get("seek") else None,
                      tip_what=f"“{cur['title']}”")

    def _visual(self, cr, x, y, w, h):
        bars = self.bars()
        mot = K.motion()
        if bars:
            draw_bars(cr, x, y, w, h, bars)
            self.region(x, y, w, h, "The visualizer: the sound's loudness by pitch, low on the left, drawn by cava")
            return
        cur = self.current
        if not Cava.available():
            why = "Install cava for a visualizer here (sudo pacman -S cava)."
        elif not self.conf.get("visualizer", True):
            why = "The visualizer is off in this panel's settings."
        elif mot != "full":
            why = "The visualizer rests while motion is reduced."
        elif not cur or cur["status"] != "Playing":
            why = "The visualizer runs while something plays."
        else:
            why = "Starting the visualizer…"
        D.rule(cr, x, y + h - 1, x + w, "dim", 0.4)
        D.text(cr, x, y + h - 18, why, 10, "static", "regular", width=w)
        self.region(x, y, w, h, why)

    def _players(self, cr, x, y, w, bottom):
        D.label(cr, x, y, f"PLAYERS · {len(self.players)}", "dim", size=10)
        y += 18
        for p in self.players:
            if y + 20 > bottom:
                break
            on = self.current and p["instance"] == self.current["instance"]
            if on:
                D.src(cr, "phosphor", 0.12)
                cr.rectangle(x - 4, y - 2, w + 8, 20)
                cr.fill()
            D.dot(cr, x + 4, y + 7, 3, "phosphor" if p["status"] == "Playing" else "static", glow=p["status"] == "Playing")
            D.text(cr, x + 14, y, p["name"], 11, "phosphor" if on else "soft", "semibold", width=w * 0.35)
            D.text(cr, x + 14 + w * 0.36, y + 1, p["title"] or p["status"].lower(), 10, "static", "regular",
                   width=w * 0.64 - 14)
            self.region(x - 4, y - 2, w + 8, 20, f"{p['name']}: {p['status'].lower()}"
                        + (f", “{p['title']}”" if p["title"] else "") + (". Shown here." if on else ". Click to show it here."),
                        None if on else (lambda i=p["instance"]: self.choose(i)))
            y += 22
        return y

    # ---- the size classes
    def _compact(self, cr, cur, w, h, top, x0, x1):
        size = h - top - 12
        ax = x0
        if size >= 48 and w >= 280:
            draw_art(self, cr, self._art(cur, size), x0, top, size, self._art_tip(cur))
            ax = x0 + size + 12
        bx = x1 - 28
        tw = bx - ax - 10
        self._words(cr, cur, ax, top + 2, tw, big=13, lines=2)
        self._playbutton(cr, cur, bx, top + 4, 28)
        frac = (cur["position"] / cur["length"]) if cur.get("position") is not None and cur.get("length") else 0
        D.bar(cr, ax, h - 14, x1 - ax, 3, frac)
        self.region(ax, h - 18, x1 - ax, 10, f"{mmss(cur.get('position'))} of {mmss(cur.get('length'))}")

    def _playbutton(self, cr, cur, x, y, s):
        playing = cur["status"] == "Playing"
        D.src(cr, "guard", 0.9)
        cr.rectangle(x, y, s, s)
        cr.fill()
        D.src(cr, "phosphor", 0.9)
        cr.set_line_width(1)
        cr.rectangle(x + 0.5, y + 0.5, s - 1, s - 1)
        cr.stroke()
        m, c = s * 0.3, (x + s / 2, y + s / 2)
        if playing:
            cr.rectangle(c[0] - m * 0.7, c[1] - m, m * 0.5, 2 * m)
            cr.rectangle(c[0] + m * 0.2, c[1] - m, m * 0.5, 2 * m)
        else:
            cr.move_to(c[0] - m * 0.6, c[1] - m)
            cr.line_to(c[0] + m, c[1])
            cr.line_to(c[0] - m * 0.6, c[1] + m)
            cr.close_path()
        cr.fill()
        self.region(x, y, s, s, ("Pause" if playing else "Play") + f" ({cur['name']})",
                    lambda: self.control("play-pause"))

    def _standard(self, cr, cur, w, h, top, x0, x1):
        size = min(h - top - 14, int((x1 - x0) * 0.36))
        draw_art(self, cr, self._art(cur, size), x0, top, size, self._art_tip(cur))
        tx = x0 + size + 16
        tw = x1 - tx
        by = h - 40
        y = self._words(cr, cur, tx, top, tw, bottom=by - 34)
        self._progress(cr, cur, tx, by - 26, tw)
        bw = self._transport(cr, cur, tx, by + 6, 22)
        vx = tx + bw + 14
        if x1 - vx > 40 and by + 6 > y:
            self._visual(cr, vx, by + 2, x1 - vx, 26)

    def _wide(self, cr, cur, w, h, top, x0, x1):
        size = h - top - 14
        draw_art(self, cr, self._art(cur, size), x0, top, size, self._art_tip(cur))
        tx = x0 + size + 16
        tw = min(420, (x1 - tx) * 0.5)
        self._words(cr, cur, tx, top, tw, bottom=h - 74)
        self._progress(cr, cur, tx, h - 66, tw)
        self._transport(cr, cur, tx, h - 38, 22)
        vx = tx + tw + 24
        self._visual(cr, vx, top + 4, x1 - vx, h - top - 22)

    def _tall(self, cr, cur, w, h, top, x0, x1):
        size = int(min(x1 - x0, (h - top) * 0.5))
        ax = x0 + (x1 - x0 - size) / 2
        draw_art(self, cr, self._art(cur, size), ax, top, size, self._art_tip(cur))
        y = top + size + 14
        y = self._words(cr, cur, x0, y, x1 - x0, big=16)
        self._progress(cr, cur, x0, y + 10, x1 - x0)
        y += 38
        bw = 3 * 30 + 16
        self._transport(cr, cur, x0 + (x1 - x0 - bw) / 2, y + 4, 26)
        y += 46
        vh = min(70, max(0, (h - y - 16) * 0.45))
        if vh >= 24:
            self._visual(cr, x0, y, x1 - x0, vh)
            y += vh + 16
        if h - y > 40 and self.players:
            self._players(cr, x0, y, x1 - x0, h - 10)

    def _large(self, cr, cur, w, h, top, x0, x1):
        size = int(min((x1 - x0) * 0.5, h - top - 120, max(220, h - top - 290)))
        draw_art(self, cr, self._art(cur, size), x0, top, size, self._art_tip(cur))
        tx = x0 + size + 24
        tw = x1 - tx
        y = self._words(cr, cur, tx, top, tw, big=20)
        D.label(cr, tx, y + 8, f"{cur['name']} · {cur['status']}", "dim", size=10)
        self.region(tx, y + 6, tw, 16, f"The player: {cur['instance']}, {cur['status'].lower()}")
        self._progress(cr, cur, tx, y + 40, tw)
        self._transport(cr, cur, tx, y + 72, 28)
        py = y + 124
        if top + size - py > 40:
            self._players(cr, tx, py, tw, top + size)
        vy = top + size + 18
        self._visual(cr, x0, vy, x1 - x0, min(260, h - vy - 26))


PANEL = NowPlayingPanel
LAYOUT = {"visible": False}
