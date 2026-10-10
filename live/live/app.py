"""bromigos-live daemon: one GTK process hosting the background layer, the
event overlays (intercept, transmission, screensaver), the holo deck and the
radial menu. Controlled over a unix socket by bin/bromigos-live."""
import os
import signal
import socket
import sys
import threading
import time

os.environ.setdefault("PYOPENGL_PLATFORM", "egl")

import gi  # noqa: E402

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
gi.require_version("GtkLayerShell", "0.1")
from gi.repository import Gdk, Gio, GLib, Gtk, GtkLayerShell  # noqa: E402

from OpenGL import GL  # noqa: E402

from . import config, hypr, motion, software  # noqa: E402
from .data import Data  # noqa: E402
from .sound import Sound, toggle_mute  # noqa: E402
from .watch import LockWatch, Notifications  # noqa: E402

RUNTIME = os.environ.get("XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}")
SOCK = os.path.join(RUNTIME, "bromigos-live.sock")


def _vector_alive():
    """VECTOR's daemon answering on its socket (then he explains lab alerts himself)."""
    import socket as _s
    try:
        c = _s.socket(_s.AF_UNIX)
        c.settimeout(0.3)
        c.connect(os.path.join(os.environ.get("XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}"), "bromigos-holo.sock"))
        c.sendall(b"status")
        ok = bool(c.recv(64))
        c.close()
        return ok
    except OSError:
        return False


def _vector_speaking():
    """VECTOR's daemon says he's speaking ($XDG_RUNTIME_DIR/bromigos-vector.json): the den TV ducks."""
    try:
        import json
        with open(os.path.join(RUNTIME, "bromigos-vector.json")) as f:
            return json.load(f).get("state") == "speaking"
    except (OSError, ValueError, AttributeError):
        return False


def log(*a):
    print("bromigos-live:", *a, flush=True)


def wait_for_display(limit=60.0):
    """Don't start half-alive: wait (up to `limit` s) for a Wayland socket that GTK can open
    with at least one monitor. Started from a context without one (a restart outside the
    session, the compositor restarting) we exit 3 instead, and the supervisor or exec-once
    starts us again once the session is up."""
    t0 = time.monotonic()
    said = False
    while True:
        d = Gdk.Display.get_default()
        if d is None:
            name = os.environ.get("WAYLAND_DISPLAY", "")
            if not name or not os.path.exists(os.path.join(RUNTIME, name)):
                socks = sorted((f for f in os.listdir(RUNTIME) if f.startswith("wayland-") and not f.endswith(".lock")),
                               key=lambda f: -os.path.getmtime(os.path.join(RUNTIME, f))) if os.path.isdir(RUNTIME) else []
                if socks:
                    os.environ["WAYLAND_DISPLAY"] = name = socks[0]
            if name and os.path.exists(os.path.join(RUNTIME, name)):
                ok = Gtk.init_check(sys.argv)
                ok = ok[0] if isinstance(ok, tuple) else ok
                d = Gdk.Display.get_default() if ok else None
        if d is not None and d.get_n_monitors() > 0:
            if said:
                log(f"display {os.environ.get('WAYLAND_DISPLAY', '?')} up after {time.monotonic() - t0:.0f} s")
            return d
        if not said:
            log("no usable display yet (no Wayland socket, or GTK can't open it); waiting up to "
                f"{limit:.0f} s")
            said = True
        if time.monotonic() - t0 > limit:
            log("no display after waiting; exiting so the supervisor can start us inside the session")
            sys.exit(3)
        if QUIT.wait(2.0):          # stopped while waiting
            sys.exit(0)


def find_monitor(name):
    display = Gdk.Display.get_default()
    if display is None:
        raise RuntimeError("no Gdk display")
    mons = [display.get_monitor(i) for i in range(display.get_n_monitors())]
    info = next((m for m in (hypr.request("monitors") or []) if m.get("name") == name), None)
    if info:
        for m in mons:
            g = m.get_geometry()
            if g.x == info["x"] and g.y == info["y"]:
                return m, (info["width"], info["height"])
    m = mons[0] if mons else None
    g = m.get_geometry() if m else None
    return m, ((g.width, g.height) if g else (2560, 1440))


def layer_window(monitor, layer, namespace, anchors="tblr", keyboard=None, exclusive=-1, size=None, margins=None):
    win = Gtk.Window()
    GtkLayerShell.init_for_window(win)
    GtkLayerShell.set_layer(win, layer)
    GtkLayerShell.set_namespace(win, namespace)
    if monitor:
        GtkLayerShell.set_monitor(win, monitor)
    for ch, edge in (("t", GtkLayerShell.Edge.TOP), ("b", GtkLayerShell.Edge.BOTTOM),
                     ("l", GtkLayerShell.Edge.LEFT), ("r", GtkLayerShell.Edge.RIGHT)):
        GtkLayerShell.set_anchor(win, edge, ch in anchors)
    GtkLayerShell.set_exclusive_zone(win, exclusive)
    if size:
        win.set_size_request(int(size[0]), int(size[1]))
    for ch, edge in (("t", GtkLayerShell.Edge.TOP), ("b", GtkLayerShell.Edge.BOTTOM),
                     ("l", GtkLayerShell.Edge.LEFT), ("r", GtkLayerShell.Edge.RIGHT)):
        if margins and ch in margins:
            GtkLayerShell.set_margin(win, edge, int(margins[ch]))
    GtkLayerShell.set_keyboard_mode(win, keyboard or GtkLayerShell.KeyboardMode.NONE)
    vis = win.get_screen().get_rgba_visual()
    if vis:
        win.set_visual(vis)
    win.set_app_paintable(True)
    return win


