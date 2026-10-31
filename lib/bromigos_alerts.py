"""bromigOS's alerts (docs/alerts.md): small checks that find what needs a person, written
as one JSON document that BRODEC's machine agent sends to the owner's phone, and that the
desktop shows as a notification.

  run_pass(env, scope, boot)    run the checks of one pass ("system" as root, "user" as you),
                                keep each alert's first-seen time, write the document
  read_merged(env)              this computer's alerts: the system document and yours
  notify(env)                   the desktop notifications, with their dedup and cooldown

The checks themselves are in bromigos_alerts_checks. Every path and command goes through an
Env, so a test gives a stand-in root, stand-in commands on PATH and a fixed clock.

Files:
  /var/lib/bromigos/alerts/system.json      the system pass (root, 0644)
  /var/lib/bromigos/alerts/state.json       its first-seen times
  ~/.local/state/bromigos/alerts/user.json  the user pass (0600), with state.json beside it
  ~/.local/state/bromigos/alerts/notified.json   what the desktop already showed
  /etc/bromigos/alerts.toml                 the settings (every key optional)
  /etc/bromigos/alerts.d/, ~/.config/bromigos/alerts.d/   your own checks
"""

import hashlib
import json
import os
import re
import stat
import subprocess
import time
import tomllib

SCHEMA = 1
SEVERITIES = ("info", "needs_you", "critical")
RANK = {s: i for i, s in enumerate(SEVERITIES)}
ACTION_KINDS = {"restart", "update", "fix", "snooze", "open", "run", "link"}
ID_OK = re.compile(r"[^A-Za-z0-9._:/@+-]")
MAX_ID, MAX_TITLE, MAX_DETAIL = 160, 120, 600
MAX_LINES, MAX_LINE, MAX_EVIDENCE = 40, 300, 4000
CUSTOM_TIMEOUT = 30

SYSTEM_DOC = "/var/lib/bromigos/alerts/system.json"
SYSTEM_STATE = "/var/lib/bromigos/alerts/state.json"
SETTINGS = "/etc/bromigos/alerts.toml"
SYSTEM_CUSTOM = "/etc/bromigos/alerts.d"

DEFAULTS = {
    "disk": {"full_percent": 90, "critical_percent": 97, "ignore": []},
    "units": {"ignore": []},
    "checks": {"off": []},
    "game": {"units": []},
}

# the desktop notification's cooldown before the same alert shows again, and how many a run shows
COOLDOWN_MS = {"critical": 6 * 3600_000, "needs_you": 24 * 3600_000}
NOTIFY_PER_RUN = 3
# a resolved alert's record is kept this long, so one that flaps doesn't show again at once
NOTIFIED_KEEP_MS = 30 * 60_000


class Skip(Exception):
    """The check doesn't apply here (no UPS, not a Server, the tool isn't installed)."""


class Failed(Exception):
    """The check couldn't look; its earlier alerts stay as they were."""


# ------------------------------------------------------------------ the environment

