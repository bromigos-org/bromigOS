"""MEDIA: what's on the den TV, now and next, and your media server's continue watching and
recently added (bromigOS's built-in plugin panel; docs/widgets.md, "Media").

The den TV (the live layer's channels on the den's screens; live/README.md, "The den TV")
says what's on through its control socket (`bromigos-live tv state`). When the den isn't
drawn, the panel works out its own channel's schedule from the same cache
(lib/bromigos_tv.py). Continue watching and recently added come from the first Jellyfin or
Plex source in homelab.toml (bromigos_homelab's `video` capability), every 5 minutes.

Its settings make one TV channel, the panel's channel, in ~/.config/bromigos/widgets/media.toml:
the source, what to play (a library, collection or playlist, chosen from the list the
servers last gave), a YouTube URL instead, the order, the den screen, and for YouTube a
folder to keep videos in. Every other channel is in the channel guide (Settings › Den TV),
which the form links to.

Sizes: compact (now and next), wide (and continue watching), large (and recently added,
with posters).
"""
import json
import os
import socket
import sys
import threading
import time

_HERE = os.path.dirname(os.path.realpath(__file__))
_REPO = os.path.dirname(os.path.dirname(_HERE))
for _p in (os.path.join(_REPO, "lib"), os.path.join(_REPO, "homelab", "lib"), "/usr/lib/bromigos/lib"):
    if os.path.isdir(_p) and _p not in sys.path:
        sys.path.append(_p)

import cairo  # noqa: E402

import draw as D  # noqa: E402
from panels import Panel  # noqa: E402

RUNTIME = os.environ.get("XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}")
SOCK = os.path.join(RUNTIME, "bromigos-live.sock")
CACHE = os.path.join(os.environ.get("XDG_CACHE_HOME") or os.path.expanduser("~/.cache"), "bromigos", "widgets", "media")
SCREENS = [["big", "The big monitor"], ["wave", "The scope"], ["emblem", "The small monitor"]]


def _tv():
    try:
        import bromigos_tv
        return bromigos_tv
    except ImportError:
        return None


def _homelab():
    try:
        import bromigos_homelab
        return bromigos_homelab
    except ImportError:
        return None


