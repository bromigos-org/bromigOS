"""YouTube playlists and channels, read through yt-dlp, with no API key.

What the desktop shows of YouTube: a playlist's or a channel's videos (the den TV's
YouTube channels, the panels), and whether a channel is live right now. It runs
`yt-dlp --flat-playlist -J`, which lists a playlist without opening each video, and
keeps the answer in a cache. Nothing here runs on every frame, and nothing here plays
anything: mpv plays a video's `url` through its own yt-dlp hook.

The interface (stable: other parts of bromigOS import it):

    import bromigos_youtube as Y

    Y.videos(url, max_age=3600, limit=200, refresh=True)
        -> {"url", "title", "channel", "fetched", "videos": [Video, ...], "error"}
        A playlist's or a channel's videos, newest first for a channel, in the
        playlist's order for a playlist. From the cache when it's younger than max_age
        seconds. Otherwise yt-dlp runs (when refresh is true) and the cache is renewed.
        When yt-dlp fails, the last good answer comes back with "error" set, so a
        network hiccup never empties a list. Never raises.

    Y.live_now(url, max_age=600, refresh=True) -> Video or None
        The channel's live stream if it's live right now (its /streams tab, read like
        videos(), with a shorter cache).

    Y.cached(url) -> the same document as videos(), from the cache only (no yt-dlp,
        no network): for a panel drawing, or None.

    Y.channel_tab(url, tab="videos") -> the URL yt-dlp should read
        A channel's own page (https://www.youtube.com/@name) lists its tabs, so a
        channel URL gets its tab added: "videos" (its uploads, the default), "streams",
        "shorts" or "playlists". A playlist URL or a video URL is left as it is.

    Y.available() -> True when yt-dlp is installed.

Keeping videos (the den TV's `keep` setting): a copy on disk in the layout Plex and
Jellyfin read, so a kept video plays offline and a media server can show it too.

    Y.kept(folder, video_id) -> the kept file's path, or None
    Y.keep(video, folder, playlist=None, index=None) -> the file's path (raises KeepError)
        Downloads one video at a low priority (nice 19, ionice idle), with a .nfo and a
        thumbnail beside it:
          a channel's video:  <folder>/<Channel>/Season <year>/<YYYY-MM-DD> - <title>.<ext>
          a playlist's:       <folder>/<Playlist>/Season 1/S01E<index> - <title>.<ext>
    Y.prune(folder, max_gb) -> [paths removed]: the oldest kept videos go first, until the
        folder's kept videos fit. Only files keep() wrote are ever removed.
    Y.on_battery() -> True on a laptop running on its battery (no downloads then)
    Y.Keeper(log) -> a one-at-a-time download queue: .want(video, folder, playlist, index,
        max_gb) adds one (once), a thread works through them, and .busy says what it's on.

keep() records what it wrote in <folder>/.bromigos-keep.json.

A Video is a dict:

    {"id": "dQw4w9WgXcQ", "title": "…", "url": "https://www.youtube.com/watch?v=…",
     "duration": 212.0 (seconds, None for a live stream or an unknown length),
     "channel": "…" (or None), "thumbnail": "https://i.ytimg.com/…" (or None),
     "live": "is_live" | "was_live" | "is_upcoming" | None,
     "uploaded": unix seconds (or None; flat listings often don't say)}

The cache is ~/.cache/bromigos/youtube/<sha1 of the URL>.json. $BROMIGOS_YTDLP names
another yt-dlp (the tests point it at a stand-in that prints a recorded answer).
"""
import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile
import threading
import time

CACHE = os.path.join(os.environ.get("XDG_CACHE_HOME") or os.path.expanduser("~/.cache"), "bromigos", "youtube")
TABS = ("videos", "streams", "shorts", "playlists", "live")
_CHANNEL = re.compile(r"^https?://(?:www\.|m\.)?youtube\.com/(@[^/?#]+|channel/[^/?#]+|c/[^/?#]+|user/[^/?#]+)"
                      r"(?:/([a-z]+))?/?(?:[?#].*)?$")
_locks = {}
_locks_lock = threading.Lock()


def ytdlp():
    return os.environ.get("BROMIGOS_YTDLP") or shutil.which("yt-dlp")


def available():
    return bool(ytdlp())


def channel_tab(url, tab="videos"):
    """The URL to list: a channel's page gets its tab (videos unless it names one)."""
    url = (url or "").strip()
    m = _CHANNEL.match(url)
    if not m:
        return url
    if m.group(2) in TABS:
        return url
    base = url.split("?", 1)[0].split("#", 1)[0].rstrip("/")
    return f"{base}/{tab if tab in TABS else 'videos'}"