class Env:
    """Where the checks look and what they run. BROMIGOS_ALERTS_ROOT puts every file the
    checks read and the system pass writes under a stand-in root; commands come from PATH,
    then the root's /usr/lib/bromigos/bin. BROMIGOS_ALERTS_NOW_MS fixes the clock."""

    def __init__(self, environ=None):
        e = dict(os.environ if environ is None else environ)
        self.environ = e
        self.root = e.get("BROMIGOS_ALERTS_ROOT") or "/"
        self.home = e.get("HOME") or os.path.expanduser("~")
        self.state_home = e.get("XDG_STATE_HOME") or os.path.join(self.home, ".local/state")
        self.config_home = e.get("XDG_CONFIG_HOME") or os.path.join(self.home, ".config")
        self.fixed_now = int(e["BROMIGOS_ALERTS_NOW_MS"]) if e.get("BROMIGOS_ALERTS_NOW_MS") else None
        self.custom_timeout = float(e.get("BROMIGOS_ALERTS_CUSTOM_TIMEOUT") or CUSTOM_TIMEOUT)
        self.statvfs_file = e.get("BROMIGOS_ALERTS_STATVFS")
        owner = e.get("BROMIGOS_ALERTS_OWNER_UID")
        self.trusted_uid = int(owner) if owner not in (None, "") else None

    @property
    def stand_in(self):
        return self.root != "/"

    def now_ms(self):
        return self.fixed_now if self.fixed_now is not None else int(time.time() * 1000)

    def path(self, p):
        return os.path.join(self.root, p.lstrip("/")) if self.stand_in else p

    def read(self, p, default=None):
        try:
            with open(self.path(p), errors="replace") as f:
                return f.read()
        except OSError:
            return default

    def exists(self, p):
        return os.path.exists(self.path(p))

    def listdir(self, p):
        try:
            return sorted(os.listdir(self.path(p)))
        except OSError:
            return []

    def find(self, name):
        for d in (self.environ.get("PATH") or "/usr/bin:/bin").split(":") + [self.path("/usr/lib/bromigos/bin")]:
            p = os.path.join(d, name)
            if d and os.path.isfile(p) and os.access(p, os.X_OK):
                return p
        return None

    def run(self, argv, timeout=60, input=None):
        """(exit status, stdout, stderr); a missing command is 127, a timeout 124."""
        exe = argv[0] if os.path.isabs(argv[0]) else self.find(argv[0])
        if not exe:
            return 127, "", f"{argv[0]}: not installed"
        env = {k: v for k, v in self.environ.items()}
        env.setdefault("LC_ALL", "C")
        try:
            r = subprocess.run([exe, *argv[1:]], capture_output=True, text=True, timeout=timeout, input=input,
                               env=env, stdin=None if input is not None else subprocess.DEVNULL, errors="replace")
            return r.returncode, r.stdout, r.stderr
        except subprocess.TimeoutExpired:
            return 124, "", f"{argv[0]}: no answer within {int(timeout)} s"
        except OSError as e:
            return 127, "", f"{argv[0]}: {e}"

    def statvfs(self, mount):
        """(total, free, available) bytes. A test gives them in a JSON file."""
        if self.statvfs_file:
            with open(self.statvfs_file) as f:
                v = json.load(f).get(mount)
            if v is None:
                raise OSError(f"no stand-in numbers for {mount}")
            return int(v["total"]), int(v["free"]), int(v["avail"])
        s = os.statvfs(mount)
        return s.f_blocks * s.f_frsize, s.f_bfree * s.f_frsize, s.f_bavail * s.f_frsize

    def is_root(self):
        return os.geteuid() == 0

    # where each pass keeps its files
    def doc_path(self, scope):
        return self.path(SYSTEM_DOC) if scope == "system" else os.path.join(self.state_home, "bromigos/alerts/user.json")

    def state_path(self, scope):
        return self.path(SYSTEM_STATE) if scope == "system" else os.path.join(self.state_home, "bromigos/alerts/state.json")

    def notified_path(self):
        return os.path.join(self.state_home, "bromigos/alerts/notified.json")

    def custom_dir(self, scope):
        return self.path(SYSTEM_CUSTOM) if scope == "system" else os.path.join(self.config_home, "bromigos/alerts.d")


def role(env):
    """desktop, server or fieldkit."""
    if env.exists("/etc/bromigos-fieldkit/medium") or env.exists("/run/archiso/bootmnt"):
        return "fieldkit"
    if env.exists("/usr/share/bromigos/server") or env.exists("/usr/lib/bromigos/server/bromigos-server"):
        return "server"
    return "desktop"


def settings(env):
    out = {k: dict(v) for k, v in DEFAULTS.items()}
    text = env.read(SETTINGS)
    if text:
        try:
            data = tomllib.loads(text)
        except tomllib.TOMLDecodeError:
            data = {}
        for section, values in data.items():
            if section in out and isinstance(values, dict):
                out[section].update(values)
    return out


# ------------------------------------------------------------------ files

