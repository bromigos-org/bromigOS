"""`bromigos lab studio`: the Creation studio's models, node packs and workflows (docs/lab.md,
"The Creation studio"; docs/lab-models.md, "Files and node packs").

    bromigos lab studio [status] [--json]      what it has, what it lacks, whether ComfyUI answers
    bromigos lab studio plan [--licence L] [--region R] [--goal G] [--vram GiB] [--vendor V] [--json]
                                               what it would install on this card (or one named)
    bromigos lab studio apply [--licence L] [--region R] [--goal G] [--only WF,…] [--json]
                                               fetch what's missing, checked; nodes; workflows; create.toml
    bromigos lab studio rollback [CAPABILITY] [--json]
                                               put back the model an upgrade replaced
    bromigos lab studio upgrade [--apply] [--json]
                                               the lab's upgrade policy, applied to this studio
                                               (`bromigos lab models upgrades --apply` runs this)

The studio is the catalogue item `comfyui` (provision-catalogue.toml): ComfyUI in a container,
its data in /srv/apps/comfyui. For each kind of art bromigOS makes (create.toml's capabilities),
it takes the shipped workflows (core/crates/bromigos-art/workflows), finds each one's catalog
variant (`_meta.catalog`, or the variant whose `workflow` names it), and keeps the ones the
catalog says fit this machine's card within the licence filter and region. The best by the
catalog's own utility wins, with its fast siblings (the Lightning workflows) beside it.

Every file comes from the catalog's `[[model.variant.file]]` rows: a Hugging Face repository at
a pinned commit, its size and sha256. A download goes to `<dest>.part`, resumes there, and is
moved into place only when its size and sha256 are right. A file an upgrade replaces at the same
path is kept in models/.previous; a workflow an upgrade replaces stays installed. Both go after
KEEP_DAYS, or come back with `rollback`. Node packs (`[node_pack.*]`) are cloned at their pinned
commit inside the container. Everything the studio did is in /srv/apps/comfyui/studio.json.

Tests replace the downloader (fetch), the commands (run), ComfyUI's API (http) and the clock;
nothing here needs the network to be tested.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import sys
import time
import urllib.error
import urllib.request

from . import catalog as C, localprovision as L

SCHEMA = 1
ITEM = "comfyui"
DATA = "srv/apps/comfyui"
MODELS = DATA + "/models"
PREVIOUS = MODELS + "/.previous"           # ComfyUI only reads its own folders: it never sees these
NODES = DATA + "/custom_nodes"
WORKFLOWS_OUT = DATA + "/user/default/workflows/bromigos"
STATE = DATA + "/studio.json"
QUADLET = L.QUADLET_DIR + "/comfyui.container"
UNIT = "comfyui.service"
CONTAINER = "comfyui"
URL = "http://127.0.0.1:8188"
KEEP_DAYS = 14
RESERVE_GIB = 10                            # disk left free after a fetch
CHUNK = 8 * 1024 * 1024
# create.toml's capabilities, the catalog capability each is ranked by, and its name for people
ART = (("image.generate", "image", "pictures from a prompt"),
       ("image.edit", "image-edit", "edits"),
       ("image.cutout", "cutout", "cutouts"),
       ("image.upscale", "upscale-image", "larger, sharper pictures"),
       ("video.loop", "video", "video loops"),
       ("video.upscale", "upscale-video", "larger, sharper clips"),
       ("model3d.generate", "3d", "3D models"))
LICENCES = ("any", "commercial", "permissive")
EXIT_PROBLEM, EXIT_USAGE, EXIT_REFUSED, EXIT_UNCHECKED = 1, 2, 3, 4
HERE = os.path.dirname(os.path.abspath(__file__))


class StudioError(Exception):
    def __init__(self, words, code=EXIT_REFUSED):
        super().__init__(words)
        self.code = code


# ---------------------------------------------------------------- the shipped workflows
def workflow_dirs():
    out = []
    if os.environ.get("BROMIGOS_ART_WORKFLOWS"):
        out.append(os.environ["BROMIGOS_ART_WORKFLOWS"])
    out += ["/usr/share/bromigos/art/workflows",
            os.path.normpath(os.path.join(HERE, "..", "..", "..", "core", "crates", "bromigos-art", "workflows"))]
    return out


def load_workflows(dirs=None):
    """{name: {name, path, caps, catalog, requires: [folder/file], classes, fast, commercial}} from the
    first folder that has them."""
    for d in dirs or workflow_dirs():
        files = sorted(Path(d).glob("*.json")) if os.path.isdir(d) else []
        if not files:
            continue
        out = {}
        for f in files:
            try:
                doc = json.loads(f.read_text())
            except (OSError, ValueError):
                continue
            meta = doc.get("_meta") or {}
            out[f.stem] = {
                "name": f.stem, "path": str(f), "caps": list(meta.get("capabilities") or []),
                "catalog": meta.get("catalog") or "",
                "requires": [f"{r['folder']}/{r['file']}" for r in meta.get("requires") or []],
                "classes": sorted({n["class_type"] for n in doc.values() if isinstance(n, dict) and "class_type" in n}),
                "fast": "fast" in (meta.get("features") or []), "commercial": meta.get("commercial"),
                "license": meta.get("license") or ""}
        return out
    return {}


def variant_of(cat, wf):
    if wf["catalog"]:
        return cat.variant(wf["catalog"])
    return next((v for m in cat.models.values() for v in m.variants if v.workflow == wf["name"]), None)


def packs_for(cat, classes):
    return sorted(k for k, p in cat.node_packs.items() if set(p.get("classes") or ()) & set(classes))


# ---------------------------------------------------------------- picking for a card
def hardware_for(cat, hw, desktop=False):
    """The catalog's view of this machine's card (the one ComfyUI uses), or None without one."""
    vendor = hw.get("gpu") if isinstance(hw.get("gpu"), str) else None
    if vendor not in ("nvidia", "amd"):
        return None
    name = hw.get("gpu_name") or ""
    g = cat.gpu(name) if name else None
    spec = g.name if g else f"{vendor}:{float(hw.get('gpu_vram_gb') or 0)}"
    if desktop:
        spec += ",desktop"
    out = C.Hardware.parse([spec], ram_gib=float(hw.get("ram_gb") or 32), cat=cat, cpu=False)
    for d in out.gpus():
        d.vendor = vendor
    return out


def plan(cat=None, hw=None, licence="commercial", region=None, goal="balanced", desktop=False, only=None,
         wfs=None):
    """What the studio would install here: one workflow per capability (with its fast siblings),
    the files they need from the catalog's manifest, the node packs, and why for each."""
    cat = cat or C.load()
    wfs = load_workflows() if wfs is None else wfs
    man = C.files(cat)
    hw = hw or {}
    H = hardware_for(cat, hw, desktop)
    give = max((d.give() for d in H.gpus()), default=0.0) if H else 0.0
    rows = []
    for art, ccap, words in ART:
        row = {"capability": art, "words": words, "workflow": None, "also": [], "why": ""}
        cands = [w for w in wfs.values() if art in w["caps"] and not w["fast"] and (not only or w["name"] in only)]
        best, why = None, []
        for w in cands:
            v = variant_of(cat, w)
            if v is None:
                why.append(f"{w['name']}: not in the model catalog")
                continue
            missing = [r for r in w["requires"] if r not in man]
            if missing:
                why.append(f"{w['name']}: no pinned source for {', '.join(missing)}")
                continue
            if H is None:
                continue
            opts = [o for o in C.options(cat, ccap, H, licence, region) if o.variant is v]
            if not opts:
                ok, w_ = cat.allows(v, licence, region)
                why.append(f"{w['name']}: " + (w_ if not ok else f"{v.model.name} needs {v.vram_gib:g} GiB; this card "
                                                                  f"gives {give:.1f}"))
                continue
            u = max(C.utility(o, goal) for o in opts)
            if best is None or u > best[0]:
                best = (u, w, v, max(opts, key=lambda o: C.utility(o, goal)))
        if best:
            _, w, v, o = best
            e = cat.effective(v)
            row.update(workflow=w["name"], model=v.model.name, variant=v.key, quant=v.quant, quality=o.quality,
                       vram_gib=o.per_gpu, licence=v.model.licence.name, licence_plain=v.model.licence.plain(),
                       effective_tier=e["tier"], effective_reason=e["reason"], notices=e["notices"],
                       why=f"{v.model.name} ({v.quant}) is the catalog's best fit with a bromigOS workflow for "
                           f"{words}: {o.per_gpu:g} GiB of the {give:.0f} this card gives")
            row["also"] = [x["name"] for x in wfs.values() if x["fast"] and art in x["caps"]
                           and variant_of(cat, x) is v and all(r in man for r in x["requires"])]
        else:
            row["why"] = ("no graphics card ComfyUI can use" if H is None else
                          "; ".join(why) or "no shipped workflow does this")
            if H is not None:
                opts = sorted(C.options(cat, ccap, H, licence, region), key=lambda o: -C.utility(o, goal))
                if opts:
                    v = opts[0].variant
                    row["catalog_best"] = f"{v.model.name} ({v.quant})"
                    row["why"] += (f". The catalog's best fit here is {v.model.name} ({v.quant}), which bromigOS has "
                                   "no workflow for yet" if not v.workflow else "")
        rows.append(row)
    names = [n for r in rows if r["workflow"] for n in [r["workflow"], *r["also"]]]
    names = list(dict.fromkeys(names))
    dests = list(dict.fromkeys(d for n in names for d in wfs[n]["requires"]))
    files = [_public(man[d]) for d in dests]
    packs = packs_for(cat, [c for n in names for c in wfs[n]["classes"]])
    return {"schema": SCHEMA, "hardware": {k: hw.get(k) for k in ("gpu", "gpu_name", "gpu_vram_gb", "ram_gb")},
            "gives_gib": round(give, 1), "licence": licence, "region": region, "goal": goal, "capabilities": rows,
            "workflows": names, "files": files, "bytes": sum(f["bytes"] for f in files),
            "node_packs": [dict(cat.node_packs[k]) for k in packs]}


