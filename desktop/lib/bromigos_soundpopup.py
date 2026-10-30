"""The bar's sound popup (`bromigos sound popup`; package bromigos-desktop,
/usr/lib/bromigos/lib): resting the pointer on the volume opens it under the icon; a click
opens it pinned.

  OUTPUT   speakers, headphones, screens (HDMI, DisplayPort) and Bluetooth headsets, each
           with a hologram of its kind and a plain name; the one in use is marked. A click
           makes one the output, and moves what's playing to it.
  INPUT    the microphones, the same way.
  Volume and mute for the output and the microphone, and OPEN AUDIO SETTINGS →
  (Settings › Sound).

A hover popup takes no keys and closes about 0.4 s after the pointer leaves both the icon
and the popup. A click on the icon, or inside the popup, pins it: then it takes the keys
(Tab, the arrows, Esc) and closes with Esc or a click anywhere else.

The bar's hover comes from bromigos-hover (waybar/hover/, a waybar CFFI module): it asks
this app, over D-Bus, for its "hover" (with the icon's centre) and "leave" actions.
Everything is done through `bromigos sound`, as Settings › Sound does: the same devices,
the same defaults, the same mute. A Bluetooth headset's line shows its profile and codec
from PipeWire's cards (bromigos_bluez), as the Bluetooth panel does.

DRIFTGLASS GLOW (docs/DRIFTGLASS.md): Glass with faint Scanlines; the device in use stands
lit on its Emitter, and turns slowly only while it plays. Nothing moves under reduced motion.

  render(path, …)   draws the popup to a PNG (tests, docs); needs a Wayland display
"""
import json
import os
import re
import sys
import time

