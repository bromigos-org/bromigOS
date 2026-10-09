"""VECTOR's memory in a homelab's Gnosis (bromigos-homelab: docs/homelab.md; VECTOR's
docs/plugins.md). Registered as the store "gnosis" when homelab.toml has a gnosis source
with both tokens; with vector.toml's [memory] backend = "auto" (the default) it is the
one in force when it loads.

Scope: the source's tenant, space vector, agent vector, user operator, private_user. All
calls go through the gnosis-gate (a small proxy in front of Gnosis) with two narrow tokens,
never Gnosis's own service token, both references in homelab.toml:
  write_auth_ref   add/search/list/context/delete, own space only
  auth_ref         read own space (and the source's search_spaces)

Recall has to be fast: it runs before the first model call, so it sits directly in front
of the first word. Gnosis's /v1/memory/context takes ~6 s with its LLM legs and ~0.35 s
without, so the hot path races two things and gives up at RECALL_BUDGET (0.2 s):
  * a local mirror of VECTOR's own Gnosis space (listed from Gnosis at start, every
    ten minutes and after each write; embedded once with the homelab's local
    qwen3-embedding through the core's endpoint, llm.py), ranked by cosine: ~50 ms;
  * Gnosis /v1/memory/context, LLM-free; used if it lands inside the budget.
Gnosis stays the store; the mirror only follows it. Writes are async (fact extraction on,
messages + infer=true): a note is in the mirror at once and in Gnosis a moment later.

Every remember, forget, recall and search goes to the audit log with the text hashed and
truncated, never in full (the core's memory.audit). This folder is protected: VECTOR
can't change his own plugins (guard.py).
"""
import hashlib
import json
import os
import shutil
import threading
import time
import urllib.request

import numpy as np

import bromigos_homelab as H
from holo.vector import memory as core
from holo.vector.memory import audit, digest

SRC = H.source_of("gnosis")                        # homelab.toml's gnosis source, or None
GATE = SRC.endpoint if SRC else ""
CACHE = os.path.expanduser("~/.cache/bromigos/vector-memory.json")
SCOPE = SRC.vector_scope() if SRC else {}           # VECTOR's own space (the adapter's, also bromigos memory's)
RECALL_BUDGET = 0.2
MIN_SCORE = 0.45
REFRESH_S = 600


def _tok(write):
    return H.config.resolve(SRC.opts.get("write_auth_ref" if write else "auth_ref") or "") if SRC else ""


def register(vector):
    """Only where the homelab has it: a gnosis source whose two tokens resolve."""
    if GATE and _tok(True) and _tok(False):
        vector.memory("gnosis", GnosisMemory)


