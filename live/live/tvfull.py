"""A private mpv controller and IPC bridge, only for the den's full-screen player."""
import json
import os
import queue
import shutil
import socket
import subprocess
import tempfile
import threading
import time


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
                f"--title={stream['title']} · bromigOS den TV", f"--force-media-title={stream['title']}",
                f"--include={self.conf_path}", f"--input-ipc-server={self.sock_path}",
                f"--script={script}", f"--script-opts={opts}"]
        if stream.get("ytdl_format"): args.append(f"--ytdl-format={stream['ytdl_format']}")
        if stream.get("start") is not None: args.append(f"--start={stream['start'] + (0.0 if screen in tv.overrides else .6):.2f}")
        args.extend(extra or [])
        args.append(stream["url"])
        try:
            self.proc = subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                         start_new_session=True)
        except OSError:
            shutil.rmtree(self.folder, ignore_errors=True)
            raise
        self.thread = threading.Thread(target=self._loop, daemon=True, name="den-tv-full")
        self.thread.start()

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

    def _stop_stream(self):
        a = self.stream.get("adapter")
        if a:
            try: a.video_stop(self.stream)
            except Exception: pass

    def _retune(self):
        n, ch = self.tv.channel(self.screen)
        slot = self.tv.slot(ch)
        stream = self.tv.stream(ch, slot, full=True)
        if not stream:
            self.send("quit")
            return
        self._stop_stream()
        self.stream = stream
        self.send("set_property", "http-header-fields", [f"{k}: {v}" for k, v in stream.get("headers", {}).items()])
        self.send("set_property", "force-media-title", stream["title"])
        self.send("set_property", "ytdl-format", stream.get("ytdl_format") or "")
        options = {"start": str(stream.get("start") or 0)}
        self.send("loadfile", stream["url"], "replace", -1, options)

    def _event(self, event):
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
        if event.get("event") == "end-file" and event.get("reason") == "eof":
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
                for i, name in enumerate(("volume", "mute", "time-pos")):
                    self.send("observe_property", i, name)
                pending = b""
                while self.proc.poll() is None and not self.stopped.is_set():
                    self.refresh_palette()
                    while not self.messages.empty():
                        cmd = self.messages.get_nowait()
                        if cmd == "retune":
                            self._retune(); continue
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
