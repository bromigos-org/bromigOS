"""Theme cards (package bromigos-desktop, /usr/lib/bromigos/lib): the themes as the theme
switcher and Settings › Theme show them, one shared piece.

  installed()                 the installed themes, each an Entry with its preview
                              (bromigos_previews: fresh, or an older version's, or none yet)
  catalog(have)               the extension catalogs' themes not installed
  render_background(names)   draw missing previews in the background (bromigos theme previews)
  CardKit(Gtk, Pango)         a card (a Gtk.FlowBoxChild): the preview, or a placeholder in
                              the theme's own colours while it's drawn; the name and a tagline;
                              IN USE, WORLD/DEN/COLOUR/CATALOG and DRAWING badges; a hover hint
  card_css(colors, font)      the cards' style, in the colours of the theme in force
  PreviewWatch(...)           calls back as pending previews land (or fail)

GTK is the caller's (GTK 4, loaded its own way: the switcher needs gtk4-layer-shell first).
"""
import hashlib
import json
import os
import shlex
import subprocess
import sys

HERE = os.path.dirname(os.path.realpath(__file__))
for _p in (HERE, "/usr/lib/bromigos/lib"):
    if os.path.isdir(_p) and _p not in sys.path:
        sys.path.append(_p)

import bromigos_previews as PV  # noqa: E402

CATALOG_CMD = ["bromigos", "ext", "search", "--kind", "theme", "--json"]

# The Wick's colours: before any theme was set, and for a theme that can't be read.
WICK = {"background": "#000500", "void": "#000500", "panel": "#001300", "selection": "#003b00",
        "primary": "#39ff14", "soft": "#9cff8a", "dim": "#159b09", "text": "#c4f5bb", "muted": "#7e927e",
        "faint": "#4e6b4e", "warn": "#d4af37", "danger": "#ff766f"}


# ------------------------------------------------------------------ the themes
class Entry:
    """A card: an installed theme, or a catalog's."""

    def __init__(self, name, display, desc, kind, sources=(), current=False, install=None, tags=()):
        self.name, self.display, self.desc, self.kind = name, display or name, desc or "", kind
        self.sources, self.current, self.install, self.tags = list(sources), current, install, list(tags)
        self.preview, self.fresh, self.stamp = None, False, None
        self.colors = dict(WICK)
        self.failed = None

    @property
    def catalog(self):
        return self.install is not None

    def tagline(self):
        """The description's first clause: short enough for one line under the picture."""
        d = self.desc.strip().rstrip(".")
        for sep in (": ", "; ", ", "):
            head = d.split(sep)[0]
            if 8 <= len(head) < len(d):
                return head
        return d

    def kind_label(self):
        return {"world": "WORLD", "den": "DEN", "colour": "COLOUR"}.get(self.kind, self.kind.upper())

    def kind_hint(self):
        return {"world": "a world: the live layer draws its own scene",
                "den": "the Wick's own den: the live layer's console room, its screens and glyph rain live",
                "colour": "a colour theme: every app's colours; the den stays behind it, recoloured: its painting, "
                          "glyph rain and live screens take this theme's colours"}.get(self.kind, self.kind)

    def hint(self, verb="Enter or click"):
        src = {"system": "first-party", "ext": "an extension", "user": "your own"}
        where = " + ".join(src.get(s, s) for s in self.sources) or "the catalog"
        lines = [f"{self.display}: {self.desc}" if self.desc else self.display, f"{self.kind_hint()} · {where}"]
        if self.catalog:
            lines.append(f"{verb}: install it from the catalog (bromigos ext install), then apply it")
        elif self.current:
            lines.append(f"In use now · {verb}: apply it again")
        else:
            lines.append(f"{verb}: apply it (bromigos theme set {self.name})")
        if self.failed:
            lines.append(f"The preview couldn't be drawn: {self.failed} (bromigos theme previews {self.name} "
                         "tries again)")
        elif not self.catalog and not self.fresh:
            lines.append("The preview is being drawn" + (" (the one shown is of an older version)" if self.preview
                                                         else ""))
        return "\n".join(lines)

    def haystack(self):
        return " ".join([self.name, self.display, self.desc, self.kind, " ".join(self.tags),
                         "catalog" if self.catalog else "installed", "current" if self.current else ""]).lower()


