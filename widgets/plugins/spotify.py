"""SPOTIFY: what your Spotify account is playing, on any of your devices, with the queue
and what you played recently. Spotify's Web API, signed in through
lib/bromigos_account.py ("spotify": the authorization code with PKCE on
http://127.0.0.1:8898/callback; the refresh token stays in the login keyring).

It works with NOW PLAYING (nowplaying.py): when the Spotify app runs on this machine, its
MPRIS player takes the play, pause and skip clicks (instant, and free accounts too),
while the Web API adds the device, the queue and the history. Without the app, the Web
API carries the clicks, which Spotify allows for Premium accounts only.

It shows one account. With several Spotify accounts, it's the first one its `account`
setting lists, or else the first one signed in.
"""
import os
import sys
import threading
import time
import urllib.error

sys.path.append(os.path.dirname(os.path.realpath(__file__)))   # after the standard library
import _kit as K  # noqa: E402
import nowplaying as NP  # noqa: E402  the shared art, transport and MPRIS reading

import draw as D  # noqa: E402

API = "https://api.spotify.com/v1"


# ------------------------------------------------------------------ parsing the Web API
def _artists(item):
    return ", ".join(a.get("name", "") for a in (item or {}).get("artists") or [] if a.get("name"))


def _image(item, want=300):
    """The album image nearest `want` px wide (images come largest first)."""
    imgs = ((item or {}).get("album") or {}).get("images") or (item or {}).get("images") or []
    if not imgs:
        return None
    return min(imgs, key=lambda i: abs((i.get("width") or want) - want)).get("url")


def track(item):
    """A track or an episode as the panel draws it."""
    if not item:
        return None
    show = item.get("show") or {}
    return {"id": item.get("id"), "title": item.get("name") or "", "artist": _artists(item) or show.get("name") or "",
            "album": (item.get("album") or {}).get("name") or show.get("name") or "",
            "length": (item.get("duration_ms") or 0) / 1000 or None, "art": _image(item),
            "url": (item.get("external_urls") or {}).get("spotify"), "kind": item.get("type") or "track"}


def parse_player(d):
    """GET /me/player: {} when nothing plays anywhere (Spotify answers 204)."""
    if not d:
        return {"active": False}
    dev = d.get("device") or {}
    return {"active": True, "playing": bool(d.get("is_playing")), "position": (d.get("progress_ms") or 0) / 1000,
            "track": track(d.get("item")), "device": dev.get("name"), "device_type": dev.get("type"),
            "volume": dev.get("volume_percent"), "shuffle": d.get("shuffle_state"), "repeat": d.get("repeat_state"),
            "context": (d.get("context") or {}).get("type"), "at": time.time()}


def parse_queue(d):
    return [t for t in (track(i) for i in (d or {}).get("queue") or []) if t]


def parse_recent(d):
    out = []
    for it in (d or {}).get("items") or []:
        t = track(it.get("track"))
        if t:
            t["played_at"] = K.iso_time(it.get("played_at"))
            out.append(t)
    return out


def control_error(e):
    """Words for a failed Web API click."""
    if isinstance(e, urllib.error.HTTPError):
        if e.code == 403:
            return "Spotify allows control through its Web API with Premium only; the Spotify app on this machine works without it"
        if e.code == 404:
            return "no active Spotify device: start playing on one first"
        if e.code == 401:
            return "Spotify's sign-in has run out; sign in again"
        return f"Spotify said HTTP {e.code}"
    return K._words(e)


# ------------------------------------------------------------------ demo readings
DEMO_PLAYER = {"active": True, "playing": True, "position": 132.0, "device": "drift (this computer)",
               "device_type": "Computer", "volume": 64, "shuffle": True, "repeat": "off", "context": "playlist",
               "track": {"id": "d1", "title": "Tidewater Static", "artist": "Breakwater Choir", "album": "Low Signal Hours",
                         "length": 213.0, "art": "demo:art", "url": None, "kind": "track"}}
