"""bromigOS Server's own steps (docs/server.md; manual/src/server.md): the model the graphical
(server_gui.py) and the text installer (server_tui.py) share, the same way common.py is for
the rest. The roles, service toggles and package lists are data (presets.toml: the
bromigos-server package's, else the medium's); this file reads them, checks what's typed,
words the summary, and turns the answers into the plan bromigos-iso-install applies
(server_apply.py).

After "What kind of computer" → bromigOS Server, the steps are: Role, Keyboard, Where,
Network, Access, Storage, Encryption, Updates, Services, Ready to install. A server has no
About you or Remote access step: Network names it and Access makes its admin.
"""
import base64
import glob
import hashlib
import ipaddress
import json
import os
import re
import subprocess

PRESET_PLACES = ["/usr/share/bromigos/server/presets.toml"]       # the bromigos-server package's
SHARE = os.environ.get("BROMIGOS_ISO_SHARE", "/usr/local/share/bromigos-iso")
GITHUB = "https://github.com"           # BROMIGOS_GITHUB_KEYS_URL: another (the tests' stub server)

# ── the steps (id, title in the step list, heading, the line under it) ──────────────────
STEPS = [
    ("role", "Role", "What will this server do?",
     "Pick its jobs: one, or several together. They suggest what it runs, and you can change any of it on the Run "
     "step, or add a role later."),
    ("secrets", "Keys", "Where should this server keep its keys and passwords?",
     "Your VPN login, game admin passwords, provider keys: each one goes straight into the store you pick, never into a "
     "file or the answer file. What needs no person is made for you and stored the same way."),
    ("network", "Network", "Its network",
     "How this server joins your network, and the name other computers know it by."),
    ("access", "Access", "Who can sign in",
     "The admin account, and how you reach it from your other computers. Keys only is the safe way: nobody can "
     "guess a key."),
    ("reach", "Reach", "Reach it from anywhere",
     "How you get to this server when you're not at home. Through BRODEC only is the safest, and you can add "
     "another way later."),
    ("storage", "Storage", "Data disks",
     "Disks for your files and apps, apart from the system's own disk. Optional: skip it to keep everything on "
     "the system disk."),
    ("unlock", "Encryption", "Lock the disk",
     "Encryption keeps the data private if the server is stolen. The question is how it unlocks when it "
     "restarts on its own after an update."),
    ("updates", "Updates", "How it updates",
     "Every update takes a snapshot first, then checks the server is healthy; if it isn't, it goes back by itself."),
    ("services", "Run", "What should this server run?",
     "First, its place in your lab. Then what it runs: your roles have ticked their suggestions, and everything "
     "can be changed, here or later."),
]
STEP_IDS = [s[0] for s in STEPS]

# VECTOR's line for each of these steps is in the voice guide's catalogue (lib/guide/lines.toml,
# installer.STEP and installer.STEP.short), so the caption and his clip say the same words


def fake():
    """The installers' stand-in mode (pictures, tests): sample ports, a chip, no reading this machine."""
    return bool(os.environ.get("BROMIGOS_INSTALLER_FAKE"))


def _read(path):
    with open(path) as f:
        return f.read()


# ── the presets ─────────────────────────────────────────────────────────────────────────
_PRESETS = None


def preset_path():
    for p in ([os.environ["BROMIGOS_SERVER_PRESETS"]] if os.environ.get("BROMIGOS_SERVER_PRESETS") else []) + \
            PRESET_PLACES + [os.path.join(SHARE, "server", "presets.toml"),
                             os.path.join(os.path.dirname(os.path.realpath(__file__)), "..", "..", "..", "share",
                                          "bromigos-iso", "server", "presets.toml")]:
        if os.path.isfile(p):
            return os.path.realpath(p)
    return None


def presets(reload=False):
    """The roles, services, apps and base (presets.toml), as a dict; {} when there's none."""
    global _PRESETS
    if _PRESETS is None or reload:
        import tomllib
        path = preset_path()
        try:
            _PRESETS = tomllib.loads(_read(path)) if path else {}
        except (OSError, tomllib.TOMLDecodeError):
            _PRESETS = {}
        _PRESETS["_source"] = path
    return _PRESETS


def roles():
    return presets().get("roles", [])


def role(rid):
    return next((r for r in roles() if r["id"] == rid), None)


def services_for(rid):
    """The Services step's toggles for a role, in the file's order."""
    return [s for s in presets().get("services", []) if "*" in s.get("roles", []) or rid in s.get("roles", [])]


def apps_for(rid):
    return [x for x in presets().get("apps", []) if rid in x.get("roles", [])]


def default_on(svc, rid, lab=False):
    r = role(rid) or {}
    on = svc.get("on", None)
    if svc["id"] in r.get("services_on", []):
        on = True
    if lab and svc["id"] in (r.get("with_lab") or {}).get("services_on", []):
        on = True
    return bool(on) if on is not None else False


def active():
    """bromigOS Server's steps are offered: the presets are there."""
    return bool(roles())


# ── the answers ─────────────────────────────────────────────────────────────────────────
def defaults():
    up = presets().get("updates", {})
    return {"role": None, "roles": [], "lab": None, "lab_join": {}, "provision": None, "provision_edited": False,
            "models": [], "setup": {}, "setup_secrets": {}, "store": {}, "interface": None, "method": "dhcp", "address": "", "prefix": "24", "gateway": "", "dns": "",
            "wake_on_lan": True, "vlan": "", "bond": [], "github": "", "github_keys": [], "github_ok": False,
            "tailscale": False, "wireguard": False, "lab_key": "", "lab_same_keys": True, "ssh_mode": "keys",
            "data_disks": [], "data_layout": "single", "unlock": None, "update_mode": up.get("mode", "auto"),
            "update_window": up.get("window", "03:00-05:00"), "notify_phone": bool(up.get("notify", True)),
            "services": {}, "apps": None, "pelican_url": "", "registry_mirror": "", "kernel": None}


def srv(a):
    """The server's answers in the installer's answers (a["server"]), made on first use."""
    s = a.get("server")
    if not isinstance(s, dict):
        s = a["server"] = defaults()
    else:
        for k, v in defaults().items():
            s.setdefault(k, v)
    return s


def is_server(a):
    from . import common
    ed = common.edition(a.get("edition", "desktop"))
    return not ed.get("desktop", True) and active()


def roles_of(s):
    """The roles chosen (several can be: Lab node + Game server + Storage), "plain" alone."""
    rs = [r for r in (s.get("roles") or ([s["role"]] if s.get("role") else [])) if role(r)]
    return rs


def services_for_roles(rids):
    out = []
    for rid in rids or ["plain"]:
        for x in services_for(rid):
            if x not in out:
                out.append(x)
    return out


def apps_for_roles(rids):
    out = []
    for rid in rids or ["plain"]:
        for x in apps_for(rid):
            if x not in out:
                out.append(x)
    return out


def set_roles(a, rids, added=None):
    """The roles chosen: Just a server is the base and goes alone; the others combine. The
    service toggles, apps and the catalogue's picks are preset from all of them."""
    s = srv(a)
    rids = [r for r in dict.fromkeys(rids) if role(r)]
    if "plain" in rids and len(rids) > 1:
        rids = ["plain"] if added == "plain" else [r for r in rids if r != "plain"]
    s["roles"] = rids
    s["role"] = rids[0] if rids else None
    lab = has_lab(s)
    s["services"] = {x["id"]: any(default_on(x, r, lab) for r in rids) for x in services_for_roles(rids)
                     if not x.get("locked")}
    s["apps"] = list(dict.fromkeys(x for r in rids for x in (role(r) or {}).get("apps_on", [])))
    if not s.get("lab_set"):                 # a Lab node joins a lab unless you say otherwise
        s["lab"] = "join" if "lab" in rids else "none"
    if s["lab"] == "join" and not s.get("lab_join"):
        s["lab_join"] = {"pair": True}       # paired with BRODEC after the install, unless a file is given
    if not s.get("provision_edited"):
        s["provision"] = None                 # the catalogue's picks follow the roles until edited


def toggle_role(a, rid, on):
    s = srv(a)
    rs = [r for r in roles_of(s) if r != rid] + ([rid] if on else [])
    set_roles(a, rs, added=rid if on else None)


def pick_role(a, rid):
    """One role (the answer files' single role, the tests)."""
    s = srv(a)
    if roles_of(s) == [rid]:
        return
    set_roles(a, [rid], added=rid)


def has_lab(s):
    """This server works with a lab: a Lab node, a server starting or joining one, or a Game
    server joining the lab's Pelican panel."""
    return ("lab" in roles_of(s) or s.get("lab") in ("new", "join") or bool((s.get("services") or {}).get("pelican-wings"))
            or "wings" in (s.get("provision") or []))


def combo_notes(rids, hw=None):
    """Plain notes for a combination of roles: its trade-offs, and what this computer lacks for it."""
    out = []
    for c in presets().get("combos", []):
        if set(c.get("roles", [])) <= set(rids):
            words = c["note"]
            need = c.get("needs") or {}
            if hw:
                short = []
                if need.get("ram_gb") and hw.get("ram_gb", 0) < need["ram_gb"]:
                    short.append(f"{need['ram_gb']} GB of memory (this one has {hw.get('ram_gb', 0)})")
                if need.get("cpu") and hw.get("cpu", 0) < need["cpu"]:
                    short.append(f"{need['cpu']} cores (this one has {hw.get('cpu', 0)})")
                if short:
                    words += " It wants " + " and ".join(short) + "."
            out.append(words)
    return out


def roles_words(rids):
    return " + ".join((role(r) or {}).get("title", r) for r in rids) or "Just a server"


