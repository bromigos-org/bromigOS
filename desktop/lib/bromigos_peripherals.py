"""The peripheral modules' running parts (docs/peripherals.md): a keyboard's dial as VECTOR's
voice dial and its volume roller, and lighting that follows VECTOR. The daemon
(bromigos-peripherals, a user service) runs these for the modules that are on; which
those are, and their devices, it asks `bromigos peripheral status --json` (the rules live
in bromigOS's core, once).

VECTOR's side is his state file, $XDG_RUNTIME_DIR/bromigos-vector.json (vector repo,
README "His state"): `voices` (role, name, colour, in his order), `voice_mode`, `voice`,
`voice_colour`, `mood`, `state`, `conversation`. The dial pins a voice with
`bromigos-holo voice <role>`; the lighting reads the colour he shows and the theme's
`primary`, `warn` and `danger` (bromigos_theme), so a desk lit by him matches his hologram.

Everything here is plain functions and small classes over injected pieces (the state, the
palette, the lighting backend, the commands), so tests run without devices or a desktop.
"""
import json
import os
import subprocess
import time

RUNTIME = os.environ.get("XDG_RUNTIME_DIR") or f"/run/user/{os.getuid()}"
VECTOR_STATE = os.path.join(RUNTIME, "bromigos-vector.json")
VECTOR_SOCK = os.path.join(RUNTIME, "bromigos-holo.sock")
HOLO = "/usr/bin/bromigos-holo"           # VECTOR (bromigos-vector)

# Linux input event types and codes the dial reads (linux/input-event-codes.h; python-evdev's
# ecodes has the same numbers, so these stay importable without it)
EV_KEY, EV_REL = 0x01, 0x02
REL_HWHEEL, REL_WHEEL = 0x06, 0x08
KEY_VOLUMEDOWN, KEY_VOLUMEUP = 114, 115

STEP_GAP = 0.12           # at most one voice step per slice of a fast turn (a detent burst)
VOLUME_STEP = 2           # percent per roller click, capped at 100%
REST_BRIGHTNESS, ACTIVE_BRIGHTNESS = 55, 100
AUTO_LABEL = "AUTO — VECTOR picks per sentence"


# ------------------------------------------------------------------ VECTOR's state

def read_state(path=VECTOR_STATE, sock=VECTOR_SOCK):
    """VECTOR's published state, or None when his daemon isn't running (no socket) or the
    file can't be read."""
    if sock and not os.path.exists(sock):
        return None
    try:
        with open(path) as f:
            st = json.load(f)
        return st if isinstance(st, dict) else None
    except (OSError, ValueError):
        return None


def voice_label(name, role):
    """'governor_voss' -> 'Governor Voss'; the role when the voice has no name."""
    n = (name or role or "").replace("_", " ").replace("-", " ").strip()
    return " ".join(w[:1].upper() + w[1:] for w in n.split()) or role


def voice_order(st):
    """The dial's stops: auto, then each of his voices in his order. [(mode, label)]"""
    out = [("auto", AUTO_LABEL)]
    for v in (st or {}).get("voices") or []:
        if isinstance(v, dict) and v.get("role"):
            out.append((v["role"], voice_label(v.get("name"), v["role"])))
    return out


def next_voice(st, direction):
    """(mode, label) one stop from the current mode, `direction` +1 (right) or -1 (left);
    None when VECTOR publishes no voices (an older VECTOR: the dial then cycles with
    `voice cycle`)."""
    order = voice_order(st)
    if len(order) < 2:
        return None
    modes = [m for m, _ in order]
    cur = (st or {}).get("voice_mode") or "auto"
    i = modes.index(cur) if cur in modes else 0
    return order[(i + direction) % len(order)]


class Dial:
    """Turns of the dial (REL_HWHEEL) step VECTOR's voice; the roller on the same interface
    (volume keys, or REL_WHEEL) steps the volume. `run(argv)` runs a command; `state()`
    reads VECTOR's state; `clock()` is monotonic seconds."""

    def __init__(self, run, state=read_state, clock=time.monotonic, holo=HOLO, roller=True):
        self.run, self.state, self.clock, self.holo, self.roller = run, state, clock, holo, roller
        self.last_step = -1e9
        self.unhandled = 0

    def event(self, etype, code, value):
        """One input event. Returns what it did ("voice <mode>", "volume +2%", None)."""
        if etype == EV_REL and code == REL_HWHEEL and value:
            now = self.clock()
            if now - self.last_step < STEP_GAP:
                return None
            self.last_step = now
            return self.step(1 if value > 0 else -1)
        if not self.roller:
            return None
        if etype == EV_KEY and value in (1, 2) and code in (KEY_VOLUMEUP, KEY_VOLUMEDOWN):
            return self.volume(1 if code == KEY_VOLUMEUP else -1)
        if etype == EV_REL and code == REL_WHEEL and value:
            return self.volume(value)
        return None

    def step(self, direction):
        st = self.state()
        if st is None:
            self.notify("VOICE", "VECTOR isn't running")
            return "voice: vector not running"
        nxt = next_voice(st, direction)
        if nxt is None:
            self.run([self.holo, "voice", "cycle"])
            return "voice cycle"
        mode, label = nxt
        self.run([self.holo, "voice", mode])
        self.notify("VOICE", label)
        return f"voice {mode}"

    def volume(self, clicks):
        pct = f"{VOLUME_STEP * abs(clicks)}%{'+' if clicks > 0 else '-'}"
        self.run(["wpctl", "set-volume", "-l", "1.0", "@DEFAULT_AUDIO_SINK@", pct])
        return f"volume {pct}"

    def notify(self, title, body):
        # a quiet stack: each turn replaces the last (dunst's stack tag), no sound cue
        self.run(["notify-send", "-a", "VECTOR", "-t", "1500", "-h", "string:x-dunst-stack-tag:vector-voice",
                  "-h", "string:x-bromigos-sound:none", title, body])


