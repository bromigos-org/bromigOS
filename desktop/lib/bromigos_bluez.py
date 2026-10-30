"""bluez over D-Bus, shared by everything Bluetooth on the desktop (package bromigos-desktop,
/usr/lib/bromigos/lib): the bar's module (waybar/scripts/bluetooth.py), its panel and menu
(bromigos_btpanel.py) and `bromigos bluetooth`'s device kinds.

  Bluez(on_change)        the adapter and the devices, kept current by bluez's own signals
                          (no polling); .state() is one plain dict; actions are async and
                          call done(ok, error) with error in plain words (explain())
  Agent(ui)               a bluez pairing agent: PIN, passkey and "does it show 123456?"
                          prompts handed to the UI, whose reply goes back to bluez
  bar(state, …)           the bar's JSON line: text, tooltip and classes (pure)
  kind(icon, name)        "headset", "game controller", … and glyph(…): the hologram to draw
  explain(error)          a bluez error in plain words

bluez lives on the system bus. BROMIGOS_BLUEZ_BUS=<address> points everything at another
bus instead (the tests' and the offscreen renders' stand-in bluez, tests/fake_bluez.py).
"""
import html
import os
import re
import shutil
import subprocess

BLUEZ = "org.bluez"
OM = "org.freedesktop.DBus.ObjectManager"
PROPS = "org.freedesktop.DBus.Properties"
ADAPTER = "org.bluez.Adapter1"
DEVICE = "org.bluez.Device1"
BATTERY = "org.bluez.Battery1"
AGENT_MANAGER = "org.bluez.AgentManager1"
AGENT_PATH = "/org/bromigos/bluetooth/agent"

LOW = 15            # % : the bar turns amber, the panel's cells too
CRITICAL = 5        # % : red

MAC = re.compile(r"^[0-9A-Fa-f]{2}(:[0-9A-Fa-f]{2}){5}$")

# bluez's Icon property (the device class) -> what to call it
KIND = {"audio-headset": "headset", "audio-headphones": "headphones", "audio-card": "speaker",
        "input-keyboard": "keyboard", "input-mouse": "mouse", "input-gaming": "game controller",
        "input-tablet": "tablet", "phone": "phone", "computer": "computer", "camera-photo": "camera",
        "camera-video": "camera", "printer": "printer", "modem": "modem", "network-wireless": "network"}
# the hologram each kind is drawn as (bromigos_driftglass), and its bar icon's name (theme/icons)
GLYPH = {"headset": "headset", "headphones": "headset", "earbuds": "earbuds", "speaker": "speaker",
         "keyboard": "keyboard", "mouse": "mouse", "game controller": "controller", "tablet": "device",
         "phone": "phone", "computer": "device", "camera": "device", "printer": "device",
         "modem": "device", "network": "device", "device": "device"}
ICON = {"controller": "bt-pad", "headset": "bt-headset", "earbuds": "bt-buds", "speaker": "bt-speaker",
        "keyboard": "bt-kbd", "mouse": "bt-mouse", "phone": "bt-phone", "device": "bt-dev"}
EARBUDS = re.compile(r"buds|airpods|earbud|ear ?\(|\bpods\b|tws", re.I)
XBOX = re.compile(r"xbox", re.I)

# Bluetooth profiles (service UUIDs) that make a device a sound device
A2DP_SINK = "0000110b-0000-1000-8000-00805f9b34fb"     # it plays what this machine sends
A2DP_SOURCE = "0000110a-0000-1000-8000-00805f9b34fb"   # it sends sound here (a phone)
HFP_HF = "0000111e-0000-1000-8000-00805f9b34fb"
HSP_HS = "00001108-0000-1000-8000-00805f9b34fb"
LE_AUDIO = "0000184e-0000-1000-8000-00805f9b34fb"      # LE Audio's audio stream control
AUDIO_OUT = {A2DP_SINK, HFP_HF, HSP_HS, LE_AUDIO}


def kind(icon, name=""):
    """What the device is, in words: bluez's Icon, sharpened by its name (an Xbox pad
    reports itself as "input-gaming"; earbuds as headphones or a headset)."""
    if is_xbox(name, icon):
        return "game controller"
    k = KIND.get(icon or "", (icon or "").split("-")[-1] if icon else "device")
    if k in ("headset", "headphones") and EARBUDS.search(name or ""):
        return "earbuds"
    return k


