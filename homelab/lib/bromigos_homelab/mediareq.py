"""Media requests from the command line: `bromigos lab media search|get|status|upcoming|
language` (docs/lab.md, "Media requests"). Ask for a film, a show, an anime or music by
name, and your lab's *arr stack fetches it at the best quality its profiles allow.

Where each request goes:
  movies, TV   Seerr when one is configured (so the request shows in Seerr), else Radarr or
               Sonarr directly. Asking for more of a show already in Sonarr changes its
               monitoring in Sonarr ("also get season 4").
  music        Lidarr (an artist, or one album). When Lidarr's indexers find nothing for an
               album, slskd (Soulseek) searches, and Lidarr imports what it fetched.
  YouTube      a channel's or playlist's link goes to Pinchflat (`bromigos lab youtube add`).

What it reads (homelab.toml sources): seerr, arr (Sonarr, Radarr, Lidarr, Prowlarr and
Bazarr, each with its endpoint and API key), jellyfin and plex (is it there already?),
qbittorrent, sabnzbd and slskd (download progress), pinchflat. Every source is optional:
without Seerr it asks the *arr apps, without the download clients status reads the *arr
queues alone.

The profile: pick_profile() reads the quality profiles that exist (Recyclarr's TRaSH
profiles, usually) and their custom-format scores, and takes the best one for the kind of
media and your audio languages. It says which and why.

Settings, in homelab.toml (`bromigos lab media language` writes them):

    [media]
    audio = ["en", "ja"]       # audio languages, best first (ISO 639-1); default: the
                               # desktop's language. The first is required unless
    audio_required = true      # this is false (then it's only preferred); the others are
                               # welcome as extra tracks (a dual-audio release ranks first)
    anime_audio = ["ja"]       # anime's own, when it differs (default: audio)
    subtitles = ["en"]         # what Bazarr fetches (default: the first audio language)
    quality = "best"           # best, 2160p, 1080p or 720p
    seerr = true               # false: straight to the *arr apps even with Seerr configured
"""
import argparse
import concurrent.futures as cf
import datetime as dt
import json
import locale
import os
import re
import sys
import time
import urllib.error
import urllib.parse

ANIME_KEYWORD = 210024                 # TMDB's "anime" keyword (Seerr's own anime test)
GIB = 2 ** 30
MIB = 2 ** 20
APPS = ("sonarr", "radarr", "lidarr", "prowlarr", "bazarr")
QUALITIES = ("best", "2160p", "1080p", "720p")
LANG_NAMES = {"en": "English", "ja": "Japanese", "fr": "French", "de": "German", "es": "Spanish", "it": "Italian",
              "pt": "Portuguese", "ko": "Korean", "zh": "Chinese", "ru": "Russian", "nl": "Dutch", "sv": "Swedish",
              "no": "Norwegian", "da": "Danish", "fi": "Finnish", "pl": "Polish", "hi": "Hindi", "ar": "Arabic"}
# Sonarr/Radarr name languages, mediainfo says ISO 639-2
LANG3 = {"eng": "en", "jpn": "ja", "fre": "fr", "fra": "fr", "ger": "de", "deu": "de", "spa": "es", "ita": "it",
         "por": "pt", "kor": "ko", "chi": "zh", "zho": "zh", "rus": "ru", "dut": "nl", "nld": "nl", "swe": "sv",
         "nor": "no", "dan": "da", "fin": "fi", "pol": "pl", "hin": "hi", "ara": "ar"}
STATE_FILE = os.path.join(os.environ.get("XDG_STATE_HOME") or os.path.expanduser("~/.local/state"), "bromigos",
                          "media-requests.json")


class MediaError(Exception):
    pass


class Ambiguous(MediaError):
    def __init__(self, query, matches):
        self.matches = matches
        super().__init__(f"{len(matches)} matches for {query!r}: say which (an id from `bromigos lab media search`)")


# ------------------------------------------------------------------ languages
def lang_code(v):
    """'en', 'English', 'eng' or 'en_US' -> 'en'; '' when unknown."""
    v = str(v or "").strip()
    if not v:
        return ""
    low = v.lower()
    if low in ("any", "original"):
        return low
    if low in LANG3:
        return LANG3[low]
    for c, n in LANG_NAMES.items():
        if low == n.lower():
            return c
    m = re.match(r"^([a-z]{2})(?:[_\-.@].*)?$", low)
    return m.group(1) if m else ""


def lang_name(c):
    return LANG_NAMES.get(c, c)


def desktop_language():
    """The desktop locale's language ('en' for C/POSIX or nothing set)."""
    for var in ("LC_ALL", "LC_MESSAGES", "LANG"):
        v = os.environ.get(var)
        if v and v not in ("C", "POSIX") and not v.startswith("C."):
            return lang_code(v) or "en"
    try:
        loc = locale.getlocale()[0]
    except ValueError:
        loc = None
    return lang_code(loc) or "en"


def _codes(v):
    if isinstance(v, str):
        v = re.split(r"[,\s]+", v)
    return [c for c in (lang_code(x) for x in (v or [])) if c]


def languages(table=None):
    """{audio, anime_audio, required, subtitles, from}: the [media] settings, or the desktop's
    language where they're missing."""
    if table is None:
        from . import config
        table = config.table("media")
    audio = _codes(table.get("audio"))
    src = "settings" if audio else "the desktop's language"
    audio = audio or [desktop_language()]
    anime = _codes(table.get("anime_audio")) or list(audio)
    subs = _codes(table.get("subtitles")) or [audio[0] if audio[0] not in ("any", "original") else desktop_language()]
    req = table.get("audio_required")
    return {"audio": audio, "anime_audio": anime, "required": True if req is None else bool(req),
            "subtitles": subs, "from": src}


def describe_audio(langs, required):
    """'English (required), Japanese welcome as a second track'."""
    if not langs or langs[0] == "any":
        return "any language"
    if langs[0] == "original":
        return "the original language"
    head = lang_name(langs[0]) + (" required" if required else " preferred")
    if len(langs) > 1:
        head += ", " + " and ".join(lang_name(x) for x in langs[1:]) + " welcome as a second track"
    return head


# ------------------------------------------------------------------ homelab.toml's [media]
def _toml_value(v):
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int, float)):
        return str(v)
    if isinstance(v, (list, tuple)):
        return "[" + ", ".join(_toml_value(x) for x in v) + "]"
    return json.dumps(str(v))


def edit_media_table(text, updates):
    """text with homelab.toml's [media] table changed: each key in updates set (None removes
    it), other lines and comments kept. A missing table is added at the end."""
    lines = text.splitlines()
    head = next((i for i, ln in enumerate(lines) if re.match(r"^\s*\[media\]\s*(#.*)?$", ln)), None)
    if head is None:
        add = [f"{k} = {_toml_value(v)}" for k, v in updates.items() if v is not None]
        tail = "" if not lines or not lines[-1].strip() else "\n"
        return text.rstrip("\n") + ("\n" if text.strip() else "") + tail + "[media]\n" + "\n".join(add) + "\n"
    end = next((i for i in range(head + 1, len(lines)) if re.match(r"^\s*\[", lines[i])), len(lines))
    body = lines[head + 1:end]
    done = set()
    out = []
    for ln in body:
        m = re.match(r"^\s*([A-Za-z0-9_]+)\s*=", ln)
        if m and m.group(1) in updates:
            k = m.group(1)
            done.add(k)
            if updates[k] is None:
                continue
            comment = re.search(r"\s+(#.*)$", ln)
            keep = comment.group(1) if comment and not re.search(r"[\"\]]", comment.group(1)) else ""
            out.append(f"{k} = {_toml_value(updates[k])}" + (f"   {keep}" if keep else ""))
        else:
            out.append(ln)
    extra = [f"{k} = {_toml_value(v)}" for k, v in updates.items() if k not in done and v is not None]
    # new keys after the table's last setting, before its trailing blank lines
    at = len(out)
    while at > 0 and not out[at - 1].strip():
        at -= 1
    out[at:at] = extra
    return "\n".join(lines[:head + 1] + out + lines[end:]) + ("\n" if text.endswith("\n") or not text else "")


def write_media_settings(updates, path=None):
    """Set keys of [media] in the user's homelab.toml (through a symlink, to its target),
    checking the result reads back before it replaces the file."""
    import tomllib
    from . import config
    path = os.path.realpath(path or config.USER)
    try:
        with open(path) as f:
            text = f.read()
    except FileNotFoundError:
        text = ""
    new = edit_media_table(text, updates)
    try:
        got = tomllib.loads(new).get("media") or {}
    except ValueError as e:
        raise MediaError(f"{path}: the edit wouldn't parse ({e}); nothing was written") from None
    for k, v in updates.items():
        if v is not None and got.get(k) != (list(v) if isinstance(v, tuple) else v):
            raise MediaError(f"{path}: [media] {k} didn't read back as written; nothing was written")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        f.write(new)
    os.replace(tmp, path)
    return path


# ------------------------------------------------------------------ quality profiles
SOURCE_RANK = {"unknown": 0, "television": 1, "tv": 1, "dvd": 2, "webrip": 3, "webRip": 3, "web": 4, "bluray": 5,
               "blurayRaw": 6, "remux": 6}
LOSSLESS = re.compile(r"flac|alac|ape|wavpack|wav\b|lossless|pcm", re.I)
LOSSY_RANK = [(re.compile(r"320|v0|high quality", re.I), 3), (re.compile(r"256|v2|mid quality", re.I), 2),
              (re.compile(r"192|160|low quality", re.I), 1)]


def _allowed(profile):
    """The allowed qualities of a profile, flattened out of its groups: [{name, resolution, source}]."""
    out = []

    def walk(items, allowed_parent=None):
        for it in items or []:
            ok = it.get("allowed") if allowed_parent is None else allowed_parent
            if it.get("items"):
                walk(it["items"], ok)
            elif ok and it.get("quality"):
                q = it["quality"]
                out.append({"name": q.get("name") or "", "resolution": q.get("resolution") or 0,
                            "source": "remux" if q.get("modifier") == "remux" else q.get("source") or "",
                            "group": it.get("name")})
    walk(profile.get("items"))
    return out


def video_rank(q):
    res = q.get("resolution") or (2160 if "2160" in q["name"] else 1080 if "1080" in q["name"] else
                                  720 if "720" in q["name"] else 480 if "480" in q["name"] else 0)
    src = "remux" if "remux" in q["name"].lower() else q.get("source") or ""
    return (res, SOURCE_RANK.get(src, SOURCE_RANK.get(src.lower(), 0)))


def audio_rank(q):
    if LOSSLESS.search(q["name"]) or LOSSLESS.search(q.get("group") or ""):
        return 4
    for rx, r in LOSSY_RANK:
        if rx.search(q["name"]) or rx.search(q.get("group") or ""):
            return r
    return 0


def _scores(profile):
    return {(fi.get("name") or "").lower(): fi.get("score") or 0 for fi in profile.get("formatItems") or []}


def profile_audio(profile):
    """What a profile does with audio language, from its custom-format scores:
    {"requires": "en" | None, "english_first": bool, "original": bool, "dual": bool}.
      requires       a release without that language can't be grabbed (Language: Not English
                     very negative, or English formats needed to reach the minimum score)
      english_first  dual audio or an English dub scores above everything else
      original       dub-only releases are rejected: the original (Japanese) audio is wanted
      dual           a dual-audio release (English + Japanese) ranks first"""
    s = _scores(profile)
    not_en = s.get("language: not english", 0)
    dual = s.get("anime dual audio", 0) or s.get("dual audio", 0)
    dub = s.get("dubs only", 0)
    minfs = profile.get("minFormatScore") or 0
    english = [v for k, v in s.items() if k in ("anime dual audio", "dual audio", "dubs only") and v > 0]
    others = sorted((v for k, v in s.items() if v > 0 and k not in ("anime dual audio", "dual audio", "dubs only")),
                    reverse=True)
    # what a release with no English track can reach: one tier (TRaSH's release-group tiers,
    # 100 and up, are mutually exclusive) plus a few of the small bonuses that stack on it
    # (a streaming service, a version, a repack)
    big = [v for v in others if v >= 100]
    reach = (big[0] if big else 0) + sum([v for v in others if v < 100][:3])
    requires = "en" if not_en <= -1000 or (english and minfs > 0 and minfs > reach) else None
    return {"requires": requires, "english_first": bool(english) and max(english) > reach,
            "original": dub <= -1000, "dual": dual > 0 and dual >= max(english or [0])}


def describe_profile_audio(a):
    if a["requires"] == "en" and a["dual"]:
        return "English audio required; dual audio (English + Japanese) ranked first"
    if a["requires"] == "en":
        return "English audio required"
    if a["english_first"]:
        return "dual audio, then an English dub, ranked first; Japanese-only allowed"
    if a["original"]:
        return "the original audio (dub-only releases rejected)"
    return "no audio-language rule"


def trash_managed(profile):
    """A profile with custom-format scores (Recyclarr's TRaSH profiles have them; the apps'
    built-in ones don't)."""
    return any(fi.get("score") for fi in profile.get("formatItems") or [])


def is_anime_profile(profile):
    s = _scores(profile)
    return "anime" in (profile.get("name") or "").lower() or any(k.startswith("anime ") for k in s if s[k])


def _audio_fit(a, langs, required, anime):
    """How well a profile's audio rule fits the wanted languages: higher is better."""
    first = langs[0] if langs else "any"
    if first == "en":
        if required:
            return 3 if a["requires"] == "en" and (a["dual"] or not anime) else 2 if a["requires"] == "en" else \
                1 if a["english_first"] else 0
        return 3 if a["english_first"] and not a["requires"] else 2 if a["english_first"] else \
            1 if a["requires"] == "en" else 0
    if first in ("any",):
        return 2 if not a["requires"] and not a["english_first"] else 1 if not a["requires"] else 0
    # Japanese, the original, or any other language first
    return 3 if a["original"] else 1 if not a["requires"] and not a["english_first"] else 0