def is_channel(url):
    return bool(_CHANNEL.match((url or "").strip()))


def _path(url):
    return os.path.join(CACHE, hashlib.sha1(url.encode()).hexdigest() + ".json")


def cached(url, tab="videos"):
    """The cached document for url (no yt-dlp, no network), or None."""
    try:
        with open(_path(channel_tab(url, tab))) as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def _thumb(e):
    th = e.get("thumbnails") or []
    best = None
    for t in th:
        if not isinstance(t, dict) or not t.get("url"):
            continue
        w = t.get("width") or 0
        if best is None or (w and w <= 720 and w > (best.get("width") or 0)):
            best = t
    if best:
        return best["url"]
    vid = e.get("id")
    return f"https://i.ytimg.com/vi/{vid}/hqdefault.jpg" if vid else None


def _video(e):
    """A Video from one entry of yt-dlp's flat listing, or None (a nested tab, a deleted one)."""
    if not isinstance(e, dict):
        return None
    vid = e.get("id")
    if not vid or e.get("_type") == "playlist" or (e.get("ie_key") not in (None, "Youtube")):
        return None
    title = e.get("title") or ""
    if title in ("[Deleted video]", "[Private video]"):
        return None
    url = e.get("url") or ""
    if not url.startswith("http"):
        url = f"https://www.youtube.com/watch?v={vid}"
    dur = e.get("duration")
    return {"id": vid, "title": title, "url": url,
            "duration": float(dur) if isinstance(dur, (int, float)) and dur > 0 else None,
            "channel": e.get("channel") or e.get("uploader"), "thumbnail": _thumb(e),
            "live": e.get("live_status"), "uploaded": e.get("timestamp") or e.get("release_timestamp")}


def parse(doc, url=""):
    """yt-dlp's -J document -> {"url", "title", "channel", "videos"}. A channel's page that
    lists its tabs instead of videos gives the first tab's entries."""
    doc = doc or {}
    entries = doc.get("entries") or []
    if entries and all(isinstance(e, dict) and e.get("_type") == "playlist" for e in entries):
        entries = (entries[0] or {}).get("entries") or []        # tabs: the first (Videos)
    vids = [v for v in (_video(e) for e in entries) if v]
    return {"url": url or doc.get("webpage_url") or "", "title": doc.get("title") or "",
            "channel": doc.get("channel") or doc.get("uploader"), "videos": vids}


def _run(url, limit, timeout):
    exe = ytdlp()
    if not exe:
        raise RuntimeError("yt-dlp isn't installed (sudo pacman -S yt-dlp)")
    cmd = [exe, "--flat-playlist", "-J", "--no-warnings", "--ignore-no-formats-error",
           "--playlist-end", str(int(limit)), url]
    p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    if p.returncode != 0 or not p.stdout.strip():
        err = (p.stderr or "").strip().splitlines()
        raise RuntimeError((err[-1] if err else f"yt-dlp exited with {p.returncode}")[:200])
    return json.loads(p.stdout)


def _save(url, doc):
    os.makedirs(CACHE, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=CACHE, prefix=".yt-")
    with os.fdopen(fd, "w") as f:
        json.dump(doc, f)
    os.replace(tmp, _path(url))


def _fresh(doc, max_age):
    """Young enough to use: max_age seconds, or 5 minutes after a failure (then try again)."""
    if not doc:
        return False
    age = time.time() - (doc.get("fetched") or 0)
    return age < (min(max_age, 300) if doc.get("error") else max_age)


def videos(url, max_age=3600, limit=200, refresh=True, tab="videos", timeout=90):
    """A playlist's or channel's videos, cached (the module's docstring)."""
    target = channel_tab(url, tab)
    old = cached(target, tab) if target else None
    if _fresh(old, max_age):
        return old
    if not refresh or not target:
        return old or {"url": target, "title": "", "channel": None, "fetched": 0, "videos": [],
                       "error": None if target else "no URL"}
    with _locks_lock:
        lock = _locks.setdefault(target, threading.Lock())
    with lock:                                        # one yt-dlp per URL at a time
        again = cached(target, tab)
        if _fresh(again, max_age):                    # another thread just read it
            return again
        try:
            doc = parse(_run(target, limit, timeout), target)
            doc.update(fetched=time.time(), error=None)
        except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as e:
            doc = dict(old or {"url": target, "title": "", "channel": None, "videos": []},
                       fetched=time.time(), error=str(e)[:200])
        try:
            _save(target, doc)
        except OSError:
            pass
        return doc


