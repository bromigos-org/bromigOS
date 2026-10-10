"""GITHUB: your personal feed. Notifications, the pull requests and issues waiting on you
(a review asked of you, or assigned to you), your repositories with their stars and what
happened on them lately, and, when large, your contribution graph.

This is the personal feed. The build-status board, CI runs and pull requests for the
repositories you list, is the CI & PRs panel (ci.py).

Sign-in: your `gh` login when you have one (its token is read when needed, never stored),
else GitHub's device flow through lib/bromigos_account.py, with the token in your keyring.
It reads every 4 minutes while the panel is seen, with conditional requests, so an
unchanged answer costs nothing against GitHub's rate limit. The contribution graph is read
hourly, and only while the panel is large.

Several accounts: github.com and a GitHub Enterprise Server, or two github.com accounts.
The `account` setting lists which to show (every signed-in one when empty). Their rows
are merged, newest first, each tagged with its account's label, and the contribution
graphs are added up. Each account is read on its own, with its own rate limit.
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

API = "https://api.github.com"
EVERY = 240
GRAPH_EVERY = 3600

CONTRIB_QUERY = ("query{viewer{login contributionsCollection{contributionCalendar{totalContributions "
                 "weeks{contributionDays{date contributionCount weekday}}}}}}")


# ------------------------------------------------------------------ the API, with ETags
class Client:
    """GET with If-None-Match: a 304 answer gives back the last copy (and costs no rate limit)."""

    def __init__(self, token_fn, api_fn=None):
        self.token_fn = token_fn
        self.api_fn = api_fn or (lambda: API)           # GitHub Enterprise Server: <base>/api/v3
        self.cache = {}                                   # url -> (etag, data)
        self.remaining = None

    def _headers(self):
        tok = self.token_fn()
        if not tok:
            raise PermissionError("not signed in")
        return {"Authorization": f"Bearer {tok}", "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28", "User-Agent": "bromigOS"}

    def get(self, path, **params):
        url = self.api_fn().rstrip("/") + path + ("?" + urllib.parse.urlencode(params) if params else "")
        h = self._headers()
        hit = self.cache.get(url)
        if hit and hit[0]:
            h["If-None-Match"] = hit[0]
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=h), timeout=15) as r:
                data = json.loads(r.read() or b"null")
                self.remaining = r.headers.get("X-RateLimit-Remaining", self.remaining)
                self.cache[url] = (r.headers.get("ETag"), data)
                return data
        except urllib.error.HTTPError as e:
            if e.code == 304 and hit:
                return hit[1]
            if e.code == 401:
                raise PermissionError("GitHub refused the token (401): sign in again") from e
            raise

    def graphql(self, query):
        h = dict(self._headers(), **{"Content-Type": "application/json"})
        root = self.api_fn().rstrip("/")
        url = root.removesuffix("/v3") + "/graphql" if root.endswith("/api/v3") else root + "/graphql"
        req = urllib.request.Request(url, data=json.dumps({"query": query}).encode(), headers=h)
        with urllib.request.urlopen(req, timeout=20) as r:
            d = json.loads(r.read())
        if d.get("errors"):
            raise ValueError(d["errors"][0].get("message", "GraphQL error"))
        return d["data"]


# ------------------------------------------------------------------ parsing
def web_of(api):
    """The web root for an API root: api.github.com -> github.com; <base>/api/v3 -> <base>."""
    api = (api or API).rstrip("/")
    return "https://github.com" if api == API else api.removesuffix("/api/v3")


def html_url(api_url, kind=None, api=API):
    """An API address as the page to open: repos/o/r/pulls/5 -> github.com/o/r/pull/5."""
    if not api_url:
        return None
    u = api_url.replace(api.rstrip("/") + "/repos/", web_of(api) + "/")
    u = u.replace("/pulls/", "/pull/").replace("/commits/", "/commit/")
    if "/releases/" in u and kind == "Release":
        u = u.rsplit("/releases/", 1)[0] + "/releases"
    return u


REASONS = {"review_requested": "review asked", "mention": "mentioned", "team_mention": "team mentioned",
           "assign": "assigned", "author": "yours", "comment": "commented", "subscribed": "watching",
           "state_change": "state changed", "ci_activity": "CI", "security_alert": "security",
           "manual": "subscribed", "invitation": "invitation", "approval_requested": "approval asked"}


def parse_notifications(items, api=API):
    out = []
    for n in items or []:
        s = n.get("subject") or {}
        out.append({"id": n.get("id"), "title": s.get("title") or "?", "type": s.get("type") or "",
                    "repo": (n.get("repository") or {}).get("full_name") or "?", "reason": n.get("reason") or "",
                    "why": REASONS.get(n.get("reason"), (n.get("reason") or "").replace("_", " ")),
                    "unread": bool(n.get("unread")), "updated": K.iso_time(n.get("updated_at")),
                    "url": html_url(s.get("url"), s.get("type"), api) or (n.get("repository") or {}).get("html_url")})
    return out


def parse_search(d, api=API):
    out = []
    for it in (d or {}).get("items") or []:
        repo = (it.get("repository_url") or "").replace(api.rstrip("/") + "/repos/", "")
        out.append({"repo": repo, "number": it.get("number"), "title": it.get("title") or "?",
                    "url": it.get("html_url"), "author": (it.get("user") or {}).get("login"),
                    "updated": K.iso_time(it.get("updated_at")), "draft": bool(it.get("draft")),
                    "pr": "pull_request" in it and it.get("pull_request") is not None,
                    "comments": it.get("comments") or 0})
    return out


def parse_repos(items):
    return [{"name": r.get("name"), "full": r.get("full_name"), "stars": r.get("stargazers_count") or 0,
             "forks": r.get("forks_count") or 0, "issues": r.get("open_issues_count") or 0,
             "pushed": K.iso_time(r.get("pushed_at")), "language": r.get("language") or "",
             "private": bool(r.get("private")), "url": r.get("html_url"), "description": r.get("description") or ""}
            for r in items or [] if not r.get("archived")]


def event_words(e):
    """What an event says, in a few words: 'starred', 'pushed 3 commits to main'."""
    t = e.get("type") or ""
    p = e.get("payload") or {}
    if t == "WatchEvent":
        return "starred it"
    if t == "ForkEvent":
        return "forked it"
    if t == "PushEvent":
        n = p.get("size") or len(p.get("commits") or []) or 1
        ref = (p.get("ref") or "").replace("refs/heads/", "")
        return f"pushed {n} commit{'s' if n != 1 else ''}" + (f" to {ref}" if ref else "")
    if t in ("IssuesEvent", "PullRequestEvent"):
        obj = p.get("issue") or p.get("pull_request") or {}
        what = "issue" if t == "IssuesEvent" else "PR"
        act = p.get("action") or "updated"
        if act == "closed" and obj.get("merged"):
            act = "merged"
        return f"{act} {what} #{obj.get('number', '?')}"
    if t == "IssueCommentEvent":
        return f"commented on #{(p.get('issue') or {}).get('number', '?')}"
    if t == "PullRequestReviewEvent":
        return f"reviewed PR #{(p.get('pull_request') or {}).get('number', '?')}"
    if t == "CreateEvent":
        return f"created {p.get('ref_type', 'a ref')}" + (f" {p['ref']}" if p.get("ref") else "")
    if t == "ReleaseEvent":
        return f"released {(p.get('release') or {}).get('tag_name', '')}".strip()
    if t == "DeleteEvent":
        return f"deleted {p.get('ref_type', '')} {p.get('ref', '')}".strip()
    return t.replace("Event", "").lower() or "did something"


def parse_events(items, me=None):
    out = []
    for e in items or []:
        actor = (e.get("actor") or {}).get("login") or "?"
        out.append({"actor": actor, "me": actor == me, "repo": (e.get("repo") or {}).get("name") or "?",
                    "type": e.get("type") or "", "words": event_words(e), "at": K.iso_time(e.get("created_at"))})
    out.sort(key=lambda e: -(e["at"] or 0))
    return out


def merge_contrib(graphs):
    """Several accounts' contribution graphs as one: each day's counts added up."""
    graphs = [g for g in graphs if g and g.get("weeks")]
    if len(graphs) < 2:
        return graphs[0] if graphs else None
    per = {}
    for g in graphs:
        for wk in g["weeks"]:
            for date, n in wk:
                per[date] = per.get(date, 0) + n
    base = max(graphs, key=lambda g: sum(len(w) for w in g["weeks"]))
    return {"total": sum(g.get("total") or 0 for g in graphs),
            "weeks": [[(date, per.get(date, 0)) for date, _ in wk] for wk in base["weeks"]]}


LISTS = (("notifications", "updated"), ("reviews", "updated"), ("assigned", "updated"), ("mine", "updated"),
         ("repos", "pushed"), ("events", "at"))


def merge_feeds(feeds):
    """One feed from several accounts' [(label, data)]: each list merged and sorted as for
    one account, newest first, every row tagged with its account's label ("acct")."""
    if not feeds:
        return None
    accts = [{"label": lab, "login": d.get("login"), "web": d.get("web") or "https://github.com"} for lab, d in feeds]
    if len(feeds) == 1:
        return dict(feeds[0][1], accounts=accts)
    out = {"login": feeds[0][1].get("login"), "web": feeds[0][1].get("web"), "accounts": accts,
           "at": max(d.get("at") or 0 for _, d in feeds), "contrib": merge_contrib([d.get("contrib") for _, d in feeds])}
    for key, when in LISTS:
        rows = [dict(r, acct=lab) for lab, d in feeds for r in d.get(key) or []]
        rows.sort(key=lambda r: -(r.get(when) or 0))
        out[key] = rows
    return out


