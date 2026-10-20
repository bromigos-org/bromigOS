#!/usr/bin/env python3
"""End to end: the theme switcher's previews are pictures of the whole desktop, at the size
asked for.

A preview is the real desktop drawn where nobody sees it: a Hyprland nested in a headless
kwin (lib/bromigos_previews.py, Nested), captured by grim inside it. On 2026-10-17 kwin 6.8
started sending the nested Hyprland a late "choose your own size", which Hyprland's Wayland
backend reads as 1280x720: every preview showed only the desktop's top-left corner, and
nothing noticed. This draws the Wick in a throwaway home (this checkout's `bromigos` and
renderer, as tools/theme-switcher/render.sh does) and checks:

  - `bromigos theme previews wick --size WxH --out FILE` at 1920x1080 and 1600x900: drawn
    nested (not the composed fallback), grim's picture WxH, and FILE WxH;
  - the cached preview (`bromigos theme previews wick`): drawn nested, captured at
    1920x1080, kept as a 1280x720 JPEG.

Nothing reaches the desktop you're on: no window, no screenshot of your screen.

Not part of `unittest discover` (it needs kwin_wayland, Hyprland, grim and a GPU). Build
`bromigos` first (cargo build -p bromigos in core/, or set $BROMIGOS):

    python3 desktop/tests/e2e_previews_nested.py [--keep]
"""
import glob
import json
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(REPO, "desktop", "lib"))
import bromigos_previews as PV  # noqa: E402

RENDERER = os.path.join(REPO, "desktop", "bin", "bromigos-theme-previews")
SIZES = [(1920, 1080), (1600, 900)]


def sandbox(tmp):
    """A throwaway home and a `bromigos` that never finds the desktop's session; returns run(argv)."""
    bro = os.environ.get("BROMIGOS") or os.path.join(REPO, "core", "target", "debug", "bromigos")
    if not os.access(bro, os.X_OK):
        sys.exit(f"needs {bro} (cargo build -p bromigos in core/, or set $BROMIGOS)")
    for d in ("bin", "home", "config", "state", "cache", "data", "run"):
        os.makedirs(os.path.join(tmp, d))
    os.chmod(os.path.join(tmp, "run"), 0o700)
    wrapper = os.path.join(tmp, "bin", "bromigos")
    with open(wrapper, "w") as f:
        f.write(f'#!/bin/sh\n[ "$1" = session ] && exit 0\n'
                f'export BROMIGOS_LIB_BIN="{REPO}/desktop/bin" BROMIGOS_WIDGETS_DEMO=1\nexec "{bro}" "$@"\n')
    os.chmod(wrapper, 0o755)
    env = {"HOME": os.path.join(tmp, "home"), "XDG_CONFIG_HOME": os.path.join(tmp, "config"),
           "XDG_STATE_HOME": os.path.join(tmp, "state"), "XDG_CACHE_HOME": os.path.join(tmp, "cache"),
           "XDG_DATA_HOME": os.path.join(tmp, "data"), "XDG_RUNTIME_DIR": os.path.join(tmp, "run"),
           "PATH": f"{tmp}/bin:{REPO}/desktop/bin:/usr/bin:/bin", "LANG": "C.UTF-8", "TZ": "UTC",
           "BROMIGOS": wrapper, "NO_AT_BRIDGE": "1", "GSK_RENDERER": "cairo"}
    for k in ("__EGL_VENDOR_LIBRARY_FILENAMES", "__GLX_VENDOR_LIBRARY_NAME"):
        if k in os.environ:
            env[k] = os.environ[k]

    def run(argv, timeout=300):
        return subprocess.run(argv, env=env, capture_output=True, text=True, timeout=timeout)
    run(["bromigos", "theme", "set", "wick", "--no-reload"])
    return run


def main():
    keep = "--keep" in sys.argv
    why = PV.nested_missing()
    if why:
        print(f"SKIP: the nested desktop can't be drawn here ({why})")
        return 0
    from PIL import Image
    tmp = tempfile.mkdtemp(prefix="bromigos-e2e-previews.")
    run = sandbox(tmp)
    results = []

    def check(ok, what, detail=""):
        results.append(ok)
        print(f"{'PASS' if ok else 'FAIL'}  {what}" + ("" if ok or not detail else f"\n      {detail}"))

    try:
        for w, h in SIZES:
            out = os.path.join(tmp, f"wick-{w}x{h}.png")
            r = run([sys.executable, RENDERER, "wick", "--size", f"{w}x{h}", "--out", out, "--json"])
            try:
                meta = json.loads(r.stdout)["results"][0]
            except (ValueError, KeyError, IndexError):
                meta = {"error": (r.stdout + r.stderr)[-600:]}
            check(meta.get("desktop") == "nested", f"{w}x{h}: drawn nested",
                  meta.get("error") or "; ".join(meta.get("notes", [])))
            check(meta.get("captured") == [w, h], f"{w}x{h}: grim's picture is {w}x{h}",
                  f"captured {meta.get('captured')}")
            size = Image.open(out).size if os.path.exists(out) else None
            check(size == (w, h), f"{w}x{h}: the picture written is {w}x{h}", f"it is {size}")
        r = run([sys.executable, RENDERER, "wick", "--json"])
        jpgs = [p for p in glob.glob(os.path.join(tmp, "cache", "bromigos", "theme-previews", "wick-*.jpg"))]
        check(len(jpgs) == 1, "the cached preview is drawn", (r.stdout + r.stderr)[-600:])
        if jpgs:
            with open(os.path.splitext(jpgs[0])[0] + ".json") as f:
                meta = json.load(f)
            check(meta.get("desktop") == "nested" and meta.get("captured") == meta.get("size") == [1920, 1080],
                  "the cached preview was captured whole, at 1920x1080",
                  f"desktop {meta.get('desktop')}, size {meta.get('size')}, captured {meta.get('captured')}")
            check(Image.open(jpgs[0]).size == (PV.SAVE_W, PV.SAVE_H), "it's kept at 1280x720")
    finally:
        if keep:
            print(f"kept: {tmp}")
        else:
            shutil.rmtree(tmp, ignore_errors=True)
    failed = results.count(False)
    print(f"\n{len(results) - failed}/{len(results)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
