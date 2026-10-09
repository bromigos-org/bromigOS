"""Notifications: do not disturb, where they appear, how long they stay, and a rule for each
app (docs/settings.md, "Notifications").

Everything goes through `bromigos notifications … --json` (dunst: dunstctl, and a drop-in
Settings keeps in ~/.config/dunst/dunstrc.d/80-settings.conf, under your 99-mine.conf): a
change applies at once and toasts Undo."""
from gi.repository import GLib, Gtk

from bromigos_settings import Entry, Page

CMD = ["bromigos", "notifications"]
DROPIN = "~/.config/dunst/dunstrc.d/80-settings.conf"
SPOTS = [("top-left", "↖", "Top left"), ("top-center", "↑", "Top, in the middle"), ("top-right", "↗", "Top right"),
         ("bottom-left", "↙", "Bottom left"), ("bottom-center", "↓", "Bottom, in the middle"),
         ("bottom-right", "↘", "Bottom right")]
URGENCY = [("low", "Low urgency", "Background news: a download done, a song changed"),
           ("normal", "Normal", "Most notifications"),
           ("critical", "Critical", "Something needs you: a battery about to die, a failed job")]
RULES = [("show", "Show"), ("quiet", "Quiet"), ("hide", "Hide")]


def _secs(v):
    return "until dismissed" if int(v) == 0 else f"{int(v)} s"


