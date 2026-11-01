"""What should this server run? The lab choice and the provisioning catalogue for bromigOS
Server's provisioning step (server_gui.py, server_tui.py), read through the lab engine's own
module, bromigos_homelab.provcatalog (bromigos-lab: load, groups, resolve, conflicts, budget,
recommend, suggest_models, fits_item), and its hardware reading (localprovision.detect). With
no engine (an older medium; the tests' fixture, BROMIGOS_PROVISION_CATALOGUE), the same rules
are kept here over the catalogue file, which has the engine's schema. Nothing here installs anything: the choices go in the answers
([server] lab, lab_join, provision, models) and the Server tour's first start runs
`bromigos lab provision --local --from-answers … --plan`, then `--apply`.
"""
import glob
import json
import os
import re
import subprocess

CATALOGUE_PLACES = ["/usr/share/bromigos/lab/provision-catalogue.toml", "/usr/share/bromigos/provision-catalogue.toml"]
ROLE_ALIASES = {"lab": "lab-node", "home": "home-services", "games": "game-server", "plain": "base", "just-a-server": "base"}


def norm_role(r):
    return ROLE_ALIASES.get(r, r)
SHARE = os.environ.get("BROMIGOS_ISO_SHARE", "/usr/local/share/bromigos-iso")
LAB_CHOICES = {   # (title, words)
    "new": ("Start a new lab on this server",
            "This server becomes the lab's first machine: its cluster, monitoring and the rest start here."),
    "join": ("Join my existing lab",
             "With your lab's connection file, a join bundle from your lab, or by pairing with BRODEC after the install."),
    "none": ("Not part of a lab", "It runs on its own. You can join a lab later."),
}

_ENGINE = None


def engine():
    """bromigos_homelab.provcatalog, or None (the stand-in rules below)."""
    global _ENGINE
    if _ENGINE is None:
        if os.environ.get("BROMIGOS_PROVISION_CATALOGUE"):
            _ENGINE = False                       # tests: this file, these rules
        else:
            try:
                import sys
                if os.environ.get("BROMIGOS_HOMELAB_LIB"):
                    sys.path.insert(0, os.environ["BROMIGOS_HOMELAB_LIB"])
                elif "/usr/lib/bromigos/lib" not in sys.path:
                    sys.path.append("/usr/lib/bromigos/lib")
                from bromigos_homelab import provcatalog
                provcatalog.load()
                _ENGINE = provcatalog
            except Exception:
                _ENGINE = False
    return _ENGINE or None


def catalogue_path():
    for p in ([os.environ["BROMIGOS_PROVISION_CATALOGUE"]] if os.environ.get("BROMIGOS_PROVISION_CATALOGUE") else []) + \
            CATALOGUE_PLACES:
        if os.path.isfile(p):
            return os.path.realpath(p)
    return None


_CAT = None


def load(reload=False):
    global _CAT
    if _CAT is None or reload:
        import tomllib
        path = catalogue_path()
        try:
            with open(path, "rb") as f:
                _CAT = tomllib.load(f) if path else {}
        except (OSError, TypeError, tomllib.TOMLDecodeError):
            _CAT = {}
        _CAT["_source"] = path
    return _CAT


def groups():
    e = engine()
    if e:
        return e.groups()
    return [{"id": g["id"], "name": g["name"], "icon": g.get("icon", "emblem-system-symbolic"), "glyph": g.get("glyph", "")}
            for g in load().get("group", [])]


def labs_of(x):
    """The lab answers an item is offered with (the engine's `lab`; older files' `modes`)."""
    return x.get("lab") or x.get("modes") or ["new", "join", "none"]


def items(group=None, mode=None):
    out = []
    for x in (engine().load() if engine() else load().get("item", [])):
        if group and x.get("group") != group:
            continue
        if mode and mode not in labs_of(x):
            continue
        out.append(x)
    return out


def item(iid):
    return next((x for x in items() if x["id"] == iid), None)


