"""Bluetooth (docs/settings.md, "Bluetooth"): the adapter; your devices as cards; pairing a
new one step by step; each device's own page (a controller's input test and rumble, a
headset's sound, rename, auto-reconnect, forget); and troubleshooting.

Clear first: plain labels, ordinary rows and buttons. DRIFTGLASS (docs/DRIFTGLASS.md) is the
accent: each device's hologram on its Emitter, battery cells, signal bars, and the Sweep
while scanning. They move only while this page or one of its dialogs is open, only for a
state (connected, connecting, scanning), and not at all under reduced motion.

Everything goes through the desktop's one bluez core, bromigos_bluez, as the bar and its
panel do: bluez's own signals keep the page current (no polling), and pairing has its own
agent, so a PIN or a passkey is asked for right here. A headset's sound profile goes
through `bromigos bluetooth profile`, its output and microphone through `bromigos sound`;
a controller's input and rumble through bromigos_gamepad; a microphone's level through
`parec`, as `bromigos bluetooth session` does for the TUI.
"""
import json
import os
import sys
import time

from gi.repository import Adw, Gdk, Gio, GLib, Gtk

from bromigos_settings import Entry, Page

for _p in ("/usr/lib/bromigos/lib", os.path.join(os.path.dirname(os.path.realpath(__file__)), "..", "..", "lib")):
    if os.path.isdir(_p) and _p not in sys.path:
        sys.path.insert(0, _p)

import bromigos_bluez as B  # noqa: E402
import bromigos_driftglass as H  # noqa: E402
import bromigos_gamepad as G  # noqa: E402
from bromigos_btsession import level as mic_level  # noqa: E402

BT = ["bromigos", "bluetooth"]
SCAN_SECS = 30
WICK = {"void": "#000500", "panel": "#001300", "selection": "#003b00", "primary": "#39ff14", "soft": "#9cff8a",
        "dim": "#159b09", "text": "#c4f5bb", "muted": "#7e927e", "faint": "#4e6b4e", "warn": "#d4af37",
        "danger": "#ff766f", "white": "#e8ffe0"}
CSS = """
.bt-card { padding: 10px; border-radius: 12px; }
.bt-card-name { font-weight: 700; }
.bt-card-state { font-size: 0.85em; opacity: 0.8; }
.bt-key { padding: 2px 8px; border-radius: 6px; border: 1px solid alpha(currentColor, 0.3); font-family: monospace;
          font-size: 0.85em; }
.bt-key.bt-lit { background-color: @accent_bg_color; color: @accent_fg_color; border-color: @accent_bg_color; }
.bt-step { font-size: 0.85em; opacity: 0.6; }
.bt-step.bt-now { opacity: 1; font-weight: 700; }
.bt-code { font-size: 2em; font-weight: 700; font-family: monospace; letter-spacing: 4px; }
.bt-title { font-size: 1.3em; font-weight: 700; }
"""


def _motion():
    try:
        import bromigos_theme as T
        return T.motion()
    except Exception:
        return "full"


def _pal(ctx):
    p = dict(WICK)
    p.update({k: v for k, v in (ctx.colors or {}).items() if isinstance(v, str) and v.startswith("#")})
    return p


def _hc():
    try:
        import bromigos_theme as T
        return T.high_contrast()
    except Exception:
        return False


class Clock:
    """One animation timer for the page and its dialogs, only while something is shown that
    moves (and never under reduced motion)."""

    def __init__(self):
        self.still = _motion() != "full"
        self.t0 = time.monotonic()
        self.areas = {}         # area -> fn() -> bool (still moving?)
        self.timer = None

    def t(self):
        return time.monotonic() - self.t0

    def watch(self, area, moving):
        self.areas[area] = moving
        if not self.still and self.timer is None:
            self.timer = GLib.timeout_add(45, self.tick)

    def forget(self, area):
        self.areas.pop(area, None)

    def tick(self):
        live = False
        for area, moving in list(self.areas.items()):
            if area.get_mapped() and moving():
                area.queue_draw()
                live = True
        if not live and not any(a.get_mapped() for a in self.areas):
            self.timer = None
            return False
        return True


def _area(w, h, draw, tip=None):
    a = Gtk.DrawingArea(content_width=w, content_height=h)
    a.set_draw_func(lambda area, cr, ww, hh: draw(cr, ww, hh))
    if tip:
        a.set_tooltip_text(tip)
    return a


def _words(d, audio=None, op=None):
    """A device's state in plain words."""
    if op:
        return {"connecting": "Connecting…", "disconnecting": "Disconnecting…", "pairing": "Pairing…",
                "trusting": "Saving it…", "forgetting": "Forgetting…"}.get(op, op.title() + "…")
    if not d["paired"]:
        return "Found nearby"
    bits = ["Connected" if d["connected"] else "Not connected"]
    if d["connected"] and audio and audio.get("mode") in B.MODE_LABEL:
        bits.append({"hifi": "Hi-fi", "headset": "Headset + mic", "off": "No sound"}[audio["mode"]] +
                    (f" · {audio['codec']}" if audio.get("codec") else ""))
    return " · ".join(bits)


class Card:
    """A device on the My devices grid: its hologram, name, state, battery and signal."""

    def __init__(self, page, d):
        self.p, self.d = page, d
        self.b = Gtk.Button()
        self.b.add_css_class("bt-card")
        self.b.add_css_class("card")
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        self.holo = _area(150, 92, self.draw_holo)
        box.append(self.holo)
        self.name = Gtk.Label(xalign=0.5, ellipsize=3, max_width_chars=18)
        self.name.add_css_class("bt-card-name")
        self.state = Gtk.Label(xalign=0.5, ellipsize=3, max_width_chars=22)
        self.state.add_css_class("bt-card-state")
        self.meter = _area(150, 10, self.draw_meter)
        for w in (self.name, self.state, self.meter):
            box.append(w)
        self.b.set_child(box)
        self.b.connect("clicked", lambda *_: page.open_device(self.d["mac"]))
        page.clock.watch(self.holo, lambda: self.d["connected"] or self.d["mac"] in page.ops or
                         self.d["mac"] in page.fx)
        self.update(d)

    def draw_holo(self, cr, w, h):
        p, d = self.p, self.d
        size = min(w, h)
        H.glyph(cr, d["glyph"], (w - size) / 2, 0, size, p.pal, t=p.clock.t(), live=d["connected"],
                fx=p.fx_of(d["mac"]), still=p.clock.still, hc=p.hc)

    def draw_meter(self, cr, w, h):
        d, pal = self.d, self.p.pal
        if d.get("battery") is not None:
            H.cells(cr, w * 0.2, 1, w * 0.6, h - 2, d["battery"], pal, n=10)
        elif d.get("rssi") is not None:
            H.bars(cr, w / 2 - 8, 0, h, d["rssi"], pal)

    def update(self, d):
        self.d = d
        audio = self.p.state.get("audio_cards", {}).get(d["mac"])
        self.name.set_text(d["name"])
        self.state.set_text(_words(d, audio, self.p.ops.get(d["mac"])) +
                            (f" · {d['battery']}%" if d.get("battery") is not None else ""))
        b = d.get("battery")
        self.b.set_tooltip_text(f"{d['name']}: {d['kind']}, {'connected' if d['connected'] else 'not connected'}"
                                + (f", battery {b}%" + (" (low)" if B.level(b) != "ok" else "") if b is not None else "")
                                + ". Click for its page: connect, test, sound, rename, forget")
        self.holo.queue_draw()
        self.meter.queue_draw()


