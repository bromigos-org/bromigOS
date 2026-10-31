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
gi.require_version("PangoCairo", "1.0")
from gi.repository import Gdk, GdkPixbuf, GLib, Gtk, Pango, PangoCairo  # noqa: E402

try:    # bromigos-desktop's holograms, Sweep and bars (the welcome tour's; the live ISO may not have them)
    import bromigos_driftglass as DG
except ImportError:
    DG = None

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

# the words of the lore's dossier, for the About you card (bromigos.org's operator dossiers)
DOSSIER_HEAD = "OPERATOR ID"


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
        "cyan": "#3fe0c5", "gold": "#f0d36a", "white": "#e8ffe0", "selection": "#003b00"}


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
.dg-section {{ color: {p}; font-weight: 700; letter-spacing: 0.2em; font-size: 0.8em; }}
.dg-panel {{ border: 1px solid {a(c['dim'], .6)}; background-color: {a(c['panel'], .9)}; }}
.dg-muted {{ color: {c['muted'] if not hc else c['text']}; }}
.dg-strong {{ color: {c['text']}; font-weight: 700; }}
/* About you: the operator ID card, in the dossier's look */
.dg-dossier {{ border: 1px solid {a(p, .55)}; background-color: {a(c['panel'], .92)};
  box-shadow: 0 0 22px {a(p, .10 if not hc else 0)}; }}
.dg-dossier-head {{ background-color: {a(p, .12)}; border-bottom: 1px solid {a(p, .45)}; padding: 6px 16px; }}
.dg-dossier-head label {{ color: {p}; font-weight: 700; letter-spacing: 0.22em; font-size: 0.78em; }}
.dg-dossier-head label.dg-dossier-serial {{ color: {c['soft']}; font-weight: 400; }}
.dg-dossier-name {{ font-size: 1.45em; font-weight: 700; letter-spacing: 0.1em; color: {c['text']}; }}
.dg-dossier-name.empty {{ color: {c['faint'] if not hc else c['text']}; }}
.dg-dossier-handle {{ color: {c['soft']}; letter-spacing: 0.04em; }}
.dg-dossier-key {{ color: {c['muted'] if not hc else c['text']}; font-size: 0.78em; letter-spacing: 0.16em; font-weight: 700; }}
.dg-dossier list, .dg-dossier .boxed-list {{ border-left: none; border-right: none; border-bottom: none; }}
.dg-chip {{ font-size: 0.78em; font-weight: 700; letter-spacing: 0.12em; padding: 2px 8px; border: 1px solid {a(p, .7)}; color: {p}; }}
.dg-chip.warn {{ border-color: {c['warn']}; color: {c['warn']}; }}
.dg-chip.danger {{ border-color: {c['danger']}; color: {c['danger']}; }}
.dg-chip.quiet {{ border-color: {a(c['dim'], .7)}; color: {c['muted'] if not hc else c['text']}; }}
.dg-valid {{ font-weight: 700; font-size: 1.3em; min-width: 22px; }}
.dg-valid.ok {{ color: {p}; }}
.dg-valid.bad {{ color: {c['warn']}; }}
/* the strength meter: a discrete level bar, its filled blocks in the level's colour */
levelbar.dg-meter block {{ min-height: 8px; min-width: 14px; border-radius: 0; border: none; margin: 0 1px; }}
levelbar.dg-meter block.empty {{ background-color: {a(c['dim'], .28)}; }}
levelbar.dg-meter block.filled {{ background-color: {p}; }}
levelbar.dg-meter block.filled.weak {{ background-color: {c['danger']}; }}
levelbar.dg-meter block.filled.fair {{ background-color: {c['warn']}; }}
levelbar.dg-meter block.filled.strong {{ background-color: {p}; box-shadow: 0 0 6px {a(p, .5 if not hc else 0)}; }}
.dg-meter-word {{ font-weight: 700; letter-spacing: 0.12em; font-size: 0.85em; }}
.dg-meter-word.weak {{ color: {c['danger']}; }}
.dg-meter-word.fair {{ color: {c['warn']}; }}
.dg-meter-word.strong {{ color: {p}; }}
/* the briefing: one row per choice, with its icon and an Edit link */
.dg-brief {{ border: 1px solid {a(c['dim'], .6)}; background-color: {a(c['panel'], .9)}; }}
.dg-brief-head {{ background-color: {a(p, .10)}; border-bottom: 1px solid {a(p, .4)}; padding: 6px 16px; }}
.dg-brief-head label {{ color: {p}; font-weight: 700; letter-spacing: 0.22em; font-size: 0.78em; }}
.dg-brief-row {{ padding: 9px 16px; border-bottom: 1px solid {a(c['dim'], .3)}; }}
.dg-brief-row:last-child {{ border-bottom: none; }}
.dg-brief-row image.dg-brief-icon {{ color: {p}; }}
.dg-brief-row.danger image.dg-brief-icon, .dg-brief-row.danger .dg-brief-val {{ color: {c['danger']}; }}
.dg-brief-key {{ color: {c['muted'] if not hc else c['text']}; font-size: 0.76em; letter-spacing: 0.16em; font-weight: 700; }}
.dg-brief-val {{ color: {c['text']}; }}
button.dg-edit {{ color: {c['soft']}; padding: 2px 12px; min-height: 0; border: 1px solid {a(c['dim'], .7)};
  background: none; box-shadow: none; font-size: 0.85em; letter-spacing: 0.1em; }}
button.dg-edit:hover {{ color: {p}; border-color: {p}; background-color: {a(p, .08)}; }}
button.dg-edit:focus-visible {{ outline: 2px solid {c['soft']}; outline-offset: 2px; }}
.dg-note {{ border-left: 3px solid {c['warn']}; padding: 8px 14px; background-color: {a(c['warn'], .07)}; color: {c['text']}; }}
.dg-note.danger {{ border-left-color: {c['danger']}; background-color: {a(c['danger'], .07)}; }}
/* Before you start: one card per thing worth knowing */
.dg-check-card {{ border: 1px solid {a(c['warn'], .55)}; border-left: 3px solid {c['warn']}; background-color: {a(c['warn'], .05)};
  padding: 12px 16px; }}
