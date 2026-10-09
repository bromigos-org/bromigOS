"""The lab model catalog: for every AI capability, the best open models a machine can run
(docs/lab-models.md). `bromigos lab models recommend | plan | pick | refresh` (the console's
bromigos-lab calls main()), the Settings › Lab page's planner, provisioning and `bromigos
target check`'s note all read it.

    from bromigos_homelab import catalog
    catalog.pick("image", 12)                         # the best fit for a 12 GB card, and why
    catalog.pick("llm", 24, vendor="amd", licence="commercial", goal="speed")
    hw = catalog.Hardware.parse(["RTX 5090", "RTX 5070,desktop"], ram_gib=64)
    catalog.plan(hw, budgets={"RTX 5070": 6})         # two to four ranked configurations

The data is models.toml: homelab/share/lab/ in the repository, /usr/share/bromigos/homelab/lab/
from the bromigos-lab-catalog package, and a newer signed copy `refresh` keeps in
~/.cache/bromigos/lab/. It records facts per model variant (peak VRAM and RAM, speed on a
reference card, a quality score with its source, the licence, the runtime, whether bromigOS's
stack runs it); the picks are computed from them for any VRAM, vendor, licence filter and
goal, so a 10 GB card or a 4x H100 box gets an answer as well as the tiers in the docs.
"""
import dataclasses
import fnmatch
import glob
import itertools
import json
import math
import os
import re
import shutil
import subprocess
import sys
import tomllib

HERE = os.path.dirname(os.path.abspath(__file__))
SHARE = os.environ.get("BROMIGOS_SHARE_DIR") or "/usr/share/bromigos"
CACHE = os.path.join(os.environ.get("XDG_CACHE_HOME") or os.path.expanduser("~/.cache"), "bromigos", "lab")

CAPABILITIES = ("llm", "code", "embed", "image", "image-edit", "cutout", "upscale", "video", "3d", "tts", "stt",
                "ocr", "vision")
# the services' names (targets.toml, create.toml) for the same capabilities
ALIASES = {"image.generate": "image", "image.edit": "image-edit", "image.cutout": "cutout", "video.loop": "video",
           "image.upscale": "upscale", "video.upscale": "upscale",
           "model3d.generate": "3d", "voice.tts": "tts", "voice.stt": "stt", "llm.code": "code",
           "model3d": "3d", "edit": "image-edit", "brain": "llm"}
# the tiers the docs' tables use (VRAM of one card, GiB as sold), then the bigger setups
TIERS = ("cpu", "8", "12", "16", "24", "32", "48", "80", "96")
SETUPS = {
    "2x24": ("RTX 4090", 2), "2x32": ("RTX 5090", 2), "4x24": ("RTX 4090", 4), "4x32": ("RTX 5090", 4),
    "1x80": ("H100", 1), "2x80": ("H100", 2), "4x80": ("H100", 4), "8x80": ("H100", 8), "8xb200": ("B200", 8),
    "spark": ("GB10", 1), "2xspark": ("GB10", 2, None, "linked"),
    "mac-64": ("Apple M4 Max", 1, 64), "mac-128": ("Apple M4 Max", 1, 128), "mac-192": ("Apple M2 Ultra", 1, 192),
    "mac-512": ("Apple M3 Ultra", 1, 512),
}
GOALS = ("quality", "balanced", "speed", "throughput")   # throughput: many agents on one LLM
LICENCE_FILTERS = ("any", "commercial", "permissive")
PRIORITIES = ("balanced", "brain", "media", "voice", "resident")
# how much each capability counts in a plan (VECTOR's brain and voice first); models.toml's
# [capability.<id>] weight overrides
WEIGHT = {"llm": 2.5, "tts": 1.8, "stt": 1.6, "embed": 1.0, "image": 1.0, "image-edit": 0.6, "video": 1.0,
          "3d": 0.6, "cutout": 0.5, "upscale": 0.4, "ocr": 0.6, "vision": 0.8, "code": 1.0}
# below these a capability isn't usable live (tok/s for one stream, x realtime for voice)
FLOOR = {"llm": 15.0, "code": 15.0, "vision": 10.0, "tts": 1.5, "stt": 3.0, "embed": 0.5}
FLOOR_PENALTY = 45.0
GOAL_WEIGHTS = {"quality": (1.0, 0.01), "balanced": (0.7, 0.3), "speed": (0.35, 0.65), "throughput": (0.5, 0.5)}
SERVED = ("llm", "code", "vision")    # served to many clients: the KV cache and batching matter
QUANT_DELTA = [  # quality lost to compression when a variant doesn't say (points of 100)
    (r"^(bf16|fp16|fp32|f16|full)$", 0.0), (r"q8|int8|fp8|w8a8|8bit|8-bit", -0.5), (r"mxfp4", -0.5),
    (r"q6", -0.8), (r"nvfp4|fp4", -1.5), (r"q5", -1.2), (r"awq|gptq|int4|w4a16|4bit|4-bit", -1.8),
    (r"q4", -2.0), (r"q3", -4.0), (r"q2|iq2", -7.0)]
OTHER_VARIANT_PENALTY = 0.0
DISK_GIB_S = 1.6           # how fast a cold model loads from local NVMe (GiB/s, conservative)
# the span the 0..100 speed score covers, by unit (a fixed scale, so a catalog with two
# similar models doesn't make a small difference look large)
SPEED_SPAN = {"tok/s": (5.0, 80.0), "s/image": (1.0, 240.0), "min/clip": (0.3, 45.0), "s/mesh": (5.0, 900.0),
              "x realtime": (0.3, 300.0), "s/page": (0.2, 60.0), "k tok/s": (0.2, 200.0), "pages/s": (0.02, 10.0)}


class CatalogError(Exception):
    pass


# ------------------------------------------------------------------ the data
@dataclasses.dataclass
class Licence:
    id: str
    name: str
    url: str = ""
    commercial: str = "no"           # yes | conditional | no
    conditions: str = ""
    territory: tuple = ()            # regions it is NOT licensed in ("EU", "UK", "KR")
    outputs: str = ""
    permissive: bool = False         # OSI or CC-BY class: no use restrictions beyond attribution
    hub: tuple = ()                  # the Hugging Face licence ids it appears as (the refresh compares them)

    def allows(self, filt="any", region=None):
        """(ok, why). filt: any | commercial | permissive. region: the user's ("EU", "UK", …)."""
        if region and region.upper() in self.territory:
            return False, f"{self.name} isn't licensed in {region.upper()}"
        if filt == "commercial" and self.commercial == "no":
            return False, f"{self.name}: no commercial use"
        if filt == "permissive" and not (self.permissive and self.commercial == "yes" and not self.territory):
            return False, f"{self.name} has conditions ({self.conditions or self.commercial})"
        return True, ""

    def plain(self):
        if self.commercial == "yes" and not self.territory:
            s = "commercial use OK"
        elif self.commercial == "no":
            s = "non-commercial only"
        else:
            s = "commercial with conditions"
        if self.territory:
            s += "; not licensed in " + ", ".join(self.territory)
        return s


@dataclasses.dataclass
class Cap:
    id: str
    title: str
    service: str = ""
    residency: str = "demand"        # always (resident) | demand (loaded per job, unloaded when idle)
    unit: str = ""                   # tok/s, s/image, min/clip, s/mesh, x realtime, s/page, k/s
    better: str = "higher"           # higher | lower (for the speed figure)
    scale: str = "bandwidth"         # how speed moves between cards: bandwidth | compute | none
    order: int = 50
    notes: str = ""
    span: tuple = ()                 # (lo, hi) for the speed score; default by unit
    weight: float = 1.0              # how much it counts in a plan against the others
    floor: float = 0.0               # the slowest that is still usable (a live voice, an agent's brain)


@dataclasses.dataclass
class GpuSpec:
    name: str
    vendor: str = "nvidia"
    vram_gib: float = 0.0
    arch: str = ""
    bandwidth: float = 0.0           # GB/s
    compute: float = 0.0             # dense BF16 TFLOPS (relative is what matters)
    unified: bool = False
    usable: float = 0.0              # unified memory: the share models may use by default
    match: tuple = ()


@dataclasses.dataclass
class Variant:
    model: "Model"
    id: str
    runtime: str
    quant: str = ""
    weights: str = ""
    vram_gib: float = 0.0            # peak, all GPUs together
    vram_note: str = ""
    ram_gib: float = 0.0             # system RAM it needs besides (offload, CPU runtimes)
    disk_gib: float = 0.0            # what a cold load reads
    speed: float = 0.0               # in its capability's unit, on speed_ref
    speed_ref: str = ""              # the GPU it was measured on (a [gpu] name), "cpu" for CPU
    speed_note: str = ""
    vendors: tuple = ("nvidia",)     # nvidia, amd, apple, intel, cpu
    arch: tuple = ()                 # only these architectures (e.g. blackwell for NVFP4)
    gpus: int = 1                    # GPUs it needs (tensor parallel)
    split: tuple = ()                # GPU counts it may be split across (vllm: 1 2 4 8)
    stack: str = "ready"             # ready | needs support: <what>
    offload: bool = False            # parts in system RAM (fits a smaller card, slower)
    fast: bool = False               # distilled / turbo / few-step
    workflow: str = ""               # the ComfyUI workflow (create.toml's comfyui = ...)
    quality_delta: float = None
    weights_gib: float = 0.0         # the weights alone (LLMs: the KV cache comes on top)
    match: tuple = ()                # globs that recognise it installed (file names, served names)
    notes: str = ""
    caps: tuple = ()                 # only these of its model's capabilities (default: all)

    @property
    def key(self):
        return f"{self.model.id}/{self.id}"

    @property
    def ready(self):
        return self.stack == "ready"

    def serves(self, cap):
        return cap in (self.caps or self.model.caps)

    def quality(self, cap):
        q = self.model.quality.get(cap, self.model.quality.get("*"))
        if q is None:
            return 0.0
        d = self.quality_delta
        if d is None:
            d = 0.0
            for pat, v in QUANT_DELTA:
                if re.search(pat, (self.quant or "").lower()):
                    d = v
                    break
        return round(q + d, 1)

    def splits(self):
        if self.split:
            return tuple(sorted(set(self.split)))
        if self.runtime in ("vllm", "sglang"):
            return (1, 2, 4, 8)
        if self.runtime in ("llama.cpp", "ollama"):
            return (1, 2, 3, 4, 8)
        return (1,)


@dataclasses.dataclass
class Model:
    id: str
    name: str
    caps: tuple
    licence: Licence
    family: str = ""
    repo: str = ""
    url: str = ""
    released: str = ""
    quality: dict = dataclasses.field(default_factory=dict)   # cap -> 0..100 within that capability
    quality_note: str = ""
    params_b: float = 0.0
    active_b: float = 0.0
    kv_kib_per_token: float = 0.0    # KV cache per token at BF16 (full-attention layers)
    state_mib_per_seq: float = 0.0   # fixed state per sequence (linear attention, Mamba)
    max_context: int = 0
    serving: tuple = ()              # published serving benchmarks
    features: tuple = ()
    cite: tuple = ()
    notes: str = ""
    variants: list = dataclasses.field(default_factory=list)