def _public(f):
    return {"dest": f["dest"], "repo": f["repo"], "rev": f["rev"], "path": f["path"], "bytes": f["bytes"],
            "sha256": f["sha256"], "url": url_of(f), "variant": f.get("variant", "")}


def url_of(f):
    return f"https://huggingface.co/{f['repo']}/resolve/{f['rev']}/{f['path']}"


# ---------------------------------------------------------------- downloading, checked
class FetchError(Exception):
    pass


def sha256_of(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(CHUNK), b""):
            h.update(block)
    return h.hexdigest()


def download(url, part, size, opener=None, token=None, progress=None):
    """Fetch url into `part`, carrying on from what's there (an HTTP range). Never checks the
    sha256 itself: the caller does, over the whole file."""
    opener = opener or urllib.request.urlopen
    have = os.path.getsize(part) if os.path.exists(part) else 0
    if have > size:
        os.unlink(part)
        have = 0
    if have == size:
        return
    headers = {"User-Agent": "bromigos-lab-studio"}
    if have:
        headers["Range"] = f"bytes={have}-"
    if token:
        headers["Authorization"] = f"Bearer {token}"
    try:
        with opener(urllib.request.Request(url, headers=headers), timeout=60) as r:
            status = getattr(r, "status", 200)
            mode = "ab" if have and status == 206 else "wb"
            done = have if mode == "ab" else 0
            with open(part, mode) as out:
                while True:
                    block = r.read(CHUNK)
                    if not block:
                        break
                    out.write(block)
                    done += len(block)
                    if progress:
                        progress(done)
    except (urllib.error.URLError, OSError, TimeoutError) as e:
        raise FetchError(f"the download stopped ({type(e).__name__}); what came is kept and the next try carries on")


