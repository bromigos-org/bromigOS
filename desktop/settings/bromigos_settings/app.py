"""The Settings window: a sidebar of the registry's pages in their groups, a search across
every setting, the page shown beside it, toasts over both. One window per session (a
second `bromigos settings` raises it, on the page it names). `--render` draws a page to a
PNG instead of keeping a window: used by the tests, in a headless compositor.

Keys: type anywhere (or Ctrl+F) to search, Down into the results, Enter opens the first;
Esc clears the search; Ctrl+PgUp / Ctrl+PgDn the previous / next page; Ctrl+1…6 the first
page of each group; Ctrl+Z undoes the last change; F1 the page's part of the manual;
Ctrl+W closes."""
import json
import os
import sys

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gdk, Gio, GLib, Gtk  # noqa: E402

from . import APP_ID, style  # noqa: E402
from .context import Context  # noqa: E402
from .registry import GROUPS, discover  # noqa: E402
from .search import Index  # noqa: E402

GROUP_TITLE = {g: t for g, t, _ in GROUPS}


def _debug(*a):
    if os.environ.get("BROMIGOS_SETTINGS_DEBUG"):
        print("settings:", *a, file=sys.stderr, flush=True)
GROUP_WHAT = {g: w for g, _, w in GROUPS}


class Window(Adw.ApplicationWindow):
    def __init__(self, app, pages, problems, size=None):
        super().__init__(application=app, title="Settings")
        self.set_size_request(360, 420)
        self._fit(size)
        self.pages = {p.id: p for p in pages}
        self.order = [p.id for p in pages]
        self.index = Index(pages)
        self.built = {}
        self.ctx = Context(self)
        self.colors = {}
        self.undo_last = None
        self._channel_base = None
        self._css = Gtk.CssProvider()
        Gtk.StyleContext.add_provider_for_display(Gdk.Display.get_default(), self._css,
                                                  Gtk.STYLE_PROVIDER_PRIORITY_USER)
        self._theme_seen = None
        self.restyle()
        GLib.timeout_add_seconds(2, self._theme_tick)
        self._watch_theme()

        self.toasts = Adw.ToastOverlay()
        self.split = Adw.NavigationSplitView()
        self.split.set_min_sidebar_width(240)
        self.split.set_max_sidebar_width(300)
        self.toasts.set_child(self.split)
        self.set_content(self.toasts)

        # narrow: the sidebar and the page one at a time (a back button between them)
        bp = Adw.Breakpoint.new(Adw.BreakpointCondition.parse("max-width: 720sp"))
        bp.add_setter(self.split, "collapsed", True)
        bp.connect("apply", lambda *_: self.add_css_class("narrow"))
        bp.connect("unapply", lambda *_: self.remove_css_class("narrow"))
        self.add_breakpoint(bp)

        self.split.set_sidebar(Adw.NavigationPage(title="Settings", child=self._sidebar(pages, problems)))

        # the page
        self.content_view = Adw.ToolbarView()
        ch = Adw.HeaderBar()
        tbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, valign=Gtk.Align.CENTER)
        self.content_title = Gtk.Label()
        self.content_title.add_css_class("title")
        self.content_subtitle = Gtk.Label()
        self.content_subtitle.add_css_class("subtitle")
        tbox.append(self.content_title)
        tbox.append(self.content_subtitle)
        ch.set_title_widget(tbox)
        self.content_view.add_top_bar(ch)
        self.stack = Gtk.Stack(transition_type=Gtk.StackTransitionType.CROSSFADE, transition_duration=120)
        self.content_view.set_content(self.stack)
        self.content = Adw.NavigationPage(title="Settings", child=self.content_view)
        self.split.set_content(self.content)
        self.current = None
        self._keys()

    def _fit(self, size):
        """85% of the monitor, at most 1280×860 (a 1366×768 screen gets a window that fits
        under the bar); the size given when rendering."""
        if size:
            self.set_default_size(*size)
            return
        w, h = 1120, 780
        try:
            mons = Gdk.Display.get_default().get_monitors()
            if mons.get_n_items():
                g = mons.get_item(0).get_geometry()
                w, h = min(1280, int(g.width * 0.85)), min(860, int(g.height * 0.85))
        except Exception:
            pass
        self.set_default_size(max(w, 360), max(h, 420))

    # ------------------------------------------------------------------ the sidebar
    def _sidebar(self, pages, problems):
        side = Adw.ToolbarView()
        sh = Adw.HeaderBar(show_end_title_buttons=False, show_start_title_buttons=False)
        title = Gtk.Label(label="SETTINGS")
        title.add_css_class("title")
        title.set_tooltip_text("bromigOS Settings (SUPER+,): every page also opens with `bromigos settings PAGE`")
        sh.set_title_widget(title)
        side.add_top_bar(sh)
        self.search = Gtk.SearchEntry(placeholder_text="Search settings")
        for s in ("start", "end"):
            getattr(self.search, f"set_margin_{s}")(8)
        self.search.set_margin_top(6)
        self.search.set_margin_bottom(4)
        self.search.set_tooltip_text("Finds any setting by its name or what it's for (type anywhere, or Ctrl+F); "
                                     "Down to the results, Enter opens the first, Esc clears")
        self.search.set_key_capture_widget(self)
        self.search.connect("search-changed", lambda *_: self._searched())
        self.search.connect("activate", lambda *_: self._open_result(0))
        self.search.connect("stop-search", lambda *_: self.search.set_text(""))
        down = Gtk.EventControllerKey()
        down.set_propagation_phase(Gtk.PropagationPhase.CAPTURE)
        down.connect("key-pressed", self._search_key)
        self.search.add_controller(down)

        self.list = Gtk.ListBox()
        self.list.add_css_class("navigation-sidebar")
        self.list.set_header_func(self._group_header)
        self.rows = {}
        for p in pages:
            self.list.append(self._side_row(p))
        self.list.connect("row-selected", self._selected)
        self.results = Gtk.ListBox()
        self.results.add_css_class("navigation-sidebar")
        self.results.add_css_class("bromigos-results")
        self.results.connect("row-activated", lambda _lb, row: self.open_page(row.page_id, row.key))
        self.noresults = Gtk.Label(label="Nothing matches", xalign=0)
        self.noresults.add_css_class("dim-label")
        self.noresults.set_margin_start(16)
        self.noresults.set_margin_top(8)
        self.noresults.set_tooltip_text("No setting or page has those words; try fewer, or another word for it")
        self.side_stack = Gtk.Stack()
        s1 = Gtk.ScrolledWindow(vexpand=True, hscrollbar_policy=Gtk.PolicyType.NEVER)
        s1.set_child(self.list)
        s2 = Gtk.ScrolledWindow(vexpand=True, hscrollbar_policy=Gtk.PolicyType.NEVER)
        rb = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        rb.append(self.results)
        rb.append(self.noresults)
        s2.set_child(rb)
        self.side_stack.add_named(s1, "pages")
        self.side_stack.add_named(s2, "results")
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        box.append(self.search)
        box.append(self.side_stack)
        if problems:
            lab = Gtk.Label(label=f"{len(problems)} page file(s) skipped", xalign=0)
            lab.add_css_class("dim-label")
            lab.set_margin_start(14)
            lab.set_margin_bottom(8)
            lab.set_tooltip_text("\n".join(f"{f}: {m}" for f, m in problems))
            box.append(lab)
        side.set_content(box)
        return side

    def _side_row(self, p):
        row = Gtk.ListBoxRow()
        row.page_id = p.id
        h = Gtk.Box(spacing=12)
        # the first of the icon's names the icon theme has (Breeze and Adwaita name some differently)
        names = p.icon if isinstance(p.icon, (list, tuple)) else p.icon.split()
        h.append(Gtk.Image.new_from_gicon(Gio.ThemedIcon.new_from_names(list(names) + ["preferences-system-symbolic"])))
        v = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        t = Gtk.Label(label=p.title, xalign=0)
        t.add_css_class("page-title")
        v.append(t)
        if p.summary:
            s = Gtk.Label(label=p.summary, xalign=0, ellipsize=3)
            s.add_css_class("page-summary")
            v.append(s)
        h.append(v)
        row.set_child(h)
        row.set_tooltip_text(f"{p.title}: {p.summary}" if p.summary else p.title)
        self.rows[p.id] = row
        return row

    def _group_header(self, row, before):
        g = self.pages[row.page_id].group_id
        if before is not None and self.pages[before.page_id].group_id == g:
            row.set_header(None)
            return
        lab = Gtk.Label(label=GROUP_TITLE.get(g, g).upper(), xalign=0)
        lab.add_css_class("bromigos-group-title")
        n = [x for x, _, _ in GROUPS].index(g) + 1 if g in GROUP_TITLE else 0
        lab.set_tooltip_text(f"{GROUP_TITLE.get(g, g)}: {GROUP_WHAT.get(g, '')}" + (f" (Ctrl+{n})" if n else ""))
        row.set_header(lab)

    def _selected(self, _lb, row):
        if row is not None:
            self.show_page(row.page_id)

    # ------------------------------------------------------------------ search
    def focus_search(self):
        self.search.grab_focus()
        self.search.select_region(0, -1)

    def _searched(self):
        q = self.search.get_text().strip()
        if not q:
            self.side_stack.set_visible_child_name("pages")
            return
        # typing anywhere lands here (key capture); the keys that follow, Enter and Esc, too
        if not self.search.has_focus() and not (self.search.get_focus_child()):
            self.search.grab_focus()
            self.search.set_position(-1)
        self.side_stack.set_visible_child_name("results")
        while (r := self.results.get_first_child()) is not None:
            self.results.remove(r)
        found = self.index.search(q)
        for res in found:
            row = Gtk.ListBoxRow()
            row.page_id, row.key = res.page, res.key or None
            v = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
            t = Gtk.Label(label=res.title, xalign=0, ellipsize=3)
            t.add_css_class("page-title")
            w = Gtk.Label(label=res.where, xalign=0, ellipsize=3)
            w.add_css_class("page-summary")
            v.append(t)
            v.append(w)
            row.set_child(v)
            row.set_tooltip_text(f"{res.title}, in {res.where}: Enter or a click opens it there")
            self.results.append(row)
        self.noresults.set_visible(not found)

    def _search_key(self, _c, keyval, _code, _state):
        if keyval in (Gdk.KEY_Return, Gdk.KEY_KP_Enter, Gdk.KEY_ISO_Enter) and self.search.get_text().strip():
            self._searched()                      # the results as typed so far, not as of the delay
            self._open_result(0)
            return True
        if keyval == Gdk.KEY_Escape and self.search.get_text():
            self.search.set_text("")
            return True
        if keyval in (Gdk.KEY_Down, Gdk.KEY_KP_Down):
            target = self.results if self.side_stack.get_visible_child_name() == "results" else self.list
            row = target.get_row_at_index(0)
            if row is not None:
                row.grab_focus()
                return True
        return False

    def _open_result(self, i):
        _debug("activate", self.side_stack.get_visible_child_name(), self.search.get_text())
        if self.side_stack.get_visible_child_name() != "results":
            return
        row = self.results.get_row_at_index(i)
        if row is not None:
            self.open_page(row.page_id, row.key)

    # ------------------------------------------------------------------ pages
    def _build(self, p):
        self.ctx.building = p
        try:
            w = p.build(self.ctx)
            if w is None:
                raise TypeError("build() returned nothing")
        except Exception as e:      # one page's bug never takes the window down
            import traceback
            traceback.print_exc()
            w = self._broken(p, e)
        for s in p.sections:
            before = list(getattr(w, "groups", []))
            try:
                s.build(self.ctx, w)
            except Exception as e:
                import traceback
                traceback.print_exc()
                g = self.ctx.group(w, s.title, "This part failed to build.")
                self.ctx.note(g, f"{type(e).__name__}: {e}", level="error", hint=s.source)
            new = [g for g in getattr(w, "groups", []) if g not in before]
            if new:
                new[0]._bromigos_key = f"section:{s.id}"
        self.ctx.building = None
        return w

    def show_page(self, pid):
        p = self.pages.get(pid)
        if p is None:
            return
        if pid not in self.built:
            w = self._build(p)
            self.built[pid] = w
            self.stack.add_named(w, pid)
        elif p.refresh:
            try:
                p.refresh(self.built[pid])
            except Exception:
                import traceback
                traceback.print_exc()
        self.stack.set_visible_child_name(pid)
        self.current = pid
        self.content_title.set_label(p.title.upper())
        self.content_subtitle.set_label(GROUP_TITLE.get(p.group_id, ""))
        self.content_title.set_tooltip_text(f"{p.title}: `bromigos settings {p.id}` opens this page")
        self.content.set_title(p.title)
        self.split.set_show_content(True)

    def _broken(self, p, e):
        self.ctx.building = p
        page = self.ctx.page()
        g = self.ctx.group(page, p.title, "This page failed to build.")
        self.ctx.note(g, f"{type(e).__name__}: {e}", level="error", hint=p.source)
        return page

    def open_page(self, pid, key=None):
        if pid not in self.pages:
            pid = self.order[0] if self.order else None
            key = None
        if pid is None:
            return
        row = self.rows.get(pid)
        if row is not None and self.list.get_selected_row() is not row:
            self.list.select_row(row)          # shows it (row-selected)
        else:
            self.show_page(pid)
        if key:
            GLib.timeout_add(80, self._focus_key, pid, key, 0)

    def find_key(self, pid, key):
        """The row (or group) on page `pid` built with this search key."""
        w = self.built.get(pid)
        stack = [w] if w is not None else []
        while stack:
            x = stack.pop()
            if getattr(x, "_bromigos_key", None) == key:
                return x
            c = x.get_last_child()
            while c is not None:
                stack.append(c)
                c = c.get_prev_sibling()
        return None

    def _focus_key(self, pid, key, tries):
        w = self.find_key(pid, key)
        _debug("focus", pid, key, type(w).__name__, w.get_mapped() if w else None, w.get_focusable() if w else None)
        if w is None:
            if tries < 40 and self.ctx.pending:           # its rows come with an answer still running
                GLib.timeout_add(150, self._focus_key, pid, key, tries + 1)
            return False
        w.grab_focus()
        w.add_css_class("bromigos-found")
        GLib.timeout_add(2600, lambda: (w.remove_css_class("bromigos-found"), False)[1])
        return False

    def step_page(self, d):
        if not self.order:
            return
        i = self.order.index(self.current) if self.current in self.order else 0
        self.open_page(self.order[(i + d) % len(self.order)])

    def open_group(self, n):
        if n < len(GROUPS):
            g = GROUPS[n][0]
            pid = next((p for p in self.order if self.pages[p].group_id == g), None)
            if pid:
                self.open_page(pid)

    # ------------------------------------------------------------------ keys
    def _keys(self):
        sc = Gtk.ShortcutController()
        sc.set_scope(Gtk.ShortcutScope.MANAGED)

        def add(trigger, fn):
            sc.add_shortcut(Gtk.Shortcut.new(Gtk.ShortcutTrigger.parse_string(trigger),
                                             Gtk.CallbackAction.new(lambda *_: (fn(), True)[1])))
        add("<Control>f", self.focus_search)
        add("<Control>Page_Down", lambda: self.step_page(1))
        add("<Control>Page_Up", lambda: self.step_page(-1))
        for n in range(len(GROUPS)):          # Alt+digits are Hyprland's workspaces in bromigOS
            add(f"<Control>{n + 1}", lambda n=n: self.open_group(n))
        add("<Control>z", self.undo)
        add("F1", self._docs)
        add("<Control>w", self.close)
        self.add_controller(sc)

    def _docs(self):
        p = self.pages.get(self.current)
        self.ctx.open_docs(p.docs if p and p.docs else "settings.md")

    def manual_url(self, page=None):
        """The manual at `page` (bromigos_cli.manual_url): the copy installed here, else the
        one published beside this machine's packages, else the source on GitHub."""
        import bromigos_cli as C
        if C.manual_dir() is None and self._channel_base is None:
            d = self.ctx.json_now(["bromigos", "channel", "--json"], timeout=4) or {}
            self._channel_base = (d.get("channel") or {}).get("base") or ""
        return C.manual_url(self._channel_base, page)

    # ------------------------------------------------------------------ toasts, undo, theme
    def toast(self, text, undo=None, timeout=5):
        t = Adw.Toast(title=GLib.markup_escape_text(text), timeout=timeout)
        t.set_priority(Adw.ToastPriority.HIGH)
        if undo:
            t.set_button_label("Undo")

            def run(*_):
                if self.undo_last is undo:
                    self.undo_last = None
                undo()
            t.connect("button-clicked", run)
            self.undo_last = undo
        self.toasts.add_toast(t)

    def undo(self):
        u, self.undo_last = self.undo_last, None
        if u:
            u()
        else:
            self.toast("Nothing to undo")

    def restyle(self):
        c, mode, _name = style.colors()
        self.colors = c
        Adw.StyleManager.get_default().set_color_scheme(
            Adw.ColorScheme.FORCE_LIGHT if mode == "light" else Adw.ColorScheme.FORCE_DARK)
        self._css.load_from_string(style.css(c))
        self._theme_seen = style.version()
        if hasattr(self, "ctx"):
            self.ctx.restyled(c)

    def _theme_tick(self):
        if style.version() != self._theme_seen:
            self.restyle()
        return True

    def _watch_theme(self):
        """A theme switch rewrites palette.json: restyle at once (the 2 s poll is the fallback)."""
        path = style.palette_path()
        if not path:
            return
        try:
            self._mon = Gio.File.new_for_path(os.path.dirname(path)).monitor_directory(Gio.FileMonitorFlags.NONE, None)
            self._mon.connect("changed", lambda *_: GLib.timeout_add(150, lambda: (self._theme_tick(), False)[1]))
        except GLib.Error:
            self._mon = None