def pick_profile(kind, profiles, langs=None, required=True, anime=False, quality="best"):
    """The best quality profile for a request, and why.

    kind      movie | tv | music
    profiles  the app's quality profiles (its /qualityprofile answer)
    langs     the audio languages, best first (["en", "ja"]); required: the first must be there
    anime     an anime: TRaSH's anime profiles first, then the audio rule decides among them
    quality   best, or a ceiling: 2160p, 1080p, 720p

    -> {"profile": {...}, "id", "name", "why", "audio": profile_audio(), "top": the best
    quality it allows, "warnings": [...]}; None when there are no profiles."""
    langs = langs or ["any"]
    profiles = [p for p in profiles or [] if _allowed(p)]
    if not profiles:
        return None
    warn = []
    if kind == "music":
        def mrank(p):
            ranks = [audio_rank(q) for q in _allowed(p)]
            return (max(ranks), min(ranks), p.get("upgradeAllowed") or False)
        best = max(profiles, key=mrank)
        top = max(_allowed(best), key=audio_rank)
        lossless = audio_rank(top) == 4
        why = (f"{best['name']}: " + ("lossless (FLAC), the best audio this Lidarr allows" if lossless else
                                       f"its best is {top['name']}; no lossless profile here") +
               (", and nothing lossy" if mrank(best)[1] == 4 else ""))
        return {"profile": best, "id": best["id"], "name": best["name"], "why": why, "top": top["name"],
                "audio": None, "warnings": warn if lossless else ["no lossless profile in Lidarr"]}
    ceiling = {"2160p": 2160, "1080p": 1080, "720p": 720}.get(quality or "best")

    def top_of(p):
        qs = _allowed(p)
        top = max(qs, key=video_rank) if qs else None
        return None if top is None or (ceiling and video_rank(top)[0] > ceiling) else top   # it would grab more
    cands = [p for p in profiles if top_of(p)]
    if not cands:
        return None
    pool = cands
    if anime:
        an = [p for p in cands if is_anime_profile(p)]
        if an:
            pool = an
        else:
            warn.append("no anime profile here: add TRaSH's anime profile to Recyclarr")
    else:
        live = [p for p in cands if not is_anime_profile(p)]
        pool = live or cands
    managed = [p for p in pool if trash_managed(p)]
    if managed:
        pool = managed
    langs_for = langs

    def rank(p):
        a = profile_audio(p)
        return (_audio_fit(a, langs_for, required, anime), video_rank(top_of(p)), bool(p.get("upgradeAllowed")),
                -len(p.get("name") or ""))
    best = max(pool, key=rank)
    a = profile_audio(best)
    top = top_of(best)
    fit = _audio_fit(a, langs, required, anime)
    bits = [f"the best {'anime ' if anime and is_anime_profile(best) else ''}profile here",
            f"up to {top['name']}"]
    if trash_managed(best):
        bits.append("a TRaSH profile")
    why = f"{best['name']}: " + ", ".join(bits) + "; " + describe_profile_audio(a)
    if langs and langs[0] not in ("any",) and fit < 2:
        warn.append(f"no profile here matches {describe_audio(langs, required)}. {best['name']}: "
                    f"{describe_profile_audio(a)}")
    if ceiling and video_rank(top)[0] < ceiling:
        warn.append(f"nothing here goes to {quality}; {best['name']} stops at {top['name']}")
    return {"profile": best, "id": best["id"], "name": best["name"], "why": why, "top": top["name"], "audio": a,
            "warnings": warn}


# ------------------------------------------------------------------ anime
def detect_anime(meta):
    """(anime?, why) from a title's metadata: TMDB's anime keyword (Seerr's test), TVDB's Anime
    genre (Sonarr), Sonarr's series type, or animation in Japanese."""
    kws = meta.get("keywords") or []
    if any((k.get("id") if isinstance(k, dict) else None) == ANIME_KEYWORD or
           str(k.get("name") if isinstance(k, dict) else k).lower() == "anime" for k in kws):
        return True, "TMDB's anime keyword"
    if (meta.get("seriesType") or "").lower() == "anime":
        return True, "Sonarr's series type is anime"
    genres = [str(g.get("name") if isinstance(g, dict) else g).lower() for g in meta.get("genres") or []]
    if "anime" in genres:
        return True, "the Anime genre"
    lang = meta.get("originalLanguage")
    lang = lang_code(lang.get("name") if isinstance(lang, dict) else lang)
    countries = [str(c).upper() for c in (meta.get("originCountry") or meta.get("productionCountries") or [])]
    if "animation" in genres and (lang == "ja" or "JP" in countries):
        return True, "animation in Japanese"
    return False, ""


# ------------------------------------------------------------------ sizes
def mb_per_minute(profile, qdefs, top=None):
    """Typical MiB per minute for a profile's best quality, from the app's quality sizes
    (Recyclarr sets TRaSH's): the preferred size, else the middle of min and max, else twice
    the minimum."""
    top = top or (max(_allowed(profile), key=video_rank)["name"] if profile else None)
    d = next((x for x in qdefs or [] if (x.get("quality") or {}).get("name") == top or x.get("title") == top), None)
    if not d:
        return None
    lo, hi, pref = d.get("minSize") or 0, d.get("maxSize"), d.get("preferredSize")
    if pref:
        return float(pref)
    if hi:
        return (lo + hi) / 2.0
    return lo * 2.0 if lo else None


def estimate(minutes, rate):
    return int(minutes * rate * MIB) if minutes and rate else None


def human(b):
    if b is None:
        return "?"
    for unit, n in (("TB", 1e12), ("GB", 1e9), ("MB", 1e6), ("kB", 1e3)):
        if b >= n:
            return f"{b / n:.0f} {unit}" if b >= 10 * n else f"{b / n:.1f} {unit}"
    return f"{b} B"


def hm(s):
    if s is None:
        return "?"
    s = int(s)
    if s >= 86400:
        return f"{s // 86400} d {s % 86400 // 3600} h"
    if s >= 3600:
        return f"{s // 3600} h {s % 3600 // 60:02d} min"
    return f"{max(1, s // 60)} min"


# ------------------------------------------------------------------ the lab's media apps
def arr_app(a):
    """Which *arr app an `arr` source is: its `app` option, its name, else what it says it is."""
    app = (a.opts.get("app") or "").lower()
    if app in APPS:
        return app
    if (a.name or "").lower() in APPS:
        return a.name.lower()
    for v in ("v3", "v1"):
        try:
            s = a.request(f"/api/{v}/system/status", timeout=5) or {}
        except Exception:
            continue
        name = (s.get("appName") or "").lower()
        if name in APPS:
            return name
    return ""


API = {"sonarr": "/api/v3", "radarr": "/api/v3", "lidarr": "/api/v1", "prowlarr": "/api/v1", "bazarr": "/api"}


class Lab:
    """The configured media sources, and the calls this needs (cached for one command)."""

    def __init__(self, instances=None, settings=None):
        from . import config, registry
        inst = registry.instances() if instances is None else instances
        self.settings = config.table("media") if settings is None else settings
        self.arr, self.by_type = {}, {}
        for a in inst:
            if a.type == "arr":
                if a.endpoint:
                    app = arr_app(a)
                    if app:
                        self.arr.setdefault(app, a)
            elif a.type in ("seerr", "jellyfin", "plex", "qbittorrent", "sabnzbd", "slskd", "pinchflat"):
                self.by_type.setdefault(a.type, a)
        self._cache = {}

    # ---- who's here
    def app(self, name):
        return self.arr.get(name)

    def src(self, type_):
        return self.by_type.get(type_)

    @property
    def seerr(self):
        return self.by_type.get("seerr") if self.settings.get("seerr", True) is not False else None

    def configured(self):
        return bool(self.arr or self.seerr)

    def names(self):
        return sorted(list(self.arr) + list(self.by_type))

    # ---- HTTP
    def call(self, a, path, data=None, method=None, timeout=20):
        try:
            return a.request(path, data=data, method=method, timeout=timeout)
        except urllib.error.HTTPError as e:
            try:
                body = e.read()[:600].decode("utf-8", "replace")
                d = json.loads(body)
                msg = d.get("message") or d.get("error") or (d[0].get("errorMessage") if isinstance(d, list) and d
                                                               and isinstance(d[0], dict) else body)
            except Exception:
                msg = ""
            raise MediaError(f"{a.name}: {method or ('POST' if data is not None else 'GET')} {path.split('?')[0]}: "
                             f"HTTP {e.code}" + (f": {str(msg)[:200]}" if msg else "")) from None
        except OSError as e:
            raise MediaError(f"{a.name}: {str(e)[:200]}") from None

    def arr_get(self, app, path, **q):
        a = self.app(app)
        if not a:
            raise MediaError(f"no {app} source in homelab.toml")
        qs = ("?" + urllib.parse.urlencode(q, doseq=True)) if q else ""
        return self.call(a, API[app] + path + qs)

    def arr_send(self, app, path, data, method="POST"):
        return self.call(self.app(app), API[app] + path, data=data, method=method, timeout=30)

    def cached(self, key, fn):
        if key not in self._cache:
            self._cache[key] = fn()
        return self._cache[key]

    def profiles(self, app):
        return self.cached(("profiles", app), lambda: self.arr_get(app, "/qualityprofile") or [])

    def qdefs(self, app):
        return self.cached(("qdefs", app), lambda: self.arr_get(app, "/qualitydefinition") or [])

    def root(self, app):
        """(path, free bytes) of the app's first root folder."""
        def get():
            rf = self.arr_get(app, "/rootfolder") or []
            if not rf:
                raise MediaError(f"{app} has no root folder: set one in its Settings › Media Management")
            return rf[0].get("path"), rf[0].get("freeSpace")
        return self.cached(("root", app), get)

    def seerr_server(self, kind):
        """Seerr's default (non-4K) Sonarr or Radarr server, or None."""
        def get():
            if not self.seerr:
                return None
            try:
                servers = self.call(self.seerr, f"/api/v1/settings/{'sonarr' if kind == 'tv' else 'radarr'}") or []
            except MediaError:
                return None
            pool = [s for s in servers if not s.get("is4k")]
            return next((s for s in pool if s.get("isDefault")), pool[0] if pool else None)
        return self.cached(("seerr-server", kind), get)


# ------------------------------------------------------------------ titles
def _year(d):
    return int(d[:4]) if d and str(d)[:4].isdigit() else None


def _day(d):
    return str(d)[:10] if d else None


def _poster(path):
    if not path:
        return None
    return path if path.startswith("http") else "https://image.tmdb.org/t/p/w342" + path


def _today():
    return dt.date.today().isoformat()


def movie_dates(d):
    """{cinemas, digital, physical} from Seerr's (TMDB's) release dates, or Radarr's fields."""
    out = {"cinemas": _day(d.get("inCinemas")), "digital": _day(d.get("digitalRelease")),
           "physical": _day(d.get("physicalRelease"))}
    rel = ((d.get("releases") or {}).get("results")) or []
    order = sorted(rel, key=lambda r: r.get("iso_3166_1") != "US")
    for r in order:
        for x in r.get("release_dates") or []:
            k = {3: "cinemas", 2: "cinemas", 4: "digital", 5: "physical"}.get(x.get("type"))
            day = _day(x.get("release_date"))
            if k and day and (not out[k] or (r.get("iso_3166_1") == "US" and day < out[k])):
                out[k] = day
    if not out["cinemas"] and d.get("releaseDate"):
        out["cinemas"] = _day(d["releaseDate"])
    return out


def release_text(item):
    """'released', 'in cinemas 2026-12-18, digital TBA', 'returning: S03E01 on 2026-11-02', …"""
    today = _today()
    d = item.get("dates") or {}
    if item["kind"] == "movie":
        home = [x for x in (d.get("digital"), d.get("physical")) if x]
        if home and min(home) <= today:
            return "released"
        year_ago = (dt.date.today() - dt.timedelta(days=365)).isoformat()
        if not home and d.get("cinemas") and d["cinemas"] < year_ago:
            return "released"                 # out for over a year: TMDB just has no home date
        bits = []
        if d.get("cinemas"):
            bits.append(("in cinemas since " if d["cinemas"] <= today else "in cinemas ") + d["cinemas"])
        bits.append("digital " + (d.get("digital") or "TBA"))
        if d.get("physical"):
            bits.append("disc " + d["physical"])
        return ", ".join(bits) if d.get("cinemas") or d.get("digital") else "announced, no dates yet"
    if item["kind"] == "tv":
        st = (item.get("status") or "").lower()
        nxt = d.get("next")
        if nxt:
            return f"returning: {nxt['code']} on {nxt['date']}"
        if d.get("first_aired") and d["first_aired"] > today:
            return f"premieres {d['first_aired']}"
        if "ended" in st or "canceled" in st:
            return "ended"
        return st or "?"
    return ""


class Item(dict):
    """A title: kind movie | tv | artist | album | youtube, and what's known about it."""


def item_from_seerr(kind, d):
    it = Item(kind=kind, title=d.get("title") or d.get("name"), tmdb=d.get("id"),
              overview=(d.get("overview") or "")[:400], poster=_poster(d.get("posterPath")),
              original_language=lang_code(d.get("originalLanguage")), genres=[g.get("name") for g in d.get("genres") or []
                                                                              if isinstance(g, dict)],
              keywords=d.get("keywords") or [], seerr=d.get("mediaInfo") or None)
    ext = d.get("externalIds") or {}
    if kind == "movie":
        it.update(year=_year(d.get("releaseDate")), imdb=d.get("imdbId") or ext.get("imdbId"),
                  runtime=d.get("runtime"), status=d.get("status"), dates=movie_dates(d),
                  countries=[c.get("iso_3166_1") for c in d.get("productionCountries") or []])
    else:
        seasons = [{"number": s.get("seasonNumber"), "episodes": s.get("episodeCount") or 0,
                    "air_date": _day(s.get("airDate"))} for s in d.get("seasons") or []]
        nxt = d.get("nextEpisodeToAir") or {}
        it.update(year=_year(d.get("firstAirDate")), tvdb=ext.get("tvdbId"), imdb=ext.get("imdbId"),
                  runtime=(d.get("episodeRunTime") or [None])[0], status=d.get("status"), seasons=seasons,
                  countries=d.get("originCountry") or [],
                  dates={"first_aired": _day(d.get("firstAirDate")),
                         "next": {"code": f"S{nxt.get('seasonNumber', 0):02d}E{nxt.get('episodeNumber', 0):02d}",
                                  "date": _day(nxt.get("airDate"))} if nxt.get("airDate") else None})
    it["id"] = f"{kind}:tmdb:{it['tmdb']}" if kind == "movie" or not it.get("tvdb") else f"tv:tvdb:{it['tvdb']}"
    return it


