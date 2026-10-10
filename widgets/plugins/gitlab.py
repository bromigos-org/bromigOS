"""GITLAB: your GitLab feed, on gitlab.com or your own instance. The merge requests waiting
on you (assigned to you, or asking for your review), your to-do list, and the latest
pipelines of the projects you were last active in. Large adds each project's recent
pipelines as a strip.

Sign-in, through lib/bromigos_account.py with the token in your keyring: GitLab's device
flow (GitLab 17.2 or later, with an application of your own), or a personal access token
you paste with `bromigos account set-token gitlab`. Both are sent as a bearer token, which
GitLab accepts for either. The instance is `base` in the [gitlab] table of
~/.config/bromigos/accounts.toml (gitlab.com when unset).

Several accounts: gitlab.com and your company's own GitLab, say. The `account` setting
lists which to show (every signed-in one when empty). Their rows are merged, newest first,
each tagged with its account's label. Each account is read on its own, every 4 minutes
while the panel is seen.
"""
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

sys.path.append(os.path.dirname(os.path.realpath(__file__)))   # after the standard library
import _kit as K  # noqa: E402

import draw as D  # noqa: E402

EVERY = 240

STATUS = {  # pipeline status -> (colour, word)
    "success": ("phosphor", "passed"), "failed": ("danger", "failed"), "running": ("cyan", "running"),
    "pending": ("amber", "pending"), "created": ("static", "created"), "canceled": ("static", "cancelled"),
    "canceling": ("static", "cancelling"), "skipped": ("static", "skipped"), "manual": ("amber", "waiting for you"),
    "scheduled": ("static", "scheduled"), "preparing": ("amber", "preparing"),
    "waiting_for_resource": ("amber", "waiting for a runner"), "waiting_for_callback": ("amber", "waiting"),
}


