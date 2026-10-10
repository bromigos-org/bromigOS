"""CI & PRS: the build-status board. Whether your repositories' builds pass, and the pull
requests waiting on you.

For each repository in `repos` (~/.config/bromigos/widgets/ci.toml, none by default): the
default branch's latest commit, its checks (GitHub Actions and commit statuses), and the
last ten commits' results as a strip. Then the pull requests whose review is requested
from you, and your own open pull requests with their checks and review state.

One GraphQL query through your `gh` login answers all of it, every 3 minutes while the
panel is on screen. The GITHUB panel is the personal feed (notifications, issues, stars);
this one is only builds and reviews.
"""
import json
import os
import re
import shutil
import subprocess
import sys
import time

sys.path.append(os.path.dirname(os.path.realpath(__file__)))   # after the standard library
import _kit as K  # noqa: E402

import draw as D  # noqa: E402

REPO_RE = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
COLORS = {"ok": "phosphor", "fail": "danger", "pending": "amber", "none": "static"}
WORDS = {"ok": "passing", "fail": "failing", "pending": "running", "none": "no checks"}

_COMMIT = """oid messageHeadline committedDate url
          statusCheckRollup { state contexts(first: 40) { nodes { __typename
            ... on CheckRun { name conclusion status detailsUrl }
            ... on StatusContext { context state targetUrl } } } }"""
_PR = """number title url updatedAt isDraft repository { nameWithOwner } author { login }"""


def query(repos):
    """The one GraphQL query: every repository (aliased r0, r1, …), then the searches."""
    parts = []
    for i, r in enumerate(repos):
        owner, name = r.split("/", 1)
        parts.append(f"""r{i}: repository(owner: {json.dumps(owner)}, name: {json.dumps(name)}) {{
      nameWithOwner url defaultBranchRef {{ name target {{ ... on Commit {{ {_COMMIT}
        history(first: 10) {{ nodes {{ oid messageHeadline committedDate statusCheckRollup {{ state }} }} }} }} }} }} }}""")
    parts.append("viewer { login }")
    parts.append(f"""review: search(query: "is:pr is:open review-requested:@me archived:false", type: ISSUE, first: 30) {{
      issueCount nodes {{ ... on PullRequest {{ {_PR} }} }} }}""")
    parts.append(f"""mine: search(query: "is:pr is:open author:@me archived:false", type: ISSUE, first: 30) {{
      issueCount nodes {{ ... on PullRequest {{ {_PR} reviewDecision
        commits(last: 1) {{ nodes {{ commit {{ statusCheckRollup {{ state }} }} }} }} }} }} }}""")
    return "query {\n  " + "\n  ".join(parts) + "\n}"


def rollup(state):
    """GitHub's rollup state -> ok | fail | pending | none."""
    s = (state or "").upper()
    if s == "SUCCESS":
        return "ok"
    if s in ("FAILURE", "ERROR"):
        return "fail"
    if s in ("PENDING", "EXPECTED"):
        return "pending"
    return "none"


def check_state(n):
    if n.get("__typename") == "StatusContext" or "context" in n:
        return rollup(n.get("state"))
    if (n.get("status") or "").upper() != "COMPLETED":
        return "pending"
    c = (n.get("conclusion") or "").upper()
    if c in ("SUCCESS", "NEUTRAL", "SKIPPED"):
        return "ok"
    return "fail"


def _pr(n):
    repo = (n.get("repository") or {}).get("nameWithOwner") or "?"
    out = {"repo": repo, "number": n.get("number"), "title": str(n.get("title") or ""), "url": n.get("url"),
           "updated": K.iso_time(n.get("updatedAt")), "draft": bool(n.get("isDraft")),
           "author": (n.get("author") or {}).get("login")}
    if "reviewDecision" in n:
        out["review"] = n.get("reviewDecision")
        commits = ((n.get("commits") or {}).get("nodes") or [])
        roll = ((commits[0] or {}).get("commit") or {}).get("statusCheckRollup") if commits else None
        out["checks"] = rollup((roll or {}).get("state")) if roll else "none"
    return out


