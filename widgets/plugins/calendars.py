"""CALENDAR (the panel `calendars`: a file named calendar.py would hide Python's own
calendar module from everything once the plugins' folder is on the import path): today's events and the days ahead, from ICS calendars. No Google sign-in.

Each calendar is an ICS address (https://…, or webcal://…, which is read over https: a
CalDAV server's export link, a shared calendar's "secret address"), a local .ics file, or
a folder of .ics files (vdirsyncer's layout, one event per file). They're parsed with
python-icalendar, and repeating events (RRULE, RDATE, EXDATE, moved instances) are
expanded with dateutil. Times show in local time. All-day events, time zones, UTC and
floating times are handled.

Addresses are fetched every 15 minutes while the panel is seen (with ETag and
Last-Modified, so an unchanged calendar costs one short answer); local files are read
again when they change. Settings: ~/.config/bromigos/widgets/calendars.toml.

Your media server's releases (`media = true`, with bromigos-homelab and a Sonarr or Radarr
source in homelab.toml): new episodes of the shows you track ("TV") and your tracked films'
home releases ("Movies"), from Sonarr's and Radarr's own calendar feeds. They're read
through `bromigos lab media calendar tv|movies`, so their API keys stay in the lab's
config and never reach this panel's settings. A ✓ marks what's already downloaded.
"""
import datetime as dt
import hashlib
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request

sys.path.append(os.path.dirname(os.path.realpath(__file__)))   # after the standard library
import _kit as K  # noqa: E402

import draw as D  # noqa: E402

FETCH_EVERY = 900               # an address: every 15 minutes
CHECK_EVERY = 60                # local files: their mtimes, every minute
AHEAD_DAYS = 31                 # how far ahead to look (the next event's countdown)
BEHIND_DAYS = 7                 # and behind (a week grid that starts on Monday)
COLOURS = ("phosphor", "cyan", "amber", "soft", "danger", "dim")


def icalendar_module():
    try:
        import icalendar
        return icalendar
    except ImportError:
        return None


def tzlocal():
    from dateutil import tz
    return tz.tzlocal()


# ------------------------------------------------------------------ the calendars in the settings
def calendars_of(raw):
    """The `calendars` setting as [{source, name, colour}]: a list of strings, or of tables
    with source (or url/path), name and colour."""
    if isinstance(raw, (str, dict)):
        raw = [raw]
    out = []
    for i, c in enumerate(raw or []):
        if isinstance(c, str):
            c = {"source": c}
        if not isinstance(c, dict):
            continue
        src = str(c.get("source") or c.get("url") or c.get("path") or "").strip()
        if not src:
            continue
        name = c.get("name") or default_name(src)
        out.append({"source": src, "name": str(name), "colour": str(c.get("colour") or c.get("color") or
                                                                    COLOURS[i % len(COLOURS)])})
    return out


def default_name(src):
    if is_url(src):
        from urllib.parse import urlparse
        u = urlparse(src)
        stem = os.path.splitext(os.path.basename(u.path.rstrip("/")))[0]
        return stem if stem and len(stem) < 24 and not re.fullmatch(r"[0-9a-f\-]{16,}", stem) else u.hostname or "calendar"
    return os.path.splitext(os.path.basename(os.path.expanduser(src).rstrip("/")))[0] or "calendar"


def is_url(src):
    return src.startswith(("http://", "https://", "webcal://", "webcals://"))


# ------------------------------------------------------------------ the lab's media releases
MEDIA = (("lab:tv", "TV", "cyan"), ("lab:movies", "Movies", "amber"))


def is_lab(src):
    return src in ("lab:tv", "lab:movies")


def _lab_bin():
    return next((p for p in (os.environ.get("BROMIGOS_LAB_BIN"), "/usr/lib/bromigos/bin/bromigos-lab",
                             shutil.which("bromigos-lab")) if p and os.path.exists(p)), None)


def lab_fetch(src, past=BEHIND_DAYS, future=AHEAD_DAYS):
    """The ICS of the lab's Sonarr (lab:tv) or Radarr (lab:movies), through bromigos lab."""
    exe = _lab_bin()
    if not exe:
        raise RuntimeError("needs bromigos-homelab (bromigos lab) with a Sonarr or Radarr source")
    r = subprocess.run([exe, "media", "calendar", src.split(":", 1)[1], "--past", str(past), "--future", str(future)],
                       capture_output=True, timeout=60, stdin=subprocess.DEVNULL)
    if r.returncode != 0 or not r.stdout.lstrip().startswith(b"BEGIN:VCALENDAR"):
        why = (r.stderr or b"").decode("utf-8", "replace").strip().splitlines()
        raise RuntimeError(why[-1][:160] if why else "bromigos lab media calendar didn't answer")
    return r.stdout


_EP = re.compile(r"^(.*?) - (\d+)x(\d+)(?: - (.*))?$")
_MOVIE = re.compile(r"^(.*?) \((Theatrical|Cinema|Digital|Physical) Release\)$")