.dg-check-card image.dg-check-icon {{ color: {c['warn']}; }}
.dg-check-card .dg-check-title {{ color: {c['warn']}; font-weight: 700; letter-spacing: 0.06em; font-size: 1.05em; }}
.dg-check-fix {{ color: {c['text']}; }}
.dg-check-fix-key {{ color: {c['warn']}; font-size: 0.76em; letter-spacing: 0.16em; font-weight: 700; }}
.dg-pass {{ color: {c['soft']}; }}
.dg-pass image {{ color: {p}; }}
.dg-pass .dg-pass-what {{ color: {c['muted'] if not hc else c['text']}; font-size: 0.9em; }}
/* keys: keycaps, and the tour's key cards */
.dg-keycap {{ border: 1px solid {a(c['soft'], .7)}; border-bottom-width: 3px; padding: 2px 10px; color: {c['soft']};
  font-weight: 700; letter-spacing: 0.08em; background-color: {a(c['void'], .6)}; }}
.dg-keyplus {{ color: {c['muted']}; font-weight: 700; }}
.dg-keycard {{ border: 1px solid {a(c['dim'], .6)}; background-color: {a(c['panel'], .9)}; padding: 14px 16px; }}
.dg-keycard image.dg-keycard-icon {{ color: {c['dim'] if not hc else c['text']}; }}
.dg-keycard.lit {{ border-color: {p}; box-shadow: 0 0 0 1px {p}, 0 0 18px {a(p, .35 if not hc else 0)}; background-color: {a(p, .07)}; }}
.dg-keycard.lit image.dg-keycard-icon, .dg-keycard.lit .dg-keycard-state {{ color: {p}; }}
.dg-keycard.lit .dg-keycap {{ border-color: {p}; color: {p}; }}
.dg-keycard-state {{ color: {c['muted'] if not hc else c['text']}; font-size: 0.9em; letter-spacing: 0.06em; }}
/* the failure */
.dg-fail {{ border: 1px solid {a(c['danger'], .7)}; background-color: {a(c['danger'], .06)}; padding: 14px 18px; }}
.bi-heading.bi-danger {{ color: {c['danger']}; text-shadow: 0 0 8px {a(c['danger'], .25 if not hc else 0)}; }}
/* numbered next steps */
.dg-num {{ color: {c['void']}; background-color: {p}; font-weight: 700; min-width: 24px; min-height: 24px; border-radius: 12px; }}
.dg-stepline {{ color: {c['text']}; }}
/* rows' prefix icons */
row image.dg-row-icon, .dg-row-icon {{ color: {p}; }}
/* the welcome tour's world hero */
.dg-hero {{ border: 1px solid {a(p, .55)}; background-color: {c['void']}; }}
.dg-hero-cap {{ background-color: {a(c['void'], .78)}; padding: 8px 14px; }}
.dg-hero-name {{ color: {p}; font-weight: 700; letter-spacing: 0.2em; font-size: 1.15em; }}
.dg-hero-tag {{ color: {c['text']}; }}
flowboxchild.card:hover {{ box-shadow: 0 0 16px {a(p, .32 if not hc else 0)}; }}
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


# ── shared drawing helpers ─────────────────────────────────────────────────────────────
def _emitter(cr, c, cx, ey, rx, glow=1.0):
    """The Emitter a hologram stands on: three flat rings."""
    for k, al in ((1.0, 0.25), (0.72, 0.4), (0.44, 0.6)):
        cr.save()
        cr.translate(cx, ey)
        cr.scale(1, 0.24)
        cr.arc(0, 0, rx * k, 0, 2 * math.pi)
        cr.restore()                   # (the source is set after: restore() would undo it)
        cr.set_source_rgba(*rgba(c["primary"], al * glow))
        cr.set_line_width(2)
        cr.stroke()


def _scanlines(cr, x, y, w, h, alpha=0.16):
    cr.set_source_rgba(0, 0, 0, alpha)
    yy = y
    while yy < y + h:
        cr.rectangle(x, yy, w, 1)
        yy += 3
    cr.fill()


def _text(widget, cr, text, x, y, size_pt, colour, weight=Pango.Weight.BOLD, align="left", spacing=0):
    """Text in the widget's own font (the theme's), placed at x, y (its top), aligned."""
    lay = widget.create_pango_layout(text)
    fd = lay.get_context().get_font_description() or Pango.FontDescription()
    fd = fd.copy()
    fd.set_size(int(size_pt * Pango.SCALE))
    fd.set_weight(weight)
    lay.set_font_description(fd)
    if spacing:
        al = Pango.AttrList()
        al.insert(Pango.attr_letter_spacing_new(int(spacing * Pango.SCALE)))
        lay.set_attributes(al)
    tw, th = lay.get_pixel_size()
    dx = {"left": 0, "center": -tw / 2, "right": -tw}[align]
    cr.move_to(x + dx, y)
    cr.set_source_rgba(*colour)
    PangoCairo.show_layout(cr, lay)
    cr.new_path()                       # no current point left behind for the next shape
    return tw, th


def section(text):
    lab = Gtk.Label(label=text.upper(), xalign=0)
    lab.add_css_class("dg-section")
    return lab


