"""A new box's hardware, read without changing anything, and described in plain words.

`collect` runs on the box: provision.py sends its source over SSH with the rest of the
probe. It reads files under /sys and /proc and asks read-only tools (lspci, lsblk,
nvidia-smi, lsusb) when they exist. Every tool is optional. `parse` turns what it read
into facts on the desktop, so fixture outputs can stand in for a whole machine.
Nothing here formats, mounts or changes a disk; spare disks are suggestions only.
"""
import inspect
import json
import re
import shlex


def collect(root="/", run=None):
    """Read the box. Self-contained and Python 3.6 compatible: it runs as source on the box."""
    import glob
    import os
    import shutil
    import subprocess

    def at(path):
        return os.path.join(root, path.lstrip("/"))

    def read(path):
        try:
            with open(path, errors="replace") as stream:
                return stream.read(1 << 20).strip()
        except (OSError, ValueError):
            return None

    def tool(argv):
        if run is not None:
            return run(argv)
        if not shutil.which(argv[0]):
            return None
        try:
            result = subprocess.run(argv, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL,
                                    universal_newlines=True, timeout=20)
        except (OSError, subprocess.SubprocessError):
            return None
        return result.stdout if result.returncode == 0 else None

    out = {}
    pci = []
    for dev in sorted(glob.glob(at("/sys/bus/pci/devices/*"))):
        cls = (read(dev + "/class") or "")[2:6]
        vendor = (read(dev + "/vendor") or "")[2:]
        device = (read(dev + "/device") or "")[2:]
        driver = os.path.basename(os.readlink(dev + "/driver")) if os.path.islink(dev + "/driver") else None
        if cls[:2] in ("03", "12") or vendor == "1ac1":
            pci.append({"slot": os.path.basename(dev), "class": cls, "vendor": vendor, "device": device, "driver": driver})
    out["pci"] = pci
    out["lspci"] = tool(["lspci", "-mm", "-nn", "-D"])
    names = {}
    ids = next((p for p in ("/usr/share/hwdata/pci.ids", "/usr/share/misc/pci.ids", "/usr/share/pci.ids") if os.path.exists(at(p))), None)
    if out["lspci"] is None and ids and pci:
        wanted = {d["vendor"] + ":" + d["device"] for d in pci}
        vendor = None
        with open(at(ids), errors="replace") as stream:
            for line in stream:
                if not line.strip() or line.startswith("#") or line.startswith("\t\t"):
                    continue
                if not line.startswith("\t"):
                    vendor = line[:4]
                    if any(w.startswith(vendor + ":") for w in wanted):
                        names[vendor] = line[4:].strip()
                elif vendor and vendor + ":" + line[1:5] in wanted:
                    names[vendor + ":" + line[1:5]] = line[5:].strip()
    out["pci_names"] = names
    out["nvidia_smi"] = tool(["nvidia-smi", "--query-gpu=pci.bus_id,name,memory.total,driver_version", "--format=csv,noheader,nounits"])
    vram = {}
    for card in glob.glob(at("/sys/class/drm/card*")):
        if not os.path.basename(card)[4:].isdigit():
            continue
        total = read(card + "/device/mem_info_vram_total")
        slot = next((line.split("=", 1)[1] for line in (read(card + "/device/uevent") or "").splitlines()
                     if line.startswith("PCI_SLOT_NAME=")), None)
        if total and total.isdigit() and slot:
            vram[slot] = int(total)
    out["drm_vram"] = vram
    columns = "NAME,SIZE,TYPE,ROTA,TRAN,RM,RO,MODEL,FSTYPE,"
    out["lsblk"] = tool(["lsblk", "-J", "-b", "-o", columns + "MOUNTPOINTS"]) or tool(["lsblk", "-J", "-b", "-o", columns + "MOUNTPOINT"])
    if out["lsblk"] is None:
        blocks = []
        for dev in sorted(glob.glob(at("/sys/block/*"))):
            name = os.path.basename(dev)
            blocks.append({"name": name, "size": int(read(dev + "/size") or 0) * 512, "rota": read(dev + "/queue/rotational") == "1",
                           "rm": read(dev + "/removable") == "1", "model": read(dev + "/device/model"),
                           "partitions": len(glob.glob(dev + "/" + name + "*")), "holders": len(os.listdir(dev + "/holders")) if os.path.isdir(dev + "/holders") else 0})
        out["sys_block"] = blocks
    network = ("nfs", "nfs4", "cifs", "smb3", "smbfs", "9p", "virtiofs", "fuse.sshfs", "glusterfs", "ceph")
    mounts = []
    for line in (read(at("/proc/mounts")) or "").splitlines():
        parts = line.split()
        if len(parts) < 3 or not (parts[0].startswith("/dev/") or parts[2] in network):
            continue
        mount, i = "", 0
        while i < len(parts[1]):  # /proc/mounts escapes spaces and tabs as octal
            code = parts[1][i + 1:i + 4]
            if parts[1][i] == "\\" and len(code) == 3 and code.isdigit():
                mount, i = mount + chr(int(code, 8)), i + 4
            else:
                mount, i = mount + parts[1][i], i + 1
        entry = {"source": parts[0], "mount": mount, "fstype": parts[2]}
        try:
            stat = os.statvfs(at(mount))
            entry.update(total=stat.f_blocks * stat.f_frsize, free=stat.f_bavail * stat.f_frsize)
        except OSError:
            pass
        mounts.append(entry)
    out["mounts"] = mounts
    nics = []
    for nic in sorted(glob.glob(at("/sys/class/net/*"))):
        name = os.path.basename(nic)
        if name == "lo" or not os.path.exists(nic + "/device"):
            continue
        nics.append({"name": name, "wireless": os.path.exists(nic + "/wireless") or os.path.exists(nic + "/phy80211"),
                     "speed": read(nic + "/speed"), "operstate": read(nic + "/operstate"), "carrier": read(nic + "/carrier")})
    out["net"] = nics
    cpuinfo = read(at("/proc/cpuinfo")) or ""
    model = next((line.split(":", 1)[1].strip() for line in cpuinfo.splitlines() if line.startswith("model name")), None)
    if not model:
        lscpu = tool(["lscpu"]) or ""
        model = next((line.split(":", 1)[1].strip() for line in lscpu.splitlines() if line.startswith("Model name:")), None)
    flags = next((line.split(":", 1)[1].split() for line in cpuinfo.splitlines() if line.startswith("flags")), [])
    out["cpu"] = {"model": model, "flags": [f for f in ("vmx", "svm", "hypervisor") if f in flags], "kvm": os.path.exists(at("/dev/kvm"))}
    out["chassis"] = read(at("/sys/class/dmi/id/chassis_type"))
    out["battery"] = any(read(p + "/type") == "Battery" and read(p + "/scope") != "Device" for p in glob.glob(at("/sys/class/power_supply/*")))
    usb = []
    for dev in sorted(glob.glob(at("/sys/bus/usb/devices/*"))):
        vendor = read(dev + "/idVendor")
        if not vendor or vendor == "1d6b":
            continue
        usb.append({"id": vendor + ":" + (read(dev + "/idProduct") or ""), "product": read(dev + "/product"), "manufacturer": read(dev + "/manufacturer"),
                    "classes": sorted({read(c) for c in glob.glob(dev + "/*:*/bInterfaceClass")} - {None})})
    out["usb"] = usb
    out["lsusb"] = None if usb else tool(["lsusb"])
    return out


