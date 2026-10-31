"""Reach it from anywhere: how a machine is reached when it isn't on your network (docs/lab-network.md).

The installer, bromigOS Server's setup and Field Kit all ask the same question, with the same
four answers. This module holds the answers, reads a lab's join bundle, joins this machine to
the lab's private network now, and stages a join for a machine being installed. Standard library
only, so the installer's live system can import it.

    import bromigos_homelab.reach as R
    R.CHOICES                                  # the four answers, the first is the default
    bundle = R.decode(text)                    # a pasted join bundle (or the printed command)
    R.find_bundles()                           # bundles this machine was given: the Field Kit
                                               # stick's lab connection, BRODEC pairing, $BROMIGOS_REACH_BUNDLE
    R.join_now(bundle)                         # tailscale up --login-server … --auth-key file:…
    R.stage("/mnt", {"mode": "lab-network", "bundle": text}, hostname="box")
                                               # the installer: files in the new system; joins at first start

Joining never adds an exit node or subnet routes: the machine is reachable on the lab's network,
and its own traffic still goes out its own way.

    python3 -m bromigos_homelab.reach choices [--json]
    python3 -m bromigos_homelab.reach check BUNDLE [--json]
    python3 -m bromigos_homelab.reach stage --root DIR --answer FILE [--hostname NAME] [--json]
    python3 -m bromigos_homelab.reach apply --answer FILE [--json]
"""
import base64
import calendar
import ipaddress
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import time
import tomllib
import urllib.parse

PREFIX = "bromigos-net:1:"
DEFAULT = "brodec"
# BRODEC pairing hands a join bundle to a machine it pairs by writing it here (root only, 0600).
PAIRING_DROP = os.environ.get("BROMIGOS_REACH_PAIRING", "/run/bromigos/network-join")
FIELDKIT_RUN = os.environ.get("BROMIGOS_FIELDKIT_RUN", "/run/bromigos-fieldkit")
UNIT = "bromigos-reach-join.service"
KEY_PATH = "/etc/bromigos/reach/authkey"
STATE_PATH = "/etc/bromigos/reach.json"

CHOICES = [
    {"id": "brodec", "title": "Through BRODEC only", "default": True, "account": None,
     "words": "Your phone reaches this machine through BRODEC, end to end encrypted. Nothing else on the "
              "internet can reach it. The safest choice, and you can add another way later.",
     "packages": []},
    {"id": "lab-network", "title": "Join my lab's private network", "account": None, "needs": "bundle",
     "words": "This machine joins your lab's own private network, which your lab runs itself. Your other "
              "devices on that network reach it from anywhere. No outside account. It needs a join code "
              "from your lab: on the Field Kit stick, from BRODEC, or pasted.",
     "packages": ["tailscale"]},
    {"id": "wireguard", "title": "WireGuard (advanced)", "account": None, "needs": "wireguard", "advanced": True,
     "words": "Paste a WireGuard configuration you made yourself. For people who already run WireGuard: "
              "bromigOS sets up only this one connection and doesn't manage keys for you.",
     "packages": ["wireguard-tools"]},
    {"id": "tailscale", "title": "Tailscale's service", "account": "Tailscale",
     "words": "Uses Tailscale's own service. You need a Tailscale account, and Tailscale (the company) "
              "coordinates your devices. Paste an auth key from Tailscale's admin page, or sign in after "
              "the first start.",
     "packages": ["tailscale"]},
]
CHOICE = {c["id"]: c for c in CHOICES}


class BundleError(ValueError):
    """A join bundle that can't be used, in plain words."""


# ------------------------------------------------------------------ the join bundle

def _private_host(host):
    host = (host or "").strip("[]").lower()
    try:
        ip = ipaddress.ip_address(host)
        return ip.is_private or ip.is_loopback or ip.is_link_local
    except ValueError:
        return host == "localhost" or host.endswith((".local", ".lan", ".internal", ".home.arpa")) or "." not in host


def check_server(url):
    """The login server's URL, checked: HTTPS, or HTTP on a private address only. No user names,
    passwords, queries or fragments. Returns it without a trailing slash."""
    u = urllib.parse.urlsplit((url or "").strip())
    if u.scheme not in ("https", "http") or not u.hostname:
        raise BundleError("The lab network's address must start with https://")
    if u.username or u.password or u.query or u.fragment:
        raise BundleError("The lab network's address can't carry a user name, password or query")
    if u.scheme == "http" and not _private_host(u.hostname):
        raise BundleError("A lab network on the internet needs https://; plain http:// is only for your own network")
    return urllib.parse.urlunsplit((u.scheme, u.netloc, u.path.rstrip("/"), "", ""))


