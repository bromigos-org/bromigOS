"""Which source addresses may reach the board: the home network and the lab's private network,
never the internet (docs/board.md, "Who can reach it"). Caddy refuses the rest first
(board/caddy/site.caddy); the API checks again, so a mistake in one doesn't open the other."""
import ipaddress

# private (RFC 1918), carrier-grade NAT (RFC 6598: the lab's private network and Tailscale use
# it), link-local, loopback, and IPv6's unique-local, link-local and loopback. Written as numbers,
# as bromigos-server writes its own: the medium's privacy guard can't tell these well-known ranges
# from a real network's addresses.
PRIVATE = [ipaddress.ip_network(n) for n in (
    str(ipaddress.IPv4Network((0x0A000000, 8))), str(ipaddress.IPv4Network((0xAC100000, 12))),
    str(ipaddress.IPv4Network((0xC0A80000, 16))), str(ipaddress.IPv4Network((0x64400000, 10))),
    str(ipaddress.IPv4Network((0xA9FE0000, 16))), str(ipaddress.IPv4Network((0x7F000000, 8))),
    "fc00::/7", "fe80::/10", "::1/128")]


def is_private(address):
    """True for an address the board answers; False for anything else, a typo included."""
    if not address:
        return False
    text = str(address).strip()
    if text.startswith("[") and "]" in text:
        text = text[1:text.index("]")]
    text = text.split("%", 1)[0]                       # fe80::1%eth0
    try:
        ip = ipaddress.ip_address(text)
    except ValueError:
        return False
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped:
        ip = ip.ipv4_mapped
    return any(ip in n for n in PRIVATE)


def source(headers, peer):
    """The address a request came from. Caddy is the only client that can open the socket (its
    group owns it), and its reverse_proxy replaces X-Forwarded-For with the address it saw, so the
    last entry is the browser's. With no header the request came over the socket itself (root or
    Caddy's own checks): that's this machine."""
    fwd = headers.get("x-forwarded-for")
    if fwd:
        return fwd.split(",")[-1].strip()
    return peer or "127.0.0.1"
