"""Many agents on one LLM: what a model and runtime serve at a given concurrency (the lab
model catalog's planner, docs/lab-models.md "Many agents at once").

A decoding step reads the weights it touches once for the whole batch, plus each sequence's
KV cache; it is memory-bound until the batch is big enough to be compute-bound. So:

    step time  t(B) = max(bytes read / (bandwidth x efficiency), 2 x active params x B / compute) + overhead
    per stream     = 1 / t(B)            aggregate = B / t(B)

- **KV cache** grows with clients x context and sits beside the weights: a model that fits
  one user may not fit sixteen. Hybrid models (linear attention, Mamba) keep KV only in their
  few full-attention layers, plus a fixed state per sequence.
- **MoE**: a batch touches more experts than one token does, so the bytes per step grow with
  the batch (toward all the weights), while compute stays at the active parameters.
- **Runtimes**: vLLM and SGLang batch continuously (hundreds of sequences); llama.cpp,
  Ollama and MLX serve a few parallel slots and each slot gets its own share of the context.
- **Tensor parallel** adds the cards' bandwidth and compute, less what the link costs.

The efficiency is calibrated from the variant's measured single-stream speed when the
catalog has one, else 0.6 of the card's bandwidth. Everything here is an estimate unless the
model lists a published serving benchmark (`serving` in models.toml), which the plan shows
beside it.
"""
import dataclasses
import math
import re

KIB, GIB = 1024, 1024 ** 3


@dataclasses.dataclass
class Load:
    clients: int = 1                 # agents hitting the endpoint at once
    context: int = 32768             # the longest context a request may need
    prompt: int = 3000               # a typical request's prompt tokens (an agent's turn: tools, history)
    output: int = 400                # a typical reply
    max_seqs: int = 0                # the server's own cap on sequences at once (vLLM --max-num-seqs), 0: its default

    @classmethod
    def parse(cls, clients=None, context=None, prompt=None, output=None):
        def tok(x, d):
            if x in (None, ""):
                return d
            s = str(x).strip().lower()
            m = re.fullmatch(r"(\d+(?:\.\d+)?)\s*([km]?)", s)
            if not m:
                raise ValueError(f"{x!r}: a token count like 32k")
            return int(float(m.group(1)) * {"": 1, "k": 1024, "m": 1024 * 1024}[m.group(2)])
        d = cls()
        return cls(int(clients or d.clients), tok(context, d.context), tok(prompt, d.prompt), tok(output, d.output))


BPW = [  # bytes per weight, by quantisation (with scales)
    (r"nvfp4|mxfp4|fp4", 0.56), (r"q2|iq2", 0.34), (r"q3", 0.45), (r"q4|awq|gptq|int4|w4a16|4bit", 0.58),
    (r"q5", 0.69), (r"q6", 0.82), (r"q8|int8|fp8|w8a8|8bit", 1.06), (r"bf16|fp16|f16", 2.0), (r"fp32", 4.0)]

PREFIX_CACHED = 0.5   # the share of an agent's prompt (its history) a server's prefix cache already holds
BATCHING = {"vllm": 256, "sglang": 256}                     # the most sequences a step decodes
SLOTS = {"llama.cpp": 4, "ollama": 4, "mlx": 2}             # parallel slots (OLLAMA_NUM_PARALLEL, -np)


def bpw(quant):
    q = (quant or "").lower()
    for pat, b in BPW:
        if re.search(pat, q):
            return b
    return 2.0


def weights_gib(model, v):
    """The weights alone: the variant's figure, else parameters x bytes per weight."""
    w = getattr(v, "weights_gib", 0) or 0
    if w:
        return w
    if model.params_b:
        return model.params_b * 1e9 * bpw(v.quant) / GIB
    return 0.0


def kv_bytes_per_token(model, v, arch=""):
    """KV cache per token: vLLM keeps it in FP8 on cards with FP8 (Ada, Hopper, Blackwell),
    llama.cpp in F16 unless told otherwise."""
    kib = model.kv_kib_per_token or 0
    if not kib:
        return 0
    fp8 = v.runtime in ("vllm", "sglang") and arch in ("ada", "hopper", "blackwell", "cdna3")
    return kib * KIB * (0.5 if fp8 else 1.0)


