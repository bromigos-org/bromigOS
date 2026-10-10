"""YOUTUBE: a channel's latest videos and whether it's live, with no API key.

The videos come from the channel's public feed,
https://www.youtube.com/feeds/videos.xml?channel_id=<id> (its 15 newest, with views),
read every 15 minutes while the panel is seen. The feed doesn't say whether the channel
is live, so the panel also opens https://www.youtube.com/channel/<id>/live every 10
minutes: when the channel is live, that page's own address (its canonical link) is the
broadcast, and the page says it's live now. When the page can't tell, the panel says the
live status is unknown rather than guess.

Set the channel in ~/.config/bromigos/widgets/youtube.toml:

  channel = "UC…"          a channel ID, or "@handle" (looked up once, then remembered)
  shorts = false           leave Shorts out (they're in by default)

Click a video to open it. Large shows each video's picture.
"""
import json
import os
import re
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

sys.path.append(os.path.dirname(os.path.realpath(__file__)))   # after the standard library
import _kit as K  # noqa: E402

import draw as D  # noqa: E402

try:                              # lib/bromigos_youtube.py (yt-dlp's view of a channel, cached hourly), when there
    import bromigos_youtube as Y  # noqa: E402
except ImportError:
    Y = None

FEED = "https://www.youtube.com/feeds/videos.xml?channel_id={}"
FEED_EVERY, LIVE_EVERY = 900.0, 600.0
NS = {"a": "http://www.w3.org/2005/Atom", "yt": "http://www.youtube.com/xml/schemas/2015",
      "media": "http://search.yahoo.com/mrss/"}
UA = "Mozilla/5.0 (X11; Linux x86_64) bromigOS"


def parse_feed(xml_bytes):
    """The Atom feed as {"channel": {id, title, url}, "videos": [...]}, newest first."""
    root = ET.fromstring(xml_bytes)
    cid = root.findtext("yt:channelId", default="", namespaces=NS)
    if cid and not cid.startswith("UC"):
        cid = "UC" + cid
    url = next((ln.get("href") for ln in root.findall("a:link", NS) if ln.get("rel") == "alternate"), None)
    ch = {"id": cid, "title": root.findtext("a:title", default="", namespaces=NS) or
          root.findtext("a:author/a:name", default="", namespaces=NS), "url": url}
    videos = []
    for e in root.findall("a:entry", NS):
        vid = e.findtext("yt:videoId", default="", namespaces=NS)
        link = next((ln.get("href") for ln in e.findall("a:link", NS) if ln.get("rel") == "alternate"), None)
        g = e.find("media:group", NS)
        thumb = views = stars = None
        if g is not None:
            t = g.find("media:thumbnail", NS)
            thumb = t.get("url") if t is not None else None
            st = g.find("media:community/media:statistics", NS)
            views = int(st.get("views")) if st is not None and (st.get("views") or "").isdigit() else None
            r = g.find("media:community/media:starRating", NS)
            stars = int(r.get("count")) if r is not None and (r.get("count") or "").isdigit() else None
        videos.append({"id": vid, "title": e.findtext("a:title", default="", namespaces=NS),
                       "url": link or f"https://www.youtube.com/watch?v={vid}",
                       "published": K.iso_time(e.findtext("a:published", default="", namespaces=NS)),
                       "views": views, "likes": stars, "thumb": thumb or (f"https://i.ytimg.com/vi/{vid}/hqdefault.jpg"
                                                                         if vid else None),
                       "short": "/shorts/" in (link or "")})
    videos.sort(key=lambda v: -(v["published"] or 0))
    return {"channel": ch, "videos": videos}


