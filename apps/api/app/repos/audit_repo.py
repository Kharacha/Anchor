from sqlalchemy import text

def insert_audit(conn, session_id: str, event_type: str, data_json: str, policy_version: str, model_version: str):
    conn.execute(
        text("""
            insert into audit_logs (session_id, event_type, data, policy_version, model_version)
            values (:session_id, :event_type, cast(:data as jsonb), :policy_version, :model_version)
        """),
        {
            "session_id": session_id,
            "event_type": event_type,
            "data": data_json,  # <-- THIS was missing in your parameters before
            "policy_version": policy_version,
            "model_version": model_version,
        },
    )
