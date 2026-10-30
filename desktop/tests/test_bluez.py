"""The bar's Bluetooth: bromigos_bluez (the state, the bar's line, the words, PipeWire's cards,
the agent) against the stand-in bluez on a private D-Bus (fake_bluez.py: nothing reaches the
machine's Bluetooth), the bar module's toasts and glow, and the panel's words."""
import io
import json
import os
import shutil
import sys
import tempfile
import time
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path[:0] = [HERE, os.path.join(os.path.dirname(HERE), "lib")]

import bromigos_bluez as B  # noqa: E402
import bromigos_btpanel as P  # noqa: E402

HAVE_BUS = shutil.which("dbus-daemon") is not None
try:
    from gi.repository import GLib  # noqa: F401
except ImportError:
    HAVE_BUS = False

WH, PAD, MOUSE, BUDS = ("00:00:5E:00:53:10", "00:00:5E:00:53:12", "00:00:5E:00:53:11", "00:00:5E:00:53:13")


def dev(name="Dev", icon="", connected=False, paired=True, battery=None, **kw):
    k = B.kind(icon, name)
    d = {"path": "/org/bluez/hci0/dev_X", "mac": kw.pop("mac", "00:00:5E:00:53:99"), "name": name, "alias": name,
         "icon": icon, "kind": k, "glyph": B.glyph(k), "paired": paired, "bonded": paired, "connected": connected,
         "trusted": True, "blocked": False, "battery": battery, "rssi": None, "audio": icon.startswith("audio"),
         "audio_source": False, "xbox": B.is_xbox(name, icon), "adapter": "/org/bluez/hci0"}
    d.update(kw)
    return d


def state(devs=(), powered=True, discovering=False, **kw):
    devs = list(devs)
    st = {"available": True, "adapter": {"path": "/org/bluez/hci0", "mac": "00:00:5E:00:53:01", "name": "box",
                                         "alias": "box", "powered": powered, "discoverable": False,
                                         "discovering": discovering, "pairable": True},
          "powered": powered, "blocked": False, "hard_blocked": False, "hardware": True, "devices": devs,
          "paired": [d for d in devs if d["paired"]], "nearby": [d for d in devs if not d["paired"]],
          "connected": [d for d in devs if d["connected"]]}
    st.update(kw)
    return st


class Words(unittest.TestCase):
    def test_kinds(self):
        self.assertEqual(B.kind("input-gaming", "Xbox Wireless Controller"), "game controller")
        self.assertEqual(B.kind("", "Xbox Elite Wireless Controller Series 2"), "game controller")
        self.assertEqual(B.glyph(B.kind("input-gaming", "Xbox Wireless Controller")), "controller")
        self.assertEqual(B.kind("audio-headphones", "Galaxy Buds2 Pro"), "earbuds")
        self.assertEqual(B.kind("audio-headset", "WH-1000XM5"), "headset")
        self.assertEqual(B.kind("", "Thing"), "device")
        self.assertFalse(B.is_xbox("Xbox Wireless Headset", "audio-headset"))
        self.assertEqual(B.mac_of("/org/bluez/hci0/dev_00_00_5E_00_53_10"), WH)

    def test_errors_in_plain_words(self):
        self.assertIn("pairing mode", B.explain("GDBus.Error:org.bluez.Error.AuthenticationFailed: Authentication Failed"))
        self.assertIn("switched on and nearby", B.explain("GDBus.Error:org.bluez.Error.Failed: Page Timeout"))
        self.assertIn("bluetoothd isn't running", B.explain("GDBus.Error:org.freedesktop.DBus.Error.ServiceUnknown: x"))
        self.assertEqual(B.explain("GDBus.Error:org.bluez.Error.Failed: odd thing"), "Odd thing")
        self.assertTrue(B.explain(None))

    def test_battery_levels(self):
        self.assertEqual([B.level(x) for x in (None, 3, 15, 16)], ["unknown", "critical", "low", "ok"])
        self.assertEqual([B.cells(x) for x in (None, 0, 1, 50, 100)], [0, 0, 1, 2, 5])

    def test_the_main_device_is_the_controller_then_the_headset(self):
        wh = dev("WH", "audio-headset", True, battery=70, mac=WH)
        pad = dev("Xbox Wireless Controller", "input-gaming", True, battery=80, mac=PAD)
        mouse = dev("Mouse", "input-mouse", True, battery=5, mac=MOUSE)
        self.assertEqual(B.main_device(state([wh, pad, mouse]))["mac"], PAD)
        self.assertEqual(B.main_device(state([wh, mouse]))["mac"], WH)
        self.assertIsNone(B.main_device(state([dev("Thing", connected=True)])))


