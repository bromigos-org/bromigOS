"""A widget's settings form (docs/widgets.md, "A widget's settings"), drawn from the fields
its panel declares (widgets/widget_settings.py): a text, list, number, switch or choice
row for each value, and a sign-in section for each service it uses: each of the service's
accounts, which of them the widget shows, and Add another account… Values go through
`bromigos panels set|unset NAME KEY … --json` (each change toasts Undo); sign-ins go
through lib/bromigos_account.py, which keeps tokens in the keyring and never shows them.

    WidgetForm(ctx, entry, done=None).present()     entry: a `bromigos panels gallery` widget

category_buttons() is the galleries' category buttons, shared by Settings › Widgets and
Customize's Widgets tab.
"""
import os
import threading
import time

from gi.repository import Adw, GLib, Gtk

CMD = ["bromigos", "panels"]


def category_buttons(cats):
    """The category buttons, [(id, label, hint)] with All first, from the "categories" that
    `bromigos panels gallery` gives (widgets/gallery.py's categories(), which edit mode's
    tray uses itself): Customize's Widgets tab and Settings › Widgets draw these."""
    out = [("all", "All", "Every widget")]
    for c in cats or []:
        if isinstance(c, dict) and c.get("id"):
            title = str(c.get("title") or c["id"])
            out.append((c["id"], str(c.get("label") or title.split(" ")[0]),
                        str(c.get("hint") or f"The {title.lower()} widgets")))
    return out


def home(path):
    """A path as a person reads it: ~/… under the home folder."""
    h = os.path.expanduser("~")
    return "~" + path[len(h):] if path and h != "/" and (path == h or path.startswith(h + "/")) else path


def short_url(url):
    """A link to show (the button opens the whole one): no scheme, no www., no query."""
    u = (url or "").split("?", 1)[0].split("#", 1)[0]
    for p in ("https://", "http://"):
        u = u.removeprefix(p)
    return u.removeprefix("www.").rstrip("/")


def field_row(f, text, on_apply, example=None):
    """A labelled text box, down the row: the field's name, its hint under it, then the box
    (an example in it while it's empty) with its Save button. Enter saves too."""
    box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4, margin_top=10, margin_bottom=10,
                  margin_start=12, margin_end=12)
    t = Gtk.Label(label=f["label"], xalign=0)
    box.append(t)
    if f.get("hint"):
        h = Gtk.Label(label=f["hint"], xalign=0, wrap=True)
        h.add_css_class("dim-label")
        h.add_css_class("caption")
        box.append(h)
    line = Gtk.Box(spacing=6, margin_top=4)
    e = Gtk.Entry(text=text, hexpand=True)
    if example:
        e.set_placeholder_text(example)
    e.set_tooltip_text(f.get("hint") or f["label"])
    b = Gtk.Button(label="Save")
    b.set_tooltip_text(f"Saves {f['label']} (Enter does too)")
    b.connect("clicked", lambda *_: on_apply(e.get_text()))
    e.connect("activate", lambda *_: on_apply(e.get_text()))
    line.append(e)
    line.append(b)
    box.append(line)
    r = Gtk.ListBoxRow(activatable=False, selectable=False)
    r.set_child(box)
    r.set_tooltip_text(f.get("hint") or f["label"])
    r.entry = e
    return r


def sentence(text, more):
    """Two hints as one: a full stop between them."""
    text = (text or "").strip()
    if not text:
        return more
    return text + ("" if text[-1] in ".!?:" else ".") + " " + more


def account():
    """lib/bromigos_account.py, or None in a bromigOS without it."""
    try:
        import bromigos_account
        return bromigos_account
    except ImportError:
        return None


class Sheet:
    """A form's content (self.page, an Adw.PreferencesPage) and how it's shown: present()
    as an Adw.Dialog over a Settings window, or a host takes self.page and gives
    on_close (the Customize window shows it in its own sheet: a dialog window would open
    under its overlay)."""
    title = ""
    size = (560, 600)
    on_close = None

    def _page(self):
        self.page = Adw.PreferencesPage()
        self.dialog = None

    def present(self):
        self.dialog = Adw.Dialog(title=self.title, content_width=self.size[0], content_height=self.size[1])
        tv = Adw.ToolbarView()
        hb = Adw.HeaderBar()
        t = Gtk.Label(label=self.title)                # the whole title: the header makes room for it
        t.add_css_class("title")
        hb.set_title_widget(t)
        tv.add_top_bar(hb)
        tv.set_content(self.page)
        self.dialog.set_child(tv)
        self.dialog.present(self.ctx.window)
        return self.dialog

    def close(self):
        if self.dialog is not None:
            self.dialog.close()
        elif self.on_close:
            self.on_close()