class Client:
    def __init__(self, base_fn, token_fn):
        self.base_fn, self.token_fn = base_fn, token_fn

    def get(self, path, **params):
        tok = self.token_fn()
        if not tok:
            raise PermissionError("not signed in")
        url = self.base_fn().rstrip("/") + "/api/v4" + path + ("?" + urllib.parse.urlencode(params) if params else "")
        req = urllib.request.Request(url, headers={"Authorization": f"Bearer {tok}", "User-Agent": "bromigOS",
                                                  "Accept": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=15) as r:
                return json.loads(r.read() or b"null")
        except urllib.error.HTTPError as e:
            if e.code == 401:
                raise PermissionError("GitLab refused the token (401): sign in again, or store a new one") from e
            raise


# ------------------------------------------------------------------ parsing
def parse_mrs(items, why):
    return [{"iid": m.get("iid"), "title": m.get("title") or "?", "url": m.get("web_url"),
             "project": (m.get("references") or {}).get("full", "").split("!")[0] or str(m.get("project_id", "?")),
             "author": (m.get("author") or {}).get("username"), "updated": K.iso_time(m.get("updated_at")),
             "draft": bool(m.get("draft") or m.get("work_in_progress")), "why": why,
             "conflicts": bool(m.get("has_conflicts")), "pipeline": ((m.get("head_pipeline") or m.get("pipeline") or {})
                                                                     .get("status"))}
            for m in items or []]


def merge_mrs(*lists):
    """One list, each MR once (a review asked of you wins over assigned), newest first."""
    seen, out = set(), []
    for lst in lists:
        for m in lst:
            if m["url"] in seen:
                continue
            seen.add(m["url"])
            out.append(m)
    out.sort(key=lambda m: -(m["updated"] or 0))
    return out


TODO_WORDS = {"assigned": "assigned you", "mentioned": "mentioned you", "build_failed": "pipeline failed",
              "marked": "added a to-do", "approval_required": "asks your approval", "directly_addressed": "addressed you",
              "review_requested": "asks your review", "unmergeable": "can't be merged", "merge_train_removed":
              "left the merge train", "member_access_requested": "asks for access", "review_submitted": "reviewed"}


def parse_todos(items):
    out = []
    for t in items or []:
        tgt = t.get("target") or {}
        out.append({"id": t.get("id"), "action": t.get("action_name") or "",
                    "words": TODO_WORDS.get(t.get("action_name"), (t.get("action_name") or "").replace("_", " ")),
                    "title": tgt.get("title") or t.get("body") or "?", "kind": t.get("target_type") or "",
                    "ref": ("!" if t.get("target_type") == "MergeRequest" else "#") + str(tgt.get("iid", "")),
                    "project": (t.get("project") or {}).get("path_with_namespace") or "?",
                    "author": (t.get("author") or {}).get("username"), "at": K.iso_time(t.get("created_at")),
                    "url": t.get("target_url") or tgt.get("web_url")})
    return out


def parse_projects(items):
    return [{"id": p.get("id"), "path": p.get("path_with_namespace") or p.get("name") or "?", "name": p.get("name"),
             "url": p.get("web_url"), "stars": p.get("star_count") or 0,
             "active": K.iso_time(p.get("last_activity_at"))} for p in items or [] if not p.get("archived")]


def parse_pipelines(items):
    return [{"id": p.get("id"), "status": p.get("status") or "?", "ref": p.get("ref") or "", "url": p.get("web_url"),
             "updated": K.iso_time(p.get("updated_at") or p.get("created_at")), "source": p.get("source") or ""}
            for p in items or []]


def merge_feeds(feeds):
    """One feed from several accounts' [(label, data)]: merge requests, to-dos and projects
    merged and sorted as for one account, each row tagged with its account's label ("acct")
    and the account's web root ("base"). A project's id becomes "<label>/<id>", so two
    servers' projects never share pipelines."""
    if not feeds:
        return None
    if len(feeds) == 1:
        lab, d = feeds[0]
        return dict(d, accounts=[{"label": lab, "login": d.get("login"), "base": d.get("base")}])
    out = {"mrs": [], "todos": [], "projects": [], "pipelines": {}, "at": 0,
           "accounts": [{"label": lab, "login": d.get("login"), "base": d.get("base")} for lab, d in feeds],
           "login": feeds[0][1].get("login"), "base": feeds[0][1].get("base")}
    for lab, d in feeds:
        tag = {"acct": lab, "acct_base": d.get("base")}
        out["mrs"] += [dict(m, **tag) for m in d.get("mrs") or []]
        out["todos"] += [dict(t, **tag) for t in d.get("todos") or []]
        for pr in d.get("projects") or []:
            key = f"{lab}/{pr['id']}"
            out["projects"].append(dict(pr, id=key, **tag))
            out["pipelines"][key] = (d.get("pipelines") or {}).get(pr["id"]) or []
        out["at"] = max(out["at"], d.get("at") or 0)
    out["mrs"].sort(key=lambda m: -(m["updated"] or 0))
    out["todos"].sort(key=lambda t: -(t["at"] or 0))
    out["projects"].sort(key=lambda pr: -(pr["active"] or 0))
    return out


def status_of(s):
    return STATUS.get(s, ("static", (s or "?").replace("_", " ")))


# ------------------------------------------------------------------ demo readings
def demo_data(now=None):
    now = now or time.time()
    m, h, d = 60, 3600, 86400
    mrs = [{"iid": i, "title": t, "url": f"https://gitlab.example.org/{p}/-/merge_requests/{i}", "project": p,
            "author": a, "updated": now - ago, "draft": dr, "why": why, "conflicts": c, "pipeline": pl}
           for i, t, p, a, ago, dr, why, c, pl in (
               (318, "Retry the uplink with backoff", "harbor/relay-firmware", "tobias", 25 * m, False, "review", False,
                "success"),
               (77, "Lantern: a dimmer night mode", "harbor/lantern", "mara", 3 * h, False, "review", False, "running"),
               (54, "Move the tide tables to the new API", "harbor/tides", "ana", 9 * h, False, "assigned", True,
                "failed"),
               (55, "Draft: tide alarms", "harbor/tides", "you", 2 * d, True, "assigned", False, "manual"))]
    todos = [{"id": i, "action": a, "words": TODO_WORDS.get(a, a), "title": t, "kind": k, "ref": r, "project": p,
              "author": au, "at": now - ago, "url": f"https://gitlab.example.org/{p}"}
             for i, a, t, k, r, p, au, ago in (
                 (1, "review_requested", "Retry the uplink with backoff", "MergeRequest", "!318",
                  "harbor/relay-firmware", "tobias", 25 * m),
                 (2, "mentioned", "Flaky test on the tide parser", "Issue", "#203", "harbor/tides", "ana", 2 * h),
                 (3, "build_failed", "Move the tide tables to the new API", "MergeRequest", "!54", "harbor/tides",
                  "ana", 9 * h),
                 (4, "assigned", "Night mode washes out the map", "Issue", "#41", "harbor/lantern", "mara", 30 * h))]
    seq = {"harbor/relay-firmware": "SSSSFSSSSSSSFSSSSSRS", "harbor/tides": "SSSFSSFSSSSFFSFSSSSF",
           "harbor/lantern": "SSSSSSSSSSSSSSSSSSSR", "harbor/charts": "SSSSSSFSSSSSCSSSSSSS",
           "you/dotfiles": "SSSSSSSSS", "harbor/buoys": "SSSFSSSSSSSSSSSS", "harbor/almanac": "SSSSSSSCSS"}
    code = {"S": "success", "F": "failed", "R": "running", "C": "canceled"}
    projects, pipes = [], {}
    for k, (path, s) in enumerate(seq.items()):
        pid = 100 + k
        projects.append({"id": pid, "path": path, "name": path.split("/")[-1], "url": f"https://gitlab.example.org/{path}",
                         "stars": (41, 12, 7, 3, 0, 5, 2)[k], "active": now - (k + 1) * 2 * h})
        pipes[pid] = [{"id": 9000 + k * 20 + j, "status": code[c], "ref": "main" if j % 3 else "feature",
                       "url": f"https://gitlab.example.org/{path}/-/pipelines/{9000 + j}",
                       "updated": now - (k + 1) * 23 * m - j * 5 * h,
                       "source": "push"} for j, c in enumerate(reversed(s))]
    return {"login": "you", "mrs": mrs, "todos": todos, "projects": projects, "pipelines": pipes, "at": now,
            "base": "https://gitlab.example.org"}


def demo_two(now=None):
    """Demo readings for two accounts: gitlab.com, and a company's own GitLab ("work")."""
    now = now or time.time()
    m, h = 60, 3600
    work = demo_data(now)
    work["login"] = "you"
    pub = {"login": "you", "base": "https://gitlab.com", "at": now,
           "mrs": [{"iid": 12, "title": "Docs: a plainer install guide", "url": "https://gitlab.com/lantern-oss/lantern/"
                    "-/merge_requests/12", "project": "lantern-oss/lantern", "author": "kit", "updated": now - 70 * m,
                    "draft": False, "why": "review", "conflicts": False, "pipeline": "success"}],
           "todos": [{"id": 9, "action": "mentioned", "words": TODO_WORDS["mentioned"], "title": "Packaging for Arch",
                      "kind": "Issue", "ref": "#88", "project": "lantern-oss/lantern", "author": "rue", "at": now - 5 * h,
                      "url": "https://gitlab.com/lantern-oss/lantern/-/issues/88"}],
           "projects": [{"id": 7, "path": "lantern-oss/lantern", "name": "lantern", "url": "https://gitlab.com/"
                         "lantern-oss/lantern", "stars": 210, "active": now - 3 * h}],
           "pipelines": {7: [{"id": 500 + j, "status": "failed" if j == 4 else "success", "ref": "main",
                              "url": "https://gitlab.com/lantern-oss/lantern/-/pipelines/" + str(500 + j),
                              "updated": now - 3 * h - j * 6 * h, "source": "push"} for j in range(12)]}}
    return merge_feeds([("gitlab.com", pub), ("work", work)])


# ------------------------------------------------------------------ the panel
class GitLabPanel(K.KitPanel):
    name, title = "gitlab", "GITLAB"
    description = "Your GitLab feed: merge requests waiting on you, your to-dos, and your projects' pipelines"
    category, reads = "notes", "GitLab (gitlab.com or your own), through a sign-in or a token"
    width, height = 460, 320
    interval = 30.0
    sizes = {
        "compact": ((240, 110), (420, 180), (300, 130)),
        "standard": ((380, 240), (620, 470), (460, 320)),
        "wide": ((680, 220), (1400, 460), (900, 300)),
        "tall": ((360, 480), (600, 1100), (440, 680)),
        "large": ((720, 480), (1400, 1100), (960, 640)),
    }
    default_size = "standard"
    settings = [
        {"key": "account", "label": "GitLab account", "kind": "secret-signin", "provider": "gitlab",
         "hint": "The device flow (GitLab 17.2+), or a personal access token: bromigos account set-token gitlab"},
        {"key": "projects", "label": "Projects with pipelines", "kind": "number", "default": 5,
         "hint": "How many of your most recently active projects"},
    ]

    def __init__(self, cfg=None, wake=None):
        super().__init__(cfg, wake)
        if K.demo():
            self.accts, self.demo = None, demo_data()          # demo_two(): two accounts, for pictures
            return
        self.demo = None
        self.accts = K.Accounts(self, "gitlab", [("poll", self.fetch, EVERY, EVERY)])

    def base(self):
        if self.demo:
            return self.demo["base"]
        shown = self.accts.signed_in() or self.accts.shown()
        return shown[0].base()

    def feed(self):
        """The data to draw: the demo's, or every shown account's, merged."""
        if self.demo:
            return self.demo
        return merge_feeds([(a.label(), d) for a, d in self.accts.data()])

    def error(self):
        return None if self.demo else self.accts.error_words()

    def fetch(self, acct):
        if not acct.status().get("signed_in"):
            return None
        api = Client(acct.base, acct.token)
        me = api.get("/user")
        user = me.get("username")
        assigned = parse_mrs(api.get("/merge_requests", scope="assigned_to_me", state="opened", per_page=30), "assigned")
        review = parse_mrs(api.get("/merge_requests", scope="all", reviewer_username=user, state="opened",
                                   per_page=30), "review")
        todos = parse_todos(api.get("/todos", state="pending", per_page=30))
        n = int(self.conf.get("projects", 5) or 5) + (3 if self.last_class == "large" else 0)
        projects = parse_projects(api.get("/projects", membership="true", order_by="last_activity_at", per_page=n,
                                          simple="true"))
        pipes = {}
        want = 20 if self.last_class == "large" else 10 if self.last_class in ("wide", "tall") else 1
        for p in projects:
            try:
                pipes[p["id"]] = parse_pipelines(api.get(f"/projects/{p['id']}/pipelines", per_page=want))
            except urllib.error.HTTPError:
                pipes[p["id"]] = []
        return {"login": user, "mrs": merge_mrs(review, assigned), "todos": todos, "projects": projects,
                "pipelines": pipes, "at": time.time(), "base": acct.base()}

    # ---- drawing
    def many(self):
        d = self.demo
        return len(d.get("accounts") or []) > 1 if d else self.accts.many()

    def draw(self, cr, w, h):
        cls = self.size_class(w, h)
        d = self.feed()
        host = urllib.parse.urlparse(self.base()).hostname or "gitlab"
        if d and len(d.get("accounts") or []) > 1:
            labs = [a["label"] for a in d["accounts"]]
            right = f"{len(labs)} ACCOUNTS" if cls == "compact" else " + ".join(labs)
            where = " and ".join(f"{a['label']} (@{a['login'] or '?'} on "
                                 f"{urllib.parse.urlparse(a['base'] or '').hostname or '?'})" for a in d["accounts"])
        else:
            right = (f"@{d['login']}" if d and d.get("login") else host) if cls == "compact" else \
                (f"@{d['login']} · {host}" if d and d.get("login") else host)
            where = host
        top = D.frame(cr, w, h, self.title, right)
        self.region(0, 0, w, 34, f"Your GitLab feed on {where}: merge requests waiting on you, your to-dos and your "
                    "projects' pipelines, read every 4 minutes while seen. Click a row to open it.",
                    lambda: K.open_url(self.base() + "/dashboard/todos"))
        if not self.demo and not self.accts.signed_in():
            self.accts.first().draw_signin(cr, w, h, top, "The GitLab panel reads your merge requests, to-dos and "
                                           "pipelines")
            return
        err = self.error()
        if d is None:
            D.label(cr, 16, top + 6, "NO ANSWER" if err else "READING…", "amber" if err else "static")
            if err:
                D.text(cr, 16, top + 26, err, 11, "soft", "regular", width=w - 32, wrap=True)
            self.region(0, top, w, h - top, err or f"Reading {host} for the first time")
            return
        if err:
            D.label(cr, w - 16, h - 18, "STALE", "amber", size=10, align="right")
            self.region(w - 80, h - 20, 64, 16, f"The last read failed ({err}); showing the one before")
        x0, x1 = 16, w - 16
        if cls == "compact":
            self._counts(cr, d, x0, x1, top, h)
        elif cls == "wide":
            cw = (x1 - x0 - 32) / 3
            self._list(cr, "MERGE REQUESTS", d["mrs"], x0, x0 + cw, top, h - 12, self._mr_row)
            self._list(cr, "TO-DO", d["todos"], x0 + cw + 16, x0 + 2 * cw + 16, top, h - 12, self._todo_row)
            self._pipes(cr, d, x0 + 2 * cw + 32, x1, top, h - 12, strip=True)
        elif cls == "tall":
            y = self._list(cr, "MERGE REQUESTS", d["mrs"], x0, x1, top, top + (h - top) * 0.36, self._mr_row)
            y = self._list(cr, "TO-DO", d["todos"], x0, x1, y + 6, y + 6 + (h - top) * 0.32, self._todo_row)
            self._pipes(cr, d, x0, x1, y + 6, h - 12, strip=True)
        elif cls == "large":
            mid = x0 + (x1 - x0) * 0.5
            split = top + (h - top) * 0.55
            ya = self._list(cr, "MERGE REQUESTS", d["mrs"], x0, mid - 10, top, split, self._mr_row)
            yb = self._list(cr, "TO-DO", d["todos"], mid + 10, x1, top, split, self._todo_row)
            self._pipes(cr, d, x0, x1, max(ya, yb) + 12, h - 12, strip=True, big=True)
        else:
            y = self._list(cr, "MERGE REQUESTS", d["mrs"], x0, x1, top, top + (h - top) * 0.5, self._mr_row)
            self._list(cr, "TO-DO", d["todos"], x0, x1, y + 6, h - 12, self._todo_row)

    def _counts(self, cr, d, x0, x1, top, h):
        failed = [p for p in d["projects"] if (d["pipelines"].get(p["id"]) or [{}])[0].get("status") == "failed"]
        review = [m for m in d["mrs"] if m["why"] == "review"]
        cells = [("REVIEWS", len(review), "amber" if review else "static",
                  f"{len(review)} merge request(s) asking for your review", "/dashboard/merge_requests?reviewer_username="
                  + (d.get("login") or "")),
                 ("TO-DO", len(d["todos"]), "phosphor" if d["todos"] else "static", f"{len(d['todos'])} pending to-do(s)",
                  "/dashboard/todos"),
                 ("FAILED", len(failed), "danger" if failed else "static",
                  f"{len(failed)} of your recent projects' latest pipelines failed"
                  + (": " + ", ".join(p["path"] for p in failed) if failed else ""), "/dashboard/projects")]
        cw = (x1 - x0) / 3
        sz = max(22, min(40, h - top - 40))
        for i, (lbl, n, col, tip, path) in enumerate(cells):
            cx = x0 + i * cw
            D.seg7(cr, cx, top + 2, sz, f"{n:d}"[-3:], col, glow=n > 0)
            D.label(cr, cx, top + sz + 10, lbl, "dim", size=10)
            self.region(cx, top, cw - 4, sz + 26, tip + ". Click to open it.",
                        lambda u=self.base() + path: K.open_url(u))

    def _list(self, cr, title, items, x0, x1, top, bottom, row_fn):
        D.label(cr, x0, top, f"{title} · {len(items)}", "phosphor" if items else "dim", size=10)
        lw = D.layout(cr, f"{title} · {len(items)}".upper(), 10, "semibold", 0.18).get_pixel_size()[0]
        D.rule(cr, x0 + lw + 10, top + 7, x1, "dim", 0.3)
        y = top + 18
        rowh = 34 if (x1 - x0) < 520 else 22
        if not items:
            D.text(cr, x0, y, "Nothing here.", 11, "static", "regular")
            self.region(x0, top, x1 - x0, 34, f"{title.capitalize()}: nothing waiting")
            return y + 20
        room = max(1, int((bottom - y) // rowh))
        for it in items[:room]:
            row_fn(cr, it, x0, x1, y, rowh)
            y += rowh
        if len(items) > room:
            D.label(cr, x1, y - 2, f"+{len(items) - room} MORE", "static", size=10, align="right")
            self.region(x1 - 90, y - 4, 90, 14, f"{len(items) - room} more; make the panel bigger to see them")
            y += 12
        return y

    def _mr_row(self, cr, m, x0, x1, y, rowh):
        col, word = status_of(m["pipeline"]) if m["pipeline"] else ("static", "no pipeline")
        D.src(cr, col, 0.9)
        cr.rectangle(x0, y + 3, 3, rowh - 8)
        cr.fill()
        tag = "REVIEW" if m["why"] == "review" else "YOURS" if m["author"] == "you" else "ASSIGNED"
        tw = self.chip(cr, x0 + 8, y + 2, tag, "amber" if m["why"] == "review" else "soft")
        two = rowh > 24
        D.text(cr, x0 + 14 + tw, y + 1, m["title"], 11, "static" if m["draft"] else "soft", "medium",
               width=x1 - x0 - 14 - tw - (0 if two else 210))
        acct = f"{m['acct']} · " if m.get("acct") else ""
        meta = f"{acct}{m['project']}!{m['iid']} · {m['author'] or '?'} · {K.ago(m['updated'])}" + \
            (" · CONFLICTS" if m["conflicts"] else "")
        if two:
            D.text(cr, x0 + 14 + tw, y + 16, meta, 10, "danger" if m["conflicts"] else "static", "regular",
                   width=x1 - x0 - 14 - tw)
        else:
            D.text(cr, x1, y + 2, meta, 10, "static", "regular", align="right", width=206)
        self.region(x0, y, x1 - x0, rowh - 2, f"{m['title']}: merge request {m['project']}!{m['iid']}"
                    + (f" on {m['acct']}" if m.get("acct") else "") + " by "
                    f"{m['author'] or '?'}, {'your review is asked' if m['why'] == 'review' else 'assigned to you'}, "
                    f"updated {K.ago(m['updated'])} ago; pipeline {word}"
                    + (", a draft" if m["draft"] else "") + (", has merge conflicts" if m["conflicts"] else "")
                    + ". Click to open it.", lambda u=m["url"]: K.open_url(u))

    def _todo_row(self, cr, t, x0, x1, y, rowh):
        col = "danger" if t["action"] == "build_failed" else "amber" if t["action"] in (
            "review_requested", "approval_required") else "phosphor"
        D.dot(cr, x0 + 4, y + 8, 3, col, glow=False)
        two = rowh > 24
        D.text(cr, x0 + 14, y + 1, t["title"], 11, "soft", "medium", width=x1 - x0 - 14 - (0 if two else 210))
        meta = (f"{t['acct']} · " if t.get("acct") else "") + \
            f"{t['author'] or '?'} {t['words']} · {t['project'].split('/')[-1]}{t['ref']} · {K.ago(t['at'])}"
        if two:
            D.text(cr, x0 + 14, y + 16, meta, 10, "static", "regular", width=x1 - x0 - 14)
        else:
            D.text(cr, x1, y + 2, meta, 10, "static", "regular", align="right", width=206)
        self.region(x0, y, x1 - x0, rowh - 2, f"To-do: {t['author'] or 'someone'} {t['words']} on {t['title']} "
                    f"({t['project']}{t['ref']}" + (f" on {t['acct']}" if t.get("acct") else "") +
                    f"), {K.ago(t['at'])} ago. Click to open it.",
                    lambda u=t["url"]: K.open_url(u))

    def _pipes(self, cr, d, x0, x1, top, bottom, strip=False, big=False):
        projects = d["projects"][:int(self.conf.get("projects", 5) or 5) + (3 if big else 0)]
        D.label(cr, x0, top, f"PIPELINES · {len(projects)} PROJECTS", "phosphor" if projects else "dim", size=10)
        y = top + 18
        if not projects:
            D.text(cr, x0, y, "No projects yet.", 11, "static", "regular")
            self.region(x0, top, x1 - x0, 34, "None of your projects has been active")
            return
        rowh = 30 if big else 22
        if big and projects:
            rowh = max(24, min(48, (bottom - y) // len(projects)))
        name_w = min(220, (x1 - x0) * (0.4 if strip else 0.6))
        for p in projects[:max(1, int((bottom - y) // rowh))]:
            pl = (d["pipelines"].get(p["id"]) or [])[:20 if big else 10]
            last = pl[0] if pl else None
            col, word = status_of(last["status"]) if last else ("static", "no pipelines")
            D.dot(cr, x0 + 4, y + rowh / 2 - 2, 4 if big else 3, col,
                  glow=bool(last) and last["status"] == "running" and K.motion() == "full")
            nm = p["path"].split("/")[-1]
            if p.get("acct"):
                tw = D.text(cr, x0 + 14, y + (rowh - 14) / 2, p["acct"], 9, "static", "semibold",
                            width=name_w * 0.4)[0]
                D.text(cr, x0 + 20 + tw, y + (rowh - 16) / 2, nm, 11, "soft", "medium", width=name_w - 20 - tw)
            else:
                D.text(cr, x0 + 14, y + (rowh - 16) / 2, nm, 11, "soft", "medium", width=name_w - 14)
            self.region(x0, y, name_w, rowh - 2, f"{p['path']}" + (f" on {p['acct']}" if p.get("acct") else "")
                        + f": latest pipeline {word}"
                        + (f" on {last['ref']}, {K.ago(last['updated'])} ago" if last else "")
                        + f"; {p['stars']} stars; active {K.ago(p['active'])} ago. Click to open its pipelines.",
                        lambda u=(p["url"] or "") + "/-/pipelines": K.open_url(u))
            if strip and pl:
                sx = x0 + name_w + 6
                n = len(pl)
                sw = min(40 if big else 16, (x1 - sx - 60) / max(1, n))
                for i, q in enumerate(reversed(pl)):                     # oldest at the left
                    c, wd = status_of(q["status"])
                    D.src(cr, c, 0.9 if q is last else 0.6)
                    cr.rectangle(sx + i * sw, y + 4, sw - 3, rowh - 10)
                    cr.fill()
                    self.region(sx + i * sw, y + 4, sw - 3, rowh - 10, f"{p['path']} pipeline #{q['id']} on {q['ref']}: "
                                f"{wd}, {K.ago(q['updated'])} ago ({q['source'] or 'unknown'}). Click to open it.",
                                lambda u=q["url"]: K.open_url(u))
            D.text(cr, x1, y + (rowh - 14) / 2, word if not strip else K.ago(last["updated"]) if last else "-", 10,
                   col if not strip else "static", "regular", align="right")
            y += rowh


PANEL = GitLabPanel
LAYOUT = {"visible": False}
