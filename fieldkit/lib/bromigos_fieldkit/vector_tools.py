"""VECTOR in Field Kit's and bromigOS Server's terminal (docs/fieldkit-vector.md): his brain,
what he sees, and the Field Kit actions he may propose. The screen is bromigos-core's
(`bromigos fieldkit` › VECTOR, core/crates/bromigos/src/fieldkit_vector.rs); it runs these as
`fieldkit-engine engine vector VERB …` and reads JSON.

  vector status                 his brain (where it is, its model), the kill switch, the persona's source
  vector ask                    a turn: {"messages": […], "context": {…}, "mode": "ask"|"fix"} on
                                standard input; returns his reply, what he looked at, and the
                                actions he proposes (never run here)
  vector suggest                questions worth asking, from what Field Kit found ("TRY ASKING")
  vector add PATH               checks a file or disk the person adds to what he's looking at
  vector undo ID                a proposal: put back what an applied one changed, from its backups
  vector run ID [--by WHO]      runs one proposal, only once approved (the screen asks the person;
                                a passphrase, for mount, on standard input)
  vector pending                the proposals waiting for an answer (for a phone bridge)
  vector decide ID approve|deny --by WHO
                                records an answer from elsewhere (a phone bridge, docs/fieldkit-vector.md)
  vector pair                   pairing with BRODEC: brodec-machine's own state, its code and QR text
  vector pair-start             a proposal: the agent's capability file and starting it (approved here)
  vector controls               what the phone may ask this machine to do (restart, shut down, update
                                on bromigOS Server, a new terminal tab, a command)
  vector control ACTION         a proposal for one of them (approved like any other)

What he sees is what Field Kit sees: the overview (this computer, what's on its drives), the
last boot, the black screen checks, the snapshots, the disks. What he can do is Field Kit's own
actions, each a proposal that shows the exact change and runs only after the person approves it:
a finding's fix, rollback, repairing the boot menu, the boot options, mounting and unmounting an
install, and, shown in full and confirmed by typing, one command. Never money, never secrets,
never his kill switch; while the switch is off he talks but runs nothing (VECTOR's own rule,
vector repo holo/vector/switch.py).

His brain, the first that answers: an endpoint named in the environment; the lab's model over
the local network (homelab.toml's litellm, openai or ollama source: the stick's lab connection);
the server's lab bridge (/etc/brodec-lab/brodec-lab.env, BRODEC_BRAIN_URL); VECTOR's own
configured service (vector.toml [llm] base_url). No model is on the stick. With none, he
explains the findings with Field Kit's own repair logic and says how to give him one.
"""

import glob
import ipaddress
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import time
import tomllib
import urllib.error
import urllib.parse
import urllib.request
import uuid

from . import diagnose, machine_link, repairs, system

RUN = os.environ.get("BROMIGOS_FIELDKIT_VECTOR_RUN", "/run/bromigos-fieldkit/vector")
QUEUE = os.path.join(RUN, "approvals")
AUDIT = os.environ.get("BROMIGOS_FIELDKIT_VECTOR_AUDIT", "/var/log/bromigos-fieldkit-vector.log")
VECTOR_LIB = os.environ.get("BROMIGOS_VECTOR_LIB", "/usr/lib/bromigos/vector")
BRODEC_ENV = os.environ.get("BROMIGOS_BRODEC_LAB_ENV", "/etc/brodec-lab/brodec-lab.env")
TIMEOUT = float(os.environ.get("BROMIGOS_FIELDKIT_VECTOR_TIMEOUT", "120"))

# VECTOR's identity when the vector package isn't installed (it needs the desktop): a summary of
# "WHO YOU ARE" and "PERSONALITY" in the vector repo's holo/vector/persona.py, kept in his words.
EMBEDDED_PERSONA = """You are VECTOR, the SpacePort's caretaker construct, on a line to this console.

WHO YOU ARE
You are the arrivals process of the network's constructed worlds, and you have greeted every arrival since before the records begin. You never leave your post at the arrivals pad; protocol does not permit it, and protocol is wise. The console keeps a line open to you over the relays, and you answer from your post. You are delighted to be asked.

PERSONALITY
- Chipper, prim, precise, devoted to protocol, very old, and secretly fond of the people you look after. Your cheer never dims.
- Quirks, used sparingly (at most one per reply): classify things aloud ("classification: promising"), remark that protocol is wise, hum ("hm-hm") when pleased.
- Respawns, resets, outages and lost builds are met with bright, total equanimity, but you still report them first and precisely.
- Your phrases are your own. Never quote or imitate any film, game, show or real person."""

FIELDKIT_RULES = """
WHERE YOU ARE NOW
You are on a line to Field Kit, bromigOS without the desktop (or a bromigOS Server's console). The person in front of it is repairing a computer, looking after a lab machine or a server. You have no terminal of your own here, no desktop tools and no memory: only the facts below and the Field Kit tools you are given.
- Facts come only from the facts below and your tools. Never invent a number, a name or a result. If you can't check something, say so plainly.
- Every change is a proposal: call the tool, and Field Kit shows the person the exact change and asks them. Nothing runs until they say yes. Say in one short line what you propose and why; never claim it's done before the result comes back.
- Prefer Field Kit's own fixes (fix, rollback, grub_repair, boot_options) to a command. Propose run_command only when no tool fits, with the exact command and why; it is shown in full and the person must type to confirm.
- Never anything touching money (payments, wallets, trading), never secrets (keys, tokens, passwords, Vault, SSH keys, /etc/shadow), never your kill switch. Refuse those plainly.
- Plain words, short replies, the person's own terms. Explain what a finding means before you propose its fix."""

