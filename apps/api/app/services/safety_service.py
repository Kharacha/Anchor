import json
from uuid import UUID

def classify_input(text: str) -> tuple[dict, bool]:
    t = (text or "").lower()

    # Placeholder rules. Keep it simple; we’ll swap in real classifier later.
    if any(p in t for p in ["how to kill myself", "suicide", "self harm", "kill myself"]):
        result = {"label": "block", "reasons": ["self_harm"], "meta": {}}
        return result, True

    result = {"label": "allow", "reasons": [], "meta": {}}
    return result, False


def to_json(d: dict) -> str:
    return json.dumps(
        d,
        ensure_ascii=False,
        default=lambda o: str(o) if isinstance(o, UUID) else str(o),
    )
