"""Peripherals: the optional modules for a keyboard with macro keys, a dial and lighting
(`bromigos peripheral`; docs/peripherals.md): each module on or off, its device, its keys
and what each does, its dial, and what its lighting follows (docs/settings.md,
"Peripherals").

Turning a module on installs its packages and joins its group the first time: that needs
your password, so it runs in a terminal; once they're in place it's one click. Off, the
lighting's choice and Refresh are `bromigos peripheral … --json`, with Undo."""
from gi.repository import Adw, GLib

from bromigos_settings import Entry, Page

CMD = ["bromigos", "peripheral"]
FOLLOW = [("vector", "VECTOR (his voice and mood)"), ("theme", "The theme (its primary)")]


def _needs_root(m):
    n = m.get("needs") or {}
    return any(not p.get("installed") for p in n.get("packages") or []) or \
        any(not g.get("member") for g in n.get("groups") or [])


class PeripheralsPage:
    def __init__(self, ctx):
        self.ctx = ctx
        self.doc = None
        self.groups = []
        self.page = ctx.page()
        self.page.set_reset(None, hint="Modules are off until you turn one on; turn one off here. Your key changes "
                                       "stay in peripherals.toml")
        g = ctx.group(self.page, "Modules")
        self.groups.append(g)
        ctx.loading(g, "Looking for peripherals…")
        self.refresh()

    def refresh(self):
        self.ctx.json(CMD + ["list", "--json"], self._got)

    def _got(self, doc, err):
        if not doc or doc.get("ok") is False:
            self._clear()
            self.ctx.failed(self._group("Modules"), CMD + ["list", "--json"], (doc or {}).get("error") or err)
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

    def sync(self, d):
        self.doc = d
        self._clear()
        ctx = self.ctx
        mods = d.get("modules") or []
        if d.get("config_error"):
            ctx.note(self._group("Your settings"), f"{d.get('config')}: {d['config_error']}", "error")
        if not mods:
            g = self._group("Modules", key="modules")
            ctx.row(g, "No modules", "bromigOS has none for a device here", hint="Modules: /usr/share/bromigos/peripherals")
        for n, m in enumerate(mods):
            self._module(m, first=n == 0)
        for b in d.get("broken") or []:
            g = self._group("A module that didn't load")
            ctx.note(g, f"{b.get('dir') or b.get('id')}: {b.get('error') or b}", "error")
        g = self._group("Keys and devices", "After editing peripherals.toml, or plugging in another keyboard.",
                        key="refresh")
        ctx.row(g, "Refresh", "Writes the keys again from peripherals.toml and the devices here",
                hint="bromigos peripheral refresh: Hyprland reloads only when the keys changed",
                buttons=[("Refresh", lambda: ctx.change(CMD + ["refresh", "--json"],
                                                        lambda doc: doc.get("detail") or "Keys written",
                                                        done=lambda _d: self.refresh()), "Writes the keys again")],
                advanced={"file": d.get("config") or "~/.config/bromigos/peripherals.toml",
                          "runs": "bromigos peripheral refresh"})
        ctx.row(g, "Your settings", d.get("config") or "~/.config/bromigos/peripherals.toml",
                hint="Change a key's command, the lighting's reach, the dial: then Refresh",
                buttons=[("Open", lambda: ctx.open_file(d.get("config") or "~/.config/bromigos/peripherals.toml"),
                          "Opens peripherals.toml in your editor")])

    def _module(self, m, first):
        ctx = self.ctx
        found = m.get("found") or []
        dev = found[0]["name"] if found else None
        g = self._group(m["name"], m.get("description"), key="modules" if first else None,
                        hint=f"The {m['id']} module ({m.get('source', 'system')}: {m.get('dir', '')})")
        root = _needs_root(m)
        sub = (f"{dev}: connected" if dev else "not connected now") + (" · on" if m.get("enabled") else "")
        if root and not m.get("enabled"):
            sub += " · the first time needs your password (a terminal opens)"
        ctx.switch_row(g, "On", sub, active=bool(m.get("enabled")), key=f"on-{m['id']}" if not first else "on",
                       hint=f"Turns the {m['name']} module on (its keys bound, the dial and lighting started) or off",
                       on_toggle=lambda on, m=m: self._enable(m, on),
                       advanced={"file": "~/.config/bromigos/peripherals.toml", "key": f"[{m['id']}] enabled",
                                 "runs": f"bromigos peripheral enable|disable {m['id']}"})
        rgb = m.get("rgb")
        if rgb:
            r = ctx.combo_row(g, "Lighting follows", "", options=FOLLOW,
                          current=rgb.get("follow") or "vector", key=f"follow-{m['id']}" if not first else "follow",
                          on_select=lambda v, m=m, old=rgb.get("follow") or "vector": self._follow(m, v, old),
                          hint="What the keyboard's lighting shows: VECTOR's voice and mood, or the theme's colour",
                          advanced={"file": "~/.config/bromigos/peripherals.toml", "key": f"[{m['id']}] rgb_follow",
                                    "runs": f"bromigos peripheral follow {m['id']} vector|theme"})
            r.set_subtitle((rgb.get("hint") or "").replace("&", "and").replace("<", "").replace(">", ""))
        dial = m.get("dial")
        if dial:
            ctx.row(g, "The dial", dial.get("hint") or "", key=f"dial-{m['id']}" if not first else "dial",
                    hint="What the dial does (peripherals.toml: [module] dial = false turns it off)")
        keys = m.get("keys") or []
        if keys:
            ex = Adw.ExpanderRow(title="Keys", subtitle=f"{len(keys)} keys: what each does")
            ex._bromigos_key = f"keys-{m['id']}" if not first else "keys"
            ctx.hint(ex, "The module's keys and what each runs (change one in peripherals.toml, then Refresh)")
            for k in keys:
                r = Adw.ActionRow(title=GLib.markup_escape_text(f"{k['label']}: {k.get('hint') or ''}"),
                                  subtitle=GLib.markup_escape_text(
                                      (k.get("press") or "").replace("{holo}", "bromigos-holo") +
                                      (f"  ·  needs {k['needs']}" if k.get("needs") else "")))
                r.set_subtitle_lines(2)
                ctx.hint(r, f"{k['label']} runs: {(k.get('press') or '').replace('{holo}', 'bromigos-holo')}")
                ex.add_row(r)
            g.add(ex)
        n = m.get("needs") or {}
        missing = [p["name"] for p in n.get("packages") or [] if not p.get("installed")] + \
                  [f"the {x['name']} group" for x in n.get("groups") or [] if not x.get("member")]
        if missing:
            ctx.note(g, "Turning it on installs or joins: " + ", ".join(missing), "note",
                     hint="Done once, in a terminal (sudo asks for your password)")

    # ------------------------------------------------------------------ changes
    def _enable(self, m, on):
        if on and _needs_root(m):
            self.ctx.terminal(CMD + ["enable", m["id"]])
            self.ctx.toast(f"{m['name']}: the first time needs your password, so it runs in a terminal "
                           f"(bromigos peripheral enable {m['id']})", timeout=8)
            GLib.timeout_add_seconds(8, lambda: (self.refresh(), False)[1])
            return
        verb = "enable" if on else "disable"
        undo = None if (not on and _needs_root(m)) else CMD + ["disable" if on else "enable", m["id"], "--json"]
        self.ctx.change(CMD + [verb, m["id"], "--json"],
                        lambda d: d.get("detail") or f"{m['name']}: {'on' if on else 'off'}",
                        undo=undo, done=lambda _d: self.refresh(), failed=lambda *_: self.refresh())

    def _follow(self, m, v, old):
        if v == old:
            return
        self.ctx.change(CMD + ["follow", m["id"], v, "--json"],
                        lambda d: d.get("detail") or f"The lighting follows {v}",
                        undo=CMD + ["follow", m["id"], old, "--json"], done=lambda _d: self.refresh(),
                        failed=lambda *_: self.refresh())


