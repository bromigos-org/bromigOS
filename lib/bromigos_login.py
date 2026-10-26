"""bromigos_login: sign in to your Bromigos account (`bromigos login`, `logout`, `whoami`).

The sign-in itself, its keyring item and its refresh are lib/bromigos_account.py's, as the
provider "bromigos". This module adds what only the Bromigos account has:

    L.ssh_sign_in(key, say=print)      sign in with an SSH key instead of a browser: the device
                                         flow's code, approved by a signature from the key
    L.local_keys()                     [Key]: the keys in ssh-agent and ~/.ssh, each once
    L.key_from_path(path)              a Key for --key PATH (a private key or its .pub)
    L.sign(key, data)                  ssh-keygen -Y sign -n bromigos-login: the armoured signature
    L.account_ssh_keys()               the SSH public keys on the account, checked, or None when
                                         signed out: [{"type", "blob", "line", "title",
                                         "fingerprint", "created_at", "last_used_at"}]
    L.parse_public(line)               (type, blob, comment) of an OpenSSH public key line, or None
    L.fingerprint(blob)                "SHA256:…", the way ssh-keygen -l shows it
    L.token()                          a valid access token for the account, refreshed when it
                                         has expired, or None (bromigos_account.token("bromigos"))

SSH sign-in, against https://account.bromigos.org (the account site, `base`):

  1. Start the device flow, as `bromigos login` does. It gives a user code.
  2. POST <base>/api/ssh/nonce {"user_code"} answers {"nonce", "expires_in"}.
  3. Sign "bromigos-login\\n<user_code>\\n<nonce>" with ssh-keygen -Y sign -n bromigos-login:
     -f <private key>, or -f <public key> -U for a key in ssh-agent. FIDO keys work too.
  4. POST <base>/api/ssh/approve {"user_code", "nonce", "signature"}.
  5. Poll the token endpoint as the device flow always does.

Command line (bin/bromigos-login, bin/bromigos-logout, bin/bromigos-whoami):

    bromigos login [--no-browser]       sign in with a code you enter on the website
    bromigos login --ssh [--key PATH]   sign in with an SSH key on your account, no browser
    bromigos login --with-token         store a personal access token, read from stdin
    bromigos logout [--json]            forget the sign-in on this computer
    bromigos whoami [--json]            who's signed in, and how
"""
import base64
import binascii
import getpass
import hashlib
import json
import os
import re
import select
import shutil
import subprocess
import sys
import tempfile
import threading
import urllib.error
import urllib.parse

import bromigos_account as A

PROVIDER = "bromigos"
NAMESPACE = "bromigos-login"
KEY_TYPES = ("ssh-ed25519", "ssh-rsa", "ecdsa-sha2-nistp256", "ecdsa-sha2-nistp384", "ecdsa-sha2-nistp521",
             "sk-ssh-ed25519@openssh.com", "sk-ecdsa-sha2-nistp256@openssh.com")
SHORT_TYPE = {"ssh-ed25519": "ED25519", "ssh-rsa": "RSA", "ecdsa-sha2-nistp256": "ECDSA", "ecdsa-sha2-nistp384": "ECDSA",
              "ecdsa-sha2-nistp521": "ECDSA", "sk-ssh-ed25519@openssh.com": "ED25519-SK",
              "sk-ecdsa-sha2-nistp256@openssh.com": "ECDSA-SK"}


class LoginError(Exception):
    """A sign-in that can't go on, in words for the person at the terminal."""


def token():
    """A valid access token for the Bromigos account, refreshed when it has expired, or None
    when signed out. BROMIGOS_TOKEN, when it's set, comes first."""
    return A.token(PROVIDER)


def site():
    """The account website's address, https://account.bromigos.org unless it's configured."""
    return A.base(PROVIDER)


def site_name():
    return urllib.parse.urlparse(site()).hostname or site()


