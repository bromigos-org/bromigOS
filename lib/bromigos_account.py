"""bromigos_account: sign in to an online account from a widget, or any bromigOS code.

API (docs/plugins.md, "A widget that needs an account"):

    import bromigos_account as A

Every function takes account="default": a service can have several named accounts, such
as gitlab.com and your company's own GitLab ("work"). The one you had before named
accounts existed is "default", and nothing about it changed.

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
    A.api(provider)                    -> its API root (GitHub Enterprise: <base>/api/v3)
    A.label(provider)                  -> a short name to tag an account's rows: its label, the
                                         host for "default" (gitlab.com), else its name
    A.names(provider)                  -> ["default", "work", …]; no keyring
    A.accounts(provider)               -> [{"name", "label", "base", "signed_in", "who", "needs",
                                         "via"}], "default" first; no network
    A.add_account(provider, name, base=None, client_id=None, label=None)
    A.remove_account(provider, name)   signs it out, then forgets its settings
    A.Signin(provider)                 a non-blocking sign-in for a panel to draw: .start(),
                                         .state ("idle" | "waiting" | "signed_in" | "error"),
                                         .prompt (the on_prompt dict), .error, .cancel()
    A.http_json(url, data=None, headers=None, method=None, timeout=15, form=True)
                                       JSON over HTTPS; HTTPError carries .body (parsed JSON or text)
    A.authed_json(provider, url, data=None, method=None)
                                       JSON with the account's token; after a 401 it refreshes
                                         the token once and tries again. Raises SignInError when
                                         signed out, or when the sign-in can't be refreshed
    A.gh_token()                       the user's `gh` login token, read when asked, never stored
    A.PROVIDERS                        {name: {...}}: bromigos, twitch, github, gitlab (device flow),
                                         spotify (authorization code with PKCE, loopback redirect),
                                         plex (Plex's PIN: a code entered at plex.tv/link)
    A.plex_claim_token()               a claim token for a new Plex Media Server (its PLEX_CLAIM),
                                         from the signed-in Plex account; valid a few minutes

Where things live:

  * Client IDs and a server address: ~/.config/bromigos/accounts.toml. The default
    account is the provider's table ([gitlab] base = "…"); a named one is a table under it,
    [gitlab.accounts.work], with base, client_id and label. Every widget for that service
    shares them. bromigOS ships its own client IDs for Twitch, GitHub and gitlab.com;
    they're used only on the public site (an account with another base needs its own app).
    A named account on the same server as the default one shares the default's settings.
  * Tokens: the login keyring, through libsecret (the Secret Service), one item per
    account: service "bromigos-account:<provider>", account "<name>" ("default" for the
    first), labelled "bromigOS: <Provider> sign-in". Never in a file.

Bromigos, your own account (lib/bromigos_login.py has `bromigos login`, its SSH sign-in and
the account's SSH keys): an OpenID Connect provider. Its endpoints come from the issuer's
discovery document (<issuer>/.well-known/openid-configuration), the client is the public
`bromigos-cli`, and refresh tokens rotate, so a refresh holds a lock and reads the keyring
again first. Its addresses, client and scopes can change, for a test server:

    env BROMIGOS_AUTH_URL, BROMIGOS_ACCOUNT_URL, BROMIGOS_CLIENT_ID, BROMIGOS_SCOPES
    accounts.toml [bromigos] issuer = "…", base = "…", client_id = "…", scopes = "openid …"

The environment wins. BROMIGOS_TOKEN, a personal access token (bmg_pat_…), stands in for the
stored sign-in while it's set, the way gh's login does for GitHub.

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

    bromigos account list [PROVIDER] [--json]
    bromigos account add PROVIDER NAME [base=URL] [client_id=ID] [label=TEXT]
    bromigos account remove PROVIDER NAME [--yes]      (signs out, then forgets its settings)
    bromigos account status|login|logout PROVIDER [--as NAME]
    bromigos account configure PROVIDER [--as NAME] client_id=ID [base=URL] [label=TEXT]
    bromigos account set-token PROVIDER [--as NAME]   (reads the token without echoing it)
    bromigos account token                (how to make a Bromigos personal access token)
"""
import base64
import contextlib
import hashlib
import json
import os
import re
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
    "bromigos": {
        "title": "Bromigos", "flow": "device", "base": "https://account.bromigos.org",
        # an OpenID Connect issuer: the endpoints come from its discovery document; these
        # paths are only the fallback when that can't be read
        "issuer": "https://auth.bromigos.org", "discovery": True,
        "device_url": "{issuer}/oauth2/device/auth", "token_url": "{issuer}/oauth2/token",
        "who_url": "{issuer}/userinfo", "revoke_url": "{issuer}/oauth2/revoke",
        "scopes": ["openid", "offline_access", "profile", "email", "lab:read", "brodec:send", "account:read"],
        "scope_key": "scope", "who_field": "preferred_username",
        "who_fields": ["preferred_username", "email", "name", "sub"], "profile": ["email", "name", "sub"],
        # bromigOS's own public client, the same on any server: a test or staging one has it too
        "client_id": "bromigos-cli", "any_base": True,
        "token_prefix": "bmg_pat_", "env_token": "BROMIGOS_TOKEN",
        "env": {"issuer": "BROMIGOS_AUTH_URL", "base": "BROMIGOS_ACCOUNT_URL", "client_id": "BROMIGOS_CLIENT_ID",
                "scopes": "BROMIGOS_SCOPES"},
        "app_help": "Nothing to set up: run bromigos login.",
    },
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
        "device_url": "{base}/login/device/code", "token_url": "{base}/login/oauth/access_token",
        "scopes": ["repo", "read:user", "notifications"], "scope_key": "scope",
        # GitHub Enterprise Server: the same paths under its own address, its API at /api/v3
        "api": "https://api.github.com", "api_self": "{base}/api/v3",
        "who_url": "{api}/user", "who_field": "login", "gh": True,
        # bromigOS's own OAuth app (device flow, no secret: its ID isn't one), used when gh isn't signed in
        "client_id": "Ov23liUrAQsRagfTYxQj",
        "app_help": "To use your own app instead: make an OAuth app at github.com/settings/developers "
                    "with Enable Device Flow ticked (and Expire user access tokens unticked), and copy its "
                    "Client ID. On GitHub Enterprise Server, make it there the same way.",
    },
    "gitlab": {
        "title": "GitLab", "flow": "device", "base": "https://gitlab.com",
        "device_url": "{base}/oauth/authorize_device", "token_url": "{base}/oauth/token",
        "scopes": ["read_api", "read_user"], "scope_key": "scope", "api": "{base}/api/v4",
        "who_url": "{api}/user", "who_field": "username",
        # bromigOS's own gitlab.com application (non-confidential, device grant: its ID isn't a
        # secret). It only works on gitlab.com; a self-hosted GitLab needs an application of its own.
        "client_id": "5e34e8644147e7edfa98f96d443f34968c7cc7faae644beb61831fa5ede4f86d",
        "app_help": "For your own GitLab server (17.2 or later), User settings › Applications: a new "
                    "application, Confidential unticked, Device authorization grant ticked, scopes "
                    "read_api and read_user, redirect URI http://localhost. Copy its Application ID. Or "
                    "store a personal access token instead (bromigos account set-token gitlab).",
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

    def __init__(self, provider, fields, account="default"):
        self.provider, self.fields, self.account = provider, list(fields), account
        p = PROVIDERS.get(provider, {})
        who = p.get("title", provider) + (f" ({account})" if account != "default" else "")
        super().__init__(f"{who} needs {', '.join(self.fields)} in {accounts_path()}. " + p.get("app_help", ""))


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


DEFAULT = "default"
NAME_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,31}$")


