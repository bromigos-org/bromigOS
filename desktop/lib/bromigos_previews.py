"""Theme previews (package bromigos-desktop, /usr/lib/bromigos/lib): each theme as a
miniature screenshot of bromigOS wearing it, for the theme switcher.

A preview is the real desktop, drawn where nobody sees it (Nested): a Hyprland running
bromigOS's own config nested in a headless kwin, with the real waybar, the real panels
(demo readings) and kitty, Hyprland's borders and shadow, and the live layer's own frame
(its offscreen renderer, EGL: a world's scene with its creatures, or the Wick's den) as
the background, captured by grim inside the nested session. A kwin window rule keeps the
nested Hyprland full screen (KWIN_RULES), and a picture of any other size than the one
asked for is refused (WrongSize), never cached. Without kwin, the same pieces are drawn
one by one and composed:

  the background  the live layer's offscreen frame
  the panels      the desktop panels' own drawing (bromigos-widgets), SYSTEM and NETWORK
  the terminal    kitty, with the theme's kitty.conf, in a headless compositor (weston)
  the bar         waybar's own stylesheets (bromigOS's style.css and the theme's
                  waybar.css with its icons) on waybar's widget tree, drawn by GTK 3
  the borders     Hyprland's border, shadow and blur, from the theme's hyprland.lua

Everything runs in a throwaway home: `bromigos theme set NAME --no-reload` renders the
theme there (nothing is reloaded, no hook runs), every child gets that home and its own
runtime directory, no session variables (no WAYLAND_DISPLAY, DISPLAY, D-Bus or Hyprland
of the desktop's), and demo readings wherever a picture could show the machine (the
panels' readings, the bar's values, the world's agents and weather). Nothing reads,
signals or draws on the running desktop.

Previews are cached in ~/.cache/bromigos/theme-previews/NAME-STAMP.jpg (with a .json
beside it), where STAMP is a hash of everything the picture depends on: the theme's
files (first-party, an extension's and the user's overlay), the templates, the bar's
style, the live layer's code and this renderer's version. A theme that changes gets a new stamp, so a new
preview; the old one is kept until the new one is drawn.

    stale(themes())                 the installed themes whose preview is missing or old
    render(names, force=False)      draw them (one run at a time: a lock in the cache)
    current(name)                   (path, fresh) of the newest preview of a theme

`bromigos theme previews` (desktop/bin/bromigos-theme-previews) is the command.
"""
import fcntl
import glob
import hashlib
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import time

RENDERER = "5"                  # bump when a preview's look changes: every cached one is redrawn
                                # (4: kwin 6.8 had shrunk the nested desktop to 1280x720; see KWIN_RULES)
                                # (5: a nested Hyprland that took a login session drew nothing; see NO_SEAT)
DESK_W, DESK_H = 1920, 1080     # the desktop a preview shows (logical px)
SAVE_W, SAVE_H = 1280, 720      # what is kept
TERM_W, TERM_H = 780, 470       # the terminal window's inside


def set_size(w, h):
    """Draw the desktop at w x h (`--size`; the switcher's are 1920x1080): the terminal
    scales with it, the panels keep their layout."""
    global DESK_W, DESK_H, TERM_W, TERM_H
    DESK_W, DESK_H = int(w), int(h)
    TERM_W, TERM_H = round(780 * DESK_W / 1920), round(470 * DESK_H / 1080)
DEMO_HOUR = 21.4                # the clock in every preview (a world at night)
SYS_PY = "/usr/bin/python3" if os.path.exists("/usr/bin/python3") else sys.executable

HOME = os.path.expanduser("~")
CACHE = os.path.join(os.environ.get("XDG_CACHE_HOME") or os.path.join(HOME, ".cache"), "bromigos", "theme-previews")
CONFIG = os.environ.get("XDG_CONFIG_HOME") or os.path.join(HOME, ".config")
DATA = os.environ.get("XDG_DATA_HOME") or os.path.join(HOME, ".local", "share")
HERE = os.path.dirname(os.path.realpath(__file__))


# ------------------------------------------------------------------ where the pieces are
class Src:
    """bromigOS's pieces: a checkout (BROMIGOS_SRC, or the one this file is in) or the
    installed packages."""

    def __init__(self):
        root = os.environ.get("BROMIGOS_SRC")
        if not root:
            up = os.path.normpath(os.path.join(HERE, "..", ".."))
            if os.path.isfile(os.path.join(up, "live", "tools", "offscreen.py")) and os.path.isdir(
                    os.path.join(up, "themes")):
                root = up
        self.root = root
        if root:
            self.share = root                         # themes/ and theme/templates/ (as BROMIGOS_SHARE_DIR)
            self.live = os.path.join(root, "live")
            self.widgets = os.path.join(root, "widgets")
            self.pylib = os.path.join(root, "lib")
            self.waybar = os.path.join(root, "desktop", "waybar")
            self.wallpaper = os.path.join(root, "desktop", "wallpaper")
            self.gtk = os.path.join(root, "settings", "gtk")
            built = os.path.join(root, "core", "target", "debug", "bromigos")
            self.bromigos = os.environ.get("BROMIGOS") or (built if os.access(built, os.X_OK) else "bromigos")
        else:
            self.share = os.environ.get("BROMIGOS_SHARE_DIR") or "/usr/share/bromigos"
            self.live = "/usr/lib/bromigos/live"
            self.widgets = "/usr/lib/bromigos/widgets"
            self.pylib = "/usr/lib/bromigos/lib"
            self.waybar = os.path.join(self.share, "default", "waybar")
            self.wallpaper = os.path.join(self.share, "wallpaper")
            self.gtk = "/usr/lib/bromigos/gtk"
            self.bromigos = os.environ.get("BROMIGOS") or "bromigos"
        self.den = os.path.join(self.wallpaper, "bromigos-den-empty-2560x1440.jpg")

    def bromigos_env(self):
        """The real environment for `bromigos` itself (theme list): only the share dir."""
        env = dict(os.environ)
        if self.root:
            env["BROMIGOS_SHARE_DIR"] = self.share
        return env


SRC = Src()


# ------------------------------------------------------------------ themes and their stamps
def themes():
    """`bromigos theme list --json`: {"themes": [...], "current": name}."""
    try:
        r = subprocess.run([SRC.bromigos, "theme", "list", "--json"], capture_output=True, text=True, timeout=15,
                           env=SRC.bromigos_env())
        d = json.loads(r.stdout)
        return d if isinstance(d, dict) else {"themes": [], "current": None}
    except (OSError, subprocess.SubprocessError, ValueError):
        return {"themes": [], "current": None}


def layers(name):
    """The directories a theme is made of, in overlay order: first-party, an extension's,
    the user's."""
    out = []
    for d in (os.path.join(SRC.share, "themes", name), os.path.join(DATA, "bromigos", "ext", "active", "themes", name),
              os.path.join(CONFIG, "bromigos", "themes", name)):
        if os.path.isdir(d):
            out.append(os.path.realpath(d))
    return out


def _skip(rel):
    parts = rel.split(os.sep)
    return any(p.startswith(".") for p in parts) or parts[-1].lower().startswith("readme") or parts[0] == "art"


def _hash_tree(h, d, tag):
    """Every file under d (not dot-files, READMEs or art/ sources): its path and its content."""
    if not os.path.isdir(d):
        return
    files = []
    for root, dirs, names in os.walk(d, followlinks=True):
        dirs[:] = sorted(x for x in dirs if not x.startswith("."))
        for n in names:
            p = os.path.join(root, n)
            rel = os.path.relpath(p, d)
            if not _skip(rel):
                files.append((rel, p))
    for rel, p in sorted(files):
        h.update(f"{tag}:{rel}\0".encode())
        try:
            with open(p, "rb") as f:
                for chunk in iter(lambda: f.read(1 << 20), b""):
                    h.update(chunk)
        except OSError:
            h.update(b"?")


_LIVE_HASH = []


def live_code_hash():
    """The live layer's drawing code (its Python, shaders and offscreen renderer) and the
    shared libraries its colours come from: a new live layer (a recoloured den, say) makes
    every preview stale. Hashed once per run."""
    if not _LIVE_HASH:
        h = hashlib.sha256()
        files = sorted(glob.glob(os.path.join(SRC.live, "live", "*.py")) +
                       glob.glob(os.path.join(SRC.live, "shaders", "*")) +
                       [os.path.join(SRC.live, "tools", "offscreen.py")] +
                       [os.path.join(SRC.pylib, f) for f in ("bromigos_retint.py", "bromigos_theme.py")])
        for p in files:
            try:
                with open(p, "rb") as f:
                    h.update(os.path.basename(p).encode() + b"\0" + f.read())
            except OSError:
                h.update(os.path.basename(p).encode() + b"\0?")
        _LIVE_HASH.append(h.hexdigest())
    return _LIVE_HASH[0]


def stamp(name, dirs=None):
    """A hash of everything a theme's preview depends on (12 hex digits)."""
    h = hashlib.sha256(f"renderer {RENDERER} {DESK_W}x{DESK_H}\0".encode())
    h.update(f"live {live_code_hash()}\0".encode())
    for i, d in enumerate(dirs if dirs is not None else layers(name)):
        _hash_tree(h, d, f"layer{i}")
    _hash_tree(h, os.path.join(SRC.share, "theme", "templates"), "templates")
    _hash_tree(h, os.path.join(CONFIG, "bromigos", "theme", "templates"), "user-templates")
    _hash_tree(h, os.path.join(CONFIG, "bromigos", "theme", "icons"), "user-icons")
    for f in ("style.css", "config.jsonc"):
        p = os.path.join(SRC.waybar, f)
        if os.path.exists(p):
            with open(p, "rb") as fh:
                h.update(f"bar:{f}\0".encode() + fh.read())
    return h.hexdigest()[:12]


def path_for(name, st):
    return os.path.join(CACHE, f"{name}-{st}.jpg")


def cached(name):
    """Every cached preview of a theme, newest first."""
    out = [p for p in glob.glob(os.path.join(CACHE, f"{glob.escape(name)}-*.jpg"))
           if re.fullmatch(re.escape(name) + r"-[0-9a-f]{12}\.jpg", os.path.basename(p))]
    return sorted(out, key=lambda p: os.path.getmtime(p), reverse=True)


def current(name, st=None):
    """(path, fresh): the preview for the theme as it is now (fresh), else the newest one
    drawn of an older version, else (None, False)."""
    st = st or stamp(name)
    p = path_for(name, st)
    if os.path.exists(p):
        return p, True
    old = cached(name)
    return (old[0], False) if old else (None, False)


def failure(name, st):
    """Why the last attempt at this version's preview failed, or None."""
    try:
        with open(os.path.join(CACHE, f"{name}-{st}.failed")) as f:
            return json.load(f).get("error") or "failed"
    except (OSError, ValueError):
        return None


def clean_legacy():
    """The old switcher's cards (NAME-STAMP.png: a painting over a palette strip, some with
    a user's own den art in them) and its downloads: never shown again, so removed."""
    try:
        names = os.listdir(CACHE)
    except OSError:
        return []
    gone = []
    for n in names:
        if re.fullmatch(r"[A-Za-z0-9._-]+-[0-9a-f]{12}\.png|no-preview\.png|catalog-.+-[0-9a-f]{10}\.png", n):
            try:
                os.unlink(os.path.join(CACHE, n))
                gone.append(n)
            except OSError:
                pass
    return gone


def stale(names=None):
    """The installed themes (or `names`) whose preview is missing or out of date."""
    d = themes()
    out = []
    for t in d.get("themes", []):
        if t.get("error") or (names and t["name"] not in names):
            continue
        if not os.path.exists(path_for(t["name"], stamp(t["name"]))):
            out.append(t["name"])
    return out


# ------------------------------------------------------------------ the throwaway home
def _short_tmp(prefix):
    """A directory under /tmp with a short path: a Wayland socket's path must fit 108 bytes."""
    d = tempfile.mkdtemp(prefix=prefix, dir="/tmp")
    os.chmod(d, 0o700)
    return d


