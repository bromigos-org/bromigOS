#!/usr/bin/env python3
"""STATIC's art for Den TV's guide (the Tonight card), cut from the bumps' clips: one short ping-pong loop per
state as an animated WebP at two heights, and the manifest lib/bromigos_static_art.py reads. ffmpeg only.

    python3 host_art.py CLIPDIR OUTDIR      (CLIPDIR: the pack's clips/<id>.mp4)

Each state is a shell doing what the guide is doing, as the lore casts them: NOIR hosts, STATIC's signal tunes
in, RECON's OWL searches for a signal, NOIR dozes when the den's asleep, and RIG's LINEMAN fixes what broke.
"""
import json
import os
import subprocess
import sys

HEIGHTS = (168, 336)        # the Tonight card's STATIC, and the same at 2x
FPS = 12
# name: (bump clip, start s, seconds, crop centre x (0..1), about)
STATES = {
    "host": ("late-night", 1.0, 2.0, 0.50, "NOIR hosts tonight's broadcast from his pod: what comes on next"),
    "snow": ("signal-in", 0.6, 2.0, 0.45, "STATIC's signal tunes in while the channels are read"),
    "antenna": ("still-lit", 1.5, 2.0, 0.72, "RECON's OWL searches the dark for a signal: there's nothing on yet"),
    "asleep": ("sign-off", -2.6, 2.0, 0.50, "NOIR has powered down: the den's live layer isn't running"),
    "whack": ("right-back", 0.8, 2.0, 0.55, "RIG's LINEMAN is on it: something can't be read"),
}


def duration(path):
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", path],
                         capture_output=True, text=True, check=True).stdout
    return float(out)


def main(clips, out):
    os.makedirs(out, exist_ok=True)
    doc = {"schema": 1, "fps": FPS, "art": {}}
    for name, (clip, start, secs, cx, about) in STATES.items():
        src = os.path.join(clips, clip + ".mp4")
        if not os.path.isfile(src):
            print(name, "no clip", clip)
            continue
        if start < 0:
            start = max(0.0, duration(src) - 1.7 + start)      # from the end, before the fade out
        entry = {"min": 96, "about": about}
        for h in HEIGHTS:
            w = round(h * 4 / 3 / 2) * 2
            dst = os.path.join(out, f"{name}-{h}.webp")
            # a 4:3 window on the shell, the segment forward then back (a seamless loop), lossy WebP
            vf = (f"trim=start={start}:duration={secs},setpts=PTS-STARTPTS,fps={FPS},"
                  f"crop=ih*4/3:ih:(iw-ih*4/3)*{cx}:0,scale={w}:{h}:flags=lanczos,"
                  f"split[a][b];[b]reverse,trim=start_frame=1,setpts=PTS-STARTPTS[r];[a][r]concat=n=2:v=1:a=0,"
                  f"trim=end_frame={2 * int(secs * FPS) - 2}")
            subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", src, "-filter_complex", vf,
                            "-an", "-c:v", "libwebp", "-lossless", "0", "-q:v", "65", "-loop", "0",
                            "-compression_level", "6", dst], check=True)
            entry[str(h)] = os.path.basename(dst)
            print(name, h, os.path.getsize(dst))
        doc["art"][name] = entry
    with open(os.path.join(out, "manifest.json"), "w") as f:
        json.dump(doc, f, indent=1)
        f.write("\n")


if __name__ == "__main__":
    main(*sys.argv[1:3])
