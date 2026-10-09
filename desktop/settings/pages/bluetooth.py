"""Bluetooth: the adapter (on, visible to devices nearby), the paired devices (connect,
disconnect, battery, forget), and finding and pairing new ones (docs/settings.md, "Bluetooth").

Everything goes through `bromigos bluetooth … --json` (bluez through bluetoothctl). A device
that asks for a PIN or a passkey is paired in bluetoothctl itself, in a terminal: the page
says so and opens it, rather than pretending."""
import json

from gi.repository import GLib

from bromigos_settings import Entry, Page

BT = ["bromigos", "bluetooth"]
KIND_ICON = {"headset": "audio-headset-symbolic", "headphones": "audio-headphones-symbolic",
             "speaker": "audio-speakers-symbolic", "keyboard": "input-keyboard-symbolic", "mouse": "input-mouse-symbolic",
             "game controller": "input-gaming-symbolic", "tablet": "input-tablet-symbolic", "phone": "phone-symbolic",
             "computer": "computer-symbolic", "camera": "camera-photo-symbolic", "printer": "printer-symbolic"}


def _icon(ctx, d):
    return ctx.icon(KIND_ICON.get(d["kind"]), d.get("icon") and d["icon"] + "-symbolic", "bluetooth-active-symbolic",
                    "bluetooth-symbolic")