class GnosisMemory:
    def __init__(self):
        self.ctx = SRC._ctx()                    # the source's TLS (its tls_ca, else [tls] ca_file)
        self.items = []          # [{id, content, kind, emb (np.float32 unit)}]
        self.lock = threading.Lock()
        self.loaded_at = 0.0
        self.last_written = None
        self.session = time.strftime("desktop-%Y%m%d-%H%M")
        self.backend = "gnosis"
        self.cache = CACHE
        self._load_cache()
        threading.Thread(target=self.refresh, daemon=True, name="memory-refresh").start()
        self.warm()                              # the first embedding call pays for TLS; not on the hot path

    # ------------------------------------------------------------------ plumbing
    def _token(self, write):
        return _tok(write)

    def _call(self, method, path, body, write=False, timeout=10.0):
        req = urllib.request.Request(GATE + path, data=json.dumps(body).encode(), method=method,
                                     headers={"Authorization": "Bearer " + self._token(write),
                                              "Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=timeout, context=self.ctx) as r:
            return json.load(r)

    def _scope(self):
        return dict(SCOPE, session_id=self.session)

    def embed(self, texts, timeout=5.0):
        return core.embed(texts, timeout, self.ctx)

    # ------------------------------------------------------------------ mirror
    def _load_cache(self):
        try:
            with open(self.cache) as f:
                raw = json.load(f)
            self.items = [dict(x, emb=np.array(x["emb"], np.float32)) for x in raw]
        except (OSError, ValueError, KeyError):
            self.items = []

    def _save_cache(self):
        os.makedirs(os.path.dirname(self.cache), exist_ok=True)
        tmp = f"{self.cache}.{os.getpid()}.{threading.get_ident()}.part"
        with self.lock:
            rows = [dict(x, emb=[round(float(v), 5) for v in x["emb"]]) for x in self.items]
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as f:
            json.dump(rows, f)
        os.replace(tmp, self.cache)

    def refresh(self):
        """Mirror VECTOR's own Gnosis space (ids + content); embed only what's new."""
        rows, page = [], 1
        try:
            while page <= 10:                      # up to 2000 notes; VECTOR keeps them short
                d = self._call("POST", "/v1/memories/list", {"scope": self._scope(), "page": page, "page_size": 200},
                               write=False, timeout=15)
                rows += d.get("results") or []
                if len(rows) >= int(d.get("total") or 0) or not d.get("results"):
                    break
                page += 1
        except Exception as e:
            audit("refresh", ok=False, err=str(e)[:120])
            return
        have = {x["id"]: x for x in self.items}
        fresh = [r for r in rows if r.get("memory_id") and r.get("content")]
        new = [r for r in fresh if r["memory_id"] not in have]
        embs = self.embed([r["content"] for r in new]) if new else []
        items = []
        for r in fresh:
            if r["memory_id"] in have:
                items.append(have[r["memory_id"]])
            else:
                k = new.index(r)
                items.append({"id": r["memory_id"], "content": r["content"],
                              "kind": (r.get("metadata") or {}).get("kind", "note"), "emb": embs[k]})
        with self.lock:
            self.items = items
            self.loaded_at = time.monotonic()
        self._save_cache()
        audit("refresh", ok=True, items=len(items))

    def maybe_refresh(self):
        if time.monotonic() - self.loaded_at > REFRESH_S:
            threading.Thread(target=self.refresh, daemon=True).start()

    # ------------------------------------------------------------------ recall (hot path)
    def recall(self, query, k=5, budget=RECALL_BUDGET):
        """-> (lines, stats). Never takes longer than `budget` seconds."""
        t0 = time.monotonic()
        box = {}

        def gnosis():
            try:
                d = self._call("POST", "/v1/memory/context",
                               {"scope": self._scope(), "query": query[:500], "max_items": k, "use_llm": False,
                                "include_graph": False, "include_short_term": False, "include_reasoning": False},
                               write=False, timeout=2.0)
                lines = []
                for sec in d.get("sections") or []:
                    for ln in (sec.get("content") or "").splitlines():
                        if ln.strip():
                            lines.append(ln.strip())
                box["gnosis"] = lines[:k]
            except Exception as e:
                box["gnosis_err"] = str(e)[:80]

        def local():
            try:
                with self.lock:
                    items = list(self.items)
                if not items:
                    box["local"] = []
                    return
                q = self.embed([query[:500]], timeout=budget)[0]
                m = np.stack([x["emb"] for x in items])
                s = m @ q
                order = np.argsort(-s)[:k]
                box["local"] = [items[i]["content"] for i in order if s[i] >= MIN_SCORE]
                box["local_ids"] = [items[i]["id"] for i in order if s[i] >= MIN_SCORE]
            except Exception as e:
                box["local_err"] = str(e)[:80]

        tg = threading.Thread(target=gnosis, daemon=True)
        tl = threading.Thread(target=local, daemon=True)
        tg.start()
        tl.start()
        deadline = t0 + budget
        while time.monotonic() < deadline:
            if "gnosis" in box:
                break
            if "local" in box:
                break                     # the mirror is in (Gnosis is ~0.35 s even LLM-free)
            time.sleep(0.005)
        src = "gnosis" if box.get("gnosis") else "mirror" if "local" in box else "none"
        lines = box.get("gnosis") or box.get("local") or []
        stats = {"recall_ms": int((time.monotonic() - t0) * 1000), "recall_source": src, "recalled": len(lines)}
        if src == "none":
            stats["recall_skipped"] = box.get("local_err") or "over budget"
        audit("recall", query=digest(query), source=src, hits=len(lines), ms=stats["recall_ms"])
        from holo.vector import events
        events.emit("memory.recall", space="vector", ids=box.get("local_ids", [])[:len(lines)] if src == "mirror" else [],
                    n=len(lines), ms=stats["recall_ms"], source=src)
        self.maybe_refresh()
        return lines, stats

    # ------------------------------------------------------------------ write / forget
    def remember(self, text, kind="note"):
        """File a note. Returns at once; the write runs in the background with Gnosis's fact
        extraction on (messages + infer=true), and the mirror holds the note immediately so
        the very next question can recall it."""
        text = " ".join(text.split())[:400]
        if len(text) < 4:
            raise ValueError("nothing to remember")
        tmp = "pending-" + hashlib.sha1(f"{time.time()}{text}".encode()).hexdigest()[:12]
        try:
            emb = self.embed([text], timeout=1.0)[0]
            with self.lock:
                self.items.append({"id": tmp, "content": text, "kind": kind, "emb": emb})
        except Exception:
            pass
        self.last_written = [tmp]

        def write():
            try:
                d = self._call("POST", "/v1/memories",
                               {"scope": self._scope(), "messages": [{"role": "user", "content": text}], "infer": True,
                                "metadata": {"kind": kind, "source": "vector-desktop"}}, write=True, timeout=120)
                ids = [r.get("memory_id") for r in d.get("results") or [] if r.get("memory_id")]
                if self.last_written == [tmp]:
                    self.last_written = ids
                audit("remember", content=digest(text), kind=kind, ids=ids[:4], extracted=max(0, len(ids) - 1))
            except Exception as e:
                audit("remember", content=digest(text), kind=kind, ok=False, err=str(e)[:120])
            self.refresh()                       # swap the pending note for what Gnosis stored
        threading.Thread(target=write, daemon=True, name="memory-write").start()
        from holo.vector import events
        events.emit("memory.file", space="vector", category=kind)
        return {"ok": True, "filed_under": kind}

    def warm(self):
        """Push-to-talk pressed: make sure the mirror is fresh and the embedding path is hot,
        so recall is ready the moment the transcript is."""
        def go():
            self.maybe_refresh()
            try:
                self.embed(["warm"], timeout=2.0)
            except Exception:
                pass
        threading.Thread(target=go, daemon=True).start()

    def forget(self, what=""):
        """Forget the best match for `what` in VECTOR's own space ("" or "that" = the last thing filed)."""
        target = None
        with self.lock:
            items = list(self.items)
        if (not what or what.strip().lower() in ("that", "it", "the last thing", "last")) and self.last_written:
            ids = [i for i in self.last_written if not i.startswith("pending-")]
            if not ids:
                return {"ok": False, "detail": "the last note is still being filed; ask again in a moment"}
            for mid in ids[1:]:
                try:
                    self._call("DELETE", f"/v1/memories/{mid}", {"scope": self._scope()}, write=True)
                except Exception:
                    pass
            target = next((x for x in items if x["id"] == ids[0]), {"id": ids[0], "content": "(the last note)"})
        elif items and what:
            items = [x for x in items if not x["id"].startswith("pending-")]
            if not items:
                return {"ok": False, "detail": "nothing filed yet"}
            q = self.embed([what])[0]
            s = np.stack([x["emb"] for x in items]) @ q
            i = int(np.argmax(s))
            if s[i] >= 0.5:
                target = items[i]
        if not target:
            audit("forget", query=digest(what), found=False)
            return {"ok": False, "detail": "nothing in my own memory matches that"}
        self._call("DELETE", f"/v1/memories/{target['id']}", {"scope": self._scope()}, write=True)
        with self.lock:
            self.items = [x for x in self.items if x["id"] != target["id"]]
        self._save_cache()
        # fact extraction may have filed the same thing again in other words (sometimes a few
        # seconds later): sweep near-duplicates now and once more shortly after
        threading.Thread(target=self._sweep, args=(target["content"],), daemon=True).start()
        if self.last_written and target["id"] in self.last_written:
            self.last_written = None
        audit("forget", query=digest(what), id=target["id"], content=digest(target["content"]))
        from holo.vector import events
        events.emit("memory.forget", space="vector", n=1, ids=[target["id"]])
        return {"ok": True, "forgot": target["content"][:120]}

    def _sweep(self, content, rounds=(0, 12)):
        try:
            q = self.embed([content], timeout=3)[0]
        except Exception:
            return
        for wait in rounds:
            time.sleep(wait)
            self.refresh()
            with self.lock:
                items = [x for x in self.items if not x["id"].startswith("pending-")]
            for x in items:
                if float(x["emb"] @ q) >= 0.8:
                    try:
                        self._call("DELETE", f"/v1/memories/{x['id']}", {"scope": self._scope()}, write=True)
                        audit("forget", sweep=True, id=x["id"], content=digest(x["content"]))
                    except Exception:
                        pass
            self.refresh()

    def summarize(self, turns):
        """End of a conversation: hand the turns to Gnosis with infer=true so it extracts the
        durable facts itself (its guidance for conversation memory). Background, small."""
        msgs = []
        for m in turns[-12:]:
            if m.get("role") in ("user", "assistant") and isinstance(m.get("content"), str) and m["content"].strip():
                msgs.append({"role": m["role"], "content": m["content"][:500]})
        if len([m for m in msgs if m["role"] == "user"]) < 2:
            return None
        try:
            self._call("POST", "/v1/memories", {"scope": self._scope(), "messages": msgs, "infer": True,
                                                "metadata": {"kind": "conversation", "source": "vector-desktop"}},
                       write=True, timeout=120)
            audit("summary", turns=len(msgs), chars=sum(len(m["content"]) for m in msgs))
            threading.Thread(target=self.refresh, daemon=True).start()
            return True
        except Exception as e:
            audit("summary", ok=False, err=str(e)[:120])
            return False


    def use_scratch(self, folder, fresh=False):
        """Evals: the mirror lives in their scratch folder (a copy, or empty when fresh)."""
        path = os.path.join(folder, "memory-mirror.json")
        if fresh and os.path.exists(path):
            os.unlink(path)
        elif not os.path.exists(path) and os.path.exists(CACHE):
            shutil.copyfile(CACHE, path)
            os.chmod(path, 0o600)
        self.cache = path
        self._load_cache()
