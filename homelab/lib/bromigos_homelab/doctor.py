"""`bromigos lab doctor`: checks on the lab, each with a fix in plain words.
docs/homelab.md, "The lab console".

A check yields findings:

    {"id": "tls.grafana", "check": "tls", "title": "TLS certificate of grafana.lab",
     "status": "ok" | "warn" | "fail" | "skip",
     "detail": "expires 2026-10-21 (in 12 days)",
     "fix": "what to do, in plain words",          # empty when status is ok
     "source": "prometheus"}                        # optional

Ways to add one (a homelab-adapter extension does the same as bromigOS):
  * a function:  @doctor.check("ups", "UPS battery", order=60, needs=("power",))
                 def ups(): yield doctor.finding(...)
    needs: capabilities; the check is skipped when none of them has a provider;
  * an adapter method doctor(self) -> [finding, …]: every configured source with one is
    asked (an exception is one "fail" finding: the source didn't answer).

Checks only read. Nothing here changes the lab, and nothing reads a secret's value: Vault
is asked for metadata (a token's expiry, a key's custom metadata), never a value.
"""
import concurrent.futures as cf
import datetime as dt
import json
import os
import shutil
import socket
import ssl
import subprocess
import time
import urllib.parse

from . import caps, config, registry

STATUSES = ("ok", "warn", "fail", "skip")
CHECKS = {}      # id -> {"id", "title", "order", "needs", "fn"}


def check(id, title, order=50, needs=()):
    """Register a check function (a generator or a function returning a list of findings).
    The first registration of an id wins."""
    def deco(fn):
        CHECKS.setdefault(id, {"id": id, "title": title, "order": order, "needs": tuple(needs), "fn": fn})
        return fn
    return deco


def finding(id, title, status, detail="", fix="", source=None, check=None):
    if status not in STATUSES:
        raise ValueError(f"finding {id}: status must be one of {STATUSES}")
    f = {"id": id, "check": check or id.split(".", 1)[0], "title": title, "status": status,
         "detail": detail or "", "fix": "" if status == "ok" else (fix or "")}
    if source:
        f["source"] = source
    return f


def _host(url):
    try:
        u = urllib.parse.urlsplit(url)
        return u.hostname, u.port or (443 if u.scheme == "https" else 80), u.scheme
    except ValueError:
        return None, None, None


def _endpoints():
    """(source name, url) for every configured source with an http(s) endpoint."""
    out = []
    for a in registry.instances():
        if a.endpoint.startswith(("http://", "https://")):
            out.append((a, a.endpoint))
    return out


# ------------------------------------------------------------------ DNS
@check("dns", "Lab services resolve", order=10)
def dns():
    seen = set()
    for a, url in _endpoints():
        host, _, _ = _host(url)
        if not host or host in seen:
            continue
        seen.add(host)
        try:
            socket.getaddrinfo(host, None)
            yield finding(f"dns.{host}", f"{host} resolves", "ok", f"{a.name}'s address", source=a.name)
        except socket.gaierror as e:
            yield finding(f"dns.{host}", f"{host} resolves", "fail", f"{a.name}: {e.strerror or e}",
                          f"This machine can't find {host}. Add it to your lab's DNS (or /etc/hosts), or point "
                          f"the {a.name!r} source in homelab.toml at an address that resolves.", source=a.name)


# ------------------------------------------------------------------ TLS
def cert_days(host, port, ca=None, timeout=5):
    """(days left, notAfter as a date, verified: bool, error) for host:port's certificate."""
    def handshake(ctx):
        with socket.create_connection((host, port), timeout=timeout) as s:
            with ctx.wrap_socket(s, server_hostname=host) as t:
                return t.getpeercert(), t.getpeercert(binary_form=True)
    ctx = ssl.create_default_context(cafile=ca) if ca and os.path.isfile(ca) else ssl.create_default_context()
    try:
        cert, _ = handshake(ctx)
        verified, err = True, None
    except ssl.SSLCertVerificationError as e:
        verified, err = False, e.verify_message or str(e)
        c2 = ssl.create_default_context()
        c2.check_hostname, c2.verify_mode = False, ssl.CERT_NONE
        _, der = handshake(c2)
        cert = _decode_der(der)
    if not cert or "notAfter" not in cert:
        return None, None, verified, err or "no certificate"
    end = dt.datetime.fromtimestamp(ssl.cert_time_to_seconds(cert["notAfter"]), dt.timezone.utc)
    return (end - dt.datetime.now(dt.timezone.utc)).days, end.date().isoformat(), verified, err


