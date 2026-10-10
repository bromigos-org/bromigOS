"""Your shortcuts, rebound without editing Lua: the logic behind `bromigos keys` (package
bromigos-desktop, /usr/lib/bromigos/lib). No GTK and no rofi here: bin/bromigos-keys is
the picker and the command, lib/bromigos_keycapture.py the "press the new shortcut" window.

- A key combination is a `Combo` ("SUPER + SHIFT + W"): the modifiers in the SHORTCUTS
  panel's order, the key as Hyprland names it, and (when it was pressed) its keycode.
- `State.read()` gathers what is bound and where it comes from: bromigOS's defaults (also
  the ones `bromigos.unbind` turns off), your shortcuts (the record), your web apps' keys,
  the rest of your hyprland.lua (lib/bromigos_keys_eval.lua runs it with a stand-in
  Hyprland), and, when Hyprland runs, its live table (`hyprctl binds -j`).
- `Plan` changes a copy of the record and the web apps' keys: bind (with a clash's owner
  swapped, replaced or refused), unbind, reset. It raises `Clash` when the key is taken and
  `Lockout` when the change would leave the menu or the terminal without a key, or take a
  key you type with.
- `commit()` writes it the safe way: auto-reload off, the files written whole, Hyprland
  --verify-config, one reload, the config errors and the binds themselves checked, auto-
  reload back as it was; anything wrong puts every file back and says what happened (a
  half-written config sends Hyprland into emergency mode).

The record is ~/.config/bromigos/keys.toml; the binds go in a marked block at the end of
~/.config/hypr/hyprland.lua (`-- >>> bromigos keys`, K.exec/K.dsp like the defaults), and
the defaults they take over in another just before the line that loads the defaults
(`-- >>> bromigos keys-unbind`, appended to `bromigos.unbind`). Nothing outside the blocks
is touched. A web app's key stays the web app's (~/.config/bromigos/webapps.toml and its
own block, as `bromigos webapp add --hotkey` writes it).
"""
import copy
import ctypes
import ctypes.util
import fcntl
import importlib.machinery
import importlib.util
import json
import os
import re
import subprocess
import sys
import tomllib
from contextlib import contextmanager
from dataclasses import dataclass, field

import bromigos_hypr as H

HERE = os.path.dirname(os.path.realpath(__file__))
EVAL = os.path.join(HERE, "bromigos_keys_eval.lua")
SUBMAP = "bromigos-capture"     # the capture window's submap (hypr/bromigos/binds.lua)
BLOCK = "keys"                  # after the defaults: your binds
UNBIND_BLOCK = "keys-unbind"    # before the defaults: the default keys you took over
WEBAPPS_BLOCK = "webapps"       # bromigos-webapp's

# ------------------------------------------------------------------ the SHORTCUTS panel's code
_KB = None


def keybinds():
    """widgets/keybinds.py (the SHORTCUTS panel's names for keys and actions), or None."""
    global _KB
    if _KB is None and "keybinds" in sys.modules:
        _KB = sys.modules["keybinds"]
    if _KB is None:
        # beside this checkout first (a dev run, the tests), else the installed panel's
        for p in (os.path.join(HERE, "..", "..", "widgets"), "/usr/lib/bromigos/widgets"):
            if os.path.exists(os.path.join(p, "keybinds.py")):
                if p not in sys.path:
                    sys.path.insert(0, p)
                try:
                    import keybinds as kb
                    _KB = kb
                except Exception:
                    _KB = False
                break
        else:
            _KB = False
    return _KB or None


# ------------------------------------------------------------------ keysyms (libxkbcommon)
_XKB = None


def _xkb():
    global _XKB
    if _XKB is None:
        try:
            lib = ctypes.CDLL(ctypes.util.find_library("xkbcommon") or "libxkbcommon.so.0")
            lib.xkb_keysym_from_name.restype = ctypes.c_uint32
            lib.xkb_keysym_from_name.argtypes = [ctypes.c_char_p, ctypes.c_int]
            lib.xkb_keysym_get_name.restype = ctypes.c_int
            lib.xkb_keysym_get_name.argtypes = [ctypes.c_uint32, ctypes.c_char_p, ctypes.c_size_t]
            _XKB = lib
        except OSError:
            _XKB = False
    return _XKB or None


def keysym(name):
    """The keysym Hyprland matches a bind's key name to (case-insensitive, so "W" is w),
    0 when it names none, None without libxkbcommon."""
    x = _xkb()
    if x is None:
        return None
    b = name.encode()
    return x.xkb_keysym_from_name(b, 1) or x.xkb_keysym_from_name(b, 0)


def keysym_name(sym):
    x = _xkb()
    if x is None or not sym:
        return None
    buf = ctypes.create_string_buffer(64)
    n = x.xkb_keysym_get_name(sym, buf, 64)
    return buf.value.decode() if n > 0 else None


# ------------------------------------------------------------------ key combinations
MOD_ORDER = ("SUPER", "ALT", "CTRL", "SHIFT")
MOD_ALIAS = {"WIN": "SUPER", "LOGO": "SUPER", "MOD4": "SUPER", "META": "SUPER", "MOD1": "ALT",
             "CONTROL": "CTRL", "CTL": "CTRL", "SHFT": "SHIFT"}
MOD_BITS = {"SHIFT": 1, "CAPS": 2, "CTRL": 4, "ALT": 8, "MOD2": 16, "MOD3": 32, "SUPER": 64, "MOD5": 128}
# What the SHORTCUTS panel shows, back to the key names Hyprland reads (typed by a user
# who copied a combo from the panel). The macro-key labels are a module's, not here.
SHOWN = {"ENTER": "RETURN", "ESC": "ESCAPE", "←": "LEFT", "→": "RIGHT", "↑": "UP", "↓": "DOWN",
         "/": "SLASH", "MUTE": "XF86AUDIOMUTE", "VOL+": "XF86AUDIORAISEVOLUME",
         "VOL−": "XF86AUDIOLOWERVOLUME", "VOL-": "XF86AUDIOLOWERVOLUME", "MIC": "XF86AUDIOMICMUTE",
         "BRI+": "XF86MONBRIGHTNESSUP", "BRI−": "XF86MONBRIGHTNESSDOWN", "BRI-": "XF86MONBRIGHTNESSDOWN",
         "PLAY": "XF86AUDIOPLAY", "PREV": "XF86AUDIOPREV", "NEXT": "XF86AUDIONEXT"}
