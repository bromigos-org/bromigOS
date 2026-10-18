"""Prometheus and VictoriaMetrics (the same query API): metrics, hosts (node-exporter),
alerts (the server's own alert view)."""
import time
import urllib.parse

from ..registry import Adapter, register

# These two rules support monitoring itself, rather than report a problem.
# Match names exactly: other info-level alerts still belong in the user's list.
MONITORING_HELPERS = {"Watchdog", "InfoInhibitor"}


def _f(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


@register
class Prometheus(Adapter):
    type = "prometheus"
    provides = ("metrics", "hosts", "alerts")
    default_ports = (9090,)

    def probe(self):
        d = self.get_json("/api/v1/status/buildinfo", timeout=3)
        return isinstance(d, dict) and d.get("status") == "success"

    def metrics_query(self, q, timeout=8):
        d = self.get_json("/api/v1/query?" + urllib.parse.urlencode({"query": q}), timeout=timeout)
        return [{"labels": r.get("metric") or {}, "value": _f((r.get("value") or [None, None])[1]),
                 "t": _f((r.get("value") or [None])[0])} for r in d["data"]["result"]]

    def metrics_range(self, q, minutes=60, step=60, timeout=10):
        now = int(time.time())
        d = self.get_json("/api/v1/query_range?" + urllib.parse.urlencode(
            {"query": q, "start": now - int(minutes) * 60, "end": now, "step": step}), timeout=timeout)
        return [{"labels": r.get("metric") or {}, "points": [[float(t), _f(v)] for t, v in r.get("values", [])]}
                for r in d["data"]["result"]]

    def _by(self, q):
        try:
            return {r["labels"].get("instance"): r["value"] for r in self.metrics_query(q, timeout=6)}
        except Exception:
            return {}

    def hosts(self):
        """node-exporter's hosts: name (nodename), up (its scrape), CPU, memory, root disk, load."""
        names = {r["labels"].get("instance"): r["labels"].get("nodename") or r["labels"].get("instance")
                 for r in self.metrics_query("node_uname_info", timeout=6)}
        if not names:
            return []
        up = self._by('up{job=~".*node.*"}')
        cpu = self._by('100*(1-avg by (instance)(rate(node_cpu_seconds_total{mode="idle"}[5m])))')
        mem = self._by("100*(1-node_memory_MemAvailable_bytes/node_memory_MemTotal_bytes)")
        disk = self._by('100*(1-node_filesystem_avail_bytes{mountpoint="/"}/node_filesystem_size_bytes{mountpoint="/"})')
        load = self._by("node_load1")
        cores = self._by('count by (instance)(node_cpu_seconds_total{mode="idle"})')
        return [{"name": names[i], "up": (up[i] > 0) if i in up else True, "cpu_pct": cpu.get(i), "mem_pct": mem.get(i),
                 "disk_pct": disk.get(i), "load1": load.get(i), "cores": int(cores[i]) if i in cores else None}
                for i in names]

    def alerts(self):
        d = self.get_json("/api/v1/alerts", timeout=6)
        out = []
        for a in (d.get("data") or {}).get("alerts", []):
            lb = a.get("labels") or {}
            if lb.get("alertname") in MONITORING_HELPERS:
                continue
            out.append({"name": lb.get("alertname"), "severity": lb.get("severity"), "state": a.get("state"),
                        "summary": (a.get("annotations") or {}).get("summary") or (a.get("annotations") or {}).get("description"),
                        "since": a.get("activeAt"), "labels": lb,
                        "link": self.alert_link(lb.get("alertname"))})
        return out

    def alert_link(self, name):
        """The server's own alerts page, searched for this alert (its detail: rule, labels, since)."""
        if not self.endpoint or not name:
            return None
        return f"{self.endpoint}/alerts?search={urllib.parse.quote(str(name))}"


@register
class VictoriaMetrics(Prometheus):
    type = "victoriametrics"
    default_ports = (8428,)

    def probe(self):
        d = self.get_json("/api/v1/status/buildinfo", timeout=3)
        return isinstance(d, dict) and d.get("status") == "success" and "victoria" in str(d).lower()


@register
class Alertmanager(Adapter):
    type = "alertmanager"
    provides = ("alerts",)
    default_ports = (9093,)

    def probe(self):
        d = self.get_json("/api/v2/status", timeout=3)
        return isinstance(d, dict) and "cluster" in d

    def alert_link(self, labels):
        """Alertmanager's page for this alert (filtered by its name)."""
        if not self.endpoint or not labels.get("alertname"):
            return None
        return f"{self.endpoint}/#/alerts?filter=" + urllib.parse.quote('{alertname="%s"}' % labels["alertname"])

    def alerts(self):
        out = []
        for a in self.get_json("/api/v2/alerts?active=true&silenced=false&inhibited=false", timeout=6) or []:
            lb = a.get("labels") or {}
            if lb.get("alertname") in MONITORING_HELPERS:
                continue
            out.append({"name": lb.get("alertname"), "severity": lb.get("severity"),
                        "state": "firing" if (a.get("status") or {}).get("state") == "active" else "pending",
                        "summary": (a.get("annotations") or {}).get("summary"), "since": a.get("startsAt"), "labels": lb,
                        "link": a.get("generatorURL") or self.alert_link(lb)})
        return out
