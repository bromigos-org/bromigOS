"""MEDIA: a remote for the den TV, and your media server's continue watching and recently
added (bromigOS's built-in plugin panel; docs/widgets.md, "Media").

The den TV (the live layer's channels on the den's three screens; live/README.md, "The den
TV") says what's on through its control socket (`bromigos-live tv state`). The panel shows
all three screens at once, which hovering one screen can't: each one's channel, what's on
and next, how far in, its poster, and where the sound comes from. Click a screen's row to
choose it; the buttons change its channel and sound, open it full screen, or open the
channel guide. When the den isn't drawn, the panel works out its own channel's schedule
from the same cache (lib/bromigos_tv.py). Continue watching and recently added come from
the first Jellyfin or Plex source in homelab.toml (bromigos_homelab's `video` capability),
every 5 minutes.

Its settings make one TV channel, the panel's channel, in ~/.config/bromigos/widgets/media.toml:
the source, what to play (a library, collection or playlist, chosen from the list the
servers last gave), a YouTube URL instead, the order, the den screen, and for YouTube a
folder to keep videos in. Every other channel is in the channel guide (Den TV),
which the form links to.

Sizes: compact (the three screens, a line each), wide (with posters and what's next), large
(and continue watching and recently added).
"""
import json
import math
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
SHORT = {"big": "BIG", "wave": "SCOPE", "emblem": "SMALL"}


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
        {"key": "guide", "label": "Every channel: the channel guide", "kind": "link", "command": "bromigos-tv-guide",
         "hint": "All the den TV's channels on every screen: add, remove, reorder, pick shows (Den TV)"},
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


DEMO = {"now": {"name": "Saturday", "channel": 2, "of": 3, "screen": "big", "sound": True, "volume": 60, "live": True,
                "item": {"title": "The Long Watch", "series": "Relay Station", "season": 2, "episode": 5,
                         "kind": "episode", "duration": 1440}, "offset": 610,
                "next_item": {"title": "Static", "series": "Relay Station", "season": 2, "episode": 6, "kind": "episode",
                              "duration": 1380}},
        "screens": [
            {"screen": "big", "name": "Saturday", "channel": 2, "of": 4, "kind": "server", "sound": True, "volume": 60,
             "live": True,
             "item": {"title": "The Long Watch", "series": "Relay Station", "season": 2, "episode": 5,
                      "kind": "episode", "duration": 1440}, "offset": 610,
             "next_item": {"title": "Static", "series": "Relay Station", "season": 2, "episode": 6,
                           "kind": "episode", "duration": 1380}},
            {"screen": "wave", "name": "Lo-fi", "channel": 3, "of": 4, "kind": "youtube", "sound": False, "live": True,
             "volume": 60, "item": {"title": "Rain on the relay", "kind": "video", "duration": 3600}, "offset": 1200,
             "next_item": {"title": "Night drive", "kind": "video", "duration": 2400}},
            {"screen": "emblem", "name": "BURN-IN", "channel": 1, "of": 4, "kind": "own", "sound": False, "live": True,
             "volume": 60}],
        "resume": [{"title": "Night Shift", "series": "Harbour Lights", "season": 1, "episode": 3, "kind": "episode",
                    "duration": 2700, "position": 1800},
                   {"title": "Drift", "year": 1998, "kind": "movie", "duration": 6100, "position": 900}],
        "latest": [{"title": "Season 3", "series": "Relay Station", "kind": "season"},
                   {"title": "The Quiet Year", "year": 2024, "kind": "movie"},
                   {"title": "Tide Tables", "series": "Harbour Lights", "kind": "episode", "season": 2, "episode": 1}]}


