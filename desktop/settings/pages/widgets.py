"""Widgets: the desktop panels (bromigos-widgets): which are on, where they sit (drawn small),
the monitor they go on, and the weather panel's place (docs/settings.md, "Widgets";
docs/widgets.md).

Everything goes through `bromigos panels … --json`: a change writes your layout.json
(bromigOS's copied the first time, every key kept) or weather.toml and tells running
panels to read it again; it toasts Undo."""
from gi.repository import GLib, Gtk

from bromigos_settings import Entry, Page

CMD = ["bromigos", "panels"]


def _rgb(hexv, fallback=(0.2, 1.0, 0.1)):
    try:
        h = hexv.lstrip("#")
        return tuple(int(h[i:i + 2], 16) / 255 for i in (0, 2, 4))
    except (AttributeError, ValueError):
        return fallback


class WidgetsPage:
    def __init__(self, ctx):
        self.ctx = ctx
        self.doc = None
        self.groups = []
        self.page = ctx.page()
        self.page.set_reset(self.reset, what="The panels go back to bromigOS's layout (your layout.json is removed: "
                                             "positions, sizes, which are on, the monitor) and the weather has no "
                                             "place (weather.toml removed).")
        g = ctx.group(self.page, "Panels")
        self.groups.append(g)
        ctx.loading(g, "Reading the panels' layout…")
        ctx.on_restyle(lambda _c: getattr(self, "area", None) and self.area.queue_draw())
        self.refresh()

    def refresh(self):
        self.ctx.json(CMD + ["--json"], self._got)

    def _got(self, doc, err):
        if not doc or doc.get("ok") is False:
            self._clear()
            self.ctx.failed(self._group("Panels"), CMD + ["--json"], (doc or {}).get("error") or err)
            return
        self.sync(doc)

    def _clear(self):
        for g in self.groups:
            self.page.remove_group(g)
        self.groups = []

    def _group(self, title, desc=None, hint=None, key=None):
        g = self.ctx.group(self.page, title, desc, hint, key=key)
        self.groups.append(g)
        return g

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

    # ------------------------------------------------------------------ building
    def sync(self, d):
        self.doc = d
        self._clear()
        ctx = self.ctx
        g = self._group("Layout", "Where each panel sits on its monitor, as px from the top left under the bar.",
                        key="layout", hint=f"From {d['file'] or 'bromigOS'}")
        self.area = Gtk.DrawingArea(content_height=230, hexpand=True)
        self.area.set_draw_func(self._draw)
        ctx.hint(self.area, "The panels' layout, small: lit ones are on, dashed ones off. Move or size one with "
                            "`bromigos panels move|size NAME …`, or edit layout.json")
        g.add(self.area)
        g = self._group("Where they go", key="placement")
        where = "yours" if d["yours"] else "bromigOS's (copied to yours on the first change)"
        ctx.row(g, "Layout file", f"{d['user_file'] if d['yours'] else d['default_file']}: {where}",
                hint="Opens the layout file in your editor (bromigos-widgets reload after)",
                buttons=[("Open", lambda: self._open(d), "Opens layout.json in your editor")],
                advanced={"file": d["user_file"], "runs": "bromigos panels move|size NAME …"})
        ctx.entry_row(g, "Monitor (empty: the primary display)", d["monitor"], key="monitor",
                      on_apply=lambda v: self._change(["monitor", v.strip()], f"Panels on {v.strip() or 'the primary'}",
                                                      ["monitor", d["monitor"]]),
                      hint="The output the panels go on, e.g. DP-1; empty: the primary display (Settings › Displays)",
                      advanced={"file": d["user_file"], "key": "monitor", "runs": "bromigos panels monitor NAME"})
        state = "running: a change shows at once" if d["running"] else "not running: a change shows at their next start"
        ctx.row(g, "The panels", state, key="running",
                hint="bromigos-widgets, started at login",
                buttons=[("Reload", lambda: ctx.run(["bromigos-widgets", "reload"],
                                                    lambda ok, o, e: ctx.toast("The panels read their layout again" if ok
                                                                               else "The panels aren't running")),
                          "Makes the running panels read their layout again")] if d["running"] else [])

        g = self._group("Panels", "Each one on or off at login (its key shows or hides it now).", key="panels")
        for p in d["panels"]:
            sub = p["what"] + (f"  ·  {p['key']}" if p["key"] else "")
            ctx.switch_row(g, p["title"], sub, active=p["visible"], key=f"panel-{p['name']}",
                           hint=f"The {p['title']} panel: on or off" + (f"; {p['key']} shows or hides it now" if p["key"] else ""),
                           on_toggle=lambda on, n=p["name"], t=p["title"]: self._change(
                               ["show" if on else "hide", n], f"{t}: {'on' if on else 'off'}",
                               ["hide" if on else "show", n]),
                           advanced={"file": d["user_file"], "key": f"panels[name={p['name']}].visible",
                                     "runs": f"bromigos panels show|hide {p['name']}"})

        w = d["weather"]
        g = self._group("Weather", "The weather panel's place (Open-Meteo: free, no key). Nothing is fetched until "
                                   "there is one.", key="weather")
        here = w.get("place") or (f"{w['lat']}, {w['lon']}" if w.get("lat") is not None else "")
        ctx.entry_row(g, "Place (a city or town)", w.get("place") or "", key="weather-place",
                      on_apply=lambda v: v.strip() and self._change(["weather", "place", v.strip()],
                                                                    f"Weather for {v.strip()}", None),
                      hint="Where the forecast is for: a city or town, found by Open-Meteo's geocoder",
                      advanced={"file": w["file"], "key": "place", "runs": "bromigos panels weather place PLACE"})
        ctx.combo_row(g, "Units", "", options=[("metric", "°C and km/h"), ("imperial", "°F and mph")],
                      current=w.get("units") or "metric", key="weather-units",
                      on_select=lambda u: self._change(["weather", "units", u], "Units changed",
                                                       ["weather", "units", w.get("units") or "metric"]),
                      hint="Celsius and km/h, or Fahrenheit and mph",
                      advanced={"file": w["file"], "key": "units", "runs": "bromigos panels weather units metric|imperial"})
        ctx.entry_row(g, "Label", w.get("name") or "", key="weather-name",
                      on_apply=lambda v: self._change(["weather", "name", v.strip()], "Label changed", None),
                      hint="The panel's header (empty: the place's name)",
                      advanced={"file": w["file"], "key": "name", "runs": "bromigos panels weather name TEXT"})
        if here:
            ctx.row(g, "Now", here, hint="The place the forecast is for",
                    buttons=[("Clear", lambda: self._change(["weather", "clear"], "No weather place", None),
                              "Removes the place: the panel fetches nothing")])
        if not next((p for p in d["panels"] if p["name"] == "weather" and p["visible"]), None):
            ctx.note(g, "The weather panel is off: switch it on under Panels to see it.", "note")
        GLib.idle_add(lambda: (self.area.queue_draw(), False)[1])

    # ------------------------------------------------------------------ changes
    def _change(self, args, said, undo_args):
        self.ctx.change(CMD + args + ["--json"], lambda d: d.get("said") or said,
                        undo=(CMD + undo_args + ["--json"]) if undo_args else None,
                        done=self.sync, failed=lambda *_: self.refresh())

    def _open(self, d):
        if d["yours"]:
            self.ctx.open_file(d["user_file"])
        else:
            self.ctx.toast("No layout of yours yet: change anything here and it's made (or copy bromigOS's)")

    def reset(self):
        self.ctx.change(CMD + ["reset", "--json"], lambda d: d.get("said") or "Reset", done=self.sync)