def item_from_radarr(r):
    it = Item(kind="movie", title=r.get("title"), year=r.get("year"), tmdb=r.get("tmdbId"), imdb=r.get("imdbId"),
              overview=(r.get("overview") or "")[:400], poster=r.get("remotePoster"), runtime=r.get("runtime"),
              status=r.get("status"), dates=movie_dates(r), genres=r.get("genres") or [],
              keywords=r.get("keywords") or [], original_language=lang_code((r.get("originalLanguage") or {}).get("name")))
    it["id"] = f"movie:tmdb:{it['tmdb']}"
    return it


def item_from_sonarr(s):
    seasons = [{"number": x.get("seasonNumber"), "episodes": (x.get("statistics") or {}).get("totalEpisodeCount")}
               for x in s.get("seasons") or []]
    it = Item(kind="tv", title=s.get("title"), year=s.get("year"), tvdb=s.get("tvdbId"), tmdb=s.get("tmdbId") or None,
              imdb=s.get("imdbId"), overview=(s.get("overview") or "")[:400], poster=s.get("remotePoster"),
              runtime=s.get("runtime"), status=s.get("status"), seasons=seasons, genres=s.get("genres") or [],
              keywords=[], original_language=lang_code((s.get("originalLanguage") or {}).get("name")),
              seriesType=s.get("seriesType"), dates={"first_aired": _day(s.get("firstAired")), "next": None})
    nxt = s.get("nextAiring")
    if nxt:
        it["dates"]["next"] = {"code": "next episode", "date": _day(nxt)}
    it["id"] = f"tv:tvdb:{it['tvdb']}"
    return it


def finish(lab, it, langs=None):
    """Fill in what search and get show: anime, library state, the profile, the size."""
    anime, why = detect_anime({"keywords": it.get("keywords"), "genres": it.get("genres"),
                               "originalLanguage": it.get("original_language"), "originCountry": it.get("countries"),
                               "seriesType": (it.get("arr") or {}).get("seriesType") or it.get("seriesType")})
    it["anime"], it["anime_why"] = anime, why
    it["release"] = release_text(it)
    langs = langs or languages(lab.settings)
    app = "radarr" if it["kind"] == "movie" else "sonarr"
    if lab.app(app):
        try:
            choice = pick_profile(it["kind"], lab.profiles(app), langs["anime_audio" if anime else "audio"],
                                  langs["required"], anime, lab.settings.get("quality") or "best")
        except MediaError:
            choice = None
        if choice:
            it["profile"] = {k: choice[k] for k in ("id", "name", "why", "top", "warnings")}
            rate = mb_per_minute(choice["profile"], lab.qdefs(app), choice["top"])
            if it["kind"] == "movie":
                it["size"] = estimate(it.get("runtime"), rate)
            else:
                eps = sum(s.get("episodes") or 0 for s in it.get("seasons") or [] if s.get("number"))
                it["episodes"] = eps
                it["size"] = estimate((it.get("runtime") or 0) * eps, rate)
    return it


def _arr_state(lab, it):
    """The title in Sonarr or Radarr already? {id, monitored, profile, files, episodes, path}."""
    try:
        if it["kind"] == "movie" and lab.app("radarr") and it.get("tmdb"):
            r = lab.arr_get("radarr", "/movie/lookup/tmdb", tmdbId=it["tmdb"])
            r = r[0] if isinstance(r, list) and r else r
            if isinstance(r, dict):
                it.setdefault("dates", movie_dates(r))
                if not it.get("runtime"):
                    it["runtime"] = r.get("runtime")
                r = _radarr_movie(lab, it["tmdb"]) or r
                if r.get("id"):
                    it["arr"] = {"app": "radarr", "id": r["id"], "monitored": r.get("monitored"),
                                 "has_file": r.get("hasFile"), "profile_id": r.get("qualityProfileId"),
                                 "availability": r.get("minimumAvailability")}
        elif it["kind"] == "tv" and lab.app("sonarr") and it.get("tvdb"):
            r = lab.arr_get("sonarr", "/series/lookup", term=f"tvdb:{it['tvdb']}")
            r = r[0] if isinstance(r, list) and r else None
            if r:
                if not it.get("genres"):
                    it["genres"] = r.get("genres") or []
                else:
                    it["genres"] = list(dict.fromkeys(list(it["genres"]) + list(r.get("genres") or [])))
                if not it.get("tmdb") and r.get("tmdbId"):
                    it["tmdb"] = r["tmdbId"]
                if r.get("id"):
                    st = r.get("statistics") or {}
                    it["arr"] = {"app": "sonarr", "id": r["id"], "monitored": r.get("monitored"),
                                 "profile_id": r.get("qualityProfileId"), "seriesType": r.get("seriesType"),
                                 "files": st.get("episodeFileCount"), "episodes": st.get("totalEpisodeCount")}
    except MediaError as e:
        it.setdefault("errors", []).append(str(e))
    return it


# ------------------------------------------------------------------ is it there already?
def _res_label(width):
    if not width:
        return None
    return "4K" if width >= 3200 else "1080p" if width >= 1700 else "720p" if width >= 1100 else "SD"


def _streams_info(ms):
    v = next((s for s in ms if s.get("Type") == "Video"), {})
    aud = [lang_code(s.get("Language")) for s in ms if s.get("Type") == "Audio"]
    subs = [lang_code(s.get("Language")) for s in ms if s.get("Type") == "Subtitle"]
    return _res_label(v.get("Width")), [a for a in dict.fromkeys(aud) if a], [s for s in dict.fromkeys(subs) if s]


def in_jellyfin(lab, it):
    a = lab.src("jellyfin")
    if not a or it["kind"] not in ("movie", "tv"):
        return None
    typ = "Movie" if it["kind"] == "movie" else "Series"
    q = urllib.parse.urlencode({"Recursive": "true", "searchTerm": it["title"], "IncludeItemTypes": typ,
                                "Fields": "ProviderIds,ProductionYear,MediaSources", "Limit": 20})
    d = lab.call(a, f"/Items?{q}") or {}
    ids = {"Tmdb": str(it.get("tmdb") or ""), "Tvdb": str(it.get("tvdb") or ""), "Imdb": str(it.get("imdb") or "")}
    hit = next((x for x in d.get("Items") or [] if any(v and (x.get("ProviderIds") or {}).get(k) == v
                                                       for k, v in ids.items())), None)
    if not hit:
        return None
    out = {"server": a.name, "id": hit.get("Id")}
    if it["kind"] == "movie":
        out["resolution"], out["audio"], out["subtitles"] = _streams_info(
            ((hit.get("MediaSources") or [{}])[0]).get("MediaStreams") or [])
        return out
    sq = urllib.parse.urlencode({"ParentId": hit["Id"], "IncludeItemTypes": "Season", "Limit": 0})
    eq = urllib.parse.urlencode({"ParentId": hit["Id"], "Recursive": "true", "IncludeItemTypes": "Episode",
                                 "Fields": "MediaSources", "Limit": 1})
    seasons = lab.call(a, f"/Items?{sq}") or {}
    eps = lab.call(a, f"/Items?{eq}") or {}
    out["seasons"] = seasons.get("TotalRecordCount")
    out["episodes"] = eps.get("TotalRecordCount")
    one = (eps.get("Items") or [{}])[0]
    out["resolution"], out["audio"], out["subtitles"] = _streams_info(
        ((one.get("MediaSources") or [{}])[0]).get("MediaStreams") or [])
    return out if out["episodes"] else None


def in_plex(lab, it):
    a = lab.src("plex")
    if not a or it["kind"] not in ("movie", "tv"):
        return None
    hdr = {"Accept": "application/json"}
    q = urllib.parse.urlencode({"query": it["title"], "includeGuids": 1, "limit": 20})
    d = a.request(f"/hubs/search?{q}", headers=hdr, timeout=15) or {}
    want = {f"tmdb://{it.get('tmdb')}", f"tvdb://{it.get('tvdb')}", f"imdb://{it.get('imdb')}"}
    typ = "movie" if it["kind"] == "movie" else "show"
    for h in (d.get("MediaContainer") or {}).get("Hub") or []:
        for m in h.get("Metadata") or []:
            if m.get("type") == typ and want & {g.get("id") for g in m.get("Guid") or []}:
                out = {"server": a.name, "id": m.get("ratingKey")}
                if typ == "movie":
                    r = ((m.get("Media") or [{}])[0]).get("videoResolution")
                    out["resolution"] = {"4k": "4K", "1080": "1080p", "720": "720p"}.get(str(r).lower(), r and "SD")
                else:
                    out["seasons"], out["episodes"] = m.get("childCount"), m.get("leafCount")
                return out
    return None


def library_check(lab, it):
    """{"jellyfin": {...}, "plex": {...}} for the servers that already have it."""
    out = {}
    for name, fn in (("jellyfin", in_jellyfin), ("plex", in_plex)):
        try:
            r = fn(lab, it)
        except Exception:                                  # noqa: BLE001  a server down never stops a request
            r = None
        if r:
            out[name] = r
    return out


def describe_library(lib):
    """'Already in Jellyfin: 4K, 9 seasons (201 episodes), English audio'."""
    out = []
    for name, r in lib.items():
        bits = [b for b in (r.get("resolution"),
                            f"{r['seasons']} season{'s' if r['seasons'] != 1 else ''}" if r.get("seasons") else None,
                            f"{r['episodes']} episode{'s' if r['episodes'] != 1 else ''}" if r.get("episodes") else None,
                            ("audio " + "+".join(lang_name(x) for x in r["audio"])) if r.get("audio") else None) if b]
        out.append(f"Already in {name.title() if name != 'jellyfin' else 'Jellyfin'}" + (": " + ", ".join(bits) if bits else ""))
    return out


# ------------------------------------------------------------------ search
YOUTUBE = re.compile(r"^https?://(www\.|m\.|music\.)?(youtube\.com|youtu\.be)/", re.I)


def youtube_item(url):
    kind = "playlist" if "list=" in url else "video" if re.search(r"watch\?v=|youtu\.be/|/shorts/", url) else "channel"
    return Item(kind="youtube", id=url, title=url, youtube=kind)


def video_search(lab, query, kind=None, limit=8):
    want = {"movie": ("movie",), "tv": ("tv",), "anime": ("movie", "tv")}.get(kind, ("movie", "tv"))
    found = []
    if lab.seerr:
        d = lab.call(lab.seerr, "/api/v1/search?" + urllib.parse.urlencode({"query": query, "page": 1},
                                                                          quote_via=urllib.parse.quote)) or {}
        hits = [r for r in d.get("results") or [] if r.get("mediaType") in want][:limit]

        def detail(r):
            d = lab.call(lab.seerr, f"/api/v1/{r['mediaType']}/{r['id']}")
            return item_from_seerr(r["mediaType"], d)
        with cf.ThreadPoolExecutor(6) as ex:
            found = [f.result() for f in [ex.submit(detail, r) for r in hits]]
    else:
        if "movie" in want and lab.app("radarr"):
            found += [item_from_radarr(r) for r in (lab.arr_get("radarr", "/movie/lookup", term=query) or [])[:limit]]
        if "tv" in want and lab.app("sonarr"):
            found += [item_from_sonarr(s) for s in (lab.arr_get("sonarr", "/series/lookup", term=query) or [])[:limit]]

    def enrich(it):
        _arr_state(lab, it)
        finish(lab, it)
        it["library"] = library_check(lab, it)
        return it
    with cf.ThreadPoolExecutor(6) as ex:
        found = [f.result() for f in [ex.submit(enrich, it) for it in found]]
    if kind == "anime":
        found = [it for it in found if it.get("anime")]
    return found


def artist_item(a):
    return Item(kind="artist", id=f"artist:{a.get('foreignArtistId')}", title=a.get("artistName"),
                mbid=a.get("foreignArtistId"), overview=(a.get("overview") or "")[:300],
                disambiguation=a.get("disambiguation"), artist_type=a.get("artistType"), status=a.get("status"),
                poster=next((i.get("remoteUrl") for i in a.get("images") or [] if i.get("coverType") == "poster"), None),
                arr={"app": "lidarr", "id": a["id"]} if a.get("id") else None)


def album_item(al):
    artist = al.get("artist") or {}
    tracks = sum(m.get("trackCount") or 0 for rel in (al.get("releases") or [])[:1] for m in rel.get("media") or [])
    return Item(kind="album", id=f"album:{al.get('foreignAlbumId')}", title=al.get("title"),
                artist=artist.get("artistName"), artist_mbid=artist.get("foreignArtistId"),
                mbid=al.get("foreignAlbumId"), year=_year(al.get("releaseDate")), album_type=al.get("albumType"),
                minutes=round((al.get("duration") or 0) / 60000) or None, tracks=tracks or None,
                poster=al.get("remoteCover"), raw=al,
                arr={"app": "lidarr", "id": al["id"], "monitored": al.get("monitored")} if al.get("id") else None)


def music_finish(lab, it):
    if it["kind"] == "album" and lab.app("lidarr"):
        try:
            choice = pick_profile("music", lab.profiles("lidarr"))
        except MediaError:
            choice = None
        if choice:
            it["profile"] = {k: choice[k] for k in ("id", "name", "why", "top", "warnings")}
            rate = 6.5 if "lossless" in choice["why"].lower() else 2.4      # MiB/min: 16-bit FLAC, 320k MP3
            it["size"] = estimate(it.get("minutes"), rate)
    return it


def music_search(lab, query, limit=10):
    if not lab.app("lidarr"):
        return []
    out = []
    for r in (lab.arr_get("lidarr", "/search", term=query) or [])[:limit * 2]:
        if r.get("artist"):
            out.append(artist_item(r["artist"]))
        elif r.get("album"):
            out.append(album_item(r["album"]))
    return [music_finish(lab, it) for it in out[:limit]]


def search(lab, query, kind=None, limit=8):
    query = query.strip()
    if YOUTUBE.match(query):
        return [youtube_item(query)]
    out = []
    if kind != "music":
        out += video_search(lab, query, kind, limit)
    if kind == "music" or (kind is None and not out):
        out += music_search(lab, query, limit)
    return out


# ------------------------------------------------------------------ which title
REF = re.compile(r"^(movie|tv):(tmdb|tvdb):(\d+)$|^(artist|album):([0-9a-f\-]{36})$")


def _norm_title(t):
    return re.sub(r"[^a-z0-9]+", " ", re.sub(r"^(the|a|an)\s+", "", (t or "").lower())).strip()