# Keys you type with: bound without a modifier (or with Shift alone) they stop typing.
TYPING = {"SPACE", "RETURN", "KP_ENTER", "BACKSPACE", "TAB", "DELETE", "ESCAPE", "LEFT", "RIGHT",
          "UP", "DOWN", "HOME", "END", "PRIOR", "NEXT", "PAGE_UP", "PAGE_DOWN", "INSERT"}


class BadKeys(ValueError):
    pass


@dataclass(frozen=True)
class Combo:
    """A key combination: the modifiers in the SHORTCUTS panel's order and one key."""
    mods: tuple
    key: str            # "W", "SPACE", "XF86AUDIOMUTE", "F13", "code:191", "mouse:272"
    keycode: int = 0    # when it was pressed: the xkb keycode (evdev + 8)

    @classmethod
    def parse(cls, text, keycode=0):
        """'super + shift + w' -> SUPER + SHIFT + W. Raises BadKeys."""
        if not isinstance(text, str) or not text.strip():
            raise BadKeys("no keys given")
        parts = [p.strip() for p in text.split("+")]
        if text.strip().endswith("+") or any(not p for p in parts):
            raise BadKeys(f"{text!r}: keys look like \"SUPER + SHIFT + W\" (a + key is \"plus\")")
        mods = set()
        for p in parts[:-1]:
            m = MOD_ALIAS.get(p.upper(), p.upper())
            if m not in MOD_BITS:
                raise BadKeys(f"{text!r}: {p} isn't a modifier (SUPER, ALT, CTRL, SHIFT)")
            mods.add(m)
        order = [m for m in MOD_ORDER if m in mods] + sorted(mods - set(MOD_ORDER))
        return cls(tuple(order), canon_key(parts[-1]), keycode)

    def __str__(self):
        return " + ".join(list(self.mods) + [self.key])

    @property
    def modmask(self):
        return sum(MOD_BITS[m] for m in self.mods)

    def display(self):
        """As the SHORTCUTS panel shows it: SUPER + SHIFT + W, ALT + ENTER, VOL+."""
        kb = keybinds()
        key = kb.keyname(self.key) if kb else self.key.upper()
        return " + ".join(list(self.mods) + [key])

    def same(self, other):
        """Whether the two would be the same keys to Hyprland."""
        if other is None or self.modmask != other.modmask:
            return False
        if self.key == other.key:
            return True
        a, b = self, other
        for x, y in ((a, b), (b, a)):
            if x.key.startswith("code:") and y.keycode and x.key[5:].isdigit() and int(x.key[5:]) == y.keycode:
                return True
        if any(k.startswith(("code:", "mouse")) for k in (a.key, b.key)):
            return False
        sa, sb = keysym(a.key), keysym(b.key)
        if sa is None or sb is None:
            return a.key.upper() == b.key.upper()
        return bool(sa) and sa == sb


def _shown_names():
    """SHOWN, and every name the SHORTCUTS panel shows for one key only (its KEYNAMES:
    "," for COMMA), back to the key."""
    out = dict(SHOWN)
    kb = keybinds()
    if kb:
        seen = {}
        for k, v in kb.KEYNAMES.items():
            seen[v] = seen.get(v, 0) + 1
        for k, v in kb.KEYNAMES.items():
            if seen[v] == 1 and v != k and (not k.startswith(("MOUSE", "CODE")) or (k.startswith("CODE:") and v.startswith("KP_"))):
                out.setdefault(v.upper(), k)
    return out


def canon_key(key):
    k = key.strip()
    low = k.lower()
    if low.startswith("code:"):
        if not low[5:].isdigit():
            raise BadKeys(f"{key!r}: a keycode looks like code:191")
        return "code:" + low[5:]
    if low.startswith("mouse"):
        return low
    k = _shown_names().get(k.upper(), k)
    if k.lower().startswith("code:"):
        return canon_key(k)
    sym = keysym(k)
    if sym is None:                     # no libxkbcommon: trust the name
        return k.upper()
    if not sym:
        raise BadKeys(f"{key!r} isn't a key Hyprland knows (names are xkb keysyms: W, SPACE, F13, XF86AudioMute)")
    return (keysym_name(sym) or k).upper()


def typing_key(c):
    """Whether `c` would take a key you type with (no modifier, or Shift alone)."""
    if set(c.mods) - {"SHIFT"}:
        return False
    if c.key.startswith(("code:", "mouse")):
        return False
    return len(c.key) == 1 or c.key in TYPING or (c.key.startswith("KP_") and not c.mods)


# ------------------------------------------------------------------ actions
def lua_str(s):
    """A Lua string literal for any text (bytes outside a safe set: decimal escapes)."""
    safe = set(b"abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789 -_./:~@%+=,()[]{}<>*&^!?#;|'$")
    return '"' + "".join(chr(b) if b in safe else f"\\{b:03d}" for b in s.encode()) + '"'


def lua_unquote(s):
    """The text of a Lua string literal written by string.format("%q") (as keys.lua's
    K.exec does in a bind's description). None if it isn't one."""
    if len(s) < 2 or s[0] != '"' or s[-1] != '"':
        return None
    body, out, i = s[1:-1], bytearray(), 0
    raw = body.encode("utf-8", "surrogateescape")
    esc = {ord("n"): 10, ord("t"): 9, ord("r"): 13, ord("a"): 7, ord("b"): 8, ord("f"): 12,
           ord("v"): 11, ord("\\"): 92, ord('"'): 34, ord("'"): 39, 10: 10}
    while i < len(raw):
        c = raw[i]
        if c != 92:
            out.append(c)
            i += 1
            continue
        i += 1
        if i >= len(raw):
            return None
        c = raw[i]
        if c in esc:
            out.append(esc[c])
            i += 1
        elif 48 <= c <= 57:
            j = i
            while j < len(raw) and j < i + 3 and 48 <= raw[j] <= 57:
                j += 1
            out.append(int(raw[i:j]) & 0xFF)
            i = j
        else:
            return None
    return out.decode("utf-8", "replace")


def action_of(a):
    """(kind, payload) of a record action: {"exec": cmd} or {"lua": source}."""
    if "exec" in a:
        return "exec", a["exec"]
    return "lua", a.get("lua", "")


