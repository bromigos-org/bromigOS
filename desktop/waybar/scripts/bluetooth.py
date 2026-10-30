#!/usr/bin/env python3
"""Waybar Bluetooth module (docs/desktop.md, "The bar's Bluetooth"): the glyph dim while
Bluetooth is off and lit while it's on, a small count of the devices connected, and a
battery sliver under the glyph for the main one (a controller, else a headset). Amber,
steady, when that battery is at 15% or under. Hidden on a machine with no adapter.

It runs for as long as the bar does and prints a line whenever bluez says something
changed (D-Bus signals: no polling). DRIFTGLASS EMBER (docs/DRIFTGLASS.md): a connect or a
disconnect gives one Spark, about a second; a scan or a pairing blinks slowly until it
ends. With reduced motion (bromigos accessibility motion reduced) neither moves.

One copy (the first bar's, by a lock in $XDG_RUNTIME_DIR) also sends the quiet "connected"
and "disconnected" toasts, and makes a headset or speaker the sound output when it
connects (Settings › Bluetooth can turn that off).
click: the Bluetooth panel · right-click: the quick menu · middle-click: on or off."""
import fcntl
import json
import os
import sys
import time

sys.path.insert(0, "/usr/lib/bromigos/lib")
sys.path.insert(0, os.path.join(os.path.dirname(os.path.realpath(__file__)), "..", "..", "lib"))
sys.path.insert(1, os.path.join(os.path.dirname(os.path.realpath(__file__)), "..", "..", "..", "lib"))
import bromigos_bluez as B  # noqa: E402

SPARK = 1.2         # seconds a connect or disconnect's Spark lasts
RUNTIME = os.environ.get("XDG_RUNTIME_DIR") or f"/run/user/{os.getuid()}"
BUSY = os.path.join(RUNTIME, "bromigos-bluetooth-busy")      # the panel holds it while pairing


def motion():
    try:
        import bromigos_theme as T
        return T.motion()
    except Exception:
        return "full"


def leader():
    """True for the one copy that sends toasts (several bars run several copies)."""
    try:
        f = open(os.path.join(RUNTIME, "bromigos-bluetooth-bar.lock"), "w")
        fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        return None
    return f            # kept open: the lock lasts as long as this process


def busy():
    try:
        return time.time() - os.path.getmtime(BUSY) < 120
    except OSError:
        return False


class Module:
    def __init__(self, out=sys.stdout, lead=None, now=time.monotonic, later=None):
        self.out, self.lead, self.now = out, lead, now
        self.seen = None            # {mac: connected} after the first state
        self.spark_until = 0.0
        self.last = None
        self.state = None
        self.later = later or (lambda secs: None)

    def changed(self, st):
        """bluez's state changed: note connects and disconnects, then print."""
        conn = {d["mac"]: d for d in st.get("connected", [])}
        if self.seen is not None:
            came = [d for m, d in conn.items() if m not in self.seen]
            went = [self.seen[m] for m in self.seen if m not in conn]
            if came or went:
                self.spark_until = self.now() + SPARK
                self.later(SPARK + 0.05)        # the Spark ends: print again
                if self.lead:
                    for d in came:
                        self.connected(d)
                    for d in went:
                        B.notify(d["name"], "disconnected", B.ICON.get(d["glyph"], "bt-dev"), tag=f"bt-{d['mac']}")
        self.seen = conn
        self.state = st
        self.emit()

    def connected(self, d):
        b = d.get("battery")
        B.notify(d["name"], "connected" + (f" · battery {b}%" if b is not None else ""),
                 B.ICON.get(d["glyph"], "bt-dev"), tag=f"bt-{d['mac']}")
        if d.get("audio") and not d.get("audio_source") and B.settings()["audio_default"]:
            audio_default(d["mac"])

    def doc(self):
        if self.state is None:
            return None
        return B.bar(self.state, motion(), spark=self.now() < self.spark_until, busy=busy())

    def emit(self):
        d = self.doc()
        if d is None:
            return
        line = json.dumps(d)
        if line != self.last:
            self.last = line
            self.out.write(line + "\n")
            self.out.flush()


def audio_default(mac, tries=16):
    """Make the device's sound output the default once PipeWire has it (it appears a moment
    after bluez says connected): `bromigos sound output`, as Settings › Sound does."""
    from gi.repository import GLib
    import subprocess
    want = "bluez_output." + mac.replace(":", "_").upper()

    def look():
        nonlocal tries
        tries -= 1
        try:
            r = subprocess.run(["pactl", "--format=json", "list", "short", "sinks"], capture_output=True,
                               text=True, timeout=4)
            sinks = json.loads(r.stdout or "[]")
        except (OSError, subprocess.SubprocessError, ValueError):
            return False
        name = next((s.get("name") for s in sinks if str(s.get("name", "")).upper().startswith(want.upper())), None)
        if name:
            subprocess.run(["bromigos", "sound", "output", name], capture_output=True, timeout=8)
            return False
        return tries > 0
    GLib.timeout_add(500, look)


def main():
    from gi.repository import Gio, GLib
    def later(secs):
        GLib.timeout_add(int(secs * 1000), lambda: m.emit() or False)
    m = Module(lead=leader(), later=later)
    bz = B.Bluez(m.changed)
    try:
        bz.start()
    except Exception:
        # no system bus to reach (a container): nothing to show
        print(json.dumps(B.bar(B.unavailable())), flush=True)
        GLib.MainLoop().run()
        return
    m.changed(bz.state())

    # the panel's pairing marker comes and goes (a stale one, from a panel that died, stops
    # counting after two minutes)
    def marker(mon, f, other, event):
        if f.get_basename() == os.path.basename(BUSY):
            m.emit()
            later(121)
    mon = Gio.File.new_for_path(RUNTIME).monitor_directory(Gio.FileMonitorFlags.NONE, None)
    mon.connect("changed", marker)
    GLib.MainLoop().run()


if __name__ == "__main__":
    main()
