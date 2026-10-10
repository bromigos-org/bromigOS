"""A virtual pointer for a test compositor: moves, clicks and drags in a nested or headless
Hyprland (zwlr_virtual_pointer_v1, which Hyprland treats like a mouse) without touching
any real input device. A bare Wayland client, like vkbd.py beside it. Used by
e2e_widgets_nested.py.

    p = VirtualPointer("/run/user/1000/wayland-9", 1600, 900)   # the output's size
    p.move(200, 120)
    p.click()                      # left; p.click(RIGHT)
    p.drag((200, 120), (480, 300)) # press, move there in steps, let go
"""
import socket
import struct
import time

from vkbd import VirtualKeyboard

LEFT, RIGHT, MIDDLE = 0x110, 0x111, 0x112        # BTN_LEFT, BTN_RIGHT, BTN_MIDDLE


class VirtualPointer:
    # the wire: the same bare client as the keyboard's
    _id = VirtualKeyboard._id
    _send = VirtualKeyboard._send
    _pack_string = staticmethod(VirtualKeyboard._pack_string)
    _string = staticmethod(VirtualKeyboard._string)
    _bind = VirtualKeyboard._bind
    _roundtrip = VirtualKeyboard._roundtrip
    _ms = VirtualKeyboard._ms

    def __init__(self, path, width, height, delay=0.02):
        self.s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.s.connect(path)
        self.w, self.h, self.delay = int(width), int(height), delay
        self.next, self.buf, self.t0 = 2, b"", time.monotonic()
        reg = self._id()
        self._send(1, 1, struct.pack("<I", reg))           # wl_display.get_registry
        globs = {}
        for obj, op, payload in self._roundtrip():
            if obj == reg and op == 0:
                name, = struct.unpack_from("<I", payload)
                iface, off = self._string(payload, 4)
                ver, = struct.unpack_from("<I", payload, off)
                globs[iface] = (name, ver)
        if "zwlr_virtual_pointer_manager_v1" not in globs:
            raise RuntimeError("the compositor has no virtual pointer protocol")
        seat = self._bind(reg, globs, "wl_seat", 1)
        mgr = self._bind(reg, globs, "zwlr_virtual_pointer_manager_v1", 1)
        self.ptr = self._id()
        self._send(mgr, 0, struct.pack("<II", seat, self.ptr))   # create_virtual_pointer
        self._roundtrip()
        self.at = (0, 0)

    def _frame(self):
        self._send(self.ptr, 4)                              # frame
        self._roundtrip()
        time.sleep(self.delay)

    def move(self, x, y):
        """To (x, y) on the output, in its px."""
        x = max(0, min(self.w - 1, int(round(x))))
        y = max(0, min(self.h - 1, int(round(y))))
        self._send(self.ptr, 1, struct.pack("<IIIII", self._ms(), x, y, self.w, self.h))   # motion_absolute
        self._frame()
        self.at = (x, y)

    def button(self, which, down):
        self._send(self.ptr, 2, struct.pack("<III", self._ms(), which, 1 if down else 0))
        self._frame()

    def arrive(self, x, y, settle=0.15):
        """To (x, y) the way a hand gets there: from a pixel away, then a moment's rest, so
        the surface under it has had its enter and motion before a button goes down."""
        self.move(x + 2, y + 1)
        self.move(x, y)
        time.sleep(settle)

    def click(self, which=LEFT, at=None):
        if at:
            self.arrive(*at)
        self.button(which, True)
        time.sleep(0.05)
        self.button(which, False)

    def drag(self, start, end, steps=12, hold=0.15):
        """Press at start, move to end in steps (a person's drag), let go."""
        self.arrive(*start)
        self.button(LEFT, True)
        time.sleep(hold)
        (x0, y0), (x1, y1) = start, end
        for i in range(1, steps + 1):
            self.move(x0 + (x1 - x0) * i / steps, y0 + (y1 - y0) * i / steps)
        time.sleep(hold)
        self.button(LEFT, False)

    def close(self):
        self.s.close()