def item_by_ref(lab, ref):
    m = REF.match(ref)
    kind, idkind, num, mkind, mbid = m.groups()
    if mkind:
        found = lab.arr_get("lidarr", f"/{mkind}/lookup", term=f"lidarr:{mbid}") or []
        hit = next((x for x in found if (x.get("foreignArtistId") if mkind == "artist" else x.get("foreignAlbumId"))
                    == mbid), None)
        if not hit:
            raise MediaError(f"Lidarr doesn't know {ref}")
        return music_finish(lab, artist_item(hit) if mkind == "artist" else album_item(hit))
    if lab.seerr and idkind == "tmdb":
        it = item_from_seerr(kind, lab.call(lab.seerr, f"/api/v1/{kind}/{num}"))
    elif kind == "movie":
        r = lab.arr_get("radarr", "/movie/lookup/tmdb", tmdbId=num)
        it = item_from_radarr(r[0] if isinstance(r, list) else r)
    else:
        res = lab.arr_get("sonarr", "/series/lookup", term=f"tvdb:{num}") or []
        if not res:
            raise MediaError(f"Sonarr doesn't know {ref}")
        it = item_from_sonarr(res[0])
        if lab.seerr and it.get("tmdb"):
            try:
                it = item_from_seerr("tv", lab.call(lab.seerr, f"/api/v1/tv/{it['tmdb']}"))
            except MediaError:
                pass
    _arr_state(lab, it)
    finish(lab, it)
    it["library"] = library_check(lab, it)
    return it


def resolve(lab, what, kind=None):
    """An id (movie:tmdb:603, tv:tvdb:76885, album:<mbid>) or a name. A name must match one
    title: exactly one result, or one whose title (and year, "Title (1999)") is exactly the
    name. Otherwise Ambiguous, with the candidates."""
    what = what.strip()
    if REF.match(what):
        return item_by_ref(lab, what)
    if YOUTUBE.match(what):
        return youtube_item(what)
    m = re.match(r"^(.*?)\s*\((\d{4})\)\s*$", what)
    name, year = (m.group(1), int(m.group(2))) if m else (what, None)
    hits = search(lab, name, kind)
    if year:
        hits = [h for h in hits if h.get("year") == year] or hits
    if len(hits) == 1:
        return hits[0]
    exact = [h for h in hits if _norm_title(h.get("title")) == _norm_title(name) and (not year or h.get("year") == year)]
    if len(exact) == 1:
        return exact[0]
    if not hits:
        raise MediaError(f"nothing found for {what!r}")
    raise Ambiguous(what, exact or hits)


# ------------------------------------------------------------------ seasons and episodes
def parse_seasons(spec):
    """all | latest | future | none, or season numbers from "1,3" and "2-4"."""
    s = str(spec or "all").strip().lower()
    if s in ("all", "latest", "future", "none"):
        return s
    out = set()
    for part in s.split(","):
        part = part.strip().lstrip("s")
        m = re.fullmatch(r"(\d+)\s*-\s*s?(\d+)", part)
        if m:
            out.update(range(int(m.group(1)), int(m.group(2)) + 1))
        elif part.isdigit():
            out.add(int(part))
        elif part:
            raise MediaError(f"--seasons {spec!r}: all, latest, future, or numbers like 1,3 or 2-4")
    return sorted(out)


def parse_episodes(spec):
    if not spec:
        return []
    eps = [(int(a), int(b)) for a, b in re.findall(r"s(\d+)\s*e(\d+)", spec, re.I)]
    if not eps:
        raise MediaError(f"--episodes {spec!r}: like S02E05,S03E01")
    return eps


def _span_text(nums):
    """[1, 2, 3, 5] -> '1–3 and 5'."""
    nums = sorted(set(nums))
    runs, start = [], None
    for i, n in enumerate(nums):
        if start is None:
            start = n
        if i == len(nums) - 1 or nums[i + 1] != n + 1:
            runs.append(f"{start}–{n}" if n > start else str(n))
            start = None
    return ", ".join(runs[:-1]) + (" and " if len(runs) > 1 else "") + runs[-1] if runs else ""


def describe_monitoring(series):
    """'Monitoring seasons 1–3 and specials; new episodes are picked up automatically.'"""
    seasons = series.get("seasons") or []
    on = [s["seasonNumber"] for s in seasons if s.get("monitored") and s["seasonNumber"] > 0]
    special = any(s.get("monitored") for s in seasons if s["seasonNumber"] == 0)
    if not series.get("monitored"):
        what = "Not monitored"
    elif on:
        what = ("Monitoring season " if len(on) == 1 else "Monitoring seasons ") + _span_text(on) + \
            (" and specials" if special else "")
    elif special:
        what = "Monitoring specials only"
    else:
        what = "Monitoring no whole season"
    new = series.get("monitorNewItems") == "all"
    return what + ("; new episodes and seasons are picked up automatically" if new else
                   "; new seasons are not picked up")


# ------------------------------------------------------------------ requests
def _audio_wanted(lab, it, audio=None):
    langs = languages(lab.settings)
    if audio:
        a = lang_code(audio) or audio
        return ([a] if a != "any" else ["any"]), a not in ("any", "original")
    return langs["anime_audio" if it.get("anime") else "audio"], langs["required"]


def plan(lab, it, seasons="all", episodes=None, new=None, specials=False, quality=None, audio=None, when=None):
    """What `get` would do, before it does anything: the app, the profile and why, the
    route (Seerr or the app), what gets monitored, the estimated size and the free space."""
    if it["kind"] == "youtube":
        return {"item": it, "app": "pinchflat", "route": "pinchflat", "quality": quality}
    if it["kind"] in ("artist", "album"):
        return plan_music(lab, it, new, quality)
    app = "radarr" if it["kind"] == "movie" else "sonarr"
    if not lab.app(app):
        raise MediaError(f"no {app} source in homelab.toml: add one ([[source]] type = \"arr\", name = \"{app}\")")
    langs, required = _audio_wanted(lab, it, audio)
    choice = pick_profile(it["kind"], lab.profiles(app), langs, required, it.get("anime"),
                          quality or lab.settings.get("quality") or "best")
    if not choice:
        raise MediaError(f"{app} has no quality profile to use")
    root, free = lab.root(app)
    existing = it.get("arr")
    p = {"item": it, "app": app, "profile": {k: choice[k] for k in ("id", "name", "why", "top", "warnings")},
         "audio": {"wanted": langs, "required": required, "text": describe_audio(langs, required),
                   "profile": describe_profile_audio(choice["audio"])},
         "root": root, "free": free, "existing": existing,
         "change_profile": existing is None or quality is not None or audio is not None,
         "library": it.get("library") or {}}
    rate = mb_per_minute(choice["profile"], lab.qdefs(app), choice["top"])
    server = lab.seerr_server(it["kind"])
    if it["kind"] == "movie":
        p["when"] = {"announced": "announced", "cinemas": "inCinemas", "released": "released"}.get(when or "released")
        if not p["when"]:
            raise MediaError(f"--when {when!r}: announced, cinemas or released")
        p["size"] = estimate(it.get("runtime"), rate)
        p["route"] = "seerr" if server and not existing else "radarr"
        p["seerr_server"] = server
        return p
    spec = parse_seasons(seasons)
    eps = parse_episodes(episodes)
    real = [s for s in it.get("seasons") or [] if s.get("number")]
    latest = max((s["number"] for s in real), default=None)
    if eps:
        now = []
        n_eps = len(eps)
    else:
        now = ([s["number"] for s in real] if spec == "all" else [latest] if spec == "latest" and latest else
               [] if spec in ("future", "none") else spec)
        if specials:
            now = [0] + [n for n in now if n]
        n_eps = sum(s.get("episodes") or 0 for s in it.get("seasons") or [] if s.get("number") in now)
    if new is None:
        new = spec != "none"
    p.update(seasons=spec, episodes=eps, specials=bool(specials), new=bool(new), now=now, latest=latest,
             size=estimate((it.get("runtime") or 0) * n_eps, rate), episode_count=n_eps)
    seerr_ok = server and not existing and not eps and spec not in ("future", "none")
    p["route"] = "seerr" if seerr_ok else "sonarr"
    p["seerr_server"] = server
    return p


def _wait(fn, timeout=60, every=2.0):
    end = time.time() + timeout
    while True:
        v = fn()
        if v or time.time() >= end:
            return v
        time.sleep(every)


def _command(lab, app, name, **kw):
    return lab.arr_send(app, "/command", dict(kw, name=name))


def _sonarr_id(lab, tvdb):
    r = lab.arr_get("sonarr", "/series/lookup", term=f"tvdb:{tvdb}") or []
    return r[0].get("id") if r and r[0].get("id") else None


def _radarr_movie(lab, tmdb):
    """The film in Radarr's library, or None (its lookup doesn't say whether it's added)."""
    r = lab.arr_get("radarr", "/movie", tmdbId=tmdb) or []
    return r[0] if isinstance(r, list) and r else None


def _radarr_id(lab, tmdb):
    return (_radarr_movie(lab, tmdb) or {}).get("id")


MONITOR = {"all": "all", "latest": "latestSeason", "future": "future"}


def apply_monitoring(lab, sid, p, fresh):
    """Set a series' profile, type, seasons, specials and new-item monitoring as planned,
    then search for what's wanted now. fresh: just added (other seasons off), else what's
    monitored already stays ("also get season 4")."""
    it = p["item"]
    s = lab.arr_get("sonarr", f"/series/{sid}")
    if p["change_profile"]:
        s["qualityProfileId"] = p["profile"]["id"]
    if it.get("anime"):
        s["seriesType"] = "anime"
    s["monitored"] = True
    s["monitorNewItems"] = "all" if p["new"] else "none"
    searches = []
    spec = p["seasons"]
    if p["episodes"]:
        lab.arr_send("sonarr", f"/series/{sid}", s, "PUT")
        eps = lab.arr_get("sonarr", "/episode", seriesId=sid) or []
        ids = [e["id"] for e in eps if (e.get("seasonNumber"), e.get("episodeNumber")) in set(p["episodes"])]
        if not ids:
            raise MediaError("Sonarr has none of those episodes (yet): check the numbers, or try again in a minute")
        lab.arr_send("sonarr", "/episode/monitor", {"episodeIds": ids, "monitored": True}, "PUT")
        searches.append({"name": "EpisodeSearch", "episodeIds": ids})
    elif isinstance(spec, str) and spec in MONITOR:
        lab.arr_send("sonarr", f"/series/{sid}", s, "PUT")
        lab.arr_send("sonarr", "/seasonpass", {"series": [{"id": sid, "monitored": True}],
                                               "monitoringOptions": {"monitor": MONITOR[spec]}})
        s = lab.arr_get("sonarr", f"/series/{sid}")
        if spec == "all":
            searches.append({"name": "SeriesSearch", "seriesId": sid})
        elif spec == "latest" and p.get("latest"):
            searches.append({"name": "SeasonSearch", "seriesId": sid, "seasonNumber": p["latest"]})
    elif isinstance(spec, list):
        for season in s.get("seasons") or []:
            n = season["seasonNumber"]
            if n in spec:
                season["monitored"] = True
            elif fresh and n:
                season["monitored"] = False
        searches += [{"name": "SeasonSearch", "seriesId": sid, "seasonNumber": n} for n in spec]
    if p["specials"]:
        for season in s.get("seasons") or []:
            if season["seasonNumber"] == 0:
                season["monitored"] = True
        searches.append({"name": "SeasonSearch", "seriesId": sid, "seasonNumber": 0})
    s["monitorNewItems"] = "all" if p["new"] else "none"
    s = lab.arr_send("sonarr", f"/series/{sid}", s, "PUT") or s
    for c in searches:
        lab.arr_send("sonarr", "/command", c)
    return s, searches


def run(lab, p):
    """Do what plan() planned. -> {"route", "app", "id", "say", …}"""
    it = p["item"]
    if it["kind"] == "youtube":
        from . import pinchflat
        pf, s = pinchflat.connect()
        rec = pinchflat.add_source(pf, s, it["id"], None, None, None, p.get("quality"))
        return {"route": "pinchflat", "app": "pinchflat", "say": pinchflat.describe_add(rec), "pinchflat": rec}
    if it["kind"] in ("artist", "album"):
        return run_music(lab, p)
    if it["kind"] == "movie":
        return run_movie(lab, p)
    return run_tv(lab, p)


def _seerr_request(lab, body):
    try:
        return lab.call(lab.seerr, "/api/v1/request", data=body, method="POST")
    except MediaError as e:
        if "409" in str(e) or "already" in str(e).lower():
            return None
        raise


def run_tv(lab, p):
    it = p["item"]
    out = {"app": "sonarr", "route": p["route"]}
    sid = (p.get("existing") or {}).get("id")
    fresh = False
    if p["route"] == "seerr":
        srv = p["seerr_server"]
        seasons = "all" if p["seasons"] == "all" else ([p["latest"]] if p["seasons"] == "latest" else p["seasons"])
        req = _seerr_request(lab, {"mediaType": "tv", "mediaId": it["tmdb"], "tvdbId": it.get("tvdb"),
                                   "seasons": seasons, "is4k": False, "serverId": srv["id"],
                                   "profileId": p["profile"]["id"], "rootFolder": p["root"]})
        if req:
            out["seerr_request"] = req.get("id")
        sid = _wait(lambda: _sonarr_id(lab, it["tvdb"]), 60)
        if not sid:
            out["say"] = "Seerr took the request; Sonarr hasn't added the show yet. It searches once it has."
            return out
        fresh = True
        if p["specials"] or not p["new"] or it.get("anime"):
            s = lab.arr_get("sonarr", f"/series/{sid}")
            s["monitorNewItems"] = "all" if p["new"] else "none"
            if it.get("anime"):
                s["seriesType"] = "anime"
            s["qualityProfileId"] = p["profile"]["id"]
            if p["specials"]:
                for season in s.get("seasons") or []:
                    if season["seasonNumber"] == 0:
                        season["monitored"] = True
            s = lab.arr_send("sonarr", f"/series/{sid}", s, "PUT") or s
            if p["specials"]:
                _command(lab, "sonarr", "SeasonSearch", seriesId=sid, seasonNumber=0)
        else:
            s = lab.arr_get("sonarr", f"/series/{sid}")
    else:
        if not sid:
            look = lab.arr_get("sonarr", "/series/lookup", term=f"tvdb:{it['tvdb']}")
            if not look:
                raise MediaError(f"Sonarr can't find TVDB {it['tvdb']}")
            body = dict(look[0], qualityProfileId=p["profile"]["id"], rootFolderPath=p["root"], monitored=True,
                        seasonFolder=True, seriesType="anime" if it.get("anime") else "standard",
                        monitorNewItems="all" if p["new"] else "none",
                        addOptions={"monitor": "none", "searchForMissingEpisodes": False,
                                    "searchForCutoffUnmetEpisodes": False})
            body.pop("id", None)
            sid = lab.arr_send("sonarr", "/series", body)["id"]
            fresh = True
            _wait(lambda: lab.arr_get("sonarr", "/episode", seriesId=sid), 60)
        s, searches = apply_monitoring(lab, sid, p, fresh)
        out["searches"] = [c["name"] for c in searches]
    out.update(id=sid, monitoring=describe_monitoring(s), profile=p["profile"]["name"],
               series_type=s.get("seriesType"))
    return out


