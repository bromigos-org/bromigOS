"""bromigos_gamepad: which axis is which stick and trigger, for the same Xbox pad on each
of its drivers (the capability sets as sysfs gives them), from SDL_GameControllerDB or,
for a pad it doesn't know, from the axes. Nothing reaches the machine's input devices:
the sysfs is made up and the events are fed in."""
import os
import shutil
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "lib"))
import bromigos_gamepad as G  # noqa: E402

# An Xbox Wireless Controller (Series X|S, 045e:0b13) as each driver presents it:
#   hid-microsoft (over Bluetooth, without xpadneo): ABS 30627 = X Y Z RZ GAS BRAKE HAT0X/Y
#   xpadneo (over Bluetooth): shows itself as 045e:028e; ABS 20003003f = X Y Z RX RY RZ HAT0 PROFILE
#   xpad (over USB, an Xbox One pad 045e:02ea): X Y Z RX RY RZ HAT0
PADS = {
    "hid-microsoft": {"bustype": 0x05, "vendor": 0x045e, "product": 0x0b13, "version": 0x0509,
                      "key": "7fff000000000000 0 0 0 0", "key_extra": {167}, "abs": "30627",
                      "hid": "0005:045E:0B13.0009", "driver": "microsoft"},
    "xpadneo": {"bustype": 0x05, "vendor": 0x045e, "product": 0x028e, "version": 0x1130,
                "key": "7cdb000000000000 0 0 0 0", "abs": "20003003f",
                "hid": "0005:045E:0B13.0011", "driver": "xpadneo"},
    "xpad": {"bustype": 0x03, "vendor": 0x045e, "product": 0x02ea, "version": 0x0408,
             "key": "7cdb000000000000 0 0 0 0", "abs": "3003f", "hid": None, "driver": "xpad"},
}
RANGES = {
    "hid-microsoft": {G.ABS_X: (0, 65535, 0), G.ABS_Y: (0, 65535, 0), G.ABS_Z: (0, 65535, 0),
                      G.ABS_RZ: (0, 65535, 0), G.ABS_GAS: (0, 1023, 0), G.ABS_BRAKE: (0, 1023, 0)},
    "xpadneo": {G.ABS_X: (-32768, 32767, 3072), G.ABS_Y: (-32768, 32767, 3072), G.ABS_RX: (-32768, 32767, 3072),
                G.ABS_RY: (-32768, 32767, 3072), G.ABS_Z: (0, 1023, 0), G.ABS_RZ: (0, 1023, 0)},
    "xpad": {G.ABS_X: (-32768, 32767, 128), G.ABS_Y: (-32768, 32767, 128), G.ABS_RX: (-32768, 32767, 128),
             G.ABS_RY: (-32768, 32767, 128), G.ABS_Z: (0, 1023, 0), G.ABS_RZ: (0, 1023, 0)},
}


def info(kind, **change):
    p = dict(PADS[kind], **change)
    return {"bustype": p["bustype"], "vendor": p["vendor"], "product": p["product"], "version": p["version"],
            "keys": G._bits(p["key"]) | p.get("key_extra", set()), "abs": G._bits(p["abs"]),
            "driver": {"microsoft": "hid-microsoft"}.get(p["driver"], p["driver"]), "hid": None}


def pad(i, ranges):
    p = G.Pad.__new__(G.Pad)
    p.info, p.layout, p.ranges = i, G.layout(i), ranges
    p.held, p.effect = set(), None
    p.axes = {"lx": 0.0, "ly": 0.0, "rx": 0.0, "ry": 0.0, "lt": 0.0, "rt": 0.0, "dx": 0, "dy": 0}
    return p


def ev(code, value, t=G.EV_ABS):
    return (t, code, value)