class Catalog:
    def __init__(self, doc, path=""):
        self.path = path
        self.doc = doc
        if doc.get("format") != 1:
            raise CatalogError(f"{path}: format {doc.get('format')!r} isn't 1")
        self.researched = str(doc.get("researched", ""))
        self.refreshed = str(doc.get("refreshed", self.researched))
        self.version = int(doc.get("version", 0))
        self.licences = {}
        for lid, t in (doc.get("licence") or {}).items():
            self.licences[lid] = Licence(lid, t.get("name", lid), t.get("url", ""), t.get("commercial", "no"),
                                         t.get("conditions", ""), tuple(t.get("territory", ())), t.get("outputs", ""),
                                         bool(t.get("permissive", False)), tuple(t.get("hub", ())))
        self.caps = {}
        for i, cid in enumerate(CAPABILITIES):
            t = (doc.get("capability") or {}).get(cid) or {}
            self.caps[cid] = Cap(cid, t.get("title", cid), t.get("service", ""), t.get("residency", "demand"),
                                 t.get("unit", ""), t.get("better", "higher"), t.get("scale", "bandwidth"),
                                 int(t.get("order", (i + 1) * 10)), t.get("notes", ""),
                                 tuple(t.get("speed_span", ())), float(t.get("weight", WEIGHT.get(cid, 1.0))),
                                 float(t.get("floor", FLOOR.get(cid, 0.0))))
        self.gpus = {}
        for name, t in (doc.get("gpu") or {}).items():
            self.gpus[name] = GpuSpec(name, t.get("vendor", "nvidia"), float(t.get("vram_gib", 0)), t.get("arch", ""),
                                      float(t.get("bandwidth", 0)), float(t.get("compute", 0)),
                                      bool(t.get("unified", False)), float(t.get("usable", 0)),
                                      tuple(t.get("match", ())))
        self.models = {}
        for m in doc.get("model") or []:
            lic = self.licences.get(m.get("licence"))
            if lic is None:
                raise CatalogError(f"{path}: model {m.get('id')}: unknown licence {m.get('licence')!r}")
            caps = tuple(ALIASES.get(c, c) for c in m.get("capabilities", ()))
            bad = [c for c in caps if c not in CAPABILITIES]
            if bad:
                raise CatalogError(f"{path}: model {m.get('id')}: unknown capabilities {bad}")
            q = m.get("quality", {})
            if not isinstance(q, dict):
                q = {"*": q}
            mod = Model(id=m["id"], name=m.get("name", m["id"]), caps=caps, licence=lic, family=m.get("family", ""),
                        repo=m.get("repo", ""),
                        url=m.get("url", "") or (f"https://huggingface.co/{m['repo']}" if m.get("repo") else ""),
                        released=str(m.get("released", "")),
                        quality={ALIASES.get(k, k): float(v) for k, v in q.items()},
                        quality_note=m.get("quality_note", ""), params_b=float(m.get("params_b", 0)),
                        active_b=float(m.get("active_b", 0) or m.get("params_b", 0)),
                        kv_kib_per_token=float(m.get("kv_kib_per_token", 0)),
                        state_mib_per_seq=float(m.get("state_mib_per_seq", 0)),
                        max_context=int(m.get("max_context", 0)), serving=tuple(m.get("serving", ())),
                        features=tuple(m.get("features", ())), cite=tuple(m.get("cite", ())), notes=m.get("notes", ""))
            if mod.id in self.models:
                raise CatalogError(f"{path}: model {mod.id} twice")
            for v in m.get("variant") or []:
                mod.variants.append(Variant(
                    mod, v["id"], v.get("runtime", ""), v.get("quant", ""), v.get("weights", ""),
                    float(v.get("vram_gib", 0)), v.get("vram_note", ""), float(v.get("ram_gib", 0)),
                    float(v.get("disk_gib", 0) or v.get("vram_gib", 0)), float(v.get("speed", 0)),
                    v.get("speed_ref", ""), v.get("speed_note", ""), tuple(v.get("vendors", ("nvidia",))),
                    tuple(v.get("arch", ())), int(v.get("gpus", 1)), tuple(int(x) for x in v.get("split", ())),
                    v.get("stack", "ready"), bool(v.get("offload", False)), bool(v.get("fast", False)),
                    v.get("workflow", ""), v.get("quality_delta"), float(v.get("weights_gib", 0)),
                    tuple(v.get("match", ())), v.get("notes", ""),
                    tuple(ALIASES.get(c, c) for c in v.get("capabilities", ()))))
            self.models[mod.id] = mod
        self.pending = list(doc.get("pending") or [])
        self.combos = list(doc.get("combo") or [])
        self._speed_range = {}

    # ---- lookups
    def variants(self, cap):
        cap = canon(cap)
        return [v for m in self.models.values() if cap in m.caps for v in m.variants if v.serves(cap)]

    def variant(self, key):
        mid, _, vid = key.partition("/")
        m = self.models.get(mid)
        if not m:
            return None
        return next((v for v in m.variants if v.id == vid), None) if vid else (m.variants[0] if m.variants else None)

    def gpu(self, name):
        """The [gpu] spec a device name means ("NVIDIA GeForce RTX 5090" -> RTX 5090), or None."""
        if not name:
            return None
        n = re.sub(r"\s+", " ", name.replace("NVIDIA", "").replace("GeForce", "").replace("-", " ")).strip().lower()
        n = re.sub(r"\s*shared$", "", n)
        best = None
        for g in self.gpus.values():
            for pat in (g.name.lower(),) + tuple(p.lower() for p in g.match):
                if n == pat or re.search(r"(^|\s)" + re.escape(pat) + r"($|\s)", n):
                    if best is None or len(pat) > best[0]:
                        best = (len(pat), g)
        return best[1] if best else None

    def speed_range(self, cap):
        """(lo, hi) the 0..100 speed score spans: the capability's speed_span, else its unit's."""
        c = self.caps[cap]
        return tuple(c.span) if len(c.span) == 2 else SPEED_SPAN.get(c.unit, (0.5, 500.0))


def canon(cap):
    c = ALIASES.get(cap, cap)
    if c not in CAPABILITIES:
        raise CatalogError(f"unknown capability {cap!r} ({', '.join(CAPABILITIES)})")
    return c


def candidates_paths():
    """Where the catalog may be, in order of trust: $BROMIGOS_LAB_CATALOG, the refreshed and
    verified copy, the package's, the repository's."""
    out = []
    if os.environ.get("BROMIGOS_LAB_CATALOG"):
        out.append(os.environ["BROMIGOS_LAB_CATALOG"])
    out += [os.path.join(CACHE, "models.toml"), os.path.join(SHARE, "homelab", "lab", "models.toml"),
            os.path.normpath(os.path.join(HERE, "..", "..", "share", "lab", "models.toml"))]
    return out


_CACHE = {}


def load(path=None):
    """The catalog: `path`, else $BROMIGOS_LAB_CATALOG, else the newest (by its `version`) of
    the refreshed copy and the packaged one, else the repository's."""
    paths = [path] if path else candidates_paths()
    if not path and os.environ.get("BROMIGOS_LAB_CATALOG"):
        paths = paths[:1]
    found = []
    for p in paths:
        if p and os.path.isfile(p):
            st = os.stat(p)
            key = (p, st.st_mtime_ns, st.st_size)
            if key not in _CACHE:
                with open(p, "rb") as f:
                    _CACHE[key] = Catalog(tomllib.load(f), p)
            found.append(_CACHE[key])
            if path:
                break
    if not found:
        raise CatalogError("no lab model catalog (the bromigos-lab-catalog package installs it; "
                           "bromigos lab models refresh fetches it)")
    # the refreshed copy only wins when it is newer than the packaged one
    return max(found, key=lambda c: (c.version, -found.index(c)))


# ------------------------------------------------------------------ the hardware
@dataclasses.dataclass
class Device:
    id: str                          # gpu0, gpu1, … ("cpu" for the processor)
    name: str                        # RTX 5090, GB10, Apple M4 Max, CPU
    vendor: str = "nvidia"
    vram_gib: float = 0.0            # what models may use (unified memory: the usable share)
    host: str = ""                   # the machine; shown, never written to settings
    desktop: bool = False            # a card the user also uses directly (screen, games)
    unified: bool = False
    arch: str = ""
    bandwidth: float = 0.0
    compute: float = 0.0
    group: str = ""                  # devices with the same group can be split across (one host or linked)
    budget: float = None             # GiB the user gives the lab on it (default: vram less a reserve)
    key: str = ""                    # the settings key: its name, "#2" for a second of the same name
    holds: tuple = ()

    def give(self):
        if self.budget is not None:
            return max(0.0, min(self.budget, self.vram_gib))
        if self.vendor == "cpu":
            return self.vram_gib
        return max(0.0, self.vram_gib - (1.5 if self.desktop else 0.4))


@dataclasses.dataclass
class Hardware:
    devices: list
    ram_gib: dict = dataclasses.field(default_factory=dict)    # host -> GiB
    notes: list = dataclasses.field(default_factory=list)

    def gpus(self):
        return [d for d in self.devices if d.vendor != "cpu"]

    def by_id(self, i):
        return next((d for d in self.devices if d.id == i), None)

    def ram(self, host):
        return self.ram_gib.get(host, self.ram_gib.get("", 32.0))

    def describe(self):
        return ", ".join(f"{d.id} {d.name} {d.vram_gib:.0f} GiB" + (" (unified)" if d.unified else "") +
                         (" desktop" if d.desktop else "") for d in self.gpus()) or "no GPU"

    def apply_budgets(self, budgets):
        """budgets: {gpu id or settings key or name: GiB}."""
        for k, v in (budgets or {}).items():
            for d in self.devices:
                if k in (d.id, d.key, d.name):
                    d.budget = float(v)
                    break

    @classmethod
    def parse(cls, specs, ram_gib=None, cat=None, cpu=True):
        """From words: "RTX 5090", "2x RTX 4090", "RTX 5070,desktop", "GB10x2" (linked),
        "mac-128", "24" (a generic 24 GB NVIDIA card), "amd:24", "H100:80,host=b". ram_gib: the
        RAM of every host (default 64)."""
        cat = cat or load()
        devs, hosts = [], {}
        for n, spec in enumerate(specs):
            parts = [p.strip() for p in spec.split(",") if p.strip()]
            word, opts = parts[0], parts[1:]
            count = 1
            if word not in SETUPS:
                m = re.match(r"^(\d+)\s*x\s+(.+)$", word) or re.match(r"^(\d+)x(\D.*)$", word)
                if m:
                    count, word = int(m.group(1)), m.group(2).strip()
                else:
                    m = re.match(r"^(.*\S)x(\d+)$", word)        # GB10x2, "RTX 5090x2"
                    if m:
                        word, count = m.group(1).strip(), int(m.group(2))
            if word in SETUPS:
                s = SETUPS[word]
                word, count = s[0], s[1] * count
                if len(s) > 2 and s[2]:
                    opts.append(f"mem={s[2]}")
                if len(s) > 3:
                    opts.append(s[3])
            host = next((o.split("=", 1)[1] for o in opts if o.startswith("host=")), f"host{n}")
            mem = next((float(o.split("=", 1)[1]) for o in opts if o.startswith("mem=")), None)
            vendor = None
            if ":" in word and word.split(":", 1)[0].lower() in ("nvidia", "amd", "apple", "intel"):
                vendor, word = word.split(":", 1)
                vendor = vendor.lower()
            size = None
            if ":" in word:
                word, size = word.rsplit(":", 1)
                size = float(size)
            if re.fullmatch(r"\d+(\.\d+)?", word):
                size, word = float(word), f"{word} GB card"
            g = cat.gpu(word)
            for i in range(count):
                vram = size or (mem if mem else (g.vram_gib if g else 0))
                unified = bool(g and g.unified)
                usable = vram
                if unified:
                    usable = vram * (g.usable or 0.75) if g else vram * 0.75
                linked = "linked" in opts and count > 1          # separate hosts on one fabric (2x DGX Spark)
                h = f"{host}-{i}" if linked else host
                d = Device(f"gpu{len(devs)}", g.name if g else word, vendor or (g.vendor if g else "nvidia"),
                           usable, h, "desktop" in opts, unified, g.arch if g else "",
                           g.bandwidth if g else 0, g.compute if g else 0, group=f"link:{host}" if linked else h)
                devs.append(d)
                hosts.setdefault(h, ram_gib if ram_gib is not None else (mem if mem else 64.0))
        hw = cls(devs, dict(hosts))
        if cpu:
            for h, r in hosts.items():
                hw.devices.append(Device(f"cpu{'' if len(hosts) == 1 else '-' + h}", "CPU", "cpu",
                                         max(0.0, r - 8.0), h, bandwidth=80.0, compute=2.0, group="cpu:" + h))
        _keys(hw)
        return hw


