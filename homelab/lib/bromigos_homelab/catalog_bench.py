"""The catalog bench: a lab job kind that measures a catalog model on this lab's own GPU
(docs/lab-models.md, "Measured on your lab"). Off until Settings › Lab › Models turns it on
(~/.config/bromigos/lab.toml [bench] enabled = true).

    bromigos lab run catalog-bench --model qwen-image-2.1/int8       one model (its catalog key)
    bromigos lab run catalog-bench --model llm                       the served LLM, at 1, 4 and 16 clients

It goes through the lab's queue like any heavy job (one at a time, gated on free VRAM, the
voice service's reserve kept) and runs one fixed test:

- a ComfyUI workflow the lab already has: one generation through `bromigos art make` (the
  homelab provider, no credits), the peak VRAM the GPU lost while it ran and the seconds it
  took, then ComfyUI is asked to unload (POST /free);
- an LLM the lab already serves: a short concurrent-load test through its OpenAI-compatible
  endpoint (streamed chat completions at 1, 4 and 16 clients): time to first token,
  tokens/s per stream and in all;
- the voice service: one fixed line of speech and its real-time factor (its models are
  resident and never unloaded or swapped from here).

It installs nothing: a model the lab doesn't have reads "needs installing (Phase 2: bromigos
lab models add)". Results land in ~/.local/state/bromigos/lab/bench.jsonl; the catalog uses
them for this lab's GPUs instead of the published figures, and `bromigos lab models refresh
--submit-bench` posts them to the open catalog pull request for the maintainers.
"""
import json
import os
import threading
import time
import urllib.request

from . import catalog as C
from . import jobs

PROMPT_IMAGE = "A brass compass on a weathered map, soft window light, shallow depth of field"
PROMPT_LLM = ("You are benchmarking. Summarise in about two hundred words why seamless video loops need the "
              "first and last frames to match, then list three ways to hide a seam.")
LINE = "The lab bench measures how quickly this voice speaks a single ordinary sentence."
CLIENTS = (1, 4, 16)


def ledger():
    return os.environ.get("BROMIGOS_LAB_BENCH_LEDGER") or os.path.join(
        os.environ.get("XDG_STATE_HOME") or os.path.expanduser("~/.local/state"), "bromigos", "lab", "bench.jsonl")


def enabled():
    b = C.read_settings().get("bench") or {}
    if not b.get("enabled"):
        return False, "off: Settings › Lab › Models › Bench candidates on the lab (lab.toml [bench] enabled = true)"
    return True, ""


def record(row):
    p = ledger()
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "a") as f:
        f.write(json.dumps(row) + "\n")


def results():
    """{variant key: {device name: latest row}}."""
    out = {}
    try:
        with open(ledger()) as f:
            for line in f:
                try:
                    r = json.loads(line)
                except ValueError:
                    continue
                if r.get("ok") and r.get("key"):
                    out.setdefault(r["key"], {})[r.get("gpu") or "?"] = r
    except OSError:
        pass
    return out


# ------------------------------------------------------------------ ComfyUI
def _comfy_free(a):
    s = a.get_json("/system_stats", timeout=5)
    d = (s.get("devices") or [{}])[0]
    return d.get("vram_free") or 0, d.get("vram_total") or 0, d.get("name") or ""


