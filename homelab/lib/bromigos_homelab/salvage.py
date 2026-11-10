"""Salvage scan: what this computer could do as a home server, in plain words
(docs/salvage.md; `bromigos hw salvage`; Field Kit's Server › What can this computer run?).

    from bromigos_homelab import salvage as S
    doc = S.scan()                      # read this machine and judge it: the --json document
    print("\\n".join(S.report(doc)))    # the report for people, top to bottom
    S.save(doc, "report.txt")           # the report and the document in one file to attach
    S.answers_toml(doc)                 # the choices as an answer file for the Server installer

`collect` reads files under /proc, /sys and /run/udev, and asks read-only tools when they
exist (lspci, lsblk, ethtool, vainfo, systemd-detect-virt; smartctl and dmidecode as root
only). Nothing is mounted, written or changed. `parse` turns what it read into facts, so a
fake root and recorded outputs can stand in for a whole machine. `judge` asks the provisioning
catalogue the installer's own questions (provcatalog.fits_item, recommend, budget): there is
one answer to "does this fit", and this module only words it.

Serial numbers, MAC addresses and the hostname are never read unless identifiers=True.
"""
import argparse
import glob
import json
import os
import re
import shutil
import subprocess
import sys
import textwrap
import time

from . import hardware as H
from . import provcatalog as PC

SCHEMA = 1
LAB = "none"                     # the scan judges a server that runs on its own
# the catalogue's roles, as the installer names them (presets.toml's titles and ids)
ROLE_NAMES = {"lab-node": "Lab node", "storage": "Storage", "home-services": "Home services",
              "game-server": "Game server", "media": "Media", "base": "Just a server"}
INSTALLER_ROLES = {"lab-node": "lab", "storage": "storage", "home-services": "home", "game-server": "games",
                   "media": "media", "base": "plain"}
# which roles the next step offers first: what a household uses first, the lab's cluster last
NEXT_ORDER = ("home-services", "media", "storage", "game-server", "lab-node")

# x86-64's feature levels, by /proc/cpuinfo's flag names (the psABI's x86-64-v2, -v3, -v4)
LEVELS = (("x86-64-v2", ("cx16", "lahf_lm", "popcnt", "sse4_1", "sse4_2", "ssse3")),
          ("x86-64-v3", ("avx", "avx2", "bmi1", "bmi2", "f16c", "fma", "abm", "movbe", "xsave")),
          ("x86-64-v4", ("avx512f", "avx512bw", "avx512cd", "avx512dq", "avx512vl")))
LEVEL_FLAGS = {"lm", "vmx", "svm", "hypervisor"} | {f for _, fs in LEVELS for f in fs}
AGE = {"x86-64-v1": ("very-old", "a very old design: no SSE4.2, as desktop processors had before about 2009"),
       "x86-64-v2": ("older", "an older or low-power design: no AVX2, as desktop processors had from about 2009 to "
                              "2013 and low-power ones into the early 2020s"),
       "x86-64-v3": ("current", "a current design: AVX2, as desktop processors have had since about 2013"),
       "x86-64-v4": ("current", "a current design with AVX-512")}
# SMBIOS chassis types (DSP0134, 7.4.1); laptops are hardware.LAPTOP_CHASSIS
MINI_CHASSIS = {"34", "35", "36"}
SERVER_CHASSIS = {"17", "23", "28", "29"}
DESKTOP_CHASSIS = {"3", "4", "5", "6", "7", "13", "15", "16", "24"}
VIDEO_DRIVERS = {"i915": "Intel graphics", "xe": "Intel graphics", "amdgpu": "AMD graphics", "nvidia": "an NVIDIA card"}
CODECS = (("MPEG2", "MPEG-2"), ("H264", "H.264"), ("HEVC", "HEVC (H.265)"), ("VP8", "VP8"), ("VP9", "VP9"), ("AV1", "AV1"))
MEMORY_STEPS = (8, 16, 32, 64, 128)      # the sizes "more memory" is tried at, in GB
STANDARD_MEMORY = (1, 2, 3, 4, 6, 8, 12, 16, 24, 32, 48, 64, 96, 128, 192, 256, 384, 512, 768, 1024)
MAC = re.compile(r"\b(?:[0-9a-fA-F]{2}[:-]){5}[0-9a-fA-F]{2}\b")
MAC_NAME = re.compile(r"(en|wl|ww)x[0-9a-f]{12}")
PRIVATE_KEYS = ("SERIAL", "ASSET", "PART_NUMBER", "Serial Number", "Asset Tag", "Part Number")
EFI_SECURE_BOOT = "/sys/firmware/efi/efivars/SecureBoot-8be4df61-93ca-11d2-aa0d-00e098032b8c"
NEEDS_ROOT = "needs administrator rights: run it with sudo, or from Field Kit"


