"""bromigos-bar (desktop/bin/bromigos-bar) in a sandbox: the bar's user service where the
runtime directory has its own user manager, a plain Waybar where it hasn't. A stand-in
systemctl and waybar; nothing reaches a real session or user manager."""
import os
from pathlib import Path
import socket
import subprocess
import tempfile
import unittest

BAR = Path(__file__).resolve().parents[1] / "bin" / "bromigos-bar"


class Bar(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        self.run_dir = root / "run"
        self.run_dir.mkdir(mode=0o700)
        bins = root / "bin"
        bins.mkdir()
        self.log = root / "calls"
        for name, body in {
            "systemctl": f'echo "systemctl $*" >> "{self.log}"\n'
                         'case "$*" in *"show -p LoadState"*) echo loaded ;; *is-active*) echo active ;; esac',
            "waybar": f'echo "waybar $*" >> "{self.log}"',
            "hyprctl": f'echo "hyprctl $*" >> "{self.log}"; echo ok',
        }.items():
            p = bins / name
            p.write_text("#!/bin/sh\n" + body + "\n")
            p.chmod(0o755)
        # nothing of the session this runs in (its display, bus or Hyprland)
        self.env = {"LANG": "C.UTF-8"}
        self.env.update(XDG_RUNTIME_DIR=str(self.run_dir), HOME=str(root), PATH=f"{bins}:/usr/bin:/bin",
                        WAYLAND_DISPLAY="wayland-test")

    def bar(self, *args, **env):
        return subprocess.run([str(BAR), *args], env=dict(self.env, **env), capture_output=True, text=True,
                              timeout=30)

    def calls(self):
        return self.log.read_text().splitlines() if self.log.exists() else []

    def manager(self):
        (self.run_dir / "systemd").mkdir()
        s = socket.socket(socket.AF_UNIX)
        s.bind(str(self.run_dir / "systemd" / "private"))
        self.addCleanup(s.close)

    def test_start_is_the_service_with_the_session_imported(self):
        self.manager()
        r = self.bar("start", HYPRLAND_INSTANCE_SIGNATURE="sig")
        self.assertEqual(r.returncode, 0, r.stderr)
        c = self.calls()
        self.assertIn("systemctl --user import-environment WAYLAND_DISPLAY HYPRLAND_INSTANCE_SIGNATURE", c)
        self.assertIn("systemctl --user start bromigos-bar.service", c)
        self.assertFalse([x for x in c if x.startswith("waybar")], c)

    def test_restart_and_stop_are_the_service(self):
        self.manager()
        self.assertEqual(self.bar("restart").returncode, 0)
        self.assertEqual(self.bar("stop").returncode, 0)
        c = self.calls()
        self.assertIn("systemctl --user restart bromigos-bar.service", c)
        self.assertIn("systemctl --user stop bromigos-bar.service", c)

    def test_no_manager_of_its_own_a_plain_waybar(self):
        # a borrowed bus (a nested desktop's) must never reach another manager
        r = self.bar("start", DBUS_SESSION_BUS_ADDRESS="unix:path=/nonexistent")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.calls(), ["waybar "])

    def test_no_units_asked_for(self):
        self.manager()
        self.bar("start", BROMIGOS_NO_UNITS="1")
        self.assertEqual(self.calls(), ["waybar "])

    def test_restart_without_service_goes_through_the_compositor(self):
        r = self.bar("restart", HYPRLAND_INSTANCE_SIGNATURE="sig")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn('hyprctl dispatch hl.dsp.exec_cmd("waybar")', self.calls())

    def test_status_says_it(self):
        self.manager()
        r = self.bar("status", "--json")
        self.assertEqual(r.returncode, 0, r.stdout)
        self.assertIn('"how":"service"', r.stdout)


if __name__ == "__main__":
    unittest.main()
