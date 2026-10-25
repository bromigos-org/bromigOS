"""Find my lab: the devices this computer, and the lab you already connected, know about
(`bromigos setup homelab --find`; docs/homelab.md, "Find my lab").

Nothing here sweeps an address range or contacts a host nobody told us about. It reads
three kinds of sources, each read-only, after the user says yes once:

  1. devices that announce themselves: an mDNS/DNS-SD browse (python-zeroconf, optional),
     an SSDP M-SEARCH and an ONVIF WS-Discovery probe. Each is one multicast question that
     a device answers only if it chooses to;
  2. what this computer knows: its neighbour table (`ip -j neigh`, else /proc/net/arp), the
     names its own resolver gives those addresses, `tailscale status --json`, and, after a
     separate yes, the Host lines of ~/.ssh/config (never keys, known_hosts or any other
     file under ~/.ssh);
  3. what the lab knows, through the sources already in homelab.toml and their adapters
     (their own credential references, nothing else): UniFi Poller's clients, Prometheus's
     scrape targets, Kubernetes nodes and Proxmox VMs' guest-agent addresses.

merge() makes one record per host, classify() names its kind, and check() runs setup's own
per-host identification (host_finds) on those hosts only, at private addresses only.
No MAC address or serial number is kept: they never reach a record, so they never reach
the output or a file.
"""
import concurrent.futures as cf
import contextlib
import ipaddress
import json
import os
import re
import shutil
import socket
import subprocess
import threading
import time
import urllib.parse
import urllib.request
import uuid
import xml.etree.ElementTree as ET

KINDS = ("lab machine", "smart home", "camera", "robot", "printer", "media", "other")
# a host's kind is its first product's in this order (a NAS that also runs Plex is a lab machine)
_PRIORITY = ("camera", "robot", "printer", "lab machine", "smart home", "media", "other")
# kinds whose hosts setup checks (and any host with a product an adapter knows, such as Plex):
# nothing bromigOS adds runs on a camera, a printer, a plug or a media player
CHECKED = ("lab machine", "other")

SOURCES = {"mdns": "mDNS", "ssdp": "UPnP", "wsd": "camera discovery", "neighbours": "neighbour table",
           "router": "default route", "dns": "DNS", "tailscale": "Tailscale", "ssh": "SSH config",
           "unifi": "UniFi", "prometheus": "Prometheus", "kubernetes": "Kubernetes", "proxmox": "Proxmox"}
# which source's name a host goes by, best first
_NAMED_BY = ("ssh", "dns", "tailscale", "mdns", "kubernetes", "proxmox", "unifi", "prometheus", "wsd", "ssdp")

