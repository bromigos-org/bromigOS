"""Theme: every theme as a picture of your desktop wearing it (the theme switcher's cards and
previews, the same code: lib/bromigos_themecards.py), a click to wear one; the theme in
force (its palette, what moves in its world and what drives it); the options around it
(the live background, the wallpaper, the theme's sounds, a keyboard's lighting); and more
themes (the catalog, a git URL, one of your own).

Everything goes through the commands (`bromigos theme set`, `bromigos live`, `bromigos
wallpaper`, `bromigos live mute`, `bromigos peripheral follow`, `bromigos ext search`,
`bromigos theme install|new`); a change applies at once and leaves a toast, with Undo where
it can be undone. The page follows the theme: a switch from anywhere (the switcher, a
terminal) marks the new one and redraws the details."""
import os
import sys
import threading
import tomllib

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gdk, Gio, GLib, Gtk, Pango  # noqa: E402

from bromigos_settings import Page, style  # noqa: E402
try:
    from bromigos_settings import Entry  # noqa: E402  (the search across every setting)
except ImportError:
    Entry = None

_LIB = os.path.normpath(os.path.join(os.path.dirname(os.path.realpath(__file__)), "..", "..", "lib"))
for _p in (_LIB, "/usr/lib/bromigos/lib"):
    if os.path.isdir(_p) and _p not in sys.path:
        sys.path.append(_p)

import bromigos_themecards as TC  # noqa: E402

CARD_W, CARD_H = 236, 133
STATE = os.environ.get("XDG_STATE_HOME") or os.path.expanduser("~/.local/state")
CURRENT = os.path.join(STATE, "bromigos", "theme", "current")

SWATCHES = [("background", "the ground everything sits on"), ("panel", "panels and the bar"),
            ("primary", "the live colour: values, the accent"), ("soft", "text that matters"),
            ("dim", "rules and frames"), ("muted", "secondary text"), ("warn", "warnings"),
            ("danger", "errors and alarms")]

# what drives a world (docs/theming.md, "Signals and events"), in plain words
SIGNALS = {
    "cpu": "this machine's CPU load", "gpu": "the GPU's load", "mem": "memory in use",
    "net": "network traffic", "net_rx": "downloads", "net_tx": "uploads",
    "health": "the lab's health", "lab_green": "every lab node and service up", "storm": "a lab alert",
    "ingress": "the lab's web traffic", "user": "you: working, dozing or away",
    "activity": "you: working, dozing or away", "vector": "VECTOR's state", "agents": "your coding agents",
    "agents_working": "your agents at work", "models": "the lab's models generating", "hour": "the real clock",
    "moon_phase": "the moon's real phase", "tide": "the tide, from the moon", "lab": "the lab",
}
REQUIRES = {"lab": "only while the lab is there", "agents": "only while you run coding agents",
            "vector": "only while VECTOR runs"}
EVENTS = {"notify": "a notification", "critical": "a critical notification", "lab_alert": "a lab alert",
          "login": "your login", "fill_win": "a plugin's win", "fill_loss": "a plugin's loss",
          "fill_open": "a plugin's open", "flyby": "a flyby, now and then"}
EFFECTS = {"rain": "Rain", "mist": "Mist", "lightning": "Lightning", "fireflies": "Fireflies", "beacon": "A beacon",
           "beam": "The lighthouse beam", "swell": "The swell", "rays": "Light shafts", "moon": "The moon",
           "stars": "The stars", "spray": "Spray", "line": "The fishing line"}
VARIANTS = {"empty": "the den, chair empty (bromigOS's)", "den": "the den with you at the desk (your own art)",
            "masked": "you at the desk, the burn-in over your face (your own art)", "v1": "the first den plate"}


def _signal_words(spec):
    """An effect's or actor's drivers: `signal`, `mix` terms, `rate_signal`."""
    names = []
    for k in ("signal", "rate_signal"):
        if isinstance(spec.get(k), str):
            names.append(spec[k])
    for term in spec.get("mix") or []:
        if isinstance(term, dict) and isinstance(term.get("signal"), str):
            names.append(term["signal"])
    out = []
    for n in names:
        w = SIGNALS.get(n, n)
        if w not in out:
            out.append(w)
    return out


