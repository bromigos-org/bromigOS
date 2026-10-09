"""Which output bromigOS's own surfaces go on (the live layer's background, the widgets).

    primary(monitors, wanted)

`monitors` is Hyprland's list (`hyprctl monitors -j`); `wanted` the surface's own setting
(the live layer's general.monitor, the widgets' layout "monitor"; "" when unset). The
choice, in order:

  1. `wanted`, when that output is there;
  2. the primary `bromigos setup monitors` recorded (~/.config/bromigos/monitors.toml);
  3. the focused output;
  4. the first Hyprland lists (lowest id), else the largest.

Nothing names a connector: a setting written for another machine's output falls through
to this one's, and a surface whose output goes away picks again (hotplug, unplug).
"""
import os
import tomllib


def _config_home():
    return os.environ.get("XDG_CONFIG_HOME") or os.path.join(os.path.expanduser("~"), ".config")


def setup_primary():
    """The primary output `bromigos setup monitors` recorded, or ""."""
    try:
        with open(os.path.join(_config_home(), "bromigos", "monitors.toml"), "rb") as f:
            return str(tomllib.load(f).get("primary", "") or "")
    except (OSError, ValueError):
        return ""


def primary(monitors, wanted=""):
    """The output's name, or `wanted` when there's no list to choose from."""
    mons = [m for m in (monitors or []) if m.get("name") and not m.get("disabled")]
    names = {m["name"] for m in mons}
    if not mons:
        return wanted
    for name in (wanted, setup_primary()):
        if name and name in names:
            return name
    focused = next((m["name"] for m in mons if m.get("focused")), None)
    if focused:
        return focused
    by_id = min(mons, key=lambda m: m.get("id", 0))
    if by_id.get("name"):
        return by_id["name"]
    return max(mons, key=lambda m: m.get("width", 0) * m.get("height", 0))["name"]
