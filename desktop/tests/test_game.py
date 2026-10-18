"""Game focus policy, recovery and keyboard event filtering without a real desktop."""
import importlib.machinery
import importlib.util
from pathlib import Path
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

path = Path(__file__).resolve().parents[1] / "bin/bromigos-game"
spec = importlib.util.spec_from_loader("game_mode", importlib.machinery.SourceFileLoader("game_mode", str(path)))
G = importlib.util.module_from_spec(spec)
spec.loader.exec_module(G)


class GameTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.addCleanup(patch.stopall)
        patch.object(G, "runtime", return_value=self.root).start()
        patch.object(G, "CONFIG", self.root / "config.json").start()

    def test_fullscreen_policy_excludes_launchers_and_native_non_games(self):
        for cls in ("steam_app_123", "SC2_x64.exe", "gamescope"):
            self.assertTrue(G.game_window({"class": cls, "fullscreen": 2}))
            self.assertFalse(G.game_window({"class": cls, "fullscreen": 0}))
        for cls in ("Steam", "lutris", "Battle.net.exe", "kitty", "launcher.exe"):
            self.assertFalse(G.game_window({"class": cls, "fullscreen": 2}))
        self.assertFalse(G.enabled())

    def test_auto_focus_loss_and_manual_escape_suppression(self):
        G.write(G.CONFIG, {"auto": True})
        mode = G.Mode()
        window = {"class": "SC2.exe", "fullscreen": 2, "address": "0x123"}
        patch.object(mode, "focus", side_effect=lambda: window).start()
        patch.object(mode, "keyboard").start()
        patch.object(G, "ctl", return_value=G.SUBMAP).start()
        def on(reason="manual"):
            G.write(G.marker(), {"paused":"false"})
            mode.reason = reason
            return mode.status()
        def off():
            G.marker().unlink(missing_ok=True)
            return mode.status()
        patch.object(mode, "on", side_effect=on).start()
        patch.object(mode, "off", side_effect=off).start()
        mode.tick()
        self.assertTrue(mode.status()["on"])
        self.assertEqual(mode.reason, "automatic")
        mode.request("off")
        mode.tick()
        self.assertFalse(mode.status()["on"])
        window = {"class":"kitty", "fullscreen":0, "address":"0x456"}
        mode.tick()
        window = {"class":"SC2.exe", "fullscreen":2, "address":"0x123"}
        mode.tick()
        self.assertTrue(mode.status()["on"])
        window = {"class":"kitty", "fullscreen":0, "address":"0x456"}
        mode.tick()
        self.assertFalse(mode.status()["on"])
        on("manual")
        mode.tick()
        self.assertTrue(mode.status()["on"])
        mode.request("auto off")
        self.assertTrue(mode.status()["on"])

    def test_dnd_snapshot_survives_failed_restore_and_retry(self):
        G.write(G.marker(), {"paused":"true", "leds":{"test":True}})
        mode=G.Mode()
        patch.object(G,"ctl",return_value=G.SUBMAP).start()
        reset=patch.object(G,"dispatch").start()
        cmd=patch.object(G,"run",side_effect=RuntimeError("dunst unavailable")).start()
        with self.assertRaises(RuntimeError): mode.off()
        reset.assert_called_with("reset")
        self.assertTrue(G.marker().exists())
        cmd.side_effect=None
        led=patch.object(mode,"leds").start()
        mode.off()
        cmd.assert_any_call("dunstctl","set-paused","true")
        cmd.assert_any_call("hyprctl", "notify", "-1", "4000", "rgb(99dd99)",
                            "GAME MODE OFF — desktop controls restored", required=False)
        led.assert_called_with(False)
        self.assertFalse(G.marker().exists())

    def test_game_key_only_toggles_on_press_without_grabbing_keyboard(self):
        mode=G.Mode(); mode.last_scan=time.monotonic()
        events=[SimpleNamespace(type=1,code=0x2ac,value=v) for v in (1,2,0)]
        events += [SimpleNamespace(type=1,code=30,value=1)]
        dev=SimpleNamespace(fd=99,read=lambda: events)
        mode.inputs={"fake":dev}
        patch.object(G.select,"select",return_value=([99],[],[])).start()
        request=patch.object(mode,"request").start()
        mode.keyboard()
        request.assert_called_once_with("toggle")

    def test_led_reconciles_openrazer_key_manager_writes(self):
        import sys
        import types
        dev=SimpleNamespace(type="keyboard",serial="test",has=lambda feature:feature=="game_mode_led",
                            game_mode_led=False)
        client=types.ModuleType("openrazer.client")
        client.DeviceManager=lambda:SimpleNamespace(devices=[dev])
        with patch.dict(sys.modules,{"openrazer":types.ModuleType("openrazer"),"openrazer.client":client}), \
             patch.object(G,"razer_enabled",return_value=True), \
             patch.object(G,"ctl",return_value=G.SUBMAP):
            mode=G.Mode()
            mode.leds(True)
            self.assertTrue(dev.game_mode_led)
            G.write(G.marker(),{"paused":"false"})
            dev.game_mode_led=False  # an asynchronous OpenRazer write arrives afterwards
            with patch.object(mode,"keyboard"):
                mode.tick()
            self.assertTrue(dev.game_mode_led)
            mode.leds(False)
            self.assertFalse(dev.game_mode_led)

    def test_native_lutris_game_ancestry_and_unrelated_fullscreen_app(self):
        with patch.object(G,"lutris_ancestor",side_effect=lambda pid:pid==123):
            self.assertTrue(G.game_window({"class":"native-game","fullscreen":2,"pid":123}))
            self.assertFalse(G.game_window({"class":"editor","fullscreen":2,"pid":456}))
            self.assertFalse(G.game_window({"class":"lutris","fullscreen":2,"pid":123}))
        self.assertFalse(G.lutris_ancestor(None))
        self.assertFalse(G.lutris_ancestor(-1))


if __name__ == "__main__":
    unittest.main()
