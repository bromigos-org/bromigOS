#!/usr/bin/env python3
"""A stand-in bluez on a private D-Bus (tests, offscreen renders): org.bluez with one adapter,
the paired devices and the ones a scan finds from fixtures/bluez.json, speaking the same
interfaces bluetoothd does (ObjectManager, Adapter1, Device1, Battery1, AgentManager1) and
calling a registered agent the way bluetoothd does when a device wants a code. Nothing
reaches the machine's real Bluetooth.

    with FakeBluez() as fb:            # its own dbus-daemon; fb.address is the bus
        env["BROMIGOS_BLUEZ_BUS"] = fb.address
        fb.set(path, "org.bluez.Device1", "Connected", True)   # as if the device did it

    python fake_bluez.py --address ADDR [--state bluez.json] [--instant]   (the service itself)

A nearby device's "pairing" says how it pairs: "just-works"; "confirm" (both sides show
123456); "type" (a keyboard: type 123456 on it); "pin" (asks for a PIN: 0000 works).
--instant: a scan finds every nearby device at once (renders); else one every 0.4 s.
"""
import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
FIXTURE = os.path.join(HERE, "fixtures", "bluez.json")
PASSKEY = 123456

IFACES = """<node>
<interface name="org.freedesktop.DBus.ObjectManager">
 <method name="GetManagedObjects"><arg type="a{oa{sa{sv}}}" direction="out"/></method>
</interface>
<interface name="org.bluez.Adapter1">
 <method name="StartDiscovery"/><method name="StopDiscovery"/>
 <method name="SetDiscoveryFilter"><arg type="a{sv}" direction="in"/></method>
 <method name="RemoveDevice"><arg type="o" direction="in"/></method>
 <property name="Address" type="s" access="read"/><property name="Name" type="s" access="read"/>
 <property name="Alias" type="s" access="readwrite"/><property name="Powered" type="b" access="readwrite"/>
 <property name="Discoverable" type="b" access="readwrite"/><property name="Pairable" type="b" access="readwrite"/>
 <property name="Discovering" type="b" access="read"/>
</interface>
<interface name="org.bluez.Device1">
 <method name="Connect"/><method name="Disconnect"/><method name="Pair"/><method name="CancelPairing"/>
 <method name="ConnectProfile"><arg type="s" direction="in"/></method>
 <property name="Address" type="s" access="read"/><property name="Name" type="s" access="read"/>
 <property name="Alias" type="s" access="readwrite"/><property name="Icon" type="s" access="read"/>
 <property name="Paired" type="b" access="read"/><property name="Bonded" type="b" access="read"/>
 <property name="Connected" type="b" access="read"/><property name="Trusted" type="b" access="readwrite"/>
 <property name="Blocked" type="b" access="readwrite"/><property name="Adapter" type="o" access="read"/>
 <property name="UUIDs" type="as" access="read"/><property name="RSSI" type="n" access="read"/>
</interface>
<interface name="org.bluez.Battery1"><property name="Percentage" type="y" access="read"/></interface>
<interface name="org.bluez.AgentManager1">
 <method name="RegisterAgent"><arg type="o" direction="in"/><arg type="s" direction="in"/></method>
 <method name="UnregisterAgent"><arg type="o" direction="in"/></method>
 <method name="RequestDefaultAgent"><arg type="o" direction="in"/></method>
</interface>
<interface name="org.bromigos.FakeBluez">
 <method name="Set"><arg type="s" direction="in"/><arg type="s" direction="in"/><arg type="s" direction="in"/>
  <arg type="v" direction="in"/></method>
 <method name="Calls"><arg type="s" direction="out"/></method>
</interface>
</node>"""

SIG = {"Address": "s", "Name": "s", "Alias": "s", "Powered": "b", "Discoverable": "b", "Pairable": "b",
       "Discovering": "b", "Icon": "s", "Paired": "b", "Bonded": "b", "Connected": "b", "Trusted": "b",
       "Blocked": "b", "Adapter": "o", "UUIDs": "as", "RSSI": "n", "Percentage": "y"}


def dev_path(adapter, mac):
    return f"{adapter}/dev_{mac.replace(':', '_').upper()}"


