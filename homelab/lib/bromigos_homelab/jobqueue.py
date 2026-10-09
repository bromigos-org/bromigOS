"""The lab job queue: `bromigos lab run|jobs` submit and read it; `bromigos-lab.service`
(`bromigos lab serve`) runs it. docs/lab.md, "Jobs".

State: ~/.local/state/bromigos/lab/ ($BROMIGOS_LAB_STATE):
  jobs/<id>.json   one job (written whole, atomically; the service and the CLI take `lock`)
  jobs/<id>.log    its log
  service.json     the running service: pid, heartbeat, the GPU it watches, what runs
  vram.json        the most VRAM each kind was seen to add (the gate uses the larger of
                   this and the kind's measured number)

The scheduler, every second:
  * heavy jobs (the GPU kinds) run one at a time, in the order they came;
  * a heavy job starts only when its GPU has the VRAM it needs plus [lab] voice_reserve_mib
    for the voice service (VECTOR's voice is never starved, stopped or restarted), and the
    GPU's server isn't busy with someone else's work; until then it waits, saying why;
  * a job that could never fit (it needs more than the GPU has) fails at once, in words;
  * light jobs (voice lines, transcription, LLM batches) don't wait behind heavy ones; one
    at a time per backend, so a long batch never crowds the voice service.
Results land in ~/Pictures/bromigos/lab/<kind>/ ($BROMIGOS_LAB_OUT); a notification says
when a job finishes or fails.
"""
import contextlib
import datetime as dt
import fcntl
import json
import os
import secrets as _rand
import shutil
import signal
import subprocess
import threading
import time

from . import caps, config, jobs, registry

STATES = ("queued", "waiting", "running", "succeeded", "failed", "cancelled")
DONE = ("succeeded", "failed", "cancelled")
POOL_LIMIT = {"voice": 1, "llm": 1}            # light jobs at once per backend (others: 2)
# VRAM kept free beyond what the voice service holds. Its models and working memory are
# resident (CUDA graphs: the 5090's free VRAM didn't move while it spoke, 2026-10-09); this is
# margin for a long line or a new reference voice, never given to a job
VOICE_RESERVE_MIB = 1024


def state_dir():
    return os.environ.get("BROMIGOS_LAB_STATE") or os.path.join(
        os.environ.get("XDG_STATE_HOME") or os.path.expanduser("~/.local/state"), "bromigos", "lab")


def out_root():
    return os.environ.get("BROMIGOS_LAB_OUT") or os.path.join(
        os.environ.get("XDG_PICTURES_DIR") or os.path.expanduser("~/Pictures"), "bromigos", "lab")


def _jobs_dir():
    d = os.path.join(state_dir(), "jobs")
    os.makedirs(d, exist_ok=True)
    return d


@contextlib.contextmanager
def locked():
    os.makedirs(state_dir(), exist_ok=True)
    with open(os.path.join(state_dir(), "lock"), "a+") as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(f, fcntl.LOCK_UN)


def _path(jid, ext=".json"):
    if not jid or "/" in jid or jid.startswith("."):
        raise KeyError(f"no job {jid!r}")
    return os.path.join(_jobs_dir(), jid + ext)


def _write(job):
    p = _path(job["id"])
    tmp = p + f".{os.getpid()}.tmp"
    with open(tmp, "w") as f:
        json.dump(job, f, indent=1, default=str)
    os.replace(tmp, p)


def get(jid):
    with open(_path(jid)) as f:
        return json.load(f)


def find(prefix):
    """A job by its id or a unique prefix of it."""
    try:
        return get(prefix)
    except (OSError, KeyError, ValueError):
        pass
    hits = [f[:-5] for f in os.listdir(_jobs_dir()) if f.endswith(".json") and f.startswith(prefix)]
    if len(hits) == 1:
        return get(hits[0])
    raise KeyError(f"no job {prefix!r}" if not hits else f"{prefix!r} matches {len(hits)} jobs")


