"""bromigOS's activity records (docs/activity.md): one record per long job, with named steps,
that the command line, a page and a phone can all read.

  run(env, …)                  start a command as a job: in its own transient systemd unit
                               (bromigos-job-<id>.service), or in the foreground where there is
                               no systemd; the caller follows it and may go away
  supervise(env, job, argv)    what runs inside the unit: the command's output becomes the log,
                               its `::` progress lines become the record
  parse(line)                  one house progress line (::stage, ::item, ::step, ::note, ::error)
  list_jobs(env), find(env, id), log_tail(env, record)     the readers; no privilege needed
  sweep(env)                   close the records a restart left running, drop what is past the bounds
  job(kind, title)             for a Python command: `with job(…) as j: j.step("copy", "Copying")`
  redact(text), redact_argv(argv)                          what keeps secrets out of a record

Files, under /var/lib/bromigos/activity/jobs/ (on bromigOS Server a link into the state
subvolume, /var/lib/bromigos/server/activity, so rolling the system back keeps them):
  <id>.json    the record (0644): written whole and atomically, only by the job's own process
  <id>.log     what the command printed, redacted (0640, root); <id>.log.1 is its older half
  <id>.lock    held for as long as the job's process lives; a reader that can take it knows
               the job is gone, and shows the record as interrupted
  <id>.spec    what a unit is to run (0600, root), removed as it starts

BROMIGOS_ROOT puts every file under a stand-in root, and commands come from PATH, so a test
gives a stand-in systemd-run and nothing real starts. BROMIGOS_ACTIVITY_NOW_MS fixes the clock;
BROMIGOS_ACTIVITY_RUNNER=systemd|foreground chooses how jobs run.
"""

import contextlib
import datetime as dt
import fcntl
import json
import os
import pwd
import re
import secrets
import select
import shlex
import shutil
import signal
import subprocess
import sys
import time

from bromigos_alerts import read_json, write_json

SCHEMA = 1
STATE_DIR = "/var/lib/bromigos/activity"
SERVER_STATE = "/var/lib/bromigos/server"          # bromigOS Server's state subvolume (docs/iso.md)
UNIT_PREFIX = "bromigos-job-"

STATES = ("queued", "running", "needs-you", "waiting", "succeeded", "failed", "rolled-back", "cancelled", "interrupted")
FINAL = ("succeeded", "failed", "rolled-back", "cancelled", "interrupted")
# the design's diagram, plus the ends a job can meet before it runs or while it waits
MOVES = {
    "queued": {"running", "failed", "cancelled", "interrupted"},
    "running": {"needs-you", "waiting", "succeeded", "failed", "rolled-back", "cancelled", "interrupted"},
    "needs-you": {"running", "failed", "cancelled", "interrupted"},
    "waiting": {"running", "failed", "cancelled", "interrupted"},
}
STEP_STATES = ("todo", "running", "waiting", "done", "failed", "skipped")
STEP_ENDS = ("done", "failed", "skipped")
VIA = ("board", "phone", "cli", "timer", "vector")
WAITING_FOR = ("network", "another job", "you", "drive")

# what an ::item's state means for a step (localprovision.py's states, and its stand-in's)
ITEM_STATES = {"waiting": "todo", "queued": "todo", "todo": "todo", "running": "running", "downloading": "running",
               "installing": "running", "done": "done", "failed": "failed", "skipped": "skipped",
               "skipped-offline": "waiting", "waiting-for-network": "waiting"}
OFFLINE = ("skipped-offline", "waiting-for-network")

# the bounds
KEEP_DAYS, KEEP_JOBS = 30, 200                     # finished jobs: both limits hold
MAX_STEPS, MAX_NOTES = 100, 20
MAX_TITLE, MAX_LABEL, MAX_DETAIL, MAX_WORDS, MAX_ID = 120, 120, 300, 600, 64
MAX_ARGS, MAX_ARG = 64, 256
RECORD_MAX = 64 * 1024                             # bytes of JSON
LOG_MAX = 2 * 1024 * 1024                          # bytes, in two halves (<id>.log and <id>.log.1)
LINE_MAX = 4096                                    # characters of one output line kept
ORPHAN_MS = 24 * 3600_000                          # a file with no record is dropped after this

SAVE_EVERY = 0.25                                  # seconds between writes that only move progress
STOP_GRACE = 15.0                                  # seconds a stopped command gets before SIGKILL
START_WAIT = 30.0                                  # seconds a unit gets to write its first record

KIND_OK = re.compile(r"^[a-z][a-z0-9-]*(\.[a-z][a-z0-9-]*)+$")
ID_OK = re.compile(r"^[a-z0-9][a-z0-9._-]*$")
JOB_ID_OK = re.compile(r"^\d{8}-\d{4}-[a-z0-9][a-z0-9.-]*-[0-9a-f]{4}$")


class ActivityError(Exception):
    """A problem to say in plain words (the command line prints it and exits 1)."""


# ------------------------------------------------------------------ the environment

