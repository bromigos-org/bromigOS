"""Den TV's bumps: short clips between items and on a channel change, like a network's
interstitials, mostly in the night block (live/README.md, "Bumps").

A bump is a short, silent clip (5 to 15 seconds) with an optional caption, which the den
draws over the clip in the theme's colours (the clips carry no text, so a caption is
translatable and readable at any size). A bump has no sound of its own: the screen is quiet
while it plays. Bumps come
in packs. A pack is a folder holding bumps.json:

    {"schema": 1, "pack": "static", "title": "STATIC's bumps",
     "bumps": [{"id": "still-lit", "file": "clips/still-lit.mp4", "seconds": 6.5,
                "roles": ["open", "between"], "caption": "STILL LIT",
                "about": "RECON's OWL keeps watch on a cliff at night"}]}

Paths are relative to bumps.json. Roles say when a bump may play:

    between   between two items on a channel; the channel waits for it, so nothing is missed
    tune      on a channel change (short ones); the channel doesn't wait: it's live
    open      the night block's first bump
    close     the night block's last: the first item boundary after it ends

Packs are looked for in $BROMIGOS_BUMPS (folders, colon-separated), then
~/.local/share/bromigos/bumps/<pack>/, then /usr/share/bromigos/bumps/<pack>/ (bromigos-mascot-art
installs STATIC's). The first pack of a name wins.

The settings, [tv.bumps] in ~/.config/bromigos-live/config.toml:

    mode = "night"          # "night" (only in the night block), "always", or "off"
    night = "22:00-04:00"   # the night block, local time (it may run past midnight)
    every = 20              # minutes: the least time between two bumps between items
    every_night = 12        #   ... in the night block
    tune_every = 30         # minutes between two bumps on a channel change
    max = 10                # at most this many a night (outside it, a day)
    packs = []              # only these packs (by name); empty: every pack installed

`bromigos mascot off` turns them off too. A bump never plays twice in a row, nor one of the
last RECENT. The state (when the last played, how many tonight) is in
~/.local/state/bromigos-live/tv-bumps.json, so the cap holds over a restart.

    packs(env=None) -> [Pack]                   every pack found, by name
    settings(cfg) -> dict                       [tv.bumps] with its defaults
    night(t, spec) -> "YYYY-MM-DD" or None      the night block t falls in (its start's date)
    choose(kind, t, cfg, state, bumps, rng)     -> (Bump, role) or None: "between" or "tune"
    record(state, bump, role, t, cfg)           the state after it plays
    load_state() / save_state(st)
"""
import json
import os
import random
import re
import tempfile
import time

ROLES = ("between", "tune", "open", "close")
MODES = ("night", "always", "off")
DEFAULTS = {"mode": "night", "night": "22:00-04:00", "every": 20, "every_night": 12, "tune_every": 30,
            "max": 10, "packs": []}
RECENT = 3                    # none of the last few again
TUNE_MAX = 6.0                # seconds: a tune bump is short (the channel is live underneath)
CLOSE_WINDOW = 90 * 60        # the sign-off: the first boundary this soon after the night block ends
GAP = 120                     # seconds: never two bumps closer than this, whatever the kinds
STATE_DIR = os.path.join(os.environ.get("XDG_STATE_HOME") or os.path.expanduser("~/.local/state"), "bromigos-live")
STATE = os.path.join(STATE_DIR, "tv-bumps.json")


class Bump(dict):
    """id ("pack/id"), path, seconds, roles, caption, about, pack."""
    __getattr__ = dict.get


class Pack:
    def __init__(self, name, folder, title, bumps):
        self.name, self.folder, self.title, self.bumps = name, folder, title, bumps

    def __repr__(self):
        return f"Pack({self.name!r}, {len(self.bumps)} bumps)"


def folders(env=None):
    """Where packs are looked for: each is a pack folder ($BROMIGOS_BUMPS) or holds them."""
    env = os.environ if env is None else env
    data = env.get("XDG_DATA_HOME") or os.path.join(env.get("HOME") or os.path.expanduser("~"), ".local", "share")
    own = [p for p in (env.get("BROMIGOS_BUMPS") or "").split(":") if p]
    return own + [os.path.join(data, "bromigos", "bumps"), "/usr/share/bromigos/bumps"]