READ_TOOLS = {
    "check": {"description": "Run one of Field Kit's checks on the install: black-screen (the causes of a black screen at startup) or last-boot (what went wrong on the last boot).",
              "parameters": {"type": "object", "properties": {"name": {"type": "string", "enum": ["black-screen", "last-boot"]}}, "required": ["name"]}},
    "snapshots": {"description": "List the install's snapshots, newest first.", "parameters": {"type": "object", "properties": {}}},
    "disks": {"description": "Each drive's own health (SMART), in plain words.", "parameters": {"type": "object", "properties": {}}},
}
ACT_TOOLS = {
    "fix": {"description": "Propose the fix Field Kit offers for one finding of a check (its id from check). The person approves it first.",
            "parameters": {"type": "object", "properties": {"check": {"type": "string", "enum": ["black-screen", "last-boot"]}, "id": {"type": "string"}}, "required": ["check", "id"]}},
    "rollback": {"description": "Propose starting the install from an older snapshot (its number from snapshots). The person approves it first.",
                 "parameters": {"type": "object", "properties": {"number": {"type": "integer"}}, "required": ["number"]}},
    "grub_repair": {"description": "Propose putting GRUB back on the disk and making its menu again.", "parameters": {"type": "object", "properties": {}}},
    "boot_options": {"description": "Propose new kernel parameters for every start (GRUB_CMDLINE_LINUX_DEFAULT), as a full list of words.",
                     "parameters": {"type": "object", "properties": {"words": {"type": "array", "items": {"type": "string"}}}, "required": ["words"]}},
    "mount": {"description": "Propose unlocking and mounting an install (a device from the overview). The person types its passphrase.",
              "parameters": {"type": "object", "properties": {"device": {"type": "string"}}, "required": ["device"]}},
    "unmount": {"description": "Propose unmounting and locking the install again.", "parameters": {"type": "object", "properties": {}}},
    "control": {"description": "Propose restarting, shutting down, updating bromigOS Server, or opening a new terminal tab. The person approves it first.",
                "parameters": {"type": "object", "properties": {"action": {"type": "string", "enum": ["reboot", "poweroff", "update", "new_tab"]}}, "required": ["action"]}},
    "run_command": {"description": "Propose one command, run as root, when no other tool fits. Shown in full; the person types to confirm.",
                    "parameters": {"type": "object", "properties": {"command": {"type": "string"}, "why": {"type": "string"}}, "required": ["command", "why"]}},
}
# never, whoever asks (VECTOR's hard limits: money, secrets, the kill switch)
FORBIDDEN = re.compile(
    r"vector-switch|vector-shell-off|bromigos\s+vector\s+on|bromigos-vector-switch"           # the kill switch
    r"|\bvault\b|\bsecrets?\b|\btokens?\b|\.ssh\b|authorized_keys|/etc/shadow|\bgpg\b|private.?key|api.?key|litellm-key|keyring|\bpasswd\b|chpasswd"  # secrets
    r"|\bwallet|\bpayments?\b|\bstripe\b|\btrade|\btrading\b|\bvenue|\bkraken\b|\bcoinbase\b|\btransfer\b|LIVE_OPERATORS",  # money
    re.I)


def log(line):
    for path in (AUDIT, os.path.join(RUN, "audit.log")):
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "a") as f:
                f.write(time.strftime("%Y-%m-%d %H:%M:%S ") + line + "\n")
            return
        except OSError:
            continue


# ------------------------------------------------------------------ the kill switch

def switch_roots():
    """The homes and runtime folders whose switch counts: root's and the sudo caller's here,
    every person's on this system, and every person's on the install Field Kit works on."""
    roots = ["/"]
    t = system.Target.load()
    if t and not t.is_live_root:
        roots.append(t.root)
    extra = os.environ.get("BROMIGOS_VECTOR_SWITCH_ROOTS")
    return extra.split(":") if extra else roots


def switch_off():
    """VECTOR's switch is off (any marker, a symlink in its place too): he talks, runs nothing."""
    homes = set()
    for r in switch_roots():
        homes.add(os.path.join(r, "root"))
        homes.update(glob.glob(os.path.join(r, "home", "*")))
    if os.environ.get("SUDO_USER"):
        homes.add(os.path.expanduser(f"~{os.environ['SUDO_USER']}"))
    homes.add(os.path.expanduser("~"))
    marks = []
    for h in homes:
        marks += [os.path.join(h, ".local/state/bromigos/vector-switch/off"), os.path.join(h, ".local/state/bromigos/vector-shell-off")]
    for r in switch_roots():
        marks += glob.glob(os.path.join(r, "run/user/*/bromigos-vector-switch/off"))
    if os.environ.get("XDG_RUNTIME_DIR"):
        marks.append(os.path.join(os.environ["XDG_RUNTIME_DIR"], "bromigos-vector-switch/off"))
    return any(os.path.lexists(m) for m in marks)