class Env:
    """Where the records live and what gets run. BROMIGOS_ROOT is a stand-in root; commands
    come from PATH."""

    def __init__(self, environ=None):
        e = dict(os.environ if environ is None else environ)
        self.environ = e
        self.root = e.get("BROMIGOS_ROOT") or "/"
        self.fixed_now = int(e["BROMIGOS_ACTIVITY_NOW_MS"]) if e.get("BROMIGOS_ACTIVITY_NOW_MS") else None

    @property
    def stand_in(self):
        return self.root != "/"

    def now_ms(self):
        return self.fixed_now if self.fixed_now is not None else int(time.time() * 1000)

    def path(self, p):
        return os.path.join(self.root, p.lstrip("/")) if self.stand_in else p

    def is_root(self):
        return os.geteuid() == 0

    def needs_root(self):
        """Jobs are the system's: on a real root only root starts one."""
        return not self.stand_in and not self.is_root()

    def find(self, name):
        if os.path.isabs(name):
            return name if os.access(name, os.X_OK) else None
        return shutil.which(name, path=self.environ.get("PATH") or "/usr/bin:/bin")

    def boot_id(self):
        for p in (self.path("/proc/sys/kernel/random/boot_id"), "/proc/sys/kernel/random/boot_id"):
            try:
                with open(p) as f:
                    return f.read().strip()
            except OSError:
                continue
        return ""

    def dir(self):
        """The activity folder: the documented one, or the state subvolume's when the link to
        it isn't there (a rollback to before the first job)."""
        a, s = self.path(STATE_DIR), os.path.join(self.path(SERVER_STATE), "activity")
        return a if os.path.exists(a) or not os.path.isdir(s) else s

    def jobs_dir(self):
        return os.path.join(self.dir(), "jobs")

    def ensure_dir(self):
        """Make the folder (the job's process does, as root). On bromigOS Server it goes on the
        state subvolume, with the documented path a link to it."""
        a, server = self.path(STATE_DIR), self.path(SERVER_STATE)
        if not os.path.exists(a) and os.path.isdir(server):
            os.makedirs(os.path.join(server, "activity", "jobs"), mode=0o755, exist_ok=True)
            if not os.path.islink(a):
                with contextlib.suppress(FileExistsError):
                    os.symlink("server/activity", a)
        os.makedirs(self.jobs_dir(), mode=0o755, exist_ok=True)
        for d in (self.dir(), self.jobs_dir()):       # everyone reads the records, whatever the umask was
            with contextlib.suppress(OSError):
                if os.stat(d).st_mode & 0o777 != 0o755:
                    os.chmod(d, 0o755)
        return self.jobs_dir()

    def file(self, job_id, ext):
        if not JOB_ID_OK.match(job_id or ""):
            raise KeyError(f"no job {job_id!r}")
        return os.path.join(self.jobs_dir(), job_id + ext)

    def runner(self):
        """systemd, or foreground where there is none (a container, a test)."""
        want = self.environ.get("BROMIGOS_ACTIVITY_RUNNER")
        if want in ("systemd", "foreground"):
            return want
        return "systemd" if os.path.isdir(self.path("/run/systemd/system")) and self.find("systemd-run") else "foreground"


def elevation(env, tty):
    """What goes before a command that must be root: nothing for root, sudo in a terminal,
    pkexec (the session's polkit agent) without one. The rule the lab's network join uses."""
    if not env.needs_root():
        return []
    for tool in (("sudo", "pkexec") if tty else ("pkexec", "sudo")):
        if env.find(tool):
            return [tool]
    raise ActivityError("starting a job needs root, and neither sudo nor pkexec is installed")


# ------------------------------------------------------------------ keeping secrets out

_NAME = (r"(?:pass(?:word|wd|phrase)?|pwd|secret|token|api[-_]?key|apikey|access[-_]?key|secret[-_]?key|private[-_]?key"
         r"|client[-_]?secret|auth(?:orization)?|bearer|credentials?|cookie|session[-_]?id)")
_RULES = [
    # a URL's password; a secret in its query
    (re.compile(r"\b([a-z][a-z0-9+.-]{0,20}://[^/\s:@]{1,256}):[^/\s@]{1,512}@", re.I), r"\1:***@"),
    (re.compile(r"([?&](?:[\w.-]{0,80}?" + _NAME + r"|key|sig|signature)=)[^&\s]+", re.I), r"\1***"),
    (re.compile(r"\b(Bearer|Basic)\s+[A-Za-z0-9._~+/=-]{8,}"), r"\1 ***"),
    # name=value and name: value, where the name ends in a secret's word
    (re.compile(r"(" + _NAME + r")(\s{0,8}[=:]\s{0,8})(\"[^\"]*\"|'[^']*'|[^\s,;&]+)", re.I), r"\1\2***"),
    # tokens by their shape: GitHub, OpenAI-style, Slack, AWS, a JWT, age, Tailscale, Vault
    (re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}|sk-[A-Za-z0-9_-]{20,}"
                r"|xox[abprs]-[A-Za-z0-9-]{10,}|AKIA[0-9A-Z]{16}|eyJ[\w-]{8,}\.[\w-]{8,}\.[\w-]{8,}"
                r"|AGE-SECRET-KEY-1[A-Z0-9]{20,}|tskey-[a-z]+-[A-Za-z0-9-]{10,}|hvs\.[\w-]{20,})"), "***"),
]
_OPTION = re.compile(r"^--?[\w-]{0,80}?" + _NAME + r"$", re.I)
_PEM_BEGIN, _PEM_END = re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"), re.compile(r"-----END [A-Z ]*PRIVATE KEY-----")


def redact(text):
    """text with what looks like a secret replaced by ***. A net, not a promise: a job must not
    print secrets, and its log is root's for that reason."""
    for rule, to in _RULES:
        text = rule.sub(to, text)
    return text


def redact_argv(argv):
    """A command for the record: an option that names a secret loses its value, each word goes
    through redact(), and the list is cut to MAX_ARGS words of MAX_ARG characters."""
    out, hide = [], False
    for a in [str(x) for x in argv][:MAX_ARGS]:
        if hide and not a.startswith("-"):
            out.append("***")
            hide = False
            continue
        hide = bool(_OPTION.match(a))
        out.append(_cut(redact(a), MAX_ARG))
    if len(argv) > MAX_ARGS:
        out.append("…")
    return out


class Redactor:
    """redact() over a stream of lines: a private key printed across lines is hidden whole."""

    def __init__(self):
        self.in_key = False

    def line(self, text):
        if self.in_key:
            self.in_key = not _PEM_END.search(text)
            return "***"
        if _PEM_BEGIN.search(text):
            self.in_key = not _PEM_END.search(text)
            return "***"
        return redact(text)


_CONTROL = re.compile(r"[\x00-\x1f\x7f-\x9f]")


def _cut(text, n):
    """One line of at most n characters, with nothing a terminal would act on."""
    text = " ".join(_CONTROL.sub(" ", str(text or "")).split())
    return text if len(text) <= n else text[: n - 1].rstrip() + "…"


def _words(text, n=MAX_WORDS):
    return _cut(redact(str(text or "")), n)


# ------------------------------------------------------------------ the progress lines

