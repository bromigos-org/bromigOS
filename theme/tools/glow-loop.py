#!/usr/bin/env python3
"""Turn a raw generated clip of a glowing creature on black into a world's loop.

  glow-loop.py RAW.mp4 OUT.mp4 [--width 1280] [--black 0.025] [--margin 0.04]
               [--stacked LO HI [--fill SIGMA]] [--mask [FEATHER]]

The clip was made to loop (its end frame is its first), so the frame most like the
first one near the end is where it wraps: everything from there on is dropped. The
frame is cropped to the creature (every frame's lit pixels, plus a margin), scaled
to at most --width, and its near-black lifted to true black (--black, 0..1) so the
engine's luma matte (an additive actor's coverage is its brightness) leaves nothing
around the creature: no box, no haze. H.264, yuv420p, no audio, the source's fps.

--stacked LO HI: for a dark creature that should hide the water behind it rather than
only add light (its body a silhouette, its glow its own), write the engine's "stacked"
layout instead: the colour on top and below it an alpha matte ramping from 0 at
brightness LO to 1 at HI (0..1). Its world.toml then sets `alpha = "stacked"` in
[loops] and leaves the actor's blend normal. --fill R also makes the solid middle of a
body darker than LO opaque: each frame's matte is closed (R px) and its enclosed holes
filled (scipy), so the body is whole and its outline doesn't grow; thin parts keep
their own soft edge. (Needs scipy: `uv run --with scipy --with numpy python glow-loop.py …`.)

--mask [FEATHER]: also write OUT-mask.png beside it, a soft oval as big as the loop (white in
the middle, fading to black at its edge over FEATHER of the radius, default 0.5): the live
layer finds it by name and multiplies the loop's alpha by it, so a cloud or a reef thins out
at its edge instead of ending at a box (Tidewell's lampfry shoals).

The raw clip may come from nolgia (an end-frame loop) or a ComfyUI (`bromigos art make
video.loop --alpha …` runs this on what Wan 2.2 made); either way its last frame is next to
its first.
"""
import argparse
import json
import subprocess

import numpy as np


def probe(path):
    out = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
                          "stream=width,height,r_frame_rate", "-of", "json", path],
                         capture_output=True, text=True, check=True).stdout
    s = json.loads(out)["streams"][0]
    n, d = s["r_frame_rate"].split("/")
    return int(s["width"]), int(s["height"]), float(n) / float(d)


def frames(path, w, h, scale=4):
    sw, sh = w // scale, h // scale
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", path, "-vf", f"scale={sw}:{sh}",
                          "-f", "rawvideo", "-pix_fmt", "gray", "-"], capture_output=True, check=True).stdout
    return np.frombuffer(raw, np.uint8).reshape(-1, sh, sw).astype(np.float32) / 255.0, scale


def fill_stacked(a, base, lut, lo, hi, ow, oh, fps):
    """The stacked layout with a filled matte, frame by frame (see --fill)."""
    from scipy import ndimage as ndi
    dec = subprocess.Popen(["ffmpeg", "-v", "error", "-i", a.raw, "-vf", f"{base},{lut}", "-f", "rawvideo",
                            "-pix_fmt", "rgb24", "-"], stdout=subprocess.PIPE)
    enc = subprocess.Popen(["ffmpeg", "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{ow}x{oh * 2}",
                            "-r", f"{fps:g}", "-i", "-", "-an", "-c:v", "libx264", "-preset", "slow", "-crf", "17",
                            "-pix_fmt", "yuv420p", "-movflags", "+faststart", a.out], stdin=subprocess.PIPE)
    size = ow * oh * 3
    r = max(1, int(round(a.fill)))
    disk = np.hypot(*np.mgrid[-r:r + 1, -r:r + 1]) <= r
    while True:
        buf = dec.stdout.read(size)
        if len(buf) < size:
            break
        rgb = np.frombuffer(buf, np.uint8).reshape(oh, ow, 3)
        y = rgb.astype(np.float32) @ np.array([0.299, 0.587, 0.114], np.float32)
        ramp = np.clip((y - lo) / (hi - lo), 0.0, 1.0)
        solid = ndi.binary_fill_holes(ndi.binary_closing(ramp > 0.25, structure=disk))
        core = ndi.gaussian_filter(solid.astype(np.float32), 1.0)
        alpha = (np.maximum(ramp, core) * 255.0 + 0.5).astype(np.uint8)
        enc.stdin.write(np.concatenate([rgb, np.repeat(alpha[..., None], 3, -1)], 0).tobytes())
    enc.stdin.close()
    if enc.wait() or dec.wait():
        raise SystemExit("ffmpeg failed")


