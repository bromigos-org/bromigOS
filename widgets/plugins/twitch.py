"""TWITCH: your own channel's live status, viewers, title and category, and which of the
channels you follow are live now. Click a channel to open it on twitch.tv.

It reads Twitch's Helix API with your own sign-in: the device flow in
lib/bromigos_account.py (provider "twitch"), with a client ID from your own Twitch app
and no secret. The token stays in your keyring. More channels to watch go in
~/.config/bromigos/widgets/twitch.toml (`channels = ["a_login", …]`).

Large adds the featured stream's thumbnail and its chat activity: messages a minute, read
from Twitch's anonymous read-only chat (IRC, as a "justinfan" guest). It counts messages;
it never keeps or shows what they say. Chat is connected only while the panel is large,
seen and the stream is live.
"""
import collections
import os
import random
import socket
import sys
import threading
import time
import urllib.error
import urllib.parse

sys.path.append(os.path.dirname(os.path.realpath(__file__)))   # after the standard library
import _kit as K  # noqa: E402

import draw as D  # noqa: E402
import sources as S  # noqa: E402

HELIX = "https://api.twitch.tv/helix"
POLL = 60.0                       # seconds between Helix reads while the panel is seen


def channel_url(login):
    return f"https://www.twitch.tv/{login}"


def thumb_url(template, w, h):
    return (template or "").replace("{width}", str(int(w))).replace("{height}", str(int(h)))


def parse_stream(s):
    """A Helix stream object as the panel's record."""
    return {"login": s.get("user_login") or "", "name": s.get("user_name") or s.get("user_login") or "?",
            "game": s.get("game_name") or "", "title": s.get("title") or "", "viewers": int(s.get("viewer_count") or 0),
            "started": K.iso_time(s.get("started_at")), "thumb": s.get("thumbnail_url") or "",
            "live": (s.get("type") or "live") == "live", "lang": s.get("language") or ""}


def merge_live(followed, watched, me_login=None):
    """The live channels to list: followed and watched together, no duplicates, not your
    own, most viewers first. Each says whether you follow it."""
    out = {}
    for s in followed:
        out[s["login"]] = dict(s, followed=True)
    for s in watched:
        out.setdefault(s["login"], dict(s, followed=False))
    rows = [s for k, s in out.items() if k and k != me_login]
    rows.sort(key=lambda s: -s["viewers"])
    return rows


def uptime(started):
    if not started:
        return ""
    return S.duration(max(0, time.time() - started))


# ------------------------------------------------------------------ chat activity (anonymous IRC)
class ChatRate(threading.Thread):
    """Counts a channel's chat messages from Twitch's read-only anonymous IRC. Keeps counts
    per minute for half an hour; never the messages."""

    HOST, PORT = "irc.chat.twitch.tv", 6667

    def __init__(self, login):
        super().__init__(daemon=True, name=f"twitch-chat-{login}")
        self.login = login.lower()
        self.stamps = collections.deque(maxlen=20000)     # message times, the last hour at most
        self.started = time.time()
        self.error = None
        self.connected = False
        self._stop = threading.Event()

    def stop(self):
        self._stop.set()

    def stopped(self):
        return self._stop.is_set()

    def count_line(self, line, now=None):
        """One IRC line: True when it's a chat message (counted)."""
        if " PRIVMSG #" in line:
            self.stamps.append(now or time.time())
            return True
        return False

    def run(self):
        backoff = 5
        while not self._stop.is_set():
            try:
                with socket.create_connection((self.HOST, self.PORT), timeout=15) as sk:
                    sk.settimeout(1.0)
                    nick = f"justinfan{random.randint(10000, 99999)}"
                    sk.sendall(f"NICK {nick}\r\nJOIN #{self.login}\r\n".encode())
                    self.connected, self.error, backoff = True, None, 5
                    buf = b""
                    while not self._stop.is_set():
                        try:
                            chunk = sk.recv(8192)
                        except socket.timeout:
                            continue
                        if not chunk:
                            raise OSError("chat closed the connection")
                        buf += chunk
                        *lines, buf = buf.split(b"\r\n")
                        for raw in lines:
                            line = raw.decode("utf-8", "replace")
                            if line.startswith("PING"):
                                sk.sendall(("PONG" + line[4:] + "\r\n").encode())
                            else:
                                self.count_line(line)
            except OSError as e:
                self.connected, self.error = False, str(e)[:80]
                self._stop.wait(backoff)
                backoff = min(backoff * 2, 120)
        self.connected = False

    def per_minute(self, now=None):
        """Messages in the last 60 s."""
        now = now or time.time()
        return sum(1 for t in self.stamps if now - t < 60)

    def series(self, minutes=30, now=None):
        """Messages per minute for the last `minutes` minutes since it connected (None before)."""
        now = now or time.time()
        out = []
        for m in range(minutes, 0, -1):
            a, b = now - m * 60, now - (m - 1) * 60
            out.append(None if b < self.started else sum(1 for t in self.stamps if a < t <= b))
        return out