# ── the lock (Encryption) ──────────────────────────────────────────────────────────────
class HoloLock(Gtk.DrawingArea):
    """A padlock hologram on its Emitter: shut and lit while encryption is on, with a slow
    Pulse; open and dim when it's off. A Spark when it locks. Still under reduced motion."""

    def __init__(self, c, size=200, still=False):
        super().__init__()
        self.c, self.still, self.size = c, still, size
        self.locked = True
        self.t0 = time.monotonic()
        self.spark_at = None
        self.ticking = False
        self.set_content_width(size)
        self.set_content_height(int(size * 1.15))
        self.set_draw_func(self.draw)
        self.set_locked(True, spark=False)

    def set_locked(self, on, spark=True):
        if on and not self.locked and spark and not self.still:
            self.spark_at = time.monotonic()
        self.locked = on
        try:
            self.update_property([Gtk.AccessibleProperty.LABEL],
                                 ["The disk's lock: " + ("shut, the disk is encrypted" if on else "open, the disk isn't encrypted")])
        except Exception:
            pass
        if on and not self.still and not self.ticking:       # the Pulse runs only while it's locked
            self.ticking = True
            self.add_tick_callback(self._tick)
        self.queue_draw()

    def _tick(self, *_):
        self.queue_draw()
        if not self.locked:
            self.ticking = False
            return False
        return True

    def draw(self, area, cr, w, h):
        c = self.c
        t = time.monotonic() - self.t0
        col = c["primary"] if self.locked else c["dim"]
        glow = 1.0
        if self.locked and not self.still:
            glow = 0.7 + 0.3 * (0.5 + 0.5 * math.sin(t * 1.6))          # the Pulse: a slow breath
        if not self.locked:
            glow = 0.55
        spark = 0.0
        if self.spark_at is not None:
            age = time.monotonic() - self.spark_at
            spark = max(0.0, 1 - age / 0.9)
            if spark == 0:
                self.spark_at = None
        cx = w / 2
        s = min(w, h / 1.15)
        oy = (h - s * 1.15) / 2                       # drawn in its own box, centred, however tall the area
        bw, bh = s * 0.56, s * 0.42                   # the body
        bx, by = cx - bw / 2, oy + s * 1.15 * 0.42
        ey = oy + s * 1.15 * 0.93
        _emitter(cr, c, cx, ey, s * 0.42, glow)
        # light rising from the Emitter
        for i in range(9):
            cr.set_source_rgba(*rgba(c["primary"], 0.05 * glow))
            cr.rectangle(bx + bw * 0.06 + i * bw * 0.11, by + bh, 3, ey - by - bh)
            cr.fill()
        depth = s * 0.05

        def body(dx, dy):
            r = s * 0.05
            x0, y0, x1, y1 = bx + dx, by + dy, bx + bw + dx, by + bh + dy
            cr.new_path()
            cr.arc(x1 - r, y0 + r, r, -math.pi / 2, 0)
            cr.arc(x1 - r, y1 - r, r, 0, math.pi / 2)
            cr.arc(x0 + r, y1 - r, r, math.pi / 2, math.pi)
            cr.arc(x0 + r, y0 + r, r, math.pi, 3 * math.pi / 2)
            cr.close_path()

        def shackle(dx, dy):
            # shut: both legs in the body; open: lifted, the right leg out of it
            sw = bw * 0.62
            lift = 0 if self.locked else s * 0.12
            top = by - s * 0.3 - lift
            x0, x1 = cx - sw / 2 + dx, cx + sw / 2 + dx
            cr.new_path()
            cr.move_to(x0, by + dy)
            cr.line_to(x0, top + sw / 2 + dy)
            cr.arc(cx + dx, top + sw / 2 + dy, sw / 2, math.pi, 2 * math.pi)
            cr.line_to(x1, by + dy - lift)
        # the back face and the ribs: a slab, not a sticker
        cr.set_line_width(1)
        cr.set_source_rgba(*rgba(col, 0.28 * glow))
        body(depth, -depth)
        cr.stroke()
        shackle(depth, -depth)
        cr.stroke()
        for px, py in ((bx, by), (bx + bw, by), (bx + bw, by + bh), (bx, by + bh)):
            cr.move_to(px, py)
            cr.line_to(px + depth, py - depth)
        cr.stroke()
        # the front, with its glow
        for lw, al in ((s * 0.09, 0.08), (s * 0.05, 0.16), (s * 0.028, 1.0)):
            cr.set_line_width(lw)
            cr.set_source_rgba(*rgba(col, min(1.0, al * glow + spark * (0.5 if al < 1 else 0))))
            shackle(0, 0)
            cr.stroke()
        cr.set_source_rgba(*rgba(c["panel"], 0.92))
        body(0, 0)
        cr.fill_preserve()
        for lw, al in ((s * 0.06, 0.12), (2.2, 1.0)):
            cr.set_line_width(lw)
            cr.set_source_rgba(*rgba(col, min(1.0, al * glow + spark * 0.4)))
            body(0, 0)
            cr.stroke()
        # the keyhole
        kx, ky = cx, by + bh * 0.42
        cr.set_source_rgba(*rgba(col, min(1.0, glow + spark)))
        cr.arc(kx, ky, s * 0.045, 0, 2 * math.pi)
        cr.fill()
        cr.move_to(kx - s * 0.022, ky)
        cr.line_to(kx + s * 0.022, ky)
        cr.line_to(kx + s * 0.034, ky + bh * 0.32)
        cr.line_to(kx - s * 0.034, ky + bh * 0.32)
        cr.close_path()
        cr.fill()
        if spark > 0:                                   # the Spark: a white flash on the lock
            cr.set_source_rgba(1, 1, 1, 0.35 * spark)
            body(0, 0)
            cr.fill()
        _scanlines(cr, bx - s * 0.1, by - s * 0.5, bw + s * 0.2, bh + s * 0.55, 0.14)


# ── the burn-in (Done) ─────────────────────────────────────────────────────────────────
class BurnIn(Gtk.DrawingArea):
    """The emblem burned in: a Spark when it appears (a one-time glow, about a second),
    then still. Under reduced motion it's simply there, still."""

    def __init__(self, c, size=200, still=False, tint=None):
        super().__init__()
        self.c, self.still, self.tint = c, still, tint
        self.set_content_width(size)
        self.set_content_height(size)
        self.emb = None
        for d in EMBLEMS:
            p = os.path.normpath(os.path.join(d, "emblem-512.png"))
            if os.path.exists(p):
                self.emb = GdkPixbuf.Pixbuf.new_from_file(p)
                break
        self.born = None
        self.set_draw_func(self.draw)
        self.connect("map", lambda *_: self.spark())
        self.update_property([Gtk.AccessibleProperty.LABEL], ["bromigOS's emblem, burned in"])

    def spark(self):
        if self.still:
            return
        self.born = time.monotonic()
        self.add_tick_callback(self._tick)

    def _tick(self, *_):
        self.queue_draw()
        return self.born is not None and time.monotonic() - self.born < 1.2

    def draw(self, area, cr, w, h):
        c = self.c
        cx, cy, r = w / 2, h / 2, min(w, h) / 2 - 4
        k = 0.0 if self.born is None else max(0.0, 1 - (time.monotonic() - self.born) / 1.0)
        grow = 1.0 - 0.06 * k * k
        # the halo: steady and faint, flaring with the Spark
        import cairo
        g = cairo.RadialGradient(cx, cy, r * 0.55, cx, cy, r * 1.0)
        pr, pg, pb, _ = rgba(c["primary"])
        g.add_color_stop_rgba(0, pr, pg, pb, 0.22 + 0.5 * k)
        g.add_color_stop_rgba(1, pr, pg, pb, 0)
        cr.set_source(g)
        cr.arc(cx, cy, r, 0, 2 * math.pi)
        cr.fill()
        if self.emb:
            s = (r * 0.86) * 2 / self.emb.get_width() * grow
            cr.save()
            cr.translate(cx, cy)
            cr.scale(s, s)
            Gdk.cairo_set_source_pixbuf(cr, self.emb, -self.emb.get_width() / 2, -self.emb.get_height() / 2)
            cr.paint_with_alpha(0.92 if not k else min(1.0, 0.6 + 0.4 * (1 - k) + 0.4 * k))
            cr.restore()
        if k > 0:                                       # the Spark's white bloom
            g2 = cairo.RadialGradient(cx, cy, 0, cx, cy, r * 0.9)
            g2.add_color_stop_rgba(0, 1, 1, 1, 0.5 * k)
            g2.add_color_stop_rgba(1, 1, 1, 1, 0)
            cr.set_source(g2)
            cr.arc(cx, cy, r, 0, 2 * math.pi)
            cr.fill()
        cr.save()
        cr.arc(cx, cy, r, 0, 2 * math.pi)
        cr.clip()
        _scanlines(cr, 0, 0, w, h, 0.16)
        cr.restore()


