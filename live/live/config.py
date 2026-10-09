"""config.toml loader. Missing keys fall back to DEFAULTS so an old or partial
config never crashes the layer.

The lab itself is bromigos-homelab's (homelab.toml, docs/homelab.md); [cluster] keeps
only its poll cadence. The operator's other internal URLs aren't in config.toml (the repo
is public): [fills] `endpoint`, an empty codec.tts_url and radial items with
`endpoint = "<name>"` are filled from the private overlay (~/.config/bromigos/lib/bromigos_private.py,
key endpoints.<name>). On a fresh clone they stay empty and those feeds stay off."""
import copy
import os
import sys
import tomllib

from . import LIB  # noqa: E402,F401  (puts the shared libs on sys.path)
import bromigos_private as PRIV  # noqa: E402

HERE = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
# Layers, merged key by key: DEFAULTS, then the packaged config.toml (/usr/share/bromigos/live,
# else the one beside the code in a bromigOS checkout), then the user's (only what they
# change: a thin file), then their animation switches (overrides.toml).
USER = os.environ.get("BROMIGOS_LIVE_CONFIG") or os.path.join(os.path.expanduser("~/.config/bromigos-live"), "config.toml")
SHARE = os.environ.get("BROMIGOS_SHARE_DIR") or "/usr/share/bromigos"
# The user's own switches (`bromigos anim on|off …`), merged over config.toml. User-owned, so
# ~/.config/bromigos/ (bromigOS's file homes); the old state path is read until the
# first write moves it (bromigos CLI, Python or Rust).
_XDG_CONFIG = os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")
_XDG_STATE = os.environ.get("XDG_STATE_HOME") or os.path.expanduser("~/.local/state")
OVERRIDES_NEW = os.path.join(_XDG_CONFIG, "bromigos", "live", "overrides.toml")
OVERRIDES_OLD = os.path.join(_XDG_STATE, "bromigos-live", "overrides.toml")
OVERRIDES = OVERRIDES_NEW if os.path.exists(OVERRIDES_NEW) or not os.path.exists(OVERRIDES_OLD) else OVERRIDES_OLD
# The user's accessibility settings (`bromigos accessibility`; docs/accessibility.md): its
# `motion` becomes general.motion (live/motion.py), winning over config.toml's.
A11Y = os.path.join(_XDG_CONFIG, "bromigos", "accessibility.toml")
PACKAGED = os.path.join(SHARE, "live", "config.toml")
if not os.path.exists(PACKAGED):
    PACKAGED = os.path.join(HERE, "config.toml")
# The public lore catalog the Drift map reads unless [driftmap] catalog names another
# (bromigos.org's public lore export; tools/lore/sync-catalog.py), the same way round.
LORE = os.path.join(SHARE, "live", "lore", "catalog.json")
if not os.path.exists(LORE):
    LORE = os.path.join(HERE, "lore", "catalog.json")
# the file a config change is watched on (app.py): the user's when they have one
PATH = USER if os.path.exists(USER) else PACKAGED

DEFAULTS = {
    "general": {"monitor": "", "fps": 30, "fps_covered": 20, "motion": "full", "reduced_motion": False,
                "allow_software": False},
    "background": {"enabled": True, "underlay": "", "underlay_fallback": "", "underlay_brightness": 1.0,
                   "glow": 0.85, "den": True, "den_plate": "", "den_plates": {}},
    "loops": {"streaks": True, "streak_period": 10, "rows": True, "row_period": 12, "row_amp": 1.0,
              "steam": ["den", "empty", "masked", "v1"], "steam_period": 7, "steam_intensity": 0.55},
    "rain": {"enabled": True, "region": [0, 30, 2390, 600], "brightness": 0.55, "bursts": True},
    "floor": {"enabled": True, "horizon_y": 926, "vanish_x": 690, "lane_slope": 0.98, "lane_offset": 0.71,
              "max_x": 1000, "draw_grid": False},
    "sweep": {"enabled": True, "interval": 60, "duration": 5.5},
    "holodeck": {"enabled": True},
    "space": {"stars": True, "traffic": True, "relay_beam": True, "health_tint": True, "planet": True,
              "station": True},
    "cluster": {"url": "", "token_file": "", "ca_file": "", "poll_seconds": 25},
    "fills": {"endpoint": "", "console": "", "url": "", "poll_seconds": 30},
    "events": {"intercept_on_login": True, "intercept_on_unlock": True, "critical_flash": True,
               "workspace_wipe": True},
    "screensaver": {"enabled": True},
    "sounds": {"enabled": True, "volume": 0.3, "terminal_classes": ["kitty", "Alacritty"]},
    "radial": {"items": []},
    "world": {"enabled": True, "dir": "", "idle_after": 90, "ambient_sounds": True},
    "driftmap": {"catalog": ""},
}


