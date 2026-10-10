"""bromigos_account: sign in to an online account from a widget, or any bromigOS code.

API (docs/plugins.md, "A widget that needs an account"):

    import bromigos_account as A

    A.status(provider)                 -> {"signed_in", "who", "needs", "via"}; no network
    A.sign_in(provider, on_prompt=None, cancelled=None)
                                       blocks until signed in; returns status(provider).
                                         cancelled: a callable or threading.Event to stop it.
                                         Device flow: on_prompt({"user_code", "verification_uri",
                                         "verification_uri_complete", "expires_in"}); PKCE:
                                         on_prompt({"auth_url"}). Without on_prompt the page
                                         opens in the browser and a notification shows the code.
                                         Raises NeedsConfig (.fields) or SignInError (words).
    A.sign_out(provider)               forgets the stored token
    A.token(provider)                  -> a usable access token, refreshed when it has expired,
                                         or None when signed out (may use the network)
    A.refresh(provider)                -> refresh now (after a 401): the new token, or None
    A.set_token(provider, token, who=None)   store a pasted token (a GitLab personal access token)
    A.configure(provider, **fields)    writes client_id / base to accounts.toml
    A.needs(provider)                  -> the config fields still missing, e.g. ["client_id"]
    A.fields(provider)                 -> [{"key", "label", "hint", "required"}] for a settings form
    A.config(provider)                 -> {"client_id", "base", …} as configured
    A.base(provider)                   -> the provider's web root (GitLab: your instance)
    A.Signin(provider)                 a non-blocking sign-in for a panel to draw: .start(),
                                         .state ("idle" | "waiting" | "signed_in" | "error"),
                                         .prompt (the on_prompt dict), .error, .cancel()
    A.http_json(url, data=None, headers=None, method=None, timeout=15, form=True)
                                       JSON over HTTPS; HTTPError carries .body (parsed JSON or text)
    A.gh_token()                       the user's `gh` login token, read when asked, never stored
    A.PROVIDERS                        {name: {...}}: twitch, github, gitlab (device flow),
                                         spotify (authorization code with PKCE, loopback redirect),
                                         plex (Plex's PIN: a code entered at plex.tv/link)
    A.plex_claim_token()               a claim token for a new Plex Media Server (its PLEX_CLAIM),
                                         from the signed-in Plex account; valid a few minutes

Where things live:

  * Client IDs and a GitLab instance URL: ~/.config/bromigos/accounts.toml, one table per
    provider ([twitch] client_id = "…"). Every widget for that service shares them. They
    come from the user's own developer app; bromigOS ships no client ID and no secret.
  * Tokens: the login keyring, through libsecret (the Secret Service), one item per
    provider, labelled "bromigOS: <Provider> sign-in". Never in a file.

No flow here needs a client secret: Twitch and GitLab take a public client through the
device flow (RFC 8628), GitHub's OAuth apps allow the device flow, and Spotify takes the
authorization code with PKCE (RFC 7636) on a loopback redirect,
http://127.0.0.1:<port>/callback.

Plex needs no app at all. Its PIN sign-in has the device flow's shape: bromigOS asks
plex.tv for a four-character code, you enter it at plex.tv/link, and bromigOS polls until
Plex hands over the account's token. The only setting is a client identifier, a random ID
made on first use and kept in accounts.toml, so Plex lists this machine once under your
authorised devices.

Command line (bin/bromigos-account, which is `bromigos account`):

    bromigos account status|login|logout PROVIDER
    bromigos account configure PROVIDER client_id=ID [base=URL]
    bromigos account set-token PROVIDER         (reads the token without echoing it)
"""
import base64
import hashlib
import json
import os
import secrets
import shutil
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

