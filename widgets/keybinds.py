#!/usr/bin/env python3
"""The live keybind list, grouped and described, for the SHORTCUTS panel and rofi.

Source: the running Hyprland. With the Lua config (hypr/hyprland.lua) every bind is made
through hypr/bromigos/keys.lua, which keeps each bind's keys and action; this asks
Hyprland for that list (`hyprctl repl ... dump()`), because `hyprctl binds -j` alone can't
name a Lua bind (its dispatcher is "__lua", and a code:N bind shows no key). With the old
hyprland.conf (the rollback) it reads `hyprctl binds -j` as before. If Hyprland can't be
asked, the config files are read instead: keybinds-dump.lua runs the Lua config with a
stand-in Hyprland (or the .conf is parsed when there is no hyprland.lua).

A bind's action is (kind, payload, old): kind "exec" with a shell command, or "lua" with
dispatcher source (e.g. 'hl.dsp.window.close()'); old is the (dispatcher, arg) of a bind
read from the old format, so it still runs there. run() runs one.

  keybinds.py            print the grouped list
  keybinds.py rofi       searchable cheat sheet; Enter runs the selected bind
"""
import glob
import json
import os
import re
import subprocess
import sys

MOD = "ALT"                     # mainMod in hypr/bromigos/binds.lua ($mainMod in the old .conf)
HYPRCTL = "/usr/bin/hyprctl"
HYPR = os.path.expanduser("~/.config/hypr")
DUMP = os.path.join(os.path.dirname(os.path.realpath(__file__)), "keybinds-dump.lua")
# Display order. The Bromigos pieces come first, grouped by what they're for; the
# stock window-manager binds follow. Within a section, rows follow the order of the
# EXEC / DISPATCH tables below (not the order in the config).
# YOURS: the shortcuts you made with `bromigos keys` (a menu item, an app, a command), by
# the names you picked them by; a default you moved stays in its own section.
SECTIONS = ["VECTOR", "HOLOGRAMS", "PANELS + NOTES", "LIVE LAYER", "YOURS",
            "LAUNCH", "CAPTURE", "WINDOWS", "WORKSPACES", "MEDIA", "SYSTEM"]
BROMIGOS = SECTIONS[:4]
# Sections whose rows can be clicked to run (the panel) — hold-to-use binds never are.
RUNNABLE = BROMIGOS + ["YOURS", "LAUNCH", "CAPTURE"]

KEYNAMES = {
    "RETURN": "ENTER", "ESCAPE": "ESC", "LEFT": "←", "RIGHT": "→", "UP": "↑", "DOWN": "↓",
    "SLASH": "/", "SPACE": "SPACE", "TAB": "TAB", "COMMA": ",", "PERIOD": ".",
    "MOUSE:272": "LMB DRAG", "MOUSE:273": "RMB DRAG",
    "XF86AUDIOMUTE": "MUTE", "XF86AUDIOLOWERVOLUME": "VOL−", "XF86AUDIORAISEVOLUME": "VOL+",
    "XF86AUDIOMICMUTE": "MIC", "XF86MONBRIGHTNESSUP": "BRI+", "XF86MONBRIGHTNESSDOWN": "BRI−",
    "XF86AUDIOPLAY": "PLAY", "XF86AUDIOPREV": "PREV", "XF86AUDIONEXT": "NEXT",
    # a Razer keyboard's macro keys (the razer-keyboard peripheral module; openrazer driver
    # mode); a module that's on names its own keys (_peripherals)
    "F13": "M1", "F14": "M2", "F15": "M3", "F16": "M4", "F17": "M5",
    "F18": "SIDE 1", "F19": "SIDE 2", "F20": "SIDE 3", "F24": "DIAL PRESS",
    "CODE:191": "M1", "CODE:192": "M2", "CODE:193": "M3", "CODE:194": "M4", "CODE:195": "M5",
    "CODE:196": "SIDE 1", "CODE:197": "SIDE 2", "CODE:198": "SIDE 3", "CODE:202": "DIAL PRESS",
}