# ------------------------------------------------------------------ lighting

def lighting_target(st, colour, follow="vector"):
    """(effect, '#rrggbb', brightness) for VECTOR's state. `colour(role)` is the theme's
    colour for primary / warn / danger. Not running: the theme's primary, dimmed.
    `follow` "theme": the theme's primary, whatever VECTOR does."""
    if follow == "theme" or st is None:
        return ("static", colour("primary"), REST_BRIGHTNESS)
    mood = st.get("mood") or "calm"
    if mood == "alarmed":
        return ("breath", colour("danger"), ACTIVE_BRIGHTNESS)
    if mood == "concerned":
        return ("static", colour("warn"), ACTIVE_BRIGHTNESS)
    col = st.get("voice_colour")
    if not (isinstance(col, str) and col.startswith("#") and len(col) == 7):
        role = st.get("voice_mode") if st.get("voice_mode") not in (None, "auto") else st.get("voice", "main")
        col = next((v.get("colour") for v in st.get("voices") or [] if isinstance(v, dict) and v.get("role") == role),
                   None) or colour("primary")
    active = st.get("state") in ("thinking", "speaking", "listening", "working") or bool(st.get("conversation"))
    return ("static", col, ACTIVE_BRIGHTNESS if active or mood == "excited" else REST_BRIGHTNESS)


def rgb(hexcol):
    h = hexcol.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def apply_openrazer(devices, effect, colour, brightness, log=print):
    """Lights openrazer devices (openrazer.client's): the keyboard's matrix, a mouse's logo
    and scroll wheel zones. A device that drops out mid-write is logged and skipped."""
    r, g, b = rgb(colour)
    for d in devices:
        try:
            if d.has("brightness"):
                d.brightness = brightness
            if d.has("lighting_static"):
                if effect == "breath" and d.has("lighting_breath_single"):
                    d.fx.breath_single(r, g, b)
                else:
                    d.fx.static(r, g, b)
            else:                                   # a mouse: its logo and wheel zones
                k = brightness / 100
                for zone in ("logo", "scroll"):
                    fx = getattr(d.fx.misc, zone, None)
                    if fx is not None and d.has(f"lighting_{zone}_static"):
                        fx.static(int(r * k), int(g * k), int(b * k))
        except Exception as e:  # noqa: BLE001  (dbus errors of every kind: the device left)
            log(f"lighting: {getattr(d, 'name', '?')}: {e}")


class Lighting:
    """Follows VECTOR: writes only when the target changes, finds the devices again every
    minute (a keyboard plugged in) and after a failure. `devices()` lists the backend's
    devices; `pids` (USB product ids, ints) keeps only the module's own (scope "device")."""

    def __init__(self, devices, colour, state=read_state, apply=apply_openrazer, clock=time.monotonic, pids=None,
                 follow="vector"):
        self.list_devices, self.colour, self.state, self.apply, self.clock = devices, colour, state, apply, clock
        self.follow = follow
        self.pids = set(pids) if pids else None
        self.devices, self.found_at, self.last = [], -1e9, None

    def tick(self):
        if not self.devices or self.clock() - self.found_at > 60:
            try:
                devs = list(self.list_devices())
            except Exception:  # noqa: BLE001  (the backend's daemon isn't up yet)
                devs = []
            if self.pids is not None:
                devs = [d for d in devs if getattr(d, "_pid", None) in self.pids]
            self.devices, self.found_at, self.last = devs, self.clock(), None   # re-apply after a (re)find
        want = lighting_target(None if self.follow == "theme" else self.state(), self.colour, self.follow)
        if self.devices and want != self.last:
            self.apply(self.devices, *want)
            self.last = want
            return want
        return None


# ------------------------------------------------------------------ the modules that are on

def status(bromigos="bromigos", timeout=10):
    """`bromigos peripheral status --json`, or None."""
    try:
        out = subprocess.run([bromigos, "peripheral", "status", "--json"], capture_output=True, text=True,
                             timeout=timeout).stdout
        doc = json.loads(out)
        return doc if isinstance(doc, dict) and doc.get("ok") else None
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return None


def plan(doc):
    """What to run from a status document: (dials, lighting), where dials is
    [(module id, event node, roller on)] and lighting is None or (backend, pids or None,
    follow: "vector" or "theme")."""
    dials, light = [], None
    for m in (doc or {}).get("modules") or []:
        dial = m.get("dial")
        if dial:
            for node in m.get("dials") or []:
                dials.append((m.get("id"), node, bool(dial.get("roller"))))
        r = m.get("rgb")
        if r and m.get("rgb_scope") != "off":
            if m.get("rgb_scope") == "device":
                pids = {int(f["usb"].split(":")[1], 16) for f in m.get("found") or [] if ":" in f.get("usb", "")}
                if light is None or light[1] is not None:
                    light = (r.get("backend"), (light[1] if light else set()) | pids, r.get("follow") or "vector")
            else:
                light = (r.get("backend"), None, r.get("follow") or "vector")   # every device the backend lights
    return dials, light


def hypr_names(doc):
    """The Hyprland device names the keys are bound for (a change means `refresh`)."""
    return sorted(n for m in (doc or {}).get("modules") or [] for n in m.get("devices") or [])
