#!/usr/bin/env python3
"""Waybar storage readout: / and /mnt/Data on the bar, every mount in the tooltip."""
import json
import os
import sys

_WIDGETS = "/usr/lib/bromigos/widgets"   # bromigos-widgets: its readings (sources.py)
sys.path.insert(0, _WIDGETS)
sys.path.insert(0, "/usr/lib/bromigos/lib")   # bromigos-core: the theme
import bromigos_theme as T  # noqa: E402  (spans are written in the Wick's colours; T.retint -> the theme's)
from sources import human, storage  # noqa: E402

mounts = storage()
bar = []
for m in mounts:
    if m["mounted"] and m["mount"] in ("/", "/mnt/Data"):
        name = "/" if m["mount"] == "/" else "DATA"
        col = "#ff766f" if m["pct"] >= 92 else "#d4af37" if m["pct"] >= 80 else "#9cff8a"
        bar.append(f"<span color='#7e927e'>{name}</span> <span color='{col}'>{m['pct']:.0f}%</span>")
rows = [f"{'MOUNT':<12} {'SIZE':>9} {'USED':>9} {'FREE':>9}  USE"]
for m in mounts:
    if m["mounted"]:
        rows.append(f"{m['mount']:<12} {human(m['size']):>9} {human(m['used']):>9} {human(m['free']):>9} {m['pct']:>4.0f}%")
    else:
        rows.append(f"{m['device']:<12} {human(m['size']):>9} {'not mounted':>20} ({m['fstype']})")
worst = max((m["pct"] for m in mounts if m["mounted"]), default=0)
print(T.retint(json.dumps({
    "text": "  ".join(bar),
    "tooltip": "<tt>" + "\n".join(rows) + "</tt>\nclick: open the file manager",
    "class": "critical" if worst >= 92 else "warning" if worst >= 80 else "",
})))