# (regex on the exec command, description, section). First match wins; the list
# order is also the row order inside each section.
EXEC = [
    # VECTOR: the caretaker on the line, and his voice
    (r"bromigos-holo\b.*\bswitch\b", "VECTOR: emergency switch (off at once; on asks first)", "VECTOR"),
    (r"bromigos-holo\b.*\bclaude\b.*\bfollow\b", "VECTOR: read Claude's replies aloud as they finish (on/off)", "VECTOR"),
    (r"bromigos-holo\b.*\b(vector|pilot)\b", "VECTOR: show / minimize", "VECTOR"),
    (r"bromigos-holo\b.*\bconversation\b", "VECTOR: conversation mode on/off (hands-free)", "VECTOR"),
    (r"bromigos-holo\b.*\bptt\b", "VECTOR: hold to talk", "VECTOR"),
    (r"bromigos-holo\b.*\bmute\b", "VECTOR: voice on/off", "VECTOR"),
    (r"bromigos-holo\b.*\bchat\b", "VECTOR: chat box shown/hidden (or click him; folded away until you point at him)", "VECTOR"),
    (r"vector-converse", "VECTOR: conversation mode on/off (hands-free)", "VECTOR"),
    # HOLOGRAMS: the full-screen decks and 3D views
    (r"bromigos-live\b.*holodeck", "Holo deck (this machine)", "HOLOGRAMS"),
    (r"bromigos-live\b.*\blab\b", "Lab deck: the homelab console (the rack, GPUs, jobs)", "HOLOGRAMS"),
    (r"bromigos-holo\b.*\bgallery\b", "3D model gallery", "HOLOGRAMS"),
    (r"bromigos-live\b.*timeline", "Timeline (scrub the last 72 h)", "HOLOGRAMS"),
    (r"bromigos-live\b.*driftmap", "Drift map (lore star chart)", "HOLOGRAMS"),
    (r"bromigos-live\b.*\bmind\b", "Mind: VECTOR's memory and knowledge", "HOLOGRAMS"),
    (r"bromigos-live\b.*\bops\b", "Ops theater: pushes, CI, Argo, pods", "HOLOGRAMS"),
    (r"bromigos-live\b.*\bswarm\b", "Swarm: repos and agent starships", "HOLOGRAMS"),
    (r"bromigos-live\b.*\bnetmap\b", "Network map: the LAN, traffic, latency", "HOLOGRAMS"),
    (r"bromigos-live\b.*radial", "Radial quick-launch", "HOLOGRAMS"),
    # PANELS + NOTES: the desktop widgets
    (r"bromigos-widgets toggle all", "All desktop panels", "PANELS + NOTES"),
    (r"bromigos-widgets edit", "Edit widgets: move, resize, switch on and off", "PANELS + NOTES"),
    (r"bromigos-widgets toggle shortcuts", "This shortcuts panel", "PANELS + NOTES"),
    (r"keybinds\.py rofi", "Search shortcuts (Enter runs)", "PANELS + NOTES"),
    (r"bromigos-widgets toggle (\w+)", lambda m: f"{m.group(1).capitalize()} panel", "PANELS + NOTES"),
    (r"bromigos-widgets notes", "Type in field notes", "PANELS + NOTES"),
    (r"quick-note", "Quick note from anywhere", "PANELS + NOTES"),
    # LIVE LAYER: the animated background
    (r"bromigos-live\b.*scan-pin", "Scanner: pin hardware schematic", "LIVE LAYER"),
    (r"bromigos-live\b.*scan-hold", "Scanner: hold to scan", "LIVE LAYER"),
    (r"bromigos-live\b.*codec-quiet", "Codec calls: voice on/off", "LIVE LAYER"),
    (r"bromigos-live\b.*tv open", "Den TV: full screen with sound", "LIVE LAYER"),
    (r"bromigos-live\b.*tv next", "Den TV: next channel", "LIVE LAYER"),
    (r"bromigos-live\b.*tv prev", "Den TV: previous channel", "LIVE LAYER"),
    (r"bromigos-live\b.*tv sound", "Den TV: sound on/off", "LIVE LAYER"),
    (r"bromigos-live\b.*tv guide", "Den TV: the channel guide", "LIVE LAYER"),
    (r"^bromigos mute\b", "Mute everything: the theme's sounds and VECTOR's voice", "LIVE LAYER"),
    (r"bromigos-live\b.*mute", "Live layer sounds on/off", "LIVE LAYER"),
    (r"bromigos-live\b.*toggle", "Live background on/off", "LIVE LAYER"),
    (r"bromigos-live\b.*wallpaper", "Wallpaper", "LIVE LAYER"),
    # LAUNCH
    (r"^bromigos-menu\b", "Desktop menu: launch, install, setup, style, update, toggles (typing searches everything)", "LAUNCH"),
    (r"^bromigos-theme-switcher\b|^bromigos-customize\b", "Customize: themes (previews) and widgets", "LAUNCH"),
    (r"^bromigos-wallpaper next\b", "Next wallpaper", "LAUNCH"),
    (r"^bromigos settings\b|^bromigos-settings\b", "Settings: idle and lock, theme, shortcuts, updates", "LAUNCH"),
    (r"^bromigos-webapp launch (\S+)", lambda m: f"Web app: {m.group(1)}", "LAUNCH"),
    (r"swayosd-client --output-volume raise", "Volume up", "MEDIA"),
    (r"swayosd-client --output-volume lower", "Volume down", "MEDIA"),
    (r"swayosd-client --output-volume mute-toggle", "Mute", "MEDIA"),
    (r"swayosd-client --input-volume mute-toggle", "Mic mute", "MEDIA"),
    (r"swayosd-client --brightness raise", "Brightness up", "MEDIA"),
    (r"swayosd-client --brightness lower", "Brightness down", "MEDIA"),
    (r"swayosd-client --playerctl play-pause", "Play / pause", "MEDIA"),
    (r"swayosd-client --playerctl prev", "Previous track", "MEDIA"),
    (r"swayosd-client --playerctl next", "Next track", "MEDIA"),
    (r"rofi -show drun", "Launcher", "LAUNCH"),
    (r"rofi -show window", "Window switcher", "LAUNCH"),
    (r"rofi -show run", "Run a command", "LAUNCH"),
    (r"^kitty\b|^alacritty\b", "Terminal", "LAUNCH"),
    (r"pcmanfm|dolphin|thunar|nautilus", "Files", "LAUNCH"),
    (r"librewolf", "LibreWolf", "LAUNCH"),
    (r"google-chrome", "Chrome", "LAUNCH"),
    (r"discord", "Discord", "LAUNCH"),
    (r"spotify", "Spotify", "LAUNCH"),
    (r"^obs\b", "OBS", "LAUNCH"),
    (r"^steam\b", "Steam", "LAUNCH"),
    (r"reStream", "reMarkable mirror", "LAUNCH"),
    # CAPTURE
    (r"bromigos-shot\b.*region|^grim\b", "Screenshot a region", "CAPTURE"),
    (r"bromigos-shot\b.*screen", "Screenshot the screen", "CAPTURE"),
    (r"bromigos-rec\b|wf-recorder", "Record a region (again to stop)", "CAPTURE"),
    # MEDIA
    (r"set-sink-mute", "Mute", "MEDIA"),
    (r"set-sink-volume\S* \S+ -", "Volume down", "MEDIA"),
    (r"set-sink-volume\S* \S+ \+", "Volume up", "MEDIA"),
    (r"set-source-mute", "Mic mute", "MEDIA"),
    (r"brightnessctl.*\+", "Brightness up", "MEDIA"),
    (r"brightnessctl.*-", "Brightness down", "MEDIA"),
    (r"playerctl play-pause", "Play / pause", "MEDIA"),
    (r"playerctl previous", "Previous track", "MEDIA"),
    (r"playerctl next", "Next track", "MEDIA"),
    # SYSTEM
    (r"lock-session|hyprlock", "Lock", "SYSTEM"),
    (r"power-menu", "Power menu", "SYSTEM"),
    (r"systemctl suspend", "Suspend", "SYSTEM"),
    (r"SIGUSR1 waybar", "Show / hide bar", "SYSTEM"),
]

