# Making a world's art

A world's art is data, like its colours. `themes/<world>/art.toml` lists every asset the
world is made from, with the recipe for each: concept paintings, edits, actor sprites,
video loops, cutouts and local steps. `bromigos art` prices what isn't made yet, makes
it, and logs every job. Running it again skips whatever is made and unchanged.

Art can be made in two places:

- **A ComfyUI** on your homelab or on this machine. It costs nothing, and the weights'
  licences apply.
- **nolgia**, a paid service that runs hosted image, video and 3D models, through its
  official Rust SDK ([`nolgia`](https://docs.rs/nolgia)). It costs credits.

Which one makes what is a setting, described [below](#creation-providers).

This page is for contributors who make a world's art. A *world* is a theme whose
wallpaper is a living scene. The theme format is in [theming.md](theming.md), and where
AI work runs is in [targets.md](targets.md). The [glossary](../manual/src/glossary.md)
defines bromigOS's terms.

<!-- site:art-commands -->
## Make the art

```bash
bromigos art status mire              # what's made, missing, stale or new (no network)
bromigos art plan mire                # what a run would make, and the exact credits
bromigos art run mire                 # make it, and log each job
bromigos art run mire boot --force    # make one asset again
```

`status` also says which backends answer: nolgia's credentials, and the ComfyUI.

`--dir` names the world's theme folder. Without it, `bromigos art` looks for
`themes/<world>/` in the checkout you're in, then `~/.config/bromigos/themes/<world>/`,
then the shipped themes.

The code is the `bromigos-art` crate in `core/`. [core/README.md](../core/README.md) has
every option and the JSON documents.

## Where the files live

| Path | What it holds | In Git | Packaged |
|---|---|---|---|
| `themes/<world>/art.toml` | The recipes | yes | no |
| `themes/<world>/art.log.jsonl` | Every job and marked asset, appended | yes | no |
| `themes/<world>/art/` | Working sources: paintings, references, masks, raw clips | no | no |
| `themes/<world>/backgrounds/`, `live/` | What the world ships | yes | yes |

`themes/.gitignore` keeps `art/` out of Git. `bromigos theme set` never copies
`art.toml`, `art.log.jsonl` or `art/` into the rendered theme.

Sources under `art/` stay on the machine that made them. On another machine, their
assets show as `missing`. They're only made again if something that reads them has to
be.

### Local finishing tools

Two tools in `theme/tools/` finish what a ComfyUI or nolgia makes:

- **`glow-loop.py RAW OUT`** turns a raw clip of a glowing creature on black into a
  world's loop. It cuts at the frame most like the first, so the loop wraps. It crops to
  the creature, sizes it near how big it's drawn, and lifts near-black to black, so the
  creature leaves no box around it.
  - `--stacked LO HI [--fill R]` writes the stacked-alpha layout instead. Use it for a
    dark body that should hide the water behind it, like Tidewell's burrs.
  - `--mask [FEATHER]` also writes `OUT-mask.png`, a soft oval that thins a cloud or a
    reef out at its edge, like Tidewell's lampfry.

  `bromigos art make video.loop --alpha luma|stacked|mask` runs it for you. The package
  installs it as `/usr/share/bromigos/tools/glow-loop.py`.
- **`plate-patch.py THEME FLAT EDITED MASK LAYER…`** writes an edit of the flattened
  layers back into the layers, inside the mask only. Each pixel goes to the front-most
  layer that covers it, so a swaying layer never uncovers a copy of itself. That's how
  the painted fish came out of Tidewell's water.

## `art.toml`

```toml
format = 1

[defaults]                 # request options every asset gets, unless it sets its own
aura = false
render_quality = "high"

[[assets]]
id = "comp-v3"             # unique: lowercase letters, digits, - _ .
version = 1                # bump it to make the asset again on purpose (default 1)
kind = "image"
model = "gpt-image-2.5-flare"
prompt = '''A night bayou…'''          # or prompt_file = "art/prompts/comp.txt"
inputs = ["art/refs/den-empty.jpg"]   # reference images
aspect = "16:9"
quality = "2k"             # the model's upscale tier; leave it out for the model's default
out = "art/comps/mire-comp-v3.png"
note = "free text, not part of the recipe"

[[assets]]
id = "comp-v4"
kind = "edit"
model = "gpt-image-2.5-flare"
input = "@comp-v3"         # another asset's output
mask = "art/masks/mire-edit-mask.png"   # a PNG: transparent means "may change"
prompt = '''Edit this painting…'''
out = "art/comps/mire-comp-v4.png"

[[assets]]
id = "water-loop"
kind = "video"
model = "seedance-2.5"
start = "@comp-v4"         # the first frame
loop = true                # end on the start frame (or end = "@other", or a file)
duration = 5               # seconds
resolution = "720p"        # the model's tier
audio = false
aspect = "16:9"
prompt = '''Locked-off camera; the water ripples…'''
out = "art/loops/water.mp4"

[[assets]]
id = "hollis-cut"
kind = "cutout"            # background removal
model = "remove-background"
input = "@hollis"
out = "art/actors/hollis-cut.png"

[[assets]]
id = "jelly-2x"
kind = "upscale"           # larger and sharper, on a ComfyUI (SeedVR2)
input = "live/loops/jelly-blue.mp4"
extra = { scale = 2 }
out = "art/loops/jelly-blue-2x.mp4"

[[assets]]
id = "layers"
kind = "command"           # a local step: no credits
run = ["layer-split", "{in}", "{outs}"]   # any program, on PATH or by path
inputs = ["@comp-v4"]
outs = ["backgrounds/layers/00-sky.webp", "backgrounds/layers/10-far.webp"]
```

The kinds are `image`, `edit`, `video`, `cutout`, `model3d` (a 3D model from a concept
image), `upscale` (a larger, sharper image or clip) and `command`.

Paths are relative to the theme folder and must stay inside it. An input is a file there,
or `@id` for another asset's first output. Assets run in input order, and a cycle is an
error. Unknown keys are errors too, so a typo never passes silently.

| Key | Kinds | What it sets |
|---|---|---|
| `model` | all but `command` | The model or workflow. Required: there's no default model. |
| `provider` | all but `command` | Who makes it: `comfyui:<name>` or `nolgia` |
| `prompt`, `prompt_file` | `image`, `edit`, `video` | The prompt, trimmed. Required for these kinds. |
| `inputs` | `image`, `command` | Reference images, or what `{in}` and `{ins}` read |
| `input` | `edit`, `cutout`, `model3d`, `upscale` | The one image or clip to work on. Required. |
| `mask` | `edit` | The edit's mask |
| `aspect` | `image`, `edit`, `video` | The aspect ratio |
| `quality` | `image`, `edit` | The upscale tier: `native`, `2k`, `4k`… per model |
| `render_quality` | `image`, `edit` | `auto` to `max`, for GPT Image models |
| `images` | `image` | How many. Outputs are lettered `-a`, `-b`… |
| `aura` | `image`, `edit` | nolgia's `aura` option |
| `start`, `end`, `loop` | `video` | The first frame (required), the last frame, or end on the first |
| `duration` | `video` | Seconds. Required. |
| `resolution` | `video` | The resolution tier: `720p`, `1080p`… |
| `audio` | `video` | Whether to generate sound |
| `extra` | all but `command` | A table merged into the request as it is |
| `run`, `outs` | `command` | The command and its outputs |
| `out` | all but `command` | Where the file goes |

In a `command`'s `run`, `{dir}` is the theme folder, `{in}` and `{out}` are the first
input and output, and `{ins}` and `{outs}` are all of them, as whole arguments. The
command runs in the theme folder.

The house rule is the best-quality models, never a cheap tier by default. The format has
no default model and no default spending cap. A world names its models, and `plan` always
shows what they cost.

## Creation providers

`create.toml` says who makes each kind of art. Anyone can create with local tools, with
nolgia, or with both. There are seven *capabilities*, each with a list of *providers* in
order.

| Capability | Makes | ComfyUI workflow | nolgia model |
|---|---|---|---|
| `image.generate` | A still from a prompt and optional references | `qwen-image-2.1` | `gpt-image-2.5-flare` |
| `image.edit` | An edit of an image, masked or whole | `qwen-image-2.1` | `gpt-image-2.5-flare` |
| `image.cutout` | A transparent PNG of the subject alone | `lucida`, then `birefnet` | `remove-background` |
| `image.upscale` | A larger, sharper PNG of an image, alpha kept | `seedvr2-7b` | none |
| `video.loop` | A seamless loop from a still | `wan2.2-i2v-a14b`, `wan2.2-ti2v-5b` | `seedance-2.5` |
| `video.upscale` | A larger, sharper MP4 of a clip, frame rate and sound kept | `seedvr2-7b-video` | none |
| `model3d.generate` | A 3D model (GLB) from a concept image | `pixal3d`, then `hunyuan3d-2.1` | `trellis` |

These are the shipped defaults. The files merge key by key, and yours wins:

| File | What it is |
|---|---|
| `/usr/share/bromigos/default/create.toml` | Shipped: the workflow and model per capability, no provider lists |
| `~/.config/bromigos/create.toml` | Yours. `bromigos setup create` writes it. |
| `$BROMIGOS_CREATE_CONFIG` | Replaces yours, for tests and CI |

**Without a `providers` list, a capability follows `targets.toml`** ([targets.md](targets.md)).
Its targets come in your order: `homelab` is `comfyui:homelab`, `local` is
`comfyui:local`, and `cloud` is `nolgia`. Their ComfyUI addresses come from targets.toml,
unless a `[comfyui.<name>]` table here gives one. The shipped default lists no providers,
so `bromigos target local` moves every capability at once. A list here pins that
capability.

`bromigos art make` reports which target it ran on, with the provider and credits. When it
routes a world's asset, it skips a ComfyUI that doesn't answer.

```toml
format = 1

# ComfyUI instances. Each [comfyui.<name>] is the provider "comfyui:<name>".
[comfyui.local]
endpoint = "http://127.0.0.1:8188"
[comfyui.homelab]
endpoint = "@homelab:comfyui"          # the homelab.toml [[source]] named "comfyui"
# timeout_s = 900                      # optional, per job

# nolgia. Credentials never go in this file (see "Credentials").
[nolgia]
enabled = true
# max_credits_per_job = 80             # optional: skip nolgia for a pricier job

# Each capability: its providers in order, and what to run on each kind of provider.
[image.generate]
providers = ["comfyui:homelab", "nolgia"]
comfyui = "qwen-image-2.1"             # a workflow, on any comfyui:* provider
nolgia = "gpt-image-2.5-flare"         # a nolgia model id

[video.loop]
providers = ["comfyui:homelab", "nolgia"]
comfyui = ["wan2.2-i2v-a14b", "wan2.2-ti2v-5b"]   # a list: tried in order on each ComfyUI
nolgia = "seedance-2.5"
```

**Providers.** A provider is `"comfyui:<name>"`, `"nolgia"` or `"none"`. The first
provider that is configured, reachable, and has the workflow or model makes the job. An
unreachable or unconfigured one is skipped. `"none"` stops the list, which turns the
capability off. Nothing falls through to a paid provider unless the list names it.

**Endpoints** are a URL or a reference, the same references `homelab.toml` uses. So the
file can live in a public dotfiles repository.

| Endpoint | Where the address comes from |
|---|---|
| `"http://127.0.0.1:8188"` | Written as it is |
| `"@env:BROMIGOS_COMFYUI_URL"` | An environment variable |
| `"@private:env.BROMIGOS_COMFYUI_URL"` | The private overlay (`~/.config/bromigos/private/config.json`), by dotted key |
| `"@file:~/path"` | A file's content |
| `"@vault:kv/path#field"` | Vault, through the `vault` command |
| `"@homelab:<source>"` | The endpoint of the `homelab.toml` `[[source]]` with that name |

**A ComfyUI in `homelab.toml`** is a source like any other. It needs `bromigos-homelab`.
Its `comfyui` adapter shows the queue and VRAM on the LAB panel, and provides the `media`
capability.

```toml
[[source]]
name = "comfyui"
type = "comfyui"
endpoint = "@private:env.BROMIGOS_COMFYUI_URL"
```

**Workflows** are ComfyUI graphs in API format. The shipped ones are in
`core/crates/bromigos-art/workflows/<name>.json`, installed in
`/usr/share/bromigos/art/workflows/`. Yours go in
`~/.config/bromigos/create/workflows/<name>.json`, and yours win over a shipped one with
the same name. Each declares the capabilities it serves and the model files it needs, so
`bromigos art status` can tell whether a ComfyUI has them.

**`art.toml` still wins for one asset.** You can pin it three ways:

- `model = "gpt-image-2.5-flare"`: a nolgia model.
- `model = "homelab:qwen-image-2.1"`: that workflow on `comfyui:homelab`.
- `provider = "comfyui:local"` with `model = "<workflow>"`: any ComfyUI.

Without a pin, the asset's kind picks the capability, and `create.toml` picks the
provider.

### Make one thing, outside a world

`bromigos art make` runs a single job through the same providers. VECTOR's hologram
builder uses it.

```bash
bromigos art make image.generate --prompt "a brass telescope" --out telescope.png
bromigos art make image.cutout --input telescope.png --out telescope-cut.png
bromigos art make model3d.generate --input telescope-cut.png --out telescope.glb
```

Its options include `--input` (repeat for more), `--mask`, `--provider`, `--model` (needs
`--provider`), `--aspect`, `--duration`, `--resolution`, `--alpha`, `--max-credits` and
`--extra KEY=VALUE`. With `--json`, it prints the capability, the target, the provider,
the model, the output, the credits, the weights' licence, the job and the seconds it
took. Every job, whichever way it ran, is logged with its provider, credits and licence.

## Art made on a ComfyUI

An asset made by a ComfyUI costs no credits. `plan` prices it at 0 and checks it locally.
A run with only ComfyUI assets needs no nolgia login or catalog. `run` uploads the inputs,
queues the workflow, waits, and downloads the PNG, GLB or MP4. It logs the job with
`"credits": 0`, the backend (`comfyui:<name>`) and the weights' licence.

| Workflow | Capabilities | Weights | Licence |
|---|---|---|---|
| `qwen-image-2.1` | `image.generate`, `image.edit` | Qwen-Image 2.1, with a Qwen3-VL-8B encoder | Qwen Research License: **non-commercial** |
| `lucida` | `image.cutout` | Lucida v7, a BiRefNet_HR fine-tune, on ComfyUI's own nodes | MIT |
| `birefnet` | `image.cutout` | BiRefNet-general, through the ComfyUI-RMBG node. The fallback without Lucida | MIT |
| `pixal3d` | `model3d.generate` | Pixal3D int8 on TRELLIS.2, with DINOv3, MoGe-2 and Lucida. Shape only | DINOv3 License (Meta); MoGe-2 and Lucida MIT |
| `hunyuan3d-2.1` | `model3d.generate` | Hunyuan3D 2.1, shape only. The fallback without Pixal3D | Tencent Hunyuan Community License: not in the EU, UK or South Korea |
| `seedvr2-7b` | `image.upscale` | SeedVR2 7B int8 and its VAE | Apache-2.0 |
| `seedvr2-7b-video` | `video.upscale` | The same, for clips | Apache-2.0 |
| `wan2.2-ti2v-5b` | `video.loop` | Wan 2.2 TI2V-5B with its VAE and the UMT5-XXL encoder | Apache-2.0 |
| `wan2.2-i2v-a14b` | `video.loop` | Wan 2.2 I2V-A14B's two fp8 experts, with the Wan 2.1 VAE | Apache-2.0 |

Measured on a 32 GB GPU, with the voice models loaded alongside:

- `qwen-image-2.1`: 6 to 47 seconds an image.
- `lucida`: 2 seconds a cutout, using 1.0 GiB.
- `birefnet`: 4 to 6 seconds a cutout.
- `pixal3d`: 35 to 57 seconds a model, using 10.2 to 12.5 GiB.
- `hunyuan3d-2.1`: 18 to 27 seconds a model, peaking at 28.5 of 32.6 GiB.
- `seedvr2-7b`: 12 seconds to double a 640-pixel image, 16 seconds up to 8.4 megapixels,
  using 8.5 to 8.7 GiB.
- `seedvr2-7b-video`: 39 seconds for a 5-second 200x298 loop at 2x, and 116 seconds
  at 4x.
- `wan2.2-ti2v-5b`: 131 to 135 seconds for a 5-second loop at 720p. ComfyUI peaked at
  16.2 to 18.2 GiB.
- `wan2.2-i2v-a14b`: wired up but not measured yet. Its two experts are 28.6 GB on disk.
  Its graph is Comfy-Org's first-and-last-frame template.

**The 3D workflows make shape only.** VECTOR's hologram bake keeps geometry and edges,
never a texture, so that's enough.

- **Pixal3D** builds the shape lined up with the concept's pixels, so it follows the
  concept closely, down to a crane's lattice and cable. The graph remeshes the shape to a
  clean outer shell of at most 500,000 faces.
- Because Pixal3D follows the concept's *view*, a concept seen from above comes out
  leaning back. Its workflow sets `_meta.level`, and `bromigos art` stands the model
  upright afterwards. It records the angle in the GLB as
  `asset.extras.bromigos_levelled_deg`. A shape with nothing square keeps its pose.
- **Hunyuan3D 2.1** is the fallback for a ComfyUI without Pixal3D. Its outline is
  faithful, but its edges are noisier.

**Upscales** take one `input` and write a `.png` for an image or an `.mp4` for a clip.
`extra.scale` sets the factor: 2 by default, at most 4, and a whole number for a clip.
The factor is lowered, and the job says so, when the result would be bigger than the
workflow makes. That's 8.4 megapixels an image or a frame, and 120 megapixel-frames for a
whole clip. A 5-second loop at 24 fps can reach about 1 megapixel a frame. A longer or
larger clip is refused, with a suggestion to trim or split it. nolgia has no upscale
model, so upscales only run on a ComfyUI.

A clip is restored in short runs of frames, sized to the VRAM that's free when the job
starts. A model still loaded from an earlier job would leave room for one frame at a time,
and the frames would flicker. So the clip workflow sets `_meta.unload_first`: before the
job, `bromigos art make` asks an idle ComfyUI to unload its models (`POST /free`). When
ComfyUI is busy with someone else's work, nothing is unloaded, and the job says so.

**A workflow's `_meta`** declares its capabilities, its output (`png`, `glb` or `mp4`),
its `license`, the model files it `requires`, and where a job's values go. Those are in
`bind`: `image`, `prompt`, `seed`, `width` and `height`, `scale` and `prefix`, each a
`[node, input]` pair or a list of them. So a workflow of your own in
`~/.config/bromigos/create/workflows/` needs no code.

```toml
[[assets]]
id = "veilwing-qwen"
kind = "image"
model = "homelab:qwen-image-2.1"
prompt = '''A single veilwing…'''
inputs = ["art/refs/tidewell-under-crop.png"]   # references, seen by the encoder
aspect = "16:9"
extra = { resolution = 1536 }                  # about 1536² pixels (512 to 2048; default 1536)
out = "art/actors/veilwing-qwen.png"           # always one PNG

[[assets]]
id = "fish-out"
kind = "edit"
model = "homelab:qwen-image-2.1"
input = "@comp-v3"
mask = "art/masks/fish.png"                    # transparent may change; the rest is put back exactly
prompt = '''Remove the fish…'''
out = "art/comps/comp-v4.png"
```

The graph is filled in by node id:

- the prompt;
- the size, from `aspect` and `extra.resolution`, on the model's 32-pixel grid;
- a seed from the asset's recipe, so the same recipe makes the same picture;
- the references.

An edit works on its image's own latent. With a mask, the original is put back
everywhere the mask is opaque. `quality`, `render_quality` and `aura` are nolgia options.
They change nothing here, though they're still part of the recipe.

**The ComfyUI's address** is `BROMIGOS_COMFYUI_URL`, or `comfyui_url = "…"` in
`~/.config/bromigos/art.toml`. The address is never in a theme or in this repository. A
private overlay can set the variable.

**Check the licence first.** Art made with a model is bound by its weights' licence, and
the log records it for each job. Qwen-Image 2.1's licence is non-commercial. That's fine
for trying looks and for a personal desktop. It isn't fine for anything sold, or shipped
in a commercial product, without Qwen's commercial licence. Check
[ASSETS.md](ASSETS.md) before a file made this way ships in a package.

## Video loops on a ComfyUI

`video.loop` runs on a ComfyUI like the other capabilities. The default lists both Wan 2.2
workflows, so a loop goes to the first ComfyUI in your targets that has one of them. It
goes to nolgia only when the cloud is in your order, or when you ask with
`--provider nolgia`.

```bash
bromigos target probe video.loop     # each ComfyUI: whether it has Wan's files, and its VRAM
bromigos art make video.loop --input jelly.png --prompt "…how it moves…" \
    --duration 5 --alpha luma --out jelly.mp4
```

The second command also keeps the clip as made, as `jelly-raw.mp4`.

**A loop ends on its start frame,** so its last frame sits next to its first, and
`glow-loop.py` cuts at the wrap. How that works depends on the model:

- **Wan 2.2 I2V-A14B** takes an end frame natively.
- **Wan 2.2 TI2V-5B** has no end-frame input, so bromigOS gives it one through its latent.
  The end image is held for 5 frames and encoded. Its second latent frame, a whole
  4-frame chunk, replaces the clip's last latent frame. A noise mask keeps it and the first
  frame clean. The motion comes back to the start. The frames that chunk decodes to are
  dropped, because they come out washed grey. In testing, a jellyfish's last kept frame
  differed from its first by less than one frame's motion.
- **`extra.loop_mode = "crossfade"`** is the default for a model that can't end on a
  frame. It makes `seam` extra frames (half a second by default) and crossfades the
  clip's tail into its head. It suits a clip that drifts little. A free-swimming
  jellyfish over 5 seconds wanders too far for a crossfade to hide.

**Describe the motion in the prompt.** Wan 2.2's 5B model moves less than seedance, and
needs the motion spelled out. Prompts that make good seedance loops, such as "it stays
centred in the same position and size", make it nearly freeze once the end frame is
pinned. A jellyfish moved 0.31 between frames with such a prompt. With a prompt
describing the stroke, it moved 4.9: "its bell contracts strongly, squeezing inward, then
relaxes and opens wide again, about one pulse a second; its ribbon arms ripple and
trail". It also follows a light cue, such as "its glow brightens with each pulse", less
than seedance does.

**In a world's `art.toml`**, a ComfyUI loop is a `video` asset with a `homelab:` model,
followed by the same `command` step as a nolgia clip:

```toml
[[assets]]
id = "jellyfish-raw-wan"
kind = "video"
model = "homelab:wan2.2-ti2v-5b"
start = "@jellyfish"
loop = true
duration = 5
resolution = "720p"              # 5B's tiers: 720p (its default) and 480p
extra = { fps = 24 }             # optional: fps, seed, steps, cfg, negative, loop_mode, seam
prompt = '''A deep-sea jellyfish swimming in place against a pure black background. Its bell
contracts strongly, then relaxes and opens wide again…'''
out = "art/clips/jellyfish-raw-wan.mp4"

[[assets]]
id = "jellyfish-loop-wan"
kind = "command"
run = ["python3", "../../theme/tools/glow-loop.py", "{in}", "{out}", "--width", "540"]
inputs = ["@jellyfish-raw-wan"]
outs = ["live/loops/jellyfish.mp4"]
```

Without an `aspect`, the clip keeps the still's shape, at the tier's pixel count on the
model's grid. For TI2V-5B, that's 768×1152 for a 2:3 still and 1280×704 for 16:9.

The 5B model makes 24 frames a second, and the A14B makes 16. The A14B's default tier is
480p.
The frames a clip needs must stay under the workflow's `max_frames`, 193 and 121. So a
loop can be up to about 7 seconds on either.

**A video workflow is data,** so the lab's model catalog ([lab-models.md](lab-models.md))
can add or rank models without code. Its `_meta` has:

| Key | What it is |
|---|---|
| `fill` | `"video"` |
| `catalog` | The catalog's id, such as `wan2.2-ti2v-5b/fp16` |
| `vram_gib`, `seconds` | Its measured peak, and a typical job's time |
| `features` | `i2v`, `t2v` or `flf2v` |
| `requires`, `nodes` | The model files and node classes it needs |
| `video` | `fps`, `frame_step`, `max_frames`, `grid`, `sizes`, `resolution` and `end_frame` |
| `bind` | Where each value goes, as `[node, input]` |

`bromigos target probe` and `bromigos art make` skip a ComfyUI that lacks a required file
or node. In `video`, a clip has `1 + frame_step × k` frames, `sizes` gives each tier's
pixel count, and `end_frame` is `native`, `latent` or `none`. `bind` covers `image`,
`prompt`, `negative`, `seed`, `steps`, `cfg`, `width`, `height`, `length`, `fps`,
`prefix` and `end_input`. For a latent end frame it also names `vae`, `latent` with
`latent_input`, and `frames` with `frames_input`.

## Up to date, stale or missing

Each asset has a *spec*: the SHA-256 of its recipe, written as canonical JSON. The recipe
is its kind, version, model, prompt text, inputs, mask, end frame, every request option
and `extra`. An input asset counts by its own spec, and a file by its path. The `id`, the
`note` and the output paths aren't part of it, so renaming an output doesn't make it
stale. `status` compares each spec with the log:

| State | Meaning | What `run` does |
|---|---|---|
| `done` | Made with this spec, the outputs are here, and the file inputs haven't changed | Skips it |
| `missing` | Made with this spec, but an output isn't on this machine | Makes it only if something it feeds is made |
| `stale` | The spec changed, a file input changed, or an input asset was made again | Makes it |
| `pending` | Sent with this spec and not finished, for example after a timeout | Waits for that job, with no new charge |
| `new` | Never made | Makes it |

If you name assets, `run` makes them unless they're `done`, and `--force` makes them
anyway. It also makes any input asset that isn't `done`. A change to an asset makes
everything that reads it stale too, because their specs include its spec.

## Credits

`plan` prices each asset from the model's entry in nolgia's live catalog. That's what
`nolgia models get` shows.

- **Per image:** the `quality` tier's credits, or the model's, plus the
  `render_quality`'s `credits_added`, times `images`.
- **Per clip:** `ceil(rate × duration / baseline_seconds)`, where the rate is the
  `resolution` tier's, less its `audio_surcharge` when `audio = false`.
- **Per generation:** a flat price.
- **Input images:** where the model charges for them, add
  `max(0, input images − free_input_images) × input_image_credits` once per request.

`plan` also refuses what the catalog says the model can't do. That includes an aspect it
doesn't offer, a mask on a model without inpainting, a loop on a model without end
frames, a duration out of range, and too many references. So a run never pays for a
request the server would refuse.

Before each job, `run` asks nolgia for a quote of the exact request. Quotes are free. It
sends the quote's confirmation token with the job, so the charge is the quote. If the
quote differs from the plan, it says so.

`--max-credits N` refuses to start when the plan costs more than N, with exit status 3.
It also stops before any job that would take the run over N. There's no cap otherwise.

## The log

`themes/<world>/art.log.jsonl` gets one JSON object per line, appended:

```json
{"schema":1,"t":"2026-10-08T02:49:49-07:00","world":"mire","asset":"boot","version":1,"kind":"image","spec":"sha256:b61a…","status":"succeeded","model":"gpt-image-2.5-flare","prompt_sha256":"5c17…","credits":8,"planned":8,"job":"c58b87c1-…","outputs":["art/actors/boot.png"],"inputs":{"art/refs/mire-left-crop.png":"da16…"},"seconds":33,"error":null,"by":"bromigos art run"}
```

- **`status`** is `submitted` first. It's written before the wait, so an interrupted run
  leaves a record, and the next run waits for the job. Then it's `succeeded`, `failed` or
  `timeout`. An asset recorded by hand with `bromigos art mark` is `marked`.
- **`credits`** is what the job was charged: the quote it was sent with. It's 0 for a
  failed job that nolgia refunded, and `null` when unknown. Spending counts each `job`
  once, at its latest record.
- **`inputs`** holds the SHA-256 of each file input when the job ran.
- ComfyUI jobs also record `backend` and `license`.

The log never holds a URL, because signed URLs carry credentials. Errors are scrubbed of
them too. It never holds a token or the prompt. It holds only the prompt's hash, since the
prompt is in `art.toml`.

Each finished job is also appended to `~/.local/state/bromigos/nolgia-spend.jsonl`, the
desktop's record of nolgia spending.

## Credentials

Each user makes art with their own nolgia account. `bromigos art` looks for credentials in
this order:

1. **`NOLGIA_API_KEY`**, else **`NOLGIA_TOKEN`**: a personal access token (`nol_…`), from
   nolgia's API tokens page.
2. **The token file `bromigos setup` writes** for an unattended setup:
   `~/.local/share/bromigos/nolgia-token`, readable only by you.
3. **The nolgia CLI's login** (`nolgia auth login`). `nolgia auth status` renews it when
   it has expired, and `nolgia auth token` hands it over on a pipe. The CLI is
   `$NOLGIA_BIN`, else `nolgia` on `PATH`, else `~/.cargo/bin/nolgia`.

The token goes to the SDK only. It's never printed, logged or put on a command line.
`NOLGIA_BASE_URL`, or the CLI's `NOLGIA_API_URL`, points at another API, such as staging.
`status` and `mark` never need credentials, and nor does a plan with nothing to make.

## Recording art made elsewhere

```bash
bromigos art mark <world> <asset> [--job ID] [--credits N] [--at TIME] [--seconds S] [--by TEXT]
```

This records an asset whose outputs exist as made with its current recipe. Use it for art
made by hand or by an older script. `--at` takes an RFC 3339 time and defaults to now.
Mire and Tidewell were seeded this way from the first art pass's script log, with
`--by "gen.sh (bromigos-worlds)"`. The credits there are what that script recorded.
