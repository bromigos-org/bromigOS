"""Play on other screens: Google Cast, DLNA renderers, AirPlay, Jellyfin's own apps and the
den's screens, behind one list of targets. Shared by `bromigos media cast`, VECTOR's tools
and BRODEC's remote (through brodec-machine's [den] capability).

    targets(timeout=4.0, dry_run=False)   every target on the local network, and the den
    find(name_or_id)                      one target: its id, or words from its name or room
    play(target, screen=, title=, id_=, source=, url=, resume=)
    control(target, op, value=None)       play, pause, stop, seek N, volume N, volume-up,
                                          volume-down, mute, unmute
    status(target)                        what it plays
    handback(target, screen)              stop it there and go on from that moment on the den
    tracks(target)                        what it plays's audio tracks and subtitles
    set_audio(target, id) / set_subs(target, id | on | off)
    subs_fetch(target, lang)              look for subtitles for what it plays

Audio tracks and subtitles (lib/bromigos_tracks.py has the defaults and the memory per
series): a Jellyfin app switches them itself (SetAudioStreamIndex, SetSubtitleStreamIndex).
A Google Cast device plays the server's HLS stream with one audio track, so another track
(or picture subtitles, burnt in) is the same stream again from the same moment; text
subtitles go to it as a WebVTT track. Only what was cast from here can be changed on a
Cast device. DLNA renderers and AirPlay receivers pick their own: the answer says so.

Discovery listens on the local network only (mDNS for Cast and AirPlay, SSDP for DLNA) and
asks the Jellyfin server which of its apps can be steered. Nothing here opens a port or
reaches the internet. A target fetches its stream from the media server itself, with the
server's token in the address it is given: that address goes only to the target, never to
the output, the audit log or the cache.

Each protocol is optional: its library is imported when it's used, and `protocols` says
why one isn't available (python-pychromecast for Cast, python-async-upnp-client for DLNA,
python-pyatv for AirPlay).
"""
import argparse
import asyncio
import json
import os
import re
import sys
import threading
import time

KINDS = ("den", "cast", "dlna", "airplay", "jellyfin")
CAN_ALL = ("play", "pause", "seek", "volume", "stop", "youtube")
OPS = ("play", "pause", "stop", "seek", "volume", "volume-up", "volume-down", "mute", "unmute")
CACHE_FRESH = 600                 # seconds a discovery is used before looking again
DEN_DEVICE = "bromigos-den-tv"    # the den's own Jellyfin device id (labvideo.DEVICE)
DRM = ("Streaming apps' protected video (Netflix, Disney+, Prime Video and the like) can't be "
       "cast from here: start those from the app on the TV.")


class CastError(ValueError):
    def __init__(self, message, code=1):
        super().__init__(message)
        self.code = code


# ------------------------------------------------------------------ paths and audit
def _cache_path():
    root = os.environ.get("XDG_CACHE_HOME") or os.path.expanduser("~/.cache")
    return os.path.join(root, "bromigos", "cast-targets.json")


def _audit_path():
    root = os.environ.get("XDG_STATE_HOME") or os.path.expanduser("~/.local/state")
    return os.path.join(root, "bromigos", "cast-audit.jsonl")


def _private_write(path, text):
    os.makedirs(os.path.dirname(path), mode=0o700, exist_ok=True)
    tmp = f"{path}.{os.getpid()}.new"
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        f.write(text)
    os.replace(tmp, path)


def audit(action, target, item=None, ok=True, error=None, **extra):
    """One line per play, control and hand back: who, where, what. Never an address or token."""
    row = dict(at=round(time.time(), 3), caller=os.environ.get("BROMIGOS_CAST_CALLER") or "cli",
               action=action, target=target.get("id"), kind=target.get("kind"), name=target.get("name"), ok=ok)
    if item:
        row["item"] = {k: item.get(k) for k in ("id", "title", "series", "season", "episode", "server") if item.get(k)}
    if error:
        row["error"] = str(error)[:200]
    row.update({k: v for k, v in extra.items() if v is not None})
    path = _audit_path()
    try:
        os.makedirs(os.path.dirname(path), mode=0o700, exist_ok=True)
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
        with os.fdopen(fd, "a") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    except OSError:
        pass


# ------------------------------------------------------------------ helpers
def public(target):
    """A target as callers see it: no addresses or private fields."""
    out = {k: v for k, v in target.items() if not k.startswith("_")}
    out.setdefault("room", None)
    out.setdefault("model", None)
    out.setdefault("playing", None)
    out.setdefault("can", [])
    return out


def playing(title=None, state="idle", position=None, duration=None, volume=None, muted=False, audio=None, subs=None):
    out = dict(title=title or None, state=state, position=None if position is None else round(float(position), 1),
               duration=None if not duration else round(float(duration), 1),
               volume=None if volume is None else max(0, min(100, int(round(volume)))), muted=bool(muted))
    if audio:
        out["audio"] = audio
    if subs:
        out["subs"] = subs
    return out


NO_TRACKS = "This TV picks its own audio and subtitles: use its own remote"


def _T():
    import bromigos_tracks
    return bromigos_tracks


def _now_path():
    root = os.environ.get("XDG_STATE_HOME") or os.path.expanduser("~/.local/state")
    return os.path.join(root, "bromigos", "cast-now.json")


def _now_all():
    try:
        with open(_now_path()) as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def _now_record(target, item=None, audio=None, sub=None):
    """What was cast to a target from here and with which tracks (no addresses), or None to
    forget it."""
    d = _now_all()
    if item is None:
        d.pop(target["id"], None)
    else:
        d[target["id"]] = dict(item={k: item.get(k) for k in ("id", "title", "series", "season", "episode", "kind",
                                                               "server", "duration") if item.get(k) is not None},
                               audio=audio, sub=sub, at=int(time.time()))
    try:
        _private_write(_now_path(), json.dumps(d))
    except OSError:
        pass


def _server_tracks(item):
    """(adapter, audio, subs) for a media server item whose server lists its streams, else
    (adapter or None, None, None)."""
    a = _video_source(item.get("server"))
    if a is None or not hasattr(a, "video_streams"):
        return a, None, None
    audio, subs = _T().from_jellyfin(a.video_streams(item))
    return a, audio, subs


def _idx(t):
    return None if t is None else t.get("index")


def _run(coro, timeout):
    """Run a coroutine to completion in its own loop (callers are synchronous)."""
    async def bounded():
        return await asyncio.wait_for(coro, timeout)
    return asyncio.run(bounded())


def youtube_id(url):
    m = re.search(r"(?:v=|youtu\.be/|/shorts/|/embed/)([A-Za-z0-9_-]{11})", url or "")
    return m[1] if m else None