def _keys(hw):
    seen = {}
    for d in hw.devices:
        seen[d.name] = seen.get(d.name, 0) + 1
        d.key = d.name if seen[d.name] == 1 else f"{d.name}#{seen[d.name]}"


def _local_gpus():
    """This machine's GPUs: [(name, vendor, vram_gib)] (nvidia-smi, else the amdgpu sysfs)."""
    out = []
    smi = shutil.which("nvidia-smi")
    if smi:
        try:
            p = subprocess.run([smi, "--query-gpu=name,memory.total", "--format=csv,noheader,nounits"],
                               capture_output=True, text=True, timeout=8)
            for line in p.stdout.splitlines():
                name, _, mib = line.rpartition(",")
                if name.strip() and mib.strip().isdigit():
                    out.append((name.strip(), "nvidia", int(mib) / 1024))
        except (OSError, subprocess.SubprocessError):
            pass
    for f in sorted(glob.glob("/sys/class/drm/card*/device/mem_info_vram_total")):
        try:
            with open(f) as fh:
                b = int(fh.read().strip())
            name = "AMD GPU"
            try:
                with open(os.path.join(os.path.dirname(f), "product_name")) as fh:
                    name = fh.read().strip() or name
            except OSError:
                pass
            if b > 2 * 1024 ** 3:
                out.append((name, "amd", b / 1024 ** 3))
        except (OSError, ValueError):
            pass
    return out


def _local_ram():
    try:
        with open("/proc/meminfo") as f:
            for line in f:
                if line.startswith("MemTotal:"):
                    return int(line.split()[1]) / 1024 ** 2
    except OSError:
        pass
    return 32.0


def detect(cat=None, inv=None, local=True):
    """The lab's GPUs (labmodels.gpus: DCGM, the media servers) and, with local, this machine's
    (a desktop card: its budget keeps a reserve for the screen)."""
    cat = cat or load()
    devs, ram = [], {}
    notes = []
    gs = []
    if inv is not None:
        gs = inv.get("gpus") or []
    else:
        try:
            from . import labmodels
            gs = labmodels.gpus()
        except Exception as e:                                # noqa: BLE001 - shown, never raised
            notes.append(f"the lab's GPUs didn't answer ({type(e).__name__}: {e})")
    host_mem = _host_ram()
    for g in gs:
        spec = cat.gpu(g.get("model") or g.get("name"))
        total = (g.get("vram_total") or 0) / 1024 ** 3
        unified = bool(spec and spec.unified)
        if unified:
            total = (spec.vram_gib or total) * (spec.usable or 0.75)
        elif not total and spec:
            total = spec.vram_gib
        host = g.get("host") or "lab"
        d = Device(f"gpu{len(devs)}", spec.name if spec else (g.get("name") or "GPU"),
                   spec.vendor if spec else "nvidia", round(total, 1), host, False, unified,
                   spec.arch if spec else "", spec.bandwidth if spec else 0, spec.compute if spec else 0,
                   group=host, holds=tuple(g.get("holds") or ()))
        devs.append(d)
        ram.setdefault(host, host_mem.get(host) or (spec.vram_gib if unified and spec else 64.0))
    _link_pairs(devs)
    if local:
        for name, vendor, gib in _local_gpus():
            spec = cat.gpu(name)
            devs.append(Device(f"gpu{len(devs)}", spec.name if spec else name, vendor, round(gib, 1), "this machine",
                               True, False, spec.arch if spec else "", spec.bandwidth if spec else 0,
                               spec.compute if spec else 0, group="this machine"))
        ram["this machine"] = round(_local_ram(), 1)
    hw = Hardware(devs, ram, notes)
    for h, r in ram.items():
        hw.devices.append(Device(f"cpu-{len(hw.devices)}" if len(ram) > 1 else "cpu", "CPU", "cpu",
                                 max(0.0, r - 8.0), h, bandwidth=80.0, compute=2.0, group="cpu:" + h))
    _keys(hw)
    return hw


def _host_ram():
    """{host: GiB} from node-exporter through the metrics capability, when there is one."""
    try:
        from . import caps
        if not caps.available("metrics"):
            return {}
        r = caps.metrics("node_memory_MemTotal_bytes", timeout=6)
        out = {}
        for x in r["items"]:
            lb = x["labels"]
            h = lb.get("nodename") or lb.get("node") or lb.get("instance", "").split(":")[0]
            if h:
                out[h] = float(x["value"]) / 1024 ** 3
        return out
    except Exception:                                         # noqa: BLE001
        return {}


def _link_pairs(devs):
    """A server split over hosts (a vLLM head and its worker on two GB10s) links them: they can
    be split across again."""
    by_server = {}
    for d in devs:
        for h in d.holds:
            base = re.sub(r"-(head|worker)(-\d+)?$", "", h.split(" ")[0])
            if base != h.split(" ")[0]:
                by_server.setdefault(base, []).append(d)
    for base, ds in by_server.items():
        if len({d.host for d in ds}) > 1:
            g = "link:" + base
            for d in ds:
                d.group = g


# ------------------------------------------------------------------ options and scores
@dataclasses.dataclass
class Option:
    cap: str
    variant: Variant
    devices: tuple                   # Device ids
    per_gpu: float                   # GiB on each
    ram: float
    host: str
    quality: float
    speed: float                     # estimated on these devices, the capability's unit
    speed_score: float               # 0..100
    notes: tuple = ()
    serving: dict = None             # LLMs: what it serves at the plan's load (catalog_serving.serve)
    agg_score: float = 0.0           # 0..100 of the aggregate tok/s, for the throughput goal
    slow: bool = False               # under its capability's usable floor

    @property
    def key(self):
        return self.variant.key


def _ref(cat, name):
    if not name:
        return None
    if name == "cpu":
        return GpuSpec("cpu", "cpu", 0, "", 80.0, 2.0)
    return cat.gpus.get(name) or cat.gpu(name)


def estimate_speed(cat, cap, v, devs):
    """The variant's speed on these devices, scaled from its reference card by memory bandwidth
    (LLM decoding) or compute (diffusion), less a tensor-parallel loss."""
    c = cat.caps[cap]
    if v.speed <= 0:
        return 0.0, "no figure"
    if v.offload:
        return v.speed, "as measured with part in system RAM (not scaled by card)"
    ref = _ref(cat, v.speed_ref)
    if not ref or c.scale == "none":
        return v.speed, f"measured on {v.speed_ref or 'its reference'}"
    attr = "bandwidth" if c.scale == "bandwidth" else "compute"
    base = getattr(ref, attr) or 0
    have = [getattr(d, attr) for d in devs]
    if not base or not all(have):
        return v.speed, f"on {v.speed_ref}"
    n = len(devs)
    split_gain = {1: 1.0, 2: 0.8, 3: 0.7, 4: 0.65, 8: 0.55}.get(n, 0.5)
    if v.runtime in ("llama.cpp", "ollama") and n > 1:
        f = min(have) / base * 0.9                           # a layer split: one card works at a time
    else:
        f = sum(have) / base * split_gain if n > 1 else have[0] / base
    if v.speed_ref == "cpu" or (devs and devs[0].vendor == "cpu"):
        f = (have[0] / base) if base else 1.0
    est = v.speed * f if c.better == "higher" else v.speed / max(f, 1e-6)
    return est, ("measured" if abs(f - 1) < 0.05 else f"est. from {v.speed_ref}")


def speed_score(cat, cap, speed):
    if speed <= 0:
        return 0.0
    lo, hi = cat.speed_range(cap)
    if hi <= lo:
        return 50.0
    s = (math.log(speed) - math.log(lo)) / (math.log(hi) - math.log(lo))
    if cat.caps[cap].better == "lower":
        s = 1 - s
    return max(0.0, min(100.0, 100 * s))


def utility(o, goal):
    wq, ws = GOAL_WEIGHTS.get(goal, GOAL_WEIGHTS["balanced"])
    pen = FLOOR_PENALTY if o.slow else 0.0
    if goal == "throughput":
        return wq * o.quality + ws * (o.agg_score if o.serving else o.speed_score) - pen
    return wq * o.quality + ws * o.speed_score - pen


def _fits_vendor(v, d):
    if d.vendor == "cpu":
        return "cpu" in v.vendors
    if d.vendor not in v.vendors:
        return False
    if v.arch and d.arch and d.arch not in v.arch:
        return False
    if v.arch and not d.arch:
        return False
    return True


