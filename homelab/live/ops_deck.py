"""SUPER+SHIFT+O — ops theater: what VECTOR (and the operator) do to the lab, made visible.

The stage runs left to right, as work flows:
  VECTOR ─ WORKSTATION ─▶ GITHUB ─▶ CI CHECKS ─▶ ARGO ─▶ CLUSTER (the rack hologram)

  * a git push (feed `git_push`, or seen in a repo's remote-tracking reflog) runs as a
    beam from the workstation to GitHub, then that commit's CI checks (gh check-runs)
    light one by one as they start, pass or fail;
  * Argo apps that change sync or health (Prometheus argocd_app_info) pulse into the
    cluster; feed `deploy` events do the same;
  * pods (kube_pod_info): a pod that disappears fades out, a new one assembles beside
    the rack — a restart reads as old-out, new-in; feed `restart` events flag them;
  * VECTOR's background tasks (feed `task`) ring him as progress arcs; his tool calls
    (`tool_start`/`tool_end`) tick past underneath.
Polling (only while this deck is open): reflogs 5 s, pods + Argo 10 s, CI 12 s while a
push is in flight. Verbs: focus <repo>, clear.
"""
import math
import time

from . import sources
from .deckkit import TAU, Deck3D, ascii_, frame_panel
from .glkit import col

ST = {"vector": (-1.25, 0.30, 0.0), "ws": (-0.86, 0.0, 0.0), "gh": (-0.42, 0.18, 0.0), "ci0": (-0.12, 0.18, 0.0),
      "ci1": (0.30, 0.18, 0.0), "argo": (0.60, 0.06, 0.0), "cluster": (0.98, -0.02, 0.0)}


def _lerp(a, b, k):
    return tuple(x + (y - x) * k for x, y in zip(a, b))


def _box(b, c, sx, sy, sz, color, space=2, reveal=0.0):
    x, y, z = c
    v = [(x + dx * sx, y + dy * sy, z + dz * sz) for dx in (-1, 1) for dy in (-1, 1) for dz in (-1, 1)]
    for a, bb in ((0, 1), (2, 3), (4, 5), (6, 7), (0, 2), (1, 3), (4, 6), (5, 7), (0, 4), (1, 5), (2, 6), (3, 7)):
        b.line(v[a], v[bb], color, space=space, reveal=reveal)


