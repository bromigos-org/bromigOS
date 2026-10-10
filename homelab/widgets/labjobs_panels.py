"""LAB JOBS: the lab job queue (bromigos-homelab's `bromigos lab run|jobs`; docs/lab.md,
"Jobs"): what runs, how far along it is, what waits and why, the GPU it waits for, and what
finished lately.

It reads the queue's own files through bromigos_homelab.jobqueue (the same as `bromigos
lab jobs --json`), every 3 s while it's seen. A panel generator (widgets/plugins.py): it
offers the "labjobs" panel only when a homelab is configured.

Clicks: a finished job opens what it made; any other opens its log in a terminal. Cancel
asks a second click to confirm, then runs `bromigos lab jobs cancel <id>`.
"""
import os
import sys
import time

_HERE = os.path.dirname(os.path.realpath(__file__))
for _p in (os.path.join(os.path.dirname(_HERE), "lib"),):        # a bromigOS checkout's homelab/lib
    if os.path.isdir(_p) and _p not in sys.path:
        sys.path.insert(1, _p)

import panels  # noqa: E402

sys.path.append(os.path.join(os.path.dirname(os.path.realpath(panels.__file__)), "plugins"))
import _kit as K  # noqa: E402

import draw as D  # noqa: E402
import sources as S  # noqa: E402

NAME = "labjobs"
ACTIVE = ("running", "waiting", "queued")
DONE = ("succeeded", "failed", "cancelled")
COLOR = {"running": "phosphor", "waiting": "amber", "queued": "soft", "succeeded": "phosphor", "failed": "danger",
         "cancelled": "static"}
RECENT_H = 24


def _demo_lab():
    return os.environ.get("BROMIGOS_WIDGETS_DEMO_LAB") == "1"


def names():
    return {NAME: 1} if available()[0] else {}


def available():
    """(True, "") when the panel has a source, else (False, why): names()' check, no network."""
    if _demo_lab():
        return True, ""
    try:
        import bromigos_homelab as H
    except ImportError:
        return False, "bromigos-homelab isn't installed"
    return (True, "") if H.configured() else (False, "no homelab is configured (bromigos setup homelab)")


def panel(name):
    return LabJobsPanel, {"visible": False}


# ------------------------------------------------------------------ the data
def split(jobs, now=None, recent_h=RECENT_H):
    """(active: running, then waiting, then queued, oldest first; recent: finished in the
    last recent_h hours, newest first)."""
    now = now or time.time()
    rank = {s: i for i, s in enumerate(ACTIVE)}
    active = sorted((j for j in jobs if j.get("state") in ACTIVE),
                    key=lambda j: (rank[j["state"]], j.get("created") or 0))
    recent = sorted((j for j in jobs if j.get("state") in DONE
                     and now - (j.get("finished") or j.get("created") or 0) < recent_h * 3600),
                    key=lambda j: -(j.get("finished") or j.get("created") or 0))
    return active, recent


def what(j):
    """The job in a few words: its preset or kind, and its prompt or text."""
    w = j.get("preset") or j.get("kind") or "job"
    p = j.get("prompt") or j.get("text") or ""
    return w, " ".join(p.split())


def progress(j):
    """0..1 for a running job that reports it, else None."""
    p = j.get("progress")
    if j.get("state") != "running" or p in (None, 0, 0.0) and not j.get("progress_text"):
        return None
    try:
        return max(0.0, min(1.0, float(p)))
    except (TypeError, ValueError):
        return None


def gpu_of(service):
    """{source, free, total, used} (MiB) of the GPU the queue watches, or None."""
    g = (service or {}).get("gpu") or {}
    if not g.get("total"):
        return None
    return {"source": g.get("source"), "free": g.get("free"), "total": g["total"],
            "used": g["total"] - (g.get("free") or 0), "running": g.get("running"), "pending": g.get("pending")}


def day_stats(recent):
    out = {"succeeded": 0, "failed": 0, "cancelled": 0}
    for j in recent:
        out[j["state"]] = out.get(j["state"], 0) + 1
    return out


def read_queue():
    from bromigos_homelab import jobqueue as Q
    return {"jobs": Q.list_jobs(limit=80), "service": Q.service_info(), "state": Q.service_state()}