def options(cat, cap, hw, licence="any", region=None, unsupported=False, why=None, load=None):
    """Every way to run `cap` on this hardware (a variant on one device, or split across
    devices it may be split across), within each device's budget alone. load: for LLMs, the
    clients and context they must serve (catalog_serving.Load; one client at 32k by default)."""
    from . import catalog_serving as sv
    cap = canon(cap)
    load = load or sv.Load()
    measured = _measured()
    out = []
    groups = {}
    for d in hw.devices:
        groups.setdefault(d.group, []).append(d)
    for v in cat.variants(cap):
        if not v.ready and not unsupported:
            if why is not None:
                why.setdefault("needs support", []).append(f"{v.key}: {v.stack}")
            continue
        ok, w = v.model.licence.allows(licence, region)
        if not ok:
            if why is not None:
                why.setdefault("licence", []).append(f"{v.key}: {w}")
            continue
        q = v.quality(cap)
        for gname, ds in groups.items():
            usable = [d for d in ds if _fits_vendor(v, d)]
            if not usable:
                continue
            for n in v.splits():
                if n < v.gpus or n > len(usable):
                    continue
                if n > 1 and usable[0].vendor == "cpu":
                    continue
                # the n devices with the most room
                pick_ds = sorted(usable, key=lambda d: -d.give())[:n]
                served = None
                if cap in SERVED and v.model.params_b and not v.offload and \
                        v.runtime in ("vllm", "sglang", "llama.cpp", "ollama", "mlx"):
                    served = sv.serve(v.model, v, pick_ds, load, _ref(cat, v.speed_ref),
                                      0.9 if pick_ds[0].group.startswith("link:") else None)
                    per = served["vram_gib"] / n
                else:
                    per = v.vram_gib / n + (0.6 if n > 1 else 0.0)
                if min(d.give() for d in pick_ds) < per:
                    if why is not None and n == max(v.gpus, 1):
                        why.setdefault("too big", []).append(
                            f"{v.key}: {per:.1f} GiB a GPU, {max(d.give() for d in pick_ds):.1f} given")
                    continue
                host = pick_ds[0].host
                if v.ram_gib > hw.ram(host):
                    continue
                if n > 1 and len({d.name for d in pick_ds}) > 1 and v.runtime in ("vllm", "sglang"):
                    continue                                  # tensor parallel wants matching cards
                if n > 1 and (cap not in SERVED or v.runtime not in ("vllm", "sglang", "llama.cpp", "ollama")) and \
                        len({d.host for d in pick_ds}) > 1:
                    continue                                  # only the LLM servers split across hosts
                sp, note = estimate_speed(cat, cap, v, pick_ds)
                if served:
                    sp, note = served["per_stream"], served["note"]
                m = (measured.get(v.key) or {}).get(pick_ds[0].name) if n == 1 else None
                if m:
                    per, sp, note = _apply_measured(cat, cap, m, per, sp)
                floor = cat.caps[cap].floor
                slow = bool(floor and sp and (sp < floor if cat.caps[cap].better == "higher" else sp > floor))
                out.append(Option(cap, v, tuple(d.id for d in pick_ds), round(per, 2), v.ram_gib, host, q, sp,
                                  speed_score(cat, cap, sp), (note,), served,
                                  sv.log_score(served["aggregate"]) if served else 0.0, slow))
    return out


def _measured():
    """The catalog bench's results on this lab ({key: {gpu name: row}}), or {}."""
    try:
        from . import catalog_bench
        return catalog_bench.results()
    except Exception:                                         # noqa: BLE001
        return {}


def _apply_measured(cat, cap, m, per, sp):
    """A bench row over the published figures: (per-GPU GiB, speed, note)."""
    unit = cat.caps[cap].unit
    if m.get("peak_vram_gib"):
        per = max(per * 0.5, float(m["peak_vram_gib"]))      # a peak over what was resident: never below half
    if m.get("seconds") and unit in ("s/image", "s/mesh", "s/page"):
        sp = float(m["seconds"])
    elif m.get("seconds") and unit == "min/clip":
        sp = float(m["seconds"]) / 60
    elif m.get("realtime_x") and unit == "x realtime":
        sp = float(m["realtime_x"])
    elif m.get("concurrency") and unit == "tok/s":
        sp = float(m["concurrency"][0].get("per_stream_tok_s") or sp)
    return per, sp, f"measured on your lab {m.get('t', '')[:10]}"


def fmt_speed(cat, cap, s):
    if s <= 0:
        return "speed unknown"
    u = cat.caps[cap].unit
    if s >= 10:
        t = f"{s:.0f}"
    elif s >= 1:
        t = f"{s:.1f}"
    else:
        t = f"{s:.2f}"
    return f"~{t} {u}".strip()


# ------------------------------------------------------------------ pick: one capability, one card
def pick(capability, vram_gib=None, ram_gib=64.0, vendor="nvidia", licence="any", goal="quality", region=None,
         arch=None, gpus=1, unified=False, gpu=None, cat=None, unsupported=False, alternatives=4, serving=None):
    """The best fit for one capability on one card (or `gpus` linked ones), with alternatives
    and the reason, in plain words:

        {"capability", "goal", "hardware", "best": {model, variant, name, quant, runtime,
         vram_gib, ram_gib, quality, speed, speed_text, licence, licence_plain, workflow,
         offload, why}, "alternatives": [...], "bigger": [...] (what the next size up gets),
         "skipped": {"licence": [...], "needs support": [...], "too big": [...]}, "reason"}

    vram_gib None or 0 means the CPU only. gpu: a card's name ("RTX 4070") instead of
    vram/vendor/arch."""
    cat = cat or load()
    cap = canon(capability)
    if gpu:
        hw = Hardware.parse([f"{gpus}x {gpu}" if gpus > 1 else gpu], ram_gib=ram_gib, cat=cat)
    elif vram_gib:
        spec = f"{vendor}:{float(vram_gib)}" if vendor in ("amd", "apple", "intel") else f"{float(vram_gib)}"
        hw = Hardware.parse([f"{gpus}x {spec}" if gpus > 1 else spec], ram_gib=ram_gib, cat=cat)
        for d in hw.gpus():
            d.vendor = vendor
            d.arch = arch or ("apple" if vendor == "apple" else "")
            d.unified = unified or vendor == "apple"
            ref = _generic_ref(cat, vendor, vram_gib)
            if ref:
                d.bandwidth, d.compute = ref.bandwidth, ref.compute
                if not arch and vendor != "apple":
                    d.arch = ref.arch
    else:
        hw = Hardware([], {"": ram_gib})
        hw.devices.append(Device("cpu", "CPU", "cpu", max(0.0, ram_gib - 8), "", bandwidth=80, compute=2,
                                 group="cpu"))
    skipped = {}
    opts = options(cat, cap, hw, licence, region, unsupported, skipped, serving)
    ranked = sorted(opts, key=lambda o: (-utility(o, goal), -o.quality, o.per_gpu))
    seen, uniq = set(), []
    for o in ranked:
        if o.key not in seen:
            seen.add(o.key)
            uniq.append(o)
    doc = {"capability": cap, "goal": goal, "licence": licence, "hardware": hw.describe(),
           "best": None, "alternatives": [], "bigger": [], "skipped": skipped}
    if uniq:
        doc["best"] = _odoc(cat, uniq[0], hw)
        doc["alternatives"] = [_odoc(cat, o, hw) for o in uniq[1:1 + alternatives]]
    # what more memory would buy
    if vram_gib or gpu:
        have = max((d.give() for d in hw.gpus()), default=0)
        better = []
        for v in cat.variants(cap):
            if not v.ready or not v.model.licence.allows(licence, region)[0]:
                continue
            if v.vram_gib / max(v.gpus, 1) > have and v.quality(cap) > (uniq[0].quality if uniq else 0) + 2:
                better.append((v.vram_gib, v))
        for need, v in sorted(better, key=lambda x: (x[0], -x[1].quality(cap)))[:2]:
            doc["bigger"].append({"model": v.model.id, "variant": v.id, "name": v.model.name, "quant": v.quant,
                                  "vram_gib": v.vram_gib, "quality": v.quality(cap)})
    doc["reason"] = _reason(cat, cap, doc, goal)
    return doc


def _generic_ref(cat, vendor, vram):
    """A typical card of that vendor and size, for speed estimates."""
    pool = [g for g in cat.gpus.values() if g.vendor == vendor and not g.unified and g.bandwidth]
    if vendor == "apple":
        pool = [g for g in cat.gpus.values() if g.vendor == "apple"]
    if not pool:
        return None
    return min(pool, key=lambda g: (abs(g.vram_gib - float(vram)), -g.bandwidth))


def _odoc(cat, o, hw=None):
    v = o.variant
    devs = [hw.by_id(i) for i in o.devices] if hw else []
    on_cpu = bool(devs) and devs[0].vendor == "cpu"
    return {"on_cpu": on_cpu, "mem_gib": o.per_gpu, "model": v.model.id, "variant": v.id, "key": v.key, "name": v.model.name, "quant": v.quant,
            "runtime": v.runtime, "workflow": v.workflow, "weights": v.weights, "repo": v.model.repo,
            "vram_gib": 0.0 if on_cpu else round(o.per_gpu * len(o.devices), 1),
            "per_gpu_gib": 0.0 if on_cpu else o.per_gpu, "ram_gib": round(o.per_gpu, 1) if on_cpu else v.ram_gib,
            "devices": list(o.devices), "device_names": [d.name for d in devs if d],
            "quality": o.quality, "speed": round(o.speed, 2), "speed_text": fmt_speed(cat, o.cap, o.speed),
            "speed_score": round(o.speed_score, 1), "licence": v.model.licence.name,
            "licence_plain": v.model.licence.plain(), "licence_conditions": v.model.licence.conditions,
            "offload": v.offload, "fast": v.fast, "stack": v.stack, "vram_note": v.vram_note,
            "notes": v.notes or v.model.notes, "released": v.model.released,
            "serving": o.serving, "published": [dict(x) for x in v.model.serving][:3]}


def _reason(cat, cap, doc, goal):
    b = doc["best"]
    if not b:
        sk = doc["skipped"]
        if sk.get("too big"):
            return f"nothing in the catalog fits: the smallest {cap} option needs more than this has"
        return f"nothing in the catalog runs {cap} here" + (" within the licence filter" if sk.get("licence") else "")
    s = (f"{b['name']} {b['quant']} ({b['vram_gib']:.1f} GiB peak, {b['speed_text']}) is the "
         f"{'strongest' if goal == 'quality' else 'best ' + goal + ' trade-off'} that fits")
    if b["offload"]:
        s += ", with part of it in system RAM (slower than fully on the GPU)"
    if doc["bigger"]:
        g = doc["bigger"][0]
        s += f"; {g['name']} {g['quant']} scores higher but needs {g['vram_gib']:.0f} GiB"
    return s + "."


# ------------------------------------------------------------------ plan: everything, every GPU
STRATEGIES = {
    "balanced": ("Balanced", {}, False, "each capability by how much it counts"),
    "brain": ("Brain first", {"llm": 6.0, "code": 3.0, "vision": 2.0}, False, "the strongest LLM the GPUs allow"),
    "media": ("Media first", {"image": 6.0, "image-edit": 4.0, "video": 6.0, "3d": 4.0, "upscale": 2.0}, False,
              "the strongest image, video and 3D models"),
    "voice": ("Voice first", {"tts": 6.0, "stt": 5.0}, False, "the best voice and hearing"),
    "resident": ("Everything resident", {}, True, "nothing swaps: every model stays loaded"),
}
DEFAULT_WANTS = ("llm", "tts", "stt", "embed", "image", "image-edit", "cutout", "video", "3d")
MISSING_RESIDENT = 100.0   # an always-on capability left out (in quality points, before its weight)
MISSING_DEMAND = 60.0
BEAM = 160
PER_CAP = 14


def _headroom(d):
    return 0.0 if d.vendor == "cpu" else max(0.6, 0.04 * d.give())


@dataclasses.dataclass
class _State:
    score: float
    place: dict                      # cap -> Option or ("share", cap) or None
    used: dict                       # device id -> GiB resident
    ram: dict                        # host -> GiB

    def clone(self):
        return _State(self.score, dict(self.place), dict(self.used), dict(self.ram))


_CAT_WEIGHT = {}


def _cap_weight(strategy, cap, priority_weights):
    return STRATEGIES[strategy][1].get(cap, 1.0) * priority_weights.get(cap, _CAT_WEIGHT.get(cap, WEIGHT.get(cap, 1.0)))