def _read_pack(folder):
    path = os.path.join(folder, "bumps.json")
    try:
        with open(path) as f:
            doc = json.load(f)
    except (OSError, ValueError):
        return None
    if not isinstance(doc, dict) or doc.get("schema") != 1 or not isinstance(doc.get("bumps"), list):
        return None
    name = str(doc.get("pack") or os.path.basename(os.path.normpath(folder)))
    out = []
    for b in doc["bumps"]:
        if not isinstance(b, dict) or not b.get("id") or not b.get("file"):
            continue
        clip = os.path.normpath(os.path.join(folder, str(b["file"])))
        if not clip.startswith(os.path.normpath(folder) + os.sep) or not os.path.isfile(clip):
            continue                                       # a clip outside its pack, or missing: left out
        try:
            secs = float(b.get("seconds") or 0)
        except (TypeError, ValueError):
            secs = 0.0
        if not 1.0 <= secs <= 30.0:
            continue
        roles = [r for r in (b.get("roles") or ["between"]) if r in ROLES]
        out.append(Bump(id=f"{name}/{b['id']}", path=clip, seconds=secs, roles=roles,
                        caption=str(b.get("caption") or "")[:40], about=str(b.get("about") or ""), pack=name))
    return Pack(name, folder, str(doc.get("title") or name), out)


def packs(env=None):
    """Every pack found, the first of each name."""
    seen, out = set(), []
    for root in folders(env):
        cands = [root] if os.path.isfile(os.path.join(root, "bumps.json")) else \
            sorted(os.path.join(root, d) for d in (os.listdir(root) if os.path.isdir(root) else []))
        for folder in cands:
            p = _read_pack(folder)
            if p and p.name not in seen:
                seen.add(p.name)
                out.append(p)
    return out


def all_bumps(cfg=None, env=None):
    """The bumps the settings allow: every pack's, or only [tv.bumps] packs'."""
    want = settings(cfg)["packs"]
    return [b for p in packs(env) if not want or p.name in want for b in p.bumps]


def settings(cfg):
    """[tv.bumps] over the defaults, each value checked (a bad one is its default)."""
    raw = ((cfg or {}).get("tv") or {}).get("bumps") or {}
    out = dict(DEFAULTS)
    if raw.get("mode") in MODES:
        out["mode"] = raw["mode"]
    if raw.get("enabled") is False:                   # bumps = { enabled = false } reads as off
        out["mode"] = "off"
    if isinstance(raw.get("night"), str) and _span(raw["night"]):
        out["night"] = raw["night"]
    for k in ("every", "every_night", "tune_every", "max"):
        try:
            v = float(raw[k]) if k != "max" else int(raw[k])
            out[k] = v if v >= 0 else out[k]
        except (KeyError, TypeError, ValueError):
            pass
    if isinstance(raw.get("packs"), list):
        out["packs"] = [str(p) for p in raw["packs"]]
    return out


def mascot_off(env=None):
    """`bromigos mascot off` (or BROMIGOS_MASCOT=off): no bumps either."""
    env = os.environ if env is None else env
    if env.get("BROMIGOS_MASCOT"):
        return env["BROMIGOS_MASCOT"] == "off"
    cfg = env.get("XDG_CONFIG_HOME") or os.path.join(env.get("HOME") or os.path.expanduser("~"), ".config")
    try:
        with open(os.path.join(cfg, "bromigos", "mascot.toml")) as f:
            m = re.search(r'^\s*mode\s*=\s*"(\w+)"', f.read(), re.M)
        return bool(m and m.group(1) == "off")
    except OSError:
        return False


def _span(spec):
    m = re.fullmatch(r"\s*(\d{1,2}):(\d{2})\s*-\s*(\d{1,2}):(\d{2})\s*", spec or "")
    if not m:
        return None
    a, b = int(m[1]) * 60 + int(m[2]), int(m[3]) * 60 + int(m[4])
    if a >= 24 * 60 or b > 24 * 60 or a == b:
        return None
    return a, b


def _midnight(t):
    lt = time.localtime(t)
    return time.mktime((lt.tm_year, lt.tm_mon, lt.tm_mday, 0, 0, 0, 0, 0, -1))


def night(t, spec=DEFAULTS["night"]):
    """The night block t falls in, as its start's local date, or None outside it."""
    span = _span(spec)
    if not span:
        return None
    a, b = span
    day = _midnight(t)
    mins = (t - day) / 60
    if a < b:
        return time.strftime("%Y-%m-%d", time.localtime(day)) if a <= mins < b else None
    if mins >= a:                                      # 22:00-04:00: tonight, before midnight
        return time.strftime("%Y-%m-%d", time.localtime(day))
    if mins < b:                                       # after midnight: last night's block
        return time.strftime("%Y-%m-%d", time.localtime(day - 43200))
    return None