def list_jobs(limit=None, states=None):
    out = []
    for f in os.listdir(_jobs_dir()):
        if not f.endswith(".json"):
            continue
        try:
            with open(os.path.join(_jobs_dir(), f)) as fh:
                j = json.load(fh)
        except (OSError, ValueError):
            continue
        if states and j.get("state") not in states:
            continue
        out.append(j)
    out.sort(key=lambda j: j.get("created") or 0, reverse=True)
    return out[:limit] if limit else out


def log(jid, text):
    with open(_path(jid, ".log"), "a") as f:
        f.write(f"{time.strftime('%H:%M:%S')} {text.rstrip()}\n")


def read_log(jid):
    try:
        with open(_path(jid, ".log")) as f:
            return f.read()
    except OSError:
        return ""


def update(jid, **kw):
    with locked():
        j = get(jid)
        j.update(kw)
        _write(j)
        return j


def describe(j):
    """One line about a job, in words (the hover hint, the notification)."""
    what = j.get("preset") or j["kind"]
    s = {"queued": "queued", "waiting": "waiting", "running": "running", "succeeded": "done",
         "failed": "failed", "cancelled": "cancelled"}.get(j["state"], j["state"])
    bits = [f"{what} {j['id']}: {s}"]
    if j.get("why") and j["state"] in ("waiting", "failed"):
        bits.append(j["why"])
    if j.get("outputs") and j["state"] == "succeeded":
        bits.append("→ " + ", ".join(os.path.basename(o) for o in j["outputs"][:3]))
    if j.get("prompt") or j.get("text"):
        bits.append(f"“{(j.get('prompt') or j.get('text'))[:60]}”")
    return " · ".join(bits)


# ------------------------------------------------------------------ submitting (the CLI, VECTOR)
def new_id(kind):
    return f"{dt.datetime.now().strftime('%m%d-%H%M%S')}-{kind[:6]}-{_rand.token_hex(2)}"


def submit(kind, preset=None, prompt=None, inputs=(), text=None, cloud=False, by="you", **opts):
    """Queue a job; -> the job. Raises ValueError for one that can't run here."""
    jobs.kinds()
    p = None
    if preset:
        p = jobs.PRESETS.get(preset)
        if not p:
            raise ValueError(f"no preset {preset!r} (bromigos lab run --presets lists them)")
        if kind and kind != p.kind:
            raise ValueError(f"the preset {preset} is a {p.kind} job, not {kind}")
        kind = p.kind
        if p.disabled:
            raise ValueError(f"{p.title}: {p.disabled}")
    k = jobs.KINDS.get(kind)
    if not k:
        raise ValueError(f"no job kind {kind!r} (bromigos lab run --kinds lists them)")
    ok, why = k.status()
    if not ok:
        raise ValueError(f"{k.title} jobs can't run on this lab: {why}")
    ins = [os.path.abspath(os.path.expanduser(i)) for i in inputs or ()]
    for i in ins:
        if not os.path.isfile(i):
            raise ValueError(f"{i} isn't a file")
    options = dict(p.options) if p else {}
    options.update(opts.pop("options", None) or {})
    j = {"id": new_id(kind), "kind": kind, "preset": preset, "state": "queued", "prompt": prompt, "text": text,
         "inputs": ins, "options": options, "cloud": bool(cloud), "by": by, "created": time.time(),
         "started": None, "finished": None, "why": "", "progress": 0.0, "progress_text": "", "outputs": [],
         "note": {}, "cancel": False, "attempt": 1}
    for key in ("voice", "model", "aspect", "mask", "name", "language", "provider", "timeout", "retry_of"):
        if opts.get(key) is not None:
            j[key] = opts[key]
    if j.get("mask"):
        j["mask"] = os.path.abspath(os.path.expanduser(j["mask"]))
    with locked():
        _write(j)
    log(j["id"], f"queued by {by}: {kind}" + (f" ({preset})" if preset else "") + (" · cloud allowed" if cloud else ""))
    return j