def _pref(o, hw, cap, resident):
    """Small preferences in plain terms: the LLM on the bigger card, residents off a card the
    user games on, the lab before the desktop, voice and hearing together."""
    devs = [hw.by_id(i) for i in o.devices]
    p = 0.0
    if any(d.desktop for d in devs):
        p -= 4.0 if resident else 1.0
    if cap in ("llm", "code"):
        p += 0.02 * sum(d.give() for d in devs)
    if devs and devs[0].vendor == "cpu" and cap not in ("tts", "stt", "embed", "ocr", "cutout"):
        p -= 3.0
    rt = {"comfyui": "comfyui", "voice": "voice", "vllm": "vllm", "sglang": "sglang", "llama.cpp": "llama",
          "ollama": "ollama"}.get(o.variant.runtime)
    if rt and devs and all(any(rt in h for h in d.holds) for d in devs):
        p += 1.5                                              # its runtime already runs there
    return p


def plan(hw, wants=None, always=None, goals=None, priority="balanced", licence="any", region=None, cat=None,
         unsupported=False, budgets=None, max_configs=4, strategies=None, serving=None):
    """Two to four ranked configurations of the whole lab: which model on which GPU, what stays
    resident and what swaps, peak VRAM per GPU against its budget, speed, and what each gives up.

    hw: Hardware (detect() or Hardware.parse). wants: capabilities (default DEFAULT_WANTS).
    always: those kept resident (default: each capability's own residency). goals: {cap or "*":
    quality|balanced|speed}. priority: balanced|brain|media|voice|resident (shown first).
    budgets: {gpu id, settings key or name: GiB}. serving: the LLM's clients, context, prompt
    and output (catalog_serving.Load): its KV cache is sized for it, and its speed is per stream
    at that concurrency."""
    from . import catalog_serving as sv
    serving_load = serving or sv.Load()
    cat = cat or load()
    hw.apply_budgets(budgets)
    _CAT_WEIGHT.clear()
    _CAT_WEIGHT.update({c: cat.caps[c].weight for c in CAPABILITIES})
    wants = [canon(c) for c in (wants or DEFAULT_WANTS)]
    always = {canon(c) for c in (always if always is not None else [c for c in wants
                                                                     if cat.caps[c].residency == "always"])}
    goals = dict(goals or {})
    g_all = goals.get("*", "balanced")
    goal = {c: goals.get(c, g_all) for c in wants}
    opts = {c: options(cat, c, hw, licence, region, unsupported, load=serving_load) for c in wants}
    order = [priority] + [s for s in (strategies or ("balanced", "brain", "media", "resident", "voice"))
                          if s != priority]
    configs = []
    for s in order:
        if s not in STRATEGIES:
            continue
        cfg = _solve(cat, hw, wants, always, goal, opts, s)
        if cfg is None:
            continue
        sig = tuple(sorted((c, p["key"], tuple(p["devices"]), p["resident"]) for c, p in cfg["_place"].items()))
        if any(sig == x["_sig"] for x in configs):
            continue
        cfg["_sig"] = sig
        configs.append(cfg)
        if len(configs) >= max_configs:
            break
    _sacrifices(configs, wants)
    for c in configs:
        c.pop("_sig", None)
        c.pop("_place", None)
    return {"hardware": [_ddoc(d) for d in hw.devices], "wants": wants, "always": sorted(always),
            "goals": goal, "priority": priority, "licence": licence, "region": region,
            "load": dataclasses.asdict(serving_load),
            "catalog": {"researched": cat.researched, "refreshed": cat.refreshed, "path": cat.path},
            "configurations": configs, "notes": hw.notes}


def _ddoc(d):
    return {"id": d.id, "key": d.key, "name": d.name, "vendor": d.vendor, "vram_gib": d.vram_gib,
            "budget_gib": round(d.give(), 1), "host": d.host, "desktop": d.desktop, "unified": d.unified}


def _fits(st, o, hw, extra_ram=True):
    for i in o.devices:
        d = hw.by_id(i)
        if st.used.get(i, 0.0) + o.per_gpu + _headroom(d) > d.give() + 1e-6:
            return False
    if extra_ram and o.ram and st.ram.get(o.host, 0.0) + o.ram > hw.ram(o.host) - 6:
        return False
    return True


def _solve(cat, hw, wants, always, goal, opts, strategy):
    _, weights, all_resident, _ = STRATEGIES[strategy]
    resident = [c for c in wants if c in always or all_resident]
    demand = [c for c in wants if c not in resident]

    def u(o, cap, res):
        return _cap_weight(strategy, cap, {}) * utility(o, goal[cap]) + _pref(o, hw, cap, res)

    # the resident ones: a beam search over each capability's best options
    resident.sort(key=lambda c: -max((o.per_gpu for o in opts[c]), default=0))
    beam = [_State(0.0, {}, {}, {})]
    for cap in resident:
        cand = sorted(opts[cap], key=lambda o: -u(o, cap, True))
        cand = _diverse(cand, PER_CAP)
        nxt = []
        for st in beam:
            shared = _shared(st, cap)
            if shared:
                s2 = st.clone()
                s2.place[cap] = ("share", shared)
                s2.score += _cap_weight(strategy, cap, {}) * utility(_as(_opt_of(st, shared), cap), goal[cap]) * 0.98
                nxt.append(s2)
            for o in cand:
                if not _fits(st, o, hw):
                    continue
                s2 = st.clone()
                s2.place[cap] = o
                for i in o.devices:
                    s2.used[i] = s2.used.get(i, 0.0) + o.per_gpu
                if o.ram:
                    s2.ram[o.host] = s2.ram.get(o.host, 0.0) + o.ram
                s2.score += u(o, cap, True) + _together(s2, cap, o)
                nxt.append(s2)
            s2 = st.clone()
            s2.place[cap] = None
            s2.score -= MISSING_RESIDENT * _cap_weight(strategy, cap, {})
            nxt.append(s2)
        nxt.sort(key=lambda s: -s.score)
        beam = nxt[:BEAM]
    # the on-demand ones: each takes the best that fits beside the residents (they swap
    # with each other, one job at a time)
    best = None
    for st in beam:
        s2 = st.clone()
        for cap in demand:
            shared = _shared(s2, cap)
            choice, cu = None, -1e9
            chosen = {p.variant.key: p.devices for p in s2.place.values() if isinstance(p, Option)}
            for o in opts[cap]:
                if not _fits(s2, o, hw, extra_ram=False):
                    continue
                v = u(o, cap, False) - 0.002 * _cold_s(o)
                if chosen.get(o.variant.key) == o.devices:
                    v += 4.0                               # already there for another job: no second model
                if v > cu:
                    choice, cu = o, v
            if shared:
                base = _opt_of(s2, shared)
                su = _cap_weight(strategy, cap, {}) * utility(_as(base, cap), goal[cap])
                same = choice is not None and choice.variant is base.variant and choice.devices == base.devices
                if choice is None or same or su >= cu - 1.0:
                    s2.place[cap] = ("share", shared)
                    s2.score += su
                    continue
            if choice is None:
                s2.place[cap] = None
                s2.score -= MISSING_DEMAND * _cap_weight(strategy, cap, {})
            else:
                s2.place[cap] = choice
                s2.score += cu
        if best is None or s2.score > best.score:
            best = s2
    if best is None:
        return None
    return _cfg_doc(cat, hw, strategy, best, resident, wants, goal)


def _together(st, cap, o):
    """The voice service holds TTS and STT in one process: on one device, or it's two services."""
    other = {"tts": "stt", "stt": "tts"}.get(cap)
    p = st.place.get(other) if other else None
    if isinstance(p, Option) and p.devices != o.devices:
        return -3.0
    return 0.0


def _as(o, cap):
    """An option seen from another capability it serves (its quality there)."""
    return dataclasses.replace(o, cap=cap, quality=o.variant.quality(cap))


def _opt_of(st, cap):
    p = st.place.get(cap)
    while isinstance(p, tuple):
        p = st.place.get(p[1])
    return p


def _shared(st, cap):
    """A capability an already-placed model also serves (a multimodal LLM reads the screen;
    Qwen-Image edits as well as draws)."""
    for c, p in st.place.items():
        if isinstance(p, Option) and p.variant.serves(cap):
            return c
    return None


def _diverse(cand, n):
    """The best n, but at most three per model, so smaller variants stay in reach."""
    out, per = [], {}
    for o in cand:
        k = o.variant.model.id
        if per.get(k, 0) >= 3:
            continue
        per[k] = per.get(k, 0) + 1
        out.append(o)
        if len(out) >= n:
            break
    return out


def _cold_s(o):
    return round(o.variant.disk_gib / DISK_GIB_S + 3, 0)


def _cfg_doc(cat, hw, strategy, st, resident, wants, goal):
    title, _, _, blurb = STRATEGIES[strategy]
    place, out, missing = {}, [], []
    for cap in wants:
        p = st.place.get(cap)
        if p is None:
            best = max((o for o in options(cat, cap, hw, "any", None, False)), key=lambda o: o.per_gpu, default=None)
            missing.append({"capability": cap, "why": "nothing that fits is left beside the resident models"
                            if best else "nothing in the catalog runs it on this hardware"})
            continue
        if isinstance(p, tuple):
            base = _as(_opt_of(st, p[1]), cap)
            d = _odoc(cat, base, hw)
            d.update({"capability": cap, "resident": cap in resident or p[1] in resident, "shared_with": p[1],
                      "vram_gib": 0.0, "cold_start_s": 0,
                      "why": f"{base.variant.model.name} already serves it ({p[1]}): no extra VRAM"})
            out.append(d)
            place[cap] = d
            continue
        d = _odoc(cat, p, hw)
        res = cap in resident
        d.update({"capability": cap, "resident": res, "shared_with": None,
                  "cold_start_s": 0 if res else _cold_s(p), "goal": goal[cap],
                  "why": _why(cat, hw, cap, p, res, goal[cap])})
        out.append(d)
        place[cap] = d
    devs = []
    for dv in hw.devices:
        res = sum(d["mem_gib"] for d in out if dv.id in d["devices"] and d["resident"] and not d["shared_with"])
        dem = [d for d in out if dv.id in d["devices"] and not d["resident"] and not d["shared_with"]]
        peak_dem = max((d["mem_gib"] for d in dem), default=0.0)
        if dv.vendor == "cpu" and not res and not dem:
            continue
        devs.append(dict(_ddoc(dv), resident_gib=round(res, 1), on_demand_peak_gib=round(peak_dem, 1),
                         peak_gib=round(res + peak_dem, 1), headroom_gib=round(dv.give() - res - peak_dem, 1),
                         resident=[f"{d['capability']}: {d['name']} {d['quant']}" for d in out
                                   if dv.id in d["devices"] and d["resident"] and not d["shared_with"]],
                         swaps=[f"{d['capability']}: {d['name']} {d['quant']}" for d in dem]))
    q = [d["quality"] for d in out]
    return {"id": strategy, "name": title, "aim": blurb, "score": round(st.score, 1),
            "quality_avg": round(sum(q) / len(q), 1) if q else 0.0, "placements": out, "devices": devs,
            "missing": missing, "_place": place}


def _why(cat, hw, cap, o, resident, goal):
    devs = [hw.by_id(i) for i in o.devices]
    where = " + ".join(f"{d.name}" for d in devs)
    v = o.variant
    bits = [f"{v.model.name} {v.quant} on {where}"]
    if len(devs) > 1:
        bits.append(f"split across {len(devs)} GPUs ({o.per_gpu:.1f} GiB each)")
    if resident:
        bits.append("stays loaded")
    else:
        bits.append(f"loads when a job needs it (~{_cold_s(o):.0f} s cold), unloaded when idle")
    if v.offload:
        bits.append("part in system RAM")
    if goal == "speed" and v.fast:
        bits.append("a fast distilled variant")
    if devs and devs[0].desktop:
        bits.append("on your desktop card, inside its budget")
    if o.serving:
        from . import catalog_serving as sv
        bits.append(sv.describe(o.serving, "serves") + f" (KV cache {o.serving['kv_gib']:.1f} GiB)")
    return "; ".join(bits)