class GLWindow:
    """A layer-shell window with one GLArea driven by a timer at a set fps."""

    def __init__(self, app, layer, namespace, make_renderer, keyboard=None, alpha=False, input_ok=True,
                 anchors="tblr", size=None, margins=None):
        self.app = app
        self.mon, self.size = find_monitor(app.cfg["general"]["monitor"])
        if size:
            self.size = size
        self.win = layer_window(self.mon, layer, namespace, anchors=anchors, keyboard=keyboard, size=size,
                                margins=margins)
        self.area = Gtk.GLArea()
        self.area.set_required_version(3, 3)
        self.area.set_has_alpha(alpha)
        self.area.set_auto_render(False)
        self.make_renderer = make_renderer
        self.renderer = None
        self.fps = 0
        self.timer = None
        self.failed = False
        self.frames = 0
        self.ticks = 0
        self.last_frame = 0.0
        self.dead = False                  # the compositor closed our surface (output gone)
        self.created = time.monotonic()
        self.win.connect("delete-event", self._closed)
        self.area.connect("realize", self._realize)
        self.area.connect("unrealize", self._unrealize)
        self.area.connect("render", self._render)
        self.win.add(self.area)
        if not input_ok:
            self.win.connect("realize", lambda w: w.get_window().input_shape_combine_region(
                __import__("cairo").Region(), 0, 0))
        self.win.show_all()

    def _closed(self, *_):
        """gtk-layer-shell turns the compositor's 'closed' (output removed) into a
        window close. Keep the object, stop drawing, and let the app rebuild."""
        if not self.dead:
            self.dead = True
            self.set_fps(0)
            log("surface closed by the compositor (output gone?)")
            GLib.idle_add(lambda: (self.app.heal_soon("surface closed"), False)[1])
        return True

    def _realize(self, area):
        area.make_current()
        if area.get_error():
            log("GL context error:", area.get_error())
            self.failed = True
            return
        # which renderer GTK's context got: a software one (no GPU) holds the layer still,
        # before the first frame builds the scene (live/software.py)
        try:
            name = GL.glGetString(GL.GL_RENDERER)
            self.app.on_gl_renderer(name.decode(errors="replace") if isinstance(name, bytes) else str(name or ""))
        except Exception as e:
            log("GL renderer unknown:", e)

    def _unrealize(self, area):
        try:
            area.make_current()            # the den TV frees its GL objects and mpv's render context
        except Exception:
            pass
        self._close_renderer()
        self.rsize = None

    def set_input(self, rects):
        """The window's input region: these logical rects take the pointer, the rest passes
        through (the background: the den TV's screens and its hint; none by default)."""
        w = self.win.get_window()
        if w is None:
            return
        import cairo
        w.input_shape_combine_region(cairo.Region([cairo.RectangleInt(*r) for r in rects]), 0, 0)

    def _close_renderer(self):
        """A world owns pollers (herdr, VECTOR's state); stop them with it."""
        r, self.renderer = self.renderer, None
        if r is not None and hasattr(r, "close"):
            try:
                r.close()
            except Exception:
                pass

    rsize = None

    def _render(self, area, ctx):
        if self.failed:
            GL.glClearColor(0, 0, 0, 0)
            GL.glClear(GL.GL_COLOR_BUFFER_BIT)
            return True
        sf = area.get_scale_factor()
        size = (area.get_allocated_width() * sf, area.get_allocated_height() * sf)
        if size[0] < 16 or size[1] < 16:
            return True
        if self.renderer is None or size != self.rsize:
            try:
                self._close_renderer()
                self.renderer = self.make_renderer(*size)
                self.rsize = size
            except Exception as e:
                import traceback
                traceback.print_exc()
                log("renderer init failed:", e)
                self.failed = True
                return True
        fbo = GL.glGetIntegerv(GL.GL_DRAW_FRAMEBUFFER_BINDING)
        if getattr(self.renderer, "sf", sf) != sf:
            self.renderer.sf = sf                  # the den TV's pointer: logical px
        self.frames += 1
        self.last_frame = time.monotonic()
        try:
            self.renderer.render(int(fbo), self.fps or 1)
        except Exception:
            import traceback
            traceback.print_exc()
            self.failed = True
            self.set_fps(0)
        return True

    def set_fps(self, fps):
        fps = 0 if self.failed else fps
        if fps and self.app.software:              # no GPU: the decks and overlays at a capped rate
            fps = min(fps, software.CAP_FPS)
        if fps == self.fps and (self.timer or not fps):
            return
        if self.timer:
            GLib.source_remove(self.timer)
            self.timer = None
        self.fps = fps
        if fps > 0:
            self.timer = GLib.timeout_add(max(int(1000 / fps), 8), self._tick, priority=GLib.PRIORITY_DEFAULT)
            self.area.queue_render()

    def _tick(self):
        self.ticks += 1
        self.area.queue_render()
        return True

    def destroy(self):
        self.set_fps(0)
        self.dead = True
        self._close_renderer()
        self.win.destroy()


