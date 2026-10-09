"""Media generation servers: the `media` capability.

ComfyUI (type "comfyui"): its queue (running and pending prompts), the GPU's free and total
VRAM, its version, and how many models it has per folder (checkpoints, diffusion_models,
text_encoders, ...), from GET /system_stats, /queue and /models (/models/<folder> per folder;
older ComfyUIs without /models report no counts). bromigos art's providers (create.toml) point
at the same server; this is what the desktop shows of it.
"""
from ..registry import Adapter, register

FOLDERS = ("checkpoints", "diffusion_models", "unet", "text_encoders", "clip", "vae", "loras",
           "controlnet", "upscale_models", "clip_vision")


@register
class ComfyUI(Adapter):
    type = "comfyui"
    provides = ("media",)
    default_ports = (8188,)

    def probe(self):
        s = self.get_json("/system_stats", timeout=3)
        return isinstance(s, dict) and "comfyui_version" in (s.get("system") or {})

    def media(self):
        s = self.get_json("/system_stats", timeout=4)
        q = self.get_json("/queue", timeout=4)
        dev = (s.get("devices") or [{}])[0]
        models = {}
        try:
            have = set(self.get_json("/models", timeout=4) or [])
            for f in FOLDERS:
                if f in have:
                    models[f] = len(self.get_json(f"/models/{f}", timeout=4) or [])
        except Exception:
            models = {}
        return [{"name": self.name, "endpoint": self.endpoint, "up": True,
                 "running": len(q.get("queue_running") or []), "pending": len(q.get("queue_pending") or []),
                 "vram_free": dev.get("vram_free"), "vram_total": dev.get("vram_total"), "gpu": dev.get("name"),
                 "version": (s.get("system") or {}).get("comfyui_version"),
                 "models": {k: v for k, v in models.items() if v}}]