def _sacrifices(configs, wants):
    """One line per configuration: what it gives up against the others."""
    for c in configs:
        mine = {p["capability"]: p for p in c["placements"]}
        lost = []
        for cap in wants:
            others = [x for o in configs if o is not c for x in o["placements"] if x["capability"] == cap]
            if cap not in mine:
                if others:
                    lost.append(f"no {cap}")
                continue
            if not others:
                continue
            top = max(others, key=lambda x: x["quality"])
            m = mine[cap]
            if top["quality"] - m["quality"] >= 3 and top["key"] != m["key"]:
                a, b = f"{m['name']} {m['quant']}", f"{top['name']} {top['quant']}"
                if a == b:
                    a, b = f"{m['name']} {m['variant']}", f"{top['name']} {top['variant']}"
                lost.append(f"a smaller {cap} model ({a} vs {b})")
            elif m["speed"] and top["speed"] and top["key"] != m["key"]:
                pass
        swaps = sum(1 for p in c["placements"] if not p["resident"] and not p.get("shared_with"))
        if swaps and any(all(p["resident"] or p.get("shared_with") for p in o["placements"])
                         for o in configs if o is not c):
            lost.append(f"{swaps} model{'s' if swaps != 1 else ''} load on demand (cold starts)")
        c["sacrifice"] = ("gives up " + "; ".join(lost[:3])) if lost else "gives up nothing the others keep"


# ------------------------------------------------------------------ recommend: this lab
def installed(cat, inv):
    """[{key, cap, where, name}]: catalog variants this lab has, matched by their globs against
    ComfyUI's model files, served model names and the voice service's models."""
    names = []
    for s in inv.get("servers") or []:
        for m in s.get("models") or []:
            n = m.get("name") or ""
            if n.startswith("("):
                continue
            names.append((f"{m.get('folder')}/{n}" if m.get("folder") else n, s.get("source"), s.get("kind")))
    for n in inv.get("served") or []:
        names.append((n["name"], n.get("where"), "served"))
    for g in inv.get("gpus") or []:
        for h in g.get("holds") or []:
            dep = h.split("/")[-1].split(" ")[0]
            if dep in cat.models:
                names.append((cat.models[dep].variants[0].match[0] if cat.models[dep].variants[0].match
                              else dep, dep, "deployment"))
    out = []
    for m in cat.models.values():
        for v in m.variants:
            pats = v.match or ((m.id,) if any(n == m.id for n, _, k in names if k == "deployment") else ())
            for name, where, kind in names:
                base = name.rsplit("/", 1)[-1]
                if any(fnmatch.fnmatch(name.lower(), p.lower()) or fnmatch.fnmatch(base.lower(), p.lower())
                       for p in pats):
                    out.append({"key": v.key, "name": m.name, "quant": v.quant, "where": where, "file": name,
                                "caps": list(v.caps or m.caps)})
                    break
    return out


def served_models():
    """What the lab's model servers serve, and where: [{name, where}]. vLLM's Prometheus
    metrics (model_name, pod) when they are scraped, else the vLLM Deployments the kubernetes
    source can read (their --model / --served-model-name / MODEL; replicas above zero)."""
    out = []
    try:
        from . import caps
        if caps.available("metrics"):
            r = caps.metrics("max by (model_name, pod, exported_pod) (vllm:num_requests_running)", timeout=6)
            for x in r["items"]:
                lb = x["labels"]
                if lb.get("model_name"):
                    out.append({"name": lb["model_name"], "where": lb.get("exported_pod") or lb.get("pod") or "vllm"})
    except Exception:                                         # noqa: BLE001
        pass
    if out:
        return out
    try:
        from . import registry
        k = next((a for a in registry.instances() if a.type == "kubernetes"), None)
        if k is None:
            return out
        doc = json.loads(k.kubectl(["get", "deploy", "-A", "-o", "json"], 25))
    except Exception:                                         # noqa: BLE001
        return out
    for d in doc.get("items") or []:
        if not (d.get("spec") or {}).get("replicas"):
            continue
        for c in ((d.get("spec") or {}).get("template") or {}).get("spec", {}).get("containers") or []:
            if "vllm" not in (c.get("image") or "") and "sglang" not in (c.get("image") or ""):
                continue
            args = list(c.get("command") or []) + list(c.get("args") or [])
            env = {e.get("name"): e.get("value") for e in c.get("env") or [] if e.get("value")}
            names = []
            for flag in ("--model", "--served-model-name"):
                if flag in args and args.index(flag) + 1 < len(args):
                    names.append(args[args.index(flag) + 1])
            names += [env[n] for n in ("MODEL", "SERVED_MODEL_NAME") if env.get(n)]
            for n in dict.fromkeys(names):
                out.append({"name": n, "where": d["metadata"]["name"]})
    return out


def _units(hw):
    """What recommend looks at: each GPU, and each group of linked GPUs (a TP pair across hosts)."""
    units = [[d] for d in hw.devices if d.vendor != "cpu"]
    groups = {}
    for d in hw.devices:
        if d.vendor != "cpu" and d.group.startswith("link:"):
            groups.setdefault(d.group, []).append(d)
    units += [ds for ds in groups.values() if len(ds) > 1]
    return units


def recommend(cat=None, hw=None, inv=None, goal="balanced", licence="any", region=None, wants=None, every=False,
              serving=None):
    """For each GPU (and each linked group): what's installed (matched to the catalog), the best
    pick for it per capability, upgrades that would fit, and installed models whose licence
    doesn't cover the filter or region. The quick version of plan()."""
    cat = cat or load()
    if inv is None:
        from . import labmodels
        inv = labmodels.inventory()
        inv["served"] = served_models()
    hw = hw or detect(cat, inv)
    have = installed(cat, inv)
    wants = [canon(c) for c in (wants or [c for c in CAPABILITIES if c != "code"])]
    devices, upgrades, warnings = [], [], []
    running = set()
    for unit in _units(hw):
        ids = tuple(d.id for d in unit)
        here = [h for h in have if any(_held_on(h, d) for d in unit)]
        if len(unit) > 1:
            here = [h for h in here if all(any(_held_on(h, d) for d in unit) for _ in (0,))]
        rows = []
        sub = Hardware(list(unit) + [x for x in hw.devices if x.vendor == "cpu" and x.host == unit[0].host],
                       hw.ram_gib)
        linked_single = len(unit) == 1 and unit[0].group.startswith("link:")
        for cap in wants:
            if len(unit) > 1 and cap not in SERVED:
                continue
            if linked_single and cap in SERVED:
                continue                                    # the linked group's row says it
            cur = [h for h in here if cap in h["caps"]]
            if not cur and not every and len(unit) == 1:
                continue
            cur_v = [(cat.variant(h["key"]), h) for h in cur]
            cur_v = [(v, h) for v, h in cur_v if v]
            top = max(cur_v, key=lambda x: x[0].quality(cap), default=(None, None))
            # what already runs costs nothing more to keep: a small bonus, so a near-tie doesn't churn
            os_ = sorted((o for o in options(cat, cap, sub, licence, region, load=serving) if o.devices == ids),
                         key=lambda o: -(utility(o, goal) + (3.0 if o.variant is top[0] else 0.0)))
            if not os_:
                continue
            best = os_[0]
            cur_q = top[0].quality(cap) if top[0] else None
            if cur:
                running.add(cap)
            row = {"capability": cap, "installed": [f"{h['name']} {h['quant']}" for h in cur],
                   "current": f"{top[1]['name']} {top[1]['quant']}" if top[1] else None,
                   "installed_quality": cur_q, "pick": _odoc(cat, best, hw)}
            if top[0] is not None and best.quality - cur_q >= 3 and best.variant is not top[0]:
                row["upgrade"] = True
                upgrades.append({"device": " + ".join(d.key for d in unit), "capability": cap, "from": row["current"],
                                 "to": f"{best.variant.model.name} {best.variant.quant}",
                                 "gain": round(best.quality - cur_q, 1), "vram_gib": round(best.per_gpu * len(unit), 1),
                                 "licence": best.variant.model.licence.name,
                                 "licence_plain": best.variant.model.licence.plain()})
            rows.append(row)
        for v, h in [(cat.variant(h["key"]), h) for h in here]:
            if not v:
                continue
            ok, why = v.model.licence.allows(licence, region)
            if not ok:
                w = {"device": " + ".join(d.key for d in unit), "model": f"{h['name']} {h['quant']}", "why": why}
                if w not in warnings:
                    warnings.append(w)
        if rows or (len(unit) == 1 and not unit[0].group.startswith("link:")):
            d0 = unit[0]
            devices.append(dict(_ddoc(d0), id="+".join(ids), name=" + ".join(d.name for d in unit),
                                vram_gib=round(sum(d.vram_gib for d in unit), 1), linked=len(unit) > 1,
                                holds=sorted({h for d in unit for h in d.holds}),
                                installed=[f"{h['name']} {h['quant']}" for h in here], picks=rows))
    # what nothing in the lab runs yet: the best fit on the biggest single GPU
    missing = []
    gpus = sorted((d for d in hw.devices if d.vendor != "cpu" and not d.desktop), key=lambda d: -d.give())
    if gpus:
        big = gpus[0]
        sub = Hardware([big] + [x for x in hw.devices if x.vendor == "cpu" and x.host == big.host], hw.ram_gib)
        for cap in wants:
            if cap in running:
                continue
            os_ = sorted((o for o in options(cat, cap, sub, licence, region) if o.devices == (big.id,)),
                         key=lambda o: -utility(o, goal))
            if os_:
                missing.append(dict(_odoc(cat, os_[0], hw), capability=cap, device=big.key))
    return {"catalog": {"researched": cat.researched, "refreshed": cat.refreshed, "path": cat.path},
            "goal": goal, "licence": licence, "region": region, "devices": devices, "upgrades": upgrades,
            "not_running": missing, "licence_warnings": warnings, "installed": have, "notes": hw.notes}


def _held_on(h, d):
    w = (h.get("where") or "").lower()
    holds = " ".join(d.holds).lower()
    return bool(w) and (w in holds or any(w.startswith(x.split("/")[-1].split(" ")[0]) for x in d.holds if x))


