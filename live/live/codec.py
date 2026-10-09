"""Codec calls: important real events arrive as a short voiced transmission.

Sources (all real): notable paper fills (the [fills] feed), lab alerts from the lab snapshot,
long jobs finishing ('bromigos-live job -- cmd'), critical notifications, or
'bromigos-live codec "text" [CHANNEL]'.

Voice: VECTOR's notify voice (one voice cast on the desktop): its speech server and
bromigos/holo/voice.json, Kokoro's 55/45 blend of two stock British male
styles, nobody cloned. If that server is down, the lab's Breeze TTS
(LAN only, default voice). Lightly band-passed like a handset, behind the
codec chirp. Without the voice (quiet mode, mute, TTS
down) the call still shows, silently.

Sanity: one call at a time, at least `min_gap` seconds apart, at most
`max_per_hour`, identical messages at most once per `dedupe` seconds; never
while locked or under a fullscreen window. Channel readouts are channel names,
never anyone's identity frequency.
"""
import hashlib
import os
import ssl
import subprocess
import tempfile
import threading
import time
import urllib.request
import uuid

import numpy as np

from .sound import SOUNDS, STATE, muted

CACHE = os.path.join(os.environ.get("XDG_CACHE_HOME", os.path.expanduser("~/.cache")), "bromigos-live", "tts")
QUIET = os.path.join(STATE, "codec-quiet")
CHANNELS = {"FLOOR": ("CH 01", "THE FLOOR"), "LAB": ("CH 02", "THE LAB"), "DECK": ("CH 03", "THE DECK"),
            "PRIORITY": ("CH 04", "PRIORITY")}


def quiet():
    return os.path.exists(QUIET)


def toggle_quiet():
    os.makedirs(STATE, exist_ok=True)
    if quiet():
        os.remove(QUIET)
        return False
    open(QUIET, "w").close()
    return True


class Call:
    def __init__(self, channel, text):
        self.channel = channel if channel in CHANNELS else "PRIORITY"
        self.text = " ".join(text.split())[:180]
        self.wav = None          # rendered transmission (chirp + voice), or None (silent)
        self.env = None          # amplitude envelope, 60 Hz frames, 0..1
        self.voice_at = 0.0      # seconds into the wav where speech starts
        self.voice_end = 0.0     # ... and ends
        self.ready = threading.Event()
        self.started = None      # monotonic time playback started
        self.duration = 4.0


