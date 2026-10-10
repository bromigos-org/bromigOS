"""The desktop panels. Each one draws real readings only; every hoverable region
carries a tooltip saying what it is, and clickable ones say what a click does."""
import json
import math
import os
import subprocess
import threading
import time
import urllib.request
from collections import deque

import cairo

import draw as D
import sources as S

# The widget gallery's categories (a panel's `category`), in the order it lists them.
CATEGORIES = ("system", "network", "homelab", "media", "notes", "fun")
# The size classes a panel can declare (its `sizes`), smallest first
# (docs/widgets.md, "Size classes").
SIZE_CLASSES = ("compact", "standard", "wide", "tall", "large")


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
    # What the widget gallery says about it (docs/plugins.md, "What the gallery shows"):
    description = ""                    # one line: what it shows
    category = "system"                 # one of CATEGORIES
    reads = ""                          # what it reads, in a few words: "your CPU and memory"
    # the sizes edit mode lets it take (px): (width, height)
    min_size = (240, 120)
    max_size = (1600, 1400)
    # Size classes (docs/widgets.md, "Size classes"): {class: (min, max)} or
    # {class: (min, max, start)}, each a (width, height) in px; the class names are
    # SIZE_CLASSES. Edit mode resizes freely inside a class and snaps between them, and
    # draw() lays the panel out for size_class(w, h). Empty: one class, "standard", from
    # min_size to max_size, and the panel just scales.
    sizes = {}
    default_size = "standard"           # the class a panel starts at (Add to desktop)

    @classmethod
    def available(cls):
        """Whether this panel can show anything here: True, or (False, "why"), such as
        (False, "no media source configured"). The widget gallery leaves an unavailable
        panel out of what can be added, and greys it out, with the reason, while it's on the
        desktop. Called once each time the gallery opens: keep it cheap, with no network."""
        return True

    @classmethod
    def size_classes(cls):
        """[(name, min, max, start)] in SIZE_CLASSES order: the declared classes, else one
        "standard" class spanning min_size to max_size."""
        out = []
        for name in SIZE_CLASSES:
            spec = (cls.sizes or {}).get(name)
            if not spec:
                continue
            lo, hi = tuple(spec[0]), tuple(spec[1])
            start = tuple(spec[2]) if len(spec) > 2 else lo
            out.append((name, lo, hi, start))
        if not out:
            out = [("standard", tuple(cls.min_size), tuple(cls.max_size), (cls.width, cls.height))]
        return out

    @classmethod
    def limits(cls):
        """The smallest and largest (width, height) over every class."""
        cs = cls.size_classes()
        return ((min(c[1][0] for c in cs), min(c[1][1] for c in cs)),
                (max(c[2][0] for c in cs), max(c[2][1] for c in cs)))

    @classmethod
    def size_class(cls, w, h):
        """The class a (w, h) panel is in: the one whose range holds it, else the nearest
        (a layout.json written by hand can hold any size)."""
        best, dist = None, None
        for name, lo, hi, _start in cls.size_classes():
            dx = max(lo[0] - w, 0, w - hi[0])
            dy = max(lo[1] - h, 0, h - hi[1])
            d = dx * dx + dy * dy
            if dist is None or d < dist:
                best, dist = name, d
        return best

    @classmethod
    def start_size(cls, name=None):
        """The size a class starts at (default_size's when name is None)."""
        cs = cls.size_classes()
        want = name or cls.default_size
        return next((c[3] for c in cs if c[0] == want), cs[0][3] if cs else (cls.width, cls.height))

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
    description = "CPU and threads, a load waterfall, memory, video memory, the GPU, uptime"
    category, reads = "system", "your CPU, memory, GPU, temperatures and processes"
    height = 452
    interval = 2.0
    sizes = {"compact": ((240, 150), (420, 300), (300, 180)),
             "standard": ((460, 452), (700, 640), (470, 470)),
             "large": ((760, 600), (1300, 1100), (900, 720))}

    def __init__(self, cfg=None):
        super().__init__(cfg)
        self.sys = S.System(history=200)   # 200 x 2 s = 6:40 of waterfall
        self.drawn = "standard"
        self.procs = []

    def tick(self):
        self.sys.sample()
        if self.drawn == "large":           # the busiest processes: only while they're shown
            self.procs = S.top_processes(getattr(self, "proc_rows", 8))

    def draw(self, cr, w, h):
        self.drawn = self.size_class(w, h)
        if self.drawn == "compact":
            return self._compact(cr, w, h)
        if self.drawn == "large":
            return self._large(cr, w, h)
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

    def _compact(self, cr, w, h):
        """One CPU ring, and memory, the GPU and the temperature beside it."""
        s = self.sys
        top = D.frame(cr, w, h, self.title, f"{s.cores} THREADS")
        self.region(0, 0, w, 34, f"This machine: host {s.host}, {s.os}, kernel {s.kernel}")
        r = max(24, min((h - top - 14) / 2, (w - 32) / 4, 64))
        cx, cy = 16 + r, top + (h - top - 10) / 2
        col = D.level(s.total, 70, 90)
        D.ring(cr, cx, cy, r - 4, s.total / 100, max(4, r / 7), col)
        D.text(cr, cx, cy - r * 0.32, f"{s.total:.0f}%", max(12, r * 0.42), col, "bold", align="center", glow=True)
        D.label(cr, cx, cy + r * 0.22, "CPU", "dim", size=max(9, int(r * 0.2)), align="center")
        self.region(cx - r, cy - r, 2 * r, 2 * r, f"CPU load across all {s.cores} threads (2 s average)")
        x0, x1 = cx + r + 16, w - 16
        y = top + 2
        m = s.mem
        rows = [("RAM", m.used / m.total, f"{100 * m.used / m.total:.0f}%",
                 f"Memory in use: {S.human(m.used)} of {S.human(m.total)}")]
        if s.g:
            g = s.g
            rows.append(("GPU", g["util"] / 100, f"{g['util']}%", f"{s.gpu.name}: {g['util']}% busy, {g['temp']} °C"))
            rows.append(("VRAM", g["vram_used"] / g["vram_total"], f"{100 * g['vram_used'] / g['vram_total']:.0f}%",
                         f"Video memory: {S.human(g['vram_used'])} of {S.human(g['vram_total'])}"))
        step = max(26, min(40, (h - top - 30) / max(1, len(rows) + 1)))
        for name, frac, right, tip in rows:
            if y + 24 > h - 24:
                break
            D.label(cr, x0, y, name, "dim")
            D.label(cr, x1, y, right, "soft", align="right")
            D.cells(cr, x0, y + 16, x1 - x0, 7, frac, n=max(8, int((x1 - x0) / 9)))
            self.region(x0, y, x1 - x0, 26, tip)
            y += step
        ctemp = s.temps.get("CPU")
        la = s.load
        foot = (f"{ctemp:.0f}°C · " if ctemp is not None else "") + f"LOAD {la[0]:.1f}"
        D.label(cr, x0, h - 22, foot, D.level(ctemp, 80, 90) if ctemp is not None else "soft")
        self.region(x0, h - 26, x1 - x0, 18, (f"CPU package {ctemp:.0f} °C; " if ctemp is not None else "")
                    + f"load average over a minute {la[0]:.2f}")

    def _large(self, cr, w, h):
        """Everything: the threads now and over time, memory, the GPU, every temperature
        and the busiest processes."""
        s = self.sys
        top = D.frame(cr, w, h, self.title, f"{s.host} · {s.os} {s.kernel.split('-')[0]}")
        self.region(0, 0, w, 34, f"This machine: host {s.host}, {s.os}, kernel {s.kernel}")
        x0, x1 = 16, w - 16
        mid = int(w * 0.56)
        # --- left: CPU now, each thread's history, the waterfall
        D.label(cr, x0, top, "CPU", "dim")
        col = D.level(s.total, 70, 90)
        D.seg7(cr, x0, top + 18, 44, f"{s.total:3.0f}", col)
        D.text(cr, x0 + 114, top + 42, "%", 18, col, "bold")
        self.region(x0, top, 140, 84, f"CPU load across all {s.cores} threads (2 s average)")
        D.label(cr, mid - 16, top, f"{s.cores} THREADS · EACH OVER THE LAST {S.duration(len(s.history) * 2)}",
                "dim", align="right")
        gx, gy, gw = x0 + 150, top + 18, mid - 16 - (x0 + 150)
        cols = 6 if s.cores > 12 else 4
        rows = math.ceil(s.cores / cols)
        cw = (gw - (cols - 1) * 6) / cols
        ch = max(24, min(44, (h * 0.36) / max(1, rows) - 6))
        hist = list(s.history)
        for i in range(s.cores):
            r_, c = divmod(i, cols)
            cx, cy = gx + c * (cw + 6), gy + r_ * (ch + 6)
            vals = [smp[i] for smp in hist[-60:] if i < len(smp)] or [0]
            v = s.per[i] if i < len(s.per) else 0
            colr = "danger" if v >= 95 else "amber" if v >= 80 else "phosphor"
            D.src(cr, "void", 0.8)
            cr.rectangle(cx, cy, cw, ch)
            cr.fill()
            D.label(cr, cx + 3, cy + 1, f"{i}", "static", size=8)
            D.label(cr, cx + cw - 3, cy + 1, f"{v:.0f}", colr, size=8, align="right")
            D.spark(cr, cx + 1, cy + 12, cw - 2, ch - 14, vals, colr, lo=0, hi=100)
            self.region(cx, cy, cw, ch, f"CPU thread {i}: {v:.0f}% now; the line is its last 2 minutes")
        wy = max(top + 100, gy + rows * (ch + 6) + 10)
        D.label(cr, x0, wy, "LOAD WATERFALL", "dim")
        D.label(cr, mid - 16, wy, f"LAST {S.duration(len(s.history) * self.interval)}", "static", align="right")
        room = h - 30 - (wy + 18) - 12
        wh = max(40, min(int(room * 0.55), s.cores * 8))
        self._waterfall(cr, x0, wy + 18, mid - 16 - x0, wh)
        self.region(x0, wy + 18, mid - 16 - x0, wh, "Load waterfall: one row per CPU thread, one column "
                    "per 2 s sample, brighter = busier; newest at the right")
        # the whole CPU over the same time, as a line
        hy = wy + 18 + wh + 14
        hh = h - 30 - hy - 12
        if hh > 40:
            tot = [sum(smp) / max(1, len(smp)) for smp in hist]
            D.label(cr, x0, hy, "ALL THREADS", "dim")
            D.label(cr, mid - 16, hy, f"PEAK {max(tot or [0]):.0f}% · AVERAGE {sum(tot) / max(1, len(tot)):.0f}%",
                    "static", align="right")
            top_pct = max(10.0, math.ceil(max(tot or [0]) * 1.25 / 10) * 10)
            gx0, gy0, gw_, gh_ = x0 + 30, hy + 18, mid - 16 - x0 - 30, hh - 20
            D.src(cr, "void", 0.8)
            cr.rectangle(gx0, gy0, gw_, gh_)
            cr.fill()
            cr.set_line_width(1)
            for k in range(5):                       # the scale: four steps up to the top
                ly = round(gy0 + gh_ - gh_ * k / 4) + 0.5
                D.src(cr, "guard", 1)
                cr.move_to(gx0, ly)
                cr.line_to(gx0 + gw_, ly)
                cr.stroke()
                D.label(cr, gx0 - 4, ly - 6, f"{top_pct * k / 4:.0f}", "static", size=8, align="right")
            D.spark(cr, gx0 + 1, gy0 + 1, gw_ - 2, gh_ - 2, tot or [0, 0], "phosphor", lo=0, hi=top_pct)
            self.region(x0, hy, mid - 16 - x0, hh, "All threads together over the last "
                        f"{S.duration(len(hist) * self.interval)}: the CPU's load as one line")
        # --- right: memory, the GPU, temperatures, processes
        rx = mid + 8
        y = top
        m = s.mem
        self._cellrow(cr, rx, x1, y, "RAM", m.used / m.total, f"{S.human(m.used)} / {S.human(m.total)}",
                      f"Memory in use (excludes cache): {S.human(m.used)} of {S.human(m.total)}; "
                      f"{S.human(m.available)} available")
        y += 36
        sw = getattr(s, "swap", None)
        if sw and sw.total:
            self._cellrow(cr, rx, x1, y, "SWAP", sw.used / sw.total, f"{S.human(sw.used)} / {S.human(sw.total)}",
                          f"Swap in use: {S.human(sw.used)} of {S.human(sw.total)}")
            y += 36
        g = s.g
        if g:
            self._cellrow(cr, rx, x1, y, "VRAM", g["vram_used"] / g["vram_total"],
                          f"{S.human(g['vram_used'])} / {S.human(g['vram_total'])}",
                          f"{s.gpu.name} video memory: {S.human(g['vram_used'])} of {S.human(g['vram_total'])}")
            y += 36
            gc = D.level(g["util"], 70, 90)
            D.label(cr, rx, y, "GPU", "dim")
            D.text(cr, rx + 46, y - 3, f"{g['util']:3d}%", 15, gc, "bold")
            D.label(cr, x1, y, f"{s.gpu.name} · {g['watts']:.0f} W", "static", align="right")
            self.region(rx, y - 4, x1 - rx, 22, f"{s.gpu.name}: {g['util']}% busy, drawing {g['watts']:.0f} W (NVML)")
            y += 30
        D.rule(cr, rx, y, x1)
        y += 10
        D.label(cr, rx, y, "TEMPERATURES", "dim")
        y += 18
        for name, t in sorted(s.temps.items()):
            if y > h * 0.62:
                break
            hot = D.level(t, 75, 90)
            D.label(cr, rx, y, name, "soft", size=10)
            D.bar(cr, rx + 70, y + 3, x1 - rx - 130, 6, min(1.0, t / 100), hot)
            D.label(cr, x1, y, f"{t:.0f}°C", hot, size=10, align="right")
            self.region(rx, y - 2, x1 - rx, 16, f"{name}: {t:.0f} °C (amber from 75, red from 90)")
            y += 18
        if not s.temps:
            D.label(cr, rx, y, "NO SENSORS READ", "static", size=10)
            y += 18
        y += 6
        D.rule(cr, rx, y, x1)
        y += 10
        D.label(cr, rx, y, "BUSIEST PROCESSES", "dim")
        D.label(cr, x1, y, "CPU   MEMORY", "dim", align="right")
        y += 18
        self.proc_rows = max(3, int((h - 52 - y) / 17))
        for p in self.procs:
            if y > h - 52:
                break
            c = D.level(p["cpu"], 50, 90)
            D.label(cr, rx, y, p["name"][:22], "soft", size=10)
            D.label(cr, x1 - 70, y, f"{p['cpu']:.0f}%", c, size=10, align="right")
            D.label(cr, x1, y, S.human(p["mem"], digits=0), "static", size=10, align="right")
            self.region(rx, y - 2, x1 - rx, 16, f"{p['name']} (process {p['pid']}): {p['cpu']:.1f}% of one CPU, "
                        f"{S.human(p['mem'])} resident")
            y += 17
        if not self.procs:
            D.label(cr, rx, y, "READING…", "static", size=10)
        # --- footer
        fy = h - 26
        D.rule(cr, x0, fy - 6, x1)
        la = s.load
        D.label(cr, x0, fy, f"LOAD {la[0]:.2f} {la[1]:.2f} {la[2]:.2f}", D.level(la[0] / s.cores, 0.7, 1.0))
        self.region(x0, fy - 2, 220, 18, f"Load average over 1, 5 and 15 minutes ({s.cores} threads)")
        up = time.time() - s.boot
        ses = time.time() - s.session_start
        D.label(cr, x1, fy, f"UP {S.duration(up)} · SESSION {S.duration(ses)}", "soft", align="right")
        self.region(x1 - 240, fy - 2, 240, 18, f"Uptime since boot {S.duration(up)}; this session {S.duration(ses)}")

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
    description = "The interface, a traffic scope, and a latency radar to the hosts you list"
    category, reads = "network", "your network interfaces, pings and connections"
    height = 262
    interval = 1.0
    sizes = {"compact": ((240, 110), (420, 200), (300, 140)),
             "standard": ((380, 240), (640, 420), (470, 262)),
             "wide": ((700, 220), (1400, 420), (940, 262)),
             "large": ((700, 440), (1300, 1000), (900, 620))}

    def __init__(self, cfg=None):
        super().__init__(cfg)
        self.net = S.Net(history=120)
        # {"private": "lan.ping"} expands to the operator's LAN hosts from the private overlay
        cfg = [x for t in self.cfg.get("ping", []) for x in (S.PRIV.get(t["private"], []) if "private" in t else [t])]
        targets = [(t["label"], t.get("host")) for t in cfg if t.get("label")] or [("GATEWAY", None)]
        self.ping = S.Pinger(targets, every=6)
        self.ping.start()
        self.sweep = 0.0
        # the last hour, a minute a point (the wide and large sizes' history)
        self.hour_rx = deque(getattr(self.net, "minutes_rx", []), maxlen=60)
        self.hour_tx = deque(getattr(self.net, "minutes_tx", []), maxlen=60)
        self._acc = [0.0, 0.0, 0]
        self.drawn = "standard"
        self.conns, self._conns_at, self.ifaces = [], 0.0, []

    def tick(self):
        self.net.sample()
        self.sweep = (self.sweep + 30) % 360
        a = self._acc
        a[0] += self.net.rx
        a[1] += self.net.tx
        a[2] += 1
        if a[2] >= 60:
            self.hour_rx.append(a[0] / a[2])
            self.hour_tx.append(a[1] / a[2])
            self._acc = [0.0, 0.0, 0]
        if self.drawn == "large" and time.monotonic() - self._conns_at > 5:
            self._conns_at = time.monotonic()      # who it talks to: only while it's shown
            self.conns = S.connections(10)
            self.ifaces = S.interfaces()

    def draw(self, cr, w, h):
        self.drawn = self.size_class(w, h)
        if self.drawn == "compact":
            return self._compact(cr, w, h)
        n = self.net
        wifi = f" · {n.signal:.0f} dBm" if n.signal is not None else ""
        top = D.frame(cr, w, h, self.title, f"{n.iface or 'NO LINK'}{wifi}",
                      "static" if n.iface else "amber")
        self.region(0, 0, w, 34, (f"Default route via {n.iface}" + (f", Wi-Fi signal {n.signal:.0f} dBm" if wifi else "")
                                  + (f"; address {n.addr} (click to copy)" if n.addr else ""))
                    if n.iface else "No default route: disconnected",
                    (lambda: copy_text(n.addr)) if n.addr else None)
        if self.drawn in ("wide", "large"):
            return self._big(cr, w, h, top)
        self._main(cr, top, 16, w - 16, h - 16)

    def _main(self, cr, top, x0, x1, bottom):
        """The standard panel's body in a box: the readouts, the scope, the radar."""
        n = self.net
        h = bottom + 16
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

    def _compact(self, cr, w, h):
        """The two rates, large, a short trace and the nearest ping."""
        n = self.net
        top = D.frame(cr, w, h, self.title, n.iface or "NO LINK", "static" if n.iface else "amber")
        self.region(0, 0, w, 34, f"Default route via {n.iface}" if n.iface else "No default route: disconnected")
        x0, x1 = 16, w - 16
        half = (x1 - x0) / 2
        for i, (lab, v, col) in enumerate((("RX", n.rx, "phosphor"), ("TX", n.tx, "soft"))):
            x = x0 + i * half
            D.label(cr, x, top, lab, "dim")
            D.text(cr, x, top + 14, S.rate(v), 15 if w < 340 else 18, col, "bold", glow=v > 1024)
            self.region(x, top, half - 8, 40, f"{'Receiving' if lab == 'RX' else 'Sending'} {S.rate(v)} now on {n.iface}")
        sy = top + 46
        if h - sy - 14 > 16:
            D.spark(cr, x0, sy, x1 - x0, h - sy - 14, list(n.rx_hist)[-60:], "phosphor")
            self.region(x0, sy, x1 - x0, h - sy - 14, "Receive rate over the last minute")
        best = min((v for v in self.ping.rtt.values() if v is not None), default=None)
        if best is not None and w >= 280:
            D.label(cr, x1, top, f"{best:.0f} MS", D.level(best, 50, 150), align="right")
            self.region(x1 - 60, top - 2, 60, 16, f"The quickest answer of the hosts it pings: {best:.1f} ms")

    def _big(self, cr, w, h, top):
        """Wide: the standard body and the last hour beside it. Large: those on top, and
        who this machine is talking to below."""
        x0, x1 = 16, w - 16
        upper = h - 16 if self.drawn == "wide" else top + max(220, int((h - top) * 0.5))
        left_w = min(560, int((x1 - x0) * 0.5))
        self._main(cr, top, x0, x0 + left_w, upper)
        hx = x0 + left_w + 24
        self._hour(cr, hx, top, x1 - hx, upper - top)
        if self.drawn == "large":
            half = (x1 - x0 - 24) / 2
            self._connections(cr, x0, upper + 14, half, h - 16 - upper - 14)
            self._interfaces(cr, x0 + half + 24, upper + 14, half, h - 16 - upper - 14)

    def _hour(self, cr, x, y, w, h):
        rx, tx = list(self.hour_rx), list(self.hour_tx)
        D.label(cr, x, y, "THE LAST HOUR", "dim")
        got_rx = sum(rx) * 60
        got_tx = sum(tx) * 60
        D.label(cr, x + w, y, f"↓ {S.human(got_rx)}  ↑ {S.human(got_tx)}", "soft", align="right")
        self.region(x, y - 2, w, 16, f"In the last {len(rx)} minutes: {S.human(got_rx)} received and "
                    f"{S.human(got_tx)} sent (a minute a point)")
        gy, gh = y + 20, h - 20
        D.src(cr, "void", 0.9)
        cr.rectangle(x, gy, w, gh)
        cr.fill()
        cr.set_line_width(1)
        D.src(cr, "guard", 1)
        for k in range(1, 6):                          # a line every 10 minutes
            gx = round(x + w * k / 6) + 0.5
            cr.move_to(gx, gy)
            cr.line_to(gx, gy + gh)
        cr.stroke()
        D.src(cr, "dim", 0.45)
        cr.rectangle(x + 0.5, gy + 0.5, w - 1, gh - 1)
        cr.stroke()
        if len(rx) < 2:
            D.label(cr, x + w / 2, gy + gh / 2 - 6, "A POINT A MINUTE: THE FIRST COMES SOON", "static",
                    size=10, align="center")
        else:
            hi = max(max(rx), max(tx), 1024)
            pad = [None] * (60 - len(rx))
            D.spark(cr, x + 1, gy + 2, w - 2, gh - 4, [0] * len(pad) + rx, "phosphor", lo=0, hi=hi)
            D.spark(cr, x + 1, gy + 2, w - 2, gh - 4, [0] * len(pad) + tx, "soft", lo=0, hi=hi, fill=False)
            D.label(cr, x + 4, gy + 3, S.rate(hi).replace(" ", ""), "static", size=9)
        self.region(x, gy, w, gh, "Average receive (filled) and send rates, one point a minute over the last "
                    "hour, while the panels ran")

    def _connections(self, cr, x, y, w, h):
        D.rule(cr, x, y - 6, x + 2 * w + 24)
        D.label(cr, x, y, "TALKING TO", "dim")
        D.label(cr, x + w, y, "PROGRAMS", "dim", align="right")
        self.region(x, y - 2, w, 16, "Established TCP connections from this machine, by the address at the other "
                    "end (every 5 s, while this size is shown)")
        y += 20
        if not self.conns:
            D.label(cr, x, y, "NONE ESTABLISHED (OR NOT YET READ)", "static", size=10)
            return
        top = max(c["count"] for c in self.conns)
        bottom = y + h - 14
        for c in self.conns:
            if y > bottom:
                break
            D.label(cr, x, y, c["host"], "soft", size=10)
            bw = max(30, w * 0.18)
            D.bar(cr, x + 130, y + 3, bw, 6, c["count"] / top, "phosphor")
            D.label(cr, x + 130 + bw + 8, y, str(c["count"]), "phosphor", size=10)
            D.label(cr, x + w, y, ", ".join(c["procs"])[:int((w - 180 - bw) / 7)] or "-", "static", size=10,
                    align="right")
            self.region(x, y - 2, w, 16, f"{c['host']}: {c['count']} connection{'s' if c['count'] != 1 else ''}"
                        + (f" from {', '.join(c['procs'])}" if c["procs"] else ""))
            y += 18

    def _interfaces(self, cr, x, y, w, h):
        D.label(cr, x, y, "INTERFACES", "dim")
        self.region(x, y - 2, w, 16, "This machine's network interfaces, their state and addresses")
        y += 20
        bottom = y + h - 34
        for i in self.ifaces:
            if y > bottom:
                break
            col = "phosphor" if i["up"] else "static"
            D.dot(cr, x + 4, y + 6, 3, col, glow=i["up"])
            D.label(cr, x + 14, y, i["name"], "soft" if i["up"] else "static", size=10)
            sp = f"{i['speed'] / 1000:g} GB/S" if i["speed"] >= 1000 else (f"{i['speed']} MB/S" if i["speed"] else "")
            D.label(cr, x + w, y, ("UP" if i["up"] else "DOWN") + (f" · {sp}" if sp and i["up"] else ""), col,
                    size=10, align="right")
            addr = ", ".join(i["addrs"][:2])
            if addr:
                D.label(cr, x + 14, y + 15, addr, "static", size=9)
            self.region(x, y - 2, w, 32 if addr else 16, f"{i['name']}: {'up' if i['up'] else 'down'}"
                        + (f", link {sp.lower()}" if sp else "") + (f"; addresses {', '.join(i['addrs'])}" if addr else
                                                                   "; no address"))
            y += 34 if addr else 18
        if not self.ifaces:
            D.label(cr, x, y, "NOT READ YET", "static", size=10)

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
    description = "The mounted filesystems and how full they are"
    category, reads = "system", "your mounted disks and their reads and writes"
    height = 214
    sizes = {"compact": ((240, 110), (420, 200), (300, 140)),
             "standard": ((320, 210), (640, 300), (470, 214)),
             "tall": ((320, 320), (560, 1000), (470, 520)),
             "large": ((700, 320), (1200, 900), (900, 520))}

    def __init__(self, cfg=None):
        super().__init__(cfg)
        self.mounts = S.storage()
        self._mounts_at = time.monotonic()
        self.io = S.DiskIO(history=90)
        self.drawn = "standard"

    @property
    def interval(self):
        # the reads and writes are drawn at the bigger sizes: sample them every 2 s there
        return 2.0 if self.drawn in ("tall", "large") else 30.0

    def tick(self):
        if self.drawn in ("tall", "large"):
            self.io.sample()
        if time.monotonic() - self._mounts_at > 25 or self.drawn not in ("tall", "large"):
            self.mounts = S.storage()
            self._mounts_at = time.monotonic()

    def draw(self, cr, w, h):
        self.drawn = self.size_class(w, h)
        if self.drawn == "compact":
            return self._list(cr, w, h, compact=True)
        if self.drawn == "tall":
            return self._list(cr, w, h)
        if self.drawn == "large":
            return self._large(cr, w, h)
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

    def _header(self, cr, w, h):
        total = sum(m["size"] for m in self.mounts if m["mounted"])
        used = sum(m["used"] for m in self.mounts if m["mounted"])
        top = D.frame(cr, w, h, self.title, f"{S.human(used)} / {S.human(total)} USED")
        self.region(0, 0, w, 34, f"All mounted filesystems together: {S.human(used)} used of {S.human(total)}")
        return top

    @staticmethod
    def _open(path):
        return lambda: subprocess.Popen(["xdg-open", path], start_new_session=True)

    def _row(self, cr, x0, x1, y, m, detail=True):
        """One filesystem as a line: its name, a bar, how full; with detail, its device."""
        if not m["mounted"]:
            D.label(cr, x0, y, m.get("label") or m["device"], "static", size=10)
            D.label(cr, x1, y, f"NOT MOUNTED · {S.human(m['size'], digits=0)}", "amber", size=10, align="right")
            self.region(x0, y - 2, x1 - x0, 16, f"{m['device']} ({m['fstype']}, {S.human(m['size'])}) is not mounted")
            return 20
        frac = m["pct"] / 100
        col = D.level(frac, 0.8, 0.92)
        D.label(cr, x0, y, m["mount"] if len(m["mount"]) < 22 else "…" + m["mount"][-20:], "phosphor", size=10)
        D.label(cr, x1, y, f"{m['pct']:.0f}% · {S.human(m['free'], digits=0)} FREE", col, size=10, align="right")
        D.cells(cr, x0, y + 15, x1 - x0, 7, frac, n=max(10, int((x1 - x0) / 10)), warn=0.8, crit=0.92)
        hgt = 30
        if detail:
            D.label(cr, x0, y + 26, f"{m['device']} · {m['fstype']} · {S.human(m['used'])} OF {S.human(m['size'])}",
                    "static", size=9)
            hgt = 44
        self.region(x0, y - 2, x1 - x0, hgt - 4, f"{m['mount']} on {m['device']} ({m['fstype']}): {S.human(m['used'])} "
                    f"used of {S.human(m['size'])}, {S.human(m['free'])} free. Click to open it.", self._open(m["mount"]))
        return hgt

    def _list(self, cr, w, h, compact=False):
        """Compact: a bar for each filesystem. Tall: each with its device, then the disks'
        reads and writes over time."""
        top = self._header(cr, w, h)
        x0, x1 = 16, w - 16
        y = top
        keep = 0 if compact else 120                  # at least this much for the reads and writes
        bottom = h - 14 - keep - (14 if keep else 0)
        for m in self.mounts:
            need = 30 if compact else 44
            if y + need > bottom:
                more = len(self.mounts) - self.mounts.index(m)
                D.label(cr, x0, y, f"+{more} MORE", "static", size=9)
                y += 16
                break
            y += self._row(cr, x0, x1, y, m, detail=not compact)
        if not compact:                               # the reads and writes fill the rest
            self._io(cr, x0, y + 12, x1 - x0, h - 14 - (y + 12))

    def _io(self, cr, x, y, w, h):
        io = self.io
        D.rule(cr, x, y - 4, x + w)
        D.label(cr, x, y + 4, "READS AND WRITES", "dim")
        D.label(cr, x + w, y + 4, f"R {S.rate(io.read)} · W {S.rate(io.write)}", "soft", align="right")
        self.region(x, y, w, 18, f"All disks together now: reading {S.rate(io.read)}, writing {S.rate(io.write)}")
        gy, gh = y + 24, h - 24
        D.src(cr, "void", 0.9)
        cr.rectangle(x, gy, w, gh)
        cr.fill()
        hi = max(max(io.read_hist), max(io.write_hist), 64 * 1024)
        D.spark(cr, x + 1, gy + 2, w - 2, gh - 4, list(io.read_hist), "phosphor", lo=0, hi=hi)
        D.spark(cr, x + 1, gy + 2, w - 2, gh - 4, list(io.write_hist), "amber", lo=0, hi=hi, fill=False)
        D.label(cr, x + 4, gy + 3, S.rate(hi).replace(" ", ""), "static", size=9)
        D.src(cr, "dim", 0.45)
        cr.set_line_width(1)
        cr.rectangle(x + 0.5, gy + 0.5, w - 1, gh - 1)
        cr.stroke()
        self.region(x, gy, w, gh, f"Reads (filled) and writes (amber) over the last {S.duration(len(io.read_hist) * 2)}, "
                    "sampled every 2 s while this size is shown")

    def _large(self, cr, w, h):
        """Every filesystem as a ring across the top, the reads and writes below, and the
        filesystems in detail beside them."""
        top = self._header(cr, w, h)
        mounted = [m for m in self.mounts if m["mounted"]]
        shown = mounted[:max(1, int((w - 32) / 140))]
        slot = (w - 32) / max(1, len(shown))
        r = min(46, slot / 2 - 18)
        for i, m in enumerate(shown):
            cx, cy = 16 + slot * i + slot / 2, top + r + 6
            frac = m["pct"] / 100
            col = D.level(frac, 0.8, 0.92)
            D.ring(cr, cx, cy, r, frac, 7, col)
            D.text(cr, cx, cy - 10, f"{m['pct']:.0f}%", 16, col, "bold", align="center", glow=True)
            D.label(cr, cx, cy + r + 10, m["mount"] if len(m["mount"]) < 14 else "…" + m["mount"][-12:], "phosphor",
                    align="center")
            self.region(cx - slot / 2, top, slot, 2 * r + 30, f"{m['mount']} on {m['device']}: {S.human(m['used'])} used "
                        f"of {S.human(m['size'])}. Click to open it.", self._open(m["mount"]))
        y = top + 2 * r + 40
        x0, x1 = 16, w - 16
        mid = int(w * 0.55)
        self._io(cr, x0, y, mid - 16 - x0, h - 14 - y)
        yy = y + 4
        for m in self.mounts:
            if yy + 44 > h - 14:
                break
            yy += self._row(cr, mid + 8, x1, yy, m)


