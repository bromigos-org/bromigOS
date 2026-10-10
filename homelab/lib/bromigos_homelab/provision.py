"""Generate and apply a user's lab repository. No operator configuration belongs here."""
import argparse
import contextlib
import getpass
import json
import ipaddress
import os
from pathlib import Path
import re
import secrets
import shlex
import shutil
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request

from . import services

SUPPORTED = ("caddy", "netdata", "restic", "homepage", "kubernetes", "helm", "argocd", "vault")
IMAGES = {"caddy": "caddy:2.11.7", "netdata": "netdata/netdata:v2.12.1",
          "homepage": "ghcr.io/gethomepage/homepage:v2.5.0", "restic": "restic/restic:0.19.1"}
K3S = "v1.37.1+k3s1"
HELM = "v4.3.0"
HELM_SHA256 = {"amd64": "86584a54def73570558f66f5111cc53dfed56689637ae32c1201205d494f54fb",
               "arm64": "31c5794dd55c66a51e6b7d2e2ac7a114ae8b1de41ff1d9ba51748ac973b06a08"}
CHARTS = {"vault": ("https://helm.releases.hashicorp.com", "vault", "0.34.1"),
          "argocd": ("https://argoproj.github.io/argo-helm", "argo-cd", "10.10.2")}


class ProvisionError(Exception):
    pass


def run(argv, data=None, cwd=None, env=None):
    """Never include subprocess output in exceptions: it may contain credentials."""
    result = subprocess.run(argv, input=data, text=True, capture_output=True, cwd=cwd, env=env, **({"stdin": subprocess.DEVNULL} if data is None else {}))
    if result.returncode:
        stage = ""
        if Path(argv[0]).name == "ansible-playbook":
            names = re.findall(r"TASK \[([a-zA-Z0-9 :_-]+)\]", result.stdout)
            stage = " at " + names[-1] if names else ""
        raise ProvisionError(f"{Path(argv[0]).name} failed (exit {result.returncode}){stage}; check reach and prerequisites")
    return result.stdout


def dump(value):
    return json.dumps(value, indent=2, sort_keys=True) + "\n"


def write(path, content, mode=0o600):
    path = Path(path)
    if path.is_symlink():
        raise ProvisionError("Refusing to replace a symbolic link")
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, mode)
    with os.fdopen(fd, "w") as stream:
        stream.write(content)
    path.chmod(mode)


def ssh_args(target):
    args = ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=10", "-p", str(target.get("port", 22))]
    if target.get("known_hosts"):
        args += ["-o", "UserKnownHostsFile=" + target["known_hosts"]]
    if target.get("identity"):
        args += ["-i", target["identity"]]
    return args + [target["ssh"]]


def validate_target(target):
    if target["kind"] == "ssh":
        if not re.fullmatch(r"[a-zA-Z0-9_.-]+@[a-zA-Z0-9_.-]+", target.get("ssh", "")):
            raise ProvisionError("Use user@host for the SSH target")
        if not 1 <= int(target.get("port", 22)) <= 65535:
            raise ProvisionError("SSH port must be between 1 and 65535")
    elif target["kind"] == "cluster":
        if not target.get("kubeconfig") or not target.get("context"):
            raise ProvisionError("An existing cluster needs both --kubeconfig and --context")
    else:
        raise ProvisionError("Choose an SSH box or an existing cluster")


def kubectl(target, args, data=None):
    if target["kind"] == "ssh":
        command = shlex.join(["sudo", "-n", "k3s", "kubectl"] + args)
        return run(ssh_args(target) + [command], data)
    return run(["kubectl", "--kubeconfig", target["kubeconfig"], "--context", target["context"]] + args, data)


def inventory(target):
    validate_target(target)
    if target["kind"] == "cluster":
        nodes = json.loads(kubectl(target, ["get", "nodes", "-o", "json"]))["items"]
        if not nodes:
            raise ProvisionError("The cluster has no nodes")
        def memory(value):
            for suffix, factor in (("Ki", 2**10), ("Mi", 2**20), ("Gi", 2**30)):
                if value.endswith(suffix):
                    return float(value[:-len(suffix)]) * factor / 2**30
            return float(value) / 2**30
        return {"cpu": sum(float(n["status"]["allocatable"]["cpu"].removesuffix("m")) /
                           (1000 if n["status"]["allocatable"]["cpu"].endswith("m") else 1) for n in nodes),
                "ram_gib": sum(memory(n["status"]["allocatable"]["memory"]) for n in nodes),
                "disk_gib": None, "distribution": "cluster", "gpu": "none", "vram_gib": 0}
    # Only reads. Sudo is tested here but never used on the desktop.
    probe = """import json, os, shutil, platform
from pathlib import Path
release = dict(line.split('=', 1) for line in Path('/etc/os-release').read_text().splitlines() if '=' in line)
mem = int(next(line.split()[1] for line in Path('/proc/meminfo').read_text().splitlines() if line.startswith('MemTotal:'))) / 1024**2
print(json.dumps(dict(cpu=os.cpu_count(), ram_gib=mem, disk_gib=shutil.disk_usage('/').free / 1024**3, distribution=release['ID'].strip(chr(34)), architecture=platform.machine(), gpu='none', vram_gib=0)))
"""
    try:
        run(ssh_args(target) + ["sudo -n true"])
        facts = json.loads(run(ssh_args(target) + ["python3 -"], probe))
    except ProvisionError:
        raise ProvisionError("SSH needs a trusted host key, a key login and passwordless sudo on the target. "
                             "First run ssh-copy-id (with your port and key), then ssh user@host to check access") from None
    if facts["distribution"] not in ("debian", "ubuntu", "fedora", "arch"):
        raise ProvisionError("Supported boxes run Debian, Ubuntu, Fedora or Arch Linux")
    return facts


def selection(cat, picked, facts=None):
    resolved = services.resolve(cat, picked)
    if resolved["unknown"] or resolved["conflicts"] or resolved.get("unmet"):
        raise ProvisionError("Selection has unknown services, conflicts or unmet dependencies")
    unsupported = set(resolved["services"]) - set(SUPPORTED)
    if unsupported:
        raise ProvisionError("No installer in this slice for: " + ", ".join(sorted(unsupported)))
    budget = [s for s in resolved["services"] if not (facts and facts.get("distribution") == "cluster" and s == "kubernetes")]
    resolved["warnings"] = services.fit(cat, budget, facts) if facts else []
    return resolved


