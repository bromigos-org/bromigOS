"""The network's edge: Traefik (routes), cert-manager (certs), a dynamic-DNS updater (ddns),
and UniFi through UniFi Poller's metrics (network).

    [[source]]
    type = "traefik"
    endpoint = "http://traefik.lab"      # its API (the dashboard's /api); else its metrics, else
                                         # IngressRoutes through the kubernetes source
    [[source]]
    type = "cert-manager"                # its metrics, else Certificates (kubernetes), else the
                                         # certificates Traefik serves (traefik_tls_certs_not_after)
    # warn_days = 21, fail_days = 7

    [[source]]
    type = "ddns"                        # a dynamic-DNS CronJob, read through the kubernetes source
    # namespace = "cloudflare-ddns"      # default: CronJobs named *ddns* / *dyndns* in any namespace
    # ip_url = "https://…"               # optional: a URL answering this network's public IPv4 now
    # resolver = "https://…/dns-query"   # optional: DNS-over-HTTPS (JSON) to resolve the records with

    [[source]]
    type = "unifi"                       # UniFi Poller's metrics (unpoller_*) in the metrics source
"""
import json
import re
import socket
import time
import urllib.parse
import urllib.request

from ..registry import Unreachable, register
from . import labcommon as L

# ------------------------------------------------------------------ Traefik

_HASH = re.compile(r"-[0-9a-f]{20}$")


def router_name(n):
    """"media-plex-0123…cdef@kubernetescrd" -> "media-plex"."""
    return _HASH.sub("", (n or "").split("@", 1)[0])


def rule_hosts(rule):
    return re.findall(r"Host(?:SNI)?\(\s*[`\"]([^`\"]+)[`\"]", rule or "")


def routes_from_api(routers, services, rps=None, errs=None):
    """routes records from Traefik's /api/http/routers and /api/http/services answers."""
    svc = {s.get("name"): s for s in services or []}
    out = []
    for r in routers or []:
        if r.get("provider") == "internal" and (r.get("name") or "").endswith("@internal"):
            continue
        sname = r.get("service") or ""
        if "@" not in sname and "@" in (r.get("name") or ""):
            sname += "@" + r["name"].split("@", 1)[1]
        s = svc.get(sname) or svc.get(r.get("service")) or {}
        status = s.get("serverStatus") or {}
        servers = (s.get("loadBalancer") or {}).get("servers") or []
        if s.get("provider") == "internal" or sname.endswith("@internal"):
            up = r.get("status") == "enabled"
        elif status:
            up = any(v == "UP" for v in status.values())
        else:
            up = bool(servers) and r.get("status") == "enabled"
        name = router_name(r.get("name"))
        rec = {"name": name, "host": ", ".join(rule_hosts(r.get("rule"))) or r.get("rule"),
               "entrypoints": r.get("entryPoints") or [], "service": router_name(sname), "up": up,
               "status": r.get("status"), "tls": "tls" in r,
               "rps": (rps or {}).get(r.get("name")), "error_pct": (errs or {}).get(r.get("name")),
               "servers": len(status) or len(servers), "error": r.get("error") or s.get("error")}
        rec["state"] = "crit" if r.get("status") != "enabled" or not up else \
            "warn" if (rec["error_pct"] or 0) >= 20 else "ok"
        out.append(rec)
    seen = {}
    for rec in sorted(out, key=lambda x: (x["name"], x["host"] or "", x["entrypoints"])):
        seen[rec["name"]] = seen.get(rec["name"], 0) + 1
        if seen[rec["name"]] > 1:                # one IngressRoute, several routes
            rec["name"] = f"{rec['name']}#{seen[rec['name']]}"
    return sorted(out, key=lambda x: x["name"])


