"""A game controller's live input and its rumble, read and driven straight from Linux's evdev
(package bromigos-desktop, /usr/lib/bromigos/lib): no python-evdev needed. The Bluetooth
TUI's and Settings' controller testers use it, through `bromigos bluetooth session`.

  find(mac)            the controller's event device (/dev/input/eventN), by its Bluetooth
                       address, or None
  Pad(path)            open it: .read() takes what's waiting and updates .buttons (the names
                       held) and .axes (sticks -1..1, triggers 0..1, the d-pad -1/0/1);
                       .rumble(strong, weak, ms) shakes it (0..1 each); .describe() its
                       driver and where its layout came from; .close()
  layout(info(path))   which code is which stick, trigger and button (pure, for tests)
  parse(data)          input_event records -> [(type, code, value)] (pure, for tests)

Which axis is which depends on the driver: xpad and xpadneo give the right stick on RX/RY
and the triggers on Z/RZ; hid-microsoft (an Xbox pad over Bluetooth without xpadneo) gives
the right stick on Z/RZ and the triggers on GAS/BRAKE. So nothing is hard-coded: the
layout is SDL_GameControllerDB's mapping for the device (gamecontrollerdb.txt beside this
file, by SDL's GUID, applied with SDL's own numbering of the device's buttons and axes), as
SDL, Steam and most games read it; a device it doesn't know gets a layout from which axes
its driver has. Each axis is scaled by its own range and dead zone (absinfo). The d-pad is
a hat (HAT0X/HAT0Y) or four buttons, whichever the driver sends.

Joysticks are the seat user's to read and write (systemd's uaccess), so no group is needed.
The names are an Xbox pad's: A at the bottom, B right, X left, Y top.
"""
import fcntl
import os
import struct

EV_KEY, EV_ABS, EV_FF = 0x01, 0x03, 0x15
FF_RUMBLE = 0x50
EVENT = struct.Struct("llHHi")          # struct input_event (64-bit: timeval, type, code, value)
ABSINFO = struct.Struct("iiiiii")       # value, minimum, maximum, fuzz, flat, resolution

BTN_SOUTH = 0x130
ABS_X, ABS_Y, ABS_Z, ABS_RX, ABS_RY, ABS_RZ, ABS_GAS, ABS_BRAKE = 0x00, 0x01, 0x02, 0x03, 0x04, 0x05, 0x09, 0x0a
ABS_HAT0X, ABS_HAT0Y, ABS_HAT3Y = 0x10, 0x11, 0x17
BTN_JOYSTICK, KEY_MAX = 0x120, 0x2ff
BTN_DPAD = {0x220: "UP", 0x221: "DOWN", 0x222: "LEFT", 0x223: "RIGHT"}
STICK_AXES = ("lx", "ly", "rx", "ry")

# SDL's names for a controller's parts -> the names the testers show
SDL_BUTTONS = {"a": "A", "b": "B", "x": "X", "y": "Y", "leftshoulder": "LB", "rightshoulder": "RB",
               "back": "VIEW", "start": "MENU", "guide": "XBOX", "leftstick": "LS", "rightstick": "RS",
               "misc1": "SHARE", "lefttrigger": "LT", "righttrigger": "RT",
               "dpup": "UP", "dpdown": "DOWN", "dpleft": "LEFT", "dpright": "RIGHT"}
SDL_AXES = {"leftx": "lx", "lefty": "ly", "rightx": "rx", "righty": "ry", "lefttrigger": "lt", "righttrigger": "rt"}
HAT_BITS = {1: "UP", 2: "RIGHT", 4: "DOWN", 8: "LEFT"}

# Without a mapping, the buttons by Linux's codes (an Xbox pad's X is BTN_X, as SDL's mappings
# have it), and the sticks and triggers from which axes the driver has (layout())
BUTTONS = {0x130: "A", 0x131: "B", 0x133: "X", 0x134: "Y", 0x136: "LB", 0x137: "RB", 0x138: "LT", 0x139: "RT",
           0x13a: "VIEW", 0x13b: "MENU", 0x13c: "XBOX", 0x13d: "LS", 0x13e: "RS", 167: "SHARE", 158: "VIEW",
           **BTN_DPAD}