class Box:
    """One theme's sealed environment: its own home, XDG directories and runtime directory,
    the theme rendered into it, and nothing of the user's session."""

    def __init__(self, base, name, extra_dirs=None):
        self.name = name
        self.dir = os.path.join(base, re.sub(r"[^A-Za-z0-9_.-]", "_", name))
        for sub in ("home", "config", "state", "cache", "data", "runtime", "empty", "plugins", "share/live", "bin",
                    "out", "shots"):
            os.makedirs(os.path.join(self.dir, sub), exist_ok=True)
        os.chmod(os.path.join(self.dir, "runtime"), 0o700)
        self.home = os.path.join(self.dir, "home")
        self.current = os.path.join(self.dir, "state", "bromigos", "theme", "current")
        self.out = os.path.join(self.dir, "out")
        # the theme's own layers outside the share dir: linked in, read-only data
        ext = extra_dirs if extra_dirs is not None else [
            d for d in layers(name) if not d.startswith(os.path.realpath(os.path.join(SRC.share, "themes")) + os.sep)]
        for d in ext:
            if os.path.realpath(d).startswith(os.path.realpath(os.path.join(CONFIG, "bromigos", "themes"))):
                link = os.path.join(self.dir, "config", "bromigos", "themes", name)
            else:
                link = os.path.join(self.dir, "data", "bromigos", "ext", "active", "themes", name)
            os.makedirs(os.path.dirname(link), exist_ok=True)
            if not os.path.lexists(link):
                os.symlink(d, link)
        for sub in ("templates", "icons"):          # the user's own templates and bar icons
            d = os.path.join(CONFIG, "bromigos", "theme", sub)
            if extra_dirs is None and os.path.isdir(d):
                link = os.path.join(self.dir, "config", "bromigos", "theme", sub)
                os.makedirs(os.path.dirname(link), exist_ok=True)
                os.symlink(os.path.realpath(d), link)
        bro = shutil.which(SRC.bromigos) or SRC.bromigos
        if os.path.isabs(bro) and os.path.exists(bro):
            os.symlink(bro, os.path.join(self.dir, "bin", "bromigos"))

    def env(self, **extra):
        d = self.dir
        env = {
            "HOME": self.home, "USER": "bromigos", "LOGNAME": "bromigos",
            "PATH": os.path.join(d, "bin") + ":/usr/bin:/bin", "LANG": "C.UTF-8", "TERM": "xterm-256color",
            "XDG_CONFIG_HOME": os.path.join(d, "config"), "XDG_STATE_HOME": os.path.join(d, "state"),
            "XDG_CACHE_HOME": os.path.join(d, "cache"), "XDG_DATA_HOME": os.path.join(d, "data"),
            "XDG_RUNTIME_DIR": os.path.join(d, "runtime"), "BROMIGOS_SHARE_DIR": SRC.share,
            "BROMIGOS_PYLIB": SRC.pylib, "BROMIGOS_HOMELAB": os.path.join(d, "empty"),
            "BROMIGOS_VECTOR": os.path.join(d, "empty"), "BROMIGOS_LIVE_PLUGINS": os.path.join(d, "plugins"),
            "BROMIGOS_WIDGET_PLUGINS": os.path.join(d, "plugins"),
            "BROMIGOS_PRIVATE_CONFIG": os.path.join(d, "no-private.json"),
            "BROMIGOS_HOLO_ROOT": os.path.join(d, "empty"), "BROMIGOS_NOTES": os.path.join(d, "empty", "notes.md"),
            "PYTHONDONTWRITEBYTECODE": "1", "NO_AT_BRIDGE": "1", "GSETTINGS_BACKEND": "memory",
        }
        for k in ("__GLX_VENDOR_LIBRARY_NAME", "__EGL_VENDOR_LIBRARY_FILENAMES", "CUDA_VISIBLE_DEVICES", "TZ",
                  "BROMIGOS_WIDGETS_DEMO_LAB_SIZE"):
            if k in os.environ:
                env[k] = os.environ[k]
        env.update({k: str(v) for k, v in extra.items()})
        return env

    def run(self, argv, timeout, log, **extra):
        with open(log, "a") as lf:
            lf.write(f"$ {' '.join(argv)}\n")
            lf.flush()
            return subprocess.run(argv, env=self.env(**extra), stdout=lf, stderr=subprocess.STDOUT, cwd=self.dir,
                                  timeout=timeout, stdin=subprocess.DEVNULL)

    def set_theme(self, log):
        r = self.run([SRC.bromigos, "theme", "set", self.name, "--no-reload"], 60, log)
        if r.returncode != 0 or not os.path.exists(os.path.join(self.current, "palette.json")):
            raise RuntimeError(f"bromigos theme set {self.name} failed (see {log})")
        with open(os.path.join(self.current, "palette.json")) as f:
            return json.load(f)


class Compositor:
    """A headless weston of our own (kiosk shell: the one window fills the output), for
    the terminal and the bar's GTK. Its socket is in a runtime directory of its own;
    nothing else connects to it."""

    def __init__(self, w, h, log):
        self.rt = _short_tmp("bpv.")
        self.socket = os.path.join(self.rt, "wl-0")
        self.proc = None
        if not shutil.which("weston"):
            raise RuntimeError("no weston (the headless compositor the terminal and the bar are drawn in)")
        env = {"HOME": self.rt, "XDG_RUNTIME_DIR": self.rt, "PATH": "/usr/bin:/bin", "LANG": "C.UTF-8"}
        self.log = open(log, "a")
        # --debug: weston's screenshooter answers its clients (only ours reach this socket)
        self.proc = subprocess.Popen(
            ["weston", "--backend=headless", "--renderer=pixman", "--shell=kiosk", f"--width={w}", f"--height={h}",
             "--socket=wl-0", "--no-config", "--idle-time=0", "--debug"],
            env=env, stdout=self.log, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL, start_new_session=True)
        for _ in range(100):
            if os.path.exists(self.socket):
                break
            if self.proc.poll() is not None:
                break
            time.sleep(0.05)
        if not os.path.exists(self.socket):
            self.close()
            raise RuntimeError("weston didn't start")

    def close(self):
        if self.proc and self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(5)
            except subprocess.TimeoutExpired:
                self.proc.kill()
        self.proc = None
        try:
            self.log.close()
        except Exception:
            pass
        shutil.rmtree(self.rt, ignore_errors=True)

    def screenshot(self, cwd, env):
        """The output as a PNG (weston-screenshooter, into cwd), or None."""
        before = set(os.listdir(cwd))
        r = subprocess.run(["weston-screenshooter"], cwd=cwd, env=env, capture_output=True, timeout=20)
        new = sorted(set(os.listdir(cwd)) - before)
        pngs = [os.path.join(cwd, f) for f in new if f.endswith(".png")]
        return pngs[0] if r.returncode == 0 and pngs else None


# ------------------------------------------------------------------ the pieces
def _world_script(cur):
    """Signals held from the start, so the scene is lit and populated at once: night, the
    user working, a few agents at work (each world's own creatures for them), calm weather."""
    agents = ",".join(f"{c}:working" for c in "abcde")
    return (f"0 w set hour {DEMO_HOUR}; 0 w set user working; 0 w set vector idle; 0 w set cpu 0.12; "
            f"0 w set net 0.55; 0 w set health 0; 0 w set lab_green 1; 0 w set lab 1; 0 w set agents {agents}")


def live_frame(box, log, out):
    """The live layer's frame for the theme: its world, else the den."""
    world = os.path.exists(os.path.join(box.current, "live", "world.toml"))
    cfg = os.path.join(box.dir, "live-config.toml")
    with open(cfg, "w") as f:
        f.write("\n".join([
            "[background]", f'underlay = "{SRC.den}"', f'underlay_fallback = "{SRC.den}"',
            "[cluster]", 'url = ""', 'token_file = ""', "[fills]", 'url = ""', 'console = ""', 'endpoint = ""',
            "[sounds]", "enabled = false", "[world]", "ambient_sounds = false", 'dir = ""',
            "[codec]", 'tts_url = ""']) + "\n")
    shutil.copy(os.path.join(SRC.live, "config.toml") if os.path.exists(os.path.join(SRC.live, "config.toml"))
                else os.path.join(SRC.share, "live", "config.toml"), os.path.join(box.dir, "share", "live", "config.toml"))
    # the rest of the share dir as it is (themes/ with the Wick's emblem kit, which the den's
    # monitor needs when the theme has no kit of its own: without it the frame failed and the
    # preview fell back to the still, green den), only live/ is the box's own
    for entry in os.listdir(SRC.share) if os.path.isdir(SRC.share) else []:
        link = os.path.join(box.dir, "share", entry)
        if entry != "live" and not os.path.lexists(link):
            os.symlink(os.path.join(SRC.share, entry), link)
    times = ["1", "2", "3", "4", "5", "6", "7", "8.5"] if world else ["1", "3", "5", "6"]
    r = box.run([SYS_PY, __file__, "--child", "live", "world" if world else "bg", out] + times, 240, log,
                BROMIGOS_LIVE_CONFIG=cfg, BROMIGOS_SHARE_DIR=os.path.join(box.dir, "share"),
                PYOPENGL_PLATFORM="egl", EGL_PLATFORM="surfaceless", OFF_W=DESK_W, OFF_H=DESK_H, OFF_WARM="0.2",
                OFF_WORLD=box.current if world else "", OFF_SCRIPT=_world_script(box.current) if world else "",
                PV_LIVE=SRC.live)
    if r.returncode != 0 or not os.path.exists(out):
        raise RuntimeError("the live layer's frame failed")
    return "world" if world else "den"


def painting(box):
    """The still behind the live layer (the fallback when it can't draw): a world's layers
    stacked, else the den."""
    from PIL import Image
    layers_dir = os.path.join(box.current, "backgrounds", "layers")
    files = sorted(glob.glob(os.path.join(layers_dir, "*.webp")) + glob.glob(os.path.join(layers_dir, "*.png")))
    if files:
        im = Image.new("RGBA", (DESK_W, DESK_H), (0, 0, 0, 255))
        for f in files:
            im.alpha_composite(Image.open(f).convert("RGBA").resize((DESK_W, DESK_H), Image.LANCZOS))
        return im.convert("RGB")
    comp = os.path.join(box.current, "backgrounds", "comp.webp")
    if os.path.exists(comp):
        return _cover(Image.open(comp).convert("RGB"), DESK_W, DESK_H)
    return _cover(den_still(box), DESK_W, DESK_H)


def den_still(box):
    """The den's painting in the box's theme: recoloured for a colour theme as the live layer
    recolours its plate (bromigos_retint), as it is under the Wick."""
    from PIL import Image
    im = Image.open(SRC.den).convert("RGB")
    try:
        import numpy as np
        import bromigos_retint as R
        with open(os.path.join(box.current, "palette.json")) as f:
            doc = json.load(f)
        col = doc.get("colors") or {}
        pal = dict({r: col.get(r, R.WICK[r]) for r in R.ROLES}, theme=doc.get("theme", "wick"))
        return Image.fromarray(R.retint(np.asarray(im), pal))
    except Exception:
        return im


def _cover(im, w, h):
    from PIL import Image
    s = max(w / im.width, h / im.height)
    im = im.resize((max(w, round(im.width * s)), max(h, round(im.height * s))), Image.LANCZOS)
    x, y = (im.width - w) // 2, (im.height - h) // 2
    return im.crop((x, y, x + w, y + h))


# bromigos-homelab's widgets: a picture with any of them gets the made-up lab (demo_lab.py)
HOMELAB_PANELS = {"lab", "alerts", "labjobs", "games", "solar"}
PANELS = ("system", "network")       # what a preview shows (the switcher's): the default scene's panels
BAR_H = 34                          # the bar's height (waybar config.jsonc): panel positions start below it
# the panels' places when the default layout has none: bromigos-homelab's LAB, beside SYSTEM
PLUGIN_SPOTS = {"lab": {"x": 514, "y": 16, "width": 470, "height": 640}}
DEMO_NOTES = """lamp check at the outer buoy, 06:00
- relay 3 hums on the hour: swap the coupler
- chart the lanes past the Drift edge
- greywater: more coffee

ideas
- a theme for the harbour at dawn
"""