def task(name, module, options, **extra):
    return {"name": name, module: options, **extra}


def plan_files(target, picked, facts, repo_url="", backup_path="", age_recipient="", domain="", listen_address="127.0.0.1", cat=None):
    """Pure, deterministic plan. Contains no generated secrets."""
    cat = cat or services.load()
    validate_target(target)
    resolved = selection(cat, picked, facts)
    picked = resolved["services"]
    if "argocd" in picked and not repo_url:
        raise ProvisionError("Argo CD needs --git-url: the address where you will publish this lab repository")
    if repo_url and (not re.fullmatch(r"https?://[^\s]+", repo_url) or "@" in repo_url.split("://", 1)[1]):
        raise ProvisionError("Use an HTTP(S) Git URL without credentials")
    if "restic" in picked and not backup_path:
        raise ProvisionError("Restic needs --backup-path, an existing backup destination on the target")
    if "restic" in picked and target["kind"] == "ssh" and not backup_path.startswith("/"):
        raise ProvisionError("The backup destination must be an absolute path on the target")
    if "vault" not in picked and any(s in picked for s in ("restic", "argocd")) and not age_recipient.startswith("age1"):
        raise ProvisionError("Without Vault, supply --age-recipient to encrypt generated secrets")
    if "restic" in picked and target["kind"] == "cluster" and not re.fullmatch(r"[a-z0-9][a-z0-9.-]*", backup_path):
        raise ProvisionError("For a cluster, --backup-path names an existing backup PVC in lab-core")
    try:
        address = ipaddress.ip_address(listen_address)
        if address.version != 4 or not address.is_private or address.is_unspecified:
            raise ValueError
    except ValueError:
        raise ProvisionError("Caddy's listen address must be a local or private IPv4 address") from None
    if domain and not re.fullmatch(r"[a-zA-Z0-9.-]+", domain):
        raise ProvisionError("The HTTPS name must be a DNS name")
    state = dict(format=1, target=target, selected=picked, inventory=facts, git_url=repo_url,
                 backup_path=backup_path, age_recipient=age_recipient, domain=domain, listen_address=listen_address)
    files = {"plan.json": dump(state), ".gitignore": ".runtime/\n*.retry\n*.log\n",
             "README.md": "# Your lab\n\nReview plan.json and the Ansible roles before applying.\n"
             "Publish this repository at the Git URL in the plan before applying Argo CD.\n"
             "Run bromigos lab provision apply --repo <this-folder> to converge again.\n"
             "Removing a service from the selection leaves its data and running resources in place.\n"}
    is_box = target["kind"] == "ssh"
    arch = {"x86_64": "amd64", "aarch64": "arm64"}.get(facts.get("architecture", "x86_64"))
    if is_box and not arch:
        raise ProvisionError("This slice supports x86-64 and ARM64 Linux boxes")
    hostvars = {"ansible_host": target.get("ssh", "").split("@")[-1],
                "ansible_user": target.get("ssh", "").split("@")[0], "ansible_port": target.get("port", 22)}
    if target.get("known_hosts"):
        hostvars["ansible_ssh_common_args"] = shlex.join(["-o", "UserKnownHostsFile=" + target["known_hosts"]])
    if target.get("identity"):
        hostvars["ansible_ssh_private_key_file"] = target["identity"]
    inventory_doc = {"all": {"hosts": {"lab": hostvars if is_box else {"ansible_connection": "local"}}}}
    files["ansible/inventory/hosts.json"] = dump(inventory_doc)
    roles = []
    if is_box and any(s in picked for s in IMAGES):
        roles.append("core")
        distro = facts["distribution"]
        packages = {"debian": ["docker.io", "docker-compose"], "ubuntu": ["docker.io", "docker-compose"],
                    "fedora": ["moby-engine", "docker-compose"], "arch": ["docker", "docker-compose"]}[distro]
        core = [task("Install the container engine", "ansible.builtin.package", {"name": packages, "state": "present", "update_cache": True}),
                task("Start the container engine", "ansible.builtin.systemd", {"name": "docker", "enabled": True, "state": "started"}),
                task("Make the lab folder", "ansible.builtin.file", {"path": "/opt/bromigos-lab", "state": "directory", "mode": "0700"}),
                task("Copy the reviewed container definitions", "ansible.builtin.copy", {"src": "{{ playbook_dir }}/../../compose/", "dest": "/opt/bromigos-lab/", "mode": "0644", "directory_mode": "0755"}),
                task("Start selected services without deleting data", "ansible.builtin.shell",
                     {"cmd": "if docker compose version >/dev/null 2>&1; then docker compose up -d; else docker-compose up -d; fi", "chdir": "/opt/bromigos-lab"},
                     changed_when=False)]
        files["ansible/roles/core/tasks/main.json"] = dump(core)
        containers = {}
        for svc in picked:
            if svc not in IMAGES:
                continue
            cfg = {"image": IMAGES[svc], "restart": "unless-stopped"}
            if svc == "caddy":
                cfg.update(ports=[f"{listen_address}:80:80", f"{listen_address}:443:443"], volumes=["./Caddyfile:/etc/caddy/Caddyfile:ro", "caddy-data:/data"])
            elif svc == "netdata":
                cfg.update(volumes=["netdata-data:/var/lib/netdata", "/proc:/host/proc:ro", "/sys:/host/sys:ro"],
                           environment={"DO_NOT_TRACK": "1"})
            elif svc == "homepage":
                cfg.update(volumes=["./homepage:/app/config"], environment={"HOMEPAGE_ALLOWED_HOSTS": "*"})
            elif svc == "restic":
                cfg.update(entrypoint=["/bin/sh", "-c"], command=["while true; do restic snapshots >/dev/null 2>&1 || restic init; restic backup /data && touch /status/last-success; sleep 86400; done"],
                           environment={"RESTIC_REPOSITORY": "/repository", "RESTIC_PASSWORD_FILE": "/run/secrets/restic"},
                           volumes=[f"{backup_path}:/repository", "/opt/bromigos-lab:/data/config:ro", "caddy-data:/data/caddy:ro", "netdata-data:/data/netdata:ro",
                                    "./restic-password:/run/secrets/restic:ro", "backup-status:/status"])
            containers[svc] = cfg
        files["compose/compose.yaml"] = dump({"services": containers, "volumes": {n: {} for n in ("caddy-data", "netdata-data", "backup-status")}})
        routes = [":80 {"]
        if "netdata" in picked:
            routes.append("  handle_path /netdata/* {\n    reverse_proxy netdata:19999\n  }")
        if "homepage" in picked:
            routes.append("  handle {\n    reverse_proxy homepage:3000\n  }")
        else:
            routes.append('  respond "Your lab is running"')
        routes.append("}")
        caddyfile = "\n".join(routes) + "\n"
        if domain:
            caddyfile += caddyfile.replace(":80 {", domain + " {\n  tls internal", 1)
        files["compose/Caddyfile"] = caddyfile
        for name, content in homepage_files(picked).items():
            files["compose/homepage/" + name] = content
    if is_box and "kubernetes" in picked:
        roles.append("k3s")
        files["ansible/roles/k3s/tasks/main.json"] = dump([
            task("Install required networking tools", "ansible.builtin.package", {"name": ["curl", "iptables"], "state": "present"}),
            task("Download the k3s installer", "ansible.builtin.get_url", {"url": "https://get.k3s.io", "dest": "/opt/bromigos-k3s-install.sh", "mode": "0700"}),
            task("Install the pinned single-node cluster", "ansible.builtin.command", {"cmd": "/opt/bromigos-k3s-install.sh server --disable traefik --disable servicelb --secrets-encryption", "creates": "/etc/rancher/k3s/k3s.yaml"},
                 environment={"INSTALL_K3S_VERSION": K3S}),
            task("Keep k3s running", "ansible.builtin.systemd", {"name": "k3s", "state": "started", "enabled": True})])
    cluster_picked = [s for s in picked if s in CHARTS]
    if cluster_picked or "helm" in picked:
        roles.append("helm")
        helm_tasks = []
        if is_box:
            helm_tasks += [task("Download pinned Helm", "ansible.builtin.get_url", {"url": f"https://get.helm.sh/helm-{HELM}-linux-{arch}.tar.gz", "dest": "/opt/bromigos-helm.tar.gz", "mode": "0644", "checksum": "sha256:" + HELM_SHA256[arch]}),
                           task("Unpack Helm", "ansible.builtin.unarchive", {"src": "/opt/bromigos-helm.tar.gz", "dest": "/opt", "remote_src": True, "creates": f"/opt/linux-{arch}/helm"}),
                           task("Install Helm", "ansible.builtin.copy", {"src": f"/opt/linux-{arch}/helm", "dest": "/usr/local/bin/helm", "remote_src": True, "mode": "0755"})]
        roles_env = {"KUBECONFIG": "/etc/rancher/k3s/k3s.yaml" if is_box else target["kubeconfig"]}
        if not is_box:
            roles_env["HELM_KUBECONTEXT"] = target["context"]
        helm_tasks.append(task("Make the values folder", "ansible.builtin.file", {"path": "/opt/bromigos-lab/helm" if is_box else "{{ playbook_dir }}/../../.runtime/helm", "state": "directory", "mode": "0700"}))
        for svc in cluster_picked:
            chart_repo, chart_name, version = CHARTS[svc]
            values_path = f"/opt/bromigos-lab/helm/{svc}.yaml" if is_box else "{{ playbook_dir }}/../../helm/" + svc + "/values.yaml"
            if is_box:
                helm_tasks.append(task(f"Copy {svc} values", "ansible.builtin.copy", {"src": "{{ playbook_dir }}/../../helm/" + svc + "/values.yaml", "dest": values_path, "mode": "0600"}))
            helm_tasks.extend([
                task(f"Read {svc} release ownership", "ansible.builtin.command", {"argv": ["helm", "status", svc, "--namespace", svc, "--output", "json"]},
                     environment=roles_env, register="existing_release", changed_when=False, failed_when=False),
                task(f"Refuse to take over an existing {svc} release", "ansible.builtin.assert", {
                    "that": ["existing_release.rc != 0 or (existing_release.stdout | from_json).info.description == 'bromigos-lab-provision'"],
                    "fail_msg": "This Helm release belongs to another installer; use a fresh namespace or cluster"})])
            argv = ["helm", "upgrade", "--install", svc, chart_name, "--description", "bromigos-lab-provision", "--repo", chart_repo, "--version", version,
                    "--namespace", svc, "--create-namespace", "--values", values_path, "--timeout", "10m"]
            if svc != "vault":
                argv.append("--wait")
            helm_tasks.append(task(f"Converge {svc}", "ansible.builtin.command", {"argv": argv}, environment=roles_env, changed_when=False))
            values = {"injector": {"enabled": False}, "server": {"standalone": {"enabled": True, "config": 'ui = true\ndisable_mlock = true\nlistener "tcp" {\n  tls_disable = 1\n  address = "[::]:8200"\n}\nstorage "raft" {\n  path = "/vault/data"\n}\n'}, "dataStorage": {"size": "2Gi"}}, "ui": {"enabled": True}} if svc == "vault" else {"configs": {"params": {"server.insecure": True}}, "server": {"service": {"type": "ClusterIP"}}}
            files[f"helm/{svc}/values.yaml"] = dump(values)
        files["ansible/roles/helm/tasks/main.json"] = dump(helm_tasks)
    if not is_box and any(s in picked for s in IMAGES):
        roles.append("core-cluster")
        docs = cluster_core(picked, backup_path, domain)
        files["helm/core/Chart.yaml"] = "apiVersion: v2\nname: lab-core\nversion: 0.1.0\ntype: application\n"
        files["helm/core/templates/services.yaml"] = "---\n".join(dump(d) for d in docs)
        files["helm/core/values.yaml"] = dump({svc: {"image": IMAGES[svc]} for svc in picked if svc in IMAGES})
        for svc in picked:
            if svc in IMAGES:
                files[f"helm/{svc}/values.yaml"] = dump({svc: {"image": IMAGES[svc]}})
        files["ansible/roles/core-cluster/tasks/main.json"] = dump([
            task("Read cluster Core release ownership", "ansible.builtin.command", {"argv": ["helm", "status", "lab-core", "--namespace", "lab-core", "--output", "json", "--kubeconfig", target["kubeconfig"], "--kube-context", target["context"]]}, register="existing_release", changed_when=False, failed_when=False),
            task("Refuse to take over an existing Core release", "ansible.builtin.assert", {
                "that": ["existing_release.rc != 0 or (existing_release.stdout | from_json).info.description == 'bromigos-lab-provision'"],
                "fail_msg": "This Helm release belongs to another installer; it will not be replaced"}),
            task("Converge cluster Core", "ansible.builtin.command", {"argv":
            ["helm", "upgrade", "--install", "lab-core", "{{ playbook_dir }}/../../helm/core", "--description", "bromigos-lab-provision", "--namespace", "lab-core", "--create-namespace",
             "--kubeconfig", target["kubeconfig"], "--kube-context", target["context"], "--wait", "--timeout", "10m"] +
            [part for svc in picked if svc in IMAGES for part in ["--values", "{{ playbook_dir }}/../../helm/" + svc + "/values.yaml"]]}, changed_when=False)])
    files["ansible/playbooks/provision.json"] = dump([{ "name": "Converge your lab", "hosts": "all", "become": is_box, "gather_facts": False,
        "roles": roles}])
    files["ansible/requirements.json"] = dump({"collections": [{"name": "community.general", "version": "13.2.0"}]})
    files["ansible/ansible.cfg"] = "[defaults]\nroles_path = roles\nhost_key_checking = True\nretry_files_enabled = False\n"
    if "argocd" in picked:
        def app(name, source, namespace):
            return {"apiVersion": "argoproj.io/v1alpha1", "kind": "Application", "metadata": {"name": name, "namespace": "argocd"},
                    "spec": {"project": "default", "source": source, "destination": {"server": "https://kubernetes.default.svc", "namespace": namespace},
                             "syncPolicy": {"automated": {"selfHeal": True, "prune": False}, "syncOptions": ["CreateNamespace=true"]}}}
        files["gitops/root.yaml"] = dump(app("lab-apps", {"repoURL": repo_url, "targetRevision": "HEAD", "path": "gitops/argocd-apps"}, "argocd"))
        for svc in cluster_picked:
            if svc == "argocd":
                continue
            url, name, version = CHARTS[svc]
            doc = app(svc, {}, svc)
            del doc["spec"]["source"]
            doc["spec"]["sources"] = [{"repoURL": url, "chart": name, "targetRevision": version,
                                       "helm": {"releaseName": svc, "valueFiles": [f"$values/helm/{svc}/values.yaml"]}},
                                      {"repoURL": repo_url, "targetRevision": "HEAD", "ref": "values"}]
            files[f"gitops/argocd-apps/{svc}.yaml"] = dump(doc)
        if not is_box and any(svc in picked for svc in IMAGES):
            files["gitops/argocd-apps/core.yaml"] = dump(app("lab-core", {"repoURL": repo_url, "targetRevision": "HEAD", "path": "helm/core",
                "helm": {"releaseName": "lab-core", "valueFiles": ["../" + svc + "/values.yaml" for svc in picked if svc in IMAGES]}}, "lab-core"))
        # Empty roots must still contain a valid resource.
        files["gitops/argocd-apps/namespace.yaml"] = dump({"apiVersion": "v1", "kind": "Namespace", "metadata": {"name": "lab"}})
    return files, resolved


