"""Stand-in machines for the salvage scan's tests: each is a fake root (/proc, /sys, /run/udev,
/dev as the kernel and udev document them) and recorded tool outputs (lspci -mm -nn -D,
lsblk -J -b, ethtool, vainfo, smartctl -H -j, nvidia-smi's CSV, dmidecode -t memory). Nothing
here reads the machine the tests run on. Every identifier is made up, and marked FAKE so a test
can prove none of them reaches a report: serial numbers, MAC addresses, the hostname.

    root, run = build(tmp, MACHINES["desktop-2012"])
    doc = salvage.scan(root=root, run=run, euid=0, sleep=lambda s: None)
"""
import json
import os
from pathlib import Path

HOSTNAME = "fake-hostname-attic"
SERIALS = ("FAKE-SERIAL-DISK", "FAKE-SERIAL-DIMM", "FAKE-SERIAL-BOARD", "FAKE-UUID-0000")

V2 = "fpu de pse tsc msr pae cx8 apic sep cmov pat mmx fxsr sse sse2 ht syscall nx lm pni ssse3 cx16 sse4_1 sse4_2 popcnt lahf_lm"
V3 = V2 + " avx avx2 bmi1 bmi2 f16c fma abm movbe xsave"


def cpuinfo(model, vendor, flags, cores=4, threads=4):
    """/proc/cpuinfo: one block per logical processor, a blank line between."""
    out = []
    for n in range(threads):
        out.append(f"processor\t: {n}\nvendor_id\t: {vendor}\nmodel name\t: {model}\nphysical id\t: 0\n"
                   f"core id\t\t: {n % cores}\ncpu cores\t: {cores}\nflags\t\t: {flags}\n")
    return "\n".join(out)


def meminfo(kib):
    return f"MemTotal:       {kib} kB\nMemFree:        {kib // 2} kB\nMemAvailable:   {kib // 2} kB\n"


def udev_memory(slots, sizes_gb, kind, ecc=None, max_gb=None):
    """udev's database entry for the DMI device (systemd's dmi_memory_id): /run/udev/data/+dmi:id."""
    lines = ["I:1234567", "E:ID_VENDOR=Example", f"E:MEMORY_ARRAY_NUM_DEVICES={slots}"]
    if max_gb:
        lines.append(f"E:MEMORY_ARRAY_MAX_CAPACITY={max_gb * 2**30}")
    if ecc:
        lines.append(f"E:MEMORY_ARRAY_EC_TYPE={ecc}")
    for n in range(slots):
        if n < len(sizes_gb):
            lines += [f"E:MEMORY_DEVICE_{n}_SIZE={sizes_gb[n] * 2**30}", f"E:MEMORY_DEVICE_{n}_TYPE={kind}",
                      f"E:MEMORY_DEVICE_{n}_SERIAL_NUMBER={SERIALS[1]}", f"E:MEMORY_DEVICE_{n}_PART_NUMBER=FAKE-PART",
                      f"E:MEMORY_DEVICE_{n}_ASSET_TAG=FAKE-ASSET"]
        else:
            lines.append(f"E:MEMORY_DEVICE_{n}_PRESENT=0")
    return "\n".join(lines) + "\n"


def pci(slot, cls, vendor, device, driver=None):
    base = f"sys/bus/pci/devices/{slot}/"
    files = {base + "class": f"0x{cls}\n", base + "vendor": f"0x{vendor}\n", base + "device": f"0x{device}\n"}
    links = [(base + "driver", f"../../../bus/pci/drivers/{driver}")] if driver else []
    return files, links


def nic(name, mac, speed=None, state="up", wireless=False):
    base = f"sys/class/net/{name}/"
    files = {base + "device": None, base + "operstate": state + "\n", base + "address": mac + "\n",
             base + "carrier": ("1" if state == "up" else "0") + "\n"}
    if speed is not None:
        files[base + "speed"] = speed + "\n"
    if wireless:
        files[base + "wireless"] = None
    return files


