"""Audio tracks and subtitles for what the den TV and the cast targets play: one shape for
mpv's track list and Jellyfin's media streams, the labels the remotes show, the defaults,
and the choice remembered per series.

    from_mpv(track_list)             mpv's `track-list` -> (audio, subs)
    from_jellyfin(media_streams)     Jellyfin's MediaStreams -> (audio, subs)
    choose(audio, subs, memory)      (audio track, subtitle track or None): what to play
    Memory().get(item) / .put(item, audio, sub)   the choice for a series (or a film)
    public(audio, subs, ...)         the JSON the remotes get: ids, languages, labels

A track is a dict:

    {id, type: audio | sub, lang (ISO 639-1 or None), title, codec, channels, default,
     forced, hi (SDH/CC), external, selected, kind, label}

kind: audio `main` or `commentary`; subtitles `full`, `forced` (signs & songs too), `sdh`
or `commentary`. label: "English · 5.1", "Japanese · Stereo", "English · Signs & Songs".

The defaults (docs: live/README.md, "Audio and subtitles"):
  - English audio when there is some (a main track, not commentary);
  - audio that isn't English: English subtitles on, a full track before a forced one;
  - English audio: English forced subtitles (signs and songs) when there are some, else off.
A choice made on a remote is remembered for the series (or the film), by language and kind,
not by track number: the next episode's tracks may be numbered differently.
"""
import json
import os
import re
import time

# ISO 639-2 (and a few names mpv and Jellyfin use) -> ISO 639-1
LANG3 = {"eng": "en", "jpn": "ja", "fre": "fr", "fra": "fr", "ger": "de", "deu": "de", "spa": "es", "ita": "it",
         "por": "pt", "kor": "ko", "chi": "zh", "zho": "zh", "rus": "ru", "dut": "nl", "nld": "nl", "swe": "sv",
         "nor": "no", "nob": "no", "dan": "da", "fin": "fi", "pol": "pl", "hin": "hi", "ara": "ar", "tur": "tr",
         "gre": "el", "ell": "el", "heb": "he", "hun": "hu", "cze": "cs", "ces": "cs", "tha": "th", "vie": "vi",
         "ind": "id", "may": "ms", "msa": "ms", "ukr": "uk", "rum": "ro", "ron": "ro", "fil": "tl", "tgl": "tl",
         "english": "en", "japanese": "ja", "spanish": "es", "french": "fr", "german": "de"}
NAMES = {"en": "English", "ja": "Japanese", "fr": "French", "de": "German", "es": "Spanish", "it": "Italian",
         "pt": "Portuguese", "ko": "Korean", "zh": "Chinese", "ru": "Russian", "nl": "Dutch", "sv": "Swedish",
         "no": "Norwegian", "da": "Danish", "fi": "Finnish", "pl": "Polish", "hi": "Hindi", "ar": "Arabic",
         "tr": "Turkish", "el": "Greek", "he": "Hebrew", "hu": "Hungarian", "cs": "Czech", "th": "Thai",
         "vi": "Vietnamese", "id": "Indonesian", "ms": "Malay", "uk": "Ukrainian", "ro": "Romanian", "tl": "Filipino"}
SUB_KINDS = {"full": "Full", "forced": "Forced", "sdh": "SDH", "commentary": "Commentary"}
ENGLISH = "en"
MEMORY_MAX = 500

_SIGNS = re.compile(r"\bsigns?\b|\bsongs?\b|\bforced\b|\bfor(eign)? parts?\b|\bnon[- ]?english\b", re.I)
_SDH = re.compile(r"\bsdh\b|\bcc\b|closed caption|hearing impaired|\bhoh\b|\bdeaf\b", re.I)
_COMMENTARY = re.compile(r"commentary|director'?s? (notes|track)", re.I)