def default_layout():
    """The packaged layout.json (the default panels and their places)."""
    for p in (os.path.join(SRC.widgets, "layout.json"), os.path.join(SRC.share, "widgets", "layout.json")):
        if os.path.exists(p):
            with open(p) as f:
                return json.load(f)
    return {"panels": []}


def load_scene(scene=None):
    """What a picture shows, with every default filled in. `scene` is a dict or a JSON
    file (`--scene FILE`; `--panels a,b` is {"panels": ["a", "b"]}):

      panels    [name | {"name", "x", "y", "width", "height"}, …]: layout.json's own
                entries (places in px from the top-left of the area below the bar);
                a bare name takes its place in the default layout (lab: beside SYSTEM).
                Default: SYSTEM and NETWORK, the switcher's previews
      terminal  false: none; or {"at": [x, y, w, h] (the window, border included; default:
                where it hides the least of the scene), "script": FILE (a script the
                terminal runs, which touches $PV_READY when it has drawn; default: the demo
                session), "font_size": pt, "title": text}
      notes     FIELD NOTES' text, when it shows
    """
    where = None
    if isinstance(scene, str):
        where = os.path.dirname(os.path.abspath(scene))
        with open(scene) as f:
            scene = json.load(f)
    scene = dict(scene or {})
    places = {p["name"]: p for p in default_layout().get("panels", [])}
    out = []
    for item in scene.get("panels", list(PANELS)):
        spec = {"name": item} if isinstance(item, str) else dict(item)
        base = dict(places.get(spec["name"]) or PLUGIN_SPOTS.get(spec["name"]) or {})
        base.update(spec)
        base.pop("visible", None)
        if "x" not in base or "y" not in base:
            raise ValueError(f"the panel {spec['name']!r} has no place: give it x and y")
        out.append(base)
    scene["panels"] = out
    term = scene.get("terminal", True)
    scene["terminal"] = False if term is False else dict(term) if isinstance(term, dict) else {}
    if scene["terminal"] and scene["terminal"].get("script") and where:     # a file's script: beside it
        scene["terminal"]["script"] = os.path.join(where, scene["terminal"]["script"])
    scene.setdefault("notes", DEMO_NOTES)
    return scene


def panel_rects(scene):
    """The panels' rectangles on the screen (below the bar)."""
    return [(p["x"], p["y"] + BAR_H, int(p.get("width", 470)), int(p.get("height", 470))) for p in scene["panels"]]


def panels(box, log, scene):
    """The scene's panels, drawn by the widgets with demo readings."""
    names = [p["name"] for p in scene["panels"]]
    r = box.run([SYS_PY, __file__, "--child", "widgets", box.out] + names, 60, log, PV_WIDGETS=SRC.widgets,
                BROMIGOS_WIDGETS_DEMO_LAB="1" if "lab" in names else "0", BROMIGOS_HOMELAB=homelab_dir() or "")
    if r.returncode != 0:
        raise RuntimeError("the panels failed")
    with open(os.path.join(box.out, "panels.json")) as f:
        return json.load(f)


def homelab_dir():
    """bromigos-homelab's tree (its widgets: LAB), in the checkout or installed."""
    for d in ((os.path.join(SRC.root, "homelab") if SRC.root else None), "/usr/lib/bromigos/homelab"):
        if d and os.path.isdir(os.path.join(d, "widgets")):
            return d
    return None


def gtk_theme(box, log):
    """The GTK theme the desktop gives this theme (the `gtk` theme-set hook's build), so
    the bar's buttons are drawn as on the desktop."""
    script = os.path.join(SRC.gtk, "build-gtk-theme.py")
    if not os.path.exists(script):
        return None
    out = os.path.join(box.home, ".themes", f"Bromigos-{box.name}")
    r = box.run([SYS_PY, script, "--current", "--out", out], 60, log, PYTHONPATH=SRC.pylib)
    return os.path.basename(out) if r.returncode == 0 and os.path.isdir(out) else None


def bar(box, comp, log, gtk):
    out = os.path.join(box.out, "bar.png")
    extra = {"WAYLAND_DISPLAY": comp.socket, "GDK_BACKEND": "wayland", "PV_WAYBAR": SRC.waybar}
    if gtk:
        extra["GTK_THEME"] = gtk
    r = box.run([SYS_PY, __file__, "--child", "bar", box.current, out, str(DESK_W)], 60, log, **extra)
    if r.returncode != 0 or not os.path.exists(out):
        raise RuntimeError("the bar failed")
    return out


TERM_SCRIPT = r"""#!/bin/bash
# the demo session in a preview's terminal
cd "$HOME/projects/drift-atlas" || exit 1
P=$'\e[1;34m~/projects/drift-atlas\e[0m \e[35mmain\e[0m \e[32m❯\e[0m '
say() { printf '%s%s\n' "$P" "$1"; }
say "ls"; ls --color=always -F
say "git log --oneline --graph -4"; git -c color.ui=always log --oneline --graph --decorate -4
say "git status -sb"; git -c color.ui=always status -sb
say "bromigos theme current"; bromigos theme current
printf '%s%s\n' "$P" "palette"
for i in 0 1 2 3 4 5 6 7; do printf '\e[48;5;%dm \e[38;5;%dm%2d \e[0m' $i $((i == 0 ? 7 : 0)) $i; done; printf '\n'
for i in 8 9 10 11 12 13 14 15; do printf '\e[48;5;%dm \e[38;5;0m%2d \e[0m' $i $i; done; printf '\n'
for i in 1 2 3 4 5 6; do printf '\e[38;5;%dm■■■ ' $i; done; printf '\e[0m\e[1mbold\e[0m \e[2mdim\e[0m \e[4munderline\e[0m\n'
printf '%s' "$P"
touch "$PV_READY"
exec sleep 300
"""

DEMO_COMMITS = ["first chart of the inner lanes", "beacon timings from the relay log", "a lane for the long haul",
                "chart the outer lanes"]


def _demo_project(box):
    """A demo project in the throwaway home: a few files and a git history."""
    d = os.path.join(box.home, "projects", "drift-atlas")
    for sub in ("docs", "src", "tools"):
        os.makedirs(os.path.join(d, sub), exist_ok=True)
    for f, text in (("README.md", "# drift-atlas\n"), ("Cargo.toml", "[package]\nname = \"drift-atlas\"\n"),
                    ("docs/notes.md", "notes\n"), ("src/lanes.rs", "// lanes\n")):
        with open(os.path.join(d, f), "w") as fh:
            fh.write(text)
    with open(os.path.join(d, "build.sh"), "w") as fh:
        fh.write("#!/bin/sh\ncargo build\n")
    os.chmod(os.path.join(d, "build.sh"), 0o755)
    if not os.path.lexists(os.path.join(d, "notes")):
        os.symlink("docs/notes.md", os.path.join(d, "notes"))
    with open(os.path.join(d, "atlas.tar.gz"), "wb") as fh:
        fh.write(b"\x1f\x8b")
    env = box.env(GIT_AUTHOR_NAME="demo", GIT_AUTHOR_EMAIL="demo@example.org", GIT_COMMITTER_NAME="demo",
                  GIT_COMMITTER_EMAIL="demo@example.org", GIT_CONFIG_NOSYSTEM="1")
    if not os.path.isdir(os.path.join(d, ".git")):
        subprocess.run(["git", "init", "-q", "-b", "main", d], env=env, check=True, capture_output=True)
        t = 1760000000
        for i, m in enumerate(DEMO_COMMITS):
            with open(os.path.join(d, "docs", "notes.md"), "a") as fh:
                fh.write(m + "\n")
            e = dict(env, GIT_AUTHOR_DATE=f"{t + i * 86400} +0000", GIT_COMMITTER_DATE=f"{t + i * 86400} +0000")
            subprocess.run(["git", "-C", d, "add", "-A"], env=e, check=True, capture_output=True)
            subprocess.run(["git", "-C", d, "commit", "-q", "-m", m], env=e, check=True, capture_output=True)
        with open(os.path.join(d, "README.md"), "a") as fh:
            fh.write("the outer lanes\n")
        with open(os.path.join(d, "src", "beacons.rs"), "w") as fh:
            fh.write("// beacons\n")
    return d


def _kitty_setup(box, term=None):
    """kitty's config (the theme's kitty.conf, the house font), the demo session's script
    (or the scene's) and the file it touches when it has printed everything: (config dir,
    script, ready)."""
    term = term or {}
    _demo_project(box)
    kdir = os.path.join(box.dir, "kitty")
    os.makedirs(kdir, exist_ok=True)
    with open(os.path.join(kdir, "kitty.conf"), "w") as f:
        f.write(f"include {box.current}/kitty.conf\n"
                f"font_family Geist Mono\nfont_size {float(term.get('font_size', 11.0)):.1f}\n"
                "window_padding_width 10\ncursor_shape block\n"
                "cursor_blink_interval 0\nenable_audio_bell no\nconfirm_os_window_close 0\nupdate_check_interval 0\n"
                "allow_remote_control no\nshell_integration disabled\nhide_window_decorations yes\n"
                "remember_window_size no\nlinux_display_server wayland\n")
    if term.get("script"):                      # the scene's own, run where it is
        script = os.path.abspath(term["script"])
        if not os.access(script, os.X_OK):
            raise RuntimeError(f"the scene's terminal script isn't executable: {script}")
    else:
        script = os.path.join(box.dir, "term.sh")
        with open(script, "w") as f:
            f.write(TERM_SCRIPT)
        os.chmod(script, 0o755)
    ready = os.path.join(box.dir, "term.ready")
    if os.path.exists(ready):
        os.unlink(ready)
    return kdir, script, ready


def terminal(box, comp, log, term=None):
    """kitty with the theme's kitty.conf, a demo session in it (or the scene's), in our weston."""
    if not shutil.which("kitty"):
        raise RuntimeError("no kitty")
    kdir, script, ready = _kitty_setup(box, term)
    # software GL: kitty draws without the GPU into weston's shared-memory buffers
    env = box.env(WAYLAND_DISPLAY=comp.socket, KITTY_CONFIG_DIRECTORY=kdir, LIBGL_ALWAYS_SOFTWARE="1",
                  PV_READY=ready)
    with open(log, "a") as lf:
        proc = subprocess.Popen(["kitty", "--class", "bromigos-preview", "--title", "~/projects/drift-atlas", script],
                                env=env, stdout=lf, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                                cwd=box.home, start_new_session=True)
    try:
        t_end = time.time() + 30
        while time.time() < t_end and not os.path.exists(ready) and proc.poll() is None:
            time.sleep(0.1)
        if not os.path.exists(ready):
            raise RuntimeError("the terminal never got ready")
        time.sleep(0.8)                 # kitty draws what was printed
        shot = comp.screenshot(os.path.join(box.dir, "shots"), box.env(WAYLAND_DISPLAY=comp.socket))
        if not shot:
            raise RuntimeError("no screenshot of the terminal")
        return shot
    finally:
        if proc.poll() is None:
            try:
                os.killpg(proc.pid, signal.SIGTERM)
            except OSError:
                proc.terminate()
            try:
                proc.wait(5)
            except subprocess.TimeoutExpired:
                os.killpg(proc.pid, signal.SIGKILL)
        time.sleep(0.2)                 # kiosk: the next window is the only one



# ------------------------------------------------------------------ the whole desktop, nested
NESTED_TOOLS = ("kwin_wayland", "Hyprland", "hyprctl", "waybar", "grim", "swaybg", "kitty", "dbus-daemon")
STUB = "#!/bin/sh\nexit 0\n"