class BluetoothPage:
    def __init__(self, ctx):
        self.ctx = ctx
        self.pal, self.hc = _pal(ctx), _hc()
        self.clock = Clock()
        self.state = {"devices": [], "paired": [], "nearby": [], "connected": []}
        self.ops, self.fx, self.seen = {}, {}, {}
        self.cards = {}
        self.errors = []
        self.scan_until = 0.0
        self.dialog = None
        self.wizard = None
        self._css()
        self.page = ctx.page()
        self.page.set_reset(None, hint="Nothing here has a bromigOS default: the paired devices are this machine's own "
                                       "(bluez keeps them)")
        self._build()
        ctx.on_restyle(self._restyled)
        self.bz = B.Bluez(self.changed)
        try:
            self.bz.start()
        except Exception:
            pass
        self.changed(self.bz.state())
        self.refresh_audio()
        self._settings()
        # offscreen renders (tools/settings/render.sh --bt-open WHAT): open a dialog first
        what = os.environ.get("BROMIGOS_SETTINGS_BT_OPEN")
        if what:
            ctx.pending += 1            # the render waits for it
            GLib.timeout_add(700, self._render_open, what)

    def _render_open(self, what):
        """device:MAC opens a device's page; wizard, wizard:KIND (its scan) or
        wizard:pair:MAC (scanning, then pairing it: its question shows)."""
        parts = what.split(":", 1)
        if parts[0] == "device" and len(parts) > 1:
            self.open_device(parts[1])
            GLib.timeout_add(1500, self._render_done)
            return False
        w = Wizard(self)
        w.present()
        rest = parts[1] if len(parts) > 1 else ""
        if rest:
            kind, _, mac = rest.partition(":")
            if kind == "pair":
                w.pick_kind(next((i for i, k in enumerate(B.PAIR_KINDS) if k[1] == "phone"), 0))

                def go():
                    d = self.find(mac)
                    if d is None:
                        return True
                    w.go_pair(d)
                    return False
                GLib.timeout_add(500, go)
            else:
                w.pick_kind(next((i for i, k in enumerate(B.PAIR_KINDS) if k[1] == kind), 0))
        GLib.timeout_add(2500, self._render_done)
        return False

    def _render_done(self):
        self.ctx.pending -= 1
        return False

    def _css(self):
        prov = Gtk.CssProvider()
        prov.load_from_string(CSS) if hasattr(prov, "load_from_string") else prov.load_from_data(CSS.encode())
        Gtk.StyleContext.add_provider_for_display(Gdk.Display.get_default(), prov,
                                                  Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)

    def _restyled(self, colors):
        self.pal = _pal(self.ctx)
        for c in self.cards.values():
            c.update(c.d)

    # ------------------------------------------------------------ the page
    def _build(self):
        ctx = self.ctx
        g = self.ad_group = ctx.group(self.page, "Adapter", "This computer's Bluetooth.", key="adapter")
        self.power_row = ctx.switch_row(
            g, "Bluetooth", "", key="power", on_toggle=self._power,
            hint="Turns Bluetooth on or off (a block from rfkill is lifted first)",
            advanced={"runs": "bromigos bluetooth power on|off", "note": "bluez's Adapter1.Powered; rfkill unblock"})
        self.vis_row = ctx.switch_row(
            g, "Visible to devices nearby", "So a phone or another computer can find this one and pair",
            key="discoverable", on_toggle=self._visible,
            hint="Lets other devices find this machine (bluez turns it off again after 3 minutes)",
            advanced={"runs": "bromigos bluetooth discoverable on|off"})
        self.audio_row = ctx.switch_row(
            g, "Switch the sound over on connect", "Bluetooth headphones become the sound output as they connect",
            key="audio-default", on_toggle=self._audio_default,
            hint="On: connecting Bluetooth headphones makes them the sound output (Settings › Sound shows it). "
                 "Off: the output stays as it is",
            advanced={"runs": "bromigos bluetooth audio-default on|off",
                      "note": "~/.config/bromigos/bluetooth.toml: audio_default"})
        self.ad_notes = []

        g = self.dev_group = ctx.group(self.page, "My devices", "The devices this computer knows. Click one for "
                                       "its page.", key="paired")
        bar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8, margin_bottom=8)
        self.pair_b = ctx.button("Pair a new device…", self.start_wizard, "Step by step: what it is, how to put "
                                 "it in pairing mode, then scan and pair", primary=True)
        self.pair_b._bromigos_key = "pair-wizard"
        self.scan_b = ctx.button("Scan", self.toggle_scan, f"Looks for devices in pairing mode for {SCAN_SECS} "
                                 "seconds; they appear under Nearby")
        self.scan_b._bromigos_key = "scan"
        bar.append(self.pair_b)
        bar.append(self.scan_b)
        g.add(bar)
        self.grid = Gtk.FlowBox(selection_mode=Gtk.SelectionMode.NONE, homogeneous=True, column_spacing=12,
                                row_spacing=12, min_children_per_line=2, max_children_per_line=5)
        g.add(self.grid)
        self.empty = Gtk.Label(label="", xalign=0, wrap=True)
        self.empty.add_css_class("dim-label")
        g.add(self.empty)

        g = self.near_group = ctx.group(self.page, "Nearby", "Devices in pairing mode near this computer.",
                                        key="nearby")
        head = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        self.radar = _area(84, 84, self.draw_radar, "The scan: each dot is a device found, further out the "
                           "weaker its signal")
        self.clock.watch(self.radar, lambda: bool(self.state.get("adapter") and
                                                  self.state["adapter"].get("discovering")))
        self.near_words = Gtk.Label(xalign=0, wrap=True, hexpand=True)
        head.append(self.radar)
        head.append(self.near_words)
        g.add(head)
        self.near_rows = []

        g = self.trouble = ctx.group(self.page, "Troubleshooting", "When something won't pair or connect.",
                                     key="trouble")
        ctx.row(g, "Reset the adapter", "Switches Bluetooth off, lifts an rfkill block, and on again: it fixes most "
                "adapters that stopped answering", key="reset",
                buttons=[("Reset", self.reset, "Switches the adapter off and on again")],
                advanced={"note": "bluez Adapter1.Powered off, rfkill unblock bluetooth, Powered on"})
        ctx.row(g, "Re-pair a device", "Forget it and pair it again: what fixes a device that connects then drops, "
                "or one paired before a firmware update", key="repair",
                hint="Open the device's page, then Re-pair")
        ctx.row(g, "In a terminal", "Bluetooth in the terminal: the same, with keys (bromigos bluetooth tui)",
                key="tui", buttons=[("Open", lambda: ctx.launch(BT + ["tui", "--window"]),
                                     "Opens bromigos bluetooth tui in a terminal window")],
                advanced={"runs": "bromigos bluetooth tui --window"})
        ctx.row(g, "bluetoothctl", "bluez's own console, for anything else", key="console",
                hint="Opens bluetoothctl in a terminal (type `help` there)",
                buttons=[("Open", lambda: ctx.terminal(["bluetoothctl"]), "Opens bluetoothctl in a terminal")],
                advanced={"runs": "bluetoothctl"})
        self.err_rows = []

    def _settings(self):
        def got(doc, err):
            if doc and doc.get("ok") is not False and "audio_default" in doc:
                self.audio_row.set_quiet(doc["audio_default"])
        self.ctx.json(BT + ["--json"], got)

    # ------------------------------------------------------------ state
    def changed(self, st):
        before = {d["mac"]: d for d in self.state.get("devices", [])}
        now = time.monotonic()
        for d in st.get("devices", []):
            was = before.get(d["mac"])
            if was is not None and was["connected"] != d["connected"]:
                self.fx[d["mac"]] = ("spark" if d["connected"] else "fade", now)
                self.refresh_audio()
            self.seen.setdefault(d["mac"], now)
        st["audio_cards"] = self.state.get("audio_cards", {})
        st["sound"] = self.state.get("sound", {})
        self.state = st
        self.sync()
        if self.dialog is not None:
            self.dialog.sync()
        if self.wizard is not None:
            self.wizard.sync()

    def refresh_audio(self):
        """PipeWire's Bluetooth cards and devices (as the session reads them), async."""
        got = {}

        def part(key):
            def fin(proc, res):
                try:
                    _, out, _ = proc.communicate_utf8_finish(res)
                    got[key] = json.loads(out or "null")
                except Exception:
                    got[key] = None
                if len(got) == 4:
                    import bromigos_btsession as S
                    self.state["audio_cards"] = B.audio_cards(got["cards"] or [])
                    self.state["sound"] = S.sound_of(got["sinks"], got["sources"], got["info"])
                    self.sync()
                    if self.dialog is not None:
                        self.dialog.sync()
            return fin
        for key, argv in (("cards", ["list", "cards"]), ("sinks", ["list", "short", "sinks"]),
                          ("sources", ["list", "short", "sources"]), ("info", ["info"])):
            try:
                p = Gio.Subprocess.new(["pactl", "--format=json", *argv], Gio.SubprocessFlags.STDOUT_PIPE |
                                       Gio.SubprocessFlags.STDERR_SILENCE)
                p.communicate_utf8_async(None, None, part(key))
            except Exception:
                got[key] = None

    def fx_of(self, mac):
        if self.ops.get(mac) in ("connecting", "pairing", "trusting", "disconnecting"):
            return ("pulse", self.clock.t())
        e = self.fx.get(mac)
        if e is None:
            return None
        age = time.monotonic() - e[1]
        if age > 0.7:
            self.fx.pop(mac, None)
            return None
        return (e[0], age)

    def sync(self):
        ctx, st = self.ctx, self.state
        a = st.get("adapter")
        has = a is not None
        self.power_row.set_sensitive(has and not st.get("hard_blocked"))
        self.power_row.set_quiet(bool(a and a["powered"]))
        self.power_row.set_subtitle(GLib.markup_escape_text(f"{a['alias'] or a['name']} ({a['mac']})" if has
                                                            else "No adapter"))
        self.vis_row.set_sensitive(bool(a and a["powered"]))
        self.vis_row.set_quiet(bool(a and a.get("discoverable")))
        on = bool(a and a["powered"])
        self.pair_b.set_sensitive(on)
        self.scan_b.set_sensitive(on)
        scanning = bool(a and a.get("discovering"))
        self.scan_b.set_label("Stop scanning" if scanning else "Scan")
        ctx.clear_group(self.ad_group, self.ad_notes)
        if not st.get("available", True) and not has:
            self.ad_notes.append(ctx.note(self.ad_group, "bluetoothd isn't running. Start it: "
                                          "sudo systemctl enable --now bluetooth", "warn"))
        elif not has:
            self.ad_notes.append(ctx.note(self.ad_group, "No Bluetooth adapter found" + (
                ": the radio is blocked (rfkill)" if st.get("blocked") else " (a USB dongle? bluetoothd sees none)"),
                "warn"))
        elif st.get("hard_blocked"):
            self.ad_notes.append(ctx.note(self.ad_group, "Switched off by a hardware switch or key: turn it on there",
                                          "warn"))
        # the cards
        paired = st.get("paired", [])
        want = [d["mac"] for d in paired]
        shown = [c._bt_mac for c in self._grid_children()]
        if shown != want:
            child = self.grid.get_first_child()
            while child is not None:
                nxt = child.get_next_sibling()
                child.set_child(None)           # the card's button goes into a new child
                self.grid.remove(child)
                child = nxt
            for d in paired:
                c = self.cards.get(d["mac"]) or Card(self, d)
                self.cards[d["mac"]] = c
                fc = Gtk.FlowBoxChild()
                fc.set_child(c.b)
                fc._bt_mac = d["mac"]
                self.grid.append(fc)
        for d in paired:
            self.cards[d["mac"]].update(d)
        self.empty.set_visible(not paired)
        self.empty.set_text("Nothing paired yet. Pair a new device… walks you through it." if on else
                            "Bluetooth is off: switch it on above.")
        # nearby
        near = st.get("nearby", [])
        self.near_group.set_visible(on and (scanning or bool(near)))
        self.near_words.set_text((f"Scanning: {len(near)} found. " if scanning else f"{len(near)} found. ") +
                                 "Put the device in pairing mode, then Pair.")
        ctx.clear_group(self.near_group, self.near_rows)
        for d in near:
            r = ctx.row(self.near_group, d["name"], f"{d['kind']} · signal " + (
                "strong" if (d.get("rssi") or -100) > -60 else "good" if (d.get("rssi") or -100) > -75 else "weak"),
                hint=f"{d['name']}: not paired yet",
                buttons=[("Pair", lambda d=d: self.start_wizard(pair=d), f"Pairs with {d['name']}, then trusts and "
                          "connects it")])
            r.add_prefix(_area(36, 36, lambda cr, w, h, d=d: H.glyph(cr, d["glyph"], 0, 0, min(w, h), self.pal,
                                                                     still=True, hc=self.hc)))
            self.near_rows.append(r)
        # what went wrong lately
        ctx.clear_group(self.trouble, self.err_rows)
        for e in self.errors[-4:]:
            self.err_rows.append(ctx.note(self.trouble, e, "error"))
        self.radar.queue_draw()

    def _grid_children(self):
        c = self.grid.get_first_child()
        while c is not None:
            yield c
            c = c.get_next_sibling()

    def draw_radar(self, cr, w, h):
        now = time.monotonic()
        blips = [(d["mac"], d.get("rssi"), now - self.seen.get(d["mac"], now - 9)) for d in self.state.get("nearby", [])]
        H.radar(cr, 0, 0, min(w, h), self.pal, self.clock.t(), blips, still=self.clock.still, hc=self.hc)

    def problem(self, text):
        self.errors.append(text)
        self.ctx.toast(text, timeout=8)
        self.sync()

    def done(self, mac, said):
        def back(ok, err):
            self.ops.pop(mac, None)
            if ok:
                self.ctx.toast(said)
            else:
                self.problem(err)
            self.sync()
            if self.dialog is not None:
                self.dialog.sync()
        return back

    # ------------------------------------------------------------ actions
    def _power(self, on):
        self.bz.power(on, lambda ok, err: self.ctx.toast(f"Bluetooth {'on' if on else 'off'}") if ok else
                      self.problem(err))

    def _visible(self, on):
        self.bz.discoverable(on, lambda ok, err: self.ctx.toast("Visible nearby" if on else "Hidden") if ok else
                             self.problem(err))

    def _audio_default(self, on):
        self.ctx.change(BT + ["audio-default", "on" if on else "off", "--json"],
                        "Sound follows headphones" if on else "Sound stays put",
                        undo=BT + ["audio-default", "off" if on else "on", "--json"])

    def toggle_scan(self):
        a = self.state.get("adapter") or {}
        if a.get("discovering"):
            self.scan_until = 0.0
            self.bz.scan(False, lambda ok, err: None if ok else self.problem(err))
        else:
            self.scan_until = time.monotonic() + SCAN_SECS
            self.bz.scan(True, lambda ok, err: None if ok else self.problem(err))
            GLib.timeout_add_seconds(SCAN_SECS, self._scan_over)

    def _scan_over(self):
        if self.scan_until and time.monotonic() >= self.scan_until - 0.5:
            self.scan_until = 0.0
            self.bz.scan(False)
        return False

    def reset(self):
        self.ctx.toast("Switching the adapter off and on again…", timeout=3)
        self.bz.reset(lambda ok, err: self.ctx.toast("The adapter was switched off and on again") if ok else
                      self.problem(err))

    def connect(self, d):
        self.ops[d["mac"]] = "connecting"
        self.bz.connect(d["path"], self.done(d["mac"], f"{d['name']} connected"))
        self.sync()

    def disconnect(self, d):
        self.ops[d["mac"]] = "disconnecting"
        self.bz.disconnect(d["path"], self.done(d["mac"], f"{d['name']} disconnected"))
        self.sync()

    def open_device(self, mac):
        d = next((x for x in self.state.get("devices", []) if x["mac"] == mac), None)
        if d is None:
            return
        DeviceDialog(self, mac).present()

    def start_wizard(self, pair=None, kind=None):
        Wizard(self, pair, kind).present()

    def find(self, mac):
        return next((x for x in self.state.get("devices", []) if x["mac"] == mac), None)