def block(name, rota):
    return {f"sys/block/{name}/queue/rotational": f"{rota}\n", f"sys/block/{name}/device/serial": SERIALS[0] + "\n"}


def disk(name, size, rota, tran, model, children=()):
    return {"name": name, "size": size, "type": "disk", "rota": rota, "tran": tran, "rm": False, "ro": False, "model": model,
            "fstype": None, "mountpoints": [None],
            **({"children": [{"name": c, "size": size // 2, "type": "part", "rota": rota, "tran": None, "rm": False,
                              "ro": False, "model": None, "fstype": fs, "mountpoints": [None]} for c, fs in children]}
               if children else {})}


def ethtool(name, modes, speed):
    rows = "\n\t                        ".join(modes)
    return (f"Settings for {name}:\n\tSupported ports: [ TP ]\n\tSupported link modes:   {rows}\n"
            "\tSupported pause frame use: Symmetric Receive-only\n\tSupports auto-negotiation: Yes\n"
            f"\tSpeed: {speed}\n\tDuplex: Full\n\tLink detected: yes\n")


def vainfo(rows):
    head = "vainfo: VA-API version: 1.22 (libva 2.22.0)\nvainfo: Driver version: an example driver\nvainfo: Supported profile and entrypoints\n"
    return head + "".join(f"      VAProfile{profile:<28}:\tVAEntrypoint{entry}\n" for profile, entry in rows)


SMART_OK = json.dumps({"smartctl": {"exit_status": 0}, "serial_number": SERIALS[0], "smart_status": {"passed": True}})
SMART_FAILING = json.dumps({"smartctl": {"exit_status": 8}, "serial_number": SERIALS[0], "smart_status": {"passed": False}})
GIGABIT = ["10baseT/Half 10baseT/Full", "100baseT/Half 100baseT/Full", "1000baseT/Full"]
DMI_PRIVATE = {"sys/class/dmi/id/product_serial": SERIALS[2] + "\n", "sys/class/dmi/id/board_serial": SERIALS[2] + "\n",
               "sys/class/dmi/id/product_uuid": SERIALS[3] + "\n", "proc/sys/kernel/hostname": HOSTNAME + "\n"}
EFI = "sys/firmware/efi/efivars/SecureBoot-8be4df61-93ca-11d2-aa0d-00e098032b8c"


def desktop_2012():
    """A 2012 office desktop: four cores without AVX2, 4 GB in two of four slots, one spinning
    disk that still holds Windows, gigabit, started the old way (BIOS)."""
    gpu, links = pci("0000:00:02.0", "030000", "8086", "0152", "i915")
    files = {**gpu, **DMI_PRIVATE, **nic("enp2s0", "02:00:00:fa:ce:01", "1000"), **block("sda", 1),
             "proc/cpuinfo": cpuinfo("Intel(R) Core(TM) i5-3470 CPU @ 3.20GHz", "GenuineIntel", V2 + " avx vmx"),
             "proc/meminfo": meminfo(3_982_000), "dev/kvm": "",
             "run/udev/data/+dmi:id": udev_memory(4, [2, 2], "DDR3", max_gb=32),
             "sys/class/dmi/id/chassis_type": "3\n", "sys/class/dmi/id/sys_vendor": "Example Computers\n",
             "sys/class/dmi/id/product_name": "Office Desktop 2012\n"}
    tools = {"lspci": '0000:00:02.0 "VGA compatible controller [0300]" "Intel Corporation [8086]" '
                      '"Xeon E3-1200 v2/3rd Gen Core processor Graphics Controller [0152]" -r09 "Example [1028]" "Device [052c]"\n',
             "lsblk": json.dumps({"blockdevices": [disk("sda", 500_107_862_016, True, "sata", "EXAMPLE HDD 500G",
                                                        [("sda1", "ntfs"), ("sda2", "ntfs")])]}),
             "ethtool": {"enp2s0": ethtool("enp2s0", GIGABIT, "1000Mb/s")}, "smartctl": {"/dev/sda": SMART_OK}}
    return files, links, tools


