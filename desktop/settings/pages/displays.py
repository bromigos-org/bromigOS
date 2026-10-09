"""Displays: each monitor's resolution, refresh rate, scale, orientation, on or off, where it
sits, and which is primary (docs/settings.md, "Displays").

Everything goes through `bromigos display … --json` (Hyprland, through the block `bromigos
setup monitors` keeps in hyprland.lua). Unlike the other pages, changes here are staged:
they wait for Apply and then go together, as a trial: "Keep these display settings?"
counts down 15 seconds, and if nobody answers (a screen gone dark can't be answered) they
revert by themselves. The command's own watchdog reverts even when this window is gone."""
import math

import cairo
import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gdk, GLib, Gtk  # noqa: E402

from bromigos_settings import Entry, Page  # noqa: E402

DISPLAY = ["bromigos", "display"]
SCALES = [1.0, 1.25, 1.5, 1.75, 2.0]
ORIENTATIONS = [(0, "Normal"), (1, "Turned right (90°)"), (2, "Upside down (180°)"), (3, "Turned left (270°)")]
CONFIRM = 15
SNAP = 48                       # logical px: closer than this to another display's edge snaps to it


def _trim(f):
    s = f"{float(f):.2f}"
    return s.rstrip("0").rstrip(".")


def _esc(text):
    return str(text).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _rgba(hexv, a=1.0):
    h = (hexv or "#39ff14").lstrip("#")
    return tuple(int(h[i:i + 2], 16) / 255 for i in (0, 2, 4)) + (a,)


