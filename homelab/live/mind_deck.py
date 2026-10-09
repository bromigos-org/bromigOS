"""SUPER+I — VECTOR's mind: his Gnosis memory and the five knowledge spaces as a
3D constellation.

  * VECTOR's own memories (space `vector`) sit around his core, placed by their real
    embeddings (the local mirror ~/.cache/bromigos/vector-memory.json, PCA to 3D);
  * the knowledge spaces (kb-bromigos, kb-nolgia, kb-personal, kb-desktop, kb-homelab)
    are clusters on a ring: space → repo hubs → one light per document, sized by its
    chunk count. The ~9.6k chunks are charted from kb-sync's own chunker and state
    (exact ids, no network; the gate's list stops at 2,000 per space and is the
    fallback), aggregated to documents and cached until the nightly kb-sync runs;
  * feed events: `recall` lights the recalled memories and documents and pulls them
    toward the core; `file` settles a new memory in from the dark; `forget` burns one out.

Zoom (scroll toward the cursor): each repo's documents sit close around its hub when
zoomed out and open up into their own lights as you zoom in; names appear by zoom
level and by room (spaces always, then repos, then documents and memories).

Verbs (bromigos-live mind <verb>): focus <text>, space <name>, clear. focus and space
fly the camera to the target.
"""
import hashlib
import json
import math
import os
import time

import numpy as np

from .deckkit import TAU, Deck3D, ascii_, frame_panel, wrap
from . import glkit
from .glkit import col
from .zoomcam import lod

from .homelab import H  # noqa: E402
# The knowledge service is homelab.toml's gnosis source: its gate (endpoint), read token
# (auth_ref), tenant, spaces and their labels and colours.
_G = H.source_of("gnosis") if H else None
GATE = _G.endpoint if _G else ""
TENANT = (_G.opts.get("tenant") if _G else "") or "bromigos"
MIRROR = os.path.expanduser("~/.cache/bromigos/vector-memory.json")
KBSYNC = os.path.expanduser("~/.local/state/bromigos/kb-sync.json")
CACHE = os.path.join(os.environ.get("XDG_CACHE_HOME", os.path.expanduser("~/.cache")), "bromigos-live",
                     "kb-docs.json")
SPACES = list((_G.opts.get("spaces") if _G else None) or [])
_PALETTE = ("phosphor", "soft", "amber", "white", "dim")
SPACE_COL = dict({sp: _PALETTE[i % len(_PALETTE)] for i, sp in enumerate(SPACES)},
                 **((_G.opts.get("colours") if _G else None) or {}), vector="white")
SPACE_ABOUT = dict((_G.opts.get("labels") if _G else None) or {})


def _h(s, k=0):
    return int.from_bytes(hashlib.blake2b(f"{s}:{k}".encode(), digest_size=4).digest(), "little") / 2 ** 32


def _post(path, body, timeout=20):
    """POST to the gate with the source's read token and TLS (bromigos_homelab)."""
    if not _G:
        raise OSError("no gnosis source in homelab.toml")
    return _G.request(path, data=body, method="POST", timeout=timeout)


KBSYNC_PY = next((p for p in ("/usr/lib/bromigos/vector/tools/kb-sync.py",
                              os.path.expanduser("~/.config/bromigos/holo/tools/kb-sync.py")) if os.path.exists(p)),
                 os.path.expanduser("~/.config/bromigos/holo/tools/kb-sync.py"))


def chart_from_kbsync(progress=None):
    """The complete chart without the network: kb-sync's own sources() + chunks() give
    every chunk's (space, repo, path, heading, key), and its state file maps each key to
    the Gnosis id. (Gnosis's list endpoint stops at 2,000 per space; this does not.)"""
    import importlib.util
    spec = importlib.util.spec_from_file_location("kb_sync", KBSYNC_PY)
    ks = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(ks)
    with open(KBSYNC) as f:
        state = json.load(f)
    rows = []
    for space, files in ks.sources().items():
        have = state.get(space, {})
        for name, _repo, rel, text in files:
            for n, (heading, _body) in enumerate(ks.chunks(text)):
                key = hashlib.sha1(f"{space}|{name}|{rel}|{heading}|{n}".encode()).hexdigest()[:20]
                if key in have:
                    rows.append((space, have[key]["id"], name, rel, heading))
        if progress:
            progress(space, len(rows))
    return rows


