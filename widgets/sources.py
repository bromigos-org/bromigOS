"""Real readings for the widgets. Everything here is cheap and non-blocking for the
GTK main loop: local counters are read inline (psutil, /proc, NVML via ctypes),
network-bound work (pings, the Lab snapshot) runs on daemon threads."""
import ctypes
import json
import os
import platform
import socket
import ssl
import sys
import subprocess
import threading
import time
import urllib.request
from collections import deque

import psutil

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.realpath(__file__))), "lib"))
import bromigos_private as PRIV  # noqa: E402  the operator's private values (empty on a fresh clone)


# ------------------------------------------------------------------ NVML (no nvidia-smi fork)
class _Util(ctypes.Structure):
    _fields_ = [("gpu", ctypes.c_uint), ("memory", ctypes.c_uint)]


class _Mem(ctypes.Structure):
    _fields_ = [("total", ctypes.c_ulonglong), ("free", ctypes.c_ulonglong), ("used", ctypes.c_ulonglong)]


class GPU:
    def __init__(self):
        self.ok = False
        self.name = ""
        try:
            self.lib = ctypes.CDLL("libnvidia-ml.so.1")
            if self.lib.nvmlInit_v2() != 0:
                return
            self.h = ctypes.c_void_p()
            if self.lib.nvmlDeviceGetHandleByIndex_v2(0, ctypes.byref(self.h)) != 0:
                return
            buf = ctypes.create_string_buffer(96)
            self.lib.nvmlDeviceGetName(self.h, buf, 96)
            self.name = buf.value.decode().replace("NVIDIA ", "").replace("GeForce ", "")
            self.ok = True
        except OSError:
            pass

    def read(self):
        if not self.ok:
            return None
        u, m, t, p = _Util(), _Mem(), ctypes.c_uint(), ctypes.c_uint()
        self.lib.nvmlDeviceGetUtilizationRates(self.h, ctypes.byref(u))
        self.lib.nvmlDeviceGetMemoryInfo(self.h, ctypes.byref(m))
        self.lib.nvmlDeviceGetTemperature(self.h, 0, ctypes.byref(t))
        self.lib.nvmlDeviceGetPowerUsage(self.h, ctypes.byref(p))
        return {"util": u.gpu, "vram_used": m.used, "vram_total": m.total,
                "temp": t.value, "watts": p.value / 1000}


# ------------------------------------------------------------------ system
class System:
    """CPU per core (+ a waterfall history), memory, GPU, temperatures, uptime."""

    def __init__(self, history=180):
        self.cores = psutil.cpu_count() or 1
        self.history = deque(maxlen=history)          # per-core % samples, oldest first
        self.gpu = GPU()
        psutil.cpu_percent(percpu=True)
        self.host = socket.gethostname()
        self.kernel = platform.release()
        self.os = _os_name()
        self.boot = psutil.boot_time()
        self.session_start = _session_start()
        self._temps_at = 0
        self.temps = {}
        self.sample()

    def sample(self):
        per = psutil.cpu_percent(percpu=True)
        self.per = per
        self.total = sum(per) / len(per)
        self.history.append(per)
        self.mem = psutil.virtual_memory()
        self.swap = psutil.swap_memory()
        self.load = os.getloadavg()
        self.g = self.gpu.read()
        now = time.time()
        if now - self._temps_at > 4:                 # hwmon walk: every 4 s is plenty
            self._temps_at = now
            self.temps = _temps()
        return self


def _os_name():
    try:
        with open("/etc/os-release") as f:
            kv = dict(line.rstrip().split("=", 1) for line in f if "=" in line)
        return kv.get("NAME", "Linux").strip('"')
    except OSError:
        return "Linux"


def _session_start():
    """Start time of the compositor process = this login session."""
    for p in psutil.process_iter(["name", "create_time"]):
        if p.info["name"] in ("Hyprland", ".Hyprland-wrapped"):
            return p.info["create_time"]
    return psutil.boot_time()


_TEMP_FILES = None


def _temp_files():
    """Locate the few hwmon inputs we show, once. Reading only these avoids walking
    every chip (psutil.sensors_temperatures() also polls slow ACPI/EC sensors)."""
    out = {}
    base = "/sys/class/hwmon"
    try:
        for h in sorted(os.listdir(base)):
            d = os.path.join(base, h)
            try:
                with open(os.path.join(d, "name")) as f:
                    name = f.read().strip()
            except OSError:
                continue
            if name in ("k10temp", "coretemp") and "CPU" not in out:
                out["CPU"] = os.path.join(d, "temp1_input")
            elif name == "nvme" and "NVME" not in out:
                out["NVME"] = os.path.join(d, "temp1_input")
    except OSError:
        pass
    return out


def _temps():
    global _TEMP_FILES
    if _TEMP_FILES is None:
        _TEMP_FILES = _temp_files()
    out = {}
    for k, path in _TEMP_FILES.items():
        try:
            with open(path) as f:
                out[k] = int(f.read()) / 1000
        except (OSError, ValueError):
            pass
    return out


