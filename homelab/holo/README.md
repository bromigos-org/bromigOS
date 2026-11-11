# The rack hologram

This folder holds `bromigos-homelab`'s hologram collection: one model of a server rack. Its
parts light up with live readings from your homelab. VECTOR's gallery (Super+O), the holo
deck (Super+H) and the Lab deck (Super+Shift+H) show it, but only when `homelab.toml` has
a source configured. The manifest marks this with `"requires": "homelab"`.

The package installs `manifest.json`, the baked `rack.holo.npz` and this README to
`/usr/share/bromigos/homelab/holo/`. The sources stay in the repository: `src/`,
`blender/` and `previews/`.

## The rack's parts

| Part | Shows |
|---|---|
| SWITCH | the gateway, clients and ingress requests |
| NODES | cluster nodes ready of total, and the busiest node |
| GPU SERVER | model serving load, VRAM, temperature and power |
| STORAGE | the NAS pool and the fullest node disk |
| POWER | power over Ethernet and the GPUs' draw |
| FRAME | Argo CD apps healthy, and alerts firing |

`manifest.json` defines each part: the boxes that pick its faces from the mesh, the live
reading it shows (`bind`), its hover hint, and how it moves when the model is exploded.
The comment at the top of the file explains each key.

## How it was made

The rack was remade on 2026-11-11, and BLACKFLAME approved it the same day. No image
and no AI model went into it:

1. `blender/SPEC.md` writes the rack down: a 24U, 600 x 600 mm cabinet on casters with a
   patch panel and switch, three 1U nodes, a 4U GPU server, a 3U storage chassis and a
   2U UPS, in real sizes.
2. `blender/build.py` builds it in Blender (5.2, headless, its Python API), one object per
   feature, and exports `src/rack.glb`. It also measures each part's box from that part's
   own objects; those are the boxes in `manifest.json`. The same script and template
   rebuild the same file, byte for byte:

   ```bash
   python3 -c 'import json; json.dump(json.load(open("homelab/holo/manifest.json"))["models"]["rack"], open("/tmp/rack.json", "w"))'
   blender -b --factory-startup --python homelab/holo/blender/build.py -- \
       rack /tmp/rack.glb /tmp/rack.parts.json /tmp/rack.json
   ```

3. Baked into `rack.holo.npz` with VECTOR's `tools/holo/bake.py` (below).
   `provenance.jsonl` records the build and the bake.

`previews/rack-parts.png` is the bake's own parts preview; `previews/holo-rack-isolated.jpg`
is an offscreen render of VECTOR's gallery with made-up readings, over the empty den.
The installers' turning rack (`desktop/art/server-rack.png`, `lib/bromigos_rack.py`) is
rendered from this model ([tools/installer-art/make.py](../../tools/installer-art/make.py)).

The rack it replaces (2026-10-04) was an image-to-3D mesh made through a hosted service;
[docs/ASSETS.md](../../docs/ASSETS.md) records both.

## Rebake it

The hologram format, its build environment and the tools are VECTOR's. They're documented
in `/usr/share/bromigos/vector/holo/README.md`, from the vector repository. From a
checkout, after changing the manifest or the source:

```bash
~/.local/share/bromigos/venv/bin/python /usr/lib/bromigos/vector/tools/holo/bake.py \
    --root homelab/holo --preview rack
```
