"""What bromigOS's built-in plugin panels share (widgets/plugins/*.py and the homelab's
widgets): settings from a TOML file, polling that pauses while the panel is hidden, clear
empty states, buttons, pictures, and small formatting helpers.

A file whose name starts with "_" isn't a panel (plugins.files() passes it over), so this
module is imported by the panels beside it:

    import os, sys
    sys.path.append(os.path.dirname(os.path.realpath(__file__)))   # after the standard library
    import _kit as K

    class MyPanel(K.KitPanel):
        name, title = "mine", "MINE"
        settings = [{"key": "repos", "label": "Repositories", "kind": "list", "default": []}]

        def __init__(self, cfg=None):
            super().__init__(cfg)
            self.poll = self.poller(self.fetch, every=300)   # runs only while it's seen

Settings: each panel's own file, ~/.config/bromigos/widgets/<name>.toml, read over the
panel's keys in layout.json, and read again when it changes. `settings` on the class says
what's in it, for the gallery card's Settings… form (docs/plugins.md, "Settings").

Demo readings: when the picture tools import demo.py ("demo" in sys.modules), demo() is
True and each panel draws its own made-up readings instead of reading anything.
"""
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time

import cairo

import draw as D
import panels as P

CONFIG = os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")
STATE = os.path.join(os.environ.get("XDG_STATE_HOME") or os.path.expanduser("~/.local/state"), "bromigos", "widgets")
CACHE = os.path.join(os.environ.get("XDG_CACHE_HOME") or os.path.expanduser("~/.cache"), "bromigos", "widgets")


def demo():
    """True while a picture is drawn with made-up readings (demo.py imported)."""
    return "demo" in sys.modules or os.environ.get("BROMIGOS_WIDGETS_DEMO") == "1"


def motion():
    """The user's motion setting: "full", "reduced" or "still" (bromigos_theme)."""
    try:
        return D.T.motion()
    except Exception:                                  # noqa: BLE001  an older theme library
        return "full"


def high_contrast():
    try:
        return bool(D.T.high_contrast())
    except Exception:                                  # noqa: BLE001
        return False


# ------------------------------------------------------------------ settings
def settings_path(name):
    return os.path.join(CONFIG, "bromigos", "widgets", f"{name}.toml")


class Settings:
    """A panel's settings: its layout.json keys, then widgets/<name>.toml over them, then
    the declared defaults under both. Re-read when the file changes (checked at most once
    every 2 s)."""

    def __init__(self, name, cfg=None, spec=()):
        self.name, self.cfg = name, dict(cfg or {})
        self.defaults = {s["key"]: s.get("default") for s in spec or () if "key" in s}
        self.path = settings_path(name)
        self.mtime, self.checked, self.values, self.error = None, 0.0, {}, None
        self.version = 0
        self.reload(force=True)

    def reload(self, force=False):
        now = time.monotonic()
        if not force and now - self.checked < 2:
            return False
        self.checked = now
        try:
            m = os.path.getmtime(self.path)
        except OSError:
            m = None
        if m == self.mtime and not force:
            return False
        self.mtime = m
        vals = dict(self.defaults)
        vals.update({k: v for k, v in self.cfg.items() if k not in ("x", "y", "width", "height", "visible", "name")})
        self.error = None
        if m is not None:
            try:
                import tomllib
                with open(self.path, "rb") as f:
                    vals.update(tomllib.load(f))
            except (OSError, ValueError) as e:
                self.error = f"{os.path.basename(self.path)}: {e}"[:160]
        self.values = vals
        self.version += 1
        return True

    def get(self, key, default=None):
        self.reload()
        v = self.values.get(key)
        return default if v is None else v

    def list(self, key):
        """A list setting; a string is split on commas, spaces and new lines."""
        v = self.get(key, [])
        if isinstance(v, str):
            v = [x for x in re.split(r"[,\s]+", v) if x]
        return [str(x).strip() for x in v if str(x).strip()]

    def exists(self):
        return self.mtime is not None


def home_path(p):
    """~/… for a path under the home folder (what a hint shows)."""
    h = os.path.expanduser("~")
    return "~" + p[len(h):] if p.startswith(h + os.sep) else p