def run_movie(lab, p):
    it = p["item"]
    out = {"app": "radarr", "route": p["route"]}
    mid = (p.get("existing") or {}).get("id")
    if p["route"] == "seerr":
        srv = p["seerr_server"]
        req = _seerr_request(lab, {"mediaType": "movie", "mediaId": it["tmdb"], "is4k": False, "serverId": srv["id"],
                                   "profileId": p["profile"]["id"], "rootFolder": p["root"]})
        if req:
            out["seerr_request"] = req.get("id")
        mid = _wait(lambda: _radarr_id(lab, it["tmdb"]), 60)
        if not mid:
            out["say"] = "Seerr took the request; Radarr hasn't added the film yet."
            return out
    elif not mid:
        look = lab.arr_get("radarr", "/movie/lookup/tmdb", tmdbId=it["tmdb"])
        look = look[0] if isinstance(look, list) else look
        body = dict(look, qualityProfileId=p["profile"]["id"], rootFolderPath=p["root"], monitored=True,
                    minimumAvailability=p["when"], addOptions={"searchForMovie": True, "monitor": "movieOnly"})
        body.pop("id", None)
        mid = lab.arr_send("radarr", "/movie", body)["id"]
        out.update(id=mid, profile=p["profile"]["name"], availability=p["when"])
        return out
    m = lab.arr_get("radarr", f"/movie/{mid}")
    changed = False
    if p["change_profile"] and m.get("qualityProfileId") != p["profile"]["id"]:
        m["qualityProfileId"], changed = p["profile"]["id"], True
    if m.get("minimumAvailability") != p["when"]:
        m["minimumAvailability"], changed = p["when"], True
    if not m.get("monitored"):
        m["monitored"], changed = True, True
    if changed:
        m = lab.arr_send("radarr", f"/movie/{mid}", m, "PUT") or m
    if p["route"] != "seerr" or changed:
        _command(lab, "radarr", "MoviesSearch", movieIds=[mid])
    out.update(id=mid, profile=p["profile"]["name"], availability=m.get("minimumAvailability"))
    return out


# ------------------------------------------------------------------ music
def plan_music(lab, it, new=None, quality=None):
    if not lab.app("lidarr"):
        raise MediaError("no lidarr source in homelab.toml")
    choice = pick_profile("music", lab.profiles("lidarr"))
    meta = lab.cached(("meta", "lidarr"), lambda: lab.arr_get("lidarr", "/metadataprofile") or [])
    root, free = lab.root("lidarr")
    return {"item": it, "app": "lidarr", "route": "lidarr",
            "profile": {k: choice[k] for k in ("id", "name", "why", "top", "warnings")},
            "metadata_profile": next((m["id"] for m in meta if m.get("name") == "Standard"), meta[0]["id"] if meta else 1),
            "root": root, "free": free, "existing": it.get("arr"), "size": it.get("size"),
            "new": True if new is None else bool(new), "slskd": bool(lab.src("slskd")), "library": {}}


def run_music(lab, p):
    it = p["item"]
    out = {"app": "lidarr", "route": "lidarr", "profile": p["profile"]["name"]}
    if it["kind"] == "artist":
        if p["existing"]:
            a = lab.arr_get("lidarr", f"/artist/{p['existing']['id']}")
            a.update(monitored=True, monitorNewItems="all" if p["new"] else "none")
            lab.arr_send("lidarr", f"/artist/{a['id']}", a, "PUT")
            _command(lab, "lidarr", "ArtistSearch", artistId=a["id"])
            out["id"] = a["id"]
        else:
            body = {"artistName": it["title"], "foreignArtistId": it["mbid"], "qualityProfileId": p["profile"]["id"],
                    "metadataProfileId": p["metadata_profile"], "rootFolderPath": p["root"], "monitored": True,
                    "monitorNewItems": "all" if p["new"] else "none",
                    "addOptions": {"monitor": "all", "searchForMissingAlbums": True}}
            out["id"] = lab.arr_send("lidarr", "/artist", body)["id"]
        out["say"] = f"Lidarr is fetching {it['title']}'s albums in {p['profile']['name']}."
        return out
    if p["existing"]:
        aid = p["existing"]["id"]
        lab.arr_send("lidarr", "/album/monitor", {"albumIds": [aid], "monitored": True}, "PUT")
    else:
        al = dict(it.get("raw") or {})
        artist = dict(al.get("artist") or {}, qualityProfileId=p["profile"]["id"],
                      metadataProfileId=p["metadata_profile"], rootFolderPath=p["root"], monitored=True,
                      monitorNewItems="none", addOptions={"monitor": "none", "searchForMissingAlbums": False})
        al.update(artist=artist, monitored=True, addOptions={"searchForNewAlbum": False})
        aid = lab.arr_send("lidarr", "/album", al)["id"]
    cmd = _command(lab, "lidarr", "AlbumSearch", albumIds=[aid])
    out["id"] = aid
    done = _wait(lambda: (lab.arr_get("lidarr", f"/command/{cmd['id']}") or {}).get("status") in
                 ("completed", "failed", "aborted"), 120, 3)
    queued = [q for q in (lab.arr_get("lidarr", "/queue", pageSize=200) or {}).get("records") or []
              if q.get("albumId") == aid]
    if queued:
        out["say"] = f"Lidarr found it and is downloading it ({queued[0].get('protocol')}, {queued[0].get('downloadClient')})."
        return out
    if not done:
        out["say"] = "Lidarr is still searching; `bromigos lab media status` will say what it finds."
        return out
    if not p["slskd"]:
        out["say"] = "Lidarr's indexers found nothing for it. It keeps looking; no Soulseek (slskd) source to try."
        out["nothing_found"] = True
        return out
    got = slskd_fetch(lab, it, aid)
    out["route"] = "soulseek"
    out.update(got)
    return out


AUDIO_EXT = (".flac", ".alac", ".m4a", ".mp3", ".ogg", ".opus", ".wav", ".ape", ".wv", ".aiff")


def pick_soulseek(responses, tracks=None):
    """The best folder among slskd's search answers: complete (the album's track count), lossless,
    a free upload slot, fast. -> {user, directory, files: [{filename, size}], lossless, score} or None."""
    best = None
    for r in responses or []:
        dirs = {}
        for f in r.get("files") or []:
            name = f.get("filename") or ""
            if not name.lower().endswith(AUDIO_EXT):
                continue
            d = name.replace("\\", "/").rsplit("/", 1)[0]
            dirs.setdefault(d, []).append(f)
        for d, files in dirs.items():
            n = len(files)
            if tracks and n < max(1, int(tracks * 0.8)):
                continue
            lossless = sum(1 for f in files if LOSSLESS.search(os.path.splitext(f["filename"])[1]))
            score = (2 if lossless == n else 0, 1 if r.get("hasFreeUploadSlot") else 0,
                     -(r.get("queueLength") or 0), r.get("uploadSpeed") or 0)
            if best is None or score > best["score"]:
                best = {"user": r.get("username"), "directory": d.replace("/", "\\"), "score": score,
                        "lossless": lossless == n, "files": [{"filename": f["filename"], "size": f.get("size")}
                                                              for f in files]}
    return best


def slskd_fetch(lab, it, album_id=None, wait=45):
    """Search Soulseek for an album and download the best folder; Lidarr imports it once it's
    done (status finishes it). -> {"say", "soulseek": {...}}"""
    import uuid
    a = lab.src("slskd")
    sid = str(uuid.uuid4())
    text = f"{it.get('artist') or ''} {it['title']}".strip()
    lab.call(a, "/api/v0/searches", data={"id": sid, "searchText": text}, method="POST")
    _wait(lambda: "Completed" in str((lab.call(a, f"/api/v0/searches/{sid}") or {}).get("state")), wait, 3)
    responses = lab.call(a, f"/api/v0/searches/{sid}/responses") or []
    pick = pick_soulseek(responses, it.get("tracks"))
    if not pick:
        return {"say": f"Lidarr's indexers and Soulseek ({len(responses)} answers) found no complete copy of "
                       f"{text}. Lidarr keeps looking.", "nothing_found": True}
    lab.call(a, f"/api/v0/transfers/downloads/{urllib.parse.quote(pick['user'])}", data=pick["files"], method="POST")
    folder = pick["directory"].replace("\\", "/").rstrip("/").rsplit("/", 1)[-1]
    base = (a.opts.get("import_path") or "").rstrip("/")
    st = _state()
    st.setdefault("soulseek", []).append({"user": pick["user"], "directory": pick["directory"], "album_id": album_id,
                                          "title": text, "import_path": f"{base}/{folder}" if base else None,
                                          "started": time.time()})
    _save_state(st)
    return {"say": f"Lidarr's indexers found nothing, so Soulseek: downloading {len(pick['files'])} "
                   f"{'lossless ' if pick['lossless'] else ''}files from {pick['user']}. Lidarr imports them into "
                   "your music library when they're done.",
            "soulseek": {"user": pick["user"], "folder": folder, "files": len(pick["files"]),
                         "lossless": pick["lossless"]}}


def _state():
    try:
        with open(STATE_FILE) as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def _save_state(st):
    os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)
    tmp = STATE_FILE + ".tmp"
    with open(tmp, "w") as f:
        json.dump(st, f, indent=1)
    os.replace(tmp, STATE_FILE)


def finish_soulseek(lab):
    """Hand finished Soulseek downloads to Lidarr (DownloadedAlbumsScan on their folder).
    -> [what was handed over]"""
    a = lab.src("slskd")
    st = _state()
    pending = st.get("soulseek") or []
    if not a or not pending or not lab.app("lidarr"):
        return []
    from .adapters.labrequests import folders_of_transfers
    folders = {(f["user"], f["directory"]): f for f in folders_of_transfers(lab.call(a, "/api/v0/transfers/downloads"))}
    done, keep = [], []
    for x in pending:
        f = folders.get((x["user"], x["directory"]))
        if f and f["state"] == "completed" and x.get("import_path"):
            _command(lab, "lidarr", "DownloadedAlbumsScan", path=x["import_path"])
            done.append(dict(x, imported=time.time()))
        elif f and f["state"] == "failed":
            done.append(dict(x, failed=True))
        elif time.time() - x.get("started", 0) < 14 * 86400:
            keep.append(x)
    if done:
        st["soulseek"] = keep
        st["soulseek_done"] = (st.get("soulseek_done") or [])[-50:] + done
        _save_state(st)
    return done


# ------------------------------------------------------------------ subtitles (Bazarr)
def _form(lab, a, path, fields):
    import urllib.request
    body = urllib.parse.urlencode(fields, doseq=True).encode()
    req = urllib.request.Request(a.endpoint + path, data=body, method="POST",
                                 headers=dict(a.auth_headers(), **{"Content-Type": "application/x-www-form-urlencoded"}))
    try:
        with urllib.request.urlopen(req, timeout=20, context=a._ctx()) as r:
            return r.status
    except urllib.error.HTTPError as e:
        raise MediaError(f"{a.name}: POST {path}: HTTP {e.code}") from None


def bazarr_profile(lab, langs, make=True):
    """Bazarr's language profile for these subtitle languages (made, and set as the default
    for new series and films, when missing). -> (id, name) or (None, why)."""
    a = lab.app("bazarr")
    if not a:
        return None, "no bazarr source"
    profiles = lab.call(a, "/api/system/languages/profiles") or []
    for p in profiles:
        if [i.get("language") for i in p.get("items") or []] == list(langs):
            return p["profileId"], p["name"]
    if not make:
        return None, "Bazarr has no profile for " + ", ".join(lang_name(x) for x in langs)
    pid = max([p["profileId"] for p in profiles] + [0]) + 1
    name = " + ".join(lang_name(x) for x in langs)
    new = {"profileId": pid, "name": name, "cutoff": None, "mustContain": [], "mustNotContain": [],
           "originalFormat": False, "tag": None,
           "items": [{"id": i + 1, "language": c, "audio_exclude": "False", "audio_only_include": "False",
                      "hi": "False", "forced": "False"} for i, c in enumerate(langs)]}
    enabled = [x.get("code2") for x in lab.call(a, "/api/system/languages?history=false") or [] if x.get("enabled")]
    _form(lab, a, "/api/system/settings", {
        "languages-enabled": list(dict.fromkeys(enabled + list(langs))),
        "languages-profiles": json.dumps(profiles + [new]),
        "settings-general-serie_default_enabled": "true", "settings-general-serie_default_profile": str(pid),
        "settings-general-movie_default_enabled": "true", "settings-general-movie_default_profile": str(pid)})
    return pid, name


def bazarr_assign(lab, app, arr_id, langs):
    """Give a series or film the subtitle profile (Bazarr knows it once it has synced from
    Sonarr or Radarr, every few minutes; new ones get the default profile anyway)."""
    pid, name = bazarr_profile(lab, langs)
    if not pid:
        return name
    a = lab.app("bazarr")
    if app == "sonarr":
        _form(lab, a, "/api/series", {"seriesid": arr_id, "profileid": pid})
    else:
        _form(lab, a, "/api/movies", {"radarrid": arr_id, "profileid": pid})
    return f"subtitles: {name} (Bazarr)"


