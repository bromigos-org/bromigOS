"""Edit mode: arrange the panels on the desktop by dragging them (docs/widgets.md, "Edit
mode"). bromigos-widgets runs it; Super+Alt+W, `bromigos panels edit`, the menu, Settings
and a right-click on a panel start it.

Why a mode, and not Alt+drag: Hyprland's own Alt+drag (or Super+drag) moves windows and
catches the drag before a panel sees it, and a panel without keyboard focus never learns a
modifier is held. So edit mode puts one surface over the panels' monitor:

  * the panels move up to the layer above windows, so nothing covers them, and keep
    updating;
  * a transparent *canvas* on the overlay layer above them takes the pointer and the
    keyboard: a frame and a title on each panel, a drag moves it, a corner resizes it
    within its own limits, × hides it; snapping and guides come from arrange.py;
  * a floating *tray*, the widget gallery: every panel, hidden ones too, with on/off
    switches, Add to desktop (a free spot), search and categories; Undo, Redo, Reset,
    Cancel and Done.

Esc or Done saves layout.json (arrange.write: one step, through a dotfiles symlink);
Cancel puts everything back as it was when edit mode began. Keyboard: Tab picks the next
panel, the arrows nudge it (Shift: 10 px; Ctrl: resize), H hides it, F6 moves between
the panels and the tray, Ctrl+Z undoes, Ctrl+Shift+Z redoes.
"""
import cairo
import gi

gi.require_version("Gtk", "3.0")
gi.require_version("GtkLayerShell", "0.1")
from gi.repository import Gdk, GLib, Gtk, GtkLayerShell, Pango  # noqa: E402

import arrange as A  # noqa: E402
import draw as D  # noqa: E402
import gallery as G  # noqa: E402

HANDLE = 12          # px: a corner handle's square
CLOSE = 24           # px: the × button's square
TRAY_W = 400
THUMB_W = 112

# written in the Wick's colours; bromigos_theme retints them to the theme in force
TRAY_CSS = """
.edit-tray { background-color: rgba(PANEL, ALPHA); border: 1px solid #159b09; border-radius: 0; }
.edit-tray * { font-family: "Geist Mono"; color: #9cff8a; }
.edit-tray .tray-title { color: #39ff14; font-weight: bold; letter-spacing: 2px; }
.edit-tray .tray-sub, .edit-tray .card-meta { color: #7e927e; font-size: 11px; }
.edit-tray .section { color: #39ff14; font-size: 11px; letter-spacing: 2px; margin-top: 8px; }
.edit-tray .card { border: 1px solid alpha(#159b09, 0.45); padding: 6px; }
.edit-tray .card.selected { border-color: #39ff14; }
.edit-tray .card-title { font-weight: bold; }
.edit-tray .card-desc { font-size: 12px; }
.edit-tray button { background-image: none; background-color: alpha(#003b00, 0.6); border: 1px solid #159b09;
                    border-radius: 0; box-shadow: none; padding: 2px 8px; min-height: 22px; }
.edit-tray button:hover { background-color: alpha(#39ff14, 0.18); }
.edit-tray button:focus, .edit-tray switch:focus, .edit-tray entry:focus { outline: 2px solid #39ff14; outline-offset: 1px; }
.edit-tray button.primary { border-color: #39ff14; color: #39ff14; }
.edit-tray button.danger, .edit-tray button.danger label { color: #ff766f; border-color: #ff766f; }
.edit-tray button.chip { padding: 0 6px; min-height: 18px; font-size: 11px; }
.edit-tray button.chip:checked { background-color: #39ff14; }
.edit-tray button.chip:checked label { color: #000500; }
.edit-tray entry { background-color: alpha(#000500, 0.8); border: 1px solid #159b09; border-radius: 0; color: #9cff8a;
                   caret-color: #39ff14; }
.edit-tray switch { border-radius: 0; background-color: #003b00; background-image: none; border: 1px solid #159b09;
                    min-width: 44px; min-height: 20px; color: transparent; }
.edit-tray switch:checked { background-color: #39ff14; }
.edit-tray switch slider { border-radius: 0; background-color: #9cff8a; background-image: none; border: 1px solid #000500;
                           min-width: 20px; min-height: 18px; }
.edit-tray switch image { color: transparent; -gtk-icon-transform: scale(0); }
.edit-tray switch:checked slider { background-color: #000500; border-color: #39ff14; }
.edit-tray .confirm { border: 1px solid #ff766f; padding: 6px; }
.edit-tray scrolledwindow, .edit-tray viewport { background-color: transparent; }
"""


def tray_css():
    alpha = "1.0" if D.T.high_contrast() else "0.94"
    return D.T.retint(TRAY_CSS).replace("PANEL", ", ".join(str(v) for v in D.T.rgb255("panel"))) \
        .replace("ALPHA", alpha).encode()


def _key_of(name):
    return {"system": "Super+S", "network": "Super+N", "storage": "Super+D", "workbench": "Super+B",
            "notes": "Super+F", "shortcuts": "Super+K"}.get(name)