class SignalLost(Gtk.DrawingArea):
    """The failure's mark: the emblem's ring broken, in the danger colour, still."""

    def __init__(self, c, size=150):
        super().__init__()
        self.c = c
        self.set_content_width(size)
        self.set_content_height(size)
        self.set_draw_func(self.draw)
        self.update_property([Gtk.AccessibleProperty.LABEL], ["The install stopped"])

    def draw(self, area, cr, w, h):
        c = self.c
        cx, cy, r = w / 2, h / 2, min(w, h) / 2 - 8
        d = rgba(c["danger"])
        for rr, lw in ((r, 5), (r * 0.8, 3)):
            for a0, a1 in ((-1.35, 0.55), (0.85, 2.5), (2.85, 4.6)):     # the ring, broken in three
                for wdt, al in ((lw * 3, 0.12), (lw, 0.95)):
                    cr.set_line_width(wdt)
                    cr.set_source_rgba(d[0], d[1], d[2], al)
                    cr.arc(cx, cy, rr, a0, a1)
                    cr.stroke()
        # the sign: a warning triangle where the flame stands
        t = r * 0.5
        cr.set_line_width(3)
        cr.set_source_rgba(*d)
        cr.move_to(cx, cy - t)
        cr.line_to(cx + t * 0.9, cy + t * 0.62)
        cr.line_to(cx - t * 0.9, cy + t * 0.62)
        cr.close_path()
        cr.stroke()
        cr.rectangle(cx - 2, cy - t * 0.42, 4, t * 0.6)
        cr.fill()
        cr.arc(cx, cy + t * 0.38, 2.6, 0, 2 * math.pi)
        cr.fill()
        _scanlines(cr, 0, 0, w, h, 0.18)


# ── the answer file's countdown (Automatic) ────────────────────────────────────────────
class Countdown(Gtk.DrawingArea):
    """The seconds left as a ring that empties, the number in the middle: it changes once a
    second, with the countdown (no motion of its own)."""

    def __init__(self, c, total, size=170):
        super().__init__()
        self.c, self.total, self.left = c, max(1, total), total
        self.set_content_width(size)
        self.set_content_height(size)
        self.set_draw_func(self.draw)
        self.set_left(total)

    def set_left(self, n):
        self.left = max(0, n)
        try:
            self.update_property([Gtk.AccessibleProperty.LABEL], [f"Installing in {self.left} seconds"])
        except Exception:
            pass
        self.queue_draw()

    def draw(self, area, cr, w, h):
        c = self.c
        cx, cy, r = w / 2, h / 2, min(w, h) / 2 - 12
        cr.set_line_width(8)
        cr.set_source_rgba(*rgba(c["dim"], 0.35))
        cr.arc(cx, cy, r, 0, 2 * math.pi)
        cr.stroke()
        end = -math.pi / 2 + 2 * math.pi * self.left / self.total
        for wdt, al in ((18, 0.1), (12, 0.2), (8, 1.0)):
            cr.set_line_width(wdt)
            cr.set_source_rgba(*rgba(c["primary"], al))
            cr.arc(cx, cy, r, -math.pi / 2, end)
            cr.stroke()
        for i in range(self.total):                    # a tick per second
            a = -math.pi / 2 + 2 * math.pi * i / self.total
            lit = i < self.left
            cr.set_source_rgba(*rgba(c["primary"] if lit else c["faint"], 0.9 if lit else 0.5))
            cr.set_line_width(2)
            cr.move_to(cx + (r - 14) * math.cos(a), cy + (r - 14) * math.sin(a))
            cr.line_to(cx + (r - 22) * math.cos(a), cy + (r - 22) * math.sin(a))
            cr.stroke()
        big = r * 0.42
        _text(self, cr, str(self.left), cx, cy - big * 1.05, big, rgba(c["primary"]), align="center")
        _text(self, cr, "SECONDS", cx, cy + big * 0.45, max(7, r * 0.09), rgba(c["muted"]), align="center", spacing=2)


