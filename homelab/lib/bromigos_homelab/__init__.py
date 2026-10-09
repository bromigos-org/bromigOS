"""bromigos_homelab: connect a homelab to the bromigOS desktop (docs/homelab.md).

Consumers (the widgets, the live layer's decks and worlds, VECTOR) ask for capabilities;
adapters for the homelab's actual services provide them:

    import bromigos_homelab as H
    H.available("models")             # does anything provide it?
    H.models()                        # Result: {"ok", "items", "errors", "sources"}
    H.metrics("up")                   # metrics; also metrics_range, scalar, series
    H.hosts() H.workloads(namespace="ai") H.deployments() H.agents() H.secrets() H.ci() H.alerts()
    H.snapshot()                      # the whole lab in one dict (snapshot.py)
    H.models_level()                  # the worlds' `models` rain, 0..1
    H.status()                        # what's configured and what provides what

Installed by bromigos-homelab at /usr/lib/bromigos/lib/bromigos_homelab. Without the
package the desktop has no lab and its homelab views hide; with it, a capability nobody
provides hides its consumers, and a source that's down reads "unreachable".
"""
from . import caps, config, registry
from .caps import (agents, alerts, available, ci, deployments, hosts, metrics, metrics_range, models, models_level,
                   media, scalar, secrets, series, voice, workloads)
from .caps import (apps, backups, certs, ddns, games, gpus, library, logs, logs_query, network, ocr,  # noqa: F401
                   packages, routes, runners, storage)
from .registry import CAPABILITIES, Adapter, Unreachable, register
from .snapshot import snapshot, source as snapshot_source

__all__ = ["caps", "config", "registry", "Adapter", "Unreachable", "register", "CAPABILITIES", "agents", "alerts",
           "available", "ci", "deployments", "hosts", "metrics", "metrics_range", "models", "models_level", "scalar",
           "media", "secrets", "series", "voice", "workloads", "snapshot", "snapshot_source", "status", "configured", "source_of",
           "kubectl", "github_orgs", "lab_name", "lab_url", "relay_hosts",
           "apps", "backups", "certs", "ddns", "games", "gpus", "library", "logs", "logs_query", "network", "ocr",
           "packages", "routes", "runners", "storage"]


def source_of(type_):
    """The first configured source of an adapter type, or None."""
    return next((a for a in registry.instances() if a.type == type_), None)


def status():
    """{"sources": [{name, type, endpoint?, provides}], "capabilities": {cap: [source names]},
    "errors": [...]} — for bromigos homelab status, VECTOR's my_setup and the docs."""
    inst = registry.instances()
    return {"sources": [{"name": a.name, "type": a.type, "provides": list(a.caps),
                         **({"endpoint": a.endpoint} if a.endpoint else {})} for a in inst],
            "capabilities": {c: [a.name for a in inst if c in a.caps] for c in CAPABILITIES + ("snapshot",)},
            "errors": [f"{w}: {m}" for w, m in registry.ERRORS] + config.errors()}


def configured():
    return bool(registry.instances())


def kubectl(args, timeout=25):
    """kubectl through the first kubernetes source (read-only by its kubeconfig's rights)."""
    k = source_of("kubernetes")
    if not k:
        raise Unreachable("no kubernetes source in homelab.toml")
    return k.kubectl(args, timeout)


def github_orgs():
    g = source_of("github")
    return tuple((g.opts.get("orgs") or ()) if g else ())


def lab_name(default="LAB"):
    """The lab's display name: homelab.toml's top-level `name` (a reference works too, e.g.
    "@private:homelab.name"), else `default`. What the live layer's views call the lab."""
    v = config.resolve(config.load()["settings"].get("name"))
    return v.strip() if isinstance(v, str) and v.strip() else default


def lab_url():
    """Where the lab's own web view is (a lab source's endpoint), or ""."""
    a = source_of("lab")
    return a.endpoint if a else ""


def relay_hosts():
    """[{name, host}] from [relays] hosts (pinged by the drift map)."""
    out = []
    for h in config.setting("relays", "hosts", []) or []:
        if isinstance(h, dict) and h.get("host"):
            out.append({"name": h.get("name") or h["host"], "host": h["host"]})
        elif isinstance(h, str):
            out.append({"name": h, "host": h})
    return out
