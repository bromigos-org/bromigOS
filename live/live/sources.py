"""Real data for VECTOR's holograms, each read only while a deck that needs it is open.

  prom(q)            Prometheus instant query through bromigos-homelab (docs/homelab.md) ~20-60 ms;
                     OSError without the package or a [prometheus] url
  repos()            every git repo under ~/github.com/<org>/ for each of orgs() + ~/.dotfiles
  git_state(r)       branch, dirty files, ahead/behind, commits in 14 days (4 git calls, ~15 ms)
  pushes(rs, since)  pushes seen in the remote-tracking reflogs ("update by push"): stats only
  gh_json(args)      gh CLI, the operator's login (~0.4-1 s a call; keep to a few per poll)
  herdr()            herdr api snapshot: every agent pane with status and cwd (~30 ms)
  ping(host)         one ICMP echo, ms or None (1 s timeout)
"""
import json
import os
import re
import shutil
import subprocess
import time
import urllib.parse

HOME = os.path.expanduser("~")


def orgs():
    """The GitHub orgs the Swarm and Ops show, in ring order: config.toml [swarm] orgs, else
    homelab.toml [github] orgs, else every folder under ~/github.com (sorted)."""
    from . import config
    from .homelab import H
    want = config.load().get("swarm", {}).get("orgs") or (H.github_orgs() if H else ())
    if want:
        return tuple(want)
    try:
        base = os.path.join(HOME, "github.com")
        return tuple(sorted(d for d in os.listdir(base) if os.path.isdir(os.path.join(base, d))))
    except OSError:
        return ()


def rings():
    """{org: orbit radius} for the Swarm: config.toml [swarm] rings, else evenly 0.48..1.10."""
    from . import config
    os_ = orgs()
    given = config.load().get("swarm", {}).get("rings") or {}
    n = max(1, len(os_) - 1)
    return {o: float(given.get(o, 0.48 + 0.62 * i / n if len(os_) > 1 else 0.8)) for i, o in enumerate(os_)}
def _rows(res):
    """A metrics Result as Prometheus API rows ({"metric", "value": [t, "v"]}): the decks' shape."""
    if not res["ok"]:
        raise OSError("; ".join(f"{k}: {v}" for k, v in res["errors"].items()) or "no metrics source in homelab.toml")
    return res["items"]


def prom(q, timeout=8):
    """A metrics query through bromigos-homelab, as Prometheus API rows. OSError without the
    package, without a metrics source, or when it's unreachable."""
    from .homelab import H
    if not H:
        raise OSError("no homelab integrations here (bromigos-homelab isn't installed)")
    return [{"metric": r["labels"], "value": [r["t"], str(r["value"])]} for r in _rows(H.metrics(q, timeout))]


def prom_range(q, minutes, step=60):
    from .homelab import H
    if not H:
        raise OSError("no homelab integrations here (bromigos-homelab isn't installed)")
    return [{"metric": r["labels"], "values": [[t, str(v)] for t, v in r["points"]]}
            for r in _rows(H.metrics_range(q, minutes, step))]


# The daemon starts from Hyprland's login autostart, whose PATH lacks the user's bin dirs
# (herdr lives in ~/.local/bin), so bare command names are resolved against them too.
_USER_BINS = [os.path.expanduser(p) for p in ("~/.local/bin", "~/.cargo/bin")]


def _resolve(cmd):
    if os.sep in cmd:
        return cmd
    path = os.pathsep.join([os.environ.get("PATH", "")] + _USER_BINS)
    return shutil.which(cmd, path=path) or cmd


def run(args, timeout=15, cwd=None):
    args = [_resolve(args[0])] + list(args[1:])
    r = subprocess.run(args, capture_output=True, text=True, timeout=timeout, cwd=cwd)
    return r.stdout if r.returncode == 0 else ""


_repos = {"at": 0, "list": []}


