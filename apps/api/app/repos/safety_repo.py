from sqlalchemy import text

def insert_safety_event(
    conn,
    session_id: str,
    turn_id: str | None,
    stage: str,
    action: str,
    category: str | None,
    severity: float | None,
    classification_json: str,
    fallback_used: bool,
    policy_version: str,
    model_version: str,
):
    conn.execute(
        text("""
            insert into safety_events (
              session_id, turn_id, stage, action, category, severity,
              classification, fallback_used, policy_version, model_version
            )
            values (
              :session_id, :turn_id, :stage, :action, :category, :severity,
              cast(:classification as jsonb), :fallback_used, :policy_version, :model_version
            )
        """),
        {
            "session_id": session_id,
            "turn_id": turn_id,
            "stage": stage,
            "action": action,
            "category": category,
            "severity": severity,
            "classification": classification_json,
            "fallback_used": fallback_used,
            "policy_version": policy_version,
            "model_version": model_version,
        },
    )