def generate(repo, files):
    repo = Path(repo)
    if repo.is_symlink():
        raise ProvisionError("Repository must not be a symbolic link")
    repo = repo.resolve()
    repo.mkdir(parents=True, exist_ok=True)
    # Preserve manual edits: rerendered plans require a clean working tree.
    if (repo / ".git").exists() and run(["git", "status", "--porcelain"], cwd=repo).strip():
        raise ProvisionError("Commit or save changes in your lab repository before changing its plan")
    for name, text in files.items():
        dest = repo / name
        if not dest.resolve().is_relative_to(repo):
            raise ProvisionError("Plan path escapes the repository")
        write(dest, text)
    if not (repo / ".git").exists():
        run(["git", "init", "--quiet"], cwd=repo)
    return repo


def summary(cat, resolved, facts, repo):
    print(f"Plan: {repo}")
    for svc in resolved["services"]:
        row = cat["service"][svc]
        needs = row["needs"]
        if svc == "kubernetes" and facts.get("distribution") == "cluster":
            print("  Kubernetes: provided by the existing target; no server is installed")
            continue
        print(f"  {row['title']}: ports {row['ports']}; RAM {needs.get('ram_gib', 0)} GiB; disk {needs.get('disk_gib', 0)} GiB")
    for _, reason in resolved["added"]:
        print(reason)
    for warning in resolved["warnings"]:
        print("Capacity: " + warning)
    print("Model downloads: none. Removing a selection does not delete resources or data.")


