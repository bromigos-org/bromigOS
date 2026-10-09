"""Date & time: network time, the time zone, and the bar's clock (docs/settings.md,
"Date and time").

Everything goes through `bromigos clock … --json`: the time zone and network time are
systemd's timedated (timedatectl; it may ask for your password), the bar's clock is a file
Settings keeps that your bar's config includes first. A change applies at once and toasts
Undo."""
from gi.repository import GLib, Gtk

from bromigos_settings import Entry, Page

CMD = ["bromigos", "clock"]
SETTINGS = "~/.config/bromigos/waybar/settings.jsonc"


class DateTimePage:
    def __init__(self, ctx):
        self.ctx = ctx
        self.doc = None
        self.zones_loaded = False
        self.page = ctx.page()
        self.page.set_reset(self.reset, what="The bar's clock goes back to bromigOS's: 24-hour, with seconds, "
                                             "no date. The time zone and network time stay as they are (they're "
                                             "this machine's).")
        self._build()
        self.refresh()
        self.ctx.json(CMD + ["zones", "--json"], self._zones)
        GLib.timeout_add_seconds(1, self._tick)

    def _build(self):
        ctx = self.ctx
        g = ctx.group(self.page, "The time")
        self.time_group = g
        self.problem = None
        self.now = ctx.row(g, "Now", "", key="now", hint="The time now, in this machine's time zone")
        self.now_label = Gtk.Label(xalign=1)
        self.now_label.add_css_class("bromigos-value")
        ctx.hint(self.now_label, "The time now, as the bar shows it")
        self.now.add_suffix(self.now_label)
        self.ntp = ctx.switch_row(g, "Set the time automatically", "", key="ntp", on_toggle=self._ntp,
                                  hint="Keeps the clock in step with time servers on the network (systemd-timesyncd)",
                                  advanced={"runs": "bromigos clock ntp on|off", "note": "timedatectl set-ntp"})
        self.zone = ctx.combo_row(g, "Time zone", "", options=[], key="timezone", enable_search=True,
                                  on_select=self._zone,
                                  hint="Where you are: the clock, the worlds' day and night and the logs follow it. "
                                       "Type to search",
                                  advanced={"file": "/etc/localtime", "runs": "bromigos clock timezone ZONE",
                                            "note": "timedatectl set-timezone (it may ask for your password)"})

        g = ctx.group(self.page, "The bar's clock", "What the clock at the end of the bar shows (a click on it "
                                                     "shows the whole date).")
        self.bar_group = g
        self.hook_row = None
        self.preview = ctx.row(g, "The bar shows", "", key="preview", hint="The clock as the bar will show it now")
        self.preview_label = Gtk.Label(xalign=1)
        self.preview_label.add_css_class("bromigos-value")
        ctx.hint(self.preview_label, "What the bar's clock reads")
        self.preview.add_suffix(self.preview_label)
        adv = {"file": SETTINGS, "key": "clock.format"}
        self.h24 = ctx.switch_row(g, "24-hour clock", "13:05, or 1:05 PM when off", key="clock24",
                                  on_toggle=lambda on: self._bar("format", "24" if on else "12", "12" if on else "24"),
                                  hint="The bar's clock in 24 hours (on) or 12 with AM and PM (off)",
                                  advanced=dict(adv, runs="bromigos clock format 24|12"))
        self.secs = ctx.switch_row(g, "Seconds", "The seconds ticking on the bar", key="seconds",
                                   on_toggle=lambda on: self._bar("seconds", "on" if on else "off", "off" if on else "on"),
                                   hint="Shows the seconds on the bar's clock",
                                   advanced=dict(adv, runs="bromigos clock seconds on|off"))
        self.date = ctx.switch_row(g, "The date", "The day and date beside the time", key="date",
                                   on_toggle=lambda on: self._bar("date", "on" if on else "off", "off" if on else "on"),
                                   hint="Shows the day and the date before the time on the bar",
                                   advanced=dict(adv, runs="bromigos clock date on|off"))

    # ------------------------------------------------------------------ state
    def refresh(self):
        self.ctx.json(CMD + ["--json"], self._got)

    def _got(self, doc, err):
        if not doc or doc.get("ok") is False:
            if self.problem is None:
                self.problem = self.ctx.failed(self.time_group, CMD + ["--json"], (doc or {}).get("error") or err)
            return
        self.sync(doc)

    def _zones(self, doc, err):
        if not doc or doc.get("ok") is False:
            return
        cur = (self.doc or {}).get("timezone")
        self.zone.set_options([(z, z.replace("_", " ")) for z in doc["zones"]], cur)
        self.zones_loaded = True

    def sync(self, d):
        self.doc = d
        if self.problem is not None:
            self.time_group.remove(self.problem)
            self.problem = None
        if not d.get("available", True):
            self.problem = self.ctx.note(self.time_group, f"timedated didn't answer: {d.get('error', '')}", "warn",
                                         hint="systemd's time service (timedatectl show)")
        self.ntp.set_quiet(bool(d.get("ntp")))
        self.ntp.set_sensitive(bool(d.get("can_ntp", True)))
        self.ntp.set_subtitle("In step with the network's time" if d.get("synced") else
                              ("Not in step yet" if d.get("ntp") else "Off: the clock keeps its own time"))
        if not self.zones_loaded and d.get("timezone"):
            self.zone.set_options([(d["timezone"], d["timezone"].replace("_", " "))], d["timezone"])
        else:
            self.zone.set_quiet(d.get("timezone"))
        self.zone.set_subtitle(d.get("timezone", ""))
        b = d["bar"]
        self.h24.set_quiet(b["format"] == "24")
        self.secs.set_quiet(b["seconds"])
        self.date.set_quiet(b["date"])
        if self.hook_row is not None:
            self.bar_group.remove(self.hook_row)
            self.hook_row = None
        if not b["hooked"]:
            why = {"missing": "your bar's config doesn't include Settings' clock yet",
                   "after": "your bar's config includes Settings' clock after bromigOS's, so bromigOS's wins",
                   "no-include": "your bar's config has no include list",
                   "no-config": "you have no ~/.config/waybar/config"}.get(b["hook"], "")
            self.hook_row = self.ctx.note(self.bar_group, f"These don't reach the bar: {why}", "warn",
                                          hint=f"Add {b['line']} first in the include list of {b['config']}")
            if b["hook"] in ("missing", "after"):
                self.hook_row.add_suffix(self.ctx.button("Add it", self._hook,
                                                         "Adds Settings' clock first among your bar's includes "
                                                         "(bromigos clock hook); nothing else in the file changes"))
        self._tick()

    def _tick(self):
        d = self.doc
        if d is None:
            return True
        try:
            tz = GLib.TimeZone.new_identifier(d.get("timezone") or "UTC") or GLib.TimeZone.new_local()
        except Exception:
            tz = GLib.TimeZone.new_local()
        now = GLib.DateTime.new_now(tz)
        b = d["bar"]
        t = ("%I:%M" if b["format"] == "12" else "%H:%M") + (":%S" if b["seconds"] else "") + \
            (" %p" if b["format"] == "12" else "")
        self.preview_label.set_text(now.format(("%a %d %b  " if b["date"] else "") + t))
        self.now_label.set_text(now.format("%A %d %B %Y  " + ("%I:%M:%S %p" if b["format"] == "12" else "%H:%M:%S")))
        self.now.set_subtitle(GLib.markup_escape_text(f"{d.get('timezone', '')} · {now.format('%Z (UTC%:z)')}"))
        return True

    # ------------------------------------------------------------------ changes
    def _change(self, args, said, undo_args=None):
        self.ctx.change(CMD + args + ["--json"], said, undo=(CMD + undo_args + ["--json"]) if undo_args else None,
                        done=self.sync, failed=lambda *_: self.refresh())

    def _ntp(self, on):
        self._change(["ntp", "on" if on else "off"], f"Network time: {'on' if on else 'off'}",
                     ["ntp", "off" if on else "on"])

    def _zone(self, z):
        old = (self.doc or {}).get("timezone")
        if z == old:
            return
        self._change(["timezone", z], f"Time zone: {z}", ["timezone", old] if old else None)

    def _bar(self, what, value, undo):
        self._change([what, value], lambda d: d.get("said"), [what, undo])

    def _hook(self):
        self._change(["hook"], lambda d: d.get("said"))

    def reset(self):
        b = (self.doc or {}).get("bar") or {}
        old = [("format", b.get("format", "24")), ("seconds", "on" if b.get("seconds", True) else "off"),
               ("date", "on" if b.get("date") else "off")]

        def undo(i=0):
            if i < len(old):
                self.ctx.change(CMD + [old[i][0], old[i][1], "--json"], "Undone",
                                done=lambda d: (self.sync(d), undo(i + 1)))
        self.ctx.change(CMD + ["reset", "--json"], lambda d: d.get("said"), undo=undo, done=self.sync)
        return None


