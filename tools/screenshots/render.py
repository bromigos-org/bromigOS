#!/usr/bin/env python3
"""The README's and the manual's pictures of bromigOS, drawn offscreen.

  tools/screenshots/render.py OUTDIR [--only ID[,ID…]] [--list] [--catalog FILE] [--previews DIR]
                              [--loop-seconds S] [--no-check]

Every picture is the real desktop drawn where nobody sees it: `bromigos theme previews`'
nested desktop (a Hyprland running bromigOS's own config in a headless kwin, with the
real waybar, panels and kitty, grim's picture of it; desktop/lib/bromigos_previews.py),
with the scenes in scenes/ (which panels, where, the terminal), plus what opens over it:
the live layer's decks and VECTOR's console (their offscreen renderers, EGL, composited
where the desktop puts them), the menu and Settings (run in the nested desktop), the
theme switcher (tools/theme-switcher/render.sh), `bromigos lab` (in the nested desktop's
terminal, on the recorded lab of homelab/tests) and the boot menu (settings/grub/preview.py).
Demo readings everywhere: no picture shows the machine it was drawn on, its network or
a lab of yours. Nothing opens a window on the desktop you're on.

  OUTDIR/masters/ID.png       the 2560x1440 master (lossless)
  OUTDIR/ID.webp              the master as WebP (2560 wide)
  OUTDIR/ID-1600.webp         the README's size (1600 wide)
  OUTDIR/loop-ID.webp         the animated loop (README size)
  OUTDIR/manifest.md, .json   each file, what it shows, its size, the check's verdict

The check (unless --no-check): every picture and a frame a second of the loop read back
with tesseract, against the words a picture must never show (the internal tools' names,
the operator's name, IP addresses and LAN host names, home paths) and, when this machine
has one, the private overlay's host and node names (read in memory, never printed: the
report gives reasons and counts only). Look at every picture too.

--catalog: the lore catalog the Drift map draws (a public one: the site's export); without
it the Drift map isn't drawn. --previews: the theme previews to reuse (a cache folder of
`bromigos theme previews`); without it they're drawn into OUTDIR/previews.

Needs what `bromigos theme previews` needs for its nested desktop (kwin_wayland, Hyprland,
waybar, grim, swaybg, kitty), a GPU with EGL for the live layer and VECTOR, weston for the
switcher, qemu with OVMF for the boot menu, ffmpeg (libwebp) and tesseract.
"""
import argparse
import json
import math
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.realpath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path[:0] = [os.path.join(ROOT, "desktop", "lib"), os.path.join(ROOT, "lib")]
os.environ.setdefault("BROMIGOS_SRC", ROOT)
import bromigos_previews as PV  # noqa: E402

SYS_PY = PV.SYS_PY
W, H = 2560, 1440
README_W = 1600
SCENES = os.path.join(HERE, "scenes")
VECTOR = next((d for d in (os.environ.get("BROMIGOS_VECTOR_SRC"), os.path.join(os.path.dirname(ROOT), "vector"),
                           "/usr/lib/bromigos/vector") if d and os.path.isfile(os.path.join(d, "tools", "offscreen.py"))),
              None)
THEMES = ["wick", "mire", "tidewell", "cinder", "deepvein", "highwind", "lowtown", "rime", "sunder"]


def scene(name):
    return os.path.join(SCENES, name + ".json")


# ------------------------------------------------------------------ the pieces
class Ctx:
    def __init__(self, out, args):
        self.out = out
        self.args = args
        self.work = tempfile.mkdtemp(prefix="bromigos-shots.")
        self.masters = os.path.join(out, "masters")
        os.makedirs(self.masters, exist_ok=True)
        self.log = os.path.join(self.work, "render.log")
        self._previews = args.previews

    def close(self):
        shutil.rmtree(self.work, ignore_errors=True)

    def desktop(self, theme, scn, out, hook=None, size=(W, H)):
        """The nested desktop wearing `theme`, the scene's panels and terminal, to `out`."""
        r = PV.render([theme], out=out, size=size, scene=scn, hook=hook)[0]
        if r.get("error"):
            raise RuntimeError(f"{theme}: {r['error']}")
        if r.get("desktop") != "nested":
            raise RuntimeError(f"{theme}: not the nested desktop ({'; '.join(r.get('notes', []))})")
        try:                                     # the renderer's notes beside the picture: not ours
            os.unlink(os.path.splitext(out)[0] + ".json")
        except OSError:
            pass
        return r

    def box(self, theme):
        base = tempfile.mkdtemp(prefix="b.", dir=self.work)
        b = PV.Box(base, theme)
        b.set_theme(self.log)
        return b

    def live(self, box, kind, out, times, catalog=None, extra=None, w=W, h=H):
        """The live layer's offscreen renderer (a deck, an overlay, a world) in the box, with
        the previews' demo readings and a made-up lab, to an RGBA PNG (or a clip: out.mp4,
        times = [seconds, fps])."""
        cfg = os.path.join(box.dir, "live-config.toml")
        lines = ["[background]", f'underlay = "{PV.SRC.den}"', f'underlay_fallback = "{PV.SRC.den}"',
                 "[cluster]", 'url = ""', 'token_file = ""', "[fills]", 'url = ""', 'console = ""', 'endpoint = ""',
                 "[sounds]", "enabled = false", "[world]", "ambient_sounds = false", 'dir = ""',
                 "[codec]", 'tts_url = ""']
        if catalog:
            lines += ["[driftmap]", f'catalog = "{catalog}"']
        with open(cfg, "w") as f:
            f.write("\n".join(lines) + "\n")
        share = os.path.join(box.dir, "share")
        if not os.path.exists(os.path.join(share, "live", "config.toml")):
            shutil.copy(os.path.join(PV.SRC.live, "config.toml"), os.path.join(share, "live", "config.toml"))
            for e in os.listdir(PV.SRC.share):
                link = os.path.join(share, e)
                if e != "live" and not os.path.lexists(link):
                    os.symlink(os.path.join(PV.SRC.share, e), link)
        env = dict(BROMIGOS_LIVE_CONFIG=cfg, BROMIGOS_SHARE_DIR=share, PYOPENGL_PLATFORM="egl",
                   EGL_PLATFORM="surfaceless", OFF_W=w, OFF_H=h, OFF_WARM="0.3", OFF_READY="20", OFF_OPAQUE="0",
                   PV_LIVE=PV.SRC.live, PV_WIDGETS=PV.SRC.widgets, PV_DEMO_LAB="1",
                   BROMIGOS_VECTOR=VECTOR or os.path.join(box.dir, "empty"))
        env.update(extra or {})
        r = box.run([SYS_PY, PV.__file__, "--child", "live", kind, out] + [str(t) for t in times], 1200, self.log,
                    **env)
        if r.returncode != 0 or not os.path.exists(out):
            raise RuntimeError(f"the live layer's {kind} failed (log: {self.log})")
        return out

    def previews(self):
        """A cache of the nine themes' previews (the switcher's, the Theme page's, the grid's)."""
        if self._previews:
            return self._previews
        d = os.path.join(self.out, "previews")
        cache = os.path.join(d, "cache")
        os.makedirs(cache, exist_ok=True)
        env = dict(os.environ, XDG_CACHE_HOME=cache)
        r = subprocess.run([sys.executable, os.path.join(ROOT, "desktop", "bin", "bromigos-theme-previews"),
                            "--quiet"], env=env)
        if r.returncode != 0:
            raise RuntimeError("the theme previews failed")
        self._previews = os.path.join(cache, "bromigos", "theme-previews")
        return self._previews


