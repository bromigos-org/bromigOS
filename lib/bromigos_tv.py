"""The den TV's channels: what each of the den's screens can show, and what's on now.

The den's three screens (the big monitor, the scope and the small monitor) each have a
list of channels. Channel 1 is the screen's own picture, as bromigOS has always drawn it.
The media channels come after it: a library, collection or playlist on a Jellyfin or Plex
server (through bromigos_homelab's `video` capability), or a YouTube playlist or channel
(through bromigos_youtube). A media channel is *live*: what's on comes from the wall
clock, so at any moment it's part-way through something, as if it had been on all along.

The live layer plays the channels (live/live/tv.py); the media panel reads the same
schedule from the same cache, so both agree on what's on, with no server call per draw.

    import bromigos_tv as TV
    TV.channels(cfg)                    every media channel in the live config's [tv]
    TV.lineup(cfg, "big", live={})      the screen's channels: its own first, then the media ones
    TV.schedule_at(items, t, seed, order) -> Slot(item, offset, start, end, index, next)
    TV.now_next(channel, t)             the channel's Slot from its cached items, or None
    TV.state() / TV.save_state(st)      each screen's channel, sound and volume (remembered)

The config, in ~/.config/bromigos-live/config.toml (docs: live/README.md, "The den TV"):

    [[tv.channel]]
    name = "Saturday"
    source = "plex"               # a jellyfin or plex source in homelab.toml (default: the first)
    library = "TV Shows"          # or collection = "…" or playlist = "…", by title
    order = "shuffle"             # or "in order"
    screens = ["big"]             # the den screens that carry it (default: the big monitor)

    [[tv.channel]]
    name = "Studio"
    youtube = "https://www.youtube.com/@example"   # a playlist or a channel (its uploads)
    live = true                   # when the channel is live, add "<name> LIVE" after it
    keep = "~/Videos/YouTube"     # optional: keep what it plays (keep_all = true: everything)

    [[tv.channel]]
    name = "Home movies"
    files = "~/Videos/Home"       # video files on disk: a folder, or a list of paths

The schedule: the items with a known length, in order or shuffled, play end to end from a
fixed start (EPOCH), round and round. A playlist plays in its own order by default, a
library or a collection shuffled. A shuffled pass is ordered by a hash of (seed, the date
the pass starts, item id): the same all day, on every machine and after a restart, and a
new item slots in without reordering the rest. When the list changes (an episode added, a
length corrected), the schedule is simply computed again.
"""
import bisect
import hashlib
import json
import os
import re
import tempfile
import time

EPOCH = 1767225600.0                     # 2026-01-01T00:00:00Z: every channel's day one
SCREENS = ("big", "wave", "emblem")      # the den's screens, as live/live/scene.py's DEN names them
OWN = {"big": ("RELAY MAP", "the homelab's nodes and links"),
       "wave": ("SCOPE", "this machine's network traffic"),
       "emblem": ("BURN-IN", "the burn-in emblem")}
SCREEN_NAMES = {"big": "the big monitor", "wave": "the scope", "emblem": "the small monitor"}
DEFAULT_SCREENS = ("big",)
DEFAULT_VOLUME = 60
STATE_DIR = os.path.join(os.environ.get("XDG_STATE_HOME") or os.path.expanduser("~/.local/state"), "bromigos-live")
STATE = os.path.join(STATE_DIR, "tv.json")
CACHE = os.path.join(os.environ.get("XDG_CACHE_HOME") or os.path.expanduser("~/.cache"), "bromigos", "tv")
BAD_FOR = 24 * 3600                      # an item that wouldn't play is left out this long


# ------------------------------------------------------------------ channels
def _slug(s):
    return re.sub(r"[^a-z0-9]+", "-", (s or "").lower()).strip("-") or "channel"


