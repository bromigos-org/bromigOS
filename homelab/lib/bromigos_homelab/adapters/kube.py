"""Kubernetes (workloads: pods; hosts: nodes) and Argo CD / Flux (deployments).

Kubernetes is read through kubectl with a read-only kubeconfig or a context:

    [[source]]
    type = "kubernetes"
    kubeconfig = "~/.local/share/bromigos/viewer-kubeconfig"   # or context = "…"

Argo CD, in the first way that works: its API (endpoint + auth_ref, an account token),
its Prometheus metrics (argocd_app_info, through the metrics capability), or its
Application objects through the kubernetes source. Flux: its Kustomizations and
HelmReleases through the kubernetes source.
"""
import json
import os
import shutil
import subprocess

from .. import config
from ..registry import Adapter, Unreachable, register, providers

_STATE = {"Running": "running", "Pending": "pending", "Failed": "failed", "Succeeded": "stopped", "Unknown": "unknown"}


def _kubectl_for(adapter, args, timeout=25):
    kc = config.expand(adapter.opts.get("kubeconfig") or "")
    cx = adapter.opts.get("context") or ""
    if kc and not os.path.exists(kc):
        raise Unreachable(f"{adapter.name}: no kubeconfig at {kc}")
    argv = ["kubectl", "--request-timeout=15s"] + (["--kubeconfig", kc] if kc else []) + \
        (["--context", cx] if cx else []) + list(args)
    try:
        p = subprocess.run(argv, capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired) as e:
        raise Unreachable(f"{adapter.name}: {e}") from None
    if p.returncode != 0:
        msg = (p.stderr or p.stdout).strip()[:300]
        if "Unable to connect" in msg or "connection refused" in msg or "i/o timeout" in msg:
            raise Unreachable(f"{adapter.name}: {msg}")
        raise RuntimeError(msg)
    return p.stdout


@register
class Kubernetes(Adapter):
    type = "kubernetes"
    provides = ("workloads", "hosts")
    local = True

    def configured(self):
        return bool(shutil.which("kubectl")) and bool(self.opts.get("kubeconfig") or self.opts.get("context"))

    def probe(self):
        return bool(self.kubectl(["version", "-o", "json"], timeout=8))

    def kubectl(self, args, timeout=25):
        """Read-only by the kubeconfig's own rights; callers pick get/logs/events."""
        return _kubectl_for(self, args, timeout)

    def workloads(self):
        d = json.loads(self.kubectl(["get", "pods", "-A", "-o", "json"]))
        out = []
        for p in d.get("items", []):
            st = p.get("status") or {}
            cs = st.get("containerStatuses") or []
            state = _STATE.get(st.get("phase"), "unknown")
            if any((c.get("state") or {}).get("waiting", {}).get("reason") in ("CrashLoopBackOff", "ImagePullBackOff",
                                                                               "ErrImagePull") for c in cs):
                state = "failed"
            out.append({"name": p["metadata"]["name"], "namespace": p["metadata"].get("namespace"), "kind": "pod",
                        "state": state, "restarts": sum(int(c.get("restartCount") or 0) for c in cs),
                        "node": (p.get("spec") or {}).get("nodeName"),
                        "image": ((p.get("spec") or {}).get("containers") or [{}])[0].get("image")})
        return out

    def hosts(self):
        d = json.loads(self.kubectl(["get", "nodes", "-o", "json"]))
        out = []
        for n in d.get("items", []):
            ready = next((c.get("status") == "True" for c in (n.get("status") or {}).get("conditions", [])
                          if c.get("type") == "Ready"), False)
            cap = (n.get("status") or {}).get("capacity") or {}
            out.append({"name": n["metadata"]["name"], "up": ready,
                        "cores": int(cap["cpu"]) if str(cap.get("cpu", "")).isdigit() else None})
        return out


def _kube_source():
    k = [a for a in providers("workloads") if a.type == "kubernetes"]
    return k[0] if k else None


_SYNC = {"Synced": "synced", "OutOfSync": "out_of_sync"}
_HEALTH = {"Healthy": "healthy", "Progressing": "progressing", "Degraded": "degraded", "Missing": "missing",
           "Suspended": "suspended"}