class WidgetForm(Sheet):
    def __init__(self, ctx, entry, done=None):
        self.ctx, self.e, self.done = ctx, entry, done
        self.name = entry["name"]
        self.wtitle = entry["title"].title() if entry["title"].isupper() else entry["title"]
        self.title = f"{self.wtitle} settings"
        self.values = dict(entry.get("values") or {})
        self._page()
        self.signins = []
        self.inputs = {}                    # each text field's box, by key (the tests type in them)
        self.build()

    # ------------------------------------------------------------------ the rows
    def build(self):
        ctx, e = self.ctx, self.e
        values = [f for f in e["form"] if f["kind"] not in ("secret-signin", "link")]
        links = [f for f in e["form"] if f["kind"] == "link"]
        if values:
            g = Adw.PreferencesGroup(title=GLib.markup_escape_text(self.wtitle.upper()),
                                     description=GLib.markup_escape_text(
                                         f"Saved in {home(e.get('settings_file')) or 'its file'}; the widget reads it "
                                         "again at once."))
            for f in values:
                g.add(self.row(f))
            for f in links:
                g.add(self.link(f))
            self.page.add(g)
        elif links:
            g = Adw.PreferencesGroup(title=GLib.markup_escape_text(self.wtitle.upper()))
            for f in links:
                g.add(self.link(f))
            self.page.add(g)
        for f in e["form"]:
            if f["kind"] == "secret-signin":
                s = SignIn(self, f)
                self.signins.append(s)
                self.page.add(s.group)

    def link(self, f):
        """A `link` field: a row that opens another Settings page (this form closes)."""
        r = Adw.ActionRow(title=GLib.markup_escape_text(f["label"]),
                          subtitle=GLib.markup_escape_text(f.get("hint") or ""))
        r.set_activatable(True)
        r.add_suffix(Gtk.Image.new_from_icon_name("go-next-symbolic"))
        page = f.get("page") or ""

        def go(*_):
            self.close()
            if f.get("command") == "bromigos-tv-guide":
                self.ctx.launch(["bromigos-tv-guide"])
            else:
                self.ctx.open_page(page)
        r.connect("activated", go)
        self.ctx.hint(r, f.get("hint") or f"{f['label']}: opens Settings › {page} (bromigos settings {page})")
        return r

    def row(self, f):
        ctx = self.ctx
        k, kind = f["key"], f["kind"]
        cur = self.values.get(k)
        hint = f.get("hint") or f["label"]
        if kind in ("text", "list"):
            g = dict(f, hint=sentence(f.get("hint"), "Separate them with commas.") if kind == "list" else f.get("hint"))
            r = field_row(g, ", ".join(map(str, cur or [])) if kind == "list" else str(cur or ""),
                          lambda text: self.change(f, [x.strip() for x in text.split(",") if x.strip()]
                                                   if kind == "list" else text), example=f.get("example"))
            self.inputs[k] = r.entry
        elif kind == "number":
            lo, hi = f.get("min", -1e9), f.get("max", 1e9)
            r = Adw.SpinRow.new_with_range(lo, hi, f.get("step", 1))
            r.set_title(GLib.markup_escape_text(f["label"]))
            r.set_value(float(cur if cur is not None else f.get("default") or 0))
            r._timer = None

            def moved(w, _p, f=f):
                if w._timer:
                    GLib.source_remove(w._timer)
                w._timer = GLib.timeout_add(600, lambda: (setattr(w, "_timer", None),
                                                          self.change(f, str(w.get_value())), False)[2])
            r.connect("notify::value", moved)
        elif kind == "bool":
            r = Adw.SwitchRow(title=GLib.markup_escape_text(f["label"]))
            r.set_active(bool(cur))
            r.connect("notify::active", lambda w, _p: self.change(f, "on" if w.get_active() else "off"))
        else:                                                          # choice
            choices = [(c[0], c[1]) if isinstance(c, (list, tuple)) else (c, str(c)) for c in f.get("choices") or []]
            r = Adw.ComboRow(title=GLib.markup_escape_text(f["label"]))
            r.set_model(Gtk.StringList.new([lab for _, lab in choices]))
            vals = [v for v, _ in choices]
            if cur in vals:
                r.set_selected(vals.index(cur))
            r.connect("notify::selected", lambda w, _p: 0 <= w.get_selected() < len(vals) and
                      self.change(f, vals[w.get_selected()]))
        if f.get("hint") and kind not in ("text", "list") and hasattr(r, "set_subtitle"):
            r.set_subtitle(GLib.markup_escape_text(f["hint"]))
        ctx.hint(r, f"{f['label']}: {hint}. Runs bromigos panels set {self.name} {k} …")
        return r

    def change(self, f, raw):
        k = f["key"]
        old = self.values.get(k)
        args = list(raw) if isinstance(raw, list) else [str(raw)]
        if f["kind"] in ("list", "secret-signin") and not args:
            argv, undo = CMD + ["unset", self.name, k, "--json"], None
        else:
            argv = CMD + ["set", self.name, k] + args + ["--json"]
            undo = (CMD + ["set", self.name, k] + ([str(x) for x in old] if isinstance(old, list) else [str(old)]) +
                    ["--json"]) if old not in (None, "", []) else CMD + ["unset", self.name, k, "--json"]

        def ok(d):
            self.values = d.get("values") or self.values
            for si in self.signins:                        # which accounts it shows may have changed
                si.refresh_all()
            if self.done:
                self.done()
        self.ctx.change(argv, lambda d: d.get("said") or f"{f['label']} saved", undo=undo, done=ok)