# ── About you: the dossier's portrait, the checks beside each field, the meter ─────────
class Portrait(Gtk.DrawingArea):
    """The ID card's portrait slot, as the dossiers have it: a framed square with corner
    brackets and a Scanline, the name's first letter in it (a silhouette before there's a
    name). It changes only as you type."""

    def __init__(self, c, size=112):
        super().__init__()
        self.c, self.name = c, ""
        self.set_content_width(size)
        self.set_content_height(size)
        self.set_draw_func(self.draw)
        self.update_property([Gtk.AccessibleProperty.LABEL], ["Your ID card's portrait: your name's first letter"])

    def set_name(self, name):
        self.name = (name or "").strip()
        self.queue_draw()

    def draw(self, area, cr, w, h):
        c = self.c
        s = min(w, h)
        x0, y0 = (w - s) / 2, (h - s) / 2
        cr.set_source_rgba(*rgba(c["void"], 0.9))
        cr.rectangle(x0 + 3, y0 + 3, s - 6, s - 6)
        cr.fill()
        cr.set_source_rgba(*rgba(c["dim"], 0.7))
        cr.set_line_width(1)
        cr.rectangle(x0 + 3.5, y0 + 3.5, s - 7, s - 7)
        cr.stroke()
        k = s * 0.18                                   # the corner brackets
        cr.set_source_rgba(*rgba(c["primary"]))
        cr.set_line_width(2)
        for (px, py, dx, dy) in ((x0 + 1, y0 + 1, 1, 1), (x0 + s - 1, y0 + 1, -1, 1), (x0 + 1, y0 + s - 1, 1, -1),
                                 (x0 + s - 1, y0 + s - 1, -1, -1)):
            cr.move_to(px, py + dy * k)
            cr.line_to(px, py)
            cr.line_to(px + dx * k, py)
        cr.stroke()
        cx, cy = x0 + s / 2, y0 + s / 2
        letter = self.name[:1].upper()
        if letter:
            big = s * 0.36
            _text(self, cr, letter, cx, cy - big * 0.95, big, rgba(c["primary"]), align="center")
        else:                                          # a silhouette: head and shoulders
            cr.set_source_rgba(*rgba(c["dim"], 0.9))
            cr.arc(cx, cy - s * 0.1, s * 0.15, 0, 2 * math.pi)
            cr.fill()
            cr.save()
            cr.translate(cx, cy + s * 0.32)
            cr.scale(1, 0.62)
            cr.arc(0, 0, s * 0.3, math.pi, 2 * math.pi)
            cr.restore()
            cr.fill()
        _scanlines(cr, x0 + 4, y0 + 4, s - 8, s - 8, 0.22)


def valid_mark():
    """The ✓ / ▲ beside a field: empty until there's something to say."""
    m = Gtk.Label(label="", valign=Gtk.Align.CENTER)
    m.add_css_class("dg-valid")
    return m


def set_valid(mark, problem, shown=True):
    """problem None: ✓; a sentence: ▲ with it as the hover hint; shown False: nothing yet."""
    for cl in ("ok", "bad"):
        mark.remove_css_class(cl)
    if not shown:
        mark.set_label("")
        mark.set_tooltip_text(None)
        return
    mark.set_label("✓" if not problem else "▲")
    mark.add_css_class("ok" if not problem else "bad")
    words = problem or "This one is fine."
    mark.set_tooltip_text(words)
    try:
        mark.update_property([Gtk.AccessibleProperty.LABEL], [words])
    except Exception:
        pass


def strength_meter():
    """A password's strength as a discrete level bar (GTK's own, so a screen reader reads
    it), its filled blocks in the level's colour, with the word and the advice beside it.
    Returns (box, set(word, advice))."""
    box = Gtk.Box(spacing=12)
    bar = Gtk.LevelBar(min_value=0, max_value=6, mode=Gtk.LevelBarMode.DISCRETE, valign=Gtk.Align.CENTER)
    bar.add_css_class("dg-meter")
    for n in ("low", "high", "full"):
        try:
            bar.remove_offset_value(n)
        except Exception:
            pass
    for n, v in (("weak", 2), ("fair", 4), ("strong", 6)):
        bar.add_offset_value(n, v)
    bar.set_size_request(150, -1)
    word = Gtk.Label(label="", xalign=0, width_chars=7)
    word.add_css_class("dg-meter-word")
    advice = Gtk.Label(label="", xalign=0, wrap=True, hexpand=True)
    advice.set_wrap_mode(2)
    advice.add_css_class("dg-muted")
    box.append(bar)
    box.append(word)
    box.append(advice)
    box.update_property([Gtk.AccessibleProperty.LABEL], ["Strength"])

    def setter(w, tip):
        for cl in ("weak", "fair", "strong"):
            word.remove_css_class(cl)
        bar.set_value({"weak": 2, "fair": 4, "strong": 6}.get(w, 0))
        word.set_label(w.upper() if w else "")
        if w:
            word.add_css_class(w)
        advice.set_label(tip or "")
        bar.update_property([Gtk.AccessibleProperty.VALUE_TEXT], [f"{w or 'empty'}. {tip or ''}"])
    setter("", "")
    return box, setter


# ── the briefing (Ready to install, and the tour's Done) ──────────────────────────────
def briefing(title, rows, on_edit=None, hint_fn=None):
    """A card with a head strip and one row per choice: its icon, its name small above its
    value, and an Edit link (when on_edit says where to go). rows: [(icon, key, value,
    target or None, danger)]."""
    card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
    card.add_css_class("dg-brief")
    head = Gtk.Box(spacing=8)
    head.add_css_class("dg-brief-head")
    head.append(Gtk.Label(label=title.upper(), xalign=0, hexpand=True))
    card.append(head)
    for ic, key, value, target, danger in rows:
        row = Gtk.Box(spacing=14)
        row.add_css_class("dg-brief-row")
        if danger:
            row.add_css_class("danger")
        im = icon(ic, 20, "dg-brief-icon")
        im.set_valign(Gtk.Align.CENTER)
        row.append(im)
        col = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2, hexpand=True)
        k = Gtk.Label(label=key.upper(), xalign=0)
        k.add_css_class("dg-brief-key")
        v = Gtk.Label(label=value, xalign=0, wrap=True)
        v.set_wrap_mode(2)
        v.add_css_class("dg-brief-val")
        v.set_selectable(False)
        col.append(k)
        col.append(v)
        row.append(col)
        row.set_tooltip_text(f"{key}: {value}")
        row.update_property([Gtk.AccessibleProperty.LABEL], [f"{key}: {value}"])
        if target and on_edit:
            b = Gtk.Button(label="Edit", valign=Gtk.Align.CENTER)
            b.add_css_class("dg-edit")
            tip = hint_fn(key, target) if hint_fn else f"Change {key.lower()}"
            b.set_tooltip_text(tip)
            b.update_property([Gtk.AccessibleProperty.LABEL, Gtk.AccessibleProperty.DESCRIPTION], [f"Edit {key}", tip])
            b.connect("clicked", lambda *_, t=target: on_edit(t))
            row.append(b)
        card.append(row)
    return card