def _scalars(table):
    return {k: v for k, v in (table or {}).items() if isinstance(v, (str, int)) and not isinstance(v, bool)}


def _named(doc, provider):
    """{name: table} of the provider's named accounts in accounts.toml."""
    acc = (doc.get(provider) or {}).get("accounts")
    return {k: v for k, v in acc.items() if isinstance(v, dict)} if isinstance(acc, dict) else {}


def _check(provider, account):
    """The provider's entry; KeyError when the provider or the named account doesn't exist."""
    p = _p(provider)
    if account != DEFAULT and account not in _named(_read_all(), provider):
        raise KeyError(f"no {p['title']} account named {account!r} "
                       f"(add it: bromigos account add {provider} {account})")
    return p


def config(provider, account=DEFAULT):
    """The account's settings: client_id, base, port (accounts.toml over the defaults). A
    named account on the same server as the default one takes the default's settings it
    doesn't set itself (its client ID, Spotify's port)."""
    p = _check(provider, account)
    doc = _read_all()
    top = _scalars(doc.get(provider))
    got = top
    if account != DEFAULT:
        got = _scalars(_named(doc, provider)[account])
        same = str(got.get("base") or p["base"]).rstrip("/") == str(top.get("base") or p["base"]).rstrip("/")
        inherit = {k: v for k, v in top.items() if k != "label" and (same or k == "port")}
        got = {**inherit, **got}
    out = {"base": p["base"], "client_id": p.get("client_id")}
    for k in ("port", "issuer"):
        if k in p:
            out[k] = p[k]
    out.update(got)
    if account == DEFAULT:                          # the environment wins (a test or staging server)
        out.update({k: os.environ[v].strip() for k, v in p.get("env", {}).items() if os.environ.get(v, "").strip()})
    out["base"] = str(out.get("base") or p["base"]).rstrip("/")
    if out.get("issuer"):
        out["issuer"] = str(out["issuer"]).rstrip("/")
    # bromigOS's own app is registered on the provider's public site only
    if "client_id" not in got and out["base"] != p["base"].rstrip("/") and not p.get("any_base"):
        out["client_id"] = None
    return out