def parse_contrib(d):
    cal = (((d or {}).get("viewer") or {}).get("contributionsCollection") or {}).get("contributionCalendar") or {}
    weeks = [[(day.get("date"), int(day.get("contributionCount") or 0)) for day in w.get("contributionDays") or []]
             for w in cal.get("weeks") or []]
    return {"total": cal.get("totalContributions") or 0, "weeks": weeks}


# ------------------------------------------------------------------ demo readings
def demo_data(now=None):
    now = now or time.time()
    m, h, d = 60, 3600, 86400
    notes = [("Size classes for the panel kit", "PullRequest", "drift-atlas/atlas", "review_requested", True, 12 * m),
             ("Crash when the relay drops its link", "Issue", "relay-firmware/relay", "mention", True, 2 * h),
             ("v0.4.0", "Release", "beacon-kit/beacon", "subscribed", False, 5 * h),
             ("Theme: a calmer amber", "PullRequest", "my-theme/theme", "author", False, 9 * h),
             ("Docs: the gallery's cards", "PullRequest", "drift-atlas/atlas", "comment", False, 26 * h)]
    notifs = [{"id": str(i), "title": t, "type": ty, "repo": r, "reason": re_, "why": REASONS.get(re_, re_),
               "unread": u, "updated": now - ago, "url": f"https://github.com/{r}"}
              for i, (t, ty, r, re_, u, ago) in enumerate(notes)]
    reviews = [{"repo": "drift-atlas/atlas", "number": 412, "title": "Size classes for the panel kit", "url":
                "https://github.com/drift-atlas/atlas/pull/412", "author": "mara", "updated": now - 12 * m, "draft": False,
                "pr": True, "comments": 4},
               {"repo": "relay-firmware/relay", "number": 88, "title": "Retry the uplink with backoff", "url":
                "https://github.com/relay-firmware/relay/pull/88", "author": "tobias", "updated": now - 3 * h,
                "draft": False, "pr": True, "comments": 1}]
    assigned = [{"repo": "relay-firmware/relay", "number": 91, "title": "Crash when the relay drops its link", "url":
                 "https://github.com/relay-firmware/relay/issues/91", "author": "ana", "updated": now - 2 * h,
                 "draft": False, "pr": False, "comments": 6},
                {"repo": "beacon-kit/beacon", "number": 17, "title": "Battery estimate is off by a day", "url":
                 "https://github.com/beacon-kit/beacon/issues/17", "author": "mara", "updated": now - 2 * d,
                 "draft": False, "pr": False, "comments": 2}]
    mine = [{"repo": "my-theme/theme", "number": 23, "title": "Theme: a calmer amber", "url":
             "https://github.com/my-theme/theme/pull/23", "author": "you", "updated": now - 9 * h, "draft": False,
             "pr": True, "comments": 3}]
    repos = [{"name": n, "full": f"you/{n}", "stars": s, "forks": f, "issues": i, "pushed": now - ago, "language": lang,
              "private": False, "url": f"https://github.com/you/{n}", "description": desc}
             for n, s, f, i, ago, lang, desc in (
                 ("drift-atlas", 1284, 96, 23, 40 * m, "Rust", "Maps for the drift"),
                 ("relay-firmware", 342, 41, 12, 3 * h, "C", "Firmware for the relay masts"),
                 ("my-theme", 87, 9, 2, 9 * h, "CSS", "A theme"),
                 ("beacon-kit", 56, 4, 5, 2 * d, "Python", "Beacons, batteries and backoff"),
                 ("lamplighter-log", 11, 1, 0, 6 * d, "Go", "A log for lamplighters"))]
    events = [{"actor": a, "me": a == "you", "repo": f"you/{r}", "type": t, "words": w, "at": now - ago}
              for a, r, t, w, ago in (("mara", "drift-atlas", "WatchEvent", "starred it", 20 * m),
                                      ("you", "drift-atlas", "PushEvent", "pushed 3 commits to main", 40 * m),
                                      ("tobias", "relay-firmware", "IssuesEvent", "opened issue #91", 2 * h),
                                      ("ana", "drift-atlas", "ForkEvent", "forked it", 4 * h),
                                      ("you", "my-theme", "PullRequestEvent", "opened PR #23", 9 * h),
                                      ("kai", "beacon-kit", "WatchEvent", "starred it", 20 * h))]
    import math
    weeks = []
    t0 = now - 52 * 7 * d
    for wk in range(53):
        days = []
        for wd in range(7):
            t = t0 + (wk * 7 + wd) * d
            if t > now:
                break
            v = max(0, int(6 * (0.5 + 0.5 * math.sin(wk / 4.0 + wd)) * (0.3 if wd in (0, 6) else 1.0)
                           + 4 * max(0.0, math.sin(wk / 9.0)) ** 3))
            days.append((time.strftime("%Y-%m-%d", time.localtime(t)), v))
        weeks.append(days)
    return {"login": "you", "notifications": notifs, "reviews": reviews, "assigned": assigned, "mine": mine,
            "repos": repos, "events": events, "at": now, "web": "https://github.com",
            "contrib": {"total": sum(c for w in weeks for _, c in w), "weeks": weeks}}


