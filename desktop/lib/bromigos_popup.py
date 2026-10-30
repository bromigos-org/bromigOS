"""The desktop's DRIFTGLASS GLOW popups, the parts they share (package bromigos-desktop,
/usr/lib/bromigos/lib; docs/DRIFTGLASS.md): GTK 4 on a gtk4-layer-shell surface under the
bar, Glass with faint Scanlines in the theme's colours, the targeting brackets, buttons and
rows, and the clear surface that closes a pinned popup on a click elsewhere. The Bluetooth
panel (bromigos_btpanel) and the sound popup (bromigos_soundpopup) are built from these.

Closing, the same for every popup: Esc; a second click on the icon that opened it; a click
anywhere else, on any screen, the bar included. That click isn't lost: the popup closes and
the click is given again to whatever was under the pointer (bromigos_vptr), so a click on
another bar module both closes the popup and does that module's job. An open popup never
holds the keyboard on its own (on demand: the keys reach it while it has the focus), only
while a PIN or passkey is being typed into it.

  Shell(Gtk, Gdk, GLib, LS)   the theme (palette, high contrast, motion), the stylesheet,
                              widget helpers, placing a surface under the pointer or a point
                              on the bar, and the clock the holograms move by
  Outside(shell, on_click)    the clear surfaces, one on each screen, that see a click
                              elsewhere: on_click() closes the popup, then the click is
                              handed on, unless it was on the popup's own icon
"""
import json
import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.realpath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import bromigos_bluez as B  # noqa: E402
import bromigos_driftglass as H  # noqa: E402


def load_gtk():
    import bromigos_keycapture as K        # gtk4-layer-shell before anything else loads GTK
    return K.load_gtk()


def palette():
    import bromigos_keycapture as K
    return K.palette()


def motion():
    for p in (os.path.join(HERE, "..", "..", "lib"), "/usr/lib/bromigos/lib"):
        if os.path.isdir(p) and p not in sys.path:
            sys.path.append(p)
    try:
        import bromigos_theme as T
        return T.motion()
    except Exception:
        return "full"


