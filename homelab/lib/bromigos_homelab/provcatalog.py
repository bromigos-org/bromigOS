"""The provisioning catalogue: what a bromigOS Server (or any lab machine) can run, as items to
tick (share/provision-catalogue.toml; docs/lab-provision.md, "The local target").

    from bromigos_homelab import provcatalog as PC
    PC.load()                                 # [item, …]: every [[item]], with defaults filled in
    PC.groups()                               # [{id, name, icon, glyph}, …]
    PC.resolve(["argocd"])                    # (["k3s", "argocd"], ["k3s"]): needs first, and what was added
    PC.budget(["photos"], hw)                 # {cpu, ram_gb, disk_gb, gpu_vram_gb, fits, notes}
    PC.recommend(["media"], hw, lab="none")   # the ids a role ticks, sized to the hardware
    PC.suggest_models(hw)                     # models from the lab's model catalogue for this GPU

hw is a dict: {cpu, ram_gb, disk_gb, gpu (False, True, or "nvidia" / "amd" / "intel"),
gpu_vram_gb, gpu_name}. localprovision.detect() reads this machine's. Nothing here installs.
"""
import os
import re
import tomllib

HERE = os.path.dirname(os.path.abspath(__file__))
SHARE = os.environ.get("BROMIGOS_SHARE_DIR") or "/usr/share/bromigos"
GROUPS = ("lab-core", "ai", "network", "storage", "games", "home", "media", "brodec")
ROLES = ("lab-node", "storage", "home-services", "game-server", "media", "base")
ROLE_ALIASES = {"just-a-server": "base", "lab": "lab-node", "plain": "base", "home": "home-services",
                "games": "game-server"}
LABS = ("new", "join", "none")
INSTALL_KINDS = ("pacman", "quadlet", "step")
FIELD_KINDS = ("text", "number", "bool", "choice", "secret", "path")
# bromigos_textual.ICONS' keys (the Nerd Font / console / ASCII table the TUIs share)
GLYPHS = ("welcome", "checks", "edition", "keyboard", "disk", "bitlocker", "user", "encryption", "ssh", "summary",
          "install", "done", "auto", "network", "vector", "lab", "phone", "tour", "server", "desktop", "windows",
          "linux", "bromigos", "chip", "usb", "check", "cross", "alert", "erase", "split", "recovery", "free",
          "power", "boot", "people", "copy", "key", "lock", "unlock", "clock", "info", "edit", "shell", "wired",
          "wifi", "nonet", "remote", "update", "settings", "search", "shield", "language", "idcard", "computer",
          "cloud", "book", "rollback", "fieldkit")
OS_RAM_GB = 1.0          # what the Server base itself uses
DISK_HEADROOM = 0.10     # keep a tenth of the disk free
# the remote path's presets, as catalogue selections (the local target accepts --preset too)
TIERS = {"core": ["start-page", "monitoring", "backups", "caddy"],
         "advanced": ["start-page", "monitoring", "backups", "caddy", "k3s", "argocd", "vault"]}

ITEM_DEFAULTS = {"needs": [], "conflicts": [], "roles": [], "requires": {}, "size_text": "", "ports": [],
                 "internet": True, "modes": [], "install": {}, "enable": [], "images": {}, "secrets": [],
                 "default": True, "lab": list(LABS), "note": "", "setup": None}


class CatalogueError(ValueError):
    pass


def paths():
    out = []
    if os.environ.get("BROMIGOS_PROVISION_CATALOGUE"):
        out.append(os.environ["BROMIGOS_PROVISION_CATALOGUE"])
    out += [os.path.join(SHARE, "lab", "provision-catalogue.toml"),
            os.path.normpath(os.path.join(HERE, "..", "..", "share", "provision-catalogue.toml"))]
    return out