DEMO_QUEUE = [{"title": t, "artist": a, "album": "", "length": l, "art": None, "kind": "track"} for t, a, l in (
    ("Relay Mast at Dusk", "Breakwater Choir", 241), ("Lamplighter's Round", "The Relay Keepers", 198),
    ("Greywater Drift", "Harbor Point Radio", 305), ("Cold Fusion Lullaby", "Tidewell", 187),
    ("Signal Fires", "Mast & Lantern", 262), ("Northern Approach", "The Relay Keepers", 224),
    ("Fog Horn Etude", "Greywater Archive", 158), ("Ember Line", "Cinder Quartet", 276))]
DEMO_RECENT = [{"title": t, "artist": a, "album": "", "length": None, "art": None, "kind": "track",
                "played_at": time.time() - ago} for t, a, ago in (
    ("Harbour Lights at Low Tide", "The Relay Keepers", 420), ("Beacon Kit", "Drift Atlas", 900),
    ("Low Water Mark", "Breakwater Choir", 1500), ("Night Ferry", "Harbor Point Radio", 2400),
    ("Salt and Copper", "Tidewell", 3900), ("The Long Watch", "Mast & Lantern", 5200),
    ("Glass Floats", "Greywater Archive", 7100))]


# ------------------------------------------------------------------ the panel
class SpotifyPanel(K.KitPanel):
    name, title = "spotify", "SPOTIFY"
    description = "Your Spotify account: what plays on any device, the queue and recent tracks (Now playing covers any player)"
    category, reads = "media", "Spotify's Web API, signed in with your account"
    width, height = 460, 200
    interval = 1.0
    settings = [
        {"key": "account", "label": "Spotify account", "kind": "secret-signin", "provider": "spotify",
         "hint": "Sign in once; the token stays in your keyring"},
        {"key": "show_queue", "label": "Show the queue when tall or large", "kind": "bool", "default": True,
         "hint": "Up next and recently played, read every minute while the panel is tall or large"},
    ]
    sizes = {
        "compact": ((240, 100), (420, 150), (300, 110)),
        "standard": ((380, 170), (640, 260), (460, 200)),
        "wide": ((660, 150), (1200, 280), (780, 190)),
        "tall": ((330, 380), (560, 900), (380, 520)),
        "large": ((660, 400), (1200, 900), (780, 560)),
    }
    default_size = "standard"

    def __init__(self, cfg=None, wake=None):
        super().__init__(cfg, wake)
        self.player, self.queue, self.recent = None, [], []
        self.art = NP.Art()
        self.note, self.note_at = None, 0.0
        self.mpris_src, self.mpris = None, None
        self.mpris_at = 0.0
        self.last_real = 0.0
        if K.demo():
            self.accts = None
            self.player, self.queue, self.recent = dict(DEMO_PLAYER), list(DEMO_QUEUE), list(DEMO_RECENT)
            return
        # one player: with several Spotify accounts, the first one the account setting lists
        # (or the first signed in)
        self.accts = K.Accounts(self, "spotify")
        self.p_now = self.poller(self.fetch_player, every=5, name="player")
        self.p_lists = self.poller(self.fetch_lists, every=60, idle=90, name="lists")

    @property
    def acct(self):
        if self.accts is None:
            return None
        signed = self.accts.signed_in()
        return signed[0] if signed else self.accts.first()

    # ---- data
    def api(self, path, method=None, data=None):
        tok = self.acct.token()
        if not tok:
            raise PermissionError("signed out")
        import bromigos_account as A
        return A.http_json(API + path, data=data, method=method, form=False,
                           headers={"Authorization": f"Bearer {tok}"})

    def fetch_player(self):
        if not self.acct.status().get("signed_in"):
            return None
        # paused or idle: every 20 s is enough
        if self.player is not None and not self.player.get("playing") and time.time() - self.last_real < 20:
            return self.player
        self.player = parse_player(self.api("/me/player"))
        self.last_real = time.time()
        return self.player

    def fetch_lists(self):
        if self.last_class not in ("tall", "large") or not self.conf.get("show_queue", True):
            return None
        if not self.acct.status().get("signed_in"):
            return None
        self.queue = parse_queue(self.api("/me/player/queue"))
        self.recent = parse_recent(self.api("/me/player/recently-played?limit=20"))
        return True

    def tick(self):
        if K.demo() or time.monotonic() - self.drawn_at > 30:
            return
        # the Spotify app on this machine, through MPRIS: for the clicks and a live position
        now = time.monotonic()
        if now - self.mpris_at >= 2:
            self.mpris_at = now
            try:
                if self.mpris_src is None:
                    self.mpris_src = NP.source()
                rows = self.mpris_src.read() if self.mpris_src else []
            except Exception:                          # noqa: BLE001
                rows = []
            self.mpris = next((r for r in rows if r["name"].lower() == "spotify"), None)
        if self.last_class in ("tall", "large") and self.queue == [] and self.recent == [] and getattr(self, "p_lists", None):
            if self.p_lists.runs <= 1 and not self.p_lists.busy:
                self.p_lists.kick()

    def position(self):
        p = self.player or {}
        if not p.get("active"):
            return None
        if self.mpris and self.mpris.get("position") is not None:
            return self.mpris["position"]
        pos = p.get("position") or 0
        if p.get("playing") and p.get("at"):
            pos += time.time() - p["at"]
        length = (p.get("track") or {}).get("length")
        return min(pos, length) if length else pos

    def act(self, verb):
        """play-pause, next, previous: through the app's MPRIS player when it's here, else
        the Web API (Premium)."""
        if K.demo():
            return
        if self.mpris and self.mpris_src:
            self.mpris_src.control(self.mpris["instance"], verb)
            self.p_now.kick()
            return
        playing = (self.player or {}).get("playing")
        path, method = {"play-pause": ("/me/player/pause" if playing else "/me/player/play", "PUT"),
                        "next": ("/me/player/next", "POST"), "previous": ("/me/player/previous", "POST")}[verb]

        def go():
            try:
                self.api(path, method=method, data={} if method == "PUT" else None)
                self.note = None
            except Exception as e:                     # noqa: BLE001
                self.note, self.note_at = control_error(e), time.monotonic()
            time.sleep(0.4)
            self.last_real = 0.0
            self.p_now.kick()
        threading.Thread(target=go, daemon=True, name="spotify-control").start()

    def _redraw(self):
        if callable(self.wake):
            try:
                self.wake(self)
            except Exception:                          # noqa: BLE001
                pass

    # ---- drawing
    def via(self):
        return ("the Spotify app on this computer (MPRIS)" if self.mpris else "Spotify's Web API (Premium only)")

    def draw(self, cr, w, h):
        cls = self.size_class(w, h)
        p = self.player or {}
        t = p.get("track") if p.get("active") else None
        right = None
        if p.get("active") and cls != "compact":
            right = ("PLAYING" if p.get("playing") else "PAUSED") + (f" · {p['device'].upper()}" if p.get("device") else "")
        elif p.get("active"):
            right = "PLAYING" if p.get("playing") else "PAUSED"
        room = max(6, int((w - 130) / 9.5))                 # characters of the header's right that fit
        if right and len(right) > room:
            right = right[:room - 1] + "…"
        top = D.frame(cr, w, h, self.title, right, "phosphor" if p.get("playing") else "static")
        st = self.acct.status() if self.acct else {"signed_in": True, "who": "demo"}
        self.region(0, 0, w, 34, "Your Spotify account through Spotify's Web API"
                    + (f", signed in as {st['who']}" if st.get("who") else "")
                    + (f". Playing on {p['device']} ({p.get('device_type', '').lower()})" if p.get("device") else "")
                    + (". The Spotify app on this computer takes the clicks (MPRIS)" if self.mpris else "")
                    + ". Now playing (the NOW PLAYING panel) covers any media player.")
        if self.acct and not st.get("signed_in"):
            self.acct.draw_signin(cr, w, h, top, "The Spotify panel reads what your account plays, its queue and recent tracks")
            return
        poll = getattr(self, "p_now", None)
        if poll and poll.error and self.player is None:
            self.empty(cr, w, h, top, "SPOTIFY DIDN'T ANSWER", poll.error, color="danger")
            return
        if self.player is None:
            self.empty(cr, w, h, top, "READING SPOTIFY…", "", color="static")
            return
        if not t:
            self.empty(cr, w, h, top, "NOTHING PLAYING ON SPOTIFY",
                       "Start something in Spotify on any device; it shows here within a few seconds."
                       if cls != "compact" else "", color="static",
                       tip="Spotify says nothing is playing on any of your devices")
            if cls == "large":
                self._list(cr, "RECENTLY PLAYED", self.recent, 16, top + 90, w - 32, h - 12, recent=True)
            return
        x0, x1 = 16, w - 16
        getattr(self, "_" + cls)(cr, p, t, w, h, top, x0, x1)
        if self.note and time.monotonic() - self.note_at < 8:
            D.src(cr, "panel", 0.95)
            cr.rectangle(x0, h - 30, x1 - x0, 22)
            cr.fill()
            D.text(cr, x0 + 4, h - 27, self.note, 10, "amber", "regular", width=x1 - x0 - 8)
            self.region(x0, h - 30, x1 - x0, 22, self.note)

    def _art(self, t, size):
        return self.art.get(t.get("art"), (size, size), on_ready=self._redraw)

    def _words(self, cr, t, x, y, width, big=15, bottom=None):
        _, th = D.text(cr, x, y, t["title"] or "Untitled", big, "phosphor", "semibold", width=width, glow=True)
        self.region(x, y, width, th, f"{t['kind'].title()}: {t['title']}" + (". Click to open it in Spotify." if t.get("url") else ""),
                    (lambda u=t["url"]: K.open_url(u)) if t.get("url") else None)
        y += th + 3
        for val, col, size, what in ((t["artist"], "soft", big - 3, "By"), (t["album"], "static", big - 4, "From")):
            if val and (bottom is None or y + size + 4 <= bottom):
                _, hh = D.text(cr, x, y, val, size, col, "regular", width=width)
                self.region(x, y, width, hh, f"{what}: {val}")
                y += hh + 2
        return y

    def _transport(self, cr, p, x, y, size=24):
        return NP.draw_transport(self, cr, x, y, p.get("playing"), self.act, size, None, self.via())

    def _progress(self, cr, t, x, y, w):
        NP.draw_progress(self, cr, x, y, w, self.position(), t.get("length"), None, tip_what=f"“{t['title']}”")

    def _device(self, cr, p, x, y, w):
        bits = []
        if p.get("device"):
            bits.append(p["device"])
        if p.get("volume") is not None:
            bits.append(f"vol {p['volume']}%")
        if p.get("shuffle"):
            bits.append("shuffle")
        if p.get("repeat") and p["repeat"] != "off":
            bits.append(f"repeat {p['repeat']}")
        if not bits:
            return
        D.text(cr, x, y, " · ".join(bits), 10, "static", "regular", width=w)
        self.region(x, y, w, 16, f"Playing on {p.get('device') or 'a device'} ({(p.get('device_type') or '').lower()})"
                    + (f" at {p['volume']}% volume" if p.get("volume") is not None else "")
                    + (", shuffled" if p.get("shuffle") else "")
                    + (f", repeating the {p['repeat']}" if p.get("repeat") not in (None, "off") else ""))

    def _list(self, cr, title, rows, x, y, w, bottom, recent=False):
        D.label(cr, x, y, title, "dim", size=10)
        D.rule(cr, x + D.layout(cr, title, 10, "semibold", 0.18).get_pixel_size()[0] + 10, y + 7, x + w, "dim", 0.3)
        y += 18
        if not rows:
            msg = ("Read every minute while this panel is tall or large." if self.conf.get("show_queue", True)
                   else "Off in this panel's settings (show_queue).")
            D.text(cr, x, y, msg, 10, "static", "regular", width=w)
            self.region(x, y - 18, w, 36, f"{title.title()}: nothing yet. {msg}")
            return y + 18
        for i, t in enumerate(rows):
            if y + 20 > bottom:
                D.label(cr, x + w, bottom - 12, f"+{len(rows) - i} MORE", "static", size=10, align="right")
                break
            D.text(cr, x, y, f"{i + 1:>2}" if not recent else K.ago(t.get("played_at")), 10, "static", "regular")
            D.text(cr, x + 34, y, t["title"], 11, "soft", "medium", width=w * 0.55 - 34)
            D.text(cr, x + w * 0.56, y + 1, t["artist"], 10, "static", "regular", width=w * 0.44 - (44 if not recent else 0))
            if not recent and t.get("length"):
                D.text(cr, x + w, y + 1, NP.mmss(t["length"]), 10, "static", "regular", align="right")
            self.region(x, y - 1, w, 19, (f"Played {K.ago(t.get('played_at'))} ago: " if recent else f"Up next, number {i + 1}: ")
                        + f"{t['title']} by {t['artist']}" + (f" ({NP.mmss(t['length'])})" if t.get("length") else ""))
            y += 20
        return y

    # ---- the size classes
    def _compact(self, cr, p, t, w, h, top, x0, x1):
        size = h - top - 12
        ax = x0
        if size >= 48 and w >= 280:
            NP.draw_art(self, cr, self._art(t, size), x0, top, size, f"Cover of {t['album'] or t['title']}")
            ax = x0 + size + 12
        bx = x1 - 30 if w < 380 else x1 - 3 * 24 - 2 * 8 - 6
        D.text(cr, ax, top + 2, t["title"], 13, "phosphor", "semibold", width=bx - ax - 8)
        D.text(cr, ax, top + 22, t["artist"], 11, "soft", "regular", width=bx - ax - 8)
        self.region(ax, top, bx - ax - 8, 36, f"{t['title']} by {t['artist']}")
        if w >= 380:
            bx = x1 - 3 * 24 - 2 * 8 - 6
            NP.draw_transport(self, cr, bx, top + 6, p.get("playing"), self.act, 24, None, self.via())
        else:
            self._play(cr, p, bx, top + 4)
        pos, length = self.position(), t.get("length")
        D.bar(cr, ax, h - 14, x1 - ax, 3, (pos / length) if pos is not None and length else 0)
        self.region(ax, h - 18, x1 - ax, 10, f"{NP.mmss(pos)} of {NP.mmss(length)}")

    def _play(self, cr, p, x, y):
        s = 28
        D.src(cr, "guard", 0.9)
        cr.rectangle(x, y, s, s)
        cr.fill()
        D.src(cr, "phosphor", 0.9)
        cr.set_line_width(1)
        cr.rectangle(x + 0.5, y + 0.5, s - 1, s - 1)
        cr.stroke()
        m, cx, cy = s * 0.3, x + s / 2, y + s / 2
        if p.get("playing"):
            cr.rectangle(cx - m * 0.7, cy - m, m * 0.5, 2 * m)
            cr.rectangle(cx + m * 0.2, cy - m, m * 0.5, 2 * m)
        else:
            cr.move_to(cx - m * 0.6, cy - m)
            cr.line_to(cx + m, cy)
            cr.line_to(cx - m * 0.6, cy + m)
            cr.close_path()
        cr.fill()
        self.region(x, y, s, s, ("Pause" if p.get("playing") else "Play") + f" ({self.via()})",
                    lambda: self.act("play-pause"))

    def _standard(self, cr, p, t, w, h, top, x0, x1):
        size = min(h - top - 14, int((x1 - x0) * 0.36))
        NP.draw_art(self, cr, self._art(t, size), x0, top, size, f"Cover of {t['album'] or t['title']}")
        tx = x0 + size + 16
        tw = x1 - tx
        by = h - 40
        self._words(cr, t, tx, top, tw, bottom=by - 34)
        self._progress(cr, t, tx, by - 26, tw)
        bw = self._transport(cr, p, tx, by + 6, 22)
        self._device(cr, p, tx + bw + 14, by + 10, x1 - tx - bw - 14)

    def _wide(self, cr, p, t, w, h, top, x0, x1):
        size = h - top - 14
        NP.draw_art(self, cr, self._art(t, size), x0, top, size, f"Cover of {t['album'] or t['title']}")
        tx = x0 + size + 16
        tw = min(420, (x1 - tx) * 0.55)
        self._words(cr, t, tx, top, tw, bottom=h - 74)
        self._progress(cr, t, tx, h - 66, tw)
        self._transport(cr, p, tx, h - 38, 22)
        dx = tx + tw + 28
        dw = x1 - dx
        D.label(cr, dx, top, "DEVICE", "dim", size=10)
        y = top + 18
        rows = [("ON", p.get("device") or "?"), ("TYPE", (p.get("device_type") or "?").lower()),
                ("VOLUME", f"{p['volume']}%" if p.get("volume") is not None else "?"),
                ("SHUFFLE", "on" if p.get("shuffle") else "off"), ("REPEAT", p.get("repeat") or "off"),
                ("CONTROL", "this computer's app" if self.mpris else "Web API")]
        for k, v in rows:
            if y + 16 > h - 12:
                break
            D.label(cr, dx, y, k, "static", size=10)
            D.text(cr, dx + 90, y - 1, v, 11, "soft", "regular", width=dw - 90)
            y += 18
        self.region(dx, top, dw, y - top, f"The device Spotify plays on: {p.get('device') or 'unknown'}"
                    + (f" at {p['volume']}% volume" if p.get("volume") is not None else "")
                    + f". The buttons go through {self.via()}.")

    def _tall(self, cr, p, t, w, h, top, x0, x1):
        size = int(min(x1 - x0, (h - top) * 0.55))
        NP.draw_art(self, cr, self._art(t, size), x0 + (x1 - x0 - size) / 2, top, size,
                    f"Cover of {t['album'] or t['title']}")
        y = self._words(cr, t, x0, top + size + 14, x1 - x0, big=16)
        self._progress(cr, t, x0, y + 10, x1 - x0)
        y += 38
        self._transport(cr, p, x0 + (x1 - x0 - 106) / 2, y + 4, 26)
        y += 46
        if y + 16 < h - 10:
            self._device(cr, p, x0, y, x1 - x0)
        if h - y > 90 and self.conf.get("show_queue", True):
            self._list(cr, "UP NEXT", self.queue, x0, y + 30, x1 - x0, h - 12)

    def _large(self, cr, p, t, w, h, top, x0, x1):
        size = int(min((x1 - x0) * 0.4, (h - top) * 0.55))
        NP.draw_art(self, cr, self._art(t, size), x0, top, size, f"Cover of {t['album'] or t['title']}")
        tx = x0 + size + 24
        tw = x1 - tx
        y = self._words(cr, t, tx, top, tw, big=20)
        self._progress(cr, t, tx, y + 18, tw)
        self._transport(cr, p, tx, y + 50, 28)
        self._device(cr, p, tx, y + 96, tw)
        ly = top + size + 20
        if not self.conf.get("show_queue", True):
            return
        qy = y + 128
        if top + size - qy >= 80:                     # room beside the cover: up next there
            self._list(cr, "UP NEXT", self.queue, tx, qy, tw, top + size)
            self._list(cr, "RECENTLY PLAYED", self.recent, x0, ly, x1 - x0, h - 12, recent=True)
        else:
            half = (x1 - x0 - 24) / 2
            self._list(cr, "UP NEXT", self.queue, x0, ly, half, h - 12)
            self._list(cr, "RECENTLY PLAYED", self.recent, x0 + half + 24, ly, half, h - 12, recent=True)


PANEL = SpotifyPanel
LAYOUT = {"visible": False}