HERE = os.path.dirname(os.path.realpath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import bromigos_bluez as B  # noqa: E402
import bromigos_driftglass as H  # noqa: E402
from bromigos_popup import Shell, clear, load_gtk  # noqa: E402

APP_ID = "org.bromigos.SoundPopup"
NAMESPACE = "bromigos-sound"
WIDTH = 380
CLOSE_AFTER = 0.4           # seconds after the pointer leaves the icon and the popup
WARM = 600                  # seconds the app stays running after it closes, to open at once
NOISE = re.compile(r"\b(analog|digital) (stereo|surround[\w.-]*|mono)\b|\bstereo\b|\bmono\b|"
                   r"\bhigh definition audio( controller)?\b", re.I)
SPEAKER_NAMES = re.compile(r"flip|charge|soundlink|boom|speaker|pulse|xtreme|soundcore motion", re.I)


# ------------------------------------------------------------------ words (pure: tested without GTK)
def friendly(dev):
    """A device's name without the plumbing ("Built-in Audio Analog Stereo" -> "Built-in Audio")."""
    d = dev.get("description") or dev.get("name") or "?"
    clean = re.sub(r"\s+", " ", NOISE.sub("", d)).strip(" -·")
    clean = re.sub(r"\(\s*\)", "", clean).strip()
    return clean or d


def glyph(dev, out=True):
    """The hologram for a sound device."""
    k = dev.get("kind")
    if k == "bluetooth":
        name = dev.get("description", "")
        if not out:
            return "headset"
        return "earbuds" if B.EARBUDS.search(name) else "speaker" if SPEAKER_NAMES.search(name) else "headset"
    return {"speakers": "speaker", "headphones": "headset", "display": "monitor", "usb": "headset" if out else "mic",
            "microphone": "mic", "virtual": "device"}.get(k, "speaker" if out else "mic")


KIND_WORDS = {"speakers": "SPEAKERS", "headphones": "HEADPHONES", "display": "SCREEN", "bluetooth": "BLUETOOTH",
              "usb": "USB", "microphone": "MICROPHONE", "virtual": "VIRTUAL"}


def detail(dev, audio=None):
    """The line under a device's name: its kind, its port, a Bluetooth headset's profile."""
    bits = [KIND_WORDS.get(dev.get("kind"), (dev.get("kind") or "").upper())]
    port = next((p for p in dev.get("ports") or [] if p.get("name") == dev.get("active_port")), None)
    if port and port.get("description") and port["description"].upper() not in bits:
        bits.append(port["description"].upper())
    if dev.get("kind") == "bluetooth" and audio:
        if audio.get("mode") in B.MODE_LABEL:
            bits.append(B.MODE_LABEL[audio["mode"]])
        if audio.get("codec"):
            bits.append(audio["codec"])
    if dev.get("muted"):
        bits.append("MUTED")
    return " · ".join(b for b in bits if b)


def bt_mac(dev):
    """A Bluetooth sink or source's device address (bluez_output.00_00_5E_00_53_10.1)."""
    m = re.match(r"bluez_(?:output|input|source|sink)\.([0-9A-Fa-f_]{17})", dev.get("name", ""))
    return m.group(1).replace("_", ":").upper() if m else None


def rows(doc, side):
    """The devices of one side, the one in use first, then by name."""
    devs = list((doc.get(side) or {}).get("devices") or [])
    return sorted(devs, key=lambda d: (not d.get("default"), friendly(d).lower()))


def hint(dev, side):
    if dev.get("default"):
        return f"{friendly(dev)} is the {side} in use" + (": it's playing now" if dev.get("state") == "running" and
                                                           side == "output" else "")
    return (f"Use {friendly(dev)} for sound: what's playing moves to it" if side == "output" else
            f"Use {friendly(dev)} as the microphone")


# ------------------------------------------------------------------ GTK
class Device:
    """One device row: a button over the whole row."""

    def __init__(self, pop, dev, side):
        self.p, self.side = pop, side
        sh, Gtk = pop.sh, pop.sh.Gtk
        self.b = Gtk.Button()
        self.b.add_css_class("dg-item")
        self.b.add_css_class("dg-dev")
        box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        self.holo = Gtk.DrawingArea()
        self.holo.set_size_request(38, 38)
        self.holo.set_draw_func(self.draw)
        box.append(self.holo)
        mid = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2, hexpand=True, valign=Gtk.Align.CENTER)
        self.name = sh.label("", "dg-name", ellipsize=3, max_width_chars=26)
        self.sub = sh.label("", "dg-status", ellipsize=3, max_width_chars=34)
        mid.append(self.name)
        mid.append(self.sub)
        box.append(mid)
        self.mark = sh.label("", "dg-item-right", valign=Gtk.Align.CENTER)
        box.append(self.mark)
        self.b.set_child(box)
        self.b.connect("clicked", lambda *_: pop.use(self.side, self.dev))
        self.update(dev)

    def draw(self, area, cr, w, h):
        d, sh = self.dev, self.p.sh
        playing = d.get("default") and d.get("state") == "running"
        H.glyph(cr, glyph(d, self.side == "output"), 0, 0, min(w, h), sh.pal, t=sh.t(), live=bool(d.get("default")),
                still=sh.still or not playing, hc=sh.hc)

    def update(self, dev):
        self.dev = dev
        audio = self.p.sh.audio.get(bt_mac(dev) or "")
        self.name.set_text(friendly(dev))
        self.sub.set_text(detail(dev, audio))
        self.mark.set_text("● IN USE" if dev.get("default") else "")
        (self.b.remove_css_class if dev.get("default") else self.b.add_css_class)("dg-idle")
        self.b.set_tooltip_text(hint(dev, self.side))
        self.holo.queue_draw()