def cancel(jid):
    with locked():
        j = find(jid)
        if j["state"] in DONE:
            return j
        if j["state"] in ("queued", "waiting"):
            j.update(state="cancelled", finished=time.time(), why="cancelled before it started")
        else:
            j["cancel"] = True
        _write(j)
    log(j["id"], "cancel asked")
    return j


def retry(jid, by="you"):
    j = find(jid)
    if j["state"] not in DONE:
        raise ValueError(f"{j['id']} is {j['state']}: only a finished job can be retried")
    keep = {k: j.get(k) for k in ("voice", "model", "aspect", "mask", "name", "language", "provider", "timeout")
            if j.get(k) is not None}
    n = submit(j["kind"], j.get("preset"), j.get("prompt"), j.get("inputs") or (), j.get("text"), j.get("cloud"),
               by=by, options=j.get("options") or {}, retry_of=j["id"], **keep)
    return update(n["id"], attempt=(j.get("attempt") or 1) + 1)


# ------------------------------------------------------------------ the service
def service_state():
    """'running' (a heartbeat in the last 15 s), 'stopped', or 'stale'."""
    try:
        with open(os.path.join(state_dir(), "service.json")) as f:
            s = json.load(f)
    except (OSError, ValueError):
        return "stopped"
    alive = _alive(s.get("pid"))
    if alive and time.time() - (s.get("heartbeat") or 0) < 15:
        return "running"
    return "stale" if alive else "stopped"


def service_info():
    try:
        with open(os.path.join(state_dir(), "service.json")) as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def _alive(pid):
    try:
        os.kill(int(pid), 0)
        return True
    except (TypeError, ValueError, OSError):
        return False


def ensure_service():
    """Start the queue's service when it isn't running: the user unit (bromigos-lab.service)
    if systemd has it, else `bromigos-lab serve` detached. -> how it was started, or ''."""
    if service_state() == "running":
        return ""
    if not os.environ.get("BROMIGOS_LAB_NO_SYSTEMD") and shutil.which("systemctl"):
        try:
            p = subprocess.run(["systemctl", "--user", "start", "bromigos-lab.service"], capture_output=True,
                               text=True, timeout=15)
            if p.returncode == 0:
                for _ in range(30):
                    if service_state() == "running":
                        return "bromigos-lab.service"
                    time.sleep(0.2)
                return "bromigos-lab.service"
        except (OSError, subprocess.TimeoutExpired):
            pass
    exe = os.environ.get("BROMIGOS_LAB_BIN") or next(
        (p for p in ("/usr/lib/bromigos/bin/bromigos-lab",
                     os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(
                         os.path.realpath(__file__))))), "bin", "bromigos-lab")) if os.path.exists(p)), None)
    if not exe:
        return ""
    os.makedirs(state_dir(), exist_ok=True)
    with open(os.path.join(state_dir(), "service.log"), "a") as lf:
        subprocess.Popen([exe, "serve"], stdin=subprocess.DEVNULL, stdout=lf, stderr=lf, start_new_session=True)
    for _ in range(40):
        if service_state() == "running":
            break
        time.sleep(0.15)
    return "bromigos-lab serve"


def notify(title, body, urgency="normal", icon="applications-science"):
    """A desktop notification (notify-send); quietly nothing without a session bus."""
    if os.environ.get("BROMIGOS_LAB_NOTIFY") == "off" or not shutil.which("notify-send"):
        return False
    try:
        subprocess.run(["notify-send", "-a", "bromigos lab", "-u", urgency, "-i", icon, title, body],
                       capture_output=True, timeout=10)
        return True
    except (OSError, subprocess.TimeoutExpired):
        return False


