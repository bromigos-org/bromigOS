"""The Customize window's Widgets tab (bin/bromigos-theme-switcher, `bromigos customize`):
the widget gallery as cards, like the Themes tab's, from `bromigos panels gallery` and the
catalog's `bromigos ext search --kind widget` (docs/widgets.md, "The widget gallery").

Each card: a picture of the widget, its name, what it shows, who made it and what it
reads; a switch, its sizes, Add to desktop, Settings… (its own form) and Remove for one
you installed or made. The sections: on your desktop, built in, installed extensions,
your own, and Get more (the catalog). Install from URL and a catalog widget's Install…
show what it can do first (bromigos_settings.widgetform.InstallFromURL), in the window's
own sheet.

    tab = WidgetsTab(Gtk, Pango, host)     host: the window (ctx, sheet(), card size, search text)
    tab.widget                             the tab's content
"""
import json
import os
import subprocess

from bromigos_themecards import rgba

CODE = {"live-deck", "widget", "vector-tool", "vector-memory", "homelab-adapter", "command", "hook"}
SECTIONS = [("desktop", "ON YOUR DESKTOP", "The widgets on your desktop now"),
            ("builtin", "BUILT IN", "bromigOS's widgets that are off"),
            ("extensions", "INSTALLED EXTENSIONS", "Widgets from extensions you installed that are off"),
            ("yours", "YOUR OWN", "Widgets from your own plugin folder that are off"),
            ("more", "GET MORE", "Widgets from the community catalog (bromigos-org/extensions): installing one "
                                 "shows what it can do first")]


def cache_dir():
    return os.path.join(os.environ.get("XDG_CACHE_HOME") or os.path.expanduser("~/.cache"),
                        "bromigos", "widgets", "gallery")


def widget_css(c, font=13):
    a = rgba
    return f"""
flowboxchild.wcard {{ padding: 0; border: 1px solid {a(c['dim'], .35)}; background-color: {a(c['void'], .55)}; }}
flowboxchild.wcard:hover {{ border-color: {a(c['primary'], .55)}; }}
flowboxchild.wcard.off .wname {{ color: {c['muted']}; }}
flowboxchild.wcard .wbody {{ padding: 6px 10px 10px 10px; }}
flowboxchild.wcard .wname {{ color: {c['soft']}; font-weight: 700; letter-spacing: 0.12em; font-size: {font}px; }}
flowboxchild.wcard .wdesc {{ color: {c['text']}; font-size: {font - 1}px; }}
flowboxchild.wcard .wmeta {{ color: {c['muted']}; font-size: {font - 2}px; }}
flowboxchild.wcard .wpic {{ background-color: {a(c['void'], .9)}; border-bottom: 1px solid {a(c['dim'], .35)}; }}
.wsection {{ color: {c['primary']}; letter-spacing: 0.18em; font-weight: 700; margin-top: 14px; }}
.wtool button, .wcard button, .sheet button {{ background-image: none; background-color: {a(c['selection'], .6)};
  border: 1px solid {a(c['dim'], .9)}; border-radius: 0; color: {c['soft']}; box-shadow: none;
  padding: 2px 10px; min-height: 24px; }}
.wtool button:hover, .wcard button:hover, .sheet button:hover {{ background-color: {a(c['primary'], .18)}; }}
.wtool button.primary, .wcard button.primary, .sheet button.suggested-action {{ border-color: {c['primary']};
  color: {c['primary']}; }}
.wtool button:checked {{ background-color: {c['primary']}; color: {c['void']}; }}
.head button.tab {{ background-image: none; background-color: transparent; border: 1px solid {a(c['dim'], .6)};
  border-radius: 0; color: {c['soft']}; letter-spacing: 0.14em; font-weight: 700; padding: 4px 14px; box-shadow: none; }}
.head button.tab:hover {{ border-color: {c['primary']}; }}
.head button.tab:checked {{ background-color: {c['primary']}; color: {c['void']}; border-color: {c['primary']}; }}
.sheet {{ background-color: {a(c['panel'], .99)}; border: 1px solid {c['dim']};
  box-shadow: 0 0 0 1px {a(c['primary'], .25)}, 0 16px 64px {a(c['void'], .85)}; }}
.lcard {{ border: 1px solid {a(c['dim'], .35)}; background-color: {a(c['void'], .55)}; padding: 0 0 8px 0; }}
.lcard:hover {{ border-color: {a(c['primary'], .55)}; }}
.lcard.made {{ border-color: {a(c['primary'], .7)}; }}
.lcard .wname, .lcard .wdesc, .lcard .wmeta {{ margin: 0 10px; }}
.lcard .lfor {{ color: {c['void']}; background-color: {c['primary']}; font-size: {font - 3}px; font-weight: 700;
  letter-spacing: 0.1em; padding: 0 6px; margin: 6px 10px 0 10px; }}
.lcard .lnote {{ color: {c['warn']}; font-size: {font - 2}px; margin: 0 10px; }}
.lhead .wmeta {{ margin-top: 14px; }}
.sheet .sheettitle {{ color: {c['primary']}; letter-spacing: 0.18em; font-weight: 700; }}
"""