def lang2(code):
    """ISO 639-1 for a language code or name, else None ("und", "", "mis")."""
    c = str(code or "").strip().lower()
    if not c or c in ("und", "mis", "zxx", "mul", "unknown"):
        return None
    c = c.split("-")[0].split("_")[0]
    if len(c) == 2 and c.isalpha():
        return c
    return LANG3.get(c)


def lang_name(code):
    c = lang2(code)
    return NAMES.get(c, c.upper() if c else "Unknown")


def channels_label(n):
    """"Mono", "Stereo", "5.1", "7.1" from a channel count or mpv's layout name."""
    if n is None:
        return None
    s = str(n).lower()
    if s in ("1", "mono", "1.0"):
        return "Mono"
    if s in ("2", "stereo", "2.0"):
        return "Stereo"
    if s in ("6", "5.1", "5.1(side)"):
        return "5.1"
    if s in ("8", "7.1", "7.1(wide)"):
        return "7.1"
    if s.isdigit():
        return f"{s} ch"
    return s.split("(")[0] or None


def audio_kind(title):
    return "commentary" if _COMMENTARY.search(title or "") else "main"


def sub_kind(title, forced=False, hi=False):
    t = title or ""
    if _COMMENTARY.search(t):
        return "commentary"
    if forced or _SIGNS.search(t):
        return "forced"
    if hi or _SDH.search(t):
        return "sdh"
    return "full"


def _signs(title):
    return bool(re.search(r"\bsigns?\b|\bsongs?\b", title or "", re.I))


def label(t):
    """What a remote shows for a track."""
    name = lang_name(t.get("lang")) if t.get("lang") else (t.get("title") or "Unknown")[:24]
    if t["type"] == "audio":
        bits = [name]
        if t.get("kind") == "commentary":
            bits.append("Commentary")
        else:
            ch = channels_label(t.get("channels"))
            if ch:
                bits.append(ch)
        return " · ".join(bits)
    kind = t.get("kind") or "full"
    word = "Signs & Songs" if kind == "forced" and _signs(t.get("title")) else SUB_KINDS.get(kind, "Full")
    return f"{name} · {word}"


def _finish(t):
    if t["type"] == "audio":
        t["kind"] = audio_kind(t.get("title"))
    else:
        t["kind"] = sub_kind(t.get("title"), t.get("forced"), t.get("hi"))
    t["label"] = label(t)
    return t


def from_mpv(track_list):
    """mpv's `track-list` -> (audio, subs). Ids are "m<mpv id>"; ff-index is kept to match
    Jellyfin's stream index on a direct stream."""
    audio, subs = [], []
    for r in track_list or []:
        typ = r.get("type")
        if typ not in ("audio", "sub"):
            continue
        t = dict(id=f"m{r.get('id')}", mpv=r.get("id"), ff=r.get("ff-index"), type=typ, lang=lang2(r.get("lang")),
                 title=r.get("title") or "", codec=r.get("codec") or "",
                 channels=r.get("demux-channel-count") or r.get("audio-channels"),
                 default=bool(r.get("default")), forced=bool(r.get("forced")),
                 hi=bool(r.get("hearing-impaired")), external=bool(r.get("external")),
                 selected=bool(r.get("selected")))
        (audio if typ == "audio" else subs).append(_finish(t))
    return audio, subs


def from_jellyfin(streams):
    """Jellyfin's MediaStreams -> (audio, subs). Ids are "j<Index>"; text subtitles (which
    can be sent as WebVTT) are marked `text`."""
    audio, subs = [], []
    for s in streams or []:
        typ = {"Audio": "audio", "Subtitle": "sub"}.get(s.get("Type"))
        if not typ or s.get("Index") is None:
            continue
        title = s.get("Title") or ""
        if typ == "sub" and not title:
            title = s.get("DisplayTitle") or ""
        t = dict(id=f"j{s['Index']}", index=int(s["Index"]), type=typ, lang=lang2(s.get("Language")), title=title,
                 codec=(s.get("Codec") or "").lower(), channels=s.get("Channels") or s.get("ChannelLayout"),
                 default=bool(s.get("IsDefault")), forced=bool(s.get("IsForced")),
                 hi=bool(s.get("IsHearingImpaired")), external=bool(s.get("IsExternal")),
                 text=bool(s.get("IsTextSubtitleStream")), selected=False)
        (audio if typ == "audio" else subs).append(_finish(t))
    return audio, subs


