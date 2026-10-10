"""ALERTS: the homelab's firing and pending alerts (bromigos-homelab's alerts capability:
a prometheus, victoriametrics or alertmanager source in homelab.toml).

A panel generator (widgets/plugins.py): it offers the "alerts" panel only while something
provides alerts, so the widget gallery lists it only then. Each alert clicks through to
its page on the source that raised it (Alertmanager's, or the Prometheus alerts page).
"""
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

NAME = "alerts"
SEVERITIES = ("critical", "error", "warning", "info", "none")
COLOR = {"critical": "danger", "error": "danger", "warning": "amber", "info": "cyan", "none": "static"}


def _demo_lab():
    return os.environ.get("BROMIGOS_WIDGETS_DEMO_LAB") == "1"


def names():
    return {NAME: 1} if available()[0] else {}


def available():
    """(True, "") when the panel has a source, else (False, why): names()' check, no network."""
    if _demo_lab():
        return True, ""
    try:
        import bromigos_homelab as H
    except ImportError:
        return False, "bromigos-homelab isn't installed"
    return (True, "") if H.available("alerts") else (False, "no [[source]] in homelab.toml provides alerts (prometheus, victoriametrics or alertmanager)")


def panel(name):
    return AlertsPanel, {"visible": False}


# ------------------------------------------------------------------ the data
def severity(a):
    s = str(a.get("severity") or (a.get("labels") or {}).get("severity") or "none").lower()
    return {"page": "critical", "crit": "critical", "high": "critical", "warn": "warning", "medium": "warning",
            "low": "info"}.get(s, s if s in SEVERITIES else "none")


def sort_alerts(items):
    """Firing before pending, then the worst severity, then the oldest first."""
    def key(a):
        return (a.get("state") != "firing", SEVERITIES.index(severity(a)), K.iso_time(a.get("since")) or 0)
    return sorted(items, key=key)


def counts(items):
    out = {"firing": 0, "pending": 0}
    for s in SEVERITIES:
        out[s] = 0
    for a in items:
        out["firing" if a.get("state") == "firing" else "pending"] += 1
        if a.get("state") == "firing":
            out[severity(a)] += 1
    return out


def worst(items):
    firing = [a for a in items if a.get("state") == "firing"]
    if not firing:
        return None
    return min((severity(a) for a in firing), key=SEVERITIES.index)


LABEL_SKIP = {"alertname", "severity", "prometheus", "alertstate", "__name__"}


def label_bits(a, limit=4):
    lb = a.get("labels") or {}
    keys = [k for k in ("namespace", "instance", "job", "pod", "service", "node", "container") if lb.get(k)]
    keys += [k for k in sorted(lb) if k not in keys and k not in LABEL_SKIP]
    return [f"{k}={lb[k]}" for k in keys[:limit]]


def demo_result():
    now = time.time()

    def at(m):
        return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now - m * 60))
    items = [
        {"name": "DiskWillFillIn4Hours", "severity": "critical", "state": "firing", "since": at(38),
         "summary": "The archive volume on mast-2 will be full in about 4 hours at this rate.",
         "labels": {"alertname": "DiskWillFillIn4Hours", "instance": "mast-2", "mountpoint": "/srv/archive",
                    "severity": "critical"}, "link": "https://alerts.example.org/#/alerts", "source": "metrics"},
        {"name": "PodCrashLooping", "severity": "warning", "state": "firing", "since": at(12),
         "summary": "Pod media/thumbnailer-7c9 restarted 6 times in 15 minutes.",
         "labels": {"alertname": "PodCrashLooping", "namespace": "media", "pod": "thumbnailer-7c9",
                    "severity": "warning"}, "link": "https://alerts.example.org/#/alerts", "source": "metrics"},
        {"name": "CertificateExpiresSoon", "severity": "warning", "state": "firing", "since": at(60 * 26),
         "summary": "The certificate for files.example.org expires in 9 days.",
         "labels": {"alertname": "CertificateExpiresSoon", "namespace": "edge", "severity": "warning"},
         "link": "https://alerts.example.org/#/alerts", "source": "metrics"},
        {"name": "HighRequestLatency", "severity": "warning", "state": "pending", "since": at(3),
         "summary": "p95 latency on the gateway is above 800 ms.",
         "labels": {"alertname": "HighRequestLatency", "job": "gateway", "severity": "warning"},
         "link": "https://alerts.example.org/#/alerts", "source": "metrics"},
        {"name": "BackupOlderThan26h", "severity": "info", "state": "firing", "since": at(95),
         "summary": "The nightly backup of the photo library hasn't finished since yesterday.",
         "labels": {"alertname": "BackupOlderThan26h", "job": "backups", "severity": "info"},
         "link": "https://alerts.example.org/#/alerts", "source": "metrics"},
    ]
    return {"ok": True, "items": items, "errors": {}, "sources": ["metrics"]}