class Bar(unittest.TestCase):
    def test_hidden_without_an_adapter(self):
        self.assertEqual(B.bar(B.unavailable(root="/nonexistent"))["text"], "")
        st = dict(state(), adapter=None, hardware=False)
        self.assertEqual(B.bar(st)["class"], ["none"])

    def test_bluetoothd_down_with_hardware_says_so(self):
        d = B.bar(dict(B.unavailable(root="/nonexistent"), hardware=True))
        self.assertEqual(d["class"], ["off", "problem"])
        self.assertIn("systemctl enable --now bluetooth", d["tooltip"])

    def test_off_on_connected(self):
        off = B.bar(state(powered=False))
        self.assertEqual(off["class"], ["off"])
        self.assertIn("turn on", off["tooltip"])
        on = B.bar(state())
        self.assertEqual(on["class"], ["on"])
        self.assertEqual(on["text"], " ")              # never empty: an empty text hides it
        self.assertIn("click: devices", on["tooltip"])
        c = B.bar(state([dev("WH <&>", "audio-headset", True, battery=70, mac=WH)]))
        self.assertEqual(c["class"], ["connected", "c4"])
        self.assertIn(">1<", c["text"])
        self.assertIn("WH &lt;&amp;&gt; · headset · 70%", c["tooltip"])

    def test_low_battery_is_amber_and_steady(self):
        c = B.bar(state([dev("Xbox Wireless Controller", "input-gaming", True, battery=12, mac=PAD)]))
        self.assertEqual(c["class"], ["connected", "c1", "low"])
        self.assertIn("12% <b>LOW</b>", c["tooltip"])
        self.assertNotIn("scanning", c["class"])

    def test_motion(self):
        st = state(discovering=True)
        self.assertIn("scanning", B.bar(st)["class"])
        self.assertIn("busy", B.bar(st, motion="reduced")["class"])
        self.assertNotIn("scanning", B.bar(st, motion="reduced")["class"])
        self.assertIn("spark", B.bar(state(), spark=True)["class"])
        self.assertNotIn("spark", B.bar(state(), motion="reduced", spark=True)["class"])
        self.assertIn("busy", B.bar(state(), motion="still", busy=True)["class"])


class Cards(unittest.TestCase):
    def test_profiles_and_codecs(self):
        with open(os.path.join(HERE, "fixtures", "pactl.json")) as f:
            cards = json.load(f)["cards"]
        got = B.audio_cards(cards)[WH]
        self.assertEqual((got["mode"], got["codec"], got["hifi"], got["headset"]),
                         ("hifi", "LDAC", "a2dp-sink", "headset-head-unit"))
        cards[0]["active_profile"] = "headset-head-unit-cvsd"
        got = B.audio_cards(cards)[WH]
        self.assertEqual((got["mode"], got["codec"]), ("headset", "CVSD"))
        cards[0]["active_profile"] = "off"
        self.assertEqual(B.audio_cards(cards)[WH]["codec"], None)
        self.assertEqual(B.audio_cards([{"name": "alsa_card.pci"}]), {})
        self.assertEqual(B.codec_of("a2dp-sink-aac"), "AAC")
        self.assertEqual(B.profile_mode("a2dp-source"), None)