def glyph(k):
    """The hologram for a kind ("game controller" -> "controller")."""
    return GLYPH.get(k, "device")


def is_xbox(name, icon=""):
    return bool(XBOX.search(name or "")) and (icon in ("input-gaming", "") or "controller" in (name or "").lower())


def mac_of(path):
    """/org/bluez/hci0/dev_00_00_5E_00_53_10 -> 00:00:5E:00:53:10"""
    tail = path.rsplit("/", 1)[-1]
    return tail[4:].replace("_", ":").upper() if tail.startswith("dev_") else ""


def xpadneo_loaded(root=None):
    """xpadneo, the Xbox controllers' full driver, is loaded (rumble, battery, the mappings)."""
    root = root or os.environ.get("BROMIGOS_PERIPHERAL_ROOT") or "/"
    return os.path.isdir(os.path.join(root, "sys/module/hid_xpadneo"))


def rfkill(root=None):
    """(soft, hard): the Bluetooth radio's rfkill blocks, from sysfs (no tool needed)."""
    base = os.path.join(root or os.environ.get("BROMIGOS_PERIPHERAL_ROOT") or "/", "sys/class/rfkill")
    soft = hard = False
    try:
        names = os.listdir(base)
    except OSError:
        return False, False
    for n in names:
        try:
            with open(os.path.join(base, n, "type")) as f:
                if f.read().strip() != "bluetooth":
                    continue
            with open(os.path.join(base, n, "soft")) as f:
                soft = soft or f.read().strip() == "1"
            with open(os.path.join(base, n, "hard")) as f:
                hard = hard or f.read().strip() == "1"
        except OSError:
            continue
    return soft, hard


def has_adapter_hw(root=None):
    """A Bluetooth controller exists in the kernel (/sys/class/bluetooth/hci*), whether or
    not bluetoothd runs: the bar shows it then, and says the service is down."""
    base = os.path.join(root or os.environ.get("BROMIGOS_PERIPHERAL_ROOT") or "/", "sys/class/bluetooth")
    try:
        return any(n.startswith("hci") and ":" not in n for n in os.listdir(base))
    except OSError:
        return False


# ------------------------------------------------------------------ errors in plain words
ERRORS = [
    (r"AuthenticationFailed", "The codes didn't match, or the device turned pairing down. Put it in pairing "
                              "mode again and retry"),
    (r"AuthenticationCanceled", "Pairing was cancelled"),
    (r"AuthenticationRejected", "The device said no to pairing"),
    (r"AuthenticationTimeout", "The device didn't answer in time: is it still in pairing mode?"),
    (r"ConnectionAttemptFailed|Page Timeout|Host is down|le-connection-abort",
     "Couldn't reach it: is it switched on and nearby?"),
    (r"br-connection-profile-unavailable|Protocol not available",
     "It has nothing this computer can connect to. For a phone, start the connection from the phone"),
    (r"AlreadyExists", "It's paired already"),
    (r"InProgress", "Busy with that device already: wait a moment"),
    (r"NotReady|org.bluez.Error.Busy", "Bluetooth isn't ready: is it on?"),
    (r"rfkill|Blocked", "Bluetooth is blocked (rfkill): a key, a switch or airplane mode turned the radio off"),
    (r"DoesNotExist|UnknownObject", "That device is gone: scan again"),
    (r"NotAvailable", "Not available on this device"),
    (r"ServiceUnknown|Name.*org.bluez.*not|was not provided by any",
     "bluetoothd isn't running (systemctl enable --now bluetooth)"),
    (r"NoReply|Timeout was reached|timed out", "No answer from the device or bluetoothd in time"),
    (r"AccessDenied|NotAuthorized", "Not allowed: bluez refused this user"),
]


def explain(err):
    """A bluez or D-Bus error (a GLib.Error, an exception or its text) in plain words."""
    text = getattr(err, "message", None) or str(err or "")
    for pat, said in ERRORS:
        if re.search(pat, text, re.I):
            return said
    text = re.sub(r"^GDBus\.Error:[\w.]+:\s*", "", text).strip()
    return text[:1].upper() + text[1:] if text else "Something went wrong"


