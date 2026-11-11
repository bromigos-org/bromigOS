"""bromigOS's outbound notifications (docs/alerts.md, "Channels"): the alerts, and opt-in
job results and the model catalogue's review, sent to Discord and to any signed webhook.

  channels(env)                 the channels in /etc/bromigos/alerts.toml, defaults filled in
  rows(env)                     what `bromigos alerts channels list` shows: no secret, only set or not set
  deliver(env)                  the timer's run: what is due, for each channel, sent
  test(env, name)               one message marked TEST through a channel
  add(env, kind, name, …), remove(env, name)   the settings and the secrets, as root
  kick(root, environ)           start the delivery now (an activity job that needs you or ended)

One library for every source, so alerts, jobs and the catalogue follow the same rules: each
channel's severities, sources, quiet hours, detail level and rate limit; one message when an
alert opens or gets worse, again after 6 hours when it's critical, and (if asked) when it
clears. Nothing counts as sent until the channel took it, so a retry carries what is true then.

BROMIGOS_ALERTS_ROOT puts every file under a stand-in root (bromigos_alerts.Env).

Files:
  /etc/bromigos/alerts.toml                  [notify] and [channels.NAME]: the settings (0644)
  /etc/bromigos/alerts-channels/NAME.url     a channel's address (0600, folder 0700, root's)
  /etc/bromigos/alerts-channels/NAME.key     a webhook's signing key (0600)
  /var/lib/bromigos/alerts/channels/NAME.json   what was sent when, backoff, the last error (0644)
"""

import fcntl
import hashlib
import hmac
import json
import os
import re
import secrets
import socket
import subprocess
import threading
import time
import tomllib
import urllib.error
import urllib.request
import uuid

import bromigos_alerts as A

SCHEMA = 1
SECRET_DIR = "/etc/bromigos/alerts-channels"
STATE_DIR = "/var/lib/bromigos/alerts/channels"
SEND_UNIT = "bromigos-alerts-send.service"
CATALOGUES = ("/usr/share/bromigos/homelab/lab/models.toml", "/usr/share/bromigos-lab/models.toml")
BRODEC_MARKS = ("/etc/brodec-machine/machine.toml", "/usr/bin/brodec-machine", "/usr/lib/brodec-machine")

TYPES = ("discord", "webhook")
DETAILS = ("minimal", "full")
# where an alert comes from, as a channel picks it; `alerts` is every one of them
ALERT_SOURCES = ("drives", "disk-space", "updates", "backups", "go-bag", "power", "services", "game-servers",
                 "app-data", "field-kit", "steam", "failed-jobs", "custom", "other")
EVENT_SOURCES = ("job-results", "catalogue")       # opt-in: never part of `alerts`
SOURCES = ALERT_SOURCES + EVENT_SOURCES
BY_CHECK = {"disk.smart": "drives", "disk.scrub": "drives", "disk.full": "disk-space", "update.waiting": "updates",
            "update.restart": "updates", "update.held": "updates", "backup.restic": "backups", "power.ups": "power",
            "systemd.failed": "services", "server.game": "game-servers", "server.app-data": "app-data",
            "fieldkit.finding": "field-kit", "game.steam": "steam", "activity.job": "failed-jobs"}
DEFAULT = {"on": True, "severities": ["critical", "needs_you"], "sources": ["alerts"], "quiet": "",
           "critical_in_quiet": False, "resolved": False, "per_hour": 10}
DEFAULT_DETAIL = {"discord": "minimal", "webhook": "full"}   # a Discord server can be shared

REMIND_MS = {"critical": 6 * 3600_000}             # a critical alert again after 6 hours
FLAP_MS = 30 * 60_000                              # cleared and back within 30 min: no new message
HOUR_MS = 3600_000
TRIES, PAUSES, MAX_WAIT, TIMEOUT = 3, (1, 2), 10, 10
BACKOFF_MAX_MS = 60 * 60_000
DISCORD_EMBEDS = 4                                 # per message, well under Discord's 6000 characters
WEBHOOK_EVENTS = 20
COLOUR = {"critical": 0xE5484D, "needs_you": 0xF5A524, "info": 0x3E9FFF, "ok": 0x30A46C}
WORD = {"critical": "Critical", "needs_you": "Needs you", "info": "Info"}
NAME_OK = re.compile(r"^[a-z0-9][a-z0-9_-]{0,31}$")
DISCORD_URL = re.compile(r"^https://(?:(?:ptb|canary)\.)?discord(?:app)?\.com/api/webhooks/\d+/[A-Za-z0-9_.-]+$")
QUIET = re.compile(r"^([01]\d|2[0-3]):([0-5]\d)-([01]\d|2[0-3]):([0-5]\d)$")
USER_AGENT = "bromigOS-alerts/1"