def numbered(lines):
    """Next steps, numbered in lit circles."""
    box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
    for i, (ic, text) in enumerate(lines, 1):
        row = Gtk.Box(spacing=12)
        n = Gtk.Label(label=str(i), valign=Gtk.Align.START)
        n.add_css_class("dg-num")
        row.append(n)
        if ic:
            im = icon(ic, 18, "dg-row-icon")
            im.set_valign(Gtk.Align.START)
            im.set_margin_top(3)
            row.append(im)
        t = Gtk.Label(label=text, xalign=0, wrap=True, hexpand=True)
        t.set_wrap_mode(2)
        t.add_css_class("dg-stepline")
        t.set_margin_top(2)
        row.append(t)
        box.append(row)
    return box


def keycaps(keys):
    """'Super + Space' as keycaps: each key boxed, a + between."""
    box = Gtk.Box(spacing=6)
    for i, k in enumerate(keys.split(" + ")):
        if i:
            p = Gtk.Label(label="+")
            p.add_css_class("dg-keyplus")
            box.append(p)
        cap = Gtk.Label(label=k.upper())
        cap.add_css_class("dg-keycap")
        box.append(cap)
    box.update_property([Gtk.AccessibleProperty.LABEL], [keys])
    return box


# ── the keyboard (Your keyboard) ───────────────────────────────────────────────────────
# the main block by evdev key code: (code, width in keys); the legends come from the layout
KB_ROWS = [
    [(41, 1), (2, 1), (3, 1), (4, 1), (5, 1), (6, 1), (7, 1), (8, 1), (9, 1), (10, 1), (11, 1), (12, 1), (13, 1), (14, 2)],
    [(15, 1.5), (16, 1), (17, 1), (18, 1), (19, 1), (20, 1), (21, 1), (22, 1), (23, 1), (24, 1), (25, 1), (26, 1), (27, 1), (43, 1.5)],
    [(58, 1.75), (30, 1), (31, 1), (32, 1), (33, 1), (34, 1), (35, 1), (36, 1), (37, 1), (38, 1), (39, 1), (40, 1), (28, 2.25)],
    [(42, 2.25), (44, 1), (45, 1), (46, 1), (47, 1), (48, 1), (49, 1), (50, 1), (51, 1), (52, 1), (53, 1), (54, 2.75)],
    [(29, 1.25), (125, 1.25), (56, 1.25), (57, 6.25), (100, 1.25), (126, 1.25), (127, 1.25), (97, 1.25)],
]
KB_NAMES = {14: "Back", 15: "Tab", 58: "Caps", 28: "Enter", 42: "Shift", 54: "Shift", 29: "Ctrl", 125: "Super",
            56: "Alt", 57: "", 100: "AltGr", 126: "Super", 127: "Menu", 97: "Ctrl"}


class KeyboardHolo(Gtk.DrawingArea):
    """The keyboard as a hologram: each key shows what it types in the chosen layout (read
    from the session's own keymap), and the key you press lights (a Spark that fades in
    under a second; under reduced motion it stays lit until the next key)."""

    def __init__(self, c, still=False, height=190):
        super().__init__()
        self.c, self.still = c, still
        self.lit = {}                 # evdev code: when
        self.typed = {}               # evdev code: what it typed (beats the keymap's guess)
        self.legends = {}
        self.set_content_height(height)
        self.set_hexpand(True)
        self.set_draw_func(self.draw)
        self.ticking = False
        self.update_property([Gtk.AccessibleProperty.LABEL],
                             ["A picture of the keyboard: the key you press lights up, showing what it types"])
        self.read_layout()

    def read_layout(self):
        """Each key's legend from the keymap the session uses now (the layout just chosen)."""
        self.legends = {}
        try:
            disp = Gdk.Display.get_default()
            for row in KB_ROWS:
                for code, _ in row:
                    if code in KB_NAMES:
                        continue
                    ok, keys, vals = disp.map_keycode(code + 8)
                    if not ok:
                        continue
                    for k, v in zip(keys, vals):
                        if k.group == 0 and k.level == 0:
                            ch = chr(Gdk.keyval_to_unicode(v)) if Gdk.keyval_to_unicode(v) else ""
                            self.legends[code] = ch.upper() if ch.isalpha() else ch
                            break
        except Exception:
            pass
        self.typed = {}
        self.queue_draw()

    def press(self, hw_keycode, keyval):
        code = hw_keycode - 8
        ch = Gdk.keyval_to_unicode(keyval)
        if ch and chr(ch).isprintable() and not chr(ch).isspace() and code not in KB_NAMES:
            self.typed[code] = chr(ch).upper() if chr(ch).isalpha() else chr(ch)
        self.lit = {code: time.monotonic()} if self.still else {**self.lit, code: time.monotonic()}
        if not self.still and not self.ticking:
            self.ticking = True
            self.add_tick_callback(self._tick)
        self.queue_draw()

    def _tick(self, *_):
        now = time.monotonic()
        self.lit = {k: t for k, t in self.lit.items() if now - t < 0.9}
        self.queue_draw()
        if not self.lit:
            self.ticking = False
            return False
        return True

    def draw(self, area, cr, w, h):
        c = self.c
        units = 15.0
        gap = 4
        u = min((w - 8) / units, (h - 8) / 5.0 / 0.92)
        kh = u * 0.92 - gap
        total_w = u * units
        x0, y0 = (w - total_w) / 2, (h - u * 0.92 * 5) / 2
        now = time.monotonic()
        # the deck's outline, a little behind
        cr.set_source_rgba(*rgba(c["dim"], 0.35))
        cr.set_line_width(1)
        cr.rectangle(x0 - 5.5, y0 - 5.5, total_w + 11 - gap, u * 0.92 * 5 + 11 - gap)
        cr.stroke()
        for ri, row in enumerate(KB_ROWS):
            x = x0
            y = y0 + ri * u * 0.92
            for code, width in row:
                kw = width * u - gap
                glow = 0.0
                if code in self.lit:
                    glow = 1.0 if self.still else max(0.0, 1 - (now - self.lit[code]) / 0.9)
                cr.set_source_rgba(*rgba(c["primary"], 0.06 + 0.5 * glow))
                cr.rectangle(x, y, kw, kh)
                cr.fill()
                if glow:
                    cr.set_source_rgba(*rgba(c["primary"], 0.25 * glow))
                    cr.set_line_width(6)
                    cr.rectangle(x - 1, y - 1, kw + 2, kh + 2)
                    cr.stroke()
                cr.set_source_rgba(*rgba(c["primary"] if glow else c["dim"], 0.95 if glow else 0.75))
                cr.set_line_width(1)
                cr.rectangle(x + 0.5, y + 0.5, kw - 1, kh - 1)
                cr.stroke()
                leg = KB_NAMES.get(code, self.typed.get(code, self.legends.get(code, "")))
                if leg:
                    col = c["void"] if glow > 0.5 else (c["soft"] if code not in KB_NAMES else c["muted"])
                    size = max(6.0, kh * (0.34 if code not in KB_NAMES else 0.24))
                    _text(self, cr, leg, x + kw / 2, y + kh / 2 - size * 0.8, size, rgba(col),
                          weight=Pango.Weight.BOLD, align="center")
                x += width * u
        _scanlines(cr, x0 - 6, y0 - 6, total_w + 12, u * 0.92 * 5 + 12, 0.12)


