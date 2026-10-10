"""GPU: the graphics card's load, video memory, temperature, power and what uses it.

NVIDIA through NVML (libnvidia-ml, which the driver installs; no nvidia-smi fork), with
each process's memory and share of the GPU. AMD through the amdgpu driver's files in
/sys/class/drm (load, VRAM, temperature, power; no per-process use). Intel's i915 and xe
drivers give only the clock there, so the panel says so. Large adds ten minutes of
history for each reading.
"""
import collections
import ctypes
import glob
import os
import sys
import time

sys.path.append(os.path.dirname(os.path.realpath(__file__)))   # after the standard library
import _kit as K  # noqa: E402

import draw as D  # noqa: E402
import sources as S  # noqa: E402

HISTORY = 300                     # samples, one every 2 s: ten minutes


# ------------------------------------------------------------------ NVIDIA (NVML)
class _Util(ctypes.Structure):
    _fields_ = [("gpu", ctypes.c_uint), ("memory", ctypes.c_uint)]


class _Mem(ctypes.Structure):
    _fields_ = [("total", ctypes.c_ulonglong), ("free", ctypes.c_ulonglong), ("used", ctypes.c_ulonglong)]


class _Proc(ctypes.Structure):          # nvmlProcessInfo_v2 (the _v3 calls take the same shape)
    _fields_ = [("pid", ctypes.c_uint), ("usedGpuMemory", ctypes.c_ulonglong),
                ("gpuInstanceId", ctypes.c_uint), ("computeInstanceId", ctypes.c_uint)]


class _ProcUtil(ctypes.Structure):      # nvmlProcessUtilizationSample_t
    _fields_ = [("pid", ctypes.c_uint), ("timeStamp", ctypes.c_ulonglong), ("smUtil", ctypes.c_uint),
                ("memUtil", ctypes.c_uint), ("encUtil", ctypes.c_uint), ("decUtil", ctypes.c_uint)]


NOT_AVAILABLE = 0xFFFFFFFFFFFFFFFF      # NVML's "unknown" for a process's memory