# ------------------------------------------------------------------ providers
PROVIDERS = {
    "twitch": {
        "title": "Twitch", "flow": "device", "base": "https://www.twitch.tv",
        "device_url": "https://id.twitch.tv/oauth2/device", "token_url": "https://id.twitch.tv/oauth2/token",
        "scopes": ["user:read:follows"], "scope_key": "scopes",
        "who_url": "https://id.twitch.tv/oauth2/validate", "who_field": "login", "who_auth": "OAuth",
        # bromigOS's own Twitch app (a Public client: its ID isn't a secret), so signing in needs no setup
        "client_id": "re6ewya32fu9j3m3kyezdfvw5b500f",
        "app_help": "To use your own app instead: make one at dev.twitch.tv/console/apps (Client Type "
                    "Public, OAuth Redirect URL http://localhost) and copy its Client ID.",
    },
    "github": {
        "title": "GitHub", "flow": "device", "base": "https://github.com",
        "device_url": "https://github.com/login/device/code", "token_url": "https://github.com/login/oauth/access_token",
        "scopes": ["repo", "read:user", "notifications"], "scope_key": "scope",
        "who_url": "https://api.github.com/user", "who_field": "login", "gh": True,
        # bromigOS's own OAuth app (device flow, no secret: its ID isn't one), used when gh isn't signed in
        "client_id": "Ov23liUrAQsRagfTYxQj",
        "app_help": "To use your own app instead: make an OAuth app at github.com/settings/developers "
                    "with Enable Device Flow ticked (and Expire user access tokens unticked), and copy its "
                    "Client ID.",
    },
    "gitlab": {
        "title": "GitLab", "flow": "device", "base": "https://gitlab.com",
        "device_url": "{base}/oauth/authorize_device", "token_url": "{base}/oauth/token",
        "scopes": ["read_api", "read_user"], "scope_key": "scope",
        "who_url": "{base}/api/v4/user", "who_field": "username",
        "app_help": "In GitLab (17.2 or later), User settings › Applications: a new application, "
                    "Confidential unticked, scopes read_api and read_user, redirect URI http://127.0.0.1. "
                    "Copy its Application ID. Or store a personal access token instead "
                    "(bromigos account set-token gitlab).",
    },
    "spotify": {
        "title": "Spotify", "flow": "pkce", "base": "https://open.spotify.com", "port": 8898,
        "auth_url": "https://accounts.spotify.com/authorize", "token_url": "https://accounts.spotify.com/api/token",
        "scopes": ["user-read-playback-state", "user-modify-playback-state", "user-read-currently-playing",
                   "user-read-recently-played"], "scope_key": "scope",
        "who_url": "https://api.spotify.com/v1/me", "who_field": "display_name",
        "app_help": "Make an app at developer.spotify.com/dashboard with the Web API, and the redirect "
                    "URI http://127.0.0.1:8898/callback. Copy its Client ID.",
    },
    "plex": {
        "title": "Plex", "flow": "plex-pin", "base": "https://plex.tv", "product": "bromigOS",
        "pin_url": "https://plex.tv/api/v2/pins", "link_url": "https://plex.tv/link",
        "claim_url": "https://plex.tv/api/claim/token.json",
        "who_url": "https://plex.tv/api/v2/user", "who_field": "username", "who_header": "X-Plex-Token",
        "app_help": "Nothing to set up: you sign in with a free Plex account by entering a code at plex.tv/link.",
    },
}


class NeedsConfig(Exception):
    """The provider isn't configured yet: .fields lists what's missing (["client_id"])."""

    def __init__(self, provider, fields):
        self.provider, self.fields = provider, list(fields)
        p = PROVIDERS.get(provider, {})
        super().__init__(f"{p.get('title', provider)} needs {', '.join(self.fields)} in {accounts_path()}. "
                         + p.get("app_help", ""))


class SignInError(Exception):
    """A sign-in that didn't finish: denied, expired, or the service said no."""


def _p(provider):
    if provider not in PROVIDERS:
        raise KeyError(f"no account provider {provider!r} (known: {', '.join(PROVIDERS)})")
    return PROVIDERS[provider]