# Dispatcher binds, keyed by their Lua source with the spaces taken out.
DISPATCH = {
    "hl.dsp.window.close()": ("Close window", "WINDOWS"),
    'hl.dsp.window.fullscreen({mode="maximized"})': ("Maximize", "WINDOWS"),
    'hl.dsp.window.fullscreen({mode="fullscreen"})': ("Fullscreen", "WINDOWS"),
    "hl.dsp.window.float()": ("Float / tile window", "WINDOWS"),
    'hl.dsp.layout("swapwithmaster")': ("Swap with master", "WINDOWS"),
    'hl.dsp.layout("cyclenext")': ("Next window", "WINDOWS"),
    'hl.dsp.layout("cycleprev")': ("Previous window", "WINDOWS"),
    "hl.dsp.window.drag()": ("Move window", "WINDOWS"),
    "hl.dsp.window.resize()": ("Resize window", "WINDOWS"),
    "hl.dsp.workspace.toggle_special()": ("Scratchpad", "WORKSPACES"),
    'hl.dsp.window.move({workspace="special"})': ("Send window to scratchpad", "WORKSPACES"),
    "hl.dsp.exit()": ("Quit Hyprland", "SYSTEM"),
}
MOUSE = {"hl.dsp.window.drag()", "hl.dsp.window.resize()"}    # drag binds: never run from a click
_FOCUS_DIR = re.compile(r'hl\.dsp\.focus\(\{direction="(\w+)"\}\)$')
_MOVE_DIR = re.compile(r'hl\.dsp\.window\.move\(\{direction="(\w+)"\}\)$')
_RESIZE = re.compile(r"hl\.dsp\.window\.resize\(\{x=(-?[\d.]+),")
_WS_GO = re.compile(r'hl\.dsp\.focus\(\{workspace="?([^,"}]+)"?\}\)$')
_WS_MOVE = re.compile(r'hl\.dsp\.window\.move\(\{workspace="?([^,"}]+)"?(,follow=(true|false))?\}\)$')
_FOCUS_MON = re.compile(r"hl\.dsp\.focus\(\{monitor=")
DIRS = {"l": "left", "r": "right", "u": "up", "d": "down"}
# Inputs handled outside Hyprland's bind table (so `hyprctl binds` can't list them):
# (section, keys, description, rank). A peripheral module's dial (bromigos peripheral; its
# daemon reads it), shown when one is on (_peripherals()).
DIAL_ROW = ("VECTOR", ["DIAL TURN"], "VECTOR: cycle voices (auto, then each voice)", 2.5)
_DRANK = {k: len(EXEC) + i for i, k in enumerate(DISPATCH)}


