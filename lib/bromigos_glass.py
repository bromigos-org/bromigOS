"""DRIFTGLASS in GTK for the installer and the welcome tour (docs/DRIFTGLASS.md): the step rail with its icons
and progress line, VECTOR as the guide in the corner, the hologram choice cards, the disk
map with the alongside divider, the emblem ring that fills as the install goes, the live
phase list and the feature slideshow. Cairo and GTK only; the art is bromigOS's own renders
(share/bromigos-iso/art, made by tools/installer-art/make.py).

Motion only follows state (a Sweep when the divider moves, a Pulse while waiting, a Spark
when something finishes) and stops under reduced motion; the screen's one FLARE is VECTOR,
except while installing, where it's the emblem ring and VECTOR stays still.
"""
import math
import os
import time

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("GdkPixbuf", "2.0")
from gi.repository import Gdk, GdkPixbuf, GLib, Gtk  # noqa: E402

HERE = os.path.dirname(os.path.realpath(__file__))
ART_DIRS = [os.path.join(HERE, "../desktop/art"), "/usr/share/bromigos/art"]     # a checkout's, then bromigos-desktop's
EMBLEMS = ["/usr/share/bromigos/themes/wick/emblem", os.path.join(HERE, "../themes/wick/emblem")]

# each step's icon (Adwaita's symbolic set, drawn in the theme's colours)
STEP_ICONS = {
    "auto": "media-playlist-repeat-symbolic", "welcome": "preferences-desktop-locale-symbolic",
    "checks": "security-high-symbolic", "edition": "computer-symbolic", "keyboard": "input-keyboard-symbolic",
    "disk": "drive-harddisk-symbolic", "bitlocker": "dialog-password-symbolic", "user": "avatar-default-symbolic",
    "encryption": "system-lock-screen-symbolic", "ssh": "network-server-symbolic",
    "summary": "document-properties-symbolic", "install": "folder-download-symbolic", "done": "object-select-symbolic",
    # the welcome tour's
    "network": "network-wireless-signal-excellent-symbolic", "screens": "video-display-symbolic",
    "world": "weather-clear-night-symbolic", "vector": "applications-science-symbolic", "lab": "network-workgroup-symbolic",
    "phone": "phone-symbolic", "keys": "input-keyboard-symbolic",
}


def use_icon_theme():
    """Adwaita's symbolic icons (gtk4 depends on adwaita-icon-theme), drawn in our colours:
    the desktop's own icon theme may not have them all as symbolic."""
    try:
        Gtk.Settings.get_default().set_property("gtk-icon-theme-name", "Adwaita")
    except Exception:
        pass


def art(name):
    for d in ART_DIRS:
        p = os.path.normpath(os.path.join(d, name))
        if os.path.exists(p):
            return p
    return None


def rgba(h, a=1.0):
    h = h.lstrip("#")
    return int(h[0:2], 16) / 255, int(h[2:4], 16) / 255, int(h[4:6], 16) / 255, a


def icon(name, size=16, *classes):
    im = Gtk.Image.new_from_icon_name(name)
    im.set_pixel_size(size)
    for c in classes:
        im.add_css_class(c)
    return im


WICK = {"background": "#000500", "void": "#000500", "panel": "#001300", "primary": "#39ff14", "soft": "#9cff8a",
        "dim": "#159b09", "text": "#c4f5bb", "muted": "#7e927e", "faint": "#4e6b4e", "warn": "#d4af37", "danger": "#ff766f",
        "cyan": "#3fe0c5", "gold": "#f0d36a", "white": "#e8ffe0"}


def palette(c):
    """A theme's colours with the Wick's for any role it doesn't set."""
    return dict(WICK, **{k: v for k, v in (c or {}).items() if isinstance(v, str) and v.startswith("#")})