LAYOUTS = {
    # hid-microsoft (an Xbox pad over Bluetooth without xpadneo): Z and RZ are the right
    # stick, GAS and BRAKE the triggers
    "hid-microsoft": {ABS_X: "lx", ABS_Y: "ly", ABS_Z: "rx", ABS_RZ: "ry", ABS_BRAKE: "lt", ABS_GAS: "rt"},
    # xpad and xpadneo: RX and RY the right stick, Z and RZ the triggers
    "xpad": {ABS_X: "lx", ABS_Y: "ly", ABS_RX: "rx", ABS_RY: "ry", ABS_Z: "lt", ABS_RZ: "rt"},
    # a pad with no analogue triggers: Z and RZ the right stick
    "generic": {ABS_X: "lx", ABS_Y: "ly", ABS_Z: "rx", ABS_RZ: "ry"},
}
DB = os.path.join(os.path.dirname(os.path.realpath(__file__)), "gamecontrollerdb.txt")


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


def norm(value, info, centred=True, flat=0):
    """A raw axis value -> -1..1 (a stick) or 0..1 (a trigger), from its range (and, for a
    stick, its flat: the dead zone around the centre the driver gives)."""
    lo, hi = info[0], info[1]
    if hi <= lo:
        return 0.0
    if centred and flat and abs(value - (lo + hi) / 2) <= flat:
        return 0.0
    f = (value - lo) / (hi - lo)
    f = max(0.0, min(1.0, f))
    return round(f * 2 - 1, 3) if centred else round(f, 3)


# ------------------------------------------------------------------ which axis is which
def info(path, root=None):
    """What sysfs says about an event device: name, bus, vendor, product, version (the
    input device's, which SDL's mappings go by), the HID device's own vendor:product
    (xpadneo shows an Xbox pad as 045e:028e; the pad is what's under it), its driver,
    and its key and axis codes."""
    base = os.path.join(_sys(root), os.path.basename(path), "device")
    out = {"name": _read(os.path.join(base, "name")), "keys": _bits(_read(os.path.join(base, "capabilities", "key"))),
           "abs": _bits(_read(os.path.join(base, "capabilities", "abs")))}
    for k in ("bustype", "vendor", "product", "version"):
        try:
            out[k] = int(_read(os.path.join(base, "id", k)) or "x", 16)
        except ValueError:
            out[k] = None
    parent = os.path.realpath(os.path.join(base, "device"))
    hid = os.path.basename(parent).split(".")[0].split(":")
    out["hid"] = (f"{hid[1].lower()}:{hid[2].lower()}" if len(hid) == 3 and all(len(x) == 4 for x in hid[1:]) else
                  (f"{out['vendor']:04x}:{out['product']:04x}" if out["vendor"] is not None and
                   out["product"] is not None else None))
    drv = os.path.basename(os.path.realpath(os.path.join(base, "device", "driver")))
    out["driver"] = {"microsoft": "hid-microsoft"}.get(drv, drv) if os.path.exists(
        os.path.join(base, "device", "driver")) else None
    return out


def guid(i):
    """SDL's GUID for a Linux evdev device (2.0.16 form, as SDL_GameControllerDB writes it):
    bus, vendor, product and version, little-endian, each padded to 32 bits."""
    if None in (i.get("bustype"), i.get("vendor"), i.get("product"), i.get("version")):
        return None
    return struct.pack("<HHHHHHHH", i["bustype"], 0, i["vendor"], 0, i["product"], 0, i["version"], 0).hex()


def sdl_indices(i):
    """SDL's numbering of a device's buttons, axes and hats (its Linux joystick driver): the
    buttons from BTN_JOYSTICK up, then those below it; the axes in code order, the hats'
    left out; a hat for each HATnX/HATnY pair. -> ({"b3": code}, {"a2": code}, {0: n})."""
    keys, absb = i.get("keys") or set(), i.get("abs") or set()
    order = [c for c in range(BTN_JOYSTICK, KEY_MAX) if c in keys] + [c for c in range(BTN_JOYSTICK) if c in keys]
    buttons = {f"b{n}": c for n, c in enumerate(order)}
    hats, n = {}, 0
    for c in range(ABS_HAT0X, ABS_HAT3Y + 1, 2):
        if c in absb or c + 1 in absb:
            hats[n] = (c - ABS_HAT0X) // 2
            n += 1
    hat_codes = {ABS_HAT0X + 2 * h + d for h in hats.values() for d in (0, 1)}
    axes = {f"a{n}": c for n, c in enumerate(c for c in range(0x40) if c in absb and c not in hat_codes)}
    return buttons, axes, hats


