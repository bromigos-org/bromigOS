"""`bromigos lab provision --local`: a bromigOS Server sets itself up from the provisioning
catalogue (provcatalog.py), on first boot or later (docs/lab-provision.md, "The local target").

    bromigos lab provision --local [--select id,id,…] [--roles r,r] [--lab new|join|none]
                           [--from-answers FILE] [--set ITEM.FIELD=VALUE] [--hardware FILE]
                           --plan [--json]          the reviewed plan; nothing changes
    bromigos lab provision --local … --apply [--json] [--no-wait]
    bromigos lab provision --check ITEM [--json]     a live check (vpn, usenet, the item's services)

Apply prints progress lines for the installer and the first-boot tour:

    ::stage PCT words                 overall progress (0-100) and what's happening
    ::item ID STATE                   waiting | downloading | installing | done | failed | skipped-offline
    ::note ID words                   something the person should know or do (not a failure)
    ::error ID words                  why ID failed, in plain words

Items that need a download wait for a network (skipped-offline, then done when it comes);
items that don't, proceed offline. Re-running is safe: finished items are left as they are,
unless what they install changed. Secrets go to the secret store (secretstore.py), never into
a config file, the plan or the answer file.
"""
import argparse
import base64
import contextlib
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import socket
import subprocess
import sys
import time
import tomllib
import urllib.error
import urllib.request

from . import provcatalog as PC, secretstore as S

ROOT = os.environ.get("BROMIGOS_ROOT", "/")
STATE = "var/lib/bromigos/lab/provision-local.json"
QUADLET_DIR = "etc/containers/systemd"
APPS = "srv/apps"
ANSWERS = "/var/log/bromigos/install-answers.toml"
STATES = ("waiting", "downloading", "installing", "done", "failed", "skipped-offline")
K3S_VERSION = "v1.37.1+k3s1"
ESO_CHART = ("https://charts.external-secrets.io", "external-secrets", "2.14.0")
WINGS = ("v1.0.0-rc.1", {"x86_64": ("wings_linux_amd64", "19dda386e02041da1f1fbcc73f34e4bb01c1fbc2d499aac79a6be3a51ba7f0e8"),
                         "aarch64": ("wings_linux_arm64", "ed7deafe0aef2acd3adae73103d2a01b57e8a7eaa56950194bdff11f87f37ff3")})
GLUETUN = {"pia": ("private internet access", "openvpn", "on"), "protonvpn": ("protonvpn", "openvpn", "on"),
           "mullvad": ("mullvad", "wireguard", "off")}
# the web apps Caddy names (<sub>.<host>.local → the app's port)
WEB = {"start-page": "home", "photos": "photos", "passwords": "passwords", "documents": "documents",
       "home-automation": "home", "uptime": "uptime", "jellyfin": "media", "seerr": "requests", "monitoring": "graphs",
       "navidrome": "music", "audiobookshelf": "books", "file-sync": "sync", "s3": "s3", "pelican-panel": "games"}
MEDIA_FOLDERS = ("movies", "tv", "music", "books", "podcasts", "youtube", "downloads", "downloads/tv-sonarr",
                 "downloads/radarr", "downloads/lidarr", "downloads/soulseek", "downloads/incomplete")
CATEGORIES = {"sonarr": ("tv-sonarr", "tvCategory", 8989, "v3"), "radarr": ("radarr", "movieCategory", 7878, "v3"),
              "lidarr": ("lidarr", "musicCategory", 8686, "v1")}
# Recyclarr's TRaSH profiles (trash ids from TRaSH-Guides' JSON): WEB-1080p for shows, HD
# Bluray + WEB for films; Language: Not English and MULTi for the language settings
TRASH = {"sonarr": {"profile": "72dae194fc92bf828f32cde7744e51a1", "not_english": "69aa1e159f97d860440b04cd6d590c4f",
                    "multi": "7ba05c6e0e14e793538174c679126996", "type": "series"},
         "radarr": {"profile": "d1d67249d3890e49bc12e275d989a7e9", "not_english": "0dc8aec3bd1c47cd6c40c46ecd27e846",
                    "multi": "4b900e171accbfb172729b63323ea8ca", "type": "movie"}}


class ProvisionError(Exception):
    pass


def at(rel, root=None):
    return os.path.join(root or ROOT, rel.lstrip("/"))


def run(argv, data=None, env=None, timeout=3600):
    """Never include a command's output in an error: it may hold a key."""
    try:
        r = subprocess.run(argv, input=data, capture_output=True, text=True, timeout=timeout,
                           env=dict(os.environ, **env) if env else None,
                           **({"stdin": subprocess.DEVNULL} if data is None else {}))
    except (OSError, subprocess.TimeoutExpired) as e:
        return 127, "", type(e).__name__
    return r.returncode, r.stdout, r.stderr


# ---------------------------------------------------------------- hardware
def detect(root="/"):
    """This machine: {cpu, ram_gb, disk_gb, gpu, gpu_vram_gb, gpu_name, arch}."""
    from . import hardware as H
    import platform
    hw = {"cpu": os.cpu_count() or 1, "arch": platform.machine()}
    try:
        kib = int(next(l.split()[1] for l in open(at("proc/meminfo", root)) if l.startswith("MemTotal:")))
        hw["ram_gb"] = round(kib / 1024 ** 2, 1)
    except (OSError, StopIteration, ValueError):
        hw["ram_gb"] = None
    base = at("srv", root) if os.path.isdir(at("srv", root)) else root
    hw["disk_gb"] = round(shutil.disk_usage(base).free / 1024 ** 3, 1)
    hw.update(gpu=False, gpu_vram_gb=0, gpu_name="")
    try:
        facts = H.parse(H.collect(root))
        kind, vram = H.legacy(facts)
        if kind != "none":
            g = next((x for x in facts["gpus"] if x["ready"] and x["vendor"].lower() == kind), {})
            hw.update(gpu=kind, gpu_vram_gb=round(vram, 1), gpu_name=g.get("model", ""))
    except Exception:                              # noqa: BLE001  no GPU facts: no GPU
        pass
    return hw


# ---------------------------------------------------------------- the answer file
def read_answers(path):
    """The installer's [server] table: {roles, lab, lab_join, provision, models, settings}."""
    try:
        with open(path, "rb") as f:
            doc = tomllib.load(f)
    except OSError:
        raise ProvisionError(f"can't read the answer file {path}") from None
    except tomllib.TOMLDecodeError as e:
        raise ProvisionError(f"the answer file {path} isn't valid TOML: {e}") from None
    s = doc.get("server") or {}
    lab = s.get("lab", "none")
    if lab not in PC.LABS:
        raise ProvisionError(f"[server] lab is new, join or none, not {lab!r}")
    roles = s.get("roles") or ([s["role"]] if s.get("role") else [])
    return {"roles": list(roles), "lab": lab, "lab_join": dict(s.get("lab_join") or {}),
            "provision": s.get("provision"), "models": s.get("models"), "settings": dict(s.get("settings") or {})}


def check_settings(settings, cat):
    """Settings are setup fields by id. A secret field holds a reference, never the value."""
    out = {}
    for item, fields in (settings or {}).items():
        it = cat.get(item)
        if not it:
            raise ProvisionError(f"settings for {item!r}, which isn't an item")
        defs = {f["id"]: f for f in ((it.get("setup") or {}).get("field") or [])}
        for k, v in fields.items():
            if k not in defs:
                raise ProvisionError(f"{item} has no setting {k!r}")
            if defs[k]["kind"] == "secret":
                if not S.is_ref(v):
                    raise ProvisionError(f"{item}.{k} is a secret: save it with `bromigos lab secrets set {item}/{k}`, "
                                         f"or reference it as {{secret = \"local:{item}/{k}\"}}; never write it in the answer file")
            elif S.is_ref(v):
                raise ProvisionError(f"{item}.{k} isn't a secret")
        out[item] = dict(fields)
    return out


def setting(settings, it, field):
    """A setup field's value: the given one, else its default."""
    v = (settings.get(it["id"]) or {}).get(field)
    if v is not None:
        return v
    f = next((f for f in ((it.get("setup") or {}).get("field") or []) if f["id"] == field), None)
    return f.get("default") if f else None


