# Where AI runs: targets.toml

bromigOS sends its AI work to one of three places: your homelab, this machine or a paid
cloud service. One setting, `targets.toml`, says which, in order of preference. This page
describes the file and the `bromigos target` command for someone extending or debugging
them. For using it, read the manual's [Creating with AI](../manual/src/where-ai-runs.md).

<!-- site:targets -->
## Targets and services

A *target* is a place AI work can run:

| Target | What it is |
|---|---|
| `homelab` | your homelab's services, named once in `homelab.toml` ([homelab.md](homelab.md)) |
| `local` | this machine: a ComfyUI, an Ollama, VECTOR's own voice on your GPU or CPU |
| `cloud` | hosted services that cost money: nolgia's credits, a hosted LLM endpoint |

A *service* is one kind of AI work. Ten services follow the targets. VECTOR is the
desktop's AI assistant, and three of the services are his.

| Service | Used by | On `homelab` | On `local` | On `cloud` |
|---|---|---|---|---|
| `image.generate`, `image.edit`, `image.cutout`, `model3d.generate` | `bromigos art`, VECTOR's `create` tool | `comfyui:homelab` | `comfyui:local` | `nolgia` |
| `image.upscale`, `video.upscale` | `bromigos art`, the lab's upscale jobs | `comfyui:homelab` | `comfyui:local` | none: there's no cloud model |
| `video.loop` | `bromigos art`, the lab's video jobs | `comfyui:homelab` | `comfyui:local` | `nolgia` |
| `voice.tts` | VECTOR's voice | `lab`, the voice service | `qwen`, then `kokoro` | none |
| `voice.stt` | VECTOR's hearing | `lab` | `local` (Whisper) | none |
| `llm` | VECTOR's brain | the lab's OpenAI-compatible server | Ollama | a hosted endpoint |

A ComfyUI only counts for `video.loop` when it has the Wan 2.2 model files. bromigOS
tries Wan 2.2 I2V-A14B first, then TI2V-5B. [art.md](art.md) has the workflows.

A service tries its targets in order. It skips a target that doesn't have the service or
doesn't answer. A target doesn't have a service when its address isn't set, the address
doesn't resolve, or a ComfyUI lacks the workflow's model files.

## Change where AI runs

To put a target first, name it:

```bash
bromigos target local
```

The other targets keep their places. Putting a target first never adds the cloud. The
cloud stays out unless it was already in the order, or you name it.

Every change is in force at once, and nothing needs a restart:

- `bromigos art` reads the file on every run.
- VECTOR's voice reads it before his next line.
- VECTOR's brain reads it before his next turn.

### Every command

| Command | What it does |
|---|---|
| `bromigos target` | Show each service, what it would use now, and whether that answers. |
| `bromigos target check` | Probe every target of every service. |
| `bromigos target probe video.loop` | Probe one service. For a ComfyUI, this checks the workflow's files and the free VRAM. |
| `bromigos target homelab` | Put the homelab first. |
| `bromigos target local` | Put this machine first. |
| `bromigos target cloud` | Put the cloud first. This costs money. |
| `bromigos target local --exclusive` | Use this machine only, with no fallback. |
| `bromigos target local --only llm` | Change one service. Repeat `--only` for more. |
| `bromigos target order homelab local` | Set the exact order. Leave `cloud` out to never use it. |
| `bromigos target reset` | Make every service follow the global order again. |
| `bromigos target resolve voice.tts` | Print, as JSON, what a service tries in order. VECTOR asks this. It doesn't probe. |

`check` and `probe` end with a note when a better model would fit one of your lab's GPUs.
That note comes from the lab model catalog ([lab-models.md](lab-models.md)). Nothing gets
installed. Installing models is a job for `bromigos lab models`.

### On a first run

`bromigos setup targets` asks the same question. It looks for a homelab with AI services,
a GPU on this machine, and the `nolgia` command. Its default order is:

1. `homelab`, when `homelab.toml` has a ComfyUI, a voice service or a model server.
2. `local`.
3. `cloud`, only when there's no homelab, no GPU here, and `nolgia` is installed.

You can also let a single service use the cloud last, for example `video.loop` on a
machine whose ComfyUI lacks Wan 2.2. Unattended, that's `--cloud-for video.loop`.

## The file

The packaged default is `/usr/share/bromigos/default/targets.toml`. Yours is
`~/.config/bromigos/targets.toml`, merged over it key by key. To use another file, set
`$BROMIGOS_TARGETS_CONFIG`.

```toml
format = 1

[targets]
order = ["homelab", "local"]          # leave out "cloud" to never use it

[service."video.loop"]                # one service's own order (bromigos target … --only)
order = ["homelab", "local", "cloud"]

[targets.homelab]                     # the packaged defaults, for reference
comfyui = "@homelab:comfyui"
voice = "@homelab:voice"
llm = "@homelab:litellm"              # /v1 is added when the URL has no path
llm_key_file = "~/.local/share/bromigos/litellm-key"

[targets.local]
comfyui = "http://127.0.0.1:8188"
voice = "builtin"                     # builtin, kokoro or off
llm = "http://localhost:11434/v1"

[targets.cloud]
nolgia = true
# llm = "https://llm.example.org/v1"
# llm_key_file = "~/.config/bromigos/llm-key"
```

The packaged order is `homelab`, `local`, `cloud`. Your file usually replaces it, because
`bromigos setup targets` writes your own order.

`voice = "builtin"` means VECTOR's designed voice on the GPU, with Kokoro on the CPU as
the fallback. `kokoro` means Kokoro only. `off` turns the local voice off.

### Addresses and keys

Every address is a URL or a reference. With references, the file can live in a public
dotfiles repository.

| Reference | Resolves to |
|---|---|
| `@homelab:<source>` | the endpoint of that source in `homelab.toml` |
| `@private:dotted.key` | a key in the private overlay, the encrypted file `bromigos private` manages |
| `@env:NAME` | an environment variable |
| `@file:~/path` | a file's content |
| `@vault:kv/path#field` | a field in Vault, read with the `vault` command |

The file never holds a key. The brain's key is a file path, `llm_key_file`.

## Settings that win over the targets

Some settings pin a service to one place. They take priority over `targets.toml`:

- **A `providers` list in `create.toml`.** A capability with its own list uses that list,
  not the targets. The packaged default lists none. [art.md](art.md) describes the file.
  `bromigos setup create` offers "follow where AI runs" first.
- **A `[comfyui.homelab]` or `[comfyui.local]` table in `create.toml`.** It overrides that
  target's ComfyUI address.
- **A pin in a world's `art.toml`.** An asset's `model = …` or `provider = …` wins over
  both files, so a world's art stays reproducible.
- **`base_url` under `[llm]` in VECTOR's `vector.toml`.** It pins his brain. Remove it to
  follow the targets.
- **`lab.url` in VECTOR's `voice.json`.** It pins the address of his lab voice.

Without a `targets.toml` of your own, VECTOR keeps following `voice.json` and
`vector.toml`. The creation tools follow the packaged order.

## Cost safety

- The cloud runs a service only when the cloud is in that service's order.
- Every `bromigos art make` reports where it ran. Its `--json` output and its log carry
  `target`, `provider` and `credits`.
- VECTOR never reaches the cloud on his own. His `create` tool takes the first ComfyUI on
  a free target, homelab or local, whatever the order, with `--max-credits 0`. nolgia is
  a separate tool, used only when you ask for it by name.
- VECTOR's guard refuses these from his terminal: `bromigos target` with a switch,
  `bromigos setup targets`, `bromigos setup create`, and writes to `targets.toml` or
  `create.toml`. Where your work runs, and whether it costs money, stays your decision.