# ------------------------------------------------------------------ accounts.toml
def accounts_path():
    return os.path.join(os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config"), "bromigos", "accounts.toml")


def _read_all():
    try:
        import tomllib
        with open(accounts_path(), "rb") as f:
            return tomllib.load(f)
    except (OSError, ValueError):
        return {}


def config(provider):
    """The provider's settings: client_id, base, port (accounts.toml over the defaults)."""
    p = _p(provider)
    out = {"base": p["base"], "client_id": p.get("client_id")}
    if "port" in p:
        out["port"] = p["port"]
    got = _read_all().get(provider) or {}
    out.update({k: v for k, v in got.items() if isinstance(v, (str, int))})
    out["base"] = str(out.get("base") or p["base"]).rstrip("/")
    return out


def base(provider):
    return config(provider)["base"]


def fields(provider):
    p = _p(provider)
    if p["flow"] == "plex-pin":
        return []                                   # no app: the client identifier is made on first use
    out = [{"key": "client_id", "label": f"{p['title']} client ID", "hint": p["app_help"], "required": True}]
    if provider == "gitlab":
        out.append({"key": "base", "label": "GitLab address", "hint": "https://gitlab.com, or your own instance",
                    "required": False})
    return out


def needs(provider):
    if provider == "github" and gh_token():
        return []
    c = config(provider)
    return [f["key"] for f in fields(provider) if f["required"] and not c.get(f["key"])]


def _toml_value(v):
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, int):
        return str(v)
    return json.dumps(str(v))


def configure(provider, **values):
    """Set fields of [provider] in accounts.toml, keeping the rest of the file's tables."""
    _p(provider)
    doc = _read_all()
    t = dict(doc.get(provider) or {})
    for k, v in values.items():
        if v in (None, ""):
            t.pop(k, None)
        else:
            t[k] = v
    doc[provider] = t
    lines = ["# bromigOS's account settings (lib/bromigos_account.py): client IDs, never secrets", ""]
    for name, table in doc.items():
        if not isinstance(table, dict):
            continue
        lines.append(f"[{name}]")
        lines += [f"{k} = {_toml_value(v)}" for k, v in table.items() if isinstance(v, (str, int, bool))]
        lines.append("")
    path = accounts_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        f.write("\n".join(lines))
    os.replace(tmp, path)


# ------------------------------------------------------------------ the keyring (libsecret)
class _SecretService:
    """The login keyring through libsecret's GObject bindings, else the secret-tool command."""

    def __init__(self):
        self.lib = None
        try:
            import gi
            gi.require_version("Secret", "1")
            from gi.repository import Secret
            self.lib = Secret
            self.schema = Secret.Schema.new("org.bromigos.Account", Secret.SchemaFlags.NONE,
                                            {"service": Secret.SchemaAttributeType.STRING,
                                             "account": Secret.SchemaAttributeType.STRING})
        except (ImportError, ValueError):
            self.lib = None

    def get(self, service, account):
        attrs = {"service": service, "account": account}
        if self.lib:
            return self.lib.password_lookup_sync(self.schema, attrs, None)
        if shutil.which("secret-tool"):
            r = subprocess.run(["secret-tool", "lookup", "service", service, "account", account],
                               capture_output=True, text=True, timeout=10)
            return r.stdout if r.returncode == 0 and r.stdout else None
        raise RuntimeError("no keyring: install libsecret (and a Secret Service such as gnome-keyring)")

    def set(self, service, account, label, value):
        attrs = {"service": service, "account": account}
        if self.lib:
            if not self.lib.password_store_sync(self.schema, attrs, self.lib.COLLECTION_DEFAULT, label, value, None):
                raise RuntimeError("the keyring refused to store it")
            return
        if shutil.which("secret-tool"):
            r = subprocess.run(["secret-tool", "store", "--label", label, "service", service, "account", account],
                               input=value, capture_output=True, text=True, timeout=30)
            if r.returncode:
                raise RuntimeError("secret-tool: " + (r.stderr.strip() or "failed"))
            return
        raise RuntimeError("no keyring: install libsecret (and a Secret Service such as gnome-keyring)")

    def delete(self, service, account):
        attrs = {"service": service, "account": account}
        if self.lib:
            self.lib.password_clear_sync(self.schema, attrs, None)
        elif shutil.which("secret-tool"):
            subprocess.run(["secret-tool", "clear", "service", service, "account", account],
                           capture_output=True, timeout=10)


