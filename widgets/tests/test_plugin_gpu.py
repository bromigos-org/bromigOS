"""plugins/gpu.py: AMD and Intel read from a made-up /sys/class/drm, process naming, and
the empty state when no GPU answers."""
import os
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "plugins"))
import gpu  # noqa: E402
import plugintest as PT  # noqa: E402


def write(root, rel, text):
    p = os.path.join(root, rel)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w") as f:
        f.write(text)


class Sysfs(unittest.TestCase):
    def test_amd(self):
        root = tempfile.mkdtemp()
        dev = "card1/device"
        write(root, f"{dev}/vendor", "0x1002\n")
        write(root, f"{dev}/product_name", "AMD Radeon RX 7900 XTX\n")
        write(root, f"{dev}/gpu_busy_percent", "63\n")
        write(root, f"{dev}/mem_info_vram_used", str(8 * 2 ** 30))
        write(root, f"{dev}/mem_info_vram_total", str(24 * 2 ** 30))
        write(root, f"{dev}/hwmon/hwmon4/temp1_input", "61000\n")
        write(root, f"{dev}/hwmon/hwmon4/power1_average", "212000000\n")
        write(root, f"{dev}/pp_dpm_sclk", "0: 500Mhz\n1: 2304Mhz *\n")
        write(root, "card1-DP-1/status", "connected\n")          # a connector, not a card
        r = gpu.SysfsReader(root)
        self.assertTrue(r.ok)
        g, = r.read()
        self.assertEqual((g["vendor"], g["name"], g["util"]), ("AMD", "Radeon RX 7900 XTX", 63))
        self.assertEqual((g["temp"], g["watts"], g["clock"]), (61.0, 212.0, 2304))
        self.assertEqual(g["vram_total"], 24 * 2 ** 30)
        self.assertIsNone(g["procs"])
        self.assertIn("process", g["note"])

    def test_intel_says_load_needs_intel_gpu_top(self):
        root = tempfile.mkdtemp()
        write(root, "card0/device/vendor", "0x8086\n")
        write(root, "card0/gt_cur_freq_mhz", "1300\n")
        g, = gpu.SysfsReader(root).read()
        self.assertIsNone(g["util"])
        self.assertEqual(g["clock"], 1300)
        self.assertIn("intel_gpu_top", g["note"])

    def test_nothing(self):
        self.assertFalse(gpu.SysfsReader(tempfile.mkdtemp()).ok)


class Procs(unittest.TestCase):
    def test_sorted_by_memory_and_named(self):
        rows = gpu.name_procs([{"pid": os.getpid(), "vram": 10, "kinds": {"compute"}},
                               {"pid": 2 ** 22 + 7, "vram": 900, "kinds": {"graphics"}}])
        self.assertEqual(rows[0]["vram"], 900)
        self.assertTrue(rows[0]["name"].startswith("pid "))          # gone: its pid instead
        self.assertEqual(rows[1]["kinds"], ["compute"])


class Panel(unittest.TestCase):
    def test_empty_state_names_what_it_tried(self):
        p = PT.make(gpu.GpuPanel)
        p.r, p.gpus = None, []
        tips = PT.draw(p, 460, 300)
        self.assertTrue(any("NVML" in t or "no graphics card" in t.lower() for t in tips))

    def test_every_size_class_draws_with_hints(self):
        p = PT.make(gpu.GpuPanel, demo=True)
        PT.every_class(self, p)


if __name__ == "__main__":
    unittest.main()
