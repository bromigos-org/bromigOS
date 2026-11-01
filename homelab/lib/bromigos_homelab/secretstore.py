"""Where a server keeps its keys and passwords: one secret store that the installer, provisioning
and the services all use, so nobody manages secrets by hand (docs/lab-secrets.md).

    from bromigos_homelab import secretstore as S
    store = S.open_store()                     # the store chosen at install (/etc/bromigos/secrets.toml)
    store.put("gluetun/password", typed)       # a key a person typed: saved now, never in a file
    store.generate("sonarr/api-key", "apikey") # one nobody needs to type: random, unique, made once
    store.get("sonarr/api-key")                # the value (only the services' plumbing asks)
    store.rotate("restic/password")            # a new value, and the services using it restarted
    store.summary()                            # "12 keys stored on this server, encrypted …"; never values
    store.recovery_text()                      # where they live and how to get them back, in words

Backends (the `backend` key of /etc/bromigos/secrets.toml, which holds no secret values):

  local     systemd credentials on this server: `systemd-creds encrypt` with systemd's default
            key (the TPM2 chip plus the host key in /var/lib/systemd, so a replaced board with the
            disk still recovers from the recovery bundle, and a stolen disk alone doesn't open). Host
            services read them with LoadCredentialEncrypted=; containers through Podman's shell
            secret driver, which decrypts the same way. An age-encrypted recovery bundle holds a
            copy of every key; its key is shown once, as text and a QR code.
  vault     an existing HashiCorp Vault or OpenBao (the same API): KV version 2, signed in with
            AppRole, a one-time wrapped token, or OIDC (your Bromigos account, when the Vault
            offers it). Never a root token; no long-lived token is kept: the AppRole's secret id
            is kept as a local credential and each run signs in afresh.
  openbao   a new OpenBao on this server ("Vault (OpenBao)"), for a new lab: initialised at first
            boot, audit log on, its unseal and recovery keys handed to the welcome tour once, and
            this server's own policy and path.
  sops      the lab repository's secrets.enc.json, encrypted with sops and age, as
            `bromigos lab provision` already keeps it (GitOps labs).

On a k3s lab, apps read Vault through the External Secrets Operator:
external_secret_manifests() writes the references, never the values.

CLI: `bromigos lab secrets status|list|set NAME|generate NAME|rotate NAME|recovery|scan ROOT|
test|policy` (bromigos server secrets is the same command on bromigOS Server). Values are read
from standard input and never printed except by `get` on a terminal.
"""
import argparse
import base64
import json
import os
from pathlib import Path
import re
import secrets as _random
import shlex
import socket
import ssl
import subprocess
import sys
import time
import tomllib
import urllib.error
import urllib.parse
import urllib.request

ROOT = os.environ.get("BROMIGOS_ROOT", "/")
CONFIG = "etc/bromigos/secrets.toml"
CREDSTORE = "etc/credstore.encrypted"
STATE = "var/lib/bromigos/secrets"
PODMAN_DROPIN = "etc/containers/containers.conf.d/50-bromigos-secrets.conf"
NAME = re.compile(r"^[a-z0-9][a-z0-9-]*(/[a-z0-9][a-z0-9_-]*)?$")
KINDS = ("password", "apikey", "hex", "base64", "token")
BACKENDS = ("local", "vault", "openbao", "sops")


class SecretError(Exception):
    """Said to the person as it is: plain words, never a value."""


def at(path, root=None):
    return os.path.join(root or ROOT, path)


def _run(argv, data=None, env=None, timeout=60):
    try:
        r = subprocess.run(argv, input=data, capture_output=True, text=True, env=env, timeout=timeout,
                           **({"stdin": subprocess.DEVNULL} if data is None else {}))
    except (OSError, subprocess.TimeoutExpired) as e:
        return 127, "", str(e)
    return r.returncode, r.stdout, r.stderr


def random_value(kind="password"):
    """Cryptographically random and unique: never a shared or default password."""
    if kind == "apikey":
        return _random.token_hex(16)            # the *arr apps' 32-character keys
    if kind == "hex":
        return _random.token_hex(32)
    if kind == "base64":
        return base64.b64encode(_random.token_bytes(32)).decode()
    return _random.token_urlsafe(32)


def check_name(name):
    if not NAME.match(name or ""):
        raise SecretError(f"{name!r} isn't a key name: lower-case words, like gluetun/password")
    return name


def podman_name(name):
    """The Podman secret a container names (Secret= in its Quadlet)."""
    return "bromigos-" + check_name(name).replace("/", "-")


def cred_name(name):
    """The systemd credential's name (LoadCredentialEncrypted=NAME)."""
    return "bromigos." + check_name(name).replace("/", ".")