def build(ctx):
    p = WidgetsPage(ctx)
    p.page._widgets = p
    return p.page


def refresh(widget):
    widget._widgets.refresh()


PAGE = Page(
    id="widgets", title="Widgets", group="desktop", order=24, build=build, refresh=refresh, docs="settings.md#widgets",
    icon="view-grid-symbolic view-app-grid-symbolic", summary="the panels, the weather",
    intro="The desktop panels: which are on, where they sit, the monitor they're on, and the weather's place.",
    keywords=["panels", "desktop widgets", "bromigos-widgets", "layout.json"],
    entries=[
        Entry("layout", "Panel layout", ["positions", "arrange panels", "layout.json"], "Layout"),
        Entry("monitor", "Panels' monitor", ["which screen", "output"], "Layout"),
        Entry("panels", "Panels on or off", ["show panel", "hide panel", "system panel", "network panel",
                                             "storage", "workbench", "notes panel", "connections"], "Panels"),
        Entry("weather", "Weather", ["forecast", "open-meteo"], "Weather"),
        Entry("weather-place", "Weather place", ["city", "location", "town"], "Weather"),
        Entry("weather-units", "Weather units", ["celsius", "fahrenheit", "metric", "imperial"], "Weather"),
        Entry("weather-name", "Weather label", ["header"], "Weather"),
    ])
