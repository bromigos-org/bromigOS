"""Live layer & holograms: the animated background and its switches, the theme's world, the
screensaver's content, the codec's calls, the frame rates, and the decks on their keys
(docs/settings.md, "Live layer and holograms").

The switches are `bromigos anim` (one per animation), the rest `bromigos scene` (the live
layer's settings in ~/.config/bromigos/live/overrides.toml); the live layer reads them again
by itself. The background on/off is `bromigos live on|off` (now, until the next login); the
decks' keys are `bromigos keys` (unbind, put back). Each change toasts Undo."""
import json
import os
import tomllib

from gi.repository import GLib

from bromigos_settings import Entry, Page

ANIM = ["bromigos", "anim"]
SCENE = ["bromigos", "scene"]
KEYS = ["bromigos", "keys"]
BACKGROUND = ["den", "streaks", "rows", "stars", "ships", "beam", "tint", "rain", "pulses", "sweep"]
EVENTS = ["bursts", "intercept", "flash", "wipe"]
TITLES = {"den": "The den's screens", "streaks": "Glitch streaks", "rows": "Floor rows", "rain": "Glyph rain",
          "bursts": "Rain bursts", "pulses": "Traffic pulses", "sweep": "The scanner's sweep", "stars": "Stars",
          "ships": "Ships and debris", "beam": "The station's beam", "tint": "Lab-health tint",
          "intercept": "The burn-in intercept", "flash": "Critical flash", "wipe": "Workspace wipe",
          "codec": "Codec calls", "screensaver": "Screensaver", "sounds": "Sound cues"}
DECKISH = ("deck", "holo", "timeline", "drift map", "radial", "gallery", "swarm", "scanner", "codec",
           "live background", "ops theater", "network map", "mind")
STATE = os.environ.get("XDG_STATE_HOME") or os.path.expanduser("~/.local/state")
CURRENT = os.path.join(STATE, "bromigos", "theme", "current")


def world():
    """The theme in force's world (its live/world.toml), or None: the den."""
    try:
        with open(os.path.join(CURRENT, "palette.json")) as f:
            theme = json.load(f).get("name") or "the theme"
    except (OSError, ValueError):
        theme = "the theme"
    try:
        with open(os.path.join(CURRENT, "live", "world.toml"), "rb") as f:
            w = tomllib.load(f)
    except (OSError, ValueError):
        return {"theme": theme, "world": None}
    return {"theme": theme, "world": w.get("name") or theme, "parallax": (w.get("camera") or {}).get("parallax", "off"),
            "water": (w.get("water") or {}).get("mode"), "actors": len(w.get("actors") or []),
            "effects": [e.get("type") for e in w.get("effects") or []]}


