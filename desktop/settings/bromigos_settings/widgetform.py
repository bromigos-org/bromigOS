"""A widget's settings form (docs/widgets.md, "A widget's settings"), drawn from the fields
its panel declares (widgets/widget_settings.py): a text, list, number, switch or choice
row for each value, and a sign-in for each account. Values go through `bromigos panels
set|unset NAME KEY … --json` (each change toasts Undo); sign-ins go through
lib/bromigos_account.py, which keeps tokens in the keyring and never shows them.

    WidgetForm(ctx, entry, done=None).present()     entry: a `bromigos panels gallery` widget
"""
import threading
import time

from gi.repository import Adw, GLib, Gtk

CMD = ["bromigos", "panels"]


def account():
    """lib/bromigos_account.py, or None in a bromigOS without it."""
    try:
        import bromigos_account
        return bromigos_account
    except ImportError:
        return None


class WidgetForm:
    def __init__(self, ctx, entry, done=None):
        self.ctx, self.e, self.done = ctx, entry, done
        self.name = entry["name"]
        self.title = entry["title"].title() if entry["title"].isupper() else entry["title"]
        self.values = dict(entry.get("values") or {})
        self.dialog = Adw.Dialog(title=self.title, content_width=560, content_height=600)
        tv = Adw.ToolbarView()
        tv.add_top_bar(Adw.HeaderBar())
        self.page = Adw.PreferencesPage()
        tv.set_content(self.page)
        self.dialog.set_child(tv)
        self.signins = []
        self.build()

    def present(self):
        self.dialog.present(self.ctx.window)
        return self.dialog

    # ------------------------------------------------------------------ the rows
    def build(self):
        ctx, e = self.ctx, self.e
        values = [f for f in e["form"] if f["kind"] != "secret-signin"]
        if values:
            g = Adw.PreferencesGroup(title=GLib.markup_escape_text(self.title.upper()),
                                     description=GLib.markup_escape_text(f"Saved in {e.get('settings_file') or 'its file'}; "
                                                                         "the widget reads it again at once."))
            for f in values:
                g.add(self.row(f))
            self.page.add(g)
        for f in e["form"]:
            if f["kind"] == "secret-signin":
                s = SignIn(self, f)
                self.signins.append(s)
                self.page.add(s.group)

    def row(self, f):
        ctx = self.ctx
        k, kind = f["key"], f["kind"]
        cur = self.values.get(k)
        hint = f.get("hint") or f["label"]
        if kind in ("text", "list"):
            r = Adw.EntryRow(title=GLib.markup_escape_text(f["label"] + (" (separate with commas)" if kind == "list" else "")))
            r.set_text(", ".join(map(str, cur or [])) if kind == "list" else str(cur or ""))
            r.set_show_apply_button(True)
            r.connect("apply", lambda w: self.change(f, [x.strip() for x in w.get_text().split(",") if x.strip()]
                                                     if kind == "list" else w.get_text()))
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
        if f.get("hint") and hasattr(r, "set_subtitle"):
            r.set_subtitle(GLib.markup_escape_text(f["hint"]))
        ctx.hint(r, f"{f['label']}: {hint}. Runs bromigos panels set {self.name} {k} …")
        return r

    def change(self, f, raw):
        k = f["key"]
        old = self.values.get(k)
        args = list(raw) if isinstance(raw, list) else [str(raw)]
        if f["kind"] == "list" and not args:
            argv, undo = CMD + ["unset", self.name, k, "--json"], None
        else:
            argv = CMD + ["set", self.name, k] + args + ["--json"]
            undo = (CMD + ["set", self.name, k] + ([str(x) for x in old] if isinstance(old, list) else [str(old)]) +
                    ["--json"]) if old not in (None, "", []) else CMD + ["unset", self.name, k, "--json"]

        def ok(d):
            self.values = d.get("values") or self.values
            if self.done:
                self.done()
        self.ctx.change(argv, lambda d: d.get("said") or f"{f['label']} saved", undo=undo, done=ok)