def _bench_comfy(job, ctx, v, cap):
    src = ctx.source("comfyui")
    if src is None:
        raise jobs.JobError("no comfyui source in homelab.toml")
    if not v.workflow:
        raise jobs.JobError(f"{v.key} has no ComfyUI workflow in bromigOS yet ({v.stack})")
    free0, total, dev = _comfy_free(src)
    need = v.vram_gib * 1024 ** 3
    if total and need > total:
        raise jobs.JobError(f"{v.key} needs {v.vram_gib:.0f} GiB; the lab's GPU has {total / 1024 ** 3:.0f}")
    low = [free0]
    stop = threading.Event()

    def sample():
        while not stop.is_set():
            try:
                low.append(_comfy_free(src)[0])
            except Exception:                                 # noqa: BLE001
                pass
            stop.wait(0.5)
    t = threading.Thread(target=sample, daemon=True)
    t.start()
    started = time.time()
    try:
        argv = [jobs.bromigos_bin(), "art", "make", {"image": "image.generate", "image-edit": "image.edit",
                                                     "cutout": "image.cutout", "3d": "model3d.generate",
                                                     "video": "video.loop"}.get(cap, cap),
                "--provider", "comfyui:homelab", "--model", v.workflow, "--max-credits", "0", "--json",
                "--out", ctx.out(stem=v.key.replace("/", "-"), ext={"3d": ".glb", "video": ".mp4"}.get(cap, ".png"))]
        if cap in ("image", "video"):
            argv += ["--prompt", PROMPT_IMAGE]
        p = ctx.run(argv, timeout=1800)
        secs = time.time() - started
    finally:
        stop.set()
        t.join(2)
        try:
            src.request("/free", data={"unload_models": True, "free_memory": True}, method="POST", timeout=30, raw=True)
        except Exception:                                     # noqa: BLE001
            pass
    if p.returncode != 0:
        why = (p.stderr or p.stdout or "").strip().splitlines()
        if why and ("missing" in why[-1].lower() or "lacks" in why[-1].lower()):
            raise jobs.JobError(f"{v.key} isn't installed on the lab: needs installing (Phase 2: bromigos lab models "
                                "add)")
        raise jobs.JobError("the generation failed: " + (why[-1][:300] if why else f"exit {p.returncode}"))
    peak = max(0, free0 - min(low)) / 1024 ** 3
    return {"gpu": dev, "seconds": round(secs, 1), "peak_vram_gib": round(peak, 2),
            "note": "peak over what the GPU held before; first run includes the cold load"}


# ------------------------------------------------------------------ LLM
def _stream(url, key, model, out, i):
    body = json.dumps({"model": model, "stream": True, "max_tokens": 256,
                       "messages": [{"role": "user", "content": PROMPT_LLM}]}).encode()
    hdr = {"Content-Type": "application/json"}
    if key:
        hdr["Authorization"] = "Bearer " + key
    t0 = time.time()
    first, n = None, 0
    try:
        with urllib.request.urlopen(urllib.request.Request(url + "/chat/completions", body, hdr), timeout=180) as r:
            for raw in r:
                line = raw.decode("utf-8", "replace").strip()
                if not line.startswith("data:") or line.endswith("[DONE]"):
                    continue
                try:
                    d = json.loads(line[5:])
                except ValueError:
                    continue
                ch = (d.get("choices") or [{}])[0].get("delta") or {}
                if ch.get("content") or ch.get("reasoning_content") or ch.get("reasoning"):
                    n += 1
                    if first is None:
                        first = time.time() - t0
        out[i] = {"ttft": first, "tokens": n, "seconds": time.time() - t0}
    except Exception as e:                                    # noqa: BLE001
        out[i] = {"error": f"{type(e).__name__}"}