# kwin's window rule for the nested Hyprland's window (its app id is "aquamarine", Hyprland's
# Wayland backend): full screen, forced. Then every size kwin sends it is the whole virtual
# screen, DESK_W x DESK_H. Without it, kwin 6.8 sends a late "choose your own size" (0x0)
# after Hyprland has sized its window, and Hyprland's backend reads 0x0 as its built-in
# 1280x720: the picture was the desktop's top-left corner. kwin 6.7 gives the same picture
# with the rule as without it (checked with 6.7.5). The hand-run nested tests
# (desktop/tests/e2e_keys_nested.py and those built on it) use the same rule and size check
# (write_kwin_rules, wait_for_size). A second nested output (`hyprctl output create`) keeps
# its own monitor rule's size.
KWIN_RULES = """[General]
count=1
rules=bromigos-preview

[bromigos-preview]
Description=bromigOS preview: the nested desktop fills the screen
wmclass=aquamarine
wmclassmatch=1
fullscreen=true
fullscreenrule=2
"""


# The nested compositors never get a seat. Hyprland asks libseat for one (for its DRM
# backend) even when it's nested; libseat's logind backend then takes the login session
# the caller runs in. When that session isn't the one on screen (a terminal multiplexer
# started from a text console, an ssh login), Hyprland sees an inactive session and
# draws nothing: its start-up never runs (no bar, no panels) and grim waits for a frame
# that never comes, every time. When it is the one on screen,
# the nested Hyprland could reach for the real GPU's outputs. "none" is no libseat
# backend at all, so opening a seat fails at once, on any machine (with seatd running
# too), and Hyprland uses only its Wayland backend. The hand-run nested tests
# (e2e_keys_nested.py and those built on it) start theirs with the same.
NO_SEAT = {"LIBSEAT_BACKEND": "none"}


class WrongSize(RuntimeError):
    """The nested desktop came up at another size than the one asked for: its picture would
    show only part of the desktop, so it isn't kept."""


def write_kwin_rules(config_dir):
    """KWIN_RULES as kwinrulesrc in `config_dir`: the XDG_CONFIG_HOME the nested kwin is
    started with, where kwin reads its window rules."""
    os.makedirs(config_dir, exist_ok=True)
    with open(os.path.join(config_dir, "kwinrulesrc"), "w") as f:
        f.write(KWIN_RULES)


def monitor_size(monitors_json, output="WAYLAND-1"):
    """(width, height) in pixels of `output` in `hyprctl monitors -j`'s answer, or None."""
    try:
        mons = json.loads(monitors_json or "[]")
    except ValueError:
        return None
    m = next((m for m in mons if isinstance(m, dict) and m.get("name") == output), None)
    return (m.get("width"), m.get("height")) if m else None


def wait_for_size(ctl, size, timeout=10, output="WAYLAND-1"):
    """Wait until the nested Hyprland's `output` is `size` (width, height) in pixels. `ctl`
    runs hyprctl with its arguments and returns what it printed. WrongSize if it never is."""
    want = tuple(size)
    end = time.time() + timeout
    got = monitor_size(ctl("monitors", "-j"), output)
    while got != want and time.time() < end:
        time.sleep(0.1)
        got = monitor_size(ctl("monitors", "-j"), output)
    if got != want:
        w, h = got or (0, 0)
        raise WrongSize(f"the nested desktop came up at {w}x{h}, not {want[0]}x{want[1]}")
    return got


def nested_missing():
    """Why the nested desktop can't be drawn here (None: it can)."""
    if os.environ.get("BROMIGOS_PREVIEWS_NESTED", "1") == "0":
        return "turned off (BROMIGOS_PREVIEWS_NESTED=0)"
    miss = [t for t in NESTED_TOOLS if not shutil.which(t)]
    return f"no {', '.join(miss)}" if miss else None


def _paths_for_nested():
    """(the defaults' hypr/ folder, the user's thin hyprland.lua template)."""
    if SRC.root:
        return os.path.join(SRC.root, "desktop", "hypr"), os.path.join(SRC.root, "desktop", "user", "hypr",
                                                                       "hyprland.lua")
    return (os.path.join(SRC.share, "default", "hypr"),
            os.path.join(SRC.share, "default", "user", "hypr", "hyprland.lua"))


def _demo_bar_files(box):
    """The custom modules' demo output (the bar scripts' own formats, retinted), one file each."""
    sys.path.insert(0, SRC.pylib)
    import bromigos_theme as T
    T.PATH = os.path.join(box.current, "palette.json")         # this theme, not the caller's
    T._sig = None
    T.version(0.0)
    d = os.path.join(box.dir, "bar-demo")
    os.makedirs(d, exist_ok=True)
    out = {}
    for mod, doc in (("custom/game", {"text": "", "class": []}),
                     ("custom/gpu", {"text": "23% <span color='#7e927e'>51°</span>", "class": ""}),
                     ("custom/storage", {"text": "<span color='#7e927e'>/</span> <span color='#9cff8a'>38%</span>",
                                         "class": ""}),
                     ("custom/vector", {"text": "VECTOR", "class": "idle"}),
                     ("custom/vector-switch", {"text": "\uf011", "class": ["on"]}),
                     ("custom/idle", {"text": " ", "class": ["normal"]}),
                     ("custom/bluetooth", {"text": "<span size='x-small' rise='4500'>1</span>",
                                           "class": ["connected", "c4"]})):
        p = os.path.join(d, mod.split("/")[1] + ".json")
        with open(p, "w") as f:
            f.write(T.retint(json.dumps(doc)) + "\n")
        out[mod] = {"exec": f"cat {p}", "return-type": "json", "interval": 3600}
    out.update(_demo_builtins(box))
    return out


# waybar's own modules read the machine (its load, memory, temperature, network, the
# time): each one's format becomes its demo text (bar_modules: the module's format filled
# with the demo readings), and its thresholds unreachable, so no reading of this machine
# can show or colour it. The other keys stay (waybar merges a config's includes into it).
# waybar keeps a state's threshold in a byte (0-255): 101 is past any percentage, and a
# bigger number would wrap round to a small one (10**6 is 64) and colour the module.
_NEVER, _NEVER_C = 101, 250


def _demo_builtins(box):
    try:
        _, mods = bar_modules(box.current, SRC.waybar)
    except (OSError, ValueError):
        return {}
    text = {css: t for _, kind, css, t, _ in mods if kind == "label" and t is not None}
    out = {}
    for mod, extra in (("cpu", {"states": {"warning": _NEVER, "critical": _NEVER}}),
                       ("memory", {"states": {"warning": _NEVER, "critical": _NEVER}}),
                       ("temperature", {"warning-threshold": _NEVER_C, "critical-threshold": _NEVER_C}),
                       ("clock", {"interval": 3600}),
                       ("network", {})):
        t = text.get(mod)
        if t is None or "{" in t or "}" in t:
            continue
        doc = {"format": t, "interval": 3600, **extra}
        if mod == "network":
            doc.update({k: t for k in ("format-ethernet", "format-wifi", "format-linked", "format-disconnected",
                                       "format-disabled")})
        out[mod] = doc
    return out