# The probe's addition: the collector's source, then a guarded call. A failure leaves the
# old facts working and reports no hardware.
SOURCE = inspect.getsource(collect) + """
try:
    hardware_raw = collect()
except Exception:
    hardware_raw = None
"""

VENDORS = {"10de": "NVIDIA", "1002": "AMD", "8086": "Intel"}
LAPTOP_CHASSIS = {"8", "9", "10", "14", "31", "32"}
SYSTEM_MOUNTS = {"/", "/home", "/var", "/usr", "/tmp", "/opt", "/var/log"}
SYSTEM_PREFIXES = ("/boot", "/efi", "/snap/", "/var/lib/docker", "/var/lib/containers", "/var/lib/kubelet", "/var/lib/rancher", "/run", "/proc", "/sys", "/dev")
NETWORK_FS = ("nfs", "nfs4", "cifs", "smb3", "smbfs", "glusterfs", "ceph")
MEMBERS = {"zfs_member": "part of a ZFS pool", "linux_raid_member": "part of a RAID array", "LVM2_member": "used by LVM",
           "crypto_LUKS": "encrypted", "swap": "used as swap", "bcache": "used by bcache", "ceph_bluestore": "used by Ceph"}
# (USB IDs, words in the device's name, what it is, what it could be used for)
USB_HINTS = (
    ({"1a6e:089a", "18d1:9302"}, ("coral",), "Coral Edge TPU", "fast object detection in Frigate"),
    ({"0658:0200"}, ("z-wave", "zwave", "z-stick", "zst10", "zst39", "zwa-"), "Z-Wave stick", "Z-Wave devices in Home Assistant"),
    ({"1cf1:0030", "0451:16a8"}, ("zigbee", "conbee", "skyconnect", "zbt-1", "zbdongle", "sonoff"), "Zigbee stick", "Zigbee devices in Home Assistant"),
    (set(), ("webcam", "camera"), "Camera", "a camera feed in Frigate or Home Assistant"),
)


