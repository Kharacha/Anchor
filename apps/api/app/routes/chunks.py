import logging
from fastapi import APIRouter, Request, HTTPException, UploadFile, File

from app.schemas.chunks import (
    StartTurnResponse,
    AppendChunkRequest,
    AppendChunkResponse,
    FinalizeTurnRequest,
    FinalizeTurnResponse,
    SafetyResult,
    AudioUploadResponse,
)
from app.services.chunks_service import start_turn, append_chunk, finalize_turn
from app.services.transcription_service import transcribe_upload_file
from app.repos import turns_repo

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1", tags=["chunks"])


@router.post("/sessions/{session_id}/turns/start", response_model=StartTurnResponse)
def start_turn_route(session_id: str, request: Request):
    try:
        engine = request.app.state.engine
        policy_version = request.app.state.policy_version
        model_version = request.app.state.model_version

        turn_id, turn_index = start_turn(engine, session_id, policy_version, model_version)
        return StartTurnResponse(turn_id=turn_id, turn_index=turn_index)

    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"{type(e).__name__}: {str(e)}")


@router.post("/sessions/{session_id}/turns/{turn_id}/chunks", response_model=AppendChunkResponse)
def append_chunk_route(session_id: str, turn_id: str, body: AppendChunkRequest, request: Request):
    try:
        engine = request.app.state.engine

        seq = append_chunk(
            engine,
            session_id=session_id,
            turn_id=turn_id,
            chunk_index=body.chunk_index,
            text=body.text,
            confidence=body.confidence,
        )
        return AppendChunkResponse(ok=True, seq=seq)

    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"{type(e).__name__}: {str(e)}")


@router.post("/sessions/{session_id}/turns/{turn_id}/finalize", response_model=FinalizeTurnResponse)
def finalize_turn_route(session_id: str, turn_id: str, body: FinalizeTurnRequest, request: Request):
    try:
        engine = request.app.state.engine
        policy_version = request.app.state.policy_version
        model_version = request.app.state.model_version

        transcript, assistant_text, safety, fallback_used, analysis = finalize_turn(
            engine,
            session_id=session_id,
            turn_id=turn_id,
            policy_version=policy_version,
            model_version=model_version,
        )

        return FinalizeTurnResponse(
            turn_id=turn_id,
            transcript=transcript,
            assistant_text=assistant_text,
            input_safety=SafetyResult(**safety),
            fallback_used=fallback_used,
            analysis=analysis,
        )

    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"{type(e).__name__}: {str(e)}")


# -------------------------------
# NEW: Audio upload -> transcription
# -------------------------------
@router.post(
    "/sessions/{session_id}/turns/{turn_id}/audio",
    response_model=AudioUploadResponse,
)
def upload_audio(session_id: str, turn_id: str, request: Request, file: UploadFile = File(...)):
    """
    Accepts multipart/form-data with a single file field named 'file'.
    Returns stable schema:
      { "transcript": str, "confidence": float|null, "content_type": str|null, "bytes": int|null }
    """
    try:
        engine = request.app.state.engine

        # (3) Validate turn belongs to session
        with engine.begin() as conn:
            ok = turns_repo.turn_belongs_to_session(conn, turn_id=turn_id, session_id=session_id)
        if not ok:
            raise HTTPException(status_code=404, detail="turn not found for this session")

        # Log basic file metadata
        content_type = getattr(file, "content_type", None)
        filename = getattr(file, "filename", None)

        # Compute size without reading whole file into memory
        size_bytes = None
        try:
            file.file.seek(0, 2)
            size_bytes = int(file.file.tell())
            file.file.seek(0)
        except Exception:
            pass

        logger.info(f"/audio upload: session={session_id} turn={turn_id} filename={filename} type={content_type} bytes={size_bytes}")

        # (2) Empty / tiny audio guard (common when recorder didn't capture)
        if size_bytes is not None and size_bytes < 4000:
            return AudioUploadResponse(transcript="", confidence=None, content_type=content_type, bytes=size_bytes)

        transcript, conf = transcribe_upload_file(file)

        return AudioUploadResponse(
            transcript=transcript or "",
            confidence=conf,
            content_type=content_type,
            bytes=size_bytes,
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.exception("audio upload failed")
        raise HTTPException(status_code=500, detail=f"{type(e).__name__}: {str(e)}")