class Ctx:
    """What a Settings form needs of its window (bromigos_settings.context.Context), for
    the Customize window: commands run without blocking, buttons and hints in the house
    style, a short message in the window's foot."""

    def __init__(self, Gtk, Gio, GLib, window, say):
        self.Gtk, self.Gio, self.GLib, self.window, self.say = Gtk, Gio, GLib, window, say
        self.pending = 0

    @staticmethod
    def hint(widget, text):
        if text:
            widget.set_tooltip_text(text)
        return widget

    def button(self, label, on_click, hint, primary=False, destructive=False, icon=None):
        b = self.Gtk.Button(label=label)
        b.set_valign(self.Gtk.Align.CENTER)
        if primary:
            b.add_css_class("suggested-action")
            b.add_css_class("primary")
        if destructive:
            b.add_css_class("destructive-action")
        b.connect("clicked", lambda *_: on_click())
        return self.hint(b, hint)

    def run(self, argv, done=None, stdin=None):
        Gio, GLib = self.Gio, self.GLib
        try:
            p = Gio.Subprocess.new(argv, Gio.SubprocessFlags.STDOUT_PIPE | Gio.SubprocessFlags.STDERR_PIPE)
        except GLib.Error as e:
            if done:
                GLib.idle_add(lambda: (done(False, "", e.message), False)[1])
            return
        self.pending += 1

        def fin(proc, res):
            self.pending -= 1
            try:
                _ok, out, err = proc.communicate_utf8_finish(res)
                ok = proc.get_successful()
            except GLib.Error as e:
                ok, out, err = False, "", e.message
            if done:
                done(ok, out or "", err or "")
        p.communicate_utf8_async(None, None, fin)

    def json(self, argv, done, stdin=None):
        def fin(ok, out, err):
            try:
                doc = json.loads(out) if out.strip() else None
            except ValueError:
                doc = None
            done(doc, err.strip() or ("" if ok else "failed"))
        self.run(argv, fin)

    def change(self, argv, said, undo=None, done=None, failed=None):
        def fin(doc, err):
            if not doc or doc.get("ok") is False:
                why = (doc or {}).get("error") or err or "failed"
                self.toast(f"Not changed: {why}"[:200])
                if failed:
                    failed(doc, why)
                return
            self.toast(said(doc) if callable(said) else said)
            if done:
                done(doc)
        self.json(list(argv), fin)

    def toast(self, text, undo=None, timeout=5):
        self.say(text)

    def copy(self, text):
        disp = self.window.get_display()
        disp.get_clipboard().set(text)
        self.toast("Copied")

    def open_url(self, url):
        try:
            import bromigos_hypr as H
            H.spawn(["xdg-open", url])
        except Exception:
            subprocess.Popen(["xdg-open", url], start_new_session=True, stdout=subprocess.DEVNULL,
                             stderr=subprocess.DEVNULL)


def _rgb(h):
    h = (h or "#39ff14").lstrip("#")
    return tuple(int(h[i:i + 2], 16) / 255 for i in (0, 2, 4)) if len(h) >= 6 else (0.2, 1.0, 0.1)


def layout_save_action(item):
    """Theme defaults are copied; installed presets are overridden in the user's folder."""
    if item.get("id") == "theme" or item.get("id", "").startswith("theme-") or item.get("made_for"):
        return "Save as new…", False
    return ("Save changes…" if item.get("source") == "yours" else "Override…"), True