@register
class ArgoCD(Adapter):
    type = "argocd"
    provides = ("deployments",)
    local = True                    # works through other sources when it has no endpoint
    default_ports = (443, 8080)
    default_scheme = "https"

    def configured(self):
        return True

    def probe(self):
        d = self.get_json("/api/version", timeout=3)
        return isinstance(d, dict) and "Version" in d

    def _app(self, name, ns, sync, health, rev="", message=None):
        return {"name": name, "namespace": ns, "sync": _SYNC.get(sync, "unknown"), "health": _HEALTH.get(health, "unknown"),
                "revision": (rev or "")[:8], "message": message}

    def _from_object(self, a):
        st = a.get("status") or {}
        return self._app(a["metadata"]["name"], (a.get("spec", {}).get("destination") or {}).get("namespace"),
                         (st.get("sync") or {}).get("status"), (st.get("health") or {}).get("status"),
                         (st.get("sync") or {}).get("revision") or ((st.get("sync") or {}).get("revisions") or [""])[0],
                         app_message(a))

    def _objects(self):
        """Application objects: through the API (endpoint + auth_ref), else the kubernetes source."""
        if self.endpoint and self.opts.get("auth_ref"):
            return self.get_json("/api/v1/applications", timeout=10).get("items") or []
        k = _kube_source()
        if not k:
            return None
        ns = self.opts.get("namespace") or "argocd"
        return json.loads(k.kubectl(["get", "applications.argoproj.io", "-n", ns, "-o", "json"])).get("items", [])

    def deployments(self):
        if self.endpoint and self.opts.get("auth_ref"):
            return [self._from_object(a) for a in self._objects()]
        from .. import caps
        if caps.available("metrics"):
            r = caps.metrics("argocd_app_info")
            if r["ok"] and r["items"]:
                apps = [self._app(x["labels"].get("name"), x["labels"].get("dest_namespace"), x["labels"].get("sync_status"),
                                  x["labels"].get("health_status")) for x in r["items"]]
                bad = {a["name"] for a in apps if a["sync"] == "out_of_sync" or a["health"] in ("degraded", "missing")}
                if bad and _kube_source():               # why: the metrics don't say; the objects do
                    try:
                        why = {a["metadata"]["name"]: app_message(a) for a in self._objects() or []
                               if a["metadata"]["name"] in bad}
                        for a in apps:
                            a["message"] = why.get(a["name"])
                    except Exception:
                        pass
                return apps
        objs = self._objects()
        if objs is not None:
            return [self._from_object(a) for a in objs]
        raise Unreachable(f"{self.name}: no Argo CD API token, no argocd_app_info metrics and no kubernetes source")

    def flips(self, minutes=60):
        """{app: how many times it went Synced -> OutOfSync in the last minutes} (Argo's events,
        through the kubernetes source; {} without one)."""
        k = _kube_source()
        if not k:
            return {}
        ns = self.opts.get("namespace") or "argocd"
        try:
            d = json.loads(k.kubectl(["get", "events", "-n", ns, "--field-selector", "reason=ResourceUpdated",
                                      "-o", "json"], timeout=20))
        except Exception:
            return {}
        return count_flips(d.get("items", []), minutes)

    def doctor(self):
        """Why apps are out of sync or degraded (their sync error, conditions, drifting resources),
        and apps that flap: synced by Argo, then drifting again, over and over."""
        apps = self.deployments()
        try:                                     # the console's [console] hide patterns
            from ..console import _visible, hidden
            pats = hidden()
            apps = [a for a in apps if _visible(a, pats)]
        except ImportError:
            pass
        return argo_findings(apps, self.flips(), self.name)


def app_message(a):
    """Why an Application isn't synced and healthy, in one line: its conditions (ComparisonError,
    SyncError, …), a failed operation's message, the resources that differ from git, and the
    degraded ones' health messages."""
    st = a.get("status") or {}
    bits = []
    for c in st.get("conditions") or []:
        if c.get("message"):
            bits.append(f"{c.get('type')}: {c['message'].strip()[:300]}")
    op = st.get("operationState") or {}
    if op.get("phase") in ("Failed", "Error") and op.get("message"):
        bits.append(f"last sync {op['phase'].lower()}: {op['message'].strip()[:300]}")
    drift = [f"{r.get('kind')}/{r.get('name')}" for r in st.get("resources") or [] if r.get("status") == "OutOfSync"]
    if drift:
        bits.append("differs from git: " + ", ".join(drift[:6]) + (f" (+{len(drift) - 6})" if len(drift) > 6 else ""))
    sick = [f"{r.get('kind')}/{r.get('name')}: {(r.get('health') or {}).get('message') or (r.get('health') or {}).get('status')}"
            for r in st.get("resources") or [] if (r.get("health") or {}).get("status") in ("Degraded", "Missing")]
    if sick:
        bits.append("unhealthy: " + "; ".join(s[:160] for s in sick[:4]))
    return " · ".join(bits) or None