def template_dirs():
    out = []
    if os.environ.get("BROMIGOS_QUADLET_TEMPLATES"):
        out.append(os.environ["BROMIGOS_QUADLET_TEMPLATES"])
    return out + [os.path.join(SHARE, "lab", "quadlet"), os.path.normpath(os.path.join(HERE, "..", "..", "share", "quadlet"))]


_cache = {}


def _doc(path=None):
    for p in [path] if path else paths():
        if p and os.path.isfile(p):
            key = (p, os.path.getmtime(p))
            if key not in _cache:
                with open(p, "rb") as f:
                    _cache[key] = tomllib.load(f)
            return _cache[key]
    raise FileNotFoundError("no provision-catalogue.toml (the provisioning catalogue)")


def load(path=None):
    """Every [[item]], in the file's order, with the optional keys filled in."""
    items = []
    for raw in _doc(path).get("item", []):
        it = {k: (list(v) if isinstance(v, list) else dict(v) if isinstance(v, dict) else v)
              for k, v in ITEM_DEFAULTS.items()}
        it.update(raw)
        items.append(it)
    return items


def groups(path=None):
    return [{"id": g["id"], "name": g["name"], "icon": g["icon"], "glyph": g.get("glyph", "")}
            for g in _doc(path).get("group", [])]


def by_id(path=None):
    return {it["id"]: it for it in load(path)}


def alternatives(need):
    return [x for x in need.split("|") if x]


def validate(path=None):
    """Problems with the catalogue, in words ([] when it's consistent)."""
    out = []
    items = load(path)
    ids = [it["id"] for it in items]
    known = set(ids)
    gids = [g["id"] for g in groups(path)]
    for g in groups(path):
        if g["id"] not in GROUPS:
            out.append(f"group {g['id']}: not one of {GROUPS}")
        if not g["icon"].endswith("-symbolic") or g["glyph"] not in GLYPHS:
            out.append(f"group {g['id']}: needs an Adwaita symbolic icon and a glyph from ICONS")
    for gid in gids:
        if not any(it["group"] == gid for it in items):
            out.append(f"group {gid}: has no items")
    if len(set(ids)) != len(ids):
        out.append("item ids repeat")
    ports = {}
    for it in items:
        k = it["id"]
        if not re.fullmatch(r"[a-z0-9][a-z0-9-]*", k):
            out.append(f"{k}: ids are lower case words with dashes")
        for f in ("group", "name", "line", "hint", "icon", "glyph", "install"):
            if not it.get(f):
                out.append(f"{k}: no {f}")
        if it["group"] not in gids:
            out.append(f"{k}: group {it['group']!r} isn't a [[group]]")
        if not str(it.get("icon", "")).endswith("-symbolic"):
            out.append(f"{k}: icon {it.get('icon')!r} isn't an Adwaita symbolic icon")
        if it.get("glyph") not in GLYPHS:
            out.append(f"{k}: glyph {it.get('glyph')!r} isn't a key of bromigos_textual.ICONS")
        if not it["line"].endswith(".") or not it["hint"].endswith("."):
            out.append(f"{k}: line and hint are sentences")
        for need in it["needs"]:
            for alt in alternatives(need):
                if alt not in known:
                    out.append(f"{k}: needs {alt!r}, which isn't an item")
        for c in it["conflicts"]:
            if c not in known:
                out.append(f"{k}: conflicts with {c!r}, which isn't an item")
            elif k not in by_id(path)[c]["conflicts"]:
                out.append(f"{k}: conflicts with {c}, but {c} doesn't say so back")
        for r in it["roles"]:
            if r not in ROLES:
                out.append(f"{k}: role {r!r} isn't one of {ROLES}")
        for x in it["lab"]:
            if x not in LABS:
                out.append(f"{k}: lab {x!r} isn't one of {LABS}")
        kinds = [x for x in INSTALL_KINDS if x in it["install"]]
        if len(kinds) != 1:
            out.append(f"{k}: install says how with exactly one of {INSTALL_KINDS}")
        elif kinds[0] == "quadlet":
            if not it["images"]:
                out.append(f"{k}: a quadlet item lists its images")
            if not any(os.path.isdir(os.path.join(d, it["install"]["quadlet"])) for d in template_dirs()):
                out.append(f"{k}: no quadlet template {it['install']['quadlet']!r}")
        for name, ref in it["images"].items():
            if not re.search(r"@sha256:[0-9a-f]{64}$", ref):
                out.append(f"{k}: image {name} isn't pinned by digest")
        if it["modes"] and set(it["modes"]) - {"server", "agent"}:
            out.append(f"{k}: modes are server and agent")
        for p in it["ports"]:
            ports.setdefault(p, []).append(k)
        setup = it.get("setup")
        if setup:
            fids = [f.get("id") for f in setup.get("field", [])]
            for f in setup.get("field", []):
                if f.get("kind") not in FIELD_KINDS:
                    out.append(f"{k}: setup field {f.get('id')}: kind {f.get('kind')!r}")
                if f.get("kind") == "secret" and "default" in f:
                    out.append(f"{k}: setup field {f['id']}: a secret has no default")
                if f.get("kind") == "choice" and f.get("default") not in [c["id"] for c in f.get("choices", [])]:
                    out.append(f"{k}: setup field {f['id']}: its default isn't a choice")
                for dep in (f.get("show_if") or {}):
                    if dep not in fids:
                        out.append(f"{k}: setup field {f['id']}: show_if names no field {dep!r}")
            for a in setup.get("action", []):
                if not a.get("url", "").startswith(("http://", "https://")):
                    out.append(f"{k}: setup action {a.get('label')!r} has no address")
    for p, owners in ports.items():
        clash = [(a, b) for i, a in enumerate(owners) for b in owners[i + 1:]
                 if b not in by_id(path)[a]["conflicts"]]
        if clash and p not in (22,):
            out.append(f"port {p}: used by {', '.join(owners)}")
    cycle = _cycle(items)
    if cycle:
        out.append("needs go round in a circle: " + " → ".join(cycle))
    return out


