"""The bar's Bluetooth panel and quick menu (`bromigos bluetooth panel|menu`; package
bromigos-desktop, /usr/lib/bromigos/lib): GTK 4 on a layer-shell surface just under the
bar's icon, in the theme's colours.

  panel   the power switch; the paired devices, each with its hologram, state, battery,
          CONNECT or DISCONNECT, a sound profile switch for headsets, and ⋯ (auto-reconnect,
          forget); SCAN, with the devices nearby on a radar as they're found, and PAIR; any
          PIN or passkey asked for, right in the panel; OPEN SETTINGS
  menu    the right-click menu: on or off, visible, each paired device's connect or
          disconnect, and Bluetooth settings

One process holds both (Gtk.Application): a second click on the icon closes what's open.
Escape or a click anywhere else closes it too. Every part explains itself on hover.

DRIFTGLASS (docs/DRIFTGLASS.md): the panel is GLOW. Glass with faint Scanlines; each device
a hologram on its Emitter that turns slowly while connected; a Pulse while connecting, a
Spark when it worked, a fade on a disconnect; the Sweep while scanning. Motion only while
the panel is open, only for a state, and none under reduced motion (bromigos accessibility
motion reduced). bluez is bromigos_bluez's: the same code as the bar's module.

  render(path, view, …)   draws the panel or the menu to a PNG (tests, docs) against
                          whatever bluez BROMIGOS_BLUEZ_BUS points at; needs a Wayland
                          display, not Hyprland
"""
import json
import math
import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.realpath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import bromigos_bluez as B  # noqa: E402
import bromigos_driftglass as H  # noqa: E402

APP_ID = "org.bromigos.BluetoothPanel"
NAMESPACE = "bromigos-bluetooth"
WIDTH = 420
SCAN_SECS = 30
RUNTIME = os.environ.get("XDG_RUNTIME_DIR") or f"/run/user/{os.getuid()}"
BUSY = os.path.join(RUNTIME, "bromigos-bluetooth-busy")


# ------------------------------------------------------------------ words (pure: tested without GTK)
def status_words(d, audio=None, op=None):
    """The line under a device's name: its state, its sound profile and codec."""
    if op:
        return {"connecting": "CONNECTING…", "disconnecting": "DISCONNECTING…", "pairing": "PAIRING…",
                "trusting": "PAIRED · SAVING…", "forgetting": "FORGETTING…"}.get(op, op.upper() + "…")
    if not d["paired"]:
        sig = d.get("rssi")
        far = "" if sig is None else " · SIGNAL " + ("STRONG" if sig > -60 else "GOOD" if sig > -75 else "WEAK")
        return d["kind"].upper() + far
    bits = ["CONNECTED" if d["connected"] else "NOT CONNECTED"]
    if d["connected"] and audio and audio.get("mode") in B.MODE_LABEL:
        bits.append(B.MODE_LABEL[audio["mode"]])
        if audio.get("codec"):
            bits.append(audio["codec"])
    if not d["trusted"]:
        bits.append("ASKS FIRST")
    return " · ".join(bits)


def action(d, op=None):
    """(label, verb, hint) for the device's big button."""
    if op:
        return (status_words(d, op=op).rstrip("…").split(" · ")[-1] + "…", None, "Working on it")
    if not d["paired"]:
        return ("PAIR", "pair", f"Pair with {d['name']}: put it in pairing mode first. It's trusted after, so "
                                "it reconnects by itself when it's switched on")
    if d["connected"]:
        return ("DISCONNECT", "disconnect", f"Disconnect {d['name']} (it stays paired)")
    return ("CONNECT", "connect", f"Connect {d['name']}" + (" for its sound (a phone's other services stay off)"
                                                             if d.get("audio_source") else ""))


def driver_note(d):
    """A hint for an Xbox controller on the kernel's basic driver, or None."""
    if not d.get("xbox") or B.xpadneo_loaded():
        return None
    return ("BASIC DRIVER · SET UP",
            "This controller runs on the kernel's basic driver. xpadneo adds rumble, the battery and the right "
            "button layout: SET UP runs `bromigos peripheral enable xbox-controller` in a terminal (it asks for "
            "your password; reboot or reconnect after)")


def prompt_words(what, name, value):
    """(title, message, buttons, entry) for an agent's question. buttons: [(label, answer)]."""
    if what == "confirm":
        code = f"{value[:3]} {value[3:]}"
        return (f"PAIR {name}", f"Does {name} show {code}? If it does, say yes there too.",
                [("YES, PAIR", True), ("NO", False)], None)
    if what == "pin":
        return (f"PIN FOR {name}", "Type the PIN the device asks for. It's often 0000 or 1234: its manual says.",
                [("PAIR", "entry"), ("CANCEL", None)], "pin")
    if what == "passkey":
        return (f"PASSKEY FOR {name}", "Type the 6-digit number the device shows.",
                [("PAIR", "entry"), ("CANCEL", None)], "passkey")
    if what == "type":
        code, typed = value
        return (f"TYPE ON {name}", f"On {name}, type {code[:3]} {code[3:]}, then press Enter."
                + (f" ({typed} typed)" if typed else ""), [("CANCEL", None)], None)
    if what == "show-pin":
        return (f"PIN FOR {name}", f"On {name}, enter the PIN {value}.", [("CANCEL", None)], None)
    return (f"ALLOW {name}?", f"{name} asks to pair with this computer.", [("ALLOW", True), ("DENY", False)], None)


