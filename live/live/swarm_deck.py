"""SUPER+SHIFT+S — the agent swarm: every repo as a body in one system, every herdr
agent as a starship holding station at the repo it works in.

Bodies: the repos under ~/github.com/<org> for each org (config.toml [swarm]) plus the
dotfiles, one orbit per org. Size = commits in the last 14 days; the ring = the latest
CI run (gh); an amber halo = uncommitted or unpushed work.

Ships (one instanced hull, starship.py): a herdr agent per ship, holding station at the
repo its cwd is in; when it moves to another repo the ship comes about and travels.
  working  steady phosphor running lights, engines lit, slow cruise
  idle     lights dimmed, engines at idle, drifting
  blocked  amber beacon blinking calmly on the spire, the ship turns to face you
  error    a red flicker, then it limps out
  gone     the lights go out and it jumps away
New agents warp in (a streak and a flash, then they decelerate into position) with a
quiet cue from the live layer's sounds (mute respected). Size grows modestly with how
long the agent has run (first seen, kept across opens). At most 24 ships; the rest are
counted per repo.

Zoom (scroll toward the cursor): ships keep a readable size and, zoomed into a repo,
carry their names and status; every repo's name appears as there is room.

Verbs: point <repo or agent>, focus <repo or agent>, clear. point and focus fly the
camera to the target (and follow a ship while it moves).
Polling while open: herdr 2 s, git state 60 s, CI 180 s (top repos only, cached 10 min).
"""
import json
import math
import os
import subprocess
import threading
import time

import numpy as np

from . import sources
from .deckkit import TAU, Deck3D, ascii_, frame_panel, wrap
from .glkit import col
from .starship import ShipPainter
from .zoomcam import lod

STATE = os.path.join(os.environ.get("XDG_STATE_HOME", os.path.expanduser("~/.local/state")), "bromigos-live",
                     "swarm-seen.json")
CI_CACHE = os.path.join(os.environ.get("XDG_CACHE_HOME", os.path.expanduser("~/.cache")), "bromigos-live", "ci.json")
# the org rings (sources.rings(): config.toml [swarm] orgs and rings), read when the deck opens
FLEET = 24
VECTOR_AT = (-1.28, 0.55, -0.6)


def status_of(a):
    s = (a.get("agent_status") or "").lower()
    if s in ("working", "busy", "running"):
        return "working"
    if s in ("idle", "ready", "done"):
        return "idle"
    if s in ("blocked", "waiting", "needs_input", "permission", "attention"):
        return "blocked"
    if s in ("error", "failed", "crashed", "exited"):
        return "error"
    return "idle"


class Ship:
    def __init__(self, key, t, delay):
        self.key = key
        self.born = t + delay
        self.pos = None
        self.vel = np.zeros(3)
        self.yaw = 0.0
        self.roll = 0.0
        self.orbit = (hash(key) % 1000) / 1000 * TAU
        self.status = "working"
        self.repo = None
        self.agent = {}
        self.gone_t = None
        self.err_t = None
        self.warp_from = None
        self.light = np.array([0.0, 0.0, 0.0, 0.0])
        self.age_h = 0.0