# ------------------------------------------------------------------ settings
def config_path():
    base = os.environ.get("XDG_CONFIG_HOME") or os.path.join(os.path.expanduser("~"), ".config")
    return os.path.join(base, "bromigos", "bluetooth.toml")


def settings():
    """~/.config/bromigos/bluetooth.toml: audio_default (a headset or speaker becomes the
    sound output when it connects; on by default)."""
    out = {"audio_default": True}
    try:
        import tomllib
        with open(config_path(), "rb") as f:
            got = tomllib.load(f)
        if isinstance(got.get("audio_default"), bool):
            out["audio_default"] = got["audio_default"]
    except (OSError, ValueError, ImportError):
        pass
    return out


def save_settings(s):
    p = config_path()
    os.makedirs(os.path.dirname(p), exist_ok=True)
    tmp = p + ".tmp"
    with open(tmp, "w") as f:
        f.write("# bromigos bluetooth (Settings › Bluetooth): yours, updates never change it\n"
                f"audio_default = {'true' if s.get('audio_default', True) else 'false'}   "
                "# a headset or speaker becomes the sound output when it connects\n")
    os.replace(tmp, p)


# ------------------------------------------------------------------ the state, as plain data
def device(path, props, battery=None):
    """A Device1's properties (unpacked) as the panel, the bar and the CLI use them."""
    name = props.get("Alias") or props.get("Name") or mac_of(path)
    icon = props.get("Icon", "")
    k = kind(icon, name)
    uuids = {u.lower() for u in props.get("UUIDs", [])}
    rssi = props.get("RSSI")
    return {"path": path, "mac": (props.get("Address") or mac_of(path)).upper(), "name": name,
            "alias": props.get("Alias", ""), "icon": icon, "kind": k, "glyph": glyph(k),
            "paired": bool(props.get("Paired")), "bonded": bool(props.get("Bonded", props.get("Paired"))),
            "connected": bool(props.get("Connected")), "trusted": bool(props.get("Trusted")),
            "blocked": bool(props.get("Blocked")), "battery": battery,
            "rssi": int(rssi) if isinstance(rssi, int) else None,
            "audio": bool(uuids & AUDIO_OUT) or icon.startswith("audio"),
            "audio_source": A2DP_SOURCE in uuids and k == "phone",
            "xbox": is_xbox(name, icon), "adapter": props.get("Adapter", "")}


def snapshot(objects, root=None):
    """The whole state from GetManagedObjects' answer ({path: {iface: {prop: value}}})."""
    soft, hard = rfkill(root)
    adapters = sorted(p for p, ifs in objects.items() if ADAPTER in ifs)
    if not adapters:
        return {"available": True, "adapter": None, "blocked": soft or hard, "hard_blocked": hard,
                "hardware": has_adapter_hw(root), "devices": [], "paired": [], "nearby": [], "connected": []}
    # the first powered adapter, else the first
    apath = next((p for p in adapters if objects[p][ADAPTER].get("Powered")), adapters[0])
    a = objects[apath][ADAPTER]
    devs = []
    for p, ifs in objects.items():
        if DEVICE not in ifs or ifs[DEVICE].get("Adapter", apath) != apath:
            continue
        b = ifs.get(BATTERY, {}).get("Percentage")
        devs.append(device(p, ifs[DEVICE], int(b) if isinstance(b, int) else None))
    devs.sort(key=lambda d: (not d["connected"], not d["paired"], d["name"].lower()))
    adapter = {"path": apath, "mac": a.get("Address", ""), "name": a.get("Name", ""), "alias": a.get("Alias", ""),
               "powered": bool(a.get("Powered")), "discoverable": bool(a.get("Discoverable")),
               "discovering": bool(a.get("Discovering")), "pairable": bool(a.get("Pairable"))}
    return {"available": True, "adapter": adapter, "powered": adapter["powered"], "blocked": soft or hard,
            "hard_blocked": hard, "hardware": True, "devices": devs,
            "paired": [d for d in devs if d["paired"]],
            # nearby: found by a scan and not paired; one with no name is noise until it says one
            "nearby": sorted((d for d in devs if not d["paired"] and (d["alias"] or d["rssi"] is not None)),
                             key=lambda d: -(d["rssi"] if d["rssi"] is not None else -999)),
            "connected": [d for d in devs if d["connected"]]}


