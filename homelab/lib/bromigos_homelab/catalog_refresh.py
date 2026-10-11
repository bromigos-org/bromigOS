"""Keeping the lab model catalog current (docs/lab-models.md, "Staying current").

    bromigos lab models refresh            the newest signed catalog from bromigOS's package
                                           repository (verified with its key), and what's
                                           pending review in it
    bromigos lab models refresh --submit-bench   this lab's catalog-bench results, to the open
                                           catalog pull request (your gh login)
    bromigos lab models refresh --hf       also ask Hugging Face now: newer versions of the
                                           catalog's families, new quantisations of its picks,
                                           new and trending models per capability, whether
                                           bromigOS's runtimes can run them. Flagged, never applied.

The weekly CI run (.github/workflows/lab-catalog.yml) runs `propose`: the same check, written
into models.toml as metadata (sizes, parameter counts, upstream dates) and `[[pending]]`
entries for review (candidates, newer family members, new quantisations, licence changes),
with an evidence report for the pull request. Picks and rankings are never changed here:
a pending entry becomes a pick when someone researches it and edits the catalog by hand.

Hugging Face is read through huggingface_hub (python-huggingface-hub), anonymously unless
HF_TOKEN is set in the environment (higher rate limits; never printed or logged).
"""
import dataclasses
import datetime
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import tomllib
import urllib.error
import urllib.request

from . import catalog as C

KEYRING = ("/usr/share/pacman/keyrings/bromigos.gpg" if os.path.isfile("/usr/share/pacman/keyrings/bromigos.gpg")
           else "/usr/share/bromigos-lab/bromigos.gpg")
PACMAN_CONF = "/etc/pacman.conf"
UA = "bromigos-lab-catalog/1 (+https://github.com/bromigos-org/bromigOS)"

# what each capability looks like on the Hub
PIPELINES = {
    "llm": ("text-generation", "image-text-to-text"), "code": ("text-generation",),
    "embed": ("feature-extraction", "sentence-similarity"), "image": ("text-to-image",),
    "image-edit": ("image-to-image",), "cutout": ("image-segmentation",), "upscale": ("image-to-image",),
    "video": ("image-to-video", "text-to-video"), "3d": ("image-to-3d", "text-to-3d"),
    "tts": ("text-to-speech",), "stt": ("automatic-speech-recognition",), "ocr": ("image-text-to-text",),
    "vision": ("image-text-to-text",)}
NAME_HINT = {"code": r"cod(e|er|ing)", "upscale": r"upscal|super.?res|esrgan|seedvr|\bsr\b",
             "ocr": r"ocr|doc|pars", "cutout": r"rmbg|birefnet|background|matting|segment"}
# publishers whose quantisations are the usual ones (the official org is always trusted)
TRUSTED = ("unsloth", "bartowski", "mlx-community", "nvidia", "RedHatAI", "lmstudio-community", "ggml-org",
           "Comfy-Org", "city96", "QuantStack", "Kijai", "QuantTrio", "cpatonn", "Intel", "AMD", "amd",
           "ISTA-DASLab", "neuralmagic", "LiquidAI", "onnx-community")
LLM_APPS = ("vllm", "sglang", "llama.cpp", "ollama", "mlx-lm")
# Hub licence ids -> the catalog's [licence] ids
HF_LICENCE = {"apache-2.0": "apache-2", "mit": "mit", "cc-by-4.0": "cc-by-4", "cc-by-nc-4.0": "cc-by-nc-4",
              "cc-by-nc-sa-4.0": "cc-by-nc-sa-4", "bsd-3-clause": "bsd-3", "openrail++": "openrail-pp",
              "gemma": "gemma", "llama3.1": "llama-3", "llama3.2": "llama-3", "llama3.3": "llama-3",
              "llama4": "llama-4", "agpl-3.0": "agpl-3"}