class Ctx:
    """What a kind's run() gets (jobs.py has the contract)."""

    def __init__(self, job, event):
        self.job = job
        self._event = event
        self.cloud = bool(job.get("cloud"))
        self.outdir = os.path.join(out_root(), job["kind"])
        self.procs = []

    def out(self, stem=None, ext=None):
        os.makedirs(self.outdir, exist_ok=True)
        k = jobs.KINDS.get(self.job["kind"])
        ext = k.ext if ext is None and k else (ext or "")
        base = stem or self.job["id"]
        p = os.path.join(self.outdir, base + ext)
        n = 2
        while os.path.exists(p):
            p = os.path.join(self.outdir, f"{base}-{n}{ext}")
            n += 1
        return p

    def log(self, text):
        log(self.job["id"], text)

    def progress(self, frac, text=""):
        update(self.job["id"], progress=round(max(0.0, min(1.0, float(frac))), 3), progress_text=text)

    def note(self, **kw):
        j = get(self.job["id"])
        j.setdefault("note", {}).update({k: v for k, v in kw.items() if v is not None})
        update(self.job["id"], note=j["note"])

    def cancelled(self):
        return self._event.is_set()

    def source(self, type_):
        return next((a for a in registry.instances() if a.type == type_), None)

    def run(self, argv, timeout=600):
        """Run a command; killed (its whole process group) when the job is cancelled."""
        p = subprocess.Popen(argv, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, start_new_session=True)
        self.procs.append(p)
        t0 = time.time()
        out, err = "", ""
        try:
            while True:
                try:
                    out, err = p.communicate(timeout=0.5)
                    break
                except subprocess.TimeoutExpired:
                    if self.cancelled() or time.time() - t0 > timeout:
                        with contextlib.suppress(OSError):
                            os.killpg(p.pid, signal.SIGTERM)
                        try:
                            out, err = p.communicate(timeout=10)
                        except subprocess.TimeoutExpired:
                            with contextlib.suppress(OSError):
                                os.killpg(p.pid, signal.SIGKILL)
                            out, err = p.communicate()
                        if not self.cancelled():
                            err = (err or "") + f"\ntimed out after {timeout:.0f} s"
                        break
        finally:
            self.procs.remove(p)
        return subprocess.CompletedProcess(argv, p.returncode, out, err)


# ------------------------------------------------------------------ the GPU gate
def voice_reserve_mib():
    """VRAM kept free for the voice service's own working memory while it speaks (its
    models are resident already)."""
    return int(config.setting("lab", "voice_reserve_mib", VOICE_RESERVE_MIB))


def observed():
    try:
        with open(os.path.join(state_dir(), "vram.json")) as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def _observe(kind, mib):
    o = observed()
    if mib > (o.get(kind) or {}).get("peak_mib", 0):
        o[kind] = {"peak_mib": int(mib), "t": int(time.time())}
        os.makedirs(state_dir(), exist_ok=True)
        tmp = os.path.join(state_dir(), "vram.json.tmp")
        with open(tmp, "w") as f:
            json.dump(o, f, indent=1)
        os.replace(tmp, os.path.join(state_dir(), "vram.json"))


def need_mib(kind):
    k = jobs.KINDS.get(kind)
    return max(k.vram_mib if k else 0, (observed().get(kind) or {}).get("peak_mib", 0))


def gpu_view(pool="media"):
    """{free, total, holds, busy, others, source} of the GPU a pool's jobs run on (MiB), or None.
    media: the first ComfyUI's device. holds: what its own process holds (it gives that up
    for a new job); busy: it runs or holds a queue of prompts that aren't ours."""
    if pool != "media":
        return None
    for a in registry.providers("media"):
        if a.type != "comfyui":
            continue
        try:
            s = a.get_json("/system_stats", timeout=4)
            q = a.get_json("/queue", timeout=4)
        except Exception as e:
            return {"error": caps._why(e), "source": a.name}
        d = (s.get("devices") or [{}])[0]
        mib = 1024 * 1024
        return {"source": a.name, "free": (d.get("vram_free") or 0) // mib, "total": (d.get("vram_total") or 0) // mib,
                "holds": (d.get("torch_vram_total") or 0) // mib,
                "running": len(q.get("queue_running") or []), "pending": len(q.get("queue_pending") or [])}
    return None