def touched(model, batch):
    """The share of the weights one decoding step reads at this batch (MoE: more experts)."""
    if not model.params_b or not model.active_b or model.active_b >= model.params_b:
        return 1.0
    a = model.active_b / model.params_b
    shared = min(a, 0.35 * a)                  # attention, embeddings, shared experts: every token
    per = (a - shared) / max(1e-9, 1 - shared)
    return min(1.0, shared + (1 - shared) * (1 - (1 - per) ** max(1, batch)))


def memory(model, v, load, devs, slots=None):
    """GiB the server needs at this load: weights + KV for the tokens in flight + per-sequence
    state + working memory. (per GPU when split: / len(devs))."""
    arch = devs[0].arch if devs else ""
    w = weights_gib(model, v)
    kvb = kv_bytes_per_token(model, v, arch)
    if v.runtime in SLOTS:
        n = min(load.clients, slots or SLOTS[v.runtime])
        tokens = n * load.context                   # each slot gets its own whole context
    else:
        n = min(load.clients, BATCHING.get(v.runtime, 1))
        tokens = max(load.context, n * (load.prompt + load.output))
    kv = tokens * kvb / GIB
    state = (model.state_mib_per_seq or 0) * n / 1024
    work = 1.0 + 0.25 * len(devs or [1]) + (0.02 * w if v.runtime in ("vllm", "sglang") else 0.0)
    return w, kv + state, work


def _eff(model, v, ref, cat_unit_speed):
    """Bandwidth efficiency, calibrated from the measured single-stream speed on `ref` (on the
    variant's own GPU count when it was measured split, e.g. TP=2 on two GB10s)."""
    if not cat_unit_speed or not ref or not getattr(ref, "bandwidth", 0):
        return 0.6
    w = weights_gib(model, v) * GIB * touched(model, 1)
    if not w:
        return 0.6
    t = 1.0 / cat_unit_speed - 0.002
    if t <= 0:
        return 0.9
    n = max(1, getattr(v, "gpus", 1))
    bw = ref.bandwidth * n * (TP_GAIN.get(n, 0.55) if n > 1 else 1.0)
    return max(0.15, min(0.92, w / (bw * 1e9 * t)))


TP_GAIN = {1: 1.0, 2: 0.82, 3: 0.72, 4: 0.7, 8: 0.6}


def _estimate(model, v, devs, load, ref=None, link_loss=None):
    """The bandwidth and compute model's figures at this load on these devices."""
    n = max(1, len(devs))
    bw = sum(d.bandwidth for d in devs) or 0
    compute = sum(d.compute for d in devs) or 0
    gain = TP_GAIN.get(n, 0.55) if n > 1 else 1.0
    if link_loss is not None and n > 1:
        gain *= link_loss
    if v.runtime in SLOTS and n > 1:                             # a layer split: one card at a time
        bw, compute, gain = min(d.bandwidth for d in devs), min(d.compute for d in devs), 0.9
    eff = _eff(model, v, ref, v.speed if v.speed_ref and v.speed_ref != "cpu" else 0)
    if devs and devs[0].vendor == "cpu":
        eff = 0.5
    w, kv, work = memory(model, v, load, devs)
    if v.runtime in SLOTS:
        batch = min(load.clients, load.max_seqs or SLOTS[v.runtime])
    else:
        batch = min(load.clients, load.max_seqs or BATCHING.get(v.runtime, 1))
    kvb = kv_bytes_per_token(model, v, devs[0].arch if devs else "")
    avg_ctx = load.prompt + load.output / 2
    fresh = load.prompt * (1 - PREFIX_CACHED) / max(1, load.output)   # prompt tokens prefilled per token decoded

    def step(b):
        bytes_ = weights_gib(model, v) * GIB * touched(model, b) + b * avg_ctx * kvb
        t_mem = bytes_ / max(1.0, bw * 1e9 * eff * gain)
        fmt = 4.0 if bpw(v.quant) < 0.6 and any(d.arch == "blackwell" for d in devs) else \
            (2.0 if bpw(v.quant) <= 1.1 and any(d.arch in ("ada", "hopper", "blackwell") for d in devs) else 1.0)
        flops = 2 * (model.active_b or model.params_b or 1) * 1e9
        t_cmp = flops * b / max(1.0, compute * 1e12 * fmt * 0.35 * gain)
        if b > 1:                                   # the others' new prompt tokens, chunked into the same steps
            t_cmp += flops * (b - 1) * fresh / max(1.0, compute * 1e12 * fmt * 0.5 * gain)
        t = max(t_mem, t_cmp) + 0.002
        if v.runtime in SLOTS and b > 1:
            t *= 1 + 0.35 * (b - 1) / b * b ** 0.5 / 2      # slots share kernels poorly
        return t

    t1 = step(1)
    tb = step(batch)
    per = 1.0 / tb
    agg = batch / tb
    # time to first token: the prompt's prefill (compute-bound), queued behind the others'
    pre = 2 * (model.active_b or model.params_b or 1) * 1e9 * load.prompt / max(1.0, compute * 1e12 * 0.45 * gain)
    queue = (1 + 0.15 * (batch - 1)) if v.runtime not in SLOTS else (1 + 0.5 * (batch - 1))
    if load.clients > batch:
        queue += (load.clients - batch) / max(1, batch) * (load.output * tb) / max(pre, 1e-3) * 0.1
    note = "estimate (bandwidth model, calibrated on its measured speed)" if v.speed else "estimate (bandwidth model)"
    return {"per_stream": round(per, 1), "aggregate": round(agg, 1), "single": round(1.0 / t1, 1),
            "ttft_s": round(pre * queue, 2), "batch": batch, "clients": load.clients,
            "weights_gib": round(w, 1), "kv_gib": round(kv, 1), "vram_gib": round(w + kv + work, 1),
            "waiting": max(0, load.clients - batch), "note": note}