class NvidiaReader:
    vendor = "NVIDIA"

    def __init__(self):
        self.ok, self.devices, self.driver = False, [], ""
        try:
            self.lib = ctypes.CDLL("libnvidia-ml.so.1")
        except OSError:
            return
        if self.lib.nvmlInit_v2() != 0:
            return
        n = ctypes.c_uint()
        if self.lib.nvmlDeviceGetCount_v2(ctypes.byref(n)) != 0:
            return
        buf = ctypes.create_string_buffer(96)
        if self.lib.nvmlSystemGetDriverVersion(buf, 96) == 0:
            self.driver = buf.value.decode()
        for i in range(n.value):
            h = ctypes.c_void_p()
            if self.lib.nvmlDeviceGetHandleByIndex_v2(i, ctypes.byref(h)) != 0:
                continue
            self.lib.nvmlDeviceGetName(h, buf, 96)
            self.devices.append((h, buf.value.decode()))
        self.ok = bool(self.devices)
        self._last_ts = {}

    def _uint(self, fn, h, *args):
        v = ctypes.c_uint()
        try:
            return v.value if getattr(self.lib, fn)(h, *args, ctypes.byref(v)) == 0 else None
        except AttributeError:
            return None

    def read(self, procs=True):
        out = []
        for i, (h, name) in enumerate(self.devices):
            u, m = _Util(), _Mem()
            util = u.gpu if self.lib.nvmlDeviceGetUtilizationRates(h, ctypes.byref(u)) == 0 else None
            mem = self.lib.nvmlDeviceGetMemoryInfo(h, ctypes.byref(m)) == 0
            power = self._uint("nvmlDeviceGetPowerUsage", h)
            limit = self._uint("nvmlDeviceGetEnforcedPowerLimit", h)
            g = {"index": i, "vendor": self.vendor, "name": short_name(name), "driver": self.driver,
                 "util": util, "mem_util": u.memory if util is not None else None,
                 "vram_used": m.used if mem else None, "vram_total": m.total if mem else None,
                 "temp": self._uint("nvmlDeviceGetTemperature", h, 0),
                 "watts": power / 1000 if power is not None else None,
                 "watts_limit": limit / 1000 if limit else None,
                 "fan": self._uint("nvmlDeviceGetFanSpeed", h),
                 "clock": self._uint("nvmlDeviceGetClockInfo", h, 0),
                 "mem_clock": self._uint("nvmlDeviceGetClockInfo", h, 2),
                 "procs": self._procs(h) if procs else None, "note": None}
            out.append(g)
        return out

    def _procs(self, h):
        rows = {}
        for fn in ("nvmlDeviceGetComputeRunningProcesses_v3", "nvmlDeviceGetGraphicsRunningProcesses_v3",
                   "nvmlDeviceGetComputeRunningProcesses_v2", "nvmlDeviceGetGraphicsRunningProcesses_v2"):
            f = getattr(self.lib, fn, None)
            if f is None or (fn.endswith("_v2") and rows):
                continue
            kind = "compute" if "Compute" in fn else "graphics"
            n = ctypes.c_uint(64)
            arr = (_Proc * 64)()
            if f(h, ctypes.byref(n), arr) != 0:
                continue
            for p in arr[:n.value]:
                r = rows.setdefault(p.pid, {"pid": p.pid, "vram": 0, "kinds": set(), "sm": None})
                if p.usedGpuMemory != NOT_AVAILABLE:
                    r["vram"] = max(r["vram"], p.usedGpuMemory)
                r["kinds"].add(kind)
        # each process's share of the GPU since the last read (NVML keeps a few seconds of samples)
        f = getattr(self.lib, "nvmlDeviceGetProcessUtilization", None)
        if f is not None and rows:
            n = ctypes.c_uint(128)
            arr = (_ProcUtil * 128)()
            last = self._last_ts.get(h.value, 0)
            if f(h, arr, ctypes.byref(n), ctypes.c_ulonglong(last)) == 0:
                newest = last
                for s in arr[:n.value]:
                    if s.pid in rows:
                        rows[s.pid]["sm"] = max(rows[s.pid]["sm"] or 0, s.smUtil)
                    newest = max(newest, s.timeStamp)
                self._last_ts[h.value] = newest
        return name_procs(rows.values())


def name_procs(rows):
    import psutil
    out = []
    for r in rows:
        try:
            p = psutil.Process(r["pid"])
            name = p.name()
            cmd = " ".join(p.cmdline()[:3])
        except (psutil.Error, OSError):
            name, cmd = f"pid {r['pid']}", ""
        out.append({"pid": r["pid"], "name": name, "cmd": cmd, "vram": r.get("vram") or 0,
                    "kinds": sorted(r.get("kinds") or ()), "sm": r.get("sm")})
    out.sort(key=lambda p: (-(p["vram"] or 0), -(p["sm"] or 0)))
    return out


def short_name(name):
    return name.replace("NVIDIA ", "").replace("GeForce ", "").replace("AMD ", "").strip()


# ------------------------------------------------------------------ AMD and Intel (sysfs)
def _read(path, conv=int):
    try:
        with open(path) as f:
            return conv(f.read().strip())
    except (OSError, ValueError):
        return None