def count_flips(events, minutes=60, now=None):
    import time as _t
    from datetime import datetime
    now = now or _t.time()
    out = {}
    for e in events:
        if "-> OutOfSync" not in (e.get("message") or ""):
            continue
        t = e.get("lastTimestamp") or e.get("eventTime") or (e.get("metadata") or {}).get("creationTimestamp")
        try:
            ts = datetime.fromisoformat(str(t).replace("Z", "+00:00")).timestamp()
        except ValueError:
            continue
        if now - ts > minutes * 60:
            continue
        name = (e.get("involvedObject") or {}).get("name")
        out[name] = out.get(name, 0) + int(e.get("count") or 1)
    return out


def argo_findings(apps, flips=None, source=None, flap_at=3):
    """Doctor findings for Argo apps: each out-of-sync or degraded one with its message, and each
    that went out of sync flap_at+ times in the last hour (Argo heals it; something undoes it)."""
    from .labcommon import finding
    out = []
    for a in apps:
        n, msg, f = a["name"], a.get("message"), (flips or {}).get(a["name"], 0)
        bad = a["health"] in ("degraded", "missing")
        if not (bad or a["sync"] == "out_of_sync" or f >= flap_at):
            continue
        what = f"health {a['health']}" if bad else "out of sync" if a["sync"] == "out_of_sync" else "synced now"
        detail = "; ".join(x for x in (what, msg, f"went out of sync {f} times in the last hour" if f >= flap_at else "") if x)
        if f >= flap_at:
            fix = ("Argo syncs it and something changes it back: compare the drifting resource's live object with git "
                   "(argocd app diff). A controller that writes the field (a finalizer, an annotation, a default) "
                   "needs ignoreDifferences on the parent app; a hand edit needs to go into the repo.")
        elif bad:
            fix = ("Its resources aren't healthy: the message names them. Look at their pods' events and logs; fix it in "
                   "the repo and let Argo sync. Never patch Argo's state by hand.")
        else:
            fix = ("The cluster differs from git (the message says what). Put a hand change into the repo, or sync the "
                   "app; if it keeps coming back, something in the cluster rewrites it.")
        out.append(finding(f"argo.{n}.why", f"{n}: {'why it is ' + a['health'] if bad else 'why it drifts'}",
                           "fail" if bad else "warn", detail, fix, source=source, check="argo"))
    return out


@register
class Flux(Adapter):
    type = "flux"
    provides = ("deployments",)
    local = True

    def configured(self):
        return True

    def deployments(self):
        k = _kube_source()
        if not k:
            raise Unreachable(f"{self.name}: Flux is read through a kubernetes source; none is configured")
        out = []
        for kind in ("kustomizations.kustomize.toolkit.fluxcd.io", "helmreleases.helm.toolkit.fluxcd.io"):
            try:
                d = json.loads(k.kubectl(["get", kind, "-A", "-o", "json"]))
            except RuntimeError:
                continue
            for o in d.get("items", []):
                conds = {c.get("type"): c for c in (o.get("status") or {}).get("conditions", [])}
                ready = conds.get("Ready", {})
                health = "healthy" if ready.get("status") == "True" else (
                    "progressing" if ready.get("reason") in ("Progressing", "DependencyNotReady") else "degraded")
                if (o.get("spec") or {}).get("suspend"):
                    health = "suspended"
                out.append({"name": o["metadata"]["name"], "namespace": o["metadata"].get("namespace"),
                            "sync": "synced" if ready.get("status") == "True" else "out_of_sync", "health": health,
                            "revision": ((o.get("status") or {}).get("lastAppliedRevision") or "")[-8:]})
        return out