class SignIn:
    """A widget's sign-in to a service: a block for each of the service's accounts (Sign in,
    Signed in as …, Sign out), which of them this widget shows, and Add another account…
    A service starts with one account, "default"; more are named ("work"), each with its
    own server and app when it needs them (lib/bromigos_account.py)."""

    def __init__(self, form, field):
        self.form, self.f, self.ctx = form, field, form.ctx
        self.provider = field.get("provider") or ""
        self.A = account()
        info = (getattr(self.A, "PROVIDERS", {}) or {}).get(self.provider, {}) if self.A else {}
        self.ptitle = info.get("title") or self.provider.title()
        self.help = info.get("app_help") or ""
        self.group = Adw.PreferencesGroup(title=GLib.markup_escape_text(field.get("label") or self.ptitle),
                                          description=GLib.markup_escape_text(field.get("hint") or
                                                                              f"Sign in to {self.ptitle} for this widget."))
        self.box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        self.group.add(self.box)
        self.blocks = []
        self.adder = None
        self.rebuild()

    # ------------------------------------------------------------------ the accounts
    def names(self):
        if self.A is None:
            return ["default"]
        try:
            return self.A.names(self.provider) if hasattr(self.A, "names") else ["default"]
        except Exception:                                         # noqa: BLE001  shown as the default, never raised
            return ["default"]

    def can_add(self):
        return self.A is not None and hasattr(self.A, "add_account") and self.provider in self.A.PROVIDERS

    def rebuild(self):
        """A block per account, then Add another account…"""
        c = self.box.get_first_child()
        while c is not None:
            self.box.remove(c)
            c = self.box.get_first_child()
        self.blocks = [Account(self, n) for n in self.names()]
        for b in self.blocks:
            self.box.append(b.list)
        if self.can_add():
            self.adder = Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE)
            self.adder.add_css_class("boxed-list")
            self.box.append(self.adder)
            self.add_closed()
        for b in self.blocks:
            b.refresh()

    def block(self, name):
        return next((b for b in self.blocks if b.name == name), None)

    def many(self):
        return len(self.blocks) > 1

    def signed_in_names(self):
        out = []
        for b in self.blocks:
            try:
                st = self.A.status(self.provider, **b.kw)
            except Exception:                                     # noqa: BLE001
                st = {}
            if st.get("signed_in"):
                out.append(b.name)
        return out

    def shown(self):
        """The accounts this widget shows: the setting's list, or every signed-in one."""
        names = self.names()
        want = [n for n in (self.form.values.get(self.f["key"]) or []) if n in names]
        return want or self.signed_in_names() or names[:1]

    def set_shown(self, name, on):
        """Show or stop showing an account here. Back to every signed-in account when that's
        what's chosen, so an account signed in later shows by itself."""
        cur = self.shown()
        want = [n for n in self.names() if (n in cur and n != name) or (n == name and on)]
        if not want:
            self.ctx.toast("A widget shows one account at least")
            self.refresh_all()
            return
        raw = [] if set(want) == set(self.signed_in_names()) else want
        self.form.change(self.f, raw)

    def refresh_all(self):
        for b in self.blocks:
            b.refresh()

    # ------------------------------------------------------------------ Add another account…
    def _clear_adder(self):
        c = self.adder.get_first_child() if self.adder else None
        while c is not None:
            self.adder.remove(c)
            c = self.adder.get_first_child()

    def add_closed(self, note=None):
        self._clear_adder()
        what = (f"Such as your company's own {self.ptitle}" if self.A.has_server(self.provider)
                else f"A second {self.ptitle} account, side by side with the first")
        r = Adw.ActionRow(title=GLib.markup_escape_text(f"Another {self.ptitle} account"),
                          subtitle=GLib.markup_escape_text(note or what))
        r.add_suffix(self.ctx.button("Add another account…", self.open_add, f"Adds another {self.ptitle} account: "
                                     "this widget shows its rows beside the others, each tagged with its name"))
        self.adder.append(self.ctx.hint(r, f"Every widget that uses {self.ptitle} can show this account too"))

    def open_add(self):
        """The new account's name, and its server for GitLab or GitHub. Its client ID comes
        after, and only when its server needs one."""
        self._clear_adder()
        self.add_name = Adw.EntryRow(title="Name, such as work")
        self.ctx.hint(self.add_name, "A short name for the account: lower-case letters, digits, - and _. The widget "
                                     "tags its rows with it")
        self.adder.append(self.add_name)
        self.add_server = None
        if self.A.has_server(self.provider):
            pub = short_url(self.A.PROVIDERS[self.provider]["base"])
            self.add_server = Adw.EntryRow(title=f"Server address (empty: {pub})")
            self.ctx.hint(self.add_server, f"Your own {self.ptitle}, such as https://git.example.org. Leave it empty "
                                           f"for {pub}, which uses bromigOS's own app")
            self.adder.append(self.add_server)
        r = Adw.ActionRow(title="")
        r.add_suffix(self.ctx.button("Cancel", self.add_closed, "Adds nothing"))
        r.add_suffix(self.ctx.button("Add", self.submit_add, "Adds the account; then sign in to it", primary=True))
        self.add_name.connect("entry-activated", lambda *_: self.submit_add())
        self.adder.append(r)

    def submit_add(self):
        name = self.add_name.get_text().strip()
        server = self.add_server.get_text().strip() if self.add_server else ""
        try:
            self.A.add_account(self.provider, name, base=server or None)
        except Exception as e:                                    # noqa: BLE001  said in the form
            self.ctx.toast(f"Not added: {e}"[:200], timeout=8)
            return
        self.ctx.toast(f"Added the {self.ptitle} account {name}")
        self.rebuild()
        if self.form.done:
            self.form.done()


