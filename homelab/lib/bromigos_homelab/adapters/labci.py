"""CI and packages: GitHub's Actions Runner Controller (runners) and a pacman repository's
channels (packages).

    [[source]]
    type = "arc"                        # runner scale sets, read through the kubernetes source: each
                                        # listener pod, its runner pods, and the listener's own count
                                        # of assigned jobs (its log); gha_* metrics when it exports them

    [[source]]
    type = "pacman-repo"                # bromigOS's repository, found from /etc/pacman.conf's
    # repo = "bromigos"                 # [bromigos] Server line (or endpoint = its base URL)
    # channels = { edge = "bromigos/x86_64", stable = "bromigos/stable/x86_64" }
    # github_repo = "org/repo"          # whose publish workflow to check (gh's login)
    # workflow = "packages.yml"
    # stale_hours = 24                  # a published build this much older than the newest run: stale

Per channel: the newest package build in its database (name, version, when) and how many
packages it has. The doctor checks the publish workflow's latest run and whether the
database caught up with it.
"""
import io
import json
import os
import re
import shutil
import subprocess
import tarfile
import time
import urllib.error

from ..registry import Unreachable, register
from . import labcommon as L

# ------------------------------------------------------------------ Actions Runner Controller
LISTENER = "app.kubernetes.io/component=runner-scale-set-listener"
SCALE_SET = "actions.github.com/scale-set-name"


def listener_stats(text):
    """The listener's latest view of its scale set, from its log: {assigned, min, max, current}
    (gha-runner-scale-set 0.10+) or {assigned, running_jobs, registered, busy, idle} (older)."""
    last = {}
    for line in (text or "").splitlines():
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            d = json.loads(line)
        except ValueError:
            continue
        msg = d.get("msg") or d.get("message") or ""
        if msg.startswith("Calculated target runner count"):
            last = {"assigned": d.get("assigned job"), "min": d.get("min"), "max": d.get("max"),
                    "current": d.get("currentRunnerCount")}
        elif isinstance(d.get("statistics"), dict):
            s = d["statistics"]
            last = {"assigned": s.get("totalAssignedJobs"), "running_jobs": s.get("totalRunningJobs"),
                    "registered": s.get("totalRegisteredRunners"), "busy": s.get("totalBusyRunners"),
                    "idle": s.get("totalIdleRunners")}
    return last


def runner_records(listeners, runner_pods, stats):
    """runners records: a scale set per listener, its runner pods and the listener's numbers."""
    pods_by = {}
    for p in runner_pods:
        pods_by.setdefault((p["metadata"].get("labels") or {}).get(SCALE_SET), []).append(p)
    out = []
    for lp in listeners:
        lb = lp["metadata"].get("labels") or {}
        name = lb.get(SCALE_SET) or lp["metadata"]["name"]
        ps = pods_by.get(name, [])
        running = sum(1 for p in ps if (p.get("status") or {}).get("phase") == "Running")
        pending = sum(1 for p in ps if (p.get("status") or {}).get("phase") == "Pending")
        failing = [L.pod_waiting(p) for p in ps if L.pod_waiting(p) in ("CrashLoopBackOff", "ImagePullBackOff",
                                                                         "ErrImagePull", "CreateContainerConfigError")]
        s = stats.get(name) or {}
        assigned = s.get("assigned")
        busy = s.get("busy") if s.get("busy") is not None else running
        queued = max(0, int(assigned) - running) if assigned is not None else pending
        online = L.pod_ready(lp)
        rec = {"name": name, "org": lb.get("actions.github.com/organization"), "online": online, "runners": running,
               "busy": busy, "idle": s.get("idle"), "queued": queued, "min": s.get("min"), "max": s.get("max"),
               "pending": pending, "failing": failing}
        rec["state"] = "crit" if not online or failing else \
            "warn" if queued and rec["max"] is not None and running >= rec["max"] else "ok"
        out.append(rec)
    return sorted(out, key=lambda r: r["name"])


def runner_records_from_metrics(get):
    def by(m):
        return {r["labels"].get("name"): r for r in get(m)}
    reg, busy, idle = by("gha_registered_runners"), by("gha_busy_runners"), by("gha_idle_runners")
    asg, run, mn, mx = by("gha_assigned_jobs"), by("gha_running_jobs"), by("gha_min_runners"), by("gha_max_runners")
    out = []
    for n in sorted(set(reg) | set(asg)):
        v = {k: (d.get(n) or {}).get("value") for k, d in (("reg", reg), ("busy", busy), ("idle", idle), ("asg", asg),
                                                            ("run", run), ("min", mn), ("max", mx))}
        lb = ((reg.get(n) or asg.get(n)) or {}).get("labels") or {}
        queued = max(0, int((v["asg"] or 0) - (v["run"] or 0)))
        out.append({"name": n, "org": lb.get("organization"), "online": True, "runners": int(v["reg"] or 0),
                    "busy": int(v["busy"] or 0), "idle": int(v["idle"] or 0), "queued": queued,
                    "min": v["min"], "max": v["max"],
                    "state": "warn" if queued and v["max"] is not None and (v["reg"] or 0) >= v["max"] else "ok"})
    return out