# ------------------------------------------------------------------ the signed catalog
def catalog_url():
    """Where the signed catalog is: $BROMIGOS_LAB_CATALOG_URL, [lab] catalog_url, else next to
    the [bromigos] repository pacman.conf names (<server>/lab/models.toml)."""
    if os.environ.get("BROMIGOS_LAB_CATALOG_URL"):
        return os.environ["BROMIGOS_LAB_CATALOG_URL"]
    try:
        from . import config
        u = config.setting("lab", "catalog_url")
        if u:
            return u
    except Exception:                                         # noqa: BLE001
        pass
    try:
        with open(PACMAN_CONF) as f:
            text = f.read()
    except OSError:
        return None
    m = re.search(r"^\[bromigos\]\s*$(.*?)(?=^\[|\Z)", text, re.M | re.S)
    if not m:
        return None
    s = re.search(r"^\s*Server\s*=\s*(\S+)", m.group(1), re.M)
    if not s:
        return None
    base = s.group(1).replace("$repo", "bromigos").replace("$arch", "x86_64").rstrip("/")
    return base + "/lab/models.toml"


def _get(url, timeout=20):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout) as r:       # noqa: S310 - a configured https URL
        return r.read()


def verify(data_path, sig_path, keyring=KEYRING):
    """(ok, why): the detached signature checks out against bromigOS's packaging key."""
    gpgv = shutil.which("gpgv")
    if not gpgv:
        return False, "gpgv isn't installed (gnupg)"
    if not os.path.isfile(keyring):
        return False, f"no {keyring} (reinstall bromigos-lab or bromigos-keyring)"
    p = subprocess.run([gpgv, "--keyring", keyring, sig_path, data_path], capture_output=True, text=True, timeout=30)
    if p.returncode != 0:
        return False, "the signature doesn't match bromigOS's key"
    return True, "signed by bromigOS's packaging key"


def fetch(url=None, keyring=KEYRING, dest=None, current=None):
    """Download the signed catalog and keep it when it verifies and is newer than `current`.
    -> {"ok", "updated", "url_host", "version", "researched", "why"} (never the full URL: it can
    carry a private host)."""
    url = url or catalog_url()
    dest = dest or C.CACHE
    if not url:
        return {"ok": False, "updated": False, "why": "no [bromigos] repository in pacman.conf and no [lab] catalog_url"}
    host = re.sub(r"^\w+://([^/]+).*$", r"\1", url)
    try:
        cur = current or C.load()
    except C.CatalogError:
        cur = None
    with tempfile.TemporaryDirectory() as tmp:
        data, sig = os.path.join(tmp, "models.toml"), os.path.join(tmp, "models.toml.sig")
        try:
            with open(data, "wb") as f:
                f.write(_get(url))
            with open(sig, "wb") as f:
                f.write(_get(url + ".sig"))
        except (urllib.error.URLError, OSError, TimeoutError) as e:
            return {"ok": False, "updated": False, "url_host": host,
                    "why": f"couldn't download it ({getattr(e, 'reason', None) or type(e).__name__})"}
        ok, why = verify(data, sig, keyring)
        if not ok:
            return {"ok": False, "updated": False, "url_host": host, "why": why}
        try:
            new = C.Catalog(tomllib.load(open(data, "rb")), data)
        except (tomllib.TOMLDecodeError, C.CatalogError, KeyError) as e:
            return {"ok": False, "updated": False, "url_host": host, "why": f"it doesn't parse: {e}"}
        problems = C.validate(new)
        if problems:
            return {"ok": False, "updated": False, "url_host": host, "why": f"it isn't consistent: {problems[0]}"}
        if cur is not None and new.version <= cur.version:
            return {"ok": True, "updated": False, "url_host": host, "version": cur.version,
                    "researched": cur.researched, "why": "already the newest"}
        os.makedirs(dest, exist_ok=True)
        for src, name in ((data, "models.toml"), (sig, "models.toml.sig")):
            shutil.copyfile(src, os.path.join(dest, name + ".new"))
        os.replace(os.path.join(dest, "models.toml.sig.new"), os.path.join(dest, "models.toml.sig"))
        os.replace(os.path.join(dest, "models.toml.new"), os.path.join(dest, "models.toml"))
        return {"ok": True, "updated": True, "url_host": host, "version": new.version,
                "researched": new.researched, "why": why}


# ------------------------------------------------------------------ Hugging Face
def hub():
    try:
        from huggingface_hub import HfApi
    except ImportError as e:
        raise C.CatalogError("this needs huggingface_hub (sudo pacman -S python-huggingface-hub)") from e
    return HfApi(token=os.environ.get("HF_TOKEN") or False)


