"""Storage: an S3 object store (RustFS, MinIO, …; storage and apps), the NAS and its NFS
volumes (storage), and the lab's databases' health (Redis / Dragonfly, Neo4j; apps).

    [[source]]
    type = "s3"
    endpoint = "http://s3.lab:9000"     # health from /health (RustFS) or /minio/health/live (MinIO)
    # access_key = "@private:s3.reader_id"          # with a read-only key: buckets, sizes, objects
    # auth_ref = "@file:~/.local/share/bromigos/s3-reader-secret"   (python-boto3)
    # scan_limit = 20000                # objects summed per bucket before it says "at least"

    [[source]]
    type = "nas"                        # NAS metrics in the metrics source: pools, shares, disks
    # label = "Media NAS"               # what the console's Storage card calls it (default: its name)
    # volume_classes = ["nfs-client"]   # PVCs of these storage classes (default: NFS-provisioned ones)

    [[source]]
    type = "dragonfly"                  # or "redis": endpoint = "redis://host:6379", else its pods
    [[source]]
    type = "neo4j"
    endpoint = "http://neo4j.lab:7474"

The NAS reads the volumes kubelet reports (kubelet_volume_stats_*, joined to their storage
class), and a NAS exporter's pools, shares, snapshots and disks when it has one
(nas_pool_*, nas_share_*, nas_disk_healthy, nas_up). The console's disk check and storage
card read these records' used / total; the doctor here adds the NAS's own health.
"""
import socket
import urllib.error

from .. import config
from ..registry import Unreachable, register
from . import labcommon as L

# ------------------------------------------------------------------ S3


def s3_health(d):
    """(up, detail) from RustFS's /health JSON."""
    if not isinstance(d, dict):
        return True, ""
    reasons = d.get("degradedReasons") or []
    bad = [k for k, v in (d.get("details") or {}).items() if isinstance(v, dict) and v.get("ready") is False]
    detail = "; ".join([str(r) for r in reasons] + [f"{k} not ready" for k in bad])
    return bool(d.get("ready", True)) and not bad, detail


@register
class S3(L.AppAdapter):
    type = "s3"
    hints = ("rustfs", "minio", "objects")  # setup --ingress: host names that suggest it
    provides = ("storage", "apps")
    kind = "object store"
    default_ports = (9000,)
    pod_selector = "app.kubernetes.io/name=rustfs"

    def probe(self):
        try:
            d = self.request("/health", timeout=3)
            svc = str(d.get("service", "")).lower() if isinstance(d, dict) else ""
            return "ready" in d and "rustfs" in svc and "console" not in svc
        except Exception:
            self.request("/minio/health/live", timeout=3, raw=True)
            return True

    def check(self):
        try:
            return s3_health(self.fetch("/health", timeout=5))
        except (urllib.error.HTTPError, ValueError):
            self.fetch("/minio/health/live", timeout=5, raw=True)
            return True, ""

    def _client(self):
        ak, sk = self.opt("access_key"), config.resolve(self.opts.get("auth_ref") or "")
        if not (ak and sk and self.endpoint):
            return None
        try:
            import boto3
            from botocore.config import Config
        except ImportError:
            raise Unreachable(f"{self.name}: bucket sizes need python-boto3") from None
        ca = config.expand(self.opts.get("tls_ca") or config.setting("tls", "ca_file", ""))
        verify = ca if ca else (False if self.opts.get("tls_verify") is False else True)
        return boto3.client("s3", endpoint_url=self.endpoint, aws_access_key_id=ak, aws_secret_access_key=sk,
                            region_name=self.opt("region", "us-east-1"), verify=verify,
                            config=Config(signature_version="s3v4", connect_timeout=5, read_timeout=15,
                                          retries={"max_attempts": 1}, s3={"addressing_style": "path"}))

    def storage(self):
        rows = L.mq_soft("minio_bucket_usage_total_bytes") if not self.has_web() or not self.opt("access_key") else []
        if rows:
            objs = L.keyed(L.mq_soft("minio_bucket_usage_object_total"), "bucket")
            return [{"name": r["labels"].get("bucket"), "kind": "bucket", "used": r["value"], "total": None,
                     "objects": objs.get(r["labels"].get("bucket")), "healthy": True, "state": "ok"} for r in rows]
        c = self._client()
        if c is None:
            return []                    # health only: no key to list buckets with
        limit = int(self.opt("scan_limit", 20000))
        out = []
        for b in c.list_buckets().get("Buckets") or []:
            size = n = 0
            more = False
            for page in c.get_paginator("list_objects_v2").paginate(Bucket=b["Name"], PaginationConfig={"PageSize": 1000}):
                for o in page.get("Contents") or []:
                    size += o.get("Size") or 0
                    n += 1
                if n >= limit:
                    more = bool(page.get("IsTruncated"))
                    break
            out.append({"name": b["Name"], "kind": "bucket", "used": size, "total": None, "objects": n,
                        "healthy": True, "state": "ok", "at_least": more})
        return out

    def doctor(self):
        out = super().doctor()
        if not self.opt("access_key") and not L.mq_soft("minio_bucket_usage_total_bytes"):
            out.append(self.finding(f"s3.{self.name}.buckets", f"{self.name}: buckets", "skip",
                                    "health only: no read-only key to list buckets with",
                                    "For bucket sizes, give the source access_key and auth_ref (a read-only key)."))
        return out