# ------------------------------------------------------------------ sources
def _peripherals():
    """The peripheral modules that are on (`bromigos peripheral status --json`; docs/
    peripherals.md): {"labels": {"CODE:191": "M1", …}, "dial": bool}. Empty without any."""
    try:
        out = subprocess.run(["bromigos", "peripheral", "status", "--json"], capture_output=True,
                             text=True, timeout=5).stdout
        doc = json.loads(out)
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return {}
    labels, dial = {}, False
    for m in doc.get("modules") or [] if isinstance(doc, dict) else []:
        for b in m.get("binds") or []:
            if b.get("keys") and b.get("label"):
                labels[b["keys"].upper()] = b["label"].upper()
        dial = dial or bool(m.get("dial") and m.get("dials"))
    return {"labels": labels, "dial": dial}


def _yours():
    """Your own shortcuts' names (`bromigos keys` keeps them in ~/.config/bromigos/keys.toml):
    {(mods, KEY, kind, payload): what} for each that isn't a bromigOS default moved."""
    import tomllib
    conf = os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")
    try:
        with open(os.path.join(conf, "bromigos", "keys.toml"), "rb") as f:
            doc = tomllib.load(f)
    except (OSError, ValueError):
        return {}
    out = {}
    for b in doc.get("bind") or []:
        if not isinstance(b, dict) or b.get("kind") == "default" or not b.get("keys") or not b.get("what"):
            continue
        mods, key = _split_keys(b["keys"])
        for a in b.get("actions") or []:
            for kind in ("exec", "lua"):
                if isinstance(a, dict) and isinstance(a.get(kind), str):
                    out[(tuple(mods), key.upper(), kind, a[kind])] = b["what"]
    return out


