"""Game servers: Pelican (and Pterodactyl, its ancestor). Capability: games. Read-only.

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
