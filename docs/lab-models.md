# The lab model catalog: bromigos lab models

The model catalog lists, for every AI capability, the best open models a machine can run,
by how much video memory it has. bromigOS uses it to say what fits your lab's GPUs, what
would be better, and how to arrange models across several GPUs. This page explains how
the catalog decides, for someone maintaining its data or building on it. For using it,
read the manual's [Lab models](../manual/src/lab-models.md) page.

The catalog was last researched on 2026-10-09. The sources were model cards, Hugging Face,
LMArena, Artificial Analysis, the Open ASR and MTEB leaderboards, OmniDocBench,
olmOCR-bench, and vendor and community benchmarks. Each model's `cite` field lists its own.
A weekly refresh keeps the catalog current ([Staying current](#staying-current)).

| Part | Where it lives |
|---|---|
| the data | `homelab/share/lab/models.toml`, installed as `/usr/share/bromigos/homelab/lab/models.toml` |
| its package | `bromigos-lab-catalog`, data only, so it can update without a code release |
| the code | `bromigos_homelab.catalog`, in `bromigos-homelab` |

Two other parts of bromigOS use it. `bromigos lab` shows what fits and what's better
([lab.md](lab.md)). `bromigos target check` mentions when a better model would fit
([targets.md](targets.md)).

## Commands

```bash
bromigos lab models recommend          # this lab's GPUs: what runs, the best fit, upgrades, licence warnings
bromigos lab models plan               # two to four ranked arrangements of the whole lab
bromigos lab models pick image 16      # the best image model for a 16 GB card
bromigos lab models tiers llm          # the best LLM at every size
bromigos lab models upgrades           # what the upgrade policy would do now
bromigos lab models refresh            # fetch the newest signed catalog
bromigos lab models check              # check the data is consistent
```

| Command | Options |
|---|---|
| `recommend` | `--all` shows every capability on every GPU. |
| `plan` | `--budget`, `--always`, `--want`, `--goal`, `--priority`, `--clients`, `--context`, `--prompt`, `--output`, `--hw`, `--ram`, `--unsupported` ([below](#planning-the-whole-lab-plan)) |
| `pick CAPABILITY [VRAM]` | `--gpu NAME`, `--gpus N`, `--vendor amd` or `apple`, `--goal G`, `--ram GiB` |
| `tiers CAPABILITY` | `--markdown` prints the tables at the end of this page. |
| `upgrades` | `--apply` isn't built yet. It says so, changes nothing, and shows what the policy would do. |
| `refresh` | `--hf` asks Hugging Face now. `--submit-bench` sends your bench results. |

The planning commands also take:

- `--licence any`, `commercial` or `permissive` (below);
- `--region US`, `EU`, `UK`, `KR` or `any`;
- `--json`, for scripts and Settings.

The licence filter and region default to your settings. Without a region setting, the
region comes from your time zone, then your locale. `--region any` turns region checks
off.

## Names

### Capabilities

A *capability* is one kind of AI work. Some have a second name: the *service* name that
`targets.toml` and `create.toml` use.

| Capability | What it does | Service name |
|---|---|---|
| `llm` | chat with tool calling: VECTOR's brain, the lab's agents | `llm` |
| `code` | coding: agentic models, and small fill-in-the-middle models for autocomplete | |
| `embed` | text embeddings, for VECTOR's memory and search | |
| `image` | image generation | `image.generate` |
| `image-edit` | instruction, masked and multi-reference edits | `image.edit` |
| `cutout` | background removal | `image.cutout` |
| `upscale` | image and video upscaling and restoration | `image.upscale`, `video.upscale` |
| `video` | loops from a still, and image or text to video | `video.loop` |
| `3d` | image to 3D, as a textured GLB or shape only | `model3d.generate` |
| `tts` | text to speech: VECTOR's voice, with voice design, cloning and streaming | `voice.tts` |
| `stt` | speech to text: VECTOR's hearing | `voice.stt` |
| `ocr` | OCR and document parsing | |
| `vision` | screen understanding, as in "look at my screen" | |

VECTOR is the desktop's AI assistant.

### Setups

A *setup* is a reference machine: one row in the tables at the end. `pick` takes any size;
these are the reference points.

| Setup | Means |
|---|---|
| `cpu` | no GPU, system RAM only |
| `8`, `12`, `16`, `24`, `32`, `48`, `80`, `96` | one card with that many GB, such as an RTX 4060, 5070, 4080, 4090, 5090, RTX 6000 Ada, H100 or RTX PRO 6000 |
| `2x24`, `2x32`, `4x24`, `4x32` | consumer cards in one machine, tensor parallel for LLMs |
| `1x80`, `2x80`, `4x80`, `8x80` | H100-class datacenter cards |
| `8xb200` | eight B200s |
| `spark`, `2xspark` | NVIDIA GB10 (DGX Spark) with 128 GB of unified memory; two linked over RoCE |
| `mac-64`, `mac-128`, `mac-192`, `mac-512` | Apple Silicon unified memory, about 75% usable by default |

## How a pick is made

The catalog records **facts about each model variant**, never picks. A *variant* is one
way to run a model, such as a particular quantisation on a particular runtime. Its facts
are:

- peak VRAM, for all its GPUs together, and `gpus` when it needs several;
- RAM;
- the runtime;
- its speed, measured on a reference card;
- a quality score within its capability;
- the licence;
- whether bromigOS's stack runs it.

The picks are computed from these facts for the hardware you have. So a 10 GB card or a
box with four H100s gets an answer, as well as the reference rows.

### Fit

A variant fits a GPU when its peak, plus a little headroom, is within the GPU's budget.
The budget is the card's VRAM less a reserve: 1.5 GiB on a desktop card that drives a
screen, 0.4 GiB otherwise.

- LLMs are sized by the serving model in [Many agents at once](#many-agents-at-once): the
  weights, plus the KV cache for the clients and context you ask for.
- A variant marked `offload` keeps part of itself in system RAM. That might be a MoE
  model's experts on the CPU, or ComfyUI's block swap. It fits a smaller card, runs slower,
  and needs the RAM.
- Unified memory, as on a DGX Spark, a Ryzen AI Max or a Mac, counts its usable share.

### Quality

Quality is a score from 0 to 100 within a capability. Where a public leaderboard exists,
the score comes from it:

| Capability | Basis |
|---|---|
| `llm` | 50 + Artificial Analysis Intelligence Index |
| `image` | 50 + (LMArena text-to-image Elo − 1000) / 5 |
| `image-edit` | 50 + (LMArena single-image edit Elo − 1100) / 6 |
| `stt` | 100 − 2.5 × word error rate, from the Open ASR Leaderboard's 8 public English sets |
| `embed` | MTEB Multilingual v2 and RTEB, relative |
| `ocr` | OmniDocBench v1.6 and olmOCR-bench, relative |
| `vision` | OSWorld-Verified, ScreenSpot-Pro and MMMU-Pro, relative |
| `code` | SWE-bench Pro, Terminal-Bench 2.1 and LiveCodeBench, relative |
| `video` | seamless loops from a still first, then the Artificial Analysis video arena |
| `tts` | the Artificial Analysis speech arena for open weights, else vendor evaluations |
| `3d`, `cutout`, `upscale` | Comfy Org's and community comparisons, relative; no neutral benchmark exists |

For `video`, a model with a native first-and-last-frame input ranks first, because that's
what makes a seamless loop. For `tts`, voice design, cloning and streaming count too.

Compression costs a few points, unless a variant records its own difference:

| Compression | Points lost |
|---|---|
| BF16, FP16 | 0 |
| FP8, INT8, Q8, MXFP4 | 0.5 |
| Q6 | 0.8 |
| Q5 | 1.2 |
| NVFP4 | 1.5 |
| AWQ, GPTQ, INT4 | 1.8 |
| Q4 | 2 |
| Q3 | 4 |
| Q2 | 7 |

### Speed

Speed is measured on a reference card and scaled to yours. LLM decoding scales by memory
bandwidth. Diffusion and the rest scale by compute. Speeds are rough. A figure measured on
your own lab replaces it ([Measured on your lab](#measured-on-your-lab)).

### Goal

Each capability has a goal:

- **best quality:** the strongest model and the least compression that fits. Speed only
  breaks ties.
- **balanced:** the default.
- **fastest:** smaller and distilled models, kept loaded.
- **many agents**, for LLMs only: the most throughput at the number of clients you set.

A capability also has a usable floor: 15 tokens a second for an agent's LLM, 1.5 times
real time for a live voice, and 3 times real time for hearing. A pick below the floor
counts for much less.

### Licence and region

The licence filter is a setting, not a judgement:

- `any` includes research and non-commercial licences. That's fine for a personal lab.
- `commercial` needs a licence that allows commercial use, perhaps with conditions such as
  a revenue cap.
- `permissive` needs a licence with no conditions: Apache, MIT, BSD, CC-BY or OpenMDW.

Some licences exclude regions. Tencent's exclude the EU, the UK and South Korea. MiniMax
H3's also excludes the US. Those models drop out where you are.

### Only what bromigOS runs

A variant is recommended only when bromigOS drives its runtime:

- a ComfyUI workflow bromigOS has, or can add with core nodes or an established node pack;
- vLLM or SGLang;
- llama.cpp or Ollama;
- MLX, for LLMs;
- the voice service, which runs Qwen3-TTS and faster-whisper today.

Anything else is in the catalog marked `needs support: …`. `pick` shows these, but never
picks them. `plan --unsupported` includes them.

### AMD and Apple

Each variant lists the vendors it runs on.

- NVFP4 and MXFP8 in ComfyUI need an NVIDIA Blackwell GPU. vLLM runs NVFP4 on older NVIDIA
  cards as weight-only.
- AMD's RDNA3 has no FP8, so it uses GGUF or BF16.
- On a Mac, LLMs run on MLX or llama.cpp. ComfyUI on Apple's GPU is slow and has no FP8,
  so most media models on a Mac are marked `needs support`.

## Planning the whole lab: plan

`recommend` answers one capability at a time. `plan` answers the real question: with
these GPUs, what goes where, what stays loaded, and what swaps.

```bash
bromigos lab models plan --budget "RTX 5070=6G" --always llm,tts,stt \
    --goal balanced,video=quality --priority brain --clients 4 --context 32k --region US
```

| Input | What it sets |
|---|---|
| the hardware | detected: the lab's GPUs, from DCGM and the media servers, and this machine's card |
| `--hw "RTX 5090" --hw "RTX 5070,desktop" --ram 64` | plan for a machine you don't have |
| `--budget` | the most the lab may use on each GPU, as `gpu0=24G` or by name, `"RTX 5070=6G"` |
| `--want` | the capabilities to place. Default: llm, tts, stt, embed, image, image-edit, cutout, video, 3d. |
| `--always` | the ones that stay loaded. Default: llm, tts, stt, embed. |
| `--goal` | quality, balanced, speed or throughput, for all or per capability |
| `--priority` | which arrangement comes first: balanced, brain, media, voice or resident |
| `--clients`, `--context`, `--prompt`, `--output` | the LLM's load ([Many agents at once](#many-agents-at-once)) |

Capabilities not in `--always` load when a job needs them, and the idle sidecar unloads
them afterwards.

`plan` answers with two to four ranked *configurations*: Balanced, Brain first, Media
first, Voice first and Everything resident. Identical ones are folded together. Each
configuration places every capability and says:

- which model runs on which GPU, or split across linked GPUs;
- its quantisation, and whether it stays loaded;
- the peak VRAM on each GPU against the budget, and the headroom left;
- the speed;
- why it went there, in plain words;
- what this configuration gives up against the others, in one line.

The planner follows these rules:

- No budget is ever exceeded.
- The always-on models fit together, with headroom.
- An on-demand model only needs to fit beside the always-on ones. On-demand models swap
  with each other, one job at a time, and each counts its cold start.
- The LLM prefers the bigger card.
- VECTOR's voice and hearing share one device, because one service runs both.
- A GPU you game on keeps resident models off it when it can.
- A model that serves two capabilities counts once. A multimodal LLM can read the screen,
  and Qwen-Image both edits and draws.

Under the hood, it's a beam search over the always-on placements. The on-demand models
are fitted around each one. Each configuration is scored by quality and speed, under each
capability's goal and weight. The brain and the voice count most.

### In Settings

Settings › Lab › Models is the same planner, live. It has a budget slider per GPU, a
switch and an always-on toggle per capability, a goal per capability, the agents and
context for the LLM, and the licence filter and region. The configurations re-plan as you
move them.

The inputs are saved in `~/.config/bromigos/lab.toml`, under `[plan]`. That file names
GPUs by model, never by host, so it holds nothing private. If the file is a symlink, it's
written through the link. A `[lab.plan]` table written by hand in `homelab.toml` is read
too, when `lab.toml` doesn't have one.

## Many agents at once

One LLM endpoint serves VECTOR, other agents, coding tools and batch jobs at the same
time. For LLMs, `plan` and `pick` size the server for `--clients` and `--context`. They
report what it serves: tokens a second for each client and in all, and the time to the
first token.

- **The KV cache** grows with clients times context, and sits beside the weights. A model
  that fits one user may not fit sixteen. Each model records its own size in
  `kv_kib_per_token`, for its full-attention layers. Hybrid linear-attention and Mamba
  models keep a small fixed state per sequence instead.
- **Runtimes differ.** vLLM and SGLang batch continuously, across hundreds of sequences.
  llama.cpp, Ollama and MLX serve a few slots, each with its own context, and scale poorly.
- **MoE models** touch more experts for a batch than for one token. Their step time grows
  with the batch, while compute stays at the active parameters.
- **Tensor parallel** across linked GPUs adds their bandwidth, less what the link costs.
  For example, a pair of DGX Sparks over RoCE.

Someone may have published figures for a model served on the same hardware: the same GPU
and count, the same kind of quantisation, and the variant's runtime when it has one. Those
figures are recorded as `[[model.serving]]` entries, and the catalog uses them,
interpolating between the concurrencies measured. Outside that range, and for everything
nobody measured, a model of memory bandwidth and compute fills in. It's calibrated on each
variant's measured single-stream speed.

A few more effects count:

- An agent's prompt is prefilled in the same steps as the other clients' replies. Half its
  new part counts, because the server's prefix cache holds the history.
- Figures measured with speculative decoding say so. That covers MTP, EAGLE and n-gram
  drafts, and any figure faster than the weights could stream without it. The gain fades
  as the batch fills the GPU.
- A server's own cap on sequences, such as vLLM's `--max-num-seqs`, makes the rest wait.

The bench measures your own server ([Measured on your lab](#measured-on-your-lab)).

## recommend and bromigos target check

`recommend` looks at each GPU, and at each group of linked GPUs. For each, it shows:

- what runs there now: ComfyUI's model files, vLLM's served models from its metrics or its
  Kubernetes Deployments, and the voice service's models;
- the best fit for each capability it runs;
- upgrades worth at least 3 quality points;
- installed models whose licence doesn't cover your filter or region;
- the best fit for each capability nothing in the lab runs yet.

`--all` shows every capability on every GPU.

`bromigos target check` prints the same upgrades under its own table, as "a better model
would fit".

## The model-selection contract

Creation providers don't hard-code a model. For each capability, `create.toml` may give a
provider a list of models in order of preference. The catalog's ranking is what
`recommend` and provisioning will write there:

```toml
[video.loop]
comfyui = ["wan2.2-i2v-a14b", "wan2.2-ti2v-5b"]     # tried in turn on each ComfyUI
```

`bromigos art make` tries each workflow on a ComfyUI in turn. It skips a workflow when
that ComfyUI lacks its files or nodes, or when the workflow's measured peak is more than
the card has, and it says why.

A workflow's `_meta` ties it to the catalog:

| `_meta` field | What it holds |
|---|---|
| `catalog` | `"<model>/<variant>"`, the catalog entry it runs, for its licence, quality and VRAM |
| `vram_gib` | its measured peak on its card |
| `features` | for video: `i2v`, `flf2v` (a native end frame, which makes loops) or `t2v` |
| `requires`, `nodes` | the model files and node classes it needs |

Workflows are named after the catalog model, such as `wan2.2-i2v-a14b.json`. A catalog
variant's `workflow` names the bromigOS workflow that runs it, when there is one.

## Upgrades

Upgrades are opt-in, per capability. Set them in Settings › Lab › Models, or in
`~/.config/bromigos/lab.toml`:

```toml
[upgrade]
enabled = false                 # the global switch; off by default
action = "notify"               # notify (default), or apply once Phase 2 is built
quiet_hours = "01:00-06:00"     # when an upgrade may apply, in local time
policy = { image = "safe", video = "any" }     # off, safe or any; a missing capability is off
```

`homelab.toml`'s `[lab.upgrade]` is read when `lab.toml` doesn't have the table.

- **safe** allows only a newer version, or a better quantisation, of the same model
  family. It must stay within the GPU's budget and the goal.
- **any** allows any catalog pick that beats the current one by 3 quality points or more,
  within the budget, the goal and the licence filter.

`bromigos lab models upgrades` shows what the policy would do now, with the reason, the
gain and the cost in VRAM and licence.

> **Planned.** Applying an upgrade is Phase 2, as `lab models replace`. It will go like
> this:
>
> 1. The change is written to your homelab repository as a pull request. The lab is never
>    edited by hand.
> 2. Argo CD deploys the new model beside the old one.
> 3. A smoke test loads it, makes one generation, and checks the peak VRAM and speed are
>    in the expected range.
> 4. If it passes, the default switches and the pull request merges. If it fails, the
>    change is reverted automatically and you're told.
> 5. The old model is kept for a few days, then cleaned up by another pull request.
> 6. Every upgrade sends a notification, with Undo, which reverts it.
> 7. The voice service's models never change while VECTOR is speaking. The lab's job queue
>    and the quiet hours are respected.

## Staying current

### The weekly refresh

`.github/workflows/lab-catalog.yml` runs every Monday. It reads Hugging Face through
`huggingface_hub`, anonymously. An `HF_TOKEN` repository secret only raises the rate
limits. It looks for:

- metadata for the catalog's models: parameter counts, licences and dates;
- new quantisations of them by the usual publishers: GGUF, FP8, AWQ, NVFP4 and MLX;
- newer members of each family, by the same publisher;
- new and trending models for each capability.

For each one, it notes whether bromigOS's runtimes can run it. That comes from the Hub's
compatibility data for vLLM, SGLang, llama.cpp, Ollama and MLX, and from a Comfy-Org
repackage for ComfyUI. A family's newer member only counts under a Hub pipeline the
catalog covers.

It writes the metadata and `[[pending]]` entries into `models.toml`, and opens a pull
request with an evidence report: why, scores, sizes, licences and links.

The refresh never changes picks or rankings. So once the catalog's tests pass, the
workflow merges the pull request itself and publishes `bromigos-lab-catalog`. The
repository is private, so it can't use branch protection's auto-merge. Where the GitHub
organisation doesn't let Actions open pull requests, the workflow commits the tested change
to main instead, and files the evidence report as an issue labelled `lab-catalog`.

The refresh lives in this repository, not a separate one. The data ships with the code
that reads it and its tests, through the same signed package pipeline.

### Reviewing pending entries

Pending entries are the review list. `bromigos lab models refresh` lists them. Each one
ends in one of two ways:

- Someone researches the candidate's quality, peak VRAM, speed and licence, and edits the
  catalog by hand. It becomes a pick.
- Someone sets `state = "dismissed"`, with the reason in `dismissed`. A dismissed entry
  isn't listed or proposed again. For example, the first refresh found three FLUX.3
  "action" repositories that are robot policies, not image models.

### Distribution

Because `bromigos-lab-catalog` is data only, `bromigos update` brings a new catalog without
a code release.

Every publish also puts the file and a detached signature next to the package repository,
at `<server>/lab/models.toml` and `models.toml.sig`, signed with the repository's key.
`bromigos lab models refresh` fetches it on demand and checks the signature with `gpgv`,
against the key `bromigos-keyring` installs. When it's newer than the packaged copy, it's
kept in `~/.cache/bromigos/lab/`.

### The weekly nudge

`bromigos-lab-models.timer` is a weekly user timer, enabled by `bromigos update`. It
fetches the newest catalog. When a better model fits one of the lab's GPUs for your goal
and licence filter, it sends one quiet notification, such as "A better image model fits
your RTX 4090: …. See bromigos lab models plan". Each suggestion is sent once.

The nudge never installs anything. Installing will go through Phase 2's `lab models add`.
VECTOR can tell you about a suggestion when you ask. To turn the nudge off:

```bash
systemctl --user disable --now bromigos-lab-models.timer
```

### Measured on your lab

The `catalog-bench` job kind measures a catalog model on your own GPU. It's off until you
turn on "Bench candidates on the lab" in Settings › Lab › Models, which sets
`[bench] enabled = true` in `lab.toml`.

```bash
bromigos lab run catalog-bench --model <model>/<variant>
bromigos lab run catalog-bench --model llm          # the LLM the lab serves
```

It runs through the lab's job queue like any heavy job: one at a time, gated on free VRAM,
with the voice service's reserve kept ([lab.md](lab.md#the-queue)). It installs nothing.
What it does depends on the model:

- **A ComfyUI workflow the lab has** makes one generation. The peak VRAM and the seconds
  are recorded, then ComfyUI is asked to unload.
- **An LLM the lab serves** gets a short load test at 1, 4 and 16 clients: the time to the
  first token, and tokens a second for each client and in all.
- **The voice service** speaks one line.

Results go to `~/.local/state/bromigos/lab/bench.jsonl`. They replace the published
figures for that GPU. `bromigos lab models refresh --submit-bench` posts them to the open
catalog pull request, or issue.

## How the data is laid out

`models.toml` has these tables:

| Table | What it holds |
|---|---|
| `[licence.<id>]` | a licence: its name, URL, whether it allows commercial use, its conditions, whether it's permissive |
| `[capability.<id>]` | a capability: its title, service name, whether it stays loaded, its speed unit, its quality basis and notes |
| `[gpu."<name>"]` | a GPU model: its VRAM, architecture, bandwidth and compute |
| `[[model]]` | a model: its capabilities, family, repository, licence, quality scores and `cite` |
| `[[model.variant]]` | one way to run it: runtime, quantisation, weights, VRAM, RAM, vendors and `stack` |
| `[[model.serving]]` | published serving figures on a given GPU, runtime and concurrency |
| `[[pending]]` | a candidate the weekly refresh found, waiting for review |

Edit facts here, never picks. The picks are computed. Run `bromigos lab models check`
after an edit.

## What Phase 2 and 3 will use

> **Planned.** These hooks are in place for work that isn't built yet.

- `bromigos lab models add` will install a catalog variant: its `weights`, which are a
  Hugging Face repository or files, its `runtime` and its `workflow`, sized by the plan.
  It will go through the homelab repository, never by hand.
- Provisioning ([lab-provision.md](lab-provision.md)) will take a service's models from
  `models = { from = "catalog", capabilities = [...] }`. The configuration you pick in
  `plan` is what will get installed.

The Python API is `catalog.pick(capability, vram_gib, ram_gib=, vendor=, licence=, goal=,
region=)` and `catalog.plan(hardware, …)`. For everything else, the stable interface is
`bromigos lab models … --json`.

## The catalog by capability and setup

These tables come from `bromigos lab models tiers --markdown`, for a US user with no
licence filter. The "Commercial use allowed" column applies the `commercial` filter.

- † marks a licence that excludes some regions. Tencent's exclude the EU, the UK and South
  Korea.
- ‡ marks a non-commercial licence.
- "+ RAM" means part of the model sits in system RAM.
- Speeds are rough, scaled from a reference card.

MiniMax H3 is the strongest open video model, but it isn't licensed in the US, the EU, the
UK or South Korea. So it's in none of these rows. Elsewhere, it leads video from 16 GB.

### LLM chat and tools (`llm`)

VECTOR's brain and the lab's agents: tool calling, long context. Served by vLLM or SGLang (many clients), llama.cpp or Ollama (GGUF, CPU, Apple), MLX on Macs.

| Setup | Best quality | Balanced | Commercial use allowed |
|---|---|---|---|
| cpu | Qwen3.6-35B-A3B GGUF UD-Q4_K_XL (CPU, ~20 tok/s) | same | same |
| 8 | Qwen3.6-35B-A3B GGUF UD-Q4_K_M + --n-cpu-moe (6 GiB + RAM, ~34 tok/s) | same | same |
| 12 | Qwen3.6-35B-A3B GGUF UD-Q4_K_M + --n-cpu-moe (6 GiB + RAM, ~34 tok/s) | Gemma 4 12B Unified GGUF QAT Q4_0 (8 GiB, ~75 tok/s) | same |
| 16 | Qwen3.8-27B GGUF UD-IQ3_XXS + mmproj-F16 (15 GiB, ~32 tok/s) | same | same |
| 24 | Qwen3.8-27B GGUF UD-Q5_K_M (22 GiB, ~40 tok/s) | Qwen3.8-27B GGUF UD-Q4_K_XL (20 GiB, ~47 tok/s) | same |
| 32 | Qwen3.8-27B GGUF Q8_0 (30 GiB, ~34 tok/s) | Qwen3.8-27B GGUF UD-Q4_K_XL (20 GiB, ~78 tok/s) | same |
| 48 | Qwen3.8-27B GGUF Q8_0 (30 GiB, ~19 tok/s) | Qwen3.8-27B GGUF UD-Q4_K_XL (20 GiB, ~45 tok/s) | same |
| 80 | Qwen3.8-27B BF16 (55 GiB, ~34 tok/s) | Qwen3.8-27B GGUF UD-Q6_K (25 GiB, ~85 tok/s) | same |
| 96 | Qwen3.8-Flash-Next GGUF UD-IQ4_XS (89 GiB, ~163 tok/s) | same | same |
| 2x24 | Qwen3.8-27B FP8 block (32 GiB, ~30 tok/s) | Qwen3.8-27B NVFP4 (23 GiB, ~61 tok/s) | same |
| 2x32 | Qwen3.8-27B BF16 (55 GiB, ~30 tok/s) | Qwen3.8-27B NVFP4 (23 GiB, ~99 tok/s) | same |
| 4x32 | Qwen3.8-Flash-Next GGUF UD-IQ4_XS (90 GiB, ~151 tok/s) | same | same |
| 2x80 | Qwen3.8-Flash-Next NVFP4 experts + FP8 n-gram table (128 GiB, ~298 tok/s) | same | same |
| 4x80 | Qwen3.8-Flash-Next GGUF Q8_0 (182 GiB, ~179 tok/s) | same | same |
| 8x80 | GLM-5.3 NVFP4 (402 GiB, ~231 tok/s) | same | same |
| 8xb200 | GLM-5.3 FP8 (722 GiB, ~267 tok/s) | same | same |
| spark | Qwen3.8-Flash-Next GGUF UD-IQ4_XS (89 GiB, ~34 tok/s) | same | same |
| 2xspark | Qwen3.8-Flash-Next NVFP4 experts + FP8 n-gram table (128 GiB, ~54 tok/s) | same | same |
| mac-64 | Qwen3.8-27B MLX 8-bit (31 GiB, ~16 tok/s) | Qwen3.6-35B-A3B GGUF Q8_0 (36 GiB, ~86 tok/s) | same |
| mac-128 | Qwen3.8-Flash-Next GGUF UD-IQ4_XS (89 GiB, ~64 tok/s) | same | same |
| mac-192 | Qwen3.8-Flash-Next GGUF UD-IQ4_XS (89 GiB, ~88 tok/s) | same | same |
| mac-512 | GLM-5.3-Flash GGUF Q8_0 (319 GiB, ~24 tok/s) | Qwen3.8-Flash-Next GGUF UD-IQ4_XS (89 GiB, ~90 tok/s) | same |

### Coding LLM (`code`)

Optional: agentic coding, and small FIM models for autocomplete.

| Setup | Best quality | Balanced | Commercial use allowed |
|---|---|---|---|
| cpu | KAT-Coder-V2.5-Dev GGUF Q4_K_M (CPU, ~20 tok/s) | same | same |
| 8 | KAT-Coder-V2.5-Dev GGUF Q4_K_M (CPU, ~20 tok/s) | Qwen3.6-35B-A3B GGUF UD-Q4_K_M + --n-cpu-moe (6 GiB + RAM, ~34 tok/s) | same |
| 12 | KAT-Coder-V2.5-Dev GGUF Q4_K_M (CPU, ~20 tok/s) | Qwen3.6-35B-A3B GGUF UD-Q4_K_M + --n-cpu-moe (6 GiB + RAM, ~34 tok/s) | same |
| 16 | Qwen3.8-27B GGUF UD-IQ3_XXS + mmproj-F16 (15 GiB, ~32 tok/s) | same | same |
| 24 | Qwen3.8-27B GGUF UD-Q5_K_M (22 GiB, ~40 tok/s) | KAT-Coder-V2.5-Dev GGUF Q4_K_M (21 GiB, ~196 tok/s) | same |
| 32 | Qwen3.8-27B GGUF Q8_0 (30 GiB, ~34 tok/s) | Qwen3.8-27B GGUF UD-Q4_K_XL (20 GiB, ~78 tok/s) | same |
| 48 | Qwen3.8-27B GGUF Q8_0 (30 GiB, ~19 tok/s) | KAT-Coder-V2.5-Dev GGUF Q4_K_M (21 GiB, ~190 tok/s) | same |
| 80 | Qwen3.8-27B BF16 (55 GiB, ~34 tok/s) | Qwen3.8-27B GGUF UD-Q6_K (25 GiB, ~85 tok/s) | same |
| 96 | Qwen3.8-Flash-Next GGUF UD-IQ4_XS (89 GiB, ~163 tok/s) | same | same |
| 2x24 | Qwen3.8-27B FP8 block (32 GiB, ~30 tok/s) | Qwen3.8-27B NVFP4 (23 GiB, ~61 tok/s) | same |
| 2x32 | Qwen3.8-27B BF16 (55 GiB, ~30 tok/s) | Qwen3.8-27B NVFP4 (23 GiB, ~99 tok/s) | same |
| 4x32 | Qwen3.8-Flash-Next GGUF UD-IQ4_XS (90 GiB, ~151 tok/s) | same | same |
| 2x80 | GLM-5.3-Flash GGUF UD-Q3_K_XL (139 GiB, ~81 tok/s) | same | same |
| 4x80 | DeepSeek-V4-Flash-0731 FP4 experts + FP8 (161 GiB, ~306 tok/s) | same | same |
| 8x80 | GLM-5.3 NVFP4 (402 GiB, ~231 tok/s) | same | same |
| 8xb200 | GLM-5.3 FP8 (722 GiB, ~267 tok/s) | same | same |
| spark | Qwen3.8-Flash-Next GGUF UD-IQ4_XS (89 GiB, ~34 tok/s) | KAT-Coder-V2.5-Dev GGUF Q4_K_M (21 GiB, ~74 tok/s) | same |
| 2xspark | Qwen3.8-Flash-Next NVFP4 experts + FP8 n-gram table (128 GiB, ~54 tok/s) | same | same |
| mac-64 | Qwen3.8-27B MLX 8-bit (31 GiB, ~16 tok/s) | KAT-Coder-V2.5-Dev GGUF Q4_K_M (21 GiB, ~129 tok/s) | same |
| mac-128 | Qwen3.8-Flash-Next GGUF UD-IQ4_XS (89 GiB, ~64 tok/s) | same | same |
| mac-192 | GLM-5.3-Flash GGUF UD-Q3_K_XL (139 GiB, ~24 tok/s) | Qwen3.8-Flash-Next GGUF UD-IQ4_XS (89 GiB, ~88 tok/s) | same |
| mac-512 | GLM-5.3-Flash GGUF Q8_0 (319 GiB, ~24 tok/s) | Qwen3.8-Flash-Next GGUF UD-IQ4_XS (89 GiB, ~90 tok/s) | same |

### Embeddings (`embed`)

VECTOR's memory and the lab's search. Changing the model means re-indexing.

| Setup | Best quality | Balanced | Commercial use allowed |
|---|---|---|---|
| cpu | Harrier OSS v1 0.6B GGUF Q8_0 (CPU, ~0.73 k tok/s) | same | same |
| 8 | Qwen3-Embedding-8B GGUF Q4_K_M (6 GiB, ~2.0 k tok/s) | Harrier OSS v1 0.6B GGUF Q8_0 (1 GiB, ~11 k tok/s) | same |
| 12 | NVIDIA Nemotron 3 Embed 8B FP8 (10 GiB, ~2.1 k tok/s) | Harrier OSS v1 0.6B GGUF Q8_0 (1 GiB, ~23 k tok/s) | same |
| 16 | NVIDIA Nemotron 3 Embed 8B FP8 (10 GiB, ~3.4 k tok/s) | Harrier OSS v1 0.6B GGUF Q8_0 (1 GiB, ~35 k tok/s) | same |
| 24 | Harrier OSS v1 27B GGUF Q6_K (22 GiB, ~2.7 k tok/s) | Harrier OSS v1 0.6B GGUF Q8_0 (1 GiB, ~60 k tok/s) | same |
| 32 | Harrier OSS v1 27B GGUF Q8_0 (29 GiB, ~2.7 k tok/s) | Harrier OSS v1 0.6B GGUF Q8_0 (1 GiB, ~76 k tok/s) | same |
| 48 | Harrier OSS v1 27B GGUF Q8_0 (29 GiB, ~2.3 k tok/s) | Harrier OSS v1 0.6B GGUF Q8_0 (1 GiB, ~66 k tok/s) | same |
| 80 | Harrier OSS v1 27B BF16 (55 GiB, ~2.7 k tok/s) | Harrier OSS v1 0.6B GGUF Q8_0 (1 GiB, ~145 k tok/s) | same |
| 96 | Harrier OSS v1 27B BF16 (55 GiB, ~1.6 k tok/s) | Harrier OSS v1 0.6B GGUF Q8_0 (1 GiB, ~87 k tok/s) | same |
| 2x24 | Harrier OSS v1 27B FP8 (31 GiB, ~3.2 k tok/s) | Harrier OSS v1 0.6B GGUF Q8_0 (1 GiB, ~60 k tok/s) | same |
| 2x32 | Harrier OSS v1 27B BF16 (56 GiB, ~2.2 k tok/s) | Harrier OSS v1 0.6B GGUF Q8_0 (1 GiB, ~76 k tok/s) | same |
| 4x32 | Harrier OSS v1 27B BF16 (57 GiB, ~3.6 k tok/s) | Harrier OSS v1 0.6B BF16 (5 GiB, ~79 k tok/s) | same |
| 2x80 | Harrier OSS v1 27B BF16 (56 GiB, ~4.3 k tok/s) | Harrier OSS v1 0.6B GGUF Q8_0 (1 GiB, ~145 k tok/s) | same |
| 4x80 | Harrier OSS v1 27B BF16 (57 GiB, ~6.9 k tok/s) | Harrier OSS v1 0.6B BF16 (5 GiB, ~151 k tok/s) | same |
| 8x80 | Harrier OSS v1 27B BF16 (60 GiB, ~12 k tok/s) | Harrier OSS v1 0.6B BF16 (7 GiB, ~256 k tok/s) | same |
| 8xb200 | Harrier OSS v1 27B BF16 (60 GiB, ~23 k tok/s) | NVIDIA Nemotron 3 Embed 8B FP8 (15 GiB, ~122 k tok/s) | same |
| spark | Harrier OSS v1 27B GGUF Q8_0 (29 GiB, ~0.79 k tok/s) | Harrier OSS v1 0.6B GGUF Q8_0 (1 GiB, ~23 k tok/s) | same |
| 2xspark | Harrier OSS v1 27B GGUF Q8_0 (29 GiB, ~0.79 k tok/s) | Harrier OSS v1 0.6B GGUF Q8_0 (1 GiB, ~23 k tok/s) | same |
| mac-64 | Harrier OSS v1 27B GGUF Q6_K (22 GiB, ~0.56 k tok/s) | Harrier OSS v1 0.6B GGUF Q8_0 (1 GiB, ~12 k tok/s) | same |
| mac-128 | Harrier OSS v1 27B GGUF Q6_K (22 GiB, ~0.56 k tok/s) | Harrier OSS v1 0.6B GGUF Q8_0 (1 GiB, ~12 k tok/s) | same |
| mac-192 | KaLM-Embedding-Gemma3-12B-2511 GGUF Q8_0 † (13 GiB, ~0.75 k tok/s) | Harrier OSS v1 0.6B GGUF Q8_0 (1 GiB, ~9.8 k tok/s) | same |
| mac-512 | Harrier OSS v1 27B GGUF Q8_0 (29 GiB, ~0.73 k tok/s) | Harrier OSS v1 0.6B GGUF Q8_0 (1 GiB, ~21 k tok/s) | same |

### Image generation (`image`)

ComfyUI workflows; the text encoder's size often decides the fit (it unloads after encoding).

| Setup | Best quality | Balanced | Commercial use allowed |
|---|---|---|---|
| cpu | none fits | none fits | none fits |
| 8 | Qwen-Image-2.1 GGUF Q4_K_M ‡ (7 GiB, ~84 s/image) | same | Z-Image-Turbo GGUF Q4_K_M (6 GiB, ~15 s/image) |
| 12 | Qwen-Image-2.1 INT8 ConvRot ‡ (11 GiB, ~32 s/image) | same | HiDream-O1-Image FP8 scaled / MXFP8 (10 GiB, ~53 s/image) |
| 16 | Qwen-Image-2.1 INT8 ConvRot ‡ (11 GiB, ~20 s/image) | same | Qwen-Image-2512 SVDQuant INT4 / FP4 (14 GiB, ~17 s/image) |
| 24 | Qwen-Image-2.1 INT8 ConvRot ‡ (18 GiB, ~9.6 s/image) | same | Ming-Image 0.1 Design INT8 ConvRot DiT + W4A8 encoder (22 GiB, ~10 s/image) |
| 32 | Qwen-Image-2.1 BF16 ‡ (31 GiB, ~16 s/image) | Qwen-Image-2.1 INT8 ConvRot ‡ (18 GiB, ~7.5 s/image) | HunyuanImage 3.0 Instruct / Instruct-Distil W4A8 † (24 GiB, ~21 s/image) |
| 48 | Qwen-Image-2.1 BF16 ‡ (31 GiB, ~18 s/image) | Qwen-Image-2.1 INT8 ConvRot ‡ (18 GiB, ~8.7 s/image) | HunyuanImage 3.0 Instruct / Instruct-Distil W4A8 † (24 GiB, ~24 s/image) |
| 80 | Qwen-Image-2.1 BF16 ‡ (31 GiB, ~8.2 s/image) | Qwen-Image-2.1 INT8 ConvRot ‡ (18 GiB, ~3.9 s/image) | HunyuanImage 3.0 Instruct / Instruct-Distil W4A8 † (24 GiB, ~11 s/image) |
| 96 | Qwen-Image-2.1 BF16 ‡ (31 GiB, ~14 s/image) | Qwen-Image-2.1 INT8 ConvRot ‡ (18 GiB, ~6.6 s/image) | HunyuanImage 3.0 Instruct / Instruct-Distil W4A8 † (24 GiB, ~18 s/image) |
| 2x24 | Qwen-Image-2.1 INT8 ConvRot ‡ (18 GiB, ~9.6 s/image) | same | Ming-Image 0.1 Design INT8 ConvRot DiT + W4A8 encoder (22 GiB, ~10 s/image) |
| 2x32 | Qwen-Image-2.1 BF16 ‡ (31 GiB, ~16 s/image) | Qwen-Image-2.1 INT8 ConvRot ‡ (18 GiB, ~7.5 s/image) | HunyuanImage 3.0 Instruct / Instruct-Distil W4A8 † (24 GiB, ~21 s/image) |
| 4x32 | Qwen-Image-2.1 BF16 ‡ (31 GiB, ~16 s/image) | Qwen-Image-2.1 INT8 ConvRot ‡ (18 GiB, ~7.5 s/image) | HunyuanImage 3.0 Instruct / Instruct-Distil W4A8 † (24 GiB, ~21 s/image) |
| 2x80 | Qwen-Image-2.1 BF16 ‡ (31 GiB, ~8.2 s/image) | Qwen-Image-2.1 INT8 ConvRot ‡ (18 GiB, ~3.9 s/image) | HunyuanImage 3.0 Instruct / Instruct-Distil W4A8 † (24 GiB, ~11 s/image) |
| 4x80 | Qwen-Image-2.1 BF16 ‡ (31 GiB, ~8.2 s/image) | Qwen-Image-2.1 INT8 ConvRot ‡ (18 GiB, ~3.9 s/image) | HunyuanImage 3.0 Instruct / Instruct-Distil W4A8 † (24 GiB, ~11 s/image) |
| 8x80 | Qwen-Image-2.1 BF16 ‡ (31 GiB, ~8.2 s/image) | Qwen-Image-2.1 INT8 ConvRot ‡ (18 GiB, ~3.9 s/image) | HunyuanImage 3.0 Instruct / Instruct-Distil W4A8 † (24 GiB, ~11 s/image) |
| 8xb200 | Qwen-Image-2.1 BF16 ‡ (31 GiB, ~4.1 s/image) | Qwen-Image-2.1 INT8 ConvRot ‡ (18 GiB, ~2.0 s/image) | HunyuanImage 3.0 Instruct / Instruct-Distil W4A8 † (24 GiB, ~5.4 s/image) |
| spark | Qwen-Image-2.1 BF16 ‡ (31 GiB, ~53 s/image) | Qwen-Image-2.1 INT8 ConvRot ‡ (18 GiB, ~25 s/image) | HunyuanImage 3.0 Instruct / Instruct-Distil W4A8 † (24 GiB, ~69 s/image) |
| 2xspark | Qwen-Image-2.1 BF16 ‡ (31 GiB, ~53 s/image) | Qwen-Image-2.1 INT8 ConvRot ‡ (18 GiB, ~25 s/image) | HunyuanImage 3.0 Instruct / Instruct-Distil W4A8 † (24 GiB, ~69 s/image) |
| mac-64 | none fits | none fits | none fits |
| mac-128 | none fits | none fits | none fits |
| mac-192 | none fits | none fits | none fits |
| mac-512 | none fits | none fits | none fits |

### Image editing (`image-edit`)

Instruction, masked and multi-reference edits. Reference images add tokens: a little more VRAM and time than generation.

| Setup | Best quality | Balanced | Commercial use allowed |
|---|---|---|---|
| cpu | none fits | none fits | none fits |
| 8 | Qwen-Image-2.1 GGUF Q4_K_M ‡ (7 GiB, ~84 s/image) | same | FLUX.2 [klein] 4B GGUF Q4_K_M-Q8_0 (5 GiB, ~17 s/image) |
| 12 | Qwen-Image-2.1 INT8 ConvRot ‡ (11 GiB, ~32 s/image) | same | Boogu-Image-0.1 NVFP4 (9 GiB, ~8.4 s/image) |
| 16 | Qwen-Image-2.1 INT8 ConvRot ‡ (11 GiB, ~20 s/image) | same | Qwen-Image-Edit-2511 SVDQuant INT4 (12 GiB, ~11 s/image) |
| 24 | Qwen-Image-2.1 INT8 ConvRot ‡ (18 GiB, ~9.6 s/image) | same | Qwen-Image-Edit-2511 FP8 mixed (22 GiB, ~7.7 s/image) |
| 32 | Qwen-Image-2.1 BF16 ‡ (31 GiB, ~16 s/image) | Qwen-Image-2.1 INT8 ConvRot ‡ (18 GiB, ~7.5 s/image) | HunyuanImage 3.0 Instruct / Instruct-Distil W4A8 † (24 GiB, ~21 s/image) |
| 48 | Qwen-Image-2.1 BF16 ‡ (31 GiB, ~18 s/image) | Qwen-Image-2.1 INT8 ConvRot ‡ (18 GiB, ~8.7 s/image) | HunyuanImage 3.0 Instruct / Instruct-Distil W4A8 † (24 GiB, ~24 s/image) |
| 80 | Qwen-Image-2.1 BF16 ‡ (31 GiB, ~8.2 s/image) | Qwen-Image-2.1 INT8 ConvRot ‡ (18 GiB, ~3.9 s/image) | HunyuanImage 3.0 Instruct / Instruct-Distil W4A8 † (24 GiB, ~11 s/image) |
| 96 | Qwen-Image-2.1 BF16 ‡ (31 GiB, ~14 s/image) | Qwen-Image-2.1 INT8 ConvRot ‡ (18 GiB, ~6.6 s/image) | HunyuanImage 3.0 Instruct / Instruct-Distil W4A8 † (24 GiB, ~18 s/image) |
| 2x24 | Qwen-Image-2.1 INT8 ConvRot ‡ (18 GiB, ~9.6 s/image) | same | Qwen-Image-Edit-2511 FP8 mixed (22 GiB, ~7.7 s/image) |
| 2x32 | Qwen-Image-2.1 BF16 ‡ (31 GiB, ~16 s/image) | Qwen-Image-2.1 INT8 ConvRot ‡ (18 GiB, ~7.5 s/image) | HunyuanImage 3.0 Instruct / Instruct-Distil W4A8 † (24 GiB, ~21 s/image) |
| 4x32 | Qwen-Image-2.1 BF16 ‡ (31 GiB, ~16 s/image) | Qwen-Image-2.1 INT8 ConvRot ‡ (18 GiB, ~7.5 s/image) | HunyuanImage 3.0 Instruct / Instruct-Distil W4A8 † (24 GiB, ~21 s/image) |
| 2x80 | Qwen-Image-2.1 BF16 ‡ (31 GiB, ~8.2 s/image) | Qwen-Image-2.1 INT8 ConvRot ‡ (18 GiB, ~3.9 s/image) | HunyuanImage 3.0 Instruct / Instruct-Distil W4A8 † (24 GiB, ~11 s/image) |
| 4x80 | Qwen-Image-2.1 BF16 ‡ (31 GiB, ~8.2 s/image) | Qwen-Image-2.1 INT8 ConvRot ‡ (18 GiB, ~3.9 s/image) | HunyuanImage 3.0 Instruct / Instruct-Distil W4A8 † (24 GiB, ~11 s/image) |
| 8x80 | Qwen-Image-2.1 BF16 ‡ (31 GiB, ~8.2 s/image) | Qwen-Image-2.1 INT8 ConvRot ‡ (18 GiB, ~3.9 s/image) | HunyuanImage 3.0 Instruct / Instruct-Distil W4A8 † (24 GiB, ~11 s/image) |
| 8xb200 | Qwen-Image-2.1 BF16 ‡ (31 GiB, ~4.1 s/image) | Qwen-Image-2.1 INT8 ConvRot ‡ (18 GiB, ~2.0 s/image) | HunyuanImage 3.0 Instruct / Instruct-Distil W4A8 † (24 GiB, ~5.4 s/image) |
| spark | Qwen-Image-2.1 BF16 ‡ (31 GiB, ~53 s/image) | Qwen-Image-2.1 INT8 ConvRot ‡ (18 GiB, ~25 s/image) | HunyuanImage 3.0 Instruct / Instruct-Distil W4A8 † (24 GiB, ~69 s/image) |
| 2xspark | Qwen-Image-2.1 BF16 ‡ (31 GiB, ~53 s/image) | Qwen-Image-2.1 INT8 ConvRot ‡ (18 GiB, ~25 s/image) | HunyuanImage 3.0 Instruct / Instruct-Distil W4A8 † (24 GiB, ~69 s/image) |
| mac-64 | none fits | none fits | none fits |
| mac-128 | none fits | none fits | none fits |
| mac-192 | none fits | none fits | none fits |
| mac-512 | none fits | none fits | none fits |

### Background removal (`cutout`)

Light: everything good fits 8 GB; more VRAM only adds batch throughput.

| Setup | Best quality | Balanced | Commercial use allowed |
|---|---|---|---|
| cpu | none fits | none fits | none fits |
| 8 | Lucida FP16 (5 GiB, ~1.4 s/image) | same | same |
| 12 | Lucida FP16 (5 GiB, ~0.67 s/image) | same | same |
| 16 | Lucida FP16 (5 GiB, ~0.43 s/image) | same | same |
| 24 | Lucida FP16 (5 GiB, ~0.25 s/image) | same | same |
| 32 | Lucida FP16 (5 GiB, ~0.20 s/image) | same | same |
| 48 | Lucida FP16 (5 GiB, ~0.23 s/image) | same | same |
| 80 | Lucida FP16 (5 GiB, ~0.10 s/image) | same | same |
| 96 | Lucida FP16 (5 GiB, ~0.17 s/image) | same | same |
| 2x24 | Lucida FP16 (5 GiB, ~0.25 s/image) | same | same |
| 2x32 | Lucida FP16 (5 GiB, ~0.20 s/image) | same | same |
| 4x32 | Lucida FP16 (5 GiB, ~0.20 s/image) | same | same |
| 2x80 | Lucida FP16 (5 GiB, ~0.10 s/image) | same | same |
| 4x80 | Lucida FP16 (5 GiB, ~0.10 s/image) | same | same |
| 8x80 | Lucida FP16 (5 GiB, ~0.10 s/image) | same | same |
| 8xb200 | Lucida FP16 (5 GiB, ~0.05 s/image) | same | same |
| spark | Lucida FP16 (5 GiB, ~0.67 s/image) | same | same |
| 2xspark | Lucida FP16 (5 GiB, ~0.67 s/image) | same | same |
| mac-64 | Lucida FP16 (5 GiB, ~1.2 s/image) | same | same |
| mac-128 | Lucida FP16 (5 GiB, ~1.2 s/image) | same | same |
| mac-192 | Lucida FP16 (5 GiB, ~1.5 s/image) | same | same |
| mac-512 | Lucida FP16 (5 GiB, ~0.73 s/image) | same | same |

### Upscaling (`upscale`)

Image restoration and upscaling (SeedVR2 also does video).

| Setup | Best quality | Balanced | Commercial use allowed |
|---|---|---|---|
| cpu | none fits | none fits | none fits |
| 8 | SeedVR2 3B GGUF Q4_K_M (6 GiB, ~209 s/image) | Real-ESRGAN x4plus FP16 (3 GiB, ~7.0 s/image) | same |
| 12 | SeedVR2 7B NVFP4 (9 GiB, ~40 s/image) | same | same |
| 16 | SeedVR2 7B INT8 convrot (13 GiB, ~43 s/image) | same | same |
| 24 | SeedVR2 7B FP16 (20 GiB, ~25 s/image) | same | same |
| 32 | SeedVR2 7B FP16 (20 GiB, ~20 s/image) | SeedVR2 7B NVFP4 (9 GiB, ~12 s/image) | same |
| 48 | SeedVR2 7B FP16 (20 GiB, ~23 s/image) | same | same |
| 80 | SeedVR2 7B FP16 (20 GiB, ~10 s/image) | same | same |
| 96 | SeedVR2 7B FP16 (20 GiB, ~17 s/image) | SeedVR2 7B NVFP4 (9 GiB, ~10 s/image) | same |
| 2x24 | SeedVR2 7B FP16 (20 GiB, ~25 s/image) | same | same |
| 2x32 | SeedVR2 7B FP16 (20 GiB, ~20 s/image) | SeedVR2 7B NVFP4 (9 GiB, ~12 s/image) | same |
| 4x32 | SeedVR2 7B FP16 (20 GiB, ~20 s/image) | SeedVR2 7B NVFP4 (9 GiB, ~12 s/image) | same |
| 2x80 | SeedVR2 7B FP16 (20 GiB, ~10 s/image) | same | same |
| 4x80 | SeedVR2 7B FP16 (20 GiB, ~10 s/image) | same | same |
| 8x80 | SeedVR2 7B FP16 (20 GiB, ~10 s/image) | same | same |
| 8xb200 | SeedVR2 7B FP16 (20 GiB, ~5.2 s/image) | SeedVR2 7B NVFP4 (9 GiB, ~3.1 s/image) | same |
| spark | SeedVR2 7B FP16 (20 GiB, ~67 s/image) | SeedVR2 7B NVFP4 (9 GiB, ~40 s/image) | same |
| 2xspark | SeedVR2 7B FP16 (20 GiB, ~67 s/image) | SeedVR2 7B NVFP4 (9 GiB, ~40 s/image) | same |
| mac-64 | SeedVR2 7B FP16 (20 GiB, ~123 s/image) | same | same |
| mac-128 | SeedVR2 7B FP16 (20 GiB, ~123 s/image) | same | same |
| mac-192 | SeedVR2 7B FP16 (20 GiB, ~155 s/image) | same | same |
| mac-512 | SeedVR2 7B FP16 (20 GiB, ~73 s/image) | same | same |

### Video (loops, image and text to video) (`video`)

bromigOS's main use is seamless loops from a still (start frame = end frame): models with a native first-and-last-frame input rank first.

| Setup | Best quality | Balanced | Commercial use allowed |
|---|---|---|---|
| cpu | none fits | none fits | none fits |
| 8 | Wan 2.2 Fun 5B InP BF16 (8 GiB, ~21 min/clip) | same | same |
| 12 | Wan 2.2 I2V A14B GGUF Q3_K_M (10 GiB + RAM, ~4.5 min/clip) | same | same |
| 16 | Wan 2.2 I2V A14B FP8 with block swap (WanVideoWrapper) (12 GiB + RAM, ~4.5 min/clip) | same | same |
| 24 | Wan 2.2 I2V A14B FP8 e4m3 scaled (21 GiB, ~3.2 min/clip) | LTX-2.3 22B GGUF Q4_K_M (16 GiB, ~0.51 min/clip) | same |
| 32 | Wan 2.2 I2V A14B FP8 e4m3 scaled (21 GiB, ~2.5 min/clip) | LTX-2.3 22B FP8 (24 GiB, ~0.42 min/clip) | same |
| 48 | Wan 2.2 I2V A14B FP16 (32 GiB, ~4.0 min/clip) | LTX-2.3 22B FP8 (24 GiB, ~0.48 min/clip) | same |
| 80 | Wan 2.2 I2V A14B FP16 (32 GiB, ~1.8 min/clip) | Wan 2.2 I2V A14B FP8 scaled, 4-step distilled full checkpoints (21 GiB, ~0.52 min/clip) | same |
| 96 | Wan 2.2 I2V A14B FP16 (32 GiB, ~3.0 min/clip) | LTX-2.3 22B FP8 (24 GiB, ~0.36 min/clip) | same |
| 2x24 | Wan 2.2 I2V A14B FP8 e4m3 scaled (21 GiB, ~3.2 min/clip) | LTX-2.3 22B GGUF Q4_K_M (16 GiB, ~0.51 min/clip) | same |
| 2x32 | Wan 2.2 I2V A14B split across GPUs (raylight) (49 GiB, ~1.2 min/clip) | LTX-2.5 22B split across GPUs (raylight) (49 GiB, ~0.62 min/clip) | same |
| 4x32 | Wan 2.2 I2V A14B split across GPUs (raylight) (50 GiB, ~0.77 min/clip) | LTX-2.5 22B split across GPUs (raylight) (50 GiB, ~0.38 min/clip) | same |
| 2x80 | Wan 2.2 I2V A14B split across GPUs (raylight) (49 GiB, ~0.65 min/clip) | LTX-2.5 22B split across GPUs (raylight) (49 GiB, ~0.33 min/clip) | same |
| 4x80 | Wan 2.2 I2V A14B split across GPUs (raylight) (50 GiB, ~0.40 min/clip) | LTX-2.5 22B split across GPUs (raylight) (50 GiB, ~0.20 min/clip) | same |
| 8x80 | Wan 2.2 I2V A14B split across GPUs (raylight) (53 GiB, ~0.24 min/clip) | same | same |
| 8xb200 | Wan 2.2 I2V A14B split across GPUs (raylight) (50 GiB, ~0.20 min/clip) | same | same |
| spark | Wan 2.2 I2V A14B FP16 (32 GiB, ~12 min/clip) | LTX-2.3 22B FP8 (24 GiB, ~1.4 min/clip) | same |
| 2xspark | Wan 2.2 I2V A14B FP16 (32 GiB, ~12 min/clip) | LTX-2.3 22B FP8 (24 GiB, ~1.4 min/clip) | same |
| mac-64 | none fits | none fits | none fits |
| mac-128 | none fits | none fits | none fits |
| mac-192 | none fits | none fits | none fits |
| mac-512 | none fits | none fits | none fits |

### Image to 3D (`3d`)

Textured (PBR) GLB first; shape-only is faster and lighter.

| Setup | Best quality | Balanced | Commercial use allowed |
|---|---|---|---|
| cpu | none fits | none fits | none fits |
| 8 | Hunyuan3D 2.0 / 2mini / 2mv FP16 † (6 GiB, ~139 s/mesh) | same | same |
| 12 | Hunyuan3D 2.1 FP16 † (10 GiB, ~84 s/mesh) | same | same |
| 16 | TRELLIS.2-4B INT8 convrot (14 GiB, ~259 s/mesh) | same | same |
| 24 | Pixal3D INT8 convrot DiT, BF16 VAEs, FP32 DINOv3 (16 GiB, ~304 s/mesh) | TRELLIS.2-4B INT8 convrot (14 GiB, ~152 s/mesh) | same |
| 32 | Pixal3D BF16 (24 GiB, ~180 s/mesh) | TRELLIS.2-4B BF16 (24 GiB, ~110 s/mesh) | same |
| 48 | Pixal3D BF16 (24 GiB, ~207 s/mesh) | TRELLIS.2-4B BF16 (24 GiB, ~126 s/mesh) | same |
| 80 | Pixal3D BF16 (24 GiB, ~94 s/mesh) | TRELLIS.2-4B BF16 (24 GiB, ~57 s/mesh) | same |
| 96 | Pixal3D BF16 (24 GiB, ~157 s/mesh) | TRELLIS.2-4B BF16 (24 GiB, ~96 s/mesh) | same |
| 2x24 | Pixal3D INT8 convrot DiT, BF16 VAEs, FP32 DINOv3 (16 GiB, ~304 s/mesh) | TRELLIS.2-4B INT8 convrot (14 GiB, ~152 s/mesh) | same |
| 2x32 | Pixal3D BF16 (24 GiB, ~180 s/mesh) | TRELLIS.2-4B BF16 (24 GiB, ~110 s/mesh) | same |
| 4x32 | Pixal3D BF16 (24 GiB, ~180 s/mesh) | TRELLIS.2-4B BF16 (24 GiB, ~110 s/mesh) | same |
| 2x80 | Pixal3D BF16 (24 GiB, ~94 s/mesh) | TRELLIS.2-4B BF16 (24 GiB, ~57 s/mesh) | same |
| 4x80 | Pixal3D BF16 (24 GiB, ~94 s/mesh) | TRELLIS.2-4B BF16 (24 GiB, ~57 s/mesh) | same |
| 8x80 | Pixal3D BF16 (24 GiB, ~94 s/mesh) | TRELLIS.2-4B BF16 (24 GiB, ~57 s/mesh) | same |
| 8xb200 | Pixal3D BF16 (24 GiB, ~47 s/mesh) | TRELLIS.2-4B BF16 (24 GiB, ~29 s/mesh) | same |
| spark | Pixal3D BF16 (24 GiB, ~607 s/mesh) | TRELLIS.2-4B BF16 (24 GiB, ~371 s/mesh) | same |
| 2xspark | Pixal3D BF16 (24 GiB, ~607 s/mesh) | TRELLIS.2-4B BF16 (24 GiB, ~371 s/mesh) | same |
| mac-64 | none fits | none fits | none fits |
| mac-128 | none fits | none fits | none fits |
| mac-192 | none fits | none fits | none fits |
| mac-512 | none fits | none fits | none fits |

### Text to speech (`tts`)

VECTOR's voice: voice design, cloning and low-latency streaming. Ready means the voice service runs it today.

| Setup | Best quality | Balanced | Commercial use allowed |
|---|---|---|---|
| cpu | Kokoro 82M v1.0 FP32 (CPU, ~2.0 x realtime) | same | same |
| 8 | Qwen3-TTS BF16 (3 GiB, ~1.9 x realtime) | same | same |
| 12 | Qwen3-TTS BF16 (6 GiB, ~2.7 x realtime) | same | same |
| 16 | Qwen3-TTS BF16 (6 GiB, ~2.8 x realtime) | same | same |
| 24 | Qwen3-TTS BF16 (6 GiB, ~4.0 x realtime) | same | same |
| 32 | Qwen3-TTS BF16 (6 GiB, ~7.1 x realtime) | same | same |
| 48 | Qwen3-TTS BF16 (6 GiB, ~3.8 x realtime) | same | same |
| 80 | Qwen3-TTS BF16 (6 GiB, ~13 x realtime) | same | same |
| 96 | Qwen3-TTS BF16 (6 GiB, ~7.1 x realtime) | same | same |
| 2x24 | Qwen3-TTS BF16 (6 GiB, ~4.0 x realtime) | same | same |
| 2x32 | Qwen3-TTS BF16 (6 GiB, ~7.1 x realtime) | same | same |
| 4x32 | Qwen3-TTS BF16 (6 GiB, ~7.1 x realtime) | same | same |
| 2x80 | Qwen3-TTS BF16 (6 GiB, ~13 x realtime) | same | same |
| 4x80 | Qwen3-TTS BF16 (6 GiB, ~13 x realtime) | same | same |
| 8x80 | Qwen3-TTS BF16 (6 GiB, ~13 x realtime) | same | same |
| 8xb200 | Qwen3-TTS BF16 (6 GiB, ~32 x realtime) | same | same |
| spark | Qwen3-TTS BF16 (3 GiB, ~1.9 x realtime) | same | same |
| 2xspark | Qwen3-TTS BF16 (3 GiB, ~1.9 x realtime) | same | same |
| mac-64 | Kokoro 82M v1.0 FP32 (CPU, ~2.0 x realtime) | same | same |
| mac-128 | Kokoro 82M v1.0 FP32 (CPU, ~2.0 x realtime) | same | same |
| mac-192 | Kokoro 82M v1.0 FP32 (CPU, ~2.0 x realtime) | same | same |
| mac-512 | Kokoro 82M v1.0 FP32 (CPU, ~2.0 x realtime) | same | same |

### Speech to text (`stt`)

VECTOR's hearing: dictation and commands.

| Setup | Best quality | Balanced | Commercial use allowed |
|---|---|---|---|
| cpu | OpenAI Whisper large-v3-turbo INT8 (CPU, ~1.7 x realtime) | same | same |
| 8 | OpenAI Whisper large-v3 FP16 (4 GiB, ~6.4 x realtime) | Distil-Whisper large-v3.5 FP16 (2 GiB, ~16 x realtime) | same |
| 12 | OpenAI Whisper large-v3 FP16 (4 GiB, ~13 x realtime) | Distil-Whisper large-v3.5 FP16 (2 GiB, ~34 x realtime) | same |
| 16 | OpenAI Whisper large-v3 FP16 (4 GiB, ~21 x realtime) | Distil-Whisper large-v3.5 FP16 (2 GiB, ~53 x realtime) | same |
| 24 | OpenAI Whisper large-v3 FP16 (4 GiB, ~35 x realtime) | Distil-Whisper large-v3.5 FP16 (2 GiB, ~90 x realtime) | same |
| 32 | OpenAI Whisper large-v3 FP16 (4 GiB, ~44 x realtime) | Distil-Whisper large-v3.5 FP16 (2 GiB, ~114 x realtime) | same |
| 48 | OpenAI Whisper large-v3 FP16 (4 GiB, ~39 x realtime) | Distil-Whisper large-v3.5 FP16 (2 GiB, ~99 x realtime) | same |
| 80 | OpenAI Whisper large-v3 FP16 (4 GiB, ~85 x realtime) | Distil-Whisper large-v3.5 FP16 (2 GiB, ~218 x realtime) | same |
| 96 | OpenAI Whisper large-v3 FP16 (4 GiB, ~51 x realtime) | Distil-Whisper large-v3.5 FP16 (2 GiB, ~131 x realtime) | same |
| 2x24 | OpenAI Whisper large-v3 FP16 (4 GiB, ~35 x realtime) | Distil-Whisper large-v3.5 FP16 (2 GiB, ~90 x realtime) | same |
| 2x32 | OpenAI Whisper large-v3 FP16 (4 GiB, ~44 x realtime) | Distil-Whisper large-v3.5 FP16 (2 GiB, ~114 x realtime) | same |
| 4x32 | OpenAI Whisper large-v3 FP16 (4 GiB, ~44 x realtime) | Distil-Whisper large-v3.5 FP16 (2 GiB, ~114 x realtime) | same |
| 2x80 | OpenAI Whisper large-v3 FP16 (4 GiB, ~85 x realtime) | Distil-Whisper large-v3.5 FP16 (2 GiB, ~218 x realtime) | same |
| 4x80 | OpenAI Whisper large-v3 FP16 (4 GiB, ~85 x realtime) | Distil-Whisper large-v3.5 FP16 (2 GiB, ~218 x realtime) | same |
| 8x80 | OpenAI Whisper large-v3 FP16 (4 GiB, ~85 x realtime) | Distil-Whisper large-v3.5 FP16 (2 GiB, ~218 x realtime) | same |
| 8xb200 | OpenAI Whisper large-v3 FP16 (4 GiB, ~170 x realtime) | Distil-Whisper large-v3.5 FP16 (2 GiB, ~436 x realtime) | same |
| spark | OpenAI Whisper large-v3 FP16 (4 GiB, ~13 x realtime) | Distil-Whisper large-v3.5 FP16 (2 GiB, ~34 x realtime) | same |
| 2xspark | OpenAI Whisper large-v3 FP16 (4 GiB, ~13 x realtime) | Distil-Whisper large-v3.5 FP16 (2 GiB, ~34 x realtime) | same |
| mac-64 | OpenAI Whisper large-v3-turbo INT8 (CPU, ~1.7 x realtime) | same | same |
| mac-128 | OpenAI Whisper large-v3-turbo INT8 (CPU, ~1.7 x realtime) | same | same |
| mac-192 | OpenAI Whisper large-v3-turbo INT8 (CPU, ~1.7 x realtime) | same | same |
| mac-512 | OpenAI Whisper large-v3-turbo INT8 (CPU, ~1.7 x realtime) | same | same |

### OCR and document parsing (`ocr`)

Pages to Markdown: small specialists beat big VLMs on page-to-Markdown; a big VLM is better for questions about documents.

| Setup | Best quality | Balanced | Commercial use allowed |
|---|---|---|---|
| cpu | PaddleOCR-VL-1.6 GGUF Q8_0 + BF16 mmproj (CPU, ~82 s/page) | Surya OCR 2 GGUF (CPU, ~15 s/page) | same |
| 8 | PaddleOCR-VL-1.6 BF16 (6 GiB, ~5.5 s/page) | same | same |
| 12 | PaddleOCR-VL-1.6 BF16 (6 GiB, ~2.7 s/page) | same | same |
| 16 | PaddleOCR-VL-1.6 BF16 (6 GiB, ~1.7 s/page) | same | same |
| 24 | PaddleOCR-VL-1.6 BF16 (6 GiB, ~1.0 s/page) | same | same |
| 32 | PaddleOCR-VL-1.6 BF16 (6 GiB, ~0.79 s/page) | same | same |
| 48 | Infinity-Parser2-Pro FP8 (42 GiB, ~2.7 s/page) | PaddleOCR-VL-1.6 BF16 (6 GiB, ~0.91 s/page) | same |
| 80 | Infinity-Parser2-Pro FP8 (42 GiB, ~1.2 s/page) | PaddleOCR-VL-1.6 BF16 (6 GiB, ~0.41 s/page) | same |
| 96 | Infinity-Parser2-Pro BF16 (82 GiB, ~2.1 s/page) | PaddleOCR-VL-1.6 BF16 (6 GiB, ~0.69 s/page) | same |
| 2x24 | Infinity-Parser2-Pro FP8 (43 GiB, ~1.9 s/page) | PaddleOCR-VL-1.6 BF16 (7 GiB, ~0.62 s/page) | same |
| 2x32 | Infinity-Parser2-Pro FP8 (43 GiB, ~1.5 s/page) | PaddleOCR-VL-1.6 BF16 (7 GiB, ~0.49 s/page) | same |
| 4x32 | Infinity-Parser2-Pro BF16 (84 GiB, ~0.91 s/page) | PaddleOCR-VL-1.6 BF16 (8 GiB, ~0.30 s/page) | same |
| 2x80 | Infinity-Parser2-Pro BF16 (81 GiB, ~0.77 s/page) | PaddleOCR-VL-1.6 BF16 (7 GiB, ~0.26 s/page) | same |
| 4x80 | Infinity-Parser2-Pro BF16 (84 GiB, ~0.48 s/page) | PaddleOCR-VL-1.6 BF16 (8 GiB, ~0.16 s/page) | same |
| 8x80 | Infinity-Parser2-Pro BF16 (87 GiB, ~0.28 s/page) | PaddleOCR-VL-1.6 BF16 (8 GiB, ~0.16 s/page) | same |
| 8xb200 | Infinity-Parser2-Pro BF16 (87 GiB, ~0.14 s/page) | same | same |
| spark | Infinity-Parser2-Pro BF16 (82 GiB, ~8.0 s/page) | PaddleOCR-VL-1.6 BF16 (6 GiB, ~2.7 s/page) | same |
| 2xspark | Infinity-Parser2-Pro BF16 (82 GiB, ~8.0 s/page) | PaddleOCR-VL-1.6 BF16 (6 GiB, ~2.7 s/page) | same |
| mac-64 | PaddleOCR-VL-1.6 BF16 (3 GiB, ~4.9 s/page) | same | same |
| mac-128 | PaddleOCR-VL-1.6 BF16 (3 GiB, ~4.9 s/page) | same | same |
| mac-192 | PaddleOCR-VL-1.6 BF16 (3 GiB, ~6.1 s/page) | same | same |
| mac-512 | PaddleOCR-VL-1.6 BF16 (3 GiB, ~2.9 s/page) | same | same |

### Screen understanding (`vision`)

'Look at my screen': describe, read and point at UI. A natively multimodal LLM serves it with no extra VRAM.

| Setup | Best quality | Balanced | Commercial use allowed |
|---|---|---|---|
| cpu | Holo4 35B-A3B GGUF Q4_K_M + mmproj-F16 (CPU, ~21 tok/s) | same | same |
| 8 | Holo4 35B-A3B GGUF Q4_K_M + mmproj-F16 (CPU, ~21 tok/s) | Qwen3.6-35B-A3B GGUF UD-Q4_K_M + --n-cpu-moe (6 GiB + RAM, ~34 tok/s) | same |
| 12 | Holo4 35B-A3B GGUF Q4_K_M + mmproj-F16 (CPU, ~21 tok/s) | Qwen3.5-9B GGUF Q4_K_M (8 GiB, ~88 tok/s) | same |
| 16 | Qwen3.8-27B GGUF UD-IQ3_XXS + mmproj-F16 (15 GiB, ~32 tok/s) | Qwen3.5-9B GGUF Q4_K_M (8 GiB, ~93 tok/s) | same |
| 24 | Qwen3.8-27B GGUF UD-Q5_K_M (22 GiB, ~40 tok/s) | Holo4 35B-A3B NVFP4 (21 GiB, ~207 tok/s) | same |
| 32 | Qwen3.8-27B GGUF Q8_0 (30 GiB, ~34 tok/s) | Qwen3.8-27B GGUF UD-Q4_K_XL (20 GiB, ~78 tok/s) | same |
| 48 | Qwen3.8-27B GGUF Q8_0 (30 GiB, ~19 tok/s) | Holo4 35B-A3B FP8 (38 GiB, ~132 tok/s) | same |
| 80 | Qwen3.8-27B BF16 (55 GiB, ~34 tok/s) | Qwen3.8-27B GGUF UD-Q6_K (25 GiB, ~85 tok/s) | same |
| 96 | Qwen3.8-27B BF16 (55 GiB, ~19 tok/s) | Qwen3.8-Flash-Next GGUF UD-IQ4_XS (89 GiB, ~163 tok/s) | same |
| 2x24 | Qwen3.8-27B FP8 block (32 GiB, ~30 tok/s) | Holo4 35B-A3B FP8 (38 GiB, ~191 tok/s) | same |
| 2x32 | Qwen3.8-27B BF16 (55 GiB, ~30 tok/s) | Qwen3.8-27B NVFP4 (23 GiB, ~99 tok/s) | same |
| 4x32 | Qwen3.8-27B BF16 (56 GiB, ~60 tok/s) | Qwen3.8-27B FP8 block (32 GiB, ~82 tok/s) | same |
| 2x80 | Qwen3.8-Flash-Next NVFP4 experts + FP8 n-gram table (128 GiB, ~298 tok/s) | same | same |
| 4x80 | Qwen3.8-Flash-Next GGUF Q8_0 (182 GiB, ~179 tok/s) | same | same |
| 8x80 | Qwen3.8-Flash-Next BF16 (345 GiB, ~308 tok/s) | same | same |
| 8xb200 | Qwen3.8-Flash-Next BF16 (345 GiB, ~396 tok/s) | same | same |
| spark | Qwen3.8-Flash-Next GGUF UD-IQ4_XS (89 GiB, ~34 tok/s) | Holo4 35B-A3B NVFP4 (21 GiB, ~80 tok/s) | same |
| 2xspark | Qwen3.8-Flash-Next NVFP4 experts + FP8 n-gram table (128 GiB, ~54 tok/s) | Holo4 35B-A3B NVFP4 (21 GiB, ~80 tok/s) | same |
| mac-64 | Qwen3.8-27B MLX 8-bit (31 GiB, ~16 tok/s) | Qwen3.6-35B-A3B GGUF Q8_0 (36 GiB, ~86 tok/s) | same |
| mac-128 | Qwen3.8-27B MLX 8-bit (31 GiB, ~16 tok/s) | Qwen3.8-Flash-Next GGUF UD-IQ4_XS (89 GiB, ~64 tok/s) | same |
| mac-192 | Qwen3.8-27B MLX 8-bit (31 GiB, ~24 tok/s) | Qwen3.8-Flash-Next GGUF UD-IQ4_XS (89 GiB, ~88 tok/s) | same |
| mac-512 | Qwen3.8-Flash-Next GGUF Q8_0 (181 GiB, ~66 tok/s) | Qwen3.8-Flash-Next GGUF UD-IQ4_XS (89 GiB, ~90 tok/s) | same |

## Sources

The leaderboards the quality scores come from (October 2026):
[LMArena text-to-image and image edit](https://arena.ai/leaderboard/text-to-image),
[Artificial Analysis](https://artificialanalysis.ai/) (the Intelligence Index, the image,
video and speech arenas),
[Open ASR Leaderboard results](https://huggingface.co/datasets/hf-audio/open-asr-leaderboard-results),
[MTEB](https://huggingface.co/spaces/mteb/leaderboard),
[OmniDocBench](https://github.com/opendatalab/OmniDocBench),
[olmOCR-bench](https://huggingface.co/datasets/allenai/olmOCR-bench).
Runtimes and memory: [ComfyUI's tutorials](https://docs.comfy.org/),
[vLLM's supported models](https://docs.vllm.ai/en/latest/models/supported_models/),
[vLLM recipes](https://recipes.vllm.ai/), the NVIDIA DGX Spark forum's measured benchmarks.
Every model in `models.toml` lists the model cards and benchmarks it was researched from
(`cite`), and its licence links to the licence text.