# Each source returns [(mods, key, action)]; the key-up (release) halves of hold binds are
# left out.
def _sig():
    sig = os.environ.get("HYPRLAND_INSTANCE_SIGNATURE")
    d = os.path.join(os.environ.get("XDG_RUNTIME_DIR", "/tmp"), "hypr")
    if sig and os.path.exists(os.path.join(d, sig, ".socket.sock")):
        return sig
    try:      # the variable can be stale (Hyprland restarted): the newest live instance
        live = [n for n in os.listdir(d) if os.path.exists(os.path.join(d, n, ".socket.sock"))]
        return max(live, key=lambda n: os.path.getmtime(os.path.join(d, n)))
    except (OSError, ValueError):
        return None


def _hyprctl_env():
    sig = _sig()
    return {**os.environ, "HYPRLAND_INSTANCE_SIGNATURE": sig} if sig else None


def _hyprctl(*args, timeout=2):
    env = _hyprctl_env()
    if not env:
        return None
    try:
        return subprocess.run([HYPRCTL, *args], capture_output=True, text=True, timeout=timeout, env=env).stdout
    except (OSError, subprocess.TimeoutExpired):
        return None


def _split_keys(keys):
    """'SUPER + SHIFT + K' -> (["SUPER", "SHIFT"], "K"), the mods in the panel's order."""
    parts = [p.strip() for p in keys.split("+") if p.strip()]
    alias = {"WIN": "SUPER", "LOGO": "SUPER", "MOD4": "SUPER", "META": "SUPER", "MOD1": "ALT", "CONTROL": "CTRL"}
    order = ["SUPER", MOD, "CTRL", "SHIFT"]
    mods = {alias.get(p.upper(), p.upper()) for p in parts[:-1]}
    return [m for m in order if m in mods] + sorted(mods - set(order)), (parts[-1] if parts else "")


def _parse_dump(text):
    """keys.lua's dump(): release, mouse, keys, kind, payload per line. None if it isn't one."""
    binds = []
    for line in (text or "").splitlines():
        f = line.split("\t", 4)
        if len(f) != 5 or f[0] not in ("0", "1") or f[3] not in ("exec", "lua"):
            return None
        if f[0] == "1":                         # the key-up half of a hold bind
            continue
        payload = re.sub(r"\\([\\tn])", lambda m: {"\\": "\\", "t": "\t", "n": "\n"}[m.group(1)], f[4])
        mods, key = _split_keys(f[2])
        binds.append((mods, key, (f[3], payload, None)))
    return binds or None


def _lua_live():
    out = _hyprctl("repl", 'return package.loaded["bromigos.keys"].dump()')
    return _parse_dump(out)


def _legacy_live():
    """The old format: Hyprland's own table (`hyprctl binds -j`) names every bind."""
    try:
        raw = json.loads(_hyprctl("binds", "-j") or "")
    except ValueError:
        return None
    if any(b.get("dispatcher") == "__lua" for b in raw):
        return None                             # Lua binds: only keys.lua's list names them
    binds = []
    for b in raw:
        mm = b.get("modmask", 0)
        mods = [n for bit, n in ((64, "SUPER"), (8, MOD), (4, "CTRL"), (1, "SHIFT")) if mm & bit]
        if b.get("release"):                   # the key-up half of a hold bind
            continue
        key = b["key"] or (f"code:{b['keycode']}" if b.get("keycode") else "")   # keycode binds (code:N)
        binds.append((mods, key, _from_legacy(b["dispatcher"], b.get("arg", ""))))
    return binds


def _hypr_binds():
    return _lua_live() or _legacy_live()


def _lua_binds(path=os.path.join(HYPR, "hyprland.lua")):
    """The Lua config's binds, read from its files (no Hyprland needed). None without one."""
    if not os.path.exists(path):
        return None
    try:
        out = subprocess.run(["lua", DUMP, path], capture_output=True, text=True, timeout=10).stdout
    except (OSError, subprocess.TimeoutExpired):
        return None
    return _parse_dump(out)


