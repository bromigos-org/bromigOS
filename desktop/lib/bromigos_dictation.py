"""Hold-to-dictate: bounded microphone capture, transcript previews and release to insert."""
import array
import io
import json
import math
import os
import signal
import socket
import subprocess
import tempfile
import threading
import time
import urllib.request
import wave

RATE = 16000
MAX_SECONDS = 120
PREVIEW_SECONDS = 1.2


class DictationError(Exception):
    pass


def runtime():
    root = os.environ.get("XDG_RUNTIME_DIR")
    display = os.environ.get("WAYLAND_DISPLAY")
    if not root or not display:
        raise DictationError("Dictation needs a Wayland session")
    # One controller per compositor; tests never find another session's socket.
    name = os.path.basename(display).replace("/", "_")
    path = os.path.join(root, "bromigos-dictation", name)
    os.makedirs(path, mode=0o700, exist_ok=True)
    return path


def focused_window():
    if not os.environ.get("HYPRLAND_INSTANCE_SIGNATURE"):
        raise DictationError("Dictation needs this session's Hyprland")
    try:
        p = subprocess.run(["hyprctl", "activewindow", "-j"], capture_output=True, text=True, timeout=3)
        address = json.loads(p.stdout).get("address") if p.returncode == 0 else None
    except (OSError, ValueError, subprocess.TimeoutExpired):
        address = None
    if not address:
        raise DictationError("Select a text field before holding the dictation key")
    return address


class Backend:
    """Use the existing voice worker, else a configured lab voice service. No AI turn."""
    def __init__(self, directory):
        self.directory = directory
        self.voice_socket = os.environ.get("BROMIGOS_VOICE_SOCK") or os.path.join(
            os.environ.get("XDG_RUNTIME_DIR", ""), "bromigos-holo-voice.sock")
        self.provider = None
        if not os.path.exists(self.voice_socket):
            try:
                from bromigos_homelab import registry
                self.provider = next(iter(registry.providers("voice")), None)
            except ImportError:
                pass
            if self.provider is None:
                raise DictationError("Set up a voice service in Settings › Lab to use dictation")

    def __call__(self, pcm):
        try:
            if self.provider is not None:
                buffer = io.BytesIO()
                with wave.open(buffer, "wb") as wav:
                    wav.setnchannels(1)
                    wav.setsampwidth(2)
                    wav.setframerate(RATE)
                    wav.writeframes(pcm)
                req = urllib.request.Request(self.provider.endpoint + "/v1/stt?language=en",
                    data=buffer.getvalue(), method="POST",
                    headers=dict(self.provider.auth_headers(), **{"Content-Type": "audio/wav"}))
                with urllib.request.urlopen(req, timeout=30, context=self.provider._ctx()) as response:
                    result = json.loads(response.read(1 << 20))
            else:
                # The existing worker accepts a raw PCM path; private, removed after each request.
                with tempfile.NamedTemporaryFile(dir=self.directory, suffix=".pcm") as sample:
                    sample.write(pcm)
                    sample.flush()
                    with socket.socket(socket.AF_UNIX) as connection:
                        connection.settimeout(30)
                        connection.connect(self.voice_socket)
                        connection.sendall((json.dumps({"op": "stt", "pcm": sample.name}) + "\n").encode())
                        data = bytearray()
                        while not data.endswith(b"\n"):
                            part = connection.recv(65536)
                            if not part or len(data) + len(part) > 1 << 20:
                                raise DictationError("The speech service returned no transcript")
                            data.extend(part)
                        result = json.loads(data)
            if not isinstance(result, dict) or result.get("error"):
                raise DictationError("The speech service could not transcribe this recording")
            return " ".join(str(result.get("text") or "").split())
        except DictationError:
            raise
        except (OSError, ValueError, RuntimeError):
            # Network exceptions can include private endpoints or authentication details.
            raise DictationError("The speech service did not answer. Try again") from None