def _decode_der(der):
    """notAfter from a DER certificate without verifying it (the cryptography package when it's
    there; else nothing)."""
    try:
        from cryptography import x509
        c = x509.load_der_x509_certificate(der)
        end = c.not_valid_after_utc
        return {"notAfter": end.strftime("%b %d %H:%M:%S %Y GMT")}
    except Exception:
        return None


@check("tls", "TLS certificates", order=20)
def tls():
    seen = set()
    default_ca = config.expand(config.setting("tls", "ca_file", ""))
    for a, url in _endpoints():
        host, port, scheme = _host(url)
        if scheme != "https" or not host or (host, port) in seen:
            continue
        seen.add((host, port))
        ca = config.expand(a.opts.get("tls_ca") or "") or default_ca
        try:
            days, end, verified, err = cert_days(host, port, ca)
        except OSError as e:
            yield finding(f"tls.{host}", f"TLS certificate of {host}", "skip", f"didn't answer: {e}", source=a.name)
            continue
        if days is None:
            yield finding(f"tls.{host}", f"TLS certificate of {host}", "warn", err or "no certificate read",
                          "Couldn't read its certificate; check the service serves TLS on that port.", source=a.name)
            continue
        if days < 0:
            st, fix = "fail", (f"{host}'s certificate expired on {end}. Renew it (cert-manager: check the "
                               "Certificate and its issuer; Let's Encrypt: the ACME solver), then reload the service.")
        elif days < 7:
            st, fix = "fail", f"{host}'s certificate expires in {days} days. Renew it now; automatic renewal isn't working."
        elif days < 21:
            st, fix = "warn", (f"{host}'s certificate expires in {days} days. Automatic renewal normally runs 30 "
                               "days ahead: check that it is working.")
        else:
            st, fix = "ok", ""
        detail = f"expires {end} (in {days} days)"
        if not verified:
            st = "warn" if st == "ok" else st
            detail += f"; not trusted here: {err}"
            fix = fix or (f"This machine doesn't trust {host}'s certificate. Add your lab's CA as [tls] ca_file "
                          "(or the source's tls_ca) in homelab.toml.")
        yield finding(f"tls.{host}", f"TLS certificate of {host}", st, detail, fix, source=a.name)