def steps_for(out, a):
    """The desktop's steps (common.steps_for's list) made bromigOS Server's: Role after the
    edition, the server's own after Where, and no About you, Encryption or Remote access."""
    if not is_server(a):
        if reach_module() and "summary" in out and "auto" not in out:
            out.insert(out.index("summary"), "reach")       # the desktop: Reach it from anywhere, before the summary
        return out
    out = [s for s in out if s not in ("user", "encryption", "ssh")]
    at = out.index("edition") + 1 if "edition" in out else (out.index("checks") + 1 if "checks" in out else
                                                             (out.index("welcome") + 1 if "welcome" in out else 0))
    out[at:at] = ["role", "secrets"]
    tail = out.index("summary") if "summary" in out else len(out)
    mine = ["network", "access", "reach", "storage", "unlock", "updates", "services"]
    if a.get("mode") == "reinstall":
        mine.remove("unlock")              # a reinstall keeps the disk's encryption as it is
    out[tail:tail] = mine
    return out


# ── what's typed: the network ───────────────────────────────────────────────────────────
def check_address(v):
    v = (v or "").strip()
    if not v:
        return "Type the address this server will have, for example 192.0.2.20."
    try:
        ip = ipaddress.ip_address(v)
    except ValueError:
        return f"\"{v}\" isn't an address. It's four numbers with dots, for example 192.0.2.20."
    if ip.is_loopback or ip.is_multicast or ip.is_unspecified or ip.is_link_local:
        return f"{v} can't be a server's address on your network. Use one from your router's range, like 192.0.2.20."
    return None


def check_prefix(v, address=""):
    v = str(v or "").strip().lstrip("/")
    six = ":" in (address or "")
    top = 128 if six else 32
    if not v.isdigit() or not 1 <= int(v) <= top:
        return (f"The network size is a number from 1 to {top}: 24 for most home networks "
                f"(the same as 255.255.255.0).")
    if address and not check_address(address) and not six:
        net = ipaddress.ip_interface(f"{address}/{v}")
        if int(v) <= 30 and net.ip in (net.network.network_address, net.network.broadcast_address):
            return f"{address} is the network's own address with /{v}: choose another one, like {net.network.network_address + 20}."
    return None


def prefix_from(v):
    """24, '/24' or 255.255.255.0 as 24 (None if it's neither)."""
    v = str(v or "").strip().lstrip("/")
    if v.isdigit():
        return v
    try:
        return str(ipaddress.ip_network(f"0.0.0.0/{v}").prefixlen)
    except ValueError:
        return None


def check_gateway(v, address="", prefix="24"):
    v = (v or "").strip()
    if not v:
        return "Type your router's address (the gateway), for example 192.0.2.1."
    try:
        gw = ipaddress.ip_address(v)
    except ValueError:
        return f"\"{v}\" isn't an address. Your router's is usually like 192.0.2.1."
    if address and not check_address(address) and not check_prefix(prefix, address):
        net = ipaddress.ip_interface(f"{address}/{prefix}").network
        if gw not in net:
            return f"The router {v} isn't on {net}: it's usually {net.network_address + 1}."
        if str(gw) == address:
            return "The router's address is the server's own: they must differ."
    return None


def split_dns(v):
    return [x for x in re.split(r"[\s,;]+", (v or "").strip()) if x]


def check_dns(v):
    items = split_dns(v)
    if not items:
        return "Type at least one name server (DNS), for example your router's address, or 9.9.9.9."
    for x in items:
        try:
            ipaddress.ip_address(x)
        except ValueError:
            return f"\"{x}\" isn't a name server's address. Separate several with spaces."
    return None


def check_vlan(v):
    v = str(v or "").strip()
    if v and (not v.isdigit() or not 1 <= int(v) <= 4094):
        return "A VLAN is a number from 1 to 4094, or leave it empty."
    return None


def network_problems(s):
    """{field: problem} for the Network step (the fields that are fine are left out)."""
    p = {}
    if s.get("method") == "static":
        p["address"] = check_address(s.get("address"))
        p["prefix"] = check_prefix(s.get("prefix"), s.get("address"))
        p["gateway"] = check_gateway(s.get("gateway"), s.get("address"), s.get("prefix"))
        p["dns"] = check_dns(s.get("dns"))
    p["vlan"] = check_vlan(s.get("vlan"))
    if len(s.get("bond") or []) == 1:
        p["bond"] = "Bonding joins two or more network ports: tick another one, or none."
    return {k: v for k, v in p.items() if v}


def check_network(a):
    from . import common
    s = srv(a)
    if not s.get("interface"):
        return "Choose the network port this server uses."
    return common.check_hostname(a.get("hostname") or "") or next(iter(network_problems(s).values()), None)


# ── interfaces ──────────────────────────────────────────────────────────────────────────
SAMPLE_NET = [
    {"name": "enp3s0", "kind": "wired", "mac": "52:54:00:12:34:56", "carrier": True, "speed": 1000,
     "address": "192.0.2.24", "prefix": 24, "gateway": "192.0.2.1", "dns": ["192.0.2.1"], "wol": True, "model": "Intel I225-V"},
    {"name": "enp4s0", "kind": "wired", "mac": "52:54:00:12:34:57", "carrier": False, "speed": None,
     "address": "", "prefix": None, "gateway": "", "dns": [], "wol": True, "model": "Realtek RTL8125"},
    {"name": "wlan0", "kind": "wifi", "mac": "52:54:00:aa:bb:cc", "carrier": False, "speed": None,
     "address": "", "prefix": None, "gateway": "", "dns": [], "wol": False, "model": "Intel AX210"},
]


def _sys(path, default=""):
    try:
        return _read(path).strip()
    except OSError:
        return default


def _run(argv, timeout=10):
    try:
        r = subprocess.run(argv, capture_output=True, text=True, timeout=timeout)
        return r.returncode, r.stdout
    except (OSError, subprocess.TimeoutExpired):
        return 127, ""


def interfaces():
    """This machine's network ports, wired first and connected first: [{name, kind (wired|wifi),
    mac, carrier, speed, address, prefix, gateway, dns, wol, model}]."""
    fixture = os.environ.get("BROMIGOS_INSTALLER_NET")
    if fixture:
        return json.loads(_read(fixture))
    if fake():
        return [dict(x) for x in SAMPLE_NET]
    out = []
    for d in sorted(glob.glob("/sys/class/net/*")):
        name = os.path.basename(d)
        if name == "lo" or not os.path.exists(os.path.join(d, "device")) or _sys(os.path.join(d, "type")) != "1":
            continue
        kind = "wifi" if os.path.isdir(os.path.join(d, "wireless")) else "wired"
        x = {"name": name, "kind": kind, "mac": _sys(os.path.join(d, "address")),
             "carrier": _sys(os.path.join(d, "carrier"), "0") == "1", "speed": None, "address": "", "prefix": None,
             "gateway": "", "dns": [], "wol": None, "model": ""}
        sp = _sys(os.path.join(d, "speed"), "")
        x["speed"] = int(sp) if sp.lstrip("-").isdigit() and int(sp) > 0 else None
        code, js = _run(["ip", "-j", "-4", "addr", "show", "dev", name])
        try:
            info = (json.loads(js) or [{}])[0].get("addr_info", [])
            if info:
                x["address"], x["prefix"] = info[0]["local"], info[0]["prefixlen"]
        except (ValueError, IndexError, KeyError):
            pass
        code, js = _run(["ip", "-j", "route", "show", "default", "dev", name])
        try:
            x["gateway"] = (json.loads(js) or [{}])[0].get("gateway", "")
        except (ValueError, IndexError):
            pass
        if kind == "wired":
            code, txt = _run(["ethtool", name])
            m = re.search(r"Supports Wake-on:\s*(\S+)", txt)
            x["wol"] = ("g" in m.group(1)) if m else None
        x["model"] = _sys(os.path.join(d, "device", "label")) or ""
        out.append(x)
    dns = []
    try:
        dns = [line.split()[1] for line in _read("/etc/resolv.conf").splitlines() if line.startswith("nameserver")]
    except OSError:
        pass
    for x in out:
        if x["address"]:
            x["dns"] = dns
    out.sort(key=lambda x: (x["kind"] != "wired", not x["carrier"], x["name"]))
    return out


def lab_hosts(quick=False):
    """The lab's machines this network announces (mDNS: _bromigos-lab._tcp), by name: what Find my
    lab would show. Sample names in the stand-in mode; quick: don't wait for the network."""
    if fake():
        return ["gpu-box", "nas", "core"]
    if quick:
        return list(_LAB_SEEN)
    code, out = _run(["avahi-browse", "-tpr", "_bromigos-lab._tcp"], timeout=6)
    names = []
    for line in out.splitlines():
        f = line.split(";")
        if len(f) > 3 and f[0] == "=" and f[3] not in names:
            names.append(f[3])
    _LAB_SEEN[:] = names
    return names


_LAB_SEEN = []


def iface_words(x):
    """One line for a port: what it is and its state, in plain words."""
    kind = "Wired" if x["kind"] == "wired" else "Wi-Fi"
    if x["carrier"] or x.get("address"):
        state = "connected" + (f" at {x['speed'] // 1000} Gb/s" if (x.get("speed") or 0) >= 1000 else
                               (f" at {x['speed']} Mb/s" if x.get("speed") else ""))
        if x.get("address"):
            state += f", now {x['address']}"
    else:
        state = "no cable" if x["kind"] == "wired" else "not connected"
    return f"{kind} · {state}" + (f" · {x['model']}" if x.get("model") else "")


def wifi_only(ports):
    return bool(ports) and not any(x["kind"] == "wired" for x in ports)