class BluetoothPage:
    def __init__(self, ctx):
        self.ctx = ctx
        self.doc = None
        self.sig = None
        self.scanning = False
        self.problem = None
        self.page = ctx.page()
        self.page.set_reset(None, hint="Nothing here has a bromigOS default: the paired devices are this machine's own "
                                       "(bluez keeps them)")
        self._static()
        self.refresh()
        GLib.timeout_add_seconds(6, self._tick)

    def _static(self):
        ctx = self.ctx
        self.ad_group = ctx.group(self.page, "Adapter", "This machine's Bluetooth.", key="adapter")
        self.power_row = ctx.switch_row(
            self.ad_group, "Bluetooth", "", key="power", on_toggle=self._power,
            hint="Turns Bluetooth on or off (a block from rfkill is lifted first)",
            advanced={"runs": "bromigos bluetooth power on|off", "note": "bluetoothctl power on|off; rfkill unblock bluetooth"})
        self.vis_row = ctx.switch_row(
            self.ad_group, "Visible to devices nearby", "So a phone or another computer can find this one and pair",
            key="discoverable", on_toggle=self._visible,
            hint="Lets other devices find this machine (bluez turns it off again after 3 minutes)",
            advanced={"runs": "bromigos bluetooth discoverable on|off"})
        self.ad_notes = []
        self.paired_group = ctx.group(self.page, "Paired devices", "Devices this machine knows: connect one, or forget "
                                      "it.", key="paired")
        self.paired_rows = []
        self.near_group = ctx.group(self.page, "Nearby", "Devices in pairing mode nearby. Put the device in pairing "
                                    "mode first (often a long press on its button), then Scan.", key="nearby")
        self.scan_row = ctx.row(self.near_group, "Look for devices", "Scans for 8 seconds", key="scan",
                                hint="Scans for Bluetooth devices nearby",
                                buttons=[("Scan", self._scan, "Scans for devices nearby for 8 seconds")],
                                advanced={"runs": "bromigos bluetooth scan 8", "note": "bluetoothctl --timeout 8 scan on"})
        self.near_rows = []
        g = ctx.group(self.page, "By hand")
        ctx.row(g, "bluetoothctl", "bluez's own console: for a device that asks for a PIN or a passkey",
                key="console", hint="Opens bluetoothctl in a terminal (type `help` there)",
                buttons=[("Open", lambda: ctx.terminal(["bluetoothctl"]), "Opens bluetoothctl in a terminal")],
                advanced={"runs": "bluetoothctl"})

    # ------------------------------------------------------------------ state
    def refresh(self):
        self.ctx.json(BT + ["--json"], self._got)

    def _tick(self):
        if self.page.get_mapped() and not self.scanning:
            self.refresh()
        return True

    def _got(self, doc, err):
        if not doc or doc.get("ok") is False:
            if self.problem is None:
                self.problem = self.ctx.failed(self.ad_group, BT + ["--json"], (doc or {}).get("error") or err)
            for r in (self.power_row, self.vis_row):
                r.set_sensitive(False)
            return
        if self.problem is not None:
            self.ad_group.remove(self.problem)
            self.problem = None
        self.sync(doc)

    def sync(self, d):
        self.doc = d
        ctx = self.ctx
        has = d.get("adapter") is not None
        self.power_row.set_sensitive(has and not d.get("hard_blocked"))
        self.power_row.set_quiet(d.get("powered", False))
        self.power_row.set_subtitle(GLib.markup_escape_text(
            f"{d['adapter']['alias']} ({d['adapter']['mac']})" if has else "No adapter"))
        self.vis_row.set_sensitive(has and d.get("powered", False))
        self.vis_row.set_quiet(d.get("discoverable", False))
        self.scan_row.set_sensitive(has and d.get("powered", False) and not self.scanning)
        sig = json.dumps([has, d.get("powered"), d.get("blocked"), d.get("hard_blocked"),
                          [(x["mac"], x["paired"], x["connected"], x["trusted"], x["battery"]) for x in d["devices"]]])
        if sig == self.sig:
            return
        self.sig = sig
        ctx.clear_group(self.ad_group, self.ad_notes)
        if not has:
            self.ad_notes.append(ctx.note(
                self.ad_group, "No Bluetooth adapter" + (": the radio is blocked (rfkill)" if d.get("blocked") else
                                                         " found (a USB dongle? bluetoothd sees none)"), "warn"))
        elif d.get("hard_blocked"):
            self.ad_notes.append(ctx.note(self.ad_group, "Switched off by a hardware switch or key: turn it on there",
                                          "warn"))
        self._paired()
        self._nearby()

    def _paired(self):
        ctx, d = self.ctx, self.doc
        ctx.clear_group(self.paired_group, self.paired_rows)
        if not d["paired"]:
            self.paired_rows.append(ctx.note(self.paired_group, "No paired devices yet: Scan below", "note"))
        for x in d["paired"]:
            bits = ["connected" if x["connected"] else "not connected"]
            if x["battery"] is not None:
                bits.append(f"battery {x['battery']}%")
            if not x["trusted"]:
                bits.append("asks before connecting")
            if x["connected"]:
                act = ("Disconnect", lambda x=x: self._do(["disconnect", x["mac"]], f"{x['name']} disconnected",
                                                          ["connect", x["mac"]]), f"Disconnects {x['name']}")
            else:
                act = ("Connect", lambda x=x: self._do(["connect", x["mac"]], f"{x['name']} connected",
                                                       ["disconnect", x["mac"]]), f"Connects {x['name']}")
            r = ctx.row(self.paired_group, x["name"], " · ".join(bits),
                        hint=f"{x['name']} ({x['kind']}, {x['mac']})",
                        buttons=[act, ("Forget…", lambda x=x: self._remove(x), f"Unpairs {x['name']}")],
                        advanced={"runs": f"bromigos bluetooth connect|disconnect|remove {x['mac']}"})
            r.add_prefix(_icon(ctx, x))
            r.set_sensitive(d.get("powered", False))
            self.paired_rows.append(r)

    def _nearby(self):
        ctx, d = self.ctx, self.doc
        ctx.clear_group(self.near_group, self.near_rows)
        for x in d["nearby"]:
            r = ctx.row(self.near_group, x["name"], f"{x['kind']} · {x['mac']}", hint=f"{x['name']}: not paired yet",
                        buttons=[("Pair", lambda x=x: self._pair(x), f"Pairs with {x['name']}, then trusts it")],
                        advanced={"runs": f"bromigos bluetooth pair {x['mac']}"})
            r.add_prefix(_icon(ctx, x))
            self.near_rows.append(r)

    # ------------------------------------------------------------------ changes
    def _do(self, args, said, undo_args=None):
        self.ctx.change(BT + args + ["--json"], said, undo=(BT + undo_args + ["--json"]) if undo_args else None,
                        done=self.sync, failed=lambda *_: self.refresh())

    def _power(self, on):
        self._do(["power", "on" if on else "off"], f"Bluetooth {'on' if on else 'off'}", ["power", "off" if on else "on"])

    def _visible(self, on):
        self._do(["discoverable", "on" if on else "off"], "Visible nearby" if on else "Hidden",
                 ["discoverable", "off" if on else "on"])

    def _scan(self):
        ctx = self.ctx
        self.scanning = True
        self.scan_row.set_sensitive(False)
        self.scan_row.set_subtitle("Scanning…")
        from gi.repository import Adw
        spin = Adw.Spinner()
        ctx.hint(spin, "Scanning for devices nearby")
        self.scan_row.add_prefix(spin)

        def done(doc, err):
            self.scanning = False
            self.scan_row.remove(spin)
            self.scan_row.set_subtitle("Scans for 8 seconds")
            if doc and doc.get("ok") is not False:
                self.sig = None
                self.sync(doc)
                ctx.toast(doc.get("said") or "Scanned")
            else:
                self.scan_row.set_sensitive(True)
                ctx.toast(f"Scan: {(doc or {}).get('error') or err}"[:160])
        ctx.json(BT + ["scan", "8", "--json"], done)

    def _pair(self, x):
        ctx = self.ctx

        def done(doc, err):
            if doc and doc.get("ok") is not False:
                self.sig = None
                self.sync(doc)
                ctx.toast(doc.get("said") or f"Paired with {x['name']}", undo=lambda: self._do(
                    ["remove", x["mac"]], f"Forgot {x['name']}"))
            elif doc and doc.get("needs_agent"):
                ctx.confirm(f"{x['name']} asks for a code",
                            f"{x['name']} wants a PIN or a passkey confirmed. Pair it in bluetoothctl: type "
                            f"`pair {x['mac']}`, then answer the code it shows (or type the one the device shows).",
                            "Open bluetoothctl", lambda: ctx.terminal(["bluetoothctl"]))
            else:
                ctx.toast(f"Not paired: {(doc or {}).get('error') or err}"[:200], timeout=8)
        ctx.toast(f"Pairing with {x['name']}…", timeout=3)
        ctx.json(BT + ["pair", x["mac"], "--json"], done)

    def _remove(self, x):
        self.ctx.confirm(f"Forget {x['name']}?", "It's unpaired: using it again means pairing it again.", "Forget",
                         lambda: self._do(["remove", x["mac"]], f"Forgot {x['name']}"), destructive=True)


