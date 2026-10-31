"""Home's live readings and disk maps, from stand-in data: how busy the processor is, the
memory in use, each disk's partitions from lsblk, and the drives' own health verdicts (SMART),
asked once and kept."""
import json
import os
import shutil
import stat
import tempfile
import unittest

from bromigos_fieldkit import overview

STAT_0 = "cpu  100 0 100 700 100 0 0 0 0 0\ncpu0 50 0 50 350 50 0 0 0 0 0\n"
STAT_1 = "cpu  160 0 140 760 140 0 0 0 0 0\n"
MEMINFO = "MemTotal:        8000000 kB\nMemFree:          500000 kB\nMemAvailable:    2000000 kB\n"
LSBLK = {"blockdevices": [
    {"name": "nvme0n1", "path": "/dev/nvme0n1", "size": 1000, "type": "disk", "model": "Fast SSD ", "tran": "nvme",
     "children": [
         {"name": "nvme0n1p1", "path": "/dev/nvme0n1p1", "size": 10, "type": "part", "fstype": "vfat",
          "parttypename": "EFI System", "label": None},
         {"name": "nvme0n1p2", "path": "/dev/nvme0n1p2", "size": 600, "type": "part", "fstype": "crypto_LUKS",
          "parttypename": "Linux filesystem", "label": None,
          "children": [{"name": "bromigos-root", "type": "crypt", "size": 600}]},
         {"name": "nvme0n1p3", "path": "/dev/nvme0n1p3", "size": 300, "type": "part", "fstype": "BitLocker",
          "parttypename": "Microsoft basic data", "label": None}]},
    {"name": "zram0", "path": "/dev/zram0", "size": 4000, "type": "disk"},
    {"name": "sr0", "path": "/dev/sr0", "size": 900, "type": "rom"},
    {"name": "loop0", "path": "/dev/loop0", "size": 800, "type": "loop"},
]}


class Readings(unittest.TestCase):
    def test_processor_and_memory(self):
        b0, t0 = overview.cpu_times(STAT_0)
        b1, t1 = overview.cpu_times(STAT_1)
        self.assertEqual((b0, t0), (200, 1000))
        # 100 busy jiffies out of 200 between the two looks
        self.assertEqual(round(100 * (b1 - b0) / (t1 - t0)), 50)
        self.assertEqual(overview.cpu_times("nothing here"), (0, 0))
        self.assertEqual(overview.mem_pct(MEMINFO), 75.0)
        self.assertIsNone(overview.mem_pct("MemTotal: 0 kB\n"))

    def test_load_has_both_shares(self):
        doc = overview.load(gap=0)
        self.assertEqual(set(doc), {"cpu_pct", "mem_pct"})


class Disks(unittest.TestCase):
    def test_partitions_by_disk(self):
        disks = overview.disks_from(LSBLK)
        self.assertEqual([d["name"] for d in disks], ["nvme0n1"], "no RAM disk, optical drive or loop")
        d = disks[0]
        self.assertEqual((d["size"], d["model"], d["tran"]), (1000, "Fast SSD", "nvme"))
        self.assertEqual([p["fstype"] for p in d["parts"]], ["vfat", "crypto_LUKS", "BitLocker"])
        self.assertEqual(d["parts"][0]["parttypename"], "EFI System")
        self.assertEqual(d["parts"][0]["label"], "")
        self.assertEqual(sum(p["size"] for p in d["parts"]), 910)

    def test_health_reaches_what_is_found_on_the_disk(self):
        disks = overview.disks_from(LSBLK)
        items = [{"kind": "bromigos", "device": "/dev/nvme0n1p2"}, {"kind": "usb", "device": "/dev/sdz"}]
        overview.with_health(items, disks, {"/dev/nvme0n1": "failing"})
        self.assertEqual(items[0]["health"], "failing")
        self.assertNotIn("health", items[1])
        self.assertEqual(disks[0]["health"], "failing")


class Smart(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="fk-smart-")
        self.bin = os.path.join(self.tmp, "bin")
        os.makedirs(self.bin)
        self.log = os.path.join(self.tmp, "log")
        self.saved = (os.environ["PATH"], overview.SMART_CACHE)
        os.environ["PATH"] = self.bin + ":" + os.environ["PATH"]
        overview.SMART_CACHE = os.path.join(self.tmp, "smart.json")

    def tearDown(self):
        os.environ["PATH"], overview.SMART_CACHE = self.saved
        shutil.rmtree(self.tmp, ignore_errors=True)

    def stub(self, body):
        path = os.path.join(self.bin, "smartctl")
        with open(path, "w") as f:
            f.write(f'#!/bin/sh\necho "$*" >> "{self.log}"\n{body}\n')
        os.chmod(path, os.stat(path).st_mode | stat.S_IEXEC)

    def asked(self):
        try:
            with open(self.log) as f:
                return f.read().splitlines()
        except OSError:
            return []

    def test_verdicts(self):
        self.assertEqual(overview.smart_verdict('{"smart_status": {"passed": true}}'), "ok")
        self.assertEqual(overview.smart_verdict('{"smart_status": {"passed": false}}'), "failing")
        self.assertEqual(overview.smart_verdict('{"smartctl": {"exit_status": 2}}'), "")
        self.assertEqual(overview.smart_verdict("not json"), "")

    def test_asked_once_then_kept(self):
        self.stub('case "$3" in /dev/sda) echo \'{"smart_status":{"passed":true}}\' ;; *) echo \'{}\'; exit 2 ;; esac')
        got = overview.smart_health(["/dev/sda", "/dev/sdb"], now=1000)
        self.assertEqual(got, {"/dev/sda": "ok"}, "a disk without a report gets no badge")
        self.assertEqual(len(self.asked()), 2)
        self.assertEqual(overview.smart_health(["/dev/sda", "/dev/sdb"], now=1100), got)
        self.assertEqual(len(self.asked()), 2, "kept for ten minutes")
        overview.smart_health(["/dev/sda"], now=1000 + overview.SMART_TTL + 1)
        self.assertEqual(len(self.asked()), 3)
        with open(overview.SMART_CACHE) as f:
            self.assertIn("/dev/sda", json.load(f))

    def test_without_smartctl_nothing(self):
        os.environ["PATH"] = self.bin
        self.assertEqual(overview.smart_health(["/dev/sda"]), {})


if __name__ == "__main__":
    unittest.main()
