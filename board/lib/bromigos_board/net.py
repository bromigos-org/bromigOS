"""Which source addresses may reach the board: the home network and the lab's private network,
never the internet (docs/board.md, "Who can reach it"). Caddy refuses the rest first
(board/caddy/site.caddy); the API checks again, so a mistake in one doesn't open the other.

The lab's private network (docs/lab-network.md) hands out addresses from the carrier-grade NAT
range (RFC 6598). Some internet providers use the same range for their customers, so it counts
as local only while this server is on the lab's network: while its interface is there."""
import ipaddress
import os

from . import paths

# always local: private (RFC 1918), link-local, loopback, and IPv6's unique-local, link-local and
# loopback. Written as numbers, as bromigos-server writes its own: the medium's privacy guard
# can't tell these well-known ranges from a real network's addresses.
PRIVATE = [ipaddress.ip_network(n) for n in (
    str(ipaddress.IPv4Network((0x0A000000, 8))), str(ipaddress.IPv4Network((0xAC100000, 12))),
    str(ipaddress.IPv4Network((0xC0A80000, 16))),
    str(ipaddress.IPv4Network((0xA9FE0000, 16))), str(ipaddress.IPv4Network((0x7F000000, 8))),
    "fc00::/7", "fe80::/10", "::1/128")]
# local only while the lab's private network is up on this server (lab_network_up)
LAB_NETWORK = [ipaddress.ip_network(str(ipaddress.IPv4Network((0x64400000, 10))))]
# the lab's private network's interface (tailscaled makes it when it starts)
LAB_INTERFACES = ("tailscale0",)


def lab_network_up():
    """Whether this server is on the lab's private network now: its interface is there."""
    return any(os.path.isdir(paths.at(f"/sys/class/net/{name}")) for name in LAB_INTERFACES)


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


def is_private(address):
    """True for an address the board answers; False for anything else, a typo included."""
    ip = _address(address)
    if ip is None:
        return False
    if any(ip in n for n in PRIVATE):
        return True
    return any(ip in n for n in LAB_NETWORK) and lab_network_up()


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