_LINE = re.compile(r"^::([a-z][a-z-]*)(?:[ \t]+(.*))?$")
_STAGE = re.compile(r"^(\d+)(?:\.\d+)?%?(?:[ \t]+(.*))?$")
_PROGRESS = re.compile(r"^(\d+(?:\.\d+)?)\s*(?:/|of)\s*(\d+(?:\.\d+)?)(?:\s+([^\s,;:]+))?")
KINDS = ("stage", "item", "step", "note", "error", "ask")


def parse(line, known=()):
    """One house progress line as a dict, or None for anything else (a line this doesn't
    understand is only output: it never stops a job).

      ::stage PCT words          {"kind": "stage", "pct", "words"}
      ::item ID STATE [words]    {"kind": "item", "id", "state", "words"}    (the installers' and the lab's)
      ::step ID STATE [words]    {"kind": "step", "id", "state", "words"}
      ::note [ID] words          {"kind": "note", "id" or None, "words"}
      ::error [ID] words         {"kind": "error", "id" or None, "words"}
      ::ask ID words             {"kind": "ask", "id", "words"}              (kept in the log; questions aren't built)

    `known` is the ids seen so far. A note's or an error's first word is its ID when it is one
    of them, or when it looks like an id and a sentence follows (`::error network 2 items wait…`,
    not `::error The disk chosen is gone`).
    """
    if not isinstance(line, str) or not line.startswith("::"):
        return None
    m = _LINE.match(line.rstrip("\r\n"))
    if not m or m.group(1) not in KINDS:
        return None
    kind, rest = m.group(1), (m.group(2) or "").strip()
    if kind == "stage":
        m = _STAGE.match(rest)
        if not m:
            return None
        return {"kind": kind, "pct": min(100, int(m.group(1))), "words": (m.group(2) or "").strip()}
    if kind in ("item", "step"):
        parts = rest.split(None, 2)
        if len(parts) < 2 or _CONTROL.search(parts[0] + parts[1]):
            return None
        return {"kind": kind, "id": parts[0], "state": parts[1], "words": parts[2].strip() if len(parts) > 2 else ""}
    if not rest:
        return None
    head, _, tail = rest.partition(" ")
    tail = tail.strip()
    if tail and (head in known or (ID_OK.match(head) and (tail[0].isupper() or tail[0].isdigit()))):
        return {"kind": kind, "id": head, "words": tail}
    return {"kind": kind, "id": None, "words": rest}


def _flat(words):
    return " ".join(str(words or "").split())


def line_stage(pct, words):
    return f"::stage {max(0, min(100, int(pct)))} {_flat(words)}".rstrip()


def line_step(step_id, state, words=""):
    return f"::step {step_id} {state} {_flat(words)}".rstrip()


def line_note(step_id, words):
    return f"::note {step_id + ' ' if step_id else ''}{_flat(words)}"


def line_error(step_id, words):
    return f"::error {step_id + ' ' if step_id else ''}{_flat(words)}"


class Lines:
    """What a job says, as house progress lines on stdout. A Job has the same methods and
    takes the lines straight into its record."""

    current = None

    def _emit(self, line):
        print(line, flush=True)

    def stage(self, pct, words):
        self._emit(line_stage(pct, words))

    def step(self, step_id, words="", state="running"):
        """Step `step_id` is now `state` (running: the step before it is done)."""
        if state == "running" and self.current and self.current != step_id:
            self._emit(line_step(self.current, "done"))
        self.current = step_id if state == "running" else (None if self.current == step_id else self.current)
        self._emit(line_step(step_id, state, words))

    def note(self, words, step_id=None):
        self._emit(line_note(step_id, words))

    def error(self, words, step_id=None):
        self._emit(line_error(step_id, words))


# ------------------------------------------------------------------ a record

def slug(text, n):
    return re.sub(r"[^a-z0-9]+", "-", str(text or "").lower()).strip("-")[:n].strip("-")


def new_id(env, kind, subject=None):
    """YYYYMMDD-HHMM-<kind>-<subject>-<4 hex>, in UTC: sorts by time, and names the unit."""
    when = dt.datetime.fromtimestamp(env.now_ms() / 1000, dt.timezone.utc).strftime("%Y%m%d-%H%M")
    while True:
        parts = [when, kind[:32].strip(".-"), slug((subject or {}).get("id"), 24), secrets.token_hex(2)]
        job_id = "-".join(p for p in parts if p)
        if not any(os.path.exists(env.file(job_id, ext)) for ext in (".json", ".lock", ".spec")):
            return job_id


def unit_name(job_id):
    return f"{UNIT_PREFIX}{job_id}.service"


def parse_subject(text):
    """TYPE:ID[:NAME] as {type, id, name}."""
    kind, _, rest = (text or "").partition(":")
    sid, _, name = rest.partition(":")
    if not ID_OK.match(kind) or not sid:
        raise ActivityError(f"--subject is TYPE:ID[:NAME] (app:photos:Photos), not {text!r}")
    return {"type": kind, "id": _cut(sid, MAX_ID), "name": _words(name or sid, MAX_LABEL)}


def new_record(env, job_id, kind, title, subject=None, command=(), via="cli", device=None, unit=None):
    now = env.now_ms()
    return {
        "schema": SCHEMA, "id": job_id, "kind": kind, "title": _words(title, MAX_TITLE), "subject": subject,
        "state": "queued", "waiting_for": None, "question": None,
        "steps": [], "step": None, "pct": None, "stage": None, "notes": [],
        "started_at": now, "updated_at": now, "ended_at": None,
        "requested_by": {"via": via, "device": _cut(device, MAX_ID) if device else None},
        "unit": unit, "locks": [], "can": [], "cancel_safe": False, "cancel_note": None,
        "result": None, "error": None, "exit_code": None,
        "command": redact_argv(command), "log": env.file(job_id, ".log"),
        "parent": None, "children": [], "boot_id": env.boot_id(),
    }


def fit(rec):
    """The record within RECORD_MAX bytes: the oldest details go first, then the notes."""
    def size():
        return len(json.dumps(rec))
    if size() <= RECORD_MAX:
        return rec
    for s in rec["steps"]:
        s["detail"] = None
        if size() <= RECORD_MAX:
            return rec
    rec["notes"] = []
    return rec