def _file_binds():
    """Hyprland's own choice of file: hyprland.lua if it exists, else hyprland.conf."""
    lua = _lua_binds()
    if lua is not None:
        return lua
    return [(mods, key, _from_legacy(disp, arg)) for mods, key, disp, arg in _conf_binds()]


def _conf_binds(path=os.path.join(HYPR, "hyprland.conf"), seen=None):
    """The old format, parsed: [(mods, key, dispatcher, arg)]; bindm rows are ("mouse", arg)."""
    seen = seen or set()
    path = os.path.realpath(path)
    if path in seen or not os.path.exists(path):
        return []
    seen.add(path)
    variables, binds = {}, []
    for line in open(path):
        line = line.split("#", 1)[0].strip() if not line.lstrip().startswith("bind") else line.strip()
        m = re.match(r"^\$(\w+)\s*=\s*(.+)$", line)
        if m:
            variables[m.group(1)] = m.group(2).strip()
            continue
        m = re.match(r"^source\s*=\s*(.+)$", line)
        if m:
            for p in glob.glob(os.path.expanduser(m.group(1).strip())):
                binds += _conf_binds(p, seen)
            continue
        m = re.match(r"^(bind[a-z]*)\s*=\s*(.*)$", line)
        if not m:
            continue
        body = re.sub(r"\s+#.*$", "", m.group(2))
        parts = [p.strip() for p in body.split(",", 3)]
        while len(parts) < 4:
            parts.append("")
        mods_s = parts[0]
        for k, v in variables.items():
            mods_s = mods_s.replace("$" + k, "MAINMOD" if k == "mainMod" else v)
        mods = [MOD if t.upper() == "MAINMOD" else t.upper() for t in mods_s.split()]
        if m.group(1).startswith("bindr"):      # the key-up half of a hold bind
            continue
        disp, arg = (parts[2], parts[3]) if m.group(1) != "bindm" else ("mouse", parts[2])
        binds.append((mods, parts[1], disp, arg))
    return binds


# ------------------------------------------------------------------ old format -> Lua
def _lua_str(s):
    """A Lua string literal for any text (bytes outside a safe set become decimal \\ddd escapes)."""
    safe = set(b"abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789 -_./:~@%+=,")
    return '"' + "".join(chr(b) if b in safe else f"\\{b:03d}" for b in s.encode()) + '"'


def _lua_ws(a):
    a = a.strip()
    return a if a.isdigit() else _lua_str(a)


_LEGACY = {   # old dispatcher -> its Lua source (the ones these configs used)
    "killactive": lambda a: "hl.dsp.window.close()",
    "fullscreen": lambda a: 'hl.dsp.window.fullscreen({ mode = "%s" })' % ("maximized" if a.strip() == "1" else "fullscreen"),
    "togglefloating": lambda a: "hl.dsp.window.float()",
    "layoutmsg": lambda a: f"hl.dsp.layout({_lua_str(a.strip())})",
    "exit": lambda a: "hl.dsp.exit()",
    "togglespecialworkspace": lambda a: f"hl.dsp.workspace.toggle_special({_lua_str(a.strip()) if a.strip() else ''})",
    "movetoworkspace": lambda a: f"hl.dsp.window.move({{ workspace = {_lua_ws(a)} }})",
    "movetoworkspacesilent": lambda a: f"hl.dsp.window.move({{ workspace = {_lua_ws(a)}, follow = false }})",
    "workspace": lambda a: f"hl.dsp.focus({{ workspace = {_lua_ws(a)} }})",
    "focusmonitor": lambda a: f"hl.dsp.focus({{ monitor = {_lua_str(a.strip())} }})",
    "movefocus": lambda a: f'hl.dsp.focus({{ direction = "{DIRS.get(a.strip(), a.strip())}" }})',
    "movewindow": lambda a: f'hl.dsp.window.move({{ direction = "{DIRS.get(a.strip(), a.strip())}" }})',
    "resizeactive": lambda a: "hl.dsp.window.resize({{ x = {}, y = {}, relative = true }})".format(*(a.split() + ["0", "0"])[:2]),
}