def css(c, hc=False):
    """The DRIFTGLASS layer over the window's own stylesheet."""
    c = palette(c)
    def a(h, al):
        r, g, b, _ = rgba(h)
        return f"rgba({int(r * 255)},{int(g * 255)},{int(b * 255)},{al})"
    p, cy = c["primary"], c.get("cyan", c["soft"])
    return f"""
.bi-rail {{ padding: 16px 0 0 0; }}
.bi-rail-title {{ color: {c['dim']}; font-size: 0.78em; font-weight: 700; letter-spacing: 0.2em; margin: 6px 22px 14px 22px; }}
.dg-railrow {{ padding: 6px 18px 6px 14px; }}
.dg-railrow image {{ color: {c['faint']}; }}
.dg-railrow label {{ color: {c['faint'] if not hc else c['text']}; letter-spacing: 0.08em; }}
.dg-railrow.done image, .dg-railrow.done label {{ color: {c['soft']}; }}
.dg-railrow.now {{ background-image: linear-gradient(90deg, {a(p, .22)}, {a(p, 0)}); box-shadow: inset 3px 0 {p}; }}
.dg-railrow.now image, .dg-railrow.now label {{ color: {p}; font-weight: 700; }}
.dg-railrow.now image {{ -gtk-icon-shadow: 0 0 6px {a(p, .9 if not hc else 0)}; }}
.dg-tick {{ color: {p}; }}
.dg-guide {{ margin: 10px; padding: 10px 12px 12px 12px; border: 1px solid {a(c['dim'], .6)};
  background-color: {a(c['panel'], .9)}; }}
.dg-guide-name {{ color: {p}; font-weight: 700; letter-spacing: 0.2em; font-size: 0.8em; }}
.dg-guide-line {{ color: {c['text']}; font-size: 0.92em; }}
.dg-card {{ border: 1px solid {a(c['dim'], .6)}; background-color: {a(c['panel'], .9)}; padding: 0; border-radius: 0; }}
.dg-card:hover {{ border-color: {a(p, .8)}; box-shadow: 0 0 14px {a(p, .25 if not hc else 0)}; }}
.dg-card:checked {{ border-color: {p}; box-shadow: 0 0 0 1px {p}, 0 0 22px {a(p, .35 if not hc else 0)}; background-color: {a(p, .07)}; }}
.dg-card:focus-visible {{ outline: 2px solid {c['soft']}; outline-offset: 3px; }}
.dg-card.dg-danger:checked {{ border-color: {c['danger']}; box-shadow: 0 0 0 1px {c['danger']}, 0 0 22px {a(c['danger'], .3 if not hc else 0)}; }}
.dg-card.dg-danger:checked .dg-card-title, .dg-card.dg-danger:checked image.dg-card-icon, .dg-card.dg-danger:checked .dg-check {{ color: {c['danger']}; }}
.dg-card-title {{ font-size: 1.25em; font-weight: 700; letter-spacing: 0.08em; color: {c['text']}; }}
.dg-card:checked .dg-card.dg-danger:checked {{ border-color: {c['danger']}; box-shadow: 0 0 0 1px {c['danger']}, 0 0 22px {a(c['danger'], .3 if not hc else 0)}; }}
.dg-card.dg-danger:checked .dg-card-title, .dg-card.dg-danger:checked image.dg-card-icon, .dg-card.dg-danger:checked .dg-check {{ color: {c['danger']}; }}
.dg-card-title {{ color: {p}; }}
.dg-card-text {{ color: {c['muted'] if not hc else c['text']}; }}
.dg-card image.dg-card-icon {{ color: {p}; }}
.dg-badge {{ font-size: 0.78em; font-weight: 700; letter-spacing: 0.12em; padding: 2px 8px; border: 1px solid {a(p, .7)}; color: {p}; }}
.dg-badge.warn {{ border-color: {c['warn']}; color: {c['warn']}; }}
.dg-badge.danger {{ border-color: {c['danger']}; color: {c['danger']}; }}
.dg-check {{ color: {p}; }}
.dg-legend {{ font-size: 0.85em; color: {c['muted']}; }}
.dg-legend image {{ color: {c['soft']}; }}
.dg-legend.windows, .dg-legend.windows image {{ color: {cy}; }}
.dg-legend.bromigos, .dg-legend.bromigos image {{ color: {p}; }}
.dg-legend.danger, .dg-legend.danger image {{ color: {c['danger']}; }}
.dg-diskmap:focus-visible {{ outline: 2px solid {p}; outline-offset: 2px; }}
.dg-phase {{ color: {c['faint']}; }}
.dg-phase image {{ color: {c['faint']}; }}
.dg-phase.done, .dg-phase.done image {{ color: {c['soft']}; }}
.dg-phase.now, .dg-phase.now image {{ color: {p}; font-weight: 700; }}
.dg-slide {{ border: 1px solid {a(c['dim'], .6)}; background-color: {a(c['void'], .9)}; }}
.dg-slide-line {{ color: {c['text']}; padding: 8px 12px; }}
.dg-pct {{ font-size: 2.2em; font-weight: 700; color: {p}; letter-spacing: 0.06em; }}
"""


# ── the step rail ──────────────────────────────────────────────────────────────────────
class RailLine(Gtk.DrawingArea):
    """The rail's progress line: it fills from the top to the current step."""

    def __init__(self, c, rows, here, total):
        super().__init__()
        self.c, self.rows, self.here, self.total = c, rows, here, total
        self.set_content_width(6)
        self.set_draw_func(self.draw)

    def draw(self, area, cr, w, h):
        c = self.c
        cr.set_source_rgba(*rgba(c["dim"], 0.45))
        cr.rectangle(2, 0, 2, h)
        cr.fill()
        fill = h * (self.here + 0.5) / max(1, self.total)
        cr.set_source_rgba(*rgba(c["primary"], 0.95))
        cr.rectangle(2, 0, 2, fill)
        cr.fill()
        cr.arc(3, fill, 4, 0, 2 * math.pi)
        cr.fill()


def rail(box, steps, here, STEP, c, guide=None, title="INSTALL BROMIGOS"):
    """Fill the rail: an icon and a word per step (the current one glowing, finished ones
    ticked), a progress line beside them, VECTOR at the foot."""
    while (ch := box.get_first_child()):
        box.remove(ch)
    box.set_hexpand(False)          # its rows expand inside it; the rail itself keeps its width
    box.set_size_request(232, -1)
    t = Gtk.Label(label=title, xalign=0)
    t.add_css_class("bi-rail-title")
    box.append(t)
    body = Gtk.Box(spacing=0)
    line = RailLine(c, len(steps), here, len(steps))
    line.set_margin_start(14)
    body.append(line)
    col = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, hexpand=True)
    for i, s in enumerate(steps):
        row = Gtk.Box(spacing=10)
        row.add_css_class("dg-railrow")
        row.add_css_class("now" if i == here else ("done" if i < here else "todo"))
        row.append(icon(STEP_ICONS.get(s, "media-record-symbolic"), 16))
        lab = Gtk.Label(label=STEP[s][1], xalign=0, hexpand=True)
        row.append(lab)
        if i < here:
            row.append(icon("object-select-symbolic", 14, "dg-tick"))
        row.set_tooltip_text(f"Step {i + 1} of {len(steps)}: {STEP[s][2]}" + (" (you're here)" if i == here else
                                                                              (" (done)" if i < here else "")))
        col.append(row)
    body.append(col)
    box.append(body)
    spacer = Gtk.Box(vexpand=True)
    box.append(spacer)
    if guide:
        box.append(guide)


