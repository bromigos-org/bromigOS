"""Sound: the output and input device, their volumes, each app's volume and output, the
theme's sound cues and the desktop's one mute (docs/settings.md, "Sound").

Everything goes through `bromigos sound … --json` (PipeWire through pactl; the mute is
`bromigos mute`, the cues `bromigos anim` and `bromigos scene`): a change applies at
once and toasts Undo. The page reads the state again every few seconds while it's shown,
so the volume keys and other mixers show up here."""
from gi.repository import GLib, Gtk

from bromigos_settings import Entry, Page

SOUND = ["bromigos", "sound"]
KIND_ICON = {"speakers": "audio-speakers-symbolic", "headphones": "audio-headphones-symbolic",
             "bluetooth": "bluetooth-active-symbolic", "display": "video-display-symbolic",
             "usb": "media-removable-symbolic", "microphone": "audio-input-microphone-symbolic",
             "virtual": "audio-card-symbolic"}


def _label(d):
    kind = {"display": "a display", "bluetooth": "Bluetooth", "usb": "USB", "headphones": "headphones",
            "virtual": "virtual"}.get(d["kind"], "")
    return d["description"] + (f"  ({kind})" if kind else "")


class SoundPage:
    def __init__(self, ctx):
        self.ctx = ctx
        self.doc = None
        self.sig = {}
        self.page = ctx.page()
        self.page.set_reset(self.reset, what="The theme's sound cues on, at their default volume. Your devices and "
                                             "their volumes are this machine's own and stay as they are.")
        self._build_static()
        self.refresh()
        GLib.timeout_add_seconds(4, self._tick)

    # ------------------------------------------------------------------ building
    def _build_static(self):
        ctx = self.ctx
        self.out_group = ctx.group(self.page, "Output", "Where the desktop's sound plays.", key="output-group")
        self.out_rows = []
        self.in_group = ctx.group(self.page, "Input", "The microphone apps and VECTOR's hearing use.", key="input-group")
        self.in_rows = []
        self.app_group = ctx.group(self.page, "Apps", "Each app playing now: its own volume, and where it plays.",
                                   key="apps")
        self.app_rows = []
        g = ctx.group(self.page, "The desktop's sounds", "The theme's cues and VECTOR's voice.")
        self.mute_row = ctx.switch_row(
            g, "Mute everything", "The theme's sounds and VECTOR's voice together (SUPER+SHIFT+M)",
            hint="The desktop's one mute (bromigos mute): the theme's cues and VECTOR's voice; apps' sound "
                 "isn't touched", key="mute-all", on_toggle=self._mute_all,
            advanced={"runs": "bromigos mute on|off", "file": "~/.local/state/bromigos-live/muted",
                      "note": "and VECTOR's ~/.local/state/bromigos/vector-voice-muted"})
        self.cues_row = ctx.switch_row(
            g, "Sound cues", "The terminal's blip, the notification chirp, the scanner's sweep",
            hint="The live layer's sound cues on or off (bromigos anim sounds)", key="cues",
            on_toggle=self._cues,
            advanced={"file": "~/.config/bromigos/live/overrides.toml", "key": "[sounds] enabled",
                      "runs": "bromigos sound sounds on|off"})
        self.cues_volume = ctx.scale_row(
            g, "Cue volume", "How loud the cues are (keep it low)", lo=0, hi=100, step=5, value=30,
            fmt=lambda v: f"{int(v)}%", key="cues-volume", on_change=self._cues_volume,
            hint="Drag: the cues' loudness, 0 to 100% (applies as you let go)",
            advanced={"file": "~/.config/bromigos/live/overrides.toml", "key": "[sounds] volume",
                      "runs": "bromigos sound sounds-volume PERCENT"})
        ctx.row(g, "The world's sounds", "Creature sounds and the codec's calls: Live layer & holograms",
                hint="Opens Live layer & holograms, where the world's ambient sounds and the codec are",
                activate=lambda: ctx.open_page("live"), key="world-sounds")
        self.problem = None

    def _sig(self, d):
        return {"out": tuple((x["name"], tuple(p["name"] for p in x["ports"])) for x in d["output"]["devices"]),
                "in": tuple(x["name"] for x in d["input"]["devices"]),
                "apps": tuple((a["id"], a["app"]) for a in d["apps"])}

    def _device_rows(self, side, group, rows):
        ctx = self.ctx
        ctx.clear_group(group, rows)
        devs = self.doc[side]["devices"]
        if not devs:
            rows.append(ctx.note(group, f"No {side} device: nothing to {'play on' if side == 'output' else 'record from'}",
                                 "warn", hint="PipeWire sees no device of this kind"))
            return
        word = "Output" if side == "output" else "Input"
        combo = ctx.combo_row(
            group, f"{word} device", "", options=[(d["name"], _label(d)) for d in devs],
            current=self.doc[side]["default"], key=side, on_select=lambda n, s=side: self._default(s, n),
            hint=f"The default {side}: {'apps play' if side == 'output' else 'apps record'} through it; "
                 f"{'playing apps move to it' if side == 'output' else 'the microphone in use moves too'}",
            advanced={"runs": f"bromigos sound {side} DEVICE",
                      "note": f"pactl set-default-{'sink' if side == 'output' else 'source'}"})
        rows.append(combo)
        vol = ctx.scale_row(
            group, "Volume" if side == "output" else "Input volume", "", lo=0, hi=150, step=1, value=0,
            fmt=lambda v: f"{int(v)}%", marks=(100,), key=f"{side}-volume",
            on_change=lambda v, s=side: self._volume(s, v),
            hint=f"Drag: the {side} device's volume, 0 to 150% (over 100% amplifies and may distort)",
            advanced={"runs": f"bromigos sound volume {side} PERCENT"})
        mute = Gtk.ToggleButton(icon_name="audio-volume-muted-symbolic", valign=Gtk.Align.CENTER)
        mute.add_css_class("flat")
        ctx.hint(mute, f"Mutes or unmutes the {side} device")
        mute._quiet = False
        mute.connect("toggled", lambda b, s=side: (not b._quiet) and self._mute(s, b.get_active()))
        vol.add_suffix(mute)
        vol.mute_button = mute
        rows.append(vol)
        setattr(self, f"{side}_combo", combo)
        setattr(self, f"{side}_volume", vol)
        cur = next((d for d in devs if d["default"]), None)
        port = None
        if cur and len(cur["ports"]) > 1:
            port = ctx.combo_row(
                group, "Port", "Which connector on this device: speakers, headphones, line out",
                options=[(p["name"], p["description"] + ("" if p["available"] else " (unplugged)"))
                         for p in cur["ports"]], current=cur["active_port"], key=f"{side}-port",
                on_select=lambda p, s=side, n=cur["name"]: self._port(s, n, p),
                hint="The device's connector in use", advanced={"runs": f"bromigos sound port {side} DEVICE PORT"})
            rows.append(port)
        setattr(self, f"{side}_port", port)
        if side == "output":
            rows.append(ctx.row(group, "Test", "Plays a short cue on this output", key="test",
                                hint="Plays the notification chirp on the output device",
                                buttons=[("Play", self._test, "Plays a cue now")],
                                advanced={"runs": "bromigos sound test"}))

    def _app_rows(self):
        ctx = self.ctx
        ctx.clear_group(self.app_group, self.app_rows)
        self.app_widgets = {}
        apps = self.doc["apps"]
        if not apps:
            r = ctx.row(self.app_group, "Nothing is playing", "An app playing sound shows here with its own volume",
                        hint="No app has a sound stream open now")
            self.app_rows.append(r)
            return
        outs = [(d["name"], d["description"]) for d in self.doc["output"]["devices"]]
        for a in apps:
            r = ctx.scale_row(self.app_group, a["app"], a["title"], lo=0, hi=150, step=1, value=a["volume"],
                              fmt=lambda v: f"{int(v)}%", marks=(100,), width=120,
                              on_change=lambda v, i=a["id"], n=a["app"]: self._app_volume(i, n, v),
                              hint=f"{a['app']}'s own volume (on top of the device's)",
                              advanced={"runs": f"bromigos sound app-volume {a['id']} PERCENT"})
            r.add_prefix(ctx.icon(a.get("icon"), a.get("binary"), "audio-x-generic-symbolic"))
            mute = Gtk.ToggleButton(icon_name="audio-volume-muted-symbolic", valign=Gtk.Align.CENTER, active=a["muted"])
            mute.add_css_class("flat")
            mute._quiet = False
            ctx.hint(mute, f"Mutes or unmutes {a['app']}")
            mute.connect("toggled", lambda b, i=a["id"], n=a["app"]: (not b._quiet) and self._app_mute(i, n, b.get_active()))
            r.add_suffix(mute)
            if len(outs) > 1:
                r.add_suffix(ctx.dropdown(outs, a["output"], hint=f"Where {a['app']} plays",
                                          on_select=lambda dev, i=a["id"], n=a["app"]: self._app_output(i, n, dev)))
            self.app_rows.append(r)
            self.app_widgets[a["id"]] = (r, mute)

    # ------------------------------------------------------------------ state
    def refresh(self):
        self.ctx.json(SOUND + ["--json"], self._got)

    def _tick(self):
        if self.page.get_mapped():
            self.refresh()
        return True

    def _got(self, doc, err):
        if not doc or doc.get("ok") is False:
            why = (doc or {}).get("error") or err
            if self.problem is None:
                self.problem = self.ctx.failed(self.out_group, SOUND + ["--json"], why)
            return
        if self.problem is not None:
            self.out_group.remove(self.problem)
            self.problem = None
        self.sync(doc)

    def sync(self, d):
        self.doc = d
        sig = self._sig(d)
        if sig["out"] != self.sig.get("out"):
            self._device_rows("output", self.out_group, self.out_rows)
        if sig["in"] != self.sig.get("in"):
            self._device_rows("input", self.in_group, self.in_rows)
        if sig["apps"] != self.sig.get("apps") or sig["out"] != self.sig.get("out"):
            self._app_rows()
        self.sig = sig
        for side in ("output", "input"):
            devs = d[side]["devices"]
            cur = next((x for x in devs if x["default"]), None)
            if cur is None or getattr(self, f"{side}_combo", None) is None:
                continue
            getattr(self, f"{side}_combo").set_quiet(cur["name"])
            vol = getattr(self, f"{side}_volume")
            vol.set_quiet(cur["volume"])
            vol.mute_button._quiet = True
            vol.mute_button.set_active(cur["muted"])
            vol.mute_button._quiet = False
            vol.set_subtitle(GLib.markup_escape_text(_label(cur) + (" · muted" if cur["muted"] else "")))
            port = getattr(self, f"{side}_port", None)
            if port is not None and cur["active_port"]:
                port.set_quiet(cur["active_port"])
        for a in d["apps"]:
            w = getattr(self, "app_widgets", {}).get(a["id"])
            if w:
                w[0].set_quiet(a["volume"])
                w[1]._quiet = True
                w[1].set_active(a["muted"])
                w[1]._quiet = False
        m = d.get("mute") or {}
        self.mute_row.set_quiet(bool(m.get("muted")))
        s = d.get("sounds") or {}
        if s.get("enabled") is not None:
            self.cues_row.set_quiet(bool(s["enabled"]))
        if s.get("volume") is not None:
            self.cues_volume.set_quiet(s["volume"])
        self.cues_volume.set_sensitive(bool(s.get("enabled", True)))

    # ------------------------------------------------------------------ changes
    def _change(self, args, said, undo_args=None):
        self.ctx.change(SOUND + args + ["--json"], said, undo=(SOUND + undo_args + ["--json"]) if undo_args else None,
                        done=self.sync, failed=lambda *_: self.refresh())

    def _cur(self, side):
        return next((x for x in self.doc[side]["devices"] if x["default"]), None) if self.doc else None

    def _default(self, side, name):
        old = self.doc[side]["default"] if self.doc else None
        if name == old:
            return
        self._change([side, name], lambda d: d.get("said") or f"{side.title()} changed", [side, old] if old else None)

    def _volume(self, side, v):
        cur = self._cur(side)
        old = cur["volume"] if cur else None
        self._change(["volume", side, str(int(v))], f"{side.title()} volume {int(v)}%",
                     ["volume", side, str(old)] if old is not None else None)

    def _mute(self, side, on):
        self._change(["mute", side, "on" if on else "off"], f"{side.title()} {'muted' if on else 'unmuted'}",
                     ["mute", side, "off" if on else "on"])

    def _port(self, side, name, p):
        cur = self._cur(side)
        old = cur["active_port"] if cur else None
        if p == old:
            return
        self._change(["port", side, name, p], f"Port: {p}", ["port", side, name, old] if old else None)

    def _app(self, i):
        return next((a for a in (self.doc or {}).get("apps", []) if a["id"] == i), None)

    def _app_volume(self, i, name, v):
        a = self._app(i)
        self._change(["app-volume", str(i), str(int(v))], f"{name}: {int(v)}%",
                     ["app-volume", str(i), str(a["volume"])] if a else None)

    def _app_mute(self, i, name, on):
        self._change(["app-mute", str(i), "on" if on else "off"], f"{name}: {'muted' if on else 'unmuted'}",
                     ["app-mute", str(i), "off" if on else "on"])

    def _app_output(self, i, name, dev):
        a = self._app(i)
        if a and a["output"] == dev:
            return
        self._change(["app-output", str(i), dev], lambda d: d.get("said"), ["app-output", str(i), a["output"]] if a else None)

    def _mute_all(self, on):
        self._change(["all-mute", "on" if on else "off"], "Everything muted" if on else "Unmuted",
                     ["all-mute", "off" if on else "on"])

    def _cues(self, on):
        self._change(["sounds", "on" if on else "off"], f"Sound cues {'on' if on else 'off'}",
                     ["sounds", "off" if on else "on"])

    def _cues_volume(self, v):
        old = ((self.doc or {}).get("sounds") or {}).get("volume")
        self._change(["sounds-volume", str(int(v))], f"Cue volume {int(v)}%",
                     ["sounds-volume", str(old)] if old is not None else None)

    def _test(self):
        self.ctx.run(SOUND + ["test", "--json"], lambda ok, out, err: None if ok else self.ctx.toast(
            "Couldn't play the cue: " + (err.strip() or out.strip())[:120]))

    def reset(self):
        def done(_doc):
            self.ctx.change(SOUND + ["sounds-volume", "30", "--json"], "Sound cues back to the defaults", done=self.sync)
        self.ctx.change(SOUND + ["sounds", "on", "--json"], "Sound cues on", done=done)
        return None


