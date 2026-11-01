"""bromigos-bar (desktop/bin/bromigos-bar) in a sandbox: the bar's user service where the
runtime directory has its own user manager, a plain Waybar where it hasn't. A stand-in
systemctl and waybar; nothing reaches a real session or user manager."""
import os
from pathlib import Path
import socket
import subprocess
import tempfile
import time
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


class Ready(unittest.TestCase):
    """`bromigos-bar ready`, the service's ExecCondition: a running Hyprland session, waited
    for while it comes up. At login Hyprland starts the bar before it writes its instance's
    hyprland.lock, which `bromigos session` reads: without the wait the condition skipped
    the bar on the live medium (and could on any slow start). A stand-in `bromigos session`
    finds the session from its Nth call on."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        self.run_dir = root / "run"
        self.run_dir.mkdir(mode=0o700)
        bins = root / "bin"
        bins.mkdir()
        self.count = root / "count"
        self.found_at = root / "found-at"
        (bins / "bromigos").write_text(
            "#!/bin/sh\n"
            f'n=$(( $(cat "{self.count}" 2>/dev/null || echo 0) + 1 )); echo $n > "{self.count}"\n'
            f'[ "$1" = session ] && [ -s "{self.found_at}" ] && [ $n -ge $(cat "{self.found_at}") ]\n')
        (bins / "bromigos").chmod(0o755)
        self.env = {"LANG": "C.UTF-8", "XDG_RUNTIME_DIR": str(self.run_dir), "HOME": str(root),
                    "PATH": f"{bins}:/usr/bin:/bin", "WAYLAND_DISPLAY": "wayland-1"}

    def socket(self):
        s = socket.socket(socket.AF_UNIX)
        s.bind(str(self.run_dir / "wayland-1"))
        self.addCleanup(s.close)

    def ready(self, found_at=None, **env):
        if found_at:
            self.found_at.write_text(str(found_at))
        return subprocess.run([str(BAR), "ready"], env=dict(self.env, **env), capture_output=True, text=True,
                              timeout=30)

    def calls(self):
        return int(self.count.read_text()) if self.count.exists() else 0

    def test_a_running_session_at_once(self):
        self.socket()
        r = self.ready(found_at=1)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.calls(), 1)
        self.assertEqual(r.stderr, "")

    def test_login_waits_for_the_session_to_be_found(self):
        # Hyprland's socket is there, its lock file not yet: found on the 5th look, ~1 s later
        self.socket()
        r = self.ready(found_at=5)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.calls(), 5)
        self.assertIn("came up after 1.0 s", r.stderr)

    def test_session_gone_is_skipped_at_once(self):
        # after the session: its socket is gone (or the manager has no display): exit 1, no wait
        r = self.ready()
        self.assertEqual(r.returncode, 1)
        self.assertEqual(self.calls(), 1)
        env = dict(self.env)
        del env["WAYLAND_DISPLAY"]
        r = subprocess.run([str(BAR), "ready"], env=env, capture_output=True, text=True, timeout=30)
        self.assertEqual(r.returncode, 1)

    def test_a_session_that_never_comes_gives_up(self):
        self.socket()
        start = time.monotonic()
        r = self.ready(BROMIGOS_SESSION_WAIT="1")
        self.assertEqual(r.returncode, 1)
        self.assertLess(time.monotonic() - start, 10)
        self.assertIn("after 1 s", r.stderr)

    def test_the_unit_waits_for_the_session(self):
        unit = (BAR.parents[1] / "systemd" / "bromigos-bar.service").read_text()
        self.assertIn("\nExecCondition=/usr/bin/bromigos-bar ready\n", unit)


if __name__ == "__main__":
    unittest.main()