class Nested:
    """The real desktop, nested: a headless kwin (kwin_wayland --virtual: no screen) hosting
    a Hyprland that runs bromigOS's own config (the user's thin hyprland.lua over the
    defaults), with the real waybar (bromigOS's config and style, the theme's waybar.css),
    the real panels (demo readings) and kitty, all in the throwaway home with a runtime
    directory and a D-Bus of its own (no service activation). What the defaults would start
    that reaches past a session (the wallpaper's swaybg restart, the live layer, idle, the
    notifications, the OSD) is a stub; the background is the live layer's own frame on
    swaybg. The picture is grim's, inside the nested session; nothing is on any real
    output."""

    def __init__(self, box, log):
        self.box, self.log = box, log
        self.rt = _short_tmp("bpn.")
        self.procs = []
        self.env = None
        self.captured = None                    # grim's picture's size (grab)

    def _start(self, argv, env, name):
        with open(os.path.join(self.box.dir, f"nested-{name}.log"), "w") as lf:
            p = subprocess.Popen(argv, env=env, stdout=lf, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                                 cwd=self.box.home, start_new_session=True)
        self.procs.append(p)
        return p

    @staticmethod
    def _wait(fn, t):
        end = time.time() + t
        while time.time() < end:
            v = fn()
            if v:
                return v
            time.sleep(0.1)
        return fn()

    def ctl(self, *args):
        try:
            return subprocess.run(["hyprctl", *args], env=self.env, capture_output=True, text=True,
                                  timeout=10).stdout
        except (OSError, subprocess.SubprocessError):
            return ""

    def start(self, background, gtk=None, scene=None):
        """The nested desktop up, with `background` behind it and the scene's panels and
        terminal (load_scene). Then ready() waits for them; grab() takes the picture."""
        box, rt = self.box, self.rt
        self.scene = scene = scene or load_scene()
        hypr_dir, template = _paths_for_nested()
        stubs = os.path.join(rt, "stubs")
        share = os.path.join(rt, "share")
        os.makedirs(stubs)
        os.makedirs(os.path.join(share, "default"))
        os.symlink(hypr_dir, os.path.join(share, "default", "hypr"))
        for sub in ("themes", "theme"):
            if os.path.isdir(os.path.join(SRC.share, sub)):
                os.symlink(os.path.join(SRC.share, sub), os.path.join(share, sub))
        bro = shutil.which(SRC.bromigos) or SRC.bromigos
        for name, text in {
                "dunst": STUB, "hypridle": STUB, "bromigos-windows": STUB, "bromigos-live": STUB,
                "swayosd-server": STUB, "notify-send": STUB, "bromigos-wallpaper": STUB, "xdg-open": STUB,
                # the session's own commands stay in the sandbox; the rest is the real CLI
                "bromigos": f'#!/bin/sh\ncase "$1" in session|wallpaper|idle|live|vector) exit 0;; esac\n'
                            f'exec "{bro}" "$@"\n',
                "bromigos-widgets": f'#!/bin/sh\nBROMIGOS_WIDGETS_DEMO=1 exec {SYS_PY} '
                                    f'"{os.path.join(SRC.widgets, "bromigos-widgets")}" "$@"\n'}.items():
            p = os.path.join(stubs, name)
            with open(p, "w") as f:
                f.write(text)
            os.chmod(p, 0o755)
        self.stubs = stubs
        cfg = os.path.join(box.dir, "config")
        term = scene["terminal"]
        rects = panel_rects(scene)
        from PIL import Image
        bg_img = Image.open(background).convert("RGB")
        if term is False:
            tx = ty = tw = th = 0
        elif term.get("at"):
            tx, ty, tw, th = (int(v) for v in term["at"])
        else:
            tx, ty, tw, th = place_terminal(bg_img, BAR_H, rects, 2,
                                            scene=os.path.exists(os.path.join(box.current, "live", "world.toml")))
        self.terminal_at = None if term is False else [tx, ty, tw, th]
        with open(template) as f:
            conf = f.read()
        conf = re.sub(r'dofile\("[^"]*/default/hypr/hyprland\.lua"\)',
                      'dofile(os.getenv("BROMIGOS_SHARE_DIR") .. "/default/hypr/hyprland.lua")', conf)
        conf = conf.replace("bromigos = {\n", "bromigos = {\n    polkit = false,\n"
                            f'    monitors = {{ {{ output = "WAYLAND-1", mode = "{DESK_W}x{DESK_H}", '
                            'position = "0x0", scale = 1 } },\n'
                            "    config = { xwayland = { enabled = false }, misc = { disable_watchdog_warning = true },"
                            " cursor = { inactive_timeout = 0.3 }, debug = { disable_logs = true },"
                            " ecosystem = { no_update_news = true, no_donation_nag = true } },\n", 1)
        if term is not False:
            # the window's inside: the border (2 px) is Hyprland's, outside it
            conf += ("\n-- the preview's terminal: floating where the scene puts it\n"
                     'hl.window_rule({ match = { class = "bromigos-preview" }, float = true })\n'
                     f'hl.window_rule({{ match = {{ class = "bromigos-preview" }}, size = "{tw - 4} {th - 4}" }})\n'
                     f'hl.window_rule({{ match = {{ class = "bromigos-preview" }}, move = "{tx + 2} {ty + 2}" }})\n')
        conf += scene.get("hyprland", "")
        os.makedirs(os.path.join(cfg, "hypr"), exist_ok=True)
        with open(os.path.join(cfg, "hypr", "hyprland.lua"), "w") as f:
            f.write(conf)
        # the user's waybar files as a new user has them, pointed at this checkout or the packages
        os.makedirs(os.path.join(cfg, "waybar"), exist_ok=True)
        with open(os.path.join(cfg, "waybar", "config"), "w") as f:
            json.dump({"include": [os.path.join(SRC.waybar, "config.jsonc"),
                                   os.path.join(box.current, "waybar-markup.jsonc")], **_demo_bar_files(box)}, f)
        with open(os.path.join(cfg, "waybar", "style.css"), "w") as f:
            f.write(f'@import url("file://{box.current}/waybar.css");\n'
                    f'@import url("file://{os.path.join(SRC.waybar, "style.css")}");\n')
        # the panels: the scene's, where it puts them (a layout.json of their own)
        os.makedirs(os.path.join(cfg, "bromigos", "widgets"), exist_ok=True)
        lay = default_layout()
        lay["panels"] = [dict(p, visible=True) for p in scene["panels"]]   # a plugin's own default is off
        with open(os.path.join(cfg, "bromigos", "widgets", "layout.json"), "w") as f:
            json.dump(lay, f)
        names = [p["name"] for p in scene["panels"]]
        if "notes" in names:
            notes = os.path.join(box.home, ".local", "share", "bromigos", "notes.md")
            os.makedirs(os.path.dirname(notes), exist_ok=True)
            with open(notes, "w") as f:
                f.write(scene["notes"])
        dconf = os.path.join(rt, "dbus.conf")
        with open(dconf, "w") as f:
            f.write('<!DOCTYPE busconfig PUBLIC "-//freedesktop//DTD D-Bus Bus Configuration 1.0//EN" '
                    '"http://www.freedesktop.org/standards/dbus/1.0/busconfig.dtd">\n'
                    f'<busconfig><type>session</type><listen>unix:path={rt}/bus</listen>'
                    '<policy context="default"><allow send_destination="*" eavesdrop="true"/>'
                    '<allow eavesdrop="true"/><allow own="*"/></policy></busconfig>\n')
        base = box.env(XDG_RUNTIME_DIR=rt, BROMIGOS_SHARE_DIR=share, DBUS_SESSION_BUS_ADDRESS=f"unix:path={rt}/bus",
                       PATH=f"{stubs}:{os.path.join(box.dir, 'bin')}:/usr/bin:/bin", **NO_SEAT)
        if set(names) & HOMELAB_PANELS and homelab_dir():
            base.update(BROMIGOS_HOMELAB=homelab_dir(), BROMIGOS_WIDGETS_DEMO_LAB="1")
        if gtk:
            base["GTK_THEME"] = gtk
        self._start(["dbus-daemon", f"--config-file={dconf}", "--nofork", "--nopidfile"], base, "dbus")
        if not self._wait(lambda: os.path.exists(os.path.join(rt, "bus")), 5):
            raise RuntimeError("the nested desktop's D-Bus didn't start")
        # a player playing, there before the bar (its middle shows it, as the composed bar's demo does)
        self._start([SYS_PY, __file__, "--child", "mpris"], base, "mpris")
        if shutil.which("playerctld"):          # waybar's media module asks playerctl's daemon
            self._start(["playerctld"], base, "playerctld")
        write_kwin_rules(cfg)                   # kwin reads it from XDG_CONFIG_HOME
        self._start(["kwin_wayland", "--virtual", "--width", str(DESK_W), "--height", str(DESK_H), "--socket", "kw",
                     "--no-lockscreen", "--no-global-shortcuts"], base, "kwin")
        if not self._wait(lambda: os.path.exists(os.path.join(rt, "kw")), 20):
            raise RuntimeError("kwin_wayland --virtual didn't start")
        self._start(["Hyprland", "-c", os.path.join(cfg, "hypr", "hyprland.lua")],
                    dict(base, WAYLAND_DISPLAY="kw", HYPRLAND_NO_SD_VARS="1", HYPRLAND_NO_SD_NOTIFY="1",
                         BROMIGOS_WIDGETS_DEMO="1"), "hyprland")

        def sig():
            d = os.path.join(rt, "hypr")
            for n in (os.listdir(d) if os.path.isdir(d) else []):
                if os.path.exists(os.path.join(d, n, ".socket.sock")):
                    return n
            return None
        s = self._wait(sig, 25)
        if not s:
            raise RuntimeError("the nested Hyprland didn't start")
        self.env = dict(base, WAYLAND_DISPLAY="wayland-1", HYPRLAND_INSTANCE_SIGNATURE=s, GDK_BACKEND="wayland")
        if not self._wait(lambda: "WAYLAND-1" in self.ctl("monitors"), 25):
            raise RuntimeError("the nested Hyprland has no output")
        wait_for_size(self.ctl, (DESK_W, DESK_H))
        self.wallpaper = self._start(["swaybg", "-o", "WAYLAND-1", "-m", "fill", "-i", background], self.env, "swaybg")
        self.ready_file = None
        if term is not False:
            kdir, script, self.ready_file = _kitty_setup(box, term)
            self._start(["kitty", "--class", "bromigos-preview", "--title", term.get("title", "~/projects/drift-atlas"),
                         script], dict(self.env, KITTY_CONFIG_DIRECTORY=kdir, PV_READY=self.ready_file), "kitty")

    def output_size(self):
        """(width, height) of the nested Hyprland's output in pixels, or None."""
        return monitor_size(self.ctl("monitors", "-j"))

    def layers(self):
        """The namespaces of the layer surfaces mapped now."""
        try:
            doc = json.loads(self.ctl("layers", "-j") or "{}")
        except ValueError:
            return []
        return [x.get("namespace") for m in doc.values() for lvl in (m.get("levels") or {}).values() for x in lvl]

    def ready(self, timeout=30):
        """Wait for the bar, the panels, the wallpaper and the terminal. Returns what showed."""
        n = len(self.scene["panels"])

        def up():
            ns = self.layers()
            return ns if ("waybar" in ns and ns.count("bromigos-widgets") >= n and "wallpaper" in ns
                          and (self.ready_file is None or os.path.exists(self.ready_file))) else None
        got = self._wait(up, timeout) or self.layers()
        try:
            clients = json.loads(self.ctl("clients", "-j") or "[]")
        except ValueError:
            clients = []
        self.term = next((c for c in clients if c.get("class") == "bromigos-preview"), None)
        if self.term:                           # its title in the bar (a panel can take the focus first)
            self.ctl("dispatch", 'hl.dsp.focus({ window = "class:bromigos-preview" })')
        time.sleep(1.2)                         # animations done, the cursor hidden
        self.got = got
        return got

    def grab(self, out):
        """grim's picture of the nested output, to `out` (PNG). A picture of another size
        than DESK_W x DESK_H is WrongSize (it would show part of the desktop)."""
        from PIL import Image
        try:
            r = subprocess.run(["grim", "-o", "WAYLAND-1", out], env=self.env, capture_output=True, text=True,
                               timeout=30)
        except subprocess.TimeoutExpired:
            raise RuntimeError("grim got no picture in 30 s: the nested Hyprland drew no frame") from None
        if r.returncode != 0 or not os.path.exists(out):
            raise RuntimeError(f"grim: {r.stderr.strip()[:200]}")
        with Image.open(out) as im:
            size = im.size
        if size != (DESK_W, DESK_H):
            os.unlink(out)
            raise WrongSize(f"the nested desktop's picture is {size[0]}x{size[1]}, not {DESK_W}x{DESK_H}")
        self.captured = list(size)
        return out

    def shoot(self, background, out, gtk=None, scene=None, hook=None):
        """The desktop with `background` behind it, to `out` (PNG). `hook(self)`, when
        given, runs once the desktop is up, before the picture (more windows, a menu).
        Returns what showed: {"bar", "panels", "terminal", "terminal_at"}."""
        self.start(background, gtk, scene)
        got = self.ready()
        if hook:
            hook(self)
        errs = self.ctl("configerrors").strip()
        self.grab(out)
        with open(self.log, "a") as lf:
            lf.write(f"nested: layers {got}, terminal {self.term and self.term.get('at')}, config errors {errs!r}\n")
        return {"bar": "waybar" in got, "panels": got.count("bromigos-widgets"), "terminal": self.term is not None,
                "terminal_at": self.terminal_at, "config_errors": errs, "captured": self.captured}

    def close(self):
        for p in reversed(self.procs):
            if p.poll() is None:
                try:
                    os.killpg(p.pid, signal.SIGTERM)
                except OSError:
                    pass
        for p in self.procs:
            try:
                p.wait(5)
            except subprocess.TimeoutExpired:
                try:
                    os.killpg(p.pid, signal.SIGKILL)
                except OSError:
                    pass
        shutil.rmtree(self.rt, ignore_errors=True)


# ------------------------------------------------------------------ no GPU
class GpuLost(RuntimeError):
    """The GPU didn't start for a nested compositor (EGL, its DRM backend). Every theme after
    it would fail the same way, so the run gives up (render)."""


# what the nested compositors log when the GPU doesn't start (Mesa's EGL on a device it has
# no driver for, Hyprland's backend, kwin's EGL)
GPU_TROUBLE = ("eglinitialize", "egl_not_initialized", "failed to create dri2 screen", "dri2: failed to create screen",
               "cbackend::create() failed", "missing protocols", "failed to initialize egl", "no egl display")


def gpu_trouble(text):
    t = (text or "").lower()
    return any(m in t for m in GPU_TROUBLE)


def driver_mismatch(root=None):
    """Why the GPU can't be used now, or None: NVIDIA's kernel module (loaded at boot) and its
    userspace libraries (replaced by an update) are different versions, until the computer
    restarts (core's reboot.rs decides the same for `bromigos update`; docs/update.md).
    BROMIGOS_GPU_ROOT moves where it reads (tests)."""
    root = root or os.environ.get("BROMIGOS_GPU_ROOT") or "/"
    try:
        with open(os.path.join(root, "sys/module/nvidia/version")) as f:
            running = f.read().strip()
    except OSError:
        return None
    installed = set()
    for d in ("usr/lib", "usr/lib64", "usr/lib/x86_64-linux-gnu"):
        try:
            names = os.listdir(os.path.join(root, d))
        except OSError:
            continue
        for n in names:
            m = re.match(r"(?:libEGL_nvidia|libGLX_nvidia|libnvidia-glcore)\.so\.(\d+(?:\.\d+)+)$", n)
            if m:
                installed.add(m.group(1))
    if not running or not installed or running in installed:
        return None
    return (f"the graphics driver was updated ({max(installed)} installed, {running} running): "
            "the previews are drawn after the computer restarts")


def nested_desktop(box, background, log, gtk=None, tries=2, scene=None, hook=None):
    """The real desktop's picture (Nested), at DESK_W x DESK_H, to box.out/desktop.png. A
    nested session that doesn't come up is tried once more (the GPU can be slow to hand
    the last one's buffers back); its logs go to the render log. When the logs say the GPU
    didn't start, there's no second try: GpuLost."""
    err = None
    for attempt in range(tries):
        n = Nested(box, log)
        try:
            out = os.path.join(box.out, "desktop.png")
            got = n.shoot(background, out, gtk, scene=scene, hook=hook)
            return out, got
        except Exception as e:
            err = e
            tails = ""
            for name in ("hyprland", "kwin"):
                try:
                    with open(os.path.join(box.dir, f"nested-{name}.log")) as f:
                        tails += f"--- {name}\n" + "".join(f.readlines()[-15:])
                except OSError:
                    pass
            with open(log, "a") as lf:
                lf.write(f"nested desktop, attempt {attempt + 1}: {e}\n{tails}")
            if gpu_trouble(tails):
                err = GpuLost(f"the GPU didn't start for the nested desktop ({e})")
                break
        finally:
            n.close()
        time.sleep(1.0)
    raise err