class LayoutSaveForm:
    """Save the current desktop, with an explicit confirmation when replacing a layout."""
    def __init__(self, row, item=None):
        self.row, self.host, self.ctx, self.Gtk = row, row.tab.host, row.ctx, row.Gtk
        self.item = item if item and layout_save_action(item)[1] else None
        self.pending = False
        self.on_close = None
        self.sheet_size = (640, 360)
        self.monitor = ((row.doc or {}).get("screen") or {}).get("monitor")
        Gtk = self.Gtk
        self.page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        for side in ("start", "end", "bottom"):
            getattr(self.page, "set_margin_" + side)(14)
        self.title = "New layout" if not self.item else layout_save_action(self.item)[0].rstrip("…")
        screen = self.monitor or "this screen"
        self.page.append(Gtk.Label(label=f"Save the widgets currently on {screen}, with their sizes and positions. "
                                   "Widget settings stay separate. Saving leaves the desktop as it is; use "
                                   "Use this layout when you want to apply a saved layout.", wrap=True, max_width_chars=64,
                                   xalign=0))
        self.name = self.description = None
        if self.item:
            message = f"Replace {self.item['title']!r} with the current arrangement. Its name and description stay the same."
            if self.item.get("source") != "yours":
                message += " This saves your own override; the packaged preset stays installed."
            self.page.append(Gtk.Label(label=message, wrap=True, max_width_chars=64, xalign=0))
        else:
            self.name = Gtk.Entry(placeholder_text="My layout", max_length=60)
            self.description = Gtk.Entry(placeholder_text="What this layout is for")
            for label, entry, hint in (("Name", self.name, "A name for a new layout; existing names are kept"),
                                       ("Description (optional)", self.description, "A short description for its card")):
                lb = Gtk.Label(label=label, xalign=0)
                self.page.append(lb)
                entry.set_tooltip_text(hint)
                self.page.append(entry)
                entry.connect("activate", lambda *_: self.submit())
        self.error = Gtk.Label(wrap=True, max_width_chars=64, xalign=0, selectable=True)
        self.error.add_css_class("status")
        self.error.set_visible(False)
        self.page.append(self.error)
        actions = Gtk.Box(spacing=8, halign=Gtk.Align.END)
        self.cancel = self.ctx.button("Cancel", self.host.close_sheet, "Leave saved layouts as they are (Esc)")
        self.save = self.ctx.button("Save layout" if not self.item else self.title,
                                    self.submit, "Save the current arrangement", primary=True)
        actions.append(self.cancel)
        actions.append(self.save)
        self.page.append(actions)
        self.initial_focus = self.name or self.cancel

    def _busy(self, busy):
        self.pending = busy
        for widget in (self.name, self.description, self.cancel, self.save, getattr(self, "close_button", None)):
            if widget is not None:
                widget.set_sensitive(not busy)
        self.save.set_label("Saving…" if busy else "Save layout" if not self.item else self.title)

    def submit(self):
        if self.pending:
            return
        argv = ["bromigos", "panels", "layout", "save"]
        if self.item:
            argv += ["--replace", self.item["id"]]
        else:
            name = self.name.get_text().strip()
            if not name:
                self.error.set_label("Give the layout a name.")
                self.error.set_visible(True)
                self.name.grab_focus()
                return
            argv += [name, "--description", self.description.get_text().strip()]
        if self.monitor:
            argv += ["--monitor", self.monitor]
        argv += ["--json"]
        self.error.set_visible(False)
        self._busy(True)

        def saved(doc, err):
            self._busy(False)
            if not isinstance(doc, dict) or doc.get("ok") is False or err:
                self.error.set_label((doc or {}).get("error") if isinstance(doc, dict) and doc.get("error")
                                     else err or "The layout could not be saved. Try again.")
                self.error.set_visible(True)
                self.initial_focus.grab_focus()
                return
            self.host.close_sheet()
            self.ctx.toast(doc.get("said") or "Layout saved")
            self.row.refresh(focus_id=doc.get("id"))
        self.ctx.json(argv, saved)


