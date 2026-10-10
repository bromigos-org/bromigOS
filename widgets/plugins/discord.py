"""DISCORD: how many members of a Discord server are online, from Discord's public API, with
no sign-in and no token.

Two ways in, set in ~/.config/bromigos/widgets/discord.toml:

  invite = "abc123"        an invite code (or a discord.gg/… link): the server's name and
                           icon, members online and members in all, from
                           discord.com/api/v10/invites/<code>?with_counts=true
  server = "1234567890"    a server ID whose widget is on (Server Settings › Widget ›
                           Enable Server Widget): who's online by name, their status, and
                           the voice channels, from discord.com/api/guilds/<id>/widget.json

Either works alone; with both, the invite gives the totals and the widget the names.
Every read is kept for the session, so the panel draws the online count over time.
Large shows the members with their pictures and who is in each voice channel.
"""
import collections
import os
import re
import sys
import threading
import time
import urllib.error

sys.path.append(os.path.dirname(os.path.realpath(__file__)))   # after the standard library
import _kit as K  # noqa: E402

import draw as D  # noqa: E402

import bromigos_account as A  # noqa: E402  (lib/, on the path once draw is imported)

API = "https://discord.com/api"
POLL = 180.0                      # every 3 minutes while seen
STATUS = {"online": ("phosphor", "online"), "idle": ("amber", "idle"), "dnd": ("danger", "do not disturb")}


def invite_code(s):
    """'abc123', 'discord.gg/abc123', 'https://discord.com/invite/abc123' -> 'abc123'."""
    s = (s or "").strip().rstrip("/")
    m = re.search(r"(?:discord(?:app)?\.(?:gg|com/invite)/)([A-Za-z0-9-]+)", s)
    if m:
        return m.group(1)
    return s if re.fullmatch(r"[A-Za-z0-9-]{2,40}", s) else None


def parse_invite(d):
    g = d.get("guild") or {}
    return {"id": g.get("id") or d.get("guild_id"), "name": g.get("name") or "?", "icon": g.get("icon"),
            "description": g.get("description"), "online": d.get("approximate_presence_count"),
            "members": d.get("approximate_member_count"), "code": d.get("code")}


def parse_widget(d):
    chans = sorted(d.get("channels") or [], key=lambda c: c.get("position", 0))
    members = []
    for m in d.get("members") or []:
        members.append({"name": m.get("username") or "?", "status": m.get("status") or "online",
                        "avatar": m.get("avatar_url"), "channel": m.get("channel_id"),
                        "game": (m.get("activity") or {}).get("name") if isinstance(m.get("activity"), dict) else None})
    order = {"online": 0, "idle": 1, "dnd": 2}
    members.sort(key=lambda m: (m["channel"] is None, order.get(m["status"], 3), m["name"].lower()))
    voice = []
    for c in chans:
        who = [m["name"] for m in members if m["channel"] == c.get("id")]
        voice.append({"id": c.get("id"), "name": c.get("name") or "?", "who": who})
    return {"id": d.get("id"), "name": d.get("name"), "online": d.get("presence_count"),
            "invite": d.get("instant_invite"), "list": members, "voice": voice}


def icon_url(gid, icon, size=128):
    if not gid or not icon:
        return None
    return f"https://cdn.discordapp.com/icons/{gid}/{icon}.png?size={size}"


# ------------------------------------------------------------------ demo readings
def demo_data():
    names = ["harbor_owl", "Lamplighter", "tidewatch", "greywater", "relay-7", "beacon", "driftwood", "nightjar",
             "quartermaster", "fogbell", "saltmarsh", "keeper", "longshore", "anchorlight"]
    st = ["online", "online", "idle", "online", "dnd", "online", "idle", "online", "online", "online", "dnd",
          "online", "idle", "online"]
    voice = {"harbor_owl": "v1", "tidewatch": "v1", "relay-7": "v2"}
    members = [{"name": n, "status": s, "avatar": None, "channel": voice.get(n), "game": None}
               for n, s in zip(names, st)]
    members.sort(key=lambda m: (m["channel"] is None, {"online": 0, "idle": 1, "dnd": 2}[m["status"]], m["name"]))
    return {"name": "Harbor Point", "id": "1", "icon": None, "description": "A made-up server for pictures",
            "online": 32, "members": 122, "code": "harbor", "invite": "https://discord.gg/harbor",
            "list": members, "voice": [{"id": "v1", "name": "Lounge", "who": ["harbor_owl", "tidewatch"]},
                                       {"id": "v2", "name": "Workshop", "who": ["relay-7"]},
                                       {"id": "v3", "name": "Quiet room", "who": []}],
            "widget": True, "widget_error": None, "at": time.time()}


