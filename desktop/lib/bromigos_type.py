"""Type Unicode text through this session's Wayland virtual keyboard, without a clipboard."""
import array
import os
import socket
import struct
import time


def keymap(chars):
    """One level, no modifiers: punctuation and non-English letters are literal text."""
    codes = {ch: i + 2 for i, ch in enumerate(dict.fromkeys(chars))}
    if len(codes) > 50:
        raise ValueError("one keymap holds at most 50 different characters")
    names = " ".join(f"<D{i:02}> = {code + 8};" for i, code in enumerate(codes.values()))
    symbols = " ".join(f'key <D{i:02}> {{ type="ONE_LEVEL", [ U{ord(ch):04X} ] }};'
                       for i, ch in enumerate(codes))
    text = ('xkb_keymap { xkb_keycodes "dictation" { minimum=8; maximum=255; '
            + names + ' }; xkb_types "dictation" { type "ONE_LEVEL" { modifiers=None; '
            'map[None]=Level1; level_name[Level1]="Any"; }; }; '
            'xkb_compatibility "dictation" {}; xkb_symbols "dictation" { ' + symbols + ' }; };')
    return text.encode() + b"\0", codes


class Keyboard:
    """A small client for zwp_virtual_keyboard_v1. Never opens an input device."""
    def __init__(self, path):
        self.sock = socket.socket(socket.AF_UNIX)
        self.sock.settimeout(3)
        self.next_id, self.buffer = 2, b""
        try:
            self.sock.connect(path)
            reg = self._id()
            self._send(1, 1, struct.pack("<I", reg))
            globals_ = {}
            for obj, op, data in self._sync():
                if obj == reg and op == 0:
                    name, = struct.unpack_from("<I", data)
                    interface, offset = self._string(data, 4)
                    version, = struct.unpack_from("<I", data, offset)
                    globals_[interface] = name, version
            seat = self._bind(reg, globals_, "wl_seat")
            manager = self._bind(reg, globals_, "zwp_virtual_keyboard_manager_v1")
            self.keyboard = self._id()
            self._send(manager, 0, struct.pack("<II", seat, self.keyboard))
        except Exception:
            self.close()
            raise

    def _id(self):
        result = self.next_id
        self.next_id += 1
        return result

    @staticmethod
    def _pack_string(text):
        raw = text.encode() + b"\0"
        return struct.pack("<I", len(raw)) + raw + b"\0" * (-len(raw) % 4)

    @staticmethod
    def _string(raw, offset):
        length, = struct.unpack_from("<I", raw, offset)
        return raw[offset + 4:offset + 3 + length].decode(), offset + 4 + ((length + 3) & ~3)

    def _send(self, obj, op, data, fd=None):
        packet = struct.pack("<II", obj, ((8 + len(data)) << 16) | op) + data
        if fd is None:
            self.sock.sendall(packet)
        else:
            sent = self.sock.sendmsg([packet], [(socket.SOL_SOCKET, socket.SCM_RIGHTS, array.array("i", [fd]))])
            if sent < len(packet):
                self.sock.sendall(packet[sent:])

    def _bind(self, registry, globals_, interface):
        if interface not in globals_:
            raise RuntimeError("This compositor cannot insert dictation text")
        name, _ = globals_[interface]
        new = self._id()
        self._send(registry, 0, struct.pack("<I", name) + self._pack_string(interface)
                   + struct.pack("<II", 1, new))
        return new

    def _sync(self):
        callback = self._id()
        self._send(1, 0, struct.pack("<I", callback))
        events = []
        while True:
            while len(self.buffer) < 8:
                self._read()
            obj, word = struct.unpack_from("<II", self.buffer)
            size, op = word >> 16, word & 65535
            if size < 8:
                raise RuntimeError("Invalid Wayland message")
            while len(self.buffer) < size:
                self._read()
            data, self.buffer = self.buffer[8:size], self.buffer[size:]
            if obj == 1 and op == 0:
                raise RuntimeError("The compositor refused dictation input")
            if obj == callback and op == 0:
                return events
            events.append((obj, op, data))

    def _read(self):
        data = self.sock.recv(65536)
        if not data:
            raise RuntimeError("The compositor disconnected")
        self.buffer += data

    def type(self, text, check=lambda: True):
        for start in range(0, len(text), 50):
            chunk = text[start:start + 50]
            raw, codes = keymap(chunk)
            fd = os.memfd_create("dictation-keymap", os.MFD_CLOEXEC)
            try:
                os.write(fd, raw)
                self._send(self.keyboard, 0, struct.pack("<II", 1, len(raw)), fd)
            finally:
                os.close(fd)
            self._send(self.keyboard, 2, struct.pack("<IIII", 0, 0, 0, 0))
            self._sync()
            if not check():
                raise RuntimeError("Focus changed; dictation stopped")
            for ch in chunk:
                timestamp = int(time.monotonic() * 1000) & 0xFFFFFFFF
                self._send(self.keyboard, 1, struct.pack("<III", timestamp, codes[ch], 1))
                self._send(self.keyboard, 1, struct.pack("<III", timestamp, codes[ch], 0))
                self._sync()
                time.sleep(.002)

    def close(self):
        self.sock.close()


def type_text(text, check=lambda: True):
    display = os.environ.get("WAYLAND_DISPLAY", "")
    if not display:
        raise RuntimeError("Dictation needs a Wayland session")
    path = display if os.path.isabs(display) else os.path.join(os.environ["XDG_RUNTIME_DIR"], display)
    keyboard = Keyboard(path)
    try:
        keyboard.type(text, check)
    finally:
        keyboard.close()
