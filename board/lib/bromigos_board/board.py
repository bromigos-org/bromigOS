"""The signed-in board: the snapshot as the page reads it (docs/board.md, "GET /api/board").

The cards pass the shipped commands' --json through unchanged (`storage`, `backups`, `apps`,
`updates`). What the page draws first is worked out here from those same documents, and from
nothing else: the one status line, what needs you (the alerts that need a person, and jobs
waiting for an answer), what fixed itself (jobs that rolled back) and this machine's row. A part
whose command couldn't run is null, and the page says it can't check.
"""
from . import SCHEMA, door

MAX_AGE_S = 45                       # a reading older than this is stale: the page greys it
SEVERITY = {"needs_you": "warn", "critical": "critical"}
# where each alert's fact lives on the page, by its check's first word
GO = {"disk": "data", "drive": "data", "storage": "data", "btrfs": "data", "backup": "data/backups",
      "update": "supply/updates", "news": "supply/updates", "activity": "activity"}
SUBJECT = {"disk.smart": "drive", "disk.space": "mount", "ups": "ups", "service": "service"}
EXTRA = ("host", "settings", "sources", "system", "activity", "alerts")


def _list(doc, key):
    v = (doc or {}).get(key) if isinstance(doc, dict) else None
    return v if isinstance(v, list) else []


def apps_of(snap):
    a = snap.get("apps")
    if isinstance(a, dict) and isinstance(a.get("apps"), list):
        return a["apps"]
    return a if isinstance(a, list) else None


def needs_you(snap, host):
    out = []
    for a in _list(snap.get("alerts"), "alerts"):
        if not isinstance(a, dict) or a.get("severity") not in SEVERITY:
            continue
        check = str(a.get("check") or "")
        subject = a.get("subject") or ""
        out.append({"id": a.get("id"), "machine": host,
                    "subject": {"type": SUBJECT.get(check, check.split(".")[0] or "server"), "id": subject, "name": subject}
                    if subject else None,
                    "severity": SEVERITY[a["severity"]], "words": a.get("title") or "", "detail": a.get("detail") or "",
                    "since": a.get("since"), "go": GO.get(check.split(".")[0]), "job": None})
    for j in _list(snap.get("activity"), "jobs"):
        if isinstance(j, dict) and j.get("state") == "needs-you":
            q = j.get("question") or {}
            out.append({"id": j.get("id"), "machine": host, "subject": j.get("subject"), "severity": "warn",
                        "words": j.get("title") or "", "detail": q.get("text") or "", "since": q.get("asked_at") or j.get("updated_at"),
                        "go": "activity", "job": j.get("id")})
    return out


def fixed(snap, host):
    return [{"id": j.get("id"), "machine": host, "words": ((j.get("result") or {}).get("summary") or j.get("title") or ""),
             "at": j.get("ended_at") or j.get("updated_at")}
            for j in _list(snap.get("activity"), "jobs") if isinstance(j, dict) and j.get("state") == "rolled-back"]


def status(snap, stale, needs, apps):
    if stale:
        return "unknown", "Can't check right now: the last reading is old."
    if needs:
        n = len(needs)
        return "needs-you", f"{n} thing{'s need' if n != 1 else ' needs'} you."
    if apps is not None and not any(isinstance(a, dict) and a.get("installed", True) for a in apps):
        return "setup", "Nothing is set up yet."
    return "ok", "Everything is running."


def shape(snap, now_ms):
    """The page's board document from one snapshot (board.json)."""
    host = snap.get("host") if isinstance(snap.get("host"), str) else ""
    at = int(snap.get("at") or 0)
    age = max(0, (now_ms - at) // 1000)
    stale = age > MAX_AGE_S
    system = snap.get("system") if isinstance(snap.get("system"), dict) else None
    apps = apps_of(snap)
    needs = needs_you(snap, host)
    state, words = status(snap, stale, needs, apps)
    roles = list(((system or {}).get("roles") or {}).get("enabled") or [])
    machine_state = {"ok": "ok", "setup": "ok", "needs-you": "warn", "unknown": "unknown"}[state]
    doc = {
        "schema": SCHEMA, "at": at, "max_age_s": MAX_AGE_S, "age_s": age, "stale": stale,
        "lab": door.lab(host),
        "server": {"name": host, "kind": "server", "roles": roles},
        "status": {"state": state, "words": words, "checked_at": at},
        "machines": [{"name": host, "kind": "server", "here": True, "page": True, "state": machine_state,
                      "state_word": {"ok": "online", "warn": "needs you", "unknown": "can't check"}[machine_state],
                      "roles": roles, "updates": None, "readings": None,
                      "apps": sum(1 for a in apps if isinstance(a, dict) and a.get("installed", True)) if apps is not None else None}],
        "needs_you": needs,
        "fixed": fixed(snap, host),
        "apps": apps,
        "storage": snap.get("storage"),
        "backups": snap.get("backups"),
        "updates": {"updates": system.get("updates"), "rollbacks": system.get("rollbacks")} if system else None,
        "ups": (system or {}).get("ups"),
    }
    # the commands' own documents too, for the Depth drawer and for scripts
    doc.update({k: snap.get(k) for k in EXTRA})
    return doc