def over(base, layer, xy=(0, 0)):
    """`layer` (premultiplied RGBA, as GL draws it) over `base` (RGB) at xy: a new RGB image."""
    import numpy as np
    from PIL import Image
    b = np.asarray(base.convert("RGB")).astype(np.float32).copy()
    la = np.asarray(layer.convert("RGBA")).astype(np.float32)
    x, y = xy
    h, w = la.shape[:2]
    reg = b[y:y + h, x:x + w]
    al = la[..., 3:4] / 255.0
    b[y:y + h, x:x + w] = np.clip(la[..., :3] + reg * (1 - al), 0, 255)
    return Image.fromarray(b.astype(np.uint8))


def wait_for(fn, t):
    end = time.time() + t
    while time.time() < end:
        v = fn()
        if v:
            return v
        time.sleep(0.1)
    return fn()


# ------------------------------------------------------------------ the pictures
SHOTS = []


def shot(id, title, what):
    def deco(fn):
        SHOTS.append({"id": id, "title": title, "what": what, "fn": fn})
        return fn
    return deco


@shot("hero-wick", "The Wick, at work",
      "The desktop in the Wick (the default den) at 2560x1440: the bar, the panels as a user arranges them "
      "(SYSTEM, NETWORK, WEATHER, STORAGE; LAB, WORKBENCH, FIELD NOTES) and a terminal with the login banner. "
      "The den's screens are the live layer's.")
def _hero(ctx, m):
    ctx.desktop("wick", scene("hero"), m)


def _world(theme):
    def fn(ctx, m):
        ctx.desktop(theme, scene("world"), m)
    return fn


shot("world-mire", "Mire, a world theme",
     "Mire: a world theme's live scene (the stilt shack, its keeper, the Sleepers risen for working agents, "
     "fireflies for traffic) behind the bar, SYSTEM, NETWORK and WEATHER and a terminal.")(_world("mire"))
shot("world-tidewell", "Tidewell, a world theme",
     "Tidewell: Greywater Light above the water and the Choir below, behind the bar, the panels and a "
     "terminal.")(_world("tidewell"))


def _colour(theme):
    def fn(ctx, m):
        ctx.desktop(theme, scene("colour"), m)
    return fn


shot("theme-cinder", "Cinder, a colour theme",
     "Cinder: a colour theme recolours everything, the den included (its painted plate, the live screens, the "
     "burn-in), the bar, the panels and the terminal's palette.")(_colour("cinder"))
shot("theme-highwind", "Highwind, a colour theme",
     "Highwind: kite-lantern gold on a dusk sky, the den and every panel in its colours.")(_colour("highwind"))


@shot("themes-grid", "Nine themes",
      "Every theme bromigOS ships, as the theme switcher previews them (3x3, each named): the Wick, Mire, "
      "Tidewell and six colour themes.")
def _grid(ctx, m):
    import glob
    from PIL import Image, ImageDraw
    cache = ctx.previews()
    names = THEMES
    cols, gap, pad, label = 3, 24, 40, 112
    cw = (W - 2 * pad - (cols - 1) * gap) // cols
    ch = cw * 9 // 16
    rows = math.ceil(len(names) / cols)
    hh = 2 * pad + rows * (ch + label) + (rows - 1) * gap
    sheet = Image.new("RGB", (W, hh), (6, 8, 7))
    d = ImageDraw.Draw(sheet)
    font = _font(30, bold=True)
    small = _font(22)
    for i, n in enumerate(names):
        pics = sorted(glob.glob(os.path.join(cache, f"{n}-*.jpg")), key=os.path.getmtime)
        if not pics:
            raise RuntimeError(f"no preview of {n} in {cache}")
        pal = _palette(n)
        r, c = divmod(i, cols)
        x = pad + c * (cw + gap)
        y = pad + r * (ch + label + gap)
        im = Image.open(pics[-1]).convert("RGB").resize((cw, ch), Image.LANCZOS)
        sheet.paste(im, (x, y))
        d.rectangle((x - 1, y - 1, x + cw, y + ch), outline=pal["primary"], width=2)
        meta = _theme_meta(n)
        d.text((x + 2, y + ch + 12), meta["name"].upper(), font=font, fill=pal["primary"])
        kind = "WORLD" if meta["world"] else ("DEN" if n == "wick" else "COLOUR")
        kw = d.textlength(kind, font=small)
        d.text((x + cw - kw - 2, y + ch + 19), kind, font=small, fill=pal["primary"])
        # the theme's description, whole, wrapped to the card's width (two lines at most)
        lines = _wrap(d, meta.get("tagline") or "", small, cw - 4)
        if len(lines) > 2:
            raise RuntimeError(f"{n}'s description needs {len(lines)} lines under its card")
        for k, ln in enumerate(lines):
            d.text((x + 2, y + ch + 54 + k * 28), ln, font=small, fill=(160, 170, 160))
    sheet.save(m)


