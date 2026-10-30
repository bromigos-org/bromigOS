"""`bromigos bluetooth session`: the desktop's bluez core (bromigos_bluez) for a program in
another language, one JSON document per line on stdin and stdout (package bromigos-desktop,
/usr/lib/bromigos/lib). The Bluetooth TUI (`bromigos bluetooth tui`, Rust) runs it, so the
bar, the panel, the TUI and Settings share one bluez code.

Out, each a line:
  {"t": "kinds", "kinds": [{"name", "glyph", "steps"}]}   first: what the pairing wizard
                                           offers and each kind's pair-mode steps
  {"t": "state", "state": {…}}            whenever bluez or PipeWire change: bromigos_bluez's
                                           state, plus "audio" (PipeWire's Bluetooth cards, by
                                           address), "sound" (each device's output and input,
                                           and the defaults) and "xpadneo"
  {"t": "reply", "id": N, "ok": …, "error": …, "said": …}   the answer to a request
  {"t": "step", "id": N, "step": "pairing" | "trusting" | "connecting"}
  {"t": "prompt", "pid": "p1", "what": …, "mac": …, "name": …, "value": …}   the pairing
                                           agent's question (bromigos_bluez.Agent's whats)
  {"t": "cancel"}                          the device gave up pairing
  {"t": "input", "mac": …, "buttons": […], "axes": {…}}     a controller's input, live
  {"t": "mic", "level": 0..1}             a microphone's level, live

In, each a line:
  {"id": N, "do": "power" | "discoverable" | "scan", "on": true}
  {"id": N, "do": "connect" | "disconnect" | "pair" | "cancel-pair" | "forget", "mac": …}
  {"id": N, "do": "trust", "mac": …, "on": true}     {"id": N, "do": "rename", "mac": …, "name": …}
  {"id": N, "do": "profile", "mac": …, "mode": "hifi" | "headset"}
  {"id": N, "do": "sound-default", "side": "output" | "input", "name": …}
  {"id": N, "do": "reset"}                 the adapter off, its rfkill block lifted, on again
  {"id": N, "do": "input", "mac": …}  {"do": "input-stop"}  {"id": N, "do": "rumble", "mac": …}
  {"id": N, "do": "mic", "source": …}  {"do": "mic-stop"}
  {"answer": "p1", "value": …}             the reply to a prompt (null or false: no)

Errors are bromigos_bluez.explain's plain words. EOF on stdin ends the session.
"""
import json
import math
import os
import struct
import sys

