# apps/api/app/services/response_service.py
from __future__ import annotations

from typing import Any, Dict

from app.services.dynamic_response_service import generate_assistant_text_openai
from app.services.domain_guard_service import is_in_domain


def _ood_redirect_message(user_text: str) -> str:
    """
    Friendly but firm domain boundary with a natural redirect.
    Plain text only. No markdown. No quoting the user's off-topic request.
    """
    return (
        "I can’t help with that request. Anchor is specifically designed for mental health "
        "and life support, so I need to stay focused on that.\n\n"
        "If you’d like, we can shift back to what’s been weighing on you — "
        "stress, anxiety, motivation, confidence, work pressure, relationships, or anything else "
        "that’s affecting how you’re feeling lately."
    )


def generate_assistant_response(
    *,
    transcript: str,
    safety: Dict[str, Any],
    scores: Dict[str, Any] | None = None,
    baseline_update: Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    """
    Returns:
      {
        "assistant_text": str,
        "source": "openai"|"fallback"|"domain_block",
        "mode": str,
        "error": Optional[str],
      }
    """
    transcript = (transcript or "").strip()
    safety_label = (safety or {}).get("label", "allow")

    # restrict domain to therapy/life support only
    in_domain, reason = is_in_domain(transcript)
    if not in_domain:
        return {
            "assistant_text": _ood_redirect_message(transcript),
            "source": "domain_block",
            "mode": "neutral",
            "error": reason,
        }

    mode = "neutral"
    if scores:
        v = scores.get("valence")
        a = scores.get("arousal")
        extreme = bool(scores.get("extremeness", 0) >= 0.55)

        try:
            if extreme and a is not None and float(a) >= 0.65:
                mode = "calming"
            elif v is not None and float(v) <= -0.35:
                mode = "supportive"
            elif v is not None and float(v) >= 0.5:
                mode = "celebratory"
        except Exception:
            pass

    # baseline can override to be steadier
    if baseline_update:
        try:
            if bool((baseline_update.get("extremeness") or {}).get("is_extreme")):
                mode = "calming"
            if bool((baseline_update.get("spike") or {}).get("is_spike")):
                mode = "calming"
        except Exception:
            pass

    try:
        text = generate_assistant_text_openai(
            user_text=transcript,
            mode=mode,
            safety_label=safety_label,
            baseline_update=baseline_update,
        )
        return {"assistant_text": text, "source": "openai", "mode": mode, "error": None}

    except Exception as e:
        fallback = (
            "I hear you. Here are two small things we can try right now:\n"
            "1) Take one slow breath in for 4 seconds, out for 6.\n"
            "2) Name the pressure in one sentence (for example: 'job search stress' or 'money worries')."
        )
        return {
            "assistant_text": fallback,
            "source": "fallback",
            "mode": mode,
            "error": f"{type(e).__name__}: {str(e)}",
        }
