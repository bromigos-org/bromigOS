"""Shared plumbing for the lab adapters (labgpu, labobserve, labedge, labstorage, labgames,
labmedia, labai, labci, labbackup): metrics, the kubernetes source, Prometheus's text
format, in-cluster services, time, and the doctor's finding shape.

Each of those adapters reads its service the first way the lab offers:
  * its own endpoint (homelab.toml `endpoint`), over HTTP;
  * the lab's metrics (a prometheus or victoriametrics source), by metric name;
  * the kubernetes source (objects, pod logs), read-only. With `service = "ns/name:port"` and a
    kubeconfig allowed to proxy to services (services/proxy, get), an in-cluster service with
    no ingress answers too.
Nothing here writes: every call is a GET, a list or a log read.
"""
import datetime as dt
import json
import re
import time

from ..registry import Adapter, Unreachable

# ------------------------------------------------------------------ time


def ts(v):
    """Unix seconds from a number, an ISO 8601 string ("…Z" allowed) or None."""
    if v in (None, ""):
        return None
    if isinstance(v, (int, float)):
        return float(v)
    try:
        return dt.datetime.fromisoformat(str(v).replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


def iso(t):
    """"2026-10-09T08:00:00Z" for unix seconds (None stays None)."""
    if t is None:
        return None
    return dt.datetime.fromtimestamp(float(t), dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def hours_since(t, now=None):
    t = ts(t)
    return None if t is None else round(((now or time.time()) - t) / 3600, 2)


def cron_minutes(expr):
    """A cron schedule's interval in minutes, best effort (*/N, hourly, daily, weekly, monthly)."""
    e = (expr or "").strip()
    macros = {"@hourly": 60, "@daily": 1440, "@midnight": 1440, "@weekly": 10080, "@monthly": 43200,
              "@yearly": 525600, "@annually": 525600}
    if e in macros:
        return macros[e]
    f = e.split()
    if len(f) != 5:
        return 1440
    m, h, dom, mon, dow = f
    if m.startswith("*/"):
        return max(1, int(m[2:])) if m[2:].isdigit() else 60
    if m == "*":
        return 1
    if h == "*":
        return 60
    if h.startswith("*/") and h[2:].isdigit():
        return 60 * max(1, int(h[2:]))
    if dom == "*" and mon == "*" and dow == "*":
        return 1440 // max(1, len(h.split(",")))
    if dow != "*" and dom == "*":
        return 10080 // max(1, len(dow.split(",")))
    if dom != "*" and mon == "*":
        return 43200
    return 525600


# ------------------------------------------------------------------ metrics


def have_metrics():
    from .. import caps
    return caps.available("metrics")


def mq(q, timeout=6):
    """A metrics query's [{labels, value}] ([] when nothing matches). Unreachable when the lab has
    no metrics source, or it didn't answer."""
    from .. import caps
    r = caps.metrics(q, timeout=timeout)
    if not r["sources"]:
        raise Unreachable("no metrics source in homelab.toml")
    if not r["ok"]:
        raise Unreachable(next(iter(r["errors"].values()), "the metrics source didn't answer"))
    return r["items"]


def mq_soft(q, timeout=6):
    """mq, or [] when there are no metrics or they didn't answer."""
    try:
        return mq(q, timeout)
    except Exception:
        return []


def keyed(rows, *labels):
    """{label value (or a tuple of them): value} from metric rows."""
    out = {}
    for r in rows:
        lb = r.get("labels") or {}
        k = lb.get(labels[0]) if len(labels) == 1 else tuple(lb.get(x) for x in labels)
        out[k] = r.get("value")
    return out


# ------------------------------------------------------------------ Prometheus's text format
_SAMPLE = re.compile(r'^([a-zA-Z_:][a-zA-Z0-9_:]*)(?:\{(.*)\})?\s+(\S+)')
_LABEL = re.compile(r'([a-zA-Z_][a-zA-Z0-9_]*)="((?:[^"\\]|\\.)*)"')


def _unescape(v):
    return re.sub(r"\\(.)", lambda m: "\n" if m.group(1) == "n" else m.group(1), v) if "\\" in v else v


def parse_prom(text):
    """[{name, labels, value}] from a /metrics page (comments and malformed lines skipped)."""
    if isinstance(text, bytes):
        text = text.decode("utf-8", "replace")
    out = []
    for line in text.splitlines():
        if not line or line[0] == "#":
            continue
        m = _SAMPLE.match(line)
        if not m:
            continue
        try:
            v = float(m.group(3))
        except ValueError:
            continue
        labels = {k: _unescape(val) for k, val in _LABEL.findall(m.group(2) or "")}
        out.append({"name": m.group(1), "labels": labels, "value": v})
    return out


def rows_of(samples, name):
    """The rows of one metric in parse_prom's output, shaped like a metrics query's."""
    return [{"labels": s["labels"], "value": s["value"]} for s in samples if s["name"] == name]


# ------------------------------------------------------------------ the kubernetes source


def kube():
    """The first configured kubernetes source, or None."""
    from .kube import _kube_source
    return _kube_source()


def kube_json(args, timeout=25):
    k = kube()
    if not k:
        raise Unreachable("no kubernetes source in homelab.toml")
    return json.loads(k.kubectl(list(args) + ["-o", "json"], timeout=timeout) or "{}")


def pods(namespace=None, selector=None, timeout=25):
    """Raw pod objects in a namespace (all when None), optionally by a label selector."""
    args = ["get", "pods"] + (["-n", namespace] if namespace else ["-A"]) + (["-l", selector] if selector else [])
    return kube_json(args, timeout).get("items", [])


def pod_ready(p):
    st = p.get("status") or {}
    if st.get("phase") != "Running":
        return False
    return all(c.get("ready") for c in st.get("containerStatuses") or []) and bool(st.get("containerStatuses"))


def pod_restarts(p):
    return sum(int(c.get("restartCount") or 0) for c in (p.get("status") or {}).get("containerStatuses") or [])


def pod_waiting(p):
    """A container's waiting reason (CrashLoopBackOff, ImagePullBackOff, …), or ""."""
    for c in (p.get("status") or {}).get("containerStatuses") or []:
        w = (c.get("state") or {}).get("waiting") or {}
        if w.get("reason"):
            return w["reason"]
    return ""


def pod_logs(namespace, pod, tail=200, since=None, container=None, timeout=20):
    k = kube()
    if not k:
        raise Unreachable("no kubernetes source in homelab.toml")
    args = ["logs", "-n", namespace, pod, f"--tail={int(tail)}"] + ([f"--since={since}"] if since else []) + \
        (["-c", container] if container else [])
    return k.kubectl(args, timeout=timeout)


def service_get(namespace, name, port, path, timeout=10):
    """GET an in-cluster service's path through the API server's service proxy (bytes)."""
    k = kube()
    if not k:
        raise Unreachable("no kubernetes source to reach the in-cluster service through")
    raw = f"/api/v1/namespaces/{namespace}/services/{name}:{port}/proxy{path if path.startswith('/') else '/' + path}"
    try:
        return k.kubectl(["get", "--raw", raw], timeout=timeout).encode()
    except RuntimeError as e:
        msg = str(e)
        if "forbidden" in msg.lower():
            raise Unreachable(f"{name}: the kubernetes source may not proxy to services (services/proxy); "
                              "give this source an endpoint instead") from None
        raise


def parse_service(s):
    """"ns/name:port" -> (ns, name, port), else None."""
    m = re.match(r"^([a-z0-9-]+)/([a-z0-9.-]+):(\d+)$", str(s or "").strip())
    return (m.group(1), m.group(2), m.group(3)) if m else None


# ------------------------------------------------------------------ doctor findings (doctor.py's shape)
STATUSES = ("ok", "warn", "fail", "skip")


def finding(id, title, status, detail="", fix="", source=None, check=None):
    """A doctor finding: {"id", "check", "title", "status": ok|warn|fail|skip, "detail", "fix", "source"}."""
    try:
        from .. import doctor
        return doctor.finding(id, title, status, detail, fix, source=source, check=check)
    except ImportError:
        if status not in STATUSES:
            raise ValueError(f"finding {id}: status must be one of {STATUSES}") from None
        f = {"id": id, "check": check or id.split(".", 1)[0], "title": title, "status": status,
             "detail": detail or "", "fix": "" if status == "ok" else (fix or "")}
        if source:
            f["source"] = source
        return f


def level(value, warn, crit, invert=False):
    """"ok" | "warn" | "crit" for a value against thresholds (invert: low is bad)."""
    if value is None:
        return "unknown"
    if invert:
        return "crit" if value <= crit else "warn" if value <= warn else "ok"
    return "crit" if value >= crit else "warn" if value >= warn else "ok"


# ------------------------------------------------------------------ detection (bromigos setup homelab)


class Discovery:
    """What `bromigos setup homelab` found, for the lab adapters' detect(d) classmethods: a
    metrics source and a kubernetes source (adapter instances; either may be None). Every
    method answers soft: empty when the source is missing or doesn't answer."""

    def __init__(self, metrics=None, kube=None):
        self.metrics, self.kube = metrics, kube
        self._cache = {}

    def rows(self, q):
        if not self.metrics:
            return []
        if q not in self._cache:
            try:
                self._cache[q] = self.metrics.metrics_query(q, timeout=8)
            except Exception:
                self._cache[q] = []
        return self._cache[q]

    def has_metric(self, name):
        return any((r.get("value") or 0) > 0 for r in self.rows(f"count({name})"))

    def jobs(self):
        """Prometheus scrape job names."""
        return {r["labels"].get("job") for r in self.rows("count by (job)(up)") if r["labels"].get("job")}

    def objects(self, kind, namespace=None, selector=None):
        if not self.kube:
            return []
        key = ("k", kind, namespace, selector)
        if key not in self._cache:
            args = ["get", kind] + (["-n", namespace] if namespace else ["-A"]) + (["-l", selector] if selector else [])
            try:
                self._cache[key] = json.loads(self.kube.kubectl(args + ["-o", "json"], timeout=20)).get("items", [])
            except Exception:
                self._cache[key] = []
        return self._cache[key]

    def pods(self, selector=None, namespace=None):
        return self.objects("pods", namespace, selector)

    def namespaces(self):
        return {p["metadata"].get("namespace") for p in self.pods()}


# ------------------------------------------------------------------ the base adapter


class LabAdapter(Adapter):
    """An adapter that can work with no endpoint (through metrics or the kubernetes source)."""
    local = True

    def configured(self):
        return True

    def opt(self, key, default=None):
        v = self.opts.get(key)
        return default if v in (None, "") else v

    def service(self):
        return parse_service(self.opts.get("service"))

    def has_web(self):
        return bool(self.endpoint or self.service())

    def fetch(self, path, timeout=8, raw=False, headers=None):
        """GET path from the endpoint, else the in-cluster service; JSON unless raw."""
        if self.endpoint:
            return self.request(path, timeout=timeout, raw=raw, headers=headers)
        s = self.service()
        if not s:
            raise Unreachable(f"{self.name}: no endpoint (or service = \"namespace/name:port\") in homelab.toml")
        b = service_get(*s, path, timeout=timeout)
        return b if raw else json.loads(b or b"null")

    def finding(self, id, title, status, detail="", fix="", check=None):
        return finding(id, title, status, detail, fix, source=self.name, check=check or id.split(".", 1)[0])


def gpu_use(namespace):
    """(VRAM used in bytes, "RTX 5090 on gpu-node") of the GPUs DCGM attributes to a namespace's
    pods, or (None, ""). A time-sliced GPU's memory is the whole card's, shared."""
    if not namespace or not have_metrics():
        return None, ""
    rows = mq_soft(f'DCGM_FI_DEV_FB_USED{{exported_namespace="{namespace}"}}') or \
        mq_soft(f'DCGM_FI_DEV_GPU_UTIL{{exported_namespace="{namespace}"}}')
    used, where, seen = None, [], set()
    for r in rows:
        lb = r["labels"]
        key = lb.get("UUID") or (lb.get("Hostname") or lb.get("hostname"), lb.get("gpu"))
        if key in seen:
            continue
        seen.add(key)
        if "FB_USED" in (lb.get("__name__") or "DCGM_FI_DEV_FB_USED") and r.get("value") is not None:
            used = (used or 0) + r["value"] * 1024 ** 2
        where.append(f"{(lb.get('modelName') or 'GPU').replace('NVIDIA ', '')} on "
                     f"{lb.get('Hostname') or lb.get('hostname') or '?'}")
    return used, ", ".join(where)


class AppAdapter(LabAdapter):
    """An app the lab runs (capability apps): whether it answers and its version, from its endpoint
    (or in-cluster service), else its pods through the kubernetes source (`namespace`,
    `selector`); the GPU memory DCGM attributes to its namespace. A subclass sets kind,
    health_path, pod_selector, and may override check() / version()."""
    provides = ("apps",)
    kind = "app"
    health_path = "/health"
    pod_selector = None
    default_namespace = None
    own_namespace = True        # every pod in its `namespace` is its (False: a shared one, by selector)

    def check(self):
        """(up, detail) from the endpoint; an HTTP error or no answer raises."""
        self.fetch(self.health_path, raw=True, timeout=5)
        return True, ""

    def version(self):
        return None

    def link(self):
        return self.opts.get("link") or self.endpoint or None

    def namespace(self):
        return self.opt("namespace", self.default_namespace)

    def _selectors(self):
        """The label selectors to find its pods by: the source's `selector`, else (with no
        `namespace`) the class's defaults, tried in turn (charts label app= or app.kubernetes.io/name=)."""
        if self.opts.get("selector"):
            return [self.opts["selector"]]
        if self.namespace() and self.own_namespace:
            return [None]
        sel = self.pod_selector
        if not sel:
            return []
        return [sel, sel.replace("app.kubernetes.io/name=", "app=")] if "app.kubernetes.io/name=" in sel else [sel]

    def pod_state(self):
        """(up, detail, deployed) from the app's pods (Job pods left out), or None without a
        kubernetes source or a namespace / selector to find them by."""
        ns, sels = self.namespace(), self._selectors()
        if not sels or not kube():
            return None
        ps = []
        for sel in sels:
            ps = [p for p in pods(ns, sel) if (p.get("status") or {}).get("phase") != "Succeeded"
                  and not any(o.get("kind") == "Job" for o in p["metadata"].get("ownerReferences") or [])]
            if ps:
                break
        if not ps:
            return False, "not deployed: no pods" + (f" in {ns}" if ns else ""), False
        ready = sum(1 for p in ps if pod_ready(p))
        waiting = next((pod_waiting(p) for p in ps if pod_waiting(p)), "")
        restarts = sum(pod_restarts(p) for p in ps)
        bits = [f"{ready}/{len(ps)} pods ready", waiting, f"{restarts} restarts" if restarts else ""]
        return ready == len(ps), " · ".join(b for b in bits if b), True

    def apps(self):
        rec = {"name": self.name, "kind": self.kind, "up": None, "version": None, "detail": "",
               "endpoint": self.endpoint or None, "vram_used": None, "link": self.link()}
        why = ""
        if self.has_web():
            try:
                rec["up"], rec["detail"] = self.check()
                try:
                    rec["version"] = self.version()
                except Exception:
                    pass
            except Exception as e:
                code = getattr(e, "code", None)
                why = f"HTTP {code}" if code else ("unreachable: " + str(e).split(": ", 1)[-1][:120])
                rec["up"], rec["detail"] = False, why
        try:
            k = self.pod_state()
        except Exception as e:
            k = None
            if rec["up"] is None:
                raise Unreachable(f"{self.name}: {str(e)[:160]}") from None
        if k is not None:
            up, detail, deployed = k
            if rec["up"] is None:                   # check() couldn't tell (or there is no endpoint)
                rec["up"] = up
            rec["detail"] = " · ".join(b for b in (rec["detail"], detail) if b)
            if not deployed:                         # not deployed is not down: nothing there to run
                rec["up"], rec["state"] = None, "not deployed"
        elif not self.has_web():
            raise Unreachable(f"{self.name}: no endpoint, service or namespace to check it by")
        used, where = gpu_use(self.namespace())
        if where:
            rec["vram_used"] = used
            rec["detail"] = " · ".join(b for b in (rec["detail"], f"GPU: {where}") if b)
        return [rec]

    def doctor(self):
        rec = self.apps()[0]
        if rec.get("state") == "not deployed":
            return [self.finding(f"apps.{self.name}", f"{self.name} ({self.kind})", "skip", rec["detail"])]
        if rec["up"]:
            return [self.finding(f"apps.{self.name}", f"{self.name} ({self.kind})", "ok",
                                 " · ".join(b for b in (rec.get("version"), rec["detail"]) if b) or "answers")]
        return [self.finding(f"apps.{self.name}", f"{self.name} ({self.kind})", "fail", rec["detail"] or "down",
                             f"{self.name} doesn't answer. Look at its pods' events and logs (bromigos lab logs "
                             f"{self.namespace() or self.name}); if it was moved, fix its source in homelab.toml.")]