def check_key(key):
    key = (key or "").strip()
    if not re.fullmatch(r"[A-Za-z0-9_-]{16,200}", key):
        raise BundleError("That join code isn't complete: copy it again from your lab")
    return key


def encode(server, key, name="", tags=(), expires=""):
    """A join bundle: what `bromigos lab network join` prints and its QR code carries."""
    doc = {"v": 1, "server": check_server(server), "key": check_key(key)}
    if name:
        doc["name"] = name
    if tags:
        doc["tags"] = list(tags)
    if expires:
        doc["expires"] = expires
    raw = json.dumps(doc, separators=(",", ":"), sort_keys=True).encode()
    return PREFIX + base64.urlsafe_b64encode(raw).decode().rstrip("=")


def decode(text):
    """A join bundle from a paste: the bundle itself, or the command `join` prints
    (tailscale up --login-server URL --auth-key KEY). Raises BundleError in plain words."""
    text = (text or "").strip()
    if not text:
        raise BundleError("Paste the join code from your lab first")
    m = re.search(re.escape(PREFIX) + r"([A-Za-z0-9_-]+)", text)
    if m:
        body = m.group(1)
        try:
            doc = json.loads(base64.urlsafe_b64decode(body + "=" * (-len(body) % 4)))
        except (ValueError, UnicodeDecodeError):
            raise BundleError("That join code is damaged: copy it again from your lab") from None
        if not isinstance(doc, dict) or doc.get("v") != 1:
            raise BundleError("That join code is from a newer bromigOS: update this machine first")
        out = {"server": check_server(doc.get("server")), "key": check_key(doc.get("key")),
               "name": str(doc.get("name") or ""), "tags": [str(t) for t in doc.get("tags") or []],
               "expires": str(doc.get("expires") or "")}
    else:
        try:
            words = shlex.split(text)
        except ValueError:
            words = text.split()
        opts = {}
        for i, w in enumerate(words):
            for flag in ("--login-server", "--auth-key", "--authkey"):
                if w == flag and i + 1 < len(words):
                    opts[flag] = words[i + 1]
                elif w.startswith(flag + "="):
                    opts[flag] = w.split("=", 1)[1]
        if "--login-server" not in opts or not (opts.get("--auth-key") or opts.get("--authkey")):
            raise BundleError("That isn't a join code. In your lab: bromigos lab network join")
        out = {"server": check_server(opts["--login-server"]), "key": check_key(opts.get("--auth-key") or opts["--authkey"]),
               "name": "", "tags": [], "expires": ""}
    if out["expires"]:
        try:
            when = calendar.timegm(time.strptime(out["expires"][:19], "%Y-%m-%dT%H:%M:%S"))
        except (ValueError, OverflowError):
            when = None                            # an unreadable date: the lab decides
        if when is not None and when < time.time():
            raise BundleError("That join code has expired. Make a new one: bromigos lab network join")
    return out


def describe(bundle):
    """One line about a decoded bundle, for a screen."""
    host = urllib.parse.urlsplit(bundle["server"]).hostname
    bits = [bundle.get("name") or "your lab's network", f"at {host}"]
    if bundle.get("tags"):
        bits.append("as " + ", ".join(t.removeprefix("tag:") for t in bundle["tags"]))
    if bundle.get("expires"):
        bits.append("code valid until " + bundle["expires"][:16].replace("T", " ") + " UTC")
    return " · ".join(bits)


def _toml_bundle(path):
    try:
        with open(path, "rb") as f:
            net = tomllib.load(f).get("network") or {}
    except (OSError, tomllib.TOMLDecodeError):
        return ""
    return str(net.get("join_bundle") or "")


def find_bundles():
    """Join bundles this machine was given, best first: [(where, text)]. Only ones that decode."""
    home = os.path.expanduser("~")
    places = [("given to this command", os.environ.get("BROMIGOS_REACH_BUNDLE", ""))]
    try:
        with open(PAIRING_DROP) as f:
            places.append(("from BRODEC pairing", f.read()))
    except OSError:
        pass
    config = os.environ.get("XDG_CONFIG_HOME") or os.path.join(home, ".config")
    for where, path in (("from your lab connection", os.environ.get("BROMIGOS_HOMELAB_CONFIG") or
                         os.path.join(config, "bromigos", "homelab.toml")),
                        ("from the Field Kit stick's lab connection", "/root/.config/bromigos/homelab.toml"),
                        ("from the Field Kit stick", os.path.join(FIELDKIT_RUN, "stick", "fieldkit", "homelab.toml"))):
        places.append((where, _toml_bundle(path)))
    out, seen = [], set()
    for where, text in places:
        if not text or text in seen:
            continue
        seen.add(text)
        try:
            decode(text)
        except BundleError:
            continue
        out.append((where, text.strip()))
    return out


