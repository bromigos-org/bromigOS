"""Lab job kinds and presets: what `bromigos lab run <kind> [preset]` can make on the lab's
GPUs, what each needs, and how it runs. The queue (jobqueue.py, bromigos-lab.service) runs
them one heavy job at a time, gated on free VRAM. docs/homelab.md, "The lab console".

A kind (bromigOS's, or a homelab-adapter extension's: register_kind):

    jobs.register_kind(jobs.Kind(
        id="ocr", title="OCR", summary="text from an image or a PDF",
        needs=("ocr",),          # capabilities that must have a provider, else "not available: …"
        vram_mib=0,              # peak VRAM the job adds on the lab GPU, measured (0: none)
        gpu="media",             # the capability whose source owns that GPU ("media": ComfyUI's)
        heavy=False,             # heavy jobs run one at a time
        takes=("input",),        # what `lab run` takes: prompt, input, text, voice, model, aspect
        ext=".txt",              # what a result file is
        run=run_ocr))            # run(job, ctx) -> [output paths]; raise JobError("plain words")

run gets the job (its id, kind, preset, prompt, inputs, text, options…) and a context:

    ctx.out(stem=None, ext=None)   a new path in ~/Pictures/bromigos/lab/<kind>/
    ctx.log(text)                  a line in the job's log (`bromigos lab jobs logs ID`)
    ctx.progress(fraction, text)   0..1, shown in the dashboard and the deck
    ctx.cancelled()                True once the job is cancelled: stop soon
    ctx.run(argv, timeout)         a command, killed when the job is cancelled -> CompletedProcess
    ctx.source(type)               a configured adapter by type (bromigos_homelab.source_of)
    ctx.cloud                      whether this job may use paid providers (`lab run --cloud`)

Homelab first: no kind reaches a paid provider unless the job says cloud (the user passed
--cloud). The image kinds go through `bromigos art make` (create.toml, targets.toml), never
a second ComfyUI client; voice and transcription through the lab's voice service, which
the queue never stops, restarts or crowds (it keeps [lab] voice_reserve_mib free).
"""
import dataclasses
import json
import os
import shutil
import subprocess
import tempfile
import time
import urllib.error
import urllib.request
import wave

from . import caps, config, registry


class JobError(Exception):
    """A job failed for a reason the user can act on (said in plain words)."""


@dataclasses.dataclass
class Kind:
    id: str
    title: str
    summary: str
    run: object = None                 # run(job, ctx) -> [paths]
    needs: tuple = ()
    vram_mib: int = 0
    gpu: str = "media"
    heavy: bool = False
    takes: tuple = ("prompt",)
    ext: str = ".png"
    available: object = None           # () -> (ok, why): beyond needs (a workflow, a backend)
    vram_note: str = ""                # where vram_mib comes from (measured when, on what)
    order: int = 50

    def status(self):
        """(ok, why): whether this kind can run on this lab now (by configuration, not load)."""
        missing = [n for n in self.needs if not caps.available(n)]
        if missing:
            return False, "nothing in homelab.toml provides " + " or ".join(missing)
        if callable(self.available):
            try:
                ok, why = self.available()
            except Exception as e:
                return False, f"{type(e).__name__}: {e}"
            if not ok:
                return False, why
        if self.run is None:
            return False, "no backend yet"
        return True, ""

    def describe(self):
        ok, why = self.status()
        return {"id": self.id, "title": self.title, "summary": self.summary, "needs": list(self.needs),
                "vram_mib": self.vram_mib, "vram_note": self.vram_note, "gpu": self.gpu, "heavy": self.heavy,
                "takes": list(self.takes), "ext": self.ext, "available": ok, "why": why}


@dataclasses.dataclass
class Preset:
    id: str
    kind: str
    title: str
    summary: str
    options: dict = dataclasses.field(default_factory=dict)   # defaults for the job (prompt template, aspect, …)
    disabled: str = ""                 # why it can't run yet ("" = it can when its kind can)

    def describe(self):
        k = KINDS.get(self.kind)
        ok, why = k.status() if k else (False, f"no kind {self.kind!r}")
        if self.disabled:
            ok, why = False, self.disabled
        return {"id": self.id, "kind": self.kind, "title": self.title, "summary": self.summary,
                "options": {k_: v for k_, v in self.options.items() if k_ != "template"},
                "template": self.options.get("template"), "available": ok, "why": why}


