"""Tasks: what a fleet of coding agents is doing, read-only (docs/lab.md, "Tasks").

A *fleet* is a set of coding agents that work through the issues of one business's
repositories by themselves. Its *control repository* keeps an issue titled `Status` (label
`agent-state`), which the fleet's scheduled job rewrites: Markdown for people, then a
`<details>` block with exactly one fenced `json` document, the *feed* (`"schema": 1`). This
module reads that feed and makes the one picture every surface prints: the Tasks card
(`bromigos lab status`, the dashboard, the Lab deck, Settings › Lab) and `bromigos lab tasks`.

    [[source]]
    name = "tasks"
    type = "fleet"                       # adapters/labfleet.py
    repo = "my-org/agents"               # the control repository, read through your gh login

    parse_body(text)      the feed out of the issue's body (FeedError when it holds none)
    check(feed, now)      fresh, stale or switched off
    view(feed, now)       the picture: a headline, lanes of rows, counts, accounts, warnings
    read_github(repo)     the feed, through `gh api` and your own gh login (ReadError says why not)
    read_url(url)         the feeds your lab's status mirror holds, over HTTP (optional)
    cached(key, read)     one read a minute, however often a view refreshes
    card(result)          the Tasks card, from the `tasks` capability's records
    render_text(view)     the picture in plain text, 80 columns
    main(argv)            bromigos lab tasks [--json]

The words are the fleet's own, so every surface says the same thing: a feed gives each task its
`lane` and its `phrase` ("Stuck · …", "Writing", "Checks running", "Fixing · round 2", "Queued ·
…", "Merged"), the lanes' counts and a `headline`, and this module shows them as given. The noun
is *task*. The lanes, in this order: Needs you, Proposed, Working, Waiting, Done. A feed written
before it carried those words gets them from the mapping here (working_phrase, _derive), and
nowhere else.

Titles, reasons and warnings in a feed are text other people wrote. clean() puts each on one
line, without control characters, terminal escape sequences or invisible characters, and caps
it. Nothing here reads it as markup, and a surface must not either.

Nothing here writes, and nothing here handles a token: GitHub is asked through `gh`.
"""
import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import textwrap
import threading
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

SCHEMA = 1                              # the feed's, and the view's
NOUN = "task"
STATUS_TITLE = "Status"                 # the issue the fleet's job keeps
STATE_LABEL = "agent-state"             # its label
STATUS_AUTHOR = "github-actions[bot]"   # who opens it: the job's own token
STALE_MINUTES = 90                      # a feed without `stale_after` is stale this long after it was written
CACHE_SECONDS = 60
CARD_ROWS = 8                           # tasks a business shows on the card before "+N more"
DONE_ROWS = 3                           # merged tasks `bromigos lab tasks` lists before "+N more"
MAX_BYTES = 2 * 1024 * 1024             # of a mirror's answer
NO_REPORT = ("no report yet: your lab's status mirror holds no feed until the fleet's next run, about ten minutes "
             "after the mirror started")

LANES = (("needs_you", "Needs you"), ("proposed", "Proposed"), ("working", "Working"), ("waiting", "Waiting"),
         ("done", "Done"))
_LANE_WORDS = {title.lower(): lane for lane, title in LANES}
SEP = " \u00b7 "                          # between a phrase's words and its reason, and the headline's parts
# the feed's lists, the lane each fills when an entry names none, and the field that says since when
_LISTS = (("needs_person", "needs_you", "since"), ("proposed", "proposed", "filed_at"),
          ("working", "working", "started_at"), ("waiting", "waiting", None), ("recent", "done", "at"))
NOT_MERGED = ("stuck", "blocked", "rejected")       # how work in `recent` ended without a merge: events, not tasks
# what a feed holds today; one that lacks any of these says so in the view's warnings
_EXPECTED = {"generated_at": str, "stale_after": str, "business": str, "enabled": bool, "timezone": str,
             "accounts": list, "working": list, "waiting": list, "needs_person": list, "recent": list, "counts": dict,
             "warnings": list, "omitted": dict}
_FRESH = {"state": "fresh", "stale": False, "age": None}
_COUNTS = ("started", "merged", "stuck", "blocked", "rejected")

HINT = ("What your fleet of coding agents is doing, from its control repository's Status issue (read through your gh "
        "login, at most once a minute). The tasks that need you come first, then the ones being worked on. bromigos "
        "lab tasks lists every task with its links. No update: the fleet's job hasn't written for 90 minutes, so it "
        "is switched off, disabled or failing.")

# each of these is used with fullmatch: `$` would let a trailing newline through
_REPO = re.compile(r"[A-Za-z0-9][A-Za-z0-9-]{0,38}/(?![.]{1,2}$)[A-Za-z0-9._-]{1,100}")
_NAME = re.compile(r"[A-Za-z0-9._-]{1,100}")
_LABEL = re.compile(r"[A-Za-z0-9._-]{1,50}")
_TIME = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z")
_URL = re.compile(r"https?://[A-Za-z0-9.-]{1,200}(?::[0-9]{1,5})?(?:/[A-Za-z0-9._/-]{0,400})?")
# terminal escape sequences, whole: OSC, DCS and friends up to their terminator, CSI, two-character ones
_ESCAPE = re.compile(r"\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)?|\x1b[PX^_][^\x1b]*(?:\x1b\\)?|\x1b\[[0-?]*[ -/]*[@-~]"
                     r"|\x9b[0-?]*[ -/]*[@-~]|\x1b[ -/]*[0-~]")
# controls and separators that break a line or a column: each becomes a space
_BREAK = re.compile("[\t\n\u000b\u000c\r\u001c-\u001f\u0085\u2028\u2029]")
# characters with no visible form of their own: the other controls, the soft hyphen, zero-width and
# joining characters, bidirectional controls, fillers, tag characters, and lone surrogates (which no
# terminal can print). Written as escapes: none of them stands in this file.
_INVISIBLE = re.compile("[\u0000-\u0008\u000e-\u001b\u007f-\u009f\u00ad\u034f\u061c\u115f\u1160\u17b4\u17b5"
                        "\u180b-\u180e\u200b-\u200f\u202a-\u202e\u2060-\u2064\u2066-\u206f\u3164\ufeff\uffa0"
                        "\ud800-\udfff\U000e0000-\U000e007f]")