def _wrap(d, text, font, width):
    """`text` in lines no wider than `width`, broken between words."""
    lines, cur = [], ""
    for w in text.split():
        t = f"{cur} {w}".strip()
        if d.textlength(t, font=font) <= width or not cur:
            cur = t
        else:
            lines.append(cur)
            cur = w
    return lines + ([cur] if cur else [])


def _font(size, bold=False):
    from PIL import ImageFont
    for f in (["GeistMono-Bold.ttf", "GeistMono-SemiBold.ttf"] if bold else []) + ["GeistMono-Regular.ttf"]:
        for d in ("/usr/share/fonts/TTF", "/usr/share/fonts/geist-mono", "/usr/share/fonts/OTF",
                  "/usr/share/fonts/truetype"):
            p = os.path.join(d, f)
            if os.path.exists(p):
                return ImageFont.truetype(p, size)
    r = subprocess.run(["fc-match", "-f", "%{file}", f"Geist Mono:{'bold' if bold else 'regular'}"],
                       capture_output=True, text=True)
    if r.returncode == 0 and r.stdout:
        return ImageFont.truetype(r.stdout, size)
    return ImageFont.load_default(size)


def _theme_meta(n):
    import tomllib
    d = os.path.join(PV.SRC.share, "themes", n)
    with open(os.path.join(d, "theme.toml"), "rb") as f:
        meta = tomllib.load(f)
    return {"name": meta.get("name", n.capitalize()), "tagline": meta.get("description") or meta.get("tagline", ""),
            "world": os.path.exists(os.path.join(d, "live", "world.toml"))}


def _palette(n):
    import tomllib
    with open(os.path.join(PV.SRC.share, "themes", n, "colors.toml"), "rb") as f:
        c = tomllib.load(f)
    flat = {k: v for k, v in c.items() if isinstance(v, str)}
    flat.update({k: v for k, v in (c.get("colors") or {}).items() if isinstance(v, str)})

    def res(v, seen=()):
        if v.startswith("#"):
            return v
        return res(flat[v], seen + (v,)) if v in flat and v not in seen else "#39ff14"
    prim = res(flat.get("primary", "#39ff14"))
    return {"primary": tuple(int(prim.lstrip("#")[i:i + 2], 16) for i in (0, 2, 4))}


@shot("vector", "VECTOR, the caretaker",
      "VECTOR on the desktop (SUPER+E): his construct and his console in the corner, answering a question about "
      "the (made-up) lab, over the Wick with its panels.")
def _vector(ctx, m):
    from PIL import Image
    base = os.path.join(ctx.work, "vector-desk.png")
    ctx.desktop("wick", scene("vector"), base)
    if not VECTOR:
        raise RuntimeError("no VECTOR (the vector repository beside this one, or bromigos-vector)")
    box = ctx.box("wick")
    out = os.path.join(ctx.work, "vector.png")
    r = box.run([SYS_PY, os.path.abspath(__file__), "--child", "vector", out, "speaking"], 180, ctx.log,
                PV_VECTOR=VECTOR, OFF_W=1180, OFF_H=640, PYOPENGL_PLATFORM="egl", OFF_WARM="3")
    if r.returncode != 0 or not os.path.exists(out):
        raise RuntimeError(f"VECTOR's render failed (log: {ctx.log})")
    # his window: 1180x640, anchored bottom right, 24 px in (vector holo/app.py)
    over(Image.open(base), Image.open(out), (W - 24 - 1180, H - 24 - 640)).save(m)


def _deck(kind, times, scn="hero", catalog=False, extra=None):
    def fn(ctx, m):
        from PIL import Image
        if catalog and not ctx.args.catalog:
            raise SkipShot("no --catalog: the Drift map needs a public lore catalog")
        base = os.path.join(ctx.work, f"{kind}-desk.png")
        ctx.desktop("wick", scene(scn), base)
        box = ctx.box("wick")
        if kind == "timeline":
            demo_history(os.path.join(box.dir, "state", "bromigos-live"))
        out = os.path.join(ctx.work, f"{kind}.png")
        ctx.live(box, kind, out, times, catalog=clean_catalog(ctx) if catalog else None, extra=extra)
        over(Image.open(base), Image.open(out)).save(m)
    return fn


def clean_catalog(ctx):
    """The --catalog without the entries (and the lanes to them) whose name or summary the
    check would stop: a public catalog can name things a picture still shouldn't."""
    with open(ctx.args.catalog) as f:
        cat = json.load(f)
    pats = [p for p, _ in fixed_terms()]
    drop = {e["id"] for e in cat.get("entries", [])
            if any(p.search(f"{e.get('id', '')} {e.get('name', '')} {e.get('summary', '')}") for p in pats)}
    cat["entries"] = [dict(e, relationships=[r for r in e.get("relationships") or [] if r.get("target") not in drop])
                      for e in cat.get("entries", []) if e["id"] not in drop]
    cat["timeline"] = [t for t in cat.get("timeline", []) if not any(p.search(json.dumps(t)) for p in pats)]
    out = os.path.join(ctx.work, "catalog.json")
    with open(out, "w") as f:
        json.dump(cat, f)
    return out


shot("holodeck", "The holo deck",
     "The holo deck (SUPER+H) over the desktop: this machine's arc rings, the lab's relay map (a made-up lab) "
     "and the hologram of the workstation.")(_deck("holodeck", [5]))
shot("timeline", "The timeline",
     "The timeline deck (SUPER+T): the last 72 hours of this machine and the lab as a ribbon to scrub "
     "(demo history).")(_deck("timeline", [5]))
shot("driftmap", "The Drift map",
     "The Drift map (SUPER+M): the lore as a star chart, every light an entry and every lane a relationship, "
     "with the Wick at its edge.")(_deck("driftmap", [6], catalog=True))


@shot("menu", "The menu",
      "The desktop menu (SUPER+SPACE) with a search typed: one list of apps, commands, themes, toggles, "
      "VECTOR's verbs and the holograms.")
def _menu(ctx, m):
    def hook(n):
        rofi_config(n)
        p = subprocess.Popen([SYS_PY, "-c", RUN_CHECKOUT, os.path.join(ROOT, "desktop", "bin", "bromigos-menu"),
                              "--filter", "theme"], env=own_apps(ctx, n), stdout=subprocess.DEVNULL,
                             stderr=subprocess.DEVNULL, start_new_session=True)
        n.procs.append(p)
        if not wait_for(lambda: "rofi" in n.layers(), 15):
            raise RuntimeError("the menu didn't show")
        time.sleep(2.0)                          # its icons load after the first frame
    ctx.desktop("wick", scene("menu"), m, hook=hook)


