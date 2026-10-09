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
