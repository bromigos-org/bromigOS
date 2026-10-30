"""One mouse click handed on to whatever is under the pointer (package bromigos-desktop,
/usr/lib/bromigos/lib), for the bar's popups: the clear surface that closes a popup on a
click elsewhere takes that click, so once it's gone the click is given again, where the
pointer is, to whatever was clicked (another bar module, a window, the desktop).

It is the compositor's virtual pointer (zwlr_virtual_pointer_v1, which Hyprland and other
wlroots-style compositors offer): a button down and up, nothing else. The pointer doesn't
move. A bare Wayland client, a few requests on a connection of its own; the tests' vptr.py
is the same wire with motion and drags.

    click(BTN_LEFT)   True when the compositor took it; False when there's no Wayland
                      display or no virtual pointer (the popup has closed either way)
"""
import os
import socket
import struct
import time

BTN_LEFT, BTN_RIGHT, BTN_MIDDLE = 0x110, 0x111, 0x112


class _Client:
    def __init__(self, path):
        self.s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.s.settimeout(2)
        self.s.connect(path)
        self.next, self.buf = 2, b""

    def id(self):
        i = self.next
        self.next += 1
        return i

    def send(self, obj, op, payload=b""):
        self.s.sendall(struct.pack("<II", obj, ((8 + len(payload)) << 16) | op) + payload)

    @staticmethod
    def string(payload, off):
        n, = struct.unpack_from("<I", payload, off)
        return payload[off + 4:off + 4 + n - 1].decode(), off + 4 + n + ((4 - n % 4) % 4)

    def roundtrip(self):
        cb = self.id()
        self.send(1, 0, struct.pack("<I", cb))                  # wl_display.sync
        events = []
        while True:
            while len(self.buf) < 8:
                chunk = self.s.recv(65536)
                if not chunk:
                    raise OSError("the compositor closed the connection")
                self.buf += chunk
            obj, word = struct.unpack_from("<II", self.buf)
            size, op = word >> 16, word & 0xFFFF
            while len(self.buf) < size:
                chunk = self.s.recv(65536)
                if not chunk:
                    raise OSError("the compositor closed the connection")
                self.buf += chunk
            payload, self.buf = self.buf[8:size], self.buf[size:]
            if obj == 1 and op == 0:                             # wl_display.error
                raise OSError("wayland error: " + self.string(payload, 8)[0])
            if obj == cb and op == 0:
                return events
            events.append((obj, op, payload))

    def bind(self, reg, globs, iface, version):
        name, ver = globs[iface]
        new = self.id()
        b = iface.encode() + b"\0"
        self.send(reg, 0, struct.pack("<I", name) + struct.pack("<I", len(b)) + b + b"\0" * ((4 - len(b) % 4) % 4)
                  + struct.pack("<II", min(version, ver), new))
        return new


def _socket():
    d = os.environ.get("WAYLAND_DISPLAY")
    if not d:
        return None
    return d if d.startswith("/") else os.path.join(os.environ.get("XDG_RUNTIME_DIR", ""), d)


def click(button=BTN_LEFT):
    path = _socket()
    if not path:
        return False
    try:
        c = _Client(path)
    except OSError:
        return False
    try:
        reg = c.id()
        c.send(1, 1, struct.pack("<I", reg))                     # wl_display.get_registry
        globs = {}
        for obj, op, payload in c.roundtrip():
            if obj == reg and op == 0:
                name, = struct.unpack_from("<I", payload)
                iface, off = c.string(payload, 4)
                globs[iface] = (name, struct.unpack_from("<I", payload, off)[0])
        if "zwlr_virtual_pointer_manager_v1" not in globs or "wl_seat" not in globs:
            return False
        seat = c.bind(reg, globs, "wl_seat", 1)
        mgr = c.bind(reg, globs, "zwlr_virtual_pointer_manager_v1", 1)
        ptr = c.id()
        c.send(mgr, 0, struct.pack("<II", seat, ptr))             # create_virtual_pointer
        ms = int(time.monotonic() * 1000) & 0xFFFFFFFF
        for down in (1, 0):
            c.send(ptr, 2, struct.pack("<III", ms, button, down))  # button
            c.send(ptr, 4)                                         # frame
            c.roundtrip()
            ms = (ms + 40) & 0xFFFFFFFF
            time.sleep(0.02)
        c.send(ptr, 8)                                             # destroy
        c.roundtrip()
        return True
    except (OSError, struct.error, ValueError):
        return False
    finally:
        c.s.close()