# ---------------------------------------------------------------- the studio on this machine
class Studio:
    """The studio's folder and its record. root: a stand-in root in tests."""

    def __init__(self, root=None, run=None, fetch=None, http=None, now=None, free=None, say=None, environ=None,
                 status_of=None):
        self.root = root or L.ROOT
        self.run = run or (L.run if self.root == "/" else (lambda argv, *a, **kw: (127, "", "a stand-in root")))
        self.fetch = fetch or download
        self.http = http or _http_json
        self.now = now or time.time
        self.free = free or (lambda p: shutil.disk_usage(p).free)
        self.say = say or (lambda sid, state, words="": None)
        self.environ = os.environ if environ is None else environ
        self.status_of = status_of or _status_of

    def path(self, rel):
        return Path(L.at(rel, self.root))

    # -- the record
    def state(self):
        try:
            doc = json.loads(self.path(STATE).read_text())
        except (OSError, ValueError):
            doc = {}
        doc.setdefault("schema", SCHEMA)
        for k in ("files", "capabilities", "previous_files", "previous", "node_packs"):
            doc.setdefault(k, {})
        doc.setdefault("workflows", [])
        return doc

    def save(self, doc):
        p = self.path(STATE)
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_name(p.name + ".new")
        tmp.write_text(json.dumps(doc, indent=1, sort_keys=True) + "\n")
        os.replace(tmp, p)

    def installed(self):
        return self.path(QUADLET).exists()

    # -- the page's lock (localprovision: STUDIO_LAUNCH, STUDIO_MANAGER_CONFIG)
    def write(self, rel, text, mode=0o644):
        """Host.write's shape, for localprovision.studio_lock: True when the file changed."""
        p = self.path(rel)
        if p.exists() and p.read_text() == text and (p.stat().st_mode & 0o777) == mode:
            return False
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_name(p.name + ".bromigos-new")
        tmp.write_text(text)
        os.chmod(tmp, mode)
        os.replace(tmp, p)
        return True

    def lock(self):
        """The launcher without ComfyUI-Manager and the Manager's locked settings, written again
        (an image update never reopens installs from the page); ComfyUI restarts when they changed."""
        changed = L.studio_lock(self)
        if changed:
            self.run(["systemctl", "restart", UNIT])
            self.say("lock", "done", "ComfyUI started again without its Manager")
        return changed

    def lock_problems(self):
        """Why the page might install code: plain sentences, none when it's locked."""
        out = []
        base = DATA + "/"
        unit = self.path(QUADLET).read_text() if self.installed() else ""
        if "Exec=bash /bromigos/launch.sh" not in unit:
            out.append("ComfyUI starts the image's own way, with its Manager: set it up again (sudo bromigos lab apps "
                       "add comfyui)")
        try:
            if self.path(base + L.STUDIO_LAUNCH_FILE).read_text() != L.STUDIO_LAUNCH:
                out.append("its launcher was changed")
        except OSError:
            out.append("its launcher is missing")
        for rel in L.STUDIO_MANAGER_CONFIGS:
            try:
                if self.path(base + rel).read_text() != L.STUDIO_MANAGER_CONFIG:
                    out.append(f"the Manager's settings ({rel}) aren't locked")
            except OSError:
                out.append(f"the Manager's settings ({rel}) are missing")
        for route in ("/v2/manager/version", "/manager/version"):
            if self.status_of(URL + route) == 200:
                out.append("ComfyUI-Manager answers on the page, so it could install node packs")
                break
        return out

    # -- files
    def present(self, f, st):
        """Whether the file is in place and right: its size, and its sha256 (from the record, or
        read once for a file that was put there some other way)."""
        p = self.path(MODELS + "/" + f["dest"])
        try:
            if p.stat().st_size != f["bytes"]:
                return False
        except OSError:
            return False
        if st["files"].get(f["dest"]) == f["sha256"]:
            return True
        if sha256_of(p) == f["sha256"]:
            st["files"][f["dest"]] = f["sha256"]
            return True
        return False

    def get(self, f, st):
        """Fetch one file, check it, and put it in place; an older file at its path goes to
        models/.previous first."""
        dest = self.path(MODELS + "/" + f["dest"])
        dest.parent.mkdir(parents=True, exist_ok=True)
        part = dest.with_name(dest.name + ".part")
        self.fetch(url_of(f), str(part), f["bytes"], token=self.environ.get("HF_TOKEN") or None)
        size = part.stat().st_size if part.exists() else -1
        if size != f["bytes"]:
            raise FetchError(f"{f['dest']} came as {size} bytes, not {f['bytes']}; it will be fetched again")
        if sha256_of(part) != f["sha256"]:
            part.unlink()
            raise FetchError(f"{f['dest']} didn't match its published checksum, so it was thrown away")
        if dest.exists():
            old = self.path(PREVIOUS + "/" + f["dest"])
            old.parent.mkdir(parents=True, exist_ok=True)
            os.replace(dest, old)
            st["previous_files"][f["dest"]] = {"sha256": st["files"].get(f["dest"]), "at": int(self.now())}
        os.replace(part, dest)
        st["files"][f["dest"]] = f["sha256"]

    # -- applying a plan
    def apply(self, doc, cat=None, wfs=None, user=None, keep=None):
        """Fetch, check and place what the plan needs; node packs; workflows; the record and
        create.toml. keep: workflows that stay installed though the plan doesn't pick them (an
        upgrade's previous ones). Returns what happened, in words and as data."""
        if not self.installed():
            raise StudioError("the Creation studio isn't set up on this machine (sudo bromigos lab apps add comfyui)")
        locked = self.lock()
        cat = cat or C.load()
        wfs = load_workflows() if wfs is None else wfs
        st = self.state()
        man = C.files(cat)
        rows = [r for r in doc["capabilities"] if r["workflow"]]
        left_out = []
        # the disk: what's missing, against what's free less the reserve; the last kinds of art go first
        while True:
            names = list(dict.fromkeys(n for r in rows for n in [r["workflow"], *r["also"]]))
            need = [man[d] for d in dict.fromkeys(d for n in names for d in wfs[n]["requires"])]
            missing = [f for f in need if not self.present(f, st)]
            want = sum(f["bytes"] for f in missing)
            base = self.path(MODELS)
            base.mkdir(parents=True, exist_ok=True)
            room = self.free(str(base)) - RESERVE_GIB * 1024 ** 3
            if want <= room or not rows:
                break
            r = rows.pop()
            left_out.append({"capability": r["capability"], "workflow": r["workflow"],
                             "why": f"not enough disk: {gib(want)} to fetch, {gib(max(room, 0))} free after keeping "
                                    f"{RESERVE_GIB} GiB"})
        fetched, failed = [], []
        for i, f in enumerate(missing, 1):
            self.say("fetch", "running", f"Fetching {f['dest']} ({gib(f['bytes'])}, {i} of {len(missing)})")
            try:
                self.get(f, st)
                fetched.append(f["dest"])
            except FetchError as e:
                failed.append({"dest": f["dest"], "why": str(e)})
        self.say("fetch", "failed" if failed else "done", f"{len(fetched)} files fetched and checked")
        bad = {x["dest"] for x in failed}
        ready = [r for r in rows if not any(d in bad for n in [r["workflow"], *r["also"]] for d in wfs[n]["requires"])]
        names = list(dict.fromkeys(n for r in ready for n in [r["workflow"], *r["also"]]))
        old = dict(st["capabilities"])
        for r in ready:
            prev = old.get(r["capability"])
            if prev and prev != r["workflow"]:
                st["previous"][r["capability"]] = {"workflow": prev, "at": int(self.now())}
            st["capabilities"][r["capability"]] = r["workflow"]
        # what stays installed though this plan didn't pick it: the workflows it replaced (until
        # KEEP_DAYS, or a rollback), and the ones of every kind of art this plan didn't cover
        covered = {r["capability"] for r in ready}
        keep = list(keep or []) + [p["workflow"] for p in st["previous"].values()] + \
            [w for c, w in old.items() if c not in covered]
        keep = [k for k in keep if k in wfs]
        keep += [x for x in st["workflows"] if x in wfs and wfs[x]["fast"]          # their fast siblings
                 and any(variant_of(cat, wfs[x]) is variant_of(cat, wfs[k]) for k in keep)]
        keep = [k for k in dict.fromkeys(keep) if k not in names]
        packs = self.nodes(cat, [c for n in names + keep for c in wfs[n]["classes"]], st)
        self.workflows(wfs, names + keep)
        st["workflows"] = names + keep
        st["licence"], st["region"], st["applied"] = doc["licence"], doc["region"], int(self.now())
        retired = self.tidy(st, man, wfs)
        self.save(st)
        toml = write_create_toml(user, st, wfs) if user else None
        return {"schema": SCHEMA, "ok": not failed, "fetched": fetched, "failed": failed, "left_out": left_out,
                "capabilities": dict(st["capabilities"]), "workflows": st["workflows"], "node_packs": packs,
                "retired": retired, "create_toml": toml, "relocked": locked, "lock_problems": self.lock_problems()}

    def nodes(self, cat, classes, st):
        """The node packs those classes need, cloned at their pinned commit inside the container,
        their Python packages installed; ComfyUI restarts when one changed."""
        changed = []
        for k in packs_for(cat, classes):
            p = cat.node_packs[k]
            if st["node_packs"].get(k) == p["commit"] and self.path(f"{NODES}/{p['name']}").is_dir():
                continue
            self.say("nodes", "running", f"Installing the node pack {p['name']} ({p['licence']})")
            where = f"/root/ComfyUI/custom_nodes/{p['name']}"
            steps = ([["git", "clone", "--filter=blob:none", p["repo"], where]]
                     if not self.path(f"{NODES}/{p['name']}").is_dir() else [["git", "-C", where, "fetch", "origin"]])
            steps += [["git", "-C", where, "checkout", "--quiet", p["commit"]],
                      ["sh", "-c", f"test ! -f {where}/requirements.txt || pip install --user --quiet -r {where}/requirements.txt"]]
            for s in steps:
                rc, _, _ = self.run(["podman", "exec", CONTAINER, *s], timeout=1800)
                if rc:
                    raise StudioError(f"couldn't install the node pack {p['name']} ({s[0]} stopped with code {rc})")
            st["node_packs"][k] = p["commit"]
            changed.append(k)
        if changed:
            self.run(["systemctl", "restart", UNIT])
            self.say("nodes", "done", "ComfyUI restarted with the new node packs")
        return changed

    def workflows(self, wfs, names):
        """bromigOS's workflows in ComfyUI's own list (Workflows › bromigos), as they ship; ones
        no longer picked are taken out of that folder only."""
        out = self.path(WORKFLOWS_OUT)
        out.mkdir(parents=True, exist_ok=True)
        for n in names:
            text = Path(wfs[n]["path"]).read_text()
            p = out / f"{n}.json"
            if not p.exists() or p.read_text() != text:
                p.write_text(text)
        for p in out.glob("*.json"):
            if p.stem not in names:
                p.unlink()

    def tidy(self, st, man, wfs):
        """Previous copies and replaced workflows older than KEEP_DAYS go; a file goes only when no
        workflow the studio keeps needs it."""
        now, gone = int(self.now()), []
        for cap, prev in list(st["previous"].items()):
            if now - prev["at"] >= KEEP_DAYS * 86400:
                del st["previous"][cap]
                if prev["workflow"] in st["workflows"] and prev["workflow"] not in st["capabilities"].values():
                    st["workflows"].remove(prev["workflow"])
                    w = self.path(f"{WORKFLOWS_OUT}/{prev['workflow']}.json")
                    if w.exists():
                        w.unlink()
        needed = {d for n in st["workflows"] if n in wfs for d in wfs[n]["requires"]}
        for d, prev in list(st["previous_files"].items()):
            if now - prev["at"] >= KEEP_DAYS * 86400:
                p = self.path(PREVIOUS + "/" + d)
                if p.exists():
                    p.unlink()
                del st["previous_files"][d]
                gone.append(".previous/" + d)
        for d in list(st["files"]):
            if d not in needed:
                p = self.path(MODELS + "/" + d)
                if p.exists():
                    p.unlink()
                del st["files"][d]
                gone.append(d)
        return gone

    def rollback(self, cap=None, wfs=None, user=None):
        """Swap each capability (or one) back to the workflow an upgrade replaced, and each file
        kept in models/.previous back into place."""
        st = self.state()
        wfs = load_workflows() if wfs is None else wfs
        caps = [cap] if cap else list(st["previous"])
        if not caps or any(c not in st["previous"] for c in caps):
            raise StudioError("there's no earlier model to go back to" + (f" for {cap}" if cap else ""), EXIT_PROBLEM)
        done = []
        for c in caps:
            prev = st["previous"].pop(c)
            cur = st["capabilities"].get(c)
            st["capabilities"][c] = prev["workflow"]
            if cur:
                st["previous"][c] = {"workflow": cur, "at": int(self.now())}
            done.append({"capability": c, "from": cur, "to": prev["workflow"]})
        for d in list(st["previous_files"]):
            if not cap or any(d in wfs.get(x["from"] or "", {}).get("requires", []) or
                              d in wfs.get(x["to"], {}).get("requires", []) for x in done):
                kept, live = self.path(PREVIOUS + "/" + d), self.path(MODELS + "/" + d)
                if kept.exists():
                    swap = live.with_name(live.name + ".swap")
                    if live.exists():
                        os.replace(live, swap)
                    os.replace(kept, live)
                    if swap.exists():
                        os.replace(swap, kept)
                    info = st["previous_files"][d]
                    st["previous_files"][d] = {"sha256": st["files"].get(d), "at": int(self.now())}
                    st["files"][d] = info.get("sha256")
        for n in st["capabilities"].values():
            if n not in st["workflows"]:
                st["workflows"].append(n)
        self.workflows(wfs, st["workflows"])
        self.save(st)
        toml = write_create_toml(user, st, wfs) if user else None
        return {"schema": SCHEMA, "ok": True, "rolled_back": done, "capabilities": st["capabilities"],
                "create_toml": toml}

    def status(self, cat=None, wfs=None):
        """What the studio has: per capability its workflow and whether every file is there; the
        node packs; whether ComfyUI answers. Never reads a whole file (sizes and the record)."""
        cat = cat or C.load()
        wfs = load_workflows() if wfs is None else wfs
        st = self.state()
        man = C.files(cat)
        doc = {"schema": SCHEMA, "installed": self.installed(), "answers": None, "comfyui_version": None,
               "capabilities": [], "missing": [], "licence": st.get("licence"), "applied": st.get("applied"),
               "previous": st["previous"], "node_packs": st["node_packs"], "locked": None, "lock_problems": []}
        if not doc["installed"]:
            return doc
        doc["lock_problems"] = self.lock_problems()
        doc["locked"] = not doc["lock_problems"]
        stats = self.http(URL + "/system_stats")
        doc["answers"] = stats is not None
        if stats:
            doc["comfyui_version"] = (stats.get("system") or {}).get("comfyui_version")
        for art, _, words in ART:
            n = st["capabilities"].get(art)
            row = {"capability": art, "words": words, "workflow": n, "ready": False, "missing": []}
            if n and n in wfs:
                for d in wfs[n]["requires"]:
                    f = man.get(d)
                    p = self.path(MODELS + "/" + d)
                    ok = p.exists() and (f is None or (p.stat().st_size == f["bytes"] and st["files"].get(d) == f["sha256"]))
                    if not ok:
                        row["missing"].append(d)
                row["ready"] = not row["missing"]
                doc["missing"] += row["missing"]
            doc["capabilities"].append(row)
        doc["missing"] = list(dict.fromkeys(doc["missing"]))
        return doc