def menu_items(state, audio=None):
    """The quick menu, top to bottom: (id, label, right, hint, sensitive)."""
    a = state.get("adapter")
    if a is None:
        why = "bluetoothd isn't running" if not state.get("available") else "No Bluetooth adapter"
        return [("none", why, "", "Settings › Bluetooth says more", False),
                ("settings", "Bluetooth settings…", "", "Opens Settings › Bluetooth", True)]
    on = a["powered"]
    items = [("power", "Bluetooth", "ON" if on else "OFF",
              f"Turns Bluetooth {'off' if on else 'on'} (middle-click on the bar icon does too)", True),
             ("visible", "Visible to devices nearby", "ON" if a.get("discoverable") else "OFF",
              "Lets a phone or another computer find this one to pair (bluez hides it again after 3 minutes)", on)]
    for d in state.get("paired", []):
        items.append((f"dev:{d['mac']}", d["name"], "DISCONNECT" if d["connected"] else "CONNECT",
                      f"{'Disconnects' if d['connected'] else 'Connects'} {d['name']} ({d['kind']})", on))
    items += [("panel", "Devices and pairing…", "", "Opens the Bluetooth panel (a left click on the icon)", True),
              ("settings", "Bluetooth settings…", "", "Opens Settings › Bluetooth", True)]
    return items


# ------------------------------------------------------------------ GTK
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
    colours = "".join(f"@define-color bt_{k} {v};\n" for k, v in p.items())
    glass = ("background-color: @bt_panel; border: 2px solid @bt_soft;" if hc else
             "background-color: alpha(@bt_panel, 0.94); border: 1px solid alpha(@bt_dim, 0.9);"
             "background-image: repeating-linear-gradient(to bottom, transparent 0px, transparent 2px, "
             "alpha(@bt_primary, 0.035) 2px, alpha(@bt_primary, 0.035) 3px);")
    return colours + """
window.bt-win { background: transparent; }
window.bt-catcher { background: transparent; }
.bt-frame { """ + glass + """ padding: 12px 14px 12px 14px; }
.bt-frame * { font-family: "Geist Mono", monospace; }
.bt-eyebrow { color: @bt_primary; font-weight: 700; font-size: 11px; letter-spacing: 3px; }
.bt-adapter { color: @bt_muted; font-size: 11px; }
.bt-section { color: @bt_muted; font-size: 10px; font-weight: 700; letter-spacing: 2px; margin-top: 8px; }
.bt-rule { background-color: alpha(@bt_dim, 0.45); min-height: 1px; margin-top: 8px; }
.bt-row { padding: 6px 4px; border-bottom: 1px solid alpha(@bt_dim, 0.18); }
.bt-name { color: @bt_white; font-size: 14px; font-weight: 600; }
.bt-row.bt-idle .bt-name { color: @bt_text; }
.bt-status { color: @bt_soft; font-size: 10px; letter-spacing: 1px; }
.bt-row.bt-idle .bt-status { color: @bt_muted; }
.bt-pct { color: @bt_soft; font-size: 10px; }
.bt-pct.bt-low { color: @bt_warn; }
.bt-pct.bt-critical { color: @bt_danger; }
button.bt-act { background: alpha(@bt_primary, 0.10); color: @bt_primary; border: 1px solid @bt_primary;
                border-radius: 0; box-shadow: none; font-size: 11px; font-weight: 700; letter-spacing: 2px;
                padding: 8px 10px; min-width: 104px; min-height: 0; }
button.bt-act:hover, button.bt-act:focus-visible { background: alpha(@bt_primary, 0.24); color: @bt_white; }
button.bt-act.bt-off { background: transparent; color: @bt_soft; border-color: @bt_dim; }
button.bt-act.bt-off:hover, button.bt-act.bt-off:focus-visible { border-color: @bt_soft; color: @bt_white; }
button.bt-act:disabled { color: @bt_faint; border-color: @bt_faint; background: transparent; }
button.bt-btn, menubutton.bt-more > button { background: transparent; color: @bt_soft; border: 1px solid @bt_dim;
                border-radius: 0; box-shadow: none; font-size: 11px; font-weight: 600; letter-spacing: 2px;
                padding: 6px 12px; min-height: 0; }
menubutton.bt-more > button { padding: 6px 8px; letter-spacing: 0; }
button.bt-btn:hover, button.bt-btn:focus-visible, menubutton.bt-more > button:hover,
menubutton.bt-more > button:focus-visible { border-color: @bt_primary; color: @bt_primary; }
button.bt-btn:disabled { color: @bt_faint; border-color: @bt_faint; }
button.bt-btn.bt-danger { color: @bt_danger; border-color: alpha(@bt_danger, 0.6); }
button.bt-seg { background: transparent; color: @bt_muted; border: 1px solid alpha(@bt_dim, 0.7); border-radius: 0;
                box-shadow: none; font-size: 9px; font-weight: 700; letter-spacing: 1px; padding: 2px 8px;
                min-height: 0; }
button.bt-seg:checked { background: alpha(@bt_primary, 0.18); color: @bt_primary; border-color: @bt_primary; }
button.bt-seg:hover, button.bt-seg:focus-visible { color: @bt_white; }
button.bt-note { background: transparent; color: @bt_warn; border: none; box-shadow: none; padding: 0;
                 font-size: 9px; font-weight: 700; letter-spacing: 1px; min-height: 0; }
button.bt-note:hover, button.bt-note:focus-visible { color: @bt_white; }
switch { background: @bt_selection; border: 1px solid @bt_dim; border-radius: 0; }
switch:checked { background: alpha(@bt_primary, 0.35); border-color: @bt_primary; }
switch slider { background: @bt_soft; border-radius: 0; min-width: 18px; min-height: 18px; border: none;
                box-shadow: none; }
switch:checked slider { background: @bt_primary; }
.bt-msg { color: @bt_muted; font-size: 11px; margin-top: 6px; }
.bt-msg.bt-error { color: @bt_danger; }
.bt-msg.bt-ok { color: @bt_primary; }
.bt-empty { color: @bt_muted; font-size: 11px; padding: 6px 4px; }
.bt-prompt { background-color: alpha(@bt_selection, 0.85); border: 1px solid @bt_primary; padding: 10px 12px;
             margin-top: 8px; }
.bt-prompt-title { color: @bt_primary; font-size: 11px; font-weight: 700; letter-spacing: 2px; }
.bt-prompt-text { color: @bt_white; font-size: 13px; margin-top: 4px; margin-bottom: 8px; }
entry.bt-entry { background: @bt_void; color: @bt_white; border: 1px solid @bt_dim; border-radius: 0;
                 box-shadow: none; font-size: 15px; letter-spacing: 3px; margin-bottom: 8px; }
.bt-scan-words { color: @bt_soft; font-size: 11px; letter-spacing: 1px; }
popover.background > contents, popover > contents { background-color: @bt_void; border: 1px solid @bt_dim;
                 border-radius: 0; padding: 6px; }
popover button.bt-btn { margin: 2px 0; }
tooltip { background-color: @bt_void; color: @bt_soft; border: 1px solid @bt_dim; border-radius: 0; }
tooltip label { color: @bt_soft; font-family: "Geist Mono"; font-size: 12px; }
button.bt-item { background: transparent; border: none; border-radius: 0; box-shadow: none; padding: 7px 10px;
                 min-height: 0; }
button.bt-item:hover, button.bt-item:focus-visible { background: alpha(@bt_primary, 0.16); }
button.bt-item:disabled .bt-item-label { color: @bt_faint; }
.bt-item-label { color: @bt_text; font-size: 12px; }
.bt-item-right { color: @bt_primary; font-size: 10px; font-weight: 700; letter-spacing: 2px; }
.bt-item-right.bt-dimmed { color: @bt_muted; }
"""


