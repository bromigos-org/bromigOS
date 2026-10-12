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
    screens = ["big"]             # only these den screens carry it (default: every screen)

    [[tv.channel]]
    name = "Studio"
    youtube = "https://www.youtube.com/@example"   # a playlist or a channel (its uploads)
    live = true                   # when the channel is live, add "<name> LIVE" after it
    keep = "~/Videos/YouTube"     # optional: keep what it plays (keep_all = true: everything)

    [[tv.channel]]
    name = "Home movies"
    files = "~/Videos/Home"       # video files on disk: a folder, or a list of paths

    [[tv.channel]]
    name = "Sitcoms"
    shows = ["Example Show", "Another Show"]   # series you pick (titles or ids); items = [...]
    order = "in order"            # movies, collections = [...] collections; "in order" takes turns
    screens = "any"               # every screen; [tv] screens is the default for a channel

A channel made of picked shows (`shows`, `items`, `collections`) shuffles their episodes
together, or with "in order" (or "alternate") takes turns: show A's next episode, then
show B's, and round again, each show going on from where it left off (rotation_at, kept
in the live layer's state, never in config.toml). A title is matched once and its id
remembered, so a renamed folder doesn't break the channel.

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
import urllib.parse

EPOCH = 1767225600.0                     # 2026-01-01T00:00:00Z: every channel's day one
SCREENS = ("big", "wave", "emblem")      # the den's screens, as live/live/scene.py's DEN names them
OWN = {"big": ("RELAY MAP", "the homelab's nodes and links"),
       "wave": ("SCOPE", "this machine's network traffic"),
       "emblem": ("BURN-IN", "the burn-in emblem")}
SCREEN_NAMES = {"big": "the big monitor", "wave": "the scope", "emblem": "the small monitor"}
DEFAULT_SCREENS = ("big", "wave", "emblem")   # a channel's screens when neither it nor [tv] screens says: all
ANY = ("any", "all", "*")                 # screens = "any": every screen
DEFAULT_VOLUME = 60
STATE_DIR = os.path.join(os.environ.get("XDG_STATE_HOME") or os.path.expanduser("~/.local/state"), "bromigos-live")
STATE = os.path.join(STATE_DIR, "tv.json")
ROTATION = os.path.join(STATE_DIR, "tv-rotation.json")    # in-order picked shows: where each one is
PICKS = os.path.join(STATE_DIR, "tv-picks.json")          # picked titles matched to their ids
CACHE = os.path.join(os.environ.get("XDG_CACHE_HOME") or os.path.expanduser("~/.cache"), "bromigos", "tv")
BAD_FOR = 24 * 3600                      # an item that wouldn't play is left out this long


# ------------------------------------------------------------------ channels
def _slug(s):
    return re.sub(r"[^a-z0-9]+", "-", (s or "").lower()).strip("-") or "channel"


def screens_of(v, default=DEFAULT_SCREENS):
    """A `screens` value as a list of SCREENS: a list, one name, or "any" (every screen)."""
    if v is None or v == "" or v == []:
        v = list(default)
    if isinstance(v, str):
        v = list(SCREENS) if v.lower() in ANY else [v]
    out = []
    for x in v:
        x = str(x).lower()
        x = {"scope": "wave", "small": "emblem"}.get(x, x)
        if x in ANY:
            return list(SCREENS)
        if x in SCREENS and x not in out:
            out.append(x)
    return out


def _as_list(v):
    if v is None or v == "":
        return []
    return [v] if isinstance(v, (str, int)) else list(v)


def norm_order(v, default="shuffle"):
    """"in order" or "shuffle"; "alternate" (taking turns) is "in order"."""
    o = str(v or default).lower().replace("_", " ").replace("-", " ").strip()
    return "in order" if o in ("in order", "inorder", "order", "alternate", "turns", "rotate") else "shuffle"


