"""Backups: what backs up the lab and when each target last succeeded. Capability: backups.

    [[source]]
    type = "backups"                    # backup CronJobs (kube-state-metrics, else the kubernetes
                                        # source), NAS share snapshots (a NAS exporter's nas_share_*),
                                        # Velero's schedules (its metrics)
    # match = "backup|velero|…"         # which CronJobs are backups (a regex on their names)
    # exclude = "drill|verify"          # and which of those aren't
    # offsite = ["*-offsite"]           # targets whose copies leave the lab (fnmatch)
    # local_classes = ["local-path"]    # storage classes on a node's own disk: their volumes need a job
    # ignore = ["scratch"]              # shares and namespaces the coverage check leaves alone

    [[source]]
    type = "pbs"                        # Proxmox Backup Server: each backup group's newest snapshot
    endpoint = "https://pbs.lab:8007"
    auth_ref = "@vault:kv/pbs#token"    # an API token, user@realm!name:secret (DatastoreAudit is enough)

A target's max_age_hours is 1.5 times its interval (a CronJob's schedule; a share's snapshots
as its history shows them) plus two hours. The console's backup check reads these records for
staleness; the doctor here says what nothing backs up, and whether any copy leaves the lab.
"""
import fnmatch
import re
import urllib.error

from ..registry import Unreachable, register
from . import labcommon as L

MATCH = (r"backup|velero|restic|borg|kopia|rclone|duplicati|dump\b|pg-?dump|mysqldump"
         r"|(?:^|-)(?:db|database|raft|etcd|vault|datastore)-?snapshot")


def _max_age(minutes):
    return round(minutes * 1.5 / 60 + 2, 1)


def job_record(ns, name, schedule, last_success, last_schedule, active=0, suspended=False, offsite=(), now=None):
    every = L.cron_minutes(schedule)
    ok = not (last_schedule and (not last_success or last_schedule > last_success + 60) and not active)
    return {"name": f"{ns}/{name}", "kind": "job", "last_success": L.iso(last_success),
            "age_h": L.hours_since(last_success, now), "schedule": schedule, "ok": ok and not suspended,
            "max_age_hours": _max_age(every), "offsite": any(fnmatch.fnmatch(name, p) for p in offsite) or None,
            "namespace": ns, "suspended": suspended}


def jobs_from_objects(items, match=MATCH, offsite=(), now=None, exclude=None):
    out = []
    for c in items:
        name, ns = c["metadata"]["name"], c["metadata"].get("namespace")
        if not re.search(match, name, re.I) or (exclude and re.search(exclude, name, re.I)):
            continue
        st, sp = c.get("status") or {}, c.get("spec") or {}
        out.append(job_record(ns, name, sp.get("schedule"), L.ts(st.get("lastSuccessfulTime")),
                              L.ts(st.get("lastScheduleTime")), len(st.get("active") or []), bool(sp.get("suspend")),
                              offsite, now))
    return out


def jobs_from_metrics(get, match=MATCH, offsite=(), now=None, exclude=None):
    def by(m):
        return {(r["labels"].get("namespace"), r["labels"].get("cronjob")): r for r in get(m)}
    info, ok, sched = by("kube_cronjob_info"), by("kube_cronjob_status_last_successful_time"), \
        by("kube_cronjob_status_last_schedule_time")
    act, sus = by("kube_cronjob_status_active"), by("kube_cronjob_spec_suspend")
    out = []
    for (ns, name), r in sorted(info.items()):
        if not name or not re.search(match, name, re.I) or (exclude and re.search(exclude, name, re.I)):
            continue
        out.append(job_record(ns, name, r["labels"].get("schedule"), (ok.get((ns, name)) or {}).get("value") or None,
                              (sched.get((ns, name)) or {}).get("value") or None,
                              (act.get((ns, name)) or {}).get("value") or 0,
                              bool((sus.get((ns, name)) or {}).get("value")), offsite, now))
    return out