class Account:
    """One account's block in a SignIn: Sign in, Signed in as …, Sign out, Remove. The
    sign-in runs off the window's thread; its prompt (a code to type, or a page to open)
    shows here."""

    def __init__(self, signin, name):
        self.si, self.name = signin, name
        self.form, self.ctx, self.A, self.provider = signin.form, signin.ctx, signin.A, signin.provider
        self.ptitle, self.help = signin.ptitle, signin.help
        self.kw = {} if name == "default" else {"account": name}
        self.list = Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE)
        self.list.add_css_class("boxed-list")
        self.rows = []
        self.cancel = False
        self.deadline = None

    def label(self):
        try:
            return self.A.label(self.provider, **self.kw) if hasattr(self.A, "label") else self.name
        except Exception:                                         # noqa: BLE001
            return self.name

    def head(self, words):
        """A row's title: "Signed in as …", or "work: signed in as …" when there are several."""
        if not self.si.many():
            return words
        return f"{self.label()}: {words[0].lower()}{words[1:]}"

    def where(self):
        try:
            return short_url(self.A.base(self.provider, **self.kw))
        except Exception:                                         # noqa: BLE001
            return self.ptitle

    def clear(self):
        for r in self.rows:
            self.list.remove(r)
        self.rows = []

    def add(self, w):
        self.list.append(w)
        self.rows.append(w)
        return w

    def button(self, label, cb, hint, primary=False, destructive=False):
        return self.ctx.button(label, cb, hint, primary=primary, destructive=destructive)

    def extras(self, r):
        """With several accounts: whether this widget shows it (a check), and Remove… for a
        named one."""
        if self.si.many():
            on = self.name in self.si.shown()
            c = Gtk.CheckButton(active=on, valign=Gtk.Align.CENTER)
            c.set_tooltip_text(f"Show {self.label()}'s rows in this widget. Unticked, the widget leaves this account "
                               "out; other widgets still can show it")
            c.connect("toggled", lambda w: self.si.set_shown(self.name, w.get_active()))
            r.add_prefix(c)
        if self.name != "default" and hasattr(self.A, "remove_account"):
            r.add_suffix(self.button("Remove…", self.ask_remove, f"Signs {self.label()} out and forgets its settings, "
                                     "after you confirm"))

    def refresh(self, note=None):
        self.clear()
        if self.A is None:
            self.add(self.ctx.hint(Adw.ActionRow(title="Signing in needs bromigos_account",
                                                 subtitle="A newer bromigOS has it: run bromigos update"),
                                   "This bromigOS has no account sign-in helper yet"))
            return
        try:
            st = self.A.status(self.provider, **self.kw)
        except Exception as e:                                    # noqa: BLE001  shown, never raised
            st = {"signed_in": False, "who": None, "needs": [], "via": None}
            note = note or f"Couldn't read the sign-in: {e}"
        many = self.si.many()
        if st.get("signed_in"):
            via = " through gh" if st.get("via") == "gh" else ""
            where = f"{self.where()} · " if many else f"{self.ptitle}: "
            r = Adw.ActionRow(title=GLib.markup_escape_text(self.head(f"Signed in{via} as {st.get('who') or '…'}")),
                              subtitle=GLib.markup_escape_text(where + "the token is in your keyring"
                                                               if not via else "Your gh login covers it: nothing to do here"))
            if st.get("via") != "gh":
                r.add_suffix(self.button("Sign out", self.sign_out, f"Forgets the {self.ptitle} sign-in (the token "
                                                                    "in your keyring)", destructive=True))
            self.extras(r)
            self.add(self.ctx.hint(r, f"Signed in to {self.ptitle}" + (f" ({self.label()})" if many else "")))
        elif st.get("needs"):
            self.connect_form(st["needs"], note)
            return
        else:
            r = Adw.ActionRow(title=GLib.markup_escape_text(self.head(f"Not signed in to {self.ptitle}")),
                              subtitle=GLib.markup_escape_text(note or (f"{self.where()} · sign in once; the widget "
                                                                        "stays signed in" if many else
                                                                        "Sign in once; the widget stays signed in")))
            r.add_suffix(self.button("Sign in", self.sign_in, f"Signs in to {self.ptitle}: you confirm it on "
                                                                f"{self.ptitle}'s own page", primary=True))
            if self.provider == "gitlab":
                r.add_suffix(self.button("Paste a token…", self.paste_token, "Use a GitLab personal access token "
                                                                              "instead of signing in"))
            self.extras(r)
            self.add(self.ctx.hint(r, f"Sign in to {self.ptitle} for this widget"))
        if note and st.get("signed_in"):
            self.add(Adw.ActionRow(title=GLib.markup_escape_text(note)))

    # ------------------------------------------------------------------ connect (the provider's app)
    def connect_form(self, missing, note=None):
        fields = []
        try:
            fields = self.A.fields(self.provider)
        except Exception:                                         # noqa: BLE001
            fields = [{"key": k, "label": k, "hint": "", "required": True} for k in missing]
        cur = {}
        try:
            cur = self.A.config(self.provider, **self.kw) or {}
        except Exception:                                         # noqa: BLE001
            pass
        head = Adw.ActionRow(title=GLib.markup_escape_text(self.head(f"Connect {self.ptitle}")),
                             subtitle=GLib.markup_escape_text(note or self.help or "Its client ID first"))
        head.set_subtitle_lines(6)
        if self.name != "default":
            head.add_suffix(self.button("Remove…", self.ask_remove, f"Forgets {self.label()}, after you confirm"))
        self.add(self.ctx.hint(head, f"{self.ptitle} needs your own app's ID once, shared by every widget that uses "
                                     f"it (~/.config/bromigos/accounts.toml)"))
        entries = {}
        for f in fields:
            hint = f.get("hint") if f.get("hint") != self.help else ""     # said once, above
            r = field_row(dict(f, label=f.get("label") or f["key"], hint=hint), str(cur.get(f["key"]) or ""),
                          lambda _t: self.save_config(entries))
            self.ctx.hint(r, f.get("hint") or f.get("label") or f["key"])
            entries[f["key"]] = r.entry
            self.add(r)
        self.entries = entries
        # each field's Save saves them all, then offers Sign in

    def save_config(self, entries):
        vals = {k: r.get_text().strip() for k, r in entries.items() if r.get_text().strip()}
        try:
            self.A.configure(self.provider, **self.kw, **vals)
        except Exception as e:                                    # noqa: BLE001
            self.refresh(f"Not saved: {e}")
            return
        self.ctx.toast(f"{self.ptitle}: saved")
        self.refresh()

    # ------------------------------------------------------------------ remove (a named account)
    def ask_remove(self):
        self.clear()
        r = Adw.ActionRow(title=GLib.markup_escape_text(f"Remove the {self.ptitle} account {self.label()}?"),
                          subtitle="It signs out and forgets the account's settings. Every widget stops showing it.")
        r.set_subtitle_lines(3)
        r.add_suffix(self.button("Cancel", self.refresh, "Keeps it"))
        r.add_suffix(self.button("Remove", self.remove, "Signs it out and forgets it", destructive=True))
        self.add(self.ctx.hint(r, "Removing an account can't be undone; you can add it again"))

    def remove(self):
        lab = self.label()
        try:
            self.A.remove_account(self.provider, self.name)
        except Exception as e:                                    # noqa: BLE001
            self.refresh(f"Not removed: {e}")
            return
        self.ctx.toast(f"Removed the {self.ptitle} account {lab}")
        self.si.rebuild()
        if self.form.done:
            self.form.done()

    # ------------------------------------------------------------------ the sign-in
    def sign_in(self):
        self.cancel = False
        self.clear()
        self.waiting = self.add(Adw.ActionRow(title=GLib.markup_escape_text(
            self.head(f"Asking {self.ptitle} for a code…"))))
        self.waiting.add_prefix(Adw.Spinner())
        cancel = self.button("Cancel", self.stop, "Stops waiting for the sign-in")
        self.waiting.add_suffix(cancel)

        def run():
            try:
                st = self.A.sign_in(self.provider, on_prompt=lambda d: GLib.idle_add(self.prompt, d),
                                    cancelled=lambda: self.cancel, **self.kw)
                GLib.idle_add(self.finished, st, None)
            except Exception as e:                                # noqa: BLE001
                GLib.idle_add(self.finished, None, e)
        threading.Thread(target=run, daemon=True, name=f"signin-{self.provider}-{self.name}").start()

    def stop(self):
        self.cancel = True
        self.deadline = None
        self.refresh("Cancelled")

    def prompt(self, d):
        """The device flow's code (large, with Copy and the page), or PKCE's page to open."""
        if getattr(self, "waiting", None) is not None:
            self.waiting.set_title(GLib.markup_escape_text(self.head(f"Waiting for you to approve on {self.ptitle}…")))
        if d.get("user_code"):
            url = d.get("verification_uri_complete") or d.get("verification_uri")
            box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10, margin_top=12, margin_bottom=12,
                          margin_start=12, margin_end=12)
            box.append(Gtk.Label(label=f"Type this code on {self.ptitle}'s page:", xalign=0))
            row = Gtk.Box(spacing=10)
            code = Gtk.Label(label=d["user_code"], selectable=True, xalign=0, hexpand=True)
            code.add_css_class("title-1")
            code.set_tooltip_text("The code: type it on the page, or copy it")
            row.append(code)
            row.append(self.button("Copy", lambda: self.ctx.copy(d["user_code"]), "Copies the code"))
            row.append(self.button("Open the page", lambda: self.ctx.open_url(url), f"Opens {url} in your browser",
                                   primary=True))
            box.append(row)
            where = Gtk.Label(label=short_url(d.get("verification_uri") or url), xalign=0, selectable=True)
            where.add_css_class("dim-label")
            where.set_tooltip_text(url)
            box.append(where)
            r = Gtk.ListBoxRow(activatable=False, selectable=False)
            r.set_child(box)
            self.add(self.ctx.hint(r, f"{self.ptitle} shows this sign-in when you type the code there"))
            self.left = self.add(Adw.ActionRow(title=""))
            self.deadline = time.monotonic() + float(d.get("expires_in") or 900)
            GLib.timeout_add_seconds(1, self.tick)
            self.tick()
        elif d.get("auth_url"):
            r = Adw.ActionRow(title=GLib.markup_escape_text(f"Sign in on {self.ptitle}'s page"),
                              subtitle="It comes back here by itself")
            r.add_suffix(self.button("Open the sign-in page", lambda: self.ctx.open_url(d["auth_url"]),
                                     f"Opens {self.ptitle}'s sign-in page in your browser", primary=True))
            self.add(self.ctx.hint(r, "Approve it there; this finishes on its own"))
        return False

    def tick(self):
        if self.deadline is None or not getattr(self, "left", None):
            return False
        left = int(self.deadline - time.monotonic())
        if left <= 0:
            self.left.set_title("The code has run out: cancel and sign in again")
            return False
        self.left.set_title(f"The code works for {left // 60}:{left % 60:02d} more")
        return True

    def finished(self, st, err):
        self.deadline = None
        if self.cancel:
            return False
        if err is None:
            self.ctx.toast(f"Signed in to {self.ptitle} as {(st or {}).get('who') or '…'}")
            self.si.refresh_all()                                 # the others' "shown here" may change
        elif type(err).__name__ == "NeedsConfig":
            self.clear()
            self.connect_form(getattr(err, "fields", []) or ["client_id"])
        else:
            self.clear()
            r = Adw.ActionRow(title="Not signed in", subtitle=GLib.markup_escape_text(str(err)[:240]))
            r.add_suffix(self.button("Retry", self.sign_in, "Tries the sign-in again", primary=True))
            self.add(self.ctx.hint(r, "The sign-in didn't finish"))
        if self.form.done:
            self.form.done()
        return False

    def sign_out(self):
        try:
            self.A.sign_out(self.provider, **self.kw)
        except Exception as e:                                    # noqa: BLE001
            self.refresh(f"Couldn't sign out: {e}")
            return
        self.ctx.toast(f"Signed out of {self.ptitle}" + (f" ({self.label()})" if self.si.many() else ""))
        self.si.refresh_all()

    def paste_token(self):
        self.clear()
        r = Adw.PasswordEntryRow(title=GLib.markup_escape_text(f"{self.ptitle} personal access token"))
        r.set_show_apply_button(True)

        def apply(w):
            tok = w.get_text().strip()
            w.set_text("")
            if not tok:
                return
            try:
                self.A.set_token(self.provider, tok, **self.kw)
            except Exception as e:                                # noqa: BLE001
                self.refresh(f"Not stored: {e}")
                return
            self.ctx.toast(f"{self.ptitle}: token stored in your keyring")
            self.si.refresh_all()
        r.connect("apply", apply)
        self.add(self.ctx.hint(r, "Pasted here, it goes to your keyring and is never shown again"))
        back = Adw.ActionRow(title="")
        back.add_suffix(self.button("Back", self.refresh, "Sign in instead"))
        self.add(back)


