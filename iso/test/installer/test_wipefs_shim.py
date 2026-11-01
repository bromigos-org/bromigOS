"""The installer's wipefs shim (shims/wipefs, first on archinstall's PATH): it waits for a
partition udev is still making and tries a probe that failed that way again, so "Preparing
the disk" no longer fails on the race. A stand-in wipefs and udevadm; nothing on this machine
is wiped."""
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

SHIM = Path(__file__).resolve().parents[2] / "profile/airootfs/usr/local/lib/bromigos-iso/shims/wipefs"


class Shim(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        t = Path(self.tmp.name)
        self.bin, self.log, self.calls = t / "bin", t / "install.log", t / "calls"
        self.bin.mkdir()
        (self.bin / "udevadm").write_text("#!/bin/sh\nexit 0\n")
        # the real wipefs, stood in: fails the first FAILS calls the way the race does
        self.real = t / "wipefs"
        self.real.write_text(f'#!/bin/sh\necho "$*" >> {self.calls}\nn=$(wc -l < {self.calls})\n'
                             'if [ "$n" -le "${FAILS:-0}" ]; then\n'
                             '  echo "wipefs: error: $2: probing initialization failed: No such file or directory" >&2; exit 1\nfi\n'
                             'echo "/dev/vda1: 8 bytes were erased"\n')
        for p in (self.bin / "udevadm", self.real):
            p.chmod(0o755)

    def tearDown(self):
        self.tmp.cleanup()

    def run_shim(self, fails, *args):
        env = dict(os.environ, PATH=f"{self.bin}:/usr/bin:/bin", BROMIGOS_WIPEFS=str(self.real),
                   BROMIGOS_WIPEFS_LOG=str(self.log), BROMIGOS_WIPEFS_WAIT="3", FAILS=str(fails))
        return subprocess.run(["bash", str(SHIM), *args], env=env, capture_output=True, text=True)

    def test_a_probe_that_races_udev_is_tried_again(self):
        r = self.run_shim(1, "--all", "/dev/nonexistent-partition1")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("8 bytes were erased", r.stdout)
        self.assertEqual(self.calls.read_text().count("--all"), 2)
        log = self.log.read_text()
        self.assertIn("waited 300 ms for /dev/nonexistent-partition1", log)
        self.assertIn("try 1: wipefs: error", log)

    def test_three_failures_are_wipefs_own(self):
        r = self.run_shim(5, "--all", "/dev/nonexistent-partition1")
        self.assertEqual(r.returncode, 1)
        self.assertIn("probing initialization failed", r.stderr)
        self.assertEqual(self.calls.read_text().count("--all"), 3)

    def test_anything_else_is_wipefs_as_it_is(self):
        r = self.run_shim(0, "--version")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.calls.read_text(), "--version\n")
        self.assertFalse(self.log.exists(), "no device: nothing waited for")


if __name__ == "__main__":
    unittest.main()
