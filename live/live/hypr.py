"""Hyprland IPC without spawning hyprctl: request socket for state queries,
event socket (socket2) on a thread for workspace/fullscreen/window events."""
import json
import os
import socket
import threading
import time


def _alive(path):
    """True when a Hyprland instance answers on this request socket. A dead instance
    leaves its socket file behind, so existence alone isn't enough."""
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
            s.settimeout(0.5)
            s.connect(path)
        return True
    except OSError:
        return False


_cache = {"sig": None}


def _sig():
    """The live Hyprland instance: the cached one or $HYPRLAND_INSTANCE_SIGNATURE if it
    still answers, else the newest instance dir whose socket answers. A daemon started from
    a shell that outlived a Hyprland restart inherits a dead signature; this follows the
    session instead of sticking to it."""
    base = os.path.join(os.environ.get("XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}"), "hypr")
    for sig in (_cache["sig"], os.environ.get("HYPRLAND_INSTANCE_SIGNATURE")):
        if sig and _alive(os.path.join(base, sig, ".socket.sock")):
            _cache["sig"] = sig
            return base, sig
    try:
        dirs = sorted((os.path.join(base, d) for d in os.listdir(base)), key=os.path.getmtime, reverse=True)
        for d in dirs:
            if _alive(os.path.join(d, ".socket.sock")):
                _cache["sig"] = os.path.basename(d)
                os.environ["HYPRLAND_INSTANCE_SIGNATURE"] = _cache["sig"]   # for child hyprctl calls too
                return base, _cache["sig"]
    except OSError:
        pass
    return base, _cache["sig"] or os.environ.get("HYPRLAND_INSTANCE_SIGNATURE", "")


def request(cmd, as_json=True):
    base, sig = _sig()
    path = os.path.join(base, sig, ".socket.sock")
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
            s.settimeout(1.0)
            s.connect(path)
            s.sendall((("j/" if as_json else "") + cmd).encode())
            chunks = []
            while True:
                b = s.recv(65536)
                if not b:
                    break
                chunks.append(b)
        out = b"".join(chunks).decode(errors="replace")
        return json.loads(out) if as_json else out
    except (OSError, ValueError):
        return None


def dispatch(lua, *old):
    """Run a dispatcher: its Lua form (hl.dsp.*, for hyprland.lua) or, when Hyprland is on
    the old hyprland.conf (it answers the Lua form "Invalid dispatcher"), the old one.
    True when Hyprland says ok."""
    out = request("dispatch " + lua, as_json=False)
    if out == "Invalid dispatcher" and old:
        out = request("dispatch " + " ".join(old), as_json=False)
    return out == "ok"


def monitor_state(name):
    """(active workspace has windows, a client there is in TRUE fullscreen, monitor).
    Maximize (fullscreen mode 1) does not count: the layer still shows in the gaps."""
    mons = request("monitors") or []
    mon = next((m for m in mons if m.get("name") == name), None)
    if not mon:
        return False, False, None
    ids = {(mon.get("activeWorkspace") or {}).get("id")}
    special = (mon.get("specialWorkspace") or {}).get("id") or 0
    if special:
        ids.add(special)
    windows = full = False
    for c in request("clients") or []:
        if (c.get("workspace") or {}).get("id") in ids and c.get("mapped", True) and not c.get("hidden"):
            windows = True
            if c.get("fullscreen") == 2:
                full = True
    return windows, full, mon


def resolve_monitor(name):
    """The output to draw on: lib/bromigos_monitors.primary (the setting when that output is
    there, else setup's primary, the focused, the first); `name` when Hyprland can't be asked."""
    mons = request("monitors") or []
    try:
        import bromigos_monitors
        return bromigos_monitors.primary(mons, name)
    except ImportError:                        # an older bromigos-core: the first output
        names = [m.get("name") for m in mons if m.get("name")]
        if name and name in names:
            return name
        return (min(mons, key=lambda m: m.get("id", 0)).get("name") if mons else None) or name


def layers_on(name):
    data = request("layers") or {}
    return (data.get(name) or {}).get("levels", {})


class Events(threading.Thread):
    def __init__(self, cb):
        super().__init__(daemon=True, name="hypr-events")
        self.cb = cb

    def run(self):
        while True:
            base, sig = _sig()
            path = os.path.join(base, sig, ".socket2.sock")
            try:
                with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
                    s.connect(path)
                    buf = b""
                    while True:
                        b = s.recv(4096)
                        if not b:
                            break
                        buf += b
                        while b"\n" in buf:
                            line, buf = buf.split(b"\n", 1)
                            ev, _, arg = line.decode(errors="replace").partition(">>")
                            self.cb(ev, arg)
            except OSError:
                pass
            time.sleep(2)
