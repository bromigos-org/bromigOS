"""bromigOS's own console cards (console.py has the card format and how to add one).

Orders: 10 nodes, 20 gpus, 30 services, 40 models, 50 deployments, 55 workloads, 60 storage,
70 alerts, 80 jobs, 90 secrets; every other capability a generic card at 100+.
"""
import os

from . import caps, config, registry
from .console import _visible, hidden, register_card, worst

GIB = 1024 ** 3


def _pct(v):
    return None if v is None else round(float(v), 1)


def _fmt_gib(b):
    return None if b is None else f"{b / GIB:.1f}"


# ------------------------------------------------------------------ nodes
def _node_state(r):
    if r.get("up") is False:
        return "crit"
    d = r.get("disk_pct") or 0
    m = r.get("mem_pct") or 0
    if d >= 95:
        return "crit"
    if d >= 85 or m >= 95:
        return "warn"
    return "ok"


def _nodes(res):
    from .snapshot import _merge_hosts
    pats = hidden()
    items = []
    for x in _merge_hosts(res["items"]):
        if not _visible(x, pats):
            continue
        it = {k: x.get(k) for k in ("name", "up", "cpu_pct", "mem_pct", "disk_pct", "load1", "cores")}
        it["cpu_pct"], it["mem_pct"], it["disk_pct"] = (_pct(it["cpu_pct"]), _pct(it["mem_pct"]), _pct(it["disk_pct"]))
        it["state"] = _node_state(x)
        bits = [f"CPU {it['cpu_pct']:.0f}%" if it["cpu_pct"] is not None else None,
                f"memory {it['mem_pct']:.0f}%" if it["mem_pct"] is not None else None,
                f"root disk {it['disk_pct']:.0f}%" if it["disk_pct"] is not None else None]
        it["hint"] = f"{it['name']}: " + (", ".join(b for b in bits if b) or "up") + \
            (" · DOWN: it doesn't answer" if x.get("up") is False else "")
        items.append(it)
    items.sort(key=lambda i: str(i["name"]))
    up = sum(1 for i in items if i["up"] is not False)
    busiest = max((i for i in items if i["cpu_pct"] is not None), key=lambda i: i["cpu_pct"], default=None)
    s = f"{up} of {len(items)} up" + (f" · busiest {busiest['name']} {busiest['cpu_pct']:.0f}% CPU" if busiest else "")
    return {"columns": ["name", "up", "cpu_pct", "mem_pct", "disk_pct", "load1", "cores"], "items": items, "summary": s}


register_card("nodes", title="Nodes", order=10, capability="hosts", needs=("hosts",), covers=("hosts",),
              hint="Every machine the lab's sources know (cluster nodes, Proxmox hosts, monitored boxes): up, "
                   "CPU, memory, root disk, load. Red: down or a disk nearly full.", build=_nodes)


# ------------------------------------------------------------------ GPUs
def _gpus(_res):
    from .labmodels import gpus
    items = []
    for g in gpus():
        used, total = g.get("vram_used"), g.get("vram_total")
        util = g.get("util_pct")
        uni = g.get("unified")
        it = {"name": g.get("name"), "host": g.get("host"),
              "vram": (f"{_fmt_gib(used)} / {_fmt_gib(total)} GiB" + (" unified" if uni else "")) if total else
              "unified memory",
              "vram_used": used, "vram_total": total, "util_pct": _pct(util), "temp_c": _pct(g.get("temp_c")),
              "power_w": _pct(g.get("power_w")), "holds": ", ".join(g.get("holds") or []) or "-",
              "unified": bool(uni), "group": g.get("group")}
        if g.get("group"):
            it["holds"] += f" ({g['group']}, tensor parallel)"
        t = g.get("temp_c") or 0
        frac = (used / total) if used is not None and total else 0
        it["state"] = "crit" if t >= 88 else "warn" if t >= 80 or (frac >= 0.97 and not uni) else "ok"
        it["busy"] = (util or 0) >= 30
        it["hint"] = (f"{it['name']} on {it['host']}: {it['vram']} " + ("(memory shared with the node: CPU and GPU "
                      "use the same pool)" if uni else "VRAM") + f", {it['util_pct'] or 0:.0f}% busy, "
                      f"{it['temp_c'] or 0:.0f} °C, {it['power_w'] or 0:.0f} W. Holds: {it['holds']}")
        items.append(it)
    if not items:
        return None
    busy = sum(1 for i in items if i["busy"])
    big = max((i for i in items if i["vram_total"] and not i["unified"]), key=lambda i: i["vram_total"], default=None)
    s = f"{len(items)} GPU{'s' if len(items) != 1 else ''} · {busy} busy"
    if big:
        s += f" · {big['vram']} on the {big['name']}"
    return {"columns": ["name", "host", "vram", "util_pct", "temp_c", "power_w", "holds"], "items": items, "summary": s}