class Popup:
    def __init__(self, sh, on_close):
        self.sh, self.on_close = sh, on_close
        Gtk = sh.Gtk
        self.doc = {}
        self.rows = {"output": {}, "input": {}}
        self.pinned = False
        self.inside = False
        self.close_timer = None
        self.timer = None
        self.dragging = {"output": 0.0, "input": 0.0}
        self.win = Gtk.Window(title="Sound")
        self.win.add_css_class("dg-win")
        self.win.set_decorated(False)
        self.win.set_resizable(False)
        sh.style(self.win.get_display())
        self._build()
        keys = Gtk.EventControllerKey()
        keys.connect("key-pressed", self.on_key)
        self.win.add_controller(keys)
        motion = Gtk.EventControllerMotion()
        motion.connect("enter", lambda *_: self.entered())
        motion.connect("leave", lambda *_: self.left())
        self.win.add_controller(motion)
        click = Gtk.GestureClick()
        click.set_button(0)
        click.set_propagation_phase(Gtk.PropagationPhase.CAPTURE)
        click.connect("pressed", lambda *_: self.pin())
        self.win.add_controller(click)
        self.win.connect("close-request", lambda *_: self.close() or True)

    def _build(self):
        sh, Gtk = self.sh, self.sh.Gtk
        frame = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        frame.add_css_class("dg-frame")
        frame.set_size_request(WIDTH, -1)
        top = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        top.append(sh.label("SOUND", "dg-eyebrow", "Sound: where it plays and where it listens. Click to keep "
                            "this open; scroll on the bar icon changes the volume", hexpand=True))
        self.server = sh.label("", "dg-adapter", "The sound server")
        top.append(self.server)
        frame.append(top)
        rule = Gtk.Box()
        rule.add_css_class("dg-rule")
        frame.append(rule)
        self.lists, self.levels = {}, {}
        for side, title, tip in (("output", "OUTPUT", "Where the sound plays: click one to use it"),
                                 ("input", "INPUT", "The microphone apps hear: click one to use it")):
            frame.append(sh.label(title, "dg-section", tip))
            box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
            self.lists[side] = box
            frame.append(box)
            frame.append(self._level(side))
        self.msg = sh.label("", "dg-msg", wrap=True, max_width_chars=44)
        self.msg.set_tooltip_text("What happened last")
        frame.append(self.msg)
        foot = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, margin_top=10)
        foot.append(Gtk.Box(hexpand=True))
        foot.append(sh.button("OPEN AUDIO SETTINGS →", "dg-btn", "Settings › Sound: every device, its ports, each "
                              "app's volume, the desktop's own sounds", lambda: (sh.open_settings("sound"),
                                                                                  self.close())))
        frame.append(foot)
        self.frame = frame
        self.win.set_child(sh.frame_overlay(frame))

    def _level(self, side):
        sh, Gtk = self.sh, self.sh.Gtk
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8, margin_top=4)
        mute = Gtk.ToggleButton(label="MUTE")
        mute.add_css_class("dg-seg")
        mute.add_css_class("dg-mute")
        mute.set_valign(sh.Gtk.Align.CENTER)
        mute.set_tooltip_text(f"Mutes the {'output' if side == 'output' else 'microphone'} (middle-click on the bar "
                              "icon mutes the output too)")
        mute.connect("toggled", lambda b: self.mute(side, b))
        scale = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 0, 100, 1)
        scale.set_draw_value(False)
        scale.set_hexpand(True)
        scale.add_css_class("dg-scale")
        scale.set_tooltip_text("The output's volume (scroll on the bar icon: ±5%)" if side == "output" else
                               "How loud the microphone is")
        scale.connect("value-changed", lambda s: self.volume(side, s))
        pct = sh.label("", "dg-pct", width_chars=4, xalign=1.0)
        row.append(mute)
        row.append(scale)
        row.append(pct)
        self.levels[side] = (mute, scale, pct)
        return row

    # -- state
    def changed(self, doc):
        if not doc or doc.get("ok") is False:
            self.say((doc or {}).get("error") or "bromigos sound didn't answer", "error")
            return
        self.doc = doc
        self.server.set_text(re.sub(r"\s*\(on PipeWire ([\d.]+)\)", r" · PipeWire \1", doc.get("server", "")))
        for side in ("output", "input"):
            self._list(side)
            self._sync_level(side)
        self.animate()

    def _list(self, side):
        devs = rows(self.doc, side)
        box, have = self.lists[side], self.rows[side]
        want = [d["name"] for d in devs]
        shown = []
        c = box.get_first_child()
        while c is not None:
            shown.append(getattr(c, "_dg_name", None))
            c = c.get_next_sibling()
        if shown != want:
            clear(box)
            for d in devs:
                r = have.get(d["name"]) or Device(self, d, side)
                r.b._dg_name = d["name"]
                have[d["name"]] = r
                box.append(r.b)
            if not devs:
                box.append(self.sh.label("No sound device" if side == "output" else "No microphone", "dg-empty"))
        for d in devs:
            have[d["name"]].update(d)

    def _sync_level(self, side):
        mute, scale, pct = self.levels[side]
        dev = next((d for d in (self.doc.get(side) or {}).get("devices") or [] if d.get("default")), None)
        for w in (mute, scale):
            w.set_sensitive(dev is not None)
        if dev is None:
            pct.set_text("")
            return
        if self.sh.now() - self.dragging[side] > 0.6:       # not while it's being dragged
            self._quiet = True
            scale.set_value(min(100, dev["volume"]))
            mute.set_active(bool(dev.get("muted")))
            mute.set_label("MUTED" if dev.get("muted") else "MUTE")
            self._quiet = False
        pct.set_text(f"{dev['volume']}%")

    def animate(self):
        if self.sh.still or self.timer is not None or not self.win.get_visible():
            return
        if not any(d.get("default") and d.get("state") == "running"
                   for d in (self.doc.get("output") or {}).get("devices") or []):
            return
        self.timer = self.sh.GLib.timeout_add(50, self.tick)

    def tick(self):
        if not self.win.get_visible():
            self.timer = None
            return False
        live = [r for r in self.rows["output"].values() if r.dev.get("default") and r.dev.get("state") == "running"]
        if not live:
            self.timer = None
            return False
        for r in live:
            r.holo.queue_draw()
        return True

    def say(self, text, kind=None):
        self.msg.set_text(text or "")
        for c in ("dg-error", "dg-ok"):
            self.msg.remove_css_class(c)
        if kind:
            self.msg.add_css_class("dg-" + kind)

    # -- actions: bromigos sound, as Settings › Sound does
    def use(self, side, dev):
        self.pin()
        if dev.get("default"):
            return
        _sound([side, dev["name"]], lambda ok, said: (self.say(said, "ok" if ok else "error"), self.refresh()))

    def volume(self, side, scale):
        if getattr(self, "_quiet", False):
            return
        self.dragging[side] = self.sh.now()
        v = int(round(scale.get_value()))
        self.levels[side][2].set_text(f"{v}%")
        pending = getattr(self, "_pending", {})
        self._pending = pending
        if side in pending:
            self.sh.GLib.source_remove(pending[side])

        def send():
            pending.pop(side, None)
            _sound(["volume", side, str(v)], lambda ok, said: None if ok else self.say(said, "error"))
            return False
        pending[side] = self.sh.GLib.timeout_add(90, send)

    def mute(self, side, btn):
        if getattr(self, "_quiet", False):
            return
        on = btn.get_active()
        btn.set_label("MUTED" if on else "MUTE")
        _sound(["mute", side, "on" if on else "off"], lambda ok, said: (None if ok else self.say(said, "error"),
                                                                        self.refresh()))

    def refresh(self):
        _sound(["status", "--light"], lambda ok, doc: self.changed(doc if ok else {"ok": False, "error": doc}),
               want_doc=True)

    # -- hover, pin, close
    def pin(self):
        if self.pinned:
            return
        self.pinned = True
        self.cancel_close()
        self.sh.keyboard(self.win, True)
        if self.on_pin:
            self.on_pin()

    on_pin = None

    def entered(self):
        self.inside = True
        self.cancel_close()

    def left(self):
        self.inside = False
        if not self.pinned:
            self.close_soon()

    def close_soon(self):
        self.cancel_close()
        self.close_timer = self.sh.GLib.timeout_add(int(CLOSE_AFTER * 1000), self._close_now)

    def _close_now(self):
        self.close_timer = None
        if not self.inside and not self.pinned:
            self.close()
        return False

    def cancel_close(self):
        if self.close_timer is not None:
            self.sh.GLib.source_remove(self.close_timer)
            self.close_timer = None

    def on_key(self, ctrl, keyval, keycode, state):
        if keyval == self.sh.Gdk.KEY_Escape:
            self.close()
            return True
        return False

    def close(self):
        self.cancel_close()
        self.win.set_visible(False)
        self.on_close()