# ------------------------------------------------------------------ the panel
class GitHubPanel(K.KitPanel):
    name, title = "github", "GITHUB"
    description = ("Your personal GitHub feed: notifications, reviews and issues waiting on you, your repos' stars "
                   "and activity (CI & PRs is the build board)")
    category, reads = "notes", "GitHub, through your gh login or a sign-in"
    width, height = 460, 320
    interval = 30.0
    sizes = {
        "compact": ((240, 110), (420, 180), (300, 130)),
        "standard": ((380, 240), (620, 470), (460, 320)),
        "wide": ((680, 220), (1400, 460), (900, 300)),
        "tall": ((360, 480), (600, 1100), (440, 680)),
        "large": ((720, 520), (1400, 1100), (960, 680)),
    }
    default_size = "standard"
    settings = [
        {"key": "account", "label": "GitHub account", "kind": "secret-signin", "provider": "github",
         "hint": "Your gh login is used when there is one; otherwise sign in here"},
        {"key": "repos", "label": "Repositories shown", "kind": "number", "default": 6,
         "hint": "How many of your repositories, by latest push"},
        {"key": "activity_repos", "label": "Activity from", "kind": "number", "default": 3,
         "hint": "Read recent activity from this many of your newest-pushed repositories"},
    ]

    def __init__(self, cfg=None, wake=None):
        super().__init__(cfg, wake)
        self.offset = 0
        self.clients = {}                               # account name -> Client (its own ETags and rate limit)
        if K.demo():
            self.accts = None
            self.demo = demo_data()
            return
        self.demo = None
        self.accts = K.Accounts(self, "github", [("poll", self.fetch, EVERY, EVERY),
                                                 ("graph", self.fetch_graph, GRAPH_EVERY, GRAPH_EVERY)])

    def signed_in(self):
        return self.demo is not None or bool(self.accts.signed_in())

    def client(self, acct):
        c = self.clients.get(acct.name)
        if c is None:
            c = self.clients[acct.name] = Client(acct.token, acct.api)
        return c

    def feed(self):
        if self.demo:
            return self.demo
        return merge_feeds([(a.label(), d) for a, d in self.accts.data("poll")])

    def web(self):
        d = self.feed()
        return (d or {}).get("web") or "https://github.com"

    def fetch(self, acct):
        if not acct.status().get("signed_in"):
            return None
        api = self.client(acct)
        root = acct.api()
        me = api.get("/user").get("login")
        out = {"login": me, "at": time.time(), "web": web_of(root)}
        out["notifications"] = parse_notifications(api.get("/notifications", per_page=30), root)
        out["reviews"] = parse_search(api.get("/search/issues", q="is:open is:pr review-requested:@me archived:false",
                                              per_page=20, sort="updated"), root)
        out["assigned"] = parse_search(api.get("/search/issues", q="is:open assignee:@me archived:false",
                                               per_page=20, sort="updated"), root)
        out["mine"] = parse_search(api.get("/search/issues", q="is:open is:pr author:@me archived:false",
                                           per_page=20, sort="updated"), root)
        repos = parse_repos(api.get("/user/repos", sort="pushed", per_page=30, affiliation="owner"))
        out["repos"] = repos
        events = []
        for r in repos[:int(self.conf.get("activity_repos", 3) or 0)]:
            try:
                events += parse_events(api.get(f"/repos/{r['full']}/events", per_page=15), me)
            except urllib.error.HTTPError:
                continue
        events.sort(key=lambda e: -(e["at"] or 0))
        out["events"] = [dict(e, web=out["web"]) for e in events[:30]]
        out["remaining"] = api.remaining
        return out

    def fetch_graph(self, acct):
        pl = self.accts.poller(acct, "graph")
        if self.last_class != "large" or not acct.status().get("signed_in"):
            self._graph_skipped = True
            return pl.data if pl else None
        self._graph_skipped = False
        return parse_contrib(self.client(acct).graphql(CONTRIB_QUERY))

    def graph(self):
        """(the contribution graph, added up over the accounts, or None; an error or None)."""
        if self.demo:
            return self.demo.get("contrib"), None
        return merge_contrib([d for _, d in self.accts.data("graph")]), self.accts.error_words("graph")

    def scroll(self, dy):
        self.offset = max(0, self.offset + int(dy))

    # ---- drawing
    def draw(self, cr, w, h):
        cls = self.size_class(w, h)
        d = self.feed()
        accts = (d or {}).get("accounts") or []
        if len(accts) > 1:
            right = f"{len(accts)} ACCOUNTS" if cls == "compact" else " + ".join(a["label"] for a in accts)
            whose = " Accounts: " + ", ".join(f"{a['label']} (@{a['login'] or '?'})" for a in accts) + "."
        else:
            right = f"@{d['login']}" if d and d.get("login") else None
            whose = ""
        top = D.frame(cr, w, h, self.title, right)
        self.region(0, 0, w, 34, "Your personal GitHub feed: notifications, what waits on you, your repositories. "
                    "Read every 4 minutes while seen (unchanged answers cost nothing). Click a row to open it. "
                    "CI & PRs is the build board for the repositories you list." + whose,
                    lambda: K.open_url(self.web() + "/notifications"))
        if not self.signed_in():
            self.accts.first().draw_signin(cr, w, h, top, "The GitHub panel reads your notifications, reviews and "
                                           "repositories")
            return
        err = None if self.demo else self.accts.error_words("poll")
        if d is None:
            D.label(cr, 16, top + 6, "NO ANSWER" if err else "READING…", "amber" if err else "static")
            if err:
                D.text(cr, 16, top + 26, err, 11, "soft", "regular", width=w - 32, wrap=True)
            self.region(0, top, w, h - top, err or "Reading GitHub for the first time")
            return
        if err:
            D.label(cr, w - 16, h - 18, "STALE", "amber", size=10, align="right")
            self.region(w - 80, h - 20, 64, 16, f"The last read failed ({err}); showing the one before, "
                        f"from {K.ago(d.get('at'))} ago")
        x0, x1 = 16, w - 16
        waiting = d["reviews"] + [a for a in d["assigned"] if a["url"] not in {r["url"] for r in d["reviews"]}]
        unread = [n for n in d["notifications"] if n["unread"]]
        if cls == "compact":
            self._counts(cr, d, waiting, unread, x0, x1, top, h)
        elif cls == "wide":
            cw = (x1 - x0 - 2 * 16) / 3
            self._list(cr, "WAITING ON YOU", waiting, x0, x0 + cw, top, h - 12, self._item_row)
            self._list(cr, "NOTIFICATIONS", d["notifications"], x0 + cw + 16, x0 + 2 * cw + 16, top, h - 12,
                       self._note_row)
            self._repos(cr, d, x0 + 2 * cw + 32, x1, top, h - 12)
        elif cls == "tall":
            y = self._list(cr, "WAITING ON YOU", waiting, x0, x1, top, top + (h - top) * 0.3, self._item_row)
            y = self._list(cr, "NOTIFICATIONS", d["notifications"], x0, x1, y + 6, y + 6 + (h - top) * 0.28,
                           self._note_row)
            y = self._repos(cr, d, x0, x1, y + 6, y + 6 + (h - y) * 0.45)
            self._events(cr, d, x0, x1, y + 6, h - 12)
        elif cls == "large":
            cell = max(8.0, min(22.0, (x1 - x0) / 53, (h - top) * 0.33 / 7))
            gh = 7 * cell + 40
            mid = x0 + (x1 - x0) * 0.52
            body_bottom = h - 12 - gh - 10
            y = self._list(cr, "WAITING ON YOU", waiting, x0, mid - 10, top, top + (body_bottom - top) * 0.42,
                           self._item_row)
            y = self._list(cr, "YOUR OPEN PRS", d.get("mine") or [], x0, mid - 10, y + 6,
                           y + 6 + (body_bottom - y) * 0.35, self._item_row)
            self._list(cr, "NOTIFICATIONS", d["notifications"], x0, mid - 10, y + 6, body_bottom, self._note_row)
            ry = self._repos(cr, d, mid + 10, x1, top, top + (body_bottom - top) * 0.5)
            self._events(cr, d, mid + 10, x1, ry + 6, body_bottom)
            self._graph(cr, d, x0, x1, h - 12 - gh, h - 12)
        else:
            y = self._list(cr, "WAITING ON YOU", waiting, x0, x1, top, top + (h - top) * 0.5, self._item_row)
            self._list(cr, "NOTIFICATIONS", d["notifications"], x0, x1, y + 6, h - 12, self._note_row)

    def _counts(self, cr, d, waiting, unread, x0, x1, top, h):
        cells = [("REVIEWS", len(d["reviews"]), "amber" if d["reviews"] else "static",
                  f"{len(d['reviews'])} pull request(s) waiting for your review", self.web() + "/pulls/review-requested"),
                 ("ASSIGNED", len(d["assigned"]), "soft", f"{len(d['assigned'])} open issue(s) or PR(s) assigned to you",
                  self.web() + "/issues/assigned"),
                 ("UNREAD", len(unread), "phosphor" if unread else "static", f"{len(unread)} unread notification(s)",
                  self.web() + "/notifications")]
        cw = (x1 - x0) / 3
        sz = max(22, min(40, h - top - 40))
        for i, (lbl, n, col, tip, url) in enumerate(cells):
            cx = x0 + i * cw
            D.seg7(cr, cx, top + 2, sz, f"{n:d}"[-3:], col, glow=n > 0)
            D.label(cr, cx, top + sz + 10, lbl, "dim", size=10)
            self.region(cx, top, cw - 4, sz + 26, tip + ". Click to open it on GitHub.", lambda u=url: K.open_url(u))

    def _list(self, cr, title, items, x0, x1, top, bottom, row_fn):
        """A titled list that fits the box; returns the y below it."""
        D.label(cr, x0, top, f"{title} · {len(items)}", "phosphor" if items else "dim", size=10)
        lw = D.layout(cr, f"{title} · {len(items)}".upper(), 10, "semibold", 0.18).get_pixel_size()[0]
        D.rule(cr, x0 + lw + 10, top + 7, x1, "dim", 0.3)
        y = top + 18
        rowh = 34 if (x1 - x0) < 520 else 22
        if not items:
            D.text(cr, x0, y, "Nothing here.", 11, "static", "regular")
            self.region(x0, top, x1 - x0, 34, f"{title.capitalize()}: nothing right now")
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

    def _item_row(self, cr, it, x0, x1, y, rowh):
        col = "amber" if it["pr"] else "soft"
        mark = "PR" if it["pr"] else "IS"
        self.chip(cr, x0, y + 2, mark, col)
        two = rowh > 24
        meta = (f"{it['acct']} · " if it.get("acct") else "") + \
            f"{it['repo']}#{it['number']} · {it.get('author') or '?'} · {K.ago(it['updated'])}"
        D.text(cr, x0 + 30, y + 1, it["title"], 11, "soft", "medium", width=x1 - x0 - 30 - (0 if two else 200))
        if two:
            D.text(cr, x0 + 30, y + 16, meta, 10, "static", "regular", width=x1 - x0 - 30)
        else:
            D.text(cr, x1, y + 2, meta, 10, "static", "regular", align="right", width=196)
        kind = "pull request" if it["pr"] else "issue"
        self.region(x0, y, x1 - x0, rowh - 2, f"{it['title']}: {kind} {it['repo']}#{it['number']}"
                    + (f" on {it['acct']}" if it.get("acct") else "") + " by "
                    f"{it.get('author') or '?'}, updated {K.ago(it['updated'])} ago, {it.get('comments', 0)} comment(s)"
                    f"{', a draft' if it.get('draft') else ''}. Click to open it.", lambda u=it["url"]: K.open_url(u))

    def _note_row(self, cr, n, x0, x1, y, rowh):
        D.dot(cr, x0 + 4, y + 8, 3, "phosphor" if n["unread"] else "static", glow=n["unread"] and K.motion() == "full")
        two = rowh > 24
        D.text(cr, x0 + 14, y + 1, n["title"], 11, "soft" if n["unread"] else "static", "medium",
               width=x1 - x0 - 14 - (0 if two else 200))
        meta = (f"{n['acct']} · " if n.get("acct") else "") + f"{n['repo']} · {n['why']} · {K.ago(n['updated'])}"
        if two:
            D.text(cr, x0 + 14, y + 16, meta, 10, "static", "regular", width=x1 - x0 - 14)
        else:
            D.text(cr, x1, y + 2, meta, 10, "static", "regular", align="right", width=196)
        self.region(x0, y, x1 - x0, rowh - 2, f"{n['title']} ({n['type'] or 'notification'} in {n['repo']}"
                    + (f" on {n['acct']}" if n.get("acct") else "") + "): "
                    f"{n['why']}, {'unread' if n['unread'] else 'read'}, {K.ago(n['updated'])} ago. Click to open it.",
                    lambda u=n["url"]: K.open_url(u))

    def _repos(self, cr, d, x0, x1, top, bottom):
        repos = d.get("repos") or []
        stars = sum(r["stars"] for r in repos)
        D.label(cr, x0, top, f"REPOSITORIES · ★ {K.short(stars)}", "phosphor" if repos else "dim", size=10)
        self.region(x0, top - 2, x1 - x0, 16, f"Your {len(repos)} repositories have {stars} stars between them. "
                    "Listed by latest push.")
        y = top + 18
        n = int(self.conf.get("repos", 6) or 6)
        top_stars = max([r["stars"] for r in repos] + [1])
        for r in repos[:min(n, max(1, int((bottom - y) // 22)))]:
            frac = r["stars"] / top_stars
            D.src(cr, "amber", 0.10)
            cr.rectangle(x0, y + 1, (x1 - x0) * frac, 18)
            cr.fill()
            D.text(cr, x0 + 4, y + 2, (f"{r['acct']} · " if r.get("acct") else "") + r["name"], 11, "soft", "medium",
                   width=(x1 - x0) * 0.55)
            D.text(cr, x1 - 4, y + 2, f"★ {K.short(r['stars'])}", 11, "amber", "semibold", align="right")
            D.text(cr, x1 - 70, y + 3, K.ago(r["pushed"]), 10, "static", "regular", align="right")
            self.region(x0, y, x1 - x0, 20, f"{r['full']}{' (private)' if r['private'] else ''}"
                        + (f" on {r['acct']}" if r.get("acct") else "") + f": {r['stars']} stars, "
                        f"{r['forks']} forks, {r['issues']} open issues, {r['language'] or 'no language'}; last push "
                        f"{K.ago(r['pushed'])} ago. {r['description'][:120]} Click to open it.",
                        lambda u=r["url"]: K.open_url(u))
            y += 22
        return y

    def _events(self, cr, d, x0, x1, top, bottom):
        evs = d.get("events") or []
        D.label(cr, x0, top, "ACTIVITY ON YOUR REPOS", "phosphor" if evs else "dim", size=10)
        y = top + 18
        if not evs:
            D.text(cr, x0, y, "Nothing lately.", 11, "static", "regular")
            self.region(x0, top, x1 - x0, 34, "No recent events on your newest repositories")
            return
        for e in evs[:max(0, int((bottom - y) // 20))]:
            star = e["type"] == "WatchEvent"
            D.text(cr, x0, y + 1, "★" if star else "•", 11, "amber" if star else "dim", "semibold")
            who = "you" if e["me"] else e["actor"]
            D.text(cr, x0 + 14, y + 1, f"{who} {e['words']}", 11, "soft" if not e["me"] else "static", "regular",
                   width=(x1 - x0) * 0.62)
            D.text(cr, x1, y + 2, (f"{e['acct']} · " if e.get("acct") else "") +
                   f"{e['repo'].split('/')[-1]} · {K.ago(e['at'])}", 10, "static", "regular",
                   align="right", width=(x1 - x0) * 0.36)
            self.region(x0, y, x1 - x0, 18, f"{who} {e['words']} in {e['repo']}"
                        + (f" on {e['acct']}" if e.get("acct") else "") + f", {K.ago(e['at'])} ago. Click to open "
                        "the repository.", lambda r=e["repo"], web=e.get("web") or self.web(): K.open_url(f"{web}/{r}"))
            y += 20

    def _graph(self, cr, d, x0, x1, top, bottom):
        c, gerr = self.graph()
        if c is None and not self.demo and getattr(self, "_graph_skipped", True):
            for a in self.accts.signed_in():             # just became large: read it now
                pl = self.accts.poller(a, "graph")
                if pl is not None and not pl.busy:
                    pl.kick()
        D.label(cr, x0, top, "CONTRIBUTIONS · LAST YEAR" + (f" · {c['total']:,}" if c else ""), "phosphor", size=10)
        if not c or not c["weeks"]:
            D.text(cr, x0, top + 20, gerr or "Reading the contribution graph…", 11, "static", "regular",
                   width=x1 - x0)
            self.region(x0, top, x1 - x0, bottom - top, "Your contribution graph, read hourly while the panel is large")
            return
        weeks = c["weeks"]
        gy = top + 32
        cell = min(22, (bottom - gy) / 7, (x1 - x0) / max(1, len(weeks)))
        last = None
        for wi, wk in enumerate(weeks):                  # month names above their first week
            if wk and wk[0][0][5:7] != last:
                last = wk[0][0][5:7]
                if wi and x0 + wi * cell + 24 < x1:
                    import datetime as _dt
                    D.text(cr, x0 + wi * cell, top + 16, _dt.date.fromisoformat(wk[0][0]).strftime("%b"), 10,
                           "static", "regular")
        days = [t for wk in weeks for t in wk]
        if days:
            best = max(days, key=lambda t: t[1])
            streak = 0
            for _, n in reversed(days):
                if not n:
                    break
                streak += 1
            D.label(cr, x1, top, f"BEST {best[1]} ON {best[0]} · STREAK {streak}D", "static", size=10, align="right")
            self.region(x1 - 300, top - 2, 300, 16, f"Your busiest day was {best[0]} with {best[1]} contributions; "
                        f"you've contributed {streak} day(s) running")
        gap = 2 if cell >= 8 else 1
        counts = sorted(n for w in weeks for _, n in w if n)
        q = [counts[int(len(counts) * f)] if counts else 1 for f in (0.25, 0.5, 0.75)]
        for wi, wk in enumerate(weeks):
            for di, (date, n) in enumerate(wk):
                cx = x0 + wi * cell
                cy = gy + di * cell
                lvl = 0 if not n else 1 if n <= q[0] else 2 if n <= q[1] else 3 if n <= q[2] else 4
                D.src(cr, "guard" if not lvl else "phosphor", 0.9 if not lvl else (0.25, 0.45, 0.7, 1.0)[lvl - 1])
                cr.rectangle(cx, cy, cell - gap, cell - gap)
                cr.fill()
            if wk:
                self.region(x0 + wi * cell, gy, cell, 7 * cell, f"Week of {wk[0][0]}: {sum(n for _, n in wk)} "
                            f"contribution(s); busiest day {max(wk, key=lambda t: t[1])[0]} "
                            f"({max(n for _, n in wk)})")


PANEL = GitHubPanel
LAYOUT = {"visible": False}
