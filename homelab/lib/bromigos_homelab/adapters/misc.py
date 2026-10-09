"""Vault (secrets: status only), herdr (agents), GitHub (ci), Docker (workloads, hosts),
and a Lab API that serves the whole lab snapshot (snapshot, hosts)."""
import http.client
import json
import os
import re
import shutil
import socket
import subprocess
import time

from .. import config
from ..registry import Adapter, Unreachable, register


# ------------------------------------------------------------------ Vault
@register
class Vault(Adapter):
    type = "vault"
    provides = ("secrets",)
    default_ports = (8200,)

    def probe(self):
        d = self.get_json("/v1/sys/health?standbyok=true&sealedcode=200&uninitcode=200", timeout=3)
        return isinstance(d, dict) and "sealed" in d

    def secrets(self):
        """sys/health only: whether Vault is up, initialized, sealed. Never reads a secret."""
        d = self.get_json("/v1/sys/health?standbyok=true&perfstandbyok=true&sealedcode=200&uninitcode=200", timeout=4)
        return [{"name": self.name, "reachable": True, "initialized": d.get("initialized"), "sealed": d.get("sealed"),
                 "standby": d.get("standby"), "version": d.get("version")}]


# ------------------------------------------------------------------ herdr
def herdr_status(s):
    """herdr's agent_status as a capability status."""
    s = (s or "").lower()
    if s in ("working", "busy", "running"):
        return "working"
    if s in ("blocked", "waiting", "needs_input", "permission", "attention"):
        return "needs_you"
    if s in ("error", "failed", "crashed", "exited"):
        return "error"
    return "finished"


@register
class Herdr(Adapter):
    type = "herdr"
    provides = ("agents",)
    local = True

    def _bin(self):
        return shutil.which("herdr") or next((p for p in (os.path.expanduser("~/.local/bin/herdr"),
                                                          os.path.expanduser("~/.cargo/bin/herdr")) if os.path.exists(p)), "")

    def configured(self):
        return bool(self._bin())

    def probe(self):
        return bool(self._bin())

    def agents(self):
        try:
            p = subprocess.run([self._bin(), "api", "snapshot"], capture_output=True, text=True, timeout=5)
        except (OSError, subprocess.TimeoutExpired) as e:
            raise Unreachable(f"{self.name}: {e}") from None
        if p.returncode != 0:
            raise Unreachable(f"{self.name}: {(p.stderr or p.stdout).strip()[:160]}")
        snap = (json.loads(p.stdout or "{}").get("result") or {}).get("snapshot") or {}
        panes = {x.get("pane_id"): x for x in snap.get("panes") or []}
        out = []
        for a in snap.get("agents") or []:
            key = a.get("terminal_id") or a.get("pane_id") or json.dumps(a.get("agent_session"))
            cwd = a.get("cwd") or (panes.get(a.get("pane_id")) or {}).get("cwd") or ""
            out.append({"key": str(key), "name": a.get("agent") or a.get("name") or "",
                        "status": herdr_status(a.get("agent_status")), "cwd": cwd})
        return out


# ------------------------------------------------------------------ GitHub (the gh CLI's login)
@register
class GitHub(Adapter):
    type = "github"
    provides = ("ci",)
    local = True

    def configured(self):
        return bool(shutil.which("gh")) and bool(self.opts.get("orgs") or self.opts.get("repos"))

    def _gh(self, args, timeout=25):
        try:
            p = subprocess.run(["gh"] + args, capture_output=True, text=True, timeout=timeout)
        except (OSError, subprocess.TimeoutExpired) as e:
            raise Unreachable(f"{self.name}: {e}") from None
        if p.returncode != 0:
            raise Unreachable(f"{self.name}: {(p.stderr or p.stdout).strip()[:160]}")
        return json.loads(p.stdout or "[]")

    def ci(self, limit=20):
        out = []
        for org in self.opts.get("orgs") or []:
            for pr in self._gh(["search", "prs", "--owner", org, "--state", "open", "--limit", str(limit),
                                "--json", "repository,number,title,url,updatedAt"]):
                out.append({"repo": (pr.get("repository") or {}).get("nameWithOwner"), "kind": "pr", "number": pr.get("number"),
                            "title": pr.get("title"), "status": "open", "conclusion": None, "url": pr.get("url"),
                            "updated": pr.get("updatedAt")})
        for repo in self.opts.get("repos") or []:
            for r in self._gh(["run", "list", "-R", repo, "-L", "3", "--json",
                               "databaseId,displayTitle,status,conclusion,url,updatedAt"]):
                out.append({"repo": repo, "kind": "run", "number": r.get("databaseId"), "title": r.get("displayTitle"),
                            "status": r.get("status"), "conclusion": r.get("conclusion") or None, "url": r.get("url"),
                            "updated": r.get("updatedAt")})
        return sorted(out, key=lambda x: x.get("updated") or "", reverse=True)[:limit]


# ------------------------------------------------------------------ Docker (the engine API)
class _UnixHTTP(http.client.HTTPConnection):
    def __init__(self, path, timeout=6):
        super().__init__("localhost", timeout=timeout)
        self.path = path

    def connect(self):
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.settimeout(self.timeout)
        self.sock.connect(self.path)


_DSTATE = {"running": "running", "created": "pending", "restarting": "pending", "paused": "stopped",
           "exited": "stopped", "dead": "failed", "removing": "stopped"}