# How often the queue asks an idle ComfyUI to unload while a heavy job waits for VRAM (s)
UNLOAD_EVERY = 120


def unload_media(source):
    """Ask the ComfyUI called `source` to unload its models and free its memory (POST /free).
    It applies that between prompts, so nothing running is cut short. -> whether it was asked.

    ComfyUI 0.38 stages models in dynamic VRAM, which its torch_vram_total doesn't count: a
    SeedVR2 left from the last job took 7.8 GiB of the card while `holds` read 1.2 (the lab,
    2026-10-09). So a job short of VRAM next to an idle ComfyUI asks it to give that back,
    rather than wait for the idle-unload sidecar's five minutes."""
    for a in registry.providers("media"):
        if a.type == "comfyui" and a.name == source:
            a.request("/free", data={"unload_models": True, "free_memory": True}, method="POST", timeout=30,
                      raw=True)
            return True
    return False


def gate(kind, view, reserve=None):
    """(start, why). The decision for one heavy job against a GPU view."""
    need = need_mib(kind)
    reserve = voice_reserve_mib() if reserve is None and caps.available("voice") else (reserve or 0)
    if not view:
        return True, ""
    if view.get("error"):
        return False, f"waiting: {view['source']} doesn't answer ({view['error']})"
    if view["total"] and need + reserve > view["total"]:
        return None, (f"it needs {jobs.gib(need)} of VRAM plus {jobs.gib(reserve)} kept for the voice service, more "
                      f"than the GPU has ({jobs.gib(view['total'])})")
    if view["running"] or view["pending"]:
        return False, f"waiting: {view['source']} is busy with other work ({view['running']} running, {view['pending']} queued)"
    can = view["free"] + view["holds"]                   # an idle ComfyUI gives up what it holds
    if can - need < reserve:
        return False, (f"waiting for VRAM: needs {jobs.gib(need)}, {jobs.gib(can)} can be had, "
                       f"{jobs.gib(reserve)} stays free for the voice service")
    return True, ""


