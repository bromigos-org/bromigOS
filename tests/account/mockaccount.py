"""A stand-in for the Bromigos account service on 127.0.0.1, for the tests: the OpenID
Connect issuer (discovery, the device flow, a token endpoint that rotates refresh tokens,
userinfo and revocation) under /auth, and the account site's API at the root.

SSH sign-in approvals are checked for real: the signature goes to `ssh-keygen -Y verify`
against an allowed-signers file made from the account's keys."""
import json
import os
import secrets
import subprocess
import tempfile
import threading
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

USER = {"sub": "u-1", "preferred_username": "tester", "email": "tester@example.org", "name": "Test User"}


class Account:
    """The service's state. Tests read and change it directly."""

    def __init__(self):
        self.lock = threading.Lock()
        self.devices = {}             # device_code -> {"user_code", "approved", "polls", "scope", "client_id"}
        self.nonces = {}              # user_code -> nonce
        self.access = {}              # access token -> expiry (time.time())
        self.refresh = None           # the one current refresh token
        self.used_refresh = []        # refresh tokens traded in, in order
        self.reused = []              # an old refresh token offered again
        self.revoked = []
        self.keys = []                # the account's SSH keys: [{"public_key", "title", ...}]
        self.extra_keys = []          # rows ssh-keys returns as they are (bad ones, for the checks)
        self.pats = set()
        self.auto_approve_after = None   # approve a device code after this many polls (the browser)
        self.access_ttl = 3600
        self.requests = []            # (method, path)
        self.signed = []              # the bytes each approval verified


