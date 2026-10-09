"""Extensions: what's installed from git (themes, decks, widgets, VECTOR's tools, homelab
adapters, commands, hooks), the updates waiting, and the catalogs (`bromigos ext`;
docs/extensions.md; docs/settings.md, "Extensions").

Enable, disable, remove and installing a theme run here (`bromigos ext … --json`). An
update shows what changed and any new permissions first, and installing anything that
runs code needs a yes from you at a terminal: those open a terminal with the command.

The rows are the extensions window's (`bromigos extensions`, the launcher's): one list from
bromigos_extlist, so both show the same extensions with the same names and actions."""
import os
import sys

from gi.repository import GLib, Gtk

from bromigos_settings import Entry, Page

for _p in (os.path.join(os.path.dirname(os.path.realpath(__file__)), "..", "..", "lib"), "/usr/lib/bromigos/lib"):
    if os.path.isfile(os.path.join(_p, "bromigos_extlist.py")):
        sys.path.insert(0, _p)
        break
from bromigos_extlist import kinds_text as _kinds, merge  # noqa: E402

CMD = ["bromigos", "ext"]


class ExtensionsPage:
    def __init__(self, ctx):
        self.ctx = ctx
        self.page = ctx.page()
        self.page.set_reset(None, hint="Extensions have no bromigOS default: remove or turn off each one here")
        self.installed = self.updates = self.catalog = None
        self.all_catalog = None            # the unfiltered catalog: the installed ones' names and words
        self.term = ""
        self.inst_group = ctx.group(self.page, "Installed", "From git: each checked against its ledger.",
                                    key="installed")
        self.inst_rows = [ctx.loading(self.inst_group, "Reading what's installed…")]
        self.cat_group = ctx.group(self.page, "The catalogs", "Extensions bromigOS's catalog (and yours, ext.toml) "
                                                              "lists. A theme installs at once; anything that runs code "
                                                              "asks you at a terminal first.", key="catalog")
        self.cat_rows = [ctx.loading(self.cat_group, "Reading the catalogs (fetched every six hours)…")]
        self.refresh()

    def refresh(self):
        self.ctx.json(CMD + ["list", "--json"], lambda d, e: self._got("installed", d, e))
        self.ctx.json(CMD + ["update", "--all", "--check", "--json"], lambda d, e: self._got("updates", d, e))
        self._search()

    def _search(self):
        self.ctx.json(CMD + ["search"] + ([self.term] if self.term else []) + ["--json"],
                      lambda d, e: self._got("catalog", d, e))

    def _got(self, what, doc, err):
        if not doc or doc.get("ok") is False:
            doc = {"_error": (doc or {}).get("error") or err or "no answer"}
        setattr(self, what, doc)
        if what == "catalog" and not self.term and not doc.get("_error"):
            self.all_catalog = doc
            if self.installed is not None and self.updates is not None:
                self._installed()
        if what == "catalog":
            self._catalog()
        elif self.installed is not None and self.updates is not None:
            self._installed()

    # ------------------------------------------------------------------ installed
    def _installed(self):
        ctx = self.ctx
        g = self.inst_group
        ctx.clear_group(g, self.inst_rows)
        rows = self.inst_rows
        if self.installed.get("_error"):
            rows.append(ctx.failed(g, CMD + ["list", "--json"], self.installed["_error"]))
            return
        lst = self.installed.get("list") or {}
        exts, _errors = merge(self.installed, self.all_catalog or {})
        exts = [e for e in exts if e["installed"]]
        ups = {u["name"]: u for u in (self.updates or {}).get("updates") or []
               if u.get("ok") and (u.get("result") or {}).get("op") not in (None, "current")}
        if ups:
            rows.append(ctx.row(g, f"{len(ups)} update{'s' if len(ups) != 1 else ''} waiting",
                                ", ".join(ups), key="updates",
                                hint="Each update shows what changed and any new permissions first, in a terminal",
                                buttons=[("Update all…", lambda: self._terminal(["update", "--all"]),
                                          "bromigos ext update --all, in a terminal")],
                                advanced={"runs": "bromigos ext update --all"}))
        else:
            rows.append(ctx.row(g, "Updates", "everything is up to date" if not (self.updates or {}).get("_error")
                                else f"couldn't check: {self.updates['_error']}", key="updates",
                                hint="bromigos ext update --all --check: what an update would change",
                                advanced={"runs": "bromigos ext update --all --check"}))
        for e in exts:
            up = ups.get(e["name"])
            sub = f"{_kinds(e['kinds'])} · {e.get('version') or '?'}" + (f" · {e['what']}" if e["what"] and
                                                                          e["what"] != e.get("source") else "")
            if e.get("status") not in ("ok", "disabled"):
                sub += f" · {e.get('status')}"
            if up:
                sub += f" · update: {(up.get('result') or {}).get('detail', '')}"
            buttons = []
            if up:
                buttons.append(("Update…", lambda e=e: self._terminal(["update", e["name"]]),
                                f"bromigos ext update {e['name']}, in a terminal: it shows what changed first"))
            buttons.append(("Remove", lambda e=e: self._remove(e), f"Removes {e['name']}: its links and its checkout"))
            sw = Gtk.Switch(active=bool(e.get("enabled")), valign=Gtk.Align.CENTER)
            ctx.hint(sw, f"{e['name']} on or off (off: its parts unlinked, its checkout kept)")
            sw.connect("notify::active", lambda s, _p, e=e: self._enable(e, s.get_active()))
            box = Gtk.Box(spacing=6)
            for label, cb, h in buttons:
                box.append(ctx.button(label, cb, h))
            box.append(sw)
            r = ctx.row(g, e["title"], sub, hint=f"{e['name']} from {e.get('source') or '?'}", control=box,
                        advanced={"file": "~/.local/state/bromigos/ext/ledger.json", "key": e["name"],
                                  "runs": f"bromigos ext enable|disable|remove {e['name']}",
                                  "note": f"source {e.get('source') or '?'}"})
            rows.append(r)
        if not exts:
            rows.append(ctx.row(g, "Nothing installed yet", "Pick one from the catalogs below",
                                hint="No extension is installed"))
        um = lst.get("unmanaged_themes") or []
        if um:
            rows.append(ctx.row(g, "Themes of yours not from an extension", ", ".join(um), key="migrate",
                                hint="Themes copied into ~/.config/bromigos/themes before extensions: one a catalog "
                                     "has can become an extension that updates",
                                buttons=[("Migrate…", lambda: self._terminal(["migrate"]),
                                          "bromigos ext migrate, in a terminal")],
                                advanced={"runs": "bromigos ext migrate"}))

    # ------------------------------------------------------------------ the catalogs
    def _catalog(self):
        ctx = self.ctx
        g = self.cat_group
        ctx.clear_group(g, self.cat_rows)
        rows = self.cat_rows
        rows.append(ctx.entry_row(g, "Search the catalogs", self.term, key="search",
                                  on_apply=self._searched,
                                  hint="Words to find an extension by (its name, what it is); empty: all of them",
                                  advanced={"runs": "bromigos ext search TERM"}))
        c = self.catalog or {}
        if c.get("_error"):
            rows.append(ctx.failed(g, CMD + ["search", "--json"], c["_error"]))
            return
        for err in c.get("errors") or []:
            rows.append(ctx.note(g, f"A catalog didn't answer: {err}", "warn"))
        items, _errors = merge({}, c)                  # the installed ones are in the group above
        for r in items:
            theme = r["theme"]
            cmd = " ".join(r["install"] or ["bromigos", "ext", "install", r["name"]])
            sub = f"{_kinds(r.get('kinds'))} · {r.get('what') or ''}"
            if r.get("bundled"):
                buttons, state = [], "comes with bromigOS"
            elif theme:
                buttons, state = [("Install", lambda r=r: self._install(r), f"Installs the {r['name']} theme now")], ""
            else:
                buttons, state = [("Install in a terminal…", lambda r=r: self._terminal(["install", r["name"]]),
                                   f"{cmd}: it runs code, so it shows its permissions and asks you there")], ""
            row = ctx.row(g, r["title"], sub + (f" · {state}" if state else ""),
                          hint=(f"{r['name']}: {r.get('what') or ''}" +
                                ("" if theme or state else f" Installing runs: {cmd}")),
                          buttons=buttons, advanced={"runs": cmd, "note": r.get("source") or ""})
            row.set_subtitle_lines(2)
            rows.append(row)
        if not items:
            rows.append(ctx.row(g, "Nothing found", "No catalog lists anything with those words", hint="Try other words"))

    def _searched(self, text):
        self.term = text.strip()
        self._search()

    # ------------------------------------------------------------------ changes
    def _terminal(self, args):
        self.ctx.terminal(CMD + args)
        self.ctx.toast(f"In a terminal: bromigos ext {' '.join(args)}", timeout=6)
        GLib.timeout_add_seconds(10, lambda: (self.refresh(), False)[1])

    def _enable(self, e, on):
        self.ctx.change(CMD + ["enable" if on else "disable", e["name"], "--json"],
                        lambda d: (d.get("result") or {}).get("detail") or f"{e['name']}: {'on' if on else 'off'}",
                        undo=CMD + ["disable" if on else "enable", e["name"], "--json"],
                        done=lambda _d: self.refresh(), failed=lambda *_: self.refresh())

    def _remove(self, e):
        self.ctx.confirm(f"Remove {e['name']}?", f"Its links and its checkout go (the ledger keeps a line). "
                                                 f"Installing it again: bromigos ext install {e['name']}.", "Remove",
                         lambda: self.ctx.change(CMD + ["remove", e["name"], "--json"],
                                                 lambda d: (d.get("result") or {}).get("detail") or "Removed",
                                                 done=lambda _d: self.refresh()), destructive=True)

    def _install(self, r):
        self.ctx.toast(f"Installing {r['name']}…")
        self.ctx.change(CMD + ["install", r["name"], "--json"],
                        lambda d: (d.get("result") or {}).get("detail") or f"Installed {r['name']}",
                        undo=CMD + ["remove", r["name"], "--json"], done=lambda _d: self.refresh())


def build(ctx):
    p = ExtensionsPage(ctx)
    p.page._ext = p
    return p.page


def refresh(widget):
    widget._ext.refresh()


PAGE = Page(
    id="extensions", title="Extensions", group="desktop", order=60, build=build, refresh=refresh,
    docs="settings.md#extensions", icon="application-x-addon-symbolic system-software-install-symbolic",
    summary="installed, updates, the catalog",
    intro="Themes, decks, widgets, VECTOR's tools and more, from git. Anything that runs code asks you at a terminal "
          "before it's installed.",
    keywords=["extensions", "plugins", "addons", "bromigos ext", "catalog", "themes from git"],
    entries=[
        Entry("installed", "Installed extensions", ["enable extension", "disable extension", "remove extension"],
              "Installed"),
        Entry("updates", "Extension updates", ["update extensions", "updates available"], "Installed"),
        Entry("catalog", "The extension catalog", ["browse extensions", "get more", "install extension"],
              "The catalogs"),
        Entry("search", "Search the catalogs", ["find an extension"], "The catalogs"),
    ])
