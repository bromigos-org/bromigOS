"""SOLAR: what the panels on the roof make, what the house uses, and the grid between them
(bromigos-homelab's energy capability: an `enphase` source, the IQ Gateway's local API).

The gateway keeps no history of its own on the network, so the day's curve is the
source's `history_metric` through the homelab's metrics when one is set, else the samples
this panel takes while it runs, kept for the day in
~/.local/state/bromigos/widgets/solar-<date>.json (a week of them).

A panel generator (widgets/plugins.py): it offers the "solar" panel only while something
provides energy, so the widget gallery lists it only then.
"""
import datetime as dt
import glob
import json
import math
import os
import sys
import time

_HERE = os.path.dirname(os.path.realpath(__file__))
for _p in (os.path.join(os.path.dirname(_HERE), "lib"),):        # a bromigOS checkout's homelab/lib
    if os.path.isdir(_p) and _p not in sys.path:
        sys.path.insert(1, _p)

import panels  # noqa: E402

sys.path.append(os.path.join(os.path.dirname(os.path.realpath(panels.__file__)), "plugins"))
import _kit as K  # noqa: E402

import draw as D  # noqa: E402

NAME = "solar"
KEEP_DAYS = 7


def _demo_lab():
    return os.environ.get("BROMIGOS_WIDGETS_DEMO_LAB") == "1"


def available():
    """(True, "") when the panel has a source, else (False, why): names()' check, no network."""
    if _demo_lab():
        return True, ""
    try:
        import bromigos_homelab as H
    except ImportError:
        return False, "bromigos-homelab isn't installed"
    return (True, "") if H.available("energy") else (
        False, "no [[source]] in homelab.toml provides energy (type = \"enphase\")")


def names():
    return {NAME: 1} if available()[0] else {}


def panel(name):
    return SolarPanel, {"visible": False}


# ------------------------------------------------------------------ the data
def power(w, digits=1):
    """1234 -> '1.2 kW', 640 -> '640 W', None -> '--'."""
    if w is None:
        return "--"
    if abs(w) >= 1000:
        return f"{w / 1000:.{digits}f} kW"
    return f"{w:.0f} W"


def energy(wh):
    if wh is None:
        return "--"
    if abs(wh) >= 1e6:
        return f"{wh / 1e6:.2f} MWh"
    return f"{wh / 1000:.1f} kWh"


def combine(items):
    """One reading from every energy record (several gateways add up)."""
    if not items:
        return None
    if len(items) == 1:
        return dict(items[0])

    def tot(k):
        vals = [r.get(k) for r in items if r.get(k) is not None]
        return sum(vals) if vals else None
    out = {k: tot(k) for k in ("production_w", "consumption_w", "net_w", "today_wh", "consumed_today_wh",
                               "lifetime_wh", "battery_w", "inverters")}
    pcts = [r["battery_pct"] for r in items if r.get("battery_pct") is not None]
    out.update(name=" + ".join(str(r.get("name")) for r in items), kind="solar",
               battery_pct=sum(pcts) / len(pcts) if pcts else None,
               history_metric=next((r.get("history_metric") for r in items if r.get("history_metric")), None))
    return out


def self_powered(r):
    """The share of what the house uses that the sun covers now (0..1), or None."""
    p, c = r.get("production_w"), r.get("consumption_w")
    if p is None or not c:
        return None
    return max(0.0, min(1.0, p / c))


def day_file(day=None):
    return os.path.join(K.STATE, f"solar-{(day or dt.date.today()).isoformat()}.json")


def record(r, now=None, path=None):
    """Append [t, production W, consumption W] to the day's file; drop files older than a week."""
    now = now or time.time()
    path = path or day_file(dt.date.fromtimestamp(now))
    pts = load_day(path)
    pts.append([round(now), r.get("production_w"), r.get("consumption_w")])
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(pts, f)
    os.replace(tmp, path)
    cutoff = (dt.date.fromtimestamp(now) - dt.timedelta(days=KEEP_DAYS)).isoformat()
    for old in glob.glob(os.path.join(os.path.dirname(path), "solar-*.json")):
        if os.path.basename(old)[6:16] < cutoff:
            try:
                os.remove(old)
            except OSError:
                pass
    return pts