class NotifyError(Exception):
    """A wrong setting or command, said in words."""


# ------------------------------------------------------------------ settings

def _toml(env):
    text = env.read(A.SETTINGS)
    if not text:
        return {}
    try:
        return tomllib.loads(text)
    except tomllib.TOMLDecodeError:
        return {}


def board(env):
    """The Lab board's address, when the owner set one ([notify] board)."""
    b = str((_toml(env).get("notify") or {}).get("board") or "").strip()
    return b if re.match(r"^https?://[^\s]+$", b) else None


def channel_conf(name, raw):
    """One [channels.NAME] table with its defaults, and what's wrong with it (`problems`)."""
    kind = str(raw.get("type") or name)
    c = dict(DEFAULT, name=name, type=kind, problems=[])
    c["detail"] = DEFAULT_DETAIL.get(kind, "minimal")
    for k in ("on", "critical_in_quiet", "resolved"):
        if k in raw:
            c[k] = bool(raw[k])
    if raw.get("detail") in DETAILS:
        c["detail"] = raw["detail"]
    elif "detail" in raw:
        c["problems"].append(f"detail is minimal or full, not {raw['detail']!r}")
    for k, ok in (("severities", A.SEVERITIES), ("sources", SOURCES + ("alerts",))):
        if k in raw:
            vals = [str(v) for v in raw[k]] if isinstance(raw[k], list) else []
            bad = [v for v in vals if v not in ok]
            if bad:
                c["problems"].append(f"{k}: {', '.join(bad)} unknown")
            c[k] = [v for v in vals if v in ok]
    if raw.get("quiet"):
        if QUIET.match(str(raw["quiet"])):
            c["quiet"] = str(raw["quiet"])
        else:
            c["problems"].append(f"quiet is HH:MM-HH:MM, not {raw['quiet']!r}")
    if "per_hour" in raw:
        try:
            c["per_hour"] = max(1, min(120, int(raw["per_hour"])))
        except (TypeError, ValueError):
            c["problems"].append("per_hour is a number")
    if kind not in TYPES + ("brodec",):
        c["problems"].append(f"type is discord or webhook, not {kind!r}")
    if not NAME_OK.match(name):
        c["problems"].append("a name is lowercase letters, digits, - and _")
    return c


def channels(env):
    """[conf] for every [channels.NAME] in the settings, BRODEC's left out (it is read-only here)."""
    out = []
    for name, raw in (_toml(env).get("channels") or {}).items():
        if isinstance(raw, dict) and str(raw.get("type") or name) != "brodec":
            out.append(channel_conf(str(name), raw))
    return out


def sources_of(conf):
    want = set(conf["sources"])
    if "alerts" in want:
        want |= set(ALERT_SOURCES)
    return want


def source_of(a):
    """Which source an alert counts as: its check's, with the Go Bag's own."""
    check, aid = str(a.get("check") or ""), str(a.get("id") or "")
    if check == "backup.restic" and str(a.get("subject") or "").startswith("server-drive"):
        return "go-bag"
    if check == "activity.job" and aid.startswith("activity.job:backup.drive"):
        return "go-bag"
    if check.startswith("custom."):
        return "custom"
    return BY_CHECK.get(check, "other")


def in_quiet(conf, now_ms):
    """Whether now (local time) is in the channel's quiet hours; 22:00-07:00 runs over midnight."""
    m = QUIET.match(conf.get("quiet") or "")
    if not m:
        return False
    a, b = int(m[1]) * 60 + int(m[2]), int(m[3]) * 60 + int(m[4])
    t = time.localtime(now_ms / 1000)
    now = t.tm_hour * 60 + t.tm_min
    return (a <= now < b) if a < b else (now >= a or now < b) if a != b else False


# ------------------------------------------------------------------ secrets

def _secret_file(env, name, part):
    return env.path(f"{SECRET_DIR}/{name}.{part}")


def secret_state(env, name, part):
    """"set", "not set", or "unknown" (only root may look)."""
    try:
        os.stat(_secret_file(env, name, part))
        return "set"
    except FileNotFoundError:
        return "not set"
    except OSError:
        return "unknown"


def read_secret(env, name, part):
    try:
        with open(_secret_file(env, name, part)) as f:
            return f.read().strip() or None
    except OSError:
        return None


def write_secret(env, name, part, value):
    d = env.path(SECRET_DIR)
    os.makedirs(d, mode=0o700, exist_ok=True)
    os.chmod(d, 0o700)
    path = _secret_file(env, name, part)
    tmp = f"{path}.tmp.{os.getpid()}"
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        f.write(value + "\n")
    os.replace(tmp, path)


# ------------------------------------------------------------------ what never leaves the machine