def resolve(ids):
    """(every id with what it needs, the ones pulled in) in the catalogue's order."""
    known = {x["id"] for x in items()}
    ids = [i for i in ids if i in known]
    e = engine()
    if e:
        return e.resolve(list(ids))
    want, added = list(dict.fromkeys(ids)), []
    i = 0
    while i < len(want):
        for need in (item(want[i]) or {}).get("needs", []):
            alts = [x for x in need.split("|") if x]          # "a|b": either one; the first if neither
            if not any(a in want for a in alts):
                want.append(alts[0])
                added.append(alts[0])
        i += 1
    order = [x["id"] for x in items()]
    want.sort(key=lambda x: order.index(x) if x in order else len(order))
    return want, added


def conflicts(ids):
    """Plain sentences for every pair of chosen items that can't run together."""
    e = engine()
    if e:
        return e.conflicts(list(ids))
    out = []
    for n, a in enumerate(ids):
        for b in ids[n + 1:]:
            if b in (item(a) or {}).get("conflicts", []) or a in (item(b) or {}).get("conflicts", []):
                out.append(f"{(item(a) or {}).get('name', a)} and {(item(b) or {}).get('name', b)} can't run on the same "
                           "server: choose one.")
    return out


def why_not(x, hw):
    """None when the item can run on this computer, else why not (the engine's fits_item)."""
    e = engine()
    if e:
        return e.fits_item(x, hw)
    r = x.get("requires") or {}
    if r.get("gpu") and not hw.get("gpu"):
        return f"{x['name']} needs a graphics card, and this server has none that's ready."
    return None


def budget(ids, hw, models=()):
    """{cpu, ram_gb, disk_gb, gpu_vram_gb, fits, notes}: what the choices need against this machine."""
    e = engine()
    if e:
        known = {m["id"]: m for m in suggest_models(hw)} if any(isinstance(m, str) for m in models) else {}
        ms = [m if isinstance(m, dict) else known.get(m) for m in models]
        return e.budget(list(ids), hw, models=[m for m in ms if m])
    ids, _ = resolve(ids)
    need = {"cpu": 0, "ram_gb": 0, "disk_gb": 0, "gpu_vram_gb": 0}
    gpu_needed = False
    for i in ids:
        r = (item(i) or {}).get("requires") or {}
        need["cpu"] = max(need["cpu"], r.get("cpu", 0))         # cores are shared; the biggest sets the floor
        need["ram_gb"] += r.get("ram_gb", 0)
        need["disk_gb"] += r.get("disk_gb", 0)
        need["gpu_vram_gb"] = max(need["gpu_vram_gb"], r.get("gpu_vram_gb", 0))
        gpu_needed = gpu_needed or bool(r.get("gpu"))
    notes = []
    if need["ram_gb"] > hw.get("ram_gb", 0):
        notes.append(f"Needs about {need['ram_gb']} GB of memory; this server has {hw.get('ram_gb', 0)} GB.")
    if need["cpu"] > hw.get("cpu", 0):
        notes.append(f"Needs {need['cpu']} processor cores; this server has {hw.get('cpu', 0)}.")
    if need["disk_gb"] > hw.get("disk_gb", 0):
        notes.append(f"Needs about {need['disk_gb']} GB of disk; there's about {hw.get('disk_gb', 0)} GB.")
    if gpu_needed and not hw.get("gpu"):
        notes.append("Model serving needs a graphics card (NVIDIA); none was found.")
    elif need["gpu_vram_gb"] > hw.get("gpu_vram_gb", 0):
        notes.append(f"Needs a card with {need['gpu_vram_gb']} GB; this one has {hw.get('gpu_vram_gb', 0)} GB.")
    need["fits"] = not notes
    need["notes"] = notes
    return need


def recommend(roles, hw, mode="none"):
    """The ids a combination of roles pre-ticks, for this lab choice and this machine."""
    e = engine()
    if e:
        return e.recommend([norm_role(r) for r in roles], hw, lab=mode)
    want = {norm_role(r) for r in roles}
    out = []
    for x in items(mode=mode):
        if want & {norm_role(r) for r in x.get("roles", [])} and x.get("default", True) is not False:
            if why_not(x, hw):
                continue
            out.append(x["id"])
    return resolve(out)[0]