class DemoChat:
    connected, error, login = True, None, "demo"

    def __init__(self, login="demo"):
        self.login = login
        self.started = time.time() - 1800

    def per_minute(self, now=None):
        return 148

    def series(self, minutes=30, now=None):
        import math
        return [int(90 + 50 * math.sin(i / 4.0) + 30 * max(0, math.sin(i / 2.1)) ** 4) for i in range(minutes)]

    def stop(self):
        pass

    def stopped(self):
        return False


# ------------------------------------------------------------------ demo readings
def demo_data():
    now = time.time()

    def st(login, name, game, title, viewers, mins, followed=True):
        return {"login": login, "name": name, "game": game, "title": title, "viewers": viewers,
                "started": now - mins * 60, "thumb": "", "live": True, "lang": "en", "followed": followed}
    return {"me": {"id": "1", "login": "relay_keeper", "name": "relay_keeper"},
            "mine": st("relay_keeper", "relay_keeper", "Software and Game Development",
                       "Building a desktop widget, live: the lighthouse panel", 214, 97),
            "channel": {"title": "Building a desktop widget, live: the lighthouse panel",
                        "game": "Software and Game Development"},
            "followers": 3842,
            "live": [st("tidewatch", "Tidewatch", "Factorio", "Megabase day 41: the rail world", 1873, 260),
                     st("lamplighter_fm", "LamplighterFM", "Music", "Night shift synth set", 642, 75),
                     st("greywater_gg", "Greywater_GG", "Elden Ring", "Blind run, no summons", 388, 140),
                     st("harborpoint", "HarborPoint", "Just Chatting", "Morning coffee and patch notes", 121, 32,
                        followed=False),
                     st("driftrelay", "DriftRelay", "Outer Wilds", "First time through the Eye", 57, 18)],
            "followed_total": 37, "at": now}


def demo_picture(w, h):
    """A made-up stream picture for demo pictures: a code editor's glow at night."""
    import cairo
    surf = cairo.ImageSurface(cairo.FORMAT_ARGB32, max(1, w), max(1, h))
    cr = cairo.Context(surf)
    g = cairo.LinearGradient(0, 0, w, h)
    g.add_color_stop_rgb(0, 0.04, 0.05, 0.12)
    g.add_color_stop_rgb(1, 0.10, 0.03, 0.16)
    cr.set_source(g)
    cr.paint()
    rnd = random.Random(7)
    for i in range(int(h / 14)):                       # lines of "code"
        x = w * 0.08 + rnd.randint(0, 4) * w * 0.03
        cr.set_source_rgba(0.3 + 0.5 * rnd.random(), 0.6 + 0.3 * rnd.random(), 0.9, 0.55)
        cr.rectangle(x, h * 0.1 + i * 12, w * (0.15 + 0.4 * rnd.random()), 5)
        cr.fill()
    cr.set_source_rgba(0.95, 0.75, 0.35, 0.85)        # a webcam corner
    cr.arc(w * 0.84, h * 0.76, h * 0.13, 0, 6.283)
    cr.fill()
    return surf


