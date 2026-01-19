# apps/api/app/services/domain_guard_service.py
from __future__ import annotations

import re
from typing import Tuple


# Strong out-of-domain triggers (requests that are clearly not "life/mental health support")
OOD_KEYWORDS = {
    # programming / dev
    "code", "coding", "program", "programming", "hello world", "python", "java", "javascript", "typescript",
    "c++", "c#", "golang", "rust", "sql", "postgres", "supabase", "api", "endpoint", "uvicorn", "fastapi",
    "react", "next.js", "nextjs", "node", "npm", "docker", "kubernetes", "linux", "windows",
    "debug", "bug", "error", "stack trace", "compile", "build",

    # school/homework style asks
    "solve this", "homework", "assignment", "quiz", "exam", "midterm",

    # shopping/recipes/etc
    "recipe", "cook", "ingredients", "oven", "bake", "hotel", "flight", "buy", "price",
}

# These topics are allowed even if they mention "work" or "job"
# (we explicitly do NOT treat job/career stress as out-of-domain)
ALLOWLIST_HINTS = {
    "anxiety", "anxious", "sad", "depressed", "stress", "stressed", "overwhelmed", "panic",
    "lonely", "burnout", "burned out", "confidence", "self esteem", "therapy", "feel", "feeling",
    "job", "career", "interview", "rejection", "money", "financial", "relationship", "breakup",
    "sleep", "insomnia", "motivation",
}


def _norm(s: str) -> str:
    s = (s or "").strip().lower()
    s = re.sub(r"\s+", " ", s)
    return s


def is_in_domain(user_text: str) -> Tuple[bool, str]:
    """
    Returns (in_domain, reason)
    Domain: mental health + life problems + emotional support + practical coping plans.
    """
    t = _norm(user_text)
    if not t:
        return True, "empty"

    # handle explicit out-of-domain triggers
    for kw in OOD_KEYWORDS:
        if kw in t:
            # If feelings/life support expressed along with out of domain triggers, then allow
            if any(h in t for h in ALLOWLIST_HINTS):
                return True, "contains_ood_but_feelings_present"
            return False, f"contains_ood_keyword:{kw}"

    return True, "ok"