def subtitle_state(lab, app, arr_id, langs):
    """{lang: "found N" | "searching N" | "not wanted"} and per-episode detail, from Bazarr."""
    a = lab.app("bazarr")
    if not a:
        return None
    if app == "sonarr":
        rows = (lab.call(a, f"/api/episodes?seriesid[]={arr_id}") or {}).get("data") or []
        series = ((lab.call(a, f"/api/series?seriesid[]={arr_id}") or {}).get("data") or [{}])[0]
        profile = series.get("profileId")
    else:
        rows = (lab.call(a, f"/api/movies?radarrid[]={arr_id}") or {}).get("data") or []
        profile = (rows[0] if rows else {}).get("profileId")
    out = {}
    for c in langs:
        have = sum(1 for r in rows if any(s.get("code2") == c for s in r.get("subtitles") or []))
        miss = sum(1 for r in rows if any(s.get("code2") == c for s in r.get("missing_subtitles") or []))
        out[c] = {"found": have, "searching": miss, "files": len(rows)}
    return {"profile": profile, "languages": out}


def describe_subs(sub):
    if sub is None:
        return None
    if not sub.get("profile"):
        return "Bazarr has no subtitle profile for it"
    bits = []
    for c, s in sub["languages"].items():
        if not s["files"]:
            bits.append(f"{lang_name(c)} subs: waiting for the files")
        elif s["searching"] and not s["found"]:
            bits.append(f"{lang_name(c)} subs: searching")
        elif s["searching"]:
            bits.append(f"{lang_name(c)} subs: found for {s['found']} of {s['files']}, searching for {s['searching']}")
        else:
            bits.append(f"{lang_name(c)} subs: found")
    return "; ".join(bits)


# ------------------------------------------------------------------ status
def _secs(hms):
    if not hms:
        return None
    m = re.match(r"(?:(\d+)\.)?(\d+):(\d+):(\d+)", str(hms))
    if not m:
        return None
    d, h, mi, s = (int(x or 0) for x in m.groups())
    return d * 86400 + h * 3600 + mi * 60 + s


def _langs_of(v):
    """'eng/jpn', 'English/Japanese', [{'name': 'Japanese'}] -> ['en', 'ja']."""
    if isinstance(v, list):
        items = [x.get("name") if isinstance(x, dict) else x for x in v]
    else:
        items = re.split(r"[/,]\s*", str(v or ""))
    return [c for c in dict.fromkeys(lang_code(x) for x in items) if c and c not in ("any", "original")]


def gather_downloads(lab):
    """What the download clients say, by download id (a torrent's hash, SABnzbd's nzo_id)."""
    from .adapters.labrequests import download_of_slot, download_of_torrent
    out = {}
    q = lab.src("qbittorrent")
    if q:
        try:
            for t in q.torrents():
                out[(t.get("hash") or "").lower()] = download_of_torrent(t, q.name)
        except Exception as e:                              # noqa: BLE001
            out["_errors"] = out.get("_errors", []) + [f"{q.name}: {str(e)[:120]}"]
    s = lab.src("sabnzbd")
    if s:
        try:
            for slot in s.queue().get("slots") or []:
                out[slot.get("nzo_id")] = download_of_slot(slot, s.name)
            for h in s.history(50).get("slots") or []:
                if (h.get("status") or "").lower() == "failed":
                    out[h.get("nzo_id")] = {"name": h.get("name"), "state": "failed", "why": h.get("fail_message"),
                                            "progress": None, "client": s.name}
        except Exception as e:                              # noqa: BLE001
            out["_errors"] = out.get("_errors", []) + [f"{s.name}: {str(e)[:120]}"]
    return out


QUEUE_PARAMS = {"sonarr": {"includeSeries": "true", "includeEpisode": "true"}, "radarr": {"includeMovie": "true"},
                "lidarr": {"includeArtist": "true", "includeAlbum": "true"}}


def queue_rows(lab, dl):
    rows = []
    for app in ("sonarr", "radarr", "lidarr"):
        if not lab.app(app):
            continue
        try:
            recs = (lab.arr_get(app, "/queue", pageSize=500, **QUEUE_PARAMS[app]) or {}).get("records") or []
        except MediaError as e:
            rows.append({"app": app, "error": str(e)})
            continue
        for r in recs:
            d = dl.get((r.get("downloadId") or "").lower()) or dl.get(r.get("downloadId") or "") or {}
            size, left = r.get("size") or 0, r.get("sizeleft") or 0
            if app == "sonarr":
                ep = r.get("episode") or {}
                title = (r.get("series") or {}).get("title")
                what = f"S{r.get('seasonNumber', ep.get('seasonNumber', 0)):02d}E{ep.get('episodeNumber', 0):02d}" \
                    if ep else r.get("title")
                arr_id = r.get("seriesId")
            elif app == "radarr":
                m = r.get("movie") or {}
                title, what, arr_id = m.get("title") or r.get("title"), m.get("year"), r.get("movieId")
            else:
                title = (r.get("artist") or {}).get("artistName")
                what, arr_id = (r.get("album") or {}).get("title"), r.get("artistId")
            msgs = list(dict.fromkeys(m for sm in r.get("statusMessages") or [] for m in sm.get("messages") or []))
            state = r.get("trackedDownloadState") or r.get("status") or "?"
            if (r.get("trackedDownloadStatus") or "") in ("warning", "error") and state == "downloading":
                state = "stuck"
            rows.append({"app": app, "arr_id": arr_id, "title": title, "what": what, "release": r.get("title"),
                         "state": state, "status": r.get("trackedDownloadStatus"),
                         "progress": d.get("progress") if d.get("progress") is not None else
                         (round(100 * (1 - left / size), 1) if size else None),
                         "speed": d.get("speed"), "eta_s": d.get("eta_s") if d.get("eta_s") is not None
                         else _secs(r.get("timeleft")), "size": size, "left": left,
                         "client": r.get("downloadClient"), "protocol": r.get("protocol"),
                         "quality": ((r.get("quality") or {}).get("quality") or {}).get("name"),
                         "audio": _langs_of(r.get("languages")), "formats": [c.get("name") for c in
                                                                              r.get("customFormats") or []],
                         "score": r.get("customFormatScore"),
                         "why": "; ".join(msgs)[:300] or d.get("why"), "indexer": r.get("indexer")})
    return rows


def group_rows(rows):
    """One line per title: how many items, overall progress, what's left, the longest wait."""
    out = {}
    for r in rows:
        if r.get("error"):
            continue
        g = out.setdefault((r["app"], r["arr_id"]), {"app": r["app"], "arr_id": r["arr_id"], "title": r["title"],
                                                      "items": 0, "size": 0, "left": 0, "eta_s": None, "speed": 0,
                                                      "states": {}, "why": [], "audio": set(), "what": []})
        g["items"] += 1
        g["size"] += r["size"] or 0
        g["left"] += r["left"] or 0
        if r["eta_s"] is not None:
            g["eta_s"] = max(g["eta_s"] or 0, r["eta_s"])
        g["speed"] += r["speed"] or 0
        g["states"][r["state"]] = g["states"].get(r["state"], 0) + 1
        g["audio"].update(r["audio"])
        g["what"].append(r["what"])
        if r["why"] and r["why"] not in g["why"]:
            g["why"].append(r["why"])
    for g in out.values():
        g["progress"] = round(100 * (1 - g["left"] / g["size"]), 1) if g["size"] else None
        g["audio"] = sorted(g["audio"])
        g["speed"] = g["speed"] or None
    return list(out.values())


def find_titles(lab, query):
    """Titles in Sonarr, Radarr and Lidarr whose name contains the query."""
    q = _norm_title(query)
    out = []
    for app, path, key in (("sonarr", "/series", "title"), ("radarr", "/movie", "title"), ("lidarr", "/artist", "artistName")):
        if not lab.app(app):
            continue
        try:
            for x in lab.arr_get(app, path) or []:
                if q and q in _norm_title(x.get(key)):
                    out.append((app, x))
        except MediaError:
            continue
    return out


def _profile_name(lab, app, pid):
    try:
        return next((p["name"] for p in lab.profiles(app) if p["id"] == pid), str(pid))
    except MediaError:
        return str(pid)


def indexer_report(lab, query, kind):
    """Why nothing was found: what Prowlarr's indexers answer for the title now."""
    a = lab.app("prowlarr")
    if not a:
        return None
    idx = {i["id"]: i["name"] for i in lab.arr_get("prowlarr", "/indexer") or [] if i.get("enable")}
    now = dt.datetime.now(dt.timezone.utc).isoformat()
    failing = {s["indexerId"]: s.get("disabledTill") for s in lab.arr_get("prowlarr", "/indexerstatus") or []
               if (s.get("disabledTill") or "") > now}
    cats = {"movie": [2000], "tv": [5000], "anime": [5070, 2000], "music": [3000]}.get(kind, [])
    try:
        res = lab.call(a, "/api/v1/search?" + urllib.parse.urlencode(
            {"query": query, "type": "search", "limit": 100, "categories": cats}, doseq=True), timeout=90) or []
    except MediaError as e:
        return {"error": str(e)}
    counts = {}
    for r in res:
        counts[r.get("indexer")] = counts.get(r.get("indexer"), 0) + 1
    asked = [n for i, n in idx.items() if i not in failing]
    return {"results": len(res), "with_results": counts, "nothing": [n for n in asked if n not in counts],
            "failing": {idx.get(i, str(i)): until for i, until in failing.items()}}


def describe_indexers(rep):
    if not rep:
        return None
    if rep.get("error"):
        return f"Prowlarr didn't answer: {rep['error']}"
    bits = []
    if rep["with_results"]:
        bits.append("results from " + ", ".join(f"{k} ({v})" for k, v in rep["with_results"].items()))
    if rep["nothing"]:
        bits.append("nothing from " + ", ".join(rep["nothing"]))
    if rep["failing"]:
        bits.append("not asked (failing, paused by Prowlarr): " + ", ".join(rep["failing"]))
    return "Prowlarr now: " + "; ".join(bits) if bits else "Prowlarr has no indexers turned on"


def title_status(lab, app, x, queue, why=False):
    langs = languages(lab.settings)
    if app == "sonarr":
        sid = x["id"]
        s = lab.arr_get("sonarr", f"/series/{sid}")
        st = s.get("statistics") or {}
        seasons = [{"season": z["seasonNumber"], "monitored": z.get("monitored"),
                    "files": (z.get("statistics") or {}).get("episodeFileCount", 0),
                    "aired": (z.get("statistics") or {}).get("episodeCount", 0),
                    "episodes": (z.get("statistics") or {}).get("totalEpisodeCount", 0)} for z in s.get("seasons") or []]
        files = lab.arr_get("sonarr", "/episodefile", seriesId=sid) or []
        audio, subs_in, below = {}, set(), 0
        for f in files:
            key = "+".join(lang_name(c) for c in _langs_of((f.get("mediaInfo") or {}).get("audioLanguages"))) or "unknown"
            audio[key] = audio.get(key, 0) + 1
            subs_in.update(_langs_of((f.get("mediaInfo") or {}).get("subtitles")))
            below += 1 if f.get("qualityCutoffNotMet") else 0
        q = [g for g in queue if g["app"] == "sonarr" and g["arr_id"] == sid]
        missing = sum(z["aired"] - z["files"] for z in seasons if z["monitored"])
        out = {"kind": "tv", "app": "sonarr", "id": sid, "title": s.get("title"), "year": s.get("year"),
               "profile": _profile_name(lab, "sonarr", s.get("qualityProfileId")), "series_type": s.get("seriesType"),
               "monitoring": describe_monitoring(s), "new_items": s.get("monitorNewItems"), "seasons": seasons,
               "files": st.get("episodeFileCount"), "episodes": st.get("totalEpisodeCount"),
               "size_on_disk": st.get("sizeOnDisk"), "audio": audio, "embedded_subs": sorted(subs_in),
               "below_target": below, "downloading": q[0] if q else None, "missing": missing}
        hist = (lab.arr_get("sonarr", "/history/series", seriesId=sid, eventType="downloadFailed") or [])[:5]
    elif app == "radarr":
        mid = x["id"]
        m = lab.arr_get("radarr", f"/movie/{mid}")
        mf = (lab.arr_get("radarr", "/moviefile", movieId=mid) or [None])
        mf = mf[0] if mf else None
        q = [g for g in queue if g["app"] == "radarr" and g["arr_id"] == mid]
        out = {"kind": "movie", "app": "radarr", "id": mid, "title": m.get("title"), "year": m.get("year"),
               "profile": _profile_name(lab, "radarr", m.get("qualityProfileId")), "monitored": m.get("monitored"),
               "has_file": m.get("hasFile"), "available": m.get("isAvailable"),
               "waits_for": m.get("minimumAvailability"), "dates": movie_dates(m),
               "audio": {"+".join(lang_name(c) for c in _langs_of(((mf or {}).get("mediaInfo") or {})
                                                                  .get("audioLanguages"))) or "unknown": 1} if mf else {},
               "embedded_subs": _langs_of(((mf or {}).get("mediaInfo") or {}).get("subtitles")) if mf else [],
               "below_target": 1 if mf and mf.get("qualityCutoffNotMet") else 0,
               "downloading": q[0] if q else None, "missing": 0 if m.get("hasFile") else 1}
        hist = (lab.arr_get("radarr", "/history/movie", movieId=mid, eventType="downloadFailed") or [])[:5]
    else:
        aid = x["id"]
        st = x.get("statistics") or {}
        q = [g for g in queue if g["app"] == "lidarr" and g["arr_id"] == aid]
        out = {"kind": "artist", "app": "lidarr", "id": aid, "title": x.get("artistName"),
               "profile": _profile_name(lab, "lidarr", x.get("qualityProfileId")),
               "albums": st.get("albumCount"), "tracks": st.get("trackFileCount"), "of": st.get("totalTrackCount"),
               "downloading": q[0] if q else None, "missing": (st.get("totalTrackCount") or 0) - (st.get("trackFileCount") or 0)}
        hist = []
    out["failed"] = [{"at": h.get("date"), "release": h.get("sourceTitle"),
                      "why": (h.get("data") or {}).get("message")} for h in hist]
    if app in ("sonarr", "radarr"):
        try:
            out["subtitles"] = subtitle_state(lab, app, out["id"], langs["subtitles"])
        except MediaError as e:
            out["subtitles"] = {"error": str(e)}
    if out["missing"] and not out["downloading"] and (why or app != "lidarr"):
        if out.get("kind") == "movie" and not out.get("available"):
            out["searching"] = f"waiting for its release ({out['waits_for']})"
        else:
            out["searching"] = "monitored and missing; Sonarr/Radarr look again every 15 minutes (RSS)" \
                if app != "lidarr" else "monitored and missing"
            if why or out["missing"]:
                out["indexers"] = indexer_report(lab, out["title"], "anime" if out.get("series_type") == "anime"
                                                 else out["kind"] if out["kind"] != "artist" else "music")
    return out