HERE = os.path.dirname(os.path.realpath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import bromigos_bluez as B  # noqa: E402
import bromigos_gamepad as G  # noqa: E402


def level(chunk):
    """Signed 16-bit mono samples -> a 0..1 level: the RMS in dBFS, -60 dB to 0 dB."""
    n = len(chunk) // 2
    if n == 0:
        return 0.0
    vals = struct.unpack(f"<{n}h", chunk[:n * 2])
    rms = math.sqrt(sum(v * v for v in vals) / n) / 32768
    if rms <= 0:
        return 0.0
    db = 20 * math.log10(rms)
    return round(max(0.0, min(1.0, (db + 60) / 60)), 3)


def sound_of(sinks, sources, info):
    """Each Bluetooth device's output and input (by address) and the defaults, from pactl's
    short lists and its info."""
    out = {"defaults": {"output": (info or {}).get("default_sink_name"),
                        "input": (info or {}).get("default_source_name")}, "devices": {}}
    for side, items in (("output", sinks), ("input", sources)):
        for s in items or []:
            name = s.get("name", "")
            if not name.startswith(("bluez_output.", "bluez_input.", "bluez_source.", "bluez_sink.")):
                continue
            if name.endswith(".monitor"):
                continue
            mac = name.split(".", 1)[1][:17].replace("_", ":").upper()
            out["devices"].setdefault(mac, {})[side] = name
    return out


class Session:
    def __init__(self, out=sys.stdout, bz=None):
        from gi.repository import Gio, GLib
        self.Gio, self.GLib = Gio, GLib
        self.out = out
        self.bz = bz or B.Bluez(self.changed)
        if bz is not None:
            bz.on_change = self.changed
        self.prompts = {}
        self.n = 0
        self.audio, self.sound = {}, {"defaults": {}, "devices": {}}
        self.connected = None
        self.pad = None
        self.pad_watch = None
        self.pad_last = None
        self.mic = None
        self.loop = None

    # -- out
    def send(self, doc):
        self.out.write(json.dumps(doc) + "\n")
        self.out.flush()

    def changed(self, st=None):
        st = st or self.bz.state()
        conn = sorted(d["mac"] for d in st.get("connected", []))
        if conn != self.connected:
            self.connected = conn
            self.refresh_audio()
        self.send({"t": "state", "state": dict(st, audio=self.audio, sound=self.sound, xpadneo=B.xpadneo_loaded())})

    def refresh_audio(self):
        def run(argv, then):
            try:
                p = self.Gio.Subprocess.new(argv, self.Gio.SubprocessFlags.STDOUT_PIPE |
                                            self.Gio.SubprocessFlags.STDERR_SILENCE)
            except Exception:
                then(None)
                return

            def done(proc, res):
                try:
                    _, text, _ = proc.communicate_utf8_finish(res)
                    then(json.loads(text or "null"))
                except Exception:
                    then(None)
            p.communicate_utf8_async(None, None, done)
        got = {}

        def part(key):
            def back(doc):
                got[key] = doc
                if len(got) == 4:
                    self.audio = B.audio_cards(got["cards"] or [])
                    self.sound = sound_of(got["sinks"], got["sources"], got["info"])
                    st = self.bz.state()
                    self.send({"t": "state", "state": dict(st, audio=self.audio, sound=self.sound,
                                                           xpadneo=B.xpadneo_loaded())})
            return back
        for key, argv in (("cards", ["list", "cards"]), ("sinks", ["list", "short", "sinks"]),
                          ("sources", ["list", "short", "sources"]), ("info", ["info"])):
            run(["pactl", "--format=json", *argv], part(key))

    # -- in
    def line(self, text):
        try:
            msg = json.loads(text)
        except ValueError:
            self.send({"t": "reply", "id": None, "ok": False, "error": "not JSON"})
            return
        if "answer" in msg:
            reply = self.prompts.pop(msg["answer"], None)
            if reply is not None:
                reply(msg.get("value"))
            return
        rid, do = msg.get("id"), msg.get("do")

        def back(ok, err=None, said=None):
            self.send({"t": "reply", "id": rid, "ok": bool(ok), "error": err, "said": said})
            if do in ("profile", "sound-default"):
                self.refresh_audio()
        d = self.bz.find(msg["mac"]) if msg.get("mac") else None
        if msg.get("mac") and d is None and do not in ("input", "rumble"):
            back(False, "That device is gone: scan again")
            return
        bz = self.bz
        try:
            if do == "power":
                bz.power(bool(msg.get("on")), back)
            elif do == "discoverable":
                bz.discoverable(bool(msg.get("on")), back)
            elif do == "scan":
                bz.scan(bool(msg.get("on")), back)
            elif do == "connect":
                bz.connect(d["path"], back)
            elif do == "disconnect":
                bz.disconnect(d["path"], back)
            elif do == "trust":
                bz.trust(d["path"], bool(msg.get("on")), back)
            elif do == "rename":
                name = (msg.get("name") or "").strip()
                if not name:
                    back(False, "A name can't be empty")
                else:
                    bz.rename(d["path"], name, back)
            elif do == "forget":
                bz.forget(d["path"], back)
            elif do == "pair":
                self.pair(d, rid, back)
            elif do == "cancel-pair":
                bz.cancel_pair(d["path"])
                back(True)
            elif do == "profile":
                self.cli(["bromigos", "bluetooth", "profile", d["mac"], msg.get("mode", ""), "--json"], back)
            elif do == "sound-default":
                self.cli(["bromigos", "sound", msg.get("side", "output"), msg.get("name", ""), "--json"], back)
            elif do == "reset":
                self.reset(back)
            elif do == "input":
                self.input(msg.get("mac", ""), back)
            elif do == "input-stop":
                self.input_stop()
                back(True)
            elif do == "rumble":
                self.rumble(msg.get("mac", ""), back)
            elif do == "mic":
                self.mic_start(msg.get("source", ""), back)
            elif do == "mic-stop":
                self.mic_stop()
                back(True)
            else:
                back(False, f"unknown request {do!r}")
        except Exception as e:      # never leave the client waiting
            back(False, B.explain(e))

    def cli(self, argv, back):
        try:
            p = self.Gio.Subprocess.new(argv, self.Gio.SubprocessFlags.STDOUT_PIPE |
                                        self.Gio.SubprocessFlags.STDERR_SILENCE)
        except Exception as e:
            back(False, str(e))
            return

        def done(proc, res):
            try:
                _, text, _ = proc.communicate_utf8_finish(res)
                doc = json.loads(text or "{}")
            except Exception as e:
                back(False, str(e))
                return
            ok = doc.get("ok", True)
            back(ok, None if ok else doc.get("error"), doc.get("said"))
        p.communicate_utf8_async(None, None, done)

    def pair(self, d, rid, back):
        def go(ok=True, err=None):
            if not ok:
                back(False, err)
                return
            self.bz.pair(d["path"], back, lambda s: self.send({"t": "step", "id": rid, "step": s}))
        if self.bz.agent is None:
            self.bz.register_agent(B.Agent(self), go)
        else:
            go()

    # the agent's UI: questions go to the client
    def prompt(self, what, path, value, reply):
        self.n += 1
        pid = f"p{self.n}"
        d = next((x for x in self.bz.state()["devices"] if x["path"] == path), None)
        self.prompts[pid] = reply
        self.send({"t": "prompt", "pid": pid, "what": what, "mac": B.mac_of(path), "name": d["name"] if d else "",
                   "value": list(value) if isinstance(value, tuple) else value})

    def cancel(self):
        self.prompts.clear()
        self.send({"t": "cancel"})

    def reset(self, back):
        self.bz.reset(lambda ok, err: back(ok, err, "The adapter was switched off and on again" if ok else None))

    # -- a controller's input and rumble
    def input(self, mac, back):
        self.input_stop()
        path = G.find(mac)
        if path is None:
            back(False, "Its input device isn't there: is it connected and switched on?")
            return
        try:
            self.pad = G.Pad(path)
        except OSError as e:
            back(False, f"Can't read {path}: {e.strerror}")
            return
        self.pad.mac = mac
        self.pad_watch = self.GLib.io_add_watch(self.pad.fd, self.GLib.PRIORITY_DEFAULT,
                                                self.GLib.IOCondition.IN | self.GLib.IOCondition.HUP |
                                                self.GLib.IOCondition.ERR, self._pad)
        back(True, None, path)
        self._send_pad(force=True)

    def _pad(self, fd, cond):
        if cond & (self.GLib.IOCondition.HUP | self.GLib.IOCondition.ERR):
            self.send({"t": "input-error", "error": "The controller went away"})
            self.input_stop(keep_watch=True)
            return False
        try:
            self.pad.read()
        except OSError:
            self.send({"t": "input-error", "error": "The controller went away"})
            self.input_stop(keep_watch=True)
            return False
        self._send_pad()
        return True

    def _send_pad(self, force=False):
        doc = {"t": "input", "mac": self.pad.mac, "buttons": self.pad.buttons, "axes": self.pad.axes}
        key = json.dumps(doc, sort_keys=True)
        if force or key != self.pad_last:
            self.pad_last = key
            self.send(doc)

    def input_stop(self, keep_watch=False):
        if self.pad_watch is not None and not keep_watch:
            self.GLib.source_remove(self.pad_watch)
        self.pad_watch = None
        if self.pad is not None:
            self.pad.close()
            self.pad = None

    def rumble(self, mac, back):
        pad, temp = self.pad, None
        if pad is None or pad.mac != mac:
            path = G.find(mac)
            if path is None:
                back(False, "Its input device isn't there: is it connected and switched on?")
                return
            pad = temp = G.Pad(path)
        ok = pad.rumble(0.7, 0.7, 450)
        if temp is not None:
            self.GLib.timeout_add(600, lambda: temp.close() and False)
        back(ok, None if ok else "Its driver doesn't rumble: xpadneo does (bromigos peripheral enable xbox-controller)",
             "Rumbling" if ok else None)

    # -- a microphone's level
    def mic_start(self, source, back):
        self.mic_stop()
        argv = ["parec", "--raw", "--format=s16le", "--rate=16000", "--channels=1", "--latency-msec=50"]
        if source:
            argv += ["-d", source]
        try:
            self.mic = self.Gio.Subprocess.new(argv, self.Gio.SubprocessFlags.STDOUT_PIPE |
                                               self.Gio.SubprocessFlags.STDERR_SILENCE)
        except Exception as e:
            back(False, f"parec: {e}")
            return
        stream = self.mic.get_stdout_pipe()
        mic = self.mic

        def got(s, res):
            if self.mic is not mic:
                return
            try:
                data = s.read_bytes_finish(res).get_data()
            except Exception:
                data = b""
            if not data:
                self.mic_stop()
                return
            self.send({"t": "mic", "level": level(data)})
            s.read_bytes_async(1600, self.GLib.PRIORITY_DEFAULT, None, got)
        stream.read_bytes_async(1600, self.GLib.PRIORITY_DEFAULT, None, got)
        back(True)

    def mic_stop(self):
        if self.mic is not None:
            self.mic.force_exit()
            self.mic = None

    # -- the loop
    def run(self, stdin=None):
        self.loop = self.GLib.MainLoop()
        self.send({"t": "kinds", "kinds": [{"name": n, "glyph": g, "steps": st} for n, g, st in B.PAIR_KINDS]})
        try:
            self.bz.start()
        except Exception:
            pass
        if self.bz.conn is None:
            self.send({"t": "state", "state": dict(B.unavailable(), audio={}, sound=self.sound, xpadneo=False)})
        else:
            self.changed()
        fd = (stdin or sys.stdin).fileno()
        data = self.Gio.DataInputStream.new(self.Gio.UnixInputStream.new(fd, False))

        def got(s, res):
            try:
                text, _ = s.read_line_finish_utf8(res)
            except Exception:
                text = None
            if text is None:
                self.loop.quit()
                return
            if text.strip():
                self.line(text)
            s.read_line_async(self.GLib.PRIORITY_DEFAULT, None, got)
        data.read_line_async(self.GLib.PRIORITY_DEFAULT, None, got)
        self.loop.run()
        self.input_stop()
        self.mic_stop()
        if self.bz.agent is not None:
            self.bz.unregister_agent()
        return 0
