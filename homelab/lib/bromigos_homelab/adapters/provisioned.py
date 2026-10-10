"""Live, read-only checks for a generated provision plan, over its explicit target."""
import json
from pathlib import Path

from .. import provision as P, agentprovision as A
from ..registry import Adapter, register


@register
class Provisioned(Adapter):
    type = "provisioned"
    provides = ("hosts", "workloads", "deployments", "backups", "secrets")
    local = True

    def __init__(self, source):
        try:
            picked = json.loads(Path(source.get("plan", "")).read_text())["selected"]
        except (OSError, ValueError, KeyError):
            picked = []
        self.provides = ("hosts", "workloads") + (("deployments",) if "argocd" in picked else ()) + \
                        (("backups",) if "restic" in picked else ()) + (("secrets",) if "vault" in picked else ()) + (("agents",) if any(a in picked for a in A.AGENTS) else ())
        super().__init__(source)

    def configured(self):
        return bool(self.opts.get("plan"))

    def state(self):
        return json.loads(Path(self.opts["plan"]).read_text())

    def hosts(self):
        state = self.state()
        facts = P.inventory(state["target"])
        return [{"name": "lab", "up": True, "cores": facts["cpu"]}]

    def workloads(self):
        state = self.state()
        out = []
        if state["target"]["kind"] == "ssh":
            text = P.run(P.ssh_args(state["target"]) + ["sudo docker ps -a --filter label=com.docker.compose.project=bromigos-lab --format '{{json .}}'"])
            for line in text.splitlines():
                row = json.loads(line)
                out.append({"name": row["Names"], "image": row["Image"], "kind": "container", "state": row["State"]})
        if "kubernetes" in state["selected"] or state["target"]["kind"] == "cluster":
            pods = json.loads(P.kubectl(state["target"], ["get", "pods", "-A", "-o", "json"]))["items"]
            for pod in pods:
                status = pod.get("status", {})
                containers = status.get("containerStatuses", [])
                phase = status.get("phase", "Unknown")
                broken = any(c.get("state", {}).get("waiting", {}).get("reason") in ("CrashLoopBackOff", "ImagePullBackOff", "ErrImagePull") for c in containers)
                out.append({"name": pod["metadata"]["name"], "namespace": pod["metadata"]["namespace"], "kind": "pod",
                            "state": "failed" if broken else {"Running": "running", "Pending": "pending", "Succeeded": "stopped", "Failed": "failed"}.get(phase, "unknown"),
                            "restarts": sum(c.get("restartCount", 0) for c in containers)})
        return out

    def agents(self):
        state = self.state()
        rows = []
        for agent in A.AGENTS:
            if agent in state["selected"]:
                try:
                    rows.append(A.metadata(state, agent))
                except (P.ProvisionError, ValueError, OSError):
                    rows.append({"name": agent, "status": "unreachable", "model": state["agents"]["model"], "gateways": "unknown", "activity": "unknown"})
        return rows

    def secrets(self):
        state = self.state()
        with P.forward(state["target"], "vault", "vault", 8200) as address:
            status = P.Vault(address).request("GET", "sys/seal-status")
        return [{"name": "Vault", "reachable": True, "initialized": status["initialized"], "sealed": status["sealed"], "version": status.get("version")}]

    def deployments(self):
        state = self.state()
        if "argocd" not in state["selected"]:
            return []
        apps = json.loads(P.kubectl(state["target"], ["-n", "argocd", "get", "applications", "-o", "json"]))["items"]
        return [{"name": a["metadata"]["name"], "namespace": a.get("spec", {}).get("destination", {}).get("namespace") or a["metadata"]["namespace"],
                 "sync": {"Synced": "synced", "OutOfSync": "out_of_sync"}.get(a.get("status", {}).get("sync", {}).get("status"), "unknown"),
                 "health": a.get("status", {}).get("health", {}).get("status", "unknown").lower()} for a in apps]

    def backups(self):
        state = self.state()
        if "restic" not in state["selected"]:
            return []
        if state["target"]["kind"] == "cluster":
            import datetime
            jobs = json.loads(P.kubectl(state["target"], ["-n", "lab-core", "get", "jobs", "-o", "json"]))["items"]
            completed = [j["status"]["completionTime"] for j in jobs if j.get("status", {}).get("succeeded")]
            stamp = max((datetime.datetime.fromisoformat(v.replace("Z", "+00:00")).timestamp() for v in completed), default=0)
        else:
            command = "sudo -n docker exec $(sudo -n docker ps -q --filter label=com.docker.compose.service=restic) stat -c %Y /status/last-success"
            stamp = float(P.run(P.ssh_args(state["target"]) + [command]).strip())
        return [{"name": "restic", "last_success": stamp, "ok": True, "max_age_hours": 30}]

    def doctor(self):
        from ..doctor import finding
        state = self.state()
        P.verify_services(state)
        A.verify(state)
        return [finding("provision.services", "Provisioned services", "ok", "Selected services answer; Vault is initialised and unsealed when selected")]