class FeedError(ValueError):
    """The text holds no feed this version can read."""


class ReadError(OSError):
    """The feed could not be fetched. kind: no-gh, signed-out, no-access, no-issue, bad-feed or failed."""

    def __init__(self, kind, message):
        super().__init__(message)
        self.kind = kind


# ------------------------------------------------------------------ text other people wrote
def clean(text, limit=200):
    """Text someone else wrote, safe to print: one line, no control character or escape sequence,
    nothing invisible, at most `limit` characters ("…" marks a cut). Never markup."""
    if text is None or isinstance(text, (dict, list, bool)):
        return ""
    text = str(text)[:8 * max(1, int(limit)) + 64]          # a megabyte of title is not worth a regex's time
    text = " ".join(_INVISIBLE.sub("", _BREAK.sub(" ", _ESCAPE.sub("", text))).split())
    return text if len(text) <= limit else text[:max(1, limit - 1)].rstrip() + "…"


def _int(v):
    return v if isinstance(v, int) and not isinstance(v, bool) and v >= 0 else None


def _link(v):
    """An address the feed's writer built, or "" for anything that isn't a plain http(s) one."""
    return v if isinstance(v, str) and _URL.fullmatch(v) else ""


def _moment(v):
    if not isinstance(v, str) or not _TIME.fullmatch(v):
        return None
    try:
        return datetime.strptime(v, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def _iso(m):
    return m.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ") if m else None


def _now(now=None):
    if now is None:
        return datetime.now(timezone.utc)
    if isinstance(now, (int, float)):
        return datetime.fromtimestamp(now, timezone.utc)
    return now if now.tzinfo else now.replace(tzinfo=timezone.utc)


def span(seconds):
    """"1 h 40 min" for 6000 seconds."""
    s = max(0, int(seconds))
    if s < 60:
        return "under a minute"
    m = s // 60
    if m < 60:
        return f"{m} min"
    if m < 24 * 60:
        return f"{m // 60} h" + (f" {m % 60} min" if m % 60 else "")
    h = m // 60
    return f"{h // 24} d" + (f" {h % 24} h" if h % 24 else "")


# ------------------------------------------------------------------ the feed out of the issue
def validate(doc):
    """The feed, when it is an object of the schema this version reads; FeedError otherwise."""
    if not isinstance(doc, dict):
        raise FeedError("the feed is not a JSON object")
    schema = doc.get("schema")
    if isinstance(schema, bool) or not isinstance(schema, int):
        raise FeedError("the feed has no `schema` number")
    if schema != SCHEMA:
        raise FeedError(f"the feed is schema {schema} and this bromigOS reads schema {SCHEMA}: update bromigOS "
                        "to read it")
    return doc


def parse_body(text):
    """The feed out of the Status issue's body. The body must hold exactly one line that reads
    ```json; the feed is the text from there to the next line that reads ```. Anything else is
    refused: this never searches a body for JSON, and never reads its Markdown."""
    lines = [line.rstrip() for line in str(text or "").replace("\r\n", "\n").split("\n")]
    starts = [n for n, line in enumerate(lines) if line == "```json"]
    if len(starts) != 1:
        raise FeedError("the body must hold exactly one ```json block, and this one holds "
                        + ("none" if not starts else str(len(starts))))
    try:
        end = lines.index("```", starts[0] + 1)
    except ValueError:
        raise FeedError("the ```json block is not closed") from None
    try:
        doc = json.loads("\n".join(lines[starts[0] + 1:end]))
    except (ValueError, RecursionError):
        raise FeedError("the ```json block is not JSON") from None
    return validate(doc)


# ------------------------------------------------------------------ fresh, stale, switched off
def check(feed, now=None):
    """Is the feed current? {"state": fresh | stale | off, "fresh", "stale", "enabled", "generated_at",
    "stale_after", "age_s", "age"}.

    stale  now is past `stale_after` (or the feed doesn't say when it was written): the fleet's job
           has not written for longer than it ever would while running. That is also how a
           switched-off fleet looks, since its job doesn't run to say so.
    off    the feed says `enabled: false` itself. It can be stale as well (`stale` says)."""
    now = _now(now)
    written = _moment(feed.get("generated_at"))
    limit = _moment(feed.get("stale_after")) or (written + timedelta(minutes=STALE_MINUTES) if written else None)
    age = max(0, int((now - written).total_seconds())) if written else None
    stale = limit is None or now > limit
    off = feed.get("enabled") is False
    return {"state": "off" if off else "stale" if stale else "fresh", "fresh": not off and not stale, "stale": stale,
            "enabled": not off, "generated_at": _iso(written), "stale_after": _iso(limit), "age_s": age,
            "age": span(age) if age is not None else None}


def headline(counts, chk, said=None):
    """The one sentence: "2 need you · 3 working · 1 waiting · 4 merged today". "Nothing needs you"
    only for a feed that was read and is fresh; a stale one says for how long, a switched-off one
    says SWITCHED OFF. said: the feed's own `headline`, used as it is for a fresh feed. Without
    it the sentence is made as the fleet makes it: proposals only when there are any, the merges
    left out when their count isn't known."""
    if chk["state"] == "off":
        return "SWITCHED OFF" + (f" · no update for {chk['age']}" if chk["stale"] and chk["age"] else "")
    if chk["state"] == "stale":
        return f"No update for {chk['age']}" if chk["age"] else "No update: the feed doesn't say when it was written"
    if said:
        return said
    need = counts.get("needs_you") or 0
    parts = [f"{need} need{'s' if need == 1 else ''} you" if need else "Nothing needs you"]
    if counts.get("proposed"):
        parts.append(f"{counts['proposed']} proposed")
    parts += [f"{counts.get('working') or 0} working", f"{counts.get('waiting') or 0} waiting"]
    if counts.get("merged_today") is not None:
        parts.append(f"{counts['merged_today']} merged today")
    return SEP.join(parts)


# ------------------------------------------------------------------ the canonical words
def _why(entry, limit=160):
    return clean(entry.get("why"), limit)


def _with(word, why):
    return f"{word} · {why}" if why else word


# what the job a work run is in is called (`stage` agent)
_STEP_WORDS = {"queued": "Starting", "prepare": "Starting", "agent": "Writing", "verify": "Checking the change",
               "review": "Reviewing", "second_review": "Second review", "finish": "Opening the pull request"}


def working_phrase(entry):
    """A working task's phrase from its `stage` and `step`, for a feed that gives none; None for a
    stage this version doesn't know. A fix run's round is the fleet's to count, so without the
    feed's phrase it is just "Fixing"."""
    stage, step = entry.get("stage"), entry.get("step")
    if stage == "agent":
        return _STEP_WORDS.get(step, "Working")
    if stage == "checks":
        return "Waiting for checks" if str(entry.get("why") or "").startswith("no checks") else "Checks running"
    if stage == "review":
        return "Second review" if step == "second_review" else "Reviewing"
    if stage == "fixing":
        return "Fixing"
    if stage == "merging":
        return "Merging"
    return None


def _derive(key, entry):
    """The phrase of a row of the feed's list `key`, for a feed that gives none."""
    if key == "needs_person":
        return _with({"stuck": "Stuck", "blocked": "Blocked"}.get(entry.get("kind"), "Needs you"), _why(entry))
    if key == "proposed":
        return "Proposed"
    if key == "working":
        return working_phrase(entry) or "Working"
    if key == "waiting":
        return _with("Queued" if entry.get("kind") == "queued" else "Waiting", _why(entry))
    if entry.get("outcome") == "merged":
        return "Merged"
    return _with("Not merged", _why(entry) or (entry["outcome"] if entry.get("outcome") in ("stuck", "blocked") else ""))


# ------------------------------------------------------------------ the picture
def _zone(feed, notes):
    name = feed.get("timezone")
    if isinstance(name, str) and name:
        try:
            return ZoneInfo(name), name
        except (ValueError, OSError, LookupError):
            notes.append(f"This computer doesn't know the feed's time zone ({clean(name, 60)}): times are in UTC.")
    return timezone.utc, "UTC"


def _when(moment, now, zone):
    """A time in the feed's zone: 15:45 today, Sat 28 Nov 15:45 another day."""
    if moment is None:
        return ""
    local, today = moment.astimezone(zone), now.astimezone(zone)
    if local.date() == today.date():
        return local.strftime("%H:%M")
    return local.strftime("%a %d %b %H:%M") if abs((local - today).days) < 300 else local.strftime("%d %b %Y %H:%M")


def _entries(feed, key):
    v = feed.get(key)
    return [e for e in v if isinstance(e, dict)] if isinstance(v, list) else []


def _row(key, lane, at_field, entry, now, zone):
    issue, pr = _int(entry.get("issue")), _int(entry.get("pr"))
    repo = entry.get("repo") if isinstance(entry.get("repo"), str) and _NAME.fullmatch(entry["repo"]) else \
        clean(entry.get("repo"), 60) or "?"
    number = issue or pr
    given = clean(entry.get("phrase"), 300) if isinstance(entry.get("phrase"), str) else ""
    phrase = given or _derive(key, entry)
    # the reason is said once: a phrase that ends in it carries it already
    why, tail = clean(entry.get("why"), 300).rstrip("…"), phrase.partition(SEP)[2].rstrip("…")
    said = bool(why and tail and (why.startswith(tail) or tail.startswith(why)))
    at = _moment(entry.get(at_field)) if at_field else None
    first = _link(entry.get("issue_url")) if issue else _link(entry.get("pr_url"))
    links = []
    if issue and pr and _link(entry.get("pr_url")):
        links.append({"text": f"PR #{pr}", "url": entry["pr_url"]})
    if _link(entry.get("run_url")):
        links.append({"text": "run", "url": entry["run_url"]})
    minutes = entry.get("minutes")
    reviewers = entry.get("reviewers")
    return {"lane": lane, "label": f"{repo}#{number}" if number else repo, "repo": repo, "number": number,
            "issue": issue, "pr": pr, "title": clean(entry.get("title"), 160), "phrase": phrase,
            "why": "" if said else _why(entry), "at": _iso(at), "when": _when(at, now, zone),
            "today": bool(at and at.astimezone(zone).date() == now.astimezone(zone).date()),
            "url": first or _link(entry.get("url")), "links": links, "account": _int(entry.get("account")),
            "attempt": _int(entry.get("attempt")), "turns": _int(entry.get("turns")),
            "minutes": round(float(minutes), 1) if isinstance(minutes, (int, float)) and not isinstance(minutes, bool)
            and 0 <= minutes < 1e6 else None,
            "reviewers": [r for r in (clean(x, 40) for x in reviewers[:4]) if r] if isinstance(reviewers, list) else None}


def _schedule(entry, now, zone):
    """One scheduled job of the fleet, as a screen says it."""
    nxt, last = _moment(entry.get("next_at")), _moment(entry.get("last_run_at"))
    said = clean(entry.get("last_words"), 80) or clean(str(entry.get("last_outcome") or "").replace("_", " "), 40)
    tickets = []
    for t in _entries(entry, "tickets")[:10]:
        repo = t.get("repo") if isinstance(t.get("repo"), str) and _NAME.fullmatch(t["repo"]) else clean(t.get("repo"), 60)
        if repo and _int(t.get("issue")):
            tickets.append({"label": f"{repo}#{t['issue']}", "url": _link(t.get("url"))})
    return {"id": clean(entry.get("id"), 60) or "?", "name": clean(entry.get("name"), 80), "when": clean(entry.get("when"), 60),
            "next_at": _iso(nxt), "next": _when(nxt, now, zone), "last_run_at": _iso(last), "last": _when(last, now, zone),
            "last_words": said, "url": _link(entry.get("last_run_url")), "digest_url": _link(entry.get("digest_url")),
            "tickets": tickets}


def _account(entry, now, zone):
    state, until = entry.get("state"), _moment(entry.get("until"))
    if state == "available":
        phrase = "Available"
    elif state == "resting":
        phrase = f"Resting until {_when(until, now, zone)}" if until else "Resting"
    else:
        state, phrase = "unknown", "Unknown"
    return {"number": _int(entry.get("number")), "state": state, "until": _iso(until), "phrase": phrase}


def view(feed, now=None):
    """The picture every surface prints, from a feed (validate() or parse_body() gave it):

      {"schema": 1, "noun": "task", "business", "control_repo", "url" (the run that wrote the feed),
       "state": fresh | stale | off, "fresh", "headline", "generated_at", "stale_after", "updated",
       "age_s", "age", "timezone", "driver": heartbeat | schedule | None, "ignored",
       "lanes": [{"id", "title", "count", "omitted", "rows": [row, …], "events": [row, …]}, …],
       "counts": {"needs_you", "proposed", "working", "waiting", "merged_today",
                  "today": {started, merged, stuck, blocked, rejected}, "seven_days": {…}},
       "accounts": [{"number", "state", "until", "phrase"}],
       "schedules": [{"id", "name", "when", "next_at", "next", "last_run_at", "last", "last_words",
                      "url", "digest_url", "tickets": [{"label", "url"}]}],
       "warnings": ["…"]}

    A row: {"lane", "label" (repo#number), "repo", "number", "issue", "pr", "title", "phrase", "why",
    "at", "when", "today", "url", "links": [{"text", "url"}], "account", "attempt", "turns", "minutes",
    "reviewers"}. Its lane and phrase are the feed's own when it gives them. `count` is the lane's
    tasks as the feed counts them (before it left any out for room, `omitted`). Done's rows are
    the merged tasks; its `events` are work that ended without a merge ("Not merged · …": stuck,
    blocked, turned down by a reviewer), which stand under Done and aren't tasks of their own.
    `ignored` counts what the fleet leaves alone, shown in no lane. Times are in the feed's time
    zone. Unknown fields are ignored; a missing one is named in `warnings` and its part is left
    out. This never raises on a feed validate() accepted."""
    now = _now(now)
    notes = []
    zone, zone_name = _zone(feed, notes)
    chk = check(feed, now)
    missing = [k for k, kind in _EXPECTED.items() if not isinstance(feed.get(k), kind)]
    if missing:
        notes.append("The feed is missing " + ", ".join(missing) + ": what "
                     + ("they" if len(missing) > 1 else "it") + " would show is left out.")
    omitted = feed.get("omitted") if isinstance(feed.get("omitted"), dict) else {}
    # the feed's own lanes: their titles, and how many tasks each holds
    said = {e["id"]: e for e in _entries(feed, "lanes") if isinstance(e.get("id"), str)}

    lanes = {lane: {"id": lane, "title": clean(said.get(lane, {}).get("title"), 40) or title, "count": 0, "omitted": 0,
                    "rows": [], "events": []} for lane, title in LANES}
    extra = {}                                   # lanes a newer feed names that this version doesn't know
    unknown_stage = unknown_outcome = skipped = left_alone = 0
    for key, lane, at_field in _LISTS:
        raw = feed.get(key)
        skipped += sum(1 for e in raw if not isinstance(e, dict)) if isinstance(raw, list) else 0
        for entry in _entries(feed, key):
            worded = isinstance(entry.get("phrase"), str) and bool(clean(entry["phrase"], 300))
            if ("lane" in entry and entry["lane"] is None) or ("lane" not in entry and entry.get("kind") == "ignored"):
                left_alone += 1                  # what the fleet leaves alone stands in no lane
                continue
            outcome = entry.get("outcome") if key == "recent" else None
            if key == "recent" and outcome != "merged" and outcome not in NOT_MERGED and not worded:
                unknown_outcome += 1
                continue
            if key == "working" and working_phrase(entry) is None and not worded:
                unknown_stage += 1
            row = _row(key, lane, at_field, entry, now, zone)
            named = clean(entry.get("lane"), 40) if isinstance(entry.get("lane"), str) else ""
            if named:
                to = _LANE_WORDS.get(named.lower().replace("_", " ").replace("-", " "))
                if to is None:                   # shown as given, after the lanes this version knows
                    to = "other:" + named.lower()
                    extra.setdefault(to, {"id": to, "title": named, "count": 0, "omitted": 0, "rows": [], "events": []})
                row["lane"] = to
            box = lanes.get(row["lane"]) or extra[row["lane"]]
            # in `recent`, only a merge is finished work: the rest are events under Done
            box["events" if key == "recent" and outcome != "merged" and row["lane"] == "done" else "rows"].append(row)
        if lane != "done":                       # `recent` is cut to its newest 20 by design, not for room
            lanes[lane]["omitted"] = _int(omitted.get(key)) or 0
    for box in list(lanes.values()) + list(extra.values()):
        counted = _int(said.get(box["id"], {}).get("count")) if box["id"] != "done" else None
        box["count"] = max(counted, len(box["rows"])) if counted is not None else len(box["rows"]) + box["omitted"]
    if unknown_stage:
        notes.append(f"{unknown_stage} working {NOUN}{'s are' if unknown_stage > 1 else ' is'} at a stage this "
                     "bromigOS doesn't know, shown as Working.")
    if unknown_outcome:
        notes.append(f"{unknown_outcome} finished {NOUN}{'s have' if unknown_outcome > 1 else ' has'} an outcome this "
                     f"bromigOS doesn't know, and {'are' if unknown_outcome > 1 else 'is'}n't shown.")
    if skipped:
        notes.append(f"{skipped} entr{'ies' if skipped > 1 else 'y'} in the feed {'are' if skipped > 1 else 'is'} not "
                     f"in a shape this bromigOS knows, and {'are' if skipped > 1 else 'is'}n't shown.")

    windows = feed.get("counts") if isinstance(feed.get("counts"), dict) else {}
    counts = {lane: lanes[lane]["count"] for lane, _title in LANES if lane != "done"}
    for name in ("today", "seven_days"):
        w = windows.get(name) if isinstance(windows.get(name), dict) else {}
        counts[name] = {k: _int(w.get(k)) for k in _COUNTS}
    counts["merged_today"] = counts["today"]["merged"]
    warned = feed.get("warnings") if isinstance(feed.get("warnings"), list) else []
    more = _int(omitted.get("warnings")) or 0
    warnings = [w for w in (clean(x, 300) for x in warned) if w] + ([f"and {more} more warnings the feed left out"]
                                                                      if more else []) + notes
    written = _moment(feed.get("generated_at"))
    ignored = _int(feed.get("ignored"))
    return {"schema": SCHEMA, "noun": NOUN, "business": clean(feed.get("business"), 60) or "?",
            "control_repo": feed["control_repo"] if isinstance(feed.get("control_repo"), str)
            and _REPO.fullmatch(feed["control_repo"]) else "", "url": _link(feed.get("tick_url")),
            "state": chk["state"], "fresh": chk["fresh"],
            "headline": headline(counts, chk, clean(feed.get("headline"), 200) if isinstance(feed.get("headline"), str) else ""),
            "generated_at": chk["generated_at"], "stale_after": chk["stale_after"],
            "updated": _when(written, now, zone), "age_s": chk["age_s"], "age": chk["age"], "timezone": zone_name,
            "driver": feed.get("driver") if feed.get("driver") in ("heartbeat", "schedule") else None,
            "ignored": ignored if ignored is not None else left_alone,
            "lanes": list(lanes.values()) + list(extra.values()), "counts": counts,
            "accounts": [_account(e, now, zone) for e in _entries(feed, "accounts")],
            "schedules": [_schedule(e, now, zone) for e in _entries(feed, "schedules")], "warnings": warnings}


# ------------------------------------------------------------------ reading: GitHub, through gh
def _gh(args, timeout=30, what="it"):
    """gh's standard output, with the user's own login. ReadError says what's wrong in plain words.
    what: the thing being read, for those words."""
    exe = shutil.which("gh")
    if not exe:
        raise ReadError("no-gh", "gh, GitHub's command, isn't installed: install github-cli, then run gh auth login")
    env = dict(os.environ, GH_PROMPT_DISABLED="1", GH_NO_UPDATE_NOTIFIER="1", NO_COLOR="1")
    try:
        p = subprocess.run([exe] + list(args), capture_output=True, text=True, timeout=timeout, env=env,
                           stdin=subprocess.DEVNULL)
    except subprocess.TimeoutExpired:
        raise ReadError("failed", f"gh didn't answer in {timeout} s") from None
    except OSError as e:
        raise ReadError("failed", f"gh could not run: {clean(e, 120)}") from None
    if p.returncode == 0:
        return p.stdout
    said = clean(p.stderr or p.stdout or "no message", 160)
    if p.returncode == 4 or "gh auth login" in said or "HTTP 401" in said:
        raise ReadError("signed-out", "gh isn't signed in to GitHub: run gh auth login")
    if "rate limit" in said.lower():
        raise ReadError("failed", "GitHub's rate limit for your login is used up: it reads again within the hour")
    if "HTTP 404" in said or "HTTP 403" in said:
        raise ReadError("no-access", f"your gh login can't read {what}, or it doesn't exist: gh auth status says "
                                     "who you are signed in as")
    raise ReadError("failed", f"gh could not read {what}: {said}")


def read_github(repo, label=STATE_LABEL, timeout=30):
    """The feed in `repo`'s Status issue, through `gh api` and the user's own gh login. `repo` is the
    control repository, owner/name. Among the issues that carry `label` (open or closed), the one
    titled exactly `Status` that the fleet's job opened holds the feed. ReadError otherwise: gh isn't
    installed, isn't signed in, can't see the repository, or the repository has no Status issue yet."""
    if not isinstance(repo, str) or not _REPO.fullmatch(repo):
        raise ReadError("failed", "the control repository must be written owner/name, like my-org/agents")
    if not isinstance(label, str) or not _LABEL.fullmatch(label):
        raise ReadError("failed", "the state label may hold letters, digits, dots, dashes and underscores only")
    out = _gh(["api", "--paginate", f"repos/{repo}/issues?labels={label}&state=all&per_page=100"], timeout, repo)
    issues, at, decoder = [], 0, json.JSONDecoder()         # with --paginate, gh prints one list per page
    try:
        while at < len(out):
            if out[at].isspace():
                at += 1
                continue
            page, at = decoder.raw_decode(out, at)
            issues += page if isinstance(page, list) else []
    except (ValueError, RecursionError):
        raise ReadError("failed", "gh didn't answer with JSON") from None
    titled = [i for i in issues if isinstance(i, dict) and i.get("title") == STATUS_TITLE]
    for issue in titled:
        if ((issue.get("user") or {}).get("login") if isinstance(issue.get("user"), dict) else None) != STATUS_AUTHOR:
            continue
        try:
            return parse_body(issue.get("body") or "")
        except FeedError as e:
            raise ReadError("bad-feed", f"the Status issue (#{_int(issue.get('number')) or '?'}) of {repo} holds no "
                                        f"feed to read: {e}") from None
    if titled:
        raise ReadError("no-issue", f"{repo} has an issue titled Status, but the fleet's job didn't open it "
                                    f"({STATUS_AUTHOR} does), so it isn't read")
    raise ReadError("no-issue", f"{repo} has no Status issue yet: the fleet's job writes it on its first run")


# ------------------------------------------------------------------ reading: your lab's status mirror, over HTTP
def read_envelope(doc):
    """The feeds in a status mirror's answer, {"schema": 1, "feeds": [{"business", "received_at",
    "feed"}, …]}: one entry per feed, {"business", "received_at", "feed"}, or {"business",
    "received_at", "error"} for a feed this version can't read. `business` is the mirror's name
    for it. An empty list is a mirror that has no report yet. ReadError for anything else."""
    if not isinstance(doc, dict) or isinstance(doc.get("schema"), bool) or doc.get("schema") != SCHEMA \
            or not isinstance(doc.get("feeds"), list):
        raise ReadError("bad-feed", 'the mirror\'s answer is not {"schema": 1, "feeds": […]}')
    out = []
    for entry in doc["feeds"]:
        if not isinstance(entry, dict):
            continue
        one = {"business": clean(entry.get("business"), 60) or "?", "received_at": _iso(_moment(entry.get("received_at")))}
        try:
            one["feed"] = validate(entry.get("feed"))
        except FeedError as e:
            one["error"] = str(e)
        out.append(one)
    return out


def fetch_url(url, timeout=8, headers=None, context=None, etag=None):
    """(entries, etag) from your lab's status mirror: GET `url` (…/v1/feed), read by read_envelope.
    With `etag`, an earlier answer's, an unchanged answer (304) gives (None, etag). ReadError when
    the mirror doesn't answer or answers something else."""
    if not isinstance(url, str) or not re.match(r"^https?://[^\s/]+", url):
        raise ReadError("failed", "the mirror's address must start with http:// or https://")
    asked = {"Accept": "application/json", **(headers or {}), **({"If-None-Match": etag} if etag else {})}
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers=asked), timeout=timeout, context=context) as r:
            raw, tag = r.read(MAX_BYTES + 1), r.headers.get("ETag")
    except urllib.error.HTTPError as e:
        code = e.code
        e.close()
        if code == 304 and etag:
            return None, etag
        if code in (401, 403):
            raise ReadError("no-access", f"the mirror refused the request (HTTP {code}): check the source's "
                                         "auth_ref") from None
        raise ReadError("failed", f"the mirror answered HTTP {code}") from None
    except (OSError, ValueError) as e:
        raise ReadError("failed", f"the mirror didn't answer: {clean(getattr(e, 'reason', e), 120)}") from None
    if len(raw) > MAX_BYTES:
        raise ReadError("bad-feed", "the mirror's answer is larger than any feed")
    try:
        doc = json.loads(raw.decode("utf-8"))
    except (ValueError, RecursionError):
        raise ReadError("bad-feed", "the mirror didn't answer with JSON") from None
    return read_envelope(doc), tag if isinstance(tag, str) and len(tag) <= 200 and clean(tag, 200) == tag else None