KINDS = {}
PRESETS = {}


def register_kind(kind):
    """Add a job kind. The first registration of an id wins: an extension adds kinds, never
    replaces bromigOS's."""
    if not kind.id or not kind.id.replace("-", "").isalnum() or kind.id != kind.id.lower():
        raise ValueError(f"job kind {kind.id!r}: lowercase letters, digits and -")
    KINDS.setdefault(kind.id, kind)
    return KINDS[kind.id]


def register_preset(preset):
    PRESETS.setdefault(preset.id, preset)
    return PRESETS[preset.id]


def kinds():
    registry.instances()               # loads plugins (their register_kind calls)
    return sorted(KINDS.values(), key=lambda k: (k.order, k.id))


def presets():
    registry.instances()
    return sorted(PRESETS.values(), key=lambda p: p.id)


def gib(mib):
    return f"{(mib or 0) / 1024:.1f} GiB"


# ------------------------------------------------------------------ measured VRAM (the lab's 5090)
# Peak VRAM a job adds on the GPU it runs on, over what that GPU holds at rest (the voice
# models, the embeddings server). The queue keeps the most it has seen per kind too
# (~/.local/state/bromigos/lab/vram.json) and gates on whichever is larger.
VRAM = {
    "image": (15450, "Qwen-Image 2.1 int8 (DiT 6.8, encoder 8.7, VAE 0.6 GiB): the 5090 lost at most 15.1 GiB of "
                     "free VRAM over a 1024 px still (2026-10-09); larger stills raise it through vram.json"),
    "image-edit": (15450, "as image (the same model)"),
    "hologram": (15450, "its largest step: the concept image (Qwen-Image 2.1)"),
}


def _measured():
    """share/lab/jobs.toml: the kinds measured by the jobs that built them (video: Wan 2.2), a
    checkout's own copy (next to this code), else the packaged one. An entry there sets its
    kind's VRAM and note."""
    import tomllib
    here = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "share", "lab", "jobs.toml")
    share = os.path.join(os.environ.get("BROMIGOS_SHARE_DIR") or "/usr/share/bromigos", "homelab", "lab", "jobs.toml")
    for path in (here, share):
        try:
            with open(path, "rb") as f:
                kinds = tomllib.load(f).get("kind") or {}
        except (OSError, ValueError):
            continue
        for k, v in kinds.items():
            if isinstance(v, dict) and isinstance(v.get("vram_mib"), int):
                note = " ".join(str(v.get("note") or "").split())
                if v.get("measured"):
                    note = f"{note} (measured {v['measured']})".strip()
                VRAM[k] = (v["vram_mib"], note)
        return


_measured()


# ------------------------------------------------------------------ helpers
def bromigos_bin():
    return os.environ.get("BROMIGOS_BIN") or shutil.which("bromigos") or "/usr/bin/bromigos"


def _art_make(job, ctx, capability, out, inputs=(), prompt=None, aspect=None, extra=(), more=()):
    """One `bromigos art make` through create.toml's providers: on the lab's ComfyUI (no
    credits) unless the job allows the cloud. `more`: further arguments as they are."""
    argv = [bromigos_bin(), "art", "make", capability, "--out", out, "--json"]
    if prompt:
        argv += ["--prompt", prompt]
    for i in inputs:
        argv += ["--input", i]
    if job.get("mask"):
        argv += ["--mask", job["mask"]]
    if aspect:
        argv += ["--aspect", aspect]
    for e in extra:
        argv += ["--extra", e]
    argv += list(more)
    if not ctx.cloud:
        argv += ["--provider", job.get("provider") or "comfyui:homelab", "--max-credits", "0"]
    ctx.log(" ".join(a if " " not in a else repr(a) for a in argv[:4]) + f" … → {os.path.basename(out)}")
    p = ctx.run(argv, timeout=float(job.get("timeout") or 1200))
    try:
        doc = json.loads((p.stdout or "").strip().splitlines()[-1]) if p.stdout.strip() else {}
    except ValueError:
        doc = {}
    if p.returncode != 0 or not os.path.exists(out):
        why = (p.stderr or p.stdout or "").strip().splitlines()
        raise JobError(f"{capability} failed: " + (why[-1][:300] if why else f"exit {p.returncode}"))
    ctx.log(f"made {os.path.basename(out)} on {doc.get('provider', '?')} ({doc.get('model', '?')}), "
            f"{doc.get('credits', 0)} credits, {doc.get('seconds', '?')} s")
    ctx.note(provider=doc.get("provider"), model=doc.get("model"), credits=doc.get("credits"),
             licence=doc.get("licence"))
    return out