def _cycle(items):
    graph = {it["id"]: [a for n in it["needs"] for a in alternatives(n)] for it in items}
    state = {}

    def visit(n, path):
        state[n] = 1
        for m in graph.get(n, []):
            if state.get(m) == 1:
                return path + [n, m]
            if not state.get(m):
                found = visit(m, path + [n])
                if found:
                    return found
        state[n] = 2
        return None
    for n in graph:
        if not state.get(n):
            found = visit(n, [])
            if found:
                return found
    return None


def resolve(selected_ids, path=None):
    """(ids with what they need, needs first; the ids that were added for them). An "a|b" need
    is met by whichever is chosen, else the first is added. Unknown ids raise CatalogueError."""
    cat = by_id(path)
    unknown = [i for i in selected_ids if i not in cat]
    if unknown:
        raise CatalogueError("no item named " + ", ".join(unknown))
    chosen = list(dict.fromkeys(selected_ids))
    added = []
    i = 0
    while i < len(chosen):
        for need in cat[chosen[i]]["needs"]:
            alts = alternatives(need)
            if not any(a in chosen for a in alts):
                pick = next((a for a in alts if not any(c in cat[a]["conflicts"] for c in chosen)), alts[0])
                chosen.append(pick)
                added.append(pick)
        i += 1
    order, seen = [], set()

    def place(n):
        if n in seen:
            return
        seen.add(n)
        for need in cat[n]["needs"]:
            for a in alternatives(need):
                if a in chosen:
                    place(a)
        order.append(n)
    catalogue_order = list(cat)
    for n in sorted(chosen, key=catalogue_order.index):
        place(n)
    return order, added