# ---------------------------------------------------------------- the plan
def build_plan(selected=None, roles=None, lab="none", lab_join=None, models=None, settings=None, hw=None,
               preset=None, path=None):
    """The reviewed plan as a dict (JSON-able, deterministic for the same input)."""
    cat = PC.by_id(path)
    hw = dict(hw if hw is not None else detect())
    roles = PC.norm_roles(roles) if roles else []
    settings = check_settings(settings, cat)
    lab = lab if lab in PC.LABS else "none"
    if selected is None and preset:
        if preset not in PC.TIERS:
            raise ProvisionError(f"preset is core or advanced, not {preset!r}")
        selected = PC.TIERS[preset]
    if selected is None:
        selected = PC.recommend(roles or ["base"], hw, lab, path)
    try:
        ids, added = PC.resolve(list(selected), path)
    except PC.CatalogueError as e:
        raise ProvisionError(str(e)) from None
    problems = PC.conflicts(ids, path)
    serving = [i for i in ids if i in ("ollama", "vllm")]
    suggestions = PC.suggest_models(hw) if serving or "models" in ids else []
    if models is None:
        models = [m["id"] for m in suggestions if m["default"] and m["capability"] == "llm" and
                  (not serving or m["serve_with"] in serving)][:1] if "models" in ids else []
    picked_models = []
    for mid in models or []:
        m = next((x for x in suggestions if x["id"] == mid), None) or {"id": mid, "name": mid, "serve_with": serving[0] if serving else "ollama",
                                                                      "vram_gb": 0, "ram_gb": 0, "disk_gb": 0}
        picked_models.append(m)
    budget = PC.budget(ids, hw, path, picked_models)
    rows = []
    for i in ids:
        it = cat[i]
        why = PC.fits_item(it, hw)
        row = {"id": i, "name": it["name"], "group": it["group"], "line": it["line"],
               "auto_added": i in added, "install": PC.describe_item(it),
               "services": services_of(it), "ports": list(it["ports"]),
               "requires": dict(it["requires"]), "size_text": it["size_text"], "internet": bool(it["internet"]),
               "downloads": downloads_of(it, hw), "notes": ([it["note"]] if it["note"] else []) + ([why] if why else [])}
        if i == "k3s":
            row["mode"] = "server" if lab == "new" or lab == "none" else "agent"
        if it.get("setup"):
            row["settings"] = {f["id"]: ({"secret": "in the secret store"} if f["kind"] == "secret" else setting(settings, it, f["id"]))
                               for f in it["setup"].get("field", [])}
        rows.append(row)
    if picked_models:
        problems += [f"{m['name']} is served by {m['serve_with']}, which isn't chosen." for m in picked_models
                     if m["serve_with"] not in ids]
    return {"format": 1, "target": "local", "roles": roles, "lab": lab,
            "lab_join": {"bundle": bool((lab_join or {}).get("bundle")), "pair": bool((lab_join or {}).get("pair"))},
            "hardware": {k: hw.get(k) for k in ("cpu", "ram_gb", "disk_gb", "gpu", "gpu_vram_gb", "gpu_name")},
            "items": rows, "auto_added": added, "models": picked_models, "budget": budget,
            "problems": problems, "needs_internet": [r["id"] for r in rows if r["internet"]],
            "offline": [r["id"] for r in rows if not r["internet"]],
            "settings": {k: {f: v for f, v in d.items() if not S.is_ref(v)} for k, d in settings.items()},
            "secret_refs": {k: {f: v["secret"] for f, v in d.items() if S.is_ref(v)} for k, d in settings.items()
                            if any(S.is_ref(v) for v in d.values())}}


def services_of(it):
    inst = it["install"]
    if "quadlet" in inst:
        out = []
        for d in PC.template_dirs():
            p = Path(d) / inst["quadlet"]
            if p.is_dir():
                out = sorted(f.stem + ".service" for f in p.glob("*.container"))
                break
        return out
    if "pacman" in inst:
        return list(it["enable"])
    return list(STEP_UNITS.get(inst["step"], []))


def downloads_of(it, hw):
    inst = it["install"]
    if "pacman" in inst:
        vendor = hw.get("gpu") if isinstance(hw.get("gpu"), str) else None
        return ["package " + p for p in inst.get(vendor, inst["pacman"]) if vendor in inst] or \
            ["package " + p for p in inst["pacman"]]
    if "quadlet" in inst:
        return ["image " + ref.split("@")[0] for name, ref in sorted(it["images"].items()) if not name.endswith("-nvidia")
                or hw.get("gpu") == "nvidia"]
    return list(STEP_DOWNLOADS.get(inst["step"], []))


def print_plan(plan, out=print):
    out("This server's plan (nothing has changed yet):")
    for r in plan["items"]:
        extra = " (ticked for you: something you chose needs it)" if r["auto_added"] else ""
        out(f"  {r['name']}{extra}")
        how = r["install"]
        if how["kind"] == "pacman":
            pkgs = [d.split(" ", 1)[1] for d in r["downloads"] if d.startswith("package ")]
            out(f"    installs {', '.join(pkgs)} from the package repositories")
        elif how["kind"] == "quadlet":
            out(f"    runs {len(how['images'])} pinned container image{'s' if len(how['images']) != 1 else ''} with Podman")
        if r["services"]:
            out(f"    services: {', '.join(r['services'])}")
        if r["ports"]:
            out(f"    ports: {', '.join(map(str, r['ports']))}")
        out(f"    {r['size_text'] or 'nothing to download'}{'; needs the internet' if r['internet'] else '; works offline'}")
        for n in r["notes"]:
            out("    " + n)
    for m in plan["models"]:
        out(f"  Model: {m['name']} ({m['serve_with']})")
    b = plan["budget"]
    out(f"Together: about {b['ram_gb']:g} GB of memory and {b['disk_gb']:g} GB of disk"
        + (f", {b['gpu_vram_gb']:g} GB of graphics memory" if b["gpu_vram_gb"] else "") + ".")
    for n in b["notes"]:
        out("  " + n)
    for p in plan["problems"]:
        out("Problem: " + p)
    if plan["needs_internet"]:
        out(f"{len(plan['needs_internet'])} of {len(plan['items'])} items need the internet; they wait for it.")


# ---------------------------------------------------------------- rendering Quadlet templates
COND = re.compile(r"^#(if|ifnot|ifset|ifgpu):([a-z0-9_/-]+) (.*)$")
PLACE = re.compile(r"\{\{([a-z]+)(?::([a-z0-9_/-]+))?\}\}")


def template_files(name):
    for d in PC.template_dirs():
        p = Path(d) / name
        if p.is_dir():
            return sorted(f for f in p.iterdir() if f.suffix in (".container", ".volume", ".network", ".pod"))
    raise ProvisionError(f"no Quadlet template {name!r}")


def render(text, it, ctx):
    """One template file, filled: conditions kept or dropped, placeholders replaced."""
    out = []
    for line in text.splitlines():
        m = COND.match(line)
        if m:
            kind, arg, rest = m.groups()
            keep = {"if": lambda: ctx.selected_for(arg), "ifnot": lambda: not ctx.selected_for(arg),
                    "ifset": lambda: ctx.is_set(it, arg), "ifgpu": lambda: ctx.hw.get("gpu") == arg}[kind]()
            if not keep:
                continue
            line = rest
        out.append(PLACE.sub(lambda mm: ctx.value(it, mm.group(1), mm.group(2)), line))
    return "\n".join(out) + "\n"


