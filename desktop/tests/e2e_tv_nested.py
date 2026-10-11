#!/usr/bin/env python3
"""End to end: the den TV in a nested Hyprland nobody sees, with a PipeWire nobody hears.

The nested Hyprland is e2e_keys_nested.py's (kwin_wayland --virtual hosting it, a runtime
directory, HOME and D-Bus of its own), at 2560x1440. This checkout's live layer runs in it
with the den, and a fake Jellyfin on this machine serves a generated test clip (ffmpeg's
test pattern: never real media) as a library of three episodes. A PipeWire of its own
(sandbox_audio.py) takes the sound. A virtual pointer (vptr.py, with a wheel here) and
keyboard (vkbd.py) drive it. It checks:

  - the channel plays on the big monitor at the schedule's position (the wall clock);
  - the background takes the pointer over the den's screens only: the hover hint shows,
    and goes when the pointer leaves;
  - the wheel changes channel (with the tuning OSD), and over the hint's volume bar the
    volume; a turn up from silent turns the sound on;
  - the hint's speaker button: the TV's sound as a PipeWire stream called "bromigOS den TV",
    at the screen's volume; bromigOS's mute silences it, VECTOR speaking ducks it, the
    screensaver mutes it and closing it gives the sound back;
  - a click opens mpv full screen with sound on the same stream at the same moment
    (--start), carrying the volume; closing it brings the TV back at the live position,
    with its sound as it was;
  - a window over the TV pauses decoding; with it gone the TV catches up to the clock;
  - `bromigos-live tv` next, prev, set, sound and volume (capped at 100), and every
    screen's channel, sound and volume remembered across a restart;
  - every screen playing its own channel at once (three players), the sound moving from
    screen to screen (one PipeWire stream, the others silent), and a screen with its sound
    on playing on behind a window while a muted one pauses;
  - the channel guide (the standalone Den TV app, driven by den_tv_guide_driver.py): a channel
    added, dragged, moved to another screen, tuned, removed and put back, and the live
    layer following each without a restart;
  - the live layer's CPU and GPU with three screens playing, one, and none (printed).

Shift+wheel and the volume keys can't be read over the TV: the background never has the
keyboard, so Hyprland tells it neither Shift nor a key. Rebinding Hyprland's keys on hover
could leave them rebound if the live layer died mid-hover (live/README.md, "The den TV").

Not part of `unittest discover` (it needs kwin_wayland, Hyprland, PipeWire, mpv,
python-mpv and a GPU):

    python3 desktop/tests/e2e_tv_nested.py [--keep] [--shots DIR] [--measure SECONDS] [--guide-only]
"""
import json
import os
import shutil
import signal
import socket
import struct
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from e2e_keys_nested import REPO, Nest, Run, wait_for  # noqa: E402
import sandbox_audio  # noqa: E402
import vptr  # noqa: E402

CLIP_SECONDS = 120
EPISODES = ("ep0", "ep1", "ep2")


class Wheel(vptr.VirtualPointer):
    """The virtual pointer with a mouse wheel (zwlr_virtual_pointer_v1 axis, axis_source,
    axis_discrete)."""

    def scroll(self, notches):
        step = 1 if notches > 0 else -1
        for _ in range(abs(int(notches))):
            self._send(self.ptr, 5, struct.pack("<I", 0))                              # axis_source: wheel
            self._send(self.ptr, 7, struct.pack("<IIii", self._ms(), 0, 15 * 256 * step, step))   # axis_discrete
            self._frame()
            time.sleep(0.15)