def _status_of(url):
    from . import labapps
    return labapps.http_status(url)


def _http_json(url, timeout=3.0):
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            return json.loads(r.read() or b"null")
    except (urllib.error.URLError, OSError, ValueError, TimeoutError):
        return None


def gib(n):
    return f"{n / 1024 ** 3:.1f} GB" if n >= 1024 ** 3 else f"{n / 1024 ** 2:.0f} MB"


# ---------------------------------------------------------------- create.toml
def user_home(environ=None, uid=None):
    """(home, uid, gid) of the person who asked: uid when given (an activity job is told it), else
    SUDO_USER or PKEXEC_UID under root, else this account. None for root with none of them (the
    provisioning engine at first boot)."""
    import pwd
    environ = os.environ if environ is None else environ
    try:
        if uid is not None:
            pw = pwd.getpwuid(int(uid))
            if pw.pw_uid == 0:
                return None
        elif os.geteuid() == 0:
            if environ.get("SUDO_USER") and environ["SUDO_USER"] != "root":
                pw = pwd.getpwnam(environ["SUDO_USER"])
            elif environ.get("PKEXEC_UID"):
                pw = pwd.getpwuid(int(environ["PKEXEC_UID"]))
            else:
                return None
        else:
            pw = pwd.getpwuid(os.getuid())
    except (KeyError, ValueError):
        return None
    return pw.pw_dir, pw.pw_uid, pw.pw_gid