class LayoutsRow:
    """The Layouts row at the top of the Widgets tab: a card per layout (`bromigos panels
    layouts`), the theme's own first ("Made for <theme>"), each a miniature of the screen
    with the scene behind and each widget where that layout puts it, fitted to this monitor.
    A click applies it; Undo puts the layout before it back; Tidy up packs the widgets on now."""
    MINI_W = 300

    def __init__(self, tab):
        Gtk = tab.Gtk
        self.tab, self.Gtk, self.ctx = tab, Gtk, tab.ctx
        self.doc, self.bg, self.bg_for = None, None, None
        self.focus_id, self.card_buttons = None, {}
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        head = Gtk.Box(spacing=10)
        head.add_css_class("lhead")
        self.title = Gtk.Label(label="LAYOUTS", xalign=0)
        self.title.add_css_class("wsection")
        self.title.set_tooltip_text("Ready-made layouts: which widgets are on, their sizes and places, fitted to "
                                    "your screen and kept off the scene's focal points")
        head.append(self.title)
        self.new_b = self.ctx.button("New layout…", self.new_layout,
                                     "Save the widgets currently on this screen, with their sizes and positions", primary=True)
        self.new_b.set_valign(Gtk.Align.END)
        self.new_b.set_sensitive(False)
        head.append(self.new_b)
        self.sub = Gtk.Label(xalign=0, hexpand=True, wrap=True)
        self.sub.add_css_class("wmeta")
        self.sub.set_tooltip_text("The theme in force and the screen the layouts are fitted to")
        head.append(self.sub)
        self.tidy_b = self.ctx.button("Tidy up", self.tidy, "Packs the widgets on now so none overlaps, in the "
                                      "same order, off the scene's focal points (bromigos panels tidy; Undo undoes it)")
        self.tidy_b.set_valign(Gtk.Align.END)
        head.append(self.tidy_b)
        self.undo_b = self.ctx.button("Undo", self.undo, "Puts back the layout from before the last one applied "
                                      "or tidied (bromigos panels layout undo)")
        self.undo_b.set_valign(Gtk.Align.END)
        head.append(self.undo_b)
        box.append(head)
        self.strip = Gtk.Box(spacing=12)
        sc = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.AUTOMATIC, vscrollbar_policy=Gtk.PolicyType.NEVER,
                                propagate_natural_height=True)
        sc.set_child(self.strip)
        sc.set_tooltip_text("Each layout, small: click one to put it on your desktop")
        self.scroller = sc
        box.append(sc)
        self.widget = box
        self.loading = Gtk.Label(label="FITTING THE LAYOUTS TO YOUR SCREEN…", xalign=0)
        self.loading.add_css_class("empty")
        self.strip.append(self.loading)
        self.refresh()

    def refresh(self, focus_id=None):
        self.focus_id = focus_id
        self.ctx.json(["bromigos", "panels", "layouts", "--json"], self.got)

    def got(self, doc, err):
        Gtk = self.Gtk
        c = self.strip.get_first_child()
        while c is not None:
            n = c.get_next_sibling()
            self.strip.remove(c)
            c = n
        if not doc or doc.get("ok") is False:
            lb = Gtk.Label(label=f"bromigos panels layouts didn't answer: {(doc or {}).get('error') or err}"[:200])
            lb.add_css_class("empty")
            self.strip.append(lb)
            self.doc = {"_error": (doc or {}).get("error") or err or "Layouts could not be read"}
            self.new_b.set_sensitive(False)
            self.tab.host.maybe_save_layout()
            return
        self.doc = doc
        self.card_buttons = {}
        self.new_b.set_sensitive(True)
        scr = doc.get("screen") or {}
        self.title.set_label("PICK A LAYOUT TO START" if doc.get("first_run") else "LAYOUTS")
        self.sub.set_label(f"for {doc.get('scene_title') or doc.get('theme')} on "
                           f"{scr.get('monitor') or 'this screen'}, {scr.get('full_width', scr.get('width'))}×"
                           f"{scr.get('full_height', scr.get('height'))}"
                           + (" · applied to every theme: " + doc["everywhere"] if doc.get("everywhere") else ""))
        self.undo_b.set_visible(bool(doc.get("undo")))
        if doc.get("undo"):
            self.undo_b.set_tooltip_text(f"Puts back the layout from before {doc['undo']['what']} "
                                         "(bromigos panels layout undo; again: redo)")
        fw = scr.get("full_width") or scr.get("width") or 1920
        fh = scr.get("full_height") or scr.get("height") or 1080
        # the miniature, its words, a note and the button, with room for the scrollbar
        self.strip.set_size_request(-1, int(self.MINI_W * fh / fw) + 226)
        for item in doc.get("layouts") or []:
            self.strip.append(self.card(item))
        if self.focus_id in self.card_buttons:
            button = self.card_buttons[self.focus_id]
            self.reveal_saved(button)
        self.focus_id = None
        self.tab.host.maybe_save_layout()

    def reveal_saved(self, button):
        """GTK focuses a child of this plain Box without scrolling its surrounding viewport."""
        attempts = 0

        def reveal():
            nonlocal attempts
            attempts += 1
            if button.get_root() is None:
                return False
            card = button.get_parent()
            ok, bounds = card.compute_bounds(self.strip)
            adjustment = self.scroller.get_hadjustment()
            if not ok or not card.get_width() or not adjustment.get_page_size():
                return attempts < 20
            button.grab_focus()
            x, right = bounds.get_x(), bounds.get_x() + bounds.get_width()
            current, width = adjustment.get_value(), adjustment.get_page_size()
            if x < current or right > current + width:
                adjustment.set_value(max(0, min(x, adjustment.get_upper() - width)))
            return False
        self.ctx.GLib.timeout_add(25, reveal)

    def card(self, item):
        Gtk = self.Gtk
        card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=3, valign=Gtk.Align.START)
        card.set_size_request(self.MINI_W, -1)
        card.add_css_class("lcard")
        if item.get("made_for"):
            card.add_css_class("made")
        scr = (self.doc or {}).get("screen") or {}
        fw, fh = scr.get("full_width") or scr.get("width") or 1920, scr.get("full_height") or scr.get("height") or 1080
        da = Gtk.DrawingArea()
        da.set_content_width(self.MINI_W)
        da.set_content_height(int(self.MINI_W * fh / fw))
        da.set_draw_func(self.draw, item)
        da.set_tooltip_text(f"{item['title']}, small: where each widget goes on your screen; the dashed boxes are "
                            "the scene's focal points, kept clear")
        card.append(da)
        if item.get("made_for"):
            lf = Gtk.Label(label=f"MADE FOR {item['made_for'].upper()}", xalign=0, halign=Gtk.Align.START)
            lf.add_css_class("lfor")
            lf.set_tooltip_text(f"{item['made_for']}'s own layout, chosen to suit its scene")
            card.append(lf)
        if not item["title"].lower().startswith("made for"):     # the theme's own: its tag says it
            card.append(self.tab.label(item["title"].upper(), "wname", 1))
        card.append(self.tab.label(item["description"], "wdesc"))
        n = len(item.get("placed") or {})
        meta = f"{n} widget{'s' if n != 1 else ''} · {round(item.get('coverage', 0) * 100)}% of the screen"
        if item.get("source") == "yours":
            meta += " · yours"
        card.append(self.tab.label(meta, "wmeta", 1))
        notes = item.get("notes") or []
        if notes:
            ln = self.tab.label(f"{len(notes)} note{'s' if len(notes) != 1 else ''}: " + notes[0], "lnote")
            ln.set_tooltip_text("\n".join(notes))
            card.append(ln)
        b = self.ctx.button("Use this layout", lambda: self.apply(item),
                            f"Puts {item['title']} on your desktop: these widgets on, at these sizes and places. "
                            "Each widget keeps its own settings; Undo puts yours back", primary=True)
        b.set_margin_start(10)
        b.set_halign(Gtk.Align.START)
        card.append(b)
        label, replace = layout_save_action(item)
        save = self.ctx.button(label, lambda: self.new_layout(item if replace else None),
                               "Save the CURRENT desktop arrangement " + (f"over {item['title']}" if replace
                                                                          else "as a new layout"))
        save.set_margin_start(10)
        save.set_halign(Gtk.Align.START)
        card.append(save)
        self.card_buttons[item["id"]] = save
        card.set_tooltip_text(f"{item['title']}: {item['description']}" + ("\n" + "\n".join(notes) if notes else ""))
        click = Gtk.GestureClick()
        click.connect("released", lambda *_: self.apply(item))
        da.add_controller(click)
        return card

    def new_layout(self, item=None):
        if not self.doc or self.doc.get("_error"):
            return
        form = LayoutSaveForm(self, item)
        self.tab.host.sheet(form, form.title)

    def background(self, w, h):
        path = (self.doc or {}).get("background")
        if not path:
            return None
        if self.bg_for != (path, w, h):
            self.bg_for, self.bg = (path, w, h), None
            try:
                import gi
                gi.require_version("GdkPixbuf", "2.0")
                from gi.repository import GdkPixbuf
                pb = GdkPixbuf.Pixbuf.new_from_file(path)
                s = max(w / pb.get_width(), h / pb.get_height())          # cover, as the live layer does
                sw, sh = max(w, round(pb.get_width() * s)), max(h, round(pb.get_height() * s))
                pb = pb.scale_simple(sw, sh, GdkPixbuf.InterpType.BILINEAR)
                self.bg = pb.new_subpixbuf((sw - w) // 2, (sh - h) // 2, w, h)
            except Exception:                                             # noqa: BLE001  no picture: a plain screen
                self.bg = None
        return self.bg

    def draw(self, _area, cr, w, h, item):
        colors = getattr(self.tab.host, "colors", {}) or {}
        prim, void, soft = _rgb(colors.get("primary")), _rgb(colors.get("void", "#000500")), _rgb(colors.get("soft"))
        warn = _rgb(colors.get("warn", "#d4af37"))
        scr = (self.doc or {}).get("screen") or {}
        fw = scr.get("full_width") or scr.get("width") or 1920
        k = w / fw
        ox, oy = (scr.get("x") or 0) * k, (scr.get("y") or 0) * k
        bg = self.background(w, h)
        if bg is not None:
            from gi.repository import Gdk
            Gdk.cairo_set_source_pixbuf(cr, bg, 0, 0)
            cr.paint()
        else:
            cr.set_source_rgb(*void)
            cr.paint()
        cr.set_source_rgba(*void, 0.25)
        cr.paint()
        if oy:                                     # the bar
            cr.set_source_rgba(*void, 0.85)
            cr.rectangle(0, 0, w, oy)
            cr.fill()
        cr.set_line_width(1)
        cr.set_dash([3, 3])
        for c in (self.doc or {}).get("clear") or []:
            cr.set_source_rgba(*warn, 0.35 if c.get("soft") else 0.7)
            cr.rectangle(ox + c["x"] * k + 0.5, oy + c["y"] * k + 0.5, c["width"] * k - 1, c["height"] * k - 1)
            cr.stroke()
        cr.set_dash([])
        for name, p in (item.get("placed") or {}).items():
            x, y, pw, ph = ox + p["x"] * k, oy + p["y"] * k, p["width"] * k, p["height"] * k
            cr.set_source_rgba(*void, 0.82)
            cr.rectangle(x, y, pw, ph)
            cr.fill()
            cr.set_source_rgba(*prim, 0.9)
            cr.rectangle(x + 0.5, y + 0.5, pw - 1, ph - 1)
            cr.stroke()
            cr.set_source_rgba(*prim, 0.9)
            cr.rectangle(x + 1, y + 1, pw - 2, min(4, ph / 6))
            cr.fill()
            if pw > 26 and ph > 12:
                cr.set_source_rgb(*soft)
                cr.select_font_face("Geist Mono")
                cr.set_font_size(max(6, min(9, ph / 3)))
                label = name.upper()[: max(2, int(pw / 6))]
                cr.move_to(x + 3, y + min(ph - 2, 14))
                cr.show_text(label)

    def apply(self, item):
        notes = item.get("notes") or []
        self.ctx.change(["bromigos", "panels", "layout", "apply", item["id"], "--json"],
                        lambda d: (d.get("said") or item["title"]) + (f" ({'; '.join(notes)})" if notes else "")
                        + ". Undo puts yours back", done=lambda _d: self.after())

    def undo(self):
        self.ctx.change(["bromigos", "panels", "layout", "undo", "--json"], lambda d: d.get("said") or "Undone",
                        done=lambda _d: self.after())

    def tidy(self):
        self.ctx.change(["bromigos", "panels", "tidy", "--json"], lambda d: (d.get("said") or "Tidied")
                        + ". Undo puts it back", done=lambda _d: self.after())

    def after(self):
        self.refresh()
        self.ctx.json(["bromigos", "panels", "gallery", "--json"], self.tab.got_gallery)


class WidgetsTab:
    def __init__(self, Gtk, Pango, host):
        self.Gtk, self.Pango, self.host = Gtk, Pango, host
        self.ctx = host.ctx
        self.gallery, self.catalog = None, None
        self.previews = {}
        self.category = "all"
        self.boxes = {}
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        tool = Gtk.Box(spacing=6)
        tool.add_css_class("wtool")
        tool.set_tooltip_text("The categories, arranging the panels on the desktop, and adding a widget from a link")
        self.chipbox = Gtk.Box(spacing=6)              # filled from the categories the widgets declare
        self.chipbox.set_tooltip_text("Only one category of widget, by each widget's own category")
        self.chips = {}
        tool.append(self.chipbox)
        self.build_chips([])                           # All, until the gallery says which there are
        tool.append(Gtk.Box(hexpand=True))
        tool.append(self.ctx.button("Arrange on the desktop", self.arrange,
                                    "Closes this and starts edit mode: drag the panels, resize them by a corner "
                                    "(Super+Alt+W)", primary=True))
        tool.append(self.ctx.button("Install from URL…", lambda: self.install(None),
                                    "A widget from any git repository or folder: you see what it can do before "
                                    "it's installed"))
        box.append(tool)
        self.list = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        self.scroll = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER, vexpand=True)
        self.scroll.set_child(self.list)
        self.scroll.set_tooltip_text("Every widget there is, on or off, then more from the catalog")
        box.append(self.scroll)
        self.widget = box
        self.loading = Gtk.Label(label="READING THE WIDGETS…")
        self.loading.add_css_class("empty")
        self.loading.set_tooltip_text("bromigos panels gallery: every widget, drawn once for its picture")
        self.list.append(self.loading)
        self.layouts = LayoutsRow(self)            # the Layouts row, first in the list
        self.refresh()

    def build_chips(self, cats):
        Gtk = self.Gtk
        c = self.chipbox.get_first_child()
        while c is not None:
            n = c.get_next_sibling()
            self.chipbox.remove(c)
            c = n
        self.chips = {}
        group = None
        from bromigos_settings.widgetform import category_buttons
        for cid, label, hint in category_buttons(cats):
            t = Gtk.ToggleButton(label=label)
            if group is None:
                group = t
            else:
                t.set_group(group)
            t.set_active(cid == self.category)
            t.set_tooltip_text(hint if cid == "all" else f"Only these: {hint[0].lower()}{hint[1:]}")
            t.connect("toggled", lambda b, c=cid: b.get_active() and self.set_category(c))
            self.chips[cid] = t
            self.chipbox.append(t)
        if self.category not in self.chips:
            self.category = "all"
            self.chips["all"].set_active(True)

    # ------------------------------------------------------------------ data
    def refresh(self):
        self.ctx.json(["bromigos", "panels", "gallery", "--previews", cache_dir(), "--json"], self.got_gallery)
        self.ctx.json(["bromigos", "ext", "search", "--kind", "widget", "--json"], self.got_catalog)

    def got_gallery(self, doc, err):
        if doc and doc.get("ok", True) is not False:
            self.gallery = doc
            for w in doc.get("widgets") or []:
                if w.get("preview"):
                    self.previews[w["name"]] = w["preview"]
            if doc.get("categories"):
                self.build_chips(doc["categories"])
        else:
            self.gallery = {"_error": (doc or {}).get("error") or err}
        self.fill()
        self.host.maybe_save_layout()

    def got_catalog(self, doc, err):
        self.catalog = doc if doc and doc.get("ok", True) is not False else {"_error": err}
        self.fill()

    def count(self):
        ws = (self.gallery or {}).get("widgets") or []
        on = sum(1 for w in ws if w["visible"])
        more = sum(1 for e in (self.catalog or {}).get("results") or [] if not e.get("installed"))
        return f"{len(ws)} widgets · {on} on the desktop" + (f" · {more} in the catalog" if more else "")

    # ------------------------------------------------------------------ the cards
    def set_category(self, c):
        self.category = c
        self.fill()

    def matches(self, cat, *words):
        if self.category != "all" and cat != self.category:
            return False
        q = self.host.query()
        hay = " ".join(str(w or "") for w in words).lower()
        return all(x in hay for x in q.split())

    def fill(self):
        Gtk = self.Gtk
        c = self.list.get_first_child()
        while c is not None:
            n = c.get_next_sibling()
            self.list.remove(c)
            c = n
        if not self.host.query().strip():          # the Layouts row first, while nothing is searched for
            self.list.append(self.layouts.widget)
        if self.gallery is None:
            self.list.append(self.loading)
            return
        if self.gallery.get("_error"):
            lb = Gtk.Label(label=f"bromigos panels gallery didn't answer: {self.gallery['_error']}"[:300], wrap=True)
            lb.add_css_class("empty")
            lb.set_tooltip_text("Run bromigos panels gallery in a terminal to see more")
            self.list.append(lb)
            return
        groups = {k: [] for k, _t, _h in SECTIONS}
        for w in self.gallery.get("widgets") or []:
            if not (w.get("available", True) or w["visible"]):
                continue
            if not self.matches(w["category"], w["name"], w["title"], w["description"], w["reads"], w["author"]):
                continue
            sec = "desktop" if w["visible"] else {"bromigos": "builtin", "homelab": "builtin",
                                                  "extension": "extensions"}.get(w["source"], "yours")
            groups[sec].append(("w", w))
        for e in (self.catalog or {}).get("results") or []:
            if e.get("installed") or e.get("bundled"):
                continue
            cat = next((t for t in e.get("tags") or [] if t in self.chips and t != "all"), "fun")
            if self.matches(cat, e["name"], e.get("display_name"), e.get("description"), " ".join(e.get("tags") or [])):
                groups["more"].append(("c", e))
        shown = 0
        for key, title, hint in SECTIONS:
            items = groups[key]
            if not items:
                continue
            lb = Gtk.Label(label=title, xalign=0)
            lb.add_css_class("wsection")
            lb.set_tooltip_text(hint)
            self.list.append(lb)
            # not homogeneous, so each row is as tall as its own cards (a short last row stays
            # short); every card is one column wide (card()), so the grid keeps its 4 or 5 a row
            flow = Gtk.FlowBox(homogeneous=False, column_spacing=12, row_spacing=12,
                               selection_mode=Gtk.SelectionMode.NONE, halign=Gtk.Align.START,
                               valign=Gtk.Align.START)
            cols = max(1, self.host.widget_cols())
            flow.set_min_children_per_line(cols)
            flow.set_max_children_per_line(cols)
            for kind, x in items:
                flow.append(self.card(x) if kind == "w" else self.catalog_card(x))
                shown += 1
            self.list.append(flow)
        if not shown:
            lb = Gtk.Label(label="NO WIDGET MATCHES")
            lb.add_css_class("empty")
            lb.set_tooltip_text("Nothing has those words in this category: Backspace to widen it, or pick All")
            self.list.append(lb)
        self.host.counted()

    def picture(self, path, w, h, hint):
        Gtk = self.Gtk
        if path and os.path.isfile(path):
            pic = Gtk.Picture.new_for_filename(path)
            pic.set_content_fit(Gtk.ContentFit.CONTAIN)
            pic.set_can_shrink(True)
        else:
            pic = Gtk.Label(label="NO PICTURE YET")
            pic.add_css_class("empty")
        pic.set_size_request(-1, h)            # the flow box sets the width: never wider than a column
        pic.add_css_class("wpic")
        pic.set_tooltip_text(hint)
        return pic

    def label(self, text, cls, lines=2):
        lb = self.Gtk.Label(label=text, xalign=0, wrap=True, lines=lines, max_width_chars=20, width_chars=10,
                            ellipsize=self.Pango.EllipsizeMode.END)
        lb.add_css_class(cls)
        return lb

    def card(self, w):
        Gtk, ctx = self.Gtk, self.ctx
        title = w["title"].title() if w["title"].isupper() else w["title"]
        child = Gtk.FlowBoxChild()
        child.add_css_class("wcard")
        if not w["visible"]:
            child.add_css_class("off")
        cw = self.host.widget_card_w()
        child.set_size_request(cw - 16, -1)       # a column wide (the flow box shares out the rest)
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        box.append(self.picture(self.previews.get(w["name"]), cw, int(cw * 0.62),
                                f"{title}, drawn with made-up readings"))
        body = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=3)
        body.add_css_class("wbody")
        body.append(self.label(title.upper(), "wname", 1))
        body.append(self.label(w["description"] or "A widget", "wdesc"))
        meta = f"by {w['author']}" + (f" · reads {w['reads']}" if w.get("reads") else "")
        if not w.get("available", True):
            meta += f" · can't show anything here: {w.get('unavailable') or 'not available'}"
        m = self.label(meta, "wmeta")
        m.set_tooltip_text(f"Who made it ({w['source']}) and what it reads")
        body.append(m)
        row = Gtk.Box(spacing=6)
        row.set_tooltip_text(f"{title}: on or off, its size, and what else you can do with it")
        sw = Gtk.Switch(active=bool(w["visible"]), valign=Gtk.Align.CENTER)
        sw.set_tooltip_text(f"{title} on or off" + (f"; {w['key']} shows or hides it any time" if w.get("key") else ""))
        sw.connect("notify::active", lambda s, _p: self.panels(["show" if s.get_active() else "hide", w["name"]],
                                                              f"{title}: {'on' if s.get_active() else 'off'}"))
        row.append(sw)
        if len(w.get("sizes") or []) > 1:
            names = [c["name"] for c in w["sizes"]]
            dd = Gtk.DropDown.new_from_strings([n.title() for n in names])
            cur = w.get("size_class") or w.get("default_size")
            if cur in names:
                dd.set_selected(names.index(cur))
            dd.set_tooltip_text(f"{title}'s size: each lays it out its own way, with more to see as it grows")
            dd.connect("notify::selected", lambda d, _p: self.panels(["size", w["name"], names[d.get_selected()]],
                                                                    f"{title}: {names[d.get_selected()]}"))
            row.append(dd)
        body.append(row)
        row = Gtk.Box(spacing=6)                     # the actions, on a line of their own
        row.set_tooltip_text(f"What you can do with {title}")
        if not w["visible"]:
            row.append(ctx.button("Add to desktop", lambda: self.panels(["add", w["name"]], f"{title}: on, in a free "
                                                                                              "spot"),
                                  f"Puts {title} on the desktop, in a free spot, at its default size", primary=True))
        if w.get("form"):
            row.append(ctx.button("Settings…", lambda: self.form(w), f"{title}'s own settings: "
                                  + ", ".join(f["label"] for f in w["form"])))
        elif w.get("settings"):
            s = w["settings"]
            row.append(ctx.button("Settings…", lambda: self.host.open_settings(
                s["page"] + (f"#{s['key']}" if s.get("key") else "")), f"{title}'s settings ({s['what']}): opens "
                                                                       f"Settings › {s['page'].title()}"))
        if w["source"] in ("extension", "yours"):
            row.append(ctx.button("Remove", lambda: self.remove(w), "Removes it: the extension that brought it, or "
                                                                    "the file in your plugin folder (to the trash)",
                                  destructive=True))
        body.append(row)
        box.append(body)
        child.set_child(box)
        child.set_tooltip_text(f"{title}: {w['description'] or 'a widget'} ({w['category']})")
        return child

    def catalog_card(self, e):
        Gtk, ctx = self.Gtk, self.ctx
        title = e.get("display_name") or e["name"]
        child = Gtk.FlowBoxChild()
        child.add_css_class("wcard")
        cw = self.host.widget_card_w()
        child.set_size_request(cw - 16, -1)       # a column wide (the flow box shares out the rest)
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        box.append(self.picture(e.get("preview"), cw, int(cw * 0.62), f"{title}: the catalog's picture of it"))
        body = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=3)
        body.add_css_class("wbody")
        body.append(self.label(title.upper(), "wname", 1))
        body.append(self.label(e.get("description") or "", "wdesc"))
        authors = ", ".join(a.split(" <")[0] for a in e.get("authors") or []) or "an unnamed author"
        code = bool(CODE & set(e.get("kinds") or []))
        body.append(self.label(f"by {authors} · {e.get('licence') or 'no licence given'} · "
                               f"{'runs code' if code else 'data only'}", "wmeta"))
        row = Gtk.Box(spacing=6)
        row.set_tooltip_text(f"Install {title}, or read its source first")
        row.append(ctx.button("Install…", lambda: self.install(e["name"]), f"Shows what {title} would add and what "
                              "it can do, then installs it when you say so", primary=True))
        url = (e.get("url") or "").removesuffix(".git").rstrip("/")
        link = f"{url}/tree/HEAD/{e['path']}" if url.startswith("https://github.com/") and e.get("path") else url
        if link:
            row.append(ctx.button("Repository", lambda: ctx.open_url(link), f"Opens its source: {link}"))
        body.append(row)
        box.append(body)
        child.set_child(box)
        child.set_tooltip_text(f"{title}, from the catalog")
        return child

    # ------------------------------------------------------------------ actions
    def panels(self, args, said):
        self.ctx.change(["bromigos", "panels"] + args + ["--json"], lambda d: d.get("said") or said,
                        done=lambda _d: self.ctx.json(["bromigos", "panels", "gallery", "--json"], self.got_gallery),
                        failed=lambda *_: self.refresh())

    def arrange(self):
        self.ctx.run(["bromigos", "panels", "edit", "--json"])
        self.host.close()

    def install(self, source):
        from bromigos_settings.widgetform import InstallFromURL
        f = InstallFromURL(self.ctx, done=self.refresh, source=source)
        self.host.sheet(f, "ADD FROM A URL" if not source else f"INSTALL {source.upper()}")

    def form(self, w):
        from bromigos_settings.widgetform import WidgetForm
        f = WidgetForm(self.ctx, w, done=lambda: self.ctx.json(["bromigos", "panels", "gallery", "--json"],
                                                                self.got_gallery))
        self.host.sheet(f, f"{w['title']} SETTINGS")

    def remove(self, w):
        title = w["title"].title() if w["title"].isupper() else w["title"]
        if w["source"] == "extension":
            ext = (w.get("extension") or {}).get("name") or w["name"]
            body = f"The {ext} extension goes: its links and its checkout (the ledger keeps a line)."

            def go():
                self.ctx.change(["bromigos", "ext", "remove", ext, "--json"], f"Removed {ext}",
                                done=lambda _d: self.refresh())
        else:
            path = os.path.join(os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config"),
                                "bromigos", "plugins", "widgets", f"{w['name']}.py")
            body = f"Its file, {path}, goes to the trash: you can get it back from there."

            def go():
                self.ctx.run(["gio", "trash", path], lambda ok, _o, err: (
                    self.ctx.toast(f"{title}: in the trash" if ok else f"Not removed: {err.strip()}"),
                    self.refresh()))
        self.host.confirm(f"Remove {title}?", body, "Remove", go)
