"""The "press the new shortcut" window of `bromigos keys` (package bromigos-desktop,
/usr/lib/bromigos/lib): GTK 4 on a layer-shell surface (gtk4-layer-shell), in the
theme's colours, with every part explaining itself on hover.

It shows the keys live as they're held. Letting go saves them after a short beat (the bar
drains; Enter saves at once), Backspace clears, Esc cancels. Enter, Backspace and Esc
alone are the window's own; with a modifier they're keys like any other. 30 seconds
without a key cancels.

While it listens, Hyprland's own binds must not fire (SUPER + Q would close a window
instead of being captured), so Hyprland goes into the `bromigos-capture` submap, which
binds nothing but Esc (hypr/bromigos/binds.lua; defined at run time if the running config
predates it). Every key then reaches the window. Nothing can leave you stuck in it:
  - Esc in the submap always leaves it (and reaches the window, which cancels);
  - the window leaves it on every way out (saved, cancelled, timed out, a signal);
  - a watchdog process leaves it if the window dies some other way (killed, crashed);
  - Hyprland's own timer leaves it after a minute, whatever happened to both;
  - Hyprland refuses to enter a submap that doesn't exist, so an old config can't strand you.

  run(what, current=None) -> {"keys": "SUPER + SHIFT + W", …} or None (cancelled)
  render(path, what, …)   draws the window to a PNG (tests, docs); needs a Wayland display,
                          not Hyprland
"""
import json
import os
import secrets
import signal
import socket
import subprocess
import sys
import threading