class Store:
    """What every backend shares: the index of names (never values), generate, rotate, the
    Podman copies, the summary."""
    backend = "?"

    def __init__(self, root=None, run=None, hostname=None):
        self.root = root or ROOT
        self.run = run or _run
        self.hostname = hostname or socket.gethostname().split(".")[0]

    # -- the index: names, how each was made, the units using it. No values.
    def _index_path(self):
        return Path(at(STATE, self.root)) / "index.json"

    def index(self):
        try:
            return json.loads(self._index_path().read_text())
        except (OSError, ValueError):
            return {}

    def _save_index(self, doc):
        p = self._index_path()
        p.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        tmp = p.with_suffix(".tmp")
        tmp.write_text(json.dumps(doc, indent=1, sort_keys=True) + "\n")
        os.chmod(tmp, 0o600)
        os.replace(tmp, p)

    def _note(self, name, **fields):
        doc = self.index()
        row = doc.setdefault(name, {"created": int(time.time()), "users": []})
        row.update({k: v for k, v in fields.items() if k != "users"})
        for u in fields.get("users") or []:
            if u not in row["users"]:
                row["users"].append(u)
        self._save_index(doc)

    def names(self):
        return sorted(self.index())

    def exists(self, name):
        return name in self.index()

    # -- the backend's own
    def _write(self, name, value):
        raise NotImplementedError

    def _read(self, name):
        raise NotImplementedError

    def _remove(self, name):
        pass

    def where(self):
        raise NotImplementedError

    def recovery_text(self):
        raise NotImplementedError

    # -- the shared verbs
    def put(self, name, value, typed=True, kind=None):
        """Save a value under a name. typed: a person gave it (rotate asks them for a new one)."""
        check_name(name)
        if not isinstance(value, str) or not value:
            raise SecretError(f"{name}: an empty value isn't saved")
        self._write(name, value)
        self._note(name, typed=bool(typed), kind=kind or ("typed" if typed else "password"), backend=self.backend)
        self._podman(name, value)
        self.after_put()
        return name

    def get(self, name):
        check_name(name)
        if not self.exists(name):
            raise SecretError(f"no key named {name} in the store (bromigos lab secrets list)")
        return self._read(name)

    def generate(self, name, kind="password", users=()):
        """Make the value once, when nobody needs to type it. An existing one is kept."""
        if kind not in KINDS:
            raise SecretError(f"kind {kind!r} isn't one of {KINDS}")
        if self.exists(name):
            if users:
                self._note(name, users=list(users))
            return False
        self.put(name, random_value(kind), typed=False, kind=kind)
        if users:
            self._note(name, users=list(users))
        return True

    def use(self, name, unit):
        """Record that a unit reads this key, so rotate restarts it."""
        self._note(check_name(name), users=[unit])

    def rotate(self, name, value=None):
        """A new value; the units that use it restart (a replaced Podman secret doesn't reach a
        running container). A typed key needs the new value from the person."""
        row = self.index().get(check_name(name))
        if not row:
            raise SecretError(f"no key named {name} in the store")
        if row.get("typed") and value is None:
            raise SecretError(f"{name} was typed by a person: give the new one (bromigos lab secrets set {name})")
        self.put(name, value or random_value(row.get("kind") or "password"), typed=row.get("typed", False),
                 kind=row.get("kind"))
        restarted = []
        for unit in row.get("users") or []:
            rc, _, _ = self.run(["systemctl", "try-restart", unit])
            if rc == 0:
                restarted.append(unit)
        return restarted

    def delete(self, name):
        doc = self.index()
        if doc.pop(check_name(name), None) is None:
            return False
        self._remove(name)
        self.run(["podman", "secret", "rm", podman_name(name)])
        self._save_index(doc)
        self.after_put()
        return True

    def _podman(self, name, value):
        """Containers read the key as a file through Podman's shell secret driver (decrypting it
        with systemd-creds), so Podman's copy is never plain text either."""
        if not os.path.exists(at(PODMAN_DROPIN, self.root)):
            return
        self.run(["podman", "secret", "create", "--replace", podman_name(name), "-"], value)

    def after_put(self):
        pass

    def summary(self):
        n = len(self.index())
        return f"{n} key{'s' if n != 1 else ''} stored {self.where()}"

    def status(self):
        return {"backend": self.backend, "where": self.where(), "count": len(self.index()), "summary": self.summary(),
                "names": self.names(), "recovery": self.recovery_text()}


