"""A private mpv controller and IPC bridge, only for the den's full-screen player."""
import collections
import json
import os
import queue
import shutil
import socket
import subprocess
import tempfile
import threading
import time

from .tvlink import redact

# A server's file opens in a second or two. Past this, the direct stream isn't coming (a server
# that answers a file's headers but never its bytes), and full screen plays a transcode instead.
DIRECT_OPEN_TIMEOUT = 8.0
FALLBACK_QUALITY = "1080p"
LOG_LINES = 40                          # mpv's warnings and errors logged per file, at most


def is_direct(stream):
    """A server's file as it is (not a transcode, a bump, YouTube or a local file)."""
    return bool(stream and stream.get("adapter") and stream.get("quality") == "direct")


class Session:
    def __init__(self, tv, screen, stream, extra=None):
        self.tv, self.screen = tv, screen
        self.folder = tempfile.mkdtemp(prefix="bromigos-tv-full-", dir=os.environ.get("XDG_RUNTIME_DIR") or None)
        self.sock_path = os.path.join(self.folder, "mpv.sock")
        self.palette_path = os.path.join(self.folder, "palette.json")
        self.conf_path = os.path.join(self.folder, "stream.conf")
        self.stream = stream
        self.messages = queue.Queue()
        self.connection = None
        self.stopped = threading.Event()
        self.version = None
        self.volume = tv.screens[screen]["volume"]
        self.muted = False
        self.bump = None                    # the bump playing between two items, if any
        self.track_sel = tv.full_tracks(screen) if hasattr(tv, "full_tracks") else {}
        self.track_list = []                # mpv's, observed
        self.subs_added = set()             # subtitle addresses added to this file
        self.quality = None                 # the server quality asked for (None: [tv] fullscreen_quality)
        self.loaded = False                 # the file playing opened (a file-loaded, or a time)
        self.switching = False              # a loadfile sent, its start-file not seen yet
        self.opened_at = time.monotonic()
        self.errors = collections.deque(maxlen=8)   # mpv's last errors, redacted
        self.logged = 0
        self.refresh_palette()
        with open(self.conf_path, "w") as f:
            os.chmod(self.conf_path, 0o600)
            for k, v in (stream.get("headers") or {}).items():
                val = f"{k}: {v}"
                f.write(f"http-header-fields-append=%{len(val.encode())}%{val}\n")
            ca = tv._tls_ca()
            if ca:
                f.write(f"tls-ca-file={ca}\ntls-verify=yes\n")
        script = os.path.join(os.path.dirname(__file__), "tvosc.lua")
        opts = f"bromigos-tv-screen={screen},bromigos-tv-palette={self.palette_path}"
        args = ["mpv", "--no-config", "--load-scripts=no", "--osc=no", "--idle=yes", "--fs",
                "--force-window=immediate", "--volume-max=100", f"--volume={self.volume}",
                "--hwdec=auto", "--hwdec-codecs=all", "--audio-client-name=bromigOS den TV",
                "--msg-level=all=warn",          # its warnings and errors, to live.log (never its addresses)
                f"--title={stream['title']} · bromigOS den TV", f"--force-media-title={stream['title']}",
                f"--include={self.conf_path}", f"--input-ipc-server={self.sock_path}",
                f"--script={script}", f"--script-opts={opts}"]
        if stream.get("ytdl_format"): args.append(f"--ytdl-format={stream['ytdl_format']}")
        if getattr(tv, "held", None) and tv.held(screen): args.append("--pause=yes")    # the remote's pause holds here too
        if stream.get("start") is not None: args.append(f"--start={stream['start'] + (0.0 if screen in tv.overrides else .6):.2f}")
        args.extend(extra or [])
        args.append(stream["url"])
        try:
            # mpv writes its messages to stdout when that isn't a terminal.
            self.proc = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                         start_new_session=True, text=True, errors="replace")
        except OSError:
            shutil.rmtree(self.folder, ignore_errors=True)
            raise
        self.reader = threading.Thread(target=self._read_errors, daemon=True, name="den-tv-full-log")
        self.reader.start()
        self.thread = threading.Thread(target=self._loop, daemon=True, name="den-tv-full")
        self.thread.start()

    def log(self, text):
        log = getattr(self.tv, "log", None)
        if log:
            log(text)

    def _read_errors(self):
        """mpv's warnings and errors, with every address and key taken out: to live.log, and
        the last ones kept to say on the player why it isn't playing."""
        try:
            for line in self.proc.stdout:
                text = redact(line.strip())[:200]
                if not text:
                    continue
                self.errors.append(text)
                if self.logged < LOG_LINES:
                    self.logged += 1
                    self.log(f"tv: full screen mpv: {text}")
        except (OSError, ValueError):
            pass
        finally:
            try: self.proc.stdout.close()
            except OSError: pass

    def why(self, fallback=""):
        """The first thing mpv said went wrong with this file (yt-dlp's guess after it is noise)."""
        if not self.errors:
            self.stopped.wait(.3)                           # its line may be a moment behind the event
        said = [e for e in self.errors if not e.startswith("[ytdl_hook]")] or list(self.errors)
        return said[0] if said else fallback

    def _loading(self):
        """A new file is on its way: the last one's end-file isn't this one's."""
        self.loaded = False
        self.switching = True
        self.opened_at = time.monotonic()
        self.errors.clear()
        self.logged = 0

    def _fall_back(self, why, mpv_said=True):
        """The server's file didn't play: the same moment as a transcode, for the rest of the session."""
        reason = self.why(why) if mpv_said else why
        self.log(f"tv: full screen: the direct stream of {self.stream.get('title')} didn't play ({reason}); "
                 f"a {FALLBACK_QUALITY} transcode instead")
        self.quality = FALLBACK_QUALITY
        self._retune()
        self.send("show-text", f"Direct play failed: {reason}\nPlaying a {FALLBACK_QUALITY} transcode", 6000)

    def _failed(self, why):
        """Nothing more to try: say why on the player, not a black screen at 00:00."""
        reason = self.why(why)
        self.log(f"tv: full screen: can't play {self.stream.get('title')}: {reason}")
        self.send("show-text", f"Can't play this: {reason}", 30000)

    def _watch(self):
        if self.loaded or self.switching or self.bump is not None or self.quality is not None:
            return
        if is_direct(self.stream) and time.monotonic() - self.opened_at > DIRECT_OPEN_TIMEOUT:
            self._fall_back(f"nothing from the server in {DIRECT_OPEN_TIMEOUT:.0f} s", mpv_said=False)

    def refresh_palette(self):
        from . import glkit
        version = glkit.T.version(0.0)
        if version == self.version: return
        self.version = version
        colors = {k: "".join(f"{round(v * 255):02X}" for v in glkit.col(k)[:3])
                  for k in ("phosphor", "panel", "soft", "dim")}
        colors["reduced"] = self.tv.motion != "full"
        temp = self.palette_path + ".new"
        with open(temp, "w") as f:
            json.dump(colors, f)
        os.replace(temp, self.palette_path)

    def send(self, *command):
        self.messages.put(list(command))

    def sound(self, volume, on):
        self.send("set_property", "mute", not on)
        self.send("set_property", "volume", volume)

    def retune(self):
        self.messages.put("retune")

    def tracks(self, sel):
        """The den's choice of audio track and subtitles (live/live/tvtracks.py full_tracks)."""
        self.track_sel = dict(sel or {})
        self.messages.put("tracks")

    def _apply_tracks(self):
        sel, tl = self.track_sel, self.track_list
        if not sel or not tl:
            return

        def by(kind, ff=None, mpv=None):
            for t in tl:
                if t.get("type") == kind and not t.get("external") and (
                        (ff is not None and t.get("ff-index") == ff) or (mpv is not None and t.get("id") == mpv)):
                    return t
            return None
        a = by("audio", ff=sel.get("audio_index"), mpv=sel.get("mpv_audio"))
        if a and not a.get("selected"):
            self.send("set_property", "aid", a["id"])
        if sel.get("subs_off"):
            self.send("set_property", "sid", "no")
            return
        url = sel.get("sub_url")
        if url:
            hit = next((t for t in tl if t.get("type") == "sub" and t.get("external-filename") == url), None)
            if hit:
                if not hit.get("selected"):
                    self.send("set_property", "sid", hit["id"])
            elif url not in self.subs_added:
                self.subs_added.add(url)
                self.send("sub-add", url, "select", sel.get("sub_label") or "", "")
            return
        sub = by("sub", ff=sel.get("sub_index"), mpv=sel.get("mpv_sub"))
        if sub and not sub.get("selected"):
            self.send("set_property", "sid", sub["id"])

    def _stop_stream(self):
        a = self.stream.get("adapter")
        if a:
            try: a.video_stop(self.stream)
            except Exception: pass

    def _play_bump(self, bump):
        """A bump between two items: its clip from the pack (a local file, silent), its caption
        on mpv's OSD."""
        self.bump = bump
        self._loading()
        self.send("set_property", "force-media-title", bump.caption or "Den TV")
        self.send("loadfile", bump.path, "replace", -1, {"start": "0"})
        if bump.caption:
            self.send("expand-properties", "show-text", bump.caption, int(max(1.0, bump.seconds - 1.5) * 1000))

    def _retune(self):
        self.bump = None
        n, ch = self.tv.channel(self.screen)
        slot = self.tv.slot(ch)
        if self.quality:
            stream = self.tv.stream(ch, slot, full=True, screen=self.screen, quality=self.quality)
        else:
            stream = self.tv.stream(ch, slot, full=True, screen=self.screen)
        if not stream:
            self.send("quit")
            return
        self._stop_stream()
        self.stream = stream
        self.send("set_property", "http-header-fields", [f"{k}: {v}" for k, v in stream.get("headers", {}).items()])
        self.send("set_property", "force-media-title", stream["title"])
        self.send("set_property", "ytdl-format", stream.get("ytdl_format") or "")
        options = {"start": str(stream.get("start") or 0)}
        self._loading()
        self.send("loadfile", stream["url"], "replace", -1, options)

    def _event(self, event):
        if event.get("event") == "start-file":
            self.switching = False
        if event.get("event") == "file-loaded":
            self.subs_added = set()
            self.loaded = not self.switching
        if (event.get("event") == "property-change" and event.get("name") == "time-pos"
                and event.get("data") is not None and not self.switching):
            self.loaded = True
        if event.get("event") == "property-change" and event.get("name") == "track-list":
            self.track_list = event.get("data") or []
            self._apply_tracks()
        if event.get("event") == "property-change":
            if event.get("name") == "time-pos" and self.screen in self.tv.overrides and event.get("data") is not None:
                self.tv.overrides[self.screen]["full_position"] = float(event["data"])

            if event.get("name") == "volume": self.volume = max(0, min(100, round(event.get("data") or 0)))
            if event.get("name") == "mute": self.muted = bool(event.get("data"))
            if event.get("name") in ("volume", "mute"):
                state = self.tv.screens[self.screen]
                if state["volume"] != self.volume or state["sound"] == self.muted:
                    # Updating the shared state also updates the den's OSD, without echoing IPC.
                    self.tv.set_sound(self.screen, on=(not self.muted if event["name"] == "mute" else state["sound"]),
                                      volume=self.volume, from_full=True)
        if event.get("event") == "end-file" and self.switching:
            return                                          # the file it replaces
        if event.get("event") == "end-file" and event.get("reason") == "error":
            why = event.get("file_error") or "it didn't open"
            if is_direct(self.stream) and self.quality is None and self.bump is None:
                self._fall_back(why)
            else:
                self._failed(why)
            return
        if event.get("event") == "end-file" and event.get("reason") == "eof":
            if self.bump is not None:                       # the bump's over: the channel's next item
                self.bump = None
                self.retune()
                return
            if self.screen not in self.tv.overrides:        # a channel's item ended: a bump first, when one's due
                bump = self.tv.full_bump(self.screen)
                if bump is not None:
                    self._play_bump(bump)
                    return
            self.tv.overrides.pop(self.screen, None)
            self.tv.feedback(self.screen, "BACK TO CHANNEL")
            self.retune()

    def _loop(self):
        try:
            deadline = time.monotonic() + 8
            while not os.path.exists(self.sock_path) and self.proc.poll() is None and time.monotonic() < deadline:
                self.stopped.wait(.05)
            if not os.path.exists(self.sock_path): return
            with socket.socket(socket.AF_UNIX) as conn:
                self.connection = conn
                conn.settimeout(.2); conn.connect(self.sock_path)
                for i, name in enumerate(("volume", "mute", "time-pos", "track-list")):
                    self.send("observe_property", i, name)
                pending = b""
                while self.proc.poll() is None and not self.stopped.is_set():
                    self.refresh_palette()
                    self._watch()
                    while not self.messages.empty():
                        cmd = self.messages.get_nowait()
                        if cmd == "retune":
                            self._retune(); continue
                        if cmd == "tracks":
                            self._apply_tracks(); continue
                        conn.sendall(json.dumps(dict(command=cmd)).encode() + b"\n")
                    try:
                        data = conn.recv(65536)
                        if not data: break
                        pending += data
                        while b"\n" in pending:
                            line, pending = pending.split(b"\n", 1)
                            try: self._event(json.loads(line))
                            except (ValueError, TypeError): pass
                    except socket.timeout: pass
        except (OSError, ValueError, KeyError):
            pass
        finally:
            self.connection = None
            # Restore the last observed volume/mute even when Escape closes mpv directly.
            state = self.tv.screens[self.screen]
            self.tv.set_sound(self.screen, on=state["sound"], volume=state["volume"], from_full=True)
            override = self.tv.overrides.get(self.screen)
            if override and "full_position" in override:
                override["offset"] = override.pop("full_position")
                self.tv._unload(self.tv.decks[self.screen])
            self._stop_stream()
            shutil.rmtree(self.folder, ignore_errors=True)

    def close(self):
        self.send("quit")
        if self.proc.poll() is None:
            try: self.proc.terminate()
            except OSError: pass
