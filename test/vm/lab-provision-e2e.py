#!/usr/bin/env python3
"""Core, Advanced and repeated apply on a fresh Debian guest. Never uses a real cluster."""
import contextlib
import functools
import http.server
import io
import importlib.util
import json
import os
from pathlib import Path
import secrets
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
from unittest import mock

TASK_HOME = Path.home()
for key in list(os.environ):
    if key.startswith("VAULT_") or key in ("KUBECONFIG", "SSH_AUTH_SOCK", "BROMIGOS_HOMELAB_CONFIG"):
        os.environ.pop(key, None)
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "homelab/lib"))
sys.path.insert(0, str(ROOT / "lib"))
os.environ["BROMIGOS_LAB_PROFILES"] = str(ROOT / "homelab/share/lab/profiles.toml")
from bromigos_homelab import provision as P

proof_spec = importlib.util.spec_from_file_location("isolated_monitoring_proof", ROOT / "test/vm/lab-infrastructure-e2e.py")
proof = importlib.util.module_from_spec(proof_spec)
proof_spec.loader.exec_module(proof)


class QuietHTTP(http.server.BaseHTTPRequestHandler):
    """A real smart Git HTTP backend, so Argo exercises normal clone and fetch."""
    def log_message(self, *_args):
        pass

    def do_GET(self):
        self.backend()

    def do_POST(self):
        self.backend()

    def backend(self):
        from urllib.parse import urlsplit, unquote
        url = urlsplit(self.path)
        path = unquote(url.path)
        if ".." in path.split("/"):
            self.send_error(400)
            return
        length = int(self.headers.get("Content-Length", 0))
        if length > 8 * 1024**2:
            self.send_error(413)
            return
        env = dict(os.environ, GIT_PROJECT_ROOT=str(self.server.gitroot), GIT_HTTP_EXPORT_ALL="1",
                   PATH_INFO=path, QUERY_STRING=url.query, REQUEST_METHOD=self.command,
                   CONTENT_TYPE=self.headers.get("Content-Type", ""), CONTENT_LENGTH=str(length))
        result = subprocess.run(["git", "http-backend"], input=self.rfile.read(length), env=env, capture_output=True)
        head, _, body = result.stdout.partition(b"\r\n\r\n")
        headers = [line.split(":", 1) for line in head.decode().splitlines() if ":" in line]
        status = next((int(value.strip().split()[0]) for key, value in headers if key.lower() == "status"), 200)
        self.send_response(status)
        for key, value in headers:
            if key.lower() != "status":
                self.send_header(key, value.strip())
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def free_port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def commit(repo):
    paths = [p for p in P.run(["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"], cwd=repo).split("\0") if p]
    P.run(["git", "add", "--"] + paths, cwd=repo)
    P.run(["git", "-c", "user.name=VM test", "-c", "user.email=test@example.org", "commit", "--quiet", "-m", "Review the generated plan"], cwd=repo)


