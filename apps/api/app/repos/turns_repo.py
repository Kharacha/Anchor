from sqlalchemy import text



def insert_turn(conn, session_id: str, request_id: str | None):
    row = conn.execute(
        text("""
            -- Serialize turn starts per session
            select 1
            from sessions
            where id = cast(:session_id as uuid)
            for update
        """),
        {"session_id": session_id},
    ).first()

    if row is None:
        raise ValueError("session not found")

    turn_id = conn.execute(
        text("""
            insert into turns (
              session_id,
              turn_index,
              request_id
            )
            values (
              cast(:session_id as uuid),
              (
                select coalesce(max(t.turn_index), -1) + 1
                from turns t
                where t.session_id = cast(:session_id as uuid)
              ),
              :request_id
            )
            returning id
        """),
        {"session_id": session_id, "request_id": request_id},
    ).scalar_one()

    return turn_id


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

def set_utterance_scores(conn, utterance_id: str, valence: float, arousal: float, confidence: float, extremeness: float):
    conn.execute(
        text("""
            update utterances
            set valence = :valence,
                arousal = :arousal,
                confidence = :confidence,
                extremeness = :extremeness
            where id = :utterance_id
        """),
        {
            "utterance_id": utterance_id,
            "valence": valence,
            "arousal": arousal,
            "confidence": confidence,
            "extremeness": extremeness,
        },
    )

def get_turn_index(conn, turn_id: str) -> int:
    return conn.execute(
        text("select turn_index from turns where id = :turn_id"),
        {"turn_id": turn_id},
    ).scalar_one()

def turn_belongs_to_session(conn, turn_id: str, session_id: str) -> bool:
    row = conn.execute(
        text("select 1 from turns where id = :turn_id and session_id = :session_id"),
        {"turn_id": turn_id, "session_id": session_id},
    ).first()
    return row is not None

def list_user_chunks(conn, session_id: str, turn_id: str):
    """
    Returns list of dicts: {id, chunk_index, text}
    Only user utterances that represent chunks (chunk_index IS NOT NULL).
    """
    return conn.execute(
        text("""
            select id, chunk_index, text
            from utterances
            where session_id = :session_id
              and turn_id = :turn_id
              and role = 'user'
              and chunk_index is not null
            order by chunk_index asc
        """),
        {"session_id": session_id, "turn_id": turn_id},
    ).mappings().all()

def upsert_user_chunk(
    conn,
    session_id: str,
    turn_id: str,
    chunk_index: int,
    text_content: str,
    chunk_confidence: float | None = None,
):
    """
    Idempotent chunk write:
    - if chunk_index already exists for this turn, overwrite its text (+ confidence)
    - else insert a new utterance row with that chunk_index (+ confidence)
    Returns: (utterance_id, seq)
    """
    # Try update first
    updated = conn.execute(
        text("""
            update utterances
            set text = :text,
                chunk_confidence = :chunk_confidence
            where session_id = :session_id
              and turn_id = :turn_id
              and role = 'user'
              and chunk_index = :chunk_index
            returning id, seq
        """),
        {
            "session_id": session_id,
            "turn_id": turn_id,
            "chunk_index": chunk_index,
            "text": text_content,
            "chunk_confidence": chunk_confidence,
        },
    ).first()

    if updated:
        return str(updated[0]), int(updated[1])

    # Insert if missing
    utt_id = insert_utterance(
        conn,
        session_id=session_id,
        turn_id=turn_id,
        role="user",
        text_content=text_content,
        chunk_index=chunk_index,
    )

    # Set confidence after insert (keeps insert_utterance signature stable)
    conn.execute(
        text("""
            update utterances
            set chunk_confidence = :chunk_confidence
            where id = :id
        """),
        {"id": utt_id, "chunk_confidence": chunk_confidence},
    )

    seq = conn.execute(
        text("select seq from utterances where id = :id"),
        {"id": utt_id},
    ).scalar_one()

    return str(utt_id), int(seq)



def get_turn_transcript(conn, turn_id: str) -> str | None:
    return conn.execute(
        text("select transcript from turns where id = :turn_id"),
        {"turn_id": turn_id},
    ).scalar_one_or_none()

def get_turn_gated(conn, turn_id: str) -> bool:
    return bool(conn.execute(
        text("select gated from turns where id = :turn_id"),
        {"turn_id": turn_id},
    ).scalar_one())

def get_existing_assistant_for_turn(conn, session_id: str, turn_id: str):
    """
    Returns dict or None:
      { final_text: str, fallback_used: bool, fallback_type: str|None }
    """
    row = conn.execute(
        text("""
            select final_text, fallback_used, fallback_type
            from assistant_messages
            where session_id = :session_id and turn_id = :turn_id
            order by created_at asc
            limit 1
        """),
        {"session_id": session_id, "turn_id": turn_id},
    ).mappings().first()
    return row

def get_existing_full_user_utterance(conn, session_id: str, turn_id: str):
    """
    The canonical stitched user utterance we create at finalize time:
    role='user' and chunk_index is null
    """
    row = conn.execute(
        text("""
            select id
            from utterances
            where session_id = :session_id
              and turn_id = :turn_id
              and role = 'user'
              and chunk_index is null
            order by created_at asc
            limit 1
        """),
        {"session_id": session_id, "turn_id": turn_id},
    ).first()
    return str(row[0]) if row else None