def encrypt(repo, recipient, values):
    """Only ciphertext touches disk. Plaintext enters sops through stdin."""
    encrypted = run(["sops", "--encrypt", "--age", recipient, "--input-type", "json", "--output-type", "json", "/dev/stdin"], dump(values))
    write(Path(repo) / "secrets.enc.json", encrypted)


def decrypt(repo):
    return json.loads(run(["sops", "--decrypt", str(Path(repo) / "secrets.enc.json")]))


class Vault:
    def __init__(self, address):
        self.address = address
        self.token = None

    def request(self, method, path, body=None):
        headers = {"Content-Type": "application/json"}
        if self.token:
            headers["X-Vault-Token"] = self.token
        request = urllib.request.Request(self.address + "/v1/" + path, data=json.dumps(body).encode() if body is not None else None,
                                         headers=headers, method=method)
        try:
            with urllib.request.urlopen(request, timeout=15) as response:
                data = response.read()
                return json.loads(data) if data else {}
        except urllib.error.HTTPError as error:
            status = error.code
            error.close()
            raise ProvisionError(f"Vault request failed (HTTP {status}); response suppressed to protect secrets") from None
        except (urllib.error.URLError, OSError):
            raise ProvisionError("Vault connection failed; response suppressed to protect secrets") from None

    def initialise(self, reveal):
        if self.request("GET", "sys/init")["initialized"]:
            return False
        doc = self.request("PUT", "sys/init", {"secret_shares": 5, "secret_threshold": 3})
        keys = doc["keys_base64"]
        self.token = doc["root_token"]
        # The callback is a terminal-only sink, never stdout, logging or an Ansible result.
        reveal(keys)
        for key in keys[:3]:
            self.request("PUT", "sys/unseal", {"key": key})
        self.wait_active()
        mount = self.request("GET", "sys/mounts").get("data", {}).get("secret/")
        if mount is None:
            self.request("POST", "sys/mounts/secret", {"type": "kv", "options": {"version": "2"}})
        elif mount.get("type") != "kv" or mount.get("options", {}).get("version") != "2":
            raise ProvisionError("The existing secret mount is not KV version 2; it will not be replaced")
        return keys

    def wait_active(self):
        for _ in range(100):
            try:
                status = self.request("GET", "sys/health")
                if status.get("initialized") and not status.get("sealed") and not status.get("standby"):
                    return
            except ProvisionError:
                pass
            time.sleep(.2)
        raise ProvisionError("Vault did not become active after unseal")

    def store(self, name, values):
        self.request("POST", "secret/data/lab/" + name, {"data": values})