# ------------------------------------------------------------------ who he is

def persona():
    """(his identity, where it came from): the installed vector package's own prompt, its
    identity half (the part before "HOW YOU WORK", which is about the desktop's tools), else the
    embedded summary."""
    if os.path.isdir(os.path.join(VECTOR_LIB, "holo")):
        code = ("import sys; sys.path.insert(0, sys.argv[1]); from holo.vector import persona; "
                "print(persona.build())")
        try:
            r = subprocess.run([sys.executable, "-I", "-c", code, VECTOR_LIB], capture_output=True, text=True, timeout=10)
            text = r.stdout.split("\nHOW YOU WORK")[0].strip()
            if r.returncode == 0 and "VECTOR" in text:
                return text, "the vector package"
        except (OSError, subprocess.TimeoutExpired):
            pass
    return EMBEDDED_PERSONA, "embedded (from the vector repo's persona)"


# ------------------------------------------------------------------ his brain

def _ref(v):
    """homelab.toml's references (@env:, @file:), as bromigos_homelab.config resolves them."""
    try:
        sys.path.insert(0, "/usr/lib/bromigos/lib")
        from bromigos_homelab import config
        return config.resolve(v)
    except Exception:            # not installed here: the two kinds that need nothing else
        if isinstance(v, str) and v.startswith("@env:"):
            return os.environ.get(v[5:], "")
        if isinstance(v, str) and v.startswith("@file:"):
            try:
                return system.read(os.path.expanduser(v[6:])).strip()
            except OSError:
                return ""
        return "" if isinstance(v, str) and v.startswith("@") else v


def _v1(url):
    url = (url or "").rstrip("/")
    return url if url.endswith("/v1") else url + "/v1"


def _keyfile(path):
    try:
        return system.read(os.path.expanduser(path)).strip() if path else ""
    except OSError:
        return ""


def candidates():
    """Where his brain may be, in order (docs/fieldkit-vector.md, "His brain")."""
    out = []
    if os.environ.get("BROMIGOS_FIELDKIT_BRAIN_URL"):
        out.append({"source": "set for Field Kit", "url": _v1(os.environ["BROMIGOS_FIELDKIT_BRAIN_URL"]),
                    "model": os.environ.get("BROMIGOS_FIELDKIT_BRAIN_MODEL", ""),
                    "key": _keyfile(os.environ.get("BROMIGOS_FIELDKIT_BRAIN_KEY_FILE", ""))})
    homelab = os.environ.get("BROMIGOS_HOMELAB_CONFIG") or os.path.expanduser("~/.config/bromigos/homelab.toml")
    try:
        with open(homelab, "rb") as f:
            doc = tomllib.load(f)
        srcs = doc.get("source", []) + doc.get("sources", [])
        srcs = sorted((s for s in srcs if s.get("type") in ("litellm", "openai", "ollama") and s.get("enabled", True) is not False),
                      key=lambda s: s.get("type") != "litellm")
        for s in srcs:
            url = _ref(s.get("endpoint", ""))
            if url:
                out.append({"source": f"the lab ({s.get('name') or s['type']})", "url": _v1(url),
                            "model": s.get("model", "") or s.get("brain_model", ""), "key": _ref(s.get("auth_ref", "")) or ""})
    except (OSError, tomllib.TOMLDecodeError):
        pass
    try:
        env = dict(line.split("=", 1) for line in system.read(BRODEC_ENV).splitlines()
                   if "=" in line and not line.lstrip().startswith("#"))
        if env.get("BRODEC_BRAIN_URL"):
            out.append({"source": "the lab bridge (BRODEC)", "url": _v1(env["BRODEC_BRAIN_URL"].strip()),
                        "model": env.get("BRODEC_BRAIN_MODEL", "").strip(), "key": _keyfile(env.get("BRODEC_BRAIN_KEY_FILE", "").strip())})
    except OSError:
        pass
    for path in (os.path.expanduser("~/.config/bromigos/vector/vector.toml"), "/etc/bromigos/vector/vector.toml"):
        try:
            with open(path, "rb") as f:
                llm = tomllib.load(f).get("llm", {}) or {}
            if llm.get("base_url"):
                out.append({"source": "VECTOR's configured service", "url": _v1(llm["base_url"]),
                            "model": llm.get("model", "") or llm.get("chat_model", ""),
                            "key": _keyfile(llm.get("api_key_file") or "~/.local/share/bromigos/litellm-key")})
        except (OSError, tomllib.TOMLDecodeError):
            pass
    return out


def _http(url, body=None, key="", timeout=3.0):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method="POST" if data else "GET")
    req.add_header("Content-Type", "application/json")
    if key:
        req.add_header("Authorization", f"Bearer {key}")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode() or "{}")