def check(kind, title, via="cli"):
    if not KIND_OK.match(kind or "") or len(kind) > 48:
        raise ActivityError(f"a job's kind is two or more short words joined by dots (app.install), not {kind!r}")
    if via not in VIA:
        raise ActivityError(f"--via is one of {', '.join(VIA)}, not {via!r}")
    if not _flat(title):
        raise ActivityError("a job needs a title: a few plain words, such as \"Updating Photos\"")


class Job(Lines):
    """A job's record, and its only writer. Lines go in through feed(); every change is
    written whole and atomically."""

    def __init__(self, env, kind, title, subject=None, command=(), via="cli", device=None, job_id=None, unit=None):
        check(kind, title, via)
        self.env = env
        self.id = job_id or new_id(env, kind, subject)
        env.ensure_dir()
        self.path = env.file(self.id, ".json")
        self.rec = new_record(env, self.id, kind, title, subject, command, via, device, unit)
        self.errors, self.sticky, self.offline, self.last_line = [], set(), set(), ""
        self._wrote, self._dirty, self._lock = 0.0, False, None

    # -- its files
    def open(self):
        """Take the job's lock and write its first record (queued)."""
        lock = self.env.file(self.id, ".lock")
        fd = os.open(lock, os.O_RDWR | os.O_CREAT | os.O_EXCL, 0o600)      # an id is never used twice
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        os.fchmod(fd, 0o644)                                               # readers test it; only now can they open it
        self._lock = fd
        self.save()
        return self

    def close(self):
        if self._lock is not None:
            with contextlib.suppress(OSError):
                os.unlink(self.env.file(self.id, ".lock"))
            os.close(self._lock)
            self._lock = None

    def save(self, force=True):
        if not force and time.monotonic() - self._wrote < SAVE_EVERY:
            self._dirty = True
            return
        self.rec["updated_at"] = self.env.now_ms()
        write_json(self.path, fit(self.rec), 0o644)
        self._wrote, self._dirty = time.monotonic(), False

    def flush(self):
        if self._dirty:
            self.save(force=False)

    # -- its state
    def set_state(self, state, save=True):
        was = self.rec["state"]
        if state == was:
            return
        if state not in MOVES.get(was, ()):
            raise ActivityError(f"a job can't go from {was} to {state}")
        self.rec["state"] = state
        if state in FINAL:
            self.rec["ended_at"] = self.env.now_ms()
        if state not in ("waiting", "needs-you"):
            self.rec["waiting_for"] = None
        if save:
            self.save()

    def _settle(self):
        """running or waiting, from the steps: a job whose steps all wait (for the internet) waits."""
        if self.rec["state"] not in ("running", "waiting"):
            return False
        states = [s["state"] for s in self.rec["steps"]]
        want = "waiting" if "waiting" in states and "running" not in states else "running"
        if want == self.rec["state"]:
            return False
        self.set_state(want, save=False)
        if want == "waiting":
            waiting = {s["id"] for s in self.rec["steps"] if s["state"] == "waiting"}
            self.rec["waiting_for"] = "network" if waiting <= self.offline else None
        return True

    # -- its steps
    def _step(self, step_id, label=None):
        step_id = _cut(step_id, MAX_ID)
        for i, s in enumerate(self.rec["steps"]):
            if s["id"] == step_id:
                return i, s, False
        if len(self.rec["steps"]) >= MAX_STEPS:
            return None, None, False
        s = {"id": step_id, "label": _words(label or step_id, MAX_LABEL), "state": "todo", "started_at": None,
             "ended_at": None, "detail": None, "progress": None}
        self.rec["steps"].append(s)
        return len(self.rec["steps"]) - 1, s, True

    def _step_state(self, i, s, state):
        if s["state"] == state:
            return False
        now = self.env.now_ms()
        s["state"] = state
        if state == "todo":
            s["started_at"] = s["ended_at"] = None
        else:
            s["started_at"] = s["started_at"] or now
            s["ended_at"] = now if state in STEP_ENDS else None
        if state == "running":
            self.rec["step"] = i
        return True

    def _emit(self, line):
        self.feed(line)

    def feed(self, line):
        """One line of the job's output (already redacted). Returns the parsed event, or None."""
        ev = parse(line, {s["id"] for s in self.rec["steps"]})
        if not ev:
            if line.strip() and not line.startswith("::"):
                self.last_line = line.strip()
            return None
        kind, words = ev["kind"], ev.get("words") or ""
        moved = False
        if kind == "stage":
            self.rec["pct"], self.rec["stage"] = ev["pct"], _words(words, MAX_DETAIL) or self.rec["stage"]
        elif kind in ("item", "step"):
            raw = ev["state"].lower()
            state = raw if kind == "step" and raw in STEP_STATES else ITEM_STATES.get(raw, "running")
            i, s, new = self._step(ev["id"], words if kind == "step" else None)
            if s is None:
                return ev
            moved = self._step_state(i, s, state) or new
            (self.offline.add if raw in OFFLINE else self.offline.discard)(s["id"])
            if words and not (new and kind == "step"):
                s["detail"] = _words(words, MAX_DETAIL)
                self.sticky.add(s["id"]) if state in STEP_ENDS else self.sticky.discard(s["id"])
            elif s["id"] not in self.sticky:
                # the state's own word says what a step is doing (downloading, installing)
                told = "Waiting for the internet" if raw in OFFLINE else raw.replace("-", " ").capitalize()
                s["detail"] = None if state in STEP_ENDS + ("todo",) or raw == state else _words(told, MAX_DETAIL)
            m = _PROGRESS.match(words)
            if m:
                s["progress"] = {"done": float(m.group(1)), "total": float(m.group(2)), "unit": m.group(3)}
            moved = self._settle() or moved
        elif kind == "note":
            self.rec["notes"] = (self.rec["notes"] + [{"id": ev["id"], "words": _words(words), "at": self.env.now_ms()}])[-MAX_NOTES:]
            self._detail(ev["id"], words)
            moved = True
        elif kind == "error":
            self.errors.append((ev["id"], _words(words)))
            self._detail(ev["id"], words)
            moved = True
        self.save(force=moved)
        return ev

    def _detail(self, step_id, words):
        for s in self.rec["steps"]:
            if s["id"] == step_id:
                s["detail"] = _words(words, MAX_DETAIL)
                self.sticky.add(step_id)

    # -- its end
    def finish(self, exit_code=0, cancelled=False, words=None, state=None, code=None):
        """The job's last state. exit_code 0 is succeeded, anything else failed (with the step
        and the reason); cancelled wins; `state` names another end (rolled-back)."""
        rec = self.rec
        if rec["state"] in FINAL:
            return rec
        end = state or ("cancelled" if cancelled else "succeeded" if exit_code == 0 else "failed")
        running = next((s for s in rec["steps"] if s["state"] == "running"), None)
        for s in rec["steps"]:
            was = s["state"]
            if was == "running":
                self._step_state(None, s, {"succeeded": "done", "failed": "failed", "rolled-back": "failed"}.get(end, "skipped"))
                if s["id"] not in self.sticky:
                    s["detail"] = None if end == "succeeded" else "It stopped here."
            elif was == "waiting" or (was == "todo" and end == "succeeded"):
                self._step_state(None, s, "skipped")
        rec["exit_code"] = exit_code
        if end == "succeeded":
            rec["result"] = {"ok": True, "summary": _words(words or rec["stage"] or "Finished."), "undo": None}
        elif end == "cancelled":
            rec["result"] = {"ok": False, "summary": _words(words or "Stopped before it finished."), "undo": None}
        else:
            ids = {s["id"] for s in rec["steps"]}
            named = next((e for e in self.errors if e[0] in ids), None) or (self.errors[0] if self.errors else None)
            failed = next((s for s in rec["steps"] if s["state"] == "failed"), None)
            step = (named[0] if named and named[0] in ids else None) or (running or failed or {}).get("id")
            why = words or (named[1] if named else None) or self.last_line or (
                f"It stopped with exit status {exit_code}." if exit_code is not None else "It stopped without saying why.")
            rec["error"] = {"step": step, "words": _words(why), "code": code or "exit", "fix": None}
            label = next((s["label"] for s in rec["steps"] if s["id"] == step), None)
            rec["result"] = {"ok": False, "undo": None, "summary": _words(
                ("It failed and put things back by itself." if end == "rolled-back" else
                 f"It stopped at {label}." if label else "It didn't finish."))}
        self.set_state(end)
        self.close()
        return rec