def serve(model, v, devs, load, ref=None, link_loss=None):
    """{per_stream, aggregate, ttft_s, batch, vram_gib, kv_gib, note} at this load on these
    devices (a split across all of them). Where someone published this model served on the
    same hardware, their figures anchor it; the bandwidth model only fills in between."""
    out = _estimate(model, v, devs, load, ref, link_loss)
    pub = published(model, v, devs, dataclasses.replace(load, clients=min(load.clients, out["batch"])),
                    lambda c: _estimate(model, v, devs, dataclasses.replace(load, clients=c), ref, link_loss)["aggregate"])
    if pub:
        note = f"published, measured at {', '.join(map(str, pub['measured_at']))} at once"
        if pub["speculative"]:
            note += ", with speculative decoding (MTP)"
        out.update(per_stream=pub["per_stream"], aggregate=pub["aggregate"], note=f"{note} ({pub['url']})")
        if pub["ttft_s"] and not out["waiting"]:        # past the cap the queue sets the wait
            out["ttft_s"] = pub["ttft_s"]
    return out


HW_KEYS = (("gb10", ("spark", "gb10")), ("rtx 5090", ("5090",)), ("rtx 4090", ("4090",)), ("h100", ("h100",)),
           ("h200", ("h200",)), ("b200", ("b200",)), ("rtx pro 6000", ("pro 6000",)), ("a100", ("a100",)),
           ("mi300x", ("mi300",)), ("apple m3 ultra", ("m3 ultra",)), ("apple m4 max", ("m4 max", "m5 max")))
QKINDS = ("nvfp4", "mxfp4", "fp8", "awq", "gptq", "int4", "int8", "gguf", "mlx", "bf16", "fp16")
SPECULATIVE = re.compile(r"mtp|specul|eagle|dflash|dspark|n-gram|ngram|medusa", re.I)


def _hw_match(devs, text):
    """Whether a benchmark's hardware ("2x DGX Spark TP=2", "RTX 5090") is these devices."""
    t = (text or "").lower()
    if not devs or "hosted" in t:
        return False
    name = devs[0].name.lower()
    keys = next((ks for k, ks in HW_KEYS if k == name), (name,))
    if not any(k in t for k in keys):
        return False
    m = re.match(r"\s*(\d+)\s*x", t)
    return (int(m.group(1)) if m else 1) == len(devs)


def _qkind(text):
    """A quantisation's kind ("NVFP4 experts + FP8 n-gram table" is nvfp4; "IQ4_XS" is gguf)."""
    t = (text or "").lower()
    hits = [(t.find(k), k) for k in QKINDS if k in t]
    m = re.search(r"\b(i?q\d(_[a-z0-9]+)*)\b", t)
    if m:
        hits.append((m.start(), "gguf"))
    return min(hits)[1] if hits else ""