# ------------------------------------------------------------------ Install from URL
def _toml_str(s):
    import json
    return json.dumps(str(s), ensure_ascii=False)


def approvals_dir():
    import os
    state = os.environ.get("XDG_STATE_HOME") or os.path.expanduser("~/.local/state")
    return os.path.join(state, "bromigos", "ext", "approvals")


def approval_file(doc, when=None):
    """A setup answers file that approves this one extension (docs/extensions.md, "Trust and
    approval"): the existing way to approve code without a terminal. It's kept, so the
    ledger's record of the approval (this file's path and sha256) points at what was
    approved, and where."""
    import os
    when = when or time.strftime("%Y-%m-%d %H:%M %Z")
    os.makedirs(approvals_dir(), exist_ok=True)
    name = "".join(c for c in (doc.get("name") or "extension") if c.isalnum() or c in "-_")
    path = os.path.join(approvals_dir(), f"settings-{time.strftime('%Y%m%dT%H%M%S')}-{name}.toml")
    perms = doc.get("permissions") or {}
    item = "{ source = " + _toml_str(doc["source"]) + (f", path = {_toml_str(doc['path'])}" if doc.get("path") else "") \
        + (f", ref = {_toml_str(doc['ref'])}" if doc.get("ref") else "") + " }"
    lines = [f"# Approved in Settings › Widgets (Install from URL), {when}: the person read what it",
             "# can do, below, and clicked Install. bromigos setup --answers installed it from this file.",
             f"# {doc.get('name')} {doc.get('version') or ''} by {', '.join(doc.get('authors') or []) or '?'}"
             f" ({doc.get('licence') or 'no licence given'}), commit {doc.get('commit') or '?'}",
             f"# runs code: {'yes' if doc.get('code') else 'no'}; network: {perms.get('network', 'none')}; "
             f"files: {', '.join(perms.get('filesystem') or []) or 'none'}"
             + (f"; VECTOR: {perms['vector']}" if perms.get("vector") else ""),
             "[extensions]", f"install = [{item}]", "approve = true", ""]
    with open(path, "w") as f:
        f.write("\n".join(lines))
    return path


