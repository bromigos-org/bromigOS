"""Idle & lock: when the screensaver starts, the screen locks, the displays go off and the
machine suspends; presets; stay awake for a while; the screensaver, now.

Everything goes through `bromigos idle … --json` (the rules live in the core): a change
applies at once (idle.toml written, hypridle's config rendered, hypridle restarted) and
leaves a toast with Undo (`bromigos idle undo`). docs/idle.md."""
import time

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, GLib, Gtk  # noqa: E402

from bromigos_settings import Entry, Page  # noqa: E402

IDLE_TOML = "~/.config/bromigos/idle.toml"

TIMERS = [
    # key, title, what it does, slider range (minutes), hover hint
    ("screensaver", "Screensaver", "The live scene, full screen. Any key or mouse movement ends it.", (1, 60),
     "Starts the live layer's screensaver after this long without input. It never locks anything by itself."),
    ("lock", "Lock", "The lock screen. Your password opens it again.", (1, 120),
     "Locks the screen after this long without input. Off: nothing locks on idle (SUPER+L still locks)."),
    ("displays", "Displays off", "The screens go dark. Any input wakes them.", (1, 120),
     "Turns the displays off (DPMS) after this long without input."),
    ("suspend", "Suspend", "The machine sleeps. Off by default.", (5, 240),
     "Suspends the machine (systemctl suspend) after this long without input."),
]
PRESETS = [
    ("default", "Default", "bromigOS's timers: the screensaver at 8 min, the lock at 10, displays off at 15, no suspend"),
    ("screensaver-only", "Screensaver only", "The screensaver at its time and nothing else: nothing locks, the displays stay on, no suspend. Any input ends it."),
    ("presentation", "Presentation", "Nothing idles: no screensaver, no lock, the displays stay on, no suspend; the creatures stay awake."),
]
PRESET_NAMES = {k: t for k, t, _ in PRESETS}


def _min(n):
    n = int(n)
    if n >= 60 and n % 60 == 0:
        return f"{n // 60} h"
    if n > 60:
        return f"{n // 60} h {n % 60:02d}"
    return f"{n} min"