def size(n):
    """Disk sizes in decimal units, as the label on the disk says."""
    if n >= 1e12:
        return f"{n / 1e12:.1f}".removesuffix(".0") + " TB"
    if n >= 1e9:
        return f"{round(n / 1e9)} GB"
    return f"{round(n / 1e6)} MB"


def gib(n):
    return f"{round(n)} GB"


def flag(value):
    return value in (True, 1, "1", "true")


def parse_lspci(text):
    """lspci -mm -nn -D → {slot: (class, vendor name, vendor ID, device name, device ID)}."""
    out = {}
    for line in (text or "").splitlines():
        try:
            fields = shlex.split(line)
        except ValueError:
            continue
        fields = [f for f in fields if not re.fullmatch(r"-[a-z]\w*", f)]
        if len(fields) < 4:
            continue
        def split(field):
            match = re.fullmatch(r"(.*?)\s*\[([0-9a-fA-F]{4})\]", field)
            return (match.group(1), match.group(2).lower()) if match else (field, "")
        _, cls = split(fields[1])
        vendor, vendor_id = split(fields[2])
        device, device_id = split(fields[3])
        out[fields[0].lower()] = (cls, vendor, vendor_id, device, device_id)
    return out


def parse_nvidia_smi(text):
    """nvidia-smi's CSV → {slot: (name, VRAM GiB, driver version)}."""
    out = {}
    for line in (text or "").splitlines():
        parts = [p.strip() for p in line.split(",")]
        if len(parts) < 4:
            continue
        try:
            memory = float(parts[2]) / 1024
        except ValueError:
            memory = None
        out[parts[0].lower()[-12:]] = (parts[1], memory, parts[3])
    return out


def model_name(device):
    """'GA102 [GeForce RTX 3090]' → 'GeForce RTX 3090'; names without brackets stay whole."""
    found = re.findall(r"\[([^\]]+)\]", device or "")
    return found[-1] if found else (device or "").strip()


