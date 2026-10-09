"""The homelab's desktop panels (bromigos-homelab; docs/homelab.md, "Panels without code").

A panel generator (widgets/plugins.py: a plugin file named *_panels.py names several
panels): names() says which exist right now, panel(name) builds one. They follow
homelab.toml: a panel appears when what it needs is configured and goes when it isn't.

  lab          the LAB panel (_lab.py), when a source provides the lab snapshot (a Lab API,
               or any of metrics/hosts/workloads/deployments/models/alerts to assemble one)
  <declared>   every [[panel]] in homelab.toml and ~/.config/bromigos/homelab/panels/*.toml

A declared panel, no code:

    [[panel]]
    name = "gpu"                    # unique; the widget's name (layout.json "plugins" places it)
    title = "GPU"
    kind = "gauge"                  # gauge | sparkline | stat | status | table
    metric = "avg(DCGM_FI_DEV_GPU_UTIL)"   # a metrics query (the source's language: PromQL)
    unit = "%"
    max = 100                       # gauge: full scale
    warn = 70                       # colours: amber from warn, red from crit (lower = worse:
    crit = 90                       #   set invert = true)
    refresh = 15                    # seconds between samples

Bindings (one per panel):
    metric = "<query>"              gauge, stat: the value; sparkline: range_minutes (60) of it;
                                    table: one row per series (columns = label names + "value")
    url = "https://…"               status: up when it answers (expect = 200), with its time
    capability = "<name>"           hosts | workloads | deployments | models | agents | secrets |
                                    ci | alerts. table: rows (columns = fields, limit); status:
                                    a light per item (ok_field / ok_values); stat: the count
                                    (where = { field = value } filters, for every kind)
For workloads, select = { namespace = "ai", name = "vllm.*", kind = "pod", state = "running" }.
Optional: width, height, x, y, visible, decimals, label, limit, interval.
"""
import os
import sys
import threading
import time
import urllib.error
import urllib.request

_HERE = os.path.dirname(os.path.realpath(__file__))
for _p in (os.path.join(os.path.dirname(_HERE), "lib"),):   # a bromigOS checkout's homelab/lib
    if os.path.isdir(_p) and _p not in sys.path:
        sys.path.insert(1, _p)
sys.path.insert(0, _HERE)                                  # _lab.py beside this file

import bromigos_homelab as H  # noqa: E402

KINDS = ("gauge", "sparkline", "stat", "status", "table")


def _sig():
    st = H.config._sig()
    return hash(st)


def _lab_available():
    return bool(H.snapshot_source())


def names():
    """{panel name: a version that changes when its definition does}."""
    out = {}
    v = _sig()
    if _lab_available():
        out["lab"] = v
    for p in H.config.panels():
        if p.get("kind") in KINDS and p.get("name") and p.get("enabled", True) is not False:
            out[str(p["name"])] = v
    return out


def panel(name):
    """-> (Panel class, LAYOUT) for one of names()."""
    if name == "lab":
        import _lab
        return _lab.LabPanel, {"width": 470, "height": 640}
    spec = next((p for p in H.config.panels() if str(p.get("name")) == name), None)
    if not spec:
        raise LookupError(f"no [[panel]] named {name!r} in homelab.toml")
    layout = {k: spec[k] for k in ("width", "height", "x", "y", "visible") if k in spec}
    layout.setdefault("width", 300 if spec["kind"] in ("gauge", "stat", "status") else 470)
    layout.setdefault("height", {"gauge": 170, "stat": 130, "status": 150, "sparkline": 150}.get(spec["kind"], 230))

    class Declared(DeclaredPanel):
        pass
    Declared.spec = spec
    return Declared, layout


# ------------------------------------------------------------------ declared panels
import draw as D  # noqa: E402
from panels import Panel, open_url  # noqa: E402


def _num(v, decimals=None):
    if v is None:
        return "--"
    if decimals is None and abs(v - round(v)) < 1e-9:
        return str(int(round(v)))
    if decimals is None:
        decimals = 0 if abs(v) >= 100 else 1 if abs(v) >= 10 else 2
    return f"{v:.{int(decimals)}f}"