class Shell:
    """What the panel and the menu share: GTK, bluez, the theme, the clock."""

    def __init__(self, Gtk, Gdk, GLib, LS, bz=None, now=time.monotonic):
        self.Gtk, self.Gdk, self.GLib, self.LS = Gtk, Gdk, GLib, LS
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

    def place(self, win, width, height_guess=380):
        """The surface just under the bar, centred on where the pointer clicked (Hyprland's
        cursor), kept on the screen; top right without Hyprland."""
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
            return
        mw = mon["width"] / mon["scale"]
        left = int(min(max(8, cx - mon["x"] - width / 2), mw - width - 8))
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

    def layer(self, win, keyboard=True):
        LS = self.LS
        if LS is None or not LS.is_supported():
            return False
        LS.init_for_window(win)
        LS.set_namespace(win, NAMESPACE)
        LS.set_layer(win, LS.Layer.OVERLAY)
        LS.set_keyboard_mode(win, LS.KeyboardMode.EXCLUSIVE if keyboard else LS.KeyboardMode.NONE)
        return True

    def catcher(self, on_click):
        """A clear surface over everything under the panel: a click on it closes the panel."""
        Gtk, LS = self.Gtk, self.LS
        if LS is None or not LS.is_supported():
            return None
        w = Gtk.Window(title="Bluetooth")
        w.add_css_class("bt-catcher")
        w.set_decorated(False)
        LS.init_for_window(w)
        LS.set_namespace(w, NAMESPACE + "-outside")
        LS.set_layer(w, LS.Layer.TOP)
        LS.set_keyboard_mode(w, LS.KeyboardMode.NONE)
        LS.set_exclusive_zone(w, -1)
        for e in (LS.Edge.TOP, LS.Edge.BOTTOM, LS.Edge.LEFT, LS.Edge.RIGHT):
            LS.set_anchor(w, e, True)
        g = Gtk.GestureClick()
        g.set_button(0)
        g.connect("pressed", lambda *_: on_click())
        w.add_controller(g)
        w.set_child(Gtk.Box())
        return w

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

    def open_settings(self):
        _spawn(["bromigos", "settings", "bluetooth"])


def _spawn(argv):
    try:
        subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                         start_new_session=True)
    except OSError:
        pass


def _terminal(argv, title):
    helper = next((p for p in ("/usr/lib/bromigos/bin/bromigos-terminal",) if os.access(p, os.X_OK)), None)
    if helper:
        _spawn([helper, "--hold", "--title", title, "--"] + argv)
    else:
        _spawn(["kitty", "--hold", "-e"] + argv)


def _clear(box):
    child = box.get_first_child()
    while child is not None:
        nxt = child.get_next_sibling()
        box.remove(child)
        child = nxt