# ------------------------------------------------------------------ polling that pauses when hidden
class Poller:
    """Runs fn() on a thread every `every` seconds while the panel is being drawn. When the
    panel hasn't been drawn for `idle` seconds (hidden, or covered by windows) it stops
    fetching; the next draw wakes it, and it fetches at once if its data is older than
    `every`. fn returns the data; an exception becomes .error (words) and keeps the old data."""

    def __init__(self, panel, fn, every, idle=None, name="poll", start=True):
        self.panel, self.fn, self.every = panel, fn, float(every)
        self.idle = float(idle if idle is not None else max(30.0, 2 * self.every))
        self.data, self.error, self.at, self.busy = None, None, 0.0, False
        self.runs = 0
        self._wake = threading.Event()
        self.name = name
        if start:
            threading.Thread(target=self._loop, daemon=True, name=f"{panel.name}-{name}").start()

    def seen(self):
        return time.monotonic() - getattr(self.panel, "drawn_at", 0.0) < self.idle

    def stale(self):
        return time.monotonic() - self.at >= self.every

    def kick(self):
        """Fetch now (a click on refresh, a setting changed)."""
        self.at = 0.0
        self._wake.set()

    def run_once(self):
        self.busy = True
        try:
            self.data = self.fn()
            self.error = None
        except Exception as e:                         # noqa: BLE001  shown in the panel, never raised
            self.error = _words(e)
        finally:
            self.at = time.monotonic()
            self.busy = False
            self.runs += 1
        wake = getattr(self.panel, "wake", None)
        if callable(wake):
            try:
                wake(self.panel)
            except Exception:                          # noqa: BLE001
                pass

    def _loop(self):
        first = True
        while True:
            if first or (self.seen() and self.stale()):
                first = False
                self.run_once()
            self._wake.wait(timeout=min(self.every, 5.0) if self.seen() else 5.0)
            self._wake.clear()


def _words(e):
    import urllib.error
    if isinstance(e, urllib.error.HTTPError):
        return f"HTTP {e.code} {e.reason}"
    if isinstance(e, urllib.error.URLError):
        return f"unreachable: {e.reason}"[:120]
    if isinstance(e, subprocess.TimeoutExpired):
        return "timed out"
    return (str(e) or type(e).__name__)[:160]


# ------------------------------------------------------------------ the panel base
class KitPanel(P.Panel):
    """A Panel with settings, pausing pollers and the house's empty state."""
    settings = []                                    # [{key, label, kind, default, hint, choices?, provider?}]

    def __init__(self, cfg=None, wake=None):
        super().__init__(cfg)
        self.wake = wake                             # the host's hook: redraw when data lands
        self.drawn_at = time.monotonic()            # as if seen: the first fetch happens
        self.pollers = []
        self.conf = Settings(self.name, cfg, self.settings)
        self._conf_v = self.conf.version
        self.last_class = None

    def poller(self, fn, every, idle=None, name="poll", start=True):
        p = Poller(self, fn, every, idle, name, start)
        self.pollers.append(p)
        return p

    def render(self, cr, w, h):
        self.drawn_at = time.monotonic()
        if self.conf.reload() and self.conf.version != self._conf_v:
            self._conf_v = self.conf.version
            self.settings_changed()
        for p in self.pollers:
            if p.stale() and not p.busy:
                p._wake.set()
        self.last_class = self.size_class(w, h)
        super().render(cr, w, h)

    def settings_changed(self):
        for p in self.pollers:
            p.kick()

    # ---- drawing helpers
    def empty(self, cr, w, h, top, headline, body="", tip=None, action=None, color="amber", button=None):
        """The panel's empty state: a headline, then how to set it up, in words. button:
        (label, tip, action) drawn under the words."""
        y = top + 6
        D.label(cr, 16, y, headline, color)
        y += 22
        if body:
            bw, bh = D.text(cr, 16, y, body, 11, "soft", "regular", width=w - 32, wrap=True)
            y += bh + 10
        self.region(0, top, w, h - top, tip or (headline.capitalize() + (". " + body if body else "")), action)
        if button:
            self.button(cr, 16, min(y, h - 30), *button)
        return y

    def button(self, cr, x, y, label, tip, action, color="phosphor", on=False, h=20):
        lay = D.layout(cr, label.upper(), 10, "semibold", 0.08)
        bw = max(34, lay.get_pixel_size()[0] + 16)
        D.src(cr, color if on else "guard", 0.22 if on else 0.9)
        cr.rectangle(x, y, bw, h)
        cr.fill()
        cr.set_line_width(1)
        D.src(cr, color if on else "dim", 0.9)
        cr.rectangle(x + 0.5, y + 0.5, bw - 1, h - 1)
        cr.stroke()
        D.text(cr, x + bw / 2, y + (h - 14) / 2, label.upper(), 10, color if on else "soft", "semibold", spacing=0.08,
               align="center")
        self.region(x, y, bw, h, tip, action)
        return bw

    def chip(self, cr, x, y, label, color="static", tip=None, filled=False):
        """A small status tag; returns its width."""
        lay = D.layout(cr, label.upper(), 9, "semibold", 0.1)
        cw = lay.get_pixel_size()[0] + 10
        D.src(cr, color, 0.9 if filled else 0.16)
        cr.rectangle(x, y, cw, 15)
        cr.fill()
        D.src(cr, color, 0.8)
        cr.set_line_width(1)
        cr.rectangle(x + 0.5, y + 0.5, cw - 1, 14)
        cr.stroke()
        D.text(cr, x + 5, y + 1, label.upper(), 9, "void" if filled else color, "semibold", spacing=0.1)
        if tip:
            self.region(x, y, cw, 15, tip)
        return cw

    def scrollbar(self, cr, x, top, view, total, offset):
        if total <= view:
            return
        th = max(20, view * view / total)
        ty = top + (view - th) * offset / max(1, total - view)
        D.src(cr, "guard", 1)
        cr.rectangle(x, top, 2, view)
        cr.fill()
        D.src(cr, "phosphor", 0.8)
        cr.rectangle(x, ty, 2, th)
        cr.fill()