register_card("gpus", title="GPUs", order=20, capability=None, needs=("metrics", "media", "gpus"), covers=("gpus",),
              hint="Each GPU: VRAM used of total, how busy, temperature, power, and what holds it (the pods or "
                   "servers using it). From NVIDIA's DCGM exporter, else the media server's own device.",
              build=_gpus)


# ------------------------------------------------------------------ services (AI and media servers)
def _services(_res):
    items, errs = [], {}
    m = caps.media()
    errs.update(m["errors"])
    for x in m["items"]:
        q = (x.get("running") or 0, x.get("pending") or 0)
        free = x.get("vram_free")
        items.append({"name": x["source"], "kind": "ComfyUI", "up": True, "state": "ok",
                      "detail": f"{'busy' if q[0] else 'idle'} · queue {q[1]} · "
                                f"{_fmt_gib(free) or '?'} GiB VRAM free · {x.get('version') or ''}".strip(" ·"),
                      "hint": "Image, edit, cutout and 3D jobs run here (bromigos lab run, bromigos art make)"})
    v = caps.voice()
    errs.update(v["errors"])
    for x in v["items"]:
        ok = bool(x.get("up")) and bool(x.get("tts")) and bool(x.get("stt"))
        items.append({"name": x["source"], "kind": "voice", "up": bool(x.get("up")),
                      "state": "ok" if ok else "warn" if x.get("up") else "crit",
                      "detail": f"TTS {'on' if x.get('tts') else 'OFF'} ({(x.get('tts_model') or '?').split('/')[-1]}) · "
                                f"STT {'on' if x.get('stt') else 'OFF'} ({x.get('stt_model') or '?'})",
                      "hint": "The lab's voice service: VECTOR speaks and listens through it; voice and transcribe "
                              "jobs use it. The console never stops or crowds it."})
    mo = caps.models()
    errs.update(mo["errors"])
    by = {}
    for x in mo["items"]:
        by.setdefault(x["source"], []).append(x)
    kinds = {a.name: a.type for a in registry.instances()}
    for src, ms in by.items():
        up = sum(1 for x in ms if x.get("up"))
        rpm = sum(x.get("requests_per_min") or 0 for x in ms)
        items.append({"name": src, "kind": {"litellm": "LiteLLM", "ollama": "Ollama", "openai": "vLLM"}.get(
            kinds.get(src), kinds.get(src) or "models"), "up": up > 0,
            "state": "ok" if up == len(ms) else "warn" if up else "crit",
            "detail": f"{up} of {len(ms)} models up" + (f" · {rpm:.0f} req/min" if rpm else ""),
            "hint": "A model server; bromigos lab models lists what it serves"})
    for src in mo["sources"]:
        if src not in by and src not in mo["errors"]:
            items.append({"name": src, "kind": {"litellm": "LiteLLM", "ollama": "Ollama", "openai": "vLLM"}.get(
                kinds.get(src), kinds.get(src) or "models"), "up": True, "state": "ok",
                "detail": "answers; lists no models (give it an auth_ref to read /v1/models)",
                "hint": "A model server that answers but didn't list its models"})
    for src, e in errs.items():
        items.append({"name": src, "kind": kinds.get(src, "?"), "up": False, "state": "crit",
                      "detail": e, "hint": f"{src} didn't answer: {e}"})
    if not items:
        return None
    bad = [i["name"] for i in items if i["state"] != "ok"]
    s = f"{len(items) - len(bad)} of {len(items)} healthy" + (f" · check {', '.join(bad[:3])}" if bad else "")
    return {"columns": ["name", "kind", "up", "detail"], "items": items, "summary": s, "errors": errs}


register_card("services", title="Services", order=30, capability=None, needs=("media", "voice", "models"),
              covers=("media", "voice"),
              hint="The lab's AI and media servers: ComfyUI (images, 3D), the voice service (speech in and out), "
                   "the model servers (LiteLLM, vLLM, Ollama). Each one's health, as it answers now.",
              build=_services)


# ------------------------------------------------------------------ models
register_card("models", title="Models", order=40,
              columns=("name", "up", "requests_per_min", "tokens_per_s", "source"),
              hint="Models the lab's servers serve, with their load (requests a minute, tokens a second). "
                   "bromigos lab models shows what's installed and loaded where.",
              summary=lambda items: (f"{sum(1 for i in items if i.get('up'))} of {len(items)} up · "
                                     f"{sum(i.get('requests_per_min') or 0 for i in items):.0f} req/min")
              if items else "the model servers list no models (give them an auth_ref to read /v1/models)")