# ------------------------------------------------------------------ the choice
def _match(tracks, want):
    """The track best matching a remembered {lang, kind}, else None."""
    if not want:
        return None
    hits = [t for t in tracks if t.get("lang") == want.get("lang") and t.get("kind") == want.get("kind")]
    if not hits and want.get("title"):
        hits = [t for t in tracks if (t.get("title") or "") == want["title"]]
    if not hits:
        return None
    if want.get("external") is not None:
        same = [t for t in hits if bool(t.get("external")) == bool(want["external"])]
        hits = same or hits
    return hits[0]


def default_audio(audio):
    """English (a main track: the default-flagged, else the one with most channels), else
    the file's default, else the first main track."""
    if not audio:
        return None
    main = [t for t in audio if t.get("kind") != "commentary"] or audio
    english = [t for t in main if t.get("lang") == ENGLISH]
    if english:
        flagged = [t for t in english if t.get("default")]
        if flagged:
            return flagged[0]
        return max(english, key=lambda t: _ch_count(t.get("channels")))
    return next((t for t in main if t.get("default")), main[0])


def _ch_count(c):
    try:
        return float(str(c).split("(")[0])
    except (TypeError, ValueError):
        return {"mono": 1, "stereo": 2}.get(str(c).lower(), 0)


def default_subs(subs, audio_track):
    """Audio that isn't English: English subtitles (full, then SDH, then forced). English
    audio (or no audio): English forced subtitles, if any, else none."""
    english = [t for t in subs if t.get("lang") == ENGLISH]
    if not english:
        return None
    by = {k: [t for t in english if t.get("kind") == k] for k in SUB_KINDS}
    # unknown audio counts as English: subtitles nobody asked for are worse than one press
    if audio_track is None or audio_track.get("lang") in (ENGLISH, None):
        return (by["forced"] or [None])[0]
    for k in ("full", "sdh", "forced"):
        if by[k]:
            # an embedded track before a file beside the video (the file may be for another cut)
            return sorted(by[k], key=lambda t: bool(t.get("external")))[0]
    return None


def choose(audio, subs, memory=None):
    """(audio track or None, subtitle track or None) for what's on: the remembered choice
    where its languages are there, else the defaults."""
    memory = memory or {}
    a = _match(audio, memory.get("audio")) or default_audio(audio)
    want = memory.get("subs")
    if want == "off":
        return a, None
    s = _match(subs, want) if isinstance(want, dict) else None
    return a, s if s is not None else default_subs(subs, a)


def describe(t):
    """What's remembered of a track: its language and kind (and title, for a tie)."""
    if t is None:
        return "off"
    return {"lang": t.get("lang"), "kind": t.get("kind"), "title": (t.get("title") or "")[:80],
            "external": bool(t.get("external"))}


# ------------------------------------------------------------------ per series
def memory_key(item):
    """A series by its name; a film (or anything else) by its server and id."""
    item = item or {}
    if item.get("series"):
        return "series:" + re.sub(r"\s+", " ", str(item["series"]).strip().lower())
    if item.get("id"):
        return f"item:{item.get('server') or ''}:{item['id']}"
    return None


def remembered_name(item):
    item = item or {}
    return item.get("series") or item.get("title") or None