def _entry(e, seen):
    """One [[tv.channel]] table (or the media panel's settings) as a channel dict, or None."""
    if not isinstance(e, dict) or e.get("enabled", True) is False:
        return None
    name = str(e.get("name") or "").strip()
    if e.get("youtube"):
        kind = "youtube"
        playlist_url = "list=" in str(e["youtube"]) and "/watch" not in str(e["youtube"])
        default_order = "in order" if playlist_url else "shuffle"
    elif e.get("library") or e.get("collection") or e.get("playlist"):
        kind = "server"
        default_order = "in order" if e.get("playlist") else "shuffle"
    elif e.get("files"):
        kind = "files"
        default_order = "shuffle"
    else:
        return None
    name = name or str(e.get("library") or e.get("collection") or e.get("playlist") or
                       ("Files" if kind == "files" else "YouTube"))
    key = _slug(name)
    if key in seen:
        return None
    seen.add(key)
    screens = e.get("screens") or e.get("screen") or list(DEFAULT_SCREENS)
    if isinstance(screens, str):
        screens = [screens]
    order = str(e.get("order") or default_order).lower().replace("_", " ")
    order = "in order" if order in ("in order", "inorder", "order") else "shuffle"
    return dict(e, name=name, key=key, kind=kind, order=order, screens=[x for x in screens if x in SCREENS],
                seed=str(e.get("seed", key)))


def panel_channel():
    """The channel the media panel's settings describe (~/.config/bromigos/widgets/media.toml),
    as a [[tv.channel]] table, or None. Its form is the friendly way to make one channel."""
    path = os.path.join(os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config"), "bromigos", "widgets",
                        "media.toml")
    try:
        import tomllib
        with open(path, "rb") as f:
            d = tomllib.load(f)
    except (OSError, ValueError):
        return None
    e = {"name": d.get("channel_name") or "", "screens": [d.get("screen") or "big"], "order": d.get("order") or None}
    what = str(d.get("play") or "")
    if (d.get("source") or "") == "youtube" or (d.get("youtube") and not what):
        if not d.get("youtube"):
            return None
        e.update(youtube=d["youtube"], keep=d.get("keep") or "", keep_max_gb=d.get("keep_max_gb"),
                 live=bool(d.get("live", True)))
    elif ":" in what:
        kind, _, title = what.partition(":")
        if kind not in ("library", "collection", "playlist") or not title:
            return None
        e[kind] = title
        if d.get("source"):
            e["source"] = d["source"]
    else:
        return None
    return {k: v for k, v in e.items() if v not in (None, "")}


def channels(cfg, panel=True):
    """Every media channel: the live config's [[tv.channel]] tables (cfg is its merged
    config), then the media panel's channel. Each is a dict: {name, key, kind: "server" |
    "youtube", screens, order, seed, ...the entry's own keys}. An entry without a name and
    something to play is skipped, and so is a second channel with the same name."""
    tv = (cfg or {}).get("tv") or {}
    if tv.get("enabled", True) is False:
        return []
    out, seen = [], set()
    entries = list(tv.get("channel") or [])
    if panel:
        pc = panel_channel()
        if pc:
            entries.append(pc)
    for e in entries:
        ch = _entry(e, seen)
        if ch:
            out.append(ch)
    return out


def own_channel(screen):
    label, what = OWN.get(screen, (screen.upper(), ""))
    return {"name": label, "key": "own", "kind": "own", "screens": [screen], "what": what}


def live_channel(ch, video):
    """A YouTube channel's live stream right now, as a channel of its own (no schedule)."""
    return dict(ch, name=f"{ch['name']} LIVE", key=ch["key"] + "-live", kind="live", video=video)


def lineup(cfg, screen, live=None):
    """The screen's channels, numbered from 1: its own picture, then each media channel
    that names this screen, each followed by its live stream when live[key] has one."""
    out = [own_channel(screen)]
    for ch in channels(cfg):
        if screen in ch["screens"]:
            out.append(ch)
            v = (live or {}).get(ch["key"])
            if v:
                out.append(live_channel(ch, v))
    return out


