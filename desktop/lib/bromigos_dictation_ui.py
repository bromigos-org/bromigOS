"""A non-interactive top-centre dictation layer, and its session-local controller."""
import collections
import fcntl
import json
import math
import os
import queue
import signal
import socket
import threading
import time

import bromigos_dictation as D


def draw_meter(cr, width, height, state, levels, clock=0, reduced=False):
    """Shared by the real overlay and the offscreen picture tool."""
    import bromigos_theme as T

    def colour(role, alpha=1):
        cr.set_source_rgba(*T.rgb(role), alpha)

    cx, cy = 30, height / 2
    active = state == "listening"
    colour("primary", .14)
    cr.arc(cx, cy, 24, 0, math.tau)
    cr.fill()
    colour("primary", .85)
    cr.set_line_width(1.5)
    if not reduced:
        angle = clock * .7
        cr.arc(cx, cy, 22, angle, angle + math.pi * 1.45)
        cr.stroke()
    else:
        cr.arc(cx, cy, 22, 0, math.tau)
        cr.stroke()
    # Microphone, drawn as paths so it needs no glyph or bitmap asset.
    cr.set_line_width(2)
    cr.move_to(cx - 4, cy - 7)
    cr.curve_to(cx - 4, cy - 13, cx + 4, cy - 13, cx + 4, cy - 7)
    cr.line_to(cx + 4, cy + 1)
    cr.curve_to(cx + 4, cy + 7, cx - 4, cy + 7, cx - 4, cy + 1)
    cr.close_path()
    cr.stroke()
    cr.arc(cx, cy + 1, 8, 0, math.pi)
    cr.stroke()
    cr.move_to(cx, cy + 9)
    cr.line_to(cx, cy + 13)
    cr.move_to(cx - 4, cy + 13)
    cr.line_to(cx + 4, cy + 13)
    cr.stroke()
    cr.select_font_face("Geist Mono", 0, 1)
    cr.set_font_size(11)
    colour("soft")
    label = {"listening": "DICTATING", "finishing": "FINISHING", "inserting": "INSERTING",
             "error": "TRY AGAIN"}.get(state, "DICTATION")
    cr.move_to(65, cy - 6)
    cr.show_text(label)
    cr.set_font_size(9)
    colour("muted")
    cr.move_to(65, cy + 10)
    cr.show_text("VOICE TO TEXT")
    left, right = 190, width - 14
    count = 36
    step = max(3, (right - left) / count)
    samples = list(levels)[-count:]
    samples = [0] * (count - len(samples)) + samples
    cr.set_line_width(max(2, step * .4))
    cr.set_line_cap(1)
    for i, level in enumerate(samples):
        value = level if active else (.2 + .15 * math.sin(clock * 3 + i * .4) if not reduced else .15)
        extent = 2 + min(1, value) * (height * .34)
        colour("primary", .28 + min(1, value) * .65)
        x = left + i * step
        cr.move_to(x, cy - extent / 2)
        cr.line_to(x, cy + extent / 2)
        cr.stroke()


def gtk():
    from ctypes import CDLL
    CDLL("libgtk4-layer-shell.so")
    import gi
    gi.require_version("Gtk", "4.0")
    gi.require_version("Gtk4LayerShell", "1.0")
    from gi.repository import Gdk, GLib, Gtk, Gtk4LayerShell as LS, Pango
    return Gtk, Gdk, GLib, LS, Pango