def live_state(html):
    """From the start of a channel's /live page: {"state": "live" | "upcoming" | "offline" |
    "unknown", "video": id or None, "title": …}. Offline when the page is the channel
    itself; live only when the page names a video and says it's live now."""
    m = re.search(r'<link rel="canonical" href="([^"]+)"', html)
    if not m:
        return {"state": "unknown", "video": None, "title": None}
    canon = m.group(1)
    v = re.search(r"[?&]v=([\w-]{6,})", canon)
    if not v:
        return {"state": "offline", "video": None, "title": None}
    t = re.search(r'<meta name="title" content="([^"]*)"', html) or re.search(r'<title>([^<]*)</title>', html)
    title = _unescape(t.group(1)).removesuffix(" - YouTube") if t else None
    if re.search(r'"isLiveNow"\s*:\s*true', html) or re.search(r'"isLive"\s*:\s*true', html):
        return {"state": "live", "video": v.group(1), "title": title}
    if re.search(r'"isUpcoming"\s*:\s*true', html) or "upcomingEventData" in html:
        return {"state": "upcoming", "video": v.group(1), "title": title}
    return {"state": "unknown", "video": v.group(1), "title": title}


def _yt(name):
    """A function of bromigos_youtube, when the module and the function are there."""
    f = getattr(Y, name, None) if Y is not None else None
    return f if callable(f) else None


def from_ytdlp(it):
    """One of yt-dlp's entries (as bromigos_youtube gives them) as the panel's video record."""
    vid = it.get("id") or ""
    url = it.get("url") or it.get("webpage_url") or f"https://www.youtube.com/watch?v={vid}"
    if not str(url).startswith("http"):
        url = f"https://www.youtube.com/watch?v={vid}"
    when = it.get("timestamp") or it.get("release_timestamp")
    if not when and it.get("upload_date"):
        try:
            when = time.mktime(time.strptime(str(it["upload_date"]), "%Y%m%d"))
        except ValueError:
            when = None
    thumb = it.get("thumbnail")
    if not thumb and it.get("thumbnails"):
        thumb = (it["thumbnails"][-1] or {}).get("url")
    return {"id": vid, "title": it.get("title") or "", "url": url, "published": when,
            "views": it.get("view_count"), "likes": it.get("like_count"),
            "thumb": thumb or (f"https://i.ytimg.com/vi/{vid}/hqdefault.jpg" if vid else None),
            "short": "/shorts/" in url or (it.get("duration") or 999) <= 60,
            "duration": it.get("duration"), "live": it.get("live_status") or ("is_live" if it.get("is_live") else None)}


def live_from(value):
    """bromigos_youtube's live answer (a bool, or a dict with live/id/title) as live_state()'s shape."""
    if isinstance(value, dict):
        on = value.get("live", value.get("is_live"))
        return {"state": "live" if on else ("unknown" if on is None else "offline"),
                "video": value.get("id") or value.get("video"), "title": value.get("title")}
    if value is None:
        return {"state": "unknown", "video": None, "title": None}
    return {"state": "live" if value else "offline", "video": None, "title": None}


def _unescape(s):
    import html as H
    return H.unescape(s)


def channel_id_of(html):
    """A channel page's own ID, from its canonical link (or its metadata)."""
    m = re.search(r'<link rel="canonical" href="https://www\.youtube\.com/channel/(UC[\w-]{20,})"', html)
    if m:
        return m.group(1)
    m = re.search(r'"(?:externalId|channelId)"\s*:\s*"(UC[\w-]{20,})"', html)
    return m.group(1) if m else None


def _get_text(url, limit=1_600_000, until=None, timeout=15):
    """A page's text, read until `until` (a function of the text so far) says enough, or limit."""
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept-Language": "en"})
    out = b""
    with urllib.request.urlopen(req, timeout=timeout) as r:
        if "consent." in r.geturl():
            raise ValueError("YouTube asked for cookie consent first; live status unknown")
        while len(out) < limit:
            chunk = r.read(65536)
            if not chunk:
                break
            out += chunk
            if until and until(out.decode("utf-8", "replace")):
                break
    return out.decode("utf-8", "replace")