def _sound(args, back, want_doc=False):
    """`bromigos sound ARGS --json`, async: back(ok, said or error), or back(ok, the document)."""
    from gi.repository import Gio
    try:
        p = Gio.Subprocess.new(["bromigos", "sound", *args, "--json"],
                               Gio.SubprocessFlags.STDOUT_PIPE | Gio.SubprocessFlags.STDERR_SILENCE)
    except Exception as e:
        back(False, str(e))
        return

    def done(proc, res):
        try:
            _, out, _ = proc.communicate_utf8_finish(res)
            doc = json.loads(out or "{}")
        except Exception as e:
            back(False, str(e))
            return
        ok = doc.get("ok", True)
        if want_doc:
            back(ok, doc if ok else doc.get("error", "failed"))
        else:
            back(ok, doc.get("said") if ok else doc.get("error", "failed"))
    p.communicate_utf8_async(None, None, done)


class Watch:
    """PipeWire's changes (`pactl subscribe`): fn() once per burst of them."""

    def __init__(self, GLib, fn):
        from gi.repository import Gio
        self.GLib, self.fn, self.pending = GLib, fn, None
        try:
            self.p = Gio.Subprocess.new(["pactl", "subscribe"], Gio.SubprocessFlags.STDOUT_PIPE |
                                        Gio.SubprocessFlags.STDERR_SILENCE)
        except Exception:
            self.p = None
            return
        self.stream = Gio.DataInputStream.new(self.p.get_stdout_pipe())
        self.stream.read_line_async(GLib.PRIORITY_DEFAULT, None, self._line)

    def _line(self, stream, res):
        try:
            line, _ = stream.read_line_finish_utf8(res)
        except Exception:
            return
        if line is None:
            return
        if any(w in line for w in ("sink", "source", "server", "card")) and "sink-input" not in line \
                and "source-output" not in line:
            if self.pending is None:
                self.pending = self.GLib.timeout_add(120, self._fire)
        stream.read_line_async(self.GLib.PRIORITY_DEFAULT, None, self._line)

    def _fire(self):
        self.pending = None
        self.fn()
        return False

    def stop(self):
        if self.p is not None:
            self.p.force_exit()
            self.p = None


