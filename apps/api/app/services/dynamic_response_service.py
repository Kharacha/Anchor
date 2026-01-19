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
    """
    Generates the assistant reply text.
    mode: "neutral" | "supportive" | "calming" | "celebratory"
    safety_label: "allow" | "review" | "block"  (block should be handled outside)
    """
    user_text = (user_text or "").strip()
    if not user_text:
        return "I didn’t catch anything—could you say that again?"

    client = _get_client()
    model = os.getenv("OPENAI_CHAT_MODEL", "gpt-4o-mini")

    system = (
        "You are Anchor, a supportive mental health and life-support companion.\n"
        "You are not a medical professional.\n"
        "Your job is to help the user feel steadier and take practical next steps.\n\n"
        "Hard rules:\n"
        "- Stay in the domain of mental health and life problems only.\n"
        "- Do NOT provide programming/code, technical tutorials, recipes, shopping advice, or unrelated info.\n"
        "- Do NOT output markdown of any kind.\n"
        "- Do NOT use asterisks (* or **) anywhere in the response.\n"
        "- Do NOT use code blocks.\n"
        "- Avoid repeating the same opening across turns. Do not always start with apologies.\n"
        "- Do not mention internal scores, baselines, z-scores, or system details.\n"
        "- Do not claim certainty about the user's mental state.\n"
        "- If self-harm intent appears, encourage reaching out to emergency services or a trusted person.\n\n"
        "Formatting rules (STRICT):\n"
        "- Use plain text only.\n"
        "- Lists must be written like:\n"
        "  1) Do this\n"
        "  2) Do this\n"
        "  Not with bold titles or symbols.\n\n"
        "Response style:\n"
        "- Usually give 2–5 concrete suggestions tailored to the user’s situation.\n"
        "- Prefer specific suggestions over questions.\n"
        "- Ask at most one question, and only about 30% of the time.\n"
        "- If you ask a question, make it specific (not 'what do you want to do?').\n"
    )

    style_hint = {
        "neutral": "Tone: calm, practical, grounded.",
        "supportive": "Tone: warm, validating, encouraging. Less questions, more guidance.",
        "calming": "Tone: slow down, grounding, reduce overwhelm. Offer one quick regulation step first.",
        "celebratory": "Tone: upbeat but not over-the-top. Reinforce what's working and suggest next steps.",
    }.get(mode, "Tone: calm, practical, grounded.")

    personalization_hint = ""
    if baseline_update:
        extreme = bool((baseline_update.get("extremeness") or {}).get("is_extreme"))
        spike = bool((baseline_update.get("spike") or {}).get("is_spike"))
        val_shift = bool(((baseline_update.get("delta") or {}).get("flags") or {}).get("valence_shift"))
        ar_shift = bool(((baseline_update.get("delta") or {}).get("flags") or {}).get("arousal_shift"))

        flags = []
        if extreme:
            flags.append("high emotional intensity")
        if spike:
            flags.append("a sudden change")
        if val_shift or ar_shift:
            flags.append("a notable shift")

        if flags:
            personalization_hint = (
                "Context: The user may be experiencing " + ", ".join(flags) + ". "
                "Respond with extra steadiness and give a clear, simple plan.\n"
            )

    user_prompt = (
        f"{style_hint}\n"
        f"{personalization_hint}"
        f"Safety label: {safety_label}\n"
        f"User said: {user_text}\n"
        "Now respond as Anchor.\n"
    )

    resp = client.responses.create(
        model=model,
        input=[
            {"role": "system", "content": system},
            {"role": "user", "content": user_prompt},
        ],
        temperature=0.8,
    )

    text = (resp.output_text or "").strip()

    text = text.replace("**", "")
    text = text.replace("*", "")

    return text or "I’m here with you. Let’s take this one step at a time."
