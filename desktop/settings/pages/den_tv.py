"""Den TV's few playback settings; the channel guide has its own app."""
from bromigos_settings import Entry, Page


def build(ctx):
    page = ctx.page()
    group = ctx.group(page, "Den TV", "The animated den's screens can play your media.", key="playback")
    def got(doc, error):
        vals = (doc or {}).get('values') or {}
        def change(key, value):
            ctx.change(['bromigos','scene','set',key,str(value).lower()], 'Den TV updated')
        ctx.switch_row(group, "Den TV", "Play media on the den's screens", key="enabled",
            active=vals.get('tv.enabled',True), hint="Turn media playback off or on",
            on_toggle=lambda v: change('tv.enabled',v))
        ctx.switch_row(group, "Floating controls on hover", "Off leaves the MEDIA widget and number-pad remote",
            key="hover-hint", active=vals.get('tv.hover_hint',True), hint="Show the floating TV controls",
            on_toggle=lambda v: change('tv.hover_hint',v))
        ctx.combo_row(group, "Screens playing at once", key="max-playing", options=[(n, str(n)) for n in (1,2,3)],
            current=vals.get('tv.max_playing',3), hint="Limit how many screens decode video at the same time",
            on_select=lambda v: change('tv.max_playing',v))
        ctx.scale_row(group, "Pause under windows", key="cover-opacity", lo=0,hi=1,step=.05,
            value=vals.get('tv.cover_opacity',.9), hint="Pause a silent screen when a window at least this opaque covers it",
            on_change=lambda v: change('tv.cover_opacity',round(v,2)))
    ctx.json(['bromigos','scene','get','tv.enabled','tv.hover_hint','tv.max_playing','tv.cover_opacity','--json'],got)
    ctx.row(group, "Channels and guide", key="guide", hint="Open the standalone Den TV app",
            buttons=[("Open Den TV…",lambda: ctx.launch(['bromigos-tv-guide']),"Every channel and what's on")])
    return page


PAGE = Page(id="den-tv",title="Den TV",group="desktop",order=46,build=build,
    docs="themes-and-worlds.md#the-den-tv",icon="video-display-symbolic",
    summary="Playback settings and the Den TV app",intro="Set how the den plays media. Open Den TV to manage channels.",
    keywords=["tv","den","channels","guide"],entries=[
        Entry('playback','Den TV playback',[], 'Den TV'), Entry('enabled','Den TV on or off',[], 'Den TV'),
        Entry('hover-hint','Floating TV controls',[], 'Den TV'),Entry('max-playing','Screens playing at once',[], 'Den TV'),Entry('cover-opacity','Picture opacity',[], 'Den TV'),
        Entry('guide','Open Den TV',[], 'Den TV')])