def _licence_id(info):
    tags = getattr(info, "tags", None) or []
    for t in tags:
        if t.startswith("license:"):
            return t.split(":", 1)[1]
    cd = getattr(info, "card_data", None)
    if cd:
        try:
            return cd.get("license")
        except AttributeError:
            return getattr(cd, "license", None)
    return None


def _quant_of(repo_id, tags=(), library=None):
    s = (repo_id + " " + " ".join(tags or ()) + " " + (library or "")).lower()
    for pat, q in ((r"gguf", "GGUF"), (r"nvfp4", "NVFP4"), (r"mxfp4", "MXFP4"), (r"\bfp8|fp8[-_]", "FP8"),
                   (r"awq", "AWQ"), (r"gptq", "GPTQ"), (r"int4|w4a16", "INT4"), (r"int8|w8a8", "INT8"),
                   (r"\bmlx\b|mlx-community", "MLX"), (r"onnx", "ONNX"), (r"exl[23]", "EXL")):
        if re.search(pat, s):
            return q
    return None


def _days_ago(dt):
    if not dt:
        return None
    if isinstance(dt, str):
        dt = datetime.datetime.fromisoformat(dt.replace("Z", "+00:00"))
    return (datetime.datetime.now(datetime.timezone.utc) - dt).days


# the Hub pipelines of the kinds of model the catalog holds: a family's newer member under any
# other (robotics, reinforcement-learning, …) is another product with the same name
KIN_PIPELINES = {t for tags in PIPELINES.values() for t in tags} | {"image-to-image", "any-to-any"}

NOISE = re.compile(r"lora|adapter|abliterat|uncensor|heretic|merge|distill-?ed-?from|finetune|fine-tune|"
                   r"character|sheet|preview-?ft|-ft-|gguf|awq|gptq|mlx|fp8|nvfp4|int4|int8|exl\d", re.I)


def _stem(name):
    """("qwen", (3, 8)) for "Qwen3.8-27B": the product's letters and its version."""
    m = re.match(r"([A-Za-z][A-Za-z-]*?)[-_. ]?v?(\d+(?:\.\d+)*)", name)
    if not m:
        return name.lower(), ()
    return m.group(1).lower().rstrip("-_."), tuple(int(x) for x in m.group(2).split("."))


@dataclasses.dataclass
class Finding:
    id: str                  # stable: hf:<repo>, or <kind>:<model id>
    kind: str                # metadata | quantisation | newer in family | new model | licence changed
    capability: str
    title: str
    why: str
    repo: str = ""
    evidence: tuple = ()
    stack: str = ""
    licence: str = ""
    size_gib: float = 0.0
    model: str = ""          # the catalog model it concerns
    field: str = ""          # metadata: the field and its new value
    value: object = None
    review: bool = True

    def doc(self):
        d = {k: v for k, v in dataclasses.asdict(self).items() if v not in ("", None, (), [], 0.0)}
        d["evidence"] = list(self.evidence)
        d["found"] = datetime.date.today().isoformat()
        return d


def _support(api, cap, repo, arch_registry=None, comfy=None):
    """Whether bromigOS's stack runs it: 'ready (…)' or 'needs support: …'."""
    if cap in ("llm", "code", "vision", "ocr", "embed"):
        apps = []
        for app in LLM_APPS:
            try:
                if any(m.id == repo for m in api.list_models(apps=app, search=repo.split("/")[-1], limit=20)):
                    apps.append(app)
            except Exception:                                 # noqa: BLE001 - a filter the Hub may not know
                continue
        if apps:
            return "ready (" + ", ".join(apps) + ")"
        return "needs support: no vLLM, llama.cpp, Ollama or MLX support on the Hub yet"
    if cap in ("tts", "stt"):
        return "needs support: a new voice-service backend (check its runtime)"
    name = repo.split("/")[-1].lower()
    for c in comfy or ():
        cn = c.split("/")[-1].lower().replace("_comfyui", "")
        if cn and (cn in name or name.startswith(cn)):
            return f"ready (ComfyUI: {c})"
    return "needs support: no ComfyUI-native repackage (Comfy-Org) yet"


