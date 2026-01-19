from sqlalchemy import text


def get_or_create_user_by_email(conn, *, email: str, tier: str) -> str:
    row = conn.execute(
        text("""
            select id
            from users
            where email = :email
            limit 1
        """),
        {"email": email},
    ).first()

    if row:
        return str(row[0])

    user_id = conn.execute(
        text("""
            insert into users (email, tier)
            values (:email, :tier)
            returning id
        """),
        {"email": email, "tier": tier},
    ).scalar_one()

    return str(user_id)


def ensure_user_settings_row(conn, user_id: str):
    conn.execute(
        text("""
            insert into user_settings (user_id)
            values (cast(:user_id as uuid))
            on conflict (user_id) do nothing
        """),
        {"user_id": user_id},
    )


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
            values (:id, cast(:user_id as uuid), :max_duration_sec, :policy_version, :model_version)
        """),
        {
            "id": session_id,
            "user_id": user_id,
            "max_duration_sec": max_duration_sec,
            "policy_version": policy_version,
            "model_version": model_version,
        },
    )


def get_session_user_id(conn, session_id: str) -> str | None:
    row = conn.execute(
        text("""
            select user_id::text as user_id
            from sessions
            where id = cast(:session_id as uuid)
            limit 1
        """),
        {"session_id": session_id},
    ).mappings().first()

    return str(row["user_id"]) if row else None


def get_session_timing(conn, session_id: str):
    row = conn.execute(
        text("""
            select
              status,
              max_duration_sec,
              started_at,
              extract(epoch from (now() - started_at))::int as elapsed_sec,
              greatest(max_duration_sec - extract(epoch from (now() - started_at))::int, 0) as remaining_sec
            from sessions
            where id = cast(:session_id as uuid)
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
            where id = cast(:session_id as uuid)
              and status <> 'ended'
        """),
        {"session_id": session_id},
    )
