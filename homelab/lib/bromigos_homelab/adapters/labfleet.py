"""Tasks: a fleet of coding agents, read from its control repository's Status issue (fleet.py has
the reading, the words and the picture; docs/lab.md, "Tasks").

    [[source]]
    name = "tasks"                      # one source per business; give each its own name
    type = "fleet"
    repo = "my-org/agents"              # the control repository, read through your gh login
    # label = "agent-state"             # the label its Status issue carries

    [[source]]                          # optional: your lab's status mirror, which holds the feeds, instead of GitHub
    name = "tasks"
    type = "fleet"
    url = "http://status-mirror.mylab.example:8082/v1/feed"
    # business = "example"              # only this business's feed (the mirror's name for it); without it, every one

Read-only, on this machine: `gh api` with your own login for a repository, a GET for a mirror.
Each answer is kept for a minute (fleet.cached), so a view that refreshes every few seconds doesn't
ask GitHub that often. `tasks` records: one per business first (kind "fleet": its headline in
`phrase`, the whole picture in `view`), then one per task (kind "task").
"""
from datetime import datetime, timezone

from .. import fleet
from ..registry import Unreachable, register
from . import labcommon as L


@register
class Fleet(L.LabAdapter):
    type = "fleet"
    provides = ("tasks",)
    local = True

    def _url(self):
        return self.opt("url") or self.endpoint

    def configured(self):
        return bool(self.opt("repo") or self._url())

    def feeds(self):
        """[{"business", "feed"} | {"business", "error"}]: the repository's one feed, or the mirror's.
        fleet.ReadError says why not."""
        url = self._url()
        if not url:
            repo, label = self.opt("repo"), self.opt("label", fleet.STATE_LABEL)
            feed = fleet.cached(("github", repo, label), lambda: fleet.read_github(repo, label))
            return [{"business": fleet.clean(feed.get("business"), 60) or "?", "feed": feed}]
        entries = fleet.cached(("url", url, self.name), lambda: fleet.read_url(
            url, headers=self.auth_headers(), context=self._ctx() if url.startswith("https://") else None))
        want = self.opt("business")
        if want:
            entries = [e for e in entries if e["business"].lower() == str(want).lower()]
        if not entries:
            raise fleet.ReadError("no-report", f"the mirror holds no feed for {fleet.clean(want, 60)}" if want else
                                  fleet.NO_REPORT)
        return entries

    def views(self, now=None):
        """[{"business", "view"} | {"business", "error"}]: fleet.view of each feed."""
        now = now or datetime.now(timezone.utc)
        return [{"business": e["business"], "view": fleet.view(e["feed"], now)} if e.get("feed") else
                {"business": e["business"], "error": e.get("error") or "the feed could not be read"}
                for e in self.feeds()]

    def tasks(self):
        try:
            views = self.views()
        except fleet.ReadError as e:
            raise Unreachable(f"{self.name}: {e}") from None
        out = []
        for one in views:
            v = one.get("view")
            if not v:
                out.append({"name": one["business"], "kind": "fleet", "business": one["business"], "phrase": "Not read",
                            "state": "warn", "error": one["error"], "view": None})
                continue
            out.append({"name": v["business"], "kind": "fleet", "business": v["business"], "phrase": v["headline"],
                        "url": v["url"], "since": v["generated_at"], "check": v["state"],
                        "state": "ok" if v["fresh"] and not v["counts"]["needs_you"] else "warn", "view": v})
            for lane in v["lanes"]:
                for row in lane["rows"] + lane["events"]:
                    out.append({"name": row["label"], "kind": "task", "business": v["business"], "lane": row["lane"],
                                "repo": row["repo"], "number": row["number"], "title": row["title"],
                                "phrase": row["phrase"], "url": row["url"], "since": row["at"],
                                "state": {"needs_you": "warn", "working": "ok", "done": "ok"}.get(row["lane"])})
        return out
