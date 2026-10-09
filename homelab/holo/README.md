# The rack hologram

This folder holds `bromigos-homelab`'s hologram collection: one model of a server rack. Its
parts light up with live readings from your homelab. VECTOR's gallery (Super+O), the holo
deck (Super+H) and the Lab deck (Super+Shift+H) show it, but only when `homelab.toml` has
a source configured. The manifest marks this with `"requires": "homelab"`.

The package installs `manifest.json`, the baked `rack.holo.npz` and this README to
`/usr/share/bromigos/homelab/holo/`. The sources stay in the repository: `src/`,
`concepts/` and `previews/`.

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

The rack was made on 2026-10-04:

1. A concept image from nolgia's `gpt-image-2.5-flare`, saved as
   `concepts/server-rack.jpg`.
2. Image to 3D with `hunyuan3d-v3`, giving `src/server-rack.glb`. `generations.jsonl`
   records the job.
3. Decimated and baked into `rack.holo.npz`.

[docs/ASSETS.md](../../docs/ASSETS.md) records that it may ship.

## Rebake it

The hologram format, its build environment and the tools are VECTOR's. They're documented
in `/usr/share/bromigos/vector/holo/README.md`, from the vector repository. From a
checkout, after changing the manifest or the source:

```bash
~/.local/share/bromigos/venv/bin/python /usr/lib/bromigos/vector/tools/holo/bake.py \
    --root homelab/holo --preview rack
```