class OpsDeck(Deck3D):
    name = "ops"
    title = "OPS THEATER // WHAT IS BEING DONE TO THE LAB"
    hint = "VECTOR: bromigos-live ops focus <repo>"

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self.yaw, self.pitch, self.persp, self.spin = 0.0, 0.32, 4.2, 0.0
        s = self.s
        self.L["center"] = (860 * s, 600 * s, 560 * s)
        self.push = None          # {t, repo, branch, sha, slug, checks, seen}
        self.pushes = []
        self.argo = {}            # app -> (sync, health)
        self.argo_pulse = []      # (t, app, what)
        self.pods = None          # set of (ns, pod)
        self.pod_node = {}
        self.pod_fx = []          # (t, ns, pod, "in"|"out", note)
        self.tasks = {}           # id -> {label, progress, state, t}
        self.tools = []           # (t, name, phase, text, ok)
        self.since = time.time() - 1800
        self.ready_ = False
        from . import holoview
        self.hv = holoview.CompactHolo(["rack"], scale=s) if "rack" in holoview.available() else None
        self.poll_every(self._watch_pushes, 5, "pushes")
        self.poll_every(self._watch_lab, 10, "lab")
        self.poll_every(self._watch_ci, 12, "ci")

    def ready(self):
        return self.ready_

    # ------------------------------------------------------------------ data
    def _watch_pushes(self):
        rs = sources.repos()
        found = sources.pushes(rs, self.since)
        if found:
            self.since = found[-1][0] + 1
        for t, r, branch, sha in found:
            self._new_push(t, r["name"], branch, sha, r.get("slug"))

    def _new_push(self, t, repo, branch, sha, slug):
        if self.push and self.push["sha"] == sha:
            return
        self.push = {"t": t, "at": self.now(), "repo": repo, "branch": branch, "sha": sha, "slug": slug,
                     "checks": None}
        self.pushes = (self.pushes + [self.push])[-6:]
        self.built_at = None
        import threading
        threading.Thread(target=self._watch_ci, daemon=True).start()

    def _watch_ci(self):
        p = self.push
        if not p or not p.get("slug") or time.time() - p["t"] > 3600:
            return
        if p["checks"] and all(c.get("status") == "completed" for c in p["checks"]) and \
                time.time() - p["t"] > 120:
            return
        p["checks"] = sources.check_runs(p["slug"], p["sha"])
        self.built_at = None

    def _watch_lab(self):
        now = self.now()
        apps = {}
        for r in sources.prom("argocd_app_info"):
            m = r["metric"]
            apps[m.get("name")] = (m.get("sync_status"), m.get("health_status"))
        for a, v in apps.items():
            old = self.argo.get(a)
            if old and old != v:
                self.argo_pulse.append((now, a, f"{old[0]}/{old[1]} → {v[0]}/{v[1]}"))
        self.argo = apps
        cur, node = set(), {}
        for r in sources.prom("kube_pod_info"):
            m = r["metric"]
            k = (m.get("namespace"), m.get("pod"))
            cur.add(k)
            node[k] = m.get("node")
        if self.pods is not None:
            for k in cur - self.pods:
                self.pod_fx.append((now, k[0], k[1], "in", node.get(k) or ""))
            for k in self.pods - cur:
                self.pod_fx.append((now, k[0], k[1], "out", self.pod_node.get(k) or ""))
        else:                                       # first look: what started in the last 15 min
            for r in sources.prom("kube_pod_created > time() - 900"):
                m = r["metric"]
                self.pod_fx.append((now - 1.0, m.get("namespace"), m.get("pod"), "in", node.get(
                    (m.get("namespace"), m.get("pod"))) or ""))
        self.pods, self.pod_node = cur, node
        self.pod_fx = self.pod_fx[-24:]
        self.argo_pulse = self.argo_pulse[-8:]
        self.ready_ = True
        self.built_at = None

    # ------------------------------------------------------------------ feed and verbs
    def on_event(self, e, t):
        ty = e.get("type")
        if ty == "git_push":
            r = next((x for x in sources.repos() if x["name"] == e.get("repo") or x["path"] == e.get("repo")), None)
            self._new_push(e.get("t", time.time()), e.get("repo"), e.get("branch", "?"), e.get("sha", "?"),
                           (r or {}).get("slug") or e.get("slug"))
        elif ty == "ci" and self.push and e.get("repo") == self.push["repo"]:
            self.push["ci_note"] = f"{e.get('status')} {e.get('conclusion') or ''}"
        elif ty == "deploy":
            self.argo_pulse.append((t, e.get("app", "?"), e.get("status", "deploy")))
        elif ty == "restart":
            self.pod_fx.append((t, e.get("namespace", "?"), e.get("name", "?"), "flag", "restart by VECTOR"))
        elif ty == "task":
            k = e.get("id") or e.get("label")
            self.tasks[k] = {"label": e.get("label", k), "progress": float(e.get("progress") or 0),
                             "state": e.get("state", "running"), "t": t}
        elif ty in ("tool_start", "tool_end"):
            self.tools.append((t, e.get("name", "?"), ty[5:], e.get("args") if ty == "tool_start" else e.get("outcome"),
                               e.get("ok", True)))
            self.tools = self.tools[-8:]
        else:
            return
        self.built_at = None

    def command(self, verb, args):
        if verb == "focus":
            for p in reversed(self.pushes):
                if args and args.lower() in (p["repo"] or "").lower():
                    self.push = p
                    self.built_at = None
                    return f"showing the push to {p['repo']}"
            return f"no recent push to {args}"
        if verb == "clear":
            self.pod_fx, self.argo_pulse, self.tools = [], [], []
            return "cleared"
        return "ops verbs: focus <repo>, clear"

    # ------------------------------------------------------------------ build
    def rebuild_due(self, t):
        return self.built_at is None or t - self.built_at >= 0.2

    def build(self, b, d, t):
        s = self.s
        T = 0.05
        self.header(b, "LIVE: GIT REFLOGS · GH CHECK RUNS · ARGO + PODS FROM PROMETHEUS · VECTOR'S FEED")
        x, y, w, h = self.L["panel"]
        frame_panel(b, x, y, w, h, "THE PIPELINE", T + 0.05, sub="PUSH → CI → ARGO → CLUSTER")
        pts, ids = [], []
        # stations
        labels = {"vector": ("VECTOR", "his tasks ring him"), "ws": ("WORKSTATION", "where pushes start"),
                  "gh": ("GITHUB", "origin"), "argo": ("ARGO CD", f"{len(self.argo)} APPS"),
                  "cluster": ("CLUSTER", "the rack")}
        for k, (lab, sub) in labels.items():
            c = ST[k]
            b.arc(c, 0, 6 * s, 0, TAU, col("white" if k == "vector" else "soft"), kind=2, space=2, reveal=T + 0.2)
            b.arc(c, 16 * s, 17.5 * s, 0, TAU, col("soft", 0.8), segs=10 if k != "gh" else 8, gap=0.3,
                  spin=0.3 if k == "vector" else 0.08, space=2, reveal=T + 0.3)
            b.text(lab, *c[:2], col("soft"), font="s", track=2, space=2, z=c[2], dx=-30, dy=-34 * s, reveal=T + 0.4)
            b.text(sub.upper(), *c[:2], col("dim"), font="xs", track=1, space=2, z=c[2], dx=-30, dy=40 * s,
                   reveal=T + 0.5)
            pts.append(c)
            ids.append(k)
        _box(b, ST["ws"], 0.07, 0.06, 0.05, col("soft", 0.9), reveal=T + 0.3)
        for a_, b_ in (("ws", "gh"), ("gh", "ci0"), ("ci1", "argo"), ("argo", "cluster"), ("vector", "ws")):
            b.line(ST[a_], ST[b_], col("guard", 1.0), space=2, dash=5, reveal=T + 0.3)
        self._push_fx(b, t, T)
        self._argo_fx(b, t, T)
        self._pods(b, t, T)
        self._tasks(b, t, T)
        self._tool_lane(b, t, T)
        self.pick_pts = __import__("numpy").array(pts, "float32").reshape(-1, 3)
        self.pick_ids = ids
        if self.hover:
            lab = labels[self.hover][0]
            lines = {"gh": [f"LAST PUSH {self.push['repo']} {self.push['branch']} {self.push['sha'][:8]}"]
                     if self.push else ["NO PUSH IN THE LAST 30 MIN"],
                     "argo": [f"{sum(1 for v in self.argo.values() if v == ('Synced', 'Healthy'))}/{len(self.argo)} "
                              "SYNCED + HEALTHY"],
                     "cluster": [f"{len(self.pods or ())} PODS · {sum(1 for f in self.pod_fx if t - f[0] < 600)} "
                                 "CHANGED IN 10 MIN"],
                     "vector": [f"{len(self.tasks)} TASKS · {len(self.tools)} RECENT TOOL CALLS"],
                     "ws": ["PUSHES ARE READ FROM EACH REPO'S REMOTE REFLOG"]}.get(self.hover, [])
            self.hover_tip(b, lab, lines, "LIVE STATION")
        self._side(b, t, T)

    def _push_fx(self, b, t, T):
        s = self.s
        p = self.push
        if not p:
            b.text("NO PUSH IN THE LAST 30 MINUTES", *ST["gh"][:2], col("dim"), font="xs", track=2, space=2, z=0,
                   dx=-60, dy=70 * s)
            return
        age = t - p["at"]
        if age < 4.0:                                           # the beam
            k = min(age / 1.2, 1.0)
            head = _lerp(ST["ws"], ST["gh"], k)
            b.line(ST["ws"], head, col("white", 0.9), width=2.5, space=2)
            b.line(ST["ws"], head, col("phosphor", 0.35), width=9, space=2)
            b.arc(head, 0, 7 * s, 0, TAU, col("white"), kind=2, space=2)
            if age > 1.2:
                b.arc(ST["gh"], 0, (10 + 30 * (age - 1.2)) * s, 0, TAU, col("soft", max(0.0, 1 - (age - 1.2) / 2)),
                      kind=2, space=2)
        b.text(f"{ascii_(p['repo'])} · {p['branch']} · {p['sha'][:8]}".upper(), *ST["gh"][:2], col("white"),
               font="xs", track=1.5, space=2, z=0, dx=-60, dy=70 * s)
        checks = p.get("checks")
        if checks is None:
            b.text("ASKING GITHUB FOR CHECKS…" if p.get("slug") else "NO GITHUB REMOTE", *ST["ci0"][:2],
                   col("dim"), font="xs", track=2, space=2, z=0, dy=60 * s)
            return
        if not checks:
            b.text("NO CI ON THIS COMMIT", *ST["ci0"][:2], col("dim"), font="xs", track=2, space=2, z=0, dy=60 * s)
            return
        n = len(checks)
        for i, c in enumerate(checks[:10]):
            q = _lerp(ST["ci0"], ST["ci1"], (i + 0.5) / min(n, 10))
            st, con = c.get("status"), c.get("conclusion")
            colr = ("phosphor" if con == "success" else "danger" if con in ("failure", "timed_out", "cancelled")
                    else "dim" if con in ("skipped", "neutral") else "amber")
            pulse = 0.6 + 0.4 * math.sin(t * 3 + i) if st != "completed" else 1.0
            b.arc(q, 0, 6.5 * s, 0, TAU, col(colr, pulse), kind=2, space=2, reveal=p["at"] + 0.3 * i + 1.2)
            b.arc(q, 10 * s, 11.2 * s, 0, TAU * (1.0 if st == "completed" else (t * 0.5) % 1.0), col(colr, 0.8),
                  space=2, reveal=p["at"] + 0.3 * i + 1.2)
            b.text(ascii_(c.get("name"), 18).upper(), *q[:2], col(colr), font="xs", track=0.8, space=2, z=0,
                   dx=-40, dy=(34 if i % 2 else -24) * s, reveal=p["at"] + 0.3 * i + 1.3)
        done = [c for c in checks if c.get("status") == "completed"]
        if len(done) == n and all(c.get("conclusion") in ("success", "skipped", "neutral") for c in done):
            b.line(ST["ci1"], ST["argo"], col("phosphor", 0.8), width=1.8, space=2)
            b.arc(ST["ci1"], 0, 3 * s, 0, TAU, col("white"), kind=2, space=2, end=ST["argo"], speed=0.5)

    def _argo_fx(self, b, t, T):
        s = self.s
        recent = [p for p in self.argo_pulse if t - p[0] < 20]
        for i, (t0, app, what) in enumerate(recent[-4:]):
            k = min((t - t0) / 1.5, 1.0)
            head = _lerp(ST["argo"], ST["cluster"], k)
            b.line(ST["argo"], head, col("soft", 0.8 * (1 - max(0, (t - t0 - 6) / 14))), width=1.6, space=2)
            b.arc(head, 0, 5 * s, 0, TAU, col("white"), kind=2, space=2)
            b.text(f"{ascii_(app)} {ascii_(what)}".upper(), *ST["argo"][:2], col("soft"), font="xs", track=0.8,
                   space=2, z=0, dx=-50, dy=(70 + 18 * i) * s)
        bad = [a for a, v in self.argo.items() if v != ("Synced", "Healthy")]
        if bad:
            b.text(f"NOT SYNCED+HEALTHY: {', '.join(bad[:3])}".upper(), *ST["argo"][:2], col("amber"), font="xs",
                   track=0.8, space=2, z=0, dx=-50, dy=64 * s)

    def _pods(self, b, t, T):
        s = self.s
        cx, cy, cz = ST["cluster"]
        fx = [f for f in self.pod_fx if t - f[0] < 600]
        for i, (t0, ns, pod, kind, note) in enumerate(fx[-16:]):
            col_i, row = i % 4, i // 4
            c = (cx + 0.2 + col_i * 0.075, cy + 0.32 - row * 0.085, cz)
            if kind == "out":
                a = max(0.0, 1.0 - (t - t0) / 6.0)
                if a <= 0:
                    continue
                _box(b, c, 0.024, 0.024, 0.024, col("danger", a))
            else:
                _box(b, c, 0.024, 0.024, 0.024, col("amber" if kind == "flag" else "phosphor", 0.95),
                     reveal=t0 + 0.05)
        if fx:
            n_in = sum(1 for f in fx if f[3] == "in")
            n_out = sum(1 for f in fx if f[3] == "out")
            b.text(f"PODS · +{n_in} NEW  -{n_out} GONE (10 MIN)", cx + 0.16, cy + 0.42, col("soft"), font="xs",
                   track=1.2, space=2, z=cz)

    TOOL_STATION = (("argo", "argo"), ("prometheus", "cluster"), ("k8s", "cluster"), ("pod", "cluster"),
                    ("lab", "cluster"), ("gh", "gh"), ("github", "gh"), ("git", "gh"), ("shell", "ws"),
                    ("docs", "ws"), ("gnosis", "vector"), ("knowledge", "vector"), ("remember", "vector"))

    def _tool_lane(self, b, t, T):
        """VECTOR's tool calls: a rail under the stage; each call runs from him to the
        station it touches and leaves its name and outcome behind for a few seconds."""
        s = self.s
        y0 = -0.55
        b.line((ST["vector"][0], y0, 0), (ST["cluster"][0] + 0.3, y0, 0), col("guard"), space=2, reveal=T + 0.3)
        b.text("VECTOR'S TOOL CALLS", ST["vector"][0], y0, col("dim"), font="xs", track=2, space=2, z=0, dy=-12 * s,
               reveal=T + 0.4)
        b.line(ST["vector"], (ST["vector"][0], y0, 0), col("guard"), space=2, dash=4)
        for i, (t0, name, ph, txt, ok) in enumerate(self.tools[-6:]):
            age = t - t0
            if age > 12:
                continue
            st = next((v for k, v in self.TOOL_STATION if k in (name or "")), "ws")
            tgt = (ST[st][0], y0, 0)
            k = min(age / 0.8, 1.0)
            head = _lerp((ST["vector"][0], y0, 0), tgt, k)
            c = "danger" if not ok else ("white" if ph == "start" else "phosphor")
            a = max(0.0, 1.0 - max(0.0, age - 8) / 4)
            b.line((ST["vector"][0], y0, 0), head, col(c, 0.6 * a), width=1.6, space=2)
            b.arc(head, 0, 4.5 * s, 0, TAU, col(c, a), kind=2, space=2)
            b.line(head, ST[st], col(c, 0.25 * a), space=2, dash=4)
            b.text(f"{ascii_(name, 24)} {ascii_(txt, 40)}".upper(), *head[:2], col(c, a), font="xs", track=0.6,
                   space=2, z=0, dx=10, dy=(22 + 18 * (i % 3)) * s)

    def _tasks(self, b, t, T):
        s = self.s
        c = ST["vector"]
        live = [v for v in self.tasks.values() if v["state"] == "running" or t - v["t"] < 8]
        for i, v in enumerate(live[:6]):
            r0 = (26 + i * 9) * s
            colr = "danger" if v["state"] == "failed" else "phosphor" if v["state"] == "done" else "soft"
            b.arc(c, r0, r0 + 4 * s, 0, TAU, col("guard", 0.8), space=2)
            b.arc(c, r0, r0 + 4 * s, 0, TAU * max(0.02, min(v["progress"], 1.0)), col(colr), space=2)

    def _side(self, b, t, T):
        s = self.s
        x, y, w, h = self.L["side"]
        frame_panel(b, x, y, w, h, "THE LOG", T + 0.1, sub="NEWEST FIRST")
        yy = y + 70 * s

        def row(txt, c="soft", big=False):
            nonlocal yy
            b.text(ascii_(txt, 62).upper(), x + 18 * s, yy, col(c), font="s" if big else "xs", track=0.8)
            yy += (24 if big else 19) * s
        row("PUSHES (30 MIN)", "dim")
        for p in reversed(self.pushes[-4:]):
            row(f"{time.strftime('%H:%M', time.localtime(float(p['t'])))} {p['repo']} {p['branch']} {p['sha'][:8]}", "white")
        if not self.pushes:
            row("NONE", "dim")
        yy += 8 * s
        row("CI ON THE LAST PUSH", "dim")
        for c in (self.push or {}).get("checks") or []:
            row(f"{c.get('name')}: {c.get('conclusion') or c.get('status')}",
                "phosphor" if c.get("conclusion") == "success" else "danger" if c.get("conclusion") == "failure"
                else "amber")
        yy += 8 * s
        row("VECTOR'S TASKS", "dim")
        for v in list(self.tasks.values())[-4:]:
            row(f"{v['label']} {int(v['progress'] * 100)}% {v['state']}", "soft")
        if not self.tasks:
            row("NONE RUNNING", "dim")
        yy += 8 * s
        row("VECTOR'S TOOL CALLS", "dim")
        for (t0, name, ph, txt, ok) in reversed(self.tools[-5:]):
            row(f"{name} {ph}: {txt or ''}", "soft" if ok else "danger")
        if not self.tools:
            row("NONE YET (FROM HIS EVENT FEED)", "dim")
        yy += 8 * s
        row("PODS CHANGED (10 MIN)", "dim")
        for (t0, ns, pod, kind, note) in reversed([f for f in self.pod_fx if t - f[0] < 600][-6:]):
            row(f"{'+' if kind == 'in' else '-' if kind == 'out' else '!'} {ns}/{pod}",
                "soft" if kind == "in" else "danger" if kind == "out" else "amber")

    # ------------------------------------------------------------------ the rack hologram
    def _rack_rect(self):
        p = self.stage.painter
        from . import glkit
        sx, sy, _ = glkit.project([ST["cluster"]], p.rot[2], p.ctr[2])[0]
        s = self.s
        return (sx - 150 * s, sy - 230 * s, 300 * s, 330 * s)

    def animate(self, t, d):
        if self.hv is not None:
            _, _, rw, rh = self._rack_rect()
            self.hv.render(rw, rh, t)

    def post_composite(self, u):
        if self.hv is not None and self.hv.target is not None:
            self.hv.composite((float(self.w), float(self.h)), self._rack_rect(), u.get("fade", 1.0) * 0.9)


DECK = OpsDeck