# ------------------------------------------------------------------ putting it together
def _rgba(s, default):
    """A Hyprland colour ("rgb(39ff14)", "rgba(39ff1430)") as an (r, g, b, a) tuple."""
    m = re.match(r"rgba?\(([0-9a-fA-F]{6})([0-9a-fA-F]{2})?\)", s or "")
    if not m:
        return default
    h = m.group(1)
    return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16), int(m.group(2), 16) if m.group(2) else 255)


def decorations(box, palette):
    """The window border and shadow, from the theme's rendered hyprland.lua (and the
    defaults' border_size 2, rounding 0, shadow range 16)."""
    try:
        with open(os.path.join(box.current, "hyprland.lua")) as f:
            lua = f.read()
    except OSError:
        lua = ""
    col = palette.get("colors", {})
    prim = col.get("primary", "#39ff14").lstrip("#")
    dflt = (int(prim[0:2], 16), int(prim[2:4], 16), int(prim[4:6], 16), 255)
    m = re.search(r"active_border\s*=\s*\{\s*colors\s*=\s*\{([^}]*)\}", lua)
    if m:
        cols = [_rgba(c, dflt) for c in re.findall(r'"([^"]+)"', m.group(1))] or [dflt]
    else:
        m = re.search(r'active_border\s*=\s*"([^"]+)"', lua)
        cols = [_rgba(m.group(1), dflt)] if m else [dflt]
    m = re.search(r'\bshadow\s*=\s*"([^"]+)"', lua)
    shadow = _rgba(m.group(1), dflt[:3] + (0x30,)) if m else dflt[:3] + (0x30,)
    m = re.search(r"border_size\s*=\s*(\d+)", lua)
    return {"border": cols, "shadow": shadow, "border_size": int(m.group(1)) if m else 2, "shadow_range": 16}