def read_json(path, default=None):
    try:
        with open(path) as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def write_json(path, doc, mode=0o644, dir_mode=0o755):
    """Atomically: a reader never sees half a file."""
    d = os.path.dirname(path)
    os.makedirs(d, mode=dir_mode, exist_ok=True)
    tmp = f"{path}.tmp.{os.getpid()}"
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, mode)
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(doc, f, indent=1, sort_keys=True)
            f.write("\n")
            f.flush()
            os.fsync(f.fileno())
        os.chmod(tmp, mode)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


# ------------------------------------------------------------------ an alert

def slug(text, n=48):
    s = re.sub(r"[^a-z]+", "-", text.lower()).strip("-")
    return s[:n].rstrip("-") or hashlib.sha256(text.encode()).hexdigest()[:8]


def alert(check, subject, severity, title, detail, source, actions=None, evidence=None, fix=None, link=None):
    """One alert as SPEC.md has it; `since` is filled in by the pass."""
    return {"id": f"{check}:{subject}" if subject else check, "check": check, "severity": severity,
            "title": title, "detail": detail, "source": source, "subject": subject or "",
            "actions": actions if actions is not None else [{"kind": "fix", "label": "Fix it"}, {"kind": "snooze"},
                                                            {"kind": "open"}],
            "evidence": evidence or {"lines": [], "facts": {}}, "fix": fix, "link": link}


def evidence(lines=(), **facts):
    return {"lines": [str(x) for x in lines if str(x).strip()], "facts": {k: str(v) for k, v in facts.items()}}


def _cut(text, n):
    text = " ".join(str(text or "").split()) if n <= MAX_TITLE else str(text or "").strip()
    return text if len(text) <= n else text[: n - 1].rstrip() + "…"


def normalise(a, check=None):
    """The shape and limits SPEC.md sets, whatever a check (or a custom one) gave."""
    a = dict(a)
    if check:
        a["check"] = check
    sev = a.get("severity")
    if sev not in RANK:
        raise ValueError(f"severity must be one of {', '.join(SEVERITIES)}")
    if not str(a.get("title") or "").strip():
        raise ValueError("an alert needs a title")
    a["id"] = ID_OK.sub("-", str(a.get("id") or a["check"]))[:MAX_ID]
    a["title"] = _cut(a["title"], MAX_TITLE)
    a["detail"] = _cut(a.get("detail") or "", MAX_DETAIL)
    a["source"] = _cut(a.get("source") or "bromigOS", 40)
    a["subject"] = _cut(a.get("subject") or "", 120)
    acts = []
    for x in a.get("actions") or []:
        if isinstance(x, dict) and x.get("kind") in ACTION_KINDS:
            acts.append({k: str(v) for k, v in x.items() if k in ("kind", "label", "command", "url") and v})
    a["actions"] = acts
    ev = a.get("evidence") if isinstance(a.get("evidence"), dict) else {}
    lines, total = [], 0
    for line in (ev.get("lines") or [])[-MAX_LINES:]:
        line = str(line).rstrip()[:MAX_LINE]
        total += len(line)
        if total > MAX_EVIDENCE:
            break
        lines.append(line)
    facts = {str(k)[:40]: str(v)[:200] for k, v in list((ev.get("facts") or {}).items())[:20]}
    a["evidence"] = {"lines": lines, "facts": facts}
    fx = a.get("fix")
    if isinstance(fx, dict) and fx.get("commands"):
        a["fix"] = {"commands": [str(c)[:400] for c in fx["commands"][:12]],
                    "touches": [str(t)[:200] for t in (fx.get("touches") or [])[:12]],
                    "from": str(fx.get("from") or "bromigos"), "root": bool(fx.get("root")),
                    "note": _cut(fx.get("note") or "", 300)}
    else:
        a["fix"] = None
    a["link"] = str(a["link"]) if a.get("link") else None
    if "since" in a and not isinstance(a["since"], int):
        a.pop("since")
    return {k: a[k] for k in ("id", "check", "severity", "title", "detail", "source", "subject", "since",
                              "actions", "evidence", "fix", "link") if k in a}