def _tvplay():
    import bromigos_tvplay
    return bromigos_tvplay


def _video_source(name):
    import bromigos_tv as TV
    H = TV._homelab()
    if H is None:
        return None
    try:
        return H.video_source(name or None)
    except Exception:                                       # noqa: BLE001
        return None


def _jellyfins():
    import bromigos_tv as TV
    H = TV._homelab()
    if H is None:
        return []
    try:
        from bromigos_homelab import registry
        return [a for a in registry.providers("video") if hasattr(a, "remote_sessions")]
    except Exception:                                       # noqa: BLE001
        return []


def media_url(item, hls=True, audio_index=None, burn_index=None):
    """(url, mime) a target fetches the item from: the media server's stream with its token
    in the address (the target can't send headers). Kept away from every output."""
    a = _video_source(item.get("server"))
    if a is None or not hasattr(a, "video_cast_url"):
        raise CastError(f"No media server for {item.get('title') or 'that item'}; " + DRM, 4)
    if audio_index is None and burn_index is None:
        return a.video_cast_url(item, hls=hls)
    return a.video_cast_url(item, hls=hls, audio_index=audio_index, burn_index=burn_index)


LOAD_WATCH = 8.0                   # seconds a Cast target has to start loading what it was sent


def _loaded_or_raise(mc, watch):
    """Wait up to `watch` seconds for a Cast target to start on what it was sent. A target
    that took the title but couldn't fetch the stream goes back to idle with an error: say
    so, instead of reporting a cast that never plays."""
    end = time.monotonic() + watch
    while time.monotonic() < end:
        ms = mc.status
        state = (getattr(ms, "player_state", "") or "").upper()
        if state in ("PLAYING", "BUFFERING", "PAUSED"):
            return
        if state == "IDLE" and (getattr(ms, "idle_reason", "") or "").upper() == "ERROR":
            raise CastError("The TV took the title but couldn't load the stream. It must reach the "
                            "media server at an address it can resolve, with a certificate it trusts: "
                            "set cast_url for the source in homelab.toml, or the server's published "
                            "address", 4)
        time.sleep(.3)


# ------------------------------------------------------------------ backends
class Backend:
    kind = ""
    hls = True                     # the stream form it plays best: HLS, else the file as it is

    def available(self):
        return True, None

    def discover(self, timeout):
        return []

    def play(self, target, item, start):
        raise CastError(f"{self.kind} can't play that", 2)

    def control(self, target, op, value):
        raise CastError(f"{self.kind} can't {op}", 2)

    def status(self, target):
        return None

    def tracks(self, target):
        return _T().public([], [], can=False, why=NO_TRACKS, target=target["id"])

    def set_track(self, target, kind, value):
        raise CastError(NO_TRACKS, 2)


class Den(Backend):
    """The den's own screens, through the same library as Den TV and its remote."""
    kind = "den"
    NAMES = {"big": "Den · big monitor", "wave": "Den · scope", "emblem": "Den · small monitor"}

    def discover(self, timeout):
        try:
            from bromigos_tvchannels import live_state
            state = live_state()
        except Exception:                                   # noqa: BLE001
            state = None
        if not state:
            return []
        rows = []
        for screen, r in (state.get("screens") or {}).items():
            on = r.get("now") or r.get("name")
            rows.append(dict(id=f"den:{screen}", kind="den", name=self.NAMES.get(screen, screen), room="Den",
                             model="bromigOS den TV", can=["play", "volume", "stop", "youtube"],
                             playing=playing(on, "playing" if r.get("now") else "idle", r.get("offset"),
                                             (r.get("item") or {}).get("duration"),
                                             r.get("volume"), not r.get("sound"))))
        return rows

    def _screen(self, target):
        return target["id"].split(":", 1)[1]

    def play(self, target, item, start):
        it = dict(item)
        if start:
            it["position"] = start
        return _tvplay().play(self._screen(target), item=it, resume=bool(start))

    def control(self, target, op, value):
        import bromigos_tvremote as R
        s = self._screen(target)
        if op == "volume":
            return R.volume(str(int(value)), s)
        if op in ("volume-up", "volume-down"):
            return R.volume(op.split("-")[1], s)
        if op in ("mute", "unmute"):
            return R.sound("off" if op == "mute" else "on", s)
        if op == "stop":
            return R.back_to_channel(s)
        if op == "play":
            return R.sound("on", s)
        raise CastError("The den's screens play like TV: pause and seek aren't there", 2)

    def tracks(self, target):
        return _T().public([], [], can=False, why="Use the den screen's own audio and CC buttons", target=target["id"])

    def status(self, target):
        rows = {r["id"]: r for r in self.discover(1)}
        return (rows.get(target["id"]) or {}).get("playing")