# ------------------------------------------------------------------ joining this machine now

def tailscale_cmd():
    return shlex.split(os.environ.get("BROMIGOS_TAILSCALE") or "tailscale")


def up_args(bundle, key_ref, hostname=None, force=False):
    """`tailscale up`'s arguments for a bundle. No exit node, no subnet routes, nothing accepted
    from other machines' routes; --reset so settings from an earlier network don't carry over."""
    args = ["up", "--reset", "--login-server=" + bundle["server"], "--auth-key=" + key_ref,
            "--accept-routes=false", "--exit-node=", "--advertise-exit-node=false", "--advertise-routes="]
    if hostname:
        args.append("--hostname=" + re.sub(r"[^A-Za-z0-9-]", "-", hostname)[:63].strip("-"))
    if force:
        args.append("--force-reauth")
    return args


def _elevate():
    if os.environ.get("BROMIGOS_TAILSCALE") or os.geteuid() == 0:
        return []
    return ["sudo"] if sys.stdin.isatty() else ["pkexec"]


def join_now(bundle, hostname=None, force=False, run=subprocess.run, timeout=90):
    """Join this machine to the lab's network: tailscaled on, then tailscale up with the key in a
    0600 file (never on a command line). Returns {"ok", "words", "ip"}."""
    if isinstance(bundle, str):
        bundle = decode(bundle)
    root = _elevate()
    ts = tailscale_cmd()
    if not os.environ.get("BROMIGOS_TAILSCALE"):
        if not shutil.which("tailscale"):
            return {"ok": False, "words": "This machine needs the tailscale package first: sudo pacman -S tailscale"}
        if run(["systemctl", "is-active", "--quiet", "tailscaled"], check=False).returncode != 0:
            r = run(root + ["systemctl", "enable", "--now", "tailscaled.service"], check=False)
            if r.returncode != 0:
                return {"ok": False, "words": "Couldn't start tailscaled (the network's service on this machine)."}
    keydir = os.environ.get("BROMIGOS_REACH_KEYDIR") or None
    fd, path = tempfile.mkstemp(prefix="reach-", dir=keydir)
    try:
        with os.fdopen(fd, "w") as f:
            f.write(bundle["key"])
        os.chmod(path, 0o600)
        r = run(root + ts + up_args(bundle, "file:" + path, hostname, force), capture_output=True, text=True,
                check=False, timeout=timeout)
    except subprocess.TimeoutExpired:
        return {"ok": False, "words": "The lab's network didn't answer in time. Check this machine's internet "
                                      "connection, and that the address in the join code is reachable from here."}
    finally:
        os.unlink(path)
    out = (r.stdout or "") + (r.stderr or "")
    if r.returncode != 0:
        if "force-reauth" in out:
            return {"ok": False, "needs_force": True,
                    "words": "This machine is already on another network. Join again with --force to leave it "
                             "(it drops that connection, so don't do it over that network)."}
        if re.search(r"invalid key|expired|not valid|already used|authkey", out, re.I):
            return {"ok": False, "words": "Your lab didn't accept the join code: it's used or expired. "
                                          "Make a new one: bromigos lab network join"}
        return {"ok": False, "words": "Joining didn't finish: " + (out.strip().splitlines() or ["no answer"])[-1][:200]}
    ip = run(root + ts + ["ip", "-4"], capture_output=True, text=True, check=False)
    addr = (ip.stdout or "").strip().splitlines()[0] if ip.returncode == 0 and (ip.stdout or "").strip() else ""
    return {"ok": True, "ip": addr, "words": "This machine is on your lab's network" + (f" as {addr}." if addr else ".")}


# ------------------------------------------------------------------ the installer: a join at first start

def check_wireguard(text):
    text = (text or "").strip()
    if not re.search(r"^\s*\[Interface\]", text, re.M) or not re.search(r"^\s*PrivateKey\s*=", text, re.M):
        raise BundleError("A WireGuard configuration needs an [Interface] with its PrivateKey")
    if not re.search(r"^\s*\[Peer\]", text, re.M):
        raise BundleError("A WireGuard configuration needs at least one [Peer]")
    if re.search(r"^\s*(PreUp|PostUp|PreDown|PostDown)\s*=", text, re.M | re.I):
        raise BundleError("This WireGuard configuration runs commands (PostUp and the like); remove those lines first")
    return text + "\n"


