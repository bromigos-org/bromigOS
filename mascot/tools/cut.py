#!/usr/bin/env python3
"""Cut Den TV's bumps from the lab's clips: each bump's silent cut (H.264, no audio track), the pack's
bumps.json, and a silent review reel with the captions drawn in. ffmpeg only; nothing generated here.

    python3 cut.py UPDIR OUTDIR      (UPDIR: the upscaled clips, <name>.mp4)
"""
import json
import os
import subprocess
import sys

# id: (pieces, hold seconds at the end, roles, caption, about)
BUMPS = {
    "still-lit": (["still-lit-owl"], 1.2, ["open", "between"], "STILL LIT",
                  "RECON's OWL keeps watch on a cliff at night: the night block's ident"),
    "right-back": (["right-back-lineman"], 0.6, ["between"], "BACK IN A MOMENT",
                   "RIG's LINEMAN hangs from a cable, fixing a junction box in a shower of sparks"),
    "cable-run": (["cable-run-lineman"], 0.0, ["tune", "between"], "",
                  "RIG's LINEMAN rides a power cable down a ship's corridor"),
    "late-night": (["late-night-noir"], 0.8, ["between"], "STAY TUNED",
                   "NOIR hosts the late-night broadcast from his pod"),
    "signal-in": (["signal-in-noir"], 0.0, ["tune", "between"], "",
                  "STATIC's signal races down a cable into NOIR's console"),
    "takeover": (["takeover-lineman"], 0.8, ["between"], "",
                 "The takeover: a dormant repair robot wakes up as STATIC's LINEMAN"),
    "crew": (["crew-owl", "crew-lineman", "crew-noir"], 0.6, ["between"], "",
             "The crew on the ship: OWL at the viewport, LINEMAN at a junction box, NOIR on the bridge"),
    "sign-off": (["sign-off-noir"], 1.6, ["close"], "SIGNING OFF",
                 "NOIR powers down for the night: the night block's sign-off"),
}
W, H, FPS = 1248, 720, 32
GLITCH = 0.25          # seconds of phosphor interference between the crew's shots


def run(*args):
    subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", *args], check=True)


def probe(path):
    out = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
                          "stream=width,height,r_frame_rate,nb_frames:format=duration", "-of", "json", path],
                         capture_output=True, text=True, check=True).stdout
    return json.loads(out)


def norm(src, dst):
    """A piece at the pack's size and rate (the upscale is 1248x720; 16 fps clips are doubled by frame)."""
    run("-i", src, "-vf", f"scale={W}:{H}:flags=lanczos,fps={FPS},format=yuv420p", "-an", "-c:v", "libx264",
        "-preset", "slow", "-crf", "14", dst)


def glitch(dst):
    """A short burst of green interference: noise, scanlines and a roll, drawn by ffmpeg's filters."""
    run("-f", "lavfi", "-i", f"color=c=0x062a08:s={W}x{H}:r={FPS}:d={GLITCH}",
        "-vf", "noise=alls=40:allf=t+u,boxblur=1:1,geq=lum='lum(X,Y)*(0.6+0.4*mod(Y,3))':cb=110:cr=100,"
               "scroll=v=0.08,format=yuv420p",
        "-c:v", "libx264", "-preset", "slow", "-crf", "16", dst)


def cut(name, spec, up, tmp, out):
    pieces, hold, *_ = spec
    parts = []
    for i, p in enumerate(pieces):
        n = os.path.join(tmp, f"{name}-{i}.mp4")
        norm(os.path.join(up, p + ".mp4"), n)
        if i:
            g = os.path.join(tmp, f"{name}-g{i}.mp4")
            glitch(g)
            parts.append(g)
        parts.append(n)
    lst = os.path.join(tmp, f"{name}.txt")
    with open(lst, "w") as f:
        f.writelines(f"file '{p}'\n" for p in parts)
    joined = os.path.join(tmp, f"{name}-joined.mp4")
    run("-f", "concat", "-safe", "0", "-i", lst, "-c", "copy", joined)
    d = float(probe(joined)["format"]["duration"]) + hold
    vf = (f"tpad=stop_mode=clone:stop_duration={hold},fade=t=in:st=0:d=0.3,"
          f"fade=t=out:st={d - 0.5:.3f}:d=0.5,format=yuv420p")
    dst = os.path.join(out, "clips", name + ".mp4")
    run("-i", joined, "-vf", vf, "-an", "-c:v", "libx264", "-profile:v", "high", "-preset", "slow", "-crf", "22",
        "-g", str(FPS * 2), "-movflags", "+faststart", "-metadata", "comment=Bromigos Den TV bump (bromigos-mascot-art)",
        dst)
    return dst, round(float(probe(dst)["format"]["duration"]), 2)


def main(up, out):
    up, out = (os.path.abspath(p) for p in (up, out))
    tmp = os.path.join(out, ".work")
    os.makedirs(tmp, exist_ok=True)
    os.makedirs(os.path.join(out, "clips"), exist_ok=True)
    doc = {"schema": 1, "pack": "static", "title": "STATIC's bumps",
           "about": "Short interstitials from STATIC's crew for Den TV's night block (bromigos-mascot-art)",
           "bumps": []}
    reel = []
    for name, spec in BUMPS.items():
        if not all(os.path.isfile(os.path.join(up, p + ".mp4")) for p in spec[0]):
            print(name, "missing pieces; skipped", flush=True)
            continue
        path, secs = cut(name, spec, up, tmp, out)
        doc["bumps"].append({"id": name, "file": f"clips/{name}.mp4", "seconds": secs, "roles": spec[2],
                             **({"caption": spec[3]} if spec[3] else {}), "about": spec[4]})
        reel.append((path, secs, spec[3]))
        print(name, secs, os.path.getsize(path), flush=True)
    with open(os.path.join(out, "bumps.json"), "w") as f:
        json.dump(doc, f, indent=1)
        f.write("\n")
    # the review reel: every bump, silent, its caption drawn as the den draws it, a beat of black between
    parts = []
    for i, (clip, secs, cap) in enumerate(reel):
        r = os.path.join(tmp, f"reel-{i}.mp4")
        draw = ""
        if cap:
            draw = (f",drawtext=fontfile=/usr/share/fonts/TTF/GeistMono-Bold.ttf:text='{cap}':fontcolor=0x7dff5a:"
                    f"fontsize=44:x=(w-tw)/2:y=h-72:box=1:boxcolor=0x020a02@0.6:boxborderw=14:"
                    f"enable='between(t,0.8,{secs - 0.2:.2f})'")
        run("-i", clip, "-f", "lavfi", "-t", "0.6", "-i", f"color=c=black:s={W}x{H}:r={FPS}",
            "-filter_complex", f"[0:v]format=yuv420p{draw}[v0];[v0][1:v]concat=n=2:v=1:a=0[v]",
            "-map", "[v]", "-an", "-c:v", "libx264", "-preset", "medium", "-crf", "20", r)
        parts.append(r)
    lst = os.path.join(tmp, "reel.txt")
    with open(lst, "w") as f:
        f.writelines(f"file '{p}'\n" for p in parts)
    run("-f", "concat", "-safe", "0", "-i", lst, "-c", "copy", "-movflags", "+faststart",
        os.path.join(os.path.dirname(os.path.abspath(out)), "den-bumps-reel.mp4"))


if __name__ == "__main__":
    main(*sys.argv[1:3])