def theme_colors(name):
    """A theme's roles from its colors.toml layers (first-party, extension, user), names
    resolved: the placeholder card is drawn in them."""
    import tomllib
    merged = {}
    for d in PV.layers(name):
        try:
            with open(os.path.join(d, "colors.toml"), "rb") as f:
                doc = tomllib.load(f)
        except (OSError, ValueError):
            continue
        for k, v in doc.items():
            if isinstance(v, dict) and isinstance(merged.get(k), dict):
                merged[k].update(v)
            else:
                merged[k] = v
    flat = {k: v for k, v in merged.items() if isinstance(v, str)}
    flat.update({k: v for k, v in (merged.get("colors") or {}).items() if isinstance(v, str)})

    def res(v, seen=()):
        if v.startswith("#"):
            return v
        if v in seen or v not in flat:
            return None
        return res(flat[v], seen + (v,))
    out = dict(WICK)
    for k, v in flat.items():
        r = res(v)
        if r:
            out[k] = r
    return out


def is_world(name):
    return any(os.path.exists(os.path.join(d, "live", "world.toml")) for d in PV.layers(name))


def kind_of(name):
    """world (its own live scene), den (the Wick: the den is its own room, the live layer's
    default scene) or colour (the den behind it)."""
    return "world" if is_world(name) else "den" if name == "wick" else "colour"


def installed():
    """The installed themes (bromigos theme list), each with its preview as it stands."""
    PV.clean_legacy()
    d = PV.themes()
    out = []
    for t in d.get("themes", []):
        if t.get("error"):
            continue
        name = t["name"]
        e = Entry(name, t.get("display_name"), t.get("description"), kind_of(name),
                  t.get("sources", []), current=name == d.get("current"))
        e.colors = theme_colors(name)
        e.stamp = PV.stamp(name)
        e.preview, e.fresh = PV.current(name, e.stamp)
        if not e.fresh:
            e.failed = PV.failure(name, e.stamp)
        out.append(e)
    return out


def catalog(have):
    """Themes a catalog offers (bromigos ext search): a list (or {"results": […]}) of objects
    with name, display_name (or title), description, preview (a URL or a path), install
    (argv or a string) and tags. Installed and bundled ones aren't repeated.
    $BROMIGOS_THEME_CATALOG names a JSON file to read instead (tests)."""
    try:
        if os.environ.get("BROMIGOS_THEME_CATALOG"):
            with open(os.environ["BROMIGOS_THEME_CATALOG"]) as f:
                d = json.load(f)
        else:
            r = subprocess.run(CATALOG_CMD, capture_output=True, text=True, timeout=15)
            d = json.loads(r.stdout) if r.returncode == 0 and r.stdout.strip() else []
    except (OSError, subprocess.SubprocessError, ValueError):
        return []
    if isinstance(d, dict):
        d = d.get("results") or d.get("themes") or d.get("extensions") or []
    out = []
    for c in d:
        name = c.get("name") if isinstance(c, dict) else None
        if not name or name in have or c.get("installed") or c.get("bundled"):
            continue
        inst = c.get("install") or ["bromigos", "ext", "install", name]
        if isinstance(inst, str):
            inst = shlex.split(inst)
        tags = c.get("tags") or []
        e = Entry(name, c.get("display_name") or c.get("title"), c.get("description"),
                  "world" if "world" in tags else "colour", [], install=inst, tags=tags)
        e.preview, e.fresh = fetched(name, c.get("preview")), True
        out.append(e)
    return out


def fetched(name, preview):
    """A catalog preview's local path: a path as is, a URL downloaded once into the cache."""
    if not preview:
        return None
    if os.path.exists(preview):
        return preview
    if not preview.startswith(("http://", "https://")):
        return None
    os.makedirs(PV.CACHE, exist_ok=True)
    path = os.path.join(PV.CACHE, f"catalog-{name}-{hashlib.sha256(preview.encode()).hexdigest()[:10]}.img")
    if not os.path.exists(path):
        try:
            import urllib.request
            req = urllib.request.Request(preview, headers={"User-Agent": "bromigos-theme-switcher"})
            with urllib.request.urlopen(req, timeout=10) as r:
                data = r.read(16 << 20)
            with open(path + ".tmp", "wb") as f:
                f.write(data)
            os.replace(path + ".tmp", path)
        except Exception:
            return None
    return path


