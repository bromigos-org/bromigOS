"""bromigOS Settings (`bromigos settings`, SUPER+,): one window for the desktop's settings,
in the theme's colours. GTK4 and libadwaita, themed from the theme's palette.json.

The window is a sidebar of pages. Pages come from a registry (registry.py), so any
package, extension or user adds one by dropping a module in a folder:

    from bromigos_settings import Page

    def build(ctx):                       # ctx: bromigos_settings.Context
        page = ctx.page()                 # an Adw.PreferencesPage in the house style
        g = ctx.group(page, "SOUND", "What the desktop says out loud")
        ctx.row(g, "Mute everything", "the theme's sounds and VECTOR's voice",
                hint="Runs `bromigos mute toggle`", button=("Toggle", lambda: ctx.run(["bromigos", "mute", "toggle"])))
        return page

    PAGE = Page(id="sound", title="Sound", icon="audio-volume-high-symbolic", order=30,
                group="system", summary="mute, voices", build=build,
                entries=[Entry("mute", "Mute everything", ["silence"])])

docs/settings.md is the page author's guide; the app is app.py.
"""
from .registry import Entry, GROUPS, Page, Section, discover, page_dirs  # noqa: F401


def __getattr__(name):
    # the toolkit only when a window is made: the registry and the search load without it
    if name == "Context":
        from .context import Context
        return Context
    raise AttributeError(name)

APP_ID = "org.bromigos.Settings"
