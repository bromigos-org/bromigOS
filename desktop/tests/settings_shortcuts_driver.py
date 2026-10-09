"""Drive the Settings app's Shortcuts page as a user would, inside e2e_keys_nested.py's nested
Hyprland: click Desktop menu's Change… (the capture window opens; the harness types the new
keys), use the toast's Undo, Remove a shortcut, Reset everything; after each, keys.toml and
the toast are checked. Prints PASS/FAIL lines.

    python3 settings_shortcuts_driver.py DESKTOP/settings
"""
import os
import sys
import tomllib

sys.path.insert(0, sys.argv[1])
from gi.repository import GLib, Gtk  # noqa: E402

from bromigos_settings import app as A  # noqa: E402

CONF = os.path.join(os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config"), "bromigos", "keys.toml")
results = []


def record():
    try:
        with open(CONF, "rb") as f:
            return tomllib.load(f)
    except FileNotFoundError:
        return {}


def buttons(widget):
    """Every Gtk.Button under `widget`, with its label and hover hint."""
    out, stack = [], [widget]
    while stack:
        w = stack.pop()
        if isinstance(w, Gtk.Button) and w.get_label():
            out.append(w)
        c = w.get_first_child()
        while c is not None:
            stack.append(c)
            c = c.get_next_sibling()
    return out


def click(page_widget, label, hint_has):
    for b in buttons(page_widget):
        if b.get_label() == label and hint_has in (b.get_tooltip_text() or ""):
            b.emit("clicked")
            return True
    return False


class T(A.App):
    def _snap_when_ready(self, waited):
        self.widget = self.win.built["shortcuts"]
        self.page = self.widget._shortcuts
        self.toasts = []
        orig = self.win.toast

        def spy(text, undo=None, timeout=5):
            self.toasts.append((text, undo))
            orig(text, undo, timeout)
        self.win.toast = spy
        self.page._confirm = lambda why, then: then()        # the "Are you sure?" dialog says yes
        self.steps = [self.s1, self.c1, self.s2, self.c2, self.s3, self.c3, self.s4, self.c4]
        GLib.timeout_add(400, self.next)
        print("READY", flush=True)
        return False

    def next(self):
        if self.win.ctx.pending or self.page.busy:
            return True
        if not self.steps:
            self.quit()
            return False
        self.steps.pop(0)()
        return True

    def s1(self):        # Desktop menu's Change…: the harness presses SUPER + CTRL + M
        ok = click(self.widget, "Change…", "Desktop menu (now SUPER + SPACE)")
        print("CAPTURE" if ok else "NO-BUTTON", flush=True)

    def c1(self):
        b = next((b for b in record().get("bind") or [] if b.get("from") == "SUPER + SPACE"), {})
        text, undo = self.toasts[-1] if self.toasts else ("", None)
        ok = b.get("keys") == "SUPER + CTRL + M" and b.get("from") == "SUPER + SPACE" and undo is not None \
            and "SUPER + CTRL + M" in text
        results.append(("Change… -> pressed keys saved, a toast with Undo", ok, text))

    def s2(self):
        self.toasts[-1][1]()                 # the toast's Undo

    def c2(self):
        r = record()
        ok = not any(b.get("from") == "SUPER + SPACE" for b in r.get("bind") or []) and \
            "SUPER + SPACE" not in (r.get("unbind") or []) and \
            any(b.get("what") == "System monitor" for b in r.get("bind") or [])         # the rest kept
        results.append(("Undo -> back as it was", ok, self.toasts[-1][0] if self.toasts else ""))

    def s3(self):        # Remove on a shortcut the harness made (System monitor)
        click(self.widget, "Remove", "SUPER + ALT + T")

    def c3(self):
        names = [b.get("what") for b in record().get("bind") or []]
        text, undo = self.toasts[-1] if self.toasts else ("", None)
        results.append(("Remove -> gone, a toast with Undo", "System monitor" not in names and undo is not None, text))

    def s4(self):
        click(self.widget, "Reset…", "Puts every bromigOS key back")

    def c4(self):
        r = record()
        ok = not r.get("bind") and not r.get("unbind")
        results.append(("Reset… -> every key bromigOS's", ok, self.toasts[-1][0] if self.toasts else ""))


T(render=("/dev/null", "shortcuts", 1120, 780)).run([sys.argv[0]])
bad = 0
for name, ok, toast in results:
    print(("PASS" if ok else "FAIL"), name, "|", toast, flush=True)
    bad += not ok
sys.exit(1 if bad or len(results) < 4 else 0)
