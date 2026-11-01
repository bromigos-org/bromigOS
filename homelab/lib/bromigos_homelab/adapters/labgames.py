"""Game servers: a Pelican panel, and Minecraft servers by the status any
client sees (below). Capability: games. Read-only.

    [[source]]
    type = "pelican"                    # a Pelican exporter's metrics (pelican_server_*) in the metrics source
    # endpoint = "https://panel.lab"    # or the panel's client API, with a client API key:
    # auth_ref = "@file:~/.local/share/bromigos/pelican-client-key"
    # expect_running = ["survival"]     # servers the doctor expects up (others may sleep)

Per server: its game, status (running / pending: starting or stopping / stopped), players online and the
most allowed (from the exporter: the panel API has no player counts), uptime, CPU, memory.
Starting, stopping and restarting a server are actions for a later phase; nothing here
changes a server.
"""
from ..registry import Unreachable, register
from . import labcommon as L

# pelican_server_state: 1 running, 2 starting, 3 stopping, 0 offline, -1 unreachable
_MSTATE = {1: "running", 2: "pending", 3: "pending", 0: "stopped", -1: "unknown"}
_ASTATE = {"running": "running", "starting": "pending", "stopping": "pending", "offline": "stopped"}


def games_from_metrics(info, state, players, players_max, uptime, cpu, mem):
    def by(rows):
        return {r["labels"].get("server_uuid") or r["labels"].get("server_name"): r["value"] for r in rows}
    st, pl, mx, up, c, m = by(state), by(players), by(players_max), by(uptime), by(cpu), by(mem)
    out = []
    for r in info:
        lb = r["labels"]
        k = lb.get("server_uuid") or lb.get("server_name")
        s = st.get(k)
        out.append({"name": lb.get("server_name"), "game": lb.get("game"),
                    "status": _MSTATE.get(int(s), "unknown") if s is not None else "unknown",
                    "players": int(pl[k]) if pl.get(k) is not None else None,
                    "players_max": int(mx[k]) if mx.get(k) is not None else None,
                    "uptime_s": up.get(k), "cpu_pct": c.get(k), "mem_bytes": m.get(k), "uuid": lb.get("server_uuid")})
    return sorted(out, key=lambda g: str(g["name"]))


def games_from_api(servers, resources):
    """games records from the client API's server list and {identifier: resources attributes}."""
    out = []
    for s in servers:
        a = s.get("attributes") or s
        res = resources.get(a.get("identifier")) or {}
        r = res.get("resources") or {}
        out.append({"name": a.get("name"), "game": (a.get("egg") or {}).get("name") if isinstance(a.get("egg"), dict)
                    else a.get("docker_image", "").rsplit("/", 1)[-1] or None,
                    "status": _ASTATE.get(res.get("current_state"), "unknown"), "players": None,
                    "players_max": None, "uptime_s": (r.get("uptime") or 0) / 1000 if r.get("uptime") is not None else None,
                    "cpu_pct": r.get("cpu_absolute"), "mem_bytes": r.get("memory_bytes"), "uuid": a.get("uuid")})
    return sorted(out, key=lambda g: str(g["name"]))


def game_findings(games, expect=(), exporter_up=None, source=None):
    out = []
    if exporter_up is not None and not exporter_up:
        out.append(L.finding("games.exporter", "Game servers' exporter", "fail", "can't reach the panel",
                             "The exporter can't read the panel: check the panel is up and the exporter's API key.",
                             source))
    for g in games:
        if g["name"] in (expect or ()) and g["status"] != "running":
            out.append(L.finding(f"games.{g['name']}", f"Game server {g['name']}", "warn", g["status"],
                                 f"{g['name']} should be running: start it from the panel and read its console.",
                                 source))
    if games and not out:
        on = [g for g in games if g["status"] == "running"]
        players = sum(g.get("players") or 0 for g in on)
        out.append(L.finding("games.all", "Game servers", "ok",
                             f"{len(on)} of {len(games)} running · {players} player(s) online", source=source))
    return out