# ------------------------------------------------------------------ SSH keys
def parse_public(line):
    """(type, blob, comment) of an OpenSSH public key line, or None. No options, no line
    breaks, a known key type and a blob that decodes and names the same type."""
    if not isinstance(line, str) or "\n" in line.strip() or "\r" in line or "\0" in line:
        return None
    parts = line.strip().split(None, 2)
    if len(parts) < 2 or parts[0] not in KEY_TYPES:
        return None
    try:
        raw = base64.b64decode(parts[1], validate=True)
    except (binascii.Error, ValueError):
        return None
    n = int.from_bytes(raw[:4], "big") if len(raw) >= 4 else 0
    if raw[4:4 + n].decode("ascii", "replace") != parts[0]:
        return None
    return parts[0], parts[1], parts[2] if len(parts) > 2 else ""


def fingerprint(blob):
    """SHA256:… of a key's blob (its base64 part), as ssh-keygen -l prints it."""
    digest = hashlib.sha256(base64.b64decode(blob)).digest()
    return "SHA256:" + base64.b64encode(digest).decode().rstrip("=")


class Key:
    """A key this computer can sign with: in ssh-agent, a private key file, or both."""

    def __init__(self, type_, blob, comment="", path=None, agent=False):
        self.type, self.blob, self.comment, self.path, self.agent = type_, blob, comment, path, agent

    @property
    def public(self):
        return f"{self.type} {self.blob}" + (f" {self.comment}" if self.comment else "")

    @property
    def fingerprint(self):
        return fingerprint(self.blob)

    def describe(self):
        where = []
        if self.agent:
            where.append("in ssh-agent")
        if self.path:
            where.append(_home(self.path))
        name = f" {self.comment}" if self.comment else ""
        return f"{self.fingerprint}  {SHORT_TYPE.get(self.type, self.type)}{name}  ({', '.join(where)})"


def _home(path):
    h = os.path.expanduser("~")
    return "~" + path[len(h):] if path and path.startswith(h + "/") else path


def ssh_dir():
    return os.path.join(os.path.expanduser("~"), ".ssh")


def agent_keys():
    """The public keys ssh-agent holds ([] without an agent, or without ssh-add)."""
    if not os.environ.get("SSH_AUTH_SOCK") or not shutil.which("ssh-add"):
        return []
    try:
        r = subprocess.run(["ssh-add", "-L"], capture_output=True, text=True, timeout=10, stdin=subprocess.DEVNULL)
    except (OSError, subprocess.SubprocessError):
        return []
    out = []
    for line in r.stdout.splitlines() if r.returncode == 0 else []:
        got = parse_public(line)
        if got:
            out.append(Key(*got, agent=True))
    return out


def file_keys(folder=None):
    """The key pairs in ~/.ssh: a public key file with its private key beside it."""
    folder = folder or ssh_dir()
    out = []
    try:
        names = sorted(os.listdir(folder))
    except OSError:
        return []
    for name in names:
        if not name.endswith(".pub"):
            continue
        private = os.path.join(folder, name[:-4])
        if not os.path.isfile(private):
            continue
        try:
            with open(os.path.join(folder, name)) as f:
                got = parse_public(f.readline())
        except (OSError, UnicodeDecodeError):
            continue
        if got:
            out.append(Key(*got, path=private))
    return out


def local_keys():
    """Every key this computer can sign with, each once: ssh-agent's first, then ~/.ssh's.
    A key in both is marked as both (the agent signs, so no passphrase is asked)."""
    keys = {}
    for k in agent_keys() + file_keys():
        if k.blob in keys:
            have = keys[k.blob]
            have.path = have.path or k.path
            have.agent = have.agent or k.agent
            have.comment = have.comment or k.comment
        else:
            keys[k.blob] = k
    return list(keys.values())


def key_from_path(path):
    """--key PATH: a private key (its .pub beside it, or read with ssh-keygen -y) or a public
    key whose private half is in ssh-agent or beside it."""
    path = os.path.abspath(os.path.expanduser(path))
    pub = path if path.endswith(".pub") else path + ".pub"
    private = path[:-4] if path.endswith(".pub") else path
    line = None
    if os.path.isfile(pub):
        with open(pub) as f:
            line = f.readline()
    elif os.path.isfile(private) and shutil.which("ssh-keygen"):
        r = subprocess.run(["ssh-keygen", "-y", "-f", private], capture_output=True, text=True, timeout=60)
        line = r.stdout if r.returncode == 0 else None
    if not line:
        raise LoginError(f"{_home(path)}: no SSH key there")
    got = parse_public(line)
    if not got:
        raise LoginError(f"{_home(pub)} isn't an SSH public key bromigOS knows")
    agent = any(k.blob == got[1] for k in agent_keys())
    key = Key(*got, path=private if os.path.isfile(private) else None, agent=agent)
    if not key.path and not key.agent:
        raise LoginError(f"{_home(pub)} is only a public key, and ssh-agent doesn't hold its private key")
    return key


