# apps/api/app/routes/turns_ingest.py

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request, UploadFile, File
from app.schemas.turns_ingest import TurnIngestRequest, TurnIngestResponse
from app.services.turns_ingest_service import ingest_transcript_turn

router = APIRouter(prefix="/v1", tags=["turns"])


@router.post("/sessions/{session_id}/turns", response_model=TurnIngestResponse)
def ingest_turn_route(session_id: str, request: Request, body: TurnIngestRequest):
    """
    Transcript-only ingest (preferred).
    Privacy: NO raw audio accepted here.
    """
    try:
        engine = request.app.state.engine
        out = ingest_transcript_turn(
            engine,
            session_id=session_id,
            transcript_text=body.transcript_text,
            transcript_confidence=body.transcript_confidence,
            speech_features=(body.speech_features.model_dump() if body.speech_features else None),
            stt_provider_used=body.stt_provider_used,
            fallback_used=body.fallback_used,
            policy_version=getattr(request.app.state, "policy_version", "v1"),
            model_version=getattr(request.app.state, "model_version", "v1"),
        )
        return out

    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"{type(e).__name__}: {str(e)}")


@router.post("/sessions/{session_id}/turns/audio", response_model=TurnIngestResponse)
async def ingest_turn_audio_route(
    session_id: str,
    request: Request,
    file: UploadFile = File(...),
):
    """
    Self-hosted STT fallback.
    Requirements:
    - Do not write audio to disk
    - Do not store audio anywhere
    - Do not log payloads
    """
    try:
        engine = request.app.state.engine

        blob = await file.read()
        if not blob or len(blob) < 4000:
            raise ValueError("audio too short")

        transcribe_fn = getattr(request.app.state, "self_hosted_transcribe", None)
        if not callable(transcribe_fn):
            raise ValueError("self-hosted STT not configured on backend (self_hosted_transcribe missing)")

        stt = transcribe_fn(blob, content_type=file.content_type or "audio/webm")
        transcript_text = (stt.get("text") or "").strip()
        transcript_conf = stt.get("confidence", None)

        if not transcript_text:
            raise ValueError("empty transcript from self-hosted stt")

        out = ingest_transcript_turn(
            engine,
            session_id=session_id,
            transcript_text=transcript_text,
            transcript_confidence=(float(transcript_conf) if transcript_conf is not None else None),
            speech_features=None,
            stt_provider_used="self_hosted",
            fallback_used=True,
            policy_version=getattr(request.app.state, "policy_version", "v1"),
            model_version=getattr(request.app.state, "model_version", "v1"),
        )
        return out

    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"{type(e).__name__}: {str(e)}")