# ── VECTOR, the guide ──────────────────────────────────────────────────────────────────
class Vector(Gtk.DrawingArea):
    """VECTOR's hologram (his own render, cut out), floating on his emitter: a slow bob and a
    breathing glow while he talks; still under reduced motion or when another FLARE has the
    screen."""

    def __init__(self, state="idle", still=False, size=(120, 178)):
        super().__init__()
        self.set_content_width(size[0])
        self.set_content_height(size[1])
        self.still = still
        self.t0 = time.monotonic()
        self.tex = None
        self.set_state(state)
        self.set_draw_func(self.draw)
        if not still:
            self.add_tick_callback(lambda *_: (self.queue_draw(), True)[1])
        self.update_property([Gtk.AccessibleProperty.LABEL], ["VECTOR, the installer's guide"])

    def set_state(self, state):
        p = art(f"vector-{state}.png") or art("vector-idle.png")
        self.tex = GdkPixbuf.Pixbuf.new_from_file(p) if p else None
        self.queue_draw()

    def draw(self, area, cr, w, h):
        if not self.tex:
            return
        t = 0 if self.still else time.monotonic() - self.t0
        tw, th = self.tex.get_width(), self.tex.get_height()
        s = min(w / tw, h / th)
        bob = 0 if self.still else 2.0 * math.sin(t * 1.3)
        cr.save()
        cr.translate((w - tw * s) / 2, (h - th * s) / 2 + bob)
        cr.scale(s, s)
        Gdk.cairo_set_source_pixbuf(cr, self.tex, 0, 0)
        cr.paint_with_alpha(1.0 if self.still else 0.88 + 0.12 * math.sin(t * 2.2))
        cr.restore()


def guide(line, state="idle", still=False, size=(120, 178)):
    """VECTOR in the corner, with one short line in his voice."""
    box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
    box.add_css_class("dg-guide")
    v = Vector(state, still, size)
    v.set_halign(Gtk.Align.CENTER)
    box.append(v)
    n = Gtk.Label(label="VECTOR", xalign=0)
    n.add_css_class("dg-guide-name")
    box.append(n)
    t = Gtk.Label(label=line, xalign=0, wrap=True, max_width_chars=22)
    t.add_css_class("dg-guide-line")
    t.set_wrap_mode(2)
    box.append(t)
    box.set_tooltip_text("VECTOR, bromigOS's AI, says what this step does")
    box.vector, box.line = v, t
    return box


# ── the hologram choice cards ──────────────────────────────────────────────────────────
def holo_card(picture, icon_name, title, lines, active, group=None, width=360):
    """A big choice card: its hologram, an icon and a title, two lines; it glows on hover
    and when chosen (a radio group of toggle buttons: arrow keys and Space work)."""
    b = Gtk.ToggleButton(active=active)
    b.add_css_class("dg-card")
    if group:
        b.set_group(group)
    v = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
    p = art(picture) if picture else None
    if p:
        pic = Gtk.Picture.new_for_filename(p)
        pic.set_content_fit(Gtk.ContentFit.COVER)
        pic.set_size_request(width, int(width * 0.55))
        v.append(pic)
    body = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6, margin_top=12, margin_bottom=14, margin_start=16,
                   margin_end=16)
    head = Gtk.Box(spacing=10)
    head.append(icon(icon_name, 22, "dg-card-icon"))
    t = Gtk.Label(label=title, xalign=0, hexpand=True, wrap=True)
    t.add_css_class("dg-card-title")
    head.append(t)
    tick = icon("object-select-symbolic", 20, "dg-check")
    tick.set_visible(active)
    head.append(tick)
    b.connect("toggled", lambda w: tick.set_visible(w.get_active()))
    body.append(head)
    for ln in lines:
        lab = Gtk.Label(label=ln, xalign=0, wrap=True)
        lab.set_wrap_mode(2)
        lab.add_css_class("dg-card-text")
        body.append(lab)
    v.append(body)
    b.set_child(v)
    return b


# ── the disk map ───────────────────────────────────────────────────────────────────────
def drive_icon(d):
    kind = (d.get("kind") or "").upper()
    if d.get("removable") or kind == "USB":
        return "drive-harddisk-usb-symbolic"
    if kind == "NVME" or d.get("ssd") or d.get("rotational") is False:
        return "drive-harddisk-solidstate-symbolic"
    return "drive-harddisk-symbolic"


