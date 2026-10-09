#!/usr/bin/env python3
"""Waybar idle module: the idle policy at a glance (docs/idle.md). A cup while staying
awake, an eye when nothing locks on idle (screensaver only, presentation), a dim eye
otherwise. Reads `bromigos idle status --json`; every change refreshes it (SIGRTMIN+10).
click: stay awake for an hour (again: stop) · middle-click: until you stop it ·
right-click: Settings › Idle & lock."""
import json
import subprocess
import time

HELP = ("click: stay awake for an hour (click again to stop)\n"
        "middle-click: stay awake until you stop it\n"
        "right-click: Settings › Idle & lock (SUPER+,)")


def main():
    try:
        r = subprocess.run(["bromigos", "idle", "status", "--json"], capture_output=True, text=True, timeout=8)
        d = json.loads(r.stdout)
    except (OSError, subprocess.SubprocessError, ValueError):
        return {"text": " ", "class": ["normal", "unknown"],
                "tooltip": "Idle: `bromigos idle` didn't answer (is bromigos-core installed?)\n" + HELP}
    aw = d.get("stay_awake") or {}
    preset = d.get("preset")
    hd = d.get("hypridle") or {}
    lines = [d.get("summary", "")]
    if aw.get("on"):
        left = aw.get("remaining_s")
        if left is None:
            text, when = "AWAKE", "until you stop it"
        else:
            m = max(1, (int(left) + 59) // 60)
            text = f"AWAKE {m // 60}h{m % 60:02d}" if m >= 60 else f"AWAKE {m}m"
            when = "until " + time.strftime("%H:%M", time.localtime(aw.get("until") or time.time()))
        cls = ["awake"]
        lines.insert(0, f"Staying awake {when}: nothing idles until then. After that:")
    elif preset == "presentation":
        text, cls = "NO IDLE", ["nothing"]
    elif d.get("screensaver_only"):
        text, cls = "NO LOCK", ["saver"]
    else:
        text, cls = " ", ["normal"]
    if not hd.get("running"):
        cls.append("stopped")
        lines.append("hypridle isn't running: nothing idles (it starts at login)")
    others = d.get("inhibitors") or []
    if others:
        lines.append("Also keeping it awake: " + ", ".join(f"{i['who']} ({i['why']})" for i in others))
    warns = [w["text"] for w in d.get("warnings") or [] if w.get("level") == "warn"]
    lines += warns[:2]
    return {"text": text, "class": cls, "tooltip": "\n".join(lines) + "\n\n" + HELP}


if __name__ == "__main__":
    print(json.dumps(main()))
