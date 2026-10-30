"""Check the login launcher with fake hardware answers and a fake Weston exec.

The tests never start a compositor, read hardware, or change the current desktop.
"""

import importlib.machinery
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch


SOURCE = Path(__file__).resolve().parents[1] / "bromigos-greeter"
loader = importlib.machinery.SourceFileLoader("bromigos_greeter", str(SOURCE))
spec = importlib.util.spec_from_loader(loader.name, loader)
greeter = importlib.util.module_from_spec(spec)
loader.exec_module(greeter)


def response(primary=None, reason_code="multiple_connected_gpus", **changes):
    data = {
        "schema": 1,
        "primary_card": primary,
        "drm_devices": ["/dev/dri/" + primary] if primary else [],
        "reason_code": reason_code,
        "reason": "Hardware policy result.",
    }
    data.update(changes)
    return SimpleNamespace(returncode=0, stdout=json.dumps(data).encode())


class FakeClock:
    def __init__(self):
        self.now = 0.0

    def monotonic(self):
        return self.now

    def sleep(self, seconds):
        self.now += seconds


class GreeterLauncher(unittest.TestCase):
    def setUp(self):
        home = self.enterContext(tempfile.TemporaryDirectory())
        self.enterContext(patch.dict(os.environ, {"HOME": home, "PATH": home}, clear=True))
        self.query = self.enterContext(patch.object(greeter.subprocess, "run"))
        self.query.return_value = response()
        self.execute = self.enterContext(patch.object(greeter.os, "execv"))
        self.clock = FakeClock()
        self.enterContext(patch.object(greeter.time, "monotonic", self.clock.monotonic))
        self.sleep = self.enterContext(patch.object(greeter.time, "sleep", side_effect=self.clock.sleep))
        self.enterContext(patch.object(greeter.sys, "stderr"))

    def assert_weston(self, *args):
        self.execute.assert_called_once_with(
            "/usr/bin/weston", ["/usr/bin/weston", "--shell=kiosk", *args])

    def test_connected_card_comes_from_policy_not_boot_vga_or_card_order(self):
        self.query.return_value = response("card4", "single_connected_gpu",
                                          drm_devices=["/dev/dri/card4", "/dev/dri/card0"])
        greeter.main(["--socket=greeter"])
        self.assert_weston("--drm-device=card4", "--socket=greeter")
        self.query.assert_called_once()
        command = self.query.call_args.args[0]
        self.assertEqual(command, ["/usr/bin/bromigos", "hw", "display", "--json"])
        options = self.query.call_args.kwargs
        self.assertLessEqual(options["timeout"], 1.0)
        self.assertEqual(options["stdin"], subprocess.DEVNULL)
        self.assertEqual(options["env"]["XDG_SEAT"], "seat0")

    def test_a_card_chosen_or_being_tried_in_settings_draws_the_login_screen(self):
        for code in ("chosen_gpu", "trial_gpu"):
            with self.subTest(code=code):
                self.execute.reset_mock()
                self.query.return_value = response("card2", code, source=code.split("_")[0],
                                                  drm_devices=["/dev/dri/card2", "/dev/dri/card0"])
                greeter.main([])
                self.assert_weston("--drm-device=card2")
        # a chosen code without a card is not a valid answer
        self.assertIsNone(greeter.parse_selection(json.dumps({
            "schema": 1, "primary_card": None, "drm_devices": [], "reason": "x",
            "reason_code": "chosen_gpu"})))

    def test_late_driver_can_appear_after_the_boot_gpu(self):
        self.query.side_effect = [
            response(reason_code="no_usable_gpus"),
            response(reason_code="no_connected_monitors", drm_devices=["/dev/dri/card0"]),
            response("card1", "single_connected_gpu"),
        ]
        greeter.main([])
        self.assert_weston("--drm-device=card1")
        self.assertEqual(self.query.call_count, 3)
        self.assertLess(self.clock.now, 2.0)

    def test_no_ready_display_waits_at_most_two_seconds_then_uses_default(self):
        self.query.return_value = response(reason_code="no_connected_monitors",
                                          drm_devices=["/dev/dri/card0"])
        greeter.main([])
        self.assert_weston()
        self.assertLessEqual(self.clock.now, 2.0)
        self.assertLessEqual(self.query.call_count, 11)
        for call in self.query.call_args_list:
            self.assertGreater(call.kwargs["timeout"], 0)
            self.assertLessEqual(call.kwargs["timeout"], 1.0)

    def test_probe_timeout_is_clamped_to_remaining_boot_wait(self):
        def slow_probe(*args, **kwargs):
            self.clock.now += kwargs["timeout"]
            return response(reason_code="no_usable_gpus")

        self.query.side_effect = slow_probe
        greeter.main([])
        self.assert_weston()
        self.assertEqual(self.clock.now, 2.0)
        self.assertAlmostEqual(self.query.call_args.kwargs["timeout"], 0.8)

    def test_multiple_connected_gpus_preserve_weston_defaults_without_waiting(self):
        greeter.main([])
        self.assert_weston()
        self.query.assert_called_once()
        self.sleep.assert_not_called()

    def test_missing_core_uses_default_without_waiting(self):
        self.query.side_effect = FileNotFoundError("core is optional")
        greeter.main([])
        self.assert_weston()
        self.sleep.assert_not_called()

    def test_old_core_uses_default_without_waiting(self):
        self.query.return_value = SimpleNamespace(returncode=2, stdout=b"")
        greeter.main([])
        self.assert_weston()
        self.sleep.assert_not_called()

    def test_stuck_query_uses_default_without_retrying(self):
        self.query.side_effect = subprocess.TimeoutExpired(greeter.DISPLAY_QUERY, 1.0)
        greeter.main([])
        self.assert_weston()
        self.query.assert_called_once()
        self.sleep.assert_not_called()

    def test_malformed_json_uses_default(self):
        self.query.return_value = SimpleNamespace(returncode=0, stdout=b"not JSON\xff")
        greeter.main([])
        self.assert_weston()
        self.sleep.assert_not_called()

    def test_invalid_contract_or_device_never_reaches_weston(self):
        variants = [
            {"schema": True}, {"schema": 2}, {"reason": None}, {"reason_code": None},
            {"reason_code": "no_connected_monitors"}, {"reason_code": "unknown_future_choice"},
            {"primary_card": "card1 --help"}, {"primary_card": "../../card1"},
            {"primary_card": 1}, {"drm_devices": ["/dev/dri/card0"]},
            {"drm_devices": ["/tmp/card1"]}, {"drm_devices": [1]},
            {"drm_devices": "/dev/dri/card1"},
            {"drm_devices": ["/dev/dri/card1", "/dev/dri/card1"]},
        ]
        for changes in variants:
            with self.subTest(changes=changes):
                self.execute.reset_mock()
                self.query.return_value = response(
                    "card1", **{"reason_code": "single_connected_gpu", **changes})
                greeter.main([])
                self.assert_weston()
        self.sleep.assert_not_called()

    def test_missing_fields_and_non_objects_are_not_a_policy_response(self):
        for payload in (b"null", b"[]", b"1", b"{}", b'{"schema": 1}'):
            with self.subTest(payload=payload):
                self.assertIsNone(greeter.parse_selection(payload))

    def test_explicit_card_option_is_forwarded_without_policy(self):
        for args in (["--drm-device=card7"], ["--drm-device", "card7"]):
            with self.subTest(args=args):
                self.execute.reset_mock()
                greeter.main(args)
                self.assert_weston(*args)
        self.query.assert_not_called()

    def test_explicit_shell_is_preserved(self):
        greeter.main(["--shell=desktop", "--drm-device=card7"])
        self.execute.assert_called_once_with(
            "/usr/bin/weston", ["/usr/bin/weston", "--shell=desktop", "--drm-device=card7"])
        self.query.assert_not_called()

    def test_nondefault_seat_never_uses_seat_zero_policy(self):
        for args in (["--seat=seat1"], ["--seat", "seat1"], ["--seat"]):
            with self.subTest(args=args):
                self.execute.reset_mock()
                greeter.main(args)
                self.assert_weston(*args)
        os.environ["XDG_SEAT"] = "seat1"
        self.execute.reset_mock()
        greeter.main([])
        self.assert_weston()
        self.query.assert_not_called()

    def test_explicit_seat_zero_overrides_environment_for_policy_and_weston(self):
        os.environ["XDG_SEAT"] = "seat1"
        self.query.return_value = response("card1", "single_connected_gpu")
        greeter.main(["--seat=seat0"])
        self.assert_weston("--drm-device=card1", "--seat=seat0")
        self.assertEqual(self.query.call_args.kwargs["env"]["XDG_SEAT"], "seat0")
        self.assertEqual(os.environ["XDG_SEAT"], "seat1")


if __name__ == "__main__":
    unittest.main()