def media_event(e, src):
    """A Sonarr or Radarr feed's event in the panel's words, or None to leave it out:
    "Show S02E05 · Title" at its air time, a film on its digital or disc release day (the
    cinema date is left out: the home release is what gets downloaded), and ✓ when it's on
    disk (the feed's STATUS:CONFIRMED)."""
    done = (e.get("status") or "").upper() == "CONFIRMED"
    title = e["title"]
    if src == "lab:tv":
        m = _EP.match(title)
        if m:
            title = f"{m.group(1)} S{int(m.group(2)):02d}E{int(m.group(3)):02d}" + (f" · {m.group(4)}" if m.group(4) else "")
    else:
        m = _MOVIE.match(title)
        if m:
            if m.group(2) in ("Theatrical", "Cinema"):
                return None
            title = f"{m.group(1)} · {m.group(2).lower()} release"
    return dict(e, title=("✓ " if done else "") + title, downloaded=done)


def media_calendars(conf):
    """[media] on: the lab's TV and Movies feeds as calendars (colours from media_colours)."""
    if not conf.get("media"):
        return []
    cols = conf.get("media_colours") or {}
    return [{"source": src, "name": name, "colour": str(cols.get(name.lower()) or col)} for src, name, col in MEDIA]


def https_url(src):
    return re.sub(r"^webcals?://", "https://", src)


# ------------------------------------------------------------------ parsing and recurrence
def _epoch(v, tz):
    """Seconds since the epoch of a date or datetime (floating times and dates: local)."""
    if isinstance(v, dt.datetime):
        if v.tzinfo is None:
            v = v.replace(tzinfo=tz)
        return v.timestamp()
    return dt.datetime.combine(v, dt.time(), tzinfo=tz).timestamp()


def _like(v, base, tz):
    """v (a date or datetime) in base's kind: naive local for a naive base, aware for an aware one."""
    if not isinstance(v, dt.datetime):
        v = dt.datetime.combine(v, dt.time())
    if base.tzinfo is None:
        return v.astimezone(tz).replace(tzinfo=None) if v.tzinfo else v
    return v.replace(tzinfo=base.tzinfo) if v.tzinfo is None else v


