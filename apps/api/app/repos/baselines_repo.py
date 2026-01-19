# apps/api/app/repos/baselines_repo.py

from __future__ import annotations

from sqlalchemy import text


def get_user_baseline(conn, user_id: str) -> dict | None:
    row = conn.execute(
        text("""
            select
              valence_mean, valence_var,
              arousal_mean, arousal_var,
              speech_rate_mean, speech_rate_var,
              pause_ratio_mean, pause_ratio_var
            from user_baselines
            where user_id = cast(:user_id as uuid)
            limit 1
        """),
        {"user_id": user_id},
    ).mappings().first()

    return dict(row) if row else None


def ensure_user_baseline_row(conn, user_id: str) -> None:
    conn.execute(
        text("""
            insert into user_baselines (
              user_id,
              valence_mean, valence_var,
              arousal_mean, arousal_var,
              speech_rate_mean, speech_rate_var,
              pause_ratio_mean, pause_ratio_var,
              updated_at
            )
            values (
              cast(:user_id as uuid),
              0, 0,
              0, 0,
              null, null,
              null, null,
              now()
            )
            on conflict (user_id) do nothing
        """),
        {"user_id": user_id},
    )


def upsert_user_baseline(
    conn,
    user_id: str,
    valence_mean: float | None,
    valence_var: float | None,
    arousal_mean: float | None,
    arousal_var: float | None,
    speech_rate_mean: float | None = None,
    speech_rate_var: float | None = None,
    pause_ratio_mean: float | None = None,
    pause_ratio_var: float | None = None,
):
    conn.execute(
        text("""
            insert into user_baselines (
              user_id,
              valence_mean, valence_var,
              arousal_mean, arousal_var,
              speech_rate_mean, speech_rate_var,
              pause_ratio_mean, pause_ratio_var,
              updated_at
            )
            values (
              cast(:user_id as uuid),
              :valence_mean, :valence_var,
              :arousal_mean, :arousal_var,
              :speech_rate_mean, :speech_rate_var,
              :pause_ratio_mean, :pause_ratio_var,
              now()
            )
            on conflict (user_id) do update set
              valence_mean = excluded.valence_mean,
              valence_var  = excluded.valence_var,
              arousal_mean = excluded.arousal_mean,
              arousal_var  = excluded.arousal_var,
              speech_rate_mean = excluded.speech_rate_mean,
              speech_rate_var  = excluded.speech_rate_var,
              pause_ratio_mean = excluded.pause_ratio_mean,
              pause_ratio_var  = excluded.pause_ratio_var,
              updated_at = now()
        """),
        {
            "user_id": user_id,
            "valence_mean": valence_mean,
            "valence_var": valence_var,
            "arousal_mean": arousal_mean,
            "arousal_var": arousal_var,
            "speech_rate_mean": speech_rate_mean,
            "speech_rate_var": speech_rate_var,
            "pause_ratio_mean": pause_ratio_mean,
            "pause_ratio_var": pause_ratio_var,
        },
    )


def insert_baseline_event(conn, user_id: str, session_id: str, data_json: str):
    conn.execute(
        text("""
            insert into baseline_events (user_id, session_id, data, created_at)
            values (cast(:user_id as uuid), cast(:session_id as uuid), cast(:data as jsonb), now())
        """),
        {"user_id": user_id, "session_id": session_id, "data": data_json},
    )