def snapshot_records(last, scheduled, taken_8d, offsite=(), now=None):
    """Share snapshots: rows of nas_share_last_snapshot_timestamp_seconds, nas_share_snapshots_scheduled,
    and changes(…[8d]) (how many were taken in 8 days, for the interval)."""
    sch = {r["labels"].get("share"): r["value"] for r in scheduled}
    n8 = {r["labels"].get("share"): r["value"] for r in taken_8d}
    out = []
    for r in last:
        share = r["labels"].get("share")
        if not sch.get(share):
            continue
        every_min = 8 * 1440 / n8[share] if n8.get(share) else 7 * 1440
        out.append({"name": share, "kind": "snapshot", "last_success": L.iso(r["value"]),
                    "age_h": L.hours_since(r["value"], now), "schedule": f"every {every_min / 60:.0f} h",
                    "ok": True, "max_age_hours": _max_age(every_min),
                    "offsite": any(fnmatch.fnmatch(share, p) for p in offsite) or None})
    return out


def coverage_findings(recs, local_pvcs, unsnapped, offsite_known, source=None, ignore=()):
    """What nothing backs up: volumes on a node's own disk in namespaces with no backup job;
    shares with snapshots off; no copy leaving the lab. local_pvcs: [(ns, pvc)];
    unsnapped: [share]."""
    out = []
    if not recs:
        return [L.finding("backups.none", "Backups", "fail",
                          "nothing backs up this lab's data: no backup jobs, no snapshots, no backup server found",
                          "Pick one: snapshots on the NAS for its shares, a backup job (or Velero) for the cluster's "
                          "volumes, and one copy that leaves the house. Then add its source here.", source)]
    covered = {r.get("namespace") for r in recs if r["kind"] == "job"}
    bare = [f"{ns}/{p}" for ns, p in local_pvcs if ns not in covered and not any(fnmatch.fnmatch(ns, i) for i in ignore)]
    if bare:
        out.append(L.finding("backups.coverage.volumes", "Volumes with no backup", "warn",
                             f"{len(bare)} on a node's own disk: " + ", ".join(bare[:10]) + (" …" if len(bare) > 10 else ""),
                             "These live on one node's disk and no backup job runs in their namespace: losing the "
                             "node loses them. Add a backup job, or move what matters to backed-up storage "
                             "(list throwaway ones in `ignore`).", source))
    gaps = [s for s in unsnapped if not any(fnmatch.fnmatch(s, i) for i in ignore)]
    if gaps:
        out.append(L.finding("backups.coverage.shares", "Shares with no snapshots", "warn", ", ".join(gaps),
                             "Snapshots are off for these shares: a deletion or ransomware there can't be undone. "
                             "Turn them on, or list the ones you can lose in `ignore`.", source))
    if not offsite_known:
        out.append(L.finding("backups.offsite", "A copy outside the lab", "warn",
                             "every backup found stays in the lab (its NAS or its nodes)",
                             "One disaster (fire, theft, a failed pool) takes the copies with the originals. "
                             "Send one copy elsewhere (a cloud bucket, a friend's NAS), then name it in `offsite`.",
                             source))
    if not out:
        out.append(L.finding("backups.coverage", "Backup coverage", "ok",
                             f"{len(recs)} targets; every volume and share covered; a copy leaves the lab", source=source))
    return out