class SysfsReader:
    """amdgpu (load, VRAM, temperature, power) and i915/xe (the clock only) from
    /sys/class/drm/card*/device."""

    def __init__(self, root="/sys/class/drm"):
        self.cards = []
        for card in sorted(glob.glob(os.path.join(root, "card[0-9]*"))):
            if "-" in os.path.basename(card):
                continue
            dev = os.path.join(card, "device")
            vendor = _read(os.path.join(dev, "vendor"), lambda s: s.lower())
            if vendor == "0x1002":
                self.cards.append(("AMD", card))
            elif vendor == "0x8086":
                self.cards.append(("Intel", card))
        self.ok = bool(self.cards)

    @staticmethod
    def _hwmon(dev, name):
        for p in glob.glob(os.path.join(dev, "hwmon", "hwmon*", name)):
            return p
        return None

    def read(self, procs=True):
        out = []
        for i, (vendor, card) in enumerate(self.cards):
            dev = os.path.join(card, "device")
            name = _read(os.path.join(dev, "product_name"), str) or f"{vendor} GPU {os.path.basename(card)}"
            g = {"index": i, "vendor": vendor, "name": short_name(name), "driver": _driver(dev), "util": None,
                 "mem_util": None, "vram_used": None, "vram_total": None, "temp": None, "watts": None,
                 "watts_limit": None, "fan": None, "clock": None, "mem_clock": None, "procs": None, "note": None}
            if vendor == "AMD":
                g["util"] = _read(os.path.join(dev, "gpu_busy_percent"))
                g["mem_util"] = _read(os.path.join(dev, "mem_busy_percent"))
                g["vram_used"] = _read(os.path.join(dev, "mem_info_vram_used"))
                g["vram_total"] = _read(os.path.join(dev, "mem_info_vram_total"))
                t = self._hwmon(dev, "temp1_input")
                g["temp"] = _read(t) / 1000 if t and _read(t) is not None else None
                pw = self._hwmon(dev, "power1_average") or self._hwmon(dev, "power1_input")
                g["watts"] = _read(pw) / 1e6 if pw and _read(pw) is not None else None
                cap = self._hwmon(dev, "power1_cap")
                g["watts_limit"] = _read(cap) / 1e6 if cap and _read(cap) else None
                g["clock"] = _amd_clock(os.path.join(dev, "pp_dpm_sclk"))
                g["note"] = "amdgpu doesn't say which process uses the GPU"
            else:
                g["clock"] = (_read(os.path.join(card, "gt_cur_freq_mhz"))
                              or _read(next(iter(glob.glob(os.path.join(dev, "tile0", "gt0", "freq0", "act_freq"))), "")))
                g["note"] = "Intel's driver gives only the clock here; load needs intel_gpu_top"
            out.append(g)
        return out


def _driver(dev):
    try:
        return os.path.basename(os.readlink(os.path.join(dev, "driver")))
    except OSError:
        return ""


def _amd_clock(path):
    try:
        with open(path) as f:
            for line in f:
                if line.rstrip().endswith("*"):
                    return int("".join(ch for ch in line.split(":", 1)[1] if ch.isdigit()) or 0) or None
    except (OSError, ValueError, IndexError):
        pass
    return None


# ------------------------------------------------------------------ demo readings
class DemoReader:
    vendor, ok = "NVIDIA", True

    def __init__(self):
        self.k = 0

    def read(self, procs=True):
        self.k += 1
        G = 2 ** 30
        return [{"index": 0, "vendor": "NVIDIA", "name": "RTX 4070", "driver": "580.95.05", "util": 37, "mem_util": 21,
                 "vram_used": int(7.4 * G), "vram_total": 12 * G, "temp": 58, "watts": 118.0, "watts_limit": 200.0,
                 "fan": 41, "clock": 2475, "mem_clock": 10501, "note": None,
                 "procs": [{"pid": 4121, "name": "python3", "cmd": "python3 train.py", "vram": int(4.9 * G),
                            "kinds": ["compute"], "sm": 31},
                           {"pid": 2210, "name": "Hyprland", "cmd": "Hyprland", "vram": int(0.9 * G),
                            "kinds": ["graphics"], "sm": 3},
                           {"pid": 3302, "name": "firefox", "cmd": "firefox", "vram": int(0.7 * G),
                            "kinds": ["graphics"], "sm": 2},
                           {"pid": 3910, "name": "bromigos-live", "cmd": "bromigos-live", "vram": int(0.5 * G),
                            "kinds": ["graphics"], "sm": 1},
                           {"pid": 4402, "name": "kitty", "cmd": "kitty", "vram": int(0.1 * G),
                            "kinds": ["graphics"], "sm": 0}]}]


def demo_history(n=HISTORY):
    import math
    out = collections.deque(maxlen=HISTORY)
    for k in range(n):
        load = 30 + 25 * math.sin(k / 23.0) + 18 * max(0.0, math.sin(k / 7.0)) ** 6
        out.append({"util": max(2, min(99, load)), "vram": 0.55 + 0.07 * math.sin(k / 41.0),
                    "temp": 52 + 7 * math.sin(k / 31.0 - 0.8), "watts": 70 + 1.3 * load})
    return out