def render_background(names):
    """Draw these previews in the background (bromigos theme previews, its own process: it
    outlives the window and waits its turn behind another run). BROMIGOS_PREVIEWS_HOLD=1
    draws none: a test's window in a sandbox leaves nothing running after it."""
    if os.environ.get("BROMIGOS_PREVIEWS_HOLD") == "1":
        return
    exe = None
    for d in (os.path.join(HERE, "..", "bin"), "/usr/lib/bromigos/desktop/bin"):
        p = os.path.join(d, "bromigos-theme-previews")
        if os.path.exists(p):
            exe = os.path.realpath(p)
            break
    argv = [exe or "bromigos-theme-previews", "--quiet", *names]
    try:
        subprocess.Popen(["nice", "-n", "10"] + argv, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL, start_new_session=True)
    except OSError:
        pass


# ------------------------------------------------------------------ the cards (GTK 4)
def rgba(h, a):
    h = h.lstrip("#")
    return f"rgba({int(h[0:2], 16)},{int(h[2:4], 16)},{int(h[4:6], 16)},{a})"


def card_css(c, font=13):
    """The cards in the colours of the theme in force (`c`: its resolved roles)."""
    a = rgba
    return f"""
flowboxchild.card {{ padding: 0; margin: 0; border-radius: 0; border: 1px solid {a(c['dim'], .35)};
  background-color: {a(c['void'], .55)}; outline: none; }}
flowboxchild.card:hover {{ border-color: {a(c['primary'], .55)}; background-color: {a(c['primary'], .05)}; }}
flowboxchild.card:selected {{ border-color: {c['primary']}; background-color: {a(c['primary'], .10)};
  box-shadow: 0 0 0 1px {c['primary']}, 0 0 18px {a(c['primary'], .35)}; }}
flowboxchild.card.current {{ border-color: {a(c['primary'], .8)}; }}
flowboxchild.card .caption {{ padding: 6px 10px 8px 10px; }}
flowboxchild.card .name {{ color: {c['soft']}; font-weight: 700; letter-spacing: 0.12em; font-size: {font}px; }}
flowboxchild.card.current .name, flowboxchild.card:selected .name {{ color: {c['primary']}; }}
flowboxchild.card .tagline {{ color: {c['muted']}; font-size: {font - 1}px; }}
flowboxchild.card .badge {{ font-weight: 700; letter-spacing: 0.12em; font-size: {font - 2}px; padding: 2px 7px;
  margin: 8px; border-radius: 0; }}
flowboxchild.card .badge.inuse {{ background-color: {c['primary']}; color: {c['void']}; }}
flowboxchild.card .badge.kind {{ background-color: {a(c['void'], .78)}; color: {c['soft']};
  border: 1px solid {a(c['dim'], .7)}; }}
flowboxchild.card .badge.catalog {{ background-color: {a(c['void'], .78)}; color: {c['warn']};
  border: 1px solid {a(c['warn'], .7)}; }}
flowboxchild.card .badge.pending {{ background-color: {a(c['void'], .82)}; color: {c['warn']};
  border: 1px solid {a(c['warn'], .55)}; }}
"""


def placeholder_css(e):
    """A card without a picture yet: the theme's own colours."""
    c = e.colors
    return (f"box.placeholder {{ background-image: linear-gradient(160deg, {c.get('background', '#000')} 0%, "
            f"{c.get('panel', '#111')} 70%, {c.get('selection', '#222')} 100%); }}\n"
            f"box.placeholder label.pname {{ color: {c.get('primary', '#fff')}; font-weight: 700; "
            f"letter-spacing: 0.2em; }}\n"
            f"box.placeholder label.pnote {{ color: {c.get('muted', '#888')}; }}\n"
            f"box.placeholder box.swatch {{ min-width: 18px; min-height: 6px; }}\n")


