"""Startup: what starts when you log in (bromigOS's own, read from the defaults Hyprland
runs; yours, `bromigos.autostart` in a marked block of your hyprland.lua) and the floating
windows put back where they were (`bromigos windows`) (docs/settings.md, "Startup").

Everything goes through `bromigos startup … --json`; a change applies at once (your
hyprland.lua is saved the safe way; what starts at login starts at the next login) and
toasts Undo."""
from gi.repository import Adw, GLib, Gtk

from bromigos_settings import Entry, Page

CMD = ["bromigos", "startup"]


def _split(what, cmd):
    """(a title, the rest of the description): "the bar" -> ("The bar", "")."""
    if not what:
        return cmd.split()[0].rsplit("/", 1)[-1], ""
    head = what.split(":")[0].split("(")[0].split(",")[0].strip()
    rest = what[len(head):].strip(" :,").strip()
    if rest.startswith("(") and rest.endswith(")"):
        rest = rest[1:-1]
    return head[:1].upper() + head[1:], rest


class StartupPage:
    def __init__(self, ctx):
        self.ctx = ctx
        self.doc = None
        self.apps = None
        self.groups = []
        self.page = ctx.page()
        self.page.set_reset(self.reset, what="Nothing of yours starts at login any more (the block in your "
                                             "hyprland.lua is removed) and no floating windows are remembered "
                                             "(windows.toml removed). bromigOS's own keep starting.")
        g = ctx.group(self.page, "Starts at login")
        self.groups.append(g)
        ctx.loading(g, "Reading what starts…")
        self.refresh()
        ctx.json(["bromigos", "defaults", "apps", "--json"], self._got_apps)

    def refresh(self):
        self.ctx.json(CMD + ["--json"], self._got)

    def _got_apps(self, doc, _err):
        self.apps = (doc or {}).get("apps") or []
        if self.doc:
            self.sync(self.doc)

    def _got(self, doc, err):
        if not doc or doc.get("ok") is False:
            self._clear()
            g = self._group("Starts at login")
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
        g = self._group("Yours", "Started at login after bromigOS's own.", key="yours",
                        hint="bromigos.autostart, in a marked block of your hyprland.lua")
        mine = [i for i in d["yours"] if i["from"] == "block"]
        for n, i in enumerate(d["yours"]):
            if i["from"] == "block":
                ctx.row(g, i["name"], i["command"] if i["name"] != i["command"] else "",
                        hint=f"Runs `{i['command']}` at login",
                        buttons=[("Remove", lambda i=i: self._remove(i), f"{i['name']} no longer starts at login")],
                        advanced={"file": d["file"], "key": "-- >>> bromigos startup",
                                  "runs": f"bromigos startup remove {mine.index(i) + 1}"})
            else:
                ctx.row(g, i["name"], "in the bromigos table of your hyprland.lua: change it there",
                        hint="Set by hand in your hyprland.lua (autostart = { … }); edit it there",
                        buttons=[("Edit…", lambda: ctx.launch(["bromigos-setup-keybindings", "--edit"]),
                                  "Opens your hyprland.lua (a safe reload after)")])
        if not d["yours"]:
            ctx.row(g, "Nothing of yours yet", "Add an app or a command below", hint="You start nothing at login yet")
        # add an app
        apps = [a for a in (self.apps or []) if not a.get("hidden")]
        if apps:
            dd = ctx.dropdown([(a["id"], a["name"]) for a in apps], apps[0]["id"], max_chars=22,
                              hint="An installed app (type to find one)")
            dd.set_enable_search(True)
            dd.set_expression(Gtk.PropertyExpression.new(Gtk.StringObject, None, "string"))
            box = Gtk.Box(spacing=8)
            box.append(dd)
            box.append(ctx.button("Add", lambda: self._add_app(apps[dd.get_selected()]),
                                  "Starts the chosen app at every login"))
            ctx.row(g, "Add an app", "Starts it at every login", key="add-app",
                    hint="An installed app started at login (through its desktop entry)", control=box,
                    advanced={"runs": "bromigos startup add --app APP", "note": "runs gtk-launch APP at login"})
        else:
            ctx.row(g, "Add an app", "Finding the installed apps…" if self.apps is None else "No apps found",
                    key="add-app", hint="The installed apps (bromigos defaults apps)")
        ctx.entry_row(g, "Add a command", "", key="add-command", on_apply=self._add_command,
                      hint="A command line run at every login (Enter or the tick adds it)",
                      advanced={"runs": "bromigos startup add COMMAND"})

        g = self._group("bromigOS's own", "What bromigOS starts at every login. These come with it.", key="own",
                        hint=f"Read from {d['defaults']}")
        for o in d["own"]:
            title, rest = _split(o["what"], o["command"])
            sub = o["command"] + (f"  ·  {rest}" if rest else "") + (f"  ·  {o['when']}" if o.get("when") else "")
            r = ctx.row(g, title, sub,
                        hint=f"`{o['command']}` at every login ({o['file']} in bromigOS's defaults)")
            r.set_subtitle_lines(2)

        xdg = d["xdg_autostart"]
        if xdg:
            g = self._group("Autostart entries", "bromigOS doesn't run these (~/.config/autostart, /etc/xdg/autostart): "
                                                 "apps put them there for other desktops. Add one as yours to start it.",
                            key="xdg")
            ours = [x for x in xdg if not x["only_in"]]
            other = [x for x in xdg if x["only_in"]]
            for title, items, open_ in (("Any desktop", ours, len(ours) <= 6), ("Other desktops only", other, False)):
                if not items:
                    continue
                ex = Adw.ExpanderRow(title=GLib.markup_escape_text(title),
                                     subtitle=GLib.markup_escape_text(f"{len(items)}: " + ", ".join(x["name"] for x in items[:5])
                                                                      + ("…" if len(items) > 5 else "")))
                ex.set_expanded(open_)
                ctx.hint(ex, "Autostart entries bromigOS doesn't run: open to add one as yours"
                         if title == "Any desktop" else "Entries meant only for other desktops (GNOME, KDE …)")
                for x in items:
                    taken = any(i["command"] == x["command"] for i in d["yours"])
                    sub = x["command"] + (f"  ·  for {', '.join(x['only_in'])} only" if x["only_in"] else "")
                    r = Adw.ActionRow(title=GLib.markup_escape_text(x["name"]), subtitle=GLib.markup_escape_text(sub))
                    ctx.hint(r, f"{x['file']}: not started by bromigOS")
                    if not taken and x["command"]:
                        r.add_suffix(ctx.button("Add as yours", lambda x=x: self._add(x["command"], x["name"]),
                                                f"Starts {x['name']} at every login, as one of yours"))
                    ex.add_row(r)
                g.add(ex)

        self._windows(d["windows"])

    def _windows(self, w):
        ctx = self.ctx
        g = self._group("Windows put back", "Floating windows of these apps open where you last left them, on the "
                                           "same workspace (bromigos windows).", key="windows",
                        hint=f"{w['file']}; where they were: {w['state']}")
        adv = {"file": w["file"], "key": "all", "runs": "bromigos startup windows all on|off"}
        ctx.switch_row(g, "Every floating window", "Whatever the app", active=w["all"], key="windows-all",
                       hint="Remembers every floating window, not only the apps listed",
                       on_toggle=lambda on: self._change(["windows", "all", "on" if on else "off"],
                                                         ["windows", "all", "off" if on else "on"]),
                       advanced=adv)
        for cls in w["remember"]:
            ctx.row(g, cls, "its floating windows go back where they were",
                    hint=f"The app class {cls} (hyprctl clients shows an app's class)",
                    buttons=[("Forget", lambda c=cls: self._change(["windows", "forget-class", c],
                                                                     ["windows", "remember", c]),
                              f"Stops remembering {cls}'s windows")],
                    advanced={"file": w["file"], "key": "remember", "runs": f"bromigos startup windows forget-class {cls}"})
        ctx.entry_row(g, "Remember an app (its class)", "", key="windows-remember",
                      on_apply=lambda c: c.strip() and self._change(["windows", "remember", c.strip()],
                                                                    ["windows", "forget-class", c.strip()]),
                      hint="An app's class, e.g. org.pulseaudio.pavucontrol (hyprctl clients lists them)",
                      advanced={"file": w["file"], "key": "remember", "runs": "bromigos startup windows remember CLASS"})
        places = w["remembered"]
        ctx.row(g, "Remembered now", f"{len(places)} window place{'s' if len(places) != 1 else ''}" if places
                    else "nothing yet", key="windows-places",
                    hint="Where each remembered window was last, per workspace",
                    buttons=[("Forget all", lambda: self._change(["windows", "clear"], None),
                              "Forgets every remembered place")] if places else [],
                    advanced={"file": w["state"], "runs": "bromigos startup windows clear [CLASS…]"})
        for p in places[:12]:
            ctx.row(g, f"{p['class']}", f"workspace {p['workspace']} · {p['w']}×{p['h']} at {p['x']},{p['y']}",
                    hint=f"{p['class']} on workspace {p['workspace']}" + (f", saved {p['saved']}" if p.get("saved") else ""),
                    buttons=[("Forget", lambda c=p["class"]: self._change(["windows", "clear", c], None),
                              f"Forgets where {p['class']}'s windows were")])
        state = "running" if w["running"] else "not running"
        ctx.row(g, "bromigos-windows", f"{state}: it reads windows.toml when it starts", key="windows-daemon",
                hint="The small daemon that puts windows back (started at login when there's something to remember)",
                buttons=[("Restart", lambda: self._change(["windows", "restart"], None),
                          "Starts it again so it reads windows.toml now")],
                advanced={"runs": "bromigos startup windows restart"})

    # ------------------------------------------------------------------ changes
    def _change(self, args, undo_args):
        self.ctx.change(CMD + args + ["--json"], lambda d: d.get("said") or "Changed",
                        undo=(CMD + undo_args + ["--json"]) if undo_args else None,
                        done=self.sync, failed=lambda *_: self.refresh())

    def _add(self, command, name):
        self.ctx.change(CMD + ["add", command, "--name", name, "--json"], lambda d: d.get("said") or "Added",
                        undo=CMD + ["remove", command, "--json"], done=self.sync)

    def _add_app(self, a):
        self.ctx.change(CMD + ["add", "--app", a["id"], "--json"], lambda d: d.get("said") or "Added",
                        undo=CMD + ["remove", f"gtk-launch {a['id']}", "--json"], done=self.sync)

    def _add_command(self, text):
        text = text.strip()
        if text:
            self.ctx.change(CMD + ["add", text, "--json"], lambda d: d.get("said") or "Added",
                            undo=CMD + ["remove", text, "--json"], done=self.sync)

    def _remove(self, i):
        self.ctx.change(CMD + ["remove", i["command"], "--json"], lambda d: d.get("said") or "Removed",
                        undo=CMD + ["add", i["command"], "--name", i["name"], "--json"], done=self.sync)

    def reset(self):
        self.ctx.change(CMD + ["reset", "--json"], lambda d: d.get("said") or "Reset", done=self.sync)


