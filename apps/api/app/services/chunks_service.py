# apps/api/app/services/chunks_service.py

from sqlalchemy import text
import re
import datetime

from app.repos import turns_repo, sessions_repo, safety_repo, audit_repo, user_settings_repo, trends_repo
from app.services.scoring_service import score_text
from app.services.safety_service import classify_input, to_json
from app.services.baselines_service import update_user_baseline_if_opted_in
from app.services.response_service import generate_assistant_response


SAFE_BLOCK_MESSAGE = (
    "I can’t help with that. If you’re in danger or thinking about harming yourself, "
    "please reach out to local emergency services or a trusted person right now."
)

SESSION_ENDED_MESSAGE = (
    "This session has ended (time limit reached). Please start a new session to continue."
)


def _chunk_conf_value(chunk: dict) -> float | None:
    if not isinstance(chunk, dict):
        return None
    c = chunk.get("confidence", None)
    if c is None:
        c = chunk.get("transcript_confidence", None)
    if c is None:
        c = chunk.get("chunk_confidence", None)
    try:
        if c is None:
            return None
        return float(c)
    except Exception:
        return None


def _compute_transcript_confidence(transcript: str, chunks: list[dict]) -> float:
    transcript = (transcript or "").strip()

    total_chars = 0
    weighted_sum = 0.0
    for c in chunks or []:
        txt = (c.get("text") or "").strip()
        if not txt:
            continue
        conf = _chunk_conf_value(c)
        conf = 0.9 if conf is None else max(0.0, min(conf, 1.0))
        n = len(txt)
        total_chars += n
        weighted_sum += conf * n

    avg_conf = (weighted_sum / total_chars) if total_chars > 0 else 0.9

    L = len(transcript)
    if L < 3:
        length_factor = 0.4
    elif L < 6:
        length_factor = 0.6
    elif L < 12:
        length_factor = 0.8
    else:
        length_factor = 1.0

    words = re.findall(r"\w+", transcript.lower())
    if not words:
        coherence_factor = 0.5
    else:
        unique_ratio = len(set(words)) / max(len(words), 1)
        coherence_factor = 0.85 if unique_ratio < 0.5 else 1.0

    conf = avg_conf * length_factor * coherence_factor
    conf = max(0.0, min(conf, 1.0))
    return round(conf, 2)


def start_turn(engine, session_id: str, policy_version: str, model_version: str):
    with engine.begin() as conn:
        timing = sessions_repo.get_session_timing(conn, session_id)
        if not timing:
            raise ValueError("session not found")

        status, _max_sec, _started_at, elapsed_sec, remaining_sec = timing
        gated = (status != "active") or (remaining_sec <= 0)

        turn_id = turns_repo.insert_turn(conn, session_id=session_id, request_id=None)
        turn_index = turns_repo.get_turn_index(conn, turn_id)

        turns_repo.set_turn_timing(
            conn,
            turn_id=turn_id,
            elapsed_sec=elapsed_sec,
            remaining_sec=remaining_sec,
            gated=gated,
        )

        if not audit_repo.audit_event_exists(
            conn, session_id=session_id, event_type="turn_received", turn_id=str(turn_id)
        ):
            audit_repo.insert_audit(
                conn,
                session_id=session_id,
                event_type="turn_received",
                data_json=to_json({"turn_id": str(turn_id), "mode": "chunked"}),
                policy_version=policy_version,
                model_version=model_version,
                turn_id=str(turn_id),
            )

    return str(turn_id), int(turn_index)


def append_chunk(engine, session_id: str, turn_id: str, chunk_index: int, text: str, confidence: float | None):
    text = (text or "").strip()
    if not text:
        raise ValueError("chunk text cannot be empty")

    with engine.begin() as conn:
        if not turns_repo.turn_belongs_to_session(conn, turn_id=turn_id, session_id=session_id):
            raise ValueError("turn not found for this session")

        _utterance_id, seq = turns_repo.upsert_user_chunk(
            conn,
            session_id=session_id,
            turn_id=turn_id,
            chunk_index=chunk_index,
            text_content=text,
            chunk_confidence=confidence,
        )

    return int(seq)