class MemoryKeyring:
    """A keyring in memory, for tests: A.KEYRING = A.MemoryKeyring()."""

    def __init__(self):
        self.items = {}

    def get(self, service, account):
        return self.items.get((service, account))

    def set(self, service, account, label, value):
        self.items[(service, account)] = value

    def delete(self, service, account):
        self.items.pop((service, account), None)


KEYRING = None
ACCOUNT = "default"
_cache = {}                      # provider -> (time read, record): the keyring is asked at most every 30 s


def _ring():
    global KEYRING
    if KEYRING is None:
        KEYRING = _SecretService()
    return KEYRING


def _service(provider):
    return f"bromigos-account:{provider}"


def _load(provider, fresh=False):
    hit = _cache.get(provider)
    if hit and not fresh and time.monotonic() - hit[0] < 30:
        return hit[1]
    try:
        raw = _ring().get(_service(provider), ACCOUNT)
        rec = json.loads(raw) if raw else None
    except (RuntimeError, ValueError, OSError, subprocess.SubprocessError):
        rec = None
    _cache[provider] = (time.monotonic(), rec)
    return rec


def _save(provider, rec):
    _ring().set(_service(provider), ACCOUNT, f"bromigOS: {_p(provider)['title']} sign-in", json.dumps(rec))
    _cache[provider] = (time.monotonic(), rec)


def sign_out(provider):
    _p(provider)
    _ring().delete(_service(provider), ACCOUNT)
    _cache[provider] = (time.monotonic(), None)


# ------------------------------------------------------------------ gh
_gh = {"t": 0.0, "token": None}


def gh_token():
    """The `gh` command's token for github.com (gh auth token), cached 5 minutes in memory."""
    if time.monotonic() - _gh["t"] < 300 and _gh["t"]:
        return _gh["token"]
    tok = None
    if shutil.which("gh"):
        try:
            r = subprocess.run(["gh", "auth", "token", "--hostname", "github.com"], capture_output=True, text=True,
                               timeout=10)
            tok = r.stdout.strip() or None if r.returncode == 0 else None
        except (OSError, subprocess.SubprocessError):
            tok = None
    _gh.update(t=time.monotonic(), token=tok)
    return tok