def suggest_models(hw):
    """The models model serving offers, biggest that fits first: [{id, name, line, gpu_vram_gb, size_text, fits}]."""
    e = engine()
    if e:
        try:
            ms = e.suggest_models(hw)
        except Exception:
            ms = []
        return [dict(m, fits=True, gpu_vram_gb=m.get("vram_gb", 0), line=m.get("why", ""),
                     size_text=f"{m.get('disk_gb', 0):g} GB", name=f"{m.get('name', m['id'])} {m.get('variant', '')}".strip())
                for m in ms if m.get("capability", "llm") == "llm"]
    vram = hw.get("gpu_vram_gb", 0)
    out = [dict(m, fits=m.get("gpu_vram_gb", 0) <= vram) for m in load().get("model", [])]
    out.sort(key=lambda m: (not m["fits"], -m.get("gpu_vram_gb", 0)))
    return out


# ── this machine ────────────────────────────────────────────────────────────────────────
def hardware(probe=None):
    """{cpu, ram_gb, disk_gb, gpu, gpu_name, gpu_vram_gb}: what this computer has to give."""
    if os.environ.get("BROMIGOS_INSTALLER_HW"):
        return json.loads(os.environ["BROMIGOS_INSTALLER_HW"])
    if os.environ.get("BROMIGOS_INSTALLER_FAKE"):
        return {"cpu": 16, "ram_gb": 64, "disk_gb": 4500, "gpu": "nvidia", "gpu_name": "NVIDIA RTX 4090", "gpu_vram_gb": 24}
    if engine():
        try:
            from bromigos_homelab import localprovision
            hw = dict(localprovision.detect())
            hw["disk_gb"] = sum(d.get("size", 0) for d in (probe or {}).get("disks", []) if not d.get("medium")) // 10 ** 9 \
                or hw.get("disk_gb", 0)
            return hw
        except Exception:
            pass
    hw = {"cpu": os.cpu_count() or 1, "ram_gb": 0, "disk_gb": 0, "gpu": False, "gpu_name": "", "gpu_vram_gb": 0}
    try:
        with open("/proc/meminfo") as f:
            hw["ram_gb"] = round(int(next(l for l in f if l.startswith("MemTotal")).split()[1]) / 1024 ** 2)
    except (OSError, StopIteration, ValueError):
        pass
    hw["disk_gb"] = sum(d.get("size", 0) for d in (probe or {}).get("disks", []) if not d.get("medium")) // 10 ** 9
    try:
        r = subprocess.run(["bromigos", "hw", "detect", "--json"], capture_output=True, text=True, timeout=30)
        for g in (json.loads(r.stdout).get("detection") or {}).get("gpus") or []:
            if (g.get("vendor") or "").lower().startswith("nvidia"):
                hw.update(gpu="nvidia", gpu_name=f"NVIDIA {g.get('name', '')}".strip(),
                          gpu_vram_gb=int(g.get("vram_gib") or g.get("vram_gb") or _vram_guess(g.get("name", ""))))
                break
    except (OSError, ValueError, subprocess.TimeoutExpired):
        pass
    if not hw["gpu"]:
        for d in glob.glob("/sys/bus/pci/devices/*"):
            try:
                if open(os.path.join(d, "vendor")).read().strip() == "0x10de" and \
                        open(os.path.join(d, "class")).read().startswith("0x03"):
                    hw.update(gpu="nvidia", gpu_name="NVIDIA graphics card", gpu_vram_gb=8)
                    break
            except OSError:
                pass
    return hw


def _vram_guess(name):
    m = re.search(r"(\d{4})", name or "")
    table = {"4090": 24, "3090": 24, "5090": 32, "4080": 16, "5080": 16, "4070": 12, "5070": 12, "3080": 10, "4060": 8,
             "3060": 12, "5060": 8}
    return table.get(m.group(1), 8) if m else 8


def hw_words(hw):
    gpu = f", {hw.get('gpu_name') or 'a graphics card'} ({hw.get('gpu_vram_gb', 0):g} GB)" if hw.get("gpu") else ", no graphics card for AI"
    return f"{hw.get('cpu', 0)} cores, {hw.get('ram_gb', 0):g} GB memory, about {hw.get('disk_gb', 0):g} GB of disk{gpu}"


