"""Default apps: which app opens links, folders, text, pictures, videos, music, PDFs and
mail (xdg-mime), the terminal and the file manager bromigOS's own keys start, and your web
apps (docs/settings.md, "Default apps").

Everything goes through `bromigos defaults … --json`: a kind's app is set for each of its
types at once; the terminal and the file manager's key are a marked block in your
hyprland.lua, taken by Hyprland the safe way. Each change toasts Undo."""
import gi

gi.require_version("Adw", "1")
from gi.repository import GLib, Adw, Gtk  # noqa: E402

from bromigos_settings import Entry, Page  # noqa: E402

CMD = ["bromigos", "defaults"]
ICONS = {"browser": "web-browser-symbolic", "files": "system-file-manager-symbolic", "editor": "text-editor-symbolic",
         "images": "image-x-generic-symbolic", "video": "video-x-generic-symbolic", "music": "audio-x-generic-symbolic",
         "pdf": "x-office-document-symbolic", "mail": "mail-unread-symbolic"}
WHAT = {"browser": "links and web pages", "files": "folders", "editor": "plain text files", "images": "pictures",
        "video": "videos", "music": "music and sound files", "pdf": "PDF documents", "mail": "mailto: links"}


def _plain(row, title=None, subtitle=None):
    """A combo row's title and subtitle, escaped (ctx.combo_row's rows show markup)."""
    if title is not None:
        row.set_title(GLib.markup_escape_text(title))
    if subtitle is not None:
        row.set_subtitle(GLib.markup_escape_text(subtitle))


