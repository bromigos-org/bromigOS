"""What a page gets to build itself with: the house-style page and rows (every one with its
hover hint, an Advanced disclosure saying what it writes, and a key the search can open),
the `bromigos` commands (async, so the window never stalls), changes that apply at once
with Undo, Reset to defaults, and ways to launch things. The `bromigos` commands hold the
rules; a page asks them (`--json`) rather than keeping a copy.

A page's layout, always the same:

    page = ctx.page(reset=…)                    # the header: title, explanation, Reset to defaults
    g = ctx.group(page, "Output", "…")          # a group of rows
    ctx.switch_row(g, "Mute", "…", hint="…", active=…, on_toggle=…, key="mute",
                   advanced={"runs": "bromigos mute on|off"})
"""
import json
import os
import shlex
import shutil
import subprocess
import sys

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gio, GLib, Gtk  # noqa: E402

sys.path.insert(0, "/usr/lib/bromigos/lib")


def _home(path):
    h = os.path.expanduser("~")
    return "~" + path[len(h):] if path and path.startswith(h + "/") else path


class PageBox(Gtk.ScrolledWindow):
    """A page: its header (the title, a short explanation, Reset to defaults), then groups in
    a column, centred, up to 1000 px wide, scrolling."""

    def __init__(self, ctx, page=None, intro=None, reset=None, reset_hint=None):
        super().__init__(hscrollbar_policy=Gtk.PolicyType.NEVER, vexpand=True)
        self.ctx = ctx
        self.add_css_class("bromigos-page")
        self.box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=26)
        for side in ("top", "bottom"):
            getattr(self.box, f"set_margin_{side}")(22)
        for side in ("start", "end"):
            getattr(self.box, f"set_margin_{side}")(24)
        self.clamp = Adw.Clamp(maximum_size=1000, tightening_threshold=760)
        self.clamp.set_child(self.box)
        self.set_child(self.clamp)
        self.page = page
        self.header = None
        self._reset = None
        self.groups = []
        if page is not None:
            self._header(page, intro, reset, reset_hint)

    # -- the header
    def _header(self, page, intro, reset, reset_hint):
        ctx = self.ctx
        head = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        head.add_css_class("bromigos-page-header")
        top = Gtk.Box(spacing=12)
        title = Gtk.Label(label=page.title.upper(), xalign=0, hexpand=True, wrap=True)
        title.add_css_class("bromigos-page-title")
        ctx.hint(title, f"{page.title}: `bromigos settings {page.id}` opens this page")
        top.append(title)
        if page.docs:
            docs = Gtk.Button(icon_name="help-browser-symbolic", valign=Gtk.Align.CENTER)
            docs.add_css_class("flat")
            docs.connect("clicked", lambda *_: ctx.open_docs(page.docs))
            ctx.hint(docs, f"Opens the manual's page about this (F1): {page.docs}")
            top.append(docs)
        self.reset_button = Gtk.Button(label="Reset to defaults", valign=Gtk.Align.CENTER)
        self.reset_button.add_css_class("bromigos-reset")
        self.reset_button.connect("clicked", lambda *_: self._reset_clicked())
        top.append(self.reset_button)
        head.append(top)
        text = intro or page.intro or page.summary
        self.intro = Gtk.Label(label=text, xalign=0, wrap=True)
        self.intro.add_css_class("bromigos-page-intro")
        ctx.hint(self.intro, f"What the {page.title} page is for")
        head.append(self.intro)
        self.box.append(head)
        self.header = head
        self.set_reset(reset, reset_hint)

    def set_intro(self, text):
        if self.header is not None:
            self.intro.set_label(text)

    def set_reset(self, reset, hint=None, what=None, ask=True):
        """reset(): puts this page's settings back to bromigOS's defaults; it may return an
        undo callable. None: the button says nothing here has a default. `ask=False` when
        reset() asks for itself."""
        self._reset = reset
        self._reset_what = what
        self._reset_ask = ask
        if self.header is None:
            return
        self.reset_button.set_sensitive(reset is not None)
        self.ctx.hint(self.reset_button, hint or (
            f"Puts every setting on this page back to bromigOS's defaults (asks first; Undo after)"
            if reset else "Nothing on this page has a bromigOS default: it's this machine's own state"))

    def _reset_clicked(self):
        if not self._reset:
            return
        if not getattr(self, "_reset_ask", True):
            self._do_reset()
            return
        title = self.page.title if self.page else "this page"
        body = self._reset_what or f"Every setting on {title} goes back to bromigOS's default."
        self.ctx.confirm(f"Reset {title}?", body, "Reset", self._do_reset, destructive=True)

    def _do_reset(self):
        r = self._reset()
        if callable(r):
            self.ctx.toast(f"{self.page.title}: back to the defaults", undo=r)

    # -- groups
    def add(self, widget):
        self.box.append(widget)
        self.groups.append(widget)

    def remove_group(self, widget):
        if widget in self.groups:
            self.groups.remove(widget)
        self.box.remove(widget)

    def clear(self):
        """Removes every group (the header stays): for a page that draws itself again."""
        for g in list(self.groups):
            self.remove_group(g)


