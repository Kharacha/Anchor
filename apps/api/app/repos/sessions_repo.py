from sqlalchemy import text

def insert_user(conn, tier: str):
    return conn.execute(
        text("insert into users (tier) values (:tier) returning id"),
        {"tier": tier},
    ).scalar_one()

def insert_session(conn, session_id: str, user_id: str, max_sec: int, policy_version: str, model_version: str):
    conn.execute(
        text("""
            insert into sessions (id, user_id, status, max_duration_sec, policy_version, model_version)
            values (:id, :user_id, 'active', :max_sec, :policy_version, :model_version)
        """),
        {
            "id": session_id,
            "user_id": user_id,
            "max_sec": max_sec,
            "policy_version": policy_version,
            "model_version": model_version,
        },
    )