def short(what, room=48):
    """A name for messages and the record: the SHORTCUTS panel's description without its
    aside ("Desktop menu: launch, install, …" -> "Desktop menu")."""
    w = re.sub(r"\s*\([^)]*\)\s*$", "", what).strip() or what
    if len(w) > room and ": " in w and " " in w.split(": ", 1)[0]:
        w = w.split(": ", 1)[0]
    return w if len(w) <= room else w[:room - 1].rstrip() + "…"


def describe(actions):
    """(what, section) the SHORTCUTS panel would call these actions (the main one: not a
    key-up half, not a focus-the-monitor-first), shortened for messages (short())."""
    kb = keybinds()
    main = None
    for a in actions:
        kind, payload = action_of(a)
        if a.get("release"):
            continue
        if kind == "lua" and re.sub(r"\s+", "", payload).startswith("hl.dsp.focus({monitor="):
            continue
        main = (kind, payload)
        break
    if main is None and actions:
        main = action_of(actions[0])
    if main is None:
        return "nothing", "SYSTEM"
    if kb:
        what, sec, _ = kb.describe((main[0], main[1], None))
        return short(what), sec
    return short(main[1]), "LAUNCH"


# ------------------------------------------------------------------ files
class Paths:
    def __init__(self, config=None, lua=None):
        self.config = config or H.CONFIG
        self.lua = lua or os.path.join(self.config, "hypr", "hyprland.lua")
        self.record = os.path.join(self.config, "bromigos", "keys.toml")
        self.webapps = os.path.join(self.config, "bromigos", "webapps.toml")
        self.lock = os.path.join(self.config, "bromigos", ".keys.lock")


@contextmanager
def locked(paths):
    """One change at a time (two pickers open, a script and the menu)."""
    os.makedirs(os.path.dirname(paths.lock), exist_ok=True)
    with open(paths.lock, "w") as f:
        try:
            fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            raise Refused("another shortcut change is being saved; try again in a moment")
        try:
            yield
        finally:
            fcntl.flock(f, fcntl.LOCK_UN)


@dataclass
class Bind:
    """One of your shortcuts."""
    keys: str           # where it is: a Combo's text
    what: str           # what it does, in words
    kind: str           # default (a bromigOS bind moved here), menu, app, command
    actions: list       # [{"exec": cmd} | {"lua": source}, optional "release": True]
    origin: str = ""    # kind default: the default's own keys, exactly as the defaults write them
    ref: str = ""       # the menu item's id, the desktop entry, …

    def combo(self):
        return Combo.parse(self.keys)


@dataclass
class Record:
    unbind: list = field(default_factory=list)   # the defaults' keys turned off, as they write them
    binds: list = field(default_factory=list)

    @classmethod
    def load(cls, path):
        try:
            with open(path, "rb") as f:
                d = tomllib.load(f)
        except FileNotFoundError:
            return cls()
        except tomllib.TOMLDecodeError as e:
            raise Refused(f"{path} isn't valid TOML ({e}); fix it or remove it (bromigos keys reset)")
        binds = []
        for b in d.get("bind", []):
            if not isinstance(b, dict) or not b.get("keys") or not b.get("actions"):
                continue
            acts = [a for a in b["actions"] if isinstance(a, dict) and ("exec" in a or "lua" in a)]
            binds.append(Bind(b["keys"], b.get("what") or "", b.get("kind") or "command", acts,
                              b.get("from") or "", b.get("ref") or ""))
        return cls([u for u in d.get("unbind", []) if isinstance(u, str)], binds)

    def dumps(self):
        q = lambda s: json.dumps(s, ensure_ascii=False)  # noqa: E731  (a TOML basic string)
        out = ["# Your shortcuts. `bromigos keys` keeps this file and writes it into two marked blocks",
               "# of ~/.config/hypr/hyprland.lua (-- >>> bromigos keys). Change them with `bromigos keys`",
               "# (or SETUP › Shortcuts… in the menu); an edit here only lands at the next change.", ""]
        out.append("# bromigOS default keys turned off (taken over by a shortcut below, or off)")
        out.append("unbind = [" + ", ".join(q(u) for u in self.unbind) + "]")
        for b in self.binds:
            out += ["", "[[bind]]", f"keys = {q(b.keys)}", f"what = {q(b.what)}", f"kind = {q(b.kind)}"]
            if b.origin:
                out.append(f"from = {q(b.origin)}")
            if b.ref:
                out.append(f"ref = {q(b.ref)}")
            acts = []
            for a in b.actions:
                kind, payload = action_of(a)
                acts.append("{ " + f"{kind} = {q(payload)}" + (", release = true" if a.get("release") else "") + " }")
            out.append("actions = [" + ", ".join(acts) + "]")
        return "\n".join(out) + "\n"

    def empty(self):
        return not self.unbind and not self.binds


def _webapp_module():
    """bromigos-webapp's own code (its TOML and its hotkeys block), loaded from beside us."""
    for p in (os.path.join(HERE, "..", "desktop", "bin", "bromigos-webapp"),
              os.path.join(HERE, "..", "bin", "bromigos-webapp"),
              "/usr/lib/bromigos/desktop/bin/bromigos-webapp"):
        if os.path.exists(p):
            loader = importlib.machinery.SourceFileLoader("bromigos_webapp", p)
            spec = importlib.util.spec_from_loader("bromigos_webapp", loader)
            mod = importlib.util.module_from_spec(spec)
            loader.exec_module(mod)
            return mod
    return None


def load_webapps(path):
    try:
        with open(path, "rb") as f:
            return tomllib.load(f).get("app", [])
    except FileNotFoundError:
        return []
    except tomllib.TOMLDecodeError as e:
        raise Refused(f"{path} isn't valid TOML ({e})")


def dump_webapps(apps):
    """(webapps.toml's text, the web apps' hotkeys block), as bromigos-webapp writes them."""
    wa = _webapp_module()
    if wa is None:
        raise Refused("bromigos-webapp isn't installed")
    text = "# Your web apps (bromigos webapp add/remove); each has a desktop entry and may have a hotkey.\n"
    for a in apps:
        text += "\n[[app]]\n"
        for k in ("name", "title", "url", "icon", "hotkey"):
            if a.get(k):
                text += f"{k} = {json.dumps(a[k])}\n"
    return text, wa.hotkeys_block(apps)