def read_url(url, timeout=8, headers=None, context=None):
    """The feeds your lab's status mirror holds (fetch_url without an etag): one entry per feed."""
    return fetch_url(url, timeout, headers, context)[0]


# ------------------------------------------------------------------ one read a minute
_cache, _lock = {}, threading.Lock()


def cached(key, read, ttl=CACHE_SECONDS, clock=time.monotonic):
    """read()'s answer, kept for `ttl` seconds under `key`: the dashboard refreshes every 15 s and the
    Lab deck every 10 s, and neither should ask GitHub that often. A ReadError is kept as long."""
    with _lock:
        hit = _cache.get(key)
    if hit and clock() - hit[0] < ttl:
        if hit[2] is not None:
            raise ReadError(hit[2].kind, str(hit[2]))
        return hit[1]
    try:
        value, error = read(), None
    except ReadError as e:
        value, error = None, e
    with _lock:
        _cache[key] = (clock(), value, error)
    if error is not None:
        raise error
    return value


def forget():
    """Drop every kept answer (tests; a process that wants a fresh read)."""
    with _lock:
        _cache.clear()


# ------------------------------------------------------------------ the Tasks card
def _accounts_words(v):
    return "; ".join(f"account {a['number'] if a['number'] is not None else '?'}: {a['phrase']}" for a in v["accounts"])