WIFI_ONLY_WORDS = ("This computer has Wi-Fi only, no network cable port. A server works best on a cable: Wi-Fi "
                   "can drop, and Wake-on-LAN doesn't work over it. It can still be one; join the Wi-Fi network in the "
                   "welcome tour after the install, or plug in a USB network adapter now.")


def pick_interface(s, ports):
    if s.get("interface") in [x["name"] for x in ports]:
        return
    s["interface"] = ports[0]["name"] if ports else None
    x = ports[0] if ports else {}
    if s.get("method") == "static" and not s.get("address") and x.get("address"):
        s.update(address=x["address"], prefix=str(x.get("prefix") or 24), gateway=x.get("gateway", ""),
                 dns=" ".join(x.get("dns") or []))


def port(s, ports):
    return next((x for x in ports if x["name"] == s.get("interface")), None)


def shown_address(a, ports=None):
    """(address or name, words): what other computers will use to reach it, for the big line."""
    s = srv(a)
    host = (a.get("hostname") or "bromigos-server")
    if s.get("method") == "static" and not check_address(s.get("address")):
        return s["address"], "Fixed: it keeps this address."
    x = port(s, ports if ports is not None else interfaces()) or {}
    if x.get("address"):
        return x["address"], (f"From your router (DHCP), so it can change. {host}.local works too, or set a fixed address, "
                              "or reserve this one in your router.")
    return f"{host}.local", "Its name on your network. Your router gives it an address when it starts."


def ssh_target(a, ports=None):
    user = a.get("user") or "admin"
    addr, _ = shown_address(a, ports)
    return user, addr


def ssh_line(a, ports=None):
    user, addr = ssh_target(a, ports)
    return f"ssh {user}@{addr}"


def qr_payload(a, ports=None):
    user, addr = ssh_target(a, ports)
    return f"ssh://{user}@{addr}"


# ── what's typed: access ────────────────────────────────────────────────────────────────
def check_admin(v):
    """The admin's user name: as common.check_username, but "admin" is fine on a server."""
    from . import common
    if v == "admin":
        return None
    return common.check_username(v)


GITHUB_USER = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9]|-(?=[A-Za-z0-9])){0,38}$")


def check_github_user(v):
    v = (v or "").strip().lstrip("@")
    if not v:
        return "Type a GitHub user name, for example octocat."
    if not GITHUB_USER.match(v):
        return f"\"{v}\" isn't a GitHub user name: letters, digits and single dashes, up to 39."
    return None


def fetch_github_keys(user, base=None, timeout=10):
    """(keys, problem): the SSH keys GitHub publishes for USER (https://github.com/USER.keys);
    problem says what went wrong, in plain words, with what to do."""
    import urllib.error
    import urllib.request
    user = (user or "").strip().lstrip("@")
    problem = check_github_user(user)
    if problem:
        return [], problem
    url = f"{(base or os.environ.get('BROMIGOS_GITHUB_KEYS_URL') or GITHUB).rstrip('/')}/{user}.keys"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "bromigos-installer"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            text = r.read(256 * 1024).decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return [], f"There's no GitHub user called {user}. Check the spelling, or paste your key instead."
        return [], f"GitHub answered {e.code}. Try again in a minute, or paste your key instead."
    except (urllib.error.URLError, OSError, ValueError):
        return [], ("GitHub can't be reached: this computer isn't on the internet. Plug in a network cable, or paste "
                    "your key, or use the USB stick's fieldkit folder.")
    from . import common
    keys = [line.strip() for line in text.splitlines() if line.strip() and common.check_key(line.strip()) is None]
    if not keys:
        return [], (f"{user} has no SSH keys on GitHub. Add one at github.com/settings/keys, or paste your key "
                    "instead.")
    return keys, None


def fingerprint(key):
    """A public key's SHA256 fingerprint, as ssh-keygen -l shows it: (type, 'SHA256:…', comment)."""
    parts = (key or "").split()
    if len(parts) < 2:
        return None, None, None
    try:
        blob = base64.b64decode(parts[1] + "=" * (-len(parts[1]) % 4), validate=False)
    except (ValueError, base64.binascii.Error):
        return parts[0], None, None
    fp = "SHA256:" + base64.b64encode(hashlib.sha256(blob).digest()).decode().rstrip("=")
    kind = {"ssh-ed25519": "ED25519", "ssh-rsa": "RSA"}.get(parts[0], parts[0].split("-")[0].upper())
    return kind, fp, " ".join(parts[2:])


def key_words(key):
    kind, fp, comment = fingerprint(key)
    return f"{kind} {fp}" + (f" ({comment})" if comment else "")


def all_keys(a):
    s = srv(a)
    out = []
    for k in list(a.get("ssh_keys") or []) + (list(s.get("github_keys") or []) if s.get("github_ok") else []):
        if k not in out:
            out.append(k)
    return out


def check_access(a):
    from . import common
    s = srv(a)
    p = check_admin(a.get("user") or "")
    if p:
        return p
    p = common.check_password(a.get("password", ""), a.get("password2", a.get("password", "")))
    if p:
        return p
    if s.get("github") and not s.get("github_ok"):
        return (f"Press Get keys to look up {s['github']}'s keys on GitHub and check them, or clear the GitHub "
                "box.")
    mode = s.get("ssh_mode", "keys")
    if mode == "keys" and not all_keys(a):
        return ("Keys only needs a key: copy your .pub file into the USB stick's fieldkit folder and press Look again, "
                "paste one, or get yours from GitHub. Or choose a password login, or no SSH.")
    if "lab" in roles_of(s) and not s.get("lab_same_keys") and common.check_key((s.get("lab_key") or "").strip()):
        return "The lab workstation's key: " + common.check_key((s.get("lab_key") or "").strip())
    if "lab" in roles_of(s) and s.get("lab_same_keys") and not all_keys(a):
        return "The lab account needs your lab workstation's key: add a key, or paste it in the lab box."
    return None


LAB_ACCOUNT_WORDS = ("The lab account is how your lab's workstation sets this server up. It signs in only with the "
                     "key below, and it can run any command as the system administrator without a password "
                     "(passwordless sudo). It exists only because this is a Lab node.")
PASSWORD_WARN = ("Anyone on your network, or the internet if this server is reachable from it, can try passwords "
                 "over SSH. Brute-force blocking slows them down; a key can't be guessed at all.")


# ── where keys and passwords go (bromigos_homelab.secretstore; its stand-in until it lands) ─
_STORE = None
STORE_SECRET_KEYS = ("secret_id", "token")


class _Store:
    """The Keys step's words and checks over the lab's secret store (bromigos_homelab.secretstore,
    bromigos-lab's) when it's here, else its stand-in (secretstore_stub): the four choices in the
    operator's order and words, the paths, the policy, the test, the summary, where the keys
    live, Bitwarden."""

    def __init__(self):
        from . import secretstore_stub as stub
        self.stub, self.engine = stub, None
        try:
            import sys
            if os.environ.get("BROMIGOS_HOMELAB_LIB"):
                sys.path.insert(0, os.environ["BROMIGOS_HOMELAB_LIB"])
            elif "/usr/lib/bromigos/lib" not in sys.path:
                sys.path.append("/usr/lib/bromigos/lib")
            from bromigos_homelab import secretstore as m
            if hasattr(m, "choices"):
                self.engine = m
        except Exception:
            pass
        self.AUTH = stub.AUTH

    def backends(self):
        return self.stub.BACKENDS

    def kv_path(self, cfg, host):
        return self.stub.kv_path(cfg, host)

    def policy_preview(self, cfg, host):
        if self.engine and cfg.get("kind") == "vault" and cfg.get("address"):
            try:
                return self._vault(cfg, host).policy_preview()
            except Exception:
                pass
        return self.stub.policy_preview(cfg, host)

    def _vault(self, cfg, host):
        return self.engine.open_store(config_doc(cfg), hostname=host)

    def test(self, cfg, host=""):
        if self.engine and cfg.get("kind") == "vault" and cfg.get("address"):
            try:
                r = self._vault(cfg, host).test()
                ok = r.get("ok") if isinstance(r, dict) else bool(r)
                return ok, (r.get("words") if isinstance(r, dict) else None) or ("Connected." if ok else "It didn't connect.")
            except Exception as e:
                return False, f"It didn't connect: {e}"
        return self.stub.test(cfg, host)

    def summary(self, cfg, paths):
        return self.stub.summary(cfg, paths)

    def where(self, cfg):
        return self.stub.where(cfg)

    def bitwarden(self, item):
        if self.engine and hasattr(self.engine, "bitwarden_get"):
            try:
                v = self.engine.bitwarden_get(item)
                return (v, "From Bitwarden.") if v else (None, "Bitwarden didn't give it: unlock it first (bw unlock).")
            except Exception as e:
                return None, f"Bitwarden didn't give it: {e}"
        return self.stub.bitwarden(item)

    def stage(self, root, cfg, values, generated):
        return self.stub.stage(root, cfg, values, generated)


def secretstore():
    global _STORE
    if _STORE is None:
        _STORE = _Store()
    return _STORE


def config_doc(cfg):
    """The store's choice as bromigos_homelab.secretstore's config (/etc/bromigos/secrets.toml): no values."""
    kind = cfg.get("kind", "local")
    doc = {"backend": kind}
    if kind in ("vault", "openbao"):
        # a new Vault runs here; the lab's comes with its address, or from the join bundle or BRODEC pairing
        doc["vault"] = {k: v for k, v in (("address", cfg.get("address") or ("http://127.0.0.1:8200" if kind == "openbao" else None)),
                                          ("auth", cfg.get("auth", "approle")), ("role_id", cfg.get("role_id"))) if v}
    if kind == "sops":
        doc["sops"] = {k: v for k, v in (("repo", cfg.get("repo")), ("recipient", cfg.get("age"))) if v}
    return doc


