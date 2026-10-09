"""A stand-in notification daemon on a private session bus: records every Notify call (JSON lines)."""
import json
import sys

from gi.repository import Gio, GLib

OUT = sys.argv[1]
XML = """<node><interface name="org.freedesktop.Notifications">
<method name="Notify"><arg type="s" direction="in"/><arg type="u" direction="in"/><arg type="s" direction="in"/>
<arg type="s" direction="in"/><arg type="s" direction="in"/><arg type="as" direction="in"/>
<arg type="a{sv}" direction="in"/><arg type="i" direction="in"/><arg type="u" direction="out"/></method>
<method name="GetCapabilities"><arg type="as" direction="out"/></method>
<method name="GetServerInformation"><arg type="s" direction="out"/><arg type="s" direction="out"/>
<arg type="s" direction="out"/><arg type="s" direction="out"/></method>
<method name="CloseNotification"><arg type="u" direction="in"/></method>
</interface></node>"""
n = [0]


def call(conn, sender, path, iface, method, params, inv):
    if method == "Notify":
        app, _id, icon, summary, body, _a, hints, timeout = params.unpack()
        n[0] += 1
        with open(OUT, "a") as f:
            f.write(json.dumps({"app": app, "icon": icon, "summary": summary, "body": body,
                                "urgency": int(hints.get("urgency", 1))}) + "\n")
        inv.return_value(GLib.Variant("(u)", (n[0],)))
    elif method == "GetCapabilities":
        inv.return_value(GLib.Variant("(as)", (["body"],)))
    elif method == "GetServerInformation":
        inv.return_value(GLib.Variant("(ssss)", ("e2e-notifyd", "test", "1", "1.2")))
    else:
        inv.return_value(None)


def acquired(conn, name):
    node = Gio.DBusNodeInfo.new_for_xml(XML)
    conn.register_object("/org/freedesktop/Notifications", node.interfaces[0], call, None, None)
    print("notifyd: up", flush=True)


Gio.bus_own_name(Gio.BusType.SESSION, "org.freedesktop.Notifications", Gio.BusNameOwnerFlags.NONE, acquired,
                 None, lambda *a: sys.exit("notifyd: lost the name"))
GLib.MainLoop().run()