# ------------------------------------------------------------------ the panel
class AlertsPanel(K.KitPanel):
    name, title = NAME, "ALERTS"
    description = "The homelab's firing and pending alerts, worst first; click one for its page"
    category, reads = "homelab", "your homelab's alerts (Prometheus or Alertmanager)"
    width, height = 460, 300
    interval = 5.0                     # the draw refresh; the alerts are read every 30 s
    sizes = {
        "compact": ((240, 120), (380, 190), (280, 140)),
        "standard": ((400, 150), (620, 420), (460, 300)),
        "wide": ((640, 180), (1100, 360), (780, 240)),
        "tall": ((380, 440), (560, 900), (420, 560)),
        "large": ((660, 460), (1200, 900), (760, 560)),
    }
    default_size = "standard"
    fit = "content"                    # as tall as its alerts (four of them: no 300 px box)

    @classmethod
    def available(cls):
        return available()

    def natural_height(self, width, cls=None):
        """All clear: the ring and its words; else what the list draws (measured)."""
        r = self.result()
        if r and r.get("ok") and r.get("sources") and not (r.get("items") or []):
            return 120
        return super().natural_height(width, cls)
    settings = [{"key": "show_pending", "label": "Show pending alerts", "kind": "bool", "default": True,
                 "hint": "Pending: the condition holds but hasn't lasted long enough to fire"}]

    def __init__(self, cfg=None, wake=None):
        super().__init__(cfg, wake)
        self.res = None
        self.read_at = 0
        if K.demo():
            self.res = demo_result()
            self.read_at = time.time() - 9
        else:
            self.poll = self.poller(self.fetch, every=30)

    def fetch(self):
        import bromigos_homelab as H
        r = H.alerts()
        self.read_at = time.time()
        return r

    def result(self):
        if K.demo():
            return self.res
        return self.poll.data

    # ---- drawing
    def draw(self, cr, w, h):
        cls = self.size_class(w, h)
        r = self.result()
        items = sort_alerts((r or {}).get("items") or [])
        if not self.conf.get("show_pending", True):
            items = [a for a in items if a.get("state") == "firing"]
        c = counts(items)
        bad = worst(items)
        right = None
        if r and r.get("ok") and cls != "compact":
            right = (f"{c['firing']} FIRING" + (f" · {c['pending']} PENDING" if c["pending"] else "")) if items else "ALL CLEAR"
        top = D.frame(cr, w, h, self.title, right, COLOR.get(bad, "phosphor") if items else "phosphor")
        srcs = ", ".join((r or {}).get("sources") or []) or "none"
        self.region(0, 0, w, 34, f"Alerts from your homelab ({srcs}), read every 30 s"
                    + (f", last {K.ago(self.read_at)} ago" if r else "") + ". Worst first; click an alert for its page.")
        if r is None:
            if getattr(self, "poll", None) and self.poll.error:
                self.empty(cr, w, h, top, "CAN'T READ ALERTS", self.poll.error)
            else:
                self.empty(cr, w, h, top, "READING…", "Asking the homelab for its alerts.", color="static")
            return
        if not r.get("sources"):
            self.empty(cr, w, h, top, "NO ALERT SOURCE",
                       "Add a source that provides alerts to ~/.config/bromigos/homelab.toml: [[source]] with "
                       "type = \"prometheus\" (or \"alertmanager\") and its endpoint. bromigos setup homelab finds one.")
            return
        if not r.get("ok"):
            why = "; ".join(f"{k}: {v}" for k, v in (r.get("errors") or {}).items())
            self.empty(cr, w, h, top, "ALERTS UNREACHABLE", why or "No source answered.",
                       tip=f"No alert source answered: {why}")
            return
        if not items:
            self._clear(cr, w, h, top, cls)
            return
        x0, x1 = 16, w - 16
        if cls == "compact":
            self._compact(cr, items, c, bad, x0, x1, top, h)
        elif cls == "wide":
            split = x0 + (190 if h >= 260 else 250)
            self._tiles(cr, c, x0, split - 16, top, h - 14, cols=1 if h >= 260 else 2)
            self._list(cr, items, split, x1, top, h - 12, two_cols=w >= 900)
        elif cls == "large":
            self._tiles(cr, c, x0, x1, top, top + 58, cols=5)
            self._timeline(cr, items, x0, x1, top + 72, top + 132)
            self._list(cr, items, x0, x1, top + 146, h - 12, grouped=True, wrap=True, labels=True)
        elif cls == "tall":
            self._tiles(cr, c, x0, x1, top, top + 52, cols=3)
            self._list(cr, items, x0, x1, top + 66, h - 12, grouped=True, wrap=True)
        else:
            self._list(cr, items, x0, x1, top, h - 12)
        errs = r.get("errors") or {}
        if errs:
            D.label(cr, x1, h - 18, f"{len(errs)} SOURCE(S) DOWN", "amber", size=10, align="right")
            self.region(x1 - 160, h - 20, 160, 16, "Not every alert source answered: "
                        + "; ".join(f"{k}: {v}" for k, v in errs.items()))

    def _clear(self, cr, w, h, top, cls):
        cx, cy = w / 2, top + (h - top) / 2 - 8
        r = max(14, min(38, (h - top) / 3))
        if cls != "compact" and h > 150:
            D.ring(cr, cx, cy, r, 1.0, 5, "phosphor")
            D.text(cr, cx, cy - 9, "OK", 15, "phosphor", "bold", align="center", glow=True)
            D.label(cr, cx, cy + r + 12, "NOTHING FIRING", "soft", align="center")
        else:
            D.label(cr, 16, top + 8, "ALL CLEAR", "phosphor", size=14)
            D.text(cr, 16, top + 32, "Nothing firing or pending.", 11, "soft", "regular")
        self.region(0, top, w, h - top, "No alert is firing or pending on your homelab right now")

    def _compact(self, cr, items, c, bad, x0, x1, top, h):
        col = COLOR.get(bad, "amber" if c["pending"] else "phosphor")
        n = c["firing"]
        tw = D.seg7(cr, x0, top + 2, max(22, min(52, h - top - 46)), f"{n}", col)
        D.label(cr, x0 + tw + 10, top + 4, "FIRING", col, size=10)
        if c["pending"]:
            D.label(cr, x0 + tw + 10, top + 22, f"{c['pending']} PENDING", "static", size=10)
        self.region(x0, top, tw + 110, 56, f"{n} alert(s) firing, {c['pending']} pending"
                    + (f"; the worst is {bad}" if bad else ""))
        a = items[0]
        y = h - 26
        D.src(cr, COLOR[severity(a)], 0.9)
        cr.rectangle(x0, y + 2, 3, 14)
        cr.fill()
        D.text(cr, x0 + 9, y, a.get("name") or "?", 11, "soft", "semibold", width=x1 - x0 - 60)
        D.label(cr, x1, y + 1, K.ago(K.iso_time(a.get("since"))), "static", size=10, align="right")
        self._hint(a, x0, y - 2, x1 - x0, 20)

    def _hint(self, a, x, y, w, h):
        since = K.iso_time(a.get("since"))
        tip = (f"{a.get('name')}: {severity(a)}, {a.get('state')}"
               + (f" for {K.ago(since)}" if since else "")
               + (f". {a['summary']}" if a.get("summary") else "")
               + (f" ({', '.join(label_bits(a, 6))})" if label_bits(a) else "")
               + (f". From {a.get('source')}." if a.get("source") else ".")
               + (" Click to open it on the source." if a.get("link") else " Its source gives no page to open."))
        link = a.get("link")
        self.region(x, y, w, h, tip, (lambda u=link: K.open_url(u)) if link else None)

    def _tiles(self, cr, c, x0, x1, top, bottom, cols):
        tiles = [("critical", c["critical"] + c["error"], "danger"), ("warning", c["warning"], "amber"),
                 ("info", c["info"] + c["none"], "cyan"), ("pending", c["pending"], "static")]
        if cols == 5:
            tiles.insert(0, ("firing", c["firing"], "danger" if c["firing"] else "phosphor"))
        if cols == 3:
            tiles = tiles[:2] + [("pending", c["pending"], "static")]
        rows = -(-len(tiles) // cols)
        tw = (x1 - x0 - (cols - 1) * 8) / cols
        th = (bottom - top - (rows - 1) * 8) / rows
        for i, (name, n, col) in enumerate(tiles):
            tx = x0 + (i % cols) * (tw + 8)
            ty = top + (i // cols) * (th + 8)
            D.src(cr, col if n else "guard", 0.14 if n else 0.6)
            cr.rectangle(tx, ty, tw, th)
            cr.fill()
            D.src(cr, col if n else "dim", 0.8)
            cr.set_line_width(1)
            cr.rectangle(tx + 0.5, ty + 0.5, tw - 1, th - 1)
            cr.stroke()
            big = min(24, th - 16)
            D.text(cr, tx + 10, ty + (th - big) / 2 - 2, str(n), big, col if n else "static", "bold", glow=bool(n))
            D.label(cr, tx + tw - 8, ty + th / 2 - 7, name, col if n else "static", size=10, align="right")
            what = {"critical": "critical (and error) alerts firing", "warning": "warnings firing",
                    "info": "informational alerts firing", "pending": "alerts pending: the condition holds, not long "
                    "enough yet to fire", "firing": "alerts firing in all"}[name]
            self.region(tx, ty, tw, th, f"{n} {what}")

    def _timeline(self, cr, items, x0, x1, top, bottom):
        """Each alert as a bar from when it started to now, over the last 24 hours."""
        now = time.time()
        span = 24 * 3600
        D.label(cr, x0, top, "LAST 24 HOURS", "dim", size=10)
        for k, t in ((2, "-16H"), (4, "-8H")):
            D.label(cr, x0 + (x1 - x0) * k / 6, top, t, "static", size=10, align="center")
        D.label(cr, x1, top, "NOW", "static", size=10, align="right")
        by = top + 16
        bh = bottom - by
        D.src(cr, "void", 0.8)
        cr.rectangle(x0, by, x1 - x0, bh)
        cr.fill()
        D.src(cr, "guard", 1)
        cr.set_line_width(1)
        for k in range(1, 6):
            gx = round(x0 + (x1 - x0) * k / 6) + 0.5
            cr.move_to(gx, by)
            cr.line_to(gx, bottom)
        cr.stroke()
        n = max(1, len(items))
        lane = max(3, min(10, (bh - 4) / n))
        for i, a in enumerate(items[:int((bh - 4) // lane) or 1]):
            t = K.iso_time(a.get("since")) or now
            sx = x0 + (x1 - x0) * max(0.0, 1 - (now - t) / span)
            col = COLOR[severity(a)]
            D.src(cr, col, 0.85 if a.get("state") == "firing" else 0.35)
            cr.rectangle(sx, by + 2 + i * lane, max(2, x1 - sx), lane - 1.5)
            cr.fill()
            self._hint(a, sx, by + 2 + i * lane, max(4, x1 - sx), lane - 1)
        self.region(x0, top, x1 - x0, 14, "Each alert's bar starts when it began (the last 24 hours; older ones start "
                    "at the left edge); the colour is its severity, faint while pending. Gridlines every 4 hours.")

    def _list(self, cr, items, x0, x1, top, bottom, grouped=False, wrap=False, labels=False, two_cols=False):
        cols = 2 if two_cols else 1
        cw = (x1 - x0 - (cols - 1) * 16) / cols
        col_i, y = 0, top
        last = None
        hidden = 0
        for idx, a in enumerate(items):
            sev = severity(a)
            group = "PENDING" if a.get("state") != "firing" else sev.upper()
            need = 24 + (16 if wrap and a.get("summary") else 0) + (17 if labels and label_bits(a) else 0)
            need += 22 if grouped and group != last else 0
            if y + need > bottom:
                if col_i + 1 < cols:
                    col_i, y, last = col_i + 1, top, None
                else:
                    hidden = len(items) - idx
                    break
            cx = x0 + col_i * (cw + 16)
            if grouped and group != last:
                last = group
                n = sum(1 for b in items if ("PENDING" if b.get("state") != "firing" else severity(b).upper()) == group)
                gc = "static" if group == "PENDING" else COLOR[sev]
                lw = D.label(cr, cx, y + 2, f"{group} · {n}", gc, size=10)[0]
                D.rule(cr, cx + lw + 8, y + 9, cx + cw, "dim", 0.3)
                self.region(cx, y, cw, 18, f"{n} alert(s) {'pending' if group == 'PENDING' else group.lower() + ', firing'}")
                y += 22
            y += self._row(cr, a, cx, cx + cw, y, wrap, labels) + 4
        if hidden:
            D.label(cr, x1, bottom - 12, f"+{hidden} MORE", "static", size=10, align="right")
            self.region(x1 - 90, bottom - 14, 90, 14, f"{hidden} more alert(s); make the panel larger to see them")

    def _row(self, cr, a, x0, x1, y, wrap, labels):
        sev = severity(a)
        col = COLOR[sev]
        firing = a.get("state") == "firing"
        D.src(cr, col, 0.95 if firing else 0.4)
        cr.rectangle(x0, y + 2, 3, 15)
        cr.fill()
        since = K.iso_time(a.get("since"))
        agew = D.label(cr, x1, y + 2, K.ago(since) + ("" if firing else " · PEND"), "static" if firing else "dim",
                       size=10, align="right")[0]
        D.text(cr, x0 + 10, y + 1, a.get("name") or "?", 12, "soft" if firing else "static", "semibold",
               width=max(40, (x1 - x0) * 0.45 if not wrap else x1 - x0 - agew - 24))
        hh = 20
        if not wrap and a.get("summary"):
            nw = min((x1 - x0) * 0.45, D.layout(cr, a.get("name") or "?", 12, "semibold").get_pixel_size()[0])
            D.text(cr, x0 + 18 + nw, y + 3, a["summary"], 10, "static", "regular", width=max(0, x1 - x0 - nw - agew - 34))
        if wrap and a.get("summary"):
            D.text(cr, x0 + 10, y + 19, a["summary"], 10, "static", "regular", width=x1 - x0 - 10)
            hh += 16
        if labels and label_bits(a):
            lx = x0 + 10
            for b in label_bits(a):
                bw = D.layout(cr, b, 9, "medium").get_pixel_size()[0] + 10
                if lx + bw > x1:
                    break
                D.src(cr, "guard", 0.9)
                cr.rectangle(lx, y + hh + 1, bw, 14)
                cr.fill()
                D.text(cr, lx + 5, y + hh + 2, b, 9, "dim", "medium")
                lx += bw + 4
            hh += 17
        self._hint(a, x0, y, x1 - x0, hh)
        return hh
