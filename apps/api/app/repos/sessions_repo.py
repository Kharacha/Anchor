from sqlalchemy import text

def insert_user(conn, tier: str):
    return conn.execute(
        text("insert into users (tier) values (:tier) returning id"),
        {"tier": tier},
    ).scalar_one()

def insert_session(
    conn,
    session_id: str,
    user_id: str,
    max_duration_sec: int,
    policy_version: str,
    model_version: str,
):
    conn.execute(
        text("""
            insert into sessions (id, user_id, max_duration_sec, policy_version, model_version)
            values (:id, :user_id, :max_duration_sec, :policy_version, :model_version)
        """),
        {
            "id": session_id,
            "user_id": user_id,
            "max_duration_sec": max_duration_sec,
            "policy_version": policy_version,
            "model_version": model_version,
        },
    )

def get_session_timing(conn, session_id: str):
    """
    Returns (status, max_duration_sec, started_at, elapsed_sec, remaining_sec)
    elapsed/remaining computed in DB for consistency.
    """
    row = conn.execute(
        text("""
            select
              status,
              max_duration_sec,
              started_at,
              extract(epoch from (now() - started_at))::int as elapsed_sec,
              greatest(max_duration_sec - extract(epoch from (now() - started_at))::int, 0) as remaining_sec
            from sessions
            where id = :session_id
        """),
        {"session_id": session_id},
    ).mappings().first()

    if not row:
        return None

    return (
        row["status"],
        int(row["max_duration_sec"]),
        row["started_at"],
        int(row["elapsed_sec"]),
        int(row["remaining_sec"]),
    )


def end_session(conn, session_id: str):
    conn.execute(
        text("""
            update sessions
            set status = 'ended', ended_at = now()
            where id = :session_id and status <> 'ended'
        """),
        {"session_id": session_id},
    )
