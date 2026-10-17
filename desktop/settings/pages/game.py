"""Game mode and its optional fullscreen detection."""
from gi.repository import GLib
from bromigos_settings import Entry, Page

CMD = ["bromigos", "game"]


class GamePage:
    def __init__(self, ctx):
        self.ctx = ctx
        self.page = ctx.page()
        self.page.set_reset(None, hint="Turn game mode off to restore the desktop")
        g = ctx.group(self.page, "Playing games", "Super+Ctrl+G turns it on. Ctrl+Shift+F12 always leaves it.")
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
        self.refresh()
        GLib.timeout_add_seconds(2, self.tick)

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


PAGE = Page(id="game", title="Playing games", group="desktop", order=65, build=build, refresh=refresh,
            docs="games.md", icon="input-gaming-symbolic", summary="game mode and fullscreen detection",
            intro="Give a game the keyboard and quiet the desktop until you leave game mode.",
            keywords=["games", "gaming", "wine", "lutris"],
            entries=[Entry("mode", "Game mode", ["game shortcuts", "keyboard"], "Playing games"),
                     Entry("auto", "Automatic game mode", ["fullscreen", "automatic games"], "Playing games")])