def unavailable(root=None):
    """The state while bluetoothd isn't running (or bluez can't be reached)."""
    soft, hard = rfkill(root)
    return {"available": False, "adapter": None, "blocked": soft or hard, "hard_blocked": hard,
            "hardware": has_adapter_hw(root), "devices": [], "paired": [], "nearby": [], "connected": []}


PRIORITY = {"controller": 0, "headset": 1, "earbuds": 1, "speaker": 2, "keyboard": 3, "mouse": 3}


def main_device(state):
    """The connected device whose battery the bar shows: a controller, then a headset or
    earbuds, then a speaker, keyboard or mouse; the lowest battery among equals."""
    with_b = [d for d in state.get("connected", []) if d.get("battery") is not None]
    if not with_b:
        return None
    return min(with_b, key=lambda d: (PRIORITY.get(d["glyph"], 5), d["battery"]))


def level(pct):
    """"ok", "low" or "critical" for a battery percentage (None: "unknown")."""
    if pct is None:
        return "unknown"
    return "critical" if pct <= CRITICAL else "low" if pct <= LOW else "ok"


def cells(pct, n=5):
    """How many of n cells a battery lights (at least one while it has any charge)."""
    if pct is None:
        return 0
    return max(1 if pct > 0 else 0, min(n, round(pct * n / 100)))


HINT = "click: devices · right-click: quick menu · middle-click: turn {}"


def _esc(s):
    return html.escape(str(s), quote=False)


def bar(state, motion="full", spark=False, busy=False):
    """The bar module's JSON document for a state (waybar custom module, return-type json).
    DRIFTGLASS: the icon is EMBER (docs/DRIFTGLASS.md): colour and state, no running motion
    but a slow blink while bluez scans or pairs, and one Spark on a change.
    Classes: off | on | connected, low (the main device's battery at LOW or under), cN (its
    battery in five cells, for the sliver under the glyph), scanning (blinks; "busy" when
    motion is reduced), spark (a connect or disconnect just now; full motion only)."""
    a = state.get("adapter")
    if a is None and not (state.get("hardware") and (not state.get("available") or state.get("blocked"))):
        return {"text": "", "tooltip": "", "class": ["none"]}
    cls = []
    if a is None:
        why = ("bluetoothd isn't running (systemctl enable --now bluetooth)" if not state.get("available")
               else "the radio is blocked (rfkill): a key, a switch or airplane mode")
        return {"text": " ", "class": ["off", "problem"],
                "tooltip": f"<b>BLUETOOTH</b> · OFF\n{_esc(why)}\n" + HINT.format("on")}
    conn = state.get("connected", [])
    if not a["powered"]:
        cls.append("off")
        head = "<b>BLUETOOTH</b> · OFF" + (" · BLOCKED by a hardware switch or key" if state.get("hard_blocked") else
                                           " · blocked (rfkill)" if state.get("blocked") else "")
        lines = [head]
    else:
        cls.append("connected" if conn else "on")
        head = f"<b>BLUETOOTH</b> · ON · {len(conn)} connected" if conn else "<b>BLUETOOTH</b> · ON · nothing connected"
        lines = [head]
        for d in conn:
            b = d.get("battery")
            bat = "" if b is None else f" · {b}%" + (" <b>LOW</b>" if level(b) != "ok" else "")
            lines.append(f"{_esc(d['name'])} · {_esc(d['kind'])}{bat}")
        if a.get("discovering"):
            lines.append("scanning for devices nearby…")
        main = main_device(state)
        if main is not None:
            cls.append(f"c{cells(main['battery'])}")
            if level(main["battery"]) != "ok":
                cls.append("low")
    if (a.get("discovering") and a["powered"]) or busy:
        cls.append("scanning" if motion == "full" else "busy")
    if spark and motion == "full":
        cls.append("spark")
    lines.append(HINT.format("off" if a["powered"] else "on"))
    n = len(conn) if a["powered"] else 0
    text = f"<span size='x-small' rise='4500'>{n}</span>" if n else " "
    return {"text": text, "tooltip": "\n".join(lines), "class": cls, "alt": cls[0]}