# ------------------------------------------------------------------ the account sign-in, drawn
class Account:
    """A panel's sign-in to one provider (lib/bromigos_account.py), with what to draw."""

    def __init__(self, panel, provider):
        import bromigos_account as A
        self.A, self.panel, self.provider = A, panel, provider
        self.signin = A.Signin(provider, on_change=lambda s: self._changed())
        self._st, self._st_at = None, 0.0

    def _changed(self):
        self._st_at = 0.0
        if self.signin.state == "signed_in":
            for p in self.panel.pollers:
                p.kick()
        wake = getattr(self.panel, "wake", None)
        if callable(wake):
            try:
                wake(self.panel)
            except Exception:                          # noqa: BLE001
                pass

    def status(self):
        """status() from the helper, asked at most every 10 s (it reads the keyring)."""
        if self._st is None or time.monotonic() - self._st_at > 10:
            try:
                self._st = self.A.status(self.provider)
            except Exception as e:                     # noqa: BLE001  no keyring, …
                self._st = {"signed_in": False, "who": None, "needs": [], "via": None, "error": str(e)[:120]}
            self._st_at = time.monotonic()
        return self._st

    def token(self):
        return self.A.token(self.provider)

    def title(self):
        return self.A.PROVIDERS[self.provider]["title"]

    def draw_signin(self, cr, w, h, top, what):
        """The signed-out state: what's needed, a sign-in button, or the code to enter.
        what: a sentence saying what the panel reads ("The Twitch panel reads your channel
        and who you follow"); it opens both the not-set-up and the signed-out words."""
        p = self.panel
        st = self.status()
        t = self.title()
        s = self.signin
        if s.state == "waiting" and s.prompt and s.prompt.get("user_code"):
            pr = s.prompt
            D.label(cr, 16, top + 6, f"SIGN IN TO {t.upper()}", "phosphor")
            D.text(cr, 16, top + 28, f"Go to {pr.get('verification_uri', '')} and enter", 11, "soft", "regular",
                   width=w - 32)
            D.text(cr, 16, top + 48, pr["user_code"], 26, "phosphor", "bold", spacing=0.12, glow=True)
            p.region(16, top + 44, w - 32, 36, f"Your {t} sign-in code. The page opened in your browser; enter "
                     f"this code there and approve. Click to copy the code.", lambda: P.copy_text(pr["user_code"]))
            p.button(cr, 16, top + 90, "Cancel", "Stop this sign-in", s.cancel)
            return
        if s.state == "waiting":
            p.empty(cr, w, h, top, f"SIGNING IN TO {t.upper()}…",
                    "Finish in the browser window that opened. This panel updates when you're done.",
                    button=("Cancel", "Stop this sign-in", s.cancel))
            return
        A = self.A
        if st.get("needs"):
            prov = A.PROVIDERS[self.provider]
            p.empty(cr, w, h, top, f"{t.upper()} ISN'T SET UP",
                    f"{what.rstrip('.')}. It needs your own {t} app's client ID. {prov['app_help']} Then run: "
                    f"bromigos account configure {self.provider} client_id=YOUR_ID",
                    tip=f"{t} sign-in needs a client ID in {home_path(A.accounts_path())}. {prov['app_help']}")
            return
        err = s.error if s.state == "error" else st.get("error")
        p.empty(cr, w, h, top, f"NOT SIGNED IN TO {t.upper()}",
                (f"Last try: {err}. " if err else "") + f"{what.rstrip('.')}. Sign in once; the token stays in your keyring.",
                button=("Sign in", f"Sign in to {t}: a code to enter on {t}'s site (or a browser page), "
                        "then the token is kept in your login keyring", self.signin.start))


