"""Widgets: the desktop panels (bromigos-widgets): the widget gallery (every panel there
is, on or off, with what it shows, who made it and what it reads), the community catalog
for more, where they sit (drawn small, and edit mode on the desktop), the monitor they go
on, and the weather panel's place (docs/settings.md, "Widgets"; docs/widgets.md).

Everything goes through `bromigos panels … --json` and `bromigos ext … --json`: a change
writes your layout.json (bromigOS's copied the first time, every key kept) or
weather.toml and tells running panels to read it again; it toasts Undo. Installing a
widget runs code, so it happens in a terminal, where `bromigos ext install` shows what it
can do and asks first."""
import os

from gi.repository import GLib, Gtk

from bromigos_settings import Entry, Page

CMD = ["bromigos", "panels"]
EXT = ["bromigos", "ext"]
CATEGORIES = [("all", "All", "Every widget"), ("system", "System", "This machine: CPU, memory, disks, keys"),
              ("network", "Network", "Traffic, Wi-Fi, connections"), ("homelab", "Homelab", "Your servers"),
              ("media", "Media", "Music and video"), ("notes", "Notes", "Notes and your work"),
              ("fun", "Fun", "Weather and other extras")]
CODE_KINDS = {"live-deck", "widget", "vector-tool", "vector-memory", "homelab-adapter", "command", "hook"}
GALLERY_SECTIONS = [("desktop", "On your desktop", "The widgets on your desktop now. Switch one off, or arrange them on the "
                                            "desktop with Edit on the desktop."),
            ("builtin", "Built in", "bromigOS's widgets that are off. Switch one on, or add it to a free spot."),
            ("extensions", "Installed extensions", "Widgets from extensions you installed that are off."),
            ("yours", "Your own", "Widgets from your own plugin folder (~/.config/bromigos/plugins/widgets).")]


def _rgb(hexv, fallback=(0.2, 1.0, 0.1)):
    try:
        h = hexv.lstrip("#")
        return tuple(int(h[i:i + 2], 16) / 255 for i in (0, 2, 4))
    except (AttributeError, ValueError):
        return fallback


def _cache():
    return os.path.join(os.environ.get("XDG_CACHE_HOME") or os.path.expanduser("~/.cache"),
                        "bromigos", "widgets", "gallery")


def repo_link(e):
    """The catalog entry's repository page: its folder on GitHub when it's one."""
    url = (e.get("url") or "").removesuffix(".git").rstrip("/")
    if url.startswith("https://github.com/") and e.get("path"):
        return f"{url}/tree/HEAD/{e['path']}"
    return url or None


def category_of(tags):
    return next((t for t in tags or [] if t in dict((c[0], 1) for c in CATEGORIES[1:])), "fun")