# The addresses a check may reach: RFC 1918, IPv6 unique local, and CGNAT on a tailnet only.
PRIVATE = tuple(ipaddress.ip_network(n) for n in ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16", "fc00::/7"))  # privacy: allow
TAILNET = (ipaddress.ip_network("100.64.0.0/10"),)

# What a device says about itself (its mDNS service type, its UPnP headers, its name), and
# what that makes it. Names are only hints: an adapter's own check decides what's added.
PRODUCTS = [
    (r"_bromigos-lab\._tcp", "bromigOS lab box", "lab machine"),
    (r"_home-assistant\._tcp|home.?assistant", "Home Assistant", "smart home"),
    (r"_mqtt\._tcp|mosquitto", "MQTT broker", "smart home"),
    (r"_esphomelib\._tcp|esphome", "ESPHome", "smart home"),
    (r"_matterc?\._(?:tcp|udp)", "Matter", "smart home"),
    (r"_hap\._(?:tcp|udp)", "HomeKit", "smart home"),
    (r"_hue\._tcp|ipbridge|hue-bridgeid|philips.?hue", "Hue bridge", "smart home"),
    (r"_shelly\._tcp|shelly", "Shelly", "smart home"),
    (r"_googlecast\._tcp|chromecast", "Chromecast", "media"),
    (r"_airplay\._tcp|_raop\._tcp", "AirPlay", "media"),
    (r"_ipps?\._tcp|_printer\._tcp|_pdl-datastream\._tcp|_uscan\._tcp|device:printer", "printer", "printer"),
    (r"synology|diskstation", "Synology NAS", "lab machine"),
    (r"truenas|freenas", "TrueNAS", "lab machine"),
    (r"unraid", "Unraid", "lab machine"),
    (r"openmediavault", "OpenMediaVault", "lab machine"),
    (r"_smb\._tcp|_afpovertcp\._tcp|_adisk\._tcp|_nfs\._tcp", "file shares", "lab machine"),
    (r"proxmox|\bpve\d*\b", "Proxmox", "lab machine"),
    (r"cockpit", "Cockpit", "lab machine"),
    (r"jellyfin", "Jellyfin", "media"),
    (r"_plexmediasvr\._tcp|plex media server|\bplex\b", "Plex", "media"),
    (r"onvif|networkvideotransmitter", "ONVIF camera", "camera"),
    (r"_rtsp\._tcp", "RTSP camera", "camera"),
    (r"frigate", "Frigate", "camera"),
    (r"rosbridge|_ros\w*\._tcp", "rosbridge", "robot"),
    (r"foxglove", "Foxglove bridge", "robot"),
    (r"_ssh\._tcp|_sftp-ssh\._tcp|_workstation\._tcp", "computer", "other"),
]
_PRODUCTS = [(re.compile(p, re.I), name, kind) for p, name, kind in PRODUCTS]
# products an adapter covers: found by setup's check, not listed as "not supported yet"
ADAPTER_OF = {"Proxmox": "proxmox", "Jellyfin": "jellyfin", "Plex": "plex", "computer": None, "router": None,
              "bromigOS lab box": None}

# mDNS service types browsed even when nothing lists them under _services._dns-sd._udp
MDNS_TYPES = ("_bromigos-lab._tcp", "_home-assistant._tcp", "_mqtt._tcp", "_esphomelib._tcp", "_matter._tcp",
              "_matterc._udp", "_hap._tcp", "_hue._tcp", "_shelly._tcp", "_googlecast._tcp", "_airplay._tcp",
              "_raop._tcp", "_ipp._tcp", "_ipps._tcp", "_printer._tcp", "_smb._tcp", "_afpovertcp._tcp",
              "_adisk._tcp", "_nfs._tcp", "_plexmediasvr._tcp", "_rtsp._tcp", "_ssh._tcp", "_workstation._tcp",
              "_http._tcp", "_https._tcp")
_MDNS_TYPE = re.compile(r"^_[a-z0-9-]{1,40}\._(?:tcp|udp)\.local\.$", re.I)
# the TXT keys kept: names and models; never an id, a MAC, a serial or a key
TXT_KEEP = ("fn", "md", "ty", "model", "vendor", "product", "am", "usb_MDL")

# a MAC address or a bare 12-digit hex id, wherever a device puts one in a name
_MAC = re.compile(r"(?i)(?<![0-9a-f])(?:[0-9a-f]{2}[:-]){5}[0-9a-f]{2}(?![0-9a-f])|(?<![0-9a-z])[0-9a-f]{12}(?![0-9a-z])")
# interfaces whose neighbours are this machine's containers, not devices on the network
_LOCAL_IF = re.compile(r"^(?:lo|docker\d*|br-|veth|cni|flannel|cali|vxlan|kube|tailscale|wg)")
_DEAD = {"FAILED", "INCOMPLETE", "NOARP"}


def scrub(s):
    """A name with any MAC address or 12-digit hex id cut out."""
    return re.sub(r"[-_ ]+$", "", _MAC.sub("", str(s or ""))).strip()


def ip_of(addr):
    try:
        ip = ipaddress.ip_address(str(addr).split("%", 1)[0].strip("[]"))
    except ValueError:
        return None
    return ip.ipv4_mapped if ip.version == 6 and ip.ipv4_mapped else ip


def allowed(addr, tailnet=False):
    """True for a private address: RFC 1918 or IPv6 unique local, and CGNAT only on a tailnet."""
    ip = ip_of(addr)
    if ip is None:
        return False
    return any(ip in n for n in PRIVATE) or (tailnet and any(ip in n for n in TAILNET))


def short(name):
    """"nas.example.org." -> "nas": the label that ties a host's names together."""
    s = str(name or "").strip().rstrip(".").lower()
    if not s or ip_of(s) is not None:
        return ""
    s = s.split(".", 1)[0]
    return "" if len(s) < 2 or s.startswith("_") or s in ("localhost", "gateway", "local") else s


def obs(source, addresses=(), names=(), label="", says="", tailnet=False, online=None, products=()):
    """One sighting: a source saw these addresses, under these names. `says` is what the device
    announced (matched against PRODUCTS); `label` a friendly name to show."""
    return {"source": source, "addresses": [str(a).split("%", 1)[0] for a in addresses if a],
            "names": [scrub(n).strip(".") for n in names if short(scrub(n).strip("."))], "label": scrub(label),
            "says": _MAC.sub("", says),
            "tailnet": tailnet, "online": online, "products": list(products)}


# ------------------------------------------------------------------ 1. devices that announce themselves


def txt_parse(raw):
    """{key: value} from a TXT record's length-prefixed strings, only the keys in TXT_KEEP."""
    out, i = {}, 0
    raw = raw or b""
    while i < len(raw):
        n = raw[i]
        item = raw[i + 1:i + 1 + n].decode("utf-8", "replace")
        i += 1 + n
        k, _, v = item.partition("=")
        if k in TXT_KEEP and v:
            out[k] = scrub(v)
    return out


def mdns_services(records):
    """[{type, instance, server, port, addresses, txt}] from mDNS records: zeroconf's
    DNSRecords, or anything with the same fields (type, name, alias, server, port, text,
    address)."""
    ptr, srv, txt, addr = {}, {}, {}, {}
    for r in records:
        name = str(r.name).lower()
        if r.type == 12 and name != "_services._dns-sd._udp.local.":
            ptr.setdefault(str(r.alias), name)
        elif r.type == 33:
            srv[name] = (str(r.server), int(r.port))
        elif r.type == 16:
            txt[name] = txt_parse(r.text)
        elif r.type in (1, 28):
            try:
                a = socket.inet_ntop(socket.AF_INET if r.type == 1 else socket.AF_INET6, bytes(r.address))
            except (OSError, ValueError, TypeError):
                continue
            addr.setdefault(name, set()).add(a)
    out = []
    for inst, type_ in sorted(ptr.items()):
        server, port = srv.get(inst.lower(), ("", 0))
        out.append({"type": type_.removesuffix(".local."), "instance": scrub(inst[:-len(type_)].rstrip(".")),
                    "fullname": inst,                   # to ask for it by name; never shown or written
                    "server": server.rstrip("."), "port": port, "addresses": sorted(addr.get(server.lower(), ())),
                    "txt": txt.get(inst.lower(), {})})
    return out


def mdns_types(records):
    """The service types devices listed under _services._dns-sd._udp (valid names only)."""
    return {str(r.alias) for r in records if r.type == 12 and str(r.name).lower() == "_services._dns-sd._udp.local."
            and _MDNS_TYPE.match(str(r.alias))}


def mdns_observations(services):
    out = []
    for s in services:
        if not s["addresses"]:
            continue
        says = " ".join([s["type"], s["instance"], s["server"]] + list(s["txt"].values()))
        out.append(obs("mdns", s["addresses"], [s["server"]], label=s["txt"].get("fn") or s["instance"], says=says))
    return out


def mdns_listen(seconds=3.0):
    """The mDNS records heard while browsing for `seconds`, or None without python-zeroconf.
    It asks the multicast group which services there are, then for each type; only devices
    that announce themselves answer."""
    try:
        import zeroconf as Z
    except ImportError:
        return None

    def noop(**_kw):
        pass

    def heard(zc):
        return [r for n in list(zc.cache.names()) for r in zc.cache.entries_with_name(n)]

    zc = Z.Zeroconf()
    browsers = []
    try:
        browsers.append(Z.ServiceBrowser(zc, "_services._dns-sd._udp.local.", handlers=[noop]))
        time.sleep(min(1.0, seconds / 3))
        types = sorted({t + ".local." for t in MDNS_TYPES} | set(list(mdns_types(heard(zc)))[:64]))
        browsers.append(Z.ServiceBrowser(zc, types, handlers=[noop]))
        time.sleep(seconds)
        # an instance that answered its pointer but not yet its address: ask it once, by name
        for s in [s for s in mdns_services(heard(zc)) if not s["addresses"]][:40]:
            with contextlib.suppress(Exception):
                Z.ServiceInfo(s["type"] + ".local.", s["fullname"]).request(zc, 500)
        return heard(zc)
    finally:
        for b in browsers:
            with contextlib.suppress(Exception):
                b.cancel()
        zc.close()


SSDP = ("239.255.255.250", 1900)
SEARCH = ("M-SEARCH * HTTP/1.1\r\nHOST: 239.255.255.250:1900\r\nMAN: \"ssdp:discover\"\r\nMX: 2\r\n"
          "ST: ssdp:all\r\n\r\n").encode()


def ssdp_parse(data, source):
    """An SSDP answer from `source` as a sighting (its type and server line; never its USN,
    which carries the device's id)."""
    text = data[:8192].decode("utf-8", "replace")
    lines = text.replace("\r\n", "\n").split("\n")
    if not lines or not lines[0].upper().startswith(("HTTP/1.1 200", "NOTIFY")):
        return None
    h = {}
    for line in lines[1:]:
        k, sep, v = line.partition(":")
        if sep:
            h[k.strip().lower()] = v.strip()
    says = " ".join([h.get("st", ""), h.get("nt", ""), h.get("server", "")] + [k for k in h if k.startswith("hue-")])
    return obs("ssdp", [source], says=says)


def _multicast(group, payload, seconds, parse, ttl=2):
    """Send one multicast question and collect the answers for `seconds`."""
    out = []
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
    try:
        s.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, ttl)
        s.settimeout(0.3)
        s.sendto(payload, group)
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            try:
                data, (addr, _port) = s.recvfrom(65535)
            except socket.timeout:
                continue
            with contextlib.suppress(Exception):
                o = parse(data, addr)
                if o:
                    out.append(o)
    finally:
        s.close()
    return out


