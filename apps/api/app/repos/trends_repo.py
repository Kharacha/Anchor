# apps/api/app/repos/trends_repo.py

from __future__ import annotations

from sqlalchemy import text


def upsert_daily_bucket(
    conn,
    *,
    user_id: str,
    day: str,  # YYYY-MM-DD
    valence: float,
    arousal: float,
    confidence: float,
    extremeness: float,
) -> None:
    """
    daily_trends stores SUMS + count (n).
    Means are computed at read-time: mean = sum / n.

    Matches Supabase schema:
      user_id uuid
      day date
      n int
      valence_sum float8
      arousal_sum float8
      confidence_sum float8
      extremeness_sum float8
      updated_at timestamptz
    """
    conn.execute(
        text(
            """
            insert into daily_trends (
              user_id, day, n,
              valence_sum, arousal_sum, confidence_sum, extremeness_sum
            )
            values (
              cast(:user_id as uuid),
              cast(:day as date),
              1,
              :valence, :arousal, :confidence, :extremeness
            )
            on conflict (user_id, day) do update set
              n = daily_trends.n + 1,
              valence_sum = coalesce(daily_trends.valence_sum, 0) + :valence,
              arousal_sum = coalesce(daily_trends.arousal_sum, 0) + :arousal,
              confidence_sum = coalesce(daily_trends.confidence_sum, 0) + :confidence,
              extremeness_sum = coalesce(daily_trends.extremeness_sum, 0) + :extremeness,
              updated_at = now()
            """
        ),
        {
            "user_id": user_id,
            "day": day,
            "valence": float(valence),
            "arousal": float(arousal),
            "confidence": float(confidence),
            "extremeness": float(extremeness),
        },
    )


def list_daily_trends(conn, *, user_id: str, days: int = 30):
    """
    Returns points with MEANS computed from sums / n:
      { day, n, valence_mean, arousal_mean, confidence_mean, extremeness_mean }

    Note: we return only days that exist in the table (sparse series).
    """
    try:
        days = int(days)
    except Exception:
        days = 30
    days = max(1, min(days, 180))

    rows = conn.execute(
        text(
            """
            select
              to_char(day, 'YYYY-MM-DD') as day,
              n,
              (valence_sum / nullif(n, 0)) as valence_mean,
              (arousal_sum / nullif(n, 0)) as arousal_mean,
              (confidence_sum / nullif(n, 0)) as confidence_mean,
              (extremeness_sum / nullif(n, 0)) as extremeness_mean
            from daily_trends
            where user_id = cast(:user_id as uuid)
              and day >= (current_date - (:days - 1))
            order by day asc
            """
        ),
        {"user_id": user_id, "days": days},
    ).mappings().all()

    return [dict(r) for r in rows]