@register
class Docker(Adapter):
    """endpoint: "unix:///var/run/docker.sock" (the default) or "http://host:2375"."""
    type = "docker"
    provides = ("workloads", "hosts")
    local = True
    default_ports = (2375,)

    def _sock(self):
        ep = self.endpoint or "unix:///var/run/docker.sock"
        return ep[len("unix://"):] if ep.startswith("unix://") else ""

    def configured(self):
        s = self._sock()
        return os.path.exists(s) if s else bool(self.endpoint)

    def _get(self, path):
        s = self._sock()
        if not s:
            return self.get_json(path, timeout=6)
        try:
            c = _UnixHTTP(s)
            c.request("GET", path)
            r = c.getresponse()
            body = r.read()
            c.close()
        except OSError as e:
            raise Unreachable(f"{self.name}: {e}") from None
        if r.status >= 400:
            raise RuntimeError(f"docker {path}: HTTP {r.status}")
        return json.loads(body or b"null")

    def probe(self):
        d = self._get("/version")
        return isinstance(d, dict) and "ApiVersion" in d

    def workloads(self):
        out = []
        for c in self._get("/containers/json?all=1") or []:
            name = (c.get("Names") or ["?"])[0].lstrip("/")
            restarts = None
            m = re.search(r"Restarting \((\d+)\)", c.get("Status") or "")
            out.append({"name": name, "namespace": (c.get("Labels") or {}).get("com.docker.compose.project"),
                        "kind": "container", "state": _DSTATE.get(c.get("State"), "unknown"),
                        "restarts": int(m.group(1)) if m else restarts, "node": self.name, "image": c.get("Image")})
        return out

    def hosts(self):
        i = self._get("/info") or {}
        return [{"name": i.get("Name") or self.name, "up": True, "cores": i.get("NCPU"),
                 "mem_total": i.get("MemTotal"), "containers_running": i.get("ContainersRunning")}]


# ------------------------------------------------------------------ a Lab API (the whole snapshot)
@register
class LabAPI(Adapter):
    """A service that already serves the lab snapshot (GET <endpoint>/api/status, bearer
    auth_ref): a homelab's own status service. Its snapshot is used as it comes."""
    type = "lab"
    provides = ("snapshot", "hosts")
    default_scheme = "https"

    def probe(self):
        d = self.get_json("/api/status", timeout=3)
        return isinstance(d, dict) and "generatedAt" in d

    def snapshot(self):
        return self.get_json("/api/status", timeout=8)

    def hosts(self):
        d = self.snapshot()
        return [{"name": n.get("name"), "up": True, "cpu_pct": n.get("cpuPct"), "mem_pct": n.get("memPct"),
                 "load1": n.get("load1"), "cores": n.get("cores")} for n in d.get("nodes") or []]


# ------------------------------------------------------------------ Gnosis (memory + knowledge base)
@register
class Gnosis(Adapter):
    """A Gnosis memory service behind its gate (narrow tokens): the Mind deck's spaces and
    VECTOR's memory store and knowledge_search. endpoint: the gate. auth_ref: the read
    token; write_auth_ref: the write token (VECTOR's own space only). Options: tenant,
    spaces = [...] (knowledge-base spaces), labels = {space = "what it is"}."""
    type = "gnosis"
    provides = ("knowledge",)
    default_scheme = "https"

    def probe(self):
        try:
            d = self.get_json("/health", timeout=3)
            return isinstance(d, dict)
        except Exception:
            return False

    def write_headers(self):
        tok = config.resolve(self.opts.get("write_auth_ref") or "")
        return {"Authorization": "Bearer " + tok} if tok else {}

    def search(self, scope, query, limit=5, write=False, timeout=10):
        body = {"scope": scope, "query": query[:400], "limit": limit, "use_llm": False}
        return self.request("/v1/memories/search", data=body, method="POST", timeout=timeout,
                            headers=self.write_headers() if write else None).get("results", [])

    # ---- VECTOR's own space: his memory store (homelab/vector/homelab_gnosis.py) files his
    # notes there; `bromigos memory` exports, clears and restores them
    def vector_scope(self, session="desktop"):
        return {"tenant_id": self.opts.get("tenant") or "bromigos", "space_id": "vector", "agent_id": "vector",
                "session_id": session, "user_id": "operator", "visibility": "private_user"}

    def vector_ready(self):
        """Both tokens resolve: VECTOR's memory is here (with [memory] backend = "auto")."""
        return bool(self.endpoint and config.resolve(self.opts.get("auth_ref") or "")
                    and config.resolve(self.opts.get("write_auth_ref") or ""))

    def vector_notes(self, pages=10, timeout=15):
        """Every note in VECTOR's space, [{id, content, kind}], 200 a page (the read token)."""
        rows, page = [], 1
        while page <= pages:
            d = self.request("/v1/memories/list", data={"scope": self.vector_scope(), "page": page, "page_size": 200},
                             method="POST", timeout=timeout) or {}
            rows += d.get("results") or []
            if len(rows) >= int(d.get("total") or 0) or not d.get("results"):
                break
            page += 1
        return [{"id": r["memory_id"], "content": r["content"], "kind": (r.get("metadata") or {}).get("kind", "note")}
                for r in rows if r.get("memory_id") and r.get("content")]

    def vector_forget(self, memory_id, timeout=15):
        self.request(f"/v1/memories/{memory_id}", data={"scope": self.vector_scope()}, method="DELETE",
                     headers=self.write_headers(), timeout=timeout)

    def vector_file(self, content, kind="note", timeout=60):
        """A note filed as it was written (no fact extraction), as an undo puts it back."""
        self.request("/v1/memories", data={"scope": self.vector_scope(), "infer": False,
                                           "messages": [{"role": "user", "content": content}],
                                           "metadata": {"kind": kind, "source": "bromigos-memory"}},
                     method="POST", headers=self.write_headers(), timeout=timeout)


_ = time