class WidgetsPage:
    def __init__(self, ctx):
        self.ctx = ctx
        self.doc = self.gallery = self.catalog = None
        self.previews = {}
        self.query, self.category = "", "all"
        self.page = ctx.page()
        self.page.set_reset(self.reset, what="The panels go back to bromigOS's layout (your layout.json is removed, "
                                             "or rewritten when it's a link into your dotfiles: positions, sizes, "
                                             "which are on, the monitor) and the weather has no place (weather.toml "
                                             "removed).")
        ctx.on_restyle(lambda _c: getattr(self, "area", None) and self.area.queue_draw())
        # every group made once, in order; each read fills its own
        self.g_layout = ctx.group(self.page, "Layout", "Where each panel sits on its monitor. Arrange them on the "
                                                       "desktop itself: drag to move, a corner to resize.",
                                  key="layout")
        self.g_place = ctx.group(self.page, "Where they go", key="placement")
        self.g_gallery = ctx.group(self.page, "Widget gallery", "Every widget there is, on or off. Each says what "
                                                                "it shows, who made it and what it reads.",
                                   key="panels")
        self.sections = {k: ctx.group(self.page, t, d, key=f"section-{k}") for k, t, d in GALLERY_SECTIONS}
        self.g_more = ctx.group(self.page, "Get more widgets",
                                "From the community catalog (bromigos-org/extensions). A widget is Python that runs as "
                                "you: installing one shows what it can do, and asks you, in a terminal.", key="more")
        self.g_weather = ctx.group(self.page, "Weather", "The weather panel's place (Open-Meteo: free, no key). Nothing "
                                                         "is fetched until there is one.", key="weather")
        self.rows = {k: [] for k in ("layout", "place", "gallery", "more", "weather", *self.sections)}
        self.rows["layout"].append(ctx.loading(self.g_layout, "Reading the panels' layout…"))
        self.rows["gallery"].append(ctx.loading(self.g_gallery, "Drawing every widget…"))
        self.rows["more"].append(ctx.loading(self.g_more, "Reading the catalog (fetched every six hours)…"))
        self.g_gallery.set_header_suffix(ctx.button(
            "Open Customize", lambda: ctx.launch(["bromigos-customize", "--tab", "widgets"]),
            "Opens Customize over the whole screen on its Widgets tab: the same gallery as cards, beside the themes"))
        self.build_filters()
        self.refresh()

    def refresh(self):
        self.ctx.json(CMD + ["--json"], self._got_status)
        self.read_gallery(previews=True)
        self.ctx.json(EXT + ["search", "--kind", "widget", "--json"], self._got_catalog)

    def read_gallery(self, previews=False):
        argv = CMD + ["gallery"] + (["--previews", _cache()] if previews else []) + ["--json"]
        self.ctx.json(argv, self._got_gallery)

    # ------------------------------------------------------------------ reads
    def _got_status(self, doc, err):
        if not doc or doc.get("ok") is False:
            self.ctx.clear_group(self.g_layout, self.rows["layout"])
            self.rows["layout"].append(self.ctx.failed(self.g_layout, CMD + ["--json"], (doc or {}).get("error") or err))
            return
        self.sync(doc)

    def _got_gallery(self, doc, err):
        if not doc or doc.get("ok") is False:
            self.ctx.clear_group(self.g_gallery, self.rows["gallery"])
            self.rows["gallery"].append(self.ctx.failed(self.g_gallery, CMD + ["gallery", "--json"],
                                                        (doc or {}).get("error") or err))
            return
        for w in doc.get("widgets") or []:
            if w.get("preview"):
                self.previews[w["name"]] = w["preview"]
        self.gallery = doc
        self.ctx.clear_group(self.g_gallery, self.rows["gallery"])
        self.fill_gallery()

    def _got_catalog(self, doc, err):
        if not doc or doc.get("ok") is False:
            doc = {"_error": (doc or {}).get("error") or err or "no answer"}
        self.catalog = doc
        self.fill_catalog()

    # ------------------------------------------------------------------ the preview
    def _draw(self, _area, cr, w, h):
        c = self.ctx.colors
        panels = (self.doc or {}).get("panels") or []
        cr.set_source_rgb(*_rgb(c.get("void", "#000500"), (0, 0, 0)))
        cr.rectangle(0, 0, w, h)
        cr.fill()
        if not panels:
            return
        right = max((p["x"] or 0) + (p["width"] or 0) for p in panels) + 24
        bottom = max((p["y"] or 0) + (p["height"] or 0) for p in panels) + 24
        right, bottom = max(right, 1600), max(bottom, 900)
        s = min((w - 8) / right, (h - 8) / bottom)
        ox, oy = (w - right * s) / 2, (h - bottom * s) / 2
        dim, prim, faint, text = (_rgb(c.get(k)) for k in ("dim", "primary", "faint", "soft"))
        cr.set_line_width(1)
        cr.set_source_rgb(*dim)
        cr.rectangle(ox + .5, oy + .5, right * s - 1, bottom * s - 1)
        cr.stroke()
        for p in panels:
            x, y = ox + (p["x"] or 0) * s, oy + (p["y"] or 0) * s
            pw, ph = (p["width"] or 0) * s, (p["height"] or 0) * s
            if p["visible"]:
                cr.set_source_rgba(*prim, 0.14)
                cr.rectangle(x, y, pw, ph)
                cr.fill()
                cr.set_source_rgb(*prim)
                cr.set_dash([])
            else:
                cr.set_source_rgb(*faint)
                cr.set_dash([3, 3])
            cr.rectangle(x + .5, y + .5, pw - 1, ph - 1)
            cr.stroke()
            cr.set_dash([])
            cr.set_source_rgb(*(text if p["visible"] else faint))
            cr.select_font_face("Geist Mono")
            cr.set_font_size(max(8, min(12, ph / 4)))
            cr.move_to(x + 4, y + 13)
            cr.show_text(p["title"].upper())

    # ------------------------------------------------------------------ layout, placement, weather
    def sync(self, d):
        self.doc = d
        ctx = self.ctx
        g = self.g_layout
        ctx.clear_group(g, self.rows["layout"])
        self.area = Gtk.DrawingArea(content_height=230, hexpand=True)
        self.area.set_draw_func(self._draw)
        ctx.hint(self.area, "The panels' layout, small: lit ones are on, dashed ones off. Edit on the desktop "
                            "(Super+Alt+W) to move or resize them by dragging")
        g.add(self.area)
        self.rows["layout"].append(self.area)
        self.rows["layout"].append(ctx.row(
            g, "Edit on the desktop", "Drag the panels, resize them by a corner, switch them on and off. "
                                      "Esc or Done saves. Its key is Super+Alt+W; a right-click on a panel works too.",
            key="edit", hint="Starts edit mode on the desktop (bromigos panels edit)",
            buttons=[("Edit on the desktop", self.edit, "Starts edit mode: the panels come above your windows, "
                                                         "and the widget gallery opens beside them")],
            advanced={"runs": "bromigos panels edit", "file": d["user_file"]}))
        g = self.g_place
        ctx.clear_group(g, self.rows["place"])
        rows = self.rows["place"]
        where = "yours" if d["yours"] else "bromigOS's (copied to yours on the first change)"
        rows.append(ctx.row(g, "Layout file", f"{d['user_file'] if d['yours'] else d['default_file']}: {where}",
                            hint="Opens the layout file in your editor (bromigos-widgets reload after)",
                            buttons=[("Open", lambda: self._open(d), "Opens layout.json in your editor")],
                            advanced={"file": d["user_file"], "runs": "bromigos panels move|size NAME …"}))
        rows.append(ctx.entry_row(g, "Monitor (empty: the primary display)", d["monitor"], key="monitor",
                                  on_apply=lambda v: self._change(["monitor", v.strip()],
                                                                  f"Panels on {v.strip() or 'the primary'}",
                                                                  ["monitor", d["monitor"]]),
                                  hint="The output the panels go on, e.g. DP-1; empty: the primary display "
                                       "(Settings › Displays)",
                                  advanced={"file": d["user_file"], "key": "monitor",
                                            "runs": "bromigos panels monitor NAME"}))
        state = "running: a change shows at once" if d["running"] else "not running: a change shows at their next start"
        rows.append(ctx.row(g, "The panels", state, key="running", hint="bromigos-widgets, started at login",
                            buttons=[("Reload", lambda: ctx.run(["bromigos-widgets", "reload"],
                                                                lambda ok, o, e: ctx.toast(
                                                                    "The panels read their layout again" if ok
                                                                    else "The panels aren't running")),
                                      "Makes the running panels read their layout again")] if d["running"] else []))
        self.fill_weather(d)
        GLib.idle_add(lambda: (self.area.queue_draw(), False)[1])

    def fill_weather(self, d):
        ctx = self.ctx
        g = self.g_weather
        ctx.clear_group(g, self.rows["weather"])
        rows = self.rows["weather"]
        w = d["weather"]
        here = w.get("place") or (f"{w['lat']}, {w['lon']}" if w.get("lat") is not None else "")
        rows.append(ctx.entry_row(g, "Place (a city or town)", w.get("place") or "", key="weather-place",
                                  on_apply=lambda v: v.strip() and self._change(["weather", "place", v.strip()],
                                                                                f"Weather for {v.strip()}", None),
                                  hint="Where the forecast is for: a city or town, found by Open-Meteo's geocoder",
                                  advanced={"file": w["file"], "key": "place",
                                            "runs": "bromigos panels weather place PLACE"}))
        rows.append(ctx.combo_row(g, "Units", "", options=[("metric", "°C and km/h"), ("imperial", "°F and mph")],
                                  current=w.get("units") or "metric", key="weather-units",
                                  on_select=lambda u: self._change(["weather", "units", u], "Units changed",
                                                                   ["weather", "units", w.get("units") or "metric"]),
                                  hint="Celsius and km/h, or Fahrenheit and mph",
                                  advanced={"file": w["file"], "key": "units",
                                            "runs": "bromigos panels weather units metric|imperial"}))
        rows.append(ctx.entry_row(g, "Label", w.get("name") or "", key="weather-name",
                                  on_apply=lambda v: self._change(["weather", "name", v.strip()], "Label changed", None),
                                  hint="The panel's header (empty: the place's name)",
                                  advanced={"file": w["file"], "key": "name", "runs": "bromigos panels weather name TEXT"}))
        if here:
            rows.append(ctx.row(g, "Now", here, hint="The place the forecast is for",
                                buttons=[("Clear", lambda: self._change(["weather", "clear"], "No weather place", None),
                                          "Removes the place: the panel fetches nothing")]))
        if not next((p for p in d["panels"] if p["name"] == "weather" and p["visible"]), None):
            rows.append(ctx.note(g, "The weather panel is off: switch it on in the widget gallery to see it.", "note"))

    # ------------------------------------------------------------------ the gallery
    def build_filters(self):
        ctx = self.ctx
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8, margin_bottom=6)
        self.search = Gtk.SearchEntry(placeholder_text="Search widgets", hexpand=True)
        ctx.hint(self.search, "Finds widgets, here and in the catalog, by name, what they show, what they read or "
                              "who made them")
        self.search.connect("search-changed", lambda e: self._filter(query=e.get_text()))
        box.append(self.search)
        self.chips = ctx.toggle_group(CATEGORIES, current="all", on_select=lambda c: self._filter(category=c),
                                      hint="Only one category of widget: from each widget's own category")
        box.append(self.chips)
        self.g_gallery.add(box)

    def _filter(self, query=None, category=None):
        if query is not None:
            self.query = query.strip().lower()
        if category is not None:
            self.category = category
        self.fill_gallery()
        self.fill_catalog()

    def matches(self, cat, *words):
        if self.category != "all" and cat != self.category:
            return False
        hay = " ".join(str(w or "") for w in words).lower()
        return all(q in hay for q in self.query.split())

    def picture(self, path, w=120, h=72):
        if path and os.path.isfile(path):
            pic = Gtk.Picture.new_for_filename(path)
            pic.set_content_fit(Gtk.ContentFit.CONTAIN)
            pic.set_can_shrink(True)
        else:
            pic = Gtk.Image.new_from_icon_name("view-grid-symbolic")
            pic.set_pixel_size(32)
        pic.set_size_request(w, h)
        return pic

    def fill_gallery(self):
        if not self.gallery:
            return
        ctx = self.ctx
        for k in self.sections:
            ctx.clear_group(self.sections[k], self.rows[k])
        shown = {k: 0 for k in self.sections}
        for w in self.gallery.get("widgets") or []:
            if not self.matches(w["category"], w["name"], w["title"], w["description"], w["reads"], w["author"]):
                continue
            if not w.get("available", True) and not w["visible"]:      # nothing it could show here
                continue
            sec = "desktop" if w["visible"] else {"bromigos": "builtin", "homelab": "builtin",
                                                  "extension": "extensions"}.get(w["source"], "yours")
            self.rows[sec].append(self.card(self.sections[sec], w))
            shown[sec] += 1
        for k, g in self.sections.items():
            g.set_visible(shown[k] > 0 or (k == "desktop" and not self.query and self.category == "all"))
        if not any(shown.values()):
            self.sections["desktop"].set_visible(True)
            self.rows["desktop"].append(ctx.row(self.sections["desktop"], "No widget matches",
                                                "Try other words, or All", hint="Nothing here has those words"))

    def card(self, g, w):
        ctx = self.ctx
        title = w["title"].title() if w["title"].isupper() else w["title"]
        meta = f"by {w['author']}" + (f" · reads {w['reads']}" if w.get("reads") else "")
        if w.get("error"):
            meta += f" · can't load: {w['error']}"
        elif not w.get("available", True):
            meta += f" · can't show anything here: {w.get('unavailable') or 'not available'}"
        sub = (w["description"] or "A widget") + "\n" + meta
        box = Gtk.Box(spacing=6)
        if w.get("form"):
            b = ctx.button("Settings…", lambda w=w: self.form(w), f"{title}'s own settings: "
                           + ", ".join(f["label"] for f in w["form"]))
            b._bromigos_key = f"form-{w['name']}"            # bromigos settings widgets#form-NAME opens it
            b._bromigos_activate = lambda w=w: self.form(w)
            box.append(b)
        elif w.get("settings"):
            s = w["settings"]
            box.append(ctx.button("Settings…", lambda s=s: ctx.open_page(s["page"], s.get("key")),
                                  f"{title}'s own settings: {s['what']}"))
        if len(w.get("sizes") or []) > 1:
            opts = [(c["name"], c["name"].title()) for c in w["sizes"]]
            cur = w.get("size_class") or w.get("default_size")
            box.append(ctx.dropdown(opts, cur, on_select=lambda c, n=w["name"], t=title, was=cur: self._change(
                ["size", n, c], f"{t}: {c}", ["size", n, was] if was else None, gallery=True),
                hint=f"{title}'s size: each size lays it out its own way, with more to see as it grows",
                max_chars=22))
        if not w["visible"]:
            box.append(ctx.button("Add to desktop", lambda n=w["name"], t=title: self._change(
                ["add", n], f"{t}: on, in a free spot", ["hide", n], gallery=True),
                f"Puts {title} on the desktop, in a free spot", primary=True))
        ext = w.get("extension")
        if ext:
            box.append(ctx.button("Uninstall", lambda e=ext: self.uninstall(e["name"]),
                                  f"Removes the {e_name(ext)} extension (bromigos ext remove), and its widget"))
        sw = Gtk.Switch(active=bool(w["visible"]), valign=Gtk.Align.CENTER)
        ctx.hint(sw, f"{title} on or off" + (f"; {w['key']} shows or hides it any time" if w.get("key") else ""))
        sw.connect("notify::active", lambda s, _p, n=w["name"], t=title: self._change(
            ["show" if s.get_active() else "hide", n], f"{t}: {'on' if s.get_active() else 'off'}",
            ["hide" if s.get_active() else "show", n], gallery=True))
        box.append(sw)
        r = ctx.row(g, title, sub, key=f"panel-{w['name']}", control=box,
                    hint=f"{title}: {w['description'] or 'a widget'} ({w['category']}; made by {w['author']})",
                    advanced={"file": (self.doc or {}).get("user_file") or "layout.json",
                              "key": f"panels[name={w['name']}].visible",
                              "runs": f"bromigos panels show|hide|add {w['name']}",
                              "note": f"min {w['min_size'][0]}×{w['min_size'][1]}, "
                                      f"max {w['max_size'][0]}×{w['max_size'][1]} px"})
        pic = self.picture(self.previews.get(w["name"]))
        ctx.hint(pic, f"{title}, drawn when this page opened")
        r.add_prefix(pic)
        if not w.get("available", True):
            r.add_css_class("dim-label")                # greyed: switch it off, or set up what it needs
        return r

    # ------------------------------------------------------------------ the catalog
    def fill_catalog(self):
        if self.catalog is None:
            return
        ctx = self.ctx
        g = self.g_more
        ctx.clear_group(g, self.rows["more"])
        rows = self.rows["more"]
        c = self.catalog
        if c.get("_error"):
            rows.append(ctx.failed(g, EXT + ["search", "--kind", "widget", "--json"], c["_error"]))
            return
        for err in c.get("errors") or []:
            rows.append(ctx.note(g, f"A catalog didn't answer: {err}", "warn"))
        n = 0
        for e in c.get("results") or []:
            title = e.get("display_name") or e["name"]
            cat = category_of(e.get("tags"))
            authors = ", ".join(a.split(" <")[0] for a in e.get("authors") or []) or "an unnamed author"
            if not self.matches(cat, e["name"], title, e.get("description"), authors, " ".join(e.get("tags") or [])):
                continue
            code = bool(CODE_KINDS & set(e.get("kinds") or []))
            meta = f"by {authors} · {e.get('licence') or 'no licence given'} · " + \
                   ("runs code" if code else "data only")
            box = Gtk.Box(spacing=6)
            link = repo_link(e)
            if link:
                box.append(ctx.button("Repository", lambda u=link: ctx.open_url(u),
                                      f"Opens its source in your browser: {link}"))
            if e.get("bundled"):
                state = ctx.hint(Gtk.Label(label="Comes with bromigOS"), "Nothing to install")
                box.append(state)
            elif e.get("installed"):
                box.append(ctx.hint(Gtk.Label(label="Installed"), f"{title} is installed: its widget is in the "
                                                                  "gallery above"))
                box.append(ctx.button("Uninstall", lambda nm=e["name"]: self.uninstall(nm),
                                      f"Removes {title} (bromigos ext remove {e['name']})"))
            else:
                box.append(ctx.button("Install…", lambda nm=e["name"]: self.install(nm),
                                      f"Opens a terminal running bromigos ext install {e['name']}: it shows what "
                                      "the widget can do and asks you first", primary=True))
            r = ctx.row(g, title, (e.get("description") or "") + "\n" + meta, control=box,
                        hint=f"{title}, from {e.get('catalog') or 'the catalog'}"
                             + (": a widget runs code as you, so installing asks you first" if code else ""),
                        advanced={"runs": " ".join(e.get("install") or EXT + ["install", e["name"]]),
                                  "note": link or e.get("url") or ""})
            pic = self.picture(e.get("preview"))
            ctx.hint(pic, f"{title}: the catalog's picture of it")
            r.add_prefix(pic)
            rows.append(r)
            n += 1
        if not n:
            rows.append(ctx.row(g, "Nothing found", "No catalog widget matches" if self.query or self.category != "all"
                                else "The catalog lists no widgets yet", hint="bromigos ext search --kind widget"))
        r = ctx.row(g, "Install from URL", "A widget from any git repository, or a folder: you see what it can do "
                                           "before it's installed", key="install-url",
                    hint="Paste a git URL or pick a folder; it's checked before anything is installed",
                    buttons=[("Install from URL…", self.from_url, "Fetches a widget, shows what it would add and "
                                                                  "what it can do, then asks")])
        r._bromigos_activate = self.from_url             # bromigos settings widgets#install-url opens it
        rows.append(r)
        rows.append(ctx.row(g, "Make your own", "bromigos ext new widget NAME makes a working widget to edit",
                            hint="Opens the guide to writing a widget",
                            buttons=[("Guide", lambda: ctx.open_docs("extensions.md"),
                                      "The manual's Extensions page: making and sharing a widget")]))

    def form(self, w):
        from bromigos_settings.widgetform import WidgetForm
        WidgetForm(self.ctx, w, done=lambda: self.read_gallery()).present()

    def from_url(self):
        from bromigos_settings.widgetform import InstallFromURL
        InstallFromURL(self.ctx, done=self.refresh).present()

    def install(self, name):
        self.ctx.terminal(EXT + ["install", name])
        self.ctx.toast(f"In a terminal: bromigos ext install {name}", timeout=6)
        GLib.timeout_add_seconds(12, lambda: (self.refresh(), False)[1])

    def uninstall(self, name):
        self.ctx.confirm(f"Uninstall {name}?", "Its widget goes from your desktop, and its links and checkout go "
                                               f"(the ledger keeps a line). Install it again: bromigos ext install {name}.",
                         "Uninstall", lambda: self.ctx.change(EXT + ["remove", name, "--json"],
                                                              lambda d: f"Uninstalled {name}",
                                                              done=lambda _d: self.refresh()), destructive=True)

    # ------------------------------------------------------------------ changes
    def edit(self):
        self.ctx.change(CMD + ["edit", "--json"], lambda d: d.get("said") or "Edit mode is on")

    def _change(self, args, said, undo_args, gallery=False):
        def done(d):
            self.sync(d) if d.get("panels") is not None else None
            if gallery:
                self.read_gallery()
        self.ctx.change(CMD + args + ["--json"], lambda d: d.get("said") or said,
                        undo=(CMD + undo_args + ["--json"]) if undo_args else None,
                        done=done, failed=lambda *_: self.refresh())

    def _open(self, d):
        if d["yours"]:
            self.ctx.open_file(d["user_file"])
        else:
            self.ctx.toast("No layout of yours yet: change anything here and it's made (or copy bromigOS's)")

    def reset(self):
        self.ctx.change(CMD + ["reset", "--json"], lambda d: d.get("said") or "Reset",
                        done=lambda d: (self.sync(d), self.read_gallery()))