class App(Adw.Application):
    def __init__(self, render=None):
        flags = Gio.ApplicationFlags.HANDLES_COMMAND_LINE
        if render:
            flags |= Gio.ApplicationFlags.NON_UNIQUE
        super().__init__(application_id=APP_ID, flags=flags)
        self.render = render            # dict(out, page, key, search, size, audit) or None
        self.win = None

    def _window(self):
        if self.win is None:
            pages, problems = discover()
            for f, m in problems:
                print(f"bromigos-settings: skipped {f}: {m}", file=sys.stderr)
            self.win = Window(self, pages, problems, size=(self.render or {}).get("size"))
        return self.win

    def do_command_line(self, cmdline):
        args = [a for a in cmdline.get_arguments()[1:] if not a.startswith("-")]
        win = self._window()
        r = self.render or {}
        page = r.get("page") or (args[0] if args else None)
        key = r.get("key")
        if page and "#" in page:
            page, key = page.split("#", 1)
        win.present()
        win.open_page(page or (win.order[0] if win.order else ""), key)
        if r.get("search"):
            win.search.set_text(r["search"])
        if self.render:
            GLib.timeout_add(400, self._snap_when_ready, 0)
        return 0

    def _snap_when_ready(self, waited):
        win = self.win
        # the page's commands answered (or 10 s went by), then a frame to lay them out
        if win.ctx.pending and waited < 10000:
            GLib.timeout_add(200, self._snap_when_ready, waited + 200)
            return False
        if self.render.get("advanced"):
            self._open_advanced()
        GLib.timeout_add(600, self._snap)
        return False

    def _open_advanced(self):
        w = self.win.built.get(self.win.current)
        for x in _walk(w):
            if getattr(x, "_bromigos_advanced", None) is not None:
                x._bromigos_advanced.set_active(True)

    def _snap(self):
        win = self.win
        out = self.render["out"]
        if self.render.get("audit"):
            print(json.dumps(audit(win, win.current)))
        w, h = win.get_width(), win.get_height()
        ok = False
        if out and out != "-":
            paintable = Gtk.WidgetPaintable.new(win)
            snap = Gtk.Snapshot()
            paintable.snapshot(snap, w, h)
            node = snap.to_node()
            if node is not None:
                tex = win.get_renderer().render_texture(node, None)
                ok = tex.save_to_png(out)
            print(f"{'rendered' if ok else 'FAILED'} {out} ({w}x{h})", file=sys.stderr if self.render.get("audit") else sys.stdout)
        self.quit()
        return False