class Context:
    def __init__(self, app_window):
        self.window = app_window
        self.pending = 0                  # async commands running (the offscreen render waits for them)
        self._commands = None
        self.building = None              # the Page being built (its header comes from it)
        self._restyle = []

    # ------------------------------------------------------------------ widgets
    @staticmethod
    def hint(widget, text):
        """Every hoverable thing says what it is and what it does."""
        if text:
            widget.set_tooltip_text(text)
        return widget

    def page(self, intro=None, reset=None, reset_hint=None):
        """A scrolling page: its header (title, explanation, Reset to defaults), then groups."""
        return PageBox(self, self.building, intro, reset, reset_hint)

    def group(self, page, title, description=None, hint=None, key=None):
        g = Adw.PreferencesGroup(title=GLib.markup_escape_text(title.upper()))
        if description:
            g.set_description(GLib.markup_escape_text(description))
        self.hint(g, hint)
        if key:
            g._bromigos_key = key
        page.add(g)
        return g

    def button(self, label, on_click, hint, primary=False, destructive=False, icon=None):
        b = Gtk.Button(label=label) if label else Gtk.Button(icon_name=icon)
        if label and icon:
            b.set_child(Adw.ButtonContent(label=label, icon_name=icon))
        b.set_valign(Gtk.Align.CENTER)
        if primary:
            b.add_css_class("suggested-action")
        if destructive:
            b.add_css_class("destructive-action")
        b.connect("clicked", lambda *_: on_click())
        return self.hint(b, hint)

    def _add(self, group, row):
        (group.append if isinstance(group, Gtk.ListBox) else group.add)(row)

    def _finish(self, group, row, key, advanced):
        if key:
            row._bromigos_key = key
        self._add(group, row)
        if advanced:
            self.advanced(group, row, advanced)
        return row

    def advanced(self, group, row, info):
        """The row's Advanced disclosure: a small toggle at its end opens a line under it
        saying the file and key it writes and the command it runs. `info`: a dict with any of
        file, key, runs, reads, note (or a list of (label, text))."""
        if isinstance(info, dict):
            lines = []
            if info.get("file"):
                f = _home(info["file"])
                lines.append(("Writes", f + (f" › {info['key']}" if info.get("key") else "")))
            elif info.get("key"):
                lines.append(("Key", info["key"]))
            if info.get("reads"):
                lines.append(("Reads", _home(info["reads"])))
            if info.get("runs"):
                lines.append(("Runs", info["runs"]))
            if info.get("note"):
                lines.append(("Note", info["note"]))
        else:
            lines = list(info)
        if not lines:
            return
        text = "\n".join(f"{k.upper():<7} {v}" for k, v in lines)
        det = Adw.ActionRow(use_markup=False, title=text)
        det.set_title_lines(0)
        det.add_css_class("bromigos-advanced")
        det.set_visible(False)
        copy = Gtk.Button(icon_name="edit-copy-symbolic", valign=Gtk.Align.CENTER)
        copy.add_css_class("flat")
        copy.connect("clicked", lambda *_: self.copy(next((v for k, v in lines if k in ("Runs", "Writes")), text)))
        self.hint(copy, "Copies the command (or the file's path)")
        det.add_suffix(copy)
        self.hint(det, "Advanced: what this setting writes and runs")
        tog = Gtk.ToggleButton(icon_name="view-more-horizontal-symbolic", valign=Gtk.Align.CENTER)
        tog.add_css_class("flat")
        tog.add_css_class("bromigos-adv-toggle")
        self.hint(tog, "Advanced: the file and key this writes, and the command it runs")

        def flip(t):
            det.set_visible(t.get_active())
        tog.connect("toggled", flip)
        if hasattr(row, "add_suffix"):
            row.add_suffix(tog)
        row._bromigos_advanced = tog
        row._bromigos_details = det
        self._add(group, det)
        return det

    def row(self, group, title, subtitle="", hint=None, buttons=(), icon=None, activate=None, key=None,
            advanced=None, control=None):
        """An Adw.ActionRow: `buttons` (label, callback, hint) at its end (wrapping when the
        window is narrow), or a `control` widget; `activate`: a click on the row itself;
        `key`: the setting the search opens here; `advanced`: see advanced()."""
        r = Adw.ActionRow(title=GLib.markup_escape_text(title), subtitle=GLib.markup_escape_text(subtitle or ""))
        r.set_subtitle_lines(3)
        if icon:
            r.add_prefix(Gtk.Image.new_from_icon_name(icon))
        if control is not None:
            control.set_valign(Gtk.Align.CENTER)
            r.add_suffix(control)
        bs = [self.button(label, cb, h) for label, cb, h in buttons]
        if len(bs) > 2:
            wb = Adw.WrapBox(child_spacing=6, line_spacing=6, justify=Adw.JustifyMode.NONE)
            wb.set_halign(Gtk.Align.END)
            for b in bs:
                wb.append(b)
            r.add_suffix(wb)
        else:
            for b in bs:
                r.add_suffix(b)
        if activate:
            r.set_activatable(True)
            r.connect("activated", lambda *_: activate())
            r.add_suffix(Gtk.Image.new_from_icon_name("go-next-symbolic"))
        self.hint(r, hint)
        return self._finish(group, r, key, advanced)

    def switch_row(self, group, title, subtitle="", hint=None, active=False, on_toggle=None, key=None,
                   advanced=None):
        """An Adw.SwitchRow; on_toggle(new) runs when the user flips it (never when the page
        sets it: row.set_quiet(value))."""
        r = Adw.SwitchRow(title=GLib.markup_escape_text(title), subtitle=GLib.markup_escape_text(subtitle or ""))
        r.set_subtitle_lines(3)
        r.set_active(bool(active))
        r._quiet = False

        def changed(row, _p):
            if not row._quiet and on_toggle:
                on_toggle(row.get_active())
        r.connect("notify::active", changed)

        def set_quiet(v):
            r._quiet = True
            try:
                r.set_active(bool(v))
            finally:
                r._quiet = False
        r.set_quiet = set_quiet
        self.hint(r, hint)
        return self._finish(group, r, key, advanced)

    def combo_row(self, group, title, subtitle="", hint=None, options=(), current=None, on_select=None,
                  key=None, advanced=None, enable_search=False):
        """An Adw.ComboRow of (value, label) options; on_select(value) when the user picks
        one (row.set_quiet(value) moves it without calling it; row.set_options(options))."""
        r = Adw.ComboRow(title=GLib.markup_escape_text(title), subtitle=GLib.markup_escape_text(subtitle or ""))
        r.set_use_markup(True)                  # a ComboRow's default is plain text; ours is escaped markup
        r.set_subtitle_lines(3)
        r.set_enable_search(enable_search)
        r._quiet = False
        r._busy = False                       # inside its own selection's handler
        r._values = []
        r._labels = []

        def set_options(opts, cur=None):
            opts = list(opts)
            values, labels = [v for v, _ in opts], [lab for _, lab in opts]
            if r._busy and (values, labels) != (r._values, r._labels):
                # a new model while its own selection is being handled locks AdwComboRow up: after it
                GLib.idle_add(lambda: (set_options(opts, cur), False)[1])
                return
            r._quiet = True
            try:
                if (values, labels) != (r._values, r._labels):
                    r._values, r._labels = values, labels
                    r.set_model(Gtk.StringList.new(labels))
                if cur in r._values:
                    r.set_selected(r._values.index(cur))
                elif r._values:
                    r.set_selected(Gtk.INVALID_LIST_POSITION)
            finally:
                r._quiet = False

        def set_quiet(v):
            r._quiet = True
            try:
                if v in r._values:
                    r.set_selected(r._values.index(v))
            finally:
                r._quiet = False

        def picked(row, _p):
            i = row.get_selected()
            if row._quiet or on_select is None or i == Gtk.INVALID_LIST_POSITION or i >= len(row._values):
                return
            row._busy = True
            try:
                on_select(row._values[i])
            finally:
                row._busy = False
        r.set_options = set_options
        r.set_quiet = set_quiet
        r.value = lambda: (r._values[r.get_selected()] if 0 <= r.get_selected() < len(r._values) else None)
        set_options(list(options), current)
        r.connect("notify::selected", picked)
        self.hint(r, hint)
        return self._finish(group, r, key, advanced)

    def scale_row(self, group, title, subtitle="", hint=None, lo=0, hi=100, step=1, value=0, on_change=None,
                  fmt=None, key=None, advanced=None, debounce=350, width=160, marks=()):
        """A row with a slider and its value; on_change(value) once the slider rests
        (`debounce` ms). row.set_quiet(v) moves it without calling on_change."""
        r = Adw.ActionRow(title=GLib.markup_escape_text(title), subtitle=GLib.markup_escape_text(subtitle or ""))
        r.set_subtitle_lines(3)
        scale = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, lo, hi, step)
        scale.set_draw_value(False)
        scale.set_hexpand(True)
        scale.set_size_request(width, -1)
        scale.set_valign(Gtk.Align.CENTER)
        for m in marks:
            scale.add_mark(m, Gtk.PositionType.BOTTOM, None)
        fmt = fmt or (lambda v: f"{v:g}")
        lab = Gtk.Label(xalign=1)
        lab.add_css_class("bromigos-value")
        self.hint(scale, hint or title)
        self.hint(lab, f"{title}, now")
        box = Gtk.Box(spacing=12)
        box.append(scale)
        box.append(lab)
        r.add_suffix(box)
        r._quiet = False
        r._timer = None

        def moved(s):
            v = round(s.get_value() / step) * step if step else s.get_value()
            lab.set_text(fmt(v))
            if r._quiet or on_change is None:
                return
            if r._timer:
                GLib.source_remove(r._timer)

            def fire():
                r._timer = None
                on_change(v)
                return False
            r._timer = GLib.timeout_add(debounce, fire)
        scale.connect("value-changed", moved)

        def set_quiet(v):
            r._quiet = True
            try:
                adj = scale.get_adjustment()
                if v > adj.get_upper():
                    adj.set_upper(v)
                scale.set_value(v)
                lab.set_text(fmt(v))
            finally:
                r._quiet = False
        r.set_quiet = set_quiet
        r.scale = scale
        r.value_label = lab
        set_quiet(value)
        self.hint(r, hint)
        return self._finish(group, r, key, advanced)

    def entry_row(self, group, title, text="", hint=None, on_apply=None, key=None, advanced=None, placeholder=None):
        """An Adw.EntryRow with an apply button: on_apply(text) when the user presses it or
        Enter."""
        r = Adw.EntryRow(title=GLib.markup_escape_text(title))
        r.set_text(text or "")
        r.set_show_apply_button(True)
        if on_apply:
            r.connect("apply", lambda row: on_apply(row.get_text()))
        if placeholder:
            r.set_input_hints(Gtk.InputHints.NONE)
        r.set_quiet = lambda v: r.set_text(v or "")
        self.hint(r, hint)
        return self._finish(group, r, key, advanced)

    def dropdown(self, options, current=None, on_select=None, hint=None, max_chars=18):
        """A compact Gtk.DropDown of (value, label): the button's label ellipsized at
        `max_chars` (the list shows them whole); on_select(value). dd.set_quiet(value)."""
        values = [v for v, _ in options]
        dd = Gtk.DropDown.new_from_strings([lab for _, lab in options])
        dd.set_valign(Gtk.Align.CENTER)

        def factory(short):
            f = Gtk.SignalListItemFactory()

            def setup(_f, item):
                lab = Gtk.Label(xalign=0)
                if short:
                    lab.set_ellipsize(3)
                    lab.set_max_width_chars(max_chars)
                    lab.set_width_chars(min(max_chars, 8))
                item.set_child(lab)

            def bind(_f, item):
                item.get_child().set_label(item.get_item().get_string())
            f.connect("setup", setup)
            f.connect("bind", bind)
            return f
        dd.set_factory(factory(True))
        dd.set_list_factory(factory(False))
        dd._quiet = False
        if current in values:
            dd.set_selected(values.index(current))

        def picked(d, _p):
            i = d.get_selected()
            if not d._quiet and on_select and 0 <= i < len(values):
                on_select(values[i])
        dd.connect("notify::selected", picked)

        def set_quiet(v):
            dd._quiet = True
            try:
                if v in values:
                    dd.set_selected(values.index(v))
            finally:
                dd._quiet = False
        dd.set_quiet = set_quiet
        return self.hint(dd, hint)

    def toggle_group(self, options, current=None, on_select=None, hint=None):
        """An Adw.ToggleGroup of (value, label, hint) options; on_select(value)."""
        tg = Adw.ToggleGroup(homogeneous=True)
        tg.set_hexpand(True)
        tg._quiet = False
        for value, label, h in options:
            tg.add(Adw.Toggle(name=value, label=label, tooltip=h))
        if current:
            tg.set_active_name(current)

        def picked(t, _p):
            if not t._quiet and on_select and t.get_active_name():
                on_select(t.get_active_name())
        tg.connect("notify::active-name", picked)

        def set_quiet(v):
            tg._quiet = True
            try:
                if v:
                    tg.set_active_name(v)
                else:
                    tg.set_active(Gtk.INVALID_LIST_POSITION)
            finally:
                tg._quiet = False
        tg.set_quiet = set_quiet
        return self.hint(tg, hint)

    def note(self, group, text, level="note", hint=None):
        """A warning or note row: the icon and colour say which."""
        icon = {"warn": "dialog-warning-symbolic", "error": "dialog-error-symbolic"}.get(level, "dialog-information-symbolic")
        r = Adw.ActionRow(title=GLib.markup_escape_text(text))
        r.set_title_lines(6)
        r.add_css_class(f"bromigos-{level}")
        r.add_prefix(Gtk.Image.new_from_icon_name(icon))
        self.hint(r, hint or {"warn": "Worth a look: probably not what you meant (it still applies)",
                              "error": "Something failed"}.get(level, "Good to know"))
        self._add(group, r)
        return r

    def failed(self, group, argv, err):
        """A read that failed: the command and what it said, never an empty group."""
        cmd = " ".join(argv) if isinstance(argv, (list, tuple)) else str(argv)
        return self.note(group, f"`{cmd}` didn't answer: {(err or 'no reply').strip()[:300]}", "error",
                         hint=f"Run `{cmd}` in a terminal to see more")

    def loading(self, group, text="Reading…"):
        """A row with a spinner while a read runs; remove it with group.remove(row)."""
        r = Adw.ActionRow(title=GLib.markup_escape_text(text))
        r.add_prefix(Adw.Spinner())
        r.add_css_class("bromigos-loading")
        self.hint(r, "Waiting for the answer (the window doesn't wait: carry on)")
        self._add(group, r)
        return r

    def placeholder(self, page, title, text, hint=None):
        """A page whose feature hasn't landed yet: what it will hold, and where to go now."""
        g = self.group(page, title, text, hint=hint)
        g.add_css_class("bromigos-placeholder")
        return g

    @staticmethod
    def clear_group(group, rows):
        """Removes `rows` (a list kept by the page; their Advanced lines with them) from
        `group`, and empties the list."""
        for r in rows:
            for w in (r, getattr(r, "_bromigos_details", None)):
                if w is None:
                    continue
                try:
                    group.remove(w)
                except Exception:
                    pass
        rows.clear()

    # ------------------------------------------------------------------ dialogs
    def confirm(self, heading, body, yes, then, destructive=False, no="Cancel"):
        """Asks first; `then()` on yes. Cancel is the default (Enter or Esc never says yes)."""
        d = Adw.AlertDialog(heading=heading, body=body)
        d.add_response("cancel", no)
        d.add_response("yes", yes)
        d.set_response_appearance("yes", Adw.ResponseAppearance.DESTRUCTIVE if destructive
                                  else Adw.ResponseAppearance.SUGGESTED)
        d.set_default_response("cancel")
        d.set_close_response("cancel")
        d.connect("response", lambda _d, r: r == "yes" and then())
        d.present(self.window)
        return d

    def choose_file(self, title, then, save=False, name=None, filters=()):
        """A file chooser; then(path)."""
        fd = Gtk.FileDialog(title=title)
        if name:
            fd.set_initial_name(name)
        if filters:
            store = Gio.ListStore.new(Gtk.FileFilter)
            for label, patterns in filters:
                f = Gtk.FileFilter(name=label)
                for p in patterns:
                    f.add_pattern(p)
                store.append(f)
            fd.set_filters(store)

        def done(d, res):
            try:
                f = d.save_finish(res) if save else d.open_finish(res)
            except GLib.Error:
                return
            if f is not None and f.get_path():
                then(f.get_path())
        (fd.save if save else fd.open)(self.window, None, done)

    # ------------------------------------------------------------------ commands
    def run(self, argv, done=None, stdin=None):
        """Runs argv without blocking; done(ok, stdout, stderr) on the main loop."""
        flags = Gio.SubprocessFlags.STDOUT_PIPE | Gio.SubprocessFlags.STDERR_PIPE
        if stdin is not None:
            flags |= Gio.SubprocessFlags.STDIN_PIPE
        try:
            p = Gio.Subprocess.new(argv, flags)
        except GLib.Error as e:
            if done:
                GLib.idle_add(lambda: (done(False, "", e.message), False)[1])
            return
        self.pending += 1

        def fin(proc, res):
            self.pending -= 1
            try:
                ok, out, err = proc.communicate_utf8_finish(res)
                ok = proc.get_successful()
            except GLib.Error as e:
                ok, out, err = False, "", e.message
            if done:
                done(ok, out or "", err or "")
        p.communicate_utf8_async(stdin, None, fin)

    def json(self, argv, done, stdin=None):
        """Runs argv (a `--json` command) without blocking; done(doc or None, stderr)."""
        def fin(ok, out, err):
            try:
                doc = json.loads(out) if out.strip() else None
            except ValueError:
                doc = None
            done(doc, err.strip() or ("" if ok else "failed"))
        self.run(argv, fin, stdin=stdin)

    @staticmethod
    def json_now(argv, timeout=8):
        """Runs argv and waits (for quick reads only); the document or None."""
        try:
            r = subprocess.run(argv, capture_output=True, text=True, timeout=timeout)
            return json.loads(r.stdout) if r.stdout.strip() else None
        except (OSError, subprocess.SubprocessError, ValueError):
            return None

    def change(self, argv, said, undo=None, done=None, failed=None):
        """A change: runs argv (a `--json` command; `ok: false` or no document is a
        failure), toasts `said` with Undo (`undo`: argv to run, or a callable), and
        done(doc) after. Undo is also Ctrl+Z, for the last change."""
        def fin(doc, err):
            if not doc or doc.get("ok") is False:
                why = (doc or {}).get("error") or err or "failed"
                self.toast(f"Not changed: {why}"[:200], timeout=8)
                if failed:
                    failed(doc, why)
                return
            u = None
            if isinstance(undo, (list, tuple)):
                u = (lambda: self.change(list(undo), "Undone", None, done))
            elif callable(undo):
                u = undo
            text = said(doc) if callable(said) else said
            note = doc.get("note") if isinstance(doc.get("note"), str) else None
            self.toast(text + (f" ({note})" if note and note not in text and len(note) < 90 else ""), undo=u)
            if done:
                done(doc)
        self.json(list(argv), fin)

    def has_command(self, route):
        """Whether `bromigos ROUTE` exists: a built-in or a bromigos-<group>-<name> command."""
        if self._commands is None:
            d = self.json_now(["bromigos", "commands", "--json", "--all"]) or {}
            names = {b.get("name") for b in d.get("builtins", [])}
            names |= {c.get("route", "").removeprefix("bromigos ") for c in d.get("commands", [])}
            self._commands = names
        return route in self._commands

    @staticmethod
    def which(name):
        return shutil.which(name)

    @staticmethod
    def icon(*names):
        """An image of the first of `names` the icon theme has (then a generic one)."""
        return Gtk.Image.new_from_gicon(Gio.ThemedIcon.new_from_names(
            [n for n in names if n] + ["application-x-executable-symbolic"]))

    # ------------------------------------------------------------------ launching
    def launch(self, argv):
        """Starts a program detached, in the desktop session."""
        try:
            import bromigos_hypr as H
            H.spawn(argv)
        except Exception:
            subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                             stderr=subprocess.DEVNULL, start_new_session=True)

    def terminal(self, argv, hold=True):
        """Runs argv in a terminal (a setup's questions, sudo, a pacman transaction):
        `bromigos terminal [--hold]` (the launcher's entries use it too), else the menu's way."""
        helper = shutil.which("bromigos-terminal") or next(
            (p for p in ("/usr/lib/bromigos/bin/bromigos-terminal",) if os.access(p, os.X_OK)), None)
        if helper:
            self.launch([helper] + (["--hold"] if hold else []) + ["--title", " ".join(argv[:3]), "--"] + list(argv))
            return
        try:
            import bromigos_hypr as H
            self.launch(H.terminal_run(argv, hold=hold, title=" ".join(argv[:3])))
        except Exception:
            term = os.environ.get("TERMINAL") or "kitty"
            self.launch([term] + (["--hold"] if hold and term == "kitty" else []) + ["-e"] + list(argv))

    def open_file(self, path):
        """Opens a file in the user's editor (a terminal one in a terminal), else xdg-open."""
        editor = os.environ.get("VISUAL") or os.environ.get("EDITOR")
        if editor and shutil.which(shlex.split(editor)[0]):
            self.terminal(shlex.split(editor) + [path], hold=False)
        else:
            self.launch(["xdg-open", path])

    def open_url(self, url):
        self.launch(["xdg-open", url])

    def open_docs(self, page):
        """The manual's page ("settings.md#sound"): the copy installed here, else the one
        published next to this machine's packages, else the source on GitHub."""
        self.open_url(self.window.manual_url(page))

    def copy(self, text):
        self.window.get_clipboard().set(text)
        self.toast("Copied")

    # ------------------------------------------------------------------ the window
    def toast(self, text, undo=None, timeout=5):
        """A toast at the bottom; with `undo`, an Undo button that calls it (and Ctrl+Z)."""
        self.window.toast(text, undo, timeout)

    def open_page(self, page_id, key=None):
        self.window.open_page(page_id, key)

    def on_restyle(self, callback):
        """callback(colors) whenever the theme changes (for colours a page sets itself)."""
        self._restyle.append(callback)

    def restyled(self, colors):
        for cb in list(self._restyle):
            try:
                cb(colors)
            except Exception:
                pass

    @property
    def colors(self):
        return self.window.colors