class Handler(BaseHTTPRequestHandler):
    account = None
    base = None

    def log_message(self, *a):
        pass

    def _send(self, code, doc):
        raw = json.dumps(doc).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def _body(self):
        raw = self.rfile.read(int(self.headers.get("Content-Length") or 0)).decode()
        if self.headers.get("Content-Type", "").startswith("application/json"):
            return json.loads(raw or "{}")
        return dict(urllib.parse.parse_qsl(raw))

    def _bearer(self):
        auth = self.headers.get("Authorization", "")
        tok = auth[7:] if auth.startswith("Bearer ") else ""
        a = self.account
        if tok in a.pats:
            return True
        exp = a.access.get(tok)
        return exp is not None and exp > time.time()

    def do_GET(self):                                          # noqa: N802
        a = self.account
        path = urllib.parse.urlparse(self.path).path
        a.requests.append(("GET", path))
        if path == "/auth/.well-known/openid-configuration":
            iss = self.base + "/auth"
            return self._send(200, {"issuer": iss, "device_authorization_endpoint": iss + "/device/code",
                                    "token_endpoint": iss + "/token", "userinfo_endpoint": iss + "/me",
                                    "revocation_endpoint": iss + "/revoke"})
        if path == "/auth/me":
            return self._send(200, USER) if self._bearer() else self._send(401, {"error": "invalid_token"})
        if path == "/api/me/ssh-keys":
            if not self._bearer():
                return self._send(401, {"error": "invalid_token"})
            rows = [dict({"created_at": "2026-10-01T00:00:00Z", "last_used_at": None}, **k) for k in a.keys]
            return self._send(200, rows + a.extra_keys)
        self._send(404, {"error": "not_found"})

    def do_POST(self):                                         # noqa: N802
        a = self.account
        path = urllib.parse.urlparse(self.path).path
        a.requests.append(("POST", path))
        body = self._body()
        with a.lock:
            if path == "/auth/device/code":
                code = secrets.token_hex(8)
                user = "WDJB-" + secrets.token_hex(2).upper()
                a.devices[code] = {"user_code": user, "approved": False, "polls": 0, "scope": body.get("scope"),
                                   "client_id": body.get("client_id")}
                return self._send(200, {"device_code": code, "user_code": user,
                                        "verification_uri": self.base + "/device",
                                        "verification_uri_complete": self.base + "/device?user_code=" + user,
                                        "expires_in": 600, "interval": 0.02})
            if path == "/auth/token":
                if body.get("client_id") != "bromigos-cli":
                    return self._send(401, {"error": "invalid_client"})
                if body.get("grant_type") == "urn:ietf:params:oauth:grant-type:device_code":
                    d = a.devices.get(body.get("device_code"))
                    if not d:
                        return self._send(400, {"error": "expired_token"})
                    d["polls"] += 1
                    if a.auto_approve_after is not None and d["polls"] >= a.auto_approve_after:
                        d["approved"] = True
                    if not d["approved"]:
                        return self._send(400, {"error": "authorization_pending"})
                    del a.devices[body["device_code"]]
                    return self._send(200, self._tokens(d["scope"]))
                if body.get("grant_type") == "refresh_token":
                    r = body.get("refresh_token")
                    if r != a.refresh:
                        if r in a.used_refresh:
                            a.reused.append(r)
                        return self._send(400, {"error": "invalid_grant"})
                    a.used_refresh.append(r)
                    return self._send(200, self._tokens("openid offline_access"))
                return self._send(400, {"error": "unsupported_grant_type"})
            if path == "/auth/revoke":
                a.revoked.append(body.get("token"))
                return self._send(200, {})
            if path == "/api/ssh/nonce":
                user = body.get("user_code")
                if not any(d["user_code"] == user for d in a.devices.values()):
                    return self._send(404, {"error": "unknown_code"})
                a.nonces[user] = secrets.token_urlsafe(16)
                return self._send(200, {"nonce": a.nonces[user], "expires_in": 120})
            if path == "/api/ssh/approve":
                user, nonce, sig = body.get("user_code"), body.get("nonce"), body.get("signature", "")
                if not nonce or a.nonces.pop(user, None) != nonce:
                    return self._send(400, {"error": "nonce_expired"})
                message = f"bromigos-login\n{user}\n{nonce}".encode()
                if not verify(a.keys, message, sig):
                    return self._send(404, {"error": "unknown_key"})
                a.signed.append(message)
                for d in a.devices.values():
                    if d["user_code"] == user:
                        d["approved"] = True
                return self._send(200, {"ok": True})
        self._send(404, {"error": "not_found"})

    def _tokens(self, scope):
        a = self.account
        access = "acc-" + secrets.token_hex(8)
        a.access[access] = time.time() + a.access_ttl
        a.refresh = "ref-" + secrets.token_hex(8)
        return {"access_token": access, "refresh_token": a.refresh, "expires_in": a.access_ttl,
                "token_type": "bearer", "scope": scope}


def verify(keys, message, signature):
    """ssh-keygen -Y verify against the account's keys: True when one of them signed it."""
    if not keys or "BEGIN SSH SIGNATURE" not in signature:
        return False
    with tempfile.TemporaryDirectory() as d:
        signers = os.path.join(d, "allowed_signers")
        with open(signers, "w") as f:
            for k in keys:
                f.write(f'{USER["email"]} namespaces="bromigos-login" {k["public_key"]}\n')
        sig = os.path.join(d, "sig")
        with open(sig, "w") as f:
            f.write(signature)
        r = subprocess.run(["ssh-keygen", "-Y", "verify", "-f", signers, "-I", USER["email"], "-n", "bromigos-login",
                            "-s", sig], input=message, capture_output=True)
        return r.returncode == 0


class Server:
    """with Server() as s: s.base is the account site, s.issuer the issuer; s.account the state."""

    def __enter__(self):
        self.account = Account()
        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.base = f"http://127.0.0.1:{self.httpd.server_address[1]}"
        self.issuer = self.base + "/auth"
        self.httpd.RequestHandlerClass = type("H", (Handler,), {"account": self.account, "base": self.base})
        self.thread = threading.Thread(target=self.httpd.serve_forever, args=(0.05,), daemon=True)
        self.thread.start()
        return self

    def __exit__(self, *exc):
        self.httpd.shutdown()
        self.httpd.server_close()