HERE = os.path.dirname(os.path.realpath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import bromigos_hypr as H  # noqa: E402
import bromigos_keys as BK  # noqa: E402

SUBMAP = BK.SUBMAP
LIMIT = 30              # seconds without a key, then it cancels
SETTLE = 1.2            # seconds between letting go and saving
HYPR_LIMIT_MS = 60000   # Hyprland's own timer: out of the submap after a minute, whatever happens
DEFINE = ('hl.define_submap("%s", function() hl.bind("ESCAPE", function() '
          'hl.dispatch(hl.dsp.submap("reset")) end, { non_consuming = true, '
          'description = "Leave the shortcut capture" }) end)' % SUBMAP)

MODS = {"Super_L": "SUPER", "Super_R": "SUPER", "Meta_L": "SUPER", "Meta_R": "SUPER",
        "Hyper_L": "SUPER", "Hyper_R": "SUPER", "Alt_L": "ALT", "Alt_R": "ALT",
        "Control_L": "CTRL", "Control_R": "CTRL", "Shift_L": "SHIFT", "Shift_R": "SHIFT"}
GHOST = "KEY"           # the dashed keycap still to be pressed
# Held for typing, not binding (AltGr, the locks): passed over.
PASSED = {"ISO_Level3_Shift", "ISO_Level5_Shift", "Mode_switch", "Caps_Lock", "Num_Lock",
          "Scroll_Lock", "ISO_Next_Group", "ISO_Prev_Group"}

# The Wick's colours, for a desktop with no theme set yet.
WICK = {"background": "#000500", "void": "#000500", "panel": "#001300", "selection": "#003b00",
        "primary": "#39ff14", "soft": "#9cff8a", "dim": "#159b09", "text": "#c4f5bb",
        "muted": "#7e927e", "faint": "#4e6b4e", "warn": "#d4af37", "danger": "#ff766f",
        "white": "#e8ffe0"}


def palette():
    """(the theme's colours, high contrast on): bromigos_theme's (bromigos-core), else
    palette.json read here, else the Wick's."""
    for p in (os.path.join(HERE, "..", "..", "lib"), "/usr/lib/bromigos/lib"):
        if os.path.isdir(p) and p not in sys.path:
            sys.path.append(p)
    try:
        import bromigos_theme as T
        got, hc = T.colors(), T.high_contrast()
    except Exception:
        got, hc = H.palette(), False
    out = dict(WICK)
    out.update({k: v for k, v in got.items() if isinstance(v, str) and v.startswith("#")})
    return out, hc


def css(p, high_contrast=False):
    colours = "".join(f"@define-color bk_{k} {v};\n" for k, v in p.items())
    # opaque (the window opens over others: nothing may show through the keys); high
    # contrast (docs/accessibility.md): a solid 2 px frame
    frame = ("background-color: @bk_panel; border: 2px solid @bk_soft;" if high_contrast else
             "background-color: @bk_panel; border: 1px solid @bk_dim;")
    return colours + """
window.bromigos-keys { background: transparent; }
.bk-frame { """ + frame + """
            padding: 20px 26px 16px 26px; min-width: 560px; }
.bk-eyebrow { color: @bk_primary; font-family: "Geist Mono"; font-weight: 700; font-size: 11px;
              letter-spacing: 3px; }
.bk-for { color: @bk_muted; font-family: "Geist Mono"; font-size: 11px; }
.bk-title { color: @bk_white; font-family: "Geist Mono"; font-size: 21px; font-weight: 600;
            margin-top: 10px; }
.bk-now { color: @bk_muted; font-family: "Geist Mono"; font-size: 12px; margin-top: 2px; }
.bk-caps { min-height: 58px; margin-top: 16px; margin-bottom: 12px; }
.bk-cap { background-color: @bk_selection; color: @bk_soft; border: 1px solid @bk_dim;
          border-bottom: 2px solid @bk_primary; padding: 8px 14px; font-family: "Geist Mono";
          font-size: 18px; font-weight: 600; letter-spacing: 1px; }
.bk-cap.bk-ghost { background-color: transparent; color: @bk_faint; border-color: @bk_faint;
                   border-style: dashed; }
.bk-plus { color: @bk_muted; font-family: "Geist Mono"; font-size: 16px; margin-left: 8px;
           margin-right: 8px; }
.bk-status { color: @bk_text; font-family: "Geist Mono"; font-size: 12px; }
.bk-status.bk-warn { color: @bk_warn; }
progressbar.bk-bar > trough { background-color: @bk_selection; background-image: none; border: none;
                              min-height: 3px; border-radius: 0; box-shadow: none; }
progressbar.bk-bar > trough > progress { background-color: @bk_dim; background-image: none; border: none;
                                         min-height: 3px; min-width: 0; margin: 0; border-radius: 0;
                                         box-shadow: none; }
progressbar.bk-bar.bk-settle > trough > progress { background-color: @bk_primary; }
progressbar.bk-bar { margin-top: 10px; margin-bottom: 12px; }
button.bk-btn { background: transparent; color: @bk_soft; border: 1px solid @bk_dim; border-radius: 0;
                box-shadow: none; font-family: "Geist Mono"; font-size: 11px; font-weight: 600;
                letter-spacing: 2px; padding: 3px 14px; min-height: 0; }
button.bk-btn:hover { border-color: @bk_primary; color: @bk_primary; }
button.bk-btn:disabled { color: @bk_faint; border-color: @bk_faint; }
popover.background, tooltip { background-color: @bk_void; color: @bk_soft; border: 1px solid @bk_dim;
                              border-radius: 0; }
tooltip label { color: @bk_soft; font-family: "Geist Mono"; font-size: 12px; }
"""


def load_gtk():
    """(Gtk, Gdk, GLib, Gtk4LayerShell or None). gtk4-layer-shell has to be loaded before
    libwayland-client, so this comes before anything else imports GTK."""
    from ctypes import CDLL
    try:
        CDLL("libgtk4-layer-shell.so")
    except OSError:
        pass
    import gi
    gi.require_version("Gtk", "4.0")
    gi.require_version("Gdk", "4.0")
    try:
        gi.require_version("Gtk4LayerShell", "1.0")
        from gi.repository import Gtk4LayerShell as LS
    except (ValueError, ImportError):
        LS = None
    from gi.repository import Gdk, GLib, Gtk
    return Gtk, Gdk, GLib, LS


def keyname(key):
    kb = BK.keybinds()
    return kb.keyname(key) if kb else key.upper()


# ------------------------------------------------------------------ Hyprland's binds held back
class Suppress:
    """Hyprland in the capture submap while the window listens (see the module's doc)."""

    def __init__(self, hypr=None):
        self.hypr = hypr or BK.Hypr()
        self.token = None
        self.active = False

    def _defined(self):
        try:
            raw = json.loads(self.hypr.run("binds", "-j") or "[]")
        except ValueError:
            return False
        return any(b.get("submap") == SUBMAP for b in raw)

    def enter(self):
        """(ok, why): in the submap, with the watchdog and Hyprland's timer set."""
        if not self.hypr.running():
            return False, "no running Hyprland"
        if not self._defined():                 # a config from before the picker: define it now
            self.hypr.eval(DEFINE)
        if not self._defined():
            return False, "Hyprland wouldn't define the capture submap"
        self.token = secrets.token_hex(8)
        self.hypr.eval(f'bromigos_capture_token = "{self.token}"; hl.timer(function() '
                       f'if bromigos_capture_token == "{self.token}" and hl.get_current_submap() == "{SUBMAP}" '
                       f'then hl.dispatch(hl.dsp.submap("reset")) end end, '
                       f'{{ timeout = {HYPR_LIMIT_MS}, type = "oneshot" }})')
        self._watchdog()
        out = self.hypr.run("dispatch", f'hl.dsp.submap("{SUBMAP}")')
        if self.hypr.run("submap") != SUBMAP:
            self.leave()
            return False, out or "Hyprland didn't enter the capture submap"
        self.active = True
        return True, ""

    def _watchdog(self):
        """A process that outlives this one: when it's gone and Hyprland is still in the
        submap (with this capture's token, or none: a reload cleared it), leave it."""
        script = (
            'while kill -0 "$1" 2>/dev/null; do sleep 0.3; done; '
            'if [ "$(hyprctl submap 2>/dev/null)" = "' + SUBMAP + '" ]; then '
            't="$(hyprctl repl "return bromigos_capture_token" 2>/dev/null)"; '
            'case "$t" in "$2"|""|nil|*rror*) hyprctl dispatch \'hl.dsp.submap("reset")\' >/dev/null 2>&1;; esac; '
            'fi')
        try:
            subprocess.Popen(["sh", "-c", script, "bromigos-keys-watchdog", str(os.getpid()), self.token],
                             env=self.hypr.env, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                             stderr=subprocess.DEVNULL, start_new_session=True)
        except OSError:
            pass

    def leave(self):
        if self.hypr.running() and self.hypr.run("submap") == SUBMAP:
            self.hypr.run("dispatch", 'hl.dsp.submap("reset")')
        self.active = False

    def watch(self, on_left):
        """Call on_left() (in a thread) when Hyprland leaves the submap for any reason."""
        env = self.hypr.env
        sig = env.get("HYPRLAND_INSTANCE_SIGNATURE")
        run = env.get("XDG_RUNTIME_DIR") or f"/run/user/{os.getuid()}"
        path = os.path.join(run, "hypr", sig or "", ".socket2.sock")

        def loop():
            try:
                s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
                s.connect(path)
            except OSError:
                return
            buf = b""
            while True:
                try:
                    chunk = s.recv(4096)
                except OSError:
                    return
                if not chunk:
                    return
                buf += chunk
                while b"\n" in buf:
                    line, buf = buf.split(b"\n", 1)
                    ev, _, data = line.decode(errors="replace").partition(">>")
                    if ev == "submap" and data != SUBMAP and self.active:
                        on_left()
                        return

        threading.Thread(target=loop, daemon=True).start()


# ------------------------------------------------------------------ the keys, without a window
class Keys:
    """What the capture window does with each key, apart from GTK (so it can be tested):
    press()/release() take the key's unmodified name (as Hyprland matches binds) and its
    keycode; press() and tick() answer None, "cancel", "confirm" or "timeout"."""

    def __init__(self, limit=LIMIT, settle=SETTLE):
        self.limit, self.settle = limit, settle
        self.held = {}              # keycode -> SUPER | ALT | CTRL | SHIFT
        self.down = set()           # keycodes of other keys held
        self.combo = None           # (mods, KEY, keycode) of the last key pressed
        self.phase = "listen"       # listen | hold | settle | done
        self.note = None            # a warning in place of the status line
        self.left = limit           # seconds before it gives up
        self.settle_t = 0.0         # seconds before a released combo saves

    def mods(self):
        return [m for m in BK.MOD_ORDER if m in self.held.values()]

    def shown(self):
        """(keys, complete): the keys to show, and whether they make a shortcut yet."""
        if self.combo is not None:
            mods, key, _ = self.combo
            return list(mods) + [key], True
        return self.mods(), False

    def press(self, name, keycode):
        if self.phase == "done":
            return None
        if keycode in self.down or keycode in self.held:
            return None                             # key repeat
        self.note = None
        self.left = self.limit
        mod = MODS.get(name or "")
        if mod:
            self.held[keycode] = mod
            if self.phase in ("listen", "settle"):
                self.combo = None
            self.phase = "hold"
            return None
        if name in PASSED:
            return None
        mods = self.mods()
        if not mods and name == "Escape":
            return "cancel"
        if not mods and name in ("Return", "KP_Enter"):
            if self.combo is not None and self.phase == "settle":
                return "confirm"
            self.note = "Enter alone is how you save: hold a modifier with it to bind it."
            return None
        if not mods and name == "BackSpace":
            self.clear()
            return None
        key = name.upper() if name else f"code:{keycode}"
        self.down.add(keycode)
        self.combo = (tuple(mods), key, keycode)
        self.phase = "hold"
        return None

    def release(self, keycode):
        if self.phase == "done":
            return
        self.held.pop(keycode, None)
        self.down.discard(keycode)
        if not self.held and not self.down and self.phase == "hold":
            if self.combo is not None:
                self.phase = "settle"
                self.settle_t = self.settle
            else:
                self.phase = "listen"

    def clear(self):
        if self.phase == "done":
            return
        self.combo, self.phase, self.note = None, "listen", None
        self.held.clear()
        self.down.clear()
        self.left = self.limit

    def tick(self, dt):
        if self.phase == "settle":
            self.settle_t -= dt
            if self.settle_t <= 0:
                return "confirm"
        elif self.phase != "done" and not self.held and not self.down:
            self.left -= dt
            if self.left <= 0:
                return "timeout"
        return None

    def result(self):
        """The combo as `bromigos keys` takes it, or raises BadKeys."""
        mods, key, keycode = self.combo
        c = BK.Combo.parse(" + ".join(list(mods) + [key]), keycode=keycode)
        return {"keys": str(c), "display": c.display(), "mods": list(c.mods), "key": c.key, "keycode": keycode}


# ------------------------------------------------------------------ the window
class Capture:
    def __init__(self, Gtk, Gdk, GLib, LS, what, current=None, limit=LIMIT, suppress=None):
        self.Gtk, self.Gdk, self.GLib, self.LS = Gtk, Gdk, GLib, LS
        self.what, self.current, self.limit = what, current, limit
        self.suppress = suppress
        self.k = Keys(limit)
        self.result = None
        self.loop = None
        self.why = None             # why it was cancelled
        self._ctrl_event = None
        self._shown = None          # the keycaps on screen (rebuilt only when they change)
        self._build()

    # -- the widgets
    def _build(self):
        Gtk = self.Gtk
        self.win = Gtk.Window(title="Shortcut")
        self.win.add_css_class("bromigos-keys")
        self.win.set_decorated(False)
        self.win.set_resizable(False)
        prov = Gtk.CssProvider()
        text = css(*palette())
        prov.load_from_string(text) if hasattr(prov, "load_from_string") else prov.load_from_data(text.encode())
        Gtk.StyleContext.add_provider_for_display(self.win.get_display(), prov,
                                                  Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION + 1)
        frame = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        frame.add_css_class("bk-frame")
        frame.set_tooltip_text("Bind a new shortcut: press the keys for it here. Hyprland's own shortcuts "
                               "are paused until this closes.")
        self.frame = frame

        top = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        eyebrow = Gtk.Label(label="SHORTCUT", xalign=0, hexpand=True)
        eyebrow.add_css_class("bk-eyebrow")
        eyebrow.set_tooltip_text("bromigos keys: binds a key without editing your hyprland.lua")
        forl = Gtk.Label(label=self.what, xalign=1, ellipsize=3, max_width_chars=40)
        forl.add_css_class("bk-for")
        forl.set_tooltip_text(f"What the new shortcut will do: {self.what}")
        top.append(eyebrow)
        top.append(forl)
        frame.append(top)

        title = Gtk.Label(label="Press the new shortcut", xalign=0)
        title.add_css_class("bk-title")
        title.set_tooltip_text("Hold the modifiers (SUPER, ALT, CTRL, SHIFT) and press a key, then let go.")
        frame.append(title)
        now = Gtk.Label(label=(f"now {self.current}" if self.current else "no key yet"), xalign=0)
        now.add_css_class("bk-now")
        now.set_tooltip_text("The key it has now. The new one replaces it." if self.current else
                             "It has no key yet.")
        frame.append(now)

        self.caps = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, halign=Gtk.Align.CENTER,
                            valign=Gtk.Align.CENTER)
        self.caps.add_css_class("bk-caps")
        self.caps.set_tooltip_text("The keys you're holding, shown the way the SHORTCUTS panel shows them.")
        frame.append(self.caps)

        self.status = Gtk.Label(xalign=0, wrap=True)
        self.status.add_css_class("bk-status")
        self.status.set_tooltip_text("What happens next. Enter saves now, Backspace clears, Esc cancels.")
        frame.append(self.status)

        self.bar = Gtk.ProgressBar()
        self.bar.add_css_class("bk-bar")
        self.bar.set_tooltip_text(f"Time left: after {self.limit} seconds without a key the window closes "
                                  "and nothing changes. Once you let go of a shortcut it drains while it saves.")
        frame.append(self.bar)

        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8, halign=Gtk.Align.END)
        self.b_clear = self._button("CLEAR", "Clear the keys and press again (Backspace).", self.clear)
        self.b_cancel = self._button("CANCEL", "Close without changing anything (Esc).", self.cancel)
        self.b_save = self._button("SAVE", "Save these keys now (Enter).", self.confirm)
        for b in (self.b_clear, self.b_cancel, self.b_save):
            row.append(b)
        frame.append(row)
        self.win.set_child(frame)

        keys = Gtk.EventControllerKey()
        keys.set_propagation_phase(Gtk.PropagationPhase.CAPTURE)
        keys.connect("key-pressed", self.on_press)
        keys.connect("key-released", self.on_release)
        self.win.add_controller(keys)
        self.win.connect("close-request", lambda *_: self.cancel() or False)
        self.update()

    def _button(self, label, tip, fn):
        b = self.Gtk.Button(label=label)
        b.add_css_class("bk-btn")
        b.set_focus_on_click(False)
        b.set_can_focus(False)
        b.set_tooltip_text(tip)
        b.connect("clicked", lambda *_: fn())
        return b

    def layer(self):
        LS = self.LS
        if LS is None or not LS.is_supported():
            return False
        LS.init_for_window(self.win)
        LS.set_namespace(self.win, "bromigos-keys")
        LS.set_layer(self.win, LS.Layer.OVERLAY)
        LS.set_keyboard_mode(self.win, LS.KeyboardMode.EXCLUSIVE)
        return True

    # -- what it shows
    def update(self):
        keys, complete = self.k.shown()
        shown = [keyname(k) for k in keys] + ([] if complete else [GHOST])
        if shown != self._shown:
            self._shown = shown
            child = self.caps.get_first_child()
            while child is not None:
                nxt = child.get_next_sibling()
                self.caps.remove(child)
                child = nxt
            self._caps(shown)
        self._status(keys, complete)

    def _caps(self, shown):
        Gtk = self.Gtk
        for i, k in enumerate(shown):
            if i:
                plus = Gtk.Label(label="+")
                plus.add_css_class("bk-plus")
                plus.set_tooltip_text("Held together.")
                self.caps.append(plus)
            cap = Gtk.Label(label=k)
            cap.add_css_class("bk-cap")
            if k == GHOST:
                cap.add_css_class("bk-ghost")
                cap.set_tooltip_text("Waiting for a key (a modifier alone isn't a shortcut).")
            else:
                cap.set_tooltip_text(f"{k}: one of the keys of the new shortcut.")
            self.caps.append(cap)

    def _status(self, keys, complete):
        k = self.k
        warn = False
        if k.phase == "listen":
            text = "Hold the keys, then let go. Esc cancels."
        elif k.phase == "hold":
            text = "Let go to save it." if complete else "Now a key with them."
        elif k.phase == "settle":
            text = f"Saving {' + '.join(keyname(x) for x in keys)}…  Enter: now · Backspace: try again · Esc: cancel"
        else:
            text = ""
        if k.note:
            text, warn = k.note, True
        if self.status.get_text() != text:
            self.status.set_text(text)
        (self.status.add_css_class if warn else self.status.remove_css_class)("bk-warn")
        self.b_save.set_sensitive(complete and k.phase != "done")
        self.b_clear.set_sensitive(bool(keys))
        if k.phase == "settle":
            self.bar.add_css_class("bk-settle")
            self.bar.set_fraction(max(0.0, k.settle_t / k.settle))
        else:
            self.bar.remove_css_class("bk-settle")
            self.bar.set_fraction(max(0.0, k.left / k.limit))

    # -- keys
    def level0(self, keycode):
        """The key's name with no modifier applied (as Hyprland matches binds)."""
        ev = self._ctrl_event
        group = ev.get_layout() if ev is not None and hasattr(ev, "get_layout") else 0
        try:
            ok, keyval, *_ = self.win.get_display().translate_key(keycode, 0, group)
        except Exception:
            ok, keyval = False, 0
        if not ok or not keyval:
            return None
        name = self.Gdk.keyval_name(keyval)
        return None if not name or name == "VoidSymbol" else name

    def on_press(self, ctrl, keyval, keycode, state):
        self._ctrl_event = ctrl.get_current_event()
        name = self.level0(keycode) or self.Gdk.keyval_name(keyval)
        what = self.k.press(name, keycode)
        if what == "cancel":
            self.cancel()
        elif what == "confirm":
            self.confirm()
        else:
            self.update()
        return True

    def on_release(self, ctrl, keyval, keycode, state):
        self.k.release(keycode)
        if self.k.phase != "done":
            self.update()

    # -- endings
    def clear(self):
        self.k.clear()
        self.update()

    def confirm(self):
        if self.k.phase == "done" or self.k.combo is None:
            return
        try:
            self.result = self.k.result()
        except BK.BadKeys:
            self.k.note = f"{self.k.combo[1]} isn't a key Hyprland can bind; try another."
            self.k.combo, self.k.phase = None, "listen"
            self.update()
            return
        self.finish()

    def cancel(self, why=None):
        if self.k.phase == "done":
            return
        self.result = None
        self.why = why
        self.finish()

    def finish(self):
        self.k.phase = "done"
        if self.suppress is not None:
            self.suppress.leave()
        self.win.set_visible(False)
        if self.loop is not None:
            self.loop.quit()

    def tick(self):
        if self.k.phase == "done":
            return False
        what = self.k.tick(0.05)
        if what == "confirm":
            self.confirm()
            return self.k.phase != "done"
        if what == "timeout":
            self.cancel("timed out")
            return False
        keys, complete = self.k.shown()
        self._status(keys, complete)
        return True