def _inputs(job, n=None, what="an input file"):
    ins = [os.path.expanduser(i) for i in job.get("inputs") or []]
    for i in ins:
        if not os.path.isfile(i):
            raise JobError(f"{i} isn't a file")
    if n and len(ins) < n:
        raise JobError(f"this needs {what} (--input FILE)")
    return ins


def _prompt(job, preset_key="template"):
    p = (job.get("prompt") or "").strip()
    tpl = (job.get("options") or {}).get(preset_key)
    if tpl and p:
        return tpl.format(prompt=p, subject=p)
    if tpl and "{" not in tpl:
        return tpl
    return p


# ------------------------------------------------------------------ image kinds (bromigos art make)
def run_image(job, ctx):
    prompt = _prompt(job)
    if not prompt:
        raise JobError("an image needs a prompt (--prompt …)")
    out = ctx.out(ext=".png")
    extra = []
    if (job.get("options") or {}).get("resolution"):
        extra.append(f"resolution={int(job['options']['resolution'])}")
    return [_art_make(job, ctx, "image.generate", out, _inputs(job), prompt,
                      job.get("aspect") or (job.get("options") or {}).get("aspect"), extra)]


def run_edit(job, ctx):
    ins = _inputs(job, 1, "the image to edit")
    prompt = _prompt(job)
    if not prompt:
        raise JobError("an edit needs a prompt saying the change (--prompt …)")
    return [_art_make(job, ctx, "image.edit", ctx.out(ext=".png"), ins[:1], prompt)]


def run_cutout(job, ctx):
    ins = _inputs(job, 1, "the image to cut out")
    return [_art_make(job, ctx, "image.cutout", ctx.out(stem=_stem(ins[0]) + "-cutout", ext=".png"), ins[:1])]


def run_3d(job, ctx):
    ins = _inputs(job, 1, "an image of the object (a cutout works best)")
    return [_art_make(job, ctx, "model3d.generate", ctx.out(stem=_stem(ins[0]), ext=".glb"), ins[:1])]


CLIP_EXT = (".mp4", ".webm", ".mov", ".mkv", ".m4v")


def run_upscale(job, ctx):
    """An image or a clip made larger and sharper on the lab (SeedVR2 7B: bromigos art make
    image.upscale, or video.upscale for a clip, which keeps its frame rate and sound). Option:
    scale (--scale; 2 by default, at most 4, a whole number for a clip); bromigos art lowers it
    when the result would be larger than the workflow makes (docs/art.md)."""
    ins = _inputs(job, 1, "the image or clip to upscale")
    clip = os.path.splitext(ins[0])[1].lower() in CLIP_EXT
    scale = (job.get("options") or {}).get("scale")
    extra = [f"scale={float(scale):g}"] if scale is not None else []
    out = ctx.out(stem=_stem(ins[0]) + "-up", ext=".mp4" if clip else ".png")
    return [_art_make(job, ctx, "video.upscale" if clip else "image.upscale", out, ins[:1], extra=extra)]


def _stem(path):
    return os.path.splitext(os.path.basename(path))[0][:40] or "out"


CONCEPT = ("{subject}. A single object, whole and centred, seen from a three-quarter angle slightly above, on a "
           "plain white background, soft even studio light, clear silhouette, no text, no logo, no other objects.")