def published(model, v, devs, load, estimate=None):
    """A published serving benchmark of this model on these devices at `load.clients`:
    {per_stream, aggregate, ttft_s, url, measured_at, speculative} or None. Only points of
    the variant's own kind of quantisation count, and its own runtime's when there are any.
    Between two measured concurrencies it interpolates; outside them, `estimate(clients)`
    (the aggregate the bandwidth model gives) scales from the nearest measured point."""
    clients = max(1, load.clients)
    kind = _qkind(v.quant)
    pts = []
    for s in model.serving or ():
        hw = s.get("hardware")
        if not _hw_match(devs, hw):
            continue
        if _qkind(s.get("quant")) and _qkind(s.get("quant")) != kind:
            continue
        ctx = re.search(r"(\d+)\s*k\s*ctx", (hw or "").lower())
        if ctx and not 0.5 <= int(ctx.group(1)) * 1024 / max(1, load.context) <= 2:
            continue                               # measured at a very different context
        c = s.get("concurrency")
        agg, per = s.get("aggregate_tok_s"), s.get("per_stream_tok_s")
        if not c or not (agg or per):
            continue
        agg = float(agg or per * c)
        per = float(per or agg / c)
        rt = s.get("runtime") or ""
        own = v.runtime.split(".")[0] in rt.lower()
        pts.append((own, int(c), agg, min(per, agg / c * 1.1), s.get("ttft_ms"), s.get("url"),
                    bool(SPECULATIVE.search(rt))))
    if not pts:
        return None
    if any(p[0] for p in pts):
        pts = [p for p in pts if p[0]]
    best = {}
    for p in pts:                                  # the best published figure at each concurrency
        if p[1] not in best or p[2] > best[p[1]][2]:
            best[p[1]] = p
    pts = sorted(best.values(), key=lambda p: p[1])
    lo = max((p for p in pts if p[1] <= clients), key=lambda p: p[1], default=None)
    hi = min((p for p in pts if p[1] >= clients), key=lambda p: p[1], default=None)
    if lo and hi and lo[1] != hi[1]:
        f = (math.log(clients) - math.log(lo[1])) / (math.log(hi[1]) - math.log(lo[1]))
        agg = math.exp(math.log(lo[2]) + f * (math.log(hi[2]) - math.log(lo[2])))
        used = (lo, hi)
    elif lo or hi:
        p = lo or hi
        agg = p[2]
        if p[1] != clients and estimate:           # the model's shape, from the nearest measurement
            g = p[2] / max(1e-6, estimate(p[1]))
            if p[1] < clients and (p[6] or g > 1.3):
                # speculative decoding (named, or faster than the weights stream without it)
                # gains less as the batch fills the GPU
                g = 1 + (g - 1) * (p[1] / clients) ** 0.5
                p = p[:6] + (True,)
            agg = estimate(clients) * g
            if p[1] < clients:
                agg = max(agg, p[2])               # more at once never serves less in all
        elif p[1] > clients:
            agg = p[3] * clients
        used = (p,)
    per = min(agg / clients, max(p[3] for p in pts))
    near = [p for p in sorted(pts, key=lambda p: abs(math.log(p[1] / clients))) if p[4]]
    ttft = near[0][4] if near and 0.5 <= near[0][1] / clients <= 2 else None
    return {"per_stream": round(per, 1), "aggregate": round(per * clients, 1),
            "ttft_s": round(ttft / 1000, 2) if ttft else None, "url": used[-1][5],
            "measured_at": [p[1] for p in pts], "speculative": any(p[6] for p in used)}


def max_clients(model, v, devs, budget_gib, load):
    """The most concurrent clients whose KV fits in budget_gib (all devices together)."""
    lo, hi = 0, 1024
    while lo < hi:
        mid = (lo + hi + 1) // 2
        w, kv, work = memory(model, v, dataclasses.replace(load, clients=mid), devs)
        if w + kv + work <= budget_gib:
            lo = mid
        else:
            hi = mid - 1
    if v.runtime in SLOTS:
        lo = min(lo, SLOTS[v.runtime])
    return lo


def describe(s, name):
    """'serves 16 agents at ~38 tok/s each (~610 tok/s in all), first token ~0.9 s'."""
    if not s:
        return ""
    t = (f"{name}: {s['clients']} agent{'s' if s['clients'] != 1 else ''} at ~{s['per_stream']:.0f} tok/s each "
         f"(~{s['aggregate']:.0f} tok/s in all), first token ~{s['ttft_s']:.1f} s")
    if s["waiting"]:
        t += f"; {s['waiting']} wait for a slot"
    return t


def log_score(x, lo=5.0, hi=5000.0):
    if x <= 0:
        return 0.0
    return max(0.0, min(100.0, 100 * (math.log(x) - math.log(lo)) / (math.log(hi) - math.log(lo))))
