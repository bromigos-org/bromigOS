"""A made-up lab for pictures drawn offscreen (demo.py's LAB panel, the theme previews'
live layer): five nodes, a dozen services in groups, a NAS, in bromigos-homelab's
snapshot shape (docs/homelab.md). No machine's names; nothing here runs on the desktop.
"""

DEMO_LAB = {
    "source": "demo",
    "cluster": {"nodesReady": 5, "nodesTotal": 5, "podsRunning": 86, "podsNotRunning": 0, "deploymentsShort": 0,
                "cpuNow": 23.0, "cpuSeries": [], "alertsFiring": 1},
    "argocd": {"healthy": 31, "total": 32},
    "traefik": {"rpsNow": 14.2},
    "network": {"wanDownBps": 48e6, "wanUpBps": 6.5e6},
    "ai": {"rpmNow": 38.0, "failedPerHour": 0.0, "rpmSeries": [], "models": []},
    "nodes": [{"name": "hub", "cpuPct": 31.0, "memPct": 58.0, "load1": 2.4, "cores": 16},
              {"name": "forge", "cpuPct": 64.0, "memPct": 71.0, "load1": 7.9, "cores": 24},
              {"name": "mast-1", "cpuPct": 12.0, "memPct": 44.0, "load1": 0.6, "cores": 8},
              {"name": "mast-2", "cpuPct": 18.0, "memPct": 49.0, "load1": 0.9, "cores": 8},
              {"name": "archive", "cpuPct": 4.0, "memPct": 27.0, "load1": 0.2, "cores": 4}],
    "config": {"groups": [
        {"name": "AI", "services": [{"id": "ollama", "name": "Ollama"}, {"id": "comfyui", "name": "ComfyUI"},
                                    {"id": "voice", "name": "Voice"}, {"id": "litellm", "name": "LiteLLM"}]},
        {"name": "PLATFORM", "services": [{"id": "argocd", "name": "Argo CD"}, {"id": "grafana", "name": "Grafana"},
                                          {"id": "prometheus", "name": "Prometheus"},
                                          {"id": "alertmanager", "name": "Alerts"}]},
        {"name": "HOME", "services": [{"id": "jellyfin", "name": "Jellyfin"}, {"id": "immich", "name": "Immich"},
                                      {"id": "nextcloud", "name": "Files"}, {"id": "backup", "name": "Backups"}]}]},
    "services": {sid: {"status": "up", "ms": ms} for sid, ms in (
        ("ollama", 12), ("comfyui", 34), ("voice", 21), ("litellm", 9), ("argocd", 41), ("grafana", 28),
        ("prometheus", 15), ("alertmanager", 11), ("jellyfin", 19), ("immich", 37), ("nextcloud", 52),
        ("backup", 8))},
    "nas": {"device": {"name": "archive"},
            "pool": {"used": 21.4e12, "total": 43.6e12, "raidMembers": 6, "health": "healthy"},
            "disks": [{"slot": i + 1, "model": "IronWolf Pro", "size": 8e12, "health": "good", "state": "normal",
                       "tempC": t, "hours": 21000 + 300 * i} for i, t in enumerate((36, 37, 38, 37, 39, 36))]},
    "nodeDisks": [{"node": n, "pct": p, "used": u, "capacity": c} for n, p, u, c in (
        ("hub", 41.0, 410e9, 1000e9), ("forge", 63.0, 1.26e12, 2000e9), ("mast-1", 22.0, 110e9, 500e9))],
}


def _big_lab():
    """A bigger made-up lab, the size a real one grows to: six nodes with long names, 36
    services in five groups (one down, one slow to answer), the NAS pool, the object
    store's share and three node disks. For pictures and tests of panels that must fit
    their content (BROMIGOS_WIDGETS_DEMO_LAB_SIZE=big)."""
    groups = {
        "AI": ["Ollama", "ComfyUI", "Voice", "LiteLLM", "Open WebUI", "Embeddings", "Whisper", "Reranker"],
        "PLATFORM": ["Argo CD", "Grafana", "Prometheus", "Alertmanager", "Loki", "Tempo", "Vault", "Traefik"],
        "HOME": ["Jellyfin", "Immich", "Files", "Backups", "Home Assistant", "Paperless", "Audiobooks", "Recipes"],
        "DEV": ["Forgejo", "Registry", "Woodpecker", "Renovate", "Sonar", "Docs"],
        "NETWORK": ["DNS", "DHCP", "WireGuard", "Unifi", "Uptime", "Speedtest"],
    }
    services, status = [], {}
    for g, names in groups.items():
        items = []
        for i, n in enumerate(names):
            sid = n.lower().replace(" ", "-")
            items.append({"id": sid, "name": n})
            status[sid] = {"status": "up", "ms": 8 + (i * 7) % 45}
        services.append({"name": g, "services": items})
    status["paperless"] = {"status": "down"}
    status["sonar"] = {"status": "degraded", "ms": 2400}
    status["rustfs"] = {"status": "up", "ms": 14}
    nodes = [("controller-1", 28.0, 61.0, 2.1, 16), ("gpu-worker-1", 71.0, 83.0, 9.4, 32),
             ("storage-node", 9.0, 38.0, 0.7, 8), ("edge-gateway", 14.0, 41.0, 0.9, 4),
             ("compute-west", 46.0, 66.0, 5.2, 24), ("compute-east", 39.0, 58.0, 4.4, 24)]
    return {
        "source": "demo",
        "cluster": {"nodesReady": 6, "nodesTotal": 6, "podsRunning": 214, "podsNotRunning": 1, "deploymentsShort": 1,
                    "cpuNow": 34.0, "cpuSeries": [], "alertsFiring": 3},
        "argocd": {"healthy": 58, "total": 60},
        "traefik": {"rpsNow": 41.0},
        "network": {"wanDownBps": 120e6, "wanUpBps": 18e6},
        "ai": {"rpmNow": 52.0, "failedPerHour": 1.0, "rpmSeries": [], "models": []},
        "nodes": [{"name": n, "cpuPct": c, "memPct": m, "load1": l, "cores": k} for n, c, m, l, k in nodes],
        "config": {"groups": services},
        "services": status,
        "nas": {"device": {"name": "storage-node"},
                "pool": {"used": 38.2e12, "total": 64.0e12, "raidMembers": 8, "health": "healthy"},
                "disks": [{"slot": i + 1, "model": "IronWolf Pro", "size": 8e12, "health": "good", "state": "normal",
                           "tempC": 35 + i % 4, "hours": 18000 + 400 * i} for i in range(8)],
                "shares": [{"name": "objects", "usage": 2.4e12, "quota": -1,
                            "volumes": [{"claim": "rustfs/rustfs-data"}]}]},
        "nodeDisks": [{"node": n, "pct": p, "used": u, "capacity": c} for n, p, u, c in (
            ("controller-1", 47.0, 470e9, 1000e9), ("gpu-worker-1", 72.0, 1.44e12, 2000e9),
            ("storage-node", 31.0, 155e9, 500e9))],
    }


BIG_LAB = _big_lab()
