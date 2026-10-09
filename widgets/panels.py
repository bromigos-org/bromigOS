"""The desktop panels. Each one draws real readings only; every hoverable region
carries a tooltip saying what it is, and clickable ones say what a click does."""
import json
import math
import os
import subprocess
import threading
import time
import urllib.request

import cairo

import draw as D
import sources as S


def open_url(url):
    if not url:
        return
    subprocess.Popen(["xdg-open", url], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                     start_new_session=True)


def copy_text(s):
    subprocess.Popen(["wl-copy", s], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


class Panel:
    name = "panel"
    title = "PANEL"
    width = 470
    height = 200
    interval = 2.0                      # seconds between samples

    def __init__(self, cfg=None):
        self.cfg = cfg or {}
        self.regions = []               # (x, y, w, h, tooltip, action-or-None)
        self.animating = False          # True while a short animation wants ~15 fps

    def region(self, x, y, w, h, tip, action=None):
        self.regions.append((x, y, w, h, tip, action))

    def hit(self, x, y):
        for r in reversed(self.regions):
            if r[0] <= x <= r[0] + r[2] and r[1] <= y <= r[1] + r[3]:
                return r
        return None

    def tick(self):
        """Sample data. Called every `interval` seconds even while covered (cheap)."""

    def render(self, cr, w, h):
        self.regions = []
        cr.set_operator(cairo.OPERATOR_SOURCE)
        cr.set_source_rgba(0, 0, 0, 0)
        cr.paint()
        cr.set_operator(cairo.OPERATOR_OVER)
        self.draw(cr, w, h)

    def draw(self, cr, w, h):
        raise NotImplementedError


# =================================================================== SYSTEM
class SystemPanel(Panel):
    name, title = "system", "SYSTEM"
    height = 452
    interval = 2.0

    def __init__(self, cfg=None):
        super().__init__(cfg)
        self.sys = S.System(history=200)   # 200 x 2 s = 6:40 of waterfall

    def tick(self):
        self.sys.sample()

    def draw(self, cr, w, h):
        s = self.sys
        top = D.frame(cr, w, h, self.title, f"{s.host} · {s.os} {s.kernel.split('-')[0]}")
        self.region(0, 0, w, 34, f"This machine: host {s.host}, {s.os}, kernel {s.kernel}")
        x0, x1 = 16, w - 16

        # --- CPU: segment readout + per-core heat grid
        D.label(cr, x0, top, "CPU", "dim")
        col = D.level(s.total, 70, 90)
        D.seg7(cr, x0, top + 18, 40, f"{s.total:3.0f}", col)
        D.text(cr, x0 + 104, top + 40, "%", 16, col, "bold")
        ctemp = s.temps.get("CPU")
        if ctemp is not None:
            D.label(cr, x0, top + 66, f"TEMP {ctemp:.0f}°C", D.level(ctemp, 80, 90))
        self.region(x0, top, 130, 84, f"CPU load across all {s.cores} threads (2 s average)"
                    + (f"; package temperature {ctemp:.0f} °C (amber 80, red 90)" if ctemp else ""))
        gx, gy = x0 + 146, top + 2
        cols = 8
        rows = math.ceil(s.cores / cols)
        cw, chh, gap = (x1 - gx - (cols - 1) * 4) / cols, 32, 4
        D.label(cr, x1, top, f"{s.cores} THREADS", "dim", align="right")
        gy += 16
        cell_h = (68 - (rows - 1) * gap) / rows if rows else chh
        for i, v in enumerate(s.per):
            r, c = divmod(i, cols)
            cx, cy = gx + c * (cw + 4), gy + r * (cell_h + gap)
            heat = v / 100
            colr = "danger" if v >= 95 else "amber" if v >= 80 else "phosphor"
            D.src(cr, "guard", 0.9)
            cr.rectangle(cx, cy, cw, cell_h)
            cr.fill()
            D.src(cr, colr, 0.15 + 0.85 * heat)
            cr.rectangle(cx, cy + cell_h * (1 - heat), cw, cell_h * heat)
            cr.fill()
            D.text(cr, cx + cw / 2, cy + cell_h / 2 - 7, f"{v:.0f}", 10,
                   "void" if heat > 0.55 else "soft", "semibold", align="center")
            self.region(cx, cy, cw, cell_h, f"CPU thread {i}: {v:.0f}% busy")

        # --- waterfall: per-thread load over time, newest at the right
        wy = top + 98
        D.label(cr, x0, wy, "LOAD WATERFALL", "dim")
        span = len(s.history) * self.interval
        D.label(cr, x1, wy, f"LAST {S.duration(span)}", "static", align="right")
        wy += 18
        wh = 128
        self._waterfall(cr, x0, wy, x1 - x0, wh)
        self.region(x0, wy, x1 - x0, wh, "Load waterfall: one row per CPU thread, one column per 2 s sample, "
                    "brighter = busier; newest at the right")

        # --- memory and GPU fuel cells
        y = wy + wh + 16
        m = s.mem
        self._cellrow(cr, x0, x1, y, "RAM", m.used / m.total,
                      f"{S.human(m.used)} / {S.human(m.total)}",
                      f"Memory in use (excludes cache): {S.human(m.used)} of {S.human(m.total)}; "
                      f"{S.human(m.available)} available. Amber past 75%, red past 90%.")
        y += 38
        g = s.g
        if g:
            self._cellrow(cr, x0, x1, y, "VRAM", g["vram_used"] / g["vram_total"],
                          f"{S.human(g['vram_used'])} / {S.human(g['vram_total'])}",
                          f"{s.gpu.name} video memory: {S.human(g['vram_used'])} of {S.human(g['vram_total'])}")
            y += 38
            gc = D.level(g["util"], 70, 90)
            D.label(cr, x0, y, "GPU", "dim")
            D.text(cr, x0 + 56, y - 3, f"{g['util']:3d}%", 15, gc, "bold", glow=g["util"] > 0)
            D.label(cr, x0 + 130, y, s.gpu.name, "static")
            D.label(cr, x1, y, f"{g['temp']}°C · {g['watts']:.0f} W", D.level(g["temp"], 75, 85), align="right")
            self.region(x0, y - 4, x1 - x0, 22, f"{s.gpu.name}: {g['util']}% busy, {g['temp']} °C, "
                        f"drawing {g['watts']:.0f} W (NVML)")
            y += 30

        # --- footer: load, uptime, session
        D.rule(cr, x0, y - 6, x1)
        la = s.load
        D.label(cr, x0, y + 2, f"LOAD {la[0]:.2f} {la[1]:.2f} {la[2]:.2f}",
                D.level(la[0] / s.cores, 0.7, 1.0))
        self.region(x0, y, 200, 18, "Load average over 1, 5 and 15 minutes "
                    f"(amber past {s.cores * 0.7:.0f}, i.e. 70% of {s.cores} threads)")
        up = time.time() - s.boot
        ses = time.time() - s.session_start
        D.label(cr, x1, y + 2, f"UP {S.duration(up)} · SESSION {S.duration(ses)}", "soft", align="right")
        self.region(x1 - 220, y, 220, 18, f"Uptime since boot {S.duration(up)}; this Hyprland session "
                    f"has run {S.duration(ses)}")
        nv = s.temps.get("NVME")
        if nv is not None:
            pass

    def _cellrow(self, cr, x0, x1, y, name, frac, right, tip):
        D.label(cr, x0, y, name, "dim")
        D.label(cr, x1, y, right, "soft", align="right")
        D.label(cr, x0 + 56, y, f"{frac * 100:.0f}%", D.level(frac, 0.75, 0.9))
        D.cells(cr, x0, y + 17, x1 - x0, 9, frac, n=40)
        self.region(x0, y, x1 - x0, 28, tip)

    def _waterfall(self, cr, x, y, w, h):
        hist = list(self.sys.history)
        n = len(hist)
        cores = self.sys.cores
        D.src(cr, "void", 0.9)
        cr.rectangle(x, y, w, h)
        cr.fill()
        if not n:
            return
        cols = 200
        colw = w / cols
        rowh = h / cores
        start = cols - n
        for i, sample in enumerate(hist):
            cx = x + (start + i) * colw
            for c, v in enumerate(sample):
                if v < 4:
                    continue
                colr = "danger" if v >= 95 else "amber" if v >= 80 else "phosphor"
                D.src(cr, colr, min(1.0, 0.12 + v / 100 * 0.95))
                cr.rectangle(cx, y + c * rowh, colw + 0.4, rowh - 0.6)
        cr.fill()
        cr.set_line_width(1)
        D.src(cr, "dim", 0.45)
        cr.rectangle(x + 0.5, y + 0.5, w - 1, h - 1)
        cr.stroke()


# =================================================================== NETWORK
class NetworkPanel(Panel):
    name, title = "network", "NETWORK"
    height = 262
    interval = 1.0

    def __init__(self, cfg=None):
        super().__init__(cfg)
        self.net = S.Net(history=120)
        # {"private": "lan.ping"} expands to the operator's LAN hosts from the private overlay
        cfg = [x for t in self.cfg.get("ping", []) for x in (S.PRIV.get(t["private"], []) if "private" in t else [t])]
        targets = [(t["label"], t.get("host")) for t in cfg if t.get("label")] or [("GATEWAY", None)]
        self.ping = S.Pinger(targets, every=6)
        self.ping.start()
        self.sweep = 0.0

    def tick(self):
        self.net.sample()
        self.sweep = (self.sweep + 30) % 360

    def draw(self, cr, w, h):
        n = self.net
        wifi = f" · {n.signal:.0f} dBm" if n.signal is not None else ""
        top = D.frame(cr, w, h, self.title, f"{n.iface or 'NO LINK'}{wifi}",
                      "static" if n.iface else "amber")
        self.region(0, 0, w, 34, (f"Default route via {n.iface}" + (f", Wi-Fi signal {n.signal:.0f} dBm" if wifi else "")
                                  + (f"; address {n.addr} (click to copy)" if n.addr else ""))
                    if n.iface else "No default route: disconnected",
                    (lambda: copy_text(n.addr)) if n.addr else None)
        x0, x1 = 16, w - 16
        scope_w = x1 - x0 - 150
        # --- readouts
        D.label(cr, x0, top, "RX", "dim")
        D.text(cr, x0 + 30, top - 3, S.rate(n.rx), 14, "phosphor", "bold", glow=n.rx > 1024)
        D.label(cr, x0 + scope_w / 2 + 10, top, "TX", "dim")
        D.text(cr, x0 + scope_w / 2 + 40, top - 3, S.rate(n.tx), 14, "soft", "bold", glow=n.tx > 1024)
        self.region(x0, top - 4, scope_w, 22, f"Live throughput on {n.iface}: receive {S.rate(n.rx)}, "
                    f"transmit {S.rate(n.tx)} (1 s)")
        # --- oscilloscope
        sy, sh = top + 26, h - top - 26 - 16
        self._scope(cr, x0, sy, scope_w, sh)
        peak_rx, peak_tx = max(n.rx_hist), max(n.tx_hist)
        self.region(x0, sy, scope_w, sh, f"Last 2 minutes, log scale. RX peak {S.rate(peak_rx)}, "
                    f"TX peak {S.rate(peak_tx)}")
        # --- latency radar
        rx = x1 - 62
        self._radar(cr, rx, top + 58, 54)

    def _scope(self, cr, x, y, w, h):
        D.src(cr, "void", 0.9)
        cr.rectangle(x, y, w, h)
        cr.fill()
        # graticule: 10 x 4 vector grid
        cr.set_line_width(1)
        D.src(cr, "guard", 1)
        for i in range(1, 10):
            gx = round(x + w * i / 10) + 0.5
            cr.move_to(gx, y)
            cr.line_to(gx, y + h)
        for j in range(1, 4):
            gy = round(y + h * j / 4) + 0.5
            cr.move_to(x, gy)
            cr.line_to(x + w, gy)
        cr.stroke()
        D.src(cr, "dim", 0.45)
        cr.rectangle(x + 0.5, y + 0.5, w - 1, h - 1)
        cr.stroke()
        top = max(max(self.net.rx_hist), max(self.net.tx_hist), 64 * 1024)
        lt = math.log10(top + 1)

        def ypos(v):
            return y + h - 3 - (h - 6) * (math.log10(v + 1) / lt)

        for hist, color, base_a in ((self.net.tx_hist, "soft", 0.55), (self.net.rx_hist, "phosphor", 1.0)):
            vals = list(hist)
            nseg = len(vals) - 1
            # afterglow: older segments fade, the head is brightest
            cr.set_line_width(1.6)
            for i in range(nseg):
                a = base_a * (0.12 + 0.88 * (i / nseg) ** 1.6)
                D.src(cr, color, a)
                cr.move_to(x + w * i / nseg, ypos(vals[i]))
                cr.line_to(x + w * (i + 1) / nseg, ypos(vals[i + 1]))
                cr.stroke()
            D.dot(cr, x + w - 1, ypos(vals[-1]), 2.4, color)
        D.label(cr, x + 4, y + 3, S.rate(top).replace(" ", ""), "static", size=9)

    def _radar(self, cr, cx, cy, r):
        cr.new_path()
        D.src(cr, "void", 0.9)
        cr.arc(cx, cy, r, 0, 2 * math.pi)
        cr.fill()
        cr.set_line_width(1)
        for rr, a in ((r, 0.7), (r * 0.66, 0.45), (r * 0.33, 0.45)):
            D.src(cr, "dim", a)
            cr.arc(cx, cy, rr, 0, 2 * math.pi)
            cr.stroke()
        D.src(cr, "guard", 1)
        cr.move_to(cx - r, cy)
        cr.line_to(cx + r, cy)
        cr.move_to(cx, cy - r)
        cr.line_to(cx, cy + r)
        cr.stroke()
        # sweep with a trailing wedge
        a0 = math.radians(self.sweep - 90)
        for k in range(10):
            D.src(cr, "phosphor", 0.10 * (1 - k / 10))
            cr.move_to(cx, cy)
            cr.arc(cx, cy, r, a0 - math.radians(3 * (k + 1)), a0 - math.radians(3 * k))
            cr.close_path()
            cr.fill()
        D.src(cr, "phosphor", 0.9)
        cr.move_to(cx, cy)
        cr.line_to(cx + r * math.cos(a0), cy + r * math.sin(a0))
        cr.stroke()
        # blips: bearing fixed per host, distance = log latency (1 ms centre .. 300 ms rim)
        targets = self.ping.targets
        legend_y = cy + r + 8
        for i, (label, _) in enumerate(targets):
            rtt = self.ping.rtt.get(label)
            bearing = 360 * i / len(targets) + 45
            ba = math.radians(bearing - 90)
            diff = (self.sweep - bearing) % 360
            fresh = 1.0 - min(diff, 360 - 0) / 360        # brightest just after the sweep passes
            if rtt is None:
                rr, col = r - 4, "danger"
            else:
                rr = 6 + (r - 10) * min(1.0, math.log10(max(rtt, 1)) / math.log10(300))
                col = D.level(rtt, 50, 150)
            D.dot(cr, cx + rr * math.cos(ba), cy + rr * math.sin(ba), 2.6, col, glow=fresh > 0.7)
            self.region(cx + rr * math.cos(ba) - 8, cy + rr * math.sin(ba) - 8, 16, 16,
                        f"{label}: " + (f"{rtt:.1f} ms round trip" if rtt is not None else "no reply"))
        # legend under the radar
        for i, (label, _) in enumerate(targets):
            rtt = self.ping.rtt.get(label)
            col = "danger" if rtt is None else D.level(rtt, 50, 150)
            lx = cx - r - 8
            ly = legend_y + i * 16
            D.label(cr, lx, ly, label, "dim", size=10)
            D.label(cr, cx + r + 6, ly, "--" if rtt is None else f"{rtt:.0f} MS", col, size=10, align="right")
            self.region(lx, ly, 2 * r + 14, 15, f"{label} latency (ICMP ping every 6 s): "
                        + (f"{rtt:.1f} ms" if rtt is not None else "no reply")
                        + ". The radar plots it by distance: centre 1 ms, rim 300 ms.")


# =================================================================== STORAGE
class StoragePanel(Panel):
    name, title = "storage", "STORAGE"
    height = 214
    interval = 30.0

    def __init__(self, cfg=None):
        super().__init__(cfg)
        self.mounts = S.storage()

    def tick(self):
        self.mounts = S.storage()

    def draw(self, cr, w, h):
        total = sum(m["size"] for m in self.mounts if m["mounted"])
        used = sum(m["used"] for m in self.mounts if m["mounted"])
        top = D.frame(cr, w, h, self.title, f"{S.human(used)} / {S.human(total)} USED")
        self.region(0, 0, w, 34, f"All mounted filesystems together: {S.human(used)} used of {S.human(total)}")
        shown = self.mounts[:4]
        slot = (w - 32) / max(1, len(shown))
        for i, m in enumerate(shown):
            cx = 16 + slot * i + slot / 2
            cy = top + 50
            if m["mounted"]:
                frac = m["pct"] / 100
                col = D.level(frac, 0.8, 0.92)
                D.ring(cr, cx, cy, 38, frac, 7, col)
                D.text(cr, cx, cy - 10, f"{m['pct']:.0f}%", 16, col, "bold", align="center", glow=True)
                name = m["mount"]
                D.label(cr, cx, cy + 50, name if len(name) < 12 else "…" + name[-10:], "phosphor", align="center")
                D.label(cr, cx, cy + 66, S.human(m['used'], digits=0).replace(" ", "") + "/"
                        + S.human(m['size'], digits=0).replace(" ", ""), "soft", size=10, align="center")
                D.label(cr, cx, cy + 81, f"{S.human(m['free'], digits=0).replace(' ', '')} FREE", "static",
                        size=10, align="center")
                tip = (f"{m['mount']} on {m['device']} ({m['fstype']}): {S.human(m['used'])} used of "
                       f"{S.human(m['size'])}, {S.human(m['free'])} free. Click to open in the file manager.")
                act = (lambda p=m["mount"]: subprocess.Popen(["xdg-open", p], start_new_session=True))
            else:
                D.ring(cr, cx, cy, 38, None, 7, "static", dashed=True)
                D.label(cr, cx, cy - 7, "OFF", "static", align="center")
                D.label(cr, cx, cy + 50, m.get("label") or m["device"], "static", align="center")
                D.label(cr, cx, cy + 66, f"{S.human(m['size'], digits=1)} {m['fstype'].upper()}", "static",
                        size=9, align="center")
                D.label(cr, cx, cy + 80, "NOT MOUNTED", "amber", size=9, align="center")
                tip = (f"{m['device']} ({m['fstype']}, {S.human(m['size'])}"
                       + (f", label {m['label']}" if m.get("label") else "") + ") is not mounted")
                act = None
            self.region(cx - slot / 2, top, slot, h - top - 6, tip, act)


# =================================================================== SWITCHBOARD
class WorkbenchPanel(Panel):
    """Recent projects (git repos by last local activity) and the folders you actually
    use (zoxide's frecency database). Each row opens in nvim, a terminal or Dolphin."""
    name, title = "workbench", "WORKBENCH"
    height = 300
    interval = 1.0                       # cheap redraw; the scan runs every 60 s in a thread
    ROW, HEAD = 26, 20
    N_PROJECTS, N_FOLDERS = 5, 3
    ROOTS = ["~/github.com/*/*", "~/.dotfiles", "~/Repos/*", "~/*"]
    TERM = ["kitty"]
    FILES = ["pcmanfm"]                 # the operator's file manager (ALT+E)

    def __init__(self, cfg=None):
        super().__init__(cfg)
        cfg = cfg or {}
        self.n_projects = cfg.get("projects", self.N_PROJECTS)
        self.n_folders = cfg.get("folders", self.N_FOLDERS)
        self.projects, self.folders, self.scanned = [], [], 0
        import threading
        threading.Thread(target=self._loop, daemon=True).start()

    # ------------------------------------------------------------ data
    def _loop(self):
        while True:
            try:
                self._scan()
            except Exception as e:  # never take the panel down
                print("workbench scan:", e)
            time.sleep(60)

    @staticmethod
    def _activity(repo):
        """Last local activity: commits/checkouts/pulls (logs/HEAD) or staging (index).
        Our own `git status` runs with --no-optional-locks so the scan never bumps the index."""
        import os
        t = 0
        for f in ("logs/HEAD", "index", "HEAD"):
            try:
                t = max(t, os.path.getmtime(os.path.join(repo, ".git", f)))
            except OSError:
                pass
        return t

    @staticmethod
    def _git(repo):
        """(branch, changed files, ahead, behind) from one `git status`."""
        try:
            out = subprocess.run(["git", "--no-optional-locks", "-C", repo, "status", "--porcelain=v1", "-b", "--no-renames"],
                                 capture_output=True, text=True, timeout=5).stdout.splitlines()
        except (OSError, subprocess.TimeoutExpired):
            return None, 0, 0, 0
        branch, ahead, behind = None, 0, 0
        if out and out[0].startswith("## "):
            import re
            head = out[0][3:]
            branch = head.split("...")[0].replace("No commits yet on ", "")
            m = re.search(r"ahead (\d+)", head)
            ahead = int(m.group(1)) if m else 0
            m = re.search(r"behind (\d+)", head)
            behind = int(m.group(1)) if m else 0
            out = out[1:]
        return branch, len(out), ahead, behind

    def _scan(self):
        import glob
        import os
        home = os.path.expanduser("~")
        repos = set()
        for pat in self.ROOTS:
            for d in glob.glob(os.path.expanduser(pat)):
                if os.path.isdir(os.path.join(d, ".git")):
                    repos.add(os.path.realpath(d))
        ranked = sorted(repos, key=self._activity, reverse=True)[:self.n_projects]
        projects = []
        for r in ranked:
            branch, changed, ahead, behind = self._git(r)
            projects.append({"path": r, "name": os.path.basename(r) or r,
                             "where": os.path.dirname(r).replace(home, "~", 1),
                             "t": self._activity(r), "branch": branch, "changed": changed,
                             "ahead": ahead, "behind": behind})
        shown = {p["path"] for p in projects}
        folders = []
        try:
            out = subprocess.run(["zoxide", "query", "-ls"], capture_output=True, text=True, timeout=3,
                                 env={**os.environ, "PATH": os.environ.get("PATH", "") + ":" + home + "/.cargo/bin"}).stdout
        except (OSError, subprocess.TimeoutExpired):
            out = ""
        for line in out.splitlines():
            score, _, path = line.strip().partition(" ")
            path = path.strip()
            if not path or path in shown or path == home or not os.path.isdir(path):
                continue
            folders.append({"path": path, "name": os.path.basename(path) or path,
                            "where": os.path.dirname(path).replace(home, "~", 1), "score": float(score or 0)})
            if len(folders) >= self.n_folders:
                break
        self.projects, self.folders, self.scanned = projects, folders, time.time()

    # ------------------------------------------------------------ actions
    def _spawn(self, argv, cwd):
        subprocess.Popen(argv, cwd=cwd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                         start_new_session=True)

    def open_nvim(self, path):
        self._spawn(self.TERM + ["--directory", path, "nvim", "."], path)

    def open_term(self, path):
        self._spawn(self.TERM + ["--directory", path], path)

    def open_files(self, path):
        self._spawn(self.FILES + [path], path)

    # ------------------------------------------------------------ draw
    @staticmethod
    def _ago(t):
        s = max(0, time.time() - t)
        for n, u in ((86400, "d"), (3600, "h"), (60, "m")):
            if s >= n:
                return f"{int(s // n)}{u}"
        return "now"

    def _button(self, cr, x, y, label, tip, action):
        lay = D.layout(cr, label, 10, "semibold", 0.06)
        bw = max(30, lay.get_pixel_size()[0] + 12)
        D.src(cr, "guard", 0.9)
        cr.rectangle(x, y, bw, 18)
        cr.fill()
        cr.set_line_width(1)
        D.src(cr, "dim", 0.9)
        cr.rectangle(x + 0.5, y + 0.5, bw - 1, 17)
        cr.stroke()
        D.text(cr, x + bw / 2, y + 2, label, 10, "phosphor", "semibold", spacing=0.06, align="center")
        self.region(x, y, bw, 18, tip, action)
        return bw

    def _row(self, cr, x0, x1, y, item, meta, meta_col, tip):
        path = item["path"]
        bx = x1
        for label, verb, act in (("DIR", "Open in Dolphin", self.open_files),
                                 (">_", "Open a terminal here", self.open_term),
                                 ("NVIM", "Open in nvim (in kitty)", self.open_nvim)):
            bw = max(30, D.layout(cr, label, 10, "semibold", 0.06).get_pixel_size()[0] + 12)
            bx -= bw
            self._button(cr, bx, y + 3, label, f"{verb}: {item['where']}/{item['name']}",
                         lambda p=path, a=act: a(p))
            bx -= 4
        name_w = bx - x0 - 8
        D.text(cr, x0, y + 1, item["name"], 12, "soft", "semibold", width=name_w)
        nw = min(name_w, D.layout(cr, item["name"], 12, "semibold").get_pixel_size()[0])
        D.text(cr, x0 + nw + 8, y + 3, meta, 10, meta_col, "regular", width=max(0, name_w - nw - 8))
        self.region(x0, y, bx - x0 - 4, self.ROW - 2, tip + " Click to open it in nvim.",
                    lambda p=path: self.open_nvim(p))

    def draw(self, cr, w, h):
        right = "SCANNING" if not self.scanned else f"{len(self.projects)} PROJECTS · {len(self.folders)} FOLDERS"
        top = D.frame(cr, w, h, self.title, right)
        self.region(0, 0, w, 34, "Your recent projects (git repos ranked by your last commit, checkout or "
                    "staging) and the folders you visit most (zoxide: `z name` jumps there in a shell). "
                    "Click a row for nvim; NVIM, >_ and DIR open nvim, a terminal or Dolphin there. "
                    "Rescans every minute.")
        x0, x1 = 16, w - 16
        y = top
        D.label(cr, x0, y + 2, "RECENT PROJECTS", "phosphor", size=10)
        D.rule(cr, x0 + 130, y + 9, x1, "dim", 0.35)
        y += self.HEAD
        for p in self.projects:
            bits, col = [], "static"
            if p["branch"]:
                bits.append(p["branch"])
            if p["changed"]:
                bits.append(f"{p['changed']} changed")
                col = "amber"
            if p["ahead"]:
                bits.append(f"↑{p['ahead']}")
            if p["behind"]:
                bits.append(f"↓{p['behind']}")
            bits.append(self._ago(p["t"]))
            tip = (f"{p['where']}/{p['name']}: on {p['branch'] or '?'}, "
                   f"{p['changed']} uncommitted file(s), {p['ahead']} to push, {p['behind']} to pull, "
                   f"last activity {self._ago(p['t'])} ago.")
            self._row(cr, x0, x1, y, p, " · ".join(bits), col, tip)
            y += self.ROW
        y += 4
        D.label(cr, x0, y + 2, "FREQUENT FOLDERS", "phosphor", size=10)
        D.rule(cr, x0 + 140, y + 9, x1, "dim", 0.35)
        y += self.HEAD
        if not self.folders and self.scanned:
            D.text(cr, x0, y + 2, "Nothing yet: zoxide learns as you cd around.", 11, "static", "regular")
        for f in self.folders:
            tip = f"{f['where']}/{f['name']}: one of your most-visited folders (zoxide score {f['score']:.0f})."
            self._row(cr, x0, x1, y, f, f["where"], "static", tip)
            y += self.ROW


# =================================================================== SHORTCUTS
class ShortcutsPanel(Panel):
    """Live Hyprland keybinds as keycaps, Bromigos sections first. Scroll to move; click a
    Bromigos, launch or capture line to run it (window, workspace, system and hold-to-use
    binds stay keyboard-only)."""
    name, title = "shortcuts", "SHORTCUTS"
    height = 384
    interval = 5.0
    ROW, HEAD = 24, 26
    RUNNABLE = None                         # keybinds.RUNNABLE, set in __init__

    def __init__(self, cfg=None):
        super().__init__(cfg)
        import keybinds
        self.kb = keybinds
        self.RUNNABLE = tuple(keybinds.RUNNABLE)
        self.items, self.mtime, self.offset = [], -1, 0
        self.tick()

    def tick(self):
        m = self.kb.config_mtime()
        if m != self.mtime:
            self.mtime = m
            self.items = self.kb.shortcuts()

    def content_height(self):
        return getattr(self, "_content_h", 0) or len(self.items) * self.ROW

    @staticmethod
    def _split(desc):
        """'Holo deck (also M3)' -> ('Holo deck', 'also M3'): the alternate key goes on a dim second line."""
        import re
        m = re.search(r"\s*\((also [^)]*)\)\s*$", desc)
        return (desc[:m.start()], m.group(1)) if m else (desc, None)

    def scroll(self, dy):
        view = self.height - 44 - 10
        self.offset = max(0, min(max(0, self.content_height() - view), self.offset + dy * self.ROW * 3))

    def keycap(self, cr, x, y, label):
        lay = D.layout(cr, label, 11, "semibold", 0.04)
        w = lay.get_pixel_size()[0] + 12
        D.src(cr, "guard", 0.9)
        cr.rectangle(x, y, w, 18)
        cr.fill()
        cr.set_line_width(1)
        D.src(cr, "dim", 0.9)
        cr.rectangle(x + 0.5, y + 0.5, w - 1, 17)
        cr.stroke()
        D.src(cr, "phosphor", 0.55)
        cr.move_to(x + 1, y + 17.5)
        cr.line_to(x + w - 1, y + 17.5)
        cr.stroke()
        D.text(cr, x + 6, y + 1, label, 11, "soft", "semibold", spacing=0.04)
        return w

    def draw(self, cr, w, h):
        top = D.frame(cr, w, h, self.title, f"{len(self.items)} BINDS · SUPER+SHIFT+K SEARCH")
        self.region(0, 0, w, 34, "Every Hyprland keybind, read live from Hyprland (it refreshes when "
                    "the Hyprland config changes). Bromigos keys first. Scroll to move; click a Bromigos, launch or capture line to run it. "
                    "SUPER+SHIFT+K opens a searchable version.")
        x0, x1 = 16, w - 16
        view_top, view_bot = top, h - 10
        cr.save()
        cr.rectangle(0, view_top, w, view_bot - view_top)
        cr.clip()
        y = view_top - self.offset
        y0 = y
        sec = None
        dx = x0 + 200
        for s, keys, desc, action in self.items:
            if s != sec:
                sec = s
                if view_top - self.HEAD <= y <= view_bot:
                    lw = D.layout(cr, s.upper(), 10, "semibold", 0.18).get_pixel_size()[0]
                    D.label(cr, x0, y + 6, s, "phosphor", size=10)
                    D.rule(cr, x0 + lw + 10, y + 13, x1, "dim", 0.35)
                y += self.HEAD
            main, alt = self._split(desc)
            if main.startswith(s + ": "):            # "VECTOR: hold to talk" under VECTOR -> "hold to talk"
                main = main[len(s) + 2:]
                main = main[:1].upper() + main[1:]
            kx = x0
            for k in keys:
                kx += D.layout(cr, k, 11, "semibold", 0.04).get_pixel_size()[0] + 12 + 12
            tx = max(kx, dx)
            tw = x1 - tx
            mh = D.layout(cr, main, 12, "regular", 0, tw, wrap=True).get_pixel_size()[1]
            ah = D.layout(cr, alt, 10, "regular", 0, tw, wrap=True).get_pixel_size()[1] if alt else 0
            rh = max(self.ROW, mh + ah + 6)
            if view_top - rh <= y <= view_bot:
                kx = x0
                for i, k in enumerate(keys):
                    if i:
                        D.text(cr, kx + 2, y + 2, "+", 10, "static", "regular")
                        kx += 12
                    kx += self.keycap(cr, kx, y + 1, k)
                D.text(cr, tx, y + 2, main, 12, "soft", "regular", width=tw, wrap=True)
                if alt:
                    D.text(cr, tx, y + 2 + mh, alt, 10, "static", "regular", width=tw, wrap=True)
                runnable = action and s in self.RUNNABLE
                tip = f"{' + '.join(keys)}: {desc}." + (" Click to run it now." if runnable else "")
                if view_top <= y and y + rh <= view_bot:
                    self.region(x0, y, x1 - x0, rh - 2, tip,
                                (lambda a=action: self.kb.run(a)) if runnable else None)
            y += rh
        self._content_h = y - y0
        cr.restore()
        # scroll position rail
        total = self.content_height()
        view = view_bot - view_top
        if total > view:
            th = max(24, view * view / total)
            ty = view_top + (view - th) * self.offset / (total - view)
            D.src(cr, "guard", 1)
            cr.rectangle(w - 6, view_top, 2, view)
            cr.fill()
            D.src(cr, "phosphor", 0.8)
            cr.rectangle(w - 6, ty, 2, th)
            cr.fill()


# =================================================================== WEATHER
# Open-Meteo (open-meteo.com, free, no key; the forecast is CC BY 4.0, credited in the
# header's tooltip). The location is ~/.config/bromigos/weather.toml (lat/lon, or a place
# name geocoded through Open-Meteo's own geocoder) or the panel's keys in layout.json;
# nothing is fetched until one is set. Off by default in the layout.
WMO = {0: "clear", 1: "mostly clear", 2: "partly cloudy", 3: "overcast", 45: "fog", 48: "rime fog",
       51: "light drizzle", 53: "drizzle", 55: "heavy drizzle", 56: "freezing drizzle", 57: "freezing drizzle",
       61: "light rain", 63: "rain", 65: "heavy rain", 66: "freezing rain", 67: "freezing rain",
       71: "light snow", 73: "snow", 75: "heavy snow", 77: "snow grains", 80: "showers", 81: "showers",
       82: "violent showers", 85: "snow showers", 86: "snow showers", 95: "thunderstorm",
       96: "thunderstorm, hail", 99: "thunderstorm, hail"}


class WeatherPanel(Panel):
    name, title = "weather", "WEATHER"
    height = 300
    interval = 60.0                    # the draw refresh; the fetch is its own thread, every 10 min

    def __init__(self, cfg=None):
        super().__init__(cfg)
        self.loc = self._location()
        self.data = None
        self.error = None
        self.fetched = 0
        self.units = (self.loc or {}).get("units", "metric")
        if self.loc:
            threading.Thread(target=self._loop, daemon=True, name="weather").start()

    def _location(self):
        """layout.json's keys, then ~/.config/bromigos/weather.toml over them."""
        loc = {k: self.cfg[k] for k in ("lat", "lon", "place", "name", "units") if k in self.cfg}
        path = os.path.join(os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config"),
                            "bromigos", "weather.toml")
        try:
            import tomllib
            with open(path, "rb") as f:
                loc.update(tomllib.load(f))
        except (OSError, ValueError):
            pass
        if "lat" in loc and "lon" in loc or loc.get("place"):
            return loc
        return None

    def _geocode(self, place):
        import urllib.parse
        url = "https://geocoding-api.open-meteo.com/v1/search?count=1&language=en&name=" + urllib.parse.quote(place)
        with urllib.request.urlopen(url, timeout=10) as r:
            hit = (json.load(r).get("results") or [None])[0]
        if not hit:
            raise ValueError(f"no place called {place!r}")
        self.loc.update(lat=hit["latitude"], lon=hit["longitude"])
        self.loc.setdefault("name", hit.get("name", place))

    def _fetch(self):
        if "lat" not in self.loc:
            self._geocode(self.loc["place"])
        imperial = self.units == "imperial"
        q = {"latitude": self.loc["lat"], "longitude": self.loc["lon"], "timezone": "auto", "forecast_days": 4,
             "current": "temperature_2m,relative_humidity_2m,apparent_temperature,weather_code,wind_speed_10m,"
                        "wind_direction_10m,precipitation,is_day",
             "hourly": "temperature_2m,precipitation_probability",
             "daily": "weather_code,temperature_2m_max,temperature_2m_min,precipitation_probability_max,sunrise,sunset"}
        if imperial:
            q.update(temperature_unit="fahrenheit", wind_speed_unit="mph", precipitation_unit="inch")
        import urllib.parse
        url = "https://api.open-meteo.com/v1/forecast?" + urllib.parse.urlencode(q)
        with urllib.request.urlopen(url, timeout=15) as r:
            return json.load(r)

    def _loop(self):
        while True:
            try:
                self.data = self._fetch()
                self.error = None
            except Exception as e:                   # noqa: BLE001  (shown in the panel, never raised)
                self.error = str(e)[:80]
            self.fetched = time.time()
            time.sleep(600)

    @staticmethod
    def _words(code):
        return WMO.get(int(code or 0), "weather")

    def draw(self, cr, w, h):
        deg = "°F" if self.units == "imperial" else "°C"
        spd = "mph" if self.units == "imperial" else "km/h"
        right = (self.loc or {}).get("name") or (self.loc or {}).get("place") or ""
        top = D.frame(cr, w, h, self.title, right.upper()[:22] if right else None)
        self.region(0, 0, w, 34, "Forecast by Open-Meteo (open-meteo.com, CC BY 4.0), refreshed every 10 minutes"
                    + (f" for {right}" if right else "") + ". Click to open the site.",
                    lambda: open_url("https://open-meteo.com/"))
        if not self.loc:
            D.label(cr, 16, top + 8, "NO LOCATION SET", "amber")
            D.text(cr, 16, top + 30, "Put lat/lon or place = \"a city\" in ~/.config/bromigos/weather.toml", 10, "static",
                   width=w - 32, wrap=True)
            self.region(0, top, w, h - top, "The weather needs a location: lat and lon, or a place name (geocoded "
                        "by Open-Meteo), in ~/.config/bromigos/weather.toml; units = \"imperial\" for °F and mph")
            return
        d = self.data
        if d is None:
            D.label(cr, 16, top + 8, "FETCHING…" if not self.error else "NO FORECAST", "amber" if self.error else "static")
            if self.error:
                D.text(cr, 16, top + 28, self.error, 10, "static", width=w - 32, wrap=True)
            self.region(0, top, w, h - top, self.error or "Waiting for the first forecast")
            return
        cur = d["current"]
        t = cur["temperature_2m"]
        code = cur.get("weather_code", 0)
        tw = D.seg7(cr, 16, top + 6, 44, f"{t:.0f}", "phosphor")
        D.text(cr, 16 + tw + 6, top + 6, deg, 14, "phosphor", "bold")
        D.label(cr, 16, top + 58, self._words(code), "soft", size=11)
        self.region(16, top, 150, 74, f"{t:.1f}{deg} now, {self._words(code)}; feels like "
                    f"{cur.get('apparent_temperature', t):.0f}{deg}")
        # the readings column
        x = 190
        rows = [("FEELS", f"{cur.get('apparent_temperature', t):.0f}{deg}", "How it feels: temperature with wind and humidity"),
                ("HUMID", f"{cur.get('relative_humidity_2m', 0):.0f}%", "Relative humidity"),
                ("WIND", f"{cur.get('wind_speed_10m', 0):.0f} {spd} {self._dir(cur.get('wind_direction_10m'))}",
                 "Wind at 10 m, and where it blows from"),
                ("RAIN", f"{cur.get('precipitation', 0):.1f} {'in' if self.units == 'imperial' else 'mm'}",
                 "Precipitation in the last hour")]
        for i, (k, v, tip) in enumerate(rows):
            y = top + 6 + i * 17
            D.label(cr, x, y, k, "dim", size=10)
            D.text(cr, x + 58, y - 1, v, 11, "soft")
            self.region(x, y - 2, w - x - 16, 17, tip)
        # the next 24 hours: temperature line, rain chance as faint bars
        hy = top + 86
        D.label(cr, 16, hy, "NEXT 24 H", "dim", size=10)
        hours = d.get("hourly", {})
        now_i = self._hour_index(hours.get("time", []), d.get("current", {}).get("time"))
        temps = hours.get("temperature_2m", [])[now_i:now_i + 24]
        rain = hours.get("precipitation_probability", [])[now_i:now_i + 24]
        gx, gy, gw, gh = 16, hy + 16, w - 32, 48
        if rain:
            bw = gw / len(rain)
            for i, p in enumerate(rain):
                if p:
                    D.src(cr, "cyan", 0.08 + 0.25 * (p or 0) / 100)
                    cr.rectangle(gx + i * bw, gy + gh - gh * (p or 0) / 100, bw - 1, gh * (p or 0) / 100)
                    cr.fill()
        if temps:
            D.spark(cr, gx, gy, gw, gh, temps, "phosphor")
            D.label(cr, w - 16, hy, f"{min(temps):.0f}–{max(temps):.0f}{deg}", "soft", size=10, align="right")
        self.region(gx, hy, gw, gh + 16, "The next 24 hours: temperature as the line, chance of rain as the bars"
                    + (f" (peak {max(rain or [0]):.0f}%)" if rain else ""))
        # the days
        dy = gy + gh + 12
        daily = d.get("daily", {})
        names = ["TODAY", "TOMORROW"]
        for i in range(min(3, len(daily.get("time", [])))):
            y = dy + i * 18
            when = names[i] if i < 2 else self._weekday(daily["time"][i])
            D.label(cr, 16, y, when, "dim", size=10)
            D.text(cr, 130, y - 1, self._words(daily["weather_code"][i]), 11, "soft")
            hi, lo = daily["temperature_2m_max"][i], daily["temperature_2m_min"][i]
            D.text(cr, w - 16, y - 1, f"{lo:.0f} / {hi:.0f}{deg}  {daily['precipitation_probability_max'][i] or 0:.0f}%",
                   11, "soft", align="right")
            self.region(16, y - 2, w - 32, 18, f"{when.title()}: {self._words(daily['weather_code'][i])}, "
                        f"low {lo:.0f}{deg}, high {hi:.0f}{deg}, up to {daily['precipitation_probability_max'][i] or 0:.0f}% "
                        f"chance of rain; sunrise {daily['sunrise'][i][-5:]}, sunset {daily['sunset'][i][-5:]}")

    @staticmethod
    def _dir(deg):
        if deg is None:
            return ""
        return "N NE E SE S SW W NW".split()[int((deg + 22.5) // 45) % 8]

    @staticmethod
    def _hour_index(times, now):
        if not times or not now:
            return 0
        stamp = now[:13]
        for i, t in enumerate(times):
            if t[:13] >= stamp:
                return i
        return 0

    @staticmethod
    def _weekday(day):
        import datetime
        try:
            return datetime.date.fromisoformat(day).strftime("%A").upper()
        except ValueError:
            return day


# =================================================================== CONNECTIONS
# NetworkManager, through nmcli: what's connected, the Wi-Fi networks in reach (click one
# to join: a saved one connects, a new secured one opens nmtui in a terminal), the VPNs
# (click to bring one up or down), and the Wi-Fi radio switch.
def _nmcli(*args, timeout=8):
    try:
        out = subprocess.run(["nmcli", "-t", "--escape", "no", *args], capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.SubprocessError):
        return None
    return out.stdout if out.returncode == 0 else None


class ConnectionsPanel(Panel):
    name, title = "connections", "CONNECTIONS"
    height = 262
    interval = 15.0

    def __init__(self, cfg=None):
        super().__init__(cfg)
        self.active, self.wifi, self.vpns, self.saved = [], [], [], set()
        self.radio = None
        self.have_nm = False
        self.pending = {}                              # name -> time of a click still being carried out
        threading.Thread(target=self._loop, daemon=True, name="connections").start()

    def _sample(self):
        act = _nmcli("-f", "NAME,TYPE,DEVICE,STATE", "connection", "show", "--active")
        if act is None:
            self.have_nm = False
            return
        self.have_nm = True
        self.active = [dict(zip(("name", "type", "device", "state"), l.split(":", 3)))
                       for l in act.splitlines() if l.count(":") >= 3]
        saved = _nmcli("-f", "NAME,TYPE", "connection", "show") or ""
        self.saved = {l.split(":", 1)[0] for l in saved.splitlines() if l}
        self.vpns = [dict(zip(("name", "type"), l.split(":", 1))) for l in saved.splitlines()
                     if l.split(":", 1)[-1] in ("vpn", "wireguard", "tun")]
        radio = (_nmcli("radio", "wifi") or "").strip()
        self.radio = radio == "enabled" if radio else None
        wifi = _nmcli("-f", "IN-USE,SSID,SIGNAL,SECURITY", "device", "wifi", "list", "--rescan", "no") or ""
        seen, rows = set(), []
        for l in wifi.splitlines():
            p = l.split(":", 3)
            if len(p) < 4 or not p[1] or p[1] in seen:
                continue
            seen.add(p[1])
            rows.append({"used": p[0].strip() == "*", "ssid": p[1], "signal": int(p[2] or 0), "sec": p[3]})
        rows.sort(key=lambda r: (not r["used"], -r["signal"]))
        self.wifi = rows[:6]

    def _loop(self):
        while True:
            self._sample()
            time.sleep(self.interval)

    def _run(self, name, *args):
        """Carry out a click off the draw thread; the row shows '…' meanwhile."""
        self.pending[name] = time.time()

        def go():
            subprocess.run(["nmcli", *args], capture_output=True, timeout=60)
            self._sample()
            self.pending.pop(name, None)
        threading.Thread(target=go, daemon=True).start()

    def _join(self, net):
        if net["used"]:
            return
        if net["ssid"] in self.saved:
            self._run(net["ssid"], "connection", "up", "id", net["ssid"])
        elif not net["sec"] or net["sec"] == "--":
            self._run(net["ssid"], "device", "wifi", "connect", net["ssid"])
        else:                                          # a password is needed: nmtui asks for it
            subprocess.Popen(["kitty", "--title", "connect", "-e", "nmtui", "connect", net["ssid"]],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)

    def draw(self, cr, w, h):
        top = D.frame(cr, w, h, self.title)
        self.region(0, 0, w, 34, "NetworkManager: what's connected, the Wi-Fi in reach and the VPNs. "
                    "Click a network to join it, a VPN to toggle it, the switch to turn Wi-Fi off and on.")
        if not self.have_nm:
            D.label(cr, 16, top + 8, "NETWORKMANAGER NOT RUNNING", "amber")
            self.region(0, top, w, h - top, "nmcli answered nothing: NetworkManager isn't running or isn't installed")
            return
        # the Wi-Fi switch, top right
        if self.radio is not None:
            lbl = "WIFI ON" if self.radio else "WIFI OFF"
            lay = D.layout(cr, lbl, 10, "semibold", 0.06)
            bw = lay.get_pixel_size()[0] + 14
            bx, by = w - 16 - bw, 9
            D.src(cr, "phosphor" if self.radio else "guard", 0.9 if not self.radio else 0.18)
            cr.rectangle(bx, by, bw, 16)
            cr.fill()
            D.src(cr, "phosphor" if self.radio else "dim", 0.9)
            cr.rectangle(bx + 0.5, by + 0.5, bw - 1, 15)
            cr.stroke()
            D.text(cr, bx + bw / 2, by + 1, lbl, 10, "phosphor" if self.radio else "static", "semibold", spacing=0.06,
                   align="center")
            self.region(bx, by, bw, 16, "The Wi-Fi radio. Click to turn it " + ("off" if self.radio else "on"),
                        lambda: self._run("radio", "radio", "wifi", "off" if self.radio else "on"))
        y = top + 4
        # active connections
        conns = [a for a in self.active if a["type"] not in ("loopback",)]
        if not conns:
            D.label(cr, 16, y + 2, "NOT CONNECTED", "amber", size=10)
            y += 18
        for a in conns[:3]:
            D.dot(cr, 22, y + 7, 3, "phosphor")
            kind = a["type"].replace("802-11-wireless", "wifi").replace("802-3-ethernet", "ethernet")
            D.text(cr, 34, y - 1, a["name"][:26], 11, "soft", "semibold")
            D.label(cr, w - 16, y + 1, f"{kind} · {a['device']}", "static", size=9, align="right")
            self.region(16, y - 2, w - 32, 17, f"Connected: {a['name']} ({kind} on {a['device']}, {a['state']})")
            y += 17
        y += 4
        D.rule(cr, 16, y, w - 16)
        y += 8
        # wi-fi in reach
        D.label(cr, 16, y, "WI-FI IN REACH", "dim", size=10)
        y += 16
        if not self.wifi:
            D.text(cr, 16, y - 1, "none seen" if self.radio else "radio off", 10, "static")
            y += 16
        for net in self.wifi[:4]:
            col = "phosphor" if net["used"] else "soft"
            busy = net["ssid"] in self.pending
            D.text(cr, 16, y - 1, ("… " if busy else "") + net["ssid"][:24], 11, col, "semibold" if net["used"] else "medium")
            D.cells(cr, w - 16 - 60, y + 3, 44, 8, net["signal"] / 100, n=6, warn=2, crit=2, gap=2)
            D.label(cr, w - 16, y + 1, "" if net["sec"] in ("", "--") else "🔒", col, size=9, align="right")
            secured = net["sec"] not in ("", "--")
            tip = (f"{net['ssid']}: signal {net['signal']}%, {net['sec'] if secured else 'open'}"
                   + (". Connected." if net["used"] else
                      (". Click to connect (saved)." if net["ssid"] in self.saved else
                       ". Click to connect; nmtui asks for the password." if secured else ". Click to connect.")))
            self.region(16, y - 2, w - 32, 17, tip, None if net["used"] else (lambda n=net: self._join(n)))
            y += 17
        # vpns
        if self.vpns:
            y += 4
            D.rule(cr, 16, y, w - 16)
            y += 8
            D.label(cr, 16, y, "VPN", "dim", size=10)
            y += 16
            up = {a["name"] for a in self.active}
            for v in self.vpns[:3]:
                on = v["name"] in up
                busy = v["name"] in self.pending
                D.dot(cr, 22, y + 7, 3, "phosphor" if on else "static", glow=on)
                D.text(cr, 34, y - 1, ("… " if busy else "") + v["name"][:26], 11, "phosphor" if on else "soft")
                D.label(cr, w - 16, y + 1, ("UP" if on else "DOWN") + f" · {v['type']}", "phosphor" if on else "static",
                        size=9, align="right")
                self.region(16, y - 2, w - 32, 17, f"VPN {v['name']} ({v['type']}) is {'up' if on else 'down'}. "
                            f"Click to bring it {'down' if on else 'up'}.",
                            lambda n=v["name"], o=on: self._run(n, "connection", "down" if o else "up", "id", n))
                y += 17
