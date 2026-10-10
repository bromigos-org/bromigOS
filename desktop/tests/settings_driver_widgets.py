"""Settings › Widgets, driven as a person would, inside e2e_widgets_nested.py's nested
Hyprland: a widget's settings form (a value typed and applied lands in its .toml), and
Install from URL (a folder checked with `bromigos panels inspect`, what it would add shown,
Install clicked: the extension is in the ledger, approved through an answers file that
says Settings). Prints PASS/FAIL lines; with SHOTS set, pictures of the dialogs (grim,
inside the nested session).

    python3 settings_driver_widgets.py DESKTOP/settings SOURCE_FOLDER SUBPATH
"""
import faulthandler
import json
import os
import subprocess
import sys

faulthandler.dump_traceback_later(240, repeat=True)

sys.path.insert(0, sys.argv[1])
import gi  # noqa: E402

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, GLib, Gtk  # noqa: E402

from bromigos_settings import app as A  # noqa: E402

SOURCE, SUBPATH = sys.argv[2], sys.argv[3]
SHOTS = os.environ.get("SHOTS")
STATE = os.environ.get("XDG_STATE_HOME") or os.path.expanduser("~/.local/state")
CONFIG = os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")


def result(name, ok, detail=""):
    print(("PASS" if ok else "FAIL"), name, "|", str(detail)[:300], flush=True)


def walk(w):
    stack = [w]
    while stack:
        x = stack.pop()
        yield x
        c = x.get_first_child()
        while c is not None:
            stack.append(c)
            c = c.get_next_sibling()


def button(root, label):
    return next((x for x in walk(root) if isinstance(x, Gtk.Button) and x.get_label() == label), None)


def shot(name):
    if SHOTS:
        os.makedirs(SHOTS, exist_ok=True)
        subprocess.run(["grim", os.path.join(SHOTS, name + ".png")], capture_output=True)


class Driver(A.App):
    def __init__(self):
        super().__init__(render={"out": "-", "page": "widgets", "key": None, "search": None, "size": (1180, 860),
                                 "advanced": False, "audit": False})
        self.steps = None

    def _snap_when_ready(self, waited):
        if self.win.ctx.pending and waited < 30000:
            GLib.timeout_add(200, self._snap_when_ready, waited + 200)
            return False
        self.page = self.win.built["widgets"]._widgets
        self.steps = [self.form_open, self.form_type, self.form_check, self.url_open, self.url_check,
                      self.url_seen, self.url_install, self.url_done]
        GLib.timeout_add(400, self.next)
        return False

    def next(self):
        if self.win.ctx.pending:
            return True
        if not self.steps:
            self.quit()
            return False
        step = self.steps.pop(0)
        try:
            again = step()
        except Exception as e:                              # noqa: BLE001
            result(step.__name__, False, f"{type(e).__name__}: {e}")
            again = None
        if again:                                           # the step waits a little more
            self.steps.insert(0, again)
        return True

    # ------------------------------------------------------------------ a widget's form
    def form_open(self):
        w = next((w for w in self.page.gallery["widgets"] if w["name"] == "tide_watch"), None)
        result("the gallery lists the widget with its settings", w and w.get("form"), w)
        from bromigos_settings.widgetform import WidgetForm
        self.form = WidgetForm(self.win.ctx, w)
        self.form.present()

    def form_type(self):
        row = next(x for x in walk(self.form.dialog) if isinstance(x, Adw.EntryRow) and x.get_title() == "Harbour")
        row.set_text("Greywater Light")
        row.emit("apply")
        GLib.timeout_add(600, lambda: (shot("widget-settings-form"), False)[1])

    def form_check(self):
        path = os.path.join(CONFIG, "bromigos", "widgets", "tide_watch.toml")
        try:
            text = open(path).read()
        except OSError as e:
            text = str(e)
        result("a value typed in the form lands in the widget's .toml", 'harbour = "Greywater Light"' in text, text)
        self.form.dialog.close()

    # ------------------------------------------------------------------ Install from URL
    def url_open(self):
        from bromigos_settings.widgetform import InstallFromURL
        self.inst = InstallFromURL(self.win.ctx, done=self.page.refresh)
        self.inst.present()
        self.inst.url.set_text(SOURCE)
        self.inst.sub.set_text(SUBPATH)
        button(self.inst.dialog, "Check it").emit("clicked")

    def url_check(self):
        doc = self.inst.doc
        if doc is None and not any(r.get_title() == "It can't be installed" for r in self.inst.rows):
            return self.url_check                           # still fetching
        result("Check it: bromigos panels inspect read what it would add", doc and doc.get("name") == "hello-gauge"
               and doc["widgets"] and doc["widgets"][0].get("reads"), doc)

    def url_seen(self):
        titles = [r.get_title() for r in self.inst.rows]
        result("the dialog shows the widget, its maker and that it runs code",
               any(t.startswith("Widget:") for t in titles) and "Made by" in titles and "Runs code" in titles, titles)
        shot("install-from-url")

    def url_install(self):
        button(self.inst.dialog, "Install").emit("clicked")

    def url_done(self):
        try:
            led = json.load(open(os.path.join(STATE, "bromigos", "ext", "ledger.json")))
        except (OSError, ValueError):
            return self.url_done
        e = (led.get("extensions") or {}).get("hello-gauge")
        if not e:
            return self.url_done
        how = e.get("approved") or {}
        result("Install: in the ledger, approved through an answers file Settings wrote",
               how.get("how") == "answers" and "approvals/settings-" in how.get("detail", ""), how)
        ans = how.get("detail", "").split("answers file ", 1)[-1].split(" (sha256")[0]
        try:
            first = open(ans).readline()
        except OSError as e:
            first = str(e)
        result("the answers file says it was approved in Settings", "Approved in Settings" in first, first)


Driver().run([sys.argv[0]])