# a desktop command run with this checkout's libraries ahead of the installed ones it puts
# first on its path itself (/usr/lib/bromigos/lib): they're imported here first
RUN_CHECKOUT = ("import runpy, sys; import bromigos_hypr; p = sys.argv[1]; sys.argv = sys.argv[1:]; "
                "runpy.run_path(p, run_name='__main__')")


def own_apps(ctx, n):
    """The nested desktop's environment with bromigOS's own app entries and icons only (as
    the packages install them: tools/launcher/check.py's stage), not this machine's apps."""
    sys.path.insert(0, os.path.join(ROOT, "tools", "launcher"))
    import check
    root = tempfile.mkdtemp(prefix="apps.", dir=ctx.work)
    data = check.stage(check.entries(), root)
    if os.path.isfile("/usr/share/icons/hicolor/index.theme"):
        shutil.copy("/usr/share/icons/hicolor/index.theme", os.path.join(data, "icons", "hicolor", "index.theme"))
    for d in ("glycin-loaders", "mime", "icons/Adwaita"):
        if os.path.isdir(os.path.join("/usr/share", d)):
            os.makedirs(os.path.dirname(os.path.join(data, d)), exist_ok=True)
            if not os.path.lexists(os.path.join(data, d)):
                os.symlink(os.path.join("/usr/share", d), os.path.join(data, d))
    for name, rel in check.PROGRAMS.items():     # what the entries' TryExec names (the nest's stubs stay)
        dst = os.path.join(n.stubs, name)
        if not os.path.lexists(dst):
            os.symlink(os.path.join(ROOT, rel), dst)
    return dict(n.env, XDG_DATA_DIRS=data, XDG_DATA_HOME=os.path.join(root, "nodata"),
                PYTHONPATH=os.pathsep.join([PV.SRC.pylib, os.path.join(ROOT, "desktop", "lib")]))


def rofi_config(n):
    """bromigOS's rofi settings in the nested desktop's home (the user's file imports the
    packaged one), pointed at this checkout."""
    d = os.path.join(n.box.dir, "config", "rofi")
    os.makedirs(d, exist_ok=True)
    # bromigos.rasi reads the theme's colours and emblem from ~/.local/state (not $XDG_STATE_HOME)
    state = os.path.join(n.box.dir, "state", "bromigos")
    emblem = os.path.join(state, "emblem")
    if not os.path.lexists(emblem):
        os.symlink(os.path.join(state, "theme", "current", "emblem"), emblem)
    home_state = os.path.join(n.box.home, ".local", "state", "bromigos")   # the panels' log is there already
    os.makedirs(home_state, exist_ok=True)
    for sub in ("theme", "emblem"):
        if not os.path.lexists(os.path.join(home_state, sub)):
            os.symlink(os.path.join(state, sub), os.path.join(home_state, sub))
    with open(os.path.join(ROOT, "desktop", "rofi", "config.rasi")) as f:
        text = f.read().replace("/usr/share/bromigos/default/rofi/bromigos.rasi",
                                os.path.join(ROOT, "desktop", "rofi", "bromigos.rasi"))
    with open(os.path.join(d, "config.rasi"), "w") as f:
        f.write(text.replace('delay:  10;', 'delay:  120;'))


@shot("settings", "Settings",
      "Settings (SUPER+,) on its Theme page: every theme as a picture of the desktop wearing it, over the Wick.")
def _settings(ctx, m):
    cache = ctx.previews()

    def hook(n):
        link = os.path.join(n.box.dir, "cache", "bromigos", "theme-previews")
        os.makedirs(os.path.dirname(link), exist_ok=True)
        if not os.path.lexists(link):
            os.symlink(cache, link)
        env = dict(n.env, PYTHONPATH=os.pathsep.join([os.path.join(ROOT, "desktop", "lib"), PV.SRC.pylib]),
                   PATH=f"{n.stubs}:{os.path.join(ROOT, 'desktop', 'bin')}:/usr/bin:/bin", GSK_RENDERER="cairo",
                   BROMIGOS_SHARE_DIR=PV.SRC.share)
        p = subprocess.Popen([SYS_PY, os.path.join(ROOT, "desktop", "settings", "bromigos-settings"), "--page", "theme"],
                             env=env, stdout=subprocess.DEVNULL, stderr=open(os.path.join(ctx.work, "settings.log"), "w"),
                             start_new_session=True)
        n.procs.append(p)
        ok = wait_for(lambda: any(c.get("class") == "org.bromigos.Settings" or "ettings" in (c.get("title") or "")
                                  for c in json.loads(n.ctl("clients", "-j") or "[]")), 20)
        if not ok:
            raise RuntimeError("Settings didn't open")
        time.sleep(4.0)                          # the previews load into the cards
    ctx.desktop("wick", scene("settings"), m, hook=hook)


@shot("theme-switcher", "The theme switcher",
      "The theme switcher (SUPER+CTRL+SHIFT+SPACE): each theme a live preview of the desktop wearing it; type "
      "to filter, Enter to wear one.")
def _switcher(ctx, m):
    cache = ctx.previews()
    tmp = os.path.join(ctx.work, "switcher")
    # behind it, the desktop it was opened on, full size (its card is the same picture, small)
    backdrop = os.path.join(ctx.work, "switcher-desk.png")
    ctx.desktop("wick", {}, backdrop)
    r = subprocess.run(["bash", os.path.join(ROOT, "tools", "theme-switcher", "render.sh"), tmp, "--size", f"{W}x{H}",
                        "--previews", cache, "--select", "mire", "--name", "shot", "--backdrop", backdrop],
                       capture_output=True, text=True)
    p = os.path.join(tmp, f"switcher-{W}x{H}-shot.png")
    if not os.path.exists(p):
        raise RuntimeError(f"the switcher's render failed: {r.stdout[-300:]} {r.stderr[-300:]}")
    shutil.copy(p, m)