def reader():
    """The first reader that finds a GPU: NVML, else sysfs (AMD, Intel), else None."""
    if K.demo():
        return DemoReader()
    nv = NvidiaReader()
    if nv.ok:
        return nv
    sf = SysfsReader()
    return sf if sf.ok else None


# ------------------------------------------------------------------ the panel
class GpuPanel(K.KitPanel):
    name, title = "gpu", "GPU"
    description = "The graphics card: load, video memory, temperature, power, and which programs use it"
    category, reads = "system", "your GPU through NVML (NVIDIA) or the kernel (AMD, Intel)"
    width, height = 460, 300
    interval = 2.0
    sizes = {
        "compact": ((240, 120), (380, 190), (280, 140)),
        "standard": ((400, 240), (620, 380), (460, 300)),
        "wide": ((640, 200), (1100, 360), (760, 240)),
        "tall": ((380, 420), (560, 900), (420, 520)),
        "large": ((660, 480), (1200, 900), (760, 560)),
    }
    default_size = "standard"

    def __init__(self, cfg=None, wake=None):
        super().__init__(cfg, wake)
        self.r = reader()
        self.gpus = []
        self.history = demo_history() if K.demo() else collections.deque(maxlen=HISTORY)
        self.procs_at = 0.0
        self.tick()

    def tick(self):
        if not self.r:
            return
        now = time.monotonic()
        # processes cost a little more (psutil per pid): every 4 s, and only while seen
        want_procs = (now - self.drawn_at < 30) and now - self.procs_at >= 4
        try:
            got = self.r.read(procs=want_procs)
        except OSError:
            return
        if want_procs:
            self.procs_at = now
        elif self.gpus:
            for g, old in zip(got, self.gpus):
                g["procs"] = old.get("procs")
        self.gpus = got
        if got and not K.demo():
            g = got[0]
            self.history.append({"util": g["util"], "temp": g["temp"], "watts": g["watts"],
                                 "vram": (g["vram_used"] / g["vram_total"]) if g["vram_used"] and g["vram_total"] else None})

    # ---- drawing
    def draw(self, cr, w, h):
        cls = self.size_class(w, h)
        g = self.gpus[0] if self.gpus else None
        right = None
        if g:
            right = g["name"] if cls == "compact" else f"{g['name']}" + (f" · {g['driver']}" if g.get("driver") else "")
        top = D.frame(cr, w, h, self.title, right)
        if not self.r or not g:
            self.region(0, 0, w, 34, "GPU: no graphics card this panel can read")
            self.empty(cr, w, h, top, "NO GPU FOUND",
                       "No NVIDIA card answered through NVML (it needs the driver's nvidia-utils), and no AMD or "
                       "Intel card is in /sys/class/drm.")
            return
        more = f"; {len(self.gpus) - 1} more GPU(s) in this machine" if len(self.gpus) > 1 else ""
        self.region(0, 0, w, 34, f"{g['vendor']} {g['name']}" + (f", driver {g['driver']}" if g.get("driver") else "")
                    + f", read every 2 s{more}")
        x0, x1 = 16, w - 16
        if cls == "compact":
            self._compact(cr, g, x0, x1, top, h)
        elif cls == "wide":
            left = x0 + max(330, (x1 - x0) * 0.36)
            self._readouts(cr, g, x0, left - 16, top, h - 12, rows=4 if h >= 230 else 3)
            self._graphs(cr, left, x1, top, h - 14, which=("util", "vram", "temp") if w >= 900 else ("util", "vram"))
        elif cls == "large":
            mid = top + max(150, (h - top) * 0.5)
            split = x0 + max(330, (x1 - x0) * 0.36)
            self._readouts(cr, g, x0, split - 20, top, mid, rows=4)
            self._graphs(cr, split, x1, top, mid, which=("util", "vram", "temp", "watts"))
            self._procs(cr, g, x0, x1, mid + 12, h - 12, columns=True)
            if len(self.gpus) > 1:
                self._others(cr, x0, x1, h - 30)
        elif cls == "tall":
            y = self._readouts(cr, g, x0, x1, top, top + 160, rows=4)
            gb = y + 6 + max(90, (h - y) * 0.42)
            self._graphs(cr, x0, x1, y + 6, gb, which=("util", "vram", "temp", "watts") if h >= 640 else ("util", "vram"))
            self._procs(cr, g, x0, x1, gb + 14, h - 12)
        else:
            y = self._readouts(cr, g, x0, x1, top, top + 140, rows=4)
            self._procs(cr, g, x0, x1, y + 6, h - 12)

    def _compact(self, cr, g, x0, x1, top, h):
        util = g.get("util")
        if util is None:
            D.label(cr, x0, top + 4, "LOAD NOT READABLE", "amber")
            self.region(x0, top, x1 - x0, 40, g.get("note") or "This GPU's driver doesn't say how busy it is")
        else:
            col = D.level(util, 70, 90)
            tw = D.seg7(cr, x0, top + 2, max(20, min(64, h - top - 52)), f"{util:3d}", col)
            D.text(cr, x0 + tw + 6, top + 4, "%", 14, col, "bold")
            self.region(x0, top, tw + 30, 50, f"GPU load: {util}% busy over the last sample (2 s)")
        rx = x1
        bits = []
        if g.get("temp") is not None:
            bits.append((f"{g['temp']:.0f}°C", D.level(g["temp"], 75, 85), f"GPU temperature {g['temp']:.0f} °C "
                         "(amber 75, red 85)"))
        if g.get("watts") is not None:
            bits.append((f"{g['watts']:.0f} W", "soft", f"Drawing {g['watts']:.0f} W"
                         + (f" of its {g['watts_limit']:.0f} W limit" if g.get("watts_limit") else "")))
        y = top + 2
        for label, col, tip in bits:
            tw, th = D.text(cr, rx, y, label, 13, col, "semibold", align="right")
            self.region(rx - tw, y, tw, th, tip)
            y += th + 4
        if g.get("vram_total"):
            frac = g["vram_used"] / g["vram_total"]
            yb = h - 26
            D.label(cr, x0, yb - 15, f"VRAM {S.human(g['vram_used'], digits=1)} / {S.human(g['vram_total'], digits=0)}",
                    "dim", size=10)
            D.cells(cr, x0, yb + 2, x1 - x0, 8, frac, n=24)
            self.region(x0, yb - 16, x1 - x0, 28, f"Video memory in use: {S.human(g['vram_used'])} of "
                        f"{S.human(g['vram_total'])} ({frac * 100:.0f}%)")

    def _readouts(self, cr, g, x0, x1, top, bottom, rows=4):
        """The big load number and ring, then the readings beside or under it. Returns the y
        below them."""
        util = g.get("util")
        r = 34
        cx, cy = x0 + r + 4, top + r + 8
        if util is not None:
            col = D.level(util, 70, 90)
            D.ring(cr, cx, cy, r, util / 100, 6, col)
            D.text(cr, cx, cy - 11, f"{util}%", 17, col, "bold", align="center", glow=util > 0)
            D.label(cr, cx, cy + r + 10, "LOAD", "dim", size=10, align="center")
            self.region(x0, top, 2 * r + 8, 2 * r + 34, f"GPU load: {util}% busy (2 s sample)"
                        + (f"; memory controller {g['mem_util']}% busy" if g.get("mem_util") is not None else ""))
        else:
            D.ring(cr, cx, cy, r, None, 6, "static", dashed=True)
            D.label(cr, cx, cy - 7, "N/A", "static", align="center")
            self.region(x0, top, 2 * r + 8, 2 * r + 34, g.get("note") or "This driver doesn't say how busy the GPU is")
        lx = x0 + 2 * r + 28
        items = []
        if g.get("vram_total"):
            frac = g["vram_used"] / g["vram_total"]
            items.append(("VRAM", f"{S.human(g['vram_used'], digits=1)} / {S.human(g['vram_total'], digits=0)}",
                          D.level(frac, 0.8, 0.95), frac,
                          f"Video memory: {S.human(g['vram_used'])} of {S.human(g['vram_total'])} in use ({frac * 100:.0f}%)"))
        if g.get("temp") is not None:
            items.append(("TEMP", f"{g['temp']:.0f}°C" + (f" · FAN {g['fan']}%" if g.get("fan") is not None else ""),
                          D.level(g["temp"], 75, 85), None,
                          f"Temperature {g['temp']:.0f} °C (amber 75, red 85)"
                          + (f"; fan at {g['fan']}%" if g.get("fan") is not None else "")))
        if g.get("watts") is not None:
            lim = g.get("watts_limit")
            items.append(("POWER", f"{g['watts']:.0f} W" + (f" / {lim:.0f}" if lim else ""),
                          D.level(g["watts"] / lim if lim else 0, 0.85, 0.97), (g["watts"] / lim) if lim else None,
                          f"Drawing {g['watts']:.0f} W" + (f" of a {lim:.0f} W limit" if lim else "")))
        if g.get("clock"):
            items.append(("CLOCK", f"{g['clock']} MHz" + (f" · MEM {g['mem_clock']}" if g.get("mem_clock") else ""),
                          "soft", None, f"Core clock {g['clock']} MHz"
                          + (f", memory clock {g['mem_clock']} MHz" if g.get("mem_clock") else "")))
        y = top + 2
        step = 26
        for name, val, col, frac, tip in items[:rows]:
            lw = D.label(cr, lx, y, name, "dim", size=10)[0]
            if D.layout(cr, val, 12, "semibold").get_pixel_size()[0] > x1 - lx - lw - 10:
                val = val.split(" · ")[0]                     # narrow: the first reading only
            D.text(cr, x1, y - 2, val, 12, col, "semibold", align="right")
            if frac is not None:
                D.bar(cr, lx, y + 16, x1 - lx, 3, frac, col)
            self.region(lx, y - 2, x1 - lx, step - 2, tip)
            y += step
        if g.get("note") and g.get("procs") is None:
            D.text(cr, lx, y + 2, g["note"], 10, "static", "regular", width=x1 - lx, wrap=True)
            self.region(lx, y, x1 - lx, 28, g["note"])
            y += 28
        return max(y, top + 2 * r + 40)

    def _graphs(self, cr, x0, x1, top, bottom, which):
        hist = list(self.history)
        span = len(hist) * self.interval
        names = {"util": ("LOAD", "%", "phosphor", 0, 100), "vram": ("VRAM", "%", "cyan", 0, 1),
                 "temp": ("TEMP", "°C", "amber", None, None), "watts": ("POWER", "W", "soft", 0, None)}
        n = len(which)
        cols = 2 if n == 4 and (x1 - x0) < 900 else n
        rows_ = -(-n // cols)
        gw = (x1 - x0 - (cols - 1) * 14) / cols
        gh = (bottom - top - (rows_ - 1) * 10) / rows_
        for i, key in enumerate(which):
            label, unit, col, lo, hi = names[key]
            gx = x0 + (i % cols) * (gw + 14)
            gy = top + (i // cols) * (gh + 10)
            vals = [s.get(key) for s in hist]
            now = next((v for v in reversed(vals) if v is not None), None)
            nowt = "--" if now is None else (f"{now * 100:.0f}%" if key == "vram" else f"{now:.0f}{unit}")
            D.label(cr, gx, gy, label, "dim", size=10)
            D.label(cr, gx + gw, gy, nowt, col, size=10, align="right")
            by = gy + 16
            bh = gh - 18
            D.src(cr, "void", 0.8)
            cr.rectangle(gx, by, gw, bh)
            cr.fill()
            D.src(cr, "guard", 1)
            cr.set_line_width(1)
            for j in (1, 2, 3):
                yy = round(by + bh * j / 4) + 0.5
                cr.move_to(gx, yy)
                cr.line_to(gx + gw, yy)
            cr.stroke()
            known = [v for v in vals if v is not None]
            if len(known) >= 2:
                D.spark(cr, gx, by + 2, gw, bh - 4, vals, col, lo=lo, hi=hi if hi is not None else max(known) * 1.1)
            peak = max(known) if known else None
            peakt = "--" if peak is None else (f"{peak * 100:.0f}%" if key == "vram" else f"{peak:.0f}{unit}")
            self.region(gx, gy, gw, gh, f"{label.title()} over the last {S.duration(span)} (a sample every 2 s): "
                        f"now {nowt}, peak {peakt}")

    def _procs(self, cr, g, x0, x1, top, bottom, limit=None, columns=False):
        procs = g.get("procs")
        D.label(cr, x0, top, "PROCESSES", "dim", size=10)
        if columns:
            D.label(cr, x1 - 150, top, "SM", "static", size=10, align="right")
            D.label(cr, x1, top, "VRAM", "static", size=10, align="right")
        D.rule(cr, x0 + 104, top + 7, x1 - (170 if columns else 0), "dim", 0.3)
        y = top + 18
        if procs is None:
            D.text(cr, x0, y, g.get("note") or "Reading which programs use it…", 10, "static", "regular",
                   width=x1 - x0, wrap=True)
            self.region(x0, top, x1 - x0, 40, g.get("note") or "Which programs use the GPU, read every 4 s")
            return
        if not procs:
            D.text(cr, x0, y, "Nothing is using the GPU.", 11, "static", "regular")
            self.region(x0, top, x1 - x0, 36, "No process holds memory on this GPU right now")
            return
        row = 20
        room = int((bottom - y) // row)
        shown = procs[:min(room, limit or room)]
        top_vram = max(p["vram"] or 0 for p in procs) or 1
        for p in shown:
            frac = (p["vram"] or 0) / (g.get("vram_total") or top_vram)
            D.src(cr, "phosphor", 0.12)
            cr.rectangle(x0, y + 1, (x1 - x0) * min(1.0, frac), row - 4)
            cr.fill()
            kinds = "+".join("C" if k == "compute" else "G" for k in p["kinds"])
            D.text(cr, x0 + 4, y + 1, p["name"], 11, "soft", "medium", width=(x1 - x0) * 0.5)
            D.text(cr, x0 + (x1 - x0) * 0.5 + 8, y + 2, f"{kinds} · {p['pid']}", 10, "static", "regular")
            if columns and p.get("sm") is not None:
                D.text(cr, x1 - 150, y + 1, f"{p['sm']}%", 11, D.level(p["sm"], 70, 90), "medium", align="right")
            D.text(cr, x1, y + 1, S.human(p["vram"], digits=1) if p["vram"] else "?", 11, "soft", "medium", align="right")
            what = {"compute": "compute (CUDA)", "graphics": "graphics"}
            self.region(x0, y, x1 - x0, row - 2,
                        f"{p['name']} (pid {p['pid']}{', ' + K.redact(p['cmd'])[:80] if p.get('cmd') else ''}): "
                        f"{S.human(p['vram']) if p['vram'] else 'unknown'} of video memory"
                        + (f", {p['sm']}% of the GPU's compute" if p.get("sm") is not None else "")
                        + f"; uses it for {' and '.join(what[k] for k in p['kinds'])}")
            y += row
        if len(procs) > len(shown):
            D.label(cr, x1, bottom - 12, f"+{len(procs) - len(shown)} MORE", "static", size=10, align="right")
            self.region(x1 - 90, bottom - 14, 90, 14, f"{len(procs) - len(shown)} more processes use the GPU; "
                        "make the panel taller to see them")

    def _others(self, cr, x0, x1, y):
        bits = []
        for g in self.gpus[1:]:
            bits.append(f"{g['name']} {g['util'] if g.get('util') is not None else '?'}%")
        D.text(cr, x0, y, "ALSO: " + " · ".join(bits), 10, "static", "regular", width=x1 - x0)
        self.region(x0, y, x1 - x0, 16, "The other GPUs in this machine, with their load")


PANEL = GpuPanel
LAYOUT = {"visible": False}
