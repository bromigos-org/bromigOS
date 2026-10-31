"""The graphical installer (docs/iso.md, "Installing from it"): full screen on the live
desktop, opened by the boot menu's "Install bromigOS" and the live desktop's welcome card.
GTK 4 and libadwaita in the Settings window's style (its CSS, the theme's colours), in
DRIFTGLASS: GLOW panels, one FLARE (the emblem on the first step, turning slowly unless
motion is reduced), and a hover hint on every control. The steps, words and checks are
common.py's, the same as the text installer's; the work is backend.py's.

  python3 -m bromigos_installer.gui [--windowed] [--fake] [--script PLAN.json]
                                    [--render DIR [--size WxH]]

--script: the test harness's driver: each step filled in from PLAN (tuidrive.py's form),
"::page NAME" printed when it's on screen, then on to the next once /tmp/bromigos-installer-next
appears (the harness took its screenshot) or after 20 s; "::result" at the end.
--render DIR: each step drawn to DIR/gui-STEP.png with the fake back end, then exit (needs
a Wayland display: a headless weston does; tools/settings/render.sh shows how).
"""
import json
import math
import os
import sys
import time

if __package__ in (None, ""):
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.realpath(__file__))))
    __package__ = "bromigos_installer"

import gi  # noqa: E402

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gdk, GLib, Gtk  # noqa: E402

from . import backend, common  # noqa: E402

sys.path.append("/usr/lib/bromigos/lib")
import bromigos_glass as glass  # noqa: E402
try:                          # VECTOR's lines and his voice (docs/voice-guide.md), bromigos-core's
    import bromigos_guide as guide  # noqa: E402
except ImportError:           # an older bromigos-core: no captions, no voice
    guide = None
from .disks import GiB, plain_size  # noqa: E402


def _read(path):
    with open(path) as f:
        return f.read()

SETTINGS = "/usr/lib/bromigos/settings"
ART = "/usr/share/plymouth/themes/bromigos"
NEXT_FLAG = "/tmp/bromigos-installer-next"


def settings_css(c):
    """The Settings window's own stylesheet (its colours from the theme), else a small one."""
    sys.path.insert(0, SETTINGS)
    try:
        from bromigos_settings import style
        return style.css(c)
    except Exception:
        return f"""* {{ font-family: "Geist Mono", monospace; }}
window, window.background {{ background-color: {c['background']}; color: {c['text']}; }}
button, entry, row, list {{ border-radius: 0; }}
button.suggested-action {{ background-color: {c['primary']}; color: {c['void']}; }}
"""


def installer_css(c, high_contrast=False):
    def a(h, al):
        h = h.lstrip("#")
        return f"rgba({int(h[0:2], 16)},{int(h[2:4], 16)},{int(h[4:6], 16)},{al})"
    hc = high_contrast
    return f"""
.bi-rail {{ background-color: {c['panel']}; border-right: 1px solid {a(c['dim'], .55)}; padding: 18px 0; min-width: 210px; }}
.bi-rail-title {{ color: {c['dim']}; font-size: 0.78em; font-weight: 700; letter-spacing: 0.2em; margin: 6px 22px 14px 22px; }}
.bi-step {{ padding: 7px 22px; color: {c['faint'] if not hc else c['text']}; letter-spacing: 0.08em; }}
.bi-step.done {{ color: {c['soft']}; }}
.bi-step.now {{ color: {c['primary']}; font-weight: 700; background-color: {a(c['primary'], .13)};
  box-shadow: inset 3px 0 {c['primary']}; }}
.bi-heading {{ font-size: 1.9em; font-weight: 700; letter-spacing: 0.14em; color: {c['primary']};
  text-shadow: 0 0 8px {a(c['primary'], .25 if not hc else 0)}; }}
.bi-intro {{ color: {c['muted'] if not hc else c['text']}; font-size: 1.05em; }}
.bi-bar {{ border-top: 1px solid {a(c['dim'], .45)}; padding: 12px 24px; background-color: {a(c['panel'], .7)}; }}
.bi-error {{ color: {c['danger']}; font-weight: 600; }}
.bi-warn {{ color: {c['warn']}; }}
.bi-danger {{ color: {c['danger']}; }}
.bi-card {{ border: 1px solid {a(c['dim'], .55 if not hc else 1)}; background-color: {a(c['panel'], .85)}; padding: 14px 18px; }}
.bi-status {{ font-size: 1.15em; color: {c['soft']}; }}
.bi-big {{ font-size: 1.15em; padding: 10px 26px; letter-spacing: 0.08em; }}
.bi-split {{ font-weight: 700; letter-spacing: 0.06em; }}
.bi-split.them {{ color: {c.get('cyan', c['soft'])}; }}
.bi-split.us {{ color: {c['primary']}; }}
.bi-limit {{ font-size: 0.85em; }}
.bi-limit.them {{ color: {c.get('cyan', c['soft'])}; }}
.bi-limit.us {{ color: {c['primary']}; }}
.bi-splitbar:focus-visible {{ outline: 2px solid {c['primary']}; outline-offset: 2px; }}
progressbar > trough {{ min-height: 10px; background-color: {a(c['dim'], .3)}; border-radius: 0; }}
progressbar > trough > progress {{ min-height: 10px; background-color: {c['primary']}; border-radius: 0;
  box-shadow: 0 0 8px {a(c['primary'], .45 if not hc else 0)}; }}
textview, textview text {{ background-color: {c['void']}; color: {c['muted']}; font-size: 0.85em; }}
"""


class SplitBar(Gtk.DrawingArea):
    """Install alongside's split, drawn as the partition it divides: the other system from the
    left (its colour), bromigOS from the right (the primary), the handle at the split, and
    each side's minimum striped at its end, so it's plain why the handle stops there. Arrow
    keys move it 1 GB, Page Up/Down 10 GB, Home/End to the limits; it shows when it has the
    focus. `value` is the other system's share, GB (as the bar reads, left to right)."""

    def __init__(self, total, lo, hi, value, who, c):
        super().__init__(accessible_role=Gtk.AccessibleRole.SLIDER)
        self.total, self.lo, self.hi, self.who, self.c = total, lo, hi, who, c
        self.value = max(lo, min(hi, value))
        self.on_change = None
        self.set_focusable(True)
        self.set_can_focus(True)
        self.set_hexpand(True)
        self.set_content_height(46)
        self.add_css_class("bi-splitbar")
        self.set_draw_func(self._draw)
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

    def _a11y(self):
        try:
            self.update_property(
                [Gtk.AccessibleProperty.LABEL, Gtk.AccessibleProperty.VALUE_MIN, Gtk.AccessibleProperty.VALUE_MAX,
                 Gtk.AccessibleProperty.VALUE_NOW, Gtk.AccessibleProperty.VALUE_TEXT],
                [f"Room for {self.who}, in gigabytes", float(self.lo), float(self.hi), float(self.value),
                 f"{self.who} {self.value:.0f} GB, bromigOS {self.total - self.value:.0f} GB"])
        except Exception:
            pass

    def set_value(self, v):
        v = max(self.lo, min(self.hi, round(v)))
        if v != self.value:
            self.value = v
            self._a11y()
            self.queue_draw()
            if self.on_change:
                self.on_change(v)

    def _at(self, x):
        w = max(1, self.get_width() - 12)
        self.set_value((x - 6) / w * self.total)

    def _key(self, ctl, keyval, code, state):
        step = {Gdk.KEY_Left: -1, Gdk.KEY_KP_Left: -1, Gdk.KEY_Right: 1, Gdk.KEY_KP_Right: 1,
                Gdk.KEY_Page_Down: -10, Gdk.KEY_Page_Up: 10}.get(keyval)
        if step:
            self.set_value(self.value + step)
            return True
        if keyval in (Gdk.KEY_Home, Gdk.KEY_End):
            self.set_value(self.lo if keyval == Gdk.KEY_Home else self.hi)
            return True
        return False

    def _draw(self, area, cr, width, height):
        def rgb(h, a=1.0):
            h = h.lstrip("#")
            cr.set_source_rgba(int(h[0:2], 16) / 255, int(h[2:4], 16) / 255, int(h[4:6], 16) / 255, a)
        c = self.c
        x0, x1, y0, y1 = 6, width - 6, 12, height - 12
        span = x1 - x0
        at = lambda gb: x0 + span * gb / self.total        # noqa: E731
        split = at(self.value)
        rgb(c.get("cyan", c["soft"]), 0.55)                # the other system's share, its own colour
        cr.rectangle(x0, y0, split - x0, y1 - y0)
        cr.fill()
        rgb(c["primary"], 0.85)                            # bromigOS's
        cr.rectangle(split, y0, x1 - split, y1 - y0)
        cr.fill()
        # each side's minimum, striped: the handle can't go into them
        for a, b in ((x0, at(self.lo)), (at(self.hi), x1)):
            cr.save()
            cr.rectangle(a, y0, b - a, y1 - y0)
            cr.clip()
            rgb(c["void"], 0.55)
            cr.set_line_width(2)
            x = a - (y1 - y0)
            while x < b:
                cr.move_to(x, y1)
                cr.line_to(x + (y1 - y0), y0)
                x += 7
            cr.stroke()
            cr.restore()
            rgb(c["text"], 0.75)                           # the limit itself
            cr.rectangle(b - 1 if a == x0 else a, y0 - 4, 2, y1 - y0 + 8)
            cr.fill()
        rgb(c["dim"], 0.9)                                 # the frame
        cr.set_line_width(1)
        cr.rectangle(x0 + 0.5, y0 + 0.5, span - 1, y1 - y0 - 1)
        cr.stroke()
        focused = self.is_focus()
        rgb(c["text"])                                     # the handle
        cr.rectangle(split - 4, y0 - 9, 8, y1 - y0 + 18)
        cr.fill()
        if focused:                                        # the focus: a ring around the handle
            rgb(c["primary"])
            cr.set_line_width(2)
            cr.rectangle(split - 8, y0 - 12, 16, y1 - y0 + 24)
            cr.stroke()


def hint(widget, text):
    """Every control says what it is and what it does, on hover; the same words are its
    accessible description, for a screen reader (Orca)."""
    if text:
        widget.set_tooltip_text(text)
        try:
            widget.update_property([Gtk.AccessibleProperty.DESCRIPTION], [text])
        except Exception:
            pass
    return widget


def label(text, classes=(), wrap=True, xalign=0.0, selectable=False):
    lab = Gtk.Label(label=text, wrap=wrap, xalign=xalign, selectable=selectable)
    lab.set_wrap_mode(2)            # word-char
    for c in classes:
        lab.add_css_class(c)
    return lab


class Emblem(Gtk.DrawingArea):
    """The FLARE: the emblem's ring and flame (the splash's art), the ring turning
    counter-clockwise once in 24 s (the canon), still when motion is reduced."""

    def __init__(self, size, still):
        super().__init__()
        self.set_content_width(size)
        self.set_content_height(size)
        self.still = still
        self.t0 = time.monotonic()
        self.ring = self.flame = None
        try:
            gi.require_version("GdkPixbuf", "2.0")
            from gi.repository import GdkPixbuf
            self.ring = GdkPixbuf.Pixbuf.new_from_file(os.path.join(ART, "ring.png"))
            self.flame = GdkPixbuf.Pixbuf.new_from_file(os.path.join(ART, "flame.png"))
        except Exception:
            pass
        self.set_draw_func(self.draw)
        if not still:
            self.add_tick_callback(lambda *_: (self.queue_draw(), True)[1])
        hint(self, "bromigOS's emblem")

    def draw(self, area, cr, w, h):
        if not self.ring:
            c, _ = common.theme()
            rgb = [int(c["primary"][i:i + 2], 16) / 255 for i in (1, 3, 5)]
            cr.set_source_rgb(*rgb)
            cr.set_line_width(max(2, w / 40))
            cr.arc(w / 2, h / 2, w * 0.42, 0, 2 * math.pi)
            cr.stroke()
            return
        angle = 0 if self.still else -2 * math.pi * ((time.monotonic() - self.t0) % 24) / 24
        for pb, rot in ((self.ring, angle), (self.flame, 0)):
            s = min(w / pb.get_width(), h / pb.get_height())
            cr.save()
            cr.translate(w / 2, h / 2)
            cr.rotate(rot)
            cr.scale(s, s)
            Gdk.cairo_set_source_pixbuf(cr, pb, -pb.get_width() / 2, -pb.get_height() / 2)
            cr.paint()
            cr.restore()


# VECTOR's one line per step, in the rail's corner: the voice guide's catalogue
# (lib/guide/lines.toml, installer.*), so the caption and his clip say the same words
def caption(line_id, **values):
    return guide.line(line_id, **values) if guide else ""