# ------------------------------------------------------------------ the schedule
class Slot(dict):
    """What's on: item, offset (seconds into it), start and end (wall clock), index (in this
    pass's order), next (the item after it), pass_ (which pass round the list)."""
    __getattr__ = dict.get


def _rank(seed, day, iid):
    return hashlib.sha1(f"{seed}:{day}:{iid}".encode()).digest()


def playable(items, bad=()):
    """The items the schedule uses: a known, positive length, not left out as bad."""
    bad = set(bad or ())
    return [i for i in items or [] if (i.get("duration") or 0) > 0 and str(i.get("id")) not in bad]


def day_of(t):
    """The local date a pass starts on: a shuffle's order holds all that day."""
    return time.strftime("%Y-%m-%d", time.localtime(t))


def order_of(items, seed, day, order):
    """One pass's order: the list's own ("in order"), or shuffled for the day it starts on,
    by a hash of (seed, day, item id): the same all day, on every machine."""
    if order == "in order":
        return list(items)
    return sorted(items, key=lambda i: _rank(seed, day, i.get("id")))


def schedule_at(items, t, seed="", order="shuffle", epoch=EPOCH, bad=()):
    """The Slot on at wall-clock time t, or None when nothing has a length."""
    its = playable(items, bad)
    if not its:
        return None
    total = sum(float(i["duration"]) for i in its)
    since = t - epoch
    pass_ = int(since // total)
    pos = since - pass_ * total
    pass_start = epoch + pass_ * total
    seq = order_of(its, seed, day_of(pass_start), order)
    ends, acc = [], 0.0
    for i in seq:
        acc += float(i["duration"])
        ends.append(acc)
    k = min(bisect.bisect_right(ends, pos), len(seq) - 1)
    start_in = ends[k] - float(seq[k]["duration"])
    if k + 1 < len(seq):
        nxt = seq[k + 1]
    else:
        nxt = order_of(its, seed, day_of(pass_start + total), order)[0]
    begin = pass_start + start_in
    return Slot(item=seq[k], offset=pos - start_in, start=begin, end=begin + float(seq[k]["duration"]), index=k,
                next=nxt, pass_=pass_, count=len(seq))


def upcoming(items, t, n=3, seed="", order="shuffle", bad=()):
    """The next n Slots after the one on at t."""
    out, s = [], schedule_at(items, t, seed, order, bad=bad)
    while s and len(out) < n:
        s = schedule_at(items, s["end"] + 0.001, seed, order, bad=bad)
        out.append(s)
    return out


def sort_episodes(items):
    """A library's items in a sensible order: by series (or title), season, episode."""
    def key(i):
        return ((i.get("series") or i.get("title") or "").lower(), i.get("season") or 0, i.get("episode") or 0,
                (i.get("title") or "").lower())
    return sorted(items, key=key)


# ------------------------------------------------------------------ items, cached
def cache_path(ch):
    return os.path.join(CACHE, f"{ch['key']}.json")


def _write_json(path, doc):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path), prefix=".tv-")
    with os.fdopen(fd, "w") as f:
        json.dump(doc, f)
    os.replace(tmp, path)


def cached_items(ch):
    """{"items": [...], "fetched", "error", "server"} for a channel, from the cache only."""
    try:
        with open(cache_path(ch)) as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def _homelab():
    try:
        import bromigos_homelab as H
        return H
    except ImportError:
        return None


def server_of(ch):
    """The channel's video server adapter (bromigos_homelab), or None."""
    H = _homelab()
    return H.video_source(ch.get("source") or None) if H else None


VIDEO_EXT = (".mp4", ".mkv", ".webm", ".mov", ".m4v", ".avi", ".ts")


def _probe(path):
    """A video file's length in seconds (ffprobe), or None."""
    import subprocess
    try:
        out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", path],
                             capture_output=True, text=True, timeout=20).stdout.strip()
        return float(out) if out else None
    except (OSError, ValueError, subprocess.SubprocessError):
        return None