def just_ended(t, spec=DEFAULTS["night"], window=CLOSE_WINDOW):
    """The night block that ended less than `window` seconds before t, or None."""
    if night(t, spec):
        return None
    k = night(t - window, spec)
    return k


def count_key(t, cfg):
    s = settings(cfg)
    return night(t, s["night"]) or time.strftime("%Y-%m-%d", time.localtime(t))


def choose(kind, t, cfg, state, bumps, rng=None, env=None):
    """(Bump, role) to play now, or None. kind: "between" (an item just ended) or "tune" (a
    channel change). Pure: the time, the state and the dice are given."""
    s = settings(cfg)
    if s["mode"] == "off" or not bumps or mascot_off(env):
        return None
    st = state or {}
    rng = rng or random.Random()
    tonight = night(t, s["night"])
    ended = just_ended(t, s["night"])
    if s["mode"] == "night" and not tonight and not ended:
        return None
    if t - float(st.get("last") or 0) < GAP:
        return None
    if (st.get("count") or {}).get(count_key(t, cfg), 0) >= s["max"]:
        return None
    role = None
    if kind == "between":
        if tonight and st.get("opened") != tonight and _with(bumps, "open"):
            role = "open"
        elif ended and st.get("closed") != ended and _with(bumps, "close"):
            role = "close"
        elif tonight or s["mode"] == "always":
            every = s["every_night"] if tonight else s["every"]
            if t - float(st.get("last_between") or 0) >= every * 60:
                role = "between"
    elif kind == "tune" and (tonight or s["mode"] == "always"):
        if t - float(st.get("last_tune") or 0) >= s["tune_every"] * 60:
            role = "tune"
    if role is None:
        return None
    pool = [b for b in _with(bumps, role) if role != "tune" or b.seconds <= TUNE_MAX]
    fresh = [b for b in pool if b.id not in (st.get("recent") or [])[-RECENT:]]
    pool = fresh or [b for b in pool if b.id != (st.get("recent") or [None])[-1]] or pool
    if not pool:
        return None
    return rng.choice(sorted(pool, key=lambda b: b.id)), role


def _with(bumps, role):
    return [b for b in bumps if role in (b.roles or ())]


def record(state, bump, role, t, cfg):
    """The state after `bump` plays as `role` at t (a new dict)."""
    st = dict(state or {})
    st["last"] = t
    if role == "tune":
        st["last_tune"] = t
    else:
        st["last_between"] = t
    s = settings(cfg)
    if role == "open":
        st["opened"] = night(t, s["night"])
    if role == "close":
        st["closed"] = just_ended(t, s["night"])
    key = count_key(t, cfg)
    count = {k: v for k, v in (st.get("count") or {}).items() if k >= time.strftime("%Y-%m-%d", time.localtime(t - 3 * 86400))}
    count[key] = count.get(key, 0) + 1
    st["count"] = count
    st["recent"] = ((st.get("recent") or []) + [bump.id])[-8:]
    return st


def load_state(path=None):
    try:
        with open(path or STATE) as f:
            doc = json.load(f)
        return doc if isinstance(doc, dict) else {}
    except (OSError, ValueError):
        return {}


def save_state(st, path=None):
    path = path or STATE
    os.makedirs(os.path.dirname(path), exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path), prefix=".tv-bumps-")
    with os.fdopen(fd, "w") as f:
        json.dump(st, f)
    os.replace(tmp, path)


def status(cfg, t=None, env=None):
    """What the den would do now, for `bromigos-live tv bumps` and Settings."""
    t = time.time() if t is None else t
    s = settings(cfg)
    ps = packs(env)
    st = load_state()
    return {"mode": "off" if mascot_off(env) else s["mode"], "mascot_off": mascot_off(env), "night": s["night"],
            "in_night": bool(night(t, s["night"])), "every": s["every"], "every_night": s["every_night"],
            "tune_every": s["tune_every"], "max": s["max"],
            "tonight": (st.get("count") or {}).get(count_key(t, cfg), 0),
            "packs": [{"name": p.name, "title": p.title, "folder": p.folder, "bumps": len(p.bumps),
                       "on": not s["packs"] or p.name in s["packs"]} for p in ps]}
