"""Readings for the live layer. Everything here is real: psutil for this
machine, one long-lived nvidia-smi stream for the GPU, bromigos-homelab's lab
snapshot for the homelab and a trade tape's paper fills (the [fills] feed, when set).

Collectors run on daemon threads and write into one dict under a lock; the
renderer only ever reads a snapshot. Rates slow down when the layer is paused.
"""
import glob
import json
import os
import ssl
import subprocess
import threading
import time
import urllib.request

import psutil

EXPAND = os.path.expanduser


class Data:
    def __init__(self, cfg, on_event):
        self.cfg = cfg
        self.on_event = on_event          # callback(kind, **info) -> main loop
        self.lock = threading.Lock()
        self.paused = False
        self.stop = threading.Event()
        self.s = {
            "cpu": 0.0, "cores": [], "cpu_temp": None, "cpu_freq": None,
            "mem": 0.0, "mem_used": 0, "mem_total": psutil.virtual_memory().total,
            "swap": 0.0,
            "gpu": None, "vram": None, "vram_used": None, "vram_total": None,
            "gpu_temp": None, "gpu_power": None, "gpu_fan": None, "gpu_clock": None,
            "rx": 0.0, "tx": 0.0, "rx_hist": [0.0] * 48, "tx_hist": [0.0] * 48,
            "disks": {}, "mounts": [], "nvme_temps": {},
            "cluster": None, "cluster_ok": False, "cluster_at": 0,
            "fills_total": None,
            "board_temp": None, "chipset_temp": None,
        }
        self.static = self._static()
        self.minute = {"cpu": [], "rx": [], "tx": []}

    # ------------------------------------------------------------------ static
    def _static(self):
        cpu_model = "CPU"
        try:
            with open("/proc/cpuinfo") as f:
                for line in f:
                    if line.startswith("model name"):
                        cpu_model = line.split(":", 1)[1].strip()
                        break
        except OSError:
            pass
        u = os.uname()
        drives = []
        try:
            for name in sorted(os.listdir("/sys/block")):
                if name.startswith(("loop", "zram", "ram", "dm-")):
                    continue
                base = f"/sys/block/{name}"
                try:
                    with open(f"{base}/device/model") as f:
                        model = f.read().strip()
                except OSError:
                    model = name
                with open(f"{base}/size") as f:
                    size = int(f.read()) * 512
                drives.append({"name": name, "model": model, "size": size,
                               "nvme": name.startswith("nvme")})
        except OSError:
            pass
        gpu_name = "GPU"
        try:
            gpu_name = subprocess.run(
                ["nvidia-smi", "--query-gpu=name", "--format=csv,noheader"],
                capture_output=True, text=True, timeout=5).stdout.strip().splitlines()[0]
        except Exception:
            pass
        return {"cpu_model": cpu_model, "threads": psutil.cpu_count(),
                "cores_phys": psutil.cpu_count(logical=False), "kernel": u.release,
                "arch": u.machine, "sys": u.sysname, "drives": drives, "gpu_name": gpu_name}

    def snapshot(self):
        with self.lock:
            return dict(self.s)

    def take_minute(self):
        """Averages of the 1 s samples since the last call (for the history)."""
        with self.lock:
            out = {k: (sum(v) / len(v)) for k, v in self.minute.items() if v}
            self.minute = {k: [] for k in self.minute}
        return out

    def _set(self, **kw):
        with self.lock:
            self.s.update(kw)

    # ------------------------------------------------------------------ threads
    def start(self):
        for fn in (self._local_loop, self._slow_loop, self._gpu_loop, self._cluster_loop, self._fills_loop):
            threading.Thread(target=fn, daemon=True, name=fn.__name__).start()

    def _sleep(self, active, paused):
        self.stop.wait(paused if self.paused else active)

    def _local_loop(self):
        psutil.cpu_percent(percpu=True)
        last = psutil.net_io_counters(pernic=True)
        last_disk = psutil.disk_io_counters(perdisk=True)
        last_t = time.monotonic()
        skip = ("lo", "docker", "veth", "br-", "virbr", "tailscale")
        while not self.stop.is_set():
            self._sleep(1.0, 4.0)
            now = time.monotonic()
            dt = max(now - last_t, 0.1)
            cores = psutil.cpu_percent(percpu=True)
            vm = psutil.virtual_memory()
            sw = psutil.swap_memory()
            net = psutil.net_io_counters(pernic=True)
            rx = tx = 0.0
            for nic, c in net.items():
                if nic.startswith(skip) or nic not in last:
                    continue
                rx += max(c.bytes_recv - last[nic].bytes_recv, 0)
                tx += max(c.bytes_sent - last[nic].bytes_sent, 0)
            rx /= dt
            tx /= dt
            dio = psutil.disk_io_counters(perdisk=True) or {}
            disks = {}
            for name, c in dio.items():
                p = last_disk.get(name)
                if p is None or not (name.startswith("nvme") and name.count("p") == 0 or name.startswith("sd") and name[-1].isalpha()):
                    continue
                disks[name] = {"r": max(c.read_bytes - p.read_bytes, 0) / dt,
                               "w": max(c.write_bytes - p.write_bytes, 0) / dt}
            last, last_disk, last_t = net, dio, now
            with self.lock:
                self.minute["cpu"].append(sum(cores) / max(len(cores), 1))
                self.minute["rx"].append(rx)
                self.minute["tx"].append(tx)
                self.s["cores"] = cores
                self.s["cpu"] = sum(cores) / max(len(cores), 1)
                self.s["mem"] = vm.percent
                self.s["mem_used"] = vm.total - vm.available
                self.s["swap"] = sw.percent
                self.s["rx"], self.s["tx"] = rx, tx
                self.s["rx_hist"] = (self.s["rx_hist"] + [rx])[-48:]
                self.s["tx_hist"] = (self.s["tx_hist"] + [tx])[-48:]
                self.s["disks"] = disks

    def _slow_loop(self):
        while not self.stop.is_set():
            try:
                t = psutil.sensors_temperatures()
                cpu_t = None
                for key in ("k10temp", "coretemp", "zenpower"):
                    if key in t and t[key]:
                        cpu_t = t[key][0].current
                        break
                nv = {}   # by controller index, straight from each controller's hwmon
                for ctrl in glob.glob("/sys/class/nvme/nvme*"):
                    for f in glob.glob(ctrl + "/hwmon*/temp1_input"):
                        try:
                            with open(f) as fh:
                                nv[int(ctrl.rsplit("nvme", 1)[1])] = int(fh.read()) / 1000.0
                        except (OSError, ValueError):
                            pass
                board = chipset = None
                for e in t.get("asusec", []):
                    if e.label == "Motherboard":
                        board = e.current
                    if e.label == "Chipset":
                        chipset = e.current
                mounts = []
                seen = set()
                for p in psutil.disk_partitions():
                    if p.fstype not in ("btrfs", "ext4", "xfs", "vfat", "f2fs", "ntfs3", "exfat"):
                        continue
                    dev = p.device
                    if (dev, p.fstype) in seen and p.mountpoint not in ("/", "/home"):
                        continue
                    seen.add((dev, p.fstype))
                    try:
                        u = psutil.disk_usage(p.mountpoint)
                    except OSError:
                        continue
                    mounts.append({"mount": p.mountpoint, "dev": os.path.basename(dev), "fs": p.fstype,
                                   "pct": u.percent, "used": u.used, "total": u.total})
                freq = psutil.cpu_freq()
                self._set(cpu_temp=cpu_t, nvme_temps=nv, mounts=mounts, board_temp=board,
                          chipset_temp=chipset, cpu_freq=freq.current if freq else None)
            except Exception:
                pass
            self._sleep(5.0, 15.0)

    def _gpu_loop(self):
        q = "utilization.gpu,memory.used,memory.total,temperature.gpu,power.draw,fan.speed,clocks.gr"
        while not self.stop.is_set():
            try:
                p = subprocess.Popen(["nvidia-smi", f"--query-gpu={q}", "--format=csv,noheader,nounits",
                                      "-lms", "1500"], stdout=subprocess.PIPE, text=True,
                                     stderr=subprocess.DEVNULL)
                for line in p.stdout:
                    if self.stop.is_set():
                        break
                    v = [x.strip() for x in line.split(",")]

                    def num(x):
                        try:
                            return float(x)
                        except ValueError:
                            return None
                    util, mu, mt, temp, pw, fan, clk = (num(x) for x in v[:7])
                    self._set(gpu=util, vram_used=mu, vram_total=mt,
                              vram=(mu / mt * 100.0) if mu is not None and mt else None,
                              gpu_temp=temp, gpu_power=pw, gpu_fan=fan, gpu_clock=clk)
                p.kill()
            except Exception:
                pass
            self.stop.wait(10)

    # ------------------------------------------------------------------ network
    def _ctx(self):
        ca = EXPAND(self.cfg["cluster"].get("ca_file", ""))
        if ca and os.path.exists(ca):
            return ssl.create_default_context(cafile=ca)
        return ssl.create_default_context()

    def _cluster_loop(self):
        """The lab snapshot from bromigos-homelab (a Lab API, or built from Prometheus), every
        poll_seconds; cluster_alert events when alerts rise or a node drops. Without the
        package or a configured source there is no lab: cluster stays None."""
        from .homelab import H
        prev_alerts = None
        prev_ready = None
        while not self.stop.is_set():
            c = self.cfg["cluster"]
            if not H or not H.snapshot_source():
                self._set(cluster=None, cluster_ok=False)
                self.stop.wait(60)
                continue
            try:
                d = H.snapshot() or {}
                keep = {k: d.get(k) for k in ("cluster", "nodes", "gpu", "ai", "argocd", "traefik",
                                               "network", "proxmox", "services", "generatedAt")}
                so = d.get("solar") or {}       # production only: the solar block also names a street address
                if so:
                    keep["solar"] = {"productionW": so.get("productionW"), "energyTodayWh": so.get("energyTodayWh")}
                nas = d.get("nas") or {}
                if nas:
                    keep["nas"] = {"pool": nas.get("pool")}
                self._set(cluster=keep, cluster_ok=True, cluster_at=time.time())
                cl = keep.get("cluster") or {}
                alerts = cl.get("alertsFiring")
                ready = cl.get("nodesReady")
                if prev_alerts is not None and alerts is not None and alerts > prev_alerts:
                    self.on_event("cluster_alert", count=alerts)
                if prev_ready is not None and ready is not None and ready < prev_ready:
                    self.on_event("cluster_alert", count=alerts, node_down=True)
                prev_alerts, prev_ready = alerts, ready
            except Exception:
                self._set(cluster_ok=False)
            self.stop.wait(max(20, int(c.get("poll_seconds", 25))) * (3 if self.paused else 1))

    def _fills_loop(self):
        """New paper fills -> rain burst; notable ones (|realized| or notional over
        the codec thresholds) also become a FLOOR codec call, batched."""
        prev = None
        while not self.stop.is_set():
            a = self.cfg.get("fills", {})
            url = a.get("url", "")
            if url:
                try:
                    with urllib.request.urlopen(url.replace("limit=1", "limit=10"), timeout=8, context=self._ctx()) as r:
                        d = json.load(r)
                    total = d.get("total")
                    if prev is not None and total is not None and total > prev:
                        new = (d.get("trades") or [])[:min(total - prev, 10)]
                        results = ["win" if (t.get("realized_usd") or 0) > 0 else
                                   "loss" if (t.get("realized_usd") or 0) < 0 else "open" for t in new]
                        self.on_event("fill", n=total - prev, notable=self._notable(new), results=results)
                    prev = total
                    self._set(fills_total=total)
                except Exception:
                    pass
            self.stop.wait(max(20, int(a.get("poll_seconds", 30))) * (3 if self.paused else 1))

    def _notable(self, trades):
        c = self.cfg.get("codec", {})
        min_real = float(c.get("fill_min_realized", 5.0))
        min_notional = float(c.get("fill_min_notional", 250.0))
        hits = [t for t in trades if abs(t.get("realized_usd") or 0) >= min_real
                or abs(t.get("notional_usd") or 0) >= min_notional]
        if not hits:
            return None
        t = max(hits, key=lambda x: abs(x.get("realized_usd") or 0) + abs(x.get("notional_usd") or 0) / 100)
        inst = (t.get("instrument") or "").split(" ")[0].replace("/", " ")
        act = f"{t.get('action', '')} {t.get('effect', '')}".strip()
        r = t.get("realized_usd")
        msg = f"Floor here. Paper fill: {act} {inst}, {abs(t.get('notional_usd') or 0):.0f} dollars"
        if r:
            msg += f", realized {'plus' if r > 0 else 'minus'} {abs(r):.2f}"
        cause = ((t.get("causes") or [{}])[0].get("kind") or t.get("reason") or "").replace("_", " ")
        if cause:
            msg += f". Cause: {cause}"
        if len(hits) > 1:
            msg += f". {len(hits) - 1} more notable"
        return msg + "."