class DefaultAppsPage:
    def __init__(self, ctx):
        self.ctx = ctx
        self.doc = None
        self.groups = []
        self.page = ctx.page()
        self.page.set_reset(self.reset, what="The terminal and the file manager bromigOS's keys start go back to "
                                             "bromigOS's (kitty, pcmanfm): the block in your hyprland.lua is removed. "
                                             "Which app opens a link or a file has no bromigOS default: it stays.")
        self.wait = ctx.group(self.page, "Opens with")
        self.groups.append(self.wait)
        self.wait_row = ctx.loading(self.wait, "Finding the apps installed…")
        self.refresh()

    def refresh(self):
        self.ctx.json(CMD + ["--json"], self._got)

    def _got(self, doc, err):
        if not doc or doc.get("ok") is False:
            self._clear()
            g = self._group("Opens with")
            self.ctx.failed(g, CMD + ["--json"], (doc or {}).get("error") or err)
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

    # ------------------------------------------------------------------ building
    def sync(self, d):
        self.doc = d
        self._clear()
        ctx = self.ctx
        g = self._group("Opens with", "The app the desktop opens each kind of file and link in: any app that asks "
                                      "(a browser, a file manager, a terminal's xdg-open) gets the same one.")
        for k in d["kinds"]:
            self._kind_row(g, k)

        g = self._group("bromigOS's keys", "What SUPER+RETURN, the menus and SUPER+E start.",
                        hint="Kept as bromigos.apps in a marked block of your hyprland.lua")
        t = d["terminal"]
        opts = [(c["id"], c["name"]) for c in t["candidates"]]
        cur = t["app"] if t["app"] in [o for o, _ in opts] else None
        if cur is None:
            opts = [("", t["command"] + " (not an installed app)")] + opts
            cur = ""
        r = ctx.combo_row(g, "Terminal", f"Starts: {t['command']}" + ("" if t["from"] != "bromigOS" else " (bromigOS's)"),
                          options=opts, current=cur, key="terminal",
                          on_select=lambda v, old=t: v and self._terminal(v, old),
                          hint="The terminal bromigOS's keys, menus and setups open (and $TERMINAL for apps "
                               "started from the desktop)",
                          advanced={"file": d["file"], "key": "-- >>> bromigos defaults: bromigos.apps.terminal",
                                    "runs": "bromigos defaults terminal APP",
                                    "note": f"also {t['xdg_terminals_file']} (xdg-terminal-exec)"})
        _plain(r, "Terminal", f"Starts: {t['command']}" + ("" if t["from"] != "bromigOS" else " (bromigOS's)"))
        r.add_prefix(ctx.icon(next((c["icon"] for c in t["candidates"] if c["id"] == t["app"]), ""),
                              "utilities-terminal-symbolic"))
        fk = d["files_key"]
        fm = next((k for k in d["kinds"] if k["kind"] == "files"), {"candidates": []})
        opts = [(c["id"], c["name"]) for c in fm["candidates"] if not c["hidden"]]
        cur = fk["app"] if fk["app"] in [o for o, _ in opts] else None
        if cur is None:
            opts = [("", fk["command"] + " (not an installed app)")] + opts
            cur = ""
        r = ctx.combo_row(g, "File manager's key", f"Starts: {fk['command']}" + ("" if fk["from"] != "bromigOS" else " (bromigOS's)"),
                          options=opts, current=cur, key="files-key",
                          on_select=lambda v, old=fk: v and self._files_key(v, old),
                          hint="The file manager bromigOS's key opens (the folders' app above is set with it)",
                          advanced={"file": d["file"], "key": "-- >>> bromigos defaults: bromigos.apps.files",
                                    "runs": "bromigos defaults files APP"})
        _plain(r, "File manager's key", f"Starts: {fk['command']}" + ("" if fk["from"] != "bromigOS" else " (bromigOS's)"))
        r.add_prefix(Gtk.Image.new_from_icon_name("system-file-manager-symbolic"))
        self.ctx.json(["bromigos", "shell", "--json"], lambda doc, err: self._prompt(g, doc, err))
        self._webapps(d["webapps"])

    def _kind_row(self, g, k):
        ctx = self.ctx
        cands = [c for c in k["candidates"] if not c["hidden"] or c["id"] == k["default"]]
        if not cands:
            r = ctx.row(g, k["title"], f"Nothing installed opens {WHAT[k['kind']]}", key=k["kind"],
                        hint=f"No installed app says it opens {', '.join(k['types'])}",
                        advanced={"key": ", ".join(k["types"]), "runs": f"bromigos defaults set {k['kind']} APP"})
            r.add_prefix(Gtk.Image.new_from_icon_name(ICONS[k["kind"]]))
            return
        opts = [(c["id"], c["name"]) for c in cands]
        cur = k["default"] if k["default"] in [o for o, _ in opts] else None
        if cur is None:
            opts = [("", "None set" if not k["default"] else f"{k['default']} (not installed)")] + opts
            cur = ""
        r = ctx.combo_row(g, k["title"], f"Opens {WHAT[k['kind']]}", options=opts, current=cur, key=k["kind"],
                          on_select=lambda v, kk=k: v and self._set(kk, v),
                          hint=f"The app that opens {WHAT[k['kind']]} ({', '.join(k['types'])})",
                          advanced={"file": "~/.config/mimeapps.list", "key": ", ".join(k["types"]),
                                    "runs": f"bromigos defaults set {k['kind']} APP",
                                    "note": "xdg-mime default APP TYPE…"})
        _plain(r, k["title"], f"Opens {WHAT[k['kind']]}")
        icon = next((c["icon"] for c in cands if c["id"] == k["default"]), "")
        r.add_prefix(ctx.icon(icon, ICONS[k["kind"]]))

    def _webapps(self, w):
        ctx = self.ctx
        g = self._group("Web apps", "A site as its own window, in the launcher and the menu (bromigos webapp).",
                        key="webapps")
        if not w["available"]:
            ctx.note(g, "bromigos webapp didn't answer: is bromigos-desktop installed?", "warn")
            return
        for a in w["yours"]:
            ctx.row(g, a["title"], a["url"] + (f"  ·  {a['hotkey']}" if a.get("hotkey") else ""),
                    hint=f"{a['title']}: opens {a['url']} in its own window",
                    buttons=[("Remove", lambda a=a: self._webapp_remove(a),
                              f"Removes {a['title']}: its launcher entry, its icon and its key")],
                    advanced={"file": "~/.config/bromigos/webapps.toml", "key": a["name"],
                              "runs": f"bromigos webapp remove {a['name']}"})
        if not w["yours"]:
            ctx.row(g, "No web apps yet", "Add one from the list below, or your own", hint="You have no web apps")
        left = [c for c in w["catalog"] if not c.get("added")]
        if left:
            dd = ctx.dropdown([(c["name"], c["title"]) for c in left], left[0]["name"],
                              hint="A ready-made web app to add", max_chars=20)
            add = ctx.button("Add", lambda: self._webapp_catalog(left[dd.get_selected()]),
                             "Adds the chosen web app (its icon is fetched from the site)")
            box = Gtk.Box(spacing=8)
            box.append(dd)
            box.append(add)
            ctx.row(g, "Add one", "Ready to add: " + ", ".join(c["title"] for c in left[:6]), key="webapp-catalog",
                    hint="Web apps bromigOS knows", control=box,
                    advanced={"runs": "bromigos webapp add --from-catalog NAME"})
        ctx.row(g, "Your own", "Any site, as its own window", key="webapp-add",
                hint="Adds a site of your choosing as a web app",
                buttons=[("Add…", self._webapp_dialog, "Asks for a name and the site's address")],
                advanced={"runs": "bromigos webapp add NAME URL"})

    # ------------------------------------------------------------------ changes
    def _set(self, k, app):
        old = k["default"]
        if app == old:
            return
        self.ctx.change(CMD + ["set", k["kind"], app, "--json"], lambda d: d.get("said") or "Changed",
                        undo=(CMD + ["set", k["kind"], old, "--json"]) if old else None,
                        done=self.sync, failed=lambda *_: self.refresh())

    def _prompt(self, group, doc, err):
        if not doc or doc.get("ok") is False:
            self.ctx.failed(group, ["bromigos", "shell", "--json"], err)
            return
        self.ctx.combo_row(group, "Prompt", "The zsh prompt. Open a new shell after changing it.",
                           options=[("mehshell", "mehshell"), ("starship", "Starship"), ("none", "None")],
                           current=doc["prompt"], key="prompt",
                           hint="Existing startup files keep their own prompt until you use bromigOS's zsh setup",
                           on_select=lambda v: self.ctx.change(
                               ["bromigos", "shell", "prompt", v, "--json"],
                               lambda d: d.get("said", "Prompt changed"),
                               undo=["bromigos", "shell", "prompt", doc["prompt"], "--json"],
                               done=lambda _: self.refresh(), failed=lambda *_: self.refresh()))

    def _terminal(self, app, old):
        if app == old.get("app"):
            return
        undo = CMD + (["terminal", old["app"] or old["command"], "--json"] if old["from"] != "bromigOS" else ["reset", "--json"])
        self.ctx.change(CMD + ["terminal", app, "--json"], lambda d: d.get("said") or "Terminal changed",
                        undo=undo, done=self.sync, failed=lambda *_: self.refresh())

    def _files_key(self, app, old):
        if app == old.get("app"):
            return
        self.ctx.change(CMD + ["files", app, "--json"], lambda d: d.get("said") or "File manager changed",
                        undo=CMD + ["files", old["app"] or old["command"], "--json"],
                        done=self.sync, failed=lambda *_: self.refresh())

    def _webapp_remove(self, a):
        self.ctx.confirm(f"Remove {a['title']}?", f"Its launcher entry, its icon and its key go; {a['url']} itself "
                                                  "isn't touched.", "Remove",
                         lambda: self.ctx.change(CMD + ["webapp-remove", a["name"], "--json"],
                                                 lambda d: d.get("said") or "Removed", done=self.sync),
                         destructive=True)

    def _webapp_catalog(self, c):
        self.ctx.toast(f"Adding {c['title']}…")
        self.ctx.change(CMD + ["webapp-catalog", c["name"], "--json"], lambda d: d.get("said") or "Added",
                        undo=CMD + ["webapp-remove", c["name"], "--json"], done=self.sync)

    def _webapp_dialog(self):
        d = Adw.AlertDialog(heading="Add a web app", body="A site in its own window, in the launcher and the menu.")
        box = Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE)
        box.add_css_class("boxed-list")
        name = Adw.EntryRow(title="Name (lowercase, e.g. notes)")
        url = Adw.EntryRow(title="Address (https://…)")
        self.ctx.hint(name, "A short name: lowercase letters, digits and -")
        self.ctx.hint(url, "The site's address, starting with https://")
        box.append(name)
        box.append(url)
        d.set_extra_child(box)
        d.add_response("cancel", "Cancel")
        d.add_response("add", "Add")
        d.set_response_appearance("add", Adw.ResponseAppearance.SUGGESTED)
        d.set_default_response("cancel")
        d.set_close_response("cancel")

        def done(_d, r):
            if r == "add":
                n, u = name.get_text().strip(), url.get_text().strip()
                self.ctx.change(CMD + ["webapp-add", n, u, "--json"], lambda doc: doc.get("said") or "Added",
                                undo=CMD + ["webapp-remove", n, "--json"], done=self.sync)
        d.connect("response", done)
        d.present(self.page.get_root())

    def reset(self):
        self.ctx.change(CMD + ["reset", "--json"], lambda d: d.get("said") or "Reset", done=self.sync)