class LivePage:
    def __init__(self, ctx):
        self.ctx = ctx
        self.page = ctx.page()
        self.page.set_reset(self.reset, what="Every animation switch on again as bromigOS ships it, and the world, the "
                                             "screensaver's content, the codec and the frame rates back to their "
                                             "defaults. The decks' keys aren't touched (Shortcuts resets those).")
        self.anims, self.scene, self.status, self.keys = None, None, None, None
        self.groups = []
        g = ctx.group(self.page, "The live background")
        self.groups.append(g)
        ctx.loading(g, "Reading the live layer…")
        self.refresh()

    def refresh(self):
        self.ctx.json(["bromigos", "status", "--json"], lambda d, e: self._got("status", d, e))
        self.ctx.json(ANIM + ["--json"], lambda d, e: self._got("anims", d, e))
        self.ctx.json(SCENE + ["--json"], lambda d, e: self._got("scene", d, e))
        self.ctx.json(KEYS + ["list", "--all", "--json"], lambda d, e: self._got("keys", d, e))

    def _got(self, what, doc, err):
        setattr(self, what, doc if doc and doc.get("ok", True) is not False else {"_error": (doc or {}).get("error") or err or "no answer"})
        if None not in (self.anims, self.scene, self.status, self.keys):
            self.sync()

    def _clear(self):
        for g in self.groups:
            self.page.remove_group(g)
        self.groups = []

    def _group(self, title, desc=None, hint=None, key=None):
        g = self.ctx.group(self.page, title, desc, hint, key=key)
        self.groups.append(g)
        return g

    # ------------------------------------------------------------------ building
    def sync(self):
        ctx = self.ctx
        self._clear()
        anims = {a["name"]: a for a in (self.anims or {}).get("animations") or []}
        scene = (self.scene or {}).get("values") or {}
        scene_file = (self.scene or {}).get("file") or "~/.config/bromigos/live/overrides.toml"
        live = (self.status or {}).get("live") or {}

        g = self._group("The live background", "The animated scene behind your windows.", key="background")
        running = bool(live.get("running"))
        bg = live.get("background")
        r = ctx.switch_row(g, "Live background", "Now, until the next login (SUPER+SHIFT+B)" if running
                           else "The live layer isn't running", active=running and bg != "off", key="live-on",
                           hint="Turns the whole animated background off or on now (bromigos live on|off); "
                                "it's on again at the next login",
                           on_toggle=self._live_on, advanced={"runs": "bromigos live on|off"})
        r.set_sensitive(running)
        if not running:
            ctx.row(g, "Start the live layer", "bromigos-live start (login starts it)", key="live-start",
                    hint="Starts the live layer now in this session",
                    buttons=[("Start", lambda: (ctx.launch(["bromigos-live", "start"]),
                                                GLib.timeout_add_seconds(3, lambda: (self.refresh(), False)[1])),
                              "Starts the live layer")])
        if (self.anims or {}).get("_error"):
            ctx.failed(g, ANIM + ["--json"], self.anims["_error"])
        for name in BACKGROUND + [n for n in anims if n not in BACKGROUND + EVENTS + ["codec", "screensaver", "sounds"]]:
            if name in anims:
                self._anim(g, anims[name])

        w = world()
        g = self._group("The world", "A theme with a world draws it instead of the den: its keeper and creatures "
                                     "follow your activity.", key="world")
        if w["world"]:
            facts = f"{w['world']} ({w['theme']}): " + ", ".join(filter(None, [
                f"{w['actors']} creatures and craft" if w["actors"] else "",
                "the camera sways with the pointer" if w["parallax"] == "cursor" else "a still camera",
                f"{w['water']} water" if w.get("water") else ""]))
        else:
            facts = f"{w['theme']} has no world: the den is drawn"
        ctx.row(g, "This theme's world", facts, hint="From the theme's live/world.toml (Settings › Theme changes the theme)")
        self._scene_switch(g, "world.enabled", "Draw the world", "Off: always the den, whatever the theme",
                           scene, scene_file, key="world-on")
        self._scene_switch(g, "world.ambient_sounds", "The world's sounds", "Its creatures' sounds, by your activity "
                           "(the mute and the cue volume apply)", scene, scene_file, key="world-sounds")
        ctx.row(g, "Creatures doze", "When the keeper and the creatures doze: Idle & lock", key="doze",
                hint="Opens Idle & lock, where the creatures' doze timer is",
                activate=lambda: ctx.open_page("idle"))

        g = self._group("Events", "Real events, shown on the background.", key="events")
        for name in EVENTS:
            if name in anims:
                self._anim(g, anims[name])

        g = self._group("The screensaver", "Opens after the idle policy's time (Settings › Idle and lock).", key="screensaver")
        if "screensaver" in anims:
            self._anim(g, anims["screensaver"], title="Screensaver")
        self._scene_switch(g, "space.planet", "The gas giant", "Its terminator is your local time of day",
                           scene, scene_file, key="planet")
        self._scene_switch(g, "space.station", "The relay station", "Its spokes are your lab's services, lit when up",
                           scene, scene_file, key="station")
        ctx.row(g, "Try it", "Opens the screensaver now; any key or mouse movement ends it", key="try",
                hint="Opens the screensaver a second after you click (so the click doesn't end it)",
                buttons=[("Try the screensaver now", self._try, "Opens the screensaver now")],
                advanced={"runs": "bromigos-live ctl screensaver open"})

        g = self._group("The codec", "Important events as a short voiced transmission, bottom right.", key="codec")
        if "codec" in anims:
            self._anim(g, anims["codec"], title="Codec calls")
        self._scene_switch(g, "codec.on_critical", "Critical notifications", "A call for each one", scene, scene_file,
                           key="codec-critical")
        self._scene_switch(g, "codec.on_lab_alert", "The lab's alerts", "A call when alerts go up or a node leaves",
                           scene, scene_file, key="codec-lab")
        self._scene_scale(g, "codec.max_per_hour", "At most, an hour", 0, 60, 1, lambda v: f"{int(v)} calls", scene,
                          scene_file, key="codec-rate")

        g = self._group("Frame rate", "How often it draws: lower costs less.", key="fps")
        self._scene_scale(g, "general.fps", "With the desktop showing", 5, 60, 1, lambda v: f"{int(v)} fps", scene,
                          scene_file, key="fps-visible")
        self._scene_scale(g, "general.fps_covered", "Under tiled windows", 1, 60, 1, lambda v: f"{int(v)} fps", scene,
                          scene_file, key="fps-covered")
        ctx.row(g, "Sounds", "The cues' on/off and volume: Sound", key="sounds-link",
                hint="Opens Sound, where the desktop's cues and the mute are", activate=lambda: ctx.open_page("sound"))

        self._decks()

    def _anim(self, g, a, title=None):
        name = a["name"]
        t = title or TITLES.get(name) or (a["description"][:1].upper() + a["description"][1:]).split(" (")[0]
        files = ", ".join(f"[{k['section']}] {k['key']}" for k in a.get("keys") or [])
        desc = a["description"] if a.get("description") and a["description"] != name else name
        self.ctx.switch_row(g, t, desc + (" · yours" if a.get("overridden") else ""), active=a["on"],
                            key=f"anim-{name}", hint=f"{a['description']} (bromigos anim on|off {name})",
                            on_toggle=lambda on, n=name, tt=t: self._change(
                                ANIM + ["on" if on else "off", n, "--json"], f"{tt}: {'on' if on else 'off'}",
                                ANIM + ["off" if on else "on", n, "--json"]),
                            advanced={"file": "~/.config/bromigos/live/overrides.toml", "key": files,
                                      "runs": f"bromigos anim on|off {name}"})

    def _scene_switch(self, g, setting, title, sub, scene, file, key=None):
        cur = scene.get(setting)
        r = self.ctx.switch_row(g, title, sub, active=bool(cur), key=key,
                                hint=f"{title}: on or off (bromigos scene {setting})",
                                on_toggle=lambda on: self._change(SCENE + ["set", setting, "on" if on else "off", "--json"],
                                                                  f"{title}: {'on' if on else 'off'}",
                                                                  SCENE + ["set", setting, "off" if on else "on", "--json"]),
                                advanced={"file": file, "key": setting, "runs": f"bromigos scene set {setting} on|off"})
        if cur is None:
            r.set_sensitive(False)
        return r

    def _scene_scale(self, g, setting, title, lo, hi, step, fmt, scene, file, key=None):
        cur = scene.get(setting)
        r = self.ctx.scale_row(g, title, "", lo=lo, hi=hi, step=step, value=cur if cur is not None else lo, fmt=fmt,
                               key=key, hint=f"Drag: {title.lower()} ({lo} to {hi}); applies as you let go",
                               on_change=lambda v: self._change(SCENE + ["set", setting, str(int(v)), "--json"],
                                                                f"{title}: {fmt(v)}",
                                                                SCENE + ["set", setting, str(cur), "--json"] if cur is not None else None),
                               advanced={"file": file, "key": setting, "runs": f"bromigos scene set {setting} N"})
        if cur is None:
            r.set_sensitive(False)
        return r

    def _decks(self):
        ctx = self.ctx
        g = self._group("Decks on their keys", "The holograms and the live layer's keys: off frees the key "
                                               "(Shortcuts moves one to another key).", key="decks")
        k = self.keys or {}
        if k.get("_error"):
            ctx.failed(g, KEYS + ["list", "--all", "--json"], k["_error"])
            return
        rows = [r for r in k.get("all") or [] if r.get("section") in ("HOLOGRAMS", "LIVE LAYER")]
        off = [o for o in k.get("off") or [] if any(w in (o.get("what") or "").lower() for w in DECKISH)]
        for r in rows:
            mov = r.get("movable")
            s = ctx.switch_row(g, r["what"], r["display"] + ("" if r.get("source") == "default" else " · yours"),
                               active=True, key=f"deck-{r['keys']}",
                               hint=f"{r['what']} on {r['display']}: off unbinds the key" if mov
                               else (r.get("why") or "Not changed from here"),
                               on_toggle=lambda on, r=r: self._deck(r, on),
                               advanced={"file": "~/.config/bromigos/keys.toml", "key": r["keys"],
                                         "runs": f"bromigos keys unbind \"{r['keys']}\""})
            s.set_sensitive(bool(mov))
        for o in off:
            ctx.switch_row(g, o["what"], f"was {o['display']} · off", active=False, key=f"deck-{o['keys']}",
                           hint=f"{o['what']} has no key: on puts it back on {o['display']}",
                           on_toggle=lambda on, o=o: self._deck(o, on),
                           advanced={"file": "~/.config/bromigos/keys.toml", "key": o["keys"],
                                     "runs": f"bromigos keys reset \"{o['keys']}\""})
        if not rows and not off:
            ctx.row(g, "No deck keys found", "bromigos keys lists none in the HOLOGRAMS or LIVE LAYER sections",
                    hint="The keys come from your hyprland.lua and bromigOS's defaults")
        ctx.row(g, "Every key", "Shortcuts: change any key, put defaults back", key="shortcuts-link",
                hint="Opens Shortcuts", activate=lambda: ctx.open_page("shortcuts"))

    # ------------------------------------------------------------------ changes
    def _change(self, argv, said, undo):
        self.ctx.change(argv, said, undo=undo, done=lambda _d: self.refresh(), failed=lambda *_: self.refresh())

    def _deck(self, r, on):
        argv = KEYS + (["reset", r["keys"]] if on else ["unbind", r["keys"]]) + ["--json"]
        self.ctx.change(argv, lambda d: "; ".join(d.get("notes") or [d.get("detail") or
                                                                     f"{r['what']}: {'on' if on else 'off'}"])[:160],
                        undo=KEYS + ["undo", "--json"], done=lambda _d: self.refresh(),
                        failed=lambda *_: self.refresh())

    def _live_on(self, on):
        def done(ok, out, err):
            said = (out or err).strip().splitlines()
            if ok:
                self.ctx.toast(f"Live background {'on' if on else 'off'}",
                               undo=lambda: self.ctx.run(["bromigos", "live", "off" if on else "on"],
                                                         lambda *_: self.refresh()))
            else:
                self.ctx.toast("Not changed: " + (said[-1] if said else "bromigos live failed"))
            self.refresh()
        self.ctx.run(["bromigos", "live", "on" if on else "off"], done)

    def _try(self):
        def go():
            def done(ok, out, err):
                said = (out or err).strip()
                if not ok or "disabled" in said:
                    self.ctx.toast("The screensaver didn't open: " + (said or "is the live layer running? (bromigos live)"))
            self.ctx.run(["bromigos-live", "ctl", "screensaver", "open"], done)
            return False
        GLib.timeout_add(900, go)

    def reset(self):
        self.ctx.change(ANIM + ["reset", "--json"], "Every animation as bromigOS ships it",
                        done=lambda _d: self.ctx.change(SCENE + ["reset", "--json"], "The live layer: back to the defaults",
                                                        done=lambda _d: self.refresh()))