class Row:
    """One device in the panel: its hologram, words, battery, buttons; updated in place."""

    def __init__(self, panel, d):
        self.p = panel
        sh, Gtk = panel.sh, panel.sh.Gtk
        self.d = d
        self.box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        self.box.add_css_class("bt-row")
        self.holo = Gtk.DrawingArea()
        self.holo.set_size_request(50, 50)
        self.holo.set_valign(Gtk.Align.CENTER)
        self.holo.set_draw_func(self.draw_holo)
        self.box.append(self.holo)
        mid = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=3, hexpand=True, valign=Gtk.Align.CENTER)
        self.name = sh.label(d["name"], "bt-name", wrap=True, ellipsize=3, lines=2, max_width_chars=24,
                             width_chars=14)
        self.status = sh.label("", "bt-status", wrap=True, max_width_chars=26)
        mid.append(self.name)
        mid.append(self.status)
        self.batt_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        self.cells = Gtk.DrawingArea()
        self.cells.set_size_request(84, 7)
        self.cells.set_valign(Gtk.Align.CENTER)
        self.cells.set_draw_func(lambda a, cr, w, h: H.cells(cr, 0, 0, w, h, self.d.get("battery"), sh.pal))
        self.pct = sh.label("", "bt-pct")
        self.batt_row.append(self.cells)
        self.batt_row.append(self.pct)
        mid.append(self.batt_row)
        self.prof = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=0)
        self.seg = {}
        group = None
        for mode in ("hifi", "headset"):
            b = Gtk.ToggleButton(label=B.MODE_LABEL[mode])
            b.add_css_class("bt-seg")
            b.set_tooltip_text(B.MODE_HINT[mode])
            if group is not None:
                b.set_group(group)
            group = group or b
            b.connect("toggled", self.on_seg, mode)
            self.seg[mode] = b
            self.prof.append(b)
        mid.append(self.prof)
        self.note = Gtk.Button(label="")
        self.note.add_css_class("bt-note")
        self.note.set_halign(Gtk.Align.START)
        self.note.connect("clicked", lambda *_: _terminal(["bromigos", "peripheral", "enable", "xbox-controller"],
                                                          "Xbox controller driver"))
        mid.append(self.note)
        self.box.append(mid)
        right = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4, valign=Gtk.Align.CENTER)
        self.act = Gtk.Button(label="")
        self.act.add_css_class("bt-act")
        self.act.connect("clicked", lambda *_: self.p.act(self.d))
        right.append(self.act)
        self.more = Gtk.MenuButton()
        self.more.set_child(Gtk.Label(label="⋯"))
        self.more.add_css_class("bt-more")
        self.more.set_tooltip_text("More: auto-reconnect, forget")
        pop = Gtk.Popover()
        pv = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        self.trust_b = sh.button("", "bt-btn", "", lambda: self.p.trust(self.d))
        self.forget_b = sh.button("FORGET…", "bt-btn bt-danger", "", lambda: self.forget())
        self.settings_b = sh.button("IN SETTINGS", "bt-btn", "Opens Settings › Bluetooth",
                                    lambda: (pop.popdown(), sh.open_settings(), self.p.close()))
        for b in (self.trust_b, self.forget_b, self.settings_b):
            pv.append(b)
        pop.set_child(pv)
        self.more.set_popover(pop)
        self.pop = pop
        right.append(self.more)
        self.box.append(right)
        self.armed = 0.0
        self._syncing = False
        self.update(d)

    def draw_holo(self, area, cr, w, h):
        p, d = self.p, self.d
        fx = p.fx_of(d["mac"])
        H.glyph(cr, d["glyph"], 0, 0, min(w, h), p.sh.pal, t=p.sh.t(), live=d["connected"], fx=fx,
                still=p.sh.still, hc=p.sh.hc)

    def update(self, d):
        self.d = d
        p, sh = self.p, self.p.sh
        op = p.ops.get(d["mac"])
        audio = sh.audio.get(d["mac"]) if d["connected"] else None
        self.name.set_text(d["name"])
        self.name.set_tooltip_text(f"{d['name']}: {d['kind']}, {d['mac']}")
        self.status.set_text(status_words(d, audio, op))
        self.status.set_tooltip_text("Its state" + (", the sound profile and the codec in use" if audio else ""))
        live = d["connected"] or not d["paired"]
        (self.box.remove_css_class if live else self.box.add_css_class)("bt-idle")
        b = d.get("battery")
        self.batt_row.set_visible(b is not None)
        self.pct.set_text(f"{b}%" if b is not None else "")
        for c in ("bt-low", "bt-critical"):
            self.pct.remove_css_class(c)
        lv = B.level(b)
        if lv in ("low", "critical"):
            self.pct.add_css_class("bt-" + lv)
        self.cells.set_tooltip_text(f"Battery {b}%" + (" (low)" if lv != "ok" else "") if b is not None else None)
        self.cells.queue_draw()
        show_prof = bool(audio and audio.get("hifi") and audio.get("headset") and audio.get("mode") in ("hifi", "headset"))
        self.prof.set_visible(show_prof)
        if show_prof:
            self._syncing = True
            self.seg[audio["mode"]].set_active(True)
            self._syncing = False
        note = driver_note(d) if d["paired"] else None
        self.note.set_visible(note is not None)
        if note:
            self.note.set_label(note[0])
            self.note.set_tooltip_text(note[1])
        label, verb, hint = action(d, op)
        self.act.set_label(label)
        self.act.set_tooltip_text(hint)
        self.act.set_sensitive(verb is not None and p.powered())
        (self.act.add_css_class if verb == "disconnect" else self.act.remove_css_class)("bt-off")
        self.more.set_visible(d["paired"])
        self.trust_b.set_label("AUTO-RECONNECT: " + ("ON" if d["trusted"] else "OFF"))
        self.trust_b.set_tooltip_text("On: it connects by itself when it's switched on (trusted). Off: it asks "
                                      "first. Click to switch")
        self.forget_b.set_label("FORGET…")
        self.forget_b.set_tooltip_text(f"Unpair {d['name']}: using it again means pairing it again. "
                                       "Click twice to be sure")
        self.holo.set_tooltip_text(f"{d['kind']}: " + ("connected" if d["connected"] else
                                                        "paired, not connected" if d["paired"] else "found nearby"))
        self.holo.queue_draw()

    def on_seg(self, btn, mode):
        if self._syncing or not btn.get_active():
            return
        self.p.profile(self.d, mode)

    def forget(self):
        now = self.p.sh.now()
        if now - self.armed > 3:
            self.armed = now
            self.forget_b.set_label("SURE? CLICK AGAIN")
            return
        self.pop.popdown()
        self.p.forget(self.d)


