"""The live desktop's welcome card (bromigos-iso-autostart, when the medium was started to try
it): two big choices, Try bromigOS or Install bromigOS, each with what it means. A small
floating GLOW panel in the Settings style; the emblem is its one FLARE, still when motion is
reduced. Install opens the graphical installer; Try closes the card (the app launcher's
"Install bromigOS" and the desktop's Install panel open the installer later).

  python3 -m bromigos_installer.welcome [--render OUT.png]
"""
import os
import subprocess
import sys

if __package__ in (None, ""):
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.realpath(__file__))))
    __package__ = "bromigos_installer"

import gi  # noqa: E402

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gdk, GLib, Gtk  # noqa: E402

from . import common  # noqa: E402
from .gui import Emblem, hint, installer_css, label, settings_css, snapshot  # noqa: E402

TRY = ("Try bromigOS", "Look around first. Everything runs from this USB stick: nothing is installed and nothing on "
                       "this computer changes. You can install from the desktop at any time.")
INSTALL = ("Install bromigOS", "Put bromigOS on this computer's disk, on its own or beside Windows. About ten minutes, "
                               "and nothing changes until you've checked a summary.")


class Card(Adw.ApplicationWindow):
    def __init__(self, app, render=None):
        super().__init__(application=app, title="Welcome to bromigOS")
        self.set_default_size(760, 470)
        self.set_resizable(False)
        css = Gtk.CssProvider()
        c, _ = common.theme()
        css.load_from_string(settings_css(c) + installer_css(c) + f"""
.bw-choice {{ padding: 18px 20px; }}
.bw-choice .bw-title {{ font-size: 1.25em; font-weight: 700; letter-spacing: 0.1em; }}
.bw-choice .bw-what {{ font-size: 0.92em; }}
""")
        Gtk.StyleContext.add_provider_for_display(Gdk.Display.get_default(), css, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=18, margin_top=26, margin_bottom=26, margin_start=30, margin_end=30)
        top = Gtk.Box(spacing=20)
        top.append(Emblem(96, common.reduced_motion() or bool(render)))
        words = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6, valign=Gtk.Align.CENTER)
        words.append(label("WELCOME TO BROMIGOS", ("bi-heading",)))
        words.append(label("You started bromigOS from a USB stick. What would you like to do?", ("bi-intro",)))
        top.append(words)
        box.append(top)
        row = Gtk.Box(spacing=16, homogeneous=True, vexpand=True)
        for (title, what), primary, act in ((TRY, False, self.on_try), (INSTALL, True, self.on_install)):
            b = Gtk.Button()
            b.add_css_class("bw-choice")
            if primary:
                b.add_css_class("suggested-action")
            inner = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
            inner.append(label(title.upper(), ("bw-title",)))
            inner.append(label(what, ("bw-what",)))
            b.set_child(inner)
            hint(b, f"{title}: {what}")
            b.update_property([Gtk.AccessibleProperty.LABEL], [title])
            b.connect("clicked", act)
            row.append(b)
            if primary:
                self.set_default_widget(b)
                GLib.idle_add(b.grab_focus)
        box.append(row)
        box.append(label("The installer is also in the app launcher (Super+Space): Install bromigOS.", ("bi-intro",)))
        self.set_content(box)
        if render:
            GLib.timeout_add(900, lambda: (snapshot(self, render), app.quit(), False)[-1])

    def on_try(self, *_):
        self.close()

    def on_install(self, *_):
        subprocess.Popen(["/usr/local/bin/bromigos-installer"], start_new_session=True)
        self.close()


class App(Adw.Application):
    def __init__(self, render=None):
        super().__init__(application_id="org.bromigos.InstallerWelcome")
        self.render = render

    def do_activate(self):
        (self.get_active_window() or Card(self, self.render)).present()


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    render = argv[argv.index("--render") + 1] if "--render" in argv else None
    return App(render).run([])


if __name__ == "__main__":
    sys.exit(main())