class Service:
    """The scheduler and its workers (one process: bromigos lab serve)."""

    def __init__(self, tick=1.0):
        self.tick = tick
        self.workers = {}          # id -> (thread, event, kind)
        self.stop = threading.Event()
        self.started = time.time()
        self.view = None
        self.view_at = 0.0
        self.unloaded_at = 0.0     # when an idle ComfyUI was last asked to unload for a waiting job

    # -- single instance
    def _single(self):
        self._lockf = open(os.path.join(state_dir(), "service.lock"), "a+")
        try:
            fcntl.flock(self._lockf, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return True
        except OSError:
            return False

    def heartbeat(self):
        s = {"pid": os.getpid(), "started": self.started, "heartbeat": time.time(),
             "running": sorted(self.workers), "gpu": self.view, "voice_reserve_mib": voice_reserve_mib()}
        tmp = os.path.join(state_dir(), "service.json.tmp")
        with open(tmp, "w") as f:
            json.dump(s, f)
        os.replace(tmp, os.path.join(state_dir(), "service.json"))

    def recover(self):
        """Jobs left running by a service that died: failed, with a retry hint."""
        for j in list_jobs(states=("running",)):
            update(j["id"], state="failed", finished=time.time(),
                   why="the lab service stopped while it ran: bromigos lab jobs retry " + j["id"])
            log(j["id"], "failed: the service stopped while it ran")

    def serve(self):
        os.makedirs(state_dir(), exist_ok=True)
        if not self._single():
            print("bromigos lab serve: another queue service runs already", flush=True)
            return 4
        signal.signal(signal.SIGTERM, lambda *a: self.stop.set())
        signal.signal(signal.SIGINT, lambda *a: self.stop.set())
        self.recover()
        print(f"bromigos lab serve: up (pid {os.getpid()}, state {state_dir()})", flush=True)
        while not self.stop.is_set():
            try:
                self.step()
            except Exception as e:                       # the queue never dies of one bad step
                print(f"bromigos lab serve: {type(e).__name__}: {e}", flush=True)
            try:
                self.heartbeat()
            except OSError:
                pass
            self.stop.wait(self.tick)
        for jid, (t, ev, _) in list(self.workers.items()):
            ev.set()
        for jid, (t, ev, _) in list(self.workers.items()):
            t.join(timeout=15)
        return 0

    def _view(self):
        if time.time() - self.view_at > 2.5:
            self.view = gpu_view("media")
            self.view_at = time.time()
        return self.view

    def step(self):
        # finished workers
        for jid, (t, ev, _) in list(self.workers.items()):
            try:
                done = get(jid)["state"] in DONE          # finished, though its thread may still be tidying up
            except (OSError, KeyError, ValueError):
                done = True
            if done or not t.is_alive():
                del self.workers[jid]
        # cancel requests for running jobs
        for j in list_jobs(states=("running",)):
            w = self.workers.get(j["id"])
            if w and j.get("cancel"):
                w[1].set()
        pending = sorted(list_jobs(states=("queued", "waiting")), key=lambda j: j.get("created") or 0)
        if not pending:
            return
        jobs.kinds()
        heavy_running = [jid for jid, (_, _, k) in self.workers.items() if k.heavy]
        pools = {}
        for jid, (_, _, k) in self.workers.items():
            if not k.heavy:
                pools[k.gpu] = pools.get(k.gpu, 0) + 1
        heavy_blocked = bool(heavy_running)
        for j in pending:
            k = jobs.KINDS.get(j["kind"])
            if not k:
                self._finish(j, "failed", why=f"no job kind {j['kind']!r} any more")
                continue
            ok, why = k.status()
            if not ok:
                self._finish(j, "failed", why=f"can't run on this lab: {why}")
                continue
            if k.heavy:
                if heavy_blocked:
                    self._wait(j, f"waiting: one heavy job at a time (after {heavy_running[0]})" if heavy_running
                               else "waiting: behind an earlier job")
                    continue
                start, why = gate(j["kind"], self._view() if k.gpu == "media" else None)
                if start is None:
                    self._finish(j, "failed", why=why)
                    continue
                if not start:
                    self._wait(j, why)
                    if k.gpu == "media":
                        self._unload_for(j)
                    heavy_blocked = True           # FIFO among heavy jobs: no overtaking
                    continue
                self._start(j, k)
                heavy_running = [j["id"]]
                heavy_blocked = True
                self.view_at = 0.0
            else:
                limit = POOL_LIMIT.get(k.gpu, 2)
                if pools.get(k.gpu, 0) >= limit:
                    self._wait(j, f"waiting: {limit} {k.gpu} job{'s' if limit > 1 else ''} at a time")
                    continue
                pools[k.gpu] = pools.get(k.gpu, 0) + 1
                self._start(j, k)

    def _unload_for(self, j):
        """A heavy job short of VRAM next to an idle ComfyUI: ask it to unload (at most every
        UNLOAD_EVERY s), and look at the GPU again on the next step."""
        v = self.view
        if not v or v.get("error") or v["running"] or v["pending"]:
            return
        if time.time() - self.unloaded_at < UNLOAD_EVERY:
            return
        self.unloaded_at = time.time()
        try:
            if unload_media(v["source"]):
                log(j["id"], f"asked {v['source']} to unload its models: it's idle, and this job needs the room")
                self.view_at = 0.0
        except Exception as e:                           # the wait goes on; the sidecar unloads in time
            log(j["id"], f"couldn't ask {v['source']} to unload: {caps._why(e)}")

    def _wait(self, j, why):
        if j["state"] != "waiting" or j.get("why") != why:
            update(j["id"], state="waiting", why=why)
            log(j["id"], why)

    def _finish(self, j, state, why="", outputs=None):
        j = update(j["id"], state=state, why=why, finished=time.time(),
                   **({"outputs": outputs} if outputs is not None else {}))
        log(j["id"], f"{state}" + (f": {why}" if why else ""))
        self.notify(j)
        return j

    def notify(self, j):
        if j["state"] == "succeeded":
            outs = j.get("outputs") or []
            notify(f"Lab: {j.get('preset') or j['kind']} done",
                   (", ".join(os.path.basename(o) for o in outs[:3]) or "no files") +
                   (f"\n{os.path.dirname(outs[0])}" if outs else ""))
        elif j["state"] == "failed":
            notify(f"Lab: {j.get('preset') or j['kind']} failed", j.get("why") or "see bromigos lab jobs logs " + j["id"],
                   urgency="critical")

    def _start(self, j, k):
        ev = threading.Event()
        j = update(j["id"], state="running", started=time.time(), why="", vram_mib=need_mib(j["kind"]) if k.heavy else 0)
        log(j["id"], f"started ({k.title})")
        t = threading.Thread(target=self._run, args=(j, k, ev), daemon=True, name=f"job-{j['id']}")
        self.workers[j["id"]] = (t, ev, k)
        t.start()

    def _sample(self, k, stop, base, out):
        """The most VRAM the GPU lost while the job ran (MiB), sampled every 0.5 s."""
        while not stop.is_set():
            v = gpu_view("media")
            if v and not v.get("error"):
                out[0] = max(out[0], base - v["free"])
            stop.wait(0.5)

    def _run(self, j, k, ev):
        ctx = Ctx(j, ev)
        stop_s = threading.Event()
        peak = [0]
        sampler = None
        if k.heavy and k.gpu == "media":
            v = gpu_view("media")
            if v and not v.get("error"):
                sampler = threading.Thread(target=self._sample, args=(k, stop_s, v["free"] + v["holds"], peak),
                                           daemon=True)
                sampler.start()
        try:
            outs = k.run(get(j["id"]), ctx) or []
            if ev.is_set():
                self._cancel_remote(j)
                self._finish(j, "cancelled", why="cancelled while it ran", outputs=[o for o in outs if os.path.exists(o)])
            else:
                outs = [o for o in outs if o and os.path.exists(o)]
                self._finish(j, "succeeded", outputs=outs)
        except jobs.JobError as e:
            if ev.is_set():
                self._cancel_remote(j)
                self._finish(j, "cancelled", why="cancelled while it ran")
            else:
                self._finish(j, "failed", why=str(e))
        except Exception as e:
            self._finish(j, "failed", why=f"{type(e).__name__}: {str(e)[:300]}")
        finally:
            stop_s.set()
            if sampler:
                sampler.join(timeout=2)
                if peak[0] > 256 and get(j["id"])["state"] == "succeeded":
                    _observe(j["kind"], peak[0])
                    log(j["id"], f"the GPU lost at most {jobs.gib(peak[0])} of free VRAM while it ran")

    def _cancel_remote(self, j):
        """A cancelled image job: the prompt bromigos art queued on ComfyUI (its client id) is
        removed or interrupted, so the GPU is free again at once."""
        for a in registry.providers("media"):
            if a.type != "comfyui":
                continue
            try:
                q = a.get_json("/queue", timeout=4)
                mine = lambda e: isinstance(e, list) and len(e) > 3 and (e[3] or {}).get("client_id") == "bromigos-art"  # noqa: E731
                pend = [e[1] for e in q.get("queue_pending") or [] if mine(e)]
                if pend:
                    a.request("/queue", data={"delete": pend}, method="POST", timeout=6, raw=True)
                if any(mine(e) for e in q.get("queue_running") or []):
                    a.request("/interrupt", data={}, method="POST", timeout=6, raw=True)
                log(j["id"], f"asked {a.name} to drop its prompt")
            except Exception as e:
                log(j["id"], f"couldn't reach {a.name} to drop its prompt: {e}")
