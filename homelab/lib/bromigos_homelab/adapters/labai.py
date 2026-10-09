"""AI services: vLLM's own numbers (models), Open WebUI and SearXNG (apps), an OCR model (ocr,
apps, and the `ocr` job kind), and any GPU app on Kubernetes (`workload`: apps).

    [[source]]
    type = "vllm"                       # every vLLM in the metrics source (vllm:* series), or one
    # endpoint = "http://vllm.lab:8000" # server's own /metrics (or service = "ns/name:8000")
    # queue_warn = 8                    # the doctor: requests waiting

    [[source]]
    type = "open-webui"                 # or "searxng": endpoint, else their pods (namespace = "…")
    endpoint = "http://chat.lab"

    [[source]]
    type = "ocr"
    via = "llm"                         # through the lab's LLM gateway (targets.toml's homelab llm)
    model = "ocr"                       # the OCR model's name there
    # endpoint = "http://ocr.lab:8000"  # or the OCR server itself (OpenAI-compatible, e.g. vLLM)
    # namespace = "ocr"                 # its pods, for health when the endpoint isn't reachable

    [[source]]
    name = "video-gen"
    type = "workload"                   # an app known by its pods (and their GPU, from DCGM)
    namespace = "video-gen"
    kind = "video"

vLLM's records: per model, requests a minute and output tokens a second (the metrics source's
rate, or two reads of the server's own counters), requests running and waiting (the queue),
and the KV cache's use. The `ocr` job kind (bromigos lab run ocr --input FILE) turns a PDF
(each page, rendered with pdftoppm) or an image into text.
"""
import base64
import os
import tempfile
import time
import urllib.request

from .. import registry
from ..registry import Unreachable, register
from . import labcommon as L

# ------------------------------------------------------------------ vLLM


def vllm_records(samples, prev=None, now=None):
    """models records from a vLLM /metrics page (parse_prom). prev: {model: (t, gen, req)} from
    the last read, for rates; returns (records, the new prev)."""
    now = now or time.time()
    by = {}

    def add(name, field, v, mode="sum"):
        for s in samples:
            if s["name"] != name:
                continue
            m = s["labels"].get("model_name") or "?"
            d = by.setdefault(m, {})
            d[field] = (d.get(field) or 0) + s["value"] if mode == "sum" else max(d.get(field) or 0, s["value"])
    add("vllm:num_requests_running", "running", None)
    add("vllm:num_requests_waiting", "waiting", None)
    add("vllm:kv_cache_usage_perc", "kv", None, "max")
    add("vllm:gpu_cache_usage_perc", "kv", None, "max")
    add("vllm:generation_tokens_total", "gen", None)
    add("vllm:request_success_total", "req", None)
    out, nxt = [], {}
    for m, d in sorted(by.items()):
        tps = rpm = None
        p = (prev or {}).get(m)
        if p and now > p[0] and d.get("gen") is not None and d.get("gen") >= p[1]:
            tps = (d["gen"] - p[1]) / (now - p[0])
            rpm = (d.get("req", 0) - p[2]) / (now - p[0]) * 60
        nxt[m] = (now, d.get("gen") or 0, d.get("req") or 0)
        out.append(model_record(m, d.get("running"), d.get("waiting"), d.get("kv"), tps, rpm))
    return out, nxt


def model_record(model, running, waiting, kv, tps, rpm, queue_warn=8):
    return {"name": model.rsplit("/", 1)[-1], "model": model, "up": True, "requests_per_min": rpm, "tokens_per_s": tps,
            "running": int(running) if running is not None else None,
            "waiting": int(waiting) if waiting is not None else None,
            "kv_cache_pct": round(kv * 100, 1) if kv is not None else None,
            "state": "warn" if (waiting or 0) >= queue_warn or (kv or 0) >= 0.95 else "ok"}