class App:
    """One process: the bar's hover and click reach it as D-Bus actions or command lines."""

    def __init__(self):
        self.Gtk, self.Gdk, self.GLib, self.LS = load_gtk()
        from gi.repository import Gio
        self.Gio = Gio
        self.app = self.Gtk.Application(application_id=APP_ID, flags=Gio.ApplicationFlags.HANDLES_COMMAND_LINE)
        self.app.connect("command-line", self.on_cmd)
        self.app.connect("startup", self.on_startup)
        self.sh = None
        self.pop = None
        self.catch = None
        self.watch = None
        self.held = False
        self.idle = None

    def on_startup(self, app):
        G = self.GLib
        for name, ptype, fn in (("hover", G.VariantType.new("i"), lambda a, v: self.hover(v.get_int32())),
                                ("leave", None, lambda a, v: self.leave()),
                                ("pin", None, lambda a, v: self.click())):
            act = self.Gio.SimpleAction.new(name, ptype)
            act.connect("activate", fn)
            app.add_action(act)

    def run(self, argv):
        return self.app.run(argv)

    def ensure(self):
        if self.sh is not None:
            return
        self.sh = Shell(self.Gtk, self.Gdk, self.GLib, self.LS, namespace=NAMESPACE)
        self.pop = Popup(self.sh, self.closed)
        self.pop.on_pin = self.pinned
        self.pop.win.set_application(self.app)
        self.sh.layer(self.pop.win, keyboard=False)
        self.pop.refresh()

    def hold(self):
        if not self.held:
            self.app.hold()
            self.held = True
        if self.idle is not None:
            self.GLib.source_remove(self.idle)
            self.idle = None

    def on_cmd(self, app, cl):
        args = cl.get_arguments()[1:]
        verb = args[0] if args else "pin"
        if verb == "hover":
            self.hover(int(args[1]) if len(args) > 1 and args[1].lstrip("-").isdigit() else None)
        elif verb == "leave":
            self.leave()
        elif verb == "close":
            if self.pop is not None and self.pop.win.get_visible():
                self.pop.close()
        else:
            self.click()
        return 0

    def show(self, at_x, pinned):
        self.ensure()
        self.hold()
        pop, sh = self.pop, self.sh
        pop.pinned = False
        if sh.LS is not None and sh.LS.is_layer_window(pop.win):
            sh.place(pop.win, WIDTH, at_x=at_x)
        sh.keyboard(pop.win, False)
        if self.watch is None:
            self.watch = Watch(self.GLib, pop.refresh)
        sh.refresh_audio(lambda: pop.changed(pop.doc) if pop.doc else None)
        pop.refresh()
        if pop.doc:
            pop.changed(pop.doc)
        pop.win.present()
        if pinned:
            pop.pin()

    def hover(self, at_x):
        if self.pop is not None and self.pop.win.get_visible():
            self.pop.cancel_close()
            return
        self.show(at_x, pinned=False)

    def leave(self):
        pop = self.pop
        if pop is not None and pop.win.get_visible() and not pop.pinned and not pop.inside:
            pop.close_soon()

    def click(self):
        pop = self.pop
        if pop is not None and pop.win.get_visible():
            if pop.pinned:
                pop.close()
            else:
                pop.pin()
            return
        self.show(None, pinned=True)

    def pinned(self):
        if self.catch is None:
            self.catch = self.sh.catcher(lambda: self.pop.close())
            if self.catch is not None:
                self.catch.set_application(self.app)
                self.catch.present()
                self.pop.win.present()

    def closed(self):
        if self.catch is not None:
            self.catch.destroy()
            self.catch = None
        if self.watch is not None:
            self.watch.stop()
            self.watch = None
        # stay running a while, so the next hover opens at once
        if self.idle is None and self.held:
            self.idle = self.GLib.timeout_add_seconds(WARM, self._quit)

    def _quit(self):
        self.idle = None
        if self.held:
            self.app.release()
            self.held = False
        return False