def secret_ref(cfg, item_id, field):
    """An answer file's reference to a secret: {secret = "local:ITEM/FIELD"} (vault:, sops:)."""
    prefix = {"openbao": "vault", "vault": "vault", "sops": "sops"}.get(cfg.get("kind"), "local")
    return {"secret": f"{prefix}:{item_id}/{field}"}


def store_of(a):
    """The store chosen: {kind, address, auth, role_id, secret_id, token}; the lab's Vault when it
    joins a lab, else this server's own."""
    s = srv(a)
    st = s.get("store") or {}
    if not st.get("kind"):
        st = s["store"] = {"kind": "vault" if s.get("lab") == "join" else "local", "auth": "oidc"}
    return st


def check_keys(a):
    st = store_of(a)
    s = srv(a)
    if st["kind"] == "vault":
        if s.get("lab_join", {}).get("bundle") or s.get("lab_join", {}).get("file"):
            return None                      # the lab's connection or join bundle carries the Vault
        addr = (st.get("address") or "").strip()
        if not re.match(r"^https?://[^\s/]+", addr):
            return "Type your lab's Vault address, for example https://vault.lab.example:8200."
        auth = st.get("auth", "oidc")
        if auth == "approle" and not (st.get("role_id") and st.get("secret_id")):
            return "Type the role ID and the secret ID your lab's admin made for this server."
        if auth == "wrapped":
            tok = (st.get("token") or "").strip()
            if not tok:
                return "Paste the one-time wrapped token."
            if tok.startswith("hvs.") and len(tok) < 30 or tok.lower().startswith("root"):
                return "That looks like a root token. Use a one-time wrapped token instead: a root token is never asked for."
    if st["kind"] == "openbao":
        s.update(lab="new", lab_set=True)
        if "vault" not in (s.get("provision") or []):
            s["provision"] = list(provision_picks(a)) + ["vault"]
            s["provision_edited"] = True
    return None


def secret_paths(a):
    """[(item, field, store path, typed or generated)] for every secret the chosen services have."""
    from . import provision as PV
    s = srv(a)
    host = a.get("hostname") or "server"
    base = secretstore().kv_path(store_of(a), host)
    out = []
    for i in PV.resolve(provision_picks(a))[0]:
        for f in PV.setup(i).get("field", []):
            if f.get("kind") == "secret" and (s.get("setup_secrets", {}).get(i) or {}).get(f["id"]):
                out.append((i, f["id"], f"{base}/{i}/{f['id']}", "typed"))
        for g in PV.generated(i):
            out.append((i, g, f"{base}/{i}/{g}", "generated"))
    return out


# ── reach it from anywhere (bromigos lab network: bromigos_homelab.reach, docs/lab-network.md) ─
_REACH = None


def reach_module():
    """bromigos_homelab.reach (bromigos-lab, on both media), or None."""
    global _REACH
    if _REACH is None:
        try:
            import sys
            if os.environ.get("BROMIGOS_HOMELAB_LIB"):        # a checkout's (pictures, tests)
                sys.path.insert(0, os.environ["BROMIGOS_HOMELAB_LIB"])
            elif "/usr/lib/bromigos/lib" not in sys.path:
                sys.path.append("/usr/lib/bromigos/lib")
            from bromigos_homelab import reach
            _REACH = reach
        except Exception:
            _REACH = False
    return _REACH or None


def reach_choices():
    """The Reach step's answers, in order (reach.CHOICES); just BRODEC without the module."""
    m = reach_module()
    if m:
        return m.CHOICES
    return [{"id": "brodec", "title": "Through BRODEC only", "default": True, "account": None, "packages": [],
             "words": "Your phone reaches this machine through BRODEC, end to end encrypted. Nothing else on the internet "
                      "can reach it."}]


def reach_default():
    return next((c["id"] for c in reach_choices() if c.get("default")), "brodec")


def check_reach(r):
    """None, or what's wrong with the Reach answer: the join code (reach.decode), the WireGuard
    configuration (reach.check_wireguard), the Tailscale key (reach.check_key)."""
    m = reach_module()
    mode = (r or {}).get("mode") or reach_default()
    if mode not in [c["id"] for c in reach_choices()]:
        return f"\"{mode}\" isn't one of the ways to reach it: " + ", ".join(c["id"] for c in reach_choices()) + "."
    if not m:
        return None
    try:
        if mode == "lab-network":
            if not (r.get("bundle") or "").strip():
                return "Paste your lab's join code, or use the one found on the USB stick."
            m.decode(r["bundle"])
        elif mode == "wireguard":
            if not (r.get("wireguard") or "").strip():
                return "Paste your WireGuard configuration (the whole file)."
            m.check_wireguard(r["wireguard"])
        elif mode == "tailscale" and (r.get("tailscale_key") or "").strip():
            m.check_key(r["tailscale_key"].strip())
    except Exception as e:                   # reach.BundleError: its words say what's wrong
        return str(e)
    return None


REACH_KEYS = ("bundle", "wireguard", "tailscale_key")


def read_reach(got, a, problems):
    """An answer file's reach = "MODE" (with reach_bundle, reach_wireguard or reach_tailscale_key) under
    [install], on both editions."""
    if not got.get("reach"):
        return
    a["reach"] = {"mode": got["reach"], **{k: got[f"reach_{k}"] for k in REACH_KEYS if got.get(f"reach_{k}")}}
    p = check_reach(a["reach"])
    if p:
        problems.append("reach: " + p)


def reach_answer(a):
    """What bromigos-iso-install hands reach.stage: {mode, bundle, wireguard, tailscale_key}."""
    r = dict(a.get("reach") or {})
    r["mode"] = r.get("mode") or reach_default()
    return r


def reach_line(a):
    """The answer file's reach line (the mode; its key and configuration are never written out)."""
    mode = (a.get("reach") or {}).get("mode")
    return [f"reach = {toml_value(mode)}"] if mode and mode != reach_default() else []


def reach_packages(r):
    mode = (r or {}).get("mode") or reach_default()
    return list(next((c.get("packages", []) for c in reach_choices() if c["id"] == mode), []))


# ── storage ─────────────────────────────────────────────────────────────────────────────
def data_disks(probe, a):
    """The disks that can hold data: every one but the system's and the USB stick's."""
    return [d for d in (probe or {}).get("disks", []) if not d.get("medium") and d["path"] != a.get("disk")]


def check_storage(a, probe):
    s = srv(a)
    chosen = [d for d in data_disks(probe, a) if d["path"] in s.get("data_disks", [])]
    s["data_disks"] = [d["path"] for d in chosen]
    if s.get("data_layout") == "raid1" and len(chosen) < 2:
        return ("Two copies (RAID1) needs two or more data disks: tick another disk, or choose One copy.")
    return None


def storage_words(s, disks):
    chosen = [d for d in disks if d["path"] in s.get("data_disks", [])]
    if not chosen:
        return "No data disks: files and apps stay on the system disk, at /srv."
    total = sum(d["size"] for d in chosen)
    from .disks import plain_size
    if s.get("data_layout") == "raid1" and len(chosen) >= 2:
        return (f"{len(chosen)} disks, two copies of everything (RAID1): about {plain_size(total // 2)} for your data at "
                "/srv/data. If one disk fails, nothing is lost.")
    return (f"{len(chosen)} disk{'s' if len(chosen) != 1 else ''}, one copy: {plain_size(total)} for your data at /srv/data. "
            "If a disk fails, what's on it is lost: back it up.")


def erases(d):
    """What formatting a data disk loses, or None when it's empty."""
    if not d.get("partitions"):
        return None
    return d.get("options", {}).get("erase", {}).get("loses") or d.get("summary")


# ── encryption ──────────────────────────────────────────────────────────────────────────
def tpm():
    """This machine's TPM 2.0 chip: True, False."""
    if os.environ.get("BROMIGOS_INSTALLER_TPM") is not None:
        return os.environ["BROMIGOS_INSTALLER_TPM"] == "1"
    if fake():
        return True
    return _sys("/sys/class/tpm/tpm0/tpm_version_major") == "2"


UNLOCK = {   # (title, words)
    "tpm": ("Encrypt, unlocked by this computer's security chip (recommended)",
            "The disk opens by itself at every start, so updates can restart it at night. Its passphrase stays the "
            "spare key: you type it once at the first start, and again only if the chip refuses (say, after a "
            "firmware change). A server that won't start is mended from Field Kit in the boot menu."),
    "passphrase": ("Encrypt, and type the passphrase after each restart",
                   "The safest, but after an update restarts it, the server waits at the passphrase until someone types "
                   "it: your phone says so. Updates that need a restart wait for you."),
    "none": ("Don't encrypt the system disk",
             "It restarts by itself after updates. Anyone who takes the disk can read it, as on most home servers."),
}


def unlock_choices(has_tpm):
    return ["tpm", "passphrase", "none"] if has_tpm else ["passphrase", "none"]


def check_unlock(a):
    from . import common
    s = srv(a)
    if a.get("mode") == "reinstall":
        return None
    if s.get("unlock") not in unlock_choices(tpm()):
        return "Choose how the disk unlocks: with a passphrase after each restart, or not encrypted."
    a["encrypt"] = s["unlock"] != "none"
    if a["encrypt"] and a.get("separate_passphrase"):
        return common.check_password(a.get("passphrase", ""), a.get("passphrase2", a.get("passphrase", "")), "passphrase")
    return None