class Desk:
    def __init__(self, app):
        self.app = app
        self.lock = threading.Lock()
        self.history = []        # (time, text)
        self.current = None
        self.queue = []

    @property
    def cfg(self):
        return self.app.cfg.get("codec", {})

    # ------------------------------------------------------------------ intake
    def offer(self, channel, text, force=False):
        """Returns a short reason string (for the CLI / log)."""
        c = self.cfg
        if not c.get("enabled", True):
            return "codec disabled"
        now = time.time()
        with self.lock:
            self.history = [(t, m) for t, m in self.history if now - t < 3600]
            if not force:
                if self.app.locked or self.app.fullscreen:
                    return "held: locked or fullscreen"
                if any(m == text and now - t < float(c.get("dedupe", 1800)) for t, m in self.history):
                    return "dropped: same message recently"
                if self.history and now - self.history[-1][0] < float(c.get("min_gap", 120)):
                    return "dropped: too soon after the last call"
                if len(self.history) >= int(c.get("max_per_hour", 8)):
                    return "dropped: hourly cap"
            if self.current is not None:
                if len(self.queue) < 2:
                    self.queue.append(Call(channel, text))
                    return "queued"
                return "dropped: line busy"
            self.history.append((now, text))
            call = Call(channel, text)
            if getattr(self.app, "history", None):
                self.app.history.event("codec", f"{channel}: {text}")
            self.current = call
        threading.Thread(target=self._prepare, args=(call,), daemon=True).start()
        from gi.repository import GLib
        GLib.idle_add(self._show, call)
        return "calling"

    def _show(self, call):
        self.app.overlay("codec", call=call)
        return False

    def done(self, call):
        with self.lock:
            if self.current is call:
                self.current = None
            nxt = self.queue.pop(0) if self.queue else None
        if nxt:
            self.offer(nxt.channel, nxt.text, force=True)

    # ------------------------------------------------------------------ voice
    def _tts(self, text):
        c = self.cfg
        url = c.get("tts_url", "")
        if not url:
            raise RuntimeError("tts: no TTS endpoint configured (private overlay endpoints.tts)")
        inst = c.get("tts_instruction", "A calm, low radio operator voice; short, clear, unhurried.")
        key = hashlib.sha1(f"{url}|{inst}|{text}".encode()).hexdigest()[:20]
        os.makedirs(CACHE, exist_ok=True)
        raw = os.path.join(CACHE, key + ".pcm")
        if os.path.exists(raw):
            return raw
        boundary = uuid.uuid4().hex
        parts = []
        for name, val in (("text", text), ("instruction", inst), ("seed", "7")):
            parts.append(f"--{boundary}\r\nContent-Disposition: form-data; name=\"{name}\"\r\n\r\n{val}\r\n")
        body = ("".join(parts) + f"--{boundary}--\r\n").encode()
        ca = os.path.expanduser(self.app.cfg.get("cluster", {}).get("ca_file", "") or "")
        ctx = ssl.create_default_context(cafile=ca) if ca and os.path.exists(ca) else ssl.create_default_context()
        req = urllib.request.Request(url, data=body, method="POST",
                                     headers={"Content-Type": f"multipart/form-data; boundary={boundary}"})
        with urllib.request.urlopen(req, timeout=float(c.get("tts_timeout", 45)), context=ctx) as r:
            data = r.read()
        if len(data) < 2400:
            raise RuntimeError("tts: empty audio")
        tmp = raw + ".part"
        with open(tmp, "wb") as f:
            f.write(data)
        os.replace(tmp, raw)
        return raw

    def _pilot_voice(self, text):
        """VECTOR's voice: his own speech server and voice.json (the notify role), so the
        desktop has one voice. Returns a wav path (cached by the server) or raises."""
        import sys
        from . import VECTOR
        holo = os.path.expanduser(self.cfg.get("pilot_holo") or "")
        holo = holo if os.path.isdir(os.path.join(holo, "holo")) else VECTOR    # a stale setting: the installed one
        if not holo or not os.path.isdir(holo):
            raise RuntimeError("pilot voice: VECTOR isn't installed")
        if holo not in sys.path:
            sys.path.insert(0, holo)
        from holo.pilot.voice import Voice      # the client: spawns the venv server if it is down
        if getattr(self, "_pv", None) is None:
            self._pv = Voice(None)
        out = self._pv._req({"op": "tts", "text": text}, float(self.cfg.get("tts_timeout", 45)))
        if not out.get("wav") or not os.path.exists(out["wav"]):
            raise RuntimeError("pilot voice: no audio")
        return out["wav"]

    def voice(self, text):
        """(path, ffmpeg input args): VECTOR's voice first, the lab's Breeze TTS if it is down."""
        if self.cfg.get("voice", "pilot") == "pilot":
            try:
                return self._pilot_voice(text), []
            except Exception as e:
                print("bromigos-live: pilot voice unavailable, using breeze:", str(e)[:100], flush=True)
        return self._tts(text), ["-f", "s16le", "-ar", "24000", "-ac", "1"]

    def _prepare(self, call):
        try:
            if quiet() or muted() or not self.app.cfg.get("sounds", {}).get("enabled", True):
                raise RuntimeError("silent")
            raw, fmt_args = self.voice(call.text)
            chirp = os.path.join(SOUNDS, self.app.cfg["sounds"].get("notify", "chirp.wav"))
            hiss = os.path.join(SOUNDS, self.app.cfg["sounds"].get("hiss", "hiss.wav"))
            out = tempfile.NamedTemporaryFile(prefix="bromigos-codec-", suffix=".wav", delete=False).name
            # chirp, then the voice through a handset band, then a breath of carrier
            trim = ("silenceremove=start_periods=1:start_silence=0.05:start_threshold=-40dB,areverse,"
                    "silenceremove=start_periods=1:start_silence=0.05:start_threshold=-40dB,areverse,")
            fc = ("[1:a]aformat=sample_rates=48000:channel_layouts=mono," + trim + "highpass=f=180,lowpass=f=5200,"
                  "acompressor=threshold=-20dB:ratio=3:attack=5:release=80,volume=1.6,"
                  "adelay=120|120[v];"
                  "[0:a]aformat=sample_rates=48000:channel_layouts=mono,volume=0.8[c];"
                  "[2:a]aformat=sample_rates=48000:channel_layouts=mono,atrim=0:0.45,volume=0.35[h];"
                  "[c][v][h]concat=n=3:v=0:a=1,loudnorm=I=-22:TP=-4[o]")
            subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", chirp] + fmt_args +
                           ["-i", raw, "-i", hiss, "-filter_complex", fc, "-map", "[o]", "-ar", "48000", out],
                           check=True, timeout=30)
            pcm = subprocess.run(["ffmpeg", "-v", "error", "-i", out, "-f", "s16le", "-ac", "1", "-ar", "6000", "-"],
                                 capture_output=True, timeout=20).stdout
            x = np.frombuffer(pcm, dtype=np.int16).astype(np.float32) / 32768.0
            hop = 100                                              # 60 Hz frames at 6 kHz
            n = len(x) // hop
            env = np.sqrt((x[:n * hop].reshape(n, hop) ** 2).mean(1)) if n else np.zeros(1)
            env = np.clip(env / max(np.percentile(env, 98), 1e-4), 0, 1.2).astype(np.float32)
            call.env = env
            call.wav = out
            call.duration = n / 60.0
            chirp_s = self._chirp_len(chirp) + 0.12
            idx = np.nonzero(env[int(chirp_s * 60):] > 0.12)[0]
            call.voice_at = chirp_s + (idx[0] / 60.0 if len(idx) else 0.0)
            call.voice_end = chirp_s + (idx[-1] / 60.0 if len(idx) else call.duration - chirp_s)
        except Exception as e:
            if str(e) != "silent":
                print("bromigos-live: codec voice unavailable:", str(e)[:120], flush=True)
            call.wav = None
            call.duration = max(3.5, len(call.text) * 0.06)
        call.ready.set()

    @staticmethod
    def _chirp_len(path):
        try:
            out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", path],
                                 capture_output=True, text=True, timeout=5).stdout
            return float(out.strip())
        except Exception:
            return 0.9

    def play(self, call):
        call.started = time.monotonic()
        if call.wav:
            self.app.sound.play_file(call.wav, delete=True)