class Window(Adw.ApplicationWindow):
    def __init__(self, app, opts):
        super().__init__(application=app, title="Install bromigOS")
        self.opts = opts
        self.a = common.defaults()
        self.probe = None
        self.step = "guide"
        self.done = None
        self.running = None
        self.lines = []
        self.reduced = common.reduced_motion()
        self.hc_forced = False               # the first step's High contrast, over the system's
        self._dpi = None                     # the first step's Larger text: the screen's own size, to go back to
        # VECTOR's voice: one player for this window, quiet in pictures (--render); its on and
        # muted are the live session's (voice-guide.json), copied to the new user at the end
        self.voice = guide.Guide("gui", notify=self._voice_notice) if guide and not opts.get("render") else None
        if self.voice and backend.FAKE:      # --fake (pictures, tests): it never makes a sound
            self.voice._out = (None, "The fake installer makes no sound.")
        if guide and opts.get("render"):     # pictures: a player that never makes a sound, its settings nobody's
            self.voice = guide.Guide("gui", state=os.devnull, root="/nonexistent")
            self.voice._out = ("pw-play", None)
            self.voice.play = self.voice.say = lambda *a, **k: False
        self._spoken = None
        g = self.a["guidance"]
        if self.voice:
            g.update(voice=self.voice.enabled, voice_muted=self.voice.muted)
        self.zones = common.timezones()
        self.eds = common.editions()
        self.set_default_size(*opts.get("size", (1280, 800)))
        glass.use_icon_theme()
        self._css = Gtk.CssProvider()
        Gtk.StyleContext.add_provider_for_display(Gdk.Display.get_default(), self._css, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
        self.restyle()
        Adw.StyleManager.get_default().connect("notify::high-contrast", lambda *_: self.restyle())

        root = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        self.rail = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.rail.add_css_class("bi-rail")
        # in a scroller of its own: on a short screen (1024×600, eleven steps) the rail scrolls
        # instead of asking for more height, which GTK would otherwise answer by widening it
        self.rail_scroll = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER, propagate_natural_width=True)
        self.rail_scroll.set_child(self.rail)
        root.append(self.rail_scroll)
        right = Adw.ToolbarView()
        head = Adw.HeaderBar(show_end_title_buttons=False, show_start_title_buttons=False)
        self.title = label("BROMIGOS // INSTALL", wrap=False)
        self.title.add_css_class("title")
        hint(self.title, "The bromigOS installer. Nothing changes on any disk until you press Install.")
        head.set_title_widget(self.title)
        right.add_top_bar(head)
        self.scroll = Gtk.ScrolledWindow(hexpand=True, vexpand=True)
        self.clamp = Adw.Clamp(maximum_size=1200, tightening_threshold=900)
        self.scroll.set_child(self.clamp)
        right.set_content(self.scroll)
        bar = Gtk.Box(spacing=12)
        bar.add_css_class("bi-bar")
        self.err = label("", ("bi-error",))
        self.err.set_hexpand(True)
        self.err.update_property([Gtk.AccessibleProperty.LABEL], ["Problems"])
        self.back = hint(Gtk.Button(label="Back"), "Go back one step. Nothing changes on any disk until you press Install.")
        self.back.add_css_class("bi-big")
        self.next = hint(Gtk.Button(label="Continue"), "Go on to the next step (Enter).")
        self.next.add_css_class("bi-big")
        self.next.add_css_class("suggested-action")
        self.back.connect("clicked", lambda *_: self.go_back())
        self.next.connect("clicked", lambda *_: self.go_next())
        # VECTOR's voice, one key away everywhere: what it's doing now, and a click to change it
        self.voice_btn = Gtk.Button(valign=Gtk.Align.CENTER)
        self.voice_btn.add_css_class("flat")
        self.voice_btn.connect("clicked", lambda *_: self.toggle_voice())
        bar.append(self.voice_btn)
        bar.append(self.err)
        bar.append(self.back)
        bar.append(self.next)
        right.add_bottom_bar(bar)
        root.append(right)
        right.set_hexpand(True)
        self.set_content(root)
        # small screens (1024×600 netbooks, a scaled 1366×768): the step rail gives way below
        # 900 px (the title still says the step), the page's margins tighten
        self.set_size_request(360, 480)
        try:
            bp = Adw.Breakpoint.new(Adw.BreakpointCondition.parse("max-width: 900sp"))
            bp.add_setter(self.rail_scroll, "visible", False)
            bp.connect("apply", lambda *_: setattr(self, "compact", True) or self._retitle())
            bp.connect("unapply", lambda *_: setattr(self, "compact", False) or self._retitle())
            self.add_breakpoint(bp)
        except (AttributeError, TypeError):      # libadwaita before 1.4: the rail stays
            pass
        keys = Gtk.EventControllerKey()
        keys.connect("key-pressed", self.on_key)
        self.add_controller(keys)
        if guide:                            # Ctrl+Alt+V: the voice guide on, then muted and back, anywhere
            sc = Gtk.ShortcutController(scope=Gtk.ShortcutScope.GLOBAL)
            sc.add_shortcut(Gtk.Shortcut.new(Gtk.ShortcutTrigger.parse_string(guide.GTK_ACCEL),
                                             Gtk.CallbackAction.new(lambda *_: (self.toggle_voice(), True)[1])))
            self.add_controller(sc)
        self.connect("close-request", lambda *_: (self.voice and self.voice.stop(), False)[1])
        self.answer_file, problems = None, []
        path = None if opts.get("render") or opts.get("script") else common.find_answer_file()
        if path:
            a, problems = common.read_answer_file(path)
            self.answer_file = path
            self.a.update({k: v for k, v in a.items() if v not in (None, "")})
            if not problems:
                self.a["auto"] = True
                self.countdown = int(a.get("countdown", 10))
        self.show_step("auto" if self.a.get("auto") else self.first_step())
        if problems:
            self.err.set_label(f"▲ The answer file {path} has problems, so the installer asks instead: " + " ".join(problems))
        if not opts.get("render"):
            self._probe_async()

    # ── look ────────────────────────────────────────────────────────────────────────
    def restyle(self):
        c, _ = common.theme()
        hc = self.hc_forced or Adw.StyleManager.get_default().get_high_contrast()
        if hc:
            c = dict(c, muted=c["text"], faint=c["soft"], dim=c["primary"])
        self.c = c
        self._css.load_from_string(settings_css(c) + installer_css(c, hc) + glass.css(c, hc))

    def on_key(self, ctl, keyval, code, state):
        ctrl_alt = Gdk.ModifierType.CONTROL_MASK | Gdk.ModifierType.ALT_MASK
        if keyval in (Gdk.KEY_t, Gdk.KEY_T) and (state & ctrl_alt) == ctrl_alt:
            backend.open_shell()                 # a shell, one keystroke away (the installer stays open)
            return True
        if keyval == Gdk.KEY_Escape and self.step not in ("install", "done"):
            if self.voice:
                self.voice.stop()                # Esc first quiets him
            self.go_back()
            return True
        return False

    # ── VECTOR's voice ──────────────────────────────────────────────────────────────
    def first_step(self):
        return self.steps()[0]

    def _voice_notice(self, words):
        """No sound device: said once, where problems are said."""
        GLib.idle_add(lambda: (self.err.set_label("▲ " + words), self._voice_shown(), False)[-1])

    def _voice_shown(self):
        """The bar's voice button and the first step's line say what the voice guide is doing."""
        if not hasattr(self, "voice_btn"):
            return
        if not self.voice:
            self.voice_btn.set_visible(False)
            return
        st = self.voice.status()
        icon = {"on": "audio-volume-high-symbolic", "muted": "audio-volume-muted-symbolic",
                "screen-reader": "audio-volume-muted-symbolic", "no-sound": "audio-volume-muted-symbolic"}.get(
                    st, "audio-volume-muted-symbolic")
        word = {"on": "Voice on", "muted": "Voice muted", "off": "Voice off", "screen-reader": "Voice quiet",
                "no-sound": "No sound"}[st]
        box = Gtk.Box(spacing=6)
        box.append(Gtk.Image.new_from_icon_name(icon))
        box.append(Gtk.Label(label=f"{word} · {guide.HOTKEY}"))
        self.voice_btn.set_child(box)
        hint(self.voice_btn, self.voice.describe() + " Click, or press " + guide.HOTKEY + ", to change it.")
        if getattr(self, "voice_state", None) is not None and self.step == "guide":
            self.voice_state.set_label(self.voice.describe())
            if self.voice_switch.get_active() != self.voice.enabled:
                self._voice_sync = True
                self.voice_switch.set_active(self.voice.enabled)
                self._voice_sync = False

    def toggle_voice(self):
        """Ctrl+Alt+V, or the bar's button: on when it's off, then muted and back."""
        if not self.voice:
            return
        self.voice.toggle()
        self.a["guidance"].update(voice=self.voice.enabled, voice_muted=self.voice.muted)
        self._spoken = None
        if self.voice.status() == "on":
            self.speak_step()
        self._voice_shown()

    def line_id(self, sid):
        """The catalogue's id for a step's line, and its {values}."""
        if sid == "done" and self.done is not True:
            return "installer.failed", {}
        if sid == "disk" and self.a.get("mode"):
            d = self.disk()
            who = ((d or {}).get("options", {}).get("alongside", {}).get("who")) or "Windows"
            lid = f"installer.disk.{self.a['mode']}"
            return (lid, {"who": who}) if guide and guide.has(lid) else ("installer.disk", {})
        return f"installer.{sid}", {}

    def speak_step(self, lid=None, values=None):
        """VECTOR says the step's line, once: a redraw of the same step doesn't repeat it."""
        if not self.voice:
            return
        if lid is None:
            lid, values = self.line_id(self.step)
        key = (lid, tuple(sorted((values or {}).items())))
        if key == self._spoken:
            return
        self._spoken = key
        self.voice.play(lid, **(values or {}))

    # ── the disks, read in the background ───────────────────────────────────────────
    def _probe_async(self):
        import threading

        def work():
            doc = backend.probe()
            GLib.idle_add(self._probed, doc)
        threading.Thread(target=work, daemon=True).start()

    def _probed(self, doc):
        self.probe = doc
        self.a["other_os"] = doc.get("other_os", False)
        found = common.checks(doc)
        self.a["checks"] = [c for c in found if c["level"] == "warn"]
        self.a["checks_info"] = [c for c in found if c["level"] != "warn"]
        if self.step == "guide":              # the rail only (a Checks step may come in): the switches keep the focus
            self.draw_rail()
            self._retitle()
        elif self.step in ("disk", "welcome"):
            self.show_step(self.step)
        return False

    def disk(self):
        return next((d for d in (self.probe or {}).get("disks", []) if d["path"] == self.a["disk"]), None)

    # ── the steps ───────────────────────────────────────────────────────────────────
    def steps(self):
        self.a["edition_info"] = common.edition(self.a["edition"])
        d = self.disk()
        self.a["bitlocker"] = bool(d and d.get("bitlocker"))
        return common.steps_for(self.a)

    def show_step(self, sid, speak=True):
        self.step = sid
        steps = self.steps()
        here = steps.index(sid) if sid in steps else 0
        self.draw_rail(steps, here)
        self._retitle()
        page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=14, margin_top=28, margin_bottom=28,
                       margin_start=24, margin_end=24)
        getattr(self, f"build_{sid}")(page)
        self.clamp.set_child(page)
        self.scroll.get_vadjustment().set_value(0)      # a new step starts at its top
        self.err.set_label("")
        self.back.set_visible(sid not in ("guide", "install", "done", "auto"))
        self.next.set_visible(sid not in ("install", "done", "auto"))
        self.next.set_label("Continue")
        self.next.remove_css_class("destructive-action")
        self.next.add_css_class("suggested-action")
        hint(self.next, "Go on to the next step (Enter).")
        if getattr(self, "editing", None) and sid != "summary":
            self.next.set_label("Back to the summary")
            hint(self.next, "Keep this change and go straight back to the summary (Enter).")
        if sid == "summary":
            erase = self.a["mode"] == "erase"
            self.next.set_label("Erase disk and install" if erase else "Install")
            if erase:
                self.next.remove_css_class("suggested-action")
                self.next.add_css_class("destructive-action")
            hint(self.next, "Start the install. " + ("Everything on the disk is deleted." if erase else "Nothing you have is deleted."))
        self.set_default_widget(self.next if self.next.get_visible() else None)
        GLib.idle_add(self.next.grab_focus if sid not in ("install", "done") else (lambda: False))
        if self.opts.get("script") and sid != "auto":
            GLib.timeout_add(300, self.script_step)
        if speak:
            self.speak_step()
        else:
            self._spoken = self.line_id(sid)[0], tuple(sorted(self.line_id(sid)[1].items()))
        self._voice_shown()

    def draw_rail(self, steps=None, here=None):
        """The rail: where you are, each step's icon, the progress line, VECTOR in the corner."""
        steps = steps or self.steps()
        sid = self.step
        here = here if here is not None else (steps.index(sid) if sid in steps else 0)
        # VECTOR is the screen's one FLARE, except while installing (the ring) and when it's done
        # (the burn-in): then he stays still
        self.guide = glass.guide(self.vector_line(sid), "idle" if sid == "install" else "speaking",
                                 still=self.reduced or sid in ("install", "done") or bool(self.opts.get("render")),
                                 size=(90, 126) if self.screen_h() < 700 else (120, 178))
        glass.rail(self.rail, steps, here, common.STEP, self.c, self.guide)

    def vector_line(self, sid):
        lid, values = self.line_id(sid)
        return caption(lid, **values)

    def _retitle(self):
        steps = self.steps()
        here = steps.index(self.step) + 1 if self.step in steps else 1
        if getattr(self, "compact", False):
            self.title.set_label(f"INSTALL · {here}/{len(steps)} · {common.STEP[self.step][1].upper()}")
        else:
            self.title.set_label(f"BROMIGOS // INSTALL   ·   STEP {here} OF {len(steps)}")

    def heading(self, page, sid):
        _, _, head, intro = common.STEP[sid]
        page.append(label(head.upper(), ("bi-heading",)))
        page.append(label(intro, ("bi-intro",)))


    def screen_h(self):
        """The window's height, or (before it has one) its screen's: a short screen (1024×600)
        gets a smaller VECTOR, so the rail fits without stretching sideways."""
        h = self.get_height()
        if h:
            return h
        if self.opts.get("render") or self.opts.get("windowed"):
            return self.opts.get("size", (1280, 800))[1]
        try:
            mons = Gdk.Display.get_default().get_monitors()
            return min(mons.get_item(i).get_geometry().height for i in range(mons.get_n_items())) or 800
        except Exception:
            return 800

    def content_width(self):
        """How wide the page is (the window less the rail and the margins): a few steps lay
        out in two columns when there's room."""
        w = self.get_width() or self.opts.get("size", (1280, 800))[0]
        return w - (0 if getattr(self, "compact", False) else 232) - 48

    def _auto_fill(self):
        """The answer file's plan, as the summary's briefing (without Edit: it's not asking)."""
        if self._auto_filled or common.auto_check(self.a, self.probe):
            return
        rows, warn = common.summary(self.a, self.disk())
        self.auto_group.append(self.briefing_ui(self.brief_rows(rows, edit=False), edit=False))
        self._auto_warn = warn
        self.auto_line.set_label(f"Installing in {self.countdown} s." + (f" {warn}" if warn else ""))
        self._auto_filled = True

    def validate_user(self):
        """Each field's ✓ or ▲ (the same checks Continue makes), and the card's head: the
        name, how you sign in, and how much is left."""
        if not getattr(self, "marks", None):
            return
        t = {k: (r.get_text() if k.startswith("password") else r.get_text().strip()) for k, r in self.f.items()}
        problems = {
            "full_name": common.check_full_name(t["full_name"]),
            "user": common.check_username(t["user"]),
            "password": common.check_password(t["password"], t["password"]),
            "password2": common.check_password(t["password"], t["password2"]) if t["password2"] else "Type the password again.",
            "hostname": common.check_hostname(t["hostname"]),
        }
        for k, mark in self.marks.items():
            glass.set_valid(mark, problems[k], shown=bool(t[k]))
        name = t["full_name"] or t["user"]
        self.portrait.set_name(name)
        self.id_name.set_label(name.upper() if name else "NOT NAMED YET")
        (self.id_name.remove_css_class if name else self.id_name.add_css_class)("empty")
        self.id_handle.set_label(f"{t['user'] or '…'}  on  {t['hostname'] or '…'}")
        left = sum(1 for p in problems.values() if p)
        for cl in ("warn", "quiet"):
            self.id_chip.remove_css_class(cl)
        if not left:
            self.id_chip.set_label("● ID COMPLETE")
            hint(self.id_chip, "Everything here is filled in and fine")
        else:
            self.id_chip.set_label(f"▲ {left} LEFT TO DO")
            self.id_chip.add_css_class("warn" if any(t.values()) else "quiet")
            hint(self.id_chip, "Fields still to fill in or fix: the ▲ beside each says what")

    def brief_rows(self, rows, edit=True):
        """The summary's rows for glass.briefing: each with its icon and the step that sets it."""
        steps = self.steps() if edit else []
        d = self.disk() or {}
        look = {"Kind": ("computer-symbolic", "edition"), "Language": ("preferences-desktop-locale-symbolic", "guide"),
                "Time zone": ("preferences-system-time-symbolic", "welcome"), "Keyboard": ("input-keyboard-symbolic", "keyboard"),
                "Disk": (glass.drive_icon(d) if d else "drive-harddisk-symbolic", "disk"),
                "Boot menu": ("system-reboot-symbolic", "disk"), "Name": ("avatar-default-symbolic", "user"),
                "User name": ("user-info-symbolic", "user"), "Computer name": ("network-workgroup-symbolic", "user"),
                "Encryption": ("system-lock-screen-symbolic" if self.a.get("encrypt") else "changes-allow-symbolic", "encryption"),
                "Remote access (SSH)": ("network-server-symbolic", "ssh"), "Firewall": ("security-high-symbolic", "ssh"),
                "Automatic updates": ("view-refresh-symbolic", "ssh"), "Packages": ("folder-download-symbolic", None)}
        out = []
        for k, v in rows:
            ic, target = look.get(k, ("document-properties-symbolic", None))
            out.append((ic, k, v, target if target in steps else None, k == "Disk" and self.a.get("mode") == "erase"))
        return out

    def briefing_ui(self, brief, edit=True):
        """The briefing card: in two columns (the computer, then you) when there's room."""
        tip = lambda k, t: f"Go back to {common.STEP[t][1]} to change {k.lower()}; Continue brings you back here."  # noqa: E731
        on_edit = self.edit_step if edit else None
        if self.content_width() >= 900 and len(brief) > 6:
            split = next((i for i, r in enumerate(brief) if r[1] == "Name"), (len(brief) + 1) // 2)
            cols = Gtk.Box(spacing=14, homogeneous=True)
            for title, part in (("Briefing · the computer", brief[:split]), ("Briefing · you", brief[split:])):
                b = glass.briefing(title, part, on_edit, tip)
                b.set_valign(Gtk.Align.START)
                cols.append(b)
            return cols
        return glass.briefing("Briefing · your choices" if edit else "What it will do", brief, on_edit, tip)

    def edit_step(self, sid):
        """An Edit link on the summary: that step, then Continue comes straight back here
        (unless the change adds or removes steps, when it goes through them)."""
        self.editing = tuple(self.steps())
        self.show_step(sid)

    def group(self, page, title, description=None):
        g = Adw.PreferencesGroup(title=GLib.markup_escape_text(title.upper()))
        if description:
            g.set_description(GLib.markup_escape_text(description))
        page.append(g)
        return g

    def build_auto(self, page):
        self.heading(page, "auto")
        page.append(label(f"From {self.answer_file}", ("bi-intro",)))
        body = Gtk.Box(spacing=28)
        left = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12, valign=Gtk.Align.START)
        self.count_ring = glass.Countdown(self.c, getattr(self, "countdown", 10), 180)
        hint(self.count_ring, "The seconds left before it installs by itself. Cancel stops it.")
        left.append(self.count_ring)
        cancel = hint(Gtk.Button(label="Cancel", halign=Gtk.Align.CENTER),
                      "Stop the automatic install and answer the questions yourself. Nothing has changed yet.")
        cancel.add_css_class("destructive-action")
        cancel.add_css_class("bi-big")
        cancel.connect("clicked", lambda *_: (self.a.update(auto=False), self.show_step(self.first_step())))
        left.append(cancel)
        body.append(left)
        right = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12, hexpand=True)
        self.auto_line = label("Looking at the disks…", ("bi-status",))
        self.auto_line.update_property([Gtk.AccessibleProperty.LABEL], ["Countdown"])
        right.append(self.auto_line)
        self.auto_group = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        right.append(self.auto_group)
        body.append(right)
        page.append(body)
        self.set_default_widget(cancel)
        GLib.idle_add(cancel.grab_focus)
        self._auto_filled = False
        if self.probe is not None:
            self._auto_fill()
        GLib.timeout_add_seconds(1, self.auto_tick)


    def auto_tick(self):
        if self.step != "auto" or not self.a.get("auto"):
            return False
        if self.probe is None:
            return True
        problem = common.auto_check(self.a, self.probe)
        if problem:
            self.a["auto"] = False
            self.show_step(self.first_step())
            self.err.set_label("▲ " + problem + " The installer asks instead.")
            return False
        self._auto_fill()
        if self.countdown <= 0:
            self.a["auto"] = False
            self.start_install()
            return False
        self.countdown -= 1
        self.count_ring.set_left(self.countdown)
        warn = getattr(self, "_auto_warn", None)
        self.auto_line.set_label(f"Installing in {self.countdown} s." + (f" {warn}" if warn else ""))
        return True


    def build_guide(self, page):
        """How would you like to be guided? VECTOR's voice (off until it's turned on, with a
        sample), the screen reader, larger text, high contrast, less motion; and the language.
        Each takes effect at once, and the new system starts the same way."""
        g = self.a["guidance"]
        self.heading(page, "guide")
        # the voice guide: the big switch, a sample, what it's doing now
        card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        card.add_css_class("dg-panel")
        top = Gtk.Box(spacing=16, margin_top=16, margin_bottom=6, margin_start=18, margin_end=18)
        top.append(glass.icon("audio-speakers-symbolic", 40, "dg-row-icon"))
        words = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4, hexpand=True, valign=Gtk.Align.CENTER)
        words.append(label("VECTOR's voice guide", ("dg-strong", "bi-status")))
        words.append(label("He reads each step aloud, in his own voice. " + (guide.HOTKEY + " turns him on, then mutes him, "
                           "anywhere." if guide else ""), ("dg-muted",)))
        top.append(words)
        self.voice_switch = Gtk.Switch(valign=Gtk.Align.CENTER, active=bool(self.voice and self.voice.enabled))
        self.voice_switch.set_size_request(72, 36)
        self.voice_switch.update_property([Gtk.AccessibleProperty.LABEL], ["VECTOR's voice guide"])
        hint(self.voice_switch, "On: VECTOR reads each step aloud. Off: his words stay on screen only. " +
             (guide.HOTKEY + " does the same from anywhere." if guide else ""))
        self.voice_switch.connect("notify::active", self.on_voice_switch)
        self.voice_switch.set_sensitive(bool(self.voice))
        top.append(self.voice_switch)
        card.append(top)
        low = Gtk.Box(spacing=12, margin_bottom=16, margin_start=18 + 56, margin_end=18)
        sample = hint(Gtk.Button(label="Play a sample", valign=Gtk.Align.CENTER),
                      "Hear VECTOR's voice now, once, before you decide")
        sample.set_sensitive(bool(self.voice))
        sample.connect("clicked", lambda *_: self.play_sample())
        low.append(sample)
        self.voice_state = label(self.voice.describe() if self.voice else
                                 "VECTOR's voice isn't on this USB stick: his words are on screen.", ("dg-muted",))
        self.voice_state.set_hexpand(True)
        self.voice_state.update_property([Gtk.AccessibleProperty.LABEL], ["The voice guide's state"])
        low.append(self.voice_state)
        card.append(low)
        page.append(card)
        # the other help: each switch works at once
        grp = self.group(page, "More help")
        self.guidance_rows = {}
        for key, icon, title, sub, tip in (
                ("screen_reader", "preferences-desktop-accessibility-symbolic", "Screen reader",
                 "Orca reads everything on the screen aloud. VECTOR stays quiet while it talks.",
                 "Start or stop Orca. Insert+S stops it talking for a moment; Insert+Q quits it."),
                ("large_text", "format-text-larger-symbolic", "Larger text", "Bigger letters everywhere.",
                 "Makes all the text a quarter bigger, here and on your new system"),
                ("high_contrast", "display-brightness-symbolic", "High contrast", "Stronger colours: solid panels, no glow.",
                 "Raises the colours' contrast, here and on your new system"),
                ("reduce_motion", "media-playback-pause-symbolic", "Reduce motion", "Nothing moves or pulses on its own.",
                 "Holds the animations still, here and on your new system")):
            row = Adw.ActionRow(title=title, subtitle=sub)
            row.set_subtitle_lines(0)
            row.add_prefix(glass.icon(icon, 22, "dg-row-icon"))
            sw = Gtk.Switch(valign=Gtk.Align.CENTER, active=bool(g.get(key)))
            sw.update_property([Gtk.AccessibleProperty.LABEL], [title])
            hint(sw, tip)
            sw.connect("notify::active", lambda w, _p, k=key: self.on_guidance(k, w.get_active()))
            row.add_suffix(sw)
            row.set_activatable_widget(sw)
            hint(row, tip)
            grp.add(row)
            self.guidance_rows[key] = (row, sw)
        self.guidance_said = label("", ("dg-muted",))
        self.guidance_said.update_property([Gtk.AccessibleProperty.LABEL], ["What changed"])
        page.append(self.guidance_said)
        # the language: the first thing anyone chooses, so it's here too
        g2 = self.group(page, "Language")
        langs = Gtk.StringList.new([n for _, n, _ in common.LANGUAGES])
        row = Adw.ComboRow(title="Language for your new system", model=langs)
        row.add_prefix(glass.icon("preferences-desktop-locale-symbolic", 20, "dg-row-icon"))
        row.set_selected([loc for loc, _, _ in common.LANGUAGES].index(self.a["locale"]))
        hint(row, "The language bromigOS uses once it's installed: menus, dates and numbers. The installer itself is in English.")
        row.connect("notify::selected", self.on_language)
        g2.add(row)
        self.lang_row = row
        self.set_default_widget(self.next)
        GLib.idle_add(self.voice_switch.grab_focus)

    def on_voice_switch(self, sw, _p):
        if getattr(self, "_voice_sync", False) or not self.voice:
            return
        on = sw.get_active()
        self.voice.set_enabled(on)
        if on and self.voice.muted:
            self.voice.set_muted(False)
        self.a["guidance"].update(voice=on, voice_muted=self.voice.muted)
        self._spoken = None
        if on:
            self.speak_step()
        self._voice_shown()

    def play_sample(self):
        if not self.voice:
            return
        if not self.voice.play("installer.guide.sample", force=True):
            st = self.voice.status()
            self.voice_state.set_label("VECTOR stays quiet while your screen reader talks." if st == "screen-reader"
                                       else self.voice.notice or self.voice.describe())
        else:
            self.voice_state.set_label("Playing a sample of VECTOR's voice.")

    def on_guidance(self, key, on):
        """One of the first step's switches: it takes effect here at once."""
        if getattr(self, "_guidance_sync", False):
            return
        self.a["guidance"][key] = on
        said = ""
        if key == "screen_reader":
            import threading

            def work():
                ok, words = backend.screen_reader(on, "wayland")
                GLib.idle_add(self._guidance_done, key, ok, words)
            threading.Thread(target=work, daemon=True).start()
            said = "Starting Orca…" if on else "Stopping Orca…"
        elif key == "large_text":
            st = Gtk.Settings.get_default()
            if self._dpi is None:
                self._dpi = st.get_property("gtk-xft-dpi")
            base = self._dpi if self._dpi and self._dpi > 0 else 96 * 1024
            st.set_property("gtk-xft-dpi", int(base * 1.25) if on else base)
            said = "Larger text is on." if on else "Larger text is off."
        elif key == "high_contrast":
            self.hc_forced = on
            self.restyle()
            said = "High contrast is on." if on else "High contrast is off."
        elif key == "reduce_motion":
            if on:
                os.environ["BROMIGOS_REDUCED_MOTION"] = "1"      # the widgets drawn from now on hold still too
            else:
                os.environ.pop("BROMIGOS_REDUCED_MOTION", None)
            self.reduced = common.reduced_motion()
            self.draw_rail()
            said = "Reduced motion is on: nothing moves on its own." if on else "Reduced motion is off."
        self.guidance_said.set_label(said)
        if hasattr(self.guidance_said, "announce"):
            self.guidance_said.announce(said, Gtk.AccessibleAnnouncementPriority.MEDIUM)

    def _guidance_done(self, key, ok, words):
        if not ok:
            self.a["guidance"][key] = False
        if self.step != "guide":
            return False
        self.guidance_said.set_label(("" if ok else "▲ ") + words)
        if not ok:                           # it didn't start: the switch says so, and what to do is under it
            self._guidance_sync = True
            self.guidance_rows[key][1].set_active(False)
            self._guidance_sync = False
        self._voice_shown()
        return False

    def build_welcome(self, page):
        hero = Gtk.Box(spacing=24)
        emb = Emblem(112, True)              # still: VECTOR is this screen's one FLARE
        emb.set_valign(Gtk.Align.CENTER)
        hero.append(emb)
        col = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10, valign=Gtk.Align.CENTER, hexpand=True)
        self.heading(col, "welcome")
        hero.append(col)
        page.append(hero)
        facts = Gtk.Box(spacing=12, homogeneous=True)
        for ic, word, tip in (("preferences-system-time-symbolic", "About ten minutes", "How long the install takes, "
                               "on most computers"),
                              ("changes-prevent-symbolic", "Nothing changes until Install", "Every step can be gone back to: "
                               "the disk is only touched once you press Install"),
                              ("edit-undo-symbolic", "Change any of it later", "Everything chosen here can be changed "
                               "afterwards, in Settings")):
            f = Gtk.Box(spacing=10)
            f.add_css_class("dg-panel")
            f.set_margin_top(2)
            inner = Gtk.Box(spacing=10, margin_top=10, margin_bottom=10, margin_start=12, margin_end=12)
            inner.append(glass.icon(ic, 18, "dg-row-icon"))
            inner.append(label(word, ("dg-strong",)))
            f.append(inner)
            hint(f, tip)
            facts.append(f)
        page.append(facts)
        g = self.group(page, "Time")      # the language is on the first step, with how you're guided
        zones = Gtk.StringList.new(self.zones)
        tz = Adw.ComboRow(title="Time zone", model=zones, enable_search=True)
        tz.add_prefix(glass.icon("preferences-system-time-symbolic", 20, "dg-row-icon"))
        tz.set_expression(Gtk.PropertyExpression.new(Gtk.StringObject, None, "string"))
        tz.set_selected(self.zones.index(self.a["timezone"]) if self.a["timezone"] in self.zones else 0)
        hint(tz, "Where you are, for the clock. Open it and type a city or region to find it.")
        tz.connect("notify::selected", lambda r, _p: self.a.update(timezone=self.zones[r.get_selected()]))
        g.add(tz)
        self.tz_row = tz
        g = self.group(page, "Network")
        self.net_row = Adw.ActionRow(title="Checking the network…")
        self.net_row.set_subtitle_lines(0)
        self.net_icon = glass.icon("network-wireless-symbolic", 20, "dg-row-icon")
        self.net_row.add_prefix(self.net_icon)
        hint(self.net_row, "Whether this computer is online. The install only needs it for something that isn't on this USB stick.")
        self.net_chip = Gtk.Label(label="CHECKING", valign=Gtk.Align.CENTER)
        self.net_chip.add_css_class("dg-chip")
        self.net_chip.add_css_class("quiet")
        hint(self.net_chip, "Online or not, checked just now")
        self.net_row.add_suffix(self.net_chip)
        wifi = hint(Gtk.Button(label="Connect to Wi-Fi…", valign=Gtk.Align.CENTER),
                    "Open the network settings to join a Wi-Fi network.")
        wifi.connect("clicked", lambda *_: self.open_wifi())
        self.net_row.add_suffix(wifi)
        g.add(self.net_row)
        self.refresh_network()


    def on_language(self, row, _p):
        loc = common.LANGUAGES[row.get_selected()][0]
        if loc != self.a["locale"]:
            self.a["locale"] = loc
            self.a["timezone"] = common.tz_guess(loc)
            if self.a["timezone"] in self.zones and self.step == "welcome":
                self.tz_row.set_selected(self.zones.index(self.a["timezone"]))

    def refresh_network(self):
        import threading

        def shown(on, dl):
            self.net_row.set_title("Connected" if on else "Not connected")
            self.net_row.set_subtitle(common.network_words(dl, on))
            self.net_icon.set_from_icon_name("network-wireless-signal-excellent-symbolic" if on else "network-offline-symbolic")
            for cl in ("quiet", "warn"):
                self.net_chip.remove_css_class(cl)
            self.net_chip.set_label("● ONLINE" if on else ("▲ OFFLINE" if dl else "○ OFFLINE"))
            if not on:
                self.net_chip.add_css_class("warn" if dl else "quiet")
            return False

        def work():
            ed = common.edition(self.a["edition"])
            on, dl = common.online(), common.needs_download(ed)
            GLib.idle_add(shown, on, dl)
        threading.Thread(target=work, daemon=True).start()


    def open_wifi(self):
        for argv in (["bromigos", "settings", "network"], ["nm-connection-editor"], ["kitty", "-e", "nmtui"]):
            try:
                GLib.spawn_async(argv, flags=GLib.SpawnFlags.SEARCH_PATH)
                break
            except GLib.Error:
                continue
        GLib.timeout_add_seconds(8, lambda: (self.refresh_network(), False)[1])

    def build_checks(self, page):
        self.heading(page, "checks")
        look = {"battery": "battery-caution-symbolic", "ram": "dialog-warning-symbolic", "secureboot": "security-low-symbolic",
                "gpu": "video-display-symbolic", "firmware": "computer-symbolic"}
        for c in self.a.get("checks") or []:
            card = Gtk.Box(spacing=16)
            card.add_css_class("dg-check-card")
            ic = look.get(c["id"], "drive-harddisk-symbolic" if c["id"].startswith("disk-") else "dialog-warning-symbolic")
            im = glass.icon(ic, 30, "dg-check-icon")
            im.set_valign(Gtk.Align.START)
            card.append(im)
            col = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6, hexpand=True)
            head = Gtk.Box(spacing=10)
            title = label(c["title"], ("dg-check-title",))
            title.set_hexpand(True)
            head.append(title)
            chip = Gtk.Label(label="WORTH KNOWING", valign=Gtk.Align.CENTER, halign=Gtk.Align.END)
            chip.add_css_class("dg-chip")
            chip.add_css_class("warn")
            hint(chip, "Not a problem for the install: something to know, and maybe to fix first")
            head.append(chip)
            col.append(head)
            col.append(label(c["what"], ("dg-muted",)))
            if c.get("fix"):
                fx = Gtk.Box(spacing=10)
                k = label("WHAT TO DO", ("dg-check-fix-key",), wrap=False)
                k.set_valign(Gtk.Align.START)
                k.set_margin_top(2)
                fx.append(k)
                fx.append(label(c["fix"], ("dg-check-fix",)))
                col.append(fx)
            card.append(col)
            hint(card, c["what"] + " What to do: " + c["fix"] if c["fix"] else c["what"])
            page.append(card)
        info = self.a.get("checks_info") or []
        if info:
            page.append(glass.section("Also checked"))
            box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
            for c in info:
                row = Gtk.Box(spacing=12)
                row.add_css_class("dg-pass")
                im = glass.icon("object-select-symbolic", 16)
                im.set_valign(Gtk.Align.START)
                im.set_margin_top(2)
                row.append(im)
                col = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2, hexpand=True)
                col.append(label(c["title"]))
                if c.get("what"):
                    col.append(label(c["what"], ("dg-pass-what",)))
                row.append(col)
                hint(row, c["title"] + ": " + (c.get("what") or "fine"))
                box.append(row)
            page.append(box)


    def build_edition(self, page):
        self.heading(page, "edition")
        row = Gtk.Box(spacing=18, homogeneous=True)
        row.update_property([Gtk.AccessibleProperty.LABEL], ["What kind of computer is this"])
        first = None
        look = {"desktop": ("kind-desktop.jpg", "video-display-symbolic"), "server": ("kind-server.jpg", "network-server-symbolic")}
        for e in self.eds:
            pic, ic = look.get(e["id"], ("kind-desktop.jpg", "computer-symbolic"))
            lines = [e.get("summary", ""), e.get("hint", "")]
            if common.needs_download(e):
                lines.append(common.download_words(e))
            card = glass.holo_card(pic, ic, e["title"], [x for x in lines if x], e["id"] == self.a["edition"], first,
                                   width=300 if getattr(self, "compact", False) else 420)
            first = first or card
            card.connect("toggled", lambda b, eid=e["id"]: b.get_active() and self.a.update(edition=eid))
            hint(card, f"Install {e['title']}: {e.get('summary', '')}")
            row.append(card)
        page.append(row)

    def build_keyboard(self, page):
        self.heading(page, "keyboard")
        if not self.a.get("keyboard_chosen"):
            self.a["keyboard"] = common.LANG_KEYBOARD.get(self.a["locale"], "us")
        g = self.group(page, "Layout")
        model = Gtk.StringList.new([k[1] for k in common.KEYBOARDS])
        row = Adw.ComboRow(title="Keyboard layout", model=model, enable_search=True)
        row.add_prefix(glass.icon("input-keyboard-symbolic", 20, "dg-row-icon"))
        row.set_expression(Gtk.PropertyExpression.new(Gtk.StringObject, None, "string"))
        row.set_selected([k[0] for k in common.KEYBOARDS].index(self.a["keyboard"]))
        hint(row, "Your keyboard's layout. It changes at once, so you can try it below.")
        compact = getattr(self, "compact", False) or self.screen_h() < 700
        self.kbd = glass.KeyboardHolo(self.c, still=self.reduced, height=130 if compact else 176)
        hint(self.kbd, "Your keyboard as this layout reads it: each key shows what it types, and lights when you press it.")

        def chosen(r, _p):
            self.a["keyboard"] = common.KEYBOARDS[r.get_selected()][0]
            self.a["keyboard_chosen"] = True
            backend.keyboard_live(self.a["keyboard"], "wayland")
            GLib.timeout_add(400, lambda: (self.kbd.read_layout(), False)[1])     # once the session has it
        row.connect("notify::selected", chosen)
        g.add(row)
        g2 = self.group(page, "Try it")
        test = Adw.EntryRow(title="Type a few letters, numbers and symbols here")
        test.add_prefix(glass.icon("document-edit-symbolic", 20, "dg-row-icon"))
        hint(test, "A box to try the layout in: what you type here isn't kept.")
        keys = Gtk.EventControllerKey(propagation_phase=Gtk.PropagationPhase.CAPTURE)
        keys.connect("key-pressed", lambda c_, kv, code, st: (self.kbd.press(code, kv), False)[1])
        test.add_controller(keys)
        g2.add(test)
        self.kbd_test = test
        holo = Gtk.Box()
        holo.add_css_class("dg-panel")
        self.kbd.set_margin_top(12)
        self.kbd.set_margin_bottom(12)
        self.kbd.set_margin_start(12)
        self.kbd.set_margin_end(12)
        holo.append(self.kbd)
        page.append(holo)


    def build_disk(self, page):
        self.heading(page, "disk")
        if self.probe is None:
            sp = Gtk.Spinner(spinning=not self.reduced, halign=Gtk.Align.START)
            page.append(sp)
            page.append(label("Looking at the disks… (this takes a few seconds)", ("bi-intro",)))
            return
        if self.probe.get("error"):
            page.append(label(self.probe["error"], ("bi-danger",)))
            page.append(label("Restart the computer and start the installer again. If it happens again, the disk may be failing."))
            return
        usable = [d for d in self.probe["disks"] if not d["medium"]]
        if not usable:
            page.append(label("No disk found to install on.", ("bi-danger",)))
            page.append(label("Check that the disk is connected (and, in the computer's settings, that it's switched on; some "
                              "laptops need the SATA mode set to AHCI instead of RAID). Then restart."))
            return
        if self.a["disk"] not in [d["path"] for d in usable]:
            self.a["disk"] = usable[0]["path"]
            self.a["mode"] = None
        g = self.group(page, "Disk", "The disks in this computer")
        first = Gtk.CheckButton()          # a hidden anchor: a lone choice still draws as a radio
        for d in self.probe["disks"]:
            title = f"{d['model']}  ·  {d['size_text']}"
            row = Adw.ActionRow(title=GLib.markup_escape_text(title),
                                subtitle=GLib.markup_escape_text(d["summary"] + (f" · {d['kind']}" if d["kind"] else "")))
            chk = Gtk.CheckButton(active=d["path"] == self.a["disk"], valign=Gtk.Align.CENTER, sensitive=not d["medium"])
            if first:
                chk.set_group(first)
            first = first or chk
            chk.connect("toggled", lambda b, p=d["path"]: b.get_active() and self.pick_disk(p))
            row.add_prefix(chk)
            row.add_prefix(glass.icon(glass.drive_icon(d), 28, "dg-card-icon"))
            row.set_activatable_widget(chk)
            row.set_sensitive(not d["medium"])
            what = "; ".join(p["what"] for p in d["partitions"]) or "empty"
            hint(row, d["options"]["erase"]["why"] if d["medium"] else f"{d['path']}: {what}")
            hint(chk, f"Install on {d['model']}")
            if d["medium"]:
                badge = ("THIS STICK", "")
            elif (d.get("health") or {}).get("state") == "failing":
                badge = ("▲ FAILING", "danger")
            elif (d.get("health") or {}).get("state") == "ok" or d.get("health") is None:
                badge = ("● HEALTHY", "")
            else:
                badge = ("? HEALTH UNKNOWN", "warn")
            b = Gtk.Label(label=badge[0], valign=Gtk.Align.CENTER)
            b.add_css_class("dg-badge")
            if badge[1]:
                b.add_css_class(badge[1])
            hint(b, (d.get("health") or {}).get("why") or ("The disk reports no problems." if badge[0] == "● HEALTHY" else
                                                            "The USB stick bromigOS started from" if d["medium"] else
                                                            "The disk didn't say how healthy it is."))
            row.add_suffix(b)
            g.add(row)
        self.detail = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=14)
        page.append(self.detail)
        self.fill_disk_detail()

    def pick_disk(self, path):
        if path != self.a["disk"]:
            self.a["disk"] = path
            self.a["mode"] = None
            self.a["failing_ok"] = False
            self.fill_disk_detail()

    def fill_disk_detail(self):
        box = self.detail
        while (c := box.get_first_child()):
            box.remove(c)
        d = self.disk()
        if not d:
            return
        self.guide.line.set_label(self.vector_line("disk"))
        if self.step == "disk":
            self.speak_step()                # a way picked: his line for it (erase's warning, alongside's)
        if (d.get("health") or {}).get("state") == "failing":
            g = self.group(box, "This disk may be failing", d["health"]["why"])
            sw = Adw.SwitchRow(title="Install on it anyway", subtitle="Only if you've copied off what you need: it may stop working.")
            sw.set_active(bool(self.a.get("failing_ok")))
            sw.connect("notify::active", lambda r, _p: self.a.update(failing_ok=r.get_active()))
            hint(sw, "The disk says it's failing. Turn this on to install on it all the same.")
            g.add(sw)
        al, er = d["options"]["alongside"], d["options"]["erase"]
        ri = d["options"].get("reinstall", {})
        if self.a["mode"] is None:
            self.a["mode"] = "reinstall" if ri.get("ok") else ("alongside" if al.get("ok") else ("erase" if er.get("ok") else None))
        box.append(label("HOW", ("bi-rail-title",)))
        cards = Gtk.Box(spacing=14, homogeneous=True)
        first = None
        choices = ([("reinstall", ri.get("label", ""), ri, "view-refresh-symbolic")] if ri.get("ok") else []) + \
            [("alongside", al["label"], al, "view-dual-symbolic"), ("erase", "Erase the whole disk", er, "user-trash-symbolic")]
        for mode, title, opt, ic in choices:
            if mode == "reinstall":
                sub = ri["words"]
            elif mode == "alongside":
                sub = (f"Keep {al.get('name') or 'what is there'} and its files. At every start, choose which one to use."
                       if al.get("ok") else al["why"])
            else:
                sub = (f"Delete everything on it ({er.get('loses')}) and give it all to bromigOS." if er.get("ok") else er["why"])
            card = glass.holo_card(None, ic, title, [sub], self.a["mode"] == mode, first, width=260)
            first = first or card
            card.set_sensitive(bool(opt.get("ok")))
            if mode == "erase" and d["partitions"]:
                card.add_css_class("dg-danger")
            card.connect("toggled", lambda b, m=mode: b.get_active() and self.pick_mode(m))
            hint(card, sub)
            cards.append(card)
        box.append(cards)
        g = Adw.PreferencesGroup()
        box.append(g)
        self.disk_map_ui(box, d, al, er)
        if not al.get("ok") and al.get("code") != "empty":
            row = Adw.ActionRow(title="What to do to install alongside", subtitle=GLib.markup_escape_text(al["fix"]))
            row.set_subtitle_lines(0)
            row.add_css_class("bromigos-note")
            row.add_prefix(Gtk.Image.new_from_icon_name("dialog-information-symbolic"))
            hint(row, al["why"] + " " + al["fix"])
            g.add(row)
        if self.a["mode"] == "reinstall" and ri.get("ok"):
            if ri.get("encrypted"):
                g2 = self.group(box, "Unlock the disk")
                self.old_pp = Adw.PasswordEntryRow(title="The disk's passphrase (the one you type at start)")
                self.old_pp.set_text(self.a.get("old_passphrase", ""))
                hint(self.old_pp, "The passphrase that unlocks this disk now. It stays the disk's passphrase.")
                g2.add(self.old_pp)
            if ri.get("users") and not self.a.get("user"):
                u = ri["users"][0]
                self.a.update(user=u["name"], full_name=u["gecos"].split(",")[0], user_edited=True)
        if self.a["mode"] == "alongside" and al.get("ok") and al.get("warn"):
            box.append(label(al["warn"], ("bi-warn",)))
        self.advanced_ui(box)

    def advanced_ui(self, box):
        """Advanced, folded away: the file system, the kernel, zram, the boot loader, and
        archinstall's own menu for partitioning it yourself."""
        adv = self.a.setdefault("advanced", {"fs": "btrfs", "kernel": "linux", "zram": True})
        g = Adw.PreferencesGroup()
        ex = Adw.ExpanderRow(title="Advanced", subtitle=GLib.markup_escape_text(common.ADVANCED_WORDS))
        ex.set_subtitle_lines(0)
        hint(ex, "Options for people who know what they want. Nothing here is needed.")
        for key, title, choices, tip in (("fs", "File system", common.FILESYSTEMS,
                                          "The root's file system. btrfs keeps snapshots you can go back to from the boot menu."),
                                         ("kernel", "Kernel", common.KERNELS, "Which Linux kernel. Arch's own suits nearly everyone.")):
            row = Adw.ComboRow(title=title, model=Gtk.StringList.new([w for _, w in choices]))
            row.set_selected([k for k, _ in choices].index(adv.get(key, choices[0][0])))
            row.connect("notify::selected", lambda r, _p, k=key, ch=choices: adv.__setitem__(k, ch[r.get_selected()][0]))
            hint(row, tip)
            ex.add_row(row)
        z = Adw.SwitchRow(title="Compressed swap in memory (zram)")
        z.set_active(adv.get("zram", True))
        z.connect("notify::active", lambda r, _p: adv.__setitem__("zram", r.get_active()))
        hint(z, "More room when memory runs short, without a swap partition.")
        ex.add_row(z)
        bl = Adw.ActionRow(title="Boot loader: GRUB", subtitle=GLib.markup_escape_text(common.BOOTLOADER_WORDS))
        bl.set_subtitle_lines(0)
        hint(bl, common.BOOTLOADER_WORDS)
        ex.add_row(bl)
        pm = Adw.ActionRow(title="Partition it myself", subtitle="archinstall's own menu, filled in with what's chosen so far.")
        b = hint(Gtk.Button(label="Open…", valign=Gtk.Align.CENTER),
                 "Change the partitions, the boot loader or anything else in archinstall's menu, then it installs.")
        b.connect("clicked", lambda *_: self.partition_myself())
        pm.add_suffix(b)
        hint(pm, "archinstall's own menu (in a terminal window): for custom partitioning")
        ex.add_row(pm)
        g.add(ex)
        box.append(g)
        self.adv_row = ex

    def partition_myself(self):
        if not self.a.get("user") or not self.a.get("password"):
            self.err.set_label("▲ Fill in About you first (your user name and password), then come back to this.")
            return
        path = backend.answers_file(common.backend_answers(self.a, self.disk()))
        subprocess_argv = ["kitty", "--title", "archinstall: partition it yourself", "sudo", backend.INSTALL,
                           "--answers", path, "--menu", "--no-reboot"]
        try:
            GLib.spawn_async(subprocess_argv, flags=GLib.SpawnFlags.SEARCH_PATH)
        except GLib.Error as e:
            self.err.set_label("▲ archinstall's menu didn't open: " + str(e))

    def pick_mode(self, mode):
        if mode != self.a["mode"]:
            self.a["mode"] = mode
            GLib.idle_add(lambda: (self.fill_disk_detail(), False)[1])

    def disk_map_ui(self, box, d, al, er):
        """The disk as a map of its partitions: the alongside divider on it, or erase's bar
        turned all bromigOS; the sizes above it, a legend and each side's minimum below."""
        mode = self.a["mode"]
        card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        card.add_css_class("bi-card")
        top = Gtk.Box()
        them = label("", ("bi-split", "them"), wrap=False)
        us = label("", ("bi-split", "us"), wrap=False, xalign=1.0)
        us.set_hexpand(True)
        top.append(them)
        top.append(us)
        card.append(top)
        shrink = mode == "alongside" and al.get("ok") and al.get("mode") == "shrink"
        value = None
        if shrink:
            total = al["part_size"] + al["free_after"]
            v = int(self.a.get("bromigos_bytes") or al["default"])
            v = max(al["min"], min(al["max"], v))
            self.a["bromigos_bytes"] = v
            value = (total - v) / GiB
        m = glass.DiskMap(d, self.c, mode if mode in ("alongside", "erase") else "view", al if mode == "alongside" else None,
                          value, still=self.reduced)
        card.append(m)
        if shrink:
            hint(m, f"The split: drag the handle, or use ← and → (Page Up and Page Down by 10 GB, Home and End to the "
                    f"limits). ← gives bromigOS more room, → gives {al['who']} more. The striped ends are what each needs.")
            lims = Gtk.Box(spacing=12)
            left = label(f"◂ {al['who']} needs {plain_size(al['keep_min'])}: what it uses now and room to grow",
                         ("bi-limit", "them"), xalign=0.0)
            right = label(f"bromigOS needs {plain_size(al['min'])} ▸", ("bi-limit", "us"), wrap=False, xalign=1.0)
            left.set_hexpand(True)
            lims.append(left)
            lims.append(right)
            card.append(lims)

            def moved(value):
                self.a["bromigos_bytes"] = max(al["min"], min(al["max"], total - int(round(value)) * GiB))
                them.set_label(f"{al['who'].upper()}  {plain_size(total - self.a['bromigos_bytes'])}")
                us.set_label(f"BROMIGOS  {plain_size(self.a['bromigos_bytes'])}")
            m.on_change = moved
            moved(m.value)
            self.split_bar = m
        elif mode == "erase":
            them.set_label(f"{d['model'].upper()}  {d['size_text']}")
            us.set_label(f"ALL BROMIGOS  {d['size_text']}")
            us.add_css_class("us")
        elif mode == "alongside" and al.get("ok"):
            them.set_label(f"{(al.get('name') or 'WHAT IS THERE').upper()}  UNTOUCHED")
            us.set_label(f"BROMIGOS  {al.get('size_text', '')}")
        else:
            them.set_label(f"{d['model'].upper()}  {d['size_text']}")
        legend = Gtk.FlowBox(selection_mode=Gtk.SelectionMode.NONE, max_children_per_line=4, column_spacing=18, row_spacing=4)
        icons = {"efi": "media-flash-symbolic", "msr": "emblem-system-symbolic", "windows": "computer-symbolic",
                 "recovery": "view-refresh-symbolic", "linux": "drive-harddisk-symbolic", "other": "drive-harddisk-symbolic",
                 "free": "list-add-symbolic"}
        if mode == "erase":
            legend.append(glass.legend_item("dialog-warning-symbolic",
                                            f"Deleted: {er.get('loses') or 'everything on it'}. Copy off anything you want first.",
                                            "danger"))
        else:
            for role, size, words, _p in glass.segments(d):
                legend.append(glass.legend_item(icons.get(role, "drive-harddisk-symbolic"), words if role != "free" else
                                                f"Free space, {plain_size(size)}", "windows" if role == "windows" else ""))
            if shrink or (mode == "alongside" and al.get("ok")):
                legend.append(glass.legend_item("emblem-ok-symbolic" if False else "object-select-symbolic",
                                                "bromigOS, in the room made beside it", "bromigos"))
        card.append(legend)
        if shrink:
            card.append(label(f"{al['who']} is made smaller to make room; its files stay where they are. {plain_size(common_good())} "
                              "or more leaves bromigOS room for apps and games.", ("bi-intro",)))
        box.append(card)

    def split_ui(self, box, al):
        total = al["part_size"] + al["free_after"]
        v = int(self.a.get("bromigos_bytes") or al["default"])
        v = max(al["min"], min(al["max"], v))
        self.a["bromigos_bytes"] = v
        card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        card.add_css_class("bi-card")
        top = Gtk.Box()
        them = label("", ("bi-split", "them"), wrap=False)
        us = label("", ("bi-split", "us"), wrap=False, xalign=1.0)
        us.set_hexpand(True)
        top.append(them)
        top.append(us)
        card.append(top)
        # the bar is the whole partition: the other system's share from the left, bromigOS's
        # from the right, the handle where they meet, each side's minimum marked on it
        lo, hi = (total - al["max"]) / GiB, (total - al["min"]) / GiB
        bar = SplitBar(total / GiB, lo, hi, (total - v) / GiB, al["who"], common.theme()[0])
        hint(bar, f"The split: drag the handle, or use ← and → (Page Up and Page Down by 10 GB, Home and End to the "
                  f"limits). ← gives bromigOS more room, → gives {al['who']} more. The striped ends are what each needs.")
        card.append(bar)
        lims = Gtk.Box(spacing=12)
        left = label(f"◂ {al['who']} needs {plain_size(al['keep_min'])}: what it uses now and room to grow",
                     ("bi-limit", "them"), xalign=0.0)
        right = label(f"bromigOS needs {plain_size(al['min'])} ▸", ("bi-limit", "us"), wrap=False, xalign=1.0)
        left.set_hexpand(True)
        lims.append(left)
        lims.append(right)
        card.append(lims)

        def moved(value):
            self.a["bromigos_bytes"] = max(al["min"], min(al["max"], total - int(round(value)) * GiB))
            them.set_label(f"{al['who'].upper()}  {plain_size(total - self.a['bromigos_bytes'])}")
            us.set_label(f"BROMIGOS  {plain_size(self.a['bromigos_bytes'])}")
        bar.on_change = moved
        moved(bar.value)
        card.append(label(f"{al['who']} is made smaller to make room; its files stay where they are. bromigOS needs at least "
                          f"{plain_size(al['min'])}; {plain_size(common_good())} or more leaves room for apps and games.", ("bi-intro",)))
        self.split_bar = bar
        box.append(card)

    def build_bitlocker(self, page):
        self.heading(page, "bitlocker")
        wide = self.content_width() >= 900           # the key beside the steps, or above them
        body = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL if wide else Gtk.Orientation.VERTICAL, spacing=22 if wide else 14)
        key = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8, valign=Gtk.Align.START,
                      halign=Gtk.Align.FILL if wide else Gtk.Align.START)
        key.add_css_class("dg-panel")
        inner = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8, margin_top=16, margin_bottom=16, margin_start=18,
                        margin_end=18)
        top = Gtk.Box(spacing=12)
        top.append(glass.icon("dialog-password-symbolic", 34, "bi-split", "them"))
        tcol = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        tcol.append(label("BITLOCKER RECOVERY KEY", ("bi-split", "them"), wrap=False))
        tcol.append(label("Windows · 48 digits, in eight groups", ("dg-muted",), wrap=False))
        top.append(tcol)
        inner.append(top)
        digits = label("000000-000000-000000-000000\n000000-000000-000000-000000", ("bi-split", "them"), wrap=False)
        digits.set_halign(Gtk.Align.START)
        inner.append(digits)
        key.append(inner)
        hint(key, "What the key looks like: eight groups of six digits. Yours is in Windows, or at aka.ms/myrecoverykey.")
        body.append(key)
        steps = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12, hexpand=True)
        steps.append(glass.section("Where to find it"))
        steps.append(glass.numbered([
            ("computer-symbolic", "In Windows: Settings › Privacy & security › Device encryption › BitLocker drive "
                                  "encryption › Back up your recovery key."),
            ("phone-symbolic", "Or, on another device, sign in at aka.ms/myrecoverykey and find this computer."),
            ("document-edit-symbolic", "Write the 48 digits down, or save them somewhere that isn't this computer."),
        ]))
        body.append(steps)
        page.append(body)
        g = self.group(page, "Before you go on")
        sw = Adw.SwitchRow(title="I've saved the BitLocker recovery key", subtitle="Somewhere that isn't this computer.")
        sw.add_prefix(glass.icon("object-select-symbolic", 20, "dg-row-icon"))
        sw.set_active(bool(self.a.get("bitlocker_saved")))
        sw.connect("notify::active", lambda r, _p: self.a.update(bitlocker_saved=r.get_active()))
        hint(sw, "Turn this on once the key is saved. bromigOS never changes Windows' BitLocker drive.")
        g.add(sw)


    def build_user(self, page):
        """About you, as an operator ID card (the lore's dossier): the portrait and the name it
        reads, then the fields, each with a ✓ or a ▲ as you type."""
        self.heading(page, "user")
        card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        card.add_css_class("dg-dossier")
        head = Gtk.Box(spacing=8)
        head.add_css_class("dg-dossier-head")
        head.append(Gtk.Label(label=glass.DOSSIER_HEAD, xalign=0, hexpand=True))
        serial = Gtk.Label(label="BROMIGOS // NEW RECORD")
        serial.add_css_class("dg-dossier-serial")
        head.append(serial)
        hint(head, "Your ID on this computer: who signs in, and what the computer is called")
        card.append(head)
        wide = self.content_width() >= 760
        body = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL if wide else Gtk.Orientation.VERTICAL, spacing=22,
                       margin_top=18, margin_bottom=18, margin_start=18, margin_end=18)
        who = Gtk.Box(orientation=Gtk.Orientation.VERTICAL if wide else Gtk.Orientation.HORIZONTAL, spacing=12)
        who.set_size_request(200 if wide else -1, -1)
        self.portrait = glass.Portrait(self.c, 128 if wide else 92)
        self.portrait.set_halign(Gtk.Align.START)
        who.append(self.portrait)
        ident = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4, hexpand=not wide)
        ident.append(label("NAME", ("dg-dossier-key",)))
        self.id_name = label("", ("dg-dossier-name",))
        ident.append(self.id_name)
        ident.append(label("SIGNS IN AS", ("dg-dossier-key",)))
        self.id_handle = label("", ("dg-dossier-handle",))
        ident.append(self.id_handle)
        self.id_chip = Gtk.Label(label="", halign=Gtk.Align.START, margin_top=6)
        self.id_chip.add_css_class("dg-chip")
        ident.append(self.id_chip)
        who.append(ident)
        body.append(who)
        fields = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12, hexpand=True)
        g = Adw.PreferencesGroup()
        self.f, self.marks = {}, {}
        for key, title, ic, tip, pw in (
                ("full_name", "Your name (optional)", "avatar-default-symbolic", "Your name, as the login screen shows it.", False),
                ("user", "User name", "user-info-symbolic", "What you type to sign in: small letters and digits, no spaces.", False),
                ("password", "Password", "dialog-password-symbolic",
                 "The password for signing in and for changes that need your permission.", True),
                ("password2", "Password again", "dialog-password-symbolic",
                 "The same password once more, to be sure it's typed right.", True),
                ("hostname", "Computer's name", "computer-symbolic",
                 "How this computer shows up to other devices on your network.", False)):
            row = (Adw.PasswordEntryRow if pw else Adw.EntryRow)(title=title)
            row.add_prefix(glass.icon(ic, 18, "dg-row-icon"))
            row.set_text(self.a.get(key, "") or "")
            mark = glass.valid_mark()
            row.add_suffix(mark)
            hint(row, tip)
            g.add(row)
            self.f[key], self.marks[key] = row, mark
        fields.append(g)
        meter, self.meter_set = glass.strength_meter()
        hint(meter, "How hard the password would be to guess")
        fields.append(meter)
        body.append(fields)
        card.append(body)
        page.append(card)
        self.f["full_name"].connect("changed", self.name_typed)
        self.f["user"].connect("changed", self.user_typed)
        self.f["hostname"].connect("changed", self.host_typed)
        self.f["password"].connect("changed", self.pw_typed)
        for row in self.f.values():
            row.connect("changed", lambda *_: self.validate_user())
        self.pw_typed(self.f["password"])
        self.validate_user()


    def name_typed(self, row):
        if not self.a.get("user_edited"):
            self._auto = True
            self.f["user"].set_text(common.suggest_username(row.get_text()))
            self._auto = False

    def user_typed(self, row):
        if not getattr(self, "_auto", False):
            self.a["user_edited"] = True
        if not self.a.get("host_edited"):
            self._auto = True
            self.f["hostname"].set_text(common.suggest_hostname(row.get_text(), self.a["edition"]))
            self._auto = False

    def host_typed(self, row):
        if not getattr(self, "_auto", False):
            self.a["host_edited"] = True

    def pw_typed(self, row):
        text = row.get_text()
        if text:
            word, advice = common.strength(text)
            self.meter_set(word, advice)
        else:
            self.meter_set("", "Longer is stronger: three or four unrelated words make a good one.")


    def build_encryption(self, page):
        self.heading(page, "encryption")
        body = Gtk.Box(spacing=28)
        left = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8, valign=Gtk.Align.START)
        size = 150 if (getattr(self, "compact", False) or self.screen_h() < 700) else 190
        self.lock = glass.HoloLock(self.c, size, still=self.reduced)
        hint(self.lock, "The disk's lock: shut while encryption is on")
        left.append(self.lock)
        self.lock_chip = Gtk.Label(label="", halign=Gtk.Align.CENTER)
        self.lock_chip.add_css_class("dg-chip")
        left.append(self.lock_chip)
        body.append(left)
        right = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=14, hexpand=True)
        right.append(label(common.ENCRYPT_WORDS, ("dg-muted",)))
        g = Adw.PreferencesGroup()
        sw = Adw.SwitchRow(title="Encrypt the disk", subtitle="Recommended")
        sw.add_prefix(glass.icon("system-lock-screen-symbolic", 20, "dg-row-icon"))
        sw.set_active(self.a["encrypt"])
        hint(sw, "On: the disk is locked until its passphrase is typed at start. Off: no passphrase.")
        g.add(sw)
        sep = Adw.SwitchRow(title="Use a different passphrase from my password",
                            subtitle="Off: your password unlocks the disk too, one less thing to remember.")
        sep.add_prefix(glass.icon("dialog-password-symbolic", 20, "dg-row-icon"))
        sep.set_active(bool(self.a.get("separate_passphrase")))
        hint(sep, "On: the disk gets a passphrase of its own, typed at every start.")
        g.add(sep)
        pp = Adw.PasswordEntryRow(title="Disk passphrase")
        pp2 = Adw.PasswordEntryRow(title="Passphrase again")
        marks = (glass.valid_mark(), glass.valid_mark())
        for r, m, tip in ((pp, marks[0], "The passphrase you'll type at every start."), (pp2, marks[1], "The same passphrase once more.")):
            r.add_prefix(glass.icon("dialog-password-symbolic", 18, "dg-row-icon"))
            r.add_suffix(m)
            hint(r, tip)
            g.add(r)
        right.append(g)
        meter, set_meter = glass.strength_meter()
        hint(meter, "How hard the passphrase would be to guess")
        right.append(meter)
        body.append(right)
        page.append(body)
        self.pp = (pp, pp2)

        def typed(*_):
            a, b = pp.get_text(), pp2.get_text()
            set_meter(*(common.strength(a) if a else ("", "A long phrase you'll remember is best: you type it at every start.")))
            glass.set_valid(marks[0], common.check_password(a, a, "passphrase"), shown=bool(a))
            glass.set_valid(marks[1], common.check_password(a, b, "passphrase"), shown=bool(b))
        pp.connect("changed", typed)
        pp2.connect("changed", typed)
        typed()

        def sync(*_):
            on = sw.get_active()
            self.a["encrypt"] = on
            self.a["separate_passphrase"] = sep.get_active()
            sep.set_sensitive(on)
            own = on and sep.get_active()
            for r in (pp, pp2):
                r.set_visible(own)
            meter.set_visible(own)
            self.lock.set_locked(on)
            self.lock_chip.set_label("● LOCKED" if on else "○ NOT LOCKED")
            (self.lock_chip.remove_css_class if on else self.lock_chip.add_css_class)("warn")
            hint(self.lock_chip, "The disk will be encrypted" if on else "The disk won't be encrypted: anyone with it can read it")
        sw.connect("notify::active", sync)
        sep.connect("notify::active", sync)
        sync()


    def build_ssh(self, page):
        self.heading(page, "ssh")
        if "found_keys" not in self.a:
            self.a["found_keys"] = common.stick_keys()
            self.a["ssh_keys"] = [k for _, k in self.a["found_keys"]]
        g = self.group(page, "SSH", common.SSH_WORDS)
        sw = Adw.SwitchRow(title="Turn on SSH")
        sw.set_active(bool(self.a.get("ssh")))
        hint(sw, "On: sign in from other computers on your network. Off: only at this computer.")
        g.add(sw)
        how = Adw.ComboRow(title="How to sign in", model=Gtk.StringList.new(["Keys only (recommended)", "Keys or my password"]))
        how.set_selected(1 if self.a.get("ssh_password") else 0)
        how.set_subtitle(GLib.markup_escape_text(common.SSH_KEY_WORDS))
        how.set_subtitle_lines(0)
        hint(how, common.SSH_KEY_WORDS)
        how.connect("notify::selected", lambda r, _p: self.a.update(ssh_password=r.get_selected() == 1))
        g.add(how)
        keyrows = []
        for name, key in self.a["found_keys"]:
            kr = Adw.SwitchRow(title=GLib.markup_escape_text(name), subtitle=GLib.markup_escape_text(key[:60] + "…"))
            kr.set_active(key in self.a["ssh_keys"])
            hint(kr, "A key found in the USB stick's fieldkit folder: on lets whoever holds its private half sign in as you.")
            kr.connect("notify::active", lambda r, _p, k=key: self.a.update(
                ssh_keys=[x for x in self.a["ssh_keys"] if x != k] + ([k] if r.get_active() else [])))
            g.add(kr)
            keyrows.append(kr)
        if not self.a["found_keys"]:
            none = Adw.ActionRow(title="No key in the USB stick's fieldkit folder",
                                 subtitle="Copy your key's .pub file there and press Look again, or paste it below.")
            none.set_subtitle_lines(0)
            again = hint(Gtk.Button(label="Look again", valign=Gtk.Align.CENTER), "Read the USB stick's fieldkit folder for keys again.")
            again.connect("clicked", lambda *_: (self.a.pop("found_keys", None), self.show_step("ssh")))
            none.add_suffix(again)
            hint(none, "Keys are read from the fieldkit folder on the USB stick.")
            g.add(none)
            keyrows.append(none)
        paste = Adw.EntryRow(title="Paste a public key (optional)")
        hint(paste, "One line from your other computer's .pub file, for example ~/.ssh/id_ed25519.pub.")
        g.add(paste)
        self.paste = paste
        keyrows += [how, paste]

        def sync(*_):
            self.a["ssh"] = sw.get_active()
            for r in keyrows:
                r.set_visible(sw.get_active())
        sw.connect("notify::active", sync)
        sync()
        g2 = self.group(page, "Protection")
        for key, title, words in (("firewall", "Firewall", common.FIREWALL_WORDS), ("auto_updates", "Automatic updates", common.AUTO_UPDATE_WORDS)):
            r = Adw.SwitchRow(title=title, subtitle=GLib.markup_escape_text(words.split(": ", 1)[1]))
            r.set_subtitle_lines(0)
            r.set_active(bool(self.a.get(key, True)))
            r.connect("notify::active", lambda rr, _p, k=key: self.a.update({k: rr.get_active()}))
            hint(r, words)
            g2.add(r)

    def build_summary(self, page):
        self.editing = None
        self.heading(page, "summary")
        rows, warn = common.summary(self.a, self.disk())
        brief = self.brief_rows(rows)
        page.append(self.briefing_ui(brief, edit=True))
        if warn:
            n = label(("▲ " if self.a["mode"] != "erase" else "▲ ") + warn, ("dg-note",) + (("danger",) if self.a["mode"] == "erase" else ()))
            page.append(n)
        exp = Gtk.Expander(label="Show what will run")
        hint(exp, "The exact commands, and the configuration archinstall gets (passwords hidden).")
        buf = Gtk.TextBuffer()
        buf.set_text("…")
        tv = Gtk.TextView(buffer=buf, editable=False, monospace=True, wrap_mode=Gtk.WrapMode.CHAR)
        sw = Gtk.ScrolledWindow(min_content_height=320)
        sw.set_child(tv)
        exp.set_child(sw)
        self.what_buf = buf

        def opened(e, _p):
            if not e.get_expanded():
                return
            import threading

            def work():
                cfg, creds, lines = backend.preview(common.backend_answers(self.a, self.disk()))
                text = "\n".join(lines) + ("\n\narchinstall's configuration (config.json):\n" + cfg +
                                            "\n\ncredentials (creds.json, secrets hidden):\n" + creds if cfg else "")
                GLib.idle_add(lambda: (buf.set_text(text), False)[1])
            threading.Thread(target=work, daemon=True).start()
        exp.connect("notify::expanded", opened)
        page.append(exp)
        self.what_exp = exp


    def build_install(self, page):
        self.heading(page, "install")
        hero = Gtk.Box(spacing=28)
        left = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        size = 220 if getattr(self, "compact", False) else 300
        self.ring = glass.EmblemRing(self.c, size, still=self.reduced)
        hint(self.ring, "How far the install has got: the ring fills as it goes.")
        left.append(self.ring)
        self.pct = label("0 %", ("dg-pct",), wrap=False, xalign=0.5)
        left.append(self.pct)
        hero.append(left)
        right = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=14, hexpand=True)
        self.status = label("Starting…", ("bi-status",))
        self.status.update_property([Gtk.AccessibleProperty.LABEL], ["What the install is doing"])
        right.append(self.status)
        self.phase_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        right.append(self.phase_box)
        self._phases("Starting…", 0)
        right.append(glass.Slideshow(still=self.reduced, width=380 if not getattr(self, "compact", False) else 300))
        hero.append(right)
        page.append(hero)
        self.bar = Gtk.ProgressBar()             # for screen readers and the harness: the same number
        self.bar.update_property([Gtk.AccessibleProperty.LABEL], ["Install progress"])
        self.bar.set_visible(False)
        page.append(self.bar)
        exp = Gtk.Expander(label="Details")
        hint(exp, "Every step the install takes, as it happens.")
        self.logbuf = Gtk.TextBuffer()
        tv = Gtk.TextView(buffer=self.logbuf, editable=False, monospace=True, wrap_mode=Gtk.WrapMode.CHAR)
        sw = Gtk.ScrolledWindow(min_content_height=260)
        sw.set_child(tv)
        self.logview = tv
        exp.set_child(sw)
        page.append(exp)

    def _phases(self, text, pct):
        while (ch := self.phase_box.get_first_child()):
            self.phase_box.remove(ch)
        d = self.disk() or {}
        al = d.get("options", {}).get("alongside", {})
        shrink = self.a.get("mode") == "alongside" and al.get("mode") == "shrink"
        self.phase_box.append(glass.phase_list(self.c, shrink, text, pct))

    def build_done(self, page):
        if self.done is True:
            hero = Gtk.Box(spacing=26)
            size = 140 if self.screen_h() < 700 else 176
            burn = glass.BurnIn(self.c, size, still=self.reduced)
            hint(burn, "bromigOS's emblem: it's on this computer now")
            burn.set_valign(Gtk.Align.CENTER)
            hero.append(burn)
            col = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10, valign=Gtk.Align.CENTER, hexpand=True)
            self.heading(col, "done")
            chip = Gtk.Label(label="● INSTALLED", halign=Gtk.Align.START)
            chip.add_css_class("dg-chip")
            hint(chip, "The install finished without a problem")
            col.append(chip)
            hero.append(col)
            page.append(hero)
            ed = common.edition(self.a["edition"])
            lines = [("system-reboot-symbolic", "Press Restart now."),
                     ("media-removable-symbolic", "When the screen goes dark, take out the USB stick.")]
            sb = common.secureboot_steps(backend.SECUREBOOT_CODE)
            if sb:
                lines.append(("security-high-symbolic", f"At the first start, approve bromigOS on the blue screen with "
                                                        f"the code {sb['code']} (the steps are below)."))
            if self.a["encrypt"]:
                lines.append(("system-lock-screen-symbolic", "At start, type the disk's passphrase" +
                              ("." if self.a.get("separate_passphrase") else " (your password).")))
            if self.a["mode"] == "alongside":
                other = (self.disk() or {}).get("options", {}).get("alongside", {}).get("name") or "the other system"
                lines.append(("view-dual-symbolic", f"The boot menu lets you choose bromigOS or {other} each time."))
            lines.append(("avatar-default-symbolic", "Then sign in at the login screen." if ed.get("desktop", True)
                          else "Then sign in at the text console."))
            page.append(glass.section("What happens next"))
            page.append(glass.numbered(lines))
            if sb:          # beside Restart now, which has the focus: the code is on screen with it
                card = glass.secureboot_card(sb)
                card.set_margin_top(8)
                page.append(card)
            btn = hint(Gtk.Button(label="Restart now", halign=Gtk.Align.START), "Restart the computer into bromigOS.")
            btn.add_css_class("suggested-action")
            btn.add_css_class("bi-big")
            btn.set_margin_top(6)
            btn.connect("clicked", lambda *_: (backend.reboot(), self.get_application().quit()))
            page.append(btn)
            self.set_default_widget(btn)
            GLib.idle_add(btn.grab_focus)
        else:
            hero = Gtk.Box(spacing=24)
            mark = glass.SignalLost(self.c, 120)
            mark.set_valign(Gtk.Align.CENTER)
            hint(mark, "The install stopped before the end")
            hero.append(mark)
            col = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10, valign=Gtk.Align.CENTER, hexpand=True)
            col.append(label("THE INSTALL DIDN'T FINISH", ("bi-heading", "bi-danger")))
            col.append(label("Go back to the summary, change something if you like, and press Install to try again. A "
                             "problem report helps whoever you ask for help.", ("bi-intro",)))
            hero.append(col)
            page.append(hero)
            card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
            card.add_css_class("dg-fail")
            card.append(label("WHAT HAPPENED", ("dg-brief-key",)))
            card.append(label(self.done or "The install stopped."))
            page.append(card)
            row = Gtk.Box(spacing=12)
            rep = hint(Gtk.Button(label="Save a problem report"), "Put the install's logs, a hardware summary and your answers "
                                                                   "(without passwords) on a USB drive, to send when you ask for help.")
            rep.add_css_class("bi-big")
            retry = hint(Gtk.Button(label="Back to the summary"), "Go back, change something if you like, and try again.")
            retry.add_css_class("bi-big")
            retry.add_css_class("suggested-action")
            row.append(retry)
            row.append(rep)
            page.append(row)
            self.report_line = label("", ("bi-intro",), selectable=True)
            page.append(self.report_line)
            retry.connect("clicked", lambda *_: self.show_step("summary"))
            rep.connect("clicked", lambda *_: self.save_report())
            exp = Gtk.Expander(label="Details")
            hint(exp, "Every step the install took, and where it stopped.")
            buf = Gtk.TextBuffer()
            buf.set_text("\n".join(self.lines[-600:]))
            tv = Gtk.TextView(buffer=buf, editable=False, monospace=True, wrap_mode=Gtk.WrapMode.CHAR)
            sw = Gtk.ScrolledWindow(min_content_height=260)
            sw.set_child(tv)
            exp.set_child(sw)
            page.append(exp)
            self.set_default_widget(retry)
            GLib.idle_add(retry.grab_focus)


    def save_report(self):
        self.report_line.set_label("Saving the report…")

        def work():
            path, words = backend.save_report(common.backend_answers(self.a, self.disk()) if self.disk() else None)
            GLib.idle_add(lambda: (self.report_line.set_label(words), False)[1])
        import threading
        threading.Thread(target=work, daemon=True).start()

    # ── moving between steps ────────────────────────────────────────────────────────
    def check(self):
        s = self.step
        if s == "disk":
            d = self.disk()
            if not d:
                return "Choose a disk to install on."
            if self.a["mode"] not in ("alongside", "erase", "reinstall") or not d["options"][self.a["mode"]].get("ok"):
                return "Choose how to install on this disk."
            if self.a["mode"] == "reinstall" and d["options"]["reinstall"].get("encrypted"):
                self.a["old_passphrase"] = self.old_pp.get_text()
                if not self.a["old_passphrase"]:
                    return "Type the disk's passphrase: the one you type when the computer starts."
            if (d.get("health") or {}).get("state") == "failing" and not self.a.get("failing_ok"):
                return "This disk may be failing. Choose another disk, or turn on Install on it anyway."
        elif s == "bitlocker" and not self.a.get("bitlocker_saved"):
            return "Save the BitLocker recovery key first, then turn on I've saved the BitLocker recovery key."
        elif s == "user":
            for k, row in self.f.items():
                self.a[k] = row.get_text() if k.startswith("password") else row.get_text().strip()
            return (common.check_full_name(self.a["full_name"]) or common.check_username(self.a["user"])
                    or common.check_password(self.a["password"], self.a["password2"]) or common.check_hostname(self.a["hostname"]))
        elif s == "encryption" and self.a["encrypt"] and self.a.get("separate_passphrase"):
            self.a["passphrase"] = self.pp[0].get_text()
            return common.check_password(self.a["passphrase"], self.pp[1].get_text(), "passphrase")
        elif s == "ssh" and self.a.get("ssh"):
            pasted = self.paste.get_text().strip()
            if pasted:
                problem = common.check_key(pasted)
                if problem:
                    return problem
                if pasted not in self.a["ssh_keys"]:
                    self.a["ssh_keys"].append(pasted)
            if not self.a.get("ssh_password") and not self.a["ssh_keys"]:
                return ("Keys only needs a key: copy your .pub file into the USB stick's fieldkit folder and press Look again, "
                        "paste it in the box, or choose Keys or my password.")
        elif s == "edition":
            ed = common.edition(self.a["edition"])
            if common.needs_download(ed) and not common.online():
                return common.network_words(True, False)
        return None

    def go_next(self):
        if self.step in ("install", "done"):
            return
        problem = self.check()
        if problem:
            self.err.set_label("▲ " + problem)
            self.err.announce(problem, Gtk.AccessibleAnnouncementPriority.HIGH) if hasattr(self.err, "announce") else None
            return
        if self.step == "summary":
            return self.start_install()
        steps = self.steps()
        if getattr(self, "editing", None):           # from the summary's Edit: straight back, if the steps
            same = tuple(steps) == self.editing      # are still the same ones
            self.editing = None
            if same:
                return self.show_step("summary")
        self.show_step(steps[steps.index(self.step) + 1])

    def go_back(self):
        steps = self.steps()
        if self.voice:
            self.voice.stop()                    # back quiets him: the step before isn't read again
        if self.step in steps and steps.index(self.step) > 0 and self.step not in ("install", "done"):
            self.show_step(steps[steps.index(self.step) - 1], speak=False)

    def start_install(self):
        self.lines = []
        doc = common.backend_answers(self.a, self.disk())
        self.show_step("install")
        self.set_deletable(False)

        def stage(pct, text):
            GLib.idle_add(self._stage, pct, text)

        def line(text):
            self.lines.append(text)
            GLib.idle_add(self._line, text)

        def done(ok, err):
            GLib.idle_add(self._done, ok, err)
        self.running = backend.Install(doc, stage, line, done).start()

    def _stage(self, pct, text):
        self.bar.set_fraction(pct / 100)
        self.bar.set_text(f"{pct} %")
        self.ring.set_pct(pct)
        self.pct.set_label(f"{pct} %")
        self.status.set_label(text)
        self._phases(text, pct)
        lid = "installer.install.nearly" if pct >= 85 else ("installer.install.copying" if pct >= 15 else "installer.install")
        self.guide.line.set_label(caption(lid))
        if pct < 100:
            self.speak_step(lid)
        if self.opts.get("script"):
            print(f"  {pct:3d}%  {text}", flush=True)
        return False

    def _line(self, text):
        end = self.logbuf.get_end_iter()
        self.logbuf.insert(end, text + "\n")
        if self.logbuf.get_line_count() > 4000:
            self.logbuf.delete(self.logbuf.get_start_iter(), self.logbuf.get_iter_at_line(1000)[1])
        return False

    def _done(self, ok, err):
        self.running = None
        self.done = True if ok else err
        self.set_deletable(True)
        self.show_step("done")
        if self.opts.get("script"):
            print("::result " + ("installed" if ok else f"failed {err}"), flush=True)
            GLib.timeout_add_seconds(4, lambda: (self.get_application().quit(), False)[1])
        return False

    # ── the harness's script ────────────────────────────────────────────────────────
    def script_step(self):
        plan = self.opts["script"]
        sid = self.step
        if sid == "disk" and self.probe is None:
            return True                                        # wait for the disks
        if getattr(self, "_scripted", None) == sid:
            return False
        self._scripted = sid
        if sid == "edition":
            self.a["edition"] = plan.get("edition", "desktop")
            self.show_step("edition")
            self._scripted = sid
        elif sid == "disk":
            usable = [d for d in self.probe["disks"]]
            self.pick_disk(usable[plan.get("disk_index", 0)]["path"])
            self.pick_mode(plan["mode"])
            if plan.get("gib") and hasattr(self, "split_bar"):
                total = self.disk()["options"]["alongside"]
                total = total["part_size"] + total["free_after"]
                self.split_bar.set_value((total - plan["gib"] * GiB) / GiB)
        elif sid == "user":
            self.f["full_name"].set_text(plan.get("full_name", "Test Er"))
            self.f["user"].set_text(plan.get("user", "tester"))
            self.f["hostname"].set_text(plan.get("hostname", "bromigos-test"))
            for k in ("password", "password2"):
                self.f[k].set_text(plan.get("password", "tester"))
        elif sid == "encryption":
            self.a["encrypt"] = plan.get("encrypt", True)
            self.show_step("encryption")
            self._scripted = sid
        elif sid == "ssh":
            self.a["ssh"] = plan.get("ssh", True)
            self.a["ssh_password"] = plan.get("ssh_password", False)
            self.show_step("ssh")
            self._scripted = sid
            if plan.get("ssh_key"):
                self.paste.set_text(plan["ssh_key"])
        elif sid == "bitlocker":
            self.a["bitlocker_saved"] = True
        if not common.edition(self.a["edition"]).get("desktop", True) or plan.get("ssh"):
            self.a["ssh"] = plan.get("ssh", True)
        GLib.timeout_add(700, self._script_shown, sid)
        return False

    def _script_shown(self, sid):
        print(f"::page {sid}", flush=True)
        if sid in ("install", "done"):
            return False
        start = time.monotonic()

        def wait():
            if os.path.exists(NEXT_FLAG) or time.monotonic() - start > 20:
                try:
                    os.unlink(NEXT_FLAG)
                except OSError:
                    pass
                if self.step == sid:
                    self.go_next()
                    if self.step == sid:
                        print(f"::stuck {sid} {self.err.get_label()}", flush=True)
                        self.get_application().quit()
                return False
            return True
        GLib.timeout_add(250, wait)
        return False