def css(p, hc=False):
    colours = "".join(f"@define-color dg_{k} {v};\n" for k, v in p.items())
    glass = ("background-color: @dg_panel; border: 2px solid @dg_soft;" if hc else
             "background-color: alpha(@dg_panel, 0.94); border: 1px solid alpha(@dg_dim, 0.9);"
             "background-image: repeating-linear-gradient(to bottom, transparent 0px, transparent 2px, "
             "alpha(@dg_primary, 0.035) 2px, alpha(@dg_primary, 0.035) 3px);")
    return colours + """
window.dg-win { background: transparent; }
window.dg-catcher { background: rgba(0, 0, 0, 0.01); }
.dg-frame { """ + glass + """ padding: 12px 14px 12px 14px; }
.dg-frame * { font-family: "Geist Mono", monospace; }
.dg-eyebrow { color: @dg_primary; font-weight: 700; font-size: 11px; letter-spacing: 3px; }
.dg-adapter { color: @dg_muted; font-size: 11px; }
.dg-section { color: @dg_muted; font-size: 10px; font-weight: 700; letter-spacing: 2px; margin-top: 8px; }
.dg-rule { background-color: alpha(@dg_dim, 0.45); min-height: 1px; margin-top: 8px; }
.dg-row { padding: 6px 4px; border-bottom: 1px solid alpha(@dg_dim, 0.18); }
.dg-name { color: @dg_white; font-size: 14px; font-weight: 600; }
.dg-row.dg-idle .dg-name { color: @dg_text; }
.dg-status { color: @dg_soft; font-size: 10px; letter-spacing: 1px; }
.dg-row.dg-idle .dg-status { color: @dg_muted; }
.dg-pct { color: @dg_soft; font-size: 10px; }
.dg-pct.dg-low { color: @dg_warn; }
.dg-pct.dg-critical { color: @dg_danger; }
button.dg-act { background: alpha(@dg_primary, 0.10); color: @dg_primary; border: 1px solid @dg_primary;
                border-radius: 0; box-shadow: none; font-size: 11px; font-weight: 700; letter-spacing: 2px;
                padding: 8px 10px; min-width: 104px; min-height: 0; }
button.dg-act:hover, button.dg-act:focus-visible { background: alpha(@dg_primary, 0.24); color: @dg_white; }
button.dg-act.dg-off { background: transparent; color: @dg_soft; border-color: @dg_dim; }
button.dg-act.dg-off:hover, button.dg-act.dg-off:focus-visible { border-color: @dg_soft; color: @dg_white; }
button.dg-act:disabled { color: @dg_faint; border-color: @dg_faint; background: transparent; }
button.dg-btn, menubutton.dg-more > button { background: transparent; color: @dg_soft; border: 1px solid @dg_dim;
                border-radius: 0; box-shadow: none; font-size: 11px; font-weight: 600; letter-spacing: 2px;
                padding: 6px 12px; min-height: 0; }
menubutton.dg-more > button { padding: 6px 8px; letter-spacing: 0; }
button.dg-btn:hover, button.dg-btn:focus-visible, menubutton.dg-more > button:hover,
menubutton.dg-more > button:focus-visible { border-color: @dg_primary; color: @dg_primary; }
button.dg-btn:disabled { color: @dg_faint; border-color: @dg_faint; }
button.dg-btn.dg-danger { color: @dg_danger; border-color: alpha(@dg_danger, 0.6); }
button.dg-seg { background: transparent; color: @dg_muted; border: 1px solid alpha(@dg_dim, 0.7); border-radius: 0;
                box-shadow: none; font-size: 9px; font-weight: 700; letter-spacing: 1px; padding: 2px 8px;
                min-height: 0; }
button.dg-seg:checked { background: alpha(@dg_primary, 0.18); color: @dg_primary; border-color: @dg_primary; }
button.dg-seg:hover, button.dg-seg:focus-visible { color: @dg_white; }
button.dg-note { background: transparent; color: @dg_warn; border: none; box-shadow: none; padding: 0;
                 font-size: 9px; font-weight: 700; letter-spacing: 1px; min-height: 0; }
button.dg-note:hover, button.dg-note:focus-visible { color: @dg_white; }
switch { background: @dg_selection; border: 1px solid @dg_dim; border-radius: 0; }
switch:checked { background: alpha(@dg_primary, 0.35); border-color: @dg_primary; }
switch slider { background: @dg_soft; border-radius: 0; min-width: 18px; min-height: 18px; border: none;
                box-shadow: none; }
switch:checked slider { background: @dg_primary; }
.dg-msg { color: @dg_muted; font-size: 11px; margin-top: 6px; }
.dg-msg.dg-error { color: @dg_danger; }
.dg-msg.dg-ok { color: @dg_primary; }
.dg-empty { color: @dg_muted; font-size: 11px; padding: 6px 4px; }
.dg-prompt { background-color: alpha(@dg_selection, 0.85); border: 1px solid @dg_primary; padding: 10px 12px;
             margin-top: 8px; }
.dg-prompt-title { color: @dg_primary; font-size: 11px; font-weight: 700; letter-spacing: 2px; }
.dg-prompt-text { color: @dg_white; font-size: 13px; margin-top: 4px; margin-bottom: 8px; }
entry.dg-entry { background: @dg_void; color: @dg_white; border: 1px solid @dg_dim; border-radius: 0;
                 box-shadow: none; font-size: 15px; letter-spacing: 3px; margin-bottom: 8px; }
.dg-scan-words { color: @dg_soft; font-size: 11px; letter-spacing: 1px; }
popover.background > contents, popover > contents { background-color: @dg_void; border: 1px solid @dg_dim;
                 border-radius: 0; padding: 6px; }
popover button.dg-btn { margin: 2px 0; }
tooltip { background-color: @dg_void; color: @dg_soft; border: 1px solid @dg_dim; border-radius: 0; }
tooltip label { color: @dg_soft; font-family: "Geist Mono"; font-size: 12px; }
scale.dg-scale { padding: 6px 0; }
scale.dg-scale trough { background: @dg_selection; min-height: 4px; border: none; border-radius: 0; }
scale.dg-scale highlight { background: @dg_primary; border: none; border-radius: 0; }
scale.dg-scale slider { background: @dg_primary; min-width: 8px; min-height: 16px; margin: -7px 0;
                        border: 1px solid @dg_void; border-radius: 0; box-shadow: none; }
scale.dg-scale:hover slider, scale.dg-scale:focus-visible slider { background: @dg_white; }
scale.dg-scale:disabled highlight, scale.dg-scale:disabled slider { background: @dg_faint; }
button.dg-seg.dg-mute { padding: 4px 8px; }
button.dg-item { background: transparent; border: none; border-radius: 0; box-shadow: none; padding: 7px 10px;
                 min-height: 0; }
button.dg-item:hover, button.dg-item:focus-visible { background: alpha(@dg_primary, 0.16); }
button.dg-item:disabled .dg-item-label { color: @dg_faint; }
.dg-item-label { color: @dg_text; font-size: 12px; }
.dg-item-right { color: @dg_primary; font-size: 10px; font-weight: 700; letter-spacing: 2px; }
.dg-item-right.dg-dimmed { color: @dg_muted; }
"""