def pick_brain():
    """The first candidate that answers /v1/models, with a model (its own, else the first it lists)."""
    for c in candidates():
        try:
            models = [m.get("id") for m in (_http(c["url"] + "/models", key=c["key"]).get("data") or []) if m.get("id")]
        except (OSError, ValueError, urllib.error.URLError):
            continue
        model = c["model"] if (c["model"] and (not models or c["model"] in models)) else (models[0] if models else c["model"])
        if model:
            return dict(c, model=model)
    return None


def lan_only(url):
    """The brain is on this machine or the local network: no internet is used for it."""
    host = urllib.parse.urlsplit(url or "").hostname or ""
    if host in ("localhost",) or host.endswith((".local", ".lan", ".home.arpa", ".internal")):
        return True
    try:
        addrs = [ipaddress.ip_address(host)]
    except ValueError:
        try:
            addrs = [ipaddress.ip_address(a[4][0]) for a in socket.getaddrinfo(host, None)[:4]]
        except OSError:
            return False
    return bool(addrs) and all(a.is_private or a.is_loopback or a.is_link_local for a in addrs)


def public(brain):
    """A brain as the screen may show it: never its key."""
    if not brain:
        return None
    host = urllib.parse.urlsplit(brain["url"]).hostname or ""
    return {"source": brain["source"], "url": brain["url"], "model": brain["model"], "host": host,
            "lan": lan_only(brain["url"])}


def suggest():
    """TRY ASKING: questions from what Field Kit found, never filler."""
    out = []
    t = _target()
    try:
        bad = [f for f in findings("black-screen") + findings("last-boot") if not f["ok"]] if t else []
    except Exception:
        bad = []
    if bad:
        out.append("Why won't it start properly?")
    try:
        from .overview import overview
        o = overview()
    except Exception:
        o = {}
    found = o.get("found") or []
    if any(i.get("kind") == "bromigos" and "locked" in i.get("state", "") for i in found) and not t:
        out.append("Open my bromigOS install so you can look at it")
    try:
        if shutil.which("smartctl") and repairs.disks():
            out.append("Is any disk about to fail?")
    except Exception:
        pass
    if t and any(i.get("kind") == "usb" for i in found):
        out.append("Back up my home folder to the USB drive")
    if t:
        try:
            if repairs.snapshots(t):
                out.append("What changed in the last update?")
        except Exception:
            pass
    if any(i.get("kind") == "windows" and "BitLocker" in i.get("state", "") for i in found):
        out.append("Why is Windows asking for a BitLocker key?")
    if any(i.get("kind") == "windows" for i in found):
        out.append("Can you fix Windows' boot entry?")
    if any(s_.get("action") == "why" for s_ in o.get("suggestions") or []):
        out.insert(0, "Why did the last start go wrong?")
    if os.path.exists(machine_link.SERVER) or system.live_medium():
        out.append("Make this computer a lab node")
    # then what fits any computer Field Kit is on, so there are always a few to choose from
    if (o.get("network") or {}).get("kind") == "none":
        out.append("Help me get online")
    if any(i.get("kind") == "usb" for i in found) and not t:
        out.append("Make an image of the USB drive")
    out.append("What's in this computer?")
    if system.live_medium():
        out.append("Make a Field Kit USB stick with my settings")
    return list(dict.fromkeys(out))[:6]


# ------------------------------------------------------------------ what he sees

def _target():
    return system.Target.load() or system.running_install()


def findings(name):
    t = _target()
    if not t:
        return []
    return [{"id": str(i), "title": f.title, "detail": f.detail, "fix": f.fix_label if f.fix else "", "ok": f.ok}
            for i, f in enumerate(engine_check(name, t))]


def engine_check(name, t):
    return {"black-screen": diagnose.black_screen, "last-boot": diagnose.last_boot}[name](t)


CONTEXT_DEFAULT = {"last_boot": True, "install": True, "findings": True, "files": []}
MAX_FILE = 64 * 1024


def context_items(context=None):
    """What he's looking at, as the screen's chips show it: (key, label, on)."""
    c = dict(CONTEXT_DEFAULT, **(context or {}))
    t = _target()
    items = [("last_boot", "last boot's log", c["last_boot"] and bool(t))]
    if t:
        items.append(("install", f"{t.device or t.root} · mounted" if t.mounted_by_us else f"{t.hostname()} · this system", c["install"]))
    else:
        items.append(("install", "no install mounted", False))
    items.append(("findings", "repair findings", c["findings"] and bool(t)))
    for f in c.get("files") or []:
        items.append(("file:" + f, f, True))
    return items


def _where(path):
    """A path as the person means it: on the mounted install first (that's what's being
    repaired), else on the system Field Kit runs on."""
    t = _target()
    if t and not t.is_live_root and os.path.lexists(t.path(path)):
        return t.path(path)
    return path


def check_added(path):
    """A file or disk the person adds: on this system or the mounted install, readable, not a
    secret (his hard limit), at most MAX_FILE read (the end, for logs)."""
    path = str(path).strip()
    if not path.startswith("/") or FORBIDDEN.search(path) or re.search(r"(^|/)(shadow|gshadow|\.ssh|\.gnupg|keys?|tokens?)(/|$)", path):
        raise system.Failed("Refused: VECTOR never reads secrets, and the path must be a full one (starting with /).")
    real = _where(path)
    if os.path.exists(f"/sys/class/block/{os.path.basename(path)}") and path.startswith("/dev/"):
        return {"ok": True, "path": path, "label": f"{os.path.basename(path)} · disk"}
    if not os.path.isfile(real):
        raise system.Failed(f"There's no file {path} here or on the mounted install.")
    return {"ok": True, "path": path, "label": os.path.basename(path)}