_LAN = [re.compile(r"\b(?:10(?:\.\d{1,3}){3}|192\.168(?:\.\d{1,3}){2}|172\.(?:1[6-9]|2\d|3[01])(?:\.\d{1,3}){2}"
                   r"|169\.254(?:\.\d{1,3}){2}|100\.(?:6[4-9]|[7-9]\d|1[01]\d|12[0-7])(?:\.\d{1,3}){2})(?::\d{1,5})?\b"),
        re.compile(r"(?<![\w:])(?:f[cd][0-9a-f]{2}|fe80):[0-9a-f:]*[0-9a-f](?:%\w+)?", re.I)]


def scrub(text):
    """Text with what looks like a secret (bromigos_activity.redact) or a LAN address taken out."""
    from bromigos_activity import redact
    text = redact(str(text or ""))
    for rule in _LAN:
        text = rule.sub("[address]", text)
    return text


def _scrub_all(v):
    if isinstance(v, str):
        return scrub(v)
    if isinstance(v, list):
        return [_scrub_all(x) for x in v]
    if isinstance(v, dict):
        return {k: _scrub_all(x) for k, x in v.items()}
    return v


def machine_name(env):
    name = (env.read("/etc/hostname") or "").strip()
    if not name and not env.stand_in:
        name = socket.gethostname()
    return name.split(".")[0][:64] or "this computer"


def ref(text):
    """A stable stand-in for an id in a minimal message: the same alert, the same ref."""
    return hashlib.sha256(str(text).encode()).hexdigest()[:16]


# ------------------------------------------------------------------ what is due: events

def _event(kind, severity, source, title, sentence="", subject="", since=None, fix=(), key="", alert=None, job=None,
           commit=None):
    return {"kind": kind, "severity": severity, "source": source, "title": title, "sentence": sentence,
            "subject": subject, "since": since, "fix": list(fix), "key": key, "alert": alert, "job": job,
            "commit": commit or (lambda: None)}


def alert_events(conf, st, doc, now):
    """The alerts this channel takes, from the system pass's document, against what it sent."""
    rec = st.setdefault("alerts", {})
    if not isinstance(doc, dict):
        return []                                  # no document: nothing opened, nothing cleared
    want_sev, want_src = set(conf["severities"]), sources_of(conf)
    live = {a["id"]: a for a in doc.get("alerts") or []
            if isinstance(a, dict) and a.get("id") and a.get("severity") in want_sev and source_of(a) in want_src}
    out = []
    for aid, a in live.items():
        r, sev = rec.get(aid), a["severity"]
        kind = None
        if r is None or r.get("resolved_sent"):
            kind = "alert.opened"
        elif A.RANK[sev] > A.RANK.get(r.get("severity"), 0):
            kind = "alert.worse"
        elif sev in REMIND_MS and now - int(r.get("at") or 0) >= REMIND_MS[sev]:
            kind = "alert.reminder"
        if r is not None and kind is None:         # back within the flap window, or milder: no message
            r.pop("gone_at", None)
            r["severity"] = sev
        if kind is None:
            continue

        def commit(a=a):
            rec[a["id"]] = {"severity": a["severity"], "at": now, "title": a.get("title", ""),
                            "source": source_of(a), "subject": a.get("subject", ""), "since": a.get("since")}
        fix = (a.get("fix") or {}).get("commands") or [x["command"] for x in a.get("actions") or [] if x.get("command")]
        body = {k: v for k, v in a.items() if k != "evidence"}         # evidence is what the machine read: never sent
        out.append(_event(kind, sev, source_of(a), a.get("title", ""), a.get("detail", ""), a.get("subject", ""),
                          a.get("since"), fix[:3], aid, alert=body, commit=commit))
    for aid, r in list(rec.items()):
        if aid in live:
            continue
        r.setdefault("gone_at", now)
        if conf["resolved"] and not r.get("resolved_sent"):
            def commit(r=r):
                r["resolved_sent"] = True
            out.append(_event("alert.resolved", r.get("severity", "info"), r.get("source", "other"),
                              r.get("title", ""), "It cleared by itself.", r.get("subject", ""), r.get("since"),
                              key=aid, commit=commit))
        elif now - r["gone_at"] > FLAP_MS:
            del rec[aid]
    return out