def world_moves(path):
    """What moves in a world and what drives it: [(title, what drives it)], from its
    world.toml (effects, then actors)."""
    try:
        with open(path, "rb") as f:
            w = tomllib.load(f)
    except (OSError, ValueError):
        return []
    rows = []
    for e in w.get("effects") or []:
        t = e.get("type", "")
        words = _signal_words(e)
        if t in ("moon", "stars"):
            words = ["the real clock and moon"]
        elif t == "rays":
            words = ["the moon or the day's light, moved by the swell"]
        elif t == "spray":
            words = ["creatures breaching, a catch leaving the water"]
        elif t == "line":
            words = ["the keeper's fishing"]
        rows.append((EFFECTS.get(t, t.capitalize()), ", ".join(words) or "always"))
    for a in w.get("actors") or []:
        name = a.get("name") or a.get("id", "").replace("-", " ").replace("_", " ").capitalize()
        kind = a.get("kind")
        if kind == "keeper":
            drive = "the keeper, mirroring you: working while you work, dozing when you're idle, asleep when locked"
        elif kind == "agents":
            drive = "one per coding agent: it rises when one starts, turns and signals when one needs you"
        elif kind == "crowd":
            drive = "your activity: about while you work, settling when you're idle"
        elif kind == "traffic":
            drive = "craft crossing with " + (", ".join(_signal_words(a)) or "your network")
        elif kind == "signal":
            drive = ", ".join(_signal_words(a)) or "a reading"
        elif kind == "flyby":
            drive = "now and then, a craft crossing the sky (bromigos-live world event flyby)"
        elif kind == "event":
            evs = [EVENTS.get(str(o.get("event")).split(":")[0].split(" ")[0], o.get("event"))
                   for o in a.get("on") or [] if o.get("event")]
            drive = "on " + ", ".join(dict.fromkeys(evs)) if evs else "events"
        else:
            drive = kind or ""
        if a.get("requires"):
            drive += f" ({REQUIRES.get(a['requires'], 'only while ' + SIGNALS.get(a['requires'], a['requires']))})"
        rows.append((name, drive))
    return rows