def live_now(url, max_age=600, refresh=True):
    """The channel's live stream right now, or None (not a channel, nothing live)."""
    if not is_channel(url):
        return None
    doc = videos(url, max_age=max_age, limit=10, refresh=refresh, tab="streams")
    return next((v for v in doc.get("videos") or [] if v.get("live") == "is_live"), None)


# ------------------------------------------------------------------ keeping videos
INDEX = ".bromigos-keep.json"
KEEP_FORMAT = "bv*[height<=1080]+ba/b[height<=1080]/b"


class KeepError(RuntimeError):
    pass


def _index(folder):
    try:
        with open(os.path.join(folder, INDEX)) as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def _save_index(folder, d):
    fd, tmp = tempfile.mkstemp(dir=folder, prefix=".keep-")
    with os.fdopen(fd, "w") as f:
        json.dump(d, f, indent=1)
    os.replace(tmp, os.path.join(folder, INDEX))


def kept(folder, video_id):
    """The kept file for a video, when it's there."""
    if not folder or not video_id:
        return None
    folder = os.path.expanduser(folder)
    e = _index(folder).get(str(video_id)) or {}
    p = e.get("path")
    return p if p and os.path.isfile(p) else None


def _safe(name):
    name = re.sub(r'[\\/:*?"<>|\x00-\x1f]+', " ", str(name or "")).strip(" .")
    return re.sub(r"\s+", " ", name)[:120] or "YouTube"


def on_battery():
    try:
        import psutil
        b = psutil.sensors_battery()
        return bool(b is not None and b.power_plugged is False)
    except Exception:                                     # noqa: BLE001  no battery to read
        return False


