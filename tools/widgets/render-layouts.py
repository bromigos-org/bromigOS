#!/usr/bin/env python3
"""Offscreen pictures of the widget layouts (docs/widgets.md, "Layouts"): a layout fitted to
a theme's scene at a screen size, drawn as the real desktop with demo readings by the theme
previews' renderer (desktop/lib/bromigos_previews.py: a nested Hyprland in a headless kwin,
the live layer's own frame behind it), and a copy with the scene's keep-clear areas outlined
(dashed red: kept clear; dashed amber: kept clear while there's room elsewhere), to check the
scene shows.

    tools/widgets/render-layouts.py OUTDIR [--size 2560x1440] [--lab big] THEME:LAYOUT…

LAYOUT is a layout's id (minimal, homelab, …), "theme" (the theme's own) or a layout file's
path (THEME:path/to/my-desk.toml). Widgets that fit their content get the height their demo
readings need (gallery.naturals_of). --lab big: LAB shows a lab the size a real one grows to
(demo_lab.BIG_LAB: six nodes, 36 services), so the picture shows LAB fitting a big lab.
For example:

    tools/widgets/render-layouts.py out wick:theme tidewell:theme mire:theme wick:homelab tidewell:homelab

Each makes OUTDIR/THEME-LAYOUT.png and OUTDIR/THEME-LAYOUT-clear.png, and prints what each
layout placed and left out. Nothing runs in your session: every piece runs in a throwaway
home (BROMIGOS_PREVIEWS_NESTED=0: composed from the pieces instead, where kwin_wayland,
Hyprland or grim are missing). Build this checkout's `bromigos` first, or set BROMIGOS to
one (`--bromigos "$(command -v bromigos)"` does the same).
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.realpath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(ROOT, "widgets"))
sys.path.insert(0, os.path.join(ROOT, "desktop", "lib"))
BAR = 34                                    # the bar's height: the panels' area starts under it


def catalog(sandbox):
    """Every widget with demo readings, the homelab's too (a made-up lab), all signed in."""
    env = dict(os.environ, BROMIGOS_WIDGETS_DEMO="1", BROMIGOS_WIDGETS_DEMO_LAB="1",
               BROMIGOS_HOMELAB=os.path.join(ROOT, "homelab"), **sandbox)
    code = ("import json, gallery, layouts as L; e = gallery.entries(); "
            "print(json.dumps(L.catalog_of(e, lambda p: True, naturals=gallery.naturals_of(e))))")
    r = subprocess.run([sys.executable, "-c", code], cwd=os.path.join(ROOT, "widgets"), env=env,
                       capture_output=True, text=True, timeout=180)
    if r.returncode:
        raise SystemExit(r.stderr[-2000:])
    doc = json.loads(r.stdout.strip().splitlines()[-1])
    for c in doc.values():
        c["classes"] = [(n, tuple(lo), tuple(hi), tuple(st)) for n, lo, hi, st in c["classes"]]
    return doc


def outline(src, dst, fit, info):
    from PIL import Image, ImageDraw
    im = Image.open(src).convert("RGB")
    d = ImageDraw.Draw(im, "RGBA")
    for c in fit["clear"]:
        x, y, w, h = c["x"], c["y"] + BAR, c["width"], c["height"]
        col = (255, 190, 40, 230) if c["soft"] else (255, 70, 60, 240)
        for i in range(0, max(w, h), 24):          # dashed
            if i < w:
                d.line([(x + i, y), (x + min(w, i + 12), y)], fill=col, width=3)
                d.line([(x + i, y + h), (x + min(w, i + 12), y + h)], fill=col, width=3)
            if i < h:
                d.line([(x, y + i), (x, y + min(h, i + 12))], fill=col, width=3)
                d.line([(x + w, y + i), (x + w, y + min(h, i + 12))], fill=col, width=3)
        d.text((x + 8, y + 6), c["name"], fill=col)
    im.save(dst)


