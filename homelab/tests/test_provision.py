"""Plan goldens, selection safety and secret boundaries. No live lab is used."""
import contextlib
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from bromigos_homelab import provision as P, services as S

os.environ["BROMIGOS_LAB_PROFILES"] = str(Path(__file__).resolve().parents[1] / "share/lab/profiles.toml")

TARGET = {"kind": "ssh", "ssh": "tester@lab.example.org", "port": 22, "identity": ""}
FACTS = {"cpu": 8, "ram_gib": 32, "disk_gib": 100, "distribution": "debian", "gpu": "none", "vram_gib": 0}


class PlanTests(unittest.TestCase):
    def golden(self, preset, **options):
        files, resolved = P.plan_files(TARGET, P.preset_selection(S.load(), preset), FACTS, **options)
        path = Path(__file__).parent / "golden" / (preset + ".json")
        self.assertEqual(json.loads(path.read_text()), files)
        for text in files.values():
            self.assertNotIn("unseal", text)
        return files

    def test_core_golden(self):
        self.golden("core", backup_path="/mnt/backups", age_recipient="age1example")

    def test_advanced_golden(self):
        self.golden("advanced", repo_url="https://git.example.org/user/lab.git", backup_path="/mnt/backups", age_recipient="age1example")

    def test_existing_cluster_explicit_context(self):
        target = {"kind": "cluster", "kubeconfig": "/tmp/test-kubeconfig", "context": "throwaway"}
        files, _ = P.plan_files(target, ["vault", "argocd"], FACTS, repo_url="https://git.example.org/user/lab.git")
        play = json.loads(files["ansible/playbooks/provision.json"])
        self.assertFalse(play[0]["become"])
        self.assertNotIn("k3s", play[0]["roles"])
        with self.assertRaises(P.ProvisionError):
            P.validate_target({"kind": "cluster", "kubeconfig": "file"})

    def test_existing_cluster_does_not_budget_a_second_server(self):
        facts = dict(FACTS, distribution="cluster", ram_gib=8, disk_gib=None)
        result = P.selection(S.load(), ["vault", "argocd"], facts)
        self.assertFalse(any("ram_gib" in w for w in result["warnings"]))
        self.assertTrue(any("unknown" in w for w in result["warnings"]))

    def test_cluster_core_has_no_host_privilege_or_exposure(self):
        target = {"kind": "cluster", "kubeconfig": "/tmp/test-kubeconfig", "context": "throwaway"}
        files, _ = P.plan_files(target, P.preset_selection(S.load(), "core"), FACTS,
                               backup_path="backups", age_recipient="age1example")
        docs = files["helm/core/templates/services.yaml"]
        self.assertNotIn("hostPath", docs)
        self.assertNotIn("NodePort", docs)
        self.assertNotIn("LoadBalancer", docs)
        self.assertIn("restic-password", docs)
        self.assertNotIn("stringData", docs)
        self.assertTrue(all(d["metadata"]["annotations"]["helm.sh/resource-policy"] == "keep" for d in P.cluster_core(["caddy", "netdata", "restic", "homepage"], "backups")))

    def test_https_name_uses_local_certificates(self):
        files, _ = P.plan_files(TARGET, ["caddy"], FACTS, domain="lab.example.org")
        self.assertIn("lab.example.org {", files["compose/Caddyfile"])
        self.assertIn("tls internal", files["compose/Caddyfile"])

    def test_no_public_proxy_bind(self):
        with self.assertRaises(P.ProvisionError):
            P.plan_files(TARGET, ["caddy"], FACTS, listen_address="0.0.0.0")
        with self.assertRaises(P.ProvisionError):
            P.plan_files(TARGET, ["caddy"], FACTS, listen_address="8.8.8.8")
        files, _ = P.plan_files(TARGET, ["caddy"], FACTS)
        self.assertEqual(json.loads(files["compose/compose.yaml"])["services"]["caddy"]["ports"],
                         ["127.0.0.1:80:80", "127.0.0.1:443:443"])

    def test_no_credentials_in_url_or_target(self):
        for url in ("https://token@git.example.org/lab", "ssh://git.example.org/lab"):
            with self.assertRaises(P.ProvisionError):
                P.plan_files(TARGET, ["argocd"], FACTS, repo_url=url)
        with self.assertRaises(P.ProvisionError):
            P.validate_target({"kind": "ssh", "ssh": "-oProxyCommand=bad"})

    def test_unsupported_and_conflicts_fail(self):
        for picked in (["plex"], ["ollama", "vllm"], ["missing"]):
            with self.assertRaises(P.ProvisionError):
                P.selection(S.load(), picked)

    def test_resolver_reports_unmet(self):
        cat = {"service": {"one": {"title": "One", "depends": ["nothing"]}}}
        self.assertEqual(S.resolve(cat, ["one"])["unmet"], [("one", "nothing")])

    def test_roles_and_capacity(self):
        cat = S.load()
        result = S.resolve(cat, ["argocd", "vault"])
        self.assertTrue({"kubernetes", "helm", "argocd", "vault"}.issubset(result["services"]))
        self.assertTrue(S.fit(cat, result["services"], dict(FACTS, ram_gib=2)))
        self.assertFalse(S.fit(cat, result["services"], FACTS))

    def test_cluster_core_renders_with_helm(self):
        import shutil
        if not shutil.which("helm"):
            self.skipTest("Helm is not installed")
        target = {"kind": "cluster", "kubeconfig": "/tmp/test-kubeconfig", "context": "throwaway"}
        files, _ = P.plan_files(target, P.preset_selection(S.load(), "core"), FACTS,
                               backup_path="backups", age_recipient="age1example")
        with tempfile.TemporaryDirectory() as tmp:
            for name, text in files.items():
                P.write(Path(tmp) / name, text)
            rendered = P.run(["helm", "template", "lab-core", str(Path(tmp) / "helm/core")])
            self.assertIn("ghcr.io/gethomepage/homepage:v2.5.0", rendered)
            self.assertNotIn("{{", rendered)
            self.assertIn("persistentVolumeClaim", rendered)

    def test_generate_rejects_dirty_repo(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = P.generate(tmp, {"plan.json": "{}"})
            with self.assertRaises(P.ProvisionError):
                P.generate(repo, {"plan.json": "changed"})


class ApplyApprovalTests(unittest.TestCase):
    def test_no_answer_does_not_apply_or_generate_secrets(self):
        with tempfile.TemporaryDirectory() as tmp:
            files, _ = P.plan_files(TARGET, ["caddy"], FACTS)
            repo = P.generate(tmp, files)
            with mock.patch.object(P, "inventory", return_value=FACTS), mock.patch("builtins.input", return_value="no"), \
                    mock.patch.object(P, "run") as run, mock.patch.object(P.secrets, "token_urlsafe") as generate, \
                    contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(P.apply(repo), 0)
                run.assert_not_called()
                generate.assert_not_called()

    def test_capacity_failure_happens_before_approval_and_writes(self):
        with tempfile.TemporaryDirectory() as tmp:
            files, _ = P.plan_files(TARGET, ["argocd"], FACTS, repo_url="https://git.example.org/user/lab.git", age_recipient="age1example")
            repo = P.generate(tmp, files)
            with mock.patch.object(P, "inventory", return_value=dict(FACTS, ram_gib=1)), \
                    mock.patch("builtins.input") as answer, mock.patch.object(P, "run") as run, \
                    contextlib.redirect_stdout(io.StringIO()):
                with self.assertRaises(P.ProvisionError):
                    P.apply(repo)
                answer.assert_not_called()
                run.assert_not_called()


class SecretTests(unittest.TestCase):
    def test_shares_only_reach_reveal_and_unseal(self):
        keys = ["TEST-SHARE-" + str(i) for i in range(5)]
        vault = P.Vault("http://unused")
        calls = []
        def request(method, path, body=None):
            calls.append((method, path, body))
            if path == "sys/init" and method == "GET":
                return {"initialized": False}
            if path == "sys/init":
                return {"keys_base64": keys, "root_token": "TEST-ROOT"}
            if path == "sys/health":
                return {"initialized": True, "sealed": False, "standby": False}
            return {}
        vault.request = request
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(P, "write") as write, \
                mock.patch.object(P, "run") as run, contextlib.redirect_stdout(io.StringIO()) as stdout, \
                contextlib.redirect_stderr(io.StringIO()) as stderr:
            seen = []
            actual = vault.initialise(lambda shares: seen.append(list(shares)))
            self.assertEqual(actual, keys)
            self.assertEqual(seen, [keys])
            self.assertEqual(len([c for c in calls if c[1] == "sys/unseal"]), 3)
            write.assert_not_called()
            run.assert_not_called()
            self.assertFalse(list(Path(tmp).iterdir()))
            for secret in keys + ["TEST-ROOT"]:
                self.assertNotIn(secret, stdout.getvalue() + stderr.getvalue())

    def test_initialised_vault_never_reinitialises_or_reveals(self):
        vault = P.Vault("http://unused")
        vault.request = mock.Mock(return_value={"initialized": True})
        reveal = mock.Mock()
        self.assertFalse(vault.initialise(reveal))
        reveal.assert_not_called()
        vault.request.assert_called_once_with("GET", "sys/init")

    def test_waits_for_active_vault_after_unseal(self):
        vault = P.Vault("http://unused")
        vault.request = mock.Mock(side_effect=[P.ProvisionError("not active"), {"initialized": True, "sealed": False, "standby": False}])
        with mock.patch.object(P.time, "sleep"):
            vault.wait_active()
        self.assertEqual(vault.request.call_count, 2)

    def test_error_does_not_log_subprocess_secrets(self):
        result = mock.Mock(returncode=1, stdout="TEST-SECRET", stderr="TEST-KEY")
        with mock.patch.object(P.subprocess, "run", return_value=result):
            with self.assertRaises(P.ProvisionError) as error:
                P.run(["ansible-playbook"], "TEST-INPUT")
            for secret in ("TEST-SECRET", "TEST-KEY", "TEST-INPUT"):
                self.assertNotIn(secret, str(error.exception))

    def test_forward_waits_for_vault_http_not_just_a_socket(self):
        response = mock.MagicMock()
        response.__enter__.return_value.read.return_value = b'{"sealed": true}'
        proc = mock.Mock()
        proc.poll.return_value = None
        with mock.patch.object(P.subprocess, "Popen", return_value=proc), \
                mock.patch.object(P.urllib.request, "urlopen", side_effect=[ConnectionResetError(), response]) as http, \
                mock.patch.object(P.time, "sleep"):
            with P.forward(TARGET, "vault", "vault", 8200) as address:
                self.assertTrue(address.startswith("http://127.0.0.1:"))
            self.assertEqual(http.call_count, 2)
            for call in http.call_args_list:
                self.assertEqual(call.args[0].get_method(), "GET")
                self.assertTrue(call.args[0].full_url.endswith("/v1/sys/seal-status"))
            proc.terminate.assert_called_once()

    def test_only_sops_ciphertext_written(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(P, "run", return_value="ENCRYPTED") as run:
            P.encrypt(tmp, "age1example", {"password": "TEST-PASSWORD"})
            self.assertEqual((Path(tmp) / "secrets.enc.json").read_text(), "ENCRYPTED")
            self.assertNotIn("TEST-PASSWORD", " ".join(run.call_args.args[0]))

    def test_auto_unseal_is_not_in_plan_and_only_three_shares_sent(self):
        with mock.patch.object(P, "kubectl") as kube:
            P.auto_unseal(TARGET, ["KEY-" + str(i) for i in range(5)])
            body = json.loads(kube.call_args_list[0].args[2])
            self.assertEqual(list(body["stringData"].values()), ["KEY-0", "KEY-1", "KEY-2"])
            for call in kube.call_args_list:
                self.assertNotIn("KEY-3", str(call))
                self.assertNotIn("KEY-4", str(call))