class Service:
    def __init__(self, address, state, instant):
        import gi  # noqa: F401
        from gi.repository import Gio, GLib
        self.Gio, self.GLib = Gio, GLib
        self.instant = instant
        self.conn = Gio.DBusConnection.new_for_address_sync(
            address, Gio.DBusConnectionFlags.AUTHENTICATION_CLIENT | Gio.DBusConnectionFlags.MESSAGE_BUS_CONNECTION,
            None, None)
        self.info = {i.name: i for i in Gio.DBusNodeInfo.new_for_xml(IFACES).interfaces}
        self.objects = {}       # path -> {iface: {prop: python value}}
        self.regs = {}
        self.pairing = {}       # path -> how it pairs
        self.agent = None       # (sender, path)
        self.calls = []
        a = state["adapter"]
        self.apath = a["path"]
        self.add(self.apath, {"org.bluez.Adapter1": {
            "Address": a["address"], "Name": a["name"], "Alias": a.get("alias", a["name"]),
            "Powered": a["powered"], "Discoverable": a["discoverable"], "Pairable": a.get("pairable", True),
            "Discovering": False}}, signal=False)
        for d in state["devices"]:
            self.add_device(d, paired=True, signal=False)
        self.nearby = list(state.get("nearby", []))
        self.export("/", "org.freedesktop.DBus.ObjectManager")
        self.export("/org/bluez", "org.bluez.AgentManager1")
        self.export("/control", "org.bromigos.FakeBluez")
        self.timers = []

    # -- objects
    def add_device(self, d, paired, signal=True):
        p = dev_path(self.apath, d["mac"])
        props = {"Address": d["mac"], "Name": d["name"], "Alias": d["name"], "Icon": d.get("icon", ""),
                 "Paired": paired, "Bonded": paired, "Connected": bool(d.get("connected")),
                 "Trusted": bool(d.get("trusted")), "Blocked": False, "Adapter": self.apath,
                 "UUIDs": d.get("uuids", [])}
        if d.get("rssi") is not None:
            props["RSSI"] = d["rssi"]
        ifs = {"org.bluez.Device1": props}
        if d.get("battery") is not None:
            ifs["org.bluez.Battery1"] = {"Percentage": d["battery"]}
        self.pairing[p] = d.get("pairing", "just-works")
        self.add(p, ifs, signal)
        return p

    def add(self, path, ifs, signal=True):
        self.objects.setdefault(path, {}).update(ifs)
        for i in ifs:
            self.export(path, i)
        if signal:
            self.emit("/", "org.freedesktop.DBus.ObjectManager", "InterfacesAdded",
                      self.GLib.Variant("(oa{sa{sv}})", (path, self.typed(ifs))))

    def remove(self, path):
        ifs = self.objects.pop(path, {})
        for i in ifs:
            r = self.regs.pop((path, i), None)
            if r:
                self.conn.unregister_object(r)
        self.emit("/", "org.freedesktop.DBus.ObjectManager", "InterfacesRemoved",
                  self.GLib.Variant("(oas)", (path, list(ifs))))

    def typed(self, ifs):
        V = self.GLib.Variant
        return {i: {k: V(SIG[k], v) for k, v in pr.items()} for i, pr in ifs.items()}

    def export(self, path, iface):
        self.regs[(path, iface)] = self.conn.register_object(
            path, self.info[iface], self.method, self.get_prop, self.set_prop)

    def emit(self, path, iface, name, params):
        self.conn.emit_signal(None, path, iface, name, params)

    def set(self, path, iface, name, value):
        pr = self.objects[path].setdefault(iface, {})
        if pr.get(name) == value:
            return
        pr[name] = value
        self.emit(path, "org.freedesktop.DBus.Properties", "PropertiesChanged",
                  self.GLib.Variant("(sa{sv}as)", (iface, {name: self.GLib.Variant(SIG[name], value)}, [])))

    def get_prop(self, conn, sender, path, iface, name):
        v = self.objects.get(path, {}).get(iface, {}).get(name)
        return None if v is None else self.GLib.Variant(SIG[name], v)

    def set_prop(self, conn, sender, path, iface, name, value):
        v = value.unpack()
        self.calls.append(["Set", path, iface, name, v])
        if iface == "org.bluez.Adapter1" and name == "Powered" and not v:
            for p, ifs in self.objects.items():
                if "org.bluez.Device1" in ifs:
                    self.set(p, "org.bluez.Device1", "Connected", False)
            self.set(path, iface, "Discovering", False)
        self.set(path, iface, name, v)
        return True

    # -- methods
    def later(self, secs, fn):
        self.GLib.timeout_add(int(secs * 1000), lambda: fn() and False)

    def method(self, conn, sender, path, iface, method, params, inv):
        args = params.unpack()
        self.calls.append([method, path] + list(args))
        V = self.GLib.Variant
        a = self.objects.get(self.apath, {}).get("org.bluez.Adapter1", {})
        if method == "GetManagedObjects":
            inv.return_value(V("(a{oa{sa{sv}}})", ({p: self.typed(i) for p, i in self.objects.items()},)))
        elif method == "Calls":
            inv.return_value(V("(s)", (json.dumps(self.calls),)))
        elif method == "Set":
            p, i, n, v = args
            self.set(p, i, n, v)
            inv.return_value(None)
        elif method == "RegisterAgent":
            self.agent = (sender, args[0])
            inv.return_value(None)
        elif method in ("UnregisterAgent", "RequestDefaultAgent", "SetDiscoveryFilter"):
            if method == "UnregisterAgent":
                self.agent = None
            inv.return_value(None)
        elif not a.get("Powered") and iface in ("org.bluez.Adapter1", "org.bluez.Device1") and \
                method not in ("RemoveDevice",):
            inv.return_dbus_error("org.bluez.Error.NotReady", "Resource Not Ready")
        elif method == "StartDiscovery":
            self.set(self.apath, "org.bluez.Adapter1", "Discovering", True)
            inv.return_value(None)
            for n, d in enumerate(self.nearby):
                if dev_path(self.apath, d["mac"]) not in self.objects:
                    self.later(0.01 if self.instant else 0.4 * (n + 1),
                               lambda d=d: self.objects.get(self.apath) and self.add_device(d, paired=False))
        elif method == "StopDiscovery":
            self.set(self.apath, "org.bluez.Adapter1", "Discovering", False)
            inv.return_value(None)
        elif method == "RemoveDevice":
            if args[0] not in self.objects:
                inv.return_dbus_error("org.bluez.Error.DoesNotExist", "Does Not Exist")
            else:
                self.remove(args[0])
                inv.return_value(None)
        elif method in ("Connect", "ConnectProfile"):
            dev = self.objects[path]["org.bluez.Device1"]
            if not dev["Paired"]:
                inv.return_dbus_error("org.bluez.Error.Failed", "br-connection-profile-unavailable")
            else:
                self.later(0.15, lambda: (self.set(path, "org.bluez.Device1", "Connected", True),
                                          inv.return_value(None)))
        elif method == "Disconnect":
            self.set(path, "org.bluez.Device1", "Connected", False)
            inv.return_value(None)
        elif method == "CancelPairing":
            inv.return_value(None)
        elif method == "Pair":
            self.pair(path, inv)
        else:
            inv.return_dbus_error("org.freedesktop.DBus.Error.UnknownMethod", method)

    def pair(self, path, inv):
        how = self.pairing.get(path, "just-works")
        V = self.GLib.Variant
        dev = self.objects[path]["org.bluez.Device1"]
        if dev["Paired"]:
            inv.return_dbus_error("org.bluez.Error.AlreadyExists", "Already Exists")
            return

        def done():
            self.set(path, "org.bluez.Device1", "Paired", True)
            self.set(path, "org.bluez.Device1", "Bonded", True)
            inv.return_value(None)

        def ask(method, args, sig, check):
            if self.agent is None:
                inv.return_dbus_error("org.bluez.Error.AuthenticationFailed", "Authentication Failed")
                return

            def back(conn, res):
                try:
                    got = conn.call_finish(res).unpack()
                except Exception:
                    inv.return_dbus_error("org.bluez.Error.AuthenticationRejected", "Authentication Rejected")
                    return
                if check(got):
                    done()
                else:
                    inv.return_dbus_error("org.bluez.Error.AuthenticationFailed", "Authentication Failed")
            self.conn.call(self.agent[0], self.agent[1], "org.bluez.Agent1", method, args,
                           None, self.Gio.DBusCallFlags.NONE, 60000, None, back)

        if how == "confirm":
            ask("RequestConfirmation", V("(ou)", (path, PASSKEY)), None, lambda got: True)
        elif how == "pin":
            ask("RequestPinCode", V("(o)", (path,)), "s", lambda got: got and got[0] == "0000")
        elif how == "type":
            if self.agent is None:
                inv.return_dbus_error("org.bluez.Error.AuthenticationFailed", "Authentication Failed")
                return
            self.conn.call(self.agent[0], self.agent[1], "org.bluez.Agent1", "DisplayPasskey",
                           V("(ouq)", (path, PASSKEY, 0)), None, self.Gio.DBusCallFlags.NONE, 5000, None, None)
            self.later(0.3, done)
        else:
            self.later(0.1, done)