def _from_legacy(disp, arg):
    """An old-format bind's action; its (dispatcher, arg) stays with it so it runs there."""
    if disp == "exec":
        return ("exec", arg, (disp, arg))
    if disp == "mouse":                         # bindm: drag to move / resize
        return ("lua", "hl.dsp.window.drag()" if arg == "movewindow" else "hl.dsp.window.resize()", None)
    f = _LEGACY.get(disp)
    return ("lua", f(arg) if f else f"{disp} {arg}".strip(), (disp, arg))


# ------------------------------------------------------------------ describe
_LABELS = {}            # a peripheral module's key labels (code:N -> "M1"), set by shortcuts()


def keyname(k):
    u = k.upper()
    return _LABELS.get(u) or KEYNAMES.get(u, u)


def _norm(source):
    return re.sub(r"\s+", "", source)


_DECKS = {}


def plugin_deck(kind):
    """A deck a plugin adds (bromigos-live decks: its own label and hint), or None."""
    if "cat" not in _DECKS:
        try:
            out = subprocess.run(["bromigos-live", "decks", "--json"], capture_output=True, text=True, timeout=8).stdout
            _DECKS["cat"] = {d["kind"]: d for d in json.loads(out or "{}").get("decks") or [] if d.get("source") == "plugin"}
        except (OSError, subprocess.SubprocessError, ValueError):
            _DECKS["cat"] = {}
    return _DECKS["cat"].get(kind)


_DECK_CMD = re.compile(r"^\s*(?:\S*/)?bromigos-live\s+(?:deck\s+)?([a-z][a-z0-9_]*)(?:\s+(?:toggle|open))?\s*$")


def describe(action):
    """(description, section, rank) — rank orders rows inside a section."""
    kind, payload = action[0], action[1]
    if kind == "exec":
        for i, (pat, desc, sec) in enumerate(EXEC):
            m = re.search(pat, payload)
            if m:
                return (desc(m) if callable(desc) else desc), sec, i
        m = _DECK_CMD.match(payload)
        d = plugin_deck(m.group(1)) if m else None
        if d:                                    # a plugin's deck, in its own words, before the radial
            rank = next((i for i, e in enumerate(EXEC) if "radial" in e[0]), len(EXEC))
            return d["label"] + (f" ({d['hint']})" if d.get("hint") else ""), "HOLOGRAMS", rank
        return (os.path.basename(payload.split()[0]) if payload.strip() else "Run"), "LAUNCH", 999
    src = _norm(payload)
    if src in DISPATCH:
        return DISPATCH[src] + (_DRANK[src],)
    n = len(EXEC) + len(DISPATCH)
    m = _FOCUS_DIR.match(src)
    if m:
        return f"Focus {DIRS.get(m.group(1), m.group(1))}", "WINDOWS", n
    m = _MOVE_DIR.match(src)
    if m:
        return f"Move window {DIRS.get(m.group(1), m.group(1))}", "WINDOWS", n + 1
    m = _RESIZE.match(src)
    if m:
        # master layout: the large window's share, whichever window is focused
        return ("Move split left" if m.group(1).startswith("-") else "Move split right"), "WINDOWS", n + 2
    m = _WS_GO.match(src)
    if m:
        return f"Go to workspace {m.group(1)}", "WORKSPACES", n + 3
    m = _WS_MOVE.match(src)
    if m:
        return f"Move window to workspace {m.group(1)}", "WORKSPACES", n + 3
    if _FOCUS_MON.match(src):
        return payload, "WORKSPACES", n + 3
    return payload, "SYSTEM", n + 4


