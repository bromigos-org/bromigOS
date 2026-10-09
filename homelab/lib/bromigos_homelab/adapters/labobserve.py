"""Logs: Loki (capabilities logs and apps), Grafana Alloy (the collector; apps) and Dozzle (a
log viewer to link out to; apps).

    [[source]]
    type = "loki"
    endpoint = "http://loki.lab:3100"     # or service = "monitoring/loki:3100" (through the kubeconfig)
    # group_by = "namespace"              # what an "app" is: a stream label (namespace, app, container…)
    # window_min = 15                     # error counts over this window
    # error_pattern = "…"                 # a RE2 regex for an error line (default below)
    # warn_errors = 25                    # the card's amber; the doctor names apps from doctor_errors = 100
    # link = "https://dozzle.lab"         # where `lab logs` and the card link to read more

    [[source]]
    type = "alloy"                        # endpoint (its UI port, 12345), else its pods
    [[source]]
    type = "dozzle"
    endpoint = "http://dozzle.lab"

`logs` records are per app (by group_by): error lines in the window. logs_query() returns
recent lines for one app (`bromigos lab logs <app>`), newest first.
"""
import time
import urllib.parse

from ..registry import Unreachable, register
from . import labcommon as L

# An error line: a structured level of error/fatal/critical/panic, a bare upper-case ERROR /
# FATAL / CRITICAL / PANIC word, or a Python traceback. RE2 (LogQL's regex dialect).
ERROR_PATTERN = (r"""(?i:\b(?:level|lvl|severity)["']?\s*[=:]\s*["']?(?:error|err|fatal|crit|critical|panic)\b)"""
                 r"""|\b(?:ERROR|FATAL|CRITICAL|PANIC)\b|Traceback \(most recent call last\)""")


def error_counts(rows, group, window, warn=25, crit=500, link=None):
    """logs records from a `sum by (group)(count_over_time(…))` answer: worst first."""
    out = []
    for r in rows:
        name = (r.get("labels") or {}).get(group)
        if not name:
            continue
        n = int(round(r.get("value") or 0))
        out.append({"name": name, "errors": n, "window_min": window, "state": L.level(n, warn, crit),
                    "link": link, group: name})
    return sorted(out, key=lambda x: (-x["errors"], x["name"]))


def noisy_findings(records, at, window, source=None):
    """Doctor findings for apps logging at least `at` errors in the window (top 8), or one ok."""
    bad = [r for r in records if r["errors"] >= at]
    out = [L.finding(f"logs.{r['name']}", f"{r['name']}: error lines", "warn",
                     f"{r['errors']} in the last {window} min",
                     f"{r['name']} is logging errors. Read them with `bromigos lab logs {r['name']}` "
                     "(or your log viewer) and fix the cause; a steady stream usually means a crash loop, "
                     "a bad config or a dependency that's down.", source) for r in bad[:8]]
    if not bad:
        total = sum(r["errors"] for r in records)
        out.append(L.finding("logs.all", "Error lines", "ok",
                             f"no app over {at} in {window} min ({total} in all)", source=source))
    return out


