#!/usr/bin/env python3
"""Menu hold/release, preview, focus and Unicode insertion in an unseen nested Hyprland.

The microphone and voice worker are synthetic. The GTK entry, overlay and Wayland
keyboard are real, all in e2e_keys_nested.py's private HOME, runtime and compositor.
Nothing records a real microphone, opens on the desktop or reads its clipboard.

    /usr/bin/python desktop/tests/e2e_dictation_nested.py [--shots DIR]
"""
import json
import os
import signal
import socket
import subprocess
import sys
import threading
import time

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, HERE)
import e2e_keys_nested as E  # noqa: E402

WORDS = "Hello, café — <world>! 😀"

MIC = '''#!/usr/bin/python
import array, math, os, signal, sys, time
stop = False
def end(*_):
    global stop
    stop = True
signal.signal(signal.SIGINT, end)
signal.signal(signal.SIGTERM, end)
mark = os.path.join(os.environ['XDG_RUNTIME_DIR'], 'synthetic-microphone.log')
with open(mark, 'a') as f: f.write('on\\n')
try:
    while not stop:
        samples = array.array('h', [int(5000 * math.sin(i * .1)) for i in range(1024)])
        sys.stdout.buffer.write(samples.tobytes()); sys.stdout.buffer.flush()
        time.sleep(.064)
finally:
    with open(mark, 'a') as f: f.write('off\\n')
'''

ENTRY = '''#!/usr/bin/python
import json, os
import gi
gi.require_version('Gtk', '4.0')
from gi.repository import Gtk, GLib
app = Gtk.Application(application_id='org.bromigos.DictationFixture')
entry = None
def save(*_):
    if entry is not None:
        with open(os.environ['DICTATION_ENTRY_STATE'], 'w') as f:
            json.dump({'text':entry.get_text(), 'position':entry.get_position()}, f)
    return True
def activate(app):
    global entry
    win = Gtk.ApplicationWindow(application=app, title='Dictation test')
    win.set_default_size(700, 320)
    box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=20)
    box.set_margin_top(140); box.set_margin_start(40); box.set_margin_end(40)
    box.append(Gtk.Label(label='A text field in the nested test app'))
    entry = Gtk.Entry(text='Start:  end.')
    entry.connect('changed', save)
    box.append(entry); win.set_child(box); win.present()
    entry.grab_focus(); entry.set_position(7)
    GLib.timeout_add(50, save)
app.connect('activate', activate)
app.run([])
'''


TERMINAL = """#!/usr/bin/python
import json, os, sys, tty
tty.setraw(sys.stdin.fileno())
data = bytearray()
with open(os.environ['DICTATION_TERMINAL_STATE'], 'w') as f: json.dump({'text':''}, f)
while True:
    part = os.read(sys.stdin.fileno(), 64)
    if not part: break
    data.extend(part)
    with open(os.environ['DICTATION_TERMINAL_STATE'], 'w') as f:
        json.dump({'text':data.decode('utf-8', errors='replace')}, f)
"""


class Voice:
    def __init__(self, path):
        self.server = socket.socket(socket.AF_UNIX)
        self.server.bind(path)
        self.server.listen(4)
        self.server.settimeout(.2)
        self.closed = threading.Event()
        self.entered = threading.Event()
        self.delay, self.calls = .05, []
        self.thread = threading.Thread(target=self.listen, daemon=True)
        self.thread.start()

    def listen(self):
        while not self.closed.is_set():
            try:
                conn, _ = self.server.accept()
            except socket.timeout:
                continue
            except OSError:
                return
            with conn:
                data = bytearray()
                while not data.endswith(b"\n"):
                    part = conn.recv(65536)
                    if not part:
                        break
                    data.extend(part)
                if not data:
                    continue
                req = json.loads(data)
                if req.get("op") == "stt":
                    self.calls.append(os.path.getsize(req["pcm"]))
                    self.entered.set()
                    time.sleep(self.delay)
                    conn.sendall(json.dumps({"text": WORDS}).encode() + b"\n")

    def close(self):
        self.closed.set()
        self.server.close()
        self.thread.join(2)