def parse(doc, repos):
    """gh api graphql's answer -> {viewer, repos: [...], review: [...], mine: [...], review_count}.
    A repository GitHub doesn't know (or you can't see) has missing=True."""
    data = (doc or {}).get("data") or {}
    out = {"viewer": (data.get("viewer") or {}).get("login"), "repos": [], "review": [], "mine": []}
    for i, name in enumerate(repos):
        r = data.get(f"r{i}")
        if not r:
            out["repos"].append({"name": name, "missing": True, "url": f"https://github.com/{name}"})
            continue
        ref = r.get("defaultBranchRef") or {}
        c = ref.get("target") or {}
        roll = c.get("statusCheckRollup") or {}
        checks = [{"name": n.get("name") or n.get("context") or "?", "state": check_state(n),
                   "url": n.get("detailsUrl") or n.get("targetUrl")}
                  for n in ((roll.get("contexts") or {}).get("nodes") or []) if n]
        hist = [rollup((h.get("statusCheckRollup") or {}).get("state")) if h.get("statusCheckRollup") else "none"
                for h in ((c.get("history") or {}).get("nodes") or [])]
        hist.reverse()                                     # oldest first, newest at the right
        out["repos"].append({"name": r.get("nameWithOwner") or name, "url": r.get("url"), "missing": False,
                             "branch": ref.get("name"), "state": rollup(roll.get("state")) if roll else "none",
                             "headline": c.get("messageHeadline") or "", "sha": (c.get("oid") or "")[:7],
                             "when": K.iso_time(c.get("committedDate")), "commit_url": c.get("url"),
                             "checks": checks, "history": hist})
    for key in ("review", "mine"):
        nodes = ((data.get(key) or {}).get("nodes") or [])
        out[key] = [_pr(n) for n in nodes if n and n.get("number")]
        out[key].sort(key=lambda p: -(p["updated"] or 0))
    out["review_count"] = (data.get("review") or {}).get("issueCount", len(out["review"]))
    return out


def clean_repos(raw):
    """(valid owner/name list, the rest)."""
    good, bad = [], []
    for r in raw:
        r = r.strip().removeprefix("https://github.com/").strip("/")
        (good if REPO_RE.match(r) else bad).append(r)
    return list(dict.fromkeys(good))[:20], bad


class GhError(Exception):
    pass


def fetch(repos):
    if not shutil.which("gh"):
        raise GhError("gh isn't installed: install github-cli, then run gh auth login")
    try:
        r = subprocess.run(["gh", "api", "graphql", "-f", "query=" + query(repos)], capture_output=True, text=True,
                           timeout=40)
    except subprocess.TimeoutExpired:
        raise GhError("GitHub didn't answer in 40 s")
    doc = None
    try:
        doc = json.loads(r.stdout) if r.stdout.strip() else None
    except ValueError:
        doc = None
    if r.returncode and not (doc and doc.get("data")):
        err = (r.stderr or "").strip()
        if "auth login" in err or "not logged" in err.lower() or "authentication" in err.lower():
            raise GhError("gh isn't signed in: run gh auth login")
        raise GhError(K.redact(err.splitlines()[-1] if err else f"gh exited {r.returncode}")[:140])
    return parse(doc, repos)


# ------------------------------------------------------------------ demo readings
_NOW = time.time()