def vllm_findings(models, queue_warn=8, source=None):
    out = []
    for m in models:
        if (m.get("waiting") or 0) >= queue_warn:
            out.append(L.finding(f"models.{m['name']}.queue", f"{m['name']}: queue", "warn",
                                 f"{m['waiting']} requests waiting, {m.get('running') or 0} running",
                                 "More requests arrive than it serves: they wait. Lower concurrent clients, or "
                                 "give it more replicas or a smaller model.", source))
        if (m.get("kv_cache_pct") or 0) >= 95:
            out.append(L.finding(f"models.{m['name']}.kv", f"{m['name']}: KV cache", "warn",
                                 f"{m['kv_cache_pct']:.0f}% used",
                                 "Its KV cache is full: new requests wait or get preempted. Shorter contexts, fewer "
                                 "parallel requests, or more GPU memory for it.", source))
    if models and not out:
        out.append(L.finding("models.vllm", "vLLM", "ok", ", ".join(
            f"{m['name']}: {m.get('running') or 0} running, {m.get('waiting') or 0} waiting" for m in models[:4]),
            source=source))
    return out


@register
class VLLM(L.LabAdapter):
    type = "vllm"
    provides = ("models",)
    default_ports = (8000,)
    supersedes = ("openai",)            # setup: an endpoint that is vLLM is this, not a plain openai

    def __init__(self, source):
        super().__init__(source)
        self._prev = {}

    def probe(self):
        return b"vllm:" in self.request("/metrics", timeout=3, raw=True)

    @classmethod
    def detect(cls, d):
        return [{"type": "vllm"}] if d.has_metric("vllm:num_requests_running") else []

    def models(self):
        qw = int(self.opt("queue_warn", 8))
        if self.has_web():
            if not self._prev:                       # counters need two reads for a rate
                _, self._prev = vllm_records(L.parse_prom(self.fetch("/metrics", raw=True)))
                time.sleep(float(self.opt("sample_s", 2)))
            samples = L.parse_prom(self.fetch("/metrics", raw=True))
            recs, self._prev = vllm_records(samples, self._prev)
            for r in recs:
                r["state"] = model_record(r["model"], r["running"], r["waiting"],
                                          (r["kv_cache_pct"] or 0) / 100, None, None, qw)["state"]
            return recs
        run = L.keyed(L.mq("sum by (model_name)(vllm:num_requests_running)"), "model_name")
        if not run:
            raise Unreachable(f"{self.name}: no vllm:* series in the metrics source (and no endpoint)")
        wait = L.keyed(L.mq_soft("sum by (model_name)(vllm:num_requests_waiting)"), "model_name")
        kv = L.keyed(L.mq_soft("max by (model_name)(vllm:kv_cache_usage_perc or vllm:gpu_cache_usage_perc)"), "model_name")
        tps = L.keyed(L.mq_soft("sum by (model_name)(rate(vllm:generation_tokens_total[2m]))"), "model_name")
        rpm = L.keyed(L.mq_soft("sum by (model_name)(rate(vllm:request_success_total[2m]))*60"), "model_name")
        return [model_record(m, run.get(m), wait.get(m), kv.get(m), tps.get(m), rpm.get(m), qw) for m in sorted(run)]

    def doctor(self):
        return vllm_findings(self.models(), int(self.opt("queue_warn", 8)), self.name)


# ------------------------------------------------------------------ Open WebUI, SearXNG


@register
class OpenWebUI(L.AppAdapter):
    type = "open-webui"
    hints = ("chat", "openwebui", "webui")  # setup --ingress: host names that suggest it
    kind = "chat UI"
    default_ports = (8080, 3000)
    pod_selector = "app.kubernetes.io/component=openwebui"

    def probe(self):
        d = self.request("/health", timeout=3)
        return isinstance(d, dict) and d.get("status") is True and "version" in (self.request("/api/version", timeout=3) or {})

    def check(self):
        d = self.fetch("/health", timeout=5)
        return isinstance(d, dict) and d.get("status") is True, ""

    def version(self):
        return (self.fetch("/api/version", timeout=5) or {}).get("version")


@register
class SearXNG(L.AppAdapter):
    type = "searxng"
    hints = ("search",)  # setup --ingress: host names that suggest it
    kind = "search"
    default_ports = (8080, 8888)
    health_path = "/healthz"
    pod_selector = "app.kubernetes.io/name=searxng"

    def probe(self):
        return self.request("/healthz", timeout=3, raw=True).strip() == b"OK" and \
            "engines" in (self.request("/config", timeout=3) or {})

    def check(self):
        b = self.fetch("/healthz", raw=True, timeout=5).strip()
        return b == b"OK", "" if b == b"OK" else b.decode("utf-8", "replace")[:80]

    def version(self):
        return (self.fetch("/config", timeout=5) or {}).get("version")


