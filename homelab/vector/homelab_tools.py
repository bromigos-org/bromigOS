"""VECTOR's homelab tools (bromigos-homelab: docs/homelab.md; VECTOR's docs/plugins.md).

Read-only tools, each offered only when homelab.toml has what it needs, through the
capability layer, so they work on any homelab bromigOS has an adapter for:

  lab_status        the lab snapshot (a Lab API, or assembled from the capabilities)
  prometheus_query  the metrics capability (PromQL on Prometheus/VictoriaMetrics)
  k8s_get / k8s_logs / k8s_events   kubectl through the kubernetes source (read-only rights)
  argocd_apps       the deployments capability (Argo CD, Flux)
  lab_vault_status  the secrets capability: Vault's health only, never a secret
  gnosis_search / knowledge_search  the gnosis source (memory and knowledge base)

Same names, arguments and read level as when they were VECTOR's core tools; every call
goes through VECTOR's tools.call (audit log, event feed, stop-after-a-block). This folder
is packaged (root-owned) and guarded: a change to it switches VECTOR's terminal off.
"""
import math
import os
import re
import time

import bromigos_homelab as H

S = {"type": "string"}
I = {"type": "integer"}
B = {"type": "boolean"}
K8S_KINDS = {"pods", "deployments", "statefulsets", "daemonsets", "jobs", "cronjobs", "nodes", "services",
             "ingresses", "ingressroutes", "applications", "namespaces", "replicasets", "events"}


def _p(props, req=()):
    return {"type": "object", "properties": props, "required": list(req)}


def _need(res):
    if not res["sources"]:
        raise RuntimeError("nothing in homelab.toml provides this")
    if not res["ok"]:
        raise RuntimeError("unreachable: " + "; ".join(f"{k}: {v}" for k, v in res["errors"].items()))
    return res["items"]


# ------------------------------------------------------------------ the lab
def lab_status(section="overview"):
    D = H.snapshot()
    if D is None:
        raise RuntimeError("nothing in homelab.toml provides a lab snapshot")
    svc = D.get("services") or {}
    down = {k: v for k, v in svc.items() if v.get("status") != "up"}
    c = D.get("cluster") or {}
    if section == "overview":
        return {"nodes_ready": c.get("nodesReady"), "nodes_total": c.get("nodesTotal"), "pods_running": c.get("podsRunning"),
                "pods_not_running": c.get("podsNotRunning"), "alerts_firing": c.get("alertsFiring"), "cluster_cpu_pct": c.get("cpuNow"),
                "services_up": len(svc) - len(down), "services_total": len(svc), "services_down": list(down),
                "argocd": D.get("argocd"), "gpu": {k: (D.get("gpu") or {}).get(k) for k in ("count", "utilNow", "tempC", "powerW")},
                "ai_models_up": [m.get("name") for m in (D.get("ai") or {}).get("models", []) if m.get("up")],
                "players_now": (D.get("games") or {}).get("playersNow"),
                "wan_down_mbps": round((D.get("network") or {}).get("wanDownBps", 0) * 8 / 1e6, 1),
                "solar_w": (D.get("solar") or {}).get("productionW")}
    pick = {"nodes": ["nodes", "nodeDisks", "proxmox"], "services": ["services"], "gpu": ["gpu", "ai"],
            "storage": ["nas", "nodeDisks"], "network": ["network", "traefik"], "games": ["games"], "solar": ["solar"]}.get(section)
    if not pick:
        raise ValueError("section must be overview|nodes|services|gpu|storage|network|games|solar")
    out = {k: D.get(k) for k in pick}
    for v in out.values():   # drop long time series; the model wants the now
        if isinstance(v, dict):
            for k in list(v):
                if k.endswith("Series"):
                    v.pop(k)
    return out