# ------------------------------------------------------------------ reading

def alive(env, job_id):
    """Whether the job's process still holds its lock."""
    try:
        fd = os.open(env.file(job_id, ".lock"), os.O_RDONLY)
    except FileNotFoundError:
        return False
    except OSError:
        return True                                 # can't tell: don't call it gone
    try:
        fcntl.flock(fd, fcntl.LOCK_SH | fcntl.LOCK_NB)
        return False
    except OSError:
        return True
    finally:
        os.close(fd)


def _interrupted(env, rec):
    """rec as it reads once its process is gone with no last state."""
    rec = json.loads(json.dumps(rec))
    now = env.now_ms()
    step = None
    for s in rec["steps"]:
        if s["state"] in ("running", "waiting"):
            step = step or (s["id"] if s["state"] == "running" else None)
            s["state"], s["ended_at"] = "skipped", now
            s["detail"] = s["detail"] or "It stopped here."
    rebooted = bool(rec.get("boot_id")) and rec["boot_id"] != env.boot_id()
    why = ("This computer restarted or lost power while it ran." if rebooted else
           "It stopped without a last word: its process was killed.")
    rec.update(state="interrupted", waiting_for=None, question=None, ended_at=rec.get("updated_at") or now, updated_at=now,
               error={"step": step, "words": why, "code": "interrupted", "fix": None},
               result={"ok": False, "summary": "It didn't finish.", "undo": None})
    return rec


def _read(env, job_id):
    rec = read_json(env.file(job_id, ".json"))
    if not isinstance(rec, dict) or rec.get("id") != job_id or rec.get("state") not in STATES:
        return None
    if rec["state"] not in FINAL and not alive(env, job_id):
        again = read_json(env.file(job_id, ".json")) or rec      # it may have ended between the two looks
        rec = again if again.get("state") in FINAL else _interrupted(env, again)
    return rec


def _ids(env):
    try:
        names = os.listdir(env.jobs_dir())
    except OSError:
        return []
    return sorted(n[:-5] for n in names if n.endswith(".json") and JOB_ID_OK.match(n[:-5]))


def list_jobs(env, limit=None, states=None):
    """The records, as they stand now: the ones still going first, then the newest ended."""
    out = [r for r in (_read(env, i) for i in _ids(env)) if r and (not states or r["state"] in states)]
    out.sort(key=lambda r: (r["state"] in FINAL, -(r.get("ended_at") or r.get("started_at") or 0), r["id"]))
    return out[:limit] if limit else out


def find(env, text=None):
    """A job by its id, or by a part of it that names only one; the newest with no text."""
    ids = _ids(env)
    if not text:
        jobs = sorted((r for r in (_read(env, i) for i in ids) if r), key=lambda r: r.get("started_at") or 0)
        if not jobs:
            raise KeyError("no jobs yet")
        return jobs[-1]
    hits = [i for i in ids if i == text] or [i for i in ids if text in i]
    if len(hits) != 1:
        raise KeyError(f"no job {text!r}" if not hits else f"{text!r} matches {len(hits)} jobs: " + ", ".join(hits[:5]))
    rec = _read(env, hits[0])
    if rec is None:
        raise KeyError(f"no job {text!r}")
    return rec


def log_tail(env, rec, n=20):
    """The log's last n lines, or None when this user may not read it (it is root's)."""
    lines = []
    try:
        for p in (env.file(rec["id"], ".log.1"), env.file(rec["id"], ".log")):
            if os.path.exists(p):
                with open(p, errors="replace") as f:
                    lines += f.read().splitlines()
    except OSError:
        return None
    return lines[-n:] if n else lines


# ------------------------------------------------------------------ closing and pruning