@register
class Backups(L.LabAdapter):
    type = "backups"
    provides = ("backups",)

    @classmethod
    def detect(cls, d):
        jobs = [r for r in d.rows("kube_cronjob_info") if re.search(MATCH, r["labels"].get("cronjob") or "", re.I)]
        if jobs or d.has_metric("nas_share_last_snapshot_timestamp_seconds") or \
                d.has_metric("velero_backup_last_successful_timestamp") or d.metrics or d.kube:
            return [{"type": "backups"}]       # with no backups at all it is what says so
        return []

    def _offsite(self):
        return tuple(self.opt("offsite", ()) or ())

    def _jobs(self):
        match, off, ex = self.opt("match", MATCH), self._offsite(), self.opt("exclude", r"restore|drill|verify")
        if L.mq_soft("count(kube_cronjob_info)"):
            return jobs_from_metrics(L.mq_soft, match, off, exclude=ex)
        if L.kube():
            return jobs_from_objects(L.kube_json(["get", "cronjobs.batch", "-A"]).get("items", []), match, off, exclude=ex)
        return None

    def backups(self):
        jobs = self._jobs()
        snaps = snapshot_records(L.mq_soft("nas_share_last_snapshot_timestamp_seconds"),
                                 L.mq_soft("nas_share_snapshots_scheduled"),
                                 L.mq_soft("changes(nas_share_last_snapshot_timestamp_seconds[8d])"), self._offsite())
        velero = [{"name": f"velero/{r['labels'].get('schedule') or 'manual'}", "kind": "velero",
                   "last_success": L.iso(r["value"]), "age_h": L.hours_since(r["value"]), "schedule": None, "ok": True,
                   "max_age_hours": float(self.opt("velero_max_age_hours", 26)),
                   "offsite": any(fnmatch.fnmatch(r["labels"].get("schedule") or "", p) for p in self._offsite()) or None}
                  for r in L.mq_soft("velero_backup_last_successful_timestamp") if r.get("value")]
        if jobs is None and not snaps and not velero and not L.have_metrics():
            raise Unreachable(f"{self.name}: backups are found through the metrics or kubernetes sources; neither is configured")
        return (jobs or []) + snaps + velero

    def _local_pvcs(self):
        classes = self.opt("local_classes") or [r["labels"].get("storageclass") for r in L.mq_soft(
            'kube_storageclass_info{provisioner=~".*(local-path|hostpath|local-volume|openebs.io/local|topolvm).*"}')]
        classes = [c for c in classes if c]
        if not classes:
            return []
        rows = L.mq_soft(f'kube_persistentvolumeclaim_info{{storageclass=~"{"|".join(classes)}"}}')
        return sorted({(r["labels"].get("namespace"), r["labels"].get("persistentvolumeclaim")) for r in rows})

    def doctor(self):
        recs = self.backups()
        unsnapped = [r["labels"].get("share") for r in L.mq_soft("nas_share_snapshots_scheduled == 0")]
        others = [r for a in self._peers() for r in a]
        allrecs = recs + others
        return coverage_findings(allrecs, self._local_pvcs(), unsnapped,
                                 any(r.get("offsite") for r in allrecs), self.name, tuple(self.opt("ignore", ()) or ()))

    def _peers(self):
        """Other backups providers' records (a PBS), so coverage counts them."""
        from ..registry import providers
        out = []
        for a in providers("backups"):
            if a is self:
                continue
            try:
                out.append(a.backups())
            except Exception:
                pass
        return out


@register
class PBS(L.LabAdapter):
    """Proxmox Backup Server's API with an API token (PBSAPIToken)."""
    type = "pbs"
    provides = ("backups",)
    default_ports = (8007,)
    default_scheme = "https"
    local = False

    def configured(self):
        return bool(self.endpoint)

    def auth_headers(self):
        from .. import config
        tok = config.resolve(self.opts.get("auth_ref") or "")
        return {"Authorization": f"PBSAPIToken={tok}"} if tok else {}

    def probe(self):
        try:
            d = self.request("/api2/json/version", timeout=3)
            return isinstance(d, dict) and "data" in d
        except urllib.error.HTTPError as e:
            return e.code == 401 and "PBS" in (e.headers.get("WWW-Authenticate") or "")

    def backups(self):
        out = []
        offsite = bool(self.opts.get("offsite"))
        for ds in (self.request("/api2/json/admin/datastore", timeout=8) or {}).get("data") or []:
            store = ds.get("store") or ds.get("name")
            for g in (self.request(f"/api2/json/admin/datastore/{store}/groups", timeout=10) or {}).get("data") or []:
                last = g.get("last-backup")
                out.append({"name": f"{store}/{g.get('backup-type')}/{g.get('backup-id')}", "kind": "pbs",
                            "last_success": L.iso(last), "age_h": L.hours_since(last), "schedule": None, "ok": True,
                            "max_age_hours": float(self.opt("max_age_hours", 26)), "offsite": offsite or None,
                            "count": g.get("backup-count")})
        return out