_db_cache = {}


def database(path=DB):
    """SDL_GameControllerDB's Linux lines (and SDL_GAMECONTROLLERCONFIG's, first, as SDL
    reads them) -> {guid: mapping}."""
    key = (path, os.environ.get("SDL_GAMECONTROLLERCONFIG", ""))
    if key in _db_cache:
        return _db_cache[key]
    lines = os.environ.get("SDL_GAMECONTROLLERCONFIG", "").splitlines()
    try:
        with open(path) as f:
            lines += f.read().splitlines()
    except OSError:
        pass
    out = {}
    for line in lines:
        line = line.strip()
        if not line or line.startswith("#") or "," not in line:
            continue
        g, rest = line.split(",", 1)
        out.setdefault(g.lower(), rest)
    _db_cache[key] = out
    return out


def lookup(i, db=None):
    """The device's mappings in SDL_GameControllerDB, best first: its own GUID's (exact), then
    those of the same bus, vendor and product under another firmware version (not exact: the
    same ids can mean another driver's layout, so layout() checks those against the axes).
    [(name, mapping, exact)]."""
    db = database() if db is None else db
    g = guid(i)
    if not g:
        return []
    out = []
    if g in db:
        out.append((*db[g].partition(",")[::2], True))
    out += [(*v.partition(",")[::2], False) for k, v in db.items() if len(k) == 32 and k != g and k[:24] == g[:24]]
    return out


class Layout:
    """Which code is which part: .axes {code: (name, invert)}, .buttons {code: name}, .hats
    {hat number: True} (the d-pad on HATnX/HATnY) and .source (where the mapping came from)."""

    def __init__(self, axes, buttons, hats, source):
        self.axes, self.buttons, self.hats, self.source = axes, buttons, hats, source


def from_sdl(i, fields):
    """An SDL mapping ("a:b0,b:b1,leftx:a0,…") applied to this device's numbering; None when it
    names a button or axis the device hasn't got (then it's not this device's mapping)."""
    bmap, amap, hmap = sdl_indices(i)
    axes, buttons, hats = {}, {}, {}
    for part in fields.split(","):
        out, _, src = part.partition(":")
        if not src or out in ("platform", "crc", "hint", "sdk>=", "sdk<="):
            continue
        out = out.lstrip("+-")
        invert = src.endswith("~")
        src = src.rstrip("~").lstrip("+-")
        if src.startswith("b") and out in SDL_BUTTONS:
            if src not in bmap:
                return None
            buttons[bmap[src]] = SDL_BUTTONS[out]
        elif src.startswith("a") and out in SDL_AXES:
            if src not in amap:
                return None
            axes[amap[src]] = (SDL_AXES[out], invert)
        elif src.startswith("h") and out in SDL_BUTTONS:
            h = int(src[1:].split(".")[0])
            if h not in hmap:
                return None
            hats[hmap[h]] = True
    if not {"lx", "ly"} <= {n for n, _ in axes.values()}:
        return None
    return axes, buttons, hats


def _dpad(i, buttons, hats):
    """The d-pad whichever way the driver sends it: HAT0X/HAT0Y, and BTN_DPAD_* buttons."""
    keys, absb = i.get("keys") or set(), i.get("abs") or set()
    for c, name in BTN_DPAD.items():
        if c in keys or not keys:
            buttons.setdefault(c, name)
    if ABS_HAT0X in absb or ABS_HAT0Y in absb or not absb:
        hats[0] = True


