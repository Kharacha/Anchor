from uuid import uuid4
from app.repos import sessions_repo, audit_repo

def create_session(engine, tier: str, policy_version: str, model_version: str):
    max_sec = 300 if tier == "free" else 600
    session_id = str(uuid4())

    with engine.begin() as conn:
        user_id = sessions_repo.insert_user(conn, tier)
        sessions_repo.insert_session(conn, session_id, str(user_id), max_sec, policy_version, model_version)
        audit_repo.insert_audit(
            conn,
            session_id,
            "session_start",
            f'{{"tier":"{tier}","max_duration_sec":{max_sec}}}',
            policy_version,
            model_version,
        )

    return session_id, str(user_id), max_sec