class Panel:
    def __init__(self, sh, on_close):
        self.sh = sh
        Gtk = sh.Gtk
        self.on_close = on_close
        self.ops = {}           # mac -> what's in flight
        self.fx = {}            # mac -> (effect, started)
        self.seen = {}          # mac -> when it was first seen nearby
        self.rows = {}
        self.state = B.unavailable()
        self.scanning_until = 0.0
        self.prompt_reply = None
        self.pairing = None
        self.timer = None
        self.win = Gtk.Window(title="Bluetooth")
        self.win.add_css_class("bt-win")
        self.win.set_decorated(False)
        self.win.set_resizable(False)
        sh.style(self.win.get_display())
        self._build()
        keys = Gtk.EventControllerKey()
        keys.connect("key-pressed", self.on_key)
        self.win.add_controller(keys)
        self.win.connect("close-request", lambda *_: self.close() or True)

    # -- the widgets
    def _build(self):
        sh, Gtk = self.sh, self.sh.Gtk
        frame = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        frame.add_css_class("bt-frame")
        frame.set_size_request(WIDTH, -1)
        top = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        top.append(sh.label("BLUETOOTH", "bt-eyebrow", "Bluetooth: this computer's adapter and its devices"))
        self.adapter = sh.label("", "bt-adapter", "This computer's name as other devices see it", hexpand=True,
                                ellipsize=3)
        top.append(self.adapter)
        self.power = Gtk.Switch(valign=Gtk.Align.CENTER)
        self.power.set_tooltip_text("Turns Bluetooth on or off (middle-click on the bar icon does too)")
        self.power.connect("state-set", self.on_power)
        top.append(self.power)
        frame.append(top)
        rule = Gtk.Box()
        rule.add_css_class("bt-rule")
        frame.append(rule)
        self.prompt_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.prompt_box.add_css_class("bt-prompt")
        self.prompt_box.set_visible(False)
        self.prompt_box.set_tooltip_text("bluez is waiting for this answer to pair")
        frame.append(self.prompt_box)
        frame.append(sh.label("PAIRED", "bt-section", "Devices this computer knows"))
        self.paired = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.nearby_head = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        self.radar = Gtk.DrawingArea()
        self.radar.set_size_request(56, 56)
        self.radar.set_draw_func(self.draw_radar)
        self.radar.set_tooltip_text("The scan: each dot is a device found nearby, further out the weaker its signal")
        self.scan_words = sh.label("", "bt-scan-words", wrap=True, hexpand=True, valign=Gtk.Align.CENTER)
        self.nearby_head.append(self.radar)
        self.nearby_head.append(self.scan_words)
        self.nearby = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        lists = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        lists.append(self.paired)
        self.near_title = sh.label("NEARBY", "bt-section", "Devices in pairing mode near this computer")
        lists.append(self.near_title)
        lists.append(self.nearby_head)
        lists.append(self.nearby)
        scroll = Gtk.ScrolledWindow()
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroll.set_propagate_natural_height(True)
        scroll.set_max_content_height(540)
        scroll.set_child(lists)
        frame.append(scroll)
        self.msg = sh.label("", "bt-msg", wrap=True, max_width_chars=44)
        self.msg.set_tooltip_text("What happened last")
        frame.append(self.msg)
        foot = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8, margin_top=10)
        self.scan_b = sh.button("SCAN", "bt-btn", f"Looks for devices nearby for {SCAN_SECS} seconds: put the "
                                "device in pairing mode first", self.toggle_scan)
        foot.append(self.scan_b)
        foot.append(Gtk.Box(hexpand=True))
        foot.append(sh.button("OPEN SETTINGS", "bt-btn", "Opens Settings › Bluetooth (SUPER+, then Bluetooth)",
                              lambda: (sh.open_settings(), self.close())))
        frame.append(foot)
        self.frame = frame
        self.win.set_child(sh.frame_overlay(frame))

    # -- state
    def powered(self):
        return bool((self.state.get("adapter") or {}).get("powered"))

    def changed(self, st):
        before = {d["mac"]: d for d in self.state.get("devices", [])}
        now = self.sh.now()
        for d in st.get("devices", []):
            was = before.get(d["mac"])
            if was is not None and was["connected"] != d["connected"]:
                self.fx[d["mac"]] = ("spark" if d["connected"] else "fade", now)
                if d["connected"]:
                    self.sh.refresh_audio(lambda: self.sync())
            if d["mac"] not in self.seen and not d["paired"]:
                self.seen[d["mac"]] = now
        self.state = st
        self.sync()

    def fx_of(self, mac):
        op = self.ops.get(mac)
        if op in ("connecting", "pairing", "trusting", "disconnecting"):
            return ("pulse", self.sh.now() - self.sh.t0)
        e = self.fx.get(mac)
        if e is None:
            return None
        age = self.sh.now() - e[1]
        if age > 0.7:
            self.fx.pop(mac, None)
            return None
        return (e[0], age)

    def sync(self):
        st, sh = self.state, self.sh
        a = st.get("adapter")
        self.adapter.set_text((a["alias"] or a["name"]) if a else "")
        self.power.set_sensitive(a is not None and not st.get("hard_blocked"))
        self.power.handler_block_by_func(self.on_power)
        self.power.set_active(bool(a and a["powered"]))
        self.power.set_state(bool(a and a["powered"]))
        self.power.handler_unblock_by_func(self.on_power)
        self._list(self.paired, st.get("paired", []), empty=self._empty_words())
        scanning = bool(a and a.get("discovering"))
        near = st.get("nearby", [])
        self._list(self.nearby, near, empty=None)
        show_near = bool(a and a["powered"]) and (scanning or bool(near))
        self.near_title.set_visible(show_near)
        self.nearby_head.set_visible(show_near and (scanning or bool(near)))
        n = len(near)
        self.scan_words.set_text(
            (f"SCANNING · {n} FOUND" if scanning else f"{n} FOUND") + "\nPut the device in pairing mode: "
            + ("an Xbox pad: hold its pair button until the logo flashes fast" if scanning else "then SCAN"))
        self.scan_b.set_label("STOP" if scanning else "SCAN")
        self.scan_b.set_sensitive(bool(a and a["powered"]))
        self.radar.queue_draw()
        self.animate()

    def _empty_words(self):
        st = self.state
        if not st.get("available"):
            return "bluetoothd isn't running. Start it: systemctl enable --now bluetooth"
        if st.get("adapter") is None:
            return "No Bluetooth adapter found" + (" (the radio is blocked: rfkill)" if st.get("blocked") else "")
        if not st["adapter"]["powered"]:
            return "Bluetooth is off" + (": a hardware switch or key turned it off" if st.get("hard_blocked") else
                                         ". Switch it on above")
        return "Nothing paired yet. SCAN finds devices in pairing mode"

    def _list(self, box, devs, empty):
        keep = []
        child = box.get_first_child()
        shown = []
        while child is not None:
            shown.append(child)
            child = child.get_next_sibling()
        want = [d["mac"] for d in devs]
        rows = [self.rows.get(m) for m in want]
        if [getattr(r, "box", None) for r in rows] != shown:
            focus = self.win.get_focus()
            _clear(box)
            for d in devs:
                r = self.rows.get(d["mac"]) or Row(self, d)
                self.rows[d["mac"]] = r
                if r.box.get_parent() is not None:
                    r.box.get_parent().remove(r.box)
                box.append(r.box)
                keep.append(d["mac"])
            if not devs and empty:
                box.append(self.sh.label(empty, "bt-empty", wrap=True, max_width_chars=44))
            if focus is not None and focus.get_root() is None:
                self.win.set_focus(None)
        for d in devs:
            self.rows[d["mac"]].update(d)

    def animate(self):
        """One timer while anything moves (connected holograms, the radar, an effect)."""
        if self.sh.still or self.timer is not None or not self.win.get_visible():
            return
        self.timer = self.sh.GLib.timeout_add(40, self.tick)

    def moving(self):
        st = self.state
        return bool(st.get("connected") or (st.get("adapter") or {}).get("discovering") or self.fx or self.ops)

    def tick(self):
        if not self.moving() or not self.win.get_visible():
            self.timer = None
            return False
        for r in self.rows.values():
            if r.box.get_parent() is not None and (r.d["connected"] or r.d["mac"] in self.fx or r.d["mac"] in self.ops):
                r.holo.queue_draw()
        if (self.state.get("adapter") or {}).get("discovering"):
            self.radar.queue_draw()
        if self.scanning_until and self.sh.now() > self.scanning_until:
            self.scanning_until = 0.0
            self.sh.bz.scan(False)
        return True

    def draw_radar(self, area, cr, w, h):
        now = self.sh.now()
        blips = [(d["mac"], d.get("rssi"), now - self.seen.get(d["mac"], now - 9)) for d in self.state.get("nearby", [])]
        H.radar(cr, 0, 0, min(w, h), self.sh.pal, self.sh.t(), blips, still=self.sh.still, hc=self.sh.hc)

    # -- messages
    def say(self, text, kind=None):
        self.msg.set_text(text or "")
        for c in ("bt-error", "bt-ok"):
            self.msg.remove_css_class(c)
        if kind:
            self.msg.add_css_class("bt-" + kind)

    def done(self, mac, ok_words):
        def back(ok, err):
            self.ops.pop(mac, None)
            if ok:
                self.say(ok_words, "ok")
            else:
                self.say(err, "error")
            self.sync()
        return back

    # -- actions
    def on_power(self, sw, on):
        self.sh.bz.power(on, lambda ok, err: self.say(f"Bluetooth {'on' if on else 'off'}", "ok") if ok else
                         (self.say(err, "error"), self.sync()))
        return False

    def act(self, d):
        label, verb, _ = action(d, self.ops.get(d["mac"]))
        if verb == "connect":
            self.ops[d["mac"]] = "connecting"
            self.sh.bz.connect(d["path"], self.done(d["mac"], f"{d['name']} connected"))
        elif verb == "disconnect":
            self.ops[d["mac"]] = "disconnecting"
            self.sh.bz.disconnect(d["path"], self.done(d["mac"], f"{d['name']} disconnected"))
        elif verb == "pair":
            self.pair(d)
        self.sync()

    def trust(self, d):
        self.sh.bz.trust(d["path"], not d["trusted"], self.done(
            d["mac"], f"{d['name']}: " + ("asks first now" if d["trusted"] else "reconnects by itself now")))

    def forget(self, d):
        self.ops[d["mac"]] = "forgetting"
        self.sync()
        self.sh.bz.forget(d["path"], self.done(d["mac"], f"Forgot {d['name']}"))

    def profile(self, d, mode):
        def back(ok, out):
            if ok:
                self.say(f"{d['name']}: {B.MODE_LABEL[mode]}", "ok")
            else:
                self.say(out, "error")
            self.sh.refresh_audio(self.sync)
        _cli(["profile", d["mac"], mode], back)

    def toggle_scan(self):
        a = self.state.get("adapter") or {}
        if a.get("discovering"):
            self.scanning_until = 0.0
            self.sh.bz.scan(False, lambda ok, err: None if ok else self.say(err, "error"))
        else:
            self.scanning_until = self.sh.now() + SCAN_SECS
            self.say("")
            self.sh.bz.scan(True, lambda ok, err: None if ok else self.say(err, "error"))

    def pair(self, d):
        bz = self.sh.bz
        self.pairing = d
        self.ops[d["mac"]] = "pairing"
        _busy(True)

        def step(word):
            self.ops[d["mac"]] = word
            self.sync()

        def finished(ok, err):
            _busy(False)
            self.hide_prompt()
            self.ops.pop(d["mac"], None)
            self.pairing = None
            if ok:
                self.fx[d["mac"]] = ("spark", self.sh.now())
                self.say(f"Paired with {d['name']}: it reconnects by itself when it's switched on", "ok")
            else:
                self.say(f"{d['name']}: {err}", "error")
            self.sync()

        def go(ok=True, err=None):
            if not ok:
                finished(False, err)
                return
            bz.pair(d["path"], finished, step)
        if bz.agent is None:
            bz.register_agent(B.Agent(self), go)
        else:
            go()
        self.sync()

    # the agent's questions (bromigos_bluez.Agent)
    def prompt(self, what, path, value, reply):
        sh, Gtk = self.sh, self.sh.Gtk
        d = next((x for x in self.state.get("devices", []) if x["path"] == path), None)
        name = d["name"] if d else B.mac_of(path)
        title, text, buttons, entry_kind = prompt_words(what, name, value)
        _clear(self.prompt_box)
        self.prompt_box.append(sh.label(title, "bt-prompt-title"))
        self.prompt_box.append(sh.label(text, "bt-prompt-text", wrap=True, max_width_chars=40))
        entry = None
        if entry_kind:
            entry = Gtk.Entry()
            entry.add_css_class("bt-entry")
            entry.set_tooltip_text("The code, then Enter")
            if entry_kind == "passkey":
                entry.set_input_purpose(Gtk.InputPurpose.DIGITS)
                entry.set_max_length(6)
            entry.connect("activate", lambda *_: answer("entry"))
            self.prompt_box.append(entry)
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8, halign=Gtk.Align.END)
        self.prompt_reply = reply

        def answer(value_):
            r, self.prompt_reply = self.prompt_reply, None
            if value_ == "entry":
                value_ = entry.get_text().strip() if entry else None
                value_ = value_ or None
            self.hide_prompt()
            if r is not None:
                r(value_)
            if value_ in (None, False) and self.pairing is not None:
                self.sh.bz.cancel_pair(self.pairing["path"])
        for label, val in buttons:
            row.append(sh.button(label, "bt-act" if val not in (None, False) else "bt-btn",
                                 {True: "Answer yes", False: "Answer no: pairing stops", None: "Stop pairing",
                                  "entry": "Send the code"}.get(val, label), lambda v=val: answer(v)))
        self.prompt_box.append(row)
        self.prompt_box.set_visible(True)
        (entry or row.get_first_child()).grab_focus()

    def cancel(self):
        name = (self.pairing or {}).get("name", "The device")
        self.hide_prompt()
        self.say(f"{name} stopped pairing (cancelled, or it took too long)", "error")

    def hide_prompt(self):
        self.prompt_box.set_visible(False)
        _clear(self.prompt_box)

    # -- keys and closing
    def on_key(self, ctrl, keyval, keycode, state):
        if keyval == self.sh.Gdk.KEY_Escape:
            if self.prompt_box.get_visible() and self.prompt_reply is not None:
                r, self.prompt_reply = self.prompt_reply, None
                self.hide_prompt()
                r(None)
                return True
            self.close()
            return True
        return False

    def close(self):
        if self.pairing is not None:
            self.sh.bz.cancel_pair(self.pairing["path"])
            _busy(False)
        if (self.state.get("adapter") or {}).get("discovering") and self.scanning_until:
            self.sh.bz.scan(False)
        self.win.set_visible(False)
        self.on_close()


