"""A game controller's live input and its rumble, read and driven straight from Linux's evdev
(package bromigos-desktop, /usr/lib/bromigos/lib): no python-evdev needed. The Bluetooth
TUI's and Settings' controller testers use it, through `bromigos bluetooth session`.

  find(mac)            the controller's event device (/dev/input/eventN), by its Bluetooth
                       address, or None
  Pad(path)            open it: .read() takes what's waiting and updates .buttons (the names
                       held) and .axes (sticks -1..1, triggers 0..1, the d-pad -1/0/1);
                       .rumble(strong, weak, ms) shakes it (0..1 each); .close()
  parse(data)          input_event records -> [(type, code, value)] (pure, for tests)

Joysticks are the seat user's to read and write (systemd's uaccess), so no group is needed.
Names follow Linux's gamepad layout: A at the bottom, B right, X left, Y top. The kernel's
basic driver reports some of them under other codes; xpadneo reports them all as named.
"""
import fcntl
import os
import struct

EV_KEY, EV_ABS, EV_FF = 0x01, 0x03, 0x15
FF_RUMBLE = 0x50
EVENT = struct.Struct("llHHi")          # struct input_event (64-bit: timeval, type, code, value)
ABSINFO = struct.Struct("iiiiii")       # value, minimum, maximum, fuzz, flat, resolution

BUTTONS = {0x130: "A", 0x131: "B", 0x133: "Y", 0x134: "X", 0x136: "LB", 0x137: "RB", 0x13a: "VIEW",
           0x13b: "MENU", 0x13c: "XBOX", 0x13d: "LS", 0x13e: "RS", 167: "SHARE", 0x138: "LT", 0x139: "RT"}
# the kernel's basic driver (hid-generic, hid-microsoft without xpadneo) on an Xbox pad
BASIC = {0x132: "X", 0x135: "Y"}
STICKS = {0x00: "lx", 0x01: "ly", 0x03: "rx", 0x04: "ry"}
TRIGGERS = {0x02: "lt", 0x05: "rt", 0x0a: "lt", 0x09: "rt"}     # ABS_Z/RZ, or ABS_BRAKE/GAS
HAT = {0x10: "dx", 0x11: "dy"}
DPAD = {(0, "dx", -1): "LEFT", (0, "dx", 1): "RIGHT", (0, "dy", -1): "UP", (0, "dy", 1): "DOWN"}
BTN_SOUTH = 0x130


def _ioc(direction, nr, size):
    return (direction << 30) | (size << 16) | (ord("E") << 8) | nr


def eviocgabs(code):
    return _ioc(2, 0x40 + code, ABSINFO.size)


EVIOCSFF = _ioc(1, 0x80, 48)            # struct ff_effect: 48 bytes on 64-bit


def _sys(root=None):
    return os.path.join(root or os.environ.get("BROMIGOS_PERIPHERAL_ROOT") or "/", "sys/class/input")


def _read(p):
    try:
        with open(p) as f:
            return f.read().strip()
    except OSError:
        return ""


def _bits(text):
    """A sysfs capabilities bitmap ("7fff000000000000 0 0 0 0") -> the set bit numbers."""
    out = set()
    words = text.split()
    for i, w in enumerate(reversed(words)):
        try:
            v = int(w, 16)
        except ValueError:
            continue
        b = 0
        while v:
            if v & 1:
                out.add(i * 64 + b)
            v >>= 1
            b += 1
    return out


def find(mac, root=None):
    """The event device of the gamepad whose uniq is mac (Bluetooth pads report their address)."""
    base = _sys(root)
    mac = mac.lower()
    try:
        names = sorted(os.listdir(base))
    except OSError:
        return None
    for n in names:
        if not n.startswith("event"):
            continue
        dev = os.path.join(base, n, "device")
        if _read(os.path.join(dev, "uniq")).lower() != mac:
            continue
        if BTN_SOUTH in _bits(_read(os.path.join(dev, "capabilities", "key"))):
            fake = root or os.environ.get("BROMIGOS_PERIPHERAL_ROOT")
            return os.path.join(fake, "dev/input", n) if fake else os.path.join("/dev/input", n)
    return None


def parse(data):
    """input_event records -> [(type, code, value)]."""
    n = len(data) // EVENT.size
    return [EVENT.unpack_from(data, i * EVENT.size)[2:] for i in range(n)]


def norm(value, info, centred=True):
    """A raw axis value -> -1..1 (a stick) or 0..1 (a trigger), from its range."""
    lo, hi = info
    if hi <= lo:
        return 0.0
    f = (value - lo) / (hi - lo)
    f = max(0.0, min(1.0, f))
    return round(f * 2 - 1, 3) if centred else round(f, 3)


class Pad:
    def __init__(self, path):
        self.path = path
        try:
            self.fd = os.open(path, os.O_RDWR | os.O_NONBLOCK)
            self.writable = True
        except PermissionError:
            self.fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK)
            self.writable = False
        self.ranges = {}
        for code in list(STICKS) + list(TRIGGERS) + list(HAT):
            buf = bytearray(ABSINFO.size)
            try:
                fcntl.ioctl(self.fd, eviocgabs(code), buf)
                v = ABSINFO.unpack(buf)
                self.ranges[code] = (v[1], v[2])
            except OSError:
                pass
        self.held = set()
        self.axes = {"lx": 0.0, "ly": 0.0, "rx": 0.0, "ry": 0.0, "lt": 0.0, "rt": 0.0, "dx": 0, "dy": 0}
        self.effect = None

    @property
    def buttons(self):
        out = set(self.held)
        for (_, k, v), name in DPAD.items():
            if self.axes.get(k) == v:
                out.add(name)
        return sorted(out)

    def feed(self, events):
        for t, code, value in events:
            if t == EV_KEY:
                name = BUTTONS.get(code) or BASIC.get(code)
                if name:
                    (self.held.add if value else self.held.discard)(name)
            elif t == EV_ABS:
                if code in STICKS and code in self.ranges:
                    self.axes[STICKS[code]] = norm(value, self.ranges[code])
                elif code in TRIGGERS and code in self.ranges:
                    self.axes[TRIGGERS[code]] = norm(value, self.ranges[code], centred=False)
                elif code in HAT:
                    self.axes[HAT[code]] = max(-1, min(1, value))

    def read(self):
        """Everything waiting; True when something changed."""
        got = b""
        while True:
            try:
                chunk = os.read(self.fd, EVENT.size * 64)
            except BlockingIOError:
                break
            except OSError:
                raise
            if not chunk:
                break
            got += chunk
        if got:
            self.feed(parse(got))
        return bool(got)

    def rumble(self, strong=0.6, weak=0.6, ms=400):
        """Shake it: both motors, 0..1 each, for ms. False when the driver can't (the
        kernel's basic driver often can't; xpadneo can)."""
        if not self.writable:
            return False
        eff = bytearray(48)
        struct.pack_into("HhHHHHH", eff, 0, FF_RUMBLE, -1 if self.effect is None else self.effect, 0, 0, 0,
                         max(1, min(5000, int(ms))), 0)
        struct.pack_into("HH", eff, 16, int(max(0, min(1, strong)) * 0xffff), int(max(0, min(1, weak)) * 0xffff))
        try:
            fcntl.ioctl(self.fd, EVIOCSFF, eff)
            self.effect = struct.unpack_from("h", eff, 2)[0]
            os.write(self.fd, EVENT.pack(0, 0, EV_FF, self.effect, 1))
            return True
        except OSError:
            return False

    def close(self):
        try:
            os.close(self.fd)
        except OSError:
            pass