class Jellyfin(Backend):
    """Jellyfin's own apps (TVs, phones, browsers) that let the server steer them."""
    kind = "jellyfin"

    def available(self):
        return (True, None) if _jellyfins() else (False, "No Jellyfin source in homelab.toml")

    def discover(self, timeout):
        rows = []
        for a in _jellyfins():
            try:
                sessions = a.remote_sessions()
            except Exception as e:                          # noqa: BLE001
                raise CastError(f"{a.name}: {type(e).__name__}") from None
            for s in sessions:
                if not s.get("SupportsRemoteControl") or s.get("DeviceId") in (None, DEN_DEVICE):
                    continue
                if "Video" not in (s.get("PlayableMediaTypes") or ["Video"]):
                    continue
                rows.append(self._row(a, s))
        return rows

    @staticmethod
    def _switches(s):
        cmds = s.get("SupportedCommands")
        return cmds is None or "SetAudioStreamIndex" in cmds or "SetSubtitleStreamIndex" in cmds

    @staticmethod
    def _now_tracks(s):
        """(audio, subs, audio id, subtitle id) of what a session plays, from its own report."""
        now = s.get("NowPlayingItem") or {}
        ps = s.get("PlayState") or {}
        audio, subs = _T().from_jellyfin(now.get("MediaStreams") or [])
        ai, si = ps.get("AudioStreamIndex"), ps.get("SubtitleStreamIndex")
        return audio, subs, (f"j{ai}" if ai is not None else None), (f"j{si}" if si not in (None, -1) else None)

    def _row(self, a, s):
        now = s.get("NowPlayingItem") or {}
        ps = s.get("PlayState") or {}
        title = now.get("Name")
        if now.get("SeriesName"):
            title = f"{now['SeriesName']} · {title}"
        state = "idle" if not now else ("paused" if ps.get("IsPaused") else "playing")
        glance = {}
        if now:
            audio, subs, aid, sid = self._now_tracks(s)
            glance = _T().summary(audio, subs, aid, sid)
        can = ["play", "pause", "seek", "volume", "stop"] + (["tracks"] if self._switches(s) else [])
        return dict(id=f"jellyfin:{s['DeviceId']}", kind="jellyfin",
                    name=s.get("DeviceName") or s.get("Client") or "Jellyfin app", room=None,
                    model=" ".join(v for v in (s.get("Client"), s.get("ApplicationVersion")) if v) or None,
                    can=can, _source=a.name,
                    playing=playing(title, state, (ps.get("PositionTicks") or 0) / 1e7 if now else None,
                                    (now.get("RunTimeTicks") or 0) / 1e7, ps.get("VolumeLevel"), ps.get("IsMuted"),
                                    glance.get("audio"), glance.get("subs")))

    def _session(self, target):
        device = target["id"].split(":", 1)[1]
        for a in _jellyfins():
            if target.get("_source") and a.name != target["_source"]:
                continue
            for s in a.remote_sessions():
                if s.get("DeviceId") == device:
                    return a, s
        raise CastError(f"{target.get('name')} isn't open in Jellyfin now", 4)

    def play(self, target, item, start):
        a, s = self._session(target)
        if item.get("server") != a.name:
            raise CastError(f"{target.get('name')} plays only what's on {a.name}", 2)
        at = st = None
        if hasattr(a, "video_streams"):
            try:
                audio, subs = _T().from_jellyfin(a.video_streams(item))
                at, st = _T().choose(audio, subs, _T().Memory().get(item))
            except Exception:                               # noqa: BLE001  the app's own choice, then
                at = st = None
        if at is None and st is None:
            a.remote_play(s["Id"], item["id"], start or 0)
        else:
            a.remote_play(s["Id"], item["id"], start or 0, audio_index=_idx(at), sub_index=_idx(st) if st else -1)

    def _now_item(self, a, s):
        now = s.get("NowPlayingItem") or {}
        return {"id": now.get("Id"), "title": now.get("Name"), "series": now.get("SeriesName"),
                "season": now.get("ParentIndexNumber"), "episode": now.get("IndexNumber"), "server": a.name}

    def tracks(self, target):
        a, s = self._session(target)
        if not s.get("NowPlayingItem"):
            return _T().public([], [], can=False, why="Nothing's playing on it", target=target["id"])
        if not self._switches(s):
            return _T().public([], [], can=False, why=NO_TRACKS, target=target["id"])
        audio, subs, aid, sid = self._now_tracks(s)
        item = self._now_item(a, s)
        if not audio and not subs and hasattr(a, "video_streams"):
            audio, subs = _T().from_jellyfin(a.video_streams(item))
        try:
            fetch = _T().fetch_available(a)
        except Exception:                                   # noqa: BLE001
            fetch = False
        return _T().public(audio, subs, aid, sid, fetch=fetch, item=item, target=target["id"])

    def set_track(self, target, kind, value):
        T = _T()
        a, s = self._session(target)
        if not s.get("NowPlayingItem"):
            raise CastError("Nothing's playing on it", 4)
        audio, subs, aid, sid = self._now_tracks(s)
        item = self._now_item(a, s)
        if kind == "audio":
            t = T.find(audio, value)
            if t is None:
                raise CastError("No such audio track", 2)
            a.remote_command(s["Id"], "SetAudioStreamIndex", {"Index": str(t["index"])})
            T.Memory().put(item, audio=t, keep_subs=True)
            aid = t["id"]
        else:
            t = _pick_sub(subs, audio, aid, sid, value, T.Memory().get(item))
            a.remote_command(s["Id"], "SetSubtitleStreamIndex", {"Index": str(t["index"] if t else -1)})
            T.Memory().put(item, subs=t, keep_audio=True)
            sid = t["id"] if t else None
        return T.public(audio, subs, aid, sid, item=item, target=target["id"])

    def control(self, target, op, value):
        a, s = self._session(target)
        if op in ("play", "pause", "stop"):
            a.remote_playstate(s["Id"], {"play": "Unpause", "pause": "Pause", "stop": "Stop"}[op])
        elif op == "seek":
            a.remote_playstate(s["Id"], "Seek", float(value))
        elif op == "volume":
            a.remote_command(s["Id"], "SetVolume", {"Volume": str(int(value))})
        else:
            a.remote_command(s["Id"], {"volume-up": "VolumeUp", "volume-down": "VolumeDown",
                                       "mute": "Mute", "unmute": "Unmute"}[op])

    def status(self, target):
        a, s = self._session(target)
        return self._row(a, s)["playing"]