# ---------------------------------------------------------------- the host
class Host:
    """What apply touches: files under root, commands, the network, the secret store, the
    progress lines. Tests replace run, online, sleep and the store."""

    def __init__(self, plan, root=None, run_=None, online=None, sleep=None, store=None, emit=None, hw=None,
                 hostname=None, tz=None, steps=None, clock=None):
        self.plan = plan
        self.root = root or ROOT
        self.run = run_ or run
        self._online = online
        self.sleep = sleep or time.sleep
        self.clock = clock or time.monotonic
        self.emit = emit or (lambda line: print(line, flush=True))
        self.hw = hw or plan.get("hardware") or {}
        self.cat = PC.by_id()
        self.selected = [r["id"] for r in plan["items"]]
        self.settings = plan.get("settings") or {}
        self.refs = plan.get("secret_refs") or {}
        self.hostname = hostname or socket.gethostname().split(".")[0]
        self.tz = tz or _timezone(self.root)
        self.store = store or S.open_store(root=self.root if self.root != "/" else None)
        self.steps = dict(STEPS, **(steps or {}))
        self.changed_units = set()
        self.media_ids = None

    # -- files
    def path(self, rel):
        return Path(at(rel, self.root))

    def write(self, rel, text, mode=0o644):
        p = self.path(rel)
        if p.exists() and p.read_text() == text:
            return False
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_name(p.name + ".bromigos-new")
        tmp.write_text(text)
        os.chmod(tmp, mode)
        os.replace(tmp, p)
        return True

    def mkdir(self, rel, mode=0o755, owner=None):
        p = self.path(rel)
        p.mkdir(parents=True, exist_ok=True)
        if owner and self.root == "/":
            self.must(["chown", owner, str(p)], "set the folder's owner")
        return p

    # -- commands
    def must(self, argv, what, data=None, env=None):
        rc, out, _ = self.run(argv, data, env)
        if rc:
            raise ProvisionError(f"couldn't {what} ({Path(argv[0]).name} stopped with code {rc})")
        return out

    def systemctl(self, *args):
        return self.run(["systemctl", *args])

    def online(self):
        if self._online:
            return self._online()
        if shutil.which("nmcli"):
            rc, out, _ = self.run(["nmcli", "networking", "connectivity", "check"])
            if rc == 0:
                return out.strip() == "full"
        try:
            with socket.create_connection(("pkgs.bromigos.org", 443), timeout=5):
                return True
        except OSError:
            return False

    # -- the selection, as templates and steps see it
    def selected_for(self, arg):
        if arg == "gluetun" and "gluetun" in self.selected:
            return bool(self.setting("gluetun", "kill_switch"))
        return arg in self.selected

    def setting(self, item, field):
        return setting(self.settings, self.cat[item], field)

    def is_set(self, it, field):
        f = next((f for f in ((it.get("setup") or {}).get("field") or []) if f["id"] == field), None)
        if f and f["kind"] == "secret":
            return self.store.exists(f"{it['id']}/{field}")
        return bool(self.setting(it["id"], field))

    def media_root(self):
        if "media-library" not in self.selected:
            return "/srv/media"
        where = self.setting("media-library", "where")
        return self.setting("media-library", "path") if where == "pool" else "/srv/media"

    def media_owner(self):
        if self.media_ids is None:
            try:
                import pwd
                pw = pwd.getpwnam("bromigos-media")
                self.media_ids = (pw.pw_uid, pw.pw_gid)
            except (KeyError, ImportError):
                self.media_ids = (0, 0) if self.root == "/" else (1000, 1000)
        return self.media_ids

    def value(self, it, kind, arg):
        if kind == "data":
            return "/" + APPS + "/" + it["id"]
        if kind == "media":
            return self.media_root()
        if kind == "downloads":
            return self.media_root().rstrip("/") + "/downloads"
        if kind == "tz":
            return self.tz
        if kind == "host":
            return self.hostname
        if kind == "puid":
            return str(self.media_owner()[0])
        if kind == "pgid":
            return str(self.media_owner()[1])
        if kind == "image":
            imgs = it["images"]
            if self.hw.get("gpu") == "nvidia" and arg + "-nvidia" in imgs:
                return imgs[arg + "-nvidia"]
            return imgs[arg]
        if kind == "secret":
            name = arg if "/" in arg else f"{it['id']}/{arg}"
            return S.podman_name(name)
        if kind == "setting":
            derived = self.derived(it["id"])
            if arg in derived:
                return str(derived[arg])
            v = self.setting(it["id"], arg)
            return "" if v is None else str(v)
        raise ProvisionError(f"unknown placeholder {kind}")

    def derived(self, item):
        if item == "gluetun":
            name, vtype, pf = GLUETUN[self.setting("gluetun", "provider") or "pia"]
            return {"provider_name": name, "vpn_type": vtype, "port_forwarding": pf}
        if item == "vllm":
            m = next((m for m in self.plan.get("models") or [] if m.get("serve_with") == "vllm"), None)
            return {"model": (m or {}).get("weights") or (m or {}).get("id") or ""}
        return {}

    # -- secrets
    def secrets_for(self, it, units):
        """Generated keys made once; typed keys taken from the answer file's references."""
        for name in it["secrets"]:
            kind = "apikey" if name == "api-key" else "password"
            self.store.generate(f"{it['id']}/{name}", kind, users=units)
        for field, ref in (self.refs.get(it["id"]) or {}).items():
            n = f"{it['id']}/{field}"
            if not self.store.exists(n):
                self.store.put(n, S.resolve_ref({"secret": ref}, self.store), typed=True)
            for u in units:
                self.store.use(n, u)

    def credential(self, name):
        """A local encrypted copy for a host service's LoadCredentialEncrypted= (the store's own
        file when the store is local)."""
        if isinstance(self.store, S.LocalStore):
            return S.cred_name(name)
        local = S.LocalStore(self.root if self.root != "/" else None, self.run)
        local._write(name, self.store.get(name))
        return S.cred_name(name)


def _timezone(root):
    try:
        return os.readlink(at("etc/localtime", root)).split("zoneinfo/", 1)[1]
    except (OSError, IndexError):
        return "UTC"


# ---------------------------------------------------------------- installing one item
def pacman_packages(it, hw):
    inst = it["install"]
    vendor = hw.get("gpu") if isinstance(hw.get("gpu"), str) else None
    return list(inst.get(vendor) or inst["pacman"]) if vendor in inst else list(inst["pacman"])


def missing_packages(host, pkgs):
    return [p for p in pkgs if host.run(["pacman", "-Q", p])[0] != 0]


def images_for(host, it):
    """The item's image refs for this server: NAME-nvidia in place of NAME on an NVIDIA server."""
    imgs = it["images"]
    out = []
    for name, ref in imgs.items():
        if name.endswith("-nvidia"):
            continue
        out.append(imgs[name + "-nvidia"] if host.hw.get("gpu") == "nvidia" and name + "-nvidia" in imgs else ref)
    return out


def missing_images(host, it):
    return [ref for ref in images_for(host, it) if host.run(["podman", "image", "exists", ref])[0] != 0]


def needs_download(host, it):
    inst = it["install"]
    if "pacman" in inst:
        return bool(missing_packages(host, pacman_packages(it, host.hw)))
    if "quadlet" in inst:
        return bool(missing_images(host, it))
    probe = STEP_PROBES.get(inst["step"])
    return probe(host, it) if probe else bool(it["internet"])


def pacman(host, pkgs):
    missing = missing_packages(host, pkgs)
    if missing:
        host.must(["pacman", "-S", "--needed", "--noconfirm", *missing], "install " + ", ".join(missing))


def enable(host, units, restart=False):
    for u in units:
        host.must(["systemctl", "enable", u], f"enable {u}")
        host.must(["systemctl", "restart" if restart else "start", u], f"start {u}")


def install_pacman(host, it):
    pacman(host, pacman_packages(it, host.hw))
    if it["enable"]:
        enable(host, it["enable"])


def install_quadlet(host, it):
    files = template_files(it["install"]["quadlet"])
    units = [f.stem + ".service" for f in files if f.suffix == ".container"]
    host.secrets_for(it, units)
    for ref in missing_images(host, it):
        host.must(["podman", "pull", ref], "download " + ref.split("@")[0])
    for raw in re.findall(r"\{\{secret:([a-z0-9_/-]+)\}\}", "".join(f.read_text() for f in files)):
        name = raw if "/" in raw else f"{it['id']}/{raw}"
        if host.store.exists(name) and host.run(["podman", "secret", "exists", S.podman_name(name)])[0] != 0:
            host.store._podman(name, host.store.get(name))      # a key saved before Podman's driver was set up
    host.mkdir(APPS + "/" + it["id"], 0o750)
    prepare = PREPARE.get(it["id"])
    if prepare:
        prepare(host, it)
    changed = host.write(QUADLET_DIR + "/bromigos-lab.network",
                         template_files("_common")[0].read_text())
    for f in files:
        text = render(f.read_text(), it, host)
        changed = host.write(QUADLET_DIR + "/" + f.name, text) or changed
        for line in text.splitlines():
            m = re.match(r"^Volume=(/[^:]+):", line)
            if m and m.group(1).startswith("/" + APPS):
                host.mkdir(m.group(1))
    host.must(["systemctl", "daemon-reload"], "reload systemd")
    for u in units:
        host.must(["systemctl", "restart" if changed else "start", u], f"start {u}")


def install(host, it):
    inst = it["install"]
    if "pacman" in inst:
        return install_pacman(host, it)
    if "quadlet" in inst:
        return install_quadlet(host, it)
    step = host.steps.get(inst["step"])
    if not step:
        raise ProvisionError(f"no step named {inst['step']}")
    return step(host, it)


# ---------------------------------------------------------------- the steps
def note(host, it, text):
    host.emit(f"::note {it['id']} {text}")


