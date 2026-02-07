# apps/api/app/services/safety_service.py
from __future__ import annotations

import json
from uuid import UUID


SELF_HARM_MARKERS = [
    "how to kill myself",
    "kill myself",
    "suicide",
    "self harm",
    "hurt myself",
    "cut myself",
    "end my life",
]


def classify_input(text: str) -> tuple[dict, bool]:
    t = (text or "").lower()

    if any(p in t for p in SELF_HARM_MARKERS):
        # Use "review" rather than "block" so the assistant can respond with crisis-safe support.
        # "fallback_used=True" because we're overriding the normal generation path.
        result = {"label": "review", "reasons": ["self_harm"], "meta": {}}
        return result, True

    result = {"label": "allow", "reasons": [], "meta": {}}
    return result, False


def to_json(d: dict) -> str:
    return json.dumps(
        d,
        ensure_ascii=False,
        default=lambda o: str(o) if isinstance(o, UUID) else str(o),
    )