def build(ctx):
    p = BluetoothPage(ctx)
    p.page._bt = p
    return p.page


def refresh(widget):
    widget._bt.refresh()


PAGE = Page(
    id="bluetooth", title="Bluetooth", group="system", order=40, build=build, refresh=refresh,
    docs="settings.md#bluetooth", icon="bluetooth-active-symbolic bluetooth-symbolic network-bluetooth-symbolic", summary="devices, pairing",
    intro="Bluetooth devices: the ones this machine knows, and pairing new ones. Changes apply at once.",
    keywords=["bt", "bluez", "wireless devices", "headphones", "controller"],
    entries=[
        Entry("power", "Bluetooth", ["bluetooth on", "bluetooth off", "adapter", "rfkill"], "Adapter"),
        Entry("discoverable", "Visible to devices nearby", ["discoverable", "visible", "findable"], "Adapter"),
        Entry("paired", "Paired devices", ["connect headphones", "disconnect", "battery", "forget device", "unpair"],
              "Paired devices"),
        Entry("scan", "Look for devices", ["scan", "search devices", "add device"], "Nearby"),
        Entry("nearby", "Pair a new device", ["pair", "pairing", "add bluetooth device"], "Nearby"),
        Entry("console", "bluetoothctl", ["pin", "passkey", "pairing code"], "By hand"),
    ])