def step_k3s(host, it):
    mode = "server" if host.plan.get("lab") in ("new", "none") else "agent"
    if host.path("etc/rancher/k3s/k3s.yaml").exists() or host.path("etc/systemd/system/k3s-agent.service").exists():
        return
    url = host.setting("k3s", "server_url")
    if mode == "agent" and not (url and host.store.exists("k3s/token")):
        note(host, it, "Your lab adds this server to its cluster from your desktop: bromigos lab provision add-node.")
        return
    pacman(host, ["curl", "iptables-nft"])
    script = host.path("var/lib/bromigos/lab/k3s-install.sh")
    script.parent.mkdir(parents=True, exist_ok=True)
    host.must(["curl", "-sfL", "-o", str(script), "https://get.k3s.io"], "download k3s's installer")
    env = {"INSTALL_K3S_VERSION": K3S_VERSION}
    args = ["server", "--disable", "traefik", "--disable", "servicelb", "--secrets-encryption"]
    if mode == "agent":
        cred = host.credential("k3s/token")
        unit = "k3s-agent.service"
        host.write(f"etc/systemd/system/{unit}.d/50-bromigos-token.conf",
                   f"[Service]\nLoadCredentialEncrypted={cred}\nEnvironment=K3S_TOKEN_FILE=%d/{cred}\n")
        token = host.path("run/bromigos/k3s-token")
        token.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(token, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as f:
            f.write(host.store.get("k3s/token"))
        env.update(K3S_URL=url, K3S_TOKEN_FILE=str(token))
        args = ["agent"]
        try:
            host.must(["sh", str(script), *args], "install k3s", env=env)
        finally:
            token.unlink(missing_ok=True)
        return
    host.must(["sh", str(script), *args], "install k3s", env=env)


def _helm(host, it):
    from . import provision as P
    if not host.path("etc/rancher/k3s/k3s.yaml").exists():
        raise ProvisionError(f"{it['name']} needs this server's own cluster (k3s as the lab's first machine)")
    pacman(host, ["helm"])
    repo, chart, version = P.CHARTS["argocd"] if it["id"] == "argocd" else ESO_CHART
    name = "argocd" if it["id"] == "argocd" else "external-secrets"
    argv = ["helm", "upgrade", "--install", name, chart, "--repo", repo, "--version", version, "--namespace", name,
            "--create-namespace", "--wait", "--timeout", "10m", "--description", "bromigos-lab-provision"]
    if it["id"] == "external-secrets":
        argv += ["--set", "installCRDs=true"]
    host.must(argv, f"install {it['name']}", env={"KUBECONFIG": "/etc/rancher/k3s/k3s.yaml"})


def step_openbao(host, it):
    pacman(host, ["openbao"])
    host.write("etc/bromigos/lab/openbao.hcl", S.openbao_config(), 0o640)
    host.mkdir("var/log/openbao", 0o750)
    host.write("etc/systemd/system/openbao.service.d/50-bromigos.conf",
               "[Service]\nExecStart=\nExecStart=/usr/bin/bao server -config=/etc/bromigos/lab/openbao.hcl\n")
    host.write("etc/systemd/system/bromigos-openbao-unseal.service",
               "[Unit]\nDescription=Unseal this server's Vault (OpenBao)\nAfter=openbao.service\nRequires=openbao.service\n\n"
               "[Service]\nType=oneshot\nExecStartPre=/bin/sleep 3\n"
               "ExecStart=/usr/lib/bromigos/bin/bromigos-lab secrets unseal\n\n[Install]\nWantedBy=multi-user.target\n")
    host.must(["systemctl", "daemon-reload"], "reload systemd")
    enable(host, ["openbao.service"])
    host.must(["systemctl", "enable", "bromigos-openbao-unseal.service"], "enable the unseal service")
    bao = S.OpenBaoStore(root=host.root if host.root != "/" else None, run=host.run, hostname=host.hostname)
    for _ in range(30):
        try:
            bao.request("GET", "sys/seal-status")
            break
        except S.SecretError:
            host.sleep(2)
    if bao.initialise():
        note(host, it, "Vault (OpenBao) is set up. The welcome tour shows its unseal keys once: save them.")


def step_monitoring(host, it):
    pacman(host, ["prometheus", "grafana"])
    host.secrets_for(it, ["grafana.service"])
    prom = host.path("etc/prometheus/prometheus.yml")
    if prom.exists() and "bromigos" not in prom.read_text():
        shutil.copy2(prom, str(prom) + ".bromigos-orig")
    host.write("etc/prometheus/prometheus.yml",
               "# bromigos lab provision --local: this server's own numbers\nglobal:\n  scrape_interval: 30s\n"
               "scrape_configs:\n  - job_name: prometheus\n    static_configs:\n      - targets: ['127.0.0.1:9090']\n"
               "  - job_name: node\n    static_configs:\n      - targets: ['127.0.0.1:9100']\n")
    host.write("etc/bromigos/lab/grafana/datasources/bromigos.yaml",
               "apiVersion: 1\ndatasources:\n  - name: Prometheus\n    type: prometheus\n    access: proxy\n"
               "    url: http://127.0.0.1:9090\n    isDefault: true\n")
    cred = host.credential("monitoring/grafana-admin")
    host.write("etc/systemd/system/grafana.service.d/50-bromigos.conf",
               f"[Service]\nLoadCredentialEncrypted={cred}\nEnvironment=GF_SECURITY_ADMIN_PASSWORD__FILE=%d/{cred}\n"
               "Environment=GF_SERVER_HTTP_PORT=3005\nEnvironment=GF_PATHS_PROVISIONING=/etc/bromigos/lab/grafana\n"
               "Environment=GF_ANALYTICS_REPORTING_ENABLED=false\n")
    host.must(["systemctl", "daemon-reload"], "reload systemd")
    enable(host, ["prometheus.service", "grafana.service"], restart=True)


def step_backups(host, it):
    if host.path("usr/lib/systemd/system/bromigos-server-backup.timer").exists():
        note(host, it, "bromigOS Server's own nightly backup is on this server; it covers the apps too.")
        return
    pacman(host, ["restic"])
    host.secrets_for(it, ["bromigos-lab-backup.service"])
    repo = host.setting("backups", "repository") or "/srv/backups/restic"
    if repo.startswith("/"):
        host.mkdir(repo.lstrip("/"), 0o700)
    cred = host.credential("backups/restic-password")
    host.write("etc/systemd/system/bromigos-lab-backup.service",
               "[Unit]\nDescription=Back up this server's apps and settings (restic)\nAfter=network-online.target\n\n"
               f"[Service]\nType=oneshot\nLoadCredentialEncrypted={cred}\nEnvironment=RESTIC_PASSWORD_FILE=%d/{cred}\n"
               f"Environment=RESTIC_REPOSITORY={repo}\n"
               "ExecStartPre=/bin/sh -c 'restic cat config >/dev/null 2>&1 || restic init'\n"
               "ExecStart=/usr/bin/restic backup --one-file-system --exclude-caches /etc /srv /var/lib/bromigos\n"
               "ExecStartPost=/usr/bin/restic forget --keep-daily 7 --keep-weekly 4 --keep-monthly 6 --prune\n")
    host.write("etc/systemd/system/bromigos-lab-backup.timer",
               "[Unit]\nDescription=Nightly backup of this server\n\n[Timer]\nOnCalendar=*-*-* 03:30\n"
               "RandomizedDelaySec=30min\nPersistent=true\n\n[Install]\nWantedBy=timers.target\n")
    host.must(["systemctl", "daemon-reload"], "reload systemd")
    enable(host, ["bromigos-lab-backup.timer"])


def caddy_routes(host):
    blocks = ["# bromigos lab provision --local: one name per web app (tls internal: Caddy's own authority)"]
    for i in host.selected:
        sub = WEB.get(i)
        it = host.cat[i]
        if not sub or not it["ports"]:
            continue
        port = it["ports"][0] if i != "monitoring" else 3005
        blocks.append(f"{i}.{host.hostname}.local {{\n  tls internal\n  reverse_proxy 127.0.0.1:{port}\n}}")
    return "\n\n".join(blocks) + "\n"


def step_caddy(host, it):
    pacman(host, ["caddy"])
    host.write("etc/caddy/conf.d/bromigos-lab.caddy", caddy_routes(host))
    main = host.path("etc/caddy/Caddyfile")
    text = main.read_text() if main.exists() else ""
    if "import /etc/caddy/conf.d/*" not in text:
        host.write("etc/caddy/Caddyfile", text + ("\n" if text and not text.endswith("\n") else "") + "import /etc/caddy/conf.d/*\n")
    enable(host, ["caddy.service"], restart=True)


def step_passwords(host, it):
    pacman(host, ["vaultwarden", "vaultwarden-web"])
    host.write("etc/systemd/system/vaultwarden.service.d/50-bromigos.conf",
               "[Service]\nEnvironment=ROCKET_ADDRESS=127.0.0.1\nEnvironment=ROCKET_PORT=8222\n"
               "Environment=WEB_VAULT_ENABLED=true\nEnvironment=WEB_VAULT_FOLDER=/usr/share/webapps/vaultwarden-web\n"
               f"Environment=DOMAIN=https://passwords.{host.hostname}.local\n")
    host.must(["systemctl", "daemon-reload"], "reload systemd")
    enable(host, ["vaultwarden.service"], restart=True)


def step_file_sync(host, it):
    pacman(host, ["syncthing"])
    if host.run(["id", "syncthing"])[0] != 0:
        host.must(["useradd", "--system", "--create-home", "--home-dir", "/" + APPS + "/file-sync", "--shell",
                   "/usr/bin/nologin", "syncthing"], "make the syncthing account")
    host.write("etc/systemd/system/syncthing@syncthing.service.d/50-bromigos.conf",
               "[Service]\nEnvironment=STGUIADDRESS=0.0.0.0:8384\n")
    host.must(["systemctl", "daemon-reload"], "reload systemd")
    enable(host, ["syncthing@syncthing.service"])


def step_adblock(host, it):
    pacman(host, ["adguardhome"])
    host.write("etc/systemd/resolved.conf.d/50-bromigos-adguard.conf",
               "# AdGuard Home answers DNS on port 53 here\n[Resolve]\nDNSStubListener=no\n")
    host.run(["systemctl", "try-restart", "systemd-resolved.service"])
    enable(host, ["adguardhome.service"])


def step_smb(host, it):
    pacman(host, ["samba"])
    if not host.path("etc/samba/smb.conf").exists():
        host.write("etc/samba/smb.conf", "# bromigos lab provision --local: Samba with no shares yet\n[global]\n"
                   "   server role = standalone server\n   map to guest = never\n   server min protocol = SMB3\n")
    enable(host, ["smb.service"])


def step_backup_target(host, it):
    if host.run(["id", "restic-backup"])[0] != 0:
        host.must(["useradd", "--system", "--home-dir", "/srv/backups", "--shell", "/usr/bin/nologin", "restic-backup"],
                  "make the backup account")
    host.mkdir("srv/backups", 0o755)                     # the SFTP jail: root's
    host.mkdir("srv/backups/data", 0o700, owner="restic-backup:restic-backup")
    keys = host.path("etc/bromigos/lab/backup-target.keys")
    if not keys.exists():
        host.write("etc/bromigos/lab/backup-target.keys", "# one line per machine allowed to back up here\n", 0o644)
    host.write("etc/ssh/sshd_config.d/40-bromigos-backup-target.conf",
               "# bromigos lab provision --local: a backup-only account (SFTP into /srv/backups, nothing else)\n"
               "Match User restic-backup\n  AuthorizedKeysFile /etc/bromigos/lab/backup-target.keys\n"
               "  ChrootDirectory /srv/backups\n  ForceCommand internal-sftp\n  AllowTcpForwarding no\n"
               "  X11Forwarding no\n  PermitTTY no\n")
    host.run(["systemctl", "try-reload-or-restart", "sshd.service"])
    note(host, it, "Add each machine's public key to /etc/bromigos/lab/backup-target.keys; it backs up to "
                   f"sftp:restic-backup@{host.hostname}:/data.")


def step_wings(host, it):
    if host.run(["pacman", "-Q", "podman-docker"])[0] == 0:
        host.must(["pacman", "-Rdd", "--noconfirm", "podman-docker"], "make way for Docker's engine")
    pacman(host, ["docker"])
    enable(host, ["docker.service"])
    import platform
    version, by_arch = WINGS
    asset, sha = by_arch.get(platform.machine(), by_arch["x86_64"])
    dest = host.path("usr/local/bin/wings")
    if not dest.exists() or hashlib.sha256(dest.read_bytes()).hexdigest() != sha:
        tmp = host.path("var/lib/bromigos/lab/wings.download")
        tmp.parent.mkdir(parents=True, exist_ok=True)
        host.must(["curl", "-sfL", "-o", str(tmp), f"https://github.com/pelican/wings/releases/download/{version}/{asset}"],
                  "download Wings")
        if hashlib.sha256(tmp.read_bytes()).hexdigest() != sha:
            tmp.unlink()
            raise ProvisionError("the Wings download didn't match its pinned checksum; nothing was installed")
        dest.parent.mkdir(parents=True, exist_ok=True)
        os.replace(tmp, dest)
        os.chmod(dest, 0o755)
    host.write("etc/systemd/system/wings.service",
               "[Unit]\nDescription=Wings (Pelican's game node)\nAfter=docker.service\nRequires=docker.service\n"
               "ConditionPathExists=/etc/pelican/config.yml\n\n[Service]\nExecStart=/usr/local/bin/wings\n"
               "Restart=on-failure\nRestartSec=5s\n\n[Install]\nWantedBy=multi-user.target\n")
    host.must(["systemctl", "daemon-reload"], "reload systemd")
    host.must(["systemctl", "enable", "wings.service"], "enable Wings")
    if not host.path("etc/pelican/config.yml").exists():
        note(host, it, "In your Pelican panel, add this server as a node and run its auto-deploy command here; Wings starts then.")


def gguf_tag(quant):
    m = re.search(r"(UD-)?I?Q\d(_[A-Z0-9]+)*|BF16|F16", quant or "")
    return m.group(0) if m else ""


def step_models(host, it):
    for m in host.plan.get("models") or []:
        if m.get("serve_with") == "vllm":
            note(host, it, f"{m['name']}: vLLM downloads it when it starts.")
            continue
        ref = m["id"]
        if m.get("weights"):
            tag = gguf_tag(m.get("quant"))
            if "GGUF" not in m["weights"].upper() or not tag:
                raise ProvisionError(f"{m['name']} isn't packaged for Ollama; pick another model")
            ref = f"hf.co/{m['weights']}:{tag}"
        host.must(["ollama", "pull", ref], f"download {m['name']}")


def step_lab_network(host, it):
    """Join the lab's private network (bromigos lab network, docs/lab-network.md) with the join
    bundle the installer was given or one this machine found; a new lab sets it up in the tour."""
    from . import reach as R
    text = None
    given = host.plan.get("lab_join_bundle")
    if given and os.path.isfile(given):
        text = Path(given).read_text()
    elif host.plan.get("lab") == "join":
        found = R.find_bundles()
        text = found[0][1] if found else None
    if text:
        try:
            r = host.join_network(text) if hasattr(host, "join_network") else R.join_now(text, hostname=host.hostname)
        except R.BundleError as e:
            raise ProvisionError(f"the lab's join code isn't valid: {e}") from None
        if not r.get("ok"):
            raise ProvisionError(r.get("words") or "couldn't join the lab's network")
        note(host, it, r.get("words") or "This server is on your lab's network.")
        return
    if host.plan.get("lab") == "new":
        note(host, it, "Set up your lab's private network in the welcome tour (bromigos lab network setup).")
    else:
        note(host, it, "With a join code from your lab, run bromigos lab network connect; until then this server isn't on it.")


def step_media_library(host, it):
    if host.run(["id", "bromigos-media"])[0] != 0:
        host.must(["useradd", "--system", "--no-create-home", "--shell", "/usr/bin/nologin", "bromigos-media"],
                  "make the media account")
    host.media_ids = None
    where = host.setting("media-library", "where")
    root = host.media_root()
    if where in ("nfs", "smb"):
        share = host.setting("media-library", "share")
        if not share:
            raise ProvisionError("the media library's NAS share isn't set (such as 192.0.2.20:/volume1/media)")
        uid, gid = host.media_owner()
        if where == "nfs":
            pacman(host, ["nfs-utils"])
            host.write("etc/systemd/system/srv-media.mount",
                       f"[Unit]\nDescription=The media library (NFS)\nAfter=network-online.target\nWants=network-online.target\n\n"
                       f"[Mount]\nWhat={share}\nWhere=/srv/media\nType=nfs\nOptions=soft,timeo=150,retrans=3,_netdev\n\n"
                       "[Install]\nWantedBy=multi-user.target\n")
            unit = "srv-media.mount"
        else:
            pacman(host, ["cifs-utils"])
            user = host.setting("media-library", "smb_user") or "guest"
            host.secrets_for(it, ["bromigos-media-mount.service"])
            cred = host.credential("media-library/smb_password") if host.store.exists("media-library/smb_password") else None
            pw = f'PASSWD="$(cat "$CREDENTIALS_DIRECTORY/{cred}")" ' if cred else ""
            host.write("etc/systemd/system/bromigos-media-mount.service",
                       "[Unit]\nDescription=The media library (SMB)\nAfter=network-online.target\nWants=network-online.target\n\n"
                       "[Service]\nType=oneshot\nRemainAfterExit=yes\n" + (f"LoadCredentialEncrypted={cred}\n" if cred else "")
                       + f"ExecStart=/bin/sh -c '{pw}exec mount.cifs {shlex.quote(share)} /srv/media -o "
                       f"username={user},uid={uid},gid={gid},vers=3.0,soft'\nExecStop=/usr/bin/umount /srv/media\n\n"
                       "[Install]\nWantedBy=multi-user.target\n")
            unit = "bromigos-media-mount.service"
        host.mkdir("srv/media")
        host.must(["systemctl", "daemon-reload"], "reload systemd")
        enable(host, [unit])
    owner = "bromigos-media:bromigos-media"
    for sub in ("",) + MEDIA_FOLDERS:
        host.mkdir((root.lstrip("/") + "/" + sub).rstrip("/"), 0o775, owner=owner if host.root == "/" else None)
    note(host, it, "For media you own or have rights to. No sources are set up: add your own in Prowlarr.")


def step_youtube_library(host, it):
    if not host.store.exists("jellyfin/api-key"):
        note(host, it, "Finish Jellyfin's first-run page, make an API key (Dashboard › API Keys) and save it with "
                       "bromigos lab secrets set jellyfin/api-key; then run this again to add the YouTube library.")
        return
    key = host.store.get("jellyfin/api-key")
    q = "name=YouTube&collectionType=tvshows&paths=%2Fmedia%2Fyoutube&refreshLibrary=true"
    try:
        req = urllib.request.Request("http://127.0.0.1:8096/Library/VirtualFolders", headers={"X-Emby-Token": key})
        with urllib.request.urlopen(req, timeout=10) as r:
            have = [f.get("Name") for f in json.loads(r.read() or b"[]")]
        if "YouTube" not in have:
            req = urllib.request.Request("http://127.0.0.1:8096/Library/VirtualFolders?" + q, data=b"{}", method="POST",
                                         headers={"X-Emby-Token": key, "Content-Type": "application/json"})
            urllib.request.urlopen(req, timeout=20).close()
    except (urllib.error.URLError, OSError, ValueError):
        raise ProvisionError("Jellyfin didn't answer on port 8096 to add the YouTube library") from None
    note(host, it, f"On your desktop: point bromigos lab youtube at http://{host.hostname}:8945 (homelab.toml's pinchflat source).")


def step_den_tv(host, it):
    rows = []
    for i, port, kind in (("jellyfin", 8096, "jellyfin"), ("plex", 32400, "plex")):
        if i in host.selected:
            rows.append(f"  <service>\n    <type>_bromigos-media._tcp</type>\n    <port>{port}</port>\n"
                        f"    <txt-record>kind={kind}</txt-record>\n    <txt-record>txtvers=1</txt-record>\n  </service>\n")
    host.write("etc/avahi/services/bromigos-media.service",
               '<?xml version="1.0" standalone="no"?>\n<!DOCTYPE service-group SYSTEM "avahi-service.dtd">\n'
               "<!-- bromigos lab provision --local: Den TV finds this server's media servers -->\n"
               '<service-group>\n  <name replace-wildcards="yes">bromigOS media on %h</name>\n' + "".join(rows) + "</service-group>\n")
    host.run(["systemctl", "try-reload-or-restart", "avahi-daemon.service"])


STEPS = {"k3s": step_k3s, "helm-chart": _helm, "openbao": step_openbao, "monitoring": step_monitoring,
         "backups": step_backups, "caddy": step_caddy, "passwords": step_passwords, "file-sync": step_file_sync,
         "adblock": step_adblock, "smb": step_smb, "backup-target": step_backup_target, "wings": step_wings,
         "models": step_models, "lab-network": step_lab_network, "media-library": step_media_library,
         "youtube-library": step_youtube_library, "den-tv": step_den_tv}
STEP_UNITS = {"k3s": ["k3s.service"], "openbao": ["openbao.service", "bromigos-openbao-unseal.service"],
              "monitoring": ["prometheus.service", "grafana.service"], "backups": ["bromigos-lab-backup.timer"],
              "caddy": ["caddy.service"], "passwords": ["vaultwarden.service"], "file-sync": ["syncthing@syncthing.service"],
              "adblock": ["adguardhome.service"], "smb": ["smb.service"], "wings": ["docker.service", "wings.service"],
              "lab-network": ["tailscaled.service"]}
STEP_DOWNLOADS = {"k3s": ["k3s " + K3S_VERSION + " from get.k3s.io"], "helm-chart": ["package helm", "Helm chart"],
                  "openbao": ["package openbao"], "monitoring": ["package prometheus", "package grafana"],
                  "backups": ["package restic"], "caddy": ["package caddy"],
                  "passwords": ["package vaultwarden", "package vaultwarden-web"], "file-sync": ["package syncthing"],
                  "adblock": ["package adguardhome"], "smb": ["package samba"],
                  "wings": ["package docker", "Wings " + WINGS[0] + " (pinned checksum)"], "models": ["the chosen models"]}
STEP_PACKAGES = {"openbao": ["openbao"], "monitoring": ["prometheus", "grafana"], "backups": ["restic"], "caddy": ["caddy"],
                 "passwords": ["vaultwarden", "vaultwarden-web"], "file-sync": ["syncthing"], "adblock": ["adguardhome"],
                 "smb": ["samba"], "wings": ["docker"], "helm-chart": ["helm"]}
STEP_PROBES = {k: (lambda pk: lambda host, it: bool(missing_packages(host, pk)))(v) for k, v in STEP_PACKAGES.items()}
STEP_PROBES["lab-network"] = lambda host, it: host.plan.get("lab") == "join"
STEP_PROBES["youtube-library"] = lambda host, it: False


# ---------------------------------------------------------------- files some apps need first
def prepare_start_page(host, it):
    links = []
    for i in host.selected:
        x = host.cat[i]
        if i in WEB and x["ports"] and i != "start-page":
            port = 3005 if i == "monitoring" else x["ports"][0]
            links.append({x["name"]: {"href": f"http://{host.hostname}.local:{port}", "description": x["line"]}})
    base = APPS + "/start-page/config/"
    host.write(base + "services.yaml", json.dumps([{"This server": links}], indent=1) + "\n")
    for name, text in (("settings.yaml", f"title: {host.hostname}\n"), ("widgets.yaml", "[]\n"),
                       ("bookmarks.yaml", "[]\n"), ("docker.yaml", "{}\n")):
        host.write(base + name, text)


def prepare_litellm(host, it):
    rows = []
    if "ollama" in host.selected:
        for m in host.plan.get("models") or []:
            if m.get("serve_with") == "ollama":
                tag = gguf_tag(m.get("quant"))
                model = f"ollama_chat/hf.co/{m['weights']}:{tag}" if m.get("weights") and tag else "ollama_chat/" + m["id"]
                rows.append({"model_name": m["name"], "litellm_params": {"model": model, "api_base": "http://host.containers.internal:11434"}})  # privacy: allow (Podman's name for the host)
    if "vllm" in host.selected:
        for m in host.plan.get("models") or []:
            if m.get("serve_with") == "vllm":
                rows.append({"model_name": m["name"], "litellm_params": {"model": "hosted_vllm/" + (m.get("weights") or m["id"]),
                                                                        "api_base": "http://vllm:8000/v1"}})
    # YAML is a superset of JSON: the key itself comes from the environment (os.environ/…)
    host.write(APPS + "/litellm/config.yaml", json.dumps({"model_list": rows,
               "general_settings": {"master_key": "os.environ/LITELLM_MASTER_KEY"}}, indent=1) + "\n")


def recyclarr_config(host):
    lang = host.setting("media-library", "language") if "media-library" in host.selected else "English"
    dual = bool(host.setting("media-library", "dual_audio")) if "media-library" in host.selected else True
    out = ["# bromigos lab provision --local: the TRaSH guides' profiles, with your audio language",
           "# (media library settings). API keys come from the environment, never this file."]
    for app, port in (("sonarr", 8989), ("radarr", 7878)):
        if app not in host.selected:
            continue
        t = TRASH[app]
        out += [f"{app}:", f"  {app}:", f"    base_url: http://{app}:{port}", f"    api_key: !env_var {app.upper()}_API_KEY",
                f"    quality_definition:\n      type: {t['type']}", "    quality_profiles:",
                f"      - trash_id: {t['profile']}", "        reset_unmatched_scores:\n          enabled: true"]
        cfs = []
        if lang == "English":
            cfs.append((t["not_english"], -10000, "Language: Not English"))
        if dual:
            cfs.append((t["multi"], 100, "MULTi (dual audio first)"))
        if cfs:
            out.append("    custom_formats:")
            for tid, score, label in cfs:
                out += [f"      - trash_ids:\n          - {tid}  # {label}", "        assign_scores_to:",
                        f"          - trash_id: {t['profile']}\n            score: {score}"]
    return "\n".join(out) + "\n"


def prepare_recyclarr(host, it):
    host.write(APPS + "/recyclarr/config/recyclarr.yml", recyclarr_config(host))
    for app in ("sonarr", "radarr"):
        if app in host.selected:
            host.store.use(f"{app}/api-key", "recyclarr.service")


def qbit_hash(password, salt=None):
    """qBittorrent's WebUI\\Password_PBKDF2: PBKDF2-HMAC-SHA512, 100000 rounds, as @ByteArray(salt:key)."""
    salt = salt or os.urandom(16)
    key = hashlib.pbkdf2_hmac("sha512", password.encode(), salt, 100000, 64)
    return f"@ByteArray({base64.b64encode(salt).decode()}:{base64.b64encode(key).decode()})"


def prepare_qbittorrent(host, it):
    host.store.generate("qbittorrent/webui-password", "password", users=["qbittorrent.service"])
    conf = APPS + "/qbittorrent/config/qBittorrent/qBittorrent.conf"
    if not host.path(conf).exists():                   # its own file after the first start
        host.write(conf, "[Preferences]\nWebUI\\Username=admin\n"
                   f"WebUI\\Password_PBKDF2=\"{qbit_hash(host.store.get('qbittorrent/webui-password'))}\"\n"
                   "WebUI\\Port=8081\nDownloads\\SavePath=/media/downloads/\nDownloads\\TempPathEnabled=true\n"
                   "Downloads\\TempPath=/media/downloads/incomplete/\n\n[BitTorrent]\nSession\\DefaultSavePath=/media/downloads/\n", 0o600)
    cats = {c: {"save_path": f"/media/downloads/{c}"} for app, (c, *_rest) in CATEGORIES.items() if app in host.selected}
    host.write(APPS + "/qbittorrent/config/qBittorrent/categories.json", json.dumps(cats, indent=1) + "\n")


def prepare_gluetun(host, it):
    provider = host.setting("gluetun", "provider") or "pia"
    need = "gluetun/wireguard_key" if GLUETUN[provider][1] == "wireguard" else "gluetun/password"
    if not host.store.exists(need):
        raise ProvisionError(f"save your VPN {'WireGuard key' if 'wireguard' in need else 'password'} first: "
                             f"bromigos lab secrets set {need}")
    if GLUETUN[provider][1] == "openvpn" and not host.setting("gluetun", "username"):
        raise ProvisionError("type your VPN user name in the VPN's settings first")


PREPARE = {"gluetun": prepare_gluetun, "start-page": prepare_start_page, "litellm": prepare_litellm, "recyclarr": prepare_recyclarr,
           "qbittorrent": prepare_qbittorrent}


# ---------------------------------------------------------------- wiring the media apps together
def http_json(method, url, body=None, headers=None, timeout=10):
    req = urllib.request.Request(url, data=json.dumps(body).encode() if body is not None else None, method=method,
                                 headers=dict({"Content-Type": "application/json"}, **(headers or {})))
    with urllib.request.urlopen(req, timeout=timeout) as r:
        data = r.read()
        return json.loads(data) if data else None


def wire_media(host, http=None):
    """Download clients (with their categories) and root folders in Sonarr, Radarr and Lidarr.
    Idempotent: what's there by name is left alone. No sources are added, ever."""
    http = http or http_json
    done = []
    clients = [c for c in ("qbittorrent", "sabnzbd") if c in host.selected]
    downloader_host = "gluetun" if host.selected_for("gluetun") else None
    for app, (cat, field, port, ver) in CATEGORIES.items():
        if app not in host.selected or not host.store.exists(f"{app}/api-key"):
            continue
        base, hdr = f"http://127.0.0.1:{port}/api/{ver}", {"X-Api-Key": host.store.get(f"{app}/api-key")}
        try:
            have = {c.get("name") for c in http("GET", base + "/downloadclient", headers=hdr) or []}
            for c in clients:
                name = {"qbittorrent": "qBittorrent", "sabnzbd": "SABnzbd"}[c]
                if name in have:
                    continue
                if c == "qbittorrent":
                    fields = [{"name": "host", "value": downloader_host or "qbittorrent"}, {"name": "port", "value": 8081},
                              {"name": "username", "value": "admin"},
                              {"name": "password", "value": host.store.get("qbittorrent/webui-password")},
                              {"name": field, "value": cat}]
                    body = {"name": name, "enable": True, "protocol": "torrent", "priority": 1,
                            "implementation": "QBittorrent", "configContract": "QBittorrentSettings", "fields": fields, "tags": []}
                else:
                    key = sab_api_key(host)
                    if not key:
                        continue
                    fields = [{"name": "host", "value": downloader_host or "sabnzbd"}, {"name": "port", "value": 8080},
                              {"name": "apiKey", "value": key}, {"name": field, "value": cat}]
                    body = {"name": name, "enable": True, "protocol": "usenet", "priority": 1,
                            "implementation": "Sabnzbd", "configContract": "SabnzbdSettings", "fields": fields, "tags": []}
                http("POST", base + "/downloadclient", body, hdr)
                done.append(f"{app}: {name}")
            folder = {"sonarr": "/media/tv", "radarr": "/media/movies", "lidarr": "/media/music"}[app]
            roots = {r.get("path") for r in http("GET", base + "/rootfolder", headers=hdr) or []}
            if folder not in roots:
                body = {"path": folder}
                if app == "lidarr":
                    body.update(name="Music", defaultQualityProfileId=1, defaultMetadataProfileId=1)
                http("POST", base + "/rootfolder", body, hdr)
                done.append(f"{app}: {folder}")
        except (urllib.error.URLError, OSError, ValueError):
            host.emit(f"::note {app} {host.cat[app]['name']} didn't answer yet; its download clients are added on the next run.")
    if "sabnzbd" in host.selected:
        sab_servers(host, http)
    return done


def sab_api_key(host):
    ini = host.path(APPS + "/sabnzbd/config/sabnzbd.ini")
    try:
        m = re.search(r"^api_key\s*=\s*(\w+)", ini.read_text(), re.M)
    except OSError:
        return None
    return m.group(1) if m else None


def sab_servers(host, http):
    """The Usenet server and the categories, through SABnzbd's own API (its own settings file)."""
    key = sab_api_key(host)
    server = host.setting("sabnzbd", "server")
    if not key or not server:
        return
    port = 8085
    q = {"mode": "set_config", "section": "servers", "keyword": "provider", "name": "provider", "host": server,
         "port": host.setting("sabnzbd", "port"), "ssl": 1 if host.setting("sabnzbd", "ssl") else 0,
         "connections": host.setting("sabnzbd", "connections"), "username": host.setting("sabnzbd", "username") or "",
         "enable": 1, "apikey": key, "output": "json"}
    if host.store.exists("sabnzbd/password"):
        q["password"] = host.store.get("sabnzbd/password")
    import urllib.parse
    try:
        http("GET", f"http://127.0.0.1:{port}/api?" + urllib.parse.urlencode(q))
        for app, (cat, *_rest) in CATEGORIES.items():
            if app in host.selected:
                http("GET", f"http://127.0.0.1:{port}/api?" + urllib.parse.urlencode(
                    {"mode": "set_config", "section": "categories", "keyword": cat, "name": cat, "dir": cat, "apikey": key, "output": "json"}))
    except (urllib.error.URLError, OSError, ValueError):
        host.emit("::note sabnzbd SABnzbd didn't answer yet; its Usenet server is set on the next run.")
    q.clear()


# ---------------------------------------------------------------- apply
def fingerprint(it, host):
    doc = {k: it[k] for k in ("install", "images", "enable", "secrets", "ports")}
    doc["settings"] = host.settings.get(it["id"]) or {}
    if "quadlet" in it["install"] or it["id"] in ("caddy", "start-page", "den-tv", "litellm"):
        doc["selected"] = sorted(host.selected)
    if it["id"] in ("models", "litellm"):
        doc["models"] = [m.get("id") for m in host.plan.get("models") or []]
    return hashlib.sha256(json.dumps(doc, sort_keys=True).encode()).hexdigest()[:16]


class Runner:
    def __init__(self, host, wait=None, poll=10):
        self.host = host
        self.wait = wait                  # seconds to wait for a network; None: until it comes
        self.poll = poll
        self.state = self.load()
        self.status = {}

    def load(self):
        try:
            return json.loads(self.host.path(STATE).read_text())
        except (OSError, ValueError):
            return {"items": {}}

    def save(self):
        p = self.host.path(STATE)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(self.state, indent=1, sort_keys=True) + "\n")

    def item(self, i, state):
        self.status[i] = state
        self.host.emit(f"::item {i} {state}")

    def stage(self, words):
        done = sum(1 for s in self.status.values() if s in ("done", "failed"))
        total = max(1, len(self.status))
        self.host.emit(f"::stage {int(100 * done / total)} {words}")

    def blocked(self, it):
        """None, or (state, why) when a need isn't done."""
        for need in it["needs"]:
            alts = [a for a in PC.alternatives(need) if a in self.status]
            st = [self.status[a] for a in alts]
            if not alts or "done" in st:
                continue
            if all(s == "failed" for s in st):
                return "failed", f"it needs {self.host.cat[alts[0]]['name']}, which didn't install"
            return "wait", None
        return None

    def attempt(self, i, offline):
        host = self.host
        it = host.cat[i]
        fp = fingerprint(it, host)
        prev = self.state["items"].get(i) or {}
        if prev.get("state") == "done" and prev.get("fingerprint") == fp:
            self.item(i, "done")
            return
        b = self.blocked(it)
        if b and b[0] == "failed":
            self.item(i, "failed")
            host.emit(f"::error {i} {it['name']} wasn't installed: {b[1]}.")
            return
        if b:
            return
        try:
            download = needs_download(host, it)
        except Exception:                          # noqa: BLE001  a probe that can't tell: assume a download
            download = bool(it["internet"])
        if download and offline:
            if self.status.get(i) != "skipped-offline":
                self.item(i, "skipped-offline")
            return
        self.stage(f"Installing {it['name']}")
        if download:
            self.item(i, "downloading")
        self.item(i, "installing")
        try:
            install(host, it)
        except (ProvisionError, S.SecretError, OSError) as e:
            self.item(i, "failed")
            host.emit(f"::error {i} {it['name']}: {e}")
            self.state["items"][i] = {"state": "failed"}
            self.save()
            return
        self.item(i, "done")
        self.state["items"][i] = {"state": "done", "fingerprint": fp}
        self.save()

    def pending(self):
        return [i for i in self.order if self.status.get(i) not in ("done", "failed")]

    def run(self):
        host = self.host
        self.order = [r["id"] for r in host.plan["items"]]
        if host.plan.get("problems"):
            for p in host.plan["problems"]:
                host.emit("::error plan " + p)
            return 1
        for i in self.order:
            self.item(i, "waiting")
        self.stage("Checking what's here")
        self.prepare_secrets()
        online = host.online()
        started = host.clock()
        while True:
            before = None
            while before != dict(self.status):          # until nothing more can move
                before = dict(self.status)
                for i in self.pending():
                    self.attempt(i, offline=not online)
            left = self.pending()
            if not left:
                break
            if online:
                # still blocked while online: what they wait for was skipped and nothing can move
                for i in left:
                    self.item(i, "failed")
                    host.emit(f"::error {i} {host.cat[i]['name']} couldn't start: what it needs isn't there.")
                break
            if self.wait is not None and host.clock() - started >= self.wait:
                host.emit(f"::error network {len(left)} item{'s' if len(left) != 1 else ''} wait for the internet "
                          "(" + ", ".join(left) + "). They install when you run this again with a network.")
                return 75
            self.stage("Waiting for the internet")
            host.sleep(self.poll)
            online = host.online()
        if any(i in host.selected for i in CATEGORIES):
            try:
                wire_media(host)
            except Exception:                      # noqa: BLE001  wiring never fails the apply
                host.emit("::note media The media apps are installed; their download clients are wired on the next run.")
        failed = [i for i, s in self.status.items() if s == "failed"]
        self.host.emit("::stage 100 " + ("Done" if not failed else f"Done, but {len(failed)} didn't install"))
        self.host.emit("::note secrets " + host.store.summary())
        return 1 if failed else 0

    def prepare_secrets(self):
        """Containers read keys through Podman's shell driver (systemd-creds on disk)."""
        if not self.host.path(S.PODMAN_DROPIN).exists():
            self.host.write(S.PODMAN_DROPIN, S.podman_driver_conf())