class Recorder:
    """PipeWire's current microphone, opened only between press and release."""
    def __init__(self, level):
        self.level_callback = level
        self.lock = threading.Lock()
        self.pcm = bytearray()
        self.done = threading.Event()
        self.stopping = threading.Event()
        self.error = None
        self.peak = 0.0
        try:
            self.proc = subprocess.Popen(["pw-record", "--raw", "--rate", str(RATE),
                "--channels", "1", "--format", "s16", "-"], stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        except OSError:
            raise DictationError("PipeWire could not open your microphone") from None
        self.thread = threading.Thread(target=self._read, daemon=True, name="dictation-microphone")
        self.thread.start()

    def _read(self):
        try:
            while True:
                data = self.proc.stdout.read(2048)
                if not data:
                    break
                with self.lock:
                    remaining = MAX_SECONDS * RATE * 2 - len(self.pcm)
                    self.pcm.extend(data[:remaining])
                samples = array.array("h", data[:len(data) // 2 * 2])
                level = math.sqrt(sum(v * v for v in samples) / max(1, len(samples))) / 32768
                self.peak = max(self.peak, level)
                self.level_callback(min(1, level * 8))
                if remaining <= len(data):
                    self.error = "Recording limit reached; try a shorter dictation"
                    self.stop()
                    break
            if not self.stopping.is_set():
                self.error = "Your microphone stopped recording"
        except (OSError, ValueError):
            self.error = "Your microphone stopped recording"
        finally:
            self.proc.stdout.close()
            try:
                self.proc.wait(timeout=2)
            except subprocess.TimeoutExpired:
                self.proc.kill()
                self.proc.wait()
            self.done.set()

    def snapshot(self):
        with self.lock:
            return bytes(self.pcm)

    def stop(self):
        self.stopping.set()
        if self.proc.poll() is None:
            try:
                self.proc.send_signal(signal.SIGINT)
            except ProcessLookupError:
                pass

    def finish(self):
        self.stop()
        if not self.done.wait(2):
            self.proc.kill()
            self.done.wait(2)
        return self.snapshot()

    def erase(self):
        with self.lock:
            self.pcm.clear()


class Session:
    """One recording. Cancellation invalidates even an in-flight speech response."""
    def __init__(self, backend, insert, event, target, recorder=Recorder, interval=PREVIEW_SECONDS):
        self.backend, self.insert, self.event, self.target = backend, insert, event, target
        self.interval = interval
        self.released = threading.Event()
        self.cancelled = threading.Event()
        self.finished = threading.Event()
        self.state, self.text, self.level = "listening", "", 0.0
        self.started = time.monotonic()
        self.recorder = recorder(self._level)
        self.thread = threading.Thread(target=self._recognize, daemon=True, name="dictation-transcript")

    def start(self):
        self.event("listening", "", 0)
        self.thread.start()

    def _level(self, value):
        self.level = value
        if not self.cancelled.is_set() and not self.finished.is_set():
            self.event(self.state, self.text, value)

    def release(self):
        if self.state == "listening" and not self.cancelled.is_set():
            self.state = "finishing"
            self.recorder.stop()
            self.released.set()
            self.event(self.state, self.text, 0)

    def cancel(self):
        self.cancelled.set()
        self.recorder.stop()
        self.released.set()

    def _recognize(self):
        last, text = b"", ""
        try:
            while not self.released.wait(self.interval):
                if self.recorder.error:
                    raise DictationError(self.recorder.error)
                sample = self.recorder.snapshot()
                if sample != last and len(sample) >= RATE and self.recorder.peak > .002:
                    text = self.backend(sample)
                    last = sample
                    if not self.cancelled.is_set():
                        self.text = text
                        self.event(self.state, text, self.level)
            sample = self.recorder.finish()
            if self.cancelled.is_set():
                return
            if self.recorder.error:
                raise DictationError(self.recorder.error)
            if len(sample) >= RATE // 5 and self.recorder.peak > .002:
                if sample != last:
                    text = self.backend(sample)
                if text and not self.cancelled.is_set():
                    self.text, self.state = text, "inserting"
                    self.event("inserting", text, 0)
                    self.insert(text, self.target, lambda: not self.cancelled.is_set())
            if not self.cancelled.is_set():
                self.state = "done"
                self.event("done", "", 0)
        except Exception as error:
            if not self.cancelled.is_set():
                self.state = "error"
                message = str(error) if isinstance(error, DictationError) else "Dictation could not insert the text"
                self.event("error", message, 0)
        finally:
            self.recorder.finish()
            self.recorder.erase()
            self.text = ""
            self.finished.set()


def insert_text(text, target, alive=lambda: True):
    from bromigos_type import type_text

    def check():
        return alive() and focused_window() == target

    if not check():
        raise DictationError("Focus changed; no text was inserted")
    type_text(text, check)