def route_findings(routes, source=None):
    out = []
    for r in routes:
        if r.get("status") not in (None, "enabled"):
            out.append(L.finding(f"routes.{r['name']}", f"Route {r['name']}", "fail",
                                 f"{r.get('status')}: {'; '.join(r.get('error') or []) if isinstance(r.get('error'), list) else r.get('error') or ''}".strip(": "),
                                 "Traefik rejected this route: fix the IngressRoute (or Ingress) it names; "
                                 "its error says what's wrong.", source))
        elif r.get("up") is False:
            out.append(L.finding(f"routes.{r['name']}", f"Route {r['name']} ({r['host']})", "fail",
                                 f"no healthy backend ({r.get('servers') or 0} servers)",
                                 f"Nothing answers behind {r['host']}: its service has no ready pods (or they fail "
                                 "Traefik's health check). Look at the service's pods.", source))
        elif (r.get("error_pct") or 0) >= 20:
            out.append(L.finding(f"routes.{r['name']}", f"Route {r['name']} ({r['host']})", "warn",
                                 f"{r['error_pct']:.0f}% of requests answer 5xx",
                                 "The app behind it is failing requests: read its logs.", source))
    if routes and not out:
        out.append(L.finding("routes.all", "Routes", "ok", f"{len(routes)} routes, every one with a backend", source=source))
    return out


@register
class Traefik(L.LabAdapter):
    type = "traefik"
    provides = ("routes",)
    default_ports = (8080,)
    ingress_merge = True                # setup: its API (the dashboard's host) joins the detected source

    def probe(self):
        d = self.request("/api/overview", timeout=3)
        return isinstance(d, dict) and "http" in d and "routers" in d["http"]

    @classmethod
    def detect(cls, d):
        if d.has_metric("traefik_router_requests_total") or d.has_metric("traefik_entrypoint_requests_total"):
            return [{"type": "traefik", "_note": "endpoint = its API (the dashboard) adds each route's backends"}]
        return []

    def _rates(self):
        if not L.have_metrics():
            return {}, {}
        rps = L.keyed(L.mq_soft("sum by (router)(rate(traefik_router_requests_total[5m]))"), "router")
        bad = L.keyed(L.mq_soft('sum by (router)(rate(traefik_router_requests_total{code=~"5.."}[5m]))'), "router")
        errs = {k: 100.0 * bad.get(k, 0) / v for k, v in rps.items() if v and bad.get(k)}
        return rps, errs

    def routes(self):
        rps, errs = self._rates()
        if self.has_web():
            routers = self.fetch("/api/http/routers?per_page=1000", timeout=8)
            services = self.fetch("/api/http/services?per_page=1000", timeout=8)
            return routes_from_api(routers, services, rps, errs)
        if L.kube():
            out = []
            for ir in L.kube_json(["get", "ingressroutes.traefik.io", "-A"]).get("items", []):
                for i, rt in enumerate((ir.get("spec") or {}).get("routes") or []):
                    name = f"{ir['metadata']['namespace']}-{ir['metadata']['name']}" + (f"-{i}" if i else "")
                    out.append({"name": name, "host": ", ".join(rule_hosts(rt.get("match"))),
                                "entrypoints": (ir.get("spec") or {}).get("entryPoints") or [],
                                "service": ", ".join(s.get("name", "") for s in rt.get("services") or []),
                                "up": None, "status": "declared", "tls": bool((ir.get("spec") or {}).get("tls")),
                                "rps": None, "error_pct": None})
            return out
        if rps:
            return [{"name": router_name(k), "host": None, "service": None, "up": None, "status": "enabled",
                     "rps": v, "error_pct": errs.get(k), "state": "warn" if (errs.get(k) or 0) >= 20 else "ok"}
                    for k, v in sorted(rps.items())]
        raise Unreachable(f"{self.name}: no endpoint for Traefik's API, no kubernetes source and no Traefik metrics")

    def doctor(self):
        return route_findings(self.routes(), self.name)


# ------------------------------------------------------------------ cert-manager