def segments(d):
    """The disk in order: (role, bytes, words), role one of efi, msr, windows, recovery,
    linux, other, free."""
    out, pos = [], 0
    parts = sorted(d.get("partitions") or [], key=lambda p: p.get("start", 0))
    frees = sorted(d.get("free") or [], key=lambda f: f["start"])
    for p in parts:
        for f in frees:
            if pos <= f["start"] < p.get("start", 0) and f["size"] > 64 * 2**20:
                out.append(("free", f["size"], "Free space"))
        if p.get("esp"):
            role = "efi"
        elif "Microsoft reserved" in (p.get("what") or ""):
            role = "msr"
        elif p.get("windows"):
            role = "windows"
        elif "recovery" in (p.get("what") or "").lower():
            role = "recovery"
        elif p.get("fstype") in ("btrfs", "ext4", "crypto_LUKS", "xfs"):
            role = "linux"
        else:
            role = "other"
        out.append((role, p["size"], p.get("what") or p["path"], p))
        pos = p.get("start", 0) + p["size"]
    for f in frees:
        if f["start"] >= pos and f["size"] > 64 * 2**20:
            out.append(("free", f["size"], "Free space"))
    return [s if len(s) == 4 else s + (None,) for s in out]


class DiskMap(Gtk.DrawingArea):
    """The disk as one bar of its partitions, in order, each in its colour with its icon.
    Alongside (making room): the other system's partition splits at a divider you drag or
    move with the keys, each side's minimum striped, a Sweep across bromigOS's new part
    when it moves. Erase: the whole bar turns bromigOS, with a danger edge."""

    MINW = 34

    def __init__(self, d, c, mode, al=None, value=None, still=False, height=74):
        super().__init__(accessible_role=Gtk.AccessibleRole.SLIDER if (mode == "alongside" and al and al.get("mode") == "shrink")
                         else Gtk.AccessibleRole.IMG)
        self.d, self.c, self.mode, self.al, self.still = d, c, mode, al or {}, still
        self.segs = segments(d)
        self.split = self.mode == "alongside" and self.al.get("mode") == "shrink"
        if self.split:
            total = self.al["part_size"] + self.al["free_after"]
            self.total = total / 2**30
            self.lo, self.hi = (total - self.al["max"]) / 2**30, (total - self.al["min"]) / 2**30
            self.value = max(self.lo, min(self.hi, value if value is not None else self.lo))
        self.on_change = None
        self.sweep_at = None
        self.set_content_height(height)
        self.set_hexpand(True)
        self.add_css_class("dg-diskmap")
        self.set_draw_func(self.draw)
        if self.split:
            self.set_focusable(True)
            keys = Gtk.EventControllerKey()
            keys.connect("key-pressed", self._key)
            self.add_controller(keys)
            click = Gtk.GestureClick()
            click.connect("pressed", lambda g, n, x, y: (self.grab_focus(), self._at(x)))
            self.add_controller(click)
            drag = Gtk.GestureDrag()
            drag.connect("drag-update", lambda g, dx, dy: self._at(g.get_start_point()[1] + dx))
            self.add_controller(drag)
            focus = Gtk.EventControllerFocus()
            focus.connect("enter", lambda *_: self.queue_draw())
            focus.connect("leave", lambda *_: self.queue_draw())
            self.add_controller(focus)
            self._a11y()
        else:
            self.update_property([Gtk.AccessibleProperty.LABEL], ["The disk: " + "; ".join(s[2] for s in self.segs)])

    # the layout: tiny partitions get room for their icon, the rest share what's left
    def _layout(self, width):
        x0, x1 = 4, width - 4
        span = x1 - x0
        big = [s for s in self.segs if s[1] / max(1, self.d["size"]) * span >= self.MINW]
        small = len(self.segs) - len(big)
        room = span - small * self.MINW
        bigsum = sum(s[1] for s in big) or 1
        out, x = [], x0
        for s in self.segs:
            w = self.MINW if s not in big else room * s[1] / bigsum
            out.append((s, x, x + w))
            x += w
        return out

    def _a11y(self):
        try:
            self.update_property(
                [Gtk.AccessibleProperty.LABEL, Gtk.AccessibleProperty.VALUE_MIN, Gtk.AccessibleProperty.VALUE_MAX,
                 Gtk.AccessibleProperty.VALUE_NOW, Gtk.AccessibleProperty.VALUE_TEXT],
                [f"Room for {self.al.get('who', 'the other system')}, in gigabytes", float(self.lo), float(self.hi),
                 float(self.value), f"{self.al.get('who')} {self.value:.0f} GB, bromigOS {self.total - self.value:.0f} GB"])
        except Exception:
            pass

    def set_value(self, v):
        v = max(self.lo, min(self.hi, round(v)))
        if v != self.value:
            self.value = v
            self._a11y()
            if not self.still:
                if self.sweep_at is None:
                    self.add_tick_callback(self._tick)
                self.sweep_at = time.monotonic()
            self.queue_draw()
            if self.on_change:
                self.on_change(v)

    def _tick(self, *_):
        self.queue_draw()
        if self.sweep_at and time.monotonic() - self.sweep_at > 0.7:
            self.sweep_at = None
            return False
        return True

    def _region(self, width):
        for s, a, b in self._layout(width):
            if s[0] == "windows" and s[3] and s[3]["path"] == self.al.get("partition"):
                return a, b
        return 4, width - 4

    def _at(self, x):
        a, b = self._region(self.get_width())
        self.set_value((x - a) / max(1, b - a) * self.total)

    def _key(self, ctl, keyval, code, state):
        step = {Gdk.KEY_Left: -1, Gdk.KEY_Right: 1, Gdk.KEY_Page_Down: -10, Gdk.KEY_Page_Up: 10}.get(keyval)
        if step:
            self.set_value(self.value + step)
            return True
        if keyval in (Gdk.KEY_Home, Gdk.KEY_End):
            self.set_value(self.lo if keyval == Gdk.KEY_Home else self.hi)
            return True
        return False

    # drawing
    def _fill(self, cr, role):
        c = self.c
        col = {"efi": (c.get("gold", c["warn"]), 0.55), "msr": (c["faint"], 0.7), "windows": (c.get("cyan", c["soft"]), 0.55),
               "recovery": (c.get("cyan", c["soft"]), 0.28), "linux": (c["soft"], 0.45), "other": (c["muted"], 0.4),
               "free": (c["faint"], 0.18), "bromigos": (c["primary"], 0.88)}[role]
        cr.set_source_rgba(*rgba(*col))

    def _stripes(self, cr, a, b, y0, y1, colour, alpha=0.6, gap=7):
        cr.save()
        cr.rectangle(a, y0, b - a, y1 - y0)
        cr.clip()
        cr.set_source_rgba(*rgba(colour, alpha))
        cr.set_line_width(2)
        x = a - (y1 - y0)
        while x < b:
            cr.move_to(x, y1)
            cr.line_to(x + (y1 - y0), y0)
            x += gap
        cr.stroke()
        cr.restore()

    def _glyph(self, cr, role, cx, cy, s):
        """Each partition's mark, drawn: Windows' four panes, the EFI chip, recovery's arrow,
        bromigOS's flame-diamond, free space's dashes."""
        c = self.c
        cr.save()
        cr.set_line_width(1.6)
        if role == "windows":
            cr.set_source_rgba(*rgba(c["white"] if "white" in c else c["text"]))
            g = s * 0.12
            q = (s - g) / 2
            for dx in (0, q + g):
                for dy in (0, q + g):
                    cr.rectangle(cx - s / 2 + dx, cy - s / 2 + dy, q, q)
            cr.fill()
        elif role == "efi":
            cr.set_source_rgba(*rgba(c["text"]))
            cr.rectangle(cx - s * 0.32, cy - s * 0.32, s * 0.64, s * 0.64)
            cr.stroke()
            for i in range(3):
                o = -s * 0.2 + i * s * 0.2
                for (x1, y1, x2, y2) in ((cx + o, cy - s * 0.32, cx + o, cy - s * 0.5), (cx + o, cy + s * 0.32, cx + o, cy + s * 0.5),
                                         (cx - s * 0.32, cy + o, cx - s * 0.5, cy + o), (cx + s * 0.32, cy + o, cx + s * 0.5, cy + o)):
                    cr.move_to(x1, y1)
                    cr.line_to(x2, y2)
            cr.stroke()
        elif role == "recovery":
            cr.set_source_rgba(*rgba(c["text"]))
            cr.arc(cx, cy, s * 0.36, math.pi * 0.25, math.pi * 1.85)
            cr.stroke()
            cr.move_to(cx + s * 0.36 * math.cos(math.pi * 1.85) + 4, cy + s * 0.36 * math.sin(math.pi * 1.85))
            cr.rel_line_to(-5, -4)
            cr.rel_line_to(1, 6)
            cr.close_path()
            cr.fill()
        elif role == "bromigos":
            cr.set_source_rgba(*rgba(c["void"]))
            cr.move_to(cx, cy - s * 0.5)
            cr.line_to(cx + s * 0.32, cy)
            cr.line_to(cx, cy + s * 0.5)
            cr.line_to(cx - s * 0.32, cy)
            cr.close_path()
            cr.fill()
        elif role == "msr":
            pass
        else:
            cr.set_source_rgba(*rgba(c["muted"]))
            for i in range(3):
                cr.rectangle(cx - s * 0.4 + i * s * 0.3, cy - 1, s * 0.18, 2)
            cr.fill()
        cr.restore()

    def draw(self, area, cr, width, height):
        c = self.c
        y0, y1 = 14, height - 14
        lay = self._layout(width)
        erase = self.mode == "erase"
        if erase:
            x0, x1 = lay[0][1], lay[-1][2]
            for s, a, b in lay:                       # what's there now, fading under bromigOS
                self._fill(cr, s[0])
                cr.rectangle(a, y0, b - a, y1 - y0)
                cr.fill()
            cr.set_source_rgba(*rgba(c["primary"], 0.82))
            cr.rectangle(x0, y0, x1 - x0, y1 - y0)
            cr.fill()
            self._glyph(cr, "bromigos", (x0 + x1) / 2, (y0 + y1) / 2, (y1 - y0) * 0.55)
            cr.set_source_rgba(*rgba(c["danger"]))         # the danger edge: everything here goes
            cr.set_line_width(3)
            cr.rectangle(x0 - 1.5, y0 - 1.5, x1 - x0 + 3, y1 - y0 + 3)
            cr.stroke()
            self._stripes(cr, x0 - 6, x0 - 1, y0, y1, c["danger"], 0.9, 5)
            self._stripes(cr, x1 + 1, x1 + 6, y0, y1, c["danger"], 0.9, 5)
            return
        for s, a, b in lay:
            role = s[0]
            if self.split and role == "windows" and s[3] and s[3]["path"] == self.al.get("partition"):
                at = lambda gb: a + (b - a) * gb / self.total      # noqa: E731
                cut = at(self.value)
                self._fill(cr, "windows")
                cr.rectangle(a, y0, cut - a, y1 - y0)
                cr.fill()
                self._fill(cr, "bromigos")
                cr.rectangle(cut, y0, b - cut, y1 - y0)
                cr.fill()
                if self.sweep_at is not None:          # the Sweep: light across the new part
                    k = (time.monotonic() - self.sweep_at) / 0.7
                    sx = cut + (b - cut) * k
                    grad_w = 40
                    cr.save()
                    cr.rectangle(cut, y0, b - cut, y1 - y0)
                    cr.clip()
                    for i in range(grad_w):
                        cr.set_source_rgba(1, 1, 1, 0.28 * (1 - i / grad_w))
                        cr.rectangle(sx - i, y0, 1, y1 - y0)
                        cr.fill()
                    cr.restore()
                self._stripes(cr, a, at(self.lo), y0, y1, c["void"], 0.55)
                self._stripes(cr, at(self.hi), b, y0, y1, c["void"], 0.55)
                for x in (at(self.lo), at(self.hi)):
                    cr.set_source_rgba(*rgba(c["text"], 0.8))
                    cr.rectangle(x - 1, y0 - 5, 2, y1 - y0 + 10)
                    cr.fill()
                sz = (y1 - y0) * 0.42
                if cut - a > sz * 2:
                    self._glyph(cr, "windows", (a + cut) / 2, (y0 + y1) / 2, sz)
                if b - cut > sz * 2:
                    self._glyph(cr, "bromigos", (cut + b) / 2, (y0 + y1) / 2, sz * 1.2)
                cr.set_source_rgba(*rgba(c["text"]))     # the divider
                cr.rectangle(cut - 4, y0 - 10, 8, y1 - y0 + 20)
                cr.fill()
                cr.set_source_rgba(*rgba(c["void"]))
                for dy in (-6, 0, 6):
                    cr.rectangle(cut - 2, (y0 + y1) / 2 + dy - 1, 4, 2)
                cr.fill()
                if self.has_focus():
                    cr.set_source_rgba(*rgba(c["primary"]))
                    cr.set_line_width(2)
                    cr.rectangle(cut - 8, y0 - 13, 16, y1 - y0 + 26)
                    cr.stroke()
                continue
            target = (self.mode == "alongside" and not self.split and role == "free")
            self._fill(cr, "bromigos" if target else role)
            cr.rectangle(a, y0, b - a, y1 - y0)
            cr.fill()
            if role == "free" and not target:
                self._stripes(cr, a, b, y0, y1, c["faint"], 0.5, 6)
            self._glyph(cr, "bromigos" if target else role, (a + b) / 2, (y0 + y1) / 2, min(b - a - 8, (y1 - y0) * 0.42))
            cr.set_source_rgba(*rgba(c["void"]))
            cr.rectangle(b - 1, y0, 2, y1 - y0)
            cr.fill()
        cr.set_source_rgba(*rgba(c["dim"], 0.9))
        cr.set_line_width(1)
        cr.rectangle(lay[0][1] + 0.5, y0 + 0.5, lay[-1][2] - lay[0][1] - 1, y1 - y0 - 1)
        cr.stroke()