def _write(root, path, text, mode):
    dest = os.path.join(root, path.lstrip("/"))
    os.makedirs(os.path.dirname(dest), mode=0o755, exist_ok=True)
    fd = os.open(dest, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, mode)
    with os.fdopen(fd, "w") as f:
        f.write(text)
    os.chmod(dest, mode)
    return path


def _enable(root, unit, target="multi-user.target", source=None):
    wants = os.path.join(root, "etc/systemd/system", target + ".wants")
    os.makedirs(wants, exist_ok=True)
    link = os.path.join(wants, unit)
    if os.path.lexists(link):
        os.unlink(link)
    os.symlink(source or "/usr/lib/systemd/system/" + unit, link)
    return unit


def join_unit(server=None, hostname=None):
    """The first-start unit: joins once, then removes the key whether or not it worked (a used or
    expired key is no good again; the user makes a new one)."""
    args = up_args({"server": server} if server else {"server": ""}, "file:" + KEY_PATH, hostname)
    if not server:
        args = [a for a in args if not a.startswith("--login-server=")]
    return ("[Unit]\n"
            "Description=Join the lab's private network, once (bromigos: Reach it from anywhere)\n"
            "Wants=network-online.target tailscaled.service\n"
            "After=network-online.target tailscaled.service\n"
            f"ConditionPathExists={KEY_PATH}\n\n"
            "[Service]\n"
            "Type=oneshot\n"
            f"ExecStart=/usr/bin/tailscale {shlex.join(args)}\n"
            f"ExecStopPost=/usr/bin/rm -f {KEY_PATH}\n"
            "TimeoutStartSec=180\n\n"
            "[Install]\n"
            "WantedBy=multi-user.target\n")


def stage(root, answer, hostname=None):
    """Write the answer into a system being installed at root: the installer calls this after
    copying the system and before it unmounts. answer = {"mode": a CHOICES id, "bundle": text,
    "wireguard": text, "tailscale_key": text}. Returns {"mode", "packages", "files", "enabled",
    "words"}; the packages must be in the install (CHOICE[mode]["packages"])."""
    mode = (answer or {}).get("mode") or DEFAULT
    if mode not in CHOICE:
        raise BundleError(f"Unknown choice: {mode}")
    files, enabled, state = [], [], {"mode": mode}
    if mode == "lab-network":
        b = decode(answer.get("bundle"))
        files.append(_write(root, KEY_PATH, b["key"] + "\n", 0o600))
        files.append(_write(root, "/etc/systemd/system/" + UNIT, join_unit(b["server"], hostname), 0o644))
        enabled += [_enable(root, "tailscaled.service"), _enable(root, UNIT, source="/etc/systemd/system/" + UNIT)]
        state.update(login_server=b["server"], name=b.get("name") or "")
        words = f"Joins {describe(b)} at its first start."
    elif mode == "wireguard":
        files.append(_write(root, "/etc/wireguard/wg0.conf", check_wireguard(answer.get("wireguard")), 0o600))
        enabled.append(_enable(root, "wg-quick@wg0.service", source="/usr/lib/systemd/system/wg-quick@.service"))
        words = "Starts the WireGuard connection wg0 at every start."
    elif mode == "tailscale":
        enabled.append(_enable(root, "tailscaled.service"))
        key = (answer.get("tailscale_key") or "").strip()
        if key:
            files.append(_write(root, KEY_PATH, check_key(key) + "\n", 0o600))
            files.append(_write(root, "/etc/systemd/system/" + UNIT, join_unit(None, hostname), 0o644))
            enabled.append(_enable(root, UNIT, source="/etc/systemd/system/" + UNIT))
            words = "Signs in to your Tailscale account with the key at its first start."
        else:
            words = "After the first start, run sudo tailscale up and sign in to your Tailscale account."
    else:
        words = "Reached through BRODEC only."
    os.makedirs(os.path.join(root, "etc/bromigos"), exist_ok=True)
    files.append(_write(root, STATE_PATH, json.dumps(state, indent=1) + "\n", 0o644))
    return {"mode": mode, "packages": CHOICE[mode]["packages"], "files": files, "enabled": enabled, "words": words}