class ThemePage:
    def __init__(self, ctx):
        self.ctx = ctx
        app = ctx.window.get_application()
        self.still = bool(getattr(app, "render", None))      # an offscreen picture: no background work
        self.kit = TC.CardKit(Gtk, Pango, still=self.still, verb="Click")
        self.cards = {}
        self.entries = []
        self.pending = set()
        self.watch = None
        self.current = None
        self.seen = None
        self.page = ctx.page(intro="Every theme as a picture of your desktop wearing it: click one to wear it. "
                                   "Then the one you have on, what moves in it, and the options around it.")
        self.css = Gtk.CssProvider()
        Gtk.StyleContext.add_provider_for_display(Gdk.Display.get_default(), self.css,
                                                  Gtk.STYLE_PROVIDER_PRIORITY_USER + 5)
        self._themes()
        self.details = None
        self.options = None
        self._more()
        self.sync()
        GLib.timeout_add_seconds(2, self._tick)

    # ------------------------------------------------------------------ the themes
    def _themes(self):
        ctx = self.ctx
        g = ctx.group(self.page, "Themes", "Click one to wear it: every app takes its colours at once. Each picture is "
                                           "your desktop wearing it.",
                      hint="Every theme installed, then the ones the extension catalogs offer", key="themes")
        self.themes_group = g
        g.set_header_suffix(ctx.button("Open Customize", lambda: ctx.launch(["bromigos-customize", "--tab", "themes"]),
                                       "Opens Customize over the whole screen (SUPER+CTRL+SHIFT+SPACE): bigger "
                                       "previews, arrows and type-to-filter, and the widgets in the next tab"))
        self.busy = Adw.ActionRow(title="")
        sp = Gtk.Spinner()
        sp.set_spinning(not self.still)
        self.busy.add_prefix(sp)
        self.busy.set_visible(False)
        ctx.hint(self.busy, "A theme being applied: bromigos theme set renders it and tells every app")
        box = Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE)
        box.add_css_class("boxed-list")
        box.append(self.busy)
        box.set_visible(False)
        self.busy_box = box
        g.add(box)
        # three to a line where there's room, then two, then one (the Settings shell's
        # one-pane mode below 720 px): each card asks for its own width, no more
        self.flow = Gtk.FlowBox(homogeneous=True, column_spacing=12, row_spacing=12,
                                selection_mode=Gtk.SelectionMode.NONE, activate_on_single_click=True)
        self.flow.set_min_children_per_line(1)
        self.flow.set_max_children_per_line(3)
        self.flow.set_valign(Gtk.Align.START)
        self.flow.set_margin_top(6)
        self.flow.connect("child-activated", lambda _f, child: self.apply(child.entry))
        ctx.hint(self.flow, "Click a theme to wear it")
        self.entries = TC.installed()
        self.pending = {e.name for e in self.entries if not e.fresh and not e.failed}
        for e in self.entries:
            self._card(e)
        g.add(self.flow)
        self.count = Gtk.Label(xalign=0)
        self.count.add_css_class("dim-label")
        self.count.set_margin_top(6)
        ctx.hint(self.count, "Previews are drawn offscreen in the background (bromigos theme previews); a card fills "
                             "in when its picture is ready")
        g.add(self.count)
        if not self.still:
            if self.pending:
                TC.render_background(sorted(self.pending))
            self.watch = TC.PreviewWatch(Gio, GLib, self.entries, self.pending,
                                         on_ready=lambda e: self.kit.refresh(self.cards[e.name]),
                                         on_failed=lambda e: self.kit.refresh(self.cards[e.name]),
                                         on_change=self._count)
            threading.Thread(target=self._load_catalog, daemon=True).start()
        elif os.environ.get("BROMIGOS_THEME_CATALOG"):
            for e in TC.catalog({x.name for x in self.entries}):
                self.entries.append(e)
                self._card(e)
        self._count()

    def _card(self, e):
        child = self.kit.card(e, CARD_W, CARD_H, pending=e.name in self.pending)
        self.cards[e.name] = child
        self.flow.append(child)

    def _load_catalog(self):
        extra = TC.catalog({e.name for e in self.entries})
        if extra:
            GLib.idle_add(self._add_catalog, extra)

    def _add_catalog(self, extra):
        for e in extra:
            if e.name not in self.cards:
                self.entries.append(e)
                self._card(e)
        self._count()
        return False

    def _count(self):
        n_inst = sum(1 for e in self.entries if not e.catalog)
        n_cat = sum(1 for e in self.entries if e.catalog)
        parts = [f"{n_inst} installed"] + ([f"{n_cat} in the catalog"] if n_cat else [])
        if self.pending:
            parts.append(f"drawing {len(self.pending)} preview{'s' if len(self.pending) != 1 else ''}…")
        self.count.set_label(" · ".join(parts))

    # ------------------------------------------------------------------ applying
    def _busy(self, text):
        self.busy.set_title(text or "")
        self.busy.set_visible(bool(text))
        self.busy_box.set_visible(bool(text))

    def apply(self, e, undo_to=None):
        ctx = self.ctx
        if self.still:
            return
        if e.catalog:
            ctx.terminal(["sh", "-c", 'bromigos ext install "$1" && bromigos theme set "$1"', "sh", e.name])
            ctx.toast(f"Installing {e.display} in a terminal; it's applied when it's in")
            return
        before = undo_to or self.current
        self._busy(f"Applying {e.display}…")

        def done(doc, err):
            self._busy(None)
            if doc:
                undo = None
                if before and before != e.name and not undo_to:
                    prev = next((x for x in self.entries if x.name == before), None)
                    undo = (lambda: self.apply(prev, undo_to=e.name)) if prev else None
                ctx.toast(f"{doc.get('display_name') or e.display} is on", undo=undo)
            else:
                ctx.toast(f"{e.display}: {err or 'bromigos theme set failed'}")
            self.sync()
        ctx.json(["bromigos", "theme", "set", e.name, "--json"], done)

    # ------------------------------------------------------------------ the theme in force
    def sync(self):
        """The marks, the details and the options for the theme in force."""
        d = self.ctx.json_now(["bromigos", "theme", "current", "--json"]) or {}
        cur = d.get("name") or d.get("current") or "wick"
        self.current = cur
        self.seen = style.version()
        self.css.load_from_string(TC.card_css(self.ctx.colors, 12))
        for name, child in self.cards.items():
            if not child.entry.catalog:
                self.kit.set_current(child, name == cur)
                child.set_tooltip_text(child.entry.hint("Click"))
        self._details(next((e for e in self.entries if e.name == cur), None))
        self._options()

    def _tick(self):
        if style.version() != self.seen:
            self.sync()
        return True

    def _details(self, e):
        ctx = self.ctx
        if self.details is not None:
            self.page.remove_group(self.details)
        name = e.display if e else (self.current or "wick")
        g = Adw.PreferencesGroup(title=f"IN USE · {name.upper()}")
        g.set_description(e.desc if e else "")
        ctx.hint(g, f"The theme in force: {self.current}")
        g._bromigos_key = "in-use"
        self.page.box.insert_child_after(g, self.themes_group)
        self.details = g
        meta = {}
        try:
            with open(os.path.join(CURRENT, "theme.toml"), "rb") as f:
                meta = tomllib.load(f)
        except (OSError, ValueError):
            pass
        if meta.get("canon"):
            r = Adw.ActionRow(title="Where it sits", subtitle=" ".join(str(meta["canon"]).split()))
            r.set_subtitle_lines(0)
            ctx.hint(r, "The theme's place in the Drift (its theme.toml)")
            g.add(r)
        sw = Gtk.Box(spacing=8)
        sw.set_margin_top(8)
        sw.set_margin_bottom(4)
        for role, what in SWATCHES:
            hexv = ctx.colors.get(role)
            if not hexv:
                continue
            b = Gtk.Box()
            b.add_css_class("bromigos-swatch")
            prov = Gtk.CssProvider()
            prov.load_from_string(f"box {{ background-color: {hexv}; }}")
            b.get_style_context().add_provider(prov, Gtk.STYLE_PROVIDER_PRIORITY_USER + 1)
            ctx.hint(b, f"{role} {hexv}: {what}")
            sw.append(b)
        ctx.hint(sw, "The theme's colours, by what they're for")
        g.add(sw)
        world = os.path.join(CURRENT, "live", "world.toml")
        box = Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE)
        box.add_css_class("boxed-list")
        box.set_margin_top(8)
        if os.path.exists(world):
            moves = world_moves(world)
            head = Adw.ActionRow(title="What moves here, and what moves it",
                                 subtitle="Every moving thing is a real reading or a real event")
            ctx.hint(head, "From the world's live/world.toml: its effects and its creatures")
            box.append(head)
            for title, drive in moves:
                r = Adw.ActionRow(title=title, subtitle=drive)
                r.set_subtitle_lines(0)
                ctx.hint(r, f"{title}: {drive}")
                box.append(r)
        else:
            head = Adw.ActionRow(title="The den moves behind it",
                                 subtitle="The Wick's console room: its screens, rain and ships live" if
                                 self.current == "wick" else
                                 "No world of its own: the den's live parts take this theme's colours")
            ctx.hint(head, "The den's moving parts, each one switchable (bromigos anim)")
            box.append(head)
            anims = (ctx.json_now(["bromigos", "anim", "--json"]) or {}).get("animations") or []
            for a in anims:
                r = Adw.ActionRow(title=a.get("name", ""), subtitle=a.get("description", ""))
                r.set_subtitle_lines(0)
                state = Gtk.Label(label="on" if a.get("on") else "off")
                state.add_css_class("bromigos-value")
                if not a.get("on"):
                    state.add_css_class("off")
                r.add_suffix(state)
                ctx.hint(r, f"{a.get('name')}: {a.get('description')} (bromigos anim on|off {a.get('name')})")
                box.append(r)
        g.add(box)

    # ------------------------------------------------------------------ options
    def _options(self):
        ctx = self.ctx
        if self.options is not None:
            self.page.remove_group(self.options)
        g = Adw.PreferencesGroup(title="AROUND IT")
        g.set_description("The live background, the wallpaper, the theme's sounds and the lights that follow it.")
        ctx.hint(g, "Options that go with whatever theme is on")
        g._bromigos_key = "around-it"
        self.page.box.insert_child_after(g, self.details)
        self.options = g
        self._live_row(g)
        self._wallpaper_row(g)
        self._sounds_row(g)
        r = ctx.row(g, "Reduced motion and high contrast", "Calmer or still backgrounds, every colour raised: "
                    "Accessibility", hint="Opens the Accessibility page (bromigos accessibility)",
                    activate=lambda: ctx.open_page("accessibility"), key="accessibility")
        r.set_subtitle_lines(2)
        self._lighting_rows(g)

    def _live_row(self, g):
        ctx = self.ctx
        st = (ctx.json_now(["bromigos", "status", "--json"]) or {}).get("live") or {}
        bg = st.get("background")
        row = ctx.switch_row(g, "Live background", "The world or the den, moving behind everything (SUPER+SHIFT+B)",
                             hint="bromigos live on|off: the animated background, all of it (the animations one by "
                                  "one: bromigos anim)", active=bool(bg), key="live-background",
                             on_toggle=lambda on: self._toggle(row, on, ["bromigos", "live", "on" if on else "off"],
                                                               f"The live background is {'on' if on else 'off'}"),
                             advanced={"runs": "bromigos live on|off", "note": "for now; bromigos anim for each part"})
        if bg is None:
            row.set_sensitive(False)
            row.set_subtitle("The live layer isn't running (bromigos live start)")

    def _toggle(self, row, on, argv, said):
        """A switch flipped: run argv, toast what changed with Undo (flip it back)."""
        def fin(ok, out, err):
            if ok:
                self.ctx.toast(said, undo=lambda: row.set_active(not on))
            else:
                row.set_quiet(not on)
                self.ctx.toast(f"Not changed: {(err or out).strip()[:160] or 'failed'}")
        self.ctx.run(argv, fin)

    def _wallpaper_row(self, g):
        ctx = self.ctx
        d = ctx.json_now(["bromigos-wallpaper", "list", "--json"]) or {}
        variants = [v.get("name") for v in d.get("variants") or [] if v.get("name")]
        world = bool(d.get("world"))
        sub = ("This theme's painting is the wallpaper (the den's choice waits for the Wick)" if world
               else VARIANTS.get(d.get("current"), d.get("current") or "the den"))
        buttons = [("Previous", lambda: self._wallpaper("previous"), "The den variant before this one"),
                   ("Next", lambda: self._wallpaper("next"), "The next den variant (SUPER+CTRL+SPACE)")]
        control = None
        if len(variants) > 1 and not world:
            control = ctx.dropdown([(v, v) for v in variants], d.get("current"),
                                   on_select=lambda v: self._wallpaper(v),
                                   hint="Pick a den variant: " + "; ".join(f"{v}: {VARIANTS.get(v, v)}"
                                                                          for v in variants))
        row = ctx.row(g, "Wallpaper", sub, hint="The still under the live layer and the lock screen's background",
                      buttons=buttons if len(variants) > 1 and not world else (), control=control, key="wallpaper",
                      advanced={"runs": "bromigos-wallpaper next|previous|NAME",
                                "file": "~/.local/state/bromigos/wallpaper/variant"})
        if world or len(variants) < 2:
            row.set_sensitive(not world)

    def _wallpaper(self, verb):
        def fin(ok, out, err):
            self.ctx.toast(out.strip().splitlines()[-1] if ok and out.strip()
                           else f"Wallpaper: {verb}" if ok else f"Not changed: {err.strip()[:120]}")
            GLib.idle_add(lambda: (self._options(), False)[1])
        self.ctx.run(["bromigos-wallpaper", verb], fin)

    def _sounds_row(self, g):
        ctx = self.ctx
        st = ctx.json_now(["bromigos", "mute", "status", "--json"]) or {}
        row = ctx.switch_row(g, "Theme sounds", "The world's sounds and the desktop's cues (SUPER+SHIFT+M mutes them "
                                                 "together with VECTOR's voice)",
                             hint="bromigos live mute on|off: the theme's sounds only; bromigos mute takes VECTOR's "
                                  "voice too", active=not st.get("theme", False), key="theme-sounds",
                             on_toggle=lambda on: self._toggle(row, on, ["bromigos", "live", "mute",
                                                                         "off" if on else "on"],
                                                               f"The theme's sounds are {'on' if on else 'off'}"),
                             advanced={"runs": "bromigos live mute on|off",
                                       "file": "~/.local/state/bromigos-live/muted"})
        row.set_subtitle_lines(2)

    def _lighting_rows(self, g):
        ctx = self.ctx
        d = ctx.json_now(["bromigos", "peripheral", "status", "--json"]) or {}
        lit = [m for m in d.get("modules") or [] if isinstance(m.get("rgb"), dict)]
        if not lit:
            ctx.row(g, "Keyboard lighting", "No keyboard with lighting is on here; a peripheral module turns one on "
                    "(bromigos peripheral)", hint="A module with lighting (a Razer keyboard's) can follow the theme "
                                                  "once it's on: bromigos peripheral enable",
                    key="lighting").set_sensitive(False)
        for m in lit:
            rgb = m.get("rgb")
            if not isinstance(rgb, dict):
                continue
            mid = m.get("id")
            holder = {}
            holder["row"] = ctx.switch_row(
                g, f"{m.get('name') or mid}: lighting follows the theme",
                "On: the theme's primary, always. Off: VECTOR's voice and mood",
                hint=f"bromigos peripheral follow {mid} theme|vector; the lights change within 10 s",
                active=rgb.get("follow") == "theme", key="lighting",
                on_toggle=lambda on, mid=mid, h=holder: self._toggle(
                    h["row"], on, ["bromigos", "peripheral", "follow", mid, "theme" if on else "vector"],
                    f"The lighting follows {'the theme' if on else 'VECTOR'}"),
                advanced={"runs": f"bromigos peripheral follow {mid} theme|vector",
                          "file": "~/.config/bromigos/peripherals.toml", "key": f"{mid}.rgb_follow"})

    # ------------------------------------------------------------------ more themes
    def _more(self):
        ctx = self.ctx
        g = ctx.group(self.page, "Get more themes", "From the catalogs, from anyone's git repository, or your own.",
                      hint="Themes are extensions: bromigos ext keeps them up to date", key="more")
        search = Gtk.SearchEntry(placeholder_text="Search the catalog")
        search.set_hexpand(True)
        search.set_valign(Gtk.Align.CENTER)
        ctx.hint(search, "Search the extension catalogs' themes by name, description or tag (bromigos ext search "
                         "--kind theme); Enter searches")
        r = Adw.ActionRow(title="The catalog")
        ctx.hint(r, "Themes people share through the extension catalogs")
        r.add_suffix(search)
        r._bromigos_key = "catalog"
        g.add(r)
        self.results = Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE)
        self.results.add_css_class("boxed-list")
        self.results.set_visible(False)
        ctx.hint(self.results, "What the catalog has; Install fetches one and applies it")
        g.add(self.results)
        search.connect("activate", lambda w: self._search(w.get_text().strip()))
        url = Gtk.Entry(placeholder_text="https://github.com/someone/bromigos-theme-…")
        url.set_hexpand(True)
        url.set_valign(Gtk.Align.CENTER)
        ctx.hint(url, "A theme's git repository (a tag after @ pins it)")
        r = Adw.ActionRow(title="From a git URL")
        ctx.hint(r, "bromigos theme install URL: kept as a git checkout that bromigos ext update updates")
        r._bromigos_key = "git-url"
        r.add_suffix(url)
        r.add_suffix(ctx.button("Install", lambda: self._install_url(url.get_text().strip()),
                                "Installs it in a terminal (bromigos theme install URL)"))
        g.add(r)
        name = Gtk.Entry(placeholder_text="my-theme")
        name.set_valign(Gtk.Align.CENTER)
        ctx.hint(name, "Your theme's name: lowercase, letters, digits and dashes")
        r = Adw.ActionRow(title="Make your own", subtitle="A copy of the theme in force, to edit and share")
        r._bromigos_key = "make-your-own"
        ctx.hint(r, "bromigos theme new NAME --from THEME: a theme extension in ~/NAME (colors.toml, theme.toml); "
                    "docs/theming.md says what each colour does")
        r.add_suffix(name)
        r.add_suffix(ctx.button("Make", lambda: self._new(name.get_text().strip()),
                                "Makes it in a terminal, from the theme in force"))
        g.add(r)

    def _search(self, term):
        ctx = self.ctx
        argv = ["bromigos", "ext", "search", "--kind", "theme", "--json"] + ([term] if term else [])

        def done(doc, err):
            child = self.results.get_first_child()
            while child is not None:
                nxt = child.get_next_sibling()
                self.results.remove(child)
                child = nxt
            rows = (doc or {}).get("results") or []
            if not rows:
                rr = Adw.ActionRow(title="Nothing found" if doc else "The catalog can't be read",
                                   subtitle=err or "Try another word")
                ctx.hint(rr, "bromigos ext search found no theme")
                self.results.append(rr)
            for c in rows:
                rr = Adw.ActionRow(title=c.get("display_name") or c.get("name"), subtitle=c.get("description") or "")
                rr.set_subtitle_lines(2)
                ctx.hint(rr, f"{c.get('name')}: " + ", ".join(c.get("tags") or []))
                if c.get("installed") or c.get("bundled"):
                    lab = Gtk.Label(label="installed")
                    lab.add_css_class("dim-label")
                    ctx.hint(lab, "Already here: click its card above to wear it")
                    rr.add_suffix(lab)
                else:
                    rr.add_suffix(ctx.button("Install", lambda n=c.get("name"): self._install_url(n),
                                             f"Installs {c.get('name')} in a terminal and applies it"))
                self.results.append(rr)
            self.results.set_visible(True)
        ctx.json(argv, done)

    def _install_url(self, src):
        if not src:
            self.ctx.toast("A git URL or a catalog name first")
            return
        self.ctx.terminal(["bromigos", "theme", "install", src])
        self.ctx.toast(f"Installing {src} in a terminal; its card appears here when it's in")

    def _new(self, name):
        import re
        if not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,40}", name or ""):
            self.ctx.toast("A name of lowercase letters, digits and dashes")
            return
        self.ctx.terminal(["bromigos", "theme", "new", name, "--from", self.current or "wick",
                           "--dir", os.path.expanduser(f"~/{name}")])
        self.ctx.toast(f"Making {name} in ~/{name} from {self.current or 'wick'}")