class CardKit:
    """Makes and updates cards. `still`: a picture for a test (no spinner running);
    `verb`: what a card's hint says activates it ("Enter or click", "Click")."""

    def __init__(self, Gtk, Pango, still=False, verb="Enter or click"):
        self.Gtk, self.Pango, self.still, self.verb = Gtk, Pango, still, verb

        class CardBox(Gtk.Widget):
            """Holds a card: its natural width is the card's, not its picture's (a 1280 px
            preview), so a flow box fits as many to a line as there's room for. (A Gtk.Box
            measures through its layout manager, so its own measure can't be changed.)"""

            def __init__(self, child, want):
                super().__init__()
                self.child, self.want = child, want
                child.set_parent(self)

            def do_measure(self, orientation, for_size):
                m, n, mb, nb = self.child.measure(orientation, for_size)
                if orientation == Gtk.Orientation.HORIZONTAL and self.want:
                    return min(m, self.want), max(min(m, self.want), self.want), -1, -1
                return m, n, mb, nb

            def do_size_allocate(self, width, height, baseline):
                self.child.allocate(width, height, baseline, None)

            def do_dispose(self):
                if self.child is not None:
                    self.child.unparent()
                    self.child = None
        self.CardBox = CardBox

    def card(self, e, w, h, pending=False, on_hover=None, on_leave=None):
        Gtk = self.Gtk
        child = Gtk.FlowBoxChild()
        child.entry = e
        child.add_css_class("card")
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        over = Gtk.Overlay()
        over.set_size_request(w, h)
        child.pic_slot = over
        child.size = (w, h)
        over.set_child(self.picture(e, w, h))
        tl = Gtk.Box(spacing=0, halign=Gtk.Align.START, valign=Gtk.Align.START)
        inuse = Gtk.Label(label="IN USE")
        inuse.add_css_class("badge")
        inuse.add_css_class("inuse")
        inuse.set_tooltip_text("The theme in force now")
        tl.append(inuse)
        child.inuse_badge = inuse
        over.add_overlay(tl)
        tr = Gtk.Box(spacing=0, halign=Gtk.Align.END, valign=Gtk.Align.START)
        k = Gtk.Label(label="CATALOG" if e.catalog else e.kind_label())
        k.add_css_class("badge")
        k.add_css_class("catalog" if e.catalog else "kind")
        k.set_tooltip_text("Not installed: a catalog's theme; choosing it installs it first" if e.catalog
                           else e.kind_hint()[0].upper() + e.kind_hint()[1:])
        tr.append(k)
        over.add_overlay(tr)
        pend = Gtk.Box(spacing=6, halign=Gtk.Align.END, valign=Gtk.Align.END)
        pend.add_css_class("badge")
        pend.add_css_class("pending")
        sp = Gtk.Spinner()
        sp.set_spinning(not self.still)
        pend.append(sp)
        pend.append(Gtk.Label(label="UPDATING" if e.preview else "DRAWING"))
        pend.set_tooltip_text("This preview is being drawn offscreen in the background; the card fills in when "
                              "it's ready")
        pend.set_visible(pending)
        child.pending_badge = pend
        over.add_overlay(pend)
        box.append(over)
        cap = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        cap.add_css_class("caption")
        name = Gtk.Label(label=e.display.upper(), xalign=0, ellipsize=self.Pango.EllipsizeMode.END)
        name.add_css_class("name")
        cap.append(name)
        tag = Gtk.Label(label=e.tagline() or " ", xalign=0, ellipsize=self.Pango.EllipsizeMode.END)
        tag.add_css_class("tagline")
        tag.set_max_width_chars(1)
        tag.set_hexpand(True)
        cap.append(tag)
        cap.set_size_request(w, -1)
        child.caption = cap
        box.append(cap)
        child.sizer = self.CardBox(box, w)
        child.set_child(child.sizer)
        self.set_current(child, e.current)
        child.set_tooltip_text(e.hint(self.verb))
        if on_hover or on_leave:
            motion = Gtk.EventControllerMotion()
            if on_hover:
                motion.connect("enter", lambda *_a, e=e: on_hover(e))
            if on_leave:
                motion.connect("leave", lambda *_a: on_leave())
            child.add_controller(motion)
        return child

    def picture(self, e, w, h):
        Gtk = self.Gtk
        if e.preview and os.path.exists(e.preview):
            pic = Gtk.Picture.new_for_filename(e.preview)
            pic.set_content_fit(Gtk.ContentFit.COVER)
            pic.set_can_shrink(True)
            pic.set_size_request(w, h)
            pic.set_alternative_text(f"{e.display} preview")
            return pic
        # no picture yet: the theme's own colours, its name, and what's happening
        ph = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10, valign=Gtk.Align.FILL)
        ph.add_css_class("placeholder")
        ph.set_size_request(w, h)
        prov = Gtk.CssProvider()
        prov.load_from_string(placeholder_css(e))
        inner = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8, vexpand=True, valign=Gtk.Align.CENTER)
        nm = Gtk.Label(label=e.display.upper())
        nm.add_css_class("pname")
        inner.append(nm)
        sw = Gtk.Box(spacing=4, halign=Gtk.Align.CENTER)
        for role in ("primary", "soft", "dim", "warn", "danger"):
            s = Gtk.Box()
            s.add_css_class("swatch")
            p2 = Gtk.CssProvider()
            p2.load_from_string(f"box.swatch {{ background-color: {e.colors.get(role, '#888')}; }}")
            s.get_style_context().add_provider(p2, Gtk.STYLE_PROVIDER_PRIORITY_USER + 2)
            sw.append(s)
        inner.append(sw)
        note = Gtk.Label(label="no preview in the catalog" if e.catalog
                         else "the preview couldn't be drawn" if e.failed else "drawing the preview…")
        note.add_css_class("pnote")
        inner.append(note)
        for wdg in (ph, nm, note):
            wdg.get_style_context().add_provider(prov, Gtk.STYLE_PROVIDER_PRIORITY_USER + 1)
        ph.append(inner)
        return ph

    def refresh(self, child):
        """The card again from its entry: picture, badges, hint."""
        e = child.entry
        w, h = child.size
        child.pic_slot.set_child(self.picture(e, w, h))
        child.pending_badge.set_visible(False)
        self.set_current(child, e.current)
        child.set_tooltip_text(e.hint(self.verb))

    def resize(self, child, w, h):
        child.size = (w, h)
        child.sizer.want = w
        child.sizer.queue_resize()
        child.pic_slot.set_size_request(w, h)
        child.pic_slot.get_child().set_size_request(w, h)
        child.caption.set_size_request(w, -1)

    @staticmethod
    def set_current(child, current):
        child.entry.current = current
        child.inuse_badge.set_visible(bool(current))
        (child.add_css_class if current else child.remove_css_class)("current")