class MediaPanel(Panel):
    name, title = "media", "MEDIA"
    description = "A remote for the den TV's three screens, with continue watching and recently added"
    category, reads = "media", "the den TV, and your Jellyfin or Plex server"
    sizes = {"compact": ((300, 140), (520, 200), (380, 150)),
             "wide": ((640, 210), (1200, 340), (760, 250)),
             "large": ((640, 400), (1200, 900), (760, 560))}
    default_size = "compact"
    interval = 2.0
    settings = _settings_fields()

    @classmethod
    def available(cls):
        if _demo():                               # pictures: its made-up den TV and library
            return True
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
        self.now = None                  # the selected screen's row (below)
        self.rows = []                   # each den screen: {screen, name, channel, of, kind, item, offset, sound, …}
        self.sel = None                  # the screen the buttons act on (a click on its row)
        self.resume, self.latest = [], []
        self.lib_error = None
        self.server = None
        self.posters = {}                # item id -> cairo surface (or None)
        self._knob_rect = None
        self._row_hits = []
        self._dial_drag = None
        self.shown = "compact"
        self._stop = threading.Event()
        self._fetched = 0.0
        if not _demo():
            threading.Thread(target=self._loop, daemon=True, name="media-panel").start()

    # ---- reading
    def tick(self):
        if _demo():
            self.rows, self.resume, self.latest = DEMO["screens"], DEMO["resume"], DEMO["latest"]
            self.sel = self.sel or "big"
            self.now = next(r for r in self.rows if r["screen"] == self.sel)
            return
        self.rows = self._screens()
        live = [r for r in self.rows if r.get("live")]
        if live:
            if self.sel not in [r["screen"] for r in live]:
                snd = next((r["screen"] for r in live if r.get("sound")), None)
                media = [r["screen"] for r in live if r.get("kind") != "own"]
                self.sel = snd or (media[0] if media else "big")
            self.now = next(r for r in live if r["screen"] == self.sel)
        else:
            self.now = self.rows[0] if self.rows else None

    def _screens(self):
        """Every den screen's row from the live layer, or the panel's own channel when the den
        isn't drawn."""
        out = _ask("tv state --json")
        if out and out.startswith("{"):
            try:
                d = json.loads(out)
            except ValueError:
                d = {}
            rows = []
            for scr, _t in SCREENS:
                v = (d.get("screens") or {}).get(scr)
                if not v:
                    continue
                r = dict(v, screen=scr, live=True)
                if r.get("offset") is not None and r.get("start"):
                    r["offset"] = time.time() - r["start"]
                rows.append(r)
            if rows:
                return rows
        n = self._now()
        return [n] if n else []

    def _now(self):
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
            if self.shown != "compact":
                self._now_posters()
            self._stop.wait(10)

    def _now_posters(self):
        """The posters of what each screen shows (a thread): the server's, or YouTube's thumbnail."""
        H = _homelab()
        for r in list(self.rows):
            it = r.get("item") or {}
            if not it.get("id") or str(it.get("id")) in self.posters:
                continue
            a = None
            if it.get("server") not in (None, "youtube", "files") and H is not None:
                try:
                    a = H.video_source(it.get("server"))
                except Exception:                              # noqa: BLE001
                    a = None
            self._poster(a, it)
        if self.wake:
            self.wake()

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
        """A poster as a cairo surface, kept as a PNG in CACHE: through the server's adapter, or
        (a=None) the item's own thumbnail address (YouTube's)."""
        iid = str(it.get("id"))
        if iid in self.posters:
            return
        path = os.path.join(CACHE, f"{a.name if a else 'web'}-{iid}.png")
        if not os.path.exists(path):
            url, headers = a.video_poster(it) if a else (it.get("thumbnail") or it.get("poster"), {})
            if not url or not str(url).startswith(("http://", "https://")):
                self.posters[iid] = None
                return
            try:
                import ssl
                import urllib.request
                req = urllib.request.Request(url, headers=headers)
                with urllib.request.urlopen(req, timeout=10, context=a._ctx() if a else
                                            ssl.create_default_context()) as r:
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
        snd = next((r for r in self.rows if r.get("sound") and r.get("kind") != "own"), None)
        right = f"SOUND · {SHORT.get(snd['screen'], '')}" if snd else None
        top = D.frame(cr, w, h, self.title, right, "phosphor")
        self.region(0, 0, w, 34, "MEDIA: a remote for the den TV, all three screens at once (click a screen's row "
                                 "to choose it), and your media server's continue watching and recently added")
        self._row_hits = []
        self._knob_rect = None
        x0, x1 = 16, w - 16
        y = self._draw_remote(cr, x0, x1, top, n, cls)
        if cls != "large":
            return
        lw = (x1 - x0)
        y += 6
        D.rule(cr, x0, y, x1)
        y += 10
        half = (h - y - 10) / 2
        self._row_list(cr, x0, y, lw, half - 8, "CONTINUE WATCHING", self.resume, posters=True)
        self._row_list(cr, x0, y + half, lw, half, "RECENTLY ADDED", self.latest, posters=True)

    def _draw_remote(self, cr, x0, x1, y, n, cls):
        """A row for each den screen (the chosen one marked), then the buttons for it."""
        TV = _tv()
        label = TV.label if TV else (lambda it: (it or {}).get("title", ""))
        if not self.rows:
            D.text(cr, x0, y, "Nothing on the den TV.", 13, "soft")
            D.text(cr, x0, y + 20, "Add channels in the channel guide (Den TV, SUPER+ALT+G), or give "
                                   "this panel one in its Settings.", 10, "dim", width=x1 - x0, wrap=True)
            self.region(x0, y, x1 - x0, 44, "Opens the channel guide (bromigos-live tv guide)", self._guide)
            return y + 50
        live = any(r.get("live") for r in self.rows)
        tall = cls != "compact"
        end_x = x1
        x1 -= 92 if tall else 64
        dial_y = y + (68 if tall else 33)
        rh = 46 if tall else 22
        for r in self.rows:
            scr = r.get("screen")
            chosen = live and scr == self.sel
            it = r.get("item")
            px = x0
            if chosen:
                D.src(cr, "phosphor", 0.10)
                cr.rectangle(x0 - 6, y - 3, x1 - x0 + 12, rh)
                cr.fill()
                D.src(cr, "phosphor", 0.9)
                cr.rectangle(x0 - 6, y - 3, 2, rh)
                cr.fill()
            if tall:
                pw, ph = 30, 44
                surf = self.posters.get(str((it or {}).get("id"))) if it else None
                if surf is not None:
                    cr.save()
                    cr.translate(px, y)
                    cr.scale(pw / surf.get_width(), ph / surf.get_height())
                    cr.set_source_surface(surf, 0, 0)
                    cr.paint()
                    cr.restore()
                else:
                    D.src(cr, "guard", 0.8)
                    cr.rectangle(px, y, pw, ph)
                    cr.fill()
                px += pw + 10
            sound = r.get("sound") and r.get("kind") != "own"
            if tall:
                head = (f"{SHORT.get(scr, '')} · CH {r['channel']} " if live and scr else "") + (r.get("name") or "")
                D.text(cr, px, y, head, 10, "phosphor" if chosen else "dim", width=x1 - px - 56)

            else:
                D.label(cr, px, y, f"{SHORT.get(scr, '')} {r.get('channel') or ''}" if live else "TV",
                        "phosphor" if chosen else "dim", 10)

            row_end = x1
            x1 -= 54
            if r.get("kind") == "own":
                now = "Its own picture"
            elif it:
                now = "▶ " + label(it)
            else:
                now = "Tuning in…"
            if tall:
                D.text(cr, px, y + 12, now, 11, "soft" if it else "static", "semibold", width=x1 - px)
                dur, off = (it or {}).get("duration"), r.get("offset")
                if dur and off is not None:
                    D.bar(cr, px, y + 28, x1 - px, 3, max(0.0, min(1.0, off / dur)))
                nxt = r.get("next_item")
                if nxt:
                    D.text(cr, px, y + 32, "NEXT  " + label(nxt), 9, "static", width=x1 - px)
            else:
                line = (f"{r.get('name')}: " + now.lstrip("▶ ")) if r.get("kind") != "own" else now
                D.text(cr, px + 76, y - 1, line, 11, "soft" if it else "static", width=x1 - px - 76)
                dur, off = (it or {}).get("duration"), r.get("offset")
                if dur and off is not None:
                    D.bar(cr, px + 76, y + 15, x1 - px - 76, 2, max(0.0, min(1.0, off / dur)))
            tip = (f"{dict(SCREENS).get(scr, 'The den TV')}: {r.get('name')}"
                   + (f", {label(it)}" if it else "") + (f"; next {label(r['next_item'])}" if r.get("next_item") else "")
                   + (". Click: choose it for the buttons below" if live else ""))
            x1 = row_end
            self._row_hits.append((scr, (x0 - 6, y - 3, x1 - x0 + 12, rh)))
            self.region(x0 - 6, y - 3, x1 - x0 + 12, rh, tip + ". Wheel: volume", (lambda s=scr: self._choose(s)) if live else None)
            if live:
                self._speaker(cr, x1 - 49, y - 1, sound)
                D.text(cr, x1, y, f"{r.get('volume', 60)}%", 9, "phosphor" if sound else "dim", align="right")
                self.region(x1 - 52, y - 3, 54, 19, "Sound from " + SHORT.get(scr, "TV") +
                            (": click to mute" if sound else ": click to move sound here"),
                            lambda scr=scr: self._tv_to("sound toggle", scr))
            y += rh + (2 if tall else 0)
        if not live:
            return y
        self._draw_dial(cr, end_x - (43 if tall else 28), dial_y, 34 if tall else 21)
        x1 = end_x
        y += 4
        s = self.sel
        bx = x0
        name = dict(SCREENS).get(s, "the screen").lower()
        bx += self._button(cr, bx, y, "◀ CH", f"The previous channel on {name}", lambda: self._tv("prev")) + 6
        bx += self._button(cr, bx, y, "CH ▶", f"The next channel on {name}", lambda: self._tv("next")) + 6
        if n:
            bx += self._button(cr, bx, y, "FULL", f"{name.capitalize()}'s channel in mpv, full screen with sound, at "
                                                  "the same moment", self._open) + 6
        self._button(cr, bx, y, "GUIDE", "Every channel: the channel guide (Den TV)", self._guide)
        return y + 24

    @staticmethod
    def _speaker(cr, x, y, on):
        D.src(cr, "phosphor" if on else "dim")
        cr.move_to(x, y + 4); cr.line_to(x + 4, y + 4); cr.line_to(x + 9, y)
        cr.line_to(x + 9, y + 12); cr.line_to(x + 4, y + 8); cr.line_to(x, y + 8)
        cr.close_path(); cr.fill(); cr.set_line_width(1)
        if on:
            for r in (4, 7): cr.arc(x + 9, y + 6, r, -.8, .8); cr.stroke()
        else:
            cr.move_to(x + 12, y + 3); cr.line_to(x + 17, y + 10)
            cr.move_to(x + 17, y + 3); cr.line_to(x + 12, y + 10); cr.stroke()

    def _dial_screen(self):
        return next((r for r in self.rows if r.get("sound") and r.get("kind") != "own"), self.now or {})

    def _draw_dial(self, cr, cx, cy, radius):
        row = self._dial_screen()
        value = row.get("volume", 60)
        self._knob_rect = (cx - radius, cy - radius, radius * 2, radius * 2)
        D.src(cr, "guard"); cr.arc(cx, cy, radius - 3, 0, math.tau); cr.fill()
        start, sweep = math.pi * .75, math.pi * 1.5
        cr.set_line_width(1)
        for i in range(21):
            a = start + sweep * i / 20
            D.src(cr, "phosphor" if i <= round(value / 5) else "dim", .9)
            cr.move_to(cx + math.cos(a) * (radius - 3), cy + math.sin(a) * (radius - 3))
            cr.line_to(cx + math.cos(a) * radius, cy + math.sin(a) * radius); cr.stroke()
        D.src(cr, "phosphor", .9); cr.set_line_width(2)
        cr.arc(cx, cy, radius - 6, start, start + sweep * value / 100); cr.stroke()
        D.text(cr, cx, cy - 5, str(value) + "%", 10 if radius < 25 else 14,
               "phosphor" if row.get("sound") else "dim", "semibold", align="center")
        D.text(cr, cx, cy + radius - 1, SHORT.get(row.get("screen"), "VOLUME"), 9, "dim", align="center")
        self.region(*self._knob_rect, "Volume for " + SHORT.get(row.get("screen"), "TV") +
                    ": wheel or drag to turn; click to mute or unmute", lambda: None)

    @staticmethod
    def _inside(x, y, rect):
        return rect and rect[0] <= x <= rect[0] + rect[2] and rect[1] <= y <= rect[1] + rect[3]

    def scroll_at(self, x, y, dy):
        row = self._dial_screen() if self._inside(x, y, self._knob_rect) else             next((r for r in self.rows if any(s == r.get("screen") and self._inside(x, y, rect)
                                             for s, rect in self._row_hits)), None)
        if not row or not row.get("live"): return False
        self._tv_to("volume " + ("up" if dy < 0 else "down"), row.get("screen")); return True

    def pointer_press(self, x, y, button=1):
        if button != 1 or not self._inside(x, y, self._knob_rect): return False
        row = self._dial_screen()
        if not row.get("live"): return False
        rx, ry, rw, rh = self._knob_rect
        self._dial_drag = dict(x=x, y=y, cx=rx + rw/2, cy=ry + rh/2, value=row.get("volume",60),
                               screen=row.get("screen"), moved=False)
        return True

    def pointer_motion(self, x, y):
        d = self._dial_drag
        if not d: return False
        dx, dy = x - d["x"], y - d["y"]
        if abs(dx) + abs(dy) < 4: return False
        d["moved"] = True
        if abs(dx) > abs(dy) * .7:
            a0 = math.atan2(d["y"] - d["cy"], d["x"] - d["cx"])
            a1 = math.atan2(y - d["cy"], x - d["cx"])
            delta = (a1 - a0 + math.pi) % math.tau - math.pi
            value = d["value"] + delta * 100 / (math.pi * 1.5)
        else: value = d["value"] - dy * 1.5
        value = max(0,min(100,round(value)))
        row = next((r for r in self.rows if r.get("screen") == d["screen"]), {})
        if row.get("volume") != value: self._tv_to("volume " + str(value), d["screen"])
        return True

    def pointer_release(self):
        d, self._dial_drag = self._dial_drag, None
        if not d: return False
        if not d["moved"]: self._tv_to("sound toggle", d["screen"])
        return True

    def _tv_to(self, verb, screen):
        _ask("tv " + verb + (f" --screen {screen}" if screen else ""))
        self.tick()
        if self.wake: self.wake()

    def _choose(self, screen):
        self.sel = screen
        self.now = next((r for r in self.rows if r.get("screen") == screen), self.now)
        if self.wake:
            self.wake()

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
        if posters and h - 18 < 60:               # too short for posters: a line each
            posters = False
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
                    cr.save()                         # its title on the blank poster, inside it
                    cr.rectangle(cx, y, pw, ph)
                    cr.clip()
                    D.text(cr, cx + 4, y + 4, label(it), 9, "soft", width=pw - 8, wrap=True)
                    cr.restore()
                if it.get("position") and it.get("duration"):
                    D.bar(cr, cx, y + ph - 4, pw, 4, it["position"] / it["duration"])
                self.region(cx, y, pw, ph, f"{label(it)}. Click: open it in {self.server or 'the server'}",
                            (lambda i=it: self._web(i)))
                cx += pw + 10
            return
        end = y + h - 18
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
        _ask("tv " + verb + (f" --screen {self.sel}" if self.sel else ""))
        self.tick()
        if self.wake:
            self.wake()

    def _guide(self):
        import subprocess
        subprocess.Popen(["bromigos-tv-guide"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                         start_new_session=True)

    def _open(self):
        out = _ask("tv open" + (f" --screen {self.sel}" if self.sel else ""))
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