class Cast(Backend):
    """Google Cast: Chromecast, Google TV, Nest screens and speakers (pychromecast)."""
    kind = "cast"

    def available(self):
        try:
            import pychromecast  # noqa: F401
            return True, None
        except ImportError:
            return False, "python-pychromecast isn't installed"

    def discover(self, timeout):
        import pychromecast
        infos, browser = pychromecast.discovery.discover_chromecasts(timeout=timeout)
        try:
            browser.stop_discovery()
        except Exception:                                   # noqa: BLE001
            pass
        rows = []
        for ci in infos:
            audio = (ci.cast_type or "") == "audio"
            can = ["play", "pause", "seek", "volume", "stop"] + ([] if audio else ["youtube", "tracks"])
            rows.append(dict(id=f"cast:{ci.uuid}", kind="cast", name=ci.friendly_name or ci.model_name or "Cast device",
                             room=None, model=" ".join(v for v in (ci.manufacturer, ci.model_name) if v) or None,
                             can=can, _host=str(ci.host), _port=int(ci.port or 8009), _uuid=str(ci.uuid),
                             _model=ci.model_name, _cast_type=ci.cast_type))
        # what each one plays: read only, in parallel, within what's left of the budget
        threads = [threading.Thread(target=self._peek, args=(r, min(3.0, timeout)), daemon=True) for r in rows]
        for t in threads:
            t.start()
        for t in threads:
            t.join(min(3.5, timeout + .5))
        return rows

    def _peek(self, row, timeout):
        try:
            row["playing"] = self.status(row, timeout)
        except Exception:                                   # noqa: BLE001
            row["playing"] = None

    def _connect(self, target, timeout=8.0):
        import uuid
        import pychromecast
        cc = pychromecast.get_chromecast_from_host(
            (target["_host"], target.get("_port") or 8009, uuid.UUID(target["_uuid"]), target.get("_model"),
             target.get("name")), tries=1, timeout=timeout)
        cc.wait(timeout=timeout)
        return cc

    def status(self, target, timeout=6.0):
        cc = self._connect(target, timeout)
        try:
            ms = cc.media_controller.status
            try:
                cc.media_controller.update_status()
                time.sleep(.4)
            except Exception:                               # noqa: BLE001
                pass
            vol = (cc.status.volume_level or 0) * 100 if cc.status else None
            muted = bool(cc.status and cc.status.volume_muted)
            st = (ms.player_state or "").lower() if ms else ""
            state = {"playing": "playing", "paused": "paused", "buffering": "buffering"}.get(st, "idle")
            title = (ms.title if ms and ms.title else None) or (None if cc.is_idle else cc.app_display_name)
            glance = self._glance(target, title)
            return playing(title, state if title else "idle", ms.adjusted_current_time if ms else None,
                           ms.duration if ms else None, vol, muted, glance.get("audio"), glance.get("subs"))
        finally:
            cc.disconnect(timeout=2)

    @staticmethod
    def _ours(target, title):
        """What was cast here from this machine, when the TV still plays it."""
        rec = _now_all().get(target["id"])
        if not rec or not title or title != _label(rec.get("item") or {}):
            return None
        return rec

    def _glance(self, target, title):
        rec = self._ours(target, title)
        if not rec:
            return {}
        try:
            a, audio, subs = _server_tracks(rec["item"])
        except Exception:                                   # noqa: BLE001
            return {}
        if audio is None:
            return {}
        return _T().summary(audio, subs, rec.get("audio"), rec.get("sub"))

    def _now(self, target):
        """(record, audio, subs, position) for what was cast here, or a CastError saying why not."""
        now = self.status(target) or {}
        if not now.get("title") or now.get("state") == "idle":
            raise CastError("Nothing's playing on it", 4)
        rec = self._ours(target, now["title"])
        if not rec:
            raise CastError("It's playing something that wasn't cast from here: change its audio and subtitles "
                            "on the TV", 4)
        a, audio, subs = _server_tracks(rec["item"])
        if audio is None:
            raise CastError(NO_TRACKS, 4)
        return rec, audio, subs, now.get("position") or 0, a

    def tracks(self, target):
        T = _T()
        try:
            rec, audio, subs, _pos, a = self._now(target)
        except CastError as e:
            return T.public([], [], can=False, why=str(e), target=target["id"])
        try:
            fetch = T.fetch_available(a)
        except Exception:                                   # noqa: BLE001
            fetch = False
        return T.public(audio, subs, rec.get("audio"), rec.get("sub"), fetch=fetch, item=rec["item"],
                        target=target["id"])

    def set_track(self, target, kind, value):
        T = _T()
        rec, audio, subs, pos, _a = self._now(target)
        item = rec["item"]
        at = T.find(audio, rec.get("audio")) if rec.get("audio") else None
        st = T.find(subs, rec.get("sub")) if rec.get("sub") else None
        if kind == "audio":
            at = T.find(audio, value)
            if at is None:
                raise CastError("No such audio track", 2)
            T.Memory().put(item, audio=at, keep_subs=True)
        else:
            st = _pick_sub(subs, audio, rec.get("audio"), rec.get("sub"), value, T.Memory().get(item))
            T.Memory().put(item, subs=st, keep_audio=True)
        self.play(target, item, pos, tracks=(at, st))           # the same stream, from the same moment
        return T.public(audio, subs, at["id"] if at else None, st["id"] if st else None, item=item,
                        target=target["id"])

    def play(self, target, item, start, tracks=None):
        cc = self._connect(target)
        try:
            if item.get("server") == "youtube" or youtube_id(item.get("url")):
                _now_record(target)
                vid = youtube_id(item.get("url") or item.get("id"))
                if not vid:
                    raise CastError("That isn't a YouTube video", 2)
                try:
                    from pychromecast.controllers.youtube import YouTubeController
                except ImportError:
                    raise CastError("YouTube on Cast needs python-casttube", 4) from None
                yt = YouTubeController()
                cc.register_handler(yt)
                yt.play_video(vid)
                return
            at, st, sub = None, None, {}
            if tracks is not None:
                at, st = tracks
                a, audio, subs = _video_source(item.get("server")), None, None
            else:
                try:
                    a, audio, subs = _server_tracks(item)
                    if audio is not None:
                        at, st = _T().choose(audio, subs, _T().Memory().get(item))
                except Exception:                           # noqa: BLE001  the stream's own tracks, then
                    a, at, st = None, None, None
            burn = st["index"] if st and not st.get("text") else None
            if st and st.get("text") and a is not None and hasattr(a, "video_cast_subtitle_url"):
                sub = dict(subtitles=a.video_cast_subtitle_url(item, st["index"]), subtitles_mime="text/vtt",
                           subtitles_lang=st.get("lang") or "und")
            url, mime = media_url(item, hls=True, audio_index=_idx(at), burn_index=burn)
            mc = cc.media_controller
            mc.play_media(url, mime, title=_label(item), stream_type="BUFFERED",
                          current_time=float(start) if start else None, **sub)
            mc.block_until_active(timeout=10)
            # Active only means the TV took the title: it may still fail to load the stream.
            _loaded_or_raise(mc, LOAD_WATCH)
            _now_record(target, item, at["id"] if at else None, st["id"] if st else None)
        finally:
            cc.disconnect(timeout=2)

    def control(self, target, op, value):
        cc = self._connect(target)
        try:
            mc = cc.media_controller
            if op in ("play", "pause", "stop", "seek"):
                try:
                    mc.update_status()
                    time.sleep(.3)
                except Exception:                           # noqa: BLE001
                    pass
            if op == "play":
                mc.play()
            elif op == "pause":
                mc.pause()
            elif op == "stop":
                cc.quit_app()
                _now_record(target)
            elif op == "seek":
                mc.seek(float(value))
            elif op == "volume":
                cc.set_volume(max(0, min(100, float(value))) / 100)
            elif op == "volume-up":
                cc.volume_up(.05)
            elif op == "volume-down":
                cc.volume_down(.05)
            elif op in ("mute", "unmute"):
                cc.set_volume_muted(op == "mute")
        finally:
            cc.disconnect(timeout=2)


