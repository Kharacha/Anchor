from __future__ import annotations

from datetime import datetime, timedelta, timezone
import re
from sqlalchemy import text

# Gated retrieval triggers
TRIGGER_RETRIEVAL = re.compile(r"\b(remember|as we talked|you said earlier|last time|like before)\b", re.I)

# Simple, cheap “worth saving?” rules (no LLM)
REMEMBER_PATTERNS = [
    (re.compile(r"\bmy name is (.+)", re.I), "bio"),
    (re.compile(r"\bi prefer (.+)", re.I), "preference"),
    (re.compile(r"\bi like (.+)", re.I), "preference"),
    (re.compile(r"\bi don't like (.+)", re.I), "preference"),
    (re.compile(r"\bmy goal is (.+)", re.I), "goal"),
    (re.compile(r"\bremember (that )?(.+)", re.I), "preference"),
]


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def should_retrieve_memory(text_in: str) -> bool:
    return bool(TRIGGER_RETRIEVAL.search(text_in or ""))


def extract_memory_items(text_in: str) -> list[tuple[str, str]]:
    """
    Returns list of (category, summary) bullet candidates.
    """
    t = (text_in or "").strip()
    out: list[tuple[str, str]] = []

    for rgx, cat in REMEMBER_PATTERNS:
        m = rgx.search(t)
        if not m:
            continue
        # last capture group tends to hold the meaningful payload
        val = (m.group(m.lastindex or 1) or "").strip()
        val = val[:180]
        if val:
            out.append((cat, val))

    return out[:3]


def decay_memory(conn, *, user_id: str):
    """
    Hard-delete expired rows (cheap). Called after responding.
    """
    conn.execute(
        text(
            """
            delete from memory_items
            where user_id = cast(:user_id as uuid)
              and expires_at <= now()
            """
        ),
        {"user_id": user_id},
    )


def upsert_memory_item(conn, *, user_id: str, category: str, summary: str, now_dt: datetime | None = None):
    """
    De-dup by exact (user_id, category, summary) via a manual check; keeps schema simple.
    Expiry policy: base 14 days.
    """
    now_dt = now_dt or now_utc()
    expires = now_dt + timedelta(days=14)

    existing = conn.execute(
        text(
            """
            select id
            from memory_items
            where user_id = cast(:user_id as uuid)
              and category = :cat
              and summary = :sum
            limit 1
            """
        ),
        {"user_id": user_id, "cat": category, "sum": summary},
    ).first()

    if existing:
        # reinforce slightly + extend expiry
        conn.execute(
            text(
                """
                update memory_items
                set strength = least(5.0, strength + 0.5),
                    last_seen_at = :now,
                    expires_at = greatest(expires_at, :exp)
                where id = cast(:id as uuid)
                """
            ),
            {"id": str(existing[0]), "now": now_dt, "exp": expires},
        )
        return

    conn.execute(
        text(
            """
            insert into memory_items (user_id, category, summary, strength, last_seen_at, created_at, expires_at)
            values (cast(:user_id as uuid), :cat, :sum, 1.0, :now, :now, :exp)
            """
        ),
        {"user_id": user_id, "cat": category, "sum": summary, "now": now_dt, "exp": expires},
    )


def fetch_active_memory(conn, *, user_id: str, limit: int = 10):
    rows = conn.execute(
        text(
            """
            select category, summary, strength
            from memory_items
            where user_id = cast(:user_id as uuid)
              and expires_at > now()
            order by strength desc, last_seen_at desc
            limit :lim
            """
        ),
        {"user_id": user_id, "lim": int(limit)},
    ).mappings().all()

    return list(rows)


def format_memory_for_prompt(rows) -> str:
    """
    Returns a tiny, safe context block. No labeling emotions, just continuity facts/preferences/goals.
    """
    if not rows:
        return ""

    bullets = []
    for r in rows[:10]:
        cat = (r.get("category") or "").strip()
        summary = (r.get("summary") or "").strip()
        if not summary:
            continue
        if cat:
            bullets.append(f"- ({cat}) {summary}")
        else:
            bullets.append(f"- {summary}")

    if not bullets:
        return ""

    return "Active memory (use only if relevant):\n" + "\n".join(bullets) + "\n"
