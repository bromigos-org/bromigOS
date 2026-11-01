# STATIC's art (`bromigos-mascot-art`)

This folder holds the painted art of STATIC, the Bromigos mascot, that bromigOS ships:
short loops (`static/`) that host Den TV's channel guide.

It's art only. The code that shows it is in `lib/bromigos_static_art.py`. Without this
package, the guide draws STATIC's code-drawn placeholder.

STATIC is signal first and a body second. He rides many machines, called **shells**, and
each shell has its own job. The art casts them by what's happening. NOIR, a host in a hover
pod, hosts. RIG's LINEMAN fixes things. RECON's OWL keeps watch. (In the Bromigos stories,
they crew a small ship between the relay posts.)

## The guide's host

`static/manifest.json` names one loop per state of the guide's Tonight card, at two
heights (168 and 336 pixels). Each loop is about four seconds of animated WebP: a
two-second stretch of a clip, played forward then back so it loops without a jump.

| Name | When the guide shows it | The shell |
|---|---|---|
| `host` | What's coming up next | NOIR hosting the late-night broadcast |
| `snow` | The channels are being read | STATIC's signal racing into NOIR's console |
| `antenna` | There are no channels yet | OWL searching the dark for a signal |
| `asleep` | The live layer isn't running | NOIR powered down for the night |
| `whack` | Something can't be read | LINEMAN fixing a junction box |

Each name has `"min": 96`. Below 96 pixels, such as a terminal's half-blocks, the
placeholder draws instead. Each name's `about` is its hover hint.

## How it was made

Everything here was made on the lab's own GPU, with no cloud service and no credits. Every
model is under Apache-2.0 or MIT.

1. **Panels.** The scene boards were painted with Qwen-Image-Edit-2511, with STATIC's
   approved concepts as identity references. BLACKFLAME locked them on 2026-10-31. For
   `asleep`, the same editor made a second frame from a panel: NOIR powered down.
2. **Clips.** Wan 2.2 I2V-A14B animated each panel at 832x480 and 16 frames a second.
   `asleep` uses its first-and-last-frame mode, between the panel and its edit.
3. **Upscale.** SeedVR2 7B upscaled each clip to 1248x720, and RIFE 4.9 doubled its frames
   to 32 a second.
4. **Cut.** `tools/cut.py` (ffmpeg) fades each clip in and out, and `tools/host_art.py`
   cuts the guide's loops from them.

`provenance.jsonl` has one line for each panel edit, clip and upscale behind these loops: the model, its
licence, the seed, the prompt and the time it took.