def scopes(provider, account=DEFAULT):
    """The scopes a sign-in asks for: accounts.toml's or the environment's `scopes` (spaces
    or commas between), else the provider's own."""
    got = config(provider, account).get("scopes")
    if isinstance(got, str) and got.strip():
        return [s for s in re.split(r"[\s,]+", got) if s]
    return list(_p(provider)["scopes"])


def base(provider, account=DEFAULT):
    return config(provider, account)["base"]


def api(provider, account=DEFAULT):
    """The account's API root: api.github.com, or <base>/api/v3 on GitHub Enterprise Server;
    <base>/api/v4 for GitLab; the web root for a provider without one."""
    p = _p(provider)
    b = base(provider, account)
    if p.get("api_self") and b != p["base"].rstrip("/"):
        return p["api_self"].format(base=b)
    return (p.get("api") or "{base}").format(base=b)


def label(provider, account=DEFAULT):
    """A short name for the account's rows: its label, else the host for the default one
    ("gitlab.com"), else its name ("work")."""
    c = config(provider, account)
    if c.get("label"):
        return str(c["label"])
    if account == DEFAULT:
        host = urllib.parse.urlparse(c["base"]).hostname or provider
        return host.removeprefix("www.").removeprefix("open.")
    return account


def names(provider):
    """The provider's account names, "default" first (no keyring)."""
    _p(provider)
    return [DEFAULT] + sorted(_named(_read_all(), provider))


def accounts(provider):
    """Every account of the provider, "default" first, each with its status (no network)."""
    out = []
    for n in names(provider):
        out.append(dict(status(provider, n), name=n, label=label(provider, n), base=base(provider, n)))
    return out


def fields(provider, account=DEFAULT):
    p = _p(provider)
    if p["flow"] == "plex-pin" or p.get("any_base"):
        return []                                   # no app: the client identifier is made on first use, or is bromigOS's own
    out = [{"key": "client_id", "label": f"{p['title']} client ID", "hint": p["app_help"], "required": True}]
    if provider == "gitlab":
        out.append({"key": "base", "label": "GitLab address", "hint": "https://gitlab.com, or your own instance",
                    "required": False})
    elif provider == "github":
        out.append({"key": "base", "label": "GitHub address",
                    "hint": "https://github.com, or your GitHub Enterprise Server", "required": False})
    return out


def has_server(provider):
    """True when an account of this provider can live on a server of its own (GitLab, GitHub
    Enterprise): the settings form asks for its address."""
    return any(f["key"] == "base" for f in fields(provider))


def needs(provider, account=DEFAULT):
    if _gh_covers(provider, account):
        return []
    c = config(provider, account)
    return [f["key"] for f in fields(provider, account) if f["required"] and not c.get(f["key"])]


def _toml_value(v):
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, int):
        return str(v)
    return json.dumps(str(v))


def _toml_key(k):
    return k if re.fullmatch(r"[A-Za-z0-9_-]+", k) else json.dumps(k)


def _write_all(doc):
    lines = ["# bromigOS's account settings (lib/bromigos_account.py): client IDs, never secrets", ""]
    for name, table in doc.items():
        if not isinstance(table, dict):
            continue
        lines.append(f"[{_toml_key(name)}]")
        lines += [f"{_toml_key(k)} = {_toml_value(v)}" for k, v in table.items() if isinstance(v, (str, int, bool))]
        lines.append("")
        for an, at in _named(doc, name).items():
            lines.append(f"[{_toml_key(name)}.accounts.{_toml_key(an)}]")
            lines += [f"{_toml_key(k)} = {_toml_value(v)}" for k, v in at.items() if isinstance(v, (str, int, bool))]
            lines.append("")
    path = accounts_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        f.write("\n".join(lines))
    os.replace(tmp, path)


def _table(doc, provider, account):
    """The account's table in doc, made when missing (the default's is [provider])."""
    t = doc.setdefault(provider, {})
    if account == DEFAULT:
        return t
    return t.setdefault("accounts", {}).setdefault(account, {})


def configure(provider, account=DEFAULT, **values):
    """Set fields of the account's table in accounts.toml ([provider], or
    [provider.accounts.<name>]), keeping the rest of the file's tables. An empty value
    removes the field."""
    _check(provider, account)
    doc = _read_all()
    t = _table(doc, provider, account)
    for k, v in values.items():
        if v in (None, ""):
            t.pop(k, None)
        else:
            t[k] = v
    _write_all(doc)


def _norm_base(provider, url):
    """A server address as typed (git.example.org/) -> https://git.example.org; None for the
    provider's public site (its built-in app applies)."""
    url = str(url or "").strip().rstrip("/")
    if not url:
        return None
    if "://" not in url:
        url = "https://" + url
    pub = _p(provider)["base"].rstrip("/")
    return None if url in (pub, pub.replace("https://www.", "https://")) else url