def reveal_once(keys):
    with open("/dev/tty", "w") as terminal:
        terminal.write("Vault recovery material — shown once. Store all five shares in your password manager.\n"
                       "Any three shares can unseal Vault. Losing them can permanently lose access.\n")
        for i, key in enumerate(keys, 1):
            terminal.write(f"Share {i}: {key}\n")
        terminal.flush()
    if input("Type stored after saving the recovery material: ").strip() != "stored":
        raise ProvisionError("Recovery acknowledgement missing. Save the terminal material before continuing")


@contextlib.contextmanager
def forward(target, namespace, service, remote_port):
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    command = ["kubectl", "--kubeconfig", target.get("kubeconfig", ""), "--context", target.get("context", ""),
               "-n", namespace, "port-forward", "service/" + service, f"{port}:{remote_port}"]
    if target["kind"] == "ssh":
        command = ssh_args(target)[:-1] + ["-L", f"{port}:127.0.0.1:{port}", target["ssh"],
                    shlex.join(["sudo", "-n", "k3s", "kubectl", "-n", namespace, "port-forward", "service/" + service, f"{port}:{remote_port}"])]
    proc = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        for _ in range(100):
            if proc.poll() is not None:
                raise ProvisionError("Service port-forward failed")
            try:
                # SSH can accept a local socket before the remote kubectl is ready.
                # Confirm a read-only HTTP response before allowing Vault initialisation.
                request = urllib.request.Request(f"http://127.0.0.1:{port}/v1/sys/seal-status")
                with urllib.request.urlopen(request, timeout=1) as response:
                    status = json.loads(response.read())
                if "sealed" in status:
                    break
            except (OSError, urllib.error.URLError, ValueError):
                time.sleep(.2)
        else:
            raise ProvisionError("Service port-forward did not start")
        yield f"http://127.0.0.1:{port}"
    finally:
        proc.terminate()
        try:
            proc.wait(10)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()


def auto_unseal(target, keys):
    doc = {"apiVersion": "v1", "kind": "Secret", "metadata": {"name": "vault-unseal-keys", "namespace": "vault"},
           "type": "Opaque", "stringData": {f"key{i+1}": key for i, key in enumerate(keys[:3])}}
    kubectl(target, ["apply", "-f", "-"], dump(doc))
    cron = {"apiVersion": "batch/v1", "kind": "CronJob", "metadata": {"name": "vault-unsealer", "namespace": "vault"},
            "spec": {"schedule": "* * * * *", "concurrencyPolicy": "Forbid", "jobTemplate": {"spec": {"template": {"spec": {
                "restartPolicy": "OnFailure", "automountServiceAccountToken": False,
                "containers": [{"name": "unseal", "image": "hashicorp/vault:2.0.4", "env": [{"name": "VAULT_ADDR", "value": "http://vault:8200"}],
                                "command": ["/bin/sh", "-ec", 'for f in /keys/*; do vault operator unseal "$(cat "$f")" >/dev/null 2>&1; done'],
                                "volumeMounts": [{"name": "keys", "mountPath": "/keys", "readOnly": True}]}],
                "volumes": [{"name": "keys", "secret": {"secretName": "vault-unseal-keys"}}]}}}}}}
    kubectl(target, ["apply", "-f", "-"], dump(cron))