def legend_item(icon_name, text, role):
    b = Gtk.Box(spacing=6)
    b.add_css_class("dg-legend")
    b.add_css_class(role)
    b.append(icon(icon_name, 14))
    lab = Gtk.Label(label=text, xalign=0, wrap=True)
    lab.set_wrap_mode(2)
    b.append(lab)
    return b


# ── installing ─────────────────────────────────────────────────────────────────────────
class EmblemRing(Gtk.DrawingArea):
    """The Hero while installing: the burn-in emblem with a ring around it that fills as the
    install goes, a Scanline drifting over it and a Sweep riding the ring's edge (still under
    reduced motion)."""

    def __init__(self, c, size=300, still=False):
        super().__init__()
        self.c, self.still, self.pct = c, still, 0
        self.t0 = time.monotonic()
        self.set_content_width(size)
        self.set_content_height(size)
        self.emb = None
        for d in EMBLEMS:
            for name in ("emblem-512.png", "emblem-1024.png"):
                p = os.path.normpath(os.path.join(d, name))
                if os.path.exists(p):
                    self.emb = GdkPixbuf.Pixbuf.new_from_file(p)
                    break
            if self.emb:
                break
        self.set_draw_func(self.draw)
        if not still:
            self.add_tick_callback(lambda *_: (self.queue_draw(), True)[1])
        self.update_property([Gtk.AccessibleProperty.LABEL], ["Install progress"])

    def set_pct(self, pct):
        self.pct = max(0, min(100, pct))
        try:
            self.update_property([Gtk.AccessibleProperty.VALUE_TEXT], [f"{self.pct} percent"])
        except Exception:
            pass
        self.queue_draw()

    def draw(self, area, cr, w, h):
        c = self.c
        t = 0 if self.still else time.monotonic() - self.t0
        cx, cy = w / 2, h / 2
        r = min(w, h) / 2 - 10
        # the track and the filled arc, with a glow
        cr.set_line_width(10)
        cr.set_source_rgba(*rgba(c["dim"], 0.35))
        cr.arc(cx, cy, r, 0, 2 * math.pi)
        cr.stroke()
        end = -math.pi / 2 + 2 * math.pi * self.pct / 100
        for wdt, al in ((22, 0.10), (16, 0.18), (10, 1.0)):
            cr.set_line_width(wdt)
            cr.set_source_rgba(*rgba(c["primary"], al))
            cr.arc(cx, cy, r, -math.pi / 2, end)
            cr.stroke()
        if self.pct > 0 and not self.still:         # a Sweep riding the edge of the fill
            cr.set_source_rgba(1, 1, 1, 0.55 + 0.35 * math.sin(t * 4))
            cr.arc(cx + r * math.cos(end), cy + r * math.sin(end), 6, 0, 2 * math.pi)
            cr.fill()
        for i in range(60):                         # ticks, lit as far as it has got
            a = -math.pi / 2 + 2 * math.pi * i / 60
            lit = i / 60 <= self.pct / 100
            cr.set_source_rgba(*rgba(c["primary"] if lit else c["faint"], 0.9 if lit else 0.5))
            cr.set_line_width(2)
            cr.move_to(cx + (r - 20) * math.cos(a), cy + (r - 20) * math.sin(a))
            cr.line_to(cx + (r - 26 - (4 if i % 5 == 0 else 0)) * math.cos(a), cy + (r - 26 - (4 if i % 5 == 0 else 0)) * math.sin(a))
            cr.stroke()
        if self.emb:
            s = (r - 34) * 2 / self.emb.get_width()
            cr.save()
            cr.arc(cx, cy, r - 32, 0, 2 * math.pi)
            cr.clip()
            cr.translate(cx, cy)
            cr.rotate(0 if self.still else -2 * math.pi * (t % 24) / 24)
            cr.scale(s, s)
            Gdk.cairo_set_source_pixbuf(cr, self.emb, -self.emb.get_width() / 2, -self.emb.get_height() / 2)
            cr.paint_with_alpha(0.9)
            cr.restore()
        # the Scanline over it all
        cr.save()
        cr.arc(cx, cy, r + 12, 0, 2 * math.pi)
        cr.clip()
        cr.set_source_rgba(0, 0, 0, 0.18)
        for y in range(0, h, 3):
            cr.rectangle(0, y, w, 1)
        cr.fill()
        if not self.still:
            sy = (t * 60) % (h + 60) - 30
            cr.set_source_rgba(*rgba(c["primary"], 0.08))
            cr.rectangle(0, sy, w, 26)
            cr.fill()
        cr.restore()