def load_day(path=None):
    try:
        with open(path or day_file()) as f:
            pts = json.load(f)
        return [p for p in pts if isinstance(p, list) and len(p) == 3]
    except (OSError, ValueError):
        return []


def midnight(now=None):
    d = dt.datetime.fromtimestamp(now or time.time())
    return d.replace(hour=0, minute=0, second=0, microsecond=0).timestamp()


def demo_curve(now):
    """A clear autumn day so far: production a bell from 7:00 to 18:30, a house that wakes and cooks."""
    m = midnight(now)
    pts = []
    t = m
    while t <= now:
        h = (t - m) / 3600
        sun = max(0.0, math.sin(math.pi * (h - 7.0) / 11.5)) if 7.0 <= h <= 18.5 else 0.0
        prod = 6200 * sun ** 1.4 * (0.93 + 0.07 * math.sin(h * 5.1))
        house = 380 + 900 * math.exp(-((h - 7.5) ** 2) / 0.6) + 1600 * math.exp(-((h - 18.6) ** 2) / 0.9) \
            + 300 * math.exp(-((h - 12.5) ** 2) / 2)
        pts.append([t, prod, house])
        t += 300
    return pts


def demo_reading(now=None):
    now = now or time.time()
    curve = demo_curve(now)
    _, p, c = curve[-1] if curve else (now, 0, 400)
    return {"name": "roof", "kind": "solar", "production_w": p, "consumption_w": c, "net_w": c - p,
            "today_wh": 23400.0, "consumed_today_wh": 11800.0, "lifetime_wh": 18.6e6, "battery_pct": 72.0,
            "battery_w": -650.0, "inverters": 18, "state": "ok", "source": "solar"}