# ------------------------------------------------------------------ sound: PipeWire's cards
CODEC = re.compile(r"codec\s+([\w.+-]+)", re.I)
CODEC_NAMES = {"sbc": "SBC", "sbc_xq": "SBC-XQ", "aac": "AAC", "aptx": "aptX", "aptx_hd": "aptX HD",
               "aptx_ll": "aptX LL", "ldac": "LDAC", "lc3": "LC3", "lc3plus_hr": "LC3plus", "opus_05": "Opus",
               "msbc": "mSBC", "cvsd": "CVSD", "lc3_swb": "LC3-SWB", "faststream": "FastStream"}


def profile_mode(name):
    """"hifi" (A2DP or LE Audio's music), "headset" (HFP/HSP: the microphone on, lower
    quality), "off" or None for a card profile's name."""
    n = (name or "").lower()
    if n.startswith(("a2dp", "bap-sink", "bap-duplex")) and "source" not in n:
        return "hifi"
    if n.startswith(("headset-head-unit", "hfp", "hsp", "bap-duplex")):
        return "headset"
    if n == "off":
        return "off"
    return None


def codec_of(name, desc=""):
    m = CODEC.search(desc or "")
    if m:
        return m.group(1)
    tail = (name or "").rsplit("-", 1)[-1].lower()
    return CODEC_NAMES.get(tail)


def audio_cards(cards):
    """PipeWire's Bluetooth cards (`pactl --format=json list cards`), by device address:
    {mac: {"card", "active", "mode", "codec", "hifi": profile, "headset": profile}}. hifi and
    headset are the profiles to switch to (the plain one, which lets PipeWire pick the best
    codec, before a codec-specific one), or None when the device has no such profile."""
    out = {}
    for c in cards or []:
        name = c.get("name", "")
        if not name.startswith("bluez_card."):
            continue
        mac = ((c.get("properties") or {}).get("api.bluez5.address") or name.split(".", 1)[1].replace("_", ":"))
        profiles = c.get("profiles") or {}
        avail = [p for p, v in profiles.items() if (v or {}).get("available", True)]

        def best(mode, prefer):
            got = [p for p in avail if profile_mode(p) == mode]
            for p in prefer:
                if p in got:
                    return p
            return got[0] if got else None
        active = c.get("active_profile", "")
        desc = (profiles.get(active) or {}).get("description", "")
        out[mac.upper()] = {"card": name, "active": active, "mode": profile_mode(active),
                            "codec": codec_of(active, desc) if profile_mode(active) not in (None, "off") else None,
                            "hifi": best("hifi", ["a2dp-sink", "a2dp-sink-ldac", "a2dp-sink-aac", "a2dp-sink-sbc_xq",
                                                  "a2dp-sink-sbc"]),
                            "headset": best("headset", ["headset-head-unit", "headset-head-unit-msbc",
                                                        "headset-head-unit-cvsd"])}
    return out


MODE_LABEL = {"hifi": "HI-FI", "headset": "HEADSET + MIC", "off": "NO SOUND"}
MODE_HINT = {"hifi": "Hi-fi: music quality (A2DP), the microphone off",
             "headset": "Headset: the microphone on (HFP), at phone-call quality: the sound gets worse while it's on"}


# ------------------------------------------------------------------ notifications
def theme_icon(name):
    """A bar icon in the theme in force (bromigos theme set writes them), for notifications."""
    state = os.environ.get("XDG_STATE_HOME") or os.path.join(os.path.expanduser("~"), ".local", "state")
    p = os.path.join(state, "bromigos", "theme", "current", "icons", name + ".svg")
    return p if os.path.exists(p) else "bluetooth"


def notify(title, body, icon="bt", tag=None, urgency="low", timeout=2500):
    """A quiet toast through the desktop's notification daemon (dunst, in the theme): low
    urgency, short, no sound; one tag replaces the last toast with it."""
    if not shutil.which("notify-send"):
        return
    argv = ["notify-send", "-a", "Bluetooth", "-u", urgency, "-t", str(timeout), "-i", theme_icon(icon),
            "-h", "string:x-bromigos-sound:none"]
    if tag:
        argv += ["-h", f"string:x-dunst-stack-tag:{tag}"]
    try:
        subprocess.Popen(argv + [title, body], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL, start_new_session=True)
    except OSError:
        pass


