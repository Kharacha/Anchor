# apps/api/app/services/scoring_service.py
from __future__ import annotations

import re
from typing import Optional

from app.services.dynamic_scoring_service import score_text_openai


def score_text(
    text: str,
    *,
    chunk_confidences: list[tuple[str, float | None]] | None = None,
) -> dict:
    """
    Returns:
      {
        valence: float [-1,1],
        arousal: float [0,1],
        confidence: float [0,1],
        extremeness: float >=0,
        source: "openai"|"fallback",
        error: Optional[str]
      }
    """
    text = (text or "").strip()
    if not text:
        return {
            "valence": 0.0,
            "arousal": 0.0,
            "confidence": 0.0,
            "extremeness": 0.0,
            "source": "fallback",
            "error": "empty_text",
        }

    # -----------------------
    # STT prior confidence from chunks (does NOT represent emotion confidence)
    # -----------------------
    prior_conf = 0.9
    if chunk_confidences:
        total_chars = 0
        weighted = 0.0
        for chunk_text, conf in chunk_confidences:
            c = conf if conf is not None else 0.9
            n = len((chunk_text or ""))
            total_chars += n
            weighted += float(c) * n
        prior_conf = weighted / max(total_chars, 1)

    # -----------------------
    # optional: tiny "coherence" dampener on the prior only
    # -----------------------
    words = re.findall(r"\w+", text.lower())
    unique_ratio = (len(set(words)) / max(len(words), 1)) if words else 0.0
    coherence = 0.85 if (words and unique_ratio < 0.5) else (0.5 if not words else 1.0)
    prior_conf = max(0.0, min(1.0, prior_conf * coherence))

    try:
        # raw openai scoring (valence/arousal/conf)
        data = score_text_openai(text, chunk_confidences=chunk_confidences)

        valence = float(data.get("valence", 0.0))
        arousal = float(data.get("arousal", 0.0))
        conf = float(data.get("confidence", 0.5))

        # clamp
        valence = max(-1.0, min(1.0, valence))
        arousal = max(0.0, min(1.0, arousal))
        conf = max(0.0, min(1.0, conf))

        # blend with prior lightly so STT quality matters
        conf = round((0.8 * conf) + (0.2 * prior_conf), 2)

        extremeness = abs(valence) * (0.5 + 0.5 * arousal)

        return {
            "valence": valence,
            "arousal": arousal,
            "confidence": conf,
            "extremeness": extremeness,
            "source": "openai",
            "error": None,
        }

    except Exception as e:
        # deterministic fallback
        confidence = round(max(0.0, min(1.0, prior_conf * 0.6)), 2)
        return {
            "valence": 0.0,
            "arousal": 0.0,
            "confidence": confidence,
            "extremeness": 0.0,
            "source": "fallback",
            "error": f"{type(e).__name__}: {str(e)}",
        }