class Layouts(unittest.TestCase):
    def roles(self, i):
        return {name: code for code, (name, _) in G.layout(i).axes.items()}

    def test_hid_microsoft_right_stick_is_z_rz(self):
        i = info("hid-microsoft")
        lay = G.layout(i)
        self.assertEqual(lay.source, "SDL GameControllerDB")
        self.assertEqual(self.roles(i), {"lx": G.ABS_X, "ly": G.ABS_Y, "rx": G.ABS_Z, "ry": G.ABS_RZ,
                                         "lt": G.ABS_BRAKE, "rt": G.ABS_GAS})

    def test_xpadneo_right_stick_is_rx_ry(self):
        i = info("xpadneo")
        self.assertEqual(G.layout(i).source, "SDL GameControllerDB")
        self.assertEqual(self.roles(i), {"lx": G.ABS_X, "ly": G.ABS_Y, "rx": G.ABS_RX, "ry": G.ABS_RY,
                                         "lt": G.ABS_Z, "rt": G.ABS_RZ})

    def test_xpad_right_stick_is_rx_ry(self):
        i = info("xpad")
        self.assertEqual(G.layout(i).source, "SDL GameControllerDB")
        self.assertEqual(self.roles(i), {"lx": G.ABS_X, "ly": G.ABS_Y, "rx": G.ABS_RX, "ry": G.ABS_RY,
                                         "lt": G.ABS_Z, "rt": G.ABS_RZ})

    def test_a_firmware_the_database_hasnt_seen(self):
        i = info("hid-microsoft", version=0x0999)
        self.assertEqual(G.layout(i).source, "SDL GameControllerDB")
        self.assertEqual(self.roles(i)["rx"], G.ABS_Z)

    def test_another_firmwares_mapping_must_put_the_right_stick_where_the_axes_say(self):
        # the same ids under another version, mapped for another driver: RX/RY as the right
        # stick, which on hid-microsoft are the triggers. Not used: the axes decide.
        i = info("hid-microsoft", version=0x0999)
        g = G.guid(info("hid-microsoft", version=0x0101))
        db = {g: "Other,a:b0,b:b1,x:b3,y:b4,leftx:a0,lefty:a1,rightx:a4,righty:a5,"
                 "lefttrigger:a2,righttrigger:a3,platform:Linux,"}
        lay = G.layout(i, db)
        self.assertIn("from its axes", lay.source)
        self.assertEqual({n: c for c, (n, _) in lay.axes.items()}["rx"], G.ABS_Z)
        # its own GUID's mapping is taken as it is
        db = {G.guid(i): db[g]}
        self.assertEqual(G.layout(i, db).source, "SDL GameControllerDB")

    def test_a_pad_the_database_doesnt_know_by_its_axes(self):
        for kind, rx, lt in (("hid-microsoft", G.ABS_Z, G.ABS_BRAKE), ("xpadneo", G.ABS_RX, G.ABS_Z)):
            i = info(kind, product=0x7777)
            lay = G.layout(i)
            self.assertIn("from its axes", lay.source)
            self.assertEqual(self.roles(i)["rx"], rx, kind)
            self.assertEqual(self.roles(i)["lt"], lt, kind)
        self.assertEqual(G.layout_of({"abs": {G.ABS_X, G.ABS_Y, G.ABS_Z, G.ABS_RZ}}), "generic")

    def test_a_mapping_that_doesnt_fit_the_device_isnt_used(self):
        # the database's hid-microsoft mapping names a6 and b15; a pad with fewer axes and
        # buttons under the same ids isn't that layout
        i = info("hid-microsoft", abs="3", key="3000000000000 0 0 0 0", key_extra=set())
        self.assertIn("from its axes", G.layout(i).source)

    def test_sdl_gamecontrollerconfig_comes_first(self):
        i = info("xpadneo")
        g = G.guid(i)
        mine = f"{g},Mine,a:b0,b:b1,leftx:a0,lefty:a1,rightx:a5,righty:a2,platform:Linux,"
        old = os.environ.get("SDL_GAMECONTROLLERCONFIG")
        os.environ["SDL_GAMECONTROLLERCONFIG"] = mine
        try:
            self.assertEqual(self.roles(i)["rx"], G.ABS_RZ)
        finally:
            if old is None:
                os.environ.pop("SDL_GAMECONTROLLERCONFIG")
            else:
                os.environ["SDL_GAMECONTROLLERCONFIG"] = old

    def test_sdl_numbering(self):
        buttons, axes, hats = G.sdl_indices(info("hid-microsoft"))
        self.assertEqual(buttons["b3"], 0x133)            # BTN_C is b2: X is b3, as the database says
        self.assertEqual(buttons["b15"], 167)             # KEY_RECORD, below BTN_JOYSTICK: last
        self.assertEqual([axes[f"a{n}"] for n in range(6)],
                         [G.ABS_X, G.ABS_Y, G.ABS_Z, G.ABS_RZ, G.ABS_GAS, G.ABS_BRAKE])
        self.assertEqual(hats, {0: 0})

    def test_the_guid(self):
        self.assertEqual(G.guid(info("hid-microsoft")), "050000005e040000130b000009050000")