def apply(repo, reveal=reveal_once):
    repo = Path(repo).resolve()
    state = json.loads((repo / "plan.json").read_text())
    target, picked = state["target"], state["selected"]
    validate_target(target)
    # Fresh capacity checks and review occur before any writes on the target.
    facts = inventory(target)
    resolved = selection(services.load(), picked, facts)
    summary(services.load(), resolved, facts, repo)
    if any("unknown" not in w for w in resolved["warnings"]):
        raise ProvisionError("Selection does not fit; remove services or provide a larger target")
    if input("Apply this reviewed repository? Type yes: ").strip() != "yes":
        print("Plan kept. Nothing applied.")
        return 0
    if "vault" in picked and reveal is reveal_once and not sys.stdin.isatty():
        raise ProvisionError("Vault initialisation needs an interactive terminal")
    values = decrypt(repo) if (repo / "secrets.enc.json").exists() else {}
    if "restic" in picked and "restic" not in values:
        existing = ""
        if target["kind"] == "ssh":
            existing = run(ssh_args(target) + ["sudo -n sh -c 'if test -f /opt/bromigos-lab/restic-password; then cat /opt/bromigos-lab/restic-password; fi'"])
        else:
            ns = {"apiVersion": "v1", "kind": "Namespace", "metadata": {"name": "lab-core"}}
            kubectl(target, ["apply", "-f", "-"], dump(ns))
            # The encrypted repo is the stable password source. A missing repo must never rotate a live backup key.
            names = json.loads(kubectl(target, ["-n", "lab-core", "get", "secrets", "-o", "json"]))["items"]
            for row in names:
                if row["metadata"]["name"] == "restic-password":
                    import base64
                    existing = base64.b64decode(row["data"]["password"]).decode()
        values["restic"] = existing or secrets.token_urlsafe(32)
    if values and "vault" not in picked:
        encrypt(repo, state["age_recipient"], values)
    if "restic" in picked and target["kind"] == "cluster":
        kubectl(target, ["-n", "lab-core", "get", "pvc", state["backup_path"]])
        kubectl(target, ["apply", "-f", "-"], dump({"apiVersion": "v1", "kind": "Secret", "metadata": {"name": "restic-password", "namespace": "lab-core"},
                "type": "Opaque", "stringData": {"password": values["restic"]}}))
    if "restic" in picked and target["kind"] == "ssh":
        # Runtime secret only on the target, root-owned; never in generated repository.
        run(ssh_args(target) + ["sudo -n install -d -m 0700 /opt/bromigos-lab"])
        run(ssh_args(target) + ["sudo -n sh -c 'umask 077; cat > /opt/bromigos-lab/restic-password'"], values["restic"])
    collection_path = repo / ".runtime/collections"
    run(["ansible-galaxy", "collection", "install", "-r", str(repo / "ansible/requirements.json"), "-p", str(collection_path)])
    env = dict(os.environ, ANSIBLE_CONFIG=str(repo / "ansible/ansible.cfg"), ANSIBLE_NO_LOG="true",
               ANSIBLE_COLLECTIONS_PATH=str(collection_path), ANSIBLE_NOCOWS="1")
    print("Applying the reviewed Ansible roles…")
    run(["ansible-playbook", "-i", "inventory/hosts.json", "playbooks/provision.json"], cwd=repo / "ansible", env=env)
    if "kubernetes" in picked or target["kind"] == "cluster":
        kubectl(target, ["wait", "--for=condition=Ready", "nodes", "--all", "--timeout=300s"])
    if "argocd" in picked:
        raw = kubectl(target, ["-n", "argocd", "get", "secret", "argocd-initial-admin-secret", "--ignore-not-found", "-o", "json"])
        if raw.strip():
            import base64
            secret = json.loads(raw)
            values["argocd-admin-password"] = base64.b64decode(secret["data"]["password"]).decode()
    if "vault" in picked:
        kubectl(target, ["-n", "vault", "wait", "--for=jsonpath={.status.phase}=Running", "pod/vault-0", "--timeout=300s"])
        with forward(target, "vault", "vault", 8200) as address:
            vault = Vault(address)
            keys = vault.initialise(reveal)
            if keys:
                vault.request("POST", "sys/auth/userpass", {"type": "userpass"})
                vault.request("PUT", "sys/policies/acl/lab-operator", {"policy":
                    'path "secret/data/lab/*" { capabilities = ["create", "read", "update", "patch"] }\n'
                    'path "secret/metadata/lab/*" { capabilities = ["read", "list"] }\n'
                    'path "auth/token/revoke-self" { capabilities = ["update"] }'})
                password = getpass.getpass("Choose a Vault operator password; store it in your password manager: ")
                if len(password) < 12:
                    raise ProvisionError("Use a Vault operator password of at least 12 characters")
                vault.request("POST", "auth/userpass/users/operator", {"password": password, "policies": "lab-operator"})
                password = None
            else:
                if vault.request("GET", "sys/seal-status")["sealed"]:
                    for _ in range(3):
                        vault.request("PUT", "sys/unseal", {"key": getpass.getpass("Unseal share: ")})
                vault.wait_active()
                password = getpass.getpass("Vault operator password (used in memory): ")
                vault.token = vault.request("POST", "auth/userpass/login/operator", {"password": password})["auth"]["client_token"]
                password = None
            for name, value in values.items():
                vault.store(name, {"value": value})
            if keys and input("Store 3 of 5 shares in a Kubernetes Secret for automatic unseal? Type yes (cluster admins can read them): ").strip() == "yes":
                auto_unseal(target, keys)
            if vault.request("GET", "sys/seal-status")["sealed"]:
                raise ProvisionError("Vault remains sealed")
            vault.request("POST", "auth/token/revoke-self", {})
            vault.token = None
            keys = None
    elif values:
        encrypt(repo, state["age_recipient"], values)
    values.clear()
    if "argocd" in picked:
        kubectl(target, ["apply", "-f", "-"], (repo / "gitops/root.yaml").read_text())
        kubectl(target, ["-n", "argocd", "wait", "--for=jsonpath={.status.sync.status}=Synced", "application/lab-apps", "--timeout=600s"])
        for _ in range(120):
            apps = json.loads(kubectl(target, ["-n", "argocd", "get", "applications", "-o", "json"]))["items"]
            if apps and any(a["metadata"]["name"] == "lab-apps" for a in apps) and all(a.get("status", {}).get("sync", {}).get("status") == "Synced" and
                   a.get("status", {}).get("health", {}).get("status") == "Healthy" for a in apps):
                break
            time.sleep(5)
        else:
            raise ProvisionError("Argo CD apps did not become synced and healthy")
    if "restic" in picked and target["kind"] == "cluster":
        jobs = json.loads(kubectl(target, ["-n", "lab-core", "get", "jobs", "-o", "json"]))["items"]
        if not any(j["metadata"]["name"] == "restic-first-backup" for j in jobs):
            kubectl(target, ["-n", "lab-core", "create", "job", "restic-first-backup", "--from=cronjob/restic"])
        kubectl(target, ["-n", "lab-core", "wait", "--for=condition=Complete", "job/restic-first-backup", "--timeout=300s"])
    if "restic" in picked and target["kind"] == "ssh":
        for _ in range(60):
            try:
                run(ssh_args(target) + ["sudo -n docker exec $(sudo -n docker ps -q --filter label=com.docker.compose.service=restic) test -f /status/last-success"])
                break
            except ProvisionError:
                time.sleep(2)
        else:
            raise ProvisionError("The first restic backup did not succeed")
    for attempt in range(30):
        try:
            verify_services(state)
            break
        except ProvisionError:
            if attempt == 29:
                raise
            time.sleep(2)
    connect(repo, state)
    print("Selected services applied and verified. The lab console is connected.")
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(prog="bromigos lab provision", description="Review and provision your own Linux box or Kubernetes cluster")
    parser.add_argument("verb", nargs="?", choices=("plan", "apply", "add", "remove"), default="plan")
    parser.add_argument("service", nargs="?")
    parser.add_argument("--repo", required=True, help="Your generated lab Git repository")
    parser.add_argument("--ssh", help="Linux box as user@host")
    parser.add_argument("--port", type=int, default=22)
    parser.add_argument("--identity", help="SSH private key path")
    parser.add_argument("--known-hosts", help="Explicit trusted SSH host key file")
    parser.add_argument("--kubeconfig")
    parser.add_argument("--context", help="Explicit Kubernetes context; never uses the ambient context")
    parser.add_argument("--preset", choices=("core", "advanced"), default="core")
    parser.add_argument("--services", nargs="+", choices=SUPPORTED, help="Selection from the dashboard tree")
    parser.add_argument("--custom", action="store_true", help="Choose services in a terminal checklist")
    parser.add_argument("--listen-address", default="127.0.0.1", help="Private IPv4 address for Caddy; defaults to loopback")
    parser.add_argument("--domain", default="", help="LAN HTTPS name; Caddy issues a local certificate")
    parser.add_argument("--git-url", default="", help="Published URL of your own lab repository")
    parser.add_argument("--backup-path", default="", help="Existing backup destination on the target")
    parser.add_argument("--age-recipient", default="", help="Your age public key for sops encryption")
    args = parser.parse_args(argv)
    try:
        if args.verb == "apply":
            return apply(args.repo)
        cat = services.load()
        if args.verb in ("add", "remove"):
            state = json.loads((Path(args.repo) / "plan.json").read_text())
            picked = state["selected"]
            if args.service not in SUPPORTED:
                raise ProvisionError("Choose a service with an installer in this slice")
            if args.verb == "add":
                picked = list(dict.fromkeys(picked + [args.service]))
            else:
                picked = [p for p in picked if p != args.service]
            target = state["target"]
            options = {"repo_url": state["git_url"], "backup_path": state["backup_path"], "age_recipient": state["age_recipient"], "domain": state.get("domain", ""), "listen_address": state.get("listen_address", "127.0.0.1")}
        else:
            if bool(args.ssh) == bool(args.kubeconfig):
                raise ProvisionError("Choose exactly one of --ssh or --kubeconfig")
            target = {"kind": "ssh", "ssh": args.ssh, "port": args.port, "identity": str(Path(args.identity).resolve()) if args.identity else "", "known_hosts": str(Path(args.known_hosts).resolve()) if args.known_hosts else ""} if args.ssh else {
                "kind": "cluster", "kubeconfig": str(Path(args.kubeconfig).resolve()), "context": args.context}
            picked = args.services or preset_selection(cat, args.preset)
            if args.custom:
                picked = checklist(cat, picked)
            options = dict(repo_url=args.git_url, backup_path=args.backup_path, age_recipient=args.age_recipient, domain=args.domain, listen_address=args.listen_address)
        facts = inventory(target)
        files, resolved = plan_files(target, picked, facts, cat=cat, **options)
        repo = generate(args.repo, files)
        summary(cat, resolved, facts, repo)
        print("Review and commit the files. Publish them if using Argo CD. Then run: bromigos lab provision apply --repo " + shlex.quote(str(repo)))
        return 0
    except (ProvisionError, OSError, ValueError, KeyError, EOFError, KeyboardInterrupt) as error:
        print("Provisioning stopped: " + (str(error) if isinstance(error, ProvisionError) else "Invalid or missing plan input"), file=sys.stderr)
        return 1