# ------------------------------------------------------------------ the NAS and its volumes


def nas_records(pools, pool_used, shares, quotas, volumes=None):
    """storage records: NAS pools (used/total), shares (used, with their quota as total), and
    volumes ({name, class, used, total})."""
    out = []
    used_by = {r["labels"].get("pool") or "NAS": r["value"] for r in pool_used}
    for r in pools:
        name = r["labels"].get("pool") or "NAS"
        used, total = used_by.get(name), r["value"]
        out.append({"name": name, "kind": "pool", "used": used, "total": total,
                    "used_pct": round(100.0 * used / total, 1) if used is not None and total else None})
    q = {r["labels"].get("share"): r["value"] for r in quotas}
    for r in shares:
        name = r["labels"].get("share")
        quota = q.get(name) or None
        out.append({"name": name, "kind": "share", "used": r["value"], "total": quota,
                    "used_pct": round(100.0 * r["value"] / quota, 1) if quota else None})
    for v in volumes or []:
        out.append(dict(v, kind="volume", used_pct=round(100.0 * v["used"] / v["total"], 1)
                        if v.get("used") is not None and v.get("total") else None))
    return out


def nas_findings(nas_up, disks, provisioner=None, source=None):
    """The NAS's own health: answering, its disks, the NFS provisioner (free space is the
    console's disk check, over these records)."""
    out = []
    if nas_up is not None and not nas_up:
        out.append(L.finding("nas.up", "NAS", "fail", "its exporter can't reach it",
                             "The NAS doesn't answer its exporter: check it's on and on the network.", source))
    for r in disks:
        if (r.get("value") or 0) < 1:
            lb = r["labels"]
            out.append(L.finding(f"nas.disk.{lb.get('slot') or lb.get('disk') or '?'}",
                                 f"NAS disk {lb.get('slot') or lb.get('disk') or '?'} ({lb.get('model') or '?'})", "fail",
                                 "unhealthy", "Replace it soon: the pool is running without its redundancy margin.", source))
    if provisioner is not None:
        up, detail = provisioner
        out.append(L.finding("nas.provisioner", "NFS provisioner", "ok" if up else "fail", detail,
                             "New NFS volumes can't be made: look at the provisioner's pod and its NFS mount.", source))
    if disks and not any(f["status"] != "ok" for f in out):
        out.append(L.finding("nas.disks", "NAS disks", "ok", f"{len(disks)} healthy", source=source))
    return out


