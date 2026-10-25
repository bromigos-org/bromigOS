"""The new box's hardware check: fixture outputs and fake /sys trees stand in for real boxes."""
import ast
import contextlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

from bromigos_homelab import hardware as H, provision as P, services as S

os.environ["BROMIGOS_LAB_PROFILES"] = str(Path(__file__).resolve().parents[1] / "share/lab/profiles.toml")
FIXTURES = Path(__file__).parent / "fixtures/hardware"
TARGET = {"kind": "ssh", "ssh": "tester@lab.example.org", "port": 22, "identity": ""}


def fixture(name):
    return (FIXTURES / name).read_text()


def tree(root, files, links=()):
    """A fake machine: {relative path: text} files, (link, target) symlinks, and None for empty folders."""
    for name, text in files.items():
        path = Path(root, name)
        if text is None:
            path.mkdir(parents=True, exist_ok=True)
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text)
    for link, target in links:
        Path(root, link).parent.mkdir(parents=True, exist_ok=True)
        os.symlink(target, Path(root, link))


def pci(slot, cls, vendor, device):
    base = f"sys/bus/pci/devices/{slot}/"
    return {base + "class": f"0x{cls}\n", base + "vendor": f"0x{vendor}\n", base + "device": f"0x{device}\n"}


def nic(name, speed=None, state="up", wireless=False):
    base = f"sys/class/net/{name}/"
    files = {base + "device": None, base + "operstate": state + "\n"}
    if speed is not None:
        files[base + "speed"] = speed + "\n"
    if wireless:
        files[base + "wireless"] = None
    return files


def gpu_box(root):
    files = {**pci("0000:01:00.0", "030000", "10de", "2204"), **pci("0000:21:00.0", "030000", "10de", "2204"),
             **pci("0000:00:00.0", "060000", "1022", "1480"),
             **nic("enp5s0", "2500"), **nic("wlp6s0", state="down", wireless=True), "sys/class/net/docker0/operstate": "up\n",
             "proc/cpuinfo": "processor\t: 0\nmodel name\t: AMD Ryzen 9 5950X 16-Core Processor\nflags\t\t: fpu sse svm\n",
             "dev/kvm": "",
             "proc/mounts": "/dev/nvme0n1p2 / ext4 rw 0 0\nproc /proc proc rw 0 0\n/dev/nvme0n1p1 /boot/efi vfat rw 0 0\n"
                            "/dev/sdb1 /srv/data ext4 rw 0 0\nnas.example.org:/volume1/backups /mnt/nas nfs4 rw 0 0\n",
             "srv/data": None, "mnt/nas": None, "boot/efi": None,
             "sys/bus/usb/devices/usb1/idVendor": "1d6b\n", "sys/bus/usb/devices/usb1/idProduct": "0002\n",
             "sys/bus/usb/devices/1-2/idVendor": "1a6e\n", "sys/bus/usb/devices/1-2/idProduct": "089a\n",
             "sys/bus/usb/devices/1-3/idVendor": "10c4\n", "sys/bus/usb/devices/1-3/idProduct": "ea60\n",
             "sys/bus/usb/devices/1-3/product": "Sonoff Zigbee 3.0 USB Dongle Plus\n", "sys/bus/usb/devices/1-3/manufacturer": "ITead\n",
             "sys/class/dmi/id/chassis_type": "3\n"}
    links = [("sys/bus/pci/devices/0000:01:00.0/driver", "../../../bus/pci/drivers/nvidia"),
             ("sys/bus/pci/devices/0000:21:00.0/driver", "../../../bus/pci/drivers/nvidia")]
    tree(root, files, links)
    outputs = {"lspci": fixture("gpu-box.lspci.txt"), "nvidia-smi": fixture("gpu-box.nvidia-smi.csv"),
               "lsblk": fixture("gpu-box.lsblk.json")}
    return H.collect(root, run=lambda argv: outputs.get(argv[0]))


