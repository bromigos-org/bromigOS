"""Widget plugins: new panels without touching the core files.

A plugin is one file, <plugins>/<name>.py, defining a panels.Panel subclass (PANEL = MyPanel,
or the first Panel subclass in the file) and optionally LAYOUT = {"width", "height", "x",
"y", "visible"}. layout.json's "plugins" map overrides LAYOUT per name. Without a position
the panel goes to free space on the monitor, clear of every other panel and of VECTOR's
console (bottom right).

<plugins> is each of DIRS, the first with a name wins (docs/plugins.md): the packaged
plugins/ beside this file, bromigos-homelab's panels (/usr/lib/bromigos/homelab/widgets,
or homelab/widgets in a bromigOS checkout), $BROMIGOS_WIDGET_PLUGINS or
~/.config/bromigos/plugins/widgets, installed extensions'
(~/.local/share/bromigos/ext/active/widgets: bromigos ext), and the old
~/.config/bromigos/widgets/plugins.

A file named <x>_panels.py is a panel generator: it names several panels, which come and go
with its own configuration (homelab.toml's [[panel]]s): names() -> {name: version} and
panel(name) -> (Panel class, LAYOUT). Each is a plugin like any other ("<file>#<name>").

  * Hot reload: the app rescans the plugin folders every 2 s; a new or changed file is (re)loaded,
    a removed one is closed.
  * Isolation: a plugin's tick() and draw() run inside SafePanel. An exception is logged
    (~/.local/state/bromigos/widgets-plugins.log, with the traceback), the panel shows
    the error instead of its content, and after 5 errors in a minute, or a draw slower
    than 100 ms five times running, the plugin is switched off (hidden) until its file
    changes. Nothing a plugin raises reaches the host.
  * Health: $XDG_RUNTIME_DIR/bromigos-widgets-health.json, written every 2 s (the build
    loop's trial watcher reads it: status, errors, draw times per plugin, a heartbeat).
  * Offscreen: `bromigos-widgets render <name|plugins/x.py> OUT.png` draws a panel to a
    PNG with real readings, no window (render()).
"""
import importlib.util
import json
import os
import sys
import time
import traceback

HERE = os.path.dirname(os.path.realpath(__file__))
_CONFIG = os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")
_HOMELAB = next((d for d in (os.environ.get("BROMIGOS_HOMELAB") and os.path.join(os.environ["BROMIGOS_HOMELAB"], "widgets"),
                             "/usr/lib/bromigos/homelab/widgets",
                             os.path.join(os.path.dirname(HERE), "homelab", "widgets")) if d and os.path.isdir(d)), None)
# installed extensions' widgets (`bromigos ext`; docs/extensions.md): after the user's own
EXT = os.path.join(os.environ.get("XDG_DATA_HOME") or os.path.expanduser("~/.local/share"),
                   "bromigos", "ext", "active", "widgets")
DIRS = [os.path.join(HERE, "plugins")] + ([_HOMELAB] if _HOMELAB else []) + [d for d in (os.environ.get("BROMIGOS_WIDGET_PLUGINS") or os.path.join(
    _CONFIG, "bromigos", "plugins", "widgets")).split(":") if d] + [EXT, os.path.join(_CONFIG, "bromigos", "widgets", "plugins")]
DIRS = list(dict.fromkeys(DIRS))
# layout.json: the user's (~/.config/bromigos/widgets/), else the packaged default, else beside the code
LAYOUT = next((p for p in (os.path.join(_CONFIG, "bromigos", "widgets", "layout.json"),
                           os.path.join(os.environ.get("BROMIGOS_SHARE_DIR") or "/usr/share/bromigos", "widgets", "layout.json"))
               if os.path.isfile(p)), os.path.join(HERE, "layout.json"))
LOG = os.path.expanduser("~/.local/state/bromigos/widgets-plugins.log")
HEALTH = os.path.join(os.environ.get("XDG_RUNTIME_DIR", "/tmp"), "bromigos-widgets-health.json")
MAX_ERRORS, ERROR_WINDOW, SLOW_MS, SLOW_RUN = 5, 60.0, 100.0, 5


def log(name, msg):
    os.makedirs(os.path.dirname(LOG), exist_ok=True)
    with open(LOG, "a") as f:
        f.write(f"{time.strftime('%Y-%m-%dT%H:%M:%S')} {name}: {msg.rstrip()}\n")


_gens = {}          # generator path -> (mtime, module)