def shipped_create(path="/usr/share/bromigos/default/create.toml"):
    """The shipped defaults' workflow lists, as fallbacks after the studio's own."""
    for p in (path, os.path.join(HERE, "..", "..", "..", "core", "crates", "bromigos-art", "create.default.toml")):
        try:
            with open(p, "rb") as f:
                import tomllib
                return tomllib.load(f)
        except (OSError, ValueError):
            continue
    return {}


def create_toml_text(text, st, wfs, shipped=None):
    """create.toml with this studio wired in: [comfyui.local] at 127.0.0.1:8188 unless the file names
    one, and each capability's `comfyui` list led by what the studio installed, then the shipped
    defaults (other ComfyUIs keep working). Everything else in the file is kept as it is."""
    import tomllib
    shipped = shipped if shipped is not None else shipped_create()
    doc = tomllib.loads(text) if text.strip() else {}
    out = text if text.strip() else "format = 1\n"
    if not (doc.get("comfyui") or {}).get("local"):
        out = out.rstrip("\n") + ('\n\n# the Creation studio on this machine (bromigos lab studio)\n[comfyui.local]\n'
                                  'endpoint = "http://127.0.0.1:8188"\n')
    for art, _, _ in ART:
        mine = st["capabilities"].get(art)
        if not mine:
            continue
        prev = (st.get("previous") or {}).get(art, {}).get("workflow")
        group, _, leaf = art.partition(".")
        base = (shipped.get(group) or {}).get(leaf) or {}
        theirs = base.get("comfyui") or []
        theirs = [theirs] if isinstance(theirs, str) else list(theirs)
        names = list(dict.fromkeys([mine, *([prev] if prev else []), *theirs]))
        line = "comfyui = [" + ", ".join(json.dumps(n) for n in names) + "]   # the Creation studio's first\n"
        head = re.compile(r"^\[" + re.escape(art) + r"\]\s*\n((?:(?!^\[).*\n?)*)", re.M)
        m = head.search(out)
        if m:
            body = m.group(1)
            if re.search(r"^comfyui\s*=.*$", body, re.M):
                body = re.sub(r"^comfyui\s*=.*\n?", line, body, count=1, flags=re.M)
            else:
                body = line + body
            out = out[:m.start(1)] + body + out[m.end(1):]
        else:
            out = out.rstrip("\n") + f"\n\n[{art}]\n{line}"
    tomllib.loads(out)                                       # never write a file that doesn't parse
    return out