# ------------------------------------------------------------------ a fake Jellyfin
def fake_jellyfin(clip, poster):
    T = 10_000_000
    eps = [{"Name": f"Test Pattern {i + 1}", "Id": e, "Type": "Episode", "SeriesName": "Test Card", "SeriesId": "s1",
            "ParentIndexNumber": 1, "IndexNumber": i + 1, "RunTimeTicks": CLIP_SECONDS * T,
            "ImageTags": {"Primary": "p"}, "MediaSources": [{"Id": e, "Bitrate": 800000}]}
           for i, e in enumerate(EPISODES)]
    answers = {"/Users": [{"Name": "admin", "Id": "u1", "Policy": {"IsAdministrator": True}}],
               "/Users/u1/Views": {"Items": [{"Name": "Shows", "Id": "lib1", "CollectionType": "tvshows"}]},
               "/System/Info/Public": {"ProductName": "Jellyfin Server", "Version": "10.11.0"}}
    data = open(clip, "rb").read()
    art = open(poster, "rb").read()
    seen = []

    class H(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, *a):
            pass

        def _send(self, code, body, ctype="application/json", extra=None):
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            for k, v in (extra or {}).items():
                self.send_header(k, v)
            self.end_headers()
            if self.command != "HEAD":
                try:
                    self.wfile.write(body)
                except OSError:
                    pass

        def do_HEAD(self):
            self.do_GET()

        def do_GET(self):
            path = self.path.split("?")[0]
            seen.append((self.path, self.headers.get("Authorization")))
            if self.headers.get("Authorization") != 'MediaBrowser Token="test-key"' and not path.endswith("/Primary"):
                return self._send(401, b"{}")
            if path.startswith("/Videos/") and path.endswith("/stream"):
                rng = self.headers.get("Range")
                if rng and rng.startswith("bytes="):
                    a, _, b = rng[6:].partition("-")
                    a = int(a or 0)
                    b = int(b) if b else len(data) - 1
                    return self._send(206, data[a:b + 1], "video/mp4",
                                      {"Content-Range": f"bytes {a}-{b}/{len(data)}", "Accept-Ranges": "bytes"})
                return self._send(200, data, "video/mp4", {"Accept-Ranges": "bytes"})
            if path.endswith("/Images/Primary"):
                return self._send(200, art, "image/png")
            if path == "/Users/u1/Items":
                q = self.path.split("?", 1)[1] if "?" in self.path else ""
                if "ParentId=lib1" in q:
                    return self._send(200, json.dumps({"Items": eps}).encode())
                return self._send(200, b'{"Items": []}')
            if path in answers:
                return self._send(200, json.dumps(answers[path]).encode())
            return self._send(404, b"{}")
    srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, seen