def laptop_raw():
    return {"pci": [{"slot": "0000:00:02.0", "class": "0300", "vendor": "8086", "device": "46a6", "driver": "i915"},
                    {"slot": "0000:01:00.0", "class": "0302", "vendor": "10de", "device": "25a2", "driver": "nouveau"}],
            "lspci": fixture("laptop.lspci.txt"), "nvidia_smi": None, "drm_vram": {}, "lsblk": fixture("laptop.lsblk.json"),
            "mounts": [{"source": "/dev/nvme0n1p2", "mount": "/", "fstype": "btrfs", "total": 5e11, "free": 3e11},
                       {"source": "/dev/nvme0n1p2", "mount": "/home", "fstype": "btrfs", "total": 5e11, "free": 3e11},
                       {"source": "/dev/nvme0n1p1", "mount": "/boot", "fstype": "vfat"}],
            "net": [{"name": "enp0s31f6", "wireless": False, "speed": None, "operstate": "down", "carrier": "0"},
                    {"name": "wlp0s20f3", "wireless": True, "speed": None, "operstate": "up", "carrier": "1"}],
            "cpu": {"model": "12th Gen Intel(R) Core(TM) i7-1260P", "flags": ["vmx"], "kvm": True},
            "chassis": "10", "battery": True,
            "usb": [{"id": "5986:1177", "product": "Integrated Camera", "manufacturer": "Bison", "classes": ["0e"]}], "lsusb": None}


def server_raw():
    return {"pci": [{"slot": "0000:03:00.0", "class": "0300", "vendor": "1a03", "device": "2000", "driver": "ast"}],
            "lspci": fixture("server.lspci.txt"), "nvidia_smi": None, "lsblk": fixture("server-old.lsblk.json"),
            "mounts": [{"source": "/dev/sda1", "mount": "/", "fstype": "ext4", "total": 2.4e11, "free": 2e11},
                       {"source": "/dev/md0", "mount": "/srv/backup", "fstype": "ext4", "total": 4e12, "free": 3.5e12}],
            "net": [{"name": "eno1", "wireless": False, "speed": "100", "operstate": "up", "carrier": "1"},
                    {"name": "eno2", "wireless": False, "speed": "-1", "operstate": "down", "carrier": "0"}],
            "cpu": {"model": "Intel(R) Xeon(R) CPU E5-2650 v4 @ 2.20GHz", "flags": ["vmx"], "kvm": False},
            "chassis": "17", "battery": False, "usb": [], "lsusb": "Bus 001 Device 001: ID 1d6b:0002 Linux Foundation 2.0 root hub\n"
            "Bus 001 Device 003: ID 0658:0200 Sigma Designs, Inc. Aeotec Z-Stick Gen5 (ZW090) - UZB\n"}


def facts(hw, **extra):
    return {**dict(cpu=16, ram_gib=64, disk_gib=400, distribution="debian", architecture="x86_64", gpu="none", vram_gib=0, hardware=hw), **extra}


