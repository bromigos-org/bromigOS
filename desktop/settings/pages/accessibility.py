"""Accessibility: how much the desktop moves, and its contrast (docs/accessibility.md).

Everything goes through `bromigos accessibility … --json` (the rules live in the core): a
change applies at once (accessibility.toml written, the theme rendered again, the running
apps told) and leaves a toast with Undo. The theme's measured contrast, as designed and
made high, is shown from `bromigos accessibility check --json`."""
import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gtk  # noqa: E402

from bromigos_settings import Entry, Page  # noqa: E402

A11Y_TOML = "~/.config/bromigos/accessibility.toml"

MOTION = [
    ("full", "Full", "Everything moves as designed."),
    ("reduced", "Reduced", "Calmer and slower: no parallax, flicker, flashes or static; windows fade instead of sliding."),
    ("still", "Still", "The live background holds a still frame, drawn again only when what it shows changes; "
                       "no window animations."),
]
MOTION_NAMES = {k: t for k, t, _ in MOTION}


def _pair(c):
    return f"{c.get('fg')} on {c.get('bg')} {c.get('ratio')}:1 (needs {c.get('min'):g}:1)"


class AccessibilityPage:
    def __init__(self, ctx):
        self.ctx = ctx
        self.syncing = False
        self.doc = {}
        self.check_rows = []
        self.problem_rows = []
        self.page = ctx.page()
        cmd = next((c for c in ("accessibility", "a11y") if ctx.has_command(c)), None)
        if not cmd:
            ctx.placeholder(self.page, "Motion and contrast",
                            "Reduced motion and high contrast come with `bromigos accessibility` "
                            "(bromigos-core); it isn't installed here.", hint="Not installed")
            self._animations()
            return
        self.page.set_reset(self.reset_defaults, what="Motion back to Full and high contrast off (the theme as "
                                                      "designed). Undo puts yours back.")
        self._motion()
        self._contrast()
        self._check()
        self._animations()
        d = ctx.json_now(["bromigos", "accessibility", "--json"])
        if d:
            self.sync(d)
        self.measure()

    # ------------------------------------------------------------------ building
    def _motion(self):
        g = self.ctx.group(self.page, "Motion", "How much the desktop moves: the live background, the worlds, the "
                                                "decks, window animations.",
                           hint="bromigos accessibility motion full|reduced|still")
        tg = Adw.ToggleGroup(homogeneous=True)
        tg.set_hexpand(True)
        for key, label, hint in MOTION:
            tg.add(Adw.Toggle(name=key, label=label, tooltip=hint))
        self.ctx.hint(tg, "Full, Reduced or Still: applies at once, to the background, the decks and the windows")
        tg.connect("notify::active-name", self._motion_chosen)
        self.motion_group = tg
        tg._bromigos_key = "motion"
        g.add(tg)
        box = Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE)
        box.add_css_class("boxed-list")
        box.set_margin_top(8)
        self.motion_row = Adw.ActionRow(title="Full", subtitle=MOTION[0][2])
        self.motion_row.set_subtitle_lines(0)
        self.ctx.hint(self.motion_row, "What the motion setting in force does")
        box.append(self.motion_row)
        self.ctx.advanced(box, self.motion_row, {"file": A11Y_TOML, "key": "motion",
                                                 "runs": "bromigos accessibility motion full|reduced|still"})
        g.add(box)

    def _contrast(self):
        g = self.ctx.group(self.page, "Contrast")
        row = Adw.SwitchRow(title="High contrast",
                            subtitle="Every colour raised to WCAG AAA: text 7:1, quiet text 4.5:1, the selection and "
                                     "borders 3:1; panels opaque, no glow. Hues are kept.")
        row.set_subtitle_lines(0)
        self.ctx.hint(row, "bromigos accessibility contrast high|normal: the theme rendered again with every colour "
                           "raised; the bar, the launcher, the terminal, the lock screen and this window follow")
        row.connect("notify::active", self._contrast_switched)
        self.contrast_row = row
        row._bromigos_key = "contrast"
        g.add(row)
        self.ctx.advanced(g, row, {"file": A11Y_TOML, "key": "contrast",
                                   "runs": "bromigos accessibility contrast high|normal"})
        self.problems = g

    def _check(self):
        g = self.ctx.group(self.page, "The theme, measured",
                           "Each pair of colours the desktop draws, against high contrast's targets.",
                           hint="bromigos accessibility check: WCAG 2.1 contrast ratios", key="measured")
        self.check_group = g
        self.check_wait = Gtk.Label(label="Measuring…", xalign=0)
        self.check_wait.add_css_class("dim-label")
        g.add(self.check_wait)

    def _animations(self):
        g = self.ctx.group(self.page, "The animations", "One by one, as well (the menu's TOGGLE has each).",
                           key="animations")
        self.ctx.row(g, "Animation switches", "Each moving part of the background can be switched off (bromigos anim off NAME)",
                     hint="Lists the animation switches in a terminal",
                     buttons=[("List", lambda: self.ctx.terminal(["bromigos", "anim"]), "bromigos anim, in a terminal")])
        self.ctx.row(g, "The live background", "All of it off, or on again (SUPER+SHIFT+B)", hint="bromigos live on|off",
                     buttons=[("Toggle", lambda: self.ctx.launch(["bromigos-live", "toggle"]),
                               "Turns the animated background off or on")])

    # ------------------------------------------------------------------ state
    def sync(self, d):
        acc = d.get("accessibility") or {}
        self.doc = acc
        self.syncing = True
        try:
            m = acc.get("motion", "full")
            self.motion_group.set_active_name(m)
            self.motion_row.set_title(MOTION_NAMES.get(m, m))
            self.motion_row.set_subtitle(dict((k, h) for k, _, h in MOTION).get(m, ""))
            self.contrast_row.set_active(acc.get("contrast") == "high")
        finally:
            self.syncing = False
        for r in self.problem_rows:
            self.problems.remove(r)
        self.problem_rows = [self.ctx.note(self.problems, f"accessibility.toml: {p}", "warn")
                             for p in acc.get("problems") or []]

    def measure(self):
        def done(doc, err):
            for r in self.check_rows:
                self.check_group.remove(r)
            self.check_rows = []
            if self.check_wait is not None:
                self.check_group.remove(self.check_wait)
                self.check_wait = None
            if not doc:
                self.check_rows.append(self.ctx.note(self.check_group, f"bromigos accessibility check didn't answer: {err}", "warn"))
                return
            theme = doc.get("theme", "")
            for key, title in (("normal", "As designed"), ("high", "High contrast")):
                r = doc.get(key) or {}
                checks = r.get("checks") or []
                short = [c for c in checks if not c.get("ok")]
                low = r.get("lowest") or {}
                if short:
                    sub = f"{len(checks) - len(short)} of {len(checks)} pairs meet the targets; the lowest: {_pair(low)}"
                else:
                    sub = f"all {len(checks)} pairs meet the targets; the lowest: {_pair(low)}"
                row = Adw.ExpanderRow(title=f"{title} ({theme})", subtitle=sub)
                row.set_subtitle_lines(0)
                row.add_prefix(Gtk.Image.new_from_icon_name(
                    "object-select-symbolic" if r.get("ok") else "dialog-warning-symbolic"))
                self.ctx.hint(row, ("The theme's own colours" if key == "normal" else
                                    "The colours high contrast renders from it") + ": open for the pairs that fall short")
                for c in short[:40]:
                    sr = Adw.ActionRow(title=_pair(c))
                    self.ctx.hint(sr, "A foreground on a background, its contrast ratio, and the target it misses")
                    row.add_row(sr)
                if not short:
                    row.set_enable_expansion(False)
                self.check_group.add(row)
                self.check_rows.append(row)
        self.ctx.json(["bromigos", "accessibility", "check", "--json"], done)

    # ------------------------------------------------------------------ changes
    def apply(self, args, said, undo_args):
        def done(doc, err):
            if not doc or doc.get("ok") is False:
                self.ctx.toast(f"Not changed: {(doc or {}).get('error') or err or 'bromigos accessibility failed'}")
                d = self.ctx.json_now(["bromigos", "accessibility", "--json"])
                if d:
                    self.sync(d)
                return
            self.sync(doc)
            self.measure()
            undo = (lambda: self.apply(undo_args, "Undone", None)) if undo_args else None
            self.ctx.toast(said, undo)
        self.ctx.json(["bromigos", "accessibility", *args, "--json"], done)

    def reset_defaults(self):
        """Motion Full and contrast normal; Undo puts both back."""
        A = ["bromigos", "accessibility"]
        old_m, old_c = self.doc.get("motion", "full"), self.doc.get("contrast", "normal")
        if old_m == "full" and old_c == "normal":
            self.ctx.toast("Already bromigOS's defaults")
            return None

        def fin(d):
            if d:
                self.sync(d)
                self.measure()
            self.ctx.toast("Accessibility: as designed", undo)

        def undo():
            self.ctx.json(A + ["motion", old_m, "--json"],
                          lambda d, e: self.apply(["contrast", old_c], "Undone", None))
        self.ctx.json(A + ["motion", "full", "--json"],
                      lambda d, e: self.ctx.json(A + ["contrast", "normal", "--json"], lambda d2, e2: fin(d2)))
        return None

    def _motion_chosen(self, tg, _p):
        if self.syncing:
            return
        new, old = tg.get_active_name(), self.doc.get("motion", "full")
        if new and new != old:
            self.apply(["motion", new], f"Motion: {MOTION_NAMES.get(new, new)}", ["motion", old])

    def _contrast_switched(self, row, _p):
        if self.syncing:
            return
        new = "high" if row.get_active() else "normal"
        old = self.doc.get("contrast", "normal")
        if new != old:
            self.apply(["contrast", new], f"Contrast: {new}", ["contrast", old])


