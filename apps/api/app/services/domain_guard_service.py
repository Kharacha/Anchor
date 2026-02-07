# apps/api/app/services/domain_guard_service.py
from __future__ import annotations

import re
from typing import Tuple


# =========================================================
# Anchor domain philosophy:
# - Be permissive for mental health + life support.
# - Allow disorders/phobias/therapy questions ALWAYS.
# - Allow school/work/grades/exams/studying IF user is asking for coping/help.
# - Block only clear non-support requests (pure dev help, "solve my homework", pure shopping/recipes).
# =========================================================

OOD_TECH_TERMS = {
    "code", "coding", "program", "programming",
    "python", "java", "javascript", "typescript", "c++", "c#", "golang", "rust",
    "sql", "postgres", "supabase", "api", "endpoint", "uvicorn", "fastapi",
    "react", "next.js", "nextjs", "node", "npm", "docker", "kubernetes",
    "linux", "windows", "debug", "bug", "stack trace", "compile", "build",
}

OOD_HOMEWORK_SOLVE_PHRASES = {
    "solve this", "do my homework", "do my assignment", "answer these questions",
    "write my essay", "finish my lab", "give me the answers", "cheat",
}

OOD_LIFESTYLE_COMMERCE_TERMS = {
    "recipe", "ingredients", "cook", "oven", "bake",
    "hotel", "flight", "book a flight", "buy", "price", "deal", "coupon",
}

# Always-in-domain signals (mental health + life support)
MENTAL_HEALTH_TERMS = {
    "anxiety", "anxious", "panic", "panic attack", "stressed", "stress", "overwhelmed",
    "sad", "depressed", "depression", "lonely", "burnout", "burned out", "hopeless",
    "fear", "phobia", "phobic", "trauma", "grief", "anger", "irritable", "rumination",
    "therapy", "therapist", "coping", "cope", "strategies", "tools", "skills",
    "mindfulness", "grounding", "breathing", "self esteem", "confidence",
    "motivation", "procrastination", "habit", "routine",
    "boundaries", "communication", "support",
    "help me", "what can i do", "how can i", "what should i do", "tips",
    "adhd", "add", "ocd", "ptsd", "autism", "bipolar", "borderline",
    "eating disorder", "anorexia", "bulimia", "panic disorder", "social anxiety",
    "generalized anxiety", "gad",
    "focus", "attention", "executive function", "executive dysfunction",
    "concentration", "memory", "brain fog",
    "sleep", "insomnia", "nightmare",
}

# Life contexts are in-domain when paired with “help/cope/strategies”
LIFE_CONTEXT_TERMS = {
    "job", "career", "interview", "rejection", "work", "boss", "coworker",
    "relationship", "breakup", "dating", "family", "friends",
    "money", "financial", "rent", "bills",
    "school", "class", "classes", "exam", "exams", "midterm", "final", "grades",
    "study", "studying", "homework", "assignment", "deadline",
}

HELP_FRAMING_TERMS = {
    "help", "advice", "strategies", "coping", "cope", "tools", "skills",
    "plan", "how do i", "how can i", "what should i do", "tips",
    "hard", "struggling", "can't focus", "cant focus", "overwhelmed",
}

SELF_HARM_PHRASES = {
    "suicide", "kill myself", "end my life", "self harm", "hurt myself", "cut myself",
    "how to kill myself",
}


def _norm(s: str) -> str:
    s = (s or "").strip().lower()
    s = re.sub(r"\s+", " ", s)
    return s


def _contains_any_phrase(t: str, phrases: set[str]) -> bool:
    return any(p in t for p in phrases)


def _contains_any_word(t: str, words: set[str]) -> bool:
    # word-ish boundary match to avoid partial hits
    for w in words:
        pattern = r"(?<!\w)" + re.escape(w) + r"(?!\w)"
        if re.search(pattern, t):
            return True
    return False


def _has_in_domain_signal(t: str) -> bool:
    if _contains_any_phrase(t, SELF_HARM_PHRASES):
        return True
    if _contains_any_word(t, MENTAL_HEALTH_TERMS):
        return True
    if _contains_any_word(t, LIFE_CONTEXT_TERMS) and _contains_any_word(t, HELP_FRAMING_TERMS):
        return True
    return False


def is_in_domain(user_text: str) -> Tuple[bool, str]:
    """
    Returns (in_domain, reason)
    Domain: mental health + life problems + emotional support + practical coping plans.
    """
    t = _norm(user_text)
    if not t:
        return True, "empty"

    # Never domain-block self-harm language; safety handles it.
    if _contains_any_phrase(t, SELF_HARM_PHRASES):
        return True, "self_harm_routed_to_safety"

    in_domain_signal = _has_in_domain_signal(t)

    # Explicit “do the work for me” homework/cheating: out-of-domain
    if _contains_any_phrase(t, OOD_HOMEWORK_SOLVE_PHRASES):
        return False, "contains_homework_solve_phrase"

    # Tech requests: only out-of-domain if no support framing
    if _contains_any_word(t, OOD_TECH_TERMS) and not in_domain_signal:
        return False, "contains_tech_terms_without_support_framing"

    # Commerce/recipes/travel: only out-of-domain if no support framing
    if _contains_any_word(t, OOD_LIFESTYLE_COMMERCE_TERMS) and not in_domain_signal:
        return False, "contains_commerce_terms_without_support_framing"

    # Default: allow (permissive). If it’s actually mildly off-topic,
    # the response layer can gently steer without refusing.
    return True, ("support_framing_present" if in_domain_signal else "default_allow")