# ------------------------------------------------------------------ a device's page
class DeviceDialog:
    def __init__(self, page, mac):
        self.p, self.mac = page, mac
        ctx = page.ctx
        d = page.find(mac)
        self.dlg = Adw.Dialog(title=d["name"], content_width=720, content_height=680)
        self.dlg.connect("closed", lambda *_: self.closed())
        tv = Adw.ToolbarView()
        tv.add_top_bar(Adw.HeaderBar())
        self.pp = Adw.PreferencesPage()
        tv.set_content(self.pp)
        self.dlg.set_child(tv)
        self.pad = self.pad_watch = self.mic = None
        self.mic_on = False

        # the hero: the hologram, the name, the state, battery and signal
        hero = Adw.PreferencesGroup()
        box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=18)
        self.holo = _area(180, 150, self.draw_holo)
        page.clock.watch(self.holo, lambda: bool(page.find(mac) and (page.find(mac)["connected"] or mac in page.ops)))
        box.append(self.holo)
        words = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6, valign=Gtk.Align.CENTER, hexpand=True)
        self.title = Gtk.Label(xalign=0, wrap=True)
        self.title.add_css_class("bt-title")
        self.sub = Gtk.Label(xalign=0, wrap=True)
        self.sub.add_css_class("dim-label")
        self.meter = _area(220, 14, self.draw_meter)
        self.act = Gtk.Button(halign=Gtk.Align.START)
        self.act.add_css_class("pill")
        self.act.connect("clicked", lambda *_: self.toggle())
        for w in (self.title, self.sub, self.meter, self.act):
            words.append(w)
        box.append(words)
        hero.add(box)
        self.pp.add(hero)

        # a controller: its input, live, and its rumble
        self.ctl = None
        if d["glyph"] == "controller":
            self.ctl = Adw.PreferencesGroup(title="TEST THE CONTROLLER",
                                            description="Press anything: its buttons light up, the sticks and "
                                                        "triggers move.")
            self.pad_area = _area(560, 190, self.draw_pad, "What the controller sends now")
            self.ctl.add(self.pad_area)
            keys = Gtk.FlowBox(selection_mode=Gtk.SelectionMode.NONE, max_children_per_line=14, column_spacing=4,
                               row_spacing=4)
            self.keys = {}
            for k in ("LB", "RB", "LT", "RT", "VIEW", "XBOX", "MENU", "SHARE", "LS", "RS", "UP", "DOWN", "LEFT",
                      "RIGHT", "A", "B", "X", "Y"):
                lab = Gtk.Label(label=k)
                lab.add_css_class("bt-key")
                lab.set_tooltip_text(f"{k}: lights up while it's held")
                keys.append(lab)
                self.keys[k] = lab
            self.ctl.add(keys)
            self.pad_msg = Gtk.Label(xalign=0, wrap=True)
            self.pad_msg.add_css_class("dim-label")
            self.ctl.add(self.pad_msg)
            self.pp.add(self.ctl)
            self.ctl = Adw.PreferencesGroup(title="CONTROLLER")
            ctx.row(self.ctl, "Rumble", "Both motors, for half a second", hint="Shakes the controller (xpadneo's "
                    "driver can; the kernel's basic one often can't)", buttons=[("Rumble", self.rumble,
                                                                                   "Shakes the controller")])
            self.driver_rows = []
            self.pp.add(self.ctl)
            self.pad_axes = {"lx": 0.0, "ly": 0.0, "rx": 0.0, "ry": 0.0, "lt": 0.0, "rt": 0.0}
            self.pad_buttons = []

        # sound: the profile, the codec, output and microphone, a mic test
        self.snd = None
        if d.get("audio") and not d.get("audio_source"):
            self.snd = Adw.PreferencesGroup(title="SOUND")
            self.prof = ctx.toggle_group(
                [("hifi", "Hi-fi", B.MODE_HINT["hifi"]), ("headset", "Headset + mic", B.MODE_HINT["headset"])],
                on_select=self.profile, hint="Hi-fi plays music at full quality; Headset + mic turns the microphone on "
                                             "and drops the sound to call quality")
            self.prof_row = ctx.row(self.snd, "Sound profile", "", control=self.prof,
                                    hint="Which way it's used: music, or calls")
            self.codec_row = ctx.row(self.snd, "Codec", "", hint="How the sound is squeezed to travel over Bluetooth: "
                                     "the best both sides share")
            self.def_row = ctx.row(self.snd, "Use it", "", hint="Make it the sound output or the microphone",
                                   buttons=[("Sound output", lambda: self.default("output"),
                                             "Makes it the sound output: what's playing moves to it"),
                                            ("Microphone", lambda: self.default("input"),
                                             "Makes its microphone the one apps hear (needs Headset + mic)")])
            self.level = Gtk.LevelBar(min_value=0, max_value=1, hexpand=True, valign=Gtk.Align.CENTER)
            self.level.set_size_request(160, -1)
            self.mic_b = ctx.button("Test", self.mic_test, "Shows the microphone's level as you speak")
            box2 = Gtk.Box(spacing=8)
            box2.append(self.level)
            box2.append(self.mic_b)
            ctx.row(self.snd, "Microphone test", "Speak: the bar follows your voice", control=box2,
                    hint="The microphone's level, live (needs Headset + mic)")
            self.pp.add(self.snd)

        # every device
        g = Adw.PreferencesGroup(title="DEVICE")
        self.name_row = ctx.entry_row(g, "Name", text=d["name"], on_apply=self.rename,
                                      hint="The name shown here, on the bar and in other apps (bluez's alias)")
        self.trust_row = ctx.switch_row(g, "Auto-reconnect", "Connects by itself when it's switched on (trusted)",
                                        on_toggle=self.trust, hint="On: it reconnects by itself. Off: it asks first")
        ctx.row(g, "Re-pair", "Forget it, then pair it again: for one that connects and drops, or after a firmware "
                "update", hint="Forgets it and opens the pairing steps",
                buttons=[("Re-pair…", self.repair, "Forgets it and starts pairing it again")])
        ctx.row(g, "Forget", "Unpair it: using it again means pairing it again", hint="Removes the pairing",
                buttons=[("Forget…", self.forget, "Unpairs it (asks first)")])
        ctx.row(g, "Address", d["mac"], hint="Its Bluetooth address")
        self.pp.add(g)
        page.dialog = self
        self.sync()
        if self.ctl is not None and d["connected"]:
            self.start_pad()

    def present(self):
        self.dlg.present(self.p.ctx.window)

    def closed(self):
        self.stop_pad()
        self.stop_mic()
        if self.p.dialog is self:
            self.p.dialog = None
        self.p.clock.forget(self.holo)

    @property
    def d(self):
        return self.p.find(self.mac)

    def draw_holo(self, cr, w, h):
        d = self.d
        if d is None:
            return
        size = min(w, h)
        H.glyph(cr, d["glyph"], (w - size) / 2, 0, size, self.p.pal, t=self.p.clock.t(), live=d["connected"],
                fx=self.p.fx_of(self.mac), still=self.p.clock.still, hc=self.p.hc,
                lit=[i for i, k in enumerate(("A", "B", "X", "Y")) if k in getattr(self, "pad_buttons", [])])

    def draw_meter(self, cr, w, h):
        d = self.d
        if d and d.get("battery") is not None:
            H.cells(cr, 0, 2, w * 0.7, h - 4, d["battery"], self.p.pal, n=10)
        if d and d.get("rssi") is not None:
            H.bars(cr, w * 0.78, 0, h, d["rssi"], self.p.pal)

    def draw_pad(self, cr, w, h):
        pal, a = self.p.pal, self.pad_axes
        H.glyph(cr, "controller", 0, 0, h, pal, live=True, still=True, hc=self.p.hc,
                lit=[i for i, k in enumerate(("A", "B", "X", "Y")) if k in self.pad_buttons])
        # the sticks: a ring each, the dot where it points
        import math
        for i, (x, y) in enumerate(((a["lx"], a["ly"]), (a["rx"], a["ry"]))):
            cx, cy, r = h + 70 + i * 120, h / 2 - 10, 42
            H._src(cr, pal, "dim", 0.9)
            cr.set_line_width(1)
            cr.arc(cx, cy, r, 0, 2 * math.pi)
            cr.stroke()
            H._src(cr, pal, "primary", 1)
            cr.arc(cx + x * r, cy + y * r, 6, 0, 2 * math.pi)
            cr.fill()
        # the triggers: two bars
        for i, v in enumerate((a["lt"], a["rt"])):
            H.cells(cr, h + 28 + i * 120, h - 30, 84, 10, int(v * 100), pal, n=12)

    def sync(self):
        d = self.d
        if d is None:
            self.dlg.close()
            return
        p, ctx = self.p, self.p.ctx
        audio = p.state.get("audio_cards", {}).get(self.mac)
        self.dlg.set_title(d["name"])
        self.title.set_text(d["name"])
        b = d.get("battery")
        self.sub.set_text(f"{d['kind'].capitalize()} · {_words(d, audio, p.ops.get(self.mac))}" +
                          (f" · battery {b}%" if b is not None else ""))
        self.act.set_label("Disconnect" if d["connected"] else "Connect")
        self.act.set_tooltip_text(("Disconnects" if d["connected"] else "Connects") + f" {d['name']}")
        self.act.set_sensitive(self.mac not in p.ops and p.state.get("powered", False))
        (self.act.remove_css_class if d["connected"] else self.act.add_css_class)("suggested-action")
        self.trust_row.set_quiet(d["trusted"])
        self.holo.queue_draw()
        self.meter.queue_draw()
        if self.ctl is not None:
            ctx.clear_group(self.ctl, self.driver_rows)
            if d.get("xbox") and not B.xpadneo_loaded():
                r = ctx.row(self.ctl, "Basic driver", "Rumble, the battery and the right button layout need xpadneo, "
                            "the Xbox controllers' full driver", hint="bromigos peripheral enable xbox-controller",
                            buttons=[("Set up…", lambda: ctx.terminal(["bromigos", "peripheral", "enable",
                                                                         "xbox-controller"]),
                                      "Installs xpadneo for your kernels in a terminal (it asks for your password); "
                                      "switch the controller off and on after")])
                self.driver_rows.append(r)
            if d["connected"] and self.pad is None:
                self.start_pad()
            if not d["connected"]:
                self.stop_pad()
                self.pad_msg.set_text("Connect it to test its buttons and sticks.")
        if self.snd is not None:
            on = d["connected"] and audio is not None
            self.prof.set_sensitive(on and bool(audio and audio.get("hifi") and audio.get("headset")))
            if audio and audio.get("mode") in ("hifi", "headset"):
                self.prof.set_quiet(audio["mode"])
            self.codec_row.set_subtitle(GLib.markup_escape_text((audio or {}).get("codec") or
                                                                ("—" if d["connected"] else "Not connected")))
            self.def_row.set_sensitive(on)

    # -- actions
    def toggle(self):
        d = self.d
        (self.p.disconnect if d["connected"] else self.p.connect)(d)

    def rename(self, text):
        d = self.d
        name = (text or "").strip()
        if not name:
            self.p.problem("A name can't be empty")
            return
        self.p.bz.rename(d["path"], name, self.p.done(self.mac, f"Renamed to {name}"))

    def trust(self, on):
        d = self.d
        self.p.bz.trust(d["path"], on, self.p.done(self.mac, f"{d['name']}: " + (
            "reconnects by itself" if on else "asks before connecting")))

    def forget(self):
        d = self.d
        self.p.ctx.confirm(f"Forget {d['name']}?", "It's unpaired: using it again means pairing it again.", "Forget",
                           lambda: (self.p.bz.forget(d["path"], self.p.done(self.mac, f"Forgot {d['name']}")),
                                    self.dlg.close()), destructive=True)

    def repair(self):
        d = self.d
        page = self.p

        def go():
            page.bz.forget(d["path"], lambda ok, err: (page.start_wizard(kind=d["glyph"]) if ok else page.problem(err)))
            self.dlg.close()
        page.ctx.confirm(f"Re-pair {d['name']}?", "It's forgotten, then the pairing steps open: put it in pairing "
                         "mode when they say.", "Re-pair", go)

    def profile(self, mode):
        def got(doc, err):
            if not doc or doc.get("ok") is False:
                self.p.problem((doc or {}).get("error") or err or "The profile didn't change")
            else:
                self.p.ctx.toast(doc.get("said") or "Profile changed")
            self.p.refresh_audio()
        self.p.ctx.json(BT + ["profile", self.mac, mode, "--json"], got)

    def default(self, side):
        name = (self.p.state.get("sound", {}).get("devices", {}).get(self.mac) or {}).get(side)
        if not name:
            self.p.problem("It has no microphone now: switch it to Headset + mic" if side == "input" else
                           "It has no sound output now: is it connected?")
            return
        self.p.ctx.change(["bromigos", "sound", side, name, "--json"],
                          "The sound now plays there" if side == "output" else "Apps now hear its microphone")

    def rumble(self):
        pad, temp = self.pad, None
        if pad is None:
            path = G.find(self.mac)
            if path is None:
                self.p.problem("Its input device isn't there: is it connected and switched on?")
                return
            pad = temp = G.Pad(path)
        ok = pad.rumble(0.7, 0.7, 450)
        if temp is not None:
            GLib.timeout_add(600, lambda: temp.close() and False)
        if not ok:
            self.p.problem("Its driver doesn't rumble: xpadneo does (Set up… above)")

    def start_pad(self):
        if self.pad is not None:
            return
        path = G.find(self.mac)
        if path is None:
            self.pad_msg.set_text("Its input device isn't there yet: is it switched on?")
            return
        try:
            self.pad = G.Pad(path)
        except OSError as e:
            self.pad_msg.set_text(f"Can't read {path}: {e.strerror}")
            return
        self.pad_msg.set_text(f"Reading {path}")
        self.pad_watch = GLib.io_add_watch(self.pad.fd, GLib.PRIORITY_DEFAULT, GLib.IOCondition.IN |
                                           GLib.IOCondition.HUP | GLib.IOCondition.ERR, self._pad)

    def _pad(self, fd, cond):
        try:
            if cond & (GLib.IOCondition.HUP | GLib.IOCondition.ERR):
                raise OSError("gone")
            self.pad.read()
        except OSError:
            self.pad_msg.set_text("The controller went away")
            self.pad_watch = None
            self.stop_pad()
            return False
        self.pad_buttons = self.pad.buttons
        self.pad_axes = dict(self.pad.axes)
        for k, lab in self.keys.items():
            (lab.add_css_class if k in self.pad_buttons or (k == "LT" and self.pad_axes["lt"] > 0.5) or
             (k == "RT" and self.pad_axes["rt"] > 0.5) else lab.remove_css_class)("bt-lit")
        self.pad_area.queue_draw()
        self.holo.queue_draw()
        return True

    def stop_pad(self):
        if self.pad_watch is not None:
            GLib.source_remove(self.pad_watch)
            self.pad_watch = None
        if self.pad is not None:
            self.pad.close()
            self.pad = None

    def mic_test(self):
        if self.mic is not None:
            self.stop_mic()
            return
        name = (self.p.state.get("sound", {}).get("devices", {}).get(self.mac) or {}).get("input")
        if not name:
            self.p.problem("It has no microphone now: switch it to Headset + mic")
            return
        try:
            self.mic = Gio.Subprocess.new(["parec", "--raw", "--format=s16le", "--rate=16000", "--channels=1",
                                           "--latency-msec=50", "-d", name],
                                          Gio.SubprocessFlags.STDOUT_PIPE | Gio.SubprocessFlags.STDERR_SILENCE)
        except Exception as e:
            self.p.problem(f"parec: {e}")
            return
        self.mic_b.set_label("Stop")
        mic, stream = self.mic, self.mic.get_stdout_pipe()

        def got(s, res):
            if self.mic is not mic:
                return
            try:
                data = s.read_bytes_finish(res).get_data()
            except Exception:
                data = b""
            if not data:
                self.stop_mic()
                return
            self.level.set_value(mic_level(data))
            s.read_bytes_async(1600, GLib.PRIORITY_DEFAULT, None, got)
        stream.read_bytes_async(1600, GLib.PRIORITY_DEFAULT, None, got)

    def stop_mic(self):
        if self.mic is not None:
            self.mic.force_exit()
            self.mic = None
        if self.snd is not None:
            self.mic_b.set_label("Test")
            self.level.set_value(0)