# ------------------------------------------------------------------ GPUs
@check("gpu", "GPU driver and CUDA", order=30, needs=("metrics", "media", "hosts"))
def gpu():
    found = False
    if caps.available("metrics"):
        r = caps.metrics("DCGM_FI_DEV_GPU_TEMP", timeout=6)
        if r["ok"] and r["items"]:
            found = True
            for x in r["items"]:
                lb = x["labels"]
                host = lb.get("Hostname") or lb.get("hostname") or lb.get("instance") or "?"
                name = f"{lb.get('modelName', 'GPU')} on {host}"
                drv = lb.get("DCGM_FI_DRIVER_VERSION")
                yield finding(f"gpu.{host}.{lb.get('gpu', '0')}", name, "ok",
                              f"the driver sees it ({'driver ' + drv if drv else 'DCGM reports it'}), {x['value']:.0f} °C")
        elif r["ok"]:
            n = caps.scalar("count(nvidia_smi_gpu_info) or count(node_drm_card_info)", None)
            if n:
                found = True
                yield finding("gpu.exporter", "GPUs (node exporter)", "ok", f"{int(n)} GPU(s) reported")
    m = caps.media()
    for x in m["items"]:
        found = True
        gpu_name = x.get("gpu") or ""
        if "cuda" in gpu_name.lower() or (x.get("vram_total") or 0) > 0:
            dev = gpu_name.split(" : ")[0]
            dev = dev.split(" ", 1)[1] if dev.startswith("cuda:") and " " in dev else dev
            yield finding(f"gpu.{x['source']}", f"{x['source']} sees its GPU", "ok", dev or "a GPU",
                          source=x["source"])
        else:
            yield finding(f"gpu.{x['source']}", f"{x['source']} sees its GPU", "fail", f"it reports {gpu_name or 'no device'}",
                          f"{x['source']} is running without CUDA: check the NVIDIA driver and the container "
                          "toolkit on its node, and that the pod requests the GPU (nvidia.com/gpu).",
                          source=x["source"])
    for s, e in m["errors"].items():
        yield finding(f"gpu.{s}", f"{s} sees its GPU", "skip", f"didn't answer ({e})", source=s)
    if not found:
        yield finding("gpu.none", "GPUs", "skip", "no GPU readings: no DCGM exporter in the metrics and no media server",
                      "To see GPUs, scrape NVIDIA's DCGM exporter in Prometheus (or add a Netdata source on the GPU box).")


# ------------------------------------------------------------------ disks and NAS
@check("disk", "Disk and NAS space", order=40, needs=("hosts", "metrics", "storage"))
def disk():
    warn = float(config.setting("console", "disk_warn_pct", 85))
    crit = float(config.setting("console", "disk_crit_pct", 95))
    h = caps.hosts()
    seen = set()
    for x in h["items"]:
        p = x.get("disk_pct")
        if p is None or x.get("name") in seen:
            continue
        seen.add(x.get("name"))
        st = "fail" if p >= crit else "warn" if p >= warn else "ok"
        yield finding(f"disk.{x['name']}", f"{x['name']}'s root disk", st, f"{p:.0f}% used",
                      f"{x['name']}'s root disk is {p:.0f}% full. Free space (old images, logs, caches) or grow "
                      "the disk; Kubernetes starts evicting pods near 90%.", source=x.get("source"))
    if caps.available("metrics"):
        q = ('100*(1-node_filesystem_avail_bytes{fstype=~"nfs.*|cifs|smb.*"}'
             '/node_filesystem_size_bytes{fstype=~"nfs.*|cifs|smb.*"})')
        r = caps.metrics(q, timeout=6)
        done = set()
        for x in r["items"]:
            lb = x["labels"]
            mp = lb.get("mountpoint") or "?"
            dev = lb.get("device") or mp
            if dev in done or x["value"] is None:
                continue
            done.add(dev)
            p = x["value"]
            st = "fail" if p >= crit else "warn" if p >= warn else "ok"
            yield finding(f"nas.{dev}", f"NAS share {dev}", st, f"{p:.0f}% used (mounted at {mp})",
                          f"The share {dev} is {p:.0f}% full. Free space on the NAS or grow its pool before "
                          "backups and media start failing.")
    if caps.available("storage"):
        s = caps.collect("storage")
        for x in s["items"]:
            used, total = x.get("used"), x.get("total")
            p = x.get("used_pct") if x.get("used_pct") is not None else (100.0 * used / total if used and total else None)
            if p is None:
                continue
            st = "fail" if p >= crit else "warn" if p >= warn else "ok"
            yield finding(f"storage.{x.get('name')}", f"{x.get('name')} ({x.get('kind') or 'storage'})", st,
                          f"{p:.0f}% used", f"{x.get('name')} is {p:.0f}% full: free space or grow it.",
                          source=x.get("source"))
        for src, e in s["errors"].items():
            yield finding(f"storage.{src}", f"{src}", "fail", e, f"{src} didn't answer: check it is up.", source=src)