class PreviewWatch:
    """Watches the preview cache for the `pending` themes (a file monitor and a 2 s timer):
    on_ready(entry) when one's picture lands (entry.preview set), on_failed(entry) when the
    renderer gave up on it; stops when none is left."""

    def __init__(self, Gio, GLib, entries, pending, on_ready, on_failed=None, on_change=None):
        self.entries = {e.name: e for e in entries}
        self.pending = pending
        self.on_ready, self.on_failed, self.on_change = on_ready, on_failed, on_change
        self.stopped = False
        os.makedirs(PV.CACHE, exist_ok=True)
        self.mon = Gio.File.new_for_path(PV.CACHE).monitor_directory(Gio.FileMonitorFlags.WATCH_MOVES, None)
        self.mon.connect("changed", lambda *_: self.check())
        GLib.timeout_add_seconds(2, self.check)

    def check(self):
        for name in list(self.pending):
            e = self.entries.get(name)
            if e is None:
                self.pending.discard(name)
                continue
            p = PV.path_for(name, e.stamp)
            if os.path.exists(p):
                e.preview, e.fresh, e.failed = p, True, None
                self.pending.discard(name)
                self.on_ready(e)
                continue
            why = PV.failure(name, e.stamp)
            if why:
                e.failed = why
                self.pending.discard(name)
                if self.on_failed:
                    self.on_failed(e)
        if self.on_change:
            self.on_change()
        return bool(self.pending) and not self.stopped

    def stop(self):
        self.stopped = True
        try:
            self.mon.cancel()
        except Exception:
            pass
