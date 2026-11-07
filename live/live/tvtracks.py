"""Audio tracks and subtitles on the den's screens (lib/bromigos_tracks.py has the shapes,
the defaults and the memory per series).

Where a screen's tracks come from:
  Jellyfin    the item's MediaStreams, read once per item off the drawing thread (and the
              next item's ahead): every audio track and subtitle, files beside the video
              included. Ids "j<index>". On a direct stream mpv has them all (matched by
              their index in the file); a transcode carries one audio track, so another is
              a new stream with that track (AudioStreamIndex), and subtitles come as
              WebVTT from the server (picture subtitles, PGS or DVD, are burnt in).
  otherwise   mpv's own track list once the file is open (Plex, files, YouTube). Ids "m<id>".

The choice is made once per item, when its tracks are known: the one remembered for the
series, else the defaults (English audio; English subtitles when the audio isn't English;
English signs and songs when it is). A choice from a remote is remembered for the series.

Sound off decodes no audio at all (mpv's aid=no): the chosen track is kept and comes back
with the sound.
"""
import threading

from . import LIB  # noqa: F401  (the shared libs on sys.path)
import bromigos_tracks as T  # noqa: E402
import bromigos_tv as TVL  # noqa: E402


class Tracks:
    def init_tracks(self):
        self.track_want = {}               # screen -> {item, audio, subs, decided, gen, reloads, added}
        self.item_streams = {}             # item id -> (audio, subs) from the server, or None while it's read
        self.track_memory = T.Memory()

    # ---- where an item's tracks come from
    def _jellyfin_of(self, ch, item):
        if not item or item.get("server") in (None, "youtube", "files") or item.get("download_source"):
            return None
        a = TVL.server_of(ch) if ch else None
        return a if a is not None and hasattr(a, "video_streams") else None

    def _read_streams(self, a, item):
        iid = str(item.get("id"))
        if iid in self.item_streams:
            return
        self.item_streams[iid] = None

        def run():
            try:
                self.item_streams[iid] = T.from_jellyfin(a.video_streams(item))
            except Exception as e:                          # noqa: BLE001
                self.log(f"tv: no track list for {TVL.label(item)}: {type(e).__name__}")
                self.item_streams[iid] = ([], [])
            try:
                T.fetch_available(a)                        # asked here, off the main thread, for the sheet
            except Exception:                               # noqa: BLE001
                pass
            if len(self.item_streams) > 64:
                for k in list(self.item_streams)[:16]:
                    self.item_streams.pop(k, None)
            self._changed()
        threading.Thread(target=run, daemon=True, name="den-tv-tracks").start()

    def _list(self, screen):
        """(audio, subs, source) for what's on a screen now, or None while unknown."""
        n, ch = self.channel(screen)
        slot = self.slot(ch)
        item = slot.item if slot else None
        if not item:
            return None
        if self._jellyfin_of(ch, item) is not None:
            got = self.item_streams.get(str(item.get("id")))
            return None if got is None else (got[0], got[1], "jellyfin")
        d = self.decks[self.follows.get(screen, screen)]
        if d.player is None or not getattr(d.player, "started", False) or not hasattr(d.player, "track_list"):
            return None
        audio, subs = T.from_mpv(d.player.track_list())
        added = (self.track_want.get(screen) or {}).get("added") or {}
        subs = [t for t in subs if t.get("mpv") not in added.values()]     # a file we added shows once, as itself
        return audio, subs, "mpv"

    # ---- the tick (0.5 s): choose once per item, then keep mpv on the choice
    def tracks_tick(self):
        for s in TVL.SCREENS:
            n, ch = self.channel(s)
            if ch["kind"] == "own":
                self.track_want.pop(s, None)
                continue
            slot = self.slot(ch)
            item = slot.item if slot else None
            if not item:
                continue
            a = self._jellyfin_of(ch, item)
            if a is not None:
                self._read_streams(a, item)
                if slot.next and self._jellyfin_of(ch, slot.next) is not None:
                    self._read_streams(a, slot.next)
            iid = str(item.get("id"))
            w = self.track_want.get(s)
            if not w or w["item"] != iid:
                w = self.track_want[s] = dict(item=iid, audio=None, subs=None, decided=False, gen=-1, reloads=0,
                                              added={})
            if not w["decided"]:
                got = self._list(s)
                if got is None:
                    continue
                audio, subs, _src = got
                at, st = T.choose(audio, subs, self.track_memory.get(item))
                w.update(audio=at["id"] if at else None, subs=st["id"] if st else None, decided=True)
                if at or st:
                    self.log(f"tv: {s}: {at['label'] if at else 'default audio'}"
                             + (f", subtitles {st['label']}" if st else ""))
            self._apply_tracks(s)

    def _apply_tracks(self, screen, force=False):
        """Put the screen's player on its chosen tracks (once per load)."""
        w = self.track_want.get(screen)
        d = self.decks[screen]
        if (not w or not w["decided"] or d.player is None or not d.loaded or not getattr(d.player, "started", False)
                or not hasattr(d.player, "choose_audio")):
            return
        if w["gen"] == getattr(d.player, "gen", 0) and not force:
            return
        got = self._list(screen)
        if got is None:
            return
        audio, subs, src = got
        p = d.player
        stream = d.stream or {}
        transcode = stream.get("quality") not in (None, "direct")
        at, st = T.find(audio, w["audio"]) if w["audio"] else None, T.find(subs, w["subs"]) if w["subs"] else None
        if src == "jellyfin" and transcode:
            want_audio = at["index"] if at else None
            want_burn = st["index"] if st and not st.get("text") else None
            if ((want_audio is not None and stream.get("audio_index") != want_audio
                 or stream.get("burn_index") != want_burn) and w["reloads"] < 3):
                w["reloads"] += 1
                w["gen"] = -1
                self._unload(d)                             # a new stream with that track (and its picture subtitles)
                self.wake.set()
                return
            p.choose_audio("auto")
            if st and st.get("text"):
                self._add_sub(screen, st)
            else:
                p.choose_sub(None)
        elif src == "jellyfin":
            mpv_audio, mpv_subs = T.from_mpv(p.track_list())
            if at:
                hit = next((t for t in mpv_audio if t.get("ff") == at["index"] and not t.get("external")), None)
                p.choose_audio(hit["mpv"] if hit else "auto")
            if st is None:
                p.choose_sub(None)
            elif st.get("external"):
                self._add_sub(screen, st)
            else:
                hit = next((t for t in mpv_subs if t.get("ff") == st["index"] and not t.get("external")), None)
                if hit:
                    p.choose_sub(hit["mpv"])
                elif st.get("text"):
                    self._add_sub(screen, st)
        else:
            if at:
                p.choose_audio(at["mpv"])
            p.choose_sub(st["mpv"] if st else None)
        w["gen"] = getattr(p, "gen", 0)
        self._apply_sound()
        fs = getattr(self, "full_session", None)
        if fs and fs.screen == screen and hasattr(fs, "tracks"):
            fs.tracks(self.full_tracks(screen))

    def _add_sub(self, screen, st):
        """A subtitle from the server (a file beside the video, or a transcode's), as WebVTT."""
        w = self.track_want[screen]
        d = self.decks[screen]
        if w.get("added_gen") != getattr(d.player, "gen", 0):    # a new load has none of the last one's
            w["added"], w["added_gen"] = {}, getattr(d.player, "gen", 0)
        if st["id"] in w["added"]:
            mid = w["added"][st["id"]]
            if mid is not None:
                d.player.choose_sub(mid)
            return
        n, ch = self.channel(screen)
        a = self._jellyfin_of(ch, self.slot(ch).item if self.slot(ch) else None)
        if a is None or not hasattr(a, "video_subtitle_url"):
            return
        item = self.slot(ch).item
        url, _headers = a.video_subtitle_url(item, st["index"])     # mpv already sends the stream's headers
        w["added"][st["id"]] = None
        gen = d.player.gen

        def done(mpv_id):
            if d.player is not None and d.player.gen == gen:
                w["added"][st["id"]] = mpv_id
        d.player.add_sub(url, st.get("label") or "", st.get("lang") or "", done)

    def full_tracks(self, screen):
        """What the full-screen player should pick: {audio_index, sub_index, sub_url, mpv_audio, mpv_sub}."""
        w = self.track_want.get(screen) or {}
        got = self._list(screen)
        if not got or not w.get("decided"):
            return {}
        audio, subs, src = got
        at = T.find(audio, w["audio"]) if w.get("audio") else None
        st = T.find(subs, w["subs"]) if w.get("subs") else None
        out = {"subs_off": st is None}
        if src == "jellyfin":
            out["audio_index"] = at["index"] if at else None
            if st:
                out["sub_index"] = st["index"]
                if st.get("external"):
                    n, ch = self.channel(screen)
                    a = self._jellyfin_of(ch, self.slot(ch).item)
                    if a is not None:
                        out["sub_url"] = a.video_subtitle_url(self.slot(ch).item, st["index"])[0]
                        out["sub_label"] = st.get("label")
        else:
            out["mpv_audio"] = at["mpv"] if at else None
            out["mpv_sub"] = st["mpv"] if st else None
        return out

    def track_stream_args(self, screen, item):
        """For a server's transcode: the audio track (and picture subtitles) to carry."""
        w = self.track_want.get(screen) or {}
        if not w.get("decided") or w.get("item") != str(item.get("id")):
            got = self.item_streams.get(str(item.get("id")))
            if not got:
                return {}
            at, st = T.choose(got[0], got[1], self.track_memory.get(item))
        else:
            got = self.item_streams.get(str(item.get("id"))) or ([], [])
            at = T.find(got[0], w["audio"]) if w.get("audio") else None
            st = T.find(got[1], w["subs"]) if w.get("subs") else None
        out = {}
        if at and "index" in at:
            out["audio_index"] = at["index"]
        if st and "index" in st and not st.get("text"):
            out["burn_index"] = st["index"]
        return out

    # ---- the commands (bromigos-live tv tracks|audio|subs)
    def _item_of(self, screen):
        n, ch = self.channel(screen)
        slot = self.slot(ch)
        return ch, slot.item if slot else None

    def tracks_json(self, screen, message=None):
        ch, item = self._item_of(screen)
        if ch["kind"] == "own" or not item:
            return dict(ok=True, screen=screen, can=False, why="Nothing's playing on this screen", audio=[], subs=[],
                        sub_on=False, fetch=False)
        got = self._list(screen)
        w = self.track_want.get(screen) or {}
        if got is None:
            return dict(ok=True, screen=screen, can=False, why="Still opening: the tracks show in a moment",
                        audio=[], subs=[], sub_on=False, fetch=False)
        audio, subs, src = got
        a = self._jellyfin_of(ch, item)
        fetch = bool(a is not None and T.fetch_cached(a))   # never the network here: the main thread
        out = T.public(audio, subs, w.get("audio"), w.get("subs"), fetch=fetch, item=item, screen=screen)
        if message:
            out["message"] = message
        return out

    def tracks_summary(self, screen):
        w = self.track_want.get(screen)
        if not w or not w.get("decided"):
            return None
        got = self._list(screen)
        if not got:
            return None
        return T.summary(got[0], got[1], w.get("audio"), w.get("subs"))

    def _need(self, screen):
        ch, item = self._item_of(screen)
        w = self.track_want.get(screen)
        got = self._list(screen)
        if ch["kind"] == "own" or not item or not w or got is None:
            return None
        return item, w, got

    def set_audio(self, screen, tid):
        need = self._need(screen)
        if not need:
            return dict(ok=False, error="No tracks to pick from on this screen yet")
        item, w, (audio, subs, _src) = need
        t = T.find(audio, tid)
        if t is None:
            return dict(ok=False, error="No such audio track")
        w.update(audio=t["id"], decided=True, gen=-1, reloads=0)
        self.track_memory.put(item, audio=t, keep_subs=True)
        self._apply_tracks(screen, force=True)
        self.feedback(screen, t["label"].upper()[:28])
        return self.tracks_json(screen, f"Audio: {t['label']}")

    def set_subs(self, screen, value):
        need = self._need(screen)
        if not need:
            return dict(ok=False, error="No tracks to pick from on this screen yet")
        item, w, (audio, subs, _src) = need
        if value == "off":
            t = None
        elif value == "on":
            at = T.find(audio, w.get("audio")) if w.get("audio") else None
            mem = self.track_memory.get(item) or {}
            t = (T.find(subs, w.get("subs")) if w.get("subs") else None) or \
                (T._match(subs, mem.get("subs")) if isinstance(mem.get("subs"), dict) else None) or \
                T.default_subs(subs, dict(at or {}, lang="und") if at else {"lang": "und"}) or (subs[0] if subs else None)
            if t is None:
                return dict(ok=False, error="This has no subtitles")
        else:
            t = T.find(subs, value)
            if t is None:
                return dict(ok=False, error="No such subtitle track")
        w.update(subs=t["id"] if t else None, decided=True, gen=-1)
        self.track_memory.put(item, subs=t, keep_audio=True)
        self._apply_tracks(screen, force=True)
        self.feedback(screen, ("CC " + t["label"]).upper()[:28] if t else "CC OFF")
        return self.tracks_json(screen, f"Subtitles: {t['label']}" if t else "Subtitles off")

    def tracks_refresh(self, screen):
        """Read the item's tracks again (a subtitle was just fetched)."""
        ch, item = self._item_of(screen)
        if item:
            self.item_streams.pop(str(item.get("id")), None)
            w = self.track_want.get(screen)
            if w:
                w["gen"] = -1
        return dict(ok=True, screen=screen, message="tracks read again")

    def tracks_command(self, verb, screen, rest):
        import json
        s = self._pick(screen)
        if verb == "tracks":
            out = self.tracks_json(s)
        elif verb == "audio":
            out = self.set_audio(s, (rest or [""])[0]) if rest else dict(ok=False, error="audio TRACK-ID")
        elif verb == "subs":
            out = self.set_subs(s, (rest or ["on"])[0])
        else:
            out = self.tracks_refresh(s)
        return json.dumps(out)