# ---------------------------------------------------------------- reading the machine
def collect(root="/", run=None, euid=None, sleep=None, clock=None, identifiers=False):
    """What the machine says about itself, unjudged. run(argv) stands in for every tool (tests);
    euid for os.geteuid(); sleep and clock for the half second between the two power readings."""
    euid = os.geteuid() if euid is None else euid
    is_root = euid == 0

    def at(path):
        return os.path.join(root, path.lstrip("/"))

    def read(path, binary=False):
        try:
            with open(at(path), "rb") as f:
                data = f.read(1 << 20)
            return data if binary else data.decode(errors="replace").strip()
        except (OSError, ValueError):
            return None

    def tool(argv, any_status=False, timeout=5):
        if run is not None:
            return run(argv)
        if not shutil.which(argv[0]):
            return None
        try:
            r = subprocess.run(argv, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL,
                               text=True, timeout=timeout)
        except (OSError, subprocess.SubprocessError):
            return None
        return r.stdout if (r.returncode == 0 or any_status) and r.stdout else None

    raw = {"privileged": is_root, "base": H.collect(root, run=run)}

    blocks = [b for b in (read("/proc/cpuinfo") or "").split("\n\n") if b.strip()]

    def field(block, key):
        for line in block.splitlines():
            k, _, v = line.partition(":")
            if k.strip() == key:
                return v.strip()
        return None
    first = blocks[0] if blocks else ""
    cores = {(field(b, "physical id"), field(b, "core id")) for b in blocks if field(b, "core id") is not None}
    flags = (field(first, "flags") or "").split()
    raw["cpu"] = {"threads": sum(1 for b in blocks if field(b, "processor") is not None) or None,
                  "cores": len(cores) or None, "sockets": len({p for p, _ in cores}) or None,
                  "vendor": field(first, "vendor_id"), "model": field(first, "model name"),
                  "flags": sorted(set(flags) & LEVEL_FLAGS),
                  "arch": "x86_64" if "lm" in flags else "x86" if flags else "arm64" if field(first, "Features") else None}

    m = re.search(r"^MemTotal:\s+(\d+)", read("/proc/meminfo") or "", re.M)
    raw["mem_kib"] = int(m.group(1)) if m else None
    # the firmware's memory table: udev keeps it readable by everyone (systemd's dmi_memory_id);
    # dmidecode reads the same table, as root. Serial, asset and part numbers are dropped here.
    udev = [line[2:] for line in (read("/run/udev/data/+dmi:id") or "").splitlines()
            if line.startswith("E:MEMORY_") and not any(k in line for k in PRIVATE_KEYS)]
    raw["memory_udev"] = udev or None
    raw["memory_dmidecode"] = None
    if not udev and is_root:
        text = tool(["dmidecode", "-t", "memory"])
        if text:
            raw["memory_dmidecode"] = "\n".join(line for line in text.splitlines() if not any(k in line for k in PRIVATE_KEYS))
    raw["edac"] = os.path.isdir(at("/sys/devices/system/edac/mc/mc0"))

    # each drive's own verdict (SMART), as root only; never its attributes or its serial number
    smart = {}
    for dev in sorted(glob.glob(at("/sys/block/*"))):
        name = os.path.basename(dev)
        if name.startswith(("loop", "zram", "ram", "sr", "dm-", "md", "fd")):
            continue
        smart[name] = tool(["smartctl", "-H", "-j", "/dev/" + name], any_status=True, timeout=3) if is_root else None
    raw["smart"] = smart
    # the stick this live system started from (archiso's boot medium): never counted
    raw["live"] = os.path.isdir(at("/run/archiso"))
    raw["medium"] = None
    for line in (read("/proc/mounts") or "").splitlines():
        parts = line.split()
        if len(parts) > 1 and parts[1] == "/run/archiso/bootmnt" and parts[0].startswith("/dev/"):
            raw["medium"] = _disk_of(parts[0][5:])

    raw["ethtool"] = {n["name"]: tool(["ethtool", n["name"]]) for n in raw["base"].get("net") or [] if not n.get("wireless")}

    secure = read(EFI_SECURE_BOOT, binary=True)
    raw["firmware"] = {"efi": os.path.isdir(at("/sys/firmware/efi")),
                       "secure_boot": secure[4] if secure and len(secure) >= 5 else None,
                       "tpm": read("/sys/class/tpm/tpm0/tpm_version_major")}
    dmi = "/sys/class/dmi/id/"
    raw["dmi"] = {"sys_vendor": read(dmi + "sys_vendor"), "product_name": read(dmi + "product_name")}
    raw["virt"] = (tool(["systemd-detect-virt", "--vm"]) or "").strip() or None

    raw["vainfo"] = None                 # the first render device that answers (no display is opened)
    for node in sorted(glob.glob(at("/dev/dri/renderD*"))):
        raw["vainfo"] = tool(["vainfo", "--display", "drm", "--device", "/" + os.path.relpath(node, root)])
        if raw["vainfo"]:
            break

    # the processor package's own power counter (RAPL), root only: two readings, half a second apart
    raw["rapl_w"] = None
    rapl = "/sys/class/powercap/intel-rapl:0/energy_uj"
    raw["rapl"] = os.path.exists(at(rapl))
    if raw["rapl"] and is_root:
        try:
            clock = clock or time.monotonic
            a, t0 = int(read(rapl)), clock()
            (sleep or time.sleep)(0.5)
            b, t1 = int(read(rapl)), clock()
            if b > a and t1 > t0:
                raw["rapl_w"] = round((b - a) / 1e6 / (t1 - t0), 1)
        except (TypeError, ValueError):
            pass

    if identifiers:
        serials = tool(["lsblk", "-dn", "-o", "NAME,SERIAL"]) or ""
        raw["identifiers"] = {
            "hostname": read("/proc/sys/kernel/hostname"),
            "mac": {n["name"]: read(f"/sys/class/net/{n['name']}/address") for n in raw["base"].get("net") or []},
            "disk_serial": {p[0]: p[1] for p in (line.split() for line in serials.splitlines()) if len(p) == 2}}
    return raw


def _disk_of(part):
    """A partition's disk by name: nvme0n1p2 → nvme0n1, mmcblk0p1 → mmcblk0, sdb1 → sdb."""
    m = re.fullmatch(r"(nvme\d+n\d+|mmcblk\d+)p\d+", part)
    return m.group(1) if m else re.sub(r"\d+$", "", part)


# ---------------------------------------------------------------- facts
def x86_level(flags):
    """The highest x86-64 feature level whose every flag is present (each level includes the last)."""
    level = "x86-64-v1"
    for name, wanted in LEVELS:
        if not all(f in flags for f in wanted):
            break
        level = name
    return level


def parse_vainfo(text):
    """vainfo's profile lines → (what it decodes, what it encodes), as codec names."""
    decode, encode = [], []
    for line in (text or "").splitlines():
        m = re.match(r"\s*VAProfile(\w+?)\s*:\s*VAEntrypoint(\w+)", line)
        if not m:
            continue
        codec = next((words for key, words in CODECS if m.group(1).upper().startswith(key)), None)
        if not codec:
            continue
        into = decode if m.group(2) == "VLD" else encode if m.group(2).startswith("EncSlice") else None
        if into is not None and codec not in into:
            into.append(codec)
    return decode, encode


def parse_ethtool(text):
    """The fastest speed the port supports, in Mb/s, from ethtool's "Supported link modes"."""
    m = re.search(r"Supported link modes:(.*?)\n\s*Support", (text or "") + "\n Support", re.S)
    speeds = [int(s) for s in re.findall(r"(\d+)base", m.group(1))] if m else []
    return max(speeds) if speeds else None


def smart_verdict(text):
    """"ok", "failing" or None (no report) from `smartctl -H -j`'s smart_status.passed."""
    try:
        passed = (json.loads(text or "{}").get("smart_status") or {}).get("passed")
    except (ValueError, AttributeError):
        return None
    return "ok" if passed is True else "failing" if passed is False else None


