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

CATEGORIES = [("all", "All"), ("system", "System"), ("network", "Network"), ("homelab", "Homelab"),
              ("media", "Media"), ("notes", "Notes"), ("fun", "Fun")]
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
        self.build_chips([{"id": c, "title": t} for c, t in CATEGORIES[1:]])
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
        for cid, label in [("all", "All")] + [(x["id"], x["title"].split(" ")[0]) for x in cats]:
            t = Gtk.ToggleButton(label=label)
            if group is None:
                group = t
            else:
                t.set_group(group)
            t.set_active(cid == self.category)
            t.set_tooltip_text("Every widget" if cid == "all" else f"Only the {label.lower()} widgets, by each "
                                                                   "widget's own category")
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
            flow = Gtk.FlowBox(homogeneous=True, column_spacing=12, row_spacing=12,
                               selection_mode=Gtk.SelectionMode.NONE)
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