class NotificationsPage:
    def __init__(self, ctx):
        self.ctx = ctx
        self.doc = None
        self.app_sig = None
        self.page = ctx.page()
        self.page.set_reset(self.reset, what="Notifications appear top right, 16 px from the edge, and stay 5 s "
                                             "(low), 8 s (normal) or until dismissed (critical); every app's rule "
                                             "goes. Settings' file is removed; your 99-mine.conf stays.")
        self._build()
        self.refresh()
        GLib.timeout_add_seconds(5, self._tick)

    # ------------------------------------------------------------------ building
    def _build(self):
        ctx = self.ctx
        g = ctx.group(self.page, "Do not disturb", "Nothing shows while it's on: notifications wait, and show "
                                                   "when it's off again.")
        self.problem_group = g
        self.problem = None
        self.dnd = ctx.switch_row(g, "Do not disturb", "Off", key="dnd", on_toggle=self._dnd,
                                  hint="Holds every notification back until you turn it off (dunstctl set-paused)",
                                  advanced={"runs": "bromigos notifications dnd on|off", "note": "dunstctl set-paused"})

        g = ctx.group(self.page, "Where they appear", "Pick a corner of the screen (the one with the mouse).",
                      key="position")
        screen = Gtk.Grid(column_homogeneous=True, row_homogeneous=True, column_spacing=4, row_spacing=46)
        screen.set_halign(Gtk.Align.CENTER)
        self._frame(screen)
        screen.set_margin_top(6)
        screen.set_margin_bottom(6)
        ctx.hint(screen, "Your screen: click where notifications should appear")
        self.spots = {}
        first = None
        for i, (pos, arrow, name) in enumerate(SPOTS):
            b = Gtk.ToggleButton(label=f"{arrow}  {name.split(',')[0]}")
            b.set_size_request(118, -1)
            if first is None:
                first = b
            else:
                b.set_group(first)
            ctx.hint(b, f"Notifications appear {name.lower()}")
            b._quiet = False
            b.connect("toggled", lambda btn, p=pos: (not btn._quiet and btn.get_active()) and self._position(p))
            screen.attach(b, i % 3, i // 3, 1, 1)
            self.spots[pos] = b
        g.add(screen)
        rows = Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE)
        rows.add_css_class("boxed-list")
        rows.set_margin_top(8)
        g.add(rows)
        self.offset = ctx.scale_row(
            rows, "Gap from the edge", "How far from the screen's edges, in pixels", lo=0, hi=120, step=2, value=16,
            fmt=lambda v: f"{int(v)} px", key="offset", on_change=self._offset,
            hint="Drag: the space between a notification and the screen's edges (applies as you let go)",
            advanced={"file": DROPIN, "key": "[global] offset", "runs": "bromigos notifications offset X Y"})

        g = ctx.group(self.page, "How long they stay", "Each urgency for its own time; 0 keeps it until you "
                                                       "dismiss it (a click, or the key).")
        self.timeouts = {}
        for u, title, what in URGENCY:
            self.timeouts[u] = ctx.scale_row(
                g, title, what, lo=0, hi=60, step=1, value=0, fmt=_secs, key=f"timeout-{u}",
                on_change=lambda v, u=u: self._timeout(u, v),
                hint=f"Drag: how long a {title.lower()} notification stays (0: until dismissed)",
                advanced={"file": DROPIN, "key": f"[urgency_{u}] timeout",
                          "runs": f"bromigos notifications timeout {u} SECONDS"})
            self.timeouts[u].value_label.set_width_chars(15)

        self.apps_group = ctx.group(self.page, "Apps", "Every app that has notified you lately, and its rule: Show, "
                                                       "Quiet (low urgency: shorter, no alert colour) or Hide (straight "
                                                       "to the history).", key="apps")
        self.app_rows = []

        g = ctx.group(self.page, "Try it")
        ctx.row(g, "Send a test", "A notification now, where and for as long as these settings say", key="test",
                hint="Sends a sample notification (notify-send)",
                buttons=[("Send", self._test, "Sends a test notification now")],
                advanced={"runs": "bromigos notifications test"})
        self.history = ctx.row(g, "History", "", key="history",
                               hint="Past notifications dunst keeps (`dunstctl history-pop` brings the last one back)",
                               buttons=[("Clear…", self._clear, "Forgets every past notification (asks first)")],
                               advanced={"runs": "bromigos notifications clear-history"})

    def _frame(self, w):
        """The little screen in the theme's colours, its picked corner lit (again on a theme switch)."""
        from gi.repository import Gdk
        w.add_css_class("bromigos-spots")
        prov = Gtk.CssProvider()
        Gtk.StyleContext.add_provider_for_display(Gdk.Display.get_default(), prov, Gtk.STYLE_PROVIDER_PRIORITY_USER + 1)

        def paint(c):
            prov.load_from_string(
                f".bromigos-spots {{ border: 1px solid {c.get('dim', '#159b09')}; padding: 10px; "
                f"background-color: {c.get('void', '#000500')}; }}\n"
                f".bromigos-spots button:checked {{ background-color: {c.get('selection', '#003b00')}; "
                f"color: {c.get('primary', '#39ff14')}; border-color: {c.get('primary', '#39ff14')}; "
                f"box-shadow: inset 0 -2px {c.get('primary', '#39ff14')}; }}")
        paint(self.ctx.colors)
        self.ctx.on_restyle(paint)

    def _apps(self, d):
        ctx = self.ctx
        sig = tuple((a["name"], a["rule"]) for a in d["apps"])
        if sig == self.app_sig:
            return
        self.app_sig = sig
        ctx.clear_group(self.apps_group, self.app_rows)
        if not d["apps"]:
            self.app_rows.append(ctx.row(self.apps_group, "No app has notified you yet",
                                         "An app shows here after its first notification",
                                         hint="dunst's history is empty"))
            return
        for a in d["apps"][:30]:
            sub = (f"{a['count']} in the history" if a["count"] else "nothing in the history now") + \
                  (f" · last: {a['last_summary']}" if a["last_summary"] else "")
            dd = ctx.dropdown(RULES, a["rule"], on_select=lambda r, n=a["name"], old=a["rule"]: self._rule(n, r, old),
                              hint=f"What {a['name']}'s notifications do: Show, Quiet (low urgency) or Hide "
                                   "(the history keeps them)")
            r = ctx.row(self.apps_group, a["name"], sub, hint=f"{a['name']}: its notifications' rule", control=dd,
                        advanced={"file": DROPIN, "key": f"appname = \"{a['name']}\"",
                                  "runs": f"bromigos notifications app \"{a['name']}\" show|quiet|hide"})
            self.app_rows.append(r)

    # ------------------------------------------------------------------ state
    def refresh(self):
        self.ctx.json(CMD + ["--json"], self._got)

    def _tick(self):
        if self.page.get_mapped():
            self.refresh()
        return True

    def _got(self, doc, err):
        if not doc or doc.get("ok") is False:
            if self.problem is None:
                self.problem = self.ctx.failed(self.problem_group, CMD + ["--json"], (doc or {}).get("error") or err)
            return
        self.sync(doc)

    def sync(self, d):
        self.doc = d
        if self.problem is not None:
            self.problem_group.remove(self.problem)
            self.problem = None
        if not d.get("running"):
            self.problem = self.ctx.note(self.problem_group, "dunst isn't running: these settings wait for it "
                                         "(it starts at login)", "warn",
                                         hint="Start it with `dunst &`, or log in again")
        c = d.get("counts") or {}
        self.dnd.set_quiet(bool(d["dnd"]))
        self.dnd.set_subtitle(("On: " if d["dnd"] else "Off: ") +
                              (f"{c['waiting']} waiting" if c.get("waiting") else
                               "nothing waiting" if d["dnd"] else "notifications show as they come"))
        for pos, b in self.spots.items():
            b._quiet = True
            b.set_active(pos == d["position"])
            b._quiet = False
        self.offset.set_quiet((d.get("offset") or [16, 16])[0])
        for u, row in self.timeouts.items():
            row.set_quiet(min(int(d["timeout"][u]), 60))
            if d["timeout"][u] > 60:
                row.value_label.set_text(_secs(d["timeout"][u]))
        self.history.set_subtitle(f"{c.get('history', 0) or 0} kept" if d.get("running") else "dunst isn't running")
        self._apps(d)

    # ------------------------------------------------------------------ changes
    def _change(self, args, said, undo_args=None):
        self.ctx.change(CMD + args + ["--json"], said, undo=(CMD + undo_args + ["--json"]) if undo_args else None,
                        done=self.sync, failed=lambda *_: self.refresh())

    def _dnd(self, on):
        self._change(["dnd", "on" if on else "off"], f"Do not disturb: {'on' if on else 'off'}",
                     ["dnd", "off" if on else "on"])

    def _position(self, pos):
        old = (self.doc or {}).get("position")
        if pos == old:
            return
        self._change(["position", pos], lambda d: d.get("said"), ["position", old] if old else None)

    def _offset(self, v):
        old = (self.doc or {}).get("offset") or [16, 16]
        self._change(["offset", str(int(v)), str(int(v))], f"{int(v)} px from the edge",
                     ["offset", str(old[0]), str(old[1])])

    def _timeout(self, u, v):
        old = ((self.doc or {}).get("timeout") or {}).get(u)
        self._change(["timeout", u, str(int(v))], lambda d: d.get("said"),
                     ["timeout", u, str(old)] if old is not None else None)

    def _rule(self, name, rule, old):
        if rule == old:
            return
        self._change(["app", name, rule], lambda d: d.get("said"), ["app", name, old])

    def _test(self):
        self._change(["test"], "Sent a test notification")

    def _clear(self):
        self.ctx.confirm("Clear the history?", "Every past notification is forgotten; there's no undo.", "Clear",
                         lambda: self._change(["clear-history"], "The history is cleared"), destructive=True)

    def reset(self):
        self._change(["reset"], "Notifications: back to bromigOS's defaults")
        return None


