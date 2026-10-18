"""Layout forms: argv, retry, pending state and keyboard focus, without the user's desktop.

The GTK check starts its own headless Weston and a disposable HOME. No real command runs.
"""
import importlib.machinery
import importlib.util
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
from types import SimpleNamespace as NS
import unittest
from unittest.mock import patch

DESKTOP = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(DESKTOP / "lib"), str(DESKTOP.parent / "lib"), str(DESKTOP / "settings")]
import bromigos_widgetcards as W  # noqa: E402

try:
    import gi
    gi.require_version("Gtk", "4.0")
    HAVE_GTK = True
except (ImportError, ValueError):
    HAVE_GTK = False


def switcher_module():
    loader = importlib.machinery.SourceFileLoader("layout_switcher", str(DESKTOP / "bin/bromigos-theme-switcher"))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    return mod


class Widget:
    def __init__(self, **kwargs):
        self.label, self.text = kwargs.get("label", ""), ""
        self.sensitive, self.visible, self.focused = True, True, False
        self.signals, self.children = {}, []

    def append(self, widget): self.children.append(widget)
    def set_margin_start(self, _): pass
    def set_margin_end(self, _): pass
    def set_margin_bottom(self, _): pass
    def add_css_class(self, _): pass
    def set_tooltip_text(self, _): pass
    def set_label(self, text): self.label = text
    def set_visible(self, value): self.visible = value
    def set_sensitive(self, value): self.sensitive = value
    def get_text(self): return self.text
    def grab_focus(self): self.focused = True
    def connect(self, signal, callback): self.signals[signal] = callback


class FormTest(unittest.TestCase):
    def setUp(self):
        self.calls, self.refreshed, self.toasts = [], [], []
        self.closed = False
        self.host = NS(close_sheet=self.close)
        ctx = NS(button=lambda label, fn, hint, **kw: Widget(label=label),
                 json=lambda argv, done: self.calls.append((argv, done)), toast=self.toasts.append)
        gtk = NS(Box=Widget, Label=Widget, Entry=Widget, Orientation=NS(VERTICAL=1), Align=NS(END=1))
        self.row = NS(ctx=ctx, Gtk=gtk, tab=NS(host=self.host), doc={"screen": {"monitor": "TEST-1"}},
                      refresh=lambda **kw: self.refreshed.append(kw))

    def close(self): self.closed = True

    def test_new_layout_rejects_blank_name_in_sheet(self):
        form = W.LayoutSaveForm(self.row)
        form.submit()
        self.assertEqual(self.calls, [])
        self.assertIn("name", form.error.label)
        self.assertTrue(form.error.visible and form.name.focused)

    def test_new_layout_uses_literal_argv_and_does_not_apply(self):
        form = W.LayoutSaveForm(self.row)
        form.name.text = "My desk; $(touch nope)"
        form.description.text = "  Work and play  "
        form.name.signals["activate"](form.name)
        self.assertEqual(self.calls[0][0], ["bromigos", "panels", "layout", "save", "My desk; $(touch nope)",
                         "--description", "Work and play", "--monitor", "TEST-1", "--json"])
        self.assertTrue(form.pending)
        self.assertFalse(form.name.sensitive or form.cancel.sensitive or form.save.sensitive)
        form.submit()
        self.assertEqual(len(self.calls), 1)
        self.calls[0][1]({"ok": True, "id": "my-desk", "said": "Saved"}, "")
        self.assertTrue(self.closed)
        self.assertEqual(self.refreshed, [{"focus_id": "my-desk"}])

    def test_collision_stays_open_and_allows_retry(self):
        form = W.LayoutSaveForm(self.row)
        form.name.text = "Work"
        form.submit()
        self.calls[0][1]({"ok": False, "error": "A layout already uses work"}, "failed")
        self.assertFalse(form.pending or self.closed)
        self.assertTrue(form.error.visible and form.save.sensitive)
        self.assertIn("already", form.error.label)
        form.name.text = "Work again"
        form.submit()
        self.assertEqual(len(self.calls), 2)
        self.assertFalse(form.error.visible)

    def test_missing_command_or_invalid_response_keeps_form(self):
        for doc, err in ((None, "Command unavailable"), ([1], "")):
            with self.subTest(doc=doc):
                form = W.LayoutSaveForm(self.row)
                form.name.text = "Desk"
                form.submit()
                self.calls[-1][1](doc, err)
                self.assertTrue(form.error.visible)
                self.assertFalse(self.closed)

    def test_replace_keeps_metadata_and_initially_focuses_cancel(self):
        for source, title in (("yours", "Save changes"), ("bromigos", "Override")):
            with self.subTest(source=source):
                form = W.LayoutSaveForm(self.row, {"id": "work", "title": "Work", "source": source})
                self.assertEqual(form.title, title)
                self.assertIs(form.initial_focus, form.cancel)
                form.submit()
                self.assertEqual(self.calls[-1][0], ["bromigos", "panels", "layout", "save", "--replace", "work",
                                                   "--monitor", "TEST-1", "--json"])

    def test_theme_defaults_always_save_as_new(self):
        for ident in ("theme", "theme-wick"):
            item = {"id": ident, "title": "Made for Wick"}
            self.assertEqual(W.layout_save_action(item), ("Save as new…", False))
            form = W.LayoutSaveForm(self.row, item)
            self.assertIsNone(form.item)
            self.assertIs(form.initial_focus, form.name)

    def test_shortcut_waits_for_data_then_opens_once(self):
        mod = switcher_module()
        opened = []
        host = NS(save_layout_requested=True, widgets=NS(gallery=None,
                  layouts=NS(doc=None, new_layout=lambda: opened.append(True))), say=lambda _: None)
        mod.Switcher.maybe_save_layout(host)
        host.widgets.layouts.doc = {"screen": {}}
        mod.Switcher.maybe_save_layout(host)
        self.assertEqual(opened, [])
        host.widgets.gallery = {"widgets": []}
        mod.Switcher.maybe_save_layout(host)
        mod.Switcher.maybe_save_layout(host)
        self.assertEqual(opened, [True])