def _fleet_hint(v):
    bits = [f"{v['business']}: {v['headline']}",
            f"updated {v['updated']} ({v['timezone']})" if v["updated"] else "the feed doesn't say when it was written"]
    if v["accounts"]:
        bits.append(_accounts_words(v))
    today = v["counts"]["today"]
    if any(n is not None for n in today.values()):
        bits.append("today: " + ", ".join(f"{today[k]} {k}" for k in _COUNTS if today[k] is not None))
    bits += [f"warning: {w}" for w in v["warnings"][:3]]
    return " · ".join(bits)


def _task_hint(row):
    return " · ".join(b for b in (f"{row['label']}: {row['phrase']}", row["title"], row["why"],
                                  f"since {row['when']}" if row["when"] else "", row["url"]) if b)


def card(result, visible=None):
    """The Tasks card (console.register_card's build) from the `tasks` capability's Result: per
    business a row with its headline, then the tasks that need you, the proposed ones and the ones
    being worked on, at most CARD_ROWS of them, then "+N more". visible(rec): [console] hide."""
    result = result or {}
    fleets = [r for r in result.get("items") or [] if r.get("kind") == "fleet"]
    errors = result.get("errors") or {}
    items, read = [], []

    def ok(row):
        return visible is None or visible({"name": row["label"], "repo": row["repo"]})
    for f in fleets:
        v = f.get("view")
        if not isinstance(v, dict):                 # a mirror's feed this version can't read
            items.append({"name": f.get("name") or "?", "task": f.get("name") or "?", "phrase": "Not read",
                          "title": f.get("error") or "", "since": "", "state": "warn", "kind": "fleet",
                          "hint": f"{f.get('name') or '?'}: {f.get('error') or 'the feed could not be read'}"})
            continue
        read.append(v)
        items.append({"name": v["business"], "task": v["business"], "phrase": v["headline"],
                      "title": " · ".join(p for p in (f"updated {v['updated']}" if v["updated"] else "",
                                                      _accounts_words(v)) if p),
                      "since": "", "state": "ok" if v["fresh"] else "warn", "kind": "fleet", "business": v["business"],
                      "url": v["url"], "hint": _fleet_hint(v)})
        by = {lane["id"]: lane for lane in v["lanes"]}
        left = {lane: by[lane]["count"] - sum(1 for r in by[lane]["rows"] if not ok(r))
                for lane in ("needs_you", "proposed", "working", "waiting")}
        for r in [r for lane in ("needs_you", "proposed", "working") for r in by[lane]["rows"] if ok(r)][:CARD_ROWS]:
            left[r["lane"]] -= 1
            items.append({"name": r["label"], "task": r["label"], "phrase": r["phrase"], "title": r["title"],
                          "since": r["when"], "state": {"needs_you": "warn", "working": "ok"}.get(r["lane"], "unknown"),
                          "kind": "task", "lane": r["lane"], "business": v["business"], "repo": r["repo"],
                          "number": r["number"], "url": r["url"], "hint": _task_hint(r)})
        n = sum(left.values())
        if n > 0:
            words = " · ".join(f"{left[lane]} {word}" for lane, word in (("needs_you", "need you"), ("proposed", "proposed"),
                                                                        ("working", "working"), ("waiting", "waiting"))
                               if left[lane] > 0)
            items.append({"name": f"+{n} more", "task": f"+{n} more", "phrase": words, "title": "bromigos lab tasks",
                          "since": "", "state": "unknown", "kind": "more", "business": v["business"],
                          "hint": f"{n} more {NOUN}{'s' if n != 1 else ''} of {v['business']} ({words}): bromigos lab "
                                  f"tasks lists every {NOUN} with its links"})
    if len(fleets) == 1 and len(read) == 1 and not errors:
        summary = read[0]["headline"]
    elif read and len(read) == len(fleets) and not errors and all(v["fresh"] for v in read):
        # several businesses, every one read and fresh: their tasks added up
        total = {k: sum(v["counts"].get(k) or 0 for v in read)
                 for k in ("needs_you", "proposed", "working", "waiting", "merged_today")}
        summary = f"{headline(total, _FRESH)} · {len(read)} businesses"
    else:                                           # each says its own; "Nothing needs you" is never added up
        summary = "; ".join([f"{v['business']}: {v['headline']}" for v in read] +
                            [f"{i['name']}: not read" for i in items if i["phrase"] == "Not read"])
    return {"columns": ["task", "phrase", "title", "since"], "items": items, "summary": summary}