def build(ctx):
    p = DefaultAppsPage(ctx)
    p.page._defaults = p
    return p.page


def refresh(widget):
    widget._defaults.refresh()


PAGE = Page(
    id="default-apps", title="Default apps", group="desktop", order=50, build=build, refresh=refresh,
    docs="settings.md#default-apps", icon="preferences-desktop-default-applications-symbolic preferences-desktop-default-applications application-x-executable-symbolic",
    summary="browser, terminal, files, web apps",
    intro="Which app opens links, folders, text, pictures and the rest; the terminal and file manager bromigOS's keys "
          "start; your web apps. A change applies at once.",
    keywords=["default applications", "open with", "mime", "xdg-mime", "handler"],
    entries=[
        Entry("browser", "Web browser", ["browser", "links", "http", "firefox", "chromium"], "Opens with"),
        Entry("files", "File manager", ["folders", "directories", "nautilus", "pcmanfm"], "Opens with"),
        Entry("editor", "Text editor", ["text files", "notepad", "plain text"], "Opens with"),
        Entry("images", "Image viewer", ["pictures", "photos", "png", "jpeg"], "Opens with"),
        Entry("video", "Video player", ["movies", "mp4", "mkv"], "Opens with"),
        Entry("music", "Music player", ["audio files", "mp3", "flac"], "Opens with"),
        Entry("pdf", "PDF viewer", ["documents", "pdf reader"], "Opens with"),
        Entry("mail", "Email", ["mailto", "mail client", "email client"], "Opens with"),
        Entry("terminal", "Terminal", ["terminal emulator", "kitty", "foot", "alacritty", "$TERMINAL", "console"],
              "bromigOS's keys"),
        Entry("prompt", "Prompt", ["zsh", "shell", "mehshell", "starship"], "bromigOS's keys"),
        Entry("files-key", "File manager's key", ["SUPER+E", "file manager shortcut"], "bromigOS's keys"),
        Entry("webapps", "Web apps", ["webapp", "pwa", "site as an app"], "Web apps"),
        Entry("webapp-catalog", "Add a web app", ["gmail", "youtube", "github", "chatgpt"], "Web apps"),
        Entry("webapp-add", "Your own web app", ["add a site", "custom web app"], "Web apps"),
    ])