def main():
    base = Path(os.environ.get("BROMIGOS_PROVISION_TEST_DIR", TASK_HOME / ".cache/bromigos-provision-e2e"))
    if base.exists():
        raise SystemExit("Choose a new BROMIGOS_PROVISION_TEST_DIR; the test refuses to reuse a VM disk")
    base.mkdir(parents=True)
    vm = base / "vm"
    vm.mkdir()
    env = dict(os.environ, BROMIGOS_VM_DIR=str(vm), BROMIGOS_VM_PORT=str(free_port()), BROMIGOS_VM_VNC="59",
               BROMIGOS_VM_MEM="8192", BROMIGOS_VM_CPUS="2", BROMIGOS_VM_DISK_GIB="180", BROMIGOS_VM_OWNER=str(os.getpid()))
    harness = str(ROOT / "test/vm/lab-vm.py")
    server = None
    recovery = []
    # OpenSSH adds a 17-byte suffix while binding its Unix control socket.
    # A long sandbox HOME can otherwise exceed Linux's 108-byte socket path.
    control_dir = tempfile.TemporaryDirectory(prefix='lab-ssh-')
    os.environ['ANSIBLE_SSH_CONTROL_PATH_DIR'] = control_dir.name
    try:
        subprocess.run([harness, "up"], env=env, check=True)
        subprocess.run([harness, "ssh", "sudo mkdir -p /mnt/backups"], env=env, check=True)
        known = base / "known_hosts"
        with known.open("w") as stream:
            subprocess.run(["ssh-keyscan", "-p", env["BROMIGOS_VM_PORT"], "127.0.0.1"], stdout=stream, stderr=subprocess.DEVNULL, check=True)
        target = dict(kind="ssh", ssh="tester@127.0.0.1", port=int(env["BROMIGOS_VM_PORT"]),
                      identity=str(vm / "id_ed25519"), known_hosts=str(known))
        os.environ["HOME"] = str(base / "home")
        (base / "home").mkdir()
        os.environ["XDG_CONFIG_HOME"] = str(base / "config")
        os.environ["BROMIGOS_TARGETS_CONFIG"] = str(base / "config/bromigos/targets.toml")
        os.environ["BROMIGOS_HOMELAB_CONFIG"] = str(base / "config/bromigos/homelab.toml")
        os.environ["SOPS_AGE_KEY_FILE"] = str(base / "age.key")
        keygen = subprocess.run(["age-keygen", "-o", os.environ["SOPS_AGE_KEY_FILE"]], capture_output=True, text=True, check=True)
        recipient = keygen.stderr.strip().split("Public key: ")[-1]
        repo = base / "lab"
        import runpy
        bounded = runpy.run_path(str(ROOT / 'test/vm/bounded-profile.py'))
        bounded['catalog'](ROOT / 'homelab/share/lab/profiles.toml', base / 'test-profiles.toml')
        os.environ['BROMIGOS_LAB_PROFILES'] = str(base / 'test-profiles.toml')
        original_plan = P.O.cluster_plan
        def small_plan(files, *args):
            original_plan(files, *args); bounded['trim'](files)
        P.O.cluster_plan = small_plan
        cat = P.services.load()
        facts = P.inventory(target)
        files, _ = P.plan_files(target, P.preset_selection(cat, "core"), facts, backup_path="/mnt/backups", age_recipient=recipient)
        P.generate(repo, files)
        commit(repo)
        with mock.patch("builtins.input", return_value="yes"):
            P.apply(repo)
            P.apply(repo)
        proof.monitoring_proof(json.loads((repo / "plan.json").read_text()), P.decrypt(repo)["grafana-admin-password"])
        proof.alert_proof(base, json.loads((repo / "plan.json").read_text()))
        print("PASS: Core, first backup, doctor and repeated apply")
        commit(repo)  # sops ciphertext generated by apply
        gitroot = base / "git"
        gitroot.mkdir()
        port = free_port()
        url = f"http://10.0.2.2:{port}/lab.git"  # privacy: allow (QEMU guest-to-host address)
        # QEMU's isolated user-network gateway, never a lab address
        files, _ = P.plan_files(target, P.preset_selection(cat, "advanced"), P.inventory(target),
                               repo_url=url, backup_path="/mnt/backups", age_recipient=recipient)
        P.generate(repo, files)
        commit(repo)
        P.run(["git", "clone", "--bare", str(repo), str(gitroot / "lab.git")])
        P.run(["git", "update-server-info"], cwd=gitroot / "lab.git")
        server = http.server.ThreadingHTTPServer(("127.0.0.1", port), QuietHTTP)
        server.gitroot = gitroot
        threading.Thread(target=server.serve_forever, daemon=True).start()
        password = secrets.token_urlsafe(24)
        def reveal(shares):
            recovery.extend(shares)  # Memory only; test stdout and files must never contain a share.
        captured = io.StringIO()
        with contextlib.redirect_stdout(captured), contextlib.redirect_stderr(captured), \
                mock.patch("builtins.input", return_value="yes"), mock.patch.object(P.getpass, "getpass", return_value=password):
            P.apply(repo, reveal=reveal)
            print("PASS: first Advanced apply and health verification", file=sys.__stdout__, flush=True)
            P.apply(repo, reveal=reveal)
            print("PASS: repeated Advanced apply and health verification", file=sys.__stdout__, flush=True)
        proof.monitoring_proof(json.loads((repo / "plan.json").read_text()), P.decrypt(repo)["grafana-admin-password"])
        proof.alert_proof(base, json.loads((repo / "plan.json").read_text()))
        # Exercise the second supported transport against this same isolated cluster.
        # Its admin kubeconfig is temporary, mode 0600, and never enters Git.
        api_port = free_port()
        tunnel = subprocess.Popen(P.ssh_args(target)[:-1] + ["-N", "-L", f"{api_port}:127.0.0.1:6443", target["ssh"]],
                                  stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        kube_path = base / "api-kubeconfig.json"
        existing_checked = False
        try:
            kube = json.loads(P.kubectl(target, ["config", "view", "--raw", "-o", "json"]))
            kube["clusters"][0]["cluster"]["server"] = f"https://127.0.0.1:{api_port}"
            kube["contexts"][0]["name"] = "throwaway"
            kube["current-context"] = "throwaway"
            P.write(kube_path, P.dump(kube))
            existing = {"kind": "cluster", "kubeconfig": str(kube_path), "context": "throwaway"}
            import time
            for attempt in range(30):
                try:
                    cluster_facts = P.inventory(existing)
                    break
                except P.ProvisionError:
                    if attempt == 29:
                        raise
                    time.sleep(.2)
            cluster_repo = base / "existing-cluster"
            files, _ = P.plan_files(existing, ["kubernetes", "helm", "argocd", "vault"], cluster_facts, repo_url=url, age_recipient=recipient)
            P.generate(cluster_repo, files)
            commit(cluster_repo)
            with contextlib.redirect_stdout(captured), contextlib.redirect_stderr(captured), \
                    mock.patch("builtins.input", return_value="yes"), mock.patch.object(P.getpass, "getpass", return_value=password):
                P.apply(cluster_repo, reveal=reveal)
            existing_checked = True
            print("PASS: existing kubeconfig target, explicit context, local Ansible with no sudo")
        finally:
            tunnel.terminate()
            tunnel.wait(10)
            kube_path.unlink(missing_ok=True)
            if existing_checked:
                P.connect(repo, json.loads((repo / "plan.json").read_text()))
        for key in recovery:
            assert key not in captured.getvalue()
            for path in base.rglob("*"):
                if path.is_file() and path.suffix not in (".qcow2", ".iso"):
                    assert key.encode() not in path.read_bytes(), "Vault share leaked to disk"
        assert len(recovery) == 5, "Vault initialised more than once"
        state = json.loads((repo / "plan.json").read_text())
        P.verify_services(state)
        apps = json.loads(P.kubectl(target, ["-n", "argocd", "get", "applications", "-o", "json"]))["items"]
        assert apps and all(a["status"]["sync"]["status"] == "Synced" for a in apps)
        doctor = json.loads(P.run([str(ROOT / "homelab/bin/bromigos-lab"), "doctor", "--json"]))
        for finding in doctor["findings"]:
            if finding["status"] in ("fail", "warn"):
                print(finding["status"], finding["title"], finding["detail"])
        assert doctor["summary"]["fail"] == 0 and doctor["summary"]["warn"] == 0, "Doctor is not green"
        print("PASS: k3s, Helm, Argo CD app-of-apps synced, Vault initialised/unsealed, doctor green")
        print("PASS: repeated Advanced apply; five shares revealed once, no shares on disk or in logs")
    except Exception:
        # Keep failure metadata useful without printing a release or its raw error.
        try:
            failed = json.loads(P.run(P.ssh_args(target) + ["sudo -n env KUBECONFIG=/etc/rancher/k3s/k3s.yaml helm status lab-monitoring -n monitoring -o json"]))['info']
            description = failed.get('description', '').lower()
            print("Monitoring failure fields:", {word: word in description for word in
                  ('immutable', 'persistentvolumeclaim', 'statefulset', 'storageclassname', 'spec.selector', 'conflict')})
            failed = description = None
        except (P.ProvisionError, OSError, ValueError, KeyError):
            pass
        # Names, images and state only: no container env, Secret values or Vault responses.
        subprocess.run([harness, "ssh", "sudo docker ps -a --format '{{.Names}} {{.Image}} {{.Status}}'"], env=env, check=False)
        raise
    finally:
        recovery.clear()
        if server:
            server.shutdown()
            server.server_close()
        subprocess.run([harness, "destroy"], env=env, check=False)
        for path in (vm / "id_ed25519", base / "age.key"):
            path.unlink(missing_ok=True)
        control_dir.cleanup()
        print("VM stopped and its disk removed")


if __name__ == "__main__":
    main()