def write_create_toml(user, st, wfs):
    home, uid, gid = user
    path = os.path.join(home, ".config", "bromigos", "create.toml")
    real = os.path.realpath(path)
    try:
        text = Path(real).read_text()
    except OSError:
        text = ""
    new = create_toml_text(text, st, wfs)
    if new == text:
        return real
    os.makedirs(os.path.dirname(real), exist_ok=True)
    tmp = real + ".new"
    Path(tmp).write_text(new)
    if os.geteuid() == 0:
        os.chown(tmp, uid, gid)
        d = os.path.dirname(real)
        while d.startswith(home) and d != home:
            try:
                os.chown(d, uid, gid)
            except OSError:
                pass
            d = os.path.dirname(d)
    os.replace(tmp, real)
    return real


# ---------------------------------------------------------------- settings
def chosen_licence(root=None, given=None):
    """--licence, else the studio's setup field (apps.toml [settings.comfyui]), else commercial."""
    if given:
        return given
    try:
        import tomllib
        with open(L.at("etc/bromigos/lab/apps.toml", root), "rb") as f:
            v = ((tomllib.load(f).get("settings") or {}).get(ITEM) or {}).get("licence")
        if v in LICENCES:
            return v
    except (OSError, ValueError):
        pass
    return "commercial"


def is_desktop(root=None):
    """A machine with a screen to drive: not a bromigOS Server (the card keeps a reserve for it)."""
    return not os.path.exists(L.at("etc/bromigos/server.toml", root))


# ---------------------------------------------------------------- the upgrade policy
def upgrade(cat=None, hw=None, studio=None, policy=None, licence="commercial", region=None, goal="balanced",
            desktop=False, wfs=None):
    """What the policy ([upgrade] in lab.toml) would change in this studio: {"enabled", "changes":
    [{capability, from, to, kind, gain, why}], "held": [...]}."""
    from . import catalog_upgrade as U
    cat = cat or C.load()
    wfs = load_workflows() if wfs is None else wfs
    pol = U.settings(policy)
    st = studio.state()
    new = plan(cat, hw, licence, region, goal, desktop, wfs=wfs)
    out = {"enabled": pol["enabled"], "policy": pol["policy"], "changes": [], "held": [], "plan": new}
    for r in new["capabilities"]:
        cur = st["capabilities"].get(r["capability"])
        if not r["workflow"] or r["workflow"] == cur:
            continue
        ccap = dict((a, c) for a, c, _ in ART)[r["capability"]]
        p = pol["policy"].get(ccap) or pol["policy"].get(C.canon(ccap, cat)) or "off"
        to = cat.variant(r["variant"])
        frm = variant_of(cat, wfs[cur]) if cur in wfs else None
        gain = round(r["quality"] - (frm.quality(ccap) if frm else 0), 1)
        kind = U.kind_of(frm, to) if frm else "new"
        row = {"capability": r["capability"], "from": cur, "to": r["workflow"], "policy": p, "kind": kind or "better model",
               "gain": gain, "why": r["why"]}
        if not cur:
            row["why"] = f"nothing makes {r['words']} here yet: {r['why']}"
            out["changes"].append(row)
        elif not pol["enabled"]:
            out["held"].append(dict(row, held="upgrades are switched off ([upgrade] enabled = false)"))
        elif p == "off":
            out["held"].append(dict(row, held=f"the policy for {ccap} is off"))
        elif p == "safe" and not kind:
            out["held"].append(dict(row, held="a different model family, and the policy is safe"))
        elif gain < U.MIN_GAIN and kind != "better quantisation":
            out["held"].append(dict(row, held=f"only {gain:+g} quality"))
        else:
            out["changes"].append(row)
    return out