class Editor:
    def __init__(self, app, select=None):
        self.app = app
        self.start = app.state()                  # Cancel goes back to this
        self.start_monitor = (app.monitor_setting, app.monitor_name)
        self.history = A.History()
        self.drag = None
        self.tray_drag = None
        self.guides = []
        self.hover = None                         # (name, part)
        self.query, self.category = "", None
        self.tray_pos = None                      # (x, y) once the tray is dragged
        self.cards = {}
        self.closed = False
        self.asked = {}                           # each panel's available(), asked once per opening
        vis = self.visible_names()
        self.sel = select if select in vis else (vis[0] if vis else None)
        self.css = Gtk.CssProvider()
        self.css.load_from_data(tray_css())
        Gtk.StyleContext.add_provider_for_screen(Gdk.Screen.get_default(), self.css,
                                                 Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION + 1)
        notes = app.windows.get("notes")
        if notes is not None and hasattr(notes, "release"):
            GtkLayerShell.set_keyboard_mode(notes.win, GtkLayerShell.KeyboardMode.NONE)
        app.raise_panels(True)
        self.build()
        self._thumbs = GLib.timeout_add(2000, self.tick_thumbs)
        GLib.timeout_add(150, self.rescue)

    def rescue(self):
        """A shown panel that's off the screen (a layout from a bigger monitor) comes onto
        it, in a free spot, so it can be reached; Cancel puts it back."""
        W, H = self.size()
        lost = [n for n in self.visible_names() if not self.reachable(self.app.windows[n].rect(), W, H)]
        done = []
        for n in lost:
            win = self.app.windows[n]
            taken = [r for k, r in self.rects().items() if k not in lost or k in done]
            done.append(n)
            win.place(*A.place(*win.size_now(), taken, (W, H), self.app.avoid((W, H)), self.tray_rects()))
        if lost:
            self.status.set_text(f"Brought onto the screen: {', '.join(self.title(n) for n in lost)}. "
                                 "Done keeps them there; Cancel puts them back.")
            self.area.queue_draw()
        return False

    @staticmethod
    def reachable(rect, W, H, grip=48):
        x, y, w, h = rect
        return x + w >= grip and y + h >= grip and x <= W - grip and y <= H - grip

    def tray_rects(self):
        t = self.tray.get_allocation()
        return [(t.x, t.y, t.width, t.height)] if self.tray.get_visible() and t.width > 1 else []

    # ------------------------------------------------------------------ the surface
    def build(self):
        win = Gtk.Window()
        win.get_style_context().add_class("bromigos")
        win.set_app_paintable(True)
        vis = win.get_screen().get_rgba_visual()
        if vis:
            win.set_visual(vis)
        GtkLayerShell.init_for_window(win)
        GtkLayerShell.set_namespace(win, "bromigos-widgets-edit")
        GtkLayerShell.set_layer(win, GtkLayerShell.Layer.OVERLAY)
        GtkLayerShell.set_monitor(win, self.app.mon)
        for e in (GtkLayerShell.Edge.TOP, GtkLayerShell.Edge.BOTTOM, GtkLayerShell.Edge.LEFT,
                  GtkLayerShell.Edge.RIGHT):
            GtkLayerShell.set_anchor(win, e, True)
        GtkLayerShell.set_exclusive_zone(win, 0)          # under the bar: the panels' own area
        GtkLayerShell.set_keyboard_mode(win, GtkLayerShell.KeyboardMode.EXCLUSIVE)
        self.win = win
        overlay = Gtk.Overlay()
        area = Gtk.DrawingArea()
        area.set_can_focus(True)
        area.set_has_tooltip(True)
        area.add_events(Gdk.EventMask.BUTTON_PRESS_MASK | Gdk.EventMask.BUTTON_RELEASE_MASK
                        | Gdk.EventMask.POINTER_MOTION_MASK | Gdk.EventMask.LEAVE_NOTIFY_MASK)
        area.connect("draw", self.on_draw)
        area.connect("button-press-event", self.on_press)
        area.connect("button-release-event", self.on_release)
        area.connect("motion-notify-event", self.on_motion)
        area.connect("query-tooltip", self.on_tip)
        area.connect("size-allocate", lambda *_: self.place_tray())
        self.area = area
        overlay.add(area)
        self.tray = self.build_tray()
        overlay.add_overlay(self.tray)
        win.add(overlay)
        win.connect("key-press-event", self.on_key)
        win.connect("delete-event", lambda *_: (self.done(), True)[1])
        win.show_all()
        self.confirm.hide()
        area.grab_focus()

    def size(self):
        a = self.area.get_allocation()
        if a.width > 1 and a.height > 1:
            return a.width, a.height
        return self.app.area()

    # ------------------------------------------------------------------ panels
    def visible_names(self):
        return [n for n, w in self.app.windows.items() if w.visible()]

    def rects(self):
        return {n: self.app.windows[n].rect() for n in self.visible_names()}

    def others(self, name):
        return [r for n, r in self.rects().items() if n != name]

    def limits(self, name):
        return self.app.windows[name].limits()

    def title(self, name):
        w = self.app.windows.get(name)
        return G.meta_of(w.panel, name)["title"] if getattr(w, "panel", None) is not None else G.NOTES["title"]

    def classes(self, name):
        return self.app.windows[name].classes()

    def hit(self, x, y):
        """(name, part) under the pointer: part is close, nw, ne, sw, se or body."""
        names = self.visible_names()
        if self.sel in names:
            names.remove(self.sel)
            names.append(self.sel)            # the selected one is on top
        for n in reversed(names):
            rx, ry, rw, rh = self.app.windows[n].rect()
            if rx + rw - CLOSE - 4 <= x <= rx + rw - 4 and ry + 4 <= y <= ry + 4 + CLOSE:
                return n, "close"
            for corner, (cx, cy) in (("nw", (rx, ry)), ("ne", (rx + rw, ry)), ("sw", (rx, ry + rh)),
                                     ("se", (rx + rw, ry + rh))):
                if abs(x - cx) <= HANDLE and abs(y - cy) <= HANDLE:
                    return n, corner
            if rx <= x <= rx + rw and ry <= y <= ry + rh:
                return n, "body"
        return None, None

    # ------------------------------------------------------------------ drawing
    def on_draw(self, _w, cr):
        W, H = self.size()
        hc = D.T.high_contrast()
        cr.set_operator(cairo.OPERATOR_SOURCE)
        r, g, b = D.rgb("void")
        cr.set_source_rgba(r, g, b, 0.62 if hc else 0.42)
        cr.paint()
        cr.set_operator(cairo.OPERATOR_OVER)
        D.src(cr, "dim", 0.5 if hc else 0.28)          # the grid, every 32 px
        for gx in range(0, W, 32):
            for gy in range(0, H, 32):
                cr.rectangle(gx, gy, 1.2, 1.2)
        cr.fill()
        rects = self.rects()
        cr.set_operator(cairo.OPERATOR_CLEAR)            # each panel shows through, crisp
        for (x, y, w, h) in rects.values():
            cr.rectangle(x, y, w, h)
        cr.fill()
        cr.set_operator(cairo.OPERATOR_OVER)
        order = [n for n in rects if n != self.sel] + ([self.sel] if self.sel in rects else [])
        for n in order:
            self.draw_frame(cr, n, rects[n], n == self.sel, hc)
        if self.guides:
            D.src(cr, "amber", 1.0)
            cr.set_line_width(2 if hc else 1)
            cr.set_dash([] if hc else [6, 4])
            for axis, pos, lo, hi in self.guides:
                if axis == "v":
                    cr.move_to(pos + 0.5, lo - 12)
                    cr.line_to(pos + 0.5, hi + 12)
                else:
                    cr.move_to(lo - 12, pos + 0.5)
                    cr.line_to(hi + 12, pos + 0.5)
            cr.stroke()
            cr.set_dash([])
        if not rects:
            D.text(cr, W / 2, H / 2 - 10, "NO PANELS ON THE DESKTOP: SWITCH ONE ON IN THE TRAY", 14, "soft",
                   "semibold", align="center")
        return True

    def draw_frame(self, cr, name, rect, selected, hc):
        x, y, w, h = rect
        col = "phosphor" if selected else "dim"
        hov = self.hover if self.hover and self.hover[0] == name else (None, None)
        cr.set_line_width(3 if selected or hc else 1.5)
        D.src(cr, col, 1.0)
        cr.rectangle(x - 1.5, y - 1.5, w + 3, h + 3)
        cr.stroke()
        for corner, (cx, cy) in (("nw", (x, y)), ("ne", (x + w, y)), ("sw", (x, y + h)), ("se", (x + w, y + h))):
            s = HANDLE + (4 if hov[1] == corner else 0)
            D.src(cr, "phosphor" if hov[1] == corner or selected else "dim", 1.0)
            cr.rectangle(cx - s / 2, cy - s / 2, s, s)
            cr.fill()
            D.src(cr, "void", 1.0)
            cr.rectangle(cx - s / 2 + 3, cy - s / 2 + 3, s - 6, s - 6)
            cr.fill()
        # ×
        bx, by = x + w - CLOSE - 4, y + 4
        D.src(cr, "void", 0.95)
        cr.rectangle(bx, by, CLOSE, CLOSE)
        cr.fill()
        D.src(cr, "danger" if hov[1] == "close" else "static", 1.0)
        cr.set_line_width(1)
        cr.rectangle(bx + 0.5, by + 0.5, CLOSE - 1, CLOSE - 1)
        cr.stroke()
        cr.set_line_width(2)
        cr.move_to(bx + 7, by + 7)
        cr.line_to(bx + CLOSE - 7, by + CLOSE - 7)
        cr.move_to(bx + CLOSE - 7, by + 7)
        cr.line_to(bx + 7, by + CLOSE - 7)
        cr.stroke()
        # the tag: its name, size and place, inside its foot (the picked, the hovered and the
        # dragged panel only: the others' own headers name them)
        drag = self.drag and self.drag["name"] == name
        if not (selected or drag or hov[0] == name):
            return
        cls = self.app.windows[name].size_class()
        many = len(self.classes(name)) > 1
        label = f"{self.title(name)}   {cls.upper() + ' ' if many and cls else ''}{w}×{h}   AT {x},{y}"
        lay = D.layout(cr, label, 11, "semibold", 0.12)
        tw = min(lay.get_pixel_size()[0] + 16, w - HANDLE)
        ty = y + h - 24
        D.src(cr, "phosphor" if selected else "guard", 1.0)
        cr.rectangle(x + HANDLE / 2 + 2, ty, tw, 22)
        cr.fill()
        D.text(cr, x + HANDLE / 2 + 10, ty + 4, label, 11, "void" if selected else "soft", "semibold", 0.12)

    # ------------------------------------------------------------------ hints
    def on_tip(self, _w, x, y, _kb, tooltip):
        name, part = self.hit(x, y)
        if not name:
            tooltip.set_text("Edit mode: drag a panel to move it, or a corner to resize it. "
                             "Esc saves and leaves; Cancel in the tray puts everything back.")
            return True
        t = self.title(name)
        (lw, lh), (hw, hh) = self.limits(name)
        cs = self.classes(name)
        sizes = ", ".join(f"{c[0]} {c[1][0]}×{c[1][1]} to {c[2][0]}×{c[2][1]}" for c in cs)
        tooltip.set_text({
            "close": f"Hide {t} (H). It stays in the tray: switch it on there to bring it back.",
            "body": f"{t}: drag to move it. It snaps to an 8 px grid and to the other panels' edges; "
                    "hold Ctrl to place it freely. Arrow keys nudge it (Shift: 10 px).",
        }.get(part, (f"Drag to resize {t}. Its sizes: {sizes} px; between them it snaps to the nearest, "
                     "and each lays it out its own way." if len(cs) > 1 else
                     f"Drag to resize {t}: {lw}×{lh} to {hw}×{hh} px.") + " Ctrl+arrows resize it from the keyboard."))
        return True

    def set_cursor(self, part):
        names = {"body": "move", "close": "pointer", "nw": "nw-resize", "se": "se-resize",
                 "ne": "ne-resize", "sw": "sw-resize", "grabbing": "grabbing"}
        gw = self.area.get_window()
        if gw:
            gw.set_cursor(Gdk.Cursor.new_from_name(self.area.get_display(), names[part]) if part in names else None)

    # ------------------------------------------------------------------ the pointer
    def on_press(self, _w, ev):
        self.area.grab_focus()
        if ev.type != Gdk.EventType.BUTTON_PRESS:
            return True
        name, part = self.hit(ev.x, ev.y)
        if ev.button != 1:
            if name:
                self.select(name)
            return True
        if not name:
            self.select(None)
            return True
        self.select(name)
        if part == "close":
            self.hide(name)
            return True
        self.to_front(name)
        self.drag = {"name": name, "part": part, "x0": ev.x, "y0": ev.y, "rect": self.app.windows[name].rect(),
                     "before": self.app.state()}
        self.set_cursor("grabbing" if part == "body" else part)
        return True

    def on_motion(self, _w, ev):
        if not self.drag:
            h = self.hit(ev.x, ev.y)
            if h != self.hover:
                self.hover = h
                self.set_cursor(h[1])
                self.area.queue_draw()
            return True
        d = self.drag
        free = bool(ev.get_state() & Gdk.ModifierType.CONTROL_MASK)
        x, y, w, h = d["rect"]
        dx, dy = ev.x - d["x0"], ev.y - d["y0"]
        name = d["name"]
        if d["part"] == "body":
            nx, ny, self.guides = A.snap_move((x + dx, y + dy, w, h), self.others(name), self.size(), snap=not free)
            self.app.windows[name].place(nx, ny)
        else:
            c = d["part"]
            px = (x if "w" in c else x + w) + dx
            py = (y if "n" in c else y + h) + dy
            r, self.guides = A.snap_resize(d["rect"], c, px, py, self.others(name), self.size(), self.limits(name),
                                           snap=not free)
            r, _cls = A.resize_in_classes(r, c, self.classes(name), self.size())
            self.app.windows[name].place(r[0], r[1])
            self.app.windows[name].resize(r[2], r[3])
        self.area.queue_draw()
        return True

    def on_release(self, _w, ev):
        if self.drag:
            d, self.drag = self.drag, None
            if self.app.state() != d["before"]:
                self.history.push(d["before"])
                self.changed()
            self.guides = []
            self.hover = self.hit(ev.x, ev.y)
            self.set_cursor(self.hover[1])
            self.area.queue_draw()
        return True

    # ------------------------------------------------------------------ the keyboard
    def on_key(self, _w, ev):
        k = ev.keyval
        state = ev.get_state()
        ctrl = bool(state & Gdk.ModifierType.CONTROL_MASK)
        shift = bool(state & Gdk.ModifierType.SHIFT_MASK)
        if k == Gdk.KEY_Escape:
            if self.confirm.get_visible():
                self.confirm.hide()
            elif self.tray_entry_focused() and self.search.get_text():
                self.search.set_text("")
            else:
                self.done()
            return True
        if ctrl and k in (Gdk.KEY_z, Gdk.KEY_Z):
            self.redo() if shift else self.undo()
            return True
        if ctrl and k in (Gdk.KEY_y, Gdk.KEY_Y):
            self.redo()
            return True
        if k == Gdk.KEY_F6:
            if self.area.has_focus():
                self.search.grab_focus()
            else:
                self.area.grab_focus()
            return True
        if self.tray_entry_focused() or not self.area.has_focus():
            return False
        if k in (Gdk.KEY_Tab, Gdk.KEY_ISO_Left_Tab):
            self.cycle(-1 if (shift or k == Gdk.KEY_ISO_Left_Tab) else 1)
            return True
        arrows = {Gdk.KEY_Left: (-1, 0), Gdk.KEY_Right: (1, 0), Gdk.KEY_Up: (0, -1), Gdk.KEY_Down: (0, 1)}
        if k in arrows and self.sel in self.visible_names():
            dx, dy = arrows[k]
            step = 10 if shift else 1
            if ctrl:
                self.resize_by(self.sel, dx * 8, dy * 8)
            else:
                self.nudge(self.sel, dx * step, dy * step)
            return True
        if k in (Gdk.KEY_h, Gdk.KEY_H, Gdk.KEY_Delete) and self.sel in self.visible_names():
            self.hide(self.sel)
            return True
        return False

    def tray_entry_focused(self):
        return isinstance(self.win.get_focus(), Gtk.Entry)

    def cycle(self, step):
        names = self.visible_names()
        if not names:
            return
        i = names.index(self.sel) if self.sel in names else -1
        self.select(names[(i + step) % len(names)])

    # ------------------------------------------------------------------ changes
    def select(self, name):
        self.sel = name
        for n, c in self.cards.items():
            (c.get_style_context().add_class if n == name else c.get_style_context().remove_class)("selected")
        self.area.queue_draw()

    def to_front(self, name):
        """The picked panel over any it overlaps: mapped again, it's the top of its layer."""
        r = self.app.windows[name].rect()
        if any(A.overlaps(r, o) for o in self.others(name)):
            win = self.app.windows[name].win
            win.hide()
            win.show_all()

    def record(self, key=None):
        self.history.push(self.app.state(), key=key)

    def nudge(self, name, dx, dy):
        x, y, w, h = self.app.windows[name].rect()
        nx, ny, _ = A.snap_move((x + dx, y + dy, w, h), [], self.size(), snap=False)
        if (nx, ny) != (x, y):
            self.record(key=f"nudge {name}")
            self.app.windows[name].place(nx, ny)
            self.changed()

    def resize_by(self, name, dw, dh):
        x, y, w, h = self.app.windows[name].rect()
        W, H = self.size()
        nw, nh = A.clamp_size(min(w + dw, W - x), min(h + dh, H - y), self.limits(name))
        nw, nh, _cls = A.fit_class(self.classes(name), nw, nh)
        if (nw, nh) != (w, h):
            self.record(key=f"size {name}")
            self.app.windows[name].resize(nw, nh)
            self.changed()

    def hide(self, name):
        self.record()
        self.app.set_visible(name, False)
        if self.sel == name:
            vis = self.visible_names()
            self.sel = vis[0] if vis else None
        self.changed(rebuild=True)

    def show(self, name, free=False):
        """On, where it was, or in a free spot when that's taken or off the area (always,
        with free: Add to desktop)."""
        self.record()
        win = self.app.windows[name]
        if free:                                  # Add to desktop: at its default size
            win.set_size_class(G.meta_of(getattr(win, "panel", None), name)["default_size"]
                               if getattr(win, "panel", None) is not None else "standard")
        x, y, w, h = win.rect()
        taken = [r for n, r in self.rects().items() if n != name]
        if free or not A.fits((x, y, w, h), taken, self.size()):
            tray = self.tray_rects()
            spot = A.place(w, h, taken, self.size(), self.app.avoid(self.size()) + tray, tray)
            win.place(*spot)
        self.app.set_visible(name, True)
        self.select(name)
        self.changed(rebuild=True)

    def undo(self):
        st = self.history.undo(self.app.state())
        if st is not None:
            self.app.apply_state(st)
            self.changed(rebuild=True)

    def redo(self):
        st = self.history.redo(self.app.state())
        if st is not None:
            self.app.apply_state(st)
            self.changed(rebuild=True)

    def reset(self):
        self.confirm.hide()
        try:
            default = A.state_of(A.read_default())
        except (OSError, ValueError):
            return
        self.record()
        st = self.app.state()
        for n, s in default.items():
            if n in st:
                st[n].update(s)
        self.app.apply_state(st)
        self.changed(rebuild=True)

    def changed(self, rebuild=False):
        self.area.queue_draw()
        self.undo_b.set_sensitive(self.history.can_undo())
        self.redo_b.set_sensitive(self.history.can_redo())
        if rebuild:                     # after the switch that asked has finished its signal
            GLib.idle_add(lambda: (not self.closed and self.fill_cards(), False)[1])

    # ------------------------------------------------------------------ leaving
    def done(self):
        if self.closed:
            return
        try:
            self.app.save_layout(self.start)
        except (OSError, ValueError) as e:
            self.status.set_text(f"Not saved: {e}")
            return
        self.close()

    def cancel(self):
        if self.closed:
            return
        if (self.app.monitor_setting, self.app.monitor_name) != self.start_monitor:
            self.app.monitor_setting = self.start_monitor[0]
            self.app.move_to_monitor(self.start_monitor[1])
        self.app.apply_state(self.start)
        self.close()

    def close(self):
        self.closed = True
        GLib.source_remove(self._thumbs)
        self.app.raise_panels(False)
        Gtk.StyleContext.remove_provider_for_screen(Gdk.Screen.get_default(), self.css)
        self.win.destroy()
        self.app.editor = None
        self.app.write_health()
        notes = self.app.windows.get("notes")
        if notes is not None and hasattr(notes, "release"):
            notes.release()

    def leave_then(self, argv):
        """Saves, leaves edit mode, then runs argv (Settings, for a widget's own settings)."""
        self.done()
        if self.closed:
            self.app.launch(argv)

    def restyle(self):
        self.css.load_from_data(tray_css())
        self.area.queue_draw()
        self.tick_thumbs()

    def monitor_moved(self):
        """The panels went to another output: the canvas goes with them."""
        tray_pos = self.tray_pos
        self.win.destroy()
        self.build()
        self.tray_pos = tray_pos
        GLib.idle_add(self.fit_area)

    def fit_area(self):
        """After a move to a smaller output: every panel back inside the area."""
        W, H = self.size()
        for n in self.visible_names():
            x, y, w, h = self.app.windows[n].rect()
            nx, ny, _ = A.snap_move((x, y, w, h), [], (W, H), snap=False)
            if (nx, ny) != (x, y):
                self.app.windows[n].place(nx, ny)
        self.area.queue_draw()
        return False

    # ------------------------------------------------------------------ the tray (the widget gallery)
    def button(self, label, hint, cb, cls=None):
        b = Gtk.Button(label=label)
        b.set_tooltip_text(hint)
        if cls:
            b.get_style_context().add_class(cls)
        b.connect("clicked", lambda *_: cb())
        return b

    def label(self, text, cls=None, wrap=False, xalign=0.0):
        lb = Gtk.Label(label=text, xalign=xalign)
        if cls:
            lb.get_style_context().add_class(cls)
        if wrap:
            lb.set_line_wrap(True)
            lb.set_line_wrap_mode(Pango.WrapMode.WORD_CHAR)
            lb.set_max_width_chars(30)
        return lb

    def build_tray(self):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        box.get_style_context().add_class("edit-tray")
        box.set_size_request(TRAY_W, -1)
        box.set_halign(Gtk.Align.START)
        box.set_valign(Gtk.Align.START)
        for side in ("start", "end", "top", "bottom"):
            getattr(box, f"set_margin_{side}")(0)
        inner = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        inner.set_border_width(10)
        box.pack_start(inner, True, True, 0)

        head = Gtk.EventBox()
        head.add_events(Gdk.EventMask.BUTTON_PRESS_MASK | Gdk.EventMask.BUTTON_RELEASE_MASK
                        | Gdk.EventMask.POINTER_MOTION_MASK)
        head.set_tooltip_text("The widget gallery. Drag this bar to move the tray out of the way.")
        hb = Gtk.Box(spacing=8)
        hb.pack_start(self.label("WIDGETS", "tray-title"), False, False, 0)
        hb.pack_start(self.label("EDIT MODE", "tray-sub"), False, False, 0)
        self.fold = self.button("Hide list", "Folds the list away, leaving the buttons; click again to unfold it",
                                self.toggle_fold)
        hb.pack_end(self.fold, False, False, 0)
        head.add(hb)
        head.connect("button-press-event", self.tray_press)
        head.connect("button-release-event", lambda *_: setattr(self, "tray_drag", None))
        head.connect("motion-notify-event", self.tray_motion)
        inner.pack_start(head, False, False, 0)

        self.body = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        help_ = self.label("Drag a panel to move it, or a corner to resize it. Ctrl places freely. "
                           "Tab picks a panel, arrows nudge it, H hides it, F6 comes here.", "tray-sub", wrap=True)
        help_.set_tooltip_text("Every way to edit: the pointer, or the keyboard alone")
        self.body.pack_start(help_, False, False, 0)
        self.search = Gtk.SearchEntry()
        self.search.set_placeholder_text("Search widgets")
        self.search.set_tooltip_text("Finds widgets by name, what they show, what they read or who made them")
        self.search.connect("search-changed", lambda e: self.set_query(e.get_text()))
        self.body.pack_start(self.search, False, False, 0)
        chips = Gtk.FlowBox()
        chips.set_selection_mode(Gtk.SelectionMode.NONE)
        chips.set_max_children_per_line(4)
        chips.set_min_children_per_line(4)
        chips.set_column_spacing(4)
        chips.set_row_spacing(4)
        self.chips = {}
        for cat, title in [(None, "All")] + [(c, G.CATEGORY_NAMES[c].split(" ")[0]) for c in G.CATEGORIES]:
            t = Gtk.ToggleButton(label=title)
            t.get_style_context().add_class("chip")
            t.set_active(cat is None)
            t.set_tooltip_text("Every widget" if cat is None else f"Only {G.CATEGORY_NAMES[cat].lower()} widgets")
            t.connect("toggled", self.chip_toggled, cat)
            self.chips[cat] = t
            chips.add(t)
        self.body.pack_start(chips, False, False, 0)
        mons = self.app.monitors()
        if len(mons) > 1:
            mb = Gtk.Box(spacing=6)
            mb.pack_start(self.label("Monitor", "tray-sub"), False, False, 0)
            combo = Gtk.ComboBoxText()
            for m in mons:
                combo.append(m, m)
            combo.set_active_id(self.app.monitor_name)
            combo.set_tooltip_text("The output the panels go on: they all move there now, and stay there "
                                   "when you save")
            combo.connect("changed", lambda c: c.get_active_id() and self.app.move_to_monitor(c.get_active_id(),
                                                                                            chosen=True))
            mb.pack_start(combo, True, True, 0)
            self.body.pack_start(mb, False, False, 0)
        self.scroll = Gtk.ScrolledWindow()
        self.scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        self.scroll.set_propagate_natural_height(True)
        self.list = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        self.scroll.add(self.list)
        self.body.pack_start(self.scroll, True, True, 0)
        more = self.button("Get more widgets…", "Saves, leaves edit mode and opens Settings › Widgets at the "
                                                "community catalog, where you can install more", lambda:
                           self.leave_then(["bromigos", "settings", "widgets#more"]))
        self.body.pack_start(more, False, False, 0)
        inner.pack_start(self.body, True, True, 0)

        self.confirm = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        self.confirm.get_style_context().add_class("confirm")
        self.confirm.pack_start(self.label("Put every panel back where bromigOS puts it, at its first size? "
                                           "Undo brings yours back.", wrap=True), False, False, 0)
        cb = Gtk.Box(spacing=6)
        cb.pack_end(self.button("Reset", "Moves every panel to bromigOS's default layout (Ctrl+Z undoes it)",
                                self.reset, "danger"), False, False, 0)
        cb.pack_end(self.button("Keep mine", "Leaves the layout as it is", self.confirm.hide), False, False, 0)
        self.confirm.pack_start(cb, False, False, 0)
        inner.pack_start(self.confirm, False, False, 0)

        foot = Gtk.Box(spacing=4)
        self.undo_b = self.button("Undo", "Undoes the last change (Ctrl+Z)", self.undo)
        self.redo_b = self.button("Redo", "Does the undone change again (Ctrl+Shift+Z)", self.redo)
        self.undo_b.set_sensitive(False)
        self.redo_b.set_sensitive(False)
        foot.pack_start(self.undo_b, False, False, 0)
        foot.pack_start(self.redo_b, False, False, 0)
        foot.pack_start(self.button("Reset…", "Asks first, then puts every panel back in bromigOS's default layout",
                                    lambda: self.confirm.show_all()), False, False, 0)
        foot.pack_end(self.button("Done", "Saves the layout and leaves edit mode (Esc)", self.done, "primary"),
                      False, False, 0)
        foot.pack_end(self.button("Cancel", "Leaves edit mode and puts everything back as it was when it began",
                                  self.cancel), False, False, 0)
        inner.pack_start(foot, False, False, 0)
        self.status = self.label("", "tray-sub", wrap=True)
        inner.pack_start(self.status, False, False, 0)
        self.fill_cards()
        return box

    def place_tray(self):
        W, H = self.size()
        tw = max(TRAY_W, self.tray.get_allocated_width())
        x, y = self.tray_pos or (W - tw - 24, 16)
        x = max(0, min(x, W - tw))
        y = max(0, min(y, H - 120))
        self.tray.set_margin_start(int(x))
        self.tray.set_margin_top(int(y))
        self.scroll.set_max_content_height(max(160, H - y - 380))

    def tray_press(self, _w, ev):
        if ev.button == 1:
            W, H = self.size()
            self.tray_drag = (ev.x_root, ev.y_root, self.tray.get_margin_start(), self.tray.get_margin_top())
        return True

    def tray_motion(self, _w, ev):
        if self.tray_drag:
            x0, y0, mx, my = self.tray_drag
            self.tray_pos = (mx + ev.x_root - x0, my + ev.y_root - y0)
            self.place_tray()
        return True

    def toggle_fold(self):
        vis = not self.body.get_visible()
        self.body.set_visible(vis)
        self.fold.set_label("Hide list" if vis else "Show list")

    def set_query(self, text):
        self.query = text.strip().lower()
        self.fill_cards()

    def chip_toggled(self, btn, cat):
        if getattr(self, "_chipping", False):
            return
        self._chipping = True
        try:
            for c, t in self.chips.items():
                t.set_active(c == cat if btn.get_active() else c is None)
            self.category = cat if btn.get_active() else None
        finally:
            self._chipping = False
        self.fill_cards()

    def items(self):
        exts = G.extensions()
        out = []
        for name, w in self.app.windows.items():
            panel = getattr(w, "panel", None)
            meta = G.notes_meta() if panel is None else G.meta_of(panel, name)
            src = G.source_of(self.app.plugins[name][0]) if name in self.app.plugins else "bromigos"
            e = G.entry(name, dict(meta), src, {name: dict(w.rect_state(), visible=w.visible())},
                        exts.get(name) if src == "extension" else None)
            e["disabled"] = getattr(panel, "disabled", None)
            e["available"], e["unavailable"] = (True, "") if panel is None else G.availability(panel, self.asked)
            out.append(e)
        return out

    def matches(self, e):
        if self.category and e["category"] != self.category:
            return False
        if not self.query:
            return True
        hay = " ".join(str(e.get(k) or "") for k in ("name", "title", "description", "reads", "author", "category"))
        return all(word in hay.lower() for word in self.query.split())

    def fill_cards(self):
        for c in self.list.get_children():
            self.list.remove(c)
        self.cards = {}
        items = [e for e in self.items() if self.matches(e) and G.addable(e)]
        sections = [("ON YOUR DESKTOP", [e for e in items if e["visible"]]),
                    ("BUILT IN", [e for e in items if not e["visible"] and e["source"] in ("bromigos", "homelab")]),
                    ("INSTALLED EXTENSIONS", [e for e in items if not e["visible"] and e["source"] == "extension"]),
                    ("YOUR OWN", [e for e in items if not e["visible"] and e["source"] == "yours"])]
        for title, group in sections:
            if not group:
                continue
            hint = {"ON YOUR DESKTOP": "The widgets on your desktop now",
                    "BUILT IN": "bromigOS's widgets that are off: switch one on, or add it to a free spot",
                    "INSTALLED EXTENSIONS": "Widgets from extensions you installed (bromigos ext) that are off",
                    "YOUR OWN": "Widgets from your own plugin folder that are off"}[title]
            lb = self.label(title, "section")
            lb.set_tooltip_text(hint)
            self.list.pack_start(lb, False, False, 0)
            for e in group:
                self.list.pack_start(self.card(e), False, False, 0)
        if not items:
            self.list.pack_start(self.label("No widget matches. Try other words, or All.", "tray-sub", wrap=True),
                                 False, False, 0)
        self.list.show_all()

    def card(self, e):
        name = e["name"]
        ev = Gtk.EventBox()
        ev.set_tooltip_text(f"{e['title']}: {e['description'] or 'a widget'}"
                            + (" Click to pick it on the desktop." if e["visible"] else ""))
        ev.connect("button-press-event", lambda *_: e["visible"] and self.select(name))
        box = Gtk.Box(spacing=8)
        box.get_style_context().add_class("card")
        if name == self.sel:
            box.get_style_context().add_class("selected")
        th = Gtk.DrawingArea()
        w, h = e["width"] or 470, e["height"] or 200
        th.set_size_request(THUMB_W, max(40, min(96, int(h * THUMB_W / w))))
        th.connect("draw", self.draw_thumb, name)
        th.set_tooltip_text(f"{e['title']} as it is now, small")
        box.pack_start(th, False, False, 0)
        col = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        col.pack_start(self.label(e["title"], "card-title"), False, False, 0)
        if e["description"]:
            col.pack_start(self.label(e["description"], "card-desc", wrap=True), False, False, 0)
        meta = f"by {e['author']}" + (f" · reads {e['reads']}" if e["reads"] else "")
        if e.get("disabled"):
            meta += " · switched off after errors"
        if not e.get("available", True):
            meta += f" · can't show anything here: {e.get('unavailable') or 'not available'}"
            box.set_opacity(0.55)
        ml = self.label(meta, "card-meta", wrap=True)
        ml.set_tooltip_text(f"Who made it ({e['source']}) and what it reads")
        col.pack_start(ml, False, False, 0)
        row = Gtk.Box(spacing=6)
        sw = Gtk.Switch()
        sw.set_active(e["visible"])
        key = _key_of(name)
        sw.set_tooltip_text(f"{e['title']} on or off" + (f" (its key, {key}, shows or hides it any time)" if key else ""))
        sw.connect("notify::active", lambda s, _p: self.show(name) if s.get_active() else self.hide(name))
        row.pack_start(sw, False, False, 0)
        if not e["visible"]:
            row.pack_start(self.button("Add to desktop", f"Puts {e['title']} on the desktop, in a free spot",
                                       lambda: self.show(name, free=True)), False, False, 0)
        if len(e.get("sizes") or []) > 1:
            col.pack_start(self.size_picker(e), False, False, 2)
        if e.get("settings"):
            s = e["settings"]
            target = s["page"] + (f"#{s['key']}" if s.get("key") else "")
            row.pack_start(self.button("Settings…", f"{e['title']}'s own settings ({s['what']}): saves, leaves "
                                                    f"edit mode and opens Settings › {s['page'].title()}",
                                       lambda: self.leave_then(["bromigos", "settings", target])), False, False, 0)
        col.pack_start(row, False, False, 4)
        box.pack_start(col, True, True, 0)
        ev.add(box)
        self.cards[name] = box
        return ev

    def size_picker(self, e):
        """One button per size class; the one it's in now pressed."""
        name = e["name"]
        box = Gtk.Box(spacing=3)
        cur = self.app.windows[name].size_class()
        for c in e["sizes"]:
            b = Gtk.ToggleButton(label=c["name"].title())
            b.get_style_context().add_class("chip")
            b.set_active(c["name"] == cur)
            b.set_tooltip_text(f"{e['title']} at its {c['name']} size: {c['start'][0]}×{c['start'][1]} px "
                               f"(it can be {c['min'][0]}×{c['min'][1]} to {c['max'][0]}×{c['max'][1]})")
            b.connect("clicked", lambda _b, n=c["name"]: self.set_class(name, n))
            box.pack_start(b, False, False, 0)
        return box

    def set_class(self, name, cls):
        win = self.app.windows[name]
        if win.size_class() == cls and win.visible():
            self.changed(rebuild=True)          # the button pressed again: shown as it is
            return
        self.record()
        win.set_size_class(cls)
        x, y, w, h = win.rect()
        W, H = self.size()
        win.place(min(x, max(0, W - w)), min(y, max(0, H - h)))
        if not win.visible():
            self.app.set_visible(name, True)
        self.select(name)
        self.changed(rebuild=True)

    def draw_thumb(self, widget, cr, name):
        win = self.app.windows.get(name)
        if win is None:
            return True
        aw = widget.get_allocated_width()
        ah = widget.get_allocated_height()
        _x, _y, w, h = win.rect()
        s = min(aw / w, ah / h)
        cr.translate((aw - w * s) / 2, (ah - h * s) / 2)
        cr.scale(s, s)
        cr.push_group()
        try:
            panel = getattr(win, "panel", None)
            if panel is None:
                G.draw_notes(cr, w, h, win.lines())
            else:
                panel.render(cr, w, h)
        except Exception:
            pass
        cr.pop_group_to_source()
        cr.paint()
        if not win.visible():
            D.src(cr, "void", 0.45)
            cr.rectangle(0, 0, w, h)
            cr.fill()
        return True

    def tick_thumbs(self):
        if self.body.get_visible():
            for c in self.cards.values():
                c.get_children()[0].queue_draw()
        return True