def choose_key(keys, ask=None, say=print):
    """The key to sign with: the only one, or the one the person picks from a numbered list."""
    if not keys:
        raise LoginError("No SSH key found: none in ssh-agent and none in ~/.ssh. Make one with "
                         "ssh-keygen -t ed25519, add its public key at " + site_name() + " › SSH keys, "
                         "then run bromigos login --ssh again.")
    if len(keys) == 1:
        return keys[0]
    if ask is None:
        if not sys.stdin.isatty():
            raise LoginError("Several SSH keys here, and no terminal to ask which: choose one with --key PATH")
        ask = input
    say("Which SSH key should sign you in?")
    for i, k in enumerate(keys, 1):
        say(f"  {i}. {k.describe()}")
    while True:
        answer = ask(f"Key (1-{len(keys)}) [1]: ").strip() or "1"
        if answer.isdigit() and 1 <= int(answer) <= len(keys):
            return keys[int(answer) - 1]
        say(f"Type a number from 1 to {len(keys)}.")


def sign(key, data):
    """The armoured SSH signature ("-----BEGIN SSH SIGNATURE-----…") of data, made by
    ssh-keygen -Y sign. A key in ssh-agent signs there (-U), so it never asks for a
    passphrase; a key file may ask for one, and a FIDO key for a touch, on the terminal."""
    if not shutil.which("ssh-keygen"):
        raise LoginError("ssh-keygen isn't installed (the openssh package has it)")
    with tempfile.TemporaryDirectory(prefix="bromigos-login-") as d:
        msg = os.path.join(d, "message")
        with open(msg, "wb") as f:
            f.write(data)
        if key.agent:
            pub = os.path.join(d, "key.pub")
            with open(pub, "w") as f:
                f.write(key.public + "\n")
            argv = ["ssh-keygen", "-Y", "sign", "-n", NAMESPACE, "-f", pub, "-U", msg]
        elif key.path:
            argv = ["ssh-keygen", "-Y", "sign", "-n", NAMESPACE, "-f", key.path, msg]
        else:
            raise LoginError("that key's private half isn't here or in ssh-agent")
        # The message goes in a file, so stdin stays the terminal: a passphrase is read there,
        # never from a pipe, and no password window opens.
        try:
            r = subprocess.run(argv, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=120)
        except subprocess.TimeoutExpired:
            raise LoginError("ssh-keygen waited too long (for a passphrase or a touch of the key)") from None
        try:
            with open(msg + ".sig") as f:
                sig = f.read()
        except OSError:
            sig = ""
        if r.returncode or "BEGIN SSH SIGNATURE" not in sig:
            why = (r.stderr.strip().splitlines() or ["it failed"])[-1]
            raise LoginError(f"ssh-keygen couldn't sign with {key.fingerprint}: {why}")
        return sig


def message(user_code, nonce):
    """The exact bytes an SSH sign-in signs."""
    return f"bromigos-login\n{user_code}\n{nonce}".encode()


def _not_on_account(key):
    return (f"The account doesn't know the SSH key {key.fingerprint}. Add its public key at "
            f"{site_name()} › SSH keys, then run bromigos login --ssh again. Its public key:\n  {key.public}")


def _said(e):
    body = getattr(e, "body", None)
    if isinstance(body, dict):
        return str(body.get("error_description") or body.get("message") or body.get("error") or "")
    return str(body or "")[:200]