def gpus(raw):
    named = parse_lspci(raw.get("lspci"))
    smi = parse_nvidia_smi(raw.get("nvidia_smi"))
    names = raw.get("pci_names") or {}
    devices = raw.get("pci") or []
    if not devices and named:
        devices = [{"slot": slot, "class": row[0], "vendor": row[2], "device": row[4], "driver": None} for slot, row in named.items()]
    out = []
    for dev in devices:
        vendor = VENDORS.get(dev["vendor"])
        if not vendor or not dev["class"].startswith("03"):
            continue  # basic display chips (a server's BMC, a VM's virtual screen) are not GPUs
        slot = dev["slot"].lower()
        row = named.get(slot)
        model = model_name(row[3] if row else names.get(dev["vendor"] + ":" + dev["device"], ""))
        driver, memory = dev.get("driver"), None
        if slot[-12:] in smi:
            name, memory, _ = smi[slot[-12:]]
            model, driver = name.removeprefix("NVIDIA ").strip(), driver or "nvidia"
        elif vendor == "AMD" and slot in (raw.get("drm_vram") or {}):
            memory = raw["drm_vram"][slot] / 2**30
        if driver == "nvidia":
            ready = slot[-12:] in smi
            state = "driver loaded" if ready else "NVIDIA's driver is loaded, but nvidia-smi doesn't answer"
        elif driver in ("amdgpu", "i915", "xe"):
            ready, state = True, "driver loaded"
        elif driver == "nouveau":
            ready, state = False, "open-source nouveau driver; AI services need NVIDIA's driver"
        elif driver == "radeon":
            ready, state = False, "old radeon driver; AI services need amdgpu"
        elif driver == "vfio-pci":
            ready, state = False, "reserved for virtual machines (vfio-pci)"
        elif driver:
            ready, state = False, driver + " driver"
        else:
            ready, state = False, "no driver loaded"
        if not model or model.lower() == "device":
            model = "graphics (device " + dev["device"] + ")"
        out.append({"slot": slot, "vendor": vendor, "model": model, "driver": driver, "ready": ready, "state": state,
                    "vram_gib": round(memory, 1) if memory else None})
    seen = {g["slot"][-12:] for g in out}
    for slot, (name, memory, _) in smi.items():  # a GPU nvidia-smi sees but the PCI read missed
        if slot not in seen:
            out.append({"slot": slot, "vendor": "NVIDIA", "model": name.removeprefix("NVIDIA ").strip(), "driver": "nvidia", "ready": True,
                        "state": "driver loaded", "vram_gib": round(memory, 1) if memory else None})
    return out


def _walk(node):
    yield node
    for child in node.get("children") or []:
        yield from _walk(child)


def disks(raw):
    """Whole disks from lsblk, or /sys/block when lsblk is missing (then emptiness is unknown)."""
    out = []
    if raw.get("lsblk"):
        try:
            tree = json.loads(raw["lsblk"]).get("blockdevices", [])
        except ValueError:
            tree = []
        for dev in tree:
            name = dev.get("name") or ""
            total = int(dev.get("size") or 0)
            if dev.get("type") != "disk" or name.startswith(("zram", "loop", "ram")) or total < 1e9:
                continue  # also a VM's seed image or an empty card reader: too small to matter
            nodes = list(_walk(dev))
            mounts = [m for n in nodes for m in (n.get("mountpoints") or [n.get("mountpoint")]) if m]
            fstypes = [n["fstype"] for n in nodes if n.get("fstype")]
            tran = (dev.get("tran") or "").lower()
            kind = "NVMe" if tran == "nvme" or name.startswith("nvme") else "virtual disk" if name.startswith(("vd", "xvd")) else "HDD" if flag(dev.get("rota")) else "SSD"
            if tran == "usb":
                kind = "USB " + kind
            system = any(m == "/" or m.startswith(("/boot", "/efi")) or m == "[SWAP]" for m in mounts)
            member = next((MEMBERS[f] for f in fstypes if f in MEMBERS), None)
            out.append({"name": name, "size": total, "kind": kind, "model": (dev.get("model") or "").strip() or None,
                        "mounts": [m for m in mounts if m != "[SWAP]"], "fstype": fstypes[0] if fstypes else None,
                        "partitions": len(nodes) - 1, "system": system, "member": member, "removable": flag(dev.get("rm")),
                        "empty": not mounts and not fstypes and len(nodes) == 1})
    else:
        mounted = {m["source"].removeprefix("/dev/") for m in raw.get("mounts") or []}
        for dev in raw.get("sys_block") or []:
            name = dev["name"]
            if name.startswith(("zram", "loop", "ram", "sr", "dm-", "md")) or dev.get("size", 0) < 1e9:
                continue
            system = any(m["mount"] == "/" and m["source"].removeprefix("/dev/").startswith(name) for m in raw.get("mounts") or [])
            mounts = [m["mount"] for m in raw.get("mounts") or [] if m["source"].removeprefix("/dev/").startswith(name)]
            out.append({"name": name, "size": dev["size"], "kind": "NVMe" if name.startswith("nvme") else "HDD" if dev.get("rota") else "SSD",
                        "model": dev.get("model"), "mounts": mounts, "fstype": None, "partitions": dev.get("partitions", 0),
                        "system": system, "member": None, "removable": dev.get("rm", False), "empty": None,
                        "unknown": not any(n.startswith(name) for n in mounted)})
    return out