class SwarmDeck(Deck3D):
    name = "swarm"
    title = "SWARM // THE AGENTS AT WORK"
    hint = "VECTOR: bromigos-live swarm point <repo>"
    zoom = (0.7, 9.0)

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self.pitch, self.yaw, self.persp, self.spin = 0.78, 0.2, 3.8, 0.02
        s = self.s
        self.L["center"] = (890 * s, 700 * s, 530 * s)
        self.ring = sources.rings()
        self.rs = []
        self.git = {}
        self.ci = self._load_ci()
        self.agents = []
        self.ships = {}
        self.first_herdr = True
        self.seen = self._load_seen()
        self.pointer = None        # (target id, t)
        self.painter = None
        self.last_out = {}         # pane id -> last line
        self.planets = {}          # repo path -> xyz
        self.ready_ = False
        self.t_last = None
        self.poll_every(self._poll_herdr, 2, "herdr")
        self.poll_every(self._poll_git, 60, "git")
        self.poll_every(self._poll_ci, 180, "ci")

    def ready(self):
        return self.ready_ and bool(self.git) and (bool(self.ci) or time.monotonic() - self.t0 > 20)

    # ------------------------------------------------------------------ data
    @staticmethod
    def _load_seen():
        try:
            with open(STATE) as f:
                return json.load(f)
        except (OSError, ValueError):
            return {}

    def _save_seen(self):
        os.makedirs(os.path.dirname(STATE), exist_ok=True)
        cut = time.time() - 7 * 86400
        with open(STATE + ".part", "w") as f:
            json.dump({k: v for k, v in self.seen.items() if v > cut}, f)
        os.replace(STATE + ".part", STATE)

    @staticmethod
    def _load_ci():
        try:
            with open(CI_CACHE) as f:
                c = json.load(f)
            return c["ci"] if time.time() - c["at"] < 600 else {}
        except (OSError, ValueError, KeyError):
            return {}

    def _poll_git(self):
        self.rs = sources.repos()
        self.git = {r["path"]: sources.git_state(r) for r in self.rs}
        self._layout()
        self.built_at = None

    def _poll_ci(self):
        if not self.git:
            time.sleep(4)
        if self.ci and os.path.exists(CI_CACHE) and time.time() - os.path.getmtime(CI_CACHE) < 600:
            return
        busy = {self._repo_of(a.get("cwd") or "") for a in self.agents}
        top = sorted(self.rs, key=lambda r: -(self.git.get(r["path"], {}).get("commits14", 0)))[:12]
        out = dict(self.ci)
        for r in {r["path"]: r for r in top + [r for r in self.rs if r["path"] in busy]}.values():
            if r.get("slug"):
                try:
                    out[r["path"]] = sources.latest_ci(r["slug"])
                except Exception:
                    pass
        self.ci = out
        os.makedirs(os.path.dirname(CI_CACHE), exist_ok=True)
        with open(CI_CACHE, "w") as f:
            json.dump({"at": time.time(), "ci": out}, f)
        self.built_at = None

    def _poll_herdr(self):
        self.agents = sources.herdr()
        now = time.time()
        for a in self.agents:
            self.seen.setdefault(self._key(a), now)
        self._save_seen()
        self.ready_ = True

    @staticmethod
    def _key(a):
        return a.get("terminal_id") or a.get("pane_id") or json.dumps(a.get("agent_session"))

    def _repo_of(self, cwd):
        best = None
        for r in self.rs:
            if cwd == r["path"] or cwd.startswith(r["path"] + "/"):
                if best is None or len(r["path"]) > len(best):
                    best = r["path"]
        if best:
            return best
        for org in self.ring:
            if f"/github.com/{org}" in cwd:
                return "org:" + org
        return "org:" + (list(self.ring)[-1] if self.ring else "")

    def _layout(self):
        by = {}
        for r in self.rs:
            by.setdefault(r["org"], []).append(r)
        pl = {}
        for oi, (org, R) in enumerate(self.ring.items()):
            rr = sorted(by.get(org, []), key=lambda r: r["name"])
            n = len(rr) + 1
            tilt = (oi - 1) * 0.06
            for k, r in enumerate([None] + rr):
                a = k / n * TAU + oi * 0.7
                p = (math.cos(a) * R, math.sin(a) * R * tilt, math.sin(a) * R)
                pl[r["path"] if r else "org:" + org] = p
        self.planets = pl

    # ------------------------------------------------------------------ ships
    def _target(self, sh, idx_at_repo):
        base = np.array(self.planets.get(sh.repo, (0, 0, 0)))
        r = 0.075 + 0.028 * idx_at_repo
        a = sh.orbit
        return base + np.array([math.cos(a) * r, 0.03 + 0.012 * (idx_at_repo % 3), math.sin(a) * r])

    def _viewer_yaw(self):
        p = self.stage.painter
        d = p.rot[2].T @ np.array([0.0, 0.0, -1.0], np.float32)
        return math.atan2(d[0], d[2])

    def animate(self, t, d):
        dt = 0.0 if self.t_last is None else min(t - self.t_last, 0.1)
        self.t_last = t
        live = {self._key(a): a for a in self.agents}
        order = sorted(live, key=lambda k: self.seen.get(k, 0))
        for i, k in enumerate(order):
            if k not in self.ships:
                delay = 0.35 * i if self.first_herdr else 0.0
                self.ships[k] = Ship(k, t, delay)
                if not self.first_herdr and self.app:
                    self.app.sound.play("sweep")          # a warp-in cue (mute respected)
        if live:
            self.first_herdr = False
        for k, sh in list(self.ships.items()):
            a = live.get(k)
            if a is None and sh.gone_t is None:
                sh.gone_t = t
            if a is not None:
                sh.agent = a
                new_repo = self._repo_of(a.get("cwd") or "")
                sh.repo = new_repo
                st = status_of(a)
                if st == "error" and sh.status != "error":
                    sh.err_t = t
                sh.status = st
            sh.age_h = (time.time() - self.seen.get(k, time.time())) / 3600
        # station keeping
        per_repo = {}
        for k, sh in self.ships.items():
            per_repo.setdefault(sh.repo, []).append(k)
        for k, sh in list(self.ships.items()):
            if t < sh.born:
                continue
            idx = per_repo.get(sh.repo, [k]).index(k)
            spd = {"working": 0.10, "idle": 0.025, "blocked": 0.0, "error": 0.0}.get(sh.status, 0.03)
            sh.orbit += spd * dt
            tgt = self._target(sh, idx)
            if sh.pos is None:                               # warp in: from far behind, along the approach
                dirn = tgt / max(np.linalg.norm(tgt), 1e-3)
                sh.warp_from = tgt - dirn * 2.4 + np.array([0, 0.25, 0])
                sh.pos = sh.warp_from.copy()
            age = t - sh.born
            if age < 0.6:                                    # the streak
                k_ = age / 0.6
                sh.pos = sh.warp_from + (tgt - sh.warp_from) * (1 - (1 - k_) ** 4) * 0.92
                v = tgt - sh.warp_from
            else:
                if sh.err_t is not None and t - sh.err_t > 6:      # limps out
                    tgt = tgt + (tgt / max(np.linalg.norm(tgt), 1e-3)) * (t - sh.err_t - 6) * 0.08
                if sh.gone_t is not None and t - sh.gone_t > 1.2:  # jumps away
                    sh.pos = sh.pos + np.array([math.sin(sh.yaw), 0.05, math.cos(sh.yaw)]) * \
                        (t - sh.gone_t - 1.2) ** 2 * 3.0 * dt * 30
                else:
                    diff = tgt - sh.pos
                    dist = float(np.linalg.norm(diff))
                    maxv = 0.35 if dist > 0.2 else 0.08 + dist
                    sh.vel = sh.vel * 0.9 + (diff / max(dist, 1e-4)) * min(maxv, dist * 2.2) * 0.1
                    sh.pos = sh.pos + sh.vel * dt
                v = sh.vel if float(np.linalg.norm(sh.vel)) > 0.02 else \
                    np.array([-math.sin(sh.orbit), 0, math.cos(sh.orbit)])  # tangent while holding station
            want = self._viewer_yaw() if sh.status == "blocked" else math.atan2(v[0], v[2])
            dy = (want - sh.yaw + math.pi) % TAU - math.pi
            sh.yaw += dy * min(1.0, dt * 2.0)
            sh.roll = max(-0.4, min(0.4, -dy * 0.8))
            if sh.gone_t is not None and t - sh.gone_t > 2.2:
                del self.ships[k]
            if sh.err_t is not None and t - sh.err_t > 14:
                del self.ships[k]

    def _ship_draw_list(self, t):
        out = []
        for k, sh in list(self.ships.items())[:FLEET]:
            if sh.pos is None or t < sh.born:
                continue
            st = sh.status
            L = {"working": (1.0, 0.85, 1.0, 1.0), "idle": (0.5, 0.45, 0.25, 0.35), "blocked": (0.8, 0.7, 0.45, 0.55),
                 "error": (0.7, 0.6, 0.3, 0.8)}.get(st, (0.5, 0.5, 0.3, 0.4))
            colour, beacon = col("phosphor")[:3], 0.35
            if st == "blocked":
                colour, beacon = col("amber")[:3], 0.3 + 0.7 * (0.5 + 0.5 * math.sin(t * TAU * 0.55))    # calm, ~0.55 Hz
            elif st == "error":
                flick = 0.55 + 0.45 * (0.5 + 0.5 * math.sin(t * 7.0) * math.sin(t * 2.3))
                colour, beacon = col("danger")[:3], flick
                L = tuple(x * flick for x in L)
            elif st == "idle":
                beacon = 0.18
            a = 1.0
            if sh.gone_t is not None:
                k_ = min((t - sh.gone_t) / 1.2, 1.0)
                L = tuple(x * (1 - k_) for x in L)
                beacon *= 1 - k_
                a = 1.0 - max(0.0, (t - sh.gone_t - 1.2) / 1.0)
            if sh.err_t is not None and t - sh.err_t > 6:
                a = max(0.0, 1.0 - (t - sh.err_t - 6) / 8)
            scale = 0.15 * (1.0 + 0.35 * min(sh.age_h / 4.0, 1.0))
            scale *= (self.cam.z if self.cam else 1.0) ** -0.45      # zoomed in: bigger, not huge
            out.append({"pos": tuple(sh.pos), "scale": scale, "rot": (sh.yaw, 0.0, sh.roll), "alpha": a,
                        "lights": L, "colour": colour, "beacon": beacon, "key": k})
        return out

    def emit_extra(self, t, u):
        if self.painter is None:
            self.painter = ShipPainter()
        self.draw_list = self._ship_draw_list(t)
        self.painter.draw(self.stage.painter, (float(self.w), float(self.h)), t, self.draw_list,
                          fade=u.get("fade", 1.0))

    # ------------------------------------------------------------------ verbs
    def _find(self, q):
        q = q.lower().strip()
        for k, sh in self.ships.items():
            title = (sh.agent.get("terminal_title_stripped") or "").lower()
            if q and (q in title or q == (sh.agent.get("pane_id") or "").lower()):
                return "ship:" + k
        for r in self.rs:
            if q and q == r["name"].lower():
                return "repo:" + r["path"]
        for r in self.rs:
            if q and q in r["name"].lower():
                return "repo:" + r["path"]
        return None

    def command(self, verb, args):
        if verb in ("point", "focus"):
            tgt = self._find(args)
            if not tgt:
                return f"no repo or agent matches '{args}'"
            if verb == "point":
                self.pointer = (tgt, self.now())
            self.select(tgt)
            if self.cam:
                self.cam.fly_to(lambda: self._pos_of(tgt), 4.5 if tgt.startswith("ship:") else 3.5)
            return f"{verb}ing at {tgt.split(':', 1)[1].rsplit('/', 1)[-1]}"
        if verb == "clear":
            self.pointer = None
            self.select(None)
            if self.cam:
                self.cam.reset()
            return "cleared"
        return "swarm verbs: point <repo|agent>, focus <repo|agent>, clear"

    def _pos_of(self, ident):
        if ident and ident.startswith("ship:"):
            sh = self.ships.get(ident[5:])
            return tuple(sh.pos) if sh is not None and sh.pos is not None else None
        if ident and ident.startswith("repo:"):
            return self.planets.get(ident[5:])
        return None

    # ------------------------------------------------------------------ build
    def rebuild_due(self, t):
        return self.built_at is None or t - self.built_at >= 0.1

    def build(self, b, d, t):
        s = self.s
        T = 0.05
        n_ag = len(self.agents)
        by = {}
        for a in self.agents:
            by[status_of(a)] = by.get(status_of(a), 0) + 1
        self.header(b, f"{len(self.rs)} REPOS · {n_ag} AGENTS · " + " · ".join(f"{v} {k.upper()}" for k, v in by.items()))
        x, y, w, h = self.L["panel"]
        frame_panel(b, x, y, w, h, "THE SYSTEM", T + 0.05, sub="SIZE = COMMITS (14 D) · RING = CI · AMBER = UNPUSHED")
        pts, ids = [], []
        z = self.cam.z
        pp = self.stage.painter
        labels = self.cam.labels(self.stage.atlas, pp, s, cap=60)
        quiet_a, ship_a = lod(z, 1.3, 2.2), lod(z, 1.7, 2.8)
        # orbits and org hubs
        for org, R in self.ring.items():
            ring = [(math.cos(i / 120 * TAU) * R, 0.0, math.sin(i / 120 * TAU) * R) for i in range(121)]
            for i in range(120):
                b.line(ring[i], ring[i + 1], col("guard", 0.9), space=2, reveal=T + 0.1)
            hub = self.planets.get("org:" + org)
            if hub:
                b.arc(hub, 0, 4 * s, 0, TAU, col("dim"), kind=2, space=2)
                labels.add(9, hub, org.upper(), "xs", 2, dx=10, dy=-8, colour=col("dim"), force=True)
        b.arc((0, 0, 0), 0, 10 * s, 0, TAU, col("white", 0.9), kind=2, space=2)
        labels.add(9, (0, 0, 0), "THE WICK", "xs", 3, dx=14, dy=-10, colour=col("soft"), force=True)
        maxc = max([g.get("commits14", 0) for g in self.git.values()] or [1]) or 1
        busy = {}
        for sh in self.ships.values():
            busy[sh.repo] = busy.get(sh.repo, 0) + 1
        for r in self.rs:
            p = self.planets.get(r["path"])
            g = self.git.get(r["path"])
            if p is None or g is None:
                continue
            act = math.sqrt(g["commits14"] / maxc)
            rad = (2.5 + 11 * act) * s
            b.arc(p, 0, rad, 0, TAU, col("soft" if g["commits14"] else "dim", 0.55 + 0.45 * act), kind=2, space=2,
                  reveal=T + 0.3)
            c = self.ci.get(r["path"])
            if c:
                con = c.get("conclusion") or ""
                cc = "phosphor" if con == "success" else "danger" if con in ("failure", "timed_out") else \
                    "amber" if c.get("status") != "completed" else "dim"
                b.arc(p, rad + 4 * s, rad + 5.6 * s, 0, TAU * (1 if c.get("status") == "completed" else (t * 0.4) % 1),
                      col(cc), space=2, reveal=T + 0.4)
            if g["dirty"] or g["ahead"]:
                b.arc(p, 0, rad * 2.4, 0, TAU, col("amber", 0.35 + 0.1 * math.sin(t * 1.5)), kind=2, space=2)
            lab = r["name"].upper() + (f"  +{busy[r['path']] - FLEET}" if busy.get(r["path"], 0) > FLEET else "")
            active = g["commits14"] or busy.get(r["path"]) or g["dirty"] or g["ahead"]
            if active:                       # zoomed out exactly as before; zoomed in, by room
                labels.add(6 + act + busy.get(r["path"], 0), p, lab, "xs", 1.2, dx=rad / s + 8, dy=4,
                           colour=col("soft" if busy.get(r["path"]) else "dim"), force=z <= 1.05)
            elif quiet_a > 0.0:
                labels.add(2, p, lab, "xs", 1.2, dx=rad / s + 8, dy=4, colour=col("dim", 0.8 * quiet_a))
            pts.append(p)
            ids.append("repo:" + r["path"])
        # warp streaks and arrival flashes
        for k, sh in self.ships.items():
            if sh.pos is None or t < sh.born:
                continue
            age = t - sh.born
            if age < 1.1:
                tail = tuple(sh.warp_from + (sh.pos - sh.warp_from) * max(0.0, (age - 0.35) / 0.6))
                b.line(tail, tuple(sh.pos), col("white", max(0.0, 1 - age / 1.1)), width=2.2, space=2)
                b.line(tail, tuple(sh.pos), col("phosphor", 0.3 * max(0.0, 1 - age / 1.1)), width=8, space=2)
            if 0.5 < age < 1.4:
                k_ = (age - 0.5) / 0.9
                b.arc(tuple(sh.pos), 0, (8 + 26 * k_) * s, 0, TAU, col("white", 1 - k_), kind=2, space=2)
            if sh.gone_t is not None and t - sh.gone_t > 1.2:
                back = tuple(sh.pos - np.array([math.sin(sh.yaw), 0.05, math.cos(sh.yaw)]) * 0.6)
                b.line(back, tuple(sh.pos), col("soft", 0.7), width=2, space=2)
            if ship_a > 0.0 and sh.gone_t is None:
                title = ascii_((sh.agent.get("terminal_title_stripped") or "").lstrip("◐✳◑◒◓●○ "), 28)
                c_ = {"working": "phosphor", "blocked": "amber", "error": "danger"}.get(sh.status, "soft")
                hull = 0.15 * (1.0 + 0.35 * min(sh.age_h / 4.0, 1.0)) * z ** 0.55 * self.L["center"][2]  # px
                labels.add(8, tuple(sh.pos), f"{title.upper() or 'AGENT'} · {sh.status.upper()}", "xs", 1.0,
                           dx=0.55 * hull + 10, dy=-0.3 * hull - 6, colour=col(c_, 0.95 * ship_a))
            pts.append(tuple(sh.pos))
            ids.append("ship:" + k)
        # VECTOR's pointer
        if self.pointer and t - self.pointer[1] < 15:
            p = self._pos_of(self.pointer[0])
            if p is not None:
                env = max(0.0, 1 - max(0.0, t - self.pointer[1] - 10) / 5)
                b.arc(VECTOR_AT, 0, 6 * s, 0, TAU, col("white", env), kind=2, space=2)
                b.text("VECTOR", *VECTOR_AT[:2], col("white", env), font="xs", track=3, space=2, z=VECTOR_AT[2],
                       dx=10, dy=-8)
                b.line(VECTOR_AT, p, col("white", 0.8 * env), width=1.6, space=2)
                b.arc(VECTOR_AT, 0, 3 * s, 0, TAU, col("white", env), kind=2, space=2, end=p, speed=0.8)
                b.arc(p, 20 * s, 21.5 * s, 0, TAU, col("white", env), segs=4, gap=0.5, spin=1.0, space=2)
        if self.selected:
            p = self._pos_of(self.selected)
            if p is not None:
                b.arc(p, 15 * s, 16.4 * s, 0, TAU, col("soft"), segs=4, gap=0.5, spin=-1.2, space=2)
        self.pick_pts = np.array(pts, np.float32).reshape(-1, 3)
        self.pick_ids = ids
        labels.place(b)
        if self.hover:
            lab, lines = self._describe(self.hover)
            self.hover_tip(b, lab, lines, "CLICK TO FOCUS" if self.hover.startswith("ship:") else "CLICK FOR DETAILS")
        self._side(b, t, T)

    def _describe(self, ident):
        if ident.startswith("ship:"):
            sh = self.ships.get(ident[5:])
            if not sh:
                return "GONE", []
            a = sh.agent
            pid = a.get("pane_id")
            if pid and pid not in self.last_out:
                self.last_out[pid] = "…"
                threading.Thread(target=self._read_last, args=(pid,), daemon=True).start()
            title = ascii_((a.get("terminal_title_stripped") or "").lstrip("◐✳◑◒◓●○ "), 40)
            return f"{a.get('agent', 'agent')} · {title}", [
                f"REPO {os.path.basename(sh.repo or '') or sh.repo}", f"STATUS {sh.status}",
                f"RUNNING {sh.age_h:.1f} H (FIRST SEEN BY THE SWARM)", f"LAST: {self.last_out.get(pid, '')}"]
        r = ident[5:]
        g = self.git.get(r, {})
        c = self.ci.get(r) or {}
        return os.path.basename(r), [f"BRANCH {g.get('branch')} · {g.get('commits14', 0)} COMMITS IN 14 DAYS",
                                     f"DIRTY {g.get('dirty', 0)} · UNPUSHED {g.get('ahead', 0)}",
                                     f"CI {c.get('workflowName', '-')}: {c.get('conclusion') or c.get('status') or 'no runs'}",
                                     f"LAST: {g.get('last_subject', '')}"]

    def _read_last(self, pid):
        out = sources.run(["herdr", "pane", "read", pid, "--source", "recent", "--lines", "40"], 5)
        keep = [l.strip() for l in out.splitlines() if l.strip() and not set(l.strip()) <= set("─━═│┃ ❯>⏵·")
                and "shift+tab" not in l and "auto mode" not in l]
        self.last_out[pid] = ascii_(keep[-1], 56) if keep else "(nothing yet)"
        self.built_at = None

    def _side(self, b, t, T):
        s = self.s
        x, y, w, h = self.L["side"]
        frame_panel(b, x, y, w, h, "THE FLEET", T + 0.1, sub="HERDR AGENTS, NEWEST FIRST")
        yy = y + 70 * s
        ships = sorted(self.ships.values(), key=lambda sh: -self.seen.get(sh.key, 0))
        c_of = {"working": "phosphor", "idle": "dim", "blocked": "amber", "error": "danger"}
        for sh in ships[:12]:
            a = sh.agent
            title = ascii_((a.get("terminal_title_stripped") or "").lstrip("◐✳◑◒◓●○ "), 34)
            b.arc((x + 26 * s, yy - 5 * s), 0, 4 * s, 0, TAU, col(c_of.get(sh.status, "dim")), kind=2)
            where = sh.repo[4:] + " (org root)" if (sh.repo or "").startswith("org:") else os.path.basename(sh.repo or "")
            b.text(where.upper()[:30], x + 42 * s, yy, col("soft"), font="xs", track=1)
            b.text(sh.status.upper(), x + w - 18 * s, yy, col(c_of.get(sh.status, "dim")), font="xs", track=1.5,
                   align="r")
            b.text(title.upper(), x + 42 * s, yy + 17 * s, col("dim"), font="xs", track=0.5)
            yy += 42 * s
        if not ships:
            b.text("NO HERDR AGENTS RUNNING", x + 18 * s, yy, col("dim"), font="xs", track=2)
        self.buttons = []
        if self.selected and self.selected.startswith("ship:") and self.selected[5:] in self.ships:
            sh = self.ships[self.selected[5:]]
            cy = y + h - 250 * s
            b.plate(x + 12 * s, cy, w - 24 * s, 236 * s, 0.94)
            b.brackets(x + 12 * s, cy, w - 24 * s, 236 * s, col("soft"), l=10, reveal=self.sel_t)
            lab, lines = self._describe(self.selected)
            b.text(ascii_(lab, 44).upper(), x + 26 * s, cy + 28 * s, col("white"), font="m", track=1)
            for k, ln in enumerate(lines):
                for j, part in enumerate(wrap(ascii_(ln).upper(), 56)[:2]):
                    b.text(part, x + 26 * s, cy + 56 * s + (k * 2 + j) * 0 + k * 22 * s + j * 18 * s, col("soft"),
                           font="xs", track=0.6)
            for i, (label, act) in enumerate((("READ OUTPUT (VECTOR)", "read"), ("SEND MESSAGE (VECTOR)", "send"))):
                bx, by, bw, bh = x + 26 * s + i * 340 * s, cy + 186 * s, 320 * s, 34 * s
                b.rect(bx, by, bw, bh, col("soft"))
                b.text(label, bx + bw / 2, by + 23 * s, col("soft"), font="xs", track=1.5, align="c")
                self.buttons.append((bx, by, bw, bh, act, sh))

    def side_click(self, x, y):
        for bx, by, bw, bh, act, sh in getattr(self, "buttons", []):
            if bx <= x <= bx + bw and by <= y <= by + bh:
                a = sh.agent
                repo = os.path.basename(sh.repo or "")
                q = (f"Read the recent output of the herdr agent in pane {a.get('pane_id')} ({repo}) and tell me "
                     "briefly what it is doing and whether it needs me." if act == "read" else
                     f"I want to send a message to the herdr agent in pane {a.get('pane_id')} ({repo}). "
                     "Ask me what to send, then send it.")
                from . import VECTOR_CMD
                if not VECTOR_CMD:
                    self.toast = ("VECTOR isn't installed", self.now(), "amber")
                    return True
                subprocess.Popen([VECTOR_CMD, "ask", q], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                 start_new_session=True)
                self.toast = (f"asked VECTOR to {act} {repo}", self.now(), "soft")
                return True
        return False


DECK = SwarmDeck