# ------------------------------------------------------------------ what is bound
@dataclass
class Entry:
    """One bind as a config makes it."""
    keys: str           # exactly as written
    kind: str           # exec | lua
    payload: str
    release: bool = False
    mouse: bool = False

    def combo(self):
        try:
            return Combo.parse(self.keys)
        except BadKeys:
            return None

    def action(self):
        a = {self.kind: self.payload}
        if self.release:
            a["release"] = True
        return a


@dataclass
class Live:
    """A bind in the running Hyprland's table."""
    combo: object       # Combo, or None when hyprctl can't say which key (a code:N bind)
    kind: str
    payload: str
    release: bool


def evaluate(lua_path, env=None, exclusive=None):
    """(defaults, user, plain, unbind, error) from the config's files (bromigos_keys_eval.lua);
    the keys peripheral modules keep for their keyboards go into `exclusive` (a list)."""
    try:
        r = subprocess.run(["lua", EVAL, lua_path], capture_output=True, text=True, timeout=20,
                           env=env or os.environ)
    except (OSError, subprocess.TimeoutExpired) as e:
        return [], [], [], [], f"can't read the config without Hyprland (lua: {e})"
    defaults, user, plain, unbind, error = [], [], [], [], None
    unesc = lambda s: re.sub(r"\\([\\tn])", lambda m: {"\\": "\\", "t": "\t", "n": "\n"}[m.group(1)], s)  # noqa: E731
    for line in r.stdout.splitlines():
        f = [unesc(x) for x in line.split("\t")]
        if f[0] in ("default", "user") and len(f) == 6:
            e = Entry(f[3], f[4], f[5], f[1] == "1", f[2] == "1")
            (defaults if f[0] == "default" else user).append(e)
        elif f[0] == "unbind" and len(f) == 2:
            unbind.append(f[1])
        elif f[0] == "plain" and len(f) == 2:
            plain.append(f[1])
        elif f[0] == "exclusive" and len(f) == 2 and exclusive is not None:
            exclusive.append(f[1])
        elif f[0] == "error":
            error = "\t".join(f[1:])
    if r.returncode != 0 and error is None:
        error = (r.stderr or "lua failed").strip()
    return defaults, user, plain, unbind, error


def _live_from_json(raw):
    out = []
    for b in raw:
        if b.get("submap") not in (None, "", "bromigos-tv-remote") and str(b.get("submap_universal")).lower() != "true":
            continue
        mods = [n for n, bit in MOD_BITS.items() if b.get("modmask", 0) & bit]
        key = b.get("key") or (f"code:{b['keycode']}" if b.get("keycode") else "")
        combo = None
        if key:
            try:
                combo = Combo.parse(" + ".join(mods + [key]))
            except BadKeys:
                combo = None
        desc = b.get("description") or ""
        m = re.match(r"^hl\.dsp\.exec_cmd\((.*)\)$", desc, re.S)
        cmd = lua_unquote(m.group(1)) if m else None
        if cmd is not None:
            kind, payload = "exec", cmd
        elif desc:
            kind, payload = "lua", desc
        else:
            kind, payload = "lua", f"{b.get('dispatcher', '')} {b.get('arg', '')}".strip()
        out.append(Live(combo, kind, payload, bool(b.get("release"))))
    return out


class Hypr(H.Hyprctl):
    """The running Hyprland (bromigos_hypr.Hyprctl), and its bind table read as Live."""

    def binds(self):
        try:
            return _live_from_json(json.loads(self.run("binds", "-j") or "[]"))
        except ValueError:
            return []


@dataclass
class Owner:
    """Who holds a key: a default, one of your shortcuts, a web app, your own config, or
    something only the running Hyprland has."""
    source: str         # default | yours | webapp | config | live
    keys: str           # where, as written there
    what: str
    ref: object = None  # default: [Entry]; yours: Bind; webapp: its name

    @property
    def movable(self):
        return self.source in ("default", "yours", "webapp")

    def says(self):
        where = {"default": "a bromigOS default", "yours": "your shortcut", "webapp": "a web app's key",
                 "config": "your own bind in hyprland.lua", "live": "a bind only the running Hyprland has"}
        return f"{self.what} ({where[self.source]})"


class Refused(Exception):
    pass


class Clash(Exception):
    def __init__(self, combo, owners, can_swap, target_keys):
        self.combo, self.owners, self.can_swap, self.target_keys = combo, owners, can_swap, target_keys
        super().__init__(f"{combo.display()} is taken: " + "; ".join(o.says() for o in owners))


class Lockout(Exception):
    def __init__(self, reasons):
        self.reasons = reasons
        super().__init__("; ".join(reasons))


class State:
    """Everything bound, and where it comes from. Read once per change."""

    def __init__(self, paths, record, webapps, defaults, user, plain, unbind, live, error=None, exclusive=()):
        self.paths, self.record, self.webapps = paths, record, webapps
        self.defaults, self.user, self.plain, self.unbind, self.live = defaults, user, plain, unbind, live
        self.error = error
        self.exclusive = list(exclusive)   # K.exclude's keys, spelled as the module spells them

    @classmethod
    def read(cls, paths=None, hypr=None, live=True, env=None):
        paths = paths or Paths()
        record = Record.load(paths.record)
        webapps = load_webapps(paths.webapps)
        if not os.path.exists(paths.lua):
            raise Refused(f"there is no {paths.lua} (bromigos update puts one in place)")
        exclusive = []
        defaults, user, plain, unbind, error = evaluate(paths.lua, env, exclusive)
        hl_live = None
        if live and hypr is not None and hypr.running():
            hl_live = hypr.binds()
        return cls(paths, record, webapps, defaults, user, plain, unbind, hl_live, error, exclusive)

    # the defaults, by their keys (in order)
    def default_groups(self):
        groups, order = {}, []
        for e in self.defaults:
            if e.keys not in groups:
                groups[e.keys] = []
                order.append(e.keys)
            groups[e.keys].append(e)
        return [(k, groups[k]) for k in order]

    def default_group(self, keys):
        """The defaults on `keys` (a string as the defaults write it, or any spelling)."""
        for k, g in self.default_groups():
            if k == keys:
                return k, g
        try:
            c = Combo.parse(keys)
        except BadKeys:
            return None, []
        for k, g in self.default_groups():
            gc = g[0].combo()
            if gc is not None and gc.same(c) and not gc.key.startswith("mouse"):
                return k, g
        return None, []

    def your_user_entries(self):
        """The binds after the defaults that are neither your shortcuts nor web apps' keys:
        what you (or a module of yours) wrote in hyprland.lua."""
        ours = []
        for b in self.record.binds:
            for a in b.actions:
                ours.append((b.keys, action_of(a)))
        for w in self.webapps:
            if w.get("hotkey"):
                ours.append((w["hotkey"], ("exec", "bromigos-webapp launch " + w["name"])))
        out = []
        for e in self.user:
            c = e.combo()
            mine = any(c is not None and _same_keys(k, c) and (e.kind, e.payload) == act for k, act in ours)
            if not mine:
                out.append(e)
        return out