def local_files(spec):
    """Items for video files on disk: a folder (searched through) or a list of paths. Their
    lengths come from ffprobe, kept in CACHE/files.json by path, size and time."""
    paths = []
    for p in ([spec] if isinstance(spec, str) else list(spec or [])):
        p = os.path.expanduser(str(p))
        if os.path.isdir(p):
            for root, _dirs, files in os.walk(p):
                paths += [os.path.join(root, f) for f in sorted(files) if f.lower().endswith(VIDEO_EXT)]
        elif os.path.isfile(p):
            paths.append(p)
    known_path = os.path.join(CACHE, "files.json")
    try:
        with open(known_path) as f:
            known = json.load(f)
    except (OSError, ValueError):
        known = {}
    out, changed = [], False
    for p in sorted(paths):
        try:
            st = os.stat(p)
        except OSError:
            continue
        sig = f"{st.st_size}:{int(st.st_mtime)}"
        hit = known.get(p)
        if not hit or hit.get("sig") != sig:
            hit = {"sig": sig, "duration": _probe(p)}
            known[p] = hit
            changed = True
        stem = os.path.splitext(os.path.basename(p))[0]
        out.append({"id": hashlib.sha1(p.encode()).hexdigest()[:16], "title": stem, "series": None, "kind": "file",
                    "duration": hit.get("duration"), "url": p, "poster": None, "server": "files"})
    if changed:
        try:
            _write_json(known_path, known)
        except OSError:
            pass
    return out


def fetch_items(ch, max_age=900, refresh=True):
    """A channel's items, read from its server or YouTube when the cache is older than
    max_age seconds, else from the cache. Never raises: a failure keeps the last list,
    with "error" set. Called from a thread, never from a frame."""
    old = cached_items(ch)
    if old and time.time() - (old.get("fetched") or 0) < (max_age if not old.get("error") else min(max_age, 120)):
        return old
    if not refresh:
        return old
    doc = {"items": (old or {}).get("items") or [], "fetched": time.time(), "error": None, "server": None}
    try:
        if ch["kind"] == "youtube":
            import bromigos_youtube as Y
            y = Y.videos(ch["youtube"], max_age=3600, tab=ch.get("tab") or "videos")
            playlist = None if Y.is_channel(ch["youtube"]) else (y.get("title") or "YouTube")
            doc["items"] = [dict(v, kind="video", series=y.get("channel"), poster=v.get("thumbnail"), server="youtube",
                                 index=n + 1, playlist=playlist)
                            for n, v in enumerate(y.get("videos") or []) if v.get("live") not in ("is_live", "is_upcoming")]
            doc["error"], doc["server"] = y.get("error"), "youtube"
        elif ch["kind"] == "files":
            doc["items"] = local_files(ch["files"])
            doc["server"] = "files"
        else:
            a = server_of(ch)
            if a is None:
                raise LookupError(f"no video server{' named ' + ch['source'] if ch.get('source') else ''} "
                                  "in homelab.toml")
            kind = "library" if ch.get("library") else "collection" if ch.get("collection") else "playlist"
            want = str(ch.get(kind)).strip().lower()
            box = next((v for v in a.video() if v["kind"] == kind and want in (str(v["title"]).lower(), str(v["id"]))),
                       None)
            if box is None:
                raise LookupError(f"{a.name} has no {kind} called {ch.get(kind)!r}")
            items = a.video_items(kind, box["id"])
            doc["items"] = sort_episodes(items) if kind == "library" else items
            doc["server"] = a.name
    except Exception as e:                                    # noqa: BLE001  never stall the TV
        doc["error"] = f"{type(e).__name__}: {e}"[:200]
    try:
        _write_json(cache_path(ch), doc)
    except OSError:
        pass
    return doc