# ---------------------------------------------------------------- local: systemd credentials
class LocalStore(Store):
    backend = "local"

    def path(self, name):
        return Path(at(CREDSTORE, self.root)) / cred_name(name)

    def tpm(self):
        rc, _, _ = self.run(["systemd-creds", "has-tpm2"])
        return rc == 0

    def _write(self, name, value):
        p = self.path(name)
        p.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        # --with-key=auto is systemd's default: the TPM2 chip and the host key together when
        # there's a TPM, the host key alone when there isn't (never TPM-only)
        rc, _, err = self.run(["systemd-creds", "encrypt", "--with-key=auto", "--name=" + cred_name(name), "-", str(p)], value)
        if rc:
            raise SecretError(f"couldn't encrypt {name} on this server (systemd-creds: {err.strip()[:200] or rc})")
        os.chmod(p, 0o600)

    def _read(self, name):
        rc, out, err = self.run(["systemd-creds", "decrypt", "--name=" + cred_name(name), str(self.path(name)), "-"])
        if rc:
            raise SecretError(f"couldn't decrypt {name} on this server (systemd-creds: {err.strip()[:200] or rc})")
        return out

    def _remove(self, name):
        try:
            self.path(name).unlink()
        except FileNotFoundError:
            pass

    def where(self):
        return "on this server, encrypted with its TPM chip and host key" if self.tpm() else \
            "on this server, encrypted with its host key"

    # -- the recovery bundle: every key, encrypted with age to a key shown once
    def _bundle(self):
        return Path(at(STATE, self.root)) / "recovery.age"

    def _recipient(self):
        p = Path(at(STATE, self.root)) / "recovery.pub"
        return p.read_text().strip() if p.exists() else ""

    def recovery_key(self):
        """Make the recovery key (once) and return it to show the person: text and a QR code.
        It's kept only as a credential until acknowledged (ack_recovery), then forgotten."""
        if self._recipient():
            if self.exists("recovery/identity"):
                return self._read("recovery/identity")
            return None                              # shown and acknowledged already
        rc, out, err = self.run(["age-keygen"])
        ident = next((l for l in out.splitlines() if l.startswith("AGE-SECRET-KEY-")), "")
        pub = next((l.split(":", 1)[1].strip() for l in (out + "\n" + err).splitlines() if "public key" in l.lower()), "")
        if rc or not ident or not pub.startswith("age1"):
            raise SecretError("couldn't make the recovery key (age-keygen)")
        p = Path(at(STATE, self.root)) / "recovery.pub"
        p.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        p.write_text(pub + "\n")
        Store.put(self, "recovery/identity", ident, typed=False, kind="token")
        self.after_put()
        return ident

    def ack_recovery(self):
        """The person saved the recovery key: this server forgets it."""
        doc = self.index()
        if "recovery/identity" in doc:
            self._remove("recovery/identity")
            doc.pop("recovery/identity")
            self._save_index(doc)

    def after_put(self):
        pub = self._recipient()
        if not pub:
            return
        values = {n: self._read(n) for n in self.names() if n != "recovery/identity"}
        rc, out, _ = self.run(["age", "--encrypt", "--armor", "-r", pub], json.dumps(values))
        values.clear()
        if rc == 0:
            b = self._bundle()
            b.write_text(out)
            os.chmod(b, 0o600)

    def recovery_bundle(self):
        """The bundle's path (ASCII-armoured age): the UI offers it as a download or a QR code."""
        b = self._bundle()
        return str(b) if b.exists() else None

    def restore(self, bundle_text, identity):
        """Put every key from a recovery bundle back (a reinstalled or repaired server)."""
        ident = Path(at(STATE, self.root)) / ".restore-identity"
        ident.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        fd = os.open(ident, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as f:
            f.write(identity.strip() + "\n")
        try:
            rc, out, _ = self.run(["age", "--decrypt", "-i", str(ident)], bundle_text)
        finally:
            ident.unlink()
        if rc:
            raise SecretError("that recovery key doesn't open this bundle")
        values = json.loads(out)
        for n, v in values.items():
            self.put(n, v, typed=True)
        return sorted(values)

    def recovery_text(self):
        lines = [f"Your keys are kept {self.where()}. They open only on this server."]
        if self._recipient():
            lines.append("A copy of every key is in the recovery bundle (" + str(self._bundle()).replace(self.root.rstrip("/"), "", 1)
                         + "), encrypted to your recovery key. Keep the recovery key in your password manager or "
                         "on paper: with it and the bundle, `bromigos lab secrets restore` puts every key back on a "
                         "new or repaired server.")
        else:
            lines.append("Make a recovery key with `bromigos lab secrets recovery` so you can get them back if this "
                         "server's disk or board is replaced.")
        return " ".join(lines)


def podman_driver_conf():
    """containers.conf drop-in: Podman's shell secret driver, decrypting with systemd-creds."""
    store = "/" + CREDSTORE
    return ("# bromigos lab secrets: Podman's secrets are systemd credentials, encrypted on disk\n"
            "[secrets]\ndriver = \"shell\"\n\n[secrets.opts]\n"
            f"list = \"ls {store} | sed -n 's/^podman[.]//p'\"\n"
            f"lookup = \"systemd-creds decrypt --name=podman {store}/podman.$SECRET_ID -\"\n"
            f"store = \"systemd-creds encrypt --with-key=auto --name=podman - {store}/podman.$SECRET_ID\"\n"
            f"delete = \"rm -f {store}/podman.$SECRET_ID\"\n")


def unit_credential_lines(names):
    """A host service's drop-in lines: LoadCredentialEncrypted= for each key; the service reads
    $CREDENTIALS_DIRECTORY/<name>."""
    return [f"LoadCredentialEncrypted={cred_name(n)}" for n in names]


# ---------------------------------------------------------------- Vault and OpenBao (one API)
class VaultStore(Store):
    """An existing HashiCorp Vault or OpenBao. KV version 2."""
    backend = "vault"

    def __init__(self, address, ca_file=None, mount=None, prefix=None, auth=None, root=None, run=None,
                 hostname=None, opener=None, local=None):
        super().__init__(root, run, hostname)
        if not re.match(r"^https?://", address or ""):
            raise SecretError("a Vault address starts with https:// (or http:// on this machine only)")
        if address.startswith("http://") and not re.match(r"^http://(127\.0\.0\.1|localhost|\[::1\])(:\d+)?/?$", address):
            raise SecretError("use https:// for a Vault on another machine")
        self.address = address.rstrip("/")
        self.ca_file = ca_file
        self.auth = dict(auth or {})
        self.token = None
        self._mount, self._prefix = mount, prefix
        self.opener = opener
        self.local = local or LocalStore(self.root, self.run, self.hostname)

    # -- HTTP
    def request(self, method, path, body=None, token=None, raw=False):
        headers = {"Content-Type": "application/json"}
        tok = token or self.token
        if tok:
            headers["X-Vault-Token"] = tok
        req = urllib.request.Request(self.address + "/v1/" + path.lstrip("/"),
                                     data=json.dumps(body).encode() if body is not None else None,
                                     headers=headers, method=method)
        try:
            if self.opener:
                resp = self.opener(req)
            else:
                ctx = ssl.create_default_context(cafile=self.ca_file) if self.address.startswith("https") else None
                resp = urllib.request.urlopen(req, timeout=15, context=ctx)
            with resp:
                data = resp.read()
                return json.loads(data) if data else {}
        except urllib.error.HTTPError as e:
            code = e.code
            e.close()
            if code == 403:
                raise SecretError("Vault refused this (permission denied): check this server's policy") from None
            if code == 404 and raw:
                return None
            raise SecretError(f"Vault answered HTTP {code}") from None
        except (urllib.error.URLError, OSError):
            raise SecretError(f"can't reach Vault at {self.address}") from None

    # -- signing in
    def login(self):
        """A fresh, short-lived token from the auth method. Never a root token."""
        a = self.auth
        method = a.get("method") or ("approle" if self.local.exists("vault/secret-id") else None)
        if method == "approle":
            role_id = a.get("role_id") or (self.local.get("vault/role-id") if self.local.exists("vault/role-id") else "")
            secret_id = a.get("secret_id") or (self.local.get("vault/secret-id") if self.local.exists("vault/secret-id") else "")
            if not role_id or not secret_id:
                raise SecretError("AppRole needs a role id and a secret id")
            doc = self.request("POST", "auth/approle/login", {"role_id": role_id, "secret_id": secret_id})
            self.token = doc["auth"]["client_token"]
            if a.get("secret_id") and a.get("keep", True):
                # kept as an encrypted credential on this server, never as plain text
                self.local.put("vault/role-id", role_id, typed=True)
                self.local.put("vault/secret-id", secret_id, typed=True)
                self.auth.pop("secret_id", None)
        elif method == "wrapped":
            doc = self.request("POST", "sys/wrapping/unwrap", {}, token=a["wrapping_token"])
            a.pop("wrapping_token", None)              # one use only
            if doc.get("auth"):
                self.token = doc["auth"]["client_token"]
            elif (doc.get("data") or {}).get("secret_id") and a.get("role_id"):
                self.auth = {"method": "approle", "role_id": a["role_id"], "secret_id": doc["data"]["secret_id"]}
                return self.login()
            else:
                raise SecretError("the wrapped token held neither a token nor an AppRole secret id")
        elif method == "token":
            self.token = a["token"]
        elif method == "oidc":
            if not a.get("token"):
                raise SecretError("finish the sign-in in the browser first (oidc_auth_url, then oidc_callback)")
            self.token = a["token"]
        else:
            raise SecretError("choose how this server signs in to Vault: AppRole, a wrapped token, or OIDC")
        self._refuse_root()
        return True

    def _refuse_root(self):
        me = self.request("GET", "auth/token/lookup-self").get("data") or {}
        if "root" in (me.get("policies") or []):
            self.token = None
            raise SecretError("that's a root token: give this server an AppRole or a wrapped token instead")
        return me

    def oidc_auth_url(self, redirect_uri, role="", mount="oidc"):
        doc = self.request("POST", f"auth/{mount}/oidc/auth_url", {"role": role, "redirect_uri": redirect_uri})
        url = (doc.get("data") or {}).get("auth_url")
        if not url:
            raise SecretError("this Vault doesn't offer OIDC sign-in")
        return url

    def oidc_callback(self, state, code, nonce="", mount="oidc"):
        q = urllib.parse.urlencode({"state": state, "code": code, "nonce": nonce})
        doc = self.request("GET", f"auth/{mount}/oidc/callback?{q}")
        self.auth = {"method": "oidc", "token": doc["auth"]["client_token"]}
        self.token = self.auth["token"]
        self._refuse_root()
        return True

    def _ensure(self):
        if not self.token:
            self.login()

    # -- the layout: the lab's own when there is one, else kv/bromigos/servers/<host>
    def layout(self):
        if self._mount and self._prefix:
            return self._mount, self._prefix
        mounts = {}
        try:
            self._ensure()
            mounts = (self.request("GET", "sys/mounts") or {}).get("data") or {}
        except SecretError:
            pass
        if "secret/" in mounts and "kv/" not in mounts and (mounts["secret/"].get("options") or {}).get("version") == "2":
            # the layout bromigos lab provision gives a lab's Vault (secret/data/lab/…)
            self._mount, self._prefix = "secret", f"lab/servers/{self.hostname}"
        else:
            self._mount, self._prefix = "kv", f"bromigos/servers/{self.hostname}"
        return self._mount, self._prefix

    def kv_path(self, name, part="data"):
        mount, prefix = self.layout()
        return f"{mount}/{part}/{prefix}/{check_name(name)}"

    def _write(self, name, value):
        self._ensure()
        self.request("POST", self.kv_path(name), {"data": {"value": value}})

    def _read(self, name):
        self._ensure()
        doc = self.request("GET", self.kv_path(name), raw=True)
        if not doc:
            raise SecretError(f"no key named {name} in Vault")
        return doc["data"]["data"]["value"]

    def _remove(self, name):
        self._ensure()
        self.request("DELETE", self.kv_path(name, "metadata"))

    def _podman(self, name, value):
        # containers still read files: the Podman copy is encrypted locally, Vault holds the original
        Store._podman(self, name, value)

    def where(self):
        return f"in your lab's Vault at {self.address}"

    def recovery_text(self):
        mount, prefix = self.layout()
        return (f"Your keys are kept {self.where()}, under {mount}/{prefix}/. Vault's own backups and "
                "recovery keys cover them; this server only holds its sign-in, encrypted.")

    def policy_name(self, hostname=None):
        return "bromigos-server-" + (hostname or self.hostname)

    def policy_preview(self, hostname=None):
        """The policy this server gets, as Vault's HCL: its own path, nothing else."""
        mount, prefix = self.layout()
        if hostname and hostname != self.hostname:
            prefix = prefix.rsplit("/", 1)[0] + "/" + hostname
        return (f'# {self.policy_name(hostname)}: this server reads and writes its own keys, nothing else\n'
                f'path "{mount}/data/{prefix}/*" {{\n  capabilities = ["create", "read", "update", "delete"]\n}}\n'
                f'path "{mount}/metadata/{prefix}/*" {{\n  capabilities = ["read", "list", "delete"]\n}}\n'
                'path "auth/token/lookup-self" {\n  capabilities = ["read"]\n}\n'
                'path "auth/token/renew-self" {\n  capabilities = ["update"]\n}\n')

    def ensure_server_policy(self, hostname=None):
        """This server's policy and AppRole (needs a token that may write policies, given once at
        setup). Afterwards the server signs in with its own AppRole, kept encrypted here."""
        self._ensure()
        host = hostname or self.hostname
        mount, _ = self.layout()
        mounts = (self.request("GET", "sys/mounts") or {}).get("data") or {}
        if f"{mount}/" not in mounts:
            self.request("POST", f"sys/mounts/{mount}", {"type": "kv", "options": {"version": "2"}})
        self.request("PUT", f"sys/policies/acl/{self.policy_name(host)}", {"policy": self.policy_preview(host)})
        auths = (self.request("GET", "sys/auth") or {}).get("data") or {}
        if "approle/" not in auths:
            self.request("POST", "sys/auth/approle", {"type": "approle"})
        role = self.policy_name(host)
        self.request("POST", f"auth/approle/role/{role}",
                     {"token_policies": [role], "token_ttl": "1h", "token_max_ttl": "4h", "secret_id_num_uses": 0})
        role_id = self.request("GET", f"auth/approle/role/{role}/role-id")["data"]["role_id"]
        secret_id = self.request("POST", f"auth/approle/role/{role}/secret-id", {})["data"]["secret_id"]
        self.local.put("vault/role-id", role_id, typed=True)
        self.local.put("vault/secret-id", secret_id, typed=True)
        self.auth = {"method": "approle"}
        self.token = None
        return {"policy": role, "path": self.kv_path("x").rsplit("/", 1)[0] + "/", "approle": role}

    def test(self):
        """{ok, message}: reachable, unsealed, signed in, and allowed to use this server's path."""
        try:
            health = self.request("GET", "sys/health?standbyok=true&sealedcode=200&uninitcode=200") or {}
            if health.get("sealed"):
                return {"ok": False, "message": f"Vault at {self.address} is sealed: unseal it first."}
            if health.get("initialized") is False:
                return {"ok": False, "message": f"Vault at {self.address} isn't set up yet."}
            self._ensure()
            path = self.kv_path("check")
            caps = self.request("POST", "sys/capabilities-self", {"paths": [path]})
            have = caps.get(path) or caps.get("capabilities") or []
            if not {"create", "update"} & set(have) and "root" not in have:
                return {"ok": False, "message": f"Signed in, but this server may not write {path.rsplit('/', 1)[0]}/."}
            return {"ok": True, "message": f"Connected to Vault at {self.address}; keys go in {path.rsplit('/', 1)[0]}/."}
        except SecretError as e:
            return {"ok": False, "message": str(e)}


class OpenBaoStore(VaultStore):
    """A new OpenBao on this server, for a new lab ("Vault (OpenBao)")."""
    backend = "openbao"
    AUDIT_LOG = "/var/log/openbao/audit.log"
    INIT_DROP = "run/bromigos/openbao-init.json"

    def __init__(self, address="http://127.0.0.1:8200", **kw):
        super().__init__(address, **kw)

    def where(self):
        return "in this server's own Vault (OpenBao)"

    def initialise(self, shares=5, threshold=3):
        """First boot: initialise, unseal, turn the audit log on, make the KV store and this
        server's policy, and revoke the root token. The unseal and recovery keys are handed to
        the welcome tour once (take_init_keys). Three unseal shares are kept as TPM-bound local
        credentials so the server unseals itself after a restart."""
        if self.request("GET", "sys/init").get("initialized"):
            return False
        doc = self.request("PUT", "sys/init", {"secret_shares": shares, "secret_threshold": threshold})
        keys, root = doc["keys_base64"], doc["root_token"]
        drop = Path(at(self.INIT_DROP, self.root))
        drop.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        fd = os.open(drop, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as f:
            json.dump({"unseal_keys": keys, "threshold": threshold}, f)
        for k in keys[:threshold]:
            self.request("PUT", "sys/unseal", {"key": k})
        for i, k in enumerate(keys[:threshold]):
            self.local.put(f"openbao/unseal-{i + 1}", k, typed=False, kind="token")
        self.token = root
        self.request("PUT", "sys/audit/file", {"type": "file", "options": {"file_path": self.AUDIT_LOG}})
        self._mount, self._prefix = "kv", f"bromigos/servers/{self.hostname}"
        self.ensure_server_policy()
        self.request("POST", "auth/token/revoke-self", {}, token=root)
        root = None
        keys = None
        return True

    def take_init_keys(self):
        """The unseal keys, once, for the tour to show (text and QR); then they're gone from here."""
        drop = Path(at(self.INIT_DROP, self.root))
        try:
            doc = json.loads(drop.read_text())
        except (OSError, ValueError):
            return None
        drop.unlink()
        return doc

    def unseal(self):
        """After a restart: unseal with the shares this server keeps (bromigos-openbao-unseal.service)."""
        if not self.request("GET", "sys/seal-status").get("sealed"):
            return False
        for i in range(1, 6):
            n = f"openbao/unseal-{i}"
            if self.local.exists(n):
                self.request("PUT", "sys/unseal", {"key": self.local.get(n)})
        return not self.request("GET", "sys/seal-status").get("sealed")

    def _refuse_root(self):
        return {}

    def login(self):
        self.auth = self.auth or {"method": "approle"}
        r = VaultStore.login(self)
        VaultStore._refuse_root(self)
        return r


def openbao_config():
    """OpenBao's server config: integrated storage under /var/lib/openbao, this machine only."""
    return ('# bromigos lab provision: this server\'s Vault (OpenBao)\n'
            'ui = true\n'
            'storage "raft" {\n  path = "/var/lib/openbao"\n  node_id = "bromigos"\n}\n'
            'listener "tcp" {\n  address = "127.0.0.1:8200"\n  tls_disable = true\n}\n'
            'api_addr = "http://127.0.0.1:8200"\ncluster_addr = "http://127.0.0.1:8201"\n')


# ---------------------------------------------------------------- sops: the lab repository
class SopsStore(Store):
    """The lab repository's secrets.enc.json (sops + age), as bromigos lab provision keeps it."""
    backend = "sops"

    def __init__(self, repo, recipient, root=None, run=None, hostname=None):
        super().__init__(root, run, hostname)
        self.repo = Path(repo)
        if not recipient.startswith("age1"):
            raise SecretError("sops needs your age public key (age1…)")
        self.recipient = recipient

    def _all(self):
        p = self.repo / "secrets.enc.json"
        if not p.exists():
            return {}
        rc, out, _ = self.run(["sops", "--decrypt", str(p)])
        if rc:
            raise SecretError("sops couldn't decrypt the lab repository's secrets (is your age key here?)")
        return json.loads(out)

    def _save(self, values):
        rc, out, _ = self.run(["sops", "--encrypt", "--age", self.recipient, "--input-type", "json",
                               "--output-type", "json", "/dev/stdin"], json.dumps(values, sort_keys=True))
        if rc:
            raise SecretError("sops couldn't encrypt the lab repository's secrets")
        p = self.repo / "secrets.enc.json"
        p.write_text(out)
        os.chmod(p, 0o600)

    def _write(self, name, value):
        values = self._all()
        values[name] = value
        self._save(values)

    def _read(self, name):
        return self._all()[name]

    def _remove(self, name):
        values = self._all()
        values.pop(name, None)
        self._save(values)

    def where(self):
        return f"in your lab repository ({self.repo.name}/secrets.enc.json), encrypted with sops and age"

    def recovery_text(self):
        return (f"Your keys are kept {self.where()}. Your age key opens them: keep it in your password "
                "manager. Git holds only the encrypted file.")


# ---------------------------------------------------------------- opening the chosen store
def read_config(root=None):
    try:
        with open(at(CONFIG, root), "rb") as f:
            return tomllib.load(f)
    except (OSError, tomllib.TOMLDecodeError):
        return {}


def write_config(doc, root=None):
    """The choice (no values): backend, and the Vault address and auth method, or the repo."""
    p = Path(at(CONFIG, root))
    p.parent.mkdir(parents=True, exist_ok=True)
    lines = ["# Where this server keeps its keys (bromigos lab secrets). No secret values here.",
             f"backend = {json.dumps(doc['backend'])}"]
    for section in ("vault", "sops"):
        if doc.get(section):
            lines.append(f"\n[{section}]")
            for k, v in doc[section].items():
                if k in ("secret_id", "token", "wrapping_token", "password"):
                    raise SecretError(f"{k} belongs in the store, not in {CONFIG}")
                lines.append(f"{k} = {json.dumps(v)}")
    p.write_text("\n".join(lines) + "\n")
    os.chmod(p, 0o644)


def open_store(config=None, root=None, run=None, opener=None, hostname=None):
    c = config if config is not None else read_config(root)
    backend = c.get("backend", "local")
    if backend == "local":
        return LocalStore(root, run, hostname)
    if backend in ("vault", "openbao"):
        v = dict(c.get("vault") or {})
        v.setdefault("address", os.environ.get("BAO_ADDR") or os.environ.get("VAULT_ADDR") or "http://127.0.0.1:8200")
        cls = OpenBaoStore if backend == "openbao" else VaultStore
        kw = dict(ca_file=v.get("ca_file"), mount=v.get("mount"), prefix=v.get("prefix"),
                  auth={"method": v.get("auth", "approle"), **({"role_id": v["role_id"]} if v.get("role_id") else {})},
                  root=root, run=run, opener=opener, hostname=hostname)
        return cls(v["address"], **kw) if backend == "vault" else cls(address=v["address"], **kw)
    if backend == "sops":
        s = c.get("sops") or {}
        return SopsStore(s.get("repo", ""), s.get("recipient", ""), root, run, hostname)
    raise SecretError(f"backend {backend!r} isn't one of {BACKENDS}")


def choices(lab="none", vault_selected=False):
    """The installer's "Where should this server keep its keys and passwords?" answers."""
    out = [{"id": "local", "title": "On this server", "default": True,
            "line": "Encrypted with this server's TPM chip and host key. You get a recovery key to keep."}]
    out.append({"id": "vault", "title": "In my lab's Vault",
                "line": "An existing Vault or OpenBao. This server gets its own policy and path."})
    if lab == "new" and vault_selected:
        out.append({"id": "openbao", "title": "In a new Vault on this server",
                    "line": "Vault (OpenBao), compatible with HashiCorp Vault. Its keys are shown once at the end."})
    out.append({"id": "sops", "title": "In my lab repository",
                "line": "Encrypted with sops and your age key, for labs kept in Git."})
    return out


# ---------------------------------------------------------------- answer files: references only
REF = re.compile(r"^(vault|local|sops|bitwarden|env):(.+)$")


def is_ref(value):
    return isinstance(value, dict) and set(value) == {"secret"} and bool(REF.match(str(value["secret"])))


def resolve_ref(value, store=None, run=None, opener=None):
    """{secret = "vault:kv/path#field" | "local:NAME" | "sops:NAME" | "bitwarden:ITEM#field"} → value.
    A plain string in an answer file is refused: answer files never carry secrets."""
    if not is_ref(value):
        raise SecretError("an answer file names secrets by reference, like {secret = \"vault:kv/…#value\"}, never inline")
    kind, rest = REF.match(value["secret"]).groups()
    run = run or _run
    if kind == "local":
        return (store if isinstance(store, LocalStore) else LocalStore(run=run)).get(rest)
    if kind == "sops":
        if not isinstance(store, SopsStore):
            raise SecretError("a sops: reference needs the lab repository's store")
        return store.get(rest)
    if kind == "bitwarden":
        item, _, field = rest.partition("#")
        return bitwarden_get(item, field or "password", run=run)
    if kind == "env":
        v = os.environ.get(rest)
        if not v:
            raise SecretError(f"${rest} isn't set")
        return v
    path, _, field = rest.partition("#")
    if not isinstance(store, VaultStore):
        raise SecretError("a vault: reference needs this server's Vault connection")
    store._ensure()
    mount, _, sub = path.partition("/")
    doc = store.request("GET", f"{mount}/data/{sub}", raw=True)
    if not doc:
        raise SecretError(f"nothing at {path} in Vault")
    return doc["data"]["data"][field or "value"]


# ---------------------------------------------------------------- password managers
def bitwarden_get(item, field="password", run=None, session=None):
    """One value from Bitwarden (or Vaultwarden) through bitwarden-cli; its session comes from
    $BW_SESSION (`bw unlock`). 1Password and Infisical would be further readers here."""
    run = run or _run
    env = dict(os.environ)
    if session:
        env["BW_SESSION"] = session
    if field in ("password", "username", "totp", "notes", "uri"):
        rc, out, _ = run(["bw", "get", field, item], env=env)
    else:
        rc, out, _ = run(["bw", "get", "item", item], env=env)
        if rc == 0:
            fields = {f.get("name"): f.get("value") for f in json.loads(out).get("fields") or []}
            out, rc = fields.get(field) or "", 0 if fields.get(field) else 1
    if rc or not out.strip():
        raise SecretError(f"Bitwarden has no {field} for {item!r} (is it unlocked? bw unlock)")
    return out.strip()


def import_bitwarden(store, mapping, run=None, session=None):
    """{store name: "item" or "item#field"} → filled from Bitwarden. Returns the names filled."""
    done = []
    for name, ref in mapping.items():
        item, _, field = ref.partition("#")
        store.put(name, bitwarden_get(item, field or "password", run=run, session=session), typed=True)
        done.append(name)
    return done


# ---------------------------------------------------------------- k3s: External Secrets
def external_secret_manifests(address, mount, prefix, app, keys, namespace="default", role_id_secret="bromigos-vault-approle"):
    """A ClusterSecretStore for the lab's Vault (OpenBao works the same) and an ExternalSecret
    for one app: Kubernetes reads the keys from Vault; Git holds only these references."""
    store = {"apiVersion": "external-secrets.io/v1", "kind": "ClusterSecretStore", "metadata": {"name": "bromigos-vault"},
             "spec": {"provider": {"vault": {"server": address, "path": mount, "version": "v2",
                                             "auth": {"appRole": {"path": "approle",
                                                                  "roleRef": {"name": role_id_secret, "key": "role-id", "namespace": "external-secrets"},
                                                                  "secretRef": {"name": role_id_secret, "key": "secret-id", "namespace": "external-secrets"}}}}}}}
    es = {"apiVersion": "external-secrets.io/v1", "kind": "ExternalSecret", "metadata": {"name": app, "namespace": namespace},
          "spec": {"refreshInterval": "1h", "secretStoreRef": {"kind": "ClusterSecretStore", "name": "bromigos-vault"},
                   "target": {"name": app, "creationPolicy": "Owner"},
                   "data": [{"secretKey": k, "remoteRef": {"key": f"{prefix}/{app}/{k}", "property": "value"}} for k in keys]}}
    return [store, es]


# ---------------------------------------------------------------- the scanner
def scan(root, values, extra_files=()):
    """Files under root (and extra_files, such as the answer file) that hold any of the values in
    plain text: [(path, name)]. The encrypted credential store is skipped (it's ciphertext)."""
    hits = []
    vals = {n: v for n, v in values.items() if v and len(v) >= 6}
    skip = os.path.join(root, CREDSTORE)
    files = []
    for dirpath, _, names in os.walk(root):
        if dirpath.startswith(skip):
            continue
        files += [os.path.join(dirpath, n) for n in names]
    for p in list(files) + list(extra_files):
        try:
            with open(p, "rb") as f:
                text = f.read(4 << 20).decode("utf-8", "replace")
        except OSError:
            continue
        for n, v in vals.items():
            if v in text:
                hits.append((p, n))
    return hits


# ---------------------------------------------------------------- CLI
def _read_value(prompt):
    if sys.stdin.isatty():
        import getpass
        return getpass.getpass(prompt)
    return sys.stdin.read().rstrip("\n")


def main(argv=None):
    p = argparse.ArgumentParser(prog="bromigos lab secrets", description="Where this server keeps its keys and passwords")
    sub = p.add_subparsers(dest="verb")
    for v in ("status", "list", "recovery", "test", "policy", "unseal"):
        s = sub.add_parser(v)
        s.add_argument("--json", action="store_true")
        if v == "recovery":
            s.add_argument("--saved", action="store_true", help="you saved the recovery key: forget it here")
    s = sub.add_parser("set", help="save a key you type (read from standard input)")
    s.add_argument("name")
    s = sub.add_parser("generate", help="make a random key, once")
    s.add_argument("name")
    s.add_argument("--kind", choices=KINDS, default="password")
    s = sub.add_parser("rotate", help="a new value, and restart what uses it")
    s.add_argument("name")
    s = sub.add_parser("get", help="print a value (on a terminal only)")
    s.add_argument("name")
    s = sub.add_parser("restore", help="put keys back from a recovery bundle")
    s.add_argument("bundle")
    s = sub.add_parser("scan", help="look for plain-text secrets under a folder")
    s.add_argument("root")
    s.add_argument("--also", nargs="*", default=[])
    s = sub.add_parser("import-bitwarden", help="fill keys from Bitwarden: NAME=ITEM[#FIELD] …")
    s.add_argument("pairs", nargs="+")
    a = p.parse_args(argv)
    try:
        store = open_store()
        verb = a.verb or "status"
        if verb in ("status", "list"):
            d = store.status()
            if getattr(a, "json", False):
                print(json.dumps(d, indent=1))
            else:
                print(d["summary"])
                if verb == "list":
                    for n in d["names"]:
                        print("  " + n)
            return 0
        if verb == "unseal":
            if not isinstance(store, OpenBaoStore):
                raise SecretError("unseal is for this server's own Vault (OpenBao)")
            print("Unsealed." if store.unseal() else "Already unsealed.")
            return 0
        if verb == "recovery" and a.saved:
            if isinstance(store, LocalStore):
                store.ack_recovery()
            print("Recovery key forgotten here. Keep your copy safe.")
            return 0
        if verb == "recovery":
            out = {"text": store.recovery_text()}
            if isinstance(store, LocalStore):
                key = store.recovery_key()
                out.update(key=key, bundle=store.recovery_bundle())
            if a.json:
                print(json.dumps(out, indent=1))
            else:
                print(out["text"])
                if out.get("key"):
                    print("\nYour recovery key (shown until you run `bromigos lab secrets recovery --saved`):\n  " + out["key"])
            return 0
        if verb == "test":
            r = store.test() if hasattr(store, "test") else {"ok": True, "message": store.summary()}
            print(json.dumps(r) if a.json else r["message"])
            return 0 if r["ok"] else 1
        if verb == "policy":
            if not isinstance(store, VaultStore):
                raise SecretError("policies are for a Vault store")
            print(store.policy_preview())
            return 0
        if verb == "set":
            store.put(a.name, _read_value(f"{a.name}: "), typed=True)
            print(f"Saved {a.name} {store.where()}.")
            return 0
        if verb == "generate":
            made = store.generate(a.name, a.kind)
            print(f"{'Made' if made else 'Kept'} {a.name} {store.where()}.")
            return 0
        if verb == "rotate":
            row = store.index().get(a.name) or {}
            value = _read_value(f"New {a.name}: ") if row.get("typed") else None
            restarted = store.rotate(a.name, value)
            print(f"Rotated {a.name}." + (f" Restarted {', '.join(restarted)}." if restarted else ""))
            return 0
        if verb == "get":
            if not sys.stdout.isatty():
                raise SecretError("get prints only to a terminal")
            print(store.get(a.name))
            return 0
        if verb == "restore":
            if not isinstance(store, LocalStore):
                raise SecretError("restore is for keys kept on this server")
            names = store.restore(Path(a.bundle).read_text(), _read_value("Recovery key: "))
            print(f"Restored {len(names)} keys.")
            return 0
        if verb == "scan":
            values = {n: store.get(n) for n in store.names()}
            hits = scan(a.root, values, a.also)
            values.clear()
            for path, name in hits:
                print(f"{path}: holds {name} in plain text")
            return 1 if hits else 0
        if verb == "import-bitwarden":
            mapping = dict(x.split("=", 1) for x in a.pairs)
            print(f"Filled {len(import_bitwarden(store, mapping))} keys from Bitwarden.")
            return 0
    except SecretError as e:
        print("bromigos lab secrets: " + str(e), file=sys.stderr)
        return 1
    return 2


if __name__ == "__main__":
    sys.exit(main())