def sweep(env):
    """Close the records whose job is gone (a restart, a kill) and drop what is past the
    bounds. Whoever can write the folder does this: every new job, and the readers as root."""
    closed = []
    for job_id in _ids(env):
        rec = read_json(env.file(job_id, ".json"))
        if not isinstance(rec, dict) or rec.get("state") in FINAL or alive(env, job_id):
            continue
        lock = env.file(job_id, ".lock")
        try:
            fd = os.open(lock, os.O_RDWR | os.O_CREAT, 0o644)
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            continue                                # someone else is closing it
        try:
            rec = read_json(env.file(job_id, ".json"))
            if isinstance(rec, dict) and rec.get("state") not in FINAL:
                write_json(env.file(job_id, ".json"), fit(_interrupted(env, rec)), 0o644)
                closed.append(job_id)
            with contextlib.suppress(OSError):
                os.unlink(lock)
        finally:
            os.close(fd)
    return closed, prune(env)


def prune(env):
    """Finished jobs past KEEP_DAYS or beyond the newest KEEP_JOBS go, with their logs; so do
    files no record owns."""
    now, gone = env.now_ms(), []
    done = []
    for job_id in _ids(env):
        rec = read_json(env.file(job_id, ".json"))
        if isinstance(rec, dict) and rec.get("state") in FINAL:
            done.append((rec.get("ended_at") or rec.get("updated_at") or 0, job_id))
    done.sort(reverse=True)
    for k, (ended, job_id) in enumerate(done):
        if k >= KEEP_JOBS or now - ended > KEEP_DAYS * 86400_000:
            for ext in (".json", ".log", ".log.1", ".lock", ".spec"):
                with contextlib.suppress(OSError):
                    os.unlink(env.file(job_id, ext))
            gone.append(job_id)
    keep = set(_ids(env))
    try:
        names = os.listdir(env.jobs_dir())
    except OSError:
        names = []
    for n in names:
        p = os.path.join(env.jobs_dir(), n)
        owner = re.sub(r"\.(log|log\.1|lock|spec)$", "", n)
        half_written = re.search(r"\.tmp\.\d+$", n)             # a writer killed mid-write leaves one
        if not half_written and (owner == n or owner in keep):
            continue
        with contextlib.suppress(OSError):
            if time.time() * 1000 - os.stat(p).st_mtime * 1000 > ORPHAN_MS:
                os.unlink(p)
    return gone


# ------------------------------------------------------------------ the log

class Log:
    """<id>.log, kept under LOG_MAX: at half of it the file becomes <id>.log.1 and a new one starts."""

    def __init__(self, path):
        self.path, self.f, self.size = path, None, 0
        self._open()

    def _open(self):
        fd = os.open(self.path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o640)
        self.f = os.fdopen(fd, "a", errors="replace")
        self.size = os.fstat(fd).st_size

    def write(self, line):
        data = line + "\n"
        if self.size + len(data) > LOG_MAX // 2 and self.size:
            self.f.close()
            os.replace(self.path, self.path + ".1")
            self._open()
        self.f.write(data)
        self.f.flush()
        self.size += len(data.encode(errors="replace"))

    def close(self):
        self.f.close()


class Tail:
    """Follow <id>.log across its turn-over: every line once, in order."""

    def __init__(self, path):
        self.path, self.f, self.buf = path, None, ""

    def close(self):
        if self.f is not None:
            self.f.close()
            self.f = None

    def lines(self):
        out = []
        while True:
            if self.f is None:
                try:
                    self.f = open(self.path, errors="replace")
                except OSError:
                    return out
            chunk = self.f.read()
            if chunk:
                self.buf += chunk
                *whole, self.buf = self.buf.split("\n")
                out += whole
                continue
            try:
                turned = os.stat(self.path).st_ino != os.fstat(self.f.fileno()).st_ino
            except OSError:
                turned = False
            if not turned:
                return out
            self.f.close()                           # read to its end; the new file is next
            self.f = None


# ------------------------------------------------------------------ running a job

def supervise(env, job, argv, echo=None, cwd=None):
    """Run argv as `job`, to its end: this process is the job. Each line the command prints is
    redacted, logged, echoed, and fed to the record. SIGTERM or SIGINT stops the command and
    the job ends cancelled (interrupted, when it is the system shutting down); a closed terminal
    changes nothing. Returns the exit status."""
    stop = {"sig": None}
    old = {s: signal.signal(s, lambda n, f: stop.__setitem__("sig", n)) for s in (signal.SIGTERM, signal.SIGINT)}
    old[signal.SIGHUP] = signal.signal(signal.SIGHUP, signal.SIG_IGN)
    old[signal.SIGPIPE] = signal.signal(signal.SIGPIPE, signal.SIG_IGN)
    log, red, out = Log(env.file(job.id, ".log")), Redactor(), {"echo": echo}

    def take(raw):
        text = red.line(raw.decode(errors="replace").rstrip("\r")[:LINE_MAX])
        log.write(text)
        if out["echo"]:
            try:
                out["echo"](text)
            except (OSError, ValueError):
                out["echo"] = None                   # whoever watched went away; the job goes on
        job.feed(text)

    try:
        try:
            child = subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                     start_new_session=True, preexec_fn=_ends_with_us(),
                                     cwd=cwd if cwd and os.path.isdir(cwd) else None,
                                     env=dict(env.environ, BROMIGOS_ACTIVITY_JOB=job.id, PYTHONUNBUFFERED="1"))
        except OSError as e:
            words = f"{argv[0]} couldn't start: {e.strerror or e}."
            log.write(words)
            job.finish(127, words=words, code="not-started")
            return 127
        job.set_state("running")
        fd, buf, told, kill_at, quiet = child.stdout.fileno(), b"", False, None, 0
        while True:
            if stop["sig"] and not told:
                told, kill_at = True, time.monotonic() + STOP_GRACE
                _signal_group(child, signal.SIGTERM)
            if kill_at and time.monotonic() > kill_at:
                kill_at = None
                _signal_group(child, signal.SIGKILL)
            ready, _, _ = select.select([fd], [], [], 0.2)
            if ready:
                chunk = os.read(fd, 65536)
                if not chunk:
                    break
                quiet, buf = 0, buf + chunk
                *whole, buf = buf.split(b"\n")
                for raw in whole:
                    take(raw)
                if len(buf) > 4 * LINE_MAX:           # a line with no end: keep its start
                    take(buf)
                    buf = b""
            elif child.poll() is not None:
                quiet += 1
                if quiet >= 3:                        # it ended; something it started still holds the pipe
                    break
            job.flush()
        if buf:
            take(buf)
        code = child.wait()
        status = code if code >= 0 else 128 - code                # 128 + the signal, as a shell says it
        if stop["sig"] and shutting_down(env):
            job.finish(status, state="interrupted", code="interrupted",
                       words="This computer was shut down or restarted while it ran.")
        elif stop["sig"]:
            job.finish(status, cancelled=True)
        elif code < 0:
            job.finish(status, words=f"It was stopped by signal {-code}.", code="signal")
        else:
            job.finish(status)
        return 130 if stop["sig"] else status
    finally:
        log.close()
        job.close()
        for s, h in old.items():
            signal.signal(s, h)