@shot("lab-console", "bromigos lab",
      "`bromigos lab`, the homelab's console in a terminal: nodes, GPUs, services, models, GitOps apps, storage, "
      "alerts and jobs, one card each (drawn on the recorded lab of the tests, not a real one).")
def _lab(ctx, m):
    ctx.desktop("wick", scene("lab"), m)


@shot("boot-menu", "The boot menu",
      "The install medium's boot menu (GRUB, the Wick's theme) as GRUB itself draws it in a VM: try it live, "
      "install, safe graphics, memtest, boot from disk, the screen reader.")
def _boot(ctx, m):
    t = os.path.join(ctx.work, "grub-theme")
    o = os.path.join(ctx.work, "grub-shots")
    subprocess.run([sys.executable, os.path.join(ROOT, "settings", "grub", "build-grub-theme.py"), "--theme-dir",
                    os.path.join(ROOT, "themes", "wick"), "--medium", "--heading", "BROMIGOS // RELAY MEDIUM",
                    "--out", t], check=True, capture_output=True)
    subprocess.run([sys.executable, os.path.join(ROOT, "settings", "grub", "preview.py"), "--theme", t, "--out", o,
                    "--mode", f"{W}x{H}", "--menu", "medium", "--firmware", "uefi", "--at", "4"], check=True,
                   capture_output=True, timeout=600)
    shutil.copy(os.path.join(o, f"medium-uefi-{W}x{H}.png"), m)


@shot("loop-tidewell", "Tidewell, moving",
      "An animated loop: Tidewell's world moving behind the bar, the panels and a terminal (the Choir, the "
      "trawlers, the light).")
def _loop(ctx, m, theme="tidewell"):
    return loop(ctx, theme, m)


class SkipShot(Exception):
    pass


# ------------------------------------------------------------------ the loop
def loop(ctx, theme, master, size=(1920, 1080), fps=15):
    """The world's clip from the live layer (offscreen), then the nested desktop with each
    frame of it as its wallpaper in turn (swaybg, one after another), grim's picture of each:
    the bar and panels stay still (stopped) while the world moves. The clip's last
    second fades into its first, so it loops."""
    from PIL import Image
    secs = float(ctx.args.loop_seconds)
    box = ctx.box(theme)
    clip = os.path.join(ctx.work, f"{theme}-clip.mp4")
    world = os.path.join(box.dir, "state", "bromigos", "theme", "current")
    ctx.live(box, "world", clip, [secs + 1.0, fps], w=size[0], h=size[1],
             extra={"OFF_WORLD": world, "OFF_SCRIPT": PV._world_script(world), "OFF_WARM": "0.2", "OFF_T0": "4"})
    frames = os.path.join(ctx.work, "frames")
    os.makedirs(frames, exist_ok=True)
    L = secs + 1.0
    fc = (f"[0:v]trim=start=1:end={L},setpts=PTS-STARTPTS[A];[0:v]trim=start=0:end=1,setpts=PTS-STARTPTS[B];"
          f"[A][B]xfade=transition=fade:duration=1:offset={L - 2}[v]")
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", clip, "-filter_complex", fc, "-map", "[v]",
                    os.path.join(frames, "bg%04d.png")], check=True)
    bgs = sorted(f for f in os.listdir(frames) if f.startswith("bg"))
    shots = os.path.join(ctx.work, "loop-shots")
    os.makedirs(shots, exist_ok=True)

    def hook(n):
        import signal
        # Hyprland's animations off first. Its layers fade in and out (the "layers" fade), so a
        # wallpaper taken a moment after it mapped was still part-transparent over black: a
        # frame dimmer than its neighbours, as if the world's glow were gone.
        if "ok" not in n.ctl("eval", "hl.config({ animations = { enabled = false } })"):
            raise RuntimeError("the nested Hyprland didn't turn its animations off")
        # the bar and the panels held still: their pictures stay as they are (the terminal is
        # idle already; a stopped window would bring up Hyprland's not-responding dialog). Only
        # the nested desktop's own (found by its runtime directory), and let go after, whatever
        # happens
        held = [pid for name in ("waybar", "bromigos-widgets") for pid in _pids_in(n.rt, name)]
        for pid in held:
            os.kill(pid, signal.SIGSTOP)
        try:
            prev, last = n.wallpaper, None
            for i, f in enumerate(bgs):
                # the next frame's wallpaper up beside the last, then the last one gone: only
                # the new one is left when the picture is taken
                bg = os.path.join(frames, f)
                cur = n._start(["swaybg", "-o", "WAYLAND-1", "-m", "fill", "-i", bg], n.env, "swaybg-loop")
                if not wait_for(lambda: n.layers().count("wallpaper") >= 2, 10):
                    raise RuntimeError(f"frame {i}: the wallpaper didn't come up")
                prev.terminate()
                prev.wait(5)
                if not wait_for(lambda: n.layers().count("wallpaper") == 1, 10):
                    raise RuntimeError(f"frame {i}: the last wallpaper didn't go")
                # then the picture, taken again until it shows this frame whole: a grab can
                # still race the compositor's next frame
                shot = os.path.join(shots, f"f{i:04d}.png")
                for _ in range(20):
                    time.sleep(0.1)
                    n.grab(shot)
                    if shows_frame(shot, bg, last):
                        break
                else:
                    raise RuntimeError(f"frame {i}: the picture never showed its wallpaper whole")
                prev, last = cur, bg
            n.wallpaper = prev
        finally:
            for pid in held:
                try:
                    os.kill(pid, signal.SIGCONT)
                except OSError:
                    pass
    ctx.desktop(theme, scene("loop"), os.path.join(ctx.work, "loop-still.png"), hook=hook, size=size)
    Image.open(os.path.join(shots, "f0000.png")).convert("RGB").resize((W, H), Image.LANCZOS).save(master)
    return shots


