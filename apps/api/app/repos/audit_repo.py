from sqlalchemy import text
from typing import Optional


def insert_audit(
    conn,
    session_id: str,
    event_type: str,
    data_json: str,
    policy_version: str,
    model_version: str,
    turn_id: Optional[str] = None,
    request_id: Optional[str] = None,
    event_seq: Optional[int] = None,
):
    conn.execute(
        text("""
            insert into audit_logs
              (session_id, turn_id, request_id, event_type, event_seq, data, policy_version, model_version)
            values
              (:session_id, cast(:turn_id as uuid), :request_id, :event_type, :event_seq,
               cast(:data as jsonb), :policy_version, :model_version)
        """),
        {
            "session_id": session_id,
            "turn_id": turn_id,          # uuid string or None
            "request_id": request_id,    # string or None
            "event_type": event_type,
            "event_seq": event_seq,
            "data": data_json,           # json string
            "policy_version": policy_version,
            "model_version": model_version,
        },
    )


def audit_event_exists(conn, session_id: str, turn_id: Optional[str], event_type: str) -> bool:
    if turn_id is None:
        row = conn.execute(
            text("""
                select 1
                from audit_logs
                where session_id = :session_id
                  and event_type = :event_type
                  and turn_id is null
                limit 1
            """),
            {"session_id": session_id, "event_type": event_type},
        ).first()
        return row is not None

    row = conn.execute(
        text("""
            select 1
            from audit_logs
            where session_id = :session_id
              and event_type = :event_type
              and turn_id = cast(:turn_id as uuid)
            limit 1
        """),
        {"session_id": session_id, "event_type": event_type, "turn_id": turn_id},
    ).first()
    return row is not None