class Dlna(Backend):
    """DLNA/UPnP media renderers: most smart TVs (async-upnp-client)."""
    kind = "dlna"
    hls = False
    ST = "urn:schemas-upnp-org:device:MediaRenderer:1"

    def available(self):
        try:
            import async_upnp_client.profiles.dlna  # noqa: F401
            import async_upnp_client.aiohttp  # noqa: F401
            return True, None
        except ImportError:
            return False, "python-async-upnp-client isn't installed"

    def discover(self, timeout):
        return _run(self._discover(timeout), timeout + 6)

    async def _discover(self, timeout):
        from async_upnp_client.search import async_search
        found = {}

        async def seen(headers):
            loc = headers.get("location")
            if loc:
                found.setdefault(loc, dict(headers))

        await async_search(seen, timeout=max(1, int(timeout)), search_target=self.ST)
        rows = []
        for loc in found:
            try:
                dmr = await self._device(loc)
            except Exception:                               # noqa: BLE001
                continue
            dev = dmr.device
            row = dict(id=f"dlna:{dev.udn}", kind="dlna", name=dev.friendly_name or "DLNA renderer", room=None,
                       model=" ".join(v for v in (dev.manufacturer, dev.model_name) if v) or None,
                       can=["play", "pause", "seek", "volume", "stop"], _location=loc)
            try:
                await dmr.async_update()
                row["playing"] = self._playing(dmr)
            except Exception:                               # noqa: BLE001
                row["playing"] = None
            rows.append(row)
        return rows

    async def _device(self, location):
        from async_upnp_client.aiohttp import AiohttpRequester
        from async_upnp_client.client_factory import UpnpFactory
        from async_upnp_client.profiles.dlna import DmrDevice
        device = await UpnpFactory(AiohttpRequester()).async_create_device(location)
        return DmrDevice(device, None)

    @staticmethod
    def _playing(dmr):
        st = str(getattr(dmr.transport_state, "value", dmr.transport_state) or "")
        state = {"PLAYING": "playing", "PAUSED_PLAYBACK": "paused", "TRANSITIONING": "buffering"}.get(st, "idle")
        vol = dmr.volume_level * 100 if dmr.has_volume_level and dmr.volume_level is not None else None
        return playing(dmr.media_title if state != "idle" else None, state, dmr.media_position, dmr.media_duration,
                       vol, dmr.is_volume_muted if dmr.has_volume_mute else False)

    def _do(self, target, fn):
        async def go():
            dmr = await self._device(target["_location"])
            await dmr.async_update()
            return await fn(dmr)
        return _run(go(), 20)

    def play(self, target, item, start):
        if item.get("server") == "youtube":
            raise CastError("A TV's DLNA player can't play YouTube; use a Cast device or the den", 2)
        url, mime = media_url(item, hls=False)

        async def go(dmr):
            from datetime import timedelta
            meta = await dmr.construct_play_media_metadata(url, _label(item), default_mime_type=mime,
                                                           default_upnp_class="object.item.videoItem")
            await dmr.async_set_transport_uri(url, _label(item), meta)
            await dmr.async_wait_for_can_play()
            await dmr.async_play()
            if start and dmr.has_seek_rel_time:
                await dmr.async_seek_rel_time(timedelta(seconds=int(start)))
        self._do(target, go)

    def control(self, target, op, value):
        async def go(dmr):
            from datetime import timedelta
            if op == "play":
                await dmr.async_play()
            elif op == "pause":
                await dmr.async_pause()
            elif op == "stop":
                await dmr.async_stop()
            elif op == "seek":
                await dmr.async_seek_rel_time(timedelta(seconds=int(float(value))))
            elif op in ("volume", "volume-up", "volume-down"):
                if not dmr.has_volume_level:
                    raise CastError(f"{target.get('name')} doesn't take volume over DLNA", 2)
                cur = (dmr.volume_level or 0) * 100
                v = float(value) if op == "volume" else cur + (5 if op == "volume-up" else -5)
                await dmr.async_set_volume_level(max(0, min(100, v)) / 100)
            elif op in ("mute", "unmute"):
                await dmr.async_mute_volume(op == "mute")
        self._do(target, go)

    def status(self, target):
        async def go(dmr):
            return self._playing(dmr)
        return self._do(target, go)


class AirPlay(Backend):
    """AirPlay receivers: Apple TV and AirPlay 2 TVs (pyatv). A device that asks for a PIN
    needs pairing once with pyatv's `atvremote … pair`; its credentials are in pyatv's own
    file. AirPlay video plays while its sender stays connected, so a small helper process
    keeps the connection until the video ends or is stopped."""
    kind = "airplay"

    def available(self):
        try:
            import pyatv  # noqa: F401
            return True, None
        except ImportError:
            return False, "python-pyatv isn't installed"

    def discover(self, timeout):
        return _run(self._scan(timeout), timeout + 4)

    async def _scan(self, timeout, identifier=None):
        import pyatv
        from pyatv.const import Protocol
        loop = asyncio.get_running_loop()
        confs = await pyatv.scan(loop, timeout=max(1, int(timeout)), protocol=Protocol.AirPlay,
                                 identifier=identifier)
        if identifier:
            return confs
        rows = []
        for c in confs:
            model = None
            try:
                model = c.device_info.model_str
            except Exception:                               # noqa: BLE001
                pass
            if model and "homepod" in model.lower():
                continue                                    # speakers: no picture
            rows.append(dict(id=f"airplay:{c.identifier}", kind="airplay", name=c.name or "AirPlay receiver",
                             room=None, model=model, can=["play", "pause", "seek", "volume", "stop"],
                             _identifier=c.identifier, _host=str(c.address)))
        return rows

    async def _connect(self, target):
        import pyatv
        loop = asyncio.get_running_loop()
        confs = await pyatv.scan(loop, timeout=3, identifier=target["_identifier"], hosts=[target["_host"]])
        if not confs:
            raise CastError(f"{target.get('name')} isn't answering", 4)
        storage = None
        try:
            from pyatv.storage.file_storage import FileStorage
            storage = FileStorage.default_storage(loop)
            await storage.load()
        except Exception:                                   # noqa: BLE001
            storage = None
        return await pyatv.connect(confs[0], loop, storage=storage)

    def _keeper(self, target):
        run = os.environ.get("XDG_RUNTIME_DIR") or f"/run/user/{os.getuid()}"
        return os.path.join(run, "bromigos-cast", "airplay-" + re.sub(r"[^A-Za-z0-9_-]", "_", target["_identifier"]))

    def play(self, target, item, start):
        if item.get("server") == "youtube":
            raise CastError("AirPlay can't play a YouTube link from here; use a Cast device or the den", 2)
        url, _mime = media_url(item, hls=True)
        self._stop_keeper(target)
        folder = os.path.dirname(self._keeper(target))
        os.makedirs(folder, mode=0o700, exist_ok=True)
        req = json.dumps(dict(target={k: target[k] for k in ("_identifier", "_host", "name")}, url=url,
                              start=start or 0, title=_label(item)))
        import subprocess
        p = subprocess.Popen([sys.executable, "-m", "bromigos_cast", "_airplay-keep", self._keeper(target)],
                             stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                             start_new_session=True, env=dict(os.environ, PYTHONPATH=os.pathsep.join(sys.path)))
        p.stdin.write(req.encode())
        p.stdin.close()
        _private_write(self._keeper(target) + ".json", json.dumps(dict(pid=p.pid, title=_label(item), at=time.time())))

    def _stop_keeper(self, target):
        import signal
        try:
            with open(self._keeper(target) + ".json") as f:
                pid = json.load(f)["pid"]
            os.kill(int(pid), signal.SIGTERM)
        except (OSError, ValueError, KeyError):
            pass

    def control(self, target, op, value):
        if op == "stop":
            self._stop_keeper(target)

        async def go():
            atv = await self._connect(target)
            try:
                rc = atv.remote_control
                if op == "play":
                    await rc.play()
                elif op == "pause":
                    await rc.pause()
                elif op == "stop":
                    await rc.stop()
                elif op == "seek":
                    await rc.set_position(int(float(value)))
                elif op in ("volume", "volume-up", "volume-down"):
                    if op == "volume":
                        await atv.audio.set_volume(max(0.0, min(100.0, float(value))))
                    elif op == "volume-up":
                        await atv.audio.volume_up()
                    else:
                        await atv.audio.volume_down()
                else:
                    raise CastError("AirPlay has no mute from here; turn the volume down", 2)
            finally:
                atv.close()
        try:
            _run(go(), 20)
        except CastError:
            raise
        except Exception as e:                              # noqa: BLE001
            if op == "stop":
                return
            raise CastError(f"{target.get('name')}: {type(e).__name__}; pair it once with atvremote "
                            "if it asks for a PIN", 4) from None

    def status(self, target):
        async def go():
            atv = await self._connect(target)
            try:
                p = await atv.metadata.playing()
                st = str(getattr(p.device_state, "name", p.device_state) or "").lower()
                state = {"playing": "playing", "paused": "paused", "loading": "buffering"}.get(st, "idle")
                vol = None
                try:
                    vol = atv.audio.volume
                except Exception:                           # noqa: BLE001
                    pass
                return playing(p.title, state, p.position, p.total_time, vol, False)
            finally:
                atv.close()
        try:
            return _run(go(), 15)
        except Exception:                                   # noqa: BLE001
            try:
                with open(self._keeper(target) + ".json") as f:
                    k = json.load(f)
                os.kill(int(k["pid"]), 0)
                return playing(k.get("title"), "playing")
            except (OSError, ValueError, KeyError):
                return None