class ForwardingTest(unittest.TestCase):
    def test_existing_window_receives_requested_tab_and_save_sheet(self):
        mod = switcher_module()
        events = []

        class App:
            chosen = None
            def __init__(self, **_kw): self.handlers = {}
            def add_main_option(self, *a): pass
            def connect(self, name, fn): self.handlers[name] = fn
            def run(self, _argv):
                for options in ({}, {"tab": "widgets"}, {"save-layout": True}, {}):
                    option_dict = NS(contains=lambda key: key in options,
                                     lookup_value=lambda key, _: NS(unpack=lambda: options[key]) if key in options else None)
                    self.handlers["command-line"](self, NS(get_options_dict=lambda: option_dict))

        class Switcher:
            def __init__(self, *a, **kw):
                self.tab, self.sel_name = kw["tab"], "wick"
                self.win = NS(present=lambda: events.append("present"))
            def fit(self): pass
            def select(self, *a, **kw): pass
            def show_tab(self, tab): events.append(tab)
            def request_save_layout(self): events.append("save")
            def close(self): events.append("close")
        glib = NS(OptionFlags=NS(NONE=0), OptionArg=NS(NONE=0, STRING=1),
                  idle_add=lambda fn: fn(), timeout_add=lambda *a: None)
        gio = NS(ApplicationFlags=NS(NON_UNIQUE=1, HANDLES_COMMAND_LINE=2))
        with patch.object(mod, "load_gtk", return_value=(NS(Application=App), None, gio, glib, None, None)), \
                patch.object(mod, "Switcher", Switcher), patch.object(mod, "focused_monitor", return_value=(1366, 768, None)), \
                patch.object(mod, "installed", return_value=[NS(name="wick", current=True)]):
            self.assertEqual(mod.run_window(), 0)
        self.assertIn("widgets", events)
        self.assertIn("save", events)
        self.assertEqual(events.count("close"), 1)


class GtkKeyboardTest(unittest.TestCase):
    @unittest.skipUnless(shutil.which("weston") and HAVE_GTK, "needs Weston and GTK 4's Python bindings")
    def test_keyboard_form_in_private_headless_display(self):
        with tempfile.TemporaryDirectory(prefix="blui-") as tmp:
            root = Path(tmp)
            for name in ("home", "run", "config", "cache", "data", "state"):
                (root / name).mkdir(mode=0o700)
            env = {"HOME": str(root / "home"), "XDG_RUNTIME_DIR": str(root / "run"),
                   "XDG_CONFIG_HOME": str(root / "config"), "XDG_CACHE_HOME": str(root / "cache"),
                   "XDG_DATA_HOME": str(root / "data"), "XDG_STATE_HOME": str(root / "state"),
                   "PATH": "/usr/bin:/bin", "LANG": "C.UTF-8", "GSK_RENDERER": "cairo",
                   "GDK_BACKEND": "wayland", "WAYLAND_DISPLAY": "layout-test", "NO_AT_BRIDGE": "1"}
            with (root / "weston.log").open("w") as log:
                proc = subprocess.Popen(["weston", "--backend=headless", "--renderer=pixman", "--shell=kiosk",
                                         "--width=1366", "--height=768", "--socket=layout-test", "--no-config",
                                         "--idle-time=0"], env=env, stdout=log, stderr=log)
                try:
                    deadline = time.monotonic() + 8
                    while not (root / "run/layout-test").is_socket() and time.monotonic() < deadline:
                        time.sleep(.05)
                    self.assertTrue((root / "run/layout-test").is_socket(), (root / "weston.log").read_text())
                    result = subprocess.run([sys.executable, __file__, "--gtk-driver"], env=env,
                                            capture_output=True, text=True, timeout=30)
                    self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                    self.assertIn("GTK layout flow passed", result.stdout)
                finally:
                    proc.terminate()
                    proc.wait(timeout=8)