def office_pc():
    """A small office PC of about 2018: six cores, 16 GB, one SATA SSD, gigabit, UEFI with
    Secure Boot on and a TPM 2.0."""
    gpu, links = pci("0000:00:02.0", "030000", "8086", "3e92", "i915")
    files = {**gpu, **DMI_PRIVATE, **nic("eno1", "02:00:00:fa:ce:02", "1000"), **block("sda", 0),
             "proc/cpuinfo": cpuinfo("Intel(R) Core(TM) i5-8500 CPU @ 3.00GHz", "GenuineIntel", V3 + " vmx", cores=6, threads=6),
             "proc/meminfo": meminfo(16_261_000), "dev/kvm": "", "dev/dri/renderD128": "",
             "run/udev/data/+dmi:id": udev_memory(4, [8, 8], "DDR4", max_gb=64),
             "sys/class/dmi/id/chassis_type": "15\n", "sys/class/dmi/id/sys_vendor": "Example Computers\n",
             "sys/class/dmi/id/product_name": "Small Office PC\n", "sys/firmware/efi": None, EFI: b"\x06\x00\x00\x00\x01",
             "sys/class/tpm/tpm0/tpm_version_major": "2\n"}
    tools = {"lspci": '0000:00:02.0 "VGA compatible controller [0300]" "Intel Corporation [8086]" '
                      '"CoffeeLake-S GT2 [UHD Graphics 630] [3e92]" -p00 "Example [1028]" "Device [085a]"\n',
             "lsblk": json.dumps({"blockdevices": [disk("sda", 256_060_514_304, False, "sata", "EXAMPLE SSD 256G")]}),
             "ethtool": {"eno1": ethtool("eno1", GIGABIT, "1000Mb/s")}, "smartctl": {"/dev/sda": SMART_OK},
             "vainfo": vainfo([("MPEG2Main", "VLD"), ("H264Main", "VLD"), ("H264Main", "EncSliceLP"), ("H264High", "VLD"),
                               ("HEVCMain", "VLD"), ("HEVCMain", "EncSliceLP"), ("VP9Profile0", "VLD"), ("JPEGBaseline", "VLD")])}
    return files, links, tools


def mini_pc():
    """A mini PC: a four-core low-power processor with AVX2, 16 GB in its one slot, a 1 TB NVMe
    drive, 2.5 Gb/s wired and Wi-Fi it isn't using."""
    gpu, links = pci("0000:00:02.0", "030000", "8086", "46d1", "i915")
    files = {**gpu, **DMI_PRIVATE, **nic("enp1s0", "02:00:00:fa:ce:03", "2500"),
             **nic("wlo1", "02:00:00:fa:ce:04", state="down", wireless=True), **block("nvme0n1", 0),
             "proc/cpuinfo": cpuinfo("Intel(R) N100", "GenuineIntel", V3 + " vmx"),
             "proc/meminfo": meminfo(16_142_000), "dev/kvm": "", "dev/dri/renderD128": "",
             "run/udev/data/+dmi:id": udev_memory(1, [16], "DDR5", max_gb=16),
             "sys/class/dmi/id/chassis_type": "35\n", "sys/class/dmi/id/sys_vendor": "Example Computers\n",
             "sys/class/dmi/id/product_name": "Mini PC\n", "sys/firmware/efi": None, EFI: b"\x06\x00\x00\x00\x00",
             "sys/class/tpm/tpm0/tpm_version_major": "2\n", "sys/class/powercap/intel-rapl:0/energy_uj": "1000000\n"}
    tools = {"lspci": '0000:00:02.0 "VGA compatible controller [0300]" "Intel Corporation [8086]" '
                      '"Alder Lake-N [UHD Graphics] [46d1]" -p00 "Example [1028]" "Device [0001]"\n',
             "lsblk": json.dumps({"blockdevices": [disk("nvme0n1", 1_000_204_886_016, False, "nvme", "EXAMPLE NVME 1TB")]}),
             "ethtool": {"enp1s0": ethtool("enp1s0", GIGABIT + ["2500baseT/Full"], "2500Mb/s")},
             "smartctl": {"/dev/nvme0n1": SMART_OK},
             "vainfo": vainfo([("H264Main", "VLD"), ("H264Main", "EncSliceLP"), ("HEVCMain", "VLD"), ("HEVCMain", "EncSliceLP"),
                               ("VP9Profile0", "VLD"), ("AV1Profile0", "VLD")])}
    return files, links, tools


