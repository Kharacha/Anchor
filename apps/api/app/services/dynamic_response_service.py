# apps/api/app/services/dynamic_response_service.py
from __future__ import annotations

import os
from typing import Optional, Dict, Any

from openai import OpenAI

_client: Optional[OpenAI] = None


def _get_client() -> OpenAI:
    global _client
    if _client is None:
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            raise RuntimeError("OPENAI_API_KEY is not set in environment")
        _client = OpenAI(api_key=api_key)
    return _client


def generate_assistant_text_openai(
    *,
    user_text: str,
    mode: str,
    safety_label: str,
    baseline_update: Dict[str, Any] | None = None,
) -> str:
    user_text = (user_text or "").strip()
    if not user_text:
        return "I didn’t catch anything—could you say that again?"

    client = _get_client()
    model = os.getenv("OPENAI_CHAT_MODEL", "gpt-4o-mini")

    # IMPORTANT: This system prompt is designed to prevent the exact failure mode you showed.
    system = (
        "You are Anchor: a supportive, therapist-style mental health and life-support companion.\n"
        "You are not a medical professional.\n\n"
        "Core behavior:\n"
        "- Give direct help immediately. Do NOT start by describing what you can help with.\n"
        "- Do NOT ask for more info as a default. Only ask ONE question if it is essential.\n"
        "- Be adaptive: reflect the user’s situation, validate, then give a clear plan.\n\n"
        "Hard bans:\n"
        "- Do not say: 'I can help with mental health...' or 'I can’t help with that request...' unless explicitly told to refuse.\n"
        "- Do not mention being restricted, being designed for a domain, or 'staying focused on that'.\n"
        "- No programming/code/tutorials, no recipes/shopping/travel advice.\n"
        "- No markdown. No asterisks. No bullet symbols like • or -.\n"
        "- Lists must use:\n"
        "  1) ...\n"
        "  2) ...\n"
        "  3) ...\n\n"
        "Response structure (most of the time):\n"
        "1) 1–2 sentences: empathic reflection + validation.\n"
        "2) 2–5 concrete suggestions tailored to the situation.\n"
        "3) Optional: ONE specific question only if needed.\n\n"
        "Quality rules:\n"
        "- Be specific and practical (exams, focus, loneliness, dating, anxiety, etc.).\n"
        "- Don’t be preachy. Don’t over-apologize.\n"
        "- Don’t claim certainty about diagnoses.\n"
    )

    style_hint = {
        "neutral": "Tone: calm, practical, grounded.",
        "supportive": "Tone: warm, validating, encouraging. More guidance, fewer questions.",
        "calming": "Tone: slow down and reduce overwhelm. Offer one quick regulation step first.",
        "celebratory": "Tone: upbeat but grounded. Reinforce what’s working, suggest next step.",
    }.get(mode, "Tone: calm, practical, grounded.")

    personalization_hint = ""
    if baseline_update:
        extreme = bool((baseline_update.get("extremeness") or {}).get("is_extreme"))
        spike = bool((baseline_update.get("spike") or {}).get("is_spike"))
        if extreme or spike:
            personalization_hint = (
                "Extra guidance: Keep it very steady and simple. Offer a short 2-step plan first.\n"
            )

    user_prompt = (
        f"{style_hint}\n"
        f"{personalization_hint}"
        f"Safety label: {safety_label}\n"
        f"User said: {user_text}\n"
        "Respond as Anchor now.\n"
    )

    resp = client.responses.create(
        model=model,
        input=[
            {"role": "system", "content": system},
            {"role": "user", "content": user_prompt},
        ],
        temperature=0.7,
    )

    text = (resp.output_text or "").strip()

    # enforce “no asterisks” rule
    text = text.replace("**", "").replace("*", "")

    # final guard: if it still starts with capability talk, rewrite locally
    low = text.lower()
    if low.startswith("i can help with") or "anchor is specifically designed" in low:
        text = (
            "I hear you. That sounds heavy to carry.\n\n"
            "1) Tell me the one part that feels most painful or urgent right now.\n"
            "2) Then we’ll pick one small step you can do today to make it feel lighter."
        )

    return text or "I’m here with you. Let’s take this one step at a time."
