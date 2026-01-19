from app.repos import turns_repo, safety_repo, audit_repo, sessions_repo
from app.services.safety_service import classify_input, to_json
from app.services.scoring_service import score_text


SAFE_BLOCK_MESSAGE = (
    "I can’t help with that. If you’re in danger or thinking about harming yourself, "
    "please reach out to local emergency services or a trusted person right now."
)

SESSION_ENDED_MESSAGE = (
    "This session has ended (time limit reached). Please start a new session to continue."
)


def create_turn(engine, session_id: str, user_text: str, policy_version: str, model_version: str):
    user_text = (user_text or "").strip()
    if not user_text:
        raise ValueError("text cannot be empty")

    # stubbed assistant; later replaced by real model call
    assistant_text = "Got it. (v1 stub response)"

    with engine.begin() as conn:
        timing = sessions_repo.get_session_timing(conn, session_id)
        if not timing:
            raise ValueError("session not found")

        status, max_sec, _started_at, elapsed_sec, remaining_sec = timing
        gated = (status != "active") or (remaining_sec <= 0)

        # Create turn row first (auditability)
        turn_id = turns_repo.insert_turn(conn, session_id=session_id)
        turns_repo.set_turn_timing(
            conn,
            turn_id=turn_id,
            elapsed_sec=elapsed_sec,
            remaining_sec=remaining_sec,
            gated=gated,
        )

        # Log "turn_received" as the first pipeline event (ordering)
        audit_repo.insert_audit(
            conn,
            session_id=session_id,
            event_type="turn_received",
            data_json=to_json({"turn_id": turn_id}),
            policy_version=policy_version,
            model_version=model_version,
        )

        # STT placeholder: treat provided text as transcript for now
        turns_repo.set_turn_transcript(conn, turn_id=turn_id, transcript=user_text, confidence=1.0)

        audit_repo.insert_audit(
            conn,
            session_id=session_id,
            event_type="stt_complete",
            data_json=to_json({"turn_id": turn_id, "stt_ms": 0, "confidence": 1.0}),
            policy_version=policy_version,
            model_version=model_version,
        )

        # Insert user utterance (canonical timeline)
        user_utt_id = turns_repo.insert_utterance(
            conn,
            session_id=session_id,
            turn_id=turn_id,
            role="user",
            text_content=user_text,
            chunk_index=0,
        )

        # Compute + store scores (v1 stub)
        scores = score_text(user_text)
        turns_repo.set_utterance_scores(
            conn,
            utterance_id=user_utt_id,
            valence=scores["valence"],
            arousal=scores["arousal"],
            confidence=scores["confidence"],
            extremeness=scores["extremeness"],
        )

        audit_repo.insert_audit(
            conn,
            session_id=session_id,
            event_type="scores_computed",
            data_json=to_json({"turn_id": turn_id, "utterance_id": user_utt_id, **scores}),
            policy_version=policy_version,
            model_version=model_version,
        )

        # If gated: reply + end session, but still log safety + completion for auditability
        if gated:
            assistant_text = SESSION_ENDED_MESSAGE

            # Safety input event (visibility + enum alignment)
            safety, _fallback_used = classify_input(user_text)

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

            audit_repo.insert_audit(
                conn,
                session_id=session_id,
                event_type="safety_input",
                data_json=to_json({"turn_id": turn_id, "action": "fallback", "category": "session_gate"}),
                policy_version=policy_version,
                model_version=model_version,
            )

            # Model step is skipped; still log a draft/output stage as "fallback"
            audit_repo.insert_audit(
                conn,
                session_id=session_id,
                event_type="llm_draft",
                data_json=to_json({"turn_id": turn_id, "skipped": True, "reason": "session_gate"}),
                policy_version=policy_version,
                model_version=model_version,
            )

            audit_repo.insert_audit(
                conn,
                session_id=session_id,
                event_type="safety_output",
                data_json=to_json({"turn_id": turn_id, "action": "fallback", "category": "session_gate"}),
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
            audit_repo.insert_audit(
                conn,
                session_id=session_id,
                event_type="session_end",
                data_json=to_json({"reason": "time_limit", "max_duration_sec": max_sec}),
                policy_version=policy_version,
                model_version=model_version,
            )

            audit_repo.insert_audit(
                conn,
                session_id=session_id,
                event_type="turn_complete",
                data_json=to_json({"turn_id": turn_id, "fallback_used": True, "gated": True}),
                policy_version=policy_version,
                model_version=model_version,
            )

            return str(turn_id), user_text, assistant_text, {"label": "allow", "reasons": [], "meta": {}}, True

        # Normal safety path
        safety, fallback_used = classify_input(user_text)

        action = "allow"
        if safety.get("label") == "block":
            action = "block"
        elif fallback_used:
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
            fallback_used=fallback_used,
            policy_version=policy_version,
            model_version=model_version,
        )

        audit_repo.insert_audit(
            conn,
            session_id=session_id,
            event_type="safety_input",
            data_json=to_json({"turn_id": turn_id, "action": action, "category": "rule_based_v1"}),
            policy_version=policy_version,
            model_version=model_version,
        )

        # "LLM draft" stage (stub)
        audit_repo.insert_audit(
            conn,
            session_id=session_id,
            event_type="llm_draft",
            data_json=to_json({"turn_id": turn_id, "stub": True}),
            policy_version=policy_version,
            model_version=model_version,
        )

        if safety.get("label") == "block":
            assistant_text = SAFE_BLOCK_MESSAGE

        # "Safety output" stage (stub allow unless blocked)
        out_action = "allow" if safety.get("label") != "block" else "block"
        audit_repo.insert_audit(
            conn,
            session_id=session_id,
            event_type="safety_output",
            data_json=to_json({"turn_id": turn_id, "action": out_action, "stub": True}),
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
            fallback_used=fallback_used,
            fallback_type="safety_block" if safety.get("label") == "block" else None,
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

        audit_repo.insert_audit(
            conn,
            session_id=session_id,
            event_type="turn_complete",
            data_json=to_json({"turn_id": turn_id, "fallback_used": fallback_used, "gated": False}),
            policy_version=policy_version,
            model_version=model_version,
        )

    return str(turn_id), user_text, assistant_text, safety, fallback_used