def build(ctx):
    p = StartupPage(ctx)
    p.page._startup = p
    return p.page


def refresh(widget):
    widget._startup.refresh()


PAGE = Page(
    id="startup", title="Startup", group="desktop", order=55, build=build, refresh=refresh, docs="settings.md#startup",
    icon="system-run-symbolic media-playback-start-symbolic", summary="apps at login, windows put back",
    intro="What starts when you log in, bromigOS's own and yours, and the floating windows put back where you left "
          "them. What you add starts at the next login.",
    keywords=["autostart", "login items", "startup applications", "session"],
    entries=[
        Entry("yours", "Apps that start at login", ["autostart", "login items", "startup apps"], "Yours"),
        Entry("add-app", "Start an app at login", ["add autostart", "launch at login"], "Yours"),
        Entry("add-command", "Run a command at login", ["autostart command", "login script"], "Yours"),
        Entry("own", "What bromigOS starts", ["waybar", "dunst", "live layer", "panels at login"], "bromigOS's own"),
        Entry("windows", "Windows put back where they were", ["remember window position", "floating windows",
                                                               "window placement", "bromigos windows"],
              "Windows put back"),
        Entry("windows-all", "Remember every floating window", ["all windows"], "Windows put back"),
        Entry("windows-remember", "Remember an app's windows", ["window class", "pavucontrol"], "Windows put back"),
        Entry("windows-places", "Remembered window places", ["forget window positions", "clear"], "Windows put back"),
        Entry("windows-daemon", "bromigos-windows", ["restart windows daemon"], "Windows put back"),
    ])
