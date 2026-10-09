"""A lab voice service: the `voice` capability (speech-to-text and text-to-speech over HTTP).

bromigOS's voice service (the homelab chart `voice`: Qwen3-TTS streamed voice cloning and
Whisper) answers GET /health with its models; VECTOR speaks through POST /v1/tts/stream and
listens through POST /v1/stt (docs/homelab.md, "Capabilities"). A source's endpoint may still carry
Breeze TTS's old path (/v1/audio/speech): only the base URL is kept.
"""
from ..registry import Adapter, register


@register
class BromigosVoice(Adapter):
    type = "bromigos-voice"
    provides = ("voice",)
    default_ports = (7860,)

    def __init__(self, source):
        super().__init__(source)
        for tail in ("/v1/audio/speech", "/v1/tts/stream", "/health"):
            if self.endpoint.endswith(tail):
                self.endpoint = self.endpoint[: -len(tail)]

    def probe(self):
        h = self.get_json("/health", timeout=3)
        return isinstance(h, dict) and "tts_model" in h

    def voice(self):
        h = self.get_json("/health", timeout=4)
        return [{"name": self.name, "endpoint": self.endpoint, "up": bool(h.get("ok")),
                 "tts": bool(h.get("tts")), "stt": bool(h.get("stt")), "sample_rate": h.get("sample_rate"),
                 "tts_model": h.get("tts_model"), "stt_model": h.get("stt_model")}]
