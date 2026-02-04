# apps/api/app/services/trends_service.py

from __future__ import annotations

from typing import Any, Dict

from app.repos import sessions_repo, trends_repo


def get_daily_trends(engine, *, session_id: str, days: int = 30) -> Dict[str, Any]:
    """
    Returns last N days of daily aggregated derived scores for the session's user.

    Notes:
    - Trends load is NOT on the chat response path (chat path only does the upsert).
    - DB stores sums + n, repo returns means.
    """

    try:
        days_int = int(days)
    except Exception:
        days_int = 30
    days_int = max(1, min(days_int, 180))

    with engine.begin() as conn:
        user_id = sessions_repo.get_session_user_id(conn, session_id)
        if not user_id:
            raise ValueError("session not found (or missing user)")

        user_id_str = str(user_id)

        points = trends_repo.list_daily_trends(
            conn,
            user_id=user_id_str,
            days=days_int,
        )

    return {
        "session_id": session_id,
        "user_id": user_id_str,
        "days": days_int,
        "points": points,
    }