def checklist(cat, picked):
    picked = list(picked)
    while True:
        for group, rows in picker_rows(cat):
            print(group.upper())
            for service, title, hint in rows:
                print(f"  [{'x' if service in picked else ' '}] {service}: {title} — {hint}")
        choice = input("Service to toggle, core/advanced preset, or done: ").strip()
        if choice == "done":
            return selection(cat, picked)["services"]
        if choice in ("core", "advanced"):
            picked = preset_selection(cat, choice)
        elif choice in SUPPORTED:
            if choice in picked:
                warning = cat["service"][choice].get("untick_warning")
                if warning:
                    print(warning)
                picked.remove(choice)
            else:
                picked.append(choice)
            resolved = selection(cat, picked)
            for _, reason in resolved["added"]:
                print(reason)
            picked = resolved["services"]


def picker_rows(cat):
    return [(group, [(sid, row["title"], row["summary"]) for sid, row in cat["service"].items()
                     if sid in SUPPORTED and row["group"] == group]) for group in services.GROUPS
            if any(s in SUPPORTED and row["group"] == group for s, row in cat["service"].items())]


def verify_services(state):
    target = state["target"]
    picked = state["selected"]
    if target["kind"] == "ssh":
        for svc in picked:
            if svc in IMAGES:
                command = "sudo -n docker ps --filter " + shlex.quote("label=com.docker.compose.service=" + svc) + " --format '{{.State}}'"
                if run(ssh_args(target) + [command]).strip() != "running":
                    raise ProvisionError(svc + " is not running")
        for service, port, path in (("homepage", 3000, "/"), ("netdata", 19999, "/api/v1/info")):
            if service in picked:
                if "caddy" in picked:
                    url = "http://" + state.get("listen_address", "127.0.0.1") + "/" + ("netdata/api/v1/info" if service == "netdata" else "")
                    probe = "import urllib.request; urllib.request.urlopen(" + repr(url) + ", timeout=10).read()"
                    run(ssh_args(target) + ["python3 -"], probe)
    if "kubernetes" in picked or target["kind"] == "cluster":
        nodes = json.loads(kubectl(target, ["get", "nodes", "-o", "json"]))["items"]
        if not nodes or any(not any(c.get("type") == "Ready" and c.get("status") == "True" for c in n["status"]["conditions"]) for n in nodes):
            raise ProvisionError("Kubernetes nodes are not ready")
    if target["kind"] == "cluster" and any(s in picked for s in IMAGES):
        kubectl(target, ["-n", "lab-core", "wait", "--for=condition=Available", "deployment", "--all", "--timeout=300s"])
    if "argocd" in picked:
        root = json.loads(kubectl(target, ["-n", "argocd", "get", "application", "lab-apps", "-o", "json"]))
        status = root.get("status", {})
        if status.get("sync", {}).get("status") != "Synced" or status.get("health", {}).get("status") != "Healthy":
            raise ProvisionError("Argo CD's root application is not synced and healthy")
    if "vault" in picked:
        with forward(target, "vault", "vault", 8200) as address:
            status = Vault(address).request("GET", "sys/seal-status")
            if not status["initialized"] or status["sealed"]:
                raise ProvisionError("Vault must be initialised and unsealed")


def connect(repo, state):
    """Add a source without overwriting a user's existing sources or AI target order."""
    config_dir = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "bromigos"
    config_dir.mkdir(parents=True, exist_ok=True)
    homelab = config_dir / "homelab.toml"
    current = homelab.read_text() if homelab.exists() else ""
    marker = "# Generated lab provision source\n"
    block = marker + "[[source]]\ntype = \"provisioned\"\nname = \"provisioned-lab\"\nplan = " + json.dumps(str(repo / "plan.json")) + "\n"
    if marker in current:
        current = re.sub(re.escape(marker) + r'\[\[source\]\]\ntype = "provisioned"\nname = "provisioned-lab"\nplan = [^\n]*\n', lambda _m: block, current)
    else:
        current += "\n" + block
    write(homelab, current)
    targets = config_dir / "targets.toml"
    if not targets.exists():
        write(targets, "# No AI services selected. Keep the desktop's default target order.\n[targets]\n")
    env = dict(os.environ, BROMIGOS_HOMELAB_CONFIG=str(homelab))
    executable = Path(__file__).resolve().parents[2] / "bin/bromigos-lab"
    doc = json.loads(run([str(executable), "doctor", "--json"], env=env))
    if doc["summary"].get("fail"):
        raise ProvisionError("Lab doctor found failures; run bromigos lab doctor for fixes")