def layout(i, db=None):
    """This device's Layout: SDL_GameControllerDB's mapping when it has one that fits;
    else from which axes the driver gives (layout_of). Another firmware version's mapping
    is used only when its right stick is where the axes say (an Xbox pad's ids are the same
    on hid-microsoft and on xpad, its right stick isn't)."""
    kind = layout_of(i)
    want = {n: c for c, n in LAYOUTS[kind].items() if n in ("rx", "ry")}
    for _name, fields, exact in lookup(i, db):
        got = from_sdl(i, fields)
        if got is None:
            continue
        if not exact and {n: c for c, (n, _) in got[0].items() if n in ("rx", "ry")} != want:
            continue
        _dpad(i, got[1], got[2])
        return Layout(*got, source="SDL GameControllerDB")
    absb = i.get("abs") or set()
    axes = {c: (n, False) for c, n in LAYOUTS[kind].items() if not absb or c in absb}
    buttons, hats = dict(BUTTONS), {}
    _dpad(i, buttons, hats)
    return Layout(axes, buttons, hats, source=f"the {kind} layout (from its axes)")


def layout_of(i):
    """Which driver's layout the axes say: GAS or BRAKE -> hid-microsoft's; RX and RY ->
    xpad's (and xpadneo's); Z and RZ only -> a pad without analogue triggers."""
    absb = i.get("abs") or set()
    if ABS_GAS in absb or ABS_BRAKE in absb:
        return "hid-microsoft"
    if ABS_RX in absb and ABS_RY in absb:
        return "xpad"
    if ABS_Z in absb and ABS_RZ in absb:
        return "generic"
    return "xpad"


def basic_driver(i):
    """An Xbox controller on the kernel's basic driver (hid-microsoft, hid-generic), not
    xpadneo: rumble and the battery are limited."""
    return bool(i) and i.get("vendor") == 0x045e and i.get("bustype") == 0x05 and \
        i.get("driver") not in (None, "xpadneo")


class Pad:
    def __init__(self, path, root=None):
        self.path = path
        try:
            self.fd = os.open(path, os.O_RDWR | os.O_NONBLOCK)
            self.writable = True
        except PermissionError:
            self.fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK)
            self.writable = False
        self.info = info(path, root)
        self.layout = layout(self.info)
        self.ranges = {}
        for code in list(self.layout.axes) + [ABS_HAT0X + 2 * h + d for h in self.layout.hats for d in (0, 1)]:
            buf = bytearray(ABSINFO.size)
            try:
                fcntl.ioctl(self.fd, eviocgabs(code), buf)
                v = ABSINFO.unpack(buf)
                self.ranges[code] = (v[1], v[2], v[4])         # minimum, maximum, flat
            except OSError:
                pass
        self.held = set()
        self.axes = {"lx": 0.0, "ly": 0.0, "rx": 0.0, "ry": 0.0, "lt": 0.0, "rt": 0.0, "dx": 0, "dy": 0}
        self.effect = None

    @property
    def driver(self):
        return self.info.get("driver")

    @property
    def basic(self):
        return basic_driver(self.info)

    def describe(self):
        """For the testers: the driver, where the layout came from, the IDs."""
        i = self.info
        return {"driver": i.get("driver"), "basic": self.basic, "layout": self.layout.source, "id": i.get("hid")}

    @property
    def buttons(self):
        out = set(self.held)
        out |= {name for (k, v), name in {("dx", -1): "LEFT", ("dx", 1): "RIGHT", ("dy", -1): "UP",
                                           ("dy", 1): "DOWN"}.items() if self.axes.get(k) == v}
        return sorted(out)

    def feed(self, events):
        lay = self.layout
        for t, code, value in events:
            if t == EV_KEY:
                name = lay.buttons.get(code)
                if name:
                    (self.held.add if value else self.held.discard)(name)
            elif t == EV_ABS:
                if code in lay.axes and code in self.ranges:
                    name, invert = lay.axes[code]
                    r = self.ranges[code]
                    if name in STICK_AXES:
                        v = norm(value, r, flat=r[2] if len(r) > 2 else 0)
                        self.axes[name] = -v if invert else v
                    else:
                        v = norm(value, r, centred=False)
                        self.axes[name] = round(1 - v, 3) if invert else v
                elif ABS_HAT0X <= code <= ABS_HAT3Y and (code - ABS_HAT0X) // 2 in lay.hats:
                    self.axes["dy" if (code - ABS_HAT0X) % 2 else "dx"] = max(-1, min(1, value))

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