# ------------------------------------------------------------------ deployments (Argo CD / Flux)
def _deploy(res):
    pats = hidden()
    items = []
    for x in res["items"]:
        if not _visible(x, pats):
            continue
        it = {k: x.get(k) for k in ("name", "namespace", "sync", "health", "revision", "source")}
        st = "crit" if x.get("health") in ("degraded", "missing") else \
            "warn" if x.get("sync") == "out_of_sync" or x.get("health") in ("progressing", "suspended") else \
            "ok" if x.get("health") == "healthy" else "unknown"
        it["state"] = st
        it["hint"] = f"{it['name']}: {it['sync'] or '?'}, {it['health'] or '?'}" + (
            " · the cluster differs from the repo" if x.get("sync") == "out_of_sync" else "")
        items.append(it)
    rank = {"crit": 0, "warn": 1, "unknown": 2, "ok": 3}
    items.sort(key=lambda i: (rank[i["state"]], str(i["name"])))
    good = sum(1 for i in items if i["state"] == "ok")
    s = f"{good} of {len(items)} synced and healthy"
    oos = sum(1 for i in items if i.get("sync") == "out_of_sync")
    if oos:
        s += f" · {oos} out of sync"
    return {"columns": ["name", "namespace", "sync", "health", "revision"], "items": items, "summary": s}


register_card("deployments", title="GitOps apps", order=50, capability="deployments", needs=("deployments",),
              covers=("deployments",),
              hint="Argo CD (or Flux) apps: whether the cluster matches the homelab repo (sync) and whether "
                   "they run (health). Problems first.", build=_deploy)


# ------------------------------------------------------------------ workloads
def _work(res):
    pats = hidden()
    ws = [w for w in res["items"] if _visible(w, pats)]
    counts = {}
    for w in ws:
        counts[w.get("state") or "unknown"] = counts.get(w.get("state") or "unknown", 0) + 1
    odd = [dict(w, state={"failed": "crit", "pending": "warn", "unknown": "warn"}.get(w.get("state"), "warn"),
                hint=f"{w.get('namespace')}/{w.get('name')} on {w.get('node') or '?'}: {w.get('state')}, "
                     f"{w.get('restarts') or 0} restarts")
           for w in ws if w.get("state") in ("failed", "pending", "unknown") or (w.get("restarts") or 0) >= 20]
    s = " · ".join(f"{n} {k}" for k, n in sorted(counts.items(), key=lambda kv: -kv[1]))
    return {"columns": ["name", "namespace", "kind", "state", "restarts", "node"], "items": odd,
            "summary": s or "none", "state": worst([w["state"] for w in odd]) if odd else "ok"}


register_card("workloads", title="Workloads", order=55, capability="workloads", needs=("workloads",),
              covers=("workloads",),
              hint="Pods, containers and VMs: how many run, and the ones that don't (failed, pending, "
                   "restarting a lot). The rest are fine.", build=_work)


# ------------------------------------------------------------------ storage
def _storage(_res):
    warn = float(config.setting("console", "disk_warn_pct", 85))
    crit = float(config.setting("console", "disk_crit_pct", 95))
    items = []

    def st(p):
        return "crit" if p >= crit else "warn" if p >= warn else "ok"
    if "storage" in registry.CAPABILITIES and caps.available("storage"):
        for x in caps.collect("storage")["items"]:
            p = x.get("used_pct")
            if p is None and x.get("used") and x.get("total"):
                p = 100.0 * x["used"] / x["total"]
            if p is None:
                continue
            items.append({"name": x.get("name"), "kind": x.get("kind") or "storage", "used_pct": _pct(p),
                          "state": st(p), "hint": f"{x.get('name')}: {p:.0f}% used"})
    if caps.available("metrics"):
        q = ('100*(1-node_filesystem_avail_bytes{fstype=~"nfs.*|cifs|smb.*"}'
             '/node_filesystem_size_bytes{fstype=~"nfs.*|cifs|smb.*"})')
        seen = set()
        for x in caps.metrics(q, timeout=6)["items"]:
            dev = x["labels"].get("device") or x["labels"].get("mountpoint")
            if dev in seen or x["value"] is None:
                continue
            seen.add(dev)
            items.append({"name": dev, "kind": "NAS share", "used_pct": _pct(x["value"]), "state": st(x["value"]),
                          "hint": f"{dev} (a network share): {x['value']:.0f}% used"})
    for h in caps.hosts()["items"]:
        if h.get("disk_pct") is None or any(i["name"] == h["name"] for i in items):
            continue
        items.append({"name": h["name"], "kind": "root disk", "used_pct": _pct(h["disk_pct"]),
                      "state": st(h["disk_pct"]), "hint": f"{h['name']}'s root disk: {h['disk_pct']:.0f}% used"})
    if not items:
        return None
    items.sort(key=lambda i: -(i["used_pct"] or 0))
    full = items[0]
    return {"columns": ["name", "kind", "used_pct"], "items": items,
            "summary": f"fullest: {full['name']} {full['used_pct']:.0f}%"}