class Shell:
    """What every popup shares: GTK, the theme, the clock (and bluez, for Bluetooth's)."""

    def __init__(self, Gtk, Gdk, GLib, LS, bz=None, now=time.monotonic, namespace="bromigos-popup"):
        self.Gtk, self.Gdk, self.GLib, self.LS = Gtk, Gdk, GLib, LS
        self.namespace = namespace
        self.pal, self.hc = palette()
        self.still = motion() != "full"
        self.now = now
        self.t0 = now()
        self.bz = bz
        self.audio = {}
        self._prov = None

    def t(self):
        return self.now() - self.t0

    def style(self, display):
        if self._prov is not None:
            return
        prov = self.Gtk.CssProvider()
        text = css(self.pal, self.hc)
        prov.load_from_string(text) if hasattr(prov, "load_from_string") else prov.load_from_data(text.encode())
        self.Gtk.StyleContext.add_provider_for_display(display, prov, self.Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION + 1)
        self._prov = prov

    def label(self, text, cls, tip=None, xalign=0.0, **kw):
        lab = self.Gtk.Label(label=text, xalign=xalign, **kw)
        for c in cls.split():
            lab.add_css_class(c)
        if tip:
            lab.set_tooltip_text(tip)
        return lab

    def button(self, text, cls, tip, fn):
        b = self.Gtk.Button(label=text)
        for c in cls.split():
            b.add_css_class(c)
        b.set_tooltip_text(tip)
        b.connect("clicked", lambda *_: fn())
        return b

    def refresh_audio(self, then=None):
        """PipeWire's Bluetooth cards (the profile and codec of each headset), async."""
        from gi.repository import Gio
        try:
            p = Gio.Subprocess.new(["pactl", "--format=json", "list", "cards"],
                                   Gio.SubprocessFlags.STDOUT_PIPE | Gio.SubprocessFlags.STDERR_SILENCE)
        except Exception:
            return

        def done(proc, res):
            try:
                _, out, _ = proc.communicate_utf8_finish(res)
                self.audio = B.audio_cards(json.loads(out or "[]"))
            except Exception:
                self.audio = {}
            if then:
                then()
        p.communicate_utf8_async(None, None, done)

    def place(self, win, width, at_x=None):
        """The surface just under the bar, centred on at_x (a point on the bar, in the
        screen's logical pixels) or else where the pointer is (Hyprland's cursor), kept on
        the screen; top right without Hyprland. Returns where the pointer is, which is on
        the icon that opened it: {"monitor": connector, "x", "y"} in that screen's logical
        pixels (None without Hyprland), so Outside can tell a click on that icon."""
        LS = self.LS
        LS.set_anchor(win, LS.Edge.TOP, True)
        try:
            cur = subprocess.run(["hyprctl", "cursorpos", "-j"], capture_output=True, text=True, timeout=2)
            mons = subprocess.run(["hyprctl", "monitors", "-j"], capture_output=True, text=True, timeout=2)
            c = json.loads(cur.stdout)
            cx, cy = c["x"], c["y"]
            mon = next(m for m in json.loads(mons.stdout)
                       if m["x"] <= cx < m["x"] + m["width"] / m["scale"] and m["y"] <= cy < m["y"] + m["height"] / m["scale"])
        except Exception:
            LS.set_anchor(win, LS.Edge.RIGHT, True)
            LS.set_margin(win, LS.Edge.RIGHT, 8)
            LS.set_margin(win, LS.Edge.TOP, 6)
            return None
        mw = mon["width"] / mon["scale"]
        centre = cx if at_x is None else at_x
        left = int(min(max(8, centre - mon["x"] - width / 2), mw - width - 8))
        LS.set_anchor(win, LS.Edge.LEFT, True)
        LS.set_margin(win, LS.Edge.LEFT, left)
        LS.set_margin(win, LS.Edge.TOP, 6)
        display = win.get_display()
        mons_g = display.get_monitors()
        for i in range(mons_g.get_n_items()):
            gm = mons_g.get_item(i)
            if gm.get_connector() == mon.get("name"):
                LS.set_monitor(win, gm)
                break
        return {"monitor": mon.get("name"), "x": cx - mon["x"], "y": cy - mon["y"]}

    def layer(self, win, keyboard=True):
        """win on the overlay layer. keyboard: True gives it the keys on demand (a pinned
        popup: Esc, Tab, the arrows, while it has the focus); False never (a hover popup)."""
        LS = self.LS
        if LS is None or not LS.is_supported():
            return False
        LS.init_for_window(win)
        LS.set_namespace(win, self.namespace)
        LS.set_layer(win, LS.Layer.OVERLAY)
        self.keyboard(win, keyboard)
        return True

    def keyboard(self, win, on):
        """No keys (False), the keys on demand (True), or all of them ("exclusive"), only
        while a PIN or passkey is typed into it: exclusive holds the whole desktop's keys."""
        LS = self.LS
        if LS is not None and LS.is_supported() and LS.is_layer_window(win):
            mode = LS.KeyboardMode.EXCLUSIVE if on == "exclusive" else (
                LS.KeyboardMode.ON_DEMAND if on else LS.KeyboardMode.NONE)
            LS.set_keyboard_mode(win, mode)

    def frame_overlay(self, child):
        """The panel's frame: its child, and the targeting brackets at the corners."""
        Gtk = self.Gtk
        ov = Gtk.Overlay()
        ov.set_child(child)
        da = Gtk.DrawingArea()
        da.set_can_target(False)

        def draw(area, cr, w, h):
            H._src(cr, self.pal, "primary", 1.0)
            cr.set_line_width(2)
            n = 12
            for (px, py, dx, dy) in ((1, 1, 1, 1), (w - 1, 1, -1, 1), (1, h - 1, 1, -1), (w - 1, h - 1, -1, -1)):
                cr.move_to(px, py + dy * n)
                cr.line_to(px, py)
                cr.line_to(px + dx * n, py)
            cr.stroke()
        da.set_draw_func(draw)
        ov.add_overlay(da)
        return ov

    def open_settings(self, page="bluetooth"):
        spawn(["bromigos", "settings", page])


