from uuid import uuid4
import json

from app.repos import sessions_repo, audit_repo


def create_session(engine, tier: str, policy_version: str, model_version: str):
    if tier not in ("free", "paid"):
        raise ValueError("tier must be 'free' or 'paid'")

    max_sec = 5 if tier == "free" else 600
    session_id = str(uuid4())

    with engine.begin() as conn:
        user_id = str(sessions_repo.insert_user(conn, tier))

        sessions_repo.insert_session(
            conn,
            session_id=session_id,
            user_id=user_id,
            max_duration_sec=max_sec,
            policy_version=policy_version,
            model_version=model_version,
        )

        audit_repo.insert_audit(
            conn,
            session_id=session_id,
            event_type="session_start",
            data_json=json.dumps({"tier": tier, "max_duration_sec": max_sec}),
            policy_version=policy_version,
            model_version=model_version,
        )

    return session_id, user_id, max_sec