# ------------------------------------------------------------------ pairing, step by step
class Wizard:
    """1 what it is · 2 pairing mode and the scan · 3 pairing (with any code) · 4 ready."""

    def __init__(self, page, pair=None, kind=None):
        self.p = page
        self.kind = 0
        if kind:
            self.kind = next((i for i, k in enumerate(B.PAIR_KINDS) if B.fits(kind, k[1])), len(B.PAIR_KINDS) - 1)
        self.target = None
        self.reply = None
        self.dlg = Adw.Dialog(title="Pairing", content_width=640, content_height=600)
        self.dlg.connect("closed", lambda *_: self.closed())
        tv = Adw.ToolbarView()
        tv.add_top_bar(Adw.HeaderBar())
        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        for side in ("top", "bottom", "start", "end"):
            getattr(outer, f"set_margin_{side}")(18)
        self.steps = Gtk.Box(spacing=12)
        self.step_labels = []
        for i, name in enumerate(("1 What it is", "2 Pairing mode", "3 Pair", "4 Ready")):
            lab = Gtk.Label(label=name)
            lab.add_css_class("bt-step")
            self.steps.append(lab)
            self.step_labels.append(lab)
        outer.append(self.steps)
        self.stack = Gtk.Stack(transition_type=Gtk.StackTransitionType.NONE, vexpand=True)
        outer.append(self.stack)
        tv.set_content(outer)
        self.dlg.set_child(tv)
        self._kind_page()
        self._scan_page()
        self._pair_page()
        self._ready_page()
        page.wizard = self
        if pair is not None:
            self.kind = next((i for i, k in enumerate(B.PAIR_KINDS) if B.fits(pair["glyph"], k[1])),
                             len(B.PAIR_KINDS) - 1)
            self.go_pair(pair)
        else:
            self.show("kind")

    def present(self):
        self.dlg.present(self.p.ctx.window)

    def closed(self):
        if self.target is not None and self.p.ops.get(self.target["mac"]):
            self.p.bz.cancel_pair(self.target["path"])
        if self.p.wizard is self:
            self.p.wizard = None
        self.p.clock.forget(self.radar)

    def show(self, name):
        self.stack.set_visible_child_name(name)
        at = ["kind", "scan", "pair", "ready"].index(name if name != "failed" else "pair")
        for i, lab in enumerate(self.step_labels):
            (lab.add_css_class if i == at else lab.remove_css_class)("bt-now")

    def _kind_page(self):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        t = Gtk.Label(label="What are you pairing?", xalign=0)
        t.add_css_class("bt-title")
        box.append(t)
        grid = Gtk.FlowBox(selection_mode=Gtk.SelectionMode.NONE, homogeneous=True, max_children_per_line=3,
                           column_spacing=10, row_spacing=10)
        for i, (name, glyph, steps) in enumerate(B.PAIR_KINDS):
            b = Gtk.Button()
            b.add_css_class("bt-card")
            v = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
            v.append(_area(120, 70, lambda cr, w, h, g=glyph: H.glyph(cr, g, (w - h) / 2, 0, h, self.p.pal, still=True,
                                                                      live=True, hc=self.p.hc)))
            v.append(Gtk.Label(label=name))
            b.set_child(v)
            b.set_tooltip_text(f"{name}: then it says how to put it in pairing mode")
            b.connect("clicked", lambda *_, i=i: self.pick_kind(i))
            grid.append(b)
        box.append(grid)
        self.stack.add_named(box, "kind")

    def _scan_page(self):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        top = Gtk.Box(spacing=16)
        self.radar = _area(120, 120, self.draw_radar, "The scan: each dot is a device found")
        self.p.clock.watch(self.radar, lambda: bool((self.p.state.get("adapter") or {}).get("discovering")))
        top.append(self.radar)
        words = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6, hexpand=True)
        self.how_title = Gtk.Label(xalign=0)
        self.how_title.add_css_class("bt-title")
        self.how = Gtk.Label(xalign=0, wrap=True)
        words.append(self.how_title)
        words.append(self.how)
        top.append(words)
        box.append(top)
        self.found_words = Gtk.Label(xalign=0)
        self.found_words.add_css_class("dim-label")
        box.append(self.found_words)
        self.found = Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE)
        self.found.add_css_class("boxed-list")
        sc = Gtk.ScrolledWindow(vexpand=True, hscrollbar_policy=Gtk.PolicyType.NEVER)
        sc.set_child(self.found)
        box.append(sc)
        row = Gtk.Box(spacing=8)
        back = Gtk.Button(label="Back")
        back.connect("clicked", lambda *_: self.show("kind"))
        back.set_tooltip_text("Choose another kind")
        again = Gtk.Button(label="Scan again")
        again.connect("clicked", lambda *_: self.scan())
        again.set_tooltip_text("Looks again for devices in pairing mode")
        row.append(back)
        row.append(again)
        box.append(row)
        self.stack.add_named(box, "scan")

    def _pair_page(self):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12, valign=Gtk.Align.CENTER)
        self.pair_title = Gtk.Label()
        self.pair_title.add_css_class("bt-title")
        self.spinner = Adw.Spinner()
        self.pair_step = Gtk.Label(wrap=True)
        self.ask = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8, halign=Gtk.Align.CENTER)
        self.retry = Gtk.Button(label="Try again", halign=Gtk.Align.CENTER)
        self.retry.add_css_class("suggested-action")
        self.retry.connect("clicked", lambda *_: (self.show("scan"), self.scan()))
        self.retry.set_tooltip_text("Back to the scan: put it in pairing mode again first")
        for w in (self.pair_title, self.spinner, self.pair_step, self.ask, self.retry):
            box.append(w)
        self.stack.add_named(box, "pair")

    def _ready_page(self):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12, valign=Gtk.Align.CENTER)
        self.ready_holo = _area(200, 140, self.draw_ready)
        box.append(self.ready_holo)
        self.ready_words = Gtk.Label(wrap=True, justify=Gtk.Justification.CENTER)
        self.ready_words.add_css_class("bt-title")
        box.append(self.ready_words)
        sub = Gtk.Label(label="It reconnects by itself whenever it's switched on.")
        sub.add_css_class("dim-label")
        box.append(sub)
        row = Gtk.Box(spacing=8, halign=Gtk.Align.CENTER)
        openb = Gtk.Button(label="Open its page")
        openb.add_css_class("suggested-action")
        openb.connect("clicked", lambda *_: (self.dlg.close(), self.p.open_device(self.target["mac"])))
        openb.set_tooltip_text("Its page: test it, its sound, rename")
        done = Gtk.Button(label="Done")
        done.connect("clicked", lambda *_: self.dlg.close())
        row.append(openb)
        row.append(done)
        box.append(row)
        self.stack.add_named(box, "ready")

    # -- the steps
    def pick_kind(self, i):
        self.kind = i
        name, glyph, steps = B.PAIR_KINDS[i]
        self.how_title.set_text(f"Put the {name.lower()} in pairing mode")
        self.how.set_text("\n".join(steps))
        self.show("scan")
        self.scan()
        self.sync()

    def scan(self):
        a = self.p.state.get("adapter") or {}
        if not a.get("discovering"):
            self.p.toggle_scan()

    def draw_radar(self, cr, w, h):
        self.p.draw_radar(cr, w, h)

    def draw_ready(self, cr, w, h):
        if self.target is None:
            return
        d = self.p.find(self.target["mac"]) or self.target
        H.glyph(cr, d["glyph"], (w - h) / 2, 0, h, self.p.pal, t=self.p.clock.t(), live=True,
                fx=self.p.fx_of(d["mac"]), still=self.p.clock.still, hc=self.p.hc)

    def sync(self):
        if self.stack.get_visible_child_name() == "scan":
            glyph = B.PAIR_KINDS[self.kind][1]
            near = sorted(self.p.state.get("nearby", []), key=lambda d: (not B.fits(d["glyph"], glyph),
                                                                         -(d.get("rssi") or -200)))
            child = self.found.get_first_child()
            while child is not None:
                nxt = child.get_next_sibling()
                self.found.remove(child)
                child = nxt
            scanning = bool((self.p.state.get("adapter") or {}).get("discovering"))
            self.found_words.set_text((f"Scanning… {len(near)} found" if scanning else f"{len(near)} found") +
                                      (": pick yours" if near else ""))
            for d in near:
                r = Adw.ActionRow(title=GLib.markup_escape_text(d["name"]),
                                  subtitle=GLib.markup_escape_text(d["kind"]))
                r.add_prefix(_area(36, 36, lambda cr, w, h, d=d: H.glyph(cr, d["glyph"], 0, 0, min(w, h), self.p.pal,
                                                                         still=True, live=True, hc=self.p.hc)))
                b = Gtk.Button(label="Pair", valign=Gtk.Align.CENTER)
                b.add_css_class("suggested-action")
                b.set_tooltip_text(f"Pairs with {d['name']}")
                b.connect("clicked", lambda *_, d=d: self.go_pair(d))
                r.add_suffix(b)
                self.found.append(r)
        self.radar.queue_draw()
        self.ready_holo.queue_draw()

    def go_pair(self, d):
        self.target = d
        self.show("pair")
        self.pair_title.set_text(f"Pairing with {d['name']}")
        self.spinner.set_visible(True)
        self.retry.set_visible(False)
        self.pair_step.set_text("Pairing…")
        self._clear_ask()
        page = self.p
        page.ops[d["mac"]] = "pairing"
        _busy(True)

        def step(word):
            page.ops[d["mac"]] = word
            self.pair_step.set_text({"pairing": "Pairing…", "trusting": "Saving it, so it reconnects by itself…",
                                     "connecting": "Connecting…"}.get(word, word))
            page.sync()

        def finished(ok, err):
            _busy(False)
            page.ops.pop(d["mac"], None)
            self._clear_ask()
            if ok:
                page.fx[d["mac"]] = ("spark", time.monotonic())
                self.ready_words.set_text(f"Ready: {d['name']} is paired and connected")
                self.show("ready")
            else:
                self.spinner.set_visible(False)
                self.pair_step.set_text(err)
                self.retry.set_visible(True)
                page.problem(f"{d['name']}: {err}")
            page.sync()

        def go(ok=True, err=None):
            if not ok:
                finished(False, err)
                return
            page.bz.pair(d["path"], finished, step)
        if page.bz.agent is None:
            page.bz.register_agent(B.Agent(self), go)
        else:
            page.bz.agent.ui = self
            go()

    # the agent's questions, asked right here
    def _clear_ask(self):
        child = self.ask.get_first_child()
        while child is not None:
            nxt = child.get_next_sibling()
            self.ask.remove(child)
            child = nxt

    def prompt(self, what, path, value, reply):
        self._clear_ask()
        d = next((x for x in self.p.state.get("devices", []) if x["path"] == path), None)
        name = d["name"] if d else B.mac_of(path)
        self.reply = reply

        def answer(v):
            r, self.reply = self.reply, None
            self._clear_ask()
            if r is not None:
                r(v)
            if v in (None, False) and self.target is not None:
                self.p.bz.cancel_pair(self.target["path"])

        def say(text, code=None):
            lab = Gtk.Label(label=text, wrap=True, justify=Gtk.Justification.CENTER)
            self.ask.append(lab)
            if code:
                c = Gtk.Label(label=code)
                c.add_css_class("bt-code")
                self.ask.append(c)

        def buttons(*items):
            row = Gtk.Box(spacing=8, halign=Gtk.Align.CENTER)
            for label, v, hint, main in items:
                b = Gtk.Button(label=label)
                if main:
                    b.add_css_class("suggested-action")
                b.set_tooltip_text(hint)
                b.connect("clicked", lambda *_, v=v: answer(v() if callable(v) else v))
                row.append(b)
            self.ask.append(row)
        if what == "confirm":
            say(f"Does {name} show this code?", f"{value[:3]} {value[3:]}")
            buttons(("Yes, pair", True, "The codes match: pair", True), ("No", False, "They don't match: stop", False))
        elif what in ("pin", "passkey"):
            say("Type the PIN it asks for. It's often 0000 or 1234: its manual says." if what == "pin" else
                "Type the 6-digit number it shows.")
            e = Gtk.Entry(max_length=16, halign=Gtk.Align.CENTER, input_purpose=Gtk.InputPurpose.DIGITS
                          if what == "passkey" else Gtk.InputPurpose.FREE_FORM)
            e.set_tooltip_text("The code, then Enter")
            e.connect("activate", lambda *_: answer(e.get_text().strip() or None))
            self.ask.append(e)
            buttons(("Pair", lambda: e.get_text().strip() or None, "Sends the code", True),
                    ("Cancel", None, "Stops pairing", False))
            e.grab_focus()
        elif what == "type":
            code, typed = value
            say(f"On {name}, type this code, then press Enter:", f"{code[:3]} {code[3:]}")
            buttons(("Cancel", None, "Stops pairing", False))
        elif what == "show-pin":
            say(f"On {name}, enter this PIN:", str(value))
        else:
            say(f"{name} asks to pair with this computer.")
            buttons(("Allow", True, "Lets it pair", True), ("Deny", False, "Stops it", False))

    def cancel(self):
        self._clear_ask()
        self.pair_step.set_text("The device stopped pairing (cancelled, or it took too long).")