def add_account(provider, name, base=None, client_id=None, label=None):
    """A new named account: its table in accounts.toml. base: its server (None or the public
    site: bromigOS's built-in app, when the provider has one). Returns status for it."""
    p = _p(provider)
    name = str(name or "").strip()
    if name == DEFAULT:
        raise ValueError(f"{p['title']} already has its default account")
    if not NAME_RE.match(name):
        raise ValueError("an account name is lower-case letters, digits, - and _, up to 32 (like work)")
    doc = _read_all()
    if name in _named(doc, provider):
        raise ValueError(f"{p['title']} already has an account named {name}")
    b = _norm_base(provider, base)
    if b and not has_server(provider):
        raise ValueError(f"{p['title']} has no servers of its own: leave the address out")
    t = _table(doc, provider, name)
    for k, v in (("base", b), ("client_id", (client_id or "").strip()), ("label", (label or "").strip())):
        if v:
            t[k] = v
    _write_all(doc)
    return status(provider, name)


def remove_account(provider, name):
    """Sign the named account out, then forget its table. The default account stays: sign
    it out instead."""
    p = _check(provider, name)
    if name == DEFAULT:
        raise ValueError(f"the default {p['title']} account can't be removed: sign it out instead")
    sign_out(provider, name)
    doc = _read_all()
    acc = doc.get(provider, {}).get("accounts", {})
    acc.pop(name, None)
    if not acc:
        doc[provider].pop("accounts", None)
    _write_all(doc)


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
ACCOUNT = DEFAULT                # the keyring account of the one sign-in a provider had before named accounts
_cache = {}                      # (provider, account) -> (time read, record): the keyring is asked at most every 30 s


def _ring():
    global KEYRING
    if KEYRING is None:
        KEYRING = _SecretService()
    return KEYRING


def _service(provider):
    return f"bromigos-account:{provider}"


def _load(provider, fresh=False, account=DEFAULT):
    key = (provider, account)
    hit = _cache.get(key)
    if hit and not fresh and time.monotonic() - hit[0] < 30:
        return hit[1]
    try:
        raw = _ring().get(_service(provider), account)
        rec = json.loads(raw) if raw else None
    except (RuntimeError, ValueError, OSError, subprocess.SubprocessError):
        rec = None
    _cache[key] = (time.monotonic(), rec)
    return rec


def _save(provider, rec, account=DEFAULT):
    title = _p(provider)["title"] + (f" ({account})" if account != DEFAULT else "")
    _ring().set(_service(provider), account, f"bromigOS: {title} sign-in", json.dumps(rec))
    _cache[(provider, account)] = (time.monotonic(), rec)


def sign_out(provider, account=DEFAULT, revoke=False):
    """Forget the stored sign-in. revoke: first ask the provider to cancel its refresh token
    too (when it has a revocation endpoint), quietly; a pasted token is left alone."""
    p = _p(provider)
    if revoke and p.get("revoke_url"):
        rec = _load(provider, fresh=True, account=account) or {}
        if rec.get("refresh_token") and not rec.get("pasted"):
            try:
                http_json(_url(provider, "revoke_url", account),
                          {"token": rec["refresh_token"], "token_type_hint": "refresh_token",
                           "client_id": rec.get("client_id") or config(provider, account).get("client_id") or ""})
            except (OSError, ValueError):
                pass                                # signing out here never waits on the service
    _ring().delete(_service(provider), account)
    _cache[(provider, account)] = (time.monotonic(), None)


