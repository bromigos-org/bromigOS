"""Live, read-only checks for a generated provision plan, over its explicit target."""
import json
from pathlib import Path

from .. import provision as P, agentprovision as A, observability as O
from ..registry import Adapter, register


@register
class Provisioned(Adapter):
    type = "provisioned"
    provides = ("hosts", "workloads", "deployments", "backups", "secrets")
    local = True

    def __init__(self, source):
        try:
            state = json.loads(Path(source.get("plan", "")).read_text())
            picked = state['selected']
        except (OSError, ValueError, KeyError):
            picked = []; state = {}
        self.provides = ("hosts", "workloads") + (("deployments",) if "argocd" in picked else ()) + \
                        (("backups",) if "restic" in picked else ()) + (("secrets",) if "vault" in picked else ()) + (("agents",) if any(a in picked for a in A.AGENTS) else ())
        if state.get('observability'): self.provides += ('metrics', 'alerts')
        if state.get('infrastructure'): self.provides += ('capacity', 'storage', 'vms')
        super().__init__(source)

    def configured(self):
        return bool(self.opts.get("plan"))

    def state(self):
        return json.loads(Path(self.opts["plan"]).read_text())

    def hosts(self):
        state = self.state()
        if state.get('infrastructure'):
            nodes = json.loads(P.kubectl(state['target'], ['get', 'nodes', '-o', 'json']))['items']
            return [{'name': n['metadata']['name'], 'up': any(c['type'] == 'Ready' and c['status'] == 'True' for c in n['status']['conditions']), 'cores': int(n['status']['capacity']['cpu'])} for n in nodes]
        facts = P.inventory(state["target"])
        return [{"name": "lab", "up": True, "cores": facts["cpu"]}]

    def metrics_query(self, q, timeout=8):
        import urllib.parse
        d = O.get(self.state(), 'prometheus', '/api/v1/query?' + urllib.parse.urlencode({'query': q}))
        return [{'labels': r.get('metric', {}), 'value': float(r['value'][1]), 't': float(r['value'][0])} for r in d['data']['result']]

    def metrics_range(self, q, minutes=60, step=60, timeout=10):
        import time, urllib.parse
        now = time.time()
        d = O.get(self.state(), 'prometheus', '/api/v1/query_range?' + urllib.parse.urlencode({'query': q, 'start': now-minutes*60, 'end': now, 'step': step}))
        return [{'labels': r.get('metric', {}), 'points': [[float(t), float(v)] for t, v in r.get('values', [])]} for r in d['data']['result']]

    def alerts(self):
        out = []
        for a in O.get(self.state(), 'alertmanager', '/api/v2/alerts?active=true&silenced=false&inhibited=false'):
            labels = a.get('labels', {})
            if labels.get('alertname') == 'Watchdog': continue
            out.append({'name': labels.get('alertname'), 'severity': labels.get('severity'), 'state': 'firing', 'summary': a.get('annotations', {}).get('summary'), 'since': a.get('startsAt'), 'labels': labels})
        return out

    def capacity(self):
        from .. import infrastructure as I
        state = self.state()
        if state.get('observability', {}).get('mode') != 'cluster': return []
        pods = json.loads(P.kubectl(state['target'], ['get', 'pods', '-A', '-o', 'json']))['items']
        messages = [c.get('message', '') for p in pods for c in p.get('status', {}).get('conditions', []) if c.get('reason') == 'Unschedulable']
        return I.proposals(lambda q: self.metrics_range(q, minutes=16, step=60), messages, __import__('time').time())

    def storage(self):
        # Read-only cached plan inventory. Live refresh is an explicit storage command,
        # so console consumers never decrypt the provider's mutation credential.
        rows = []
        for provider, observed in self.state().get('storage_inventory', {}).items():
            for p in observed.get('pools', []):
                total, free = p.get('total'), p.get('avail')
                rows.append({'name': provider + '/' + p['storage'], 'kind': p.get('type'), 'total': total, 'free': free, 'used': total-free if total is not None and free is not None else None, 'health': p.get('health'), 'note': 'Inventory from planning; refresh before apply'})
            for raid in observed.get('raid', []):
                rows.append({'name': provider + '/' + raid['name'], 'kind': raid['kind'], 'health': raid['health'], 'redundancy': raid['redundancy'], 'note': 'RAID inventory from planning; refresh before apply'})
        return rows

    def vms(self):
        live = {n['name']: 'Ready' if n['up'] else 'not Ready' for n in self.hosts()}
        return [{'name': n['name'], 'role': n['role'], 'provider': n.get('on', 'existing'), 'cpu': n.get('vm', {}).get('cpu'), 'ram_mib': n.get('vm', {}).get('ram_mib'), 'disk_gib': n.get('vm', {}).get('disk_gib'), 'storage': n.get('vm', {}).get('storage'), 'state': live.get(n['name'], 'not joined')} for n in self.state().get('infrastructure', {}).get('nodes', [])]

    def workloads(self):
        state = self.state()
        out = []
        host_monitoring = state.get('observability', {}).get('mode') == 'host'
        if state["target"]["kind"] == "ssh" and (host_monitoring or any(s in state['selected'] for s in P.IMAGES or ()) or any(s in state['selected'] for s in A.AGENTS)):
            projects = ['bromigos-lab'] + (['bromigos-monitoring'] if host_monitoring else [])
            filters = ' '.join('--filter label=com.docker.compose.project=' + project for project in projects)
            text = P.run(P.ssh_args(state["target"]) + ["sudo -n docker ps -a " + filters + " --format '{{json .}}'"])
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
            command = "sudo -n docker exec $(sudo -n docker ps -q --filter label=com.docker.compose.service=restic --filter label=com.docker.compose.project=bromigos-lab) stat -c %Y /status/last-success"
            stamp = float(P.run(P.ssh_args(state["target"]) + [command]).strip())
        return [{"name": "restic", "last_success": stamp, "ok": True, "max_age_hours": 30}]

    def doctor(self):
        from ..doctor import finding
        state = self.state()
        P.verify_services(state)
        A.verify(state)
        O.verify(state)
        return [finding("provision.services", "Provisioned services", "ok", "Selected services answer; Vault is initialised and unsealed when selected")]