@register
class Pelican(L.LabAdapter):
    type = "pelican"
    hints = ("panel", "games")  # setup --ingress: host names that suggest it
    provides = ("games",)

    def probe(self):
        try:
            self.request("/api/client", timeout=3)
        except Exception as e:                    # the client API answers 401 without a key
            return getattr(e, "code", None) == 401 and b"pelican" in self.request("/", timeout=3, raw=True).lower()
        return True

    @classmethod
    def detect(cls, d):
        if d.has_metric("pelican_server_info"):
            return [{"type": "pelican"}]
        return []

    def games(self):
        info = L.mq_soft("pelican_server_info") if not (self.endpoint and self.opts.get("auth_ref")) else []
        if info:
            return games_from_metrics(info, L.mq_soft("pelican_server_state"), L.mq_soft("pelican_server_players_online"),
                                      L.mq_soft("pelican_server_players_max"), L.mq_soft("pelican_server_uptime_seconds"),
                                      L.mq_soft("pelican_server_cpu_percent"), L.mq_soft("pelican_server_memory_bytes"))
        if not (self.endpoint and self.opts.get("auth_ref")):
            raise Unreachable(f"{self.name}: no pelican_server_* metrics, and no panel endpoint with a client API key")
        servers = (self.fetch("/api/client?per_page=100", timeout=10) or {}).get("data") or []
        res = {}
        for s in servers:
            ident = (s.get("attributes") or {}).get("identifier")
            try:
                res[ident] = (self.fetch(f"/api/client/servers/{ident}/resources", timeout=6) or {}).get("attributes") or {}
            except Exception:
                res[ident] = {}
        return games_from_api(servers, res)

    def doctor(self):
        up = L.mq_soft("pelican_exporter_up")
        return game_findings(self.games(), self.opt("expect_running", ()),
                             all((r["value"] or 0) > 0 for r in up) if up else None, self.name)


# ------------------------------------------------------------------ Minecraft (Server List Ping)
# The status a Minecraft Java server gives any client before it logs in: the handshake
# (next state 1, status), a status request, and its JSON answer (version, players and a
# sample of their names, the message of the day), then a ping for the round trip. No login,
# no RCON, nothing changed. https://minecraft.wiki/w/Java_Edition_protocol/Server_List_Ping
#
#     [[source]]
#     type = "minecraft"
#     endpoint = "minecraft://mc.example.org:25565"    # or host:port, or a host (port 25565)
#     # servers = [{ name = "creative", address = "mc.example.org:25566" }]   # more than one
import json as _json  # noqa: E402
import re as _re  # noqa: E402
import socket as _socket  # noqa: E402
import struct as _struct  # noqa: E402
import time as _time  # noqa: E402


def _varint(n):
    n &= 0xFFFFFFFF
    out = b""
    while True:
        b = n & 0x7F
        n >>= 7
        out += bytes([b | (0x80 if n else 0)])
        if not n:
            return out


def _read_varint(sock):
    n = shift = 0
    for _ in range(5):
        b = sock.recv(1)
        if not b:
            raise ConnectionError("the server closed the connection")
        n |= (b[0] & 0x7F) << shift
        if not b[0] & 0x80:
            return n - (1 << 32) if n & (1 << 31) else n
        shift += 7
    raise ValueError("a varint longer than 5 bytes")


def _recv_exact(sock, n):
    buf = b""
    while len(buf) < n:
        chunk = sock.recv(n - len(buf))
        if not chunk:
            raise ConnectionError("the server closed the connection")
        buf += chunk
    return buf


def _packet(pid, payload=b""):
    body = _varint(pid) + payload
    return _varint(len(body)) + body