def approve(start, key, sign_with=None):
    """Steps 2 to 4 of an SSH sign-in: a nonce for the code, the key's signature, and the
    approval. Raises LoginError in plain words."""
    sign_with = sign_with or sign
    b = site()
    code = start["user_code"]
    try:
        got = A.http_json(b + "/api/ssh/nonce", {"user_code": code}, method="POST", form=False)
    except urllib.error.HTTPError as e:
        raise LoginError(f"The account site wouldn't start an SSH sign-in (HTTP {e.code}). {_said(e)}".strip()) from None
    except (OSError, ValueError) as e:
        raise LoginError(f"Couldn't reach {site_name()}: {getattr(e, 'reason', e)}") from None
    nonce = got.get("nonce") if isinstance(got, dict) else None
    if not isinstance(nonce, str) or not nonce or "\n" in nonce:
        raise LoginError("The account site gave no sign-in challenge")
    sig = sign_with(key, message(code, nonce))
    try:
        A.http_json(b + "/api/ssh/approve", {"user_code": code, "nonce": nonce, "signature": sig},
                    method="POST", form=False)
    except urllib.error.HTTPError as e:
        word = ""
        if isinstance(getattr(e, "body", None), dict):
            word = str(e.body.get("error") or "")
        if e.code in (403, 404) or "key" in word:
            raise LoginError(_not_on_account(key)) from None
        if e.code in (400, 410) and ("expired" in word or "nonce" in word):
            raise LoginError("The sign-in challenge expired before it was signed; run bromigos login --ssh again") from None
        raise LoginError(f"The account site refused the signature (HTTP {e.code}). {_said(e)}".strip()) from None
    except (OSError, ValueError) as e:
        raise LoginError(f"Couldn't reach {site_name()}: {getattr(e, 'reason', e)}") from None


def ssh_sign_in(key, say=print, sign_with=None, cancelled=None):
    """Sign in with an SSH key: no browser, no code to type. Stores the tokens in the
    keyring and returns bromigos_account.status("bromigos")."""
    start = A.device_start(PROVIDER)
    say(f"Signing in with {key.fingerprint}" + (" (ssh-agent)" if key.agent else "") + "…")
    if key.type.startswith("sk-"):
        say("Touch your security key when it blinks.")
    approve(start, key, sign_with)
    tok = A.device_poll(PROVIDER, start, A._stopper(cancelled))
    if not tok.get("access_token"):
        raise A.SignInError("the account gave no token")
    rec = A._record(PROVIDER, tok)
    rec.update(how="ssh", ssh_key=key.fingerprint)
    _keep(rec, "bromigos login --ssh")
    return A.status(PROVIDER)


# ------------------------------------------------------------------ the account's SSH keys
def account_ssh_keys():
    """The SSH public keys on the account (GET <base>/api/me/ssh-keys), or None when this
    computer isn't signed in. Each key is checked: a known type, no options and no line
    breaks, so it's safe to add to an authorized_keys file. Its fingerprint is worked out
    here, not taken from the answer. `line` is the authorized_keys line, with the key's title
    as its comment. Raises SignInError or OSError when the account can't be read."""
    if not token():
        return None
    got = A.authed_json(PROVIDER, site() + "/api/me/ssh-keys")
    if isinstance(got, dict):                       # {"keys": [...]} is accepted too
        got = got.get("keys") or got.get("ssh_keys") or []
    out, seen = [], set()
    for row in got if isinstance(got, list) else []:
        if not isinstance(row, dict):
            continue
        parsed = parse_public(str(row.get("public_key") or ""))
        if not parsed or parsed[1] in seen:
            continue
        seen.add(parsed[1])
        title = re.sub(r"[^\w .@:+()-]", "", str(row.get("title") or parsed[2] or "")).strip()[:60]
        out.append({"type": parsed[0], "blob": parsed[1], "title": title, "fingerprint": fingerprint(parsed[1]),
                    "line": f"{parsed[0]} {parsed[1]} " + (f"{title} (Bromigos account)" if title else "Bromigos account"),
                    "created_at": row.get("created_at"), "last_used_at": row.get("last_used_at")})
    return out


# ------------------------------------------------------------------ the browser
def graphical():
    """A desktop session on this computer, where a browser can open: not over SSH."""
    if any(os.environ.get(v) for v in ("SSH_CONNECTION", "SSH_CLIENT", "SSH_TTY")):
        return False
    return bool(os.environ.get("WAYLAND_DISPLAY") or os.environ.get("DISPLAY"))


