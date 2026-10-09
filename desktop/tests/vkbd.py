"""A virtual keyboard for a test compositor: types into a nested or headless Hyprland
(zwp_virtual_keyboard_v1, which Hyprland treats like a keyboard: its binds see it) without
touching any real input device. A bare Wayland client: the wire protocol over the socket,
the keymap compiled by libxkbcommon (the default, us). Used by e2e_keys_nested.py.

    kb = VirtualKeyboard("/run/user/1000/wayland-9")
    kb.combo("SUPER + SHIFT + W")      press the modifiers, the key, let go
    kb.tap("ESCAPE")
    kb.type("desktop panels")
"""
import array
import ctypes
import ctypes.util
import os
import socket
import struct
import time

# evdev key codes (linux/input-event-codes.h) of a us keyboard
KEYS = {"ESCAPE": 1, "BACKSPACE": 14, "TAB": 15, "RETURN": 28, "ENTER": 28, "SPACE": 57, "MINUS": 12,
        "SLASH": 53, "PERIOD": 52, "COMMA": 51, "F1": 59, "F2": 60, "F12": 88,
        "LEFT": 105, "RIGHT": 106, "UP": 103, "DOWN": 108, "PAGEUP": 104, "PAGEDOWN": 109, "HOME": 102,
        "END": 107}
for _i, _c in enumerate("1234567890"):
    KEYS[_c] = 2 + _i
for _row, _start in (("qwertyuiop", 16), ("asdfghjkl", 30), ("zxcvbnm", 44)):
    for _i, _c in enumerate(_row):
        KEYS[_c.upper()] = _start + _i
MODS = {"SHIFT": (42, 1), "CTRL": (29, 4), "ALT": (56, 8), "SUPER": (125, 64)}
CHARS = {" ": "SPACE", "-": "MINUS", "/": "SLASH", ".": "PERIOD", ",": "COMMA"}


def keymap_text():
    x = ctypes.CDLL(ctypes.util.find_library("xkbcommon") or "libxkbcommon.so.0")
    x.xkb_context_new.restype = ctypes.c_void_p
    x.xkb_keymap_new_from_names.restype = ctypes.c_void_p
    x.xkb_keymap_new_from_names.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_int]
    x.xkb_keymap_get_as_string.restype = ctypes.c_void_p
    x.xkb_keymap_get_as_string.argtypes = [ctypes.c_void_p, ctypes.c_int]
    ctx = x.xkb_context_new(0)
    km = x.xkb_keymap_new_from_names(ctx, None, 0)
    ptr = x.xkb_keymap_get_as_string(km, 1)
    return ctypes.string_at(ptr)


class VirtualKeyboard:
    def __init__(self, path, delay=0.03):
        self.s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.s.connect(path)
        self.delay = delay
        self.next = 2
        self.buf = b""
        self.t0 = time.monotonic()
        reg = self._id()
        self._send(1, 1, struct.pack("<I", reg))          # wl_display.get_registry
        globs = {}
        for obj, op, payload in self._roundtrip():
            if obj == reg and op == 0:
                name, = struct.unpack_from("<I", payload)
                iface, off = self._string(payload, 4)
                ver, = struct.unpack_from("<I", payload, off)
                globs[iface] = (name, ver)
        if "zwp_virtual_keyboard_manager_v1" not in globs:
            raise RuntimeError("the compositor has no virtual keyboard protocol")
        seat = self._bind(reg, globs, "wl_seat", 1)
        mgr = self._bind(reg, globs, "zwp_virtual_keyboard_manager_v1", 1)
        self.kb = self._id()
        self._send(mgr, 0, struct.pack("<II", seat, self.kb))   # create_virtual_keyboard
        km = keymap_text() + b"\0"
        fd = os.memfd_create("keymap")
        os.write(fd, km)
        self._send(self.kb, 0, struct.pack("<II", 1, len(km)), fds=[fd])   # keymap (xkb v1)
        os.close(fd)
        self._roundtrip()
        self.mods = 0

    # -- the wire
    def _id(self):
        i = self.next
        self.next += 1
        return i

    def _send(self, obj, op, payload=b"", fds=()):
        msg = struct.pack("<II", obj, ((8 + len(payload)) << 16) | op) + payload
        if fds:
            self.s.sendmsg([msg], [(socket.SOL_SOCKET, socket.SCM_RIGHTS, array.array("i", fds))])
        else:
            self.s.sendall(msg)

    @staticmethod
    def _pack_string(s):
        b = s.encode() + b"\0"
        return struct.pack("<I", len(b)) + b + b"\0" * ((4 - len(b) % 4) % 4)

    @staticmethod
    def _string(payload, off):
        n, = struct.unpack_from("<I", payload, off)
        s = payload[off + 4:off + 4 + n - 1].decode()
        return s, off + 4 + n + ((4 - n % 4) % 4)

    def _bind(self, reg, globs, iface, version):
        name, ver = globs[iface]
        new = self._id()
        self._send(reg, 0, struct.pack("<I", name) + self._pack_string(iface) +
                   struct.pack("<II", min(version, ver), new))
        return new

    def _roundtrip(self):
        cb = self._id()
        self._send(1, 0, struct.pack("<I", cb))            # wl_display.sync
        events = []
        while True:
            while len(self.buf) < 8:
                chunk = self.s.recv(65536)
                if not chunk:
                    raise RuntimeError("the compositor closed the connection")
                self.buf += chunk
            obj, word = struct.unpack_from("<II", self.buf)
            size, op = word >> 16, word & 0xFFFF
            while len(self.buf) < size:
                self.buf += self.s.recv(65536)
            payload, self.buf = self.buf[8:size], self.buf[size:]
            if obj == 1 and op == 0:
                _, code = struct.unpack_from("<II", payload)
                msg, _ = self._string(payload, 8)
                raise RuntimeError(f"wayland error {code}: {msg}")
            if obj == cb and op == 0:
                return events
            events.append((obj, op, payload))

    # -- keys
    def _ms(self):
        return int((time.monotonic() - self.t0) * 1000) & 0xFFFFFFFF

    def key(self, code, down):
        self._send(self.kb, 1, struct.pack("<III", self._ms(), code, 1 if down else 0))
        self._roundtrip()
        time.sleep(self.delay)

    def modifiers(self, mask):
        self.mods = mask
        self._send(self.kb, 2, struct.pack("<IIII", mask, 0, 0, 0))
        self._roundtrip()

    def combo(self, keys, hold=0.05):
        """Press "SUPER + SHIFT + W": the modifiers down, the key down and up, the modifiers up."""
        parts = [p.strip().upper() for p in keys.split("+")]
        mods, key = parts[:-1], parts[-1]
        mask = 0
        for m in mods:
            code, bit = MODS[m]
            self.key(code, True)
            mask |= bit
            self.modifiers(mask)
        self.key(KEYS[key], True)
        time.sleep(hold)
        self.key(KEYS[key], False)
        for m in reversed(mods):
            code, bit = MODS[m]
            self.key(code, False)
            mask &= ~bit
            self.modifiers(mask)

    def tap(self, key):
        self.combo(key)

    def type(self, text):
        for ch in text:
            if ch.isupper():
                self.combo("SHIFT + " + ch)
            else:
                self.tap(CHARS.get(ch, ch.upper()))

    def close(self):
        self.s.close()