class IdlePage:
    def __init__(self, ctx):
        self.ctx = ctx
        self.doc = {}
        self.syncing = False
        self.pending = {}                     # key -> GLib source id (a slider's debounce)
        self.timer_widgets = {}
        self.note_rows = []
        self.page = ctx.page()
        self.page.set_reset(self.reset_defaults, what="bromigOS's timers: the screensaver at 8 min, the lock at 10, "
                                                     "the displays off at 15, no suspend, lock before sleep on. "
                                                     "Undo puts yours back.")
        self._now()
        self._presets()
        self._awake()
        self._timers()
        self._try()
        self._files()
        doc = ctx.json_now(["bromigos", "idle", "status", "--json"])
        if doc:
            self.sync(doc)
        else:
            self.summary.set_text("bromigos idle didn't answer: is bromigos-core installed?")
        GLib.timeout_add_seconds(20, self._tick)

    # ------------------------------------------------------------------ building
    def _now(self):
        g = self.ctx.group(self.page, "Now", hint="What the desktop does when you leave it, as set now")
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        box.set_margin_bottom(6)
        self.summary = Gtk.Label(xalign=0, wrap=True)
        self.summary.add_css_class("bromigos-summary")
        self.ctx.hint(self.summary, "The policy in plain words; it changes as you change the settings below")
        self.state = Gtk.Label(xalign=0, wrap=True)
        self.state.add_css_class("bromigos-state")
        self.ctx.hint(self.state, "The preset this matches, stay awake, and hypridle (the idle daemon that runs it)")
        box.append(self.summary)
        box.append(self.state)
        # the warnings and notes, under the summary (rows of their own list: a group's rows
        # would sit above it)
        self.notes = Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE)
        self.notes.add_css_class("boxed-list")
        self.notes.set_margin_top(8)
        self.notes.set_visible(False)
        self.ctx.hint(self.notes, "What's worth knowing about these settings: warnings (likely not what you meant; "
                                  "they still apply) and notes")
        box.append(self.notes)
        g.add(box)

    def _presets(self):
        g = self.ctx.group(self.page, "Presets", "One click for the usual setups; you can still change any timer after.")
        tg = Adw.ToggleGroup(homogeneous=True)
        tg.set_hexpand(True)
        for key, label, hint in PRESETS:
            t = Adw.Toggle(name=key, label=label, tooltip=hint)
            tg.add(t)
        tg.connect("notify::active-name", self._preset_chosen)
        self.ctx.hint(tg, "Default, Screensaver only (nothing locks) or Presentation (nothing idles). "
                          "None lit: your own timers")
        self.preset_group = tg
        tg._bromigos_key = "presets"
        g.add(tg)
        row = Adw.ActionRow(title="Custom", subtitle="Your own timers")
        row.set_subtitle_lines(0)
        self.ctx.hint(row, "What the preset in force does")
        self.preset_row = row
        box = Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE)
        box.add_css_class("boxed-list")
        box.set_margin_top(8)
        box.append(row)
        g.add(box)

    def _awake(self):
        g = self.ctx.group(self.page, "Stay awake",
                           "For a while, nothing idles: no screensaver, lock, displays off or suspend. "
                           "Then everything is as it was.")
        row = Adw.ActionRow(title="Stay awake", subtitle="Off")
        self.awake_row = row
        for label, arg, hint in [("1 h", "1h", "Stay awake for an hour"), ("2 h", "2h", "Stay awake for two hours"),
                                 ("Until off", "until-off", "Stay awake until you turn it off here, on the bar, or with `bromigos idle off`")]:
            row.add_suffix(self.ctx.button(label, (lambda a=arg, l=label: self.stay(a, l)), hint))
        self.awake_stop = self.ctx.button("Stop", lambda: self.stay("off", None),
                                          "Stop staying awake: the timers run again", destructive=True)
        row.add_suffix(self.awake_stop)
        self.ctx.hint(row, "A logind idle inhibitor (systemd-inhibit), which hypridle honours. "
                           "The bar's eye turns into a cup while it's on; click it there to toggle.")
        row._bromigos_key = "stay-awake"
        g.add(row)
        self.ctx.advanced(g, row, {"runs": "bromigos idle stay-awake 1h|2h|until-off|off",
                                   "note": "systemd-inhibit --what=idle (logind)"})
        self.others_row = None
        self.awake_group = g

    def _timer_row(self, g, key, title, what, rng, hint, unit="min"):
        row = Adw.ActionRow(title=title, subtitle=what)
        row.set_subtitle_lines(0)
        lo, hi = rng
        scale = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, lo, hi, 1)
        scale.set_draw_value(False)
        scale.set_size_request(250, -1)
        scale.set_valign(Gtk.Align.CENTER)
        scale.set_round_digits(0)
        self.ctx.hint(scale, f"Drag to set when ({lo}–{hi} {unit}; any time up to 24 h with `bromigos idle set`). "
                             "It applies as you let go.")
        value = Gtk.Label(xalign=1)
        value.add_css_class("bromigos-value")
        self.ctx.hint(value, f"When {title.lower()} happens, after the last input")
        sw = Gtk.Switch(valign=Gtk.Align.CENTER)
        self.ctx.hint(sw, f"{title}: on or off")
        box = Gtk.Box(spacing=14)
        box.append(scale)
        box.append(value)
        box.append(sw)
        row.add_suffix(box)
        self.ctx.hint(row, hint)
        scale.connect("value-changed", lambda s, k=key, u=unit: self._slid(k, s, u))
        sw.connect("notify::active", lambda s, _p, k=key, t=title: self._switched(k, s, t))
        row._bromigos_key = key
        g.add(row)
        field = "seconds" if unit == "s" else "minutes"
        self.ctx.advanced(g, row, {"file": IDLE_TOML, "key": f"[{key}] enabled, {field}",
                                   "runs": f"bromigos idle set {key}.{field} N  ·  {key}.enabled on|off"})
        self.timer_widgets[key] = (row, scale, value, sw)

    def _timers(self):
        g = self.ctx.group(self.page, "Timers",
                           "Each counts from the last key or mouse movement, in this order: screensaver, lock, "
                           "displays off, suspend.")
        for key, title, what, rng, hint in TIMERS:
            self._timer_row(g, key, title, what, rng, hint)
        sleep = Adw.SwitchRow(title="Lock before sleep",
                              subtitle="Lock whenever the machine goes to sleep: a suspend, the lid, the power menu.")
        self.ctx.hint(sleep, "On: waking the machine always shows the lock screen first. On by default.")
        sleep.connect("notify::active", self._sleep_switched)
        self.sleep_row = sleep
        sleep._bromigos_key = "lock-before-sleep"
        g.add(sleep)
        self.ctx.advanced(g, sleep, {"file": IDLE_TOML, "key": "lock_before_sleep",
                                     "runs": "bromigos idle set lock-before-sleep on|off"})
        g2 = self.ctx.group(self.page, "The world", "The theme's keeper and creatures notice when you're away.")
        self._timer_row(g2, "activity", "Creatures doze",
                        "The keeper and creatures doze without input, and wake on the next.", (10, 600),
                        "The worlds' activity idle: the keeper and creatures doze after this long without input "
                        "(the live layer's activity reading).", unit="s")

    def _try(self):
        g = self.ctx.group(self.page, "Try it")
        self.ctx.row(g, "The screensaver", "Opens it now, full screen. Any key or mouse movement ends it.",
                     hint="Runs the live layer's screensaver now, a second after you click (so the click doesn't end it)",
                     key="try", advanced={"runs": "bromigos-live ctl screensaver open"},
                     buttons=[("Try the screensaver now", self.try_saver,
                               "Opens the screensaver now; any key or mouse movement ends it")])

    def _files(self):
        g = self.ctx.group(self.page, "Files", "What these settings are made of; Settings and `bromigos idle` write them.")
        self.file_rows = {}
        for key, title, hint in [
            ("file", "Your settings", "~/.config/bromigos/idle.toml: what you changed here, over bromigOS's defaults. Yours; updates never touch it."),
            ("hook", "Your hypridle.conf", "~/.config/hypr/hypridle.conf: sources the rendered policy, then any listeners of your own"),
            ("rendered", "Rendered for hypridle", "~/.local/state/bromigos/idle/hypridle.conf: written again on every change; don't edit it"),
        ]:
            r = self.ctx.row(g, title, "", hint=hint,
                             buttons=[("Open", (lambda k=key: self.open(k)), f"Open {title.lower()} in your editor")])
            self.file_rows[key] = r

    # ------------------------------------------------------------------ state
    def sync(self, d):
        """Shows a status document (`bromigos idle status --json`)."""
        self.doc = d
        self.syncing = True
        try:
            p = d.get("policy") or {}
            for key, (row, scale, value, sw) in self.timer_widgets.items():
                t = p.get(key) or {}
                n = t.get("minutes", t.get("seconds", 0))
                adj = scale.get_adjustment()
                if n > adj.get_upper():
                    adj.set_upper(n)
                scale.set_value(n)
                on = bool(t.get("enabled"))
                sw.set_active(on)
                scale.set_sensitive(on)
                value.set_text(_min(n) if key != "activity" else f"{n} s")
                (value.remove_css_class if on else value.add_css_class)("off")
            self.sleep_row.set_active(bool(p.get("lock_before_sleep")))
            preset = d.get("preset")
            if preset:
                self.preset_group.set_active_name(preset)
                self.preset_row.set_title(PRESET_NAMES.get(preset, preset))
                self.preset_row.set_subtitle(dict((k, h) for k, _, h in PRESETS).get(preset, ""))
            else:
                self.preset_group.set_active(Gtk.INVALID_LIST_POSITION)
                self.preset_row.set_title("Custom")
                self.preset_row.set_subtitle("Your own timers: no preset matches them")
        finally:
            self.syncing = False
        self._show_state(d)

    def _show_state(self, d):
        aw = d.get("stay_awake") or {}
        summary = d.get("summary", "")
        if aw.get("on"):
            if aw.get("remaining_s") is not None:
                until = time.strftime("%H:%M", time.localtime(aw.get("until") or time.time()))
                left = max(1, (int(aw["remaining_s"]) + 59) // 60)
                awake = f"Staying awake until {until} ({_min(left)} left)"
            else:
                awake = "Staying awake until you turn it off"
            self.summary.set_text(f"{awake}. Then: {summary}")
            self.awake_row.set_subtitle(awake)
            self.awake_row.add_css_class("bromigos-awake")
        else:
            self.summary.set_text(summary)
            self.awake_row.set_subtitle("Off: the timers below run")
            self.awake_row.remove_css_class("bromigos-awake")
        self.awake_stop.set_sensitive(bool(aw.get("on")))
        hd = d.get("hypridle") or {}
        preset = PRESET_NAMES.get(d.get("preset"), "custom")
        self.state.set_text(f"Preset: {preset} · hypridle: {'running' if hd.get('running') else 'not running'}"
                            + (" · stay awake: on" if aw.get("on") else ""))
        # warnings and notes, under the summary
        for r in self.note_rows:
            self.notes.remove(r)
        self.note_rows = []
        for w in d.get("warnings") or []:
            r = self.ctx.note(self.notes, w.get("text", ""), w.get("level", "note"))
            if w.get("text", "").startswith("hypridle isn't running"):
                r.add_suffix(self.ctx.button("Start it", self.start_hypridle,
                                             "Starts hypridle in this session now (bromigos idle start --detach)"))
            self.note_rows.append(r)
        self.notes.set_visible(bool(self.note_rows))
        if self.others_row is not None:
            self.awake_group.remove(self.others_row)
            self.others_row = None
        others = d.get("inhibitors") or []
        if others:
            text = "Also keeping it awake: " + ", ".join(f"{i['who']} ({i['why']})" for i in others)
            self.others_row = self.ctx.note(self.awake_group, text, "note",
                                            hint="Other programs holding an idle inhibitor (a video, a download); "
                                                 "nothing idles while they do")
        for key, path in [("file", d.get("file")), ("hook", None), ("rendered", d.get("rendered"))]:
            r = self.file_rows.get(key)
            if r is None:
                continue
            if key == "hook":
                r.set_subtitle({"rendered": "sources the rendered policy",
                                "packaged": "still sources the packaged policy: `bromigos idle hook` moves it",
                                "other": "your own: doesn't source bromigOS's policy",
                                "missing": "none: `bromigos idle hook` makes it"}.get(d.get("hook"), ""))
            elif key == "file":
                r.set_subtitle((path or "") + ("" if d.get("exists") else " (none yet: the defaults apply)"))
            else:
                r.set_subtitle(path or "")

    def refresh(self):
        self.ctx.json(["bromigos", "idle", "status", "--json"], lambda doc, _e: doc and self.sync(doc))

    def _tick(self):
        if (self.doc.get("stay_awake") or {}).get("on"):
            self.refresh()
        return True

    # ------------------------------------------------------------------ changes
    def apply(self, args, said, undo=True):
        def done(doc, err):
            if not doc or doc.get("ok") is False:
                self.ctx.toast(f"Not changed: {(doc or {}).get('error') or err or 'bromigos idle failed'}")
                self.refresh()
                return
            self.sync(doc)
            failed = [r for r in (doc.get("applied") or {}).get("restarts") or [] if not r.get("ok")]
            if failed:
                self.ctx.toast(f"{said}, but hypridle didn't restart: {failed[0].get('detail') or ''}", timeout=8)
            else:
                self.ctx.toast(said, self.undo if undo else None)
        self.ctx.json(["bromigos", "idle", *args, "--json"], done)

    def undo(self):
        self.apply(["undo"], "Undone", undo=False)

    def reset_defaults(self):
        self.apply(["preset", "default"], "Idle & lock: bromigOS's timers")
        return None

    def _switched(self, key, sw, title):
        if self.syncing:
            return
        on = sw.get_active()
        self.timer_widgets[key][1].set_sensitive(on)
        if key == "activity":
            self.apply(["set", "activity.enabled", "on" if on else "off"], f"Creatures doze: {'on' if on else 'off'}")
        else:
            word = "on" if on else "off"
            self.apply(["set", f"{key}.enabled", word], f"{title}{' on idle' if key == 'lock' else ''}: {word}")

    def _slid(self, key, scale, unit):
        n = int(round(scale.get_value()))
        value = self.timer_widgets[key][2]
        value.set_text(_min(n) if unit == "min" else f"{n} s")
        if self.syncing:
            return
        if key in self.pending:
            GLib.source_remove(self.pending.pop(key))

        def commit():
            self.pending.pop(key, None)
            field = "seconds" if unit == "s" else "minutes"
            title = dict((k, t) for k, t, *_ in TIMERS).get(key, "Creatures doze")
            self.apply(["set", f"{key}.{field}", str(n)],
                       f"{title} at {_min(n) if unit == 'min' else f'{n} s'}")
            return False
        self.pending[key] = GLib.timeout_add(450, commit)

    def _sleep_switched(self, row, _p):
        if self.syncing:
            return
        on = row.get_active()
        self.apply(["set", "lock-before-sleep", "on" if on else "off"], f"Lock before sleep: {'on' if on else 'off'}")

    def _preset_chosen(self, tg, _p):
        if self.syncing:
            return
        name = tg.get_active_name()
        if name:
            self.apply(["preset", name], f"Preset: {PRESET_NAMES.get(name, name)}")

    def stay(self, arg, label):
        def done(doc, err):
            if not doc or doc.get("ok") is False:
                self.ctx.toast(f"Stay awake: {(doc or {}).get('error') or err or 'failed'}")
                return
            self.sync(doc)
            if arg == "off":
                self.ctx.toast("Stay awake: off")
            else:
                self.ctx.toast(f"Staying awake {'until you turn it off' if arg == 'until-off' else 'for ' + label}",
                               lambda: self.stay("off", None))
        self.ctx.json(["bromigos", "idle", "stay-awake", arg, "--json"], done)

    def start_hypridle(self):
        def done(ok, out, err):
            self.ctx.toast("hypridle: " + ((out or err).strip() or ("started" if ok else "didn't start")))
            self.refresh()
        self.ctx.run(["bromigos", "idle", "start", "--detach"], done)

    def try_saver(self):
        def go():
            def done(ok, out, err):
                said = (out or err).strip()
                if not ok or "disabled" in said:
                    self.ctx.toast("The screensaver didn't open: " + (said or "is the live layer running? (bromigos live)"))
            self.ctx.run(["bromigos-live", "ctl", "screensaver", "open"], done)
            return False
        GLib.timeout_add(900, go)

    def open(self, key):
        path = {"file": self.doc.get("file"), "rendered": self.doc.get("rendered")}.get(key)
        if key == "hook":
            import os
            path = os.path.join(os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config"), "hypr/hypridle.conf")
        if key == "file" and path and not self.doc.get("exists"):
            self.ctx.toast("No idle.toml yet: change any setting here and it's made")
            return
        if path:
            self.ctx.open_file(path)


def build(ctx):
    p = IdlePage(ctx)
    p.page._idle = p
    return p.page


def refresh(widget):
    widget._idle.refresh()


PAGE = Page(id="idle", title="Idle & lock", icon="system-lock-screen-symbolic", order=10, group="desktop",
            summary="screensaver, lock, displays, sleep", docs="idle.md",
            intro="What happens when you leave the desktop: when the screensaver starts, the screen locks, the "
                  "displays go off and the machine sleeps. Each change applies at once (hypridle restarts).",
            entries=[Entry("presets", "Idle presets", ["presentation", "screensaver only", "default timers"], "Presets"),
                     Entry("stay-awake", "Stay awake", ["caffeine", "keep awake", "inhibit", "don't sleep"],
                           "Stay awake"),
                     Entry("screensaver", "Screensaver after", ["screen saver", "idle time"], "Timers"),
                     Entry("lock", "Lock the screen after", ["auto lock", "lock timeout", "password"], "Timers"),
                     Entry("displays", "Turn the displays off after", ["dpms", "screen off", "blank"], "Timers"),
                     Entry("suspend", "Suspend after", ["sleep", "auto suspend", "standby"], "Timers"),
                     Entry("lock-before-sleep", "Lock before sleep", ["lock on suspend", "lock on lid"], "Timers"),
                     Entry("activity", "Creatures doze after", ["world idle", "keeper"], "The world"),
                     Entry("try", "Try the screensaver", ["preview screensaver", "test screensaver"], "Try it")],
            keywords=["screensaver", "lock", "dpms", "displays", "suspend", "sleep", "stay awake", "caffeine",
                      "hypridle", "timeout", "presentation"],
            build=build, refresh=refresh)