def cert_record(name, ns, not_after, ready=None, dns_names=None, issuer=None, warn=21, fail=7, now=None):
    t = L.ts(not_after)
    days = None if t is None else int((t - (now or time.time())) // 86400)
    st = "unknown" if days is None else "crit" if days < fail or ready is False else "warn" if days < warn else "ok"
    return {"name": name, "namespace": ns, "dns_names": dns_names or [], "not_after": L.iso(t), "days_left": days,
            "ready": ready, "issuer": issuer, "state": st}


def certs_from_objects(items, warn=21, fail=7, now=None):
    out = []
    for c in items:
        st = c.get("status") or {}
        ready = next((x.get("status") == "True" for x in st.get("conditions") or [] if x.get("type") == "Ready"), None)
        out.append(cert_record(c["metadata"]["name"], c["metadata"].get("namespace"), st.get("notAfter"), ready,
                               (c.get("spec") or {}).get("dnsNames"), ((c.get("spec") or {}).get("issuerRef") or {}).get("name"),
                               warn, fail, now))
    return out


def cert_findings(certs, warn=21, fail=7, source=None):
    out = []
    for c in certs:
        cid = f"certs.{c.get('namespace') + '/' if c.get('namespace') else ''}{c['name']}"
        d = c.get("days_left")
        if c.get("ready") is False:
            out.append(L.finding(cid, f"Certificate {c['name']}", "fail", "not ready",
                                 "cert-manager can't issue it: `kubectl describe certificate` and its "
                                 "CertificateRequest/Order say why (often the ACME challenge or the issuer).", source))
        elif d is not None and d < fail:
            out.append(L.finding(cid, f"Certificate {c['name']}", "fail",
                                 f"expires {c['not_after'][:10]} ({'expired' if d < 0 else f'in {d} days'})",
                                 "Renewal isn't happening: check the Certificate's events and its issuer, then "
                                 "renew it (cmctl renew).", source))
        elif d is not None and d < warn:
            out.append(L.finding(cid, f"Certificate {c['name']}", "warn", f"expires {c['not_after'][:10]} (in {d} days)",
                                 "cert-manager renews ahead of expiry (two-thirds through by default): if this "
                                 "one hasn't, check its events and its issuer.", source))
    if certs and not out:
        soonest = min((c for c in certs if c.get("days_left") is not None), key=lambda c: c["days_left"], default=None)
        out.append(L.finding("certs.all", "Certificates", "ok", f"{len(certs)} certificates" + (
            f", the soonest in {soonest['days_left']} days ({soonest['name']})" if soonest else ""), source=source))
    return out


@register
class CertManager(L.LabAdapter):
    type = "cert-manager"
    provides = ("certs",)
    default_ports = (9402,)

    def probe(self):
        return b"certmanager_" in self.request("/metrics", timeout=3, raw=True)

    @classmethod
    def detect(cls, d):
        if d.has_metric("certmanager_certificate_expiration_timestamp_seconds") or \
                d.pods("app.kubernetes.io/name=cert-manager") or d.has_metric("traefik_tls_certs_not_after"):
            return [{"type": "cert-manager"}]
        return []

    def _limits(self):
        return int(self.opt("warn_days", 21)), int(self.opt("fail_days", 7))

    def _from_rows(self, exp, ready):
        warn, fail = self._limits()
        rd = {(r["labels"].get("namespace") or r["labels"].get("exported_namespace"), r["labels"].get("name")): r["value"]
              for r in ready if r["labels"].get("condition") == "True"}
        out = []
        for r in exp:
            lb = r["labels"]
            ns = lb.get("exported_namespace") or lb.get("namespace")
            out.append(cert_record(lb.get("name"), ns, r["value"],
                                   bool(rd[(ns, lb.get("name"))]) if (ns, lb.get("name")) in rd else None,
                                   None, lb.get("issuer_name"), warn, fail))
        return out

    def certs(self):
        warn, fail = self._limits()
        if self.has_web():
            s = L.parse_prom(self.fetch("/metrics", raw=True))
            return self._from_rows(L.rows_of(s, "certmanager_certificate_expiration_timestamp_seconds"),
                                   L.rows_of(s, "certmanager_certificate_ready_status"))
        exp = L.mq_soft("certmanager_certificate_expiration_timestamp_seconds")
        if exp:
            return self._from_rows(exp, L.mq_soft("certmanager_certificate_ready_status"))
        why = []
        if L.kube():
            try:
                return certs_from_objects(L.kube_json(["get", "certificates.cert-manager.io", "-A"]).get("items", []),
                                          warn, fail)
            except Exception as e:
                why.append(str(e).split("\n")[0][:120])
        served = L.mq_soft("traefik_tls_certs_not_after")
        if served:                               # what Traefik serves: no names, but the expiry is real
            out = []
            for r in served:
                lb = r["labels"]
                sans = [x for x in (lb.get("sans") or "").split(",") if x]
                rec = cert_record(lb.get("cn") or (sans[0] if sans else lb.get("serial", "?")[:12]), None, r["value"],
                                  None, sans, "served by Traefik", warn, fail)
                out.append(rec)
            return out
        raise Unreachable(f"{self.name}: no cert-manager metrics, Certificates or served certificates"
                          + (f" ({'; '.join(why)})" if why else ""))

    def doctor(self):
        warn, fail = self._limits()
        return cert_findings(self.certs(), warn, fail, self.name)


# ------------------------------------------------------------------ dynamic DNS

_IP = r"(\d{1,3}(?:\.\d{1,3}){3})"
_HOSTNAME = r"((?:\*\.)?[a-z0-9-]+(?:\.[a-z0-9-]+)+)"


def parse_ddns_log(text):
    """{public_ip, records: [{name, type, ip, proxied, status}], failures, changes} from a DDNS
    updater's log (a generic reading: a WAN/public/current IP line, and one line per record with
    a status word, its name and its address)."""
    out = {"public_ip": None, "records": [], "failures": 0, "changes": 0}
    seen = {}
    for line in (text or "").splitlines():
        low = line.lower()
        m = re.search(r"(?:wan|public|current|external|detected)\b.{0,20}?\bip(?:v4)?\b(?:\s+address)?(?:\s+is)?\s*[:=]?\s*"
                      + _IP, low)
        if m:
            out["public_ip"] = m.group(1)
            continue
        m = re.search(r"(\d+)\s+failure", low)
        if m:
            out["failures"] = max(out["failures"], int(m.group(1)))
        m = re.search(r"(\d+)\s+change", low)
        if m:
            out["changes"] = max(out["changes"], int(m.group(1)))
        hosts = [h for h in re.findall(_HOSTNAME, low) if not re.fullmatch(_IP, h)]
        ip = re.search(_IP, line)
        if not hosts or not ip:
            continue
        host = hosts[0]
        status = "fail" if re.search(r"\b(fail\w*|error)\b", low) else \
            "updated" if re.search(r"\b(updat\w*|added|creat\w*|chang\w*|set to)\b", low) else \
            "ok" if re.search(r"\b(ok|unchanged|up to date|already|no change|skip\w*)\b", low) else None
        if status is None:
            continue
        rtype = "AAAA" if re.search(r"\bAAAA\b", line) else "A"
        prox = re.search(r"proxied[=: ]+(true|false)", low)
        seen[(host, rtype)] = {"name": host, "type": rtype, "ip": ip.group(1),
                                        "proxied": (prox.group(1) == "true") if prox else None, "status": status}
    out["records"] = list(seen.values())
    return out


def ddns_records(parsed, job_ok, last_success, now_ip=None, resolved=None):
    """ddns records: each record's address against the public one (now_ip when known, else
    what the updater saw), with what DNS answers when resolved."""
    pub = now_ip or parsed.get("public_ip")
    out = []
    for r in parsed["records"]:
        dns_ip = (resolved or {}).get(r["name"])
        match = (r["ip"] == pub) if pub else None
        if dns_ip and not r.get("proxied"):
            match = match is not False and dns_ip == pub
        st = "crit" if r["status"] == "fail" or match is False or not job_ok else "ok"
        out.append({"name": r["name"], "type": r["type"], "public_ip": pub, "dns_ip": dns_ip or r["ip"],
                    "match": match, "proxied": r.get("proxied"), "updated": L.iso(last_success), "state": st,
                    "status": r["status"]})
    return out


def ddns_findings(recs, job, now_ip=None, logged_ip=None, source=None):
    out = []
    if job.get("missing"):
        return [L.finding("ddns.job", "Dynamic DNS", "fail", job["missing"],
                          "No DDNS updater found: name its namespace or CronJob in homelab.toml.", source)]
    age, every = job.get("age_min"), job.get("every_min") or 60
    if job.get("suspended"):
        out.append(L.finding("ddns.job", f"Dynamic DNS ({job['name']})", "warn", "the CronJob is suspended",
                             "Your public address can change without DNS following: resume the CronJob.", source))
    elif age is None:
        out.append(L.finding("ddns.job", f"Dynamic DNS ({job['name']})", "fail", "never succeeded",
                             "Its runs fail: read the last one's log (bromigos lab logs " + job.get("namespace", "") + ").",
                             source))
    elif age > 3 * every + 10:
        out.append(L.finding("ddns.job", f"Dynamic DNS ({job['name']})", "fail",
                             f"last good run {age:.0f} min ago (it runs every {every} min)",
                             "Its recent runs fail: read their logs. Often a revoked or expired API token.", source))
    if now_ip and logged_ip and now_ip != logged_ip:
        out.append(L.finding("ddns.ip", "Public address", "warn", "the public address changed since the last update",
                             "The next DDNS run should catch it; if it doesn't, run its CronJob now.", source))
    for r in recs:
        if r["state"] == "crit" and r.get("status") == "fail":
            out.append(L.finding(f"ddns.{r['name']}", f"DNS record {r['name']}", "fail", "the last update failed",
                                 "Read the updater's log; a token without DNS edit rights or a deleted zone "
                                 "are the usual causes.", source))
        elif r.get("match") is False:
            out.append(L.finding(f"ddns.{r['name']}", f"DNS record {r['name']}", "fail",
                                 "points somewhere else than this network's public address",
                                 "Visitors reach the old address. Run the updater now and check its log.", source))
    if recs and not out:
        out.append(L.finding("ddns.all", "Dynamic DNS", "ok",
                             f"{len(recs)} record(s) match the public address · updated {age:.0f} min ago"
                             if age is not None else f"{len(recs)} record(s)", source=source))
    return out


@register
class DDNS(L.LabAdapter):
    type = "ddns"
    provides = ("ddns",)

    @classmethod
    def detect(cls, d):
        cj = [c for c in d.objects("cronjobs.batch") if re.search(r"ddns|dyndns|dynamic-dns", c["metadata"]["name"])]
        return [{"type": "ddns", "namespace": cj[0]["metadata"]["namespace"]}] if cj else []

    def _job(self):
        if not L.kube():
            raise Unreachable(f"{self.name}: the DDNS updater is read through a kubernetes source; none is configured")
        ns = self.opt("namespace")
        items = L.kube_json(["get", "cronjobs.batch"] + (["-n", ns] if ns else ["-A"])).get("items", [])
        want = self.opt("cronjob")
        cj = [c for c in items if (c["metadata"]["name"] == want) if want] or \
            [c for c in items if re.search(r"ddns|dyndns|dynamic-dns", c["metadata"]["name"])] or (items if ns else [])
        if not cj:
            return {"missing": "no DDNS CronJob" + (f" in {ns}" if ns else "")}, ""
        c = cj[0]
        st = c.get("status") or {}
        last = L.ts(st.get("lastSuccessfulTime"))
        job = {"name": c["metadata"]["name"], "namespace": c["metadata"]["namespace"],
               "every_min": L.cron_minutes((c.get("spec") or {}).get("schedule")),
               "suspended": bool((c.get("spec") or {}).get("suspend")), "last_success": last,
               "age_min": None if last is None else (time.time() - last) / 60}
        ps = [p for p in L.pods(job["namespace"]) if (p.get("status") or {}).get("phase") in ("Succeeded", "Failed")]
        ps.sort(key=lambda p: p["metadata"].get("creationTimestamp") or "")
        log = ""
        for p in reversed(ps[-3:]):
            try:
                log = L.pod_logs(job["namespace"], p["metadata"]["name"], tail=200)
            except Exception:
                continue
            if log.strip():
                break
        return job, log

    def _now_ip(self):
        url = self.opt("ip_url")
        if not url:
            return None
        b = self.request(url, timeout=5, raw=True).decode("utf-8", "replace")
        m = re.search(r"ip=" + _IP, b) or re.search(_IP, b)
        return m.group(1) if m else None

    def _resolve(self, names):
        out, res = {}, self.opt("resolver")
        for n in names:
            if n.startswith("*."):
                n2 = "bromigos-check." + n[2:]          # any name under a wildcard
            else:
                n2 = n
            try:
                if res:
                    d = json.loads(self.request(res + ("&" if "?" in res else "?") + urllib.parse.urlencode(
                        {"name": n2, "type": "A"}), timeout=5, raw=True, headers={"Accept": "application/dns-json"}))
                    a = [x.get("data") for x in d.get("Answer") or [] if x.get("type") == 1]
                    out[n] = a[0] if a else None
                elif self.opt("resolve", False):
                    out[n] = socket.gethostbyname(n2)
            except Exception:
                out[n] = None
        return out

    def _read(self):
        job, log = self._job()
        parsed = parse_ddns_log(log)
        now_ip = None
        try:
            now_ip = self._now_ip()
        except Exception:
            pass
        names = [r["name"] for r in parsed["records"] if not r.get("proxied")]
        resolved = self._resolve(names) if (self.opt("resolver") or self.opt("resolve")) else {}
        job_ok = not job.get("missing") and job.get("age_min") is not None and \
            job["age_min"] <= 3 * (job.get("every_min") or 60) + 10
        return job, parsed, now_ip, ddns_records(parsed, job_ok, job.get("last_success"), now_ip, resolved)

    def ddns(self):
        job, parsed, now_ip, recs = self._read()
        if job.get("missing"):
            raise Unreachable(f"{self.name}: {job['missing']}")
        return recs

    def doctor(self):
        job, parsed, now_ip, recs = self._read()
        return ddns_findings(recs, job, now_ip, parsed.get("public_ip"), self.name)


# ------------------------------------------------------------------ UniFi (UniFi Poller's metrics)
_KIND = {"udm": "gateway", "ugw": "gateway", "uxg": "gateway", "usw": "switch", "uap": "ap", "uck": "controller"}


def unifi_records(info, uptime, stations, wan_rx, wan_tx, wan_state, site_clients=None):
    """network records from unpoller rows: one per device, one per WAN link, one for the site."""
    up = {r["labels"].get("name"): r["value"] for r in uptime}
    st = {r["labels"].get("name"): r["value"] for r in stations}
    rx = {r["labels"].get("name"): r["value"] for r in wan_rx}
    tx = {r["labels"].get("name"): r["value"] for r in wan_tx}
    out = []
    for r in info:
        lb = r["labels"]
        n = lb.get("name")
        kind = _KIND.get(lb.get("type"), lb.get("type") or "device")
        rec = {"name": n, "kind": kind, "model": lb.get("model"), "up": (up.get(n) or 0) > 0,
               "clients": int(st[n]) if st.get(n) is not None else None,
               "rx_bps": rx[n] * 8 if rx.get(n) is not None else None,
               "tx_bps": tx[n] * 8 if tx.get(n) is not None else None,
               "uptime_s": up.get(n), "version": lb.get("version")}
        out.append(rec)
    for r in wan_state:
        lb = r["labels"]
        name = lb.get("wan_interface") or lb.get("wan_networkgroup") or "WAN"
        role = (lb.get("state") or "").lower()
        out.append({"name": name, "kind": "wan", "model": lb.get("wan_networkgroup"),
                    "up": (r["value"] or 0) > 0 or role == "backup", "clients": None, "rx_bps": None, "tx_bps": None,
                    "uptime_s": None, "version": None, "role": role,
                    "state": "ok" if (r["value"] or 0) > 0 or role == "backup" else "crit"})
    if site_clients is not None:
        gw = next((x for x in out if x["kind"] == "gateway"), {})
        out.append({"name": "site", "kind": "site", "model": None, "up": True, "clients": int(site_clients),
                    "rx_bps": gw.get("rx_bps"), "tx_bps": gw.get("tx_bps"), "uptime_s": None, "version": None})
    return out


def network_findings(recs, controller_up=None, source=None):
    out = []
    if controller_up is not None and not controller_up:
        out.append(L.finding("network.controller", "UniFi controller", "fail", "UniFi Poller can't reach it",
                             "unpoller can't log in to the controller: check its credentials and the console's "
                             "address in unpoller's config.", source))
    for r in recs:
        if r["kind"] == "wan" and r.get("state") == "crit":
            out.append(L.finding(f"network.wan.{r['name']}", f"WAN {r['name']}", "fail", "down",
                                 "This internet link is down: check the modem and the gateway's WAN port.", source))
        elif r["kind"] not in ("wan", "site") and not r["up"]:
            out.append(L.finding(f"network.{r['name']}", f"{r['name']} ({r['kind']})", "fail", "offline",
                                 f"{r['name']} is offline: check its power (PoE) and uplink cable.", source))
    if recs and not out:
        n = sum(1 for r in recs if r["kind"] not in ("wan", "site"))
        out.append(L.finding("network.all", "Network", "ok", f"{n} devices up", source=source))
    return out


@register
class UniFi(L.LabAdapter):
    type = "unifi"
    provides = ("network",)
    default_ports = (9130,)

    def probe(self):
        return b"unpoller_" in self.request("/metrics", timeout=3, raw=True)

    @classmethod
    def detect(cls, d):
        return [{"type": "unifi"}] if d.has_metric("unpoller_device_info") else []

    def _rows(self):
        names = ("unpoller_device_info", "unpoller_device_uptime_seconds", "unpoller_device_stations",
                 "unpoller_device_wan_receive_rate_bytes", "unpoller_device_wan_transmit_rate_bytes",
                 "unpoller_wan_interface_state", "unpoller_controller_up")
        if self.has_web():
            s = L.parse_prom(self.fetch("/metrics", raw=True))
            rows = {n: L.rows_of(s, n) for n in names}
            rows["clients"] = [{"labels": {}, "value": sum(r["value"] for r in L.rows_of(s, "unpoller_site_stations"))}]
        else:
            rows = {"unpoller_device_info": L.mq("unpoller_device_info")}
            for n in names[1:]:
                rows[n] = L.mq_soft(n)
            rows["clients"] = L.mq_soft("sum(unpoller_site_stations)")
        return rows

    def network(self):
        r = self._rows()
        clients = r["clients"][0]["value"] if r.get("clients") else None
        return unifi_records(r["unpoller_device_info"], r["unpoller_device_uptime_seconds"],
                             r["unpoller_device_stations"], r["unpoller_device_wan_receive_rate_bytes"],
                             r["unpoller_device_wan_transmit_rate_bytes"], r["unpoller_wan_interface_state"], clients)

    def doctor(self):
        r = self._rows()
        ctl = r.get("unpoller_controller_up")
        recs = unifi_records(r["unpoller_device_info"], r["unpoller_device_uptime_seconds"],
                             r["unpoller_device_stations"], r["unpoller_device_wan_receive_rate_bytes"],
                             r["unpoller_device_wan_transmit_rate_bytes"], r["unpoller_wan_interface_state"])
        return network_findings(recs, all((x["value"] or 0) > 0 for x in ctl) if ctl else None, self.name)