def memory_table(raw):
    """The firmware's memory table: {slots, filled, free, installed_gb, max_gb, type, ecc,
    source}, or None when neither udev nor dmidecode gave one."""
    if raw.get("memory_udev"):
        env = dict(line.split("=", 1) for line in raw["memory_udev"] if "=" in line)
        sizes, empty = {}, set()
        for k, v in env.items():
            m = re.fullmatch(r"MEMORY_DEVICE_(\d+)_(SIZE|PRESENT)", k)
            if m and m.group(2) == "SIZE" and v.isdigit() and int(v) > 0:
                sizes[int(m.group(1))] = int(v)
            elif m and m.group(2) == "PRESENT" and v == "0":
                empty.add(int(m.group(1)))
        if not sizes and not empty:
            return None
        slots = int(env["MEMORY_ARRAY_NUM_DEVICES"]) if env.get("MEMORY_ARRAY_NUM_DEVICES", "").isdigit() else len(sizes) + len(empty)
        cap = env.get("MEMORY_ARRAY_MAX_CAPACITY", "")
        kind = next((env.get(f"MEMORY_DEVICE_{n}_TYPE") for n in sorted(sizes)), None)
        ec = env.get("MEMORY_ARRAY_EC_TYPE")           # udev leaves "None" out
        return {"slots": slots, "filled": len(sizes), "free": max(slots - len(sizes), 0),
                "installed_gb": round(sum(sizes.values()) / 2**30, 1), "max_gb": round(int(cap) / 2**30) if cap.isdigit() and int(cap) else None,
                "type": kind if kind not in (None, "Other", "Unknown", "<OUT OF SPEC>") else None,
                "ecc": _ecc(ec) if ec else False, "source": "udev"}
    text = raw.get("memory_dmidecode")
    if not text:
        return None
    sizes, slots, kinds = [], 0, []
    for block in text.split("\n\n"):
        if "Memory Device" not in block:
            continue
        m = re.search(r"^\s*Size:\s*(.+)$", block, re.M)
        if not m:
            continue
        slots += 1
        n = re.match(r"(\d+)\s*(MB|GB|TB)", m.group(1))
        if n:
            sizes.append(int(n.group(1)) * {"MB": 1 / 1024, "GB": 1, "TB": 1024}[n.group(2)])
            k = re.search(r"^\s*Type:\s*(.+)$", block, re.M)
            kinds.append(k.group(1).strip() if k else None)
    if not slots:
        return None
    count = re.search(r"Number Of Devices:\s*(\d+)", text)
    cap = re.search(r"Maximum Capacity:\s*(\d+)\s*(MB|GB|TB)", text)
    ec = re.search(r"Error Correction Type:\s*(.+)", text)
    slots = int(count.group(1)) if count else slots
    kind = next((k for k in kinds if k and k not in ("Other", "Unknown")), None)
    return {"slots": slots, "filled": len(sizes), "free": max(slots - len(sizes), 0), "installed_gb": round(sum(sizes), 1),
            "max_gb": round(int(cap.group(1)) * {"MB": 1 / 1024, "GB": 1, "TB": 1024}[cap.group(2)]) if cap else None,
            "type": kind, "ecc": _ecc(ec.group(1).strip()) if ec else None, "source": "dmidecode"}


def _ecc(words):
    """True for a correcting or checking kind, False for "None", None when the firmware doesn't say."""
    if words in ("Other", "Unknown", "<OUT OF SPEC>"):
        return None
    return words != "None"


def _discrete(gpus, vendor):
    """How many graphics cards are separate ones: NVIDIA's always are; an AMD or Intel one is when
    the processor is the other maker's, or when it isn't the only one."""
    cpu = {"GenuineIntel": "Intel", "AuthenticAMD": "AMD"}.get(vendor)
    other = sum(1 for g in gpus if g["vendor"] == "NVIDIA" or (cpu and g["vendor"] != cpu))
    return other + max(len(gpus) - other - 1, 0)