# ------------------------------------------------------------------ plain text, for a terminal
def render_text(v, width=80, everything=False):
    """One business's picture in plain text, at most `width` columns (an address is never broken,
    so a very long one can stand out): the headline, then each lane's tasks with their links.
    Done is collapsed: a count, the newest DONE_ROWS merged tasks and the work that ended without
    a merge, a line each. everything: every finished task and each schedule's links, in full."""
    width = max(40, int(width))

    def wrap(text, indent="", hang=None):
        hang = indent if hang is None else hang
        return textwrap.wrap(text, width=width, initial_indent=indent, subsequent_indent=hang, break_long_words=True,
                             break_on_hyphens=False) if text else []

    def task(row, word="since"):
        meta = [f"{word} {row['when']}" if row["when"] else "", row["why"],
                f"account {row['account']}" if row["account"] is not None else "",
                f"attempt {row['attempt']}" if row["attempt"] else "",
                f"{row['turns']} turns" if row["turns"] is not None else "",
                f"{max(1, round(row['minutes']))} min" if row["minutes"] is not None else "",
                "reviewed by " + " and ".join(row["reviewers"]) if row["reviewers"] else ""]
        out = wrap(f"{row['label']}  {row['phrase']}", "  ", "        ") + wrap(row["title"], "      ")
        out += wrap(" · ".join(m for m in meta if m), "      ")
        out += ["      " + row["url"]] if row["url"] else []
        return out + [f"      {link['text']}: {link['url']}" for link in row["links"]]

    def line(row):
        text = "  " + " · ".join(p for p in (f"{row['label']}  {row['phrase']}", row["when"], row["title"]) if p)
        return [text if len(text) <= width else text[:width - 1].rstrip() + "…"]

    lines = wrap(f"{v['business'].upper()} · {v['headline']}", "", "  ")
    where = " · ".join(p for p in (f"Updated {v['updated']} ({v['timezone']})" if v["updated"] else
                                   "The feed doesn't say when it was written", v["control_repo"]) if p)
    lines += wrap(where, "", "  ")
    if not v["fresh"]:
        lines += wrap("What follows is the last picture the fleet's job wrote. No update means it isn't running: it is "
                      "switched off, disabled or failing.", "", "  ")
    if v["accounts"]:
        lines += wrap("Accounts: " + " · ".join(f"{a['number'] if a['number'] is not None else '?'} {a['phrase']}"
                                               for a in v["accounts"]), "", "  ")
    for lane in v["lanes"]:
        rows, events = lane["rows"], lane["events"]
        if not rows and not events and not lane["omitted"]:
            continue
        if lane["id"] != "done":
            lines += ["", f"{lane['title'].upper()} ({lane['count']})"]
            for row in rows:
                lines += task(row, "filed" if lane["id"] == "proposed" else "since")
            if lane["omitted"]:
                lines += wrap(f"+{lane['omitted']} more the feed left out for room", "  ")
            continue
        today, week = v["counts"]["merged_today"], v["counts"]["seven_days"]["merged"]
        head = " · ".join(p for p in (f"{today} merged today" if today is not None else "",
                                      f"{week} in 7 days" if week is not None else "") if p) or f"{len(rows)} merged"
        lines += ["", f"{lane['title'].upper()} ({head})"]
        for row in rows if everything else rows[:DONE_ROWS]:
            lines += task(row, "at") if everything else line(row)
        for row in events if everything else events[:DONE_ROWS]:
            lines += task(row, "at") if everything else line(row)
        hidden = max(0, len(rows) - DONE_ROWS) + max(0, len(events) - DONE_ROWS)
        if not everything:
            lines += wrap((f"+{hidden} more · " if hidden else "") + "bromigos lab tasks --all lists them with their "
                          "links", "  ")
    if v["schedules"]:
        lines += ["", "SCHEDULES"]
        for sch in v["schedules"]:
            lines += wrap(" · ".join(p for p in (
                sch["name"] or sch["id"], sch["when"], f"next {sch['next']}" if sch["next"] else "",
                (f"last run {sch['last']}" + (f": {sch['last_words']}" if sch["last_words"] else "")) if sch["last"]
                else "no run seen") if p), "  ", "      ")
            if everything:
                lines += [f"      {text}: {url}" for text, url in [("run", sch["url"]), ("digest", sch["digest_url"])] +
                          [(t["label"], t["url"]) for t in sch["tickets"]] if url]
    for name, words in (("today", "Today"), ("seven_days", "7 days")):
        w = v["counts"][name]
        if any(n is not None for n in w.values()):
            lines += ([""] if name == "today" else []) + wrap(f"{words}: " + " · ".join(
                f"{w[k] if w[k] is not None else '?'} {k}" for k in _COUNTS), "", "  ")
    if v["ignored"]:
        lines += wrap(f"{v['ignored']} more that the fleet leaves alone {'is' if v['ignored'] == 1 else 'are'}n't shown.",
                      "", "  ")
    if v["warnings"]:
        lines += ["", "WARNINGS"]
        for w in v["warnings"]:
            lines += wrap(w, "  ! ", "    ")
    return "\n".join(lines) + "\n"