def _demo():
    def checks(*states):
        names = ("build", "test", "lint", "docs", "package")
        return [{"name": n, "state": s, "url": None} for n, s in zip(names, states)]
    return {"viewer": "you", "review_count": 2, "repos": [
        {"name": "example-org/desk-tools", "url": "https://github.com/example-org/desk-tools", "missing": False,
         "branch": "main", "state": "ok", "headline": "clock: the seconds hand follows reduced motion", "sha": "4be1c0a",
         "when": _NOW - 1500, "commit_url": None, "checks": checks("ok", "ok", "ok", "ok"),
         "history": ["ok", "ok", "fail", "ok", "ok", "ok", "ok", "ok", "ok", "ok"]},
        {"name": "example-org/theme-kit", "url": "https://github.com/example-org/theme-kit", "missing": False,
         "branch": "main", "state": "fail", "headline": "tide: a calmer accent for high contrast", "sha": "91d3e7f",
         "when": _NOW - 3 * 3600, "commit_url": None, "checks": checks("ok", "fail", "ok", "pending"),
         "history": ["ok", "ok", "ok", "ok", "ok", "pending", "ok", "ok", "fail", "fail"]},
        {"name": "example-org/relay-firmware", "url": "https://github.com/example-org/relay-firmware", "missing": False,
         "branch": "trunk", "state": "pending", "headline": "radio: retry the handshake twice", "sha": "07aa2d9",
         "when": _NOW - 240, "commit_url": None, "checks": checks("ok", "pending", "pending"),
         "history": ["ok", "ok", "ok", "fail", "ok", "ok", "ok", "ok", "ok", "pending"]},
        {"name": "example-org/notes-sync", "url": "https://github.com/example-org/notes-sync", "missing": False,
         "branch": "main", "state": "ok", "headline": "sync: keep the newer copy on conflict", "sha": "c33f810",
         "when": _NOW - 2 * 86400, "commit_url": None, "checks": checks("ok", "ok"),
         "history": ["none", "ok", "ok", "ok", "ok", "ok", "ok", "ok", "ok", "ok"]}],
        "review": [{"repo": "example-org/desk-tools", "number": 88, "title": "weather: say where the forecast comes from",
                    "url": "https://github.com/example-org/desk-tools/pull/88", "updated": _NOW - 2400, "draft": False,
                    "author": "harbor-dev"},
                   {"repo": "example-org/theme-kit", "number": 31, "title": "ember: warmer amber for warnings",
                    "url": "https://github.com/example-org/theme-kit/pull/31", "updated": _NOW - 7 * 3600, "draft": False,
                    "author": "lamplighter"}],
        "mine": [{"repo": "example-org/relay-firmware", "number": 12, "title": "radio: retry the handshake twice",
                  "url": "https://github.com/example-org/relay-firmware/pull/12", "updated": _NOW - 600, "draft": False,
                  "author": "you", "review": "REVIEW_REQUIRED", "checks": "pending"},
                 {"repo": "example-org/notes-sync", "number": 5, "title": "sync: a dry run that lists what would change",
                  "url": "https://github.com/example-org/notes-sync/pull/5", "updated": _NOW - 26 * 3600, "draft": False,
                  "author": "you", "review": "APPROVED", "checks": "ok"},
                 {"repo": "example-org/theme-kit", "number": 29, "title": "wip: a seasonal palette",
                  "url": "https://github.com/example-org/theme-kit/pull/29", "updated": _NOW - 4 * 86400, "draft": True,
                  "author": "you", "review": None, "checks": "fail"}]}