def conflicts(ids, path=None):
    """Plain sentences for every pair that can't run together."""
    cat = by_id(path)
    out = []
    for i, a in enumerate(ids):
        for b in ids[i + 1:]:
            if b in cat[a]["conflicts"] or a in cat[b]["conflicts"]:
                out.append(f"{cat[a]['name']} and {cat[b]['name']} can't run on the same server: choose one.")
    return out


def _gpu_vendor(hw):
    g = (hw or {}).get("gpu")
    if g in (None, False, "none", ""):
        return None
    return g if isinstance(g, str) else "any"


def fits_item(it, hw):
    """None when it fits, else a plain sentence saying why not."""
    req = it["requires"] or {}
    vendor = _gpu_vendor(hw)
    if req.get("gpu") and not vendor:
        return f"{it['name']} needs a graphics card, and this server has none that's ready."
    if req.get("gpu_vendor") and vendor not in (req["gpu_vendor"], "any"):
        return f"{it['name']} needs an {req['gpu_vendor'].upper()} card."
    if req.get("gpu_vram_gb") and float(hw.get("gpu_vram_gb") or 0) < req["gpu_vram_gb"]:
        return f"{it['name']} needs {req['gpu_vram_gb']:g} GB of graphics memory; this card has {float(hw.get('gpu_vram_gb') or 0):g} GB."
    if req.get("ram_gb") and hw.get("ram_gb") is not None and req["ram_gb"] + OS_RAM_GB > hw["ram_gb"]:
        return f"{it['name']} needs {req['ram_gb']:g} GB of memory; this server has {hw['ram_gb']:g} GB."
    return None


def budget(ids, hw, path=None, models=()):
    """What the items need together against what the server has: {cpu, ram_gb, disk_gb,
    gpu_vram_gb, fits, notes}. Memory and disk add up; the processor is shared, so it fits when
    the hungriest item fits, and a note says when they'd be busy together."""
    cat = by_id(path)
    rows = [cat[i] for i in ids]
    req = [r["requires"] or {} for r in rows]
    cpu = sum(float(r.get("cpu", 0)) for r in req)
    ram = sum(float(r.get("ram_gb", 0)) for r in req)
    disk = sum(float(r.get("disk_gb", 0)) for r in req)
    vram = 0.0
    for m in models or ():
        vram = max(vram, float(m.get("vram_gb") or 0))
        ram += float(m.get("ram_gb") or 0) if not _gpu_vendor(hw) else 0
        disk += float(m.get("disk_gb") or 0)
    notes, fits = [], True
    hw = hw or {}
    for r in rows:
        why = fits_item(r, hw)
        if why and (r["requires"] or {}).get("gpu"):
            fits = False
            notes.append(why)
    total_ram = ram + OS_RAM_GB
    if hw.get("ram_gb") is not None and total_ram > hw["ram_gb"]:
        fits = False
        notes.append(f"Together these need about {total_ram:.1f} GB of memory, and this server has {hw['ram_gb']:.1f} GB. "
                     "Untick something, or add memory.")
    elif hw.get("ram_gb") is not None and total_ram > 0.85 * hw["ram_gb"]:
        notes.append(f"Memory will be tight: about {total_ram:.1f} of {hw['ram_gb']:.1f} GB.")
    if hw.get("disk_gb") is not None and disk > hw["disk_gb"] * (1 - DISK_HEADROOM):
        fits = False
        notes.append(f"Together these need about {disk:.0f} GB of disk, and {hw['disk_gb']:.0f} GB is free. "
                     "Untick something, or add a disk.")
    biggest = max((float(r.get("cpu", 0)) for r in req), default=0)
    if hw.get("cpu") and biggest > hw["cpu"]:
        fits = False
        notes.append(f"Something here needs {biggest:g} processor cores, and this server has {hw['cpu']}.")
    elif hw.get("cpu") and cpu > 2 * hw["cpu"]:
        notes.append(f"They share {hw['cpu']} processor cores: fine for a household, slow if all are busy at once.")
    if vram and hw.get("gpu_vram_gb") is not None and vram > float(hw.get("gpu_vram_gb") or 0):
        fits = False
        notes.append(f"The models need {vram:g} GB of graphics memory; this card has {float(hw.get('gpu_vram_gb') or 0):g} GB.")
    for problem in conflicts(list(ids), path):
        fits = False
        notes.append(problem)
    return {"cpu": round(cpu, 2), "ram_gb": round(ram + OS_RAM_GB, 2), "disk_gb": round(disk, 1),
            "gpu_vram_gb": round(vram, 1), "fits": fits, "notes": notes}


