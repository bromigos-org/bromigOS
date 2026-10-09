"""The LAB panel: the lab snapshot at a glance (bromigos-homelab; docs/homelab.md).

Nodes, pods, Argo, alerts, services, storage: whatever the homelab's snapshot carries (a
Lab API's, or one assembled from the capabilities). Drawn with the widgets' own
primitives (draw.py), like every panel. It exists only when homelab.toml has a snapshot
source (homelab_panels.py decides); a source that's down reads "LAB UNREACHABLE".
"""
import math
import threading
import time
import urllib.error

import draw as D
import sources as S
from panels import Panel, copy_text, open_url

import bromigos_homelab as H


OBJECT_STORE = "rustfs"                  # the object store's service id, and its namespace


def store_share(nas):
    """The NAS share that holds the object store's volumes, found in the snapshot (each share
    lists the claims bound on it, as namespace/name), or None. The share's name is the lab's
    own; nothing here knows it."""
    for sh in nas.get("shares") or []:
        claims = [v.get("claim") or "" for v in sh.get("volumes") or []]
        if sh.get("usage") is not None and any(c.split("/", 1)[0] == OBJECT_STORE for c in claims):
            return sh
    return None


class LabSource(threading.Thread):
    """Polls the snapshot every `every` s. state: 'ok' | 'stale' | 'unauthorized' | 'down'."""

    def __init__(self, every=20, on_update=None):
        super().__init__(daemon=True)
        self.every = every
        self.on_update = on_update
        self.data = None
        self.state = "down"
        self.error = ""
        self.fetched = 0
        self.where = H.snapshot_source() or "none"

    def run(self):
        while True:
            self.poll()
            time.sleep(self.every)

    def poll(self):
        self.where = H.snapshot_source() or "none"
        try:
            d = H.snapshot()
            if d is None:
                self.state, self.error = "down", "nothing in homelab.toml provides a snapshot"
                return
            self.data = d
            self.fetched = time.time()
            age = time.time() - float(d.get("generatedAt") or 0)
            self.state = "stale" if age > 120 else "ok"
            self.error = ""
        except urllib.error.HTTPError as e:
            self.state = "unauthorized" if e.code in (401, 403) else "down"
            self.error = f"HTTP {e.code}"
        except (OSError, ValueError) as e:
            self.state, self.error = "down", str(e)[:80]
        if self.on_update:
            self.on_update()