# ------------------------------------------------------------------ backups
@check("backups", "Backups are recent", order=50, needs=("backups",))
def backups():
    """A `backups` capability (records: name, last_success as unix seconds or ISO 8601, ok,
    max_age_hours) from a backup source; skipped without one."""
    r = caps.collect("backups")
    now = time.time()
    for x in r["items"]:
        last = _ts(x.get("last_success"))
        limit = float(x.get("max_age_hours") or config.setting("console", "backup_max_age_hours", 30))
        name = x.get("name") or x.get("source")
        if last is None:
            yield finding(f"backups.{name}", f"Backup {name}", "fail", "never succeeded",
                          f"{name} has no successful backup. Run it by hand once and read its log.", source=x.get("source"))
            continue
        age = (now - last) / 3600
        st = "ok" if age <= limit and x.get("ok", True) is not False else ("warn" if age <= 2 * limit else "fail")
        yield finding(f"backups.{name}", f"Backup {name}", st, f"last good backup {age:.0f} h ago",
                      f"{name}'s last good backup is {age:.0f} hours old (expected every {limit:.0f} h). "
                      "Check its schedule and its last run's log.", source=x.get("source"))
    for src, e in r["errors"].items():
        yield finding(f"backups.{src}", f"Backups ({src})", "fail", e, f"{src} didn't answer: check it is up.", source=src)