def build(ctx):
    p = DateTimePage(ctx)
    p.page._datetime = p
    return p.page


def refresh(widget):
    widget._datetime.refresh()


PAGE = Page(
    id="datetime", title="Date & time", group="system", order=80, build=build, refresh=refresh,
    docs="settings.md#date-and-time", icon="preferences-system-time-symbolic x-office-calendar-symbolic clock-symbolic",
    summary="time zone, network time, the clock",
    intro="The time zone, the time from the network, and how the bar's clock reads.",
    keywords=["clock", "date", "time", "timezone", "ntp", "calendar"],
    entries=[
        Entry("now", "The time now", ["current time", "clock"], "The time"),
        Entry("ntp", "Set the time automatically", ["ntp", "network time", "sync", "automatic time"], "The time"),
        Entry("timezone", "Time zone", ["timezone", "tz", "zone", "location"], "The time"),
        Entry("preview", "The bar's clock", ["bar clock", "waybar clock"], "The bar's clock"),
        Entry("clock24", "24-hour clock", ["24h", "12h", "am pm", "time format"], "The bar's clock"),
        Entry("seconds", "Seconds on the clock", ["show seconds"], "The bar's clock"),
        Entry("date", "The date on the bar", ["show date", "day"], "The bar's clock"),
    ])