def _same_keys(keys, combo):
    try:
        return Combo.parse(keys).same(combo)
    except BadKeys:
        return False


def actions_of(entries):
    return [e.action() for e in entries if not e.mouse]


def _main(actions):
    """(kind, payload) of the action a key press runs (not a key-up half), or None."""
    for a in actions:
        if not a.get("release"):
            return action_of(a)
    return action_of(actions[0]) if actions else None


# ------------------------------------------------------------------ targets
@dataclass
class Target:
    """What a key is being bound to."""
    kind: str           # default | yours | menu | app | webapp | command
    what: str
    actions: list = field(default_factory=list)
    origin: str = ""    # default: its keys as the defaults write them; yours: its keys now
    ref: str = ""       # webapp: its name; menu/app: the item id

    @staticmethod
    def command(cmd, what=None):
        return Target("command", what or cmd, [{"exec": cmd}])

    @staticmethod
    def webapp(name, title=None):
        return Target("webapp", f"Web app: {title or name}", [{"exec": f"bromigos-webapp launch {name}"}], ref=name)


def default_target(state, keys):
    k, group = state.default_group(keys)
    if not group:
        raise Refused(f"no bromigOS default is on {keys}")
    acts = actions_of(group)
    if not acts:
        raise Refused(f"{keys} is a mouse bind; those stay where they are")
    what, _ = describe(acts)
    return Target("default", what, acts, origin=k)


def yours_target(state, keys):
    c = Combo.parse(keys)
    for b in state.record.binds:
        if _same_keys(b.keys, c):
            if b.kind == "default" and state.default_group(b.origin)[1]:
                return default_target(state, b.origin)     # a moved default: its own key puts it back
            return Target("yours", b.what, b.actions, origin=b.keys, ref=b.ref)
    for w in state.webapps:
        if w.get("hotkey") and _same_keys(w["hotkey"], c):
            return Target.webapp(w["name"], w.get("title"))
    raise Refused(f"{c.display()} isn't one of your shortcuts")


# ------------------------------------------------------------------ a change
CRITICAL = (("the menu", re.compile(r"^bromigos-menu$")),)


