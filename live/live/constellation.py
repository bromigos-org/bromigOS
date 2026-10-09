"""The lab's nodes as the holo deck's constellation draws them (gadgets.constellation).

The nodes come from the lab's snapshot: nothing here names a machine. homelab.toml's
[constellation] may pin the drawing (docs/homelab.md): `hub` (the node in the middle,
linked to the others), `ai` (two nodes whose link carries the models' requests/min) and
`positions`, each node's place on the unit sphere, in drawing order, as a list of
`{node = "…", at = [x, y, z]}` tables. Node names are host names: references keep them out
of a public file, and in the private overlay this list form is the one to use, since sops
encrypts values but leaves a map's keys in clear text (a `{"node": [x, y, z]}` table
would publish every name). That table form still works in a config that isn't encrypted.
Without positions the first node is the hub and the rest ring it.
"""
import math

TAU = 2 * math.pi
WAN = ("uplink", (-0.15, -0.20, -0.95))


def auto_layout(names):
    """{name: (x, y, z)}: the first in the middle, the rest round it at varied heights."""
    if not names:
        return {}
    hub, rest = names[0], names[1:]
    pos = {hub: (0.0, 0.08, 0.0)}
    for i, n in enumerate(rest):
        a = TAU * i / len(rest) + 0.35
        y = 0.72 * math.sin(i * 2.4 + 0.6)
        r = 0.9 * math.sqrt(max(0.0, 1.0 - y * y))
        pos[n] = (r * math.cos(a), y, r * math.sin(a))
    return pos


def layout(names, conf):
    """(positions in drawing order, links, the models' link or None) for these node names
    and a [constellation] table."""
    conf = conf if isinstance(conf, dict) else {}
    raw = conf.get("positions")
    if isinstance(raw, dict):                    # {node = [x, y, z]}: an unencrypted config
        pairs = list(raw.items())
    elif isinstance(raw, list):                  # [{node, at}]: every name a value (an overlay)
        pairs = [(e.get("node"), e.get("at")) for e in raw if isinstance(e, dict)]
    else:
        pairs = []
    pos = {}
    for k, v in pairs:
        try:
            p = tuple(float(x) for x in v[:3])
        except (TypeError, ValueError):
            continue
        if k not in (None, "") and len(p) == 3:
            pos[str(k)] = p
    pos = pos or auto_layout(list(names))
    hub = conf.get("hub") if conf.get("hub") in pos else next(iter(pos), None)
    ai = conf.get("ai")
    ai = tuple(ai[:2]) if isinstance(ai, list) and len(ai) >= 2 and all(a in pos for a in ai[:2]) else None
    links = [(hub, n) for n in pos if n != hub] + ([ai] if ai else []) + ([(hub, WAN[0])] if hub else [])
    return pos, links, ai


def node_layout(d):
    """layout() for a data reading (its snapshot's nodes) and homelab.toml's [constellation]."""
    from .homelab import constellation
    names = [n["name"] for n in ((d.get("cluster") or {}).get("nodes") or []) if n.get("name")]
    return layout(names, constellation())