class Menu:
    """The right-click menu: a short list, keyboard and mouse."""

    def __init__(self, sh, on_close, on_panel):
        self.sh, self.on_close, self.on_panel = sh, on_close, on_panel
        Gtk = sh.Gtk
        self.state = B.unavailable()
        self.win = Gtk.Window(title="Bluetooth")
        self.win.add_css_class("bt-win")
        self.win.set_decorated(False)
        self.win.set_resizable(False)
        sh.style(self.win.get_display())
        self.frame = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.frame.add_css_class("bt-frame")
        self.frame.set_size_request(300, -1)
        self.list = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.frame.append(sh.label("BLUETOOTH", "bt-eyebrow", "Bluetooth's quick menu: ↑ ↓ and Enter, or click"))
        rule = Gtk.Box()
        rule.add_css_class("bt-rule")
        self.frame.append(rule)
        self.frame.append(self.list)
        self.win.set_child(sh.frame_overlay(self.frame))
        keys = Gtk.EventControllerKey()
        keys.connect("key-pressed", self.on_key)
        self.win.add_controller(keys)
        self.win.connect("close-request", lambda *_: self.close() or True)
        self.sig = None
        self.pending = 0

    def changed(self, st):
        self.state = st
        items = menu_items(st)
        sig = json.dumps(items)
        if sig == self.sig:
            return
        self.sig = sig
        sh, Gtk = self.sh, self.sh.Gtk
        focus_id = getattr(self.win.get_focus(), "_bt_id", None)
        _clear(self.list)
        first = None
        for iid, label, right, hint, ok in items:
            if iid.startswith("dev:") and not any(c._bt_id.startswith("dev:") for c in self._children()):
                self.list.append(sh.label("DEVICES", "bt-section", "Paired devices: click to connect or disconnect"))
            b = Gtk.Button()
            b.add_css_class("bt-item")
            b._bt_id = iid
            box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
            box.append(sh.label(label, "bt-item-label", hexpand=True, ellipsize=3, max_width_chars=26))
            r = sh.label(right, "bt-item-right" + (" bt-dimmed" if right in ("OFF", "CONNECT") else ""))
            box.append(r)
            b.set_child(box)
            b.set_tooltip_text(hint)
            b.set_sensitive(ok)
            b.connect("clicked", lambda *_, i=iid: self.pick(i))
            self.list.append(b)
            if first is None and ok:
                first = b
            if iid == focus_id:
                first = b
        if first is not None:
            first.grab_focus()

    def _children(self):
        c = self.list.get_first_child()
        while c is not None:
            if hasattr(c, "_bt_id"):
                yield c
            c = c.get_next_sibling()

    def pick(self, iid):
        st, bz = self.state, self.sh.bz
        a = st.get("adapter") or {}

        def report(what):
            def back(ok, err):
                self.pending -= 1
                if not ok:
                    B.notify("Bluetooth", f"{what}: {err}", "bt", tag="bt-menu", urgency="normal", timeout=6000)
                if self.pending <= 0:
                    self.on_close()
            self.pending += 1
            return back
        if iid == "power":
            bz.power(not a.get("powered"), report("Bluetooth on/off"))
        elif iid == "visible":
            bz.discoverable(not a.get("discoverable"), report("Visible"))
        elif iid.startswith("dev:"):
            d = next((x for x in st.get("paired", []) if x["mac"] == iid[4:]), None)
            if d is not None:
                (bz.disconnect if d["connected"] else bz.connect)(d["path"], report(d["name"]))
        elif iid == "panel":
            self.win.set_visible(False)
            self.on_panel()
            return
        elif iid == "settings":
            self.sh.open_settings()
        self.win.set_visible(False)
        if self.pending <= 0:
            self.on_close()

    def on_key(self, ctrl, keyval, keycode, state):
        if keyval == self.sh.Gdk.KEY_Escape:
            self.close()
            return True
        return False

    def close(self):
        self.win.set_visible(False)
        self.on_close()


