"""The lab's GPUs and models: what's installed and loaded where, with VRAM, and loading or
unloading them (`bromigos lab models`, the console's GPU card, the Lab deck).

Read from the capabilities, whatever runs the lab:
  * GPUs: a `gpus` capability when an adapter provides one; else NVIDIA's DCGM exporter
    through the metrics capability (per GPU: VRAM, use, temperature, power, the pod using
    it); else the media servers' own device (ComfyUI's /system_stats).
  * models: ComfyUI's model files (installed) and what it holds in VRAM, the voice
    service's resident TTS and STT models, Ollama's pulled and loaded models (with VRAM),
    the OpenAI-compatible and LiteLLM servers' served models.

Load and unload go through the server's own API, never a restart: ComfyUI's POST /free
(the same call its idle-unload sidecar makes, applied between prompts so no job is cut),
Ollama's keep_alive. The voice service's models are never unloaded from here: VECTOR
speaks through them. Adding or removing models changes the lab (Phase 2: the homelab repo).
"""
import re

from . import caps, registry

GIB = 1024 ** 3
MIB = 1024 ** 2
COMFY_FOLDERS = ("checkpoints", "diffusion_models", "unet", "unet_gguf", "text_encoders", "clip_gguf", "vae", "loras",
                 "controlnet", "upscale_models", "clip_vision", "rmbg", "background_removal", "audio_encoders")
MODEL_EXT = (".safetensors", ".gguf", ".ckpt", ".pt", ".pth", ".bin", ".onnx", ".sft")


def _short_pod(pod):
    """vllm-llama-5d8f7c9b6c-x2k4q -> vllm-llama (a Deployment's pod name, its hashes off)."""
    return re.sub(r"(-[a-z0-9]{8,10})?-[a-z0-9]{5}$", "", pod or "")