class Memory:
    """The choice per series, in $XDG_STATE_HOME/bromigos/den-tracks.json (0600)."""

    def __init__(self, path=None):
        root = os.environ.get("XDG_STATE_HOME") or os.path.expanduser("~/.local/state")
        self.path = path or os.path.join(root, "bromigos", "den-tracks.json")

    def _load(self):
        try:
            with open(self.path) as f:
                d = json.load(f)
            return d if isinstance(d, dict) else {}
        except (OSError, ValueError):
            return {}

    def get(self, item):
        k = memory_key(item)
        return self._load().get(k) if k else None

    def put(self, item, audio=None, subs=None, keep_audio=False, keep_subs=False):
        """Remember a choice: `audio` a track; `subs` a track or None (off). keep_*: leave
        that half as it was."""
        k = memory_key(item)
        if not k:
            return None
        d = self._load()
        row = dict(d.get(k) or {})
        if not keep_audio and audio is not None:
            row["audio"] = describe(audio)
        if not keep_subs:
            row["subs"] = describe(subs)
        row["at"] = int(time.time())
        d[k] = row
        if len(d) > MEMORY_MAX:
            for old in sorted(d, key=lambda x: (d[x] or {}).get("at", 0))[:len(d) - MEMORY_MAX]:
                d.pop(old, None)
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        tmp = self.path + ".new"
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as f:
            json.dump(d, f, indent=1, sort_keys=True)
        os.replace(tmp, self.path)
        return row


# ------------------------------------------------------------------ for the remotes
def public_track(t, selected=False):
    return {"id": t["id"], "lang": t.get("lang"), "label": t.get("label") or label(t), "kind": t.get("kind"),
            "external": bool(t.get("external")), "selected": bool(selected)}


def public(audio, subs, audio_id=None, sub_id=None, can=True, why=None, fetch=False, item=None, **where):
    """The JSON a remote gets: no paths, no addresses, no codecs beyond the label."""
    out = dict(ok=True, can=bool(can), audio=[public_track(t, t["id"] == audio_id) for t in audio],
               subs=[public_track(t, t["id"] == sub_id) for t in subs], sub_on=sub_id is not None,
               fetch=bool(fetch), remembered=remembered_name(item) if item else None)
    if why:
        out["why"] = why
    out.update({k: v for k, v in where.items() if v is not None})
    return out


def summary(audio, subs, audio_id=None, sub_id=None):
    """{"audio": label, "subs": label or None}: what a remote shows at a glance."""
    a = next((t for t in audio if t["id"] == audio_id), None)
    s = next((t for t in subs if t["id"] == sub_id), None)
    return {"audio": a["label"] if a else None, "subs": s["label"] if s else None}


def find(tracks, tid):
    return next((t for t in tracks if t["id"] == str(tid)), None)


# ------------------------------------------------------------------ finding subtitles
TO3 = {"en": "eng", "ja": "jpn", "fr": "fre", "de": "ger", "es": "spa", "it": "ita", "pt": "por", "ko": "kor",
       "zh": "chi", "ru": "rus", "nl": "dut", "sv": "swe", "no": "nor", "da": "dan", "fi": "fin", "pl": "pol",
       "hi": "hin", "ar": "ara", "tr": "tur", "el": "gre", "he": "heb", "hu": "hun", "cs": "cze", "th": "tha",
       "vi": "vie", "id": "ind", "ms": "may", "uk": "ukr", "ro": "rum", "tl": "fil"}


class FetchError(ValueError):
    pass


def _lab():
    try:
        from bromigos_homelab import mediareq
        return mediareq.Lab()
    except Exception:                                       # noqa: BLE001  (no homelab.toml, no bromigos-homelab)
        return None


_AVAILABLE = {}


def fetch_available(adapter, lab=None):
    """Subtitles can be looked for: the lab's Bazarr (with Sonarr or Radarr), or a subtitle
    plugin in the media server. Cached for ten minutes."""
    key = getattr(adapter, "name", None)
    hit = _AVAILABLE.get(key)
    if hit and time.time() - hit[1] < 600:
        return hit[0]
    lab = lab or _lab()
    ok = bool(lab and lab.app("bazarr") and (lab.app("sonarr") or lab.app("radarr")))
    if not ok and hasattr(adapter, "has_subtitle_search"):
        ok = bool(adapter.has_subtitle_search())
    _AVAILABLE[key] = (ok, time.time())
    return ok