def shutting_down(env):
    """Whether systemd is stopping the system: a job stopped by that was interrupted, not cancelled."""
    exe = env.find("systemctl") if env.runner() == "systemd" else None
    if not exe:
        return False
    try:
        r = subprocess.run([exe, "is-system-running"], capture_output=True, text=True, timeout=5, env=env.environ)
    except (OSError, subprocess.TimeoutExpired):
        return False
    return r.stdout.strip() == "stopping"


def _ends_with_us():
    """For the command as it starts: a SIGTERM if this process dies with no last word (a
    kill), so nothing runs on with nobody keeping its record. In a unit systemd does the same."""
    try:
        import ctypes
        prctl = ctypes.CDLL(None, use_errno=True).prctl
    except (ImportError, OSError, AttributeError):
        return None
    return lambda: prctl(1, int(signal.SIGTERM)) and None          # PR_SET_PDEATHSIG


def _signal_group(child, sig):
    with contextlib.suppress(OSError):
        os.killpg(child.pid, sig)


def start_unit(env, job_id, title, self_argv, run=subprocess.run):
    """Start bromigos-job-<id>.service: `self_argv run --job <id>` in its own transient unit.
    The unit's command line carries the id only; what to run is in the job's spec file."""
    exe = env.find("systemd-run")
    if not exe:
        raise ActivityError("systemd-run isn't installed, so a job can't have its own unit")
    cmd = [exe, f"--unit={unit_name(job_id)}", "--collect", "--quiet", "--service-type=exec",
           "--property=KillMode=mixed", f"--description=bromigOS job: {_words(title, MAX_TITLE).replace('%', '')}"]
    # a system unit has no HOME; the command gets the one `sudo COMMAND` would give it
    home = env.environ.get("HOME") if env.stand_in else pwd.getpwuid(os.geteuid()).pw_dir
    if home:
        cmd.append(f"--setenv=HOME={home}")
    if env.stand_in:
        cmd.append(f"--setenv=BROMIGOS_ROOT={env.root}")
    r = run(cmd + ["--", *self_argv, "run", "--job", job_id], capture_output=True, text=True, env=env.environ)
    if r.returncode != 0:
        why = (r.stderr or r.stdout or "").strip().splitlines()
        raise ActivityError("the job's unit didn't start" + (f": {why[-1]}" if why else ""))


def follow(env, job_id, echo=None, wait=START_WAIT, poll=0.1):
    """Watch a job until it ends: its log's lines go to echo. Returns the last record. Only a
    watcher: stopping this stops nothing."""
    tail, deadline, out = Tail(env.file(job_id, ".log")), time.monotonic() + wait, {"echo": echo}

    def tell():
        for line in tail.lines() if out["echo"] else ():
            try:
                out["echo"](line)
            except (OSError, ValueError):
                out["echo"] = None                   # nobody reads any more; keep waiting for its end
                return

    try:
        while True:
            rec = _read(env, job_id) if os.path.exists(env.file(job_id, ".json")) else None
            tell()
            if rec and rec["state"] in FINAL:
                tell()                               # what it said as it ended
                return rec
            if rec is None and time.monotonic() > deadline:
                raise ActivityError(f"the job's unit started but wrote no record within {int(wait)} s: "
                                    f"journalctl -u {unit_name(job_id)}")
            time.sleep(poll)
    finally:
        tail.close()


def run(env, kind, title, argv, subject=None, via="cli", device=None, detach=False, echo=None, self_argv=None, note=None):
    """Start argv as a job and (unless detach) watch it to its end. Returns (exit status, the
    job's id). With systemd the job is its own unit and outlives the caller; without, it runs
    here, in the foreground, with the same record."""
    check(kind, title, via)
    if not argv:
        raise ActivityError("nothing to run: bromigos activity run --kind KIND --title WORDS -- COMMAND…")
    exe = env.find(argv[0])
    if not exe:
        raise ActivityError(f"no such command: {argv[0]}")
    note = note or (lambda words: None)
    if env.runner() == "foreground" or not self_argv:
        if detach:
            note("There's no systemd here, so the job runs in this terminal.")
        env.ensure_dir()
        sweep(env)
        job = Job(env, kind, title, subject, argv, via, device).open()
        return supervise(env, job, [exe, *argv[1:]], echo=echo, cwd=os.getcwd()), job.id
    env.ensure_dir()
    job_id = new_id(env, kind, subject)
    spec = {"kind": kind, "title": title, "subject": subject, "via": via, "device": device,
            "argv": [exe, *argv[1:]], "typed": list(argv), "cwd": os.getcwd()}
    write_json(env.file(job_id, ".spec"), spec, 0o600)
    try:
        start_unit(env, job_id, title, self_argv)
    except ActivityError:
        with contextlib.suppress(OSError):
            os.unlink(env.file(job_id, ".spec"))
        raise
    if detach:
        return 0, job_id
    try:
        rec = follow(env, job_id, echo)
    except KeyboardInterrupt:
        note(f"Still running as {unit_name(job_id)}: bromigos activity show {job_id}")
        return 130, job_id
    code = rec.get("exit_code")
    return (code if isinstance(code, int) else 130 if rec["state"] == "cancelled" else 1), job_id