class LabPanel(Panel):
    name, title = "lab", "LAB"
    height = 640
    interval = 1.0                       # redraw cadence for the freshness clock; data every 20 s

    def __init__(self, cfg=None, wake=None):
        super().__init__(cfg)
        src = H.source_of("lab")
        label = (src.opts.get("title") if src else None) or (self.cfg or {}).get("label")
        self.title = f"LAB · {label.upper()}" if label else "LAB"
        self.lab = LabSource(every=20, on_update=self._new)
        self.pulse_at = 0
        self._wake = wake
        self.lab.start()

    def _new(self):
        self.pulse_at = time.time()
        if self._wake:
            self._wake(self)

    @property
    def animating(self):
        return time.time() - self.pulse_at < 1.6

    @animating.setter
    def animating(self, _v):
        pass

    def draw(self, cr, w, h):
        L, d = self.lab, self.lab.data
        age = time.time() - L.fetched if L.fetched else None
        state_txt = {"ok": f"SYNC {int(age)}s AGO" if age is not None else "SYNC",
                     "stale": "SNAPSHOT STALE", "no-token": "NO TOKEN",
                     "unauthorized": "TOKEN REFUSED", "down": "LAB UNREACHABLE"}[L.state]
        state_col = {"ok": "static", "stale": "amber"}.get(L.state, "danger")
        top = D.frame(cr, w, h, self.title, state_txt, state_col)
        if L.state == "ok":
            pulse = max(0.0, 1 - (time.time() - self.pulse_at) / 1.6)
            tw = D.layout(cr, state_txt.upper(), 11, "semibold", 0.18).get_pixel_size()[0]
            D.dot(cr, w - 16 - tw - 10, 18, 2.5 + 2 * pulse, "phosphor", glow=True)
        self.region(0, 0, w, 34, f"The lab snapshot ({L.where}, every 20 s; homelab.toml). "
                    f"State: {L.state}{' - ' + L.error if L.error else ''}."
                    + (" Click to open the Lab." if H.lab_url() else ""),
                    (lambda: open_url(H.lab_url())) if H.lab_url() else None)
        x0, x1 = 16, w - 16
        if not d:
            D.text(cr, x0, top + 10, L.error or "waiting for the first snapshot", 12, "amber", width=x1 - x0)
            return
        c = d.get("cluster", {})
        y = top
        # --- summary strip
        alerts = int(c.get("alertsFiring") or 0)
        argo = d.get("argocd") or {}
        items = [
            ("NODES", f"{c.get('nodesReady', 0)}/{c.get('nodesTotal', 0)}",
             "phosphor" if c.get("nodesReady") == c.get("nodesTotal") else "amber",
             "Kubernetes nodes Ready / total"),
            ("PODS", f"{int(c.get('podsRunning') or 0)}", "danger" if c.get("podsNotRunning") else "phosphor",
             f"Pods running; {int(c.get('podsNotRunning') or 0)} not running"),
            ("ARGO", f"{argo.get('healthy', 0)}/{argo.get('total', 0)}",
             "phosphor" if argo.get("healthy") == argo.get("total") else "amber",
             "ArgoCD applications healthy / total. Click to open ArgoCD."),
            ("ALERTS", f"{alerts}", "amber" if alerts else "phosphor",
             "Prometheus alerts firing. Click to open Alertmanager."),
        ]
        acts = [None, None, lambda: open_url(self._svc_url(d, "argocd")),
                lambda: open_url(self._svc_url(d, "alertmanager"))]
        cw = (x1 - x0) / len(items)
        for i, (k, v, col, tip) in enumerate(items):
            ix = x0 + i * cw
            D.label(cr, ix, y, k, "dim")
            D.text(cr, ix, y + 14, v, 20, col, "bold", glow=True)
            self.region(ix, y, cw - 6, 40, tip, acts[i])
        y += 50
        D.rule(cr, x0, y, x1)
        y += 10
        # --- node map: a bus with the nodes hanging off it
        y = self._nodes(cr, d, x0, x1, y)
        D.rule(cr, x0, y, x1)
        y += 10
        # --- services matrix
        y = self._services(cr, d, x0, x1, y)
        D.rule(cr, x0, y, x1)
        y += 10
        # --- storage pools
        self._pools(cr, d, x0, x1, y)

    def _svc_url(self, d, sid):
        for g in d.get("config", {}).get("groups", []):
            for s in g.get("services", []):
                if s.get("id") == sid:
                    return s.get("lan") or s.get("wan") or H.lab_url()
        dom = H.config.setting("services", "domain", "")
        return f"https://{sid}.{dom}" if dom else H.lab_url()

    def _nodes(self, cr, d, x0, x1, y):
        nodes = d.get("nodes") or []
        D.label(cr, x0, y, "NODE MAP", "dim")
        cl = d.get("cluster", {})
        D.label(cr, x1, y, f"CLUSTER CPU {cl.get('cpuNow', 0):.0f}%", "static", align="right")
        y += 20
        n = max(1, len(nodes))
        bw = (x1 - x0 - (n - 1) * 8) / n
        bus_y = y + 4
        D.src(cr, "dim", 0.6)
        cr.set_line_width(1)
        cr.move_to(x0, bus_y + 0.5)
        cr.line_to(x1, bus_y + 0.5)
        cr.stroke()
        pulse = max(0.0, 1 - (time.time() - self.pulse_at) / 1.6)
        for i, nd in enumerate(nodes):
            bx = x0 + i * (bw + 8)
            cx = bx + bw / 2
            cpu, mem = nd.get("cpuPct", 0) / 100, nd.get("memPct", 0) / 100
            worst = max(D.level(cpu, 0.85, 0.95), D.level(mem, 0.9, 0.97),
                        key=["phosphor", "amber", "danger", "static"].index)
            D.src(cr, "dim", 0.6)
            cr.move_to(cx + 0.5, bus_y)
            cr.line_to(cx + 0.5, bus_y + 10)
            cr.stroke()
            by = bus_y + 10
            D.src(cr, "void", 0.7)
            cr.rectangle(bx, by, bw, 76)
            cr.fill()
            D.brackets(cr, bx, by, bw, 76, 6, worst, 1.2, 0.9)
            D.dot(cr, bx + 9, by + 11, 2.5 + 1.5 * pulse, worst, glow=True)
            D.text(cr, bx + 18, by + 4, nd.get("name", "?").replace("k8s-", "").upper(), 10, "soft", "semibold", spacing=0.08, width=bw - 22)
            D.label(cr, bx + 6, by + 25, "CPU", "dim", size=10)
            D.bar(cr, bx + 40, by + 30, bw - 46, 5, cpu, D.level(cpu, 0.85, 0.95))
            D.label(cr, bx + 6, by + 41, "MEM", "dim", size=10)
            D.bar(cr, bx + 40, by + 46, bw - 46, 5, mem, D.level(mem, 0.9, 0.97))
            D.label(cr, bx + 6, by + 57, f"L{nd.get('load1', 0):.1f} · {nd.get('cores', '?')}C", "static", size=10)
            self.region(bx, by, bw, 76, f"Node {nd.get('name')}: CPU {nd.get('cpuPct', 0):.0f}%, memory "
                        f"{nd.get('memPct', 0):.0f}%, load {nd.get('load1', 0):.2f} on {nd.get('cores')} cores. "
                        "Amber: memory past 90% or CPU past 85%.")
        return bus_y + 10 + 76 + 12

    def _services(self, cr, d, x0, x1, y):
        groups = d.get("config", {}).get("groups", [])
        status = d.get("services", {})
        total = sum(len(g.get("services", [])) for g in groups)
        up = sum(1 for g in groups for s in g.get("services", []) if status.get(s["id"], {}).get("status") == "up")
        D.label(cr, x0, y, "SERVICES", "dim")
        D.label(cr, x1, y, f"{up}/{total} UP", "phosphor" if up == total else "amber", align="right")
        y += 20
        cols = 4
        cw = (x1 - x0 - (cols - 1) * 4) / cols
        ch = 21
        for g in groups:
            D.label(cr, x0, y, g.get("name", ""), "static", size=10)
            y += 16
            for i, s in enumerate(g.get("services", [])):
                r, c = divmod(i, cols)
                cx, cy = x0 + c * (cw + 4), y + r * (ch + 3)
                st = status.get(s["id"], {})
                state = st.get("status")
                col = {"up": "phosphor", "down": "danger"}.get(state, "amber")
                D.src(cr, col, 0.10 if state == "up" else 0.22)
                cr.rectangle(cx, cy, cw, ch)
                cr.fill()
                D.src(cr, col, 0.55 if state == "up" else 1)
                cr.set_line_width(1)
                cr.rectangle(cx + 0.5, cy + 0.5, cw - 1, ch - 1)
                cr.stroke()
                D.src(cr, col)
                cr.rectangle(cx + 5, cy + ch / 2 - 2, 4, 4)
                cr.fill()
                D.text(cr, cx + 14, cy + 3, s.get("name", s["id"]).upper(), 10,
                       "soft" if state == "up" else col, "semibold", spacing=0.06, width=cw - 18)
                url = s.get("lan") or s.get("wan")
                ms = st.get("ms")
                tip = (f"{s.get('name')} ({s.get('role', '')}): {state or 'unknown'}"
                       + (f", answered in {ms:.0f} ms" if isinstance(ms, (int, float)) else "")
                       + (f". Click to open {url}" if url else (f". Address {s.get('address')}" if s.get("address") else "")))
                act = (lambda u=url: open_url(u)) if url else \
                    ((lambda a=s.get("address"): copy_text(a)) if s.get("address") else None)
                self.region(cx, cy, cw, ch, tip, act)
            rows = math.ceil(len(g.get("services", [])) / cols)
            y += rows * (ch + 3) + 4
        return y + 4

    def _pools(self, cr, d, x0, x1, y):
        D.label(cr, x0, y, "STORAGE POOLS", "dim")
        y += 20
        nas = d.get("nas") or {}
        pool = nas.get("pool") or {}
        if pool.get("total"):
            frac = pool["used"] / pool["total"]
            D.label(cr, x0, y, "NAS", "phosphor")
            D.label(cr, x0 + 44, y, f"{S.human(pool['used'], digits=1)} / {S.human(pool['total'], digits=1)}", "soft")
            disks = nas.get("disks") or []
            # disk bays as 8 small cells at the right
            bx = x1 - len(disks) * 16
            for i, dk in enumerate(disks):
                bad = dk.get("health") != "good" or dk.get("state") != "normal"
                col = "danger" if bad else D.level(dk.get("tempC") or 0, 45, 55)
                D.src(cr, col, 0.9)
                cr.rectangle(bx + i * 16, y + 1, 12, 12)
                cr.fill()
                self.region(bx + i * 16, y, 14, 14, f"NAS bay {dk.get('slot')}: {dk.get('model', '')} "
                            f"{S.human(dk.get('size'))}, {dk.get('health')}, {dk.get('tempC')} °C, "
                            f"{dk.get('hours', 0)} power-on hours")
            D.cells(cr, x0, y + 18, x1 - x0, 7, frac, n=48, warn=0.8, crit=0.9)
            dev = nas.get("device") or {}
            self.region(x0, y, bx - x0 - 6, 28, f"{dev.get('name', 'NAS')}: RAID pool ({pool.get('raidMembers')} disks, "
                        f"{pool.get('health')}) {S.human(pool['used'])} used of {S.human(pool['total'])}")
            y += 34
        rf = store_share(nas)
        if rf:
            where = f"the NAS share {rf['name']}" if rf.get("name") else "the NAS"
            quota = f"quota {S.human(rf['quota'])}" if (rf.get("quota") or 0) > 0 else "no quota"
            D.label(cr, x0, y, "RUSTFS", "phosphor")
            D.label(cr, x0 + 70, y, f"{S.human(rf['usage'], digits=1)} on {where}", "soft")
            st = (d.get("services") or {}).get(OBJECT_STORE, {}).get("status")
            D.dot(cr, x1 - 4, y + 7, 3, "phosphor" if st == "up" else "danger")
            self.region(x0, y, x1 - x0, 16, f"RustFS object store: {S.human(rf['usage'])} used on {where} "
                        f"({quota}); console {st or 'unknown'}. Click to open.",
                        lambda: open_url(self._svc_url(d, OBJECT_STORE)))
            y += 22
        for nd in d.get("nodeDisks") or []:
            frac = nd["pct"] / 100
            D.label(cr, x0, y, nd["node"].replace("k8s-", ""), "static", size=9)
            D.bar(cr, x0 + 110, y + 4, x1 - x0 - 210, 5, frac, D.level(frac, 0.8, 0.9))
            D.label(cr, x1, y, f"{S.human(nd['used'], digits=0)}/{S.human(nd['capacity'], digits=0)}",
                    "soft", size=9, align="right")
            self.region(x0, y, x1 - x0, 15, f"Local disk on node {nd['node']}: {nd['pct']:.0f}% used")
            y += 16


# =================================================================== SWITCHBOARD