def policy_for_user(environ=None, uid=None):
    """The [upgrade] table of the asking person's lab.toml (under sudo, theirs, not root's)."""
    u = user_home(environ, uid)
    if not u:
        return None
    path = os.path.join(u[0], ".config", "bromigos", "lab.toml")
    try:
        import tomllib
        with open(path, "rb") as f:
            return dict(tomllib.load(f).get("upgrade") or {})
    except (OSError, ValueError):
        return None


# ---------------------------------------------------------------- the provisioning engine's step
def provision_step(host, it, studio=None):
    """After the container is set up (localprovision.install_quadlet): the models that fit, checked,
    the node packs, the workflows. A server at first boot has nobody's create.toml to write."""
    s = studio or Studio(root=host.root, run=host.run)
    licence = chosen_licence(host.root, host.setting(ITEM, "licence"))
    doc = plan(hw=host.hw, licence=licence, region=C.default_region(), desktop=is_desktop(host.root))
    if not doc["files"]:
        host.emit(f"::note {ITEM} No model fits this card yet: bromigos lab studio plan says why.")
        return
    host.emit(f"::note {ITEM} Fetching {len(doc['files'])} model files ({gib(doc['bytes'])}), each checked against its "
              "published checksum.")
    r = s.apply(doc, user=user_home())
    for x in r["left_out"]:
        host.emit(f"::note {ITEM} Left out {x['workflow']}: {x['why']}.")
    if r["failed"]:
        raise L.ProvisionError(f"{len(r['failed'])} model files didn't download right ({r['failed'][0]['why']}); "
                               "the Fix in Settings › Lab, or bromigos lab studio apply, tries again")
    made = [w for a, _, w in ART if a in r["capabilities"]]
    host.emit(f"::note {ITEM} The Creation studio makes {', '.join(made)}.")


# ---------------------------------------------------------------- for people
def print_plan(doc):
    hw = doc["hardware"]
    card = f"{hw.get('gpu_name') or (hw.get('gpu') or '').upper() + ' card'} ({doc['gives_gib']:g} GiB for models)" \
        if hw.get("gpu") else "no graphics card"
    print(f"For {card}, licences: {doc['licence']}{', region ' + doc['region'] if doc['region'] else ''}:")
    for r in doc["capabilities"]:
        if r["workflow"]:
            extra = f" (and {', '.join(r['also'])})" if r["also"] else ""
            print(f"  {r['words']:<26} {r['model']} {r['quant']}, workflow {r['workflow']}{extra}")
            if r.get("effective_tier") != "clean":
                print(f"  {'':<26} licence: {r['licence']}; {r['effective_tier']} ({r['effective_reason']})")
            for n in r.get("notices") or []:
                print(f"  {'':<26} passing it on: {n}")
        else:
            print(f"  {r['words']:<26} nothing: {r['why']}")
    print(f"{len(doc['files'])} files, {gib(doc['bytes'])} to download at most, each checked against its sha256.")
    for p in doc["node_packs"]:
        print(f"Node pack: {p['name']} ({p['licence']}) at {p['commit'][:12]}")


def print_status(doc):
    if not doc["installed"]:
        print("The Creation studio isn't set up on this machine. Settings › Lab sets it up, or: "
              "sudo bromigos lab apps add comfyui")
        return
    print("Creation studio: " + ("ComfyUI answers" + (f" (ComfyUI {doc['comfyui_version']})" if doc["comfyui_version"] else "")
                                 if doc["answers"] else "ComfyUI doesn't answer (bromigos lab apps logs comfyui says why)"))
    if doc["locked"]:
        print("Its page has no sign-in: it answers your own network only, and nothing can be installed from it.")
    else:
        print("✖ Its page isn't locked: " + "; ".join(doc["lock_problems"]) + ". sudo bromigos lab studio apply locks it.")
    for r in doc["capabilities"]:
        if not r["workflow"]:
            print(f"  · {r['words']:<26} nothing installed")
        elif r["ready"]:
            print(f"  ● {r['words']:<26} ready ({r['workflow']})")
        else:
            print(f"  ✖ {r['words']:<26} {len(r['missing'])} files missing ({r['workflow']})")
    if doc["missing"]:
        print("The Fix in Settings › Lab fetches them again, or: sudo bromigos lab studio apply")
    for c, p in doc["previous"].items():
        print(f"  {c}: the earlier {p['workflow']} is kept; bromigos lab studio rollback {c} puts it back")