def _num(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def gpus():
    """[{name, host, model, uuid, vram_used, vram_total (bytes; None on unified memory),
    util_pct, temp_c, power_w, holds: [str], source}]."""
    if "gpus" in registry.CAPABILITIES and caps.available("gpus"):
        r = caps.collect("gpus")
        return [dict(g, holds=list(g.get("holds") or [])) for g in r["items"]]
    out = {}
    if caps.available("metrics"):
        fields = {"DCGM_FI_DEV_FB_USED": "fb_used", "DCGM_FI_DEV_FB_FREE": "fb_free", "DCGM_FI_DEV_GPU_UTIL": "util_pct",
                  "DCGM_FI_DEV_GPU_TEMP": "temp_c", "DCGM_FI_DEV_POWER_USAGE": "power_w"}
        for q, f in fields.items():
            r = caps.metrics(q, timeout=6)
            for x in r["items"]:
                lb = x["labels"]
                host = lb.get("Hostname") or lb.get("hostname") or lb.get("instance") or "?"
                key = lb.get("UUID") or f"{host}:{lb.get('gpu', '0')}"
                g = out.setdefault(key, {"name": f"{(lb.get('modelName') or 'GPU').replace('NVIDIA ', '')}",
                                         "host": host, "model": lb.get("modelName"), "uuid": lb.get("UUID"),
                                         "index": lb.get("gpu"), "driver": lb.get("DCGM_FI_DRIVER_VERSION"),
                                         "holds": [], "source": "metrics"})
                g[f] = _num(x["value"])
                pod = lb.get("exported_pod") or lb.get("pod_name")
                if pod and lb.get("exported_namespace") != lb.get("namespace"):
                    p = f"{lb.get('exported_namespace')}/{_short_pod(pod)}" if lb.get("exported_namespace") else _short_pod(pod)
                    if p not in g["holds"]:
                        g["holds"].append(p)
        unified = {}
        for g in out.values():
            used, free = g.pop("fb_used", None), g.pop("fb_free", None)
            g["vram_used"] = used * MIB if used is not None else None
            g["vram_total"] = (used + free) * MIB if used is not None and free is not None else None
            if g["vram_total"] is None:
                unified.setdefault(g["host"], []).append(g)
        if unified:
            _unified_memory(unified)
        _gpu_pods(out.values())
        _pairs(list(out.values()))
    m = caps.media()
    for x in m["items"]:
        dev = re.sub(r"^cuda:\d+\s+", "", (x.get("gpu") or "")).split(" : ")[0].strip()   # "cuda:0 NVIDIA … : cudaMallocAsync"
        name = re.sub(r"NVIDIA\s+|GeForce\s+", "", dev)
        match = [g for g in out.values() if name and (g["name"] or "").replace("GeForce ", "") in name]
        if len(match) == 1:
            g = match[0]
        else:
            g = out.setdefault(f"media:{x['source']}", {"name": name or "GPU", "host": x["source"], "model": dev,
                                                        "uuid": None, "holds": [], "source": x["source"],
                                                        "vram_used": None, "vram_total": None})
            if x.get("vram_total"):
                g["vram_total"] = x["vram_total"]
                g["vram_used"] = x["vram_total"] - (x.get("vram_free") or 0)
        g["media"] = x["source"]
        g["vram_free_media"] = x.get("vram_free")
        tag = f"{x['source']} (ComfyUI)"
        if tag not in g["holds"] and not any(h.endswith("/comfyui") or h == "comfyui" for h in g["holds"]):
            g["holds"].append(tag)
    for g in out.values():
        g["name"] = (g.get("name") or "GPU").replace("GeForce ", "")
    return sorted(out.values(), key=lambda g: (g.get("vram_total") is None, -(g.get("vram_total") or 0), g["host"]))


def _unified_memory(by_host):
    """GPUs with no framebuffer of their own (a DGX Spark's GB10 shares the node's memory):
    their memory is the node's, from node-exporter, marked unified."""
    tot, avail = {}, {}
    for q, into in (("node_memory_MemTotal_bytes * on(instance) group_left(nodename) node_uname_info", tot),
                    ("node_memory_MemAvailable_bytes * on(instance) group_left(nodename) node_uname_info", avail)):
        for x in caps.metrics(q, timeout=6)["items"]:
            n = x["labels"].get("nodename")
            if n and x["value"] is not None:
                into[n] = x["value"]
    for host, gs in by_host.items():
        for g in gs:
            g["unified"] = True
            if host in tot:
                g["vram_total"] = tot[host]
                g["vram_used"] = tot[host] - avail[host] if host in avail else None


def _gpu_pods(gs):
    """Every pod that asks for a GPU, by node (kube-state-metrics' resource requests): what
    holds each GPU, more than DCGM's one pod per device. Items [console] hide matches stay off."""
    from .console import _visible, hidden
    pats = hidden()
    r = caps.metrics('kube_pod_container_resource_requests{resource=~"nvidia_com_gpu.*"} > 0', timeout=6)
    by = {}
    for x in r["items"]:
        lb = x["labels"]
        if not lb.get("node") or not _visible({"name": lb.get("pod"), "namespace": lb.get("namespace")}, pats):
            continue
        p = f"{lb.get('namespace')}/{_short_pod(lb.get('pod'))}"
        if p not in by.setdefault(lb["node"], []):
            by[lb["node"]].append(p)
    for g in gs:
        if g["host"] in by:
            g["holds"] = sorted(by[g["host"]])
        else:
            g["holds"] = [h for h in g["holds"] if _visible({"name": h.split("/")[-1], "namespace": h.split("/")[0]}, pats)]


def _pairs(gs):
    """A model served across several GPUs (tensor parallel: vllm-llama-head and vllm-llama-worker
    on two nodes) is named once, as a group, on each of them."""
    base = {}
    for g in gs:
        for h in g.get("holds") or []:
            b = re.sub(r"-(head|worker|leader|follower|rank-?\d+|\d+)$", "", h)
            if b != h:
                base.setdefault(b, []).append(g)
    for b, members in base.items():
        if len(members) > 1:
            for g in members:
                g["group"] = f"{b.split('/')[-1]} across {len(members)} GPUs"


def comfy_sources():
    return [a for a in registry.providers("media") if a.type == "comfyui"]


def _comfy(a):
    """One ComfyUI: its device's VRAM, what its own process holds, its queue and its model files."""
    s = a.get_json("/system_stats", timeout=5)
    q = a.get_json("/queue", timeout=5)
    dev = (s.get("devices") or [{}])[0]
    files = {}
    try:
        have = set(a.get_json("/models", timeout=5) or [])
        for f in COMFY_FOLDERS:
            if f in have:
                names = [n for n in (a.get_json(f"/models/{f}", timeout=5) or []) if n.lower().endswith(MODEL_EXT)]
                if names:
                    files[f] = names
    except Exception:
        files = {}
    return {"device": dev.get("name"), "vram_total": dev.get("vram_total"), "vram_free": dev.get("vram_free"),
            "holds": dev.get("torch_vram_total"), "running": len(q.get("queue_running") or []),
            "pending": len(q.get("queue_pending") or []), "files": files,
            "version": (s.get("system") or {}).get("comfyui_version")}


def inventory():
    """{"gpus": [...], "servers": [{source, kind, up, detail, models: [{name, installed, loaded,
    vram (bytes or None), where, can: [load, unload], note}]}], "errors": {...}}"""
    servers, errors = [], {}
    for a in comfy_sources():
        try:
            c = _comfy(a)
        except Exception as e:
            errors[a.name] = caps._why(e)
            servers.append({"source": a.name, "kind": "ComfyUI", "up": False, "detail": errors[a.name], "models": []})
            continue
        held = c["holds"] or 0
        rows = [{"name": "(what ComfyUI holds now)", "installed": True, "loaded": held > 512 * MIB, "vram": held,
                 "state": "holding models" if held > 512 * MIB else "holds nothing",
                 "where": a.name, "can": ["unload"] if held > 512 * MIB else [],
                 "note": "ComfyUI keeps the last job's models until asked or idle (its idle-unload sidecar frees "
                         "them after a few quiet minutes)"}]
        for folder, names in sorted(c["files"].items()):
            for n in names:
                rows.append({"name": n, "folder": folder, "installed": True, "loaded": None, "vram": None,
                             "where": a.name, "can": [], "note": f"{folder}: loaded by the jobs that need it"})
        servers.append({"source": a.name, "kind": "ComfyUI", "up": True,
                        "detail": f"ComfyUI {c['version']} · {'busy' if c['running'] else 'idle'} · queue "
                                  f"{c['pending']} · {(c['vram_free'] or 0) / GIB:.1f} of "
                                  f"{(c['vram_total'] or 0) / GIB:.1f} GiB free on its GPU",
                        "vram_free": c["vram_free"], "vram_total": c["vram_total"], "busy": bool(c["running"]),
                        "models": rows})
    v = caps.voice()
    for x in v["items"]:
        rows = [{"name": m, "installed": True, "loaded": bool(x.get(k)), "vram": None, "where": x["source"],
                 "can": [], "note": "resident: VECTOR speaks and listens through it; never unloaded from here"}
                for m, k in ((x.get("tts_model"), "tts"), (x.get("stt_model"), "stt")) if m]
        servers.append({"source": x["source"], "kind": "voice", "up": x.get("up"),
                        "detail": "TTS and STT, resident", "models": rows})
    errors.update(v["errors"])
    for a in registry.providers("models"):
        try:
            if a.type == "ollama":
                tags = (a.get_json("/api/tags", timeout=6) or {}).get("models", [])
                ps = {m.get("name"): m for m in (a.get_json("/api/ps", timeout=6) or {}).get("models", [])}
                rows = [{"name": t.get("name"), "installed": True, "loaded": t.get("name") in ps,
                         "vram": (ps.get(t.get("name")) or {}).get("size_vram"), "size": t.get("size"),
                         "where": a.name, "can": ["unload"] if t.get("name") in ps else ["load"],
                         "note": ""} for t in tags]
                servers.append({"source": a.name, "kind": "Ollama", "up": True,
                                "detail": f"{len(ps)} loaded of {len(tags)}", "models": rows})
            else:
                ms = a.models()
                rows = [{"name": m.get("name"), "installed": True, "loaded": bool(m.get("up")), "vram": None,
                         "where": a.name, "can": [],
                         "note": "served for the server's life; changing it is a deployment (Phase 2)"} for m in ms]
                kind = "LiteLLM" if a.type == "litellm" else "vLLM / OpenAI-compatible"
                servers.append({"source": a.name, "kind": kind, "up": True,
                                "detail": f"{sum(1 for r in rows if r['loaded'])} of {len(rows)} up", "models": rows})
        except Exception as e:
            errors[a.name] = caps._why(e)
            servers.append({"source": a.name, "kind": a.type, "up": False, "detail": errors[a.name], "models": []})
    try:
        g = gpus()
    except Exception as e:
        g, errors["gpus"] = [], caps._why(e)
    return {"gpus": g, "servers": servers, "errors": errors}


class Refused(Exception):
    pass


def _find(name, source=None):
    """(adapter, kind) for a model name or a source name."""
    for a in registry.instances():
        if source and a.name != source:
            continue
        if a.name == name and "voice" in a.caps:
            return a, "voice"
        if a.name == name or (a.type == "comfyui" and name in ("comfyui", a.name)):
            return a, "source"
    for a in registry.providers("models"):
        if source and a.name != source:
            continue
        if a.type == "ollama":
            try:
                tags = [t.get("name") for t in (a.get_json("/api/tags", timeout=6) or {}).get("models", [])]
            except Exception:
                continue
            if name in tags or name + ":latest" in tags:
                return a, "ollama"
        else:
            try:
                if name in [m.get("name") for m in a.models()]:
                    return a, "served"
            except Exception:
                pass
    for x in caps.voice()["items"]:
        if name in (x.get("tts_model"), x.get("stt_model"), x["source"]):
            return x, "voice"
    for a in comfy_sources():
        try:
            c = _comfy(a)
        except Exception:
            continue
        if any(name == n or name == n.rsplit("/", 1)[-1] for ns in c["files"].values() for n in ns):
            return a, "comfy-file"
    return None, None


def unload(name, source=None):
    """-> a plain-words result. Raises Refused for what can't or mustn't be unloaded."""
    a, kind = _find(name, source)
    if a is None:
        raise Refused(f"no model or server named {name!r} (bromigos lab models lists them)")
    if kind == "voice":
        raise Refused("the voice service's models stay loaded: VECTOR speaks and listens through them, and the "
                      "lab console never unloads, stops or restarts it")
    if kind == "served":
        raise Refused(f"{name} is served by {a.name} for the server's life (vLLM loads one model at start); "
                      "stopping it is a deployment change (Phase 2, through the homelab repo)")
    if kind in ("source", "comfy-file") and getattr(a, "type", "") == "comfyui":
        a.request("/free", data={"unload_models": True, "free_memory": True}, method="POST", timeout=30, raw=True)
        return (f"asked {a.name} to unload its models (POST /free: applied between prompts, so a running job "
                "finishes first; the next job loads what it needs)")
    if kind == "ollama":
        a.request("/api/generate", data={"model": name, "keep_alive": 0}, method="POST", timeout=60, raw=True)
        return f"{name} unloaded from {a.name}"
    raise Refused(f"{name}: nothing to unload")


def load(name, source=None, keep="30m"):
    a, kind = _find(name, source)
    if a is None:
        raise Refused(f"no model named {name!r} (bromigos lab models lists them)")
    if kind == "ollama":
        a.request("/api/generate", data={"model": name, "keep_alive": keep}, method="POST", timeout=600, raw=True)
        return f"{name} loaded on {a.name} (kept {keep} after its last use)"
    if kind in ("source", "comfy-file"):
        raise Refused("ComfyUI loads a model when a job needs it; there's nothing to load ahead (a cold start "
                      "costs little: the weights come off the node's NVMe). Submit the job: bromigos lab run …")
    if kind == "voice":
        raise Refused("the voice service's models are always loaded")
    if kind == "served":
        raise Refused(f"{name} is already served by {a.name}")
    raise Refused(f"{name}: nothing to load")
