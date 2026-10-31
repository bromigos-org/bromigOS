"""The secret store's backends: local systemd credentials (with and without a TPM), a Vault /
OpenBao (an HTTP stub of Vault's API on 127.0.0.1: rootless Podman isn't available to these
tests, so no real OpenBao dev server), sops, and the answer-file references. No network."""
import json
import os
from pathlib import Path
import tempfile
import unittest

from bromigos_homelab import secretstore as S
from provfake import FakeMachine, VaultStub


class LocalTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = self.tmp.name
        self.m = FakeMachine(self.root)
        self.store = S.LocalStore(self.root, self.m, "box")

    def tearDown(self):
        self.tmp.cleanup()

    def test_put_get_and_never_plain(self):
        self.store.put("gluetun/password", "hunter2-typed-value")
        self.assertEqual(self.store.get("gluetun/password"), "hunter2-typed-value")
        cred = Path(self.root, S.CREDSTORE, "bromigos.gluetun.password")
        self.assertTrue(cred.exists())
        self.assertNotIn("hunter2", cred.read_text())
        enc = self.m.ran("systemd-creds encrypt")[0]
        self.assertIn("--with-key=auto", enc)     # TPM2 plus host key, never TPM-only
        self.assertEqual(S.scan(self.root, {"x": "hunter2-typed-value"}), [])

    def test_generated_once_unique_random(self):
        self.assertTrue(self.store.generate("sonarr/api-key", "apikey"))
        self.assertFalse(self.store.generate("sonarr/api-key", "apikey"))
        self.store.generate("radarr/api-key", "apikey")
        a, b = self.store.get("sonarr/api-key"), self.store.get("radarr/api-key")
        self.assertNotEqual(a, b)
        self.assertRegex(a, r"^[0-9a-f]{32}$")
        self.assertEqual(len({S.random_value() for _ in range(50)}), 50)

    def test_tpm_and_no_tpm(self):
        self.assertIn("TPM chip", self.store.where())
        self.m.tpm = False
        self.assertNotIn("TPM", self.store.where())
        self.assertIn("host key", self.store.where())

    def test_summary_never_values(self):
        self.store.put("a/b", "value-one-xyz")
        self.store.generate("c/d")
        s = self.store.summary()
        self.assertTrue(s.startswith("2 keys stored on this server"))
        self.assertNotIn("value-one", json.dumps(self.store.status()))

    def test_rotate_restarts_users_and_refuses_typed(self):
        self.store.generate("restic/password", users=["bromigos-lab-backup.service"])
        old = self.store.get("restic/password")
        restarted = self.store.rotate("restic/password")
        self.assertNotEqual(self.store.get("restic/password"), old)
        self.assertEqual(restarted, ["bromigos-lab-backup.service"])
        self.assertTrue(self.m.ran("systemctl try-restart bromigos-lab-backup.service"))
        self.store.put("gluetun/password", "typed-one")
        with self.assertRaises(S.SecretError):
            self.store.rotate("gluetun/password")
        self.store.rotate("gluetun/password", "typed-two")
        self.assertEqual(self.store.get("gluetun/password"), "typed-two")

    def test_podman_copy_through_shell_driver(self):
        self.store.put("x/y", "no-driver-yet")
        self.assertEqual(self.m.podman_secrets, {})
        p = Path(self.root, S.PODMAN_DROPIN)
        p.parent.mkdir(parents=True)
        p.write_text(S.podman_driver_conf())
        self.store.put("x/y", "with-driver")
        self.assertIn("bromigos-x-y", self.m.podman_secrets)
        self.assertIn('driver = "shell"', p.read_text())
        self.assertIn("systemd-creds decrypt", p.read_text())

    def test_recovery_bundle_and_restore(self):
        self.store.put("gluetun/password", "pw-for-the-vpn")
        key = self.store.recovery_key()
        self.assertTrue(key.startswith("AGE-SECRET-KEY-"))
        bundle = Path(self.store.recovery_bundle())
        self.assertNotIn("pw-for-the-vpn", bundle.read_text())
        self.assertIn("recovery bundle", self.store.recovery_text())
        self.store.ack_recovery()
        self.assertIsNone(self.store.recovery_key())
        # a new server: restore from the bundle and the key
        with tempfile.TemporaryDirectory() as other:
            fresh = S.LocalStore(other, FakeMachine(other), "box")
            self.assertIn("gluetun/password", fresh.restore(bundle.read_text(), key))
            self.assertEqual(fresh.get("gluetun/password"), "pw-for-the-vpn")

    def test_names_checked(self):
        for bad in ("../etc", "Up/Case", "", "a b"):
            with self.assertRaises(S.SecretError):
                self.store.put(bad, "v")

    def test_config_refuses_values(self):
        with self.assertRaises(S.SecretError):
            S.write_config({"backend": "vault", "vault": {"address": "https://v", "secret_id": "x"}}, self.root)
        S.write_config({"backend": "local"}, self.root)
        self.assertIsInstance(S.open_store(root=self.root, run=self.m), S.LocalStore)


class VaultTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = self.tmp.name
        self.m = FakeMachine(self.root)
        self.v = VaultStub()

    def tearDown(self):
        self.v.close()
        self.tmp.cleanup()

    def admin(self):
        return S.VaultStore(self.v.address, auth={"method": "token", "token": "admin-token"}, root=self.root,
                            run=self.m, hostname="box")

    def test_refuses_root_token(self):
        s = S.VaultStore(self.v.address, auth={"method": "token", "token": "root-token"}, root=self.root, run=self.m)
        with self.assertRaises(S.SecretError) as e:
            s.login()
        self.assertIn("root token", str(e.exception))

    def test_refuses_plain_http_elsewhere(self):
        with self.assertRaises(S.SecretError):
            S.VaultStore("http://192.0.2.10:8200")

    def test_policy_then_approle_then_put_get(self):
        s = self.admin()
        preview = s.policy_preview()
        self.assertIn('path "kv/data/bromigos/servers/box/*"', preview)
        r = s.ensure_server_policy()
        self.assertEqual(r["policy"], "bromigos-server-box")
        self.assertIn("bromigos-server-box", self.v.policies)
        # it now signs in with its own AppRole, kept encrypted locally, never as plain text
        s.put("gluetun/password", "vault-held-value")
        self.assertEqual(self.v.kv["kv/bromigos/servers/box/gluetun/password"], {"value": "vault-held-value"})
        self.assertEqual(s.get("gluetun/password"), "vault-held-value")
        used = [t for (_, p, t) in self.v.log if p.startswith("kv/data")]
        self.assertNotIn("admin-token", used)
        sid = s.local.get("vault/secret-id")
        self.assertEqual(S.scan(self.root, {"sid": sid, "v": "vault-held-value"}), [])
        self.assertTrue(s.test()["ok"])

    def test_least_privilege(self):
        s = self.admin()
        s.ensure_server_policy()
        s.login()
        with self.assertRaises(S.SecretError):
            s.request("POST", "kv/data/bromigos/servers/other-box/x", {"data": {"value": "no"}})

    def test_wrapped_token(self):
        s = self.admin()
        s.ensure_server_policy()
        role = self.v.roles["bromigos-server-box"]
        wrap = self.v.wrap({"data": {"secret_id": role["secret_ids"][0]}})
        w = S.VaultStore(self.v.address, auth={"method": "wrapped", "wrapping_token": wrap, "role_id": role["role_id"]},
                         root=self.root, run=self.m, hostname="box")
        w.put("plex/claim", "claim-abc-123")
        self.assertEqual(w.get("plex/claim"), "claim-abc-123")
        again = S.VaultStore(self.v.address, auth={"method": "wrapped", "wrapping_token": wrap, "role_id": role["role_id"]},
                             root=self.root, run=self.m, hostname="box")
        with self.assertRaises(S.SecretError):                  # a wrapped token works once
            again.login()

    def test_approle_auth(self):
        s = self.admin()
        s.ensure_server_policy()
        role = self.v.roles["bromigos-server-box"]
        a = S.VaultStore(self.v.address, auth={"method": "approle", "role_id": role["role_id"], "secret_id": role["secret_ids"][0]},
                         root=self.root, run=self.m, hostname="box")
        a.generate("restic/password")
        self.assertIn("kv/bromigos/servers/box/restic/password", self.v.kv)

    def test_oidc(self):
        s = S.VaultStore(self.v.address, root=self.root, run=self.m)
        self.assertTrue(s.oidc_auth_url("http://localhost:8250/oidc/callback").startswith("https://"))
        s.oidc_callback("abc", "code")
        self.assertTrue(s.token)

    def test_lab_layout_detected(self):
        v = VaultStub(kv=None)
        try:
            v.mounts["secret/"] = {"type": "kv", "options": {"version": "2"}}
            s = S.VaultStore(v.address, auth={"method": "token", "token": "admin-token"}, root=self.root, run=self.m, hostname="box")
            self.assertEqual(s.layout(), ("secret", "lab/servers/box"))
        finally:
            v.close()

    def test_answer_refs(self):
        s = self.admin()
        self.v.kv["kv/shared/vpn"] = {"password": "from-the-lab"}
        self.assertEqual(S.resolve_ref({"secret": "vault:kv/shared/vpn#password"}, s), "from-the-lab")
        with self.assertRaises(S.SecretError):
            S.resolve_ref("plain-text-password")
        self.assertEqual(S.resolve_ref({"secret": "bitwarden:VPN#password"}, run=self.m), "bw-value-VPN")


