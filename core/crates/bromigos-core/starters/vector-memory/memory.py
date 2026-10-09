"""__TITLE__: a memory store for VECTOR (made by `bromigos ext new vector-memory`).

register(vector) offers a factory; VECTOR builds the store when [memory] backend in
vector.toml names it ("__IDENT__"), or with "auto" when it's the first plugin store.
The interface (VECTOR's holo/vector/memory.py):

  recall(query, k, budget) -> (lines, stats)   the hot path: never longer than budget s
  remember(text, kind)     -> {"ok": True, …}   return at once
  forget(what)             -> {"ok": bool, …}   "" or "that": the last thing filed
  summarize(turns)                              end of a conversation (may do nothing)
  warm(), refresh(), last_written

This one keeps notes in a JSON-lines file and recalls by shared words: no embeddings,
no network. Swap in your own backend (a database, a service: declare its host).
"""
import json
import os
import re
import threading
import time

STATE = os.path.join(os.environ.get("XDG_STATE_HOME") or os.path.expanduser("~/.local/state"),
                     "bromigos-ext", "__NAME__")
WORD = re.compile(r"[a-z0-9]{3,}")


def _words(s):
    return set(WORD.findall(s.lower()))


class __CAMEL__Memory:
    backend = "__IDENT__"

    def __init__(self):
        os.makedirs(STATE, exist_ok=True)
        self.path = os.path.join(STATE, "notes.jsonl")
        self.lock = threading.Lock()
        self.last_written = None
        self.notes = []
        try:
            with open(self.path) as f:
                self.notes = [json.loads(line) for line in f if line.strip()]
        except (OSError, ValueError):
            self.notes = []

    def _save(self):
        tmp = self.path + ".tmp"
        with open(tmp, "w") as f:
            for n in self.notes:
                f.write(json.dumps(n) + "\n")
        os.replace(tmp, self.path)

    def recall(self, query, k=5, budget=1.0):
        t0 = time.monotonic()
        q = _words(query)
        with self.lock:
            scored = sorted(((len(q & _words(n["text"])), n) for n in self.notes), key=lambda x: -x[0])
        lines = [n["text"] for s, n in scored[:k] if s > 0]
        return lines, {"recall_ms": int((time.monotonic() - t0) * 1000), "recall_source": "__IDENT__",
                       "recalled": len(lines)}

    def remember(self, text, kind="note"):
        text = " ".join(str(text).split())[:400]
        if len(text) < 4:
            raise ValueError("nothing to remember")
        with self.lock:
            nid = max((n["id"] for n in self.notes), default=0) + 1
            self.notes.append({"id": nid, "text": text, "kind": kind, "t": time.time()})
            self._save()
        self.last_written = [nid]
        return {"ok": True, "filed_under": kind}

    def forget(self, what=""):
        with self.lock:
            if (not what or what.strip().lower() in ("that", "it", "last")) and self.last_written:
                target = self.last_written[0]
            else:
                q = _words(what)
                best = max(self.notes, key=lambda n: len(q & _words(n["text"])), default=None)
                target = best["id"] if best and q & _words(best["text"]) else None
            gone = [n for n in self.notes if n["id"] == target]
            if not gone:
                return {"ok": False, "detail": "nothing matches that"}
            self.notes = [n for n in self.notes if n["id"] != target]
            self._save()
        return {"ok": True, "forgot": gone[0]["text"][:120]}

    def summarize(self, turns):
        return None

    def warm(self):
        pass

    def refresh(self):
        pass


def register(vector):
    vector.memory("__IDENT__", __CAMEL__Memory)