# =================================================================== SWITCHBOARD
class WorkbenchPanel(Panel):
    """Recent projects (git repos by last local activity) and the folders you actually
    use (zoxide's frecency database). Each row opens in nvim, a terminal or Dolphin."""
    name, title = "workbench", "WORKBENCH"
    description = "Your recent Git repositories and most-visited folders"
    category, reads = "notes", "your Git repositories and zoxide"
    height = 300
    sizes = {"compact": ((240, 120), (420, 230), (300, 170)),
             "standard": ((360, 240), (700, 440), (470, 300)),
             "tall": ((360, 460), (700, 1200), (470, 640)),
             "large": ((760, 300), (1400, 1100), (940, 520))}
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
        self.drawn = "standard"
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
        big = self.drawn in ("tall", "large")        # more rows, and each one's last commits
        ranked = sorted(repos, key=self._activity, reverse=True)[:max(self.n_projects, 12 if big else 0)]
        projects = []
        for r in ranked:
            branch, changed, ahead, behind = self._git(r)
            p = {"path": r, "name": os.path.basename(r) or r, "where": os.path.dirname(r).replace(home, "~", 1),
                 "t": self._activity(r), "branch": branch, "changed": changed, "ahead": ahead, "behind": behind}
            if big:
                p["subject"], p["days"] = self._commits(r)
            projects.append(p)
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
            if len(folders) >= max(self.n_folders, 10 if big else 0):
                break
        self.projects, self.folders, self.scanned = projects, folders, time.time()

    @staticmethod
    def _commits(repo, days=14):
        """(the last commit's subject, commits on each of the last `days` days, oldest first)."""
        try:
            out = subprocess.run(["git", "--no-optional-locks", "-C", repo, "log", f"--since={days}.days",
                                  "--format=%ct%x09%s", "-n", "400"], capture_output=True, text=True,
                                 timeout=5).stdout.splitlines()
            last = out[0].split("\t", 1)[1] if out else subprocess.run(
                ["git", "-C", repo, "log", "-1", "--format=%s"], capture_output=True, text=True,
                timeout=5).stdout.strip()
        except (OSError, subprocess.TimeoutExpired, IndexError):
            return "", [0] * days
        now = time.time()
        per = [0] * days
        for line in out:
            try:
                age = int((now - int(line.split("\t", 1)[0])) // 86400)
            except ValueError:
                continue
            if 0 <= age < days:
                per[days - 1 - age] += 1
        return last, per

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
        was, self.drawn = self.drawn, self.size_class(w, h)
        if self.drawn in ("tall", "large") and was not in ("tall", "large"):
            threading.Thread(target=self._scan, daemon=True).start()     # read the commits now
        right = "SCANNING" if not self.scanned else f"{len(self.projects)} PROJECTS · {len(self.folders)} FOLDERS"
        if self.drawn == "compact":
            right = "SCANNING" if not self.scanned else f"{len(self.projects)} PROJECTS"
        top = D.frame(cr, w, h, self.title, right)
        if self.drawn == "compact":
            return self._compact(cr, w, h, top)
        if self.drawn in ("tall", "large"):
            return self._big(cr, w, h, top)
        self.region(0, 0, w, 34, "Your recent projects (git repos ranked by your last commit, checkout or "
                    "staging) and the folders you visit most (zoxide: `z name` jumps there in a shell). "
                    "Click a row for nvim; NVIM, >_ and DIR open nvim, a terminal or Dolphin there. "
                    "Rescans every minute.")
        x0, x1 = 16, w - 16
        y = top
        D.label(cr, x0, y + 2, "RECENT PROJECTS", "phosphor", size=10)
        D.rule(cr, x0 + 130, y + 9, x1, "dim", 0.35)
        y += self.HEAD
        for p in self.projects[:self.n_projects]:
            if y + self.ROW > h - 8:
                break
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
        for f in self.folders[:self.n_folders]:
            if y + self.ROW > h - 8:
                break
            tip = f"{f['where']}/{f['name']}: one of your most-visited folders (zoxide score {f['score']:.0f})."
            self._row(cr, x0, x1, y, f, f["where"], "static", tip)
            y += self.ROW

    @staticmethod
    def _bits(p):
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
        return bits, col

    def _compact(self, cr, w, h, top):
        """The projects by name, most recent first; a dot when one has uncommitted work."""
        x0, x1 = 16, w - 16
        y = top
        for p in self.projects:
            if y + 18 > h - 10:
                break
            col = "amber" if p["changed"] else "phosphor"
            D.dot(cr, x0 + 3, y + 7, 3, col, glow=bool(p["changed"]))
            D.text(cr, x0 + 14, y, p["name"], 12, "soft", "semibold", width=x1 - x0 - 60)
            D.label(cr, x1, y + 2, self._ago(p["t"]), "static", size=10, align="right")
            self.region(x0, y - 2, x1 - x0, 20, f"{p['where']}/{p['name']}" + (f": {p['changed']} uncommitted "
                        "file(s)" if p["changed"] else "") + f", last activity {self._ago(p['t'])} ago. "
                        "Click to open it in nvim.", lambda q=p["path"]: self.open_nvim(q))
            y += 22

    def _big(self, cr, w, h, top):
        """Tall: more projects, each with its last commit and a fortnight of commits, then
        the folders. Large: the projects and the folders side by side."""
        x0, x1 = 16, w - 16
        if self.drawn == "large":
            split = int(w * 0.62)
            self._projects(cr, x0, split - 12, top, h - 12)
            self._folders(cr, split + 12, x1, top, h - 12)
            return
        bottom = h - 12 - min(len(self.folders), 4) * self.ROW - self.HEAD - 8
        self._projects(cr, x0, x1, top, bottom)
        self._folders(cr, x0, x1, bottom + 6, h - 12)

    def _projects(self, cr, x0, x1, y, bottom):
        D.label(cr, x0, y + 2, "RECENT PROJECTS", "phosphor", size=10)
        D.label(cr, x1, y + 2, "COMMITS, 14 DAYS", "dim", size=9, align="right")
        y += self.HEAD
        for p in self.projects:
            if y + 46 > bottom:
                break
            bits, col = self._bits(p)
            bits.append(self._ago(p["t"]))
            tip = (f"{p['where']}/{p['name']}: on {p['branch'] or '?'}, {p['changed']} uncommitted file(s), "
                   f"{p['ahead']} to push, {p['behind']} to pull, last activity {self._ago(p['t'])} ago.")
            self._row(cr, x0, x1 - 120, y, p, " · ".join(bits), col, tip)
            days = p.get("days") or [0] * 14
            sx = x1 - 112
            D.src(cr, "void", 0.8)
            cr.rectangle(sx, y + 2, 112, 20)
            cr.fill()
            top_ = max(days) or 1
            bw = 112 / len(days)
            for i, n in enumerate(days):
                if n:
                    D.src(cr, "phosphor", 0.35 + 0.65 * n / top_)
                    hh = 18 * n / top_
                    cr.rectangle(sx + i * bw + 1, y + 21 - hh, bw - 2, hh)
            cr.fill()
            self.region(sx, y + 2, 112, 20, f"{p['name']}: {sum(days)} commit(s) in the last 14 days, a bar a day "
                        f"(the busiest day had {max(days)})")
            subj = p.get("subject") or ""
            D.text(cr, x0 + 12, y + self.ROW - 2, ("“" + subj + "”") if subj else "no commits yet", 10, "static",
                   "regular", width=x1 - x0 - 12)
            self.region(x0, y + self.ROW - 4, x1 - x0, 16, f"{p['name']}'s last commit: {subj or 'none'}")
            y += self.ROW + 20

    def _folders(self, cr, x0, x1, y, bottom):
        D.label(cr, x0, y + 2, "FREQUENT FOLDERS", "phosphor", size=10)
        D.rule(cr, x0 + 140, y + 9, x1, "dim", 0.35)
        y += self.HEAD
        if not self.folders and self.scanned:
            D.text(cr, x0, y + 2, "Nothing yet: zoxide learns as you cd around.", 11, "static", "regular")
        for f in self.folders:
            if y + self.ROW > bottom:
                break
            tip = f"{f['where']}/{f['name']}: one of your most-visited folders (zoxide score {f['score']:.0f})."
            self._row(cr, x0, x1, y, f, f["where"], "static", tip)
            y += self.ROW


# =================================================================== SHORTCUTS
class ShortcutsPanel(Panel):
    """Live Hyprland keybinds as keycaps, Bromigos sections first. Scroll to move; click a
    Bromigos, launch or capture line to run it (window, workspace, system and hold-to-use
    binds stay keyboard-only)."""
    name, title = "shortcuts", "SHORTCUTS"
    description = "Every key binding, read from Hyprland"
    category, reads = "system", "Hyprland's key bindings"
    height = 384
    sizes = {"standard": ((440, 200), (720, 1400), (470, 384)),
             "wide": ((900, 260), (2000, 1400), (960, 560))}
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
        view = getattr(self, "view_h", self.height - 44 - 10)
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
        self.view_h = h - 44 - 10
        top = D.frame(cr, w, h, self.title, f"{len(self.items)} BINDS · SUPER+SHIFT+K SEARCH")
        self.region(0, 0, w, 34, "Every Hyprland keybind, read live from Hyprland (it refreshes when "
                    "the Hyprland config changes). Bromigos keys first. Scroll to move; click a Bromigos, launch or capture line to run it. "
                    "SUPER+SHIFT+K opens a searchable version.")
        x0, x1 = 16, w - 16
        view_top, view_bot = top, h - 10
        # the sections, in columns at the wide size (each section goes to the shortest column)
        sections = []
        for item in self.items:
            if not sections or sections[-1][0] != item[0]:
                sections.append((item[0], []))
            sections[-1][1].append(item)
        ncol = max(1, int((x1 - x0 + 24) / 460)) if self.size_class(w, h) == "wide" else 1
        colw = (x1 - x0 - 24 * (ncol - 1)) / ncol
        cols = [[] for _ in range(ncol)]
        heights = [0] * ncol
        for sec in sections:
            i = heights.index(min(heights))
            cols[i].append(sec)
            heights[i] += self._section(cr, sec, 0, colw, 0, 0, -1, measure=True)
        cr.save()
        cr.rectangle(0, view_top, w, view_bot - view_top)
        cr.clip()
        for i, col in enumerate(cols):
            cx0 = x0 + i * (colw + 24)
            y = view_top - self.offset
            for sec in col:
                y += self._section(cr, sec, cx0, cx0 + colw, y, view_top, view_bot)
        self._content_h = max(heights) if heights else 0
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

    def _section(self, cr, sec, x0, x1, y, view_top, view_bot, measure=False):
        """One section's heading and rows from y; its height. measure: no drawing."""
        s, items = sec
        y0 = y
        if not measure and view_top - self.HEAD <= y <= view_bot:
            lw = D.layout(cr, s.upper(), 10, "semibold", 0.18).get_pixel_size()[0]
            D.label(cr, x0, y + 6, s, "phosphor", size=10)
            D.rule(cr, x0 + lw + 10, y + 13, x1, "dim", 0.35)
        y += self.HEAD
        dx = x0 + 200
        for _s, keys, desc, action in items:
            main, alt = self._split(desc)
            if main.startswith(s + ": "):            # "VECTOR: hold to talk" under VECTOR -> "hold to talk"
                main = main[len(s) + 2:]
                main = main[:1].upper() + main[1:]
            kx = x0
            for k in keys:
                kx += D.layout(cr, k, 11, "semibold", 0.04).get_pixel_size()[0] + 12 + 12
            tx = max(kx, dx)
            tw = max(40, x1 - tx)
            mh = D.layout(cr, main, 12, "regular", 0, tw, wrap=True).get_pixel_size()[1]
            ah = D.layout(cr, alt, 10, "regular", 0, tw, wrap=True).get_pixel_size()[1] if alt else 0
            rh = max(self.ROW, mh + ah + 6)
            if not measure and view_top - rh <= y <= view_bot:
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
        return y - y0


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
    description = "The forecast for a place you choose: now, the next hours, and the days ahead"
    category, reads = "fun", "Open-Meteo, for your place"
    height = 300
    sizes = {"compact": ((240, 110), (400, 220), (300, 140)),
             "standard": ((400, 260), (700, 440), (470, 300)),
             "wide": ((760, 200), (1600, 380), (980, 250)),
             "large": ((640, 460), (1100, 900), (760, 600))}
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
        q = {"latitude": self.loc["lat"], "longitude": self.loc["lon"], "timezone": "auto", "forecast_days": 7,
             "current": "temperature_2m,relative_humidity_2m,apparent_temperature,weather_code,wind_speed_10m,"
                        "wind_direction_10m,precipitation,is_day",
             "hourly": "temperature_2m,precipitation_probability,weather_code,is_day",
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
        cls = self.size_class(w, h)
        if cls == "compact":
            return self._compact(cr, w, h, top, d, deg)
        if cls == "wide":
            return self._wide(cr, w, h, top, d, deg, spd)
        if cls == "large":
            return self._large(cr, w, h, top, d, deg, spd)
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

    # ------------------------------------------------------------ the other sizes
    @staticmethod
    def glyph(cr, cx, cy, r, code, day=True):
        """A small drawn picture of the weather: the sun or moon, cloud, rain, snow, fog or
        lightning, from its WMO code."""
        code = int(code or 0)
        cloud = code >= 2
        rain = code in (51, 53, 55, 56, 57, 61, 63, 65, 66, 67, 80, 81, 82)
        snow = code in (71, 73, 75, 77, 85, 86)
        storm = code >= 95
        fog = code in (45, 48)
        cr.set_line_width(max(1.2, r / 9))
        if code <= 2:
            sx, sy, sr = (cx - r * 0.25, cy - r * 0.25, r * 0.45) if cloud else (cx, cy, r * 0.5)
            if day:
                D.src(cr, "amber", 1)
                cr.arc(sx, sy, sr, 0, 2 * math.pi)
                cr.fill()
                for k in range(8):
                    a = k * math.pi / 4
                    cr.move_to(sx + math.cos(a) * sr * 1.3, sy + math.sin(a) * sr * 1.3)
                    cr.line_to(sx + math.cos(a) * sr * 1.7, sy + math.sin(a) * sr * 1.7)
                cr.stroke()
            else:
                D.src(cr, "soft", 1)
                cr.arc(sx, sy, sr, 0, 2 * math.pi)
                cr.arc_negative(sx + sr * 0.45, sy - sr * 0.3, sr * 0.85, 2 * math.pi, 0)
                cr.fill()
        if cloud:
            oy = cy + (r * 0.1 if (rain or snow or storm) else r * 0.2)
            D.src(cr, "static" if (rain or storm) else "soft", 1)
            for dx, dy, rr in ((-0.35, 0.05, 0.32), (0.05, -0.15, 0.42), (0.42, 0.08, 0.3)):
                cr.new_sub_path()
                cr.arc(cx + dx * r, oy + dy * r, rr * r, 0, 2 * math.pi)
            cr.rectangle(cx - 0.35 * r, oy + 0.05 * r, 0.77 * r, 0.32 * r)
            cr.fill()
            if rain:
                D.src(cr, "cyan", 1)
                for k in range(3):
                    x = cx - 0.3 * r + k * 0.3 * r
                    cr.move_to(x, oy + 0.5 * r)
                    cr.line_to(x - 0.12 * r, oy + 0.85 * r)
                cr.stroke()
            if snow:
                D.src(cr, "soft", 1)
                for k in range(3):
                    cr.new_sub_path()
                    cr.arc(cx - 0.3 * r + k * 0.3 * r, oy + 0.7 * r, max(1.2, r * 0.07), 0, 2 * math.pi)
                cr.fill()
            if storm:
                D.src(cr, "amber", 1)
                cr.move_to(cx + 0.05 * r, oy + 0.35 * r)
                cr.line_to(cx - 0.15 * r, oy + 0.7 * r)
                cr.line_to(cx + 0.05 * r, oy + 0.7 * r)
                cr.line_to(cx - 0.1 * r, oy + 1.0 * r)
                cr.stroke()
        if fog:
            D.src(cr, "static", 1)
            for k in range(3):
                y = cy - 0.3 * r + k * 0.3 * r
                cr.move_to(cx - 0.6 * r, y)
                cr.line_to(cx + 0.6 * r, y)
            cr.stroke()

    def _now(self, cr, x, y, d, deg, size=44):
        cur = d["current"]
        t = cur["temperature_2m"]
        code = cur.get("weather_code", 0)
        tw = D.seg7(cr, x, y, size, f"{t:.0f}", "phosphor")
        D.text(cr, x + tw + 6, y, deg, 14, "phosphor", "bold")
        D.label(cr, x, y + size + 8, self._words(code), "soft", size=11)
        self.region(x, y - 4, tw + 40, size + 28, f"{t:.1f}{deg} now, {self._words(code)}; feels like "
                    f"{cur.get('apparent_temperature', t):.0f}{deg}")
        return tw + 40

    def _hours(self, d, n):
        hours = d.get("hourly", {})
        i = self._hour_index(hours.get("time", []), d.get("current", {}).get("time"))
        pick = (lambda k: (hours.get(k) or [])[i:i + n])
        return pick("time"), pick("temperature_2m"), pick("precipitation_probability"), pick("weather_code"), \
            pick("is_day")

    def _compact(self, cr, w, h, top, d, deg):
        cur = d["current"]
        code = cur.get("weather_code", 0)
        r = min(30, (h - top - 14) / 2)
        self.glyph(cr, 16 + r, top + r + 4, r, code, cur.get("is_day", 1))
        x = 16 + 2 * r + 14
        self._now(cr, x, top, d, deg, size=min(40, h - top - 36))
        self.region(16, top, 2 * r, 2 * r + 8, f"Now: {self._words(code)}")
        daily = d.get("daily", {})
        if daily.get("time") and w >= 280:
            hi, lo = daily["temperature_2m_max"][0], daily["temperature_2m_min"][0]
            D.label(cr, w - 16, top + 4, f"{lo:.0f}–{hi:.0f}{deg}", "soft", size=10, align="right")
            D.label(cr, w - 16, top + 20, f"RAIN {daily['precipitation_probability_max'][0] or 0:.0f}%", "cyan",
                    size=10, align="right")
            self.region(w - 90, top, 74, 34, f"Today: low {lo:.0f}{deg}, high {hi:.0f}{deg}, up to "
                        f"{daily['precipitation_probability_max'][0] or 0:.0f}% chance of rain")

    def _strip(self, cr, x, y, w, h, d, deg, n):
        """The next n hours as columns: the hour, a picture, the temperature, the chance of rain."""
        times, temps, rain, codes, day = self._hours(d, n)
        if not times:
            return
        cw = w / len(times)
        lo, hi = min(temps), max(temps)
        for i, t in enumerate(times):
            cx = x + cw * i + cw / 2
            D.label(cr, cx, y, t[11:13], "dim", size=9, align="center")
            gr = min(cw * 0.38, 14)
            self.glyph(cr, cx, y + 24, gr, codes[i] if i < len(codes) else 0, day[i] if i < len(day) else 1)
            tt = temps[i]
            ty = y + 48 + (h - 100) * (1 - (tt - lo) / max(0.1, hi - lo))
            D.dot(cr, cx, ty + 6, 2.2, "phosphor", glow=False)
            if i:
                pt = temps[i - 1]
                py = y + 48 + (h - 100) * (1 - (pt - lo) / max(0.1, hi - lo))
                D.src(cr, "phosphor", 0.7)
                cr.set_line_width(1.4)
                cr.move_to(cx - cw, py + 6)
                cr.line_to(cx, ty + 6)
                cr.stroke()
            D.label(cr, cx, ty - 10, f"{tt:.0f}°", "soft", size=9, align="center")
            p = rain[i] if i < len(rain) else 0
            bh = 18 * (p or 0) / 100
            D.src(cr, "cyan", 0.25 + 0.6 * (p or 0) / 100)
            cr.rectangle(cx - cw * 0.3, y + h - 6 - bh, cw * 0.6, bh)
            cr.fill()
            if p and cw > 26:
                D.label(cr, cx, y + h - 22 - bh, f"{p:.0f}%", "cyan", size=8, align="center")
            self.region(cx - cw / 2, y, cw, h, f"{t[11:16]}: {tt:.0f}{deg}, {self._words(codes[i] if i < len(codes) else 0)}, "
                        f"{p or 0:.0f}% chance of rain")

    def _wide(self, cr, w, h, top, d, deg, spd):
        """Now on the left, then the next hours as a strip."""
        cur = d["current"]
        self.glyph(cr, 46, top + 30, 28, cur.get("weather_code", 0), cur.get("is_day", 1))
        self.region(16, top, 60, 64, f"Now: {self._words(cur.get('weather_code', 0))}")
        nw = self._now(cr, 92, top, d, deg)
        D.label(cr, 92, top + 74, f"FEELS {cur.get('apparent_temperature', 0):.0f}{deg} · "
                f"WIND {cur.get('wind_speed_10m', 0):.0f} {spd} {self._dir(cur.get('wind_direction_10m'))}",
                "static", size=9)
        self.region(92, top + 72, max(nw, 200), 16, "How it feels, and the wind at 10 m and where it blows from")
        x = 92 + max(nw, 210) + 16
        n = max(6, min(24, int((w - 16 - x) / 34)))
        self._strip(cr, x, top, w - 16 - x, h - top - 12, d, deg, n)

    def _large(self, cr, w, h, top, d, deg, spd):
        """Now with every reading, the next 24 hours as a strip, and the week ahead."""
        cur = d["current"]
        self.glyph(cr, 50, top + 34, 32, cur.get("weather_code", 0), cur.get("is_day", 1))
        self.region(16, top, 70, 72, f"Now: {self._words(cur.get('weather_code', 0))}")
        self._now(cr, 100, top, d, deg)
        x = max(300, w * 0.45)
        t = cur.get("temperature_2m", 0)
        rows = [("FEELS", f"{cur.get('apparent_temperature', t):.0f}{deg}", "How it feels: temperature with wind and humidity"),
                ("HUMID", f"{cur.get('relative_humidity_2m', 0):.0f}%", "Relative humidity"),
                ("WIND", f"{cur.get('wind_speed_10m', 0):.0f} {spd} {self._dir(cur.get('wind_direction_10m'))}",
                 "Wind at 10 m, and where it blows from"),
                ("RAIN", f"{cur.get('precipitation', 0):.1f} {'in' if self.units == 'imperial' else 'mm'}",
                 "Precipitation in the last hour")]
        for i, (k, v, tip) in enumerate(rows):
            y = top + 4 + i * 18
            D.label(cr, x, y, k, "dim", size=10)
            D.text(cr, x + 62, y - 1, v, 11, "soft")
            self.region(x, y - 2, w - x - 16, 18, tip)
        sy = top + 92
        D.label(cr, 16, sy, "NEXT 24 HOURS", "dim", size=10)
        sh = max(130, int((h - sy) * 0.4))
        self._strip(cr, 16, sy + 18, w - 32, sh, d, deg, max(8, min(24, int((w - 32) / 30))))
        dy = sy + 18 + sh + 14
        D.rule(cr, 16, dy - 8, w - 16)
        daily = d.get("daily", {})
        n = len(daily.get("time", []))
        if not n:
            return
        D.label(cr, 16, dy, "THE WEEK", "dim", size=10)
        lo_all = min(daily["temperature_2m_min"][:n])
        hi_all = max(daily["temperature_2m_max"][:n])
        rh = max(22, min(40, (h - 14 - dy - 18) / n))
        names = ["TODAY", "TOMORROW"]
        bx0, bx1 = w * 0.48, w - 90
        for i in range(n):
            y = dy + 18 + i * rh
            if y + rh > h - 8:
                break
            when = names[i] if i < 2 else self._weekday(daily["time"][i])
            code = daily["weather_code"][i]
            D.label(cr, 16, y + rh / 2 - 7, when, "dim", size=10)
            self.glyph(cr, 140, y + rh / 2, min(11, rh / 2 - 2), code, True)
            D.text(cr, 160, y + rh / 2 - 8, self._words(code), 11, "soft", width=bx0 - 170)
            lo, hi = daily["temperature_2m_min"][i], daily["temperature_2m_max"][i]
            span = max(0.1, hi_all - lo_all)
            a = bx0 + (bx1 - bx0) * (lo - lo_all) / span
            b = bx0 + (bx1 - bx0) * (hi - lo_all) / span
            D.src(cr, "guard", 1)
            cr.rectangle(bx0, y + rh / 2 - 2, bx1 - bx0, 4)
            cr.fill()
            D.src(cr, "phosphor", 0.9)
            cr.rectangle(a, y + rh / 2 - 3, max(3, b - a), 6)
            cr.fill()
            D.label(cr, bx0 - 8, y + rh / 2 - 7, f"{lo:.0f}°", "static", size=10, align="right")
            D.label(cr, bx1 + 8, y + rh / 2 - 7, f"{hi:.0f}°", "soft", size=10)
            pr = daily["precipitation_probability_max"][i] or 0
            D.label(cr, w - 16, y + rh / 2 - 7, f"{pr:.0f}%", "cyan" if pr >= 30 else "static", size=10, align="right")
            self.region(16, y, w - 32, rh, f"{when.title()}: {self._words(code)}, low {lo:.0f}{deg}, high {hi:.0f}{deg}, "
                        f"up to {pr:.0f}% chance of rain; sunrise {daily['sunrise'][i][-5:]}, "
                        f"sunset {daily['sunset'][i][-5:]}")

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
    description = "Network connections, Wi-Fi in reach and VPNs, with a Wi-Fi switch"
    category, reads = "network", "NetworkManager"
    sizes = {"compact": ((240, 100), (420, 190), (300, 130)),
             "standard": ((360, 200), (640, 440), (470, 262)),
             "tall": ((360, 460), (640, 1200), (470, 620))}
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
        self.saved_wifi = [l.split(":", 1)[0] for l in saved.splitlines() if l.endswith(":802-11-wireless")]
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
        self.wifi = rows[:16]

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
        cls = self.size_class(w, h)
        if cls == "compact":
            return self._compact(cr, w, h, top)
        tall = cls == "tall"
        y = top + 4
        # active connections
        conns = [a for a in self.active if a["type"] not in ("loopback",)]
        if not conns:
            D.label(cr, 16, y + 2, "NOT CONNECTED", "amber", size=10)
            y += 18
        for a in conns[:6 if tall else 3]:
            if y + 17 > h - 6:
                break
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
        room = (h - y - 16 - (24 + 17 * len(self.vpns) if self.vpns else 0)) // 17 if tall else 4
        for net in self.wifi[:max(1, int(room))]:
            if y + 17 > h - 6:
                break
            col = "phosphor" if net["used"] else "soft"
            busy = net["ssid"] in self.pending
            D.text(cr, 16, y - 1, ("… " if busy else "") + net["ssid"][:24], 11, col, "semibold" if net["used"] else "medium")
            D.cells(cr, w - 16 - 60, y + 3, 44, 8, net["signal"] / 100, n=6, warn=2, crit=2, gap=2)
            if tall:
                D.label(cr, w - 16 - 70, y + 1, f"{net['signal']}%", "static", size=9, align="right")
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
            for v in self.vpns[:8 if tall else 3]:
                if y + 17 > h - 6:
                    break
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
        # tall: the Wi-Fi networks this machine knows
        saved = getattr(self, "saved_wifi", [])
        if tall and saved and y + 40 < h:
            y += 4
            D.rule(cr, 16, y, w - 16)
            y += 8
            D.label(cr, 16, y, "SAVED WI-FI", "dim", size=10)
            self.region(16, y - 2, w - 32, 16, "The Wi-Fi networks NetworkManager has saved: they join without a "
                        "password when in reach")
            y += 16
            reach = {n["ssid"] for n in self.wifi}
            for name in saved:
                if y + 17 > h - 8:
                    break
                near = name in reach
                D.text(cr, 16, y - 1, name[:30], 11, "soft" if near else "static")
                D.label(cr, w - 16, y + 1, "IN REACH" if near else "", "phosphor", size=9, align="right")
                self.region(16, y - 2, w - 32, 17, f"{name}: saved" + (", in reach now" if near else ", not in reach"))
                y += 17


    def _compact(self, cr, w, h, top):
        """What's connected, and the Wi-Fi network in use with its signal."""
        conns = [a for a in self.active if a["type"] not in ("loopback",)]
        y = top
        if not conns:
            D.label(cr, 16, y + 2, "NOT CONNECTED", "amber")
            self.region(16, y, w - 32, 18, "Nothing is connected")
            return
        for a in conns[:max(1, int((h - top - 10) / 20))]:
            kind = a["type"].replace("802-11-wireless", "wifi").replace("802-3-ethernet", "ethernet")
            D.dot(cr, 22, y + 8, 3, "phosphor")
            D.text(cr, 34, y, a["name"][:22], 12, "soft", "semibold")
            net = next((n for n in self.wifi if n["used"]), None) if kind == "wifi" else None
            if net:
                D.cells(cr, w - 16 - 44, y + 4, 44, 8, net["signal"] / 100, n=6, warn=2, crit=2, gap=2)
            else:
                D.label(cr, w - 16, y + 2, kind.upper(), "static", size=9, align="right")
            self.region(16, y - 2, w - 32, 20, f"Connected: {a['name']} ({kind} on {a['device']})"
                        + (f", signal {net['signal']}%" if net else ""))
            y += 20


# bromigOS's panels that layout.json lists by name, in the gallery's order. More built-in
# panels are files in plugins/ beside this one (docs/widgets.md, "Adding a widget").
CORE = {"system": SystemPanel, "network": NetworkPanel, "storage": StoragePanel, "shortcuts": ShortcutsPanel,
        "workbench": WorkbenchPanel, "weather": WeatherPanel, "connections": ConnectionsPanel}