# ------------------------------------------------------------------ settings (~/.config/bromigos/lab.toml)
# The planner's inputs, the upgrade policy and the bench switch live in their own small file,
# not homelab.toml: VECTOR's guard switches his terminal off whenever homelab.toml changes, and
# Settings writes these on every slider. [plan], [upgrade] and [bench] here; the same tables
# under [lab.*] in homelab.toml are read when lab.toml doesn't have them (hand-written).
def settings_path():
    if os.environ.get("BROMIGOS_LAB_SETTINGS"):
        return os.environ["BROMIGOS_LAB_SETTINGS"]
    return os.path.join(os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config"), "bromigos", "lab.toml")


def read_settings():
    """{"plan": {...}, "upgrade": {...}, "bench": {...}}: lab.toml over homelab.toml's [lab.*]."""
    out = {}
    try:
        from . import config
        lab = config.table("lab")
        for k in ("plan", "upgrade", "bench"):
            if isinstance(lab.get(k), dict):
                out[k] = dict(lab[k])
    except Exception:                                         # noqa: BLE001
        pass
    try:
        with open(settings_path(), "rb") as f:
            mine = tomllib.load(f)
        for k in ("plan", "upgrade", "bench"):
            if isinstance(mine.get(k), dict):
                out[k] = dict(mine[k])
    except (OSError, tomllib.TOMLDecodeError):
        pass
    return out


def _toml_value(v):
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int, float)):
        return repr(round(v, 2)) if isinstance(v, float) else str(v)
    if isinstance(v, str):
        return json.dumps(v)
    if isinstance(v, (list, tuple)):
        return "[" + ", ".join(_toml_value(x) for x in v) + "]"
    if isinstance(v, dict):
        return "{ " + ", ".join(f"{json.dumps(str(k))} = {_toml_value(x)}" for k, x in v.items()) + " }"
    raise CatalogError(f"can't write {v!r} to lab.toml")


def save_settings(section, values):
    """Replace one table ([plan], [upgrade] or [bench]) of lab.toml; the others are kept as
    they are. Writes through a symlink (a dotfiles-managed file stays linked), atomically."""
    if section not in ("plan", "upgrade", "bench"):
        raise CatalogError(f"lab.toml has no [{section}]")
    path = settings_path()
    real = os.path.realpath(path)
    try:
        with open(real) as f:
            text = f.read()
    except OSError:
        text = ("# bromigOS lab settings (docs/lab-models.md): the planner's inputs, the upgrade policy and\n"
                "# the catalog bench. Settings › Lab writes it; so can you. Nothing private belongs here.\n")
    body = "".join(f"{k} = {_toml_value(v)}\n" for k, v in values.items() if v is not None)
    block = f"[{section}]\n{body}"
    pat = re.compile(r"^\[" + re.escape(section) + r"\]\s*\n(?:(?!^\[).*\n?)*", re.M)
    text = pat.sub(lambda m: block + "\n", text, count=1) if pat.search(text) else \
        text.rstrip("\n") + "\n\n" + block
    tomllib.loads(text)                                       # never write a file that doesn't parse
    os.makedirs(os.path.dirname(real), exist_ok=True)
    tmp = real + ".tmp"
    with open(tmp, "w") as f:
        f.write(text)
    try:
        os.chmod(tmp, os.stat(real).st_mode & 0o777)
    except OSError:
        pass
    os.replace(tmp, real)
    return real


def _settings():
    return dict(read_settings().get("plan") or {})


US_ZONES = re.compile(r"(America/(New_York|Chicago|Denver|Los_Angeles|Phoenix|Anchorage|Adak|Boise|Detroit|"
                      r"Juneau|Metlakatla|Nome|Sitka|Yakutat|Menominee|Indiana/.*|Kentucky/.*|North_Dakota/.*)|"
                      r"Pacific/Honolulu|US/.*)$")
EU_COUNTRIES = {"AT", "BE", "BG", "HR", "CY", "CZ", "DK", "EE", "FI", "FR", "DE", "GR", "HU", "IE", "IT", "LV",
                "LT", "LU", "MT", "NL", "PL", "PT", "RO", "SK", "SI", "ES", "SE"}
EU_ZONES = re.compile(r"Europe/(Amsterdam|Athens|Berlin|Bratislava|Brussels|Bucharest|Budapest|Busingen|"
                      r"Copenhagen|Dublin|Helsinki|Lisbon|Ljubljana|Luxembourg|Madrid|Malta|Mariehamn|Paris|"
                      r"Prague|Riga|Rome|Sofia|Stockholm|Tallinn|Vienna|Vilnius|Warsaw|Zagreb)$|"
                      r"Asia/(Nicosia|Famagusta)$|Atlantic/(Canary|Madeira|Azores)$")


def default_region():
    """Where the licences are read for when Settings doesn't say: the time zone's country
    (US, EU, UK, KR); with no time zone (or UTC), the locale's; else None (every model counts)."""
    zone = os.environ.get("TZ", "").lstrip(":")
    if not zone:
        try:
            zone = os.readlink("/etc/localtime").split("zoneinfo/", 1)[-1]
        except OSError:
            zone = ""
    if US_ZONES.match(zone):
        return "US"
    if EU_ZONES.match(zone):
        return "EU"
    if zone in ("Europe/London", "Europe/Belfast", "GB"):
        return "UK"
    if zone in ("Asia/Seoul", "ROK"):
        return "KR"
    if "/" in zone and not zone.startswith("Etc/"):
        return None                                  # a place none of the licences single out
    lang = os.environ.get("LC_ALL") or os.environ.get("LANG") or ""
    m = re.match(r"[a-z]{2,3}_([A-Z]{2})", lang)
    cc = m.group(1) if m else ""
    return {"US": "US", "GB": "UK", "KR": "KR"}.get(cc) or ("EU" if cc in EU_COUNTRIES else None)


def settings():
    """The planner's saved inputs: wants, always, goal, goals, priority, licence, region, budgets."""
    s = _settings()
    return {"wants": s.get("wants") or list(DEFAULT_WANTS), "always": s.get("always"),
            "goal": s.get("goal", "balanced"), "goals": dict(s.get("goals") or {}),
            "priority": s.get("priority", "balanced"), "licence": s.get("licence", "any"),
            "region": s.get("region") or None, "budgets": dict(s.get("budgets") or {}),
            "clients": s.get("clients"), "context": s.get("context")}


# ------------------------------------------------------------------ the docs' table
def tier_table(cat, cap, goal="quality", licence="any", tiers=TIERS + tuple(SETUPS), region=None):
    """{tier: pick doc} for the docs and the tests."""
    out = {}
    for t in tiers:
        if t == "cpu":
            out[t] = pick(cap, None, cat=cat, goal=goal, licence=licence, alternatives=1, region=region)
        elif t in SETUPS:
            s = SETUPS[t]
            hw_words = [f"{s[1]}x {s[0]}" if s[1] > 1 else s[0]]
            if len(s) > 2 and s[2]:
                hw_words = [f"{s[0]},mem={s[2]}"]
            if len(s) > 3:
                hw_words = [hw_words[0] + "," + s[3]]
            hw = Hardware.parse(hw_words, ram_gib=(s[2] if len(s) > 2 and s[2] else 256.0), cat=cat)
            os_ = sorted(options(cat, cap, hw, licence, region), key=lambda o: (-utility(o, goal), -o.quality))
            out[t] = {"best": _odoc(cat, os_[0], hw) if os_ else None,
                      "alternatives": [_odoc(cat, o, hw) for o in os_[1:2]]}
        else:
            out[t] = pick(cap, float(t), cat=cat, goal=goal, licence=licence, alternatives=1, region=region,
                          ram_gib=64.0 if float(t) <= 32 else 128.0)
    return out


DOC_TIERS = ("cpu", "8", "12", "16", "24", "32", "48", "80", "96", "2x24", "2x32", "4x32", "2x80", "4x80", "8x80",
             "8xb200", "spark", "2xspark", "mac-64", "mac-128", "mac-192", "mac-512")


def _cell(cat, b):
    if not b:
        return "none fits"
    m = cat.models[b["model"]]
    mark = " †" if m.licence.territory else (" ‡" if m.licence.commercial == "no" else "")
    mem = "CPU" if b.get("on_cpu") else f"{b['vram_gib']:.0f} GiB" + (" + RAM" if b["offload"] else "")
    return f"{b['name']} {b['quant']}{mark} ({mem}, {b['speed_text']})"


def markdown_tables(cat, licence="any", tiers=DOC_TIERS, region="US"):
    """The docs' tables: per capability and tier, the best-quality pick, the balanced pick and
    the best one whose licence allows commercial use."""
    lines = []
    for cap in CAPABILITIES:
        c = cat.caps[cap]
        lines.append(f"### {c.title} (`{cap}`)\n")
        if c.notes:
            lines.append(c.notes + "\n")
        lines.append("| Setup | Best quality | Balanced | Commercial use allowed |")
        lines.append("|---|---|---|---|")
        tq = tier_table(cat, cap, goal="quality", licence=licence, tiers=tiers, region=region)
        tb = tier_table(cat, cap, goal="balanced", licence=licence, tiers=tiers, region=region)
        tc = tier_table(cat, cap, goal="quality", licence="commercial", tiers=tiers, region=region)
        for t in tiers:
            q, b, cm = tq[t].get("best"), tb[t].get("best"), tc[t].get("best")
            bc = "same" if b and q and b["key"] == q["key"] else _cell(cat, b)
            cc = "same" if cm and q and cm["key"] == q["key"] else _cell(cat, cm)
            lines.append(f"| {t} | {_cell(cat, q)} | {bc} | {cc} |")
        lines.append("")
    return "\n".join(lines)


# ------------------------------------------------------------------ the command
USAGE = """bromigos lab models recommend|plan|pick|tiers|upgrades|refresh|check (docs/lab-models.md)

  recommend [--json] [--goal G] [--licence L]       what fits this lab's GPUs, installed vs recommended
  plan [--budget gpu0=24G,RTX 5070=6G] [--always llm,tts,stt] [--want …] [--goal quality|balanced|speed
       or video=quality,llm=speed] [--priority balanced|brain|media|voice|resident] [--licence any|commercial|
       permissive] [--region EU] [--clients 16 --context 32k --prompt 3k --output 400]
       [--hw "RTX 5090" --hw "RTX 5070,desktop" --ram 64] [--json]
                                                    two to four ranked configurations (goal throughput:
                                                    many agents on one LLM)
  pick CAPABILITY [VRAM] [--vendor amd] [--gpu NAME] [--gpus N] [--goal G] [--licence L] [--json]
  tiers CAPABILITY [--json] [--markdown]            the best fit per tier
  upgrades [--json] [--apply]                       what the upgrade policy ([lab.upgrade]) would do now
  refresh [--hf] [--json]                           a newer signed catalog; --hf: check Hugging Face for
                                                    newer or better candidates (flagged for review, never applied)
  check                                             the catalog's data is consistent
Capabilities: """ + " ".join(CAPABILITIES)


def _arg(argv, name, default=None, many=False):
    vals = []
    i = 0
    while i < len(argv):
        a = argv[i]
        if a == name and i + 1 < len(argv):
            vals.append(argv[i + 1])
            i += 2
            continue
        if a.startswith(name + "="):
            vals.append(a.split("=", 1)[1])
        i += 1
    if many:
        return vals
    return vals[-1] if vals else default


VALUED = {"--catalog", "--goal", "--licence", "--region", "--vendor", "--gpu", "--gpus", "--ram", "--hw", "--budget",
          "--always", "--want", "--clients", "--context", "--prompt", "--output", "--priority", "--since", "--repo"}


def _positional(argv):
    out, skip = [], False
    for a in argv:
        if skip:
            skip = False
            continue
        if a in VALUED:
            skip = True
            continue
        if not a.startswith("--"):
            out.append(a)
    return out


def _list(s):
    return [x.strip() for x in (s or "").split(",") if x.strip()]