def _bench_llm(job, ctx, model_name):
    url, key = jobs._llm()
    if not url:
        raise jobs.JobError("targets.toml has no homelab LLM")
    levels = []
    for n in (job.get("options") or {}).get("clients") or CLIENTS:
        if ctx.cancelled():
            break
        ctx.progress(len(levels) / len(CLIENTS), f"{n} client(s)")
        out = {}
        ts = [threading.Thread(target=_stream, args=(url, key, model_name, out, i), daemon=True) for i in range(n)]
        t0 = time.time()
        for t in ts:
            t.start()
        for t in ts:
            t.join(240)
        wall = time.time() - t0
        ok = [r for r in out.values() if "error" not in r and r.get("tokens")]
        if not ok:
            raise jobs.JobError(f"no answers at {n} client(s): " + ", ".join(sorted({r.get('error', '?') for r in out.values()})))
        toks = sum(r["tokens"] for r in ok)
        per = [r["tokens"] / max(1e-3, r["seconds"] - (r["ttft"] or 0)) for r in ok]
        levels.append({"clients": n, "ok": len(ok), "aggregate_tok_s": round(toks / wall, 1),
                       "per_stream_tok_s": round(sum(per) / len(per), 1),
                       "ttft_s": round(sorted(r["ttft"] or 0 for r in ok)[len(ok) // 2], 2)})
        ctx.log(f"{n} client(s): {levels[-1]['aggregate_tok_s']} tok/s in all, {levels[-1]['per_stream_tok_s']} each, "
                f"first token {levels[-1]['ttft_s']} s")
    return {"served": model_name, "concurrency": levels,
            "note": "streamed chat completions, 256-token replies; tokens counted per streamed chunk"}


# ------------------------------------------------------------------ voice
def _bench_voice(job, ctx):
    src = ctx.source("bromigos-voice")
    if src is None:
        raise jobs.JobError("no voice source in homelab.toml")
    t0 = time.time()
    hdr = {"Content-Type": "application/json"}
    body = json.dumps({"text": LINE}).encode()
    with urllib.request.urlopen(urllib.request.Request(src.endpoint.rstrip("/") + "/v1/tts", body, hdr),
                                timeout=120) as r:
        audio = r.read()
    secs = time.time() - t0
    dur = max(0.0, (len(audio) - 44) / (24000 * 2))           # 24 kHz 16-bit mono WAV
    return {"seconds": round(secs, 2), "audio_s": round(dur, 2),
            "realtime_x": round(dur / secs, 2) if secs else None,
            "note": "one line, the service's default voice; its models stay loaded"}


def run_bench(job, ctx):
    ok, why = enabled()
    if not ok:
        raise jobs.JobError(why)
    target = (job.get("model") or "").strip()
    if not target:
        raise jobs.JobError("which model? --model <catalog key> (bromigos lab models tiers <capability> lists them), "
                            "or --model llm / voice for what the lab serves")
    cat = C.load()
    row = {"t": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "key": target, "catalog": cat.version}
    if target in ("llm", "voice"):
        res = _bench_llm(job, ctx, job.get("served") or "") if target == "llm" else _bench_voice(job, ctx)
        if target == "llm" and not res.get("served"):
            res["served"] = "(the endpoint's default model)"
    else:
        v = cat.variant(target)
        if v is None:
            raise jobs.JobError(f"{target} isn't in the catalog (model/variant, e.g. qwen-image-2.1/int8)")
        cap = v.model.caps[0]
        row["capability"] = cap
        if v.runtime == "comfyui":
            res = _bench_comfy(job, ctx, v, cap)
        elif v.runtime in ("vllm", "sglang", "llama.cpp", "ollama") and cap in C.SERVED:
            res = _bench_llm(job, ctx, v.model.repo or v.weights)
        elif cap in ("tts", "stt"):
            res = _bench_voice(job, ctx)
        else:
            raise jobs.JobError(f"{target} runs on {v.runtime}: the bench has no test for it yet")
    row.update(res)
    row["ok"] = True
    record(row)
    out = ctx.out(stem=target.replace("/", "-"), ext=".json")
    with open(out, "w") as f:
        json.dump(row, f, indent=1)
    ctx.note(**{k: v for k, v in row.items() if k in ("seconds", "peak_vram_gib", "realtime_x")})
    return [out]


def register():
    jobs.register_kind(jobs.Kind(
        "catalog-bench", "Catalog bench", "measure a catalog model on the lab: one fixed test, peak VRAM and speed",
        run_bench, (), vram_mib=4096, gpu="media", heavy=True, takes=("model",), ext=".json", order=90,
        available=enabled,
        vram_note="the queue's gate; the bench checks the candidate's own peak against the GPU before it loads"))


register()
