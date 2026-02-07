# apps/api/app/schemas/turns_ingest.py

from __future__ import annotations

from pydantic import BaseModel, Field
from typing import Any, Dict, Optional, Literal


class SpeechFeatures(BaseModel):
    duration_ms: Optional[int] = Field(default=None, ge=0)
    speech_rate: Optional[float] = Field(default=None, ge=0)
    pause_ratio: Optional[float] = Field(default=None, ge=0, le=1)


class ClientLatencyMs(BaseModel):
    record_ms: Optional[int] = Field(default=None, ge=0)
    stt_ms: Optional[int] = Field(default=None, ge=0)


class TurnIngestRequest(BaseModel):
    input_mode: Literal["voice", "text"] = "voice"

    transcript_text: str = Field(..., min_length=1)
    transcript_confidence: Optional[float] = Field(default=None, ge=0, le=1)

    speech_features: Optional[SpeechFeatures] = None

    stt_provider_used: Literal["on_device", "self_hosted"] = "on_device"
    fallback_used: bool = False

    client_latency_ms: Optional[ClientLatencyMs] = None


class TurnIngestResponse(BaseModel):
    turn_id: str
    transcript: str
    assistant_text: str
    input_safety: Dict[str, Any]
    fallback_used: bool
    analysis: Optional[Dict[str, Any]] = None