def _busy(on):
    try:
        if on:
            with open(BUSY, "w") as f:
                f.write(str(os.getpid()))
        else:
            os.unlink(BUSY)
    except OSError:
        pass


def _cli(args, back):
    """`bromigos bluetooth ARGS --json`, async: back(ok, said-or-error)."""
    from gi.repository import Gio
    try:
        p = Gio.Subprocess.new(["bromigos", "bluetooth", *args, "--json"],
                               Gio.SubprocessFlags.STDOUT_PIPE | Gio.SubprocessFlags.STDERR_SILENCE)
    except Exception as e:
        back(False, str(e))
        return

    def done(proc, res):
        try:
            _, out, _ = proc.communicate_utf8_finish(res)
            doc = json.loads(out or "{}")
        except Exception as e:
            back(False, str(e))
            return
        back(doc.get("ok", True), doc.get("said") if doc.get("ok", True) else doc.get("error", "failed"))
    p.communicate_utf8_async(None, None, done)


# ------------------------------------------------------------------ the app
class App:
    def __init__(self):
        self.Gtk, self.Gdk, self.GLib, self.LS = load_gtk()
        from gi.repository import Gio
        self.app = self.Gtk.Application(application_id=APP_ID, flags=Gio.ApplicationFlags.HANDLES_COMMAND_LINE)
        self.app.connect("command-line", self.on_cmd)
        self.sh = None
        self.view = None
        self.catch = None

    def run(self, argv):
        return self.app.run(argv)

    def ensure(self):
        if self.sh is not None:
            return
        self.sh = Shell(self.Gtk, self.Gdk, self.GLib, self.LS)
        self.sh.bz = B.Bluez(self.changed)
        try:
            self.sh.bz.start()
        except Exception:
            pass
        self.sh.refresh_audio(lambda: self.view and self.changed(self.sh.bz.state()))

    def changed(self, st):
        if self.view is not None:
            self.view.changed(st)

    def on_cmd(self, app, cl):
        args = cl.get_arguments()[1:]
        what = args[0] if args else "panel"
        self.ensure()
        cur = type(self.view).__name__.lower() if self.view is not None else None
        if what == "close" or (what == cur and what in ("panel", "menu")):
            if self.view is not None:
                self.view.close()
            return 0
        if self.view is not None:
            self.view.win.set_visible(False)
            self.view = None
        self.open(what, args[1:])
        return 0

    def open(self, what, rest):
        sh = self.sh
        self.app.hold()
        if self.catch is None:
            self.catch = sh.catcher(lambda: self.view and self.view.close())
            if self.catch is not None:
                self.catch.set_application(self.app)
                self.catch.present()
        if what == "menu":
            v = Menu(sh, self.closed, lambda: self.switch("panel"))
            width = 300
        else:
            v = Panel(sh, self.closed)
            width = WIDTH
        v.win.set_application(self.app)
        if sh.layer(v.win):
            sh.place(v.win, width)
        self.view = v
        v.changed(sh.bz.state())
        v.win.present()
        if what == "pair" and rest:
            d = sh.bz.find(rest[0]) if B.MAC.match(rest[0]) else None
            if d is None:
                v.say(f"No device {rest[0]}: SCAN finds it in pairing mode", "error")
            else:
                v.pair(d)
        elif what == "scan":
            v.toggle_scan()

    def switch(self, what):
        self.app.release()
        self.view = None
        self.open(what, [])

    def closed(self):
        if self.view is None:
            return
        self.view = None
        if self.catch is not None:
            self.catch.destroy()
            self.catch = None
        self.app.release()
        self.GLib.idle_add(lambda: self.app.quit() or False)