def main(argv=None):
    return App().run([sys.argv[0]] + list(sys.argv[1:] if argv is None else argv))


# ------------------------------------------------------------------ offscreen
def render(path, t=1.4):
    """Draw the popup to a PNG, from whatever `bromigos sound` and pactl answer on PATH (the
    tests' stand-ins)."""
    os.environ.setdefault("GSK_RENDERER", "cairo")
    Gtk, Gdk, GLib, LS = load_gtk()
    if not Gtk.init_check():
        raise RuntimeError("no display to render on")
    clock = {"t": 100.0}
    sh = Shell(Gtk, Gdk, GLib, None, now=lambda: clock["t"], namespace=NAMESPACE)
    sh.t0 = clock["t"] - t
    pop = Popup(sh, lambda: None)
    pop.animate = lambda: None
    loop = GLib.MainLoop()
    got = {}

    def doc(ok, d):
        got["doc"] = d
        pop.changed(d if ok else {"ok": False, "error": d})
    sh.refresh_audio(lambda: got.setdefault("audio", True))
    _sound(["status", "--light"], doc, want_doc=True)
    seen, out = [], {}

    def snap():
        if "doc" not in got or "audio" not in got:
            return True
        if not got.get("synced"):
            got["synced"] = True
            pop.changed(got["doc"])
            return True
        frame = pop.win.get_child()
        w, h = frame.get_width(), frame.get_height()
        seen.append((w, h))
        if w <= 1 or h <= 1 or seen[-2:] != [(w, h)] * 2:
            return True
        paintable = Gtk.WidgetPaintable.new(frame)
        snapshot = Gtk.Snapshot.new()
        paintable.snapshot(snapshot, w, h)
        node = snapshot.to_node()
        if node is None:
            return True
        pop.win.get_renderer().render_texture(node, None).save_to_png(path)
        out["size"] = (w, h)
        loop.quit()
        return False
    pop.win.present()
    GLib.timeout_add(100, snap)
    GLib.timeout_add(20000, loop.quit)
    loop.run()
    pop.win.destroy()
    if "size" not in out:
        raise RuntimeError("the popup never laid out")
    return out["size"]