class CollectTests(unittest.TestCase):
    def test_gpu_box_with_every_tool(self):
        with tempfile.TemporaryDirectory() as root:
            raw = gpu_box(root)
        hw = H.parse(raw)
        lines = H.describe(facts(hw))
        self.assertIn("GPU: 2 × NVIDIA GeForce RTX 3090, 24 GB each, driver loaded", lines)
        self.assertIn("CPU: AMD Ryzen 9 5950X 16-Core Processor, virtualisation available (AMD-V)", lines)
        self.assertIn("System disk: 1 TB NVMe (Samsung SSD 980 1TB)", lines)
        self.assertIn("Spare disk: 4 TB HDD (WDC WD40EFRX-68N32N0), empty, not mounted", lines)
        self.assertIn("Disk: 2 TB SSD (Samsung SSD 870 EVO 2TB), mounted at /srv/data", lines)
        self.assertTrue(any(line.startswith("NAS share: /mnt/nas (nfs4)") for line in lines))
        self.assertIn("Wired network: enp5s0, 2.5 Gb/s, connected", lines)
        self.assertIn("Wi-Fi: wlp6s0, not connected", lines)
        self.assertIn("USB: Coral Edge TPU. Could be used for fast object detection in Frigate", lines)
        self.assertIn("USB: ITead Sonoff Zigbee 3.0 USB Dongle Plus. Could be used for Zigbee devices in Home Assistant", lines)
        self.assertFalse(any("docker0" in line or "zram" in line or "Laptop" in line for line in lines))
        # The removable USB stick is listed, but never suggested for backups.
        self.assertTrue(any("32 GB USB HDD" in line for line in lines))
        self.assertEqual(H.legacy(hw), ("nvidia", 48.0))

    def test_no_tools_falls_back_to_sys(self):
        files = {**pci("0000:00:02.0", "030000", "8086", "a780"),
                 "usr/share/hwdata/pci.ids": "# test excerpt\n8086  Intel Corporation\n\t0100  2nd Generation Core\n"
                                             "\ta780  Raptor Lake-S GT1 [UHD Graphics 770]\n\t\t1043 8882  subsystem\n10de  NVIDIA Corporation\n",
                 "sys/block/nvme0n1/size": str(1000204886016 // 512), "sys/block/nvme0n1/queue/rotational": "0",
                 "sys/block/nvme0n1/removable": "0", "sys/block/nvme0n1/nvme0n1p1": None, "sys/block/nvme0n1/holders": None,
                 "sys/block/sda/size": str(4000787030016 // 512), "sys/block/sda/queue/rotational": "1",
                 "sys/block/sda/removable": "0", "sys/block/sda/device/model": "ST4000DM004-2CV1\n", "sys/block/sda/holders": None,
                 "sys/block/loop0/size": "0",
                 "proc/mounts": "/dev/nvme0n1p1 / ext4 rw 0 0\n", **nic("eth0", "1000"),
                 "proc/cpuinfo": "processor\t: 0\nflags\t: fpu\n"}
        with tempfile.TemporaryDirectory() as root:
            tree(root, files, [("sys/bus/pci/devices/0000:00:02.0/driver", "../../../bus/pci/drivers/i915")])
            ran = []
            raw = H.collect(root, run=lambda argv: ran.append(argv[0]))
        self.assertEqual(set(ran), {"lspci", "nvidia-smi", "lsblk", "lscpu", "lsusb"})  # read-only tools, nothing else
        self.assertEqual(raw["pci_names"], {"8086": "Intel Corporation", "8086:a780": "Raptor Lake-S GT1 [UHD Graphics 770]"})
        lines = H.describe(facts(H.parse(raw)))
        self.assertIn("GPU: Intel UHD Graphics 770, driver loaded", lines)
        self.assertIn("System disk: 1 TB NVMe", lines)
        self.assertIn("Disk: 4 TB HDD (ST4000DM004-2CV1), not mounted; lsblk is missing, so its contents are unknown", lines)
        self.assertFalse(any(line.startswith("Spare disk") for line in lines))
        self.assertIn("Wired network: eth0, 1 Gb/s, connected", lines)
        self.assertTrue(any(line.startswith("CPU: virtualisation not available") for line in lines))

    def test_collector_runs_on_old_python_and_is_read_only(self):
        tree_source = H.SOURCE
        ast.parse(tree_source, feature_version=(3, 6))
        for word in ("write(", "unlink", "remove(", "rmdir", "chmod", "mkdir", "makedirs", '"w"', '"a"', "shell=True"):
            self.assertNotIn(word, tree_source)


class ParseTests(unittest.TestCase):
    def test_laptop_on_wifi_with_nouveau(self):
        hw = H.parse(laptop_raw())
        lines = H.describe(facts(hw))
        self.assertIn("Machine: a laptop. Keep it plugged in, and set it to stay on with the lid closed", lines)
        self.assertIn("GPU: Intel Iris Xe Graphics, driver loaded", lines)
        self.assertIn("GPU: NVIDIA GeForce RTX 3050 Mobile, open-source nouveau driver; AI services need NVIDIA's driver", lines)
        self.assertIn("CPU: 12th Gen Intel Core i7-1260P, virtualisation available (VT-x)", lines)
        self.assertIn("System disk: 512 GB NVMe (SAMSUNG MZVL2512HCJQ-00BL7)", lines)
        self.assertIn("Wired network: enp0s31f6, not connected", lines)
        self.assertIn("Wi-Fi: wlp0s20f3, connected", lines)
        self.assertIn("USB: Bison Integrated Camera. Could be used for a camera feed in Frigate or Home Assistant", lines)
        self.assertEqual(H.legacy(hw), ("none", 0))
        self.assertEqual(hw["backup_places"], [])
        self.assertIn("Only Wi-Fi is connected. A network cable is steadier for a server", H.notes(facts(hw), [], S.load()))

    def test_server_without_gpu_old_lsblk_and_raid(self):
        hw = H.parse(server_raw())
        lines = H.describe(facts(hw))
        self.assertIn("GPU: none found", lines)
        self.assertIn("System disk: 240 GB SSD (INTEL SSDSC2KB240G8)", lines)
        self.assertEqual(lines.count("Disk: 4 TB HDD (ST4000NM0035-1V4), part of a RAID array"), 2)
        self.assertFalse(any("DVD" in line for line in lines))
        self.assertIn("Wired network: eno1, 100 Mb/s, connected", lines)
        self.assertIn("CPU: Intel Xeon CPU E5-2650 v4 @ 2.20GHz, virtualisation supported (VT-x), but /dev/kvm is missing", lines)
        self.assertIn("USB: Sigma Designs, Inc. Aeotec Z-Stick Gen5 (ZW090) - UZB. Could be used for Z-Wave devices in Home Assistant", lines)
        self.assertEqual([p["path"] for p in hw["backup_places"]], ["/srv/backup"])
        notes = H.notes(facts(hw), ["restic"], S.load(), "/srv/backup/lab")
        self.assertEqual(notes, ["The wired link runs at 100 Mb/s. Check the cable and switch port; backups will be slow"])

    def test_multiple_vendors_and_amd_memory(self):
        raw = {"pci": [{"slot": "0000:0b:00.0", "class": "0300", "vendor": "1002", "device": "73bf", "driver": "amdgpu"},
                       {"slot": "0000:0c:00.0", "class": "0300", "vendor": "10de", "device": "2204", "driver": "vfio-pci"}],
               "lspci": '0000:0b:00.0 "VGA compatible controller [0300]" "Advanced Micro Devices, Inc. [AMD/ATI] [1002]" '
                        '"Navi 21 [Radeon RX 6800/6800 XT / 6900 XT] [73bf]" -rc1 "XFX [1682]" "Device [6801]"\n',
               "drm_vram": {"0000:0b:00.0": 16 * 2**30}}
        hw = H.parse(raw)
        lines = H.describe(facts(hw))
        self.assertIn("GPU: AMD Radeon RX 6800/6800 XT / 6900 XT, 16 GB, driver loaded", lines)
        self.assertIn("GPU: NVIDIA graphics (device 2204), reserved for virtual machines (vfio-pci)", lines)
        self.assertEqual(H.legacy(hw), ("amd", 16.0))

    def test_parsers_tolerate_junk(self):
        self.assertEqual(H.parse_lspci('broken "line\n\n'), {})
        self.assertEqual(H.parse_nvidia_smi("No devices were found\n"), {})
        self.assertEqual(H.disks({"lsblk": "not json"}), [])
        seed = {"name": "vdb", "size": 374784, "type": "disk", "rota": True, "fstype": "iso9660", "mountpoints": [None]}
        self.assertEqual(H.disks({"lsblk": json.dumps({"blockdevices": [seed]})}), [])
        self.assertIsNone(H.parse(None))
        self.assertEqual(H.size(4000787030016), "4 TB")
        self.assertEqual(H.size(1500000000000), "1.5 TB")
        self.assertEqual(H.speed_text(10000), "10 Gb/s")


class PlanTextTests(unittest.TestCase):
    def setUp(self):
        with tempfile.TemporaryDirectory() as root:
            self.gpu = H.parse(gpu_box(root))

    def test_gpu_service_without_a_working_gpu_warns(self):
        cat = {"service": {"comfy": {"title": "ComfyUI", "needs": {"gpu": "nvidia"}}}}
        laptop = H.parse(laptop_raw())
        self.assertEqual(H.notes(facts(laptop), ["comfy"], cat)[0],
                         "ComfyUI needs a GPU. The NVIDIA GeForce RTX 3050 Mobile has no working driver "
                         "(open-source nouveau driver; AI services need NVIDIA's driver). Set up its driver on the box first")
        self.assertEqual(H.notes(facts(H.parse(server_raw())), ["comfy"], cat)[0], "ComfyUI needs a GPU, and none was found")
        self.assertFalse(any("ComfyUI" in n for n in H.notes(facts(self.gpu), ["comfy"], cat)))
        amd = {"service": {"vllm": {"title": "vLLM", "needs": {"gpu": "nvidia"}}}}
        only_amd = {"gpus": [{"vendor": "AMD", "model": "Radeon RX 6800", "ready": True, "state": "driver loaded", "vram_gib": 16}]}
        self.assertEqual(H.notes(facts(only_amd), ["vllm"], amd), ["vLLM needs an NVIDIA GPU with a working driver; this box has none"])

    def test_backups_on_the_system_disk_suggest_other_places(self):
        notes = H.notes(facts(self.gpu), ["restic"], S.load(), "/var/backups/lab")
        self.assertEqual(notes[0], "Backups go to /var/backups/lab, on the system disk. If that disk fails, the backups go with it")
        self.assertEqual(sorted(n.split(" with ")[0] for n in notes[1:3]),
                         ["Suggestion: /mnt/nas is a NAS share", "Suggestion: /srv/data is a disk"])
        self.assertEqual(notes[3], "Suggestion: the empty 4 TB HDD (sda) could hold backups once you format and mount it. "
                                   "Provisioning never formats or mounts disks")
        self.assertEqual(len(notes), 4)
        self.assertFalse(any("system disk" in n for n in H.notes(facts(self.gpu), ["restic"], S.load(), "/mnt/nas/lab")))
        self.assertFalse(any("Suggestion" in n for n in H.notes(facts(self.gpu), ["caddy"], S.load(), "")))

    def test_plan_summary_prints_hardware_and_notes(self):
        cat = S.load()
        box = facts(self.gpu, gpu="nvidia", vram_gib=48)
        resolved = P.selection(cat, P.preset_selection(cat, "core"), box)
        with contextlib.redirect_stdout(io.StringIO()) as out:
            P.summary(cat, resolved, box, "/tmp/lab", backup_path="/var/backups/lab")
        text = out.getvalue()
        self.assertIn("Hardware:\n  Box: Debian, x86-64, 16 CPU threads, 64 GB memory, 429 GB free on the system disk\n", text)
        self.assertIn("  GPU: 2 × NVIDIA GeForce RTX 3090, 24 GB each, driver loaded\n", text)
        self.assertIn("  Spare disk: 4 TB HDD (WDC WD40EFRX-68N32N0), empty, not mounted\n", text)
        self.assertIn("Note: Backups go to /var/backups/lab, on the system disk.", text)
        self.assertLess(text.index("Hardware:"), text.index("Model downloads"))

    def test_inventory_sends_the_collector_and_parses_its_answer(self):
        laptop = laptop_raw()
        answer = json.dumps(dict(cpu=12, ram_gib=16, disk_gib=200, distribution="ubuntu", architecture="x86_64", gpu="none", vram_gib=0,
                                 hardware_raw=laptop))
        with mock.patch.object(P, "run", side_effect=["", answer]) as run:
            result = P.inventory(TARGET)
        probe = run.call_args_list[1].args[1]
        self.assertIn("def collect(", probe)
        compile(probe, "probe", "exec")
        self.assertNotIn("hardware_raw", result)
        self.assertEqual(result["hardware"]["gpus"][1]["driver"], "nouveau")
        self.assertEqual(result["gpu"], "none")
        broken = json.dumps(dict(cpu=2, ram_gib=4, disk_gib=20, distribution="debian", gpu="none", vram_gib=0, hardware_raw=None))
        with mock.patch.object(P, "run", side_effect=["", broken]):
            self.assertNotIn("hardware", P.inventory(TARGET))

    def test_whole_probe_runs_and_prints_json(self):
        # The real probe, run by this Python on this machine: it only reads, and must print facts.
        with mock.patch.object(P, "run", side_effect=["", "{}"]) as run, self.assertRaises(KeyError):
            P.inventory(TARGET)
        probe = run.call_args_list[1].args[1]
        result = subprocess.run([sys.executable, "-I", "-"], input=probe, text=True, capture_output=True, timeout=120)
        self.assertEqual(result.returncode, 0, result.stderr[-500:])
        doc = json.loads(result.stdout)
        self.assertIn("hardware_raw", doc)
        self.assertIsNotNone(H.parse(doc["hardware_raw"]))


class ClusterTests(unittest.TestCase):
    def test_gpus_from_node_labels(self):
        nodes = [{"metadata": {"name": "gpu-1", "labels": {"nvidia.com/gpu.product": "NVIDIA-GeForce-RTX-3090", "nvidia.com/gpu.memory": "24576"}},
                  "status": {"allocatable": {"cpu": "16", "memory": "64Gi", "nvidia.com/gpu": "2"}}},
                 {"metadata": {"name": "gpu-2", "labels": {"feature.node.kubernetes.io/pci-0300_10de.present": "true"}},
                  "status": {"allocatable": {"cpu": "8", "memory": "32Gi"}}},
                 {"metadata": {"name": "small", "labels": {"feature.node.kubernetes.io/pci-0300_8086.present": "true"}},
                  "status": {"allocatable": {"cpu": "4", "memory": "8Gi"}}},
                 {"metadata": {"name": "plain", "labels": {}}, "status": {"allocatable": {"cpu": "4", "memory": "8Gi"}}}]
        lines = H.describe({"distribution": "cluster", "hardware": H.from_nodes(nodes)})
        self.assertEqual(lines, ["GPU: 2 × NVIDIA GeForce RTX 3090 on node gpu-1, 24 GB each, usable by the cluster",
                                 "GPU: NVIDIA GPU on node gpu-2, found, but the cluster can't use it yet (no device plugin)",
                                 "GPU: Intel GPU on node small, found, but the cluster can't use it yet (no device plugin)"])
        self.assertEqual(H.describe({"distribution": "cluster", "hardware": H.from_nodes(nodes[3:])}),
                         ["GPU: none found in the cluster's node labels"])

    def test_cluster_inventory_adds_gpu_facts(self):
        nodes = {"items": [{"metadata": {"name": "n1", "labels": {}}, "status": {"allocatable": {"cpu": "4", "memory": "8Gi", "nvidia.com/gpu": "1"}}}]}
        with mock.patch.object(P, "kubectl", side_effect=[json.dumps(nodes), json.dumps({"items": []})]):
            result = P.inventory({"kind": "cluster", "kubeconfig": "/tmp/test-kubeconfig", "context": "throwaway"})
        self.assertEqual(result["hardware"]["gpus"][0]["node"], "n1")
        self.assertEqual(result["gpu"], "nvidia")