def holo_tools():
    """VECTOR's hologram tools and their build venv (bromigos-vector), or (None, None)."""
    tools = next((d for d in (os.environ.get("BROMIGOS_HOLO_TOOLS"), "/usr/lib/bromigos/vector/tools/holo",
                              os.path.expanduser("~/github.com/bromigos-org/vector/tools/holo"))
                  if d and os.path.isfile(os.path.join(d, "make-holo.py"))), None)
    py = next((p for p in (os.environ.get("BROMIGOS_HOLO_PYTHON"),
                           os.path.expanduser("~/.local/share/bromigos/venv/bin/python"))
               if p and os.path.exists(p)), None)
    return tools, py


def run_hologram(job, ctx):
    """concept (a prompt, or the given image) → cutout → 3D mesh → a baked hologram, in its
    own folder: <name>/ with the concept, the cutout, the GLB and NAME.holo.npz."""
    name = "".join(c if c.isalnum() else "-" for c in (job.get("name") or job.get("prompt") or "holo").lower())
    name = "-".join(w for w in name.split("-") if w)[:32] or "holo"
    folder = ctx.out(stem=name, ext="")
    os.makedirs(folder, exist_ok=True)
    ins = _inputs(job)
    outs = []
    if ins:
        concept = ins[0]
    else:
        subject = (job.get("prompt") or "").strip()
        if not subject:
            raise JobError("a hologram needs a subject (--prompt …) or an image (--input FILE)")
        ctx.progress(0.05, "concept")
        concept = _art_make(job, ctx, "image.generate", os.path.join(folder, "concept.png"),
                            prompt=CONCEPT.format(subject=subject), aspect="1:1")
        outs.append(concept)
    if ctx.cancelled():
        return outs
    ctx.progress(0.35, "cutout")
    cut = _art_make(job, ctx, "image.cutout", os.path.join(folder, "cutout.png"), [concept])
    outs.append(cut)
    if ctx.cancelled():
        return outs
    ctx.progress(0.55, "3D")
    glb = _art_make(job, ctx, "model3d.generate", os.path.join(folder, f"{name}.glb"), [cut])
    outs.append(glb)
    if ctx.cancelled():
        return outs
    ctx.progress(0.85, "bake")
    tools, py = holo_tools()
    if not tools or not py:
        ctx.log("bake skipped: VECTOR's hologram tools (bromigos-vector) and their build venv aren't here; "
                "the GLB is made")
        return outs
    parts = os.path.join(folder, "parts.json")
    with open(parts, "w") as f:
        json.dump([{"id": "body", "label": name.upper(), "hint": f"{job.get('prompt') or name}: made on the lab",
                    "bind": "", "rest": True}], f)
    p = ctx.run([py, os.path.join(tools, "make-holo.py"), "--root", folder, "glb", name, glb, parts], timeout=900)
    if p.returncode != 0:
        why = (p.stderr or p.stdout or "").strip().splitlines()
        raise JobError("the bake failed: " + (why[-1][:300] if why else f"exit {p.returncode}"))
    npz = os.path.join(folder, f"{name}.holo.npz")
    if os.path.exists(npz):
        outs.append(npz)
    prev = os.path.join(folder, "previews", f"{name}-parts.png")
    if os.path.exists(prev):
        outs.append(prev)
    ctx.log(f"baked {name}.holo.npz; to add it to your gallery: copy {folder}'s manifest entry and .holo.npz "
            "into ~/.config/bromigos/vector/holo/ (or ask VECTOR to build it in)")
    return outs


# ------------------------------------------------------------------ voice (the lab's voice service)
def _voice_source():
    for a in registry.providers("voice"):
        return a
    raise JobError("nothing in homelab.toml provides a voice service")