class PanelWords(unittest.TestCase):
    def test_status_and_action(self):
        wh = dev("WH", "audio-headset", True, battery=70, mac=WH)
        self.assertEqual(P.status_words(wh, {"mode": "hifi", "codec": "LDAC"}), "CONNECTED · HI-FI · LDAC")
        self.assertEqual(P.action(wh)[:2], ("DISCONNECT", "disconnect"))
        off = dev("Mouse", "input-mouse", False, mac=MOUSE, trusted=False)
        self.assertEqual(P.status_words(off), "NOT CONNECTED · ASKS FIRST")
        self.assertEqual(P.action(off)[:2], ("CONNECT", "connect"))
        near = dev("JBL", "audio-card", paired=False, rssi=-58)
        self.assertEqual(P.status_words(near), "SPEAKER · SIGNAL STRONG")
        self.assertEqual(P.action(near)[:2], ("PAIR", "pair"))
        self.assertIn("pairing mode", P.action(near)[2])
        self.assertEqual(P.status_words(wh, op="connecting"), "CONNECTING…")
        self.assertIsNone(P.action(wh, "connecting")[1])

    def test_the_xbox_driver_note(self):
        pad = dev("Xbox Wireless Controller", "input-gaming", True, mac=PAD)
        with tempfile.TemporaryDirectory() as root:
            with mock.patch.dict(os.environ, {"BROMIGOS_PERIPHERAL_ROOT": root}):
                note = P.driver_note(pad)
                self.assertIn("xpadneo", note[1])
                self.assertIn("bromigos peripheral enable xbox-controller", note[1])
                os.makedirs(os.path.join(root, "sys/module/hid_xpadneo"))
                self.assertIsNone(P.driver_note(pad))
        self.assertIsNone(P.driver_note(dev("Mouse", "input-mouse")))

    def test_prompts(self):
        t, m, buttons, entry = P.prompt_words("confirm", "Pixel 9", "123456")
        self.assertIn("123 456", m)
        self.assertEqual([b[1] for b in buttons], [True, False])
        self.assertEqual(P.prompt_words("pin", "Car kit", None)[3], "pin")
        self.assertIn("type 123 456", P.prompt_words("type", "K3", ("123456", 2))[1])

    def test_the_menu(self):
        items = P.menu_items(state([dev("WH", "audio-headset", True, mac=WH), dev("M", "input-mouse", mac=MOUSE)]))
        ids = [i[0] for i in items]
        self.assertEqual(ids, ["power", "visible", f"dev:{WH}", f"dev:{MOUSE}", "panel", "settings"])
        self.assertEqual(items[2][2], "DISCONNECT")
        self.assertTrue(all(i[3] for i in items))          # every item explains itself
        off = P.menu_items(state([dev("WH", mac=WH)], powered=False))
        self.assertFalse(off[1][4] or off[2][4])            # visible and devices: not while off
        self.assertEqual(P.menu_items(dict(state(), adapter=None))[0][0], "none")


class Settings(unittest.TestCase):
    def test_audio_default_round_trip(self):
        with tempfile.TemporaryDirectory() as d:
            with mock.patch.dict(os.environ, {"XDG_CONFIG_HOME": d}):
                self.assertTrue(B.settings()["audio_default"])
                B.save_settings({"audio_default": False})
                self.assertFalse(B.settings()["audio_default"])