def common_good():
    from .disks import GOOD_BROMIGOS
    return GOOD_BROMIGOS


class App(Adw.Application):
    def __init__(self, opts):
        super().__init__(application_id="org.bromigos.Installer")
        self.opts = opts

    def do_activate(self):
        win = self.get_active_window() or Window(self, self.opts)
        if self.opts.get("render"):
            GLib.timeout_add(600, render_all, win, self.opts["render"])
        elif not self.opts.get("windowed"):
            win.fullscreen()
        win.present()


def snapshot(win, path):
    w, h = win.get_width(), win.get_height()
    paint = Gtk.WidgetPaintable.new(win)
    snap = Gtk.Snapshot()
    paint.snapshot(snap, w, h)
    node = snap.to_node()
    if node is None:
        return False
    tex = win.get_renderer().render_texture(node, None)
    tex.save_to_png(path)
    return True


def render_all(win, out):
    """Each step, drawn with the fake back end (the recorded disks), to OUT/gui-STEP.png."""
    os.makedirs(out, exist_ok=True)
    plan = [("guide", {}), ("guide-on", {}), ("welcome", {}), ("checks", {}), ("edition", {}), ("keyboard", {}), ("disk", {}), ("disk-erase", {}),
            ("disk-advanced", {}), ("bitlocker", {}), ("user-problems", {}),
            ("user", {"full_name": "Alex Rivera", "password": "correct-horse-battery"}), ("encryption", {}),
            ("encryption-own", {}), ("encryption-off", {}), ("ssh", {}), ("summary", {}), ("summary-what", {}),
            ("install", {}), ("done", {}), ("done-secureboot", {}), ("failed", {}), ("auto", {})]
    win.probe = backend.probe()
    win._probed(win.probe)
    win.a.update(disk=win.probe["disks"][0]["path"], mode=None)
    if not win.a.get("checks"):
        win.a["checks"] = [{"id": "battery", "level": "warn", "title": "Running on battery",
                            "what": "If the battery runs out during the install, the disk is left half done.",
                            "fix": "Plug in the charger before you start."}]
    if not win.a.get("checks_info"):
        win.a["checks_info"] = [{"id": "firmware", "level": "info", "title": "Started the newer way (UEFI)",
                                 "what": "bromigOS installs either way, and its boot menu matches.", "fix": ""}]
    state = {"i": 0}

    def step():
        if state["i"] >= len(plan):
            win.get_application().quit()
            return False
        sid, fill = plan[state["i"]]
        state["i"] += 1
        if sid == "guide-on":                     # the voice guide and high contrast on, as someone chose them
            win.show_step("guide")
            win.voice_switch.set_active(True)
            win.guidance_rows["high_contrast"][1].set_active(True)

            def undo():
                win.guidance_rows["high_contrast"][1].set_active(False)
                return False
            GLib.timeout_add(900, undo)
        elif sid == "disk-erase":
            win.a["mode"] = "erase"
            win.show_step("disk")
            GLib.idle_add(lambda: (win.scroll.get_vadjustment().set_value(400), False)[1])
        elif sid == "disk-advanced":
            win.a["mode"] = "alongside"
            win.show_step("disk")
            win.adv_row.set_expanded(True)
            GLib.idle_add(lambda: (win.scroll.get_vadjustment().set_value(win.scroll.get_vadjustment().get_upper()), False)[1])
        elif sid == "summary-what":
            win.show_step("summary")
            win.what_exp.set_expanded(True)
            GLib.timeout_add(300, lambda: (win.scroll.get_vadjustment().set_value(win.scroll.get_vadjustment().get_upper()), False)[1])
        elif sid == "ssh":
            win.a.update(edition="server", ssh=True)
            win.show_step("ssh")
            win.a.update(edition="desktop")
        elif sid == "keyboard":
            win.show_step("keyboard")
            win.kbd_test.set_text("Hello, bromigOS 42!")
            win.kbd.press(48 + 8, Gdk.KEY_b)                  # the last key typed, lit
        elif sid == "bitlocker":
            win.disk()["bitlocker"] = True                    # the recorded Windows, as if BitLocker were on
            win.a["mode"] = "alongside"
            win.show_step("bitlocker")
            win.disk()["bitlocker"] = False
        elif sid == "user-problems":
            win.show_step("user")
            for k, v in (("full_name", "Alex Rivera"), ("user", "Alex R"), ("password", "hunter2"), ("password2", "hunter3")):
                win.f[k].set_text(v)
            win.a.update(user_edited=False, host_edited=False)
        elif sid == "encryption-own":
            win.a.update(encrypt=True, separate_passphrase=True)
            win.show_step("encryption")
            win.pp[0].set_text("lantern-orbit-velvet-42")
            win.pp[1].set_text("lantern-orbit-velvet-42")
        elif sid == "encryption-off":
            win.a.update(encrypt=False, separate_passphrase=False)
            win.show_step("encryption")
            win.a.update(encrypt=True)
        elif sid == "auto":
            win.answer_file = "/run/media/live/FIELDKIT/bromigos/install.toml"
            win.a.update(auto=True, disk=win.probe["disks"][1]["path"], mode="erase", encrypt=True)
            win.countdown = 7
            win.show_step("auto")
        elif sid == "user":
            win.a.update(user_edited=False, host_edited=False)
            win.show_step("user")
            for k, v in (("full_name", fill["full_name"]), ("password", fill["password"]), ("password2", fill["password"])):
                win.f[k].set_text(v)
            win.a.update(full_name="Alex Rivera", user="alex", hostname="alex-pc", password="x")
        elif sid == "install":
            win.show_step("install")
            win._stage(41, "Copying bromigOS onto the disk (338 of 816)")
            for t in ("Creating partitions: /dev/nvme0n1", "luks2 formatting mapper dev: /dev/mapper/root", "(338/555) installing mesa"):
                win._line(t)
        elif sid == "done":
            win.done = True
            win.show_step("done")
        elif sid == "done-secureboot":      # the install set up Secure Boot: its code on the last page
            backend.SECUREBOOT_CODE = "4821"
            win.done = True
            win.show_step("done")
            backend.SECUREBOOT_CODE = None
        elif sid == "failed":
            win.done = "Making room stopped and the install didn't finish. The other system's files are as they were."
            win.lines = ["ntfsresize: …"]
            win.show_step("done")
        else:
            win.show_step(sid)
        GLib.timeout_add(500, lambda: (snapshot(win, os.path.join(out, f"gui-{sid}.png")), print(f"rendered gui-{sid}.png"), False)[-1])
        return True
    GLib.timeout_add(1300, step)
    return False


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    opts = {"windowed": "--windowed" in argv}
    if "--fake" in argv or "--render" in argv:
        os.environ["BROMIGOS_INSTALLER_FAKE"] = "1"
        backend.FAKE = True
    if "--script" in argv:
        opts["script"] = json.loads(_read(argv[argv.index("--script") + 1]))
    if "--render" in argv:
        opts["render"] = argv[argv.index("--render") + 1]
        opts["windowed"] = True
    if "--size" in argv:
        opts["size"] = tuple(int(x) for x in argv[argv.index("--size") + 1].split("x"))
    return App(opts).run([])


if __name__ == "__main__":
    sys.exit(main())