def prometheus_query(promql, range_minutes=None, step_seconds=60):
    if len(promql) > 600:
        raise ValueError("query too long")
    if range_minutes:
        res = _need(H.metrics_range(promql, min(int(range_minutes), 1440), max(int(step_seconds), 15)))
        return [{"metric": r["labels"], "points": len(r["points"]),
                 "first": r["points"][0][1] if r["points"] else None, "last": r["points"][-1][1] if r["points"] else None,
                 "min": min((v for _, v in r["points"] if v is not None), default=None),
                 "max": max((v for _, v in r["points"] if v is not None), default=None)} for r in res[:25]]
    res = _need(H.metrics(promql))
    return {"count": len(res), "result": [{"metric": r["labels"], "value": r["value"]} for r in res[:40]]}


def lab_capacity():
    return _need(H.caps.collect('capacity'))


# ------------------------------------------------------------------ Kubernetes (read only)
def k8s_get(kind, namespace=None, name=None, selector=None):
    kind = kind.lower().rstrip()
    if kind in ("pod", "deployment", "node", "service", "job", "application", "ingress"):
        kind += "s"
    if kind not in K8S_KINDS:
        raise ValueError(f"kind must be one of {sorted(K8S_KINDS)}")
    if kind == "applications" and not namespace:
        namespace = "argocd"
    args = ["get", kind]
    if name:
        if not re.fullmatch(r"[a-z0-9.\-]{1,253}", name):
            raise ValueError("bad name")
        args.append(name)
    args += ["-n", namespace] if namespace else (["-A"] if kind not in ("nodes", "namespaces") else [])
    if selector:
        if not re.fullmatch(r"[\w./\-=,!]{1,200}", selector):
            raise ValueError("bad selector")
        args += ["-l", selector]
    if namespace and not re.fullmatch(r"[a-z0-9\-]{1,63}", namespace):
        raise ValueError("bad namespace")
    args += ["-o", "wide"] if kind in ("pods", "nodes") else []
    lines = H.kubectl(args).strip().splitlines()
    return {"rows": len(lines) - 1, "table": "\n".join(lines[:80]) + ("\n…" if len(lines) > 80 else "")}


def k8s_logs(namespace, pod, container=None, tail=80, grep=None):
    for v in (namespace, pod) + ((container,) if container else ()):
        if not re.fullmatch(r"[a-z0-9.\-]{1,253}", v or ""):
            raise ValueError("bad name")
    args = ["logs", "-n", namespace, pod, f"--tail={min(int(tail), 300)}"]
    if container:
        args += ["-c", container]
    lines = H.kubectl(args).splitlines()
    if grep:
        lines = [ln for ln in lines if grep.lower() in ln.lower()]
    return "\n".join(ln[:300] for ln in lines[-120:])


def k8s_events(namespace=None, warnings_only=True):
    args = ["get", "events", "--sort-by=.lastTimestamp"]
    args += ["-n", namespace] if namespace else ["-A"]
    if warnings_only:
        args += ["--field-selector", "type=Warning"]
    lines = H.kubectl(args).strip().splitlines()
    return "\n".join(lines if len(lines) <= 41 else lines[:1] + lines[-40:])


# ------------------------------------------------------------------ deployments, secrets
_SYNC = {"synced": "Synced", "out_of_sync": "OutOfSync"}
_HEALTH = {"healthy": "Healthy", "progressing": "Progressing", "degraded": "Degraded", "missing": "Missing",
           "suspended": "Suspended"}


def argocd_apps(problems_only=False):
    apps = [{"name": a["name"], "sync": _SYNC.get(a["sync"], "Unknown"), "health": _HEALTH.get(a["health"], "Unknown"),
             "revision": a.get("revision") or ""} for a in _need(H.deployments())]
    bad = [a for a in apps if a["sync"] != "Synced" or a["health"] != "Healthy"]
    return {"total": len(apps), "healthy_synced": len(apps) - len(bad), "problems": bad,
            **({} if problems_only else {"apps": [a["name"] for a in apps]})}


def lab_vault_status():
    return _need(H.secrets())


# ------------------------------------------------------------------ Gnosis (memory, knowledge base)
def _gnosis():
    g = H.source_of("gnosis")
    if not g:
        raise RuntimeError("no gnosis source in homelab.toml")
    return g


