"""__TITLE__: a homelab adapter (made by `bromigos ext new homelab-adapter`;
docs/homelab.md, "Adapters").

An adapter is code that talks to one kind of service and provides capabilities (hosts,
metrics, workloads, …: bromigos_homelab/caps.py has every record's fields). This one
needs no service: it reports this machine as a host. Turn it on in homelab.toml:

    [[source]]
    type = "__IDENT__"

then VECTOR's homelab tools and the desktop's panels see it (bromigos restart vector,
bromigos restart widgets). For a real service: set default_ports, write probe() (so
`bromigos setup homelab` finds it), and use self.get_json(path) against self.endpoint
(the source's TLS and auth_ref are applied for you).
"""
import os
import shutil
import socket
import time

from bromigos_homelab.registry import Adapter, register


def _cpu_times():
    with open("/proc/stat") as f:
        v = [int(x) for x in f.readline().split()[1:]]
    return sum(v), v[3] + v[4]          # total, idle + iowait


@register
class __CAMEL__(Adapter):
    type = "__IDENT__"
    provides = ("hosts",)
    local = True                         # no endpoint: it reads this machine

    def hosts(self):
        t0, i0 = _cpu_times()
        time.sleep(0.2)
        t1, i1 = _cpu_times()
        cpu = 100.0 * (1 - (i1 - i0) / max(t1 - t0, 1))
        mem = {}
        with open("/proc/meminfo") as f:
            for line in f:
                k, v = line.split(":", 1)
                mem[k] = int(v.split()[0])
        du = shutil.disk_usage("/")
        return [{"name": socket.gethostname(), "up": True, "cpu_pct": round(cpu, 1),
                 "mem_pct": round(100.0 * (1 - mem.get("MemAvailable", 0) / max(mem.get("MemTotal", 1), 1)), 1),
                 "disk_pct": round(100.0 * du.used / du.total, 1), "load1": round(os.getloadavg()[0], 2),
                 "cores": os.cpu_count()}]
