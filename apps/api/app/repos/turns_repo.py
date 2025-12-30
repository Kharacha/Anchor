from sqlalchemy import text


def insert_turn(conn, session_id: str, request_id: str | None = None) -> str:
    """
    Inserts a new turn for a session with an auto-computed turn_index (0,1,2,...).
    Respects: turns.turn_index NOT NULL + unique(session_id, turn_index).
    """
    return conn.execute(
        text("""
            insert into turns (session_id, turn_index, request_id)
            values (
                :session_id,
                coalesce(
                    (select max(turn_index) + 1 from turns where session_id = :session_id),
                    0
                ),
                :request_id
            )
            returning id
        """),
        {"session_id": session_id, "request_id": request_id},
    ).scalar_one()


def next_utterance_seq(conn, session_id: str) -> int:
    """
    Utterances have a global per-session sequence: unique(session_id, seq).
    Computes next seq safely inside the current transaction.
    """
    return conn.execute(
        text("""
            select coalesce(max(seq) + 1, 0)
            from utterances
            where session_id = :session_id
        """),
        {"session_id": session_id},
    ).scalar_one()


def insert_utterance(
    conn,
    session_id: str,
    turn_id: str | None,
    role: str,
    text_content: str,
    chunk_index: int | None = None,
) -> str:
    """
    Inserts an utterance row matching your schema:
      utterances(session_id, turn_id, role, seq, chunk_index, text)

    NOTE: schema uses column name `text`, not `content`.
    """
    seq = next_utterance_seq(conn, session_id)

    return conn.execute(
        text("""
            insert into utterances (session_id, turn_id, role, seq, chunk_index, text)
            values (:session_id, :turn_id, :role, :seq, :chunk_index, :text)
            returning id
        """),
        {
            "session_id": session_id,
            "turn_id": turn_id,
            "role": role,
            "seq": seq,
            "chunk_index": chunk_index,
            "text": text_content,
        },
    ).scalar_one()


def insert_assistant_message(
    conn,
    session_id: str,
    turn_id: str | None,
    final_text: str,
    policy_version: str,
    model_version: str,
    draft_text: str | None = None,
    fallback_used: bool = False,
    fallback_type: str | None = None,
    evidence_json: str = "{}",
) -> str:
    """
    Inserts assistant_messages matching your schema:
      assistant_messages(session_id, turn_id, draft_text, final_text, fallback_used, fallback_type, evidence, policy_version, model_version)
    """
    return conn.execute(
        text("""
            insert into assistant_messages (
              session_id, turn_id, draft_text, final_text,
              fallback_used, fallback_type,
              evidence, policy_version, model_version
            )
            values (
              :session_id, :turn_id, :draft_text, :final_text,
              :fallback_used, :fallback_type,
              cast(:evidence as jsonb), :policy_version, :model_version
            )
            returning id
        """),
        {
            "session_id": session_id,
            "turn_id": turn_id,
            "draft_text": draft_text,
            "final_text": final_text,
            "fallback_used": fallback_used,
            "fallback_type": fallback_type,
            "evidence": evidence_json,
            "policy_version": policy_version,
            "model_version": model_version,
        },
    ).scalar_one()

def set_turn_timing(conn, turn_id: str, elapsed_sec: int, remaining_sec: int, gated: bool):
    conn.execute(
        text("""
            update turns
            set elapsed_session_sec = :elapsed_sec,
                remaining_session_sec = :remaining_sec,
                gated = :gated
            where id = :turn_id
        """),
        {
            "turn_id": turn_id,
            "elapsed_sec": elapsed_sec,
            "remaining_sec": remaining_sec,
            "gated": gated,
        },
    )

def set_turn_transcript(conn, turn_id: str, transcript: str | None, confidence: float | None):
    conn.execute(
        text("""
            update turns
            set transcript = :transcript,
                transcript_confidence = :confidence
            where id = :turn_id
        """),
        {
            "turn_id": turn_id,
            "transcript": transcript,
            "confidence": confidence,
        },
    )