def wallpaper_error(shot, bg):
    """How far the picture's wallpaper is from `bg`: the median over 32x32-pixel blocks of
    their mean difference (0-255). The bar, panels and terminal cover a minority of the
    blocks, so the median reads the wallpaper alone."""
    import numpy as np
    from PIL import Image
    a = np.asarray(Image.open(shot).convert("RGB"), np.float32)
    b = np.asarray(Image.open(bg).convert("RGB").resize((a.shape[1], a.shape[0])), np.float32)
    h, w = (a.shape[0] // 32) * 32, (a.shape[1] // 32) * 32
    d = np.abs(a[:h, :w] - b[:h, :w]).mean(axis=2)
    return float(np.median(d.reshape(h // 32, 32, w // 32, 32).mean(axis=(1, 3))))


def shows_frame(shot, bg, last=None, tol=2.0):
    """Whether the picture shows `bg` as the wallpaper, whole: within `tol` of it, and no
    nearer the last frame's (`last`) than this one's."""
    err = wallpaper_error(shot, bg)
    return err <= tol and (last is None or err <= wallpaper_error(shot, last))


def _pids_in(rt, name):
    """The processes named `name` started in the nested desktop (its runtime directory)."""
    out = []
    for pid in filter(str.isdigit, os.listdir("/proc")):
        try:
            with open(f"/proc/{pid}/comm") as f:
                comm = f.read().strip()
            if not (comm == name or comm.startswith(name[:15]) or name in comm):
                with open(f"/proc/{pid}/cmdline", "rb") as f:
                    if name.encode() not in f.read():
                        continue
            with open(f"/proc/{pid}/environ", "rb") as f:
                if f"XDG_RUNTIME_DIR={rt}".encode() in f.read().split(b"\0"):
                    out.append(int(pid))
        except OSError:
            continue
    return out


def encode_loop(shots_dir, out, width=1280, fps=15, quality=75):
    """The frames as an animated WebP, `width` wide, looping forever."""
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-framerate", str(fps), "-i", os.path.join(shots_dir, "f%04d.png"),
                    "-vf", f"scale={width}:-2:flags=lanczos", "-c:v", "libwebp_anim", "-lossless", "0",
                    "-quality", str(quality), "-compression_level", "6", "-loop", "0", "-preset", "picture", out],
                   check=True)


# ------------------------------------------------------------------ demo history (the timeline)
def demo_history(state):
    """72 hours of made-up minute history and a few events, in the files the timeline reads."""
    import numpy as np
    os.makedirs(state, exist_ok=True)
    fields = ["cpu", "gpu", "mem", "vram", "cpu_temp", "gpu_temp", "gpu_power", "rx", "tx",
              "lab_cpu", "lab_alerts", "lab_ready", "lab_nodes", "lab_pods", "svc_up", "svc_total", "wan_down"]
    n = 72 * 60
    end = time.time()
    t = end - (n - 1 - np.arange(n)) * 60.0
    hod = (t % 86400) / 3600.0
    day = np.clip(np.sin((hod - 7) / 24 * 2 * np.pi) * 1.2, 0, 1)
    rng = np.random.default_rng(7)
    v = np.full((n, len(fields)), np.nan, dtype=np.float32)
    ix = {f: i for i, f in enumerate(fields)}
    v[:, ix["cpu"]] = 6 + 30 * day + 10 * rng.random(n) + 40 * (rng.random(n) > 0.995)
    v[:, ix["gpu"]] = 3 + 25 * day * (rng.random(n) > 0.6)
    v[:, ix["mem"]] = 30 + 10 * day + 2 * rng.random(n)
    v[:, ix["vram"]] = 18 + 12 * day + 2 * rng.random(n)
    v[:, ix["cpu_temp"]] = 42 + 18 * day + 3 * rng.random(n)
    v[:, ix["gpu_temp"]] = 38 + 16 * day + 2 * rng.random(n)
    v[:, ix["rx"]] = 2e5 + 3e6 * day * rng.random(n) + 4e7 * (rng.random(n) > 0.997)
    v[:, ix["tx"]] = v[:, ix["rx"]] * 0.1
    v[:, ix["lab_cpu"]] = 12 + 9 * day + 3 * rng.random(n)
    v[:, ix["lab_ready"]] = 5
    v[:, ix["lab_nodes"]] = 5
    v[:, ix["lab_pods"]] = 84 + 3 * rng.random(n)
    v[:, ix["svc_up"]] = 12
    v[:, ix["svc_total"]] = 12
    v[:, ix["wan_down"]] = 1e6 + 2e7 * day * rng.random(n)
    v[:, ix["lab_alerts"]] = (rng.random(n) > 0.985).astype(np.float32) * 2
    np.savez_compressed(os.path.join(state, "history.npz"), t=t, v=v, fields=np.array(fields))
    evs = [(2.1, "notify", "Build finished"), (5.5, "start", "Session started"), (9.0, "notify", "Backup complete"),
           (14.2, "lock", ""), (14.9, "unlock", ""), (22.0, "critical", "Disk 85% full on /data"),
           (30.5, "notify", "Update available"), (41.0, "codec", "VECTOR: all relays answering"),
           (55.0, "notify", "Download complete")]
    with open(os.path.join(state, "events.jsonl"), "w") as f:
        for h, k, x in evs:
            f.write(json.dumps({"t": end - h * 3600, "k": k, "x": x}) + "\n")


# ------------------------------------------------------------------ the children (system Python, sealed)
TRANSCRIPT = [
    ("user", "how's the lab doing?"),
    ("tool", "lab status · 5 of 5 nodes, 12 of 12 services"),
    ("reply", "All five nodes are up and all twelve services are answering. One alert: Argo has an app out of "
              "sync, the media stack, since about noon. Nothing's on fire. I can sync it, or leave it for the "
              "morning."),
]


def child_vector(out, state):
    """VECTOR's console (his offscreen renderer, vector tools/offscreen.py), a short demo
    conversation, saved with its alpha (premultiplied, as GL draws it)."""
    vec = os.environ["PV_VECTOR"]
    sys.path.insert(0, vec)
    import importlib.util
    spec = importlib.util.spec_from_file_location("vector_offscreen", os.path.join(vec, "tools", "offscreen.py"))
    off = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(off)
    import numpy as np
    from OpenGL import GL
    from PIL import Image
    w, h = off.W, off.H
    off.egl()
    from holo.live import Live
    from holo.vector.scene import VectorScene
    fbo = off.target()
    p = VectorScene(Live())
    p.set_state(state)
    time.sleep(float(os.environ.get("OFF_WARM", 3)))
    for kind, text in TRANSCRIPT:
        if kind == "user":
            p.add_user(text)
        elif kind == "tool":
            p.add_tool(text)
        else:
            p.feed(text)
            p.end_reply()
    for msg in p.msgs:
        msg.shown = len(msg.text)
    p.panel = p.panel_to = 1.0
    p.fade = 1.0
    for _ in range(90):
        p.advance(1 / 30)
    p.set_state(state)
    p.fade = 1.0
    p.render(fbo, w, h)
    p.render(fbo, w, h)
    GL.glBindFramebuffer(GL.GL_FRAMEBUFFER, fbo)
    px = GL.glReadPixels(0, 0, w, h, GL.GL_RGBA, GL.GL_UNSIGNED_BYTE)
    a = np.frombuffer(px, np.uint8).reshape(h, w, 4)[::-1]
    Image.fromarray(a.copy(), "RGBA").save(out)


# ------------------------------------------------------------------ the check
FIXED = [
    (r"\bbrodec\b", "a separate product"), (r"dotfiles", "a private config"),
    (r"\b(?:\d{1,3}\.){3}\d{1,3}\b", "an IP address"), (r"\bsecret/(?:data/)?", "a Vault path"),
    (r"\b[\w-]+\.(?:lan|local|internal|home|corp|lab)\b", "a LAN host name"), (r"\bk8s-[\w-]+", "a cluster node name"),
    (r"/home/(?!u\b)\w+", "a home path"), (r"\btrading\b|\bpaper fills\b", "an internal tool"),
    (r"k8s_rustfs|\brustfs\b", "the lab's object store"),
]
# The internal tools' names and the lab's own are never spelled here: tools/privacy/private_words.py
# matches the first by salted hashes, and reads the lab's name from the private overlay when this
# machine has one.
sys.path.insert(0, os.path.join(ROOT, "tools", "privacy"))
import private_words  # noqa: E402


def fixed_terms():
    """[(regex-like, why)]: FIXED, the hashed internal names, and the lab's name (with an overlay)."""
    terms = [(re.compile(p, re.I), why) for p, why in FIXED]
    terms += [(private_words.HashedWords(why), why) for why in sorted(set(private_words.HASHED.values()))]
    lab = private_words.lab_name_pattern()
    if lab:
        terms.append((re.compile(lab, re.I), "the lab's name"))
    return terms


def private_terms():
    """[(regex, why)]: the fixed words, this machine's host and user names, and the private
    overlay's node and host names when it has one (held here only, never printed)."""
    terms = fixed_terms()

    def term(t, why):
        terms.append((re.compile(r"(?<![\w-])" + re.escape(t) + r"(?![\w-])", re.I), why))
    try:
        with open("/proc/sys/kernel/hostname") as f:
            hn = f.read().strip()
        if hn and hn not in ("localhost", "archlinux"):
            term(hn, "this machine's host name")
    except OSError:
        pass
    user = os.environ.get("USER") or ""
    if len(user) > 2:
        term(user, "this machine's user name")
    path = os.environ.get("BROMIGOS_PRIVATE_CONFIG") or os.path.expanduser("~/.config/bromigos/private/config.json")
    try:
        with open(path) as f:
            data = json.load(f)
    except (OSError, ValueError):
        return terms, False
    from urllib.parse import urlsplit
    con = (data.get("homelab") or {}).get("constellation") or {}
    nodes = [con.get("hub")] + list(con.get("ai") or []) + [p.get("node") for p in con.get("positions") or []
                                                             if isinstance(p, dict)]
    for n in {n.strip() for n in nodes if isinstance(n, str) and n.strip()}:
        term(n, "a lab node name")
    hosts = set()

    def walk(o):
        if isinstance(o, dict):
            for k, v in o.items():
                if k != "label":
                    walk(v)
        elif isinstance(o, list):
            for v in o:
                walk(v)
        elif isinstance(o, str):
            h = urlsplit(o).hostname if "://" in o else o.strip()
            if h and re.fullmatch(r"[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+", h) and not re.fullmatch(r"[\d.]+", h):
                hosts.add(h.lower())
    walk(data.get("endpoints"))
    walk(data.get("lan"))
    for h in hosts:
        term(h, "a LAN host name")
    # the owner's name and its forms (operator.name, full_name, aliases): each word of them
    op = data.get("operator") if isinstance(data.get("operator"), dict) else {}
    words = set()
    for k in ("name", "full_name", "aliases"):
        v = op.get(k)
        for x in (v if isinstance(v, list) else [v]):
            if isinstance(x, str):
                words.update(w for w in re.findall(r"[A-Za-z][A-Za-z0-9]{2,}", x))
    for w in words:
        term(w, "the owner's name")
    return terms, True


def ocr_ready():
    """Can tesseract read English here? (tesseract-data-eng, or TESSDATA_PREFIX pointing at an
    eng.traineddata.) A check that can't read would pass everything, so it refuses."""
    try:
        r = subprocess.run(["tesseract", "--list-langs"], capture_output=True, text=True, timeout=20)
    except OSError:
        return "no tesseract"
    if "eng" not in r.stdout.split():
        return "tesseract has no English data (install tesseract-data-eng, or set TESSDATA_PREFIX)"
    return None


def ocr(png):
    """tesseract over the picture as it is and 2x in grey with the contrast stretched."""
    out = ""
    with tempfile.TemporaryDirectory() as d:
        big = os.path.join(d, "big.png")
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", png, "-vf",
                        "scale=iw*2:ih*2:flags=lanczos,format=gray,eq=contrast=1.6:brightness=0.05", big], check=True)
        env = dict(os.environ, OMP_THREAD_LIMIT="2")
        procs = [subprocess.Popen(["tesseract", src, "-", "-l", "eng", "--psm", "11"], stdout=subprocess.PIPE,
                                  stderr=subprocess.PIPE, text=True, env=env) for src in (png, big)]
        for p in procs:
            so, se = p.communicate()
            if p.returncode != 0:
                raise RuntimeError(f"tesseract failed: {se.strip()[-200:]}")
            out += so + "\n"
    return out