@contextlib.contextmanager
def _refresh_lock(provider, account=DEFAULT):
    """One refresh at a time for an account, across processes: a provider that rotates its
    refresh tokens refuses the old one, and may cancel the sign-in when it sees it reused."""
    import fcntl
    d = os.path.join(os.environ.get("XDG_RUNTIME_DIR") or os.path.join(os.path.expanduser("~"), ".cache"), "bromigos")
    try:
        os.makedirs(d, mode=0o700, exist_ok=True)
        f = open(os.path.join(d, f"account-{provider}-{account}.lock"), "a")
    except OSError:
        yield                                       # no place for a lock: refresh without one
        return
    with f:
        fcntl.flock(f, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(f, fcntl.LOCK_UN)


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


def _gh_covers(provider, account=DEFAULT):
    """The gh login stands in for GitHub's default account on github.com."""
    p = _p(provider)
    return bool(p.get("gh") and account == DEFAULT and base(provider) == p["base"].rstrip("/") and gh_token())


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


def _fmt(url, provider, account=DEFAULT):
    return url.format(base=base(provider, account), api=api(provider, account) if "{api}" in url else "",
                      issuer=config(provider, account).get("issuer") or "")


_discovered = {}                 # issuer -> (time read, its discovery document), kept an hour
DISCOVERY = {"device_url": "device_authorization_endpoint", "token_url": "token_endpoint",
             "who_url": "userinfo_endpoint", "revoke_url": "revocation_endpoint"}


def discovery(provider, account=DEFAULT):
    """The issuer's OpenID Connect discovery document ({} when it can't be read)."""
    iss = config(provider, account).get("issuer")
    if not iss:
        return {}
    hit = _discovered.get(iss)
    if hit and time.monotonic() - hit[0] < 3600:
        return hit[1]
    try:
        doc = http_json(iss + "/.well-known/openid-configuration", timeout=10)
    except (OSError, ValueError):
        return {}
    if not isinstance(doc, dict):
        return {}
    _discovered[iss] = (time.monotonic(), doc)
    return doc


def _url(provider, key, account=DEFAULT):
    """An endpoint: from the discovery document for a provider that has one, else the
    provider's own pattern ("device_url", "token_url", "who_url", "revoke_url")."""
    p = _p(provider)
    if p.get("discovery"):
        got = discovery(provider, account).get(DISCOVERY[key])
        if isinstance(got, str) and got.startswith(("https://", "http://")):
            return got
    return _fmt(p[key], provider, account)


def _err_code(body):
    """The OAuth error word in an answer: {"error": "authorization_pending"} (RFC 8628), or
    Twitch's {"status": 400, "message": "authorization_pending"}."""
    if not isinstance(body, dict):
        return None
    return body.get("error") or body.get("message")


def _userinfo(provider, access, account=DEFAULT):
    """Who the token belongs to, as the service says ({} when it can't say)."""
    p = _p(provider)
    if not p.get("who_url"):
        return {}
    try:
        if p.get("who_header"):
            h = {p["who_header"]: access, **_plex_headers(provider)}
        else:
            h = {"Authorization": f"{p.get('who_auth', 'Bearer')} {access}",
                 "Client-Id": config(provider, account).get("client_id") or ""}
        d = http_json(_url(provider, "who_url", account), headers=h)
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def _pick_who(provider, d):
    p = _p(provider)
    for f in p.get("who_fields") or (p.get("who_field"), "login", "id"):
        if f and d.get(f):
            return d[f]
    return None


def _who(provider, access, account=DEFAULT):
    return _pick_who(provider, _userinfo(provider, access, account))


def _record(provider, tok, who=None, account=DEFAULT):
    now = time.time()
    c = config(provider, account)
    rec = {"access_token": tok["access_token"], "refresh_token": tok.get("refresh_token"),
           "expires_at": now + float(tok["expires_in"]) if tok.get("expires_in") else None,
           "scope": tok.get("scope"), "client_id": c.get("client_id"), "base": c["base"], "got": now}
    if who:
        rec["who"] = who
    else:
        info = _userinfo(provider, rec["access_token"], account)
        rec["who"] = _pick_who(provider, info)
        keep = {k: info[k] for k in _p(provider).get("profile", ()) if isinstance(info.get(k), str)}
        if keep:
            rec["profile"] = keep
    return rec


def _expired(rec):
    return bool(rec.get("expires_at") and rec["expires_at"] - 60 < time.time())


def _refresh(provider, rec, account=DEFAULT):
    with _refresh_lock(provider, account):
        # Read the keyring again under the lock: another program may have refreshed it while
        # this one waited, and a rotated refresh token can't be used twice.
        now = _load(provider, fresh=True, account=account)
        if not now:
            return None                             # signed out meanwhile
        if now.get("access_token") != rec.get("access_token") and not _expired(now):
            return now
        rec = now
        if not rec.get("refresh_token"):
            return None
        try:
            tok = http_json(_url(provider, "token_url", account),
                            {"grant_type": "refresh_token", "refresh_token": rec["refresh_token"],
                             "client_id": rec.get("client_id") or config(provider, account)["client_id"]})
        except (OSError, ValueError):
            return None
        if not tok.get("access_token"):
            return None
        tok.setdefault("refresh_token", rec["refresh_token"])        # Spotify may not send a new one
        new = _record(provider, tok, who=rec.get("who"), account=account)
        for k in ("profile", "how", "ssh_key"):                      # how it was signed in stays
            if rec.get(k):
                new[k] = rec[k]
        _save(provider, new, account)
        return new


def token(provider, account=DEFAULT):
    """A usable access token, or None. Refreshes one that has expired (or is within a
    minute of it). GitHub's default account: the gh login first, when there is one."""
    _p(provider)
    if _gh_covers(provider, account):
        return gh_token()
    env = _env_token(provider, account)
    if env:
        return env
    rec = _load(provider, account=account)
    if not rec:
        return None
    if _expired(rec):
        rec = _refresh(provider, rec, account)
        if not rec:
            return None
    return rec["access_token"]


def _env_token(provider, account=DEFAULT):
    """A token from the environment (BROMIGOS_TOKEN), which stands in for the stored sign-in."""
    var = _p(provider).get("env_token")
    if not var or account != DEFAULT:
        return None
    return os.environ.get(var, "").strip() or None


def refresh(provider, account=DEFAULT):
    """Refresh the stored token now (after the service answered 401): the new access
    token, or None when there's nothing to refresh with."""
    _p(provider)
    rec = _load(provider, fresh=True, account=account)
    new = _refresh(provider, rec, account) if rec else None
    return new["access_token"] if new else None


def set_token(provider, tok, who=None, account=DEFAULT):
    """Store a token the user pasted (a personal access token): no expiry, no refresh."""
    p = _check(provider, account)
    tok = (tok or "").strip()
    if not tok:
        raise SignInError("an empty token")
    if p.get("token_prefix") and not tok.startswith(p["token_prefix"]):
        raise SignInError(f"that isn't a {p['title']} personal access token: those start with {p['token_prefix']}")
    if re.search(r"\s", tok):
        raise SignInError("a token has no spaces or line breaks in it: paste only the token")
    rec = _record(provider, {"access_token": tok}, who=who, account=account)
    rec["pasted"] = True
    rec["how"] = "token"
    _save(provider, rec, account)
    return status(provider, account)


def status(provider, account=DEFAULT):
    p = _check(provider, account)
    if _gh_covers(provider, account):
        return {"signed_in": True, "who": _gh_login(), "needs": [], "via": "gh"}
    if _env_token(provider, account):
        return {"signed_in": True, "who": None, "needs": [], "via": "env", "how": "env"}
    rec = _load(provider, account=account)
    out = {"signed_in": bool(rec), "who": (rec or {}).get("who"), "needs": [] if rec else needs(provider, account),
           "via": "keyring" if rec else None}
    if p.get("profile") and rec:                    # Bromigos: how it was signed in, and the email
        out.update(how=rec.get("how") or ("token" if rec.get("pasted") else "device"),
                   email=(rec.get("profile") or {}).get("email"), ssh_key=rec.get("ssh_key"))
    return out


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
def device_start(provider, account=DEFAULT):
    """Ask for a user code: {device_code, user_code, verification_uri, verification_uri_complete,
    expires_in, interval}."""
    p = _p(provider)
    c = config(provider, account)
    if not c.get("client_id"):
        raise NeedsConfig(provider, ["client_id"], account)
    d = http_json(_url(provider, "device_url", account),
                  {"client_id": c["client_id"], p["scope_key"]: " ".join(scopes(provider, account))})
    if not d.get("device_code"):
        raise SignInError(f"{p['title']} gave no device code: {str(d)[:120]}")
    d.setdefault("verification_uri_complete", d.get("verification_uri"))
    d.setdefault("interval", 5)
    d.setdefault("expires_in", 900)
    return d


def device_poll(provider, start, cancelled=lambda: False, sleep=None, account=DEFAULT):
    """Wait for the user to approve; returns the token answer. Honours slow_down."""
    sleep = sleep or time.sleep                      # looked up now, so a test can stand in for it
    p = _p(provider)
    c = config(provider, account)
    interval = float(start.get("interval") or 5)
    deadline = time.time() + float(start.get("expires_in") or 900)
    data = {"client_id": c["client_id"], "device_code": start["device_code"],
            "grant_type": "urn:ietf:params:oauth:grant-type:device_code"}
    if provider == "twitch":
        data["scopes"] = " ".join(scopes(provider, account))
    while time.time() < deadline:
        if cancelled():
            raise SignInError("cancelled")
        sleep(interval)
        try:
            tok = http_json(_url(provider, "token_url", account), data)
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
    (a random one, made on first use and kept in accounts.toml). It names this machine, so
    every Plex account signed in here sends the default account's one."""
    c = config(provider)
    cid = c.get("client_id")
    if not cid:
        import uuid
        cid = str(uuid.uuid4())
        configure(provider, client_id=cid)
    return {"X-Plex-Product": _p(provider)["product"], "X-Plex-Client-Identifier": cid}


def plex_start(provider="plex", account=DEFAULT):
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


def plex_poll(provider, start, cancelled=lambda: False, sleep=None, account=DEFAULT):
    """Wait for the code to be entered at plex.tv/link: {"access_token": the account's token}."""
    sleep = sleep or time.sleep
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


def plex_claim_token(provider="plex", account=DEFAULT):
    """A claim token ("claim-…") for a new Plex Media Server, from the signed-in account. A
    server started with it as PLEX_CLAIM joins that account. It lasts only a few minutes, so
    ask for it just before the server starts."""
    tok = token(provider, account)
    if not tok:
        raise SignInError("sign in to Plex first: bromigos account login plex"
                          + (f" --as {account}" if account != DEFAULT else ""))
    d = http_json(_p(provider)["claim_url"], headers={"X-Plex-Token": tok, **_plex_headers(provider)})
    if not str(d.get("token") or "").startswith("claim-"):
        raise SignInError(f"Plex gave no claim token: {str(d)[:120]}")
    return d["token"]


# ------------------------------------------------------------------ authorization code + PKCE, loopback
def pkce_pair():
    verifier = base64.urlsafe_b64encode(secrets.token_bytes(48)).rstrip(b"=").decode()
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    return verifier, challenge


def pkce_url(provider, challenge, state, redirect, account=DEFAULT):
    p = _p(provider)
    c = config(provider, account)
    if not c.get("client_id"):
        raise NeedsConfig(provider, ["client_id"], account)
    q = {"client_id": c["client_id"], "response_type": "code", "redirect_uri": redirect, "state": state,
         "code_challenge_method": "S256", "code_challenge": challenge, p["scope_key"]: " ".join(scopes(provider, account))}
    return p["auth_url"] + "?" + urllib.parse.urlencode(q)


def pkce_flow(provider, on_prompt, cancelled=lambda: False, timeout=300, account=DEFAULT):
    """Listen on 127.0.0.1:<port>, send the user to the authorize page, take the code from
    the redirect, and trade it (with the verifier) for tokens."""
    import http.server
    p = _p(provider)
    c = config(provider, account)
    port = int(c.get("port") or p.get("port") or 8898)
    redirect = f"http://127.0.0.1:{port}/callback"
    verifier, challenge = pkce_pair()
    state = secrets.token_urlsafe(16)
    url = pkce_url(provider, challenge, state, redirect, account)
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
def _title(provider, account=DEFAULT):
    """"GitLab", or "GitLab (work)" for a named account."""
    t = _p(provider)["title"]
    return t if account == DEFAULT else f"{t} ({account})"


def _default_prompt(provider, account=DEFAULT):
    title = _title(provider, account)

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


def sign_in(provider, on_prompt=None, cancelled=None, account=DEFAULT):
    """Sign in, blocking until it's done: returns status(provider, account). cancelled: a
    callable or a threading.Event; when it says True the sign-in stops with SignInError."""
    cancelled = _stopper(cancelled)
    p = _check(provider, account)
    missing = needs(provider, account)
    if missing:
        raise NeedsConfig(provider, missing, account)
    prompt = on_prompt or _default_prompt(provider, account)
    if p["flow"] in ("device", "plex-pin"):
        start = (plex_start if p["flow"] == "plex-pin" else device_start)(provider, account=account)
        prompt({k: start.get(k) for k in ("user_code", "verification_uri", "verification_uri_complete", "expires_in")})
        tok = (plex_poll if p["flow"] == "plex-pin" else device_poll)(provider, start, cancelled, account=account)
    else:
        tok = pkce_flow(provider, prompt, cancelled, account=account)
    if not tok.get("access_token"):
        raise SignInError(f"{p['title']} gave no token")
    rec = _record(provider, tok, account=account)
    rec["how"] = "browser" if p["flow"] == "pkce" else "device"
    _save(provider, rec, account)
    return status(provider, account)


def authed_json(provider, url, data=None, method=None, account=DEFAULT, form=False, timeout=15):
    """JSON from a service with the account's token. A 401 refreshes the token once and
    tries again; SignInError when signed out or when the sign-in can't be renewed."""
    title = _title(provider, account)
    tok = token(provider, account)
    if not tok:
        raise SignInError(f"not signed in to {title}")

    def call(t):
        return http_json(url, data, headers={"Authorization": f"Bearer {t}"}, method=method, timeout=timeout,
                         form=form)
    try:
        return call(tok)
    except urllib.error.HTTPError as e:
        if e.code != 401:
            raise
        e.close()
    new = None if _env_token(provider, account) else refresh(provider, account)
    if not new:
        raise SignInError(f"your {title} sign-in has expired or was cancelled; sign in again")
    return call(new)


class Signin:
    """A sign-in a panel can draw while it runs: start() and read .state and .prompt."""

    def __init__(self, provider, on_change=None, account=DEFAULT):
        self.provider, self.on_change, self.account = provider, on_change, account
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
                sign_in(self.provider, prompt, lambda: self._stop, account=self.account)
                self._set(state="signed_in", prompt=None)
            except (NeedsConfig, SignInError, OSError, ValueError, RuntimeError, KeyError) as e:
                self._set(state="error", error=str(e)[:240], prompt=None)
        self.thread = threading.Thread(target=run, daemon=True, name=f"signin-{self.provider}-{self.account}")
        self.thread.start()

    def cancel(self):
        self._stop = True
        self._set(state="idle", prompt=None)


def token_help():
    """What `bromigos account token` prints: personal access tokens are made on the website."""
    site = base("bromigos")
    host = urllib.parse.urlparse(site).hostname or site
    return "\n".join([
        "A personal access token lets a script or another computer use your Bromigos account",
        "without signing in. bromigOS can't make one for you: you make it on the website.",
        "",
        f"  1. Open {site} and sign in.",
        f"  2. Go to {host} › Personal access tokens, and create one. Choose what it may do.",
        "  3. Copy it. It starts with bmg_pat_, and the website shows it only once.",
        "  4. Store it on this computer:",
        "       bromigos login --with-token",
        "     Paste it, then press Enter. Or give it to one script in BROMIGOS_TOKEN.",
        "",
        "Treat a token like a password. Delete it on the website when you no longer need it.",
    ])


# ------------------------------------------------------------------ command line
VERBS = ("status", "login", "logout", "configure", "set-token", "list", "add", "remove", "token")


def _usage():
    print(__doc__.split("Command line")[1].split("\n", 1)[1].strip())
    return 2


def _opts(argv):
    """(positional words, --as NAME, flags): --as NAME (or --as=NAME), --yes, --json."""
    words, acct, flags = [], DEFAULT, set()
    it = iter(argv)
    for a in it:
        if a == "--as":
            acct = next(it, "") or DEFAULT
        elif a.startswith("--as="):
            acct = a.split("=", 1)[1] or DEFAULT
        elif a in ("--yes", "-y", "--json"):
            flags.add("json" if a == "--json" else "yes")
        else:
            words.append(a)
    return words, acct, flags


def _list_lines(provider, rows):
    out = [_p(provider)["title"]]
    for r in rows:
        state = (f"signed in{' through gh' if r.get('via') == 'gh' else ''}"
                 + (f" as {r['who']}" if r.get("who") else "")) if r["signed_in"] else \
            ("needs " + ", ".join(r["needs"]) if r.get("needs") else "not signed in")
        out.append(f"  {r['name']:<12} {r['label']:<20} {r['base']:<32} {state}")
    return out


def main(argv):
    words, acct, flags = _opts(argv)
    if not words or words[0] not in VERBS or (words[0] not in ("list", "token") and len(words) < 2):
        return _usage()
    if words[0] == "token":
        print(token_help())
        return 0
    verb, prov = words[0], (words[1] if len(words) > 1 else None)
    kv = dict(a.split("=", 1) for a in words[2:] if "=" in a)
    try:
        if verb == "list":
            provs = [prov] if prov else list(PROVIDERS)
            got = {p: accounts(p) for p in provs}
            if "json" in flags:
                print(json.dumps(got if not prov else got[prov]))
            else:
                for p in provs:
                    print("\n".join(_list_lines(p, got[p])))
        elif verb == "add":
            name = words[2] if len(words) > 2 and "=" not in words[2] else None
            if not name:
                print("bromigos account: add PROVIDER NAME [base=URL] [client_id=ID] [label=TEXT]", file=sys.stderr)
                return 2
            st = add_account(prov, name, base=kv.get("base"), client_id=kv.get("client_id"), label=kv.get("label"))
            more = f"; it needs {', '.join(st['needs'])}: bromigos account configure {prov} --as {name} " + \
                " ".join(f"{k}=…" for k in st["needs"]) if st.get("needs") else \
                f"; sign in with: bromigos account login {prov} --as {name}"
            print(f"added the {_p(prov)['title']} account {name} ({base(prov, name)}){more}")
        elif verb == "remove":
            name = words[2] if len(words) > 2 else ""
            _check(prov, name)
            if name == DEFAULT:
                raise ValueError(f"the default {_p(prov)['title']} account can't be removed: "
                                 f"bromigos account logout {prov}")
            if "yes" not in flags:
                if not sys.stdin.isatty():
                    print("bromigos account: remove asks first; add --yes to remove without asking", file=sys.stderr)
                    return 1
                ans = input(f"Remove the {_p(prov)['title']} account {name}? It signs out and forgets its "
                            "settings. [y/N] ")
                if ans.strip().lower() not in ("y", "yes"):
                    print("kept it")
                    return 1
            remove_account(prov, name)
            print(f"removed the {_p(prov)['title']} account {name}")
        elif verb == "status":
            print(json.dumps(status(prov, acct)))
        elif verb == "logout":
            sign_out(prov, acct)
            print(f"signed out of {_title(prov, acct)}")
        elif verb == "configure":
            configure(prov, acct, **kv)
            where = f"[{prov}]" if acct == DEFAULT else f"[{prov}.accounts.{acct}]"
            print(f"{accounts_path()}: {where} updated")
        elif verb == "set-token":
            _check(prov, acct)
            import getpass
            tok = getpass.getpass(f"{_title(prov, acct)} token: ") if sys.stdin.isatty() else sys.stdin.read()
            print(json.dumps(set_token(prov, tok, account=acct)))
        else:
            def show(d):
                if d.get("user_code"):
                    print(f"Go to {d['verification_uri']} and enter {d['user_code']}")
                else:
                    print(f"Opening {d['auth_url']}")
                _default_prompt(prov, acct)(d)
            s = sign_in(prov, show, account=acct)
            print(f"signed in to {_title(prov, acct)}" + (f" as {s['who']}" if s.get("who") else ""))
    except (NeedsConfig, SignInError, KeyError, RuntimeError, ValueError) as e:
        msg = e.args[0] if isinstance(e, KeyError) and e.args else e
        print(f"bromigos account: {msg}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