def _airplay_keep(path):
    """The helper that holds an AirPlay video's connection until it ends or is stopped."""
    req = json.loads(sys.stdin.read())
    b = AirPlay()

    async def go():
        atv = await b._connect(req["target"])
        try:
            await atv.stream.play_url(req["url"], position=int(req.get("start") or 0))
        finally:
            atv.close()
    try:
        asyncio.run(go())
    finally:
        try:
            os.unlink(path + ".json")
        except OSError:
            pass


BACKENDS = {"den": Den(), "jellyfin": Jellyfin(), "cast": Cast(), "dlna": Dlna(), "airplay": AirPlay()}


def _label(item):
    try:
        import bromigos_tv as TV
        return TV.label(item) or item.get("title") or "Video"
    except Exception:                                       # noqa: BLE001
        return item.get("title") or "Video"


# ------------------------------------------------------------------ the API
def protocols():
    out = {}
    for kind in KINDS[1:]:
        ok, why = BACKENDS[kind].available()
        out[kind] = dict(available=bool(ok), **({"why": why} if why else {}))
    return out


def targets(timeout=4.0, dry_run=False):
    """Every target: the den's screens, then each available protocol's, found in parallel."""
    timeout = max(1.0, min(15.0, float(timeout)))
    protos = protocols()
    found, errors = {}, {}

    def run(kind):
        try:
            found[kind] = BACKENDS[kind].discover(timeout)
        except Exception as e:                              # noqa: BLE001
            errors[kind] = f"{type(e).__name__}: {e}" if isinstance(e, CastError) else type(e).__name__
            found[kind] = []

    kinds = ["den"] + [k for k in KINDS[1:] if protos[k]["available"]]
    threads = [threading.Thread(target=run, args=(k,), daemon=True) for k in kinds]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout + 12)
    rows = [r for k in kinds for r in sorted(found.get(k) or [], key=lambda r: r.get("name") or "")]
    for kind, why in errors.items():
        if kind in protos:
            protos[kind]["error"] = why
    at = int(time.time())
    if not dry_run:
        _private_write(_cache_path(), json.dumps(dict(at=at, targets=rows)))
    return dict(ok=True, targets=[public(r) for r in rows], protocols=protos, at=at)


def _cached():
    try:
        with open(_cache_path()) as f:
            doc = json.load(f)
        return doc.get("targets") or [], doc.get("at") or 0
    except (OSError, ValueError):
        return [], 0


ALIASES = {"chromecast": "cast", "google": "cast", "nest": "cast", "cast": "cast", "airplay": "airplay",
           "apple": "airplay", "dlna": "dlna", "upnp": "dlna", "jellyfin": "jellyfin", "den": "den"}
FILLER = {"the", "a", "on", "in", "to", "tv", "screen", "device", "my"}


def _words(text):
    return [w for w in re.findall(r"[a-z0-9]+", (text or "").casefold()) if w not in FILLER]


def _match(rows, query):
    q = (query or "").strip()
    hit = [r for r in rows if r["id"] == q]
    if hit:
        return hit
    words = _words(q)
    if not words:
        return []
    scored = []
    for r in rows:
        hay = set(_words(" ".join(str(r.get(k) or "") for k in ("name", "room", "model", "kind"))))
        hay |= {ALIASES[w] for w in list(hay) if w in ALIASES}
        need = [ALIASES.get(w, w) for w in words]
        if all(w in hay or any(h.startswith(w) for h in hay) for w in need):
            scored.append(r)
    return scored


