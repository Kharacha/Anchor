# apps/api/app/services/dynamic_scoring_service.py
from __future__ import annotations

import os
import json
import re
from typing import Any, Optional

from openai import OpenAI

_client: Optional[OpenAI] = None


def _get_client() -> OpenAI:
    """
    Lazy client creation so uvicorn reload won't crash on import
    if OPENAI_API_KEY isn't loaded until app startup.
    """
    global _client
    if _client is None:
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            raise RuntimeError("OPENAI_API_KEY is not set in environment")
        _client = OpenAI(api_key=api_key)
    return _client


def _extract_json(text: str) -> dict:
    """
    Handles cases where the model returns extra text around JSON.
    """
    text = (text or "").strip()
    if not text:
        raise ValueError("Empty model response")

    if text.startswith("{") and text.endswith("}"):
        return json.loads(text)

    m = re.search(r"\{.*\}", text, flags=re.DOTALL)
    if not m:
        raise ValueError(f"Could not find JSON object in: {text[:200]}")
    return json.loads(m.group(0))


def score_text_openai(
    text: str,
    *,
    # accepted for compatibility with callers; not used inside this function
    chunk_confidences: list[tuple[str, float | None]] | None = None,
) -> dict[str, Any]:
    """
    Raw OpenAI scoring.
    Returns dict with keys: valence, arousal, confidence
    - valence: [-1, 1]
    - arousal: [0, 1]
    - confidence: [0, 1]
    """
    text = (text or "").strip()
    if not text:
        return {"valence": 0.0, "arousal": 0.0, "confidence": 0.0}

    client = _get_client()
    model = os.getenv("OPENAI_SCORING_MODEL", "gpt-4o-mini")

    prompt = (
        "You are scoring a short user utterance.\n"
        "Return ONLY valid JSON with keys: valence, arousal, confidence.\n"
        "valence in [-1, 1], arousal in [0, 1], confidence in [0, 1].\n"
        "Interpret valence as negative/sad to positive/happy.\n"
        "Interpret arousal as calm/low-energy to stressed/excited/high-energy.\n"
        f"User text: {text}\n"
    )

    resp = client.responses.create(
        model=model,
        input=prompt,
        temperature=0,
    )

    raw = (resp.output_text or "").strip()
    data = _extract_json(raw)

    valence = float(data.get("valence", 0.0))
    arousal = float(data.get("arousal", 0.0))
    conf = float(data.get("confidence", 0.5))

    # clamp
    valence = max(-1.0, min(1.0, valence))
    arousal = max(0.0, min(1.0, arousal))
    conf = max(0.0, min(1.0, conf))

    return {"valence": valence, "arousal": arousal, "confidence": conf}