def job_events(env, conf, st, now):
    """Activity jobs (docs/activity.md) that finished, failed or wait for an answer, from when the
    channel first took job-results. Only what every user may read: the record, never its log."""
    if "job-results" not in conf["sources"]:
        st.pop("jobs", None)
        st.pop("jobs_from", None)
        return []
    import bromigos_activity as J
    jenv = J.Env(dict(env.environ, BROMIGOS_ROOT=env.root) if env.stand_in else env.environ)
    start = st.setdefault("jobs_from", now)
    seen = st.setdefault("jobs", {})
    if not os.path.isdir(jenv.jobs_dir()):
        return []
    out, ids = [], set()
    for r in J.list_jobs(jenv):
        ids.add(r["id"])
        state, q = r.get("state"), r.get("question") or {}
        if state == "succeeded":
            kind, sev, title = "job.succeeded", "info", f"A job finished: {r['title']}"
            sentence = "It finished."
        elif state in ("failed", "rolled-back"):
            kind, sev = "job.failed", "needs_you" if state == "failed" else "info"
            title = f"A job failed: {r['title']}"
            sentence = ((r.get("error") or {}).get("words") or "It stopped without saying why.") + (
                " It put things back the way they were." if state == "rolled-back" else "")
        elif state == "needs-you" and q:
            kind, sev, title = "job.needs-you", "needs_you", f"A job needs you: {r['title']}"
            sentence = f"It asks: {q.get('text', '')}"
        else:
            continue
        when = r.get("ended_at") or q.get("asked_at") or r.get("updated_at") or 0
        mark = f"{state}:{q.get('id', '')}:{q.get('asked_at', '')}"
        if when < start or seen.get(r["id"]) == mark:
            continue

        def commit(i=r["id"], mark=mark):
            seen[i] = mark
        job = {"id": r["id"], "kind": r.get("kind"), "title": r["title"], "state": state,
               "question": {"text": q.get("text"), "choices": [c.get("id") for c in q.get("choices") or []]} if q else None}
        out.append(_event(kind, sev, "job-results", title, sentence, "", r.get("started_at"),
                          [f"bromigos activity show {r['id']}"], f"job:{r['id']}", job=job, commit=commit))
    for i in [i for i in seen if i not in ids]:
        del seen[i]
    return out


def catalogue_events(env, conf, st, now):
    """New models waiting for review in the installed lab catalogue (the weekly review)."""
    if "catalogue" not in conf["sources"]:
        st.pop("catalogue", None)
        return []
    path = next((env.path(p) for p in CATALOGUES if env.exists(p)), None)
    if not path:
        return []
    try:
        with open(path, "rb") as f:
            pending = [p for p in tomllib.load(f).get("pending") or []
                       if isinstance(p, dict) and p.get("id") and p.get("state") == "pending review"]
    except (OSError, tomllib.TOMLDecodeError):
        return []
    ids = sorted({str(p["id"]) for p in pending})
    if "catalogue" not in st:                      # the first look: what is there is known already
        st["catalogue"] = ids
        return []
    known = set(st["catalogue"])
    new = [p for p in pending if str(p["id"]) not in known]
    if not new:
        st["catalogue"] = ids
        return []

    def commit():
        st["catalogue"] = ids
    n = len(new)
    names = "; ".join(str(p.get("title") or p["id"]) for p in new[:5]) + ("…" if n > 5 else "")
    return [_event("catalogue.review", "info", "catalogue",
                   f"{n} new model{'s' if n != 1 else ''} to review in the lab's model catalogue", names,
                   since=now, fix=["bromigos lab models refresh"], key=f"catalogue:{ref(','.join(ids))}", commit=commit)]


# ------------------------------------------------------------------ the messages

def _plural(n, one, many):
    return one if n == 1 else many


def summary(events):
    """Minimal detail: what happened, counted, with nothing about the machine."""
    lines = []
    al = [e for e in events if e["kind"] in ("alert.opened", "alert.worse", "alert.reminder", "test")]
    loud = [e for e in al if e["severity"] != "info"]
    crit = sum(1 for e in al if e["severity"] == "critical")
    if loud:
        n = len(loud)
        lines.append(f"{n} {_plural(n, 'alert needs', 'alerts need')} you on your lab"
                     + (f" ({crit} critical)" if crit else ""))
    elif al:
        lines.append(f"{len(al)} new {_plural(len(al), 'alert', 'alerts')} on your lab")
    for kind, one, many in (("alert.resolved", "alert on your lab cleared", "alerts on your lab cleared"),
                            ("job.needs-you", "job on your lab waits for your answer", "jobs on your lab wait for your answer"),
                            ("job.failed", "job on your lab failed", "jobs on your lab failed"),
                            ("job.succeeded", "job on your lab finished", "jobs on your lab finished")):
        n = sum(1 for e in events if e["kind"] == kind)
        if n:
            lines.append(f"{n} {_plural(n, one, many)}")
    if any(e["kind"] == "catalogue.review" for e in events):
        lines.append("New models to review in your lab's model catalogue")
    return lines


def _worst(events):
    sev = [e["severity"] for e in events if e["kind"] != "alert.resolved"]
    return max(sev, key=lambda s: A.RANK[s]) if sev else "ok"


