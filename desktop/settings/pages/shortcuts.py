"""Shortcuts: every key, and changing one by pressing it.

Everything goes through `bromigos keys … --json` (the rules live there: clashes, the
lockout guard, the safe save; docs/desktop.md, "Shortcuts you set by pressing the keys").
Change… opens its "press the new shortcut" window; a change applies at once and leaves a
toast with Undo (`bromigos keys undo`). Without `bromigos keys` installed the page says so and shows the other ways."""
import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gtk  # noqa: E402

from bromigos_settings import Entry, Page  # noqa: E402

KEYS = ["bromigos", "keys"]
SECTION_NAMES = {"VECTOR": "VECTOR", "HOLOGRAMS": "Holograms", "PANELS + NOTES": "Panels and notes",
                 "LIVE LAYER": "Live layer", "YOURS": "Yours", "LAUNCH": "Launch", "CAPTURE": "Capture",
                 "WINDOWS": "Windows", "WORKSPACES": "Workspaces", "MEDIA": "Media", "SYSTEM": "System"}


class ShortcutsPage:
    def __init__(self, ctx):
        self.ctx = ctx
        self.page = ctx.page()
        self.page.set_reset(self.reset_all, ask=False, hint="Every bromigOS key back on its own key, and your "
                                                          "shortcuts removed (asks first; Undo after)")
        self.groups = []
        self.doc = None
        self.busy = False
        if ctx.has_command("keys"):
            self.reload()
        else:
            self._without_picker()

    # ------------------------------------------------------------------ data
    def reload(self):
        self.ctx.json(KEYS + ["list", "--all", "--json"], self._got)

    def _got(self, doc, err):
        self.doc = doc
        self._build(err)

    # ------------------------------------------------------------------ building
    def _clear(self):
        for g in self.groups:
            self.page.remove_group(g)
        self.groups = []

    def _group(self, title, description=None, hint=None, key=None):
        g = self.ctx.group(self.page, title, description, hint, key=key)
        self.groups.append(g)
        return g

    def _build(self, err=None):
        self._clear()
        ctx = self.ctx
        doc = self.doc or {}
        yours, off, every = doc.get("binds") or [], doc.get("off") or [], doc.get("all") or []
        g = self._group("Change a key", "Change… opens a small window: press the new keys there. "
                        "Taken keys are caught, and the old ones can be swapped or replaced.",
                        hint="The shortcut picker (bromigos keys)")
        ctx.row(g, "Bind something new", "Anything in the menu, an app, a web app or a command of your own",
                hint="Opens the picker: choose what to bind, then press its keys", key="bind-new",
                advanced={"file": "~/.config/bromigos/keys.toml", "runs": "bromigos keys",
                          "note": "written into your hyprland.lua's marked blocks, then one verified reload"},
                buttons=[("Bind…", self.picker, "Opens the shortcut picker (bromigos keys)")])
        n_yours, n_off = len(yours), len(off)
        said = (f"{n_yours} shortcut{'s' if n_yours != 1 else ''} of yours, "
                f"{n_off} default{'s' if n_off != 1 else ''} turned off") if (n_yours or n_off) else \
            "Every key is bromigOS's own"
        reset = ctx.button("Reset…", self.reset_all, "Puts every bromigOS key back and removes yours (Undo after)",
                           destructive=True)
        reset.set_sensitive(bool(n_yours or n_off))
        r = ctx.row(g, "Reset to bromigOS's keys", said, hint="Every default back on its key, your shortcuts gone",
                    key="reset", advanced={"runs": "bromigos keys reset --yes"})
        r.add_suffix(reset)
        if self.doc is None:
            ctx.note(g, f"bromigos keys didn't answer: {err or 'no reply'}", "error")
        elif not every:
            ctx.note(g, "bromigos keys found no keys: your ~/.config/hypr/hyprland.lua doesn't load bromigOS's "
                        "defaults, or they aren't installed (bromigos-desktop)", "warn",
                     hint="Check: bromigos keys list --all")

        if yours:
            g = self._group("Yours", "The shortcuts you made, and bromigOS keys you moved",
                            hint="Kept in ~/.config/bromigos/keys.toml (web apps' in webapps.toml)", key="yours")
            for b in yours:
                sub = b["display"]
                if b.get("from"):
                    sub += f"  ·  moved from {b['from']}"
                if b.get("source") == "webapp":
                    sub += "  ·  a web app's key"
                buttons = [("Change…", lambda b=b: self.change(b["keys"], b["what"]),
                            f"Press a new key for {b['what']}")]
                if b.get("from"):
                    buttons.append(("Put back", lambda b=b: self.put_back(b["from"], b["what"]),
                                    f"{b['what']} goes back on {b['from']}"))
                buttons.append(("Remove", lambda b=b: self.remove(b["keys"], b["what"]),
                                f"Takes {b['display']} off" + (": it has no key then" if b.get("from") else "")))
                ctx.row(g, b["what"], sub, hint=f"{b['display']}: {b['what']}", buttons=buttons)

        if off:
            g = self._group("Turned off", "bromigOS keys you turned off (or gave away)",
                            hint="Listed in bromigos.unbind by bromigos keys")
            for o in off:
                ctx.row(g, o["what"], f"was {o['display']}", hint=f"{o['what']} has no key",
                        buttons=[("Put back", lambda o=o: self.put_back(o["keys"], o["what"]),
                                  f"{o['what']} goes back on {o['display']}"),
                                 ("Change…", lambda o=o: self.change(o["keys"], o["what"], default=True),
                                  f"Press a new key for {o['what']}")])

        if every:
            g = self._group("Every key", "As the SHORTCUTS panel lists them (SUPER+K), from your config",
                            hint="Open a section to see its keys; Change… moves one", key="every")
            sections, order = {}, []
            for r in every:
                if r["section"] not in sections:
                    sections[r["section"]] = []
                    order.append(r["section"])
                sections[r["section"]].append(r)
            for sec in order:
                rows = sections[sec]
                ex = Adw.ExpanderRow(title=SECTION_NAMES.get(sec, sec.title()),
                                     subtitle=f"{len(rows)} key{'s' if len(rows) != 1 else ''}")
                ctx.hint(ex, f"The {SECTION_NAMES.get(sec, sec).lower()} keys: open to see and change them")
                for r in rows:
                    row = Adw.ActionRow(title=r["what"], subtitle=r["display"])
                    row.set_subtitle_lines(2)
                    if r["movable"]:
                        row.add_suffix(ctx.button("Change…", lambda r=r: self.change(r["keys"], r["what"]),
                                                  f"Press a new key for {r['what']} (now {r['display']})"))
                        ctx.hint(row, f"{r['display']}: {r['what']}" +
                                 (" (yours)" if r["source"] in ("yours", "webapp") else " (bromigOS's)"))
                    else:
                        lab = Gtk.Label(label="in your config" if r["source"] == "config" else "fixed")
                        lab.add_css_class("dim-label")
                        row.add_suffix(ctx.hint(lab, r.get("why") or "Not changed from here"))
                        ctx.hint(row, f"{r['display']}: {r['what']}. {r.get('why') or ''}".strip())
                    ex.add_row(row)
                g.add(ex)

        g = self._group("See them")
        self._see_them(g)

    def _see_them(self, g):
        ctx = self.ctx
        ctx.row(g, "Shortcuts panel", "Every key on the desktop, from your own config (SUPER+K)",
                hint="Shows or hides the SHORTCUTS panel", key="panel",
                buttons=[("Show", lambda: ctx.launch(["bromigos-widgets", "toggle", "shortcuts"]), "SUPER+K")])
        ctx.row(g, "Search them", "Type to find a key; Enter runs it (SUPER+SHIFT+K)", hint="Opens the searchable list",
                key="search-keys",
                buttons=[("Search", lambda: ctx.launch(["python3", "/usr/lib/bromigos/widgets/keybinds.py", "rofi"]),
                          "SUPER+SHIFT+K")])
        ctx.row(g, "Edit them by hand", "Your binds in ~/.config/hypr/hyprland.lua, checked before Hyprland loads them",
                hint="Opens SETUP › Keybindings", key="by-hand",
                buttons=[("Edit", lambda: ctx.launch(["bromigos-setup-keybindings", "--edit"]),
                          "Opens your hyprland.lua (auto-reload off, one verified reload after)")])
        ctx.row(g, "Settings", "SUPER+, (comma) opens this window", hint="The key for Settings")

    def _without_picker(self):
        ctx = self.ctx
        ctx.placeholder(self.page, "Change a key",
                        "The shortcut picker (bromigos keys) isn't installed: update bromigOS "
                        "(bromigos update) to press new keys here. Until then, edit your hyprland.lua (below).",
                        hint="bromigos keys comes with bromigos-desktop")
        self._see_them(ctx.group(self.page, "See them"))

    # ------------------------------------------------------------------ changes
    def _apply(self, argv, undo=True, retry_yes=None):
        """Runs a `bromigos keys … --json` change; a toast says what changed (with Undo)."""
        if self.busy:
            self.ctx.toast("Another change is still going")
            return
        self.busy = True

        def done(doc, err):
            self.busy = False
            doc = doc or {}
            if doc.get("ok"):
                notes = doc.get("notes") or [doc.get("detail") or "Saved"]
                self.ctx.toast("; ".join(notes)[:160], self.undo if undo else None, timeout=8)
            elif doc.get("cancelled"):
                pass
            elif doc.get("confirm") and retry_yes:
                self._confirm(doc.get("error") or "Are you sure?", retry_yes)
            else:
                self.ctx.toast(f"Not changed: {doc.get('error') or doc.get('detail') or err or 'bromigos keys failed'}",
                               timeout=10)
            self.reload()
        self.ctx.json(KEYS + argv + ["--json"], done)

    def _confirm(self, why, then):
        d = Adw.AlertDialog(heading="Are you sure?", body=why[:1].upper() + why[1:] + ".")
        d.add_response("cancel", "Cancel")
        d.add_response("yes", "Do it anyway")
        d.set_response_appearance("yes", Adw.ResponseAppearance.DESTRUCTIVE)
        d.set_default_response("cancel")
        d.set_close_response("cancel")
        d.connect("response", lambda _d, r: r == "yes" and then())
        d.present(self.page.get_root())

    def picker(self):
        self.ctx.run(KEYS, lambda ok, out, err: self.reload())

    def change(self, keys, what, default=False):
        self._apply(["bind", "--default" if default else "--from", keys])

    def remove(self, keys, what):
        self._apply(["unbind", keys], retry_yes=lambda: self._apply(["unbind", keys, "--yes"]))

    def put_back(self, keys, what):
        self._apply(["reset", keys])

    def reset_all(self):
        self._confirm("every bromigOS key goes back on its own key, and your shortcuts are removed "
                      "(Undo puts them back)", lambda: self._apply(["reset", "--yes"]))

    def undo(self):
        self._apply(["undo"], undo=False)

    def refresh(self):
        if self.ctx.has_command("keys"):
            self.reload()