PHASES = [  # (key, icon, words, the stage words that mean it has begun)
    ("room", "drive-harddisk-symbolic", "Making room", ("Making room",)),
    ("disk", "media-flash-symbolic", "Preparing the disk", ("Preparing the disk", "Opening your")),
    ("copy", "folder-download-symbolic", "Copying bromigOS onto the disk", ("Copying", "Installing")),
    ("people", "avatar-default-symbolic", "Your account and your desktop", ("Setting up", "Bringing back", "Your account")),
    ("boot", "system-reboot-symbolic", "The boot menu and snapshots", ("boot menu", "Boot", "snapshots")),
]


def phase_list(c, shrink, now_text, pct):
    """The install's phases, each with its icon: done ones ticked, the current one lit."""
    box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
    phases = [p for p in PHASES if shrink or p[0] != "room"]
    cur = 0
    for i, p in enumerate(phases):
        if any(w.lower() in (now_text or "").lower() for w in p[3]):
            cur = i
    if pct >= 100:
        cur = len(phases)
    for i, (key, ic, words, _) in enumerate(phases):
        row = Gtk.Box(spacing=10)
        row.add_css_class("dg-phase")
        row.add_css_class("done" if i < cur else ("now" if i == cur else "todo"))
        row.append(icon("object-select-symbolic" if i < cur else ic, 16))
        row.append(Gtk.Label(label=(now_text if i == cur and now_text else words), xalign=0, wrap=True))
        box.append(row)
    return box


