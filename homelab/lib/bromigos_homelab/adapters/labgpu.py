"""GPUs: NVIDIA's DCGM exporter (the GPU operator's nvidia-dcgm-exporter, or a standalone one).
Capability: gpus.

    [[source]]
    type = "dcgm"                       # through the metrics source (its DCGM_FI_* series)
    # endpoint = "http://gpu-box:9400"  # or the exporter itself (/metrics): no Prometheus needed
    # warn_temp = 83                    # the doctor's temperatures, °C (crit_temp = 90)

Per GPU: its model, host, VRAM used and total (bytes; none on unified-memory boards, whose
GPU memory is the system's), utilisation, temperature, power, and what holds it: the pod
DCGM names for it, plus every running pod that asks its node for a GPU when the node has one
(a time-sliced GPU is shared by all of them).
"""
import re

from ..registry import register
from . import labcommon as L

FIELDS = {"DCGM_FI_DEV_GPU_UTIL": "util_pct", "DCGM_FI_DEV_FB_USED": "fb_used", "DCGM_FI_DEV_FB_FREE": "fb_free",
          "DCGM_FI_DEV_FB_RESERVED": "fb_reserved", "DCGM_FI_DEV_GPU_TEMP": "temp_c",
          "DCGM_FI_DEV_POWER_USAGE": "power_w", "DCGM_FI_DEV_POWER_MGMT_LIMIT": "power_limit_w",
          "DCGM_FI_DEV_XID_ERRORS": "xid"}
MIB = 1024 ** 2


def short_pod(pod):
    """web-7d9f8c6b5d-x2x9q -> web (a Deployment's or a StatefulSet's pod name, its hashes off)."""
    return re.sub(r"(-[a-z0-9]{8,10})?-[a-z0-9]{5}$", "", pod or "")


def _host(lb):
    return lb.get("Hostname") or lb.get("hostname") or lb.get("node") or lb.get("instance") or "?"


def _user(lb):
    """(namespace, pod) of the workload using the GPU, from DCGM's pod attribution."""
    if lb.get("exported_pod"):
        return lb.get("exported_namespace"), lb["exported_pod"]
    pod = lb.get("pod") or lb.get("pod_name")
    if pod and "dcgm" not in pod:              # read from the exporter itself: these are the user's
        return lb.get("namespace") or lb.get("pod_namespace"), pod
    return None, None


def gpus_from(rows, gpu_pods=None):
    """GPU records from DCGM rows ({metric: [{labels, value}]}) and {node: ["ns/pod", …]} of the
    running pods that ask for a GPU."""
    out = {}
    for metric, field in FIELDS.items():
        for r in rows.get(metric) or []:
            lb = r.get("labels") or {}
            host = _host(lb)
            key = lb.get("UUID") or f"{host}:{lb.get('gpu', '0')}"
            model = lb.get("modelName") or "GPU"
            g = out.setdefault(key, {"name": re.sub(r"^NVIDIA\s+|GeForce\s+", "", model).replace("GeForce ", ""),
                                     "host": host, "model": model, "uuid": lb.get("UUID"), "index": lb.get("gpu"),
                                     "driver": lb.get("DCGM_FI_DRIVER_VERSION"), "holds": []})
            g[field] = r.get("value")
            ns, pod = _user(lb)
            if pod:
                tag = f"{ns}/{short_pod(pod)}" if ns else short_pod(pod)
                if tag not in g["holds"]:
                    g["holds"].append(tag)
    per_host = {}
    for g in out.values():
        per_host[g["host"]] = per_host.get(g["host"], 0) + 1
    for g in out.values():
        if per_host[g["host"]] == 1:            # one GPU on the node: every GPU pod there shares it
            for tag in (gpu_pods or {}).get(g["host"], []):
                if tag not in g["holds"]:
                    g["holds"].append(tag)
        used, free, res = g.pop("fb_used", None), g.pop("fb_free", None), g.pop("fb_reserved", None)
        g["vram_used"] = used * MIB if used is not None else None
        g["vram_total"] = (used + free + (res or 0)) * MIB if used is not None and free is not None else None
        g["holds"].sort()
    return sorted(out.values(), key=lambda g: (g["host"], str(g.get("index"))))


def gpu_pods_from_limits(rows):
    """{node: ["ns/pod", …]} from kube_pod_container_resource_limits rows (nvidia GPUs)."""
    out = {}
    for r in rows:
        lb = r.get("labels") or {}
        if not lb.get("node") or (r.get("value") or 0) <= 0:
            continue
        tag = f"{lb.get('namespace')}/{short_pod(lb.get('pod'))}"
        if tag not in out.setdefault(lb["node"], []):
            out[lb["node"]].append(tag)
    return out