class DisplaysPage:
    def __init__(self, ctx):
        self.ctx = ctx
        self.doc = None
        self.staged = {}               # name -> {mode, scale, x, y, transform, on}
        self.primary = None            # a staged primary
        self.sel = None
        self.drag = None
        self.dialog = None
        self.asking = False            # a trial's question is (about to be) up
        self.page = ctx.page()
        self._build()
        self.refresh()

    # ------------------------------------------------------------------ building
    def _build(self):
        ctx = self.ctx
        g = ctx.group(self.page, "Arrangement", "Where the displays sit, as Hyprland places them. Click one to "
                                                "choose it, drag it to move it; it snaps to the others' edges.",
                      key="arrangement")
        self.area = Gtk.DrawingArea(content_height=230, hexpand=True, focusable=True)
        self.area.set_draw_func(self._draw)
        self.area.add_css_class("bromigos-arrangement")
        ctx.hint(self.area, "The displays as they sit: click one to choose it, drag it to move it (it snaps to the "
                            "others' edges), arrow keys nudge the chosen one (Shift: further). Moves wait for Apply.")
        click = Gtk.GestureClick()
        click.connect("pressed", self._pressed)
        self.area.add_controller(click)
        drag = Gtk.GestureDrag()
        drag.connect("drag-begin", self._drag_begin)
        drag.connect("drag-update", self._drag_update)
        drag.connect("drag-end", self._drag_end)
        self.area.add_controller(drag)
        keys = Gtk.EventControllerKey()
        keys.connect("key-pressed", self._key)
        self.area.add_controller(keys)
        frame = Gtk.Frame(child=self.area)
        frame.add_css_class("bromigos-arrangement-frame")
        g.add(frame)
        self.off_label = Gtk.Label(xalign=0, wrap=True)
        self.off_label.add_css_class("dim-label")
        self.off_label.set_margin_top(6)
        ctx.hint(self.off_label, "Displays switched off: they aren't drawn above; turn one on below")
        self.off_label.set_visible(False)
        g.add(self.off_label)

        # the apply bar: what's waiting, Apply, and dropping the staged changes
        g = ctx.group(self.page, "Apply", key="apply-group")
        self.apply_btn = ctx.button("Apply", self.apply, "Applies every staged change together, then asks whether "
                                    "to keep them (15 s, then they revert by themselves)", primary=True)
        self.discard_btn = ctx.button("Undo changes", self.discard, "Drops the staged changes: nothing is applied")
        box = Gtk.Box(spacing=8, valign=Gtk.Align.CENTER)
        box.append(self.discard_btn)
        box.append(self.apply_btn)
        self.apply_row = ctx.row(g, "No changes waiting", "Changes here wait for Apply, then go together",
                                 hint="What's staged: nothing changes until Apply", control=box, key="apply",
                                 advanced={"runs": "bromigos display apply --output NAME [--mode WxH@HZ] [--scale S] "
                                                   "[--position XxY] [--transform N] [--off|--on] … [--primary NAME]",
                                           "file": "~/.config/hypr/hyprland.lua",
                                           "key": "the block `-- >>> bromigos setup monitors` (bromigos.monitors)"})
        self.trial_row = None
        self.trial_group = g

        g = ctx.group(self.page, "The chosen display", key="selected")
        self.sel_group = g
        self.out_combo = ctx.combo_row(g, "Display", "", options=[], on_select=self._choose, key="display",
                                       hint="Which display the settings below are for (or click it above)")
        self.mode_combo = ctx.combo_row(
            g, "Resolution", "", options=[], on_select=lambda v: self._stage("res", v), key="resolution",
            hint="Its resolution: the modes the display offers (from its EDID)",
            advanced={"runs": "bromigos display apply --output NAME --mode WxH@HZ"})
        self.hz_combo = ctx.combo_row(
            g, "Refresh rate", "", options=[], on_select=lambda v: self._stage("hz", v), key="refresh",
            hint="How many times a second it redraws, at that resolution",
            advanced={"runs": "bromigos display apply --output NAME --mode WxH@HZ"})
        self.scale_combo = ctx.combo_row(
            g, "Scale", "", options=[], on_select=lambda v: self._stage("scale", v), key="scale",
            hint="How big everything is drawn: 1 is a pixel a pixel; the suggested one comes from the display's "
                 "pixel density (about 110 per inch at 1x)",
            advanced={"runs": "bromigos display apply --output NAME --scale S"})
        self.rot_combo = ctx.combo_row(
            g, "Orientation", "", options=ORIENTATIONS, on_select=lambda v: self._stage("transform", v),
            key="orientation", hint="Turn the picture for a display on its side or upside down",
            advanced={"runs": "bromigos display apply --output NAME --transform 0-3"})
        self.on_row = ctx.switch_row(
            g, "On", "Off: nothing is drawn on it; its workspaces move to the others", key="enabled",
            on_toggle=lambda v: self._stage("on", v), hint="Turns the display on or off (one always stays on)",
            advanced={"runs": "bromigos display apply --output NAME --off|--on",
                      "note": "written as { output = NAME, disabled = true }"})
        self.primary_row = ctx.switch_row(
            g, "Primary display", "The live layer, the widgets and VECTOR go on it", key="primary",
            on_toggle=self._primary, hint="Makes this the display bromigOS's own surfaces go on",
            advanced={"file": "~/.config/bromigos/monitors.toml", "key": "primary",
                      "runs": "bromigos display apply --primary NAME"})
        self.problem = None

        g = ctx.group(self.page, "More")
        ctx.row(g, "Displays off when idle", "When the screens go dark: Idle & lock",
                hint="Opens Idle & lock, where the displays-off timer is", activate=lambda: ctx.open_page("idle"),
                key="idle")
        ctx.row(g, "In a terminal", "bromigos setup monitors asks the same questions (primary, order, scale, "
                                    "refresh) and writes the same block",
                hint="Opens bromigos setup monitors in a terminal", key="setup",
                buttons=[("Open…", lambda: ctx.terminal(["bromigos", "setup", "monitors"]),
                          "bromigos setup monitors, in a terminal")],
                advanced={"runs": "bromigos setup monitors", "file": "~/.config/hypr/hyprland.lua"})
        ctx.on_restyle(lambda _c: self.area.queue_draw())

    # ------------------------------------------------------------------ state
    def refresh(self):
        self.ctx.json(DISPLAY + ["--json"], self._got)

    def _got(self, doc, err):
        if not doc or doc.get("ok") is False:
            self._problem(f"`bromigos display` didn't answer: {(doc or {}).get('error') or err}", "error")
            return
        self.sync(doc)

    def _problem(self, text, level="warn"):
        if self.problem is not None:
            self.sel_group.remove(self.problem)
            self.problem = None
        if text:
            self.problem = self.ctx.note(self.sel_group, text, level)

    def sync(self, d):
        self.doc = d
        self.staged = {}
        self.primary = None
        outs = d.get("outputs") or []
        running = d.get("running", False)
        self._problem(None if running else d.get("error") or "Hyprland isn't running")
        for w in (self.out_combo, self.mode_combo, self.hz_combo, self.scale_combo, self.rot_combo, self.on_row,
                  self.primary_row, self.area):
            w.set_sensitive(running and bool(outs))
        if self.sel not in [o["name"] for o in outs]:
            self.sel = next((o["name"] for o in outs if o["primary"]), outs[0]["name"] if outs else None)
        self.out_combo.set_options([(o["name"], self._title(o)) for o in outs], self.sel)
        self.page.set_reset(self.reset if d.get("block") else None,
                            hint=None if d.get("block") else "Nothing pinned: every display already follows "
                                                             "bromigOS's defaults (its preferred mode, the scale "
                                                             "its density gives, placed automatically)",
                            what="Every display back to its preferred mode, the scale its density gives and an "
                                 "automatic place (the pinned block goes). You get 15 seconds to keep it.")
        self._trial_row(d.get("trial") or {})
        self._show_selected()
        self._changed()

    def _title(self, o):
        name = o["model"] or o["make"] or o["description"]
        return f"{o['name']} · {name}" if name else o["name"]

    def _out(self, name):
        return next((o for o in (self.doc or {}).get("outputs", []) if o["name"] == name), None)

    def eff(self, name):
        """The output as it will be: what it is now, the staged changes on top."""
        o = self._out(name)
        if o is None:
            return None
        s = self.staged.get(name, {})
        e = {"name": name, "width": o["width"], "height": o["height"], "refresh": o["refresh"],
             "scale": o["scale"], "x": o["x"], "y": o["y"], "transform": o["transform"], "on": o["enabled"]}
        e.update(s)
        prim = self.primary if self.primary is not None else (self.doc or {}).get("primary")
        e["primary"] = name == prim
        sw, sh = (e["height"], e["width"]) if e["transform"] % 2 else (e["width"], e["height"])
        e["lw"], e["lh"] = sw / e["scale"], sh / e["scale"]
        return e

    def _show_selected(self):
        o = self._out(self.sel)
        if o is None:
            return
        e = self.eff(self.sel)
        self.out_combo.set_quiet(self.sel)
        res = []
        for m in o["modes"]:
            r = f"{m['width']}x{m['height']}"
            if r not in res:
                res.append(r)
        cur = f"{e['width']}x{e['height']}"
        if cur not in res:
            res.insert(0, cur)
        nat = res[0] if o["modes"] else cur
        self.mode_combo.set_options([(r, r.replace("x", " × ") + (" native" if r == nat else "")) for r in res], cur)
        hzs = sorted({m["refresh"] for m in o["modes"] if f"{m['width']}x{m['height']}" == cur}, reverse=True) \
            or [e["refresh"]]
        best = min(hzs, key=lambda h: abs(h - e["refresh"]))
        self.hz_combo.set_options([(h, f"{_trim(h)} Hz") for h in hzs], best)
        scales = sorted(set(SCALES + [o["suggested_scale"], round(e["scale"], 2)]))
        self.scale_combo.set_options([(s, f"{_trim(s)}x" + (" suggested" if s == o["suggested_scale"] else ""))
                                      for s in scales], round(e["scale"], 2))
        self.rot_combo.set_quiet(e["transform"] if e["transform"] in dict(ORIENTATIONS) else 0)
        self.on_row.set_quiet(e["on"])
        self.primary_row.set_quiet(e["primary"])
        self.primary_row.set_sensitive(e["on"] and (self.doc or {}).get("running", False))
        phys = o["physical"]
        sub = f"{o['description'] or o['name']}" + (f" · {phys['inches']:.0f} inch ({phys['width_mm']}×{phys['height_mm']} mm)"
                                                    if phys.get("inches") else "")
        self.out_combo.set_subtitle(_esc(sub))
        self.mode_combo.set_subtitle(_esc(f"now {o['width']}x{o['height']}"))
        lw, lh = round(e["lw"]), round(e["lh"])
        self.scale_combo.set_subtitle(_esc(f"looks like {lw} × {lh}; suggested for this display: "
                                           f"{_trim(o['suggested_scale'])}x"))
        self.area.queue_draw()

    def _trial_row(self, t):
        if self.trial_row is not None:
            self.ctx.clear_group(self.trial_group, [self.trial_row])
            self.trial_row = None
        if t.get("pending") and self.dialog is None and not self.asking:
            self.trial_row = self.ctx.row(
                self.trial_group, "A display change is waiting to be kept",
                f"{t.get('said', '')}: it reverts by itself in {t.get('remaining', 0)} s",
                hint="A change applied from here or `bromigos display apply` that nobody kept yet",
                buttons=[("Keep", self.keep, "Keeps the change (bromigos display keep)"),
                         ("Revert", self.revert, "Puts the old settings back now (bromigos display revert)")])

    # ------------------------------------------------------------------ staging
    def _stage(self, what, v):
        if self.sel is None or self.doc is None:
            return
        o, s = self._out(self.sel), self.staged.setdefault(self.sel, {})
        if what == "res":
            w, h = (int(x) for x in v.split("x"))
            s["width"], s["height"] = w, h
            hzs = [m["refresh"] for m in o["modes"] if (m["width"], m["height"]) == (w, h)]
            if hzs:
                s["refresh"] = max(hzs)
            s.setdefault("x", o["x"])
            s.setdefault("y", o["y"])
        elif what == "hz":
            s["refresh"] = v
        elif what == "scale":
            s["scale"] = v
        elif what == "transform":
            s["transform"] = v
        elif what == "on":
            if not v and sum(1 for n in self._names() if self.eff(n)["on"]) <= 1:
                self.ctx.toast("One display always stays on")
                self.on_row.set_quiet(True)
                return
            s["on"] = v
            if not v and self.eff(self.sel)["primary"]:
                self.primary = next(n for n in self._names() if n != self.sel and self.eff(n)["on"])
        self._clean(self.sel)
        self._show_selected()
        self._changed()

    def _primary(self, on):
        if self.sel is None:
            return
        if on:
            self.primary = self.sel
        elif self.eff(self.sel)["primary"]:
            # off on the primary: the next display that's on takes it
            others = [n for n in self._names() if n != self.sel and self.eff(n)["on"]]
            if not others:
                self.ctx.toast("The only display that's on is the primary")
                self.primary_row.set_quiet(True)
                return
            self.primary = others[0]
        if self.primary == (self.doc or {}).get("primary"):
            self.primary = None
        self._show_selected()
        self._changed()

    def _names(self):
        return [o["name"] for o in (self.doc or {}).get("outputs", [])]

    def _clean(self, name):
        """Drops staged values equal to what the display has now."""
        o, s = self._out(name), self.staged.get(name, {})
        now = {"width": o["width"], "height": o["height"], "refresh": o["refresh"], "scale": o["scale"],
               "x": o["x"], "y": o["y"], "transform": o["transform"], "on": o["enabled"]}
        for k in list(s):
            if (abs(s[k] - now[k]) < 0.01) if isinstance(s[k], float) else s[k] == now[k]:
                del s[k]
        if not s:
            self.staged.pop(name, None)

    def _args(self):
        args = []
        for name, s in self.staged.items():
            e = self.eff(name)
            a = ["--output", name]
            if {"width", "height", "refresh"} & set(s):
                a += ["--mode", f"{e['width']}x{e['height']}@{_trim(e['refresh'])}"]
            if "scale" in s:
                a += ["--scale", _trim(e["scale"])]
            if {"x", "y"} & set(s):
                a += ["--position", f"{int(e['x'])}x{int(e['y'])}"]
            if "transform" in s:
                a += ["--transform", str(e["transform"])]
            if "on" in s:
                a.append("--on" if e["on"] else "--off")
            if len(a) > 2:
                args += a
        if self.primary is not None:
            args += ["--primary", self.primary]
        return args

    def _changed(self):
        n = sum(len(s) for s in self.staged.values()) + (1 if self.primary is not None else 0)
        waiting = bool(self._args())
        self.apply_btn.set_sensitive(waiting)
        (self.apply_btn.add_css_class if waiting else self.apply_btn.remove_css_class)("suggested-action")
        self.discard_btn.set_sensitive(waiting)
        if waiting:
            names = sorted(set(self.staged) | ({self.primary} if self.primary else set()))
            self.apply_row.set_title(f"{n} change{'s' if n != 1 else ''} waiting")
            self.apply_row.set_subtitle(_esc(
                f"on {', '.join(names)}: Apply sends them together, then you have {CONFIRM} s to keep them"))
        else:
            self.apply_row.set_title("No changes waiting")
            self.apply_row.set_subtitle("Changes here wait for Apply, then go together")
        self.area.queue_draw()

    def discard(self):
        self.staged, self.primary = {}, None
        self._show_selected()
        self._changed()

    def _choose(self, name):
        self.sel = name
        self._show_selected()

    # ------------------------------------------------------------------ the trial
    def _snapshot_args(self):
        """apply's arguments that put every display back as it is now (the Undo after Keep)."""
        args = []
        for o in (self.doc or {}).get("outputs", []):
            args += ["--output", o["name"]]
            if o["enabled"]:
                args += ["--on", "--mode", o["mode"], "--scale", _trim(o["scale"]), "--position",
                         f"{o['x']}x{o['y']}", "--transform", str(o["transform"])]
            else:
                args += ["--off"]
        if (self.doc or {}).get("primary"):
            args += ["--primary", self.doc["primary"]]
        return args

    def apply(self):
        args = self._args()
        if not args:
            return
        before = self._snapshot_args()
        self._run(DISPLAY + ["apply", *args, "--confirm", str(CONFIRM), "--json"], before)

    def reset(self):
        before = self._snapshot_args()
        self._run(DISPLAY + ["reset", "--confirm", str(CONFIRM), "--json"], before)
        return None

    def _run(self, argv, before):
        self.apply_btn.set_sensitive(False)

        def done(doc, err):
            if not doc or doc.get("ok") is False:
                self.ctx.toast(f"Not changed: {(doc or {}).get('error') or err}"[:220], timeout=10)
                self.refresh()
                return
            t = doc.get("trial") or {}
            self.asking = bool(t.get("pending"))
            self.sync(doc)
            if t.get("pending"):
                self._ask(t.get("said") or "The displays changed", before, t.get("remaining") or CONFIRM)
            else:
                self.ctx.toast(doc.get("said", "Displays changed"))
        self.ctx.json(argv, done)

    def _ask(self, said, before, left=CONFIRM):
        """Keep these display settings? A countdown (the trial's own time left); Esc, closing
        or the end of it reverts."""
        d = Adw.AlertDialog(heading="Keep these display settings?")
        d.add_response("revert", "Revert")
        d.add_response("keep", "Keep")
        d.set_response_appearance("keep", Adw.ResponseAppearance.SUGGESTED)
        d.set_default_response("revert")
        d.set_close_response("revert")
        self.left = int(left)

        def body():
            d.set_body(f"{said[:1].upper() + said[1:]}.\nThey revert by themselves in {self.left} s: if a screen "
                       "went dark, wait, or press Esc.")
        body()

        def tick():
            if self.dialog is not d:
                return False
            self.left -= 1
            if self.left <= 0:
                d.close()                      # the close response: revert (the watchdog may have already)
                return False
            body()
            return True
        d.connect("response", lambda _d, r: self._answered(r, before))
        self.dialog = d
        self._tick = GLib.timeout_add_seconds(1, tick)
        d.present(self.page.get_root())

    def _answered(self, r, before):
        self.dialog = None
        self.asking = False
        if r == "keep":
            self.keep(before)
        else:
            self.revert()

    def keep(self, before=None):
        def done(doc, err):
            if not doc or doc.get("ok") is False:
                self.ctx.toast(f"Couldn't keep it: {(doc or {}).get('error') or err}")
                self.refresh()
                return
            self.sync(doc)
            if doc.get("said", "").startswith("Nothing to keep"):
                self.ctx.toast("Too late: they had already reverted by themselves")
                return
            undo = None
            if before:
                undo = (lambda: self._run(DISPLAY + ["apply", *before, "--confirm", str(CONFIRM), "--json"], None))
            self.ctx.toast("Display settings kept", undo=undo)
        self.ctx.json(DISPLAY + ["keep", "--json"], done)

    def revert(self):
        def done(doc, err):
            if doc and doc.get("ok") is not False:
                self.sync(doc)
                self.ctx.toast("Display settings reverted" if "reverted" in doc.get("said", "") else
                               "Display settings back as they were")
            else:
                self.ctx.toast(f"Couldn't revert: {(doc or {}).get('error') or err}")
                self.refresh()
        self.ctx.json(DISPLAY + ["revert", "--json"], done)

    # ------------------------------------------------------------------ the arrangement
    def _layout(self, w, h):
        """(scale, offset x, offset y, [eff]) fitting every display that's on in w × h."""
        es = [self.eff(n) for n in self._names()]
        es = [e for e in es if e and e["on"]]
        if not es:
            return 1, 0, 0, []
        x0, y0 = min(e["x"] for e in es), min(e["y"] for e in es)
        x1, y1 = max(e["x"] + e["lw"] for e in es), max(e["y"] + e["lh"] for e in es)
        pad = 18
        k = min((w - 2 * pad) / max(1, x1 - x0), (h - 2 * pad) / max(1, y1 - y0))
        ox = (w - (x1 - x0) * k) / 2 - x0 * k
        oy = (h - (y1 - y0) * k) / 2 - y0 * k
        return k, ox, oy, es

    def _draw(self, _area, cr, w, h):
        c = self.ctx.colors
        cr.set_source_rgba(*_rgba(c.get("void"), 1))
        cr.paint()
        k, ox, oy, es = self._layout(w, h)
        offs = [n for n in self._names() if self.eff(n) and not self.eff(n)["on"]]
        self.off_label.set_label(("Off: " + ", ".join(offs)) if offs else "")
        self.off_label.set_visible(bool(offs))
        if not es:
            cr.set_source_rgba(*_rgba(c.get("muted")))
            cr.move_to(20, h / 2)
            cr.show_text("No displays: is Hyprland running?")
            return
        cr.select_font_face("Geist Mono", cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_BOLD)
        for e in es:
            x, y, ww, hh = ox + e["x"] * k, oy + e["y"] * k, e["lw"] * k, e["lh"] * k
            sel = e["name"] == self.sel
            staged = e["name"] in self.staged
            cr.rectangle(x + 2, y + 2, ww - 4, hh - 4)
            cr.set_source_rgba(*_rgba(c.get("primary"), 0.16 if sel else 0.06))
            cr.fill_preserve()
            cr.set_line_width(2 if sel else 1)
            cr.set_source_rgba(*_rgba(c.get("primary") if sel else c.get("dim"), 1 if sel else 0.8))
            if staged:
                cr.set_dash([6, 4])
            cr.stroke()
            cr.set_dash([])
            cr.set_source_rgba(*_rgba(c.get("primary") if sel else c.get("soft")))
            cr.set_font_size(max(10, min(15, hh / 7)))
            cr.move_to(x + 10, y + 22)
            cr.show_text(e["name"] + ("  · PRIMARY" if e["primary"] else ""))
            cr.set_source_rgba(*_rgba(c.get("muted")))
            cr.set_font_size(max(9, min(12, hh / 9)))
            cr.move_to(x + 10, y + 40)
            cr.show_text(f"{e['width']}×{e['height']} @{_trim(e['refresh'])} Hz")
            cr.move_to(x + 10, y + 56)
            cr.show_text(f"{_trim(e['scale'])}x" + (f" · {dict(ORIENTATIONS).get(e['transform'], '')}"
                                                    if e["transform"] else ""))
        self._k = (k, ox, oy)

    def _hit(self, px, py):
        k, ox, oy = getattr(self, "_k", (1, 0, 0))
        for n in self._names():
            e = self.eff(n)
            if e and e["on"] and ox + e["x"] * k <= px <= ox + (e["x"] + e["lw"]) * k \
                    and oy + e["y"] * k <= py <= oy + (e["y"] + e["lh"]) * k:
                return n
        return None

    def _pressed(self, _g, _n, px, py):
        self.area.grab_focus()
        n = self._hit(px, py)
        if n:
            self.sel = n
            self._show_selected()

    def _drag_begin(self, _g, px, py):
        n = self._hit(px, py)
        if n:
            e = self.eff(n)
            self.drag = (n, e["x"], e["y"], getattr(self, "_k", (1, 0, 0))[0])
            self.sel = n
            self._show_selected()

    def _drag_update(self, _g, dx, dy):
        if not self.drag:
            return
        n, x, y, k = self.drag
        s = self.staged.setdefault(n, {})
        s["x"], s["y"] = round(x + dx / k), round(y + dy / k)
        self.area.queue_draw()

    def _drag_end(self, _g, _dx, _dy):
        if not self.drag:
            return
        n = self.drag[0]
        self.drag = None
        self._snap(n)
        self._clean(n)
        self._show_selected()
        self._changed()

    def _snap(self, n):
        """Moves `n` against the nearest edges of the others (within SNAP), so the
        displays touch, and puts the whole layout's top-left corner at 0,0."""
        e = self.eff(n)
        others = [self.eff(m) for m in self._names() if m != n]
        others = [o for o in others if o and o["on"]]
        s = self.staged.setdefault(n, {})
        if others:
            xs = [(o["x"] + o["lw"]) for o in others] + [o["x"] - e["lw"] for o in others] + \
                 [o["x"] for o in others] + [o["x"] + o["lw"] - e["lw"] for o in others]
            ys = [(o["y"] + o["lh"]) for o in others] + [o["y"] - e["lh"] for o in others] + \
                 [o["y"] for o in others] + [o["y"] + o["lh"] - e["lh"] for o in others]
            bx = min(xs, key=lambda v: abs(v - e["x"]))
            by = min(ys, key=lambda v: abs(v - e["y"]))
            if abs(bx - e["x"]) <= SNAP:
                s["x"] = round(bx)
            if abs(by - e["y"]) <= SNAP:
                s["y"] = round(by)
            # never left floating apart: if it touches nothing, put it against the nearest one's side
            e = self.eff(n)
            if not any(self._touch(e, o) for o in others):
                o = min(others, key=lambda o: math.hypot(o["x"] - e["x"], o["y"] - e["y"]))
                s["x"] = round(o["x"] + o["lw"]) if e["x"] >= o["x"] else round(o["x"] - e["lw"])
                s["y"] = round(min(max(e["y"], o["y"] - e["lh"] + 1), o["y"] + o["lh"] - 1))
        # the layout's top-left at 0,0 (Hyprland is happy either way; this reads better)
        es = [self.eff(m) for m in self._names()]
        es = [x for x in es if x and x["on"]]
        mx, my = min(x["x"] for x in es), min(x["y"] for x in es)
        if mx or my:
            for x in es:
                st = self.staged.setdefault(x["name"], {})
                st["x"], st["y"] = round(x["x"] - mx), round(x["y"] - my)
                self._clean(x["name"])

    @staticmethod
    def _touch(a, b):
        h = (abs(a["x"] + a["lw"] - b["x"]) < 1 or abs(b["x"] + b["lw"] - a["x"]) < 1) and \
            a["y"] < b["y"] + b["lh"] and b["y"] < a["y"] + a["lh"]
        v = (abs(a["y"] + a["lh"] - b["y"]) < 1 or abs(b["y"] + b["lh"] - a["y"]) < 1) and \
            a["x"] < b["x"] + b["lw"] and b["x"] < a["x"] + a["lw"]
        return h or v

    def _key(self, _c, keyval, _code, state):
        if self.sel is None:
            return False
        step = 100 if state & Gdk.ModifierType.SHIFT_MASK else 10
        d = {Gdk.KEY_Left: (-step, 0), Gdk.KEY_Right: (step, 0), Gdk.KEY_Up: (0, -step), Gdk.KEY_Down: (0, step)}
        if keyval not in d:
            return False
        e = self.eff(self.sel)
        s = self.staged.setdefault(self.sel, {})
        s["x"], s["y"] = e["x"] + d[keyval][0], e["y"] + d[keyval][1]
        self._clean(self.sel)
        self._changed()
        return True


