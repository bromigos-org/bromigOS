"""Drive the Idle & lock page as a user would: switch the lock off (a toast with Undo), undo,
pick Screensaver only, drag the screensaver's slider; after each, idle.toml and the summary
are checked. Then Accessibility: Reduced motion and high contrast switched (their file, the
theme rendered again, toasts with Undo), and the theme's measured contrast shown. Run by render.sh --interact, in its headless compositor and throwaway home
(no session there: hypridle is never restarted).

    python3 tools/settings/interact.py desktop/settings
"""
import os, sys, tomllib
sys.path.insert(0, sys.argv[1])
from gi.repository import GLib
from bromigos_settings import app as A

HOME = os.environ["HOME"]
F = os.path.join(HOME, ".config/bromigos/idle.toml")
results = []

def toml():
    try:
        with open(F, "rb") as f:
            return tomllib.load(f)
    except FileNotFoundError:
        return {}

class T(A.App):
    def _snap_when_ready(self, waited):
        self.page = self.win.built["idle"]._idle
        self.toasts = []
        orig = self.win.toast
        def spy(text, undo=None, timeout=5):
            self.toasts.append((text, undo is not None))
            orig(text, undo, timeout)
        self.win.toast = spy
        self.steps = [self.s1, self.c1, self.s2, self.c2, self.s3, self.c3, self.s4, self.c4,
                      self.a0, self.a1, self.ac1, self.a2, self.ac2, self.a3, self.ac3]
        GLib.timeout_add(300, self.next)
        return False

    def next(self):
        if self.win.ctx.pending or self.page.pending:
            return True
        if not self.steps:
            self.quit(); return False
        self.steps.pop(0)()
        return True

    def s1(self):  # the lock's switch off
        self.page.timer_widgets["lock"][3].set_active(False)
    def c1(self):
        t = toml(); ok = t.get("lock", {}).get("enabled") is False and self.toasts[-1] == ("Lock on idle: off", True)
        results.append(("lock switch off -> idle.toml, toast with Undo", ok, self.toasts[-1:], self.page.summary.get_text()))
    def s2(self):
        self.page.undo()
    def c2(self):
        t = toml(); ok = t.get("lock", {}).get("enabled") is not False and self.page.timer_widgets["lock"][3].get_active()
        results.append(("undo -> back", ok, self.toasts[-1:], self.page.summary.get_text()))
    def s3(self):
        self.page.preset_group.set_active_name("screensaver-only")
    def c3(self):
        ok = self.page.summary.get_text().startswith("Screensaver at 8 min, then nothing locks") and not self.page.timer_widgets["lock"][3].get_active()
        results.append(("preset Screensaver only", ok, self.toasts[-1:], self.page.summary.get_text()))
    def s4(self):
        self.page.timer_widgets["screensaver"][1].set_value(5)
    def c4(self):
        ok = toml().get("screensaver", {}).get("minutes") == 5 and "5 min" in self.page.summary.get_text()
        results.append(("slider to 5 min (debounced)", ok, self.toasts[-1:], self.page.summary.get_text()))

    # Accessibility: motion and contrast, with undo
    def a0(self):
        self.win.open_page("accessibility")
    def a1(self):
        self.a = self.win.built["accessibility"]._a11y
        self.a.motion_group.set_active_name("reduced")
    def ac1(self):
        ok = A11Y().get("motion") == "reduced" and self.toasts[-1] == ("Motion: Reduced", True)
        results.append(("motion Reduced -> accessibility.toml, toast with Undo", ok, self.toasts[-1:], ""))
    def a2(self):
        self.a.contrast_row.set_active(True)
    def ac2(self):
        pal = os.path.join(HOME, ".local/state/bromigos/theme/current/palette.json")
        ok = A11Y().get("contrast") == "high" and os.path.exists(pal) and self.toasts[-1] == ("Contrast: high", True)
        results.append(("high contrast -> accessibility.toml, the theme rendered again", ok, self.toasts[-1:], ""))
    def a3(self):
        self.a.apply(["contrast", "normal"], "back", None)
    def ac3(self):
        rows = [r.get_title() for r in self.a.check_rows]
        ok = A11Y().get("contrast") == "normal" and len(rows) == 2
        results.append(("contrast back; the theme measured, as designed and high", ok, rows, ""))


def A11Y():
    try:
        with open(os.path.join(HOME, ".config/bromigos/accessibility.toml"), "rb") as f:
            return tomllib.load(f)
    except FileNotFoundError:
        return {}


T(render=("/dev/null", "idle", 1120, 780)).run([sys.argv[0]])
bad = 0
for name, ok, toast, summary in results:
    print(("PASS" if ok else "FAIL"), name, "|", toast, "|", summary)
    bad += not ok
print(f"{len(results)} steps, {bad} failed")
sys.exit(1 if bad or len(results) < 7 else 0)