# ── updates ─────────────────────────────────────────────────────────────────────────────
MODES = {
    "auto": ("Update by itself (recommended)",
             "Each night in the window: a snapshot, the update, a health check, and a rollback if it isn't healthy. It "
             "restarts only when an update needs it, and only in the window."),
    "download": ("Download, then ask me",
                 "It fetches the updates at night, then your phone says they're ready: one tap installs them, the same "
                 "safe way."),
    "off": ("I'll update it myself",
            "Nothing happens by itself. Arch moves quickly: a server left for months is harder to bring up to date."),
}
WINDOW_RE = re.compile(r"^([01]\d|2[0-3]):([0-5]\d)-([01]\d|2[0-3]):([0-5]\d)$")


def check_window(v):
    if not WINDOW_RE.match(v or ""):
        return "The window is two times, like 03:00-05:00."
    a, b = v.split("-")
    if a == b:
        return "The window needs a start and a different end, like 03:00-05:00."
    return None


def window_words(w):
    a, b = w.split("-")

    def h(t):
        hh, mm = (int(x) for x in t.split(":"))
        ap = "AM" if hh < 12 else "PM"
        return f"{(hh % 12) or 12}{':%02d' % mm if mm else ''} {ap}"
    return f"{h(a)} to {h(b)}"


def window_calendar(w):
    """(OnCalendar, RandomizedDelaySec) for the update timer: the window's start, spread over all
    but its last half hour (a restart then still lands inside it)."""
    a, b = w.split("-")
    ah, am = (int(x) for x in a.split(":"))
    bh, bm = (int(x) for x in b.split(":"))
    minutes = ((bh * 60 + bm) - (ah * 60 + am)) % (24 * 60)
    return f"*-*-* {a}:00", f"{max(0, minutes - 30)}min"


def check_updates(a):
    s = srv(a)
    if s.get("update_mode") not in MODES:
        return "Choose how it updates."
    return check_window(s.get("update_window"))


# ── services ────────────────────────────────────────────────────────────────────────────
def nvidia():
    if os.environ.get("BROMIGOS_INSTALLER_NVIDIA") is not None:
        return os.environ["BROMIGOS_INSTALLER_NVIDIA"] == "1"
    if fake():
        return False
    for d in glob.glob("/sys/bus/pci/devices/*"):
        if _sys(os.path.join(d, "vendor")) == "0x10de" and _sys(os.path.join(d, "class")).startswith("0x03"):
            return True
    return False


def ups():
    if os.environ.get("BROMIGOS_INSTALLER_UPS") is not None:
        return os.environ["BROMIGOS_INSTALLER_UPS"] == "1"
    vendors = set(presets().get("base", {}).get("ups_usb_vendors", []))
    return any(_sys(os.path.join(d, "idVendor")) in vendors for d in glob.glob("/sys/bus/usb/devices/*"))


def service_shown(svc):
    if svc.get("needs") == "nvidia" and not nvidia():
        return False
    return True


def provision_picks(a, hw=None, probe=None):
    """The catalogue's ticked items: the roles' suggestions until edited by hand."""
    from . import provision as PV
    s = srv(a)
    if s.get("provision") is None:
        mode = s.get("lab") or "none"
        s["provision"] = [i for i in PV.recommend(roles_of(s) or ["plain"], hw or PV.hardware(probe), mode)
                          if PV.item(i) and mode in PV.labs_of(PV.item(i))]
    return s["provision"]


def suggested_by(a):
    """{item id: [who suggests it]} for the catalogue's "suggested by" marks: the roles' picks, and
    a new lab's."""
    from . import provision as PV
    s = srv(a)
    rids = roles_of(s) or ["plain"]
    hw = PV.hardware()
    picked = set(PV.recommend(rids, hw, s.get("lab") or "none"))
    out = {}
    for x in PV.items():
        if x["id"] not in picked:
            continue
        mine = [r for r in rids if PV.norm_role(r) in {PV.norm_role(y) for y in x.get("roles", [])}]
        out[x["id"]] = [(role(r) or {}).get("title", r) for r in mine] or (["a new lab"] if s.get("lab") == "new" else ["what it needs"])
    return out


def check_services(a):
    s = srv(a)
    from . import provision as PV
    if s.get("lab") == "join" and not (s.get("lab_join") or {}):
        return "Choose how it joins your lab: its connection file or a join bundle on the USB stick, or pairing with BRODEC."
    bundle = (s.get("lab_join") or {}).get("bundle")
    if bundle and not os.path.isfile(bundle) and not fake():
        return f"There's no join bundle at {bundle}. Copy it onto the USB stick, or choose pairing with BRODEC."
    ids, _ = PV.resolve(provision_picks(a))
    clash = PV.conflicts(ids)
    if clash:
        return clash[0]
    if (s.get("services") or {}).get("pelican-wings"):
        url = (s.get("pelican_url") or "").strip()
        if url and not re.match(r"^https?://[^\s/]+", url):
            return "The panel's address starts with https://, for example https://panel.lab.example."
    return None


def check(sid, a, probe=None):
    """The step's answers checked: None, or what to fix, in plain words (both front ends)."""
    if sid == "role":
        return None if roles_of(srv(a)) else "Pick what this server will do: one card, or several."
    if sid == "network":
        return check_network(a)
    if sid == "access":
        return check_access(a)
    if sid == "secrets":
        return check_keys(a)
    if sid == "reach":
        return check_reach(a.get("reach"))
    if sid == "storage":
        return check_storage(a, probe)
    if sid == "unlock":
        return check_unlock(a)
    if sid == "updates":
        return check_updates(a)
    if sid == "services":
        return check_services(a)
    return None


# ── the plan: what bromigos-iso-install applies ─────────────────────────────────────────
def _uniq(xs):
    out = []
    for x in xs:
        if x not in out:
            out.append(x)
    return out


def plan(a, probe=None):
    """Everything the install does for this server, resolved from the presets and the answers
    (bromigos-iso-install hands it to answers.py and server_apply.py as answers["server"]).
    Several roles merge: the union of their packages, services, firewall rule sets, health
    checks and sysctls."""
    from . import provision as PV
    P = presets()
    s = srv(a)
    base = P.get("base", {})
    rids = roles_of(s) or ["plain"]
    rs = [role(x) for x in rids]
    lab = has_lab(s)
    pk = list(base.get("packages", []))
    units = list(base.get("services", []))
    fw = list(base.get("firewall", []))
    health = list(base.get("health", []))
    sysctl = dict(base.get("sysctl", {}))
    drop = []
    for r in rs:
        wl = (r.get("with_lab") or {}) if lab and r["id"] == "games" else {}
        pk += list(r.get("packages", [])) + list(wl.get("packages", []))
        units += list(r.get("services", [])) + list(wl.get("services", []))
        fw += list(r.get("firewall", [])) + list(wl.get("firewall", []))
        health += list(r.get("health", [])) + list(wl.get("health", []))
        sysctl.update(r.get("sysctl", {}))
        drop += wl.get("drop", [])
    off_units = list(base.get("off_services", []))
    never = []
    chosen = dict(s.get("services") or {})
    for svc in services_for_roles(rids):
        on = True if svc.get("locked") else chosen.get(svc["id"], any(default_on(svc, x, lab) for x in rids))
        if svc.get("needs") == "nvidia":
            on = on and nvidia()
            if on:
                for r in rs:
                    pk += r.get("gpu_packages", [])
                    units += r.get("gpu_services", [])
        if on:
            pk += svc.get("packages", [])
            units += svc.get("units", [])
            fw += svc.get("firewall", [])
            never += svc.get("never", [])
        else:
            units = [u for u in units if u not in svc.get("units", [])]
        chosen[svc["id"]] = bool(on)
    # what it runs: the lab catalogue's picks (bromigos lab provision --local at the first start); the
    # presets' own apps only when there's no catalogue
    have_cat = bool(PV.items())
    provision, auto = PV.resolve(provision_picks(a)) if have_cat else ([], [])
    apps = [] if have_cat else [x for x in (s.get("apps") if s.get("apps") is not None else
                                            [y for r in rs for y in r.get("apps_on", [])])
                                if any(y["id"] == x for y in apps_for_roles(rids))]
    if lab and "games" in rids:
        apps = [x for x in apps if x != "minecraft"]       # the games run through the lab's panel
    for x in P.get("apps", []):
        if x["id"] in apps:
            fw += x.get("firewall", [])
            if x.get("package"):
                pk.append(x["package"])
    if ups() and chosen.get("ups", True):
        pk += base.get("ups_packages", [])          # set up by bromigos-server once it knows the UPS
    pk += reach_packages(a.get("reach"))           # the Reach step's choice (reach.CHOICES' packages)
    for d in drop:
        pk = [p for p in pk if p != d]
    pk = [p for p in pk if p not in never]
    if s.get("tailscale"):
        units.append("tailscaled.service")
        off_units = [u for u in off_units if u != "tailscaled.service"]
    data = [d for d in s.get("data_disks", [])]
    layout = s.get("data_layout") if len(data) >= 2 else "single"
    if data:
        units.append("btrfs-scrub@srv-data.timer")
    kernel = s.get("kernel") or base.get("kernel", "linux-lts")
    fallback = base.get("fallback_kernel", "linux")
    kernels = _uniq([kernel, fallback])
    mode = s.get("update_mode", "auto")
    up = P.get("updates", {})
    method = s.get("method", "dhcp")
    ssh_mode = s.get("ssh_mode", "keys")
    fw = _uniq([f for f in fw if f != "ssh" or ssh_mode != "off"])
    rules = {k: P.get("firewall", {}).get(k, {}) for k in fw}
    lab_account = any(r.get("lab_account") for r in rs)
    lab_key = (s.get("lab_key") or "").strip() if not s.get("lab_same_keys") else None
    out = {
        "schema": 1, "presets": P.get("_source"), "role": rids[0], "roles": rids, "lab": lab,
        "packages": _uniq(pk + kernels), "services": _uniq(units), "off_services": _uniq(off_units),
        "firewall": fw, "firewall_rules": rules, "health": _uniq(health), "sysctl": sysctl,
        "journald": dict(base.get("journald", {})), "ssh_config": dict(base.get("ssh", {})),
        "lsm": base.get("lsm"), "kernels": kernels, "kernel": kernel,
        "network": {"interface": s.get("interface"), "method": method, "address": s.get("address", "").strip(),
                    "prefix": int(prefix_from(s.get("prefix")) or 24) if method == "static" else None,
                    "gateway": s.get("gateway", "").strip(), "dns": split_dns(s.get("dns")) if method == "static" else [],
                    "wake_on_lan": bool(s.get("wake_on_lan")), "vlan": int(s["vlan"]) if str(s.get("vlan") or "").isdigit() else None,
                    "bond": list(s.get("bond") or [])},
        "access": {"ssh": ssh_mode != "off", "password_login": ssh_mode == "password", "keys": all_keys(a),
                   "github": s.get("github") if s.get("github_ok") else None, "tailscale": bool(s.get("tailscale")),
                   "wireguard": bool(s.get("wireguard")),
                   "lab_account": lab_account, "lab_keys": ([lab_key] if lab_key else all_keys(a)) if lab_account else []},
        "storage": {"disks": data, "layout": layout, "mount": "/srv/data",
                    "shares": [x for x in ("smb", "nfs") if chosen.get(x)], "timeline": bool(chosen.get("timeline"))},
        "unlock": (s.get("unlock") or ("passphrase" if a.get("encrypt", True) else "none")) if a.get("mode") != "reinstall" else "as-is",
        "updates": {"mode": mode, "window": s.get("update_window") or up.get("window", "03:00-05:00"),
                    "channel": up.get("channel", "live"), "notify": bool(s.get("notify_phone")),
                    "arch_news_hold": bool(up.get("arch_news_hold", True)), "reboot": True,
                    "cluster_reboots": lab and "lab" in rids},
        "toggles": chosen, "apps": apps, "docker": "docker" in pk,
        "games": {"pelican_url": (s.get("pelican_url") or "").strip(), "registry_mirror": (s.get("registry_mirror") or "").strip()}
        if "games" in rids else {},
        "lab_mode": s.get("lab") or "none", "lab_join": dict(s.get("lab_join") or {}),
        "store": dict(store_of(a)), "store_config": config_doc(store_of(a)),
        "secrets": {f"{i}/{f}": (s.get("setup_secrets", {}).get(i) or {}).get(f) for i, f, path, how in secret_paths(a)
                    if how == "typed"},
        "generate": [f"{i}/{f}" for i, f, path, how in secret_paths(a) if how == "generated"],
        "setup": {i: x for i, x in (s.get("setup") or {}).items() if x},
        "provision": provision, "provision_auto": auto, "models": list(s.get("models") or []),
        "ups": ups(), "nvidia": nvidia() and bool(chosen.get("gpu")),
    }
    return out


