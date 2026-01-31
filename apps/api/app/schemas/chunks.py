from pydantic import BaseModel, Field
from typing import Any, Dict, Literal, Optional


class StartTurnResponse(BaseModel):
    turn_id: str
    turn_index: int


class AppendChunkRequest(BaseModel):
    chunk_index: int = Field(ge=0)
    text: str
    confidence: Optional[float] = Field(default=None, ge=0, le=1)


class AppendChunkResponse(BaseModel):
    ok: bool = True
    seq: int


class SafetyResult(BaseModel):
    label: Literal["allow", "block", "review"]
    reasons: list[str] = []
    meta: Dict[str, Any] = {}


class FinalizeTurnRequest(BaseModel):
    client_turn_done: bool = True


class FinalizeTurnResponse(BaseModel):
    turn_id: str
    transcript: str
    assistant_text: str
    input_safety: SafetyResult
    fallback_used: bool = False
    analysis: Optional[Dict[str, Any]] = None


# -------------------------------
# NEW: Audio upload response schema
# -------------------------------
class AudioUploadResponse(BaseModel):
    transcript: str
    confidence: Optional[float] = None
    content_type: Optional[str] = None
    bytes: Optional[int] = None