def demo_history():
    import math
    return collections.deque([(time.time() - (60 - i) * 180, int(26 + 6 * math.sin(i / 7.0) + 3 * math.sin(i / 2.3)))
                              for i in range(60)], maxlen=480)


# ------------------------------------------------------------------ the panel
class DiscordPanel(K.KitPanel):
    name, title = "discord", "DISCORD"
    description = "How many members of a Discord server are online, and who, with no sign-in"
    category, reads = "fun", "Discord's public invite and server widget"
    width, height = 420, 240
    interval = 10.0
    settings = [
        {"key": "invite", "label": "Invite", "kind": "text", "default": "",
         "hint": "An invite code or a discord.gg link: the server's name, members online and in all"},
        {"key": "server", "label": "Server ID", "kind": "text", "default": "",
         "hint": "A server whose widget is on (Server Settings › Widget): who's online by name, and voice channels"},
    ]
    sizes = {
        "compact": ((240, 120), (380, 190), (260, 130)),
        "standard": ((380, 220), (600, 380), (420, 240)),
        "wide": ((620, 180), (1100, 340), (720, 220)),
        "tall": ((360, 400), (520, 900), (400, 520)),
        "large": ((640, 460), (1100, 900), (720, 540)),
    }
    default_size = "standard"

    def __init__(self, cfg=None, wake=None):
        super().__init__(cfg, wake)
        self.demo = K.demo()                          # made-up readings, for pictures
        self.icon = None                              # bytes of the server's icon
        self.avatars = {}                             # url -> bytes (large only)
        self._av_busy = False
        if self.demo:
            self.data, self.history, self.poll = demo_data(), demo_history(), None
            return
        self.data = None
        self.history = collections.deque(maxlen=480)  # (time, online): a day at 3 minutes
        self.poll = self.poller(self.fetch, every=POLL, name="discord")

    def configured(self):
        return bool(invite_code(self.conf.get("invite", "")) or str(self.conf.get("server", "")).strip())

    def fetch(self):
        code = invite_code(self.conf.get("invite", ""))
        sid = re.sub(r"\D", "", str(self.conf.get("server", "") or ""))
        if not code and not sid:
            return None
        out = {"widget": False, "widget_error": None, "list": [], "voice": [], "at": time.time()}
        if code:
            try:
                out.update(parse_invite(A.http_json(f"{API}/v10/invites/{code}?with_counts=true")))
            except urllib.error.HTTPError as e:
                if e.code == 404:
                    raise ValueError(f"Discord doesn't know the invite {code!r}: it may have expired")
                raise
        if sid:
            try:
                w = parse_widget(A.http_json(f"{API}/guilds/{sid}/widget.json"))
                out["widget"] = True
                out["list"], out["voice"] = w["list"], w["voice"]
                out["invite"] = w["invite"]
                if out.get("online") is None:
                    out["online"] = w["online"]
                out.setdefault("name", w["name"])
                out.setdefault("id", w["id"])
            except urllib.error.HTTPError as e:
                body = getattr(e, "body", None)
                if e.code == 403 or (isinstance(body, dict) and body.get("code") == 50004):
                    out["widget_error"] = "the server's widget is off: Server Settings › Widget › Enable Server Widget"
                elif e.code == 404:
                    out["widget_error"] = f"no server {sid}"
                else:
                    out["widget_error"] = f"HTTP {e.code}"
                if not code:
                    raise ValueError(out["widget_error"])
        if out.get("online") is not None:
            self.history.append((time.time(), int(out["online"])))
        if out.get("icon") and out.get("id") and not self.icon:
            try:
                self.icon = K.fetch_bytes(icon_url(out["id"], out["icon"]))
            except OSError:
                pass
        return out

    def tick(self):
        if self.demo or not self.poll:
            return
        if self.poll.data is not None:
            self.data = self.poll.data
        # members' pictures: only while large and seen, a few at a time
        if self.last_class == "large" and time.monotonic() - self.drawn_at < 30 and self.data and not self._av_busy:
            want = [m["avatar"] for m in self.data.get("list") or [] if m.get("avatar") and m["avatar"] not in self.avatars]
            if want:
                self._av_busy = True

                def go(urls=want[:12]):
                    for u in urls:
                        try:
                            self.avatars[u] = K.fetch_bytes(u, timeout=8)
                        except OSError:
                            self.avatars[u] = None
                    self._av_busy = False
                threading.Thread(target=go, daemon=True, name="discord-avatars").start()

    # ---- drawing
    def draw(self, cr, w, h):
        cls = self.size_class(w, h)
        d = self.data
        right = None
        if d and d.get("name"):
            right = d["name"] if cls in ("compact", "standard") else f"{d['name']} · {K.short(d.get('members'))} MEMBERS" \
                if d.get("members") else d["name"]
        top = D.frame(cr, w, h, self.title, right)
        open_it = (lambda u=(d or {}).get("invite") or (f"https://discord.gg/{d['code']}" if d and d.get("code") else None):
                   K.open_url(u)) if d else None
        self.region(0, 0, w, 34, "Discord: members online on a server, from Discord's public invite and widget (no sign-in), "
                    "read every 3 minutes while the panel is seen" + (". Click to open the invite." if d else ""), open_it)
        if not self.demo and not self.configured():
            self.empty(cr, w, h, top, "NO SERVER SET",
                       f"Put invite = \"CODE\" (a discord.gg invite) or server = \"ID\" (a server with its widget "
                       f"on) in {K.home_path(K.settings_path('discord'))}.",
                       tip="The Discord panel needs a server: an invite code for the counts, or a server ID whose "
                           "widget is on (Server Settings › Widget) for who's online by name")
            return
        if d is None:
            err = self.poll.error if self.poll else None
            self.empty(cr, w, h, top, "NO ANSWER FROM DISCORD" if err else "READING DISCORD…", err or "",
                       color="amber" if err else "static")
            return
        x0, x1 = 16, w - 16
        if cls == "compact":
            y = self._counts(cr, d, x0, x1, top, h - 10, big=max(20, min(44, h - top - 50)))
            if h - 12 - y >= 40:
                self._history(cr, x0, x1, y + 2, h - 12)
        elif cls == "wide":
            split = x0 + max(250, (x1 - x0) * 0.32)
            y = self._counts(cr, d, x0, split - 16, top, h - 12, big=40)
            if d.get("list"):
                if h - 12 - y >= 60:
                    self._history(cr, x0, split - 16, y + 4, h - 12)
                self._grid(cr, d, split, x1, top, h - 12)
            else:
                self._history(cr, split, x1, top, h - 14)
        elif cls == "tall":
            y = self._counts(cr, d, x0, x1, top, top + 140, big=44)
            gh = max(70, min(160, (h - y) * 0.22))
            self._history(cr, x0, x1, y + 6, y + 6 + gh)
            y = self._voice(cr, d, x0, x1, y + gh + 16, h - 12)
            self._members(cr, d, x0, x1, y + 6, h - 12)
        elif cls == "large":
            self._large(cr, d, x0, x1, top, h)
        else:
            y = self._counts(cr, d, x0, x1, top, top + 120, big=40)
            if d.get("list"):
                self._members(cr, d, x0, x1, y + 6, h - 12, cols=2)
            else:
                self._history(cr, x0, x1, y + 6, h - 12)

    def _counts(self, cr, d, x0, x1, top, bottom, big=40, icon=False):
        """The online count, members in all, and the server's name. Returns the y under it."""
        on, all_ = d.get("online"), d.get("members")
        x = x0
        if icon:
            surf = K.picture(self.icon, (56, 56)) if self.icon else None
            D.src(cr, "guard", 0.9)
            cr.arc(x0 + 28, top + 30, 28, 0, 6.283)
            cr.fill()
            if surf:
                cr.save()
                cr.arc(x0 + 28, top + 30, 27, 0, 6.283)
                cr.clip()
                K.draw_picture(cr, surf, x0, top + 2, 56, 56)
                cr.restore()
            else:
                D.text(cr, x0 + 28, top + 18, (d.get("name") or "?")[:2].upper(), 18, "phosphor", "bold", align="center")
            self.region(x0, top, 60, 60, f"{d.get('name')}: the server's icon")
            x = x0 + 72
        D.dot(cr, x + 4, top + 8, 3.5, "phosphor", glow=False)
        D.label(cr, x + 14, top + 1, "ONLINE", "dim", size=10)
        tw = D.seg7(cr, x, top + 22, big, "--" if on is None else str(on), "phosphor")
        y = top + 22 + big + 8
        tip = (f"{on} members of {d.get('name')} are online now" if on is not None else "Discord gave no online count")
        if all_:
            D.text(cr, x + tw + 14, top + 22 + big - 16, f"/ {all_:,}", 14, "soft", "semibold")
            frac = (on or 0) / all_
            tip += f", of {all_:,} members ({frac * 100:.0f}%)"
        self.region(x0, top, x1 - x0, y - top, tip + (". Discord's counts are approximate and lag a few minutes." if all_
                                                    else "."))
        if bottom - y >= 20 and all_:
            D.cells(cr, x0, y, x1 - x0, 7, (on or 0) / all_, n=30, warn=2, crit=2)
            self.region(x0, y - 2, x1 - x0, 12, f"{on} of {all_:,} members online")
            y += 14
        if d.get("widget_error") and bottom - y >= 30:
            D.text(cr, x0, y, "Names: " + d["widget_error"], 10, "amber", "regular", width=x1 - x0, wrap=True)
            self.region(x0, y, x1 - x0, 28, "The server ID's widget couldn't be read: " + d["widget_error"]
                        + ". Until then only the invite's counts show.")
            y += 30
        return y

    def _history(self, cr, x0, x1, top, bottom):
        hist = list(self.history)
        D.label(cr, x0, top, "ONLINE OVER TIME", "dim", size=10)
        gh = bottom - top - 18
        D.src(cr, "void", 0.7)
        cr.rectangle(x0, top + 16, x1 - x0, gh)
        cr.fill()
        if len(hist) >= 2:
            vals = [v for _, v in hist]
            D.spark(cr, x0, top + 18, x1 - x0, gh - 4, vals, "phosphor", lo=0, hi=max(vals) * 1.15 or 1)
            span = hist[-1][0] - hist[0][0]
            D.label(cr, x1, top, (f"LAST {K.ago(time.time() - span).upper()} · " if x1 - x0 >= 320 else "")
                    + f"PEAK {max(vals)}", "static", size=10, align="right")
            self.region(x0, top, x1 - x0, bottom - top, f"Members online at each read (every 3 minutes) since the panel "
                        f"started: low {min(vals)}, high {max(vals)}")
        else:
            D.text(cr, x0 + 8, top + 24, "Builds up as the panel reads Discord every 3 minutes.", 10, "static", "regular",
                   width=x1 - x0 - 16)
            self.region(x0, top, x1 - x0, bottom - top, "The online count over time, kept from each read this session")

    def _member_row(self, cr, m, x, y, cw, pic=False):
        col, words = STATUS.get(m["status"], ("static", m["status"]))
        tx = x + 12
        if pic:
            surf = K.picture(self.avatars.get(m.get("avatar")), (20, 20)) if self.avatars.get(m.get("avatar")) else None
            D.src(cr, "guard", 0.9)
            cr.arc(x + 10, y + 9, 10, 0, 6.283)
            cr.fill()
            if surf:
                cr.save()
                cr.arc(x + 10, y + 9, 10, 0, 6.283)
                cr.clip()
                K.draw_picture(cr, surf, x, y - 1, 20, 20)
                cr.restore()
            else:
                D.text(cr, x + 10, y + 2, m["name"][:1].upper(), 10, "soft", "bold", align="center")
            D.dot(cr, x + 17, y + 16, 3, col, glow=False)
            tx = x + 26
        else:
            D.dot(cr, x + 4, y + 8, 3, col, glow=False)
        D.text(cr, tx, y + 1, m["name"], 11, "soft", "medium", width=cw - (tx - x) - 4)
        self.region(x, y - 1, cw, 19, f"{m['name']}: {words}" + (f", playing {m['game']}" if m.get("game") else "")
                    + (", in a voice channel" if m.get("channel") else ""))

    def _members(self, cr, d, x0, x1, top, bottom, cols=1, pic=False):
        rows = d.get("list") or []
        if top + 14 > bottom:                     # no room even for its heading: left out
            return
        D.label(cr, x0, top, f"ONLINE NOW · {len(rows)}", "dim", size=10)
        if rows and top + 18 + 20 > bottom:       # room for the heading only: who, in its hover hint
            self.region(x0, top - 2, x1 - x0, 16, f"{len(rows)} online: " + ", ".join(m["name"] for m in rows[:30])
                        + (" and more" if len(rows) > 30 else "") + ". Make the panel taller to see them here.")
            return
        y0 = top + 18
        if not rows:
            msg = ("Set server = \"ID\" for names (the server's widget must be on)." if not d.get("widget")
                   else "Nobody's online.")
            D.text(cr, x0, y0, msg, 10, "static", "regular", width=x1 - x0, wrap=True)
            self.region(x0, top, x1 - x0, 36, "Who's online needs the server's widget: Server Settings › Widget › "
                        "Enable Server Widget, then server = \"ID\" in discord.toml")
            return
        cw = (x1 - x0 - (cols - 1) * 12) / cols
        per = max(1, int((bottom - y0) // 20))       # at least one row: there's room for it (above)
        for i, m in enumerate(rows[:per * cols]):
            self._member_row(cr, m, x0 + (i // per) * (cw + 12), y0 + (i % per) * 20, cw, pic)
        if len(rows) > per * cols:
            D.label(cr, x1, top, f"+{len(rows) - per * cols} MORE", "static", size=10, align="right")
            self.region(x1 - 90, top - 2, 90, 16, f"{len(rows) - per * cols} more online; make the panel bigger to see them")

    def _grid(self, cr, d, x0, x1, top, bottom):
        cols = max(1, int((x1 - x0) // 150))
        self._members(cr, d, x0, x1, top, bottom, cols=cols)

    def _voice(self, cr, d, x0, x1, top, bottom):
        voice = d.get("voice") or []
        if not voice:
            return top
        D.label(cr, x0, top, "VOICE", "dim", size=10)
        y = top + 18
        for c in voice:
            if y > bottom - 40:
                break
            D.text(cr, x0, y, "🔊 " + c["name"], 11, "soft" if c["who"] else "static", "semibold", width=(x1 - x0) * 0.45)
            D.text(cr, x0 + (x1 - x0) * 0.47, y + 1, ", ".join(c["who"]) or "empty", 10,
                   "phosphor" if c["who"] else "static", "regular", width=(x1 - x0) * 0.53)
            self.region(x0, y - 1, x1 - x0, 18, f"Voice channel {c['name']}: "
                        + (", ".join(c["who"]) + " in it" if c["who"] else "nobody in it"))
            y += 19
        return y + 4

    def _large(self, cr, d, x0, x1, top, h):
        split = x0 + (x1 - x0) * 0.46
        y = self._counts(cr, d, x0, split - 16, top, top + 150, big=48, icon=True)
        if d.get("description"):
            D.text(cr, x0, y, d["description"], 10, "static", "regular", width=split - x0 - 16)
            self.region(x0, y, split - x0 - 16, 16, f"The server's description: {d['description']}")
            y += 18
        gb = max(y + 90, top + (h - top) * 0.55)
        self._history(cr, x0, split - 16, y + 8, gb)
        self._voice(cr, d, x0, split - 16, gb + 12, h - 12)
        self._members(cr, d, split + 4, x1, top, h - 12, cols=2 if x1 - split > 360 else 1, pic=True)


PANEL = DiscordPanel
LAYOUT = {"visible": False}