@register
class Loki(L.AppAdapter):
    type = "loki"
    provides = ("logs", "apps")
    kind = "logs"
    own_namespace = False
    default_ports = (3100,)
    health_path = "/ready"
    pod_selector = "app.kubernetes.io/name=loki,app.kubernetes.io/component notin (canary,memcached-chunks-cache," \
                   "memcached-results-cache)"

    def probe(self):
        return b"ready" in self.request("/ready", timeout=3, raw=True).lower() and \
            "version" in (self.request("/loki/api/v1/status/buildinfo", timeout=3) or {})

    @classmethod
    def detect(cls, d):
        for s in d.objects("services", selector="app.kubernetes.io/name=loki"):
            ports = [p.get("port") for p in (s.get("spec") or {}).get("ports") or []]
            name = s["metadata"]["name"]
            if 3100 in ports and not any(w in name for w in ("headless", "memberlist", "canary", "gateway")):
                return [{"type": "loki", "service": f"{s['metadata']['namespace']}/{name}:3100",
                         "_note": "or endpoint = its URL, if the kubeconfig can't proxy to services"}]
        return []

    def check(self):
        b = self.fetch("/ready", raw=True, timeout=5)
        return b"ready" in b.lower(), "" if b"ready" in b.lower() else b.decode("utf-8", "replace")[:120]

    def version(self):
        return (self.fetch("/loki/api/v1/status/buildinfo", timeout=5) or {}).get("version")

    def namespace(self):
        return self.opt("namespace") or (self.service() or (None,))[0]

    def _query(self, q, timeout=15):
        d = self.fetch("/loki/api/v1/query?" + urllib.parse.urlencode({"query": q}), timeout=timeout) or {}
        if d.get("status") != "success":
            raise Unreachable(f"{self.name}: {str(d)[:160]}")
        return [{"labels": r.get("metric") or {}, "value": float((r.get("value") or [0, 0])[1])}
                for r in (d.get("data") or {}).get("result") or []]

    def logs(self):
        group = self.opt("group_by", "namespace")
        window = int(self.opt("window_min", 15))
        sel = self.opt("selector", '{%s=~".+"}' % group)
        pat = self.opt("error_pattern", ERROR_PATTERN)
        rows = self._query(f"sum by ({group}) (count_over_time({sel} |~ `{pat}` [{window}m]))")
        return error_counts(rows, group, window, int(self.opt("warn_errors", 25)), int(self.opt("crit_errors", 500)),
                            self.opt("link"))

    def logs_query(self, selector=None, since_min=60, limit=200, contains=None, timeout=15):
        """Recent lines: [{t (unix s), labels, line}], newest first. selector: an app name (its
        group_by label) or a LogQL stream selector ({…})."""
        group = self.opt("group_by", "namespace")
        sel = selector if str(selector or "").startswith("{") else \
            ('{%s="%s"}' % (group, selector) if selector else self.opt("selector", '{%s=~".+"}' % group))
        q = sel + (f' |= `{contains}`' if contains else "")
        now = time.time()
        d = self.fetch("/loki/api/v1/query_range?" + urllib.parse.urlencode(
            {"query": q, "limit": int(limit), "direction": "backward", "start": int((now - since_min * 60) * 1e9),
             "end": int(now * 1e9)}), timeout=timeout) or {}
        out = []
        for s in (d.get("data") or {}).get("result") or []:
            for t, line in s.get("values") or []:
                out.append({"t": int(t) / 1e9, "labels": s.get("stream") or {}, "line": line})
        return sorted(out, key=lambda x: -x["t"])[:int(limit)]

    def doctor(self):
        out = super().doctor()
        if out and out[0]["status"] == "fail":
            return out
        recs = self.logs()
        return out + noisy_findings(recs, int(self.opt("doctor_errors", 100)), int(self.opt("window_min", 15)), self.name)


@register
class Alloy(L.AppAdapter):
    type = "alloy"
    kind = "log collector"
    own_namespace = False
    default_ports = (12345,)
    health_path = "/-/ready"
    pod_selector = "app.kubernetes.io/name=alloy"

    def probe(self):
        return b"alloy" in self.request("/-/ready", timeout=3, raw=True).lower()

    @classmethod
    def detect(cls, d):
        ps = d.pods("app.kubernetes.io/name=alloy")
        return [{"type": "alloy", "namespace": ps[0]["metadata"]["namespace"]}] if ps else []

    def check(self):
        b = self.fetch("/-/ready", raw=True, timeout=5)
        return b"ready" in b.lower(), ""


@register
class Dozzle(L.AppAdapter):
    type = "dozzle"
    kind = "log viewer"
    health_path = "/healthcheck"
    pod_selector = "app.kubernetes.io/name=dozzle"

    def probe(self):
        self.request("/healthcheck", timeout=3, raw=True)
        return b"dozzle" in self.request("/", timeout=3, raw=True).lower()