class Plan:
    """A change to your shortcuts, on copies; `commit()` writes it."""

    def __init__(self, state):
        self.state = state
        self.record = copy.deepcopy(state.record)
        self.webapps = copy.deepcopy(state.webapps)
        self.notes = []          # what changed, in words
        self.expect = []         # (Combo, (kind, payload) or None): what the key does once reloaded
        # defaults you turned off yourself (bromigos.unbind in your own table): off whatever we do
        self.hand_off = set(state.unbind) - set(state.record.unbind)
        self._terminal = self._find_terminal()

    def off(self, keys):
        """Whether the default on `keys` (as the defaults write it) is off in this plan."""
        return keys in self.record.unbind or keys in self.hand_off

    # -- who holds a key, in this plan
    def owners(self, combo):
        out = []
        st = self.state
        for keys, group in st.default_groups():
            if self.off(keys):
                continue
            gc = group[0].combo()
            if gc is not None and gc.same(combo):
                out.append(Owner("default", keys, describe(actions_of(group) or [group[0].action()])[0], group))
        for b in self.record.binds:
            if _same_keys(b.keys, combo):
                out.append(Owner("yours", b.keys, b.what, b))
        for w in self.webapps:
            if w.get("hotkey") and _same_keys(w["hotkey"], combo):
                out.append(Owner("webapp", w["hotkey"], f"Web app: {w.get('title') or w['name']}", w["name"]))
        seen = set()
        for e in st.your_user_entries():
            c = e.combo()
            if c is not None and c.same(combo) and e.keys not in seen and not e.release:
                seen.add(e.keys)
                out.append(Owner("config", e.keys, describe([e.action()])[0], [e]))
        for keys in st.plain:
            if _same_keys(keys, combo) and keys not in seen:
                seen.add(keys)
                out.append(Owner("config", keys, "a bind made with hl.bind (SHORTCUTS can't name it)"))
        if st.live is not None and not out:
            for lv in st.live:
                if lv.combo is not None and lv.combo.same(combo) and not lv.release and not self._configured(lv):
                    out.append(Owner("live", str(lv.combo), describe([{lv.kind: lv.payload}])[0]))
                    break
        return out

    def _configured(self, lv):
        """Whether a live bind is one the config files make (so its owner is known), or
        one this change is about to take away."""
        st = self.state
        for e in st.defaults + st.user:
            c = e.combo()
            if c is not None and c.same(lv.combo) and (e.kind, e.payload) == (lv.kind, lv.payload):
                return True
        return False

    def is_target(self, owner, target):
        if target.kind == "default":
            return (owner.source == "default" and owner.keys == target.origin) or \
                   (owner.source == "yours" and owner.ref.kind == "default" and owner.ref.origin == target.origin)
        if target.kind == "yours":
            return owner.source == "yours" and owner.ref.keys == target.origin
        if target.kind == "webapp":
            return owner.source == "webapp" and owner.ref == target.ref
        return owner.source == "yours" and [action_of(a) for a in owner.ref.actions] == \
            [action_of(a) for a in target.actions]

    def current(self, target):
        """Where the target is now (a Combo), or None."""
        if target.kind == "default":
            for b in self.record.binds:
                if b.kind == "default" and b.origin == target.origin:
                    return b.combo()
            if self.off(target.origin):
                return None
            return Combo.parse(target.origin)
        if target.kind == "yours":
            return Combo.parse(target.origin)
        if target.kind == "webapp":
            for w in self.webapps:
                if w["name"] == target.ref and w.get("hotkey"):
                    return Combo.parse(w["hotkey"])
            return None
        return None

    # -- the changes
    def bind(self, target, combo, resolution=None, confirm=False):
        """Put `target` on `combo`. resolution: None (raise Clash if taken), "replace" (the
        holder loses the key) or "swap" (the holder gets the target's old key)."""
        before = self._critical_keys()
        cur = self.current(target)
        holders = self.owners(combo)
        if (cur is not None and cur.same(combo)) or any(self.is_target(o, target) for o in holders):
            self.notes.append(f"{target.what} is already on {combo.display()}")
            return
        owners = holders
        if owners:
            stuck = [o for o in owners if not o.movable]
            if stuck:
                raise Refused(f"{combo.display()} is {stuck[0].says()}: change it there, or pick another key")
            if resolution not in ("replace", "swap"):
                raise Clash(combo, owners, cur is not None, cur)
            if resolution == "swap" and cur is None:
                raise Refused(f"{target.what} has no key to swap with; replace instead, or pick another key")
            for o in owners:
                self._take(o)
        self._place(target, combo, cur)
        if owners and resolution == "swap":
            for o in owners:
                self._put(o, cur)
        elif owners:
            for o in owners:
                self.notes.append(f"{o.what} lost {combo.display()}")
        self.expect.append((combo, _main(target.actions)))
        self._check_lockout(before, combo, confirm, remote=all(action_of(a)[0] == "exec" and
            action_of(a)[1].startswith("bromigos-live tv remote ") for a in target.actions))

    def unbind(self, combo, confirm=False):
        """Take whatever is on `combo` off it (a default is turned off)."""
        before = self._critical_keys()
        owners = self.owners(combo)
        if not owners:
            raise Refused(f"nothing is bound to {combo.display()}")
        stuck = [o for o in owners if not o.movable]
        if stuck:
            raise Refused(f"{combo.display()} is {stuck[0].says()}: change it there")
        for o in owners:
            self._take(o)
            if o.source == "default":
                self.notes.append(f"{o.what} is off; `bromigos keys reset \"{o.keys}\"` puts it back")
            elif o.source == "yours" and o.ref.kind == "default":
                self.notes.append(f"{o.what} has no key now; `bromigos keys reset \"{o.ref.origin}\"` "
                                  f"puts it back on {Combo.parse(o.ref.origin).display()}")
            else:
                self.notes.append(f"{o.what} no longer has {combo.display()}")
        self.expect.append((combo, None))
        self._check_lockout(before, None, confirm)

    def reset(self, keys=None):
        """Every default back where bromigOS puts it (keys=None), or the one on `keys`."""
        if keys is None:
            n = len(self.record.binds)
            self.record = Record()
            self.notes.append(f"every bromigOS default is back; {n} shortcut{'s' if n != 1 else ''} of yours removed"
                              if n else "every bromigOS default is back")
            for keys_, group in self.state.default_groups():
                gc = group[0].combo()
                for w in self.webapps:
                    if gc is not None and w.get("hotkey") and _same_keys(w["hotkey"], gc):
                        self.notes.append(f"Web app: {w.get('title') or w['name']} lost {gc.display()} (a default's again)")
                        w.pop("hotkey")
            return
        k, group = self.state.default_group(keys)
        if not group:
            raise Refused(f"no bromigOS default is on {keys}")
        if k in self.hand_off:
            raise Refused(f"you turned {k} off yourself (bromigos.unbind in your hyprland.lua): take it out there")
        gc = group[0].combo()
        what = describe(actions_of(group) or [group[0].action()])[0]
        for b in list(self.record.binds):
            if b.kind == "default" and b.origin == k:
                self.record.binds.remove(b)
            elif _same_keys(b.keys, gc):
                self.record.binds.remove(b)
                self.notes.append(f"{b.what} lost {gc.display()}")
        for w in self.webapps:
            if w.get("hotkey") and _same_keys(w["hotkey"], gc):
                self.notes.append(f"Web app: {w.get('title') or w['name']} lost {gc.display()}")
                w.pop("hotkey")
        if k in self.record.unbind:
            self.record.unbind.remove(k)
        self.notes.append(f"{what} is back on {gc.display()}")
        self.expect.append((gc, _main(actions_of(group))))

    # -- the pieces
    def _take(self, o):
        if o.source == "default":
            if o.keys not in self.record.unbind:
                self.record.unbind.append(o.keys)
        elif o.source == "yours":
            if o.ref in self.record.binds:
                self.record.binds.remove(o.ref)
        elif o.source == "webapp":
            for w in self.webapps:
                if w["name"] == o.ref:
                    w.pop("hotkey", None)

    def _put(self, o, combo):
        if o.source == "default":
            k = o.keys
            moved = Bind(str(combo), o.what, "default", actions_of(o.ref), origin=k)
            if Combo.parse(k).same(combo):          # back home
                if k in self.record.unbind:
                    self.record.unbind.remove(k)
            else:
                self.record.binds.append(moved)
        elif o.source == "yours":
            o.ref.keys = str(combo)
            if o.ref.kind == "default" and Combo.parse(o.ref.origin).same(combo):
                if o.ref.origin in self.record.unbind:
                    self.record.unbind.remove(o.ref.origin)
            else:
                self.record.binds.append(o.ref)
        elif o.source == "webapp":
            for w in self.webapps:
                if w["name"] == o.ref:
                    w["hotkey"] = str(combo)
        self.notes.append(f"{o.what} moved to {combo.display()}")
        acts = actions_of(o.ref) if o.source == "default" else (o.ref.actions if o.source == "yours" else
                                                                [{"exec": f"bromigos-webapp launch {o.ref}"}])
        self.expect.append((combo, _main(acts)))

    def _place(self, target, combo, cur):
        k = str(combo)
        if target.kind == "default":
            o = target.origin
            moved = next((b for b in self.record.binds if b.kind == "default" and b.origin == o), None)
            home = Combo.parse(o).same(combo) and o not in self.hand_off
            if moved is not None:
                self.record.binds.remove(moved)
            if home:
                if o in self.record.unbind:
                    self.record.unbind.remove(o)
            else:
                if o not in self.record.unbind:
                    self.record.unbind.append(o)
                self.record.binds.append(Bind(k, target.what, "default", target.actions, origin=o))
        elif target.kind == "yours":
            b = next((b for b in self.record.binds if b.keys == target.origin), None)
            if b is None:
                raise Refused(f"{target.what} isn't one of your shortcuts any more")
            b.keys = k
        elif target.kind == "webapp":
            w = next((w for w in self.webapps if w["name"] == target.ref), None)
            if w is None:
                raise Refused(f"no web app named {target.ref}")
            w["hotkey"] = k
        else:
            self.record.binds.append(Bind(k, target.what, target.kind, target.actions, ref=target.ref))
        self.notes.append(f"{target.what}: {combo.display()}" + (f" (was {cur.display()})" if cur else ""))

    # -- lockout
    def _find_terminal(self):
        """The defaults' terminal command (bromigos.apps.terminal, on MOD + SHIFT + RETURN)."""
        for e in self.state.defaults:
            c = e.combo()
            if e.kind == "exec" and c is not None and c.key == "RETURN" and "SHIFT" in c.mods:
                return e.payload
        return None

    def _keys_for(self, test):
        """The keys (Combo texts) that run an action `test` matches, in this plan."""
        keys = set()
        for k, group in self.state.default_groups():
            if self.off(k):
                continue
            if any(e.kind == "exec" and test(e.payload) for e in group):
                keys.add(k)
        for b in self.record.binds:
            if any(action_of(a)[0] == "exec" and test(action_of(a)[1]) for a in b.actions):
                keys.add(b.keys)
        for e in self.state.your_user_entries():
            if e.kind == "exec" and test(e.payload):
                keys.add(e.keys)
        return keys

    def _critical_keys(self):
        out = {}
        for name, rx in CRITICAL:
            out[name] = self._keys_for(lambda p, rx=rx: bool(rx.match(p.strip())))
        if self._terminal:
            out["the terminal"] = self._keys_for(lambda p: p.strip() == self._terminal.strip())
        return out

    def _check_lockout(self, before, combo, confirm, remote=False):
        reasons = []
        after = self._critical_keys()
        for name, had in before.items():
            if had and not after.get(name):
                reasons.append(f"that leaves {name} without a key (it's how you get back to everything, "
                               f"Shortcuts too)")
        if combo is not None and typing_key(combo) and not remote:
            reasons.append(f"{combo.display()} without a modifier stops that key from typing in every app")
        if reasons and not confirm:
            raise Lockout(reasons)
        self.risks = reasons

    # -- the result
    def changed(self):
        return self.record != self.state.record or self.webapps != self.state.webapps