def _fix_until(rule, base, tz):
    """dateutil wants UNTIL in UTC when DTSTART has a zone, and without one when it hasn't;
    calendars in the wild get this wrong both ways. Rewrite UNTIL to match base."""
    m = re.search(r"UNTIL=(\d{8})(T(\d{6}))?(Z)?", rule)
    if not m:
        return rule
    day = dt.datetime.strptime(m.group(1), "%Y%m%d")
    if m.group(3):
        until = day.replace(hour=int(m.group(3)[:2]), minute=int(m.group(3)[2:4]), second=int(m.group(3)[4:6]))
    else:
        until = day.replace(hour=23, minute=59, second=59)
    if m.group(4):
        until = until.replace(tzinfo=dt.timezone.utc)
    if base.tzinfo is None:
        new = (until.astimezone(tz).replace(tzinfo=None) if until.tzinfo else until).strftime("%Y%m%dT%H%M%S")
    else:
        if until.tzinfo is None:
            until = until.replace(tzinfo=base.tzinfo)
        new = until.astimezone(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return rule[:m.start()] + "UNTIL=" + new + rule[m.end():]


def _dates(prop):
    """The dates in an EXDATE/RDATE property, or a list of them."""
    if prop is None:
        return []
    props = prop if isinstance(prop, list) else [prop]
    out = []
    for p in props:
        for d in getattr(p, "dts", []) or []:
            out.append(d.dt)
    return out


def _text(comp, key):
    v = comp.get(key)
    return str(v).strip() if v is not None else ""


def parse(data, cal=None, lo=None, hi=None, tz=None):
    """The events of one ICS document between lo and hi (seconds since the epoch), each
    {uid, title, start, end, all_day, location, description, url, cal, colour}, sorted."""
    ical = icalendar_module()
    if ical is None:
        raise ImportError("python-icalendar isn't installed")
    from dateutil import rrule as R
    tz = tz or tzlocal()
    cal = cal or {"name": "calendar", "colour": "phosphor"}
    now = time.time()
    lo = now - BEHIND_DAYS * 86400 if lo is None else lo
    hi = now + AHEAD_DAYS * 86400 if hi is None else hi
    doc = ical.Calendar.from_ical(data)
    vevents = [c for c in doc.walk("VEVENT")]
    moved = set()                                   # (uid, start) of instances a RECURRENCE-ID replaces
    for c in vevents:
        rid = c.get("recurrence-id")
        if rid is not None:
            moved.add((_text(c, "uid"), round(_epoch(rid.dt, tz))))
    out = []
    for c in vevents:
        if _text(c, "status").upper() == "CANCELLED" or c.get("dtstart") is None:
            continue
        start = c.get("dtstart").dt
        all_day = not isinstance(start, dt.datetime)
        if c.get("dtend") is not None:
            end = c.get("dtend").dt
            dur = (_epoch(end, tz) - _epoch(start, tz))
        elif c.get("duration") is not None:
            dur = c.get("duration").dt.total_seconds()
        else:
            dur = 86400.0 if all_day else 0.0
        dur = max(0.0, dur)
        uid = _text(c, "uid")
        base = dt.datetime.combine(start, dt.time()) if all_day else start
        rule = c.get("rrule")
        recurring = rule is not None and c.get("recurrence-id") is None
        starts = []
        if recurring:
            rs = R.rruleset()
            text = rule.to_ical().decode()
            try:
                rs.rrule(R.rrulestr(text, dtstart=base))
            except ValueError:
                rs.rrule(R.rrulestr(_fix_until(text, base, tz), dtstart=base))
            for d in _dates(c.get("rdate")):
                rs.rdate(_like(d, base, tz))
            for d in _dates(c.get("exdate")):
                rs.exdate(_like(d, base, tz))
            a = dt.datetime.fromtimestamp(lo - dur, tz)
            b = dt.datetime.fromtimestamp(hi, tz)
            if base.tzinfo is None:
                a, b = a.replace(tzinfo=None), b.replace(tzinfo=None)
            starts = rs.between(a, b, inc=True)
        else:
            starts = [base] + [_like(d, base, tz) for d in _dates(c.get("rdate"))]
        for s in starts:
            t0 = _epoch(s, tz)
            if recurring and (uid, round(t0)) in moved:
                continue
            t1 = t0 + dur if dur else t0
            if t1 < lo or t0 > hi:
                continue
            out.append({"uid": uid, "title": _text(c, "summary") or "(no title)", "start": t0, "end": t1,
                        "all_day": all_day, "location": _text(c, "location"), "description": _text(c, "description"),
                        "url": _text(c, "url"), "cal": cal["name"], "colour": cal["colour"],
                        "status": _text(c, "status")})
    out.sort(key=lambda e: (e["start"], not e["all_day"], e["title"]))
    return out


def link_of(e):
    """A web address to open for an event: its location when that's one, else its URL, else
    a meeting link in its description."""
    for s in (e.get("location"), e.get("url")):
        if s and re.match(r"https?://", s.strip()):
            return s.strip()
    m = re.search(r"https?://[^\s<>\"]+", e.get("description") or "")
    return m.group(0) if m and re.search(r"meet|zoom|teams|jitsi|whereby|webex", m.group(0)) else None


def when(e, tz=None):
    """'14:00–15:30', 'all day', 'all day, 3 days'."""
    if e["all_day"]:
        days = max(1, round((e["end"] - e["start"]) / 86400))
        return "all day" + (f", {days} days" if days > 1 else "")
    a, b = K.clock(e["start"]), K.clock(e["end"])
    return a if a == b else f"{a}–{b}"


def day_of(t):
    return dt.date.fromtimestamp(t)


def countdown(e, now=None):
    now = now or time.time()
    if e["start"] <= now < e["end"]:
        return "now · ends in " + _span(e["end"] - now)
    if e["start"] > now:
        return "in " + _span(e["start"] - now)
    return "ended"


def _span(s):
    s = int(s)
    d, r = divmod(s, 86400)
    h, r = divmod(r, 3600)
    m = r // 60
    if d:
        return f"{d}d {h}h"
    if h:
        return f"{h}h {m:02d}m"
    return f"{max(1, m)}m"


# ------------------------------------------------------------------ reading the sources
class Sources:
    """Reads each calendar when it changed (files) or every 15 min (addresses), keeping
    each one's parsed events; events() is all of them, for now's window."""

    def __init__(self):
        self.state = {}            # source -> {sig, etag, modified, fetched, error, events, day}

    def cache_file(self, src):
        return os.path.join(K.CACHE, "calendar", hashlib.sha1(src.encode()).hexdigest()[:16] + ".ics")

    def _fetch(self, src, st):
        url = https_url(src)
        h = {"User-Agent": "bromigOS", "Accept": "text/calendar, */*"}
        if st.get("etag"):
            h["If-None-Match"] = st["etag"]
        if st.get("modified"):
            h["If-Modified-Since"] = st["modified"]
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=h), timeout=20) as r:
                body = r.read(16 << 20)
                st["etag"], st["modified"] = r.headers.get("ETag"), r.headers.get("Last-Modified")
        except urllib.error.HTTPError as e:
            if e.code == 304:
                return None
            raise
        path = self.cache_file(src)
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "wb") as f:
                f.write(body)
        except OSError:
            pass
        return body

    @staticmethod
    def _local(src):
        """(signature, [bytes]) of a file or a folder of .ics files."""
        p = os.path.expanduser(src)
        if os.path.isdir(p):
            files = sorted(os.path.join(p, f) for f in os.listdir(p) if f.endswith(".ics"))
            sig = tuple((f, os.path.getmtime(f)) for f in files)
            return sig, files
        return (p, os.path.getmtime(p)), [p]

    def refresh(self, cals, force=False):
        now = time.time()
        today = dt.date.today()
        for c in cals:
            src = c["source"]
            st = self.state.setdefault(src, {"events": [], "error": None, "fetched": 0, "day": None, "data": None})
            try:
                changed = False
                if is_lab(src):
                    if force or now - st["fetched"] >= FETCH_EVERY or st["data"] is None:
                        st["data"] = [lab_fetch(src)]
                        st["fetched"] = now
                        changed = True
                elif is_url(src):
                    if force or now - st["fetched"] >= FETCH_EVERY or st["data"] is None:
                        if st["data"] is None and os.path.exists(self.cache_file(src)):
                            with open(self.cache_file(src), "rb") as f:     # last copy, while offline
                                st["data"] = [f.read()]
                            changed = True
                        body = self._fetch(src, st)
                        st["fetched"] = now
                        if body is not None:
                            st["data"] = [body]
                            changed = True
                else:
                    sig, files = self._local(src)
                    if sig != st.get("sig"):
                        st["sig"] = sig
                        datas = []
                        for f in files:
                            with open(f, "rb") as fh:
                                datas.append(fh.read())
                        st["data"] = datas
                        changed = True
                if changed or st["day"] != today or c.get("colour") != st.get("colour"):
                    evs = []
                    for d in st["data"] or []:
                        evs += parse(d, c)
                    if is_lab(src):
                        evs = [x for x in (media_event(e, src) for e in evs) if x]
                    st["events"], st["day"], st["colour"] = evs, today, c.get("colour")
                st["error"] = None
            except FileNotFoundError:
                st["error"], st["events"] = f"no file or folder {K.home_path(os.path.expanduser(src))}", []
            except ImportError as e:
                raise e
            except Exception as e:                     # noqa: BLE001  one bad calendar never hides the rest
                st["error"] = K._words(e)
        for gone in set(self.state) - {c["source"] for c in cals}:
            self.state.pop(gone)
        events = sorted((e for s in self.state.values() for e in s["events"]),
                        key=lambda e: (e["start"], not e["all_day"]))
        errors = {src: s["error"] for src, s in self.state.items() if s["error"]}
        return {"events": events, "errors": errors, "at": now}