# ------------------------------------------------------------------ HTTP
def http_json(url, data=None, headers=None, method=None, timeout=15, form=True):
    """GET (or POST with data) and parse JSON. data is form-encoded (form=True) or JSON.
    An HTTP error raises urllib.error.HTTPError with .body set to the parsed answer."""
    h = {"Accept": "application/json", "User-Agent": "bromigOS"}
    h.update(headers or {})
    body = None
    if data is not None:
        if form:
            body = urllib.parse.urlencode(data).encode()
            h.setdefault("Content-Type", "application/x-www-form-urlencoded")
        else:
            body = json.dumps(data).encode()
            h.setdefault("Content-Type", "application/json")
    req = urllib.request.Request(url, data=body, headers=h, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read()
    except urllib.error.HTTPError as e:
        raw = e.read() or b""
        try:
            e.body = json.loads(raw)
        except ValueError:
            e.body = raw.decode(errors="replace")[:300]
        raise
    return json.loads(raw) if raw.strip() else {}


def _fmt(url, provider):
    return url.format(base=base(provider))


def _err_code(body):
    """The OAuth error word in an answer: {"error": "authorization_pending"} (RFC 8628), or
    Twitch's {"status": 400, "message": "authorization_pending"}."""
    if not isinstance(body, dict):
        return None
    return body.get("error") or body.get("message")


def _who(provider, access):
    p = _p(provider)
    if not p.get("who_url"):
        return None
    try:
        if p.get("who_header"):
            h = {p["who_header"]: access, **_plex_headers(provider)}
        else:
            h = {"Authorization": f"{p.get('who_auth', 'Bearer')} {access}",
                 "Client-Id": config(provider).get("client_id") or ""}
        d = http_json(_fmt(p["who_url"], provider), headers=h)
        return d.get(p["who_field"]) or d.get("login") or d.get("id")
    except (OSError, ValueError):
        return None


def _record(provider, tok, who=None):
    now = time.time()
    rec = {"access_token": tok["access_token"], "refresh_token": tok.get("refresh_token"),
           "expires_at": now + float(tok["expires_in"]) if tok.get("expires_in") else None,
           "scope": tok.get("scope"), "client_id": config(provider).get("client_id"), "base": base(provider),
           "got": now}
    rec["who"] = who or _who(provider, rec["access_token"])
    return rec


def _refresh(provider, rec):
    if not rec.get("refresh_token"):
        return None
    p = _p(provider)
    try:
        tok = http_json(_fmt(p["token_url"], provider), {"grant_type": "refresh_token", "refresh_token": rec["refresh_token"],
                                                         "client_id": rec.get("client_id") or config(provider)["client_id"]})
    except (OSError, ValueError):
        return None
    if not tok.get("access_token"):
        return None
    tok.setdefault("refresh_token", rec["refresh_token"])        # Spotify may not send a new one
    new = _record(provider, tok, who=rec.get("who"))
    _save(provider, new)
    return new


def token(provider):
    """A usable access token, or None. Refreshes one that has expired (or is within a
    minute of it). GitHub: the gh login first, when there is one."""
    p = _p(provider)
    if p.get("gh"):
        t = gh_token()
        if t:
            return t
    rec = _load(provider)
    if not rec:
        return None
    if rec.get("expires_at") and rec["expires_at"] - 60 < time.time():
        rec = _refresh(provider, _load(provider, fresh=True) or rec)
        if not rec:
            return None
    return rec["access_token"]


def refresh(provider):
    """Refresh the stored token now (after the service answered 401): the new access
    token, or None when there's nothing to refresh with."""
    _p(provider)
    rec = _load(provider, fresh=True)
    new = _refresh(provider, rec) if rec else None
    return new["access_token"] if new else None


def set_token(provider, tok, who=None):
    """Store a token the user pasted (a personal access token): no expiry, no refresh."""
    tok = (tok or "").strip()
    if not tok:
        raise SignInError("an empty token")
    rec = _record(provider, {"access_token": tok}, who=who)
    rec["pasted"] = True
    _save(provider, rec)
    return status(provider)


def status(provider):
    p = _p(provider)
    if p.get("gh") and gh_token():
        return {"signed_in": True, "who": _gh_login(), "needs": [], "via": "gh"}
    rec = _load(provider)
    return {"signed_in": bool(rec), "who": (rec or {}).get("who"), "needs": [] if rec else needs(provider),
            "via": "keyring" if rec else None}


_gh_who = {"login": None}


def _gh_login():
    if _gh_who["login"] is None and shutil.which("gh"):
        try:
            r = subprocess.run(["gh", "api", "user", "--jq", ".login"], capture_output=True, text=True, timeout=10)
            _gh_who["login"] = r.stdout.strip() if r.returncode == 0 else ""
        except (OSError, subprocess.SubprocessError):
            _gh_who["login"] = ""
    return _gh_who["login"] or None


# ------------------------------------------------------------------ the device flow (RFC 8628)
def device_start(provider):
    """Ask for a user code: {device_code, user_code, verification_uri, verification_uri_complete,
    expires_in, interval}."""
    p = _p(provider)
    c = config(provider)
    if not c.get("client_id"):
        raise NeedsConfig(provider, ["client_id"])
    d = http_json(_fmt(p["device_url"], provider), {"client_id": c["client_id"], p["scope_key"]: " ".join(p["scopes"])})
    if not d.get("device_code"):
        raise SignInError(f"{p['title']} gave no device code: {str(d)[:120]}")
    d.setdefault("verification_uri_complete", d.get("verification_uri"))
    d.setdefault("interval", 5)
    d.setdefault("expires_in", 900)
    return d


def device_poll(provider, start, cancelled=lambda: False, sleep=time.sleep):
    """Wait for the user to approve; returns the token answer. Honours slow_down."""
    p = _p(provider)
    c = config(provider)
    interval = float(start.get("interval") or 5)
    deadline = time.time() + float(start.get("expires_in") or 900)
    data = {"client_id": c["client_id"], "device_code": start["device_code"],
            "grant_type": "urn:ietf:params:oauth:grant-type:device_code"}
    if provider == "twitch":
        data["scopes"] = " ".join(p["scopes"])
    while time.time() < deadline:
        if cancelled():
            raise SignInError("cancelled")
        sleep(interval)
        try:
            tok = http_json(_fmt(p["token_url"], provider), data)
        except urllib.error.HTTPError as e:
            tok = getattr(e, "body", None) or {}
        code = _err_code(tok) if not (isinstance(tok, dict) and tok.get("access_token")) else None
        if code is None and isinstance(tok, dict) and tok.get("access_token"):
            return tok
        if code == "authorization_pending":
            continue
        if code == "slow_down":
            interval += 5
            continue
        if code in ("expired_token", "invalid device code"):
            raise SignInError("the code expired before it was approved; start again")
        if code == "access_denied":
            raise SignInError("sign-in was declined")
        raise SignInError(f"{p['title']} said: {code or str(tok)[:120]}")
    raise SignInError("the code expired before it was approved; start again")


# ------------------------------------------------------------------ Plex's PIN (plex.tv/link)
def _plex_headers(provider="plex"):
    """The headers plex.tv wants from a client: its product name and a stable identifier
    (a random one, made on first use and kept in accounts.toml)."""
    c = config(provider)
    cid = c.get("client_id")
    if not cid:
        import uuid
        cid = str(uuid.uuid4())
        configure(provider, client_id=cid)
    return {"X-Plex-Product": _p(provider)["product"], "X-Plex-Client-Identifier": cid}


def plex_start(provider="plex"):
    """Ask plex.tv for a PIN: {device_code (the PIN's id), user_code, verification_uri,
    verification_uri_complete, expires_in, interval}. Without `strong`, the code is the short
    one plex.tv/link takes."""
    p = _p(provider)
    d = http_json(p["pin_url"], {}, headers=_plex_headers(provider), method="POST")
    if not d.get("id") or not d.get("code"):
        raise SignInError(f"Plex gave no PIN: {str(d)[:120]}")
    return {"device_code": str(d["id"]), "user_code": d["code"], "verification_uri": p["link_url"],
            "verification_uri_complete": p["link_url"], "expires_in": int(d.get("expiresIn") or 900),
            "interval": 2}


def plex_poll(provider, start, cancelled=lambda: False, sleep=time.sleep):
    """Wait for the code to be entered at plex.tv/link: {"access_token": the account's token}."""
    p = _p(provider)
    deadline = time.time() + float(start.get("expires_in") or 900)
    while time.time() < deadline:
        if cancelled():
            raise SignInError("cancelled")
        sleep(float(start.get("interval") or 2))
        try:
            d = http_json(f"{p['pin_url']}/{start['device_code']}", headers=_plex_headers(provider))
        except urllib.error.HTTPError as e:
            if e.code == 404:
                raise SignInError("the code expired before it was entered; start again") from None
            raise SignInError(f"Plex said: HTTP {e.code}") from None
        if d.get("authToken"):
            return {"access_token": d["authToken"]}
    raise SignInError("the code expired before it was entered; start again")


def plex_claim_token(provider="plex"):
    """A claim token ("claim-…") for a new Plex Media Server, from the signed-in account. A
    server started with it as PLEX_CLAIM joins that account. It lasts only a few minutes, so
    ask for it just before the server starts."""
    tok = token(provider)
    if not tok:
        raise SignInError("sign in to Plex first: bromigos account login plex")
    d = http_json(_p(provider)["claim_url"], headers={"X-Plex-Token": tok, **_plex_headers(provider)})
    if not str(d.get("token") or "").startswith("claim-"):
        raise SignInError(f"Plex gave no claim token: {str(d)[:120]}")
    return d["token"]


# ------------------------------------------------------------------ authorization code + PKCE, loopback
def pkce_pair():
    verifier = base64.urlsafe_b64encode(secrets.token_bytes(48)).rstrip(b"=").decode()
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    return verifier, challenge


def pkce_url(provider, challenge, state, redirect):
    p = _p(provider)
    c = config(provider)
    if not c.get("client_id"):
        raise NeedsConfig(provider, ["client_id"])
    q = {"client_id": c["client_id"], "response_type": "code", "redirect_uri": redirect, "state": state,
         "code_challenge_method": "S256", "code_challenge": challenge, p["scope_key"]: " ".join(p["scopes"])}
    return p["auth_url"] + "?" + urllib.parse.urlencode(q)


def pkce_flow(provider, on_prompt, cancelled=lambda: False, timeout=300):
    """Listen on 127.0.0.1:<port>, send the user to the authorize page, take the code from
    the redirect, and trade it (with the verifier) for tokens."""
    import http.server
    p = _p(provider)
    c = config(provider)
    port = int(c.get("port") or p.get("port") or 8898)
    redirect = f"http://127.0.0.1:{port}/callback"
    verifier, challenge = pkce_pair()
    state = secrets.token_urlsafe(16)
    url = pkce_url(provider, challenge, state, redirect)
    got = {}

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):                                  # noqa: N802
            u = urllib.parse.urlparse(self.path)
            q = dict(urllib.parse.parse_qsl(u.query))
            if u.path != "/callback":
                self.send_response(404)
                self.end_headers()
                return
            ok = q.get("state") == state and q.get("code")
            got.update(q if ok else {"error": q.get("error") or "the answer didn't match this sign-in"})
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            msg = "Signed in to bromigOS. You can close this tab." if ok else "Sign-in failed: " + got["error"]
            self.wfile.write(f"<!doctype html><title>bromigOS</title><p>{msg}</p>".encode())

        def log_message(self, *a):
            pass

    try:
        srv = http.server.HTTPServer(("127.0.0.1", port), Handler)
    except OSError as e:
        raise SignInError(f"port {port} is busy ({e.strerror}); set port in [{provider}] of accounts.toml "
                          "and the same redirect URI in your app")
    srv.timeout = 1
    on_prompt({"auth_url": url, "redirect_uri": redirect})
    deadline = time.time() + timeout
    try:
        while not got and time.time() < deadline and not cancelled():
            srv.handle_request()
    finally:
        srv.server_close()
    if not got:
        raise SignInError("cancelled" if cancelled() else "no answer from the browser in 5 minutes; start again")
    if got.get("error"):
        raise SignInError(got["error"])
    return http_json(p["token_url"], {"grant_type": "authorization_code", "code": got["code"], "redirect_uri": redirect,
                                      "client_id": c["client_id"], "code_verifier": verifier})