def main(argv=None):
    return App().run([sys.argv[0]] + list(sys.argv[1:] if argv is None else argv))


# ------------------------------------------------------------------ offscreen
def render(path, view="panel", scan=False, prompt=None, t=1.4, settle=1.5):
    """Draw the panel ("panel") or the menu ("menu") to a PNG against the bluez
    BROMIGOS_BLUEZ_BUS points at. scan: scanning, with what it found; prompt: ("confirm",
    MAC) shows that pairing question. t: the holograms' moment."""
    os.environ.setdefault("GSK_RENDERER", "cairo")
    Gtk, Gdk, GLib, LS = load_gtk()
    if not Gtk.init_check():
        raise RuntimeError("no display to render on")
    clock = {"t": 100.0}
    sh = Shell(Gtk, Gdk, GLib, None, now=lambda: clock["t"])
    sh.t0 = clock["t"] - t
    loop = GLib.MainLoop()
    holder = {}
    sh.bz = B.Bluez(lambda st: holder["v"].changed(st) if "v" in holder else None).start()
    if view == "menu":
        v = Menu(sh, lambda: None, lambda: None)
    else:
        v = Panel(sh, lambda: None)
        v.animate = lambda: None
    holder["v"] = v
    got = {}

    def ready_audio():
        got["audio"] = True
        v.changed(sh.bz.state())
    sh.refresh_audio(ready_audio)
    v.changed(sh.bz.state())
    if scan and view != "menu":
        v.toggle_scan()
    out = {}
    seen = []

    def go_prompt():
        if prompt and view != "menu":
            what, mac = prompt
            d = sh.bz.find(mac)
            if d is None:                   # not found by the scan yet
                return True
            v.pairing = d
            v.ops[mac] = "pairing"
            v.prompt(what, d["path"], "123456" if what == "confirm" else ("123456", 2) if what == "type" else None,
                     lambda *_: None)
        return False
    GLib.timeout_add(int(settle * 1000) - 200, go_prompt)

    def snap():
        if clock["t"] < 100.0 + settle:
            clock["t"] += 0.1
            if scan:
                for mac in list(v.seen if hasattr(v, "seen") else []):
                    v.seen[mac] = 100.0 + settle - 2.0      # found a moment ago: no ring
            return True
        frame = v.win.get_child()
        w, h = frame.get_width(), frame.get_height()
        seen.append((w, h))
        if w <= 1 or h <= 1 or seen[-2:] != [(w, h)] * 2:
            return True
        paintable = Gtk.WidgetPaintable.new(frame)
        snapshot = Gtk.Snapshot.new()
        paintable.snapshot(snapshot, w, h)
        node = snapshot.to_node()
        if node is None:                    # not drawn yet: the next frame
            return True
        texture = v.win.get_renderer().render_texture(node, None)
        texture.save_to_png(path)
        out["size"] = (w, h)
        loop.quit()
        return False
    v.win.present()
    GLib.timeout_add(100, snap)
    GLib.timeout_add(20000, loop.quit)
    loop.run()
    v.win.destroy()
    if "size" not in out:
        raise RuntimeError("the panel never laid out")
    return out["size"]