def run_spec(env, job_id):
    """Inside the unit: read the job's spec, remove it, and be the job. Returns the exit status."""
    spec_path = env.file(job_id, ".spec")
    spec = read_json(spec_path)
    if not isinstance(spec, dict) or not spec.get("argv"):
        raise ActivityError(f"no job {job_id} is waiting to start")
    with contextlib.suppress(OSError):
        os.unlink(spec_path)
    sweep(env)
    job = Job(env, spec["kind"], spec["title"], spec.get("subject"), spec.get("typed") or spec["argv"],
              spec.get("via") or "cli", spec.get("device"), job_id, unit_name(job_id)).open()
    return supervise(env, job, spec["argv"], cwd=spec.get("cwd"))


@contextlib.contextmanager
def job(kind, title, subject=None, env=None, via="cli"):
    """For a Python command that is a job:

        with activity.job("backup.run", "Backing up") as j:
            j.step("snapshot", "Taking a snapshot")
            j.step("copy", "Copying what changed")

    Under `bromigos activity run` it prints the progress lines and the wrapper keeps the
    record. On its own it keeps the record itself, in this process (no unit: it ends when the
    process does). An exception ends the job failed, with the exception's words."""
    env = env or Env()
    if env.environ.get("BROMIGOS_ACTIVITY_JOB"):
        j = Lines()
        yield j
        if j.current:
            j.step(j.current, state="done")
        return
    sweep(env)
    j = Job(env, kind, title, subject, [os.path.basename(sys.argv[0] or "python")], via).open()
    j.set_state("running")
    try:
        yield j
    except BaseException as e:
        j.finish(1, cancelled=isinstance(e, KeyboardInterrupt), words=None if isinstance(e, KeyboardInterrupt) else str(e) or type(e).__name__)
        raise
    else:
        j.finish(0)
    finally:
        j.close()


# ------------------------------------------------------------------ for people

WORDS = {"queued": "queued", "running": "running", "needs-you": "needs you", "waiting": "waiting", "succeeded": "done",
         "failed": "failed", "rolled-back": "put back", "cancelled": "cancelled", "interrupted": "interrupted"}
MARKS = {"todo": "·", "running": "▸", "waiting": "…", "done": "✓", "failed": "✗", "skipped": "-"}


def ago(ms):
    s = max(0, int(ms // 1000))
    for n, unit in ((86400, "d"), (3600, "h"), (60, "min")):
        if s >= n:
            return f"{s // n} {unit} ago"
    return "just now"


def took(ms):
    s = max(0, int(ms // 1000))
    return f"{s // 3600} h {s % 3600 // 60} min" if s >= 3600 else f"{s // 60} min {s % 60} s" if s >= 60 else f"{s} s"


def now_words(rec):
    """What a job is doing, or how it ended, in one line."""
    steps, state = rec["steps"], rec["state"]
    if state in ("failed", "interrupted", "rolled-back") and rec.get("error"):
        at = next((s["label"] for s in steps if s["id"] == rec["error"].get("step")), None)
        return (f"stopped at {at}: " if at else "") + rec["error"]["words"]
    if state in FINAL:
        return (rec.get("result") or {}).get("summary") or ""
    parts = []
    if rec.get("pct") is not None:
        parts.append(f"{rec['pct']} %")
    i = rec.get("step")
    if steps and i is not None and i < len(steps):
        s = steps[i]
        parts.append(f"step {i + 1} of {len(steps)}, {s['label']}" + (f" ({s['detail']})" if s.get("detail") else ""))
    elif rec.get("stage"):
        parts.append(rec["stage"])
    if state == "waiting" and rec.get("waiting_for"):
        parts.append(f"waiting for the {rec['waiting_for']}" if rec["waiting_for"] in ("network", "drive") else f"waiting for {rec['waiting_for']}")
    return ", ".join(parts)


def plain_list(jobs, now_ms):
    if not jobs:
        return "No jobs yet. A long job shows here while it runs and for 30 days after."
    rows = []
    for r in jobs:
        when = ago(now_ms - (r.get("ended_at") or r["started_at"]))
        rows.append((WORDS[r["state"]], when, r["id"], r["title"] + (": " + now_words(r) if now_words(r) else "")))
    w = [max(len(row[k]) for row in rows + [("STATE", "WHEN", "JOB", "")]) for k in range(3)]
    lines = [f"{'STATE':<{w[0]}}  {'WHEN':<{w[1]}}  {'JOB':<{w[2]}}  WHAT"]
    lines += [f"{a:<{w[0]}}  {b:<{w[1]}}  {c:<{w[2]}}  {d}" for a, b, c, d in rows]
    return "\n".join(lines)


def plain_show(rec, tail, now_ms):
    end = rec.get("ended_at")
    head = f"{WORDS[rec['state']]} {ago(now_ms - (end or rec['started_at']))}"
    head += f", after {took(end - rec['started_at'])}" if end else f", for {took(now_ms - rec['started_at'])}"
    lines = [rec["title"], f"  {head}  ·  {rec['kind']}  ·  {rec['id']}"]
    if now_words(rec):
        lines.append("  " + now_words(rec))
    if rec["steps"]:
        w = max(len(s["label"]) for s in rec["steps"])
        lines += ["", "Steps"]
        for s in rec["steps"]:
            lines.append(f"  {MARKS[s['state']]} {s['label']:<{w}}  {s['state']:<7}  {s.get('detail') or ''}".rstrip())
    if rec["notes"]:
        lines += ["", "Notes"] + [f"  ▲ {n['id'] + ': ' if n.get('id') else ''}{n['words']}" for n in rec["notes"]]
    lines += ["", f"Command  {shlex.join(rec['command'])}", f"Unit     {rec['unit'] or 'none: it ran in the foreground'}",
              f"Log      {rec['log']}"]
    if tail is None:
        lines.append("         The log is root's to read: sudo bromigos activity show " + rec["id"])
    elif tail:
        lines += ["", f"The log's last {len(tail)} line{'s' if len(tail) != 1 else ''}"]
        lines += ["  " + _CONTROL.sub("", t.replace("\t", "    ")) for t in tail]
    return "\n".join(lines)