# ------------------------------------------------------------------ the panel
class SolarPanel(K.KitPanel):
    name, title = NAME, "SOLAR"
    description = "Solar now: what the roof makes, what the house uses, the grid and batteries; the day's curve when large"
    category, reads = "homelab", "your solar gateway (Enphase), through the homelab"
    width, height = 460, 280
    interval = 10.0                    # the draw refresh; the gateway is read every 30 s
    sizes = {
        "compact": ((240, 120), (380, 190), (280, 140)),
        "standard": ((400, 220), (620, 380), (460, 280)),
        "wide": ((640, 180), (1100, 360), (800, 230)),
        "tall": ((380, 420), (560, 860), (420, 520)),
        "large": ((660, 440), (1200, 860), (780, 540)),
    }
    default_size = "standard"
    settings = [{"key": "decimals", "label": "Decimals for kW", "kind": "number", "default": 1}]

    @classmethod
    def available(cls):
        return available()

    def __init__(self, cfg=None, wake=None):
        super().__init__(cfg, wake)
        self.hist_q = None
        self.now_t = None
        if K.demo():                       # a picture: half past three on a clear day
            self.now_t = midnight() + 15.5 * 3600
            self.r = demo_reading(self.now_t)
            self.curve = demo_curve(self.now_t)
            self.read_at = time.time() - 12
        else:
            self.r, self.curve, self.read_at = None, load_day(), 0
            self.poll = self.poller(self.fetch, every=30)
            self.hist = self.poller(self.fetch_history, every=300, name="history")

    def fetch(self):
        import bromigos_homelab as H
        res = H.energy()
        r = combine(res.get("items") or [])
        if r is not None:
            self.r, self.read_at = r, time.time()
            self.hist_q = r.get("history_metric")
            if not self.hist_q:
                self.curve = record(r)
        return res

    def fetch_history(self):
        """The day from the metrics source, when the energy source names a history_metric."""
        if not self.hist_q:
            return None
        import bromigos_homelab as H
        mins = max(10, int((time.time() - midnight()) / 60))
        res = H.metrics_range(self.hist_q, minutes=mins, step=300)
        series = (res.get("items") or [])
        if series:
            self.curve = [[t, v, None] for t, v in series[0].get("points") or []]
        return res

    # ---- drawing
    def draw(self, cr, w, h):
        cls = self.size_class(w, h)
        r = self.r
        dec = int(self.conf.get("decimals", 1) or 0)
        right = None
        if r and cls != "compact":
            n = r.get("net_w")
            right = ("EXPORTING " + power(-n, dec) if n is not None and n < -20 else
                     "IMPORTING " + power(n, dec) if n is not None and n > 20 else "BALANCED" if n is not None else
                     str(r.get("name") or "").upper())
        top = D.frame(cr, w, h, self.title, right, "phosphor" if (r or {}).get("net_w", 0) is not None and
                      ((r or {}).get("net_w") or 0) <= 20 else "amber")
        self.region(0, 0, w, 34, "Solar from your gateway (Enphase), read every 30 s"
                    + (f", last {K.ago(self.read_at)} ago" if r else "") + ". Grid: exporting sends the surplus out; "
                    "importing draws from it.")
        if r is None:
            res = getattr(getattr(self, "poll", None), "data", None) or {}
            err = getattr(getattr(self, "poll", None), "error", None)
            if res and not res.get("sources"):
                self.empty(cr, w, h, top, "NO SOLAR SOURCE",
                           "Add your gateway to ~/.config/bromigos/homelab.toml: [[source]] type = \"enphase\", "
                           "endpoint = \"https://envoy.local\", and for firmware 7 or later auth_ref with an owner "
                           "token and tls_verify = false.")
            elif res or err:
                why = err or "; ".join(f"{k}: {v}" for k, v in (res.get("errors") or {}).items()) or "no readings"
                self.empty(cr, w, h, top, "GATEWAY UNREACHABLE", why)
            else:
                self.empty(cr, w, h, top, "READING…", "Asking the gateway.", color="static")
            return
        x0, x1 = 16, w - 16
        if cls == "compact":
            self._compact(cr, r, x0, x1, top, h, dec)
        elif cls == "wide":
            split = x0 + max(300, (x1 - x0) * 0.34)
            self._readouts(cr, r, x0, split - 16, top, h - 12, dec)
            self._curve(cr, split, x1, top, h - 12, r)
        elif cls == "large":
            mid = top + max(170, (h - top) * 0.42)
            self._flow(cr, r, x0, x0 + (x1 - x0) * 0.55, top, mid, dec)
            self._stats(cr, r, x0 + (x1 - x0) * 0.55 + 20, x1, top + 4, mid)
            self._curve(cr, x0, x1, mid + 12, h - 12, r, axis=True)
        elif cls == "tall":
            mid = top + max(200, (h - top) * 0.5)
            self._flow(cr, r, x0, x1, top, mid, dec)
            y = self._stats(cr, r, x0, x1, mid + 8, mid + 110, cols=2)
            if h - 12 - y > 80:
                self._curve(cr, x0, x1, y + 10, h - 12, r, axis=True)
        else:
            y = self._readouts(cr, r, x0, x1, top, h - 12, dec)
            if h - 12 - y > 80:
                self._curve(cr, x0, x1, y + 6, h - 12, r, axis=h - y > 130)

    def _compact(self, cr, r, x0, x1, top, h, dec):
        p = r.get("production_w")
        col = "phosphor" if p and p > 50 else "static"
        txt = f"{(p or 0) / 1000:.{dec}f}" if p is not None else "--"
        tw = D.seg7(cr, x0, top + 2, max(22, min(50, h - top - 48)), txt, col)
        D.label(cr, x0 + tw + 8, top + 4, "KW", col, size=11)
        D.label(cr, x0 + tw + 8, top + 22, "MAKING", "dim", size=10)
        self.region(x0, top, tw + 90, 56, f"The roof is making {power(p, 2)} now")
        y = h - 26
        t = r.get("today_wh")
        D.label(cr, x0, y, f"TODAY {energy(t)}", "soft", size=10)
        n = r.get("net_w")
        if n is not None:
            D.label(cr, x1, y, ("OUT " if n < 0 else "IN ") + power(abs(n), dec), "phosphor" if n <= 0 else "amber",
                    size=10, align="right")
        self.region(x0, y - 2, x1 - x0, 16, f"Made today: {energy(t)}"
                    + (f"; the grid: {'exporting' if n < 0 else 'importing'} {power(abs(n), 2)}" if n is not None else ""))

    def _readouts(self, cr, r, x0, x1, top, bottom, dec):
        """Making, using and the grid as three readouts; today and how much of the house the sun covers."""
        p, c, n = r.get("production_w"), r.get("consumption_w"), r.get("net_w")
        cols = [("MAKING", power(p, dec), "phosphor", f"The roof makes {power(p, 2)} now"
                 + (f" ({r['inverters']} inverters reporting)" if r.get("inverters") else "")),
                ("USING", power(c, dec), "soft", f"The house uses {power(c, 2)} now" if c is not None else
                 "What the house uses needs consumption CTs on the gateway; it has none"),
                ("GRID", ("↑ " + power(-n, dec)) if n is not None and n < 0 else ("↓ " + power(n, dec)) if n is not None
                 else "--", "phosphor" if (n or 0) <= 0 else "amber",
                 ("Exporting " + power(-n, 2) + " to the grid" if n < 0 else "Importing " + power(n, 2) + " from the grid")
                 if n is not None else "The grid flow needs consumption CTs on the gateway")]
        cw = (x1 - x0) / 3
        for i, (lab, val, col, tip) in enumerate(cols):
            cx = x0 + i * cw
            D.label(cr, cx, top, lab, "dim", size=10)
            D.text(cr, cx, top + 16, val, 20 if cw > 120 else 15, col, "bold", glow=col == "phosphor" and val != "--")
            self.region(cx, top - 2, cw - 6, 46, tip)
        y = top + 54
        sp = self_powered(r)
        if sp is not None:
            D.label(cr, x0, y, "SUN COVERS", "dim", size=10)
            D.label(cr, x1, y, f"{sp * 100:.0f}% OF THE HOUSE", "phosphor" if sp >= 1 else "soft", size=10, align="right")
            D.cells(cr, x0, y + 16, x1 - x0, 8, sp, n=30, warn=2, crit=2)
            self.region(x0, y - 2, x1 - x0, 28, f"The sun covers {sp * 100:.0f}% of what the house uses right now")
            y += 34
        if r.get("battery_pct") is not None:
            bw = r.get("battery_w")
            D.label(cr, x0, y, "BATTERY", "dim", size=10)
            D.label(cr, x1, y, f"{r['battery_pct']:.0f}%" + (f" · {'CHARGING' if bw < 0 else 'GIVING'} {power(abs(bw), dec)}"
                                                           if bw else ""), "soft", size=10, align="right")
            D.cells(cr, x0, y + 16, x1 - x0, 8, r["battery_pct"] / 100, n=30, warn=2, crit=2)
            self.region(x0, y - 2, x1 - x0, 28, f"Batteries at {r['battery_pct']:.0f}%"
                        + (f", {'charging at' if bw < 0 else 'giving'} {power(abs(bw), 2)}" if bw else ""))
            y += 34
        if y + 18 <= bottom:
            D.label(cr, x0, y, f"TODAY {energy(r.get('today_wh'))} MADE", "soft", size=10)
            if r.get("consumed_today_wh") is not None:
                D.label(cr, x1, y, f"{energy(r['consumed_today_wh'])} USED", "static", size=10, align="right")
            self.region(x0, y - 2, x1 - x0, 16, f"Since midnight: {energy(r.get('today_wh'))} made"
                        + (f", {energy(r['consumed_today_wh'])} used" if r.get("consumed_today_wh") is not None else ""))
            y += 20
        return y

    def _flow(self, cr, r, x0, x1, top, bottom, dec):
        """Sun, house, grid (and battery) as nodes, joined by lines as thick as the power on them."""
        p, c, n = r.get("production_w") or 0, r.get("consumption_w"), r.get("net_w")
        bat = r.get("battery_pct")
        cy = top + (bottom - top) * 0.5
        rad = max(18, min(34, (bottom - top) / 6))
        sun = (x0 + rad + 8, top + rad + 6)
        house = ((x0 + x1) / 2, cy + rad * 0.4)
        grid = (x1 - rad - 8, top + rad + 6)
        batt = (x1 - rad - 8, bottom - rad - 10) if bat is not None else None
        peak = max(1000.0, p, abs(n or 0), c or 0)

        def link(a, b, watts, col, tip):
            wdt = 1.5 + 7 * min(1.0, abs(watts or 0) / peak)
            D.src(cr, col if watts else "guard", 0.75 if watts else 0.9)
            cr.set_line_width(wdt)
            cr.move_to(*a)
            cr.line_to(*b)
            cr.stroke()
            mx, my = (a[0] + b[0]) / 2, (a[1] + b[1]) / 2
            if watts:
                t = power(abs(watts), dec)
                tw_ = D.layout(cr, t, 11, "semibold").get_pixel_size()[0]
                D.src(cr, "void", 0.9)
                cr.rectangle(mx - tw_ / 2 - 4, my - 9, tw_ + 8, 18)
                cr.fill()
                D.text(cr, mx, my - 8, t, 11, col, "semibold", align="center")
            self.region(mx - 50, my - 20, 100, 30, tip)
        to_house = min(p, c) if c is not None else p
        link(sun, house, to_house, "phosphor", f"The sun gives the house {power(to_house, 2)}")
        if n is not None:
            link(grid, house, n if n > 0 else -n, "amber" if n > 0 else "phosphor",
                 f"Importing {power(n, 2)} from the grid" if n > 0 else f"Exporting {power(-n, 2)} to the grid")
        if batt:
            bw = r.get("battery_w") or 0
            link(batt, house, bw, "cyan", (f"The batteries charge at {power(-bw, 2)}" if bw < 0 else
                                           f"The batteries give {power(bw, 2)}") if bw else "The batteries rest")
        cr.set_line_width(1)

        def node(pt, label, value, col, tip, frac=None):
            x, y = pt
            D.src(cr, "void", 1)
            cr.arc(x, y, rad, 0, 2 * math.pi)
            cr.fill()
            if frac is not None:
                D.ring(cr, x, y, rad, frac, 4, col)
            else:
                D.src(cr, col, 0.9)
                cr.set_line_width(2)
                cr.arc(x, y, rad, 0, 2 * math.pi)
                cr.stroke()
                cr.set_line_width(1)
            D.text(cr, x, y - 8, value, 11 if rad < 26 else 13, col, "bold", align="center")
            D.label(cr, x, y + rad + 6, label, "dim", size=10, align="center")
            self.region(x - rad, y - rad, 2 * rad, 2 * rad + 22, tip)
        node(sun, "SUN", power(p, dec), "phosphor" if p > 50 else "static", f"The roof makes {power(p, 2)}"
             + (f" ({r['inverters']} inverters reporting)" if r.get("inverters") else ""))
        node(house, "HOUSE", power(c, dec), "soft", f"The house uses {power(c, 2)}" if c is not None else
             "What the house uses needs consumption CTs on the gateway", self_powered(r))
        node(grid, "GRID", power(abs(n), dec) if n is not None else "--", "amber" if (n or 0) > 0 else "phosphor",
             ("Importing " if (n or 0) > 0 else "Exporting ") + power(abs(n or 0), 2) if n is not None else
             "The grid flow needs consumption CTs on the gateway")
        if batt:
            node(batt, "BATTERY", f"{bat:.0f}%", "cyan", f"Batteries at {bat:.0f}%", bat / 100)

    def _stats(self, cr, r, x0, x1, top, bottom, cols=1):
        rows = [("MADE TODAY", energy(r.get("today_wh")), "Made since midnight"),
                ("USED TODAY", energy(r.get("consumed_today_wh")), "Used since midnight (needs consumption CTs)"),
                ("SUN COVERS", f"{self_powered(r) * 100:.0f}%" if self_powered(r) is not None else "--",
                 "The share of what the house uses that the sun covers now"),
                ("LIFETIME", energy(r.get("lifetime_wh")), "Everything the system has made"),
                ("INVERTERS", str(int(r["inverters"])) if r.get("inverters") is not None else "--",
                 "Microinverters reporting to the gateway")]
        cw = (x1 - x0 - (cols - 1) * 16) / cols
        y0 = top
        for i, (lab, val, tip) in enumerate(rows):
            c_, r_ = i % cols, i // cols
            x = x0 + c_ * (cw + 16)
            y = y0 + r_ * 22
            if y + 18 > bottom:
                break
            D.label(cr, x, y, lab, "dim", size=10)
            D.text(cr, x + cw, y - 2, val, 12, "soft", "semibold", align="right")
            self.region(x, y - 2, cw, 20, f"{tip}: {val}")
        return y0 + -(-len(rows) // cols) * 22

    def _curve(self, cr, x0, x1, top, bottom, r, axis=False):
        """Today from midnight: production as a filled area, the house as a line."""
        pts = self.curve or []
        m = midnight()
        span = 24 * 3600
        D.label(cr, x0, top, "TODAY", "dim", size=10)
        made = sum((pts[i + 1][0] - pts[i][0]) * (pts[i][1] or 0) for i in range(len(pts) - 1)
                   if pts[i + 1][0] - pts[i][0] < 1800) / 3600
        by, bh = top + 16, bottom - top - 16 - (14 if axis else 0)
        D.src(cr, "void", 0.8)
        cr.rectangle(x0, by, x1 - x0, bh)
        cr.fill()
        D.src(cr, "guard", 1)
        cr.set_line_width(1)
        for hr in range(3, 24, 3):
            gx = round(x0 + (x1 - x0) * hr / 24) + 0.5
            cr.move_to(gx, by)
            cr.line_to(gx, by + bh)
        cr.stroke()
        if axis:
            for hr in range(3, 24, 3):
                D.label(cr, x0 + (x1 - x0) * hr / 24, by + bh + 2, f"{hr:02d}", "static", size=10, align="center")
        src = "metrics" if self.hist_q else "this panel's own samples"
        if len(pts) < 2:
            D.text(cr, x0 + 8, by + bh / 2 - 8, "The day's curve fills in as this panel runs.", 10, "static", "regular",
                   width=x1 - x0 - 16)
            self.region(x0, top, x1 - x0, bottom - top, "Today's production and use, from " + src + "; it fills in "
                        "while the panel runs (or set history_metric on the enphase source)")
            return
        peak = max(max((p[1] or 0) for p in pts), max((p[2] or 0) for p in pts), 500)

        def xy(t, v):
            return x0 + (x1 - x0) * (t - m) / span, by + bh - (bh - 4) * (v or 0) / peak
        cr.move_to(*xy(pts[0][0], 0))
        for t, p, _c in pts:
            cr.line_to(*xy(t, p))
        cr.line_to(*xy(pts[-1][0], 0))
        cr.close_path()
        D.src(cr, "phosphor", 0.22)
        cr.fill_preserve()
        D.src(cr, "phosphor", 0.9)
        cr.set_line_width(1.5)
        cr.new_path()
        for i, (t, p, _c) in enumerate(pts):
            (cr.line_to if i else cr.move_to)(*xy(t, p))
        cr.stroke()
        house = [(t, c) for t, _p, c in pts if c is not None]
        if len(house) >= 2:
            D.src(cr, "amber", 0.85)
            cr.set_line_width(1.2)
            for i, (t, c) in enumerate(house):
                (cr.line_to if i else cr.move_to)(*xy(t, c))
            cr.stroke()
        cr.set_line_width(1)
        nx, _ = xy(self.now_t or time.time(), 0)
        D.src(cr, "soft", 0.6)
        cr.move_to(round(nx) + 0.5, by)
        cr.line_to(round(nx) + 0.5, by + bh)
        cr.stroke()
        D.label(cr, x1, top, f"PEAK {power(max((p[1] or 0) for p in pts))}", "soft", size=10, align="right")
        self.region(x0, top, x1 - x0, bottom - top, f"Today from midnight ({src}): production as the green area "
                    f"(peak {power(max((p[1] or 0) for p in pts), 2)}, about {energy(made)} in these samples)"
                    + (", what the house uses as the amber line" if len(house) >= 2 else "") + "; the line marks now")