def _budgets(s):
    out = {}
    for part in _list(s):
        k, _, v = part.partition("=")
        if not v:
            raise CatalogError(f"--budget {part!r}: use gpu0=24G or 'RTX 5070=6G'")
        out[k.strip()] = float(re.sub(r"(?i)\s*gi?b?$", "", v.strip()))
    return out


def _goals(s, default):
    goals = {"*": default}
    for part in _list(s):
        if "=" in part:
            k, v = part.split("=", 1)
            goals[canon(k.strip())] = v.strip()
        else:
            goals["*"] = part
    for k, v in goals.items():
        if v not in GOALS:
            raise CatalogError(f"goal {v!r}: quality, balanced or speed")
    return goals


def _print_plan(doc):
    print(f"hardware: " + ", ".join(f"{d['id']} {d['name']} ({d['budget_gib']:.0f} of {d['vram_gib']:.0f} GiB"
                                   f"{', desktop' if d['desktop'] else ''})" for d in doc["hardware"]
                                   if d["vendor"] != "cpu"))
    ld = doc.get("load") or {}
    print(f"wants: {', '.join(doc['wants'])} · always on: {', '.join(doc['always']) or 'none'} · "
          f"licence: {doc['licence']}" + (f" · region {doc['region']}" if doc["region"] else "") +
          f" · LLM load: {ld.get('clients', 1)} client(s), {ld.get('context', 0) // 1024}k context")
    for n, c in enumerate(doc["configurations"], 1):
        print(f"\n{n}. {c['name']}: {c['aim']} — {c['sacrifice']}")
        for d in c["devices"]:
            print(f"   {d['id']} {d['name']}: peak {d['peak_gib']:.1f} of {d['budget_gib']:.1f} GiB "
                  f"(resident {d['resident_gib']:.1f}, headroom {d['headroom_gib']:.1f})")
        for p in sorted(c["placements"], key=lambda p: (not p["resident"], p["capability"])):
            tag = "resident" if p["resident"] else "on demand"
            if p.get("shared_with"):
                print(f"   {p['capability']:<10} {p['name']} (shared with {p['shared_with']})")
                continue
            print(f"   {p['capability']:<10} {p['name']} {p['quant']} · {p['runtime']} · {'+'.join(p['devices'])} · "
                  f"{p['per_gpu_gib']:.1f} GiB{' each' if len(p['devices']) > 1 else ''} · {tag} · "
                  f"{p['speed_text']} · q{p['quality']:.0f} · {p['licence_plain']}")
            if p.get("serving") and not p.get("shared_with"):
                sv_ = p["serving"]
                print(f"   {'':<10} serves {sv_['clients']} at ~{sv_['per_stream']:.0f} tok/s each, ~{sv_['aggregate']:.0f} "
                      f"tok/s in all, first token ~{sv_['ttft_s']:.1f} s; KV cache {sv_['kv_gib']:.1f} GiB "
                      f"({'from published benchmarks' if sv_.get('note', '').startswith('published') else 'estimate'}"
                      f"{', ' + str(sv_['waiting']) + ' wait' if sv_.get('waiting') else ''})")
        for m in c["missing"]:
            print(f"   {m['capability']:<10} none: {m['why']}")
    for n in doc.get("notes") or []:
        print("note:", n)


def s_goal(s):
    return s.get("goal") or "balanced"


def _print_recommend(doc):
    print(f"catalog researched {doc['catalog']['researched']} · goal {doc['goal']} · licence {doc['licence']}"
          + (f" · region {doc['region']}" if doc.get("region") else ""))
    for d in doc["devices"]:
        print(f"\n{d['id']} {d['name']} ({d['vram_gib']:.0f} GiB{', unified' if d['unified'] else ''}"
              f"{', linked' if d.get('linked') else ''}{', desktop' if d['desktop'] else ''}): "
              f"{', '.join(d['holds']) or 'nothing running'}")
        for r in d["picks"]:
            b = r["pick"]
            have = r.get("current") or "-"
            flag = "  UPGRADE" if r.get("upgrade") else ""
            print(f"  {r['capability']:<10} runs: {have:<40} best fit: {b['name']} {b['quant']} "
                  f"({b['vram_gib']:.1f} GiB, {b['speed_text']}, {b['licence_plain']}){flag}")
    if doc.get("not_running"):
        print("\nnothing in the lab runs these yet; the best fit on the biggest GPU:")
        for m in doc["not_running"]:
            print(f"  {m['capability']:<10} {m['name']} {m['quant']} on {m['device']} ({m['vram_gib']:.1f} GiB, "
                  f"{m['speed_text']}, {m['licence_plain']})")
    if doc["upgrades"]:
        print("\nupgrades that fit:")
        for u in doc["upgrades"]:
            print(f"  {u['device']} {u['capability']}: {u['from']} -> {u['to']} (+{u['gain']} quality, "
                  f"{u['vram_gib']:.1f} GiB, {u['licence_plain']})")
    for w in doc.get("licence_warnings") or []:
        print(f"licence: {w['model']} on {w['device']}: {w['why']}")
    print("\nA whole configuration (what stays resident, what swaps): bromigos lab models plan")
    for n in doc["notes"]:
        print("note:", n)


def _print_pick(doc):
    b = doc["best"]
    print(f"{doc['capability']} on {doc['hardware']} ({doc['goal']}):")
    if not b:
        print("  " + doc["reason"])
        return
    print(f"  {b['name']} {b['quant']} · {b['runtime']} · {b['vram_gib']:.1f} GiB · {b['speed_text']} · "
          f"quality {b['quality']:.0f} · {b['licence']} ({b['licence_plain']})")
    for a in doc["alternatives"]:
        print(f"  or {a['name']} {a['quant']} · {a['runtime']} · {a['vram_gib']:.1f} GiB · {a['speed_text']} · "
              f"quality {a['quality']:.0f} · {a['licence_plain']}")
    print("  " + doc["reason"])


def main(argv):
    argv = list(argv)
    if not argv or argv[0] in ("-h", "--help", "help"):
        print(USAGE)
        return 0
    cmd, rest = argv[0], argv[1:]
    js = "--json" in rest
    try:
        if cmd == "check":
            cat = load(_arg(rest, "--catalog"))
            problems = validate(cat)
            for p in problems:
                print("problem:", p)
            print(f"{cat.path}: {len(cat.models)} models, "
                  f"{sum(len(m.variants) for m in cat.models.values())} variants, researched {cat.researched}"
                  + ("" if problems else ", consistent"))
            return 1 if problems else 0
        if cmd == "refresh":
            from . import catalog_refresh
            return catalog_refresh.main(rest)
        if cmd == "upgrades":
            from . import catalog_upgrade
            return catalog_upgrade.main(rest)
        cat = load(_arg(rest, "--catalog"))
        s = settings()
        licence = _arg(rest, "--licence", s["licence"])
        if licence not in LICENCE_FILTERS:
            raise CatalogError(f"--licence {licence}: {', '.join(LICENCE_FILTERS)}")
        region = _arg(rest, "--region", s["region"] or default_region())
        if region and region.lower() in ("any", "none", "-"):
            region = None
        if cmd == "pick":
            pos = _positional(rest)
            if not pos:
                raise CatalogError("pick which capability? " + " ".join(CAPABILITIES))
            vram = float(pos[1]) if len(pos) > 1 else None
            doc = pick(pos[0], vram, vendor=_arg(rest, "--vendor", "nvidia"), licence=licence, region=region,
                       goal=_arg(rest, "--goal", "quality"), gpu=_arg(rest, "--gpu"),
                       gpus=int(_arg(rest, "--gpus", 1)), ram_gib=float(_arg(rest, "--ram", 64)), cat=cat)
            print(json.dumps(doc, indent=1)) if js else _print_pick(doc)
            return 0 if doc["best"] else 1
        if cmd == "tiers":
            pos = _positional(rest)
            if not pos:
                if "--markdown" in rest:
                    print(markdown_tables(cat, licence, region=region or "US"))
                    return 0
                raise CatalogError("tiers for which capability?")
            t = tier_table(cat, canon(pos[0]), goal=_arg(rest, "--goal", "quality"), licence=licence)
            if js:
                print(json.dumps(t, indent=1))
            else:
                for k, d in t.items():
                    b = d.get("best")
                    print(f"  {k:<8} " + (f"{b['name']} {b['quant']} ({b['vram_gib']:.1f} GiB, {b['speed_text']}, "
                                          f"{b['licence']})" if b else "none fits"))
            return 0
        hw = None
        hws = _arg(rest, "--hw", many=True)
        if hws:
            hw = Hardware.parse(hws, ram_gib=float(_arg(rest, "--ram", 64)), cat=cat)
        if cmd == "recommend":
            doc = recommend(cat, hw, goal=_arg(rest, "--goal", s_goal(s)), licence=licence, region=region,
                            every="--all" in rest)
            if js:
                print(json.dumps(doc, indent=1, default=str))
                return 0
            _print_recommend(doc)
            return 0
        if cmd == "plan":
            if hw is None:
                hw = detect(cat)
            budgets = dict(s["budgets"])
            budgets.update(_budgets(_arg(rest, "--budget", "")))
            goals = dict(s["goals"])
            goals["*"] = s["goal"]
            goals.update(_goals(_arg(rest, "--goal", ""), goals["*"]))
            wants = _list(_arg(rest, "--want", "")) or s["wants"]
            always = _list(_arg(rest, "--always", "")) or s["always"]
            from . import catalog_serving as sv
            serving = sv.Load.parse(_arg(rest, "--clients", s["clients"]), _arg(rest, "--context", s["context"]),
                                    _arg(rest, "--prompt"), _arg(rest, "--output"))
            doc = plan(hw, wants=wants, always=always, goals=goals, priority=_arg(rest, "--priority", s["priority"]),
                       licence=licence, region=region, cat=cat, budgets=budgets,
                       unsupported="--unsupported" in rest, serving=serving)
            print(json.dumps(doc, indent=1, default=str)) if js else _print_plan(doc)
            return 0 if doc["configurations"] else 1
    except CatalogError as e:
        print(f"bromigos lab models: {e}", file=sys.stderr)
        return 2
    print(USAGE, file=sys.stderr)
    return 2


# ------------------------------------------------------------------ consistency
def validate(cat):
    """Plain-words problems with the data (the tests and `check` run it)."""
    out = []
    for m in cat.models.values():
        if not m.variants:
            out.append(f"{m.id}: no variants")
        for c in m.caps:
            if c not in m.quality and "*" not in m.quality:
                out.append(f"{m.id}: no quality score for {c}")
        if not m.cite:
            out.append(f"{m.id}: no source cited")
        for v in m.variants:
            if v.vram_gib < 0 or (v.vram_gib == 0 and "cpu" not in v.vendors):
                out.append(f"{v.key}: no peak VRAM")
            if v.speed and v.speed_ref and not _ref(cat, v.speed_ref):
                out.append(f"{v.key}: speed_ref {v.speed_ref!r} isn't a [gpu]")
            if v.stack != "ready" and not v.stack.startswith("needs support"):
                out.append(f"{v.key}: stack must be 'ready' or 'needs support: …'")
            bad = [x for x in v.vendors if x not in ("nvidia", "amd", "apple", "intel", "cpu")]
            if bad:
                out.append(f"{v.key}: unknown vendors {bad}")
    for c in CAPABILITIES:
        if not cat.variants(c):
            out.append(f"{c}: no models")
    return out


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