# ------------------------------------------------------------------ custom checks

def trusted(path, uid):
    """Its file and folder belong to `uid` and no one else may write them."""
    for p in (path, os.path.dirname(path)):
        try:
            st = os.stat(p)
        except OSError:
            return False
        if st.st_uid != uid or st.st_mode & (stat.S_IWGRP | stat.S_IWOTH):
            return False
    return True


def custom_checks(env, scope):
    """[(name, path)] of the executables in this pass's alerts.d."""
    d = env.custom_dir(scope)
    try:
        names = sorted(os.listdir(d))
    except OSError:
        return []
    out = []
    for n in names:
        p = os.path.join(d, n)
        if n.startswith(".") or n.endswith((".disabled", "~", ".bak")) or not os.path.isfile(p):
            continue
        out.append((re.sub(r"[^A-Za-z0-9_-]+", "-", n.rsplit(".", 1)[0] if "." in n else n), p))
    return out


def run_custom(env, scope, name, path):
    """A custom check's alerts. Raises Failed with why."""
    uid = env.trusted_uid if env.trusted_uid is not None else (0 if scope == "system" else os.getuid())
    if not trusted(path, uid):
        raise Failed(f"{path} isn't used: it and its folder must belong to "
                     f"{'root' if uid == 0 else 'you'} and be writable by no one else")
    if not os.access(path, os.X_OK):
        raise Failed(f"{path} isn't executable (chmod +x)")
    rc, out, err = env.run([path], timeout=env.custom_timeout)
    if rc == 124:
        raise Failed(f"{name} gave no answer within {int(env.custom_timeout)} s")
    if rc != 0:
        raise Failed(f"{name} exited with {rc}: {(err.strip().splitlines() or [''])[-1][:200]}")
    try:
        doc = json.loads(out)
    except ValueError:
        raise Failed(f"{name} didn't print a JSON document")
    check = f"custom.{name}"
    found = []
    for i, a in enumerate(doc.get("alerts") or [] if isinstance(doc, dict) else []):
        if not isinstance(a, dict):
            continue
        own = ID_OK.sub("-", str(a.get("id") or a.get("subject") or i))
        a = dict(a, id=f"{check}:{own}", check=check)
        a.setdefault("source", name)
        try:
            found.append(normalise(a, check))
        except ValueError as e:
            raise Failed(f"{name}: {e}")
    return found


# ------------------------------------------------------------------ a pass

def run_pass(env, scope, boot=False, checks=None):
    """Run every check of this pass and write its document. Returns the document. One pass of a
    scope at a time (the boot pass and the timer's may meet): the second waits for the first."""
    import fcntl
    lock = env.doc_path(scope) + ".lock"
    os.makedirs(os.path.dirname(lock), mode=0o755 if scope == "system" else 0o700, exist_ok=True)
    with open(lock, "a") as held:
        fcntl.flock(held, fcntl.LOCK_EX)
        return _run_pass(env, scope, boot, checks)


