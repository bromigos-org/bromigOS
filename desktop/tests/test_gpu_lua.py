"""Startup GPU preferences with a stand-in hardware probe; never starts a desktop."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


MODULE = Path(__file__).resolve().parents[1] / 'hypr/bromigos/gpu.lua'


@unittest.skipUnless(shutil.which('lua'), 'needs Lua')
class GpuStartup(unittest.TestCase):
    def run_config(self, *, output='/dev/dri/card7:/dev/dri/card1\n', inherited='',
                   saved=None, disabled=False, success=True, unavailable=False,
                   reload=False, chosen='', chosen_success=True, report=False):
        with tempfile.TemporaryDirectory() as tmp:
            if saved is not None:
                hw = Path(tmp) / 'bromigos/hw'
                hw.mkdir(parents=True)
                (hw / 'hyprland.lua').write_text(saved)
            code = '''
local env = { XDG_STATE_HOME = %s, HOME = %s, AQ_DRM_DEVICES = %s }
os.getenv = function(key) return env[key] end
hl = { env = function(key, value) print("ENV\t" .. key .. "\t" .. value); env[key] = value end }
local count, chosen = 0, 0
io.popen = function(command)
    if command == "/usr/bin/timeout 2s /usr/bin/bromigos hw display --hyprland-chosen 2>/dev/null" then
        chosen = chosen + 1
        if %s then return nil end
        return { read = function() return %s end, close = function() return %s end }
    end
    count = count + 1
    assert(command == "/usr/bin/timeout 2s /usr/bin/bromigos hw display --hyprland 2>/dev/null")
    if %s then return nil end
    return { read = function() return %s end, close = function() return %s end }
end
local B = { hw = %s }
local gpu = dofile(%s)
gpu.apply(B)
if %s then gpu.apply(B) end
print("PROBES\t" .. count)
if %s then
    print("CHOSEN\t" .. chosen)
    for _, cmd in ipairs(B.autostart or {}) do print("AUTOSTART\t" .. cmd) end
end
''' % (json.dumps(tmp), json.dumps(tmp), json.dumps(inherited),
       str(unavailable).lower(), json.dumps(chosen), str(chosen_success).lower(),
       str(unavailable).lower(), json.dumps(output), str(success).lower(),
       'nil' if not disabled else 'false', json.dumps(str(MODULE)), str(reload).lower(),
       str(report).lower())
            result = subprocess.run(['lua', '-'], input=code, text=True, capture_output=True,
                                    env={'HOME': tmp, 'PATH': os.environ['PATH']}, timeout=5)
            self.assertEqual(result.returncode, 0, result.stderr)
            return result.stdout.splitlines()

    def test_connected_card_first_and_other_outputs_retained(self):
        self.assertEqual(self.run_config(), [
            'ENV\tAQ_DRM_DEVICES\t/dev/dri/card7:/dev/dri/card1', 'PROBES\t1'])

    def test_explicit_environment_wins_over_saved_and_automatic(self):
        rows = self.run_config(inherited='/dev/dri/user-gpu',
                               saved='return { env = {{ "AQ_DRM_DEVICES", "/dev/dri/saved" }} }')
        self.assertEqual(rows, ['PROBES\t0'])

    def test_saved_preference_wins_and_other_environment_is_applied(self):
        rows = self.run_config(saved='return { env = {{ "AQ_DRM_DEVICES", "/dev/dri/saved" }, { "OTHER", "value" }} }')
        self.assertEqual(rows, ['ENV\tAQ_DRM_DEVICES\t/dev/dri/saved', 'ENV\tOTHER\tvalue', 'PROBES\t0'])

    def test_missing_saved_device_allows_new_hardware_selection(self):
        rows = self.run_config(saved='return { env = {{ "AQ_DRM_DEVICES", "/dev/dri/old", when = { "/nonexistent-gpu-test-node" } }} }')
        self.assertIn('ENV\tAQ_DRM_DEVICES\t/dev/dri/card7:/dev/dri/card1', rows)

    def test_opt_out_skips_saved_and_probe(self):
        self.assertEqual(self.run_config(disabled=True, saved='error("must not load")'), ['PROBES\t0'])

    def test_no_probe_on_config_reload_even_without_initial_choice(self):
        self.assertEqual(self.run_config(output='', reload=True), ['PROBES\t1'])

    def test_unavailable_or_failed_probe_keeps_native_choice(self):
        self.assertEqual(self.run_config(unavailable=True), ['PROBES\t1'])
        self.assertEqual(self.run_config(success=False), ['PROBES\t1'])

    def test_a_card_chosen_in_settings_wins_over_saved_and_automatic(self):
        rows = self.run_config(chosen='chosen /dev/dri/card2:/dev/dri/card0\n', report=True,
                               saved='return { env = {{ "AQ_DRM_DEVICES", "/dev/dri/saved" }, { "OTHER", "value" }} }')
        self.assertEqual(rows, ['ENV\tAQ_DRM_DEVICES\t/dev/dri/card2:/dev/dri/card0', 'ENV\tOTHER\tvalue',
                                'PROBES\t0', 'CHOSEN\t1'])

    def test_a_card_being_tried_asks_to_be_kept_after_login(self):
        rows = self.run_config(chosen='trial /dev/dri/card2:/dev/dri/card0\n', report=True)
        self.assertEqual(rows, ['ENV\tAQ_DRM_DEVICES\t/dev/dri/card2:/dev/dri/card0', 'PROBES\t0', 'CHOSEN\t1',
                                "AUTOSTART\tsh -c 'sleep 3; exec bromigos settings graphics#trial'"])

    def test_no_chosen_card_or_an_old_probe_falls_through(self):
        for chosen, ok in [('', True), ('trial /dev/dri/card2', False), ('later /dev/dri/card2', True),
                           ('chosen /dev/dri/card2;reboot', True), ('chosen', True)]:
            with self.subTest(chosen=chosen):
                rows = self.run_config(chosen=chosen, chosen_success=ok, report=True)
                self.assertEqual(rows, ['ENV\tAQ_DRM_DEVICES\t/dev/dri/card7:/dev/dri/card1', 'PROBES\t1',
                                        'CHOSEN\t1'])

    def test_inherited_environment_skips_the_chosen_probe_too(self):
        rows = self.run_config(inherited='/dev/dri/user-gpu', chosen='chosen /dev/dri/card2', report=True)
        self.assertEqual(rows, ['PROBES\t0', 'CHOSEN\t0'])

    def test_unclear_or_malformed_result_does_not_set_environment(self):
        for output in ['', 'old CLI help', '/dev/dri/card0:', '/dev/dri/card0::/dev/dri/card1',
                       '/dev/dri/card0:/dev/dri/card0', '/dev/dri/card1\n/dev/dri/card2',
                       '/dev/dri/card0;echo broken', '/dev/dri/renderD128']:
            with self.subTest(output=output):
                self.assertEqual(self.run_config(output=output), ['PROBES\t1'])


if __name__ == '__main__':
    unittest.main()
