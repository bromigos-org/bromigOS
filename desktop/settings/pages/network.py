"""Network: Wi-Fi (the radio, the network in use, the networks in reach, joining one, the
saved ones), wired, VPNs, and the CONNECTIONS panel (docs/settings.md, "Network").

Everything goes through `bromigos net … --json` (NetworkManager through nmcli). A new
secured network's password goes to the command on stdin, never on a command line. The
page reads the state again every few seconds while it's shown."""
import json

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, GLib, Gtk  # noqa: E402

from bromigos_settings import Entry, Page  # noqa: E402

NET = ["bromigos", "net"]
LOCK = ("network-wireless-encrypted-symbolic", "channel-secure-symbolic", "system-lock-screen-symbolic")


def _signal_icon(s):
    level = "excellent" if s > 75 else "good" if s > 50 else "ok" if s > 25 else "weak" if s > 5 else "none"
    return f"network-wireless-signal-{level}-symbolic"


class NetworkPage:
    def __init__(self, ctx):
        self.ctx = ctx
        self.doc = None
        self.sig = None
        self.busy = False
        self.problem = None
        self.page = ctx.page()
        self.page.set_reset(None, hint="Nothing here has a bromigOS default: your networks and their passwords are "
                                       "this machine's own (NetworkManager keeps them)")
        self._static()
        self.refresh()
        GLib.timeout_add_seconds(6, self._tick)

    # ------------------------------------------------------------------ building
    def _static(self):
        ctx = self.ctx
        self.wifi_group = ctx.group(self.page, "Wi-Fi", "The wireless network this machine is on.", key="wifi-group")
        self.wifi_row = ctx.switch_row(
            self.wifi_group, "Wi-Fi", "The wireless radio", key="wifi", on_toggle=self._wifi,
            hint="Turns the Wi-Fi radio on or off (NetworkManager); wired and VPNs are untouched",
            advanced={"runs": "bromigos net wifi on|off", "note": "nmcli radio wifi on|off"})
        self.cur_rows = []
        self.reach_group = ctx.group(self.page, "Networks in reach", "Pick one to join it. A lock: it asks for a "
                                     "password the first time.", key="networks")
        self.reach_rows = []
        self.saved_group = ctx.group(self.page, "Saved networks", "Networks this machine has joined: whether each "
                                     "joins by itself, and forgetting one (its password goes with it).", key="saved")
        self.saved_rows = []
        self.wired_group = ctx.group(self.page, "Wired", "Ethernet ports and the network on each.", key="wired")
        self.wired_rows = []
        self.vpn_group = ctx.group(self.page, "VPN", "Your VPN and WireGuard connections: switch one on to go "
                                   "through it.", key="vpn")
        self.vpn_rows = []
        g = ctx.group(self.page, "On the desktop", "The CONNECTIONS panel: what's connected, the Wi-Fi in reach, "
                                                   "the VPNs, live on the desktop.")
        self.panel_row = ctx.switch_row(
            g, "Connections panel", "Shown on the desktop (it samples every 15 seconds)", key="panel",
            on_toggle=self._panel,
            hint="Shows or hides the CONNECTIONS panel on the desktop (bromigos panels)",
            advanced={"runs": "bromigos net panel on|off", "file": "~/.config/bromigos/widgets/layout.json",
                      "key": "connections › visible"})
        ctx.row(g, "Every panel", "Which panels are on, where they sit: Widgets", key="widgets",
                hint="Opens the Widgets page", activate=lambda: ctx.open_page("widgets"))
        g = ctx.group(self.page, "More")
        self.editor_row = ctx.row(
            g, "More settings", "Static addresses, proxies, enterprise Wi-Fi, VPN profiles: NetworkManager's own editor",
            key="editor", hint="Opens nm-connection-editor (NetworkManager's connection editor)",
            buttons=[("Open", lambda: ctx.launch(["nm-connection-editor"]), "Opens nm-connection-editor")],
            advanced={"runs": "nm-connection-editor"})

    def _sig(self, d):
        nets = [(n["ssid"], n["in_use"], n["saved"], n["secured"]) for n in d["wifi"]["networks"]]
        return json.dumps([d["wifi"]["enabled"], nets, [(c["uuid"], c["autoconnect"], c["active"]) for c in d["connections"]],
                           [(x["name"], x["state"], x.get("ip4")) for x in d["devices"]]])

    def _current(self):
        ctx, d = self.ctx, self.doc
        ctx.clear_group(self.wifi_group, self.cur_rows)
        net = next((n for n in d["wifi"]["networks"] if n["in_use"]), None)
        wdev = next((x for x in d["devices"] if x["type"] == "wifi" and x["state"].startswith("connected")), None)
        if not d["wifi"]["devices"]:
            self.cur_rows.append(ctx.row(self.wifi_group, "No Wi-Fi device", "This machine has no wireless card "
                                         "NetworkManager can use", key="current", hint="No Wi-Fi hardware found"))
            return
        if net is None or wdev is None:
            self.cur_rows.append(ctx.row(
                self.wifi_group, "Not connected", "Pick a network below" if d["wifi"]["enabled"] else "Wi-Fi is off",
                key="current", hint="This machine isn't on a wireless network now"))
            return
        addr = ", ".join(wdev.get("ip4") or [])
        more = " · ".join(x for x in [f"gateway {wdev['gateway']}" if wdev.get("gateway") else "",
                                       "DNS " + ", ".join(wdev["dns"]) if wdev.get("dns") else ""] if x)
        saved = next((c for c in d["saved_wifi"] if c.get("ssid") == net["ssid"] and c["active"]), None)
        r = ctx.row(self.wifi_group, net["ssid"], f"Connected · {net['signal']}%", key="current",
                    hint=f"The network in use: {net['ssid']} on {wdev['name']} ({net['security'] or 'open'}, "
                         f"channel {net['channel']}, {net['bssid']})",
                    buttons=[("Disconnect", lambda: self._disconnect(wdev["name"], saved),
                              f"Takes {wdev['name']} off {net['ssid']} (Undo joins again)")]
                    + ([("Forget…", lambda: self._forget(saved), f"Deletes {net['ssid']} and its password")] if saved else []),
                    advanced={"runs": f"bromigos net disconnect {wdev['name']}", "note": f"hardware address {wdev.get('hwaddr', '')}"})
        r.add_prefix(ctx.icon(_signal_icon(net["signal"])))
        self.cur_rows.append(r)
        if addr or more:
            self.cur_rows.append(ctx.row(
                self.wifi_group, "Address", " · ".join(x for x in (addr, more) if x), key="address",
                hint=f"{wdev['name']}'s IPv4 address, its gateway and the DNS servers it uses",
                buttons=[("Copy", lambda: ctx.copy(addr.split("/")[0]), "Copies the IP address")] if addr else []))

    def _reach(self):
        ctx, d = self.ctx, self.doc
        ctx.clear_group(self.reach_group, self.reach_rows)
        scan = ctx.row(self.reach_group, "Look again", "Scans for networks (NetworkManager also scans by itself)",
                       key="scan", hint="Scans for Wi-Fi networks now",
                       buttons=[("Scan", self._scan, "Scans for Wi-Fi networks now")],
                       advanced={"runs": "bromigos net scan"})
        scan.set_sensitive(d["wifi"]["enabled"])
        self.reach_rows.append(scan)
        if not d["wifi"]["enabled"]:
            self.reach_rows.append(ctx.note(self.reach_group, "Wi-Fi is off: switch it on above to see networks", "note"))
        elif not d["wifi"]["networks"]:
            self.reach_rows.append(ctx.note(self.reach_group, "No networks in reach", "note",
                                            hint="Nothing answered the last scan; try Scan"))
        for n in d["wifi"]["networks"]:
            if n["in_use"]:
                continue
            bits = (["saved"] if n["saved"] else []) + [n["security"] or "open"] + [f"{n['signal']}%"]
            if n["enterprise"]:
                label, cb, h = "More settings", lambda: ctx.launch(["nm-connection-editor"]), \
                    "An enterprise network (802.1X) needs its account: set it up in nm-connection-editor"
            elif n["secured"] and not n["saved"]:
                label, cb, h = "Connect…", (lambda n=n: self._ask_password(n["ssid"], n["security"])), \
                    f"Asks for {n['ssid']}'s password, then joins it"
            else:
                label, cb, h = "Connect", (lambda n=n: self._connect(n["ssid"], None)), f"Joins {n['ssid']}"
            lock = None
            if n["secured"]:
                lock = ctx.icon(*LOCK)
                ctx.hint(lock, "Secured: " + n["security"])
            r = ctx.row(self.reach_group, n["ssid"], " · ".join(bits), buttons=[(label, cb, h)], control=lock,
                        hint=f"{n['ssid']}: {n['signal']}% signal, {n['security'] or 'open (no password)'}, "
                             f"channel {n['channel']} ({n['bssid']})",
                        advanced={"runs": f"bromigos net connect '{n['ssid']}'" +
                                  (" --password-stdin" if n["secured"] and not n["saved"] else ""),
                                  "note": "a password goes on stdin, never the command line"})
            r.add_prefix(ctx.icon(_signal_icon(n["signal"])))
            self.reach_rows.append(r)
        hid = ctx.row(self.reach_group, "Join another network…", "One that doesn't announce its name (hidden)",
                      key="hidden", hint="Joins a hidden network by its name and password",
                      buttons=[("Join…", self._ask_hidden, "Asks for the network's name and password")],
                      advanced={"runs": "bromigos net connect NAME --hidden --password-stdin"})
        hid.set_sensitive(d["wifi"]["enabled"])
        self.reach_rows.append(hid)

    def _saved(self):
        ctx, d = self.ctx, self.doc
        ctx.clear_group(self.saved_group, self.saved_rows)
        if not d["saved_wifi"]:
            self.saved_rows.append(ctx.note(self.saved_group, "No saved networks yet", "note"))
        for c in d["saved_wifi"]:
            r = ctx.switch_row(
                self.saved_group, c["name"], ("in use · " if c["active"] else "") +
                ("joins by itself" if c["autoconnect"] else "joins only when you pick it"),
                active=c["autoconnect"], on_toggle=lambda on, c=c: self._autoconnect(c, on),
                hint=f"On: this machine joins {c['name']} by itself when it's in reach",
                advanced={"runs": f"bromigos net autoconnect '{c['name']}' on|off", "note": f"uuid {c['uuid']}"})
            r.add_suffix(ctx.button("Forget…", lambda c=c: self._forget(c), f"Deletes {c['name']} and its password"))
            tog = getattr(r, "_bromigos_advanced", None)
            if tog is not None:                 # the Advanced toggle stays last
                r.remove(tog)
                r.add_suffix(tog)
            self.saved_rows.append(r)

    def _wired(self):
        ctx, d = self.ctx, self.doc
        ctx.clear_group(self.wired_group, self.wired_rows)
        if not d["wired"]:
            self.wired_rows.append(ctx.note(self.wired_group, "No ethernet port", "note",
                                            hint="NetworkManager sees no wired device"))
        profiles = [c for c in d["connections"] if c["type"] in ("802-3-ethernet", "ethernet")]
        for w in d["wired"]:
            on = w["state"].startswith("connected")
            if on:
                sub = f"Connected ({w['connection']}) · " + ", ".join(w.get("ip4") or []) + \
                      (f" · gateway {w['gateway']}" if w.get("gateway") else "")
                btn = ("Disconnect", lambda w=w: self._disconnect(w["name"], next(
                    (c for c in profiles if c["name"] == w["connection"]), None)), f"Takes {w['name']} off its network")
            else:
                sub = {"unavailable": "No cable", "disconnected": "Not connected"}.get(w["state"], w["state"])
                prof = next((c for c in profiles if c["device"] in ("", w["name"])), None)
                btn = ("Connect", lambda p=prof: self._up(p), f"Brings {prof['name']} up on {w['name']}") if prof else None
            r = ctx.row(self.wired_group, w["name"], sub, buttons=[btn] if btn else [],
                        hint=f"The ethernet port {w['name']} ({w.get('hwaddr') or 'no address'})",
                        advanced={"runs": f"bromigos net disconnect {w['name']}" if on else "bromigos net up PROFILE"})
            r.add_prefix(ctx.icon("network-wired-symbolic"))
            self.wired_rows.append(r)

    def _vpns(self):
        ctx, d = self.ctx, self.doc
        ctx.clear_group(self.vpn_group, self.vpn_rows)
        if not d["vpns"]:
            self.vpn_rows.append(ctx.note(self.vpn_group, "No VPN set up: add one in More settings "
                                          "(nm-connection-editor) or import a WireGuard file with nmcli", "note"))
        for v in d["vpns"]:
            r = ctx.switch_row(
                self.vpn_group, v["name"], ("WireGuard" if v["type"] == "wireguard" else "VPN") +
                (" · up" if v["active"] else ""), active=v["active"],
                on_toggle=lambda on, v=v: self._vpn(v, on),
                hint=f"Brings {v['name']} up or down",
                advanced={"runs": f"bromigos net up|down '{v['name']}'", "note": f"uuid {v['uuid']}"})
            r.add_prefix(ctx.icon("network-vpn-symbolic"))
            self.vpn_rows.append(r)

    # ------------------------------------------------------------------ state
    def refresh(self):
        self.ctx.json(NET + ["--json"], self._got)

    def _tick(self):
        if self.page.get_mapped() and not self.busy:
            self.refresh()
        return True

    def _got(self, doc, err):
        if not doc or doc.get("ok") is False:
            if self.problem is None:
                self.problem = self.ctx.failed(self.wifi_group, NET + ["--json"], (doc or {}).get("error") or err)
            self.wifi_row.set_sensitive(False)
            return
        if self.problem is not None:
            self.wifi_group.remove(self.problem)
            self.problem = None
        self.sync(doc)

    def sync(self, d):
        self.doc = d
        self.wifi_row.set_sensitive(bool(d["wifi"]["devices"]))
        self.wifi_row.set_quiet(d["wifi"]["enabled"])
        self.wifi_row.set_subtitle(GLib.markup_escape_text(
            {"full": "On · the internet answers", "limited": "On · no internet (the network answers)",
             "portal": "On · a sign-in page is in the way", "none": "On · not connected"}.get(d["connectivity"], "On")
            if d["wifi"]["enabled"] else "Off"))
        if d.get("panel") is None:
            self.panel_row.set_sensitive(False)
            self.ctx.hint(self.panel_row, "The CONNECTIONS panel comes with bromigos-widgets (bromigos panels isn't "
                                          "answering here)")
        else:
            self.panel_row.set_sensitive(True)
            self.panel_row.set_quiet(d["panel"])
        self.editor_row.set_sensitive(bool(d.get("editor")))
        if not d.get("editor"):
            self.ctx.hint(self.editor_row, "nm-connection-editor isn't installed (pacman -S nm-connection-editor)")
        sig = self._sig(d)
        if sig != self.sig:
            self.sig = sig
            self._current()
            self._reach()
            self._saved()
            self._wired()
            self._vpns()

    # ------------------------------------------------------------------ changes
    def _change(self, args, said, undo_args=None):
        self.ctx.change(NET + args + ["--json"], said, undo=(NET + undo_args + ["--json"]) if undo_args else None,
                        done=self.sync, failed=lambda *_: self.refresh())

    def _wifi(self, on):
        self._change(["wifi", "on" if on else "off"], f"Wi-Fi {'on' if on else 'off'}",
                     ["wifi", "off" if on else "on"])

    def _panel(self, on):
        self._change(["panel", "on" if on else "off"], f"Connections panel {'shown' if on else 'hidden'}",
                     ["panel", "off" if on else "on"])

    def _scan(self):
        self.busy = True

        def done(doc, err):
            self.busy = False
            if doc and doc.get("ok") is not False:
                self.sync(doc)
                self.ctx.toast(f"{len(doc['wifi']['networks'])} networks in reach")
            else:
                self.ctx.toast(f"Scan: {(doc or {}).get('error') or err}"[:160])
        self.ctx.json(NET + ["scan", "--json"], done)

    def _connect(self, ssid, password, hidden=False):
        self.busy = True
        argv = NET + ["connect", ssid] + (["--hidden"] if hidden else []) + \
            (["--password-stdin"] if password is not None else []) + ["--json"]

        def done(doc, err):
            self.busy = False
            if doc and doc.get("ok") is not False:
                self.sync(doc)
                self.ctx.toast(doc.get("said") or f"Connected to {ssid}")
            else:
                self.ctx.toast(f"Not connected: {(doc or {}).get('error') or err}"[:200], timeout=8)
                self.refresh()
        self.ctx.toast(f"Joining {ssid}…", timeout=3)
        self.ctx.json(argv, done, stdin=(password + "\n") if password is not None else None)

    def _password_dialog(self, heading, body, then, ask_name=False):
        d = Adw.AlertDialog(heading=heading, body=body)
        box = Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE)
        box.add_css_class("boxed-list")
        name = None
        if ask_name:
            name = Adw.EntryRow(title="Network name")
            self.ctx.hint(name, "The network's name (its SSID), exactly")
            box.append(name)
        pw = Adw.PasswordEntryRow(title="Password")
        self.ctx.hint(pw, "The network's password: it goes to NetworkManager on stdin, never a command line")
        box.append(pw)
        d.set_extra_child(box)
        d.add_response("cancel", "Cancel")
        d.add_response("connect", "Connect")
        d.set_response_appearance("connect", Adw.ResponseAppearance.SUGGESTED)
        d.set_default_response("connect")
        d.set_close_response("cancel")

        def resp(_d, r):
            if r == "connect":
                then(name.get_text().strip() if name else None, pw.get_text())
        d.connect("response", resp)
        pw.set_activates_default(True)
        d.present(self.ctx.window)
        (name or pw).grab_focus()

    def _ask_password(self, ssid, security):
        self._password_dialog(f"Join {ssid}", f"{ssid} is secured ({security}). Its password:",
                              lambda _n, pw: pw and self._connect(ssid, pw))

    def _ask_hidden(self):
        self._password_dialog("Join a hidden network", "Its name and, when it's secured, its password.",
                              lambda n, pw: n and self._connect(n, pw or None, hidden=True), ask_name=True)

    def _disconnect(self, dev, conn):
        self._change(["disconnect", dev], lambda d: d.get("said") or f"{dev} disconnected",
                     ["up", conn["uuid"]] if conn else None)

    def _up(self, conn):
        self._change(["up", conn["uuid"]], f"{conn['name']}: up", ["down", conn["uuid"]])

    def _forget(self, conn):
        if not conn:
            return
        self.ctx.confirm(f"Forget {conn['name']}?", "Its saved password goes with it: joining again asks for it.",
                         "Forget", lambda: self._change(["forget", conn["uuid"]], f"Forgot {conn['name']}"),
                         destructive=True)

    def _autoconnect(self, c, on):
        self._change(["autoconnect", c["uuid"], "on" if on else "off"],
                     f"{c['name']}: {'joins by itself' if on else 'joins when you pick it'}",
                     ["autoconnect", c["uuid"], "off" if on else "on"])

    def _vpn(self, v, on):
        self._change(["up" if on else "down", v["uuid"]], f"{v['name']}: {'up' if on else 'down'}",
                     ["down" if on else "up", v["uuid"]])


