# apps/api/app/services/response_service.py
from __future__ import annotations

from typing import Any, Dict, Optional

from app.services.dynamic_response_service import generate_assistant_text_openai
from app.services.domain_guard_service import is_in_domain


def _ood_redirect_message() -> str:
    # Short, not hostile, and gives ONE redirect question.
    return (
        "I’m not the best fit for that specific request. "
        "But I can help with what you’re dealing with emotionally or in your life.\n\n"
        "What’s the main pressure you’re feeling right now?"
    )


def _crisis_support_message() -> str:
    return (
        "I’m really sorry you’re dealing with this. You don’t have to carry it alone.\n\n"
        "If you feel in immediate danger or might act on those thoughts, please call your local emergency number now.\n"
        "If you’re in the U.S., you can call or text 988 (Suicide & Crisis Lifeline).\n\n"
        "If you’re not in immediate danger: tell me what’s happening right now — what triggered this feeling today, "
        "and whether you’re alone or with someone — and we’ll focus on getting you through the next 10–30 minutes safely."
    )


def generate_assistant_response(
    *,
    transcript: str,
    safety: Dict[str, Any],
    scores: Optional[Dict[str, Any]] = None,
    baseline_update: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    transcript = (transcript or "").strip()
    safety_label = (safety or {}).get("label", "allow")

    # Domain guard (ONLY true OOD gets redirected)
    in_domain, reason = is_in_domain(transcript)
    if not in_domain:
        return {
            "assistant_text": _ood_redirect_message(),
            "source": "domain_block",
            "mode": "neutral",
            "error": reason,
        }

    # Crisis routing (never domain-block)
    if safety_label in {"block", "review"} and "self_harm" in (safety or {}).get("reasons", []):
        return {
            "assistant_text": _crisis_support_message(),
            "source": "fallback",
            "mode": "calming",
            "error": "self_harm_routed",
        }

    # Mode selection (kept)
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

    if baseline_update:
        try:
            if bool((baseline_update.get("extremeness") or {}).get("is_extreme")):
                mode = "calming"
            if bool((baseline_update.get("spike") or {}).get("is_spike")):
                mode = "calming"
        except Exception:
            pass

    # Generate (OpenAI)
    try:
        text = generate_assistant_text_openai(
            user_text=transcript,
            mode=mode,
            safety_label=safety_label,
            baseline_update=baseline_update,
        )

        # If model still tries “capability talk”, replace with a helpful opener
        tlow = (text or "").lower()
        bad_openers = [
            "i can help with mental health",
            "i can’t help with that request",
            "i can't help with that request",
            "i need to stay focused on that",
            "anchor is specifically designed",
        ]
        if any(b in tlow for b in bad_openers):
            text = (
                "I hear you. Let’s make this feel more manageable.\n\n"
                "Tell me the one part that’s hitting you hardest right now, and I’ll give you a clear next-step plan."
            )

        return {"assistant_text": text, "source": "openai", "mode": mode, "error": None}

    except Exception as e:
        fallback = (
            "I hear you. Let’s make this manageable.\n\n"
            "1) Pick the smallest next step you can do in 5 minutes.\n"
            "2) Set a timer for 10 minutes and do only that.\n"
            "3) When it ends, tell me what got in the way (distraction, anxiety, low energy, etc.)."
        )
        return {
            "assistant_text": fallback,
            "source": "fallback",
            "mode": mode,
            "error": f"{type(e).__name__}: {str(e)}",
        }