def find(name_or_id, fresh=False):
    """One target, by its id or by words from its name, room or kind ("living room chromecast")."""
    rows, at = _cached()
    hits = [] if fresh or time.time() - at > CACHE_FRESH else _match(rows, name_or_id)
    if not hits:
        rows = list(BACKENDS["den"].discover(2)) if (name_or_id or "").startswith("den:") else None
        hits = _match(rows, name_or_id) if rows else []
    if not hits:
        targets()
        rows, _ = _cached()
        hits = _match(rows, name_or_id)
    if not hits:
        raise CastError(f"No cast target called {name_or_id!r}; `bromigos media cast targets` lists them", 4)
    if len(hits) > 1:
        exact = [r for r in hits if (r.get("name") or "").casefold() == (name_or_id or "").casefold()]
        if len(exact) == 1:
            return exact[0]
        raise CastError("Several targets match: " + ", ".join(f"{r['name']} ({r['id']})" for r in hits[:6]), 3)
    return hits[0]


def _item(screen=None, title=None, id_=None, source=None, url=None, resume=False):
    """(item, start): what to play and from where."""
    P = _tvplay()
    if screen:
        from bromigos_tvchannels import live_state
        state = live_state()
        if not state:
            raise CastError("The den TV isn't running", 3)
        row = (state.get("screens") or {}).get(P.screen_name(screen)) or {}
        item = row.get("item")
        if not item:
            raise CastError("Nothing to cast on that screen: it shows its own picture", 2)
        if item.get("server") == "files":
            raise CastError("Files on this machine can't be cast; pick it from the media server", 2)
        return item, row.get("offset") or 0
    try:
        item = P.resolve(title, id_, url, source)
    except ValueError as e:
        raise CastError(str(e), getattr(e, "code", 4)) from None
    if item.get("kind") in ("show", "season"):
        raise CastError("Pick an episode to play", 2)
    return item, (item.get("position") or 0) if resume else 0


def _target(target):
    return target if isinstance(target, dict) else find(target)


def play(target, screen=None, title=None, id_=None, source=None, url=None, resume=False):
    t = _target(target)
    item, start = _item(screen, title, id_, source, url, resume)
    b = BACKENDS[t["kind"]]
    try:
        b.play(t, item, start)
    except Exception as e:
        audit("play", t, item, ok=False, error=e)
        if isinstance(e, CastError):
            raise
        raise CastError(f"{t.get('name')}: {type(e).__name__}", 1) from None
    audit("play", t, item, start=round(start) if start else None)
    P = _tvplay()
    return dict(ok=True, target=t["id"], name=t.get("name"), item=P.public_item(item),
                message=f"Playing {_label(item)} on {t.get('name')}")


def control(target, op, value=None):
    t = _target(target)
    if op not in OPS:
        raise CastError("Do: " + ", ".join(OPS), 2)
    if op in ("seek", "volume"):
        try:
            value = float(value)
        except (TypeError, ValueError):
            raise CastError(f"{op} needs a number", 2) from None
    b = BACKENDS[t["kind"]]
    try:
        b.control(t, op, value)
    except Exception as e:
        audit("control", t, ok=False, error=e, op=op)
        if isinstance(e, CastError):
            raise
        raise CastError(f"{t.get('name')}: {type(e).__name__}", 1) from None
    audit("control", t, op=op, value=value)
    try:
        now = b.status(t)
    except Exception:                                       # noqa: BLE001
        now = None
    return dict(ok=True, target=t["id"], name=t.get("name"), playing=now, message=f"{t.get('name')}: {op}")


def status(target):
    t = _target(target)
    try:
        now = BACKENDS[t["kind"]].status(t)
    except CastError:
        raise
    except Exception as e:                                  # noqa: BLE001
        raise CastError(f"{t.get('name')}: {type(e).__name__}", 1) from None
    return dict(ok=True, target=t["id"], name=t.get("name"), playing=now)


def handback(target, screen):
    """Stop the target and go on from the same moment on a den screen."""
    t = _target(target)
    if t["kind"] == "den":
        raise CastError("That's already the den", 2)
    P = _tvplay()
    screen = P.screen_name(screen)
    b = BACKENDS[t["kind"]]
    now = b.status(t) or {}
    rows = [r for r in _audit_rows() if r.get("target") == t["id"] and r.get("action") == "play" and r.get("ok")]
    last = (rows[-1].get("item") if rows else None) or {}
    if not last.get("id"):
        raise CastError(f"Nothing that was cast to {t.get('name')} from here to hand back", 4)
    position = now.get("position") or 0
    try:
        item = P.resolve(id_=last["id"], source=last.get("server")) if last.get("server") != "youtube" else \
            P.resolve(url=f"https://www.youtube.com/watch?v={youtube_id(last['id']) or last['id']}")
    except ValueError as e:
        raise CastError(str(e), getattr(e, "code", 4)) from None
    try:
        b.control(t, "stop", None)
    except Exception:                                       # noqa: BLE001
        pass
    item = dict(item, position=position)
    result = P.play(screen, item=item, resume=bool(position))
    audit("handback", t, item, screen=screen, position=round(position))
    return dict(ok=True, target=t["id"], name=t.get("name"), screen=screen, item=P.public_item(item),
                position=round(position), message=result.get("message") or f"Back on the den's {screen}")


def _pick_sub(subs, audio, aid, sid, value, memory=None):
    """The subtitle track for a press: an id, "off" (None) or "on" (the one showing, the one
    remembered, else the best English, else the first)."""
    T = _T()
    if value == "off":
        return None
    if value == "on":
        at = T.find(audio, aid) if aid else None
        t = (T.find(subs, sid) if sid else None) or \
            (T._match(subs, memory.get("subs")) if isinstance((memory or {}).get("subs"), dict) else None) or \
            T.default_subs(subs, dict(at or {}, lang="und")) or (subs[0] if subs else None)
        if t is None:
            raise CastError("This has no subtitles", 4)
        return t
    t = T.find(subs, value)
    if t is None:
        raise CastError("No such subtitle track", 2)
    return t


def tracks(target):
    t = _target(target)
    try:
        return BACKENDS[t["kind"]].tracks(t)
    except CastError:
        raise
    except Exception as e:                                  # noqa: BLE001
        raise CastError(f"{t.get('name')}: {type(e).__name__}", 1) from None


def _set(target, kind, value):
    t = _target(target)
    b = BACKENDS[t["kind"]]
    try:
        out = b.set_track(t, kind, value)
    except Exception as e:
        audit(kind, t, ok=False, error=e, value=value)
        if isinstance(e, CastError):
            raise
        raise CastError(f"{t.get('name')}: {type(e).__name__}", 1) from None
    audit(kind, t, value=value)
    pick = [x for x in out.get("audio" if kind == "audio" else "subs") or [] if x.get("selected")]
    if kind == "audio":
        out["message"] = f"Audio: {pick[0]['label']}" if pick else "Audio changed"
    else:
        out["message"] = f"Subtitles: {pick[0]['label']}" if pick and out.get("sub_on") else "Subtitles off"
    return out


