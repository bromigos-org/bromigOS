"""GAME SERVERS: the homelab's game servers, who's on them and whether they're up
(bromigos-homelab's games capability: a `pelican` source for a Pelican or Pterodactyl
panel, or a `minecraft` source that asks a server for its status as any client would).

A panel generator (widgets/plugins.py): it offers the "games" panel only while something
provides games, so the widget gallery lists it only then.
"""
import os
import sys
import time

_HERE = os.path.dirname(os.path.realpath(__file__))
for _p in (os.path.join(os.path.dirname(_HERE), "lib"),):        # a bromigOS checkout's homelab/lib
    if os.path.isdir(_p) and _p not in sys.path:
        sys.path.insert(1, _p)

import panels  # noqa: E402

sys.path.append(os.path.join(os.path.dirname(os.path.realpath(panels.__file__)), "plugins"))
import _kit as K  # noqa: E402

import draw as D  # noqa: E402
import sources as S  # noqa: E402

NAME = "games"
STATUS = {"running": ("UP", "phosphor"), "pending": ("STARTING", "amber"), "stopped": ("DOWN", "danger"),
          "unknown": ("?", "static")}


def _demo_lab():
    return os.environ.get("BROMIGOS_WIDGETS_DEMO_LAB") == "1"


def names():
    return {NAME: 1} if available()[0] else {}


def available():
    """(True, "") when the panel has a source, else (False, why): names()' check, no network."""
    if _demo_lab():
        return True, ""
    try:
        import bromigos_homelab as H
    except ImportError:
        return False, "bromigos-homelab isn't installed"
    return (True, "") if H.available("games") else (False, "no [[source]] in homelab.toml provides games (minecraft or pelican)")


def panel(name):
    return GamesPanel, {"visible": False}


# ------------------------------------------------------------------ the data
def order(items):
    """Running first, then by players online, then by name."""
    rank = {"running": 0, "pending": 1, "unknown": 2, "stopped": 3}
    return sorted(items, key=lambda g: (rank.get(g.get("status"), 2), -(g.get("players") or 0), str(g.get("name"))))


def totals(items):
    up = [g for g in items if g.get("status") == "running"]
    return {"servers": len(items), "up": len(up), "players": sum(g.get("players") or 0 for g in up),
            "slots": sum(g.get("players_max") or 0 for g in up)}


def demo_result():
    return {"ok": True, "sources": ["games"], "errors": {}, "items": [
        {"name": "survival", "game": "Minecraft", "status": "running", "players": 4, "players_max": 20,
         "version": "1.21.4", "motd": "Harbor Point survival · be kind to the creepers", "latency_ms": 3.1,
         "player_names": ["lamplighter", "Tidewatch", "greywater_7", "mossbyte"], "address": "mc.example.org:25565",
         "uptime_s": None, "cpu_pct": None, "mem_bytes": None, "source": "minecraft"},
        {"name": "creative", "game": "Minecraft", "status": "running", "players": 1, "players_max": 10,
         "version": "1.21.4", "motd": "Build anything", "latency_ms": 2.6, "player_names": ["driftwood"],
         "address": "mc.example.org:25566", "uptime_s": None, "cpu_pct": None, "mem_bytes": None, "source": "minecraft"},
        {"name": "valheim-crew", "game": "Valheim", "status": "running", "players": 2, "players_max": 10,
         "uptime_s": 3 * 86400 + 4 * 3600, "cpu_pct": 38.0, "mem_bytes": 3.4 * 2 ** 30, "source": "pelican"},
        {"name": "factorio", "game": "Factorio", "status": "stopped", "players": None, "players_max": None,
         "uptime_s": None, "cpu_pct": None, "mem_bytes": None, "source": "pelican"},
    ]}