# ------------------------------------------------------------------ the blocks
def unbind_body(record):
    keys = ", ".join(lua_str(k) for k in record.unbind)
    return "\n".join([
        "-- bromigOS default keys your shortcuts took over or turned off (generated by `bromigos keys`;",
        "-- change them with it, not here: `bromigos keys reset` puts them all back).",
        'bromigos = type(bromigos) == "table" and bromigos or {}',
        "bromigos.unbind = bromigos.unbind or {}",
        f"for _, keys in ipairs({{ {keys} }}) do",
        "    table.insert(bromigos.unbind, keys)",
        "end",
    ])


def spelled(keys, exclusive=()):
    """`keys` as the config must write them: a key a peripheral module keeps for its keyboard
    (K.exclude, keyed by its exact text) in the module's own spelling, so the bind gets the
    exclusion; anything else as it is."""
    for x in exclusive:
        if _same_keys(x, Combo.parse(keys)):
            return x
    return keys


def binds_body(record, exclusive=()):
    lines = ["-- Your shortcuts (generated by `bromigos keys` from ~/.config/bromigos/keys.toml; change",
             "-- them with `bromigos keys` or SETUP › Shortcuts… in the menu, not here).",
             "do",
             '    local K = require("bromigos.keys")']
    for b in record.binds:
        note = re.sub(r"[\r\n]+", " ", b.what)[:80]
        if b.kind == "default" and b.origin:
            note += f" (from {b.origin})"
        for i, a in enumerate(b.actions):
            kind, payload = action_of(a)
            fn = "K.exec" if kind == "exec" else "K.dsp"
            opts = ", { release = true }" if a.get("release") else ""
            tail = f"   -- {note}" if i == 0 else ""
            lines.append(f"    {fn}({lua_str(spelled(b.keys, exclusive))}, {lua_str(payload)}{opts}){tail}")
    lines.append("end")
    return "\n".join(lines)


def drop_block(lua, name):
    """`lua` without the marked block `name`, and the blank line H.with_block put beside
    it; nothing else changes."""
    begin, end = H.markers(name)
    b = H.find_marker(lua, begin)
    e = H.find_marker(lua, end, b + 1) if b >= 0 else -1
    if b < 0 or e < 0:
        return lua
    nl = lua.find("\n", e)
    e = len(lua) if nl < 0 else nl + 1
    head, tail = lua[:b], lua[e:]
    if tail == "" and head.endswith("\n\n"):
        head = head[:-1]
    elif tail.startswith("\n") and (head == "" or head.endswith("\n")):
        tail = tail[1:]
    return head + tail


def render(lua, record, webapps_block=None, webapps_changed=False, exclusive=()):
    """The new hyprland.lua: your two blocks (and the web apps' when their keys changed)."""
    if record.unbind:
        lua = H.with_block(lua, UNBIND_BLOCK, unbind_body(record), before_dofile=True)
    else:
        lua = drop_block(lua, UNBIND_BLOCK)
    if record.binds:
        lua = H.with_block(lua, BLOCK, binds_body(record, exclusive), before_dofile=False)
    else:
        lua = drop_block(lua, BLOCK)
    if webapps_changed:
        if webapps_block is not None and "K.exec(" in webapps_block:
            lua = H.with_block(lua, WEBAPPS_BLOCK, webapps_block, before_dofile=False)
        else:
            lua = drop_block(lua, WEBAPPS_BLOCK)
    return lua


# ------------------------------------------------------------------ saving
def _bound_live(hypr, combo, action):
    """Whether the running Hyprland has `action` on `combo` (None: nothing on it)."""
    live = [lv for lv in hypr.binds() if lv.combo is not None and lv.combo.same(combo) and not lv.release]
    if action is None:
        return not live
    return any((lv.kind, lv.payload) == tuple(action) for lv in live)