def shortcuts():
    """[(section, keys list, description, action or None)] in display order."""
    binds = _hypr_binds() or _file_binds()
    per = _peripherals()
    _LABELS.clear()
    _LABELS.update(per.get("labels") or {})
    by_combo, order = {}, []
    for mods, key, action in binds:
        combo = (tuple(mods), key.upper())
        focus_mon = action[0] == "lua" and _FOCUS_MON.match(_norm(action[1]))
        if focus_mon and combo in by_combo:
            continue
        if combo not in by_combo:
            order.append(combo)
        if focus_mon:                           # paired with a workspace bind on the same key
            by_combo.setdefault(combo, (mods, key, action))
        else:
            by_combo[combo] = (mods, key, action)
    out, ws_go, ws_move = [], [], []
    yours = _yours()
    for combo in order:
        mods, key, action = by_combo[combo]
        src = _norm(action[1]) if action[0] == "lua" else ""
        if key.isdigit() and _WS_GO.match(src):
            ws_go.append((mods, key))
            continue
        if key.isdigit() and _WS_MOVE.match(src):
            ws_move.append((mods, key))
            continue
        if _FOCUS_MON.match(src):
            continue
        desc, sec, rank = describe(action)
        mine = yours.get((tuple(mods), key.upper(), action[0], action[1]))
        if mine:
            desc, sec, rank = mine, "YOURS", 0
        hold = "hold" in desc                   # press-and-hold binds can't be run from a click
        out.append((sec, mods + [keyname(key)], desc, None if src in MOUSE or hold else action, rank))
    for group, desc in ((ws_go, "Go to workspace"), (ws_move, "Move window to workspace")):
        if group:
            keys = [k for _, k in group]
            rng = f"{keys[0]}–{keys[-1]}" if len(keys) > 1 else keys[0]
            out.append(("WORKSPACES", group[0][0] + [rng], desc, None, 10_000))
    if per.get("dial"):
        sec, keys, desc, rank = DIAL_ROW
        out.append((sec, keys, desc, None, rank))
    out.sort(key=lambda s: (SECTIONS.index(s[0]) if s[0] in SECTIONS else 99, s[4]))   # stable: ties keep config order
    merged, seen = [], {}
    for sec, keys, desc, action, _ in out:     # two binds, one job (ALT+C and ALT+SHIFT+C both close)
        if (sec, desc) in seen:
            i = seen[(sec, desc)]
            s0, k0, d0, a0 = merged[i]
            # keycaps show the keyboard chord; the Razer macro key goes in "(also …)"
            if _macro(k0) and not _macro(keys):
                k0, keys = keys, k0
            elif _macro(k0) == _macro(keys) and len(keys) < len(k0):
                k0, keys = keys, k0
            merged[i] = (s0, k0, f"{d0} (also {'+'.join(keys)})", a0)
            continue
        seen[(sec, desc)] = len(merged)
        merged.append((sec, keys, desc, action))
    return merged


def _macro(keys):
    return any((k.startswith(("M", "SIDE", "DIAL")) and k in KEYNAMES.values()) or k in _LABELS.values()
               for k in keys)


def config_mtime():
    paths = glob.glob(os.path.join(HYPR, "*.conf")) + glob.glob(os.path.join(HYPR, "**", "*.lua"), recursive=True)
    return max((os.path.getmtime(p) for p in paths if os.path.exists(p)), default=0)


def run(action):
    """Run a bind's action in Hyprland (detached): the Lua dispatcher, or the old form
    when the bind came from the old format."""
    kind, payload, old = action
    if old:
        args = ["dispatch", *old]
    elif kind == "exec":
        args = ["dispatch", f"hl.dsp.exec_cmd({_lua_str(payload)})"]
    else:
        args = ["dispatch", payload]
    env = _hyprctl_env()
    if env:
        subprocess.Popen([HYPRCTL, *args], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, env=env)


# ------------------------------------------------------------------ CLI
def _rofi():
    items = shortcuts()
    lines = [f"{'  '.join(k):<22} {d:<30} {s}" for s, k, d, _ in items]
    theme = ('window { width: 760px; } listview { lines: 14; } '
             'element-text { font: "Geist Mono Medium 12"; }')
    r = subprocess.run(["rofi", "-dmenu", "-i", "-no-custom", "-format", "i", "-p", "",
                        "-mesg", f"{len(items)} SHORTCUTS · ENTER RUNS THE SELECTED ONE",
                        "-theme-str", theme], input="\n".join(lines), capture_output=True, text=True)
    if r.returncode != 0 or not r.stdout.strip():
        return
    _, _, _, action = items[int(r.stdout.strip())]
    if action:
        run(action)


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "rofi":
        _rofi()
    else:
        sec = None
        for s, k, d, _ in shortcuts():
            if s != sec:
                print(f"\n{s}")
                sec = s
            print(f"  {' + '.join(k):<24} {d}")