def toml_value(v):
    if isinstance(v, dict):
        return "{ " + ", ".join(f"{k if re.fullmatch(r'[A-Za-z0-9_-]+', str(k)) else json.dumps(str(k))} = {toml_value(x)}"
                                for k, x in v.items()) + " }"
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, int):
        return str(v)
    if isinstance(v, list):
        return "[" + ", ".join(toml_value(x) for x in v) + "]"
    return json.dumps(str(v))


# the installer's roles as bromigos-server's (server/roles/*.toml): [roles] enabled is what
# `bromigos-server setup` turns on; Media has none of its own (the lab engine sets it up)
PACKAGE_ROLES = {"lab": "lab-node", "storage": "storage", "home": "home-services", "games": "game-server",
                 "plain": "just-a-server"}


def package_roles(p):
    """[roles] enabled: bromigos-server's ids, a game server's variant (Pelican's Wings with a
    lab, else Podman), and the Cockpit extra when it's on."""
    out = []
    for r in p["roles"]:
        rid = PACKAGE_ROLES.get(r)
        if rid == "game-server":
            rid += "/pelican-wings" if p.get("docker") else "/podman"
        if rid and rid not in out:
            out.append(rid)
    if p["toggles"].get("cockpit"):
        out.append("cockpit")
    return out


def server_toml(p, pending=(), allow=None):
    """/etc/bromigos/server.toml: bromigos-server's own keys ([ssh], [firewall], [updates],
    [health]) and the installer's ([roles], [network], [storage], [unlock], [apps], [lab],
    [games], [kernel], [packages]) for bromigos-server setup to apply (docs/server.md)."""
    u = p["updates"]
    sections = [
        ("ssh", [("password", p["access"]["password_login"]), ("enabled", p["access"]["ssh"])]),
        ("firewall", [("allow", list(allow) if allow is not None else
                       [f for f in p["firewall"] if f not in ("ssh", "mdns", "node-exporter")]),
                      ("rule_sets", p["firewall"])]),
        ("updates", [("auto", u["mode"] == "auto"), ("reboot", u["reboot"]), ("mode", u["mode"]), ("window", u["window"]),
                     ("channel", u["channel"]), ("notify", u["notify"]), ("arch_news_hold", u["arch_news_hold"]),
                     ("cluster_reboots", u["cluster_reboots"])]),
        ("health", [("minutes", 10), ("checks", p["health"])]),
        ("roles", [("enabled", package_roles(p)), ("picked", p["roles"]), ("lab", p["lab"])]),
        ("boot", [("kernel", p["kernel"]), ("apparmor", bool(p["toggles"].get("apparmor", True)))]),
        ("network", [(k, v) for k, v in (("interface", p["network"]["interface"]), ("method", p["network"]["method"]),
                                          ("address", p["network"]["address"]), ("prefix", p["network"]["prefix"]),
                                          ("gateway", p["network"]["gateway"]), ("dns", p["network"]["dns"]),
                                          ("wake_on_lan", p["network"]["wake_on_lan"]), ("vlan", p["network"]["vlan"]),
                                          ("bond", p["network"]["bond"])) if v not in (None, "", [])
                     or k in ("wake_on_lan",)]),
        ("storage", [("disks", p["storage"]["disks"]), ("layout", p["storage"]["layout"]), ("mount", p["storage"]["mount"]),
                     ("shares", p["storage"]["shares"]), ("timeline", p["storage"]["timeline"])]),
        ("unlock", [("mode", p["unlock"])]),
        ("services", [("on", sorted(k for k, v in p["toggles"].items() if v)),
                      ("off", sorted(k for k, v in p["toggles"].items() if not v))]),
        ("apps", [("enabled", p["apps"])]),
        ("kernel", [("default", p["kernel"]), ("installed", p["kernels"])]),
        ("remote", [("tailscale", p["access"]["tailscale"]), ("wireguard", p["access"]["wireguard"])]),
    ]
    if p["access"]["lab_account"]:
        sections.append(("lab", [("account", "lab")]))
    if p.get("games"):
        sections.append(("games", [(k, v) for k, v in (("pelican_url", p["games"].get("pelican_url")),
                                                        ("registry_mirror", p["games"].get("registry_mirror")),
                                                        ("docker", p["docker"])) if v not in (None, "")]))
    if pending:
        sections.append(("packages", [("pending", list(pending))]))
    lines = ["# bromigOS Server's settings, from the installer (docs/server.md). bromigos-server setup applies them;",
             "# change one and run: sudo bromigos-server setup"]
    for name, items in sections:
        lines.append("")
        lines.append(f"[{name}]")
        for k, v in items:
            if v is None:
                continue
            lines.append(f"{k} = {toml_value(v)}")
    return "\n".join(lines) + "\n"


def package_plan(p, in_store, online):
    """(now, later): the plan's packages that archinstall installs from the medium, and the rest,
    installed from the network (during the install when there's one, else at the first update)."""
    if online:
        return list(p["packages"]), []
    now = [x for x in p["packages"] if in_store(x)]
    return now, [x for x in p["packages"] if x not in now]