def commit(plan, hypr=None, wait=1.5):
    """Write the plan the safe way (bromigos_hypr.save: auto-reload off, the files whole,
    verified, one reload, no new config errors, the binds checked live). Returns (ok,
    message); not ok means every file is as it was and Hyprland runs what it ran."""
    paths = plan.state.paths
    hypr = hypr or Hypr()
    lua = H.read_file(paths.lua)
    if lua is None:
        return False, f"there is no {paths.lua}"
    files = {paths.record: plan.record.dumps()}
    if plan.record.empty() and H.read_file(paths.record) is None:
        files[paths.record] = None
    webapps_changed = plan.webapps != plan.state.webapps
    wa_block = None
    if webapps_changed:
        files[paths.webapps], wa_block = dump_webapps(plan.webapps)
    try:
        files[paths.lua] = render(lua, plan.record, wa_block, webapps_changed, plan.state.exclusive)
    except ValueError as e:
        return False, str(e)

    def check():
        for c, a in plan.expect:
            if not _bound_live(hypr, c, a):
                return f"{c.display()} isn't {'free' if a is None else 'bound'} in Hyprland after the reload"
        return None

    ok, detail = H.save(files, lua=paths.lua, hypr=hypr, check=check, wait=wait)
    if ok and detail == "reloaded":
        detail = "saved and live"
    return ok, detail


# ------------------------------------------------------------------ listing
def listing(state):
    """Your shortcuts and the defaults you turned off, for `bromigos keys list`."""
    rows, off = [], []
    moved = {b.origin for b in state.record.binds if b.kind == "default"}
    for b in state.record.binds:
        try:
            c = b.combo()
        except BadKeys:
            continue
        stale = False
        if b.kind == "default":
            _, group = state.default_group(b.origin)
            stale = bool(group) and actions_of(group) != b.actions
        rows.append({"keys": str(c), "display": c.display(), "what": b.what, "kind": b.kind,
                     "from": b.origin or None, "source": "yours", "actions": b.actions, "stale": stale})
    for w in state.webapps:
        if w.get("hotkey"):
            try:
                c = Combo.parse(w["hotkey"])
            except BadKeys:
                continue
            rows.append({"keys": str(c), "display": c.display(), "what": f"Web app: {w.get('title') or w['name']}",
                         "kind": "webapp", "from": None, "source": "webapp",
                         "actions": [{"exec": f"bromigos-webapp launch {w['name']}"}], "stale": False})
    for k in state.record.unbind:
        if k in moved:
            continue
        _, group = state.default_group(k)
        what = describe(actions_of(group))[0] if group else "a default that isn't there any more"
        try:
            disp = Combo.parse(k).display()
        except BadKeys:
            disp = k
        off.append({"keys": k, "display": disp, "what": what})
    return rows, off


def everything(state):
    """Every key the config binds, in the SHORTCUTS panel's sections and order, each with
    where it comes from and whether `bromigos keys` can move it (`list --all`)."""
    kb = keybinds()
    order = list(kb.SECTIONS) if kb else []
    plan = Plan(state)
    out = []

    def add(keys, what, section, source, movable, frm=None, why=None):
        try:
            c = Combo.parse(keys)
            disp, keys = c.display(), str(c)
        except BadKeys:
            disp = keys
        out.append({"keys": keys, "display": disp, "what": what, "section": section, "source": source,
                    "movable": movable, "from": frm, "why": why})

    for keys, group in state.default_groups():
        if plan.off(keys):
            continue
        acts = actions_of(group)
        if not acts:
            what, sec = describe([group[0].action()])
            add(keys, what, sec, "default", False, why="a mouse bind: it stays where it is")
            continue
        what, sec = describe(acts)
        add(keys, what, sec, "default", True)
    for b in state.record.binds:
        what, sec = describe(b.actions) if b.kind == "default" else (b.what, "YOURS")
        add(b.keys, b.what if b.kind != "default" else what, sec, "yours", True, frm=b.origin or None)
    for w in state.webapps:
        if w.get("hotkey"):
            add(w["hotkey"], f"Web app: {w.get('title') or w['name']}", "LAUNCH", "webapp", True)
    seen = set()
    for e in state.your_user_entries():
        if e.release or e.keys in seen:
            continue
        seen.add(e.keys)
        what, sec = describe([e.action()])
        add(e.keys, what, sec, "config", False, why="your own bind in hyprland.lua: change it there")
    for keys in state.plain:
        if keys not in seen:
            seen.add(keys)
            add(keys, "a bind made with hl.bind", "SYSTEM", "config", False,
                why="made with hl.bind in your hyprland.lua: change it there")
    rank = {s: i for i, s in enumerate(order)}
    out.sort(key=lambda r: rank.get(r["section"], len(rank)))      # stable: the config's order within
    return out


# ------------------------------------------------------------------ undo
def undo_path():
    return os.path.join(H.STATE, "bromigos", "keys", "undo.json")


def save_undo(state, said):
    """What was there before a change, for `bromigos keys undo` (one step)."""
    doc = {"schema": 1, "said": said, "record": state.record.dumps(),
           "hotkeys": {w["name"]: w.get("hotkey") for w in state.webapps}}
    path = undo_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    H.write_file(path, json.dumps(doc, ensure_ascii=False))


def undo_plan(state):
    """A plan that puts back what the last change replaced. Raises Refused."""
    try:
        with open(undo_path()) as f:
            doc = json.load(f)
    except (OSError, ValueError):
        raise Refused("nothing to undo")
    import tempfile
    with tempfile.NamedTemporaryFile("w", suffix=".toml", delete=False) as f:
        f.write(doc.get("record") or "")
        tmp = f.name
    try:
        record = Record.load(tmp)
    finally:
        os.unlink(tmp)
    plan = Plan(state)
    plan.record = record
    hot = doc.get("hotkeys") or {}
    for w in plan.webapps:
        if w["name"] in hot:
            if hot[w["name"]]:
                w["hotkey"] = hot[w["name"]]
            else:
                w.pop("hotkey", None)
    said = doc.get("said") or "the last change"
    # undoing an undo is the change again
    plan.notes.append(said[len("undone: "):] if said.startswith("undone: ") else f"undone: {said}")
    return plan