def ssdp_listen(seconds=3.0):
    return _multicast(SSDP, SEARCH, seconds, ssdp_parse)


WSD = ("239.255.255.250", 3702)


def wsd_probe():
    return ('<?xml version="1.0" encoding="UTF-8"?>'
            '<e:Envelope xmlns:e="http://www.w3.org/2003/05/soap-envelope" '
            'xmlns:w="http://schemas.xmlsoap.org/ws/2004/08/addressing" '
            'xmlns:d="http://schemas.xmlsoap.org/ws/2005/04/discovery" '
            'xmlns:dn="http://www.onvif.org/ver10/network/wsdl"><e:Header>'
            f'<w:MessageID>uuid:{uuid.uuid4()}</w:MessageID>'
            '<w:To e:mustUnderstand="true">urn:schemas-xmlsoap-org:ws:2005:04:discovery</w:To>'
            '<w:Action e:mustUnderstand="true">http://schemas.xmlsoap.org/ws/2005/04/discovery/Probe</w:Action>'
            '</e:Header><e:Body><d:Probe><d:Types>dn:NetworkVideoTransmitter</d:Types></d:Probe></e:Body>'
            '</e:Envelope>').encode()


def wsd_parse(data, source):
    """A WS-Discovery ProbeMatch as a camera sighting: its addresses (XAddrs) and the name
    and model in its scopes. Its endpoint id (a UUID) is left out."""
    if len(data) > 65536 or b"<!DOCTYPE" in data or b"<!ENTITY" in data:
        return None
    root = ET.fromstring(data)

    def text(tag):
        return " ".join(e.text.strip() for e in root.iter() if str(e.tag).endswith("}" + tag) and e.text)
    types, scopes, xaddrs = text("Types"), text("Scopes"), text("XAddrs")
    if not (types or scopes or xaddrs):
        return None
    found = dict(re.findall(r"onvif://www\.onvif\.org/(name|hardware)/(\S+)", scopes))
    name = scrub(urllib.parse.unquote(found.get("name", "")))
    hardware = scrub(urllib.parse.unquote(found.get("hardware", "")))
    addrs = [source] + [h for h in (urllib.parse.urlsplit(u).hostname for u in xaddrs.split()) if h and ip_of(h)]
    return obs("wsd", list(dict.fromkeys(addrs)), label=" ".join(x for x in (name, hardware) if x),
               says=f"{types} {scopes}", products=["ONVIF camera"] if "onvif" in (types + scopes).lower() else [])