def main():
    shots = sys.argv[sys.argv.index("--shots") + 1] if "--shots" in sys.argv else None
    command = os.path.join(REPO, "desktop", "bin", "bromigos-dictate")
    E.STUBS["bromigos"] = ('#!/bin/sh\nif [ "$1" = dictate ]; then shift; exec /usr/bin/python '
                          + command + ' "$@"; fi\nexit 0\n')
    nest = E.Nest(shots=shots)
    voice = Voice(os.path.join(nest.run, "synthetic-voice.sock"))
    nest.base["BROMIGOS_VOICE_SOCK"] = os.path.join(nest.run, "synthetic-voice.sock")
    nest.base["DICTATION_ENTRY_STATE"] = os.path.join(nest.run, "entry.json")
    nest.base["DICTATION_TERMINAL_STATE"] = os.path.join(nest.run, "terminal.json")
    for name, text in (("pw-record", MIC), ("entry.py", ENTRY), ("terminal.py", TERMINAL)):
        path = os.path.join(nest.stubs, name)
        with open(path, "w") as f:
            f.write(text)
        os.chmod(path, 0o755)
    results, daemon_pid = [], None

    def check(name, condition):
        results.append(bool(condition))
        print(("PASS " if condition else "FAIL ") + name, flush=True)

    def call(verb):
        p = subprocess.run(["/usr/bin/python", command, verb, "--json"], env=nest.env,
                           capture_output=True, text=True, timeout=10)
        try:
            return json.loads(p.stdout)
        except ValueError:
            return {}

    def state():
        try:
            with open(nest.base["DICTATION_ENTRY_STATE"]) as f:
                return json.load(f)
        except (OSError, ValueError):
            return {}

    try:
        nest.start()
        entry = subprocess.Popen(["/usr/bin/python", os.path.join(nest.stubs, "entry.py")], env=nest.env,
                                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
        nest.procs.append(entry)
        if not E.wait_for(lambda: state().get("text") == "Start:  end."):
            raise RuntimeError("the nested GTK entry did not start")
        E.wait_for(lambda: json.loads(nest.ctl("activewindow", "-j") or "{}").get("class") ==
                   "org.bromigos.DictationFixture")
        target = json.loads(nest.ctl("activewindow", "-j"))["address"]
        clipboard = subprocess.Popen(["wl-copy", "--foreground", "--type", "text/plain"], stdin=subprocess.PIPE,
                                     env=nest.env, start_new_session=True)
        clipboard.stdin.write(b"Clipboard stays unchanged")
        clipboard.stdin.close()
        nest.procs.append(clipboard)
        # Physical Menu: evdev 127 + xkb's 8 = code:135, both edges through the shipped binds.
        nest.kb.key(127, True)
        started = E.wait_for(lambda: call("status").get("state") == "listening", 8)
        check("holding Menu starts recording through the default bind", started)
        daemon_pid = call("status").get("pid")
        check("the overlay appears", E.wait_for(lambda: nest.layer("bromigos-dictation"), 5))
        check("the focused application stays selected", json.loads(nest.ctl("activewindow", "-j"))["address"] == target)
        check("the live preview arrives before release", E.wait_for(lambda: call("status").get("characters", 0) > 0, 8))
        check("the audio meter receives the synthetic microphone", call("status").get("level", 0) > .1)
        layers = json.loads(nest.ctl("layers", "-j"))
        layer = next(l for mon in layers.values() for group in mon["levels"].values() for l in group
                     if l.get("namespace") == "bromigos-dictation")
        monitor = next(m for m in json.loads(nest.ctl("monitors", "-j")) if m.get("focused"))
        logical_width = monitor["width"] / monitor["scale"]
        if shots:
            os.makedirs(shots, exist_ok=True)
            with open(os.path.join(shots, "geometry.json"), "w") as f:
                json.dump({"x": layer["x"], "y": layer["y"], "w": layer["w"], "h": layer["h"],
                           "scale": monitor["scale"]}, f)
        check("the overlay is top-centre", abs(layer["x"] - (logical_width - layer["w"]) / 2) <= 3
              and 30 <= layer["y"] <= 60)
        check("no text is inserted while the key is held", state()["text"] == "Start:  end.")
        nest.shot("dictation-listening")
        nest.kb.key(127, False)
        expected = "Start: " + WORDS + " end."
        check("release inserts Unicode and punctuation at the original cursor",
              E.wait_for(lambda: state().get("text") == expected, 8))
        check("the overlay disappears after insertion", E.wait_for(lambda: not nest.layer("bromigos-dictation"), 5))
        pasted = subprocess.run(["wl-paste", "--no-newline"], env=nest.env, capture_output=True, timeout=3)
        check("the clipboard stays unchanged", pasted.stdout == b"Clipboard stays unchanged")
        check("speech snapshots are removed", not any(name.endswith(".pcm") for name in os.listdir(
            os.path.join(nest.run, "bromigos-dictation", "wayland-1"))))
        with open(os.path.join(nest.run, "synthetic-microphone.log")) as f:
            check("release closes the microphone", f.read().splitlines() == ["on", "off"])
        nest.shot("dictation-inserted")
        # An in-flight preview after cancel cannot insert or bring the overlay back.
        voice.delay = .8
        voice.entered.clear()
        nest.kb.key(127, True)
        check("another hold starts a fresh recording", E.wait_for(lambda: call("status").get("state") == "listening", 5))
        check("the delayed speech request is in flight", voice.entered.wait(5))
        call("cancel")
        nest.kb.key(127, False)
        time.sleep(1)
        check("cancel hides the overlay and discards the response", not nest.layer("bromigos-dictation")
              and state().get("text") == expected)
        with open(os.path.join(nest.run, "synthetic-microphone.log")) as f:
            check("cancel closes the microphone", f.read().splitlines() == ["on", "off", "on", "off"])
        # A terminal is a different real app; no Enter is synthesized or required.
        terminal = subprocess.Popen(["kitty", "--config", "NONE", "--override", "confirm_os_window_close=0",
            "/usr/bin/python", os.path.join(nest.stubs, "terminal.py")], env=nest.env,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
        nest.procs.append(terminal)
        terminal_state = nest.base["DICTATION_TERMINAL_STATE"]
        ready = E.wait_for(lambda: os.path.exists(terminal_state) and
                          json.loads(nest.ctl("activewindow", "-j") or "{}").get("class") == "kitty", 8)
        check("a real terminal is selected in the nest", ready)
        if ready:
            voice.delay = .05
            nest.kb.key(127, True)
            E.wait_for(lambda: call("status").get("state") == "listening", 5)
            time.sleep(.7)
            nest.kb.key(127, False)
            def terminal_text():
                try:
                    with open(terminal_state) as f: return json.load(f).get("text")
                except (OSError, ValueError): return None
            check("dictation also inserts Unicode into a terminal without Enter",
                  E.wait_for(lambda: terminal_text() == WORDS, 8))
        # rofi's dump needs a display on some versions; use only this private one.
        rofi = subprocess.run(["/usr/bin/python", "-m", "unittest",
            "test_keys.TitleThemeTest.test_rofi_reads_the_title"],
            env=dict(nest.env, PYTHONPATH=os.path.join(REPO, "desktop", "lib") + os.pathsep + HERE),
            capture_output=True, text=True, timeout=30)
        check("the existing rofi theme reader works offscreen", rofi.returncode == 0)
    finally:
        if daemon_pid:
            try:
                os.kill(daemon_pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
            E.wait_for(lambda: not os.path.exists(os.path.join(nest.run, "bromigos-dictation", "wayland-1", "control.sock")), 4)
        voice.close()
        nest.stop()
    print(f"{sum(results)}/{len(results)} checks pass", flush=True)
    return 0 if all(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