def _generator(path):
    m = os.path.getmtime(path)
    hit = _gens.get(path)
    if hit and hit[0] == m:
        return hit[1]
    name = os.path.splitext(os.path.basename(path))[0]
    mod_name = f"bromigos_gen_{name}_{int(m * 1000)}"
    spec = importlib.util.spec_from_file_location(mod_name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[mod_name] = mod
    spec.loader.exec_module(mod)
    _gens[path] = (m, mod)
    return mod


def files():
    """{name: (path, mtime)} for every <plugins>/*.py, and every panel a generator names
    ({name: ("<file>#<name>", version)})."""
    out = {}
    for d in DIRS:
        if os.path.isdir(d):
            for f in sorted(os.listdir(d)):
                if not f.endswith(".py") or f.startswith(("_", ".")):
                    continue
                p = os.path.join(d, f)
                if f.endswith("_panels.py"):
                    try:
                        for n, v in _generator(p).names().items():
                            out.setdefault(n, (f"{p}#{n}", (os.path.getmtime(p), v)))
                    except Exception:
                        log(f[:-3], "generator failed:\n" + traceback.format_exc())
                    continue
                if f[:-3] not in out:
                    try:
                        out[f[:-3]] = (p, os.path.getmtime(p))
                    except OSError:
                        pass
    return out


def load(path):
    """-> (panel class, LAYOUT dict). Raises on any error (the caller logs it)."""
    import panels as P
    if "#" in path:                                   # a generator's panel
        gpath, pname = path.split("#", 1)
        cls, layout = _generator(gpath).panel(pname)
        if not (isinstance(cls, type) and issubclass(cls, P.Panel)):
            raise TypeError(f"{gpath}: panel({pname!r}) didn't return a panels.Panel subclass")
        return cls, dict(layout or {})
    name = os.path.splitext(os.path.basename(path))[0]
    mod_name = f"bromigos_plugin_{name}_{int(os.path.getmtime(path) * 1000)}"
    spec = importlib.util.spec_from_file_location(mod_name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[mod_name] = mod
    spec.loader.exec_module(mod)
    cls = getattr(mod, "PANEL", None)
    if cls is None:
        cls = next((v for v in vars(mod).values() if isinstance(v, type) and issubclass(v, P.Panel)
                    and v is not P.Panel and v.__module__ == mod_name), None)
    if cls is None or not issubclass(cls, P.Panel):
        raise TypeError("no panels.Panel subclass (set PANEL = YourPanel)")
    return cls, dict(getattr(mod, "LAYOUT", {}) or {})


class SafePanel:
    """Wraps a plugin panel: same interface as a Panel, but nothing it raises escapes."""

    def __init__(self, name, panel, path):
        self.name, self.inner, self.path = name, panel, path
        self.errors = []            # times
        self.last_error = None
        self.draw_ms = []
        self.slow_run = 0
        self.disabled = None        # reason
        self.loaded_at = time.time()

    # Panel interface ---------------------------------------------------------
    def __getattr__(self, k):
        return getattr(self.inner, k)

    @property
    def interval(self):
        return getattr(self.inner, "interval", 2.0)

    @property
    def animating(self):
        return bool(getattr(self.inner, "animating", False)) and not self.disabled

    def _fail(self, where, e):
        now = time.time()
        self.errors = [t for t in self.errors if now - t < ERROR_WINDOW] + [now]
        self.last_error = f"{where}: {type(e).__name__}: {str(e)[:160]}"
        log(self.name, f"{where} failed:\n{traceback.format_exc()}")
        if len(self.errors) >= MAX_ERRORS and not self.disabled:
            self.disabled = f"{MAX_ERRORS} errors in a minute ({self.last_error})"
            log(self.name, "switched off: " + self.disabled)

    def tick(self):
        if self.disabled:
            return
        try:
            self.inner.tick()
        except Exception as e:
            self._fail("tick", e)

    def hit(self, x, y):
        try:
            return self.inner.hit(x, y)
        except Exception:
            return None

    def scroll(self, dy):
        if hasattr(self.inner, "scroll"):
            try:
                self.inner.scroll(dy)
            except Exception as e:
                self._fail("scroll", e)

    def render(self, cr, w, h):
        import cairo

        import draw as D
        if self.disabled or (self.last_error and self.errors and time.time() - self.errors[-1] < 5):
            cr.set_operator(cairo.OPERATOR_SOURCE)
            cr.set_source_rgba(0, 0, 0, 0)
            cr.paint()
            cr.set_operator(cairo.OPERATOR_OVER)
            D.frame(cr, w, h, self.inner.title, "PLUGIN ERROR" if not self.disabled else "SWITCHED OFF", "danger")
            D.text(cr, 16, 50, (self.disabled or self.last_error or "")[:300], 11, "danger", width=w - 32, wrap=True)
            D.text(cr, 16, h - 26, f"plugins/{self.name}.py · log: widgets-plugins.log", 10, "static")
            self.inner.regions = [(0, 0, w, h, f"Plugin {self.name} failed: {self.last_error}. It is logged in "
                                   f"{LOG}; fix the file and it reloads.", None)]
            return
        t0 = time.perf_counter()
        cr.save()
        try:
            self.inner.render(cr, w, h)
        except Exception as e:
            self._fail("draw", e)
        finally:
            cr.restore()
        ms = (time.perf_counter() - t0) * 1000
        self.draw_ms = (self.draw_ms + [ms])[-50:]
        self.slow_run = self.slow_run + 1 if ms > SLOW_MS else 0
        if self.slow_run >= SLOW_RUN and not self.disabled:
            self.disabled = f"draw took over {SLOW_MS:.0f} ms {SLOW_RUN} times running ({ms:.0f} ms)"
            log(self.name, "switched off: " + self.disabled)

    def health(self):
        ms = sorted(self.draw_ms)
        return {"status": "off" if self.disabled else "error" if self.last_error and self.errors else "ok",
                "disabled": self.disabled, "errors_last_minute": len([t for t in self.errors if time.time() - t < 60]),
                "last_error": self.last_error, "draw_ms_p50": round(ms[len(ms) // 2], 1) if ms else None,
                "draw_ms_max": round(ms[-1], 1) if ms else None, "loaded_at": self.loaded_at, "path": self.path}


# ------------------------------------------------------------------ placement
def free_spot(w, h, taken, area, avoid=()):
    """The first free top-left (scanning columns from the right of the core panels, top to
    bottom) for a w x h panel inside area (W, H), clear of taken rects by 16 px."""
    W, H = area
    gap = 16
    rects = list(taken) + list(avoid)

    def clear(x, y):
        return all(x + w + gap <= rx or rx + rw + gap <= x or y + h + gap <= ry or ry + rh + gap <= y
                   for rx, ry, rw, rh in rects)
    xs = sorted({rx + rw + gap for rx, ry, rw, rh in taken} | {28})
    for x0 in xs + list(range(28, max(29, W - w), 32)):
        if x0 + w > W - 16:
            continue
        for y in range(16, max(17, H - h - 16), 16):
            if clear(x0, y):
                return x0, y
    return None


def make(cls, spec, wake=None):
    """A panel instance: with the host's wake hook when its constructor takes one (a panel that
    animates when its data lands, like LAB), else plain."""
    import inspect
    try:
        takes = "wake" in inspect.signature(cls.__init__).parameters
    except (TypeError, ValueError):
        takes = False
    return cls(spec, wake=wake) if takes else cls(spec)


def render(target, out, ticks=3, w=None, h=None, background=(0, 0.02, 0, 1)):
    """Draw a core panel (by name) or a plugin file to a PNG with real readings, no window."""
    import cairo

    import panels as P
    core = P.CORE
    layout = {}
    if target.endswith(".py") or target in files():
        path = target if target.endswith(".py") else files()[target][0]
        cls, layout = load(os.path.realpath(path))
    elif target in core:
        cls = core[target]
    else:
        raise SystemExit(f"no panel or plugin {target!r}")
    cfg = dict(layout)
    try:
        with open(LAYOUT) as f:
            spec = next((p for p in json.load(f).get("panels", []) if p.get("name") == target), {})
            cfg.update(spec)
    except (OSError, ValueError):
        pass
    panel = make(cls, cfg, lambda p: None)
    W = int(w or cfg.get("width") or panel.width)
    Hh = int(h or cfg.get("height") or panel.height)
    t0 = time.perf_counter()
    for i in range(max(1, int(ticks))):
        panel.tick()
        if i < ticks - 1:
            time.sleep(min(float(getattr(panel, "interval", 1.0)), 1.0))
    surf = cairo.ImageSurface(cairo.FORMAT_ARGB32, W, Hh)
    cr = cairo.Context(surf)
    cr.set_source_rgba(*background)
    cr.paint()
    layer = cairo.ImageSurface(cairo.FORMAT_ARGB32, W, Hh)
    lc = cairo.Context(layer)
    t1 = time.perf_counter()
    panel.render(lc, W, Hh)
    draw_ms = (time.perf_counter() - t1) * 1000
    cr.set_source_surface(layer, 0, 0)
    cr.paint()
    surf.write_to_png(out)
    regions = getattr(panel, "regions", [])
    return {"out": out, "size": [W, Hh], "draw_ms": round(draw_ms, 1), "ticks": ticks,
            "seconds": round(time.perf_counter() - t0, 2), "regions": len(regions),
            "regions_without_hint": sum(1 for r in regions if not (r[4] or "").strip()),
            "regions_out_of_bounds": sum(1 for r in regions if r[0] < -1 or r[1] < -1 or r[0] + r[2] > W + 1
                                         or r[1] + r[3] > Hh + 1)}