def build(ctx):
    p = SoundPage(ctx)
    p.page._sound = p
    return p.page


def refresh(widget):
    widget._sound.refresh()


PAGE = Page(
    id="sound", title="Sound", group="system", order=20, build=build, refresh=refresh, docs="settings.md#sound",
    icon="audio-volume-high-symbolic audio-speakers-symbolic", summary="output, input, apps, the cues",
    intro="What plays where and how loud: the output and input device, each app playing, and the desktop's own "
          "sounds. A change applies at once.",
    keywords=["audio", "volume", "speakers", "microphone", "pipewire", "pulseaudio"],
    entries=[
        Entry("output", "Output device", ["speakers", "headphones", "default output", "hdmi", "playback"], "Output"),
        Entry("output-volume", "Output volume", ["volume", "loudness", "master volume"], "Output"),
        Entry("output-port", "Output port", ["headphones jack", "line out", "connector"], "Output"),
        Entry("test", "Test the output", ["play a sound", "check speakers"], "Output"),
        Entry("input", "Input device", ["microphone", "mic", "recording", "default input"], "Input"),
        Entry("input-volume", "Input volume", ["microphone volume", "mic gain", "input level"], "Input"),
        Entry("apps", "App volumes", ["per-app volume", "mixer", "application volume", "streams"], "Apps"),
        Entry("mute-all", "Mute everything", ["mute", "silence", "SUPER+SHIFT+M"], "The desktop's sounds"),
        Entry("cues", "Sound cues", ["theme sounds", "beeps", "chirp", "system sounds", "alert sounds"],
              "The desktop's sounds"),
        Entry("cues-volume", "Cue volume", ["system sounds volume", "alert volume"], "The desktop's sounds"),
    ])
