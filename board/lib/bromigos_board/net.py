"""Which source addresses may reach the board: the home network and the lab's private network,
never the internet (docs/board.md, "Who can reach it"). Caddy refuses the rest first
(board/caddy/site.caddy); the API checks again, so a mistake in one doesn't open the other.

The lab's private network (docs/lab-network.md) hands out addresses from the carrier-grade NAT
range (RFC 6598). Some internet providers use the same range for their customers, so an address
from it says nothing by itself: it counts as local only when the request came in on the lab
network's own interface. Caddy says which of this server's addresses the connection arrived at
(X-Bromigos-Local), and that must be one of tailscale0's. A neighbour in the provider's range
arrives at the uplink's address instead. (The firewall decides the same way, by the interface:
server/bromigos-server, lab_twins.)"""
import ipaddress
import os
import socket
import struct

from . import paths

# always local: private (RFC 1918), link-local, loopback, and IPv6's unique-local, link-local and
# loopback. Written as numbers, as bromigos-server writes its own: the medium's privacy guard
# can't tell these well-known ranges from a real network's addresses.
PRIVATE = [ipaddress.ip_network(n) for n in (
    str(ipaddress.IPv4Network((0x0A000000, 8))), str(ipaddress.IPv4Network((0xAC100000, 12))),
    str(ipaddress.IPv4Network((0xC0A80000, 16))),
    str(ipaddress.IPv4Network((0xA9FE0000, 16))), str(ipaddress.IPv4Network((0x7F000000, 8))),
    "fc00::/7", "fe80::/10", "::1/128")]
# local only when the request came in on the lab network's own interface (is_private)
LAB_NETWORK = [ipaddress.ip_network(str(ipaddress.IPv4Network((0x64400000, 10))))]
# the lab's private network's interface (tailscaled makes it when it starts)
LAB_INTERFACES = ("tailscale0",)
# the header Caddy sets to the address of this server that the connection came in at
# ({http.request.local.host}, site.caddy); a browser's own is replaced, never passed on
LOCAL_HEADER = "x-bromigos-local"


def _ifindex(name):
    try:
        with open(paths.at(f"/sys/class/net/{name}/ifindex")) as f:
            return int(f.read().strip())
    except (OSError, ValueError):
        return None


def interface_addresses(names=LAB_INTERFACES):
    """This server's IPv4 and IPv6 addresses on those interfaces, asked of the kernel over
    rtnetlink (RTM_GETADDR, which needs no privilege). [] when there is no such interface, or
    the kernel can't be asked."""
    wanted = {i for i in (_ifindex(n) for n in names) if i is not None}
    if not wanted:
        return []
    try:
        return [a for index, a in _rtnl_addresses() if index in wanted]
    except OSError:
        return []


def _rtnl_addresses():
    """[(interface index, address)] of every address the kernel has, from one RTM_GETADDR dump."""
    RTM_GETADDR, RTM_NEWADDR, NLMSG_DONE, NLMSG_ERROR = 22, 20, 3, 2
    IFA_ADDRESS, IFA_LOCAL = 1, 2
    out = []
    with socket.socket(socket.AF_NETLINK, socket.SOCK_RAW | socket.SOCK_CLOEXEC, 0) as s:   # 0: NETLINK_ROUTE
        s.settimeout(2)
        s.bind((0, 0))
        req = struct.pack("=LHHLL", 16 + 8, RTM_GETADDR, 0x1 | 0x300, 1, 0) + struct.pack("=BBBBI", socket.AF_UNSPEC, 0, 0, 0, 0)
        s.send(req)
        while True:
            data = s.recv(65536)
            off = 0
            while off + 16 <= len(data):
                length, kind = struct.unpack_from("=LH", data, off)
                if length < 16:
                    return out
                if kind == NLMSG_DONE or kind == NLMSG_ERROR:
                    return out
                if kind == RTM_NEWADDR and length >= 24:
                    family, _, _, _, index = struct.unpack_from("=BBBBI", data, off + 16)
                    attrs, local, address = off + 24, None, None
                    while attrs + 4 <= off + length:
                        alen, atype = struct.unpack_from("=HH", data, attrs)
                        if alen < 4:
                            break
                        value = data[attrs + 4:attrs + alen]
                        if atype in (IFA_ADDRESS, IFA_LOCAL) and family in (socket.AF_INET, socket.AF_INET6):
                            try:
                                ip = ipaddress.ip_address(value)
                            except ValueError:
                                ip = None
                            if atype == IFA_LOCAL:
                                local = ip
                            else:
                                address = ip
                        attrs += (alen + 3) & ~3
                    if local or address:
                        out.append((index, local or address))
                off += (length + 3) & ~3


def _address(address):
    if not address:
        return None
    text = str(address).strip()
    if text.startswith("[") and "]" in text:
        text = text[1:text.index("]")]
    text = text.split("%", 1)[0]                       # fe80::1%eth0
    try:
        ip = ipaddress.ip_address(text)
    except ValueError:
        return None
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped:
        ip = ip.ipv4_mapped
    return ip


def is_private(address, arrived_at=None):
    """True for an address the board answers; False for anything else, a typo included.
    `arrived_at`: the address of this server the request came in at (Caddy's X-Bromigos-Local);
    an address in the lab network's range needs it to be one of the lab interface's."""
    ip = _address(address)
    if ip is None:
        return False
    if any(ip in n for n in PRIVATE):
        return True
    if not any(ip in n for n in LAB_NETWORK):
        return False
    local = _address(arrived_at)
    return local is not None and local in interface_addresses()


def arrived_at(headers):
    """The X-Bromigos-Local Caddy set: its last line, or None (a request over the socket itself)."""
    lines = [(v.decode("latin-1") if isinstance(v, bytes) else str(v)) for k, v in headers
             if (k.decode("latin-1") if isinstance(k, bytes) else str(k)).lower() == LOCAL_HEADER] \
        if isinstance(headers, (list, tuple)) else []
    return lines[-1].strip() if lines else None


def source(headers, peer):
    """The address a request came from. Caddy is the only client that can open the socket (its
    group owns it), and its reverse_proxy replaces X-Forwarded-For with the address it saw, so the
    last entry of the last such line is the browser's. With no header the request came over the
    socket itself (root or Caddy's own checks): that's this machine.

    `headers`: a list of (name, value) pairs as ASGI gives them, or anything with getlist() or
    get(). Every caller gets the same answer for the same request (api.LocalOnly reads it once)."""
    if isinstance(headers, (list, tuple)):
        lines = [(v.decode("latin-1") if isinstance(v, bytes) else str(v)) for k, v in headers
                 if (k.decode("latin-1") if isinstance(k, bytes) else str(k)).lower() == "x-forwarded-for"]
    elif hasattr(headers, "getlist"):
        lines = headers.getlist("x-forwarded-for")
    else:
        one = headers.get("x-forwarded-for")
        lines = [one] if one else []
    if lines:
        return lines[-1].split(",")[-1].strip()
    return peer or "127.0.0.1"