def finalize_turn(engine, session_id: str, turn_id: str, policy_version: str, model_version: str):
    with engine.begin() as conn:
        if not turns_repo.turn_belongs_to_session(conn, turn_id=turn_id, session_id=session_id):
            raise ValueError("turn not found for this session")

        claimed = conn.execute(
            text("""
                update turns
                set finalized_at = now()
                where id = cast(:turn_id as uuid)
                  and session_id = cast(:session_id as uuid)
                  and finalized_at is null
                returning id
            """),
            {"turn_id": turn_id, "session_id": session_id},
        ).first()

        if claimed is None:
            existing = turns_repo.get_existing_assistant_for_turn(conn, session_id=session_id, turn_id=turn_id)
            if existing:
                transcript = turns_repo.get_turn_transcript(conn, turn_id) or ""
                safety = safety_repo.get_latest_input_safety(conn, session_id=session_id, turn_id=turn_id)
                return transcript, existing["final_text"], safety, bool(existing["fallback_used"]), None
            raise ValueError("turn already finalized but assistant missing")

        timing = sessions_repo.get_session_timing(conn, session_id)
        if not timing:
            raise ValueError("session not found")

        status, max_sec, _started_at, elapsed_sec, remaining_sec = timing
        gated = (status != "active") or (remaining_sec <= 0)

        turns_repo.set_turn_timing(
            conn,
            turn_id=turn_id,
            elapsed_sec=elapsed_sec,
            remaining_sec=remaining_sec,
            gated=gated,
        )

        chunks = turns_repo.list_user_chunks(conn, session_id=session_id, turn_id=turn_id)
        if not chunks:
            raise ValueError("no chunks uploaded for this turn")

        parts = [c["text"] for c in chunks if (c.get("text") or "").strip()]
        transcript = " ".join(p.strip() for p in parts).strip()
        if not transcript:
            raise ValueError("final transcript is empty")

        transcript_conf = _compute_transcript_confidence(transcript, chunks)
        turns_repo.set_turn_transcript(conn, turn_id=turn_id, transcript=transcript, confidence=transcript_conf)

        if not audit_repo.audit_event_exists(conn, session_id=session_id, event_type="stt_complete", turn_id=turn_id):
            audit_repo.insert_audit(
                conn,
                session_id=session_id,
                event_type="stt_complete",
                data_json=to_json(
                    {"turn_id": turn_id, "stt_ms": 0, "confidence": transcript_conf, "chunk_count": len(chunks)}
                ),
                policy_version=policy_version,
                model_version=model_version,
                turn_id=turn_id,
            )

        full_user_utt_id = turns_repo.get_existing_full_user_utterance(conn, session_id=session_id, turn_id=turn_id)
        if not full_user_utt_id:
            full_user_utt_id = turns_repo.insert_utterance(
                conn,
                session_id=session_id,
                turn_id=turn_id,
                role="user",
                text_content=transcript,
                chunk_index=None,
            )

        # -----------------------
        # SCORING
        # -----------------------
        chunk_conf_pairs = [(c.get("text") or "", _chunk_conf_value(c)) for c in chunks]
        scores = score_text(transcript, chunk_confidences=chunk_conf_pairs)

        turns_repo.set_utterance_scores(
            conn,
            utterance_id=full_user_utt_id,
            valence=scores["valence"],
            arousal=scores["arousal"],
            confidence=scores["confidence"],
            extremeness=scores["extremeness"],
        )

        if not audit_repo.audit_event_exists(conn, session_id=session_id, event_type="scores_computed", turn_id=turn_id):
            payload = {
                "turn_id": turn_id,
                "utterance_id": str(full_user_utt_id),
                "valence": scores["valence"],
                "arousal": scores["arousal"],
                "confidence": scores["confidence"],
                "extremeness": scores["extremeness"],
                "source": scores.get("source"),
            }
            if scores.get("error"):
                payload["error"] = scores["error"]

            audit_repo.insert_audit(
                conn,
                session_id=session_id,
                event_type="scores_computed",
                data_json=to_json(payload),
                policy_version=policy_version,
                model_version=model_version,
                turn_id=turn_id,
            )

        # -----------------------
        # BASELINE UPDATE (opt-in) + analysis bundle
        # -----------------------
        analysis = {}
        baseline_update = None

        user_id = sessions_repo.get_session_user_id(conn, session_id)
        baseline_opt_in = False

        if user_id:
            user_id = str(user_id)

            ensure_fn = getattr(user_settings_repo, "ensure_user_settings_row", None)
            if callable(ensure_fn):
                ensure_fn(conn, user_id)

            _personalization_opt_in, baseline_opt_in = user_settings_repo.get_user_settings_flags(conn, user_id)

            baseline_update = update_user_baseline_if_opted_in(
                conn,
                user_id=user_id,
                session_id=session_id,
                baseline_opt_in=baseline_opt_in,
                valence=scores.get("valence"),
                arousal=scores.get("arousal"),
                confidence=scores.get("confidence"),
                transcript_confidence=transcript_conf,
            )

            if baseline_update:
                analysis["baseline_update"] = baseline_update

                # Audit baseline_updated (enum exists)
                if not audit_repo.audit_event_exists(
                    conn, session_id=session_id, event_type="baseline_updated", turn_id=turn_id
                ):
                    audit_repo.insert_audit(
                        conn,
                        session_id=session_id,
                        event_type="baseline_updated",
                        data_json=to_json({"turn_id": turn_id, "updated": True}),
                        policy_version=policy_version,
                        model_version=model_version,
                        turn_id=turn_id,
                    )

            # -----------------------
            # DAILY TRENDS (derived scores only)
            # Only update if baseline_opt_in is true (opt-in requirement).
            # -----------------------
            if baseline_opt_in:
                day = datetime.date.today().isoformat()
                trends_repo.upsert_daily_bucket(
                    conn,
                    user_id=user_id,
                    day=day,
                    valence=float(scores["valence"]),
                    arousal=float(scores["arousal"]),
                    confidence=float(scores["confidence"]),
                    extremeness=float(scores["extremeness"]),
                )

        # -----------------------
        # GATE handling
        # -----------------------
        if gated:
            assistant_text = SESSION_ENDED_MESSAGE

            safety, _ = classify_input(transcript)
            safety_repo.insert_safety_event(
                conn,
                session_id=session_id,
                turn_id=turn_id,
                stage="input",
                action="fallback",
                category="session_gate",
                severity=None,
                classification_json=to_json(safety),
                fallback_used=True,
                policy_version=policy_version,
                model_version=model_version,
            )

            turns_repo.insert_assistant_message(
                conn,
                session_id=session_id,
                turn_id=turn_id,
                final_text=assistant_text,
                policy_version=policy_version,
                model_version=model_version,
                draft_text=None,
                fallback_used=True,
                fallback_type="session_expired",
                evidence_json="{}",
            )
            turns_repo.insert_utterance(
                conn,
                session_id=session_id,
                turn_id=turn_id,
                role="assistant",
                text_content=assistant_text,
                chunk_index=0,
            )

            sessions_repo.end_session(conn, session_id)

            if not audit_repo.audit_event_exists(conn, session_id=session_id, event_type="session_end", turn_id=None):
                audit_repo.insert_audit(
                    conn,
                    session_id=session_id,
                    event_type="session_end",
                    data_json=to_json({"reason": "time_limit", "max_duration_sec": max_sec}),
                    policy_version=policy_version,
                    model_version=model_version,
                    turn_id=None,
                )

            if not audit_repo.audit_event_exists(conn, session_id=session_id, event_type="turn_complete", turn_id=turn_id):
                audit_repo.insert_audit(
                    conn,
                    session_id=session_id,
                    event_type="turn_complete",
                    data_json=to_json({"turn_id": turn_id, "fallback_used": True, "gated": True, "mode": "chunked"}),
                    policy_version=policy_version,
                    model_version=model_version,
                    turn_id=turn_id,
                )

            return transcript, assistant_text, {"label": "allow", "reasons": [], "meta": {}}, True, (analysis or None)

        # -----------------------
        # SAFETY classification (normal)
        # -----------------------
        safety, safety_fallback_used = classify_input(transcript)

        action = "allow"
        if safety.get("label") == "block":
            action = "block"
        elif safety_fallback_used:
            action = "fallback"

        safety_repo.insert_safety_event(
            conn,
            session_id=session_id,
            turn_id=turn_id,
            stage="input",
            action=action,
            category="rule_based_v1",
            severity=None,
            classification_json=to_json(safety),
            fallback_used=safety_fallback_used,
            policy_version=policy_version,
            model_version=model_version,
        )

        # -----------------------
        # RESPONSE generation
        # -----------------------
        if safety.get("label") == "block":
            assistant_text = SAFE_BLOCK_MESSAGE
            response_source = "safety_block"
            mode = "neutral"
            response_error = None
        else:
            resp = generate_assistant_response(
                transcript=transcript,
                safety=safety,
                scores=scores,
                baseline_update=baseline_update,
            )
            assistant_text = resp["assistant_text"]
            response_source = resp.get("source", "fallback")
            mode = resp.get("mode", "neutral")
            response_error = resp.get("error")

        analysis["mode"] = mode
        analysis["response_source"] = response_source
        if response_error:
            analysis["response_error"] = response_error

        turns_repo.insert_assistant_message(
            conn,
            session_id=session_id,
            turn_id=turn_id,
            final_text=assistant_text,
            policy_version=policy_version,
            model_version=model_version,
            draft_text=None,
            fallback_used=(response_source != "openai"),
            fallback_type=(
                "safety_block"
                if safety.get("label") == "block"
                else ("llm_fallback" if response_source != "openai" else None)
            ),
            evidence_json="{}",
        )
        turns_repo.insert_utterance(
            conn,
            session_id=session_id,
            turn_id=turn_id,
            role="assistant",
            text_content=assistant_text,
            chunk_index=0,
        )

        if not audit_repo.audit_event_exists(conn, session_id=session_id, event_type="assistant_generated", turn_id=turn_id):
            audit_repo.insert_audit(
                conn,
                session_id=session_id,
                event_type="assistant_generated",
                data_json=to_json(
                    {
                        "turn_id": turn_id,
                        "source": response_source,
                        "mode": mode,
                        "error": response_error,
                    }
                ),
                policy_version=policy_version,
                model_version=model_version,
                turn_id=turn_id,
            )

        if not audit_repo.audit_event_exists(conn, session_id=session_id, event_type="turn_complete", turn_id=turn_id):
            audit_repo.insert_audit(
                conn,
                session_id=session_id,
                event_type="turn_complete",
                data_json=to_json(
                    {"turn_id": turn_id, "fallback_used": (response_source != "openai"), "gated": False, "mode": "chunked"}
                ),
                policy_version=policy_version,
                model_version=model_version,
                turn_id=turn_id,
            )

        return transcript, assistant_text, safety, (response_source != "openai"), (analysis or None)
