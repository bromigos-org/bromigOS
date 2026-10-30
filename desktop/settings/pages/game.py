"""Playing games (docs/settings.md, "Playing games"; manual: games.md): whether games are
ready to play, in plain words, from `bromigos game check`; one Fix; the Proton games use;
Set up Steam when Steam isn't installed; then game mode and its fullscreen detection.

bromigOS keeps Steam and Proton ready by itself (`bromigos game maintain`, after each
update and each time Steam exits), so this page mostly says so. What it lists is only what
needs the person, and Fix does now what bromigOS would do the next time Steam closes, plus
the one part that needs the password (a leftover login screen file in /etc, through pkexec).

The status card is a DRIFTGLASS GLOW panel (docs/DRIFTGLASS.md): a controller's hologram on
its Emitter that turns slowly while games are ready, Pulses while checking or fixing and
Sparks once when a fix lands; dim and still while something needs the person. It moves only
while the page is shown, and not at all under reduced motion.
"""
import os
import shutil
import sys
import time

from gi.repository import Gdk, GLib, Gtk

from bromigos_settings import Entry, Page

for _p in ("/usr/lib/bromigos/lib", os.path.join(os.path.dirname(os.path.realpath(__file__)), "..", "..", "lib")):
    if os.path.isdir(_p) and _p not in sys.path:
        sys.path.insert(0, _p)

import bromigos_driftglass as H  # noqa: E402
import bromigos_gamefix as F  # noqa: E402

CMD = ["bromigos", "game"]
TIDY = "/usr/lib/bromigos/sddm/bromigos-sddm-tidy"
WICK = {"void": "#000500", "panel": "#001300", "selection": "#003b00", "primary": "#39ff14", "soft": "#9cff8a",
        "dim": "#159b09", "text": "#c4f5bb", "muted": "#7e927e", "faint": "#4e6b4e", "warn": "#d4af37",
        "danger": "#ff766f", "white": "#e8ffe0"}
CSS = """
.game-status { padding: 12px; border-radius: 12px; }
.game-headline { font-size: 1.3em; font-weight: 700; }
.game-proton { font-size: 0.9em; opacity: 0.85; }
"""


def _motion():
    try:
        import bromigos_theme as T
        return T.motion()
    except Exception:
        return "full"


def _hc():
    try:
        import bromigos_theme as T
        return T.high_contrast()
    except Exception:
        return False


