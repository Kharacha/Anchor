# apps/api/app/schemas/turns.py

from __future__ import annotations

from pydantic import BaseModel
from typing import Any, Dict, Literal


class CreateTurnRequest(BaseModel):
    text: str


class SafetyResult(BaseModel):
    label: Literal["allow", "block", "review"]
    reasons: list[str] = []
    meta: Dict[str, Any] = {}


class CreateTurnResponse(BaseModel):
    turn_id: str
    user_text: str
    assistant_text: str
    input_safety: SafetyResult
    fallback_used: bool = False
