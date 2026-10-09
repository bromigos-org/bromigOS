#!/usr/bin/env python3
"""Checks an offscreen run of the theme switcher (tools/theme-switcher/render.sh OUTDIR):

  - every shipped theme (themes/* in this checkout) has a preview in OUTDIR/previews,
    1280x720, drawn from every piece (the live layer's frame, the bar, the SYSTEM and
    NETWORK panels, the terminal) and not blank;
  - every preview differs from every other where the theme shows: the bar and the SYSTEM
    panel (the den is the same behind every colour theme, so the whole picture can be
    close between two of them);
  - the switcher was drawn at each size given, at that size.

  tools/theme-switcher/check.py OUTDIR [WxH …]     (default sizes: render.sh's four)

Exit 0 when everything passes; one line per check.
"""
import glob
import itertools
import json
import os
import re
import sys

from PIL import Image, ImageChops, ImageStat

ROOT = os.path.normpath(os.path.join(os.path.dirname(os.path.realpath(__file__)), "..", ".."))
SIZES = ["1366x768", "1920x1080", "2560x1440", "3440x1440"]
PIECES = {"background", "bar", "panel:system", "panel:network", "terminal"}
# where a preview wears the theme, in the saved 1280x720 picture: the bar, the SYSTEM panel
REGIONS = [(0, 0, 1280, 22), (19, 34, 331, 345)]
MIN_DIFF = 2.0


def main():
    out = sys.argv[1]
    sizes = sys.argv[2:] or SIZES
    fails = []

    def check(ok, what):
        print(f"{'PASS' if ok else 'FAIL'}  {what}")
        if not ok:
            fails.append(what)

    themes = sorted(os.path.basename(d.rstrip("/")) for d in glob.glob(os.path.join(ROOT, "themes", "*/"))
                    if os.path.exists(os.path.join(d, "colors.toml")))
    previews = {}
    for t in themes:
        found = [p for p in glob.glob(os.path.join(out, "previews", f"{t}-*.jpg"))
                 if re.fullmatch(re.escape(t) + r"-[0-9a-f]{12}\.jpg", os.path.basename(p))]
        check(len(found) == 1, f"{t}: one preview ({len(found)} found)")
        if not found:
            continue
        p = found[0]
        im = Image.open(p).convert("RGB")
        check(im.size == (1280, 720), f"{t}: 1280x720 ({im.size[0]}x{im.size[1]})")
        lum = ImageStat.Stat(im.convert("L")).mean[0]
        check(lum > 8, f"{t}: not blank (mean light {lum:.1f})")
        try:
            with open(os.path.splitext(p)[0] + ".json") as f:
                meta = json.load(f)
        except (OSError, ValueError):
            meta = {}
        missing = PIECES - set(meta.get("pieces", []))
        check(not missing, f"{t}: every piece drawn" + (f" (missing {', '.join(sorted(missing))}; "
                                                        f"{'; '.join(meta.get('notes', []))})" if missing else
                                                        f" ({meta.get('background')}, {meta.get('seconds')} s)"))
        previews[t] = im
    worst = None
    for a, b in itertools.combinations(sorted(previews), 2):
        d = min(sum(ImageStat.Stat(ImageChops.difference(previews[a].crop(r), previews[b].crop(r))).mean) / 3
                for r in REGIONS)
        if worst is None or d < worst[0]:
            worst = (d, a, b)
    if worst:
        check(worst[0] >= MIN_DIFF, f"every preview differs from every other in the theme's colours "
                                    f"(closest: {worst[1]} and {worst[2]}, {worst[0]:.1f} >= {MIN_DIFF})")
    for s in sizes:
        p = os.path.join(out, f"switcher-{s}.png")
        if not os.path.exists(p):
            check(False, f"switcher at {s}: {p} missing")
            continue
        w, h = Image.open(p).size
        check(f"{w}x{h}" == s, f"switcher at {s}: drawn at {w}x{h}")
    print(f"{len(fails)} failed" if fails else "all passed")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