class GamePage:
    def __init__(self, ctx):
        self.ctx = ctx
        self.state = None                  # readiness(), once the first check answers
        self.doc = None
        self.busy = None                   # "checking", "fixing"
        self.spark = None                  # when the last fix landed (monotonic)
        self.t0 = time.monotonic()
        self.still = _motion() != "full"
        self.hc = _hc()
        self.timer = None
        self.note_rows = []
        self._css()
        self.page = ctx.page()
        self.page.set_reset(None, hint="Nothing here has a default to go back to: game mode is off until you turn "
                                       "it on, and Steam's settings are your own")
        self._build_status()
        self._build_mode()
        self.page.connect("map", lambda *_: self.check())
        self.refresh()
        self.check()
        GLib.timeout_add_seconds(2, self.tick)

    def _css(self):
        prov = Gtk.CssProvider()
        prov.load_from_string(CSS) if hasattr(prov, "load_from_string") else prov.load_from_data(CSS.encode())
        Gtk.StyleContext.add_provider_for_display(Gdk.Display.get_default(), prov,
                                                  Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)

    def pal(self):
        p = dict(WICK)
        p.update({k: v for k, v in (self.ctx.colors or {}).items() if isinstance(v, str) and v.startswith("#")})
        return p

    # ------------------------------------------------------------ ready to play
    def _build_status(self):
        ctx = self.ctx
        g = self.status_group = ctx.group(
            self.page, "Ready to play", "Steam, Proton and what games need to start. bromigOS keeps them in order "
            "by itself.", key="status",
            hint="Whether Steam games can start on this computer, and anything only you can do")
        card = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=14)
        card.add_css_class("card")
        card.add_css_class("game-status")
        ctx.hint(card, "Whether Steam games can start here. bromigOS checks Steam, Proton and the Steam Linux "
                       "Runtimes, and repairs what it can by itself")
        self.holo = Gtk.DrawingArea(content_width=112, content_height=84)
        self.holo.set_draw_func(lambda _a, cr, w, h: self.draw_holo(cr, w, h))
        ctx.hint(self.holo, "Lit and turning: games are ready. Dim: something needs you. Breathing: checking or "
                            "fixing")
        card.append(self.holo)
        words = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4, hexpand=True, valign=Gtk.Align.CENTER)
        self.headline = Gtk.Label(label="Checking…", xalign=0, wrap=True)
        self.headline.add_css_class("game-headline")
        ctx.hint(self.headline, "Games are ready, or how many things need you")
        self.detail = Gtk.Label(label="", xalign=0, wrap=True)
        self.detail.add_css_class("dim-label")
        ctx.hint(self.detail, "What bromigOS is doing about it, and when")
        self.proton = Gtk.Label(label="", xalign=0, wrap=True, selectable=False)
        self.proton.add_css_class("game-proton")
        ctx.hint(self.proton, "The Proton (the layer that runs Windows games) every game uses unless you chose "
                              "another for a game in Steam: its Properties › Compatibility")
        buttons = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8, margin_top=6)
        self.fix_b = ctx.button("Fix", self.fix, "Fixes now what bromigOS would fix by itself the next time Steam "
                                "closes: games set to a removed Proton, the default Proton, broken runtimes. A "
                                "leftover login screen file asks for your password. Close Steam first",
                                primary=True)
        self.setup_b = ctx.button("Set up Steam", self.setup, "Opens a terminal that installs Steam, GameMode and "
                                  "the 32-bit graphics drivers for this computer's graphics cards (it asks for "
                                  "your password)", primary=True)
        self.again_b = ctx.button("Check again", self.check, "Looks at Steam, Proton and the runtimes again")
        for w in (self.fix_b, self.setup_b, self.again_b):
            buttons.append(w)
        for w in (self.headline, self.detail, self.proton, buttons):
            words.append(w)
        card.append(words)
        g.add(card)
        # what it found, under the card (a list of its own: the group's rows would go above it)
        self.notes = Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE, margin_top=12)
        self.notes.add_css_class("boxed-list")
        self.notes.set_visible(False)
        g.add(self.notes)
        upkeep = Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE, margin_top=12)
        upkeep.add_css_class("boxed-list")
        g.add(upkeep)
        ctx.row(upkeep, "Kept ready by itself", "After each update and each time Steam exits, bromigOS installs the "
                "newest GE-Proton, points games at a Proton that's installed and replaces broken runtimes. Nothing "
                "changes while Steam is open, and every change keeps a backup.", key="upkeep",
                hint="bromigos game maintain, run by its user service. You don't need to do anything",
                buttons=[("Log", lambda: ctx.terminal(["journalctl", "--user", "-u", "bromigos-game-maintain",
                                                       "-n", "200", "--no-pager"]),
                          "Opens what it did, from the journal, in a terminal")],
                advanced={"runs": "bromigos game maintain",
                          "note": "bromigos-game-maintain.path starts it when Steam starts or exits; "
                                  "journalctl --user -u bromigos-game-maintain"})
        self.sync()

    def draw_holo(self, cr, w, h):
        st = self.state
        live = bool(st and st["ready"])
        fx = None
        if self.busy:
            fx = ("pulse", time.monotonic() - self.t0)
        elif self.spark is not None and time.monotonic() - self.spark < 0.7:
            fx = ("spark", time.monotonic() - self.spark)
        size = min(w, h)
        H.glyph(cr, "controller", (w - size) / 2, 0, size, self.pal(), t=time.monotonic() - self.t0,
                live=live, fx=fx, still=self.still, hc=self.hc)

    def moving(self):
        return bool(self.busy or (self.state and self.state["ready"]) or
                    (self.spark is not None and time.monotonic() - self.spark < 0.7))

    def animate(self):
        """The hologram's timer: only while it's shown, moving, and motion is on."""
        if self.still or self.timer is not None:
            return

        def tick():
            if self.holo.get_mapped() and self.moving():
                self.holo.queue_draw()
                return True
            self.timer = None
            return False
        self.timer = GLib.timeout_add(45, tick)

    def sync(self):
        st = self.state
        ctx = self.ctx
        if self.busy == "fixing":
            self.headline.set_text("Fixing…")
        elif st is None:
            self.headline.set_text("Checking…")
        else:
            self.headline.set_text(st["headline"])
        self.detail.set_text(st["detail"] if st else "")
        self.detail.set_visible(bool(st and st["detail"]))
        proton = st and st["proton"]
        self.proton.set_text(f"Proton in use: {proton}" if proton else "")
        self.proton.set_visible(bool(proton))
        self.fix_b.set_visible(bool(st and st["fixable"]))
        self.setup_b.set_visible(bool(st and st["setup"]))
        for b in (self.fix_b, self.setup_b, self.again_b):
            b.set_sensitive(self.busy is None)
        ctx.clear_group(self.notes, self.note_rows)
        for f in (st["needs_you"] if st else []):
            tip = " ".join(x for x in (f.get("detail"), f.get("fix")) if x)
            r = ctx.note(self.notes, f["title"], "error" if f["level"] == "problem" else "warn", hint=tip)
            r.set_subtitle(GLib.markup_escape_text(f.get("fix") or ""))
            r.set_subtitle_lines(4)
            self.note_rows.append(r)
        for f in (st["handled"] if st else []):
            when = ("when Steam closes" if (self.doc or {}).get("steam_running") else "the next time Steam closes") \
                if f.get("auto") else "at its next update"
            r = ctx.note(self.notes, f["title"], "note",
                         hint=f"bromigOS fixes this by itself {when}, or now with Fix. {f.get('detail') or ''}".strip())
            r.set_subtitle(GLib.markup_escape_text(f"bromigOS fixes this by itself {when}"))
            self.note_rows.append(r)
        self.notes.set_visible(bool(self.note_rows))
        self.holo.queue_draw()
        self.animate()

    def check(self):
        if self.busy:
            return
        self.busy = "checking"
        self.sync()
        self.ctx.json(CMD + ["check", "--json"], self.checked)

    def checked(self, doc, err):
        if self.busy == "checking":
            self.busy = None
        if doc and doc.get("findings") is not None:
            self.doc = doc
            self.state = F.readiness(doc)
        elif self.state is None:
            self.state = {"ready": False, "headline": "Couldn't check", "detail": (err or "no answer")[:200],
                          "needs_you": [], "handled": [], "fixable": False, "root": False, "setup": False,
                          "proton": None}
        self.sync()

    def setup(self):
        self.ctx.terminal(CMD + ["setup"])
        self.ctx.toast("Setting up Steam in a terminal. Check again when it's done")

    def fix(self):
        if self.busy:
            return
        self.busy = "fixing"
        root = bool(self.state and self.state["root"])
        self.sync()
        ctx = self.ctx

        def done(said):
            self.busy = None
            self.spark = time.monotonic()
            ctx.toast(said, timeout=8)
            self.check()

        def checked(doc, err):
            steam = bool(doc) and any("Steam is running" in d for d in doc.get("fixed") or [])
            said = ("Close Steam first: bromigOS fixes the rest by itself when it exits" if steam else
                    "Fixed" if doc else f"Not fixed: {(err or 'no answer')[:120]}")
            if not (root and os.access(TIDY, os.X_OK) and shutil.which("pkexec")):
                done(said)
                return
            # the login screen's leftover file: root's, so the password prompt (polkit) asks
            ctx.run(["pkexec", TIDY, "--apply", "--json"],
                    lambda ok, out, err: done(said if ok else "The login screen file stays: the password prompt "
                                                              "was dismissed"))

        def maintained(doc, err):
            # then what isn't Steam's (a second bar), through the check's own --fix
            ctx.json(CMD + ["check", "--fix", "--json"], checked)
        ctx.json(CMD + ["maintain", "--refresh", "--json"], maintained)

    # ------------------------------------------------------------ game mode
    def _build_mode(self):
        ctx = self.ctx
        g = ctx.group(self.page, "Game mode", "Super+Ctrl+G turns it on. Ctrl+Shift+F12 always leaves it.",
                      hint="Gives a game the keyboard and quiets the desktop until you leave")
        self.mode = ctx.switch_row(g, "Game mode", "Pass keys to the game and quiet the desktop", key="mode",
                                   on_toggle=lambda on: self.change(["on" if on else "off"]),
                                   hint="No desktop shortcuts except Ctrl+Shift+F12. Stops idle and idle locking, "
                                        "quiets notifications, pauses the wallpaper and hides panels.")
        self.auto = ctx.switch_row(g, "Automatic game mode", "Off by default; follows fullscreen game focus",
                                   key="auto", on_toggle=lambda on: self.change(["auto", "on" if on else "off"]),
                                   hint="Detects fullscreen steam_app_* windows, gamescope and .exe games. "
                                        "Leaving manually keeps it off until focus or fullscreen changes.")
        ctx.row(g, "Recovery from a TTY or SSH", "bromigos game off", key="recovery",
                hint="Restores shortcuts and the previous notification and panel state")

    def change(self, args):
        self.ctx.change(CMD + args + ["--json"], "Game setting changed", done=lambda *_: self.refresh(),
                        failed=lambda *_: self.refresh())

    def refresh(self):
        self.ctx.json(CMD + ["status", "--json"], self.got)

    def got(self, doc, err):
        if doc and doc.get("ok"):
            self.mode.set_quiet(bool(doc["on"]))
            self.auto.set_quiet(bool(doc["auto"]))

    def tick(self):
        if self.page.get_mapped():
            self.refresh()
        return True


def build(ctx):
    page = GamePage(ctx)
    page.page._game = page
    return page.page


def refresh(widget):
    widget._game.refresh()
    widget._game.check()


PAGE = Page(id="game", title="Playing games", group="desktop", order=65, build=build, refresh=refresh,
            docs="games.md", icon="input-gaming-symbolic", summary="Steam and Proton ready, game mode",
            intro="Whether games are ready to play, and game mode: the keyboard for the game and a quiet desktop.",
            keywords=["games", "gaming", "steam", "proton", "ge-proton", "wine", "lutris"],
            entries=[Entry("status", "Ready to play", ["steam", "proton", "games won't start", "game check",
                                                       "fix games", "install steam", "set up steam"],
                           "Ready to play"),
                     Entry("upkeep", "Kept ready by itself", ["ge-proton update", "maintenance", "automatic"],
                           "Ready to play"),
                     Entry("mode", "Game mode", ["game shortcuts", "keyboard"], "Game mode"),
                     Entry("auto", "Automatic game mode", ["fullscreen", "automatic games"], "Game mode")])
