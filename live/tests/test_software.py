"""No GPU (live/software.py): which renderers hold the layer still, and the one notification.

    cd live && python -m unittest discover -s tests

The live layer under a real software renderer, measured: tests/software_session.py.
"""
import os
import stat
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from live import software  # noqa: E402

# GL_RENDERER as Mesa and NVIDIA report it
LLVMPIPE = "llvmpipe (LLVM 19.1.7, 256 bits)"
NVIDIA = "NVIDIA GeForce RTX 5070/PCIe/SSE2"


class RendererTest(unittest.TestCase):
    def test_software_renderers(self):
        for r in (LLVMPIPE, "softpipe", "Mesa swrast", "Software Rasterizer", "LLVMPIPE"):
            self.assertTrue(software.is_software(r), r)
        for r in (NVIDIA, "AMD Radeon RX 7800 XT (radeonsi, navi32, LLVM 19.1.7)",
                  "Mesa Intel(R) Graphics (ADL GT2)", "virgl (NVIDIA GeForce RTX 5070)", "", None):
            self.assertFalse(software.is_software(r), r)

    def test_a_real_machine_without_its_gpu_is_held_still(self):
        """The 2026-10-09 update: the new driver couldn't start, GTK got llvmpipe."""
        held, why = software.limited(LLVMPIPE, allow=False, vm=False)
        self.assertTrue(held)
        self.assertIn("allow_software = true", why)

    def test_a_vm_is_held_too_and_the_setting_moves(self):
        held, why = software.limited(LLVMPIPE, allow=False, vm=True)
        self.assertTrue(held)
        self.assertIn("virtual machine", why)
        self.assertNotIn("driver update", why)
        self.assertEqual(software.limited(LLVMPIPE, allow=True, vm=False)[0], False)
        self.assertEqual(software.limited(LLVMPIPE, allow=True, vm=True)[0], False)
        self.assertEqual(software.limited(NVIDIA, allow=False, vm=False), (False, ""))


class NotifyTest(unittest.TestCase):
    def test_once_a_session(self):
        with tempfile.TemporaryDirectory() as d:
            bindir, run = os.path.join(d, "bin"), os.path.join(d, "run")
            os.makedirs(bindir)
            os.makedirs(run)
            log = os.path.join(d, "sent")
            exe = os.path.join(bindir, "notify-send")
            with open(exe, "w") as f:
                f.write(f'#!/bin/sh\necho "$*" >> {log}\n')
            os.chmod(exe, stat.S_IRWXU)
            old = os.environ["PATH"]
            os.environ["PATH"] = bindir + os.pathsep + old
            try:
                self.assertTrue(software.notify_once(run, LLVMPIPE))
                self.assertFalse(software.notify_once(run, LLVMPIPE), "the flag is there")
            finally:
                os.environ["PATH"] = old
            for _ in range(50):                     # the notification runs on its own
                if os.path.exists(log):
                    break
                import time
                time.sleep(0.05)
            with open(log) as f:
                sent = f.read().splitlines()
            self.assertEqual(len(sent), 1)
            self.assertIn("graphics card isn't available", sent[0])
            with open(os.path.join(run, software.FLAG)) as f:
                self.assertEqual(f.read().strip(), LLVMPIPE)


if __name__ == "__main__":
    unittest.main()