def main(argv, self_argv=None):
    p = argparse.ArgumentParser(prog="bromigos lab studio")
    p.add_argument("verb", nargs="?", default="status", choices=("status", "plan", "apply", "rollback", "upgrade"))
    p.add_argument("capability", nargs="?")
    p.add_argument("--licence", choices=LICENCES)
    p.add_argument("--region")
    p.add_argument("--goal", default="balanced", choices=("quality", "balanced", "speed"))
    p.add_argument("--vram", type=float, help="plan for a card with this many GiB")
    p.add_argument("--vendor", choices=("nvidia", "amd"), default="nvidia")
    p.add_argument("--only", help="these workflows only, by name, comma-separated")
    p.add_argument("--apply", action="store_true", help="upgrade: make the changes")
    p.add_argument("--json", action="store_true")
    p.add_argument("--for-uid", type=int, help=argparse.SUPPRESS)     # whose create.toml, inside a job
    try:
        a = p.parse_args(argv)
    except SystemExit as e:
        return EXIT_USAGE if e.code else 0
    from . import labapps
    m = labapps.Machine()
    s = Studio(say=_sayer(m))
    try:
        cat = C.load()
        hw = m.hw() if a.vram is None else {"gpu": a.vendor, "gpu_vram_gb": a.vram, "gpu_name": "", "ram_gb": 64}
        region = a.region if a.region is not None else C.default_region()
        if region in ("any", ""):
            region = None
        licence = chosen_licence(given=a.licence)
        only = [x.strip() for x in a.only.split(",")] if a.only else None
        if a.verb == "status":
            doc = s.status(cat)
            print(json.dumps(doc, indent=1)) if a.json else print_status(doc)
            return EXIT_PROBLEM if doc["installed"] and (doc["missing"] or not doc["answers"] or not doc["locked"]) else 0
        if a.verb == "plan":
            doc = plan(cat, hw, licence, region, a.goal, is_desktop(), only)
            print(json.dumps(doc, indent=1)) if a.json else print_plan(doc)
            return 0
        changes = a.verb in ("apply", "rollback") or (a.verb == "upgrade" and a.apply)
        if changes and not m.in_job() and self_argv:
            # a job of its own (bromigos activity: a unit, named steps, the apps lock; it asks for root)
            inner = [x for x in argv if not x.startswith("--for-uid")] + ["--for-uid", str(os.getuid())]
            title = {"apply": "Setting up the Creation studio's models", "rollback": "Putting the studio's earlier "
                     "models back", "upgrade": "Upgrading the Creation studio's models"}[a.verb]
            code = labapps.as_job(m, self_argv, "app.models", title, f"app:{ITEM}:Images, video and 3D", inner, a.json)
            if code is not None:
                return code
        if changes and not m.may_change():
            raise StudioError(f"{a.verb} changes this machine, so it needs root: sudo bromigos lab studio {a.verb} …")
        user = user_home(uid=a.for_uid)
        if a.verb == "apply":
            if not s.installed():
                raise StudioError("the Creation studio isn't set up on this machine: Settings › Lab sets it up, or "
                                  "sudo bromigos lab apps add comfyui")
            doc = plan(cat, hw, licence, region, a.goal, is_desktop(), only)
            r = s.apply(doc, cat, user=user)
            return _report(r, a.json)
        if a.verb == "rollback":
            r = s.rollback(a.capability, user=user)
            if a.json:
                print(json.dumps(r, indent=1))
            for x in r["rolled_back"]:
                print(f"{x['capability']}: back to {x['to']} (from {x['from']})") if not a.json else None
            return 0
        ev = upgrade(cat, hw, s, policy_for_user(uid=a.for_uid), licence, region, a.goal, is_desktop())
        if not a.apply:
            print(json.dumps(ev, indent=1)) if a.json else _print_upgrade(ev)
            return 0
        if not ev["changes"]:
            print(json.dumps(dict(ev, applied=None), indent=1)) if a.json else _print_upgrade(ev)
            return 0
        caps = {c["capability"] for c in ev["changes"]}
        doc = dict(ev["plan"], capabilities=[r for r in ev["plan"]["capabilities"] if r["capability"] in caps])
        st = s.state()
        keep = [w for c, w in st["capabilities"].items() if c not in caps] + \
               [st["capabilities"][c] for c in caps if c in st["capabilities"]]
        r = s.apply(doc, cat, user=user, keep=keep)
        if a.json:
            print(json.dumps(dict(ev, applied=r), indent=1))
            return 0 if r["ok"] else EXIT_PROBLEM
        _print_upgrade(ev)
        return _report(r, False)
    except StudioError as e:
        print(f"bromigos lab studio: {e}", file=sys.stderr)
        return e.code
    except C.CatalogError as e:
        print(f"bromigos lab studio: {e}", file=sys.stderr)
        return EXIT_UNCHECKED


def _sayer(m):
    if m.in_job():
        return lambda sid, state, words="": print(f"::step {sid} {state}" + (f" {words}" if words else ""), flush=True)
    return lambda sid, state, words="": print(words, flush=True) if words and state == "running" else None


def _report(r, js):
    if js:
        print(json.dumps(r, indent=1))
        return 0 if r["ok"] else EXIT_PROBLEM
    made = [w for a, _, w in ART if a in r["capabilities"]]
    print(f"The Creation studio makes {', '.join(made) or 'nothing yet'}. "
          f"{len(r['fetched'])} files fetched and checked.")
    for x in r["left_out"]:
        print(f"Left out {x['workflow']}: {x['why']}.")
    for x in r["failed"]:
        print(f"Not fetched: {x['dest']}: {x['why']}")
    if r["create_toml"]:
        print(f"bromigos art uses it first: {r['create_toml']}")
    return 0 if r["ok"] else EXIT_PROBLEM


def _print_upgrade(ev):
    print(f"Upgrades: {'on' if ev['enabled'] else 'off'} ([upgrade] in ~/.config/bromigos/lab.toml)")
    for c in ev["changes"]:
        print(f"  {c['capability']}: {c['from'] or 'nothing'} -> {c['to']} ({c['kind']}, {c['gain']:+g} quality)")
    for c in ev["held"]:
        print(f"  {c['capability']}: {c['from']} -> {c['to']} held: {c['held']}")
    if not ev["changes"] and not ev["held"]:
        print("  The studio has the best models that fit, for every kind of art it makes.")


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