FEATURES = [
    ("feature-desktop.jpg", "The desktop reads your machine: the panels show what it's doing, live."),
    ("feature-holodeck.jpg", "Super+H opens the holodeck: your lab and this machine as holograms."),
    ("feature-den.jpg", "The den: your music and TV in the same room as your work."),
    ("feature-lab.jpg", "Your lab's console: every machine, its jobs and its health in one place."),
    ("feature-settings.jpg", "Settings has everything in plain words, and every choice can be changed later."),
]


class Slideshow(Gtk.Box):
    """What's coming: real bromigOS screens, one line each, changing every 9 s (still under
    reduced motion: the first one stays)."""

    def __init__(self, still=False, width=420):
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        self.add_css_class("dg-slide")
        self.items = [(art(p), w) for p, w in FEATURES if art(p)]
        self.pic = Gtk.Picture()
        self.pic.set_content_fit(Gtk.ContentFit.COVER)
        self.pic.set_size_request(width, int(width * 0.56))
        self.line = Gtk.Label(xalign=0, wrap=True)
        self.line.add_css_class("dg-slide-line")
        self.append(self.pic)
        self.append(self.line)
        self.i = 0
        self.show_one()
        if not still and len(self.items) > 1:
            GLib.timeout_add_seconds(9, self.next)

    def show_one(self):
        if self.items:
            p, w = self.items[self.i % len(self.items)]
            self.pic.set_filename(p)
            self.line.set_label(w)
            self.set_tooltip_text("A look at bromigOS while it installs: " + w)

    def next(self):
        if not self.get_root():
            return False
        self.i += 1
        self.show_one()
        return True