# ------------------------------------------------------------------ commands
def run(argv, timeout=10, env=None):
    """A command's stdout, or None when it's missing, fails or times out."""
    if not shutil.which(argv[0]):
        return None
    try:
        r = subprocess.run(argv, capture_output=True, text=True, timeout=timeout, env=env)
    except (OSError, subprocess.SubprocessError):
        return None
    return r.stdout if r.returncode == 0 else None


def run_json(argv, timeout=10):
    out = run(argv, timeout)
    if out is None:
        return None
    try:
        return json.loads(out)
    except ValueError:
        return None


def spawn(argv):
    try:
        subprocess.Popen(argv, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
    except OSError:
        pass


def terminal(argv, title=None, hold=True):
    """Run a command in the user's terminal (`bromigos terminal`)."""
    cmd = ["bromigos", "terminal"] + (["--hold"] if hold else []) + (["--title", title] if title else []) + ["--"] + argv
    spawn(cmd)


def open_url(url):
    P.open_url(url)


# ------------------------------------------------------------------ pictures
_pics = {}


def picture(src, size=None):
    """A cairo surface from a file path, a file:// URL or bytes, scaled to fit size (w, h);
    cached. None when it can't be read."""
    key = (src if isinstance(src, str) else hash(src), size)
    if key in _pics:
        return _pics[key]
    surf = None
    try:
        import gi
        gi.require_version("GdkPixbuf", "2.0")
        from gi.repository import GdkPixbuf, GLib
        if isinstance(src, (bytes, bytearray)):
            loader = GdkPixbuf.PixbufLoader()
            loader.write(bytes(src))
            loader.close()
            pb = loader.get_pixbuf()
        else:
            path = src[7:] if src.startswith("file://") else src
            from urllib.parse import unquote
            pb = GdkPixbuf.Pixbuf.new_from_file(unquote(path))
        if size:
            sw, sh = size
            k = min(sw / pb.get_width(), sh / pb.get_height())
            pb = pb.scale_simple(max(1, int(pb.get_width() * k)), max(1, int(pb.get_height() * k)),
                                 GdkPixbuf.InterpType.BILINEAR)
        surf = _pixbuf_surface(pb)
    except Exception:                                  # noqa: BLE001  GLib.Error, a bad file, no GdkPixbuf
        surf = None
    if len(_pics) > 64:
        _pics.clear()
    _pics[key] = surf
    return surf


def _pixbuf_surface(pb):
    """A GdkPixbuf as a cairo ImageSurface (premultiplied BGRA), without Gdk."""
    w, h = pb.get_width(), pb.get_height()
    if not pb.get_has_alpha():
        pb = pb.add_alpha(False, 0, 0, 0)
    stride_in = pb.get_rowstride()
    data = pb.get_pixels()
    surf = cairo.ImageSurface(cairo.FORMAT_ARGB32, w, h)
    stride = surf.get_stride()
    buf = surf.get_data()
    out = bytearray(stride * h)
    for y in range(h):
        row = data[y * stride_in:y * stride_in + w * 4]
        o = y * stride
        # RGBA -> BGRA (premultiplied)
        r, g, b, a = row[0::4], row[1::4], row[2::4], row[3::4]
        if all(x == 255 for x in a):
            out[o:o + w * 4:4], out[o + 1:o + w * 4:4], out[o + 2:o + w * 4:4], out[o + 3:o + w * 4:4] = b, g, r, a
        else:
            out[o:o + w * 4:4] = bytes(bb * aa // 255 for bb, aa in zip(b, a))
            out[o + 1:o + w * 4:4] = bytes(gg * aa // 255 for gg, aa in zip(g, a))
            out[o + 2:o + w * 4:4] = bytes(rr * aa // 255 for rr, aa in zip(r, a))
            out[o + 3:o + w * 4:4] = a
    buf[:] = bytes(out)
    surf.mark_dirty()
    return surf


def draw_picture(cr, surf, x, y, w, h, alpha=1.0, cover=True):
    """Paint surf into the box, cropped to fill it (cover) or fitted inside it."""
    if surf is None:
        return False
    sw, sh = surf.get_width(), surf.get_height()
    k = max(w / sw, h / sh) if cover else min(w / sw, h / sh)
    cr.save()
    cr.rectangle(x, y, w, h)
    cr.clip()
    cr.translate(x + (w - sw * k) / 2, y + (h - sh * k) / 2)
    cr.scale(k, k)
    cr.set_source_surface(surf, 0, 0)
    cr.paint_with_alpha(alpha)
    cr.restore()
    return True


def fetch_bytes(url, timeout=10, max_bytes=4 << 20, headers=None):
    import urllib.request
    req = urllib.request.Request(url, headers={"User-Agent": "bromigOS", **(headers or {})})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read(max_bytes)


# ------------------------------------------------------------------ words and numbers
def ago(t, now=None):
    """'now', '4m', '3h', '2d' since t (seconds since the epoch)."""
    if not t:
        return "?"
    s = max(0, (now or time.time()) - t)
    for n, u in ((86400, "d"), (3600, "h"), (60, "m")):
        if s >= n:
            return f"{int(s // n)}{u}"
    return "now"


def clock(t):
    return time.strftime("%H:%M", time.localtime(t))


def iso_time(s):
    """Seconds since the epoch from an ISO 8601 time ("2026-10-09T21:35:24Z", offsets, fractions)."""
    import datetime as dt
    if not s:
        return None
    if isinstance(s, (int, float)):
        return float(s)
    s = str(s).strip().replace("Z", "+00:00")
    s = re.sub(r"(\.\d{6})\d+", r"\1", s)               # nanoseconds: Python takes six digits
    try:
        d = dt.datetime.fromisoformat(s)
    except ValueError:
        return None
    if d.tzinfo is None:
        d = d.astimezone()
    return d.timestamp()


def short(n):
    """1234 -> 1.2K, 2500000 -> 2.5M."""
    if n is None:
        return "-"
    n = float(n)
    for div, u in ((1e9, "B"), (1e6, "M"), (1e3, "K")):
        if abs(n) >= div:
            return f"{n / div:.1f}{u}".replace(".0", "")
    return f"{n:.0f}"


_SECRET = re.compile(r"(?i)("
                     r"gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}|glpat-[A-Za-z0-9_\-]{16,}|"
                     r"sk-[A-Za-z0-9_\-]{16,}|xox[abpr]-[A-Za-z0-9\-]{10,}|AKIA[0-9A-Z]{16}|"
                     r"eyJ[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{5,}|"
                     r"(?:bearer|token|password|passwd|secret|api[_-]?key|authorization)[\"']?\s*[:=]\s*[\"']?[^\s\"',}]+|"
                     r"[A-Fa-f0-9]{32,}|[A-Za-z0-9+/]{40,}={0,2})")


def redact(s):
    """Text with anything that looks like a token, key or password replaced by «redacted»."""
    if s is None:
        return ""
    return _SECRET.sub("«redacted»", str(s))