def runner_findings(recs, source=None):
    out = []
    for r in recs:
        rid, title = f"runners.{r['name']}", f"Runner pool {r['name']}"
        if not r["online"]:
            out.append(L.finding(rid, title, "fail", "its listener isn't running",
                                 "Jobs for this pool won't start: look at the listener pod in the controller's "
                                 "namespace (its GitHub credentials, usually).", source))
        elif r.get("failing"):
            out.append(L.finding(rid, title, "fail", f"runner pods failing ({', '.join(sorted(set(r['failing'])))})",
                                 "Its runners can't start: check the runner image and the pool's pod template.", source))
        elif r["queued"] and r.get("max") is not None and r["runners"] >= r["max"]:
            out.append(L.finding(rid, title, "warn", f"{r['queued']} job(s) queued, {r['runners']} of {r['max']} runners busy",
                                 "The pool is full: jobs wait. Raise maxRunners if the nodes have room.", source))
    if recs and not out:
        out.append(L.finding("runners.all", "Runner pools", "ok", f"{len(recs)} pools online · "
                             f"{sum(r['runners'] for r in recs)} running · {sum(r['queued'] for r in recs)} queued",
                             source=source))
    return out


@register
class ARC(L.LabAdapter):
    type = "arc"
    provides = ("runners",)

    @classmethod
    def detect(cls, d):
        return [{"type": "arc"}] if d.pods(LISTENER) or d.has_metric("gha_registered_runners") else []

    def _kube(self):
        listeners = L.pods(self.opt("namespace"), LISTENER)
        runners = [p for p in L.pods(None, SCALE_SET)
                   if (p["metadata"].get("labels") or {}).get("app.kubernetes.io/component") != "runner-scale-set-listener"]
        stats = {}
        for lp in listeners:
            name = (lp["metadata"].get("labels") or {}).get(SCALE_SET)
            try:
                stats[name] = listener_stats(L.pod_logs(lp["metadata"]["namespace"], lp["metadata"]["name"], tail=60))
            except Exception:
                stats[name] = {}
        return runner_records(listeners, runners, stats)

    def runners(self):
        rows = L.mq_soft("gha_registered_runners")
        if rows:
            return runner_records_from_metrics(L.mq_soft)
        if not L.kube():
            raise Unreachable(f"{self.name}: no gha_* metrics and no kubernetes source")
        return self._kube()

    def doctor(self):
        return runner_findings(self.runners(), self.name)


# ------------------------------------------------------------------ a pacman repository

BROMIGOS_CHANNELS = {"edge": "{repo}/{arch}", "rc": "{repo}/rc/{arch}", "stable": "{repo}/stable/{arch}"}


def pacman_server(repo, conf="/etc/pacman.conf"):
    """The first http(s) Server of [repo] in pacman.conf, or ""."""
    try:
        with open(conf) as f:
            text = f.read()
    except OSError:
        return ""
    sec = None
    for line in text.splitlines():
        line = line.split("#", 1)[0].strip()
        if line.startswith("[") and line.endswith("]"):
            sec = line[1:-1]
        elif sec == repo and line.startswith("Server") and "=" in line:
            url = line.split("=", 1)[1].strip()
            if url.startswith(("http://", "https://")):
                return url
    return ""


def repo_base(server):
    """https://host/$repo/$arch (or …/$repo/stable/$arch) -> https://host."""
    return server.split("/$repo", 1)[0].rstrip("/") if "$repo" in server else server.rstrip("/")


def parse_db(data):
    """[{name, version, builddate}] from a pacman sync database (a tar, gz/xz/zst)."""
    if data[:4] == b"\x28\xb5\x2f\xfd":                    # zstd: tarfile needs Python 3.14's, else the CLI
        try:
            tf = tarfile.open(fileobj=io.BytesIO(data), mode="r:zst")
        except (tarfile.CompressionError, tarfile.ReadError, ValueError):
            if not shutil.which("zstd"):
                raise ValueError("a zstd database needs Python 3.14 or the zstd command") from None
            data = subprocess.run(["zstd", "-dc"], input=data, capture_output=True, timeout=30).stdout
            tf = tarfile.open(fileobj=io.BytesIO(data), mode="r:")
    else:
        tf = tarfile.open(fileobj=io.BytesIO(data), mode="r:*")
    out = []
    with tf:
        for m in tf.getmembers():
            if not m.isfile() or not m.name.endswith("/desc"):
                continue
            text = tf.extractfile(m).read().decode("utf-8", "replace")
            fields = dict(re.findall(r"%([A-Z0-9]+)%\n([^\n]*)", text))
            out.append({"name": fields.get("NAME"), "version": fields.get("VERSION"),
                        "builddate": int(fields["BUILDDATE"]) if fields.get("BUILDDATE", "").isdigit() else None})
    return out