# ------------------------------------------------------------------ network
def default_iface():
    try:
        with open("/proc/net/route") as f:
            for line in f.readlines()[1:]:
                p = line.split()
                if p[1] == "00000000":
                    gw = socket.inet_ntoa(int(p[2], 16).to_bytes(4, "little"))
                    return p[0], gw
    except OSError:
        pass
    return None, None


class Net:
    def __init__(self, history=120):
        self.rx_hist = deque([0.0] * history, maxlen=history)
        self.tx_hist = deque([0.0] * history, maxlen=history)
        self.iface, self.gw = default_iface()
        self._last = None
        self.rx = self.tx = 0.0
        self.addr = None
        self.signal = None

    def sample(self):
        self.iface, self.gw = default_iface()
        now = time.monotonic()
        c = psutil.net_io_counters(pernic=True).get(self.iface) if self.iface else None
        if c and self._last:
            dt = now - self._last[0]
            self.rx = max(0.0, (c.bytes_recv - self._last[1]) / dt)
            self.tx = max(0.0, (c.bytes_sent - self._last[2]) / dt)
        else:
            self.rx = self.tx = 0.0
        if c:
            self._last = (now, c.bytes_recv, c.bytes_sent)
        self.rx_hist.append(self.rx)
        self.tx_hist.append(self.tx)
        self.addr = None
        if self.iface:
            for a in psutil.net_if_addrs().get(self.iface, []):
                if a.family == socket.AF_INET:
                    self.addr = a.address
        self.signal = _wifi_dbm(self.iface)
        return self


def _wifi_dbm(iface):
    try:
        with open("/proc/net/wireless") as f:
            for line in f.readlines()[2:]:
                p = line.split()
                if p[0].rstrip(":") == iface:
                    return float(p[3].rstrip("."))
    except (OSError, IndexError, ValueError):
        pass
    return None


class Pinger(threading.Thread):
    """ICMP round-trips to a few named hosts every `every` seconds (ping(8), non-blocking)."""

    def __init__(self, targets, every=6):
        super().__init__(daemon=True)
        self.targets = targets                         # [(label, host-or-None-for-gateway)]
        self.every = every
        self.rtt = {label: None for label, _ in targets}
        self.updated = 0

    def run(self):
        while True:
            _, gw = default_iface()
            for label, host in self.targets:
                h = host or gw
                self.rtt[label] = _ping(h) if h else None
            self.updated = time.time()
            time.sleep(self.every)


def _ping(host):
    try:
        out = subprocess.run(["ping", "-c1", "-n", "-W1", host], capture_output=True, text=True, timeout=3).stdout
        for part in out.split():
            if part.startswith("time="):
                return float(part[5:])
    except (subprocess.TimeoutExpired, OSError, ValueError):
        pass
    return None


# ------------------------------------------------------------------ storage
SKIP_FS = {"tmpfs", "devtmpfs", "overlay", "squashfs", "efivarfs", "proc", "sysfs", "ramfs", "fuse.portal"}


def storage():
    """Every real mount (one per device; btrfs subvolumes collapse onto '/'), then
    any sizeable unmounted filesystem from lsblk as 'not mounted'."""
    seen, out = {}, []
    for p in psutil.disk_partitions(all=False):
        if p.fstype in SKIP_FS or "/snap/" in p.mountpoint or p.device.startswith("/dev/loop"):
            continue
        if p.device in seen and len(seen[p.device]) <= len(p.mountpoint):
            continue
        seen[p.device] = p.mountpoint
    for dev, mnt in seen.items():
        try:
            u = psutil.disk_usage(mnt)
        except OSError:
            continue
        out.append({"mount": mnt, "device": os.path.basename(dev), "size": u.total, "used": u.used,
                    "free": u.free, "pct": u.percent, "fstype": _fstype(dev), "mounted": True})
    try:
        j = json.loads(subprocess.run(["lsblk", "-J", "-b", "-o", "NAME,SIZE,FSTYPE,MOUNTPOINTS,LABEL"],
                                      capture_output=True, text=True, timeout=3).stdout)
        for d in j["blockdevices"]:
            for c in d.get("children", []) or []:
                mps = [m for m in (c.get("mountpoints") or []) if m]
                if not mps and c.get("fstype") in ("ntfs", "ext4", "btrfs", "xfs", "exfat", "vfat") \
                        and int(c.get("size") or 0) > 20e9:
                    out.append({"mount": None, "device": c["name"], "size": int(c["size"]), "used": None,
                                "free": None, "pct": None, "fstype": c["fstype"], "label": c.get("label"),
                                "mounted": False})
    except (OSError, ValueError, subprocess.TimeoutExpired, KeyError):
        pass
    out.sort(key=lambda m: (not m["mounted"], m["mount"] != "/", -(m["size"] or 0)))
    return out


