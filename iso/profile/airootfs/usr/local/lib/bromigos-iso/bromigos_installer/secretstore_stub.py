"""A stand-in for bromigos_homelab.secretstore (the lab provisioning engine's: vault, openbao and
local backends), following its interface, for the installer until the module lands. It never
contacts anything: test() says the connection is checked at the first start, put() and
generate() only record the path, and stage() leaves the values root-only in the new system for
the first start to put in the real store (bromigos-server-secrets.service)."""
import json
import os
import secrets as _secrets

BACKENDS = [
    {"id": "vault", "title": "Connect my lab's Vault (OpenBao/HashiCorp)",
     "words": "Your lab's own Vault keeps them, under this server's own path. Recommended when the server joins a lab."},
    {"id": "openbao", "title": "Create a new Vault (OpenBao)",
     "words": "For a new lab: this server runs OpenBao, which is compatible with HashiCorp Vault. At the first start "
              "you see its unseal and recovery keys once."},
    {"id": "local", "title": "Keep them on this server, encrypted (TPM-bound, with a recovery bundle)",
     "words": "systemd's encrypted credentials, sealed with the security chip (TPM2) and the host key, and a recovery "
              "bundle (age) to download or print as a QR code."},
    {"id": "sops", "title": "My lab uses sops + age",
     "words": "For power users: the secrets live sops-encrypted in your lab's repository; this server gets its own age key."},
]
AUTH = [
    {"id": "oidc", "title": "Sign in with your Bromigos account", "words": "When your lab's Vault offers it (OIDC)."},
    {"id": "approle", "title": "A role ID and secret ID", "words": "AppRole: your lab's admin makes them for this server."},
    {"id": "wrapped", "title": "A one-time wrapped token", "words": "Used once to fetch this server's own login, then gone."},
]


def backends():
    return BACKENDS


def kv_path(cfg, host):
    if cfg.get("kind") == "sops":
        return f"secrets/servers/{host}.sops.yaml"
    if cfg.get("kind") == "local":
        return f"creds:/etc/credstore.encrypted/bromigos-{host}"
    return f"kv/data/servers/{host}"


def where(cfg):
    """Where the keys live, and how to get them back, in plain words (Done, the Server tour)."""
    kind = cfg.get("kind")
    if kind == "vault":
        return ("In your lab's Vault, under this server's own path.", "Your lab's Vault keeps them; its own backups recover them.")
    if kind == "openbao":
        return ("In the new Vault (OpenBao) on this server.", "With the unseal and recovery keys the welcome tour shows once.")
    if kind == "sops":
        return ("In your lab's repository, sops-encrypted to this server's age key.", "With your lab's own age keys.")
    return ("On this server, encrypted and sealed to its security chip.",
            "With the recovery bundle (age) the welcome tour offers to download or print as a QR code.")


def bitwarden(item):
    """A secret from Bitwarden (or Vaultwarden) with bitwarden-cli: (value or None, words)."""
    import shutil
    import subprocess
    if not shutil.which("bw"):
        return None, "Bitwarden's command (bitwarden-cli) isn't here: import from Bitwarden in the welcome tour."
    r = subprocess.run(["bw", "get", "password", item], capture_output=True, text=True, timeout=30)
    if r.returncode != 0:
        return None, "Bitwarden didn't give it: unlock it first (bw unlock), then try again."
    return r.stdout.strip(), "From Bitwarden."


def policy_preview(cfg, host):
    return (f'path "kv/data/servers/{host}/*" {{ capabilities = ["create", "read", "update", "delete", "list"] }}\n'
            f'path "kv/metadata/servers/{host}/*" {{ capabilities = ["list", "read"] }}')


def test(cfg, host=""):
    """(ok True/False/None, words): None, it can't be tried from here."""
    return None, "The installer can't reach the Vault yet: the connection is tested at the first start, before anything is stored."


def put(cfg, path, value):
    return path


def generate(cfg, path, kind="password"):
    return path


def summary(cfg, paths):
    where_ = {"vault": "your lab's Vault", "openbao": "this server's new Vault (OpenBao)", "local": "this server, encrypted",
              "sops": "your lab's sops repository"}
    return f"{len(paths)} key{'s' if len(paths) != 1 else ''} stored in {where_.get(cfg.get('kind'), 'the store')}"


def stage(root, cfg, values, generated):
    """The values (typed) and the names to generate, root-only in the new system, for the first start."""
    d = os.path.join(root, "var/lib/bromigos/secrets")
    os.makedirs(d, mode=0o700, exist_ok=True)
    path = os.path.join(d, "staged.json")
    with open(path, "w", opener=lambda p, f: os.open(p, f, 0o600)) as f:
        json.dump({"store": {k: v for k, v in cfg.items() if k not in ("secret_id", "token")},
                   "login": {k: cfg[k] for k in ("secret_id", "token") if cfg.get(k)},
                   "values": values, "generate": generated, "nonce": _secrets.token_hex(8)}, f)
    return path