def norm_roles(roles):
    out = []
    for r in roles or ():
        r = ROLE_ALIASES.get(r, r)
        if r not in ROLES:
            raise CatalogueError(f"no role named {r!r} (there's {', '.join(ROLES)})")
        out.append(r)
    return list(dict.fromkeys(out)) or ["base"]


def recommend(roles, hw, lab="none", path=None):
    """The ids the roles tick, for this hardware and lab answer (new, join or none), with what
    they need, needs first. Several roles tick the union. Items with default = false, items for
    another lab answer and items the hardware can't run are left for the person to tick."""
    roles = norm_roles(roles)
    lab = lab if lab in LABS else "none"
    picked = []
    for it in load(path):
        if not set(it["roles"]) & set(roles) or not it["default"] or lab not in it["lab"]:
            continue
        if fits_item(it, hw or {}):
            continue
        if any(c in picked for c in it["conflicts"]):
            continue
        picked.append(it["id"])
    ids, _ = resolve(picked, path)
    return ids


def suggest_models(hw, cat=None, capabilities=("llm", "embed")):
    """Models for this server from the lab's model catalogue (models.toml), sized to its GPU:
    [{id, capability, name, variant, runtime, serve_with, vram_gb, ram_gb, disk_gb, licence,
    why, default}]. The first of each capability is the default pick."""
    from . import catalog as C
    hw = hw or {}
    vendor = _gpu_vendor(hw)
    vram = float(hw.get("gpu_vram_gb") or 0) if vendor else 0
    out = []
    for cap in capabilities:
        try:
            doc = C.pick(cap, vram or None, ram_gib=float(hw.get("ram_gb") or 16),
                         vendor=vendor if vendor in ("amd", "intel") else "nvidia", cat=cat, alternatives=2)
        except Exception:                          # noqa: BLE001  no catalogue: no suggestions
            continue
        for n, b in enumerate([doc["best"]] + list(doc["alternatives"])):
            if not b or b["runtime"] not in ("llama.cpp", "ollama", "vllm"):
                continue
            serve = "vllm" if b["runtime"] == "vllm" else "ollama"
            out.append({"id": b["key"], "capability": cap, "name": b["name"], "variant": b["variant"],
                        "quant": b.get("quant", ""), "runtime": b["runtime"], "serve_with": serve,
                        "weights": b.get("weights") or b.get("repo") or "",
                        "vram_gb": float(b.get("vram_gib") or 0), "ram_gb": float(b.get("ram_gib") or 0),
                        "disk_gb": float(b.get("vram_gib") or b.get("ram_gib") or 0),
                        "licence": b.get("licence", ""), "why": b.get("why") or doc.get("reason", ""),
                        "default": not any(o["capability"] == cap for o in out)})
    return out


def describe_item(it):
    """How an item installs, in the plan's words."""
    inst = it["install"]
    if "pacman" in inst:
        return {"kind": "pacman", "packages": inst["pacman"],
                **({"gpu_packages": {k: v for k, v in inst.items() if k in ("nvidia", "amd")}}
                   if any(k in inst for k in ("nvidia", "amd")) else {})}
    if "quadlet" in inst:
        return {"kind": "quadlet", "template": inst["quadlet"], "images": dict(it["images"])}
    return {"kind": "step", "step": inst["step"]}