def storage_plan(disks):
    """How the disks could be grouped, as the installer's Storage step would: the system on the
    fastest disk (the smallest of those), the rest as data disks holding one copy or two. The
    stick, removable disks and a disk that says it's failing are left out."""
    inside = [d for d in disks if not d["medium"] and not d["removable"] and d["health"] != "failing"]
    if not inside:
        return {"system": None, "data": [], "layouts": []}
    system = sorted(inside, key=lambda d: (d["rotational"], d["kind"] != "NVMe", d["size_bytes"], d["name"]))[0]
    data = [d for d in inside if d is not system]
    layouts = []
    if not data:
        layouts.append({"id": "one-disk", "usable_bytes": system["size_bytes"], "survives_a_disk": False,
                        "words": f"One disk ({system['size']} {system['kind']}): the system and your data share it. "
                                 "Nothing protects them if it fails."})
    else:
        total = sum(d["size_bytes"] for d in data)
        names = " + ".join(f"{d['size']} {d['kind']}" for d in data)
        layouts.append({"id": "one-copy", "usable_bytes": total, "survives_a_disk": False,
                        "words": f"The system on the {system['size']} {system['kind']}; data on {names} as one copy: "
                                 f"{H.size(total)} to use, and a failed disk loses what was on it."})
        if len(data) >= 2:
            usable = min(total // 2, total - max(d["size_bytes"] for d in data))      # btrfs raid1
            layouts.append({"id": "two-copies", "usable_bytes": usable, "survives_a_disk": True,
                            "words": f"The system on the {system['size']} {system['kind']}; data on {names} as two "
                                     f"copies: {H.size(usable)} to use, and one disk can fail without losing anything."})
    return {"system": system["name"], "data": [d["name"] for d in data], "layouts": layouts}


def parse(raw):
    """What collect() read → the machine's facts, with what couldn't be read and why."""
    base = raw.get("base") or {}
    hwf = H.parse(base) or {"cpu": {}, "gpus": [], "disks": [], "network": [], "laptop": False}
    root_user = bool(raw.get("privileged"))
    unread = []
    cpu = raw.get("cpu") or {}
    flags = set(cpu.get("flags") or [])
    vm = raw.get("virt") or ("yes" if "hypervisor" in flags else None)

    level = x86_level(flags) if cpu.get("arch") == "x86_64" else None
    age, age_words = AGE.get(level, (None, None))
    gpus = hwf["gpus"]
    capable = [g for g in gpus if g.get("driver") in VIDEO_DRIVERS]
    decode, encode = parse_vainfo(raw.get("vainfo"))
    if raw.get("vainfo"):
        video = {"source": "vainfo", "decode": decode, "encode": encode, "likely": bool(decode or encode)}
    elif capable:
        video = {"source": "driver", "decode": [], "encode": [], "likely": True,
                 "from": f"{VIDEO_DRIVERS[capable[0]['driver']]} with the {capable[0]['driver']} driver loaded"}
        unread.append({"what": "which video formats the graphics chip decodes and encodes",
                       "why": "vainfo isn't installed (package libva-utils), or it found no device"})
    else:
        video = {"source": "driver", "decode": [], "encode": [], "likely": False}
    processor = {"model": hwf["cpu"].get("model") or None, "cpuinfo_model": cpu.get("model"), "vendor": cpu.get("vendor"),
                 "arch": cpu.get("arch"),
                 "threads": cpu.get("threads"), "cores": cpu.get("cores"), "sockets": cpu.get("sockets"),
                 "level": level, "age_class": age, "age_words": age_words, "age_from": "instruction sets" if level else None,
                 "virtualisation": hwf["cpu"].get("virtualisation"), "kvm": bool(hwf["cpu"].get("kvm")), "video": video}
    if not cpu.get("threads"):
        unread.append({"what": "the processor", "why": "/proc/cpuinfo couldn't be read"})

    kib = raw.get("mem_kib")
    table = memory_table(raw)
    memory = {"total_gb": round(kib / 1024 ** 2, 1) if kib else None, "installed_gb": None, "slots": None, "slots_free": None,
              "max_gb": None, "type": None, "ecc": None, "source": None}
    if kib is None:
        unread.append({"what": "how much memory there is", "why": "/proc/meminfo couldn't be read"})
    if table:
        memory.update(installed_gb=table["installed_gb"], slots=table["slots"], slots_free=table["free"], max_gb=table["max_gb"],
                      type=table["type"], ecc=table["ecc"], source=table["source"])
    else:
        unread.append({"what": "memory slots, memory type and ECC",
                       "why": "the firmware gave no memory table (usual in a virtual machine)" if root_user
                       else "the firmware's memory table isn't in udev's database here, and dmidecode " + NEEDS_ROOT})
    if memory["ecc"] is None and raw.get("edac"):
        memory.update(ecc=True, source=(memory["source"] + ", " if memory["source"] else "") + "the kernel's error reporting (EDAC)")

    disks = []
    for d in hwf["disks"]:
        kind = "virtual disk" if d["name"].startswith(("vd", "xvd")) else d["kind"]     # /sys/block alone can't tell
        disks.append({"name": d["name"], "size_bytes": d["size"], "size": H.size(d["size"]), "kind": kind,
                      "rotational": kind.endswith("HDD"), "model": d["model"],
                      "removable": bool(d["removable"]) or kind.startswith("USB"), "medium": d["name"] == raw.get("medium"),
                      "holds_data": None if d["empty"] is None else not d["empty"],
                      "health": smart_verdict((raw.get("smart") or {}).get(d["name"]))})
    real = [d for d in disks if not d["medium"] and d["kind"] != "virtual disk"]
    if not disks:
        unread.append({"what": "the disks", "why": "none was found: lsblk is missing, or there is no disk"})
    elif real and not any(d["health"] for d in real):
        unread.append({"what": "each drive's own health verdict (SMART)",
                       "why": "smartctl isn't installed, or these drives don't report one" if root_user else "smartctl " + NEEDS_ROOT})

    network = []
    for n in hwf["network"]:
        top = None if n["wifi"] else parse_ethtool((raw.get("ethtool") or {}).get(n["name"]))
        name = ("usb-wifi" if n["wifi"] else "usb-ethernet") if MAC_NAME.fullmatch(n["name"]) else n["name"]
        network.append({"name": name, "wifi": n["wifi"], "connected": n["connected"], "speed_mbps": n["speed_mbps"], "max_mbps": top})
        if not n["wifi"] and not top and not n["speed_mbps"]:
            unread.append({"what": f"how fast the wired port {name} is",
                           "why": "the port reports no speed (usual for a virtual one), and ethtool isn't installed or didn't answer"
                           if n["connected"] else "no cable is connected, and ethtool isn't installed or didn't answer"})

    fw = raw.get("firmware") or {}
    firmware = {"boot": "UEFI" if fw.get("efi") else "BIOS",
                "secure_boot": None if not fw.get("efi") or fw.get("secure_boot") is None else bool(fw["secure_boot"]),
                "tpm": {"2": "2.0", "1": "1.2"}.get(fw.get("tpm"))}
    if fw.get("efi") and fw.get("secure_boot") is None:
        unread.append({"what": "whether Secure Boot is on", "why": "the firmware's SecureBoot variable couldn't be read"})

    chassis = (base.get("chassis") or "").strip()
    kind = ("virtual machine" if vm else "laptop" if hwf.get("laptop") else "mini PC" if chassis in MINI_CHASSIS
            else "server" if chassis in SERVER_CHASSIS else "desktop" if chassis in DESKTOP_CHASSIS else "computer")
    dmi = raw.get("dmi") or {}
    junk = ("to be filled by o.e.m.", "system product name", "system manufacturer", "default string", "not specified", "none")
    model = " ".join(x for x in (dmi.get("sys_vendor"), dmi.get("product_name")) if x and x.lower() not in junk)
    computer = {"kind": kind, "model": model or None, "virtual_machine": vm or None}

    spinning = sum(1 for d in disks if d["rotational"] and not d["medium"] and not d["removable"])
    separate = _discrete(gpus, cpu.get("vendor"))
    power = {"class": None, "estimate": True, "from": [], "measured_w": raw.get("rapl_w")}
    if not vm:
        score = {"laptop": 0, "mini PC": 0, "server": 2}.get(kind, 1) + (1 if separate else 0) + (1 if spinning >= 3 else 0)
        power["class"] = ("low", "medium", "high")[min(score, 2)]
        power["from"] = ["a " + kind, f"{separate} separate graphics card{'s' if separate != 1 else ''}" if separate else "no separate graphics card",
                         f"{spinning} spinning disk{'s' if spinning != 1 else ''}" if spinning else "no spinning disk"]
        if raw.get("rapl") and not root_user:
            unread.append({"what": "the processor's measured power", "why": "its power counter (RAPL) " + NEEDS_ROOT})

    facts = {"computer": computer, "processor": processor, "memory": memory, "disks": disks, "storage": storage_plan(disks),
             "graphics": [{k: g.get(k) for k in ("vendor", "model", "driver", "ready", "state", "vram_gib")} for g in gpus],
             "network": network, "firmware": firmware, "power": power, "privileged": root_user, "live": bool(raw.get("live")),
             "unread": unread}
    if raw.get("identifiers"):
        facts["identifiers"] = raw["identifiers"]
    return facts


def budget_hardware(facts):
    """The facts as the catalogue's hw: {cpu, ram_gb, disk_gb, gpu, gpu_vram_gb, gpu_name}, counted
    the way the installer's meter counts them (provision.hardware, localprovision.detect): the
    processor's threads, MemTotal in GiB to one decimal, every disk but the medium in whole GB,
    and a graphics card only once its driver works (hardware.legacy)."""
    kind, vram = H.legacy({"gpus": facts["graphics"]})
    card = next((g for g in facts["graphics"] if g["ready"] and g["vendor"].lower() == kind), {})
    return {"cpu": facts["processor"]["threads"] or 1, "ram_gb": facts["memory"]["total_gb"],
            "disk_gb": sum(d["size_bytes"] for d in facts["disks"] if not d["medium"]) // 10 ** 9,
            "gpu": False if kind == "none" else kind, "gpu_vram_gb": round(vram, 1) if kind != "none" else 0,
            "gpu_name": card.get("model") or ""}


# ---------------------------------------------------------------- the verdict
def _short(note):
    """A budget note without its installer advice ("Untick something, or add memory.")."""
    return re.sub(r"\s*Untick something, or add (memory|a disk)\.$", "", note or "")


def cause(reason):
    """Which limit a provcatalog sentence is about: memory, disk, graphics, processor, conflict."""
    for name, words in (("graphics", ("graphics", " card")), ("memory", ("of memory", "Memory ")), ("disk", ("of disk",)),
                        ("processor", ("processor cores",)), ("conflict", ("can't run on the same server",))):
        if any(w in reason for w in words):
            return name
    return "other" if reason else None


def judge(hw, path=None):
    """Every role and every catalogue item against this hardware, through provcatalog alone:
    {roles: [{id, name, fit, reason, cause, items, left_out, budget}], items: [{id, name, group,
    fit, reason, cause, with, budget}], groups}. fit is "yes", "tradeoff" or "no"; reason is
    provcatalog's own sentence, and cause names the limit it is about."""
    catalogue = PC.load(path)
    everywhere = {it["id"] for it in catalogue if set(it["roles"]) >= set(PC.ROLES)}
    items = []
    for it in catalogue:
        ids, added = PC.resolve([it["id"]], path)
        b = PC.budget(ids, hw, path)
        why = PC.fits_item(it, hw)
        fit, reason = ("no", why) if why else ("no", _short(b["notes"][0])) if not b["fits"] else \
            ("tradeoff", _short(b["notes"][0])) if b["notes"] else ("yes", "")
        items.append({"id": it["id"], "name": it["name"], "group": it["group"], "fit": fit, "reason": reason,
                      "cause": cause(reason), "with": added,
                      "budget": {k: b[k] for k in ("cpu", "ram_gb", "disk_gb")}})
    roles = []
    for rid in PC.ROLES:
        ticks = [it for it in catalogue if rid in it["roles"] and it["default"] and LAB in it["lab"]]
        out = [(it, PC.fits_item(it, hw)) for it in ticks]
        out = [(it, why) for it, why in out if why]
        ids = PC.recommend([rid], hw, lab=LAB, path=path)
        b = PC.budget(ids, hw, path)
        own = [it["id"] for it in ticks if it["id"] not in everywhere]        # what makes it this role
        names = ", ".join(it["name"] for it, _ in out)
        if not b["fits"]:
            fit, reason = "no", _short(b["notes"][0])
        elif own and all(i in {it["id"] for it, _ in out} for i in own):
            fit, reason = "no", out[0][1]
        elif out:
            fit, reason = "tradeoff", f"without {names}: {out[0][1]}"
        elif b["notes"]:
            fit, reason = "tradeoff", _short(b["notes"][0])
        else:
            fit, reason = "yes", ""
        roles.append({"id": rid, "name": ROLE_NAMES[rid], "fit": fit, "reason": reason, "cause": cause(reason), "items": ids,
                      "left_out": [it["id"] for it, _ in out], "budget": b})
    return {"roles": roles, "items": items, "groups": [{"id": g["id"], "name": g["name"]} for g in PC.groups(path)]}


def cautions(facts):
    """What holds for anything this machine runs: [{id, text}], from the facts alone."""
    out = []
    add = lambda cid, text: out.append({"id": cid, "text": text})                     # noqa: E731
    disks = [d for d in facts["disks"] if not d["medium"]]
    plan = facts["storage"]
    system = next((d for d in disks if d["name"] == plan["system"]), None)
    if facts["computer"]["virtual_machine"]:
        add("virtual-machine", "This is a virtual machine: the scan sees what its host gives it, not the computer "
                               "underneath. Run it on the computer itself, from Field Kit, for a real answer.")
    for d in disks:
        if d["health"] == "failing":
            add("failing-disk", f"The {d['size']} {d['kind']} ({d['name']}) says it is failing: don't trust it with anything you'd miss.")
    if system and system["rotational"]:
        add("spinning-system", "The system would run from a spinning disk: everything works, but apps start slowly and updates take longer.")
    if len(plan["layouts"]) == 1 and plan["layouts"][0]["id"] == "one-disk" and not facts["computer"]["virtual_machine"]:
        add("one-disk", "One disk holds the system and your data: nothing protects them if it fails. Back up to another machine or a USB drive.")
    if any(d["holds_data"] for d in disks):
        add("holds-data", "The disks hold data now. Installing erases the disk you choose: copy off anything you need first.")
    nics = facts["network"]
    wired = [n for n in nics if not n["wifi"]]
    if nics and not wired:
        add("wifi-only", "No wired network port was found. A server on Wi-Fi is slower and drops out more: use a cable where you can.")
    elif wired and not any(n["connected"] for n in wired) and any(n["wifi"] and n["connected"] for n in nics):
        add("wifi-connected", "Only Wi-Fi is connected. A network cable is steadier for a server.")
    slow = [n for n in wired if n["connected"] and n["speed_mbps"] and n["speed_mbps"] < 1000]
    if slow and not any(n["connected"] and (n["speed_mbps"] or 0) >= 1000 for n in wired):
        top = slow[0]["max_mbps"]
        add("slow-link", f"The wired link runs at {H.speed_text(slow[0]['speed_mbps'])}"
                         + (f", and the port can do {H.speed_text(top)}: check the cable and the switch." if top and top > slow[0]["speed_mbps"]
                            else ": copying files and backups will be slow."))
    if facts["computer"]["kind"] == "laptop":
        add("laptop", "A laptop: keep it plugged in, and set it to stay on with the lid closed.")
    if not facts["processor"]["video"]["likely"] and not facts["computer"]["virtual_machine"]:
        add("no-hardware-video", "No hardware video was found: a media server converts video with the processor alone, "
                                 "which keeps it busy while someone watches.")
    if facts["processor"]["level"] == "x86-64-v1":
        add("old-processor", "This processor lacks instructions (SSE4.2) that some apps' containers are built for: some may not start.")
    waiting = [g for g in facts["graphics"] if g["vendor"] in ("NVIDIA", "AMD") and not g["ready"]]
    if waiting and not any(g["ready"] and g["vendor"] in ("NVIDIA", "AMD") for g in facts["graphics"]):
        g = waiting[0]
        add("graphics-driver", f"The {g['vendor']} {g['model']} isn't ready here ({g['state']}), so the AI items are judged "
                               "without it. Once bromigOS Server is installed with its driver, run the scan again.")
    return out


def fatal(facts):
    """Why bromigOS can't run here at all, or None."""
    arch = facts["processor"]["arch"]
    if arch in ("x86", "arm64"):
        return ("bromigOS is built for 64-bit Intel and AMD processors (x86-64); this one is "
                + ("32-bit only." if arch == "x86" else "an ARM processor."))
    return None


def _nominal(memory):
    """The memory installed, in GB: the firmware's figure, else the next standard size up from
    what the kernel sees (the kernel always sees a little less than is installed)."""
    if memory["installed_gb"]:
        return memory["installed_gb"]
    if memory["total_gb"] is None:
        return None
    return next((s for s in STANDARD_MEMORY if s >= memory["total_gb"]), memory["total_gb"])


def _gained(before, after):
    """(role names, item names) that don't fit before and do after."""
    def names(key):
        was = {x["id"] for x in before[key] if x["fit"] == "no"}
        return [x["name"] for x in after[key] if x["id"] in was and x["fit"] != "no"]
    return names("roles"), names("items")


def _listed(names, most=5):
    """Names as a phrase: "a, b and c", or the first few "and N more"."""
    if len(names) > most:
        return ", ".join(names[:most]) + f" and {len(names) - most} more"
    return ", ".join(names[:-1]) + (" and " if len(names) > 1 else "") + names[-1] if names else ""


def upgrades(facts, hw, verdict, path=None):
    """Up to three changes that would change the answer, smallest change first, each tried
    against the same catalogue logic: [{id, title, words, roles, items}]. No brands, no prices."""
    out = []
    vm = bool(facts["computer"]["virtual_machine"])
    memory = facts["memory"]
    now = _nominal(memory)
    if now is not None:
        for step in MEMORY_STEPS:
            if step <= now or (memory["max_gb"] and step > memory["max_gb"]):
                continue
            after = judge(dict(hw, ram_gb=round(hw["ram_gb"] + step - now, 1)), path)
            roles, items = _gained(verdict, after)
            if not roles and not items:
                continue
            words = []
            if roles:
                words.append(f"The {_listed(roles)} role{'s' if len(roles) > 1 else ''} would fit.")
            if items:
                words.append(f"{_listed(items)} would fit.")
            if memory["slots"] and not vm:
                words.append(f"{memory['slots_free']} of {memory['slots']} memory slots {'is' if memory['slots_free'] == 1 else 'are'} free."
                             if memory["slots_free"] else "Every memory slot is full, so modules would be replaced.")
            if memory["type"] and not vm:
                words.append(f"It takes {memory['type']} memory.")
            out.append({"id": "memory", "title": f"More memory: {step} GB in all", "words": " ".join(words), "roles": roles, "items": items})
            break
    held = {c["id"] for c in cautions(facts)}
    if "spinning-system" in held:
        out.append({"id": "system-ssd", "title": "An SSD for the system",
                    "words": "Apps start faster and updates finish sooner. The spinning disk stays, as the data disk.", "roles": [], "items": []})
    after = judge(dict(hw, disk_gb=hw["disk_gb"] + 4000), path)
    roles, items = _gained(verdict, after)
    if roles or items:
        out.append({"id": "more-disk", "title": "A bigger or a second disk",
                    "words": f"{_listed(roles + items)} would fit.", "roles": roles, "items": items})
    elif "one-disk" in held:
        out.append({"id": "second-disk", "title": "A second disk",
                    "words": "With two data disks the installer can keep two copies, so one disk can fail without losing anything.",
                    "roles": [], "items": []})
    if "wifi-only" in held:
        out.append({"id": "wired-network", "title": "A wired network port",
                    "words": "A network adapter and a cable make the server steadier and faster to reach than Wi-Fi.", "roles": [], "items": []})
    if not hw["gpu"] and not vm:
        after = judge(dict(hw, gpu=True), path)
        roles, items = _gained(verdict, after)
        if items:
            out.append({"id": "graphics-card", "title": "A graphics card the AI apps can use (NVIDIA or AMD)",
                        "words": f"{_listed(items)} would fit.", "roles": roles, "items": items})
    return out[:3]


def next_step(facts, hw, verdict, path=None):
    """The roles to install with: every role that fits, household roles first, for as long as
    they still fit together: {roles, installer_roles, provision, budget, words}."""
    fits = {r["id"] for r in verdict["roles"] if r["fit"] != "no"}
    chosen = []
    for rid in NEXT_ORDER:
        if rid in fits and PC.budget(PC.recommend(chosen + [rid], hw, lab=LAB, path=path), hw, path)["fits"]:
            chosen.append(rid)
    if not chosen and "base" in fits:
        chosen = ["base"]
    if not chosen:
        return {"roles": [], "installer_roles": [], "provision": [], "budget": None,
                "words": "bromigOS Server's apps don't fit this computer as it is."}
    ids = PC.recommend(chosen, hw, lab=LAB, path=path)
    b = PC.budget(ids, hw, path)
    return {"roles": chosen, "installer_roles": [INSTALLER_ROLES[r] for r in chosen], "provision": ids, "budget": b,
            "words": "Install bromigOS Server as " + " + ".join(ROLE_NAMES[r] for r in chosen) + "."}


def assemble(facts, path=None):
    """The whole document from the facts: what --json prints."""
    hw = budget_hardware(facts)
    stop = fatal(facts)
    if stop:
        hw_none = dict(hw, cpu=0, ram_gb=0)
        verdict = judge(hw_none, path)
        for x in verdict["roles"] + verdict["items"]:
            x.update(fit="no", reason=stop, cause="processor")
        ups, nxt = [], {"roles": [], "installer_roles": [], "provision": [], "budget": None, "words": stop}
    else:
        verdict = judge(hw, path)
        ups = upgrades(facts, hw, verdict, path)
        nxt = next_step(facts, hw, verdict, path)
    return {"schema": SCHEMA, "scan": "salvage", "machine": facts, "budget_hardware": hw, "fatal": stop,
            "verdict": dict(verdict, cautions=cautions(facts)), "upgrades": ups, "next": nxt}


def scan(root="/", run=None, euid=None, sleep=None, clock=None, identifiers=False, path=None):
    """Read this machine and judge it."""
    return assemble(parse(collect(root, run=run, euid=euid, sleep=sleep, clock=clock, identifiers=identifiers)), path)


# ---------------------------------------------------------------- for people
def answers_toml(doc):
    """The next step's choices as an answer file for bromigOS Server's installer (docs/iso.md,
    "Answer files"). It has no disk and no password on purpose: the installer asks for those, and
    for the rest, with these roles and apps already chosen."""
    nxt = doc["next"]
    if not nxt["roles"]:
        return None
    model = doc["machine"]["processor"]["cpuinfo_model"] or ""
    lines = ["# Salvage scan's choices for this computer, for bromigOS Server's installer.",
             "# It names no disk and no password, so the installer asks for those and for the rest,",
             "# with the roles and apps below already chosen. Add disk (or disk_model) and password",
             "# under [install] to install with no questions (docs/iso.md, \"Answer files\").",
             "[install]", 'edition = "server"']
    if model and not any(c in model for c in "*?["):
        lines.append(f"cpu_model = {json.dumps(model)}        # these choices were sized for this processor's computer")
    lines += ["", "[server]", "roles = " + json.dumps(nxt["installer_roles"]), f'lab = "{LAB}"',
              "provision = " + json.dumps(nxt["provision"]), ""]
    return "\n".join(lines)


def _wrap(text, lead, width=92):
    return textwrap.wrap(text, width=width, initial_indent=lead, subsequent_indent=" " * len(lead)) or [lead.rstrip()]


def _speed(n):
    if n["speed_mbps"] and n["connected"]:
        text = H.speed_text(n["speed_mbps"])
        return text + (f" now, up to {H.speed_text(n['max_mbps'])}" if n["max_mbps"] and n["max_mbps"] > n["speed_mbps"] else "")
    return f"up to {H.speed_text(n['max_mbps'])}" if n["max_mbps"] else "speed not read"


def _by_cause(rows, hw, tight=False):
    """Items that share a limit, on one line each limit: "3.8 GB of memory isn't enough for: …".
    The figures are provcatalog.budget's own (the item, what it needs beside it, the system)."""
    groups = {}
    for i in rows:
        groups.setdefault(i["cause"], []).append(i)
    out = []
    for why, group in groups.items():
        names = _listed([i["name"] for i in group], most=99)
        if why == "memory" and hw["ram_gb"] is not None:
            figures = _listed([f"{i['name']} ({round(i['budget']['ram_gb'], 1):g} GB)" for i in group], most=99)
            out.append((f"Memory would be tight, with {hw['ram_gb']:g} GB here: " if tight else f"{hw['ram_gb']:g} GB of memory isn't enough for: ")
                       + figures + f". Each figure counts the {PC.OS_RAM_GB:g} GB the system uses and the apps it needs beside it.")
        elif why == "disk" and not tight:
            figures = _listed([f"{i['name']} ({i['budget']['disk_gb']:g} GB)" for i in group], most=99)
            out.append(f"{hw['disk_gb']:g} GB of disk isn't enough for: {figures}. A tenth of the disk is kept free.")
        elif why == "graphics" and not hw["gpu"]:
            out.append(f"No graphics card is ready for AI: {names}.")
        elif why == "processor" and tight:
            out.append(f"They'd share {hw['cpu']} processor threads, which is fine for a household and slow if all are busy at once: {names}.")
        else:
            out += [i["reason"] if i["reason"].startswith(i["name"]) else f"{i['name']}: {i['reason']}" for i in group]
    return out


def report(doc, attach_hint=True):
    """The report for people, top to bottom: the machine, what couldn't be read, what it's good
    for, what would change the answer, the next step. Plain lines, no colour."""
    m = doc["machine"]
    p, mem, fw, power = m["processor"], m["memory"], m["firmware"], m["power"]
    out = ["SALVAGE SCAN: what this computer can do as a home server",
           "Read-only: nothing on this computer was changed.", "", "THIS COMPUTER"]

    def row(label, text):
        out.extend(_wrap(text, f"  {label:<11} "))
    row("Kind", "a " + m["computer"]["kind"] + (f" ({m['computer']['model']})" if m["computer"]["model"] else ""))
    count = (f"{p['cores']} core{'s' if p['cores'] != 1 else ''}, " if p["cores"] else "") \
        + (f"{p['threads']} thread{'s' if p['threads'] != 1 else ''}" if p["threads"] else "not read")
    row("Processor", f"{p['model'] or 'unnamed'}: {count}")
    if p["level"]:
        row("", f"{p['age_words']} ({p['level']}; an estimate from its instruction sets, not a date)")
    if p["virtualisation"]:
        row("", f"virtual machines: {p['virtualisation']}")
    v = p["video"]
    if v["source"] == "vainfo" and v["likely"]:
        row("", "hardware video: decodes " + (", ".join(v["decode"]) or "nothing") + "; encodes " + (", ".join(v["encode"]) or "nothing"))
    elif v["likely"]:
        row("", f"hardware video: likely ({v['from']}); the formats weren't listed")
    else:
        row("", "hardware video: none found")
    if mem["total_gb"] is None:
        row("Memory", "not read")
    else:
        bits = [f"{mem['total_gb']:g} GB usable" + (f" ({mem['installed_gb']:g} GB installed)" if mem["installed_gb"] else "")]
        if mem["slots"]:
            bits.append(f"{mem['slots_free']} of {mem['slots']} slots free" if mem["slots_free"] else
                        "its one slot is full" if mem["slots"] == 1 else f"all {mem['slots']} slots are full")
        if mem["type"]:
            bits.append(mem["type"])
        bits.append({True: "ECC (error-correcting)", False: "no ECC reported", None: "ECC not read"}[mem["ecc"]])
        row("Memory", "; ".join(bits))
    for n, d in enumerate(m["disks"]):
        health = {"ok": "says it's healthy", "failing": "says it's FAILING", None: "health not read"}[d["health"]]
        extra = "the stick this started from, not counted" if d["medium"] else "removable" if d["removable"] else ""
        row("Disks" if n == 0 else "", f"{d['size']} {d['kind']}" + (", spinning" if d["rotational"] else "")
            + (f" ({d['model']})" if d["model"] else "") + f"; {health}" + (f"; {extra}" if extra else ""))
    if not m["disks"]:
        row("Disks", "none found")
    for layout in m["storage"]["layouts"]:
        row("", "→ " + layout["words"])
    for n, g in enumerate(m["graphics"]):
        memory = f", {g['vram_gib']:g} GB" if g["vram_gib"] else ""
        name = g["model"] if g["model"].startswith(g["vendor"]) else f"{g['vendor']} {g['model']}"
        row("Graphics" if n == 0 else "", f"{name}{memory}; {g['state']}")
    if not m["graphics"]:
        row("Graphics", "none found")
    for n, nic in enumerate(m["network"]):
        text = ("Wi-Fi" if nic["wifi"] else "wired, " + _speed(nic)) + ("; connected" if nic["connected"] else "; not connected")
        row("Network" if n == 0 else "", f"{text} ({nic['name']})")
    if not m["network"]:
        row("Network", "no network port found")
    secure = {True: "Secure Boot on", False: "Secure Boot off", None: "Secure Boot not read"}[fw["secure_boot"]] if fw["boot"] == "UEFI" \
        else "started the old way, so Secure Boot doesn't apply"
    row("Firmware", f"{fw['boot']}; {secure}; " + (f"a security chip (TPM {fw['tpm']}), which can unlock an encrypted disk by itself"
                                                  if fw["tpm"] else "no security chip (TPM) found"))
    if power["class"]:
        row("Idle power", f"{power['class']}: an estimate from the kind of computer and its parts ({', '.join(power['from'])}), not a measurement")
    else:
        row("Idle power", "not estimated: a virtual machine draws its host's power")
    if power["measured_w"]:
        row("", f"the processor alone drew {power['measured_w']:g} W over half a second while this scan ran "
                "(its own counter, RAPL); the whole computer draws more")

    if m["unread"]:
        out += ["", "COULD NOT READ"]
        for u in m["unread"]:
            out.extend(_wrap(f"{u['what']}: {u['why']}.", "  - "))

    v = doc["verdict"]
    hw = doc["budget_hardware"]
    out += ["", "WHAT IT'S GOOD FOR"]
    if doc["fatal"]:
        out.extend(_wrap("Nothing, as a bromigOS Server: " + doc["fatal"], "  "))
        return out
    out.extend(_wrap(f"Judged as the installer's \"What should this server run?\" step judges it: {hw['cpu']} processor threads, "
                     + (f"{hw['ram_gb']:g} GB of memory" if hw["ram_gb"] is not None else "memory unknown")
                     + f", {hw['disk_gb']:g} GB of disk, " + (f"{hw['gpu_name'] or 'a graphics card'} ({hw['gpu_vram_gb']:g} GB) for AI." if hw["gpu"]
                                                            else "no graphics card ready for AI."), "  "))
    out += ["", "  Roles"]
    mark = {"yes": "yes     ", "tradeoff": "yes, but", "no": "no      "}
    for r in v["roles"]:
        out.extend(_wrap(r["name"] + (f": {r['reason']}" if r["reason"] else ""), f"    {mark[r['fit']]}  "))
    total = len(v["items"])
    out += ["", f"  Apps and services ({total} in the catalogue)"]
    easy = [i for i in v["items"] if i["fit"] == "yes"]
    whole, part = [], []
    for g in v["groups"]:
        members = [i for i in v["items"] if i["group"] == g["id"]]
        fit = [i["name"] for i in members if i["fit"] == "yes"]
        rest = [i["name"] for i in members if i["fit"] != "yes"]
        if fit and not rest:
            whole.append(f"{g['name']} ({len(fit)})")
        elif fit and len(rest) < len(fit):
            part.append(f"{g['name']} except {_listed(rest, most=99)}")
        elif fit:
            part.append(f"in {g['name']}, {_listed(fit, most=99)}")
    words = "; ".join((["all of " + _listed(whole, most=99)] if whole else []) + part)
    out.extend(_wrap(f"Fit comfortably ({len(easy)}): " + (words or "none") + ".", "    "))
    for fit, title in (("tradeoff", "Fit with a trade-off"), ("no", "Don't fit")):
        rows = [i for i in v["items"] if i["fit"] == fit]
        if rows:
            out.append(f"    {title} ({len(rows)}):")
            for line in _by_cause(rows, hw, tight=fit == "tradeoff"):
                out.extend(_wrap(line, "      - "))
    if v["cautions"]:
        out += ["", "  Whatever it runs"]
        for c in v["cautions"]:
            out.extend(_wrap(c["text"], "    - "))

    if doc["upgrades"]:
        out += ["", "WHAT WOULD CHANGE THE ANSWER (smallest change first; no brands, no prices)"]
        for n, u in enumerate(doc["upgrades"], 1):
            out.extend(_wrap(f"{u['title']}. {u['words']}", f"  {n}. "))

    nxt = doc["next"]
    out += ["", "NEXT STEP"]
    out.extend(_wrap(nxt["words"], "  "))
    if nxt["roles"]:
        b = nxt["budget"]
        names = {i["id"]: i["name"] for i in v["items"]}
        out.extend(_wrap("It would run: " + ", ".join(names[i] for i in nxt["provision"]) + ".", "  "))
        out.extend(_wrap(f"Together they need about {b['ram_gb']:g} GB of memory"
                         + (f" of {hw['ram_gb']:g}" if hw["ram_gb"] is not None else "") + f" and {b['disk_gb']:g} GB of disk of {hw['disk_gb']:g}."
                         + ("".join(" " + n for n in b["notes"])), "  "))
        out += ["", "  To carry these choices into the installer:", "    bromigos hw salvage --answers salvage.toml"]
        out.extend(_wrap("BROMIGOS_ANSWERS=salvage.toml bromigos-iso-install --text" if m["live"]
                         else "then copy salvage.toml to a Field Kit stick as fieldkit/install.toml, and start this computer from it", "    "))
        out.extend(_wrap("The installer asks for the disk, the password and the rest, with these roles and apps already chosen.", "  "))
    elif doc["upgrades"]:
        out.extend(_wrap("The changes above would change that.", "  "))
    if attach_hint:
        out += ["", "  To attach this report when asking for help:  bromigos hw salvage --save salvage-report.txt"]
    return out


def redact(text, doc=None):
    """Belt and braces for a saved report: anything shaped like a MAC address is cut, and so is
    the hostname when the scan was asked to read it."""
    text = MAC.sub("[left out]", text)
    host = ((doc or {}).get("machine", {}).get("identifiers") or {}).get("hostname")
    return text.replace(host, "[left out]") if host and len(host) > 2 else text


def public(doc):
    """The document without the identifiers (serial numbers, MAC addresses, the hostname)."""
    return dict(doc, machine={k: v for k, v in doc["machine"].items() if k != "identifiers"})


def save(doc, path, identifiers=False):
    """The report and the document in one text file to attach when asking for help. Serial
    numbers, MAC addresses and the hostname are left out unless identifiers=True (and the scan
    read them)."""
    shown = doc if identifiers else public(doc)
    lines = report(shown, attach_hint=False)
    if identifiers and doc["machine"].get("identifiers"):
        ids = doc["machine"]["identifiers"]
        lines += ["", "IDENTIFIERS (asked for with --identifiers: think before you share them)", f"  hostname: {ids.get('hostname')}"]
        lines += [f"  {name}: MAC {mac}" for name, mac in (ids.get("mac") or {}).items()]
        lines += [f"  {name}: serial {serial}" for name, serial in (ids.get("disk_serial") or {}).items()]
    text = "\n".join(lines) + "\n\n---- the same, for programs (JSON; docs/salvage.md) ----\n" + json.dumps(shown, indent=1, sort_keys=True) + "\n"
    if not identifiers:
        text = redact(text, doc)
    with open(path, "w") as f:
        f.write(text)
    return path


def main(argv=None, out=print, scan_fn=scan):
    ap = argparse.ArgumentParser(
        prog="bromigos hw salvage",
        description="Salvage scan: what this computer can do as a home server. It reads the processor, memory, disks, "
                    "graphics, network and firmware (read-only, a few seconds), then judges every role and app in "
                    "bromigOS Server's catalogue with the installer's own budget logic.",
        epilog="Without administrator rights it can't read the drives' health verdicts or the processor's power counter, "
               "and it says so. docs/salvage.md has every probe, every rule and the JSON's schema.")
    ap.add_argument("--json", action="store_true", help="print the JSON document (schema in docs/salvage.md)")
    ap.add_argument("--save", metavar="FILE", help="also write the report and the JSON to FILE, to attach when asking for help; "
                                                   "serial numbers, MAC addresses and the hostname are left out")
    ap.add_argument("--answers", metavar="FILE", help="also write the next step's choices to FILE, as an answer file for "
                                                      "bromigOS Server's installer (it still asks for the disk and the password)")
    ap.add_argument("--identifiers", action="store_true", help="read disk serial numbers, MAC addresses and the hostname too, "
                                                               "and keep them in --json and --save (off by default)")
    a = ap.parse_args(argv)
    try:
        doc = scan_fn(identifiers=a.identifiers)
    except FileNotFoundError as e:
        print(f"bromigos hw salvage: {e}. It comes with the bromigos-lab package.", file=sys.stderr)
        return 1
    out(json.dumps(doc, indent=1, sort_keys=True) if a.json else "\n".join(report(doc)))
    notes = []
    if a.save:
        notes.append(f"Saved the report to {save(doc, a.save, identifiers=a.identifiers)}.")
    if a.answers:
        text = answers_toml(doc)
        if text:
            with open(a.answers, "w") as f:
                f.write(text)
            notes.append(f"Saved the installer's answer file to {a.answers}.")
        else:
            notes.append("No answer file was written: nothing in the catalogue fits this computer as it is.")
    for line in notes:
        print(line, file=sys.stderr if a.json else sys.stdout)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