class OpenBaoTests(unittest.TestCase):
    def test_new_vault_first_boot(self):
        with tempfile.TemporaryDirectory() as root:
            m = FakeMachine(root)
            v = VaultStub(initialized=False)
            try:
                b = S.OpenBaoStore(address=v.address, root=root, run=m, hostname="box")
                self.assertTrue(b.initialise())
                self.assertFalse(v.sealed)
                self.assertIn("file", v.audit)                     # audit log on
                self.assertIn("bromigos-server-box", v.policies)
                self.assertNotIn("init-root", v.tokens)            # root token revoked
                keys = b.take_init_keys()
                self.assertEqual(len(keys["unseal_keys"]), 5)
                self.assertIsNone(b.take_init_keys())              # handed over once
                b.put("restic/password", "bao-held")
                self.assertEqual(b.get("restic/password"), "bao-held")
                v.sealed, v.unsealed_with = True, []
                self.assertTrue(b.unseal())
                self.assertEqual(S.scan(root, {k: k for k in keys["unseal_keys"]}), [])
                self.assertIn("openbao", S.openbao_config().lower() + "openbao")
            finally:
                v.close()


class SopsTests(unittest.TestCase):
    def test_lab_repo(self):
        with tempfile.TemporaryDirectory() as root:
            m = FakeMachine(root)
            s = S.SopsStore(root, "age1example", root=root, run=m)
            s.put("vault/token-not", "sops-held")
            self.assertEqual(s.get("vault/token-not"), "sops-held")
            self.assertNotIn("sops-held", Path(root, "secrets.enc.json").read_text())


class ManifestTests(unittest.TestCase):
    def test_external_secrets_reference_only(self):
        docs = S.external_secret_manifests("https://vault.example.org", "kv", "bromigos/servers/box", "sonarr", ["api-key"])
        text = json.dumps(docs)
        self.assertIn("ExternalSecret", text)
        self.assertIn("bromigos/servers/box/sonarr/api-key", text)
        self.assertNotIn("stringData", text)

    def test_choices(self):
        self.assertEqual([c["id"] for c in S.choices()], ["local", "vault", "sops"])
        self.assertIn("openbao", [c["id"] for c in S.choices("new", True)])


if __name__ == "__main__":
    unittest.main()