def lore_catalog(cfg):
    """The Drift map's catalog: [driftmap] catalog when set, else the packaged public one."""
    return os.path.expanduser((cfg.get("driftmap") or {}).get("catalog") or LORE)


def _merge(base, over):
    out = copy.deepcopy(base)
    for k, v in (over or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _merge(out[k], v)
        else:
            out[k] = v
    return out


def _private(cfg):
    """Fill the internal URLs from the private overlay (see the module docstring)."""
    fl = cfg["fills"]                                  # a trade tape's paper fills
    if not fl.get("console") and fl.get("endpoint"):
        fl["console"] = PRIV.url(fl["endpoint"])
    if (fl.get("url") or "").startswith("/"):          # a path on the console
        fl["url"] = fl["console"] + fl["url"] if fl.get("console") else ""
    co = cfg.setdefault("codec", {})
    if not co.get("tts_url"):
        co["tts_url"] = PRIV.url("tts")
    items = []
    for it in cfg.get("radial", {}).get("items") or []:
        if it.get("endpoint"):
            it = dict(it, url=PRIV.url(it["endpoint"]))
            if not it["url"] and it.get("stat") == "lab":  # the lab's own web view (homelab.toml)
                try:
                    from .homelab import H
                    it["url"] = H.lab_url() if H else ""
                except Exception:
                    it["url"] = ""
            if not it["url"]:
                continue                                  # not configured on this machine
        items.append(it)
    cfg.setdefault("radial", {})["items"] = items
    return cfg


def _layer(cfg, path, what):
    try:
        with open(path, "rb") as f:
            return _merge(cfg, tomllib.load(f))
    except FileNotFoundError:
        return cfg
    except (OSError, tomllib.TOMLDecodeError) as e:
        print(f"bromigos-live: {what} ignored ({path}):", e, flush=True)
        return cfg


def load():
    cfg = _layer(copy.deepcopy(DEFAULTS), PACKAGED, "packaged config")
    if os.path.realpath(USER) != os.path.realpath(PACKAGED):
        cfg = _layer(cfg, USER, "config")
    path = OVERRIDES_NEW if os.path.exists(OVERRIDES_NEW) else OVERRIDES_OLD
    try:
        with open(path, "rb") as f:
            cfg = _merge(cfg, tomllib.load(f))
    except FileNotFoundError:
        pass
    except (OSError, tomllib.TOMLDecodeError) as e:
        print("bromigos-live: overrides ignored:", e, flush=True)
    return _private(_motion(cfg))


def _motion(cfg):
    """general.motion from the accessibility settings (else config.toml's, else full); the
    old reduced_motion = true means at least "reduced", and is kept true for any calm mode,
    so code that reads it follows both."""
    from . import motion
    g = cfg.setdefault("general", {})
    try:
        with open(A11Y, "rb") as f:
            m = tomllib.load(f).get("motion")
        if m in motion.MODES:
            g["motion"] = m
    except FileNotFoundError:
        pass
    except (OSError, tomllib.TOMLDecodeError) as e:
        print("bromigos-live: accessibility settings ignored:", e, flush=True)
    g["motion"] = motion.mode(cfg)
    g["reduced_motion"] = g["motion"] != "full"
    return cfg