def open_browser(url):
    try:
        subprocess.Popen(["xdg-open", url], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL, start_new_session=True)
        return True
    except OSError:
        return False


# ------------------------------------------------------------------ the keyring
def _keep(rec, again):
    """Store an approved sign-in in the keyring, or say plainly that it wasn't kept and why."""
    try:
        A._save(PROVIDER, rec)
    except RuntimeError as e:
        raise LoginError(f"You approved the sign-in, but this computer couldn't keep it, so you're not signed in "
                         f"here. {_plain(e)} Then run {again} again.") from None


def _plain(e):
    """A keyring error in plain words: KeyringError already is; anything else (a GLib error
    from libsecret) goes through bromigos_keyring.explain, never printed raw."""
    if isinstance(e, A.KeyringError):
        return str(e)
    import bromigos_keyring
    return bromigos_keyring.explain(e)


def _keyring_first():
    """Before a sign-in starts: a keyring that can keep it, so the approval isn't wasted."""
    why = A.keyring_ready()
    if why:
        raise LoginError(why)


# ------------------------------------------------------------------ command line
def _who_line(st):
    who = st.get("who") or "your account"
    email = st.get("email")
    return who + (f" ({email})" if email and email != who else "")


def _how_line(st):
    return {"device": "a code on the website", "browser": "the browser", "ssh": f"the SSH key {st.get('ssh_key') or ''}".strip(),
            "token": "a personal access token", "env": "the token in BROMIGOS_TOKEN"}.get(st.get("how"), "this computer")


def _env_note(say):
    if os.environ.get("BROMIGOS_TOKEN", "").strip():
        say("Note: BROMIGOS_TOKEN is set, so bromigOS uses that token while it stays set.")