def demo_queue():
    now = time.time()
    J = []

    def job(i, kind, state, prompt=None, text=None, mins=0, dur=0, **kw):
        created = now - mins * 60
        j = {"id": f"1009-{2100 + i:06d}-{kind[:6]}-{i:04x}", "kind": kind, "preset": kw.pop("preset", None),
             "state": state, "prompt": prompt, "text": text, "created": created,
             "started": created + 20 if state != "queued" else None,
             "finished": created + 20 + dur * 60 if state in DONE else None, "why": kw.pop("why", ""),
             "progress": kw.pop("progress", 0.0), "progress_text": kw.pop("progress_text", ""),
             "outputs": kw.pop("outputs", []), "vram_mib": kw.pop("vram_mib", None), "by": kw.pop("by", "you")}
        J.append(j)
    job(1, "video", "running", "A paper lantern drifting over a harbour at night, slow pan", mins=6, progress=0.62,
        progress_text="step 31 of 50", vram_mib=22000)
    job(2, "image", "waiting", "A brass relay mast on a hill at dusk", mins=4, vram_mib=16384,
        why="waiting for 16.0 GiB of VRAM (11.2 GiB free)")
    job(3, "voice", "queued", text="The relays are lit. The queue is clear.", mins=1)
    job(4, "image", "succeeded", "Fog over a lighthouse, painterly", mins=35, dur=1, vram_mib=16384,
        outputs=["/srv/demo/lighthouse.png"])
    job(5, "transcribe", "succeeded", text=None, mins=80, dur=3, outputs=["/srv/demo/meeting.txt"], preset="meeting")
    job(6, "llm", "failed", "Summarise the field notes", mins=140, dur=0, why="the model server answered 503")
    job(7, "image", "succeeded", "A cutaway of a relay station, blueprint style", mins=60 * 5, dur=2, vram_mib=16384,
        outputs=["/srv/demo/relay.png"])
    job(8, "voice", "cancelled", text="A line nobody needed", mins=60 * 9, dur=0, why="cancelled before it started")
    return {"jobs": J, "state": "running",
            "service": {"pid": 1, "heartbeat": now, "gpu": {"source": "media", "free": 11468, "total": 32607,
                                                             "running": 1, "pending": 1}}}