def repos():
    if time.time() - _repos["at"] < 300:
        return _repos["list"]
    out = []
    org_list = orgs()
    for org in org_list:
        base = os.path.join(HOME, "github.com", org)
        try:
            names = sorted(os.listdir(base))
        except OSError:
            continue
        for n in names:
            p = os.path.join(base, n)
            if os.path.isdir(os.path.join(p, ".git")):
                out.append({"name": n, "org": org, "path": p})
    dot = os.path.join(HOME, ".dotfiles")
    if os.path.isdir(os.path.join(dot, ".git")):
        out.append({"name": "dotfiles", "org": None, "path": dot})
    for r in out:
        url = run(["git", "-C", r["path"], "config", "--get", "remote.origin.url"], 5).strip()
        m = re.search(r"github\.com[:/]([^/]+)/([^/]+?)(\.git)?/?$", url)
        r["slug"] = f"{m.group(1)}/{m.group(2)}" if m else None
        if r["org"] is None:     # the dotfiles: their GitHub owner's ring, else the last ring
            owner = m.group(1) if m else ""
            r["org"] = owner if owner in org_list else (org_list[-1] if org_list else owner or "dotfiles")
    _repos.update(at=time.time(), list=out)
    return out


def git_state(r):
    p = r["path"]
    st = run(["git", "-C", p, "status", "--porcelain=v1", "-b"], 8).splitlines()
    head = st[0] if st else ""
    dirty = len(st) - 1 if st else 0
    ahead = int(m.group(1)) if (m := re.search(r"ahead (\d+)", head)) else 0
    behind = int(m.group(1)) if (m := re.search(r"behind (\d+)", head)) else 0
    branch = head[3:].split("...")[0] if head.startswith("## ") else "?"
    n14 = run(["git", "-C", p, "rev-list", "--count", "--since=14.days", "HEAD"], 8).strip()
    last = run(["git", "-C", p, "log", "-1", "--format=%ct %s"], 5).strip()
    t, _, subj = last.partition(" ")
    return {"branch": branch, "dirty": dirty, "ahead": ahead, "behind": behind,
            "commits14": int(n14 or 0), "last_t": int(t or 0), "last_subject": subj}


def pushes(rs, since):
    """[(time, repo, branch, sha)] from 'update by push' lines in the remote-tracking reflogs."""
    out = []
    for r in rs:
        d = os.path.join(r["path"], ".git", "logs", "refs", "remotes", "origin")
        try:
            files = [os.path.join(d, f) for f in os.listdir(d)]
        except OSError:
            continue
        for f in files:
            try:
                if os.path.getmtime(f) < since or not os.path.isfile(f):
                    continue
                with open(f, errors="replace") as fh:
                    lines = fh.readlines()[-5:]
            except OSError:
                continue
            for ln in lines:
                if "update by push" not in ln:
                    continue
                parts = ln.split()
                m = re.search(r"> (\d+) [+-]\d{4}\t", ln)
                if m and int(m.group(1)) >= since:
                    out.append((int(m.group(1)), r, os.path.basename(f), parts[1]))
    return sorted(out, key=lambda x: x[0])


def gh_json(args, timeout=20):
    out = run(["gh"] + args, timeout)
    return json.loads(out) if out.strip() else None


def check_runs(slug, sha):
    """CI for one commit: every check run, in start order."""
    d = gh_json(["api", f"repos/{slug}/commits/{sha}/check-runs", "--jq",
                 "[.check_runs[] | {name, status, conclusion, started_at, completed_at}]"])
    return sorted(d or [], key=lambda c: c.get("started_at") or "")


def latest_ci(slug):
    d = gh_json(["run", "list", "-R", slug, "-L", "1", "--json", "status,conclusion,workflowName,createdAt,headSha"])
    return (d or [None])[0]


def herdr():
    out = run(["herdr", "api", "snapshot"], 5)
    if not out:
        return []
    snap = (json.loads(out).get("result") or {}).get("snapshot") or {}
    panes = {p.get("pane_id"): p for p in snap.get("panes") or []}
    agents = []
    for a in snap.get("agents") or []:
        a = dict(a)
        a["pane"] = panes.get(a.get("pane_id"), {})
        agents.append(a)
    return agents


def ping(host, timeout=1):
    out = run(["ping", "-n", "-c", "1", "-W", str(timeout), host], timeout + 1)
    m = re.search(r"time=([\d.]+) ms", out)
    return float(m.group(1)) if m else None
