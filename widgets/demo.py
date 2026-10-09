"""Demo readings for the panels, for pictures drawn offscreen (the theme switcher's
previews, docs): importing this module swaps the readers in sources.py for steady,
made-up ones, so a picture never shows the machine it was drawn on (its host name, its
load, its mounts, its network, the lab) and two pictures drawn a minute apart match.

    import demo        # before panels; then draw panels as usual (plugins.render, …)

Nothing here runs in the desktop's panels.
"""
import math
import threading
import time
from collections import deque, namedtuple

import sources as S

T0 = time.time()
_Mem = namedtuple("svmem", "total available percent used free")

# a load per core that looks like a working desktop: a few busy cores, most idle, bursts
_LEVEL = [0.62, 0.08, 0.41, 0.03, 0.27, 0.71, 0.05, 0.18, 0.02, 0.36, 0.11, 0.54,
          0.04, 0.22, 0.09, 0.47, 0.02, 0.15, 0.31, 0.06, 0.58, 0.01, 0.25, 0.12]


def _per(t, n=24):
    out = []
    for i in range(n):
        lv = _LEVEL[i % len(_LEVEL)]
        burst = max(0.0, math.sin(t * 0.11 + i * 2.4)) ** 12
        v = 100 * (lv * (0.55 + 0.45 * math.sin(t * (0.3 + 0.07 * i) + i)) + 0.85 * burst)
        out.append(max(0.5, min(98.0, v)))
    return out


class DemoGPU:
    ok, name = True, "RTX 4070"

    def read(self):
        return {"util": 23, "vram_used": int(3.1 * 2 ** 30), "vram_total": 12 * 2 ** 30, "temp": 51,
                "watts": 74.0}


class DemoSystem:
    def __init__(self, history=180):
        self.cores = 24
        self.history = deque(maxlen=history)
        self.gpu = DemoGPU()
        self.host = "drift"
        self.kernel = "6.16.8-arch1-1"
        self.os = "bromigOS"
        self.boot = time.time() - 3 * 86400 - 4 * 3600
        self.session_start = time.time() - 6 * 3600 - 1260
        self.temps = {"CPU": 58.0, "NVME": 41.0}
        for k in range(history):                       # a waterfall with history already in it
            self.history.append(_per(k * 2.0 * 0.21))
        self.sample()

    def sample(self):
        t = 40.0 + 2.0 * len(self.history) * 0.21
        self.per = _per(t)
        self.total = sum(self.per) / len(self.per)
        self.history.append(self.per)
        total = 64 * 2 ** 30
        used = int(23.6 * 2 ** 30)
        self.mem = _Mem(total, total - used, 100 * used / total, used, total - used)
        self.swap = _Mem(8 * 2 ** 30, 8 * 2 ** 30, 0.0, 0, 8 * 2 ** 30)
        self.load = (3.12, 2.87, 2.41)
        self.g = self.gpu.read()
        return self


class DemoNet:
    def __init__(self, history=120):
        self.rx_hist = deque(maxlen=history)
        self.tx_hist = deque(maxlen=history)
        for k in range(history):
            self.rx_hist.append(1.8e6 * (0.4 + math.sin(k * 0.13) ** 2) + 9e5 * max(0, math.sin(k * 0.05)) ** 8)
            self.tx_hist.append(2.4e5 * (0.4 + math.sin(k * 0.19 + 1) ** 2))
        self.iface, self.gw = "enp7s0", None
        self.rx = self.tx = 0.0
        self.addr = None
        self.signal = None

    def sample(self):
        k = len(self.rx_hist)
        self.rx = 2.3e6 * (0.5 + math.sin(k * 0.7) ** 2)
        self.tx = 3.1e5 * (0.5 + math.sin(k * 0.9 + 1) ** 2)
        self.rx_hist.append(self.rx)
        self.tx_hist.append(self.tx)
        return self


class DemoPinger(threading.Thread):
    def __init__(self, targets, every=6):
        super().__init__(daemon=True)
        self.targets = targets
        self.rtt = {label: v for (label, _), v in zip(targets, (1.2, 14.6, 23.0, 31.5, 8.8))}
        self.updated = time.time()

    def run(self):
        return


def demo_storage():
    G = 1024 ** 3
    return [{"mount": "/", "device": "nvme0n1p2", "size": 1863 * G, "used": 702 * G, "free": 1161 * G, "pct": 37.7,
             "fstype": "btrfs", "mounted": True},
            {"mount": "/boot", "device": "nvme0n1p1", "size": 1 * G, "used": 0.21 * G, "free": 0.79 * G, "pct": 21.0,
             "fstype": "vfat", "mounted": True},
            {"mount": "/data", "device": "sda1", "size": 3726 * G, "used": 2610 * G, "free": 1116 * G,
             "pct": 70.0, "fstype": "ext4", "mounted": True}]


S.GPU = DemoGPU
S.System = DemoSystem
S.Net = DemoNet
S.Pinger = DemoPinger
S.storage = demo_storage
S.default_iface = lambda: ("enp7s0", None)
# the operator's private values (ping targets, …): none
S.PRIV = type("NoPrivate", (), {"get": staticmethod(lambda k, d=None: d if d is not None else [])})()