def hf_check(cat, api=None, since_days=60, min_likes=40, per_tag=25, families=True, trending=True, quants=True,
             log=None):
    """Findings from the Hub for this catalog: [Finding]. Errors are findings too (kind error)."""
    api = api or hub()
    say = log or (lambda *_: None)
    out, known = [], set()
    for m in cat.models.values():
        for r in (m.repo, *[v.weights for v in m.variants]):
            if r and "/" in r and " " not in r:
                known.add(r.split(":")[0].lower())
    for p in cat.pending:
        if p.get("repo"):
            known.add(p["repo"].lower())
    try:
        comfy = [m.id for m in api.list_models(author="Comfy-Org", limit=400)]
    except Exception as e:                                    # noqa: BLE001
        comfy = []
        out.append(Finding("error:comfy-org", "error", "", "Comfy-Org's repos didn't list", str(e)[:200], review=False))
    # 1. the catalog's own models: parameters, licence, upstream changes
    pipes = {}
    for m in cat.models.values():
        if not m.repo or "/" not in m.repo:
            continue
        try:
            info = api.model_info(m.repo, expand=["safetensors", "cardData", "lastModified", "createdAt", "tags",
                                                  "gated", "library_name"])
        except Exception as e:                                # noqa: BLE001
            out.append(Finding(f"error:{m.id}", "error", m.caps[0], f"{m.repo} didn't answer",
                               f"{type(e).__name__}: {str(e)[:160]}", m.repo, review=False, model=m.id))
            continue
        say(f"  {m.repo}")
        st = getattr(info, "safetensors", None)
        if st and getattr(st, "total", None) and st.total > 1e8:
            pb = round(st.total / 1e9, 2)
            if m.params_b and abs(pb - m.params_b) / max(m.params_b, 1e-6) > 0.05:
                out.append(Finding(f"metadata:{m.id}:params_b", "metadata", m.caps[0], f"{m.name}: parameters",
                                   f"the Hub counts {pb} B parameters, the catalog {m.params_b} B", m.repo,
                                   (f"https://huggingface.co/{m.repo}",), model=m.id, field="params_b", value=pb,
                                   review=False))
        pipes[m.id] = getattr(info, "pipeline_tag", None)
        lic = _licence_id(info)
        known_ids = set(m.licence.hub) | {m.licence.id, HF_LICENCE.get(m.licence.id, m.licence.id)}
        if lic and lic not in ("other", "unknown") and lic not in known_ids \
                and HF_LICENCE.get(lic, lic) not in known_ids:     # "other": a custom licence, read on the card
            out.append(Finding(f"licence:{m.id}:{lic}", "licence changed", m.caps[0], f"{m.name}: licence",
                               f"the Hub says {lic}; the catalog has {m.licence.id} ({m.licence.name}). Check the "
                               "card before changing it: the licence filter depends on it", m.repo,
                               (f"https://huggingface.co/{m.repo}",), licence=lic, model=m.id))
    # 2. new quantisations of the catalog's models, by the usual publishers
    if quants:
        for m in cat.models.values():
            if not m.repo or "/" not in m.repo:
                continue
            author = m.repo.split("/")[0]
            try:
                qs = list(api.list_models(filter=f"base_model:quantized:{m.repo}", sort="downloads", limit=40,
                                          expand=["downloads", "tags", "library_name", "createdAt"]))
            except Exception:                                 # noqa: BLE001
                continue
            have_kinds = {_quant_of(v.weights or v.quant, (), None) or _quant_of(v.quant, (), None)
                          for v in m.variants}
            seen_kind = set()
            for q in qs:
                pub = q.id.split("/")[0]
                if q.id.lower() in known or (pub not in TRUSTED and pub != author):
                    continue
                kind = _quant_of(q.id, q.tags, q.library_name)
                if not kind or kind in have_kinds or kind in seen_kind or (q.downloads or 0) < 500:
                    continue                                  # a kind the catalog has already, or a minor one
                seen_kind.add(kind)
                known.add(q.id.lower())
                out.append(Finding(f"hf:{q.id}", "quantisation", m.caps[0], f"{q.id}: {kind} of {m.name}",
                                   f"{kind} by {pub}, {q.downloads or 0} downloads; the catalog has no {kind} "
                                   "variant of it", q.id, (f"https://huggingface.co/{q.id}",), model=m.id,
                                   review=False))
    # 3. newer members of each family, by the same publisher
    if families:
        seen_fam = set()
        for m in cat.models.values():
            if not m.repo or not m.family or (m.repo.split("/")[0], m.family) in seen_fam:
                continue
            seen_fam.add((m.repo.split("/")[0], m.family))
            stem, ver = _stem(m.repo.split("/")[-1])
            if not stem:
                continue
            try:
                cands = list(api.list_models(author=m.repo.split("/")[0], search=stem, sort="created_at", limit=20,
                                             expand=["createdAt", "likes", "tags", "pipeline_tag"]))
            except Exception:                                 # noqa: BLE001
                continue
            for x in cands:
                if x.id.lower() in known or _quant_of(x.id, x.tags) or NOISE.search(x.id):
                    continue
                xs, xv = _stem(x.id.split("/")[-1])
                if xs != stem or not xv or (ver and xv <= ver):
                    continue                                  # another product, or not a newer version
                xp = getattr(x, "pipeline_tag", None)
                if pipes.get(m.id) and xp != pipes.get(m.id):
                    continue                                  # the same kind of model (a robot policy isn't an image model)
                if xp and xp not in KIN_PIPELINES:
                    continue                                  # FLUX.3 action is a robot policy, not FLUX.2's successor
                age = _days_ago(getattr(x, "created_at", None))
                rel = m.released or ""
                if age is None or age > since_days or (rel and str(x.created_at)[:7] <= rel):
                    continue
                known.add(x.id.lower())
                cap = m.caps[0]
                out.append(Finding(f"hf:{x.id}", "newer in family", cap, f"{x.id}: newer {m.family}",
                                   f"{m.repo.split('/')[0]} published it {age} days ago ({x.likes or 0} likes); the "
                                   f"catalog's {m.family} is {m.name} ({m.released or 'undated'})", x.id,
                                   (f"https://huggingface.co/{x.id}",), _support(api, cap, x.id, comfy=comfy),
                                   model=m.id))
    # 4. new and trending models per capability
    if trending:
        for cap, tags in PIPELINES.items():
            for tag in tags:
                try:
                    xs = list(api.list_models(pipeline_tag=tag, sort="trending_score", limit=per_tag,
                                              expand=["createdAt", "likes", "tags", "downloads"]))
                except Exception as e:                        # noqa: BLE001
                    out.append(Finding(f"error:trending:{tag}", "error", cap, f"trending {tag} didn't list",
                                       str(e)[:160], review=False))
                    continue
                for x in xs:
                    if x.id.lower() in known or (x.likes or 0) < min_likes or NOISE.search(x.id):
                        continue
                    if (x.downloads or 0) < 300:
                        continue                              # liked but not used yet
                    if _quant_of(x.id, x.tags) or any(t.startswith("base_model:") for t in (x.tags or ())):
                        continue                              # a quant, fine-tune or adapter of something else
                    if NAME_HINT.get(cap) and not re.search(NAME_HINT[cap], x.id, re.I):
                        continue
                    if cap in ("upscale", "cutout") and not NAME_HINT.get(cap):
                        continue
                    age = _days_ago(getattr(x, "created_at", None))
                    if age is None or age > since_days:
                        continue
                    known.add(x.id.lower())
                    out.append(Finding(f"hf:{x.id}", "new model", cap, f"{x.id}: trending {tag}",
                                       f"new in the last {since_days} days ({age} days old), {x.likes or 0} likes, "
                                       f"{x.downloads or 0} downloads", x.id, (f"https://huggingface.co/{x.id}",),
                                       _support(api, cap, x.id, comfy=comfy), licence=_licence_id(x) or ""))
    return out