def _browser_login(say, no_browser, stdin, opener):
    """The device flow in plain words. In a desktop session, Enter opens the page; the
    sign-in finishes either way, from this computer or another one."""
    start = A.device_start(PROVIDER)
    url = start.get("verification_uri") or site() + "/device"
    full = start.get("verification_uri_complete") or url
    minutes = max(1, int(float(start.get("expires_in") or 900)) // 60)
    say("To sign in to your Bromigos account, open this page on any device:")
    say(f"    {url}")
    say("and enter this code:")
    say(f"    {start['user_code']}")
    say(f"The code works for {minutes} minutes.")
    result, stop = {}, threading.Event()

    def poll():
        try:
            result["tok"] = A.device_poll(PROVIDER, start, stop.is_set)
        except (A.SignInError, OSError, ValueError) as e:
            result["error"] = e
    t = threading.Thread(target=poll, daemon=True, name="bromigos-login")
    t.start()
    offer = not no_browser and graphical() and stdin is not None and stdin.isatty()
    if offer:
        say("Press Enter to open it in your browser, or approve it from another device. Waiting… (Ctrl+C stops)")
    else:
        say("Waiting for you to approve it… (Ctrl+C stops)")
    try:
        while t.is_alive():
            if offer:
                ready, _, _ = select.select([stdin], [], [], 0.5)
                if ready:
                    stdin.readline()
                    offer = False
                    if opener(full):
                        say("Opened it in your browser. Waiting…")
                    else:
                        say("Couldn't open a browser. Open the page yourself. Waiting…")
            else:
                t.join(0.5)
    except KeyboardInterrupt:
        stop.set()
        raise
    if "error" in result:
        raise result["error"]
    tok = result.get("tok") or {}
    if not tok.get("access_token"):
        raise A.SignInError("the account gave no token")
    rec = A._record(PROVIDER, tok)
    rec["how"] = "device"
    _keep(rec, "bromigos login")
    return A.status(PROVIDER)


def _read_token(stdin):
    if stdin.isatty():
        return getpass.getpass("Paste your personal access token (it isn't shown): ")
    return stdin.read()


def login(args, say=print, stdin=None, opener=None):
    stdin = stdin if stdin is not None else sys.stdin
    opener = opener or open_browser
    _keyring_first()
    if args.with_token:
        try:
            st = A.set_token(PROVIDER, _read_token(stdin))
        except A.SignInError as e:
            raise LoginError(f"Not stored: {e}. bromigos account token says how to make one.") from None
        say("Signed in with your personal access token. It's kept in your keyring" +
            (f", for {_who_line(st)}." if st.get("who") else "."))
        _env_note(say)
        return 0
    if args.ssh:
        key = key_from_path(args.key) if args.key else choose_key(local_keys(), say=say)
        st = ssh_sign_in(key, say=say)
    else:
        st = _browser_login(say, args.no_browser, stdin, opener)
    say(f"Signed in to your Bromigos account as {_who_line(st)}. The sign-in is kept in your keyring.")
    _env_note(say)
    return 0


def logout(args, say=print):
    st = A.status(PROVIDER)
    stored = st.get("via") == "keyring"
    A.sign_out(PROVIDER, revoke=True)
    env = bool(os.environ.get("BROMIGOS_TOKEN", "").strip())
    said = "Signed out. This computer no longer keeps your Bromigos sign-in." if stored else \
        "You weren't signed in on this computer."
    if env:
        said += " BROMIGOS_TOKEN is still set: unset it to stop using that token."
    if args.json:
        print(json.dumps({"ok": True, "said": said, **A.status(PROVIDER)}))
    else:
        say(said)
    return 0


def whoami(args, say=print):
    st = A.status(PROVIDER)
    if args.json:
        print(json.dumps({"signed_in": st["signed_in"], "who": st.get("who"), "email": st.get("email"),
                          "via": st.get("via"), "how": st.get("how"), "ssh_key": st.get("ssh_key"),
                          "site": site()}))
        return 0
    if not st["signed_in"]:
        say("Not signed in to a Bromigos account. To sign in, run: bromigos login")
        return 1
    if st.get("via") == "env":
        say("Using the personal access token in BROMIGOS_TOKEN.")
        return 0
    say(f"Signed in to your Bromigos account as {_who_line(st)}, with {_how_line(st)}.")
    return 0


def _parser(verb):
    import argparse
    if verb == "login":
        p = argparse.ArgumentParser(prog="bromigos login", description="Sign in to your Bromigos account. The "
                                    "sign-in is kept in your keyring.")
        g = p.add_mutually_exclusive_group()
        g.add_argument("--ssh", action="store_true", help="sign in with an SSH key on your account, without a browser")
        g.add_argument("--with-token", action="store_true", help="store a personal access token read from stdin "
                       "(bromigos account token says how to make one)")
        p.add_argument("--key", metavar="PATH", help="with --ssh: the key to sign with (a private key or its .pub)")
        p.add_argument("--no-browser", action="store_true", help="don't offer to open the browser")
    else:
        p = argparse.ArgumentParser(prog=f"bromigos {verb}", description={
            "logout": "Forget your Bromigos sign-in on this computer.",
            "whoami": "Show who's signed in to a Bromigos account here, and how."}[verb])
        p.add_argument("--json", action="store_true", help="print it as JSON")
    return p


def main(verb, argv):
    args = _parser(verb).parse_args(argv)
    if verb == "login" and args.key and not args.ssh:
        print("bromigos login: --key goes with --ssh", file=sys.stderr)
        return 2
    try:
        return {"login": login, "logout": logout, "whoami": whoami}[verb](args)
    except KeyboardInterrupt:
        print("\nStopped. Nothing was stored.", file=sys.stderr)
        return 130
    except (LoginError, A.SignInError, A.NeedsConfig) as e:
        print(f"bromigos {verb}: {e}", file=sys.stderr)
        return 1
    except RuntimeError as e:                      # the keyring (a GLib error is a RuntimeError too)
        print(f"bromigos {verb}: {_plain(e)}", file=sys.stderr)
        return 1
    except urllib.error.HTTPError as e:
        print(f"bromigos {verb}: the account service said HTTP {e.code}. {_said(e)}".strip(), file=sys.stderr)
        return 1
    except OSError as e:
        print(f"bromigos {verb}: couldn't reach your Bromigos account: {getattr(e, 'reason', e)}", file=sys.stderr)
        return 1