def _fstype(dev):
    for p in psutil.disk_partitions(all=False):
        if p.device == dev:
            return p.fstype
    return ""


def http_alive(url, timeout=4):
    """Any answer below 500 counts as up (the same rule the Lab uses)."""
    try:
        req = urllib.request.Request(url, method="HEAD")
        with urllib.request.urlopen(req, timeout=timeout, context=ssl.create_default_context()) as r:
            return r.status < 500
    except urllib.error.HTTPError as e:
        return e.code < 500
    except OSError:
        return False


# ------------------------------------------------------------------ for the larger size classes
# Read only while a panel is drawn at a size that shows them (a panel's tick() asks).
_procs = {}


def top_processes(n=6):
    """The busiest processes now: [{"pid", "name", "cpu" (% of one CPU), "mem" (bytes)}].
    The first call primes each process's counter; from the second, cpu is per interval."""
    seen = set()
    rows = []
    for p in psutil.process_iter(["pid", "name"]):
        pid = p.info["pid"]
        seen.add(pid)
        proc = _procs.setdefault(pid, p)
        try:
            cpu = proc.cpu_percent(None)
            mem = proc.memory_info().rss
        except (psutil.Error, OSError):
            continue
        rows.append({"pid": pid, "name": p.info["name"] or "?", "cpu": cpu, "mem": mem})
    for pid in list(_procs):
        if pid not in seen:
            del _procs[pid]
    rows.sort(key=lambda r: (-r["cpu"], -r["mem"]))
    return rows[:n]


class DiskIO:
    """Read and write rates over all disks, with a history (bytes a second)."""

    def __init__(self, history=120):
        self.read_hist = deque([0.0] * history, maxlen=history)
        self.write_hist = deque([0.0] * history, maxlen=history)
        self.read = self.write = 0.0
        self._last = None

    def sample(self):
        c = psutil.disk_io_counters()
        now = time.monotonic()
        if c is None:
            return self
        if self._last:
            dt = max(1e-3, now - self._last[0])
            self.read = max(0.0, (c.read_bytes - self._last[1]) / dt)
            self.write = max(0.0, (c.write_bytes - self._last[2]) / dt)
        self._last = (now, c.read_bytes, c.write_bytes)
        self.read_hist.append(self.read)
        self.write_hist.append(self.write)
        return self


def connections(n=8):
    """Who this machine is talking to: [{"host", "count", "procs"}], busiest first (TCP
    connections that are established, by remote address)."""
    by = {}
    try:
        conns = psutil.net_connections(kind="inet")
    except (psutil.Error, OSError):
        return []
    names = {}
    for c in conns:
        if c.status != psutil.CONN_ESTABLISHED or not c.raddr:
            continue
        host = c.raddr.ip
        if host.startswith(("127.", "::1")):
            continue
        e = by.setdefault(host, {"host": host, "count": 0, "procs": set()})
        e["count"] += 1
        if c.pid:
            if c.pid not in names:
                try:
                    names[c.pid] = psutil.Process(c.pid).name()
                except (psutil.Error, OSError):
                    names[c.pid] = None
            if names[c.pid]:
                e["procs"].add(names[c.pid])
    rows = sorted(by.values(), key=lambda e: -e["count"])[:n]
    for e in rows:
        e["procs"] = sorted(e["procs"])
    return rows


def interfaces():
    """Every network interface but loopback: [{"name", "up", "speed" (Mb/s or 0),
    "addrs" (IPv4 and IPv6, without link-local), "mac"}]."""
    out = []
    try:
        stats, addrs = psutil.net_if_stats(), psutil.net_if_addrs()
    except (psutil.Error, OSError):
        return out
    for name, st in sorted(stats.items()):
        if name == "lo":
            continue
        ips, mac = [], None
        for a in addrs.get(name, []):
            if a.family == socket.AF_INET or (a.family == socket.AF_INET6 and not a.address.startswith("fe80")):
                ips.append(a.address.split("%")[0])
            elif a.family == psutil.AF_LINK:
                mac = a.address
        out.append({"name": name, "up": bool(st.isup), "speed": int(st.speed or 0), "addrs": ips, "mac": mac})
    return out


# ------------------------------------------------------------------ formatting
def human(n, unit="B", base=1024.0, digits=1):
    if n is None:
        return "-"
    for u in ("", "K", "M", "G", "T", "P"):
        if abs(n) < base:
            return f"{n:.{digits if u else 0}f} {u}{unit}".replace(" B", " B")
        n /= base
    return f"{n:.1f} E{unit}"


def rate(n):
    return human(n, "B/s")


def duration(sec):
    sec = int(sec)
    d, sec = divmod(sec, 86400)
    h, sec = divmod(sec, 3600)
    m, sec = divmod(sec, 60)
    if d:
        return f"{d}d {h}h"
    if h:
        return f"{h}h {m:02d}m"
    if m:
        return f"{m}m"
    return f"{sec}s"