def _walk(w):
    stack = [w] if w is not None else []
    while stack:
        x = stack.pop()
        yield x
        c = x.get_first_child()
        while c is not None:
            stack.append(c)
            c = c.get_next_sibling()


INTERACTIVE = (Gtk.Button, Gtk.Switch, Gtk.Scale, Gtk.DropDown, Gtk.Entry, Gtk.Text, Gtk.CheckButton,
               Adw.ToggleGroup, Gtk.SpinButton)


def audit(win, pid):
    """What a page is missing: interactive widgets with no hover hint (theirs or a parent's
    up to the row), and the page's search entries no row was built for."""
    p = win.pages.get(pid)
    w = win.built.get(pid)
    missing, seen_keys = [], set()
    for x in _walk(w):
        k = getattr(x, "_bromigos_key", None)
        if k:
            seen_keys.add(k)
        if not isinstance(x, INTERACTIVE) or not x.get_visible() or not x.get_mapped():
            continue
        y, hinted = x, False
        while y is not None and y is not w:
            if y.get_tooltip_text() or y.get_tooltip_markup():
                hinted = True
                break
            if isinstance(y, (Adw.PreferencesRow, Gtk.ListBoxRow)) and y is not x:
                break
            y = y.get_parent()
        if not hinted:
            label = x.get_label() if hasattr(x, "get_label") and isinstance(x, Gtk.Button) else ""
            row = x
            while row is not None and not isinstance(row, Adw.PreferencesRow):
                row = row.get_parent()
            missing.append({"widget": type(x).__name__, "label": label or "",
                            "row": row.get_title() if row is not None else ""})
    keys = [e.key for e in (p.entries if p else [])] + [e.key for s in (p.sections if p else []) for e in s.entries]
    # rows wider than the page can show (they'd be cut off on a small screen)
    too_wide = []
    room = (min(w.get_width(), win.get_width()) - 2 * 24) if w is not None else 0
    if w is not None and w.measure(Gtk.Orientation.HORIZONTAL, -1)[0] > win.get_width():
        too_wide.append({"widget": "page", "title": pid, "min": w.measure(Gtk.Orientation.HORIZONTAL, -1)[0],
                         "room": win.get_width()})
    for x in _walk(w):
        if isinstance(x, (Adw.PreferencesRow, Adw.PreferencesGroup)) and x.get_mapped():
            mn = x.measure(Gtk.Orientation.HORIZONTAL, -1)[0]
            if room and mn > room:
                too_wide.append({"widget": type(x).__name__, "title": x.get_title() if hasattr(x, "get_title") else "",
                                 "min": mn, "room": room})
    return {"page": pid, "unhinted": missing, "unbuilt_keys": [k for k in keys if k not in seen_keys],
            "too_wide": too_wide}


def main(argv):
    render = None
    if "--render" in argv or "--audit" in argv:
        def opt(name, default=None):
            return argv[argv.index(name) + 1] if name in argv else default
        size = opt("--size", "1120x780")
        w, h = (int(x) for x in size.split("x"))
        render = {"out": opt("--render", "-"), "page": opt("--page"), "key": opt("--key"),
                  "search": opt("--search"), "size": (w, h), "advanced": "--advanced" in argv,
                  "audit": "--audit" in argv}
        argv = [argv[0]]
    return App(render).run(argv)