# ------------------------------------------------------------------ the CI proposal
def propose(path, findings, today=None):
    """models.toml's new text: metadata applied (parameter counts), new [[pending]] entries
    appended, `version` bumped and `refreshed` set. -> (text, {"metadata": n, "pending": n,
    "review": n}). Needs tomlkit (keeps the file's comments and layout)."""
    import tomlkit
    today = today or datetime.date.today().isoformat()
    with open(path) as f:
        doc = tomlkit.parse(f.read())
    counts = {"metadata": 0, "pending": 0, "review": 0}
    models = {m["id"]: m for m in doc.get("model", [])}
    for fd in findings:
        if fd.kind == "metadata" and fd.model in models and fd.field in ("params_b", "disk_gib", "released"):
            models[fd.model][fd.field] = fd.value
            counts["metadata"] += 1
    pend = doc.get("pending")
    if pend is None:
        pend = tomlkit.aot()
        doc["pending"] = pend
    have = {p.get("id") for p in pend}
    for fd in findings:
        if fd.kind in ("metadata", "error", "quantisation") or fd.id in have:
            continue                                        # quantisations: in the report, not the catalog
        t = tomlkit.table()
        for k, v in fd.doc().items():
            if k in ("value", "field"):
                continue
            t[k] = v
        t["state"] = "pending review" if fd.review else "noted"
        pend.append(t)
        have.add(fd.id)
        counts["pending"] += 1
        counts["review"] += 1 if fd.review else 0
    if counts["metadata"] or counts["pending"]:
        doc["version"] = int(doc.get("version", 0)) + 1
        doc["refreshed"] = today
    return tomlkit.dumps(doc), counts