def run(what, current=None, limit=LIMIT, hypr=None):
    """Show the window; the pressed combo as a dict, or None (cancelled). Raises
    RuntimeError when it can't hold Hyprland's binds back."""
    Gtk, Gdk, GLib, LS = load_gtk()
    if not Gtk.init_check():
        raise RuntimeError("no display to show the window on")
    suppress = Suppress(hypr)
    cap = Capture(Gtk, Gdk, GLib, LS, what, current, limit, suppress)
    cap.layer()
    cap.loop = GLib.MainLoop()
    for s in (signal.SIGTERM, signal.SIGINT, signal.SIGHUP):
        GLib.unix_signal_add(GLib.PRIORITY_DEFAULT, s, lambda *_: cap.cancel("stopped") or False)
    started = {}

    def start():
        ok, why = suppress.enter()
        started["ok"], started["why"] = ok, why
        if not ok:
            cap.cancel(f"Hyprland's shortcuts couldn't be paused: {why}")
            return False
        suppress.watch(lambda: GLib.idle_add(lambda: cap.cancel("Hyprland left the capture") or False))
        GLib.timeout_add(50, cap.tick)
        return False

    cap.win.connect("map", lambda *_: GLib.timeout_add(60, start))
    cap.win.present()
    try:
        cap.loop.run()
    finally:
        suppress.leave()
    if started.get("ok") is False:
        raise RuntimeError(started.get("why") or "Hyprland's shortcuts couldn't be paused")
    return cap.result


