"""Settings › Mascot: STATIC on, quiet or off (`bromigos mascot`, lib/bromigos_static.py).
On: he hosts Den TV and the media TUI. Quiet: his sprite and its faces, no thought
bubbles. Off: nowhere. The same switch as BRODEC's."""
from bromigos_settings import Entry, Page

MODES = [("on", "On"), ("quiet", "Quiet: his face, no thought bubbles"), ("off", "Off: nowhere")]


def build(ctx):
    page = ctx.page()
    group = ctx.group(page, "STATIC", "The Bromigos mascot. He hosts Den TV and the media library's channels. He's "
                                      "never on confirmations, passwords or alerts.", key="mascot")

    def got(doc, _err):
        cur = (doc or {}).get("mode") or "on"
        row = ctx.combo_row(group, "Mascot", key="mode", options=MODES, current=cur,
                            hint="On, quiet (his face but no thought bubbles) or off everywhere on this computer",
                            on_select=lambda v: ctx.change(["bromigos", "mascot", v, "--json"],
                                                           {"on": "STATIC is on", "quiet": "STATIC is quiet",
                                                            "off": "STATIC is off"}[v],
                                                           undo=["bromigos", "mascot", cur, "--json"]),
                            advanced={"file": (doc or {}).get("file", "~/.config/bromigos/mascot.toml"),
                                      "runs": "bromigos mascot on|quiet|off"})
        art = (doc or {}).get("art") or {}
        ctx.row(group, "His art", "Rendered frames from " + art["folders"][0] if art.get("names") else
                "The placeholder drawn in code, until rendered art is installed", key="art",
                hint="Where STATIC's pictures come from: an art folder with a manifest.json, else the placeholder")
        return row
    ctx.json(["bromigos", "mascot", "--json"], got)
    return page


PAGE = Page(id="mascot", title="Mascot", group="desktop", order=47, build=build,
            docs="settings.md#den-tv", icon="face-smile-symbolic", summary="STATIC on, quiet or off",
            intro="STATIC, the Bromigos mascot: on, quiet or off on this computer.",
            keywords=["static", "mascot", "character", "quiet", "turn off", "den tv"],
            entries=[Entry("mascot", "The mascot", ["static"], "STATIC"),
                     Entry("mode", "Mascot on, quiet or off", ["static", "quiet", "off"], "STATIC")])