def _xml(s):
    return (str(s or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


def _nfo(path, info, show, season, episode):
    """An episode .nfo beside the video, and the show's tvshow.nfo when it has none."""
    base = os.path.splitext(path)[0]
    up = str(info.get("upload_date") or "")
    aired = f"{up[:4]}-{up[4:6]}-{up[6:8]}" if len(up) == 8 else ""
    with open(base + ".nfo", "w") as f:
        f.write("<?xml version=\"1.0\" encoding=\"UTF-8\"?>\n<episodedetails>\n"
                f"  <title>{_xml(info.get('title'))}</title>\n  <showtitle>{_xml(show)}</showtitle>\n"
                f"  <season>{season}</season>\n  <episode>{episode}</episode>\n  <aired>{aired}</aired>\n"
                f"  <plot>{_xml(info.get('description'))}</plot>\n"
                f"  <uniqueid type=\"youtube\" default=\"true\">{_xml(info.get('id'))}</uniqueid>\n"
                "</episodedetails>\n")
    show_dir = os.path.dirname(os.path.dirname(path))
    tv = os.path.join(show_dir, "tvshow.nfo")
    if not os.path.exists(tv):
        with open(tv, "w") as f:
            f.write("<?xml version=\"1.0\" encoding=\"UTF-8\"?>\n<tvshow>\n"
                    f"  <title>{_xml(show)}</title>\n</tvshow>\n")
    thumb = base + "-thumb.jpg"
    poster = os.path.join(show_dir, "poster.jpg")
    if os.path.isfile(thumb) and not os.path.exists(poster):
        import shutil as _sh
        _sh.copyfile(thumb, poster)


def keep(video, folder, playlist=None, index=None, timeout=3 * 3600):
    """Download one video into folder (the module's docstring); its path."""
    exe = ytdlp()
    if not exe:
        raise KeepError("yt-dlp isn't installed")
    folder = os.path.expanduser(folder)
    os.makedirs(folder, exist_ok=True)
    have = kept(folder, video.get("id"))
    if have:
        return have
    if playlist:
        show = _safe(playlist)
        season, episode = 1, int(index or 0)
        stem = os.path.join(folder, show, "Season 1", f"S01E{episode:03d} - %(title)s")
    else:
        show = _safe(video.get("channel") or "%(channel)s")
        season, episode = None, None
        stem = os.path.join(folder, show, "Season %(upload_date>%Y)s", "%(upload_date>%Y-%m-%d)s - %(title)s")
    stem = stem.replace("%(title)s", "%(title).150B")
    cmd = [exe, "--no-playlist", "--no-warnings", "-f", KEEP_FORMAT, "--merge-output-format", "mkv",
           "--write-info-json", "--write-thumbnail", "--convert-thumbnails", "jpg",
           "-o", stem + ".%(ext)s", "-o", "thumbnail:" + stem + "-thumb.%(ext)s",
           "-o", "infojson:" + stem, "--print", "after_move:filepath", video["url"]]
    pre = []
    if shutil.which("nice"):
        pre += ["nice", "-n", "19"]
    if shutil.which("ionice"):
        pre += ["ionice", "-c", "3"]
    try:
        p = subprocess.run(pre + cmd, capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.SubprocessError) as e:
        raise KeepError(f"yt-dlp: {e}") from None
    path = next((ln.strip() for ln in reversed(p.stdout.splitlines()) if ln.strip()), "")
    if p.returncode != 0 or not path or not os.path.isfile(path):
        err = (p.stderr or "").strip().splitlines()
        raise KeepError((err[-1] if err else f"yt-dlp exited with {p.returncode}")[:200])
    base = os.path.splitext(path)[0]
    info = {}
    try:
        with open(base + ".info.json") as f:
            info = json.load(f)
        os.remove(base + ".info.json")
    except (OSError, ValueError):
        info = {"id": video.get("id"), "title": video.get("title")}
    if season is None:
        up = str(info.get("upload_date") or "")
        season = int(up[:4]) if up[:4].isdigit() else 1
        episode = int(up[4:8]) if up[4:8].isdigit() else 0
        show = os.path.basename(os.path.dirname(os.path.dirname(path)))
    _nfo(path, info, show, season, episode)
    files = [x for x in (path, base + ".nfo", base + "-thumb.jpg") if os.path.isfile(x)]
    d = _index(folder)
    d[str(video["id"])] = {"path": path, "files": files, "kept_at": time.time(),
                           "size": sum(os.path.getsize(x) for x in files), "title": video.get("title")}
    _save_index(folder, d)
    return path


def prune(folder, max_gb):
    """Remove the oldest kept videos (with their .nfo and thumbnail) until what keep() wrote
    in folder fits in max_gb. Files keep() didn't write are never touched."""
    if not folder or not max_gb:
        return []
    folder = os.path.expanduser(folder)
    d = _index(folder)
    cap = float(max_gb) * 1e9
    total = sum((e.get("size") or 0) for e in d.values())
    gone = []
    for vid, e in sorted(d.items(), key=lambda kv: kv[1].get("kept_at") or 0):
        if total <= cap:
            break
        for f in e.get("files") or []:
            if os.path.realpath(f).startswith(os.path.realpath(folder) + os.sep):
                try:
                    os.remove(f)
                    gone.append(f)
                except OSError:
                    pass
        total -= e.get("size") or 0
        del d[vid]
    if gone:
        _save_index(folder, d)
    return gone


class Keeper:
    """One download at a time, at a low priority, never on battery."""

    def __init__(self, log=print):
        self.log = log
        self.queue = []
        self.seen = set()
        self.busy = None
        self.lock = threading.Lock()
        self.wake = threading.Event()
        self.thread = None

    def want(self, video, folder, playlist=None, index=None, max_gb=None):
        if not video or not video.get("id") or not folder or kept(folder, video["id"]):
            return False
        with self.lock:
            if video["id"] in self.seen:
                return False
            self.seen.add(video["id"])
            self.queue.append((video, folder, playlist, index, max_gb))
        if self.thread is None:
            self.thread = threading.Thread(target=self._run, daemon=True, name="yt-keep")
            self.thread.start()
        self.wake.set()
        return True

    def _run(self):
        while True:
            self.wake.wait(60)
            self.wake.clear()
            while True:
                if on_battery():
                    break                                   # later, on mains power
                with self.lock:
                    job = self.queue.pop(0) if self.queue else None
                if job is None:
                    break
                video, folder, playlist, index, max_gb = job
                self.busy = video.get("title") or video.get("id")
                try:
                    path = keep(video, folder, playlist, index)
                    self.log(f"youtube: kept {os.path.basename(path)}")
                    for f in prune(folder, max_gb):
                        self.log(f"youtube: removed {os.path.basename(f)} (over keep_max_gb)")
                except Exception as e:                      # noqa: BLE001  an age-gated, removed or blocked video
                    self.log(f"youtube: couldn't keep {video.get('id')}: {e}")
                self.busy = None