def render(path, what, current=None, keys=None, phase="hold", note=None):
    """Draw the window to a PNG: `keys` ("SUPER + SHIFT + W") as held, in `phase`."""
    os.environ.setdefault("GSK_RENDERER", "cairo")      # an offscreen picture needs no GPU
    Gtk, Gdk, GLib, LS = load_gtk()
    if not Gtk.init_check():
        raise RuntimeError("no display to render on")
    cap = Capture(Gtk, Gdk, GLib, LS, what, current)
    if keys:
        c = BK.Combo.parse(keys)
        cap.k.combo = (c.mods, c.key, 0)
    cap.k.phase = phase
    cap.k.note = note
    if phase == "settle":
        cap.k.settle_t = SETTLE * 0.6
    cap.update()
    loop = GLib.MainLoop()
    out = {}

    seen = []

    def snap():
        frame = cap.frame
        w, h = frame.get_width(), frame.get_height()
        nat_w = frame.measure(Gtk.Orientation.HORIZONTAL, -1)[1]
        seen.append((w, h))
        # wait for the size the window asks for, twice in a row (a compositor's first
        # configure can be another)
        if w > nat_w + 2 and len(seen) % 5 == 0:
            # a compositor's first configure can be its own size: ask for ours again
            cap.win.unmaximize()
            cap.win.unfullscreen()
            cap.win.set_default_size(1, 1)
            cap.win.queue_resize()
        if w <= 1 or h <= 1 or w > nat_w + 2 or seen[-2:] != [(w, h)] * 2:
            return True
        paintable = Gtk.WidgetPaintable.new(frame)
        snapshot = Gtk.Snapshot.new()
        paintable.snapshot(snapshot, w, h)
        node = snapshot.to_node()
        renderer = cap.win.get_renderer()
        texture = renderer.render_texture(node, None)
        texture.save_to_png(path)
        out["size"] = (w, h)
        loop.quit()
        return False

    cap.win.set_default_size(1, 1)
    cap.win.present()
    GLib.timeout_add(100, snap)
    GLib.timeout_add(8000, loop.quit)
    loop.run()
    cap.win.destroy()
    if "size" not in out:
        raise RuntimeError("the window never laid out")
    return out["size"]