def serve(argv):
    ap = argparse.ArgumentParser()
    ap.add_argument("--address", required=True)
    ap.add_argument("--state", default=FIXTURE)
    ap.add_argument("--instant", action="store_true")
    o = ap.parse_args(argv)
    with open(o.state) as f:
        state = json.load(f)
    s = Service(o.address, state, o.instant)
    from gi.repository import Gio, GLib
    loop = GLib.MainLoop()

    def owned(*_):
        print("ready", flush=True)
    Gio.bus_own_name_on_connection(s.conn, "org.bluez", Gio.BusNameOwnerFlags.NONE, owned, lambda *_: loop.quit())
    loop.run()


class FakeBluez:
    """A private dbus-daemon with the stand-in bluez on it, for a `with` block."""

    def __init__(self, state=None, instant=False):
        self.state, self.instant = state, instant
        self.address = None

    def __enter__(self):
        if not shutil.which("dbus-daemon"):
            raise RuntimeError("no dbus-daemon")
        self.tmp = tempfile.mkdtemp(prefix="fbz-")
        sock = os.path.join(self.tmp, "bus")
        self.bus = subprocess.Popen(["dbus-daemon", "--session", "--nofork", "--nopidfile",
                                     f"--address=unix:path={sock}", "--print-address"],
                                    stdout=subprocess.PIPE, text=True)
        self.address = self.bus.stdout.readline().strip()
        st = self.state
        if isinstance(st, dict):
            p = os.path.join(self.tmp, "bluez.json")
            with open(p, "w") as f:
                json.dump(st, f)
            st = p
        argv = [sys.executable, os.path.abspath(__file__), "--address", self.address, "--state", st or FIXTURE]
        if self.instant:
            argv.append("--instant")
        self.svc = subprocess.Popen(argv, stdout=subprocess.PIPE, text=True)
        line = self.svc.stdout.readline().strip()
        if line != "ready":
            self.__exit__()
            raise RuntimeError("the stand-in bluez didn't start")
        return self

    def __exit__(self, *exc):
        for p in (getattr(self, "svc", None), getattr(self, "bus", None)):
            if p is None:
                continue
            if p.poll() is None:
                p.terminate()
                try:
                    p.wait(5)
                except subprocess.TimeoutExpired:
                    p.kill()
                    p.wait(5)
            if p.stdout is not None:
                p.stdout.close()
        shutil.rmtree(self.tmp, ignore_errors=True)
        return False

    def _conn(self):
        from gi.repository import Gio
        return Gio.DBusConnection.new_for_address_sync(
            self.address, Gio.DBusConnectionFlags.AUTHENTICATION_CLIENT |
            Gio.DBusConnectionFlags.MESSAGE_BUS_CONNECTION, None, None)

    def set(self, path, iface, name, value):
        from gi.repository import Gio, GLib
        v = GLib.Variant(SIG[name], value)
        self._conn().call_sync("org.bluez", "/control", "org.bromigos.FakeBluez", "Set",
                               GLib.Variant("(sssv)", (path, iface, name, v)), None, Gio.DBusCallFlags.NONE, 5000, None)

    def calls(self):
        from gi.repository import Gio
        v = self._conn().call_sync("org.bluez", "/control", "org.bromigos.FakeBluez", "Calls", None, None,
                                   Gio.DBusCallFlags.NONE, 5000, None)
        return json.loads(v.unpack()[0])


if __name__ == "__main__":
    serve(sys.argv[1:])