PREFIX = {"alert.worse": "Worse: ", "alert.reminder": "Still there: ", "alert.resolved": "Cleared: "}
WHERE = "Act on it in BRODEC or on the Lab board: nothing can be done from here."


def discord_payloads(events, conf, ctx):
    """Discord's incoming-webhook bodies: [(events, body)], embeds only, mentions off."""
    mark = "TEST · " if ctx.get("test") else ""
    look = f"Open the Lab board: {ctx['board']}" if ctx.get("board") else "Open BRODEC, or run `bromigos alerts` on the server."
    out = []
    if conf["detail"] == "minimal":
        lines = summary(events)
        embed = {"title": (mark + lines[0])[:256], "description": "\n".join(lines[1:] + ["", look, WHERE]).strip()[:2000],
                 "color": COLOUR[_worst(events)], "footer": {"text": "bromigOS"}, "timestamp": _iso(ctx["now"])}
        if ctx.get("board"):
            embed["url"] = ctx["board"]
        return [(events, _discord_body([embed]))]
    for i in range(0, len(events), DISCORD_EMBEDS):
        chunk, embeds = events[i:i + DISCORD_EMBEDS], []
        for e in chunk:
            desc = scrub(e["sentence"])[:1200]
            if e["fix"] and e["kind"] != "alert.resolved":
                cmds = "\n".join(scrub(c).replace("```", "'''") for c in e["fix"])[:800]
                desc += f"\n```sh\n{cmds}\n```"
            fields = [{"name": "Machine", "value": ctx["machine"], "inline": True}]
            if e["subject"]:
                fields.append({"name": "Device" if e["source"] in ("drives", "disk-space") else "About",
                               "value": scrub(e["subject"])[:200], "inline": True})
            if e["since"]:
                fields.append({"name": "Since", "value": f"<t:{int(e['since']) // 1000}:R>", "inline": True})
            fields.append({"name": "Severity", "value": WORD.get(e["severity"], e["severity"]), "inline": True})
            embed = {"title": (mark + PREFIX.get(e["kind"], "") + scrub(e["title"]))[:256], "description": desc.strip(),
                     "color": COLOUR["ok" if e["kind"] == "alert.resolved" else e["severity"]], "fields": fields,
                     "footer": {"text": "bromigOS · " + WHERE}, "timestamp": _iso(ctx["now"])}
            if ctx.get("board"):
                embed["url"] = ctx["board"]
            embeds.append(embed)
        out.append((chunk, _discord_body(embeds)))
    return out


def _discord_body(embeds):
    return {"username": "bromigOS", "embeds": embeds, "allowed_mentions": {"parse": []}}


def _iso(ms):
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(ms / 1000))


def webhook_payloads(events, conf, ctx):
    """The signed webhook's bodies: [(events, body)], schema 1 (docs/alerts.md, "The webhook")."""
    full = conf["detail"] == "full"
    out = []
    for i in range(0, len(events), WEBHOOK_EVENTS):
        chunk = events[i:i + WEBHOOK_EVENTS]
        items = []
        for e in chunk:
            if full:
                item = {"event": e["kind"], "severity": e["severity"], "source": e["source"], "title": e["title"],
                        "sentence": e["sentence"], "subject": e["subject"], "since": e["since"], "fix": e["fix"]}
                if e["alert"] is not None:
                    item["alert"] = e["alert"]
                if e["job"] is not None:
                    item["job"] = e["job"]
                items.append(_scrub_all(item))
            else:
                items.append({"event": e["kind"], "severity": e["severity"], "source": e["source"],
                              "ref": ref(e["key"]), "since": e["since"]})
        body = {"schema": SCHEMA, "type": "bromigos.alerts", "test": bool(ctx.get("test")),
                "delivery": uuid.uuid4().hex, "sent_at": ctx["now"], "detail": conf["detail"],
                "machine": ctx["machine"] if full else None, "board": ctx.get("board"),
                "summary": summary(chunk), "events": items}
        out.append((chunk, body))
    return out


def sign(key, body):
    return "sha256=" + hmac.new(key.encode(), body, hashlib.sha256).hexdigest()


# ------------------------------------------------------------------ sending

class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k):
        return None                                # a webhook that moves is an error, never followed


def post(url, body, headers, timeout=TIMEOUT):
    """(status, retry-after seconds or None, why in words). 0 when nothing answered. The
    address is never part of `why`."""
    opener = urllib.request.build_opener(_NoRedirect)
    req = urllib.request.Request(url, data=body, headers=headers, method="POST")
    try:
        with opener.open(req, timeout=timeout) as r:
            return r.status, None, None
    except urllib.error.HTTPError as e:
        wait = e.headers.get("Retry-After") if e.headers else None
        e.close()
        try:
            wait = float(wait) if wait is not None else None
        except ValueError:
            wait = None
        return e.code, wait, f"the channel answered {e.code}" + {401: " (the address is no longer valid)",
                                                                  403: " (refused)", 404: " (the address is gone)",
                                                                  429: " (too many messages)"}.get(e.code, "")
    except (TimeoutError, socket.timeout):
        return 0, None, f"no answer within {timeout} s"
    except (urllib.error.URLError, OSError):
        return 0, None, "couldn't reach it (no network, or the name doesn't resolve)"