def _saliency(bg, rects):
    """How much of the scene each rect would hide: light, colour and detail (creatures,
    lights and the keeper score high; sky, water and the den's void low)."""
    from PIL import Image, ImageFilter, ImageStat
    small = bg.resize((DESK_W // 8, DESK_H // 8), Image.BILINEAR)
    grey = small.convert("L")
    edges = grey.filter(ImageFilter.FIND_EDGES).filter(ImageFilter.GaussianBlur(1))
    hsv = small.convert("HSV")
    sat = hsv.getchannel("S")
    out = []
    for (x, y, w, h) in rects:
        box = (x // 8, y // 8, (x + w) // 8, (y + h) // 8)
        e = ImageStat.Stat(edges.crop(box)).mean[0]
        lum = ImageStat.Stat(grey.crop(box))
        s = ImageStat.Stat(sat.crop(box)).mean[0]
        bright = sum(v * c for v, c in enumerate(grey.crop(box).histogram()[160:], 160)) / max(1, w * h // 64)
        out.append(e * 2.0 + lum.mean[0] * 0.3 + s * 0.15 + bright * 0.02)
    return out


def place_terminal(bg, bar_h, panel_rects, border, scene=True):
    """Where the terminal goes: of a few spots clear of the bar and the panels, the one that
    hides the least of the scene (the first, in order of preference, within a tenth of the
    best, so a steady scene keeps a steady layout). Not a world's scene (the den, the same
    behind every colour theme): the first spot, so those previews line up."""
    w, h = TERM_W + 2 * border, TERM_H + 2 * border
    gap = 12
    left = max((x + pw for x, _, pw, _ in panel_rects), default=0) + gap * 2
    right, centre = DESK_W - gap - w, max(left, (DESK_W - w) // 2 + 120)
    top, middle, bottom = bar_h + gap, (bar_h + DESK_H - h) // 2, DESK_H - gap - h
    rects = [(x, y, w, h) for x, y in ((right, bottom), (right, top), (centre, top), (centre, bottom),
                                       (right, middle), (centre, middle)) if x >= left]
    if not scene:
        return rects[0]
    scores = _saliency(bg, rects)
    best = min(scores)
    return next(r for s, r in zip(scores, rects) if s <= best * 1.1)


def compose(box, palette, pieces, out_path, full=False, scene=None):
    """The desktop: the background, the panels and the bar over it (blurred behind, as
    Hyprland's layer rules do), the terminal window with its border and shadow."""
    from PIL import Image, ImageDraw, ImageFilter
    bg = pieces["background"].convert("RGB")
    desk = bg.convert("RGBA")
    blurred = bg.filter(ImageFilter.GaussianBlur(4)).convert("RGBA")
    bar_h = pieces.get("bar_h", 34)
    deco = decorations(box, palette)

    def layer(img, x, y):
        """A layer surface with blur behind it (ignore_alpha 0.2: only where it's drawn)."""
        a = img.getchannel("A").point(lambda v: 255 if v > 51 else 0)
        desk.paste(blurred.crop((x, y, x + img.width, y + img.height)), (x, y), a)
        desk.alpha_composite(img, (x, y))

    scene = scene or load_scene()
    rects = []
    for spec in scene["panels"]:
        p = pieces.get(f"panel:{spec['name']}")
        if p is None:
            continue
        x, y = int(spec["x"]), int(spec["y"]) + bar_h
        rects.append((x, y, p.width, p.height))
        layer(p, x, y)
    term = pieces.get("terminal")
    if term is not None and scene["terminal"] is not False:
        b = deco["border_size"]
        if scene["terminal"].get("at"):
            tx, ty, tw, th = (int(v) for v in scene["terminal"]["at"])
        else:
            tx, ty, tw, th = place_terminal(bg, bar_h, rects, b, scene=pieces.get("kind") == "world")
        # the shadow: the theme's shadow colour, range 16, falling off
        sh = Image.new("RGBA", desk.size, (0, 0, 0, 0))
        r = deco["shadow_range"]
        ImageDraw.Draw(sh).rectangle((tx - r // 3, ty - r // 3, tx + tw + r // 3, ty + th + r // 3),
                                     fill=deco["shadow"])
        sh = sh.filter(ImageFilter.GaussianBlur(r * 0.6))
        desk.alpha_composite(sh)
        # the border: the theme's gradient at 45 degrees
        cols = deco["border"]
        grad = Image.new("RGBA", (tw, th))
        if len(cols) == 1:
            grad.paste(cols[0], (0, 0, tw, th))
        else:
            gd = ImageDraw.Draw(grad)
            n = tw + th
            for i in range(n):
                t = i / max(1, n - 1)
                k = min(len(cols) - 2, int(t * (len(cols) - 1)))
                f = t * (len(cols) - 1) - k
                c = tuple(round(cols[k][j] + (cols[k + 1][j] - cols[k][j]) * f) for j in range(4))
                gd.line([(i, 0), (i - th, th)], fill=c, width=2)
        desk.alpha_composite(grad, (tx, ty))
        inner = term.convert("RGBA").resize((tw - 2 * b, th - 2 * b), Image.LANCZOS) \
            if term.size != (tw - 2 * b, th - 2 * b) else term.convert("RGBA")
        desk.alpha_composite(inner, (tx + b, ty + b))
        pieces["terminal_at"] = [tx, ty, tw, th]
    barimg = pieces.get("bar")
    if barimg is not None:
        layer(barimg, 0, 0)
    save(desk, out_path, full)


def save(img, out_path, full=False):
    """The picture, written whole: 1280x720 JPEG for the cache, or at full size (`--size`)
    in the format the name says (.png, .webp, else JPEG)."""
    from PIL import Image
    img = img.convert("RGB")
    if not full:
        img = img.resize((SAVE_W, SAVE_H), Image.LANCZOS)
    ext = os.path.splitext(out_path)[1].lower()
    tmp = out_path + ".tmp" + (ext or ".jpg")
    if ext == ".png":
        img.save(tmp, "PNG", optimize=True)
    elif ext == ".webp":
        img.save(tmp, "WEBP", quality=88)
    else:
        img.save(tmp, "JPEG", quality=90, optimize=True, progressive=True)
    os.replace(tmp, out_path)


def render_one(name, base, comp_box, log, dirs=None, out=None, full=False, scene=None, hook=None):
    """Draw one theme's preview. Returns its metadata (and writes it beside the picture).

    The real desktop nested (Nested: Hyprland, waybar, the panels and kitty, grim's picture)
    where kwin, Hyprland and grim are; else composed from the same pieces drawn one by one
    (kitty and the bar's GTK in a headless weston, the panels and the live layer offscreen,
    Hyprland's border and shadow from its config)."""
    from PIL import Image
    t0 = time.time()
    scene = load_scene(scene)
    st = stamp(name, dirs)
    out = out or path_for(name, st)
    box = Box(base, name, extra_dirs=dirs)
    palette = box.set_theme(log)
    pieces, notes = {}, []
    bg_png = os.path.join(box.out, "background.png")
    try:
        kind = live_frame(box, log, bg_png)
        pieces["background"] = Image.open(bg_png).convert("RGB")
    except Exception as e:                      # no GPU, no EGL: the painting, still
        kind = "painting"
        notes.append(f"background: {e}; the still painting instead")
        pieces["background"] = painting(box)
        pieces["background"].save(bg_png)
    pieces["kind"] = "world" if os.path.exists(os.path.join(box.current, "live", "world.toml")) else "den"
    os.makedirs(os.path.dirname(out) or ".", exist_ok=True)
    gtk = None
    why = nested_missing()
    if why is None:
        try:
            gtk = gtk_theme(box, log)
            shot, got = nested_desktop(box, bg_png, log, gtk, scene=scene, hook=hook)
            save(Image.open(shot), out, full)
            drawn = ["background"] + (["bar"] if got["bar"] else []) + \
                [f"panel:{p['name']}" for p in scene["panels"]][:got["panels"]] + \
                (["terminal"] if got["terminal"] else [])
            if got.get("config_errors"):
                notes.append(f"Hyprland's config errors: {got['config_errors'][:200]}")
            meta = {"schema": 1, "name": name, "stamp": st, "renderer": RENDERER, "path": out,
                    "background": kind, "desktop": "nested", "pieces": sorted(drawn),
                    "terminal_at": got.get("terminal_at"), "notes": notes, "size": [DESK_W, DESK_H],
                    "captured": got.get("captured"), "seconds": round(time.time() - t0, 1),
                    "rendered_at": int(time.time())}
            with open(os.path.splitext(out)[0] + ".json", "w") as f:
                json.dump(meta, f, indent=1)
            return meta
        except GpuLost:
            raise                               # not a lesser picture, cached as if current
        except Exception as e:
            notes.append(f"the nested desktop: {e}; composed instead")
    else:
        notes.append(f"the nested desktop: {why}; composed instead")
    try:
        for n, size in panels(box, log, scene).items():
            pieces[f"panel:{n}"] = Image.open(os.path.join(box.out, f"{n}.png")).convert("RGBA")
    except Exception as e:
        notes.append(f"panels: {e}")
    comp = None
    try:
        comp = comp_box()
    except Exception as e:
        notes.append(f"compositor: {e}; no bar or terminal")
    if comp is not None:
        try:
            gtk = gtk or gtk_theme(box, log)
            img = Image.open(bar(box, comp, log, gtk)).convert("RGBA")
            pieces["bar"], pieces["bar_h"] = img, img.height
        except Exception as e:
            notes.append(f"bar: {e}")
        if scene["terminal"] is not False:
            try:
                pieces["terminal"] = Image.open(terminal(box, comp, log, scene["terminal"])).convert("RGBA")
            except Exception as e:
                notes.append(f"terminal: {e}")
    compose(box, palette, pieces, out, full, scene)
    meta = {"schema": 1, "name": name, "stamp": st, "renderer": RENDERER, "path": out, "background": kind,
            "desktop": "composed",
            "pieces": sorted(k for k in pieces if not k.endswith("_at") and k not in ("bar_h", "kind")),
            "terminal_at": pieces.get("terminal_at"), "notes": notes, "size": [DESK_W, DESK_H],
            "seconds": round(time.time() - t0, 1), "rendered_at": int(time.time())}
    with open(os.path.splitext(out)[0] + ".json", "w") as f:
        json.dump(meta, f, indent=1)
    return meta


class _Lazy:
    """The compositor, started the first time a theme needs it, shared by the run."""

    def __init__(self, log):
        self.log, self.c, self.err = log, None, None

    def __call__(self):
        if self.err:
            raise RuntimeError(self.err)
        if self.c is None:
            try:
                self.c = Compositor(TERM_W, TERM_H, self.log)
            except Exception as e:
                self.err = str(e)
                raise
        return self.c

    def close(self):
        if self.c:
            self.c.close()


def render(names, force=False, dirs=None, out=None, progress=None, wait=True, size=None, scene=None, hook=None):
    """Draw the previews of `names` that are missing or stale (all of them with force).
    One run at a time (a lock in the cache): a second one waits, then finds them drawn.
    `dirs`/`out`: one theme from a directory (not installed), written to `out` too.
    `size` (w, h) with `out`: one theme's desktop at that size, full size, to `out` only
    (pictures for elsewhere: the site, a catalog); the cache isn't touched. `scene` (a dict
    or a JSON file, load_scene) with `out` too: what it shows (the panels and where, the
    terminal); `hook(nested)` runs in the nested desktop before its picture (a tool's extras).
    Returns [meta, …]; a theme that failed has "error"."""
    if size or scene or hook:
        if not out or len(names) != 1:
            raise ValueError("a size or a scene needs one theme and an output file")
        if size:
            set_size(*size)
        size = size or (DESK_W, DESK_H)
    os.makedirs(CACHE, exist_ok=True)
    clean_legacy()
    lock = open(os.path.join(CACHE, ".lock"), "w")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | (0 if wait else fcntl.LOCK_NB))
    except BlockingIOError:
        return [{"name": n, "error": "another render is running"} for n in names]
    log = os.path.join(CACHE, "render.log")
    with open(log, "w") as lf:
        lf.write(f"bromigos theme previews, renderer {RENDERER}, {time.ctime()}\n")
    # the GPU can't be used until the computer restarts: nothing is tried (each theme would
    # fail, slowly, on the CPU's software renderer)
    why = driver_mismatch()
    if why:
        _say(log, f"not drawing: {why}")
        lock.close()
        return [{"name": n, "held": why} for n in names]
    base = tempfile.mkdtemp(prefix="bromigos-previews.")
    comp = _Lazy(log)
    results = []
    lost = None                                 # the GPU failed in this run: the rest wait
    try:
        for name in names:
            if lost:
                results.append({"name": name, "held": f"not tried: {lost}", "log": log})
                continue
            if size:
                if progress:
                    progress(name, "rendering")
                try:
                    results.append(render_one(name, base, comp, log, dirs=dirs, out=os.path.abspath(out), full=True,
                                              scene=scene, hook=hook))
                except GpuLost as e:
                    lost = str(e)
                    _say(log, f"giving up this run after one failure: {lost}")
                    results.append({"name": name, "error": f"GpuLost: {e}", "log": log})
                except Exception as e:
                    results.append({"name": name, "error": f"{type(e).__name__}: {e}", "log": log})
                continue
            st = stamp(name, dirs)
            dest = path_for(name, st)
            if not force and os.path.exists(dest) and not out:
                results.append({"name": name, "stamp": st, "path": dest, "skipped": "current"})
                continue
            if progress:
                progress(name, "rendering")
            failed = os.path.splitext(dest)[0] + ".failed"
            try:
                meta = render_one(name, base, comp, log, dirs=dirs, out=dest)
                if os.path.exists(failed):
                    os.unlink(failed)
                if out and os.path.abspath(out) != dest:
                    shutil.copy(dest, out)
                    meta["copied_to"] = out
                # this theme's older pictures and failures (NAME-STAMP: wick's, never wick-mire's)
                fails = [p for p in glob.glob(os.path.join(CACHE, f"{glob.escape(name)}-*.failed"))
                         if re.fullmatch(re.escape(name) + r"-[0-9a-f]{12}\.failed", os.path.basename(p))]
                for old in cached(name) + fails:
                    if old != dest:                    # the older versions' pictures
                        for p in (old, os.path.splitext(old)[0] + ".json"):
                            try:
                                os.unlink(p)
                            except OSError:
                                pass
                results.append(meta)
            except Exception as e:
                if isinstance(e, GpuLost):
                    lost = str(e)
                    _say(log, f"giving up this run after one failure: {lost}; the next run tries again")
                err = {"name": name, "stamp": st, "error": f"{type(e).__name__}: {e}", "log": log}
                results.append(err)
                try:
                    with open(failed, "w") as f:      # the switcher says so instead of waiting
                        json.dump(err, f)
                except OSError:
                    pass
            # each theme's throwaway home goes as soon as its picture is drawn (a world's is
            # tens of MB, and /tmp is often memory)
            shutil.rmtree(os.path.join(base, re.sub(r"[^A-Za-z0-9_.-]", "_", name)), ignore_errors=True)
            if progress:
                progress(name, "done")
    finally:
        comp.close()
        shutil.rmtree(base, ignore_errors=True)
        lock.close()
    return results


def _say(log, line):
    """A line in the render log and on stderr (the journal, for the user service)."""
    with open(log, "a") as lf:
        lf.write(line + "\n")
    print(f"bromigos theme previews: {line}", file=sys.stderr, flush=True)


# ------------------------------------------------------------------ the children (system Python, sealed)
def _child_live(argv):
    """The live layer's offscreen renderer with demo readings (no machine, no lab, no
    agents of the user's, no sound)."""
    import math
    import threading
    live_dir = os.environ["PV_LIVE"]
    sys.path.insert(0, live_dir)
    import live.data as LD

    lab = None
    if os.environ.get("PV_DEMO_LAB") == "1":    # a made-up lab for the decks (widgets/demo_lab.py)
        sys.path.insert(0, os.environ.get("PV_WIDGETS") or SRC.widgets)
        from demo_lab import DEMO_LAB as lab

    def snap(t):
        cores = [max(2.0, min(96.0, 22 + 18 * math.sin(t * 0.7 + i * 0.9) + 10 * math.sin(t * 2.3 + i)))
                 for i in range(24)]
        # the readings the widgets' demo shows (37% of 64 GB, 58 °C, 2.3 MB/s); VRAM in MiB,
        # as the live layer reads it from nvidia-smi
        return {"cpu": sum(cores) / len(cores), "cores": cores, "cpu_temp": 58.0, "cpu_freq": 4710.0,
                "mem": 37.0, "mem_used": 23.6 * 2 ** 30, "mem_total": 64 * 2 ** 30, "swap": 0.0,
                "gpu": 23.0, "vram": 26.0, "vram_used": 3.1 * 1024, "vram_total": 12 * 1024,
                "gpu_temp": 51.0, "gpu_power": 74.0, "gpu_fan": 32.0, "gpu_clock": 1830.0,
                "rx": 2.3e6 * (0.8 + 0.2 * math.sin(t * 0.5)), "tx": 3.5e5,
                "rx_hist": [2.0e6 + 1.5e6 * math.sin(i * 0.4) ** 2 for i in range(48)],
                "tx_hist": [2.5e5 + 1.8e5 * math.sin(i * 0.5 + 1) ** 2 for i in range(48)],
                "disks": {"nvme0n1": {"read": 1.2e6, "write": 3.4e5}}, "nvme_temps": {"nvme0n1": 41.0},
                "mounts": [{"mount": "/", "used": 702e9, "total": 1863e9, "pct": 37.7, "fs": "btrfs",
                            "dev": "nvme0n1p2"},
                           {"mount": "/data", "used": 2.61e12, "total": 3.73e12, "pct": 70.0, "fs": "ext4",
                            "dev": "sda1"}],
                "cluster": dict(lab, generatedAt=time.time() - 4) if lab else None, "cluster_ok": bool(lab),
                "cluster_at": time.time() if lab else 0, "fills_total": None, "board_temp": 38.0,
                "chipset_temp": 51.0}

    class DemoData:
        def __init__(self, cfg, on_event):
            self.cfg, self.on_event = cfg, on_event
            self.lock = threading.Lock()
            self.paused = False
            self.stop = threading.Event()
            self.t0 = time.monotonic()
            self.static = {"cpu_model": "AMD Ryzen 9 7900", "threads": 24, "cores_phys": 12,
                           "kernel": "6.16.8-arch1-1", "arch": "x86_64", "sys": "Linux",
                           "gpu_name": "NVIDIA GeForce RTX 4070",
                           "drives": [{"name": "nvme0n1", "model": "Samsung SSD 990 PRO 2TB", "size": 2000398934016,
                                       "nvme": True},
                                      {"name": "sda", "model": "WDC WD40EFRX", "size": 4000787030016, "nvme": False}]}
            self.minute = {"cpu": [], "rx": [], "tx": []}
            self.s = snap(0.0)

        def snapshot(self):
            return snap(time.monotonic() - self.t0)

        def take_minute(self):
            return {"cpu": 24.0, "rx": 2.4e6, "tx": 3.0e5}

        def start(self):
            pass

        def _set(self, **kw):
            self.s.update(kw)

    LD.Data = DemoData
    try:                                        # the world's own feeds (agents, models, VECTOR): off
        import live.worldfeed as WF
        WF.Feed.start = lambda self: None
    except Exception:
        pass
    try:
        import live.activity as AC

        class _Working:
            def state(self):
                return "working"

            def level(self):
                return 1.0

            def cursor(self):
                return (0.0, 0.0)

            def __getattr__(self, k):
                return lambda *a, **kw: None
        AC.get = lambda: _Working()
        import live.world as LW
        LW.activity = AC.get
    except Exception:
        pass
    try:
        import live.sound as SND
        for n in dir(SND):
            if callable(getattr(SND, n)) and n.startswith("play"):
                setattr(SND, n, lambda *a, **kw: None)
    except Exception:
        pass
    import importlib.util
    spec = importlib.util.spec_from_file_location("bromigos_offscreen", os.path.join(live_dir, "tools", "offscreen.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    sys.argv = ["offscreen.py"] + argv
    mod.main()


def _child_widgets(argv):
    """The panels, drawn as the desktop draws them (plugins.make, Panel.render), with demo
    readings, to PNGs with their transparency."""
    out, names = argv[0], argv[1:]
    wdir = os.environ["PV_WIDGETS"]
    sys.path.insert(0, wdir)
    import demo  # noqa: F401  (the demo readings, before the panels import the readers)
    import cairo
    import panels as P
    import plugins as PL
    core = {"system": P.SystemPanel, "network": P.NetworkPanel, "storage": P.StoragePanel,
            "workbench": P.WorkbenchPanel, "shortcuts": P.ShortcutsPanel, "weather": P.WeatherPanel,
            "connections": P.ConnectionsPanel}
    # the packaged layout (/usr/share/bromigos/widgets/layout.json), else beside the code
    # (a checkout): plugins.LAYOUT's own search, which the box's config can't reach
    with open(PL.LAYOUT if os.path.isfile(PL.LAYOUT) else os.path.join(wdir, "layout.json")) as f:
        layout = {p["name"]: p for p in json.load(f)["panels"]}
    sizes = {}
    for name in names:
        cfg = dict(layout.get(name, {}))
        if name in core:
            cls = core[name]
        elif name == "lab" and os.environ.get("BROMIGOS_HOMELAB"):     # bromigos-homelab's (demo.py: a made-up lab)
            sys.path.insert(0, os.path.join(os.environ["BROMIGOS_HOMELAB"], "widgets"))
            import homelab_panels
            cls, spot = homelab_panels.panel("lab")
            cfg = dict(spot, **cfg)
        else:
            continue                            # FIELD NOTES and plugins: only in the nested desktop
        panel = PL.make(cls, cfg, lambda p: None)
        w = int(cfg.get("width") or panel.width)
        h = int(panel.height if name == "system" else cfg.get("height") or panel.height)
        for _ in range(3):
            panel.tick()
        surf = cairo.ImageSurface(cairo.FORMAT_ARGB32, w, h)
        panel.render(cairo.Context(surf), w, h)
        surf.write_to_png(os.path.join(out, f"{name}.png"))
        sizes[name] = [w, h]
    with open(os.path.join(out, "panels.json"), "w") as f:
        json.dump(sizes, f)


DEMO_TRACK = {"artist": "Greywater", "title": "Low Tide", "album": "Harbour Lights", "length": 220, "position": 72}
MPRIS_XML = """<node>
 <interface name="org.mpris.MediaPlayer2">
  <property name="Identity" type="s" access="read"/><property name="CanQuit" type="b" access="read"/>
  <property name="CanRaise" type="b" access="read"/><property name="HasTrackList" type="b" access="read"/>
  <property name="SupportedUriSchemes" type="as" access="read"/><property name="SupportedMimeTypes" type="as" access="read"/>
 </interface>
 <interface name="org.mpris.MediaPlayer2.Player">
  <method name="Play"/><method name="Pause"/><method name="PlayPause"/><method name="Stop"/>
  <method name="Next"/><method name="Previous"/>
  <method name="Seek"><arg type="x" direction="in"/></method>
  <property name="PlaybackStatus" type="s" access="read"/><property name="LoopStatus" type="s" access="read"/>
  <property name="Rate" type="d" access="read"/><property name="Shuffle" type="b" access="read"/>
  <property name="Metadata" type="a{sv}" access="read"/><property name="Volume" type="d" access="read"/>
  <property name="Position" type="x" access="read"/><property name="MinimumRate" type="d" access="read"/>
  <property name="MaximumRate" type="d" access="read"/><property name="CanGoNext" type="b" access="read"/>
  <property name="CanGoPrevious" type="b" access="read"/><property name="CanPlay" type="b" access="read"/>
  <property name="CanPause" type="b" access="read"/><property name="CanSeek" type="b" access="read"/>
  <property name="CanControl" type="b" access="read"/>
 </interface>
</node>"""


def _child_mpris(argv):
    """A made-up player on the nested desktop's own bus (MPRIS), playing DEMO_TRACK, its
    position held still, for the bar's media module."""
    from gi.repository import Gio, GLib
    t = DEMO_TRACK
    V = GLib.Variant
    props = {
        "Identity": V("s", "mpv"), "CanQuit": V("b", False), "CanRaise": V("b", False),
        "HasTrackList": V("b", False), "SupportedUriSchemes": V("as", []), "SupportedMimeTypes": V("as", []),
        "PlaybackStatus": V("s", "Playing"), "LoopStatus": V("s", "None"), "Rate": V("d", 0.0),
        "Shuffle": V("b", False), "Volume": V("d", 0.35), "Position": V("x", t["position"] * 1000000),
        "MinimumRate": V("d", 0.0), "MaximumRate": V("d", 1.0), "CanGoNext": V("b", True),
        "CanGoPrevious": V("b", True), "CanPlay": V("b", True), "CanPause": V("b", True),
        "CanSeek": V("b", True), "CanControl": V("b", True),
        "Metadata": V("a{sv}", {"mpris:trackid": V("o", "/org/bromigos/demo/track/1"),
                                "mpris:length": V("x", t["length"] * 1000000), "xesam:title": V("s", t["title"]),
                                "xesam:artist": V("as", [t["artist"]]), "xesam:album": V("s", t["album"])}),
    }
    info = Gio.DBusNodeInfo.new_for_xml(MPRIS_XML)
    loop = GLib.MainLoop()

    def call(conn, sender, path, iface, method, params, inv):
        inv.return_value(None)

    def get(conn, sender, path, iface, name):
        return props.get(name)

    def acquired(conn, name):
        for i in info.interfaces:
            conn.register_object("/org/mpris/MediaPlayer2", i, call, get, None)
    Gio.bus_own_name(Gio.BusType.SESSION, "org.mpris.MediaPlayer2.mpv", Gio.BusNameOwnerFlags.NONE,
                     acquired, None, lambda *a: loop.quit())
    GLib.timeout_add_seconds(600, loop.quit)
    loop.run()


def _jsonc(path):
    with open(path) as f:
        text = f.read()
    # comments out (not inside strings), then trailing commas
    out, i, n, s = [], 0, len(text), None
    while i < n:
        c = text[i]
        if s:
            out.append(c)
            if c == "\\":
                out.append(text[i + 1])
                i += 1
            elif c == s:
                s = None
        elif c == '"':
            s = c
            out.append(c)
        elif text.startswith("//", i):
            while i < n and text[i] != "\n":
                i += 1
            continue
        elif text.startswith("/*", i):
            i = text.find("*/", i) + 2
            continue
        else:
            out.append(c)
        i += 1
    return json.loads(re.sub(r",(\s*[}\]])", r"\1", "".join(out)))


def bar_modules(cur, waybar_dir):
    """The bar's modules as waybar would draw them here: bromigOS's config (with the
    theme's markup colours merged in, as the user's config includes them), each module's
    own format filled with demo values. [(side, kind, css name, text or None, classes)]."""
    import datetime
    sys.path.insert(0, SRC.pylib)
    import bromigos_theme as T
    cfg = _jsonc(os.path.join(waybar_dir, "config.jsonc"))
    try:
        for k, v in _jsonc(os.path.join(cur, "waybar-markup.jsonc")).items():
            if isinstance(v, dict) and isinstance(cfg.get(k), dict):
                cfg[k].update(v)
    except (OSError, ValueError):
        pass
    h = int(DEMO_HOUR)
    m = int(round((DEMO_HOUR - h) * 60))
    now = datetime.datetime(2026, 10, 9, h, m, 7)
    # the demo readings: what a quiet desktop shows (the scripts' own formats for custom/)
    demo = {
        "cpu": {"usage": 12}, "memory": {"percentage": 37, "used": 23.6, "total": 64.0},
        "temperature": {"temperatureC": 58},
        "network": {"bandwidthDownBytes": "2.3MB/s", "bandwidthUpBytes": "353kB/s", "ifname": "enp7s0"},
        "pulseaudio": {"volume": 35}, "mpris": {"artist": "Greywater", "title": "Low Tide", "position": "1:12",
                                                "length": "3:40", "player": "mpv", "status": "playing"},
        "hyprland/window": {"title": "~/projects/drift-atlas"},
    }
    custom = {   # the bar scripts' output (desktop/waybar/scripts), written in the Wick's colours
        "custom/game": ("", []),
        "custom/idle": (" ", ["normal"]),
        "custom/vector": ("VECTOR", []),
        "custom/vector-switch": ("\uf011", ["on"]),          # VECTOR's emergency switch, on
        "custom/gpu": ("23% <span color='#7e927e'>51°</span>", []),
        "custom/storage": ("<span color='#7e927e'>/</span> <span color='#9cff8a'>38%</span>", []),
        "custom/bluetooth": ("<span size='x-small' rise='4500'>1</span>", ["connected", "c4"]),
    }
    skip = {"power-profiles-daemon", "battery"}          # a laptop's: not on this desktop
    out = []
    for side in ("modules-left", "modules-center", "modules-right"):
        for mod in cfg.get(side, []):
            base = mod.split("#")[0]
            mc = cfg.get(mod, {}) if isinstance(cfg.get(mod), dict) else {}
            css = base.replace("/", "-") if base.startswith("custom/") else base.split("/")[-1]
            if base in skip:
                continue
            if base == "ext/workspaces" or base.endswith("/workspaces"):
                out.append((side, "workspaces", "workspaces", None, []))
                continue
            if base == "tray":
                out.append((side, "tray", "tray", None, []))
                continue
            if base in custom:
                text, cls = custom[base]
                out.append((side, "label", css, T.retint(text), cls))
                continue
            if base.startswith("custom/"):
                fmt = mc.get("format")
                if fmt:
                    out.append((side, "label", css, fmt.replace("{}", ""), []))
                continue
            if base == "clock":
                fmt = mc.get("format", "{:%H:%M}")
                out.append((side, "label", css, fmt.format(now), []))
                continue
            vals = demo.get(base, {})
            if base == "network":
                fmt = mc.get("format-ethernet") or mc.get("format") or "{ifname}"
                cls = ["ethernet"]
            elif base == "mpris":
                fmt = mc.get("format") or "{artist} - {title}"
                cls = ["playing"]
            else:
                fmt = mc.get("format") or "{}"
                cls = []
            try:
                text = fmt.format(**vals)
            except (KeyError, IndexError, ValueError):
                continue
            out.append((side, "label", css, text, cls))
    return cfg, out


def _child_bar(argv):
    """waybar's widget tree in GTK 3 (the toolkit waybar draws with) under waybar's own
    stylesheets, drawn offscreen: window#waybar > box > box.modules-{left,center,right},
    a label per module named as waybar names it (#cpu, #custom-vector, …), workspace
    buttons in box#workspaces."""
    cur, out, width = argv[0], argv[1], int(argv[2])
    import gi
    gi.require_version("Gtk", "3.0")
    gi.require_version("Gdk", "3.0")
    from gi.repository import Gdk, GLib, Gtk
    waybar_dir = os.environ["PV_WAYBAR"]
    cfg, mods = bar_modules(cur, waybar_dir)
    css = os.path.join(os.path.dirname(out), "bar-style.css")
    with open(css, "w") as f:                   # as the user's ~/.config/waybar/style.css does
        f.write(f'@import url("file://{cur}/waybar.css");\n'
                f'@import url("file://{os.path.join(waybar_dir, "style.css")}");\n')
    prov = Gtk.CssProvider()
    prov.load_from_path(css)
    Gtk.StyleContext.add_provider_for_screen(Gdk.Screen.get_default(), prov, Gtk.STYLE_PROVIDER_PRIORITY_USER)
    win = Gtk.OffscreenWindow()
    win.set_name("waybar")
    win.get_style_context().add_class(cfg.get("position", "top"))
    vis = win.get_screen().get_rgba_visual()
    if vis:
        win.set_visual(vis)

    def paint(w, cr):                           # a toplevel's own background and border
        sc, a = w.get_style_context(), w.get_allocation()
        Gtk.render_background(sc, cr, 0, 0, a.width, a.height)
        Gtk.render_frame(sc, cr, 0, 0, a.width, a.height)
        return False
    win.connect("draw", paint)
    box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=int(cfg.get("spacing", 0)))
    sides = {}
    for side in ("modules-left", "modules-center", "modules-right"):
        b = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=int(cfg.get("spacing", 0)))
        b.get_style_context().add_class(side)
        sides[side] = b
    box.pack_start(sides["modules-left"], False, False, 0)
    box.set_center_widget(sides["modules-center"])
    box.pack_end(sides["modules-right"], False, False, 0)
    for side, kind, name, text, classes in mods:
        if kind == "workspaces":
            ws = Gtk.Box()
            ws.set_name("workspaces")
            for i in range(1, 5):
                bt = Gtk.Button(label=str(i))
                bt.set_can_focus(False)
                bt.set_relief(Gtk.ReliefStyle.NONE)
                if i == 2:
                    bt.get_style_context().add_class("active")
                ws.pack_start(bt, False, False, 0)
            w = ws
        elif kind == "tray":
            w = Gtk.Box()
            w.set_name("tray")
        else:
            w = Gtk.EventBox()
            lab = Gtk.Label()
            lab.set_name(name)
            lab.set_markup(text)
            for c in classes:
                lab.get_style_context().add_class(c)
            w.add(lab)
        sides[side].pack_start(w, False, False, 0)
    win.add(box)
    win.set_size_request(width, int(cfg.get("height", 34)))
    win.show_all()
    state = {"n": 0}

    def snap():
        state["n"] += 1
        if win.get_allocated_width() < width and state["n"] < 40:
            return True
        surf = win.get_surface()
        surf.flush()
        surf.write_to_png(out)
        Gtk.main_quit()
        return False
    GLib.timeout_add(150, snap)
    GLib.timeout_add(15000, Gtk.main_quit)
    Gtk.main()
    if not os.path.exists(out):
        sys.exit("the bar never laid out")


if __name__ == "__main__" and len(sys.argv) > 2 and sys.argv[1] == "--child":
    kind, rest = sys.argv[2], sys.argv[3:]
    {"live": _child_live, "widgets": _child_widgets, "bar": _child_bar, "mpris": _child_mpris}[kind](rest)
