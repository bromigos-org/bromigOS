"""The bar popups' closing rules (lib/bromigos_popup.py), without a display: a stand-in
layer shell records what each surface asks for. The real thing, clicks and all, is
e2e_popups_nested.py."""
import os
import socket
import struct
import sys
import tempfile
import threading
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "lib"))
import bromigos_popup as P  # noqa: E402
import bromigos_vptr as V  # noqa: E402


def _read(path):
    with open(path) as f:
        return f.read()


class Enum:
    def __init__(self, *names):
        for n in names:
            setattr(self, n, n)


class FakeLS:
    KeyboardMode = Enum("NONE", "ON_DEMAND", "EXCLUSIVE")
    Layer = Enum("BACKGROUND", "BOTTOM", "TOP", "OVERLAY")
    Edge = Enum("TOP", "BOTTOM", "LEFT", "RIGHT")

    def __init__(self):
        self.modes = {}

    def is_supported(self):
        return True

    def is_layer_window(self, win):
        return True

    def set_keyboard_mode(self, win, mode):
        self.modes[win] = mode


class Mon:
    def __init__(self, name):
        self.name = name

    def get_connector(self):
        return self.name


class KeyboardTest(unittest.TestCase):
    def setUp(self):
        self.ls = FakeLS()
        self.sh = P.Shell.__new__(P.Shell)
        self.sh.LS = self.ls

    def test_never_exclusive_unless_asked(self):
        self.sh.keyboard("w", True)
        self.assertEqual(self.ls.modes["w"], "ON_DEMAND")
        self.sh.keyboard("w", False)
        self.assertEqual(self.ls.modes["w"], "NONE")
        self.sh.keyboard("w", "exclusive")
        self.assertEqual(self.ls.modes["w"], "EXCLUSIVE")

    def test_the_panel_asks_exclusive_only_for_a_code(self):
        src = _read(os.path.join(HERE, "..", "lib", "bromigos_btpanel.py"))
        self.assertEqual(src.count('"exclusive"'), 1)
        self.assertIn('if entry is not None:\n            sh.keyboard(self.win, "exclusive")', src)
        for lib in ("bromigos_btpanel.py", "bromigos_soundpopup.py", "bromigos_popup.py"):
            text = _read(os.path.join(HERE, "..", "lib", lib))
            self.assertNotIn("set_keyboard_mode(win, LS.KeyboardMode.EXCLUSIVE", text, lib)


class OutsideTest(unittest.TestCase):
    def outside(self, opener):
        o = P.Outside.__new__(P.Outside)
        o.opener = opener
        return o

    def test_a_click_on_the_opener_icon_is_the_toggle(self):
        o = self.outside({"monitor": "DP-1", "x": 1500, "y": 17})
        self.assertTrue(o.on_icon(Mon("DP-1"), 1500, 17))
        self.assertTrue(o.on_icon(Mon("DP-1"), 1520, 4))

    def test_anything_else_is_handed_on(self):
        o = self.outside({"monitor": "DP-1", "x": 1500, "y": 17})
        self.assertFalse(o.on_icon(Mon("DP-1"), 1400, 17))        # the next module
        self.assertFalse(o.on_icon(Mon("DP-1"), 1500, 300))       # under the icon: the desktop
        self.assertFalse(o.on_icon(Mon("HDMI-A-1"), 1500, 17))    # the same spot, another screen
        self.assertFalse(self.outside(None).on_icon(Mon("DP-1"), 1500, 17))

    def test_one_click_closes_once_and_hands_on(self):
        calls = []

        class GLib:
            @staticmethod
            def timeout_add(ms, fn):
                calls.append(("later", ms))

        class Gdk:
            class Display:
                @staticmethod
                def get_default():
                    return None

        class Sh:
            pass
        sh = Sh()
        sh.GLib, sh.Gdk = GLib, Gdk
        o = self.outside({"monitor": "DP-1", "x": 1500, "y": 17})
        o.sh, o.wins, o.done = sh, [], False
        o.on_click = lambda: calls.append("closed")
        o.clicked(1, Mon("DP-1"), 40, 17)
        o.clicked(1, Mon("DP-1"), 40, 17)
        self.assertEqual(calls, ["closed", ("later", 60)])
        calls.clear()
        o.done = False
        o.clicked(1, Mon("DP-1"), 1500, 17)                       # the icon: closes, nothing handed on
        self.assertEqual(calls, ["closed"])

    def test_the_clear_surface_is_drawn(self):
        # a GTK 4 surface with nothing drawn is never shown: the catcher must not be transparent
        css = P.css({"panel": "#000000"})
        line = next(ln for ln in css.splitlines() if "dg-catcher" in ln)
        self.assertNotIn("transparent", line)


class VirtualPointerTest(unittest.TestCase):
    """bromigos_vptr against a stand-in compositor: the requests it sends."""

    def test_no_display(self):
        env = dict(os.environ)
        os.environ.pop("WAYLAND_DISPLAY", None)
        try:
            self.assertFalse(V.click())
        finally:
            os.environ.clear()
            os.environ.update(env)

    def test_a_click(self):
        tmp = tempfile.mkdtemp()
        path = os.path.join(tmp, "wl")
        srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        srv.bind(path)
        srv.listen(1)
        seen = []

        def serve():
            conn, _ = srv.accept()
            buf = b""
            registry = None
            while True:
                chunk = conn.recv(65536)
                if not chunk:
                    break
                buf += chunk
                while len(buf) >= 8:
                    obj, word = struct.unpack_from("<II", buf)
                    size, op = word >> 16, word & 0xFFFF
                    if len(buf) < size:
                        break
                    payload, buf = buf[8:size], buf[size:]
                    seen.append((obj, op, payload))
                    if obj == 1 and op == 1:
                        registry, = struct.unpack("<I", payload)
                    elif obj == 1 and op == 0:
                        cb, = struct.unpack("<I", payload)
                        if registry is not None and len([s for s in seen if s[:2] == (1, 0)]) == 1:
                            for name, iface in ((1, "wl_seat"), (2, "zwlr_virtual_pointer_manager_v1")):
                                b = iface.encode() + b"\0"
                                body = struct.pack("<I", name) + struct.pack("<I", len(b)) + b + \
                                    b"\0" * ((4 - len(b) % 4) % 4) + struct.pack("<I", 1)
                                conn.sendall(struct.pack("<II", registry, ((8 + len(body)) << 16) | 0) + body)
                        conn.sendall(struct.pack("<II", cb, (12 << 16) | 0) + struct.pack("<I", 0))
            conn.close()
        t = threading.Thread(target=serve, daemon=True)
        t.start()
        env = dict(os.environ)
        os.environ["WAYLAND_DISPLAY"] = path
        try:
            self.assertTrue(V.click(V.BTN_RIGHT))
        finally:
            os.environ.clear()
            os.environ.update(env)
        t.join(3)
        srv.close()
        buttons = [struct.unpack("<III", p)[1:] for _, op, p in seen if op == 2 and len(p) == 12]
        self.assertEqual(buttons, [(V.BTN_RIGHT, 1), (V.BTN_RIGHT, 0)])
        self.assertFalse(any(op in (0, 1) and len(p) == 20 for _, op, p in seen if _ > 1), "it never moves the pointer")


if __name__ == "__main__":
    unittest.main()