def send(url, body, headers, sleep, post_fn):
    """POST with retries: three tries, 1 s then 2 s apart (a 429's Retry-After up to 10 s). A
    4xx other than 429 isn't tried again. -> (ok, why)."""
    why = None
    for i in range(TRIES):
        status, wait, why = post_fn(url, body, headers)
        if 200 <= status < 300:
            return True, None
        if 400 <= status < 500 and status != 429:
            return False, why
        if i < TRIES - 1:
            sleep(min(MAX_WAIT, wait) if status == 429 and wait else PAUSES[i])
    return False, why


def _message(conf, env, name, events, ctx):
    """[(events, url, bytes, headers)] for the channel's type."""
    url = read_secret(env, name, "url")
    out = []
    if conf["type"] == "discord":
        for chunk, body in discord_payloads(events, conf, ctx):
            data = json.dumps(body).encode()
            out.append((chunk, url, data, {"Content-Type": "application/json", "User-Agent": USER_AGENT}))
    else:
        key = read_secret(env, name, "key") or ""
        for chunk, body in webhook_payloads(events, conf, ctx):
            data = json.dumps(body, sort_keys=True).encode()
            out.append((chunk, url, data, {"Content-Type": "application/json", "User-Agent": USER_AGENT,
                                           "X-Bromigos-Event": "test" if ctx.get("test") else "alerts",
                                           "X-Bromigos-Delivery": body["delivery"],
                                           "X-Bromigos-Schema": str(SCHEMA),
                                           "X-Bromigos-Signature-256": sign(key, data)}))
    return out


# ------------------------------------------------------------------ the delivery state

def state_path(env, name):
    return env.path(f"{STATE_DIR}/{name}.json")


def load_state(env, name):
    st = A.read_json(state_path(env, name), {})
    return st if isinstance(st, dict) else {}


def save_state(env, name, st):
    A.write_json(state_path(env, name), st, 0o644, 0o755)


def _failed(st, now, why):
    st["failures"] = int(st.get("failures") or 0) + 1
    st["retry_at"] = now + min(BACKOFF_MAX_MS, 60_000 * 2 ** (st["failures"] - 1))
    st["last_error"] = {"at": now, "why": why or "it failed"}


def _worked(st, now):
    st["failures"], st["retry_at"], st["last_ok"] = 0, 0, now
    st["sent"] = [t for t in st.get("sent") or [] if now - t < HOUR_MS] + [now]


ORDER = {"critical": 0, "needs_you": 1, "info": 2}


def deliver_channel(env, conf, doc, ctx, sleep=time.sleep, post_fn=post):
    """What is due for one channel, sent. -> a report row."""
    name, now = conf["name"], ctx["now"]
    row = {"channel": name, "type": conf["type"], "messages": 0, "events": 0, "held": 0, "why_held": None, "error": None}
    if not conf["on"]:
        row["why_held"] = "off"
        return row
    if conf["problems"]:
        row["error"] = "; ".join(conf["problems"])
        return row
    if not read_secret(env, name, "url"):
        row["error"] = f"its address is not set: sudo bromigos alerts channels add {conf['type']} {name}"
        return row
    st = load_state(env, name)
    events = alert_events(conf, st, doc, now) + job_events(env, conf, st, now) + catalogue_events(env, conf, st, now)
    events.sort(key=lambda e: (e["kind"] == "alert.resolved", ORDER.get(e["severity"], 3)))
    go = events
    if events and int(st.get("retry_at") or 0) > now:
        go, row["why_held"] = [], f"trying again after {time.strftime('%H:%M', time.localtime(st['retry_at'] / 1000))}"
    elif events and in_quiet(conf, now):
        go = [e for e in events if conf["critical_in_quiet"] and e["severity"] == "critical"
              and e["kind"] != "alert.resolved"]
        if len(go) < len(events):
            row["why_held"] = f"quiet hours ({conf['quiet']})"
    window = [t for t in st.get("sent") or [] if now - t < HOUR_MS]
    st["sent"] = window
    room = conf["per_hour"] - len(window)
    sent = []
    for chunk, url, data, headers in (_message(conf, env, name, go, ctx) if go else []):
        if room <= 0:
            row["why_held"] = row["why_held"] or f"the limit of {conf['per_hour']} messages an hour"
            break
        ok, why = send(url, data, headers, sleep, post_fn)
        if not ok:
            _failed(st, now, why)
            row["error"] = why
            break
        for e in chunk:
            e["commit"]()
        sent += chunk
        _worked(st, now)
        room -= 1
        row["messages"] += 1
    row["events"], row["held"] = len(sent), len(events) - len(sent)
    save_state(env, name, st)
    return row