def _run_pass(env, scope, boot, checks):
    from bromigos_alerts_checks import REGISTRY
    conf = settings(env)
    off = set(conf["checks"].get("off") or [])
    prev = read_json(env.doc_path(scope), {}) or {}
    prev_alerts = [a for a in prev.get("alerts") or [] if isinstance(a, dict)]
    prev_checks = {c.get("check"): c for c in prev.get("checks") or [] if isinstance(c, dict)}
    ctx = Context(env, scope, conf, role(env), boot, prev_alerts)
    now = env.now_ms()
    rows, alerts = [], []

    def kept(name):
        return [a for a in prev_alerts if a.get("check") == name]

    todo = [(c.name, c) for c in REGISTRY if scope in c.passes and (checks is None or c.name in checks)]
    todo += [(f"custom.{n}", (n, p)) for n, p in custom_checks(env, scope)
             if checks is None or f"custom.{n}" in checks]
    for name, c in todo:
        row = {"check": name, "state": "ran", "error": None, "ran_at": now}
        try:
            if name in off:
                raise Skip("turned off in /etc/bromigos/alerts.toml")
            if isinstance(c, tuple):
                found = run_custom(env, scope, *c)
            elif c.boot_only and not boot:
                # looked at the last boot: what it found stands until the next one
                old = prev_checks.get(name) or {}
                if old.get("state") == "failed":
                    row.update(state="failed", error=old.get("error"))
                elif old.get("state") == "skipped":
                    row.update(state="skipped", error=old.get("error"))
                row["ran_at"] = old.get("ran_at") or now
                found = kept(name)
            else:
                found = [normalise(a, name) for a in c.fn(ctx)]
        except Skip as e:
            row.update(state="skipped", error=str(e) or None)
            found = []
        except Failed as e:
            row.update(state="failed", error=str(e))
            found = kept(name)
        except Exception as e:  # a check's own bug never stops the others
            row.update(state="failed", error=f"the check broke: {type(e).__name__}: {e}"[:300])
            found = kept(name)
        rows.append(row)
        alerts.extend(found)
    # one alert per id: the higher severity wins
    by_id = {}
    for a in alerts:
        if a["id"] not in by_id or RANK[a["severity"]] > RANK[by_id[a["id"]]["severity"]]:
            by_id[a["id"]] = a
    # first seen: kept across runs for as long as the alert stays
    state = read_json(env.state_path(scope), {}) or {}
    since = state.get("since") or {}
    new_since = {}
    for a in by_id.values():
        a["since"] = int(since.get(a["id"]) or a.get("since") or now)
        new_since[a["id"]] = a["since"]
    order = sorted(by_id.values(), key=lambda a: (-RANK[a["severity"]], a["since"], a["id"]))
    doc = {"schema": SCHEMA, "scope": scope, "role": ctx.role, "checked_at": now, "checks": rows, "alerts": order}
    if checks is not None:
        # a partial run (one check): the others stand as they were
        doc["checks"] = [r for n, r in prev_checks.items() if n not in {x["check"] for x in rows}] + rows
        doc["alerts"] = sorted([a for a in prev_alerts if a.get("check") not in {x["check"] for x in rows}] + order,
                               key=lambda a: (-RANK.get(a.get("severity"), 0), a.get("since", 0), a.get("id", "")))
        new_since = dict(since, **new_since)
    system = scope == "system"
    write_json(env.state_path(scope), {"since": new_since}, 0o644 if system else 0o600, 0o755 if system else 0o700)
    write_json(env.doc_path(scope), doc, 0o644 if system else 0o600, 0o755 if system else 0o700)
    return doc


class Context:
    """What a check gets: the environment, the settings, the role, whether it's the boot pass,
    and the pass's previous alerts (for hysteresis)."""

    def __init__(self, env, scope, conf, role_, boot, prev):
        self.env, self.scope, self.settings, self.role, self.boot = env, scope, conf, role_, boot
        self._prev = prev

    def previous(self, check):
        return {a["id"]: a for a in self._prev if a.get("check") == check and "id" in a}


# ------------------------------------------------------------------ reading

def read_merged(env):
    """This computer's alerts, the system pass's and yours, one per id, worst first."""
    docs = [read_json(env.doc_path("system")), read_json(env.doc_path("user"))]
    by_id, checks = {}, []
    out = {"schema": SCHEMA, "checks": checks, "alerts": [], "system_checked_at": None, "user_checked_at": None}
    for scope, d in zip(("system", "user"), docs):
        if not isinstance(d, dict):
            continue
        out[f"{scope}_checked_at"] = d.get("checked_at")
        out.setdefault("role", d.get("role"))
        for c in d.get("checks") or []:
            checks.append(dict(c, scope=scope))
        for a in d.get("alerts") or []:
            if a.get("severity") not in RANK:
                continue
            if a["id"] not in by_id or RANK[a["severity"]] > RANK[by_id[a["id"]]["severity"]]:
                by_id[a["id"]] = a
    out["alerts"] = sorted(by_id.values(), key=lambda a: (-RANK[a["severity"]], a.get("since", 0), a["id"]))
    return out