def parse_address(addr, default_port=25565):
    """(host, port) from "minecraft://host:port", "host:port", "[v6]:port" or "host"."""
    a = (addr or "").strip()
    a = _re.sub(r"^[a-z]+://", "", a).rstrip("/")
    m = _re.match(r"^\[([^\]]+)\](?::(\d+))?$", a)
    if m:
        return m.group(1), int(m.group(2) or default_port)
    if a.count(":") == 1:
        h, p = a.split(":")
        return h, int(p)
    return a, default_port


def motd_text(desc):
    """The message of the day as plain text: a string, or a chat component ({text, extra})."""
    def flat(d):
        if d is None:
            return ""
        if isinstance(d, str):
            return _re.sub(r"§.", "", d)
        if isinstance(d, list):
            return "".join(flat(x) for x in d)
        if isinstance(d, dict):
            return flat(d.get("text", "")) + "".join(flat(e) for e in d.get("extra") or [])
        return str(d)
    return " ".join(flat(desc).split())


def slp(host, port, timeout=4.0):
    """The server's status JSON and the ping's round trip in ms."""
    with _socket.create_connection((host, port), timeout=timeout) as s:
        s.settimeout(timeout)
        hs = _varint(767) + _varint(len(host.encode())) + host.encode() + _struct.pack(">H", port) + _varint(1)
        s.sendall(_packet(0, hs) + _packet(0))
        _read_varint(s)                                    # the packet's length
        if _read_varint(s) != 0:
            raise ValueError("not a status answer")
        n = _read_varint(s)
        status = _json.loads(_recv_exact(s, n).decode("utf-8", "replace"))
        t0 = _time.perf_counter()
        s.sendall(_packet(1, _struct.pack(">q", 1)))
        try:
            _read_varint(s)
            _read_varint(s)
            _recv_exact(s, 8)
            ms = (_time.perf_counter() - t0) * 1000
        except (OSError, ValueError):
            ms = None
    return status, ms


def game_from_status(name, status, ms=None):
    pl = status.get("players") or {}
    ver = status.get("version") or {}
    sample = [p.get("name") for p in pl.get("sample") or [] if isinstance(p, dict) and p.get("name")]
    # a server that hides its players fills the sample with lines of text ("§7and 12 more")
    names = [n for n in sample if _re.match(r"^[A-Za-z0-9_]{2,16}$", n)]
    return {"name": name, "game": "Minecraft", "status": "running", "players": pl.get("online"),
            "players_max": pl.get("max"), "uptime_s": None, "cpu_pct": None, "mem_bytes": None,
            "version": ver.get("name"), "motd": motd_text(status.get("description")), "latency_ms": ms,
            "player_names": names}


@register
class Minecraft(L.LabAdapter):
    type = "minecraft"
    provides = ("games",)
    default_ports = (25565,)
    local = True

    def configured(self):
        return bool(self.endpoint or self.opts.get("servers"))

    def targets(self):
        out = []
        if self.endpoint:
            out.append((self.name, self.endpoint))
        for s in self.opts.get("servers") or []:
            if isinstance(s, dict) and s.get("address"):
                out.append((s.get("name") or s["address"], s["address"]))
            elif isinstance(s, str):
                out.append((s, s))
        return out

    def probe(self):
        try:
            slp(*parse_address(self.endpoint), timeout=3)
            return True
        except (OSError, ValueError):
            return False

    def games(self):
        out = []
        for name, addr in self.targets():
            try:
                host, port = parse_address(addr)
                st, ms = slp(host, port, timeout=float(self.opt("timeout", 4)))
                out.append(dict(game_from_status(name, st, ms), address=addr))
            except (OSError, ValueError) as e:
                out.append({"name": name, "game": "Minecraft", "status": "stopped", "players": None,
                            "players_max": None, "uptime_s": None, "cpu_pct": None, "mem_bytes": None, "address": addr,
                            "error": f"no answer: {getattr(e, 'strerror', None) or e}"[:120]})
        if not out:
            raise Unreachable(f"{self.name}: no endpoint (minecraft://host:port) or servers in homelab.toml")
        return out

    def doctor(self):
        return game_findings(self.games(), self.opt("expect_running", ()), None, self.name)