# ── the summary ─────────────────────────────────────────────────────────────────────────
def summary(a, disk):
    """common.summary's rows for a server: [(label, value)], the one warning line."""
    from . import common
    s = srv(a)
    ed = common.edition(a.get("edition", "server"))
    kb = common.KEYBOARD.get(a.get("keyboard"), common.KEYBOARDS[0])
    rows = []
    if len(common.editions()) > 1:
        rows.append(("Kind", ed["title"]))
    rows.append(("Roles" if len(roles_of(s)) > 1 else "Role", roles_words(roles_of(s))))
    rows += [("Language", common.language_name(a["locale"])), ("Time zone", a["timezone"].replace("_", " ")),
             ("Keyboard", kb[1])]
    where = f"{disk['model']} ({disk['size_text']})" if disk else "?"
    warn = None
    if a.get("mode") == "reinstall":
        rows.append(("Disk", f"{where}: bromigOS made fresh; your home folder stays"))
    elif a.get("mode") == "erase":
        rows.append(("Disk", f"{where}: erased, then bromigOS Server on all of it"))
        lost = (disk or {}).get("options", {}).get("erase", {}).get("loses")
        warn = f"Everything on {where} is deleted: {lost}." if disk and disk.get("partitions") else None
    else:
        opt = (disk or {}).get("options", {}).get("alongside", {})
        rows.append(("Disk", f"{where}: bromigOS beside {opt.get('name') or 'what is there'}"))
    p = plan(a)
    n = p["network"]
    rows.append(("Server name", a.get("hostname") or "?"))
    ports = interfaces()
    x = port(s, ports) or {}
    how = ("fixed address " + f"{n['address']}/{n['prefix']}, router {n['gateway']}, DNS {' '.join(n['dns'])}"
           if n["method"] == "static" else "address from your router (DHCP)")
    extra = [w for w in (f"VLAN {n['vlan']}" if n["vlan"] else "", ("bonded: " + " + ".join(n["bond"])) if n["bond"] else "",
                         "Wake-on-LAN on" if n["wake_on_lan"] and x.get("kind") == "wired" else "") if w]
    rows.append(("Network", f"{n['interface'] or '?'}" + (" (Wi-Fi)" if x.get("kind") == "wifi" else "") + f": {how}"
                 + (f"; {', '.join(extra)}" if extra else "")))
    acc = p["access"]
    nk = len(acc["keys"])
    signin = {"keys": f"SSH, keys only: {nk} key{'s' if nk != 1 else ''}" + (f" (with {acc['github']}'s from GitHub)" if acc["github"] else ""),
              "password": f"SSH with keys or the password ({nk} key{'s' if nk != 1 else ''})",
              "off": "No SSH: only at this computer"}[s.get("ssh_mode", "keys")]
    rows.append(("Admin", f"{a.get('user') or '?'}: signs in at the console and over SSH, uses sudo"))
    rows.append(("Sign-in", signin))
    remote = [w for w, on in (("Tailscale", acc["tailscale"]), ("WireGuard", acc["wireguard"])) if on]
    rows.append(("Remote access", ("On: " + ", ".join(remote)) if remote else "Tailscale and WireGuard installed, both off"))
    if acc["lab_account"]:
        rows.append(("Lab account", "lab: your lab workstation's key, passwordless sudo"))
    st = p["storage"]
    rows.append(("Data disks", ("None: data stays on the system disk, at /srv" if not st["disks"] else
                                f"{', '.join(st['disks'])}: " + ("two copies (RAID1)" if st["layout"] == "raid1" else "one copy")
                                + " at /srv/data" + (f"; shared over {', '.join(x.upper() for x in st['shares'])}" if st["shares"] else ""))))
    if st["disks"]:
        warn = (warn + " " if warn else "") + f"Everything on the data disks ({', '.join(st['disks'])}) is deleted too."
    rows.append(("Disk encryption", {"tpm": "On: the security chip unlocks it at each start; the passphrase is the spare",
                                     "passphrase": "On: type the passphrase after each restart",
                                     "none": "Off", "as-is": "As it was"}.get(p["unlock"], "Off")))
    u = p["updates"]
    rows.append(("Updates", f"{MODES[u['mode']][0].split(' (')[0]}, {window_words(u['window'])}"
                 + (", snapshot and rollback" if u["mode"] != "off" else "")
                 + ("; your phone hears" if u["notify"] else "")))
    on = [svc["title"] for svc in services_for(p["role"]) if p["toggles"].get(svc["id"]) and not svc.get("locked")]
    rows.append(("Services", ", ".join(on) if on else "The safe base only"))
    from . import provision as PV
    rows.append(("Lab", {"new": "Starts a new lab on this server", "none": "Not part of a lab"}.get(
        p["lab_mode"], "Joins your lab" + (" (paired with BRODEC after the install)" if p["lab_join"].get("pair") else
                                           " (with the file from the USB stick)"))))
    if p["provision"]:
        names = [(PV.item(i) or {}).get("name", i).split(" (")[0] for i in p["provision"]]
        rows.append(("Runs", ", ".join(names) + (f"; model: {', '.join(p['models'])}" if p["models"] else "")
                     + " (set up at the first start)"))
    paths = secret_paths(a)
    rows.append(("Keys and passwords", secretstore().summary(store_of(a), [x[2] for x in paths])
                 if paths else {"vault": "Your lab's Vault", "openbao": "A new Vault on this server",
                                "local": "This server, encrypted"}.get(store_of(a)["kind"], "")))
    rmode = reach_answer(a)["mode"]
    rows.append(("Reach", next((c["title"] for c in reach_choices() if c["id"] == rmode), rmode)))
    if p["apps"]:
        rows.append(("Apps", ", ".join(next(x["title"] for x in presets().get("apps", []) if x["id"] == i) for i in p["apps"])))
    rows.append(("Kernel", f"{p['kernel']}, with {p['kernels'][-1]} as the spare in the boot menu"
                 if len(p["kernels"]) > 1 else p["kernel"]))
    rows.append(("Packages", f"Downloaded from the internet (about {ed.get('download_size', '400 MB')})"
                 if common.needs_download(ed) else "From this USB stick; anything it lacks comes from the internet"))
    return rows, warn


# ── answer files: the [server] table ────────────────────────────────────────────────────
ANSWER_KEYS = ["role", "roles", "lab", "lab_join", "provision", "models", "settings", "store", "interface", "method", "address", "prefix", "gateway", "dns", "wake_on_lan", "vlan", "bond",
               "github", "ssh_mode", "tailscale", "wireguard", "lab_key", "data_disks", "data_layout", "unlock",
               "update_mode", "update_window", "notify_phone", "services", "apps", "pelican_url", "registry_mirror",
               "kernel"]


def answers_toml_lines(a):
    """The [server] table of an answer file (common.answers_toml adds it)."""
    if not isinstance(a.get("server"), dict) or not roles_of(a["server"]):
        return reach_line(a)
    s = a["server"]
    lines = reach_line(a) + ["", "[server]"]
    for k in ANSWER_KEYS:
        v = s.get(k)
        if k == "role":
            continue
        if k == "roles":
            v = roles_of(s)
        if k == "provision":
            v = provision_picks(a)
        if k == "lab_join" and not v:
            continue
        if k == "settings":                   # each item's setup: its values, its secrets as references only
            from . import provision as PV
            v = {}
            chosen = PV.resolve(provision_picks(a))[0]
            for i in chosen:
                vals = {f: x for f, x in (s.get("setup") or {}).get(i, {}).items() if x not in (None, "")}
                for f in (s.get("setup_secrets") or {}).get(i, {}):
                    if (s["setup_secrets"][i] or {}).get(f):
                        vals[f] = secret_ref(store_of(a), i, f)
                if vals:
                    v[i] = vals
            if not v:
                continue
        if k == "store":
            v = {x: y for x, y in store_of(a).items() if x not in STORE_SECRET_KEYS and y}
        if k == "services":
            on = sorted(x for x, y in (v or {}).items() if y)
            off = sorted(x for x, y in (v or {}).items() if not y)
            if on:
                lines.append(f"services = {toml_value(on)}")
            if off:
                lines.append(f"services_off = {toml_value(off)}")
            continue
        if k == "prefix" and s.get("method") != "static":
            continue
        if v in (None, "", []) and k not in ("apps",):
            continue
        if k == "apps" and v is None:
            continue
        if k == "dns":
            v = split_dns(v)
        if k in ("prefix", "vlan") and str(v).isdigit():
            v = int(v)
        lines.append(f"{k} = {toml_value(v)}")
    if s.get("github_keys") and s.get("github_ok"):
        lines.append(f"github_keys = {toml_value(s['github_keys'])}")
    return lines


def from_answer_file(doc, a, problems, install=None):
    """An answer file's [server] table (or server.KEY lines in YAML) into a["server"], with
    what's wrong said in plain words."""
    if not doc:
        return
    s = srv(a)
    rids = list(doc.get("roles") or [doc.get("role", "plain")])     # roles = [...]; the older single role too
    bad = [r for r in rids if not role(r)]
    if bad or not rids:
        problems.append(f"server role \"{(bad or ['?'])[0]}\" isn't one of: " + ", ".join(r["id"] for r in roles()))
        return
    if "plain" in rids and len(rids) > 1:
        problems.append("server roles: \"plain\" (Just a server) goes alone; drop it, or the other roles.")
    set_roles(a, rids)
    rid = " + ".join(rids)
    if doc.get("lab"):
        s["lab_set"] = True
    if doc.get("provision") is not None:
        s["provision_edited"] = True
    for k, v in doc.items():
        if k in ("role", "roles", "services", "services_off", "github_keys", "setup_secrets", "secrets", "settings", "setup"):
            continue
        if k not in ANSWER_KEYS:
            problems.append(f"\"server.{k}\" isn't an answer the installer knows; it's ignored.")
            continue
        if k == "dns" and isinstance(v, list):
            v = " ".join(v)
        if k in ("prefix", "vlan"):
            v = str(v)
        s[k] = v
    if s.get("lab") == "join" and not s.get("lab_join"):
        s["lab_join"] = {"pair": True}
    if s.get("lab") not in ("new", "join", "none"):
        problems.append("server.lab is \"new\", \"join\" or \"none\".")
    known = {x["id"] for x in services_for_roles(rids)}
    for k, on in [(x, True) for x in doc.get("services", [])] + [(x, False) for x in doc.get("services_off", [])]:
        if k in known:
            s["services"][k] = on
        else:
            problems.append(f"server service \"{k}\" isn't one for the {rid} role.")
    from . import provision as PV
    for i, vals in dict(doc.get("settings") or doc.get("setup") or {}).items():
        if not PV.item(i):
            problems.append(f"server.settings: \"{i}\" isn't something it can run.")
            continue
        kinds = {f["id"]: f.get("kind") for f in PV.setup(i).get("field", [])}
        for f, v in dict(vals).items():
            if f not in kinds:
                problems.append(f"server.settings.{i}: \"{f}\" isn't one of its settings.")
            elif kinds[f] == "secret":
                if not (isinstance(v, dict) and set(v) == {"secret"}):
                    problems.append(f"server.settings.{i}.{f} is a secret: reference it as {{secret = \"local:{i}/{f}\"}} "
                                    "(or vault:, sops:, bitwarden:); a value is never written in an answer file.")
            else:
                s.setdefault("setup", {}).setdefault(i, {})[f] = v
    if doc.get("github_keys"):
        s["github_keys"], s["github_ok"] = list(doc["github_keys"]), True
    elif s.get("github"):                    # fetched now (the countdown waits for it)
        keys, problem = fetch_github_keys(s["github"])
        if problem:
            problems.append(f"server.github: {problem}")
        else:
            s["github_keys"], s["github_ok"] = keys, True
    if not s.get("interface"):
        ports = interfaces()
        s["interface"] = ports[0]["name"] if ports else None
    elif s["interface"] == "auto":
        ports = interfaces()
        s["interface"] = ports[0]["name"] if ports else None
    s.setdefault("ssh_mode", "keys")
    install = install or {}
    if install.get("ssh") is False and "ssh_mode" not in doc:      # [install] ssh = false: no SSH
        s["ssh_mode"] = "off"
    if install.get("ssh_password") and "ssh_mode" not in doc:
        s["ssh_mode"] = "password"
    if s.get("unlock") is None:
        s["unlock"] = "tpm" if (a.get("encrypt", True) and tpm()) else ("passphrase" if a.get("encrypt", True) else "none")
    a["encrypt"] = s["unlock"] != "none"
    for p in [check_network(a), check_unlock(a), check_updates(a), check_services(a)]:
        if p:
            problems.append("server: " + p)
    s["data_layout"] = s.get("data_layout") or "single"
    if s["data_layout"] not in ("single", "raid1"):
        problems.append("server.data_layout is \"single\" or \"raid1\".")
    elif s["data_layout"] == "raid1" and len(s.get("data_disks") or []) < 2:
        problems.append("server: RAID1 needs two or more data_disks.")
    if s.get("ssh_mode") not in ("keys", "password", "off"):
        problems.append("server.ssh_mode is \"keys\", \"password\" or \"off\".")
    elif s["ssh_mode"] == "keys" and not all_keys(a):
        problems.append("server: keys only needs a key: ssh_keys = [\"ssh-ed25519 …\"] under [install], or github = \"you\".")
    apply_access(a)