def gtk_driver():
    mod = switcher_module()
    Gtk, Gdk, Gio, GLib, Pango, _ls = mod.load_gtk()
    Gtk.init()
    app = Gtk.Application(application_id="org.bromigos.LayoutTest", flags=Gio.ApplicationFlags.NON_UNIQUE)
    app.register(None)
    callbacks, requests = [], []
    item = {"id": "work", "title": "Work", "description": "For work", "source": "yours"}
    layouts = {"ok": True, "theme": "wick", "screen": {"monitor": "TEST-1", "width": 1366, "height": 768},
               "layouts": [{"id": f"preset-{i}", "title": f"Preset {i}", "description": "A starting point"}
                           for i in range(6)] + [item]}

    def fake_json(_ctx, argv, done, stdin=None):
        requests.append(argv)
        if argv[1:4] == ["panels", "layout", "save"]:
            callbacks.append(done)
        else:
            doc = layouts if argv[1] == "panels" and argv[2] == "layouts" else {"widgets": [], "results": []}
            GLib.idle_add(lambda: (done(doc, ""), False)[1])

    def pump():
        end = time.monotonic() + .12
        while time.monotonic() < end:
            while GLib.MainContext.default().pending():
                GLib.MainContext.default().iteration(False)
            time.sleep(.005)

    with patch.object(W.Ctx, "json", fake_json), patch.object(W.Ctx, "run", side_effect=AssertionError("external command")):
        sw = mod.Switcher(Gtk, Gdk, Gio, GLib, Pango, None, app, (1366, 768, None),
                          [mod.Entry("wick", "Wick", "", "den")], shot={"w": 1366, "h": 768}, tab="widgets")
        sw.win.present()
        sw.request_save_layout()
        pump()
        form = sw.sheet_form
        assert isinstance(form, W.LayoutSaveForm)
        assert form.name.is_ancestor(sw.win.get_focus()) or sw.win.get_focus().is_ancestor(form.name)
        assert sw.search.get_key_capture_widget() is None
        form.name.set_text("New desk")
        form.name.emit("activate")
        assert form.pending and not form.close_button.get_sensitive()
        sw._key(None, Gdk.KEY_Escape, 0, Gdk.ModifierType(0))
        assert sw.sheet_form is form
        callbacks.pop(0)({"ok": False, "error": "Choose another name"}, "failed")
        assert form.error.get_visible() and not form.pending
        form.name.set_text("New desk again")
        form.description.emit("activate")
        callbacks.pop(0)({"ok": True, "id": "work", "said": "Saved"}, "")
        pump()
        assert sw.sheet_form is None
        assert sw.win.get_focus() is sw.widgets.layouts.card_buttons["work"]
        assert sw.widgets.layouts.scroller.get_hadjustment().get_value() > 0
        sw.widgets.layouts.new_layout(item)
        pump()
        form = sw.sheet_form
        assert sw.win.get_focus() is form.cancel
        form.page.child_focus(Gtk.DirectionType.TAB_FORWARD)
        assert sw.win.get_focus() is form.save
        sw._key(None, Gdk.KEY_Escape, 0, Gdk.ModifierType(0))
        assert sw.sheet_form is None
        # Other sheets retain their original size and regain filter keyboard handling on close.
        sw.sheet(NS(page=Gtk.Box()), "Another form")
        assert sw.sheet_box.get_size_request() == (min(760, sw.g.w - 80), min(720, sw.g.h - 80))
        sw.close_sheet()
        assert sw.search.get_key_capture_widget() is sw.win
        assert not any("apply" in argv for argv in requests)
        sw.close()
    print("GTK layout flow passed")


if __name__ == "__main__":
    if "--gtk-driver" in sys.argv:
        gtk_driver()
    else:
        unittest.main()