# ------------------------------------------------------------------ bromigos lab tasks
SETUP = """No task source yet. Add your fleet's control repository to ~/.config/bromigos/homelab.toml:

    [[source]]
    name = "tasks"
    type = "fleet"
    repo = "my-org/agents"

Or look at one now: bromigos lab tasks --repo my-org/agents (docs/lab.md, "Tasks")."""


def assemble(fleets, errors, configured=True, now=None):
    """The document every Tasks screen reads, from the pictures (view() of each feed, with its
    `source`) and what couldn't be read: {"schema": 1, "generatedAt", "configured", "state",
    "fleets": [view + {"source"}, …], "errors": {source: why}}. state: ok (every feed read and
    fresh, nothing needs you), warn (something needs you, or a feed is stale or switched off),
    unreachable (no feed could be read) or empty (no source). `bromigos lab tasks --json` prints
    it, and the Lab board's GET /api/fleet answers it."""
    now = _now(now)
    bad = any(not v["fresh"] or v["counts"]["needs_you"] for v in fleets)
    state = "empty" if not configured else "unreachable" if not fleets else "warn" if bad or errors else "ok"
    return {"schema": SCHEMA, "generatedAt": int(now.timestamp()), "configured": bool(configured), "state": state,
            "fleets": list(fleets), "errors": dict(errors)}