def apply(answer, hostname=None, run=subprocess.run):
    """The same answer on a running machine (bromigOS Server's setup, Field Kit's Server › Network)."""
    mode = (answer or {}).get("mode") or DEFAULT
    if mode == "lab-network":
        return join_now(answer.get("bundle"), hostname, force=bool(answer.get("force")), run=run)
    if mode == "wireguard":
        conf = check_wireguard(answer.get("wireguard"))
        root = _elevate()
        r = run(root + ["install", "-D", "-m", "0600", "/dev/stdin", "/etc/wireguard/wg0.conf"], input=conf,
                text=True, check=False)
        if r.returncode == 0:
            r = run(root + ["systemctl", "enable", "--now", "wg-quick@wg0.service"], check=False)
        return {"ok": r.returncode == 0, "words": "WireGuard's wg0 is on." if r.returncode == 0 else
                "WireGuard didn't start: journalctl -u wg-quick@wg0 says why."}
    if mode == "tailscale":
        root = _elevate()
        run(root + ["systemctl", "enable", "--now", "tailscaled.service"], check=False)
        r = run(root + tailscale_cmd() + ["up", "--accept-routes=false", "--exit-node="], check=False)
        return {"ok": r.returncode == 0, "words": "Signed in to Tailscale's service." if r.returncode == 0 else
                "Tailscale's sign-in didn't finish."}
    return {"ok": True, "words": "Reached through BRODEC only: nothing to change."}


# ------------------------------------------------------------------ the command line

def choose(say=print, ask=input):
    """The question in a terminal: Field Kit's Server › Network and bromigOS Server's setup."""
    say("Reach it from anywhere\n")
    for n, c in enumerate(CHOICES, 1):
        say(f"  {n}. {c['title']}" + ("  (the default)" if c.get("default") else "")
            + (f"  needs a {c['account']} account" if c.get("account") else ""))
        say("     " + c["words"] + "\n")
    pick = (ask("Choose 1-4 (Enter for 1): ").strip() or "1")
    if pick not in ("1", "2", "3", "4"):
        say("Nothing changed.")
        return {"mode": DEFAULT}
    c = CHOICES[int(pick) - 1]
    answer = {"mode": c["id"]}
    if c["id"] == "lab-network":
        found = find_bundles()
        if found:
            where, text = found[0]
            say(f"A join code {where}: {describe(decode(text))}")
            if ask("Use it? [Y/n] ").strip().lower() in ("", "y", "yes"):
                answer["bundle"] = text
        if "bundle" not in answer:
            answer["bundle"] = ask("Paste the join code (bromigos lab network join, in your lab): ").strip()
    elif c["id"] == "wireguard":
        say("Paste the WireGuard configuration, then an empty line:")
        lines = []
        while True:
            line = ask("")
            if not line.strip():
                break
            lines.append(line)
        answer["wireguard"] = "\n".join(lines)
    return answer


def main(argv=None):
    import argparse
    p = argparse.ArgumentParser(prog="python3 -m bromigos_homelab.reach", description="Reach it from anywhere")
    sub = p.add_subparsers(dest="verb", required=True)
    s = sub.add_parser("choices")
    s.add_argument("--json", action="store_true")
    s = sub.add_parser("check")
    s.add_argument("bundle", nargs="?")
    s.add_argument("--json", action="store_true")
    s = sub.add_parser("found")
    s.add_argument("--json", action="store_true")
    for name in ("stage", "apply"):
        s = sub.add_parser(name)
        s.add_argument("--answer", required=name == "stage", help="a JSON file: {mode, bundle, wireguard, tailscale_key}")
        s.add_argument("--hostname")
        s.add_argument("--json", action="store_true")
        if name == "stage":
            s.add_argument("--root", required=True)
    a = p.parse_args(argv)
    try:
        if a.verb == "choices":
            print(json.dumps(CHOICES, indent=1) if a.json else "\n".join(f"{c['id']:<12} {c['title']}" for c in CHOICES))
            return 0
        if a.verb == "found":
            found = [{"where": w, "summary": describe(decode(t)), "bundle": t} for w, t in find_bundles()]
            print(json.dumps(found, indent=1) if a.json else "\n".join(f"{f['where']}: {f['summary']}" for f in found)
                  or "No join code on this machine.")
            return 0
        if a.verb == "check":
            b = decode(a.bundle if a.bundle is not None else sys.stdin.read())
            print(json.dumps({"ok": True, "server": b["server"], "name": b["name"], "tags": b["tags"],
                              "expires": b["expires"], "summary": describe(b)}) if a.json else describe(b))
            return 0
        if a.answer:
            with open(a.answer) as f:
                answer = json.load(f)
        else:
            answer = choose()
        result = stage(a.root, answer, a.hostname) if a.verb == "stage" else apply(answer, a.hostname)
        print(json.dumps(result, indent=1) if a.json else result["words"])
        return 0 if result.get("ok", True) else 1
    except BundleError as e:
        print(json.dumps({"ok": False, "words": str(e)}) if getattr(a, "json", False) else str(e), file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