def main(argv):
    if "--bromigos" in argv:
        i = argv.index("--bromigos")
        os.environ["BROMIGOS"] = argv[i + 1]
        del argv[i:i + 2]
    if "--lab" in argv:
        i = argv.index("--lab")
        os.environ["BROMIGOS_WIDGETS_DEMO_LAB_SIZE"] = argv[i + 1]
        del argv[i:i + 2]
    size = (2560, 1440)
    if "--size" in argv:
        i = argv.index("--size")
        size = tuple(int(v) for v in argv[i + 1].split("x"))
        del argv[i:i + 2]
    if len(argv) < 2:
        print(__doc__)
        return 2
    out = os.path.abspath(argv[0])
    os.makedirs(out, exist_ok=True)
    work = tempfile.mkdtemp(prefix="bromigos-layout-render.")
    sandbox = {"HOME": os.path.join(work, "home"), "XDG_CONFIG_HOME": os.path.join(work, "config"),
               "XDG_STATE_HOME": os.path.join(work, "state"), "XDG_DATA_HOME": os.path.join(work, "data"),
               "XDG_CACHE_HOME": os.path.join(work, "cache"), "DBUS_SESSION_BUS_ADDRESS": "disabled:"}
    for v in sandbox.values():
        if v.startswith(work):
            os.makedirs(v, exist_ok=True)
    os.environ.update(sandbox)                  # the previews' cache and boxes: the throwaway home's
    for k in ("WAYLAND_DISPLAY", "DISPLAY", "HYPRLAND_INSTANCE_SIGNATURE"):
        os.environ.pop(k, None)
    import layouts as L
    cat = catalog(sandbox)
    fails = 0
    try:
        for job in argv[1:]:
            theme, _, ident = job.partition(":")
            ident = ident or "theme"
            info = L.scene_info(theme, os.path.join(ROOT, "themes", theme))
            if ident.endswith(".toml"):                 # a layout file of anyone's
                t = L.load(os.path.expanduser(ident))
                ident = t["id"]
            else:
                t = info["recommended"] if ident == "theme" else L.templates()[ident]
            scr = L.Screen.size(*size, bar=BAR)
            fit = L.fit(t, scr, cat, info["clear"], info.get("focus"))
            scene = {"panels": [{"name": n, "x": p["x"], "y": p["y"], "width": p["width"], "height": p["height"]}
                                for n, p in fit["placed"].items()], "terminal": False}
            sf = os.path.join(work, f"{theme}-{ident}.json")
            with open(sf, "w") as f:
                json.dump(scene, f)
            png = os.path.join(out, f"{theme}-{ident}.png")
            env = dict(os.environ, BROMIGOS_WIDGETS_DEMO_LAB="1", BROMIGOS_HOMELAB=os.path.join(ROOT, "homelab"))
            r = subprocess.run([sys.executable, os.path.join(ROOT, "desktop", "bin", "bromigos-theme-previews"),
                                theme, "--size", f"{size[0]}x{size[1]}", "--scene", sf, "--out", png, "--json"],
                               env=env, capture_output=True, text=True, timeout=600)
            if r.returncode or not os.path.exists(png):
                print(f"FAILED {theme}:{ident}: {(r.stdout + r.stderr)[-600:]}")
                fails += 1
                continue
            outline(png, os.path.join(out, f"{theme}-{ident}-clear.png"), fit, info)
            print(f"{theme}:{ident} {t['title']}: " + ", ".join(f"{n} {p['x']},{p['y']} {p['width']}x{p['height']}"
                                                            for n, p in fit["placed"].items())
                  + f"; covers {round(fit['coverage'] * 100)}%"
                  + "".join(f"; {x['title']} left out: {x['why']}" for x in fit["left_out"]) + f" -> {png}")
    finally:
        shutil.rmtree(work, ignore_errors=True)
    return fails


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