def backup_places(raw):
    """Mounted filesystems off the system disk, and NAS shares: places backups could go."""
    mounts = raw.get("mounts") or []
    root = next((m["source"] for m in mounts if m["mount"] == "/"), None)
    out, seen = [], set()
    for m in mounts:
        path = m["mount"]
        if path in SYSTEM_MOUNTS or path.startswith(SYSTEM_PREFIXES) or m["source"] == root or path in seen:
            continue
        seen.add(path)
        nas = m["fstype"] in NETWORK_FS
        out.append({"path": path, "kind": "NAS share" if nas else "disk", "fstype": m["fstype"], "free": m.get("free"), "total": m.get("total")})
    return sorted(out, key=lambda p: -(p["free"] or 0))


def network(raw):
    out = []
    for nic in raw.get("net") or []:
        text = (nic.get("speed") or "").strip()
        speed = int(text) if text.lstrip("-").isdigit() and int(text) > 0 else None
        out.append({"name": nic["name"], "wifi": bool(nic.get("wireless")), "connected": nic.get("operstate") == "up",
                    "speed_mbps": speed})
    return out


def cpu(raw):
    info = raw.get("cpu") or {}
    model = re.sub(r"\s+", " ", re.sub(r"\((R|TM|tm|r)\)", "", info.get("model") or "")).strip() or None
    flags = set(info.get("flags") or [])
    kind = "VT-x" if "vmx" in flags else "AMD-V" if "svm" in flags else "KVM" if info.get("kvm") else None
    if kind and info.get("kvm"):
        virt = f"available ({kind})"
    elif kind:
        virt = f"supported ({kind}), but /dev/kvm is missing"
    elif "hypervisor" in flags:
        virt = "not available inside this virtual machine"
    else:
        virt = "not available; if the CPU supports it, turn it on in the firmware settings"
    return {"model": model, "virtualisation": virt, "kvm": bool(info.get("kvm"))}


def usb(raw):
    devices = list(raw.get("usb") or [])
    for line in (raw.get("lsusb") or "").splitlines():
        match = re.match(r"Bus \d+ Device \d+: ID ([0-9a-f]{4}:[0-9a-f]{4})\s*(.*)", line)
        if match and not match.group(1).startswith("1d6b:"):
            devices.append({"id": match.group(1), "product": match.group(2), "manufacturer": None, "classes": []})
    out = []
    for dev in devices:
        product, maker = dev.get("product") or "", dev.get("manufacturer") or ""
        name = (product if not maker or not product or maker.split()[0].lower() in product.lower() else maker + " " + product) or maker
        words = name.lower()
        for ids, keywords, label, use in USB_HINTS:
            if dev["id"] in ids or any(k in words for k in keywords) or (label == "Camera" and "0e" in (dev.get("classes") or [])):
                out.append({"bus": "USB", "id": dev["id"], "name": name or label, "kind": label, "use": use})
                break
    for dev in raw.get("pci") or []:
        if dev["vendor"] == "1ac1":  # Global Unichip: Coral's M.2 and PCIe cards
            out.append({"bus": "PCIe", "id": "1ac1:" + dev["device"], "name": "Coral Edge TPU", "kind": "Coral Edge TPU", "use": USB_HINTS[0][3]})
    return out


def parse(raw):
    """What collect() read → hardware facts. None when the box sent nothing."""
    if not raw:
        return None
    return {"cpu": cpu(raw), "gpus": gpus(raw), "disks": disks(raw), "backup_places": backup_places(raw),
            "network": network(raw), "usb": usb(raw),
            "laptop": (raw.get("chassis") or "") in LAPTOP_CHASSIS or bool(raw.get("battery"))}


def legacy(hw):
    """The older gpu and vram_gib facts that sizing reads: a GPU counts once its driver works."""
    ready = [g for g in (hw or {}).get("gpus", []) if g["ready"] and g["vendor"] in ("NVIDIA", "AMD")]
    for vendor in ("NVIDIA", "AMD"):
        chosen = [g for g in ready if g["vendor"] == vendor]
        if chosen:
            return vendor.lower(), sum(g["vram_gib"] or 0 for g in chosen)
    return "none", 0


