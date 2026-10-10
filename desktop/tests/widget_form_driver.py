"""Draw a widget's settings form (Settings › Widgets › Settings…, widgetform.py) in its
sign-in states, inside e2e_widget_plugins_nested.py's nested Hyprland, and save each as a
picture. The account helper (lib/bromigos_account.py) keeps its tokens in memory here,
never in a keyring, and its sign-in is a stand-in that shows a made-up code: nothing
reaches a real service.

    python3 widget_form_driver.py DESKTOP/settings WIDGET OUTDIR

States: not set up (no client ID), signed out, the device code shown, signed in. Prints
PASS/FAIL lines and the pictures' paths.
"""
import os
import sys
import threading

sys.path.insert(0, sys.argv[1])
import gi  # noqa: E402

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import GLib, Gtk  # noqa: E402

import bromigos_account as ACC  # noqa: E402
from bromigos_settings import app as A  # noqa: E402

WIDGET, OUT = sys.argv[2], sys.argv[3]
os.makedirs(OUT, exist_ok=True)
ACC.KEYRING = ACC.MemoryKeyring()
release = threading.Event()


def fake_sign_in(provider, on_prompt=None, cancelled=None):
    """The device flow, pretended: a code to show, then signed in once released."""
    stop = ACC._stopper(cancelled)
    on_prompt({"user_code": "WDJB-MJHT", "verification_uri": "https://www.twitch.tv/activate",
               "verification_uri_complete": "https://www.twitch.tv/activate?device-code=WDJB-MJHT", "expires_in": 1800})
    while not release.wait(0.1):
        if stop():
            raise ACC.SignInError("cancelled")
    ACC._save(provider, {"access_token": "x", "who": "relay_keeper", "client_id": "demo"})
    return ACC.status(provider)


ACC.sign_in = fake_sign_in
# "not set up" needs a provider without a built-in app: hide bromigOS's own Twitch client ID
ACC.PROVIDERS[WIDGET].pop("client_id", None) if WIDGET in ACC.PROVIDERS else None


def entry():
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
                                    "widgets"))
    import gallery as G
    return next(e for e in G.entries() if e["name"] == WIDGET)


class Driver(A.App):
    def __init__(self):
        super().__init__(render={"out": None, "page": "widgets", "size": (1120, 860)})
        self.results = []
        self.form = None

    def _snap_when_ready(self, waited):
        GLib.timeout_add(600, self.step, 0)
        return False

    def shoot(self, name):
        win = self.win
        w, h = win.get_width(), win.get_height()
        paintable = Gtk.WidgetPaintable.new(win)
        snap = Gtk.Snapshot()
        paintable.snapshot(snap, w, h)
        node = snap.to_node()
        out = os.path.join(OUT, f"form-{WIDGET}-{name}.png")
        ok = node is not None and win.get_renderer().render_texture(node, None).save_to_png(out)
        self.check(f"picture of the form: {name}", ok, out)

    def check(self, name, ok, detail=""):
        print(("PASS" if ok else "FAIL"), name, "|", str(detail)[:300], flush=True)
        self.results.append(ok)

    def texts(self):
        out = []
        stack = [self.form.dialog]
        while stack:
            x = stack.pop()
            for get in ("get_title", "get_subtitle", "get_label"):
                f = getattr(x, get, None)
                if f:
                    try:
                        v = f()
                    except TypeError:
                        v = None
                    if isinstance(v, str) and v:
                        out.append(v)
            c = x.get_first_child()
            while c is not None:
                stack.append(c)
                c = c.get_next_sibling()
        return " | ".join(out)

    def open_form(self):
        from bromigos_settings.widgetform import WidgetForm
        if self.form:
            self.form.dialog.close()
        self.form = WidgetForm(self.win.ctx, entry())
        self.form.present()

    def step(self, n):
        s = self.form.signins[0] if self.form and self.form.signins else None
        if n == 0:                                    # not set up: no client ID yet
            self.open_form()
        elif n == 1:
            t = self.texts()
            self.check("not set up: it asks for the client ID", "Connect" in t and "client ID" in t, t)
            self.shoot("not-set-up")
            ACC.configure("twitch", client_id="demo-client-id")
            self.open_form()
        elif n == 2:
            t = self.texts()
            self.check("signed out: Sign in is offered", "Not signed in" in t and "Sign in" in t, t)
            self.shoot("signed-out")
            s.sign_in()
        elif n == 3:
            t = self.texts()
            self.check("the device code is shown, with its page", "WDJB-MJHT" in t and "twitch.tv/activate" in t, t)
            self.shoot("device-code")
            release.set()
        elif n == 4:
            t = self.texts()
            self.check("signed in, as whom", "Signed in" in t and "relay_keeper" in t, t)
            self.shoot("signed-in")
            self.quit()
            return False
        GLib.timeout_add(900, self.step, n + 1)
        return False


if __name__ == "__main__":
    d = Driver()
    d.run([sys.argv[0]])
    print(f"{sum(d.results)}/{len(d.results)} passed")
    sys.exit(0 if d.results and all(d.results) else 1)