# ---------------------------------------------------------------- checks the UI calls
def check(item, host, connect=None):
    """{ok, message}: a live check of one item, in plain words."""
    it = host.cat.get(item)
    if not it:
        return {"ok": False, "message": f"no item named {item}"}
    kind = (it.get("setup") or {}).get("check")
    if kind == "vpn":
        rc, _, _ = host.run(["podman", "healthcheck", "run", "gluetun"])
        if rc == 0:
            return {"ok": True, "message": "The VPN is connected; the downloaders use only its connection."}
        return {"ok": False, "message": "The VPN isn't connected. Check the provider, user name and password "
                                        "(journalctl -u gluetun shows why)."}
    if kind == "usenet":
        return usenet_check(host, connect=connect)
    units = services_of(it)
    bad = [u for u in units if host.run(["systemctl", "is-active", "--quiet", u])[0] != 0]
    if bad:
        return {"ok": False, "message": f"{it['name']}: {', '.join(bad)} isn't running."}
    return {"ok": True, "message": f"{it['name']} is running."}


def usenet_check(host, connect=None):
    """Connect to the provider's server, read its greeting and sign in (AUTHINFO): the same as
    SABnzbd's own Test Server button."""
    import ssl as _ssl
    server = host.setting("sabnzbd", "server")
    if not server:
        return {"ok": False, "message": "Type your provider's server address first."}
    port = int(host.setting("sabnzbd", "port") or 563)
    use_ssl = bool(host.setting("sabnzbd", "ssl"))
    try:
        if connect:
            sock = connect(server, port, use_ssl)
        else:
            raw = socket.create_connection((server, port), timeout=15)
            sock = _ssl.create_default_context().wrap_socket(raw, server_hostname=server) if use_ssl else raw
        f = sock.makefile("rwb")
        greet = f.readline().decode(errors="replace")
        if not greet.startswith(("200", "201")):
            return {"ok": False, "message": f"{server} answered, but not as a news server."}
        user = host.setting("sabnzbd", "username")
        if user:
            f.write(f"AUTHINFO USER {user}\r\n".encode())
            f.flush()
            r = f.readline().decode(errors="replace")
            if r.startswith("381"):
                pw = host.store.get("sabnzbd/password") if host.store.exists("sabnzbd/password") else ""
                f.write(f"AUTHINFO PASS {pw}\r\n".encode())
                f.flush()
                pw = None
                r = f.readline().decode(errors="replace")
            if not r.startswith("281"):
                return {"ok": False, "message": f"{server} refused the user name or password."}
        f.write(b"QUIT\r\n")
        f.flush()
        sock.close()
        return {"ok": True, "message": f"Connected to {server} on port {port}{' with SSL' if use_ssl else ''}" +
                                       (" and signed in." if user else ".")}
    except (OSError, _ssl.SSLError):
        return {"ok": False, "message": f"Couldn't connect to {server} on port {port}. Check the address and port."}