# ── a card with a hologram drawn in it (the tour's choices) ────────────────────────────
class Glyph(Gtk.DrawingArea):
    """A bromigos_driftglass hologram (a device, the rack, a cloud…) on its Emitter: lit
    and turning slowly while its card is chosen, dim and still otherwise (still under
    reduced motion)."""

    def __init__(self, kind, c, size=96, still=False):
        super().__init__()
        self.kind, self.c, self.still, self.live = kind, c, still, False
        self.t0 = time.monotonic()
        self.ticking = False
        self.set_content_width(size)
        self.set_content_height(size)
        self.set_draw_func(self.draw)

    def set_live(self, on):
        self.live = on
        if on and not self.still and not self.ticking:
            self.ticking = True
            self.add_tick_callback(self._tick)
        self.queue_draw()

    def _tick(self, *_):
        self.queue_draw()
        if not self.live:
            self.ticking = False
            return False
        return True

    def draw(self, area, cr, w, h):
        if DG is None:
            return
        s = min(w, h)
        DG.glyph(cr, self.kind, (w - s) / 2, (h - s) / 2, s, self.c, time.monotonic() - self.t0, live=self.live,
                 still=self.still)


def glyph_card(kind, c, icon_name, title, lines, active, group=None, still=False, size=96):
    """holo_card with a drawn hologram in place of a picture: it turns while chosen."""
    g = Glyph(kind, c, size, still)
    b = holo_card(None, icon_name, title, lines, active, group)
    v = b.get_child()
    holder = Gtk.Box(halign=Gtk.Align.CENTER, margin_top=10)
    holder.append(g)
    v.prepend(holder)
    g.set_live(active)
    b.connect("toggled", lambda w: g.set_live(w.get_active()))
    b.glyph = g
    return b


# ── the tour's screens map ─────────────────────────────────────────────────────────────
class ScreensMap(Gtk.DrawingArea):
    """The screens side by side at their sizes: the main one lit, with the panels drawn on
    it; click one to make it the main screen (the rows below do the same by keyboard)."""

    def __init__(self, c, mons, height=170):
        super().__init__()
        self.c, self.mons = c, mons
        self.primary = next((m["name"] for m in mons if m.get("focused")), mons[0]["name"] if mons else None)
        self.on_pick = None
        self.boxes = []
        self.set_content_height(height)
        self.set_hexpand(True)
        self.set_draw_func(self.draw)
        click = Gtk.GestureClick()
        click.connect("pressed", self._click)
        self.add_controller(click)
        self.update_property([Gtk.AccessibleProperty.LABEL], ["Your screens, side by side: the lit one is the main screen"])

    def pick(self, name):
        self.primary = name
        self.queue_draw()

    def _click(self, g, n, x, y):
        for name, (bx, by, bw, bh) in self.boxes:
            if bx <= x <= bx + bw and by <= y <= by + bh:
                self.pick(name)
                if self.on_pick:
                    self.on_pick(name)

    def draw(self, area, cr, w, h):
        c = self.c
        if not self.mons:
            return
        dims = []
        for m in self.mons:
            try:
                mw, mh = (int(v) for v in m["size"].replace("x", "×").split("×"))
            except (ValueError, KeyError):
                mw, mh = 1920, 1080
            dims.append((mw / max(1.0, m.get("scale", 1.0)), mh / max(1.0, m.get("scale", 1.0))))
        # each screen drawn at its own aspect; its height follows its pixels, gently
        tallest = max(d[1] for d in dims)
        gap = 28
        hs = [(h - 44) * (0.62 + 0.38 * d[1] / tallest) for d in dims]
        ws = [hh * d[0] / d[1] for hh, d in zip(hs, dims)]
        k = min(1.0, (w - gap * (len(ws) - 1) - 8) / max(1, sum(ws)))
        ws, hs = [x * k for x in ws], [x * k for x in hs]
        x = (w - sum(ws) - gap * (len(ws) - 1)) / 2
        base = h - 30
        self.boxes = []
        for m, mw, mh in zip(self.mons, ws, hs):
            y = base - mh
            main = m["name"] == self.primary
            col = c["primary"] if main else c["dim"]
            cr.set_source_rgba(*rgba(c["panel"], 0.95))
            cr.rectangle(x, y, mw, mh)
            cr.fill()
            if main:
                for lw, al in ((10, 0.08), (5, 0.18)):
                    cr.set_source_rgba(*rgba(col, al))
                    cr.set_line_width(lw)
                    cr.rectangle(x, y, mw, mh)
                    cr.stroke()
                # the panels: the bar on top, a few widget plates on the left
                cr.set_source_rgba(*rgba(col, 0.55))
                cr.rectangle(x + 4, y + 4, mw - 8, max(3, mh * 0.05))
                cr.fill()
                for i in range(3):
                    cr.set_source_rgba(*rgba(col, 0.22))
                    cr.rectangle(x + 6, y + 6 + mh * 0.08 + i * mh * 0.22, mw * 0.22, mh * 0.18)
                    cr.fill()
            cr.set_source_rgba(*rgba(col, 1.0 if main else 0.8))
            cr.set_line_width(2 if main else 1)
            cr.rectangle(x + 0.5, y + 0.5, mw - 1, mh - 1)
            cr.stroke()
            cr.move_to(x + mw / 2, base)                 # the stand
            cr.line_to(x + mw / 2, base + 8)
            cr.move_to(x + mw / 2 - mw * 0.12, base + 9)
            cr.line_to(x + mw / 2 + mw * 0.12, base + 9)
            cr.stroke()
            _text(self, cr, m["name"], x + mw / 2, y + mh / 2 - 9, 9.5, rgba(c["soft"] if main else c["muted"]),
                  align="center")
            if main:
                _text(self, cr, "MAIN", x + mw / 2, y + mh / 2 + 7, 7.5, rgba(c["primary"]), align="center", spacing=2)
            _scanlines(cr, x, y, mw, mh, 0.14)
            self.boxes.append((m["name"], (x, y, mw, mh)))
            x += mw + gap