# ------------------------------------------------------------------ demo readings
def demo_data():
    now = time.time()
    rows = [("The lighthouse lens, rebuilt by hand", 2.1, 48210), ("Night shift: tide charts and tea", 26, 15302),
            ("How a fog bell is tuned", 74, 88104), ("Harbor Point, an hour of rain (no talking)", 120, 230511),
            ("Lamp oil, then and now", 196, 12007), ("Q&A: keeping a relay mast alive", 270, 9822),
            ("The longshore drift, explained with sand", 340, 51630), ("A short: the beam at 3 a.m.", 380, 4410),
            ("Repairing a brass clock movement", 460, 37298), ("Tidewatch, a week in timelapse", 560, 120443)]
    vids = [{"id": f"demo{i}", "title": t, "url": "https://www.youtube.com/", "published": now - hrs * 3600,
             "views": v, "likes": v // 31, "thumb": None, "short": "short:" in t.lower() or "a short" in t.lower()}
            for i, (t, hrs, v) in enumerate(rows)]
    return {"channel": {"id": "UCdemo", "title": "Keeper's Workshop", "url": "https://www.youtube.com/"},
            "videos": vids, "live": {"state": "live", "video": "demolive", "title": "Live from the lamp room: Q&A",
                                     "at": now}, "at": now}


def demo_picture(i, w, h):
    import cairo
    surf = cairo.ImageSurface(cairo.FORMAT_ARGB32, max(1, w), max(1, h))
    cr = cairo.Context(surf)
    hues = [(0.10, 0.18, 0.30), (0.25, 0.14, 0.08), (0.06, 0.22, 0.18), (0.20, 0.08, 0.22), (0.18, 0.20, 0.08)]
    r, g, b = hues[i % len(hues)]
    grad = cairo.LinearGradient(0, 0, 0, h)
    grad.add_color_stop_rgb(0, r * 1.8, g * 1.8, b * 1.8)
    grad.add_color_stop_rgb(1, r * 0.5, g * 0.5, b * 0.5)
    cr.set_source(grad)
    cr.paint()
    cr.set_source_rgba(1, 0.85, 0.5, 0.75)
    cr.arc(w * (0.25 + 0.12 * (i % 4)), h * 0.42, h * 0.16, 0, 6.283)
    cr.fill()
    cr.set_source_rgba(0, 0, 0, 0.35)
    cr.rectangle(0, h * 0.72, w, h * 0.28)
    cr.fill()
    return surf


# ------------------------------------------------------------------ the panel
class YoutubePanel(K.KitPanel):
    name, title = "youtube", "YOUTUBE"
    description = "A YouTube channel's latest videos, and whether it's live, with no account or key"
    category, reads = "media", "a channel's public YouTube feed"
    width, height = 460, 300
    interval = 10.0
    settings = [
        {"key": "channel", "label": "Channel", "kind": "text", "default": "",
         "hint": "A channel ID (UC…) or an @handle"},
        {"key": "shorts", "label": "Show Shorts", "kind": "bool", "default": True,
         "hint": "Include the channel's Shorts in the list"},
    ]
    sizes = {
        "compact": ((240, 120), (380, 190), (300, 140)),
        "standard": ((400, 240), (620, 420), (460, 300)),
        "wide": ((640, 200), (1100, 380), (780, 260)),
        "tall": ((380, 440), (560, 900), (420, 600)),
        "large": ((660, 480), (1200, 900), (800, 600)),
    }
    default_size = "standard"

    def __init__(self, cfg=None, wake=None):
        super().__init__(cfg, wake)
        self.demo = K.demo()                          # made-up readings, for pictures
        self.thumbs = {}                              # video id -> bytes (large only)
        self._th_busy = False
        if self.demo:
            self.data, self.feed, self.live = demo_data(), None, None
            return
        self.data = None
        self._cid = None                              # (setting, channel id) resolved
        self.feed = self.poller(self.fetch_feed, every=FEED_EVERY, name="feed")
        self.live = self.poller(self.fetch_live, every=LIVE_EVERY, name="live")

    # ---- data
    def _cache_path(self):
        return os.path.join(K.CACHE, "youtube-handles.json")

    def channel_id(self):
        """The configured channel's ID: a UC… ID as it is, an @handle looked up once and cached."""
        raw = str(self.conf.get("channel", "") or "").strip()
        if not raw:
            return None
        m = re.search(r"(UC[\w-]{20,})", raw)
        if m:
            return m.group(1)
        handle = raw if raw.startswith("@") else "@" + raw.rsplit("/", 1)[-1].lstrip("@")
        if self._cid and self._cid[0] == handle:
            return self._cid[1]
        try:
            with open(self._cache_path()) as f:
                cached = json.load(f).get(handle)
        except (OSError, ValueError):
            cached = None
        if not cached:
            html = _get_text("https://www.youtube.com/" + urllib.parse.quote(handle),
                             until=lambda t: channel_id_of(t) is not None)
            cached = channel_id_of(html)
            if not cached:
                raise ValueError(f"YouTube has no channel {handle}")
            try:
                os.makedirs(K.CACHE, exist_ok=True)
                try:
                    with open(self._cache_path()) as f:
                        doc = json.load(f)
                except (OSError, ValueError):
                    doc = {}
                doc[handle] = cached
                with open(self._cache_path(), "w") as f:
                    json.dump(doc, f)
            except OSError:
                pass
        self._cid = (handle, cached)
        return cached

    def fetch_feed(self):
        cid = self.channel_id()
        if not cid:
            return None
        videos = _yt("channel_videos")
        if videos:                                    # yt-dlp through bromigos_youtube; the feed if it fails
            try:
                items = videos(f"https://www.youtube.com/channel/{cid}", limit=15)
                vids = [from_ytdlp(it) for it in items or []]
                vids.sort(key=lambda v: -(v["published"] or 0))
                return {"channel": {"id": cid, "title": (self.feed.data or {}).get("channel", {}).get("title")
                                    if self.feed and self.feed.data else "", "url":
                                    f"https://www.youtube.com/channel/{cid}"}, "videos": vids, "at": time.time(),
                        "via": "yt-dlp"}
            except Exception:                         # noqa: BLE001  yt-dlp missing or failing: the public feed
                pass
        req = urllib.request.Request(FEED.format(cid), headers={"User-Agent": UA})
        try:
            with urllib.request.urlopen(req, timeout=15) as r:
                got = parse_feed(r.read(2_000_000))
        except urllib.error.HTTPError as e:
            if e.code == 404:
                raise ValueError("YouTube's feed answered 404 for this channel (a wrong ID, or the feed is down); "
                                 "it's tried again in 15 minutes")
            raise
        got["at"] = time.time()
        return got

    def fetch_live(self):
        cid = self.channel_id()
        if not cid:
            return None
        live_now = _yt("live_now")
        if live_now:
            try:
                st = live_from(live_now(f"https://www.youtube.com/channel/{cid}"))
                st["at"] = time.time()
                return st
            except Exception:                         # noqa: BLE001  the page check below instead
                pass
        html = _get_text(f"https://www.youtube.com/channel/{cid}/live",
                         until=lambda t: '<link rel="canonical"' in t and ("watch?v=" not in t.split(
                             '<link rel="canonical"', 1)[1][:120] or '"isLiveNow"' in t or '"isUpcoming"' in t))
        st = live_state(html)
        st["at"] = time.time()
        return st

    def snapshot(self):
        """{"channel", "videos", "live"} from the two pollers (or the demo)."""
        if self.demo:
            return self.data
        f = self.feed.data if self.feed else None
        lv = self.live.data if self.live else None
        if f is None and lv is None:
            return None
        out = dict(f or {"channel": {"id": self._cid[1] if self._cid else None, "title": "", "url": None}, "videos": []})
        out["live"] = lv or {"state": "unknown", "video": None, "title": None}
        if self.live and self.live.error and not lv:
            out["live"] = {"state": "unknown", "video": None, "title": None, "why": self.live.error}
        return out

    def videos(self, d):
        vids = d.get("videos") or []
        if not self.conf.get("shorts", True):
            vids = [v for v in vids if not v.get("short")]
        return vids

    def tick(self):
        if self.demo or self.last_class != "large" or time.monotonic() - self.drawn_at > 30 or self._th_busy:
            return
        d = self.snapshot()
        want = [v for v in self.videos(d or {})[:12] if v.get("thumb") and v["id"] not in self.thumbs]
        if not want:
            return
        self._th_busy = True

        def go(vs=want[:6]):
            for v in vs:
                try:
                    self.thumbs[v["id"]] = K.fetch_bytes(v["thumb"].replace("hqdefault", "mqdefault"), timeout=8)
                except OSError:
                    self.thumbs[v["id"]] = None
            self._th_busy = False
        threading.Thread(target=go, daemon=True, name="youtube-thumbs").start()

    # ---- drawing
    def draw(self, cr, w, h):
        cls = self.size_class(w, h)
        d = self.snapshot()
        ch = (d or {}).get("channel") or {}
        name = (ch.get("title") or "") if d else ""
        room = max(4, int((w - 150) // 10))
        top = D.frame(cr, w, h, self.title, (name if len(name) <= room else name[:room - 1] + "…") or None)
        chan_url = ch.get("url") or (f"https://www.youtube.com/channel/{ch['id']}" if ch.get("id") else None)
        self.region(0, 0, w, 34, "YouTube: a channel's latest videos from its public feed (every 15 minutes) and whether "
                    "it's live (every 10 minutes), while the panel is seen" + (". Click to open the channel." if chan_url
                                                                              else ""),
                    (lambda: K.open_url(chan_url)) if chan_url else None)
        if not self.demo and not str(self.conf.get("channel", "") or "").strip():
            self.empty(cr, w, h, top, "NO CHANNEL SET",
                       f"Put channel = \"@handle\" or channel = \"UC…\" (a channel ID) in "
                       f"{K.home_path(K.settings_path('youtube'))}.",
                       tip="The YouTube panel needs a channel: its @handle, or its ID (UC…, in the channel's "
                           "address or its About page). No account or key is needed.")
            return
        if d is None:
            err = (self.feed.error if self.feed else None) or (self.live.error if self.live else None)
            self.empty(cr, w, h, top, "NO ANSWER FROM YOUTUBE" if err else "READING YOUTUBE…", err or "",
                       color="amber" if err else "static")
            return
        x0, x1 = 16, w - 16
        vids = self.videos(d)
        if cls == "compact":
            y = self._live(cr, d, x0, x1, top, compact=True)
            if vids:
                v = vids[0]
                D.label(cr, x0, y + 2, f"LATEST · {K.ago(v['published']).upper()}", "dim", size=10)
                th = D.text(cr, x0, y + 18, v["title"], 12, "soft", "medium", width=x1 - x0)[1]
                self._video_tip(v, x0, y, x1 - x0, th + 20)
                yy = y + 22 + th
                for v2 in vids[1:]:
                    if yy + 18 > h - 8:
                        break
                    D.text(cr, x0, yy, K.ago(v2["published"]), 10, "static", "semibold", width=34)
                    D.text(cr, x0 + 40, yy - 1, v2["title"], 11, "soft", "regular", width=x1 - x0 - 40)
                    self._video_tip(v2, x0, yy - 2, x1 - x0, 18)
                    yy += 19
        elif cls == "wide":
            split = x0 + max(260, (x1 - x0) * 0.32)
            y = self._live(cr, d, x0, split - 16, top)
            self._views_chart(cr, vids, x0, split - 16, y + 8, h - 14)
            self._list(cr, vids, split, x1, top, h - 12, meta=True)
        elif cls == "tall":
            y = self._live(cr, d, x0, x1, top)
            y = self._views_chart(cr, vids, x0, x1, y + 6, y + 6 + max(70, (h - y) * 0.18))
            self._list(cr, vids, x0, x1, y + 10, h - 12, meta=True, two_lines=True)
        elif cls == "large":
            y = self._live(cr, d, x0, x1, top)
            self._grid(cr, vids, x0, x1, y + 8, h - 12)
        else:
            y = self._live(cr, d, x0, x1, top)
            self._list(cr, vids, x0, x1, y + 6, h - 12, meta=w >= 440)
        if self.feed and self.feed.error and d.get("videos"):
            D.label(cr, x1, h - 14, "FEED: LAST READ " + K.ago(d.get("at")).upper(), "amber", size=9, align="right")
            self.region(x1 - 180, h - 16, 180, 14, f"The last read of the feed failed ({self.feed.error}); these are "
                        f"from {K.ago(d.get('at'))} ago")

    def _live(self, cr, d, x0, x1, top, compact=False):
        """The live line. Returns the y under it."""
        lv = d.get("live") or {}
        st = lv.get("state", "unknown")
        col = {"live": "danger", "upcoming": "amber", "offline": "static"}.get(st, "static")
        label = {"live": "LIVE NOW", "upcoming": "LIVE SOON", "offline": "NOT LIVE"}.get(st, "LIVE: UNKNOWN")
        cw = self.chip(cr, x0, top, label, col, filled=st == "live")
        url = f"https://www.youtube.com/watch?v={lv['video']}" if lv.get("video") else None
        words = {"live": "The channel is live now", "upcoming": "The channel has a live stream scheduled",
                 "offline": "The channel isn't live",
                 "unknown": "Whether the channel is live is unknown: YouTube's page didn't say"
                            + (f" ({lv['why']})" if lv.get("why") else "")}[st if st in ("live", "upcoming", "offline")
                                                                           else "unknown"]
        if lv.get("title") and st in ("live", "upcoming"):
            D.text(cr, x0 + cw + 8, top - 1, lv["title"], 11, "soft", "medium", width=x1 - x0 - cw - 8)
        tip = words + (f": “{lv['title']}”" if lv.get("title") and st in ("live", "upcoming") else "") \
            + (f". Checked {K.ago(lv['at'])} ago, every 10 minutes." if lv.get("at") else ".") \
            + (" Click to watch." if url and st in ("live", "upcoming") else "")
        self.region(x0, top - 2, x1 - x0, 20, tip, (lambda: K.open_url(url)) if url and st in ("live", "upcoming") else None)
        y = top + 22
        if not compact:
            D.rule(cr, x0, y, x1)
            y += 6
        return y

    def _video_tip(self, v, x, y, w, h):
        bits = [f"“{v['title']}”", f"published {K.ago(v['published'])} ago"]
        if v.get("views") is not None:
            bits.append(f"{v['views']:,} views")
        if v.get("short"):
            bits.append("a Short")
        self.region(x, y, w, h, ", ".join(bits) + ". Click to open it on YouTube.", lambda u=v["url"]: K.open_url(u))

    def _list(self, cr, vids, x0, x1, top, bottom, meta=True, two_lines=False):
        D.label(cr, x0, top, f"LATEST VIDEOS · {len(vids)}", "dim", size=10)
        y = top + 18
        if not vids:
            D.text(cr, x0, y, "No videos in the feed.", 11, "static", "regular")
            self.region(x0, top, x1 - x0, 36, "The channel's feed has no videos (or Shorts are hidden in youtube.toml)")
            return
        rh = 36 if two_lines else 21
        room = max(1, int((bottom - y) // rh))
        for v in vids[:room]:
            right = K.short(v["views"]) + " VIEWS" if meta and v.get("views") is not None else ""
            rw = D.layout(cr, right, 10, "semibold", 0.18).get_pixel_size()[0] if right else 0
            ago = K.ago(v["published"])
            D.text(cr, x0, y + 1, ago, 10, "static", "semibold", width=34)
            if v.get("short"):
                self.chip(cr, x0 + 38, y, "S", "amber")
            tx = x0 + (58 if v.get("short") else 40)
            D.text(cr, tx, y, v["title"], 12, "soft", "medium", width=x1 - tx - rw - 10, wrap=False)
            if right:
                D.label(cr, x1, y + 1, right, "dim", size=10, align="right")
            if two_lines and v.get("likes") is not None:
                D.text(cr, tx, y + 17, f"{v['likes']:,} likes · " + time.strftime("%d %b %Y", time.localtime(
                    v["published"] or 0)), 10, "static", "regular")
            self._video_tip(v, x0, y - 2, x1 - x0, rh - 2)
            y += rh
        if len(vids) > room:
            D.label(cr, x1, top, f"+{len(vids) - room} MORE", "static", size=10, align="right")
            self.region(x1 - 90, top - 2, 90, 16, f"{len(vids) - room} more in the feed; make the panel taller")

    def _views_chart(self, cr, vids, x0, x1, top, bottom):
        """Views of the latest videos as bars, newest on the right. Returns the y under it."""
        vs = [v for v in vids[:12] if v.get("views") is not None][::-1]
        D.label(cr, x0, top, "VIEWS, LATEST VIDEOS" if x1 - x0 >= 320 else "VIEWS", "dim", size=10)
        gy, gh = top + 16, bottom - top - 18
        if not vs or gh < 20:
            return top + 18
        hi = max(v["views"] for v in vs) or 1
        bw = (x1 - x0) / len(vs)
        for i, v in enumerate(vs):
            bh = max(2, gh * v["views"] / hi)
            D.src(cr, "amber" if v.get("short") else "phosphor", 0.75)
            cr.rectangle(x0 + i * bw + 1, gy + gh - bh, max(1, bw - 3), bh)
            cr.fill()
            self.region(x0 + i * bw, gy, bw, gh, f"“{v['title']}”: {v['views']:,} views, published "
                        f"{K.ago(v['published'])} ago" + (" (a Short)" if v.get("short") else "") + ". Click to open it.",
                        lambda u=v["url"]: K.open_url(u))
        D.label(cr, x1, top, f"TOP {K.short(hi)}", "static", size=10, align="right")
        return bottom

    def _grid(self, cr, vids, x0, x1, top, bottom):
        if not vids:
            self._list(cr, vids, x0, x1, top, bottom)
            return
        gap = 14
        cols = max(2, min(4, int((x1 - x0 + gap) // 200)))
        cw = (x1 - x0 - (cols - 1) * gap) / cols
        ph = cw * 9 / 16
        ch = ph + 44
        rows = max(1, int((bottom - top + gap) // (ch + gap)))
        for i, v in enumerate(vids[:cols * rows]):
            cx = x0 + (i % cols) * (cw + gap)
            cy = top + (i // cols) * (ch + gap)
            D.src(cr, "void", 0.9)
            cr.rectangle(cx, cy, cw, ph)
            cr.fill()
            surf = demo_picture(i, int(cw), int(ph)) if self.demo else (
                K.picture(self.thumbs[v["id"]], (int(cw * 1.2), int(ph * 1.2))) if self.thumbs.get(v["id"]) else None)
            if not K.draw_picture(cr, surf, cx, cy, cw, ph):
                D.label(cr, cx + cw / 2, cy + ph / 2 - 7, "…", "static", align="center")
            if v.get("short"):
                self.chip(cr, cx + 6, cy + 6, "SHORT", "amber", filled=True)
            D.text(cr, cx, cy + ph + 5, v["title"], 11, "soft", "medium", width=cw, wrap=False)
            meta = K.ago(v["published"]) + " ago" + (f" · {K.short(v['views'])} views" if v.get("views") is not None else "")
            D.text(cr, cx, cy + ph + 22, meta, 10, "static", "regular", width=cw)
            self._video_tip(v, cx, cy, cw, ch - 4)
        if len(vids) > cols * rows:
            D.label(cr, x1, bottom - 12, f"+{len(vids) - cols * rows} MORE", "static", size=10, align="right")
            self.region(x1 - 90, bottom - 14, 90, 14, f"{len(vids) - cols * rows} more videos in the feed")


PANEL = YoutubePanel
LAYOUT = {"visible": False}