def build(ctx):
    return ThemePage(ctx).page


def _entries():
    if Entry is None:
        return []
    return [
        Entry("themes", "Themes", ["wear a theme", "switch theme", "colours", "colors", "look", "previews", "world",
                                   "dark", "light", "dark mode", "light mode", "colour scheme"], "Themes"),
        Entry("in-use", "The theme in force", ["palette", "what moves", "world", "creatures", "den"], "In use"),
        Entry("live-background", "Live background", ["animated background", "animation", "wallpaper moving",
                                                     "background off"], "Around it"),
        Entry("wallpaper", "Wallpaper", ["den", "background picture", "lock screen background"], "Around it"),
        Entry("theme-sounds", "Theme sounds", ["sounds", "cues", "mute", "ambient"], "Around it"),
        Entry("lighting", "Keyboard lighting follows the theme", ["rgb", "razer", "keyboard colour", "lights"],
              "Around it"),
        Entry("catalog", "Search the theme catalog", ["more themes", "download themes", "extensions"],
              "Get more themes"),
        Entry("git-url", "Install a theme from a git URL", ["github", "install theme"], "Get more themes"),
        Entry("make-your-own", "Make your own theme", ["new theme", "custom theme", "create a theme"],
              "Get more themes"),
    ]


_kw = dict(group="desktop", intro="Wear a theme from a picture of your desktop in it; what moves in its world; "
                                  "the background, wallpaper, sounds and lights around it; more themes.",
           docs="themes-and-worlds.md", entries=_entries())
try:
    PAGE = Page(id="theme", title="Theme", icon="applications-graphics-symbolic", order=20,
                summary="wear a theme, its world, more themes",
                keywords=["colours", "colors", "wallpaper", "world", "look", "switcher", "sounds", "lighting",
                          "catalog"], build=build, **_kw)
except TypeError:                   # an older Settings shell: no groups, intro, docs or entries
    PAGE = Page(id="theme", title="Theme", icon="applications-graphics-symbolic", order=20,
                summary="wear a theme, its world, more themes",
                keywords=["colours", "colors", "wallpaper", "world", "look", "switcher", "sounds", "lighting",
                          "catalog"], build=build)
