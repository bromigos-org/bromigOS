"""Model servers: LiteLLM, Ollama, and any OpenAI-compatible server (vLLM, llama.cpp,
LM Studio, …). Capability: models.

Load (requests/min, tokens/s) comes from the server itself where it says (Ollama: the
models it holds loaded), else from its Prometheus metrics through the metrics capability
(LiteLLM: litellm_deployment_total_requests_total, litellm_output_tokens_metric_total;
vLLM: vllm:request_success_total, vllm:generation_tokens_total).
"""
from ..registry import Adapter, register


def _metric_by(q, label):
    from .. import caps
    if not caps.available("metrics"):
        return None
    r = caps.metrics(q, timeout=4)
    if not r["ok"]:
        return None
    return {x["labels"].get(label, ""): x["value"] for x in r["items"]}


class _OpenAICompatible(Adapter):
    models_path = "/v1/models"

    def probe(self):
        d = self.get_json(self.models_path, timeout=3)
        return isinstance(d, dict) and isinstance(d.get("data"), list)

    def listed(self):
        return [m.get("id") for m in (self.get_json(self.models_path, timeout=6) or {}).get("data", []) if m.get("id")]


@register
class OpenAI(_OpenAICompatible):
    type = "openai"                  # vLLM, llama.cpp server, LM Studio, anything with /v1/models
    provides = ("models",)
    default_ports = (8000,)

    def models(self):
        rpm = _metric_by("sum by (model_name)(rate(vllm:request_success_total[1m]))*60", "model_name") or {}
        tps = _metric_by("sum by (model_name)(rate(vllm:generation_tokens_total[1m]))", "model_name") or {}
        return [{"name": m, "model": m, "up": True, "requests_per_min": rpm.get(m), "tokens_per_s": tps.get(m)}
                for m in self.listed()]


@register
class LiteLLM(_OpenAICompatible):
    type = "litellm"
    provides = ("models",)
    default_ports = (4000,)

    def probe(self):
        try:
            b = self.request("/health/liveliness", timeout=3, raw=True)
            return b"alive" in b.lower()
        except Exception:
            return False

    def models(self):
        rpm = _metric_by("sum by (model_group)(rate(litellm_deployment_total_requests_total[1m]))*60", "model_group")
        tps = _metric_by("sum by (model_group)(rate(litellm_output_tokens_metric_total[1m]))", "model_group")
        state = _metric_by("min by (model_group)(litellm_deployment_state)", "model_group")   # 0 healthy
        try:
            names = self.listed()
        except Exception:
            if state is None and rpm is None:
                raise
            # no key for /v1/models: the metrics know the model groups
            names = sorted(k for k in (state or rpm or {}) if k)
        rpm, tps = rpm or {}, tps or {}
        out = [{"name": m, "model": m, "up": (state.get(m) == 0) if state and m in state else True,
                "requests_per_min": rpm.get(m, 0.0) if rpm else None,
                "tokens_per_s": tps.get(m, 0.0) if tps else None} for m in names]
        # load the list doesn't name (a wildcard route, unlabelled counters) still counts
        extra_rpm = sum(v for k, v in rpm.items() if k not in names)
        extra_tps = sum(v for k, v in tps.items() if k not in names)
        if extra_rpm or extra_tps:
            if not out:
                out.append({"name": self.name, "model": None, "up": True, "requests_per_min": 0.0, "tokens_per_s": 0.0})
            out[0]["requests_per_min"] = (out[0]["requests_per_min"] or 0.0) + extra_rpm
            out[0]["tokens_per_s"] = (out[0]["tokens_per_s"] or 0.0) + extra_tps
        return out


@register
class Ollama(Adapter):
    type = "ollama"
    provides = ("models",)
    default_ports = (11434,)

    def probe(self):
        d = self.get_json("/api/version", timeout=3)
        return isinstance(d, dict) and "version" in d

    def models(self):
        tags = [m.get("name") for m in (self.get_json("/api/tags", timeout=6) or {}).get("models", [])]
        loaded = {m.get("name") for m in (self.get_json("/api/ps", timeout=6) or {}).get("models", [])}
        # Ollama has no request counters: a loaded model reads as up, its load unknown
        return [{"name": n, "model": n, "up": n in loaded, "requests_per_min": None, "tokens_per_s": None,
                 "loaded": n in loaded} for n in tags]