def build(ctx):
    p = DisplaysPage(ctx)
    p.page._displays = p
    return p.page


def refresh(widget):
    p = widget._displays
    if not p.staged and p.primary is None and p.dialog is None:
        p.refresh()


PAGE = Page(
    id="displays", title="Displays", group="system", order=10, build=build, refresh=refresh, docs="settings.md#displays",
    icon="video-display-symbolic preferences-desktop-display-symbolic preferences-desktop-display-randr-symbolic monitor-symbolic", summary="resolution, scale, arrangement",
    intro="Your monitors: resolution, refresh rate, scale, where each sits and which is primary. Changes here wait "
          "for Apply and then go together, with 15 seconds to keep them: if a screen goes dark, they undo themselves.",
    keywords=["monitors", "screens", "hyprland", "outputs", "multi-monitor"],
    entries=[
        Entry("arrangement", "Arrangement", ["arrange displays", "position", "layout", "left of", "right of", "drag"],
              "Arrangement"),
        Entry("apply", "Apply display changes", ["keep these settings", "revert"], "Apply"),
        Entry("display", "Display", ["which monitor", "choose display"], "The chosen display"),
        Entry("resolution", "Resolution", ["mode", "pixels", "4k", "1080p", "1440p"], "The chosen display"),
        Entry("refresh", "Refresh rate", ["hz", "144hz", "fps", "frame rate"], "The chosen display"),
        Entry("scale", "Scale", ["hidpi", "zoom", "fractional scaling", "text size", "ui size"], "The chosen display"),
        Entry("orientation", "Orientation", ["rotate", "rotation", "portrait", "landscape", "transform"],
              "The chosen display"),
        Entry("enabled", "Turn a display on or off", ["disable monitor", "enable monitor"], "The chosen display"),
        Entry("primary", "Primary display", ["main monitor", "main display"], "The chosen display"),
        Entry("idle", "Displays off when idle", ["dpms", "screen off", "blank"], "More"),
        Entry("setup", "Set up monitors in a terminal", ["bromigos setup monitors"], "More"),
    ])