register_card("storage", title="Storage", order=60, capability=None, needs=("hosts", "metrics", "storage"),
              covers=("storage",),
              hint="Disks and shares, fullest first: NAS shares and pools, then each machine's root disk. "
                   f"Amber from {85}%, red from {95}% ([console] disk_warn_pct / disk_crit_pct).", build=_storage)


# ------------------------------------------------------------------ alerts
def _alerts(res):
    pats = hidden()
    items = []
    for x in res["items"]:
        if x.get("state") not in ("firing", "pending") or not _visible({"name": x.get("name"),
                                                                       "namespace": (x.get("labels") or {}).get("namespace")}, pats):
            continue
        sev = (x.get("severity") or "").lower()
        it = {"name": x.get("name"), "severity": sev or "-", "state": "crit" if x["state"] == "firing" and sev in (
            "critical", "page", "error") else "warn", "firing": x["state"], "summary": x.get("summary") or "",
            "since": x.get("since"), "source": x.get("source")}
        it["hint"] = f"{it['name']} ({sev or 'no severity'}, {x['state']} since {x.get('since') or '?'}): {it['summary']}"
        items.append(it)
    items.sort(key=lambda i: (i["state"] != "crit", str(i["name"])))
    firing = sum(1 for i in items if i["firing"] == "firing")
    return {"columns": ["name", "severity", "firing", "summary", "since"], "items": items,
            "summary": f"{firing} firing" + (f", {len(items) - firing} pending" if len(items) > firing else "")
            if items else "none firing", "state": None if items else ("ok" if res["ok"] else None)}


def _alerts_finish(res):
    c = _alerts(res)
    if c["state"] is None:
        c.pop("state")
    return c


register_card("alerts", title="Alerts", order=70, capability="alerts", needs=("alerts",), covers=("alerts",),
              hint="Prometheus or Alertmanager alerts firing now (Watchdog left out). Red: critical.",
              build=_alerts_finish)


# ------------------------------------------------------------------ jobs (the lab queue)
def _jobs(_res):
    from . import jobqueue
    try:
        js = jobqueue.list_jobs(limit=12)
    except Exception:
        js = []
    st = {"queued": "unknown", "waiting": "warn", "running": "ok", "succeeded": "ok", "failed": "crit",
          "cancelled": "unknown"}
    items = [{"name": j["id"], "kind": j["kind"], "status": j["state"], "detail": j.get("why") or
              (", ".join(os.path.basename(o) for o in (j.get("outputs") or [])[:2])) or (j.get("prompt") or "")[:60],
              "state": st.get(j["state"], "unknown"), "hint": jobqueue.describe(j)} for j in js]
    run = sum(1 for j in js if j["state"] in ("running",))
    q = sum(1 for j in js if j["state"] in ("queued", "waiting"))
    svc = jobqueue.service_state()
    return {"columns": ["name", "kind", "status", "detail"], "items": items,
            "summary": (f"{run} running · {q} queued" if js else "no jobs yet: bromigos lab run …") + f" · service {svc}",
            "state": "ok" if not [i for i in items if i["state"] == "crit"] else "warn"}


register_card("jobs", title="Jobs", order=80, capability=None, needs=("media", "voice", "models"),
              hint="The lab job queue (bromigos lab jobs): image, cutout, 3D, hologram, voice and LLM jobs, run "
                   "one heavy job at a time when the GPU has the VRAM. Newest first.", build=_jobs)


# ------------------------------------------------------------------ Vault
def _vault_state(r):
    if r.get("sealed"):
        return "crit"
    if r.get("initialized") is False:
        return "warn"
    return "ok" if r.get("reachable") else "unknown"


register_card("secrets", title="Vault", order=90, columns=("name", "initialized", "sealed", "standby", "version"),
              state=_vault_state, hint="Vault's health only (up, initialized, sealed): the console never reads a "
                                       "secret.",
              summary=lambda items: "sealed!" if any(i.get("sealed") for i in items) else
              ("unsealed" if items else "-"))

register_card("agents", title="Agents", order=120, columns=("name", "status", "cwd"),
              hint="Coding agents working on this machine (herdr)")
register_card("ci", title="CI and pull requests", order=130,
              columns=("repo", "kind", "number", "title", "status", "conclusion"),
              hint="Open pull requests and the latest CI runs of the repos you named (GitHub)")