def e_name(ext):
    return ext.get("name") or "?"


def build(ctx):
    p = WidgetsPage(ctx)
    p.page._widgets = p
    return p.page


def refresh(widget):
    widget._widgets.refresh()


PAGE = Page(
    id="widgets", title="Widgets", group="desktop", order=24, build=build, refresh=refresh, docs="settings.md#widgets",
    icon="view-grid-symbolic view-app-grid-symbolic", summary="the widget gallery, edit mode, the weather",
    intro="The desktop panels: every widget there is, which are on, where they sit, more from the catalog, and the "
          "weather's place.",
    keywords=["panels", "desktop widgets", "bromigos-widgets", "layout.json", "widget gallery"],
    entries=[
        Entry("layout", "Panel layout", ["positions", "arrange panels", "layout.json"], "Layout"),
        Entry("edit", "Edit widgets on the desktop", ["edit mode", "move widgets", "drag panels", "resize panels"],
              "Layout"),
        Entry("monitor", "Panels' monitor", ["which screen", "output"], "Where they go"),
        Entry("panels", "Widget gallery", ["show panel", "hide panel", "system panel", "network panel",
                                           "storage", "workbench", "notes panel", "connections", "add widget"],
              "Widget gallery"),
        Entry("more", "Get more widgets", ["install widget", "community widgets", "catalog", "download widgets"],
              "Get more widgets"),
        Entry("weather", "Weather", ["forecast", "open-meteo"], "Weather"),
        Entry("weather-place", "Weather place", ["city", "location", "town"], "Weather"),
        Entry("weather-units", "Weather units", ["celsius", "fahrenheit", "metric", "imperial"], "Weather"),
        Entry("weather-name", "Weather label", ["header"], "Weather"),
    ])