class Input(unittest.TestCase):
    def test_hid_microsoft_right_stick_moves_the_right_stick(self):
        # the operator's report: the right stick lit LT and RT and never moved the dot
        p = pad(info("hid-microsoft"), RANGES["hid-microsoft"])
        p.feed([ev(G.ABS_Z, 65535), ev(G.ABS_RZ, 0)])
        self.assertEqual((p.axes["rx"], p.axes["ry"]), (1.0, -1.0))
        self.assertEqual((p.axes["lt"], p.axes["rt"]), (0.0, 0.0))
        self.assertNotIn("LT", p.buttons)
        p.feed([ev(G.ABS_BRAKE, 1023), ev(G.ABS_GAS, 512)])
        self.assertEqual(p.axes["lt"], 1.0)
        self.assertAlmostEqual(p.axes["rt"], 0.5, places=2)
        self.assertEqual((p.axes["rx"], p.axes["ry"]), (1.0, -1.0))

    def test_xpadneo_and_xpad_right_stick_and_triggers(self):
        for kind in ("xpadneo", "xpad"):
            p = pad(info(kind), RANGES[kind])
            p.feed([ev(G.ABS_RX, 32767), ev(G.ABS_RY, -32768), ev(G.ABS_Z, 1023)])
            self.assertEqual((p.axes["rx"], p.axes["ry"]), (1.0, -1.0), kind)
            self.assertEqual((p.axes["lt"], p.axes["rt"]), (1.0, 0.0), kind)

    def test_the_dead_zone(self):
        p = pad(info("xpadneo"), RANGES["xpadneo"])
        p.feed([ev(G.ABS_X, 2000), ev(G.ABS_Y, -3000)])
        self.assertEqual((p.axes["lx"], p.axes["ly"]), (0.0, 0.0))
        p.feed([ev(G.ABS_X, 16384)])
        self.assertGreater(p.axes["lx"], 0.4)

    def test_buttons_as_the_database_names_them(self):
        p = pad(info("hid-microsoft"), RANGES["hid-microsoft"])
        p.feed([ev(0x130, 1, G.EV_KEY), ev(0x133, 1, G.EV_KEY), ev(167, 1, G.EV_KEY), ev(0x132, 1, G.EV_KEY)])
        self.assertEqual(p.buttons, ["A", "SHARE", "X"])  # BTN_C is nothing on this pad

    def test_the_dpad_as_a_hat_and_as_buttons(self):
        p = pad(info("xpadneo"), RANGES["xpadneo"])
        p.feed([ev(G.ABS_HAT0X, -1), ev(G.ABS_HAT0Y, 1)])
        self.assertEqual(p.buttons, ["DOWN", "LEFT"])
        p.feed([ev(G.ABS_HAT0X, 0), ev(G.ABS_HAT0Y, 0)])
        self.assertEqual(p.buttons, [])
        q = pad(info("xpad", key="7cdb000000000000 0 0 0 0", key_extra={0x220, 0x223}), RANGES["xpad"])
        q.feed([ev(0x220, 1, G.EV_KEY), ev(0x223, 1, G.EV_KEY)])
        self.assertEqual(q.buttons, ["RIGHT", "UP"])


class Sysfs(unittest.TestCase):
    """info() and the driver hint from a made-up /sys."""

    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="gpi-")

    def tearDown(self):
        shutil.rmtree(self.root)

    def device(self, n, kind):
        p = PADS[kind]
        hid = os.path.join(self.root, "sys/devices/virtual/misc/uhid", p["hid"] or "1-2:1.0")
        drv = os.path.join(self.root, "sys/bus/hid/drivers", p["driver"])
        os.makedirs(hid)
        os.makedirs(drv)
        os.symlink(drv, os.path.join(hid, "driver"))
        inp = os.path.join(hid, "input", f"input{n}")
        os.makedirs(os.path.join(inp, "capabilities"))
        os.makedirs(os.path.join(inp, "id"))
        os.symlink(hid, os.path.join(inp, "device"))
        for k in ("bustype", "vendor", "product", "version"):
            with open(os.path.join(inp, "id", k), "w") as f:
                f.write(f"{p[k]:04x}\n")
        with open(os.path.join(inp, "name"), "w") as f:
            f.write("Xbox Wireless Controller\n")
        for k in ("key", "abs"):
            with open(os.path.join(inp, "capabilities", k), "w") as f:
                f.write(p[k] + "\n")
        cls = os.path.join(self.root, "sys/class/input", f"event{n}")
        os.makedirs(cls)
        os.symlink(inp, os.path.join(cls, "device"))
        return f"/dev/input/event{n}"

    def test_hid_microsoft(self):
        i = G.info(self.device(31, "hid-microsoft"), self.root)
        self.assertEqual(i["driver"], "hid-microsoft")
        self.assertEqual(i["hid"], "045e:0b13")
        self.assertEqual(G.guid(i), "050000005e040000130b000009050000")
        self.assertTrue(G.basic_driver(i))
        self.assertEqual(G.layout(i).axes[G.ABS_Z][0], "rx")

    def test_xpadneo_is_the_pad_under_its_028e(self):
        i = G.info(self.device(31, "xpadneo"), self.root)
        self.assertEqual(i["driver"], "xpadneo")
        self.assertEqual((i["vendor"], i["product"]), (0x045e, 0x028e))
        self.assertEqual(i["hid"], "045e:0b13")
        self.assertFalse(G.basic_driver(i))
        self.assertEqual(G.layout(i).axes[G.ABS_RX][0], "rx")

    def test_no_sysfs(self):
        i = G.info("/dev/input/event99", self.root)
        self.assertIsNone(i["driver"])
        self.assertFalse(G.basic_driver(i))
        self.assertIn("xpad layout", G.layout(i).source)


if __name__ == "__main__":
    unittest.main()