def report(cat, findings, counts):
    """The pull request's evidence report (Markdown)."""
    lines = [f"Weekly lab model catalog refresh ({datetime.date.today().isoformat()}).", "",
             f"Catalog researched {cat.researched}; this run: {counts['metadata']} metadata updates, "
             f"{counts['pending']} new pending entries ({counts['review']} for review).", "",
             "Picks and rankings are unchanged: a pending entry becomes a pick only when someone researches it "
             "(quality, peak VRAM, speed, licence) and edits `homelab/share/lab/models.toml` by hand "
             "(docs/lab-models.md, \"Staying current\").", ""]
    groups = {}
    for f in findings:
        groups.setdefault(f.kind, []).append(f)
    for kind in ("newer in family", "new model", "licence changed", "quantisation", "metadata", "error"):
        fs = groups.get(kind)
        if not fs:
            continue
        lines.append(f"### {kind.capitalize()} ({len(fs)})\n")
        lines.append("| Capability | What | Why | Our stack | Link |")
        lines.append("|---|---|---|---|---|")
        for f in fs[:60]:
            link = f.evidence[0] if f.evidence else ""
            lines.append(f"| {f.capability} | {f.title} | {f.why} | {f.stack or '-'} | {link} |")
        lines.append("")
    return "\n".join(lines)


# ------------------------------------------------------------------ bench results to the pull request
def submit_bench(repo="bromigos-org/bromigOS"):
    """Posts this lab's catalog-bench results (the latest per model and GPU) to the open catalog
    pull request, through your own gh login. GPU and model names only: never a host."""
    from . import catalog_bench
    rows = [r for per in catalog_bench.results().values() for r in per.values()]
    if not rows:
        print("no bench results yet (bromigos lab run catalog-bench --model …)", file=sys.stderr)
        return 1
    gh = shutil.which("gh")
    if not gh:
        print("this needs the GitHub CLI (gh) and a login with access to " + repo, file=sys.stderr)
        return 2
    p = subprocess.run([gh, "pr", "list", "-R", repo, "--label", "lab-catalog", "--state", "open", "--json",
                        "number,url", "--limit", "1"], capture_output=True, text=True, timeout=60)
    prs = json.loads(p.stdout or "[]") if p.returncode == 0 else []
    kind = "pr"
    if not prs:                                  # the refresh files an issue where Actions can't open PRs
        p = subprocess.run([gh, "issue", "list", "-R", repo, "--label", "lab-catalog", "--state", "open", "--json",
                            "number,url", "--limit", "1"], capture_output=True, text=True, timeout=60)
        prs = json.loads(p.stdout or "[]") if p.returncode == 0 else []
        kind = "issue"
    if not prs:
        print("no open lab-catalog pull request or issue to add them to", file=sys.stderr)
        return 1
    keep = ("key", "capability", "gpu", "t", "catalog", "seconds", "peak_vram_gib", "realtime_x", "concurrency",
            "served", "note")
    body = ["<!-- bromigos-bench -->", "Measured on a lab by `catalog-bench` (bromigos lab models refresh "
            "--submit-bench):", "", "```json", json.dumps([{k: r[k] for k in keep if k in r} for r in rows], indent=1),
            "```"]
    with tempfile.NamedTemporaryFile("w", suffix=".md", delete=False) as f:
        f.write("\n".join(body))
        tmp = f.name
    try:
        p = subprocess.run([gh, kind, "comment", str(prs[0]["number"]), "-R", repo, "--body-file", tmp],
                           capture_output=True, text=True, timeout=60)
    finally:
        os.unlink(tmp)
    if p.returncode != 0:
        print("gh pr comment failed: " + (p.stderr.strip().splitlines() or ["?"])[-1], file=sys.stderr)
        return 2
    print(f"posted {len(rows)} result(s) to {prs[0]['url']}")
    return 0


