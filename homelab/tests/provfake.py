"""Stand-ins for the local provisioning tests: a fake machine's commands (pacman, podman,
systemctl, systemd-creds, age, …) over a temporary root, and a Vault/OpenBao HTTP stub served
on 127.0.0.1 that answers the API calls secretstore makes, as Vault does."""
import base64
import http.server
import json
import os
from pathlib import Path
import re
import secrets
import threading
import urllib.parse

KEY = 0x5A


def _enc(text):
    return "FAKECRED:" + base64.b64encode(bytes(b ^ KEY for b in text.encode())).decode()


def _dec(text):
    return bytes(b ^ KEY for b in base64.b64decode(text.split(":", 1)[1])).decode()


class FakeMachine:
    """run(argv, data=None, env=None) → (rc, stdout, stderr), like localprovision.run."""

    def __init__(self, root, installed=(), images=(), tpm=True, fail=()):
        self.root = Path(root)
        self.installed = set(installed)
        self.images = set(images)
        self.tpm = tpm
        self.fail = set(fail)                  # command words that fail, such as "pacman -S jellyfin"
        self.calls = []
        self.podman_secrets = {}
        self.users = set()
        self.unseal_ok = True

    def __call__(self, argv, data=None, env=None, **kw):
        argv = [str(a) for a in argv]
        self.calls.append(argv)
        line = " ".join(argv)
        for f in self.fail:
            if line.startswith(f):
                return 1, "", "failed on purpose"
        cmd = argv[0]
        if cmd == "pacman":
            if argv[1] == "-Q":
                return (0, argv[2] + " 1-1\n", "") if argv[2] in self.installed else (1, "", "not found")
            if argv[1] == "-S":
                self.installed |= {a for a in argv[2:] if not a.startswith("-")}
                return 0, "", ""
            if argv[1] == "-Rdd":
                self.installed -= set(argv[3:])
                return 0, "", ""
        if cmd == "podman":
            if argv[1:3] == ["image", "exists"]:
                return (0, "", "") if argv[3] in self.images else (1, "", "")
            if argv[1] == "pull":
                self.images.add(argv[2])
                return 0, "", ""
            if argv[1:3] == ["secret", "create"]:
                # the shell driver keeps it encrypted: record only that it exists
                self.podman_secrets[argv[-2]] = len(data or "")
                return 0, "", ""
            if argv[1:3] == ["secret", "exists"]:
                return (0, "", "") if argv[3] in self.podman_secrets else (1, "", "")
            if argv[1:3] == ["secret", "rm"]:
                self.podman_secrets.pop(argv[3], None)
                return 0, "", ""
            if argv[1:3] == ["healthcheck", "run"]:
                return 0, "", ""
        if cmd == "systemd-creds":
            if argv[1] == "has-tpm2":
                return (0 if self.tpm else 1), "", ""
            if argv[1] == "encrypt":
                path = Path(argv[-1])
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(_enc(data))
                return 0, "", ""
            if argv[1] == "decrypt":
                return 0, _dec(Path(argv[-2]).read_text()), ""
        if cmd == "age-keygen":
            ident = "AGE-SECRET-KEY-1" + secrets.token_hex(24).upper()
            return 0, "# created: now\n# public key: age1fakerecipient\n" + ident + "\n", "Public key: age1fakerecipient\n"
        if cmd == "age":
            if "--encrypt" in argv:
                return 0, "-----BEGIN AGE ENCRYPTED FILE-----\n" + _enc(data) + "\n-----END AGE ENCRYPTED FILE-----\n", ""
            if "--decrypt" in argv:
                body = [l for l in data.splitlines() if l.startswith("FAKECRED:")][0]
                return 0, _dec(body), ""
        if cmd == "id":
            return (0, "", "") if argv[1] in self.users else (1, "", "")
        if cmd == "useradd":
            self.users.add(argv[-1])
            return 0, "", ""
        if cmd == "curl":
            out = Path(argv[argv.index("-o") + 1])
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text("#!/bin/sh\n")
            return 0, "", ""
        if cmd == "sops":
            if "--encrypt" in argv:
                return 0, json.dumps({"sops": _enc(data)}), ""
            if "--decrypt" in argv:
                return 0, _dec(json.loads(Path(argv[-1]).read_text())["sops"]), ""
        if cmd == "bw":
            return 0, "bw-value-" + argv[-1] + "\n", ""
        return 0, "", ""

    def ran(self, prefix):
        return [c for c in self.calls if " ".join(c).startswith(prefix)]


