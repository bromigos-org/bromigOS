# Lowtown's hologram models

This folder holds Lowtown's hologram models. They're 3D models from Lowtown's part of the
Bromigos universe, shown in VECTOR's hologram gallery. Press Super+O to open the gallery.
Lowtown's shelf is drawn in Lowtown's colours, and comes first while Lowtown is the theme
in force. bromigos.org shows the same models as interactive holograms.

## The models

| Model | What it is | Parts |
|---|---|---|
| `low-note` | Della Ash's post, the Low Note | neon sign (live), street lamp, stairwell, overpass, pavement, facade |

**The Low Note.** A basement jazz bar under Lowtown's overpass, with the relay hidden in
its neon sign.

Every part has hover text, its `hint` in `manifest.json`. A part marked *live* shows a
reading through VECTOR's `holo/bind.py`. Each live part here reads `wick.beam`, so it's
lit while every homelab service is up and every node is Ready. The other parts only shape
the model. A viewer without live readings, such as the website, lights every part the
same.

> **Planned.** This folder is also reserved for the theme's deck style: line weights,
> glow and label type. Nothing reads that yet. The decks' colours already come from
> `[holo]` in `colors.toml`.

## What's in this folder

| File | What it is | Ships? |
|---|---|---|
| `manifest.json` | Each model's title, parts, part boxes and readings | Yes |
| `NAME.holo.npz` | The baked model the renderers read | Yes |
| `README.md` | This file | Yes |
| `src/NAME.glb` | The master mesh, about 1.8 MB | No |
| `concepts/NAME.jpg` | The concept image the model was made from | No |
| `previews/` | Offscreen renders of each model, whole, exploded and turning, and its parts | No |
| `generations.jsonl` | Every generation step, with its prompt, seed, model and licence | No |

`bromigos-core` installs the shipped files in `/usr/share/bromigos/themes/lowtown/holo/`.
The sources stay in the repository. The format is VECTOR's: the vector repository
documents it in `assets/holo/README.md` and `tools/holo/`.

The previews come from VECTOR's own hologram renderer (`holo/gallery.py`, `stage.py`,
`render.py`). They're drawn in this collection's palette, on a plain void instead of a
wallpaper. Parts with no live reading are drawn lit.

## How they were made

The models were made on a homelab on 2026-10-08, with no paid credits. Each step ran
through `bromigos art make --provider comfyui:homelab --json`:

1. **Concept.** Qwen-Image 2.1 drew a concept about 1536 pixels square (`image.generate`,
   workflow `qwen-image-2.1`). The prompt and seed are in `generations.jsonl`. Every
   prompt ends with the same isolation block: a plain medium-grey studio background, the
   whole object in frame, a three-quarter view from slightly above, and crisp hard-surface
   parts with a strong silhouette. Creatures and craft were given the worlds' own art as a
   reference image, so the designs match it.
2. **Cutout.** BiRefNet cut the object out of the concept (`image.cutout`).
3. **Image to 3D.** Hunyuan3D 2.1 made the shape, without texture (`model3d.generate`,
   workflow `hunyuan3d-2.1`).
4. **Master.** Floating specks were dropped, meaning any piece under 0.2% of the largest.
   Then fast-simplification decimated the mesh to 100,000 faces. The result is
   `src/NAME.glb`, about 1.8 MB. The raw outputs, 12 MB and up, stay out of the
   repository, in `~/.local/share/bromigos/3d-raw/`.
5. **Parts and bake.** VECTOR's `tools/holo/make-holo.py glb` split the model into parts,
   found its feature edges and baked it at 40,000 triangles. The result is
   `NAME.holo.npz`, 560 to 650 KB, and `previews/NAME-parts.png`.

## Rebake

From a bromigOS checkout, with the vector repository checked out at `<vector>`:

```bash
~/.local/share/bromigos/venv/bin/python <vector>/tools/holo/bake.py --root themes/lowtown/holo --preview
```

Always pass `--root`. Without it, the tools work on your own collection in
`~/.config/bromigos/vector/holo` instead.

## Licences

These models were made on a homelab, and are published under bromigos.org's terms by the
operator's decision of 2026-10-08. The models used to make them have their own licences:

- Qwen-Image 2.1 is under the Qwen Research License, for research or evaluation only.
- Hunyuan3D 2.1 is under the Tencent Hunyuan 3D 2.1 Community License. Its territory
  excludes the EU, the UK and South Korea.
- BiRefNet is under the MIT licence.

[docs/ASSETS.md](../../../docs/ASSETS.md) has the asset's row, and its Provenance section
links each licence.