# ------------------------------------------------------------------ the command
def pending(cat):
    return [p for p in cat.pending if p.get("state", "pending review") != "dismissed"]


def main(argv):
    js = "--json" in argv
    if argv and argv[0] == "propose":
        # CI: propose [--catalog PATH] [--out PATH] [--report PATH] [--since DAYS]
        path = C._arg(argv, "--catalog", os.path.join(os.path.dirname(C.HERE), "..", "share", "lab", "models.toml"))
        cat = C.load(path)
        fs = hf_check(cat, since_days=int(C._arg(argv, "--since", 60)), log=lambda s: print(s, file=sys.stderr))
        text, counts = propose(path, fs)
        with open(C._arg(argv, "--out", path), "w") as f:
            f.write(text)
        rep = report(cat, fs, counts)
        if C._arg(argv, "--report"):
            with open(C._arg(argv, "--report"), "w") as f:
                f.write(rep)
        print(json.dumps({"counts": counts, "review": counts["review"] > 0,
                          "changed": bool(counts["metadata"] or counts["pending"])}))
        return 0
    if "--weekly" in argv:
        # bromigos-lab-models.timer: the newest signed catalog, then one quiet nudge if a better
        # model fits a GPU (never an install)
        from . import catalog_upgrade, config
        if not config.sources():
            return 0
        f = fetch()
        if not f.get("ok"):
            print(f"catalog: {f['why']}", file=sys.stderr)
        return catalog_upgrade.main(["--nudge"])
    if "--submit-bench" in argv:
        return submit_bench(C._arg(argv, "--repo", "bromigos-org/bromigOS"))
    out = {"fetch": None, "pending": [], "hub": None}
    if "--offline" not in argv:
        out["fetch"] = fetch()
    try:
        cat = C.load()
    except C.CatalogError as e:
        print(f"bromigos lab models refresh: {e}", file=sys.stderr)
        return 2
    out["catalog"] = {"path": cat.path, "version": cat.version, "researched": cat.researched,
                      "refreshed": cat.refreshed}
    out["pending"] = pending(cat)
    if "--hf" in argv:
        try:
            fs = hf_check(cat, since_days=int(C._arg(argv, "--since", 60)),
                          log=None if js else (lambda s: print(s, file=sys.stderr)))
        except C.CatalogError as e:
            print(f"bromigos lab models refresh: {e}", file=sys.stderr)
            return 2
        out["hub"] = [f.doc() for f in fs]
    if js:
        print(json.dumps(out, indent=1, default=str))
        return 0
    f = out["fetch"]
    if f:
        print(("catalog: " + (f"updated to version {f['version']} (researched {f['researched']})" if f["updated"]
                              else f"{f['why']}")) + (f" · from {f['url_host']}" if f.get("url_host") else ""))
    c = out["catalog"]
    print(f"in use: {c['path']} · version {c['version']} · researched {c['researched']} · refreshed {c['refreshed']}")
    if out["pending"]:
        print(f"\npending review ({len(out['pending'])}):")
        for p in out["pending"]:
            print(f"  [{p.get('capability', '')}] {p.get('title', p.get('id'))}: {p.get('why', '')}"
                  + (f" · {p['stack']}" if p.get("stack") else ""))
    if out["hub"] is not None:
        print(f"\nHugging Face now ({len(out['hub'])} findings, flagged, nothing applied):")
        for h in out["hub"]:
            if h["kind"] == "error":
                continue
            print(f"  {h['kind']:<16} [{h.get('capability', '')}] {h['title']}: {h['why']}"
                  + (f" · {h['stack']}" if h.get("stack") else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