def gnosis_search(space, query, limit=5):
    g = _gnosis()
    users = {"vector": ("operator", "vector"), **{k: tuple(v) for k, v in (g.opts.get("search_spaces") or {}).items()}}
    if space not in users:
        raise ValueError(f"space must be one of {sorted(users)}")
    user, agent = users[space]
    scope = {"tenant_id": g.opts.get("tenant") or "bromigos", "space_id": space, "agent_id": agent, "session_id": agent,
             "user_id": user, "visibility": "private_user" if space == "vector" else "agent_shared"}
    res = g.search(scope, query, max(1, min(int(limit), 8)), timeout=20)
    return [{"content": x.get("content", "")[:600], "score": round(x.get("score", 0), 3),
             "date": (x.get("metadata") or {}).get("date") or x.get("created_at"), "kind": (x.get("metadata") or {}).get("kind")}
            for x in res]


_STOP = set("a an and are as at be by can do does for from has have how i in is it its me my of on or our so that the "
            "their them there this to us was we what whats when where which who why will with you your about".split())


def _terms(q):
    return [w for w in re.findall(r"[a-z0-9][a-z0-9_.-]*[a-z0-9]|[a-z0-9]", q.lower().replace("'s", "")) if w not in _STOP and len(w) > 1]


def _kb_spaces(g):
    """{short name: space id}: kb-desktop -> desktop."""
    return {s[3:] if s.startswith("kb-") else s: s for s in g.opts.get("spaces") or []}


def _kb_file(g, space, repo, path):
    """Where a knowledge-base chunk's doc lives on this machine, if it does: [gnosis] roots
    (space -> a folder) or orgs (space -> ~/github.com/<org>/<repo>)."""
    if not repo or not path:
        return None
    home = os.path.expanduser("~")
    roots = []
    root = (g.opts.get("roots") or {}).get(space)
    if root:
        roots.append(os.path.expanduser(root))
    org = (g.opts.get("orgs") or {}).get(space)
    if org:
        roots.append(os.path.join(home, "github.com", org, repo))
    for r in roots:
        f = os.path.join(r, path)
        if os.path.isfile(f):
            return f
    return None


def knowledge_search(query, space=None, limit=6):
    """The knowledge base in Gnosis, read through its gate. Gnosis ranks by embeddings only,
    which misses exact names, so a wider pool per space is re-ranked here with a small
    lexical bonus (query words in the path, heading and text), and copies of the same doc
    (a repo kept in two orgs) are folded together."""
    import concurrent.futures as cf
    g = _gnosis()
    kb = _kb_spaces(g)
    spaces = list(kb.values())
    if not spaces:
        raise RuntimeError("the gnosis source lists no knowledge-base spaces (spaces = [...])")
    if space:
        sp = kb.get(space.replace("kb-", ""), space)
        if sp not in spaces:
            raise ValueError(f"space must be one of {sorted(kb)}")
        spaces = [sp]
    n = max(1, min(int(limit), 10))
    terms = _terms(query)
    tenant = g.opts.get("tenant") or "bromigos"

    def one(sp):
        scope = {"tenant_id": tenant, "space_id": sp, "agent_id": "vector", "session_id": "vector",
                 "user_id": sp, "visibility": "agent_shared"}
        return sp, g.search(scope, query, 20, timeout=10)

    WORD = re.compile(r"[a-z0-9][a-z0-9_.-]*[a-z0-9]|[a-z0-9]")
    pool = []
    with cf.ThreadPoolExecutor(len(spaces)) as ex:
        for sp, res in ex.map(one, spaces):
            for x in res:
                m = x.get("metadata") or {}
                text = x.get("content") or ""
                where = f"{m.get('repo') or ''}/{m.get('path') or ''} {m.get('heading') or ''}".lower()
                pool.append((sp, x, m, text, where, set(WORD.findall(text.lower()))))
    idf = {t: math.log((len(pool) + 1) / (1 + sum(1 for p in pool if t in p[5] or t in p[4]))) + 0.1 for t in terms}
    total = sum(idf.values()) or 1.0
    hits, seen = [], {}
    for sp, x, m, text, where, words in pool:
        bonus = (0.14 * sum(idf[t] for t in terms if t in words) + 0.08 * sum(idf[t] for t in terms if t in where)) / total
        score = (x.get("score") or 0) + bonus
        key = (m.get("path"), m.get("heading"), text[:200])
        h = {"space": sp, "score": round(score, 3), "repo": m.get("repo"), "path": m.get("path"),
             "heading": m.get("heading"), "url": m.get("url"), "text": text[:900], "id": x.get("memory_id")}
        f = _kb_file(g, sp, m.get("repo"), m.get("path"))
        if f:
            h["file"] = f
        if key in seen:
            keep = seen[key]
            keep.setdefault("also_in", []).append(f"{sp}:{m.get('repo')}")
            keep["score"] = max(keep["score"], h["score"])
            continue
        seen[key] = h
        hits.append(h)
    hits.sort(key=lambda h: -h["score"])
    try:
        from holo.vector import events
        for sp in sorted({h["space"] for h in hits[:n]}):
            ids = [h["id"] for h in hits[:n] if h["space"] == sp and h.get("id")]
            events.emit("memory.recall", space=sp, ids=ids, n=len(ids), ms=None, source="gnosis")
    except Exception:
        pass
    return {"query": query, "hits": hits[:n]}