# ── an item's guided setup ([item.setup]) ───────────────────────────────────────────────
def setup(iid):
    """The item's guided setup: {notes, links, check, field: [...]}, or {}."""
    return (item(iid) or {}).get("setup") or {}


def fields(iid, values=None):
    """The setup's fields to show now: a choice field narrows the rest to its choice's fields."""
    st = setup(iid)
    fs = st.get("field", [])
    values = dict(defaults(iid), **(values or {}))
    shown = None
    for f in fs:
        if f.get("kind") == "choice":
            pick = values.get(f["id"], f.get("default"))
            c = next((c for c in f.get("choices", []) if c["id"] == pick), None)
            if c and c.get("fields"):
                shown = set(c["fields"])

    def visible(f):                       # the engine's show_if = {field: [values]}
        cond = f.get("show_if") or {}
        return all(values.get(k) in (v if isinstance(v, list) else [v]) for k, v in cond.items())
    return [f for f in fs if visible(f) and (shown is None or f.get("kind") == "choice" or f["id"] in shown)]


def words(f, key):
    """A field's or choice's words whichever name the file gives them: hint/help, title/label, link/url."""
    names = {"hint": ("hint", "help"), "title": ("title", "label"), "link": ("link", "url")}[key]
    return next((f[n] for n in names if f.get(n)), "")


def defaults(iid):
    return {f["id"]: f.get("default") for f in setup(iid).get("field", []) if f.get("kind") != "secret"}


def split_secrets(iid, values):
    """(plain values, secret values): secrets never go in an answer file."""
    kinds = {f["id"]: f.get("kind") for f in setup(iid).get("field", [])}
    plain = {k: v for k, v in values.items() if kinds.get(k) != "secret"}
    secret = {k: v for k, v in values.items() if kinds.get(k) == "secret" and v}
    return plain, secret


def check(iid, values, timeout=40):
    """The engine's live check of an item's setup (bromigos lab provision --check ITEM --json, the
    values on its input): (True/False/None, words). None: there's no check here yet; the first start
    runs it."""
    import shutil
    cmd = os.environ.get("BROMIGOS_PROVISION_CMD", "bromigos")
    if not shutil.which(cmd.split()[0]):
        return None, "The check runs at the first start, with the rest of the plan."
    try:
        r = subprocess.run(cmd.split() + ["lab", "provision", "--check", iid, "--json"], input=json.dumps(values),
                           capture_output=True, text=True, timeout=timeout)
        doc = json.loads(r.stdout or "{}")
        return bool(doc.get("ok")), doc.get("words") or ("Connected." if doc.get("ok") else "It didn't connect.")
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return None, "The check runs at the first start, with the rest of the plan."


def setup_notes(iid):
    st = setup(iid)
    return list(st.get("notes") or []) + ([st["intro"]] if st.get("intro") else [])


def setup_links(iid, host="server"):
    """[(label, url)]: the setup's links and actions ({host}: this server's name)."""
    st = setup(iid)
    out = []
    for ln in list(st.get("links") or []) + list(st.get("action") or []):
        out.append((words(ln, "title"), (words(ln, "link") or "").replace("{host}", f"{host}.local")))
    return out


ACRONYMS = {"api": "API", "id": "ID", "url": "URL", "ssh": "SSH", "tls": "TLS", "jwt": "JWT", "s3": "S3", "vpn": "VPN"}


def secret_title(name):
    """A generated secret's name as words: `api_key` → "API key"."""
    words = name.replace("-", " ").replace("_", " ").split()
    out = [ACRONYMS.get(w.lower(), w.lower()) for w in words]
    if out and out[0] == out[0].lower():
        out[0] = out[0].capitalize()
    return " ".join(out)


def generated(iid):
    """The secrets the item makes for itself (its `secrets`, and older files' generated fields)."""
    x = item(iid) or {}
    return list(x.get("secrets") or []) + [f["id"] for f in setup(iid).get("field", []) if f.get("kind") == "generated"]