def _entry(e, seen, default_screens=DEFAULT_SCREENS):
    """One [[tv.channel]] table (or the media panel's settings) as a channel dict, or None."""
    if not isinstance(e, dict) or e.get("enabled", True) is False:
        return None
    name = str(e.get("name") or "").strip()
    picks = bool(_as_list(e.get("shows")) or _as_list(e.get("items")) or _as_list(e.get("collections")))
    if picks and not e.get("youtube") and not e.get("files"):
        kind = "server"
        default_order = "shuffle"
    elif e.get("youtube"):
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
    picks = picks and kind == "server"
    name = name or str(e.get("library") or e.get("collection") or e.get("playlist") or
                       ("Picked shows" if picks else "Files" if kind == "files" else "YouTube"))
    key = _slug(name)
    if key in seen:
        return None
    seen.add(key)
    screens = screens_of(e.get("screens") if e.get("screens") not in (None, "", []) else e.get("screen"),
                         default_screens)
    order = norm_order(e.get("order"), default_order)
    return dict(e, name=name, key=key, kind=kind, order=order, screens=screens, picks=picks,
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
    e = {"name": d.get("channel_name") or "", "screens": d.get("screen") or "any", "order": d.get("order") or None}
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
    default = screens_of(tv.get("screens"), DEFAULT_SCREENS) if tv.get("screens") else DEFAULT_SCREENS
    for e in entries:
        ch = _entry(e, seen, default)
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
            doc = json.load(f)
        if doc.get('definition') and doc['definition'] != content_signature(ch):
            return None
        return doc
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


def content_signature(ch):
    keys = ("source", "shows", "items", "collections", "library", "collection", "playlist", "youtube", "files", "tab")
    text = json.dumps({key: ch.get(key) for key in keys}, sort_keys=True, default=str)
    return hashlib.sha256(text.encode()).hexdigest()


def fetch_items(ch, max_age=900, refresh=True):
    """A channel's items, read from its server or YouTube when the cache is older than
    max_age seconds, else from the cache. Never raises: a failure keeps the last list,
    with "error" set. Called from a thread, never from a frame."""
    old = cached_items(ch)
    signature = content_signature(ch)
    changed = bool(old and old.get("definition") and old["definition"] != signature)
    if old and old.get("definition") == signature and time.time() - (old.get("fetched") or 0) < (max_age if not old.get("error") else min(max_age, 120)):
        return old
    if not refresh:
        return old
    doc = {"items": [] if changed else (old or {}).get("items") or [], "fetched": time.time(),
           "definition": signature, "error": None, "server": None}
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
        elif ch.get("picks"):
            a = server_of(ch)
            if a is None and any(not youtube_pick(v) for k in PICK_KEYS for v in _as_list(ch.get(k))):
                raise LookupError(f"no video server{' named ' + ch['source'] if ch.get('source') else ''} "
                                  "in homelab.toml")
            doc["items"], doc["groups"], missing = pick_items(ch, a)
            doc["server"] = a.name if a else "youtube"
            if missing:
                doc["error"] = f"{a.name} has nothing called " + ", ".join(repr(m) for m in missing)
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


# ------------------------------------------------------------------ picked shows
def _read(path):
    try:
        with open(path) as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


PICK_KINDS = (("shows", "show"), ("items", "movie"), ("collections", "collection"))


def _choices(a, kind):
    """What a server offers to pick from: its shows, movies or collections, as records
    with id and title (the adapter's video_shows / video_movies, the `video` collections)."""
    if kind == "show":
        return a.video_shows()
    if kind == "movie":
        return a.video_movies()
    return [b for b in a.video() if b.get("kind") == "collection"]


def resolve_picks(ch, a):
    """{kind: [(id, title, what was written)]} for a channel's picks on server a, and the
    names that matched nothing. An id is used as it is; a title is matched once (case
    aside) and its id remembered in PICKS, so a show renamed on the server still plays."""
    memory = _read(PICKS)
    mine = memory.setdefault(a.name, {})
    out, missing, listed, changed = {}, [], {}, False
    for key, kind in PICK_KINDS:
        want = [str(x) for x in _as_list(ch.get(key)) if str(x).strip()]
        if not want:
            continue
        known = mine.setdefault(kind, {})
        rows = []
        for w in want:
            low = w.strip().lower()
            if low in known:
                rows.append((known[low]["id"], known[low].get("title") or w, w))
                continue
            if kind not in listed:
                try:
                    listed[kind] = _choices(a, kind)
                except Exception:                              # noqa: BLE001  the server: next time
                    listed[kind] = []
            hit = next((c for c in listed[kind] if str(c.get("id")) == w.strip()), None) or \
                next((c for c in listed[kind] if str(c.get("title") or "").strip().lower() == low), None)
            if hit is None:
                missing.append(w)
                continue
            known[low] = {"id": str(hit["id"]), "title": hit.get("title")}
            changed = True
            rows.append((str(hit["id"]), hit.get("title") or w, w))
        out[kind] = rows
    if changed:
        try:
            _write_json(PICKS, memory)
        except OSError:
            pass
    return out, missing


def forget_pick(server, kind, name):
    """Drop a remembered match (its id is gone from the server): matched by title again."""
    memory = _read(PICKS)
    if memory.get(server, {}).get(kind, {}).pop(str(name).strip().lower(), None) is not None:
        try:
            _write_json(PICKS, memory)
        except OSError:
            pass


def youtube_pick(value):
    host = (urllib.parse.urlparse(str(value)).hostname or "").lower()
    return host in ("youtube.com", "www.youtube.com", "m.youtube.com", "youtu.be")


def pick_items(ch, a):
    """(items, groups, missing) for a channel of picked shows, movies and collections. Each
    show (and each collection) is a group of its own, its episodes in season and episode
    order; the picked movies are one group, in the order written. groups: [[id, title]]."""
    extras = [str(v) for v in _as_list(ch.get("items")) if youtube_pick(v) or str(v).startswith("music:")]
    server_picks = dict(ch, items=[v for v in _as_list(ch.get("items")) if str(v) not in extras])
    picked, missing = resolve_picks(server_picks, a) if a else ({}, [])
    items, groups = [], []
    for sid, title, written in picked.get("show", []):
        try:
            eps = sort_episodes(a.video_show_items(sid))
        except Exception:                                     # noqa: BLE001  a show deleted, or renamed with a new id
            forget_pick(a.name, "show", written)
            missing.append(written)
            continue
        gid = f"show:{sid}"
        groups.append([gid, title])
        items += [dict(i, group=gid) for i in eps]
    movies = []
    for mid, title, written in picked.get("movie", []):
        try:
            it = a.video_item(mid)
        except Exception:                                     # noqa: BLE001
            it = None
        if not it:
            forget_pick(a.name, "movie", written)
            missing.append(written)
            continue
        movies.append(dict(it, group="items"))
    if movies:
        groups.append(["items", "Movies"])
        items += movies
    for cid, title, written in picked.get("collection", []):
        try:
            got = a.video_items("collection", cid)
        except Exception:                                     # noqa: BLE001
            forget_pick(a.name, "collection", written)
            missing.append(written)
            continue
        gid = f"collection:{cid}"
        groups.append([gid, title])
        items += [dict(i, group=gid) for i in got]
    for value in extras:
        gid = "pick:" + hashlib.sha1(value.encode()).hexdigest()[:16]
        try:
            if youtube_pick(value):
                import bromigos_youtube as Y
                doc = Y.videos(value)
                if doc.get("error"): raise LookupError(doc["error"])
                got = [dict(v, kind="video", server="youtube", poster=v.get("thumbnail"))
                       for v in doc.get("videos") or [] if v.get("live") not in ("is_live", "is_upcoming")]
                title = doc.get("title") or value
            else:
                _, music_kind, title = value.split(":", 2)
                got = a.video_music(music_kind, title) if a else []
            if not got: raise LookupError("No playable items")
            groups.append([gid, title])
            items += [dict(v, group=gid) for v in got]
        except (LookupError, ValueError, AttributeError):
            missing.append(value)
    return items, groups, missing


def _groups_of(doc):
    """[(group id, [its items])] from a picked channel's cached doc, in the groups' order."""
    by = {}
    for i in doc.get("items") or []:
        by.setdefault(i.get("group") or "items", []).append(i)
    order = [g[0] for g in doc.get("groups") or []] or list(by)
    return [(g, by.get(g, [])) for g in order]


def day_start(t):
    """Local midnight before t."""
    lt = time.localtime(t)
    return time.mktime((lt.tm_year, lt.tm_mon, lt.tm_mday, 0, 0, 0, 0, 0, -1))


def rotation_at(groups, t, anchor=None, bad=()):
    """Taking turns: the Slot on at wall-clock time t when the groups (shows) play one item
    each in turn, each group in its own order, from the anchor {"t": when, "pos": {group:
    the id of its next item}, "turn": whose turn it is then}. With no anchor: from local
    midnight, every group at its first item. The Slot's `anchor` is the same schedule
    anchored at the start of what's on (rotation_advance keeps it, so the walk stays short)."""
    gs = [(g, playable(its, bad)) for g, its in groups]
    gs = [(g, its) for g, its in gs if its]
    if not gs:
        return None
    anchor = anchor or {}
    order = [g for g, _ in gs]
    items = dict(gs)
    cur = float(anchor.get("t") or day_start(t))
    k = order.index(anchor["turn"]) if anchor.get("turn") in order else 0
    pos = {}
    for g, its in gs:
        want = (anchor.get("pos") or {}).get(g)
        ids = [str(i.get("id")) for i in its]
        pos[g] = ids.index(str(want)) if want is not None and str(want) in ids else 0
    if t < cur:                                  # before the anchor (a clock set back): its first item
        t = cur
    count = sum(len(v) for v in items.values())
    for _ in range(500000):
        g = order[k % len(order)]
        its = items[g]
        i = pos[g] % len(its)
        d = float(its[i]["duration"])
        if cur + d > t:
            here = {x: str(items[x][pos[x] % len(items[x])].get("id")) for x in order}
            pos[g] = i + 1
            g2 = order[(k + 1) % len(order)]
            nxt = items[g2][pos[g2] % len(items[g2])]
            return Slot(item=its[i], offset=t - cur, start=cur, end=cur + d, index=i, next=nxt, pass_=0,
                        count=count, group=g, anchor={"t": cur, "pos": here, "turn": g})
        cur += d
        pos[g] = i + 1
        k += 1
    return None


def rotation_state(key):
    return (_read(ROTATION).get(key) or None)


def rotation_advance(ch, t=None, every=3 * 3600):
    """The worker's job for an in-order picked channel: keep its anchor near now (where each
    show is), so the walk from it stays short and each show goes on where it left off, day
    after day. Written when there's none yet or it's older than `every` seconds."""
    if not (ch.get("picks") and ch.get("order") == "in order"):
        return None
    t = (time.time() if t is None else t) + channel_offset(ch)
    doc = cached_items(ch) or {}
    st = _read(ROTATION)
    old = st.get(ch["key"])
    if old and t - float(old.get("t") or 0) < every:
        return old
    s = rotation_at(_groups_of(doc), t, old, bad_items())
    if not s:
        return old
    st[ch["key"]] = s.anchor
    try:
        _write_json(ROTATION, st)
    except OSError:
        pass
    return s.anchor


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


def channel_offset(ch):
    return float(_read(os.path.join(STATE_DIR, "tv-clocks.json")).get(ch["key"], 0))


def channel_step(ch, previous=False, t=None):
    """Move the channel clock to the adjacent item's start, keeping its schedule."""
    t = time.time() if t is None else t
    current = now_next(ch, t)
    if not current or current.end is None:
        return None
    target = now_next(ch, current.start - .001) if previous else now_next(ch, current.end + .001)
    if not target:
        return None
    path = os.path.join(STATE_DIR, "tv-clocks.json")
    clocks = _read(path)
    clocks[ch["key"]] = channel_offset(ch) + target.start - t
    _write_json(path, clocks)
    return now_next(ch, t)


def now_next(ch, t=None):
    """The channel's Slot now, from its cached items (no network), or None."""
    if ch.get("kind") == "live":
        v = ch.get("video") or {}
        return Slot(item=dict(v, kind="live"), offset=None, start=None, end=None, index=0, next=None)
    doc = cached_items(ch) or {}
    t = time.time() if t is None else t
    shift = channel_offset(ch)
    if ch.get("picks") and ch.get("order") == "in order":
        slot = rotation_at(_groups_of(doc), t + shift, rotation_state(ch.get("key")), bad_items())
    else:
        slot = schedule_at(doc.get("items") or [], t + shift, ch.get("seed", ch.get("key")),
                           ch.get("order", "shuffle"), bad=bad_items())
    if slot:
        slot["start"] -= shift
        slot["end"] -= shift
    return slot


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


def start_key(cfg, screen):
    """The key of the channel a screen starts on ([tv] start = {big = "Shows", …}: a name or
    key), or None: channel 1."""
    want = ((cfg or {}).get("tv") or {}).get("start") or {}
    v = want.get(screen) if isinstance(want, dict) else None
    if not v:
        return None
    return _slug(str(v))


def save_state(st):
    try:
        _write_json(STATE, st)
    except OSError:
        pass


def fmt_time(s):
    s = int(max(0, s or 0))
    h, m = divmod(s // 60, 60)
    return f"{h}:{m:02d}:{s % 60:02d}" if h else f"{m}:{s % 60:02d}"