def apply_access(a):
    """The server's access answers in the installer's own keys (backend_answers reads them)."""
    s = srv(a)
    mode = s.get("ssh_mode", "keys")
    a["ssh"] = mode != "off"
    a["ssh_password"] = mode == "password"
    a["ssh_keys"] = all_keys(a) if mode != "off" else []
    a["firewall"] = True
    a["auto_updates"] = s.get("update_mode", "auto") != "off"


def backend_doc(a, disk=None):
    """The server's part of bromigos-iso-install's answers (common.backend_answers adds it)."""
    apply_access(a)
    return plan(a)


# ── the plain questions (a screen reader's: plain.py) ───────────────────────────────────
def plain_steps(a, probe, P):
    """bromigOS Server's steps as plain questions, after About you and Encryption (plain.py
    asks those the usual way): role, network, sign-in, data disks, unlock, updates, services."""
    from . import common
    s = srv(a)
    P.heading("role")
    pick_role(a, P.choose("What will this server do?", [(r["id"], f"{r['title']}: {r['summary']}") for r in roles()],
                          default=len(roles()) - 1))
    P.heading("network")
    ports = interfaces()
    if not ports:
        P.say("No network port found. Plug in a network cable or a USB network adapter; the server can join a network after "
              "the install too.")
    else:
        if wifi_only(ports):
            P.say(WIFI_ONLY_WORDS)
        s["interface"] = P.choose("Network port:", [(x["name"], f"{x['name']}, {iface_words(x)}") for x in ports])
        if P.yes("A fixed address? (No: your router gives it one, DHCP)", False):
            s["method"] = "static"
            x = port(s, ports) or {}
            s["address"] = P.ask("Address", x.get("address") or None, check_address)
            s["prefix"] = server_prefix = P.ask("Network size (24 for most home networks)", str(x.get("prefix") or 24),
                                                lambda v: check_prefix(prefix_from(v) or v, s["address"]))
            s["prefix"] = prefix_from(server_prefix) or server_prefix
            s["gateway"] = P.ask("Router (gateway)", x.get("gateway") or None,
                                 lambda v: check_gateway(v, s["address"], s["prefix"]))
            s["dns"] = P.ask("Name servers, separated by spaces", " ".join(x.get("dns") or []) or s["gateway"], check_dns)
        x = port(s, ports) or {}
        s["wake_on_lan"] = x.get("kind") == "wired" and x.get("wol") is not False and P.yes("Wake-on-LAN, so it can be "
                                                                                            "switched on over the cable?", True)
    addr, words = shown_address(a, ports)
    P.say(f"Other computers find it at {addr}. {words}")
    P.heading("access")
    P.say(common.SSH_KEY_WORDS)
    s["ssh_mode"] = P.choose("Signing in over SSH:", [("keys", "Keys only (recommended)"), ("password", "Keys or the password"),
                                                      ("off", "No SSH: only at this computer")])
    if s["ssh_mode"] == "password":
        P.say(PASSWORD_WARN)
    if s["ssh_mode"] != "off":
        a["ssh_keys"] = [k for name, k in common.stick_keys() if P.yes(f"Use the key in {name} from the USB stick's fieldkit "
                                                                      "folder?", True)]
        gh = P.ask("A GitHub user name to fetch your keys from (Enter: none)", "",
                   lambda v: None if not v else check_github_user(v))
        if gh:
            keys, problem = fetch_github_keys(gh)
            if problem:
                P.say(problem)
            else:
                for k in keys:
                    P.say(f"GitHub {gh}: {key_words(k)}")
                if P.yes("Are these your keys? Compare the fingerprints with ssh-keygen -l on your computer", False):
                    s.update(github=gh, github_keys=keys, github_ok=True)
        while s["ssh_mode"] == "keys" and not all_keys(a):
            k = P.ask("Keys only needs a key. Paste one line from your .pub file (Enter: allow the password instead)", "")
            if not k:
                s["ssh_mode"] = "password"
            elif common.check_key(k):
                P.say(common.check_key(k))
            else:
                a["ssh_keys"].append(k)
    if s.get("role") == "lab":
        P.say(LAB_ACCOUNT_WORDS)
        s["lab_same_keys"] = P.yes("Use the same keys for the lab account?", True)
        if not s["lab_same_keys"]:
            s["lab_key"] = P.ask("The lab workstation's public key", None, lambda v: common.check_key(v.strip()))
    s["wireguard"] = P.yes("Turn on WireGuard now? (It's installed either way.)", False)
    s["tailscale"] = P.yes("Turn on Tailscale now? (It's installed either way.)", False)
    disks = data_disks(probe, a)
    if disks:
        P.heading("storage")
        s["data_disks"] = [d["path"] for d in disks if P.yes(
            f"Use {d['model']} ({d['size_text']}, {d.get('summary', '')}) for data?" + (
                f" Everything on it is deleted: {erases(d)}." if erases(d) else ""), False)]
        if len(s["data_disks"]) >= 2:
            s["data_layout"] = "raid1" if P.yes("Keep two copies of everything (RAID1), so one disk can fail?", True) else "single"
        P.say(storage_words(s, disks))
    if a.get("mode") != "reinstall":
        P.heading("unlock")
        if a.get("encrypt"):
            s["unlock"] = "tpm" if tpm() and P.yes(UNLOCK["tpm"][1] + " Let the security chip unlock it?", True) else "passphrase"
            if s["unlock"] == "passphrase":
                P.say(UNLOCK["passphrase"][1])
        else:
            s["unlock"] = "none"
    P.heading("updates")
    s["update_mode"] = P.choose("How it updates:", [(m, f"{MODES[m][0]}: {MODES[m][1]}") for m in MODES])
    wins = presets().get("updates", {}).get("windows") or ["03:00-05:00"]
    if s["update_mode"] != "off":
        s["update_window"] = P.choose("When:", [(w, window_words(w)) for w in wins])
    P.heading("services")
    for svc in [x for x in services_for(s["role"]) if not x.get("locked") and service_shown(x)]:
        s["services"][svc["id"]] = P.yes(f"{svc['title']}: {svc['words']} On?", s["services"].get(svc["id"], False))
    from . import provision as PV
    st = store_of(a)
    st["kind"] = P.choose("Where its keys and passwords go:", [(b["id"], f"{b['title']}: {b['words']}")
                                                              for b in secretstore().backends()],
                          default=[b["id"] for b in secretstore().backends()].index(st["kind"]))
    s["lab"] = P.choose("Its place in your lab:", [(k, f"{t}: {w}") for k, (t, w) in PV.LAB_CHOICES.items()],
                        default=list(PV.LAB_CHOICES).index(s.get("lab") or "none"))
    s["lab_set"], s["provision"] = True, None
    picks = provision_picks(a)
    names = ", ".join((PV.item(i) or {}).get("name", i) for i in picks) or "nothing extra"
    if not P.yes(f"It will run: {names}. Keep that?", True):
        s["provision"] = [x["id"] for x in PV.items(mode=s["lab"]) if P.yes(f"{x['name']}: {x['line']} Run it?", x["id"] in picks)]
        s["provision_edited"] = True
    apply_access(a)


def done_lines(a):
    """The last page's lines for a server: where its keys live and how to recover them, and what the
    first start sets up. [(kind, words)], kind: key, recover, run."""
    if not is_server(a):
        return []
    st = store_of(a)
    S = secretstore()
    where, recover = S.where(st) if hasattr(S, "where") else ("In the store you chose.", "With its recovery keys.")
    out = [("key", "Your keys: " + where), ("recover", "To recover them: " + recover)]
    if provision_picks(a):
        out.append(("run", "At the first sign-in, the welcome tour shows the plan for what it runs; nothing runs until you "
                           "press Apply."))
    return out