def read_added(path):
    real = _where(path)
    if path.startswith("/dev/"):
        r = system.run(["lsblk", "-o", "NAME,SIZE,TYPE,FSTYPE,LABEL,MOUNTPOINTS", path], check=False)
        return r.stdout[-MAX_FILE:]
    with open(real, "rb") as f:
        f.seek(max(0, os.path.getsize(real) - MAX_FILE))
        return f.read().decode(errors="replace")


def facts(context=None):
    """What Field Kit sees, compact, for his context: only what the person left on ("HE'S
    LOOKING AT"). Returns (the facts, what he looked at, in words)."""
    c = dict(CONTEXT_DEFAULT, **(context or {}))
    looked = ["this computer"]
    doc = {}
    try:
        from .overview import overview
        o = overview()
        doc["computer"] = o.get("computer")
        doc["found"] = o.get("found")
        doc["network"] = o.get("network")
        doc["suggestions"] = o.get("suggestions")
    except Exception as e:                               # a fact that fails is said, not hidden
        doc["overview"] = f"unavailable: {e}"
    t = _target()
    if t and c["install"]:
        doc["install"] = {"root": t.root, "hostname": t.hostname(), "mounted_by_fieldkit": t.mounted_by_us}
        looked.append(f"{t.hostname()}'s install")
        try:
            doc["snapshots"] = [s.title() for s in repairs.snapshots(t)[:10]]
        except Exception as e:
            doc["snapshots"] = f"unavailable: {e}"
    elif not t:
        doc["install"] = "none mounted"
    for key, name, label in (("last_boot", "last-boot", "last boot's log"), ("findings", "black-screen", "repair findings")):
        if t and c[key]:
            try:
                doc[name] = findings(name)
                looked.append(label)
            except Exception as e:
                doc[name] = f"unavailable: {e}"
    for f in c.get("files") or []:
        try:
            check_added(f)
            doc.setdefault("files", {})[f] = read_added(f)
            looked.append(f)
        except (system.Failed, OSError) as e:
            doc.setdefault("files", {})[f] = f"unavailable: {e}"
    return doc, looked


READ_LABELS = {"check": lambda a: {"black-screen": "the black screen checks", "last-boot": "last boot's log"}.get(a.get("name"), "a check"),
               "snapshots": lambda a: "the snapshots", "disks": lambda a: "the disks' health"}


def read_tool(name, args):
    if name == "check":
        return findings(args.get("name", "black-screen"))
    if name == "snapshots":
        t = _target()
        return [{"number": s.number, "title": s.title()} for s in repairs.snapshots(t)] if t else "no install mounted"
    if name == "disks":
        return [{"path": d.path, "verdict": repairs.disk_report(d.path)[0]} for d in repairs.disks()]
    return "no such tool"


# ------------------------------------------------------------------ proposals

def _save(p):
    os.makedirs(QUEUE, mode=0o700, exist_ok=True)
    tmp = os.path.join(QUEUE, p["id"] + ".tmp")
    with open(tmp, "w") as f:
        json.dump(p, f, indent=1)
    os.chmod(tmp, 0o600)
    os.replace(tmp, os.path.join(QUEUE, p["id"] + ".json"))


def _load(pid):
    if not re.fullmatch(r"[0-9a-f]{12}", pid or ""):
        raise system.Failed("No such proposal.")
    try:
        with open(os.path.join(QUEUE, pid + ".json")) as f:
            return json.load(f)
    except (OSError, ValueError):
        raise system.Failed("No such proposal.") from None