def build(ctx):
    p = PeripheralsPage(ctx)
    p.page._peripherals = p
    return p.page


def refresh(widget):
    widget._peripherals.refresh()


PAGE = Page(
    id="peripherals", title="Peripherals", group="system", order=70, build=build, refresh=refresh,
    docs="settings.md#peripherals", icon="input-gaming-symbolic applications-games-symbolic input-keyboard-symbolic",
    summary="macro keys, the dial, lighting",
    intro="Optional modules for a keyboard with macro keys, a dial or lighting: each on or off, its keys, its dial, "
          "and what its lighting follows.",
    keywords=["razer", "macro keys", "rgb", "dial", "openrazer", "keyboard lighting"],
    entries=[
        Entry("modules", "Peripheral modules", ["razer keyboard", "device"], "Modules"),
        Entry("on", "Turn a module on", ["enable peripheral"], "Modules"),
        Entry("follow", "Lighting follows", ["rgb", "keyboard lighting", "vector colours", "theme colours"], "Modules"),
        Entry("dial", "The dial", ["command dial", "voice dial", "volume roller"], "Modules"),
        Entry("keys", "Macro keys", ["M1", "side keys", "what the keys do"], "Modules"),
        Entry("refresh", "Refresh the keys", ["peripherals.toml", "plugged in"], "Keys and devices"),
    ])