# ------------------------------------------------------------------ bluez over D-Bus (GLib)
def _gi():
    import gi
    from gi.repository import Gio, GLib
    return gi, Gio, GLib


def connect_bus():
    """The bus bluez is on: the system bus, or BROMIGOS_BLUEZ_BUS's."""
    _, Gio, _ = _gi()
    addr = os.environ.get("BROMIGOS_BLUEZ_BUS")
    if addr:
        return Gio.DBusConnection.new_for_address_sync(
            addr, Gio.DBusConnectionFlags.AUTHENTICATION_CLIENT | Gio.DBusConnectionFlags.MESSAGE_BUS_CONNECTION,
            None, None)
    return Gio.bus_get_sync(Gio.BusType.SYSTEM, None)


class Bluez:
    """The adapter and its devices, current through bluez's signals. on_change(state) runs
    (on the GLib main loop) after each change, at most once per main-loop pass."""

    def __init__(self, on_change=None, conn=None):
        _, self.Gio, self.GLib = _gi()
        self.on_change = on_change
        self.conn = conn
        self.objects = {}
        self.available = False
        self._subs = []
        self._pending = False
        self.agent = None
        self.root = None

    # -- start and the signals
    def start(self):
        if self.conn is None:
            self.conn = connect_bus()
        c, Gio = self.conn, self.Gio
        sub = c.signal_subscribe
        self._subs = [
            sub(BLUEZ, OM, "InterfacesAdded", None, None, Gio.DBusSignalFlags.NONE, self._added),
            sub(BLUEZ, OM, "InterfacesRemoved", None, None, Gio.DBusSignalFlags.NONE, self._removed),
            sub(BLUEZ, PROPS, "PropertiesChanged", None, None, Gio.DBusSignalFlags.NONE, self._props),
            sub("org.freedesktop.DBus", "org.freedesktop.DBus", "NameOwnerChanged", "/org/freedesktop/DBus",
                BLUEZ, Gio.DBusSignalFlags.NONE, self._owner),
        ]
        self.reload()
        return self

    def stop(self):
        for s in self._subs:
            self.conn.signal_unsubscribe(s)
        self._subs = []

    def reload(self):
        try:
            v = self.conn.call_sync(BLUEZ, "/", OM, "GetManagedObjects", None, None,
                                    self.Gio.DBusCallFlags.NONE, 5000, None)
            self.objects = {p: {i: dict(pr) for i, pr in ifs.items()} for p, ifs in v.unpack()[0].items()}
            self.available = True
        except Exception:
            self.objects, self.available = {}, False
        self._changed()

    def _owner(self, *a):
        self.GLib.timeout_add(300, lambda: self.reload() or False)

    def _added(self, conn, sender, path, iface, signal, params):
        p, ifs = params.unpack()
        o = self.objects.setdefault(p, {})
        for i, pr in ifs.items():
            o.setdefault(i, {}).update(pr)
        self._changed()

    def _removed(self, conn, sender, path, iface, signal, params):
        p, ifs = params.unpack()
        o = self.objects.get(p, {})
        for i in ifs:
            o.pop(i, None)
        if not o:
            self.objects.pop(p, None)
        self._changed()

    def _props(self, conn, sender, path, iface, signal, params):
        i, changed, gone = params.unpack()
        if path not in self.objects or i not in self.objects[path]:
            return
        pr = self.objects[path][i]
        pr.update(changed)
        for k in gone:
            pr.pop(k, None)
        self._changed()

    def _changed(self):
        if self._pending or self.on_change is None:
            return
        self._pending = True

        def fire():
            self._pending = False
            self.on_change(self.state())
            return False
        self.GLib.idle_add(fire)

    def state(self):
        return snapshot(self.objects, self.root) if self.available else unavailable(self.root)

    def find(self, mac):
        mac = mac.upper()
        return next((d for d in self.state()["devices"] if d["mac"] == mac), None)

    # -- calls
    def _call(self, path, iface, method, args=None, timeout=25000, done=None):
        def back(conn, res):
            try:
                conn.call_finish(res)
            except Exception as e:      # GLib.Error
                if done:
                    done(False, explain(e))
                return
            if done:
                done(True, None)
        self.conn.call(BLUEZ, path, iface, method, args, None, self.Gio.DBusCallFlags.NONE, timeout, None, back)

    def _set(self, path, iface, name, value, done=None):
        V = self.GLib.Variant
        self._call(path, PROPS, "Set", V("(ssv)", (iface, name, value)), 10000, done)

    def _adapter(self, done):
        a = self.state().get("adapter")
        if a is None:
            if done:
                done(False, "No Bluetooth adapter" if self.available else explain("ServiceUnknown"))
            return None
        return a["path"]

    def power(self, on, done=None):
        """On (a soft rfkill block is lifted first) or off."""
        path = self._adapter(done)
        if path is None:
            return
        soft, hard = rfkill(self.root)
        if on and hard:
            if done:
                done(False, "Bluetooth is switched off by a hardware switch or key: turn it on there")
            return
        if on and soft:
            subprocess.run(["rfkill", "unblock", "bluetooth"], capture_output=True, timeout=5)
        self._set(path, ADAPTER, "Powered", self.GLib.Variant("b", bool(on)), done)

    def discoverable(self, on, done=None):
        path = self._adapter(done)
        if path is not None:
            self._set(path, ADAPTER, "Discoverable", self.GLib.Variant("b", bool(on)), done)

    def scan(self, on, done=None):
        """Look for devices nearby (they arrive as InterfacesAdded), or stop. bluez stops a
        scan by itself when the process that started it goes."""
        path = self._adapter(done)
        if path is None:
            return
        if on:
            filt = self.GLib.Variant("(a{sv})", ({"Transport": self.GLib.Variant("s", "auto")},))
            self._call(path, ADAPTER, "SetDiscoveryFilter", filt, 5000,
                       lambda ok, err: self._call(path, ADAPTER, "StartDiscovery", None, 10000, done))
        else:
            self._call(path, ADAPTER, "StopDiscovery", None, 10000, done)

    def connect(self, path, done=None):
        """Connect a paired device. A phone connects for its sound only (A2DP source): its
        other profiles (internet sharing, contacts) stay off."""
        d = next((x for x in self.state()["devices"] if x["path"] == path), None)
        if d is not None and d["audio_source"]:
            self._call(path, DEVICE, "ConnectProfile", self.GLib.Variant("(s)", (A2DP_SOURCE,)), 30000, done)
        else:
            self._call(path, DEVICE, "Connect", None, 30000, done)

    def disconnect(self, path, done=None):
        self._call(path, DEVICE, "Disconnect", None, 15000, done)

    def trust(self, path, on, done=None):
        self._set(path, DEVICE, "Trusted", self.GLib.Variant("b", bool(on)), done)

    def rename(self, path, alias, done=None):
        self._set(path, DEVICE, "Alias", self.GLib.Variant("s", alias), done)

    def forget(self, path, done=None):
        d = next((x for x in self.state()["devices"] if x["path"] == path), None)
        adapter = (d or {}).get("adapter") or path.rsplit("/", 1)[0]
        self._call(adapter, ADAPTER, "RemoveDevice", self.GLib.Variant("(o)", (path,)), 10000, done)

    def register_agent(self, agent, done=None):
        """Our agent answers the pairings this process starts (not the system's default)."""
        self.agent = agent
        agent.export(self.conn)
        self._call("/org/bluez", AGENT_MANAGER, "RegisterAgent",
                   self.GLib.Variant("(os)", (AGENT_PATH, "KeyboardDisplay")), 5000, done)

    def unregister_agent(self):
        if self.agent is None:
            return
        try:
            self.conn.call_sync(BLUEZ, "/org/bluez", AGENT_MANAGER, "UnregisterAgent",
                                self.GLib.Variant("(o)", (AGENT_PATH,)), None, self.Gio.DBusCallFlags.NONE, 2000, None)
        except Exception:
            pass
        self.agent.unexport()
        self.agent = None

    def pair(self, path, done=None, step=None):
        """Pair (the agent asks the UI for any code), then trust it, so it reconnects by
        itself when it's switched on, then connect. step(word) reports progress."""
        def paired(ok, err):
            if not ok and "AlreadyExists" not in (err or "") and err != explain("AlreadyExists"):
                if done:
                    done(False, err)
                return
            if step:
                step("trusting")
            self.trust(path, True, lambda ok2, err2: (step and step("connecting"),
                                                      self.connect(path, done)))
        if step:
            step("pairing")
        self._call(path, DEVICE, "Pair", None, 90000, paired)

    def cancel_pair(self, path):
        self._call(path, DEVICE, "CancelPairing", None, 5000, None)