# ── the tour's lab radar ───────────────────────────────────────────────────────────────
class LabRadar(Gtk.DrawingArea):
    """The Sweep, while it looks for your lab: each machine found is a blip with its name;
    click one (or pick it in the list beside) to see it. The beam turns only while it's
    looking, and not at all under reduced motion."""

    def __init__(self, c, size=260, still=False):
        super().__init__()
        self.c, self.still, self.size = c, still, size
        self.hosts, self.chosen, self.searching = [], None, False
        self.on_pick = None
        self.t0 = time.monotonic()
        self.found_at = {}
        self.ticking = False
        self.set_content_width(size)
        self.set_content_height(size)
        self.set_draw_func(self.draw)
        click = Gtk.GestureClick()
        click.connect("pressed", self._click)
        self.add_controller(click)
        self.update_property([Gtk.AccessibleProperty.LABEL], ["The lab radar: each dot is a machine found"])

    def _key(self, i, h):
        return (h.get("name") or "?") + str(i)

    def _rssi(self, i):
        return -66 - 10 * (i % 3) - 2 * (i // 3)    # spread out, clear of this computer in the middle

    def set_searching(self, on):
        self.searching = on
        if on and not self.still and not self.ticking:
            self.ticking = True
            self.add_tick_callback(self._tick)
        self.queue_draw()

    def set_hosts(self, hosts):
        now = time.monotonic()
        self.hosts = list(hosts)
        for i, h in enumerate(self.hosts):
            self.found_at.setdefault(self._key(i, h), now)
        if self.hosts and self.chosen is None:
            self.chosen = 0
        self.queue_draw()

    def pick(self, i):
        self.chosen = i
        self.queue_draw()

    def _tick(self, *_):
        self.queue_draw()
        if not self.searching and all(time.monotonic() - t > 1 for t in self.found_at.values()):
            self.ticking = False
            return False
        return True

    def _pos(self, i, h, w, hh):
        s = min(w, hh)
        cx, cy, R = (w - s) / 2 + s / 2, (hh - s) / 2 + s / 2, s / 2 - 1.5
        a, r = DG._where(self._key(i, h), self._rssi(i))
        return cx + R * r * math.cos(a), cy + R * r * math.sin(a)

    def _click(self, g, n, x, y):
        for i, h in enumerate(self.hosts):
            px, py = self._pos(i, h, self.get_width(), self.get_height())
            if (px - x) ** 2 + (py - y) ** 2 < 18 ** 2:
                self.pick(i)
                if self.on_pick:
                    self.on_pick(i)

    def draw(self, area, cr, w, h):
        if DG is None:
            return
        c = self.c
        s = min(w, h)
        x0, y0 = (w - s) / 2, (h - s) / 2
        now = time.monotonic()
        blips = [(self._key(i, hst), self._rssi(i), (now - self.found_at.get(self._key(i, hst), 0)) if not self.still else None)
                 for i, hst in enumerate(self.hosts)]
        sweeping = self.searching and not self.still
        DG.radar(cr, x0, y0, s, c, now - self.t0, blips, still=not sweeping)
        cx, cy = x0 + s / 2, y0 + s / 2
        cr.set_source_rgba(*rgba(c["primary"]))             # this computer, in the middle
        cr.rectangle(cx - 3, cy - 3, 6, 6)
        cr.fill()
        _text(self, cr, "YOU", cx, cy + 6, 7, rgba(c["muted"]), align="center", spacing=1)
        for i, hst in enumerate(self.hosts):
            px, py = self._pos(i, hst, w, h)
            on = i == self.chosen
            if on:
                cr.set_source_rgba(*rgba(c["primary"]))
                cr.set_line_width(1.5)
                cr.arc(px, py, 9, 0, 2 * math.pi)
                cr.stroke()
                for a in range(4):                          # target brackets
                    ang = a * math.pi / 2 + math.pi / 4
                    cr.move_to(px + 12 * math.cos(ang), py + 12 * math.sin(ang))
                    cr.line_to(px + 16 * math.cos(ang), py + 16 * math.sin(ang))
                cr.stroke()
            name = (hst.get("name") or "?").upper()
            right = px < cx + s * 0.18
            _text(self, cr, name, px + (13 if right else -13), py - 7, 8.5, rgba(c["primary"] if on else c["soft"]),
                  align="left" if right else "right", spacing=1)


class SignalBars(Gtk.DrawingArea):
    """A Wi-Fi network's strength, four rising bars (bromigos_driftglass.bars)."""

    def __init__(self, c, signal_pct):
        super().__init__()
        self.c, self.pct = c, signal_pct
        self.set_content_width(22)
        self.set_content_height(18)
        self.set_valign(Gtk.Align.CENTER)
        self.set_draw_func(self.draw)
        self.update_property([Gtk.AccessibleProperty.LABEL], [f"Signal {signal_pct} %"])

    def draw(self, area, cr, w, h):
        if DG is None:
            return
        rssi = -100 + self.pct * 0.6        # nmcli's percent, roughly back to dBm
        DG.bars(cr, 2, 1, h - 2, rssi, self.c)


class MiniSweep(Gtk.DrawingArea):
    """A small Sweep beside 'Looking for networks…': it turns while looking (state), and
    not under reduced motion."""

    def __init__(self, c, size=44, still=False):
        super().__init__()
        self.c, self.still, self.on = c, still, True
        self.t0 = time.monotonic()
        self.set_content_width(size)
        self.set_content_height(size)
        self.set_draw_func(self.draw)
        if not still:
            self.add_tick_callback(self._tick)

    def _tick(self, *_):
        self.queue_draw()
        return self.on

    def stop(self):
        self.on = False
        self.queue_draw()

    def draw(self, area, cr, w, h):
        if DG is None:
            return
        DG.radar(cr, 0, 0, min(w, h), self.c, time.monotonic() - self.t0, (), still=self.still or not self.on)