# ------------------------------------------------------------------ demo readings
def demo_events(now=None):
    now = now or time.time()
    day = dt.datetime.combine(dt.date.today(), dt.time()).timestamp()
    H = 3600
    rows = [  # (day offset, start hour, hours, title, calendar, colour, location, description)
        (0, 9.0, 0.5, "Stand-up", "Work", "cyan", "https://meet.example.org/standup", "Daily, fifteen minutes."),
        (0, 11.5, 1.0, "Design review: panels", "Work", "cyan", "Room 2", "Size classes and the gallery."),
        (0, 13.0, 1.0, "Lunch with Mara", "Home", "phosphor", "Harbor Point café", ""),
        (0, 16.0, 1.5, "Relay firmware pairing", "Work", "cyan", "", "Bring the bench supply."),
        (0, 19.5, 2.0, "Climbing", "Home", "phosphor", "North wall gym", ""),
        (1, 10.0, 1.0, "Dentist", "Home", "phosphor", "Main St clinic", ""),
        (1, 14.0, 2.0, "Planning", "Work", "cyan", "", "Next quarter's roadmap."),
        (2, 9.0, 0.5, "Stand-up", "Work", "cyan", "https://meet.example.org/standup", ""),
        (2, 18.0, 3.0, "Board games", "Friends", "amber", "Tobias's place", ""),
        (3, 8.0, 1.0, "Run", "Home", "phosphor", "Seafront", ""),
        (3, 15.0, 1.0, "1:1 with Ana", "Work", "cyan", "", ""),
        (4, 9.0, 0.5, "Stand-up", "Work", "cyan", "https://meet.example.org/standup", ""),
        (4, 12.0, 2.0, "Release v0.2", "Work", "cyan", "", "Tag, notes, ISO."),
        (5, 11.0, 4.0, "Sailing", "Friends", "amber", "Marina", ""),
        (6, 17.0, 2.0, "Family dinner", "Home", "phosphor", "", ""),
    ]
    # today's sit around the time the picture is drawn: some past, one on now, some ahead
    hour = (now - day) / H
    shift = {9.0: -3.0, 11.5: -1.5, 13.0: -0.25, 16.0: 1.0, 19.5: 2.5}
    out = []
    for d, s, hrs, title, cal, col, loc, desc in rows:
        t0 = day + d * 86400 + s * H
        if d == 0:
            t0 = day + max(0.0, min(24 - hrs, round((hour + shift[s]) * 4) / 4)) * H
        out.append({"uid": f"demo-{d}-{s}", "title": title, "start": t0, "end": t0 + hrs * H, "all_day": False,
                    "location": loc, "description": desc, "url": "", "cal": cal, "colour": col})
    for d, n, title, cal, col in ((0, 1, "Ana's birthday", "Friends", "amber"), (2, 3, "Conference", "Work", "cyan")):
        t0 = day + d * 86400
        out.append({"uid": f"demo-ad-{d}", "title": title, "start": t0, "end": t0 + n * 86400, "all_day": True,
                    "location": "", "description": "", "url": "", "cal": cal, "colour": col})
    out.sort(key=lambda e: (e["start"], not e["all_day"]))
    return out


