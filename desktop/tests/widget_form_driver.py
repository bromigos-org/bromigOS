"""Draw a widget's settings form (Settings › Widgets › Settings…, widgetform.py) in its
sign-in states, inside e2e_widget_plugins_nested.py's nested Hyprland, and save each as a
picture. The account helper (lib/bromigos_account.py) keeps its tokens in memory here,
never in a keyring, and its sign-in is a stand-in that shows a made-up code: nothing
reaches a real service.

    python3 widget_form_driver.py DESKTOP/settings WIDGET OUTDIR

States: not set up (no client ID), signed out, the device code shown, signed in. Then a
second account: Add another account… (its name, and its server for GitLab and GitHub),
its client ID when its server needs one, its sign-in, both accounts signed in with which
of them the widget shows, and removing it. Prints PASS/FAIL lines and the pictures' paths.

Which accounts the widget shows is saved with `bromigos panels set`; here that runs
in-process through widgets/widget_settings.py (the same code), into this sandbox's HOME.
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
WHO = {"default": "relay_keeper", "work": "tide_work"}
SERVER = "https://git.example.org" if WIDGET in ("gitlab", "github") else ""     # the second account's own server


def fake_sign_in(provider, on_prompt=None, cancelled=None, account="default"):
    """The device flow, pretended: a code to show, then signed in once released."""
    stop = ACC._stopper(cancelled)
    page = ACC.base(provider, account) + "/activate"
    code = "WDJB-MJHT" if account == "default" else "QXRT-PLNV"
    on_prompt({"user_code": code, "verification_uri": page, "verification_uri_complete": f"{page}?code={code}",
               "expires_in": 1800})
    while not release.wait(0.1):
        if stop():
            raise ACC.SignInError("cancelled")
    release.clear()
    ACC._save(provider, {"access_token": "x", "who": WHO.get(account, account), "client_id": "demo"}, account)
    return ACC.status(provider, account)


ACC.sign_in = fake_sign_in
# "not set up" needs a provider without a built-in app: hide bromigOS's own client ID
ACC.PROVIDERS[WIDGET].pop("client_id", None) if WIDGET in ACC.PROVIDERS else None


def panels_in_process(ctx):
    """`bromigos panels set|unset WIDGET KEY …` answered by widget_settings.py itself."""
    import json as _json
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
                                    "widgets"))
    import widget_settings as WS
    real = ctx.json
    ran = []

    def json_(argv, done, stdin=None):
        if argv[:2] != ["bromigos", "panels"] or argv[2] not in ("set", "unset"):
            return real(argv, done, stdin)
        ran.append(argv)
        form = entry()["form"]
        try:
            if argv[2] == "set":
                vals = WS.set_value(argv[3], form, argv[4], [a for a in argv[5:] if a != "--json"])
            else:
                WS.unset(argv[3], argv[4])
                vals = WS.values(argv[3], form)
            GLib.idle_add(lambda: (done(_json.loads(_json.dumps({"values": vals})), ""), False)[1])
        except ValueError as e:
            GLib.idle_add(lambda: (done({"ok": False, "error": str(e)}, ""), False)[1])
    ctx.json = json_
    return ran


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
        b = s.blocks[0] if s and s.blocks else None
        host = ACC.base(WIDGET).split("://")[-1].removeprefix("www.")
        if n == 0:                                    # not set up: no client ID yet
            self.ran = panels_in_process(self.win.ctx)
            self.open_form()
        elif n == 1:
            t = self.texts()
            self.check("not set up: it asks for the client ID", "Connect" in t and "client ID" in t, t)
            self.shoot("not-set-up")
            ACC.configure(WIDGET, client_id="demo-client-id")
            self.open_form()
        elif n == 2:
            t = self.texts()
            self.check("signed out: Sign in is offered", "Not signed in" in t and "Sign in" in t, t)
            self.check("one account: no Remove, no Shown check", "Remove" not in t, t)
            self.shoot("signed-out")
            b.sign_in()
        elif n == 3:
            t = self.texts()
            self.check("the device code is shown, with its page", "WDJB-MJHT" in t and f"{host}/activate" in t, t)
            self.shoot("device-code")
            release.set()
        elif n == 4:
            t = self.texts()
            self.check("signed in, as whom", "Signed in" in t and "relay_keeper" in t, t)
            self.shoot("signed-in")
            s.open_add()                              # a second account
        elif n == 5:
            t = self.texts()
            self.check("Add another account asks for a name" + (" and the server" if SERVER else ""),
                       "Name" in t and (("Server address" in t) == bool(SERVER)), t)
            s.add_name.set_text("work")
            if SERVER:
                s.add_server.set_text(SERVER)
        elif n == 6:                                  # drawn with what was typed, then added
            self.shoot("add-account")
            s.submit_add()
        elif n == 7:
            t = self.texts()
            self.check("the second account is listed", [x.name for x in s.blocks] == ["default", "work"],
                       [x.name for x in s.blocks])
            w = s.block("work")
            if SERVER:                                # its own server: its own app, asked for only now
                self.check("its own server asks for its client ID", "work: connect" in t and "client ID" in t, t)
                self.shoot("second-needs-client-id")
                w.entries["client_id"].set_text("work-app")
                w.save_config(w.entries)
                self.check("the client ID is the second account's alone",
                           (ACC.config(WIDGET, "work")["client_id"], ACC.config(WIDGET)["client_id"])
                           == ("work-app", "demo-client-id"), ACC.config(WIDGET, "work"))
            w.sign_in()
        elif n == 8:
            t = self.texts()
            self.check("the second account's code shows in its own block", "QXRT-PLNV" in t and "WDJB-MJHT" not in t, t)
            self.shoot("second-device-code")
            release.set()
        elif n == 9:
            t = self.texts()
            self.check("both signed in, each as itself", "signed in as relay_keeper" in t and
                       "work: signed in as tide_work" in t, t)
            checks = [c for c in self.widgets_of(Gtk.CheckButton)]
            self.check("a Shown check for each account, both ticked", len(checks) == 2 and all(c.get_active()
                                                                                               for c in checks),
                       [c.get_active() for c in checks])
            self.check("the keyring holds two items", sorted(ACC.KEYRING.items) ==
                       [(f"bromigos-account:{WIDGET}", "default"), (f"bromigos-account:{WIDGET}", "work")],
                       sorted(ACC.KEYRING.items))
            self.shoot("two-accounts")
            checks[0].set_active(False)               # this widget shows work only
        elif n == 10:
            import widget_settings as WS
            self.check("unticking saves which accounts it shows", WS.read_file(WIDGET).get("account") == ["work"],
                       (WS.read_file(WIDGET), self.ran[-1:]))
            checks = [c for c in self.widgets_of(Gtk.CheckButton)]
            checks[0].set_active(True)                # both again: back to every signed-in account
        elif n == 11:
            import widget_settings as WS
            self.check("ticking it again goes back to every account", "account" not in WS.read_file(WIDGET),
                       WS.read_file(WIDGET))
            s.block("work").ask_remove()
        elif n == 12:
            t = self.texts()
            self.check("Remove asks first", "Remove the" in t and "Cancel" in t, t)
            self.shoot("remove-confirm")
            s.block("work").remove()
        elif n == 13:
            t = self.texts()
            self.check("removed: one account again, signed in as before",
                       ACC.names(WIDGET) == ["default"] and "Signed in as relay_keeper" in t and "work" not in t, t)
            self.check("its keyring item is gone", list(ACC.KEYRING.items) == [(f"bromigos-account:{WIDGET}",
                                                                                 "default")], ACC.KEYRING.items)
            self.quit()
            return False
        GLib.timeout_add(900, self.step, n + 1)
        return False

    def widgets_of(self, cls):
        out, stack = [], [self.form.dialog]
        while stack:
            x = stack.pop(0)
            if isinstance(x, cls):
                out.append(x)
            c = x.get_first_child()
            while c is not None:
                stack.append(c)
                c = c.get_next_sibling()
        return out


if __name__ == "__main__":
    d = Driver()
    d.run([sys.argv[0]])
    print(f"{sum(d.results)}/{len(d.results)} passed")
    sys.exit(0 if d.results and all(d.results) else 1)
