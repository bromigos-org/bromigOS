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
# the parts the status line stands on, and what each is called when it couldn't be read
PARTS = (("alerts", "the alerts"), ("activity", "the jobs"), ("apps", "the apps"), ("storage", "the drives' health"),
         ("backups", "the backups"), ("system", "the system's status"))
NOT_RUNNING = ("down", "degraded")       # an app's states that `bromigos lab apps list` ends 1 for


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
    # `title` is the job's own ("Updating Photos"); `words` what became of it, which for a job
    # that put things back names no subject ("It failed and put things back by itself.")
    return [{"id": j.get("id"), "machine": host, "title": j.get("title") or "",
             "words": ((j.get("result") or {}).get("summary") or j.get("title") or ""),
             "at": j.get("ended_at") or j.get("updated_at")}
            for j in _list(snap.get("activity"), "jobs") if isinstance(j, dict) and j.get("state") == "rolled-back"]


def _said(doc):
    """What an error document says went wrong ({"error": "…"} or {"error": {"message": "…"}})."""
    e = doc.get("error") if isinstance(doc, dict) else None
    e = e.get("message") if isinstance(e, dict) else e
    return e if isinstance(e, str) and e else None


def unread(snap):
    """The parts that couldn't be read this time: [(part, its name in words, why or None)]. A
    command that didn't answer (`sources` has why), or one that answered with an error document
    and not the reading."""
    sources = snap.get("sources") if isinstance(snap.get("sources"), dict) else {}
    out = []
    for part, words in PARTS:
        doc = snap.get(part)
        have = apps_of(snap) is not None if part == "apps" else \
            isinstance(doc, dict) and not (part == "backups" and not isinstance(doc.get("health"), dict))
        if not have:
            note = sources.get(part) if isinstance(sources.get(part), dict) else {}
            out.append((part, words, _said(doc) or (note.get("why") if isinstance(note.get("why"), str) else None)))
    return out


def _names(things):
    return things[0] if len(things) == 1 else ", ".join(things[:-1]) + " and " + things[-1]


def status(snap, stale, needs, apps):
    """The one status line, worst first. It says "Everything is running." only when every part
    was read and nothing in them says otherwise: a part that couldn't be read is "unknown", with
    the part and the reason in the words."""
    if stale:
        return "unknown", "Can't check right now: the last reading is old."
    if needs:
        n = len(needs)
        return "needs-you", f"{n} thing{'s need' if n != 1 else ' needs'} you."
    down = [str(a.get("job") or a.get("id") or "An app") for a in apps or []
            if isinstance(a, dict) and a.get("installed", True) and a.get("state") in NOT_RUNNING]
    if down:
        return "needs-you", f"{_names(down[:3])} {'is' if len(down) == 1 else 'are'}n't running." if len(down) <= 3 \
            else f"{len(down)} apps aren't running."
    health = (snap.get("backups") or {}).get("health") if isinstance(snap.get("backups"), dict) else None
    if isinstance(health, dict) and health.get("state") == "attention":
        return "needs-you", str(health.get("verdict") or "The backups need a look.")
    # nothing installed is said before what couldn't be read: it is true either way, and it
    # doesn't say all is well
    if apps is not None and not any(isinstance(a, dict) and a.get("installed", True) for a in apps):
        return "setup", "Nothing is set up yet."
    missing = unread(snap)
    if missing:
        whys = {why for _, _, why in missing if why}
        # one reason when they all failed the same way (no `bromigos` at all); else each its own
        if len(missing) == 1 or len(whys) == 1:
            why = f" ({next(iter(whys))})" if whys else ""
            return "unknown", f"Can't say everything is running: {_names([w for _, w, _ in missing])} couldn't be read{why}."
        return "unknown", "Can't say everything is running: " + "; ".join(
            f"{w} couldn't be read" + (f" ({why})" if why else "") for _, w, why in missing) + "."
    return "ok", "Everything is running."


def _num(v):
    return v if isinstance(v, (int, float)) and not isinstance(v, bool) else None


def hardware(snap):
    """What is in the box, as the app manager's scan has it (`bromigos lab apps budget --json`,
    its `hardware`): cores, memory, the free disk where apps keep their data, and whether there
    is a graphics card. None when that command didn't answer. The drives aren't listed here:
    `storage.drives` has them, and no command prints their sizes yet."""
    b = snap.get("budget")
    hw = b.get("hardware") if isinstance(b, dict) else None
    if not isinstance(hw, dict):
        return None
    gpu, name = hw.get("gpu"), hw.get("gpu_name")
    return {"cpu": _num(hw.get("cpu")), "ram_gb": _num(hw.get("ram_gb")), "disk_gb": _num(hw.get("disk_gb")),
            # the scan says which kind of card ("nvidia"), or false
            "gpu": bool(gpu), "gpu_kind": gpu if isinstance(gpu, str) and gpu else None,
            "gpu_name": name if isinstance(name, str) and name else None, "gpu_vram_gb": _num(hw.get("gpu_vram_gb"))}


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
    # the machine's row: whether it answers, and whether something on it needs a person. What
    # the status line adds (an app that isn't running, a part that couldn't be read) is the
    # status line's; the row doesn't say "can't check" of a machine that answered.
    machine_state = "unknown" if stale else "warn" if needs else "ok"
    doc = {
        "schema": SCHEMA, "at": at, "max_age_s": MAX_AGE_S, "age_s": age, "stale": stale,
        "lab": door.lab(host),
        "server": {"name": host, "kind": "server", "roles": roles},
        "status": {"state": state, "words": words, "checked_at": at},
        "machines": [{"name": host, "kind": "server", "here": True, "page": True, "state": machine_state,
                      "state_word": {"ok": "online", "warn": "needs you", "unknown": "can't check"}[machine_state],
                      "roles": roles, "updates": None, "readings": None, "hardware": hardware(snap),
                      "apps": sum(1 for a in apps if isinstance(a, dict) and a.get("installed", True)) if apps is not None else None}],
        "needs_you": needs,
        "fixed": fixed(snap, host),
        "apps": apps,
        "storage": snap.get("storage"),
        "backups": snap.get("backups"),
        "updates": {"updates": system.get("updates"), "rollbacks": system.get("rollbacks")} if system else None,
        "ups": (system or {}).get("ups"),
        # what the page may ask for (root's [board] actions, as the reader read it): the page
        # shows a control only for a verb that is here. Root's helper decides again each time.
        "actions": [a for a in snap.get("actions") or [] if isinstance(a, str)] if isinstance(snap.get("actions"), list) else [],
    }
    # the commands' own documents too, for the Depth drawer and for scripts
    doc.update({k: snap.get(k) for k in EXTRA})
    return doc