def seerr_pending(lab, queue):
    """Seerr's requests that are approved but not on disk yet, with their titles."""
    if not lab.seerr:
        return []
    try:
        reqs = lab.seerr.requests()
    except Exception:                                    # noqa: BLE001
        return []
    out = [r for r in reqs if r["state"] in ("pending approval", "approved") and r["media"] in ("pending", "processing")]

    def title(r):
        try:
            d = lab.call(lab.seerr, f"/api/v1/{r['kind']}/{r['tmdb']}") or {}
            r["name"] = d.get("title") or d.get("name") or r["name"]
            r["year"] = _year(d.get("releaseDate") or d.get("firstAirDate"))
        except MediaError:
            pass
        return r
    with cf.ThreadPoolExecutor(6) as ex:
        return list(ex.map(title, out[:20]))


def status(lab, query=None, why=False, finish=True):
    """Everything in flight, and with a query the matching titles in detail."""
    dl = gather_downloads(lab)
    rows = queue_rows(lab, dl)
    groups = group_rows(rows)
    out = {"downloads": groups, "items": [r for r in rows if not r.get("error")],
           "errors": [r["error"] for r in rows if r.get("error")] + dl.get("_errors", []),
           "requests": seerr_pending(lab, groups)}
    if lab.src("slskd"):
        try:
            from .adapters.labrequests import folders_of_transfers
            pend = {(p["user"], p["directory"]) for p in _state().get("soulseek") or []}
            out["soulseek"] = [f for f in folders_of_transfers(lab.call(lab.src("slskd"), "/api/v0/transfers/downloads"))
                               if (f["user"], f["directory"]) in pend]
        except MediaError as e:
            out["errors"].append(str(e))
        if finish:
            try:
                out["imported"] = finish_soulseek(lab)
            except MediaError as e:
                out["errors"].append(str(e))
    if query:
        found = find_titles(lab, query)
        out["titles"] = [title_status(lab, app, x, groups, why) for app, x in found]
        keys = {(app, x["id"]) for app, x in found}
        q = _norm_title(query)
        out["downloads"] = [g for g in groups if (g["app"], g["arr_id"]) in keys]
        out["items"] = [r for r in out["items"] if (r["app"], r["arr_id"]) in keys]
        out["requests"] = [r for r in out["requests"] if q in _norm_title(r.get("name"))]
    if lab.app("bazarr"):
        try:
            gen = (lab.call(lab.app("bazarr"), "/api/system/settings") or {}).get("general") or {}
            if not gen.get("enabled_providers"):
                out["subtitle_warning"] = ("Bazarr has no subtitle providers turned on, so it finds no subtitles: "
                                           "turn some on in Bazarr's Settings › Providers")
        except MediaError:
            pass
    return out


# ------------------------------------------------------------------ upcoming, calendars, recent imports
def _local(iso):
    if not iso:
        return None
    try:
        t = dt.datetime.fromisoformat(str(iso).replace("Z", "+00:00"))
    except ValueError:
        return str(iso)[:16]
    if t.tzinfo:
        t = t.astimezone()
    return t.strftime("%Y-%m-%d %H:%M") if (t.hour, t.minute) != (0, 0) or "T" in str(iso) and t.tzinfo else \
        t.strftime("%Y-%m-%d")


def upcoming(lab, days=90):
    start = dt.date.today()
    end = start + dt.timedelta(days=days)
    rows = []
    if lab.app("sonarr"):
        for e in lab.arr_get("sonarr", "/calendar", start=start.isoformat(), end=end.isoformat(),
                             includeSeries="true", unmonitored="false") or []:
            rows.append({"date": _local(e.get("airDateUtc")) or e.get("airDate"), "kind": "tv",
                         "title": (e.get("series") or {}).get("title"),
                         "what": f"S{e.get('seasonNumber', 0):02d}E{e.get('episodeNumber', 0):02d}",
                         "name": e.get("title"), "has_file": e.get("hasFile")})
    if lab.app("radarr"):
        for m in lab.arr_get("radarr", "/calendar", start=start.isoformat(), end=end.isoformat(),
                             unmonitored="false") or []:
            for k, label in (("inCinemas", "in cinemas"), ("digitalRelease", "digital"), ("physicalRelease", "disc")):
                day = _day(m.get(k))
                if day and start.isoformat() <= day <= end.isoformat():
                    rows.append({"date": day, "kind": "movie", "title": m.get("title"), "what": label,
                                 "name": str(m.get("year") or ""), "has_file": m.get("hasFile"),
                                 "dates": movie_dates(m)})
    rows.sort(key=lambda r: (r["date"] or "", r["title"] or ""))
    return rows


def calendar_sources(lab=None):
    """The iCal feeds of the lab's Sonarr ("TV") and Radarr ("Movies"), for the Calendar
    widget: [{source: "lab:tv", name, app}]. The key never leaves the adapter: the widget
    reads each feed through calendar_ics()."""
    lab = lab or Lab()
    return [{"source": f"lab:{k}", "name": n, "app": app} for k, n, app in (("tv", "TV", "sonarr"),
                                                                            ("movies", "Movies", "radarr"))
            if lab.app(app)]


def calendar_ics(which, past=7, future=90, lab=None):
    """The feed's ICS bytes (Sonarr's or Radarr's /feed/v3/calendar, monitored titles only)."""
    lab = lab or Lab()
    app = {"tv": "sonarr", "movies": "radarr", "sonarr": "sonarr", "radarr": "radarr"}.get(which)
    a = lab.app(app) if app else None
    if not a:
        raise MediaError(f"no {app or which} source in homelab.toml")
    from . import config
    key = config.resolve(a.opts.get("auth_ref") or "")
    q = urllib.parse.urlencode({"apikey": key, "pastDays": past, "futureDays": future, "unmonitored": "false"})
    try:
        ics = a.request(f"/feed/v3/calendar/{app.title()}.ics?{q}", raw=True, timeout=20)
    except urllib.error.HTTPError as e:
        raise MediaError(f"{a.name}: its calendar feed answered HTTP {e.code}") from None
    if app == "radarr":
        # Radarr's feed says CONFIRMED for any film past "announced"; the panel's ✓ means
        # "on disk", so each event's STATUS comes from the film's hasFile instead
        try:
            have = {m["id"] for m in lab.arr_get("radarr", "/movie") or [] if m.get("hasFile")}
        except MediaError:
            have = None
        if have is not None:
            ics = movie_status(ics, have)
    return ics


def movie_status(ics, have):
    """Radarr's ICS with STATUS:CONFIRMED on the films in `have` (ids) and TENTATIVE on the rest."""
    out, uid_movie, buf = [], None, []
    for line in ics.decode("utf-8", "replace").splitlines():
        if line == "BEGIN:VEVENT":
            buf, uid_movie = [line], None
            continue
        if buf:
            buf.append(line)
            m = re.match(r"UID:Radarr_movie_(\d+)_", line)
            if m:
                uid_movie = int(m.group(1))
            if line == "END:VEVENT":
                st = "STATUS:CONFIRMED" if uid_movie in have else "STATUS:TENTATIVE"
                buf = [x for x in buf if not x.startswith("STATUS:")]
                buf.insert(-1, st)
                out += buf
                buf = []
            continue
        out.append(line)
    return ("\r\n".join(out) + "\r\n").encode()