# ------------------------------------------------------------------ a GPU app on Kubernetes


@register
class Workload(L.AppAdapter):
    """Any app known by its pods: `namespace` (all its pods) or `selector`, with `kind` saying what
    it is; up when every pod is ready; the GPU memory DCGM attributes to its namespace. An
    `endpoint` with `health_path` adds its own health answer."""
    type = "workload"

    def __init__(self, source):
        super().__init__(source)
        self.kind = source.get("kind") or "app"
        self.health_path = source.get("health_path") or "/health"

    def configured(self):
        return bool(self.endpoint or self.opts.get("namespace") or self.opts.get("selector"))


# ------------------------------------------------------------------ OCR

OCR_PROMPT = "Read this page. Output all of its text, in reading order, keeping paragraphs and tables. Output only the text."


@register
class OCR(L.AppAdapter):
    type = "ocr"
    provides = ("ocr", "apps")
    kind = "OCR"

    _usable = None

    def _via_llm(self):
        return not self.endpoint and self.opt("via", "llm") == "llm"

    def _api(self):
        """(base URL, headers, model) to send pages to."""
        if self.endpoint:
            model = self.opt("model")
            if not model:
                ids = [m.get("id") for m in (self.fetch("/v1/models", timeout=6) or {}).get("data") or []]
                model = ids[0] if ids else None
            return self.endpoint, self.auth_headers(), model
        try:
            from .. import jobs
            url, key = jobs._llm()
        except ImportError:
            url, key = None, None
        if not url:
            raise Unreachable(f"{self.name}: no endpoint, and targets.toml has no homelab LLM to reach the model through")
        return url, ({"Authorization": f"Bearer {key}"} if key else {}), self.opt("model", "ocr")

    def check(self):
        if self.endpoint:
            self.fetch("/health", raw=True, timeout=5)
            return True, ""
        url, headers, model = self._api()
        req = urllib.request.Request(url.rstrip("/") + ("" if url.rstrip("/").endswith("/v1") else "/v1") + "/models",
                                     headers=headers)
        with urllib.request.urlopen(req, timeout=8, context=self._ctx()) as r:
            import json
            ids = [m.get("id") for m in (json.loads(r.read() or b"{}").get("data") or [])]
        self._usable = model in ids
        if model in ids:
            return True, ""
        return None, f"this machine's LLM key can't use {model} (the gateway serves it {len(ids)} others)"

    def has_web(self):
        return bool(self.endpoint) or self._via_llm()

    def apps(self):
        self._usable = None
        recs = super().apps()
        if self._usable is False and recs[0].get("state") != "not deployed":
            recs[0]["state"] = "warn"            # it runs, but jobs from here can't reach it
        return recs

    def doctor(self):
        rec = self.apps()[0]
        if self._usable is False:
            return [self.finding(f"ocr.{self.name}", f"{self.name} (OCR)", "warn", rec["detail"],
                                 f"OCR jobs from this machine go through the lab's LLM gateway, and its key here isn't "
                                 f"allowed {self.opt('model', 'the model')}. Add the model to that key's models in the "
                                 "gateway, or give this source the OCR server's own endpoint.")]
        return super().doctor()

    def ocr(self):
        rec = self.apps()[0]
        return [{"name": self.name, "endpoint": self.endpoint or None, "up": rec["up"],
                 "model": self.opt("model"), "via": "endpoint" if self.endpoint else self.opt("via", "llm"),
                 "detail": rec["detail"], **({"state": rec["state"]} if rec.get("state") else {})}]

    def page_text(self, data, mime="image/png", timeout=300):
        """One page image -> its text, through the OpenAI-compatible chat API (an image_url part)."""
        import json
        url, headers, model = self._api()
        base = url.rstrip("/")
        base = base if base.endswith("/v1") else base + "/v1"
        body = {"model": model, "temperature": 0, "max_tokens": int(self.opt("max_tokens", 4096)),
                "messages": [{"role": "user", "content": [
                    {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{base64.b64encode(data).decode()}"}},
                    {"type": "text", "text": self.opt("prompt", OCR_PROMPT)}]}]}
        req = urllib.request.Request(base + "/chat/completions", data=json.dumps(body).encode(), method="POST",
                                     headers=dict(headers, **{"Content-Type": "application/json"}))
        with urllib.request.urlopen(req, timeout=timeout, context=self._ctx()) as r:
            d = json.loads(r.read() or b"{}")
        return ((d.get("choices") or [{}])[0].get("message") or {}).get("content") or ""


_IMAGE = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp",
          ".tif": "image/tiff", ".tiff": "image/tiff", ".bmp": "image/bmp", ".gif": "image/gif"}