def deliver(env, sleep=time.sleep, post_fn=post):
    """The delivery run (bromigos-alerts-send.service): every channel, one run at a time. A
    channel that fails never stops the others."""
    lock = env.path(STATE_DIR) + "/.lock"
    os.makedirs(os.path.dirname(lock), mode=0o755, exist_ok=True)
    with open(lock, "a") as held:
        fcntl.flock(held, fcntl.LOCK_EX)
        doc = A.read_json(env.doc_path("system"))
        ctx = {"now": env.now_ms(), "machine": machine_name(env), "board": board(env)}
        rows = []
        for conf in channels(env):
            try:
                rows.append(deliver_channel(env, conf, doc, ctx, sleep, post_fn))
            except Exception as e:  # one channel's bug never stops the others
                rows.append({"channel": conf["name"], "type": conf["type"], "messages": 0, "events": 0, "held": 0,
                             "why_held": None, "error": f"broke: {type(e).__name__}"})
        return rows


def test(env, name, sleep=time.sleep, post_fn=post):
    """One message marked TEST through channel `name`, past quiet hours and the rate limit.
    -> (ok, why)."""
    conf = next((c for c in channels(env) if c["name"] == name), None)
    if conf is None:
        raise NotifyError(f"no channel {name!r}: bromigos alerts channels lists them")
    if conf["problems"]:
        raise NotifyError("; ".join(conf["problems"]))
    if not read_secret(env, name, "url"):
        raise NotifyError(f"its address is not set: sudo bromigos alerts channels add {conf['type']} {name}")
    now = env.now_ms()
    ctx = {"now": now, "machine": machine_name(env), "board": board(env), "test": True}
    e = _event("test", "info", "test", "Test message from bromigOS",
               "This channel works. Alerts from your lab will look like this.", "", now,
               ["bromigos alerts"], key="test")
    st = load_state(env, name)
    ok, why = False, None
    for _chunk, url, data, headers in _message(conf, env, name, [e], ctx):
        ok, why = send(url, data, headers, sleep, post_fn)
    if ok:
        st["last_ok"], st["failures"], st["retry_at"] = now, 0, 0
    else:
        st["last_error"] = {"at": now, "why": why or "it failed"}
    save_state(env, name, st)
    return ok, why


# ------------------------------------------------------------------ the list

def brodec_row(env):
    """BRODEC's phone: the machine agent reads the alerts itself (brodec docs/MACHINE_JOBS.md)."""
    there = any(env.exists(p) for p in BRODEC_MARKS) or bool(env.find("brodec-machine"))
    raw = (_toml(env).get("channels") or {}).get("brodec")
    wanted = None
    if isinstance(raw, dict):
        c = channel_conf("brodec", dict(raw, type="brodec"))
        wanted = {k: c[k] for k in ("severities", "sources", "quiet", "critical_in_quiet")}
    return {"name": "brodec", "type": "brodec", "label": "BRODEC (paired phone)", "read_only": True,
            "on": there, "installed": there,
            "rules": "BRODEC's own: needs-you and critical alerts, with buttons; quiet hours are set on the phone",
            "wanted": wanted, "applied": False}


def rows(env):
    """Each channel as `list` shows it, BRODEC's last. No address and no key, only whether set."""
    out = []
    for c in channels(env):
        st = load_state(env, c["name"])
        r = {k: c[k] for k in ("name", "type", "on", "detail", "severities", "sources", "quiet", "critical_in_quiet",
                               "resolved", "per_hour", "problems")}
        r.update(label={"discord": "Discord", "webhook": "Webhook"}.get(c["type"], c["type"]), read_only=False,
                 address=secret_state(env, c["name"], "url"),
                 key=secret_state(env, c["name"], "key") if c["type"] == "webhook" else None,
                 last_ok=st.get("last_ok"), last_error=st.get("last_error"),
                 retry_at=st.get("retry_at") or None,
                 sent_last_hour=len([t for t in st.get("sent") or [] if env.now_ms() - t < HOUR_MS]))
        out.append(r)
    out.append(brodec_row(env))
    return out


def document(env):
    """The `channels` section for `bromigos alerts --json` (the Lab board's Settings › Notifications)."""
    return {"schema": SCHEMA, "board": board(env), "sources": list(SOURCES), "opt_in": list(EVENT_SOURCES),
            "severities": list(A.SEVERITIES), "channels": rows(env)}


# ------------------------------------------------------------------ changing the settings