AGENT_XML = """<node><interface name="org.bluez.Agent1">
<method name="Release"/>
<method name="RequestPinCode"><arg type="o" direction="in"/><arg type="s" direction="out"/></method>
<method name="DisplayPinCode"><arg type="o" direction="in"/><arg type="s" direction="in"/></method>
<method name="RequestPasskey"><arg type="o" direction="in"/><arg type="u" direction="out"/></method>
<method name="DisplayPasskey"><arg type="o" direction="in"/><arg type="u" direction="in"/><arg type="q" direction="in"/></method>
<method name="RequestConfirmation"><arg type="o" direction="in"/><arg type="u" direction="in"/></method>
<method name="RequestAuthorization"><arg type="o" direction="in"/></method>
<method name="AuthorizeService"><arg type="o" direction="in"/><arg type="s" direction="in"/></method>
<method name="Cancel"/>
</interface></node>"""


class Agent:
    """bluez's pairing agent (org.bluez.Agent1, capability KeyboardDisplay). Each question
    goes to ui.prompt(what, path, value, reply):

      what "confirm"   value: the 6-digit passkey both sides show; reply(True|False)
           "pin"       the device wants a PIN typed here (older keyboards, car kits); reply("0000"|None)
           "passkey"   a number typed here; reply(123456|None)
           "type"      value: (passkey, entered): type it on the device (a keyboard), then Enter
           "show-pin"  value: a PIN to type on the device
           "authorize" a device asks to pair or connect; reply(True|False)

    ui.cancel() when bluez gives up (the device cancelled, a time-out). A reply of None or
    False rejects (org.bluez.Error.Rejected)."""

    def __init__(self, ui):
        _, self.Gio, self.GLib = _gi()
        self.ui = ui
        self.reg = None
        self.conn = None

    def export(self, conn):
        if self.reg is not None:
            return
        self.conn = conn
        info = self.Gio.DBusNodeInfo.new_for_xml(AGENT_XML).interfaces[0]
        self.reg = conn.register_object(AGENT_PATH, info, self._call, None, None)

    def unexport(self):
        if self.reg is not None:
            self.conn.unregister_object(self.reg)
            self.reg = None

    def _call(self, conn, sender, path, iface, method, params, inv):
        V = self.GLib.Variant
        args = params.unpack()

        def reject():
            inv.return_dbus_error("org.bluez.Error.Rejected", "rejected")

        def reply_bool(ok):
            inv.return_value(None) if ok else reject()

        if method == "Release":
            inv.return_value(None)
        elif method == "Cancel":
            inv.return_value(None)
            self.ui.cancel()
        elif method == "RequestConfirmation":
            self.ui.prompt("confirm", args[0], f"{args[1]:06d}", reply_bool)
        elif method == "RequestAuthorization":
            self.ui.prompt("authorize", args[0], None, reply_bool)
        elif method == "AuthorizeService":
            inv.return_value(None)          # a device we're pairing asks for a profile: yes
        elif method == "RequestPinCode":
            self.ui.prompt("pin", args[0], None,
                           lambda pin: inv.return_value(V("(s)", (str(pin),))) if pin else reject())
        elif method == "RequestPasskey":
            def back(n):
                try:
                    inv.return_value(V("(u)", (int(n),)))
                except (TypeError, ValueError):
                    reject()
            self.ui.prompt("passkey", args[0], None, back)
        elif method == "DisplayPasskey":
            inv.return_value(None)
            self.ui.prompt("type", args[0], (f"{args[1]:06d}", int(args[2])), lambda *_: None)
        elif method == "DisplayPinCode":
            inv.return_value(None)
            self.ui.prompt("show-pin", args[0], args[1], lambda *_: None)
        else:
            inv.return_dbus_error("org.freedesktop.DBus.Error.UnknownMethod", method)