def wsd_listen(seconds=3.0):
    return _multicast(WSD, wsd_probe(), seconds, wsd_parse)


# ------------------------------------------------------------------ 2. what this computer knows


def _run(argv, timeout=5):
    if not shutil.which(argv[0]):
        return None
    try:
        p = subprocess.run(argv, capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return p.stdout if p.returncode == 0 else None


def neigh_parse(text):
    """`ip -j neigh` -> [address]: live neighbours on the network's interfaces (the MAC is
    never read)."""
    out = []
    for n in json.loads(text or "[]"):
        state = set(n.get("state") or [])
        if not n.get("dst") or state & _DEAD or _LOCAL_IF.match(n.get("dev") or ""):
            continue
        out.append(n["dst"])
    return out


def arp_parse(text):
    """/proc/net/arp -> [address] (complete entries only; the hardware address column is skipped)."""
    out = []
    for line in (text or "").splitlines()[1:]:
        f = line.split()
        if len(f) >= 6 and f[2] != "0x0" and not _LOCAL_IF.match(f[5]):
            out.append(f[0])
    return out


def neighbours():
    """(addresses, the default gateway or "")."""
    text = _run(["ip", "-j", "neigh", "show"])
    if text is not None:
        addrs = neigh_parse(text)
    else:
        try:
            with open("/proc/net/arp") as f:
                addrs = arp_parse(f.read())
        except OSError:
            addrs = []
    gw = ""
    with contextlib.suppress(Exception):
        gw = next((r.get("gateway") for r in json.loads(_run(["ip", "-j", "route", "show", "default"]) or "[]")
                   if r.get("gateway")), "")
    return addrs, gw


def _pool(fn, items, timeout, workers=8):
    """{item: fn(item)} for those that answered within `timeout` seconds in all."""
    out = {}
    if not items:
        return out
    ex = cf.ThreadPoolExecutor(max_workers=workers)
    futs = {ex.submit(fn, i): i for i in items}
    try:
        for f in cf.as_completed(futs, timeout=timeout):
            with contextlib.suppress(Exception):
                out[futs[f]] = f.result()
    except cf.TimeoutError:
        pass
    ex.shutdown(wait=False, cancel_futures=True)
    return out


def reverse(addresses, timeout=4.0):
    """{address: name} from this computer's own resolver (a reverse lookup each)."""
    def one(a):
        name = socket.gethostbyaddr(a)[0]
        return "" if not short(name) else name
    return {a: n for a, n in _pool(one, sorted(set(addresses)), timeout).items() if n}


def resolve(names, timeout=4.0):
    """{name: [address]} through this computer's own resolver."""
    def one(n):
        return sorted({i[4][0] for i in socket.getaddrinfo(n, None, proto=socket.IPPROTO_TCP)})
    return _pool(one, sorted(set(names)), timeout)


def tailscale_parse(text):
    """`tailscale status --json` -> sightings of the tailnet's other devices."""
    d = json.loads(text or "{}")
    out = []
    for p in (d.get("Peer") or {}).values():
        dns = str(p.get("DNSName") or "").rstrip(".")
        names = [n for n in (p.get("HostName"), dns) if n]
        out.append(obs("tailscale", p.get("TailscaleIPs") or [], names, says=str(p.get("OS") or ""), tailnet=True,
                       online=bool(p.get("Online"))))
    return out


def tailscale():
    if not shutil.which("tailscale"):
        return None
    return tailscale_parse(_run(["tailscale", "status", "--json"]) or "{}")


SSH_CONFIG = os.path.expanduser("~/.ssh/config")


def ssh_parse(text):
    """[(alias, hostname)] from an ssh_config's Host blocks (patterns and Match blocks skipped;
    Include isn't followed: only this one file is read)."""
    out, aliases, host = [], [], None

    def close():
        for a in aliases:
            out.append((a, host or a))
    for line in (text or "").splitlines():
        line = line.split("#", 1)[0].strip()
        if not line:
            continue
        m = re.match(r"(\S+)\s*(?:=\s*|\s+)(.*)", line)
        if not m:
            continue
        key, val = m.group(1).lower(), m.group(2).strip().strip('"')
        if key in ("host", "match"):
            close()
            aliases = [a for a in val.split() if key == "host" and not re.search(r"[*?!%]", a)]
            host = None
        elif key == "hostname" and aliases:
            host = val if "%" not in val else None
    close()
    return out


def ssh_config(path=None):
    """Sightings for ~/.ssh/config's hosts, each resolved by this computer's resolver."""
    try:
        with open(path or SSH_CONFIG) as f:
            pairs = ssh_parse(f.read())
    except OSError:
        return None
    addrs = resolve([h for _a, h in pairs])
    return [obs("ssh", addrs.get(h) or ([h] if ip_of(h) else []), [a] + ([h] if not ip_of(h) else []))
            for a, h in pairs]


# ------------------------------------------------------------------ 3. what the lab knows (homelab.toml's sources)


def unifi_parse(rows):
    """UniFi Poller's client rows (unpoller_client_*) -> sightings by IP and name (the mac
    and oui labels are never read)."""
    out = []
    for r in rows:
        lb = r.get("labels") or {}
        if lb.get("ip"):
            out.append(obs("unifi", [lb["ip"]], list(dict.fromkeys(n for n in (lb.get("hostname"), lb.get("name")) if n))))
    return out


def prometheus_parse(doc):
    """/api/v1/targets -> the hosts it scrapes: static and node targets, not pods (a pod's
    address is the cluster's, not a host on the network)."""
    out = []
    for t in ((doc or {}).get("data") or {}).get("activeTargets") or []:
        found = t.get("discoveredLabels") or {}
        if any(k.startswith(("__meta_kubernetes_pod", "__meta_kubernetes_service", "__meta_kubernetes_endpoint"))
               for k in found):
            continue
        host = urllib.parse.urlsplit(t.get("scrapeUrl") or "").hostname or ""
        if host and host not in ("localhost",) and not host.startswith("127."):
            out.append(obs("prometheus", [host] if ip_of(host) else [], [] if ip_of(host) else [host]))
    return out


def kube_parse(doc):
    """`kubectl get nodes -o json` -> each node's InternalIP and name."""
    out = []
    for n in (doc or {}).get("items") or []:
        a = (n.get("status") or {}).get("addresses") or []
        ips = [x["address"] for x in a if x.get("type") in ("InternalIP", "ExternalIP") and x.get("address")]
        names = [x["address"] for x in a if x.get("type") == "Hostname"] or [(n.get("metadata") or {}).get("name")]
        out.append(obs("kubernetes", ips, [x for x in names if x]))
    return out


def proxmox_parse(name, doc):
    """A VM's guest-agent interfaces (network-get-interfaces) -> its addresses (never the
    hardware address)."""
    ips = []
    for i in ((doc or {}).get("result") or []):
        if i.get("name") == "lo":
            continue
        for a in i.get("ip-addresses") or []:
            ip = ip_of(a.get("ip-address"))
            if ip and not (ip.is_loopback or ip.is_link_local):
                ips.append(str(ip))
    return [obs("proxmox", ips, [name])] if ips else []


def _resolve_names(found):
    """Give each name-only sighting the addresses its names resolve to."""
    names = {n for o in found if not o["addresses"] for n in o["names"]}
    got = resolve(names) if names else {}
    for o in found:
        if not o["addresses"]:
            o["addresses"] = sorted({a for n in o["names"] for a in got.get(n, [])})
    return found


def lab_known(instances=None, max_vms=64):
    """{source: [sightings]} from the lab's configured sources, read with their adapters."""
    from . import registry
    from .adapters import labcommon as L
    insts = registry.instances() if instances is None else instances
    out = {}
    for a in insts:
        try:
            if a.type == "unifi":
                rows = L.rows_of(L.parse_prom(a.fetch("/metrics", raw=True, timeout=6)), "unpoller_client_uptime_seconds") \
                    if a.has_web() else L.mq_soft("unpoller_client_uptime_seconds")
                out.setdefault("unifi", []).extend(unifi_parse(rows))
            elif a.type in ("prometheus", "victoriametrics"):
                doc = a.get_json("/api/v1/targets?state=active", timeout=6)
                out.setdefault("prometheus", []).extend(_resolve_names(prometheus_parse(doc)))
            elif a.type == "kubernetes":
                out.setdefault("kubernetes", []).extend(kube_parse(json.loads(a.kubectl(["get", "nodes", "-o", "json"],
                                                                                        timeout=20))))
            elif a.type == "proxmox":
                vms = [r for r in a._data("/cluster/resources?type=vm", timeout=6) or []
                       if r.get("type") == "qemu" and r.get("status") == "running"][:max_vms]
                for r in vms:
                    with contextlib.suppress(Exception):
                        doc = a._data(f"/nodes/{r['node']}/qemu/{r['vmid']}/agent/network-get-interfaces", timeout=4)
                        out.setdefault("proxmox", []).extend(proxmox_parse(r.get("name") or str(r["vmid"]), doc))
                out.setdefault("proxmox", [])
        except Exception:
            out.setdefault(a.type if a.type != "victoriametrics" else "prometheus", [])
    return out


# ------------------------------------------------------------------ merging, classifying, checking


def classify(products):
    """A host's kind from what it was recognised as."""
    kinds = {k for _p, k in products}
    return next((k for k in _PRIORITY if k in kinds), "other")


def recognise(says):
    """[(product, kind)] for what a device said about itself."""
    return [(name, kind) for r, name, kind in _PRODUCTS if says and r.search(says)]


def merge(found, own=(), gateway=""):
    """One record per host from every sighting: sightings that share an address or a host
    name are one host. Addresses that aren't private are dropped (and counted), as are this
    computer's own. Returns (hosts, ignored)."""
    own = set(own)
    keep, ignored = [], 0
    for o in found:
        good = [a for a in o["addresses"] if allowed(a, o["tailnet"]) and a not in own]
        ignored += len([a for a in o["addresses"] if not allowed(a, o["tailnet"]) and ip_of(a)
                        and not (ip_of(a).is_link_local or ip_of(a).is_loopback or ip_of(a).is_multicast)])
        if good:
            keep.append(dict(o, addresses=good))
    parent = list(range(len(keep)))

    def root(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i
    first = {}
    for i, o in enumerate(keep):
        for k in [("a", str(ip_of(a))) for a in o["addresses"]] + [("n", short(n)) for n in o["names"] if short(n)]:
            if k in first:
                parent[root(i)] = root(first[k])
            else:
                first[k] = i
    groups = {}
    for i, o in enumerate(keep):
        groups.setdefault(root(i), []).append(o)
    hosts = []
    for group in groups.values():
        addrs = sorted({str(ip_of(a)) for o in group for a in o["addresses"]},
                       key=lambda a: (ip_of(a).version, any(ip_of(a) in n for n in TAILNET), ip_of(a)))
        products = {}
        for o in group:
            for p in o["products"]:
                products.setdefault(p, next((k for _r, n, k in _PRODUCTS if n == p), "other"))
            for p, k in recognise(" ".join([o["says"], o["label"]] + o["names"])):
                products.setdefault(p, k)
        if gateway and gateway in addrs:
            products.setdefault("router", "other")
        by = sorted(group, key=lambda o: _NAMED_BY.index(o["source"]) if o["source"] in _NAMED_BY else 99)
        names = list(dict.fromkeys(n for o in by for n in o["names"]))
        labels = list(dict.fromkeys(o["label"] for o in group if o["label"]))
        onl = [o["online"] for o in group if o["online"] is not None]     # offline only if only Tailscale saw it
        hosts.append({"name": names[0] if names else (labels[0] if labels else addrs[0]), "names": names,
                      "labels": labels, "addresses": addrs,
                      "sources": sorted({o["source"] for o in group}, key=lambda s: list(SOURCES).index(s)),
                      "tailnet": any(o["tailnet"] for o in group), "online": any(onl) if len(onl) == len(group) else None,
                      "products": sorted(products), "kind": classify(products.items()), "services": [],
                      "checked": ""})
    hosts.sort(key=lambda h: (KINDS.index(h["kind"]), h["name"].lower()))
    return hosts, ignored


def check_address(host):
    """The address setup checks a host at: its first private IPv4 (a LAN one before a tailnet
    one), or None."""
    return next((a for a in host["addresses"] if ip_of(a).version == 4 and allowed(a, host["tailnet"])), None)


class Pace:
    """At most `rate` new connections a second, across threads."""

    def __init__(self, rate=25):
        self.gap, self.next, self.lock = 1.0 / rate, 0.0, threading.Lock()

    def wait(self):
        with self.lock:
            now = time.monotonic()
            at = max(now, self.next)
            self.next = at + self.gap
        if at > now:
            time.sleep(at - now)


PACE = Pace(25)


@contextlib.contextmanager
def same_host_redirects():
    """While checking, a redirect may only stay on the host it came from: an answer can never
    send a probe off to somewhere else."""
    H = urllib.request.HTTPRedirectHandler
    orig = H.redirect_request

    def guarded(self, req, fp, code, msg, headers, newurl):
        if urllib.parse.urlsplit(newurl).hostname != urllib.parse.urlsplit(req.full_url).hostname:
            return None
        return orig(self, req, fp, code, msg, headers, newurl)
    H.redirect_request = guarded
    try:
        yield
    finally:
        H.redirect_request = orig


def checkable(host):
    return host["kind"] in CHECKED or any(ADAPTER_OF.get(p) for p in host["products"])


def check(hosts, finder, workers=4, names=None):
    """Run finder(address) (setup's host_finds: each adapter's well-known ports, counted only
    when its own API answers) on each found host, and on nothing else. Kinds outside
    CHECKED, offline tailnet devices and hosts with no private IPv4 are skipped. Each find's
    endpoint uses a host name when that name resolves back to the same address."""
    todo = {}
    for h in hosts:
        addr = check_address(h)
        if not checkable(h):
            h["checked"] = "not checked: nothing bromigOS adds runs on one"
        elif h.get("online") is False:
            h["checked"] = "not checked: offline"
        elif not addr:
            h["checked"] = "not checked: no private IPv4 address"
        else:
            todo[addr] = h
    with same_host_redirects():
        got = _pool(finder, sorted(todo), timeout=max(60.0, 20.0 * len(todo) / max(1, workers)), workers=workers)
    back = (names or resolve)([n for addr in got if got[addr] for n in todo[addr]["names"]])
    for addr, h in todo.items():
        if addr not in got:
            h["checked"] = "the check failed or didn't finish"
            continue
        name = next((n for n in h["names"] if addr in (back.get(n) or [])), None)
        h["services"] = [dict(s, endpoint=s["endpoint"].replace(f"://{addr}", f"://{name}", 1)) if name else s
                         for s in got[addr]]
        h["checked"] = "checked"
        if h["services"] and h["kind"] == "other":
            media = all(s["type"] in ("jellyfin", "plex") for s in h["services"])
            h["kind"] = "media" if media else "lab machine"
    hosts.sort(key=lambda h: (KINDS.index(h["kind"]), h["name"].lower()))
    return hosts


def ssh_boxes(hosts, port=22, connect=None, names=None):
    """The found hosts that accept a connection on their SSH port, for `bromigos lab provision`'s
    step 3: only hosts a source found, at private IPv4 addresses, rate-limited. Each gets
    "ssh", the name to reach it by (one that resolves back to its address), else the address."""
    def knock(addr):
        PACE.wait()
        with socket.create_connection((addr, port), timeout=0.8):
            return True
    todo = {}
    for h in hosts:
        addr = check_address(h)
        if addr and checkable(h) and h.get("online") is not False:
            todo[addr] = h
    got = _pool(connect or knock, sorted(todo), timeout=30.0)
    up = [a for a in sorted(todo) if got.get(a)]
    back = (names or resolve)([n for a in up for n in todo[a]["names"]])
    out = []
    for a in up:
        h = todo[a]
        out.append(dict(h, ssh=next((n for n in h["names"] if a in (back.get(n) or [])), a)))
    return out


def unsupported(host):
    """[(product, adapter or None)] found on a host that nothing it adds covers: no adapter
    ("found, not supported yet"), or an adapter whose check didn't answer."""
    have = {s["type"] for s in host["services"]}
    return [(p, ADAPTER_OF.get(p)) for p in host["products"]
            if p not in ADAPTER_OF or (ADAPTER_OF[p] and ADAPTER_OF[p] not in have)]


# ------------------------------------------------------------------ all of it


def plan(ssh=False, lab=True):
    """The sources this run will read, in words (the consent question lists them)."""
    out = ["devices that announce themselves on your network (mDNS, UPnP and ONVIF camera discovery)",
           "this computer's list of nearby devices (its neighbour table) and the names your DNS gives them"]
    if shutil.which("tailscale"):
        out.append("your Tailscale devices (tailscale status)")
    if lab:
        out.append("what the sources already in homelab.toml know: router clients (UniFi), Prometheus's "
                   "scrape targets, Kubernetes nodes and Proxmox VMs")
    if ssh:
        out.append("the Host lines in ~/.ssh/config (that one file, never your keys)")
    return out


def own_addresses():
    """This computer's own addresses (they're the local checks', not the lab's)."""
    out = set()
    with contextlib.suppress(Exception):
        for i in json.loads(_run(["ip", "-j", "addr", "show"]) or "[]"):
            out |= {a.get("local") for a in i.get("addr_info") or [] if a.get("local")}
    return out


def find(ssh=False, lab=True, seconds=3.0, log=None):
    """{"hosts", "sources": {source: count, or why it was skipped}, "ignored"}: every source
    read, merged per host. Nothing is checked yet: check() does that."""
    say = log or (lambda _m: None)
    found, sources = [], {}

    def note(src, got, why="not available"):
        if got is None:
            sources[src] = why
        else:
            sources[src] = len(got)
            found.extend(got)
    say(f"Listening for devices that announce themselves ({seconds:g} seconds)…")
    with cf.ThreadPoolExecutor(max_workers=3) as ex:
        m = ex.submit(mdns_listen, seconds)
        s = ex.submit(ssdp_listen, seconds)
        w = ex.submit(wsd_listen, seconds)
        for src, fut in (("ssdp", s), ("wsd", w)):
            try:
                note(src, fut.result())
            except OSError as e:
                note(src, None, f"couldn't listen: {e.strerror or e}")
        try:
            recs = m.result()
            note("mdns", None if recs is None else mdns_observations(mdns_services(recs)),
                 "needs python-zeroconf (sudo pacman -S python-zeroconf)")
        except OSError as e:
            note("mdns", None, f"couldn't listen: {e.strerror or e}")
    say("Reading what this computer knows…")
    addrs, gw = neighbours()
    note("neighbours", [obs("neighbours", [a]) for a in addrs])
    note("tailscale", tailscale(), "Tailscale isn't installed")
    if ssh:
        note("ssh", ssh_config(), "no ~/.ssh/config")
    else:
        sources["ssh"] = "not read (no yes for it)"
    if lab:
        say("Asking the sources already in homelab.toml…")
        for src, got in lab_known().items():
            note(src, got)
    nameless = {a for o in found if not o["names"] for a in o["addresses"] if allowed(a, o["tailnet"])}
    names = reverse(nameless)
    note("dns", [obs("dns", [a], [n]) for a, n in sorted(names.items())])
    hosts, ignored = merge(found, own=own_addresses(), gateway=gw)
    return {"hosts": hosts, "sources": sources, "ignored": ignored}
