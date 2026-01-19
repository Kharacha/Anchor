from fastapi import APIRouter, Request, HTTPException

from app.schemas.chunks import (
    StartTurnResponse,
    AppendChunkRequest,
    AppendChunkResponse,
    FinalizeTurnRequest,
    FinalizeTurnResponse,
    SafetyResult,
)
from app.services.chunks_service import start_turn, append_chunk, finalize_turn


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