def cluster_core(picked, backup_pvc, domain=""):
    """Generic Core chart resources; all web services stay ClusterIP."""
    docs = [{"apiVersion": "v1", "kind": "PersistentVolumeClaim", "metadata": {"name": "lab-data"},
             "spec": {"accessModes": ["ReadWriteOnce"], "resources": {"requests": {"storage": "4Gi"}}}}]
    for service in picked:
        if service not in IMAGES or service == "restic":
            continue
        port = {"caddy": 80, "homepage": 3000, "netdata": 19999}[service]
        container = {"name": service, "image": "{{ .Values." + service + ".image }}", "ports": [{"containerPort": port}],
                     "readinessProbe": {"httpGet": {"path": "/", "port": port}, "initialDelaySeconds": 10},
                     "resources": {"requests": {"cpu": "100m", "memory": "128Mi"}}}
        mount = {"caddy": "/data", "homepage": "/app/config", "netdata": "/var/lib/netdata"}[service]
        container["volumeMounts"] = [{"name": "data", "mountPath": mount, "subPath": service}]
        setup = "mkdir -p /state/" + service
        if service == "homepage":
            setup += "; chown 1000:1000 /state/homepage"
        pod = {"containers": [container], "automountServiceAccountToken": False,
               "volumes": [{"name": "data", "persistentVolumeClaim": {"claimName": "lab-data"}}],
               "initContainers": [{"name": "folders", "image": "busybox:1.37.0", "command": ["/bin/sh", "-ec", setup],
                                   "volumeMounts": [{"name": "data", "mountPath": "/state"}]}],
               "affinity": {"podAffinity": {"requiredDuringSchedulingIgnoredDuringExecution": [{
                   "labelSelector": {"matchLabels": {"lab-core-data": "true"}}, "topologyKey": "kubernetes.io/hostname"}]}}}
        if service == "homepage":
            container["env"] = [{"name": "HOMEPAGE_ALLOWED_HOSTS", "value": "*"}]
            docs.append({"apiVersion": "v1", "kind": "ConfigMap", "metadata": {"name": "homepage-config"}, "data": homepage_files(picked)})
            pod["volumes"].append({"name": "homepage-config", "configMap": {"name": "homepage-config"}})
            pod["initContainers"][0]["volumeMounts"].append({"name": "homepage-config", "mountPath": "/defaults", "readOnly": True})
            pod["initContainers"][0]["command"][-1] += "; cp -n /defaults/* /state/homepage/; chown 1000:1000 /state/homepage/*"
        if service == "caddy":
            routes = ":80 {\n"
            if "netdata" in picked:
                routes += " handle_path /netdata/* {\n  reverse_proxy netdata:19999\n }\n"
            if "homepage" in picked:
                routes += " handle {\n  reverse_proxy homepage:3000\n }\n"
            else:
                routes += ' respond "Your lab is running"\n'
            routes += "}\n"
            if domain:
                routes += routes.replace(":80 {", domain + " {\n tls internal", 1)
            docs.append({"apiVersion": "v1", "kind": "ConfigMap", "metadata": {"name": "caddy"}, "data": {"Caddyfile": routes}})
            container["volumeMounts"].append({"name": "config", "mountPath": "/etc/caddy"})
            pod["volumes"].append({"name": "config", "configMap": {"name": "caddy"}})
        docs.extend([{"apiVersion": "apps/v1", "kind": "Deployment", "metadata": {"name": service},
                      "spec": {"replicas": 1, "selector": {"matchLabels": {"app": service}},
                               "template": {"metadata": {"labels": {"app": service, "lab-core-data": "true"}}, "spec": pod}}},
                     {"apiVersion": "v1", "kind": "Service", "metadata": {"name": service},
                      "spec": {"type": "ClusterIP", "selector": {"app": service}, "ports": [{"port": port, "targetPort": port}]}}])
    if "restic" in picked:
        docs.append({"apiVersion": "batch/v1", "kind": "CronJob", "metadata": {"name": "restic"}, "spec": {
            "schedule": "0 2 * * *", "concurrencyPolicy": "Forbid", "jobTemplate": {"spec": {"template": {"spec": {
                "restartPolicy": "OnFailure", "automountServiceAccountToken": False, "containers": [{"name": "restic", "image": "{{ .Values.restic.image }}",
                "command": ["/bin/sh", "-ec", "restic snapshots >/dev/null 2>&1 || restic init; restic backup /data"],
                "env": [{"name": "RESTIC_REPOSITORY", "value": "/repository"}, {"name": "RESTIC_PASSWORD", "valueFrom": {"secretKeyRef": {"name": "restic-password", "key": "password"}}}],
                "volumeMounts": [{"name": "backup", "mountPath": "/repository"}, {"name": "data", "mountPath": "/data", "readOnly": True}]}],
                "volumes": [{"name": "backup", "persistentVolumeClaim": {"claimName": backup_pvc}},
                            {"name": "data", "persistentVolumeClaim": {"claimName": "lab-data"}}]}}}}}})
    for doc in docs:
        doc["metadata"].setdefault("annotations", {})["helm.sh/resource-policy"] = "keep"
    return docs


def preset_selection(cat, name):
    defaults = [sid for sid, row in cat["service"].items() if row.get("default") and sid in SUPPORTED]
    return list(dict.fromkeys(defaults + services.preset(cat, name)["services"]))


def homepage_files(picked):
    links = []
    if "netdata" in picked:
        links.append({"Netdata": {"href": "/netdata/", "description": "Live metrics", "siteMonitor": "http://netdata:19999/api/v1/info"}})
    if "restic" in picked:
        links.append({"Backups": {"description": "Daily encrypted backups. Check the last run with bromigos lab doctor."}})
    return {"services.yaml": dump([{"Your lab": links}]) if links else "[]\n",
            "settings.yaml": "title: Your lab\n", "widgets.yaml": "[]\n", "bookmarks.yaml": "[]\n", "docker.yaml": "{}\n"}