# ------------------------------------------------------------------ the panel
class CiPanel(K.KitPanel):
    name, title = "ci", "CI & PRS"
    description = ("The build-status board: your repositories' CI and the pull requests waiting on you "
                   "(the GitHub panel is your personal feed)")
    category, reads = "notes", "GitHub through your gh login, every 3 minutes while shown"
    width, height = 480, 300
    interval = 10.0
    sizes = {
        "compact": ((240, 120), (380, 190), (280, 140)),
        "standard": ((400, 240), (640, 420), (480, 300)),
        "wide": ((660, 200), (1200, 380), (820, 260)),
        "tall": ((380, 440), (580, 960), (440, 600)),
        "large": ((680, 480), (1300, 960), (860, 600)),
    }
    default_size = "standard"
    settings = [{"key": "repos", "label": "Repositories", "kind": "list", "default": [],
                 "hint": "owner/name, one per line: the repositories whose builds it shows"},
                {"key": "mine", "label": "Show my open pull requests", "kind": "bool", "default": True,
                 "hint": "Your own pull requests, with their checks and review"}]

    def __init__(self, cfg=None, wake=None):
        super().__init__(cfg, wake)
        if K.demo():
            self.poll = None
            self.demo = _demo()
        else:
            self.demo = None
            self.poll = self.poller(lambda: fetch(self.repos()[0]), every=180, name="gh")

    def repos(self):
        return clean_repos(self.conf.list("repos"))

    def state(self):
        if self.demo is not None:
            return self.demo, None, time.time() - 70
        at = (time.time() - (time.monotonic() - self.poll.at)) if self.poll.at else None
        return self.poll.data, self.poll.error, at

    def refresh(self):
        if self.poll:
            self.poll.kick()

    # ---- drawing
    def draw(self, cr, w, h):
        cls = self.size_class(w, h)
        d, err, at = self.state()
        right = None
        if d and cls != "compact":
            fails = sum(1 for r in d["repos"] if r.get("state") == "fail")
            right = (f"{fails} FAILING" if fails else "ALL GREEN" if d["repos"] else None)
        top = D.frame(cr, w, h, self.title, right, "danger" if right and "FAILING" in right else "phosphor")
        self.region(0, 0, w, 34, "The build-status board: your repositories' CI on their default branch and the pull "
                    "requests waiting on you, through your gh login every 3 minutes while it's on screen. "
                    f"Repositories go in {K.home_path(K.settings_path('ci'))}. Click to check now."
                    + (f" Last checked {K.ago(at)} ago." if at else ""), self.refresh)
        if d is None:
            if err:
                self.empty(cr, w, h, top, "CAN'T REACH GITHUB" if "gh" not in err else "GH ISN'T READY", err + ".",
                           button=("Try again", "Ask GitHub again now", self.refresh))
            else:
                self.empty(cr, w, h, top, "CHECKING…", "Asking GitHub about your builds and reviews.", color="static")
            return
        x0, x1 = 16, w - 16
        if cls == "compact":
            self._compact(cr, d, x0, x1, top, h)
        elif cls == "standard":
            y = self._repos(cr, d, x0, x1, top, top + (h - top) * 0.56, strip=False)
            self._prlist(cr, d["review"], "WAITING ON YOUR REVIEW", x0, x1, y + 6, h - 12, kind="review")
        elif cls == "wide":
            mid = x0 + (x1 - x0) * 0.55
            self._repos(cr, d, x0, mid - 18, top, h - 12, strip=True)
            half = top + (h - 12 - top) / 2
            if self.conf.get("mine", True):
                self._prlist(cr, d["review"], "WAITING ON YOUR REVIEW", mid, x1, top, half - 4, kind="review")
                self._prlist(cr, d["mine"], "YOURS", mid, x1, half + 4, h - 12, kind="mine")
            else:
                self._prlist(cr, d["review"], "WAITING ON YOUR REVIEW", mid, x1, top, h - 12, kind="review")
        elif cls == "tall":
            y = self._repos(cr, d, x0, x1, top, top + (h - top) * 0.45, strip=True)
            mid = min(y + 6 + 18 + 34 * max(1, len(d["review"])) + 8, y + (h - y) * 0.5)
            self._prlist(cr, d["review"], "WAITING ON YOUR REVIEW", x0, x1, y + 6, mid - 4, kind="review")
            if self.conf.get("mine", True):
                self._prlist(cr, d["mine"], "YOURS", x0, x1, mid + 4, h - 12, kind="mine")
        else:
            y = self._repos(cr, d, x0, x1, top, top + (h - top) * 0.6, strip=True, checks=True)
            mid = x0 + (x1 - x0) / 2
            self._prlist(cr, d["review"], "WAITING ON YOUR REVIEW", x0, mid - 12, y + 8, h - 12, kind="review")
            if self.conf.get("mine", True):
                self._prlist(cr, d["mine"], "YOURS", mid + 12, x1, y + 8, h - 12, kind="mine")

    def _compact(self, cr, d, x0, x1, top, h):
        repos = [r for r in d["repos"] if not r.get("missing")]
        counts = {k: sum(1 for r in repos if r["state"] == k) for k in ("ok", "fail", "pending", "none")}
        # a row of lights, one per repository
        n = len(repos)
        if n:
            size = max(8, min(22 + max(0, (h - 150) * 0.5), (x1 - x0) / max(n, 1) - 4))
            for i, r in enumerate(repos[:16]):
                lx = x0 + i * (size + 4)
                D.src(cr, COLORS[r["state"]], 0.9)
                cr.rectangle(lx, top + 2, size, size)
                cr.fill()
                self.region(lx, top + 2, size, size, f"{r['name']}: {WORDS[r['state']]} on {r['branch']} "
                            f"({r['headline'][:60]}). Click to open its Actions.",
                            lambda u=r["url"]: K.open_url(u + "/actions"))
            word = (f"{counts['fail']} FAILING" if counts["fail"] else f"{counts['pending']} RUNNING" if counts["pending"]
                    else f"{counts['ok']}/{n} PASSING")
            col = "danger" if counts["fail"] else "amber" if counts["pending"] else "phosphor"
            wy = top + size + 8
            D.text(cr, x0, wy, word, 15, col, "bold", spacing=0.06)
            self.region(x0, wy - 2, x1 - x0, 22, f"{counts['ok']} passing, {counts['fail']} failing, "
                        f"{counts['pending']} running, {counts['none']} without checks")
        else:
            D.label(cr, x0, top + 4, "NO REPOSITORIES", "amber", size=10)
            D.text(cr, x0, top + 20, "Add some in ci.toml", 10, "static", "regular", width=x1 - x0)
            self.region(x0, top, x1 - x0, 34, f"Add repos = [\"owner/name\"] to {K.home_path(K.settings_path('ci'))}")
        rv = d.get("review_count") or 0
        y = h - 26
        D.label(cr, x0, y, f"{rv} REVIEW(S) WAITING", "amber" if rv else "static", size=10)
        self.region(x0, y - 2, x1 - x0, 18, f"{rv} pull request(s) ask for your review"
                    + (f"; newest: {d['review'][0]['repo']}#{d['review'][0]['number']} {d['review'][0]['title']}. "
                       "Click to open it." if d["review"] else ""),
                    (lambda u=d["review"][0]["url"]: K.open_url(u)) if d["review"] else None)

    def _repos(self, cr, d, x0, x1, top, bottom, strip=False, checks=False):
        """A row per repository: its light, name, the latest commit, and (strip) its last ten
        results. Returns the y under them."""
        D.label(cr, x0, top, "BUILDS", "dim", size=10)
        D.rule(cr, x0 + 66, top + 7, x1, "dim", 0.3)
        y = top + 18
        repos = d["repos"]
        _good, bad = self.repos()
        if not repos:
            path = K.home_path(K.settings_path("ci"))
            D.text(cr, x0, y, f"No repositories yet. Add them to {path}:", 11, "soft", "regular", width=x1 - x0,
                   wrap=True)
            D.text(cr, x0, y + 32, 'repos = ["owner/name", "owner/other"]', 11, "phosphor", "medium", width=x1 - x0)
            self.region(x0, top, x1 - x0, 64, f"The board shows the repositories you list: repos = [\"owner/name\"] in {path} "
                        "(or the gallery card's Settings…). It rereads the file when it changes.")
            return y + 56
        row = 36 if (checks or strip) else 34
        avail = max(1, int((bottom - y) // row))
        for r in repos[:avail]:
            if r.get("missing"):
                D.dot(cr, x0 + 5, y + 8, 3.2, "static", glow=False)
                D.text(cr, x0 + 16, y, r["name"], 12, "static", "semibold", width=x1 - x0 - 16)
                D.text(cr, x0 + 16, y + 16, "not found, or your gh login can't see it", 10, "amber", "regular")
                self.region(x0, y - 1, x1 - x0, row - 2, f"{r['name']}: GitHub doesn't know it, or your gh login can't "
                            "see it. Check the name in ci.toml.")
                y += row
                continue
            col = COLORS[r["state"]]
            D.dot(cr, x0 + 5, y + 8, 3.6, col, glow=r["state"] != "none")
            sw = 0
            if strip and r["history"]:
                cell = 14 if checks and (x1 - x0) > 900 else 9
                sw = len(r["history"]) * (cell + 2)
                sx = x1 - sw
                for i, hs in enumerate(r["history"]):
                    D.src(cr, COLORS[hs], 0.9 if hs != "none" else 0.35)
                    cr.rectangle(sx + i * (cell + 2), y + 3, cell, 10)
                    cr.fill()
                self.region(sx, y, sw, 16, f"{r['name']}: its last {len(r['history'])} commits on {r['branch']}, oldest "
                            "first: " + ", ".join(WORDS[s] for s in r["history"]))
                sw += 10
            name = r["name"].split("/", 1)[1] if len(r["name"]) > 28 else r["name"]
            D.text(cr, x0 + 16, y, name, 12, "soft", "semibold", width=x1 - x0 - 16 - sw - 60)
            D.label(cr, x1 - sw, y + 1, WORDS[r["state"]].upper(), col, size=10, align="right")
            sub = f"{r['branch']} · {r['sha']} · {K.ago(r['when'])} · {r['headline']}"
            D.text(cr, x0 + 16, y + 16, sub, 10, "static", "regular", width=x1 - x0 - 16)
            failing = [c for c in r["checks"] if c["state"] == "fail"]
            running = [c for c in r["checks"] if c["state"] == "pending"]
            tip = (f"{r['name']} on {r['branch']}: {WORDS[r['state']]}. Latest commit {r['sha']}, {K.ago(r['when'])} ago: "
                   f"{r['headline']}. {len(r['checks'])} check(s)"
                   + (f"; failing: {', '.join(c['name'] for c in failing)}" if failing else "")
                   + (f"; running: {', '.join(c['name'] for c in running)}" if running else "")
                   + ". Click to open its Actions.")
            self.region(x0, y - 1, x1 - x0 - sw, row - 2, tip, lambda u=r["url"]: K.open_url(u + "/actions"))
            y += row
            if checks and r["checks"]:
                cx = x0 + 16
                order = failing + running + [c for c in r["checks"] if c["state"] not in ("fail", "pending")]
                for c in order[:12]:
                    lab = c["name"][:22]
                    cw = D.layout(cr, lab.upper(), 9, "semibold", 0.1).get_pixel_size()[0] + 10
                    if cx + cw > x1:
                        break
                    self.chip(cr, cx, y - 2, lab, COLORS[c["state"]])
                    self.region(cx, y - 2, cw, 15, f"{c['name']}: {WORDS[c['state']]}" + (". Click to open it." if c.get("url")
                                                                                          else ""),
                                (lambda u=c["url"]: K.open_url(u)) if c.get("url") else None)
                    cx += cw + 5
                y += 18
        if len(repos) > avail:
            D.label(cr, x1, y, f"+{len(repos) - avail} MORE", "static", size=10, align="right")
            self.region(x1 - 90, y - 2, 90, 14, f"{len(repos) - avail} more repositories; make the panel bigger to see them")
            y += 14
        if bad:
            D.text(cr, x0, y, f"Not owner/name: {', '.join(bad)[:60]}", 10, "amber", "regular", width=x1 - x0)
            self.region(x0, y - 1, x1 - x0, 15, "These entries in ci.toml aren't owner/name, so they're left out")
            y += 16
        return y

    def _prlist(self, cr, prs, head, x0, x1, top, bottom, kind="review"):
        D.label(cr, x0, top, f"{head} · {len(prs)}", "dim", size=10)
        D.rule(cr, x0 + D.layout(cr, f"{head} · {len(prs)}", 10, "semibold", 0.18).get_pixel_size()[0] + 10, top + 7, x1,
               "dim", 0.3)
        y = top + 18
        if not prs:
            msg = "Nothing waits on you." if kind == "review" else "No open pull requests of yours."
            D.text(cr, x0, y, msg, 11, "static", "regular")
            self.region(x0, top, x1 - x0, 34, msg)
            return
        row = 34
        n = max(1, int((bottom - y) // row))
        for p in prs[:n]:
            x = x0
            if kind == "mine":
                c = p.get("checks") or "none"
                D.dot(cr, x0 + 5, y + 8, 3.2, COLORS[c], glow=c != "none")
                x = x0 + 16
            D.text(cr, x, y, p["title"], 11, "static" if p["draft"] else "soft", "medium", width=x1 - x)
            meta = f"{p['repo']}#{p['number']} · {K.ago(p['updated'])}"
            if kind == "review" and p.get("author"):
                meta += f" · {p['author']}"
            cx = x
            if p["draft"]:
                cx += self.chip(cr, cx, y + 16, "draft", "static") + 5
            if kind == "mine" and p.get("review"):
                rv = {"APPROVED": ("approved", "phosphor"), "CHANGES_REQUESTED": ("changes", "danger"),
                      "REVIEW_REQUIRED": ("needs review", "amber")}.get(p["review"], (p["review"].lower(), "static"))
                cx += self.chip(cr, cx, y + 16, rv[0], rv[1]) + 5
            D.text(cr, cx, y + 17, meta, 10, "static", "regular", width=max(10, x1 - cx))
            if kind == "review":
                tip = (f"{p['repo']}#{p['number']} by {p.get('author') or '?'}: {p['title']}. It asks for your review; "
                       f"updated {K.ago(p['updated'])} ago. Click to open it.")
            else:
                tip = (f"Your {p['repo']}#{p['number']}: {p['title']}. Checks {WORDS[p.get('checks') or 'none']}"
                       + (f", review {p['review'].replace('_', ' ').lower()}" if p.get("review") else "")
                       + (", a draft" if p["draft"] else "") + ". Click to open it.")
            self.region(x0, y - 1, x1 - x0, row - 2, tip, lambda u=p["url"]: K.open_url(u))
            y += row
        if len(prs) > n:
            D.label(cr, x1, bottom - 10, f"+{len(prs) - n} MORE", "static", size=10, align="right")
            self.region(x1 - 90, bottom - 12, 90, 14, f"{len(prs) - n} more; make the panel bigger to see them")


PANEL = CiPanel
LAYOUT = {"visible": False}