def build(ctx):
    p = AccessibilityPage(ctx)
    p.page._a11y = p
    return p.page


def refresh(widget):
    p = getattr(widget, "_a11y", None)
    if p is not None and getattr(p, "motion_group", None) is not None:
        d = p.ctx.json_now(["bromigos", "accessibility", "--json"])
        if d:
            p.sync(d)


PAGE = Page(id="accessibility", title="Accessibility", icon="preferences-desktop-accessibility-symbolic", order=40,
            group="desktop", docs="accessibility.md", summary="motion, contrast",
            intro="How much the desktop moves and how strong its contrast is. Each change applies at once to the "
                  "background, the decks, the windows and the apps, and can be undone.",
            keywords=["a11y", "reduced motion", "contrast", "animations", "still", "wcag"],
            entries=[Entry("motion", "Reduce motion", ["reduced motion", "still", "animations", "vestibular",
                                                       "parallax"], "Motion"),
                     Entry("contrast", "High contrast", ["contrast", "wcag", "legibility", "low vision"], "Contrast"),
                     Entry("measured", "The theme's contrast, measured", ["contrast ratio", "check colours"],
                           "The theme, measured"),
                     Entry("animations", "Animation switches", ["anim", "rain", "turn off animations"],
                           "The animations")],
            build=build, refresh=refresh)