def recent(lab, since):
    """What was imported since `since` (seconds since the epoch), newest first."""
    iso = dt.datetime.fromtimestamp(since, dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    rows = []
    for app, ev, inc in (("sonarr", "downloadFolderImported", {"includeSeries": "true", "includeEpisode": "true"}),
                         ("radarr", "downloadFolderImported", {"includeMovie": "true"}),
                         ("lidarr", "trackFileImported", {"includeArtist": "true", "includeAlbum": "true"})):
        if not lab.app(app):
            continue
        try:
            hist = lab.arr_get(app, "/history/since", date=iso, eventType=ev, **inc) or []
        except MediaError:
            continue
        for h in hist:
            if app == "sonarr":
                ep = h.get("episode") or {}
                title, what = (h.get("series") or {}).get("title"), \
                    f"S{ep.get('seasonNumber', 0):02d}E{ep.get('episodeNumber', 0):02d}"
            elif app == "radarr":
                title, what = (h.get("movie") or {}).get("title"), str((h.get("movie") or {}).get("year") or "")
            else:
                title, what = (h.get("artist") or {}).get("artistName"), (h.get("album") or {}).get("title")
            rows.append({"at": h.get("date"), "app": app, "title": title, "what": what,
                         "quality": ((h.get("quality") or {}).get("quality") or {}).get("name"),
                         "audio": _langs_of(h.get("languages"))})
    rows.sort(key=lambda r: r["at"] or "", reverse=True)
    groups = {}
    for r in rows:
        g = groups.setdefault((r["app"], r["title"]), dict(r, items=[]))
        g["items"].append(r["what"])
    return list(groups.values())


# ------------------------------------------------------------------ words
def summary(it):
    """One line: 'The Office (US), 2005, TV, 9 seasons, Sonarr profile WEB-2160p, about 180 GB'."""
    if it["kind"] == "youtube":
        return f"a YouTube {it.get('youtube')}: Pinchflat downloads it"
    bits = [it.get("title") or "?"]
    if it.get("year"):
        bits.append(str(it["year"]))
    if it["kind"] == "album":
        bits = [f"{it.get('artist')}: {it.get('title')}"] + ([str(it["year"])] if it.get("year") else []) + \
            [it.get("album_type") or "album"] + ([f"{it['tracks']} tracks"] if it.get("tracks") else [])
    elif it["kind"] == "artist":
        bits += [b for b in ("artist", it.get("disambiguation")) if b]
    else:
        bits.append(("anime " if it.get("anime") else "") + ("film" if it["kind"] == "movie" else "TV"))
        real = [s for s in it.get("seasons") or [] if s.get("number")]
        if real:
            bits.append(f"{len(real)} season{'s' if len(real) != 1 else ''}")
        rel = it.get("release")
        if rel and rel not in ("released",):
            bits.append(rel)
    if it.get("profile"):
        app = {"movie": "Radarr", "tv": "Sonarr"}.get(it["kind"], "Lidarr")
        bits.append(f"{app} profile {it['profile']['name']}")
    if it.get("size"):
        bits.append(f"about {human(it['size'])}")
    if it.get("arr"):
        bits.append("already in " + {"sonarr": "Sonarr", "radarr": "Radarr", "lidarr": "Lidarr"}[it["arr"]["app"]])
    for line in describe_library(it.get("library") or {}):
        bits.append(line[0].lower() + line[1:])
    return ", ".join(bits)


def plan_lines(p):
    it = p["item"]
    L = [summary(it)]
    if it["kind"] == "youtube":
        return L + ["  Goes to Pinchflat (bromigos lab youtube add)" + (f", at {p['quality']}" if p.get("quality") else "")]
    app = {"sonarr": "Sonarr", "radarr": "Radarr", "lidarr": "Lidarr"}[p["app"]]
    L.append(f"  {app} profile {p['profile']['why']}")
    for w in p["profile"].get("warnings") or []:
        L.append(f"  Note: {w}")
    if p.get("audio"):
        L.append(f"  Audio: you want {p['audio']['text']}. The profile: {p['audio']['profile']}")
    if it.get("anime"):
        L.append(f"  Anime ({it.get('anime_why')}): Sonarr's anime series type and absolute numbering"
                 if it["kind"] == "tv" else f"  Anime ({it.get('anime_why')})")
    if it["kind"] == "tv":
        spec = p["seasons"]
        if p["episodes"]:
            what = "episodes " + ", ".join(f"S{a:02d}E{b:02d}" for a, b in p["episodes"])
        elif spec == "future":
            what = "nothing now; new episodes from here on"
        elif spec == "none":
            what = "nothing (monitoring only what's set)"
        else:
            real = [n for n in p["now"] if n]
            what = (("the one season" if len(real) == 1 else f"all {len(real)} seasons") if spec == "all" else f"season {real[0]}" if len(real) == 1
                    else "seasons " + _span_text(real)) + (" and specials" if p["specials"] else "")
            if p.get("episode_count"):
                what += f" ({p['episode_count']} episodes)"
        L.append(f"  Gets: {what}; new episodes and seasons: {'picked up automatically' if p['new'] else 'no'}")
    if it["kind"] == "movie":
        when = {"announced": "as soon as it's announced (anything)", "inCinemas": "from its cinema release",
                "released": "when it's out at home (digital or disc), the best copy, never a cam"}[p["when"]]
        L.append(f"  Fetches it {when}" + ("" if it.get("release") == "released" else f"; {it.get('release')}"))
    size, free = p.get("size"), p.get("free")
    L.append(f"  About {human(size)} on disk" + (f"; the library has {human(free)} free" if free else "")
             if size else "  Size: unknown" + (f"; the library has {human(free)} free" if free else ""))
    if size and free and size > free * 0.9:
        L.append("  WARNING: that's more than the free space")
    for line in describe_library(p.get("library") or {}):
        L.append("  " + line)
    if p.get("existing"):
        L.append(f"  Already in {app}: this changes its monitoring" + (" and profile" if p["change_profile"] else "")
                 + ", it doesn't add it again")
    elif p["route"] == "seerr":
        L.append("  Through Seerr, so it shows in its Requests")
    if p["app"] == "lidarr" and p.get("slskd"):
        L.append("  If Lidarr's indexers find nothing for an album, Soulseek (slskd) is tried next")
    return L


def result_lines(r):
    L = []
    route = {"seerr": "Requested through Seerr", "sonarr": "Set in Sonarr", "radarr": "Added to Radarr",
             "lidarr": "Asked Lidarr", "soulseek": "Fetching from Soulseek", "pinchflat": "Added to Pinchflat"}
    L.append(route.get(r.get("route"), "Done") + (f" (request {r['seerr_request']})" if r.get("seerr_request") else "") + ".")
    if r.get("monitoring"):
        L.append("  " + r["monitoring"] + ".")
    if r.get("profile"):
        L.append(f"  Profile: {r['profile']}" + (f", series type {r['series_type']}" if r.get("series_type") else ""))
    if r.get("searches"):
        L.append("  Searching now: " + ", ".join(r["searches"]))
    if r.get("availability"):
        L.append(f"  Waits for: {r['availability']}")
    if r.get("subtitles"):
        L.append("  " + r["subtitles"])
    if r.get("say"):
        L.append("  " + r["say"])
    return L


def _pct(v):
    return "?" if v is None else f"{v:.0f}%"


def status_lines(d):
    L = []
    if d.get("downloads"):
        L.append("Downloading:")
        for g in sorted(d["downloads"], key=lambda g: g["title"] or ""):
            states = ", ".join(f"{n} {s}" for s, n in g["states"].items())
            line = f"  {g['title']}: {g['items']} item{'s' if g['items'] != 1 else ''} ({states}), {_pct(g['progress'])}"
            if g["size"]:
                line += f" of {human(g['size'])}"
            if g.get("speed"):
                line += f" at {human(g['speed'])}/s"
            if g.get("eta_s"):
                line += f", about {hm(g['eta_s'])} left"
            if g["audio"]:
                line += f"; audio {'+'.join(lang_name(a) for a in g['audio'])} (from the release names)"
            L.append(line)
            for w in g["why"][:3]:
                L.append(f"    why: {w}")
    else:
        L.append("Nothing downloading.")
    for r in d.get("requests") or []:
        L.append(f"  Requested in Seerr: {r['name']}" + (f" ({r['year']})" if r.get("year") else "") +
                 f", {'film' if r['kind'] == 'movie' else 'TV'}: {r['media']}")
    if d.get("subtitle_warning"):
        L.append("  Note: " + d["subtitle_warning"])
    for f in d.get("soulseek") or []:
        L.append(f"  Soulseek: {f['name']} from {f['user']}: {_pct(f['progress'])} ({f['state']})")
    for x in d.get("imported") or []:
        L.append(f"  Soulseek download handed to Lidarr to import: {x['title']}" + (" (failed)" if x.get("failed") else ""))
    for t in d.get("titles") or []:
        L.append("")
        L += title_lines(t)
    for e in d.get("errors") or []:
        L.append(f"  (couldn't read: {e})")
    return L


def title_lines(t):
    L = [f"{t['title']}" + (f" ({t['year']})" if t.get("year") else "") +
         f" · {({'sonarr': 'Sonarr', 'radarr': 'Radarr', 'lidarr': 'Lidarr'})[t['app']]} profile {t['profile']}"
         + (f" · series type {t['series_type']}" if t.get("series_type") else "")]
    if t["kind"] == "tv":
        L.append("  " + t["monitoring"] + ".")
        for z in t["seasons"]:
            name = "Specials" if z["season"] == 0 else f"Season {z['season']}"
            L.append(f"  {name}: {'monitored' if z['monitored'] else 'not monitored'}, "
                     f"{z['files']} of {z['aired']} aired on disk" + (f" ({z['episodes']} in all)"
                                                                      if z["episodes"] != z["aired"] else ""))
    elif t["kind"] == "movie":
        d = t.get("dates") or {}
        L.append(f"  {'On disk' if t['has_file'] else 'Not on disk yet'}; "
                 f"{'monitored' if t['monitored'] else 'not monitored'}; waits for {t['waits_for']}"
                 + "".join(f"; {k} {v}" for k, v in d.items() if v))
    else:
        L.append(f"  {t.get('albums') or 0} albums, {t.get('tracks') or 0} of {t.get('of') or 0} tracks on disk")
    if t.get("audio"):
        L.append("  Audio on disk: " + ", ".join(f"{k} ({v} file{'s' if v != 1 else ''})" for k, v in t["audio"].items()))
    if t.get("below_target"):
        L.append(f"  {t['below_target']} file{'s are' if t['below_target'] != 1 else ' is'} below the profile's target "
                 f"(an audio language or quality it ranks higher): replaced when a better release turns up")
    if t.get("subtitles") is not None:
        s = describe_subs(t["subtitles"]) if not t["subtitles"].get("error") else t["subtitles"]["error"]
        L.append(f"  Subtitles: {s}" + (f" (in the files: {', '.join(lang_name(x) for x in t['embedded_subs'])})"
                                       if t.get("embedded_subs") else ""))
    g = t.get("downloading")
    if g:
        L.append(f"  Downloading: {g['items']} item(s), {_pct(g['progress'])}"
                 + (f", about {hm(g['eta_s'])} left" if g.get("eta_s") else ""))
    if t.get("searching"):
        L.append(f"  Searching: {t['searching']}")
    if t.get("indexers"):
        L.append("  " + describe_indexers(t["indexers"]))
    for f in t.get("failed") or []:
        L.append(f"  Failed {str(f['at'])[:10]}: {f['release']}: {f['why']}")
    return L


def upcoming_lines(rows, days):
    if not rows:
        return [f"Nothing tracked comes out in the next {days} days."]
    L = []
    for r in rows:
        mark = " (on disk)" if r.get("has_file") else ""
        if r["kind"] == "tv":
            L.append(f"  {r['date']}  {r['title']} {r['what']} · {r['name']}{mark}")
        else:
            L.append(f"  {r['date']}  {r['title']} ({r['name']}): {r['what']}{mark}")
    return [f"Coming up in the next {days} days:"] + L


def language_lines(d):
    L = [f"Audio: {describe_audio(d['audio'], d['required'])}"]
    if d["anime_audio"] != d["audio"]:
        L.append(f"Anime: {describe_audio(d['anime_audio'], d['required'])}")
    else:
        L.append("Anime: the same")
    L.append("Subtitles (Bazarr): " + ", ".join(lang_name(x) for x in d["subtitles"]))
    if d["from"] != "settings":
        L.append(f"(from {d['from']}: set your own with bromigos lab media language set …)")
    return L


# ------------------------------------------------------------------ the command line
def _clean(o):
    """JSON-safe, without the raw API objects."""
    if isinstance(o, dict):
        return {k: _clean(v) for k, v in o.items() if k not in ("raw",)}
    if isinstance(o, (list, tuple)):
        return [_clean(x) for x in o]
    if isinstance(o, set):
        return sorted(o)
    return o


def confirm(q):
    if not sys.stdin.isatty():
        return None
    try:
        return input(q + " [y/N] ").strip().lower() in ("y", "yes")
    except EOFError:
        return False


def parser():
    p = argparse.ArgumentParser(prog="bromigos lab media", description="Ask your lab's *arr stack for films, shows, "
                                "anime and music, at the best quality its profiles allow (docs/lab.md).")
    sub = p.add_subparsers(dest="cmd")

    def cmd(name, help):
        c = sub.add_parser(name, help=help, description=help)
        c.add_argument("--json", action="store_true", help="print JSON")
        return c

    def kinds(c):
        k = c.add_mutually_exclusive_group()
        for f in ("movie", "tv", "anime", "music"):
            k.add_argument("--" + f, dest="kind", action="store_const", const=f)
    c = cmd("search", "find a title: year, kind, release dates, in your library or requested, size")
    c.add_argument("query", nargs="+")
    kinds(c)
    c.add_argument("--limit", type=int, default=8)
    c = cmd("get", "request a title (asks first unless --yes)")
    c.add_argument("what", nargs="+", metavar="ID|NAME|URL")
    kinds(c)
    c.add_argument("--quality", choices=QUALITIES, help="best (default), or a ceiling")
    c.add_argument("--audio", help="this request's audio: en, ja, … or any (default: your [media] setting)")
    c.add_argument("--seasons", default="all", help="all (default), latest, future (new episodes only), 1,3 or 2-4")
    c.add_argument("--episodes", help="just these: S02E05,S03E01")
    c.add_argument("--specials", action="store_true", help="the specials (season 0) too")
    c.add_argument("--new", choices=("yes", "no"), help="pick up new episodes and seasons (default yes)")
    c.add_argument("--when", choices=("announced", "cinemas", "released"),
                   help="films: fetch from this point (default released: the home release, never a cam)")
    c.add_argument("--yes", "-y", action="store_true", help="don't ask")
    c = cmd("status", "what's requested, downloading (progress, ETA), imported or failed, and why")
    c.add_argument("query", nargs="*")
    c.add_argument("--why", action="store_true", help="ask Prowlarr's indexers now for anything missing")
    c = cmd("upcoming", "what you track and when it comes out")
    c.add_argument("--days", type=int, default=90)
    c = cmd("recent", "what was imported lately")
    c.add_argument("--hours", type=float, default=24)
    c = cmd("language", "your audio and subtitle languages (anime same: anime follows your audio again)")
    c.add_argument("verb", nargs="?", default="show", choices=("show", "set", "anime", "subtitles", "required"))
    c.add_argument("values", nargs="*", metavar="LANG")
    c = cmd("calendar", "the TV or Movies iCal feed (for the Calendar widget)")
    c.add_argument("which", choices=("tv", "movies"))
    c.add_argument("--past", type=int, default=7)
    c.add_argument("--future", type=int, default=90)
    return p


def main(argv=None):
    p = parser()
    a = p.parse_args(argv)
    if not a.cmd:
        p.print_help(sys.stderr)
        return 2
    js = getattr(a, "json", False)
    try:
        return _main(a, js)
    except Ambiguous as e:
        if js:
            print(json.dumps({"ambiguous": True, "error": str(e),
                              "matches": [dict(id=m["id"], summary=summary(m)) for m in e.matches]}, indent=1))
        else:
            print(f"media {a.cmd}: {e}", file=sys.stderr)
            for m in e.matches:
                print(f"  {m['id']:<24} {summary(m)}", file=sys.stderr)
        return 3
    except MediaError as e:
        if js:
            print(json.dumps({"error": str(e)}))
        print(f"media {a.cmd}: {e}", file=sys.stderr)
        return 4 if str(e).startswith("nothing found") else 1


def _main(a, js):
    out = (lambda *x: None) if js else print
    if a.cmd == "language":
        return cmd_language(a, js)
    if a.cmd == "calendar":
        sys.stdout.buffer.write(calendar_ics(a.which, a.past, a.future))
        return 0
    lab = Lab()
    if not lab.configured():
        raise MediaError("no Seerr or *arr sources in homelab.toml (docs/lab.md, \"Media requests\")")
    if a.cmd == "search":
        hits = search(lab, " ".join(a.query), a.kind, a.limit)
        if js:
            print(json.dumps(_clean([dict(h, summary=summary(h)) for h in hits]), indent=1, default=str))
            return 0 if hits else 4
        if not hits:
            print("Nothing found.")
            return 4
        for h in hits:
            print(f"{h['id']:<24} {summary(h)}")
        return 0
    if a.cmd == "get":
        it = resolve(lab, " ".join(a.what), a.kind)
        pl = plan(lab, it, a.seasons, a.episodes, None if a.new is None else a.new == "yes", a.specials, a.quality,
                  a.audio, a.when)
        for line in plan_lines(pl):
            out(line)
        if not a.yes:
            ok = confirm("Request it?")
            if ok is None:
                if js:
                    print(json.dumps(_clean({"plan": dict(pl, lines=plan_lines(pl)), "asked": True}), indent=1, default=str))
                else:
                    print("(nothing requested: add --yes to request it without a terminal)", file=sys.stderr)
                return 2
            if not ok:
                out("Nothing requested.")
                return 1
        res = run(lab, pl)
        if it["kind"] in ("movie", "tv") and res.get("id") and lab.app("bazarr"):
            try:
                res["subtitles"] = bazarr_assign(lab, pl["app"], res["id"], languages(lab.settings)["subtitles"])
            except MediaError as e:
                res["subtitles"] = f"subtitles: Bazarr didn't take the profile ({e}); it applies its default"
        for line in result_lines(res):
            out(line)
        if js:
            print(json.dumps(_clean({"plan": dict(pl, lines=plan_lines(pl)), "result": dict(res, lines=result_lines(res))}),
                             indent=1, default=str))
        return 0
    if a.cmd == "status":
        d = status(lab, " ".join(a.query) or None, a.why)
        if js:
            print(json.dumps(_clean(dict(d, lines=status_lines(d))), indent=1, default=str))
        else:
            print("\n".join(status_lines(d)))
        return 0
    if a.cmd == "upcoming":
        rows = upcoming(lab, a.days)
        if js:
            print(json.dumps(rows, indent=1, default=str))
        else:
            print("\n".join(upcoming_lines(rows, a.days)))
        return 0
    if a.cmd == "recent":
        rows = recent(lab, time.time() - a.hours * 3600)
        if js:
            print(json.dumps(rows, indent=1, default=str))
        else:
            for r in rows:
                print(f"  {str(r['at'])[:16].replace('T', ' ')}  {r['title']}: {', '.join(str(x) for x in r['items'][:6])}"
                      + (f" (+{len(r['items']) - 6})" if len(r["items"]) > 6 else ""))
            if not rows:
                print(f"Nothing imported in the last {a.hours:g} hours.")
        return 0
    return 2


def cmd_language(a, js):
    from . import config
    vals = _codes(a.values)
    if a.verb == "show":
        d = languages()
    else:
        if a.verb == "required":
            if not a.values or a.values[0].lower() not in ("yes", "no", "true", "false"):
                raise MediaError("language required yes|no")
            updates = {"audio_required": a.values[0].lower() in ("yes", "true")}
        elif a.verb == "anime" and [v.lower() for v in a.values] == ["same"]:
            updates = {"anime_audio": None}                   # anime follows `audio` again
        else:
            if not vals:
                raise MediaError(f"language {a.verb} LANG …: ISO 639-1 codes, best first (en ja), or any")
            key = {"set": "audio", "anime": "anime_audio", "subtitles": "subtitles"}[a.verb]
            updates = {key: vals}
        path = write_media_settings(updates)
        config._cache["sig"] = None
        d = dict(languages(), written=path)
        if a.verb == "subtitles":
            try:
                lab = Lab()
                if lab.app("bazarr"):
                    pid, name = bazarr_profile(lab, d["subtitles"])
                    d["bazarr"] = f"Bazarr's default profile is now {name}" if pid else name
            except MediaError as e:
                d["bazarr"] = f"Bazarr: {e}"
    if js:
        print(json.dumps(d, indent=1))
        return 0
    print("\n".join(language_lines(d)))
    if d.get("written"):
        print(f"(saved in {d['written']})")
    if d.get("bazarr"):
        print(d["bazarr"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