def build(ctx):
    p = LivePage(ctx)
    p.page._live = p
    return p.page


def refresh(widget):
    widget._live.refresh()


PAGE = Page(
    id="live", title="Live layer & holograms", group="desktop", order=22, build=build, refresh=refresh,
    docs="settings.md#live-layer-and-holograms", icon="weather-clear-night-symbolic video-display-symbolic",
    summary="background, world, screensaver, decks",
    intro="The animated background and what moves on it, the theme's world, the screensaver, the codec's calls and "
          "the decks on their keys. A change applies at once.",
    keywords=["live background", "animated wallpaper", "animations", "bromigos-live", "holo deck", "holograms"],
    entries=[
        Entry("background", "Animations", ["animation switches", "rain", "stars", "ships", "den"], "The live background"),
        Entry("live-on", "Live background on or off", ["SUPER+SHIFT+B", "animated background off"], "The live background"),
        Entry("world", "The world", ["theme world", "creatures", "keeper"], "The world"),
        Entry("world-on", "Draw the world", ["world off", "den instead"], "The world"),
        Entry("world-sounds", "The world's sounds", ["ambient sounds", "creature sounds"], "The world"),
        Entry("events", "Event effects", ["flash", "intercept", "bursts", "wipe"], "Events"),
        Entry("screensaver", "The screensaver", ["screen saver", "saver content"], "The screensaver"),
        Entry("planet", "The screensaver's gas giant", ["planet"], "The screensaver"),
        Entry("station", "The screensaver's relay station", ["station"], "The screensaver"),
        Entry("try", "Try the screensaver", ["preview screensaver"], "The screensaver"),
        Entry("codec", "Codec calls", ["voiced events", "transmission"], "The codec"),
        Entry("codec-rate", "Codec calls an hour", ["how often", "rate limit"], "The codec"),
        Entry("fps", "Frame rate", ["fps", "performance", "battery"], "Frame rate"),
        Entry("decks", "Decks on their keys", ["holo deck key", "timeline key", "drift map", "radial", "gallery",
                                               "SUPER+H", "SUPER+T"], "Decks on their keys"),
    ])