class InstallFromURL(Sheet):
    """Paste a git URL (or pick a folder), see what it would add and what it can do
    (`bromigos panels inspect`, which runs `bromigos ext info`), then Install: the button
    is the approval, given through a setup answers file, the existing way."""

    title = "Add from a URL"
    size = (720, 700)

    def __init__(self, ctx, done=None, source=None):
        self.ctx, self.done = ctx, done
        self.doc = None
        self._page()
        g = Adw.PreferencesGroup(title="WHERE IT IS", description="A git URL (https://, ssh:// or git@host:path; add "
                                                                  "@tag to pin a version), or a folder on this machine.")
        self.url = Adw.EntryRow(title="Git URL or folder")
        ctx.hint(self.url, "For example https://github.com/someone/their-widget@v1.0, or a folder you made with "
                           "bromigos ext new widget")
        g.add(self.url)
        self.sub = Adw.EntryRow(title="Its folder inside the repository (if it isn't the root)")
        ctx.hint(self.sub, "Like examples/moon-phase: the folder that holds bromigos-ext.toml")
        g.add(self.sub)
        r = Adw.ActionRow(title="")
        r.add_suffix(ctx.button("Pick a folder…", self.pick, "Chooses a folder on this machine instead of a URL"))
        r.add_suffix(ctx.button("Check it", self.check, "Fetches it and checks it (bromigos ext info): nothing is "
                                                        "installed yet", primary=True))
        g.add(r)
        self.page.add(g)
        self.result = Adw.PreferencesGroup(title="WHAT IT WOULD ADD")
        self.result.set_visible(False)
        self.page.add(self.result)
        self.rows = []
        if source:                                  # a catalog entry or a link: check it straight away
            self.url.set_text(source)
            GLib.idle_add(lambda: (self.check(), False)[1])

    def pick(self):
        fd = Gtk.FileDialog(title="The extension's folder")

        def done(d, res):
            try:
                f = d.select_folder_finish(res)
            except GLib.Error:
                return
            if f is not None and f.get_path():
                self.url.set_text(f.get_path())
        fd.select_folder(self.ctx.window, None, done)

    def clear(self):
        for r in self.rows:
            self.result.remove(r)
        self.rows = []

    def add(self, w):
        self.result.add(w)
        self.rows.append(w)
        return w

    def row(self, title, sub, hint):
        r = Adw.ActionRow(title=GLib.markup_escape_text(title), subtitle=GLib.markup_escape_text(sub or ""))
        r.set_subtitle_lines(4)
        return self.add(self.ctx.hint(r, hint))

    def check(self):
        src = self.url.get_text().strip()
        if not src:
            self.ctx.toast("Paste a git URL, or pick a folder")
            return
        self.clear()
        self.result.set_visible(True)
        r = self.add(Adw.ActionRow(title="Fetching and checking it…"))
        r.add_prefix(Adw.Spinner())
        argv = CMD + ["inspect", src] + (["--path", self.sub.get_text().strip()] if self.sub.get_text().strip() else [])
        self.ctx.json(argv + ["--json"], self.checked)

    def checked(self, doc, err):
        self.clear()
        if not doc or doc.get("ok") is False:
            self.doc = None
            self.row("It can't be installed", (doc or {}).get("error") or err or "no answer",
                     "bromigos ext info refused it, or couldn't fetch it")
            return
        self.doc = doc
        perms = doc.get("permissions") or {}
        self.row(f"{doc['name']} {doc.get('version') or ''}", doc.get("description") or "",
                 "Its name and version, as its manifest says")
        self.row("Made by", f"{', '.join(doc.get('authors') or []) or 'nobody named'} · "
                            f"{doc.get('licence') or 'no licence given'}"
                 + (f" · {doc['homepage']}" if doc.get("homepage") else ""), "Who made it, and its licence")
        for w in doc.get("widgets") or []:
            words = w.get("description") or "a widget"
            extra = []
            if w.get("reads"):
                extra.append(f"reads {w['reads']}")
            if w.get("sizes"):
                extra.append("sizes: " + ", ".join(w["sizes"]))
            if w.get("accounts"):
                extra.append("signs in to " + ", ".join(a for a in w["accounts"] if a))
            self.row(f"Widget: {(w.get('title') or w.get('name') or '?').title()}", words + (
                "\n" + " · ".join(extra) if extra else ""), "A desktop panel it adds, in its own words (read from its "
                                                           "code without running it)")
        kinds = ", ".join(k for k in doc.get("kinds") or [] if k != "widget")
        if kinds:
            self.row("Also", kinds, "Other parts it adds")
        net = perms.get("network", "none")
        net = ", ".join(net) if isinstance(net, list) else net
        self.row("Runs code" if doc.get("code") else "Data only",
                 (f"Network: {net} · Files outside its folder: {', '.join(perms.get('filesystem') or []) or 'none'}"
                  + (f" · VECTOR: {perms['vector']}" if perms.get("vector") else "")),
                 "What it says it reaches. bromigOS shows and records this, but doesn't enforce it: an extension runs "
                 "as you, like any program you install.")
        for wtext in doc.get("warnings") or []:
            self.row("Note", str(wtext), "From bromigos ext info")
        if doc.get("installed"):
            self.row("Already installed", "Update it from Settings › Extensions", "It's installed already")
            return
        r = Adw.ActionRow(title="Install it?", subtitle="It runs as you. Installing records that you approved it here."
                          if doc.get("code") else "It's data only.")
        r.add_suffix(self.ctx.button("Cancel", self.close, "Closes this without installing anything"))
        r.add_suffix(self.ctx.button("Install", self.install, "Installs it: this click is your approval, recorded in "
                                                              "the extensions' ledger", primary=True))
        self.add(self.ctx.hint(r, "Your approval: the extension runs code as you"))

    def install(self):
        doc = self.doc
        try:
            path = approval_file(doc)
        except OSError as e:
            self.ctx.toast(f"Not installed: {e}")
            return
        self.ctx.toast(f"Installing {doc['name']}…")

        def fin(res, err):
            items = (res or {}).get("setup") or []
            ext = next((x for x in items if x.get("section") == "extensions" or "extensions" in str(x)), {})
            ok = bool(res) and all(x.get("ok", True) for x in items)
            if ok:
                self.ctx.toast(f"Installed {doc['name']}: its widget is in the gallery within a few seconds")
                self.close()
                if self.done:
                    GLib.timeout_add_seconds(3, lambda: (self.done(), False)[1])
            else:
                why = ext.get("detail") or err or "failed"
                self.clear()
                self.row("Not installed", str(why)[:400], "bromigos setup --answers said this")
        self.ctx.json(["bromigos", "setup", "--answers", path, "--json"], fin)