class Overlay:
    def __init__(self, app, modules):
        self.Gtk, self.Gdk, self.GLib, self.LS, Pango = modules
        Gtk, Gdk, GLib, LS = self.Gtk, self.Gdk, self.GLib, self.LS
        import bromigos_theme as T
        self.state = "listening"
        self.levels = collections.deque([0] * 36, maxlen=36)
        self.motion = T.motion()
        self.win = Gtk.ApplicationWindow(application=app)
        self.win.set_title("Dictation")
        self.win.set_decorated(False)
        self.win.set_resizable(False)
        self.win.add_css_class("dictation-window")
        if not LS.is_supported():
            raise D.DictationError("This session does not support the dictation overlay")
        LS.init_for_window(self.win)
        LS.set_namespace(self.win, "bromigos-dictation")
        LS.set_layer(self.win, LS.Layer.OVERLAY)
        LS.set_keyboard_mode(self.win, LS.KeyboardMode.NONE)
        LS.set_anchor(self.win, LS.Edge.TOP, True)
        LS.set_margin(self.win, LS.Edge.TOP, 48)
        LS.set_exclusive_zone(self.win, 0)
        frame = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        frame.add_css_class("dictation-card")
        self.win.set_child(frame)
        self.meter = Gtk.DrawingArea()
        self.meter.set_content_width(550)
        self.meter.set_content_height(64)
        self.meter.set_draw_func(self._draw)
        frame.append(self.meter)
        self.transcript = Gtk.Label(xalign=0)
        self.transcript.set_wrap(True)
        self.transcript.set_wrap_mode(Pango.WrapMode.WORD_CHAR)
        self.transcript.set_max_width_chars(62)
        self.transcript.set_lines(3)
        self.transcript.set_ellipsize(Pango.EllipsizeMode.END)
        self.transcript.add_css_class("dictation-text")
        frame.append(self.transcript)
        self.hint = Gtk.Label(label="Release to insert", xalign=0)
        self.hint.add_css_class("dictation-hint")
        frame.append(self.hint)
        self.provider = Gtk.CssProvider()
        self.theme_version = None
        self._theme()
        Gtk.StyleContext.add_provider_for_display(Gdk.Display.get_default(), self.provider,
                                                 Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
        self.win.connect("realize", self._passthrough)
        self.animate = GLib.timeout_add(33, self._tick)

    def _theme(self):
        import bromigos_theme as T
        version = T.version(0)
        if version == self.theme_version:
            return
        self.theme_version = version
        self.motion = T.motion()
        self.provider.load_from_data((
            "window.dictation-window { background: transparent; }"
            ".dictation-card { padding: 10px 18px 16px; border-radius: 18px; border: 1px solid "
            + T.hex("primary") + "; background: " + T.hex("panel") + "; }"
            ".dictation-text { color: " + T.hex("text") + "; font-family: Sans; font-size: 17px;"
            " min-height: 42px; } .dictation-hint { color: " + T.hex("muted")
            + "; font-family: Geist Mono; font-size: 10px; margin-top: 6px; }").encode())

    def _passthrough(self, *_):
        import cairo
        self.win.get_surface().set_input_region(cairo.Region())

    def _tick(self):
        if self.win.get_visible():
            self._theme()
            if self.motion == "full":
                self.meter.queue_draw()
        return True

    def _draw(self, _area, cr, width, height):
        draw_meter(cr, width, height, self.state, self.levels, time.monotonic(), self.motion != "full")

    def show(self):
        # Place on the focused app's monitor, rather than changing focus to the pointer's.
        try:
            import subprocess
            p = subprocess.run(["hyprctl", "monitors", "-j"], capture_output=True, text=True, timeout=2)
            name = next((m["name"] for m in json.loads(p.stdout) if m.get("focused")), None)
            monitors = self.Gdk.Display.get_default().get_monitors()
            for i in range(monitors.get_n_items()):
                monitor = monitors.get_item(i)
                if monitor.get_connector() == name:
                    self.LS.set_monitor(self.win, monitor)
                    break
        except (OSError, ValueError, KeyError, StopIteration, subprocess.TimeoutExpired):
            pass
        self._theme()
        self.levels.clear()
        self.win.set_visible(True)

    def update(self, state, text, level):
        self.state = state
        self.levels.append(level)
        if state != "error" and len(text) > 180:
            text = "… " + text[-180:].split(" ", 1)[-1]
        self.transcript.set_text(text or ("Speak naturally. Your words will appear here." if state == "listening"
                                         else "Finishing your words…"))
        self.hint.set_text({"listening": "Release to insert", "finishing": "Preparing your text…",
                           "inserting": "Inserting at your cursor…", "error": "Dictation stopped"}.get(state, ""))
        self.meter.queue_draw()

    def hide(self):
        self.win.set_visible(False)


class Controller:
    def __init__(self, modules):
        Gtk, _Gdk, GLib, _LS, _Pango = modules
        self.GLib, self.modules = GLib, modules
        self.path = D.runtime()
        self.lock = open(os.path.join(self.path, "server.lock"), "a")
        fcntl.flock(self.lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        self.socket_path = os.path.join(self.path, "control.sock")
        self.closed = threading.Event()
        self.session = None
        self.generation, self.hide_timer = 0, None
        self.last_command = time.monotonic()
        from gi.repository import Gio
        self.app = Gtk.Application(application_id="org.bromigos.Dictation",
                                   flags=Gio.ApplicationFlags.NON_UNIQUE)
        self.app.connect("activate", self.activate)

    def activate(self, app):
        self.overlay = Overlay(app, self.modules)
        self.app.hold()
        self.listener = socket.socket(socket.AF_UNIX)
        if os.path.exists(self.socket_path):
            os.unlink(self.socket_path)
        self.listener.bind(self.socket_path)
        os.chmod(self.socket_path, 0o600)
        self.listener.listen(8)
        self.listener.settimeout(1)
        threading.Thread(target=self._listen, daemon=True, name="dictation-control").start()
        self.GLib.timeout_add_seconds(5, self._idle)
        signal.signal(signal.SIGTERM, lambda *_: self.GLib.idle_add(self.app.quit))

    def _idle(self):
        if (self.session is None or self.session.finished.is_set()) and time.monotonic() - self.last_command > 120:
            self.app.quit()
            return False
        return True

    def _listen(self):
        while not self.closed.is_set():
            try:
                connection, _ = self.listener.accept()
            except socket.timeout:
                continue
            except OSError:
                return
            with connection:
                connection.settimeout(5)
                try:
                    raw = connection.recv(1024)
                    request = json.loads(raw)
                    response = queue.Queue(maxsize=1)
                    self.GLib.idle_add(self._command, request.get("command"), response)
                    connection.sendall((json.dumps(response.get(timeout=5)) + "\n").encode())
                except (OSError, ValueError, queue.Empty):
                    pass

    def _command(self, command, response):
        self.last_command = time.monotonic()
        try:
            if command == "on":
                if self.session and not self.session.finished.is_set():
                    response.put({"ok": True, "state": self.session.state, "pid": os.getpid()})
                    return False
                self.generation += 1
                generation = self.generation
                if self.hide_timer is not None:
                    self.GLib.source_remove(self.hide_timer)
                    self.hide_timer = None
                self.overlay.show()
                self.session = D.Session(D.Backend(self.path), D.insert_text,
                    lambda state, text, level: self.GLib.idle_add(self._event, generation, state, text, level),
                    D.focused_window())
                self.session.start()
            elif command == "off":
                if self.session:
                    self.session.release()
            elif command == "cancel":
                self.generation += 1
                if self.session:
                    self.session.cancel()
                self.overlay.hide()
            elif command != "status":
                raise D.DictationError("Use on, off, cancel or status")
            state = self.session.state if self.session and not self.session.finished.is_set() else "idle"
            response.put({"ok": True, "state": state, "pid": os.getpid(),
                          "level": round(self.session.level, 3) if self.session else 0,
                          "characters": len(self.session.text) if self.session else 0})
        except D.DictationError as error:
            self._event(self.generation, "error", str(error), 0)
            response.put({"ok": False, "error": str(error)})
        except Exception:
            self._event(self.generation, "error", "Dictation could not start", 0)
            response.put({"ok": False, "error": "Dictation could not start"})
        return False

    def _event(self, generation, state, text, level):
        if generation != self.generation:
            return False
        if state == "done":
            self.overlay.hide()
        else:
            self.overlay.update(state, text, level)
            if state == "error":
                self.hide_timer = self.GLib.timeout_add(3500, self._hide_error, generation)
        return False

    def _hide_error(self, generation):
        if generation == self.generation:
            self.overlay.hide()
        self.hide_timer = None
        return False

    def run(self):
        try:
            self.app.run([])
        finally:
            self.closed.set()
            if self.session:
                self.session.cancel()
                self.session.recorder.finish()
            if hasattr(self, "listener"):
                self.listener.close()
            if os.path.exists(self.socket_path):
                os.unlink(self.socket_path)
            self.lock.close()


def serve():
    modules = gtk()
    Controller(modules).run()