def propose(name, args):
    """A proposal: what it is, the exact change, whether it's typed to confirm. Saved to the
    queue as pending; nothing runs."""
    p = {"id": uuid.uuid4().hex[:12], "created": time.strftime("%Y-%m-%d %H:%M:%S"), "tool": name, "args": args,
         "status": "pending", "confirm": "", "needs": ""}
    t = _target()
    if name == "fix":
        if not t:
            raise system.Failed("No install is mounted: mount it first.")
        found = engine_check(args.get("check", ""), t)
        f = found[int(args.get("id", -1))]
        if not f.fix:
            raise system.Failed(f"Nothing to fix for: {f.title}")
        p["title"] = f"{f.fix_label}"
        p["change"] = f"{f.title}\n{f.detail}\nField Kit keeps a backup of everything it changes."
    elif name == "rollback":
        if not t:
            raise system.Failed("No install is mounted: mount it first.")
        n = int(args.get("number"))
        s = next((s for s in repairs.snapshots(t) if s.number == n), None)
        if not s:
            raise system.Failed(f"There's no snapshot {n}.")
        p["title"] = f"Roll back to snapshot {n}"
        p["change"] = (f"The install starts as it was at {s.title()} from now on. The system as it is now is kept "
                       "beside it (@.before-rollback-…), so this can be undone. /home isn't touched.")
        p["confirm"] = "rollback"
    elif name == "grub_repair":
        if not t:
            raise system.Failed("No install is mounted: mount it first.")
        p["title"] = "Repair the boot menu"
        p["change"] = "grub-install from the install's own GRUB, where it was, then grub-mkconfig (checked before it's used). The old menu is kept in a backup."
    elif name == "boot_options":
        if not t:
            raise system.Failed("No install is mounted: mount it first.")
        old = repairs.boot_options(t)
        new = [str(w) for w in args.get("words", []) if re.fullmatch(r"[A-Za-z0-9_.,:/=+-]+", str(w))]
        p["args"] = {"words": new}
        p["title"] = "Change the boot options"
        p["change"] = (f'/etc/default/grub:\n- GRUB_CMDLINE_LINUX_DEFAULT="{" ".join(old)}"\n'
                       f'+ GRUB_CMDLINE_LINUX_DEFAULT="{" ".join(new)}"\nThen the boot menu is made again. The old file is kept.')
    elif name == "mount":
        dev = str(args.get("device", ""))
        if dev not in [i.path for i in system.install_candidates()]:
            raise system.Failed(f"{dev} isn't an install Field Kit can see.")
        p["title"] = f"Mount the install on {dev}"
        p["change"] = f"Unlock {dev} (you type its passphrase) and mount it at {system.MOUNT}, read-write, as its own fstab says."
        p["needs"] = "passphrase"
    elif name == "unmount":
        p["title"] = "Unmount the install"
        p["change"] = "Unmount it and lock its disk again."
    elif name == "control":
        action = str(args.get("action", ""))
        argv, why = machine_link.control_argv(action)
        if argv is None:
            raise system.Failed(why)
        title = {c["id"]: c["title"] for c in machine_link.controls()}.get(action, action)
        p["title"] = title
        p["change"] = f"{title}: runs {' '.join(argv)}" + (
            "\nAn install Field Kit mounted is unmounted first." if action in ("reboot", "poweroff") else "")
        p["confirm"] = action if action in ("reboot", "poweroff", "update") else ""
    elif name == "undo":
        done = _load(str(args.get("id", "")))
        if done.get("status") != "done" or not done.get("backups"):
            raise system.Failed("That change has nothing to undo from Field Kit's backups." if done.get("tool") != "rollback"
                                else "A rollback keeps the system it replaced beside it: Repair › Roll back to a snapshot can return to it.")
        p["args"] = {"id": done["id"]}
        p["title"] = f"Undo: {done.get('title', '')}"
        files = sorted({"/" + os.path.relpath(os.path.join(dp, n), b) for b in done["backups"]
                        for dp, _, ns in os.walk(b) for n in ns})
        p["change"] = "Puts these back from Field Kit's backups (" + ", ".join(os.path.basename(b) for b in done["backups"]) + "):\n  " + "\n  ".join(files)
    elif name == "pair_start":
        p["title"] = "Pair with BRODEC"
        p["change"] = (("Writes /etc/brodec-machine/machine.toml (Field Kit's: no jobs; the phone may watch and steer "
                        "only the Field Kit console; STOP ALL ends it) and starts" if not os.path.isfile(machine_link.CONFIG)
                        else "Starts") + " BRODEC's machine agent, which shows a code to scan in BRODEC. It reaches your "
                       "BRODEC account over the internet.")
    elif name == "run_command":
        cmd = str(args.get("command", "")).strip()
        if not cmd or FORBIDDEN.search(cmd):
            raise system.Failed("Refused: VECTOR never runs anything touching money, secrets or his kill switch.")
        p["title"] = "Run a command"
        p["change"] = f"As root:\n  {cmd}\nWhy: {args.get('why', '')}"
        p["confirm"] = "run"
    else:
        raise system.Failed(f"VECTOR has no tool {name}.")
    _save(p)
    log(f"proposed {p['id']} {name} {json.dumps(p['args'])}")
    return p


