from uuid import uuid4
import json
import os

from app.repos import sessions_repo, audit_repo


def create_session(engine, tier: str, policy_version: str, model_version: str):
    if tier not in ("free", "paid"):
        raise ValueError("tier must be 'free' or 'paid'")

    max_sec = 3600 if tier == "free" else 600
    session_id = str(uuid4())

    stable_email = (os.getenv("ANCHOR_SINGLE_USER_EMAIL") or "").strip()

    with engine.begin() as conn:
        if stable_email:
            user_id = sessions_repo.get_or_create_user_by_email(
                conn, email=stable_email, tier=tier
            )
            sessions_repo.ensure_user_settings_row(conn, user_id)
        else:
            raise RuntimeError(
                "ANCHOR_SINGLE_USER_EMAIL not set — baseline persistence disabled"
            )

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
            data_json=json.dumps(
                {"tier": tier, "max_duration_sec": max_sec}
            ),
            policy_version=policy_version,
            model_version=model_version,
        )

    return session_id, user_id, max_sec