def build(ctx):
    p = ShortcutsPage(ctx)
    p.page._shortcuts = p
    return p.page


def refresh(widget):
    widget._shortcuts.refresh()


PAGE = Page(id="shortcuts", title="Shortcuts", icon="input-keyboard-symbolic preferences-desktop-keyboard-shortcuts-symbolic", order=30,
            group="desktop", docs="keys.md", summary="every key; press new ones",
            intro="Every key on the desktop, by section. Change… opens a small window: press the new keys there. "
                  "Each change applies at once (a verified Hyprland reload) and can be undone.",
            keywords=["keys", "keybindings", "binds", "hotkeys", "rebind"],
            entries=[Entry("bind-new", "Bind a new shortcut", ["new shortcut", "custom shortcut", "add a key"],
                           "Change a key"),
                     Entry("reset", "Reset every key", ["default keys", "restore shortcuts"], "Change a key"),
                     Entry("every", "Every key", ["list of shortcuts", "keymap", "cheat sheet"], "Every key"),
                     Entry("panel", "The shortcuts panel", ["SUPER+K", "keys panel"], "See them"),
                     Entry("search-keys", "Search the keys", ["find a shortcut"], "See them"),
                     Entry("by-hand", "Edit binds by hand", ["hyprland.lua", "config file"], "See them")],
            build=build, refresh=refresh)
