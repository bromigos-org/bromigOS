"""Real-event sources outside Hyprland's socket:

* desktop notifications, observed on the session bus with a monitor-mode
  connection (no dunstrc edits, no polling): Notify calls and closures;
* the session lock, by watching for the locker process, gtklock or hyprlock (cheap: one stat per
  second while locked, a /proc scan every 2 s otherwise).
"""
import os
import threading
import time

import gi

gi.require_version("Gio", "2.0")
from gi.repository import Gio, GLib  # noqa: E402


class Notifications:
    """Calls cb('notify', app, summary, urgency) / cb('closed', id)."""

    RULES = [
        "type='method_call',interface='org.freedesktop.Notifications',member='Notify'",
        "type='signal',interface='org.freedesktop.Notifications',member='NotificationClosed'",
    ]

    def __init__(self, cb):
        self.cb = cb
        self.conn = None

    def start(self):
        try:
            addr = Gio.dbus_address_get_for_bus_sync(Gio.BusType.SESSION, None)
            self.conn = Gio.DBusConnection.new_for_address_sync(
                addr, Gio.DBusConnectionFlags.AUTHENTICATION_CLIENT |
                Gio.DBusConnectionFlags.MESSAGE_BUS_CONNECTION, None, None)
            self.conn.add_filter(self._filter)
            self.conn.call_sync("org.freedesktop.DBus", "/org/freedesktop/DBus",
                                "org.freedesktop.DBus.Monitoring", "BecomeMonitor",
                                GLib.Variant("(asu)", (self.RULES, 0)), None,
                                Gio.DBusCallFlags.NONE, -1, None)
        except Exception as e:  # never fatal: the layer works without it
            print("bromigos-live: notification monitor unavailable:", e, flush=True)

    def _filter(self, conn, msg, incoming):
        try:
            member = msg.get_member()
            body = msg.get_body()
            if member == "Notify" and body is not None:
                app, _rid, _icon, summary, _body, _act, hints, _to = body.unpack()
                urg = hints.get("urgency", 1)
                if isinstance(urg, (bytes, bytearray)):
                    urg = urg[0]
                # tools that play their own cue: a capture.* category or x-bromigos-sound:none
                quiet = (str(hints.get("category", "")).startswith("capture.")
                         or str(hints.get("x-bromigos-sound", "")).lower() == "none")
                GLib.idle_add(self.cb, "notify", app, summary, int(urg), quiet)
            elif member == "NotificationClosed" and body is not None:
                nid, reason = body.unpack()
                GLib.idle_add(self.cb, "closed", nid, reason, 0, False)
        except Exception:
            pass
        return msg


class LockWatch(threading.Thread):
    LOCKERS = ("hyprlock", "gtklock")         # bromigos-lock runs gtklock, falling back to hyprlock

    def __init__(self, cb, names=LOCKERS):
        super().__init__(daemon=True, name="lock-watch")
        self.cb = cb
        self.names = set(names)
        self.pid = None

    def _find(self):
        for d in os.scandir("/proc"):
            if not d.name.isdigit():
                continue
            try:
                with open(f"/proc/{d.name}/comm") as f:
                    if f.read().strip() in self.names:
                        return int(d.name)
            except OSError:
                continue
        return None

    def run(self):
        self.pid = self._find()
        if self.pid:
            GLib.idle_add(self.cb, True)
        while True:
            if self.pid:
                time.sleep(0.5)
                if not os.path.exists(f"/proc/{self.pid}"):
                    self.pid = None
                    GLib.idle_add(self.cb, False)
            else:
                time.sleep(1.5)
                pid = self._find()
                if pid:
                    self.pid = pid
                    GLib.idle_add(self.cb, True)