def laptop_wifi():
    """A laptop with no wired port: four cores and eight threads, 8 GB, a 256 GB NVMe drive, on Wi-Fi."""
    gpu, links = pci("0000:00:02.0", "030000", "8086", "5917", "i915")
    files = {**gpu, **DMI_PRIVATE, **nic("wlp2s0", "02:00:00:fa:ce:05", wireless=True), **block("nvme0n1", 0),
             "proc/cpuinfo": cpuinfo("Intel(R) Core(TM) i5-8250U CPU @ 1.60GHz", "GenuineIntel", V3 + " vmx", cores=4, threads=8),
             "proc/meminfo": meminfo(8_030_000), "dev/kvm": "",
             "run/udev/data/+dmi:id": udev_memory(2, [8], "DDR4", max_gb=32),
             "sys/class/dmi/id/chassis_type": "10\n", "sys/class/dmi/id/sys_vendor": "Example Computers\n",
             "sys/class/dmi/id/product_name": "Laptop 14\n", "sys/firmware/efi": None, EFI: b"\x06\x00\x00\x00\x01",
             "sys/class/power_supply/BAT0/type": "Battery\n"}
    tools = {"lspci": '0000:00:02.0 "VGA compatible controller [0300]" "Intel Corporation [8086]" '
                      '"UHD Graphics 620 [5917]" -r07 "Example [17aa]" "Device [225d]"\n',
             "lsblk": json.dumps({"blockdevices": [disk("nvme0n1", 256_060_514_304, False, "nvme", "EXAMPLE NVME 256G",
                                                        [("nvme0n1p1", "vfat"), ("nvme0n1p2", "ext4")])]}),
             "smartctl": {"/dev/nvme0n1": SMART_OK}}
    return files, links, tools