def list_space(space, progress=None):
    """Every chunk's metadata in one kb space (content dropped), through the gate."""
    if not GATE:
        raise OSError("no gnosis source in homelab.toml")
    scope = {"tenant_id": TENANT, "space_id": space, "agent_id": "vector", "session_id": "vector",
             "user_id": space, "visibility": "agent_shared"}
    rows, page = [], 1
    while page <= 80:
        d = _post("/v1/memories/list", {"scope": scope, "page": page, "page_size": 200})
        res = d.get("results") or []
        for x in res:
            m = x.get("metadata") or {}
            rows.append((x.get("memory_id"), m.get("repo") or "?", m.get("path") or "?", m.get("heading") or ""))
        if progress:
            progress(len(rows), int(d.get("total") or 0))
        if not res or len(rows) >= int(d.get("total") or 0):
            break
        page += 1
    return rows


class MindDeck(Deck3D):
    name = "mind"
    title = "MIND // VECTOR'S MEMORY AND KNOWLEDGE"
    hint = "VECTOR: bromigos-live mind focus <text>"
    zoom = (0.7, 16.0)

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self.pitch, self.yaw, self.persp = 0.62, 0.3, 3.6
        self.docs = []          # {space, repo, path, heading, n, ids}
        self.chunk_doc = {}     # chunk id -> doc index
        self.mems = []          # {id, content, kind, p}
        self.mem_ix = {}
        self.layout = {}        # node id -> xyz
        self.charting = None    # (done, total) while listing
        self.flare = {}         # node id -> (t0, colour)
        self.settle = {}        # memory id -> (t0, from xyz)
        self.burn = {}          # memory id -> t0
        self.log = []           # (t, kind, text)
        self.mirror_mtime = 0
        self.focus_t = None
        self.poll_every(self._load_kb, 3600, "kb")
        self.poll_every(self._load_mirror, 20, "mirror")

    def ready(self):
        return bool(self.docs) and bool(self.mems)

    # ------------------------------------------------------------------ data
    def _load_mirror(self):
        try:
            m = os.path.getmtime(MIRROR)
        except OSError:
            return
        if m == self.mirror_mtime:
            return
        with open(MIRROR) as f:
            raw = json.load(f)
        self.mirror_mtime = m
        mems = [{"id": x["id"], "content": x.get("content", ""), "kind": x.get("kind", "note")} for x in raw]
        if len(raw) >= 4:
            E = np.array([x["emb"] for x in raw], np.float32)
            E -= E.mean(0)
            u, sv, vt = np.linalg.svd(E, full_matrices=False)
            P = E @ vt[:3].T
            P /= max(np.abs(P).max(), 1e-6)
        else:
            P = np.array([[_h(x["id"], k) * 2 - 1 for k in range(3)] for x in raw], np.float32).reshape(-1, 3)
        for x, p in zip(mems, P):
            x["p"] = (float(p[0]) * 0.26, float(p[1]) * 0.17, float(p[2]) * 0.26)
        self.mems = mems
        self.mem_ix = {x["id"]: i for i, x in enumerate(mems)}
        self.built_at = None

    def _load_kb(self):
        stale = True
        try:
            with open(CACHE) as f:
                c = json.load(f)
            age = time.time() - c.get("at", 0)
            synced = os.path.getmtime(KBSYNC) if os.path.exists(KBSYNC) else 0
            stale = age > 12 * 3600 or synced > c.get("at", 0)
            if not stale:
                self._set_docs(c["docs"])
        except (OSError, ValueError, KeyError):
            pass
        if not stale:
            return
        docs = {}
        try:
            total = sum(len(v) for v in json.load(open(KBSYNC)).values())
            rows = chart_from_kbsync(lambda sp, n: setattr(self, "charting", (sp, n, total)))
        except Exception as e:                    # no local checkout: what the gate will list
            print("bromigos-live: mind: kb-sync chart failed, listing through the gate:", e, flush=True)
            rows = []
            for sp in SPACES:
                rows += [(sp,) + r for r in list_space(sp, lambda n, tot, sp=sp: setattr(self, "charting", (sp, n, tot)))]
        for sp, cid, repo, path, heading in rows:
            k = (sp, repo, path)
            dd = docs.setdefault(k, {"space": sp, "repo": repo, "path": path, "heading": heading, "n": 0, "ids": []})
            dd["n"] += 1
            dd["ids"].append(cid)
        out = sorted(docs.values(), key=lambda d: (d["space"], d["repo"], d["path"]))
        os.makedirs(os.path.dirname(CACHE), exist_ok=True)
        with open(CACHE + ".part", "w") as f:
            json.dump({"at": time.time(), "docs": out}, f)
        os.replace(CACHE + ".part", CACHE)
        self.charting = None
        self._set_docs(out)

    def _set_docs(self, docs):
        lay = {}
        repos = {}
        for i, d in enumerate(docs):
            repos.setdefault((d["space"], d["repo"]), []).append(i)
        for si, sp in enumerate(SPACES):
            a = si / len(SPACES) * TAU + 0.3
            c = np.array([math.cos(a) * 0.9, 0.12 * math.sin(a * 2.0), math.sin(a) * 0.9])
            lay["space:" + sp] = tuple(c)
            rs = sorted([r for (s_, r) in repos if s_ == sp], key=lambda r: -len(repos[(sp, r)]))
            for ri, r in enumerate(rs):
                ra = ri * 2.399963 + a                     # golden angle around the space centre
                rr = 0.02 + 0.22 * math.sqrt(ri / max(len(rs), 1))
                hub = c + np.array([math.cos(ra) * rr, (_h(r, 3) - 0.5) * 0.12, math.sin(ra) * rr])
                lay[f"repo:{sp}:{r}"] = tuple(hub)
                ids = repos[(sp, r)]
                for k, i in enumerate(ids):
                    da = k * 2.399963
                    dr = 0.015 + 0.09 * math.sqrt((k + 0.5) / len(ids))
                    q = hub + np.array([math.cos(da) * dr, (_h(docs[i]["path"], 1) - 0.5) * 0.05, math.sin(da) * dr])
                    lay[f"doc:{i}"] = tuple(q)
        self.layout = lay
        n = len(docs)
        q = np.array([lay.get(f"doc:{i}", (0, 0, 0)) for i in range(n)], np.float64).reshape(-1, 3)
        hub = np.array([lay.get(f"repo:{d['space']}:{d['repo']}", (0, 0, 0)) for d in docs], np.float64).reshape(-1, 3)
        sc = np.array([lay.get("space:" + d["space"], (0, 0, 0)) for d in docs], np.float64).reshape(-1, 3)
        self.doc_arr = (q, hub, sc)                # for opening every cluster at once
        self.docs = docs
        self.chunk_doc = {cid: i for i, d in enumerate(docs) for cid in d["ids"]}
        self.built_at = None

    def pos(self, node, t):
        """Displayed position: layout, pulled toward the core while flared, settling if new."""
        if node.startswith("mem:"):
            m = self.mems[self.mem_ix[node[4:]]] if node[4:] in self.mem_ix else None
            base = np.array(m["p"] if m else (0, 0, 0))
            st = self.settle.get(node[4:])
            if st:
                k = min((t - st[0]) / 2.5, 1.0)
                k = 1 - (1 - k) ** 3
                base = np.array(st[1]) * (1 - k) + base * k
        else:
            base = self._xp(node)
        f = self.flare.get(node)
        if f:
            env = max(0.0, 1.0 - (t - f[0]) / 6.0)
            base = base * (1 - 0.45 * math.sin(min((t - f[0]) / 1.2, 1.0) * math.pi / 2) * env)
        return base

    def _spread(self):
        """How far clusters are opened at this zoom: (repos around their space, docs around their repo)."""
        z = self.cam.z if self.cam else 1.0
        return 0.8 + 0.2 * lod(z, 1.0, 2.2), 0.5 + 0.5 * lod(z, 1.0, 4.0)

    def _doc_positions(self):
        """Every document's position at this zoom, in one go."""
        q, hub, sc = getattr(self, "doc_arr", (np.zeros((0, 3)),) * 3)
        er, ed = self._spread()
        return sc + (hub - sc) * er + (q - hub) * ed

    def _xp(self, node):
        """Layout position with the clusters opened as far as the zoom says."""
        p = np.array(self.layout.get(node, (0, 0, 0)))
        if node.startswith(("repo:", "doc:")):
            er, ed = self._spread()
            if node.startswith("doc:"):
                d = self.docs[int(node[4:])]
                hub = np.array(self.layout.get(f"repo:{d['space']}:{d['repo']}", p))
                sc = np.array(self.layout.get("space:" + d["space"], hub))
                hub2 = sc + (hub - sc) * er
                return hub2 + (p - hub) * ed
            sc = np.array(self.layout.get("space:" + node.split(":")[1], p))
            return sc + (p - sc) * er
        return p

    # ------------------------------------------------------------------ events and verbs
    def on_event(self, e, t):
        ty = e.get("type")
        if ty == "recall":
            n = 0
            for mid in e.get("ids") or []:
                if mid in self.mem_ix:
                    self.flare["mem:" + mid] = (t, "white")
                    n += 1
            for k in e.get("kb") or []:
                for i, d in enumerate(self.docs):
                    if d["space"] == k.get("space") and d["path"] == k.get("path") and \
                            (not k.get("repo") or d["repo"] == k.get("repo")):
                        self.flare[f"doc:{i}"] = (t, SPACE_COL.get(d["space"], "soft"))
                        n += 1
            for cid in e.get("chunks") or []:
                if cid in self.chunk_doc:
                    i = self.chunk_doc[cid]
                    self.flare[f"doc:{i}"] = (t, SPACE_COL.get(self.docs[i]["space"], "soft"))
                    n += 1
            self.log.append((time.time(), "RECALL", f"{e.get('query', '')} · {n} lit"))
        elif ty == "file":
            mid = e.get("id") or hashlib.sha1((e.get("text") or "").encode()).hexdigest()[:16]
            if mid not in self.mem_ix:
                a = _h(mid) * TAU
                tgt = (math.cos(a) * 0.18, (_h(mid, 2) - 0.5) * 0.12, math.sin(a) * 0.18)
                self.mems.append({"id": mid, "content": e.get("text", ""), "kind": e.get("kind", "note"), "p": tgt})
                self.mem_ix[mid] = len(self.mems) - 1
            self.settle[mid] = (t, (math.cos(_h(mid, 5) * TAU) * 1.6, 0.6, math.sin(_h(mid, 5) * TAU) * 1.6))
            self.flare["mem:" + mid] = (t, "soft")
            self.log.append((time.time(), "FILE", e.get("text", "")))
        elif ty == "forget":
            mid = e.get("id")
            if mid in self.mem_ix:
                self.burn[mid] = t
            self.log.append((time.time(), "FORGET", e.get("text") or mid or ""))
        else:
            return
        self.log = self.log[-12:]
        self.built_at = None

    def command(self, verb, args):
        if verb == "focus":
            q = args.lower().strip()
            best = None
            for m in self.mems:
                if q and q in m["content"].lower():
                    best = "mem:" + m["id"]
                    break
            if best is None:
                for i, d in enumerate(self.docs):
                    if q and (q in d["path"].lower() or q in d["heading"].lower() or q == d["repo"].lower()):
                        best = f"doc:{i}"
                        break
            if best is None:
                return f"nothing in mind matches '{args}'"
            self._turn_to(best)
            self.select(best)
            self.flare[best] = (self.now(), "white")
            self.fly_to(best, 3.0 if best.startswith("mem:") else 5.0)
            return f"focused {self.label(best)[0]}"
        if verb == "space":
            sp = args if args.startswith("kb-") else "kb-" + args
            if "space:" + sp not in self.layout:
                return f"no space {args}"
            self._turn_to("space:" + sp)
            self.select("space:" + sp)
            self.fly_to("space:" + sp, 2.2)
            return f"showing {sp}"
        if verb == "clear":
            self.select(None)
            self.flare.clear()
            if self.cam:
                self.cam.reset()
            return "cleared"
        return "mind verbs: focus <text>, space <name>, clear"

    def _turn_to(self, node):
        p = self.pos(node, self.now())
        self.yaw = -math.atan2(p[0], p[2]) if (abs(p[0]) + abs(p[2])) > 1e-3 else self.yaw
        self.last_input = self.now()

    # ------------------------------------------------------------------ build
    def rebuild_due(self, t):
        busy = bool(self.flare or self.settle or self.burn) or self.charting
        return self.built_at is None or t - self.built_at >= (0.08 if busy else 0.7)

    def label(self, node):
        if node.startswith("mem:"):
            m = self.mems[self.mem_ix[node[4:]]]
            return "VECTOR · " + m["kind"].upper(), wrap(ascii_(m["content"]), 54)[:3]
        if node.startswith("doc:"):
            d = self.docs[int(node[4:])]
            return f"{d['space']} · {d['repo']}", [d["path"], f"{d['n']} CHUNKS · {ascii_(d['heading'], 50)}"]
        if node.startswith("repo:"):
            _, sp, r = node.split(":", 2)
            n = sum(1 for d in self.docs if d["space"] == sp and d["repo"] == r)
            return f"{sp} · {r}", [f"{n} DOCUMENTS"]
        if node.startswith("space:"):
            sp = node[6:]
            dd = [d for d in self.docs if d["space"] == sp]
            return sp, [SPACE_ABOUT.get(sp, ""), f"{len(dd)} DOCUMENTS · {sum(d['n'] for d in dd)} CHUNKS"]
        return "VECTOR", ["THE CORE: EVERY RECALL PULLS TOWARD IT"]

    def build(self, b, d, t):
        s = self.s
        T = 0.05
        for k in [k for k, v in self.flare.items() if t - v[0] > 6.5]:
            del self.flare[k]
        for k in [k for k, v in self.settle.items() if t - v[0] > 2.6]:
            del self.settle[k]
        for k in [k for k, v in self.burn.items() if t - v > 2.2]:
            del self.burn[k]
            if k in self.mem_ix:
                self.mems.pop(self.mem_ix[k])
                self.mem_ix = {x["id"]: i for i, x in enumerate(self.mems)}
        nd = len(self.docs)
        nc = sum(x["n"] for x in self.docs)
        sub = f"{len(self.mems)} MEMORIES · {nd} DOCUMENTS · {nc} CHUNKS · GNOSIS VIA THE GATE (READ TOKEN)"
        self.header(b, sub)
        x, y, w, h = self.L["panel"]
        frame_panel(b, x, y, w, h, "THE CONSTELLATION", T + 0.05, sub="SIZE = CHUNKS · RECALLS PULL TOWARD THE CORE")
        if self.charting:
            sp, n, tot = self.charting
            b.text(f"CHARTING {sp.upper()} · {n}/{tot} CHUNKS", x + w / 2, y + 60 * s, col("amber"), font="s",
                   track=2, align="c")
        pts, ids = [], []
        z = self.cam.z
        pp = self.stage.painter
        labels = self.cam.labels(self.stage.atlas, pp, s, cap=70)
        repo_a, doc_a, mem_a = lod(z, 1.25, 2.0), lod(z, 2.6, 4.5), lod(z, 1.8, 3.0)
        # the core
        b.arc((0, 0, 0), 0, 9 * s, 0, TAU, col("white"), kind=2, space=2, reveal=T + 0.2)
        for k, r in enumerate((0.06, 0.09)):
            b.arc((0, 0, 0), r * 200 * s, r * 200 * s + 1.4, 0, TAU, col("soft", 0.8), segs=8 + 4 * k, gap=0.4,
                  spin=0.3 * (1 if k else -1), space=2, reveal=T + 0.3)
        pts.append((0, 0, 0))
        ids.append("core")
        # spaces and repos
        for sp in SPACES:
            key = "space:" + sp
            if key not in self.layout:
                continue
            c = self.layout[key]
            sc = SPACE_COL[sp]
            b.line((0, 0, 0), c, col(sc, 0.18), space=2, dash=6, reveal=T + 0.3)
            b.arc(c, 0, 5.5 * s, 0, TAU, col(sc), kind=2, space=2, reveal=T + 0.4)
            b.arc(c, 14 * s, 15.4 * s, 0, TAU, col(sc, 0.8), segs=10, gap=0.35, spin=0.2, space=2, reveal=T + 0.4)
            labels.add(10, c, sp.upper(), "s", 2, dx=20, dy=-12, colour=col(sc), reveal=T + 0.6, force=True)
            pts.append(c)
            ids.append(key)
        ndocs = {}
        for dd in self.docs:
            ndocs[(dd["space"], dd["repo"])] = ndocs.get((dd["space"], dd["repo"]), 0) + 1
        for key in self.layout:
            if key.startswith("repo:"):
                _, sp, rname = key.split(":", 2)
                c = tuple(self._xp(key))
                b.line(self.layout["space:" + sp], c, col(SPACE_COL[sp], 0.16), space=2, reveal=T + 0.5)
                b.arc(c, 0, 2.6 * s, 0, TAU, col(SPACE_COL[sp], 0.9), kind=2, space=2, reveal=T + 0.5)
                if repo_a > 0.0:
                    n = ndocs.get((sp, rname), 0)
                    labels.add(5 + math.log1p(n), c, ascii_(rname, 28).upper(), "xs", 1.2, dx=8, dy=-6,
                               colour=col(SPACE_COL[sp], 0.9 * repo_a))
                pts.append(c)
                ids.append(key)
        # documents (labels only for the ones on screen, biggest first)
        P = self._doc_positions()
        lab_ok = set()
        if doc_a > 0.0 and len(P) == len(self.docs):
            pr = glkit.project(P.astype(np.float32), pp.rot[2], pp.ctr[2])
            x0, y0, w0, h0 = self.cam.rect
            on = np.nonzero((pr[:, 0] > x0) & (pr[:, 0] < x0 + w0) & (pr[:, 1] > y0) & (pr[:, 1] < y0 + h0))[0]
            on = sorted(on.tolist(), key=lambda i: -self.docs[i]["n"])[:240]
            lab_ok = set(on)
        for i, dd in enumerate(self.docs):
            node = f"doc:{i}"
            if node not in self.layout:
                continue
            p = self.pos(node, t) if node in self.flare else (P[i] if i < len(P) else self._xp(node))
            sc = SPACE_COL[dd["space"]]
            r = (0.8 + 0.55 * math.sqrt(dd["n"])) * s
            f = self.flare.get(node)
            if f:
                env = max(0.0, 1.0 - (t - f[0]) / 6.0)
                b.arc(tuple(p), 0, r * (1.8 + 2.5 * env), 0, TAU, col("white", 0.6 + 0.4 * env), kind=2, space=2)
                b.line(tuple(p), (0, 0, 0), col(sc, 0.5 * env), space=2)
                b.arc(tuple(p), 0, 2.2 * s, 0, TAU, col("white", env), kind=2, space=2, end=(0, 0, 0), speed=0.6,
                      phase=_h(node))
            else:
                b.arc(tuple(p), 0, r, 0, TAU, col(sc, 0.55), kind=2, space=2, reveal=T + 0.6 + (i % 50) * 0.01)
            if i in lab_ok:
                parts = [x for x in dd["path"].split("/") if x]
                name = "/".join(([dd["repo"]] + parts)[-2:])          # README.MD alone says nothing
                labels.add(1 + math.log1p(dd["n"]), tuple(p), ascii_(name, 34).upper(), "xs", 0.8, dx=r / s + 6,
                           dy=4, colour=col(sc, 0.85 * doc_a))
            pts.append(tuple(p))
            ids.append(node)
        # VECTOR's memories
        for m in self.mems:
            node = "mem:" + m["id"]
            p = tuple(self.pos(node, t))
            bt = self.burn.get(m["id"])
            if bt is not None:
                k = (t - bt) / 2.2
                b.arc(p, 0, (4 + 10 * k) * s, 0, TAU, col("danger", max(0.0, 1 - k)), kind=2, space=2)
                continue
            f = self.flare.get(node)
            env = max(0.0, 1.0 - (t - f[0]) / 6.0) if f else 0.0
            b.line(p, (0, 0, 0), col("white", 0.08 + 0.5 * env), space=2)
            b.arc(p, 0, (3.0 + 4 * env) * s, 0, TAU, col("white", 0.85 + 0.15 * env), kind=2, space=2, reveal=T + 0.5)
            if m["id"] in self.settle:
                b.text(ascii_(m["content"], 40).upper(), *p[:2], col("soft"), font="xs", track=1, space=2, z=p[2],
                       dx=10, dy=-6, reveal=self.settle[m["id"]][0], type_rate=0.01)
            elif mem_a > 0.0:
                labels.add(2 + env * 8, p, ascii_(m["content"], 30).upper(), "xs", 0.8, dx=10, dy=-6,
                           colour=col("white", 0.8 * mem_a))
            pts.append(p)
            ids.append(node)
        self.pick_pts = np.array(pts, np.float32).reshape(-1, 3)
        self.pick_ids = ids
        if self.selected and self.selected in ids:
            p = self.pick_pts[ids.index(self.selected)]
            b.arc(tuple(p), 12 * s, 13.5 * s, 0, TAU, col("white"), segs=4, gap=0.5, spin=1.5, space=2)
        labels.place(b)
        if self.hover:
            lab, lines = self.label(self.hover)
            self.hover_tip(b, lab, lines, "CLICK FOR THE CARD")
        self._side(b, t, T)

    def _side(self, b, t, T):
        s = self.s
        x, y, w, h = self.L["side"]
        frame_panel(b, x, y, w, h, "SPACES", T + 0.1, sub="CLICK A LIGHT FOR ITS CARD")
        yy = y + 70 * s
        for sp in ["vector"] + SPACES:
            if sp == "vector":
                n, ch, about = len(self.mems), len(self.mems), "his own notes (embedded, by meaning)"
            else:
                dd = [d for d in self.docs if d["space"] == sp]
                n, ch, about = len(dd), sum(d["n"] for d in dd), SPACE_ABOUT[sp]
            b.arc((x + 26 * s, yy - 5 * s), 0, 4 * s, 0, TAU, col(SPACE_COL[sp]), kind=2)
            b.text(sp.upper(), x + 44 * s, yy, col(SPACE_COL[sp]), font="s", track=1.5)
            b.text(f"{n} · {ch}", x + w - 18 * s, yy, col("soft"), font="xs", track=1, align="r")
            b.text(about.upper(), x + 44 * s, yy + 18 * s, col("dim"), font="xs", track=1)
            yy += 46 * s
        yy += 10 * s
        b.text("LATEST IN THE FEED", x + 18 * s, yy, col("dim"), font="xs", track=3)
        yy += 24 * s
        evs = self.log[-6:] or [(None, "", "NO RECALL, FILE OR FORGET YET")]
        for tt, kind, txt in reversed(evs):
            stamp = time.strftime("%H:%M:%S", time.localtime(float(tt))) if tt else ""
            c = {"RECALL": "white", "FILE": "soft", "FORGET": "danger"}.get(kind, "dim")
            b.text(f"{stamp} {kind}", x + 18 * s, yy, col(c), font="xs", track=1)
            for ln in wrap(ascii_(txt).upper(), 52)[:2]:
                yy += 18 * s
                b.text(ln, x + 30 * s, yy, col("soft", 0.85), font="xs", track=0.5)
            yy += 24 * s
        if self.selected:
            lab, lines = self.label(self.selected)
            cy = y + h - 230 * s
            b.plate(x + 12 * s, cy, w - 24 * s, 216 * s, 0.94)
            b.brackets(x + 12 * s, cy, w - 24 * s, 216 * s, col("soft"), l=10, reveal=self.sel_t)
            b.text(ascii_(lab, 50).upper(), x + 26 * s, cy + 28 * s, col("white"), font="m", track=1,
                   reveal=self.sel_t, type_rate=0.008)
            more = []
            if self.selected.startswith("mem:"):
                more = wrap(ascii_(self.mems[self.mem_ix[self.selected[4:]]]["content"]), 58)[:7]
            else:
                more = [ascii_(l, 58) for l in lines]
                if self.selected.startswith("doc:"):
                    more.append("VECTOR CAN READ IT: docs_read / knowledge_search")
            for k, ln in enumerate(more[:7]):
                b.text(ln, x + 26 * s, cy + 58 * s + k * 21 * s, col("soft"), font="xs", track=0.6,
                       reveal=self.sel_t + 0.05, type_rate=0.002)


DECK = MindDeck