def catalog(max_age=900, refresh=True):
    """What the video servers offer: {"boxes": [the `video` capability's records: libraries,
    collections and playlists], "servers": [source names], "fetched", "error"}. Cached in
    CACHE/catalog.json; read from the servers (a thread's job) when older than max_age and
    refresh is true. The media panel's settings form lists its choices from it."""
    path = os.path.join(CACHE, "catalog.json")
    try:
        with open(path) as f:
            old = json.load(f)
    except (OSError, ValueError):
        old = None
    if old and (not refresh or time.time() - (old.get("fetched") or 0) < max_age):
        return old
    if not refresh:
        return {"boxes": [], "servers": [], "fetched": 0, "error": None}
    H = _homelab()
    doc = {"boxes": [], "servers": [], "fetched": time.time(), "error": None}
    if H is not None and H.available("video"):
        r = H.video()
        doc["boxes"] = r["items"]
        doc["servers"] = r["sources"]
        doc["error"] = "; ".join(f"{k}: {v}" for k, v in r["errors"].items()) or None
        if not r["ok"] and old:
            doc["boxes"] = old.get("boxes") or []
    try:
        _write_json(path, doc)
    except OSError:
        pass
    return doc


def bad_items():
    """{item id: when it failed} for items that wouldn't play in the last BAD_FOR seconds."""
    try:
        with open(os.path.join(CACHE, "bad.json")) as f:
            d = json.load(f)
    except (OSError, ValueError):
        return {}
    now = time.time()
    return {k: v for k, v in d.items() if isinstance(v, (int, float)) and now - v < BAD_FOR}


def mark_bad(item_id):
    d = bad_items()
    d[str(item_id)] = time.time()
    try:
        _write_json(os.path.join(CACHE, "bad.json"), d)
    except OSError:
        pass


def unmark_bad(item_ids):
    """Take items off the bad list (they failed together: the server, not the items)."""
    d = bad_items()
    for i in item_ids:
        d.pop(str(i), None)
    try:
        _write_json(os.path.join(CACHE, "bad.json"), d)
    except OSError:
        pass


def now_next(ch, t=None):
    """The channel's Slot now, from its cached items (no network), or None."""
    if ch.get("kind") == "live":
        v = ch.get("video") or {}
        return Slot(item=dict(v, kind="live"), offset=None, start=None, end=None, index=0, next=None)
    doc = cached_items(ch) or {}
    return schedule_at(doc.get("items") or [], time.time() if t is None else t, ch.get("seed", ch.get("key")),
                       ch.get("order", "shuffle"), bad=bad_items())


def label(item):
    """"Series S2E5 · Title", "Title (1999)" or "Title"."""
    if not item:
        return ""
    t = item.get("title") or ""
    if item.get("series") and item.get("kind") == "season":
        return f"{item['series']} · {t}"
    if item.get("series") and item.get("kind") == "episode":
        se = ""
        if item.get("season") is not None and item.get("episode") is not None:
            se = f" S{item['season']}E{item['episode']}"
        return f"{item['series']}{se} · {t}"
    if item.get("year"):
        return f"{t} ({item['year']})"
    return t


# ------------------------------------------------------------------ remembered state
def state():
    """{"screens": {screen: {"channel": key, "sound": bool, "volume": 0..100}}}."""
    try:
        with open(STATE) as f:
            d = json.load(f)
        if isinstance(d, dict) and isinstance(d.get("screens"), dict):
            return d
    except (OSError, ValueError):
        pass
    return {"screens": {}}


def screen_state(st, screen, default_volume=DEFAULT_VOLUME):
    s = dict((st.get("screens") or {}).get(screen) or {})
    s.setdefault("channel", "own")
    s["sound"] = bool(s.get("sound", False))
    try:
        s["volume"] = max(0, min(100, int(s.get("volume", default_volume))))
    except (TypeError, ValueError):
        s["volume"] = default_volume
    return s


def save_state(st):
    try:
        _write_json(STATE, st)
    except OSError:
        pass


def fmt_time(s):
    s = int(max(0, s or 0))
    h, m = divmod(s // 60, 60)
    return f"{h}:{m:02d}:{s % 60:02d}" if h else f"{m}:{s % 60:02d}"