def build(ctx):
    p = NetworkPage(ctx)
    p.page._net = p
    return p.page


def refresh(widget):
    widget._net.refresh()


PAGE = Page(
    id="network", title="Network", group="system", order=30, build=build, refresh=refresh, docs="settings.md#network",
    icon="network-wireless-symbolic network-workgroup-symbolic", summary="Wi-Fi, wired, VPN",
    intro="Wi-Fi, wired and VPNs, through NetworkManager. A change applies at once; a new network's password is "
          "asked for once and kept by NetworkManager.",
    keywords=["internet", "networkmanager", "nmcli", "connection", "online", "ip address"],
    entries=[
        Entry("wifi", "Wi-Fi", ["wireless", "wlan", "radio", "airplane"], "Wi-Fi"),
        Entry("current", "Network in use", ["connected network", "ip address", "gateway", "dns", "disconnect"], "Wi-Fi"),
        Entry("networks", "Networks in reach", ["join", "connect", "ssid", "available networks"], "Networks in reach"),
        Entry("scan", "Scan for networks", ["rescan", "refresh networks", "look again"], "Networks in reach"),
        Entry("hidden", "Join a hidden network", ["hidden ssid", "other network"], "Networks in reach"),
        Entry("saved", "Saved networks", ["forget network", "known networks", "autoconnect", "remembered"],
              "Saved networks"),
        Entry("wired", "Wired", ["ethernet", "cable", "lan", "port"], "Wired"),
        Entry("vpn", "VPN", ["wireguard", "tunnel", "vpn connection"], "VPN"),
        Entry("panel", "Connections panel", ["network panel", "connections widget", "desktop panel"], "On the desktop"),
        Entry("widgets", "Every panel", ["widgets", "panels"], "On the desktop"),
        Entry("editor", "More network settings", ["static ip", "proxy", "nm-connection-editor", "enterprise", "802.1x"],
              "More"),
    ])