# ------------------------------------------------------------------ registration
def register(vector):
    has = H.available
    if has('capacity'):
        vector.tool('lab_capacity', 'Read-only proposals for a new Kubernetes worker or GPU node after sustained pressure. Never creates resources; user approval is required.', _p({}), lab_capacity)
    if H.snapshot_source():
        vector.tool("lab_status", "The homelab's summary (its lab snapshot). section: overview (default), nodes, services, "
                    "gpu, storage, network, games, solar.", _p({"section": S}), lab_status)
    if has("metrics"):
        vector.tool("prometheus_query", "PromQL against the homelab's metrics (read only). Instant by default; "
                    "range_minutes for a summary over time.",
                    _p({"promql": S, "range_minutes": I, "step_seconds": I}, ["promql"]), prometheus_query)
    if H.source_of("kubernetes"):
        vector.tool("k8s_get", "Read-only kubectl get on the homelab cluster. kind: " + ", ".join(sorted(K8S_KINDS)) +
                    ". Optional namespace, name, selector.",
                    _p({"kind": S, "namespace": S, "name": S, "selector": S}, ["kind"]), k8s_get)
        vector.tool("k8s_logs", "Tail a pod's logs (read only). tail up to 300 lines; optional grep substring.",
                    _p({"namespace": S, "pod": S, "container": S, "tail": I, "grep": S}, ["namespace", "pod"]), k8s_logs)
        vector.tool("k8s_events", "Recent cluster events, warnings only by default.",
                    _p({"namespace": S, "warnings_only": B}), k8s_events)
    if has("deployments"):
        vector.tool("argocd_apps", "The homelab's GitOps apps (Argo CD / Flux): sync and health.",
                    _p({"problems_only": B}), argocd_apps)
    if has("secrets"):
        vector.tool("lab_vault_status", "Vault's health in the homelab: reachable, initialized, sealed, version. "
                    "Status only: it never reads a secret.", _p({}), lab_vault_status)
    g = H.source_of("gnosis")
    if g:
        extra = sorted((g.opts.get("search_spaces") or {}))
        vector.tool("gnosis_search", "Search memory: vector (your own long-term memory)"
                    + (", or " + ", ".join(extra) + " (read only)" if extra else "") + ".",
                    _p({"space": S, "query": S, "limit": I}, ["space", "query"]), gnosis_search)
        kb = _kb_spaces(g)
        if kb:
            labels = g.opts.get("labels") or {}
            desc = "; ".join(f"{short} ({labels.get(sp, sp)})" for short, sp in kb.items())
            vector.tool("knowledge_search", "Search the knowledge base: what the host's software is and how it works. "
                        f"Spaces: {desc}. Omit space to search all. For exact detail, docs_read a hit's file (its local "
                        "path; never the url); hits from .py files are code docstrings, so read those with run_shell.",
                        _p({"query": S, "space": S, "limit": I}, ["query"]), knowledge_search)


_ = time