def run_voice(job, ctx):
    """Text to a WAV through the lab's voice service: its default (designed) voice, or a
    voice it holds (--voice ID: the 16+ hex id of a stored reference)."""
    text = (job.get("text") or job.get("prompt") or "").strip()
    if not text:
        raise JobError("a voice line needs its text (--text … or --prompt …)")
    if len(text) > 2000:
        raise JobError("that's long for one line: keep it under 2000 characters (split it into several jobs)")
    a = _voice_source()
    out = ctx.out(ext=".wav")
    voice = (job.get("voice") or "").strip()
    t0 = time.time()
    if voice:
        body = json.dumps({"text": text, "voice": voice}).encode()
        req = urllib.request.Request(a.endpoint + "/v1/tts/stream", data=body, method="POST",
                                     headers=dict(a.auth_headers(), **{"Content-Type": "application/json"}))
    else:
        import uuid
        b = uuid.uuid4().hex
        body = (f"--{b}\r\nContent-Disposition: form-data; name=\"text\"\r\n\r\n{text}\r\n--{b}--\r\n").encode()
        req = urllib.request.Request(a.endpoint + "/v1/audio/speech", data=body, method="POST",
                                     headers=dict(a.auth_headers(), **{"Content-Type": f"multipart/form-data; boundary={b}"}))
    rate = 24000
    try:
        with urllib.request.urlopen(req, timeout=120, context=a._ctx()) as r:
            rate = int(r.headers.get("X-Sample-Rate") or 24000)
            pcm = bytearray()
            while True:
                if ctx.cancelled():
                    return []
                chunk = r.read(65536)
                if not chunk:
                    break
                pcm += chunk
    except urllib.error.HTTPError as e:
        raise JobError(f"the voice service said {e.code}" + (" (unknown voice id)" if e.code == 404 else
                                                              " (still loading; try again)" if e.code == 503 else ""))
    except OSError as e:
        raise JobError(f"the voice service didn't answer: {e}")
    if len(pcm) < 2000:
        raise JobError("the voice service answered with no audio")
    with wave.open(out, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(bytes(pcm[: len(pcm) // 2 * 2]))
    secs = len(pcm) / 2 / rate
    ctx.log(f"{secs:.1f} s of speech in {time.time() - t0:.1f} s ({a.name}, {voice or 'its default voice'})")
    ctx.note(provider=a.name, seconds_audio=round(secs, 2))
    txt = os.path.splitext(out)[0] + ".txt"
    with open(txt, "w") as f:
        f.write(text + "\n")
    return [out]


def run_transcribe(job, ctx):
    ins = _inputs(job, 1, "an audio file")
    a = _voice_source()
    src = ins[0]
    wav = src
    tmp = None
    if not src.lower().endswith(".wav"):
        if not shutil.which("ffmpeg"):
            raise JobError("only .wav without ffmpeg (install ffmpeg to transcribe other formats)")
        tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False).name
        p = ctx.run(["ffmpeg", "-nostdin", "-loglevel", "error", "-y", "-i", src, "-ac", "1", "-ar", "16000", tmp],
                    timeout=300)
        if p.returncode != 0:
            raise JobError("ffmpeg couldn't read it: " + (p.stderr or "").strip()[-200:])
        wav = tmp
    try:
        with open(wav, "rb") as f:
            data = f.read()
        q = "?language=" + (job.get("language") or "en")
        req = urllib.request.Request(a.endpoint + "/v1/stt" + q, data=data, method="POST",
                                     headers=dict(a.auth_headers(), **{"Content-Type": "audio/wav"}))
        with urllib.request.urlopen(req, timeout=600, context=a._ctx()) as r:
            doc = json.loads(r.read() or b"{}")
    except OSError as e:
        raise JobError(f"the voice service didn't answer: {e}")
    finally:
        if tmp:
            os.unlink(tmp)
    out = ctx.out(stem=_stem(src), ext=".txt")
    with open(out, "w") as f:
        f.write((doc.get("text") or "").strip() + "\n")
    ctx.log(f"{doc.get('seconds', '?')} s of audio in {doc.get('ms', '?')} ms")
    return [out]


# ------------------------------------------------------------------ batch LLM (the lab's LLM server)
def _llm():
    """(base url, key) of the lab's OpenAI-compatible server: targets.toml's homelab llm."""
    try:
        p = subprocess.run([bromigos_bin(), "target", "resolve", "llm", "--json"], capture_output=True, text=True,
                           timeout=20)
        doc = json.loads(p.stdout)
    except (OSError, subprocess.TimeoutExpired, ValueError):
        doc = {}
    for e in doc.get("entries") or []:
        if e.get("target") == "homelab" and e.get("endpoint"):
            key = ""
            if e.get("key_file"):
                try:
                    with open(os.path.expanduser(e["key_file"])) as f:
                        key = f.read().strip()
                except OSError:
                    key = ""
            return e["endpoint"].rstrip("/"), key
    return None, None


def run_batch_llm(job, ctx):
    """Prompts (one per line of an input file, or --prompt) through the lab's LLM server, to a
    JSONL file of {prompt, answer}."""
    url, key = _llm()
    if not url:
        raise JobError("targets.toml has no homelab LLM (bromigos lab target shows where AI runs)")
    prompts = []
    for i in _inputs(job):
        with open(i) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                if line.startswith("{"):
                    try:
                        line = json.loads(line).get("prompt") or ""
                    except ValueError:
                        pass
                if line:
                    prompts.append(line)
    if job.get("prompt"):
        prompts.append(job["prompt"].strip())
    if not prompts:
        raise JobError("batch-llm needs prompts: --input FILE (one per line) or --prompt …")
    model = job.get("model") or config.setting("lab", "llm_model", "")
    hdr = {"Content-Type": "application/json"}
    if key:
        hdr["Authorization"] = "Bearer " + key
    if not model:
        try:
            with urllib.request.urlopen(urllib.request.Request(url + "/models", headers=hdr), timeout=20) as r:
                model = (json.loads(r.read()).get("data") or [{}])[0].get("id") or ""
        except OSError:
            model = ""
    if not model:
        raise JobError("which model? (--model NAME, or [lab] llm_model in homelab.toml)")
    out = ctx.out(ext=".jsonl")
    system = (job.get("options") or {}).get("system")
    with open(out, "w") as f:
        for n, pr in enumerate(prompts):
            if ctx.cancelled():
                break
            msgs = ([{"role": "system", "content": system}] if system else []) + [{"role": "user", "content": pr}]
            body = json.dumps({"model": model, "messages": msgs}).encode()
            try:
                with urllib.request.urlopen(urllib.request.Request(url + "/chat/completions", data=body, headers=hdr,
                                                                   method="POST"), timeout=600) as r:
                    ans = (json.loads(r.read()).get("choices") or [{}])[0].get("message", {}).get("content")
                err = None
            except urllib.error.HTTPError as e:
                ans, err = None, f"HTTP {e.code}"
            except OSError as e:
                ans, err = None, str(e)[:200]
            f.write(json.dumps({"prompt": pr, "answer": ans, **({"error": err} if err else {})}) + "\n")
            f.flush()
            ctx.progress((n + 1) / len(prompts), f"{n + 1} of {len(prompts)}")
    ctx.note(model=model, prompts=len(prompts))
    ctx.log(f"{len(prompts)} prompts through {model}")
    return [out]


# ------------------------------------------------------------------ video (bromigos art make video.loop)
def run_video(job, ctx):
    """A loop from a still on the lab (Wan 2.2: docs/art.md, "Video loops on a ComfyUI"). Options:
    duration (s, default 5), resolution (720p | 480p), fps, seed, and alpha (luma | stacked | mask:
    the world loop glow-loop.py makes, the raw clip kept beside it as <name>-raw.mp4)."""
    ins = _inputs(job, 1, "the still to animate (a creature on black for a world loop)")
    prompt = _prompt(job)
    if not prompt:
        raise JobError("a video needs a prompt that says how it moves (--prompt …)")
    o = job.get("options") or {}
    more = ["--duration", str(int(o.get("duration") or 5))]
    if o.get("resolution"):
        more += ["--resolution", str(o["resolution"])]
    if o.get("alpha"):
        more += ["--alpha", str(o["alpha"])]
    extra = [f"{k}={int(o[k])}" for k in ("fps", "seed") if o.get(k) is not None]
    out = ctx.out(stem=_stem(ins[0]) + "-loop", ext=".mp4")
    _art_make(job, ctx, "video.loop", out, ins[:1], prompt,
              job.get("aspect") or o.get("aspect"), extra, more)
    raw = out[:-4] + "-raw.mp4"
    return [out, raw] if os.path.exists(raw) else [out]


# ------------------------------------------------------------------ bromigOS's kinds and presets
def _ui(k):
    v = VRAM.get(k)
    return {"vram_mib": v[0], "vram_note": v[1]} if v else {}


for _k in (
    Kind("image", "Image", "a still from a prompt (Qwen-Image 2.1 on the lab)", run_image, ("media",),
         heavy=True, takes=("prompt", "input", "aspect"), order=10, **_ui("image")),
    Kind("image-edit", "Image edit", "change an image as a prompt says (optional --mask)", run_edit, ("media",),
         heavy=True, takes=("prompt", "input", "mask"), order=11, **_ui("image-edit")),
    Kind("cutout", "Cutout", "the subject without its background: a transparent PNG (Lucida)", run_cutout,
         ("media",), heavy=True, takes=("input",), order=12, **_ui("cutout")),
    Kind("3d", "3D model", "a GLB mesh from an image of an object (Pixal3D, shape only)", run_3d, ("media",),
         heavy=True, takes=("input",), ext=".glb", order=13, **_ui("3d")),
    Kind("hologram", "Hologram", "concept → cutout → 3D → a baked hologram for the gallery", run_hologram,
         ("media",), heavy=True, takes=("prompt", "input", "name"), ext="", order=14, **_ui("hologram")),
    Kind("voice", "Voice line", "speech from text, to a WAV (the lab's voice service)", run_voice, ("voice",),
         gpu="voice", takes=("text", "voice"), ext=".wav", order=20,
         vram_note="none added: the voice models stay resident (the 5090's free VRAM didn't move while a 4.6 s line "
                   "was made, 2026-10-09); lines are made one at a time"),
    Kind("transcribe", "Transcribe", "an audio file to text (Whisper on the lab's voice service)", run_transcribe,
         ("voice",), gpu="voice", takes=("input",), ext=".txt", order=21,
         vram_note="none added: Whisper stays resident in the voice service"),
    Kind("upscale", "Upscale", "a sharper, larger image or clip (SeedVR2 7B)", run_upscale, ("media",), heavy=True,
         takes=("input", "scale"), order=15, **_ui("upscale")),
    Kind("batch-llm", "Batch LLM", "many prompts through the lab's LLM server, to JSONL", run_batch_llm, (),
         gpu="llm", takes=("prompt", "input", "model"), ext=".jsonl", order=30,
         vram_note="none added: the LLM servers hold their memory already"),
    Kind("video", "Video", "a seamless loop from an image (Wan 2.2 on the lab)", run_video, ("media",),
         heavy=True, takes=("prompt", "input", "aspect"), ext=".mp4", order=16, **_ui("video")),
):
    register_kind(_k)

for _p in (
    Preset("hologram", "hologram", "Hologram", "a new hologram of a subject, made and baked on the lab"),
    Preset("world-painting", "image", "World painting",
           "a wide painted scene for a world's background",
           {"template": "{prompt}. A wide painted establishing shot, rich atmosphere, painterly brushwork, "
                        "cinematic light, no text, no people in the foreground, no logos.",
            "aspect": "16:9", "resolution": 2048}),
    Preset("voice-line", "voice", "Voice line", "one short spoken line in the lab voice's default voice"),
    # Wan 2.2's 5B needs the motion described: "stays in place … seamless loop" makes it all
    # but freeze once the loop's end frame is pinned (docs/art.md, "Video loops on a ComfyUI")
    Preset("creature-loop", "video", "Creature loop",
           "a world creature on black as a seamless loop, matted for the live layer (like the Choir)",
           {"template": "{prompt}. One glowing creature alone on a pure black background, moving the whole "
                        "time: smooth, organic, continuous motion. Static camera, nothing else appears.",
            "duration": 5, "alpha": "luma"}),
):
    register_preset(_p)

# the lab model catalog's bench (catalog_bench.py, docs/lab-models.md): off until Settings turns it on
from . import catalog_bench  # noqa: E402,F401