class App:
    def __init__(self, login=False):
        self.cfg = config.load()
        self.gl_renderer = None            # GL_RENDERER, from the first window's context
        self.software = ""                 # that renderer, when it's software and holds the layer still
        self._apply_motion()
        self._still_timer = None
        self._still_last = 0.0             # when the last still frame was asked for
        self.monitor_setting = self.cfg["general"].get("monitor", "")     # the user's, as written
        self.cfg["general"]["monitor"] = hypr.resolve_monitor(self.monitor_setting)
        self.sound = Sound(self.cfg)
        self.data = Data(self.cfg, self.on_data_event)
        self.bg = None
        self.bg_enabled = bool(self.cfg["background"].get("enabled", True))
        self.bg_user_off = False           # SUPER+SHIFT+B / `toggle`: deliberate, never healed back on
        self.bg_fault = ""                 # why the background could not be created (retried with backoff)
        self.bg_tries = 0
        self.bg_retry_at = 0.0
        self.locked = False
        self.covered = False
        self.fullscreen = False
        self.overlays = {}
        self.cfg_mtime = self._mtime()
        self.data.start()
        from .codec import Desk
        self.codec = Desk(self)
        from .history import History, Recorder
        self.history = History()
        Recorder(self.data, self.history).start()
        self.history.event("start", "live layer started" + (" (login)" if login else ""))
        if self.bg_enabled:
            self.show_background()
        else:
            self.wallpaper_fallback()
        hypr.Events(lambda ev, arg: GLib.idle_add(self.on_hypr, ev, arg)).start()
        self.notif = Notifications(self.on_notify)
        self.notif.start()
        self.lockwatch = LockWatch(self.on_lock)
        self.lockwatch.start()
        from .lockemblem import LockEmblem
        self.lock_emblem = LockEmblem() if self.cfg["events"].get("lock_emblem", True) else None
        self._serve()
        GLib.timeout_add_seconds(3, self._watch_config)
        self.output_gone = False
        self.dpms = True
        self.measured = None
        self.stall_n = 0
        self._sample_at = (time.monotonic(), 0)
        self._heal_timers = []
        disp = Gdk.Display.get_default()
        disp.connect("monitor-added", lambda *_: self.heal_soon("output added"))
        disp.connect("monitor-removed", lambda *_: self.heal_soon("output removed", (0.3, 2.0)))
        GLib.timeout_add_seconds(5, self._sample)
        GLib.timeout_add_seconds(30, lambda: (self.heal("periodic check"), True)[1])
        GLib.idle_add(self.refresh_state)
        if login and self.cfg["events"].get("intercept_on_login", True):
            GLib.timeout_add(1200, lambda: (self.overlay("intercept"), False)[1])
        if login:                                  # a world's roll call, after the intercept
            GLib.timeout_add(5500, lambda: (self._world_event("login"), False)[1])

    def wallpaper_fallback(self):
        """Reconcile the still asynchronously; its socket query runs on this main loop."""
        import shutil
        import subprocess
        tool = shutil.which("bromigos-wallpaper")
        if tool:
            subprocess.Popen([tool, "apply"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    # ------------------------------------------------------------------ layers
    def show_background(self):
        """Create the background window. A failure is kept as a fault (status shows it) and
        retried by heal() with backoff (30 s, 60 s, 2 min, then every 5 min)."""
        if self.bg:
            return True
        from . import world

        def make(w, h):
            r = world.make_scene(self.cfg, self.data, w, h)   # the theme's world, or the Wick's den
            r.app = self
            return r
        self.world_sig = world.signature(self.cfg)
        try:
            self.bg = GLWindow(self, GtkLayerShell.Layer.BACKGROUND, "bromigos-live", make, input_ok=False)
            self._tv_events(self.bg)
        except Exception as e:
            self.bg = None
            self.bg_tries += 1
            self.bg_fault = f"{type(e).__name__}: {str(e)[:120]}"
            wait = (30, 60, 120, 300)[min(self.bg_tries - 1, 3)]
            self.bg_retry_at = time.monotonic() + wait
            log(f"background failed to start ({self.bg_fault}); retry {self.bg_tries} in {wait} s")
            import traceback
            traceback.print_exc()
            self.wallpaper_fallback()
            return False
        if self.bg_fault:
            log(f"background started after {self.bg_tries} failed attempt(s)")
        self.bg_fault, self.bg_tries, self.bg_retry_at = "", 0, 0.0
        self.wallpaper_active = True
        self.wallpaper_fallback()
        self.refresh_state()
        return True

    # ------------------------------------------------------------------ the den TV (live/tv.py)
    def den_tv(self):
        r = self.bg.renderer if self.bg and not self.bg.dead else None
        return getattr(r, "tv", None) if r is not None and not getattr(r, "is_world", False) else None

    def _tv_events(self, win):
        """The pointer over the den's screens: the background window's input region is
        only their rects (and the hint while it shows), so everywhere else clicks go through."""
        a = win.area
        a.add_events(Gdk.EventMask.POINTER_MOTION_MASK | Gdk.EventMask.ENTER_NOTIFY_MASK | Gdk.EventMask.BUTTON_PRESS_MASK
                     | Gdk.EventMask.BUTTON_RELEASE_MASK | Gdk.EventMask.SCROLL_MASK
                     | Gdk.EventMask.SMOOTH_SCROLL_MASK | Gdk.EventMask.LEAVE_NOTIFY_MASK)
        self._scroll_acc = 0.0

        def tv():
            return self.den_tv()

        def motion(_w, ev):
            t = tv()
            if t:
                t.pointer_motion(ev.x, ev.y)
                self._tv_redraw()
            return True

        def leave(_w, ev):
            t = tv()
            if t and ev.detail != Gdk.NotifyType.INFERIOR:
                t.pointer_leave()
                self._tv_redraw()
            return False

        def press(_w, ev):
            t = tv()
            if t and ev.type == Gdk.EventType.BUTTON_PRESS:
                out = t.click(ev.x, ev.y, ev.button)
                if out:
                    log(out)
                self._tv_redraw()
            return True

        def release(_w, ev):
            t = tv()
            if t:
                t.release()
            return True

        def scroll(_w, ev):
            t = tv()
            if not t:
                return False
            shift = bool(ev.state & Gdk.ModifierType.SHIFT_MASK)
            dy = dx = 0.0
            d = ev.direction
            if d in (Gdk.ScrollDirection.UP, Gdk.ScrollDirection.DOWN):
                dy = -1.0 if d == Gdk.ScrollDirection.UP else 1.0
            elif d in (Gdk.ScrollDirection.LEFT, Gdk.ScrollDirection.RIGHT):
                dx = -1.0 if d == Gdk.ScrollDirection.LEFT else 1.0
            elif d == Gdk.ScrollDirection.SMOOTH:
                ok, sdx, sdy = ev.get_scroll_deltas()
                if not ok:
                    return True
                self._scroll_acc += sdy
                self._scroll_acc_x = getattr(self, "_scroll_acc_x", 0.0) + sdx
                if abs(self._scroll_acc) >= 1.0:           # a touchpad: one step per notch's worth
                    dy, self._scroll_acc = (1.0 if self._scroll_acc > 0 else -1.0), 0.0
                elif abs(self._scroll_acc_x) >= 1.0:
                    dx, self._scroll_acc_x = (1.0 if self._scroll_acc_x > 0 else -1.0), 0.0
            if dy or dx:
                t.scroll(ev.x, ev.y, dy, shift, dx)
                self._tv_redraw()
            return True
        a.connect("motion-notify-event", motion)
        a.connect("enter-notify-event", motion)          # a pointer that lands without moving
        a.connect("leave-notify-event", leave)
        a.connect("button-press-event", press)
        a.connect("button-release-event", release)
        a.connect("scroll-event", scroll)
        if not getattr(self, "_tv_timer", None):
            self._tv_timer = GLib.timeout_add(500, self._tv_tick)

    def _tv_changed(self):
        """The den TV's channels or hint changed: its input region, and a frame."""
        GLib.idle_add(self._tv_region)

    def _tv_region(self):
        t = self.den_tv()
        if t and self.bg:
            rects = t.input_rects()
            if rects != getattr(self, "_tv_rects", None):
                self._tv_rects = rects
                self.bg.set_input(rects)
        self._tv_redraw()
        return False

    def _tv_redraw(self):
        """A frame now, for a still background (motion still, or no GPU) or a slow one."""
        if self.bg and not self.bg.dead and self.bg.fps == 0 and self.mode != "paused":
            self.bg.area.queue_render()

    def _tv_tick(self):
        t = self.den_tv()
        if t is None:
            return True
        if t.on_change is None:
            t.on_change = self._tv_changed
            self._tv_region()
        rects = {s: t.rects[s] for s, _ch in t.media_screens() if t.rects.get(s)}
        covered = set()
        if rects:
            now = time.monotonic()
            if now - getattr(self, "_tv_cov_at", 0.0) > 1.0:
                self._tv_cov_at = now
                try:
                    least = float(t.conf().get("cover_opacity", 0.9))
                except (TypeError, ValueError):
                    least = 0.9
                self._tv_cov = hypr.covered(self.cfg["general"]["monitor"], rects, least)
            covered = set(getattr(self, "_tv_cov", set())) & set(rects)
        saver = "screensaver" in self.overlays
        speaking = bool(getattr(self.codec, "current", None)) or _vector_speaking()
        t.tick(covered=covered, quiet=self.locked or saver, ducked=speaking, motion=motion.mode(self.cfg),
               software=bool(self.software))
        if t.hint_expired():
            self._tv_redraw()
        return True

    def hide_background(self):
        if self.bg:
            self.bg.destroy()
            self.bg = None

    def toggle_background(self):
        self.bg_enabled = not self.bg_enabled
        self.bg_user_off = not self.bg_enabled
        if self.bg_enabled:
            self.bg_fault, self.bg_tries, self.bg_retry_at = "", 0, 0.0     # the operator asked: try now
            self.show_background()
        else:
            self.hide_background()
            self.wallpaper_fallback()

    def _world_event(self, name, **info):
        """An event for the world, when one is drawn (the den takes rain bursts instead)."""
        r = self.bg.renderer if self.bg else None
        if r is not None and getattr(r, "is_world", False):
            r.event(name, **info)
            return True
        return False

    def check_world(self):
        """Theme switched (bromigos theme set → `theme` on the socket), or world.toml edited:
        rebuild the background as the new world or the den."""
        from . import world
        sig = world.signature(self.cfg)
        if sig != getattr(self, "world_sig", None) and self.bg_enabled:
            log("world changed:", sig[0] if sig else "none (the den)")
            self.hide_background()
            self.show_background()
            return "world " + (os.path.basename(os.path.dirname(os.path.dirname(sig[0]))) if sig else "none (the den)")
        return "ok"

    def overlay(self, kind, **kw):
        from . import overlays
        cur = self.overlays.get(kind)
        if cur and kind == "codec":
            return
        if cur and (kind in ("radial", "screensaver") or self.is_deck(kind)):
            cur.close()
            return
        if cur:
            cur.close()
        if self.is_deck(kind):
            # one hologram at a time: the next one takes over instead of stacking on top
            for other, ov in list(self.overlays.items()):
                if other != kind and self.is_deck(other):
                    ov.close()
        try:
            self.overlays[kind] = overlays.make(self, kind, **kw)
        except Exception:
            import traceback
            traceback.print_exc()
        self.refresh_state()

    # bromigOS's and the homelab's; a plugin folder's <kind>_deck.py is a deck too (decks.py)
    DECKS = ("holodeck", "driftmap", "timeline", "mind", "ops", "swarm", "netmap")

    @classmethod
    def is_deck(cls, kind):
        """A full-screen hologram (built in or a deck plugin), as opposed to the radial
        menu, notifications, the codec panel or the screensaver."""
        return kind in cls.DECKS or kind.startswith("plugin:") or cls.deck_module(kind)

    @staticmethod
    def deck_module(kind):
        """A <kind>_deck module exists: bromigOS's own, or a plugin folder's (live.PLUGINS)."""
        import importlib.util
        try:
            return kind.isidentifier() and importlib.util.find_spec(f"{__package__}.{kind}_deck") is not None
        except (ImportError, ValueError):
            return False

    def overlay_closed(self, kind, obj):
        if self.overlays.get(kind) is obj:
            del self.overlays[kind]
        self.refresh_state()

    # ------------------------------------------------------------------ self-healing (hotplug)
    def heal_soon(self, reason, delays=(1.5, 4.0, 9.0, 20.0)):
        """Outputs flap while a monitor powers up: check now-ish, then again a few times."""
        for t in self._heal_timers:
            if GLib.MainContext.default().find_source_by_id(t):
                GLib.source_remove(t)
        self._heal_timers = [GLib.timeout_add(int(d * 1000), self._heal_once, reason) for d in delays]
        return False

    def _heal_once(self, reason):
        self.heal(reason)
        self._notifier()
        return False

    def _notifier(self):
        """dunst can die when its output goes away; without it nothing (ours or anyone's)
        reaches the screen. Relaunch it if no one owns the notification name."""
        try:
            bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
            r = bus.call_sync("org.freedesktop.DBus", "/org/freedesktop/DBus", "org.freedesktop.DBus",
                              "NameHasOwner", GLib.Variant("(s)", ("org.freedesktop.Notifications",)),
                              None, Gio.DBusCallFlags.NONE, 2000, None)
            if r.unpack()[0] or self.output_gone:
                return
            import shutil
            if shutil.which("dunst"):
                hypr.dispatch('hl.dsp.exec_cmd("dunst")', "exec", "dunst")   # a child of Hyprland, not of us
                log("notification daemon was gone; relaunched dunst")
        except Exception as e:
            log("notifier check failed:", e)

    def _monitor_info(self):
        name = self.cfg["general"]["monitor"]
        return next((m for m in (hypr.request("monitors") or []) if m.get("name") == name), None)

    def surface_mapped(self, namespace="bromigos-live", level="0"):
        levels = hypr.layers_on(self.cfg["general"]["monitor"])
        return any(L.get("namespace") == namespace for L in (levels.get(level) or []))

    def heal(self, reason="", force=False):
        # hotplug: the output we're on went away and another is there, or the one asked for
        # came back: move (lib/bromigos_monitors decides which)
        cur = self.cfg["general"]["monitor"]
        best = hypr.resolve_monitor(getattr(self, "monitor_setting", ""))
        if best and best != cur and (self._monitor_info() is None or best == getattr(self, "monitor_setting", "")):
            log(f"output: {cur} -> {best} ({reason})")
            self.cfg["general"]["monitor"] = best
            if self.bg:
                self.bg.destroy()
                self.bg = None
            force = True
        info = self._monitor_info()
        if info is None:                           # the output is gone: drop what died with it
            if not self.output_gone:
                log(f"output {self.cfg['general']['monitor']} gone ({reason}); waiting for it")
            self.output_gone = True
            if self.bg:
                self.bg.destroy()
                self.bg = None
            for ov in list(self.overlays.values()):
                ov.finish() if hasattr(ov, "finish") else ov.close()
            return False
        if self.output_gone:
            log(f"output {info['name']} back (id {info.get('id')}, {reason})")
        self.output_gone = False
        self.dpms = bool(info.get("dpmsStatus", True))
        if not self.bg_enabled:
            return False
        if self.bg is None and self.bg_fault and time.monotonic() < self.bg_retry_at:
            return False                       # failed to start: wait out the backoff
        need = force or self.bg is None or self.bg.dead
        why = "forced" if force else ("no surface object" if (self.bg is None or self.bg.dead) else "")
        if not need and time.monotonic() - self.bg.created > 6 and not self.surface_mapped():
            need, why = True, "surface missing from the compositor"
        if need:
            log(f"healing ({reason}): {why}; recreating the background surface")
            if self.bg:
                self.bg.destroy()
                self.bg = None
            self.show_background()
        return False

    def _sample(self):
        """Every 5 s: measured frame rate, DPMS transitions, stall detection."""
        now = time.monotonic()
        bg = self.bg
        t0, f0 = self._sample_at
        frames = bg.frames if bg else 0
        self.measured = (frames - f0) / max(now - t0, 1e-3) if bg and frames >= f0 else None
        self._sample_at = (now, frames)
        info = self._monitor_info()
        dpms = bool(info.get("dpmsStatus", True)) if info else False
        if info and dpms and not self.dpms:
            self.heal_soon("display on (dpms)")
        if info and self.output_gone:
            self.heal_soon("output present again")
        self.dpms = dpms
        target = bg.fps if (bg and not bg.dead) else 0
        stalled = bool(target and dpms and not self.locked and self.measured is not None
                       and self.measured < 0.4 * target)
        self.stall_n = self.stall_n + 1 if stalled else 0
        if self.stall_n == 4:                      # 20 s stalled: is the surface still there?
            self.heal("stalled")
        elif self.stall_n >= 12 and not self.covered:
            self.heal("stalled for a minute with the desktop visible", force=True)
            self.stall_n = 0
        active = bool(self.bg_enabled and self.bg and not self.bg.dead and not self.bg.failed)
        if active != getattr(self, "wallpaper_active", active):
            self.wallpaper_fallback()
        self.wallpaper_active = active
        return True

    def health(self):
        """(surface state, fault or '') for status."""
        if self.output_gone:
            return "output gone (waiting for it)", ""
        if not self.bg_enabled:
            return "off", ""
        if not self.bg and self.bg_fault:
            left = max(0, int(self.bg_retry_at - time.monotonic()))
            return "FAILED", (f"background failed to start ({self.bg_fault}); attempt {self.bg_tries}, "
                              f"next try in {left} s")
        if not self.bg or self.bg.dead:
            return "MISSING", "no background surface"
        mapped = self.surface_mapped()
        if not mapped and time.monotonic() - self.bg.created > 6:
            return "MISSING", "surface not in the compositor's layers"
        if self.bg.fps and self.dpms and not self.locked and self.measured is not None \
                and self.measured < 0.4 * self.bg.fps:
            return ("mapped" if mapped else "mapping"), f"STALLED: {self.measured:.1f}/s against a {self.bg.fps} fps target"
        return ("mapped" if mapped else "mapping"), ""

    # ------------------------------------------------------------------ state
    mode = "starting"

    def refresh_state(self):
        windows, full, _mon = hypr.monitor_state(self.cfg["general"]["monitor"])
        self.covered, self.fullscreen = windows, full
        g = self.cfg["general"]
        own_full = [k for k in self.overlays if k == "screensaver" or self.is_deck(k)]
        if self.locked:
            mode, why = "paused", "session locked"
        elif full:
            mode, why = "paused", "fullscreen window"
        elif own_full:
            mode, why = "paused", f"{own_full[0]} on top"
        elif windows:
            mode, why = "idle", "windows tiled over it"
        else:
            mode, why = "running", "desktop visible"
        fps = 0 if mode == "paused" else int(g.get("fps_covered", 20) if mode == "idle" else g.get("fps", 30))
        self.data.paused = mode == "paused" and not own_full
        still = motion.mode(self.cfg) == "still" and mode != "paused"
        if still:
            fps = 0                                # a still frame, drawn again when it changes
        if self.bg and not self.bg.dead:
            self.bg.set_fps(fps)
        self._still(still)
        if (mode, why) != getattr(self, "_last_mode", None):
            log(f"{mode} ({why}) fps={fps if self.bg else 0}")
            self._last_mode = (mode, why)
        self.mode = mode
        return False

    # ------------------------------------------------------------------ no GPU (live/software.py)
    def on_gl_renderer(self, name):
        """The first GL context's renderer. A software one on a real machine holds the layer
        to a still frame, logged and notified once."""
        if self.gl_renderer is not None:
            return
        self.gl_renderer = name
        held, why = software.limited(name, self._allow_software(), software.in_vm())
        log(f"GL renderer: {name}" + (f" ({why})" if why else ""))
        if held:
            self._apply_motion()
            if not software.in_vm():               # a VM's software renderer isn't a fault
                software.notify_once(RUNTIME, name)
            GLib.idle_add(self.refresh_state)

    def _allow_software(self):
        return bool(self.cfg["general"].get("allow_software", False))

    def _apply_motion(self):
        """The motion in force: the user's, or "still" while a software renderer holds it."""
        held = bool(self.gl_renderer) and software.limited(self.gl_renderer, self._allow_software(),
                                                           software.in_vm())[0]
        self.software = self.gl_renderer if held else ""
        if held:
            self.cfg["general"]["motion"] = "still"
            self.cfg["general"]["reduced_motion"] = True
        motion.set_current(motion.mode(self.cfg))

    # ------------------------------------------------------------------ still (accessibility)
    def _still(self, on):
        """motion = "still" (live/motion.py): no frame timer; every STILL_CHECK s the scene says
        whether what it shows changed (or STILL_EVERY passed), and only then one frame."""
        if on and self._still_timer is None:
            self._still_timer = GLib.timeout_add(int(motion.STILL_CHECK * 1000), self._still_check)
            self._still_frame(force=True)
        elif not on and self._still_timer is not None:
            GLib.source_remove(self._still_timer)
            self._still_timer = None

    def _still_check(self):
        self._still_frame()
        return True

    def _still_frame(self, force=False):
        bg = self.bg
        r = bg.renderer if bg and not bg.dead else None
        if bg is None or bg.dead:
            return
        if r is None:                              # not drawn yet: the first frame makes it
            bg.area.queue_render()
            return
        # on a software renderer each frame loads the CPU, which itself changes the CPU reading
        # a still frame shows: at most one every STILL_MIN s there, or it redraws itself on and on
        if not force and self.software and time.monotonic() - self._still_last < software.STILL_MIN:
            return
        due = getattr(r, "still_due", None)
        if force or (due is not None and due()):
            tick = getattr(r, "still_tick", None)
            if tick is not None:
                tick()
            self._still_last = time.monotonic()
            bg.area.queue_render()

    def describe(self):
        bg = self.bg
        if not self.bg_enabled:
            mode = "off (toggled off: SUPER+SHIFT+B or bromigos-live toggle)" if self.bg_user_off \
                else "off (config: background.enabled = false)"
        else:
            mode = "waiting for the output" if self.output_gone else ("not started" if self.bg is None else self.mode)
        surface, fault = self.health()
        m = "--" if self.measured is None else f"{self.measured:.1f}/s"
        mo = motion.mode(self.cfg)
        out = [f"background {mode} target={bg.fps if bg else 0}fps measured={m} surface={surface}"
               + (f" · DPMS off" if not self.dpms else "") + (f" · motion {mo}" if mo != "full" else "")]
        if self.software:
            why = software.limited(self.software, False, software.in_vm())[1]
            out.append(f"NO GPU: the renderer is {self.software}, {why}")
        elif self.gl_renderer:
            out.append(f"renderer: {self.gl_renderer}")
        if fault:
            out.append("FAULT: " + fault + " (self-heal runs on hotplug, unlock, display-on and every 30 s)")
        if bg:
            out.append(f"frames={bg.frames} last_frame={time.monotonic() - bg.last_frame:.1f}s ago failed={bg.failed}")
        levels = hypr.layers_on(self.cfg["general"]["monitor"])
        ns = {}
        for lv in levels.values():
            for L in lv:
                ns[L.get("namespace")] = ns.get(L.get("namespace"), 0) + 1
        out.append("layers on " + self.cfg["general"]["monitor"] + ": " +
                   (", ".join(f"{k}×{v}" for k, v in sorted(ns.items())) or "none"))
        out.append(f"windows={self.covered} fullscreen={self.fullscreen} locked={self.locked} "
                   f"overlays={sorted(self.overlays)}")
        return "\n".join(out)

    def on_hypr(self, ev, arg):
        if ev in ("workspacev2", "fullscreen", "openwindow", "closewindow", "movewindowv2",
                  "focusedmon", "activespecial", "changefloatingmode", "monitoradded", "monitorremoved"):
            self.refresh_state()
        if ev in ("monitoradded", "monitoraddedv2"):
            self.heal_soon(f"monitor added: {arg}")
        elif ev in ("monitorremoved", "monitorremovedv2"):
            self.heal_soon(f"monitor removed: {arg}", (0.3, 2.0))
        if ev == "workspacev2" and self.bg:
            self.bg.renderer and self.bg.renderer.wipe()
        if ev in ("workspacev2", "activewindowv2", "openwindow", "focusedmon", "activespecial"):
            from .activity import get as activity
            activity().touch()
        if ev == "openwindow":
            parts = arg.split(",", 3)
            if len(parts) >= 3 and parts[2] in self.cfg["sounds"].get("terminal_classes", []):
                self.sound.play("terminal")
        return False

    def on_lock(self, locked):
        was = self.locked
        if locked != was:
            self.history.event("lock" if locked else "unlock")
        self.locked = locked
        from .activity import get as activity
        activity().set_locked(locked)
        le = getattr(self, "lock_emblem", None)
        if le:
            le.start(self.lockwatch.pid) if locked else le.stop()      # the turning burn-in on the lock screen
        if locked:
            for k in ("screensaver", "holodeck", "radial"):
                if k in self.overlays:
                    self.overlays[k].close()
        elif was:
            self.heal_soon("unlock", (1.0, 5.0))
            if self.cfg["events"].get("intercept_on_unlock", True):
                GLib.timeout_add(150, lambda: (self.overlay("intercept"), False)[1])
        self.refresh_state()
        return False

    def on_notify(self, what, a, b, c, quiet=False):
        if what == "notify":
            app_name, summary, urgency = a, b, c
            if app_name == "bromigos-live":
                return False
            quiet = quiet or app_name in self.cfg["sounds"].get("quiet_apps", [])
            self.history.event("critical" if urgency >= 2 else "notify",
                               f"{app_name}: {summary}" if urgency >= 2 else (app_name or "notification"))
            if not self._world_event("critical" if urgency >= 2 else "notify") and self.bg and self.bg.renderer:
                self.bg.renderer.burst(2 if urgency >= 2 else 0)
            if urgency >= 2 and self.cfg["events"].get("critical_flash", True) and not self.locked:
                if not quiet:
                    self.sound.play("critical")
                self.overlay("transmission", summary=summary)
                if self.cfg.get("codec", {}).get("on_critical", True):
                    who = app_name if app_name and app_name.lower() not in ("notify-send", "") else "the desk"
                    self.codec.offer("PRIORITY", f"Priority traffic from {who}: {summary}")
            elif not quiet:
                self.sound.play("notify")
        elif what == "closed":
            ov = self.overlays.get("transmission")
            if ov:
                ov.dismissed()
        return False

    def on_data_event(self, kind, **info):
        def go():
            if kind == "fill":
                self.history.event("fill", f"{info.get('n', 1)} paper fill(s)" +
                                   (" · notable" if info.get("notable") else ""))
            elif kind == "cluster_alert":
                self.history.event("lab", "node left Ready" if info.get("node_down")
                                   else f"alerts firing up to {int(info.get('count') or 0)}")
            world_ev = ("fill", {"results": info.get("results")}) if kind == "fill" else ("lab_alert", {})
            if not self._world_event(world_ev[0], **world_ev[1]) and self.bg and self.bg.renderer:
                self.bg.renderer.burst(1 if kind == "fill" else 2)
            cc = self.cfg.get("codec", {})
            # VECTOR explains lab alerts himself (holo/vector/briefing.py, through this codec channel);
            # while his daemon answers, the raw count call stands down
            if kind == "cluster_alert" and cc.get("on_lab_alert", True) and not _vector_alive():
                if info.get("node_down"):
                    self.codec.offer("LAB", "Lab here. A node dropped out of Ready. Check the cluster.")
                else:
                    self.codec.offer("LAB", f"Lab here. Alerts firing went up, now {int(info.get('count') or 0)}.")
            if kind == "fill" and cc.get("on_fill", True) and info.get("notable"):
                self.codec.offer("FLOOR", info["notable"])
            return False
        GLib.idle_add(go)

    # ------------------------------------------------------------------ control
    def _serve(self):
        try:
            os.unlink(SOCK)
        except OSError:
            pass
        srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        srv.bind(SOCK)
        srv.listen(4)

        def loop():
            while True:
                conn, _ = srv.accept()
                with conn:
                    try:
                        cmd = conn.recv(256).decode().strip()
                        done = threading.Event()
                        out = {}

                        def run():
                            out["r"] = self.command(cmd)
                            done.set()
                            return False
                        GLib.idle_add(run)
                        done.wait(3)
                        conn.sendall((out.get("r") or "ok").encode())
                    except OSError:
                        pass
        threading.Thread(target=loop, daemon=True, name="ctl").start()

    def command(self, cmd):
        c, _, arg = cmd.partition(" ")
        if c == "background-active":
            return "on" if self.bg_enabled and self.bg and not self.bg.dead and not self.bg.failed else "off"
        if c == "ping":
            return "pong"
        if c == "state":
            return self.describe()
        if c == "toggle":
            self.toggle_background()
            return "background " + ("on" if self.bg_enabled else "off")
        if c == "mute":
            return "muted" if toggle_mute() else "unmuted"
        if c in ("intercept", "holodeck", "driftmap", "timeline", "radial", "screensaver"):
            if c == "screensaver" and not self.cfg["screensaver"].get("enabled", True):
                return "screensaver disabled"
            verb = arg.strip()
            if verb in ("open", "close"):        # explicit (VECTOR's tour); no verb toggles, as the keys do
                cur = self.overlays.get(c)
                if verb == "open" and not cur:
                    self.overlay(c)
                elif verb == "close" and cur:
                    cur.close()
                return f"{c} {'open' if verb == 'open' else 'closed'}"
            self.overlay(c)
            return c
        if c == "screensaver-off":
            if "screensaver" in self.overlays:
                self.overlays["screensaver"].close()
            return "ok"
        if c == "plugin":                            # a deck plugin: bromigos-live plugin <name> [verb args]
            from .plugins import deck_names
            name, _, rest = arg.partition(" ")
            if name not in deck_names():
                return "plugins: " + " ".join(deck_names())
            kind = "plugin:" + name
            verb, _, vargs = rest.strip().partition(" ")
            cur = self.overlays.get(kind)
            r = getattr(cur, "renderer", None) if cur else None
            if verb == "close":
                if cur:
                    cur.close()
                return f"{name} closed"
            if not verb or verb == "open":
                if not cur:
                    self.overlay(kind)
                return f"{name} open"
            if r is not None and not r.done and hasattr(r, "command"):
                return r.command(verb, vargs.strip())
            self.overlay(kind, commands=[(verb, vargs.strip())])
            return f"{name} opening; {verb} queued"
        if c == "deck":
            kind, _, rest = arg.partition(" ")
            if not (kind in self.DECKS or self.deck_module(kind)) or kind in ("holodeck", "driftmap", "timeline"):
                from .decks import catalog
                return "decks: " + " ".join(d["kind"] for d in catalog() if self.deck_module(d["kind"]))
            verb, _, vargs = rest.strip().partition(" ")
            cur = self.overlays.get(kind)
            r = getattr(cur, "renderer", None) if cur else None
            if verb == "toggle":                  # the keys' and menu's (bromigos-live <kind>)
                self.overlay(kind)
                return f"{kind} {'closed' if cur else 'open'}"
            if not verb or verb == "open":
                if not cur:
                    self.overlay(kind)
                return f"{kind} open"
            if verb == "close":
                if cur:
                    cur.close()
                return f"{kind} closed"
            if r is not None and not r.done:
                return r.command(verb, vargs.strip())
            self.overlay(kind, commands=[(verb, vargs.strip())])      # open, then apply
            return f"{kind} opening; {verb} queued"
        if c == "codec":
            ch, _, text = arg.partition("|")
            if not text:
                ch, text = "DECK", ch
            return self.codec.offer(ch.strip().upper() or "DECK", text.strip(), force=False)
        if c == "codec-quiet":
            from .codec import toggle_quiet
            return "codec quiet (no voice)" if toggle_quiet() else "codec voice on"
        if c == "transmission":
            self.overlay("transmission", summary=arg or "TEST TRANSMISSION")
            return "ok"
        if c in ("scan", "scan-pin", "scan-hold"):
            r = self.bg.renderer if self.bg else None
            if not r:
                return "background off"
            if c == "scan":
                r.scan()
                return "scanning"
            if c == "scan-pin":
                return "schematic pinned" if r.scan_pin_toggle() else "schematic unpinned"
            r.scan_hold(arg.strip() != "off")
            return "hold " + ("off" if arg.strip() == "off" else "on")
        if c == "tv":                               # bromigos-live tv …: the den TV (live/tv.py)
            t = self.den_tv()
            if t is None:
                return "no den TV: the den isn't drawn (a world, or the background is off)"
            out = t.command(arg.strip())
            self._tv_redraw()
            return out
        if c == "theme":                            # bromigos theme set: the world may have changed
            return self.check_world()
        if c == "world":                            # bromigos-live ctl world [state|event …|set …|clear|rollcall]
            r = self.bg.renderer if self.bg else None
            if r is None or not getattr(r, "is_world", False):
                return "no world: the current theme has none (the Wick's den is drawn)"
            verb, _, rest = arg.strip().partition(" ")
            return r.command(verb, rest.strip())
        if c == "activity":                         # hypridle: activity idle|active
            from .activity import get as activity
            return "activity " + activity().hypridle_says(arg.strip() or "active")
        if c == "burst":
            if self.bg and self.bg.renderer:
                self.bg.renderer.burst(int(arg or 0))
            return "ok"
        if c == "reload":
            self.reload()
            return "reloaded"
        if c == "quit":
            Gtk.main_quit()
            return "bye"
        return "unknown command"

    def _mtime(self):
        """The packaged and the user's config.toml and the overrides file: a change to any reloads."""
        m = []
        for p in (config.PACKAGED, config.USER, config.OVERRIDES_NEW, config.OVERRIDES_OLD, config.A11Y):
            try:
                m.append(os.path.getmtime(p))
            except OSError:
                m.append(0)
        return tuple(m)

    def _watch_config(self):
        m = self._mtime()
        if m != self.cfg_mtime:
            self.cfg_mtime = m
            self.reload()
        elif self.bg:
            self.check_world()
        return True

    def reload(self):
        self.cfg_mtime = self._mtime()             # a socket reload: the watcher needn't again
        new = config.load()
        self.monitor_setting = new["general"].get("monitor", "")
        new["general"]["monitor"] = hypr.resolve_monitor(self.monitor_setting)
        t = self.den_tv()
        if t is not None and {k: v for k, v in new.items() if k != "tv"} == {k: v for k, v in self.cfg.items()
                                                                             if k != "tv"}:
            # only the den TV's channels changed (the channel guide): no new background, no
            # player closed; the screens carry on and the lists are read again
            self.cfg["tv"] = new.get("tv") or {}
            t.reconfigured()
            log("config: the den TV's channels changed; read again")
            return
        self.cfg.clear()
        self.cfg.update(new)
        self._apply_motion()
        self._still(False)                         # refresh_state starts it again if still
        if self.bg:
            self.hide_background()
        self.bg_enabled = bool(self.cfg["background"].get("enabled", True)) and not self.bg_user_off
        if self.bg_enabled:
            self.show_background()
        else:
            self.wallpaper_fallback()


QUIT = threading.Event()        # SIGTERM: quit, whether the main loop runs yet or not


def _on_term(*_):
    QUIT.set()
    if Gtk.main_level() > 0:
        GLib.idle_add(Gtk.main_quit)


def main():
    login = "--login" in sys.argv
    signal.signal(signal.SIGINT, signal.SIG_DFL)
    signal.signal(signal.SIGTERM, _on_term)
    # one daemon per user: the lock is held for this process's life (live/instance.py);
    # another daemon running (or starting) keeps it, and this one leaves
    from . import instance
    lock = instance.acquire()
    if lock is None:
        held = instance.read(instance.LOCK)
        log(f"another live daemon runs (PID {held[0] if held else '?'}); not starting a second")
        sys.exit(instance.TAKEN)
    wait_for_display()
    if QUIT.is_set():
        return
    app = App(login=login)
    if not QUIT.is_set():           # a SIGTERM during start-up isn't lost: it never runs the loop
        Gtk.main()
    try:
        app.history.save()
    except Exception:
        pass
    try:
        os.unlink(SOCK)
    except OSError:
        pass


if __name__ == "__main__":
    main()