def fetch_cached(adapter):
    """fetch_available's last answer for this server, or None when it hasn't been asked (for
    callers that mustn't wait on the network)."""
    hit = _AVAILABLE.get(getattr(adapter, "name", None))
    return hit[0] if hit and time.time() - hit[1] < 600 else None


def _bazarr(lab, ids, lang):
    """Ask Bazarr to find and download `lang` subtitles for one episode or film now. -> True
    when it was asked, False when Bazarr doesn't know the item."""
    import urllib.parse
    baz = lab.app("bazarr")
    if ids.get("kind") == "episode" and lab.app("sonarr") and ids.get("series_tvdb"):
        series = lab.arr_get("sonarr", "/series", tvdbId=ids["series_tvdb"]) or []
        if not series:
            return False
        sid = series[0]["id"]
        eps = lab.arr_get("sonarr", "/episode", seriesId=sid) or []
        ep = next((e for e in eps if e.get("seasonNumber") == ids.get("season")
                   and e.get("episodeNumber") == ids.get("episode")), None)
        if not ep:
            return False
        q = urllib.parse.urlencode({"seriesid": sid, "episodeid": ep["id"], "language": lang, "forced": "False",
                                    "hi": "False"})
        lab.call(baz, f"/api/episodes/subtitles?{q}", method="PATCH", timeout=60)
        return True
    if ids.get("kind") == "movie" and lab.app("radarr") and ids.get("tmdb"):
        movies = lab.arr_get("radarr", "/movie", tmdbId=ids["tmdb"]) or []
        if not movies:
            return False
        q = urllib.parse.urlencode({"radarrid": movies[0]["id"], "language": lang, "forced": "False", "hi": "False"})
        lab.call(baz, f"/api/movies/subtitles?{q}", method="PATCH", timeout=60)
        return True
    return False


def fetch_subs(item, lang, adapter, lab=None):
    """Look for `lang` subtitles for an item and download the best: the lab's Bazarr first
    (it follows Sonarr and Radarr), then the media server's own subtitle search. The server
    then looks beside the video again, so the new file shows in the list.
    -> {ok, message, via}; FetchError when nothing could look or nothing was found."""
    lang = lang2(lang) or ENGLISH
    name = lang_name(lang)
    lab = lab if lab is not None else _lab()
    tried = []
    if lab and lab.app("bazarr") and hasattr(adapter, "provider_ids"):
        try:
            if _bazarr(lab, adapter.provider_ids(item), lang):
                try:
                    adapter.refresh_item(item)
                except Exception:                           # noqa: BLE001  it shows at the next scan
                    pass
                return dict(ok=True, via="bazarr",
                            message=f"Bazarr looked for {name} subtitles; anything it found shows here in a moment")
            tried.append("Bazarr doesn't follow this title (it isn't in Sonarr or Radarr)")
        except Exception as e:                              # noqa: BLE001
            tried.append(f"Bazarr: {str(e)[:120]}")
    if hasattr(adapter, "has_subtitle_search") and adapter.has_subtitle_search():
        try:
            n = adapter.subtitle_search(item, TO3.get(lang, lang))
        except Exception as e:                              # noqa: BLE001
            raise FetchError(f"The media server's subtitle search failed: {str(e)[:120]}") from None
        if n:
            try:
                adapter.refresh_item(item)
            except Exception:                               # noqa: BLE001
                pass
            return dict(ok=True, via="server", message=f"Found {name} subtitles; they show here in a moment")
        raise FetchError(f"No {name} subtitles found for this")
    if tried:
        raise FetchError("; ".join(tried))
    raise FetchError("Nothing here looks for subtitles: add Bazarr to your lab, or a subtitle plugin to Jellyfin")