# ------------------------------------------------------------------ the nest
class TVNest(Nest):
    SIZE = (2560, 1440)

    def __init__(self, keep=False, shots=None):
        super().__init__(keep, shots)
        with open(self.lua) as f:
            conf = f.read()
        conf = conf.replace("bromigos = {\n", 'bromigos = {\n    monitors = { { output = "WAYLAND-1", '
                            'mode = "2560x1440@60", position = "0x0", scale = 1 } },\n', 1)
        with open(self.lua, "w") as f:
            f.write(conf)
        media = os.path.join(self.tmp, "media")
        os.makedirs(media)
        self.clip = os.path.join(media, "test-pattern.mp4")
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc2=size=640x360:rate=24",
                        "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000", "-t", str(CLIP_SECONDS),
                        "-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p", "-g", "48", "-c:a", "aac",
                        self.clip], check=True)
        self.poster = os.path.join(media, "poster.png")
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc=size=200x300", "-frames:v", "1",
                        self.poster], check=True)
        self.jf, self.jf_seen = fake_jellyfin(self.clip, self.poster)
        self.media2 = os.path.join(self.tmp, "media2")
        self.media3 = os.path.join(self.tmp, "media3")
        for d, src in ((self.media2, "smptebars=size=640x360:rate=24"), (self.media3, "mandelbrot=size=640x360:rate=24")):
            os.makedirs(d)
            subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", src, "-f", "lavfi", "-i",
                            "sine=frequency=660:sample_rate=48000", "-t", str(CLIP_SECONDS), "-c:v", "libx264",
                            "-preset", "veryfast", "-pix_fmt", "yuv420p", "-c:a", "aac", os.path.join(d, "clip.mp4")],
                           check=True)
        cfg = os.path.join(self.home, ".config")
        os.makedirs(os.path.join(cfg, "bromigos-live"))
        os.makedirs(os.path.join(cfg, "bromigos"), exist_ok=True)
        key = os.path.join(self.home, ".local", "share", "bromigos", "jellyfin-key")
        os.makedirs(os.path.dirname(key))
        with open(key, "w") as f:
            f.write("test-key\n")
        os.chmod(key, 0o600)
        with open(os.path.join(cfg, "bromigos", "homelab.toml"), "w") as f:
            f.write(f'[[source]]\ntype = "jellyfin"\nendpoint = "http://127.0.0.1:{self.jf.server_port}"\n'
                    f'auth_ref = "@file:{key}"\n')
        den = os.path.join(REPO, "desktop", "wallpaper", "bromigos-den-empty-2560x1440.jpg")
        with open(os.path.join(cfg, "bromigos-live", "config.toml"), "w") as f:
            f.write(f'''[general]
monitor = "WAYLAND-1"

[background]
underlay = "{den}"

[events]
intercept_on_login = false
intercept_on_unlock = false
lock_emblem = false

[codec]
on_lab_alert = false

[[tv.channel]]
name = "Test Card"
source = "jellyfin"
library = "Shows"
order = "in order"
screens = ["big", "wave"]

[[tv.channel]]
name = "Second"
files = "{media}"
screens = ["big"]

[[tv.channel]]
name = "Scope Clips"
files = "{self.media2}"
screens = ["wave"]

[[tv.channel]]
name = "Small Clips"
files = "{self.media3}"
screens = ["emblem"]
''')
        # mpv for full screen: the real one, its arguments written down first
        with open(os.path.join(self.stubs, "mpv"), "w") as f:
            f.write('#!/bin/sh\nprintf "%s\\n" "$@" > "$HOME/mpv-args.txt"\nexec /usr/bin/mpv --ao=pipewire "$@"\n')
        os.chmod(os.path.join(self.stubs, "mpv"), 0o755)
        with open(os.path.join(self.stubs, "xdg-open"), "w") as f:
            f.write('#!/bin/sh\necho "$@" >> "$HOME/xdg-open.log"\n')
        os.chmod(os.path.join(self.stubs, "xdg-open"), 0o755)
        self.live = None

    def start(self):
        super().start()
        self.audio = sandbox_audio.AudioSandbox(keep=self.keep, run_dir=self.run, home=self.home)
        self.audio.start()
        self.audio.sink("speakers", "Test speakers")
        self.audio.pactl("set-default-sink", "speakers")
        self.ptr = Wheel(os.path.join(self.run, "wayland-1"), *self.SIZE)
        self.start_live()
        # Default keybinds use the source wrapper, but autostart remains a no-op.
        with open(os.path.join(self.stubs, "bromigos-live"), "w") as f:
            f.write('#!/bin/sh\ncase "$1" in start|stop|restart) exit 0;; esac\nexec ' +
                    __import__("shlex").quote(os.path.join(REPO,"live/bin/bromigos-live")) + ' "$@"\n')
        os.chmod(os.path.join(self.stubs, "bromigos-live"), 0o755)

    def live_env(self):
        env = dict(self.env, **{k: v for k, v in self.audio.env.items() if k.startswith(("PIPEWIRE", "PULSE"))})
        env["BROMIGOS_HOMELAB"] = os.path.join(REPO, "homelab")
        env["PYTHONPATH"] = os.pathsep.join(filter(None, [os.path.join(REPO, "lib"), os.environ.get("PYTHONPATH")]))
        env["XDG_SESSION_TYPE"] = "wayland"
        return env

    def start_live(self):
        log = open(os.path.join(self.home, "live.log"), "a")
        self.live = subprocess.Popen([sys.executable, "-m", "live.app"], cwd=os.path.join(REPO, "live"),
                                     env=self.live_env(), stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
        self.procs.append(self.live)
        if not wait_for(lambda: self.ctl_live("ping") == "pong", 30):
            raise RuntimeError("the live layer didn't start (see live.log)")

    def stop_live(self):
        if self.live and self.live.poll() is None:
            self.ctl_live("quit")
            try:
                self.live.wait(10)
            except subprocess.TimeoutExpired:
                os.killpg(self.live.pid, signal.SIGKILL)

    def stop(self):
        for p in (getattr(self, "full", None),):
            if p:
                subprocess.run(["pkill", "-f", "--", self.clip], capture_output=True)
        try:
            self.stop_live()
        except Exception:
            pass
        if getattr(self, "audio", None):
            self.audio.stop()
        if getattr(self, "jf", None):
            self.jf.shutdown()
        super().stop()

    def ctl_live(self, cmd, timeout=5):
        try:
            with socket.socket(socket.AF_UNIX) as s:
                s.settimeout(timeout)
                s.connect(os.path.join(self.run, "bromigos-live.sock"))
                s.sendall(cmd.encode())
                out = b""
                while True:
                    b = s.recv(65536)
                    if not b:
                        break
                    out += b
            return out.decode()
        except OSError:
            return None

    def tv(self, *args):
        return self.ctl_live("tv " + " ".join(args))

    def state(self):
        out = self.tv("state", "--json")
        try:
            return json.loads(out)
        except (TypeError, ValueError):
            return {}

    def streams(self):
        """The sound server's playing streams: [{name, volume %, muted}]."""
        out = subprocess.run(["pactl", "-f", "json", "list", "sink-inputs"], env=self.audio.env, capture_output=True,
                             text=True, timeout=10).stdout
        try:
            doc = json.loads(out or "[]")
        except ValueError:
            return []
        res = []
        for si in doc:
            props = si.get("properties") or {}
            vols = [int(str(v.get("value_percent", "0")).rstrip("%")) for v in (si.get("volume") or {}).values()]
            res.append({"name": props.get("application.name") or props.get("media.name"), "volume": max(vols or [0]),
                        "muted": si.get("mute"), "pid": props.get("application.process.id")})
        return res

    def tv_volume(self):
        """The TV's level as mpv plays it (its own volume, ducking included), with its stream
        in PipeWire; None while it has no stream."""
        if self.tv_stream() is None:
            return None
        return (self.state().get("playing") or {}).get("volume")

    def tv_stream(self, pid=None):
        return next((s for s in self.streams() if s["name"] == "bromigOS den TV"
                     and (pid is None or str(s.get("pid")) == str(pid))), None)

    def proc_cpu(self, pid):
        with open(f"/proc/{pid}/stat") as f:
            fields = f.read().rsplit(")", 1)[1].split()
        ticks = os.sysconf("SC_CLK_TCK")
        threads = 0
        return (int(fields[11]) + int(fields[12])) / ticks, threads


def center(r):
    return (r[0] + r[2] / 2, r[1] + r[3] / 2)


def live_offset(n):
    s = n.state().get("screens", {}).get("big", {})
    return s.get("offset")


def scenarios(n, r, measure=0):
    ptr = n.ptr
    r.check("the live layer runs in the nest, on the den", wait_for(
        lambda: (n.state().get("screens") or {}).get("big", {}).get("of") == 3, 20), n.state())
    st = n.state()
    big = st["screens"]["big"]["rect"]
    wave = st["screens"]["wave"]["rect"]
    emblem = st["screens"]["emblem"]["rect"]
    r.check("every screen with a channel of its own takes the pointer",
            sorted(map(tuple, st["input"])) == sorted([tuple(big), tuple(wave), tuple(emblem)]), st["input"])

    # -- tune in from the command line: the schedule's position
    out = n.tv("set", "2", "big")
    r.check("tv set 2: the big monitor on Test Card", "Test Card" in (out or ""), out)
    r.check("mpv plays it on the TV", wait_for(lambda: (n.state().get("playing") or {}).get("position") is not None, 20),
            n.state())
    time.sleep(2)
    s = n.state()
    off, pos = s["screens"]["big"]["offset"], (s.get("playing") or {}).get("position")
    r.check("…at the wall clock's position, as if it had been on all along",
            pos is not None and abs(pos - off) < 2.5, (pos, off))
    expect = (time.time() - 1767225600.0) % (CLIP_SECONDS * 3)      # in order: ep0, ep1, ep2, round again
    idx = EPISODES.index(s["screens"]["big"]["item"]["id"])
    r.check("…which is the schedule's: the episode and the second, by the clock",
            abs(idx * CLIP_SECONDS + off - expect) < 3 or abs(idx * CLIP_SECONDS + off - expect) > CLIP_SECONDS * 3 - 3,
            (idx, off, expect))
    r.check("the key goes in a header, never a URL", all("test-key" not in p for p, _ in n.jf_seen), n.jf_seen[-3:])
    r.check("the sound is off by default: no stream in PipeWire", n.tv_stream() is None, n.streams())

    # -- the pointer: hover, the hint
    ptr.move(*center(big))
    r.check("hovering the big monitor shows the hint", wait_for(lambda: n.state().get("hint") == "big", 4), n.state())
    time.sleep(0.6)
    n.shot("tv-hint")
    st = n.state()
    r.check("the hint takes the pointer too while it shows", len(st.get("input") or []) == 4, st.get("input"))
    ptr.move(80, 80)
    r.check("moving off the screens hides it", wait_for(lambda: n.state().get("hint") is None, 4), n.state())

    # -- the wheel: channels, and the volume with Shift
    ptr.move(*center(big))
    time.sleep(0.4)
    ptr.scroll(1)
    r.check("a wheel notch down: the next channel (3, Second)",
            wait_for(lambda: n.state()["screens"]["big"]["channel"] == 3, 4), n.state()["screens"]["big"])
    time.sleep(0.2)
    n.shot("tv-tuning")
    ptr.scroll(-1)
    r.check("a notch up: back to Test Card (2)", wait_for(lambda: n.state()["screens"]["big"]["channel"] == 2, 4))
    time.sleep(0.6)
    vol0 = n.state()["screens"]["big"]["volume"]
    bar = (n.state().get("buttons") or {}).get("bar")
    r.check("the hint shows its volume bar", bar is not None, n.state().get("buttons"))
    if bar:
        ptr.move(*bar)
        time.sleep(0.3)
        ptr.scroll(-2)
    s = n.state()["screens"]["big"]
    r.check("the wheel over the volume bar: up 10%, and up from silent turns the sound on",
            s["volume"] == min(100, vol0 + 10) and s["sound"], s)
    r.check("the TV's sound in PipeWire as \"bromigOS den TV\", at its volume",
            wait_for(lambda: n.tv_volume() == s["volume"], 8), (n.streams(), n.tv_volume(), s["volume"]))
    r.check("the hint stays while the pointer is on it", n.state().get("hint") == "big")
    n.shot("tv-volume")

    # -- the hint's buttons: speaker, −, +
    time.sleep(0.6)
    btn = n.state().get("buttons") or {}
    r.check("the hint has its buttons", {"prev", "next", "speaker", "down", "up", "bar", "full", "web"} <= set(btn), btn)
    if "speaker" in btn:
        ptr.click(at=btn["speaker"])
        r.check("the speaker button: sound off, and the stream gone",
                wait_for(lambda: not n.state()["screens"]["big"]["sound"] and n.tv_stream() is None, 6), n.streams())
        ptr.click(at=btn["speaker"])
        r.check("…and on again", wait_for(lambda: n.tv_stream() is not None, 6))
        v = n.state()["screens"]["big"]["volume"]
        ptr.click(at=btn["down"])
        r.check("− steps it down 5%", wait_for(lambda: n.state()["screens"]["big"]["volume"] == v - 5, 3))
        bx, by = btn["bar"]
        ptr.click(at=(bx - 42 + 84 * 0.25, by))                    # a quarter along the 84 px bar
        r.check("clicking the bar sets the level", wait_for(lambda: abs(n.state()["screens"]["big"]["volume"] - 25) <= 3, 3),
                n.state()["screens"]["big"]["volume"])
    n.tv("volume", "40")

    # -- the desktop's sound around it
    r.check("tv volume 40", wait_for(lambda: n.tv_volume() == 40, 6), (n.streams(), n.tv_volume()))
    with open(os.path.join(n.run, "bromigos-vector.json"), "w") as f:
        json.dump({"state": "speaking"}, f)
    r.check("VECTOR speaking ducks it to 30%", wait_for(lambda: n.tv_volume() == 12, 4), n.tv_volume())
    with open(os.path.join(n.run, "bromigos-vector.json"), "w") as f:
        json.dump({"state": "idle"}, f)
    r.check("…and it comes back", wait_for(lambda: n.tv_volume() == 40, 4), n.tv_volume())
    muted = os.path.join(n.home, ".local", "state", "bromigos-live", "muted")
    os.makedirs(os.path.dirname(muted), exist_ok=True)
    open(muted, "w").close()
    r.check("bromigOS's mute silences it", wait_for(lambda: n.tv_stream() is None, 4), n.streams())
    os.remove(muted)
    r.check("…unmuted, it plays again", wait_for(lambda: n.tv_stream() is not None, 4))
    n.ctl_live("screensaver open")
    r.check("the screensaver mutes it (and the den pauses)", wait_for(lambda: n.tv_stream() is None, 6), n.streams())
    n.ctl_live("screensaver close")
    r.check("closing it gives the sound back", wait_for(lambda: n.tv_stream() is not None, 8), n.streams())

    # -- a window over the TV: a screen with its sound on plays on; a muted one pauses
    p = subprocess.Popen(["kitty"] if shutil.which("kitty") else ["foot"], env=n.env, stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL, start_new_session=True)
    r.check("a window over it: covered", wait_for(lambda: "big" in (n.state().get("covered") or []), 10),
            n.state().get("covered"))
    time.sleep(2)
    r.check("…with its sound on, it plays on behind the window (you hear it)",
            (n.state().get("playing") or {}).get("paused") is False and n.tv_stream() is not None,
            (n.state().get("playing"), n.streams()))
    n.tv("sound", "off", "--screen", "big")
    r.check("a muted screen behind a window pauses decoding",
            wait_for(lambda: (n.state()["screens"]["big"].get("playing") or {}).get("paused"), 10),
            n.state()["screens"]["big"].get("playing"))
    time.sleep(3)
    os.killpg(p.pid, signal.SIGTERM)
    n.tv("sound", "on", "--screen", "big")
    r.check("with it gone, decoding resumes", wait_for(lambda: (n.state().get("playing") or {}).get("paused") is False, 10))
    time.sleep(2.5)
    s = n.state()
    r.check("…caught up with the clock, not where it paused",
            abs((s.get("playing") or {}).get("position", -99) - s["screens"]["big"]["offset"]) < 2.5,
            (s.get("playing"), s["screens"]["big"]["offset"]))

    # -- a click: full screen with sound at the same moment
    ptr.move(*center(big))
    time.sleep(0.3)
    off = live_offset(n)
    t_click = time.time()
    ptr.click()
    r.check("a click opens mpv full screen", wait_for(lambda: any(c.get("class") == "mpv" and c.get("fullscreen")
                                                                  for c in json.loads(n.ctl("clients", "-j") or "[]")), 15),
            n.ctl("clients", "-j")[:400])
    args = (n.read("mpv-args.txt") or "").splitlines()
    start = next((float(a.split("=", 1)[1]) for a in args if a.startswith("--start=")), None)
    r.check("…at the same moment (--start)", start is not None and abs(start - (off + (time.time() - t_click) * 0)) < 3,
            (start, off))
    r.check("…on the same stream", any(a.endswith("/Videos/" + n.state()["screens"]["big"]["item"]["id"] +
                                              "/stream?static=true&MediaSourceId=" +
                                              n.state()["screens"]["big"]["item"]["id"]) for a in args), args[-1:])
    r.check("…with the TV's volume, and the key not on its command line",
            "--volume=40" in args and not any("test-key" in a for a in args), args)
    r.check("…with sound, as its own PipeWire stream", wait_for(lambda: len([x for x in n.streams()
                                                                           if x["name"] == "bromigOS den TV"]) >= 1, 8),
            n.streams())
    time.sleep(1.5)
    n.shot("tv-fullscreen")
    r.check("the den TV pauses behind it", wait_for(lambda: (n.state().get("playing") or {}).get("paused"), 6))
    for c in json.loads(n.ctl("clients", "-j") or "[]"):
        if c.get("class") == "mpv" and c.get("pid"):
            os.kill(int(c["pid"]), signal.SIGTERM)                  # closing its window
    r.check("closing mpv: back on the TV at the live position",
            wait_for(lambda: (n.state().get("playing") or {}).get("paused") is False, 10))
    time.sleep(2.5)
    s = n.state()
    r.check("…on the clock", abs((s.get("playing") or {}).get("position", -99) - s["screens"]["big"]["offset"]) < 2.5,
            (s.get("playing"), s["screens"]["big"]["offset"]))
    r.check("…with its sound as it was", s["screens"]["big"]["sound"] and wait_for(lambda: n.tv_volume() == 40, 6),
            (s["screens"]["big"]["sound"], n.streams(), n.tv_volume()))

    # -- the commands
    r.check("tv volume 150 is capped at 100", "volume 100%" in (n.tv("volume", "150") or ""))
    n.tv("volume", "40")
    n.tv("sound", "off")
    r.check("tv sound off", wait_for(lambda: n.tv_stream() is None, 4))
    n.tv("volume", "up")
    r.check("tv volume up from silent turns it on", n.state()["screens"]["big"]["sound"])
    # -- every screen at once, the sound moving between them
    n.tv("set", "3", "--screen", "wave")
    n.tv("set", "2", "--screen", "emblem")
    s = n.state()["screens"]
    r.check("the scope and the small monitor tuned in; the big monitor stays on its channel",
            s["wave"]["name"] == "Scope Clips" and s["emblem"]["name"] == "Small Clips" and s["big"]["channel"] == 2,
            {k: (v["channel"], v["name"]) for k, v in s.items()})
    r.check("three screens play at once, each with a player of its own",
            wait_for(lambda: all((v.get("playing") or {}).get("has_frame") and
                                 not (v.get("playing") or {}).get("paused")
                                 for v in n.state()["screens"].values()), 20),
            {k: v.get("playing") for k, v in n.state()["screens"].items()})
    n.shot("tv-three-screens")
    n.tv("sound", "on", "--screen", "scope")
    r.check("sound on the scope: the big monitor's goes off, one stream in PipeWire",
            wait_for(lambda: n.state().get("sound_from") == "wave" and
                     len([x for x in n.streams() if x["name"] == "bromigOS den TV"]) == 1 and
                     not n.state()["screens"]["big"]["sound"], 8), (n.state().get("sound_from"), n.streams()))
    n.tv("sound", "on", "--screen", "small")
    r.check("…and on to the small monitor", wait_for(lambda: n.state().get("sound_from") == "emblem" and
                                                     len([x for x in n.streams()
                                                          if x["name"] == "bromigOS den TV"]) == 1, 8),
            (n.state().get("sound_from"), n.streams()))
    ptr.move(*center(emblem))
    r.check("the hint over the small monitor: its speaker on, the others' off",
            wait_for(lambda: n.state().get("hint") == "emblem", 4) and n.state()["screens"]["emblem"]["sound"])
    ptr.move(80, 80)
    n.tv("sound", "on", "--screen", "big")
    n.tv("set", "2", "big")
    lst = n.tv("list")
    r.check("tv list", "Test Card" in (lst or "") and "RELAY MAP" in lst, lst)
    r.check("tv web opens the item's page", "opened" in (n.tv("web") or "") and
            wait_for(lambda: "/web/#/details?id=" in (n.read("xdg-open.log") or ""), 5), n.read("xdg-open.log"))

    # -- remembered across a restart
    before = {k: (v["channel"], v["sound"], v["volume"]) for k, v in n.state()["screens"].items()}
    n.stop_live()
    n.start_live()
    r.check("the live layer back", wait_for(lambda: (n.state().get("screens") or {}).get("big", {}).get("of") == 3, 20))
    after = {k: (v["channel"], v["sound"], v["volume"]) for k, v in n.state()["screens"].items()}
    r.check("each screen's channel, sound and volume remembered", before == after, (before, after))

    # -- the channel guide (the standalone Den TV app): the live layer follows each change
    guide(n, r)

    if measure:
        measure_cost(n, r, measure)


def guide(n, r):
    env = dict(n.live_env(), PATH=f"{os.path.join(REPO, 'desktop', 'settings')}:{os.path.join(REPO, 'live', 'bin')}:{n.stubs}:/usr/bin",
               PYTHONPATH=os.pathsep.join([os.path.join(REPO, "lib"), os.path.join(REPO, "homelab", "lib")]))
    with open(os.path.join(n.home, ".config", "bromigos-live", "config.toml")) as f:
        text = f.read()
    with open(os.path.join(n.home, ".config", "bromigos-live", "config.toml"), "w") as f:
        f.write("# the den TV, as the test has it\n" + text)
    time.sleep(3)                                              # the live layer reads the comment line too
    p = subprocess.run([sys.executable, os.path.join(HERE, "den_tv_guide_driver.py"),
                        os.path.join(os.path.dirname(HERE), "settings"), os.path.join(n.tmp, "media2")],
                       env=env, capture_output=True, text=True, timeout=300)
    steps = [ln for ln in p.stdout.splitlines() if ln.startswith(("PASS", "FAIL"))]
    for ln in steps:
        name, _, detail = ln.split(" ", 1)[1].partition(" | ")
        r.check("guide: " + name, ln.startswith("PASS"), detail)
    r.check("guide: the driver ran every step", len(steps) >= 8, (p.returncode, p.stdout[-500:], p.stderr[-1500:]))
    log = open(os.path.join(n.home, "live.log")).read()
    r.check("guide: the live layer read the channels again without a restart (no new background)",
            "the den TV's channels changed; read again" in log and log.count("background failed") == 0, log[-600:])


def controller_checks(n, r):
    """The shipped physical-code binds through a virtual keyboard, and the real mpv OSC."""
    n.ptr.move(80,80)
    for locked in (0,16):  # Mod2 is NumLock in the fixture's US keymap.
        n.kb.lock(locked)
        n.kb.combo("SUPER + KP_1")
        r.check("remote: select BIG with NumLock " + ("on" if locked else "off"),
                wait_for(lambda:n.state().get("selected")=="big",5), n.state().get("selected"))
        r.check("remote: enters its Hyprland submap", "bromigos-tv-remote" in n.submap(), n.submap())
        old=n.state()["screens"]["big"]["volume"]
        n.kb.combo("KP_ADD")
        r.check("remote: number-pad volume",wait_for(lambda:n.state()["screens"]["big"]["volume"]==min(100,old+5),5))
        n.kb.combo("KP_DECIMAL"); n.kb.combo("KP_2")
        r.check("remote: digit 2 tunes after one second",wait_for(lambda:n.state()["screens"]["big"]["channel"]==2 and n.state().get("digits") is None,5))
        n.kb.combo("KP_6")
        r.check("remote: skip plays the next item",wait_for(lambda:n.state()["screens"]["big"].get("on_demand"),5))
        n.kb.combo("KP_0")
        r.check("remote: deselect and reset",wait_for(lambda:n.state().get("selected") is None and n.submap() == "default",5))
    n.kb.combo("SUPER + KP_2")
    r.check("remote: select scope",wait_for(lambda:n.state().get("selected")=="wave",5))
    r.check("remote: idle timeout gives the keyboard back",wait_for(lambda:n.state().get("selected") is None and n.submap() == "default",18))
    n.tv("set","2","--screen","big")
    n.tv("open","--screen","big")
    args_path=os.path.join(n.home,"mpv-args.txt")
    r.check("full screen: private controller loaded by --script, global config off",wait_for(lambda:os.path.exists(args_path),8))
    with open(args_path) as f: args=f.read().splitlines()
    r.check("full screen: no stock OSC or global scripts", "--no-config" in args and "--load-scripts=no" in args and "--osc=no" in args and any("tvosc.lua" in v for v in args),args)
    path=next(v.split("=",1)[1] for v in args if v.startswith("--input-ipc-server="))
    def mpv(*command):
        try:
            with socket.socket(socket.AF_UNIX) as sock:
                sock.settimeout(2);sock.connect(path)
                sock.sendall(json.dumps(dict(command=list(command),request_id=71)).encode()+b"\n")
                buf=b""
                while True:
                    data=sock.recv(65536)
                    if not data:return None
                    buf+=data
                    while b"\n" in buf:
                        line,buf=buf.split(b"\n",1);doc=json.loads(line)
                        if doc.get("request_id")==71:return doc.get("data",doc.get("error")=="success")
        except OSError:return None
    r.check("full screen: Lua controller answers in real nested mpv",wait_for(lambda:bool(mpv("get_property","user-data/den/controller")),8))
    mpv("set_property","volume",37)
    r.check("full screen: volume shared with the den",wait_for(lambda:n.state()["screens"]["big"]["volume"]==37,5))
    mpv("quit")
    r.check("full screen: back to den, same volume",wait_for(lambda:not n.state().get("full_screen") and n.state()["screens"]["big"]["volume"]==37,8))


def measure_cost(n, r, secs):
    """The live layer's CPU (all its threads, mpv's decoder included) and the GPU it uses,
    with the TV playing and with every screen on its own picture."""
    def sample(label):
        pid = n.live.pid
        t0, (c0, _) = time.monotonic(), n.proc_cpu(pid)
        gpu = subprocess.Popen(["nvidia-smi", "pmon", "-s", "u", "-c", str(int(secs)), "-d", "1"],
                               stdout=subprocess.PIPE, text=True) if shutil.which("nvidia-smi") else None
        time.sleep(secs)
        t1, (c1, _) = time.monotonic(), n.proc_cpu(pid)
        sm = dec = []
        if gpu:
            out = gpu.communicate(timeout=secs + 10)[0]
            rows = [ln.split() for ln in out.splitlines() if ln.strip() and not ln.startswith("#")]
            mine = [x for x in rows if len(x) > 5 and x[1] == str(pid)]
            sm = [float(x[3]) for x in mine if x[3] not in ("-",)]
            dec = [float(x[6]) for x in mine if len(x) > 6 and x[6] not in ("-",)]
        cpu = (c1 - c0) / (t1 - t0) * 100
        avg = lambda v: sum(v) / len(v) if v else 0.0  # noqa: E731
        print(f"MEASURE  {label}: live layer CPU {cpu:.1f}% of one core; GPU SM {avg(sm):.1f}%, "
              f"decoder {avg(dec):.1f}% (nvidia-smi pmon, {len(sm)} samples)", flush=True)
        return cpu
    n.ptr.move(80, 80)
    for s in ("big", "wave", "emblem"):
        n.tv("sound", "off", "--screen", s)
    n.tv("set", "2", "--screen", "big")
    n.tv("set", "3", "--screen", "wave")
    n.tv("set", "2", "--screen", "emblem")
    time.sleep(4)
    three = sample("three screens playing (muted)")
    n.tv("sound", "on", "--screen", "big")
    time.sleep(2)
    sample("three screens playing, the big monitor's sound on")
    n.tv("sound", "off", "--screen", "big")
    n.tv("set", "1", "--screen", "wave")
    n.tv("set", "1", "--screen", "emblem")
    time.sleep(35)                                   # a screen's mpv is closed after 30 s with nothing on
    one = sample("one screen playing (the big monitor)")
    n.tv("set", "1", "--screen", "big")
    time.sleep(35)
    off = sample("no media channel (the den as before)")
    r.check("one screen's cost is small: under 6% of a core over the den alone", one - off < 6, (one, off))
    r.check("three screens: under 12% of a core over the den alone", three - off < 12, (three, off))


def main():
    keep = "--keep" in sys.argv
    shots_dir = sys.argv[sys.argv.index("--shots") + 1] if "--shots" in sys.argv else None
    measure = float(sys.argv[sys.argv.index("--measure") + 1]) if "--measure" in sys.argv else 0
    for tool in ("kwin_wayland", "dbus-run-session", "Hyprland", "mpv", "ffmpeg"):
        if not shutil.which(tool):
            print(f"SKIP: needs {tool}")
            return 0
    if not sandbox_audio.available():
        print("SKIP: needs pipewire, wireplumber, pipewire-pulse, pactl")
        return 0
    if subprocess.run([sys.executable, "-c", "import mpv"], capture_output=True).returncode != 0:
        print("SKIP: needs python-mpv")
        return 0
    n = TVNest(keep, shots_dir)
    r = Run()
    try:
        n.start()
        if "--controls-only" in sys.argv:
            controller_checks(n,r)
        elif "--guide-only" in sys.argv:
            guide(n,r)
        else:
            scenarios(n, r, measure)
    finally:
        n.stop()
        if keep:
            print(f"kept: {n.tmp}")
    failed = [x for x in r.results if not x[1]]
    print(f"\n{len(r.results) - len(failed)}/{len(r.results)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