class VaultStub:
    """Vault's HTTP API, the parts secretstore uses, in memory: KV v2, AppRole, wrapping, policies,
    mounts, audit, init/unseal/seal-status, token lookup and revoke."""

    def __init__(self, initialized=True, kv="kv"):
        self.tokens = {"root-token": ["root"], "admin-token": ["admin"]}
        self.kv = {}
        self.mounts = {f"{kv}/": {"type": "kv", "options": {"version": "2"}}, "sys/": {"type": "system"}} if kv else {"sys/": {"type": "system"}}
        self.auths = {"token/": {"type": "token"}}
        self.policies = {}
        self.roles = {}
        self.wrapped = {}
        self.audit = {}
        self.initialized = initialized
        self.sealed = not initialized
        self.keys = []
        self.unsealed_with = []
        self.log = []
        self.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), self._handler())
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    @property
    def address(self):
        return f"http://127.0.0.1:{self.server.server_address[1]}"

    def close(self):
        self.server.shutdown()
        self.server.server_close()

    def wrap(self, payload):
        t = "wrap-" + secrets.token_hex(6)
        self.wrapped[t] = payload
        return t

    def _handler(self):
        stub = self

        class H(http.server.BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def _send(self, code, doc=None):
                body = json.dumps(doc).encode() if doc is not None else b""
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def _do(self, method):
                n = int(self.headers.get("Content-Length") or 0)
                body = json.loads(self.rfile.read(n) or b"{}") if n else {}
                url = urllib.parse.urlparse(self.path)
                path = url.path[len("/v1/"):]
                token = self.headers.get("X-Vault-Token")
                stub.log.append((method, path, token))
                code, doc = stub.answer(method, path, body, token, urllib.parse.parse_qs(url.query))
                self._send(code, doc)

            def do_GET(self):
                self._do("GET")

            def do_POST(self):
                self._do("POST")

            def do_PUT(self):
                self._do("PUT")

            def do_DELETE(self):
                self._do("DELETE")
        return H

    def answer(self, method, path, body, token, query):
        open_paths = ("sys/health", "sys/init", "sys/unseal", "sys/seal-status", "auth/approle/login", "sys/wrapping/unwrap")
        if path in open_paths or path.startswith("auth/oidc/"):
            return self.open_api(method, path, body, token, query)
        if self.sealed:
            return 503, {"errors": ["Vault is sealed"]}
        pol = self.tokens.get(token)
        if pol is None:
            return 403, {"errors": ["permission denied"]}
        admin = "root" in pol or "admin" in pol
        if path == "auth/token/lookup-self":
            return 200, {"data": {"policies": pol}}
        if path == "auth/token/revoke-self":
            self.tokens.pop(token, None)
            return 204, None
        if path == "sys/capabilities-self":
            p = body["paths"][0]
            return 200, {p: self.caps(pol, p), "capabilities": self.caps(pol, p)}
        if path.startswith("sys/") or path.startswith("auth/approle/role"):
            if not admin:
                return 403, {"errors": ["permission denied"]}
            return self.admin_api(method, path, body)
        mount = path.split("/", 1)[0] + "/"
        if mount not in self.mounts:
            return 404, {"errors": []}
        if not ({"create", "read", "update"} & set(self.caps(pol, path)) or admin):
            return 403, {"errors": ["permission denied"]}
        m = re.match(r"^([^/]+)/(data|metadata)/(.+)$", path)
        key = m.group(1) + "/" + m.group(3)
        if method in ("POST", "PUT") and m.group(2) == "data":
            self.kv[key] = body["data"]
            return 200, {"data": {"version": 1}}
        if method == "GET" and m.group(2) == "data":
            if key not in self.kv:
                return 404, {"errors": []}
            return 200, {"data": {"data": self.kv[key], "metadata": {}}}
        if method == "DELETE":
            self.kv.pop(key, None)
            return 204, None
        return 405, None

    def caps(self, pol, path):
        if "root" in pol or "admin" in pol:
            return ["root"]
        out = []
        for name in pol:
            for pat, caps in re.findall(r'path "([^"]+)" \{\n  capabilities = \[([^\]]*)\]', self.policies.get(name, "")):
                rx = "^" + re.escape(pat).replace(r"\*", ".*") + "$"
                if re.match(rx, path):
                    out += [c.strip(' "') for c in caps.split(",")]
        return out

    def open_api(self, method, path, body, token, query):
        if path == "sys/health":
            return 200, {"initialized": self.initialized, "sealed": self.sealed, "standby": False}
        if path == "sys/seal-status":
            return 200, {"sealed": self.sealed, "initialized": self.initialized}
        if path == "sys/init":
            if method == "GET":
                return 200, {"initialized": self.initialized}
            self.initialized = True
            self.keys = [base64.b64encode(os.urandom(16)).decode() for _ in range(body["secret_shares"])]
            self.threshold = body["secret_threshold"]
            self.tokens["init-root"] = ["root"]
            return 200, {"keys_base64": self.keys, "root_token": "init-root"}
        if path == "sys/unseal":
            if body["key"] in self.keys:
                self.unsealed_with.append(body["key"])
                if len(set(self.unsealed_with)) >= self.threshold:
                    self.sealed = False
            return 200, {"sealed": self.sealed}
        if path == "auth/approle/login":
            for name, role in self.roles.items():
                if role["role_id"] == body.get("role_id") and body.get("secret_id") in role["secret_ids"]:
                    t = "s." + secrets.token_hex(8)
                    self.tokens[t] = list(role["token_policies"])
                    return 200, {"auth": {"client_token": t, "policies": role["token_policies"]}}
            return 400, {"errors": ["invalid role or secret id"]}
        if path == "sys/wrapping/unwrap":
            payload = self.wrapped.pop(token, None)
            if payload is None:
                return 400, {"errors": ["wrapping token is not valid or does not exist"]}
            return 200, payload
        if path.endswith("/oidc/auth_url"):
            return 200, {"data": {"auth_url": "https://id.example.org/authorize?state=abc"}}
        if path.endswith("/oidc/callback"):
            t = "s.oidc" + secrets.token_hex(4)
            self.tokens[t] = ["oidc-user"]
            return 200, {"auth": {"client_token": t}}
        return 404, None

    def admin_api(self, method, path, body):
        if path == "sys/mounts":
            return 200, {"data": self.mounts}
        if path.startswith("sys/mounts/"):
            self.mounts[path.split("/", 2)[2] + "/"] = {"type": body["type"], "options": body.get("options")}
            return 204, None
        if path == "sys/auth":
            return 200, {"data": self.auths}
        if path.startswith("sys/auth/"):
            self.auths[path.split("/", 2)[2] + "/"] = {"type": body["type"]}
            return 204, None
        if path.startswith("sys/policies/acl/"):
            self.policies[path.rsplit("/", 1)[1]] = body["policy"]
            return 204, None
        if path.startswith("sys/audit/"):
            self.audit[path.rsplit("/", 1)[1]] = body
            return 204, None
        m = re.match(r"^auth/approle/role/([^/]+)(/role-id|/secret-id)?$", path)
        if m:
            role = self.roles.setdefault(m.group(1), {"role_id": "role-" + secrets.token_hex(4), "secret_ids": []})
            if not m.group(2):
                role.update(token_policies=body["token_policies"])
                return 204, None
            if m.group(2) == "/role-id":
                return 200, {"data": {"role_id": role["role_id"]}}
            sid = "sid-" + secrets.token_hex(8)
            role["secret_ids"].append(sid)
            return 200, {"data": {"secret_id": sid}}
        return 404, None