@register
class NAS(L.LabAdapter):
    type = "nas"
    provides = ("storage",)

    @classmethod
    def detect(cls, d):
        if d.has_metric("nas_pool_total_bytes") or d.has_metric("nas_share_usage_bytes") or \
                d.pods("app=nfs-subdir-external-provisioner"):
            return [{"type": "nas"}]
        return []

    def _classes(self):
        want = self.opt("volume_classes")
        if want:
            return list(want)
        return [r["labels"].get("storageclass") for r in L.mq_soft('kube_storageclass_info{provisioner=~".*nfs.*"}')]

    def _volumes(self):
        classes = [c for c in self._classes() if c]
        if not classes:
            return []
        cls_re = "|".join(classes)
        info = {(r["labels"].get("namespace"), r["labels"].get("persistentvolumeclaim")): r["labels"].get("storageclass")
                for r in L.mq_soft(f'kube_persistentvolumeclaim_info{{storageclass=~"{cls_re}"}}')}
        used = L.keyed(L.mq_soft("kubelet_volume_stats_used_bytes"), "namespace", "persistentvolumeclaim")
        cap = L.keyed(L.mq_soft("kubelet_volume_stats_capacity_bytes"), "namespace", "persistentvolumeclaim")
        return [{"name": f"{ns}/{pvc}", "namespace": ns, "class": sc, "used": used.get((ns, pvc)), "total": cap.get((ns, pvc))}
                for (ns, pvc), sc in sorted(info.items()) if (ns, pvc) in cap]

    def storage(self):
        L.mq("vector(1)")                         # Unreachable without metrics
        recs = nas_records(L.mq_soft("nas_pool_total_bytes"), L.mq_soft("nas_pool_used_bytes"),
                           L.mq_soft("nas_share_usage_bytes"), L.mq_soft("nas_share_quota_bytes"), self._volumes())
        label = self.opt("label", self.name)      # what the console calls this NAS ("nas" by default)
        for r in recs:
            r["state"] = L.level(r.get("used_pct"), 85, 95) if r.get("used_pct") is not None else "ok"
            if r["kind"] in ("pool", "share"):
                r["nas"] = label
            if r.get("free") is None and r.get("used") is not None and r.get("total"):
                r["free"] = max(0.0, r["total"] - r["used"])
        return recs

    def _provisioner(self):
        if not L.kube():
            rows = L.mq_soft('kube_pod_status_ready{condition="true", pod=~".*nfs.*provisioner.*"}')
            if not rows:
                return None
            ok = sum(1 for r in rows if (r["value"] or 0) > 0)
            return ok == len(rows), f"{ok}/{len(rows)} pods ready"
        ps = L.pods(self.opt("provisioner_namespace"), self.opt("provisioner_selector", "app=nfs-subdir-external-provisioner"))
        if not ps:
            return None
        ok = sum(1 for p in ps if L.pod_ready(p))
        return ok == len(ps), f"{ok}/{len(ps)} pods ready"

    def doctor(self):
        up = L.mq_soft("nas_up")
        return nas_findings(all((r["value"] or 0) > 0 for r in up) if up else None, L.mq_soft("nas_disk_healthy"),
                            self._provisioner(), self.name)


# ------------------------------------------------------------------ Redis / Dragonfly (RESP over TCP)


def resp(host, port, commands, timeout=4):
    """Send RESP commands, then QUIT; the replies as text, read until the server closes."""
    with socket.create_connection((host, int(port)), timeout=timeout) as s:
        for c in list(commands) + ["QUIT"]:
            parts = [p.encode() for p in c.split(" ")]
            s.sendall(f"*{len(parts)}\r\n".encode() + b"".join(b"$%d\r\n%s\r\n" % (len(p), p) for p in parts))
        buf = b""
        while len(buf) < 1 << 20:
            chunk = s.recv(65536)
            if not chunk:
                break
            buf += chunk
        return buf.decode("utf-8", "replace")


@register
class Redis(L.AppAdapter):
    type = "redis"
    kind = "key-value store"
    default_ports = (6379,)
    pod_selector = "app.kubernetes.io/name=redis"

    def _addr(self):
        ep = self.endpoint.split("://", 1)[-1].rstrip("/")
        host, _, port = ep.rpartition(":")
        return (host, int(port)) if host and port.isdigit() else (ep, 6379)

    def has_web(self):
        return bool(self.endpoint)

    def _ask(self, cmds):
        host, port = self._addr()
        pw = config.resolve(self.opts.get("auth_ref") or "")
        try:
            return resp(host, port, ([f"AUTH {pw}"] if pw else []) + cmds)
        except OSError as e:
            raise Unreachable(f"{self.name}: {e}") from None

    def probe(self):
        r = self._ask(["PING"])
        return "+PONG" in r or "NOAUTH" in r

    def check(self):
        r = self._ask(["PING"])
        if "+PONG" in r:
            return True, ""
        return False, r.strip().split("\r\n")[0][:120]

    def version(self):
        r = self._ask(["INFO server"])
        for k in ("dragonfly_version", "redis_version", "valkey_version"):
            if k + ":" in r:
                return r.split(k + ":", 1)[1].split("\r\n", 1)[0]
        return None


@register
class Dragonfly(Redis):
    type = "dragonfly"
    pod_selector = "app.kubernetes.io/name=dragonfly"


# ------------------------------------------------------------------ Neo4j


@register
class Neo4j(L.AppAdapter):
    type = "neo4j"
    kind = "graph database"
    default_ports = (7474,)
    health_path = "/"
    pod_selector = "app=neo4j"

    def probe(self):
        d = self.request("/", timeout=3)
        return isinstance(d, dict) and ("neo4j_version" in d or "bolt_direct" in d)

    def check(self):
        d = self.fetch("/", timeout=5)
        return isinstance(d, dict) and ("bolt_direct" in d or "neo4j_version" in d or "transaction" in d), ""

    def version(self):
        d = self.fetch("/", timeout=5)
        return d.get("neo4j_version") if isinstance(d, dict) else None