# ------------------------------------------------------------------ the other panels
# WORKBENCH, WEATHER and CONNECTIONS read the machine (git repositories, the network,
# NetworkManager): made-up ones here. FIELD NOTES reads its file in the home the picture
# is drawn in (the preview writes one there). LAB (bromigos-homelab) gets a made-up lab
# when BROMIGOS_WIDGETS_DEMO_LAB=1 (a picture that shows LAB asks for it; without it no
# lab is found and the panel doesn't appear).
import os  # noqa: E402

import panels as P  # noqa: E402

_NOW = time.time()
_PROJECTS = [("drift-atlas", "~/projects", 1800, "main", 3, 1),
             ("relay-firmware", "~/projects", 3 * 3600, "main", 0, 0),
             ("my-theme", "~/projects", 9 * 3600, "colours", 2, 0),
             ("lamplighter-log", "~/projects", 26 * 3600, "main", 0, 2),
             ("beacon-kit", "~/projects", 3 * 86400, "main", 0, 0)]
_FOLDERS = [("Pictures", 41.0), ("notes", 33.0), ("Downloads", 20.0)]


def _scan(self):
    self.projects = [{"path": f"/srv/demo/{n}", "name": n, "where": w, "t": _NOW - ago, "branch": b, "changed": c,
                      "ahead": a, "behind": 0} for n, w, ago, b, c, a in _PROJECTS][:self.n_projects]
    self.folders = [{"path": f"/srv/demo/{n}", "name": n, "where": "~", "score": s}
                    for n, s in _FOLDERS][:self.n_folders]
    self.scanned = time.time()


P.WorkbenchPanel._scan = _scan
P.WorkbenchPanel._loop = lambda self: self._scan()


def demo_weather(now=None):
    """Open-Meteo's answer for a made-up harbour town on a wet night."""
    now = now or _NOW
    hours = [time.strftime("%Y-%m-%dT%H:00", time.localtime(now + 3600 * (h - 2))) for h in range(48)]
    days = [time.strftime("%Y-%m-%d", time.localtime(now + 86400 * d)) for d in range(4)]
    return {
        "current": {"time": hours[2], "temperature_2m": 11.4, "relative_humidity_2m": 88, "apparent_temperature": 9.6,
                    "weather_code": 61, "wind_speed_10m": 14.2, "wind_direction_10m": 230, "precipitation": 0.6,
                    "is_day": 0},
        "hourly": {"time": hours, "temperature_2m": [11 + 3 * math.sin((h - 6) / 24 * 6.283) for h in range(48)],
                   "precipitation_probability": [int(60 + 30 * math.sin(h / 5.0)) for h in range(48)]},
        "daily": {"time": days, "weather_code": [61, 3, 2, 80], "temperature_2m_max": [14.1, 15.8, 17.2, 13.9],
                  "temperature_2m_min": [8.2, 7.9, 9.4, 8.8], "precipitation_probability_max": [80, 30, 10, 70],
                  "sunrise": [d + "T07:12" for d in days], "sunset": [d + "T18:41" for d in days]},
    }


def _weather_init(self, cfg=None):
    P.Panel.__init__(self, cfg)
    self.loc = {"name": "Harbor Point", "lat": 0, "lon": 0}
    self.data = demo_weather()
    self.error = None
    self.fetched = time.time()
    self.units = "metric"


P.WeatherPanel.__init__ = _weather_init

_NM_ACTIVE = "Wired connection 1:802-3-ethernet:enp7s0:activated\nlighthouse:wireguard:wg0:activated\n"
_NM_SAVED = "Wired connection 1:802-3-ethernet\nlighthouse:wireguard\nHarbor Guest:802-11-wireless\n" \
            "Greywater:802-11-wireless\n"
_NM_WIFI = " :Greywater:82:WPA2\n :Harbor Guest:64:WPA2\n :Lamplighters:47:WPA3\n :Tidewatch-5G:31:WPA2\n" \
           " :Drift Relay:18:WPA2\n"


def _demo_nmcli(*args, timeout=8):
    """NetworkManager's answers for a desktop on a wire, a WireGuard tunnel up, Wi-Fi in reach."""
    if "connection" in args:
        return _NM_ACTIVE if "--active" in args else _NM_SAVED
    if "radio" in args:
        return "enabled\n"
    if "wifi" in args and "list" in args:
        return _NM_WIFI
    return ""


P._nmcli = _demo_nmcli

from demo_lab import DEMO_LAB  # noqa: E402  (shared with the live layer's pictures)


def _demo_lab():
    """bromigos_homelab with the made-up lab in it (when the picture asks for LAB)."""
    import sys
    for d in (os.path.join(os.environ.get("BROMIGOS_HOMELAB") or "", "lib"),
              os.path.join(os.path.dirname(os.path.dirname(os.path.realpath(__file__))), "homelab", "lib"),
              "/usr/lib/bromigos/lib"):
        if os.path.isdir(os.path.join(d, "bromigos_homelab")) and d not in sys.path:
            sys.path.insert(0, d)
            break
    try:
        import bromigos_homelab as H
    except ImportError:
        return
    H.snapshot_source = lambda: "demo"
    H.snapshot = lambda: dict(DEMO_LAB, generatedAt=time.time() - 4)
    H.source_of = lambda *a, **k: None
    H.lab_url = lambda: None
    H.config.panels = lambda: []


if os.environ.get("BROMIGOS_WIDGETS_DEMO_LAB") == "1":
    _demo_lab()