# ---------------------------------------------------------------- the end screen
def where_keys_live(store):
    """The plain summary for the installer's and the tour's last screen."""
    doc = {"summary": store.summary(), "recovery": store.recovery_text()}
    if isinstance(store, S.LocalStore):
        doc["bundle"] = store.recovery_bundle()
    return doc


# ---------------------------------------------------------------- CLI
def main(argv):
    p = argparse.ArgumentParser(prog="bromigos lab provision --local",
                                description="Set this server up from the provisioning catalogue")
    p.add_argument("--local", action="store_true")
    p.add_argument("--select", default=None, help="item ids, comma-separated (default: what the roles tick)")
    p.add_argument("--roles", default=None, help="lab-node, storage, home-services, game-server, media, base")
    p.add_argument("--lab", choices=PC.LABS, default=None)
    p.add_argument("--preset", choices=tuple(PC.TIERS), default=None, help="the remote path's Core or Advanced")
    p.add_argument("--models", default=None, help="model ids from the plan's suggestions, comma-separated")
    p.add_argument("--from-answers", default=None, metavar="FILE", help=f"the installer's answer file ({ANSWERS})")
    p.add_argument("--set", action="append", default=[], metavar="ITEM.FIELD=VALUE", help="a setup field (not a secret)")
    p.add_argument("--hardware", default=None, metavar="FILE", help=argparse.SUPPRESS)
    p.add_argument("--plan", action="store_true")
    p.add_argument("--apply", action="store_true")
    p.add_argument("--no-wait", action="store_true", help="don't wait for the internet; exit 75 if items are left")
    p.add_argument("--wait", type=int, default=None, help="seconds to wait for the internet (default: until it comes)")
    p.add_argument("--check", default=None, metavar="ITEM")
    p.add_argument("--json", action="store_true")
    a = p.parse_args(argv)
    try:
        cat = PC.by_id()
        ans = read_answers(a.from_answers) if a.from_answers else {}
        settings = {k: dict(v) for k, v in (ans.get("settings") or {}).items()}
        for s in a.set:
            key, _, value = s.partition("=")
            item, _, field = key.partition(".")
            if not item or not field:
                raise ProvisionError(f"--set ITEM.FIELD=VALUE, not {s!r}")
            v = {"true": True, "false": False}.get(value, int(value) if value.isdigit() else value)
            settings.setdefault(item, {})[field] = v
        hw = json.loads(Path(a.hardware).read_text()) if a.hardware else detect()
        roles = a.roles.split(",") if a.roles else ans.get("roles") or []
        lab = a.lab or ans.get("lab") or "none"
        selected = a.select.split(",") if a.select else ans.get("provision")
        models = a.models.split(",") if a.models else ans.get("models")
        plan = build_plan(selected, roles, lab, ans.get("lab_join"), models, settings, hw, a.preset)
        if (ans.get("lab_join") or {}).get("bundle"):
            plan["lab_join_bundle"] = ans["lab_join"]["bundle"]
        if a.check:
            host = Host(plan, hw=hw)
            r = check(a.check, host)
            print(json.dumps(r) if a.json else r["message"])
            return 0 if r["ok"] else 1
        if not a.apply:
            if a.json:
                print(json.dumps({k: v for k, v in plan.items() if k != "lab_join_bundle"}, indent=1, sort_keys=True))
            else:
                print_plan(plan)
            return 0 if not plan["problems"] else 1
        if os.geteuid() != 0 and ROOT == "/":
            raise ProvisionError("applying needs root: sudo bromigos lab provision --local --apply …")
        host = Host(plan, hw=hw)
        code = Runner(host, wait=0 if a.no_wait else a.wait).run()
        if a.json:
            print(json.dumps({"result": code, "keys": where_keys_live(host.store)}))
        return code
    except (ProvisionError, PC.CatalogueError, S.SecretError, FileNotFoundError) as e:
        if a.json:
            print(json.dumps({"error": str(e)}))
        print("bromigos lab provision: " + str(e), file=sys.stderr)
        return 1