def set_audio(target, value):
    return _set(target, "audio", value)


def set_subs(target, value):
    return _set(target, "subs", value)


def subs_fetch(target, lang="en"):
    """Look for subtitles for what a target plays (cast from here, or a Jellyfin app's item)."""
    T = _T()
    t = _target(target)
    b = BACKENDS[t["kind"]]
    if t["kind"] == "jellyfin":
        a, s = b._session(t)
        if not s.get("NowPlayingItem"):
            raise CastError("Nothing's playing on it", 4)
        item = b._now_item(a, s)
    elif t["kind"] == "cast":
        rec, _audio, _subs, _pos, a = b._now(t)
        item = rec["item"]
    else:
        raise CastError(NO_TRACKS, 2)
    try:
        out = T.fetch_subs(item, lang, a)
    except T.FetchError as e:
        raise CastError(str(e), 4) from None
    audit("subs-fetch", t, item, lang=lang)
    return dict(out, target=t["id"])


def _audit_rows(limit=200):
    try:
        with open(_audit_path()) as f:
            lines = f.readlines()[-limit:]
        return [json.loads(x) for x in lines if x.strip()]
    except (OSError, ValueError):
        return []


# ------------------------------------------------------------------ the command line
def parser():
    p = argparse.ArgumentParser(prog="bromigos media cast",
                                description="Play on Chromecasts, DLNA TVs, AirPlay, Jellyfin's apps and the den")
    sub = p.add_subparsers(dest="verb", required=True)
    t = sub.add_parser("targets", help="every target on the local network, and what it plays")
    t.add_argument("--timeout", type=float, default=4.0, help="seconds to listen (default 4)")
    t.add_argument("--dry-run", action="store_true", help="only list: keep nothing")
    q = sub.add_parser("play", help="play a title, an item or what a den screen shows on a target")
    q.add_argument("--target", required=True, help="its id, or words from its name or room")
    g = q.add_mutually_exclusive_group(required=True)
    g.add_argument("--screen", help="what the den's big, scope or small screen shows, from the same moment")
    g.add_argument("--id", help="a media server item id (with --source)")
    g.add_argument("--title", help="a title, such as \"Cowboy Bebop S01E05\"")
    g.add_argument("--url", help="a YouTube video link")
    q.add_argument("--source", help="the media server's name in homelab.toml")
    q.add_argument("--resume", action="store_true", help="from where you stopped watching")
    c = sub.add_parser("control", help="play, pause, stop, seek, volume or mute a target")
    c.add_argument("--target", required=True)
    c.add_argument("op", choices=OPS)
    c.add_argument("value", nargs="?", help="seconds for seek, 0-100 for volume")
    s = sub.add_parser("status", help="what a target plays")
    s.add_argument("--target", required=True)
    h = sub.add_parser("handback", help="stop a target and go on from that moment on a den screen")
    h.add_argument("--target", required=True)
    h.add_argument("--screen", default="big")
    k = sub.add_parser("tracks", help="what a target plays's audio tracks and subtitles")
    k.add_argument("--target", required=True)
    au = sub.add_parser("audio", help="play another audio track on a target (an id from tracks)")
    au.add_argument("--target", required=True)
    au.add_argument("track")
    su = sub.add_parser("subs", help="subtitles on a target: a track's id, on or off")
    su.add_argument("--target", required=True)
    su.add_argument("track")
    sf = sub.add_parser("subs-fetch", help="look for subtitles for what a target plays")
    sf.add_argument("--target", required=True)
    sf.add_argument("--lang", default="en")
    for x in (t, q, c, s, h, k, au, su, sf):
        x.add_argument("--json", action="store_true")
    return p


def _print(result, js):
    if js:
        print(json.dumps(result, ensure_ascii=False))
        return
    if "targets" in result:
        for r in result["targets"]:
            now = r.get("playing") or {}
            what = f"  {now.get('state')}: {now.get('title')}" if now.get("title") else ""
            print(f"{r['id']:<44} {r['name']}" + (f" ({r['model']})" if r.get("model") else "") + what)
        for kind, p in result["protocols"].items():
            if not p["available"] or p.get("error"):
                print(f"{kind}: {p.get('why') or p.get('error')}")
        return
    if "audio" in result and "subs" in result and "message" not in result:
        if not result.get("can"):
            print(result.get("why") or NO_TRACKS)
            return
        for kind, rows in (("audio", result["audio"]), ("subs", result["subs"])):
            for t in rows:
                print(("* " if t["selected"] else "  ") + f"{kind:<5} {t['id']:<6} {t['label']}"
                      + (" (file)" if t.get("external") else ""))
        print("subtitles " + ("on" if result.get("sub_on") else "off"))
        return
    if "playing" in result and "message" not in result:
        now = result["playing"]
        print(f"{result.get('name')}: " + (f"{now['state']} {now.get('title') or ''}".strip() if now else "nothing"))
        return
    print(result.get("message") or "ok")


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv[:1] == ["_airplay-keep"]:
        _airplay_keep(argv[1])
        return 0
    js = "--json" in argv
    try:
        try:
            if js:
                import contextlib
                import io
                with contextlib.redirect_stderr(io.StringIO()) as err:
                    try:
                        a = parser().parse_args(argv)
                    except SystemExit as e:
                        if e.code:
                            why = (err.getvalue().strip().splitlines() or ["Invalid arguments"])[-1]
                            raise CastError(why.split(": error: ", 1)[-1], 2) from None
                        raise
            else:
                a = parser().parse_args(argv)
        except SystemExit as e:
            return e.code
        if a.verb == "targets":
            result = targets(a.timeout, a.dry_run)
        elif a.verb == "play":
            result = play(a.target, a.screen, a.title, a.id, a.source, a.url, a.resume)
        elif a.verb == "control":
            result = control(a.target, a.op, a.value)
        elif a.verb == "status":
            result = status(a.target)
        elif a.verb == "tracks":
            result = tracks(a.target)
        elif a.verb == "audio":
            result = set_audio(a.target, a.track)
        elif a.verb == "subs":
            result = set_subs(a.target, a.track)
        elif a.verb == "subs-fetch":
            result = subs_fetch(a.target, a.lang)
        else:
            result = handback(a.target, a.screen)
        _print(result, js)
        return 0
    except (CastError, ValueError, OSError) as e:
        code = getattr(e, "code", 1) if isinstance(getattr(e, "code", 1), int) else 1
        if js:
            print(json.dumps(dict(ok=False, error=str(e), code=code)))
        else:
            print(str(e), file=sys.stderr)
        return code


if __name__ == "__main__":
    sys.exit(main())