@unittest.skipUnless(HAVE_BUS, "needs dbus-daemon and PyGObject")
class Live(unittest.TestCase):
    """bromigos_bluez against the stand-in bluez."""

    def setUp(self):
        from fake_bluez import FakeBluez
        from gi.repository import GLib
        self.GLib = GLib
        self.fb = FakeBluez().__enter__()
        self.env = mock.patch.dict(os.environ, {"BROMIGOS_BLUEZ_BUS": self.fb.address,
                                                "BROMIGOS_PERIPHERAL_ROOT": "/nonexistent"})
        self.env.start()
        self.seen = []
        self.bz = B.Bluez(self.seen.append).start()

    def tearDown(self):
        self.bz.stop()
        self.env.stop()
        self.fb.__exit__()

    def wait(self, cond, secs=6):
        ctx = self.GLib.MainContext.default()
        end = time.monotonic() + secs
        while time.monotonic() < end:
            ctx.iteration(False)
            if cond():
                return True
            time.sleep(0.01)
        return False

    def call(self, fn, *a, **kw):
        got = []
        fn(*a, lambda ok, err: got.append((ok, err)), **kw)
        self.assertTrue(self.wait(lambda: got), "no answer")
        return got[0]

    def test_the_state(self):
        st = self.bz.state()
        self.assertEqual(st["adapter"]["alias"], "workstation")
        self.assertEqual([d["name"] for d in st["connected"]], ["WH-1000XM5", "Xbox Wireless Controller"])
        pad = self.bz.find(PAD)
        self.assertEqual((pad["glyph"], pad["battery"], pad["xbox"]), ("controller", 12, True))
        self.assertTrue(self.bz.find(WH)["audio"])
        self.assertEqual(st["nearby"], [])

    def test_signals_arrive_without_polling(self):
        self.seen.clear()
        self.fb.set(f"/org/bluez/hci0/dev_{MOUSE.replace(':', '_')}", "org.bluez.Device1", "Connected", True)
        self.assertTrue(self.wait(lambda: self.seen and self.bz.find(MOUSE)["connected"]))
        self.fb.set(f"/org/bluez/hci0/dev_{PAD.replace(':', '_')}", "org.bluez.Battery1", "Percentage", 9)
        self.assertTrue(self.wait(lambda: self.bz.find(PAD)["battery"] == 9))

    def test_connect_disconnect_trust_forget_power(self):
        mouse = self.bz.find(MOUSE)
        self.assertEqual(self.call(self.bz.connect, mouse["path"]), (True, None))
        self.assertTrue(self.wait(lambda: self.bz.find(MOUSE)["connected"]))
        self.assertEqual(self.call(self.bz.disconnect, mouse["path"]), (True, None))
        self.assertEqual(self.call(self.bz.trust, mouse["path"], False), (True, None))
        self.assertTrue(self.wait(lambda: not self.bz.find(MOUSE)["trusted"]))
        self.assertEqual(self.call(self.bz.forget, mouse["path"]), (True, None))
        self.assertTrue(self.wait(lambda: self.bz.find(MOUSE) is None))
        self.assertEqual(self.call(self.bz.power, False), (True, None))
        self.assertTrue(self.wait(lambda: not self.bz.state()["adapter"]["powered"]))
        self.assertTrue(self.wait(lambda: not self.bz.state()["connected"]))
        ok, err = self.call(self.bz.connect, self.bz.find(WH)["path"])
        self.assertFalse(ok)
        self.assertIn("isn't ready", err)

    def scan(self):
        self.assertEqual(self.call(self.bz.scan, True), (True, None))
        self.assertTrue(self.wait(lambda: len(self.bz.state()["nearby"]) == 4, 8))

    def pair(self, mac, answer):
        """Pairs mac with one agent for the test: answer(what) is the UI's reply."""
        asked = []
        t = self

        class UI:
            def prompt(self, what, path, value, reply):
                t.asked.append((what, value))
                reply(t.answer(what))

            def cancel(self):
                t.asked.append(("cancel", None))
        self.asked, self.answer = asked, answer
        if self.bz.agent is None:
            self.assertEqual(self.call(self.bz.register_agent, B.Agent(UI())), (True, None))
        steps = []
        got = self.call(self.bz.pair, self.bz.find(mac)["path"], step=steps.append)
        return got, asked, steps

    def test_scan_then_pair_with_a_confirmed_passkey(self):
        self.scan()
        self.assertEqual(self.bz.state()["nearby"][0]["name"], "JBL Flip 6")    # strongest first
        got, asked, steps = self.pair("00:00:5E:00:53:21", lambda what: True)
        self.assertEqual(got, (True, None))
        self.assertEqual(asked, [("confirm", "123456")])
        self.assertEqual(steps, ["pairing", "trusting", "connecting"])
        self.assertTrue(self.wait(lambda: self.bz.find("00:00:5E:00:53:21")["connected"]))
        pixel = self.bz.find("00:00:5E:00:53:21")
        self.assertTrue(pixel["paired"] and pixel["trusted"])
        # a phone connects for its sound only
        self.assertIn(["ConnectProfile", pixel["path"], B.A2DP_SOURCE], self.fb.calls())

    def test_a_refused_code_says_so(self):
        self.scan()
        got, asked, _ = self.pair("00:00:5E:00:53:21", lambda what: False)
        self.assertEqual(got, (False, B.explain("AuthenticationRejected")))
        self.assertFalse(self.bz.find("00:00:5E:00:53:21")["paired"])

    def test_a_pin_and_a_keyboard(self):
        self.scan()
        got, asked, _ = self.pair("00:00:5E:00:53:23", lambda what: "0000")
        self.assertEqual((got, asked), ((True, None), [("pin", None)]))
        got, asked, _ = self.pair("00:00:5E:00:53:22", lambda what: None)
        self.assertEqual(got, (True, None))
        self.assertEqual(asked, [("type", ("123456", 0))])

    def test_a_wrong_pin_fails_in_plain_words(self):
        self.scan()
        got, _, _ = self.pair("00:00:5E:00:53:23", lambda what: "1234")
        self.assertFalse(got[0])
        self.assertIn("codes didn't match", got[1])