def from_nodes(nodes):
    """GPUs on an existing cluster, from node labels and allocatable resources (no SSH)."""
    out = []
    for node in nodes:
        labels = node["metadata"].get("labels") or {}
        allocatable = node["status"].get("allocatable") or {}
        name = node["metadata"]["name"]
        for vendor, resource, product, vendor_id in (("NVIDIA", "nvidia.com/gpu", "nvidia.com/gpu.product", "10de"),
                                                     ("AMD", "amd.com/gpu", "amd.com/gpu.product-name", "1002"),
                                                     ("Intel", "gpu.intel.com/i915", "", "8086")):
            count = int(float(allocatable.get(resource, 0) or 0))
            present = any(re.fullmatch(r"feature\.node\.kubernetes\.io/pci-03[0-9a-f]{2}_" + vendor_id + r"\.present", k) or
                          (vendor != "Intel" and k == f"feature.node.kubernetes.io/pci-{vendor_id}.present") for k in labels)
            if not count and not present:
                continue
            memory = labels.get("nvidia.com/gpu.memory") if vendor == "NVIDIA" else None
            out.append({"node": name, "vendor": vendor, "model": (labels.get(product) or "").replace("-", " ").removeprefix("NVIDIA ").strip() or None,
                        "count": count or int(labels.get("nvidia.com/gpu.count", 0) or 0) or 1,
                        "vram_gib": round(float(memory) / 1024, 1) if memory and memory.isdigit() else None, "ready": bool(count),
                        "state": "usable by the cluster" if count else "found, but the cluster can't use it yet (no device plugin)"})
    return {"gpus": out}


def describe(facts):
    """Plain lines for the plan: what the box is, what it has."""
    hw = facts.get("hardware") or {}
    lines = []
    if facts.get("distribution") == "cluster":
        for g in hw.get("gpus", []):
            name = " ".join(p for p in (g["vendor"], g["model"]) if p) if g["model"] else g["vendor"] + " GPU"
            count = f"{g['count']} × " if g["count"] > 1 else ""
            memory = f", {gib(g['vram_gib'])}{' each' if g['count'] > 1 else ''}" if g["vram_gib"] else ""
            lines.append(f"GPU: {count}{name} on node {g['node']}{memory}, {g['state']}")
        if not hw.get("gpus"):
            lines.append("GPU: none found in the cluster's node labels")
        return lines
    distro = {"debian": "Debian", "ubuntu": "Ubuntu", "fedora": "Fedora", "arch": "Arch Linux"}.get(facts.get("distribution"), facts.get("distribution"))
    arch = {"x86_64": "x86-64", "aarch64": "ARM64"}.get(facts.get("architecture"), facts.get("architecture"))
    parts = [p for p in (distro, arch) if p]
    if facts.get("cpu"):
        parts.append(f"{facts['cpu']} CPU threads")
    if facts.get("ram_gib"):
        parts.append(f"{gib(facts['ram_gib'])} memory")
    if facts.get("disk_gib") is not None:
        parts.append(f"{size(facts['disk_gib'] * 2**30)} free on the system disk")
    lines.append("Box: " + ", ".join(parts))
    if not hw:
        return lines
    if hw.get("laptop"):
        lines.append("Machine: a laptop. Keep it plugged in, and set it to stay on with the lid closed")
    c = hw["cpu"]
    lines.append("CPU: " + (c["model"] + ", " if c["model"] else "") + "virtualisation " + c["virtualisation"])
    groups = {}
    for g in hw["gpus"]:
        name = g["model"] if g["model"].startswith(g["vendor"]) else g["vendor"] + " " + g["model"]
        groups.setdefault((name, g["vram_gib"], g["state"]), []).append(g)
    for (name, memory, state), same in groups.items():
        count = f"{len(same)} × " if len(same) > 1 else ""
        memory = f"{gib(memory)}{' each' if len(same) > 1 else ''}, " if memory else ""
        lines.append(f"GPU: {count}{name}, {memory}{state}")
    if not hw["gpus"]:
        lines.append("GPU: none found")
    for d in hw["disks"]:
        label = size(d["size"]) + " " + d["kind"] + (f" ({d['model']})" if d["model"] else "")
        if d["system"]:
            lines.append(f"System disk: {label}")
        elif d["empty"]:
            lines.append(f"{'Removable disk' if d['removable'] else 'Spare disk'}: {label}, empty, not mounted")
        elif d["member"]:
            lines.append(f"Disk: {label}, {d['member']}")
        elif d["mounts"]:
            shown = sorted(d["mounts"], key=len)[:2]
            more = f" and {len(d['mounts']) - 2} more" if len(d["mounts"]) > 2 else ""
            lines.append(f"Disk: {label}, mounted at {', '.join(shown)}{more}")
        elif d["fstype"]:
            lines.append(f"Disk: {label}, has a filesystem ({d['fstype']}), not mounted")
        elif d["empty"] is None:
            lines.append(f"Disk: {label}, not mounted; lsblk is missing, so its contents are unknown")
        else:
            lines.append(f"Disk: {label}, partitioned, no filesystem found, not mounted")
    for p in hw["backup_places"]:
        if p["kind"] == "NAS share":
            lines.append(f"NAS share: {p['path']} ({p['fstype']})" + (f", {size(p['free'])} free" if p["free"] is not None else ""))
    for n in hw["network"]:
        state = "connected" if n["connected"] else "not connected"
        speed = speed_text(n["speed_mbps"]) + ", " if n["speed_mbps"] and n["connected"] and not n["wifi"] else ""
        lines.append(f"{'Wi-Fi' if n['wifi'] else 'Wired network'}: {n['name']}, {speed}{state}")
    for u in hw["usb"]:
        lines.append(f"{u['bus']}: {u['name']}. Could be used for {u['use']}")
    return lines