def ocr_pages(path, run, tmpdir, dpi=150):
    """[(image path, mime)] for a file: a PDF's pages rendered with pdftoppm, or the image itself."""
    ext = os.path.splitext(path)[1].lower()
    if ext in _IMAGE:
        return [(path, _IMAGE[ext])]
    if ext != ".pdf":
        raise ValueError(f"{os.path.basename(path)}: not a PDF or an image")
    p = run(["pdftoppm", "-r", str(dpi), "-png", path, os.path.join(tmpdir, "page")], 600)
    if p.returncode != 0:
        raise ValueError("pdftoppm couldn't render it: " + (p.stderr or "").strip()[-200:])
    pages = sorted(f for f in os.listdir(tmpdir) if f.startswith("page") and f.endswith(".png"))
    return [(os.path.join(tmpdir, f), "image/png") for f in pages]


def run_ocr(job, ctx):
    """The `ocr` job kind: each input (a PDF or an image) to a .txt, page by page."""
    from .. import jobs
    ins = jobs._inputs(job, 1, "a PDF or an image (--input FILE)")
    srcs = [a for a in registry.providers("ocr") if a.type == "ocr"]
    if not srcs:
        raise jobs.JobError("no ocr source in homelab.toml")
    a = srcs[0]
    outs = []
    for path in ins:
        with tempfile.TemporaryDirectory(prefix="bromigos-ocr-") as tmp:
            try:
                pages = ocr_pages(path, ctx.run, tmp, int(a.opt("dpi", 150)))
            except FileNotFoundError:
                raise jobs.JobError("PDFs need pdftoppm (poppler)") from None
            except ValueError as e:
                raise jobs.JobError(str(e)) from None
            texts = []
            for i, (img, mime) in enumerate(pages, 1):
                if ctx.cancelled():
                    raise jobs.JobError("cancelled")
                ctx.progress((i - 1) / max(1, len(pages)), f"{os.path.basename(path)}: page {i} of {len(pages)}")
                with open(img, "rb") as f:
                    data = f.read()
                try:
                    texts.append(a.page_text(data, mime).strip())
                except OSError as e:
                    raise jobs.JobError(f"the OCR model didn't answer: {e}") from None
            out = ctx.out(stem=os.path.splitext(os.path.basename(path))[0], ext=".txt")
            with open(out, "w") as f:
                f.write("\n\f\n".join(texts) + "\n")
            ctx.log(f"{os.path.basename(path)}: {len(pages)} page(s), {sum(len(t) for t in texts)} characters")
            outs.append(out)
    ctx.progress(1.0, "done")
    return outs


def _ocr_available():
    import shutil
    srcs = [a for a in registry.providers("ocr") if a.type == "ocr"]
    if not srcs:
        return False, "no ocr source in homelab.toml"
    if not shutil.which("pdftoppm"):
        return True, "images only: PDFs need pdftoppm (poppler)"
    return True, ""


try:                                     # the lab console's job queue (jobs.py), when installed
    from .. import jobs as _jobs
    _jobs.register_kind(_jobs.Kind(
        id="ocr", title="OCR", summary="text from a PDF or an image (the lab's OCR model)", run=run_ocr,
        needs=("ocr",), vram_mib=0, gpu="llm", heavy=False, takes=("input",), ext=".txt",
        available=_ocr_available, vram_note="a resident model: the job adds nothing to the GPU", order=70))
except (ImportError, AttributeError, TypeError):
    pass