def channel_record(channel, repo, pkgs, now=None):
    pkgs = [p for p in pkgs if p.get("builddate")]
    if not pkgs:
        return {"name": channel, "repo": repo, "latest": None, "built": None, "age_h": None, "packages": 0,
                "state": "unknown"}
    newest = max(pkgs, key=lambda p: p["builddate"])
    return {"name": channel, "repo": repo, "latest": f"{newest['name']} {newest['version']}",
            "built": L.iso(newest["builddate"]), "age_h": L.hours_since(newest["builddate"], now),
            "packages": len(pkgs), "state": "ok"}


def package_findings(recs, runs=None, stale_hours=24, source=None, now=None):
    """Doctor findings: an unpublished channel (skip), the publish workflow's last run failing
    (fail), and a database older than the newest successful publish run (stale: warn).
    runs: gh run list's JSON (newest first), or None without a GitHub repository to check."""
    out = []
    now = now or time.time()
    for r in recs:
        if r.get("state") == "unknown":
            out.append(L.finding(f"packages.{r['name']}", f"Packages: {r['name']}", "skip", r.get("detail") or "not published"))
    edge = next((r for r in recs if r["name"] in ("edge", "default") and r.get("built")), None) or \
        next((r for r in recs if r.get("built")), None)
    if runs:
        done = [x for x in runs if x.get("status") == "completed"]
        last = done[0] if done else None
        if last and last.get("conclusion") not in ("success", "skipped", "neutral", "cancelled"):
            out.append(L.finding("packages.publish", "Package publishing", "fail",
                                 f"the last publish run {last.get('conclusion')}: {last.get('displayTitle') or ''}"[:200],
                                 f"Read its log ({last.get('url')}); until it passes, machines on this channel get "
                                 "nothing new.", source))
        ok = next((x for x in done if x.get("conclusion") == "success"), None)
        if ok and edge:
            ran = L.ts(ok.get("updatedAt") or ok.get("createdAt"))
            built = L.ts(edge["built"])
            if ran and built and (ran - built) / 3600 > stale_hours:
                out.append(L.finding("packages.stale", "Package publishing", "warn",
                                     f"the newest build is {(ran - built) / 3600:.0f} h older than the last good run",
                                     "CI passed but the repository didn't change: check the publish step's upload "
                                     "and that the bucket is the one machines read.", source))
    if recs and not [f for f in out if f["status"] in ("warn", "fail")]:
        out.append(L.finding("packages.all", "Package repository", "ok", ", ".join(
            f"{r['name']} {r['age_h']:.0f} h old" for r in recs if r.get("age_h") is not None) or "published",
            source=source))
    return out


@register
class PacmanRepo(L.LabAdapter):
    type = "pacman-repo"
    provides = ("packages",)

    def _repo(self):
        return self.opt("repo", "bromigos")

    def _base(self):
        return self.endpoint or repo_base(pacman_server(self._repo(), self.opt("pacman_conf", "/etc/pacman.conf")))

    def configured(self):
        return bool(self._base())

    def _channels(self):
        ch = self.opt("channels")
        if isinstance(ch, dict) and ch:
            return ch
        server = pacman_server(self._repo(), self.opt("pacman_conf", "/etc/pacman.conf"))
        if self._repo() == "bromigos" or not server:
            return BROMIGOS_CHANNELS
        tail = server.split("/$repo", 1)[1] if "/$repo" in server else "/$arch"
        return {"default": "{repo}" + tail.replace("$arch", "{arch}")}

    def packages(self):
        base, repo, arch = self._base(), self._repo(), self.opt("arch", os.uname().machine)
        if not base:
            raise Unreachable(f"{self.name}: no endpoint, and pacman.conf has no [{repo}] Server")
        out = []
        for ch, path in self._channels().items():
            url = f"{base}/{path.format(repo=repo, arch=arch)}/{repo}.db"
            try:
                data = self.request(url, timeout=15, raw=True)
            except urllib.error.HTTPError as e:
                if e.code in (403, 404):
                    out.append({"name": ch, "repo": repo, "latest": None, "built": None, "age_h": None,
                                "packages": 0, "state": "unknown", "detail": "not published"})
                    continue
                raise
            out.append(channel_record(ch, repo, parse_db(data)))
        return out

    def _runs(self):
        repo, wf = self.opt("github_repo"), self.opt("workflow", "packages.yml")
        if not repo or not shutil.which("gh"):
            return None
        try:
            p = subprocess.run(["gh", "run", "list", "-R", repo, "-w", wf, "-b", self.opt("branch", "main"), "-L", "10",
                                "--json", "status,conclusion,createdAt,updatedAt,displayTitle,url,event"],
                               capture_output=True, text=True, timeout=25)
        except (OSError, subprocess.TimeoutExpired):
            return None
        return json.loads(p.stdout or "[]") if p.returncode == 0 else None

    def doctor(self):
        return package_findings(self.packages(), self._runs(), float(self.opt("stale_hours", 24)), self.name)