def speed_text(mbps):
    return f"{mbps / 1000:g} Gb/s" if mbps >= 1000 else f"{mbps} Mb/s"


def on_place(path, places):
    return next((p for p in places if path == p["path"] or path.startswith(p["path"].rstrip("/") + "/")), None)


def notes(facts, picked, cat, backup_path=""):
    """Warnings and suggestions from the hardware. Suggestions never change the plan."""
    hw = facts.get("hardware")
    if not hw:
        return []
    out = []
    usable = [g for g in hw.get("gpus", []) if g["ready"]]
    for sid in picked:
        need = cat["service"].get(sid, {}).get("needs", {}).get("gpu", "none")
        if need == "none":
            continue
        title = cat["service"][sid].get("title", sid)
        if any(need == "any" or g["vendor"].lower() == need for g in usable):
            continue
        matching = [g for g in hw.get("gpus", []) if need == "any" or g["vendor"].lower() == need]
        if not hw.get("gpus"):
            out.append(f"{title} needs a GPU, and none was found")
        elif matching:
            g = matching[0]
            out.append(f"{title} needs a GPU. The {g['vendor']} {g['model']} has no working driver ({g['state']}). Set up its driver on the box first")
        else:
            out.append(f"{title} needs an {VENDORS.get({'nvidia': '10de', 'amd': '1002'}.get(need), need)} GPU with a working driver; this box has none")
    nics = hw.get("network", [])
    if nics and not any(n["connected"] and not n["wifi"] for n in nics) and any(n["connected"] and n["wifi"] for n in nics):
        out.append("Only Wi-Fi is connected. A network cable is steadier for a server")
    slow = [n for n in nics if n["connected"] and not n["wifi"] and n["speed_mbps"] and n["speed_mbps"] < 1000]
    if slow and not any(n["connected"] and not n["wifi"] and (n["speed_mbps"] or 0) >= 1000 for n in nics):
        out.append(f"The wired link runs at {speed_text(slow[0]['speed_mbps'])}. Check the cable and switch port; backups will be slow")
    if "restic" in picked:
        places = hw.get("backup_places", [])
        if backup_path and facts.get("distribution") != "cluster" and not on_place(backup_path, places):
            out.append(f"Backups go to {backup_path}, on the system disk. If that disk fails, the backups go with it")
            for p in places:
                out.append(f"Suggestion: {p['path']} is a {p['kind']}" + (f" with {size(p['free'])} free" if p["free"] is not None else "") + ". It could hold backups")
        for d in hw.get("disks", []):
            if d["empty"] and not d["removable"]:
                out.append(f"Suggestion: the empty {size(d['size'])} {d['kind']} ({d['name']}) could hold backups once you format and mount it. "
                           "Provisioning never formats or mounts disks")
    return out