def _where(items, where):
    if not where:
        return items
    return [x for x in items if all(str(x.get(k)) == str(v) for k, v in where.items())]


class DeclaredPanel(Panel):
    spec = {}
    interval = 1.0

    def __init__(self, cfg=None):
        super().__init__(cfg)
        s = self.spec
        self.name = s["name"]
        self.title = str(s.get("title") or s["name"]).upper()
        self.value, self.series, self.rows, self.lights = None, [], [], []
        self.state, self.error, self.at = "waiting", "", 0
        self.lock = threading.Lock()
        threading.Thread(target=self._loop, daemon=True).start()

    # ---- sampling (off the draw thread)
    def _loop(self):
        while True:
            try:
                self._sample()
            except Exception as e:                       # shown in the panel, never raised
                with self.lock:
                    self.state, self.error = "error", f"{type(e).__name__}: {str(e)[:90]}"
            time.sleep(max(3.0, float(self.spec.get("refresh", 15))))

    def _result(self, res):
        if not res["sources"]:
            raise LookupError("nothing in homelab.toml provides this")
        if not res["ok"]:
            raise OSError("unreachable: " + "; ".join(res["errors"].values())[:120])

    def _sample(self):
        s, kind = self.spec, self.spec["kind"]
        if "metric" in s:
            if kind == "sparkline":
                res = H.metrics_range(s["metric"], int(s.get("range_minutes", 60)), int(s.get("step", 60)))
                self._result(res)
                pts = res["items"][0]["points"] if res["items"] else []
                with self.lock:
                    self.series = [v for _, v in pts]
                    self.value = self.series[-1] if self.series else None
            else:
                res = H.metrics(s["metric"])
                self._result(res)
                with self.lock:
                    vals = [x["value"] for x in res["items"] if x.get("value") is not None]
                    self.value = sum(vals) if vals else None
                    cols = s.get("columns") or ["value"]
                    self.rows = [[(_num(x["value"], s.get("decimals")) if c == "value" else str(x["labels"].get(c, "")))
                                  for c in cols] for x in res["items"][: int(s.get("limit", 12))]]
        elif "url" in s:
            t0 = time.time()
            ok, code = False, None
            try:
                with urllib.request.urlopen(s["url"], timeout=6) as r:
                    code = r.status
            except urllib.error.HTTPError as e:
                code = e.code
            except OSError:
                code = None
            ok = code is not None and (code == int(s.get("expect", 200)) if "expect" in s else 200 <= code < 400)
            with self.lock:
                self.lights = [(s.get("label") or s["name"], ok, f"{(time.time() - t0) * 1000:.0f} ms" if code else "down")]
                self.value = 1.0 if ok else 0.0
        elif "capability" in s:
            cap = s["capability"]
            res = H.workloads(**(s.get("select") or {})) if cap == "workloads" else getattr(H, cap)()
            self._result(res)
            items = _where(res["items"], s.get("where"))
            okf = s.get("ok_field") or {"hosts": "up", "workloads": "state", "deployments": "health", "models": "up",
                                        "agents": "status", "secrets": "sealed", "alerts": "state", "ci": "conclusion"}.get(cap)
            okv = s.get("ok_values") or {"workloads": ["running"], "deployments": ["healthy"], "secrets": [False],
                                         "agents": ["working", "finished"], "alerts": [], "ci": ["success", None]}.get(cap, [True])
            with self.lock:
                self.value = float(len(items))
                cols = s.get("columns") or ["name", okf]
                self.rows = [[str(x.get(c, "")) for c in cols] for x in items[: int(s.get("limit", 12))]]
                self.lights = [(str(x.get("name") or x.get("repo") or x.get("key")), x.get(okf) in okv, str(x.get(okf)))
                               for x in items[: int(s.get("limit", 16))]]
        else:
            raise LookupError("a [[panel]] needs metric, url or capability")
        with self.lock:
            self.state, self.error, self.at = "ok", "", time.time()

    # ---- drawing (the widgets' primitives, themed)
    def _colour(self, v):
        s = self.spec
        if v is None or ("warn" not in s and "crit" not in s):
            return "phosphor"
        warn, crit = float(s.get("warn", float("inf"))), float(s.get("crit", float("inf")))
        if s.get("invert"):
            return D.level(-v, -warn, -crit)
        return D.level(v, warn, crit)

    def draw(self, cr, w, h):
        with self.lock:
            state, err, v = self.state, self.error, self.value
            series, rows, lights = list(self.series), list(self.rows), list(self.lights)
        s, kind = self.spec, self.spec["kind"]
        right = {"ok": "", "waiting": "…", "error": "UNREACHABLE" if "unreachable" in err else "ERROR"}.get(state, "")
        top = D.frame(cr, w, h, self.title, right, "danger" if state == "error" else "static")
        what = s.get("metric") or s.get("url") or s.get("capability")
        self.region(0, 0, w, 34, f"{self.title}: a homelab.toml panel ({kind} of {what}). "
                    + (f"Error: {err}" if err else f"Every {int(float(s.get('refresh', 15)))} s."),
                    (lambda: open_url(s["link"])) if s.get("link") else None)
        x0, x1 = 16, w - 16
        if state == "error":
            D.text(cr, x0, top + 8, err, 11, "danger", width=x1 - x0)
            return
        if state == "waiting":
            D.text(cr, x0, top + 8, "waiting for the first reading", 11, "static")
            return
        unit = str(s.get("unit", ""))
        col = self._colour(v)
        if kind == "gauge":
            mx = float(s.get("max", 100))
            r = min((h - top - 24) / 2, (w - 32) / 4)
            cx, cy = x0 + r + 8, top + 10 + r
            D.ring(cr, cx, cy, r, (v or 0) / mx if mx else 0, 6, col)
            D.text(cr, cx, cy - 9, _num(v, s.get("decimals")) + unit, 16, col, "semibold", align="center")
            D.label(cr, cx + r + 24, cy - 8, s.get("label") or f"OF {_num(mx, 0)}{unit}", "dim")
        elif kind == "stat":
            D.seg7(cr, x0, top + 8, 44, _num(v, s.get("decimals")), col)
            if unit or s.get("label"):
                D.label(cr, x0, h - 22, f"{s.get('label', '')} {unit}".strip(), "dim")
        elif kind == "sparkline":
            D.text(cr, x1, top - 2, _num(v, s.get("decimals")) + unit, 14, col, "semibold", align="right")
            D.spark(cr, x0, top + 22, x1 - x0, h - top - 34, series, col,
                    lo=s.get("min"), hi=s.get("max"))
            D.label(cr, x0, h - 14, f"{int(s.get('range_minutes', 60))} MIN", "dim")
        elif kind in ("status", "table") and not (lights if kind == "status" else rows):
            D.text(cr, x0, top + 8, "nothing reported right now", 11, "static")
        elif kind == "status":
            y = top + 6
            for name, ok, note in lights:
                if y > h - 18:
                    break
                D.dot(cr, x0 + 5, y + 7, 4, "phosphor" if ok else "danger", glow=ok)
                D.text(cr, x0 + 18, y, str(name).upper(), 11, "soft" if ok else "danger", width=x1 - x0 - 110)
                D.label(cr, x1, y + 1, str(note).upper(), "dim", align="right")
                self.region(x0, y, x1 - x0, 16, f"{name}: {'OK' if ok else 'not OK'} ({note})")
                y += 20
        elif kind == "table":
            cols = s.get("columns") or ["value"]
            n = len(cols)
            cw = (x1 - x0) / max(1, n)
            for i, c in enumerate(cols):
                D.label(cr, x0 + i * cw, top + 2, str(c).upper(), "dim")
            y = top + 20
            for row in rows:
                if y > h - 16:
                    break
                for i, cell in enumerate(row):
                    D.text(cr, x0 + i * cw, y, cell, 11, "soft", width=cw - 8)
                y += 18