# ── the phone, for pairing ─────────────────────────────────────────────────────────────
class PhoneFrame(Gtk.Overlay):
    """The pairing QR inside a holographic phone on its Emitter: a Pulse breathing in the
    frame while it waits for the phone, a Spark when it's paired (then a ✓ instead of the
    QR). Still under reduced motion: the frame glows evenly and the ✓ just appears."""

    def __init__(self, c, size=230, still=False):
        super().__init__()
        self.c, self.size, self.still = c, size, still
        self.state, self.spark_at, self.qr = "waiting", None, None
        self.t0 = time.monotonic()
        self.frame = Gtk.DrawingArea()
        self.frame.set_content_width(int(size * 0.86))
        self.frame.set_content_height(int(size * 1.32))
        self.frame.set_draw_func(self.draw)
        self.set_child(self.frame)
        if not still:
            self.frame.add_tick_callback(lambda *_: (self.frame.queue_draw(), True)[1])
        self.update_property([Gtk.AccessibleProperty.LABEL], ["The pairing code, on a phone"])

    def set_qr(self, path):
        """The QR (a PNG or SVG file), drawn on the phone's screen; None clears it."""
        q = int(self.size * 0.66)
        try:
            self.qr = GdkPixbuf.Pixbuf.new_from_file_at_size(path, q, q) if path else None
        except Exception:
            self.qr = None
        self.frame.queue_draw()

    def set_state(self, state):
        if state == "paired" and self.state != "paired":
            self.spark_at = time.monotonic()
        self.state = state
        self.frame.queue_draw()

    def draw(self, area, cr, w, h):
        c = self.c
        t = 0 if self.still else time.monotonic() - self.t0
        x0, y0, x1, y1 = w * 0.06, 6, w * 0.94, h * 0.84
        r = 18
        # the Emitter it stands on
        cx, ey = w / 2, h * 0.92
        for k, al in ((1.0, 0.18), (0.72, 0.3), (0.44, 0.5)):
            cr.save()
            cr.translate(cx, ey)
            cr.scale(1, 0.24)
            cr.set_source_rgba(*rgba(c["primary"], al))
            cr.set_line_width(3)
            cr.arc(0, 0, w * 0.46 * k, 0, 2 * math.pi)
            cr.restore()
            cr.stroke()
        # light rising from the Emitter
        for i in range(10):
            cr.set_source_rgba(*rgba(c["primary"], 0.05))
            cr.rectangle(x0 + (x1 - x0) * 0.08 + i * (x1 - x0) * 0.09, y1, 3, ey - y1)
            cr.fill()
        # the frame: brighter with the Pulse while waiting, a Spark when paired
        glow = 0.75
        if self.state == "waiting" and not self.still:
            glow = 0.55 + 0.4 * (0.5 + 0.5 * math.sin(t * 2.4))
        if self.spark_at is not None:
            age = time.monotonic() - self.spark_at
            glow = 1.0 if self.still else 0.75 + 0.6 * max(0.0, 1 - age)
        def rr(pad=0):
            cr.new_path()
            cr.arc(x1 - r, y0 + r, r, -math.pi / 2, 0)
            cr.arc(x1 - r, y1 - r, r, 0, math.pi / 2)
            cr.arc(x0 + r, y1 - r, r, math.pi / 2, math.pi)
            cr.arc(x0 + r, y0 + r, r, math.pi, 3 * math.pi / 2)
            cr.close_path()
        cr.set_source_rgba(*rgba(c["panel"], 0.92))
        rr(0)
        cr.fill()
        for lw, al in ((10, 0.08 * glow), (5, 0.2 * glow), (2, min(1.0, glow))):
            cr.set_line_width(lw)
            cr.set_source_rgba(*rgba(c["primary"], al))
            rr(0)
            cr.stroke()
        sx0, sy0, sx1, sy1 = x0 + 8, y0 + 22, x1 - 8, y1 - 10
        cr.set_source_rgba(0, 0, 0, 0.16)            # the screen's scanlines, under the code
        y = sy0
        while y < sy1:
            cr.rectangle(sx0, y, sx1 - sx0, 1)
            y += 3
        cr.fill()
        if self.state == "paired":                   # the ✓, drawn
            cx2, cy2, k = (sx0 + sx1) / 2, (sy0 + sy1) / 2, (sx1 - sx0) * 0.3
            for lw, al in ((14, 0.15 * glow), (6, min(1.0, glow))):
                cr.set_line_width(lw)
                cr.set_source_rgba(*rgba(c["primary"], al))
                cr.move_to(cx2 - k, cy2)
                cr.line_to(cx2 - k * 0.3, cy2 + k * 0.7)
                cr.line_to(cx2 + k, cy2 - k * 0.8)
                cr.stroke()
        elif self.qr:                                # the code, on a white card for the camera
            q = self.qr.get_width()
            qx, qy = (sx0 + sx1 - q) / 2, sy0 + (sy1 - sy0 - q) / 2
            cr.set_source_rgba(1, 1, 1, 1)
            cr.rectangle(qx - 6, qy - 6, q + 12, q + 12)
            cr.fill()
            Gdk.cairo_set_source_pixbuf(cr, self.qr, qx, qy)
            cr.paint()
        # the speaker slot and the screen's scanlines
        cr.set_source_rgba(*rgba(c["primary"], 0.6))
        cr.rectangle(cx - 18, y0 + 10, 36, 4)
        cr.fill()
