"""Hypervisors and host monitors: Proxmox VE (hosts, workloads) and Netdata (metrics, hosts).

    [[source]]                                   [[source]]
    name = "proxmox"                             name = "netdata"
    type = "proxmox"                             type = "netdata"
    endpoint = "@private:endpoints.proxmox"      endpoint = "http://box:19999"
    auth_ref = "@vault:kv/homelab/proxmox#token" # user@realm!tokenid=secret (read-only role)
    tls_ca = "~/.config/homelab/homelab-ca.crt"  # or tls_verify = false for its own cert

Netdata has no PromQL: its `metrics` queries are `chart` or `chart.dimension`
(`system.cpu`, `system.ram.used`), each answering one series per dimension.
"""
import urllib.error
import urllib.parse

from ..registry import Adapter, register

# Proxmox's guest status -> the workloads schema's state
_PSTATE = {"running": "running", "stopped": "stopped", "paused": "stopped", "suspended": "stopped",
           "prelaunch": "pending"}


def _pct(used, total):
    try:
        return round(100.0 * float(used) / float(total), 1) if total else None
    except (TypeError, ValueError):
        return None


@register
class Proxmox(Adapter):
    """Proxmox VE's API (/api2/json) with an API token (PVEAPIToken; a read-only role is enough)."""
    type = "proxmox"
    provides = ("hosts", "workloads")
    default_ports = (8006,)
    default_scheme = "https"

    def auth_headers(self):
        from .. import config
        ref = self.opts.get("auth_ref")
        tok = config.resolve(ref) if ref else ""
        # the token is "user@realm!tokenid=secret"; Proxmox wants it after "PVEAPIToken="
        return {"Authorization": f"PVEAPIToken={tok}"} if tok else {}

    def _data(self, path, timeout=8):
        return (self.get_json("/api2/json" + path, timeout=timeout) or {}).get("data")

    def probe(self):
        try:
            d = self._data("/version", timeout=3)
            return isinstance(d, dict) and "version" in d
        except urllib.error.HTTPError as e:
            # unauthenticated: Proxmox answers 401 with its own realm (setup still adds it)
            return e.code == 401 and "PVE" in (e.headers.get("WWW-Authenticate") or "")

    def hosts(self):
        out = []
        for n in self._data("/nodes") or []:
            out.append({"name": n.get("node"), "up": n.get("status") == "online",
                        "cpu_pct": round(100.0 * float(n["cpu"]), 1) if n.get("cpu") is not None else None,
                        "mem_pct": _pct(n.get("mem"), n.get("maxmem")),
                        "disk_pct": _pct(n.get("disk"), n.get("maxdisk")),
                        "load1": None, "cores": n.get("maxcpu"), "uptime_s": n.get("uptime")})
        return out

    def workloads(self):
        out = []
        for r in self._data("/cluster/resources?type=vm") or []:
            out.append({"name": r.get("name") or f"{r.get('type')}/{r.get('vmid')}",
                        "namespace": r.get("pool"),
                        "kind": "vm" if r.get("type") == "qemu" else "container",
                        "state": _PSTATE.get(r.get("status"), "unknown"),
                        "restarts": None, "node": r.get("node"), "image": None,
                        "vmid": r.get("vmid"), "cpu_pct": round(100.0 * float(r.get("cpu") or 0), 1),
                        "mem_pct": _pct(r.get("mem"), r.get("maxmem"))})
        return out


@register
class Netdata(Adapter):
    """A Netdata agent or parent (/api/v1). Queries are `chart` or `chart.dimension`."""
    type = "netdata"
    provides = ("metrics", "hosts")
    default_ports = (19999,)

    def probe(self):
        i = self.get_json("/api/v1/info", timeout=3)
        return isinstance(i, dict) and "version" in i and "mirrored_hosts" in i

    def _series(self, chart, after, points):
        q = urllib.parse.urlencode({"chart": chart, "after": after, "points": points, "format": "json",
                                    "options": "seconds"})
        d = self.get_json("/api/v1/data?" + q, timeout=6) or {}
        labels, rows = d.get("labels") or [], d.get("data") or []
        return labels, rows                     # labels[0] == "time"; rows newest first

    def _split(self, q):
        """("system.ram", "used") for "system.ram.used" when that dimension exists, else (q, None)."""
        chart, _, dim = q.rpartition(".")
        if chart and "." in chart:
            return chart, dim
        return q, None

    def metrics_query(self, q, timeout=8):
        chart, dim = self._split(q)
        try:
            labels, rows = self._series(chart, -60, 1)
        except urllib.error.HTTPError:
            labels, rows = self._series(q, -60, 1)        # a chart name with a dot and no dimension
            chart, dim = q, None
        if not rows:
            return []
        row = rows[0]
        return [{"labels": {"chart": chart, "dimension": name}, "value": row[i], "t": row[0]}
                for i, name in enumerate(labels) if i and (dim is None or name == dim)]

    def metrics_range(self, q, minutes=60, step=60, timeout=10):
        chart, dim = self._split(q)
        labels, rows = self._series(chart, -int(minutes) * 60, max(1, int(minutes * 60 / step)))
        rows = list(reversed(rows))
        return [{"labels": {"chart": chart, "dimension": name}, "points": [[r[0], r[i]] for r in rows]}
                for i, name in enumerate(labels) if i and (dim is None or name == dim)]

    def _last(self, chart):
        labels, rows = self._series(chart, -10, 1)
        return dict(zip(labels[1:], rows[0][1:])) if rows else {}

    def hosts(self):
        info = self.get_json("/api/v1/info", timeout=6) or {}
        name = (info.get("mirrored_hosts") or [self.name])[0]
        cpu = self._last("system.cpu")                     # % per state; busy = everything but idle
        ram = self._last("system.ram")                     # MiB: free, used, cached, buffers
        load = self._last("system.load")
        disk = self._last("disk_space./")                  # GiB: avail, used, reserved for root
        total_ram = sum(v for v in ram.values() if isinstance(v, (int, float)))
        disk_total = sum(v for v in disk.values() if isinstance(v, (int, float)))
        return [{"name": name, "up": True,
                 "cpu_pct": round(sum(v for k, v in cpu.items() if k != "idle"), 1) if cpu else None,
                 "mem_pct": _pct(ram.get("used"), total_ram),
                 "disk_pct": _pct(disk.get("used"), disk_total),
                 "load1": load.get("load1"), "cores": info.get("cores_total")}]