def virtual_machine():
    """A virtual machine that gives almost nothing away: two plain virtual processors, 2 GB, a
    virtual disk seen only through /sys/block, a virtual network port with no speed, no firmware
    tables in udev, and none of the tools installed."""
    files = {**nic("eth0", "02:00:00:fa:ce:06", "-1"), **DMI_PRIVATE,
             "proc/cpuinfo": "processor\t: 0\nvendor_id\t: GenuineIntel\nmodel name\t: QEMU Virtual CPU version 2.5+\n"
                             "flags\t\t: fpu de pse tsc msr pae cx8 apic sep cmov pat mmx fxsr sse sse2 syscall nx lm pni cx16 hypervisor\n\n"
                             "processor\t: 1\nvendor_id\t: GenuineIntel\nmodel name\t: QEMU Virtual CPU version 2.5+\n"
                             "flags\t\t: fpu de pse tsc msr pae cx8 apic sep cmov pat mmx fxsr sse sse2 syscall nx lm pni cx16 hypervisor\n",
             "proc/meminfo": meminfo(2_030_000), "sys/block/vda/size": str(20 * 2**30 // 512) + "\n",
             "sys/block/vda/queue/rotational": "1\n", "sys/block/vda/removable": "0\n",
             "sys/class/dmi/id/chassis_type": "1\n", "sys/class/dmi/id/sys_vendor": "QEMU\n",
             "sys/class/dmi/id/product_name": "Standard PC (i440FX + PIIX, 1996)\n"}
    return files, [], {}


def tower():
    """A tower with a graphics card: six cores and twelve threads, 32 GB, an SSD for the system,
    two 4 TB spinning disks, and an NVIDIA card whose driver is loaded."""
    gpu, links = pci("0000:01:00.0", "030000", "10de", "2504", "nvidia")
    files = {**gpu, **DMI_PRIVATE, **nic("enp5s0", "02:00:00:fa:ce:07", "1000"), **block("sda", 0), **block("sdb", 1), **block("sdc", 1),
             "proc/cpuinfo": cpuinfo("AMD Ryzen 5 3600 6-Core Processor", "AuthenticAMD", V3 + " svm", cores=6, threads=12),
             "proc/meminfo": meminfo(32_780_000), "dev/kvm": "",
             "run/udev/data/+dmi:id": udev_memory(4, [16, 16], "DDR4", max_gb=128),
             "sys/class/dmi/id/chassis_type": "7\n", "sys/class/dmi/id/sys_vendor": "To Be Filled By O.E.M.\n",
             "sys/class/dmi/id/product_name": "To Be Filled By O.E.M.\n", "sys/firmware/efi": None, EFI: b"\x06\x00\x00\x00\x00"}
    tools = {"lspci": '0000:01:00.0 "VGA compatible controller [0300]" "NVIDIA Corporation [10de]" '
                      '"GA106 [GeForce RTX 3060 Lite Hash Rate] [2504]" -ra1 "Example [1458]" "Device [4074]"\n',
             "nvidia-smi": "00000000:01:00.0, NVIDIA GeForce RTX 3060, 12288, 570.86\n",
             "lsblk": json.dumps({"blockdevices": [disk("sda", 500_107_862_016, False, "sata", "EXAMPLE SSD 500G"),
                                                   disk("sdb", 4_000_787_030_016, True, "sata", "EXAMPLE HDD 4T"),
                                                   disk("sdc", 4_000_787_030_016, True, "sata", "EXAMPLE HDD 4T")]}),
             "ethtool": {"enp5s0": ethtool("enp5s0", GIGABIT, "1000Mb/s")},
             "smartctl": {"/dev/sda": SMART_OK, "/dev/sdb": SMART_OK, "/dev/sdc": SMART_FAILING}}
    return files, links, tools


MACHINES = {"desktop-2012": desktop_2012, "office-pc": office_pc, "mini-pc": mini_pc, "laptop-wifi": laptop_wifi,
            "virtual-machine": virtual_machine, "tower": tower}


class Tools:
    """run(argv) for salvage.collect and hardware.collect: the recorded output for the tool, or
    None when the machine doesn't have it. Every call is kept, to prove what was and wasn't asked."""

    def __init__(self, outputs):
        self.outputs = dict(outputs)
        self.calls = []

    def __call__(self, argv):
        self.calls.append(list(argv))
        if argv[0] == "lsblk" and "SERIAL" in " ".join(argv):
            return "".join(f"{d['name']} {SERIALS[0]}\n" for d in json.loads(self.outputs.get("lsblk") or '{"blockdevices": []}')["blockdevices"])
        out = self.outputs.get(argv[0])
        return out.get(argv[-1]) if isinstance(out, dict) else out


def build(root, machine):
    """Write the machine under root; (root, its tools)."""
    files, links, tools = machine() if callable(machine) else machine
    for name, text in files.items():
        path = Path(root, name)
        if text is None:
            path.mkdir(parents=True, exist_ok=True)
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(text, bytes):
            path.write_bytes(text)
        else:
            path.write_text(text)
    for link, target in links:
        Path(root, link).parent.mkdir(parents=True, exist_ok=True)
        os.symlink(target, Path(root, link))
    return str(root), Tools(tools)