def build(ctx):
    p = NotificationsPage(ctx)
    p.page._notifications = p
    return p.page


def refresh(widget):
    widget._notifications.refresh()


PAGE = Page(
    id="notifications", title="Notifications", group="desktop", order=26, build=build, refresh=refresh,
    docs="settings.md#notifications", icon="preferences-system-notifications-symbolic notifications-symbolic",
    summary="do not disturb, where, how long",
    intro="Do not disturb, where notifications appear, how long they stay, and what each app may do. dunst "
          "shows them; a change applies at once.",
    keywords=["dunst", "alerts", "banners", "popups", "toasts"],
    entries=[
        Entry("dnd", "Do not disturb", ["dnd", "quiet", "pause notifications", "silence"], "Do not disturb"),
        Entry("position", "Where notifications appear", ["corner", "position", "placement", "origin"],
              "Where they appear"),
        Entry("offset", "Gap from the edge", ["offset", "margin"], "Where they appear"),
        Entry("timeout-low", "How long low-urgency ones stay", ["timeout", "duration"], "How long they stay"),
        Entry("timeout-normal", "How long notifications stay", ["timeout", "duration", "seconds"],
              "How long they stay"),
        Entry("timeout-critical", "How long critical ones stay", ["timeout", "urgent", "until dismissed"],
              "How long they stay"),
        Entry("apps", "Notifications per app", ["app rules", "mute an app", "hide an app", "per-app"], "Apps"),
        Entry("test", "Send a test notification", ["try", "sample"], "Try it"),
        Entry("history", "Clear the notification history", ["history", "past notifications"], "Try it"),
    ])
