# apps/api/app/schemas/audio.py
from pydantic import BaseModel, Field
from typing import Optional


class UploadAudioResponse(BaseModel):
    ok: bool = True
    transcript: str
    transcript_confidence: Optional[float] = Field(default=None, ge=0, le=1)
