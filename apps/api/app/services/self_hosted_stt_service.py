# apps/api/app/services/self_hosted_stt_service.py

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional

from faster_whisper import WhisperModel


@dataclass
class SelfHostedSTTConfig:
    model_size: str = "small"          # tiny/base/small/medium/large-v3
    device: str = "cpu"                # "cpu" or "cuda"
    compute_type: str = "int8"         # cpu: int8/int16/float32 | cuda: float16/int8_float16
    language: Optional[str] = "en"     # None to auto-detect
    vad_filter: bool = True
    beam_size: int = 5


class SelfHostedWhisper:
    """
    Self-hosted Whisper transcription.
    - Accepts raw audio bytes (webm/ogg/wav/mp3/etc)
    - Does NOT write to disk
    - Returns text + optional confidence-ish score
    """

    def __init__(self, cfg: Optional[SelfHostedSTTConfig] = None):
        self.cfg = cfg or SelfHostedSTTConfig()
        self.model = WhisperModel(
            self.cfg.model_size,
            device=self.cfg.device,
            compute_type=self.cfg.compute_type,
        )

    def transcribe(self, audio_bytes: bytes, *, content_type: str = "audio/webm") -> Dict[str, Any]:
        if not audio_bytes or len(audio_bytes) < 4000:
            return {"text": "", "confidence": None}

        segments, info = self.model.transcribe(
            audio=audio_bytes,
            language=self.cfg.language,
            vad_filter=self.cfg.vad_filter,
            beam_size=self.cfg.beam_size,
        )

        parts: list[str] = []
        for seg in segments:
            t = (seg.text or "").strip()
            if t:
                parts.append(t)

        text = " ".join(parts).strip()

        # Rough signal only (NOT a true confidence)
        conf = None
        try:
            avg_lp = getattr(info, "avg_logprob", None)
            if isinstance(avg_lp, (int, float)):
                # Map [-2..0] -> [0..1] clamped
                conf = max(0.0, min(1.0, (avg_lp + 2.0) / 2.0))
        except Exception:
            conf = None

        return {"text": text, "confidence": conf}