# ------------------------------------------------------------------ sign in
def _default_prompt(provider):
    title = _p(provider)["title"]

    def show(d):
        url = d.get("verification_uri_complete") or d.get("auth_url")
        if url:
            subprocess.Popen(["xdg-open", url], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                             start_new_session=True)
        if d.get("user_code") and shutil.which("notify-send"):
            subprocess.Popen(["notify-send", "-a", "bromigOS", f"Sign in to {title}",
                              f"Enter {d['user_code']} at {d.get('verification_uri')}"],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return show


def _stopper(cancelled):
    """cancelled as a callable: a function, a threading.Event, or None."""
    if cancelled is None:
        return lambda: False
    if hasattr(cancelled, "is_set"):
        return cancelled.is_set
    return cancelled


def sign_in(provider, on_prompt=None, cancelled=None):
    """Sign in, blocking until it's done: returns status(provider). cancelled: a callable
    or a threading.Event; when it says True the sign-in stops with SignInError."""
    cancelled = _stopper(cancelled)
    p = _p(provider)
    missing = needs(provider)
    if missing:
        raise NeedsConfig(provider, missing)
    prompt = on_prompt or _default_prompt(provider)
    if p["flow"] in ("device", "plex-pin"):
        start = (plex_start if p["flow"] == "plex-pin" else device_start)(provider)
        prompt({k: start.get(k) for k in ("user_code", "verification_uri", "verification_uri_complete", "expires_in")})
        tok = (plex_poll if p["flow"] == "plex-pin" else device_poll)(provider, start, cancelled)
    else:
        tok = pkce_flow(provider, prompt, cancelled)
    if not tok.get("access_token"):
        raise SignInError(f"{p['title']} gave no token")
    _save(provider, _record(provider, tok))
    return status(provider)


class Signin:
    """A sign-in a panel can draw while it runs: start() and read .state and .prompt."""

    def __init__(self, provider, on_change=None):
        self.provider, self.on_change = provider, on_change
        self.state, self.prompt, self.error = "idle", None, None
        self._stop = False
        self.thread = None

    def _set(self, **kw):
        self.__dict__.update(kw)
        if self.on_change:
            try:
                self.on_change(self)
            except Exception:                          # noqa: BLE001  a panel's hook never breaks the sign-in
                pass

    def start(self):
        if self.state == "waiting":
            return
        self._stop = False
        self._set(state="waiting", prompt=None, error=None)

        def run():
            def prompt(d):
                self._set(prompt=d)
                url = d.get("verification_uri_complete") or d.get("auth_url")
                if url:
                    subprocess.Popen(["xdg-open", url], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                     start_new_session=True)
            try:
                sign_in(self.provider, prompt, lambda: self._stop)
                self._set(state="signed_in", prompt=None)
            except (NeedsConfig, SignInError, OSError, ValueError, RuntimeError) as e:
                self._set(state="error", error=str(e)[:240], prompt=None)
        self.thread = threading.Thread(target=run, daemon=True, name=f"signin-{self.provider}")
        self.thread.start()

    def cancel(self):
        self._stop = True
        self._set(state="idle", prompt=None)


# ------------------------------------------------------------------ command line
def main(argv):
    if len(argv) < 2 or argv[0] not in ("status", "login", "logout", "configure", "set-token"):
        print(__doc__.split("Command line")[1].split("\n", 1)[1].strip())
        return 2
    verb, prov = argv[0], argv[1]
    try:
        if verb == "status":
            print(json.dumps(status(prov)))
        elif verb == "logout":
            sign_out(prov)
            print(f"signed out of {_p(prov)['title']}")
        elif verb == "configure":
            configure(prov, **dict(a.split("=", 1) for a in argv[2:] if "=" in a))
            print(f"{accounts_path()}: [{prov}] updated")
        elif verb == "set-token":
            import getpass
            tok = getpass.getpass(f"{_p(prov)['title']} token: ") if sys.stdin.isatty() else sys.stdin.read()
            print(json.dumps(set_token(prov, tok)))
        else:
            def show(d):
                if d.get("user_code"):
                    print(f"Go to {d['verification_uri']} and enter {d['user_code']}")
                else:
                    print(f"Opening {d['auth_url']}")
                _default_prompt(prov)(d)
            s = sign_in(prov, show)
            print(f"signed in to {_p(prov)['title']}" + (f" as {s['who']}" if s.get("who") else ""))
    except (NeedsConfig, SignInError, KeyError, RuntimeError) as e:
        print(f"bromigos account: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