class Outside:
    """A click anywhere but the popup: a clear surface over each screen, under the popup and
    over everything else (the bar too). A click on one (when its button comes back up)
    calls on_click(), which closes the popup; then the same button is clicked again where
    the pointer is (bromigos_vptr), so what was under it gets its click. Not when it was on
    the popup's own icon (opener, from Shell.place): that click is the toggle, it closes."""

    ICON = 28           # px either side of where the pointer was on the icon: still the icon

    def __init__(self, sh, on_click, opener=None, app=None):
        self.sh, self.on_click, self.opener = sh, on_click, opener
        self.wins = []
        self.done = False
        if sh.LS is None or not sh.LS.is_supported():
            return
        mons = sh.Gdk.Display.get_default().get_monitors()
        for i in range(mons.get_n_items()):
            self.wins.append(self._one(mons.get_item(i), app))

    def _one(self, mon, app):
        Gtk, LS = self.sh.Gtk, self.sh.LS
        w = Gtk.Window(title="outside")
        w.add_css_class("dg-catcher")        # all but clear: a surface with nothing drawn is never shown
        w.set_decorated(False)
        if app is not None:
            w.set_application(app)
        LS.init_for_window(w)
        LS.set_namespace(w, self.sh.namespace + "-outside")
        LS.set_layer(w, LS.Layer.TOP)
        LS.set_keyboard_mode(w, LS.KeyboardMode.NONE)
        LS.set_exclusive_zone(w, -1)          # over the bar as well
        LS.set_monitor(w, mon)
        for e in (LS.Edge.TOP, LS.Edge.BOTTOM, LS.Edge.LEFT, LS.Edge.RIGHT):
            LS.set_anchor(w, e, True)
        g = Gtk.GestureClick()
        g.set_button(0)
        g.connect("released", lambda gest, n, x, y: self.clicked(gest.get_current_button(), mon, x, y))
        w.add_controller(g)
        w.set_child(Gtk.Box())
        return w

    def present(self):
        for w in self.wins:
            w.present()

    def on_icon(self, mon, x, y):
        o = self.opener
        if not o or mon is None or mon.get_connector() != o.get("monitor"):
            return False
        return abs(x - o["x"]) <= self.ICON and y <= o["y"] + self.ICON

    def clicked(self, button, mon, x, y):
        if self.done:
            return
        self.done = True
        again = not self.on_icon(mon, x, y)
        self.destroy()
        self.on_click()
        if again:
            display = self.sh.Gdk.Display.get_default()
            if display is not None:
                display.flush()
            # a moment for the compositor to take the surfaces away, so the click lands on
            # what was under them
            self.sh.GLib.timeout_add(60, lambda: click_again(button))

    def destroy(self):
        for w in self.wins:
            w.destroy()
        self.wins = []


def click_again(button):
    """The pointer's button (GDK's 1, 2, 3) clicked again where it is."""
    import bromigos_vptr as V
    V.click({1: V.BTN_LEFT, 2: V.BTN_MIDDLE, 3: V.BTN_RIGHT}.get(button, V.BTN_LEFT))
    return False


def spawn(argv):
    try:
        subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                         start_new_session=True)
    except OSError:
        pass


def terminal(argv, title):
    helper = next((p for p in ("/usr/lib/bromigos/bin/bromigos-terminal",) if os.access(p, os.X_OK)), None)
    if helper:
        spawn([helper, "--hold", "--title", title, "--"] + argv)
    else:
        spawn(["kitty", "--hold", "-e"] + argv)


def clear(box):
    child = box.get_first_child()
    while child is not None:
        nxt = child.get_next_sibling()
        box.remove(child)
        child = nxt
