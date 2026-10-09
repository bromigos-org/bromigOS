"""The lab snapshot: one dict the desktop's richer views read (the LAB panel, the live
layer's gadgets, timeline and drift map, the worlds' health, VECTOR's lab_status).

A source that provides "snapshot" (type = "lab": a Lab API, a homelab's own status
service) is used as it comes. Otherwise the snapshot is assembled from the
capabilities: whatever the homelab provides fills its part, the rest is absent.

  generatedAt  unix seconds
  cluster      nodesReady, nodesTotal, podsRunning, podsNotRunning, deploymentsShort,
               alertsFiring, cpuNow (%), cpuSeries [[t, v], …]
  nodes        [{name, cpuPct, memPct, load1, cores}]
  gpu          count, utilNow (%), utilSeries, vramUsed, vramTotal (bytes), tempC, powerW
  ai           rpmNow, rpmSeries, failedPerHour, models [{name, up, model}]
  argocd       healthy, total                      (any deployments provider)
  traefik      rpsNow, rpsSeries
  services     {name: {status: "up"|"down"}}       (the drift map's relays, the beacon)
  errors       {source: "unreachable: …"}           (assembled snapshots only)
"""
import time

from . import caps, config, registry


def source():
    """"lab" (a snapshot provider) | "assembled" | "" (nothing to show)."""
    if registry.providers("snapshot"):
        return "lab"
    if any(caps.available(c) for c in ("metrics", "hosts", "workloads", "deployments", "models", "alerts")):
        return "assembled"
    return ""


def snapshot(timeout=8):
    """The snapshot, or None when the homelab provides nothing. A Lab API that's down raises
    registry.Unreachable (callers show "unreachable")."""
    labs = registry.providers("snapshot")
    if labs:
        return labs[0].snapshot()
    if not source():
        return None
    return assemble()


def assemble():
    t0 = time.time()
    snap = {"generatedAt": int(t0), "source": "assembled", "errors": {}}
    m = caps.available("metrics")
    q = caps.scalar
    cluster = {}
    if m:
        cpu = '100*(1-avg(rate(node_cpu_seconds_total{mode="idle"}[5m])))'
        cluster = {
            "nodesReady": q('sum(kube_node_status_condition{condition="Ready",status="true"})'),
            "nodesTotal": q("count(kube_node_info)"),
            "podsRunning": q('sum(kube_pod_status_phase{phase="Running"})'),
            "podsNotRunning": q('sum(kube_pod_status_phase{phase=~"Pending|Failed|Unknown"})'),
            "deploymentsShort": q("count(kube_deployment_status_replicas_available < kube_deployment_spec_replicas)", 0.0),
            "cpuNow": q(cpu),
            "cpuSeries": caps.series(cpu, 60, 60),
        }
    if cluster.get("nodesTotal") is None:                 # no kube-state-metrics: count what the sources list
        h = caps.hosts()
        snap["errors"].update(h["errors"])
        if h["items"]:
            cluster["nodesTotal"] = float(len(h["items"]))
            cluster["nodesReady"] = float(sum(1 for x in h["items"] if x.get("up")))
    if cluster.get("podsRunning") is None and caps.available("workloads"):
        w = caps.workloads()
        snap["errors"].update(w["errors"])
        if w["items"]:
            cluster["podsRunning"] = float(sum(1 for x in w["items"] if x["state"] == "running"))
            cluster["podsNotRunning"] = float(sum(1 for x in w["items"] if x["state"] in ("pending", "failed", "unknown")))
    a = caps.alerts()
    snap["errors"].update(a["errors"])
    if a["ok"]:
        cluster["alertsFiring"] = float(sum(1 for x in a["items"] if x["state"] == "firing"))
    snap["cluster"] = {k: v for k, v in cluster.items() if v is not None}
    h = caps.hosts()
    snap["nodes"] = sorted(({"name": x["name"], "cpuPct": x.get("cpu_pct"), "memPct": x.get("mem_pct"),
                             "load1": x.get("load1"), "cores": x.get("cores")} for x in _merge_hosts(h["items"])),
                           key=lambda n: str(n["name"]))
    if m:
        gpus = q("count(DCGM_FI_DEV_GPU_UTIL)")
        if gpus:
            used, free = q("sum(DCGM_FI_DEV_FB_USED)"), q("sum(DCGM_FI_DEV_FB_FREE)")
            snap["gpu"] = {"count": int(gpus), "utilNow": q("avg(DCGM_FI_DEV_GPU_UTIL)"),
                           "utilSeries": caps.series("avg(DCGM_FI_DEV_GPU_UTIL)", 60, 60),
                           "vramUsed": used * 2**20 if used is not None else None,          # DCGM reports MiB
                           "vramTotal": (used + free) * 2**20 if used is not None and free is not None else None,
                           "tempC": q("max(DCGM_FI_DEV_GPU_TEMP)"), "powerW": q("sum(DCGM_FI_DEV_POWER_USAGE)")}
        rps = q("sum(rate(traefik_entrypoint_requests_total[1m]))")
        if rps is not None:
            snap["traefik"] = {"rpsNow": rps, "rpsSeries": caps.series("sum(rate(traefik_entrypoint_requests_total[1m]))", 60, 60)}
    mo = caps.models()
    snap["errors"].update(mo["errors"])
    if mo["ok"]:
        rpm = sum(x.get("requests_per_min") or 0.0 for x in mo["items"])
        snap["ai"] = {"rpmNow": rpm, "models": [{"name": x["name"], "up": x.get("up"), "model": x.get("model")}
                                                for x in mo["items"]]}
        if m:
            snap["ai"]["rpmSeries"] = caps.series("sum(rate(litellm_deployment_total_requests_total[1m]))*60", 60, 60)
            snap["ai"]["failedPerHour"] = q("sum(increase(litellm_deployment_failure_responses_total[1h]))", 0.0)
    d = caps.deployments()
    snap["errors"].update(d["errors"])
    if d["ok"]:
        snap["argocd"] = {"healthy": sum(1 for x in d["items"] if x["health"] == "healthy"), "total": len(d["items"])}
    snap["services"] = services()
    return snap


def _merge_hosts(items):
    """The same host from two sources (node-exporter and the kubelet): one record, the fuller one's
    numbers first."""
    by = {}
    for x in items:
        k = str(x.get("name"))
        cur = by.get(k)
        if not cur:
            by[k] = dict(x)
            continue
        for f, v in x.items():
            if cur.get(f) is None and v is not None:
                cur[f] = v
        cur["up"] = bool(cur.get("up")) and bool(x.get("up", True))
    return list(by.values())


def services():
    """{name: {status}}: blackbox probes when the metrics have them, else scrape targets by
    job. [services] include / exclude narrow it."""
    if not caps.available("metrics"):
        return {}
    inc = set(config.setting("services", "include", []) or ())
    exc = set(config.setting("services", "exclude", []) or ())
    out = {}
    probes = caps.metrics("probe_success")["items"]
    if probes:
        for r in probes:
            name = r["labels"].get("job") or r["labels"].get("instance")
            up = (r["value"] or 0) > 0
            out[name] = {"status": "up" if up and out.get(name, {}).get("status", "up") == "up" else "down"}
    else:
        for r in caps.metrics("min by (job)(up)")["items"]:
            name = r["labels"].get("job")
            if name:
                out[name] = {"status": "up" if (r["value"] or 0) > 0 else "down"}
    if inc:
        out = {k: v for k, v in out.items() if k in inc}
    return {k: v for k, v in sorted(out.items()) if k not in exc}