def _table_re(name):
    return re.compile(r"^\s*\[\s*channels\s*\.\s*" + re.escape(name) + r"\s*\]\s*(#.*)?$")


def _without(text, name):
    """The settings' text with [channels.NAME] (to the next table) taken out."""
    out, skip, head = [], False, _table_re(name)
    for line in text.splitlines():
        if head.match(line):
            skip = True
            continue
        if skip and re.match(r"^\s*\[", line):
            skip = False
        if not skip:
            out.append(line)
    while out and not out[-1].strip():
        out.pop()
    return "\n".join(out)


def _q(v):
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, int):
        return str(v)
    if isinstance(v, list):
        return "[" + ", ".join(_q(x) for x in v) + "]"
    return json.dumps(str(v))


def _write_settings(env, text):
    try:
        tomllib.loads(text)
    except tomllib.TOMLDecodeError as e:
        raise NotifyError(f"{A.SETTINGS} wouldn't read back ({e}); nothing changed")
    path = env.path(A.SETTINGS)
    os.makedirs(os.path.dirname(path), mode=0o755, exist_ok=True)
    tmp = f"{path}.tmp.{os.getpid()}"
    with open(tmp, "w") as f:
        f.write(text)
    os.chmod(tmp, 0o644)
    os.replace(tmp, path)


def check_address(kind, url):
    url = (url or "").strip()
    if kind == "discord":
        if not DISCORD_URL.match(url):
            raise NotifyError("that isn't a Discord webhook address: it starts https://discord.com/api/webhooks/ "
                              "(a channel's Settings › Integrations › Webhooks › Copy Webhook URL)")
    elif not re.match(r"^https?://[^\s/]+(/\S*)?$", url):
        raise NotifyError("a webhook address starts with https:// (or http:// on your own network)")
    return url


def add(env, kind, name, url, key=None, **opts):
    """Write [channels.NAME] and its secrets. Returns (conf, made_key)."""
    if kind not in TYPES:
        raise NotifyError("a channel is discord or webhook. BRODEC needs no channel: pair your phone in BRODEC")
    name = name or kind
    if name == "brodec" or not NAME_OK.match(name):
        raise NotifyError("a name is lowercase letters, digits, - and _, and not brodec")
    url = check_address(kind, url)
    table = {"type": kind}
    for k in ("on", "detail", "severities", "sources", "quiet", "critical_in_quiet", "resolved", "per_hour"):
        if opts.get(k) is not None:
            table[k] = opts[k]
    conf = channel_conf(name, table)
    if conf["problems"]:
        raise NotifyError("; ".join(conf["problems"]))
    made = False
    if kind == "webhook" and not key:
        key, made = secrets.token_hex(32), True
    text = _without(env.read(A.SETTINGS) or "", name)
    block = [f"[channels.{name}]"] + [f"{k} = {_q(v)}" for k, v in table.items()]
    _write_settings(env, (text + "\n\n" if text.strip() else "") + "\n".join(block) + "\n")
    write_secret(env, name, "url", url)
    if kind == "webhook":
        write_secret(env, name, "key", key)
    return conf, made


def remove(env, name):
    text = env.read(A.SETTINGS) or ""
    if name == "brodec":
        raise NotifyError("BRODEC isn't a channel here: unpair the phone in BRODEC")
    if not any(_table_re(name).match(line) for line in text.splitlines()):
        raise NotifyError(f"no channel {name!r}: bromigos alerts channels lists them")
    _write_settings(env, _without(text, name) + "\n")
    for part in ("url", "key"):
        try:
            os.unlink(_secret_file(env, name, part))
        except FileNotFoundError:
            pass
    try:
        os.unlink(state_path(env, name))
    except FileNotFoundError:
        pass


# ------------------------------------------------------------------ started by a job

def kick(root="/", environ=None, ended=False):
    """Start the delivery now without waiting for it: an activity job asks (for the channels
    that take job results), or ended and its alert was written (`ended`: for every channel
    that is on). Never raises; does nothing in a stand-in root unless a test names its own
    stand-in with BROMIGOS_NOTIFY_KICK."""
    e = dict(os.environ if environ is None else environ)
    stub = e.get("BROMIGOS_NOTIFY_KICK")
    try:
        if not stub and (root != "/" or os.geteuid() != 0):
            return False
        env = A.Env(dict(e, BROMIGOS_ALERTS_ROOT=root))
        if not any(c["on"] and (ended or "job-results" in c["sources"]) for c in channels(env)):
            return False
        argv = [stub] if stub else ["systemctl", "--no-block", "start", SEND_UNIT]
        p = subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                             start_new_session=True)
        threading.Thread(target=p.wait, daemon=True).start()     # reaped, never waited on
        return True
    except Exception:
        return False