WORDS = {"critical": "CRITICAL", "needs_you": "NEEDS YOU", "info": "info"}


def plain(doc, now_ms):
    lines = []
    alerts = doc["alerts"]
    if not alerts:
        lines.append("Nothing needs you on this computer.")
    for a in alerts:
        lines.append(f"{WORDS[a['severity']]:<9}  {a['title']}  ({a['source']}, {ago(now_ms - a.get('since', now_ms))})")
        if a.get("detail"):
            lines.append(f"           {a['detail']}")
        if a.get("fix"):
            lines.append(f"           Fix: {' && '.join(a['fix']['commands'][:2])}")
    failed = [c for c in doc["checks"] if c.get("state") == "failed"]
    for c in failed:
        lines.append(f"couldn't check {c['check']}: {c.get('error') or '?'}")
    if doc.get("system_checked_at") is None:
        lines.append("The system checks haven't run yet (bromigos-alerts.timer, as root).")
    return "\n".join(lines)


def ago(ms):
    s = max(0, int(ms // 1000))
    for n, unit in ((86400, "d"), (3600, "h"), (60, "min")):
        if s >= n:
            return f"{s // n} {unit} ago"
    return "just now"


# ------------------------------------------------------------------ the desktop notification

def graphical(env):
    return bool(env.environ.get("WAYLAND_DISPLAY") or env.environ.get("DISPLAY"))


def notify(env, send=None):
    """Show what needs you as desktop notifications: needs-you and critical alerts, once each
    (again after the cooldown, or when one gets worse), at most NOTIFY_PER_RUN a run, the rest
    as "and N more". Returns what it showed, as [(title, body, urgency)]."""
    if send is None:
        exe = env.find("notify-send")
        if not exe or not graphical(env):
            return []

        def send(title, body, urgency):
            env.run([exe, "--app-name=bromigOS", f"--urgency={urgency}", "--category=device.error",
                     "--icon=dialog-warning", title, body], timeout=10)
    now = env.now_ms()
    seen = read_json(env.notified_path(), {}) or {}
    alerts = [a for a in read_merged(env)["alerts"] if a["severity"] in ("needs_you", "critical")]
    live = {a["id"] for a in alerts}
    # resolved ones are kept a little while: an alert that flaps doesn't show again at once
    for k in list(seen):
        if k not in live:
            rec = seen[k]
            rec.setdefault("gone_at", now)
            if now - rec["gone_at"] > NOTIFIED_KEEP_MS:
                del seen[k]
        else:
            seen[k].pop("gone_at", None)
    due = []
    for a in alerts:
        rec = seen.get(a["id"])
        if (rec is None or RANK[a["severity"]] > RANK.get(rec.get("severity"), 0)
                or now - int(rec.get("at", 0)) >= COOLDOWN_MS[a["severity"]]):
            due.append(a)
    shown = []
    if due:
        alone = due if len(due) <= NOTIFY_PER_RUN else due[: NOTIFY_PER_RUN - 1]
        for a in alone:
            body = a.get("detail") or ""
            if a.get("fix") or any(x.get("kind") == "fix" for x in a.get("actions") or []):
                body += "\nbromigos alerts lists it; BRODEC on your phone can ask VECTOR to fix it."
            shown.append((a["title"], body.strip(), "critical" if a["severity"] == "critical" else "normal"))
        rest = due[len(alone):]
        if rest:
            worst = "critical" if any(a["severity"] == "critical" for a in rest) else "normal"
            shown.append((f"And {len(rest)} more alert{'s' if len(rest) != 1 else ''} on this computer",
                          "; ".join(a["title"] for a in rest[:4]) + ("…" if len(rest) > 4 else "")
                          + "\nbromigos alerts lists them all.", worst))
        for title, body, urgency in shown:
            send(title, body, urgency)
        for a in due:
            seen[a["id"]] = {"severity": a["severity"], "at": now}
    write_json(env.notified_path(), seen, 0o600, 0o700)
    return shown