def gpu_pods_from_kube(items):
    out = {}
    for p in items:
        if (p.get("status") or {}).get("phase") != "Running":
            continue
        asks = any(k.startswith("nvidia.com/gpu") for c in (p.get("spec") or {}).get("containers") or []
                   for k in ((c.get("resources") or {}).get("limits") or {}))
        node = (p.get("spec") or {}).get("nodeName")
        if asks and node:
            tag = f"{p['metadata'].get('namespace')}/{short_pod(p['metadata']['name'])}"
            if tag not in out.setdefault(node, []):
                out[node].append(tag)
    return out


def gpu_findings(gpus, warn_temp=83, crit_temp=90, source=None):
    """Doctor findings for GPU records: hot, VRAM full, XID errors; one ok line when all is well."""
    out = []
    for g in gpus:
        gid = f"gpus.{g['host']}.{g.get('index') or 0}"
        title = f"{g['name']} on {g['host']}"
        t = g.get("temp_c")
        if t is not None and t >= crit_temp:
            out.append(L.finding(gid + ".temp", title + ": temperature", "fail", f"{t:.0f} °C",
                                 f"It is at {t:.0f} °C. Check its fans and airflow, and what's running on it; "
                                 "a GPU this hot throttles and can shut down.", source))
        elif t is not None and t >= warn_temp:
            out.append(L.finding(gid + ".temp", title + ": temperature", "warn", f"{t:.0f} °C",
                                 f"It is running hot ({t:.0f} °C). Check its airflow and its load.", source))
        used, total = g.get("vram_used"), g.get("vram_total")
        if used is not None and total and used / total >= 0.97:
            out.append(L.finding(gid + ".vram", title + ": VRAM", "warn",
                                 f"{used / 2**30:.1f} of {total / 2**30:.1f} GiB used ({', '.join(g['holds']) or '?'})",
                                 "Its memory is nearly full: the next model load fails. Unload what's idle "
                                 "(bromigos lab models) or move a workload to another GPU.", source))
        if g.get("xid"):
            out.append(L.finding(gid + ".xid", title + ": driver errors", "warn", f"XID error {g['xid']:.0f}",
                                 "The driver reported an XID error: look it up in NVIDIA's XID list; repeated "
                                 "ones usually mean a driver/library mismatch or a failing card.", source))
    if gpus and not out:
        hot = max((g.get("temp_c") or 0) for g in gpus)
        out.append(L.finding("gpus.all", "GPUs", "ok", f"{len(gpus)} GPU(s), hottest {hot:.0f} °C", source=source))
    return out


@register
class DCGM(L.LabAdapter):
    type = "dcgm"
    provides = ("gpus",)
    default_ports = (9400,)

    def probe(self):
        return b"DCGM_FI_DEV_GPU_UTIL" in self.request("/metrics", timeout=3, raw=True)

    @classmethod
    def detect(cls, d):
        return [{"type": "dcgm"}] if d.has_metric("DCGM_FI_DEV_GPU_UTIL") else []

    def _rows(self):
        if self.has_web():
            samples = L.parse_prom(self.fetch("/metrics", raw=True))
            return {m: L.rows_of(samples, m) for m in FIELDS}
        out = {"DCGM_FI_DEV_GPU_UTIL": L.mq("DCGM_FI_DEV_GPU_UTIL")}
        for m in FIELDS:
            if m not in out:
                out[m] = L.mq_soft(m)
        return out

    def _gpu_pods(self):
        rows = L.mq_soft('kube_pod_container_resource_limits{resource=~"nvidia_com_gpu.*"} '
                         '* on (namespace, pod) group_left() (kube_pod_status_phase{phase="Running"} == 1)')
        if rows:
            return gpu_pods_from_limits(rows)
        if L.kube():
            try:
                return gpu_pods_from_kube(L.pods())
            except Exception:
                return {}
        return {}

    def gpus(self):
        out = gpus_from(self._rows(), self._gpu_pods())
        for g in out:
            t, used, total = g.get("temp_c"), g.get("vram_used"), g.get("vram_total")
            frac = used / total if used is not None and total else 0
            g["state"] = L.level(t, self.opt("warn_temp", 83), self.opt("crit_temp", 90)) if t is not None else "ok"
            if frac >= 0.97 and g["state"] == "ok":
                g["state"] = "warn"
        return out

    def doctor(self):
        return gpu_findings(self.gpus(), self.opt("warn_temp", 83), self.opt("crit_temp", 90), self.name)