# ------------------------------------------------------------------ the panel
class TwitchPanel(K.KitPanel):
    name, title = "twitch", "TWITCH"
    description = "Your Twitch channel's live status and viewers, and which channels you follow are live"
    category, reads = "media", "Twitch's API, with your sign-in"
    width, height = 460, 300
    interval = 5.0
    settings = [
        {"key": "account", "label": "Twitch account", "kind": "secret-signin", "provider": "twitch",
         "hint": "Sign in once; the token stays in your keyring"},
        {"key": "channels", "label": "More channels to watch", "kind": "list", "default": [],
         "hint": "Twitch logins, as in twitch.tv/<login>, whether you follow them or not"},
    ]
    sizes = {
        "compact": ((240, 120), (380, 190), (280, 140)),
        "standard": ((400, 240), (620, 420), (460, 300)),
        "wide": ((640, 200), (1100, 360), (760, 240)),
        "tall": ((380, 440), (560, 900), (420, 560)),
        "large": ((660, 480), (1200, 900), (780, 580)),
    }
    default_size = "standard"

    def __init__(self, cfg=None, wake=None):
        super().__init__(cfg, wake)
        self.demo = K.demo()                          # made-up readings, for pictures
        self.chat = None
        self.thumb = None                       # (login, bytes) of the featured stream's picture
        self.auth_error = None
        if self.demo:
            self.acc = None
            self.data = demo_data()
            self.chat = DemoChat("relay_keeper")
            self.poll = None
            return
        self.acc = K.Account(self, "twitch")
        self.data = None
        self.poll = self.poller(self.fetch, every=POLL, name="helix")

    # ---- data
    def _get(self, path, **q):
        import bromigos_account as A
        tok = A.token("twitch")
        if not tok:
            raise PermissionError("signed out")
        cid = A.config("twitch").get("client_id") or ""
        qs = urllib.parse.urlencode([(k, v) for k, vs in q.items() for v in (vs if isinstance(vs, list) else [vs])])
        url = f"{HELIX}/{path}" + (f"?{qs}" if qs else "")
        try:
            return A.http_json(url, headers={"Authorization": f"Bearer {tok}", "Client-Id": cid})
        except urllib.error.HTTPError as e:
            if e.code != 401:
                raise
            # the token may have been revoked or gone stale: refresh once, then ask again
            new = A.refresh("twitch")
            if not new:
                raise PermissionError("Twitch didn't accept the stored sign-in (unused for 30 days, or revoked)")
            return A.http_json(url, headers={"Authorization": f"Bearer {new}", "Client-Id": cid})

    def fetch(self):
        if not self.acc.status().get("signed_in"):
            return self.data
        try:
            me = (self._get("users").get("data") or [{}])[0]
        except PermissionError as e:
            self.auth_error = str(e)
            return None
        self.auth_error = None
        uid = me.get("id")
        out = {"me": {"id": uid, "login": me.get("login"), "name": me.get("display_name") or me.get("login"),
                      "image": me.get("profile_image_url")}, "at": time.time()}
        mine = [parse_stream(s) for s in self._get("streams", user_id=uid).get("data") or []]
        out["mine"] = mine[0] if mine else None
        ch = (self._get("channels", broadcaster_id=uid).get("data") or [{}])[0]
        out["channel"] = {"title": ch.get("title") or "", "game": ch.get("game_name") or ""}
        try:
            out["followers"] = self._get("channels/followers", broadcaster_id=uid, first=1).get("total")
        except (urllib.error.HTTPError, OSError):
            out["followers"] = None
        followed = []
        cursor = None
        for _ in range(3):                                 # 300 live channels at most
            q = {"user_id": uid, "first": 100}
            if cursor:
                q["after"] = cursor
            page = self._get("streams/followed", **q)
            followed += [parse_stream(s) for s in page.get("data") or []]
            cursor = (page.get("pagination") or {}).get("cursor")
            if not cursor:
                break
        watched = []
        names = self.conf.list("channels")[:100]
        if names:
            watched = [parse_stream(s) for s in self._get("streams", user_login=names).get("data") or []]
        out["live"] = merge_live(followed, watched, out["me"]["login"])
        out["watched"] = names
        return out

    def _load_thumb(self, feat):
        """The featured stream's picture, on a thread (only while large and seen; every 5 min)."""
        def go():
            try:
                self.thumb = (feat["login"], K.fetch_bytes(thumb_url(feat["thumb"], 640, 360)), time.time())
            except OSError:
                self.thumb = (feat["login"], None, time.time())
            finally:
                self._thumb_busy = False
        self._thumb_busy = True
        threading.Thread(target=go, daemon=True, name="twitch-thumb").start()

    @staticmethod
    def featured(d):
        """The stream large shows: yours when you're live, else the busiest live one."""
        if not d:
            return None
        if d.get("mine"):
            return d["mine"]
        return (d.get("live") or [None])[0]

    def tick(self):
        """Chat runs only while large, seen and the featured stream is live."""
        if self.demo:
            return
        d = self.poll.data if self.poll else None
        if d:
            self.data = d
        feat = self.featured(self.data)
        want = (feat["login"] if feat and self.last_class == "large"
                and time.monotonic() - self.drawn_at < 30 else None)
        if self.chat and (not want or self.chat.login != want):
            self.chat.stop()
            self.chat = None
        if want and not self.chat:
            self.chat = ChatRate(want)
            self.chat.start()
        if want and feat.get("thumb") and not getattr(self, "_thumb_busy", False):
            if not self.thumb or self.thumb[0] != feat["login"] or time.time() - self.thumb[2] > 300:
                self._load_thumb(feat)

    # ---- drawing
    def draw(self, cr, w, h):
        cls = self.size_class(w, h)
        d = self.data if self.demo else (self.poll.data if self.poll else None) or self.data
        me = (d or {}).get("me") or {}
        live_n = len((d or {}).get("live") or [])
        right = None
        if d:
            right = me.get("name") if cls == "compact" else f"{me.get('name', '')} · {live_n} LIVE"
        top = D.frame(cr, w, h, self.title, right)
        self.region(0, 0, w, 34, "Twitch: your channel, and the channels you follow that are live now"
                    + (f" ({live_n})" if d else "") + ". Read every minute while the panel is seen. Click to open Twitch.",
                    lambda: K.open_url("https://www.twitch.tv/directory/following"))
        if not self.demo:
            st = self.acc.status()
            if not st.get("signed_in") or self.auth_error:
                if self.auth_error and st.get("signed_in"):
                    self.empty(cr, w, h, top, "SIGN IN AGAIN", self.auth_error + ".",
                               button=("Sign in", "Sign in to Twitch again with the device flow",
                                       self.acc.signin.start))
                else:
                    self.acc.draw_signin(cr, w, h, top, "The Twitch panel reads your channel and the channels you follow")
                return
            if d is None:
                err = self.poll.error if self.poll else None
                self.empty(cr, w, h, top, "NO ANSWER FROM TWITCH" if err else "READING TWITCH…", err or "",
                           color="amber" if err else "static")
                return
        x0, x1 = 16, w - 16
        if cls == "compact":
            self._compact(cr, d, x0, x1, top, h)
        elif cls == "wide":
            split = x0 + max(280, (x1 - x0) * 0.36)
            self._mine(cr, d, x0, split - 16, top, h - 12, lines=3)
            self._grid(cr, d, split, x1, top, h - 12)
        elif cls == "tall":
            y = self._mine(cr, d, x0, x1, top, top + 150, lines=4)
            self._list(cr, d, x0, x1, y + 8, h - 12, titles=True)
        elif cls == "large":
            self._large(cr, d, x0, x1, top, h)
        else:
            y = self._mine(cr, d, x0, x1, top, top + 110, lines=2)
            self._list(cr, d, x0, x1, y + 6, h - 12, titles=h >= 360)

    def _live_badge(self, cr, x, y, live):
        col = "danger" if live else "static"
        return self.chip(cr, x, y, "LIVE" if live else "OFFLINE", col, filled=live)

    def _compact(self, cr, d, x0, x1, top, h):
        mine = d.get("mine")
        me = d.get("me") or {}
        self._live_badge(cr, x0, top, bool(mine))
        if mine:
            sh = max(18, min(44, h - top - 58 - (24 if h >= 170 else 0)))
            tw = D.seg7(cr, x0, top + 22, sh, f"{min(mine['viewers'], 99999)}", "phosphor")
            D.label(cr, x0 + tw + 12, top + 22 + sh - 14, "VIEWERS", "dim", size=10)
            if h >= 170:
                D.text(cr, x0, top + 30 + sh, " · ".join(b for b in (mine["game"], "UP " + uptime(mine["started"])) if b),
                       11, "soft", "regular", width=x1 - x0)
            self.region(x0, top, x1 - x0, 66, f"You're live: {mine['viewers']} watching, for {uptime(mine['started'])}, "
                        f"playing {mine['game'] or 'no category'}. Click to open your channel.",
                        lambda: K.open_url(channel_url(me.get("login"))))
        else:
            D.text(cr, x0, top + 22, (d.get("channel") or {}).get("game") or "Offline", 12, "soft", "medium", width=x1 - x0)
            self.region(x0, top, x1 - x0, 44, "Your channel is offline. Click to open it.",
                        lambda: K.open_url(channel_url(me.get("login"))))
        n = len(d.get("live") or [])
        D.label(cr, x0, h - 26, f"{n} FOLLOWED LIVE" if n else "NOBODY YOU FOLLOW IS LIVE", "phosphor" if n else "static",
                size=10)
        names = ", ".join(s["name"] for s in (d.get("live") or [])[:6])
        self.region(x0, h - 30, x1 - x0, 20, (f"Live now: {names}" if n else "None of the channels you follow is live")
                    + ". Make the panel bigger to see them.")

    def _mine(self, cr, d, x0, x1, top, bottom, lines=2):
        """Your channel: live or offline, viewers, title, category. Returns the y under it."""
        me = d.get("me") or {}
        mine = d.get("mine")
        ch = d.get("channel") or {}
        url = channel_url(me.get("login") or "")
        y = top
        bw = self._live_badge(cr, x0, y, bool(mine))
        D.text(cr, x0 + bw + 8, y - 1, me.get("name") or "?", 13, "phosphor", "semibold", width=x1 - x0 - bw - 100)
        if mine:
            D.text(cr, x1, y - 2, f"{mine['viewers']:,}", 15, "phosphor", "bold", align="right", glow=True)
            tip = (f"You're live on Twitch: {mine['viewers']:,} watching, live for {uptime(mine['started'])}. "
                   f"Title: {mine['title']}. Category: {mine['game'] or 'none'}. Click to open your channel.")
        else:
            fol = d.get("followers")
            if fol is not None:
                D.text(cr, x1, y, f"{K.short(fol)} FOLLOWERS", 10, "static", "semibold", align="right")
            tip = (f"Your channel is offline. Its title: {ch.get('title') or 'none'}; category: "
                   f"{ch.get('game') or 'none'}" + (f"; {fol:,} followers" if fol is not None else "") + ". Click to open it.")
        y += 22
        title = (mine or {}).get("title") or ch.get("title") or ""
        game = (mine or {}).get("game") or ch.get("game") or ""
        if title and lines >= 2:
            th = D.text(cr, x0, y, title, 12, "soft", "regular", width=x1 - x0, wrap=lines >= 3)[1]
            y += min(th, 34) + 4
        meta = " · ".join(b for b in (game, f"UP {uptime(mine['started'])}" if mine else "",
                                      f"{mine['lang'].upper()}" if mine and mine.get("lang") else "") if b)
        if meta:
            D.text(cr, x0, y, meta.upper(), 10, "dim", "semibold", spacing=0.18, width=x1 - x0)
            y += 18
        if lines >= 4 and not mine and d.get("followers") is not None:
            D.label(cr, x0, y, f"{d['followers']:,} FOLLOWERS", "static", size=10)
            y += 18
        self.region(x0, top - 2, x1 - x0, y - top, tip, lambda: K.open_url(url))
        D.rule(cr, x0, y + 2, x1)
        return y + 6

    def _row(self, cr, s, x0, x1, y, titles=False):
        rh = 34 if titles else 20
        D.dot(cr, x0 + 4, y + 8, 3, "danger", glow=False)
        D.text(cr, x0 + 14, y, s["name"], 12, "soft", "semibold", width=(x1 - x0) * 0.42)
        D.text(cr, x0 + 14 + (x1 - x0) * 0.44, y + 1, s["game"], 11, "static", "regular", width=(x1 - x0) * 0.36)
        D.text(cr, x1, y, f"{K.short(s['viewers'])}", 12, "phosphor", "semibold", align="right")
        if titles:
            D.text(cr, x0 + 14, y + 17, s["title"], 10, "static", "regular", width=x1 - x0 - 14)
        self.region(x0, y - 2, x1 - x0, rh - 2,
                    f"{s['name']} is live: {s['viewers']:,} watching, for {uptime(s['started'])}, in "
                    f"{s['game'] or 'no category'}. “{s['title']}”"
                    + ("" if s.get("followed", True) else " (a channel from your settings; you don't follow it)")
                    + ". Click to open it on twitch.tv.", lambda u=channel_url(s["login"]): K.open_url(u))
        return rh

    def _list(self, cr, d, x0, x1, top, bottom, titles=False):
        rows = d.get("live") or []
        D.label(cr, x0, top, "LIVE NOW", "dim", size=10)
        D.label(cr, x1, top, "VIEWERS", "static", size=10, align="right")
        y = top + 18
        if not rows:
            D.text(cr, x0, y, "Nobody you follow is live.", 11, "static", "regular")
            self.region(x0, top, x1 - x0, 40, "None of the channels you follow (or list in twitch.toml) is live right now")
            return
        rh = 34 if titles else 20
        room = max(1, int((bottom - y) // rh))
        for s in rows[:room]:
            y += self._row(cr, s, x0, x1, y, titles)
        if len(rows) > room:
            D.label(cr, x1, bottom - 12, f"+{len(rows) - room} MORE", "static", size=10, align="right")
            self.region(x1 - 90, bottom - 14, 90, 14, f"{len(rows) - room} more live channels: "
                        + ", ".join(s["name"] for s in rows[room:room + 12]))

    def _grid(self, cr, d, x0, x1, top, bottom):
        rows = d.get("live") or []
        D.label(cr, x0, top, f"LIVE NOW · {len(rows)}", "dim", size=10)
        if not rows:
            D.text(cr, x0, top + 20, "Nobody you follow is live.", 11, "static", "regular")
            self.region(x0, top, x1 - x0, 40, "None of the channels you follow is live right now")
            return
        cw, ch, gap = 190, 64, 10
        cols = max(1, int((x1 - x0 + gap) // (cw + gap)))
        cw = (x1 - x0 - (cols - 1) * gap) / cols
        nrows = max(1, int((bottom - top - 18 + gap) // (ch + gap)))
        for i, s in enumerate(rows[:cols * nrows]):
            cx = x0 + (i % cols) * (cw + gap)
            cy = top + 18 + (i // cols) * (ch + gap)
            D.src(cr, "guard", 0.6)
            cr.rectangle(cx, cy, cw, ch)
            cr.fill()
            D.src(cr, "danger", 0.9)
            cr.rectangle(cx, cy, 3, ch)
            cr.fill()
            D.text(cr, cx + 10, cy + 6, s["name"], 12, "soft", "semibold", width=cw - 70)
            D.text(cr, cx + cw - 8, cy + 6, K.short(s["viewers"]), 12, "phosphor", "bold", align="right")
            D.text(cr, cx + 10, cy + 24, s["game"], 10, "static", "regular", width=cw - 18)
            D.text(cr, cx + 10, cy + 40, s["title"], 10, "dim", "regular", width=cw - 18)
            self.region(cx, cy, cw, ch, f"{s['name']} is live: {s['viewers']:,} watching, for {uptime(s['started'])}, "
                        f"in {s['game'] or 'no category'}. “{s['title']}”. Click to open it.",
                        lambda u=channel_url(s["login"]): K.open_url(u))
        hidden = len(rows) - cols * nrows
        if hidden > 0:
            D.label(cr, x1, top, f"+{hidden} MORE", "static", size=10, align="right")
            self.region(x1 - 90, top - 2, 90, 16, f"{hidden} more live channels; make the panel bigger to see them")

    def _large(self, cr, d, x0, x1, top, h):
        feat = self.featured(d)
        tw = min((x1 - x0) * 0.55, (h - top) * 0.5 * 16 / 9)
        th = tw * 9 / 16
        # the featured stream's picture
        D.src(cr, "void", 0.9)
        cr.rectangle(x0, top, tw, th)
        cr.fill()
        surf = None
        if self.demo and feat:
            surf = demo_picture(int(tw), int(th))
        elif self.thumb and feat and self.thumb[0] == feat["login"] and self.thumb[1]:
            surf = K.picture(self.thumb[1], (int(tw), int(th)))
        if surf:
            K.draw_picture(cr, surf, x0, top, tw, th)
        else:
            D.label(cr, x0 + tw / 2, top + th / 2 - 7, "NOBODY IS LIVE" if not feat else "LOADING THE PICTURE…",
                    "static", size=10, align="center")
        D.src(cr, "dim", 0.6)
        cr.set_line_width(1)
        cr.rectangle(x0 + 0.5, top + 0.5, tw - 1, th - 1)
        cr.stroke()
        if feat:
            self._live_badge(cr, x0 + 8, top + 8, True)
            self.region(x0, top, tw, th, f"{feat['name']}'s stream as Twitch last pictured it (refreshed every 5 minutes "
                        f"while large). {'Your stream.' if d.get('mine') else 'The busiest live channel you follow.'} "
                        "Click to watch it.", lambda u=channel_url(feat["login"]): K.open_url(u))
        else:
            self.region(x0, top, tw, th, "Nobody you follow is live, and neither are you")
        # beside it: your channel, then the featured stream's chat activity
        rx = x0 + tw + 18
        y = self._mine(cr, d, rx, x1, top, top + th, lines=4)
        if feat:
            y = self._chat(cr, feat, rx, x1, y + 6, top + th)
        # under it: everyone live, with titles
        self._list(cr, d, x0, x1, top + th + 16, h - 12, titles=True)

    def _chat(self, cr, feat, x0, x1, top, bottom):
        c = self.chat
        D.label(cr, x0, top, f"CHAT · {feat['name']}", "dim", size=10)
        if not c or c.login != feat["login"].lower() and not self.demo:
            D.text(cr, x0, top + 18, "Connecting to chat…", 10, "static", "regular")
            self.region(x0, top, x1 - x0, 34, "Chat activity starts when the panel is large and seen")
            return top + 34
        rate = c.per_minute()
        D.text(cr, x1, top - 2, f"{rate}/MIN", 12, "phosphor" if c.connected else "static", "semibold", align="right")
        gy, gh = top + 18, max(24, min(60, bottom - top - 22))
        vals = c.series(30)
        D.src(cr, "void", 0.7)
        cr.rectangle(x0, gy, x1 - x0, gh)
        cr.fill()
        if sum(1 for v in vals if v is not None) >= 2:
            D.spark(cr, x0, gy + 2, x1 - x0, gh - 4, vals, "cyan", lo=0)
        known = [v for v in vals if v is not None]
        self.region(x0, top, x1 - x0, gh + 20,
                    f"Chat activity in {feat['name']}'s channel: {rate} messages in the last minute"
                    + (f", up to {max(known)} a minute in the last half hour" if known else "")
                    + ". Counted from Twitch's anonymous read-only chat; no message is kept or shown."
                    + ("" if c.connected else f" Not connected: {c.error or 'connecting'}."))
        return gy + gh + 6


PANEL = TwitchPanel
LAYOUT = {"visible": False}