class SignIn:
    """An account row: Sign in, Signed in as …, Sign out. The sign-in runs off the window's
    thread; its prompt (a code to type, or a page to open) shows here."""

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
        self.rows = []
        self.cancel = False
        self.deadline = None
        self.refresh()

    def clear(self):
        for r in self.rows:
            self.group.remove(r)
        self.rows = []

    def add(self, w):
        self.group.add(w)
        self.rows.append(w)
        return w

    def button(self, label, cb, hint, primary=False, destructive=False):
        return self.ctx.button(label, cb, hint, primary=primary, destructive=destructive)

    def refresh(self, note=None):
        self.clear()
        if self.A is None:
            self.add(self.ctx.hint(Adw.ActionRow(title="Signing in needs bromigos_account",
                                                 subtitle="A newer bromigOS has it: run bromigos update"),
                                   "This bromigOS has no account sign-in helper yet"))
            return
        try:
            st = self.A.status(self.provider)
        except Exception as e:                                    # noqa: BLE001  shown, never raised
            st = {"signed_in": False, "who": None, "needs": [], "via": None}
            note = note or f"Couldn't read the sign-in: {e}"
        if st.get("signed_in"):
            via = " through gh" if st.get("via") == "gh" else ""
            r = Adw.ActionRow(title=GLib.markup_escape_text(f"Signed in{via} as {st.get('who') or '…'}"),
                              subtitle=GLib.markup_escape_text(f"{self.ptitle}: the token is in your keyring"
                                                               if not via else "Your gh login covers it: nothing to do here"))
            if st.get("via") != "gh":
                r.add_suffix(self.button("Sign out", self.sign_out, f"Forgets the {self.ptitle} sign-in (the token "
                                                                    "in your keyring)", destructive=True))
            self.add(self.ctx.hint(r, f"Signed in to {self.ptitle}"))
        elif st.get("needs"):
            self.connect_form(st["needs"], note)
            return
        else:
            r = Adw.ActionRow(title=GLib.markup_escape_text(f"Not signed in to {self.ptitle}"),
                              subtitle=GLib.markup_escape_text(note or "Sign in once; the widget stays signed in"))
            r.add_suffix(self.button("Sign in", self.sign_in, f"Signs in to {self.ptitle}: you confirm it on "
                                                                f"{self.ptitle}'s own page", primary=True))
            if self.provider == "gitlab":
                r.add_suffix(self.button("Paste a token…", self.paste_token, "Use a GitLab personal access token "
                                                                              "instead of signing in"))
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
            cur = self.A.config(self.provider) or {}
        except Exception:                                         # noqa: BLE001
            pass
        head = Adw.ActionRow(title=GLib.markup_escape_text(f"Connect {self.ptitle}"),
                             subtitle=GLib.markup_escape_text(note or self.help or "Its client ID first"))
        head.set_subtitle_lines(6)
        self.add(self.ctx.hint(head, f"{self.ptitle} needs your own app's ID once, shared by every widget that uses "
                                     f"it (~/.config/bromigos/accounts.toml)"))
        entries = {}
        for f in fields:
            r = Adw.EntryRow(title=GLib.markup_escape_text(f.get("label") or f["key"]))
            r.set_text(str(cur.get(f["key"]) or ""))
            self.ctx.hint(r, f.get("hint") or f.get("label") or f["key"])
            entries[f["key"]] = r
            self.add(r)
        r = Adw.ActionRow(title="Then sign in")
        r.add_suffix(self.button("Save", lambda: self.save_config(entries), f"Saves {self.ptitle}'s settings to "
                                                                             "~/.config/bromigos/accounts.toml",
                                 primary=True))
        self.add(self.ctx.hint(r, "Saves them, then offers Sign in"))

    def save_config(self, entries):
        vals = {k: r.get_text().strip() for k, r in entries.items() if r.get_text().strip()}
        try:
            self.A.configure(self.provider, **vals)
        except Exception as e:                                    # noqa: BLE001
            self.refresh(f"Not saved: {e}")
            return
        self.ctx.toast(f"{self.ptitle}: saved")
        self.refresh()

    # ------------------------------------------------------------------ the sign-in
    def sign_in(self):
        self.cancel = False
        self.clear()
        self.waiting = self.add(Adw.ActionRow(title=GLib.markup_escape_text(f"Asking {self.ptitle}…")))
        self.waiting.add_prefix(Adw.Spinner())
        cancel = self.button("Cancel", self.stop, "Stops waiting for the sign-in")
        self.waiting.add_suffix(cancel)

        def run():
            try:
                st = self.A.sign_in(self.provider, on_prompt=lambda d: GLib.idle_add(self.prompt, d),
                                    cancelled=lambda: self.cancel)
                GLib.idle_add(self.finished, st, None)
            except Exception as e:                                # noqa: BLE001
                GLib.idle_add(self.finished, None, e)
        threading.Thread(target=run, daemon=True, name=f"signin-{self.provider}").start()

    def stop(self):
        self.cancel = True
        self.deadline = None
        self.refresh("Cancelled")

    def prompt(self, d):
        """The device flow's code (large, with Copy and the page), or PKCE's page to open."""
        if d.get("user_code"):
            code = Gtk.Label(label=d["user_code"], selectable=True)
            code.add_css_class("title-1")
            r = Adw.ActionRow(title="Type this code on the page", subtitle=GLib.markup_escape_text(
                d.get("verification_uri") or ""))
            r.add_suffix(code)
            r.add_suffix(self.button("Copy", lambda: self.ctx.copy(d["user_code"]), "Copies the code"))
            url = d.get("verification_uri_complete") or d.get("verification_uri")
            r.add_suffix(self.button("Open the page", lambda: self.ctx.open_url(url), f"Opens {url} in your browser",
                                     primary=True))
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
            self.refresh()
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
            self.A.sign_out(self.provider)
        except Exception as e:                                    # noqa: BLE001
            self.refresh(f"Couldn't sign out: {e}")
            return
        self.ctx.toast(f"Signed out of {self.ptitle}")
        self.refresh()

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
                self.A.set_token(self.provider, tok)
            except Exception as e:                                # noqa: BLE001
                self.refresh(f"Not stored: {e}")
                return
            self.ctx.toast(f"{self.ptitle}: token stored in your keyring")
            self.refresh()
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


class InstallFromURL:
    """Paste a git URL (or pick a folder), see what it would add and what it can do
    (`bromigos panels inspect`, which runs `bromigos ext info`), then Install: the button
    is the approval, given through a setup answers file, the existing way."""

    def __init__(self, ctx, done=None):
        self.ctx, self.done = ctx, done
        self.doc = None
        self.dialog = Adw.Dialog(title="Add from a URL", content_width=720, content_height=700)
        tv = Adw.ToolbarView()
        tv.add_top_bar(Adw.HeaderBar())
        self.page = Adw.PreferencesPage()
        tv.set_content(self.page)
        self.dialog.set_child(tv)
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

    def present(self):
        self.dialog.present(self.ctx.window)
        return self.dialog

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
        r.add_suffix(self.ctx.button("Cancel", self.dialog.close, "Closes this without installing anything"))
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
                self.dialog.close()
                if self.done:
                    GLib.timeout_add_seconds(3, lambda: (self.done(), False)[1])
            else:
                why = ext.get("detail") or err or "failed"
                self.clear()
                self.row("Not installed", str(why)[:400], "bromigos setup --answers said this")
        self.ctx.json(["bromigos", "setup", "--answers", path, "--json"], fin)