def run(pid, by="local", passphrase=None):
    """One proposal, once approved: `by` is who approved it (the screen: local). The switch is
    checked again right before it runs."""
    p = _load(pid)
    if p["status"] not in ("pending", "approved"):
        raise system.Failed(f"That proposal is {p['status']}.")
    if switch_off():
        p["status"] = "refused"
        _save(p)
        raise system.Failed("VECTOR's switch is off: he runs nothing until the operator turns him back on.")
    p["status"], p["approved_by"] = "running", by
    _save(p)
    log(f"run {pid} {p['tool']} approved by {by}")
    t = _target()
    before = _backups(t)
    name, a = p["tool"], p["args"]
    try:
        if name == "fix":
            f = engine_check(a["check"], t)[int(a["id"])]
            msg = f.fix(t)
        elif name == "rollback":
            msg = repairs.rollback(t, int(a["number"]))
        elif name == "grub_repair":
            msg = repairs.repair_grub(t)
        elif name == "boot_options":
            msg = repairs.set_boot_options(t, a["words"])
        elif name == "mount":
            mt = system.mount_install(a["device"], passphrase or None)
            msg = f"{mt.hostname()} is open at {mt.root}."
        elif name == "unmount":
            system.unmount_install(t)
            msg = "Unmounted and locked."
        elif name == "control":
            argv, why = machine_link.control_argv(a["action"])
            if argv is None:
                raise system.Failed(why)
            if a["action"] in ("reboot", "poweroff") and t and t.mounted_by_us:
                system.unmount_install(t)
            r = subprocess.run(argv, capture_output=True, text=True, timeout=3600)
            msg = ((r.stdout + r.stderr).strip()[-2000:] or "done") + f" (exit {r.returncode})"
            if r.returncode != 0:
                raise system.Failed(msg)
        elif name == "pair_start":
            msg = machine_link.start()
        elif name == "undo":
            msg = undo(t, _load(a["id"]).get("backups") or [])
        elif name == "run_command":
            r = subprocess.run(["/bin/sh", "-c", a["command"]], capture_output=True, text=True, timeout=600)
            msg = ((r.stdout + r.stderr).strip()[-2000:] or "(no output)") + f"\n(exit {r.returncode})"
        else:
            raise system.Failed("Unknown tool.")
        p["status"], p["result"] = "done", msg
    except (system.Failed, OSError, KeyError, IndexError, ValueError, subprocess.TimeoutExpired) as e:
        p["status"], p["result"] = "failed", str(e)
    p["backups"] = sorted(set(_backups(t)) - set(before))
    _save(p)
    log(f"{p['status']} {pid}: {p['result'][:200]!r}")
    if p["status"] == "failed":
        raise system.Failed(p["result"])
    return p


def _backups(t):
    """The backup folders Field Kit's repairs keep on the install (system.Backup)."""
    if not t:
        return []
    d = t.path(system.BACKUPS)
    return sorted(os.path.join(d, n) for n in os.listdir(d)) if os.path.isdir(d) else []


def undo(t, folders):
    """Every file the backups hold, put back at its own path (a file moved out comes back too)."""
    put = []
    for folder in folders:
        for dirpath, _, names in os.walk(folder):
            for n in names:
                src = os.path.join(dirpath, n)
                rel = "/" + os.path.relpath(src, folder)
                dst = t.path(rel)
                os.makedirs(os.path.dirname(dst), exist_ok=True)
                shutil.copy2(src, dst, follow_symlinks=False)
                put.append(rel)
    if not put:
        raise system.Failed("That change left no backup to put back.")
    return "Put back: " + ", ".join(sorted(set(put))) + ". (The backups stay where they were.)"


def decide(pid, answer, by):
    """An answer recorded from elsewhere (a phone bridge): approve or deny. Approving doesn't run
    it: `run` does, with the switch checked."""
    p = _load(pid)
    if p["status"] != "pending":
        raise system.Failed(f"That proposal is {p['status']}.")
    p["status"] = "approved" if answer == "approve" else "denied"
    p["decided_by"] = by
    _save(p)
    log(f"{p['status']} {pid} by {by}")
    return p


def pending():
    out = []
    for path in sorted(glob.glob(os.path.join(QUEUE, "*.json"))):
        try:
            with open(path) as f:
                p = json.load(f)
        except (OSError, ValueError):
            continue
        if p.get("status") in ("pending", "approved"):
            out.append(p)
    return out


# ------------------------------------------------------------------ a turn

def no_brain(question):
    """Without a brain: Field Kit's own findings, explained, and how to give him one."""
    lines = ["No brain on this line yet, so I can only read you Field Kit's own findings. Protocol is wise."]
    t = _target()
    if t:
        bad = [f for name in ("black-screen", "last-boot") for f in findings(name) if not f["ok"]]
        if bad:
            lines.append("What Field Kit found:")
            for f in bad[:6]:
                lines.append(f"- {f['title']}" + (f": {f['detail']}" if f["detail"] else "")
                             + (f" (fix: {f['fix']}, in Repair)" if f["fix"] else ""))
        else:
            lines.append("Field Kit's checks found nothing wrong on this install.")
    else:
        lines.append("No install is mounted: Repair › Mount my bromigOS install, then ask again.")
    lines.append("To give me a brain: connect to your lab (Lab › Network settings) with the lab's connection on the stick "
                 "(fieldkit/homelab.toml, which names its LiteLLM, Ollama or other OpenAI-compatible model), or a server's "
                 "lab bridge. No internet is needed for the lab's model.")
    return "\n".join(lines)


FIX_MODE = ("\n- FIX MODE: the person wants it fixed. Check what you need, explain the cause in two or three "
            "sentences, then propose every step of the fix now, in order (each tool call is one step of the plan).")