def _live_cfg():
    """The live layer's [tv] table, from the user's config.toml (the packaged one has no channels)."""
    path = os.environ.get("BROMIGOS_LIVE_CONFIG") or os.path.join(
        os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config"), "bromigos-live", "config.toml")
    try:
        import tomllib
        with open(path, "rb") as f:
            return {"tv": tomllib.load(f).get("tv") or {}}
    except (OSError, ValueError):
        return {}


def _settings_fields():
    """The form's fields. What to play is chosen from the list the servers last gave (the
    den TV's cache, lib/bromigos_tv.py's catalog): no network while the form opens."""
    TV = _tv()
    cat = TV.catalog(refresh=False) if TV else {"boxes": [], "servers": []}
    servers = [["", "The first media server"]] + [[s, s] for s in cat.get("servers") or []] + [["youtube", "YouTube"]]
    play = [["", "Nothing (show what the den TV is on)"]]
    for b in cat.get("boxes") or []:
        play.append([f"{b['kind']}:{b['title']}", f"{b['title']} ({b['kind']}, {b.get('server') or b.get('source')})"])
    return [
        {"key": "source", "label": "Source", "kind": "choice", "default": "", "choices": servers,
         "hint": "A Jellyfin or Plex source in homelab.toml, or YouTube"},
        {"key": "play", "label": "What to play", "kind": "choice", "default": "", "choices": play,
         "hint": "A library, collection or playlist on that server, as a TV channel"},
        {"key": "youtube", "label": "YouTube playlist or channel", "kind": "text", "default": "",
         "hint": "With Source set to YouTube: a playlist's or a channel's address"},
        {"key": "order", "label": "Order", "kind": "choice", "default": "",
         "choices": [["", "Its own (playlists in order, the rest shuffled)"], ["shuffle", "Shuffled, the same all day"],
                     ["in order", "In order"]]},
        {"key": "screen", "label": "Den screen", "kind": "choice", "default": "big", "choices": SCREENS + [["any", "Every screen"]],
         "hint": "Which of the den's screens carries the channel"},
        {"key": "channel_name", "label": "Channel name", "kind": "text", "default": "",
         "hint": "What the TV calls it; the library's or playlist's name by default"},
        {"key": "keep", "label": "Keep YouTube videos in", "kind": "text", "default": "",
         "hint": "A folder, such as ~/Videos/YouTube: what the TV plays is kept there and plays offline. Empty: off"},
        {"key": "keep_all", "label": "Keep every video, not just what plays", "kind": "bool", "default": False},
        {"key": "keep_max_gb", "label": "Keep at most (GB)", "kind": "number", "default": 50, "min": 1, "max": 10000,
         "hint": "Over this, the oldest kept videos go first"},
        {"key": "guide", "label": "Every channel: the channel guide", "kind": "link", "page": "den-tv",
         "hint": "All the den TV's channels on every screen: add, remove, reorder, pick shows (Settings › Den TV)"},
    ]


def _ask(cmd, timeout=1.5):
    """The live layer's answer over its control socket, or None."""
    try:
        with socket.socket(socket.AF_UNIX) as s:
            s.settimeout(timeout)
            s.connect(SOCK)
            s.sendall(cmd.encode())
            chunks = []
            while True:
                b = s.recv(65536)
                if not b:
                    break
                chunks.append(b)
        return b"".join(chunks).decode(errors="replace")
    except OSError:
        return None


def _demo():
    return "demo" in sys.modules or os.environ.get("BROMIGOS_WIDGETS_DEMO") == "1"


DEMO = {"now": {"name": "Saturday", "channel": 2, "of": 3, "screen": "big", "sound": False, "volume": 60, "live": True,
                "item": {"title": "The Long Watch", "series": "Relay Station", "season": 2, "episode": 5,
                         "kind": "episode", "duration": 1440}, "offset": 610,
                "next_item": {"title": "Static", "series": "Relay Station", "season": 2, "episode": 6, "kind": "episode",
                              "duration": 1380}},
        "resume": [{"title": "Night Shift", "series": "Harbour Lights", "season": 1, "episode": 3, "kind": "episode",
                    "duration": 2700, "position": 1800},
                   {"title": "Drift", "year": 1998, "kind": "movie", "duration": 6100, "position": 900}],
        "latest": [{"title": "Season 3", "series": "Relay Station", "kind": "season"},
                   {"title": "The Quiet Year", "year": 2024, "kind": "movie"},
                   {"title": "Tide Tables", "series": "Harbour Lights", "kind": "episode", "season": 2, "episode": 1}]}


class MediaPanel(Panel):
    name, title = "media", "MEDIA"
    description = "What's on the den TV, now and next, with continue watching and recently added"
    category, reads = "media", "the den TV, and your Jellyfin or Plex server"
    sizes = {"compact": ((300, 120), (520, 200), (380, 150)),
             "wide": ((640, 210), (1200, 340), (760, 250)),
             "large": ((640, 400), (1200, 900), (760, 560))}
    default_size = "compact"
    interval = 2.0
    settings = _settings_fields()

    @classmethod
    def available(cls):
        H = _homelab()
        if H is not None:
            try:
                if H.available("video"):
                    return True
            except Exception:                                  # noqa: BLE001  a broken homelab.toml
                pass
        TV = _tv()
        if TV is not None and (TV.channels(_live_cfg()) if TV else []):
            return True
        return (False, "no media source: a Jellyfin or Plex source in homelab.toml, or a den TV channel "
                       "(live/README.md, \"The den TV\")")

    def __init__(self, cfg=None, wake=None):
        super().__init__(cfg)
        self.wake = wake
        self.now = None                  # the den TV's media screen: {name, channel, of, screen, item, offset, …}
        self.resume, self.latest = [], []
        self.lib_error = None
        self.server = None
        self.posters = {}                # item id -> cairo surface (or None)
        self.shown = "compact"
        self._stop = threading.Event()
        self._fetched = 0.0
        if not _demo():
            threading.Thread(target=self._loop, daemon=True, name="media-panel").start()

    # ---- reading
    def tick(self):
        if _demo():
            self.now, self.resume, self.latest = DEMO["now"], DEMO["resume"], DEMO["latest"]
            return
        self.now = self._now()

    def _now(self):
        out = _ask("tv state --json")
        if out and out.startswith("{"):
            try:
                d = json.loads(out)
            except ValueError:
                d = {}
            want = self.setting("screen", "big")
            screens = d.get("screens") or {}
            media = [s for s, v in screens.items() if v.get("kind") != "own"]
            snd = d.get("sound_from")
            pick = want if want in media else (snd if snd in media else (media[0] if media else None))
            if pick:
                v = dict(screens[pick], screen=pick, live=True)
                if v.get("offset") is not None and v.get("start"):
                    v["offset"] = time.time() - v["start"]
                return v
        # the den isn't drawn (or nothing media is on): the panel's own channel, from the cache
        TV = _tv()
        if TV is None:
            return None
        chans = TV.channels(_live_cfg())
        ch = (chans[-1] if TV.panel_channel() else chans[0]) if chans else None     # the panel's own comes last
        if not ch:
            return None
        slot = TV.now_next(ch)
        if not slot:
            return {"name": ch["name"], "channel": None, "of": None, "item": None, "live": False}
        return {"name": ch["name"], "channel": None, "of": None, "item": slot.item, "next_item": slot.next,
                "offset": slot.offset, "start": slot.start, "end": slot.end, "live": False}

    def _loop(self):
        while not self._stop.is_set():
            if self.shown != "compact" and time.time() - self._fetched > 300:
                self._fetch_library()
            self._stop.wait(10)

    def _fetch_library(self):
        """Continue watching and recently added, with their posters (a thread; every 5 minutes)."""
        self._fetched = time.time()
        H = _homelab()
        if H is None:
            return
        try:
            src = self.setting("source", "") or None
            a = H.video_source(None if src == "youtube" else src)
            if a is None:
                self.lib_error = None
                return
            self.server = {"jellyfin": "Jellyfin", "plex": "Plex"}.get(a.type, a.type)
            self.resume = a.video_resume(6)
            self.latest = a.video_latest(8) if self.shown == "large" else self.latest
            self.lib_error = None
            if self.shown == "large":
                for it in (self.resume + self.latest)[:12]:
                    self._poster(a, it)
            TV = _tv()
            if TV:
                TV.catalog(max_age=900)                        # the settings form's choices
        except Exception as e:                                  # noqa: BLE001
            self.lib_error = f"{type(e).__name__}: {str(e)[:120]}"
        if self.wake:
            self.wake()

    def _poster(self, a, it):
        iid = str(it.get("id"))
        if iid in self.posters:
            return
        path = os.path.join(CACHE, f"{a.name}-{iid}.png")
        if not os.path.exists(path):
            url, headers = a.video_poster(it)
            if not url:
                self.posters[iid] = None
                return
            try:
                import urllib.request
                req = urllib.request.Request(url, headers=headers)
                with urllib.request.urlopen(req, timeout=10, context=a._ctx()) as r:
                    data = r.read(4 << 20)
                import gi
                gi.require_version("GdkPixbuf", "2.0")
                from gi.repository import GdkPixbuf
                loader = GdkPixbuf.PixbufLoader()
                loader.write(data)
                loader.close()
                pb = loader.get_pixbuf().scale_simple(120, 180, GdkPixbuf.InterpType.BILINEAR)
                os.makedirs(CACHE, exist_ok=True)
                pb.savev(path, "png", [], [])
            except Exception:                                   # noqa: BLE001
                self.posters[iid] = None
                return
        try:
            self.posters[iid] = cairo.ImageSurface.create_from_png(path)
        except Exception:                                       # noqa: BLE001
            self.posters[iid] = None

    # ---- drawing
    def draw(self, cr, w, h):
        cls = self.size_class(w, h)
        if cls != self.shown:
            self.shown = cls
            self._fetched = 0.0
        n = self.now
        right = None
        if n and n.get("channel"):
            right = f"CH {n['channel']}/{n['of']}"
        top = D.frame(cr, w, h, self.title, right, "phosphor")
        self.region(0, 0, w, 34, "MEDIA: what the den TV shows (scroll over the TV to change channel), and your "
                                 "media server's continue watching and recently added")
        x0, x1 = 16, w - 16
        y = self._draw_now(cr, x0, x1, top, n, cls)
        if cls == "compact":
            return
        lw = (x1 - x0)
        y += 6
        D.rule(cr, x0, y, x1)
        y += 10
        if cls == "wide":
            self._row_list(cr, x0, y, lw, h - y - 10, "CONTINUE WATCHING", self.resume, posters=False)
            return
        half = (h - y - 10) / 2
        self._row_list(cr, x0, y, lw, half - 8, "CONTINUE WATCHING", self.resume, posters=True)
        self._row_list(cr, x0, y + half, lw, half, "RECENTLY ADDED", self.latest, posters=True)

    def _draw_now(self, cr, x0, x1, y, n, cls):
        TV = _tv()
        label = TV.label if TV else (lambda it: (it or {}).get("title", ""))
        if not n:
            D.text(cr, x0, y, "Nothing on the den TV.", 13, "soft")
            D.text(cr, x0, y + 20, "Scroll over a den screen to change channel, or give this panel a channel in",
                   10, "dim", width=x1 - x0)
            D.text(cr, x0, y + 34, "its Settings (a library, a playlist or YouTube).", 10, "dim", width=x1 - x0)
            return y + 50
        it = n.get("item")
        D.label(cr, x0, y, ("ON " + {"big": "THE BIG MONITOR", "wave": "THE SCOPE", "emblem": "THE SMALL MONITOR"}
                            .get(n.get("screen"), "THE TV") + " · " if n.get("screen") else "") + n.get("name", ""),
                "dim", 10)
        y += 18
        if not it:
            D.text(cr, x0, y, "Tuning in… (the channel's list is on its way)", 12, "static")
            return y + 22
        title = label(it)
        D.text(cr, x0, y, "▶ " + title, 14, "phosphor", "semibold", width=x1 - x0, glow=True)
        dur, off = it.get("duration"), n.get("offset")
        self.region(x0, y - 2, x1 - x0, 22, f"Now on the den TV: {title}. Click: full screen with sound "
                                           "(bromigos-live tv open)", self._open)
        y += 22
        if dur and off is not None:
            D.bar(cr, x0, y, x1 - x0, 4, max(0.0, min(1.0, off / dur)))
            left = max(0, dur - off)
            D.text(cr, x1, y + 8, f"{int(left // 60)} min left", 10, "dim", align="right")
            y += 8
        nxt = n.get("next_item")
        if nxt:
            D.text(cr, x0, y, "NEXT  " + label(nxt), 10, "static", width=(x1 - x0) * 0.7)
            self.region(x0, y - 2, (x1 - x0) * 0.7, 16, f"Next on {n.get('name')}: {label(nxt)}")
        y += 18
        if n.get("live") and cls != "compact":
            bx = x0
            bx += self._button(cr, bx, y, "◀ CH", "The den TV's previous channel", lambda: self._tv("prev")) + 6
            bx += self._button(cr, bx, y, "CH ▶", "The den TV's next channel", lambda: self._tv("next")) + 6
            snd = "SOUND ON" if n.get("sound") else "SOUND OFF"
            tip = (f"The den TV's sound, now {snd.lower()} at {n.get('volume')}%: click to turn it "
                   + ("off" if n.get("sound") else "on"))
            bx += self._button(cr, bx, y, snd, tip, lambda: self._tv("sound toggle")) + 6
            bx += self._button(cr, bx, y, "−", "Volume down 5%", lambda: self._tv("volume down")) + 4
            bx += self._button(cr, bx, y, "+", "Volume up 5%", lambda: self._tv("volume up")) + 6
            self._button(cr, bx, y, "FULL SCREEN", "Open it in mpv, full screen with sound, at the same moment",
                         self._open)
            y += 24
        return y

    def _row_list(self, cr, x, y, w, h, title, items, posters):
        D.label(cr, x, y, title + (f" · {self.server}" if self.server else ""), "dim", 10)
        y += 18
        TV = _tv()
        label = TV.label if TV else (lambda it: (it or {}).get("title", ""))
        if self.lib_error:
            why = self.lib_error
            if "no API key" in why:
                why = ("Jellyfin needs an API key: make one in Dashboard › API Keys, keep it in a file "
                       "and name it as auth_ref in homelab.toml (docs/homelab.md, Video libraries).")
            elif "no token" in why:
                why = ("Plex needs your token: keep it in a file and name it as auth_ref in homelab.toml "
                       "(docs/homelab.md, Video libraries).")
            D.text(cr, x, y, why, 10, "amber", width=w, wrap=True)
            return
        if not items:
            D.text(cr, x, y, "Nothing yet." if self.server or _demo() else
                   "No media server: add a Jellyfin or Plex source to homelab.toml.", 10, "static", width=w)
            return
        if posters:
            pw, ph = 80, 120
            if h < ph + 20:
                ph = max(40, h - 22)
                pw = ph * 2 / 3
            cx = x
            for it in items:
                if cx + pw > x + w:
                    break
                surf = self.posters.get(str(it.get("id")))
                if surf is not None:
                    cr.save()
                    cr.translate(cx, y)
                    cr.scale(pw / surf.get_width(), ph / surf.get_height())
                    cr.set_source_surface(surf, 0, 0)
                    cr.paint()
                    cr.restore()
                else:
                    D.src(cr, "guard", 0.8)
                    cr.rectangle(cx, y, pw, ph)
                    cr.fill()
                    D.text(cr, cx + 4, y + 4, label(it), 9, "soft", width=pw - 8, wrap=True)
                if it.get("position") and it.get("duration"):
                    D.bar(cr, cx, y + ph - 4, pw, 4, it["position"] / it["duration"])
                self.region(cx, y, pw, ph, f"{label(it)}. Click: open it in {self.server or 'the server'}",
                            (lambda i=it: self._web(i)))
                cx += pw + 10
            return
        end = y + h
        for it in items:
            if y + 18 > end:
                break
            D.text(cr, x, y, label(it), 11, "soft", width=w * 0.72)
            if it.get("position") and it.get("duration"):
                D.bar(cr, x + w * 0.75, y + 5, w * 0.25, 4, it["position"] / it["duration"])
            self.region(x, y - 2, w, 18, f"{label(it)}" + (f", {int(it['position'] // 60)} min in" if it.get("position")
                                                           else "") + f". Click: open it in {self.server or 'the server'}",
                        (lambda i=it: self._web(i)))
            y += 20

    def _button(self, cr, x, y, label, tip, action):
        lay = D.layout(cr, label, 10, "semibold", 0.06)
        bw = max(28, lay.get_pixel_size()[0] + 12)
        D.src(cr, "guard", 0.9)
        cr.rectangle(x, y, bw, 18)
        cr.fill()
        cr.set_line_width(1)
        D.src(cr, "dim", 0.9)
        cr.rectangle(x + 0.5, y + 0.5, bw - 1, 17)
        cr.stroke()
        D.text(cr, x + bw / 2, y + 2, label, 10, "phosphor", "semibold", spacing=0.06, align="center")
        self.region(x, y, bw, 18, tip, action)
        return bw

    # ---- actions
    def _tv(self, verb):
        _ask("tv " + verb)
        self.now = self._now()
        if self.wake:
            self.wake()

    def _open(self):
        out = _ask("tv open")
        if out is None:
            import subprocess
            subprocess.Popen(["bromigos-live", "tv", "open"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                             start_new_session=True)

    def _web(self, it):
        H = _homelab()
        if H is None:
            return
        a = H.video_source(it.get("server"))
        if a is None:
            return
        import subprocess
        subprocess.Popen(["xdg-open", a.video_web(it)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                         start_new_session=True)


PANEL = MediaPanel
LAYOUT = {"visible": False}