class Module(unittest.TestCase):
    """The bar module's lines, glow and toasts (bromigos-desktop's waybar/scripts/bluetooth.py)."""

    def setUp(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "btbar", os.path.join(os.path.dirname(HERE), "waybar", "scripts", "bluetooth.py"))
        self.M = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.M)

    def test_lines_glow_and_toasts(self):
        clock = [10.0]
        out = io.StringIO()
        later = []
        m = self.M.Module(out=out, lead=True, now=lambda: clock[0], later=later.append)
        toasts, outputs = [], []
        wh = dev("WH", "audio-headset", True, battery=70, mac=WH)
        with mock.patch.object(B, "notify", lambda *a, **k: toasts.append(a[:2])), \
                mock.patch.object(self.M, "audio_default", outputs.append), \
                mock.patch.object(self.M, "motion", lambda: "full"), \
                mock.patch.object(self.M, "busy", lambda: False):
            m.changed(state([dev("WH", "audio-headset", False, mac=WH)]))
            m.changed(state([dev("WH", "audio-headset", False, mac=WH)]))     # the same: no new line
            self.assertEqual(len(out.getvalue().splitlines()), 1)
            self.assertEqual(toasts, [])                                         # nothing on start
            m.changed(state([wh]))
            last = json.loads(out.getvalue().splitlines()[-1])
            self.assertIn("spark", last["class"])
            self.assertEqual(toasts, [("WH", "connected · battery 70%")])
            self.assertEqual(outputs, [WH])
            self.assertEqual(later, [self.M.SPARK + 0.05])
            clock[0] += 2
            m.emit()
            self.assertNotIn("spark", json.loads(out.getvalue().splitlines()[-1])["class"])
            m.changed(state([dev("WH", "audio-headset", False, mac=WH)]))
            self.assertEqual(toasts[-1], ("WH", "disconnected"))

    def test_only_the_leader_toasts_and_settings_can_stop_the_switch(self):
        toasts, outputs = [], []
        m = self.M.Module(out=io.StringIO(), lead=None)
        with mock.patch.object(B, "notify", lambda *a, **k: toasts.append(a)), \
                mock.patch.object(self.M, "audio_default", outputs.append):
            m.changed(state())
            m.changed(state([dev("WH", "audio-headset", True, mac=WH)]))
        self.assertEqual((toasts, outputs), ([], []))
        lead = self.M.Module(out=io.StringIO(), lead=True)
        with mock.patch.object(B, "notify", lambda *a, **k: toasts.append(a)), \
                mock.patch.object(self.M, "audio_default", outputs.append), \
                mock.patch.object(B, "settings", lambda: {"audio_default": False}):
            lead.changed(state())
            lead.changed(state([dev("WH", "audio-headset", True, mac=WH)]))
            lead.changed(state([dev("WH", "audio-headset", True, mac=WH),
                                dev("Pixel", "phone", True, mac=PAD, audio=True, audio_source=True)]))
        self.assertEqual(len(toasts), 2)
        self.assertEqual(outputs, [])


if __name__ == "__main__":
    unittest.main()
