# apps/api/app/services/turns_ingest_service.py

from __future__ import annotations

import datetime
from typing import Any, Dict, Optional

from sqlalchemy import text

from app.repos import (
    turns_repo,
    sessions_repo,
    safety_repo,
    audit_repo,
    user_settings_repo,
    trends_repo,
)
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


def _clamp01(x: Optional[float]) -> Optional[float]:
    if x is None:
        return None
    try:
        v = float(x)
    except Exception:
        return None
    return max(0.0, min(1.0, v))


def _get_privacy_flags(conn, user_id: str) -> tuple[bool, bool]:
    """
    Returns (store_transcripts, no_transcript_mode)

    If your user_settings_repo doesn’t have these yet, default to:
      store_transcripts=True, no_transcript_mode=False
    """
    get_priv = getattr(user_settings_repo, "get_privacy_flags", None)
    if callable(get_priv):
        try:
            return get_priv(conn, user_id)
        except Exception:
            pass
    return True, False


def ingest_transcript_turn(
    engine,
    *,
    session_id: str,
    transcript_text: str,
    transcript_confidence: float | None,
    speech_features: Dict[str, Any] | None,
    stt_provider_used: str,
    fallback_used: bool,
    policy_version: str,
    model_version: str,
) -> Dict[str, Any]:
    transcript = (transcript_text or "").strip()
    if not transcript:
        raise ValueError("transcript_text cannot be empty")

    tc = _clamp01(transcript_confidence)

    with engine.begin() as conn:
        timing = sessions_repo.get_session_timing(conn, session_id)
        if not timing:
            raise ValueError("session not found")

        status, max_sec, _started_at, elapsed_sec, remaining_sec = timing
        gated = (status != "active") or (remaining_sec <= 0)

        # Create turn
        turn_id_uuid = turns_repo.insert_turn(conn, session_id=session_id, request_id=None)
        turn_id = str(turn_id_uuid)

        # Attach timing
        turns_repo.set_turn_timing(
            conn,
            turn_id=turn_id,
            elapsed_sec=elapsed_sec,
            remaining_sec=remaining_sec,
            gated=gated,
        )

        # Resolve user
        user_id_uuid = sessions_repo.get_session_user_id(conn, session_id)
        if not user_id_uuid:
            raise ValueError("session not found (or missing user)")
        user_id = str(user_id_uuid)

        ensure_fn = getattr(user_settings_repo, "ensure_user_settings_row", None)
        if callable(ensure_fn):
            ensure_fn(conn, user_id)

        _personalization_opt_in, baseline_opt_in = user_settings_repo.get_user_settings_flags(conn, user_id)
        store_transcripts, no_transcript_mode = _get_privacy_flags(conn, user_id)

        # Extract cheap features
        duration_ms = None
        speech_rate = None
        pause_ratio = None
        if isinstance(speech_features, dict):
            duration_ms = speech_features.get("duration_ms")
            speech_rate = speech_features.get("speech_rate")
            pause_ratio = _clamp01(speech_features.get("pause_ratio"))

        # Determine whether we store transcript text in DB at all
        should_store_transcript = bool(store_transcripts) and not bool(no_transcript_mode)
        transcript_for_storage = transcript if should_store_transcript else None

        # Store turn metadata fields
        conn.execute(
            text("""
                update turns
                set
                  input_mode = :input_mode,
                  transcript_confidence = :tc,
                  duration_ms = :duration_ms,
                  speech_rate = :speech_rate,
                  pause_ratio = :pause_ratio,
                  stt_provider_used = :stt_provider_used,
                  fallback_used = :fallback_used,
                  transcript_text = :transcript_text
                where id = cast(:turn_id as uuid)
            """),
            {
                "turn_id": turn_id,
                "input_mode": "voice" if stt_provider_used in ("on_device", "self_hosted") else "text",
                "tc": tc,
                "duration_ms": int(duration_ms) if isinstance(duration_ms, int) else None,
                "speech_rate": float(speech_rate) if isinstance(speech_rate, (int, float)) else None,
                "pause_ratio": float(pause_ratio) if isinstance(pause_ratio, (int, float)) else None,
                "stt_provider_used": stt_provider_used,
                "fallback_used": bool(fallback_used),
                "transcript_text": transcript_for_storage,
            },
        )

        # Audit: turn received (NO transcript)
        if not audit_repo.audit_event_exists(conn, session_id=session_id, event_type="turn_received", turn_id=turn_id):
            audit_repo.insert_audit(
                conn,
                session_id=session_id,
                event_type="turn_received",
                data_json=to_json({"turn_id": turn_id, "mode": "transcript_ingest"}),
                policy_version=policy_version,
                model_version=model_version,
                turn_id=turn_id,
            )

        # Insert user utterance row (store transcript only if allowed)
        full_user_utt_id = turns_repo.insert_utterance(
            conn,
            session_id=session_id,
            turn_id=turn_id,
            role="user",
            text_content=(transcript if should_store_transcript else ""),
            chunk_index=None,
        )

        # Score always uses transcript in-memory
        scores = score_text(transcript, chunk_confidences=None)
        turns_repo.set_utterance_scores(
            conn,
            utterance_id=full_user_utt_id,
            valence=scores["valence"],
            arousal=scores["arousal"],
            confidence=scores["confidence"],
            extremeness=scores["extremeness"],
        )

        # Audit: stt complete (NO transcript)
        if not audit_repo.audit_event_exists(conn, session_id=session_id, event_type="stt_complete", turn_id=turn_id):
            audit_repo.insert_audit(
                conn,
                session_id=session_id,
                event_type="stt_complete",
                data_json=to_json(
                    {
                        "turn_id": turn_id,
                        "provider": stt_provider_used,
                        "fallback_used": bool(fallback_used),
                        "confidence": tc,
                        "duration_ms": duration_ms,
                    }
                ),
                policy_version=policy_version,
                model_version=model_version,
                turn_id=turn_id,
            )

        # Audit: scores computed
        if not audit_repo.audit_event_exists(conn, session_id=session_id, event_type="scores_computed", turn_id=turn_id):
            audit_repo.insert_audit(
                conn,
                session_id=session_id,
                event_type="scores_computed",
                data_json=to_json(
                    {
                        "turn_id": turn_id,
                        "utterance_id": str(full_user_utt_id),
                        "valence": scores["valence"],
                        "arousal": scores["arousal"],
                        "confidence": scores["confidence"],
                        "extremeness": scores["extremeness"],
                        "source": scores.get("source"),
                        "error": scores.get("error"),
                    }
                ),
                policy_version=policy_version,
                model_version=model_version,
                turn_id=turn_id,
            )

        # Baseline update (opt-in)
        analysis: Dict[str, Any] = {}
        baseline_update = update_user_baseline_if_opted_in(
            conn,
            user_id=user_id,
            session_id=session_id,
            baseline_opt_in=baseline_opt_in,
            valence=scores.get("valence"),
            arousal=scores.get("arousal"),
            confidence=scores.get("confidence"),
            transcript_confidence=tc,
            # Keep your current convention: speech_rate is words/sec. Baseline uses WPM in your fn name,
            # so we pass None for now (you can convert later if desired).
            speech_rate_wpm=None,
            pause_ratio=float(pause_ratio) if isinstance(pause_ratio, (int, float)) else None,
        )
        if baseline_update:
            analysis["baseline_update"] = baseline_update
            if not audit_repo.audit_event_exists(conn, session_id=session_id, event_type="baseline_updated", turn_id=turn_id):
                audit_repo.insert_audit(
                    conn,
                    session_id=session_id,
                    event_type="baseline_updated",
                    data_json=to_json({"turn_id": turn_id, "updated": True}),
                    policy_version=policy_version,
                    model_version=model_version,
                    turn_id=turn_id,
                )

        # DAILY TRENDS (derived scores only; only if baseline_opt_in)
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

        # Gate handling
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

            return {
                "turn_id": turn_id,
                "transcript": transcript,
                "assistant_text": assistant_text,
                "input_safety": {"label": "allow", "reasons": [], "meta": {}},
                "fallback_used": True,
                "analysis": analysis or None,
            }

        # Safety
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

        # Response
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
                data_json=to_json({"turn_id": turn_id, "source": response_source, "mode": mode, "error": response_error}),
                policy_version=policy_version,
                model_version=model_version,
                turn_id=turn_id,
            )

        if not audit_repo.audit_event_exists(conn, session_id=session_id, event_type="turn_complete", turn_id=turn_id):
            audit_repo.insert_audit(
                conn,
                session_id=session_id,
                event_type="turn_complete",
                data_json=to_json({"turn_id": turn_id, "fallback_used": (response_source != "openai"), "gated": False}),
                policy_version=policy_version,
                model_version=model_version,
                turn_id=turn_id,
            )

        return {
            "turn_id": turn_id,
            "transcript": transcript,
            "assistant_text": assistant_text,
            "input_safety": safety,
            "fallback_used": (response_source != "openai") or bool(fallback_used),
            "analysis": analysis or None,
        }