def document(adapters, now=None):
    """assemble() of what each `fleet` source reads now (adapters/labfleet.py)."""
    now = _now(now)
    fleets, errors = [], {}
    for a in adapters:
        try:
            for one in a.views(now):
                if one.get("view"):
                    fleets.append(dict(one["view"], source=a.name))
                else:
                    errors[f"{a.name}: {one.get('business') or '?'}"] = one.get("error") or "the feed could not be read"
        except ReadError as e:
            errors[a.name] = str(e)
    return assemble(fleets, errors, bool(adapters), now)


def main(argv=None, prog="bromigos lab tasks"):
    """bromigos lab tasks [--json] [--all] [--width N] [--repo OWNER/NAME | --url URL]. Exit 0 when
    every feed was read, is fresh and nothing needs you (and always with --json, like bromigos lab
    status); 1 when something needs you, a feed is stale or switched off, or one could not be read."""
    p = argparse.ArgumentParser(prog=prog, description="What your fleet of coding agents is doing: every task, by "
                                                       "lane, with its links. Read-only.")
    p.add_argument("--json", action="store_true", help="print the document instead (docs/lab.md, Tasks)")
    p.add_argument("--all", action="store_true", help="list every merged task, not the newest three")
    p.add_argument("--width", type=int, default=80, help="columns of the plain-text picture (default 80)")
    p.add_argument("--repo", metavar="OWNER/NAME", help="read this control repository instead of homelab.toml's "
                                                        "fleet sources (through your gh login)")
    p.add_argument("--url", help="read your lab's status mirror at this address instead of homelab.toml's fleet "
                                 "sources")
    a = p.parse_args(argv)
    from . import registry
    from .adapters import labfleet
    if a.repo or a.url:
        adapters = [labfleet.Fleet({"name": a.repo or "mirror", "type": "fleet", "repo": a.repo, "url": a.url})]
    else:
        adapters = registry.providers("tasks")
    doc = document(adapters)
    if a.json:
        print(json.dumps(doc, indent=1))
        return 0
    if not adapters:
        print(SETUP)
        return 0
    for n, v in enumerate(doc["fleets"]):
        sys.stdout.write(("\n" + "-" * 40 + "\n\n" if n else "") + render_text(v, a.width, a.all))
    for source, why in doc["errors"].items():
        print(("\n" if doc["fleets"] else "") + "\n".join(textwrap.wrap(f"{clean(source, 80)}: {clean(why, 400)}",
                                                                      width=max(40, a.width), subsequent_indent="  ")),
              file=sys.stderr)
    return 0 if doc["state"] == "ok" else 1