def _ts(v):
    if v is None or v == "":
        return None
    if isinstance(v, (int, float)):
        return float(v)
    try:
        return dt.datetime.fromisoformat(str(v).replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


# ------------------------------------------------------------------ Argo / GitOps drift
@check("argo", "GitOps apps in sync and healthy", order=60, needs=("deployments",))
def argo():
    d = caps.deployments()
    from .console import _visible, hidden
    pats = hidden()
    bad = 0
    for x in d["items"]:
        if not _visible(x, pats):
            continue
        name = x.get("name")
        if x.get("health") in ("degraded", "missing"):
            bad += 1
            yield finding(f"argo.{name}", f"{name}", "fail", f"health {x['health']}, sync {x.get('sync')}",
                          f"{name} is {x['health']}: its pods aren't running as the repo says. Look at its pods' "
                          f"events and logs (kubectl --context <yours> -n {x.get('namespace') or '<ns>'} get pods); "
                          "fix it in the homelab repo and let Argo sync. Never patch Argo's state by hand.",
                          source=x.get("source"))
        elif x.get("sync") == "out_of_sync":
            bad += 1
            yield finding(f"argo.{name}", f"{name}", "warn", f"out of sync (health {x.get('health')})",
                          f"The cluster's {name} differs from the homelab repo. If someone changed it by hand, put "
                          "that change in the repo; otherwise sync it in Argo CD. Never patch Argo's state directly.",
                          source=x.get("source"))
    if d["ok"] and not bad:
        yield finding("argo.all", "GitOps apps", "ok", f"{len(d['items'])} apps synced and healthy")
    for src, e in d["errors"].items():
        yield finding(f"argo.{src}", f"GitOps apps ({src})", "fail", e,
                      f"{src} didn't answer: check Argo CD (or its metrics) is up.", source=src)


# ------------------------------------------------------------------ tokens (Vault metadata only)
def _vault(args, timeout=8):
    if not shutil.which("vault"):
        return None
    try:
        p = subprocess.run(["vault"] + args, capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired):
        return None
    if p.returncode != 0:
        return None
    try:
        return json.loads(p.stdout)
    except ValueError:
        return None


@check("tokens", "Tokens that expire", order=70)
def tokens():
    """The vault CLI's own login token's expiry (token lookup: only ttl and expire_time are
    kept; the token itself is dropped before anything else sees it), and each [console]
    tokens entry's Vault KV metadata (custom_metadata expires = "YYYY-MM-DD"). Never a value."""
    entries = config.setting("console", "tokens", []) or []
    if shutil.which("vault") and (os.environ.get("VAULT_ADDR") or entries):
        d = _vault(["token", "lookup", "-format=json"])
        if d is not None:
            data = d.get("data") or {}
            meta = {"ttl": data.get("ttl"), "expire_time": data.get("expire_time")}
            d = data = None                                 # nothing else of it is kept
            ttl = meta["ttl"]
            if ttl in (0, None) and not meta["expire_time"]:
                yield finding("tokens.vault-login", "Your Vault login", "ok", "doesn't expire")
            else:
                days = (ttl or 0) / 86400
                st = "fail" if days < 1 else "warn" if days < 7 else "ok"
                yield finding("tokens.vault-login", "Your Vault login", st, f"expires in {days:.1f} days",
                              "Log in to Vault again (vault login) before it expires; @vault: references in "
                              "homelab.toml stop resolving when it does.")
    for e in entries:
        if not isinstance(e, dict) or not e.get("vault"):
            continue
        name = e.get("name") or e["vault"]
        path = e["vault"].split("#", 1)[0]
        m = _vault(["kv", "metadata", "get", "-format=json", path])
        if m is None:
            yield finding(f"tokens.{name}", f"Token: {name}", "skip", "Vault didn't answer for its metadata",
                          "Check `vault login` and that this path exists (only its metadata is read).")
            continue
        cm = ((m.get("data") or {}).get("custom_metadata") or {})
        exp = cm.get(e.get("field") or "expires") or cm.get("expires_at")
        if not exp:
            yield finding(f"tokens.{name}", f"Token: {name}", "skip", "no expiry recorded in its metadata",
                          f"Record it once: vault kv metadata patch -custom-metadata=expires=YYYY-MM-DD {path}")
            continue
        when = _ts(exp)
        if when is None:
            yield finding(f"tokens.{name}", f"Token: {name}", "warn", f"expiry {exp!r} isn't a date",
                          "Write it as YYYY-MM-DD.")
            continue
        days = (when - time.time()) / 86400
        st = "fail" if days < 3 else "warn" if days < 14 else "ok"
        yield finding(f"tokens.{name}", f"Token: {name}", st, f"expires {exp} (in {days:.0f} days)",
                      f"Make a new {name}, store it at the same Vault path, and update its expires metadata.")


# ------------------------------------------------------------------ targets.toml
@check("targets", "Where AI runs points at live services", order=80)
def targets():
    """`bromigos target --json`: each service's first answering target. A homelab target
    that doesn't answer, ahead of what the service uses, is a finding; a fallback behind it
    that the lab doesn't have (an older workflow kept for other ComfyUIs) is not."""
    exe = shutil.which("bromigos") or "/usr/bin/bromigos"
    if not os.path.exists(exe):
        return
    try:
        p = subprocess.run([exe, "target", "--json"], capture_output=True, text=True, timeout=30)
        doc = json.loads(p.stdout)
    except (OSError, subprocess.TimeoutExpired, ValueError):
        yield finding("targets.read", "targets.toml", "skip", "bromigos target --json didn't answer")
        return
    for svc in doc.get("services") or []:
        name = svc.get("service") or svc.get("name")
        entries = svc.get("entries") or []
        uses = svc.get("uses") or {}
        first_ok = next((i for i, e in enumerate(entries) if e.get("ok")), len(entries))
        bad_home = [e for e in entries[:first_ok] if e.get("target") == "homelab" and e.get("ok") is False]
        if bad_home:
            e = bad_home[0]
            yield finding(f"targets.{name}", f"{name} on the homelab", "warn",
                          f"{e.get('engine') or 'the homelab'}: {e.get('detail') or 'does not answer'}; "
                          f"using {uses.get('engine') or 'nothing'}",
                          f"targets.toml sends {name} to the homelab first, but it doesn't answer. Check the "
                          "service (bromigos lab status), or see the order with `bromigos lab target`; "
                          "`bromigos lab connect` finds services again.")
        elif uses:
            paid = uses.get("target") == "cloud"
            yield finding(f"targets.{name}", f"{name}", "ok",
                          f"runs on {uses.get('target')}: {uses.get('engine')}" + (" (costs credits)" if paid else ""))
        else:
            yield finding(f"targets.{name}", f"{name}", "warn", "no target answers",
                          f"Nothing can run {name} now: start its service, or change the order with "
                          "`bromigos lab target`.")


# ------------------------------------------------------------------ the sources themselves
@check("sources", "Every source answers", order=5)
def sources():
    for c in registry.CAPABILITIES:
        if c == "metrics" or not caps.available(c):
            continue
        r = caps.collect(c)
        for s, e in r["errors"].items():
            yield finding(f"sources.{s}.{c}", f"{s} ({c})", "fail", e,
                          f"{s} didn't answer for {c}. Check the service is up and its endpoint in homelab.toml "
                          "(bromigos homelab status shows it).", source=s)
    if caps.available("metrics"):
        r = caps.metrics("up", timeout=6)
        for s, e in r["errors"].items():
            yield finding(f"sources.{s}.metrics", f"{s} (metrics)", "fail", e,
                          f"{s} didn't answer a metrics query: check it is up.", source=s)


# ------------------------------------------------------------------ running them
def _run_one(c):
    try:
        out = list(c["fn"]() or [])
    except Exception as e:
        return [finding(f"{c['id']}.error", c["title"], "fail", f"{type(e).__name__}: {str(e)[:200]}",
                        "The check itself failed; run `bromigos lab doctor --json` and report it.", check=c["id"])]
    for f in out:
        f.setdefault("check", c["id"])
    return out


def _adapter_findings(a):
    try:
        out = []
        for f in a.doctor() or []:
            f = dict(f)
            f.setdefault("check", a.type)
            f.setdefault("source", a.name)
            if f.get("status") not in STATUSES:
                f["status"] = "warn"
            f.setdefault("fix", "")
            f.setdefault("detail", "")
            out.append(f)
        return out
    except Exception as e:
        return [finding(f"{a.name}.doctor", f"{a.name}", "fail", caps._why(e),
                        f"{a.name} didn't answer its checks: check it is up and its endpoint in homelab.toml.",
                        source=a.name, check=a.type)]


def run(only=None, timeout=45):
    """Every check: {"generatedAt", "findings", "summary": {ok, warn, fail, skip}, "checks"}.
    only: a set of check ids. A check that needs capabilities nobody provides is skipped."""
    insts = registry.instances()
    t0 = time.time()
    todo = [c for c in sorted(CHECKS.values(), key=lambda c: c["order"])
            if (not only or c["id"] in only) and (not c["needs"] or any(caps.available(n) for n in c["needs"]))]
    adapters = [a for a in insts if callable(getattr(a, "doctor", None))] if not only else []
    findings, ran = [], []
    with cf.ThreadPoolExecutor(8) as ex:
        futs = [(c["id"], ex.submit(_run_one, c)) for c in todo] + \
               [(a.name, ex.submit(_adapter_findings, a)) for a in adapters]
        for cid, f in futs:
            try:
                findings += f.result(timeout=max(1.0, timeout - (time.time() - t0)))
            except cf.TimeoutError:
                findings.append(finding(f"{cid}.timeout", cid, "fail", f"no answer within {timeout} s",
                                        "Something it reads is slow or hanging; run that check alone to see which.",
                                        check=cid))
            ran.append(cid)
    seen, uniq = set(), []
    for f in findings:                      # a finding id once (an adapter and a check can meet)
        if f["id"] in seen:
            continue
        seen.add(f["id"])
        uniq.append(f)
    order = {"fail": 0, "warn": 1, "skip": 3, "ok": 2}
    summary = {s: sum(1 for f in uniq if f["status"] == s) for s in STATUSES}
    return {"generatedAt": int(t0), "seconds": round(time.time() - t0, 2), "checks": ran,
            "summary": summary, "findings": sorted(uniq, key=lambda f: (order[f["status"]], f["check"], f["id"])),
            "configured": bool(insts)}