def _busy(on):
    run = os.environ.get("XDG_RUNTIME_DIR") or f"/run/user/{os.getuid()}"
    p = os.path.join(run, "bromigos-bluetooth-busy")
    try:
        if on:
            with open(p, "w") as f:
                f.write(str(os.getpid()))
        else:
            os.unlink(p)
    except OSError:
        pass


def build(ctx):
    p = BluetoothPage(ctx)
    p.page._bt = p
    return p.page


def refresh(widget):
    widget._bt.sync()


PAGE = Page(
    id="bluetooth", title="Bluetooth", group="system", order=40, build=build, refresh=refresh,
    docs="settings.md#bluetooth", icon="bluetooth-active-symbolic bluetooth-symbolic network-bluetooth-symbolic",
    summary="devices, pairing",
    intro="Your Bluetooth devices: connect one, pair a new one step by step, test a controller, switch a headset's "
          "sound. Changes apply at once.",
    keywords=["bt", "bluez", "wireless devices", "headphones", "controller", "devices", "gamepad", "xbox", "earbuds"],
    entries=[
        Entry("power", "Bluetooth", ["bluetooth on", "bluetooth off", "adapter", "rfkill"], "Adapter"),
        Entry("discoverable", "Visible to devices nearby", ["discoverable", "visible", "findable"], "Adapter"),
        Entry("audio-default", "Switch the sound over on connect",
              ["audio switch", "bluetooth audio", "follow"], "Adapter"),
        Entry("pair-wizard", "Pair a new device", ["pair", "pairing", "add bluetooth device", "add controller",
                                                    "pair headphones", "pair controller", "connect controller"],
              "My devices"),
        Entry("paired", "My devices", ["connect headphones", "disconnect", "battery", "forget device", "unpair",
                                       "controller test", "rumble", "codec", "rename"], "My devices"),
        Entry("scan", "Look for devices", ["scan", "search devices", "find devices"], "My devices"),
        Entry("nearby", "Nearby", ["pair nearby"], "Nearby"),
        Entry("reset", "Reset the adapter", ["bluetooth not working", "reset bluetooth", "restart bluetooth"],
              "Troubleshooting"),
        Entry("repair", "Re-pair a device", ["re-pair", "repair", "keeps disconnecting"], "Troubleshooting"),
        Entry("tui", "In a terminal", ["tui", "terminal"], "Troubleshooting"),
        Entry("console", "bluetoothctl", ["pin", "passkey", "pairing code"], "Troubleshooting"),
    ])