# ------------------------------------------------------------------ the panel
class CalendarPanel(K.KitPanel):
    name, title = "calendars", "CALENDAR"
    description = "Today's events and the days ahead, from ICS calendars: an address, a file or a folder"
    category, reads = "notes", "your ICS calendars (addresses, files, vdirsyncer folders)"
    width, height = 440, 300
    interval = 30.0                     # the clock and countdown; reading is the poller's
    sizes = {
        "compact": ((240, 110), (400, 180), (300, 130)),
        "standard": ((380, 240), (600, 460), (440, 300)),
        "wide": ((640, 200), (1300, 420), (820, 260)),
        "tall": ((340, 470), (560, 1000), (400, 620)),
        "large": ((680, 460), (1400, 1000), (900, 600)),
    }
    default_size = "standard"
    settings = [
        {"key": "calendars", "label": "Calendars", "kind": "list", "default": [],
         "hint": "One per line: an ICS address (https:// or webcal://), an .ics file, or a folder of .ics files"},
        {"key": "week_start", "label": "Large: the week starts", "kind": "choice", "default": "today",
         "choices": ["today", "monday", "sunday"]},
        {"key": "media", "label": "Your media server's releases", "kind": "bool", "default": False,
         "hint": "New episodes of the shows you track (TV) and your films' home releases (Movies), from your lab's "
                 "Sonarr and Radarr. Needs bromigos-homelab with a Sonarr or Radarr source; ✓ marks what's downloaded"},
    ]

    def __init__(self, cfg=None, wake=None):
        super().__init__(cfg, wake)
        self.src = Sources()
        self.offset = 0
        if K.demo():
            self.data = {"events": demo_events(), "errors": {}, "at": time.time()}
            self.poll = None
        else:
            self.data = None
            self.poll = self.poller(self.fetch, every=CHECK_EVERY, idle=120)

    def cals(self):
        return calendars_of(self.conf.get("calendars", [])) + media_calendars(self.conf)

    def fetch(self):
        cals = self.cals()
        if not cals:
            return None
        if icalendar_module() is None:
            return {"missing": True}
        return self.src.refresh(cals)

    def settings_changed(self):
        self.src = Sources()
        super().settings_changed()

    def scroll(self, dy):
        self.offset = max(0, self.offset + int(dy) * 2)

    # ---- drawing
    def draw(self, cr, w, h):
        cls = self.size_class(w, h)
        data = self.data if self.poll is None else self.poll.data
        cals = self.cals() if self.poll is not None else [{"name": "demo"}]
        evs = (data or {}).get("events") or []
        now = time.time()
        today = dt.date.today()
        right = today.strftime("%a %d %b").upper() if cls != "compact" else today.strftime("%a %d").upper()
        top = D.frame(cr, w, h, self.title, right)
        names = ", ".join(c["name"] for c in cals) if self.poll is not None else "made-up events"
        self.region(0, 0, w, 34, f"Your calendars ({names}): addresses are fetched every 15 minutes while this "
                    f"panel is seen, files when they change. Today is {today.strftime('%A %d %B')}. "
                    f"Settings: {K.home_path(K.settings_path(self.name))}.")
        if not cals:
            self.empty(cr, w, h, top, "NO CALENDARS SET",
                       f"Add them to {K.home_path(K.settings_path(self.name))}: calendars = [\"https://…/basic.ics\", "
                       "\"~/calendars/home\"]. An address can be webcal:// or a CalDAV server's export link; a folder "
                       "holds .ics files.")
            return
        if data and data.get("missing"):
            self.empty(cr, w, h, top, "PYTHON-ICALENDAR IS MISSING",
                       "Reading ICS needs python-icalendar: sudo pacman -S python-icalendar",
                       tip="The calendar panel parses ICS with python-icalendar, which isn't installed")
            return
        if data is None:
            D.label(cr, 16, top + 6, "READING…", "static")
            self.region(0, top, w, h - top, "Reading your calendars for the first time")
            return
        errs = data.get("errors") or {}
        if errs and not evs:
            src, err = next(iter(errs.items()))
            self.empty(cr, w, h, top, "CALENDAR UNREADABLE", f"{default_name(src)}: {err}",
                       tip="; ".join(f"{default_name(s)}: {e}" for s, e in errs.items()))
            return
        if errs:
            D.label(cr, w - 16, h - 18, f"{len(errs)} UNREADABLE", "amber", size=10, align="right")
            self.region(w - 140, h - 20, 124, 16, "Not read: " + "; ".join(f"{default_name(s)}: {e}"
                                                                         for s, e in errs.items()))
        x0, x1 = 16, w - 16
        if cls == "compact":
            self._compact(cr, evs, x0, x1, top, h, now)
        elif cls == "wide":
            self._strip(cr, evs, x0, x1, top, h - 12, now, days=max(3, min(5, int((x1 - x0) // 200))))
        elif cls == "tall":
            self._agenda(cr, evs, x0, x1, top, h - 14, now, days=7)
        elif cls == "large":
            self._week(cr, evs, x0, x1, top, h - 12, now)
        else:
            self._standard(cr, evs, x0, x1, top, h - 12, now)

    def _tip(self, e):
        bits = [f"{e['title']}: {day_of(e['start']).strftime('%A %d %B')}, {when(e)}"]
        if e.get("location"):
            bits.append(f"at {e['location']}")
        bits.append(f"({e['cal']} calendar)")
        tip = " ".join(bits)
        if e.get("description"):
            tip += ". " + e["description"][:400]
        link = link_of(e)
        if link:
            tip += f". Click to open {link}"
        return tip

    def _event_region(self, x, y, w, h, e):
        link = link_of(e)
        self.region(x, y, w, h, self._tip(e), (lambda u=link: K.open_url(u)) if link else None)

    def _upcoming(self, evs, now):
        return [e for e in evs if e["end"] > now and not (e["all_day"] and day_of(e["start"]) < dt.date.today()
                                                          and e["end"] <= now)]

    def _compact(self, cr, evs, x0, x1, top, h, now):
        nxt = next((e for e in self._upcoming(evs, now) if not e["all_day"]), None)
        if nxt is None:
            D.label(cr, x0, top + 6, "NOTHING AHEAD", "static")
            D.text(cr, x0, top + 26, f"No events in the next {AHEAD_DAYS} days.", 11, "soft", "regular", width=x1 - x0)
            self.region(0, top, x1 + 16, h - top, f"No timed events in the next {AHEAD_DAYS} days")
            return
        live = nxt["start"] <= now
        col = "amber" if live else "phosphor"
        D.dot(cr, x0 + 4, top + 9, 4, nxt["colour"], glow=live and K.motion() == "full")
        D.text(cr, x0 + 16, top, nxt["title"], 15 if h > 140 else 13, "soft", "semibold", width=x1 - x0 - 16)
        D.label(cr, x0 + 16, top + 26, countdown(nxt, now), col, size=11)
        day = day_of(nxt["start"])
        dname = "today" if day == dt.date.today() else day.strftime("%a %d")
        if h >= 130:
            D.text(cr, x0 + 16, top + 46, f"{dname} {when(nxt)}" + (f" · {nxt['location']}" if nxt.get("location")
                                                                     else ""), 11, "static", "regular", width=x1 - x0 - 16)
        self._event_region(x0, top - 4, x1 - x0, min(64, h - top), nxt)
        later = [e for e in self._upcoming(evs, now) if e is not nxt and not e["all_day"]]
        if h > 150 and later:
            e = later[0]
            D.text(cr, x0 + 16, top + 70, f"then {K.clock(e['start'])} {e['title']}", 10, "static", "regular",
                   width=x1 - x0 - 16)
            self._event_region(x0, top + 68, x1 - x0, 16, e)

    def _row(self, cr, e, x0, x1, y, now, show_day=False, rowh=22):
        past = e["end"] <= now
        live = e["start"] <= now < e["end"]
        D.src(cr, e["colour"], 0.9 if not past else 0.35)
        cr.rectangle(x0, y + 3, 3, rowh - 6)
        cr.fill()
        if live:
            D.src(cr, e["colour"], 0.12)
            cr.rectangle(x0, y, x1 - x0, rowh - 1)
            cr.fill()
        tcol = "static" if past else ("amber" if live else "soft")
        tw = 92 if show_day else 84
        label = ("all day" if e["all_day"] else K.clock(e["start"]))
        if show_day:
            label = day_of(e["start"]).strftime("%a ") + label
        D.text(cr, x0 + 10, y + 3, label, 11, tcol, "medium", width=tw)
        D.text(cr, x0 + 10 + tw, y + 2, e["title"], 12, "static" if past else "soft", "semibold" if live else "medium",
               width=max(10, x1 - x0 - tw - 16))
        self._event_region(x0, y, x1 - x0, rowh - 1, e)

    def _standard(self, cr, evs, x0, x1, top, bottom, now):
        today = dt.date.today()
        todays = [e for e in evs if day_of(e["start"]) <= today < day_of(e["end"] - 1) + dt.timedelta(days=1)
                  and (e["start"] < now + 86400)]
        todays = [e for e in todays if day_of(e["start"]) == today or e["all_day"]]
        y = top
        D.label(cr, x0, y, f"TODAY · {len(todays)}", "phosphor", size=10)
        D.rule(cr, x0 + 100, y + 7, x1, "dim", 0.3)
        y += 18
        room = int((bottom - y) // 22)
        later = [e for e in evs if day_of(e["start"]) > today]
        show_today = todays[:max(1, room - min(3, len(later)) - 1)] if later else todays[:room]
        if not todays:
            D.text(cr, x0, y + 2, "Nothing today.", 11, "static", "regular")
            self.region(x0, y, x1 - x0, 20, "No events today")
            y += 22
        for e in show_today:
            self._row(cr, e, x0, x1, y, now)
            y += 22
        if len(todays) > len(show_today):
            D.label(cr, x1, y - 2, f"+{len(todays) - len(show_today)} MORE TODAY", "static", size=10, align="right")
            self.region(x1 - 160, y - 4, 160, 16, "More events today: make the panel taller, or tall, to see them")
            y += 14
        if later and y + 40 < bottom:
            y += 4
            D.label(cr, x0, y, "NEXT", "phosphor", size=10)
            D.rule(cr, x0 + 50, y + 7, x1, "dim", 0.3)
            y += 18
            for e in later[:int((bottom - y) // 22)]:
                self._row(cr, e, x0, x1, y, now, show_day=True)
                y += 22

    def _days(self, evs, start, n):
        out = []
        for i in range(n):
            d = start + dt.timedelta(days=i)
            a = dt.datetime.combine(d, dt.time()).timestamp()
            b = a + 86400
            out.append((d, [e for e in evs if e["start"] < b and (e["end"] > a or e["start"] >= a)]))
        return out

    def _dayname(self, d):
        today = dt.date.today()
        return "TODAY" if d == today else "TOMORROW" if d == today + dt.timedelta(days=1) else d.strftime("%a %d").upper()

    def _strip(self, cr, evs, x0, x1, top, bottom, now, days):
        cols = self._days(evs, dt.date.today(), days)
        gap = 10
        cw = (x1 - x0 - gap * (days - 1)) / days
        for i, (d, items) in enumerate(cols):
            cx = x0 + i * (cw + gap)
            D.src(cr, "guard", 0.35 if i else 0.6)
            cr.rectangle(cx, top - 2, cw, bottom - top + 2)
            cr.fill()
            D.label(cr, cx + 8, top + 2, self._dayname(d), "phosphor" if i == 0 else "dim", size=10)
            D.label(cr, cx + cw - 8, top + 2, str(len(items)), "static", size=10, align="right")
            self.region(cx, top - 2, cw, 18, f"{d.strftime('%A %d %B')}: {len(items)} event(s)")
            y = top + 22
            rowh = 34
            for e in items:
                if y + rowh > bottom:
                    D.label(cr, cx + cw - 8, bottom - 14, f"+{len(items) - items.index(e)}", "static", size=10,
                            align="right")
                    self.region(cx, bottom - 16, cw, 16, f"{len(items) - items.index(e)} more on {d.strftime('%A')}")
                    break
                past = e["end"] <= now
                live = e["start"] <= now < e["end"]
                D.src(cr, e["colour"], 0.18 if not past else 0.07)
                cr.rectangle(cx + 6, y, cw - 12, rowh - 4)
                cr.fill()
                D.src(cr, e["colour"], 0.95 if not past else 0.4)
                cr.rectangle(cx + 6, y, 3, rowh - 4)
                cr.fill()
                D.text(cr, cx + 14, y + 2, when(e), 10, "amber" if live else "static", "medium", width=cw - 24)
                D.text(cr, cx + 14, y + 15, e["title"], 11, "static" if past else "soft", "semibold", width=cw - 24)
                self._event_region(cx + 6, y, cw - 12, rowh - 4, e)
                y += rowh

    def _agenda(self, cr, evs, x0, x1, top, bottom, now, days):
        y = top - self.offset
        total = 0
        cr.save()
        cr.rectangle(0, top - 2, x1 + 16, bottom - top + 2)
        cr.clip()
        for d, items in self._days(evs, dt.date.today(), days):
            if top - 20 <= y <= bottom:
                D.label(cr, x0, y + 2, self._dayname(d), "phosphor" if d == dt.date.today() else "dim", size=10)
                D.label(cr, x1, y + 2, d.strftime("%d %b").upper() if self._dayname(d) in ("TODAY", "TOMORROW")
                        else f"{len(items)}", "static", size=10, align="right")
                D.rule(cr, x0 + 110, y + 9, x1 - 50, "dim", 0.25)
                if top <= y and y + 18 <= bottom:
                    self.region(x0, y, x1 - x0, 18, f"{d.strftime('%A %d %B')}: {len(items)} event(s)")
            y += 22
            total += 22
            if not items:
                if top <= y <= bottom - 18:
                    D.text(cr, x0 + 10, y, "free", 10, "static", "regular")
                    self.region(x0, y, x1 - x0, 16, f"Nothing on {d.strftime('%A')}")
                y += 18
                total += 18
            for e in items:
                if top <= y and y + 22 <= bottom:
                    self._row(cr, e, x0, x1, y, now)
                elif top - 22 < y < bottom:
                    pass
                y += 22
                total += 22
            y += 4
            total += 4
        cr.restore()
        view = bottom - top
        self.offset = min(self.offset, max(0, total - view))
        self.scrollbar(cr, x1 + 10, top, view, total, self.offset)

    def _week(self, cr, evs, x0, x1, top, bottom, now):
        today = dt.date.today()
        ws = self.conf.get("week_start", "today")
        start = today
        if ws == "monday":
            start = today - dt.timedelta(days=today.weekday())
        elif ws == "sunday":
            start = today - dt.timedelta(days=(today.weekday() + 1) % 7)
        cols = self._days(evs, start, 7)
        gutter = 40
        gx = x0 + gutter
        cw = (x1 - gx) / 7
        # the hours shown: 08–20, widened to fit the week's timed events
        timed = [e for _, items in cols for e in items if not e["all_day"]]
        h0, h1 = 8, 20
        for e in timed:
            a = dt.datetime.fromtimestamp(e["start"])
            b = dt.datetime.fromtimestamp(max(e["start"], e["end"] - 1))
            if a.date() == b.date():
                h0, h1 = min(h0, a.hour), max(h1, b.hour + 1)
        if any(d == today for d, _ in cols):                # now is always on the grid
            hn = dt.datetime.fromtimestamp(now).hour
            h0, h1 = min(h0, hn), max(h1, hn + 1)
        h1 = min(24, h1)
        # headers and the all-day row
        allday = max([len([e for e in items if e["all_day"]]) for _, items in cols] + [0])
        head = 20
        ady = top + head
        adh = 18 * allday
        gy = ady + adh + (6 if allday else 0)
        hh = (bottom - gy) / max(1, h1 - h0)
        for i, (d, items) in enumerate(cols):
            cx = gx + i * cw
            is_today = d == today
            D.label(cr, cx + cw / 2, top, d.strftime("%a %d").upper(), "phosphor" if is_today else "dim", size=10,
                    align="center")
            self.region(cx, top - 2, cw, head, f"{d.strftime('%A %d %B')}: {len(items)} event(s)")
            if is_today:
                D.src(cr, "phosphor", 0.06)
                cr.rectangle(cx, gy, cw, bottom - gy)
                cr.fill()
            k = 0
            for e in items:
                if not e["all_day"]:
                    continue
                ey = ady + k * 18
                D.src(cr, e["colour"], 0.25)
                cr.rectangle(cx + 2, ey, cw - 4, 16)
                cr.fill()
                D.text(cr, cx + 6, ey + 1, e["title"], 10, "soft", "medium", width=cw - 10)
                self._event_region(cx + 2, ey, cw - 4, 16, e)
                k += 1
        # the hour lines
        cr.set_line_width(1)
        for hr in range(h0, h1 + 1):
            y = round(gy + (hr - h0) * hh) + 0.5
            D.src(cr, "guard", 1 if hr % 6 else 1)
            cr.move_to(gx, y)
            cr.line_to(x1, y)
            cr.stroke()
            if hr < h1 and (hh >= 14 or hr % 2 == 0):
                D.text(cr, gx - 6, y - 6, f"{hr:02d}", 10, "static", "regular", align="right")
        for i in range(8):
            x = round(gx + i * cw) + 0.5
            D.src(cr, "guard", 1)
            cr.move_to(x, gy)
            cr.line_to(x, bottom)
            cr.stroke()
        self.region(x0, gy, gutter, bottom - gy, f"Hours {h0:02d}:00 to {h1:02d}:00, widened to fit this week's events")
        # the events, side by side where they overlap
        for i, (d, items) in enumerate(cols):
            cx = gx + i * cw
            day0 = dt.datetime.combine(d, dt.time()).timestamp()
            tim = [e for e in items if not e["all_day"]]
            lanes = []
            placed = []
            for e in tim:
                lane = next((j for j, end in enumerate(lanes) if end <= e["start"]), None)
                if lane is None:
                    lanes.append(e["end"])
                    lane = len(lanes) - 1
                else:
                    lanes[lane] = e["end"]
                placed.append((e, lane))
            n = max(1, len(lanes))
            for e, lane in placed:
                a = max(e["start"], day0 + h0 * 3600)
                b = min(max(e["end"], e["start"] + 900), day0 + h1 * 3600)
                if b <= a:
                    continue
                ey = gy + (a - day0 - h0 * 3600) / 3600 * hh
                eh = max(12, (b - a) / 3600 * hh - 2)
                lw = (cw - 4) / n
                ex = cx + 2 + lane * lw
                past = e["end"] <= now
                D.src(cr, e["colour"], 0.28 if not past else 0.12)
                cr.rectangle(ex, ey + 1, lw - 2, eh)
                cr.fill()
                D.src(cr, e["colour"], 0.95 if not past else 0.4)
                cr.rectangle(ex, ey + 1, 2, eh)
                cr.fill()
                if eh >= 14:
                    D.text(cr, ex + 5, ey + 2, e["title"], 10, "static" if past else "soft", "semibold", width=lw - 9)
                if eh >= 28:
                    D.text(cr, ex + 5, ey + 15, when(e), 9 if eh < 40 else 10, "static", "regular", width=lw - 9)
                self._event_region(ex, ey + 1, lw - 2, eh, e)
        # now
        if any(d == today for d, _ in cols):
            i = [d for d, _ in cols].index(today)
            nowh = (now - dt.datetime.combine(today, dt.time()).timestamp()) / 3600
            if h0 <= nowh <= h1:
                y = gy + (nowh - h0) * hh
                D.src(cr, "danger", 0.95)
                cr.set_line_width(2)
                cr.move_to(gx + i * cw, y)
                cr.line_to(gx + (i + 1) * cw, y)
                cr.stroke()
                cr.set_line_width(1)
                D.dot(cr, gx + i * cw, y, 3, "danger", glow=K.motion() == "full")
                self.region(gx + i * cw, y - 4, cw, 8, f"Now, {K.clock(now)}")


PANEL = CalendarPanel
LAYOUT = {"visible": False}