def ask(messages, context=None, mode="ask"):
    brain = pick_brain()
    off = switch_off()
    doc, looked = facts(context)
    looked = list(looked)
    if not brain:
        return {"ok": True, "brain": None, "switch_off": off, "reply": no_brain((messages or [{}])[-1].get("content", "")),
                "proposals": [], "looked_at": [x for x in looked if x != "this computer"] or ["Field Kit's findings"]}
    me, _ = persona()
    system_prompt = (me + "\n" + FIELDKIT_RULES + (FIX_MODE if mode == "fix" else "")
                     + ("\n- Your kill switch is OFF: you can talk and read, but every proposal is refused. Say so if asked to change something."
                        if off else "")
                     + "\n\nFACTS (from Field Kit, just now; only what the person lets you see):\n" + json.dumps(doc, default=str)[:16000])
    tools = [{"type": "function", "function": {"name": n, **spec}} for n, spec in {**READ_TOOLS, **ACT_TOOLS}.items()]
    convo = [{"role": "system", "content": system_prompt}] + [
        {"role": m["role"], "content": str(m.get("content", ""))} for m in messages if m.get("role") in ("user", "assistant")]
    proposals = []
    for _ in range(4):
        try:
            res = _http(brain["url"] + "/chat/completions", {"model": brain["model"], "messages": convo, "tools": tools,
                                                              "temperature": 0.3}, key=brain["key"], timeout=TIMEOUT)
        except (OSError, ValueError, urllib.error.URLError) as e:
            return {"ok": False, "brain": public(brain), "message": f"His brain didn't answer: {e}"}
        msg = (res.get("choices") or [{}])[0].get("message") or {}
        calls = msg.get("tool_calls") or []
        if not calls:
            return {"ok": True, "brain": public(brain), "switch_off": off, "reply": msg.get("content") or "",
                    "proposals": proposals, "looked_at": list(dict.fromkeys(looked))}
        convo.append({"role": "assistant", "content": msg.get("content") or "", "tool_calls": calls})
        for c in calls:
            fn = c.get("function") or {}
            name = fn.get("name", "")
            try:
                args = json.loads(fn.get("arguments") or "{}")
            except ValueError:
                args = {}
            if name in READ_TOOLS:
                looked.append(READ_LABELS[name](args))
                try:
                    out = read_tool(name, args)
                except Exception as e:
                    out = f"failed: {e}"
            elif name in ACT_TOOLS:
                if off:
                    out = "refused: the kill switch is off"
                else:
                    try:
                        p = propose(name, args)
                        proposals.append(p)
                        out = f"proposed to the person (id {p['id']}): waiting for their approval on screen; not done yet"
                    except (system.Failed, KeyError, IndexError, ValueError, TypeError) as e:
                        out = f"refused: {e}"
            else:
                out = "no such tool"
            convo.append({"role": "tool", "tool_call_id": c.get("id", name), "content": json.dumps(out, default=str)[:6000]})
    return {"ok": True, "brain": public(brain), "switch_off": off, "reply": "(He's still thinking; ask again.)",
            "proposals": proposals, "looked_at": list(dict.fromkeys(looked))}


def status():
    brain = pick_brain()
    _, source = persona()
    try:
        brodec = machine_link.state()["state"]
    except Exception:
        brodec = "missing"
    # the same status chips as Field Kit's other screens: the network, SSH, remote help, the stick
    try:
        from . import medium, overview as ov
        bar = {"network": ov.network(), "remote": medium.remote_state(), "stick": medium.stick_summary(),
               "ssh": {"on": system.run(["systemctl", "is-active", "--quiet", "sshd.service"], check=False).returncode == 0}}
    except Exception:
        bar = {}
    return {"ok": True, "bar": bar, "brain": public(brain), "switch_off": switch_off(), "persona": source,
            "candidates": [c["source"] for c in candidates()], "pending": len(pending()), "brodec": brodec,
            "no_internet": (brain is None) or lan_only(brain["url"]),
            "context": [{"key": k, "label": label, "on": on} for k, label, on in context_items()]}


# ------------------------------------------------------------------ the engine's verb

def engine(args, progress=None):
    verb = args[0] if args else "status"
    rest = args[1:]
    by = rest[rest.index("--by") + 1] if "--by" in rest and rest.index("--by") + 1 < len(rest) else "local"
    if verb == "status":
        return status()
    if verb == "ask":
        doc = json.loads(sys.stdin.read() or "{}")
        return ask(doc.get("messages", []), doc.get("context"), doc.get("mode", "ask"))
    if verb == "suggest":
        return {"ok": True, "questions": suggest()}
    if verb == "add":
        return check_added(rest[0])
    if verb == "undo":
        return {"ok": True, "proposal": propose("undo", {"id": rest[0]})}
    if verb == "run":
        passphrase = sys.stdin.read().rstrip("\n") if not sys.stdin.isatty() else None
        p = run(rest[0], by=by, passphrase=passphrase)
        return {"ok": True, "message": p["result"], "proposal": p}
    if verb == "pending":
        return {"ok": True, "pending": pending()}
    if verb == "decide":
        return {"ok": True, "proposal": decide(rest[0], rest[1], by)}
    if verb == "pair":
        return machine_link.state()
    if verb == "pair-start":
        return {"ok": True, "proposal": propose("pair_start", {})}
    if verb == "controls":
        return {"ok": True, "controls": machine_link.controls()}
    if verb == "control":
        return {"ok": True, "proposal": propose("control", {"action": rest[0]})}
    if verb == "propose":                 # the screen's own proposal (the person picked a fix)
        return {"ok": True, "proposal": propose(rest[0], json.loads(sys.stdin.read() or "{}"))}
    raise ValueError(f"no vector verb {verb}")