# ------------------------------------------------------------------ the panel
class GamesPanel(K.KitPanel):
    name, title = NAME, "GAME SERVERS"
    description = "Your homelab's game servers: up or down, and who's playing"
    category, reads = "homelab", "your homelab's game servers (Pelican, Minecraft)"
    width, height = 460, 260
    interval = 10.0                    # the draw refresh; the servers are asked every 60 s
    fit = "content"                    # as tall as its rows (panels.Panel.fit)
    sizes = {
        "compact": ((240, 120), (380, 190), (280, 140)),
        "standard": ((400, 200), (620, 420), (460, 260)),
        "wide": ((640, 180), (1200, 340), (820, 220)),
        "tall": ((380, 440), (560, 900), (420, 520)),
        "large": ((660, 440), (1200, 900), (780, 540)),
    }
    default_size = "standard"

    @classmethod
    def available(cls):
        return available()
    settings = [{"key": "hide", "label": "Servers to leave out", "kind": "list", "default": [],
                 "hint": "Server names, one per line"}]

    def __init__(self, cfg=None, wake=None):
        super().__init__(cfg, wake)
        self.read_at = time.time()
        if K.demo():
            self.res = demo_result()
        else:
            self.poll = self.poller(self.fetch, every=60)

    def fetch(self):
        import bromigos_homelab as H
        r = H.games()
        self.read_at = time.time()
        return r

    def result(self):
        return self.res if K.demo() else self.poll.data

    def draw(self, cr, w, h):
        cls = self.size_class(w, h)
        r = self.result()
        hide = set(self.conf.list("hide"))
        items = order([g for g in (r or {}).get("items") or [] if g.get("name") not in hide])
        t = totals(items)
        right = None
        if items and cls != "compact":
            right = f"{t['up']}/{t['servers']} UP · {t['players']} PLAYING"
        top = D.frame(cr, w, h, self.title, right, "phosphor" if t["up"] == t["servers"] else "amber")
        self.region(0, 0, w, 34, f"Your homelab's game servers ({', '.join((r or {}).get('sources') or []) or 'none'}), "
                    f"asked every minute. {t['up']} of {t['servers']} up, {t['players']} player(s) on.")
        if r is None:
            err = getattr(getattr(self, "poll", None), "error", None)
            self.empty(cr, w, h, top, "CAN'T READ THE SERVERS" if err else "ASKING…", err or "Asking the servers.",
                       color="amber" if err else "static")
            return
        if not r.get("sources"):
            self.empty(cr, w, h, top, "NO GAME SERVERS SET UP",
                       "Add one to ~/.config/bromigos/homelab.toml: [[source]] type = \"minecraft\" with endpoint = "
                       "\"minecraft://host:25565\", or type = \"pelican\" for a Pelican panel.")
            return
        if not r.get("ok") and not items:
            why = "; ".join(f"{k}: {v}" for k, v in (r.get("errors") or {}).items())
            self.empty(cr, w, h, top, "SERVERS UNREACHABLE", why or "No source answered.")
            return
        x0, x1 = 16, w - 16
        if cls == "compact":
            self._compact(cr, items, t, x0, x1, top, h)
        elif cls == "wide":
            self._cards(cr, items, x0, x1, top, h - 12, names=False)
        elif cls == "large":
            self._cards(cr, items, x0, x1, top, h - 12, names=True)
        else:
            self._rows(cr, items, x0, x1, top, h - 12, detail=(cls == "tall"))

    def _compact(self, cr, items, t, x0, x1, top, h):
        col = "phosphor" if t["players"] else "soft"
        tw = D.seg7(cr, x0, top + 2, max(22, min(50, h - top - 48)), str(t["players"]), col)
        D.label(cr, x0 + tw + 10, top + 4, "PLAYING", col, size=10)
        D.label(cr, x0 + tw + 10, top + 22, f"{t['up']}/{t['servers']} UP", "phosphor" if t["up"] == t["servers"]
                else "amber", size=10)
        self.region(x0, top, x1 - x0, 56, f"{t['players']} player(s) on {t['up']} running server(s) of {t['servers']}")
        busy = next((g for g in items if g.get("status") == "running"), None)
        if busy:
            y = h - 26
            D.dot(cr, x0 + 4, y + 9, 3, "phosphor")
            D.text(cr, x0 + 14, y, busy["name"], 11, "soft", "semibold", width=x1 - x0 - 70)
            D.label(cr, x1, y + 1, self._count(busy), "phosphor", size=10, align="right")
            self._hint(busy, x0, y - 2, x1 - x0, 20)

    @staticmethod
    def _count(g):
        if g.get("players") is None:
            return STATUS.get(g.get("status"), STATUS["unknown"])[0]
        return f"{g['players']}/{g['players_max']}" if g.get("players_max") else str(g["players"])

    def _hint(self, g, x, y, w, h):
        st = STATUS.get(g.get("status"), STATUS["unknown"])[0].lower()
        bits = [f"{g.get('name')} ({g.get('game') or 'a game server'}): {st}"]
        if g.get("players") is not None:
            bits.append(f"{g['players']} of {g.get('players_max') or '?'} players")
        if g.get("player_names"):
            bits.append("on now: " + ", ".join(g["player_names"][:12]))
        if g.get("version"):
            bits.append(f"version {g['version']}")
        if g.get("latency_ms") is not None:
            bits.append(f"answers in {g['latency_ms']:.0f} ms")
        if g.get("uptime_s"):
            bits.append(f"up {S.duration(g['uptime_s'])}")
        if g.get("error"):
            bits.append(g["error"])
        if g.get("players") is None and g.get("source") and g.get("status") == "running":
            bits.append("its source doesn't count players")
        tip = "; ".join(bits) + "."
        addr = g.get("address")
        if addr:
            tip += f" Click to copy its address ({addr}) for the game's server list."
        self.region(x, y, w, h, tip, (lambda a=addr: panels.copy_text(a.split("://")[-1])) if addr else None)

    def _rows(self, cr, items, x0, x1, top, bottom, detail=False):
        y = top
        rh = 40 if detail else 26
        shown = 0
        for g in items:
            if y + rh > bottom:
                break
            label, col = STATUS.get(g.get("status"), STATUS["unknown"])
            D.dot(cr, x0 + 4, y + 9, 3.2, col, glow=g.get("status") == "running")
            D.text(cr, x0 + 16, y + 1, g.get("name") or "?", 12, "soft", "semibold", width=(x1 - x0) * 0.42)
            D.label(cr, x0 + 16 + (x1 - x0) * 0.42 + 6, y + 3, g.get("game") or "", "static", size=10)
            cnt = self._count(g)
            D.text(cr, x1, y + 1, cnt, 12, col if g.get("players") is None else "phosphor", "semibold", align="right")
            if g.get("players_max"):
                D.bar(cr, x0 + 16, y + 19, x1 - x0 - 16, 2, (g.get("players") or 0) / g["players_max"], "phosphor")
            if detail:
                sub = g.get("motd") or g.get("error") or ""
                bits = [b for b in (g.get("version") and f"v{g['version']}",
                                    g.get("latency_ms") is not None and f"{g['latency_ms']:.0f} ms",
                                    g.get("uptime_s") and f"up {S.duration(g['uptime_s'])}",
                                    g.get("cpu_pct") is not None and f"CPU {g['cpu_pct']:.0f}%",
                                    g.get("mem_bytes") and S.human(g["mem_bytes"], digits=1)) if b]
                D.text(cr, x0 + 16, y + 23, " · ".join(bits + ([sub] if sub else [])), 10, "static", "regular",
                       width=x1 - x0 - 16)
            self._hint(g, x0, y - 2, x1 - x0, rh - 2)
            y += rh
            shown += 1
        if shown < len(items):
            D.label(cr, x1, bottom - 12, f"+{len(items) - shown} MORE", "static", size=10, align="right")
            self.region(x1 - 90, bottom - 14, 90, 14, f"{len(items) - shown} more server(s); make the panel taller")

    def _cards(self, cr, items, x0, x1, top, bottom, names):
        """Wide: one row of cards. Large: a grid of cards with more in each, and under them who's on."""
        n = len(items)
        gap = 10
        cols = max(1, min(n, int((x1 - x0 + gap) // ((260 if names else 170) + gap)) or 1))
        if not names:
            rows, ch = 1, bottom - top
        else:
            need = -(-n // cols)
            on = sum(len(g.get("player_names") or []) for g in items if g.get("status") == "running")
            roster = (30 + 20 * -(-on // max(1, int((x1 - x0) // 240)))) if on else 0
            ch = max(150, min(260, (bottom - top - roster - (need - 1) * gap) / need))
            rows = max(1, min(need, int((bottom - top + gap) // (ch + gap))))
        cw = (x1 - x0 - (cols - 1) * gap) / cols
        shown = 0
        for i, g in enumerate(items):
            r_, c_ = divmod(i, cols)
            if r_ >= rows:
                break
            self._card(cr, g, x0 + c_ * (cw + gap), top + r_ * (ch + gap), cw, ch, names)
            shown += 1
        if shown < n:
            D.label(cr, x1, bottom - 10, f"+{n - shown} MORE", "static", size=10, align="right")
            self.region(x1 - 90, bottom - 12, 90, 12, f"{n - shown} more server(s); make the panel bigger")
        if names:
            self._roster(cr, items, x0, x1, top + rows * (ch + gap) + 6, bottom - 16)

    def _roster(self, cr, items, x0, x1, top, bottom):
        """Everyone the servers name, with where they're playing."""
        on = [(p, g["name"]) for g in items if g.get("status") == "running" for p in g.get("player_names") or []]
        if not on or bottom - top < 40:
            return
        D.label(cr, x0, top, f"ON NOW · {len(on)}", "dim", size=10)
        D.rule(cr, x0 + 110, top + 7, x1, "dim", 0.3)
        self.region(x0, top, x1 - x0, 16, "The players the servers name right now, and where they are (a server "
                    "that hides its players isn't listed)")
        y = top + 20
        colw = 240
        cols = max(1, int((x1 - x0) // colw))
        for i, (p, srv) in enumerate(on):
            c_, r_ = i % cols, i // cols
            yy = y + r_ * 20
            if yy + 18 > bottom:
                break
            xx = x0 + c_ * colw
            D.dot(cr, xx + 4, yy + 8, 2.6, "phosphor")
            tw = D.text(cr, xx + 14, yy, p, 11, "soft", "semibold", width=colw - 110)[0]
            D.text(cr, xx + 20 + tw, yy + 1, srv, 10, "static", "regular", width=colw - tw - 40)
            self.region(xx, yy - 2, colw - 10, 18, f"{p} is playing on {srv}")

    def _card(self, cr, g, x, y, w, h, names):
        label, col = STATUS.get(g.get("status"), STATUS["unknown"])
        up = g.get("status") == "running"
        D.src(cr, "guard", 0.55)
        cr.rectangle(x, y, w, h)
        cr.fill()
        D.src(cr, col, 0.7 if up else 0.4)
        cr.set_line_width(1)
        cr.rectangle(x + 0.5, y + 0.5, w - 1, h - 1)
        cr.stroke()
        D.src(cr, col, 0.9)
        cr.rectangle(x, y, 3, h)
        cr.fill()
        D.text(cr, x + 12, y + 8, g.get("name") or "?", 12, "soft", "semibold", width=w - 70)
        D.label(cr, x + w - 8, y + 10, label, col, size=10, align="right")
        D.label(cr, x + 12, y + 26, g.get("game") or "", "static", size=10)
        big = min(30, max(14, h * 0.24))
        cnt = str(g["players"]) if g.get("players") is not None else "--"
        tw = D.text(cr, x + 12, y + 44, cnt, big, "phosphor" if up and g.get("players") else "static", "bold",
                    glow=bool(up and g.get("players")))[0]
        if g.get("players_max"):
            D.text(cr, x + 16 + tw, y + 44 + big - 16, f"/ {g['players_max']}", 11, "static", "regular")
        yy = y + 50 + big
        if g.get("players_max"):
            D.cells(cr, x + 12, yy, w - 24, 6, (g.get("players") or 0) / g["players_max"], n=max(6, min(20, g["players_max"])),
                    warn=0.9, crit=1.01)
            yy += 14
        meta = [b for b in (g.get("version") and f"v{g['version']}",
                            g.get("latency_ms") is not None and f"{g['latency_ms']:.0f} ms",
                            g.get("uptime_s") and f"up {S.duration(g['uptime_s'])}",
                            g.get("cpu_pct") is not None and f"CPU {g['cpu_pct']:.0f}%",
                            g.get("mem_bytes") and S.human(g["mem_bytes"], digits=1)) if b]
        if meta and yy + 14 <= y + h:
            D.text(cr, x + 12, yy, " · ".join(meta), 10, "static", "regular", width=w - 24)
            yy += 16
        if names:
            if g.get("motd") and yy + 14 <= y + h:
                D.text(cr, x + 12, yy, g["motd"], 10, "soft", "regular", width=w - 24)
                yy += 18
            px = x + 12
            for p in g.get("player_names") or []:
                pw = D.layout(cr, p, 10, "medium").get_pixel_size()[0] + 12
                if px + pw > x + w - 8:
                    px = x + 12
                    yy += 18
                if yy + 16 > y + h - 4:
                    break
                D.src(cr, "phosphor", 0.14)
                cr.rectangle(px, yy, pw, 15)
                cr.fill()
                D.text(cr, px + 6, yy + 1, p, 10, "phosphor", "medium")
                px += pw + 4
            if up and not g.get("player_names") and g.get("players") and yy + 14 <= y + h:
                D.text(cr, x + 12, yy, "the server doesn't list who", 10, "static", "regular")
        self._hint(g, x, y, w, h)