def write_mask(out, w, h, feather):
    """OUT-mask.png: a soft oval filling w x h, 1 inside, smoothly 0 at its rim."""
    import os
    y, x = np.mgrid[0:h, 0:w].astype(np.float32)
    d = np.hypot((x + 0.5 - w / 2) / (w / 2), (y + 0.5 - h / 2) / (h / 2))
    t = np.clip((1.0 - d) / max(1e-3, min(1.0, feather)), 0.0, 1.0)
    m = (t * t * (3 - 2 * t) * 255 + 0.5).astype(np.uint8)
    path = os.path.splitext(out)[0] + "-mask.png"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "gray", "-s", f"{w}x{h}",
                    "-i", "-", "-frames:v", "1", path], input=m.tobytes(), check=True)
    return path


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("raw")
    ap.add_argument("out")
    ap.add_argument("--width", type=int, default=1280)
    ap.add_argument("--black", type=float, default=0.025)
    ap.add_argument("--margin", type=float, default=0.04)
    ap.add_argument("--stacked", type=float, nargs=2, metavar=("LO", "HI"))
    ap.add_argument("--fill", type=float, default=0.0)
    ap.add_argument("--mask", type=float, nargs="?", const=0.5, default=None, metavar="FEATHER")
    a = ap.parse_args()
    w, h, fps = probe(a.raw)
    f, sc = frames(a.raw, w, h)
    n = len(f)
    tail = range(max(1, n - int(fps * 1.5)), n)          # wrap in the last second and a half
    err = [float(np.mean((f[k] - f[0]) ** 2)) for k in tail]
    cut = list(tail)[int(np.argmin(err))]
    lit = (f[:cut] > a.black * 2).any(0)
    ys, xs = np.nonzero(lit)
    if len(xs) == 0:
        raise SystemExit("nothing lit in the clip")
    mx, my = int(w * a.margin), int(h * a.margin)
    x0, x1 = max(0, xs.min() * sc - mx), min(w, (xs.max() + 1) * sc + mx)
    y0, y1 = max(0, ys.min() * sc - my), min(h, (ys.max() + 1) * sc + my)
    cw, ch = (x1 - x0) // 2 * 2, (y1 - y0) // 2 * 2
    ow = min(a.width, cw) // 2 * 2
    oh = int(round(ch * ow / cw)) // 2 * 2
    b = a.black
    lut = f"lutrgb=r='clip((val-{b*255:.1f})*255/(255-{b*255:.1f}),0,255)':g='clip((val-{b*255:.1f})*255/(255-{b*255:.1f}),0,255)':b='clip((val-{b*255:.1f})*255/(255-{b*255:.1f}),0,255)'"
    base = f"trim=end_frame={cut},setpts=PTS-STARTPTS,crop={cw}:{ch}:{x0}:{y0},scale={ow}:{oh}:flags=lanczos"
    if a.mask is not None:
        write_mask(a.out, ow, oh, a.mask)
    if a.stacked:
        lo, hi = a.stacked[0] * 255, a.stacked[1] * 255
        ramp = f"lut=y='clip((val-{lo:.1f})*255/({hi - lo:.1f}),0,255)'"
        if a.fill > 0:
            fill_stacked(a, base, lut, lo, hi, ow, oh, fps)
            print(f"{a.out}: frames 0..{cut - 1} of {n} (wrap error {min(err):.5f}), crop {cw}x{ch}+{x0}+{y0} -> {ow}x{oh}"
                  " + its alpha below (stacked, filled)")
            return
        matte = f"[m]format=gray,{ramp},format=yuv420p[aa];"
        graph = (f"[0:v]{base},split[c][m];[c]{lut},format=yuv420p[cc];" + matte +
                 f"[cc][aa]vstack,format=yuv420p[v]")
        args = ["-filter_complex", graph, "-map", "[v]"]
    else:
        args = ["-vf", f"{base},{lut},format=yuv420p"]
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", a.raw, "-an", *args, "-r", f"{fps:g}",
                    "-c:v", "libx264", "-preset", "slow", "-crf", "17", "-movflags", "+faststart", a.out], check=True)
    print(f"{a.out}: frames 0..{cut - 1} of {n} (wrap error {min(err):.5f}), crop {cw}x{ch}+{x0}+{y0} -> {ow}x{oh}"
          + (" + its alpha below (stacked)" if a.stacked else ""))


if __name__ == "__main__":
    main()