def check(paths, terms):
    """{why: count} over every picture's OCR text (never the words themselves)."""
    import concurrent.futures
    hits = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as ex:
        for text in ex.map(ocr, paths):
            for pat, why in terms:
                for _ in pat.finditer(text):
                    hits[why] = hits.get(why, 0) + 1
    return hits


# ------------------------------------------------------------------ main
def encode(master, out_dir, id):
    """The master as WebP at full width and at the README's width."""
    from PIL import Image
    im = Image.open(master).convert("RGB")
    full = os.path.join(out_dir, f"{id}.webp")
    im.save(full, "WEBP", quality=90, method=6)
    small = os.path.join(out_dir, f"{id}-{README_W}.webp")
    im.resize((README_W, round(im.height * README_W / im.width)), Image.LANCZOS).save(small, "WEBP", quality=86,
                                                                                         method=6)
    return [full, small]


def human(n):
    for u in ("B", "KB", "MB"):
        if n < 1024 or u == "MB":
            return f"{n:.0f} {u}" if u == "B" else f"{n:.1f} {u}"
        n /= 1024


def main():
    if len(sys.argv) > 2 and sys.argv[1] == "--child":
        if sys.argv[2] == "vector":
            return child_vector(sys.argv[3], sys.argv[4] if len(sys.argv) > 4 else "idle")
        sys.exit(f"unknown child {sys.argv[2]}")
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("out", nargs="?")
    ap.add_argument("--only", default="")
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--catalog", help="a public lore catalog for the Drift map")
    ap.add_argument("--previews", help="a cache folder of theme previews to reuse")
    ap.add_argument("--loop-seconds", default="8")
    ap.add_argument("--no-check", action="store_true")
    a = ap.parse_args()
    if a.list:
        for s in SHOTS:
            print(f"{s['id']:16} {s['title']}")
        return 0
    if not a.out:
        ap.error("OUTDIR")
    out = os.path.abspath(a.out)
    os.makedirs(out, exist_ok=True)
    if a.catalog:
        a.catalog = os.path.abspath(a.catalog)
    if a.previews:
        a.previews = os.path.abspath(a.previews)
    only = {x for x in a.only.split(",") if x}
    unknown = only - {s["id"] for s in SHOTS}
    if unknown:
        sys.exit(f"render: no such picture: {', '.join(sorted(unknown))} (--list)")
    if not a.no_check and ocr_ready():
        sys.exit(f"render: the check can't read pictures: {ocr_ready()} (--no-check to skip it)")
    terms, overlay = (None, False) if a.no_check else private_terms()
    mpath = os.path.join(out, "manifest.json")
    try:
        with open(mpath) as f:
            manifest = {e["id"]: e for e in json.load(f).get("pictures", [])}
    except (OSError, ValueError):
        manifest = {}
    import concurrent.futures
    ctx = Ctx(out, a)
    fails = 0
    pool = concurrent.futures.ThreadPoolExecutor(max_workers=2)
    pending = {}
    try:
        for s in SHOTS:
            if only and s["id"] not in only:
                continue
            t0 = time.time()
            m = os.path.join(ctx.masters, f"{s['id']}.png")
            print(f"{s['id']:16} drawing…", flush=True)
            try:
                res = s["fn"](ctx, m)
            except SkipShot as e:
                print(f"{s['id']:16} skipped: {e}", flush=True)
                continue
            except Exception as e:
                fails += 1
                print(f"{s['id']:16} FAILED: {type(e).__name__}: {e}", flush=True)
                continue
            files = [m]
            checked = [m]
            if s["id"].startswith("loop-"):
                anim = os.path.join(out, f"{s['id']}.webp")
                encode_loop(res, anim)
                files = [anim, m]
                frames = sorted(os.listdir(res))
                checked += [os.path.join(res, f) for f in frames[::15]]
            else:
                files = encode(m, out, s["id"]) + [m]
            if terms is not None:                # read back beside the next picture's drawing (the work
                pending[s["id"]] = pool.submit(check, checked, terms)    # folder stays until they're read)
            from PIL import Image
            manifest[s["id"]] = {
                "id": s["id"], "title": s["title"], "what": s["what"], "check": "not checked",
                "overlay_checked": overlay,
                "files": [{"path": os.path.relpath(f, out), "bytes": os.path.getsize(f),
                           "size": list(Image.open(f).size)} for f in files],
                "rendered_at": time.strftime("%Y-%m-%d %H:%M %Z"), "seconds": round(time.time() - t0, 1)}
            print(f"{s['id']:16} drawn in {round(time.time() - t0)} s", flush=True)
        for id, fut in pending.items():
            hits = fut.result()
            verdict = ("BLOCKED: " + "; ".join(f"{k} ({v})" for k, v in sorted(hits.items()))) if hits else "ok"
            manifest[id]["check"] = verdict
            fails += bool(hits)
            print(f"{id:16} check: {verdict}", flush=True)
    finally:
        pool.shutdown(wait=True)
        ctx.close()
    order = {s["id"]: i for i, s in enumerate(SHOTS)}
    pics = sorted(manifest.values(), key=lambda e: order.get(e["id"], 99))
    with open(mpath, "w") as f:
        json.dump({"pictures": pics}, f, indent=1)
    with open(os.path.join(out, "manifest.md"), "w") as f:
        try:
            rev = subprocess.run(["git", "-C", ROOT, "log", "-1", "--format=%h %cd", "--date=format-local:%Y-%m-%d"],
                                 capture_output=True, text=True).stdout.strip()
        except OSError:
            rev = ""
        f.write("# bromigOS pictures\n\n"
                f"Drawn offscreen by `tools/screenshots/render.py` (bromigOS {rev or 'checkout'}), "
                f"{time.strftime('%Y-%m-%d %H:%M %Z')}, with demo readings: a made-up machine (\"drift\"), a made-up "
                "lab, demo weather, projects and notes. Nothing in them is a real machine, network or lab.\n\n"
                f"`masters/ID.png` is the lossless master; `ID.webp` the master as WebP; `ID-{README_W}.webp` the "
                "README's size; `loop-*.webp` an animated WebP (loops forever). The check reads every picture "
                "back (tesseract) against the words a picture must never show.\n\n")
        for e in pics:
            f.write(f"## {e['title']} (`{e['id']}`)\n\n{e['what']}\n\n")
            for fl in e["files"]:
                f.write(f"- `{fl['path']}`: {fl['size'][0]}x{fl['size'][1]}, {human(fl['bytes'])}\n")
            f.write(f"- check: {e['check']}\n\n")
    print(f"manifest: {os.path.join(out, 'manifest.md')}")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
