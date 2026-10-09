#!/usr/bin/env python3
"""Waits for a boot menu on the test VM's screen and saves it (docs/iso.md, "Testing it").

  screen-wait.py --qmp SOCK --out PNG [--timeout 120] [--bar 280] [--settle 1.0] [--keys down,down]

Takes QEMU's screen through its monitor (screendump) every half second until a menu's
selection bar shows: a row with a run of at least --bar light pixels (bromigOS's phosphor
bar in GRUB's theme or vesamenu, GRUB's own highlighted row). The firmware's logo, the
kernel's text and the splash have none that long. Then it waits --settle, presses --keys
(QMP send-key, one each), waits again and saves --out. Exit 1 when no menu showed in
--timeout seconds (the last screen is saved anyway, to see what was there).
"""

import argparse
import json
import os
import socket
import sys
import tempfile
import time

from PIL import Image


def qmp(path, *cmds):
    s = socket.socket(socket.AF_UNIX)
    s.settimeout(10)
    here = os.getcwd()
    os.chdir(os.path.dirname(path) or ".")          # a socket's path may not pass 107 bytes
    try:
        s.connect(os.path.basename(path))
    finally:
        os.chdir(here)
    f = s.makefile("rw")
    f.readline()
    for c in ({"execute": "qmp_capabilities"}, *cmds):
        f.write(json.dumps(c) + "\n")
        f.flush()
        while True:
            line = f.readline()
            if not line:
                break
            msg = json.loads(line)
            if "return" in msg or "error" in msg:
                break
    s.close()


def screen(sock, ppm):
    if os.path.exists(ppm):
        os.unlink(ppm)
    qmp(sock, {"execute": "screendump", "arguments": {"filename": ppm}})
    for _ in range(20):
        if os.path.exists(ppm) and os.path.getsize(ppm) > 0:
            try:
                return Image.open(ppm).convert("RGB")
            except OSError:
                pass
        time.sleep(0.1)
    return None


def longest_bar(im, coloured=False):
    """The longest run of light pixels in any row (every other row); `coloured`: of a colour
    (a theme's phosphor bar), not white or grey (the firmware's frames, GRUB's own menu)."""
    w, h = im.size
    px = im.load()
    best = 0
    for y in range(0, h, 2):
        run = 0
        for x in range(w):
            r, g, b = px[x, y]
            if max(r, g, b) > 150 and (r + g + b) > 260 and (not coloured or max(r, g, b) - min(r, g, b) > 80):
                run += 1
                if run > best:
                    best = run
            else:
                run = 0
    return best


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--qmp", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--timeout", type=float, default=120)
    ap.add_argument("--bar", type=int, default=280)
    ap.add_argument("--settle", type=float, default=1.0)
    ap.add_argument("--keys", default="")
    ap.add_argument("--coloured", action="store_true", help="only a coloured bar counts (a bromigOS theme's)")
    args = ap.parse_args(argv)
    with tempfile.TemporaryDirectory(dir=os.path.dirname(os.path.abspath(args.out))) as tmp:
        ppm = os.path.join(tmp, "screen.ppm")
        deadline = time.time() + args.timeout
        im = None
        found = False
        while time.time() < deadline:
            im = screen(args.qmp, ppm)
            if im is not None and longest_bar(im.resize((im.width // 2, im.height // 2)), args.coloured) * 2 >= args.bar:
                found = True
                break
            time.sleep(0.5)
        if found:
            time.sleep(args.settle)
            for k in [k for k in args.keys.split(",") if k]:
                qmp(args.qmp, {"execute": "send-key", "arguments": {"keys": [{"type": "qcode", "data": q} for q in k.split("-")]}})
                time.sleep(0.4)
            if args.keys:
                time.sleep(args.settle)
            im = screen(args.qmp, ppm) or im
        if im is not None:
            im.save(args.out)
            print(f"{args.out} {im.width}x{im.height}" + ("" if found else " (no menu)"))
    return 0 if found else 1


if __name__ == "__main__":
    sys.exit(main())