# ------------------------------------------------------------------ the panel
class LabJobsPanel(K.KitPanel):
    name, title = NAME, "LAB JOBS"
    description = "The lab job queue: what runs and how far along, what waits and why, and what finished"
    category, reads = "homelab", "the lab job queue (bromigos lab jobs)"
    width, height = 460, 300
    interval = 3.0
    sizes = {
        "compact": ((240, 120), (380, 190), (280, 140)),
        "standard": ((400, 220), (620, 420), (460, 300)),
        "wide": ((640, 200), (1100, 380), (800, 240)),
        "tall": ((380, 440), (560, 900), (420, 580)),
        "large": ((660, 480), (1200, 900), (780, 580)),
    }
    default_size = "standard"

    @classmethod
    def available(cls):
        return available()
    settings = [{"key": "recent_hours", "label": "Show finished jobs from the last … hours", "kind": "number",
                 "default": RECENT_H}]

    def __init__(self, cfg=None, wake=None):
        super().__init__(cfg, wake)
        self.armed = {}                    # job id -> when its cancel was clicked once
        if K.demo():
            self.q = demo_queue()
        else:
            self.poll = self.poller(read_queue, every=3, idle=20)

    def queue(self):
        return self.q if K.demo() else self.poll.data

    # ---- actions
    def _open(self, j):
        if j.get("state") == "succeeded" and j.get("outputs"):
            K.spawn(["xdg-open", j["outputs"][0]])
        else:
            K.terminal(["bromigos", "lab", "jobs", "logs", j["id"]], title=f"lab job {j['id']}")

    def _cancel(self, j):
        now = time.monotonic()
        if now - self.armed.get(j["id"], 0) < 4:
            self.armed.pop(j["id"], None)
            K.spawn(["bromigos", "lab", "jobs", "cancel", j["id"]])
            if getattr(self, "poll", None):
                self.poll.kick()
        else:
            self.armed[j["id"]] = now

    # ---- drawing
    def draw(self, cr, w, h):
        cls = self.size_class(w, h)
        q = self.queue()
        jobs = (q or {}).get("jobs") or []
        active, recent = split(jobs, recent_h=float(self.conf.get("recent_hours", RECENT_H) or RECENT_H))
        running = [j for j in active if j["state"] == "running"]
        st = (q or {}).get("state")
        right = None
        if q is not None and cls != "compact":
            right = (f"{len(running)} RUNNING · {len(active) - len(running)} WAITING" if active else "IDLE") + \
                    ("" if st == "running" else " · SERVICE " + str(st).upper())
        top = D.frame(cr, w, h, self.title, right, "amber" if st not in ("running", None) and active else "static")
        self.region(0, 0, w, 34, "The lab job queue (bromigos lab jobs), read every 3 s: "
                    f"the service is {st or 'unknown'}; {len(active)} job(s) in the queue, {len(recent)} finished "
                    f"in the last {self.conf.get('recent_hours', RECENT_H)} h. A finished job opens what it made; any "
                    "other opens its log.")
        if q is None:
            err = getattr(getattr(self, "poll", None), "error", None)
            self.empty(cr, w, h, top, "CAN'T READ THE QUEUE" if err else "READING…", err or "", color="amber" if err
                       else "static")
            return
        if not active and not recent:
            self.empty(cr, w, h, top, "NO JOBS", "Nothing queued, and nothing finished lately. Start one with "
                       "`bromigos lab run image --prompt \"…\"`, or ask VECTOR.", color="static",
                       tip="The lab job queue is empty. `bromigos lab run KIND` starts a job; `bromigos lab jobs` lists them.")
            return
        x0, x1 = 16, w - 16
        g = gpu_of(q.get("service"))
        if cls == "compact":
            self._compact(cr, active, recent, x0, x1, top, h)
        elif cls == "wide":
            split_x = x0 + (x1 - x0) * 0.5
            y = self._gpu(cr, g, active, x0, split_x - 12, top) if g else top
            self._jobs(cr, active, x0, split_x - 12, y + 4, h - 12, cancel=True)
            self._jobs(cr, recent, split_x + 12, x1, top, h - 12, title="FINISHED")
        elif cls == "large":
            y = self._gpu(cr, g, active, x0, x1, top, big=True) if g else top
            y = self._timeline(cr, jobs, x0, x1, y + 6, y + 70)
            mid = x0 + (x1 - x0) * 0.55
            kinds_h = min(150, (h - y) - 180) if h - y > 260 else 0
            ya = self._jobs(cr, active, x0, mid - 12, y + 8, h - 12 - kinds_h, cancel=True, detail=True)
            yb = self._jobs(cr, recent, mid + 12, x1, y + 8, h - 12 - kinds_h, title="FINISHED", stats=True)
            if kinds_h:
                self._kinds(cr, jobs, x0, x1, max(ya, yb) + 16, h - 12)
        elif cls == "tall":
            y = self._gpu(cr, g, active, x0, x1, top) if g else top
            y = self._jobs(cr, active, x0, x1, y + 4, h - 12, cancel=True, detail=True)
            y = self._jobs(cr, recent, x0, x1, y + 10, h - 12, title="FINISHED")
            if h - y > 140:
                self._kinds(cr, jobs, x0, x1, y + 16, h - 12)
        else:
            y = self._gpu(cr, g, active, x0, x1, top) if g else top
            y = self._jobs(cr, active, x0, x1, y + 4, h - 12, cancel=True)
            if h - 12 - y > 40:
                self._jobs(cr, recent, x0, x1, y + 8, h - 12, title="FINISHED", limit=max(1, int((h - y - 40) // 24)))

    def _compact(self, cr, active, recent, x0, x1, top, h):
        run = next((j for j in active if j["state"] == "running"), None)
        if run:
            k, p = what(run)
            pr = progress(run)
            D.label(cr, x0, top + 2, f"RUNNING · {k}", "phosphor", size=11)
            D.text(cr, x0, top + 18, p or run["id"], 11, "soft", "regular", width=x1 - x0)
            if pr is not None:
                D.cells(cr, x0, top + 38, x1 - x0 - 50, 8, pr, n=20, warn=2, crit=2)
                D.text(cr, x1, top + 33, f"{pr * 100:.0f}%", 13, "phosphor", "bold", align="right")
            self.region(x0, top, x1 - x0, 56, self._tip(run), lambda j=run: self._open(j))
        else:
            j = recent[0] if recent else active[0]
            k, p = what(j)
            D.label(cr, x0, top + 2, f"{j['state'].upper()} · {k}", COLOR[j["state"]], size=11)
            D.text(cr, x0, top + 20, p or j["id"], 11, "soft", "regular", width=x1 - x0)
            self.region(x0, top, x1 - x0, 40, self._tip(j), lambda j=j: self._open(j))
        waiting = [j for j in active if j["state"] != "running"]
        y = h - 24
        D.label(cr, x0, y, f"{len(waiting)} WAITING" if waiting else "NOTHING WAITING", "amber" if waiting else "static",
                size=10)
        D.label(cr, x1, y, f"{len(recent)} DONE TODAY", "static", size=10, align="right")
        self.region(x0, y - 2, x1 - x0, 16, f"{len(waiting)} job(s) waiting or queued; {len(recent)} finished lately")

    def _tip(self, j):
        k, p = what(j)
        bits = [f"{k} {j['id']}: {j['state']}"]
        if progress(j) is not None:
            bits.append(f"{progress(j) * 100:.0f}%" + (f" ({j['progress_text']})" if j.get("progress_text") else ""))
        if j.get("why") and j["state"] in ("waiting", "failed", "cancelled"):
            bits.append(j["why"])
        if j.get("vram_mib"):
            bits.append(f"needs {j['vram_mib'] / 1024:.1f} GiB of VRAM")
        if j.get("started") and j["state"] == "running":
            bits.append(f"started {K.ago(j['started'])} ago")
        if j.get("finished"):
            bits.append(f"finished {K.ago(j['finished'])} ago" + (f" after {S.duration(j['finished'] - j['started'])}"
                                                                    if j.get("started") else ""))
        if j.get("by") and j["by"] != "you":
            bits.append(f"asked by {j['by']}")
        if p:
            bits.append(f"“{p[:90]}”")
        tip = " · ".join(bits) + ". "
        if j["state"] == "succeeded" and j.get("outputs"):
            tip += f"Click to open {os.path.basename(j['outputs'][0])}."
        else:
            tip += "Click to read its log in a terminal (bromigos lab jobs logs)."
        return tip

    def _gpu(self, cr, g, active, x0, x1, top, big=False):
        """The GPU the queue waits for: used, free, and what the next job needs."""
        D.label(cr, x0, top, f"GPU · {g['source'] or 'lab'}", "dim", size=10)
        free = g["free"] or 0
        D.label(cr, x1, top, f"{free / 1024:.1f} GIB FREE OF {g['total'] / 1024:.0f}", "soft", size=10, align="right")
        bh = 12 if big else 8
        by = top + 16
        D.bar(cr, x0, by, x1 - x0, bh, g["used"] / g["total"], "cyan")
        nxt = next((j for j in active if j["state"] in ("waiting", "queued") and j.get("vram_mib")), None)
        tip = (f"VRAM on the GPU the queue watches ({g['source'] or 'the lab'}): {g['used'] / 1024:.1f} GiB in use, "
               f"{free / 1024:.1f} GiB free of {g['total'] / 1024:.1f} GiB")
        if nxt:
            need = nxt["vram_mib"] / g["total"]
            sx = x0 + (x1 - x0) * g["used"] / g["total"]
            fits = nxt["vram_mib"] <= free
            D.src(cr, "phosphor" if fits else "amber", 0.35)
            cr.rectangle(sx, by, min(x1 - sx, (x1 - x0) * need), bh)
            cr.fill()
            D.src(cr, "phosphor" if fits else "amber", 0.9)
            cr.set_line_width(1)
            cr.rectangle(sx + 0.5, by + 0.5, max(1, min(x1 - sx, (x1 - x0) * need) - 1), bh - 1)
            cr.stroke()
            tip += (f". The next job, {what(nxt)[0]} {nxt['id']}, needs {nxt['vram_mib'] / 1024:.1f} GiB"
                    + (" and fits" if fits else ": it waits until that much is free") + " (the outlined part)")
        self.region(x0, top - 2, x1 - x0, bh + 20, tip)
        return by + bh + 10

    def _jobs(self, cr, jobs, x0, x1, top, bottom, title=None, cancel=False, detail=False, limit=None, stats=False):
        y = top
        if title:
            lab = f"{title} · {len(jobs)}"
            if stats:
                s = day_stats(jobs)
                lab += f" · {s['succeeded']} OK" + (f" · {s['failed']} FAILED" if s["failed"] else "")
            lw = D.label(cr, x0, y, lab, "dim", size=10)[0]
            D.rule(cr, x0 + lw + 8, y + 7, x1, "dim", 0.3)
            self.region(x0, y - 2, x1 - x0, 16, f"Jobs that finished in the last {self.conf.get('recent_hours', RECENT_H)}"
                        " hours, newest first")
            y += 18
        if not jobs:
            if not title:
                D.text(cr, x0, y, "Nothing queued.", 11, "static", "regular")
                self.region(x0, y - 2, x1 - x0, 18, "No job is running or waiting")
                return y + 20
            D.text(cr, x0, y, "None lately.", 11, "static", "regular")
            return y + 20
        shown = 0
        for j in jobs:
            run = j["state"] == "running"
            pr = progress(j)
            rh = 22 + (14 if detail and (pr is not None or j.get("why")) else 0) + (12 if run and pr is not None and not
                                                                                   detail else 0)
            if y + rh > bottom or (limit and shown >= limit):
                break
            self._job(cr, j, x0, x1, y, rh, cancel, detail)
            y += rh + 2
            shown += 1
        if shown < len(jobs):
            D.label(cr, x1, min(y, bottom - 12), f"+{len(jobs) - shown} MORE", "static", size=10, align="right")
            self.region(x1 - 90, min(y, bottom - 12) - 2, 90, 14, f"{len(jobs) - shown} more; `bromigos lab jobs` "
                        "lists them all")
            y += 14
        return y

    def _job(self, cr, j, x0, x1, y, rh, cancel, detail):
        st = j["state"]
        col = COLOR[st]
        k, p = what(j)
        D.src(cr, col, 0.95 if st in ("running", "failed") else 0.5)
        cr.rectangle(x0, y + 2, 3, rh - 6)
        cr.fill()
        rx = x1
        if cancel and st in ACTIVE:
            armed = time.monotonic() - self.armed.get(j["id"], 0) < 4
            bw = self.button(cr, rx - (64 if armed else 24), y, "CANCEL?" if armed else "×",
                             f"Cancel {k} {j['id']}: " + ("click again to cancel it now (bromigos lab jobs cancel)"
                                                          if armed else "click, then click again within 4 s to confirm"),
                             lambda j=j: self._cancel(j), color="danger", on=armed, h=18)
            rx -= bw + 8
        tag = {"running": "", "waiting": "WAITING", "queued": "QUEUED", "succeeded": K.ago(j.get("finished")),
               "failed": "FAILED", "cancelled": "CANCELLED"}[st]
        pr = progress(j)
        if st == "running" and pr is not None:
            tag = f"{pr * 100:.0f}%"
        tw = D.label(cr, rx, y + 3, tag, col, size=10, align="right")[0] if tag else 0
        kw = D.label(cr, x0 + 10, y + 3, k, col if st != "queued" else "soft", size=10)[0]
        D.text(cr, x0 + 18 + kw, y + 2, p or j["id"], 11, "soft" if st in ACTIVE else "static", "regular",
               width=max(10, rx - tw - x0 - kw - 34))
        yy = y + 18
        if st == "running" and pr is not None:
            D.bar(cr, x0 + 10, yy, rx - x0 - 10, 4, pr, "phosphor")
            if detail and j.get("progress_text"):
                D.text(cr, x0 + 10, yy + 6, j["progress_text"], 10, "static", "regular", width=rx - x0 - 10)
        elif detail and j.get("why"):
            D.text(cr, x0 + 10, yy - 1, j["why"], 10, "amber" if st == "waiting" else "static", "regular",
                   width=rx - x0 - 10)
        self.region(x0, y, rx - x0 - 4, rh, self._tip(j), lambda j=j: self._open(j))

    def _timeline(self, cr, jobs, x0, x1, top, bottom):
        """The last 12 hours: each job a bar from when it started to when it finished (or now)."""
        now = time.time()
        span = 6 * 3600
        D.label(cr, x0, top, "LAST 6 HOURS", "dim", size=10)
        D.label(cr, x0 + (x1 - x0) / 2, top, "-3H", "static", size=10, align="center")
        D.label(cr, x1, top, "NOW", "static", size=10, align="right")
        by = top + 16
        bh = bottom - by
        D.src(cr, "void", 0.8)
        cr.rectangle(x0, by, x1 - x0, bh)
        cr.fill()
        D.src(cr, "guard", 1)
        cr.set_line_width(1)
        for k in range(1, 12):
            gx = round(x0 + (x1 - x0) * k / 12) + 0.5
            cr.move_to(gx, by)
            cr.line_to(gx, bottom)
        cr.stroke()
        lanes = {}
        shown = [j for j in jobs if (j.get("finished") or now) > now - span and (j.get("started") or j.get("created"))]
        for j in sorted(shown, key=lambda j: j.get("started") or j.get("created")):
            t0 = j.get("started") or j.get("created")
            t1 = j.get("finished") or now
            lane = next((i for i in range(4) if lanes.get(i, 0) <= t0), 3)
            lanes[lane] = t1 + span / 60
            lh = (bh - 4) / 4
            sx = x0 + (x1 - x0) * max(0.0, 1 - (now - t0) / span)
            ex = x0 + (x1 - x0) * max(0.0, 1 - (now - t1) / span)
            D.src(cr, COLOR[j["state"]], 0.9 if j["state"] in ("running", "failed", "succeeded") else 0.45)
            cr.rectangle(sx, by + 2 + lane * lh, max(5, ex - sx), lh - 2)
            cr.fill()
            self.region(sx, by + 2 + lane * lh, max(6, ex - sx), lh - 2, self._tip(j), lambda j=j: self._open(j))
        self.region(x0, top - 2, x1 - x0, 16, "The last 6 hours of the queue: each job's bar runs from its start to its "
                    "end (or now); green succeeded or running, red failed, amber waiting. Gridlines every 30 minutes.")
        return bottom

    def _kinds(self, cr, jobs, x0, x1, top, bottom):
        """Each kind of job lately: how many ran, how many failed, and how long one takes."""
        _, recent = split(jobs, recent_h=float(self.conf.get("recent_hours", RECENT_H) or RECENT_H))
        kinds = {}
        for j in recent:
            k = kinds.setdefault(j.get("kind") or "job", {"n": 0, "failed": 0, "secs": []})
            k["n"] += 1
            k["failed"] += j["state"] == "failed"
            if j["state"] == "succeeded" and j.get("started") and j.get("finished"):
                k["secs"].append(j["finished"] - j["started"])
        if not kinds:
            return
        lw = D.label(cr, x0, top, "BY KIND", "dim", size=10)[0]
        D.rule(cr, x0 + lw + 8, top + 7, x1, "dim", 0.3)
        self.region(x0, top - 2, x1 - x0, 16, "The jobs that finished lately, by kind: how many, how many failed, "
                    "and the median time one took")
        y = top + 20
        most = max(k["n"] for k in kinds.values())
        for name, k in sorted(kinds.items(), key=lambda kv: -kv[1]["n"]):
            if y + 18 > bottom:
                break
            secs = sorted(k["secs"])
            med = secs[len(secs) // 2] if secs else None
            D.label(cr, x0, y + 1, name, "soft", size=10)
            bx, bw = x0 + 110, min(420, x1 - x0 - 110 - 150)
            ok = k["n"] - k["failed"]
            D.bar(cr, bx, y + 4, bw * k["n"] / most, 8, 1.0, "phosphor")
            if k["failed"]:
                D.src(cr, "danger", 1)
                cr.rectangle(bx + bw * ok / most, y + 4, bw * k["failed"] / most, 8)
                cr.fill()
            D.text(cr, x1, y, f"{k['n']}" + (f" · {k['failed']} failed" if k["failed"] else "")
                   + (f" · {S.duration(med)}" if med is not None else ""), 10, "static", "regular", align="right")
            self.region(x0, y - 2, x1 - x0, 18, f"{name}: {k['n']} finished lately, {k['failed']} failed"
                        + (f"; one takes about {S.duration(med)}" if med is not None else ""))
            y += 20
